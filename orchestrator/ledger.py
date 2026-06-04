"""Append-only outreach ledger — the load-bearing source of truth.

Every Person enrollment, pipeline transition, and external action
(Gmail send, LinkedIn invite) is recorded here as a single JSON line.
Vault frontmatter becomes a denormalized view; the ledger is authoritative.

Why append-only:
  - Concurrent writers (dispatcher + manual /send-outreach + reconcile)
    all serialize cleanly via O_APPEND + fcntl advisory lock. No "last
    writer wins" data loss like there is on vault frontmatter.
  - Crash recovery is deterministic: a partial line is detected on read
    and discarded; the next event is appended cleanly.
  - The send-gate's "have we sent to this human?" question is answered
    by ledger query, not by walking vault state — vault drift can't
    fail the gate open.

Storage:
  ~/.outreach-factory/ledger/
    events.jsonl                 → symlink to events-YYYY-MM-DD.jsonl
    events-2026-05-15.jsonl
    events-2026-05-14.jsonl
    ...
  Daily rotation at UTC 00:00 — files are append-only, never modified.

Event schema:
  {"v": 1, "ts": "<ISO 8601 UTC>", "type": "<event_type>", ...fields}

  Required:
    v       (int, schema version; readers tolerate missing fields)
    ts      (ISO 8601 UTC string with 'Z' or '+00:00' offset)
    type    (event type from the catalog below)

  Common:
    person_id        — the Person.id this event concerns
    intent_id        — ULID for two-phase commit on external actions
    channel          — "email" / "linkedin" / "twitter"
    gmail_message_id — Gmail API id, on send_confirmed / reply / bounce
    email            — recipient address (for cross-reference)
    _recovered_by    — "backfill" (emitted by EITHER the standalone
                       orchestrator.backfill_ledger script OR the
                       wrapped ledger/0002_backfill_send_history
                       migration — both produce Phase-5.5-shape
                       enrolled / send_intent / send_confirmed /
                       send_confirmed_orphan events with identical
                       schema; ADR-0013 D24-N + Alternative 12),
                       "reconcile" (emitted by orchestrator.reconcile),
                       or "migration_<id>" (emitted by every OTHER
                       ledger migration — see ADR-0010 D15 + the
                       migration_event audit trail for migration_id
                       cross-reference).

Event types:
  Discovery/enrollment:
    enrolled, enrollment_skipped_exists, enrollment_conflict,
    needs_identity_upgrade, identity_upgraded
  Pipeline:
    state_transition, research_complete, research_failed,
    draft_complete, draft_failed, draft_rejected,
    review_approved, review_rejected
  Send (two-phase) — per-channel families per ADR-0014 D33:
    Email (existing — Phase 5.5):
      send_intent, send_confirmed, send_failed, send_aborted,
      send_run_complete
    LinkedIn invite (Pillar C Week 2 shipped — see ADR-0015):
      li_invite_intent, li_invite_confirmed, li_invite_failed,
      li_invite_aborted
    LinkedIn DM (Pillar C Week 3 shipped — see ADR-0016):
      li_dm_intent, li_dm_confirmed, li_dm_failed, li_dm_aborted
    Twitter DM (Pillar C Week 5 delivers — see ADR-0018 planned):
      tw_dm_intent, tw_dm_confirmed, tw_dm_failed, tw_dm_aborted
    Calendar booking (Pillar C Week 6 shipped — see ADR-0019; no
    _aborted type per ADR-0014 D33 because the abort case is "user
    cancelled the booking", a separate event class
    calendar_booking_cancelled handled by Pillar D):
      calendar_booking_intent, calendar_booking_confirmed,
      calendar_booking_failed
    Every two-phase event of any channel MUST carry a top-level
    `channel: <value>` field where value is one of `{email, linkedin,
    twitter, calendar}`. ADR-0003 §Decision "Event-type predicate" +
    ADR-0014 D33 — the cross-channel rule's safety check depends on
    this; an event missing the field is silently invisible to the rule.
  Inbox:
    bounce_detected, reply_received
  Health:
    reconcile_drift, reconcile_healed, cooldown_blocked, dedup_blocked,
    policy_blocked
  Cost (I7 — see ADR-0006):
    cost_incurred — emitted at the SUCCESS path of every external API
      call (Anthropic / Apollo / PDL / Reoon / Gmail send / LinkedIn
      invite). Required fields: source (vendor name), amount_usd
      (float; 0.0 for quota-only sources), units (int; per-source
      natural unit — tokens / credits / sends / invites),
      model_or_endpoint (free-form diagnostic). Optional: person_id
      (attributable cost), run_id (run-level attribution). Failed API
      calls do NOT emit (we don't pay for failures; biasing the budget
      would defeat its purpose).
  Admin:
    manual_override, migration_event, send_confirmed_orphan
    migration_event — per ADR-0010 D17 + ADR-0014 D35: every per-
      channel migration passes channel=<channel_name> as an extra
      kwarg so Pillar G observability can filter by channel without
      text-matching against the free-form migration_id slug.
    send_confirmed_orphan — Person.last_touch set but no matching
      touch note in conversations dir; per ADR-0014 D33 carries no
      channel field (no source-of-truth for which channel the
      operator used). Operator-review surface, not gate-decision.

CLI:
    python ledger.py tail [--type <t>] [-n <count>]
    python ledger.py grep --person <id> | --intent <id> | --gmail-msg <id>
    python ledger.py funnel --since 30d
    python ledger.py healthcheck [--json]
    python ledger.py rebuild-index
    python ledger.py append @event.json
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


SCHEMA_VERSION = 1
DEFAULT_LEDGER_DIR = Path.home() / ".outreach-factory" / "ledger"

# Event types that imply a pipeline stage. Used by derived_stage().
_STAGE_BY_EVENT_TYPE: dict[str, str] = {
    "enrolled": "queued",
    "research_complete": "researched",
    "draft_complete": "drafted",
    "review_approved": "ready",
}

# Two-phase outcome types — per ADR-0014 D33 the email shape (``send_*``)
# generalizes to a per-channel family:
#
#   Email:            send_intent       send_confirmed       send_failed       send_aborted
#   LinkedIn invite:  li_invite_intent  li_invite_confirmed  li_invite_failed  li_invite_aborted
#   LinkedIn DM:      li_dm_intent      li_dm_confirmed      li_dm_failed      li_dm_aborted
#   Twitter DM:       tw_dm_intent      tw_dm_confirmed      tw_dm_failed      tw_dm_aborted
#   Calendar booking: calendar_booking_intent  calendar_booking_confirmed  calendar_booking_failed
#
# Pillar C Week 2 lands `li_invite_*`; subsequent weeks land the rest. The
# indexer needs to recognize every channel's outcome types so the two-phase
# correlation (`_idx_intent_outcome[intent_id] = outcome_event`) works
# uniformly. Each newly-shipped channel appends to this set + to
# ``_INTENT_TYPES`` below; the two-phase shape per channel does not change.
_OUTCOME_TYPES = frozenset({
    # Email (Phase 5.5 — shipped).
    "send_confirmed", "send_failed", "send_aborted",
    # LinkedIn invite (Pillar C Week 2 — shipped).
    "li_invite_confirmed", "li_invite_failed", "li_invite_aborted",
    # LinkedIn DM (Pillar C Week 3 — shipped, see ADR-0016).
    "li_dm_confirmed", "li_dm_failed", "li_dm_aborted",
    # Twitter DM (Pillar C Week 5 — planned, see ADR-0018).
    "tw_dm_confirmed", "tw_dm_failed", "tw_dm_aborted",
    # Calendar booking (Pillar C Week 6 — planned, see ADR-0019; no
    # ``_aborted`` per ADR-0014 D33 — the abort case is "user cancelled
    # the booking", a separate event class).
    "calendar_booking_confirmed", "calendar_booking_failed",
})

# Two-phase intent types — the symmetric counterpart of ``_OUTCOME_TYPES``.
# An ``intent`` event opens a two-phase commit; an ``outcome`` event closes
# it. ``last_send_for`` walks intents that match a given channel and looks
# up each intent's outcome by ``intent_id``; for the index to materialize
# the LinkedIn / Twitter / calendar intents, the indexer must recognize
# them by type. Convention per D33: every intent type ends in ``_intent``.
_INTENT_TYPES = frozenset({
    "send_intent",
    "li_invite_intent",
    "li_dm_intent",
    "tw_dm_intent",
    "calendar_booking_intent",
})

# Confirmed-outcome subset of ``_OUTCOME_TYPES`` — used by ``last_send_for``
# (only confirmed sends gate the next send; failed/aborted mean the send
# didn't reach the human, so retry is allowed and the cooldown rules
# decide whether retry is appropriate). Mirrors the
# ``type.endswith("_confirmed")`` predicate Pillar A's
# ``CrossChannelTouchRule`` uses (per ADR-0003 §Decision "Event-type
# predicate" + ADR-0014 D33).
_CONFIRMED_TYPES = frozenset({
    t for t in _OUTCOME_TYPES if t.endswith("_confirmed")
})


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


class Event:
    """Thin wrapper around an event dict.

    Stored shape is just a JSON object — the wrapper exposes common fields
    as attributes for readability without locking us into a strict schema.
    Unknown fields are preserved through round-trips (forward-compat).
    """

    __slots__ = ("_d",)

    def __init__(self, **fields):
        if "type" not in fields:
            raise ValueError("Event requires 'type'")
        self._d: dict = dict(fields)
        self._d.setdefault("v", SCHEMA_VERSION)

    @property
    def type(self) -> str:
        return self._d["type"]

    @property
    def ts(self) -> str | None:
        return self._d.get("ts")

    @property
    def v(self) -> int:
        return int(self._d.get("v", SCHEMA_VERSION))

    @property
    def person_id(self) -> str | None:
        return self._d.get("person_id")

    @property
    def intent_id(self) -> str | None:
        return self._d.get("intent_id")

    def __getitem__(self, key):
        return self._d[key]

    def __contains__(self, key) -> bool:
        return key in self._d

    def get(self, key, default=None):
        return self._d.get(key, default)

    def to_dict(self) -> dict:
        return dict(self._d)

    def __repr__(self) -> str:
        return f"Event({self._d!r})"

    def __eq__(self, other) -> bool:
        if isinstance(other, Event):
            return self._d == other._d
        if isinstance(other, dict):
            return self._d == other
        return NotImplemented

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        e = cls.__new__(cls)
        e._d = dict(d)
        e._d.setdefault("v", SCHEMA_VERSION)
        if "type" not in e._d:
            raise ValueError("event dict missing 'type'")
        return e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """ISO 8601 UTC with millisecond precision and trailing 'Z'.

    Millisecond precision keeps the symbol comfortably sortable as a string
    (alphabetic compare = chronological compare) while staying readable.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def new_intent_id(prefix: str = "snd_") -> str:
    """ULID-shaped intent id.

    Format: '<prefix><26-char base32>' — sortable by timestamp prefix
    and extremely collision-resistant under concurrent generation. We
    don't pull in `ulid-py` for one function; this is good enough.

    The default ``"snd_"`` prefix matches the email + LinkedIn + Twitter
    dispatcher convention (Phase 5.5 + Pillar C Weeks 2 / 3 / 5). Pillar
    C Week 6 (ADR-0019 D65) introduces ``"cb_"`` for calendar bookings
    so the booking URL (``cal.com/yourhandle/intro?intent_id=cb_<ULID>``) is
    self-evidently a calendar-booking link to operators scanning their
    outbound messages; the webhook handler also short-circuits on the
    prefix when classifying inbound payloads.
    """
    ts_ms = int(time.time() * 1000)
    rand = uuid.uuid4().int & ((1 << 80) - 1)
    # 48-bit timestamp + 80-bit randomness, base32 encoded (Crockford-ish).
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    n = (ts_ms << 80) | rand
    out: list[str] = []
    for _ in range(26):
        out.append(alphabet[n & 31])
        n >>= 5
    return prefix + "".join(reversed(out))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class Ledger:
    """Append-only event log with lazy in-memory indexing.

    Indexes are rebuilt from disk on demand (mtime-checked) so multiple
    processes can write concurrently without coordination — the next
    query sees fresh state.

    Index set:
        _idx_person          person_id  -> [events, chronological]
        _idx_intent_origin   intent_id  -> send_intent event
        _idx_intent_outcome  intent_id  -> send_confirmed|failed|aborted
        _idx_gmail_msg       gmail_message_id -> event
        _idx_email           email_lower -> set[person_id]
    """

    def __init__(self, ledger_dir: Path = DEFAULT_LEDGER_DIR):
        self.dir = Path(ledger_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._symlink = self.dir / "events.jsonl"
        self._indexes_built_at_mtime: float = -1.0
        self._all_events: list[dict] = []
        self._idx_person: dict[str, list[dict]] = {}
        self._idx_intent_origin: dict[str, dict] = {}
        self._idx_intent_outcome: dict[str, dict] = {}
        self._idx_gmail_msg: dict[str, dict] = {}
        self._idx_gmail_thread: dict[str, list[dict]] = {}
        self._idx_email: dict[str, set[str]] = {}
        self._idx_intents_by_person: dict[str, list[dict]] = {}
        # Pillar H Week 9 — post-append observer seam per ADR-0067 D362
        # (W9 extension to ADR-0067 per ADR-0060 D336). Operators register
        # callbacks via :meth:`append_observer`; each callback fires with
        # the SERIALIZED event dict AFTER the fsync + symlink + mtime-
        # cache invalidation. The daemon's per-event-class index
        # invalidation (orchestrator.daemon._install_index_invalidation_observer)
        # is the canonical v1 consumer; Pillar I per-tenant audit-tooling
        # + Pillar J GDPR purge MAY add additional observers. The list is
        # per-Ledger-instance — cross-process appends are NOT visible to
        # another process's observers (per ADR-0060 D335 invariant 1
        # single-tenant per-daemon-process scope).
        self._post_append_observers: list[Callable[[dict], None]] = []

    # -- file management ----------------------------------------------------

    def _current_file(self) -> Path:
        return self.dir / f"events-{_utc_date()}.jsonl"

    def _all_event_files(self) -> list[Path]:
        return sorted(self.dir.glob("events-*.jsonl"))

    def _ensure_symlink(self, target: Path) -> None:
        """Point events.jsonl at the current day's file.

        Atomic via symlink-to-tmp + os.replace so concurrent processes
        never observe a half-built link.
        """
        target_name = target.name
        try:
            if self._symlink.is_symlink():
                try:
                    current = os.readlink(self._symlink)
                except OSError:
                    current = None
                if current == target_name:
                    return
                self._symlink.unlink()
            elif self._symlink.exists():
                # Someone replaced our symlink with a real file. Preserve
                # the data — rename it out of the way rather than clobber.
                bak = self.dir / f"events.jsonl.unexpected-{int(time.time())}"
                self._symlink.rename(bak)
            tmp = self.dir / f".events.jsonl.tmp-{os.getpid()}-{int(time.time()*1e6)}"
            if tmp.exists() or tmp.is_symlink():
                tmp.unlink()
            os.symlink(target_name, tmp)
            os.replace(tmp, self._symlink)
        except OSError as exc:
            print(f"WARNING: ledger symlink update failed: {exc}", file=sys.stderr)

    # -- append --------------------------------------------------------------

    def append_observer(
        self, observer: Callable[[dict], None],
    ) -> None:
        """Pillar H Week 9 — register a post-append observer per ADR-0067
        D362 (W9 extension to ADR-0067 per ADR-0060 D336).

        The observer is invoked with the serialized event dict AFTER each
        successful :meth:`append` (post fsync + symlink update + mtime-
        cache invalidation). Observers fire in registration order; an
        observer raising an exception logs to stderr + does NOT propagate
        (preserves :meth:`append`'s durability contract per Phase 5.5 +
        ADR-0060 D335 invariant 2 — the ledger is durable BEFORE
        observers fire; observer failure does NOT roll back the append).

        Canonical v1 consumer is the daemon's per-event-class index
        invalidation per ADR-0067 D362
        (:func:`orchestrator.daemon._install_index_invalidation_observer`
        at :func:`init_daemon` Step 8.5). Pillar I per-tenant audit-
        tooling + Pillar J GDPR purge MAY add additional observers
        post-W9.

        Args:
            observer: callable accepting the serialized event dict
                (with ts + v defaults filled in). Operators that mutate
                the dict MUST defensive-copy first — the same dict
                instance flows through all observers in sequence.

        Raises:
            TypeError: if ``observer`` is not callable per the
                per-pillar-H raw-primitive refuse-loud-at-boundary
                discipline (Pillar H Week 2 follow-up P2-2 closure
                established the boundary-validation convention for
                ``build_*_payload`` factories; Pillar H Week 9
                follow-up P2-3 closure extends to
                :meth:`append_observer` per the cross-pillar
                refuse-loud-at-boundary discipline). A non-callable
                observer would only surface at first append time as
                a stderr WARNING ``... raised TypeError: '<type>'
                object is not callable``; the boundary refuse-loud
                surfaces operator errors at registration time
                directly.
        """
        if not callable(observer):
            raise TypeError(
                f"Ledger.append_observer: observer must be callable; "
                f"got {type(observer).__name__!r} (value: {observer!r}). "
                f"Per Pillar H Week 9 follow-up P2-3 closure's raw-"
                f"primitive refuse-loud-at-boundary discipline."
            )
        self._post_append_observers.append(observer)

    def append(self, event: Event | dict) -> dict:
        """Atomically append one event. Returns the serialized dict (with
        ts + v defaults filled in).

        Pillar H Week 9 — after the durable fsync + symlink + mtime-
        cache invalidation, invokes any observers registered via
        :meth:`append_observer` per ADR-0067 D362. Observer exceptions
        are logged to stderr but do NOT propagate (preserves the
        durability contract per Phase 5.5 + ADR-0060 D335 invariant 2).
        """
        d = event.to_dict() if isinstance(event, Event) else dict(event)
        if "type" not in d:
            raise ValueError("event missing 'type'")
        d.setdefault("v", SCHEMA_VERSION)
        d.setdefault("ts", _now_iso())

        line = json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded = line.encode("utf-8")
        target = self._current_file()

        # O_APPEND + fcntl.lockf is the standard pattern. On regular files
        # POSIX guarantees O_APPEND writes go to current EOF, and lockf
        # serializes concurrent writers across processes. fsync ensures
        # durability before we ack the append back to the caller.
        fd = os.open(str(target),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX)
            os.write(fd, encoded)
            os.fsync(fd)
            fcntl.lockf(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

        self._ensure_symlink(target)
        # Invalidate cache; next query rebuilds.
        self._indexes_built_at_mtime = -1.0

        # Pillar H Week 9 per ADR-0067 D362 — fire post-append observers
        # AFTER fsync + symlink + mtime invalidation. Observers see the
        # serialized dict (with ts + v defaults filled in); observer
        # exceptions log to stderr but do NOT propagate (preserves the
        # durability contract per Phase 5.5 + ADR-0060 D335 invariant 2 —
        # the ledger is durable BEFORE observers fire; observer failure
        # does NOT roll back the append). Operators registering observers
        # MUST be defensive about side-effecting work (the daemon's
        # index invalidation observer is in-process O(1) per append; a
        # future Pillar I observer doing network I/O SHOULD wrap in a
        # try/except internally to surface its own failures).
        for _observer in self._post_append_observers:
            try:
                _observer(d)
            except Exception as _exc:  # noqa: BLE001 — operator-resilience contract
                print(
                    f"WARNING: ledger post-append observer "
                    f"{_observer!r} raised {type(_exc).__name__}: {_exc}",
                    file=sys.stderr,
                )

        return d

    # -- read + index --------------------------------------------------------

    def _max_event_file_mtime(self) -> float:
        m = 0.0
        for f in self._all_event_files():
            try:
                m = max(m, f.stat().st_mtime)
            except OSError:
                continue
        return m

    def _load_events(self) -> list[dict]:
        """Read every event-*.jsonl, parsing tolerantly.

        Lines that don't parse (truncated tails, future schema oddities)
        are skipped with a stderr warning rather than aborting — a single
        bad line cannot poison the ledger.
        """
        events: list[dict] = []
        for f in self._all_event_files():
            try:
                text = f.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"WARNING: ledger {f.name} unreadable: {exc}",
                      file=sys.stderr)
                continue
            for lineno, line in enumerate(text.split("\n"), 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    print(
                        f"WARNING: ledger {f.name}:{lineno} skipped "
                        f"(unparseable JSON, likely truncated tail)",
                        file=sys.stderr,
                    )
                    continue
                if not isinstance(obj, dict):
                    print(f"WARNING: ledger {f.name}:{lineno} not a JSON "
                          "object; skipped", file=sys.stderr)
                    continue
                if "type" not in obj:
                    print(f"WARNING: ledger {f.name}:{lineno} missing "
                          "'type'; skipped", file=sys.stderr)
                    continue
                events.append(obj)
        # Sort by ts (ISO-8601 strings sort chronologically).
        events.sort(key=lambda e: e.get("ts") or "")
        return events

    def _build_indexes(self, force: bool = False) -> None:
        current_mtime = self._max_event_file_mtime()
        if (not force) and self._indexes_built_at_mtime >= current_mtime \
                and self._all_events:
            return
        events = self._load_events()
        self._idx_person.clear()
        self._idx_intent_origin.clear()
        self._idx_intent_outcome.clear()
        self._idx_gmail_msg.clear()
        self._idx_gmail_thread.clear()
        self._idx_email.clear()
        self._idx_intents_by_person.clear()
        for e in events:
            pid = e.get("person_id")
            if pid:
                self._idx_person.setdefault(pid, []).append(e)
            iid = e.get("intent_id")
            t = e.get("type")
            if iid:
                if t in _INTENT_TYPES:
                    # Per ADR-0014 D33, every channel's intent type lands
                    # in the origin index. Email's ``send_intent`` is
                    # joined by ``li_invite_intent`` / ``li_dm_intent`` /
                    # ``tw_dm_intent`` / ``calendar_booking_intent`` as
                    # each per-channel dispatcher ships. The intent's
                    # ``channel`` field discriminates downstream queries.
                    self._idx_intent_origin[iid] = e
                    if pid:
                        self._idx_intents_by_person.setdefault(pid, []).append(e)
                elif t in _OUTCOME_TYPES:
                    # Chronologically last outcome wins (rare but possible
                    # if a flaky network produces both fail and confirm).
                    self._idx_intent_outcome[iid] = e
            gid = e.get("gmail_message_id")
            if gid:
                self._idx_gmail_msg[gid] = e
            tid = e.get("gmail_thread_id")
            if tid:
                self._idx_gmail_thread.setdefault(tid, []).append(e)
            em = e.get("email")
            if em and pid:
                self._idx_email.setdefault(str(em).lower(), set()).add(pid)
        self._all_events = events
        self._indexes_built_at_mtime = current_mtime

    # -- query ---------------------------------------------------------------

    def query_by_person(
        self,
        person_id: str,
        since: datetime | None = None,
    ) -> list[Event]:
        self._build_indexes()
        events = self._idx_person.get(person_id, [])
        if since is not None:
            cutoff = since.isoformat() if since.tzinfo else \
                since.replace(tzinfo=timezone.utc).isoformat()
            events = [e for e in events if (e.get("ts") or "") >= cutoff]
        return [Event.from_dict(e) for e in events]

    def query_by_intent(self, intent_id: str) -> Event | None:
        """Return the originating send_intent event for this intent_id, or None."""
        self._build_indexes()
        e = self._idx_intent_origin.get(intent_id)
        return Event.from_dict(e) if e else None

    def outcome_for_intent(self, intent_id: str) -> Event | None:
        """Return the send_confirmed|failed|aborted event for this intent."""
        self._build_indexes()
        e = self._idx_intent_outcome.get(intent_id)
        return Event.from_dict(e) if e else None

    def query_by_gmail_message_id(self, gmail_message_id: str) -> Event | None:
        self._build_indexes()
        e = self._idx_gmail_msg.get(gmail_message_id)
        return Event.from_dict(e) if e else None

    def query_by_gmail_thread_id(self, gmail_thread_id: str) -> list[Event]:
        """All events tagged with this Gmail thread id (sends, replies, bounces).

        Returned chronologically. Used by reconcile Pass B to find the
        originating send when an inbound DSN or reply lands on the thread.
        """
        self._build_indexes()
        events = self._idx_gmail_thread.get(gmail_thread_id, [])
        return [Event.from_dict(e) for e in events]

    def query_by_email(self, email: str) -> set[str]:
        """Return the set of person_ids the ledger has associated with this
        email address (used by reconcile to spot drift)."""
        self._build_indexes()
        return set(self._idx_email.get(email.lower(), set()))

    def last_send_for(
        self, person_id: str, channel: str,
    ) -> Event | None:
        """The send gate's hot path.

        Returns the most-recent CONFIRMED outreach for ``(person_id,
        channel)``, or ``None`` if there is none. The confirmed-outcome
        types are per-channel per ADR-0014 D33 — the email
        ``send_confirmed`` shape generalizes to ``li_invite_confirmed`` /
        ``li_dm_confirmed`` / ``tw_dm_confirmed`` /
        ``calendar_booking_confirmed``. ``*_failed`` and ``*_aborted``
        are NOT considered confirmed — they mean the send didn't reach
        the human, so a subsequent send is allowed (the cooldown rules
        engine, not this method, decides whether retry is appropriate).

        The intent's ``channel`` field is the discriminator — Pillar C
        per-channel dispatchers stamp ``channel: <value>`` on every
        two-phase event per the D33 invariant. An intent missing the
        ``channel`` field is silently skipped (mirrors the cross-channel
        rule's safety check in ADR-0003).

        Confirmed-outcome predicate
        ---------------------------
        An outcome event qualifies as "confirmed" when its ``type`` ends
        with ``_confirmed`` AND is in ``_CONFIRMED_TYPES`` (which lists
        every known per-channel confirmed outcome). The membership check
        is defense against a future event type that happens to end
        ``_confirmed`` but isn't a two-phase outcome — ``_CONFIRMED_TYPES``
        is the closed set that bumps when a new channel ships.
        """
        self._build_indexes()
        best: dict | None = None
        for intent in self._idx_intents_by_person.get(person_id, []):
            if intent.get("channel") != channel:
                continue
            outcome = self._idx_intent_outcome.get(intent.get("intent_id"))
            if not outcome or outcome.get("type") not in _CONFIRMED_TYPES:
                continue
            if best is None or (outcome.get("ts") or "") > (best.get("ts") or ""):
                best = outcome
        return Event.from_dict(best) if best else None

    def confirmed_send_count(self, person_id: str, channel: str = "email") -> int:
        """Number of CONFIRMED sends to ``(person_id, channel)`` — the follow-up
        cadence's touch count.

        Counts the per-channel ``*_confirmed`` events (``_CONFIRMED_TYPES`) that
        carry the matching ``channel`` field. The send path reads this BEFORE
        appending a new ``send_intent`` and stamps the result as the send's
        ``followup_step`` (0 for the cold email, 1 for the first follow-up, …),
        so the ledger records which touch each send was.
        ``orchestrator.followup`` derives the same count from ``send_confirmed``
        events directly; the two agree on the email channel by construction.
        """
        self._build_indexes()
        n = 0
        for e in self._idx_person.get(person_id, []):
            if e.get("type") in _CONFIRMED_TYPES and (
                e.get("channel") or "email"
            ) == channel:
                n += 1
        return n

    def open_intents(
        self,
        *,
        since: datetime,
        channel: str | None = None,
        min_age: timedelta = timedelta(0),
    ) -> list[Event]:
        """Intents without an outcome event yet — input to reconcile Pass A.

        `min_age` lets the caller filter out intents that are still in the
        normal send-completion window (typically 5min). Reconcile passes
        timedelta(minutes=5) so we don't race the send loop.
        """
        self._build_indexes()
        cutoff_iso = since.isoformat() if since.tzinfo else \
            since.replace(tzinfo=timezone.utc).isoformat()
        now = datetime.now(timezone.utc)
        out: list[Event] = []
        for iid, intent in self._idx_intent_origin.items():
            ts = intent.get("ts") or ""
            if ts < cutoff_iso:
                continue
            if channel and intent.get("channel") != channel:
                continue
            if iid in self._idx_intent_outcome:
                continue
            # min_age check
            try:
                intent_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if (now - intent_ts) < min_age:
                continue
            out.append(Event.from_dict(intent))
        out.sort(key=lambda e: e.ts or "")
        return out

    def all_events_for_person(self, person_id: str) -> list[Event]:
        return self.query_by_person(person_id)

    def derived_stage(self, person_id: str) -> str | None:
        """Replay events for this person to determine the current stage.

        Stage progression: queued → researched → drafted → ready → sent.
        Later events outrank earlier ones — a `review_rejected` after a
        `review_approved` pushes the stage back to `drafted`. A confirmed
        send anywhere wins outright (terminal).

        Returns None if no stage-bearing events exist for this person.
        """
        self._build_indexes()
        events = self._idx_person.get(person_id, [])
        if not events:
            return None
        stage: str | None = None
        for e in events:  # chronological
            t = e.get("type")
            if t in _STAGE_BY_EVENT_TYPE:
                stage = _STAGE_BY_EVENT_TYPE[t]
            elif t == "state_transition":
                to = e.get("to")
                if to:
                    stage = to
            elif t == "review_rejected":
                stage = "drafted"
            elif t == "draft_rejected":
                stage = "researched"
        # Confirmed sends are terminal.
        for intent in self._idx_intents_by_person.get(person_id, []):
            outcome = self._idx_intent_outcome.get(intent.get("intent_id"))
            if outcome and outcome.get("type") == "send_confirmed":
                return "sent"
        return stage

    # -- diagnostics ---------------------------------------------------------

    def healthcheck(self) -> dict:
        """Validate ledger directory + parse cleanliness.

        Returns a dict describing: file count, total events parsed, lines
        skipped (truncated/unparseable), symlink target validity, and any
        intents with neither outcome that are >24h old (a healing signal).
        """
        files = self._all_event_files()
        total_lines = 0
        bad_lines = 0
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.split("\n"):
                if not line.strip():
                    continue
                total_lines += 1
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict) or "type" not in obj:
                        bad_lines += 1
                except json.JSONDecodeError:
                    bad_lines += 1

        symlink_ok = False
        symlink_target: str | None = None
        if self._symlink.is_symlink():
            try:
                symlink_target = os.readlink(self._symlink)
                expected = f"events-{_utc_date()}.jsonl"
                # Symlink is ok if it points at today's OR yesterday's
                # file (a stale-but-correct link during a write quiet
                # period right after UTC midnight is fine).
                symlink_ok = symlink_target.startswith("events-") and \
                    symlink_target.endswith(".jsonl")
                if not symlink_ok:
                    pass
                # Also surface "is stale" as info, not as a failure.
            except OSError:
                pass

        self._build_indexes(force=True)
        now = datetime.now(timezone.utc)
        old_open: list[str] = []
        for iid, intent in self._idx_intent_origin.items():
            if iid in self._idx_intent_outcome:
                continue
            try:
                ts = datetime.fromisoformat(
                    (intent.get("ts") or "").replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if (now - ts) > timedelta(hours=24):
                old_open.append(iid)

        return {
            "ok": (bad_lines == 0 and symlink_ok),
            "ledger_dir": str(self.dir),
            "file_count": len(files),
            "events_parsed": total_lines - bad_lines,
            "bad_lines": bad_lines,
            "symlink_ok": symlink_ok,
            "symlink_target": symlink_target,
            "open_intents_over_24h": old_open,
            "indexed_persons": len(self._idx_person),
            "indexed_intents": len(self._idx_intent_origin),
        }

    def all_events(self) -> list[Event]:
        self._build_indexes()
        return [Event.from_dict(e) for e in self._all_events]


# ---------------------------------------------------------------------------
# Funnel
# ---------------------------------------------------------------------------


def funnel(ledger: Ledger, *, since: datetime) -> dict:
    """Pipeline counts since a given timestamp.

    The diagnostic operators ask for: "where is my pipeline leaking?"
    Counts events by type within the window, then aggregates funnel
    stages (enrolled → researched → drafted → ready → sent).
    """
    ledger._build_indexes(force=True)
    cutoff_iso = since.isoformat() if since.tzinfo else \
        since.replace(tzinfo=timezone.utc).isoformat()
    by_type: dict[str, int] = {}
    persons_at_stage: dict[str, set[str]] = {}
    sent_persons: set[str] = set()

    for e in ledger._all_events:
        if (e.get("ts") or "") < cutoff_iso:
            continue
        t = e.get("type", "?")
        by_type[t] = by_type.get(t, 0) + 1

    # Stage funnel — count distinct persons who reached each stage in window.
    for pid in ledger._idx_person:
        stage_reached: set[str] = set()
        for e in ledger._idx_person[pid]:
            if (e.get("ts") or "") < cutoff_iso:
                continue
            t = e.get("type")
            if t in _STAGE_BY_EVENT_TYPE:
                stage_reached.add(_STAGE_BY_EVENT_TYPE[t])
            elif t == "state_transition":
                to = e.get("to")
                if to:
                    stage_reached.add(to)
        # Sent — joined via intent → confirmed.
        for intent in ledger._idx_intents_by_person.get(pid, []):
            if (intent.get("ts") or "") < cutoff_iso:
                continue
            outcome = ledger._idx_intent_outcome.get(intent.get("intent_id"))
            if outcome and outcome.get("type") == "send_confirmed":
                stage_reached.add("sent")
                sent_persons.add(pid)
        for s in stage_reached:
            persons_at_stage.setdefault(s, set()).add(pid)

    stages = ("queued", "researched", "drafted", "ready", "sent")
    counts = {s: len(persons_at_stage.get(s, set())) for s in stages}
    return {
        "since": cutoff_iso,
        "by_type": dict(sorted(by_type.items())),
        "persons_reached_stage": counts,
        "sent_count": len(sent_persons),
        "total_events_in_window": sum(by_type.values()),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_SINCE_RE = re.compile(r"^(\d+)([dhm])$")


def _parse_since(text: str) -> datetime:
    """Accept '30d', '6h', '90m', or an ISO date/datetime."""
    m = _SINCE_RE.match(text.strip())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n),
                 "m": timedelta(minutes=n)}[unit]
        return datetime.now(timezone.utc) - delta
    # ISO date/datetime
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"--since: {text!r} not a duration "
                         f"(e.g. 30d) or ISO date: {exc}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ledger_dir_from_args(args) -> Path:
    if getattr(args, "ledger_dir", None):
        return Path(os.path.expanduser(args.ledger_dir)).resolve()
    return DEFAULT_LEDGER_DIR


def _cmd_tail(args) -> None:
    led = Ledger(_ledger_dir_from_args(args))
    events = led.all_events()
    if args.type:
        events = [e for e in events if e.type == args.type]
    if args.person:
        events = [e for e in events if e.person_id == args.person]
    tail = events[-args.n:] if args.n > 0 else events
    if args.json:
        print(json.dumps([e.to_dict() for e in tail], indent=2,
                         ensure_ascii=False))
    else:
        for e in tail:
            d = e.to_dict()
            extras = {k: v for k, v in d.items()
                      if k not in ("v", "ts", "type", "person_id", "intent_id")}
            tail_str = (" " + json.dumps(extras, ensure_ascii=False,
                                         separators=(",", ":"))) if extras else ""
            pid = e.person_id or "-"
            iid = e.intent_id or ""
            print(f"{e.ts}  {e.type:28s}  {pid:30s}  {iid}{tail_str}")


def _cmd_grep(args) -> None:
    led = Ledger(_ledger_dir_from_args(args))
    if args.person:
        events = led.query_by_person(args.person)
    elif args.intent:
        origin = led.query_by_intent(args.intent)
        outcome = led.outcome_for_intent(args.intent)
        events = [e for e in (origin, outcome) if e is not None]
    elif args.gmail_msg:
        e = led.query_by_gmail_message_id(args.gmail_msg)
        events = [e] if e else []
    else:
        raise SystemExit("grep requires --person | --intent | --gmail-msg")
    if args.json:
        print(json.dumps([e.to_dict() for e in events], indent=2,
                         ensure_ascii=False))
    else:
        for e in events:
            print(json.dumps(e.to_dict(), ensure_ascii=False,
                             separators=(",", ":")))


def _cmd_funnel(args) -> None:
    led = Ledger(_ledger_dir_from_args(args))
    since = _parse_since(args.since)
    result = funnel(led, since=since)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    print(f"Funnel since {result['since']}:")
    print(f"  Total events in window: {result['total_events_in_window']}")
    print()
    print("  Stage           | persons reached")
    print("  ----------------+----------------")
    for stage, n in result["persons_reached_stage"].items():
        gate = "  ⏸" if stage == "drafted" else "   "
        term = " ←" if stage == "sent" else ""
        print(f"  {stage:<15s} | {n:>3d}{gate}{term}")
    print()
    print("  Events by type:")
    width = max((len(t) for t in result["by_type"]), default=10)
    for t, n in result["by_type"].items():
        print(f"    {t:<{width}s}  {n:>4d}")


def _cmd_healthcheck(args) -> None:
    led = Ledger(_ledger_dir_from_args(args))
    h = led.healthcheck()
    if args.json:
        print(json.dumps(h, indent=2, ensure_ascii=False))
        return
    tag = "✅" if h["ok"] else "⚠️ "
    print(f"{tag} ledger: {h['ledger_dir']}")
    print(f"   files:                 {h['file_count']}")
    print(f"   events parsed:         {h['events_parsed']}")
    print(f"   bad lines:             {h['bad_lines']}")
    print(f"   symlink ok:            {h['symlink_ok']} → {h['symlink_target']}")
    print(f"   indexed persons:       {h['indexed_persons']}")
    print(f"   indexed intents:       {h['indexed_intents']}")
    if h["open_intents_over_24h"]:
        print(f"   ⚠ open intents >24h:   {len(h['open_intents_over_24h'])}")
        for iid in h["open_intents_over_24h"]:
            print(f"      {iid}")
    sys.exit(0 if h["ok"] else 1)


def _cmd_rebuild_index(args) -> None:
    led = Ledger(_ledger_dir_from_args(args))
    led._build_indexes(force=True)
    print(f"Rebuilt: {len(led._all_events)} events, "
          f"{len(led._idx_person)} persons, "
          f"{len(led._idx_intent_origin)} intents.")


def _cmd_append(args) -> None:
    led = Ledger(_ledger_dir_from_args(args))
    payload = args.event
    if payload.startswith("@"):
        text = Path(payload[1:]).read_text(encoding="utf-8")
    else:
        text = payload
    try:
        d = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"append: invalid JSON: {exc}")
    if not isinstance(d, dict):
        raise SystemExit("append: payload must be a JSON object")
    if "type" not in d:
        raise SystemExit("append: payload must include 'type'")
    out = led.append(d)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"appended {out['type']} at {out['ts']}")


def main() -> None:
    p = argparse.ArgumentParser(description="Outreach ledger CLI")
    p.add_argument("--ledger-dir", default=None,
                   help="Override default ~/.outreach-factory/ledger/")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tail", help="Show recent events")
    t.add_argument("-n", type=int, default=20)
    t.add_argument("--type", default=None)
    t.add_argument("--person", default=None)
    t.add_argument("--json", action="store_true")

    g = sub.add_parser("grep", help="Filter events by id")
    g.add_argument("--person", default=None)
    g.add_argument("--intent", default=None)
    g.add_argument("--gmail-msg", default=None)
    g.add_argument("--json", action="store_true")

    fn = sub.add_parser("funnel", help="Pipeline counts in a time window")
    fn.add_argument("--since", default="30d",
                    help="Duration (e.g. 30d, 6h) or ISO datetime")
    fn.add_argument("--json", action="store_true")

    hc = sub.add_parser("healthcheck", help="Validate ledger directory")
    hc.add_argument("--json", action="store_true")

    sub.add_parser("rebuild-index", help="Force-rebuild in-memory indexes")

    ap = sub.add_parser("append", help="Append one event (admin/migration)")
    ap.add_argument("event", help='JSON string or "@file.json"')
    ap.add_argument("--json", action="store_true")

    args = p.parse_args()
    cmd = {
        "tail": _cmd_tail, "grep": _cmd_grep, "funnel": _cmd_funnel,
        "healthcheck": _cmd_healthcheck, "rebuild-index": _cmd_rebuild_index,
        "append": _cmd_append,
    }[args.cmd]
    cmd(args)


if __name__ == "__main__":
    main()
