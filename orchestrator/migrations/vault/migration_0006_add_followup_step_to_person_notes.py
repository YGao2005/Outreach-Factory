"""Vault migration 0006 - add ``followup_step:`` field to Person notes.

Follow-up cadence vault migration. ``followup_step`` is the per-Person
denormalization of the follow-up touch count derived from the ledger by
:func:`orchestrator.followup.derive_followup_steps`: the number of follow-up
touches already sent (0 = the cold email sent, no follow-ups; 1 = first
follow-up sent; 2 = second follow-up sent). The ledger remains the source of
truth; this field is the denormalized worklist key the dispatch skill scans.

This migration STAMPS the field at its ledger-derived value on every Person note
that has at least one confirmed email touch. Existing operators who turn on
follow-ups get the field populated retroactively from the sends already in their
ledger, so the dispatch skill + ``status`` can report per-step from the first
run rather than only after the next reconcile heal.

Why a migration (not just a heal)
---------------------------------
Same one-time existing-operator seed convention as vault/0004
(conversation_status). Without the migration, ``followup_step`` is ABSENT on
every Person note that predates the feature; the field lands at its ledger-
derived value on the next ``runner.apply()``.

Contract
--------
* **Idempotent.** Notes already at the ledger-derived value are skipped; notes
  at a stale value (drift or hand-edit) are HEALED to the derived value; notes
  with no confirmed touch (no derivable step) are left untouched (absent field =
  "no sequence yet").
* **Reversible.** ``downgrade`` removes the field.
* **Per-file atomic.** Each rewrite goes through tmp-then-rename with ``fsync``.
* **Refuses on missing vault / ledger.** Both are required - the migration
  computes the derived step from the ledger.

Mirrors vault/0004's structure (ADR-0028 D119 set the per-Person ledger-derived
denormalization pattern + the surgical-edit / atomic-write discipline).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._vault_io import (
    add_frontmatter_field_text,
    is_person_note,
    iter_person_notes,
    read_person_frontmatter,
    remove_frontmatter_field_text,
    write_person_frontmatter_atomic,
)


MIGRATION_ID = "0006_add_followup_step_to_person_notes"
FOLLOWUP_STEP_FIELD = "followup_step"


_OBSIDIAN_SYNC_WARNING = (
    "WARNING: vault migration about to rewrite Person notes (followup_step). "
    "If Obsidian Sync is uploading concurrent edits, merge conflicts may appear "
    "as .conflicted.md files in your vault. Quit Obsidian before running apply, "
    "or accept the rare conflict-recovery cost."
)


def _import_runtime_helpers():
    """Lazy-load the ledger + followup modules through the package path (the
    runtime modules live at the orchestrator/ top-level)."""
    from orchestrator import followup as _fu
    from orchestrator import ledger as _led
    return _led, _fu


@dataclass
class AddFollowupStepToPersonNotes:
    """Stamp ``followup_step:`` on every Person note from ledger-derived touch
    counts. Thin dataclass implementing the ``Migration`` Protocol; the work is
    in :meth:`upgrade` / :meth:`downgrade`."""

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.VAULT
    description: str = (
        "Add followup_step: <n> to every Person note with a confirmed email "
        "touch, from the ledger-derived follow-up count (cadence engine "
        "denormalization)"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} requires ctx.vault_dir; set "
                f"vault.path in ~/.outreach-factory/config.yml or pass "
                f"--vault-path."
            )
        if ctx.ledger_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} requires ctx.ledger_dir; the "
                f"migration computes per-Person follow-up counts from the "
                f"ledger. Set ledger.dir or pass --ledger-dir."
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)

        _led, _fu = _import_runtime_helpers()
        led = _led.Ledger(ctx.ledger_dir)
        # One ledger walk for the whole migration run, then query per-Person
        # (same precompute-once pattern as vault/0004).
        steps_by_person = _fu.derive_followup_steps(led.all_events())

        affected = 0
        already_at_target = 0
        skipped_no_step = 0
        skipped_no_person_id = 0
        skipped_non_person = 0

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

            derived = steps_by_person.get(person_id)
            if derived is None:
                skipped_no_step += 1
                continue

            existing = fm.get(FOLLOWUP_STEP_FIELD)
            if existing == derived:
                already_at_target += 1
                continue

            text = note.read_text(encoding="utf-8")
            if existing is None:
                new_text = add_frontmatter_field_text(
                    text, FOLLOWUP_STEP_FIELD, derived,
                )
            else:
                # Surgical in-place update (preserve comments + field order),
                # mirroring vault/0004's stale-value heal path.
                pattern = re.compile(
                    rf"^{re.escape(FOLLOWUP_STEP_FIELD)}:\s*.*$", re.MULTILINE,
                )
                if not text.startswith("---\n"):
                    raise ValueError(f"no YAML frontmatter in {note}")
                end = text.find("\n---\n", 4)
                if end == -1:
                    raise ValueError(f"unterminated frontmatter in {note}")
                fm_text = text[4:end]
                if pattern.search(fm_text):
                    fm_text = pattern.sub(
                        f"{FOLLOWUP_STEP_FIELD}: {derived}", fm_text,
                    )
                else:
                    fm_text = (
                        fm_text.rstrip("\n")
                        + f"\n{FOLLOWUP_STEP_FIELD}: {derived}"
                    )
                new_text = text[:4] + fm_text + text[end:]

            ctx.logger.info(
                "%s: stamping followup_step: %s on %s (was %s)",
                self.id, derived, note.name, existing,
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would stamp" if ctx.dry_run else "stamped"
        ctx.logger.info(
            "%s followup_step on %d Person notes (%d already at target, "
            "%d no derivable step, %d no person_id, %d non-Person skipped)",
            verb, affected, already_at_target, skipped_no_step,
            skipped_no_person_id, skipped_non_person,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} followup_step on {affected} Person notes "
                f"({already_at_target} already at target, {skipped_no_step} "
                f"no derivable step, {skipped_no_person_id} no person_id, "
                f"{skipped_non_person} non-Person skipped)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} downgrade requires ctx.vault_dir."
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
            if FOLLOWUP_STEP_FIELD not in fm:
                already_absent += 1
                continue
            text = note.read_text(encoding="utf-8")
            new_text = remove_frontmatter_field_text(text, FOLLOWUP_STEP_FIELD)
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would remove" if ctx.dry_run else "removed"
        ctx.logger.info(
            "%s followup_step from %d Person notes (%d already absent, "
            "%d non-Person skipped)",
            verb, affected, already_absent, skipped_non_person,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} followup_step from {affected} Person notes "
                f"({already_absent} already absent, {skipped_non_person} "
                f"non-Person skipped)"
            ),
        )


# Module-level singleton - the registry imports this directly.
MIGRATION: AddFollowupStepToPersonNotes = AddFollowupStepToPersonNotes()


__all__ = [
    "AddFollowupStepToPersonNotes",
    "FOLLOWUP_STEP_FIELD",
    "MIGRATION",
    "MIGRATION_ID",
]
