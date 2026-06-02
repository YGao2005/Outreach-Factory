"""Per-event IO surface for ledger migrations.

The ledger is the single source of truth (I1); ledger migrations
NEVER rewrite events in place. The valid mutations are:

* Append a superseding event that consumers interpret in preference
  to the original (precedent: ``send_confirmed_orphan`` with
  ``_recovered_by: reconcile`` emitted by ``orchestrator.reconcile``).
* Append a ``migration_event`` describing the schema bump itself,
  so future runners + replay tools (Pillar B Week 5–6 synthetic
  replay; Pillar G observability) can audit when the schema changed.

This module exposes:

* :func:`iter_events` — walk every ``events-YYYY-MM-DD.jsonl`` file
  in the ledger dir, yield dicts in chronological order by ``ts``,
  skip malformed lines. Parsing-tolerant — matches
  ``orchestrator.ledger.Ledger._load_events`` so a corrupt tail line
  doesn't poison the migration.
* :func:`append_event_atomic` — delegate to ``Ledger.append`` so
  every migration write goes through the same ``O_APPEND +
  fcntl.lockf + fsync`` path the production send loop uses. The
  durability bar is shared.
* :func:`emit_migration_event` — write the ``migration_event``
  audit-trail event every ledger migration emits at the end of
  ``upgrade``. Standardizes the shape so downstream readers (Pillar
  G OTel, Pillar J compliance) can query by type.
* :func:`latest_intent_outcome` — return the latest outcome
  (``send_confirmed | send_failed | send_aborted``) for an
  ``intent_id``, or ``None`` if the intent has no outcome yet.
  Matches ``Ledger._idx_intent_outcome`` semantics (chronological
  last outcome wins).
* :func:`events_by_type` — filter the event stream by type, in
  chronological order.

The atomicity model is append-only at the file level:

* Each :func:`append_event_atomic` call is a single line write
  serialized across processes by ``fcntl.lockf(LOCK_EX)``.
* A migration's :meth:`Migration.upgrade` may append N events
  during its run. If ``upgrade`` raises mid-batch, the events
  appended before the raise are durably on disk; the framework
  state file does NOT mark the migration applied (per ADR-0009
  D4 atomicity contract); re-running ``apply`` re-invokes
  ``upgrade`` from scratch. The migration is responsible for
  being idempotent across that retry (see ADR-0010 D15 for the
  first migration's idempotence design).

See ADR-0010 for the ledger-migration-specific design.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterator

from orchestrator.ledger import Ledger


# Outcome types for the two-phase-commit shape (per I2 in PILLAR-PLAN §1).
# Matches ``orchestrator.ledger._OUTCOME_TYPES`` exactly — we re-declare
# here rather than import the private constant from ``ledger.py`` so the
# migration surface owns this contract independently. If the canonical
# set ever grows (a fourth outcome type would be a Pillar D / E concern),
# both files bump together.
_OUTCOME_TYPES: frozenset[str] = frozenset({
    "send_confirmed", "send_failed", "send_aborted",
})

# Event-file naming pattern. Every per-day rotation file from
# ``orchestrator.ledger`` is ``events-YYYY-MM-DD.jsonl``; this glob
# excludes the ``events.jsonl`` symlink (which doesn't have a date)
# + any operator-introduced stray files (``events.jsonl.lock``,
# ``README.md``, etc.).
_EVENT_FILE_GLOB = "events-*.jsonl"


def iter_events(ledger_dir: Path) -> Iterator[dict]:
    """Yield every event in the ledger in chronological order by ``ts``.

    Walks every ``<ledger_dir>/events-YYYY-MM-DD.jsonl`` file, parses
    each line as JSON, sorts the global set by ``ts``, and yields the
    result one event at a time. The iterator materializes the full set
    in memory before yielding the first event (the global sort needs
    every event); for ledger sizes <100k events this is comfortably
    fast and the predictable order is more valuable than a streaming
    iterator.

    Parsing tolerance — matches ``orchestrator.ledger.Ledger._load_events``:

    * Blank lines are skipped.
    * Lines that don't parse as JSON are skipped with a stderr warning
      (a truncated tail is the typical case — fcntl serialization
      prevents torn writes mid-line, but a crash mid-write would still
      leave a partial line that the next reader sees once).
    * Lines that parse but aren't JSON objects (arrays, strings) are
      skipped.
    * Objects without a ``type`` field are skipped (per the schema —
      every valid event has a type).

    Returns an empty iterator if the ledger dir does not exist —
    matches the migration's contract of "a fresh state directory with
    no ledger yet is a legitimate zero-event state, not a failure."

    Parameters
    ----------
    ledger_dir:
        Path to a directory containing ``events-*.jsonl`` files. May
        not exist yet (returns empty); may be empty (returns empty);
        may contain unrelated files (they're skipped by the glob).

    Yields
    ------
    dict:
        Raw event dicts (NOT ``Event`` instances — migrations operate
        on the underlying shape; wrapping in ``Event`` would couple
        the migration surface to the production ``Ledger`` class).
    """
    ledger_dir = Path(ledger_dir)
    if not ledger_dir.exists():
        return
    events: list[dict] = []
    for f in sorted(ledger_dir.glob(_EVENT_FILE_GLOB)):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"WARNING: ledger {f.name} unreadable: {exc}",
                file=sys.stderr,
            )
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
                print(
                    f"WARNING: ledger {f.name}:{lineno} not a JSON "
                    "object; skipped",
                    file=sys.stderr,
                )
                continue
            if "type" not in obj:
                print(
                    f"WARNING: ledger {f.name}:{lineno} missing "
                    "'type'; skipped",
                    file=sys.stderr,
                )
                continue
            events.append(obj)
    events.sort(key=lambda e: e.get("ts") or "")
    yield from events


def append_event_atomic(ledger_dir: Path, event: dict) -> dict:
    """Append one event to the ledger via the durable production path.

    Delegates to :meth:`orchestrator.ledger.Ledger.append` — that
    method opens the current day's ``events-YYYY-MM-DD.jsonl`` with
    ``O_APPEND | O_CREAT``, acquires ``fcntl.lockf(LOCK_EX)``, writes
    the JSON line, fsyncs, and releases the lock. Every concurrent
    writer (dispatcher, manual /send-outreach, reconcile, this
    migration helper) serializes at the same lock.

    The atomicity contract:

    * One ``append_event_atomic`` call = one line on disk, atomically.
      A crash between ``write`` and ``fsync`` leaves the line either
      fully present (if the kernel flushed) or absent (if it didn't);
      the partial-line case is impossible because ``write`` of a
      single line under ``O_APPEND + LOCK_EX`` is atomic on POSIX.
    * If a migration's ``upgrade`` raises after appending K of N
      events, those K events are durably on disk; the runner's state
      file does NOT mark the migration applied; re-running ``apply``
      re-invokes ``upgrade`` from scratch. Idempotence is the
      migration's responsibility (see ADR-0010 D15).

    The helper auto-fills ``ts`` and ``v`` defaults if absent (same
    as ``Ledger.append``) but preserves explicit values — backfill
    migrations that pin historical timestamps pass ``ts`` explicitly.

    Parameters
    ----------
    ledger_dir:
        Where to write. Created on demand (``Ledger.__init__``
        mkdirs).
    event:
        Event dict. MUST include ``type``; ``ts`` and ``v`` are
        filled in if absent. All other fields pass through.

    Returns
    -------
    dict:
        The event dict as written to disk, including any
        auto-filled defaults.

    Raises
    ------
    ValueError:
        If ``event`` is missing the ``type`` field — propagated
        from ``Ledger.append``.
    """
    led = Ledger(Path(ledger_dir))
    return led.append(dict(event))


def emit_migration_event(
    ledger_dir: Path,
    *,
    migration_id: str,
    affected_count: int,
    **extra: object,
) -> dict:
    """Append a ``migration_event`` audit-trail event.

    Every ledger migration's ``upgrade`` calls this once at the end
    (per ADR-0010 D17). The standardized shape lets downstream
    readers — Pillar G observability, Pillar J compliance audit,
    the Week 5–6 synthetic replay vehicle — query "when did the
    schema evolve?" by filtering for ``type: "migration_event"``.

    Mandatory fields on the emitted event:

    * ``type``: ``"migration_event"`` (matches the catalog entry at
      ``orchestrator/ledger.py`` line 68).
    * ``migration_id``: the migration's ``id`` (e.g.
      ``"0001_close_orphan_send_intents"``). The ``category``
      prefix is NOT included — the migration_id alone is unique
      within its category and the consumer can read the
      ``category`` field if needed.
    * ``affected_count``: how many primary writes the migration
      performed (e.g. how many ``send_aborted`` events it appended).
      Zero is valid (a no-op re-apply still emits the event for
      audit-trail continuity).

    Any ``**extra`` kwargs are merged into the event as additional
    fields — free-form diagnostic context like ``runner_version``,
    ``category``, ``notes``. Reserved field names ``type``,
    ``migration_id``, ``affected_count``, ``ts``, ``v`` cannot be
    overridden; the helper raises ``ValueError`` if any of them
    appear in ``extra``.

    Parameters
    ----------
    ledger_dir:
        Where to write.
    migration_id:
        The migration's ``id`` attribute.
    affected_count:
        How many writes the migration performed in this apply.
    **extra:
        Additional diagnostic fields. Cannot include reserved names.

    Returns
    -------
    dict:
        The emitted event dict with ``ts`` and ``v`` filled in.

    Raises
    ------
    ValueError:
        If ``extra`` includes any of the reserved field names.
    """
    reserved = {"type", "migration_id", "affected_count", "ts", "v"}
    overlap = reserved & set(extra)
    if overlap:
        raise ValueError(
            f"emit_migration_event: extra fields {sorted(overlap)!r} "
            f"collide with reserved migration_event field names. "
            f"Pass them as explicit kwargs (migration_id=..., "
            f"affected_count=...) or rename them.",
        )
    event: dict = {
        "type": "migration_event",
        "migration_id": migration_id,
        "affected_count": int(affected_count),
    }
    event.update(extra)
    return append_event_atomic(ledger_dir, event)


def latest_intent_outcome(
    ledger_dir: Path,
    intent_id: str,
) -> dict | None:
    """Return the latest outcome event for an ``intent_id``, or ``None``.

    Searches every ``send_confirmed | send_failed | send_aborted``
    event in the ledger; among those matching the ``intent_id``,
    returns the chronologically-latest by ``ts``. Returns ``None``
    if no outcome event exists.

    Matches ``orchestrator.ledger.Ledger._idx_intent_outcome``
    semantics — chronological last outcome wins. This handles the
    rare flaky-network case where both ``send_failed`` and
    ``send_confirmed`` were written for the same intent.

    The "is this intent still open?" check used by the first ledger
    migration (``CloseOrphanSendIntents``) is implemented as
    ``latest_intent_outcome(...) is None``.

    Parameters
    ----------
    ledger_dir:
        Where to read.
    intent_id:
        The intent id to look up.

    Returns
    -------
    dict or None:
        The latest outcome event dict, or ``None`` if no outcome
        exists for this intent.
    """
    best: dict | None = None
    best_ts: str = ""
    for e in iter_events(ledger_dir):
        if e.get("intent_id") != intent_id:
            continue
        if e.get("type") not in _OUTCOME_TYPES:
            continue
        ts = e.get("ts") or ""
        if best is None or ts > best_ts:
            best = e
            best_ts = ts
    return best


def events_by_type(
    ledger_dir: Path,
    type_name: str,
) -> Iterator[dict]:
    """Yield every event of the given type, in chronological order.

    Convenience filter — :func:`iter_events` already returns
    chronological; this just filters by ``type``. Useful for
    migrations that need to walk one event class (e.g. every
    ``send_intent`` to find the orphans, or every prior
    ``migration_event`` to detect "has this migration already
    been recorded as run?").

    Parameters
    ----------
    ledger_dir:
        Where to read.
    type_name:
        Event type to filter on (e.g. ``"send_intent"``,
        ``"migration_event"``).

    Yields
    ------
    dict:
        Matching event dicts in chronological order by ``ts``.
    """
    for e in iter_events(ledger_dir):
        if e.get("type") == type_name:
            yield e
