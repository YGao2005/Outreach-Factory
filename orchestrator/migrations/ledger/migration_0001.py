"""Ledger migration 0001 — close orphan send intents.

Pillar B Week 3's first real ledger migration. Operationalizes the
ledger-migration shape ADR-0010 specifies: append-only superseding
events with ``_recovered_by`` tagging + ``migration_event``
audit-trail emission.

What it does
------------

For every ``send_intent`` event in the ledger that has no matching
outcome event (``send_confirmed`` / ``send_failed`` / ``send_aborted``),
append a synthetic ``send_aborted`` event that closes the two-phase
commit. The synthetic event carries:

* ``intent_id`` matching the originating intent
* ``person_id`` + ``channel`` denormalized from the intent (so a
  downstream reader doesn't have to join back through the index)
* ``reason`` — a human-readable explanation that ``ledger.py tail
  --type send_aborted`` operators can read without inspecting code
* ``_recovered_by`` — the migration id, prefixed ``migration_`` so
  it's distinguishable from ``reconcile`` / ``backfill`` synthetic
  events at a glance.

After processing every open intent, the migration emits one
``migration_event`` audit-trail event describing what it did.
Per ADR-0010 D17 every ledger migration emits this regardless of
whether it did work (a no-op apply still leaves the audit trail).

Why
---

Open intents that never received an outcome are a real failure mode
in the production system:

* Network failure mid-send: ``send_intent`` written, network drops
  before the Gmail API call completes, no outcome.
* Crash mid-send: same shape, different cause.
* Reconcile pass A handles SOME of these (it emits
  ``send_confirmed_orphan`` when the Gmail send actually succeeded
  but the local outcome wasn't recorded). This migration handles
  the complement: intents that have no Gmail trace AND no outcome
  — we close them by fiat with ``send_aborted`` because the asym-
  metric-failure-cost calculus says "assume the send didn't happen"
  is safer than leaving them open forever.

Why ``is_reversible=False``
---------------------------

Ledger is append-only. A "rollback" would need to either:

* Delete bytes from a JSONL file (forbidden — append-only is the
  load-bearing invariant), or
* Append a "re-open" event that consumers interpret as un-doing
  the ``send_aborted``. This would invent a brand-new event type
  with no precedent.

Per ADR-0010 D14 the contract is: ledger migrations are forward-
only; rollback requires backup + replay. The runner refuses
``rollback`` with ``MigrationNotReversibleError``.

TOCTOU between read and write
-----------------------------

The migration does a read-then-write across the ledger: Pass 1
scans every event to identify orphans; the append loop emits
``send_aborted`` per orphan. Between Pass 1 and a given append a
concurrent writer (dispatcher / reconcile / manual
``/send-outreach``) could append an outcome event for one of the
orphans we identified.

Two-layer mitigation:

1. **Rollout step 1.5** (ADR-0010 §Migration/rollout): operators
   stop the dispatcher before invoking ``apply``. This is the
   canonical safety belt.
2. **In-process re-check** (this module): immediately before the
   append loop, the migration rebuilds the outcome set from the
   ledger one more time and checks each orphan against it. Any
   orphan that gained an outcome between Pass 1 and the rebuild
   is skipped + logged. The remaining race window is microseconds
   (between rebuild and append) and is rare in practice.

The skipped-due-to-race count is surfaced in the operator-facing
log message + the ``MigrationResult.notes`` + the ``migration_event``
audit-trail event (``skipped_raced`` field).

Idempotence
-----------

The migration is idempotent at the per-event level:

* If an intent already has any outcome event (``send_confirmed``,
  ``send_failed``, or a prior ``send_aborted`` from a previous
  migration run or reconcile pass), the migration does NOT append
  a duplicate.
* Re-running ``upgrade`` directly after success finds zero new
  orphans → ``affected_count=0`` → still emits the ``migration_event``
  (every apply leaves an audit trail, per D17).

In production the runner skips re-invoking ``upgrade`` once the
state file shows the migration applied; the per-event idempotence
matters for the partial-failure retry case (the framework's
atomicity contract says a raising ``upgrade`` does NOT mark applied,
so re-running ``apply`` re-invokes ``upgrade`` — which must
gracefully handle that some events were already appended on the
first pass).

Refuse-on-missing-ledger
------------------------

The runner's ``ledger_dir`` defaults to ``<state_dir>/ledger``, so
``ctx.ledger_dir`` is never ``None``. The meaningful failure is
"the path doesn't exist on disk." The migration refuses loudly in
that case (raises ``FileNotFoundError``) rather than silently
creating an empty ledger:

* Silent creation could mask a misconfigured state dir (operator's
  ``OUTREACH_FACTORY_STATE_DIR`` env points at the wrong dir; the
  migration creates a fresh empty ledger; the migration is marked
  applied; the operator's real ledger remains untouched).
* The asymmetric-failure-cost calculus (PILLAR-PLAN §0) says loud
  refusal is correct here: false-positive refuse is recoverable
  (operator creates the dir + re-runs); false-negative silent
  apply is catastrophic (real ledger never gets the cleanup).

See ADR-0010 for the full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..runner import RUNNER_VERSION
from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    events_by_type,
    iter_events,
    latest_intent_outcome,
)


# The migration id — exported so tests + downstream consumers can refer
# to it symbolically without re-typing the string.
MIGRATION_ID = "0001_close_orphan_send_intents"

# The ``_recovered_by`` tag the migration stamps on every
# ``send_aborted`` event it emits. Prefix ``migration_`` distinguishes
# from ``reconcile`` / ``backfill`` synthetic events at a glance —
# operators reading ``ledger.py tail`` immediately see which subsystem
# produced the event.
RECOVERED_BY_TAG = f"migration_{MIGRATION_ID}"

# Human-readable reason on every emitted ``send_aborted`` event. Lives
# at module scope so the test suite + ADR can verify the operator-
# facing message without scraping the implementation.
_ABORT_REASON = (
    "closed by migration_0001_close_orphan_send_intents: the "
    "originating send_intent had no matching outcome at migration "
    "apply time. Per ADR-0010 the migration closes orphan intents "
    "by fiat with send_aborted — operators inspecting this event "
    "can manually inspect the originating intent and emit a "
    "manual_override if the send actually completed."
)


@dataclass
class CloseOrphanSendIntents:
    """Append ``send_aborted`` for every ``send_intent`` lacking an outcome.

    See module docstring for the full contract. This class is a
    thin dataclass implementing the ``Migration`` Protocol; the
    work happens in :meth:`upgrade`. :meth:`downgrade` raises
    ``NotImplementedError`` because the migration is structurally
    irreversible (append-only ledger).

    Constructed once at module import time and exported as
    ``MIGRATION``; the category sub-package's ``__init__.py``
    registers it into ``MIGRATIONS = [MIGRATION]``.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.LEDGER
    description: str = (
        "Close every orphan send_intent (no matching outcome event) "
        "by appending a send_aborted with _recovered_by tagging"
    )
    is_reversible: bool = False

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Close orphan intents + emit the audit-trail event.

        Refuses with ``FileNotFoundError`` if ``ctx.ledger_dir`` does
        not exist as a real directory on disk. Operators with a fresh
        state dir whose ledger sub-dir hasn't been created yet should
        emit at least one event through the normal send path before
        invoking the migration (or ``mkdir -p`` the directory
        explicitly).

        Returns a :class:`MigrationResult` with ``affected_count`` set
        to the number of ``send_aborted`` events appended (or in
        ``dry_run`` mode, the number that WOULD be appended).

        Side effects:

        * If not ``dry_run``: N + 1 events appended to the ledger
          (N ``send_aborted`` + 1 ``migration_event``).
        * If ``dry_run``: zero events appended.

        Raises
        ------
        FileNotFoundError:
            When ``ctx.ledger_dir`` does not exist. Distinguishable
            from the vault migration's ``ValueError`` (which fires on
            ``ctx.vault_dir is None``) — the ledger context's path is
            always set, so the meaningful refusal is "path doesn't
            exist."
        """
        ledger_dir = Path(ctx.ledger_dir)
        if not ledger_dir.exists():
            raise FileNotFoundError(
                f"ledger migration {self.id!r} requires "
                f"ctx.ledger_dir to be an existing directory; got "
                f"{ledger_dir!s}. Either point the runner at the "
                f"correct ledger dir (operator's "
                f"~/.outreach-factory/ledger/ in production) or "
                f"`mkdir -p` it before applying.",
            )

        # Pass 1 — collect every send_intent + figure out which ones
        # already have an outcome. We walk the ledger once and bucket
        # events by intent_id so the orphan check is O(N) rather than
        # O(N²).
        intents_by_id: dict[str, dict] = {}
        intents_with_outcome: set[str] = set()
        for e in iter_events(ledger_dir):
            t = e.get("type")
            iid = e.get("intent_id")
            if not iid:
                continue
            if t == "send_intent":
                # First send_intent wins on dedup (matches
                # Ledger._idx_intent_origin behavior — the index
                # records the originating intent, not the latest).
                intents_by_id.setdefault(iid, e)
            elif t in ("send_confirmed", "send_failed", "send_aborted"):
                intents_with_outcome.add(iid)

        orphans = [
            intent for iid, intent in intents_by_id.items()
            if iid not in intents_with_outcome
        ]

        # TOCTOU narrowing: between Pass 1 completing and the append
        # loop running, a concurrent writer (dispatcher / reconcile /
        # manual /send-outreach) may have appended an outcome event
        # for one of our orphan intents. Re-build the outcome set
        # immediately before the append loop so the race window
        # shrinks from "all of Pass 1 + the entire loop" down to
        # "this rebuild + each individual append" — typically
        # microseconds. The remaining narrow window is closed by
        # ADR-0010 §Migration / rollout step 1.5 (quiesce dispatcher
        # before apply); this in-process check is defense-in-depth
        # so an operator who forgets the rollout step still gets
        # correct semantics in the common case (no concurrent
        # outcome arrives during the few microseconds between
        # rebuild and append).
        if not ctx.dry_run:
            fresh_outcomes: set[str] = set()
            for e in iter_events(ledger_dir):
                if e.get("type") in (
                    "send_confirmed", "send_failed", "send_aborted",
                ):
                    iid = e.get("intent_id")
                    if iid:
                        fresh_outcomes.add(iid)
        else:
            # In dry-run we skip the rebuild — the orphans list from
            # Pass 1 IS the preview the caller sees.
            fresh_outcomes = intents_with_outcome

        affected = 0
        skipped_raced = 0
        for intent in orphans:
            iid = intent.get("intent_id")
            if iid in fresh_outcomes:
                # Concurrent writer appended an outcome between Pass 1
                # and now. Skip — emitting send_aborted would clobber
                # the truth the concurrent writer recorded.
                ctx.logger.warning(
                    "intent %s gained an outcome between Pass 1 scan "
                    "and append (concurrent writer detected); "
                    "skipping. Per ADR-0010 §Migration/rollout the "
                    "dispatcher should be quiesced before apply to "
                    "eliminate this race entirely.",
                    iid,
                )
                skipped_raced += 1
                continue
            if not ctx.dry_run:
                append_event_atomic(ledger_dir, {
                    "type": "send_aborted",
                    "intent_id": iid,
                    "person_id": intent.get("person_id"),
                    "channel": intent.get("channel"),
                    "reason": _ABORT_REASON,
                    "_recovered_by": RECOVERED_BY_TAG,
                })
            affected += 1

        verb = "would close" if ctx.dry_run else "closed"
        ctx.logger.info(
            "%s %d orphan send_intent event(s) by appending "
            "send_aborted with _recovered_by=%s "
            "(skipped %d intent(s) that gained outcomes between "
            "scan and append — concurrent-writer race)",
            verb, affected, RECOVERED_BY_TAG, skipped_raced,
        )

        # Per ADR-0010 D17: emit migration_event on EVERY apply,
        # including no-op + dry_run-equivalent runs. The dry-run
        # case skips even this emission — a dry run mutates nothing.
        if not ctx.dry_run:
            emit_migration_event(
                ledger_dir,
                migration_id=self.id,
                affected_count=affected,
                runner_version=RUNNER_VERSION,
                category=self.category.value,
                notes=(
                    f"{verb} {affected} orphan send_intent(s) by "
                    f"appending send_aborted with _recovered_by="
                    f"{RECOVERED_BY_TAG}"
                    + (
                        f"; skipped {skipped_raced} due to concurrent-"
                        f"writer race (see ADR-0010 §Migration/rollout)"
                        if skipped_raced else ""
                    )
                ),
                skipped_raced=skipped_raced,
            )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} {affected} orphan send_intent event(s)"
                + (
                    f" ({skipped_raced} skipped due to concurrent "
                    f"writer)" if skipped_raced else ""
                )
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Refuse — ledger is append-only.

        Raises ``NotImplementedError``; the runner translates this
        into ``MigrationNotReversibleError`` for the operator-facing
        error message. Per ADR-0010 D14 every ledger migration is
        ``is_reversible=False`` and ``downgrade`` raises here; the
        runner refuses ``rollback`` BEFORE invoking ``downgrade``
        (it checks ``is_reversible`` first), so this body is only
        reached if a caller bypasses the runner.
        """
        raise NotImplementedError(
            f"ledger migration {self.id!r} is structurally "
            "irreversible (append-only ledger). The runner refuses "
            "rollback with MigrationNotReversibleError. To recover "
            "from a bad apply: restore the ledger directory from "
            "backup and re-run from a state-file checkpoint."
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: CloseOrphanSendIntents = CloseOrphanSendIntents()
