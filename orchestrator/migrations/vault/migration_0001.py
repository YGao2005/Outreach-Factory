"""Vault migration 0001 — add ``schema_version: 1`` to every Person note.

Pillar B Week 2's first real migration. Operationalizes invariant I3
(PILLAR-PLAN §1) for Person frontmatter: every Person note declares its
schema version so future schema evolutions can target old vs new shapes.

Greenfield-on-arrival: Person notes ship today with no ``schema_version:``
field. This migration stamps ``1`` on every note in one pass. Subsequent
migrations (Pillar D / E / F additions) bump the version each time they
mutate the Person-note shape.

Contract
--------

* **Idempotent.** Notes already declaring ``schema_version: 1`` are
  silently skipped. Re-running ``apply`` after a successful apply is
  a no-op (``affected_count = 0``).

* **Reversible.** ``downgrade`` removes the field via the inverse
  surgical-edit helper. Per-file atomicity holds on the reverse path
  too.

* **Per-file atomic.** Each note's rewrite goes through
  :func:`._vault_io.write_person_frontmatter_atomic` — tmp-then-rename
  with ``fsync``. A crash mid-batch leaves every file in either the
  pre-migration shape or the post-migration shape, never half.

* **Refuses on missing vault.** ``ctx.vault_dir is None`` raises
  ``ValueError`` before any file is touched.

* **Refuses on unexpected schema_version.** A Person note declaring
  ``schema_version: 2`` (or any non-1 value) raises
  :class:`._vault_io.FrontmatterError` — the migration does NOT
  overwrite. Operator must inspect + decide.

* **Refuses on corrupt YAML.** A Person note with malformed YAML inside
  the frontmatter delimiters raises FrontmatterError with the path so
  the operator can fix the file. Re-running apply after the fix
  retries idempotently.

Notes-on-non-Person-files: the iterator yields every ``*.md`` under
``<vault_dir>/10 People/``. Some operators store sub-notes (drafts,
diary entries, scratch files) alongside Person notes. The migration
silently skips files where ``type != "person"`` — those are not Person
notes and have no schema-version contract to honor.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._vault_io import (
    FrontmatterError,
    add_frontmatter_field_text,
    is_person_note,
    iter_person_notes,
    read_person_frontmatter,
    remove_frontmatter_field_text,
    write_person_frontmatter_atomic,
)


# The schema version this migration stamps. Bumping the Person-note
# schema to 2+ is a SEPARATE migration; this one's invariant is "go
# from no-version to v1." A separate ADR + ADR-0011 amendment will
# document the next bump's transformation when it lands.
SCHEMA_VERSION_VALUE = 1

# Obsidian Sync concurrency warning — printed at upgrade/downgrade start
# regardless of dry_run, so operators see it BEFORE deciding to apply.
# Per ADR-0011 D9: document + warn, no enforcement. The warning is the
# only operator-facing surface in Week 2; Pillar I revisits with hard
# isolation primitives.
_OBSIDIAN_SYNC_WARNING = (
    "WARNING: vault migration about to rewrite Person notes. If "
    "Obsidian Sync is uploading concurrent edits, merge conflicts may "
    "appear as .conflicted.md files in your vault. Quit Obsidian "
    "before running apply, or accept the rare conflict-recovery cost."
)


@dataclass
class AddSchemaVersionToPersonNotes:
    """Add ``schema_version: 1`` to every Person note's frontmatter.

    See module docstring for the full contract. This class is a thin
    dataclass implementing the ``Migration`` Protocol; the work happens
    in :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as ``MIGRATION``;
    the category sub-package's ``__init__.py`` registers it into
    ``MIGRATIONS = [MIGRATION]``.
    """

    id: str = "0001_add_schema_version_to_person_notes"
    category: MigrationCategory = MigrationCategory.VAULT
    description: str = (
        "Add schema_version: 1 to every Person note's frontmatter "
        "(I3 baseline for Person-note evolution)"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Stamp ``schema_version: 1`` on every Person note without one.

        Iterates every ``*.md`` under ``<vault_dir>/10 People/``,
        reads each note's frontmatter, and:

        * Skips files with no parseable frontmatter (sub-notes, drafts).
        * Skips files where ``type != "person"`` (touch notes, lead
          lists, diary entries).
        * Skips Person notes already at ``schema_version: 1`` (idempotent).
        * Refuses LOUD on Person notes with a different ``schema_version``
          value (raises ``FrontmatterError``).
        * For Person notes with no ``schema_version``, surgically inserts
          ``schema_version: 1`` as the last frontmatter line via
          tmp-then-rename atomic write.

        Returns a :class:`MigrationResult` with ``affected_count`` set
        to the number of Person notes actually rewritten (or in
        ``dry_run`` mode, the number that WOULD be rewritten).

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None`` (vault not configured).
        FrontmatterError:
            On any unparseable / unexpected-schema_version Person note.
            The state-file pointer does NOT advance — the runner's
            atomicity contract.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                "vault migration "
                "0001_add_schema_version_to_person_notes requires "
                "ctx.vault_dir; set vault.path in "
                "~/.outreach-factory/config.yml or pass --vault-path.",
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)
        affected = 0
        already_at_target = 0
        skipped_non_person = 0
        for note in iter_person_notes(ctx.vault_dir):
            fm, _body = read_person_frontmatter(note)
            if not is_person_note(fm):
                skipped_non_person += 1
                continue
            assert fm is not None  # is_person_note ensures non-None
            existing = fm.get("schema_version")
            if existing == SCHEMA_VERSION_VALUE:
                already_at_target += 1
                continue
            if existing is not None:
                raise FrontmatterError(
                    f"{note} declares schema_version: {existing!r}; "
                    f"this migration expects absent or "
                    f"{SCHEMA_VERSION_VALUE}. Manual intervention "
                    f"required — re-run apply after inspecting the file.",
                )
            text = note.read_text(encoding="utf-8")
            new_text = add_frontmatter_field_text(
                text, "schema_version", SCHEMA_VERSION_VALUE,
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would add" if ctx.dry_run else "added"
        ctx.logger.info(
            "%s schema_version: %d to %d Person notes "
            "(%d already at v%d, %d non-Person files skipped)",
            verb,
            SCHEMA_VERSION_VALUE,
            affected,
            already_at_target,
            SCHEMA_VERSION_VALUE,
            skipped_non_person,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} schema_version: {SCHEMA_VERSION_VALUE} to "
                f"{affected} Person notes ({already_at_target} already "
                f"at v{SCHEMA_VERSION_VALUE}, {skipped_non_person} "
                f"non-Person files skipped)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove ``schema_version`` from every Person note that has it.

        Inverse of :meth:`upgrade`. Operators rarely invoke; the
        framework requires ``allow_rollback=True`` explicitly.

        Iterates every Person note and removes the ``schema_version:``
        line via surgical edit (preserves all other fields + comments).
        Per-file atomic via tmp-then-rename.

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None``.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                "vault migration "
                "0001_add_schema_version_to_person_notes downgrade "
                "requires ctx.vault_dir.",
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
            if "schema_version" not in fm:
                already_absent += 1
                continue
            text = note.read_text(encoding="utf-8")
            new_text = remove_frontmatter_field_text(text, "schema_version")
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would remove" if ctx.dry_run else "removed"
        ctx.logger.info(
            "%s schema_version from %d Person notes "
            "(%d had no schema_version, %d non-Person skipped)",
            verb, affected, already_absent, skipped_non_person,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} schema_version from {affected} Person notes "
                f"({already_absent} already absent, "
                f"{skipped_non_person} non-Person files skipped)"
            ),
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: AddSchemaVersionToPersonNotes = AddSchemaVersionToPersonNotes()
