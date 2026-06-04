"""Vault migrations — Markdown frontmatter rewrites.

The vault is a denormalized view of the ledger (I1); reconcile heals
it from the ledger. Vault migrations rewrite YAML frontmatter in place
via the per-file IO surface in :mod:`._vault_io`.

Atomicity is per-file: a vault migration that rewrites N notes must
either complete all N writes or leave the vault in a consistent state
(every file is either the pre-migration shape or the post-migration
shape; no file is half-written). The migration's ``upgrade`` is
responsible for per-file atomicity (use
:func:`._vault_io.write_person_frontmatter_atomic` — tmp-then-rename);
the runner's state file tracks batch-level atomicity (applied-or-not
for the migration as a whole).

Vault migrations are usually reversible (rename a field back, drop a
new field). When a vault migration is genuinely one-way (purging
fields, dropping content), declare ``is_reversible=False`` — the
runner refuses ``rollback`` on it and prints "restore from backup."

Per-category dispatcher boundary
--------------------------------

Vault migrations consume :mod:`._vault_io` for the per-file IO. The
helper module exposes:

* :func:`._vault_io.iter_person_notes` — walk the Person notes,
  skipping hidden + Obsidian Sync conflict files.
* :func:`._vault_io.read_person_frontmatter` — parse frontmatter +
  body. Returns ``(None, body)`` for files without parseable
  frontmatter (sub-notes); raises :class:`._vault_io.FrontmatterError`
  for files with corrupt frontmatter.
* :func:`._vault_io.is_person_note` — filter predicate.
* :func:`._vault_io.add_frontmatter_field_text` /
  :func:`._vault_io.remove_frontmatter_field_text` — surgical insert /
  delete preserving comments + ordering of unaffected fields.
* :func:`._vault_io.write_person_frontmatter_atomic` — tmp-then-rename
  atomic write per file.

See ADR-0011 for the vault-migration-specific design (per-file
atomicity, Obsidian Sync handling, helper-module dispatcher shape).
"""

from __future__ import annotations

from ..types import Migration
from .migration_0001 import MIGRATION as MIGRATION_0001_ADD_SCHEMA_VERSION
from .migration_0002 import MIGRATION as MIGRATION_0002_BACKFILL_IDENTITY
from .migration_0003_add_linkedin_action_to_touch_notes import (
    MIGRATION as MIGRATION_0003_ADD_LINKEDIN_ACTION,
)
from .migration_0004_add_conversation_status_to_person_notes import (
    MIGRATION as MIGRATION_0004_ADD_CONVERSATION_STATUS,
)
from .migration_0005_add_discovery_lineage_to_identity_keys import (
    MIGRATION as MIGRATION_0005_ADD_DISCOVERY_LINEAGE,
)
from .migration_0006_add_followup_step_to_person_notes import (
    MIGRATION as MIGRATION_0006_ADD_FOLLOWUP_STEP,
)


MIGRATIONS: list[Migration] = [
    MIGRATION_0001_ADD_SCHEMA_VERSION,
    MIGRATION_0002_BACKFILL_IDENTITY,
    MIGRATION_0003_ADD_LINKEDIN_ACTION,
    MIGRATION_0004_ADD_CONVERSATION_STATUS,
    MIGRATION_0005_ADD_DISCOVERY_LINEAGE,
    MIGRATION_0006_ADD_FOLLOWUP_STEP,
]
