"""Vault migration 0004 — add ``conversation_status:`` field to Person notes.

Pillar D Week 4-5 vault migration. Per ADR-0028 D119, the
conversation state machine's per-thread states are denormalized into
ONE per-Person ``conversation_status:`` frontmatter field via the
aggregation logic in
``orchestrator.conversation_state.derived_conversation_status``
(highest-priority state across all threads wins).

This migration STAMPS the field at its ledger-derived value on every
Person note. Existing operators who upgrade to Pillar D Week 4-5 get
the field populated retroactively from the conversation events
already in their ledger (e.g., pre-Week-4-5 replies that were
classified by Pass G now have their per-thread state computed +
aggregated to the Person frontmatter).

Why a migration (not just Pass C heal)
--------------------------------------

Pass C heals the field on every reconcile run. The migration's role
is the ONE-TIME existing-operator seed per ADR-0014 D36's convention:

* Without the migration, the field is ABSENT on every pre-Week-4-5
  Person note. Pass C's heal extension (per ADR-0028 D119) adds the
  field on each reconcile run that touches the Person, but operators
  who don't reconcile see stale state.

* With the migration, the field lands at ledger-derived value on the
  next ``runner.apply()`` invocation. Pass C heals on subsequent
  reconcile runs.

The migration is reversible — ``downgrade`` removes the field via
the inverse surgical-edit helper.

Contract
--------

* **Idempotent.** Person notes already at the ledger-derived value
  are silently skipped. Notes at a stale value (drift since previous
  migration apply OR operator hand-edit) are HEALED to the ledger-
  derived value. Notes with no derivable status (no conversation
  events for the person_id) are left untouched (no field stamped —
  absent field is the right "no conversation yet" state).

* **Reversible.** ``downgrade`` removes the field via
  :func:`._vault_io.remove_frontmatter_field_text`.

* **Per-file atomic.** Each note's rewrite goes through
  :func:`._vault_io.write_person_frontmatter_atomic` —
  tmp-then-rename with ``fsync``. A crash mid-batch leaves every file
  in either the pre-migration or post-migration shape, never half.

* **Refuses on missing vault.** ``ctx.vault_dir is None`` raises
  ``ValueError`` before any file is touched.

* **Refuses on missing ledger.** ``ctx.ledger_dir is None`` raises
  ``ValueError`` — the migration can't compute the ledger-derived
  status without it.

* **Tolerates unexpected `conversation_status` values.** Per the
  asymmetric-failure-cost calculus (PILLAR-PLAN §0), a stale or
  operator-set value drifts to the ledger-derived canonical — the
  ledger is the SoT per I1. Distinct from vault/0001's refuse-loud
  posture on ``schema_version`` (where any non-1 value is operator
  error needing human review); ``conversation_status`` values evolve
  with the conversation state machine + the migration is the right
  surface to converge them.

Non-Person files (sub-notes, drafts) are silently skipped via
``is_person_note``. People notes with no ``id:`` field (newly-
created drafts in progress) are skipped — the migration needs a
person_id to compute the ledger-derived status.

See ADR-0028 D119 for the design rationale + the per-Person
aggregation logic + the priority order (unsubscribed > active >
dormant > classified > replied).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._vault_io import (
    add_frontmatter_field_text,
    is_person_note,
    iter_person_notes,
    read_person_frontmatter,
    remove_frontmatter_field_text,
    write_person_frontmatter_atomic,
)


MIGRATION_ID = "0004_add_conversation_status_to_person_notes"
CONVERSATION_STATUS_FIELD = "conversation_status"


# Obsidian Sync concurrency warning — printed at upgrade/downgrade
# start regardless of dry_run, so operators see it BEFORE deciding
# to apply. Mirrors vault/0001 + vault/0002 + vault/0003's
# convention.
_OBSIDIAN_SYNC_WARNING = (
    "WARNING: vault migration about to rewrite Person notes "
    "(conversation_status). If Obsidian Sync is uploading concurrent "
    "edits, merge conflicts may appear as .conflicted.md files in "
    "your vault. Quit Obsidian before running apply, or accept the "
    "rare conflict-recovery cost."
)


def _import_runtime_helpers():
    """Lazy-load the ledger + conversation_state modules.

    The runtime modules live at the orchestrator/ top-level (bare-name
    imports per the project's CWD convention). Migrations are inside
    a subpackage so we go through the package import path to keep
    test isolation clean.
    """
    from orchestrator import conversation_state as _cs
    from orchestrator import ledger as _led
    return _led, _cs


@dataclass
class AddConversationStatusToPersonNotes:
    """Stamp ``conversation_status:`` on every Person note from ledger state.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work happens in
    :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as
    ``MIGRATION``; the category sub-package's ``__init__.py``
    registers it into ``MIGRATIONS``.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.VAULT
    description: str = (
        "Add conversation_status: <state> to every Person note from "
        "ledger-derived per-thread aggregation (Pillar D Week 4-5 — "
        "per-Person denormalized view of the conversation state "
        "machine per ADR-0028 D119)"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Stamp ``conversation_status:`` on every Person note with a
        derivable conversation state.

        Walks every ``*.md`` under ``<vault_dir>/10 People/``; for
        each Person note (per ``is_person_note``), computes the
        ledger-derived conversation status via
        :func:`conversation_state.derived_conversation_status`; stamps
        the field via tmp-then-rename atomic write.

        * Skips files with no parseable frontmatter (sub-notes, drafts).
        * Skips files where ``type != "person"``.
        * Skips Person notes with no ``id:`` field (drafts in progress).
        * Skips Person notes with no derivable conversation status
          (no conversation events for the person_id) — absent field is
          the right "no conversation yet" state.
        * Skips Person notes already at the ledger-derived value.
        * For Person notes with drift (vault value ≠ ledger-derived
          OR vault field absent) → surgically inserts/updates via
          tmp-then-rename atomic write.

        Returns a :class:`MigrationResult` with ``affected_count`` set
        to the number of Person notes actually rewritten (or in
        ``dry_run`` mode, the number that WOULD be rewritten).

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None`` (vault not configured),
            or when ``ctx.ledger_dir`` is ``None`` (ledger not
            configured — migration needs both).
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} requires ctx.vault_dir; "
                f"set vault.path in ~/.outreach-factory/config.yml or "
                f"pass --vault-path."
            )
        if ctx.ledger_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} requires ctx.ledger_dir; "
                f"the migration computes per-Person conversation state "
                f"from the ledger. Set ledger.dir in "
                f"~/.outreach-factory/config.yml or pass --ledger-dir."
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)

        _led, _cs = _import_runtime_helpers()
        led = _led.Ledger(ctx.ledger_dir)

        # Per ADR-0028 D119 — precompute the conversation-state map
        # ONCE for this migration run, then query per-Person. Saves
        # O(N persons * full-ledger-walk) re-computation. Same
        # pattern as Pass C's heal extension.
        thread_states = _cs.compute_thread_states(led)

        affected = 0
        already_at_target = 0
        skipped_no_state = 0
        skipped_no_person_id = 0
        skipped_non_person = 0
        stamp_counts: dict[str, int] = {}

        for note in iter_person_notes(ctx.vault_dir):
            fm, _body = read_person_frontmatter(note)
            if not is_person_note(fm):
                skipped_non_person += 1
                continue
            assert fm is not None
            person_id = fm.get("id")
            if not person_id or not isinstance(person_id, str):
                skipped_no_person_id += 1
                continue

            derived = _cs.derived_conversation_status(
                led, person_id, thread_states=thread_states,
            )
            if derived is None:
                skipped_no_state += 1
                continue

            existing = fm.get(CONVERSATION_STATUS_FIELD)
            if isinstance(existing, str):
                existing = existing.strip()
            if existing == derived:
                already_at_target += 1
                continue

            text = note.read_text(encoding="utf-8")
            if existing in (None, ""):
                new_text = add_frontmatter_field_text(
                    text, CONVERSATION_STATUS_FIELD, derived,
                )
            else:
                # Use surgical regex replace for the in-place update
                # (mirrors reconcile's ``_write_conversation_status``
                # — preserves comments + ordering of every other
                # field).
                pattern = re.compile(
                    rf"^{re.escape(CONVERSATION_STATUS_FIELD)}:\s*.*$",
                    re.MULTILINE,
                )
                if not text.startswith("---\n"):
                    raise ValueError(
                        f"no YAML frontmatter in {note}"
                    )
                end = text.find("\n---\n", 4)
                if end == -1:
                    raise ValueError(
                        f"unterminated frontmatter in {note}"
                    )
                fm_text = text[4:end]
                if pattern.search(fm_text):
                    fm_text = pattern.sub(
                        f"{CONVERSATION_STATUS_FIELD}: {derived}",
                        fm_text,
                    )
                else:
                    fm_text = (
                        fm_text.rstrip("\n")
                        + f"\n{CONVERSATION_STATUS_FIELD}: {derived}"
                    )
                new_text = text[:4] + fm_text + text[end:]

            ctx.logger.info(
                "%s: stamping conversation_status: %s on %s "
                "(was %s)",
                self.id, derived, note.name, existing,
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1
            stamp_counts[derived] = stamp_counts.get(derived, 0) + 1

        verb = "would stamp" if ctx.dry_run else "stamped"
        ctx.logger.info(
            "%s conversation_status on %d Person notes "
            "(%s; %d already at target, %d no derivable state, "
            "%d no person_id, %d non-Person skipped)",
            verb, affected,
            ", ".join(f"{c} {s}" for s, c in sorted(stamp_counts.items())),
            already_at_target, skipped_no_state,
            skipped_no_person_id, skipped_non_person,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} conversation_status on {affected} Person "
                f"notes ({stamp_counts}; {already_at_target} already "
                f"at target, {skipped_no_state} no derivable state, "
                f"{skipped_no_person_id} no person_id, "
                f"{skipped_non_person} non-Person skipped)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove ``conversation_status`` from every Person note that has it.

        Inverse of :meth:`upgrade`. Operators rarely invoke; the
        framework requires ``allow_rollback=True`` explicitly.

        Iterates every Person note and removes the
        ``conversation_status:`` line via surgical edit (preserves
        all other fields + comments). Per-file atomic via
        tmp-then-rename.

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None``.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} downgrade requires "
                f"ctx.vault_dir."
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)

        affected = 0
        already_absent = 0
        skipped_non_person = 0

        for note in iter_person_notes(ctx.vault_dir):
            fm, _body = read_person_frontmatter(note)
            if not is_person_note(fm):
                skipped_non_person += 1
                continue
            assert fm is not None
            if CONVERSATION_STATUS_FIELD not in fm:
                already_absent += 1
                continue
            text = note.read_text(encoding="utf-8")
            new_text = remove_frontmatter_field_text(
                text, CONVERSATION_STATUS_FIELD,
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would remove" if ctx.dry_run else "removed"
        ctx.logger.info(
            "%s conversation_status from %d Person notes "
            "(%d already absent, %d non-Person skipped)",
            verb, affected, already_absent, skipped_non_person,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} conversation_status from {affected} Person "
                f"notes ({already_absent} already absent, "
                f"{skipped_non_person} non-Person skipped)"
            ),
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: AddConversationStatusToPersonNotes = (
    AddConversationStatusToPersonNotes()
)


__all__ = [
    "AddConversationStatusToPersonNotes",
    "CONVERSATION_STATUS_FIELD",
    "MIGRATION",
    "MIGRATION_ID",
]
