"""Ledger migration 0006 — backfill retroactive Calendar booking history.

Pillar C Week 6's per-channel ledger migration. Mirrors
``ledger/0005_baseline_tw_dm_history`` in shape but scoped to calendar
bookings: walks the operator's vault for ``sent: true`` calendar touch
notes and emits retroactive ``calendar_booking_intent`` events so the
post-migration ledger holds the same shape the production Calendar
booking dispatcher (ADR-0019) emits going forward.

ASYMMETRIC pair semantics (the Week 6 structural distinction)
-------------------------------------------------------------

Unlike Weeks 2 / 3 / 5's per-channel backfills (``ledger/0003`` for
LinkedIn invites, ``ledger/0004`` for LinkedIn DMs, ``ledger/0005`` for
Twitter DMs) — which emit BOTH ``_intent`` AND ``_confirmed`` for every
walked touch — this migration emits ``calendar_booking_intent``
UNCONDITIONALLY but ``calendar_booking_confirmed`` ONLY when the touch
note carries a ``calendar_booking_confirmed_at:`` field.

Why the asymmetric semantics:

* Calendar bookings are webhook-driven, not synchronous (ADR-0019 D66).
  At dispatcher send-time the operator generates a booking URL + emits
  ``calendar_booking_intent`` ONLY; the matching ``calendar_booking_confirmed``
  arrives later via the Cal.com webhook handler IF AND ONLY IF the
  recipient actually books a slot.
* A LinkedIn-invite / DM / Twitter-DM ``sent: true`` touch means the
  send happened (the API returned success). A calendar-booking
  ``sent: true`` touch means the operator shared the booking link —
  not that the recipient booked. The "booking confirmed" state is
  orthogonal to the "link shared" state.
* The backfill respects this asymmetry: ``sent: true`` → intent only;
  ``calendar_booking_confirmed_at:`` present → confirmed too.

For pre-Week-6 operators with retroactive booking confirmations the
operator stamps ``calendar_booking_confirmed_at: <ISO>`` on the touch
note BEFORE running the migration; the backfill picks it up + emits
the paired confirmed event. Without that stamp the backfill emits
intent only — which is the correct shape because the orchestrator
genuinely doesn't know whether the recipient booked.

What it does
------------

Reconstructs Calendar booking history from the vault's current state.
Per ADR-0014 D33 + D35 + ADR-0019 D65:

1. **Per touch** — emit ``calendar_booking_intent`` stamped
   ``channel: "calendar"`` (D33 invariant). Optionally emit
   ``calendar_booking_confirmed`` ALSO when the touch carries
   ``calendar_booking_confirmed_at:``. ``intent_id`` is deterministic
   (``bf_cb_<sha256(person_id|date|touch_stem)[:16]>``) so re-runs are
   idempotent without ledger duplication.
2. **One audit-trail event** — ``migration_event`` with
   ``channel="calendar"`` per ADR-0014 D35 + diagnostic fields:
   ``calendar_intents_emitted``, ``calendar_confirmeds_emitted``,
   ``calendar_pairs_skipped``, ``touches_without_person_match``.

NO action-discriminator field (per ADR-0019 D69)
------------------------------------------------

Calendar bookings have one outreach action (share a booking link); no
``calendar_action:`` field is read. Mirrors ledger/0005's
no-Twitter-action-discriminator rationale (ADR-0018 D61): the field
would be uniformly populated + add zero discriminator power. If
Pillar F's quality scoring later needs a calendar-action discriminator
(e.g., a future "calendar group booking" action class), the vault
migration can ship then.

Why ``bf_cb_`` not ``bf_calendar_``
-----------------------------------

The ``cb_`` discriminator is consistent with the dispatcher-runtime
intent-id prefix (``send_queued.py::CALENDAR_BOOKING_INTENT_ID_PREFIX``;
``new_intent_id(prefix="cb_")`` per the Week 6 ledger.py extension).
The ``bf_`` prefix continues to distinguish synthetic backfill IDs
from live dispatcher-emitted IDs across all channels. The Pillar I CLI
operator filter ``--intent-prefix bf_cb_`` is a one-token specifier.

Why ``is_reversible=False``
---------------------------

Append-only ledger (ADR-0010 D14). Same posture as ledger/0001 through
ledger/0005. Recovery path: restore the ledger directory from backup +
manually mark the migration un-applied via
:func:`orchestrator.migrations.state.mark_unapplied`. For operators
who have been managing calendar bookings via a pre-Pillar-C MCP-mediated
or fully-manual flow AND want their historical state preserved as-is
(no retroactive backfill emissions), the ADR-0019 §"Existing-operator
seed" subsection documents a one-time ``mark_applied`` incantation.

Cross-category dependency on vault/0002
----------------------------------------

This migration READS Person notes to find their ``id:`` field (stamped
by vault/0002, same pattern as ledger/0003 through ledger/0005).
Touches without a matched Person ``id`` surface in the
``touches_without_person_match`` diagnostic.

ADR-0013 D27 + ADR-0014 D34 document the cross-category ordering
contract (VAULT → LEDGER → POLICY); ``ledger/0006`` slots into the
existing apply order after ``ledger/0005`` without amendment.

Backfill overlap with ledger/0002
---------------------------------

A ``channel: calendar`` + ``sent: true`` touch produces TWO events
after a full apply:

1. ``send_intent`` + ``send_confirmed`` from ledger/0002 (channel-
   agnostic walker emits a generic pair for every ``sent: true``
   touch).
2. ``calendar_booking_intent`` from THIS migration (asymmetric per-
   channel backfill; no paired ``_confirmed`` unless the touch has the
   ``calendar_booking_confirmed_at:`` field).

The dual representation is by design per ADR-0019 §"Backfill overlap
with ledger/0002". The cross-channel rule's first-match-wins semantics
short-circuit correctly — but note the calendar case differs from
Weeks 2-5: the calendar's per-channel ledger reflects "link shared,
recipient may or may not have booked" while the ledger/0002 generic
pair reflects "operator marked sent". This is correct for the calendar
semantics; downstream consumers (Pillar D win-attribution, Pillar G
funnel observability) consume the per-channel ``calendar_booking_*``
events specifically because they distinguish link-shared vs booking-
confirmed states.

Per-event atomicity
-------------------

Each append goes through :func:`._ledger_io.append_event_atomic` —
same atomicity contract as ledger/0001-0005.

Refuse-on-missing-vault + refuse-on-missing-ledger
--------------------------------------------------

Same shape as ledger/0001-0005: raises ``ValueError`` if vault_dir is
unset; ``FileNotFoundError`` if ledger_dir does not exist.

See ADR-0019 for the full Week 6 design.
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


MIGRATION_ID = "0006_baseline_calendar_booking_history"

# Default people sub-dir. Matches ``ledger/0002 .. 0005``'s PEOPLE_SUBDIR.
PEOPLE_SUBDIR = "10 People"

# Calendar channel value per ADR-0014 D33 + ADR-0019 D65. Every event
# this migration emits carries ``channel: "calendar"``.
CALENDAR_CHANNEL = "calendar"

# Synthetic intent id prefix — ``bf_cb_`` distinguishes from live
# calendar-booking IDs (``cb_<26-char ULID>`` per the Week 6
# dispatcher's ``new_intent_id(prefix="cb_")`` extension) AND from
# email backfill (``bf_``) AND from LinkedIn / Twitter backfill
# (``bf_li_`` / ``bf_lidm_`` / ``bf_twdm_``). A reader scanning the
# ledger can instantly tell which sends came from each retroactive-
# reconstruction class.
SYNTHETIC_INTENT_PREFIX = "bf_cb_"

# ``_recovered_by`` value on every event this migration emits. Shares
# the ``"backfill"`` tag with ledger/0002 through ledger/0005 per
# ADR-0013 Alternative 12 rationale.
RECOVERED_BY_TAG = "backfill"


# ---------------------------------------------------------------------------
# Helpers — duplicates the frontmatter / date / wikilink parsing from
# ledger/0005 because the channel-specific walker (filtering on
# ``channel: calendar``) is small + tightly coupled to the migration's
# purpose. Same discipline as ledger/0003-0005 (channel-specific walkers).
# ---------------------------------------------------------------------------


@dataclass
class _PersonRecord:
    """One Person note's identity-lookup state. Same shape as
    ledger/0005's slim ``_PersonRecord``."""
    path: Path
    name: str
    person_id: str | None


@dataclass
class _CalendarTouchRecord:
    """One Calendar touch note's booking-history-relevant state."""
    path: Path
    person_link_name: str | None
    date_ts: str
    sent_at_ts: str | None
    # When set, the operator stamped a recipient-actually-booked
    # confirmation on the touch note; the backfill emits the paired
    # ``calendar_booking_confirmed`` event. Absent → intent only
    # (the recipient may not have booked).
    confirmed_at_ts: str | None


@dataclass
class _CalendarBackfillCounts:
    """Per-category emit counts surfaced in MigrationResult.notes.

    Per Week 6 per-week review migration P2-2: ``calendar_pairs_skipped``
    counts touches where NOTHING was emitted (both intent + confirmed
    already present, OR intent present + touch has no
    ``calendar_booking_confirmed_at:``). ``calendar_confirmeds_added_on_rerun``
    is the disambiguator: it counts touches where the intent was
    already present BUT a newly-stamped ``calendar_booking_confirmed_at:``
    caused the confirmed event to land on re-run. Without the split,
    Pillar G observability would conflate "operator added a confirmed
    on re-run" with "nothing happened" — both would show
    ``calendar_pairs_skipped == 0`` in the partial-rerun case.
    """
    calendar_intents_emitted: int = 0
    calendar_confirmeds_emitted: int = 0
    calendar_pairs_skipped: int = 0
    calendar_confirmeds_added_on_rerun: int = 0
    touches_without_person_match: list[str] = field(default_factory=list)


def _parse_frontmatter(path: Path) -> dict | None:
    """Read + parse a markdown file's frontmatter dict. Mirrors
    ledger/0005's ``_parse_frontmatter``."""
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
    """Coerce a frontmatter date value to an ISO 8601 UTC string. Mirrors
    ledger/0005."""
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
    """Extract bare display name from ``[[Name]]``. Mirrors ledger/0005."""
    if not value:
        return None
    if isinstance(value, str):
        m = re.match(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", value.strip())
        return (m.group(1).strip() if m else value.strip()) or None
    return None


def _walk_person_records(people_dir: Path) -> list[_PersonRecord]:
    """Yield one PersonRecord per Person note. Mirrors ledger/0005."""
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


def _walk_calendar_touch_records(
    conv_dir_iter_touches,
) -> list[_CalendarTouchRecord]:
    """Yield one ``_CalendarTouchRecord`` per Calendar ``sent: true``
    touch note.

    The ``channel: calendar`` predicate is the load-bearing filter —
    every Calendar touch must declare it (per ADR-0014 D33's channel-
    on-every-event invariant extended to vault touch frontmatter);
    touches without it are silently skipped.

    The ``calendar_booking_confirmed_at:`` field is read OPTIONALLY:
    when present, the migration emits a paired confirmed event; when
    absent, only the intent. Mirrors the asymmetric semantics doc'd in
    the module docstring.
    """
    out: list[_CalendarTouchRecord] = []
    for note in conv_dir_iter_touches:
        fm = _parse_frontmatter(note)
        if not is_touch_note(fm):
            continue
        if not bool(fm.get("sent")):
            continue
        if (fm.get("channel") or "").strip().lower() != CALENDAR_CHANNEL:
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
        confirmed_at_ts = None
        confirmed_raw = fm.get("calendar_booking_confirmed_at")
        if confirmed_raw is not None:
            confirmed_at_ts = _date_to_iso(
                confirmed_raw, fallback_mtime=mtime,
            )
        out.append(_CalendarTouchRecord(
            path=note.resolve(),
            person_link_name=_person_link_to_name(fm.get("person")),
            date_ts=date_ts,
            sent_at_ts=sent_at_ts,
            confirmed_at_ts=confirmed_at_ts,
        ))
    return out


def _synth_intent_id(
    person_id: str,
    date_iso: str,
    touch_stem: str | None,
) -> str:
    """Deterministic synthetic intent id for Calendar booking backfill.

    ``bf_cb_`` prefix distinguishes from live calendar-booking IDs
    (``cb_<26-char ULID>``) + from email backfill (``bf_``) + from
    LinkedIn / Twitter backfill prefixes. The hash discriminates by
    person + date + touch stem so two real bookings to the same person
    on the same day (initial + follow-up) hash distinctly.

    Mirrors ledger/0005's ``_synth_intent_id`` modulo: no action
    constant in the hash, because calendar bookings have one action
    class (share a link). If Pillar F later adds a "calendar group
    booking" action class, extend the hash with an action discriminator
    + ship a renaming migration.
    """
    parts = [person_id, date_iso[:10]]
    if touch_stem:
        parts.append(touch_stem)
    payload = "|".join(parts).encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()[:16]
    return f"{SYNTHETIC_INTENT_PREFIX}{h}"


def _build_name_to_id(persons: list[_PersonRecord]) -> dict[str, str]:
    """Map display-name (case-insensitive) → person_id. Mirrors
    ledger/0005."""
    out: dict[str, str] = {}
    for p in persons:
        if not p.person_id:
            continue
        out.setdefault(p.name.strip().lower(), p.person_id)
        out.setdefault(p.path.stem.strip().lower(), p.person_id)
    return out


@dataclass
class BaselineCalendarBookingHistory:
    """Emit retroactive ``calendar_booking_intent`` (+ optional
    ``calendar_booking_confirmed``) events.

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
        "Backfill retroactive calendar_booking_intent events "
        "(+ optional calendar_booking_confirmed when the touch carries "
        "calendar_booking_confirmed_at) from Calendar touch notes "
        "(Pillar C Week 6 — fourth per-channel ledger migration; "
        "asymmetric pair semantics per ADR-0019)"
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Emit retroactive Calendar booking events + migration_event.

        Walks ``<ctx.vault_dir>/40 Conversations/`` for ``sent: true``
        Calendar touch notes; emits retroactive
        ``calendar_booking_intent`` per walked touch +
        ``calendar_booking_confirmed`` ONLY when the touch carries
        ``calendar_booking_confirmed_at:`` (per ADR-0019 D69's asymmetric
        semantics); ends with one ``migration_event`` carrying
        ``channel="calendar"`` per ADR-0014 D35.

        Returns a ``MigrationResult`` whose ``affected_count`` is the
        total count of primary events emitted
        (``calendar_intents_emitted + calendar_confirmeds_emitted``).

        Raises
        ------
        ValueError:
            When ``ctx.vault_dir`` is ``None``.
        FileNotFoundError:
            When ``ctx.ledger_dir`` does not exist on disk.
        """
        if ctx.vault_dir is None:
            raise ValueError(
                f"ledger migration {self.id!r} requires ctx.vault_dir "
                f"(the backfill reads Calendar touch notes to "
                f"reconstruct booking history); set vault.path in "
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
        touches = _walk_calendar_touch_records(
            iter_touch_notes(ctx.vault_dir),
        )
        name_to_id = _build_name_to_id(persons)

        # Build existing-state indexes from the ledger so we can dedup
        # on re-run. The relevant set is every
        # ``calendar_booking_intent`` event's ``intent_id`` —
        # production dispatcher emissions (live ``cb_<ULID>`` IDs) AND
        # prior backfill emissions (``bf_cb_<hash>``).
        existing_calendar_intents: set[str] = set()
        existing_calendar_confirmeds: set[str] = set()
        for e in iter_events(ledger_dir):
            t = e.get("type")
            if t == "calendar_booking_intent":
                iid = e.get("intent_id")
                if iid:
                    existing_calendar_intents.add(iid)
            elif t == "calendar_booking_confirmed":
                iid = e.get("intent_id")
                if iid:
                    existing_calendar_confirmeds.add(iid)

        counts = _CalendarBackfillCounts()
        emitted_intents_this_run: set[str] = set()
        emitted_confirmeds_this_run: set[str] = set()

        # Walk Calendar touches and emit per asymmetric semantics:
        # ``sent: true`` → intent unconditionally; presence of
        # ``calendar_booking_confirmed_at:`` → paired confirmed too.
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
            already_intent = (
                intent_id in existing_calendar_intents
                or intent_id in emitted_intents_this_run
            )
            already_confirmed = (
                intent_id in existing_calendar_confirmeds
                or intent_id in emitted_confirmeds_this_run
            )

            if already_intent and (
                t.confirmed_at_ts is None or already_confirmed
            ):
                # Nothing to do for this touch — both sides (if needed)
                # already present.
                counts.calendar_pairs_skipped += 1
                continue

            if not already_intent:
                intent_evt = {
                    "type": "calendar_booking_intent",
                    "person_id": pid,
                    "intent_id": intent_id,
                    # D33 invariant — every two-phase event carries channel.
                    "channel": CALENDAR_CHANNEL,
                    "touch_note": str(t.path),
                    "ts": send_ts,
                    "_recovered_by": RECOVERED_BY_TAG,
                }
                if not ctx.dry_run:
                    append_event_atomic(ledger_dir, intent_evt)
                emitted_intents_this_run.add(intent_id)
                counts.calendar_intents_emitted += 1

            if t.confirmed_at_ts is not None and not already_confirmed:
                confirm_evt = {
                    "type": "calendar_booking_confirmed",
                    "person_id": pid,
                    "intent_id": intent_id,
                    # D33 invariant — denormalize from the paired intent
                    # so the cross-channel rule (ADR-0003) can
                    # discriminate.
                    "channel": CALENDAR_CHANNEL,
                    # Traceability — mirror the intent event's touch_note
                    # so queries on calendar_booking_confirmed find the
                    # source touch without a join through intent_id.
                    "touch_note": str(t.path),
                    "ts": t.confirmed_at_ts,
                    "_recovered_by": RECOVERED_BY_TAG,
                }
                if not ctx.dry_run:
                    append_event_atomic(ledger_dir, confirm_evt)
                emitted_confirmeds_this_run.add(intent_id)
                counts.calendar_confirmeds_emitted += 1
                if already_intent:
                    # Partial-rerun shape: the intent was already in the
                    # ledger from a prior apply; this run emits ONLY the
                    # newly-stampable confirmed. Track separately from
                    # the fresh-emit case so Pillar G observability can
                    # chart "operator stamped confirmed_at + re-ran" vs
                    # "first-time apply".
                    counts.calendar_confirmeds_added_on_rerun += 1

        verb = "would emit" if ctx.dry_run else "emitted"
        ctx.logger.info(
            "%s: %s %d calendar_booking_intent + %d "
            "calendar_booking_confirmed event(s); "
            "%d confirmed added on rerun; "
            "skipped %d already-present; "
            "%d touch(es) without person match",
            self.id, verb,
            counts.calendar_intents_emitted,
            counts.calendar_confirmeds_emitted,
            counts.calendar_confirmeds_added_on_rerun,
            counts.calendar_pairs_skipped,
            len(counts.touches_without_person_match),
        )

        affected = (
            counts.calendar_intents_emitted
            + counts.calendar_confirmeds_emitted
        )

        notes_msg = (
            f"{verb} {counts.calendar_intents_emitted} "
            f"calendar_booking_intent + "
            f"{counts.calendar_confirmeds_emitted} "
            f"calendar_booking_confirmed event(s) "
            f"({counts.calendar_confirmeds_added_on_rerun} confirmed "
            f"added on rerun); "
            f"{counts.calendar_pairs_skipped} touches already present; "
            f"{len(counts.touches_without_person_match)} touch(es) "
            f"without person match"
        )

        # Per ADR-0010 D17 + ADR-0014 D35: emit migration_event on every
        # apply (audit-trail continuity even on no-op), with the
        # ``channel="calendar"`` kwarg so Pillar G observability can
        # query per-channel without text-matching against migration_id.
        if not ctx.dry_run:
            emit_migration_event(
                ledger_dir,
                migration_id=self.id,
                affected_count=affected,
                runner_version=RUNNER_VERSION,
                category=self.category.value,
                channel=CALENDAR_CHANNEL,
                notes=notes_msg,
                calendar_intents_emitted=counts.calendar_intents_emitted,
                calendar_confirmeds_emitted=counts.calendar_confirmeds_emitted,
                calendar_confirmeds_added_on_rerun=counts.calendar_confirmeds_added_on_rerun,
                calendar_pairs_skipped=counts.calendar_pairs_skipped,
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
        ledger migration is ``is_reversible=False``.
        """
        raise NotImplementedError(
            f"ledger migration {self.id!r} is structurally "
            f"irreversible (append-only ledger; see ADR-0010 D14). "
            f"The runner refuses rollback with "
            f"MigrationNotReversibleError. To recover from a bad "
            f"apply: restore the ledger directory from backup and "
            f"re-run from a state-file checkpoint, OR follow the "
            f"ADR-0019 §'Existing-operator seed' incantation to mark "
            f"the migration applied without re-applying."
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: BaselineCalendarBookingHistory = BaselineCalendarBookingHistory()


__all__ = [
    "BaselineCalendarBookingHistory",
    "CALENDAR_CHANNEL",
    "MIGRATION",
    "MIGRATION_ID",
    "PEOPLE_SUBDIR",
    "RECOVERED_BY_TAG",
    "SYNTHETIC_INTENT_PREFIX",
]
