"""Ledger migration 0005 — backfill retroactive Twitter DM history.

Pillar C Week 5's per-channel ledger migration. Mirrors
``ledger/0004_baseline_li_dm_history`` in shape but scoped to Twitter
DMs: walks the operator's vault for ``sent: true`` Twitter touch notes
and emits retroactive ``tw_dm_intent`` + ``tw_dm_confirmed`` event pairs
so the post-migration ledger holds the same two-phase shape the
production Twitter DM dispatcher (ADR-0018) emits going forward.

What it does
------------

Reconstructs Twitter DM history from the vault's current state by
emitting retroactive event pairs per matched Twitter touch note. Each
event carries ``_recovered_by: "backfill"`` so downstream readers can
distinguish synthetic backfill from organically-emitted events. Per
ADR-0014 D33 + D35 + ADR-0018 D58:

1. **Per pair** — ``tw_dm_intent`` + ``tw_dm_confirmed`` both stamped
   ``channel: "twitter"`` (D33 invariant — distinct channel value from
   LinkedIn's; the cross-channel rule's ``consider_channels:`` matches
   on this string). ``intent_id`` is deterministic
   (``bf_twdm_<sha256(person_id|date|action|touch_stem)[:16]>``) so
   re-runs are idempotent without ledger duplication.
2. **One audit-trail event** — ``migration_event`` with
   ``channel="twitter"`` per ADR-0014 D35 + diagnostic fields:
   ``twitter_dm_pairs_emitted``, ``twitter_dm_pairs_skipped``,
   ``touches_without_person_match``.

No invite-vs-DM distinction (ADR-0018 D61)
------------------------------------------

Unlike ``ledger/0003`` + ``ledger/0004`` (which split LinkedIn invite vs
DM via the ``_classify_linkedin_action`` heuristic per ADR-0015 D38),
this migration does NOT classify Twitter touches by action. Twitter has
one outreach action (DM); the per-touch ``twitter_action:`` field is
deferred per ADR-0018 D61 (no vault migration ships in Week 5; the
field would be uniformly populated with the same string + add zero
discriminator power). Every ``channel: twitter`` + ``sent: true`` touch
is unconditionally walked + backfilled.

Why ``bf_twdm_`` not ``bf_tw_dm_`` (or ``bf_tw_``)
--------------------------------------------------

The ``_`` between the channel prefix and the action discriminator is
load-bearing — it would parse identically but reads more naturally
without it (``bf_twdm`` ≈ "backfill Twitter DM" reads as one unit;
``bf_tw_dm`` could be misread as "backfill Twitter / DM"). Same
discipline as ``ledger/0004``'s ``bf_lidm_`` choice (per its module
docstring). Even though Twitter has no action-disambiguation need now
(per ADR-0018 D61's deferral), the ``twdm`` discriminator forward-
preserves the structural slot if Pillar F later adds a Twitter
thread-mention action class — the existing ``bf_twdm_`` IDs are then
self-evidently DM-specific. ``bf_tw_`` (no action discriminator) would
force a rename when the second action arrives. The Pillar I CLI operator
filter ``--intent-prefix bf_twdm_`` is a one-token specifier.

Why ``is_reversible=False``
---------------------------

Append-only ledger (ADR-0010 D14). Same posture as ledger/0001 +
ledger/0002 + ledger/0003 + ledger/0004. Recovery path: restore the
ledger directory from backup + manually mark the migration un-applied
via :func:`orchestrator.migrations.state.mark_unapplied`. For operators
who have been using Twitter DMs via the pre-Pillar-C MCP-mediated flow
AND want their historical state preserved as-is (no retroactive
backfill emissions), the ADR-0018 §"Existing-operator seed" subsection
documents a one-time ``mark_applied`` incantation.

Cross-category dependency on vault/0002
----------------------------------------

This migration READS Person notes to find their ``id:`` field
(stamped by vault/0002, same pattern as ledger/0003 + ledger/0004).
Touches without a matched Person ``id`` surface in the
``touches_without_person_match`` diagnostic. Unlike ledger/0004 there
is no per-touch action-discriminator field to read (per ADR-0018 D61);
the migration walks every Twitter touch unconditionally.

ADR-0013 D27 + ADR-0014 D34 document the cross-category ordering
contract (VAULT → LEDGER → POLICY); ``ledger/0005`` slots into the
existing apply order after ``ledger/0004`` without amendment.

Backfill overlap with ledger/0002
---------------------------------

Evan's Twitter DM touch on 2026-04-22 produces TWO event pairs after a
full apply:

1. ``send_intent`` + ``send_confirmed`` from ledger/0002
   (channel-agnostic walker emits a generic pair for every
   ``sent: true`` touch).
2. ``tw_dm_intent`` + ``tw_dm_confirmed`` from this migration
   (per-channel Twitter DM backfill).

The dual representation is by design per ADR-0018 §"Backfill overlap
with ledger/0002" (Pillar C Week 2 established the rationale for the
LinkedIn-invite case + Week 3 for LinkedIn DM; same logic applies to
Twitter DMs). The cross-channel rule's first-match-wins semantics
short-circuit correctly under dual representation — no double-
engagement; both events carry ``channel: twitter`` and the rule fires
once.

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
is unset — same shape as vault migrations + ledger/0002 + ledger/0003
+ ledger/0004.

Refuse-on-missing-ledger
------------------------

Same shape as ledger/0001 + ledger/0002 + ledger/0003 + ledger/0004:
raises ``FileNotFoundError`` if ``ctx.ledger_dir`` does not exist.
Operators with a fresh state dir emit at least one event through the
normal send path before invoking the migration, or ``mkdir -p`` the
directory.

See ADR-0018 for the full Week 5 design (per-channel dispatcher
shape, follow-state-gate ALLOW posture, MCP surface choice, operator-
seed pattern).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..runner import RUNNER_VERSION
from ..types import MigrationCategory, MigrationContext, MigrationResult
from ..vault._vault_io import (
    is_obsidian_conflict_file,
    is_person_note,
    is_touch_note,
    iter_touch_notes,
)
from ._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    iter_events,
)


MIGRATION_ID = "0005_baseline_tw_dm_history"

# Default people sub-dir. Matches ``ledger/0002.PEOPLE_SUBDIR`` for
# consistency — ledger/0005 reads Person notes for ``id:`` lookup the
# same way prior ledger migrations do.
PEOPLE_SUBDIR = "10 People"

# Twitter channel value per ADR-0014 D33 + ADR-0018 D58. Every event
# this migration emits carries ``channel: "twitter"`` — the cross-
# channel rule (ADR-0003) discriminates on this field.
TWITTER_CHANNEL = "twitter"

# Synthetic intent id prefix — ``bf_twdm_`` distinguishes from live
# Twitter DM ULIDs (``twdm_`` per Pillar C Week 5 dispatcher convention
# — though the dispatcher uses :func:`ledger.new_intent_id` which
# returns ``snd_``-prefixed ULIDs; the ``twdm_`` discriminator on
# synthetic IDs is the human-readable per-channel-backfill tag) AND
# from email backfill (``bf_``) AND from LinkedIn invite / DM backfill
# (``bf_li_`` / ``bf_lidm_``). A reader scanning the ledger can
# instantly tell which sends came from each retroactive-reconstruction
# class. See module docstring for the ``bf_twdm_`` vs ``bf_tw_dm_``
# naming choice.
SYNTHETIC_INTENT_PREFIX = "bf_twdm_"

# ``_recovered_by`` value on every event this migration emits. Shares
# the ``"backfill"`` tag with ledger/0002 + ledger/0003 + ledger/0004
# per ADR-0013 Alternative 12 rationale.
RECOVERED_BY_TAG = "backfill"

# Action discriminator — the only Twitter outreach action class today
# is DM. The constant exists for symmetry with ledger/0003 +
# ledger/0004 and as the canonical string the synthetic intent id
# hash incorporates (preserves the structural slot for future Pillar
# F action classes per ADR-0018 D61's deferral rationale).
TWITTER_ACTION_DM = "dm"


# ---------------------------------------------------------------------------
# Helpers — duplicates the frontmatter/date/wikilink parsing from
# ledger/0003 + ledger/0004 because their helpers are LinkedIn-channel-
# specific (the ``_walk_linkedin_touch_records`` walker filters on
# ``channel: linkedin``). Importing those + monkeypatching would couple
# the migrations tightly; the small amount of duplicated logic is the
# cost-correct shape per ADR-0013 D24-N (channel-specific walkers).
# ---------------------------------------------------------------------------


@dataclass
class _PersonRecord:
    """One Person note's identity-lookup state.

    Same shape as ledger/0003's slim ``_PersonRecord`` — name → id
    mapping for touch correlation. We don't emit ``enrolled`` events
    here (ledger/0002 owns that invariant; re-emitting would
    duplicate).
    """
    path: Path
    name: str
    person_id: str | None


@dataclass
class _TwitterTouchRecord:
    """One Twitter touch note's DM-history-relevant state."""
    path: Path
    person_link_name: str | None
    date_ts: str
    sent_at_ts: str | None


@dataclass
class _TwitterBackfillCounts:
    """Per-category emit counts surfaced in MigrationResult.notes.

    Mirrors ledger/0004's ``_DMBackfillCounts`` shape modulo the channel.
    No ``touches_skipped_not_dm`` counter — Twitter has no
    invite-vs-DM ambiguity per ADR-0018 D61, so every walked touch is a
    DM. Wrong-channel filtering happens inside
    :func:`_walk_twitter_touch_records` (every touch the walker yields
    already passed the ``channel: twitter`` check); a wrong-channel
    count would necessarily be zero so we omit it. Same discipline as
    ledger/0003 + ledger/0004 per Week 2 per-week review P2-3.
    """
    twitter_dm_pairs_emitted: int = 0
    twitter_dm_pairs_skipped: int = 0
    touches_without_person_match: list[str] = field(default_factory=list)


def _parse_frontmatter(path: Path) -> dict | None:
    """Read + parse a markdown file's frontmatter dict.

    Returns ``None`` for files without frontmatter or with malformed
    YAML — the caller silently skips. Mirrors ledger/0003 +
    ledger/0004's ``_parse_frontmatter``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end].lstrip("\n"))
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _date_to_iso(value: Any, *, fallback_mtime: float | None = None) -> str:
    """Coerce a frontmatter date value to an ISO 8601 UTC string.

    Mirrors ``ledger/0003._date_to_iso`` (which mirrors
    ``ledger/0002._date_to_iso``). Same fallback chain: explicit value
    → file mtime → ``now()``.
    """
    if value is not None:
        if hasattr(value, "isoformat"):
            try:
                if isinstance(value, datetime):
                    dt = (
                        value if value.tzinfo
                        else value.replace(tzinfo=timezone.utc)
                    )
                else:
                    dt = datetime(
                        value.year, value.month, value.day,
                        tzinfo=timezone.utc,
                    )
                return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            except (TypeError, ValueError):
                pass
        if isinstance(value, str):
            s = value.strip()
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            except ValueError:
                m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
                if m:
                    return f"{m.group(1)}T00:00:00.000Z"
    if fallback_mtime is not None:
        dt = datetime.fromtimestamp(fallback_mtime, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _person_link_to_name(value: Any) -> str | None:
    """Extract bare display name from an Obsidian wikilink ``[[Name]]``.

    Mirrors ``ledger/0003._person_link_to_name``.
    """
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", value.strip())
        return (m.group(1).strip() if m else value.strip()) or None
    return None


def _walk_person_records(people_dir: Path) -> list[_PersonRecord]:
    """Yield one PersonRecord per Person note under ``people_dir``.

    Mirrors ``ledger/0003._walk_person_records`` — slim version that
    only carries the ``name → person_id`` mapping (no
    ``last_touch`` / ``created_ts`` because Week 5 doesn't emit
    ``enrolled`` events; ledger/0002 owns that invariant).
    """
    out: list[_PersonRecord] = []
    if not people_dir.exists():
        return out
    for note in sorted(people_dir.rglob("*.md")):
        rel = note.relative_to(people_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if is_obsidian_conflict_file(note.name):
            continue
        fm = _parse_frontmatter(note)
        if not is_person_note(fm):
            continue
        out.append(_PersonRecord(
            path=note.resolve(),
            name=str(fm.get("name") or note.stem).strip(),
            person_id=(str(fm["id"]).strip() if fm.get("id") else None),
        ))
    return out


def _walk_twitter_touch_records(
    conv_dir_iter_touches,
) -> list[_TwitterTouchRecord]:
    """Yield one ``_TwitterTouchRecord`` per Twitter ``sent: true``
    touch note.

    Mirrors ``ledger/0003._walk_linkedin_touch_records`` but scoped to
    Twitter touches. The ``channel: twitter`` predicate is the
    load-bearing filter — every Twitter touch must declare it (per
    ADR-0014 D33's channel-on-every-event invariant extended to vault
    touch frontmatter); touches without it are silently skipped.

    No ``twitter_action:`` field read per ADR-0018 D61's deferral
    (Twitter has no invite-vs-DM ambiguity; every walked touch is a
    DM).

    Accepts a pre-built iterator (rather than re-walking the dir) so
    the caller can substitute a test fake without reaching into
    private file IO. The production caller uses
    :func:`..vault._vault_io.iter_touch_notes`.

    Returns
    -------
    list[_TwitterTouchRecord]:
        One record per matched touch.
    """
    out: list[_TwitterTouchRecord] = []
    for note in conv_dir_iter_touches:
        fm = _parse_frontmatter(note)
        if not is_touch_note(fm):
            continue
        if not bool(fm.get("sent")):
            continue
        if (fm.get("channel") or "").strip().lower() != TWITTER_CHANNEL:
            continue
        try:
            mtime = note.stat().st_mtime
        except OSError:
            mtime = None
        date_ts = _date_to_iso(fm.get("date"), fallback_mtime=mtime)
        sent_at_ts = None
        if fm.get("sent_at"):
            sent_at_ts = _date_to_iso(
                fm.get("sent_at"), fallback_mtime=mtime,
            )
        out.append(_TwitterTouchRecord(
            path=note.resolve(),
            person_link_name=_person_link_to_name(fm.get("person")),
            date_ts=date_ts,
            sent_at_ts=sent_at_ts,
        ))
    return out


def _synth_intent_id(
    person_id: str,
    date_iso: str,
    touch_stem: str | None,
) -> str:
    """Deterministic synthetic intent id for Twitter DM backfill.

    ``bf_twdm_`` prefix distinguishes from live Twitter DM ULIDs
    (which use ``ledger.new_intent_id``'s ``snd_`` prefix by default;
    a future Pillar I CLI may add channel-prefixed IDs) + from email
    backfill (``bf_``) + from LinkedIn invite / DM backfill (``bf_li_``
    / ``bf_lidm_``). The hash incorporates the constant
    ``TWITTER_ACTION_DM`` to preserve the structural slot if Pillar F
    later adds a Twitter thread-mention action — the existing
    ``bf_twdm_<hash>`` IDs remain self-evidently DM-specific.

    The touch_stem discriminator is load-bearing: two real Twitter
    DMs to the same person on the same day (initial + follow-up) are
    distinct sends — without the stem they'd hash-collide. Mirrors
    ledger/0004's ``_synth_intent_id``.
    """
    parts = [person_id, date_iso[:10], TWITTER_ACTION_DM]
    if touch_stem:
        parts.append(touch_stem)
    payload = "|".join(parts).encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()[:16]
    return f"{SYNTHETIC_INTENT_PREFIX}{h}"


def _build_name_to_id(persons: list[_PersonRecord]) -> dict[str, str]:
    """Map display-name (case-insensitive) → person_id.

    Mirrors ``ledger/0003._build_name_to_id``.
    """
    out: dict[str, str] = {}
    for p in persons:
        if not p.person_id:
            continue
        out.setdefault(p.name.strip().lower(), p.person_id)
        out.setdefault(p.path.stem.strip().lower(), p.person_id)
    return out


@dataclass
class BaselineTwitterDMHistory:
    """Emit retroactive ``tw_dm_intent`` + ``tw_dm_confirmed`` pairs.

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
        "Backfill retroactive tw_dm_intent + tw_dm_confirmed event "
        "pairs from Twitter DM touch notes "
        "(Pillar C Week 5 — third per-channel ledger migration)"
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Emit retroactive Twitter DM pairs + migration_event.

        Walks ``<ctx.vault_dir>/40 Conversations/`` for ``sent: true``
        Twitter touch notes; emits retroactive ``tw_dm_intent`` +
        ``tw_dm_confirmed`` pairs for every walked touch (no
        action-discriminator filter per ADR-0018 D61); ends with one
        ``migration_event`` carrying ``channel="twitter"`` per
        ADR-0014 D35.

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
                f"(the backfill reads Twitter touch notes to "
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
        touches = _walk_twitter_touch_records(
            iter_touch_notes(ctx.vault_dir),
        )
        name_to_id = _build_name_to_id(persons)

        # Build existing-state indexes from the ledger so we can dedup
        # on re-run. The relevant set is every ``tw_dm_intent`` event's
        # ``intent_id`` — production dispatcher emissions (live
        # ULID-shaped IDs) AND prior backfill emissions
        # (``bf_twdm_<hash>``) AND any pre-Pillar-C synthetic events
        # (the fixture's orphan ``twdm_synthetic_orphan_dm_01``).
        # All three classes share the same intent_id-uniqueness contract.
        existing_tw_dm_intents: set[str] = set()
        for e in iter_events(ledger_dir):
            if e.get("type") == "tw_dm_intent":
                iid = e.get("intent_id")
                if iid:
                    existing_tw_dm_intents.add(iid)

        counts = _TwitterBackfillCounts()
        emitted_intents_this_run: set[str] = set()

        # Walk Twitter touches and emit pairs unconditionally (no
        # invite-vs-DM filter per ADR-0018 D61). Every ``channel:
        # twitter`` + ``sent: true`` touch is a DM.
        for t in touches:
            if not t.person_link_name:
                counts.touches_without_person_match.append(str(t.path))
                continue
            pid = name_to_id.get(t.person_link_name.strip().lower())
            if not pid:
                counts.touches_without_person_match.append(str(t.path))
                continue

            send_ts = t.sent_at_ts or t.date_ts
            intent_id = _synth_intent_id(
                pid, send_ts, touch_stem=t.path.stem,
            )
            if (intent_id in existing_tw_dm_intents
                    or intent_id in emitted_intents_this_run):
                counts.twitter_dm_pairs_skipped += 1
                continue

            intent_evt = {
                "type": "tw_dm_intent",
                "person_id": pid,
                "intent_id": intent_id,
                # D33 invariant — every two-phase event carries channel.
                "channel": TWITTER_CHANNEL,
                "touch_note": str(t.path),
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            confirm_evt = {
                "type": "tw_dm_confirmed",
                "person_id": pid,
                "intent_id": intent_id,
                # D33 invariant — denormalize from the paired intent so
                # the cross-channel rule (ADR-0003) can discriminate.
                # Same discipline as ledger/0003 + ledger/0004's
                # confirmed-event channel stamping.
                "channel": TWITTER_CHANNEL,
                # Traceability — mirror the intent event's touch_note
                # so queries on tw_dm_confirmed can find the source
                # touch without a join through intent_id. Same shape
                # as ledger/0003 + ledger/0004's confirmed-event
                # stamping (per Week 2 per-week review P2-4).
                "touch_note": str(t.path),
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, intent_evt)
                append_event_atomic(ledger_dir, confirm_evt)
            emitted_intents_this_run.add(intent_id)
            counts.twitter_dm_pairs_emitted += 1

        verb = "would emit" if ctx.dry_run else "emitted"
        ctx.logger.info(
            "%s: %s %d Twitter DM pair(s); "
            "skipped %d already-present; "
            "%d touch(es) without person match",
            self.id, verb,
            counts.twitter_dm_pairs_emitted,
            counts.twitter_dm_pairs_skipped,
            len(counts.touches_without_person_match),
        )

        affected = counts.twitter_dm_pairs_emitted

        notes_msg = (
            f"{verb} {counts.twitter_dm_pairs_emitted} Twitter DM "
            f"pair(s); {counts.twitter_dm_pairs_skipped} already "
            f"present; {len(counts.touches_without_person_match)} "
            f"touch(es) without person match"
        )

        # Per ADR-0010 D17 + ADR-0014 D35: emit migration_event on
        # EVERY apply (audit-trail continuity even on no-op), with the
        # ``channel="twitter"`` kwarg so Pillar G observability can
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
                channel=TWITTER_CHANNEL,
                notes=notes_msg,
                twitter_dm_pairs_emitted=counts.twitter_dm_pairs_emitted,
                twitter_dm_pairs_skipped=counts.twitter_dm_pairs_skipped,
                touches_without_person_match=len(
                    counts.touches_without_person_match,
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
            f"ADR-0018 §'Existing-operator seed' incantation to mark "
            f"the migration applied without re-applying."
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: BaselineTwitterDMHistory = BaselineTwitterDMHistory()


__all__ = [
    "BaselineTwitterDMHistory",
    "MIGRATION",
    "MIGRATION_ID",
    "PEOPLE_SUBDIR",
    "RECOVERED_BY_TAG",
    "SYNTHETIC_INTENT_PREFIX",
    "TWITTER_ACTION_DM",
    "TWITTER_CHANNEL",
]
