"""MigrationRunner tests with synthetic in-memory migrations.

These tests exercise the runner via in-memory ``Migration`` instances
and verify:

* dry-run produces preview without state mutation
* apply moves the state pointer + is idempotent on re-run
* rollback reverses (when reversible) or refuses (when not)
* rollback requires explicit ``allow_rollback=True``
* partial-apply atomicity: a raising migration does NOT mark itself
  applied; earlier migrations in the batch DO remain applied
* the runner refuses out-of-order applies (per-category sequential)
* the runner refuses duplicate migration ids within a category
* the runner refuses category-mismatched migrations
* concurrent runner processes serialize via the state-file lock
* the MigrationContext carries the right paths through to migrations

No real ledger / vault / policy files are touched — Week 1 ships the
runner with synthetic test migrations only. Real per-category
migrations land in Week 2.
"""

from __future__ import annotations

import multiprocessing
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import pytest

from orchestrator.migrations.runner import (
    RUNNER_VERSION,
    MigrationNotReversibleError,
    MigrationOrderError,
    MigrationRunner,
)
from orchestrator.migrations.state import (
    is_applied,
    load_state,
    state_file_path,
)
from orchestrator.migrations.types import (
    Migration,
    MigrationCategory,
    MigrationContext,
    MigrationResult,
)


# ---------------------------------------------------------------------------
# Test migrations — in-memory, no on-disk side effects unless explicit.
# ---------------------------------------------------------------------------


@dataclass
class RecordingMigration:
    """A test migration that records its calls.

    The recording lives on the instance so the test can assert on
    ``upgrade_calls`` / ``downgrade_calls`` after the fact.
    """

    id: str
    category: MigrationCategory
    description: str
    is_reversible: bool
    affected_count: int = 0
    upgrade_calls: list[tuple[str, bool]] = field(default_factory=list)
    downgrade_calls: list[tuple[str, bool]] = field(default_factory=list)
    on_upgrade: Callable[[MigrationContext], None] | None = None
    on_downgrade: Callable[[MigrationContext], None] | None = None

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        self.upgrade_calls.append((self.id, ctx.dry_run))
        if self.on_upgrade and not ctx.dry_run:
            self.on_upgrade(ctx)
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=self.affected_count,
            notes=f"{'preview' if ctx.dry_run else 'applied'}: {self.description}",
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        if not self.is_reversible:
            raise NotImplementedError(
                f"{self.id} declared is_reversible=False",
            )
        self.downgrade_calls.append((self.id, ctx.dry_run))
        if self.on_downgrade and not ctx.dry_run:
            self.on_downgrade(ctx)
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=self.affected_count,
            notes=f"rolled back: {self.description}",
        )


@dataclass
class RaisingMigration:
    """A test migration that raises on upgrade — for atomicity tests."""

    id: str
    category: MigrationCategory
    description: str = "raises on upgrade"
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        raise RuntimeError(f"{self.id} simulated failure")

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "outreach-factory"
    d.mkdir()
    return d


def _make_runner(
    state_dir: Path,
    registries: dict[MigrationCategory, Sequence[Migration]] | None = None,
) -> MigrationRunner:
    return MigrationRunner(
        state_dir=state_dir,
        ledger_dir=state_dir / "ledger",
        vault_dir=state_dir / "vault",
        policy_dir=state_dir / "policies",
        registries=registries or {cat: [] for cat in MigrationCategory},
    )


# ---------------------------------------------------------------------------
# Pending — what's not yet applied?
# ---------------------------------------------------------------------------


class TestPending:
    def test_empty_registries_no_pending(self, state_dir: Path):
        runner = _make_runner(state_dir)
        assert runner.pending() == []
        for cat in MigrationCategory:
            assert runner.pending(cat) == []

    def test_unapplied_migrations_are_pending(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        b = RecordingMigration("0002_b", MigrationCategory.VAULT, "second", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a, b]})
        pending = runner.pending(MigrationCategory.VAULT)
        assert [m.id for m in pending] == ["0001_a", "0002_b"]

    def test_applied_migrations_are_skipped(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        b = RecordingMigration("0002_b", MigrationCategory.VAULT, "second", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a, b]})
        runner.apply(MigrationCategory.VAULT)
        assert runner.pending(MigrationCategory.VAULT) == []

    def test_pending_orders_by_default_apply_order(self, state_dir: Path):
        """The all-category pending walks VAULT → LEDGER → POLICY in
        the default apply order — vault first because ledger
        migrations may read state vault migrations have stamped (e.g.
        ledger/0002 reads ``id:`` stamped by vault/0002). Per ADR-0013
        D27 the default apply order is distinct from
        ``MigrationCategory`` enum declaration order (the latter
        remains the JSON serialization order for the state file)."""
        a_ledger = RecordingMigration(
            "0001_x", MigrationCategory.LEDGER, "l", False,
        )
        a_vault = RecordingMigration(
            "0001_y", MigrationCategory.VAULT, "v", True,
        )
        a_policy = RecordingMigration(
            "0001_z", MigrationCategory.POLICY, "p", True,
        )
        runner = _make_runner(state_dir, {
            MigrationCategory.LEDGER: [a_ledger],
            MigrationCategory.VAULT: [a_vault],
            MigrationCategory.POLICY: [a_policy],
        })
        pending = runner.pending()
        # VAULT first (0001_y), then LEDGER (0001_x), then POLICY (0001_z).
        assert [m.id for m in pending] == ["0001_y", "0001_x", "0001_z"]


# ---------------------------------------------------------------------------
# Dry-run — preview without mutation.
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_does_not_mutate_state_file(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        results = runner.dry_run(MigrationCategory.VAULT)
        assert len(results) == 1
        assert results[0].dry_run is True
        # State file's `applied[vault]` is still empty.
        state = load_state(state_dir)
        assert state.applied["vault"] == []

    def test_passes_dry_run_flag_to_upgrade(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.dry_run(MigrationCategory.VAULT)
        assert a.upgrade_calls == [("0001_a", True)]

    def test_dry_run_then_apply_works(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        preview = runner.dry_run(MigrationCategory.VAULT)
        results = runner.apply(MigrationCategory.VAULT)
        assert preview[0].dry_run is True
        assert results[0].dry_run is False
        assert results[0].applied is True

    def test_dry_run_returns_empty_when_nothing_pending(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.apply(MigrationCategory.VAULT)
        assert runner.dry_run(MigrationCategory.VAULT) == []

    def test_dry_run_result_carries_migration_id_and_category(
        self, state_dir: Path,
    ):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        result = runner.dry_run(MigrationCategory.VAULT)[0]
        assert result.migration_id == "0001_a"
        assert result.category == MigrationCategory.VAULT


# ---------------------------------------------------------------------------
# Apply — moves the state pointer.
# ---------------------------------------------------------------------------


class TestApply:
    def test_marks_applied_in_state_file(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.apply(MigrationCategory.VAULT)
        s = load_state(state_dir)
        assert is_applied(s, MigrationCategory.VAULT, "0001_a")
        assert s.last_runner_version == RUNNER_VERSION
        assert s.last_applied_at is not None

    def test_idempotent_on_re_apply(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        first = runner.apply(MigrationCategory.VAULT)
        second = runner.apply(MigrationCategory.VAULT)
        assert len(first) == 1
        assert second == []
        # The migration's upgrade was called exactly once.
        assert len(a.upgrade_calls) == 1
        assert a.upgrade_calls == [("0001_a", False)]

    def test_applies_in_per_category_order(self, state_dir: Path):
        """0001 → 0002 → 0003. The runner walks the registry in list
        order, which the registry validation pins to sorted-id order."""
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        b = RecordingMigration("0002_b", MigrationCategory.VAULT, "second", True)
        c = RecordingMigration("0003_c", MigrationCategory.VAULT, "third", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a, b, c]})

        # Record the order via a shared list each migration appends to.
        order: list[str] = []
        a.on_upgrade = lambda ctx: order.append("a")
        b.on_upgrade = lambda ctx: order.append("b")
        c.on_upgrade = lambda ctx: order.append("c")

        runner.apply(MigrationCategory.VAULT)
        assert order == ["a", "b", "c"]

    def test_apply_all_walks_every_category(self, state_dir: Path):
        a = RecordingMigration("0001_l", MigrationCategory.LEDGER, "l", False)
        b = RecordingMigration("0001_v", MigrationCategory.VAULT, "v", True)
        c = RecordingMigration("0001_p", MigrationCategory.POLICY, "p", True)
        runner = _make_runner(state_dir, {
            MigrationCategory.LEDGER: [a],
            MigrationCategory.VAULT: [b],
            MigrationCategory.POLICY: [c],
        })
        results = runner.apply()
        assert len(results) == 3
        s = load_state(state_dir)
        assert is_applied(s, MigrationCategory.LEDGER, "0001_l")
        assert is_applied(s, MigrationCategory.VAULT, "0001_v")
        assert is_applied(s, MigrationCategory.POLICY, "0001_p")

    def test_apply_result_carries_full_shape(self, state_dir: Path):
        a = RecordingMigration(
            "0001_a", MigrationCategory.VAULT, "first", True,
            affected_count=42,
        )
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        result = runner.apply(MigrationCategory.VAULT)[0]
        assert result.migration_id == "0001_a"
        assert result.category == MigrationCategory.VAULT
        assert result.applied is True
        assert result.dry_run is False
        assert result.affected_count == 42
        assert "applied: first" in result.notes

    def test_state_file_persists_across_runner_instances(self, state_dir: Path):
        """Creating a second runner instance against the same state dir
        should observe the first runner's apply."""
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        r1 = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        r1.apply(MigrationCategory.VAULT)

        b = RecordingMigration("0001_a", MigrationCategory.VAULT, "first", True)
        r2 = _make_runner(state_dir, {MigrationCategory.VAULT: [b]})
        assert r2.pending(MigrationCategory.VAULT) == []
        assert r2.apply(MigrationCategory.VAULT) == []
        # r2's migration was never called.
        assert len(b.upgrade_calls) == 0


# ---------------------------------------------------------------------------
# Partial-apply atomicity — a raising migration does NOT advance state.
# ---------------------------------------------------------------------------


class TestPartialApplyAtomicity:
    def test_raise_does_not_mark_applied(self, state_dir: Path):
        bad = RaisingMigration("0001_bad", MigrationCategory.VAULT)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [bad]})
        with pytest.raises(RuntimeError, match="simulated failure"):
            runner.apply(MigrationCategory.VAULT)
        s = load_state(state_dir)
        assert not is_applied(s, MigrationCategory.VAULT, "0001_bad")

    def test_raise_after_success_keeps_earlier_marks(self, state_dir: Path):
        """0001 succeeds → marked applied. 0002 raises → NOT marked
        applied. State on disk reflects this. Re-running apply will
        skip 0001 (already applied) and retry 0002 (still pending),
        which is the resume-from-where-it-failed contract."""
        good = RecordingMigration(
            "0001_good", MigrationCategory.VAULT, "ok", True,
        )
        bad = RaisingMigration("0002_bad", MigrationCategory.VAULT)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [good, bad]})
        with pytest.raises(RuntimeError, match="simulated failure"):
            runner.apply(MigrationCategory.VAULT)
        s = load_state(state_dir)
        assert is_applied(s, MigrationCategory.VAULT, "0001_good")
        assert not is_applied(s, MigrationCategory.VAULT, "0002_bad")

    def test_dry_run_does_not_mark_even_on_raise(self, state_dir: Path):
        """Dry-run never mutates state, even if a migration raises."""
        bad = RaisingMigration("0001_bad", MigrationCategory.VAULT)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [bad]})
        with pytest.raises(RuntimeError, match="simulated failure"):
            runner.dry_run(MigrationCategory.VAULT)
        s = load_state(state_dir)
        assert not is_applied(s, MigrationCategory.VAULT, "0001_bad")


# ---------------------------------------------------------------------------
# Registry validation — out-of-order, duplicate, category mismatch.
# ---------------------------------------------------------------------------


class TestRegistryValidation:
    def test_duplicate_ids_raise(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        b = RecordingMigration("0001_a", MigrationCategory.VAULT, "y", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a, b]})
        with pytest.raises(MigrationOrderError, match="duplicate"):
            runner.pending(MigrationCategory.VAULT)

    def test_category_mismatch_raises(self, state_dir: Path):
        """Migration declares VAULT but is registered under LEDGER —
        moving the file or the attribute is the right fix."""
        wrong = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        runner = _make_runner(state_dir, {MigrationCategory.LEDGER: [wrong]})
        with pytest.raises(MigrationOrderError, match="category"):
            runner.pending(MigrationCategory.LEDGER)

    def test_out_of_order_registry_raises(self, state_dir: Path):
        """vault/0002 listed before vault/0001 in the registry list."""
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        b = RecordingMigration("0002_b", MigrationCategory.VAULT, "y", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [b, a]})
        with pytest.raises(MigrationOrderError, match="sorted id order"):
            runner.pending(MigrationCategory.VAULT)

    def test_apply_with_bad_registry_does_not_partially_advance(
        self, state_dir: Path,
    ):
        """Registry validation happens before any upgrade — a bad
        registry must NOT allow any partial apply."""
        a = RecordingMigration("0002_b", MigrationCategory.VAULT, "x", True)
        b = RecordingMigration("0001_a", MigrationCategory.VAULT, "y", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a, b]})
        with pytest.raises(MigrationOrderError):
            runner.apply(MigrationCategory.VAULT)
        s = load_state(state_dir)
        assert s.applied["vault"] == []


# ---------------------------------------------------------------------------
# Rollback.
# ---------------------------------------------------------------------------


class TestRollback:
    def test_requires_allow_rollback_flag(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.apply(MigrationCategory.VAULT)
        with pytest.raises(ValueError, match="allow_rollback=True"):
            runner.rollback(
                MigrationCategory.VAULT, "0001_a", allow_rollback=False,
            )

    def test_omitting_allow_rollback_gives_operator_readable_error(
        self, state_dir: Path,
    ):
        """The default-False shape (per D4 defense-in-depth): omitting
        the flag entirely should give the operator-readable ValueError
        ("pass allow_rollback=True"), not a bare TypeError from Python
        missing-kwarg machinery."""
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.apply(MigrationCategory.VAULT)
        with pytest.raises(ValueError, match="allow_rollback=True"):
            runner.rollback(MigrationCategory.VAULT, "0001_a")

    def test_reverses_reversible_migration(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.apply(MigrationCategory.VAULT)
        result = runner.rollback(
            MigrationCategory.VAULT, "0001_a", allow_rollback=True,
        )
        assert result.applied is False
        s = load_state(state_dir)
        assert not is_applied(s, MigrationCategory.VAULT, "0001_a")
        assert a.downgrade_calls == [("0001_a", False)]

    def test_refuses_irreversible_migration(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.LEDGER, "x", False)
        runner = _make_runner(state_dir, {MigrationCategory.LEDGER: [a]})
        runner.apply(MigrationCategory.LEDGER)
        with pytest.raises(MigrationNotReversibleError, match="one-way"):
            runner.rollback(
                MigrationCategory.LEDGER, "0001_a", allow_rollback=True,
            )
        # State unchanged after the failed rollback.
        s = load_state(state_dir)
        assert is_applied(s, MigrationCategory.LEDGER, "0001_a")

    def test_refuses_unknown_migration(self, state_dir: Path):
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: []})
        with pytest.raises(ValueError, match="unknown migration"):
            runner.rollback(
                MigrationCategory.VAULT, "0001_nonexistent",
                allow_rollback=True,
            )

    def test_refuses_unapplied_migration(self, state_dir: Path):
        """Can't rollback what hasn't been applied."""
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        with pytest.raises(ValueError, match="not currently applied"):
            runner.rollback(
                MigrationCategory.VAULT, "0001_a", allow_rollback=True,
            )

    def test_rollback_then_re_apply_works(self, state_dir: Path):
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.apply(MigrationCategory.VAULT)
        runner.rollback(
            MigrationCategory.VAULT, "0001_a", allow_rollback=True,
        )
        # Pending again.
        assert [m.id for m in runner.pending(MigrationCategory.VAULT)] == ["0001_a"]
        runner.apply(MigrationCategory.VAULT)
        s = load_state(state_dir)
        assert is_applied(s, MigrationCategory.VAULT, "0001_a")
        # upgrade called twice (initial apply + post-rollback re-apply).
        assert len(a.upgrade_calls) == 2

    def test_rollback_does_not_advance_when_downgrade_raises(
        self, state_dir: Path,
    ):
        """If downgrade itself raises, state must NOT be touched —
        the migration is still marked applied."""
        a = RecordingMigration("0001_a", MigrationCategory.VAULT, "x", True)
        a.on_downgrade = lambda ctx: (_ for _ in ()).throw(
            RuntimeError("downgrade boom"),
        )
        runner = _make_runner(state_dir, {MigrationCategory.VAULT: [a]})
        runner.apply(MigrationCategory.VAULT)
        with pytest.raises(RuntimeError, match="downgrade boom"):
            runner.rollback(
                MigrationCategory.VAULT, "0001_a", allow_rollback=True,
            )
        s = load_state(state_dir)
        # Still marked applied because the downgrade didn't complete.
        assert is_applied(s, MigrationCategory.VAULT, "0001_a")


# ---------------------------------------------------------------------------
# Concurrent runner serialization — multiprocess.
# ---------------------------------------------------------------------------


def _apply_worker(
    state_dir_str: str,
    sentinel_str: str,
    duration: float,
) -> None:
    """Worker for cross-process apply concurrency test.

    Each worker applies one migration whose ``upgrade`` callback writes
    a sentinel timestamp + sleeps. With the runner's state-lock held
    across the upgrade, two workers must serialize their writes —
    the second sentinel is at least ``duration`` after the first.
    """
    from pathlib import Path

    from orchestrator.migrations.runner import MigrationRunner
    from orchestrator.migrations.types import (
        MigrationCategory,
        MigrationContext,
        MigrationResult,
    )

    state_dir_p = Path(state_dir_str)
    sentinel = Path(sentinel_str)

    class HoldingMigration:
        id = "0001_hold"
        category = MigrationCategory.VAULT
        description = "holds the lock briefly"
        is_reversible = True

        def upgrade(self, ctx: MigrationContext) -> MigrationResult:
            sentinel.write_text(str(time.time()), encoding="utf-8")
            time.sleep(duration)
            return MigrationResult(
                migration_id=self.id, category=self.category,
                applied=True, dry_run=ctx.dry_run,
            )

        def downgrade(self, ctx: MigrationContext) -> MigrationResult:
            return MigrationResult(
                migration_id=self.id, category=self.category,
                applied=False, dry_run=ctx.dry_run,
            )

    # Each worker has its OWN registry — the state file is the only
    # cross-process shared resource.
    runner = MigrationRunner(
        state_dir=state_dir_p,
        ledger_dir=state_dir_p / "ledger",
        vault_dir=state_dir_p / "vault",
        policy_dir=state_dir_p / "policies",
        registries={MigrationCategory.VAULT: [HoldingMigration()]},
    )
    try:
        runner.apply(MigrationCategory.VAULT)
    except Exception:
        # Second worker may see "already applied" from the state file
        # written by the first; that's the expected outcome — not an
        # error to surface.
        pass


class TestConcurrentRunners:
    def test_apply_serializes_across_processes(
        self, state_dir: Path, tmp_path: Path,
    ):
        """Two processes apply concurrently. They must NOT overlap on
        the state-file write (which is what the lock protects)."""
        sentinel_a = tmp_path / "a.marker"
        sentinel_b = tmp_path / "b.marker"
        hold = 0.3

        ctx = multiprocessing.get_context("spawn")
        p_a = ctx.Process(
            target=_apply_worker,
            args=(str(state_dir), str(sentinel_a), hold),
        )
        p_b = ctx.Process(
            target=_apply_worker,
            args=(str(state_dir), str(sentinel_b), hold),
        )

        p_a.start()
        time.sleep(0.05)
        p_b.start()

        p_a.join(timeout=10)
        p_b.join(timeout=10)
        assert p_a.exitcode == 0
        assert p_b.exitcode == 0

        # Exactly one sentinel was written (the one whose apply ran);
        # the other worker saw the state file already showed
        # ``0001_hold`` applied and never called upgrade.
        # Both sentinels existing would mean the lock failed.
        written = [
            s for s in (sentinel_a, sentinel_b) if s.exists()
        ]
        assert len(written) == 1, (
            f"expected exactly one worker to actually run upgrade; got "
            f"{len(written)}. The state-file lock did not serialize "
            f"the two apply calls."
        )

        # The state file shows the migration as applied.
        s = load_state(state_dir)
        assert is_applied(s, MigrationCategory.VAULT, "0001_hold")


# ---------------------------------------------------------------------------
# MigrationContext shape — does the runner pass the right paths through?
# ---------------------------------------------------------------------------


class TestMigrationContext:
    def test_context_carries_runner_directories(self, state_dir: Path):
        seen_ctx: list[MigrationContext] = []

        @dataclass
        class CapturingMigration:
            id: str = "0001_capture"
            category: MigrationCategory = MigrationCategory.VAULT
            description: str = "captures ctx"
            is_reversible: bool = True

            def upgrade(self, ctx: MigrationContext) -> MigrationResult:
                seen_ctx.append(ctx)
                return MigrationResult(
                    migration_id=self.id, category=self.category,
                    applied=True, dry_run=ctx.dry_run,
                )

            def downgrade(self, ctx: MigrationContext) -> MigrationResult:
                return MigrationResult(
                    migration_id=self.id, category=self.category,
                    applied=False, dry_run=ctx.dry_run,
                )

        runner = MigrationRunner(
            state_dir=state_dir,
            ledger_dir=state_dir / "ledger",
            vault_dir=state_dir / "vault",
            policy_dir=state_dir / "policies",
            registries={MigrationCategory.VAULT: [CapturingMigration()]},
        )
        runner.apply(MigrationCategory.VAULT)
        assert len(seen_ctx) == 1
        ctx = seen_ctx[0]
        assert ctx.state_dir == state_dir
        assert ctx.ledger_dir == state_dir / "ledger"
        assert ctx.vault_dir == state_dir / "vault"
        assert ctx.policy_dir == state_dir / "policies"
        assert ctx.dry_run is False
        assert ctx.now.tzinfo is not None

    def test_dry_run_context_has_dry_run_true(self, state_dir: Path):
        seen: list[bool] = []

        @dataclass
        class CapturingMigration:
            id: str = "0001_capture"
            category: MigrationCategory = MigrationCategory.VAULT
            description: str = "captures dry_run flag"
            is_reversible: bool = True

            def upgrade(self, ctx: MigrationContext) -> MigrationResult:
                seen.append(ctx.dry_run)
                return MigrationResult(
                    migration_id=self.id, category=self.category,
                    applied=True, dry_run=ctx.dry_run,
                )

            def downgrade(self, ctx: MigrationContext) -> MigrationResult:
                return MigrationResult(
                    migration_id=self.id, category=self.category,
                    applied=False, dry_run=ctx.dry_run,
                )

        runner = _make_runner(
            state_dir, {MigrationCategory.VAULT: [CapturingMigration()]},
        )
        runner.dry_run(MigrationCategory.VAULT)
        assert seen == [True]

    def test_context_is_frozen(self, state_dir: Path):
        """A migration can't accidentally mutate the context the
        runner will pass to subsequent migrations."""
        seen_ctx: list[MigrationContext] = []

        @dataclass
        class CapturingMigration:
            id: str = "0001_capture"
            category: MigrationCategory = MigrationCategory.VAULT
            description: str = "captures ctx"
            is_reversible: bool = True

            def upgrade(self, ctx: MigrationContext) -> MigrationResult:
                seen_ctx.append(ctx)
                return MigrationResult(
                    migration_id=self.id, category=self.category,
                    applied=True, dry_run=ctx.dry_run,
                )

            def downgrade(self, ctx: MigrationContext) -> MigrationResult:
                return MigrationResult(
                    migration_id=self.id, category=self.category,
                    applied=False, dry_run=ctx.dry_run,
                )

        runner = _make_runner(
            state_dir, {MigrationCategory.VAULT: [CapturingMigration()]},
        )
        runner.apply(MigrationCategory.VAULT)
        ctx = seen_ctx[0]
        with pytest.raises((AttributeError, Exception)):
            # Frozen dataclass attribute assignment raises FrozenInstanceError.
            ctx.dry_run = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Default registries — the runner can be constructed without explicit
# registries and reads each category sub-package's MIGRATIONS list.
# Week 2 populated vault/MIGRATIONS with the first vault migration;
# Week 3 populated ledger/MIGRATIONS with the first ledger migration;
# Week 4 populated policy/MIGRATIONS with the first policy migration.
# The test below confirms the wiring works without exercising the
# migrations themselves (vault_dir is None so the vault migration would
# refuse if invoked; the ledger + policy dirs don't exist so they would
# refuse too — but none are invoked because pending() doesn't run
# upgrades).
# ---------------------------------------------------------------------------


class TestRealMigrationRollbackRefusal:
    """Runner-level pin that the wrapped Phase 5.5 backfills
    (``vault/0002_backfill_identity_lineage`` + ``ledger/0002_backfill_send_history``)
    refuse rollback at the ``MigrationRunner.rollback`` integration
    seam — not just at the per-migration ``downgrade`` call.

    Why this is a distinct concern from the generic ``RecordingMigration``
    refusal tests above: those exercise the runner's refusal logic against
    a synthetic migration. These pin the REAL irreversibility-by-design
    contracts of the specific migrations the Pillar B exit criterion
    depends on. A future refactor that flipped ``vault/0002.is_reversible``
    or ``ledger/0002.is_reversible`` to ``True`` (perhaps as part of an
    ill-considered "operators want undo" feature) would silently regress
    the load-bearing posture per ADR-0013 Alternative 4. These tests
    catch that regression at the runner integration layer.

    Per ADR-0013 Alternative 4:

    * **vault/0002** is irreversible because the ``id`` mint is path-
      dependent: removing + re-minting after vault edits could produce
      a different id, a denormalized-view drift the asymmetric-failure-
      cost calculus structurally avoids.
    * **ledger/0002** is irreversible because the ledger is append-only
      (per ADR-0010 D14): there is no rollback mechanism for events
      already appended.

    Closes Week 5 review §Testing coverage gap #4.
    """

    def test_runner_rollback_refuses_wrapped_vault_backfill(
        self, state_dir: Path,
    ):
        """``runner.rollback(VAULT, "0002_backfill_identity_lineage",
        allow_rollback=True)`` raises ``MigrationNotReversibleError``
        — the wrap-bypassing path is closed."""
        from orchestrator.migrations.vault.migration_0002 import (
            MIGRATION as VAULT_BACKFILL,
        )
        # The runner needs the migration in its registry so the lookup
        # finds it. Then it MUST refuse before consulting state — even
        # if the state file said the migration was applied, the
        # is_reversible=False refusal short-circuits.
        runner = _make_runner(
            state_dir, {MigrationCategory.VAULT: [VAULT_BACKFILL]},
        )
        with pytest.raises(MigrationNotReversibleError, match="one-way"):
            runner.rollback(
                MigrationCategory.VAULT,
                "0002_backfill_identity_lineage",
                allow_rollback=True,
            )

    def test_runner_rollback_refuses_wrapped_ledger_backfill(
        self, state_dir: Path,
    ):
        """``runner.rollback(LEDGER, "0002_backfill_send_history",
        allow_rollback=True)`` raises ``MigrationNotReversibleError``
        — the append-only contract is enforced at the runner seam."""
        from orchestrator.migrations.ledger.migration_0002 import (
            MIGRATION as LEDGER_BACKFILL,
        )
        runner = _make_runner(
            state_dir, {MigrationCategory.LEDGER: [LEDGER_BACKFILL]},
        )
        with pytest.raises(MigrationNotReversibleError, match="one-way"):
            runner.rollback(
                MigrationCategory.LEDGER,
                "0002_backfill_send_history",
                allow_rollback=True,
            )


class TestDefaultRegistries:
    def test_runner_with_no_registries_uses_real_packages(
        self, state_dir: Path,
    ):
        """No explicit registries → runner imports ledger/vault/policy
        sub-packages' MIGRATIONS lists.

        As of Pillar B Week 5 the registries hold:

        * vault: 0001_add_schema_version_to_person_notes + 0002_backfill_identity_lineage
        * ledger: 0001_close_orphan_send_intents + 0002_backfill_send_history
        * policy: 0001_add_engine_compat_field

        Per ADR-0013 D27 the default cross-category apply order is
        VAULT → LEDGER → POLICY (distinct from ``MigrationCategory``
        enum declaration order, which still controls JSON
        serialization). The order matters because ledger/0002 reads
        ``id:`` stamped by vault/0002.
        """
        runner = MigrationRunner(
            state_dir=state_dir,
            ledger_dir=state_dir / "ledger",
            policy_dir=state_dir / "policies",
        )
        all_pending = runner.pending()
        # Pillar B set (5) + Pillar C Week 2 (2 — vault/0003 +
        # ledger/0003) + Pillar C Week 3 (1 — ledger/0004) + Pillar C
        # Week 5 (1 — ledger/0005) + Pillar C Week 6 (1 — ledger/0006)
        # + Pillar C Week 7 (1 — policy/0002) + Pillar C Week 8 (1 —
        # policy/0003) + Pillar C Week 9 (1 — policy/0004) + Pillar C
        # Week 10 (1 — policy/0005) + Pillar C Week 11 (1 — policy/0006)
        # + Pillar D Week 4-5 (1 — vault/0004 add conversation_status)
        # + Pillar D Week 6-8 (1 — policy/0007 add reply-classifier-
        # llm-monthly-cap per ADR-0029 D127) + Pillar E Week 9-11 (2 —
        # vault/0005 add discovery_lineage per ADR-0036 D168 +
        # ledger/0007 backfill enrolled.source_skill per ADR-0036 D170).
        # (Weeks 1 + 4 + Pillar D Weeks 2-3 + Pillar E Weeks 1-8 added
        # zero migrations.)
        assert len(all_pending) == 19
        # Per ADR-0013 D27 + ADR-0014 D34: VAULT first, then LEDGER,
        # then POLICY. Within each category, sequential id order.
        assert all_pending[0].id == "0001_add_schema_version_to_person_notes"
        assert all_pending[0].category == MigrationCategory.VAULT
        assert all_pending[1].id == "0002_backfill_identity_lineage"
        assert all_pending[1].category == MigrationCategory.VAULT
        assert all_pending[2].id == "0003_add_linkedin_action_to_touch_notes"
        assert all_pending[2].category == MigrationCategory.VAULT
        assert all_pending[3].id == "0004_add_conversation_status_to_person_notes"
        assert all_pending[3].category == MigrationCategory.VAULT
        assert all_pending[4].id == "0005_add_discovery_lineage_to_identity_keys"
        assert all_pending[4].category == MigrationCategory.VAULT
        assert all_pending[5].id == "0001_close_orphan_send_intents"
        assert all_pending[5].category == MigrationCategory.LEDGER
        assert all_pending[6].id == "0002_backfill_send_history"
        assert all_pending[6].category == MigrationCategory.LEDGER
        assert all_pending[7].id == "0003_baseline_li_invite_history"
        assert all_pending[7].category == MigrationCategory.LEDGER
        assert all_pending[8].id == "0004_baseline_li_dm_history"
        assert all_pending[8].category == MigrationCategory.LEDGER
        assert all_pending[9].id == "0005_baseline_tw_dm_history"
        assert all_pending[9].category == MigrationCategory.LEDGER
        assert all_pending[10].id == "0006_baseline_calendar_booking_history"
        assert all_pending[10].category == MigrationCategory.LEDGER
        assert all_pending[11].id == "0007_backfill_enrolled_source_skill"
        assert all_pending[11].category == MigrationCategory.LEDGER
        assert all_pending[12].id == "0001_add_engine_compat_field"
        assert all_pending[12].category == MigrationCategory.POLICY
        assert all_pending[13].id == "0002_add_li_invite_weekly_cap"
        assert all_pending[13].category == MigrationCategory.POLICY
        assert all_pending[14].id == "0003_add_li_dm_weekly_cap"
        assert all_pending[14].category == MigrationCategory.POLICY
        assert all_pending[15].id == "0004_add_tw_dm_weekly_cap"
        assert all_pending[15].category == MigrationCategory.POLICY
        assert all_pending[16].id == "0005_add_calendar_booking_daily_cap"
        assert all_pending[16].category == MigrationCategory.POLICY
        assert all_pending[17].id == "0006_add_cross_channel_email_linkedin_cooldown"
        assert all_pending[17].category == MigrationCategory.POLICY
        assert all_pending[18].id == "0007_add_reply_classifier_llm_cap"
        assert all_pending[18].category == MigrationCategory.POLICY
        # Per-category breakdown.
        assert len(runner.pending(MigrationCategory.LEDGER)) == 7
        assert len(runner.pending(MigrationCategory.VAULT)) == 5
        assert len(runner.pending(MigrationCategory.POLICY)) == 7
