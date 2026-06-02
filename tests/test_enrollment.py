"""Tests for orchestrator/enrollment.py (Phase 5.5 Week 1b).

Covers the identity-aware refactor: enrollment dedup is now driven by
identity.find_matches + identity.resolve_strict, not name-only lookup.

Run:
    cd /Users/yang/code/outreach-factory && pytest tests/test_enrollment.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator import enrollment, identity, ledger as ledger_mod


# ---------------------------------------------------------------------------
# Fixtures: synthetic vault + cfg
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> dict:
    """Create a vault layout matching Yang's setup, return a cfg dict."""
    vault_path = tmp_path / "vault"
    people_dir = vault_path / "10 People"
    queue_dir = people_dir / "🟦 Queue"
    active_dir = people_dir / "🟧 Active"
    for d in (queue_dir, active_dir):
        d.mkdir(parents=True)
    conflicts_dir = tmp_path / "outreach-factory" / "conflicts"
    conflicts_dir.mkdir(parents=True)
    ledger_dir = tmp_path / "outreach-factory" / "ledger"
    ledger_dir.mkdir(parents=True)
    return {
        "vault": {
            "path": str(vault_path),
            "people_dir": "10 People",
            "queue_subdir": "🟦 Queue",
            "active_subdir": "🟧 Active",
        },
        "_test_people_dir": people_dir,
        "_test_queue_dir": queue_dir,
        "_test_active_dir": active_dir,
        "_test_conflicts_dir": conflicts_dir,
        "_test_ledger_dir": ledger_dir,
    }


@pytest.fixture(autouse=True)
def redirect_conflicts(monkeypatch, vault):
    """Force enrollment._conflicts_dir to point at the test conflicts dir
    so we don't write reports into the user's real ~/.outreach-factory."""
    monkeypatch.setattr(
        enrollment, "_conflicts_dir",
        lambda cfg: vault["_test_conflicts_dir"],
    )


@pytest.fixture(autouse=True)
def redirect_ledger(monkeypatch, vault):
    """Sandbox ledger writes so enrollment tests don't pollute the real
    ~/.outreach-factory/ledger/. Set via env var so the Ledger constructor
    in enrollment + state_machine + every other consumer picks it up
    uniformly."""
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR",
                       str(vault["_test_ledger_dir"]))


def _write_person(people_dir: Path, subdir: str, name: str, **frontmatter):
    fm = {"type": "person", "name": name}
    fm.update(frontmatter)
    fm.setdefault("pipeline_stage", "queued")
    fm_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    path = people_dir / subdir / f"{name}.md"
    path.write_text(f"---\n{fm_yaml}\n---\n\n# {name}\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Creation path: 0 matches -> mint id, create stub
# ---------------------------------------------------------------------------


class TestCreation:
    def test_creates_with_linkedin(self, vault):
        result = enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
        )
        assert result["ok"] is True
        assert result["status"] == "created"
        assert result["person_id"] == "dylan-txa-li"
        path = Path(result["path"])
        assert path.exists()
        fm = yaml.safe_load(path.read_text().split("---")[1])
        assert fm["id"] == "dylan-txa-li"
        assert fm["identity_keys"]["linkedin"] == "in/dylan-txa"
        assert fm["identity_version"] == 1
        assert fm["pipeline_stage"] == "queued"
        assert fm["type"] == "person"
        assert fm["name"] == "Dylan Teixeira"

    def test_creates_with_email_only(self, vault):
        result = enrollment.enroll_person(
            "Test User", cfg=vault,
            emails=["test@example.com"],
        )
        assert result["status"] == "created"
        assert result["person_id"].endswith("-em")
        fm = yaml.safe_load(Path(result["path"]).read_text().split("---")[1])
        assert "test@example.com" in fm["identity_keys"]["emails"]
        assert "linkedin" not in fm["identity_keys"]

    def test_creates_with_no_keys_yields_tmp_id(self, vault):
        result = enrollment.enroll_person(
            "Unknown Person", cfg=vault,
            frontmatter={"company": "[[Acme]]"},
        )
        assert result["status"] == "created"
        assert result["person_id"].endswith("-tmp")
        fm = yaml.safe_load(Path(result["path"]).read_text().split("---")[1])
        assert fm["id"] == result["person_id"]
        # No strong match keys, but the alt_names slot still records the
        # canonicalized display name (diagnostic only — alt_names is not a
        # match class, so this won't auto-merge two different unknowns who
        # happen to share a typed-out name).
        if "identity_keys" in fm:
            keys_block = fm["identity_keys"]
            for k in ("linkedin", "emails", "github", "twitter"):
                assert k not in keys_block

    def test_preserves_frontmatter_extras(self, vault):
        result = enrollment.enroll_person(
            "Alex Liu", cfg=vault,
            linkedin="https://linkedin.com/in/alexdliu7",
            frontmatter={
                "company": "[[Korso]]",
                "role": "Co-Founder",
                "source_channel": "funded-founders",
                "tags": ["funded-founders", "tier-S"],
            },
        )
        assert result["status"] == "created"
        fm = yaml.safe_load(Path(result["path"]).read_text().split("---")[1])
        assert fm["company"] == "[[Korso]]"
        assert fm["role"] == "Co-Founder"
        assert fm["tags"] == ["funded-founders", "tier-S"]

    def test_back_compat_linkedin_in_frontmatter(self, vault):
        """Legacy callers pass linkedin in --frontmatter rather than --linkedin."""
        result = enrollment.enroll_person(
            "Back Compat User", cfg=vault,
            frontmatter={"linkedin": "https://linkedin.com/in/bc-user"},
        )
        assert result["status"] == "created"
        assert result["person_id"] == "bc-user-li"

    def test_explicit_arg_wins_over_frontmatter(self, vault):
        """When both --linkedin and frontmatter.linkedin are set, --linkedin
        wins (discovery skills know what they scraped; frontmatter may be stale)."""
        result = enrollment.enroll_person(
            "Override", cfg=vault,
            linkedin="https://linkedin.com/in/correct-slug",
            frontmatter={"linkedin": "https://linkedin.com/in/wrong-slug"},
        )
        assert result["person_id"] == "correct-slug-li"

    def test_rejects_caller_supplied_id(self, vault):
        """Caller cannot inject an `id:` via frontmatter — we own minting."""
        result = enrollment.enroll_person(
            "Spoofed", cfg=vault,
            linkedin="https://linkedin.com/in/real-slug",
            frontmatter={"id": "attacker-supplied-id"},
        )
        assert result["person_id"] == "real-slug-li"

    def test_empty_name_errors(self, vault):
        result = enrollment.enroll_person("", cfg=vault, linkedin="x")
        assert result["ok"] is False
        assert result["status"] == "error"

    def test_pipeline_enrolled_at_is_iso8601(self, vault):
        result = enrollment.enroll_person(
            "Time Test", cfg=vault, linkedin="https://linkedin.com/in/time-test",
        )
        fm = yaml.safe_load(Path(result["path"]).read_text().split("---")[1])
        # ISO 8601 UTC: ...Z
        assert fm["pipeline_enrolled_at"].endswith("Z")


# ---------------------------------------------------------------------------
# Match path: 1 existing record -> return exists
# ---------------------------------------------------------------------------


class TestExistingMatch:
    def test_linkedin_match_returns_exists(self, vault):
        existing = _write_person(
            vault["_test_people_dir"], "🟧 Active", "Dylan T",
            id="dylan-txa-li",
            identity_keys={"linkedin": "in/dylan-txa"},
        )
        result = enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
        )
        assert result["ok"] is True
        assert result["status"] == "exists"
        assert Path(result["path"]) == existing
        assert "linkedin" in result["matched_classes"]
        assert result["person_id"] == "dylan-txa-li"

    def test_email_match_returns_exists(self, vault):
        existing = _write_person(
            vault["_test_people_dir"], "🟧 Active", "Existing",
            id="abc123-em",
            identity_keys={"emails": ["shared@example.com"]},
        )
        result = enrollment.enroll_person(
            "Different Name", cfg=vault,
            emails=["shared@example.com"],
        )
        assert result["status"] == "exists"
        assert Path(result["path"]) == existing

    def test_legacy_frontmatter_fallback_match(self, vault):
        """Pre-backfill notes have linkedin: at top-level, no identity_keys block.
        Match still works via legacy fallback in identity.read_person_keys."""
        existing = _write_person(
            vault["_test_people_dir"], "🟦 Queue", "Legacy Person",
            linkedin="https://linkedin.com/in/legacy-slug",
        )
        result = enrollment.enroll_person(
            "Legacy Person", cfg=vault,
            linkedin="https://linkedin.com/in/legacy-slug",
        )
        assert result["status"] == "exists"
        assert Path(result["path"]) == existing

    def test_name_collision_without_identity_collision_creates_new(self, vault):
        """Two distinct Alex Lius with different LinkedIns. Old code would
        have merged them; new identity layer keeps them apart."""
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Alex Liu",
            id="alexdliu7-li",
            identity_keys={"linkedin": "in/alexdliu7"},
        )
        result = enrollment.enroll_person(
            "Alex Liu", cfg=vault,
            linkedin="https://linkedin.com/in/alex-liu-different",
        )
        # New record — different LinkedIn means different person.
        assert result["status"] == "created"
        assert result["person_id"] == "alex-liu-different-li"


# ---------------------------------------------------------------------------
# Conflict path: 2+ matches -> refuse, write report
# ---------------------------------------------------------------------------


class TestConflict:
    def test_two_records_share_email_yields_conflict(self, vault):
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Alice Shared",
            id="alice-li",
            identity_keys={"linkedin": "in/alice", "emails": ["family@home.com"]},
        )
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Bob Shared",
            id="bob-li",
            identity_keys={"linkedin": "in/bob", "emails": ["family@home.com"]},
        )
        # Candidate has only the shared email — matches BOTH existing records.
        result = enrollment.enroll_person(
            "Carol Newcomer", cfg=vault,
            emails=["family@home.com"],
        )
        assert result["ok"] is False
        assert result["status"] == "conflict"
        assert result["report_path"] is not None
        assert Path(result["report_path"]).exists()
        report = yaml.safe_load(Path(result["report_path"]).read_text())
        assert len(report["matched_records"]) == 2

    def test_single_class_email_distinct_linkedin_conflict(self, vault):
        """Strict-policy refinement: sole email match + candidate has distinct
        LinkedIn from existing record -> escalate to Conflict."""
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Alice Existing",
            id="alice-li",
            identity_keys={"linkedin": "in/alice-existing",
                           "emails": ["work@shared.com"]},
        )
        result = enrollment.enroll_person(
            "Bob Newcomer", cfg=vault,
            linkedin="https://linkedin.com/in/bob-different",
            emails=["work@shared.com"],
        )
        assert result["status"] == "conflict"


# ---------------------------------------------------------------------------
# File / path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_disambiguates_filename_collision(self, vault, monkeypatch):
        """Two distinct people share a sanitized filename. find_matches returns
        empty (different LinkedIns), but the file already exists. The helper
        must NOT overwrite — pick a disambiguated path."""
        first = enrollment.enroll_person(
            "Test Collide", cfg=vault,
            linkedin="https://linkedin.com/in/first-slug",
        )
        assert first["status"] == "created"
        second = enrollment.enroll_person(
            "Test Collide", cfg=vault,
            linkedin="https://linkedin.com/in/second-slug",
        )
        assert second["status"] == "created"
        assert second["path"] != first["path"]

    def test_no_vault_errors_cleanly(self, tmp_path):
        cfg = {"vault": {"path": str(tmp_path / "nonexistent"),
                         "people_dir": "10 People"}}
        result = enrollment.enroll_person("Anyone", cfg=cfg, linkedin="x")
        assert result["ok"] is False
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# check command behavior (mirrors enroll path but read-only)
# ---------------------------------------------------------------------------


class TestCheckLogic:
    """Exercise enroll_person's match logic indirectly — the underlying
    identity.find_matches surface."""

    def test_idempotent_re_enroll(self, vault):
        """Enrolling the same prospect twice yields one created + one exists."""
        r1 = enrollment.enroll_person(
            "Idem", cfg=vault, linkedin="https://linkedin.com/in/idem",
        )
        r2 = enrollment.enroll_person(
            "Idem", cfg=vault, linkedin="https://linkedin.com/in/idem",
        )
        assert r1["status"] == "created"
        assert r2["status"] == "exists"
        assert r2["path"] == r1["path"]


# ---------------------------------------------------------------------------
# Ledger emission (Phase 5.5 Week 2)
# ---------------------------------------------------------------------------


class TestLedgerEmission:
    def test_created_emits_enrolled_event(self, vault):
        enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
            frontmatter={"source_channel": "find-funded-founders",
                         "source_list": "2026-05-13-funded-founders"},
        )
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        types = [e["type"] for e in events]
        assert "enrolled" in types
        enrolled = next(e for e in events if e["type"] == "enrolled")
        assert enrolled["person_id"] == "dylan-txa-li"
        assert enrolled["source"] == "find-funded-founders"
        assert enrolled["source_list"] == "2026-05-13-funded-founders"
        assert enrolled["identity_keys"]["linkedin"] == "in/dylan-txa"

    def test_tmp_id_emits_needs_identity_upgrade(self, vault):
        result = enrollment.enroll_person("Nobody Special", cfg=vault)
        assert result["status"] == "created"
        assert identity.id_is_temporary(result["person_id"])
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        types = [e.type for e in led.all_events()]
        assert "enrolled" in types
        assert "needs_identity_upgrade" in types

    def test_strong_id_does_not_emit_needs_identity_upgrade(self, vault):
        result = enrollment.enroll_person(
            "Has LinkedIn", cfg=vault,
            linkedin="https://linkedin.com/in/has-linkedin",
        )
        assert result["status"] == "created"
        assert not identity.id_is_temporary(result["person_id"])
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        types = [e.type for e in led.all_events()]
        assert "needs_identity_upgrade" not in types

    def test_needs_identity_upgrade_carries_source_attribution(self, vault):
        """Pillar E Week 1 P2-A regression pin per ADR-0032 D146 +
        .planning/REVIEW-pillar-e-surface-audit.md §3.

        The audit surfaced a pre-existing structural-symmetric-omission:
        the `enrolled` / `enrollment_skipped_exists` / `enrollment_conflict`
        events all carried `source` + `source_list` (per the existing
        enrollment.py:279-280 convention), but `needs_identity_upgrade`
        did NOT. Downstream consumers (Pillar G "which discovery skills
        surface mostly-tmp prospects?" dashboards; the operator-facing
        identity-upgrade backlog) could only attribute the signal by
        joining back to the paired `enrolled` event by person_id.

        This regression pin verifies the Pillar E Week 1 commit's inline
        fix — `needs_identity_upgrade` now stamps `source` + `source_list`
        from the same fm_in.get("source_channel") || fm_in.get("source")
        || None precedence as the other three enrollment-adjacent events.
        Analog of Pillar D Week 1's Pass B `channel: "email"` fix
        (per ADR-0025 D96's channel-on-every-event invariant extension).
        """
        result = enrollment.enroll_person(
            "Nobody Special", cfg=vault,
            frontmatter={"source_channel": "find-leads",
                         "source_list": "2026-05-24-find-leads-test"},
        )
        assert result["status"] == "created"
        assert identity.id_is_temporary(result["person_id"])
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        upgrade_events = [e for e in events
                          if e["type"] == "needs_identity_upgrade"]
        assert len(upgrade_events) == 1, (
            "expected exactly one needs_identity_upgrade event for the "
            "-tmp id; got " + str(len(upgrade_events))
        )
        upgrade = upgrade_events[0]
        assert upgrade["source"] == "find-leads", (
            "needs_identity_upgrade must stamp source per Pillar E "
            "Week 1 surface audit P2-A fix; got "
            + repr(upgrade.get("source"))
        )
        assert upgrade["source_list"] == "2026-05-24-find-leads-test", (
            "needs_identity_upgrade must stamp source_list per Pillar E "
            "Week 1 surface audit P2-A fix; got "
            + repr(upgrade.get("source_list"))
        )

    def test_needs_identity_upgrade_source_attribution_handles_absent(
        self, vault,
    ):
        """Pillar E Week 1 P2-A: when no source_channel/source_list is
        provided in the enrollment frontmatter, `needs_identity_upgrade`
        stamps `source: None` + `source_list: None` — symmetric with the
        other three enrollment events' fallback behavior per the existing
        `fm_in.get("source_channel") or fm_in.get("source") or None`
        precedence in enrollment.py:279-280.
        """
        result = enrollment.enroll_person("Nobody Special", cfg=vault)
        assert result["status"] == "created"
        assert identity.id_is_temporary(result["person_id"])
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        upgrade_events = [e for e in events
                          if e["type"] == "needs_identity_upgrade"]
        assert len(upgrade_events) == 1
        upgrade = upgrade_events[0]
        # The fields are PRESENT but None — symmetric with the other
        # three enrollment events (line 295, 316, 389 in enrollment.py).
        assert "source" in upgrade
        assert "source_list" in upgrade
        assert upgrade["source"] is None
        assert upgrade["source_list"] is None

    def test_exists_emits_skipped_event(self, vault):
        # Pre-existing Person note with identity_keys.
        existing = _write_person(
            vault["_test_people_dir"], "🟧 Active", "Original",
            id="original-li",
            identity_keys={"linkedin": "in/original"},
            identity_version=1,
        )
        result = enrollment.enroll_person(
            "Original", cfg=vault,
            linkedin="https://linkedin.com/in/original",
        )
        assert result["status"] == "exists"
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        skipped = [e for e in events if e["type"] == "enrollment_skipped_exists"]
        assert len(skipped) == 1
        assert skipped[0]["person_id"] == "original-li"
        assert "linkedin" in skipped[0]["matched_classes"]
        assert skipped[0]["note_path"] == str(existing.resolve())

    def test_conflict_emits_event(self, vault):
        # Two records share an email; candidate brings a third LinkedIn →
        # single-class email match with distinct LinkedIn → Conflict.
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Alice",
            id="alice-li",
            identity_keys={"linkedin": "in/alice",
                           "emails": ["shared@family.com"]},
            identity_version=1,
        )
        result = enrollment.enroll_person(
            "Bob", cfg=vault,
            linkedin="https://linkedin.com/in/bob",
            emails=["shared@family.com"],
        )
        assert result["status"] == "conflict"
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        conflicts = [e for e in events if e["type"] == "enrollment_conflict"]
        assert len(conflicts) == 1
        assert conflicts[0]["match_count"] == 1
        assert conflicts[0]["candidate_name"] == "Bob"


# ---------------------------------------------------------------------------
# Pillar E Week 9-11 — discovery_lineage stamping per ADR-0036 D169 + D170
# ---------------------------------------------------------------------------


class TestDiscoveryLineageStamping:
    """Per ADR-0036 D169 + D170 — when enroll_person is called with an
    explicit ``lineage`` DiscoveryLineage kwarg, the four canonical
    fields stamp on:

    1. The Person frontmatter's ``identity_keys.discovery_lineage:`` sub-block.
    2. The emitted ``enrolled`` event (denormalized).
    3. The emitted ``enrollment_skipped_exists`` event (when matching).
    4. The emitted ``enrollment_conflict`` event (when ambiguous match).
    5. The emitted ``needs_identity_upgrade`` event (when tmp id).

    All four enrollment-adjacent event classes get the new
    ``source_skill`` field per the symmetric stamping convention; the
    enrolled event also gets the full lineage sub-fields
    (``scraped_at`` + ``raw_input_hash``).
    """

    def _lineage(self, **overrides):
        # Use bare-name import (matches the codebase convention per
        # conftest.py's sys.path setup); this avoids the dual-module-
        # identity hazard where the orchestrator.X path and bare X path
        # resolve to distinct module objects + distinct classes.
        from discovery_lineage import DiscoveryLineage
        fields = {
            "source_skill": "find-funded-founders",
            "source_list": "[[2026-05-13-vcs]]",
            "scraped_at": "2026-05-13T10:00:00Z",
            "raw_input_hash": "sha256:" + "a" * 64,
        }
        fields.update(overrides)
        return DiscoveryLineage(**fields)

    def test_created_stamps_lineage_on_person_frontmatter(self, vault):
        """The Person note's identity_keys.discovery_lineage sub-block lands."""
        result = enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
            lineage=self._lineage(),
        )
        assert result["status"] == "created"
        path = Path(result["path"])
        fm = yaml.safe_load(path.read_text().split("---")[1])
        assert "identity_keys" in fm
        assert "discovery_lineage" in fm["identity_keys"]
        lineage_dict = fm["identity_keys"]["discovery_lineage"]
        assert lineage_dict == {
            "source_skill": "find-funded-founders",
            "source_list": "[[2026-05-13-vcs]]",
            "scraped_at": "2026-05-13T10:00:00Z",
            "raw_input_hash": "sha256:" + "a" * 64,
        }

    def test_enrolled_event_carries_source_skill_and_full_lineage(self, vault):
        enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
            lineage=self._lineage(),
        )
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        enrolled = next(e for e in events if e["type"] == "enrolled")
        # Canonical (post-Week-9-11) field.
        assert enrolled["source_skill"] == "find-funded-founders"
        # Legacy field — same value, for back-compat.
        assert enrolled["source"] == "find-funded-founders"
        # Source list.
        assert enrolled["source_list"] == "[[2026-05-13-vcs]]"
        # Full lineage denormalized.
        assert enrolled["scraped_at"] == "2026-05-13T10:00:00Z"
        assert enrolled["raw_input_hash"] == "sha256:" + "a" * 64

    def test_enrollment_skipped_exists_carries_source_skill(self, vault):
        """The matching event class also gets the canonical field."""
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Original",
            id="original-li",
            identity_keys={"linkedin": "in/original"},
            identity_version=1,
        )
        enrollment.enroll_person(
            "Original", cfg=vault,
            linkedin="https://linkedin.com/in/original",
            lineage=self._lineage(source_skill="competitor-customers"),
        )
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        skipped = next(e for e in events
                       if e["type"] == "enrollment_skipped_exists")
        assert skipped["source_skill"] == "competitor-customers"
        assert skipped["source_list"] == "[[2026-05-13-vcs]]"
        # Legacy field also stamped.
        assert skipped["source"] == "competitor-customers"

    def test_enrollment_conflict_carries_source_skill(self, vault):
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Alice",
            id="alice-li",
            identity_keys={"linkedin": "in/alice",
                           "emails": ["shared@family.com"]},
            identity_version=1,
        )
        enrollment.enroll_person(
            "Bob", cfg=vault,
            linkedin="https://linkedin.com/in/bob",
            emails=["shared@family.com"],
            lineage=self._lineage(source_skill="find-leads"),
        )
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        conflicts = [e for e in events if e["type"] == "enrollment_conflict"]
        assert len(conflicts) == 1
        assert conflicts[0]["source_skill"] == "find-leads"
        assert conflicts[0]["source"] == "find-leads"
        assert conflicts[0]["source_list"] == "[[2026-05-13-vcs]]"

    def test_needs_identity_upgrade_carries_source_skill(self, vault):
        """The fourth enrollment-adjacent event extends the symmetric stamping."""
        result = enrollment.enroll_person(
            "Nobody Special", cfg=vault,
            lineage=self._lineage(source_skill="manual"),
        )
        assert result["status"] == "created"
        assert identity.id_is_temporary(result["person_id"])
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        upgrade = next(e for e in events
                       if e["type"] == "needs_identity_upgrade")
        assert upgrade["source_skill"] == "manual"
        assert upgrade["source"] == "manual"

    def test_legacy_path_normalizes_source_to_canonical_skill(self, vault):
        """Pre-Week-9-11 callers pass source_channel via frontmatter; the
        canonical source_skill is derived via normalize_legacy_source_to_skill."""
        enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
            frontmatter={"source_channel": "funded-founders",  # legacy spelling
                         "source_list": "[[legacy-list]]"},
        )
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        enrolled = next(e for e in events if e["type"] == "enrolled")
        # Legacy source field unchanged (legacy spelling preserved).
        assert enrolled["source"] == "funded-founders"
        # Canonical source_skill derived via normalize.
        assert enrolled["source_skill"] == "find-funded-founders"
        # No lineage sub-fields when lineage kwarg absent.
        assert "scraped_at" not in enrolled
        assert "raw_input_hash" not in enrolled

    def test_legacy_path_with_no_source_stamps_none(self, vault):
        """No lineage + no source_channel → source_skill is None."""
        enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
        )
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        enrolled = next(e for e in events if e["type"] == "enrolled")
        assert enrolled["source"] is None
        assert enrolled["source_skill"] is None

    def test_lineage_preserved_through_yaml_safe_dump_roundtrip(self, vault):
        """The frontmatter YAML round-trips cleanly (no operator-readable shape loss)."""
        result = enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
            lineage=self._lineage(),
        )
        path = Path(result["path"])
        text = path.read_text()
        # Verify YAML re-parses to the same dict.
        fm = yaml.safe_load(text.split("---")[1])
        assert fm["identity_keys"]["discovery_lineage"]["source_skill"] == "find-funded-founders"
        # Re-parse via discovery_lineage.parse for full round-trip.
        from discovery_lineage import parse_discovery_lineage_dict
        lineage_obj = parse_discovery_lineage_dict(
            fm["identity_keys"]["discovery_lineage"],
        )
        assert lineage_obj.source_skill == "find-funded-founders"

    def test_back_compat_existing_tests_pass_without_lineage(self, vault):
        """Existing tests that don't pass lineage continue to work unchanged."""
        # Mirror the existing test_created_emits_enrolled_event shape.
        enrollment.enroll_person(
            "Dylan Teixeira", cfg=vault,
            linkedin="https://linkedin.com/in/dylan-txa",
            frontmatter={"source_channel": "find-funded-founders",
                         "source_list": "2026-05-13-funded-founders"},
        )
        led = ledger_mod.Ledger(vault["_test_ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        enrolled = next(e for e in events if e["type"] == "enrolled")
        assert enrolled["person_id"] == "dylan-txa-li"
        assert enrolled["source"] == "find-funded-founders"
        assert enrolled["source_list"] == "2026-05-13-funded-founders"
        assert enrolled["identity_keys"]["linkedin"] == "in/dylan-txa"
