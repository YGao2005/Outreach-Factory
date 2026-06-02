# ADR-0010: Ledger migrations — append-only superseding event pattern, `migration_event` audit trail, helper-module dispatcher

- **Status:** Accepted
- **Date:** 2026-05-19
- **Pillar:** B (Migration framework — Week 3 ledger dispatcher + first real ledger migration)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0009 (Week 1) shipped the migration-framework foundation; ADR-0011 (Week 2) shipped the vault per-category dispatcher + first real vault migration. Per ADR-0009 D7, per-category ADRs land alongside per-category dispatchers + first concrete migrations. Pillar B Week 3 ships the ledger per-category dispatcher.

The ledger is structurally different from the vault. The vault is a denormalized view of the ledger (I1); a vault migration that loses data is reconstructible from the ledger via reconcile. The ledger is the SoT (I1) and irreplaceable — a ledger migration that loses data has no recovery vehicle inside the system. The asymmetric-failure-cost calculus (PILLAR-PLAN §0) compels stricter design discipline:

1. **Append-only at the file level is the binding contract.** Per `orchestrator/ledger.py` line 1–15, the ledger uses `O_APPEND + fcntl.lockf + fsync` for every write. Concurrent writers (dispatcher + manual /send-outreach + reconcile + now this migration helper) serialize at the same lock. In-place mutation of an existing event is forbidden — it would either require deleting bytes from a JSONL file (which we never do) or rewriting a line in place (no atomic primitive for that exists at the file level the way `os.replace` exists for whole files).

2. **Superseding events are the migration's only mutation tool.** When a ledger migration needs to "change" the meaning of an existing event, the valid shape is to append a new event that downstream readers interpret in preference. Precedent: `orchestrator/reconcile.py` emits `send_confirmed_orphan` with `_recovered_by: reconcile` when Pass A finds a Gmail message that has no local `send_confirmed`. The orphan event supersedes the inferred-from-bare-intent semantic. Ledger migrations follow the same shape — every appended event carries a `_recovered_by` tag (or analogous `migration_id` field) so downstream readers can distinguish synthetic events from organically-emitted ones.

3. **Reversibility is structurally impossible.** The ledger has no "remove" primitive; the only inverse of "append event X" is "append event Y that consumers interpret as undoing X." That would require a new event type with no precedent + tight coupling between the migration and every downstream reader. Per D14 below, ledger migrations declare `is_reversible=False`; rollback requires backup + replay.

4. **Pillar B's exit-criterion vehicle (Weeks 5–6 synthetic replay) consumes this surface.** The framework's value proposition is that `backfill_identity.py` + `backfill_ledger.py` get a second life as `Migration` instances replayed against synthetic before-states (ADR-0013). The Week 3 helper module + first real migration MUST compose cleanly with a synthetic-ledger constructor in that vehicle. Specifically: every helper function accepts an arbitrary `ledger_dir` path (not hardcoded to `DEFAULT_LEDGER_DIR`) so the replay test points it at fixture data.

Three concerns this ADR resolves:

- **The per-category dispatcher boundary for ledger has a shape now.** ADR-0009 §Decision item "Layout" promised `orchestrator/migrations/ledger/` would gain a dispatcher boundary; Week 3 makes it concrete: `_ledger_io.py` exposes the per-event IO surface migrations consume.
- **The `migration_event` audit-trail type, present in the catalog but never emitted, gains its first emit site.** Per `orchestrator/ledger.py` line 68, `migration_event` is in the event catalog as an Admin type. A `grep -rn '"migration_event"' orchestrator/` before Week 3 returned only the docstring; the type was declared but unused. Week 3 standardizes the shape (D17 below) and emits one per migration apply.
- **The first concrete ledger migration shape demonstrates the pattern.** `0001_close_orphan_send_intents` exercises every contract this ADR pins: append-only superseding events, `_recovered_by` tagging, `migration_event` emission, idempotence at the per-event level, refuse-on-missing-ledger-dir, `is_reversible=False`.

Risks this ADR mitigates: **R005 (ledger schema bump regret)** by giving Pillar D / E / G a vehicle for additive ledger evolution that future readers can interpret correctly. ADR-0009's R002 (vault frontmatter drift) is unchanged — vault work is ADR-0011's surface.

## Decision

### D14. Per-category dispatcher shape — helper module, mirroring ADR-0011 D8

`orchestrator/migrations/ledger/_ledger_io.py` exposes module-level functions + delegates to `orchestrator.ledger.Ledger.append` for every write. Migrations import what they need:

```python
from ._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    events_by_type,
    iter_events,
    latest_intent_outcome,
)
```

Rejected the dispatcher-class shape (`LedgerDispatcher` wrapping all helpers with a per-batch transaction context). Same reasoning as ADR-0011 D8: helper-module shape is precedented across `orchestrator/policy/`, lets a migration import only what it needs, and avoids ceremony for migrations that are ~100 LOC each.

Why delegate to `Ledger.append` rather than re-implement:

- The atomicity contract (`O_APPEND + fcntl.lockf + fsync`) is load-bearing. Re-implementing it in `_ledger_io.py` would mean two code paths to keep aligned across future changes (rotate-at-midnight, symlink-on-write, etc.). Delegation guarantees alignment.
- Every concurrent writer in the system (`dispatcher`, `/send-outreach`, `reconcile`, this migration helper) serializes at the same `fcntl.lockf` lock by virtue of opening the same file with the same flags. Re-implementation would risk introducing a parallel-lock path that doesn't coordinate with the existing one.
- The cost of delegation is constructing a `Ledger(ledger_dir)` object per call. `Ledger.__init__` is cheap (sets paths, mkdirs the dir, initializes empty indexes); no I/O happens until `append` or a query method is called.

The helper IS the dispatcher boundary — concrete migrations consume the surface; the surface owns the per-event IO conventions + parsing tolerance; the runner stays generic-over-category and doesn't know what a ledger migration is.

### D15. First real ledger migration — `ledger/0001_close_orphan_send_intents`

`orchestrator/migrations/ledger/migration_0001.py` is the first concrete ledger migration. For every `send_intent` event with no matching outcome event (`send_confirmed | send_failed | send_aborted`), it appends a synthetic `send_aborted` that carries:

* `intent_id` matching the originating intent.
* `person_id` + `channel` denormalized from the intent.
* `reason` — a human-readable explanation: *"closed by migration_0001_close_orphan_send_intents: the originating send_intent had no matching outcome at migration apply time. Per ADR-0010 the migration closes orphan intents by fiat with send_aborted — operators inspecting this event can manually inspect the originating intent and emit a manual_override if the send actually completed."*
* `_recovered_by: "migration_0001_close_orphan_send_intents"` — the same convention `_recovered_by: "backfill"` / `_recovered_by: "reconcile"` use, prefixed with `migration_` to distinguish at-a-glance from the other synthetic-event sources.

Contract:

* **Idempotent at the per-event level.** If an intent already has any outcome event (including `send_aborted` from a prior reconcile pass or migration run), the migration does NOT append a duplicate.
* **Idempotent on direct re-invocation.** Direct call to `upgrade(ctx)` after success finds zero new orphans, `affected_count=0`, STILL emits the `migration_event` audit-trail event (per D17). In production the runner skips re-invoking `upgrade` once the state file shows applied; the direct-call idempotence matters for the partial-failure retry case (per ADR-0009 D4 a raising `upgrade` doesn't mark applied; re-running `apply` re-invokes `upgrade` and the helper must handle the partial-state).
* **Per-event atomic.** Each appended event goes through `append_event_atomic` (which delegates to `Ledger.append`) — `O_APPEND + fcntl.lockf + fsync`. The per-event atomicity is the framework-level analog of the vault migration's per-file atomicity (ADR-0011 D10).
* **Refuses on missing ledger dir.** If `ctx.ledger_dir` does not exist on disk, the migration raises `FileNotFoundError`. Silent creation could mask a misconfigured `state_dir` env var (operator points runner at wrong dir; fresh empty ledger is created; migration marks applied; operator's real ledger is untouched). The asymmetric-failure-cost calculus: loud refusal is recoverable (operator `mkdir -p`s and re-runs); silent apply is catastrophic.
* **`is_reversible=False`.** Per D14, ledger migrations are forward-only.

Rejected alternatives (D15 specifically):

- **`ledger/0001_baseline_migration_event`** — appends ONE `migration_event` recording "Pillar B Week 3 ran." No-op in effect. The Pillar A Week 1 handoff explicitly rejected this shape ("boundary-of-empty proof"): the empty placeholder in Week 1 already proves the boundary exists; what's missing is the surface a real migration consumes.

- **`ledger/0001_normalize_legacy_timestamps`** — for every event missing a timezone offset, append a corrective event. Rejected because the ledger has only existed since Phase 5.5 with strict timezone-aware writes; no real events have this problem. The migration would have `affected_count=0` on every operator's ledger, exercising boundary-of-empty.

- **A migration that uses Gmail API to verify each orphan before closing.** Pillar D / G surface this naturally (Pillar D's reconcile Pass A already does Gmail introspection). Pulling the API call into Week 3 would couple the migration framework to external service availability — bad shape. The conservative "close by fiat" posture is recoverable post-hoc (operator inspects, emits `manual_override` if needed).

Counter-argument: a real ledger migration in Week 3 risks disturbing the operator's live ledger. **Mitigations:**

* **Dry-run preview.** `MigrationRunner.dry_run()` invokes `upgrade(ctx)` with `dry_run=True`; the migration computes `affected_count` without writing. Operators see "would close N orphan intents" before committing.
* **Doctor's WARN-on-pending surface** (shipped Week 2). Operators see "ledger/0001 pending" in `doctor.py` output and can apply on their schedule.
* **Per-event idempotence.** Re-running `apply` after fixing a partial-failure picks up where the previous attempt left off; no double-close.

### D16. ADR-0010 scope — narrow, per the per-ADR convention

This ADR covers:

* The append-only-superseding-event pattern (no in-place rewrites; superseding events get `_recovered_by` or `migration_id` tagging).
* The reversibility limit (`is_reversible=False` is the default for ledger migrations).
* The `_ledger_io.py` dispatcher boundary (D14).
* The first real migration's shape (D15).
* The `migration_event` audit-trail emission contract (D17).
* Downstream pillar impact (cross-cutting per the ADR-0009 convention).

Out of scope (explicitly deferred):

- **Synthetic-replay exit-criterion vehicle (Week 5–6 / ADR-0013).** Per the Pillar A retrospective on per-ADR scoping: keep each ADR narrow; the replay vehicle is its own ADR. ADR-0010 ensures the Week 5–6 work CAN compose by accepting arbitrary `ledger_dir` paths, but doesn't pre-bake the replay shape.
- **CLI (`python -m orchestrator.migrations apply`).** Same shape as ADR-0011's deferral; lands once per-category dispatchers stabilize across Weeks 3–4. Operators invoke via Python REPL / script in Week 3.
- **Replaying `backfill_identity.py` + `backfill_ledger.py` as `Migration` instances.** Phase 5.5's backfill scripts are the most likely Week 5–6 deliverables. Their shape ALREADY composes with this ADR: backfill events carry `_recovered_by: "backfill"` and use deterministic synthetic `intent_id`s (`bf_<sha256>...`). Wrapping them as `Migration` instances is mechanical (the `upgrade` body is mostly already in `backfill_ledger.plan_and_apply`).
- **Refuse-on-pending in doctor for ledger migrations.** ADR-0011 D12 punted this to Pillar I; ADR-0010 inherits the same posture — Week 3's `doctor.py:check_migrations` already surfaces both vault/0001 AND ledger/0001 via the same WARN-on-pending shape. No category-specific tightening here.

### D17. Every ledger migration emits one `migration_event` per apply

The ledger has a `migration_event` event type in its catalog (`orchestrator/ledger.py` line 68) that has not yet been emitted by any production code path. ADR-0010 standardizes the shape + makes Week 3 the first real emit:

```python
{
  "v": 1,
  "ts": "2026-05-19T12:34:56.789Z",
  "type": "migration_event",
  "migration_id": "0001_close_orphan_send_intents",
  "affected_count": 5,
  "runner_version": "0.1.0",
  "category": "ledger",
  "notes": "closed 5 orphan send_intent(s) by appending send_aborted with _recovered_by=migration_0001_close_orphan_send_intents"
}
```

Required fields: `type` (always `"migration_event"`), `migration_id` (the migration's `id`), `affected_count` (how many primary writes the migration performed). Helper-injected fields: `ts`, `v`. Standardized-by-helper-contract fields: `runner_version`, `category`, `notes` — passed as `**extra` to `emit_migration_event` from every ledger migration.

Reserved-field-collision check: the helper's `emit_migration_event` raises `ValueError` if `**extra` includes any of `type`, `migration_id`, `affected_count`, `ts`, `v` — the standardized shape is load-bearing for downstream readers (Pillar G OTel, Pillar J compliance, Week 5–6 replay), and a migration that overrides one of these silently would break that contract.

Every ledger migration's `upgrade` calls `emit_migration_event` exactly once at the end, regardless of work performed:

- After closing N orphans → `affected_count=N`.
- On a no-op re-apply (zero orphans found) → `affected_count=0`.
- On a dry-run → NOT emitted (dry-runs mutate nothing per `MigrationContext.dry_run` contract).

Rationale for emitting on no-op too: the audit trail is "when did this migration last apply against this ledger?" — the answer is interesting even when the work was zero. Pillar G's observability dashboards can chart `migration_event` over time; a no-op apply line distinguishes "migration was never run" from "migration ran but found nothing to do."

Rejected:

- **Emit `migration_event` only when `affected_count > 0`.** Loses the no-op-apply audit trail. Future Pillar G dashboards would have to infer "the operator ran the migration but nothing happened" from secondary evidence; that's worse than an explicit event.
- **Standardize a stricter shape (`ts_start` + `ts_end` for timing).** Pillar G is the natural home for timing instrumentation; adding it here would couple Week 3 to OTel evolution. Future Pillar G work can amend `migration_event` shape via a fresh ADR + migration.
- **Emit on `downgrade` too.** For irreversible migrations `downgrade` raises `NotImplementedError` before reaching any emit site; for hypothetical future reversible ledger migrations (none currently planned) the `downgrade` body would emit its own `migration_event` with a distinguishing field (e.g. `direction: "downgrade"`). Out of scope until a reversible ledger migration is actually proposed.

### Downstream pillar impact

Per the ADR-0009 convention (every Pillar B ADR explicitly names cross-pillar impact):

* **Pillar D (reply + conversation handling).** The reply classifier reads events; new event types (`reply_classified`, `conversation_state_transition`) land via ledger migrations consuming this ADR's surface. The Pillar D author writes `ledger/000N_add_reply_state_events.py` following the `ledger/0001` pattern + reuses `_ledger_io.py` helpers wholesale. The append-only-superseding-event discipline transfers directly: a new `reply_received_v2` event with richer fields would NOT rewrite existing `reply_received` events; it'd append v2 events for new replies + readers would prefer the latest version.

* **Pillar E (discovery quality + lineage).** Pillar E's enroll-time lineage capture writes to `enrolled` event shape. A future migration that backfills lineage onto historical enrollments would emit one synthetic `enrolled` event per Person with `_recovered_by: migration_NNNN_backfill_lineage` AND a `superseded_by: <new_event_id>` cross-reference. The cross-reference field is a Pillar E concern; this ADR's only contribution is the precedent that "append synthetic events with `_recovered_by` tagging" is the right shape.

* **Pillar F (voice corpus + draft quality).** No direct ledger work in Pillar F (voice events live in the vault); Pillar F may consume `migration_event` audit-trail events for replay-test purposes.

* **Pillar G (observability).** OTel + Prometheus emit per-event; `migration_event` becomes a first-class observable. The Pillar G dashboard "when did we last apply migrations?" reads directly from this event. Cost-per-migration timing (a future need) extends `migration_event` shape via a fresh ADR.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant ledger directories; each tenant gets independent migration state. The doctor's refuse-on-pending hardening applies uniformly to vault/ledger/policy migrations. No category-specific work here.

* **Pillar J (security + compliance).** GDPR-forget on a ledger migration (e.g. `ledger/000N_purge_pii_from_old_events`) is the catastrophic-failure-mode case: the migration appends a `tombstone_event` referencing the to-be-purged events; a SEPARATE compaction tool (Pillar J's `policy.py forget`) actually removes the bytes from JSONL files at the next rotation. The two-step shape preserves the append-only invariant during normal operation; the compaction step is the only place bytes are removed, and it runs with a write-pause + backup. ADR-0010 doesn't ship the compaction tool; it ships the migration shape that future compaction-tooling will compose with.

  Specifically: ledger compaction in Pillar J does NOT use the migration framework — it's a separate primitive because the migration framework's contract is "append-only, no removal." Pillar J's compaction is "remove bytes at a controlled checkpoint" — a different shape with different safety bars.

## Alternatives considered

### Alternative 1: Dispatcher class per category (`LedgerDispatcher`)

A class wrapping the per-event IO + offering a batch-transaction context manager. Migrations instantiate and use. **Rejected** — same shape as ADR-0011 §Alternative 1: helper-module is precedented + lets migrations import only what they need + a transaction-context wrapper adds no real protection beyond what `fcntl.lockf` already provides (every `append_event_atomic` call is its own atomic event; a multi-event "transaction" would either need cross-event locking — which the ledger doesn't support — or would lie about atomicity).

### Alternative 2: Re-implement `O_APPEND + fcntl.lockf + fsync` inside `_ledger_io.append_event_atomic`

Skip the `Ledger` class round-trip; write the line directly. **Rejected** because:

* Two code paths to keep aligned. The daily-rotation logic, symlink-on-write logic, and (future) backup-rotation logic in `Ledger.append` would have to be duplicated in the migration helper.
* Risk of parallel-lock paths that don't coordinate. The migration helper's lock acquisition would need to be byte-identical to `Ledger.append`'s; even one divergence (a different `fcntl.lockf` flag, a different file descriptor pattern) could allow a race.
* Construction cost of `Ledger(ledger_dir)` is negligible — no I/O until `.append()` is called.

The delegation pattern matches the Pillar A precedent where `orchestrator/policy/budget.py`'s rule classes don't re-implement ledger queries; they go through `LedgerLike` + the production `Ledger.query_by_person`.

### Alternative 3: Make the first ledger migration a no-op `baseline` that just emits `migration_event`

Land `ledger/0001_baseline` that emits one `migration_event` with `affected_count=0` and nothing else. The first real ledger migration waits for a concrete Pillar D / E / G need to surface. **Rejected** because:

* Exercising boundary-of-empty is not the same as boundary-of-real. The Week 1 empty placeholder already proves the dispatcher boundary exists; what's missing is the surface a real migration consumes, and we add that surface for ledger here.
* The Pillar A retrospective explicitly noted "deferred indefinitely" is a valid outcome (per ADR-0007 §Alternative 4 `simulation.py` precedent), but the Week 3 handoff document recommended a real migration. Reversing that recommendation in this ADR would be ADR drift.
* `close_orphan_send_intents` is a genuinely useful migration — operators with long-running send loops occasionally accumulate orphan intents (network failure mid-send + no reconcile pass yet). Shipping the migration in Week 3 means operators have a tool for that case.

### Alternative 4: Use the Gmail API to verify each orphan before closing

For every `send_intent` without an outcome, hit Gmail's API to check if the send actually completed. Only close intents with no Gmail trace. **Rejected** because:

* Couples the migration framework to external service availability. A migration that depends on Gmail being reachable can't run during an outage; that's the wrong shape for a framework whose purpose is local schema evolution.
* Reconcile Pass A already does Gmail introspection — it's the right surface for that work. Pulling it into the migration framework would conflate "schema evolution" with "data healing."
* The conservative posture (close by fiat with `send_aborted`) is recoverable: operator inspects the events afterward and emits `manual_override` if a send actually completed. The asymmetric-failure-cost calculus says forward-only + recoverable beats data-dependent + brittle.

### Alternative 5: Emit `migration_event` only when `affected_count > 0`

Standardize the audit-trail event but only emit on non-zero applies. **Rejected** because the no-op-apply audit trail is interesting. Pillar G dashboards charting "when was each migration last applied" need explicit signal for "applied but found nothing to do"; inferring it from absence of evidence is worse than an explicit zero-count event.

### Alternative 6: Make the `_recovered_by` tag a plain string field (not the canonical `_recovered_by` convention)

Use `migration_origin: "0001_close_orphan_send_intents"` instead of `_recovered_by: "migration_0001_close_orphan_send_intents"`. **Rejected** because:

* `_recovered_by` is already established convention in `backfill_ledger.py` (Phase 5.5) + `reconcile.py` (production). Adding a parallel field would force every downstream reader to check two field names instead of one.
* The `migration_` prefix on the value (`migration_0001_close_orphan_send_intents`) is the right disambiguation — operators reading `ledger.py tail` see at a glance which subsystem generated the synthetic event.

### Alternative 7: Reverse the ADR ordering — number this 0011 since vault landed first in Week 2

Renumber: vault becomes ADR-0010 (since it shipped Week 2), ledger becomes ADR-0011 (Week 3). **Rejected** — same shape as ADR-0011 D13's rejection of renumbering: ADRs are append-only at the directory level, and ADR-0009 already references "ADR-0010 = ledger" + "ADR-0011 = vault" in its forward-references. Renumbering would break the existing references. Reserved → Accepted is the correct transition for ADR-0010.

### Alternative 8: Ship a `downgrade` that appends a "rollback event" type

Define a new event type `migration_rolled_back` that consumers interpret as "treat the original migration's effects as undone." Make ledger migrations conceptually reversible. **Rejected** because:

* Inventing a new event type couples every downstream reader (reply classifier, conversation state machine, observability dashboards) to migration-specific event shapes. Bad shape.
* The "is it currently rolled back?" question becomes a derived-state query that joins migration events with rollback events — exactly the kind of cross-event state machine the append-only-superseding pattern was designed to avoid.
* Backup + replay is the right recovery path for ledger-level disasters. It's already the discipline operators are expected to follow (every dispatch run has a snapshot of `~/.outreach-factory/ledger/`); the migration framework doesn't need to reinvent it.

## Consequences

### Positive

- **The append-only-superseding-event pattern is uniform across migrations + reconcile + backfill.** Operators have one mental model: synthetic events carry `_recovered_by`; the prefix tells you which subsystem emitted them (`backfill`, `reconcile`, `migration_<id>`).
- **Pillar D / E / G inherit a working pattern.** A future Pillar D author writing `ledger/000N_add_reply_state_events.py` reuses `_ledger_io.py` helpers + emits `migration_event` via the standardized helper. No category-specific design needed.
- **`migration_event` becomes a first-class observable.** Pillar G's "when did the schema evolve?" dashboard reads directly from this event type. Pillar J's compliance audit ("which migrations ran in the last quarter?") is a one-query filter.
- **Per-event idempotence is a tested contract.** `0001` is idempotent at the per-event level (re-run finds zero orphans) AND survives the partial-failure retry (first pass appended some events; second pass picks up remaining orphans). The test suite pins both.
- **The synthetic-replay vehicle (Week 5–6) has a clean composition path.** Every `_ledger_io` helper accepts an arbitrary `ledger_dir`; the replay test will construct a synthetic ledger fixture and point the helper at it. Backfill scripts can be wrapped as `Migration` instances in Week 5–6 with mechanical edits to their `plan_and_apply` bodies.

### Negative

- **Ledger migrations are forward-only.** No `downgrade`; operators recovering from a bad apply restore from backup + replay from a state-file checkpoint. **Mitigation:** the framework's atomicity contract (raise → state pointer doesn't move) means most "bad apply" cases never actually apply on disk; the recover-from-backup case is the genuine catastrophe scenario. ADR-0009 §Negative already names this trade-off.
- **`migration_event` shape is now de-facto contract.** Future evolutions (adding `ts_start` + `ts_end` for timing, adding `tenant_id` for multi-tenant) require an ADR amendment + a migration to backfill the new fields onto historical `migration_event` events. **Mitigation:** the helper's reserved-field-collision check makes the contract loud + obvious — a contributor trying to add `migration_id` as an extra field hits an explicit `ValueError`.
- **The orphan-closing migration's "close by fiat" posture may close intents the operator wishes had been confirmed.** A `send_intent` with no outcome that actually succeeded in Gmail (but reconcile never ran to detect it) becomes a `send_aborted` event after the migration. The downstream send-gate then allows a duplicate send to the same human. **Mitigation:** (a) ADR-0010 D15's reason field explicitly names this case and instructs operators to inspect; (b) reconcile Pass B (already shipped Phase 5.5) would have detected the orphan-but-confirmed case BEFORE this migration ran; (c) the operator's `manual_override` event is the documented recovery path. Operators with active dispatchers should ensure reconcile is current before running this migration.
- **TOCTOU race between Pass 1 scan and the append loop.** Identified in the Week 3 follow-up review. The migration walks the ledger to identify orphans (Pass 1) and then loops to append `send_aborted` events (Pass 2). Between Pass 1 and a specific Pass 2 append, a concurrent writer can append an outcome event for the same `intent_id` — producing both `send_confirmed` (from the concurrent writer) and `send_aborted` (from this migration) for the same intent. Two-layer mitigation: (a) rollout step 1.5 above instructs operators to quiesce the dispatcher before apply — this is the canonical safety belt; (b) the migration rebuilds the outcome set in memory immediately before the Pass 2 append loop and skips any orphan whose `intent_id` now appears in the rebuilt set, narrowing the remaining race window from "all of Pass 1 + the entire append loop" (potentially seconds) to "the rebuild call + each individual append" (microseconds). The skipped count surfaces in the operator log, the `MigrationResult.notes`, and the `migration_event`'s `skipped_raced` field. The narrow remaining window is rare in practice and the test suite documents the in-process narrowing path (`TestConcurrentWriterRace.test_concurrent_outcome_during_scan_is_detected_and_skipped`).
- **No CLI yet.** `python -m orchestrator.migrations apply` still doesn't exist. Operators invoke `MigrationRunner().apply()` from a Python REPL or script. **Mitigation:** deferred to Pillar I's OSS bring-up; the helper-module pattern + `__init__.py` registry list are CLI-ready when the time comes.

### Neutral / observability

- The migration logs at INFO with `affected_count` + `_recovered_by` tag. The doctor's WARN-on-pending message surfaces "ledger/0001_close_orphan_send_intents" by id. Pillar G's OTel wiring picks up both surfaces unchanged.
- The `migration_event` audit-trail events accumulate one per apply; over a year of normal operation, expect ~3-5 events per migration (one initial apply + retries during partial-failure cases). Storage overhead is negligible.
- `FileNotFoundError` is a built-in exception; the migration uses it directly rather than introducing a new exception class. Future ledger migrations may add domain-specific exceptions (`LedgerSchemaMismatchError`, etc.); none are needed for `0001`.

## Compliance with invariants

- **I1 (single source of truth):** The ledger is the SoT for "did we send to this human?" This migration's `send_aborted` events are NOT a new SoT — they're synthetic events that close two-phase commits the SoT already knows about. The `_recovered_by` tag distinguishes synthetic from organic so the SoT view doesn't lose meaningful provenance. No SoT changes.
- **I2 (two-phase commit):** This migration operationalizes I2 for orphan intents — every `send_intent` event MUST have a matching outcome event (`send_confirmed | send_failed | send_aborted`). The migration enforces this invariant retroactively on existing orphans. After apply, the invariant holds for every intent in the ledger.
- **I3 (schema versioning):** Ledger events carry `v: 1`; this migration's appended events also carry `v: 1` (the helper auto-fills via `Ledger.append`). The `migration_event` events themselves are at `v: 1`. Future event-schema bumps (Pillar D / G) would emit migrations that append events at `v: 2+`; the existing v1 events stay at v1 (the migration framework is for evolving schemas forward, not for retroactively renumbering existing data).
- **I5 (observable by default):** Every apply + downgrade-refusal logs at INFO with the migration id. The `migration_event` event itself is the structured-observability surface; Pillar G consumes it directly.
- **I6 (tests prove invariants):** New tests across `tests/test_migrations_ledger_io.py` (32) + `tests/test_migrations_ledger_0001.py` (27). Per-event atomicity is pinned by the cross-process concurrency test (two workers each append 10 events; 20 distinct events visible after). Idempotence is pinned by the direct-re-invocation test + the partial-failure retry test. Refuse-on-missing-ledger is pinned. `is_reversible=False` + `MigrationNotReversibleError` are pinned at both the protocol level and the runner level.
- **I7 (cost is a first-class concern):** Ledger migrations do not emit `cost_incurred` events — they're local IO with no external API calls. The `migration_event` audit-trail does NOT carry timing fields in Week 3; Pillar G adds them via a future ADR amendment if needed.
- **I8 (decisions documented):** This ADR. ADR-0009 §References gains a "Shipped since this ADR landed" subsection entry for ADR-0010. `docs/adr/README.md` flips ADR-0010 from Reserved to Accepted.

Does not weaken any invariant. I2's enforcement is strictly strengthened — orphan intents are no longer a possible state after the migration applies.

## Migration / rollout

The first real ledger migration is `ledger/0001_close_orphan_send_intents`. Rollout shape:

1. Operator runs `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             2 pending: ledger/0001_close_orphan_send_intents, vault/0001_add_schema_version_to_person_notes
   ```

1.5. **Quiesce the dispatcher (and any other concurrent ledger writer) before proceeding.** If the operator runs the dispatcher as a background process, stop it now (`Ctrl-C` the dispatcher, or send `SIGTERM` to the daemon). Confirm no dispatcher / reconcile / manual `/send-outreach` process is active before running `apply`. The migration's read-then-append loop is not atomic across the whole batch — a concurrent writer that appends an outcome event between the migration's scan and its append for the same `intent_id` produces a non-deterministic outcome (the migration's in-process re-check narrows the race window to microseconds but does not eliminate it; quiescence is the canonical safety belt). Restart the dispatcher after the doctor confirms `ledger/0001` is applied.

2. Operator ensures reconcile is current (per the D15 mitigation — Gmail-side state should be reflected in the ledger before the migration closes orphans by fiat):
   ```bash
   python orchestrator/reconcile.py --apply  # pass A + B; emits send_confirmed_orphan for any Gmail-side sends with missing local outcomes
   ```

3. Operator runs the dry-run preview:
   ```python
   from pathlib import Path
   from orchestrator.migrations import MigrationRunner, MigrationCategory
   runner = MigrationRunner()
   preview = runner.dry_run(MigrationCategory.LEDGER)
   # Prints "would close N orphan send_intent(s)"; N should match the
   # operator's expectation from inspecting `ledger.py healthcheck`.
   ```

4. Operator applies for real:
   ```python
   runner.apply(MigrationCategory.LEDGER)
   # Appends N send_aborted events + 1 migration_event.
   ```

5. Re-runs `python scripts/doctor.py` → ledger/0001 is no longer pending.

6. Operator inspects the closed intents via:
   ```bash
   python orchestrator/ledger.py tail --type send_aborted -n 50
   ```
   Any intent that was closed but actually had a successful Gmail send becomes an operator manual-override case (emit a `manual_override` event with the rationale).

A CLI (`python -m orchestrator.migrations apply`) is deferred until per-category dispatchers stabilize (Week 4 policy + later weeks). Pillar I will likely ship the operator-friendly CLI as part of the OSS bring-up.

The migration is forward-only — operators who decide a closed intent should be re-opened emit a `manual_override` event referencing the affected `intent_id`. The reverse-mutation shape is application-level, not framework-level.

## References

- ADR-0001 (policy engine architecture) — the engine surface this framework parallels (rules → migrations).
- ADR-0004 (suppression rules + GDPR forget) — the `is_reversible=False` precedent for irreversible migrations; the tmp-then-rename atomicity precedent that the migration state file (not the ledger files) follows.
- ADR-0009 (migration framework foundation) — D1–D7 + the per-category-ADR-per-dispatcher convention this ADR fulfills.
- ADR-0011 (vault migrations) — D8–D13 + the helper-module dispatcher precedent this ADR mirrors for ledger.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies refuse-on-missing-ledger + close-by-fiat-with-`send_aborted`).
- `docs/PILLAR-PLAN.md` §1 — I1 (single source of truth: ledger), I2 (two-phase commit), I3 (schema versioning), I5 (observable by default), I6 (tests prove invariants).
- `docs/PILLAR-PLAN.md` §2 Pillar B — scope + exit criterion.
- `docs/SOURCES-OF-TRUTH.md` — "Send-history" row (ledger is SoT for "did we send"); this migration's `send_aborted` events preserve that invariant.
- `orchestrator/ledger.py` — the production ledger surface this ADR's helper delegates to. `Ledger.append` is the atomicity primitive every concurrent writer in the system shares.
- `orchestrator/reconcile.py` — the `send_confirmed_orphan` + `_recovered_by: "reconcile"` precedent this ADR generalizes for migrations.
- `orchestrator/backfill_ledger.py` — the Phase 5.5 backfill that uses `_recovered_by: "backfill"` for synthetic enrollment / send events. Wrapping this as a `Migration` instance is the Week 5–6 ADR-0013 deliverable; the shape composes with this ADR's contracts already.
- `orchestrator/migrations/ledger/_ledger_io.py` — `iter_events`, `append_event_atomic`, `emit_migration_event`, `latest_intent_outcome`, `events_by_type`.
- `orchestrator/migrations/ledger/migration_0001.py` — `CloseOrphanSendIntents`, `MIGRATION` module-level instance, `MIGRATION_ID`, `RECOVERED_BY_TAG` constants.
- `orchestrator/migrations/ledger/__init__.py` — `MIGRATIONS = [MIGRATION_0001_CLOSE_ORPHANS]`.
- `scripts/doctor.py:check_migrations` — surfaces ledger/0001 in the WARN-on-pending list (no code change — the existing implementation walks every category).
- `tests/test_migrations_ledger_io.py` — helper module tests (chronological walk, parsing tolerance, append atomicity under cross-process concurrency, reserved-field-collision check on `emit_migration_event`, etc.).
- `tests/test_migrations_ledger_0001.py` — migration tests (orphan closing, idempotence, dry-run no-op, `is_reversible=False` refusal, failure atomicity, runner integration).
- Forward-references:
  - **ADR-0012** — policy migrations (Week 4): surgical YAML rewrite, helper-module dispatcher, engine version-range coordination. **Accepted** 2026-05-20.
  - **ADR-0013** — synthetic-replay exit-criterion vehicle (Week 5 foundations + Week 6 exit gate). Wraps `backfill_identity.py` + `backfill_ledger.py` as `Migration` instances composing with this ADR's `_ledger_io.py` helpers (ADR-0013's `ledger/0002_backfill_send_history` emits the standardized `migration_event` per D17 with diagnostic fields `enrolled_emitted` / `sends_emitted` / `orphans_emitted` / `persons_without_id` / `touches_without_person_match`). **Accepted** 2026-05-21.
