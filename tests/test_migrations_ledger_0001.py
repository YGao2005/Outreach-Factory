"""Tests for ledger migration 0001 — close orphan send intents.

Exercises the migration directly (calling ``upgrade`` against a
synthetic ``MigrationContext``) AND through the runner (``apply`` +
``rollback`` paths). Covers:

* Every open ``send_intent`` with no matching outcome gets a
  ``send_aborted`` event appended with ``_recovered_by`` tagging.
* Intents with an existing outcome (``send_confirmed``, ``send_failed``,
  ``send_aborted``) are NOT touched.
* The migration emits a ``migration_event`` audit-trail event on every
  apply, including no-op applies (affected_count = 0).
* Idempotence on direct re-invocation: after closing all orphans,
  another ``upgrade`` finds zero orphans + emits a fresh
  ``migration_event`` with ``affected_count=0``.
* The ``send_aborted`` event carries the originating intent's
  ``person_id`` + ``channel`` + the ``_recovered_by`` tag.
* ``dry_run=True`` reports the count without writing events.
* ``is_reversible=False`` — runner refuses rollback with
  ``MigrationNotReversibleError``.
* ``downgrade`` raises ``NotImplementedError`` (the runner translates
  to ``MigrationNotReversibleError``).
* The migration is marked applied in the state file; re-applying via
  the runner is a no-op (pending is empty).
* Refuses on a ``ctx`` whose ``ledger_dir`` doesn't exist as a real
  directory — refuses loudly rather than silently creating an empty
  one (the asymmetric-failure-cost calculus: silent creation could
  mask a misconfigured ``state_dir`` env var).

  Note: this is a softer refusal than the vault migration's
  ``ctx.vault_dir is None`` check. Ledger dir defaults to
  ``<state_dir>/ledger`` in :class:`MigrationRunner`, so it's
  ALWAYS a non-None path — the meaningful check is "does the path
  actually exist." See ADR-0010 D15 for the refusal contract.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

from orchestrator.migrations import (
    MigrationCategory,
    MigrationNotReversibleError,
    MigrationRunner,
)
from orchestrator.migrations.ledger._ledger_io import (
    append_event_atomic,
    events_by_type,
    iter_events,
)
from orchestrator.migrations.ledger.migration_0001 import (
    MIGRATION,
    MIGRATION_ID,
    RECOVERED_BY_TAG,
    CloseOrphanSendIntents,
)
from orchestrator.migrations.state import is_applied, load_state
from orchestrator.migrations.types import (
    Migration,
    MigrationContext,
    MigrationResult,
)


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    """Isolated ledger directory per test."""
    d = tmp_path / "ledger"
    d.mkdir()
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Isolated state directory per test."""
    d = tmp_path / "state"
    d.mkdir()
    return d


def _make_ctx(
    ledger_dir: Path,
    state_dir: Path,
    *,
    dry_run: bool = False,
) -> MigrationContext:
    """Build a MigrationContext for direct upgrade()/downgrade() tests."""
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir,
        vault_dir=None,
        policy_dir=state_dir / "policies",
        now=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
        logger=logging.getLogger("test.migrations.ledger.0001"),
    )


def _make_runner(
    state_dir: Path,
    ledger_dir: Path,
    registries: dict[MigrationCategory, Sequence[Migration]] | None = None,
) -> MigrationRunner:
    return MigrationRunner(
        state_dir=state_dir,
        ledger_dir=ledger_dir,
        policy_dir=state_dir / "policies",
        registries=registries or {MigrationCategory.LEDGER: [MIGRATION]},
    )


def _seed_intent(
    ledger_dir: Path, intent_id: str, *,
    person_id: str = "p1", channel: str = "email",
) -> dict:
    return append_event_atomic(ledger_dir, {
        "type": "send_intent",
        "person_id": person_id,
        "intent_id": intent_id,
        "channel": channel,
    })


def _seed_outcome(
    ledger_dir: Path, intent_id: str, outcome_type: str,
) -> dict:
    return append_event_atomic(ledger_dir, {
        "type": outcome_type,
        "intent_id": intent_id,
    })


# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_id_is_correct(self):
        assert MIGRATION.id == "0001_close_orphan_send_intents"

    def test_category_is_ledger(self):
        assert MIGRATION.category == MigrationCategory.LEDGER

    def test_is_not_reversible(self):
        """Ledger is append-only; rollback is structurally impossible.
        Per ADR-0010, every ledger migration declares
        ``is_reversible=False``."""
        assert MIGRATION.is_reversible is False

    def test_module_constants_match_instance(self):
        """The module exposes RECOVERED_BY_TAG and MIGRATION_ID for
        consumers + tests. Verify they match the instance."""
        assert MIGRATION_ID == MIGRATION.id
        assert RECOVERED_BY_TAG == f"migration_{MIGRATION.id}"

    def test_description_is_one_line(self):
        assert "\n" not in MIGRATION.description
        assert len(MIGRATION.description) > 10


# ---------------------------------------------------------------------------
# Upgrade — direct invocation
# ---------------------------------------------------------------------------


class TestUpgradeClosesOrphans:
    def test_closes_every_open_send_intent(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1", person_id="alice")
        _seed_intent(ledger_dir, "i2", person_id="bob")
        _seed_intent(ledger_dir, "i3", person_id="carol")
        ctx = _make_ctx(ledger_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 3
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        assert len(aborted) == 3
        intent_ids = {e["intent_id"] for e in aborted}
        assert intent_ids == {"i1", "i2", "i3"}

    def test_send_aborted_carries_recovered_by_tag(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1")
        ctx = _make_ctx(ledger_dir, state_dir)
        MIGRATION.upgrade(ctx)
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        assert len(aborted) == 1
        assert aborted[0]["_recovered_by"] == RECOVERED_BY_TAG

    def test_send_aborted_carries_person_id_and_channel(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """The denormalized fields from the originating ``send_intent``
        are carried onto the synthetic ``send_aborted`` so downstream
        readers don't have to join back to the intent. Matches the
        backfill_ledger.py pattern (line 364-369)."""
        _seed_intent(ledger_dir, "i1", person_id="alice", channel="linkedin")
        ctx = _make_ctx(ledger_dir, state_dir)
        MIGRATION.upgrade(ctx)
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        assert aborted[0]["person_id"] == "alice"
        assert aborted[0]["channel"] == "linkedin"

    def test_send_aborted_includes_reason(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """The migration's ``send_aborted`` events MUST include a
        human-readable ``reason`` field so an operator running
        ``ledger.py tail --type send_aborted`` understands why these
        events appeared without back-referencing the migration code."""
        _seed_intent(ledger_dir, "i1")
        ctx = _make_ctx(ledger_dir, state_dir)
        MIGRATION.upgrade(ctx)
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        assert "reason" in aborted[0]
        assert "migration" in aborted[0]["reason"].lower()

    def test_intents_with_confirmed_outcome_not_touched(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1")
        _seed_outcome(ledger_dir, "i1", "send_confirmed")
        _seed_intent(ledger_dir, "i2")  # orphan
        ctx = _make_ctx(ledger_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        assert len(aborted) == 1
        assert aborted[0]["intent_id"] == "i2"

    def test_intents_with_failed_outcome_not_touched(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1")
        _seed_outcome(ledger_dir, "i1", "send_failed")
        ctx = _make_ctx(ledger_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        # No new send_aborted (other than the originating, but there
        # are none here — we seeded a failed, not an aborted).
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        assert len(aborted) == 0

    def test_intents_with_aborted_outcome_not_re_touched(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """If an intent already has a ``send_aborted`` outcome (from
        an earlier reconcile pass or migration run), the migration
        does NOT append a second one. Idempotence at the per-event
        level."""
        _seed_intent(ledger_dir, "i1")
        _seed_outcome(ledger_dir, "i1", "send_aborted")
        ctx = _make_ctx(ledger_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        # Exactly one — the pre-seeded one. The migration did NOT
        # append a second one.
        assert len(aborted) == 1


class TestUpgradeMigrationEvent:
    def test_emits_migration_event_on_apply(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1")
        ctx = _make_ctx(ledger_dir, state_dir)
        MIGRATION.upgrade(ctx)
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert len(migration_events) == 1
        assert migration_events[0]["migration_id"] == MIGRATION_ID
        assert migration_events[0]["affected_count"] == 1

    def test_emits_migration_event_on_no_op_apply(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """No orphans → affected_count=0, but migration_event still
        emitted. Per ADR-0010 D17, every apply leaves an audit trail
        regardless of work performed."""
        ctx = _make_ctx(ledger_dir, state_dir)
        MIGRATION.upgrade(ctx)
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert len(migration_events) == 1
        assert migration_events[0]["affected_count"] == 0

    def test_migration_event_includes_runner_version(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """The audit-trail event carries the runner version so a future
        reader can reconstruct which runner generation wrote it."""
        ctx = _make_ctx(ledger_dir, state_dir)
        MIGRATION.upgrade(ctx)
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        # The migration emits its own version; it doesn't query the
        # runner. The contract is "the event has SOMETHING that lets
        # us know which generation of code wrote it." Both
        # `runner_version` and `migration_version` would be acceptable
        # here; we standardize on `runner_version` since it matches
        # the state file's `last_runner_version`.
        assert "runner_version" in migration_events[0]


class TestIdempotence:
    def test_second_direct_upgrade_finds_no_orphans(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """A direct (bypassing-runner) second upgrade after success
        produces ``affected_count=0`` and STILL emits the migration_event.

        In production the runner would refuse to re-invoke upgrade
        (state file says applied); this test is the "what if someone
        constructs a fresh runner pointed at a state dir that hasn't
        recorded this migration" case — the migration MUST be safe to
        re-invoke directly because that's the synthetic-replay
        contract.
        """
        _seed_intent(ledger_dir, "i1")
        _seed_intent(ledger_dir, "i2")
        ctx = _make_ctx(ledger_dir, state_dir)
        first = MIGRATION.upgrade(ctx)
        assert first.affected_count == 2
        second = MIGRATION.upgrade(ctx)
        assert second.affected_count == 0
        # Migration events: one per apply = two total.
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert len(migration_events) == 2
        assert [e["affected_count"] for e in migration_events] == [2, 0]
        # send_aborted events: one per orphan = two total (NOT four —
        # the second apply finds the intents already closed).
        aborted = list(events_by_type(ledger_dir, "send_aborted"))
        assert len(aborted) == 2


class TestDryRun:
    def test_dry_run_reports_count_without_writing(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1")
        _seed_intent(ledger_dir, "i2")
        ctx = _make_ctx(ledger_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 2
        assert result.dry_run is True
        # No new events: only the two send_intents we seeded.
        events = list(iter_events(ledger_dir))
        assert len(events) == 2
        assert all(e["type"] == "send_intent" for e in events)
        # In particular: no migration_event from a dry run.
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert migration_events == []

    def test_dry_run_with_no_orphans_reports_zero(
        self, ledger_dir: Path, state_dir: Path,
    ):
        ctx = _make_ctx(ledger_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        assert result.dry_run is True


# ---------------------------------------------------------------------------
# Refusal paths
# ---------------------------------------------------------------------------


class TestRefuse:
    def test_downgrade_raises_not_implemented(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """is_reversible=False → downgrade raises NotImplementedError;
        the runner translates this into MigrationNotReversibleError."""
        ctx = _make_ctx(ledger_dir, state_dir)
        with pytest.raises(NotImplementedError):
            MIGRATION.downgrade(ctx)

    def test_runner_refuses_rollback_with_clean_error(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """Runner-level rollback: the runner sees ``is_reversible=False``
        BEFORE calling downgrade and raises MigrationNotReversibleError
        directly (per ADR-0009 D4)."""
        _seed_intent(ledger_dir, "i1")
        runner = _make_runner(state_dir, ledger_dir)
        runner.apply(MigrationCategory.LEDGER)
        with pytest.raises(MigrationNotReversibleError):
            runner.rollback(
                MigrationCategory.LEDGER, MIGRATION_ID,
                allow_rollback=True,
            )

    def test_refuses_on_missing_ledger_dir(
        self, tmp_path: Path, state_dir: Path,
    ):
        """A migration context with a non-existent ledger_dir refuses
        loudly. Silent creation could mask a misconfigured state_dir
        env var (operator points the runner at the wrong directory,
        the migration silently creates a fresh empty ledger, the
        operator's real ledger is untouched but the migration is
        marked applied)."""
        nonexistent = tmp_path / "no_ledger_here"
        ctx = _make_ctx(nonexistent, state_dir)
        with pytest.raises(FileNotFoundError, match="ledger"):
            MIGRATION.upgrade(ctx)


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


class TestRunnerApply:
    def test_apply_marks_state(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1")
        runner = _make_runner(state_dir, ledger_dir)
        results = runner.apply(MigrationCategory.LEDGER)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].affected_count == 1
        state = load_state(state_dir)
        assert is_applied(state, MigrationCategory.LEDGER, MIGRATION_ID)

    def test_re_apply_through_runner_is_no_op(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """After apply, the state file shows the migration applied.
        Re-running apply: the runner skips it (pending is empty)."""
        _seed_intent(ledger_dir, "i1")
        runner = _make_runner(state_dir, ledger_dir)
        runner.apply(MigrationCategory.LEDGER)
        second_results = runner.apply(MigrationCategory.LEDGER)
        assert second_results == []
        # And: only ONE migration_event (the first apply).
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert len(migration_events) == 1

    def test_pending_includes_migration_until_applied(
        self, ledger_dir: Path, state_dir: Path,
    ):
        runner = _make_runner(state_dir, ledger_dir)
        pending = runner.pending(MigrationCategory.LEDGER)
        assert len(pending) == 1
        assert pending[0].id == MIGRATION_ID
        runner.apply(MigrationCategory.LEDGER)
        pending_after = runner.pending(MigrationCategory.LEDGER)
        assert pending_after == []

    def test_dry_run_via_runner_does_not_mutate_ledger(
        self, ledger_dir: Path, state_dir: Path,
    ):
        _seed_intent(ledger_dir, "i1")
        _seed_intent(ledger_dir, "i2")
        runner = _make_runner(state_dir, ledger_dir)
        results = runner.dry_run(MigrationCategory.LEDGER)
        assert len(results) == 1
        assert results[0].dry_run is True
        assert results[0].affected_count == 2
        # No mutations.
        events = list(iter_events(ledger_dir))
        assert len(events) == 2
        # Not marked applied either.
        state = load_state(state_dir)
        assert not is_applied(state, MigrationCategory.LEDGER, MIGRATION_ID)


# ---------------------------------------------------------------------------
# Failure atomicity (the framework's load-bearing contract per ADR-0009 D4)
# ---------------------------------------------------------------------------


class TestFailureAtomicity:
    def test_raising_upgrade_does_not_mark_applied(
        self, ledger_dir: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """If ``upgrade`` raises mid-batch, the state file pointer
        does NOT move. Standard ADR-0009 D4 atomicity — we exercise
        it here with a monkey-patched _ledger_io.append_event_atomic
        that raises mid-batch."""
        _seed_intent(ledger_dir, "i1")
        _seed_intent(ledger_dir, "i2")
        _seed_intent(ledger_dir, "i3")

        import orchestrator.migrations.ledger.migration_0001 as mod
        call_count = {"n": 0}
        original_append = mod.append_event_atomic

        def flaky_append(led_dir, event):
            call_count["n"] += 1
            # Allow the first send_aborted; raise on the second.
            if call_count["n"] == 2:
                raise RuntimeError("simulated disk full")
            return original_append(led_dir, event)

        monkeypatch.setattr(mod, "append_event_atomic", flaky_append)

        runner = _make_runner(state_dir, ledger_dir)
        with pytest.raises(RuntimeError, match="simulated disk full"):
            runner.apply(MigrationCategory.LEDGER)

        # Migration NOT marked applied.
        state = load_state(state_dir)
        assert not is_applied(state, MigrationCategory.LEDGER, MIGRATION_ID)

        # The first send_aborted IS on disk (we appended once before
        # the simulated failure); the migration is responsible for
        # being idempotent on re-run — verify that.
        aborted_first_pass = list(events_by_type(ledger_dir, "send_aborted"))
        assert len(aborted_first_pass) == 1

        # Re-run with the patch removed → should close remaining orphans.
        monkeypatch.setattr(mod, "append_event_atomic", original_append)
        runner.apply(MigrationCategory.LEDGER)
        aborted_after = list(events_by_type(ledger_dir, "send_aborted"))
        # All three intents now have a send_aborted outcome.
        assert len(aborted_after) == 3
        intent_ids = {e["intent_id"] for e in aborted_after}
        assert intent_ids == {"i1", "i2", "i3"}


# ---------------------------------------------------------------------------
# Concurrent-writer race (TOCTOU narrowing — Week 3 follow-up P2-2)
# ---------------------------------------------------------------------------


class TestConcurrentWriterRace:
    def test_concurrent_outcome_during_scan_is_detected_and_skipped(
        self, ledger_dir: Path, state_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Pre-append rebuild closes most of the TOCTOU window: if a
        concurrent writer appends an outcome event between Pass 1 and
        the append loop, the migration's pre-loop ledger rebuild
        picks it up + the in-loop membership check skips the intent.

        Simulates the race by monkey-patching ``iter_events`` to
        inject a concurrent ``send_confirmed`` write the FIRST time
        it's called after Pass 1 (i.e., during the pre-loop rebuild).
        The migration sees the concurrent write in its rebuilt outcome
        set and refuses to emit send_aborted for the raced intent.
        """
        _seed_intent(ledger_dir, "i_raced")
        _seed_intent(ledger_dir, "i_safe")

        import orchestrator.migrations.ledger.migration_0001 as mod
        original_iter = mod.iter_events
        call_count = {"n": 0}

        def iter_with_injected_concurrent_write(led_dir):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # Pass 1 finished (first iter_events call). Now the
                # migration is about to do its pre-loop rebuild
                # (second iter_events call). Simulate a concurrent
                # writer appending send_confirmed for i_raced before
                # the rebuild reads it.
                mod.append_event_atomic(led_dir, {
                    "type": "send_confirmed",
                    "intent_id": "i_raced",
                    "_recovered_by": "simulated_concurrent_dispatcher",
                })
            yield from original_iter(led_dir)

        monkeypatch.setattr(mod, "iter_events",
                            iter_with_injected_concurrent_write)
        ctx = _make_ctx(ledger_dir, state_dir)
        result = MIGRATION.upgrade(ctx)

        # i_safe was closed by the migration; i_raced was skipped.
        assert result.affected_count == 1
        aborted = [e for e in events_by_type(ledger_dir, "send_aborted")
                   if e.get("_recovered_by") == RECOVERED_BY_TAG]
        assert len(aborted) == 1
        assert aborted[0]["intent_id"] == "i_safe"

        # The migration_event records the skip count.
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert len(migration_events) == 1
        assert migration_events[0]["affected_count"] == 1
        assert migration_events[0]["skipped_raced"] == 1

        # The injected send_confirmed for i_raced is preserved.
        confirmed = [e for e in events_by_type(ledger_dir, "send_confirmed")
                     if e.get("intent_id") == "i_raced"]
        assert len(confirmed) == 1

    def test_no_concurrent_writer_means_no_skips(
        self, ledger_dir: Path, state_dir: Path,
    ):
        """Negative control: with no concurrent writer, the pre-loop
        rebuild finds the same outcome set Pass 1 saw + no orphan
        is skipped due to race."""
        _seed_intent(ledger_dir, "i1")
        _seed_intent(ledger_dir, "i2")
        ctx = _make_ctx(ledger_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 2
        # migration_event records skipped_raced=0.
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert migration_events[0]["skipped_raced"] == 0


# ---------------------------------------------------------------------------
# The class is importable and matches the Migration Protocol
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_class_implements_migration_protocol(self):
        """``CloseOrphanSendIntents`` implements the structural
        Migration Protocol — the runtime_checkable check returns
        True. This is the same check the runner's registry validation
        leans on."""
        assert isinstance(MIGRATION, Migration)
        assert isinstance(CloseOrphanSendIntents(), Migration)
