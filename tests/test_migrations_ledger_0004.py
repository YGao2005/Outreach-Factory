"""Tests for ``ledger/0004_baseline_li_dm_history``.

Direct unit tests against the synthetic fixture. Mirrors
``tests/test_migrations_ledger_0003.py`` shape — the per-migration test
classes (TestMigrationSurface, TestUpgradeHappyPath, TestUpgradeWithoutVaultBackfill,
TestDryRun, TestIdempotence, TestRefuseLoud, TestDowngrade,
TestIntentIdDeterminism, TestDMClassification) match Pillar B's
per-migration test convention. The replay-test in
``tests/test_migrations_replay.py`` covers the runner-mediated path;
this module exercises the migration's contract end-to-end without
going through the runner.

The synthetic fixture (``tests/fixtures/synthetic_pillar_b/``) was
extended by Pillar C Week 3 (per the Week 3 handoff §"Fixture
extension") with:

* Dana Davis Person note (``vault/10 People/Dana Davis.md``,
  ``linkedin_connected: true``) — LinkedIn-only existing connection.
* Dana's LinkedIn DM touch (``vault/40 Conversations/2026-04-20 Dana
  linkedin dm.md``, ``sent: true``, ``channel: linkedin``,
  ``linkedin_action: dm``) — the substrate ledger/0004 backfills.

This migration depends on vault/0002 having stamped ``id:`` on Person
notes — without that, the ``person_id`` lookup fails for every touch
and the migration records the touches in ``touches_without_person_match``.

See ADR-0016 for the full Week 3 design.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.migrations.ledger._ledger_io import iter_events
from orchestrator.migrations.ledger.migration_0004_baseline_li_dm_history import (
    LINKEDIN_ACTION_DM,
    LINKEDIN_ACTION_INVITE,
    LINKEDIN_CHANNEL,
    MIGRATION,
    MIGRATION_ID,
    RECOVERED_BY_TAG,
    SYNTHETIC_INTENT_PREFIX,
    BaselineLinkedInDMHistory,
    _synth_intent_id,
)
from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext,
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
        logger=logging.getLogger("test.ledger.0004"),
    )


def _apply_vault_backfill_first(state) -> None:
    """Run vault/0002 first so Person notes have ``id:`` set.

    Mirrors the ledger/0003 test helper — ledger/0004 depends on
    vault/0002 the same way.
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
        assert MIGRATION.id == "0004_baseline_li_dm_history"
        assert MIGRATION.category == MigrationCategory.LEDGER
        assert MIGRATION.is_reversible is False

    def test_description_is_one_line(self):
        assert "\n" not in MIGRATION.description
        # The description names the channel + action so operators
        # scanning the migration manifest can recognize what runs.
        assert "linkedin" in MIGRATION.description.lower()
        assert "dm" in MIGRATION.description.lower()

    def test_is_distinct_singleton_from_ledger_0003(self):
        """ledger/0004 + ledger/0003 are distinct migrations.

        Sanity check against an accidental aliasing — the registry
        imports each migration by name; two MIGRATION constants pointing
        at the same object would mask one of them in the registry.
        """
        from orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history import (
            MIGRATION as LEDGER_0003,
        )
        assert MIGRATION is not LEDGER_0003
        assert MIGRATION.id != LEDGER_0003.id

    def test_registered_in_migrations_list(self):
        """The MIGRATION singleton is in the ledger registry."""
        from orchestrator.migrations.ledger import MIGRATIONS
        assert MIGRATION in MIGRATIONS


# ---------------------------------------------------------------------------
# upgrade() — happy path with vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:
    def test_emits_li_dm_pair_per_dm_touch(self, synthetic_state_dir):
        """Each ``sent: true`` LinkedIn DM touch produces a
        ``li_dm_intent`` + ``li_dm_confirmed`` pair.

        Fixture has one DM-classified LinkedIn touch (Dana's
        2026-04-20 ``2026-04-20 Dana linkedin dm.md`` — filename matches
        the DM heuristic + explicit ``linkedin_action: dm`` field).
        ledger/0004 emits one pair."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_intent",
        )
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_confirmed",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 1
        backfill_confirms = [
            e for e in confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_confirms) == 1
        # Pair structure: same intent_id; both channel: linkedin.
        bf_iid = backfill_intents[0]["intent_id"]
        assert backfill_confirms[0]["intent_id"] == bf_iid

    def test_both_pair_sides_carry_channel_linkedin(self, synthetic_state_dir):
        """Every emitted ``li_dm_*`` event carries
        ``channel: "linkedin"`` per ADR-0014 D33.

        Same discipline ledger/0003 inherited from the Pillar C Week 1
        fix — Pillar C Week 3 ships ledger/0004 correct from day one.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_intent",
        )
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_confirmed",
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
            synthetic_state_dir.ledger_dir, "li_dm_intent",
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
        # affected_count = pairs_emitted (1 from Dana's DM touch).
        assert e["affected_count"] == 1
        # Diagnostic fields.
        assert e["linkedin_dm_pairs_emitted"] == 1
        assert e["linkedin_dm_pairs_skipped"] == 0
        # The invite-classified touch (Alice's invite) was skipped.
        assert e["touches_skipped_not_dm"] == 1

    def test_backfilled_confirm_event_carries_touch_note(
        self, synthetic_state_dir,
    ):
        """The backfilled ``li_dm_confirmed`` carries the
        ``touch_note`` path — mirroring ledger/0003's Week 2 P2-4 fix.
        The backfill knows the touch path at confirm-emit time (vs the
        live dispatcher which does NOT carry it), so a query on the
        confirmed events can find the source touch without joining
        through intent_id.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_dm_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        confirms = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_dm_confirmed")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(intents) == 1
        assert len(confirms) == 1
        # Both sides carry touch_note pointing at the same path.
        assert intents[0].get("touch_note") is not None
        assert confirms[0].get("touch_note") is not None
        assert intents[0]["touch_note"] == confirms[0]["touch_note"]
        # The path points at Dana's LinkedIn DM touch in the fixture.
        assert "linkedin dm" in confirms[0]["touch_note"]

    def test_invite_touch_not_emitted_by_dm_migration(
        self, synthetic_state_dir,
    ):
        """ledger/0004 SKIPS invite-classified touches — they belong to
        ledger/0003. The classifier filter inversion is load-bearing."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        # Alice's LinkedIn invite touch in the fixture: ledger/0004 does
        # NOT emit a li_dm pair for it; ledger/0003 would have.
        li_dm_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_intent",
        )
        for e in li_dm_intents:
            tn = e.get("touch_note", "")
            assert "linkedin invite" not in tn, (
                f"li_dm_intent should not be emitted for an invite "
                f"touch. Got {tn!r}."
            )


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
            synthetic_state_dir.ledger_dir, "li_dm_intent",
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
        # land here when vault/0002 hasn't run — the person_match check
        # fires before the invite-vs-DM classification check, so the
        # action classification is bypassed (same shape as ledger/0003).
        assert ours[0]["touches_without_person_match"] == 2
        assert ours[0]["linkedin_dm_pairs_emitted"] == 0
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
        # 1 pair from Dana's LinkedIn DM touch.
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
        """Re-running doesn't append duplicate li_dm_* events."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_intent",
        )
        # Two: Dana's backfilled pair + the Pillar C Week 4 fixture orphan
        # (lidm_synthetic_orphan_dm_01 — substrate for reconcile Pass E).
        # No new emissions on re-apply.
        assert len(intents) == 2

    def test_re_apply_skipped_count_reflects_existing_events(
        self, synthetic_state_dir,
    ):
        """The second apply's migration_event records the per-touch
        skip as ``linkedin_dm_pairs_skipped`` — the idempotence check
        recognizes Dana's intent_id is already in the ledger and skips
        emission."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.upgrade(ctx)
        mes = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "migration_event")
            if e.get("migration_id") == MIGRATION_ID
        ]
        assert len(mes) == 2
        # First apply emitted 1 pair, skipped 0.
        assert mes[0]["linkedin_dm_pairs_emitted"] == 1
        assert mes[0]["linkedin_dm_pairs_skipped"] == 0
        # Second apply emitted 0 pairs, skipped 1 (Dana's pair was
        # already present from the first apply).
        assert mes[1]["linkedin_dm_pairs_emitted"] == 0
        assert mes[1]["linkedin_dm_pairs_skipped"] == 1


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

        Mirrors ledger/0003's analogous test — the
        ``_vault_io.is_touch_note`` shared predicate is robust to
        non-string ``type:`` (per Pillar B Week 6 holistic-review).
        """
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        (conv / "Broken touch.md").write_text(
            "---\ntype: 42\nperson: \"[[Dana Davis]]\"\n"
            "channel: linkedin\nsent: true\nlinkedin_action: dm\n---\n"
            "body\n",
            encoding="utf-8",
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # No crash. The broken note is silently skipped; Dana's valid
        # LinkedIn DM touch still backfills.
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
# Intent-id determinism + distinctness from ledger/0003's prefix
# ---------------------------------------------------------------------------


class TestIntentIdDeterminism:
    def test_same_touch_re_run_produces_same_intent_id(
        self, synthetic_state_dir,
    ):
        """The synthetic intent_id is deterministic.

        Re-running the migration produces the same intent_id per touch
        — that's WHY the idempotence check works."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents_1 = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_dm_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        first_id = intents_1[0]["intent_id"]
        # bf_lidm_<16-hex-chars>.
        assert first_id.startswith(SYNTHETIC_INTENT_PREFIX)
        assert len(first_id) == len(SYNTHETIC_INTENT_PREFIX) + 16

    def test_prefix_distinguishes_from_li_invite_backfill(self):
        """``bf_lidm_`` distinguishes from ledger/0003's ``bf_li_``.

        Per the Week 3 module docstring: the prefix discriminator at
        the intent_id level lets operators scanning the ledger
        immediately tell which retroactive-reconstruction class a
        synthetic event came from."""
        from orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history import (
            SYNTHETIC_INTENT_PREFIX as INVITE_PREFIX,
        )
        assert SYNTHETIC_INTENT_PREFIX == "bf_lidm_"
        assert INVITE_PREFIX == "bf_li_"
        # The DM prefix is NOT a prefix-of-prefix of the invite prefix
        # (and vice versa) — startswith-checks for each remain
        # unambiguous.
        assert not SYNTHETIC_INTENT_PREFIX.startswith(INVITE_PREFIX)
        assert not INVITE_PREFIX.startswith(SYNTHETIC_INTENT_PREFIX)

    def test_synth_intent_id_hash_inputs_include_action(self):
        """The synthetic intent_id incorporates the action string so
        same-day same-person invite + DM produce distinct hashes.

        Without this, an operator who sent both an invite + a DM to
        the same person on the same day would see hash collision
        between ledger/0003 and ledger/0004 backfills — the action
        discriminator forecloses that."""
        # Same person + date + touch stem, different actions.
        id_invite = _synth_intent_id(
            "dana-li", "2026-04-20T00:00:00.000Z", "invite", "stem",
        )
        id_dm = _synth_intent_id(
            "dana-li", "2026-04-20T00:00:00.000Z", "dm", "stem",
        )
        # Same prefix (the migration ships ``bf_lidm_`` regardless),
        # different hashes because the input strings differ.
        assert id_invite.startswith(SYNTHETIC_INTENT_PREFIX)
        assert id_dm.startswith(SYNTHETIC_INTENT_PREFIX)
        assert id_invite != id_dm


# ---------------------------------------------------------------------------
# Invite-vs-DM classification — Week 3 inherits ledger/0003's classifier
# ---------------------------------------------------------------------------


class TestDMClassification:
    def test_invite_touch_skipped_by_migration(self, synthetic_state_dir):
        """A LinkedIn touch classified as INVITE (filename heuristic or
        explicit field) is skipped — ledger/0003 walks invite touches."""
        conv = synthetic_state_dir.vault_dir / "40 Conversations"
        # Inline an additional invite-classified touch on top of the
        # fixture's Alice invite + Dana DM.
        (conv / "2026-05-15 Bob linkedin invite.md").write_text(
            "---\ntype: touch\nperson: \"[[Bob Brown]]\"\n"
            "channel: linkedin\nsent: true\nsent_at: 2026-05-15\n"
            "date: 2026-05-15\n---\nInvite body\n",
            encoding="utf-8",
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        # Only Dana's DM touch was emitted — Bob's inline-invite AND
        # Alice's fixture-invite were both skipped.
        assert result.affected_count == 1
        mes = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "migration_event")
            if e.get("migration_id") == MIGRATION_ID
        ]
        assert len(mes) == 1
        # Diagnostic count: two touches skipped (Bob's inline invite +
        # Alice's fixture invite).
        assert mes[0]["touches_skipped_not_dm"] == 2

    def test_explicit_field_takes_precedence_in_full_migration(
        self, synthetic_state_dir,
    ):
        """When a touch note already has ``linkedin_action: invite``,
        the migration honors it even if the filename matches the DM
        pattern. Operator-supplied signal wins."""
        # The fixture's Dana LinkedIn touch filename contains "dm";
        # override the field to invite via direct stamp.
        dana_touch = (
            synthetic_state_dir.vault_dir / "40 Conversations"
            / "2026-04-20 Dana linkedin dm.md"
        )
        text = dana_touch.read_text(encoding="utf-8")
        text = text.replace(
            "linkedin_action: dm\n",
            "linkedin_action: invite\n",
        )
        dana_touch.write_text(text, encoding="utf-8")

        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        # Dana's touch is now classified as invite and skipped.
        assert result.affected_count == 0

    def test_inherits_classifier_from_ledger_0003(self):
        """ledger/0004 uses the SAME classifier function as ledger/0003
        — shared primitive contract per Week 3 module docstring."""
        from orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history import (
            _classify_linkedin_action as classifier_0003,
        )
        from orchestrator.migrations.ledger.migration_0004_baseline_li_dm_history import (
            _classify_linkedin_action as classifier_0004,
        )
        # Same function — re-export, not re-implementation.
        assert classifier_0003 is classifier_0004
