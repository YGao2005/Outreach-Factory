"""Ledger migration 0004 — backfill retroactive LinkedIn DM history.

Pillar C Week 3's per-channel ledger migration. Mirrors
``ledger/0003_baseline_li_invite_history`` in shape but scoped to
LinkedIn DMs: walks the operator's vault for ``sent: true`` LinkedIn
touch notes that classify as DM and emits retroactive ``li_dm_intent``
+ ``li_dm_confirmed`` event pairs so the post-migration ledger holds
the same two-phase shape production dispatchers (ADR-0016) emit going
forward.

What it does
------------

Reconstructs LinkedIn-DM history from the vault's current state by
emitting retroactive event pairs per matched DM touch note. Each event
carries ``_recovered_by: "backfill"`` so downstream readers can
distinguish synthetic backfill from organically-emitted events. Per
ADR-0014 D33 + D35:

1. **Per pair** — ``li_dm_intent`` + ``li_dm_confirmed`` both stamped
   ``channel: "linkedin"`` (D33 invariant — same channel value as
   ``ledger/0003`` because both invites + DMs share the LinkedIn
   channel; the discriminator at the funnel-query level is the
   event-type prefix). ``intent_id`` is deterministic
   (``bf_lidm_<sha256(person_id|date|action|touch_stem)[:16]>``) so
   re-runs are idempotent without ledger duplication.
2. **One audit-trail event** — ``migration_event`` with
   ``channel="linkedin"`` per ADR-0014 D35 + diagnostic fields:
   ``linkedin_dm_pairs_emitted``, ``linkedin_dm_pairs_skipped``,
   ``touches_without_person_match``, ``touches_skipped_not_dm``.

Distinguishing invite vs DM (ADR-0015 D38)
------------------------------------------

This migration reads the SAME classification primitive
(:func:`orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history._classify_linkedin_action`)
that ledger/0003 uses, then inverts the filter — DM touches are
walked here; invite touches are skipped (ledger/0003 walked those).
Sharing the classifier means a future change to the heuristic
(e.g. an additional filename pattern) lands in one place and both
migrations honor the new rule. Mirror-of-truth violation surfaces as
a stale test (Per Week 2 per-week review P3-1 — same shared-primitive
discipline).

Why ``bf_lidm_`` not ``bf_li_dm_``
----------------------------------

The ``_`` between the channel prefix and the action discriminator is
load-bearing — it would parse identically but reads more naturally
without it (``bf_lidm`` ≈ "backfill LinkedIn DM" reads as one unit;
``bf_li_dm`` could be misread as "backfill LinkedIn / DM"). The
companion ledger/0003's prefix is ``bf_li_`` (no second discriminator
needed because invites are the default action). The Pillar I CLI
operator filter ``--intent-prefix bf_lidm_`` is a one-token specifier.

Why ``is_reversible=False``
---------------------------

Append-only ledger (ADR-0010 D14). Same posture as ledger/0001 +
ledger/0002 + ledger/0003. Recovery path: restore the ledger directory
from backup + manually mark the migration un-applied via
:func:`orchestrator.migrations.state.mark_unapplied`. For operators
who have been using LinkedIn DMs via the pre-Pillar-C MCP-mediated
flow AND want their historical state preserved as-is (no retroactive
backfill emissions), the ADR-0016 §"Existing-operator seed"
subsection documents a one-time ``mark_applied`` incantation.

Cross-category dependency on vault/0002 + (optionally) vault/0003
-----------------------------------------------------------------

This migration READS Person notes to find their ``id:`` field
(stamped by vault/0002, same pattern as ledger/0003) AND optionally
reads touch notes for a ``linkedin_action:`` field (stamped by
vault/0003 when present). Touches without a matched Person ``id``
surface in the ``touches_without_person_match`` diagnostic. Touches
without ``linkedin_action:`` fall back to the filename heuristic via
``_classify_linkedin_action``.

ADR-0013 D27 + ADR-0014 D34 document the cross-category ordering
contract (VAULT → LEDGER → POLICY); ``ledger/0004`` slots into the
existing apply order without amendment.

Backfill overlap with ledger/0002 + ledger/0003
-----------------------------------------------

Dana's DM touch on 2026-04-20 produces THREE event pairs after a
full apply:

1. ``send_intent`` + ``send_confirmed`` from ledger/0002
   (channel-agnostic walker emits a generic pair for every
   ``sent: true`` touch).
2. ``li_dm_intent`` + ``li_dm_confirmed`` from this migration
   (per-action LinkedIn DM backfill).

The dual representation is by design per ADR-0015 §"Backfill overlap
with ledger/0002" (Pillar C Week 2 established the rationale for the
LinkedIn-invite case; the same logic applies to DMs). The cross-
channel rule's first-match-wins semantics short-circuit correctly
under dual representation — no double-engagement; both events carry
``channel: linkedin`` and the rule fires once.

Per-event atomicity
-------------------

Each append goes through :func:`._ledger_io.append_event_atomic`,
which delegates to :meth:`orchestrator.ledger.Ledger.append` — the
``O_APPEND + fcntl.lockf + fsync`` durability path every concurrent
writer in the system shares. A crash mid-batch leaves emitted events
durably on disk; the runner's state-file pointer does NOT advance
(ADR-0009 D4); re-running ``apply`` re-invokes ``upgrade`` from
scratch and the per-event idempotence checks (existing intent_id set,
per-touch dedup) skip already-emitted events.

Refuse-on-missing-vault
-----------------------

The migration requires ``ctx.vault_dir is not None`` (because it
reads touch notes from the vault). Raises ``ValueError`` if vault_dir
is unset — same shape as vault migrations + ledger/0002 + ledger/0003.

Refuse-on-missing-ledger
------------------------

Same shape as ledger/0001 + ledger/0002 + ledger/0003: raises
``FileNotFoundError`` if ``ctx.ledger_dir`` does not exist. Operators
with a fresh state dir emit at least one event through the normal
send path before invoking the migration, or ``mkdir -p`` the
directory.

See ADR-0016 for the full Week 3 design (per-channel DM dispatcher
shape, requires-existing-connection gate posture, lazy-stamping of
``linkedin_connected:`` per-Person state, operator-seed pattern).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..runner import RUNNER_VERSION
from ..types import MigrationCategory, MigrationContext, MigrationResult
from ..vault._vault_io import iter_touch_notes
from ._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    iter_events,
)
from .migration_0003_baseline_li_invite_history import (
    LINKEDIN_ACTION_DM,
    LINKEDIN_ACTION_FIELD,
    LINKEDIN_ACTION_INVITE,
    LINKEDIN_CHANNEL,
    PEOPLE_SUBDIR,
    RECOVERED_BY_TAG,
    _build_name_to_id,
    _classify_linkedin_action,
    _walk_linkedin_touch_records,
    _walk_person_records,
)


MIGRATION_ID = "0004_baseline_li_dm_history"

# Synthetic intent id prefix — ``bf_lidm_`` distinguishes from live
# LinkedIn DM ULIDs (``lidm_`` per Pillar C Week 3 dispatcher
# convention) AND from email backfill (``bf_``) AND from LinkedIn
# invite backfill (``bf_li_``). A reader scanning the ledger can
# instantly tell which sends came from each retroactive-reconstruction
# class. See module docstring for the ``bf_lidm_`` vs ``bf_li_dm_``
# naming choice.
SYNTHETIC_INTENT_PREFIX = "bf_lidm_"


# ---------------------------------------------------------------------------
# Helpers — most of the heavy lifting (Person walker, touch walker,
# name-to-id map, action classifier) is shared with ledger/0003 via
# direct import. Any divergence from ledger/0003's logic should be
# intentional + called out in ADR-0016. The only Week-3-specific code
# is the counts dataclass + the synthetic intent_id generator + the
# upgrade body's invite-vs-DM filter inversion.
# ---------------------------------------------------------------------------


@dataclass
class _DMBackfillCounts:
    """Per-category emit counts surfaced in MigrationResult.notes.

    Mirrors ledger/0003's ``_BackfillCounts`` shape modulo the
    invite-vs-DM naming inversion. Wrong-channel filtering happens
    inside :func:`_walk_linkedin_touch_records` (every touch the
    walker yields already passed the ``channel: linkedin`` check);
    a wrong-channel count would necessarily be zero, so we omit it
    rather than expose a misleading "always zero" counter to Pillar
    G's migration_event consumers. Same discipline as ledger/0003
    per Week 2 per-week review P2-3.
    """
    linkedin_dm_pairs_emitted: int = 0
    linkedin_dm_pairs_skipped: int = 0
    touches_without_person_match: list[str] = field(default_factory=list)
    touches_skipped_not_dm: list[str] = field(default_factory=list)


def _synth_intent_id(
    person_id: str,
    date_iso: str,
    action: str,
    touch_stem: str | None,
) -> str:
    """Deterministic synthetic intent id for LinkedIn-DM backfill.

    ``bf_lidm_`` prefix distinguishes from live LinkedIn DM ULIDs
    (``lidm_``) + from email backfill (``bf_``) + from LinkedIn
    invite backfill (``bf_li_``) + from live LinkedIn invite ULIDs
    (``li_``). The ``action`` discriminator (``"dm"``) ensures the
    bf_lidm_<hash> never collides with ledger/0003's bf_li_<hash>
    (different hash inputs even for the same touch via the action
    string).

    The touch_stem discriminator is load-bearing: two real LinkedIn
    DMs to the same person on the same day (initial + follow-up) are
    distinct sends — without the stem they'd hash-collide. Mirrors
    ledger/0003's ``_synth_intent_id``.
    """
    parts = [person_id, date_iso[:10], action]
    if touch_stem:
        parts.append(touch_stem)
    payload = "|".join(parts).encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()[:16]
    return f"{SYNTHETIC_INTENT_PREFIX}{h}"


@dataclass
class BaselineLinkedInDMHistory:
    """Emit retroactive ``li_dm_intent`` + ``li_dm_confirmed`` pairs.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work lives in
    :meth:`upgrade`. :meth:`downgrade` raises ``NotImplementedError``
    per the append-only-ledger constraint.

    Module-level singleton ``MIGRATION`` is registered in
    ``ledger/__init__.py::MIGRATIONS`` so the runner discovers it.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.LEDGER
    description: str = (
        "Backfill retroactive li_dm_intent + li_dm_confirmed event "
        "pairs from LinkedIn DM touch notes "
        "(Pillar C Week 3 — second per-channel ledger migration)"
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Emit retroactive LinkedIn DM pairs + migration_event.

        Walks ``<ctx.vault_dir>/40 Conversations/`` for ``sent: true``
        LinkedIn touch notes; classifies each via the
        :func:`_classify_linkedin_action` heuristic (or the
        ``linkedin_action:`` frontmatter field when set); emits
        retroactive ``li_dm_intent`` + ``li_dm_confirmed`` pairs for
        DM-classified touches; ends with one ``migration_event``
        carrying ``channel="linkedin"`` per ADR-0014 D35.

        Returns a ``MigrationResult`` whose ``affected_count`` is the
        total count of primary events emitted (one count per emitted
        pair — the migration_event itself does not count).

        Side effects on a successful apply:

        * ``2 * pairs_emitted + 1`` events appended to the ledger
          (intent + confirmed per pair; ``+ 1`` for the
          migration_event).
        * Zero vault writes.
        * Zero policy writes.

        On dry-run (``ctx.dry_run=True``): no on-disk mutation. The
        ``MigrationResult`` carries the same counts as a real apply
        would produce (iteration is identical; the
        ``append_event_atomic`` calls AND the closing
        ``emit_migration_event`` call are both skipped per ADR-0010
        D17 "a dry run mutates nothing").

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None`` (the backfill needs to
            read touch notes).
        FileNotFoundError:
            When ``ctx.ledger_dir`` does not exist on disk.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"ledger migration {self.id!r} requires ctx.vault_dir "
                f"(the backfill reads LinkedIn touch notes to "
                f"reconstruct DM history); set vault.path in "
                f"~/.outreach-factory/config.yml or pass an explicit "
                f"vault_dir to the runner.",
            )
        ledger_dir = Path(ctx.ledger_dir)
        if not ledger_dir.exists():
            raise FileNotFoundError(
                f"ledger migration {self.id!r} requires "
                f"ctx.ledger_dir to be an existing directory; got "
                f"{ledger_dir!s}. Either point the runner at the "
                f"correct ledger dir or `mkdir -p` it before "
                f"applying.",
            )

        people_dir = ctx.vault_dir / PEOPLE_SUBDIR

        persons = _walk_person_records(people_dir)
        touches = _walk_linkedin_touch_records(
            iter_touch_notes(ctx.vault_dir),
        )
        name_to_id = _build_name_to_id(persons)

        # Build existing-state indexes from the ledger so we can dedup
        # on re-run. The relevant set is every ``li_dm_intent`` event's
        # ``intent_id`` — production dispatcher emissions (live
        # ``lidm_<ULID>``) AND prior backfill emissions
        # (``bf_lidm_<hash>``). Same intent_id-uniqueness contract as
        # every other per-channel two-phase event type.
        existing_li_dm_intents: set[str] = set()
        for e in iter_events(ledger_dir):
            if e.get("type") == "li_dm_intent":
                iid = e.get("intent_id")
                if iid:
                    existing_li_dm_intents.add(iid)

        counts = _DMBackfillCounts()
        emitted_intents_this_run: set[str] = set()

        # Walk LinkedIn touches and emit pairs for DM-classified
        # touches. Invite-classified touches are skipped (ledger/0003
        # already picked them up). Email touches were never walked
        # (the channel filter in _walk_linkedin_touch_records excluded
        # them).
        for t in touches:
            if not t.person_link_name:
                counts.touches_without_person_match.append(str(t.path))
                continue
            pid = name_to_id.get(t.person_link_name.strip().lower())
            if not pid:
                counts.touches_without_person_match.append(str(t.path))
                continue
            action = _classify_linkedin_action(t.path, t.linkedin_action)
            if action != LINKEDIN_ACTION_DM:
                # Invite (or anything not DM) → skip; ledger/0003
                # walked invite touches.
                counts.touches_skipped_not_dm.append(str(t.path))
                continue

            send_ts = t.sent_at_ts or t.date_ts
            intent_id = _synth_intent_id(
                pid, send_ts, action, touch_stem=t.path.stem,
            )
            if (intent_id in existing_li_dm_intents
                    or intent_id in emitted_intents_this_run):
                counts.linkedin_dm_pairs_skipped += 1
                continue

            intent_evt = {
                "type": "li_dm_intent",
                "person_id": pid,
                "intent_id": intent_id,
                # D33 invariant — every two-phase event carries channel.
                "channel": LINKEDIN_CHANNEL,
                "touch_note": str(t.path),
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            confirm_evt = {
                "type": "li_dm_confirmed",
                "person_id": pid,
                "intent_id": intent_id,
                # D33 invariant — denormalize from the paired intent
                # so the cross-channel rule (ADR-0003) can discriminate.
                # Same discipline as ledger/0003's confirmed-event
                # channel stamping (the Pillar C Week 1 fix that
                # closed the latent ledger/0002 gap).
                "channel": LINKEDIN_CHANNEL,
                # Traceability — mirror the intent event's touch_note
                # so queries on li_dm_confirmed can find the source
                # touch without a join through intent_id. Same shape
                # as ledger/0003's confirmed-event stamping (per
                # Week 2 per-week review P2-4).
                "touch_note": str(t.path),
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, intent_evt)
                append_event_atomic(ledger_dir, confirm_evt)
            emitted_intents_this_run.add(intent_id)
            counts.linkedin_dm_pairs_emitted += 1

        verb = "would emit" if ctx.dry_run else "emitted"
        ctx.logger.info(
            "%s: %s %d LinkedIn DM pair(s); "
            "skipped %d already-present / %d non-DM; "
            "%d touch(es) without person match",
            self.id, verb,
            counts.linkedin_dm_pairs_emitted,
            counts.linkedin_dm_pairs_skipped,
            len(counts.touches_skipped_not_dm),
            len(counts.touches_without_person_match),
        )

        affected = counts.linkedin_dm_pairs_emitted

        notes_msg = (
            f"{verb} {counts.linkedin_dm_pairs_emitted} LinkedIn DM "
            f"pair(s); {counts.linkedin_dm_pairs_skipped} already "
            f"present; {len(counts.touches_skipped_not_dm)} non-DM "
            f"(handled by ledger/0003_baseline_li_invite_history); "
            f"{len(counts.touches_without_person_match)} touch(es) "
            f"without person match"
        )

        # Per ADR-0010 D17 + ADR-0014 D35: emit migration_event on
        # EVERY apply (audit-trail continuity even on no-op), with the
        # ``channel="linkedin"`` kwarg so Pillar G observability can
        # query per-channel without text-matching against migration_id.
        # Dry-run skips emission per ADR-0010 D17 (a dry run mutates
        # nothing).
        if not ctx.dry_run:
            emit_migration_event(
                ledger_dir,
                migration_id=self.id,
                affected_count=affected,
                runner_version=RUNNER_VERSION,
                category=self.category.value,
                channel=LINKEDIN_CHANNEL,
                notes=notes_msg,
                linkedin_dm_pairs_emitted=counts.linkedin_dm_pairs_emitted,
                linkedin_dm_pairs_skipped=counts.linkedin_dm_pairs_skipped,
                touches_without_person_match=len(
                    counts.touches_without_person_match,
                ),
                touches_skipped_not_dm=len(
                    counts.touches_skipped_not_dm,
                ),
            )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=notes_msg,
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Refuse — ledger is append-only.

        Raises ``NotImplementedError``; the runner translates this
        into ``MigrationNotReversibleError``. Per ADR-0010 D14 every
        ledger migration is ``is_reversible=False`` and ``downgrade``
        raises here; the runner refuses ``rollback`` BEFORE invoking
        ``downgrade`` (it checks ``is_reversible`` first), so this
        body is only reached if a caller bypasses the runner.
        """
        raise NotImplementedError(
            f"ledger migration {self.id!r} is structurally "
            f"irreversible (append-only ledger; see ADR-0010 D14). "
            f"The runner refuses rollback with "
            f"MigrationNotReversibleError. To recover from a bad "
            f"apply: restore the ledger directory from backup and "
            f"re-run from a state-file checkpoint, OR follow the "
            f"ADR-0016 §'Existing-operator seed' incantation to mark "
            f"the migration applied without re-applying."
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: BaselineLinkedInDMHistory = BaselineLinkedInDMHistory()


__all__ = [
    "BaselineLinkedInDMHistory",
    "LINKEDIN_ACTION_DM",
    "LINKEDIN_ACTION_FIELD",
    "LINKEDIN_ACTION_INVITE",
    "LINKEDIN_CHANNEL",
    "MIGRATION",
    "MIGRATION_ID",
    "PEOPLE_SUBDIR",
    "RECOVERED_BY_TAG",
    "SYNTHETIC_INTENT_PREFIX",
]
