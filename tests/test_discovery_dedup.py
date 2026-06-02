"""Tests for orchestrator/discovery_dedup.py — Pillar E Week 2.

Covers the pre-enrichment dedup primitive per ADR-0033 D149-D153:
:class:`DedupResult` dataclass invariants, :func:`check_dedup` happy
paths + conflict paths, event-payload factory contracts, and the
per-skill integration shape (smoke test against the find-leads
canonical caller pattern).

Run:
    cd /Users/yang/code/outreach-factory && pytest tests/test_discovery_dedup.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator import discovery_dedup, identity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> dict:
    """Synthetic vault layout — mirrors test_enrollment's fixture so the
    dedup primitive's tests + the enrollment tests use compatible
    setups (the dedup primitive is the FAST-PATH for the same
    identity-resolver that enrollment uses as the BACK-STOP per
    ADR-0033 D143)."""
    vault_path = tmp_path / "vault"
    people_dir = vault_path / "10 People"
    queue_dir = people_dir / "Queue"
    active_dir = people_dir / "Active"
    for d in (queue_dir, active_dir):
        d.mkdir(parents=True)
    conflicts_dir = tmp_path / "outreach-factory" / "conflicts"
    conflicts_dir.mkdir(parents=True)
    return {
        "people_dir": people_dir,
        "queue_dir": queue_dir,
        "active_dir": active_dir,
        "conflicts_dir": conflicts_dir,
    }


def _write_person(
    people_dir: Path, subdir: str, name: str, **frontmatter,
) -> Path:
    fm = {"type": "person", "name": name}
    fm.update(frontmatter)
    fm.setdefault("pipeline_stage", "queued")
    fm_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    path = people_dir / subdir / f"{name}.md"
    path.write_text(
        f"---\n{fm_yaml}\n---\n\n# {name}\n", encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# DedupResult invariants
# ---------------------------------------------------------------------------


class TestDedupResultInvariants:
    """ADR-0033 D149 — the dataclass's status + helper-property contract."""

    def test_not_duplicate_status_does_not_skip_enrichment(self):
        result = discovery_dedup.DedupResult(
            status="not_duplicate",
            candidate_partial=identity.IdentityKeys(),
        )
        assert result.is_not_duplicate is True
        assert result.is_duplicate is False
        assert result.is_conflict is False
        assert result.should_skip_enrichment is False

    def test_duplicate_status_skips_enrichment(self):
        match = identity.Match(
            note_path=Path("/tmp/fake.md"),
            person_id="dylan-txa-li",
            matched_classes=frozenset({"linkedin"}),
        )
        result = discovery_dedup.DedupResult(
            status="duplicate",
            candidate_partial=identity.IdentityKeys(linkedin="in/dylan-txa"),
            existing_person_id="dylan-txa-li",
            matched_classes=frozenset({"linkedin"}),
            existing_match=match,
        )
        assert result.is_duplicate is True
        assert result.is_not_duplicate is False
        assert result.is_conflict is False
        assert result.should_skip_enrichment is True

    def test_conflict_status_skips_enrichment(self):
        candidate = identity.IdentityKeys(emails=frozenset({"x@y.com"}))
        conflict = identity.Conflict(
            candidate_keys=candidate,
            matches=[],
            report_path=Path("/tmp/conflict.yml"),
        )
        result = discovery_dedup.DedupResult(
            status="conflict",
            candidate_partial=candidate,
            conflict=conflict,
        )
        assert result.is_conflict is True
        assert result.is_duplicate is False
        assert result.should_skip_enrichment is True

    def test_unknown_status_rejected_at_construction(self):
        with pytest.raises(ValueError, match="status must be one of"):
            discovery_dedup.DedupResult(
                status="bogus",
                candidate_partial=identity.IdentityKeys(),
            )

    def test_duplicate_without_existing_match_rejected(self):
        with pytest.raises(ValueError, match="requires existing_match"):
            discovery_dedup.DedupResult(
                status="duplicate",
                candidate_partial=identity.IdentityKeys(
                    linkedin="in/test",
                ),
                existing_person_id="test-li",
                # existing_match=None — the omission the validator catches
            )

    def test_conflict_without_conflict_rejected(self):
        with pytest.raises(ValueError, match="requires conflict"):
            discovery_dedup.DedupResult(
                status="conflict",
                candidate_partial=identity.IdentityKeys(
                    emails=frozenset({"shared@x.com"}),
                ),
                # conflict=None — the omission the validator catches
            )


# ---------------------------------------------------------------------------
# check_dedup happy paths
# ---------------------------------------------------------------------------


class TestCheckDedupHappyPaths:
    """ADR-0033 D149 — the per-skill entry point's 0/1/2+ behavior."""

    def test_empty_candidate_returns_not_duplicate(self, vault):
        result = discovery_dedup.check_dedup(
            candidate_partial=identity.IdentityKeys(),
            source_skill="find-leads",
            source_list="[[test-list]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_not_duplicate is True
        assert result.should_skip_enrichment is False

    def test_no_existing_persons_returns_not_duplicate(self, vault):
        candidate = identity.compute_keys(
            name="New Person",
            linkedin_url="https://linkedin.com/in/never-seen",
        )
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="find-leads",
            source_list="[[test-list]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_not_duplicate is True

    def test_linkedin_match_returns_duplicate(self, vault):
        _write_person(
            vault["people_dir"], "Active", "Dylan",
            id="dylan-txa-li",
            identity_keys={"linkedin": "in/dylan-txa"},
        )
        candidate = identity.compute_keys(
            name="Dylan Teixeira",
            linkedin_url="https://linkedin.com/in/dylan-txa",
        )
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="find-leads",
            source_list="[[test-list]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_duplicate is True
        assert result.existing_person_id == "dylan-txa-li"
        assert "linkedin" in result.matched_classes
        assert result.existing_match is not None
        assert result.should_skip_enrichment is True

    def test_email_only_partial_matches_by_email(self, vault):
        _write_person(
            vault["people_dir"], "Active", "Existing",
            id="abc-em",
            identity_keys={"emails": ["dylan@example.com"]},
        )
        # Pre-enrichment partial: ONLY an email (no LinkedIn yet —
        # mimics the find-leads scrape path where the email comes
        # from a /team page but the LinkedIn URL hasn't been
        # resolved yet).
        candidate = identity.compute_keys(
            name="Dylan",
            email="dylan@example.com",
        )
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="find-leads",
            source_list="[[test-list]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_duplicate is True
        assert "email" in result.matched_classes

    def test_linkedin_only_partial_matches_by_linkedin(self, vault):
        _write_person(
            vault["people_dir"], "Active", "Existing",
            id="dylan-txa-li",
            identity_keys={"linkedin": "in/dylan-txa"},
        )
        candidate = identity.compute_keys(
            name="Dylan",
            linkedin_url="linkedin.com/in/dylan-txa",
        )
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="find-funded-founders",
            source_list="[[funded-2026-05-24]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_duplicate is True
        assert result.matched_classes == frozenset({"linkedin"})

    def test_both_keys_match_same_person(self, vault):
        _write_person(
            vault["people_dir"], "Active", "Existing",
            id="dylan-txa-li",
            identity_keys={
                "linkedin": "in/dylan-txa",
                "emails": ["dylan@example.com"],
            },
        )
        candidate = identity.compute_keys(
            name="Dylan",
            linkedin_url="linkedin.com/in/dylan-txa",
            email="dylan@example.com",
        )
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="competitor-customers",
            source_list="[[acme-customers]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_duplicate is True
        assert "linkedin" in result.matched_classes
        assert "email" in result.matched_classes

    def test_two_persons_share_email_yields_conflict(self, vault):
        # Two distinct existing Persons with the same shared email
        # (e.g., shared family mailbox or cofounder inbox). The
        # strict policy escalates to Conflict.
        _write_person(
            vault["people_dir"], "Active", "Alice",
            id="alice-li",
            identity_keys={
                "linkedin": "in/alice",
                "emails": ["shared@family.com"],
            },
        )
        _write_person(
            vault["people_dir"], "Active", "Bob",
            id="bob-li",
            identity_keys={
                "linkedin": "in/bob",
                "emails": ["shared@family.com"],
            },
        )
        candidate = identity.compute_keys(
            name="Unknown",
            email="shared@family.com",
        )
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="find-leads",
            source_list="[[test-list]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_conflict is True
        assert result.conflict is not None
        assert len(result.conflict.matches) == 2
        # The strict policy's report file is written.
        assert result.conflict.report_path.exists()
        assert result.should_skip_enrichment is True

    def test_ambiguous_single_class_email_match_yields_conflict(self, vault):
        # Per identity._is_ambiguous_single_class_email_match: when the
        # only matched class is email AND the candidate carries a
        # LinkedIn that differs from the existing record's LinkedIn,
        # the shared email is treated as ambiguous (likely shared
        # inbox) + escalated to Conflict.
        _write_person(
            vault["people_dir"], "Active", "Existing",
            id="alice-li",
            identity_keys={
                "linkedin": "in/alice",
                "emails": ["shared@family.com"],
            },
        )
        candidate = identity.compute_keys(
            name="Bob",
            linkedin_url="linkedin.com/in/bob",  # DIFFERENT LinkedIn
            email="shared@family.com",            # SAME email
        )
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="find-leads",
            source_list="[[test-list]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result.is_conflict is True
        assert result.should_skip_enrichment is True

    def test_vault_unreadable_falls_back_to_not_duplicate(self, tmp_path):
        # Simulate the vault-unreadable case: people_dir resolves to
        # a missing path. The primitive returns not_duplicate (the
        # FAST-PATH gracefully no-ops; the BACK-STOP via
        # enrollment's resolve_strict still fires post-enrichment).
        missing_people_dir = tmp_path / "vault" / "people"
        # Don't create it.
        candidate = identity.compute_keys(
            name="Test",
            linkedin_url="linkedin.com/in/test",
        )
        # Pass an explicit people_dir override; we test the
        # vault-resolution-failed path via the cfg branch in the
        # CLI test below. Here we test that an empty / non-existent
        # people_dir doesn't crash:
        result = discovery_dedup.check_dedup(
            candidate_partial=candidate,
            source_skill="find-leads",
            source_list=None,
            people_dir=missing_people_dir,
            conflicts_dir=tmp_path / "conflicts",
        )
        # find_matches on a non-existent dir returns empty list
        # gracefully (identity.build_index uses rglob which yields
        # nothing on a missing directory). Result is not_duplicate.
        assert result.is_not_duplicate is True


# ---------------------------------------------------------------------------
# build_discovery_dedup_hit_payload contract
# ---------------------------------------------------------------------------


class TestBuildDiscoveryDedupHitPayload:
    """ADR-0033 D150 — the discovery_dedup_hit event emit-shape."""

    def _make_duplicate_result(self) -> discovery_dedup.DedupResult:
        candidate = identity.IdentityKeys(
            linkedin="in/dylan-txa",
            emails=frozenset({"dylan@example.com"}),
        )
        match = identity.Match(
            note_path=Path("/tmp/dylan.md"),
            person_id="dylan-txa-li",
            matched_classes=frozenset({"linkedin", "email"}),
        )
        return discovery_dedup.DedupResult(
            status="duplicate",
            candidate_partial=candidate,
            existing_person_id="dylan-txa-li",
            matched_classes=frozenset({"linkedin", "email"}),
            existing_match=match,
        )

    def test_payload_type_is_discovery_dedup_hit(self):
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="find-leads",
            source_list="[[2026-05-24-find-leads-q2]]",
        )
        assert payload["type"] == "discovery_dedup_hit"

    def test_payload_carries_existing_person_id(self):
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="find-leads",
            source_list="[[test-list]]",
        )
        assert payload["person_id"] == "dylan-txa-li"

    def test_payload_carries_candidate_partial_serialized(self):
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="find-leads",
            source_list="[[test-list]]",
        )
        # candidate_partial uses IdentityKeys.to_serializable() shape
        assert payload["candidate_partial"]["linkedin"] == "in/dylan-txa"
        assert payload["candidate_partial"]["emails"] == ["dylan@example.com"]

    def test_payload_carries_matched_classes_sorted(self):
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="find-leads",
            source_list="[[test-list]]",
        )
        # sorted for deterministic test output + Pillar G dashboard
        # aggregation determinism
        assert payload["matched_classes"] == ["email", "linkedin"]

    def test_payload_carries_source_attribution(self):
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="competitor-customers",
            source_list="[[acme-customers]]",
        )
        assert payload["source_skill"] == "competitor-customers"
        assert payload["source_list"] == "[[acme-customers]]"

    def test_payload_carries_channel_none_per_d146(self):
        """ADR-0032 D146 + ADR-0014 D33 channel-on-every-event invariant
        extension. Dedup is channel-agnostic; the explicit ``"none"``
        value makes the absence operator-visible in Pillar G dashboards
        filtered by channel."""
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="find-leads",
            source_list="[[test-list]]",
        )
        assert payload["channel"] == "none"

    def test_payload_carries_emitted_by_marker(self):
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="find-leads",
            source_list="[[test-list]]",
        )
        assert payload["_emitted_by"] == "discovery_dedup"

    def test_source_list_optional(self):
        """source_list MAY be None per D142 (operator-supplied,
        OPERATOR-PRIVATE per D148). The factory accepts the None
        value verbatim so per-skill callers without an explicit list
        context can still emit."""
        payload = discovery_dedup.build_discovery_dedup_hit_payload(
            self._make_duplicate_result(),
            source_skill="manual",
            source_list=None,
        )
        assert payload["source_list"] is None

    def test_rejects_non_duplicate_result(self):
        """The factory enforces dispatch correctness at construction
        time — calling it with a not_duplicate or conflict result
        is a programmer error per D150."""
        not_dup = discovery_dedup.DedupResult(
            status="not_duplicate",
            candidate_partial=identity.IdentityKeys(),
        )
        with pytest.raises(ValueError, match="requires status='duplicate'"):
            discovery_dedup.build_discovery_dedup_hit_payload(
                not_dup, "find-leads", None,
            )


# ---------------------------------------------------------------------------
# build_discovery_dedup_conflict_payload contract
# ---------------------------------------------------------------------------


class TestBuildDiscoveryDedupConflictPayload:
    """ADR-0033 D151 — the discovery_dedup_conflict event emit-shape."""

    def _make_conflict_result(
        self, report_path: Path,
    ) -> discovery_dedup.DedupResult:
        candidate = identity.IdentityKeys(
            emails=frozenset({"shared@family.com"}),
        )
        m1 = identity.Match(
            note_path=Path("/tmp/alice.md"),
            person_id="alice-li",
            matched_classes=frozenset({"email"}),
        )
        m2 = identity.Match(
            note_path=Path("/tmp/bob.md"),
            person_id="bob-li",
            matched_classes=frozenset({"email"}),
        )
        conflict = identity.Conflict(
            candidate_keys=candidate,
            matches=[m1, m2],
            report_path=report_path,
        )
        return discovery_dedup.DedupResult(
            status="conflict",
            candidate_partial=candidate,
            matched_classes=frozenset({"email"}),
            conflict=conflict,
        )

    def test_payload_type_is_discovery_dedup_conflict(self, tmp_path):
        result = self._make_conflict_result(tmp_path / "conflict.yml")
        payload = discovery_dedup.build_discovery_dedup_conflict_payload(
            result, "find-leads", "[[test-list]]",
        )
        assert payload["type"] == "discovery_dedup_conflict"

    def test_payload_carries_match_count_and_paths(self, tmp_path):
        result = self._make_conflict_result(tmp_path / "conflict.yml")
        payload = discovery_dedup.build_discovery_dedup_conflict_payload(
            result, "find-leads", "[[test-list]]",
        )
        assert payload["match_count"] == 2
        assert sorted(payload["matched_note_paths"]) == sorted([
            "/tmp/alice.md", "/tmp/bob.md",
        ])

    def test_payload_carries_report_path(self, tmp_path):
        report = tmp_path / "conflict.yml"
        result = self._make_conflict_result(report)
        payload = discovery_dedup.build_discovery_dedup_conflict_payload(
            result, "find-leads", "[[test-list]]",
        )
        assert payload["report_path"] == str(report)

    def test_payload_carries_channel_none_and_emitted_by(self, tmp_path):
        result = self._make_conflict_result(tmp_path / "conflict.yml")
        payload = discovery_dedup.build_discovery_dedup_conflict_payload(
            result, "find-leads", "[[test-list]]",
        )
        assert payload["channel"] == "none"
        assert payload["_emitted_by"] == "discovery_dedup"

    def test_payload_carries_source_attribution(self, tmp_path):
        result = self._make_conflict_result(tmp_path / "conflict.yml")
        payload = discovery_dedup.build_discovery_dedup_conflict_payload(
            result, "find-funded-founders", "[[funded-2026]]",
        )
        assert payload["source_skill"] == "find-funded-founders"
        assert payload["source_list"] == "[[funded-2026]]"

    def test_rejects_non_conflict_result(self):
        not_dup = discovery_dedup.DedupResult(
            status="not_duplicate",
            candidate_partial=identity.IdentityKeys(),
        )
        with pytest.raises(ValueError, match="requires status='conflict'"):
            discovery_dedup.build_discovery_dedup_conflict_payload(
                not_dup, "find-leads", None,
            )


# ---------------------------------------------------------------------------
# Per-skill integration smoke test — find-leads canonical caller pattern
# ---------------------------------------------------------------------------


class TestPerSkillIntegrationSmoke:
    """ADR-0033 D152 — the per-skill integration discipline.

    The smoke test exercises the canonical caller pattern that
    skills/find-leads/SKILL.md documents (Phase 3e in the Week 2
    update). The pattern:

    .. code-block:: python

        result = discovery_dedup.check_dedup(
            candidate_partial=keys,
            source_skill="find-leads",
            source_list="[[<list>]]",
            people_dir=people_dir,
        )

        if result.should_skip_enrichment:
            # Emit the appropriate event class; DO NOT call Apollo / PDL / Reoon.
            payload = (
                discovery_dedup.build_discovery_dedup_hit_payload(...)
                if result.is_duplicate
                else discovery_dedup.build_discovery_dedup_conflict_payload(...)
            )
            led.append(payload)
            continue  # next candidate
        # else: proceed with enrichment as before
    """

    def test_caller_can_dispatch_on_should_skip_enrichment(self, vault):
        _write_person(
            vault["people_dir"], "Active", "Dylan",
            id="dylan-txa-li",
            identity_keys={"linkedin": "in/dylan-txa"},
        )

        # Simulate a discovery batch with TWO candidates: one
        # already-known + one new. The caller's loop should skip
        # enrichment on the duplicate + proceed on the new.
        candidates = [
            (
                "Dylan Teixeira",
                "linkedin.com/in/dylan-txa",
                None,
            ),  # duplicate
            (
                "Brand New Person",
                "linkedin.com/in/brand-new",
                None,
            ),  # not_duplicate
        ]

        emitted_events: list[dict] = []
        enrichment_called: list[str] = []

        for name, linkedin, email in candidates:
            keys = identity.compute_keys(
                name=name, linkedin_url=linkedin, email=email,
            )
            result = discovery_dedup.check_dedup(
                candidate_partial=keys,
                source_skill="find-leads",
                source_list="[[2026-05-24-test]]",
                people_dir=vault["people_dir"],
                conflicts_dir=vault["conflicts_dir"],
            )

            if result.should_skip_enrichment:
                if result.is_duplicate:
                    emitted_events.append(
                        discovery_dedup.build_discovery_dedup_hit_payload(
                            result, "find-leads", "[[2026-05-24-test]]",
                        )
                    )
                else:  # conflict
                    emitted_events.append(
                        discovery_dedup.build_discovery_dedup_conflict_payload(
                            result, "find-leads", "[[2026-05-24-test]]",
                        )
                    )
                continue
            # Simulate the enrichment call
            enrichment_called.append(name)

        # The duplicate path: one discovery_dedup_hit emitted, no
        # Apollo / PDL / Reoon call.
        assert len(emitted_events) == 1
        assert emitted_events[0]["type"] == "discovery_dedup_hit"
        assert emitted_events[0]["person_id"] == "dylan-txa-li"

        # The new-person path: enrichment proceeds.
        assert enrichment_called == ["Brand New Person"]

    def test_three_skills_one_day_same_person_consumes_one_check(self, vault):
        """Smoke-test the subset of the binding exit-criterion test
        (``TestPillarEExitCriterion::test_three_skills_one_day_consume
        _one_apollo_one_reoon_zero_duplicates``) that Week 2 ships in
        isolation.

        Three skills surface the same person in one day. Skill A is
        the first to discover; emits the enrollment via the
        post-enrichment path (simulated here by writing the Person
        note directly). Skills B + C consult the dedup primitive;
        BOTH see the duplicate + skip enrichment.
        """
        # Skill A's path: enrollment (simulated by directly writing).
        _write_person(
            vault["people_dir"], "Active", "Dylan",
            id="dylan-txa-li",
            identity_keys={"linkedin": "in/dylan-txa"},
        )

        # Skill B: surfaces same person via different source_list.
        candidate_b = identity.compute_keys(
            name="Dylan Teixeira",
            linkedin_url="linkedin.com/in/dylan-txa",
        )
        result_b = discovery_dedup.check_dedup(
            candidate_partial=candidate_b,
            source_skill="find-funded-founders",
            source_list="[[2026-05-24-funded]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result_b.is_duplicate is True

        # Skill C: surfaces same person via yet another source.
        candidate_c = identity.compute_keys(
            name="Dylan Teixeira",
            linkedin_url="linkedin.com/in/dylan-txa",
        )
        result_c = discovery_dedup.check_dedup(
            candidate_partial=candidate_c,
            source_skill="competitor-customers",
            source_list="[[2026-05-24-acme-customers]]",
            people_dir=vault["people_dir"],
            conflicts_dir=vault["conflicts_dir"],
        )
        assert result_c.is_duplicate is True

        # Both skills emit discovery_dedup_hit events with their
        # respective source attribution. The Pillar G "per-source
        # dedup-hit-rate" dashboard reads these to compute "how
        # much did each source rediscover already-known prospects?"
        payload_b = discovery_dedup.build_discovery_dedup_hit_payload(
            result_b, "find-funded-founders", "[[2026-05-24-funded]]",
        )
        payload_c = discovery_dedup.build_discovery_dedup_hit_payload(
            result_c, "competitor-customers", "[[2026-05-24-acme-customers]]",
        )
        assert payload_b["source_skill"] == "find-funded-founders"
        assert payload_c["source_skill"] == "competitor-customers"
        # Both point at the SAME existing Person.
        assert payload_b["person_id"] == "dylan-txa-li"
        assert payload_c["person_id"] == "dylan-txa-li"


# ---------------------------------------------------------------------------
# SOURCE_SKILLS enum + module constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """The module-level reserved constants per ADR-0033."""

    def test_source_skills_is_closed_set_of_five(self):
        """Per ADR-0032 D142. The five values are: find-leads,
        find-funded-founders, competitor-customers, research-prospect,
        manual. Future skills extend via coordinated ADR amendment."""
        assert discovery_dedup.SOURCE_SKILLS == frozenset({
            "find-leads",
            "find-funded-founders",
            "competitor-customers",
            "research-prospect",
            "manual",
        })

    def test_emitted_by_marker_reserved(self):
        """Per ADR-0010 D17 convention. The marker is the operator-
        facing filter for "events from the dedup primitive" in the
        cross-pillar surface audit's literal-string predicate."""
        assert discovery_dedup.EMITTED_BY == "discovery_dedup"

    def test_channel_value_is_none_per_d146(self):
        """Per ADR-0032 D146. Dedup is channel-agnostic; the explicit
        ``"none"`` makes the absence operator-visible."""
        assert discovery_dedup.CHANNEL_VALUE == "none"
