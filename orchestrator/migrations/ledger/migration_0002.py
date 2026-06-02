"""Ledger migration 0002 — backfill retroactive send-history events.

Pillar B Week 5: wraps the Phase 5.5 Week 2 backfill
(``backfill_ledger.py``) as a ``Migration`` so the same retroactive
reconstruction logic can be replayed against synthetic fixtures via
the migration framework. The wrapper is the integration vehicle that
the Pillar B exit criterion (PILLAR-PLAN §2) names: *"the Phase 5.5
backfills replayed cleanly through the migration runner against a
fresh synthetic vault."*

What it does
------------

Reconstructs the ledger from the vault's current state by emitting
three classes of synthetic events, each carrying
``_recovered_by: "backfill"`` so downstream readers can distinguish
them from organically-emitted events:

1. ``enrolled`` — one per Person note with an ``id:``. ``ts`` is the
   ``created:`` frontmatter date (or file mtime fallback).
2. ``send_intent`` + ``send_confirmed`` pairs — one per touch note
   under ``<vault_dir>/40 Conversations/`` declaring ``sent: true``.
   ``intent_id`` is deterministic
   (``bf_<sha256(person_id|date|channel|touch_stem)[:16]>``) so re-runs
   are idempotent.
3. ``send_confirmed_orphan`` — one per Person whose ``last_touch:``
   set has no matching touch note. Surfaces for manual review.

After processing, emits one ``migration_event`` per ADR-0010 D17
regardless of work done (audit-trail continuity even on no-op).

Why ``is_reversible=False``
---------------------------

Append-only ledger (ADR-0010 D14). Rolling back would require either
deleting bytes (forbidden) or inventing a "re-open" event type
(unprecedented + couples downstream readers to migration-specific
shapes). Operators recovering from a bad apply restore the ledger
directory from backup + manually mark the migration un-applied via
:func:`orchestrator.migrations.state.mark_unapplied`.

Cross-category dependency on vault/0002
---------------------------------------

This migration READS Person notes to find their ``id:`` field. The
``id:`` is stamped by vault/0002 (``BackfillIdentityLineage``). If
this migration runs BEFORE vault/0002, Person notes lack ``id:``,
and ``enrolled`` events are emitted only for Person notes that
happen to already have ``id`` set (e.g. operators who ran the Phase
5.5 backfill script before the migration framework existed).

ADR-0013 D27 documents the cross-category dependency + reorders the
runner's default cross-category apply order to VAULT → LEDGER →
POLICY so a no-args ``apply()`` invocation walks the dependency in
the right direction.

Per-event atomicity
-------------------

Each append goes through :func:`._ledger_io.append_event_atomic`,
which delegates to :meth:`orchestrator.ledger.Ledger.append` — the
``O_APPEND + fcntl.lockf + fsync`` durability path every concurrent
writer in the system shares. A crash mid-batch leaves emitted events
durably on disk; the runner's state-file pointer does NOT advance
(ADR-0009 D4); re-running ``apply`` re-invokes ``upgrade`` from
scratch and the per-event idempotence checks (existing enrolled set,
existing intent_id set, existing orphan set) skip already-emitted
events.

Refuse-on-missing-vault
-----------------------

The migration requires ``ctx.vault_dir is not None`` (because it
reads Person notes + touch notes from the vault). Raises
``ValueError`` if vault_dir is unset — same shape as vault
migrations.

Refuse-on-missing-ledger
------------------------

Same shape as ledger/0001: raises ``FileNotFoundError`` if
``ctx.ledger_dir`` does not exist. Operators with a fresh state dir
emit at least one event through the normal send path before
invoking the migration, or ``mkdir -p`` the directory.

See ADR-0013 for the synthetic-replay vehicle design.
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
)
from ._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    iter_events,
)


MIGRATION_ID = "0002_backfill_send_history"

# Default vault subdirs. Mirror the convention `_vault_io.iter_person_notes`
# uses (``10 People``) AND backfill_ledger's defaults (``40 Conversations``).
# Operators with renamed subdirs configure via `vault.people_dir` /
# `vault.conversations_dir` in `~/.outreach-factory/config.yml`; future
# work that surfaces those config knobs to the migration framework can
# parameterize this migration (Pillar I OSS hardening).
PEOPLE_SUBDIR = "10 People"
CONVERSATIONS_SUBDIR = "40 Conversations"

# Synthetic intent id prefix — ``bf_`` distinguishes from live ``snd_``
# ULIDs so a reader can instantly tell which sends came from retroactive
# reconstruction. Matches backfill_ledger.synth_intent_id.
SYNTHETIC_INTENT_PREFIX = "bf_"

# `_recovered_by` value on every event this migration emits. Matches
# the Phase 5.5 script convention; the literal string `"backfill"`
# stays load-bearing for downstream readers that filter on it.
RECOVERED_BY_TAG = "backfill"


# ---------------------------------------------------------------------------
# Helpers — inlined from backfill_ledger to keep this module
# self-contained (the production backfill script lives at
# orchestrator/backfill_ledger.py and uses bare-name imports that don't
# resolve cleanly under the migration framework's package-import path).
# Any divergence from the script's logic should be intentional + called
# out in ADR-0013.
# ---------------------------------------------------------------------------


@dataclass
class _PersonRecord:
    """One Person note's send-history-relevant state."""
    path: Path
    name: str
    person_id: str | None
    created_ts: str
    last_touch: str | None


@dataclass
class _TouchRecord:
    """One touch note's send-history-relevant state."""
    path: Path
    person_link_name: str | None
    channel: str
    date_ts: str
    sent_at_ts: str | None


@dataclass
class _BackfillCounts:
    """Per-category emit counts surfaced in MigrationResult.notes."""
    enrolled_emitted: int = 0
    enrolled_skipped: int = 0
    sends_emitted: int = 0
    sends_skipped: int = 0
    orphans_emitted: int = 0
    persons_without_id: list[str] = field(default_factory=list)
    touches_without_person_match: list[str] = field(default_factory=list)


def _parse_frontmatter(path: Path) -> dict | None:
    """Read + parse a markdown file's frontmatter dict.

    Returns ``None`` for files without frontmatter or with malformed
    YAML — the caller silently skips. Mirrors
    backfill_ledger._parse_frontmatter; we duplicate rather than
    import because backfill_ledger uses bare-name imports that don't
    resolve under the migration framework's package-import path.
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

    Accepts datetime / date / 'YYYY-MM-DD' strings; falls back to file
    mtime; final fallback is ``now()``. The fallback is silent (matches
    backfill_ledger._date_to_iso): we don't want to refuse to backfill
    a Person just because their ``created:`` field was edited away.
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

    Mirrors backfill_ledger._person_link_to_name.
    """
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", value.strip())
        return (m.group(1).strip() if m else value.strip()) or None
    return None


def _walk_person_records(people_dir: Path) -> list[_PersonRecord]:
    """Yield one PersonRecord per Person note under ``people_dir``.

    Skips hidden files + Obsidian Sync conflict files; skips notes
    without ``type: person`` frontmatter. The ``type:`` check is
    delegated to :func:`..vault._vault_io.is_person_note` — the
    canonical shared predicate consolidated in Pillar B Week 6's
    holistic-review follow-up. The shared helper is robust to
    non-string ``type:`` values (Week 2 P2-1 + Week 5 P2-2 fix).
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
        try:
            mtime = note.stat().st_mtime
        except OSError:
            mtime = None
        created_ts = _date_to_iso(fm.get("created"), fallback_mtime=mtime)
        out.append(_PersonRecord(
            path=note.resolve(),
            name=str(fm.get("name") or note.stem).strip(),
            person_id=(str(fm["id"]).strip() if fm.get("id") else None),
            created_ts=created_ts,
            last_touch=(
                str(fm.get("last_touch")).strip()
                if fm.get("last_touch") else None
            ),
        ))
    return out


def _walk_touch_records(conv_dir: Path) -> list[_TouchRecord]:
    """Yield one TouchRecord per ``sent: true`` touch note under ``conv_dir``.

    Skips hidden files + Obsidian Sync conflict files; skips notes
    without ``type: touch`` or ``sent: true``. The ``type:`` check is
    delegated to :func:`..vault._vault_io.is_touch_note` — the
    canonical shared predicate consolidated in Pillar B Week 6's
    holistic-review follow-up.
    """
    if not conv_dir.exists():
        return []
    out: list[_TouchRecord] = []
    for note in sorted(conv_dir.rglob("*.md")):
        rel = note.relative_to(conv_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if is_obsidian_conflict_file(note.name):
            continue
        fm = _parse_frontmatter(note)
        if not is_touch_note(fm):
            continue
        if not bool(fm.get("sent")):
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
        channel = (
            str(fm.get("channel") or "email").strip().lower() or "email"
        )
        out.append(_TouchRecord(
            path=note.resolve(),
            person_link_name=_person_link_to_name(fm.get("person")),
            channel=channel,
            date_ts=date_ts,
            sent_at_ts=sent_at_ts,
        ))
    return out


def _synth_intent_id(
    person_id: str,
    date_iso: str,
    channel: str,
    touch_stem: str | None,
) -> str:
    """Deterministic synthetic intent id for backfill.

    ``bf_`` prefix distinguishes from live ``snd_`` ULIDs. The
    touch_stem discriminator is load-bearing: two real touches to the
    same person on the same day via the same channel (initial + retry,
    or reply-thread fragments) are distinct sends — without the stem
    they'd hash-collide. Mirrors backfill_ledger.synth_intent_id.
    """
    parts = [person_id, date_iso[:10], channel]
    if touch_stem:
        parts.append(touch_stem)
    payload = "|".join(parts).encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()[:16]
    return f"{SYNTHETIC_INTENT_PREFIX}{h}"


def _build_name_to_id(persons: list[_PersonRecord]) -> dict[str, str]:
    """Map display-name (case-insensitive) → person_id.

    Indexes both ``name:`` and the filename stem. Skips persons
    without a ``person_id`` set (they'd map to None, which we don't
    want in the dict — touches referencing them surface as
    ``touches_without_person_match`` for operator review).
    Mirrors backfill_ledger._build_name_to_id.
    """
    out: dict[str, str] = {}
    for p in persons:
        if not p.person_id:
            continue
        out.setdefault(p.name.strip().lower(), p.person_id)
        out.setdefault(p.path.stem.strip().lower(), p.person_id)
    return out


@dataclass
class BackfillSendHistory:
    """Emit retroactive enrolled / send-pair / orphan events.

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
        "Backfill retroactive enrolled / send_intent+send_confirmed / "
        "send_confirmed_orphan events from vault state "
        "(Phase 5.5 Week 2 backfill replay)"
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Emit retroactive events + the migration_event audit trail.

        Walks ``<ctx.vault_dir>/10 People/`` for Person notes and
        ``<ctx.vault_dir>/40 Conversations/`` for touch notes;
        emits the three event classes per the module docstring;
        ends with one ``migration_event`` per ADR-0010 D17.

        Returns a ``MigrationResult`` whose ``affected_count`` is the
        total count of primary events emitted (enrolled + send_intent
        pair count + orphan count — the ``migration_event`` itself
        does not count).

        Side effects on a successful apply:

        * N + M + K + 1 events appended to the ledger, where
          ``N = enrolled_emitted``, ``M = 2 * sends_emitted`` (intent
          and confirmed per pair), ``K = orphans_emitted``, and the
          ``+ 1`` is the ``migration_event``.
        * Zero vault writes.
        * Zero policy writes.

        On dry-run (``ctx.dry_run=True``): no on-disk mutation. The
        ``MigrationResult`` carries the same counts as a real apply
        would produce (the iteration is identical; only the
        ``append_event_atomic`` calls are skipped).

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None`` (the backfill needs to
            read Person + touch notes to reconstruct history).
        FileNotFoundError:
            When ``ctx.ledger_dir`` does not exist on disk.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"ledger migration {self.id!r} requires ctx.vault_dir "
                f"(the backfill reads Person + touch notes to "
                f"reconstruct send history); set vault.path in "
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
        conv_dir = ctx.vault_dir / CONVERSATIONS_SUBDIR

        persons = _walk_person_records(people_dir)
        touches = _walk_touch_records(conv_dir)
        name_to_id = _build_name_to_id(persons)

        # Build existing-state indexes from the ledger so we can dedup
        # on re-run. Single pass — `iter_events` materializes the
        # global stream and yields in chronological order.
        existing_enrolled: set[str] = set()
        existing_intents: set[str] = set()
        existing_orphans: set[str] = set()
        for e in iter_events(ledger_dir):
            t = e.get("type")
            if t == "enrolled":
                pid = e.get("person_id")
                if pid:
                    existing_enrolled.add(pid)
            elif t == "send_intent":
                iid = e.get("intent_id")
                if iid:
                    existing_intents.add(iid)
            elif t == "send_confirmed_orphan":
                pid = e.get("person_id")
                if pid:
                    existing_orphans.add(pid)

        counts = _BackfillCounts()

        # Pass 1 — enrolled events (one per Person note with an id).
        for p in persons:
            if not p.person_id:
                counts.persons_without_id.append(str(p.path))
                continue
            if p.person_id in existing_enrolled:
                counts.enrolled_skipped += 1
                continue
            evt = {
                "type": "enrolled",
                "person_id": p.person_id,
                "note_path": str(p.path),
                "candidate_name": p.name,
                "ts": p.created_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, evt)
            # In-run dedup: future passes / future migrations check
            # `existing_enrolled` after our appends. Update in-memory
            # so the local view is current.
            existing_enrolled.add(p.person_id)
            counts.enrolled_emitted += 1

        # Pass 2 — send_intent + send_confirmed pairs per ``sent: true``
        # touch note. matched_touch_persons records which persons have
        # at least one touch we matched, so Pass 3 (orphans) can skip
        # them.
        matched_touch_persons: set[str] = set()
        emitted_intents_this_run: set[str] = set()
        for t in touches:
            if not t.person_link_name:
                counts.touches_without_person_match.append(str(t.path))
                continue
            pid = name_to_id.get(t.person_link_name.strip().lower())
            if not pid:
                counts.touches_without_person_match.append(str(t.path))
                continue
            matched_touch_persons.add(pid)
            send_ts = t.sent_at_ts or t.date_ts
            intent_id = _synth_intent_id(
                pid, send_ts, t.channel, touch_stem=t.path.stem,
            )
            if (intent_id in existing_intents
                    or intent_id in emitted_intents_this_run):
                counts.sends_skipped += 1
                continue
            intent_evt = {
                "type": "send_intent",
                "person_id": pid,
                "intent_id": intent_id,
                "channel": t.channel,
                "touch_note": str(t.path),
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            confirm_evt = {
                "type": "send_confirmed",
                "person_id": pid,
                "intent_id": intent_id,
                # Denormalize channel from the paired intent — production
                # ``send_queued.py:gated_send_one`` stamps channel on both
                # sides of the pair; the backfill must mirror or the
                # cross-channel rule (ADR-0003) cannot discriminate
                # against the backfilled history. ADR-0014 D33 pins this
                # as the load-bearing invariant for Pillar C coherence
                # (without channel, the rule's safety check skips the
                # event silently). ledger/0001 already denormalizes
                # channel onto its emitted ``send_aborted`` events
                # (line 308) — this brings ledger/0002 into line.
                "channel": t.channel,
                "ts": send_ts,
                "_recovered_by": RECOVERED_BY_TAG,
            }
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, intent_evt)
                append_event_atomic(ledger_dir, confirm_evt)
            emitted_intents_this_run.add(intent_id)
            counts.sends_emitted += 1

        # Pass 3 — orphans (Person with last_touch but no matching
        # touch event).
        for p in persons:
            if not p.person_id or not p.last_touch:
                continue
            if p.person_id in matched_touch_persons:
                continue
            if p.person_id in existing_orphans:
                continue
            orphan_ts = _date_to_iso(p.last_touch)
            evt = {
                "type": "send_confirmed_orphan",
                "person_id": p.person_id,
                "note_path": str(p.path),
                # ``send_confirmed_orphan`` carries no channel field —
                # by definition the orphan has no matching touch note,
                # so we have no source of truth for which channel
                # the operator used. The cross-channel rule (ADR-0003
                # §Decision "Event-type predicate") looks only at
                # events ending in ``_confirmed`` (not ``_orphan``),
                # so this absence is structurally invisible to the
                # rule — orphans participate in the operator-review
                # surface, not the gate-decision surface. ADR-0014
                # D33 clarifies the boundary.
                "ts": orphan_ts,
                "reason": (
                    "Person.last_touch set but no matching touch note "
                    "in conversations dir — manual review recommended"
                ),
                "_recovered_by": RECOVERED_BY_TAG,
            }
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, evt)
            existing_orphans.add(p.person_id)
            counts.orphans_emitted += 1

        verb = "would emit" if ctx.dry_run else "emitted"
        ctx.logger.info(
            "%s: %s %d enrolled / %d send-pair(s) / %d orphan(s); "
            "skipped %d enrolled-already / %d intent-already; "
            "%d person(s) without id; %d touch(es) without person match",
            self.id, verb,
            counts.enrolled_emitted, counts.sends_emitted,
            counts.orphans_emitted,
            counts.enrolled_skipped, counts.sends_skipped,
            len(counts.persons_without_id),
            len(counts.touches_without_person_match),
        )

        affected = (
            counts.enrolled_emitted
            + counts.sends_emitted
            + counts.orphans_emitted
        )

        notes_msg = (
            f"{verb} {counts.enrolled_emitted} enrolled "
            f"+ {counts.sends_emitted} send-pair(s) "
            f"+ {counts.orphans_emitted} orphan(s); "
            f"{counts.enrolled_skipped} enrolled already present; "
            f"{counts.sends_skipped} intent_ids already present; "
            f"{len(counts.persons_without_id)} person(s) without "
            f"id (run vault/0002_backfill_identity_lineage first); "
            f"{len(counts.touches_without_person_match)} touch(es) "
            f"without person match"
        )

        # Per ADR-0010 D17: emit migration_event on EVERY apply,
        # including no-op + dry_run-equivalent runs. The dry-run case
        # skips even this emission — a dry run mutates nothing.
        if not ctx.dry_run:
            emit_migration_event(
                ledger_dir,
                migration_id=self.id,
                affected_count=affected,
                runner_version=RUNNER_VERSION,
                category=self.category.value,
                notes=notes_msg,
                enrolled_emitted=counts.enrolled_emitted,
                sends_emitted=counts.sends_emitted,
                orphans_emitted=counts.orphans_emitted,
                persons_without_id=len(counts.persons_without_id),
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
            f"re-run from a state-file checkpoint."
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: BackfillSendHistory = BackfillSendHistory()


__all__ = [
    "BackfillSendHistory",
    "MIGRATION",
    "MIGRATION_ID",
    "PEOPLE_SUBDIR",
    "CONVERSATIONS_SUBDIR",
    "RECOVERED_BY_TAG",
    "SYNTHETIC_INTENT_PREFIX",
]
