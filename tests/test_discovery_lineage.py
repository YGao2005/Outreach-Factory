"""Unit tests for orchestrator/discovery_lineage.py per ADR-0036.

Coverage per the ADR-0036 D167 + D168 + D170 contracts:

* :class:`DiscoveryLineage` construction-time invariants (enum-check;
  sha256-prefix check; ISO 8601 UTC check; non-empty source_list).
* :func:`build_discovery_lineage_dict` + :func:`parse_discovery_lineage_dict`
  round-trip (D167's factories).
* :func:`normalize_legacy_source_to_skill` mapping + the manual floor.
* :func:`compute_canonical_raw_input_hash` determinism + the
  ``sha256:<hex>`` prefix convention.
* :func:`build_enrolled_source_skill_backfill_payload` shape per D170.
* The canonical ``SOURCE_SKILLS`` re-export from ``discovery_dedup.py``.
* The CLI's ``validate`` + ``backfill`` subcommands smoke-tested.

Migration coverage (vault/0005 + ledger/0007) lives in
``tests/test_migrations_vault_005.py`` + ``tests/test_migrations_ledger_007.py``
respectively (the runner-substrate tests live in
``tests/test_migrations_runner.py`` per the Pillar B Week 3 convention).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import discovery_lineage
from discovery_lineage import (
    BACKFILL_EVENT_TYPE,
    CHANNEL_VALUE,
    DiscoveryLineage,
    EMITTED_BY,
    LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL,
    SOURCE_SKILLS,
    build_discovery_lineage_dict,
    build_enrolled_source_skill_backfill_payload,
    compute_canonical_raw_input_hash,
    normalize_legacy_source_to_skill,
    parse_discovery_lineage_dict,
)


# Shared fixtures ------------------------------------------------------------


VALID_SKILL = "find-funded-founders"
VALID_LIST = "[[2026-05-13-funded-founders]]"
VALID_TS = "2026-05-13T10:00:00Z"
VALID_HASH = "sha256:" + "a" * 64


def _valid_lineage(**overrides) -> DiscoveryLineage:
    """Return a valid :class:`DiscoveryLineage` with optional field overrides."""
    fields = {
        "source_skill": VALID_SKILL,
        "source_list": VALID_LIST,
        "scraped_at": VALID_TS,
        "raw_input_hash": VALID_HASH,
    }
    fields.update(overrides)
    return DiscoveryLineage(**fields)


# ---------------------------------------------------------------------------
# DiscoveryLineage invariants — D167 construction-time validation
# ---------------------------------------------------------------------------


class TestDiscoveryLineageInvariants:
    """Per ADR-0036 D167 — the frozen dataclass refuses-loud on every
    invariant violation at construction time."""

    def test_happy_path_construction(self):
        lineage = _valid_lineage()
        assert lineage.source_skill == VALID_SKILL
        assert lineage.source_list == VALID_LIST
        assert lineage.scraped_at == VALID_TS
        assert lineage.raw_input_hash == VALID_HASH

    def test_all_source_skills_construct(self):
        """Every value in SOURCE_SKILLS must construct successfully."""
        for skill in sorted(SOURCE_SKILLS):
            _valid_lineage(source_skill=skill)  # raises on failure

    def test_unknown_source_skill_refuses_loud(self):
        with pytest.raises(ValueError, match="not in SOURCE_SKILLS"):
            _valid_lineage(source_skill="bogus")

    def test_none_source_skill_refuses_loud(self):
        with pytest.raises(ValueError, match="not in SOURCE_SKILLS"):
            _valid_lineage(source_skill=None)

    def test_empty_source_skill_refuses_loud(self):
        with pytest.raises(ValueError, match="not in SOURCE_SKILLS"):
            _valid_lineage(source_skill="")

    def test_empty_source_list_refuses_loud(self):
        with pytest.raises(ValueError, match="source_list must be a non-empty string"):
            _valid_lineage(source_list="")

    def test_whitespace_source_list_refuses_loud(self):
        with pytest.raises(ValueError, match="source_list must be a non-empty string"):
            _valid_lineage(source_list="   \t\n  ")

    def test_none_source_list_refuses_loud(self):
        with pytest.raises(ValueError, match="source_list must be a non-empty string"):
            _valid_lineage(source_list=None)

    def test_non_string_source_list_refuses_loud(self):
        with pytest.raises(ValueError, match="source_list must be a non-empty string"):
            _valid_lineage(source_list=42)

    def test_scraped_at_valid_canonical_form(self):
        """``YYYY-MM-DDTHH:MM:SSZ`` is the canonical form."""
        _valid_lineage(scraped_at="2026-05-13T10:00:00Z")
        _valid_lineage(scraped_at="2026-12-31T23:59:59Z")

    def test_scraped_at_valid_fractional_seconds(self):
        """Fractional seconds are tolerated."""
        _valid_lineage(scraped_at="2026-05-13T10:00:00.123Z")
        _valid_lineage(scraped_at="2026-05-13T10:00:00.000001Z")

    def test_scraped_at_valid_explicit_offset(self):
        """Explicit ``+00:00`` offset is tolerated (canonical UTC variant)."""
        _valid_lineage(scraped_at="2026-05-13T10:00:00+00:00")

    def test_scraped_at_naive_refuses_loud(self):
        """Naive timestamp (no Z, no offset) is refused."""
        with pytest.raises(ValueError, match="scraped_at must be ISO 8601 UTC"):
            _valid_lineage(scraped_at="2026-05-13T10:00:00")

    def test_scraped_at_non_utc_offset_refuses_loud(self):
        """Non-UTC offsets are refused — canonical form is UTC."""
        with pytest.raises(ValueError, match="scraped_at must be ISO 8601 UTC"):
            _valid_lineage(scraped_at="2026-05-13T10:00:00-08:00")

    def test_scraped_at_date_only_refuses_loud(self):
        with pytest.raises(ValueError, match="scraped_at must be ISO 8601 UTC"):
            _valid_lineage(scraped_at="2026-05-13")

    def test_scraped_at_garbage_refuses_loud(self):
        with pytest.raises(ValueError, match="scraped_at must be ISO 8601 UTC"):
            _valid_lineage(scraped_at="not-a-date")

    def test_scraped_at_none_refuses_loud(self):
        with pytest.raises(ValueError, match="scraped_at must be ISO 8601 UTC"):
            _valid_lineage(scraped_at=None)

    def test_raw_input_hash_valid_lower_hex(self):
        _valid_lineage(raw_input_hash="sha256:" + "0" * 64)
        _valid_lineage(raw_input_hash="sha256:" + "f" * 64)

    def test_raw_input_hash_valid_mixed_case(self):
        """Upper-case hex is tolerated (the canonical form is lower)."""
        _valid_lineage(raw_input_hash="sha256:" + "AbCdEf" + "0" * 58)

    def test_raw_input_hash_missing_prefix_refuses_loud(self):
        with pytest.raises(ValueError, match="raw_input_hash must be"):
            _valid_lineage(raw_input_hash="a" * 64)

    def test_raw_input_hash_wrong_prefix_refuses_loud(self):
        with pytest.raises(ValueError, match="raw_input_hash must be"):
            _valid_lineage(raw_input_hash="md5:" + "a" * 64)

    def test_raw_input_hash_short_hex_refuses_loud(self):
        with pytest.raises(ValueError, match="raw_input_hash must be"):
            _valid_lineage(raw_input_hash="sha256:" + "a" * 32)

    def test_raw_input_hash_long_hex_refuses_loud(self):
        with pytest.raises(ValueError, match="raw_input_hash must be"):
            _valid_lineage(raw_input_hash="sha256:" + "a" * 128)

    def test_raw_input_hash_non_hex_refuses_loud(self):
        with pytest.raises(ValueError, match="raw_input_hash must be"):
            _valid_lineage(raw_input_hash="sha256:" + "g" * 64)

    def test_raw_input_hash_none_refuses_loud(self):
        with pytest.raises(ValueError, match="raw_input_hash must be"):
            _valid_lineage(raw_input_hash=None)

    def test_frozen_dataclass_is_immutable(self):
        """The frozen dataclass cannot be mutated after construction."""
        lineage = _valid_lineage()
        with pytest.raises(Exception):  # FrozenInstanceError
            lineage.source_skill = "manual"

    def test_frozen_dataclass_is_hashable(self):
        lineage = _valid_lineage()
        # The frozen dataclass is hashable + comparable.
        assert hash(lineage) == hash(_valid_lineage())
        assert lineage == _valid_lineage()

    def test_error_message_names_adr_anchor(self):
        """Error messages name the ADR anchor for operator debuggability."""
        try:
            _valid_lineage(source_skill="bogus")
        except ValueError as exc:
            assert "ADR-0032 D142" in str(exc)


# ---------------------------------------------------------------------------
# Frontmatter serialization round-trip
# ---------------------------------------------------------------------------


class TestBuildAndParse:

    def test_build_returns_canonical_key_order(self):
        """D167 pins the key order: source_skill + source_list + scraped_at + raw_input_hash."""
        d = build_discovery_lineage_dict(_valid_lineage())
        assert list(d.keys()) == [
            "source_skill", "source_list", "scraped_at", "raw_input_hash",
        ]

    def test_build_includes_all_four_fields(self):
        d = build_discovery_lineage_dict(_valid_lineage())
        assert d["source_skill"] == VALID_SKILL
        assert d["source_list"] == VALID_LIST
        assert d["scraped_at"] == VALID_TS
        assert d["raw_input_hash"] == VALID_HASH

    def test_build_refuses_non_dataclass(self):
        """The factory enforces the construction-time-validated input."""
        with pytest.raises(TypeError, match="expects a DiscoveryLineage"):
            build_discovery_lineage_dict({"source_skill": "manual"})

    def test_parse_returns_none_on_none(self):
        assert parse_discovery_lineage_dict(None) is None

    def test_parse_round_trip(self):
        original = _valid_lineage()
        d = build_discovery_lineage_dict(original)
        parsed = parse_discovery_lineage_dict(d)
        assert parsed == original

    def test_parse_refuses_non_dict(self):
        with pytest.raises(ValueError, match="must be a dict"):
            parse_discovery_lineage_dict("not-a-dict")
        with pytest.raises(ValueError, match="must be a dict"):
            parse_discovery_lineage_dict(42)

    def test_parse_missing_field_propagates_dataclass_validation(self):
        """Missing fields trigger the dataclass's loud refusal."""
        with pytest.raises(ValueError):
            parse_discovery_lineage_dict({
                "source_skill": "manual",
                "source_list": VALID_LIST,
                "scraped_at": VALID_TS,
                # raw_input_hash missing
            })

    def test_parse_ignores_extra_fields_forward_compat(self):
        """Future schema extensions land additively; the parser ignores extras."""
        d = build_discovery_lineage_dict(_valid_lineage())
        d["future_field"] = "extension"
        parsed = parse_discovery_lineage_dict(d)
        assert parsed == _valid_lineage()


# ---------------------------------------------------------------------------
# Legacy normalization — the rename trajectory
# ---------------------------------------------------------------------------


class TestNormalizeLegacySource:

    def test_canonical_legacy_mappings(self):
        assert normalize_legacy_source_to_skill("find-leads") == "find-leads"
        assert normalize_legacy_source_to_skill("funded-founders") == "find-funded-founders"
        assert normalize_legacy_source_to_skill("competitor-customers") == "competitor-customers"
        assert normalize_legacy_source_to_skill("research-prospect") == "research-prospect"
        assert normalize_legacy_source_to_skill("manual") == "manual"

    def test_canonical_form_also_maps(self):
        """Operators who pre-wrote the canonical form get the canonical form back."""
        assert normalize_legacy_source_to_skill("find-funded-founders") == "find-funded-founders"

    def test_unknown_value_falls_to_manual(self):
        """The §Existing-operator seed floor — unknown → manual."""
        assert normalize_legacy_source_to_skill("scraping-via-rapidapi") == "manual"
        assert normalize_legacy_source_to_skill("legacy-csv-import") == "manual"

    def test_none_falls_to_manual(self):
        assert normalize_legacy_source_to_skill(None) == "manual"

    def test_empty_string_falls_to_manual(self):
        assert normalize_legacy_source_to_skill("") == "manual"

    def test_mapping_is_total_for_source_skills(self):
        """Every canonical SOURCE_SKILLS value is reachable via the mapping."""
        targets = set(LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL.values())
        assert targets == SOURCE_SKILLS

    def test_all_mapping_targets_in_source_skills(self):
        """No mapping points outside the canonical enum."""
        for legacy, canonical in LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL.items():
            assert canonical in SOURCE_SKILLS, (
                f"Mapping {legacy!r} → {canonical!r} points outside "
                f"SOURCE_SKILLS — break the canonical contract"
            )


# ---------------------------------------------------------------------------
# Canonical raw-input hash
# ---------------------------------------------------------------------------


class TestComputeCanonicalRawInputHash:

    def test_returns_sha256_prefixed_lower_hex(self):
        h = compute_canonical_raw_input_hash("hello world")
        assert h.startswith("sha256:")
        assert len(h) == len("sha256:") + 64
        # All lower-case + hex.
        tail = h[len("sha256:"):]
        assert tail == tail.lower()
        int(tail, 16)  # raises if non-hex

    def test_deterministic_for_same_input(self):
        a = compute_canonical_raw_input_hash("test input")
        b = compute_canonical_raw_input_hash("test input")
        assert a == b

    def test_different_input_produces_different_hash(self):
        a = compute_canonical_raw_input_hash("input a")
        b = compute_canonical_raw_input_hash("input b")
        assert a != b

    def test_accepts_str_and_bytes_equivalently(self):
        s_hash = compute_canonical_raw_input_hash("test")
        b_hash = compute_canonical_raw_input_hash(b"test")
        assert s_hash == b_hash

    def test_output_passes_dataclass_validation(self):
        """The computed hash satisfies the DiscoveryLineage invariant."""
        h = compute_canonical_raw_input_hash("test")
        # Construct a lineage with this hash — must not raise.
        _valid_lineage(raw_input_hash=h)

    def test_known_value(self):
        """Pin a known hash to detect accidental algorithm changes."""
        h = compute_canonical_raw_input_hash("test")
        # Computed independently via openssl sha256:
        assert h == ("sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b8"
                     "22cd15d6c15b0f00a08")


# ---------------------------------------------------------------------------
# Ledger backfill event factory — D170
# ---------------------------------------------------------------------------


class TestBuildEnrolledSourceSkillBackfillPayload:

    def test_happy_path_shape(self):
        ev = build_enrolled_source_skill_backfill_payload(
            person_id="dylan-li",
            source_skill="find-funded-founders",
            backfill_of_ts="2026-05-13T10:00:00Z",
            migration_id="0007_backfill_enrolled_source_skill",
        )
        assert ev["type"] == BACKFILL_EVENT_TYPE
        assert ev["type"] == "enrolled_source_skill_backfill"
        assert ev["person_id"] == "dylan-li"
        assert ev["source_skill"] == "find-funded-founders"
        assert ev["_backfill_of_ts"] == "2026-05-13T10:00:00Z"
        assert ev["_recovered_by"] == "migration_0007_backfill_enrolled_source_skill"
        assert ev["channel"] == "none"
        assert ev["channel"] == CHANNEL_VALUE
        assert ev["_emitted_by"] == "discovery_lineage"
        assert ev["_emitted_by"] == EMITTED_BY

    def test_unknown_source_skill_refuses_loud(self):
        with pytest.raises(ValueError, match="not in SOURCE_SKILLS"):
            build_enrolled_source_skill_backfill_payload(
                person_id="dylan-li",
                source_skill="bogus",
                backfill_of_ts="2026-05-13T10:00:00Z",
                migration_id="0007_backfill_enrolled_source_skill",
            )

    def test_empty_person_id_refuses_loud(self):
        with pytest.raises(ValueError, match="person_id must be"):
            build_enrolled_source_skill_backfill_payload(
                person_id="",
                source_skill="manual",
                backfill_of_ts="2026-05-13T10:00:00Z",
                migration_id="0007_backfill_enrolled_source_skill",
            )

    def test_invalid_backfill_ts_refuses_loud(self):
        with pytest.raises(ValueError, match="backfill_of_ts must be ISO 8601 UTC"):
            build_enrolled_source_skill_backfill_payload(
                person_id="dylan-li",
                source_skill="manual",
                backfill_of_ts="not-a-timestamp",
                migration_id="0007_backfill_enrolled_source_skill",
            )

    def test_empty_migration_id_refuses_loud(self):
        with pytest.raises(ValueError, match="migration_id must be"):
            build_enrolled_source_skill_backfill_payload(
                person_id="dylan-li",
                source_skill="manual",
                backfill_of_ts="2026-05-13T10:00:00Z",
                migration_id="",
            )

    def test_channel_is_channel_agnostic_none(self):
        """Per ADR-0014 D33 the lineage primitive's events are channel-agnostic."""
        ev = build_enrolled_source_skill_backfill_payload(
            person_id="dylan-li",
            source_skill="manual",
            backfill_of_ts="2026-05-13T10:00:00Z",
            migration_id="0007_test",
        )
        assert ev["channel"] == "none"

    def test_payload_serializes_to_json(self):
        """The event payload must round-trip via JSON for ledger append."""
        ev = build_enrolled_source_skill_backfill_payload(
            person_id="dylan-li",
            source_skill="manual",
            backfill_of_ts="2026-05-13T10:00:00Z",
            migration_id="0007_test",
        )
        s = json.dumps(ev)
        parsed = json.loads(s)
        assert parsed == ev


# ---------------------------------------------------------------------------
# Canonical SOURCE_SKILLS re-export from discovery_dedup
# ---------------------------------------------------------------------------


class TestSourceSkillsCanonicalReexport:
    """Per ADR-0036 D167 — the SOURCE_SKILLS canonical home moves from
    discovery_dedup.py:96 (Week 2 reservation) to discovery_lineage.py
    (Week 9-11). discovery_dedup.py imports for back-compat."""

    def test_dedup_module_reexports_source_skills(self):
        """The legacy import path continues to work."""
        from discovery_dedup import SOURCE_SKILLS as dedup_skills
        from discovery_lineage import SOURCE_SKILLS as lineage_skills
        # SAME object — the dedup module imports the name.
        assert dedup_skills is lineage_skills

    def test_dedup_reexport_has_same_values(self):
        from discovery_dedup import SOURCE_SKILLS as dedup_skills
        assert dedup_skills == frozenset({
            "find-leads",
            "find-funded-founders",
            "competitor-customers",
            "research-prospect",
            "manual",
        })


# ---------------------------------------------------------------------------
# Module constants pinned
# ---------------------------------------------------------------------------


class TestModuleConstants:

    def test_source_skills_frozen(self):
        """SOURCE_SKILLS is a frozenset — operators cannot mutate."""
        with pytest.raises(AttributeError):
            SOURCE_SKILLS.add("new-skill")

    def test_source_skills_pinned_at_five_values(self):
        assert len(SOURCE_SKILLS) == 5
        assert SOURCE_SKILLS == frozenset({
            "find-leads",
            "find-funded-founders",
            "competitor-customers",
            "research-prospect",
            "manual",
        })

    def test_emitted_by_constant(self):
        assert EMITTED_BY == "discovery_lineage"

    def test_channel_value_constant(self):
        """Per ADR-0014 D33 — lineage primitive is channel-agnostic."""
        assert CHANNEL_VALUE == "none"

    def test_backfill_event_type_constant(self):
        assert BACKFILL_EVENT_TYPE == "enrolled_source_skill_backfill"


# ---------------------------------------------------------------------------
# CLI surface — validate + backfill
# ---------------------------------------------------------------------------


class TestCliValidate:

    def test_validate_happy_path(self, capsys):
        rc = discovery_lineage.main([
            "validate",
            "--source-skill", "find-leads",
            "--source-list", "[[2026-05-13-find-leads-q2]]",
            "--scraped-at", "2026-05-13T10:00:00Z",
            "--raw-input-hash", "sha256:" + "a" * 64,
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert "VALID" in captured.out

    def test_validate_json_happy_path(self, capsys):
        rc = discovery_lineage.main([
            "validate",
            "--source-skill", "find-leads",
            "--source-list", "[[test]]",
            "--scraped-at", "2026-05-13T10:00:00Z",
            "--raw-input-hash", "sha256:" + "b" * 64,
            "--json",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["ok"] is True
        assert result["lineage"]["source_skill"] == "find-leads"

    def test_validate_invalid_skill_returns_nonzero(self, capsys):
        rc = discovery_lineage.main([
            "validate",
            "--source-skill", "bogus",
            "--source-list", "[[test]]",
            "--scraped-at", "2026-05-13T10:00:00Z",
            "--raw-input-hash", "sha256:" + "a" * 64,
        ])
        assert rc == 1

    def test_validate_invalid_skill_json_format(self, capsys):
        rc = discovery_lineage.main([
            "validate",
            "--source-skill", "bogus",
            "--source-list", "[[test]]",
            "--scraped-at", "2026-05-13T10:00:00Z",
            "--raw-input-hash", "sha256:" + "a" * 64,
            "--json",
        ])
        assert rc == 1
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["ok"] is False
        assert "not in SOURCE_SKILLS" in result["error"]


class TestCliBackfill:
    """The backfill CLI requires a vault + config. We test the
    can-locate-Person-note path via direct call to the helper rather
    than a full end-to-end CLI run (which would require ~/.outreach-factory/
    config). The end-to-end path is covered in tests/test_migrations_vault_005.py."""

    def test_find_person_note_by_id(self, tmp_path):
        """The private helper used by the backfill CLI to locate the Person."""
        import yaml

        people_dir = tmp_path / "people"
        people_dir.mkdir()
        note = people_dir / "Dylan.md"
        note.write_text(
            "---\n" + yaml.safe_dump({"type": "person", "id": "dylan-li"})
            + "---\n",
            encoding="utf-8",
        )
        found = discovery_lineage._find_person_note("dylan-li", people_dir)
        assert found == note

    def test_find_person_note_returns_none_when_missing(self, tmp_path):
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        assert discovery_lineage._find_person_note("nobody", people_dir) is None

    def test_find_person_note_skips_non_yaml_files(self, tmp_path):
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        # File without frontmatter — must not crash.
        (people_dir / "notes.md").write_text("# Just text", encoding="utf-8")
        assert discovery_lineage._find_person_note("anyone", people_dir) is None


# ---------------------------------------------------------------------------
# Public API surface contract
# ---------------------------------------------------------------------------


class TestPublicApiSurface:
    """Pin the public ``__all__`` surface — adding to it is a deliberate
    schema-extending act; removing requires an ADR amendment."""

    def test_all_exports_present(self):
        expected = {
            "BACKFILL_EVENT_TYPE",
            "CHANNEL_VALUE",
            "DiscoveryLineage",
            "EMITTED_BY",
            "LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL",
            "SOURCE_SKILLS",
            "build_discovery_lineage_dict",
            "build_enrolled_source_skill_backfill_payload",
            "compute_canonical_raw_input_hash",
            "normalize_legacy_source_to_skill",
            "parse_discovery_lineage_dict",
        }
        assert set(discovery_lineage.__all__) == expected

    def test_every_export_is_importable(self):
        for name in discovery_lineage.__all__:
            assert hasattr(discovery_lineage, name), name
