# ADR-0017: Pillar C Week 4 — Reconcile Pass D (LinkedIn invites) + Pass E (LinkedIn DMs)

- **Status:** Accepted
- **Date:** 2026-05-21
- **Pillar:** C (Multi-channel coherence — Week 4)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar C Weeks 1-3 (ADRs 0014, 0015, 0016) shipped the LinkedIn dispatcher half of the two-phase commit shape: `gated_li_invite_one` (Week 2) writes `li_invite_intent` → `mcp__linkedin__connect_with_person` → `li_invite_confirmed | li_invite_failed`, and `gated_li_dm_one` (Week 3) writes `li_dm_intent` → `mcp__linkedin__send_message` → `li_dm_confirmed | li_dm_failed`. Both dispatchers stamp a deterministic intent-id marker (per ADR-0015 D39 zero-width-Unicode-wrapped token) into the connection-note text / DM body, so any later reader can correlate the LinkedIn-side record back to its originating intent.

Week 4 ships the **recovery half** — the LinkedIn-side analog of email's reconcile Pass A. Where Pass A walks `send_intent` events without matching outcomes, queries Gmail for the marker, and emits `send_confirmed | send_aborted`, Pass D + Pass E do the same thing against LinkedIn's two surfaces:

* **Pass D — Ledger ↔ LinkedIn invitations.** Walks `li_invite_intent` events without matching outcomes; queries the LinkedIn client's sent-invitations surface; matches the marker against connection-note text; emits `li_invite_confirmed` or `li_invite_aborted`.

* **Pass E — Ledger ↔ LinkedIn conversations.** Walks `li_dm_intent` events without matching outcomes; queries the LinkedIn client's recent-conversations surface; matches the marker against message body text; emits `li_dm_confirmed` or `li_dm_aborted`.

The five concerns Week 4 resolves:

1. **The two-phase commit shape needs a recovery vehicle on every channel.** Without Pass D + Pass E, a dispatcher crash between intent-write and MCP-call success leaves a stranded `li_invite_intent | li_dm_intent` event the indexer treats as "still in flight." The `last_send_for(person_id, channel="linkedin")` query returns None for the intent (it isn't a confirmed outcome), which fail-opens the dedup gate on the operator's next send attempt — biasing the asymmetric-failure-cost calculus in the wrong direction.

2. **Pass D and Pass E share the LinkedIn MCP rate-limit pool.** LinkedIn's MCP rate-limits at ~30 calls/minute on personal accounts. Running Pass D + Pass E concurrently compounds the rate-limit overhead — both calls land in the same per-minute bucket. D48 pins the serial-execution convention; concurrency belongs in Pillar H (the daemon) if needed.

3. **The marker-scan window is bounded by the LinkedIn surface's page-size convention.** LinkedIn's UI defaults to 100 items per page on both the sent-invitations + recent-conversations surfaces; the MCP backends typically respect the same convention. D49 pins the default scan limit at 100, matching the worst-case operator scenario of ~50 orphans across both action types within a 24h crash window.

4. **Marker-not-found semantics need a deliberate abort-after-grace policy.** When an intent is older than `RECONCILE_FRESH_MAX_AGE` AND the LinkedIn query doesn't surface a matching marker, the intent is presumed-failed. The asymmetric-failure-cost calculus (PILLAR-PLAN §0) favors abort over leave-orphan-stale — a recovered `_aborted` outcome lets the operator's next send attempt proceed via the normal dispatcher path. D50 instantiates the policy.

5. **Existing operators need the per-pass §"Existing-operator seed" entry.** Per the established ADR-0014 D36 + ADR-0015 D41 + ADR-0016 D46 convention, every per-Pillar-C ADR ships a §"Existing-operator seed" subsection. D51 carries the convention forward — reconcile passes have no ledger backfill of their own (they're operational, not migration-time), so the §"Existing-operator seed" subsection covers operator-facing rollout (when does reconcile run? how often? what happens on first invocation against a stale ledger?).

A sixth concern surfaces only on close inspection: **reconcile passes don't fit the migration-runner shape.** Per ADR-0009, migrations are versioned + applied-once + recorded in `migrations.state.json`. Reconcile passes are operational primitives — they run on a cadence (every hour for Pass A; less frequently for the others), each invocation reads + emits independently, and there's no migration-state file to update. The two are complementary: migrations close pre-Pillar-C orphans + backfill historical events; reconcile recovers ongoing dispatcher crashes. Pass D + Pass E are operational; Week 4 ships no migrations.

Risks this ADR mitigates by design:

* **R001 (silent data loss from dispatcher crashes between intent and outcome).** Without Pass D + Pass E, a crash between `li_invite_intent` write and `mcp__linkedin__connect_with_person` success leaves a stranded intent; the operator's next attempt fail-opens the dedup gate; the recipient receives a duplicate invitation. Pass D's abort-after-grace forecloses the duplicate-send path.

* **R002 (false-confirm from a delayed MCP response).** If the MCP response arrives after the dispatcher's crash + restart, Pass D reads the LinkedIn-side record + emits `li_invite_confirmed` retroactively — the operator's ledger reflects ground truth.

* **R011 (cross-channel double-engagement).** Pass D + E's `_aborted` events do NOT fire the cross-channel rule (per ADR-0003 the rule fires only on `_confirmed`). An over-aborted intent doesn't double-engage the recipient — the worst case is the operator's retry sees no prior confirmed outcome + proceeds normally; the recipient receives one (the retry's) outreach, not two.

## Decision

### D48. Pass D + Pass E run SERIALLY within a single reconcile invocation

Per the LinkedIn MCP's ~30 calls/minute rate-limit (shared across all surfaces on personal accounts), Pass D + Pass E execute serially — Pass D first, then Pass E — when both are requested in the same `reconcile(passes=...)` call. The orchestrator's pass-list iteration is the implementation mechanism (Pass D + E are sequential entries in the same loop; concurrent invocation would require explicit threading).

**Why serial and not concurrent.** Three reasons:

1. **Rate-limit amortization.** Each pass pre-fetches one batch (default 100 items per ADR-0017 D49); concurrent execution lands two MCP calls in the same per-minute bucket, halving the effective per-pass throughput. Serial execution lets each pass complete within ~2 calls (1 fetch + 1 per-orphan check fold-in) instead of doubling the bucket pressure.

2. **Simplicity + observability.** Serial execution is deterministic — the `reconcile()` result's pass-list reflects the actual execution order; an operator inspecting `~/.outreach-factory/reconcile/status.yml` sees Pass D's last-run-clean-ts before Pass E's. Concurrent execution requires per-pass instrumentation to disambiguate.

3. **Per-pass duration is bounded.** For an active operator with O(10) orphan intents across both action types, each pass completes in <5 seconds (one MCP fetch + per-orphan regex scan). Serial completion of both passes finishes in <10 seconds — well within the operator-tolerable reconcile-run window.

**Counter-argument: concurrent execution amortizes the per-minute window.** Yes — but the daemon (Pillar H concern) is the right home for per-stage parallelism if it's needed. A simple operational primitive that's deterministic + observable beats a clever one that's hard to debug.

#### D48-Alt1: Concurrent Pass D + Pass E via `concurrent.futures.ThreadPoolExecutor`

Spawn one thread per pass; both fire MCP calls in parallel. **Rejected** because:

* The LinkedIn MCP rate-limit pool is shared across surfaces; concurrent calls compound the per-minute pressure without yielding effective per-pass throughput gains.
* The aggregate `ReconcileResult` would need cross-thread synchronization (the pass-list is mutated by the threads); the added complexity isn't justified for a primitive that completes in <10 seconds serially.
* The operator-facing observability (per-pass last-run-clean timestamps in `status.yml`) would need per-pass locking on the YAML file; another complexity tax.

#### D48-Alt2: Run Pass D + Pass E in separate reconcile invocations (operator schedules each independently)

The operator runs `reconcile.py --passes D` + `reconcile.py --passes E` from separate cron jobs. **Rejected** because:

* The two passes are conceptually one operation ("recover all stranded LinkedIn intents"). Forcing the operator to schedule two independent cron entries is operator-hostile UX — the operator forgets to schedule one, half the LinkedIn-side recovery silently never happens.
* The status file's `last_run` map already tracks per-pass timestamps; a single invocation that runs both passes serially writes both timestamps coherently, while two separate invocations write them at different points in time + the operator-facing `--status` output becomes noisier.
* The `--full` mode's existing convention (Pass A + B + C in one call) generalizes to "all 5 passes in one call" by extending the default to A,B,C,D,E. The serial-within-one-invocation pattern is the operational primitive operators expect.

#### D48-Alt3: Interleave Pass D + Pass E (fetch invitations, then scan, then fetch conversations, then scan, then emit-all)

Pre-fetch both batches up-front + interleave the per-orphan marker-scan loops. **Rejected** because:

* Pre-fetching both batches up-front lands two MCP calls in the same per-minute bucket without the benefit of in-flight parallelism — same rate-limit overhead as D48-Alt1 modulo the threading.
* The per-pass marker-scan logic is distinct (Pass D scans `note` text on invitations; Pass E scans message bodies in conversations + filters by `from_self`); interleaving the scans would conflate the two passes' semantics for marginal performance gain.
* The pass-level observability story collapses (one combined pass-result vs two clean per-pass results); operator inspection becomes harder.

### D49. Marker-scan window — pre-fetch the most-recent 100 invitations / 100 conversations

`LINKEDIN_DEFAULT_SCAN_LIMIT = 100`. Pass D's `list_sent_invitations(limit=100)` + Pass E's `list_recent_conversations(limit=100)` each return up to 100 items per call. The marker-scan loop iterates the returned batch once per orphan intent; cumulative work is O(orphans × batch_size) — at most 10,000 string scans per pass, completing in <100ms even on a slow machine.

**Why 100 and not 50 / 250 / 500.** Three reasons:

1. **LinkedIn UI's default page size is 100.** Operators inspecting their LinkedIn sent-invitations or message inboxes via the LinkedIn UI see 100 items per page; the MCP backends typically respect the same convention (some allow up to 250, but 100 is the universal floor). Aligning the default with the UI page size gives operators predictable mental model: "what reconcile sees is roughly what I'd see if I scrolled the LinkedIn UI."

2. **The worst-case operator scenario is ~50 orphans across both action types within a 24h crash window.** Pillar C's expected operator throughput per ADR-0014: ~10-20 LinkedIn touches/day across both invites + DMs. A catastrophic 24h dispatcher outage produces ~10-20 orphans on each surface; 100 captures the worst case with 5× headroom.

3. **MCP rate-limit pressure scales with fetch frequency, not fetch size.** A single `limit=100` fetch counts as one MCP call against the per-minute bucket; the same call with `limit=10` or `limit=500` is also one call. Setting the limit at 100 minimizes the number of fetches needed under bursty conditions — if an operator has 50 orphans, one limit=100 fetch covers them; one limit=10 fetch would miss 40 of them.

**Why the scan_limit is parameterizable.** Operators with unusually high throughput (Pillar I OSS bring-up's per-tenant scale) can override via the CLI's `--linkedin-scan-limit` flag or the `reconcile(linkedin_scan_limit=...)` kwarg. The default is the safe shape for the dominant operator profile; the override gives the long-tail operators a tuning knob without forcing a fixture change.

**Edge case: operator with long-orphan situation (intent from a week ago + no MCP response).** The scan_limit=100 doesn't cover this case; the marker-not-found path per D50 fires + emits `_aborted`. The operator's retry re-enters via the normal dispatcher gate; if the intent eventually does resolve in LinkedIn's system (a delayed acceptance), the recipient sees the retry's duplicate. The risk is real but rare; mitigated by the asymmetric-failure-cost preference for abort-and-retry over leave-orphan-stale.

#### D49-Alt1: Scan window of 250 items (LinkedIn UI's max-page-size option)

Default to limit=250 to maximize per-fetch coverage. **Rejected** because:

* 250 isn't the universal MCP floor — some backends cap at 100; defaulting higher would fail-loud on some operator environments without any way to detect the cap without a probe call.
* The marker-scan loop's `O(orphans × batch_size)` work scales with batch_size; 2.5× the work for diminishing returns (the dominant operator profile has <50 orphans).
* The per-fetch MCP call still counts as one against the rate-limit bucket regardless of batch_size; the rate-limit advantage is fetch-frequency-dependent, not fetch-size-dependent.

#### D49-Alt2: Time-bounded scan window ("last 24h of invitations") instead of count-bounded

Use the MCP's `since` parameter (if available) to bound by time. **Rejected** because:

* Not all LinkedIn MCP backends expose a `since` parameter on the sent-invitations or recent-conversations surfaces; the count-bounded approach is universally supported.
* Operator dispatcher crashes are uncorrelated with time-of-day; a count-bounded window naturally covers the recent activity regardless of clock skew.
* Time-bounded would require the operator to estimate crash recovery latency in absolute time ("how old can my orphans be?") — a less natural concept than "how many recent items should reconcile scan?".

#### D49-Alt3: Per-orphan MCP query (no batch fetch; one fetch per orphan with intent_id filter)

For each orphan, call `list_sent_invitations(filter=intent_id)`. **Rejected** because:

* The MCP surfaces don't expose a `filter=intent_id` query — the marker is embedded in note text, not exposed as a queryable field.
* Per-orphan MCP calls would multiply rate-limit pressure linearly with orphan count — 10 orphans → 10 MCP calls; the batch-fetch approach handles them in 1.
* The batch approach is the operationally-correct shape: pre-fetch once, scan in-memory, emit. Per-orphan would be the textbook anti-pattern.

### D50. Marker-not-found semantics — abort after `RECONCILE_FRESH_MAX_AGE`

When an `li_invite_intent | li_dm_intent` event is older than `min_intent_age` (default 5 minutes; the same threshold Pass A uses for `send_intent`) AND the LinkedIn batch fetch returns no item whose marker matches the intent_id, Pass D / Pass E emit a `_aborted` event with:

* `type`: `li_invite_aborted` (Pass D) or `li_dm_aborted` (Pass E)
* `intent_id`: the orphan's intent_id
* `person_id`: carried forward from the intent
* `channel`: `"linkedin"` (per ADR-0014 D33 invariant)
* `_recovered_by`: `"reconcile"` (per ADR-0010's convention)
* `reason`: `no_linkedin_invitation_match_after_<seconds>s` (Pass D) / `no_linkedin_dm_match_after_<seconds>s` (Pass E) — names the abort cause + the threshold for debugging

**Why abort instead of leave-open.** Three reasons:

1. **Asymmetric failure cost (PILLAR-PLAN §0).** An orphan intent left open is silently invisible to the indexer's `last_send_for(person_id, channel="linkedin")` query — the dedup gate fail-opens; the operator's retry sends a second copy; the recipient gets two outreaches. An aborted intent is recovered: the indexer sees `li_invite_aborted` (a non-confirmed outcome that doesn't fire the cross-channel rule), the dedup gate allows the retry, the retry emits a fresh `li_invite_intent` + Mcp call, the recipient gets one outreach.

2. **Operator-facing observability.** An open intent has no operator-facing surface — the operator can't see it without `python -m orchestrator.ledger healthcheck` (which surfaces opens >24h, not 5min). An aborted intent shows up in the funnel: `cooldown_blocked`-shaped diagnostics + Pillar G's per-channel dashboard. The operator gets a signal something happened.

3. **The `_aborted` event composes correctly with reconcile-Pass-A's retroactive-confirm semantics.** If an MCP-delayed confirmation arrives AFTER the abort (within the scan_limit window in the future), Pass D would re-find the matching invitation, but the indexer already has an aborted outcome for the intent_id — the duplicate confirm is silently skipped (the index's "chronologically last outcome wins" rule applies; a confirmed-after-aborted is acceptable per the append-only ledger semantics + the rule's idempotence + the cross-channel rule's `_confirmed`-only firing). The worst case is a fresh `li_invite_intent` from the operator's retry + a re-confirmed original — both legitimate two-phase commits, no duplicate engagement.

**Why min_intent_age=5min (not 1min / 60min).** Three reasons:

1. **The 5-minute threshold matches Pass A's convention.** Operationally identical to the email-side recovery window; the cross-channel parity preserves operator mental model.

2. **The MCP's typical round-trip latency is <10 seconds.** A 5-minute window comfortably exceeds the 99th-percentile MCP completion time; intents younger than 5 minutes are statistically likely to still be in-flight rather than stranded.

3. **The grace window favors the recover-late path over the abort-early path.** Aborting at 1 minute would catch in-flight intents (false-positive abort); aborting at 60 minutes would leave orphans stranded for an hour after a crash. 5 minutes is the empirically-validated middle ground.

#### D50-Alt1: Leave orphans open indefinitely; rely on operator-manual recovery via `python -m orchestrator.ledger healthcheck`

The reconcile passes never emit `_aborted`; orphans accumulate until the operator runs healthcheck + manually closes them. **Rejected** because:

* The dedup gate's fail-open behavior on open orphans causes silent duplicate-send risk; manual healthcheck is operator-burden the framework should foreclose.
* Pillar H's daemon and Pillar I's CLI don't have a "fix the orphans" operator surface ready in Week 4; the manual-recovery path doesn't exist yet.
* The healthcheck output (a flat list of orphan intent_ids per `python -m orchestrator.ledger healthcheck`) is debugging-only; it has no remediation path.

#### D50-Alt2: Abort immediately (`min_intent_age=0`); no grace window

The pass aborts every unmatched intent on the first scan, regardless of age. **Rejected** because:

* The MCP's <10s typical latency means in-flight intents would be aborted as false-positives.
* The retry-after-abort pattern would create churn: dispatcher writes intent → reconcile aborts (false-positive) → dispatcher retries → reconcile aborts again → ...; the operator would observe a never-completing dispatcher.

#### D50-Alt3: Emit `_failed` instead of `_aborted` when marker isn't found

Use `li_invite_failed | li_dm_failed` for the recovery path. **Rejected** because:

* `_failed` semantically means "we know the send didn't reach the human" — the dispatcher's MCP call raised an exception. Reconcile doesn't have that knowledge — the MCP call may have succeeded but the dispatcher crashed before writing the outcome. `_aborted` is the correct semantic: "we don't know what happened; abandoning the intent."
* The cross-channel rule's downstream behavior differs: `_failed` events stay in the ledger as historical records; `_aborted` events explicitly mean "this intent was abandoned; the operator's retry is safe."
* Pillar G's per-channel dashboards distinguish failed (dispatcher-side error) from aborted (reconcile-side recovery); conflating the two would lose diagnostic resolution.

### D51. Existing-operator seed for reconcile Pass D + Pass E

Reconcile passes are operational primitives, not migrations — they have no `mark_applied`-style seed instruction (no state file entry to set). The per-Pillar-C-ADR §"Existing-operator seed" convention adapts to reconcile by naming the operator-facing rollout posture instead:

#### When does reconcile run? How often?

Operators choose between two execution modes:

* **Manual (Pillar I OSS bring-up's day-1 mode).** `python orchestrator/reconcile.py --quick` (Pass A only) or `--full` (all 5 passes, A+B+C+D+E). The operator schedules cron entries themselves; default cadence: `--quick` hourly + `--full` daily.

* **Daemon-managed (Pillar H, future).** The Pillar H daemon's per-stage parallelism includes a reconcile worker that fires `--quick` on a continuous loop + `--full` on a daily schedule.

#### First-invocation against a stale ledger

An operator who has been running Weeks 2 + 3 dispatchers WITHOUT reconcile may have accumulated stranded LinkedIn intents from past crashes. The first `--full` (or first `--passes D,E`) invocation under Week 4 will:

* Walk every `li_invite_intent` + `li_dm_intent` in the window (default 30d for `--full`) without a matching outcome.
* Query LinkedIn for the marker (one batch each per pass).
* For markers found in the recent-100 window: emit `_confirmed` retroactively (the recipient has the message; the indexer now agrees).
* For markers not found AND intent older than 5 minutes: emit `_aborted`.

The aggregate effect is a one-time recovery wave: the operator sees a flurry of `li_invite_confirmed` / `li_invite_aborted` / `li_dm_confirmed` / `li_dm_aborted` events in their first Week-4 reconcile-run logs. Subsequent runs are quiet (only recovers crashes since the last run).

#### Recommended posture per operator profile

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero pre-Pillar-C LinkedIn history) | Run `--full` manually after `git pull`; daemon-managed thereafter. The first run emits at most the small set of orphans from the operator's initial dispatcher exercise. |
| Existing operator (Yang as of 2026-05-21) with Weeks 2 + 3 dispatcher history | Run `--passes D,E --apply` once manually to catch up the historical orphans; then `--full` daily. Yang's stranded-orphan count should be small (no documented dispatcher crashes; the orphans recovered are mostly idiomatic "MCP failed silently"). |
| Operator using a non-MCP LinkedIn client (programmatic API directly) | Inject a custom `LinkedInClientLike` via the `reconcile(linkedin=...)` kwarg; the protocol's two methods accommodate any client surface. The CLI's `_build_linkedin_adapter()` shim is the operator's hook (lives in `skills/send-outreach/scripts/linkedin_client.py` — a Pillar I OSS bring-up concern). |
| Operator who wants Pass D + Pass E disabled (LinkedIn surface unavailable / opt-out) | Omit `D,E` from the `--passes` argument: `reconcile.py --passes A,B,C` runs the email + vault passes; LinkedIn passes are skipped. The operator-deliberate omission is honored. |

#### Why no `mark_applied`-style seed for reconcile

Reconcile passes are idempotent across invocations — running them multiple times is safe. There's no per-Pillar-C reconcile state to preserve; the operator's existing pre-Pillar-C LinkedIn ledger state passes through Pass D + Pass E identically on every run (intents with matching outcomes are skipped; intents without outcomes are healed). The migration-runner's `mark_applied` semantics don't apply.

### D52. Downstream pillar impact

Per the ADR-0009 / 0010 / 0011 / 0012 / 0013 / 0014 / 0015 / 0016 convention:

* **Pillar D (reply + conversation handling).** Pass E's `li_dm_confirmed` events stamp `linkedin_thread_id` when the LinkedIn conversation surface returns one. Pillar D's reply joiner correlates `li_dm_reply_received` events (per ADR-0025 D96's per-channel-prefixed naming convention; supersedes the generic `reply_received` placeholder this paragraph used pre-ADR-0025) to `li_dm_confirmed` by both `intent_id` AND `linkedin_thread_id` — same pattern as Pass D's `linkedin_invitation_id`. The `_recovered_by: "reconcile"` field on Pass E emissions lets Pillar D's joiner distinguish reconcile-emitted confirmations from dispatcher-emitted ones (relevant for surfaces that care about authentication of the confirmation path).

* **Pillar E (discovery quality + lineage).** No direct interaction. Pass D + Pass E operate on send-side events; Pillar E's `discovery_lineage:` blocks are pre-send. The cross-pillar query is one ledger join, no Pillar C schema change.

* **Pillar F (voice corpus + draft quality).** No direct interaction. Pillar F's voice-fidelity scoring is dispatcher-time (pre-MCP-call); reconcile recovers post-MCP-call. The `_recovered_by: "reconcile"` field on emissions has no voice-scoring implication.

* **Pillar G (observability).** Pillar G's per-channel funnel dashboard reads `li_invite_aborted` + `li_dm_aborted` events filtered by `channel="linkedin"` per ADR-0014 D33 + `_recovered_by="reconcile"` per ADR-0010's convention. The per-pass last-run-clean timestamp in `~/.outreach-factory/reconcile/status.yml` is the per-pass health indicator Pillar G's dashboard surfaces. Reconcile error counts (per `result.errors`) become per-pass error-rate metrics; a sustained spike in Pass D errors signals the LinkedIn MCP surface is unhealthy.

* **Pillar H (daemon + dispatcher).** Pillar H's daemon runs reconcile on a continuous-loop cadence: `--quick` every N minutes (default 5; matches Pass A's existing convention) + `--full` daily. The serial-execution convention per D48 informs the daemon's per-stage parallelism budget: the LinkedIn passes (D + E) run on a dedicated reconcile worker, not parallel to the dispatcher (otherwise they'd compete for the same MCP rate-limit bucket).

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel state isolation. The reconcile primitive accepts injected `LinkedInClientLike` adapters — Pillar I OSS bring-up ships a reference adapter (`skills/send-outreach/scripts/linkedin_client.py::build_reconcile_adapter`) that wraps the MCP surface; multi-tenant deployments inject per-tenant clients. The CLI's `--linkedin-scan-limit` flag is operator-tunable; the per-tenant override surfaces as a Pillar I config field.

* **Pillar J (security + compliance).** GDPR-forget on a Person who has LinkedIn invite / DM aborted events: the `_aborted` events are tombstoned per the same pattern as `_confirmed` events. The `linkedin_invitation_id` / `linkedin_thread_id` fields are potentially-PII; Pillar J's forget tooling redacts them on tombstone (same shape as ADR-0016 D47's DM tombstoning).

## Alternatives considered

### D48-Alt1: Concurrent Pass D + Pass E via `concurrent.futures.ThreadPoolExecutor`

See D48 above. Rejected for rate-limit, observability, and complexity reasons.

### D48-Alt2: Run Pass D + Pass E in separate reconcile invocations

See D48 above. Rejected because the operator-facing scheduling is more error-prone than the all-in-one default.

### D48-Alt3: Interleave Pass D + Pass E with combined fetch-then-scan loops

See D48 above. Rejected because the scan semantics differ between passes (notes vs message bodies + from_self filter).

### D49-Alt1: Scan window of 250 items

See D49 above. Rejected because not every MCP backend supports limit=250 and the marginal coverage gain is small.

### D49-Alt2: Time-bounded scan window via the MCP's `since` parameter

See D49 above. Rejected because the parameter isn't universally supported.

### D49-Alt3: Per-orphan MCP query

See D49 above. Rejected as the textbook anti-pattern (multiplies rate-limit pressure linearly).

### D50-Alt1: Leave orphans open indefinitely; rely on operator-manual recovery

See D50 above. Rejected because dedup gate fail-open behavior would cause silent duplicate sends.

### D50-Alt2: Abort immediately (no grace window)

See D50 above. Rejected because the false-positive abort rate on in-flight MCP calls would create dispatcher-retry churn.

### D50-Alt3: Emit `_failed` instead of `_aborted` when marker isn't found

See D50 above. Rejected because the semantic distinction matters for Pillar G's diagnostic resolution.

### D51-Alt1: Ship a `vault/0005_initialize_reconcile_state` migration to record first-run timestamp

A migration that stamps `~/.outreach-factory/reconcile/status.yml` with a baseline last-run-clean timestamp. **Rejected** because:

* Reconcile passes are operational, not migration-time; no migration semantics apply.
* The status file's existing schema accommodates first-time initialization automatically (the `_load_status` function returns `{"last_run": {}, "last_results": {}}` on absence).
* Operators who manually edit the status file get the same effect; a migration would add complexity without operator-visible benefit.

### D51-Alt2: Auto-discover stale orphans + refuse to run Pass D until operator confirms recovery scope

The first `--full` invocation detects pre-Week-4 orphans + prints a "Y/N: proceed?" prompt. **Rejected** because:

* The interactive prompt deadlocks non-interactive contexts (daemon, cron).
* Pass D + Pass E are idempotent — running them safely is the default; an interactive guardrail would be friction for the safe operation.

### D51-Alt3: Combine Pass D + Pass E's §"Existing-operator seed" into a single Pillar C reconcile section

Treat both passes as one §"Existing-operator seed" entry. **Accepted in spirit (D51 covers both)** — but the per-pass distinction matters for operator inspection (the per-pass last-run timestamp in `status.yml` is separate). The single combined seed section documents both; the per-pass status file is per-pass.

### D52-Alt1: Defer the §Downstream pillar impact section to a future ADR

Skip it in Week 4; cover in Pillar D's ADR. **Rejected** by the established ADR-0009-onwards convention; every Pillar C ADR ships the section to give downstream pillars a forward-references contract.

### D52-Alt2: Combine D52 with ADR-0014 D33's §Downstream pillar impact (cross-week aggregation)

Treat the per-week §Downstream impact sections as cumulative; Week 4's references are additive to Week 1's. **Rejected** because the per-ADR section gives readers a per-week scope without requiring a multi-ADR read-through; the cumulative pattern would be hidden context.

### D52-Alt3: Defer the Pillar D / E / F sections; only document G / H / I / J (where Pass D + E touch directly)

Skip the downstream sections for pillars that don't interact directly. **Rejected** by the established convention — every per-Pillar-C ADR documents every downstream pillar so future readers see the explicit "no interaction" rather than ambiguous absence.

## Existing-operator seed

See D51 above for the full operator-facing posture + recommended first-invocation flow + per-operator-profile table. Reconcile passes have no `mark_applied`-style seed (they're operational, not migrational); the seed entry covers when-and-how-often-to-run + the first-invocation-against-a-stale-ledger semantics.

## Dry-run interaction

Per ADR-0013 D24-N + the ADR-0014 / 0015 / 0016 inheritance pattern, dry-run interaction for reconcile passes works as follows:

* `reconcile.py --dry-run --passes D,E` runs both passes' read paths (intent enumeration + LinkedIn batch fetch + marker scan) WITHOUT writing any `_confirmed | _aborted` events to the ledger. The result reports the would-emit events with `_dry_run: True` markers.
* `reconcile.py --apply --passes D,E` is the operational write path. Per the existing `--quick` / `--full` mode conventions, mode-default-apply applies; explicit `--dry-run` always wins.
* Dry-run still calls the LinkedIn MCP (the marker-scan is read-only by definition). Operators who want zero MCP traffic should omit the passes from the `--passes` argument.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. Pass D + Pass E read the ledger as authoritative (per the "Send-history" SoT); the LinkedIn surface is a recovery probe, not an SoT. The `_recovered_by: "reconcile"` field on emissions denormalizes the recovery source for observability.
- **I2 (two-phase commit on every external side effect):** Reconcile is the recovery vehicle for I2's two-phase shape on the LinkedIn channels. Pass D + Pass E heal crashes between intent-write and MCP-call success; the recovery emissions (`_confirmed | _aborted`) close the two-phase commit cleanly.
- **I3 (schema versioning):** No new event-schema versions introduced. Pass D + Pass E emit existing per-channel outcome types (`li_invite_confirmed | li_invite_aborted | li_dm_confirmed | li_dm_aborted`) per ADR-0014 D33's catalog.
- **I4 (reproducible state):** Reconcile passes are idempotent — running them multiple times produces identical results (the indexer's outcome-for-intent check prevents duplicate emissions). The emission shape is deterministic per the intent's existing fields.
- **I5 (observable by default):** Per-pass result counts in the `ReconcileResult.passes[].summary()` output; per-pass last-run-clean timestamps in `~/.outreach-factory/reconcile/status.yml`. The `--json` CLI flag emits machine-readable per-pass diagnostics for Pillar G dashboard integration.
- **I6 (tests prove invariants):** `tests/test_reconcile_li_invite.py` (23 tests) + `tests/test_reconcile_li_dm.py` (24 tests) cover happy path + execution + channel discipline + failure modes + orchestration integration per pass. `tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel::test_li_invite_aborted_for_orphan_intent` + `TestLinkedInDMChannel::test_li_dm_aborted_for_orphan_intent` exercise the end-to-end recovery against the synthetic fixture's orphan substrate.
- **I7 (cost is a first-class concern):** Reconcile passes don't emit `cost_incurred` events — the MCP calls they make are read-only + cheap. The per-pass batch-fetch convention per D49 amortizes the MCP rate-limit cost; concurrent execution per D48-Alt1 would have compounded the cost (rejected for that reason).
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains an ADR-0017 row. The Week 4 commit's per-week handoff document (`.planning/HANDOFF-pillar-c-week-4.md`) scoped the deliverables.

Does not weaken any invariant. I2's recovery guarantee strengthens for the LinkedIn channels (previously Weeks 2 + 3 shipped the forward path only; Week 4 closes the loop).

## Migration / rollout

Week 4 ships zero new migrations (reconcile is operational, not migration-time). The deliverable is purely orchestrator-side code + tests + this ADR.

**Operator-facing changes:**

1. **`runner.pending()` is unchanged at 8.** No new migrations.

2. **CLI extends: `python orchestrator/reconcile.py --full` now runs all 5 passes (A,B,C,D,E) by default.** Operators who want the prior 3-pass behavior pass `--passes A,B,C` explicitly. The new default is the operator-facing breaking change of Week 4; the rollout doc above (D51) names it.

3. **A new CLI flag `--linkedin-scan-limit N` (default 100) tunes the marker-scan batch size per D49.** Default works for the dominant operator profile; long-tail operators with high throughput can override.

4. **First-invocation against a stale ledger emits a recovery wave** per D51. Operators see a flurry of `_confirmed` / `_aborted` events in their first Week-4 reconcile run; subsequent runs are quiet.

5. **A new LinkedIn-adapter shim is required for production CLI invocation of Pass D / E** — `skills/send-outreach/scripts/linkedin_client.py::build_reconcile_adapter`. Without it, the CLI records "Pass D requires a LinkedIn client" + skips the pass (same shape as Pass A's missing-Gmail error). Pillar I OSS bring-up will ship the reference adapter; until then, programmatic callers inject a fake (e.g. `FakeLinkedIn` in `tests/test_reconcile_li_invite.py`).

**The Week 4 commit's verification surface:**

```bash
# 1. No new migrations.
$ python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print(len(r.pending()))"
8

# 2. Pass D + Pass E tests pass.
$ python -m pytest tests/test_reconcile_li_invite.py tests/test_reconcile_li_dm.py -v
# Expected: 47 passed (23 Pass D + 24 Pass E).

# 3. The previously-skipped coherence rows un-skip and pass.
$ python -m pytest tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel::test_li_invite_aborted_for_orphan_intent tests/test_multi_channel_coherence.py::TestLinkedInDMChannel::test_li_dm_aborted_for_orphan_intent -v
# Expected: 2 passed.

# 4. Both LinkedIn channel test classes have 6 of 6 rows running.
$ python -m pytest tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel tests/test_multi_channel_coherence.py::TestLinkedInDMChannel -v
# Expected: 12 passed, 0 skipped in this class subset.

# 5. The full suite is green at +49 tests (1271 + 49 = 1320 passing).
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q

# 6. ADR-0017 exists; README index gains the row; PILLAR-PLAN §6 Pillar C
#    row updated to reflect Week 4 ship.
$ ls docs/adr/0017-pillar-c-reconcile-passes-d-e.md
$ grep "0017" docs/adr/README.md
$ grep "Week 4" docs/PILLAR-PLAN.md
```

## References

- ADR-0001 (policy engine architecture) — `RuleContext.channel` field; reconcile-emitted `_aborted` events don't fire the cross-channel rule (the rule fires only on `_confirmed`), so over-aborts are safe.
- ADR-0003 (channel as first-class policy predicate) — the `CrossChannelTouchRule` Pass D + Pass E's emissions integrate against. The `_aborted` semantics don't fire the rule per ADR-0003's `type.endswith("_confirmed")` predicate.
- ADR-0009 (migration framework) — reconcile passes are operational primitives, NOT migrations; D51 names the distinction.
- ADR-0010 (ledger migrations) — D14 append-only invariant (reconcile emissions are append-only); D15 idempotence (reconcile passes are idempotent across invocations); the `_recovered_by: "reconcile"` field convention.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — D24-N dry-run interaction (reconcile dry-run reports without writing); D32 per-ADR existing-operator seed pattern (D51 adapts for reconcile's operational shape).
- ADR-0014 (Pillar C foundation) — D33 channel event-type naming convention (Pass D + E emit `li_invite_aborted | li_dm_aborted` per the convention); D36 per-ADR seed pattern.
- ADR-0015 (Pillar C Week 2 — LinkedIn invite) — D39 zero-width-Unicode marker (Pass D reads back what the dispatcher wrote); D41 per-migration seed pattern; D42 per-week per-channel rollout template.
- ADR-0016 (Pillar C Week 3 — LinkedIn DM) — D43 reaffirms D39's marker shape for DMs (Pass E reads back); D44 requires-existing-connection gate (Pass E does NOT re-check connection state on recovery — reconcile recovers crashes, doesn't re-send); D46 per-migration seed pattern.
- `docs/PILLAR-PLAN.md` §2 Pillar C — exit criterion (binding text); §6 Pillar C row updated to reflect Week 4 ship.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D50's abort-after-grace posture.
- `docs/RISK-REGISTER.md` R001 (dispatcher crash between intent and outcome) — risk this ADR mitigates by design via Pass D + Pass E recovery.
- `docs/RISK-REGISTER.md` R002 (false-confirm from delayed MCP response) — risk this ADR mitigates via retroactive confirm on marker match.
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — risk this ADR mitigates by design via `_aborted` events not firing the cross-channel rule.
- `docs/SOURCES-OF-TRUTH.md` — reconcile reads the ledger as authoritative; LinkedIn is a recovery probe.
- `.planning/HANDOFF-pillar-c-week-3.md` — the prior week's handoff documenting Week 3's deliverables.
- `.planning/HANDOFF-pillar-c-week-4.md` — the handoff that scoped this commit's deliverables.
- `.planning/HANDOFF-pillar-c-week-5.md` — the next week's handoff scoping the Twitter DM dispatcher + reconcile Pass F.
- `orchestrator/reconcile.py` — `run_pass_d` + `run_pass_e` + `LinkedInClientLike` Protocol + shared `_run_linkedin_intent_pass` core.
- `orchestrator/ledger.py` — `_OUTCOME_TYPES` + `_INTENT_TYPES` + `_CONFIRMED_TYPES` already include `li_invite_aborted | li_dm_aborted` per Week 1's generalization; Week 4 ships the events.
- `orchestrator/policy/cross_channel.py` — the rule class Pass D + Pass E's `_confirmed` recoveries fire; the rule's `_confirmed`-only predicate ensures `_aborted` recoveries don't fire (no double-engagement risk).
- `skills/send-outreach/scripts/send_queued.py` — `gated_li_invite_one` + `gated_li_dm_one` (Weeks 2 + 3); their intent-id markers are what Pass D + Pass E read back.
- `tests/test_reconcile_li_invite.py` — Pass D's 23 direct unit tests.
- `tests/test_reconcile_li_dm.py` — Pass E's 24 direct unit tests (imports FakeLinkedIn from Pass D's test module).
- `tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel::test_li_invite_aborted_for_orphan_intent` — un-skipped Week 4 (was skipped pre-Week-4; verifies Pass D against the fixture's orphan).
- `tests/test_multi_channel_coherence.py::TestLinkedInDMChannel::test_li_dm_aborted_for_orphan_intent` — un-skipped Week 4 (was skipped pre-Week-4; verifies Pass E against the fixture's orphan).
- `tests/fixtures/synthetic_pillar_b/ledger/events-2026-04-15.jsonl` — extended Week 4 with two orphan intents (Carol's `li_synthetic_orphan_invite_01` + Dana's `lidm_synthetic_orphan_dm_01`) — substrate for the coherence tests.
- Forward-references (planned):
  - **ADR-0018** (Pillar C Week 5): Twitter DM dispatcher + reconcile Pass F (Twitter DM orphan recovery). Same shape as Pass D + Pass E with a Twitter-specific MCP surface.
  - **ADR-0019** (Pillar C Week 6): Calendar booking dispatcher + Cal.com webhook + reconcile Pass G (calendar-booking orphan recovery; the webhook surface may obviate the need for a periodic reconcile pass — see ADR-0019's planned analysis).
  - **Pillar H daemon** (Weeks 31–36): per-stage parallelism for reconcile-on-cadence; the serial-execution convention per D48 informs the per-LinkedIn-pass worker budget.
  - **Pillar I OSS bring-up** (Weeks 43–48): the `LinkedInClientLike` reference adapter (`skills/send-outreach/scripts/linkedin_client.py::build_reconcile_adapter`); per-tenant adapter injection; the `--linkedin-scan-limit` flag's per-tenant override surface.
