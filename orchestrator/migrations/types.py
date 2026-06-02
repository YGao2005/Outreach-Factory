"""Pillar B migration framework — value types.

These types are the contract every migration declares and the runner
consumes. Frozen dataclasses where mutation would be a bug; Protocol
for the Migration surface so test fakes don't have to subclass anything
(precedent: ``orchestrator.policy.types.Rule`` + ``LedgerLike``).

See ``docs/adr/0009-migration-framework.md`` for the architecture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable


class MigrationCategory(str, Enum):
    """The three classes of migration outreach-factory currently supports.

    Each category corresponds to a sub-package under
    ``orchestrator/migrations/``:

    * ``LEDGER`` — append-only event-stream migrations. The ledger is the
      single source of truth (I1); mutating an existing event in place is
      forbidden. Ledger migrations either append a superseding event or
      raise. Reversibility is generally impossible (the original event
      was append-only at write time; an undo would require deleting
      bytes from a JSONL file, which we never do).
    * ``VAULT`` — Markdown frontmatter rewrites. The vault is
      denormalized; reconcile heals it from the ledger. Vault migrations
      rewrite YAML in place via the parser surface in
      ``orchestrator.vault``. Often reversible (rename a field back).
    * ``POLICY`` — YAML policy file rewrites. Every policy file carries
      ``version:``; a migration bumps the version + transforms the
      rules. Reversible if the transformation is.

    The enum is a ``str`` subclass so JSON serialization is trivial and
    the on-disk state file's ``applied`` dict keys round-trip without a
    custom encoder/decoder. Iteration order (``LEDGER``, ``VAULT``,
    ``POLICY``) determines the **JSON-serialization key order** of the
    ``applied`` dict in ``migrations.state.json`` — NOT the runner's
    default cross-category apply order. The runner's apply order is
    governed by ``orchestrator.migrations.runner._DEFAULT_APPLY_ORDER``
    (currently ``(VAULT, LEDGER, POLICY)`` per ADR-0013 D27 — vault is
    the operator-edited substrate; ledger denormalizes / retroactively
    emits from it, so vault must apply first; policy is independent and
    runs last). The apply-order constant is decoupled from the enum
    declaration order in Week 5 — see ADR-0013 D27 for the rationale.

    A future contributor adding a fourth category appends to this enum
    (preserving JSON-key compatibility for existing state files) AND
    decides where it slots into ``_DEFAULT_APPLY_ORDER`` (a separate
    decision surface per D27).
    """

    LEDGER = "ledger"
    VAULT = "vault"
    POLICY = "policy"


@dataclass(frozen=True)
class MigrationContext:
    """Per-run context the runner hands to each migration.

    Frozen so a migration cannot accidentally mutate the context that
    the runner will pass to subsequent migrations.

    Fields
    ------
    dry_run:
        True when the runner is producing a preview without writing
        state. Migrations MUST honor this — a migration that writes
        during a dry-run is a bug. The contract: at the top of
        ``upgrade``, branch on ``ctx.dry_run`` and either return a
        ``MigrationResult(dry_run=True, applied=True, ...)`` without
        any on-disk mutation, or perform the mutation and return
        ``MigrationResult(dry_run=False, applied=True, ...)``.
    state_dir:
        ``~/.outreach-factory/`` (or test override). The migration
        state file ``migrations.state.json`` lives directly under this
        directory; the lock file ``migrations.state.json.lock`` lives
        beside it.
    ledger_dir:
        ``~/.outreach-factory/ledger/`` (or test override). Ledger
        migrations operate on the JSONL files in this directory via
        ``orchestrator.ledger.Ledger.append`` (append-only — never
        rewrite).
    vault_dir:
        Path to the operator's Obsidian vault root, or ``None`` if the
        operator hasn't configured one (``~/.outreach-factory/config.yml``
        ``vault.path:``). Vault migrations MUST check
        ``ctx.vault_dir is not None`` at the top of ``upgrade`` and
        refuse if unset; ledger + policy migrations don't need it.
    policy_dir:
        ``~/.outreach-factory/policies/`` (or test override). Policy
        migrations rewrite YAML files in this directory.
    now:
        Evaluation timestamp, injected so tests can pin a deterministic
        ``last_applied_at`` value. Must be timezone-aware.
    logger:
        Standard library ``logging.Logger``. Migrations use this for
        operator-visible progress messages; the runner configures the
        log level + format at construction time. (The reference is
        frozen via ``dataclass(frozen=True)``; the logger object itself
        remains mutable — callers may ``.setLevel`` etc. on the same
        logger from outside without violating the frozen contract.)
    """

    dry_run: bool
    state_dir: Path
    ledger_dir: Path
    vault_dir: Path | None
    policy_dir: Path
    now: datetime
    logger: logging.Logger


@dataclass(frozen=True)
class MigrationResult:
    """Single-migration verdict from one run.

    Returned by both ``upgrade`` and ``downgrade``. The runner aggregates
    these across a batch (``apply()`` returns ``list[MigrationResult]``).

    Fields
    ------
    migration_id:
        ``<NNNN>_<slug>`` per the per-category sequential convention
        (e.g. ``"0001_add_schema_version"``). Matches the migration's
        ``id`` attribute. Carried on the result so the runner's report
        can include the id without re-deriving.
    category:
        Which category this migration belongs to. Carried so the
        runner's report can group results without re-lookup.
    applied:
        True if the migration's state would change (or did change). A
        dry-run preview that WOULD apply returns ``applied=True`` +
        ``dry_run=True``. A migration that the runner skipped (because
        the state file already shows it applied) is not represented in
        the result list at all — the runner filters those out before
        calling ``upgrade``. ``applied=False`` is reserved for
        ``downgrade`` results (the migration is no longer in the
        applied set after the rollback).
    dry_run:
        True if this verdict came from a preview. ``dry_run=True`` +
        ``applied=True`` is the dry-run preview shape: "this migration
        would apply if run for real."
    affected_count:
        Per-migration count of items the migration touched (rows
        rewritten, events appended, fields added). Diagnostic-only;
        the runner does not load-bear on this number. Defaults to 0
        for no-op migrations or for migrations that don't track counts.
    notes:
        Free-form human-readable description of what changed (or would
        change). Surfaces in the runner's report. Defaults to "".
    """

    migration_id: str
    category: MigrationCategory
    applied: bool
    dry_run: bool
    affected_count: int = 0
    notes: str = ""


@runtime_checkable
class Migration(Protocol):
    """Structural type for one migration.

    Concrete migrations live under ``orchestrator/migrations/<category>/``.
    They're registered into the category's ``MIGRATIONS`` list at import
    time so the runner can discover them; the runner reads each
    category's list directly rather than scanning the filesystem (so
    forgotten-from-registry is detected at load time rather than
    silently at apply time — see ADR-0009 §Decision item "Migration
    discovery").

    Required surface
    ----------------
    ``id``:
        ``"<NNNN>_<slug>"`` per the per-category sequential numeric
        convention. Unique within the migration's ``category``.
        Operator-readable. The runner pins per-category sorted-id
        order — the registry list must equal sorted(ids).
    ``category``:
        Which file-system surface this migration mutates. Must match
        the sub-package the migration lives in (the runner checks).
    ``description``:
        One-line summary for the runner's pending / dry-run report.
    ``is_reversible``:
        Explicit — no default. ``False`` means ``downgrade`` raises
        ``NotImplementedError`` and the runner translates this into a
        clean ``MigrationNotReversibleError`` refusal. ``True`` means
        ``downgrade`` reverses the change cleanly; the runner still
        requires an explicit ``allow_rollback=True`` flag at the call
        site (defense-in-depth — accidental rollback of a real
        migration is the catastrophic failure mode in this framework).
    ``upgrade(ctx)``:
        Apply the migration forward. Honor ``ctx.dry_run`` — when
        True, return a ``MigrationResult(dry_run=True, applied=True, ...)``
        WITHOUT mutating any on-disk state. When False, perform the
        mutation + return ``MigrationResult(dry_run=False, applied=True, ...)``.
        Raise on partial-apply failure — the runner does NOT mark the
        migration applied if ``upgrade`` raises, which is the
        atomicity contract D4 requires.
    ``downgrade(ctx)``:
        Reverse the migration. ``is_reversible=False`` migrations
        raise ``NotImplementedError`` here (the runner catches +
        translates). ``is_reversible=True`` migrations perform the
        reverse mutation. Same ``ctx.dry_run`` contract as ``upgrade``.
    """

    id: str
    category: MigrationCategory
    description: str
    is_reversible: bool

    def upgrade(self, ctx: MigrationContext) -> MigrationResult: ...

    def downgrade(self, ctx: MigrationContext) -> MigrationResult: ...
