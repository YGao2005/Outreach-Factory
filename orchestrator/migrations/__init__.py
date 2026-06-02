"""Pillar B — versioned, idempotent migration framework.

The framework operates on three categories of persistent state:

* ``ledger`` — append-only JSONL events under
  ``~/.outreach-factory/ledger/``. The single source of truth (I1).
  Migrations are append-only superseding events; in-place rewrites
  are forbidden.
* ``vault`` — Markdown frontmatter under the operator's Obsidian
  vault. Denormalized view of the ledger; reconcile heals from the
  ledger. Vault migrations rewrite YAML frontmatter in place via the
  parser surface in ``orchestrator.vault``.
* ``policy`` — YAML policy files under
  ``~/.outreach-factory/policies/``. Versioned per file (``version:``
  field). Migrations bump the version + transform the rules.

Architecture
------------

``MigrationRunner`` is generic over category. Each category sub-package
exports ``MIGRATIONS: list[Migration]``; the runner reads that list,
filters by ``is_applied`` against the on-disk state, and dispatches
the un-applied ones to their ``upgrade()`` / ``downgrade()`` methods.

State lives in ``~/.outreach-factory/migrations.state.json`` — the
applies-once SoT. A single advisory file lock serializes concurrent
runners across processes; tmp-then-rename atomic writes ensure no
partial state ever appears on disk.

Public surface — import from here, not from sub-modules::

    from orchestrator.migrations import MigrationRunner, MigrationCategory

    runner = MigrationRunner()
    pending = runner.pending()
    preview = runner.dry_run()
    runner.apply()

See ``docs/adr/0009-migration-framework.md`` for architecture and
``docs/PILLAR-PLAN.md`` §2 Pillar B for scope.
"""

from .runner import (
    RUNNER_VERSION,
    MigrationNotReversibleError,
    MigrationOrderError,
    MigrationRunner,
)
from .state import (
    DEFAULT_STATE_DIR,
    STATE_FILENAME,
    STATE_LOCK_FILENAME,
    STATE_SCHEMA_VERSION,
    MigrationState,
    acquire_state_lock,
    is_applied,
    load_state,
    lock_file_path,
    mark_applied,
    mark_unapplied,
    save_state_atomic,
    state_file_path,
)
from .types import (
    Migration,
    MigrationCategory,
    MigrationContext,
    MigrationResult,
)


__all__ = [
    # Types
    "Migration",
    "MigrationCategory",
    "MigrationContext",
    "MigrationResult",
    # Runner
    "MigrationRunner",
    "MigrationOrderError",
    "MigrationNotReversibleError",
    "RUNNER_VERSION",
    # State
    "DEFAULT_STATE_DIR",
    "MigrationState",
    "STATE_FILENAME",
    "STATE_LOCK_FILENAME",
    "STATE_SCHEMA_VERSION",
    "acquire_state_lock",
    "is_applied",
    "load_state",
    "lock_file_path",
    "mark_applied",
    "mark_unapplied",
    "save_state_atomic",
    "state_file_path",
]
