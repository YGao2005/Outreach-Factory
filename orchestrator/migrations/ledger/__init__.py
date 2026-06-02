"""Ledger migrations — append-only event-stream rewrites.

The ledger is the single source of truth (I1); migrations here NEVER
rewrite events in place. The valid mutations are:

* Append a superseding event that consumers interpret in preference to
  the original. ``send_confirmed_orphan`` (``_recovered_by:
  reconcile``) is the precedent — a synthetic event that supersedes
  what would otherwise be inferred from the bare intent. Ledger
  migrations follow the same shape: emit a new event that future
  readers know how to merge with the original.
* Append a ``migration_event`` describing the schema bump itself, so
  future runners + replay tools can audit when the schema changed.

In-place rewrites of existing events are forbidden. If you find
yourself wanting one, the correct shape is a superseding event + a
reader that interprets the supersession.

Per-category dispatcher boundary
--------------------------------

Ledger migrations consume :mod:`._ledger_io` for the per-event IO.
The helper module exposes:

* :func:`._ledger_io.iter_events` — walk every
  ``events-YYYY-MM-DD.jsonl`` file in chronological order by ``ts``.
  Parsing-tolerant (skips malformed lines like
  ``orchestrator.ledger.Ledger._load_events`` does).
* :func:`._ledger_io.append_event_atomic` — delegates to
  :meth:`orchestrator.ledger.Ledger.append` so every migration write
  goes through the same ``O_APPEND + fcntl.lockf + fsync`` durability
  path the production send loop uses.
* :func:`._ledger_io.emit_migration_event` — write the
  ``migration_event`` audit-trail event every ledger migration emits
  at the end of ``upgrade`` (per ADR-0010 D17).
* :func:`._ledger_io.latest_intent_outcome` — convenience for the
  "is this two-phase commit still open?" check.
* :func:`._ledger_io.events_by_type` — filter the event stream by
  ``type`` in chronological order.

Reversibility
-------------

Ledger migrations declare ``is_reversible=False`` in practice — the
ledger is append-only at the file level, so "rolling back" would
either require deleting bytes (forbidden) or appending a brand-new
"re-open" event type (unprecedented + couples downstream readers to
migration-specific event shapes). The framework's
``MigrationNotReversibleError`` is the correct refusal surface.
Operators who need to undo a bad apply restore from backup + replay
from a state-file checkpoint.

See ADR-0010 for the full design (helper-module dispatcher shape,
append-only superseding event pattern, ``migration_event`` emission
contract, first concrete migration ``0001_close_orphan_send_intents``).
"""

from __future__ import annotations

from ..types import Migration
from .migration_0001 import MIGRATION as MIGRATION_0001_CLOSE_ORPHANS
from .migration_0002 import MIGRATION as MIGRATION_0002_BACKFILL_SEND_HISTORY
from .migration_0003_baseline_li_invite_history import (
    MIGRATION as MIGRATION_0003_BASELINE_LI_INVITE_HISTORY,
)
from .migration_0004_baseline_li_dm_history import (
    MIGRATION as MIGRATION_0004_BASELINE_LI_DM_HISTORY,
)
from .migration_0005_baseline_tw_dm_history import (
    MIGRATION as MIGRATION_0005_BASELINE_TW_DM_HISTORY,
)
from .migration_0006_baseline_calendar_booking_history import (
    MIGRATION as MIGRATION_0006_BASELINE_CALENDAR_BOOKING_HISTORY,
)
from .migration_0007_backfill_enrolled_source_skill import (
    MIGRATION as MIGRATION_0007_BACKFILL_ENROLLED_SOURCE_SKILL,
)


MIGRATIONS: list[Migration] = [
    MIGRATION_0001_CLOSE_ORPHANS,
    MIGRATION_0002_BACKFILL_SEND_HISTORY,
    MIGRATION_0003_BASELINE_LI_INVITE_HISTORY,
    MIGRATION_0004_BASELINE_LI_DM_HISTORY,
    MIGRATION_0005_BASELINE_TW_DM_HISTORY,
    MIGRATION_0006_BASELINE_CALENDAR_BOOKING_HISTORY,
    MIGRATION_0007_BACKFILL_ENROLLED_SOURCE_SKILL,
]
