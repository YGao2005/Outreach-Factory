"""Tests for ``ledger/0002_backfill_send_history``.

Direct unit tests against the synthetic fixture. The replay-test in
``tests/test_migrations_replay.py`` covers the runner-mediated path;
this module exercises the migration's contract end-to-end without
going through the runner.

The synthetic fixture (``tests/fixtures/synthetic_pillar_b/``) is the
canonical before-state: three Person notes (Alice has linkedin+email
+ matching touch; Bob has email only + no touch; Carol has linkedin
only + last_touch with NO matching touch → orphan). The pre-existing
ledger has one orphan ``send_intent`` unrelated to the backfill (for
``ledger/0001`` to close).

This migration depends on vault/0002 having stamped ``id:`` on Person
notes — without that, ``enrolled`` events are not emitted (the
migration records the persons in ``persons_without_id`` for operator
visibility, then emits the ``migration_event`` audit trail).

See ADR-0013 for the synthetic-replay vehicle design.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.migrations.ledger._ledger_io import iter_events
from orchestrator.migrations.ledger.migration_0002 import (
    BackfillSendHistory,
    CONVERSATIONS_SUBDIR,
    MIGRATION,
    MIGRATION_ID,
    PEOPLE_SUBDIR,
    RECOVERED_BY_TAG,
    SYNTHETIC_INTENT_PREFIX,
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
    """Construct a MigrationContext for direct migration invocation."""
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir if ledger_dir is not None else state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.ledger.0002"),
    )


def _apply_vault_backfill_first(state: "SyntheticState") -> None:
    """Run vault/0002 first so Person notes have ``id:`` set.

    Mirrors the cross-category dependency documented in ADR-0013 D27 +
    the runner's ``_DEFAULT_APPLY_ORDER`` (VAULT → LEDGER → POLICY).
    Direct-call tests for ledger/0002 reproduce that order manually.
    """
    ctx = _make_ctx(state_dir=state.state_dir, vault_dir=state.vault_dir)
    VAULT_BACKFILL.upgrade(ctx)


def _events_by_type(ledger_dir: Path, type_name: str) -> list[dict]:
    """Read all events of a given type from the ledger dir."""
    return [e for e in iter_events(ledger_dir) if e.get("type") == type_name]


# ---------------------------------------------------------------------------
# Migration surface — Protocol compliance
# ---------------------------------------------------------------------------


class TestMigrationSurface:
    def test_singleton_implements_protocol(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0002_backfill_send_history"
        assert MIGRATION.category == MigrationCategory.LEDGER
        assert MIGRATION.is_reversible is False

    def test_description_is_one_line(self):
        assert "\n" not in MIGRATION.description
        assert "backfill replay" in MIGRATION.description.lower()


# ---------------------------------------------------------------------------
# upgrade() — happy path with vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:
    def test_emits_enrolled_per_person_with_id(self, synthetic_state_dir):
        """One enrolled event per Person note with id (6 in the fixture
        as of Pillar C Week 6:
        Alice/Bob/Carol/Dana/Evan/Fiona)."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.applied is True
        enrolled = _events_by_type(synthetic_state_dir.ledger_dir, "enrolled")
        assert len(enrolled) == 6
        for e in enrolled:
            assert e["_recovered_by"] == RECOVERED_BY_TAG
            assert "person_id" in e
            assert "ts" in e

    def test_emits_send_pair_per_touch(self, synthetic_state_dir):
        """Touch notes with sent:true produce send_intent+send_confirmed.

        Fixture has five backfill-eligible touches (Pillar B Week 6
        second follow-up + Pillar C Week 3 + Week 5 + Week 6 fixture
        extensions): Alice's email touch on 2026-04-10, Alice's
        LinkedIn invite touch on 2026-04-18, Dana's LinkedIn DM touch
        on 2026-04-20, Evan's Twitter DM touch on 2026-04-22, and
        Fiona's calendar booking touch on 2026-04-25. The pre-existing
        orphan ``send_intent`` would be closed by ledger/0001 (not run
        here), so it stays."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(synthetic_state_dir.ledger_dir, "send_intent")
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 5
        assert len(confirms) == 5
        # The set of channels covers Alice's email touch + Alice's
        # LinkedIn invite touch + Dana's LinkedIn DM touch + Evan's
        # Twitter DM touch + Fiona's calendar booking touch. ledger/0002
        # is channel-agnostic — it emits a generic
        # send_intent/send_confirmed pair regardless of action; Week 2's
        # ledger/0003 + Week 3's ledger/0004 + Week 5's ledger/0005 +
        # Week 6's ledger/0006 emit per-channel shapes additively.
        bf_channels = [e["channel"] for e in backfill_intents]
        assert sorted(bf_channels) == [
            "calendar", "email", "linkedin", "linkedin", "twitter",
        ]
        confirm_ids = {c["intent_id"] for c in confirms}
        for bf in backfill_intents:
            assert bf["_recovered_by"] == RECOVERED_BY_TAG
            assert bf["intent_id"] in confirm_ids
        for c in confirms:
            assert c["_recovered_by"] == RECOVERED_BY_TAG

    def test_backfilled_send_confirmed_carries_channel_from_paired_intent(
        self, synthetic_state_dir,
    ):
        """Every backfilled ``send_confirmed`` carries the same ``channel``
        field as its paired ``send_intent``.

        Production ``send_queued.py:gated_send_one`` stamps ``channel``
        on both sides of the pair. The backfill must mirror or the
        ADR-0003 ``CrossChannelTouchRule`` cannot discriminate
        backfilled events — its safety check skips events whose
        ``channel`` is not in ``consider_channels``. ADR-0014 D33
        pins this as the load-bearing coherence invariant for
        Pillar C; this test is the Pillar C Week 1 regression pin
        for the BACKFILL path specifically.

        Scope: this test covers the ledger/0002-backfilled path only
        (events whose intent_id carries the ``SYNTHETIC_INTENT_PREFIX``
        from ledger/0002). The broader gate that covers every
        send-family event from any source (production dispatchers,
        future migrations, reconcile) is
        ``tests/test_multi_channel_coherence.py::TestEmailChannel::test_every_send_family_event_carries_a_channel_field``.
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(synthetic_state_dir.ledger_dir, "send_intent")
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        intent_channel_by_id = {
            e["intent_id"]: e["channel"] for e in backfill_intents
        }
        for c in confirms:
            iid = c["intent_id"]
            assert iid in intent_channel_by_id, (
                f"send_confirmed {iid!r} has no paired backfill intent — "
                f"a pair lost its channel correlation."
            )
            assert c.get("channel") == intent_channel_by_id[iid], (
                f"send_confirmed {iid!r} channel={c.get('channel')!r} "
                f"does not match its paired send_intent channel "
                f"{intent_channel_by_id[iid]!r}. ADR-0003 cross-channel "
                f"rule depends on both sides carrying the same channel."
            )

    def test_emits_orphan_for_carol(self, synthetic_state_dir):
        """Carol has last_touch but no touch note → send_confirmed_orphan."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        orphans = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed_orphan",
        )
        assert len(orphans) == 1
        o = orphans[0]
        assert o["_recovered_by"] == RECOVERED_BY_TAG
        assert "Carol Cole" in o.get("note_path", "")
        assert o["ts"].startswith("2026-04-15")

    def test_emits_migration_event(self, synthetic_state_dir):
        """Per ADR-0010 D17 every ledger migration emits one migration_event."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        assert len(mes) == 1
        e = mes[0]
        assert e["migration_id"] == MIGRATION_ID
        assert e["category"] == "ledger"
        # affected_count = 6 enrolled (Alice/Bob/Carol/Dana/Evan/Fiona)
        # + 5 send-pairs (Alice email + Alice linkedin invite + Dana
        # linkedin DM + Evan Twitter DM + Fiona calendar booking per the
        # Pillar C Week 3 + Week 5 + Week 6 fixture extensions) +
        # 1 orphan (Carol) = 12
        assert e["affected_count"] == 12
        # Diagnostic counts.
        assert e["enrolled_emitted"] == 6
        assert e["sends_emitted"] == 5
        assert e["orphans_emitted"] == 1

    def test_alice_touch_does_not_become_orphan(self, synthetic_state_dir):
        """Alice has a touch note matching her last_touch — no orphan emitted."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        orphans = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed_orphan",
        )
        for o in orphans:
            assert "Alice" not in o.get("note_path", "")

    def test_affected_count_includes_all_three_classes(
        self, synthetic_state_dir,
    ):
        """affected_count = enrolled + send-pairs + orphans (NOT migration_event)."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        # 6 enrolled + 5 send-pairs + 1 orphan = 12
        assert result.affected_count == 12
        assert "6 enrolled" in result.notes
        assert "5 send-pair" in result.notes
        assert "1 orphan" in result.notes


# ---------------------------------------------------------------------------
# upgrade() — without vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeWithoutVaultBackfill:
    def test_emits_no_enrolled_when_no_person_has_id(
        self, synthetic_state_dir,
    ):
        """Person notes without id are tracked in persons_without_id."""
        # Note: NOT calling _apply_vault_backfill_first — Person notes
        # don't have id yet.
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        # Zero enrolled because no Person note has id.
        enrolled = _events_by_type(synthetic_state_dir.ledger_dir, "enrolled")
        assert enrolled == []
        # The migration_event still records what it tried.
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        assert len(mes) == 1
        assert mes[0]["persons_without_id"] == 6
        assert mes[0]["enrolled_emitted"] == 0
        # No touches matched either (touches use name_to_id which is
        # empty when no Person has id). Alice's email + Alice's
        # LinkedIn invite + Dana's LinkedIn DM + Evan's Twitter DM +
        # Fiona's calendar booking touches are all tallied here
        # (Pillar B + Pillar C Week 3 + Week 5 + Week 6 fixture
        # extensions).
        assert mes[0]["touches_without_person_match"] == 5
        # affected_count is zero.
        assert result.affected_count == 0


# ---------------------------------------------------------------------------
# upgrade() — dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_append(self, synthetic_state_dir):
        """Dry-run produces counts without appending to the ledger."""
        _apply_vault_backfill_first(synthetic_state_dir)
        # Snapshot existing events.
        before = list(iter_events(synthetic_state_dir.ledger_dir))

        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.applied is True
        # 6 enrolled + 5 send-pairs + 1 orphan = 12 (Pillar C Week 3
        # added Dana + her DM touch; Week 5 added Evan + his Twitter
        # DM touch; Week 6 added Fiona + her calendar booking touch).
        assert result.affected_count == 12

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
        assert mes == []


# ---------------------------------------------------------------------------
# upgrade() — idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_re_apply_finds_zero_new_work(self, synthetic_state_dir):
        """Second apply finds zero new enrolled / send-pair / orphan."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        r2 = MIGRATION.upgrade(ctx)
        # All emits skipped on re-run.
        assert r2.affected_count == 0
        # Still emits migration_event per D17 (audit trail continuity).
        mes = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        # 2 total — one per apply.
        assert len(mes) == 2

    def test_re_apply_does_not_duplicate_events(self, synthetic_state_dir):
        """Re-running doesn't append duplicate enrolled / send / orphan events."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        MIGRATION.upgrade(ctx)
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir, "enrolled")) == 6
        # send_intents from backfill (excluding the pre-existing
        # orphan that doesn't carry the bf_ prefix).
        bf_intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "send_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        # Fixture has 5 backfill-eligible touches (Alice email + Alice
        # LinkedIn invite + Dana LinkedIn DM + Evan Twitter DM +
        # Fiona calendar booking). Re-apply doesn't duplicate.
        assert len(bf_intents) == 5
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed")) == 5
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir,
            "send_confirmed_orphan",
        )) == 1


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
        # Note: state/ledger NOT created — the runner default would
        # create it via state_dir/ledger but our direct ctx points at
        # state/ledger which doesn't exist.
        ctx = _make_ctx(state_dir=state, vault_dir=vault)
        with pytest.raises(FileNotFoundError, match="ctx.ledger_dir"):
            MIGRATION.upgrade(ctx)

    def test_non_string_type_in_person_note_is_silently_skipped(
        self, synthetic_state_dir,
    ):
        """A Person note with ``type: 42`` (unquoted YAML int) is by
        contract non-Person; skip silently rather than crashing the
        migration. Per the Week 5 review P2-2 fix, this mirrors
        ``_vault_io.is_person_note``'s Week 2 P2-1 fix."""
        people = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        (people / "Broken.md").write_text(
            "---\ntype: 42\nname: Broken\n---\nbody\n",
            encoding="utf-8",
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # No crash; the migration continues against the 6 valid Person
        # notes. The broken note is silently skipped.
        result = MIGRATION.upgrade(ctx)
        # 6 enrolled (Alice/Bob/Carol/Dana/Evan/Fiona — Broken skipped)
        # + 5 send-pairs (Alice email + Alice linkedin invite + Dana
        # linkedin DM + Evan Twitter DM + Fiona calendar booking per
        # Pillar B + Pillar C Week 3 + Week 5 + Week 6 fixture
        # extensions) + 1 orphan = 12.
        assert result.affected_count == 12

    def test_non_string_type_in_touch_note_is_silently_skipped(
        self, synthetic_state_dir,
    ):
        """A touch note with ``type: true`` (unquoted YAML bool) is
        non-touch; skip silently rather than crashing."""
        conv = synthetic_state_dir.vault_dir / CONVERSATIONS_SUBDIR
        (conv / "Broken touch.md").write_text(
            "---\ntype: true\nperson: \"[[Alice Anderson]]\"\nsent: true\n---\nbody\n",
            encoding="utf-8",
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        # The broken touch note is skipped; Alice's two real touches
        # (email + linkedin invite) + Dana's linkedin DM + Evan's
        # Twitter DM + Fiona's calendar booking still produce send-
        # pairs. 6 enrolled + 5 send-pairs + 1 orphan = 12.
        assert result.affected_count == 12

    def test_no_op_on_missing_people_subdir(self, tmp_path):
        """Vault without 10 People/ → zero enrolled (legitimate empty state).

        Same posture as vault/0002: a fresh-install vault dir without
        the People sub-dir is empty, not broken. The migration emits
        no enrolled events but still completes + emits migration_event.
        """
        state = tmp_path / "state"
        state.mkdir()
        (state / "ledger").mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()
        ctx = _make_ctx(state_dir=state, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.applied is True
        assert result.affected_count == 0
        # migration_event still emitted (audit-trail continuity).
        mes = _events_by_type(state / "ledger", "migration_event")
        assert len(mes) == 1


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

        Re-running the migration after deleting the emitted send_intent
        produces the same intent_id (which is why the idempotence
        check works — re-emission would collide on intent_id, but the
        check ALSO works because the same intent_id is in the existing
        set after the first apply).
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents_1 = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "send_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        first_id = intents_1[0]["intent_id"]
        assert first_id.startswith(SYNTHETIC_INTENT_PREFIX)
        # 16 hex chars after the prefix.
        assert len(first_id) == len(SYNTHETIC_INTENT_PREFIX) + 16
