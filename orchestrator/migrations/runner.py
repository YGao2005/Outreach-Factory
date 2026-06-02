"""Pillar B migration framework — the runner.

The ``MigrationRunner`` reads each category's ``MIGRATIONS`` registry,
filters by ``is_applied`` against the on-disk state, and dispatches the
un-applied ones to their ``upgrade()`` / ``downgrade()`` methods.

Architecture choices (per ADR-0009)
-----------------------------------

* **Generic over category.** The runner doesn't know what a ledger
  migration is vs a vault migration — it dispatches them through the
  ``Migration`` Protocol, which abstracts the side-effect surface.
* **Explicit registry (D6).** Each category's ``__init__.py`` exports
  ``MIGRATIONS: list[Migration]`` and the runner reads that list
  directly. Forgotten-from-registry is detected at load time;
  forgotten-on-disk (a filesystem-scan alternative) would be silent
  until apply, which is the failure mode we wanted to avoid.
* **Sequential per-category ordering (D2).** Numeric-prefix IDs
  (``0001_foo``, ``0002_bar``, ...) sort naturally. The runner pins
  this — the registry list MUST equal ``sorted(ids)``; out-of-order
  registries raise at load time.
* **Atomicity (D4).** ``upgrade`` raises → ``mark_applied`` is NOT
  called; the state-file pointer does not move. The runner saves
  state AFTER each successful ``upgrade`` so a multi-migration apply
  that fails on migration N still persists migrations 1..N-1 (the
  caller can re-run apply to resume from where the failure left off).
* **Reversibility (D4).** ``rollback`` requires explicit
  ``allow_rollback=True`` (defense-in-depth — accidental rollback of
  a real migration is the catastrophic failure mode in this
  framework). Irreversible migrations refuse rollback up-front.

See ``docs/adr/0009-migration-framework.md`` for the full design.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .state import (
    DEFAULT_STATE_DIR,
    acquire_state_lock,
    is_applied,
    load_state,
    mark_applied,
    mark_unapplied,
    save_state_atomic,
)
from .types import (
    Migration,
    MigrationCategory,
    MigrationContext,
    MigrationResult,
)


# Bumped when the framework's own surface evolves (state-file schema
# bumps, public Migration Protocol changes). Diagnostic only; rolled
# into ``state.last_runner_version`` on every write so operators can
# detect "the last writer was a newer runner than me; check the
# changelog before applying."
RUNNER_VERSION = "0.1.0"


_LOGGER_NAME = "orchestrator.migrations.runner"


# Default cross-category apply order — distinct from
# ``MigrationCategory`` declaration order (which controls JSON
# serialization in the state file).
#
# Why VAULT first: ADR-0013 D27 surfaces a real cross-category
# dependency that Week 5 introduces. ``ledger/0002_backfill_send_history``
# reads ``id:`` from Person notes (stamped by
# ``vault/0002_backfill_identity_lineage``) to emit retroactive
# ``enrolled`` events. If LEDGER ran first, Person notes wouldn't
# have ``id:`` yet and the backfill would skip them silently
# (recording them in ``persons_without_id`` but not emitting
# enrolled), producing an incomplete after-state.
#
# Future migrations follow the same shape: vault evolves the
# operator-edited substrate; ledger denormalizes / retroactively
# emits from it; policy is independent and runs last.
#
# Per-category apply (``runner.apply(MigrationCategory.X)``) is
# unaffected — only the no-args ``apply()`` and ``pending()``
# defaults consult this constant.
_DEFAULT_APPLY_ORDER: tuple[MigrationCategory, ...] = (
    MigrationCategory.VAULT,
    MigrationCategory.LEDGER,
    MigrationCategory.POLICY,
)


class MigrationOrderError(ValueError):
    """A category's registry violates the per-category ordering invariant.

    Sequential per-category ordering is the load-bearing invariant —
    ``vault/0002`` may not apply before ``vault/0001`` has applied.
    This error signals one of:

    * The registry list (in ``orchestrator/migrations/<cat>/__init__.py``)
      is in the wrong order. Reorder it.
    * Two migrations declare the same id. Renumber one.
    * A migration's ``category`` attribute disagrees with the sub-package
      it lives in. Move the file or fix the attribute.

    These are all contributor mistakes — caught loudly at runner load
    time so they fail immediately, not silently at apply time.
    """


class MigrationNotReversibleError(RuntimeError):
    """``rollback`` invoked on an ``is_reversible=False`` migration.

    Per D4 (Reversibility contract), irreversible migrations explicitly
    refuse rollback. The runner translates this into a clean refusal
    so the operator sees "this migration is one-way; rollback is
    impossible by design" rather than a bare ``NotImplementedError``
    surfacing from inside ``downgrade``.

    The right response is "restore from backup if you need the prior
    state" — the framework cannot manufacture a reverse-mutation it
    wasn't designed for.
    """


class MigrationRunner:
    """The Pillar B foreman.

    A single ``MigrationRunner`` instance owns one state file. Multiple
    runner instances (e.g. one process running ``apply`` while another
    runs ``pending``) serialize via the state file's advisory lock —
    only one process at a time can be inside ``apply`` / ``dry_run`` /
    ``rollback``.
    """

    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        ledger_dir: Path | None = None,
        vault_dir: Path | None = None,
        policy_dir: Path | None = None,
        registries: dict[MigrationCategory, Sequence[Migration]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Construct a runner.

        Defaults
        --------
        ``state_dir``
            ``~/.outreach-factory/`` (``DEFAULT_STATE_DIR``).
        ``ledger_dir``
            ``<state_dir>/ledger`` — matches ``DEFAULT_LEDGER_DIR``
            in ``orchestrator.ledger``.
        ``vault_dir``
            ``None`` — vault migrations refuse to run when unset. The
            operator's ``~/.outreach-factory/config.yml`` ``vault.path:``
            is the configured source; callers wiring the runner into
            production code must read that config and pass it in.
        ``policy_dir``
            ``<state_dir>/policies``.
        ``registries``
            The live per-category ``MIGRATIONS`` lists imported from
            the category sub-packages. Tests pass synthetic registries
            here to exercise the runner without touching real migration
            code.
        ``logger``
            ``logging.getLogger("orchestrator.migrations.runner")``.
        """
        self.state_dir = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
        self.ledger_dir = (
            Path(ledger_dir) if ledger_dir else (self.state_dir / "ledger")
        )
        self.vault_dir = Path(vault_dir) if vault_dir else None
        self.policy_dir = (
            Path(policy_dir) if policy_dir else (self.state_dir / "policies")
        )
        if registries is None:
            registries = _load_default_registries()
        self._registries: dict[MigrationCategory, list[Migration]] = {
            cat: list(registries.get(cat, ())) for cat in MigrationCategory
        }
        self.logger = logger or logging.getLogger(_LOGGER_NAME)

    # ---- registry inspection ----------------------------------------------

    def registry(self, category: MigrationCategory) -> list[Migration]:
        """Return the validated ordered list of migrations for one category.

        Validation runs every call (it's O(N) and N is small — ~10s of
        migrations per category at steady state). We deliberately don't
        cache: a test or a hot-reload scenario that mutates the
        underlying registry should see the new order on the next call.

        Raises
        ------
        MigrationOrderError:
            * Duplicate ids within the category.
            * A migration whose ``category`` attribute disagrees with
              the category it was registered under.
            * Registry list order disagrees with ``sorted(ids)``.
        """
        migs = list(self._registries[category])
        ids = [m.id for m in migs]
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            dupes: list[str] = []
            for i in ids:
                if i in seen and i not in dupes:
                    dupes.append(i)
                seen.add(i)
            raise MigrationOrderError(
                f"category {category.value!r} has duplicate migration ids: "
                f"{sorted(dupes)}. Each migration id must be unique per "
                f"category.",
            )
        for m in migs:
            if m.category != category:
                raise MigrationOrderError(
                    f"migration {m.id!r} registered under "
                    f"{category.value!r} but its category attribute is "
                    f"{m.category.value!r}. Move it to the right registry "
                    f"or fix the category attribute.",
                )
        sorted_ids = sorted(ids)
        if ids != sorted_ids:
            raise MigrationOrderError(
                f"category {category.value!r} registry order does not "
                f"match sorted id order. Got {ids}, expected {sorted_ids}. "
                f"Per D2 the per-category numeric prefix dictates apply "
                f"order; the registry list must match.",
            )
        return migs

    # ---- public API --------------------------------------------------------

    def pending(
        self,
        category: MigrationCategory | None = None,
    ) -> list[Migration]:
        """List un-applied migrations for one (or all) categories.

        Returns in apply order — per-category sequential per D2. When
        ``category`` is ``None``, walks every category in the default
        cross-category apply order (``_DEFAULT_APPLY_ORDER`` at module
        top: VAULT → LEDGER → POLICY per ADR-0013 D27). The order
        matters because ledger migrations may read state vault
        migrations have stamped — concretely,
        ``ledger/0002_backfill_send_history`` reads ``id:`` stamped by
        ``vault/0002_backfill_identity_lineage``.

        Note: the ``MigrationCategory`` enum declaration order
        (LEDGER, VAULT, POLICY) is preserved as the state-file JSON-
        serialization key order — that's a separate concern from
        ``_DEFAULT_APPLY_ORDER``. ADR-0013 D27 documents the split.

        Read-only. Does NOT take the state lock — concurrent ``apply``
        calls in other processes might transition migrations from
        pending to applied between this read and the caller's use of
        the result. Callers that want a snapshot consistent with an
        upcoming apply should call ``dry_run`` instead.
        """
        state = load_state(self.state_dir)
        out: list[Migration] = []
        cats = [category] if category else list(_DEFAULT_APPLY_ORDER)
        for cat in cats:
            for mig in self.registry(cat):
                if not is_applied(state, cat, mig.id):
                    out.append(mig)
        return out

    def dry_run(
        self,
        category: MigrationCategory | None = None,
    ) -> list[MigrationResult]:
        """Preview what ``apply`` would do without writing state.

        Returns one ``MigrationResult`` per pending migration, in apply
        order. Each migration's ``upgrade`` is called with
        ``ctx.dry_run=True``; migrations honor this by computing the
        counts + notes without mutating their on-disk surface. The
        state file is NOT written.

        The state lock IS acquired so a concurrent ``apply`` in another
        process cannot leave the state file in a mid-batch intermediate
        state between the read and the caller's use of the result.
        Two concurrent ``dry_run`` calls would be safe without the lock
        (reads don't corrupt each other); the lock specifically protects
        against interleaving with an ``apply`` batch.
        """
        with acquire_state_lock(self.state_dir):
            return self._run(category, dry_run=True, persist=False)

    def apply(
        self,
        category: MigrationCategory | None = None,
    ) -> list[MigrationResult]:
        """Apply all pending migrations for one (or all) categories.

        Per the atomicity contract (D4):

        * Each migration's ``upgrade`` is called in order.
        * The state file is updated after each SUCCESSFUL ``upgrade``.
        * If any migration raises, the runner STOPS — subsequent
          migrations are not attempted. The state file contains the
          cumulative applied list at the point of failure (the
          migrations that succeeded before the failure ARE persisted;
          the failing one is NOT marked applied).
        * The exception propagates uncaught to the caller. The send-
          loop equivalent is expected to log + halt the run; we do not
          try/except here for the same reason ``policy.engine.evaluate``
          doesn't (silent swallow would hide a partial-apply from the
          operator, which is exactly the failure mode the framework
          exists to prevent).

        The state lock is held for the entire batch — concurrent
        applies from other processes wait until this one completes.
        """
        with acquire_state_lock(self.state_dir):
            return self._run(category, dry_run=False, persist=True)

    def rollback(
        self,
        category: MigrationCategory,
        migration_id: str,
        *,
        allow_rollback: bool = False,
    ) -> MigrationResult:
        """Reverse a single applied migration.

        Defense-in-depth: ``allow_rollback`` must be passed True
        explicitly. The default is ``False`` so a caller that forgot
        the flag (or a CLI that didn't surface it) gets the operator-
        readable ``ValueError`` ("pass allow_rollback=True explicitly"),
        not a bare ``TypeError`` from Python's missing-kwarg machinery.
        Per D4, rollback of a real migration is the catastrophic
        failure mode in this framework; the loud + actionable refusal
        is intentional.

        The state lock is held for the lookup + downgrade + state
        write so concurrent applies cannot interleave with a rollback.

        Raises
        ------
        ValueError:
            If ``allow_rollback`` is ``False``; if ``migration_id`` is
            not in the category's registry; or if the migration has
            not been applied (nothing to roll back).
        MigrationNotReversibleError:
            If the migration declares ``is_reversible=False``. The
            runner refuses rather than calling ``downgrade`` (which
            would itself raise ``NotImplementedError`` by the D4
            convention).
        """
        if not allow_rollback:
            raise ValueError(
                f"rollback of {migration_id!r} refused: pass "
                f"allow_rollback=True explicitly. This default-deny "
                f"shape prevents accidental rollback of real "
                f"migrations.",
            )
        registry = self.registry(category)
        mig = next((m for m in registry if m.id == migration_id), None)
        if mig is None:
            raise ValueError(
                f"unknown migration id {migration_id!r} in category "
                f"{category.value!r}",
            )
        if not mig.is_reversible:
            raise MigrationNotReversibleError(
                f"migration {migration_id!r} declares is_reversible="
                f"False; this is a one-way change. Rollback is "
                f"impossible by design; restore from backup if you "
                f"need the prior state.",
            )

        with acquire_state_lock(self.state_dir):
            state = load_state(self.state_dir)
            if not is_applied(state, category, migration_id):
                raise ValueError(
                    f"migration {migration_id!r} is not currently "
                    f"applied; nothing to rollback.",
                )
            ctx = self._build_context(dry_run=False)
            self.logger.info(
                "rolling back %s/%s", category.value, migration_id,
            )
            result = mig.downgrade(ctx)
            mark_unapplied(
                state, category, migration_id,
                now=ctx.now, runner_version=RUNNER_VERSION,
            )
            save_state_atomic(self.state_dir, state)
            return result

    # ---- internals --------------------------------------------------------

    def _run(
        self,
        category: MigrationCategory | None,
        *,
        dry_run: bool,
        persist: bool,
    ) -> list[MigrationResult]:
        """Shared core for ``dry_run`` and ``apply``. Caller holds the lock."""
        state = load_state(self.state_dir)
        cats = [category] if category else list(_DEFAULT_APPLY_ORDER)
        out: list[MigrationResult] = []
        ctx = self._build_context(dry_run=dry_run)
        for cat in cats:
            for mig in self.registry(cat):
                if is_applied(state, cat, mig.id):
                    continue
                self.logger.info(
                    "%s %s/%s — %s",
                    "would apply" if dry_run else "applying",
                    cat.value, mig.id, mig.description,
                )
                # An exception here propagates UP — mark_applied is NOT
                # reached, so the state pointer does not move. This is
                # the atomicity contract D4 requires.
                result = mig.upgrade(ctx)
                out.append(result)
                if persist:
                    mark_applied(
                        state, cat, mig.id,
                        now=ctx.now, runner_version=RUNNER_VERSION,
                    )
                    save_state_atomic(self.state_dir, state)
        return out

    def _build_context(self, *, dry_run: bool) -> MigrationContext:
        return MigrationContext(
            dry_run=dry_run,
            state_dir=self.state_dir,
            ledger_dir=self.ledger_dir,
            vault_dir=self.vault_dir,
            policy_dir=self.policy_dir,
            now=datetime.now(timezone.utc),
            logger=self.logger,
        )


def _load_default_registries() -> dict[MigrationCategory, Sequence[Migration]]:
    """Import each category's MIGRATIONS list at runner-construction time.

    Imported lazily (not at module top level) so a test that
    monkey-patches the category modules can do so before the
    registries are loaded. Also avoids an import cycle: the category
    sub-packages import ``Migration`` from ``..types``; if this
    function were a top-level import, the type-checker import order
    would matter.
    """
    from . import ledger as _ledger
    from . import policy as _policy
    from . import vault as _vault

    return {
        MigrationCategory.LEDGER: tuple(_ledger.MIGRATIONS),
        MigrationCategory.VAULT: tuple(_vault.MIGRATIONS),
        MigrationCategory.POLICY: tuple(_policy.MIGRATIONS),
    }
