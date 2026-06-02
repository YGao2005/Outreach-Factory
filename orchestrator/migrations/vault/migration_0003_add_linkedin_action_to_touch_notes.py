"""Vault migration 0003 — stamp ``linkedin_action: invite|dm`` on LinkedIn touch notes.

Pillar C Week 2 vault migration. Walks ``<ctx.vault_dir>/40 Conversations/``
for LinkedIn touch notes (``type: touch`` + ``channel: linkedin``) and
stamps an explicit ``linkedin_action:`` frontmatter field via the
filename-pattern heuristic. The companion ledger migration
(``ledger/0003_baseline_li_invite_history``) reads this field in
preference to the heuristic, so an operator who runs vault/0003 before
ledger/0003 gets deterministic classification on every touch.

Why explicit field + heuristic
------------------------------

Per ADR-0015 D38: pre-Pillar-C touch notes don't distinguish invite vs
DM at the frontmatter level — operators wrote "linkedin invite" or
"linkedin dm" in the filename but the frontmatter typically just says
``channel: linkedin``. Going forward, Pillar C's LinkedIn dispatcher
stamps ``linkedin_action: invite | dm`` on every touch it writes. This
migration backports the field to historical touches so:

1. ``ledger/0003`` can correlate touches to invite-vs-DM
   deterministically (rather than re-applying the filename heuristic
   on every Pillar C reconcile pass).
2. Pillar D's reply-classifier work has a clean per-touch invite-vs-DM
   discriminator without re-parsing filenames.
3. Pillar G's per-channel funnel observability can group by
   ``linkedin_action:`` without filename heuristics.

Heuristic (mirrors the ledger/0003 fallback)
--------------------------------------------

* Filename matches ``invite`` or ``connect`` → ``linkedin_action: invite``.
* Filename matches ``dm`` or ``message`` → ``linkedin_action: dm``.
* Default (neither matches) → ``linkedin_action: invite`` per the
  historical-prevalence rationale in ADR-0015 D38.

The heuristic logs each match decision at INFO level so an operator
can review the migration's classifications before subsequent migrations
load-bear on them.

Contract
--------

* **Idempotent.** Touch notes already declaring ``linkedin_action:`` are
  silently skipped. Re-running ``apply`` after a successful apply is
  a no-op (``affected_count = 0``).
* **Reversible.** ``downgrade`` removes the field via the inverse
  surgical-edit helper. Per-file atomicity holds on the reverse path
  too. (Distinct from ledger/0003 which is structurally irreversible.)
* **Per-file atomic.** Each note's rewrite goes through
  :func:`._vault_io.write_person_frontmatter_atomic` — tmp-then-rename
  with ``fsync``. A crash mid-batch leaves every file in either the
  pre-migration or post-migration shape, never half.
* **Refuses on missing vault.** ``ctx.vault_dir is None`` raises
  ``ValueError`` before any file is touched.
* **Refuses on unexpected `linkedin_action`.** A touch note declaring
  ``linkedin_action: unexpected_value`` raises
  :class:`._vault_io.FrontmatterError` — the migration does NOT
  overwrite. Operator must inspect + decide. (Mirrors vault/0001's
  ``schema_version: <unexpected>`` refuse-loud posture.)
* **Refuses on corrupt YAML.** A touch note with malformed YAML inside
  frontmatter delimiters raises ``FrontmatterError`` with the path.
  Operator fixes the file + re-runs apply (idempotent retry).

Non-LinkedIn touches are silently skipped. The walker yields every
``*.md`` under ``40 Conversations/``; the migration filters via
``is_touch_note`` + ``channel: linkedin`` predicate.

See ADR-0015 D38 for the design rationale, alternatives, and the
operator-discipline carve-out (operators with non-conventional
filename patterns can manually stamp ``linkedin_action:`` before
running this migration; the explicit field always wins).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._vault_io import (
    FrontmatterError,
    add_frontmatter_field_text,
    is_touch_note,
    iter_touch_notes,
    read_person_frontmatter,
    remove_frontmatter_field_text,
    write_person_frontmatter_atomic,
)


MIGRATION_ID = "0003_add_linkedin_action_to_touch_notes"

LINKEDIN_CHANNEL = "linkedin"
LINKEDIN_ACTION_FIELD = "linkedin_action"
LINKEDIN_ACTION_INVITE = "invite"
LINKEDIN_ACTION_DM = "dm"

# Acceptable existing values — the migration silently skips touches
# already declaring one of these. Anything else raises
# FrontmatterError per the refuse-loud posture.
_ACCEPTABLE_VALUES = frozenset({
    LINKEDIN_ACTION_INVITE, LINKEDIN_ACTION_DM,
})

# Filename-pattern heuristic. Word-boundary matching avoids false
# positives (e.g. "invitation-response" is still an invite; but a
# touch named "deinvited" would never appear by convention).
_INVITE_PATTERN = re.compile(r"\b(?:invite|connect)\b", re.IGNORECASE)
_DM_PATTERN = re.compile(r"\b(?:dm|message)\b", re.IGNORECASE)

# Obsidian Sync concurrency warning — printed at upgrade/downgrade start
# regardless of dry_run, so operators see it BEFORE deciding to apply.
# Mirrors vault/0001 + vault/0002.
_OBSIDIAN_SYNC_WARNING = (
    "WARNING: vault migration about to rewrite LinkedIn touch notes. "
    "If Obsidian Sync is uploading concurrent edits, merge conflicts "
    "may appear as .conflicted.md files in your vault. Quit Obsidian "
    "before running apply, or accept the rare conflict-recovery cost."
)


def _classify_action_from_filename(name: str) -> str:
    """Return ``"invite"`` or ``"dm"`` per the ADR-0015 D38 heuristic.

    * Matches ``invite`` or ``connect`` → invite.
    * Matches ``dm`` or ``message`` → dm.
    * Default (no match) → invite.

    Centralized here + duplicated in
    :mod:`orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history._classify_linkedin_action`
    so each module is self-contained for its own test surface. The
    duplication is two patterns + one fallback; the alternative (a
    shared helper module) would introduce a Pillar C-specific shared
    helper that lives in neither sub-package cleanly.

    **If you change the patterns here, mirror the change in the
    ledger module's twin function.** The two functions MUST stay
    consistent because the ledger migration's filename-heuristic
    fallback (when ``linkedin_action:`` is absent from frontmatter)
    must produce the SAME classification this vault migration would
    have stamped. Divergence between the two would silently produce
    inconsistent invite-vs-DM classifications. Per Week 2 per-week
    review P3-1.
    """
    if _INVITE_PATTERN.search(name):
        return LINKEDIN_ACTION_INVITE
    if _DM_PATTERN.search(name):
        return LINKEDIN_ACTION_DM
    return LINKEDIN_ACTION_INVITE


@dataclass
class AddLinkedInActionToTouchNotes:
    """Stamp ``linkedin_action: invite|dm`` on LinkedIn touch notes.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work happens in
    :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as
    ``MIGRATION``; the category sub-package's ``__init__.py`` registers
    it into ``MIGRATIONS``.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.VAULT
    description: str = (
        "Stamp linkedin_action: invite|dm on LinkedIn touch notes via "
        "filename-pattern heuristic (Pillar C Week 2 — supports "
        "ledger/0003 deterministic invite-vs-DM classification)"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Stamp ``linkedin_action:`` on every LinkedIn touch without one.

        Walks every ``*.md`` under ``<vault_dir>/40 Conversations/``,
        reads each note's frontmatter, and:

        * Skips files with no parseable frontmatter (sub-notes, drafts).
        * Skips files where ``type != "touch"`` (Person notes, lead
          lists, diary entries).
        * Skips touch notes where ``channel != "linkedin"`` (email
          touches, future Twitter touches).
        * Skips LinkedIn touches already at ``linkedin_action: invite |
          dm`` (idempotent).
        * Refuses LOUD on touches with an unexpected ``linkedin_action``
          value (raises ``FrontmatterError``).
        * For LinkedIn touches with no ``linkedin_action``, classifies
          via :func:`_classify_action_from_filename` and surgically
          inserts the field via tmp-then-rename atomic write.

        Returns a :class:`MigrationResult` with ``affected_count`` set
        to the number of touch notes actually rewritten (or in
        ``dry_run`` mode, the number that WOULD be rewritten).

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None`` (vault not configured).
        FrontmatterError:
            On any unparseable / unexpected-linkedin_action touch note.
            The state-file pointer does NOT advance — the runner's
            atomicity contract.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} requires ctx.vault_dir; "
                f"set vault.path in ~/.outreach-factory/config.yml or "
                f"pass --vault-path.",
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)

        affected = 0
        already_stamped = 0
        skipped_non_linkedin = 0
        skipped_non_touch = 0
        classify_counts = {LINKEDIN_ACTION_INVITE: 0, LINKEDIN_ACTION_DM: 0}

        for note in iter_touch_notes(ctx.vault_dir):
            fm, _body = read_person_frontmatter(note)
            if not is_touch_note(fm):
                skipped_non_touch += 1
                continue
            assert fm is not None  # is_touch_note ensures non-None
            channel = (fm.get("channel") or "").strip().lower()
            if channel != LINKEDIN_CHANNEL:
                skipped_non_linkedin += 1
                continue
            existing = fm.get(LINKEDIN_ACTION_FIELD)
            if isinstance(existing, str):
                existing = existing.strip().lower()
            if existing in _ACCEPTABLE_VALUES:
                already_stamped += 1
                continue
            if existing not in (None, ""):
                raise FrontmatterError(
                    f"{note} declares {LINKEDIN_ACTION_FIELD}: "
                    f"{existing!r}; this migration expects absent or "
                    f"one of {sorted(_ACCEPTABLE_VALUES)!r}. Manual "
                    f"intervention required — re-run apply after "
                    f"inspecting the file.",
                )

            action = _classify_action_from_filename(note.name)
            classify_counts[action] += 1
            ctx.logger.info(
                "%s: classifying %s as linkedin_action: %s (filename heuristic)",
                self.id, note.name, action,
            )
            text = note.read_text(encoding="utf-8")
            new_text = add_frontmatter_field_text(
                text, LINKEDIN_ACTION_FIELD, action,
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would stamp" if ctx.dry_run else "stamped"
        ctx.logger.info(
            "%s linkedin_action on %d LinkedIn touch(es): "
            "%d invite + %d dm "
            "(%d already stamped, %d non-LinkedIn skipped, "
            "%d non-touch skipped)",
            verb, affected,
            classify_counts[LINKEDIN_ACTION_INVITE],
            classify_counts[LINKEDIN_ACTION_DM],
            already_stamped, skipped_non_linkedin, skipped_non_touch,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} linkedin_action on {affected} LinkedIn "
                f"touch(es): {classify_counts[LINKEDIN_ACTION_INVITE]} "
                f"invite + {classify_counts[LINKEDIN_ACTION_DM]} dm "
                f"({already_stamped} already stamped, "
                f"{skipped_non_linkedin} non-LinkedIn skipped, "
                f"{skipped_non_touch} non-touch skipped)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove ``linkedin_action`` from every LinkedIn touch with one.

        Inverse of :meth:`upgrade`. Operators rarely invoke; the
        framework requires ``allow_rollback=True`` explicitly.

        Iterates every LinkedIn touch and removes the
        ``linkedin_action:`` line via surgical edit (preserves all
        other fields + comments). Per-file atomic via tmp-then-rename.

        Note: downgrading vault/0003 doesn't break ledger/0003 (which is
        irreversible) — ledger/0003 already emitted its events; without
        ``linkedin_action:`` the next time ledger/0003 runs, the
        filename heuristic determines invite-vs-DM. As long as no
        operator has manually edited a filename to a different
        invite-vs-DM pattern between the two migrations, the
        classification is stable. ADR-0015 D38 §"Downgrade semantics"
        documents this.

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None``.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"vault migration {self.id!r} downgrade requires "
                f"ctx.vault_dir.",
            )
        ctx.logger.warning(_OBSIDIAN_SYNC_WARNING)

        affected = 0
        already_absent = 0
        skipped_non_linkedin = 0
        skipped_non_touch = 0

        for note in iter_touch_notes(ctx.vault_dir):
            fm, _body = read_person_frontmatter(note)
            if not is_touch_note(fm):
                skipped_non_touch += 1
                continue
            assert fm is not None
            channel = (fm.get("channel") or "").strip().lower()
            if channel != LINKEDIN_CHANNEL:
                skipped_non_linkedin += 1
                continue
            if LINKEDIN_ACTION_FIELD not in fm:
                already_absent += 1
                continue
            text = note.read_text(encoding="utf-8")
            new_text = remove_frontmatter_field_text(
                text, LINKEDIN_ACTION_FIELD,
            )
            if not ctx.dry_run:
                write_person_frontmatter_atomic(note, new_text)
            affected += 1

        verb = "would remove" if ctx.dry_run else "removed"
        ctx.logger.info(
            "%s linkedin_action from %d LinkedIn touch(es) "
            "(%d had no field, %d non-LinkedIn skipped, "
            "%d non-touch skipped)",
            verb, affected, already_absent,
            skipped_non_linkedin, skipped_non_touch,
        )
        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} linkedin_action from {affected} LinkedIn "
                f"touch(es) ({already_absent} already absent, "
                f"{skipped_non_linkedin} non-LinkedIn skipped, "
                f"{skipped_non_touch} non-touch skipped)"
            ),
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: AddLinkedInActionToTouchNotes = AddLinkedInActionToTouchNotes()


__all__ = [
    "AddLinkedInActionToTouchNotes",
    "LINKEDIN_ACTION_DM",
    "LINKEDIN_ACTION_FIELD",
    "LINKEDIN_ACTION_INVITE",
    "LINKEDIN_CHANNEL",
    "MIGRATION",
    "MIGRATION_ID",
]
