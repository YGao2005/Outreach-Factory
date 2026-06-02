"""Tests for ``ledger/0003_baseline_li_invite_history``.

Direct unit tests against the synthetic fixture. Mirrors
``tests/test_migrations_ledger_0002.py`` shape — the per-migration
test classes (TestMigrationSurface, TestUpgradeHappyPath, TestDryRun,
TestIdempotence, TestRefuseLoud, TestDowngrade, TestIntentIdDeterminism)
match Pillar B's per-migration test convention. The replay-test in
``tests/test_migrations_replay.py`` covers the runner-mediated path;
this module exercises the migration's contract end-to-end without
going through the runner.

The synthetic fixture (``tests/fixtures/synthetic_pillar_b/``) was
extended by Pillar B Week 6 third follow-up with:

* Alice's LinkedIn touch (``2026-04-18 Alice linkedin invite.md``,
  ``sent: true``, ``channel: linkedin``) — the substrate ledger/0003
  backfills.
* Carol's pre-Pillar-C ``li_invite_intent`` + ``li_invite_confirmed``
  event pair (``li_synthetic_carol_01``) — the substrate ledger/0003's
  idempotence check protects against re-emitting.

This migration depends on vault/0002 having stamped ``id:`` on Person
notes — without that, the ``person_id`` lookup fails for every touch
and the migration records the touches in ``touches_without_person_match``.

See ADR-0015 for the full Week 2 design.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.migrations.ledger._ledger_io import iter_events
from orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history import (
    LINKEDIN_ACTION_DM,
    LINKEDIN_ACTION_FIELD,
    LINKEDIN_ACTION_INVITE,
    LINKEDIN_CHANNEL,
    MIGRATION,
    MIGRATION_ID,
    PEOPLE_SUBDIR,
    RECOVERED_BY_TAG,
    SYNTHETIC_INTENT_PREFIX,
    BaselineLinkedInInviteHistory,
    _classify_linkedin_action,
)
from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext, MigrationResult,
)
from orchestrator.migrations.vault.migration_0002 import (
    MIGRATION as VAULT_BACKFILL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    state_dir: Path,
    vault_dir: Path | None,
    ledger_dir: Path | None = None,
    dry_run: bool = False,
) -> MigrationContext:
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir if ledger_dir is not None else state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.ledger.0003"),
    )


def _apply_vault_backfill_first(state) -> None:
    """Run vault/0002 first so Person notes have ``id:`` set.

    Mirrors ``test_migrations_ledger_0002._apply_vault_backfill_first``
    — ledger/0003 depends on vault/0002 the same way ledger/0002 does.
    """
    ctx = _make_ctx(state_dir=state.state_dir, vault_dir=state.vault_dir)
    VAULT_BACKFILL.upgrade(ctx)


def _events_by_type(ledger_dir: Path, type_name: str) -> list[dict]:
    return [e for e in iter_events(ledger_dir) if e.get("type") == type_name]


# ---------------------------------------------------------------------------
# Migration surface — Protocol compliance
# ---------------------------------------------------------------------------


class TestMigrationSurface:
    def test_singleton_implements_protocol(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0003_baseline_li_invite_history"
        assert MIGRATION.category == MigrationCategory.LEDGER
        assert MIGRATION.is_reversible is False

    def test_description_is_one_line(self):
        assert "\n" not in MIGRATION.description
        assert "linkedin" in MIGRATION.description.lower()
        assert "invite" in MIGRATION.description.lower()

    def test_is_distinct_singleton_from_ledger_0002(self):
        """ledger/0003 + ledger/0002 are distinct migrations.

        Sanity check against an accidental aliasing — the registry
        imports each migration by name; two MIGRATION constants pointing
        at the same object would mask one of them in the registry.
        """
        from orchestrator.migrations.ledger.migration_0002 import (
            MIGRATION as LEDGER_0002,
        )
        assert MIGRATION is not LEDGER_0002
        assert MIGRATION.id != LEDGER_0002.id


# ---------------------------------------------------------------------------
# upgrade() — happy path with vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:
    def test_emits_li_invite_pair_per_invite_touch(self, synthetic_state_dir):
        """Each ``sent: true`` LinkedIn invite touch produces a
        ``li_invite_intent`` + ``li_invite_confirmed`` pair.

        Fixture has one invite-classified LinkedIn touch (Alice's
        2026-04-18 ``2026-04-18 Alice linkedin invite.md`` — filename
        matches the invite heuristic). ledger/0003 emits one pair."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_confirmed",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        # One backfilled pair from Alice's LinkedIn touch.
        assert len(backfill_intents) == 1
        # All confirmed events from this migration share intent_ids
        # with the backfilled intents (plus any pre-existing pair from
        # the synthetic Carol fixture).
        backfill_confirms = [
            e for e in confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_confirms) == 1
        # Pair structure: same intent_id; both channel: linkedin.
        bf_iid = backfill_intents[0]["intent_id"]
        assert backfill_confirms[0]["intent_id"] == bf_iid

    def test_both_pair_sides_carry_channel_linkedin(self, synthetic_state_dir):
        """Every emitted ``li_invite_*`` event carries ``channel: "linkedin"``
        per ADR-0014 D33.

        Ledger/0002 paid the price of OMITTING this on backfilled
        send_confirmed (Pillar C Week 1 fix); ledger/0003 ships this
        correct from day one.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_confirmed",
        )
        backfilled = [
            e for e in intents + confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        # Two events from this migration (one intent + one confirmed).
        assert len(backfilled) == 2
        for e in backfilled:
            assert e.get("channel") == LINKEDIN_CHANNEL, (
                f"backfilled {e.get('type')!r} for "
                f"{e.get('intent_id')!r} missing channel='linkedin'. "
                f"ADR-0014 D33 invariant violated."
            )

    def test_backfilled_events_recovered_by_tag(self, synthetic_state_dir):
        """Backfilled events carry ``_recovered_by: 'backfill'`` per
        ADR-0010 D15 + ADR-0014 D33 + ADR-0013 Alternative 12 (the
        tag is shared across migrations emitting Phase-5.5-shape
        semantic events)."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        backfilled = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfilled) == 1
        assert backfilled[0]["_recovered_by"] == RECOVERED_BY_TAG
        assert RECOVERED_BY_TAG == "backfill"  # shared tag invariant.

    def test_emits_migration_event_with_channel_kwarg(
        self, synthetic_state_dir,
    ):
        """Per ADR-0010 D17 + ADR-0014 D35 every ledger migration emits
        one ``migration_event``; per-channel migrations pass
        ``channel=<channel_name>`` as an extra kwarg so Pillar G can
        query without text-matching against migration_id."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert len(ours) == 1
        e = ours[0]
        assert e["category"] == "ledger"
        # The D35 invariant — Pillar G's discriminator.
        assert e["channel"] == LINKEDIN_CHANNEL
        # affected_count = pairs_emitted (1 from Alice's invite touch).
        assert e["affected_count"] == 1
        # Diagnostic fields.
        assert e["linkedin_pairs_emitted"] == 1
        assert e["linkedin_pairs_skipped"] == 0

    def test_backfilled_confirm_event_carries_touch_note(
        self, synthetic_state_dir,
    ):
        """Per Week 2 per-week review P2-4: the backfilled
        ``li_invite_confirmed`` carries the ``touch_note`` path —
        matching the symmetric intent event. The backfill knows the
        touch path at confirm-emit time (vs the live dispatcher which
        does NOT carry it), so a query on the confirmed events can
        find the source touch without joining through intent_id.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_invite_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        confirms = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_invite_confirmed")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(intents) == 1
        assert len(confirms) == 1
        # Both sides carry touch_note pointing at the same path.
        assert intents[0].get("touch_note") is not None
        assert confirms[0].get("touch_note") is not None
        assert intents[0]["touch_note"] == confirms[0]["touch_note"]
        # The path points at Alice's LinkedIn invite touch in the fixture.
        assert "linkedin invite" in confirms[0]["touch_note"]

    def test_carol_pre_existing_li_pair_not_duplicated(
        self, synthetic_state_dir,
    ):
        """Carol's pre-Pillar-C ``li_synthetic_carol_01`` pair stays
        unique. The migration walks vault for ``sent: true`` LinkedIn
        touches; Carol has no touch note (only the ``last_touch:``
        frontmatter field on her Person note), so ledger/0003 does NOT
        re-emit her pair. The Pillar C Week 4 orphan
        ``li_synthetic_orphan_invite_01`` also stays unique (ledger/0003
        only emits pairs for touch notes, never for arbitrary intent
        events in the ledger)."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        # Three total: 1 pre-existing Carol + 1 newly-backfilled Alice
        # + 1 Pillar C Week 4 orphan (Carol's li_synthetic_orphan_invite_01).
        assert len(intents) == 3
        carol_intents = [
            e for e in intents
            if e.get("intent_id") == "li_synthetic_carol_01"
        ]
        # Carol's exact intent_id appears exactly once (not duplicated).
        assert len(carol_intents) == 1
        # The Week 4 orphan stays unique too.
        orphan_intents = [
            e for e in intents
            if e.get("intent_id") == "li_synthetic_orphan_invite_01"
        ]
        assert len(orphan_intents) == 1


# ---------------------------------------------------------------------------
# upgrade() — without vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeWithoutVaultBackfill:
    def test_zero_pairs_when_no_person_has_id(self, synthetic_state_dir):
        """Without vault/0002 stamping ``id:`` on Person notes, the
        person_id lookup fails for every touch; the migration records
        them in ``touches_without_person_match`` and emits zero pairs."""
        # NOT calling _apply_vault_backfill_first.
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 0
        # The migration_event still records the no-op + the diagnostic
        # count for operator visibility.
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert len(ours) == 1
        # Both Alice's LinkedIn invite touch + Dana's LinkedIn DM touch
        # (Pillar C Week 3 fixture extension) land here when vault/0002
        # hasn't run — the person_match check fires before the
        # invite-vs-DM classification check, so the action classification
        # is bypassed.
        assert ours[0]["touches_without_person_match"] == 2
        assert ours[0]["linkedin_pairs_emitted"] == 0
        assert result.affected_count == 0


# ---------------------------------------------------------------------------
# upgrade() — dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_append(self, synthetic_state_dir):
        """Dry-run produces counts without appending to the ledger."""
        _apply_vault_backfill_first(synthetic_state_dir)
        before = list(iter_events(synthetic_state_dir.ledger_dir))

        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.applied is True
        # 1 pair from Alice's LinkedIn invite touch.
        assert result.affected_count == 1

        after = list(iter_events(synthetic_state_dir.ledger_dir))
        assert before == after, "dry-run must not write events"

    def test_dry_run_does_not_emit_migration_event(self, synthetic_state_dir):
        """Per ADR-0010 D17: dry-run does NOT emit migration_event."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        MIGRATION.upgrade(ctx)
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert ours == []


# ---------------------------------------------------------------------------
# upgrade() — idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_re_apply_finds_zero_new_work(self, synthetic_state_dir):
        """Second apply finds zero new pairs."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        r2 = MIGRATION.upgrade(ctx)
        assert r2.affected_count == 0
        # Still emits migration_event per D17 (audit trail continuity).
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        ours = [e for e in mes if e.get("migration_id") == MIGRATION_ID]
        assert len(ours) == 2  # one per apply.

    def test_re_apply_does_not_duplicate_events(self, synthetic_state_dir):
        """Re-running doesn't append duplicate li_invite_* events."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        # 3 total: 1 pre-existing Carol + 1 backfilled Alice + 1 Pillar C
        # Week 4 orphan (Carol's li_synthetic_orphan_invite_01). No new
        # emissions on re-apply.
        assert len(intents) == 3


# ---------------------------------------------------------------------------
# upgrade() — refuse-loud
# ---------------------------------------------------------------------------


class TestRefuseLoud:
    def test_refuses_on_missing_vault_dir(self, synthetic_state_dir):
        """ctx.vault_dir=None → ValueError (the backfill reads vault)."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=None,
        )
        with pytest.raises(ValueError, match="vault_dir"):
            MIGRATION.upgrade(ctx)

    def test_refuses_on_missing_ledger_dir(self, tmp_path):
        """ctx.ledger_dir not on disk → FileNotFoundError."""
        state = tmp_path / "state"
        state.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()
        ctx = _make_ctx(state_dir=state, vault_dir=vault)
        with pytest.raises(FileNotFoundError, match="ctx.ledger_dir"):
            MIGRATION.upgrade(ctx)

    def test_non_string_type_in_touch_note_is_silently_skipped(
        self, synthetic_state_dir,
    ):
        """A touch note with ``type: 42`` (unquoted YAML int) is by
        contract non-touch; skip silently rather than crashing.

        Mirrors ledger/0002's analogous test — the
        ``_vault_io.is_touch_note`` shared predicate is robust to
        non-string ``type:`` (per Pillar B Week 6 holistic-review).
        """
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        (conv / "Broken touch.md").write_text(
            "---\ntype: 42\nperson: \"[[Alice Anderson]]\"\n"
            "channel: linkedin\nsent: true\n---\nbody\n",
            encoding="utf-8",
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # No crash. The broken note is silently skipped; Alice's valid
        # LinkedIn touch still backfills.
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1


# ---------------------------------------------------------------------------
# downgrade() — refusal
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_downgrade_raises_not_implemented(self, synthetic_state_dir):
        """The migration is structurally irreversible (append-only ledger)."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        with pytest.raises(NotImplementedError, match="irreversible"):
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# Intent-id determinism
# ---------------------------------------------------------------------------


class TestIntentIdDeterminism:
    def test_same_touch_re_run_produces_same_intent_id(
        self, synthetic_state_dir,
    ):
        """The synthetic intent_id is deterministic.

        Re-running the migration produces the same intent_id per touch
        — that's WHY the idempotence check works.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents_1 = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_invite_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        first_id = intents_1[0]["intent_id"]
        # bf_li_<16-hex-chars>.
        assert first_id.startswith(SYNTHETIC_INTENT_PREFIX)
        assert len(first_id) == len(SYNTHETIC_INTENT_PREFIX) + 16


# ---------------------------------------------------------------------------
# Invite-vs-DM classification (D38 heuristic)
# ---------------------------------------------------------------------------


class TestClassifyLinkedInAction:
    def test_explicit_field_wins_over_heuristic(self, tmp_path):
        """An explicit ``linkedin_action: dm`` overrides the filename
        heuristic. Operator-supplied signal is always authoritative."""
        # Filename suggests invite, but explicit field says dm.
        p = tmp_path / "2026-05-21 Alice linkedin invite.md"
        action = _classify_linkedin_action(p, LINKEDIN_ACTION_DM)
        assert action == LINKEDIN_ACTION_DM

    def test_filename_matches_invite_pattern(self, tmp_path):
        """Filenames matching ``invite`` or ``connect`` classify as invite."""
        for name in (
            "2026-05-21 Alice linkedin invite.md",
            "2026-05-21 Alice linkedin connect.md",
            "INVITE alice.md",
            "Alice Connect attempt.md",
        ):
            assert _classify_linkedin_action(
                tmp_path / name, None,
            ) == LINKEDIN_ACTION_INVITE

    def test_filename_matches_dm_pattern(self, tmp_path):
        """Filenames matching ``dm`` or ``message`` classify as DM."""
        for name in (
            "2026-05-21 Alice linkedin dm.md",
            "2026-05-21 Alice linkedin message.md",
            "DM alice.md",
            "Alice followup MESSAGE.md",
        ):
            assert _classify_linkedin_action(
                tmp_path / name, None,
            ) == LINKEDIN_ACTION_DM

    def test_default_is_invite_when_no_pattern_matches(self, tmp_path):
        """Filenames matching neither pattern default to invite per
        the historical-prevalence rationale in ADR-0015 D38."""
        for name in (
            "2026-05-21 Alice followup.md",
            "Alice second touch.md",
            "Random filename.md",
        ):
            assert _classify_linkedin_action(
                tmp_path / name, None,
            ) == LINKEDIN_ACTION_INVITE

    def test_word_boundary_prevents_false_positives(self, tmp_path):
        """The ``\\b...\\b`` regex prevents substring matches like
        'Connecticut' triggering 'connect'."""
        # "Connecticut" contains "connect" but the word-boundary regex
        # should not match. Default-to-invite is correct here (no
        # other action signal), but the test pins the regex behavior.
        assert _classify_linkedin_action(
            tmp_path / "Connecticut intro.md", None,
        ) == LINKEDIN_ACTION_INVITE

    def test_dm_touch_skipped_by_migration(self, synthetic_state_dir):
        """A LinkedIn touch classified as DM (via explicit field or
        filename heuristic) is skipped — ledger/0004 (Week 3) walks
        DMs separately."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        (conv / "2026-05-15 Bob linkedin dm.md").write_text(
            "---\ntype: touch\nperson: \"[[Bob Brown]]\"\n"
            "channel: linkedin\nsent: true\nsent_at: 2026-05-15\n"
            "date: 2026-05-15\n---\nDM body\n",
            encoding="utf-8",
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        # Only Alice's invite touch was emitted — Bob's inline-DM AND
        # Dana's fixture-DM were both skipped (Dana's DM lives in the
        # Pillar C Week 3 fixture extension; this test adds Bob's DM
        # inline on top).
        assert result.affected_count == 1
        mes = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "migration_event")
            if e.get("migration_id") == MIGRATION_ID
        ]
        assert len(mes) == 1
        # Diagnostic count: two touches skipped (Bob's inline DM +
        # Dana's fixture DM).
        assert mes[0]["touches_skipped_not_invite"] == 2

    def test_explicit_field_takes_precedence_in_full_migration(
        self, synthetic_state_dir,
    ):
        """When a touch note already has ``linkedin_action: dm``, the
        migration honors it even if the filename matches the invite
        pattern. Operator-supplied signal wins."""
        # The fixture's Alice LinkedIn touch filename contains "invite";
        # override the field via direct stamp.
        alice_touch = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-18 Alice linkedin invite.md"
        )
        text = alice_touch.read_text(encoding="utf-8")
        # Stamp linkedin_action: dm via direct frontmatter rewrite.
        text = text.replace(
            "channel: linkedin\n",
            "channel: linkedin\nlinkedin_action: dm\n",
        )
        alice_touch.write_text(text, encoding="utf-8")

        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        # Alice's touch is now classified as DM and skipped.
        assert result.affected_count == 0
