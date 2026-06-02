# ADR-0034: Pillar E Week 4-5 — email-verification cache primitive

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** E (Discovery quality + lineage — Week 4-5 email-verification cache primitive)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0032 (Pillar E Week 1 foundation) pinned the discovery-lineage shape (D142), the pre-enrichment dedup contract (D143), the email-verification cache shape (D144), the tier auto-assignment substrate (D145), the cross-pillar surface audit (D146), the exit-criterion vehicle scope (D147), and the privacy-respecting invariant (D148). ADR-0033 (Pillar E Week 2) shipped the dedup primitive module (`orchestrator/discovery_dedup.py`) + the per-skill integration in `find-leads`; the Week 3 amendment (2026-05-24) extended per-skill integration to `find-funded-founders` (Phase 4f) + `competitor-customers` (Phase 3e). The Week 2 commit shipped 35 new dedup primitive unit tests + 4 un-skipped coherence rows; the Week 3 commit un-skipped the cross-skill three-credit subset of the binding exit-criterion.

**Pillar E Week 4-5 is the email-verification cache primitive.** The handoff (`.planning/HANDOFF-pillar-e-week-4.md` — committed in the Week 3 follow-up) scopes Week 4-5 to: (a) the cache primitive's foundation module + emit-shape factory + ledger-as-substrate derivation semantics; (b) the per-call-site integration in `orchestrator/enrich_emails.py` (single call site — structurally simpler than the dedup primitive's four-skill integration); (c) the cross-pillar audit row extension naming the new event class's consumer surface; (d) the un-skip of all 4 `TestEmailVerificationCache` coherence rows. The split — cache primitive in Week 4-5 + tier-suggestion primitive deferred to Week 6-8 + per-skill lineage stamping deferred to Week 9-11 — bounds each week's failure radius: a cache-primitive bug in Week 4-5 is one Python module + its tests + one call-site wrap; a multi-pillar rework at Week 9-11 would compound risk.

The six concerns this ADR resolves:

1. **The cache primitive module's PLACEMENT must be pinned before the implementation lands.** Three plausible homes: (a) `orchestrator/email_verification_cache.py` (top-level, sibling of `enrich_emails.py` + `discovery_dedup.py`); (b) inside `orchestrator/enrich_emails.py` (conflates cache-as-prevention with verification-as-action); (c) inside `orchestrator/ledger.py` (conflates cache-as-derivation with ledger-as-substrate); (d) a new `orchestrator/cache/` subpackage (over-organization for one module in Week 4-5). D154 picks (a). The placement mirrors ADR-0033 D149's sibling-of-existing-primitives shape — the cache primitive IS a Pillar E primitive in its own right.

2. **The `email_verification_cache_hit` event class's EMIT-SHAPE must be pinned per the channel-on-every-event invariant + the cache-hit-REPLACES-cost-incurred contract.** Per ADR-0032 D144 + D146 the event carries `channel: "email"` (the cache is email-channel-specific — contrasts with the dedup primitive's `channel: "none"`); per D144 the cache hit emits the new event class INSTEAD of `cost_incurred` (co-emission would double-count). The Pillar G dashboard filtering by channel must surface cache hits on the email channel; the cost-avoidance aggregation must read `cache_hit_count / (cache_hit_count + cost_incurred.source=reoon_count)`. D155 pins the field shape + the operator-readable `_emitted_by: "email_verification_cache"` marker.

3. **The cache SUBSTRATE must derive from existing ledger state to preserve I1.** Per ADR-0032 D144 the cache is a derived view of `cost_incurred.source=reoon` events — no separate cache file; the ledger IS the cache. But the current `emit_reoon_cost_event` doesn't carry the `email` + the `verification_response` fields needed to RECONSTRUCT the cache at lookup time. D156 extends the cost event content-additively with these two fields. Pre-Pillar-E-Week-4 cost events lacking the fields are invisible to the cache (treated as miss); the existing-operator seed populates the cache from the next Reoon call forward.

4. **The TTL SEMANTICS must be pinned at a documented default.** Per ADR-0032 D144 the cache TTL is 30 days — Reoon's official accuracy guarantee bound. D157 pins the constant + the inclusive-lower-bound semantics (matches the cooldown / budget rule convention per ADR-0002 + ADR-0006).

5. **The per-call-site INTEGRATION must be pinned at the wrap layer.** Per ADR-0032 D143's atomicity contract the cache primitive is the FAST-PATH for the common case; the cache hit short-circuits the Reoon HTTP call + emits the cache_hit event; the cache miss falls through to the existing Reoon path UNCHANGED. D158 pins the integration site (`orchestrator/enrich_emails.py::verify_with_reoon`) + the content-additive wrap discipline (existing call signature preserved; new optional kwargs `led` / `person_id` / `run_id` enable the cache prelude).

6. **The cross-pillar surface audit (per ADR-0032 D146) MUST be extended row-by-row each Pillar E week.** Week 4-5 ships the `email_verification_cache_hit` event class — it lands in `_idx_person` when the cache hit carries `person_id` (broadens the per-Person index for every consumer). The audit must verify each consumer is either closed-set-protected or by-design-broadening. D159 names the audit extension.

Risks this ADR mitigates by design: **R001 (identity-graph false-merge cascade)** is not regressed — the cache primitive operates on emails (not identity keys); no identity-resolution semantics change. **R020 (email-verification cache staleness)** named in ADR-0032 §Context is mitigated structurally: the 30-day TTL bounds the staleness window per Reoon's documented accuracy guarantee; operator eviction via Pillar I CLI is the deferred recovery surface; the existing `bounce_detected` Pass B flow naturally surfaces stale-cache failures (a cache hit returning `safe` for an email that subsequently bounces produces an operator-visible bounce event). The asymmetric-failure-cost calculus per PILLAR-PLAN §0 carries: a false-positive cache hit (stale `safe` outcome for a now-invalid email) is one bounce in production (operator-visible; corrective via Pillar I evict); a false-negative cache miss (no hit when a hit would have been valid) is one extra Reoon credit ($0.005) — the failure costs are bounded + asymmetric in the operator-friendly direction.

No new risk surfaces in this ADR's authoring. R001 + R018 + R019 + R020 (all named in ADR-0032 §Context) carry the design-time mitigation forward; the Week 4-5 implementation does not introduce new risk classes.

## Decision

### D154. Cache primitive module placement — `orchestrator/email_verification_cache.py`

The cache primitive ships as a single top-level module under `orchestrator/`, sibling of `enrich_emails.py` + `discovery_dedup.py` + `enrollment.py` + `identity.py`:

```
orchestrator/
├── email_verification_cache.py    ← NEW (Pillar E Week 4-5)
├── discovery_dedup.py             ← Pillar E Week 2 (the SIBLING primitive)
├── enrich_emails.py               ← Pillar A Week 4 (the WRAPPED call site)
├── enrollment.py                  ← Pillar 5.5 Week 1b
├── identity.py                    ← Pillar 5.5 Week 1b
├── reply_classifier.py            ← Pillar D Week 2 (sibling-primitive precedent)
├── ledger.py
├── reconcile.py
└── ...
```

**The cache primitive is a Pillar E primitive, not a sub-helper of `enrich_emails.py`.** Like the dedup primitive (per ADR-0033 D149), the cache primitive PRODUCES events (it emits `email_verification_cache_hit` on hit; the wrap inside `verify_with_reoon` orchestrates the dispatch). The placement-as-pillar-primitive matches `discovery_dedup.py`'s shape — both are pre-action-decision wrappers around an existing Pillar A/B/C/D surface.

**Top-level placement matches the existing per-primitive convention.** `orchestrator/ledger.py` + `orchestrator/reconcile.py` + `orchestrator/identity.py` + `orchestrator/enrollment.py` + `orchestrator/reply_classifier.py` + `orchestrator/discovery_dedup.py` are each single-file pillar primitives. The cache primitive follows the same shape. An `orchestrator/cache/` subpackage would be over-organization for Week 4-5's ~500 LOC; the subpackage rationale resurfaces in a future Pillar E week IF a second cache primitive lands (e.g., an Apollo-organization-enrichment cache) — TBD.

**Why NOT inside `enrich_emails.py`?** Conflates cache-as-prevention with verification-as-action. `enrich_emails.py` today is the dispatcher-side CLI + the Reoon HTTP call + the cost emit. The cache primitive RUNS BEFORE the Reoon call (it's the prevention layer); merging into `enrich_emails.py` would either (i) inflate `enrich_emails.py`'s surface to include cache-derivation semantics + event-payload-factory shape (the module already has 600+ LOC of CLI + frontmatter parsing); or (ii) split the cache logic across two modules — exactly the SoT split D144 explicitly rejects. The sibling-of-the-wrapped-call-site placement (D154's choice) preserves both modules' single-purpose shape.

**Why NOT inside `ledger.py`?** Conflates cache-as-derivation with ledger-as-substrate. `ledger.py` is the append + query + indexer primitive — its load-bearing exports are `Ledger`, `Event`, `query_by_*`, `all_events`, `funnel`. Adding a cache-lookup wrapper inside the same module would dilute the single-purpose shape. The cache primitive depends on the ledger; the ledger does not depend on the cache. Putting the dependent inside the dependency creates the inverted-coupling smell that the Pillar D Week 2 D102 precedent explicitly rejects (the classifier is a SIBLING of `reconcile.py`, not inside it).

**Why NOT an `orchestrator/cache/` subpackage?** Over-organization for Week 4-5's scope (~500 LOC of cache primitive + tests). The single-file convention used by every other Pillar primitive is the precedent for new primitives. The subpackage rationale resurfaces IF a future Pillar E (or Pillar G) week adds a second cache primitive (e.g., Apollo organization cache, PDL person cache); until then, the top-level placement is the right grain.

### D155. `email_verification_cache_hit` event class — emit-shape contract

Per ADR-0032 D146 + ADR-0014 D33 (channel-on-every-event invariant). The `email_verification_cache_hit` event class carries the following fields:

```python
{
    "type": "email_verification_cache_hit",
    "person_id": "<person-id>",                # the Person whose email was verified
                                                # (defaults to the cached event's person_id)
    "email": "dylan@example.com",              # the email looked up
    "cached_result": "safe",                   # the Reoon status STRING ("safe" /
                                                # "catch_all" / "invalid" /
                                                # "disposable" / etc.) — derived from
                                                # the cached response's status field
    "cached_at": "2026-05-01T10:00:00.000Z",   # ISO 8601 of the originating
                                                # cost_incurred event
    "cache_age_days": 23,                      # computed at lookup time for operator audit
    "channel": "email",                        # cache is email-channel-specific per
                                                # D146 channel-on-every-event invariant
    "_emitted_by": "email_verification_cache", # per ADR-0010 D17 convention
}
```

**Field rationale:**

* **`person_id`** — defaults to the cached event's `person_id` (the original verification's attribution). The cache hit's natural attribution IS the original verification's attribution; the same Person whose email was first verified is typically the one being re-verified now. A caller in a different per-Person context (e.g., a manual operator-initiated lookup where the original cached event has no `person_id`, or a cross-Person email lookup) MAY override via the `person_id` kwarg on the factory.
* **`email`** — the email address looked up. Operator-deliberate so the event is queryable by email without joining back to the originating cost event. Operators investigating per-email verification history grep on this field.
* **`cached_result`** — the Reoon status STRING (NOT the full response dict). The dict is preserved on the originating `cost_incurred` event's `verification_response` field (per D156); the event carries the status for fast operator-readable filtering ("how many `safe`-status cache hits this month?"). The status alone is the operator-visible outcome label; full audit drills back to the originating cost event via `cached_at` lookup.
* **`cached_at`** — ISO 8601 timestamp of the originating cost event. Pillar G dashboards consume this to compute "average cache age at hit time" + the cache-hit-rate-over-time series.
* **`cache_age_days`** — computed at lookup time for operator audit. The field is denormalized (could be computed from `cached_at` + the event's own `ts`) but the explicit field surfaces the operator-meaningful number without per-query computation. Mirrors `discovery_dedup_hit`'s `matched_classes` denormalization (per ADR-0033 D150 — same pattern).
* **`channel: "email"`** — per ADR-0032 D146's channel-on-every-event invariant extension. The cache primitive is email-channel-specific (the lookup key is an email; the cached outcome is Reoon's email-verification verdict). The explicit stamp makes the absence operator-visible to Pillar G dashboards filtered by channel; a future operator filtering "show me email-channel events" sees cache hits in the email-channel funnel. Contrasts with the dedup primitive's `channel: "none"` (dedup is channel-agnostic).
* **`_emitted_by: "email_verification_cache"`** — per ADR-0010 D17 the operator-facing filter marker. Tests + the cross-pillar audit consume this literal string predicate.

**The event REPLACES (does not co-emit with) the `cost_incurred` event** per ADR-0032 D144. The cache hit IS the cost-avoidance signal; co-emitting both would double-count in Pillar G's per-source cost dashboards. The wrap inside `verify_with_reoon` enforces the early-return: on cache hit, emit the cache_hit event + return; the cost_incurred emit path is never reached.

**Why `channel: "email"` (rejected: `channel: "none"` mirroring dedup; rejected: omit the field).** Three plausible postures: (a) `channel: "email"` (D155's choice); (b) `channel: "none"` (mirroring the dedup primitive); (c) omit the field. The rationale:

* **Per ADR-0014 D33 + ADR-0032 D146 the channel-on-every-event invariant** — every event carries the field. Omitting the field for cache events would create a per-event-class special case that Pillar G dashboards must handle.
* **The cache event IS email-channel-specific** — the lookup key is an email; the cached outcome is Reoon's email-verification verdict; the Pillar G dashboard's per-email-channel cost-avoidance aggregation needs the cache hits to land in the email channel. Stamping `channel: "none"` would exclude cache hits from per-channel filters — operator-confusing.
* **Mirrors Pillar D Week 1's `reply_received` events** stamping `channel: "email"` even though Pass B's emit context is unambiguously email — the "stamp the channel verbatim, no inference" discipline applies. The cache event's context IS unambiguously email; the explicit stamp makes the channel attribution operator-visible.
* **Contrasts deliberately with the dedup primitive's `channel: "none"`** — dedup operates over identity keys (channel-agnostic); cache operates over emails (email-specific). The asymmetry IS by design — Pillar G dashboards aggregate per-channel cost-avoidance from cache hits + per-source dedup hits independently.

**Pin:** `tests/test_multi_channel_coherence.py::TestEmailVerificationCache::test_cache_hit_emits_cache_hit_event_not_cost_incurred` un-skipped + passing in this Week 4-5 commit. `tests/test_email_verification_cache.py::TestBuildEmailVerificationCacheHitPayload::*` cover every field's contract individually (11 per-field tests).

### D156. Cache substrate — derived view of `cost_incurred.source=reoon` events + content-additive cost-event extension

Per ADR-0032 D144 the cache substrate IS the ledger event stream — no separate cache file; the ledger IS the cache. The cache primitive's `lookup_cache(email)` walks `Ledger.all_events()` filtering by `type == "cost_incurred"` + `source == "reoon"` + `email == <target>` (case-insensitive) + `ts >= now - ttl_days`. Returns the most-recent matching row's `verification_response` field as the cached payload.

**The current `emit_reoon_cost_event` doesn't carry the substrate fields.** Pre-Pillar-E-Week-4 cost events carry `type` + `source` + `amount_usd` + `units` + `model_or_endpoint` + `person_id` + `run_id` — but NO `email` or `verification_response` fields. D156 extends the function content-additively with two new optional kwargs:

```python
def emit_reoon_cost_event(
    led, *,
    person_id: str | None = None,
    run_id: str | None = None,
    email: str | None = None,                    # NEW per D156
    verification_response: dict | None = None,   # NEW per D156
) -> None:
    ...
    led.append({
        "type": "cost_incurred",
        "source": "reoon",
        "amount_usd": float(rate),
        "units": 1,
        "model_or_endpoint": "verifier/power",
        "person_id": person_id,
        "run_id": run_id,
        "email": email,                            # NEW per D156
        "verification_response": verification_response,  # NEW per D156
    })
```

**The extension is content-additive.** Pre-Pillar-E-Week-4 cost events lacking the new fields are tolerated by every consumer:

- **`BudgetWindowCapRule.evaluate`** (per ADR-0006) walks `cost_incurred` events summing `amount_usd`. The new fields are silently ignored; the budget rule's behavior is unchanged.
- **`ledger.query_by_*`** indexes events by `person_id`, `intent_id`, `gmail_message_id`, `email` (per `_idx_email`). The new `email` field on cost events DOES populate `_idx_email` — which is the desired side effect (the email-to-person-ids lookup now indexes Reoon-verified emails alongside the existing per-Person email writes).
- **Pillar G dashboards** (future Weeks 31-42) consume the existing `amount_usd` aggregation + gain new per-email cost-attribution via the `email` field.

**Pre-Pillar-E-Week-4 cost events are invisible to the cache.** A Reoon cost event without `email` or `verification_response` is treated as a miss (no payload to return; no email to match on). Existing operators populate the cache going forward — the next Reoon call after Pillar E Week 4-5 ships emits the extended event; subsequent calls within TTL find that event as the cache substrate. The Existing-operator seed section names this trajectory.

**The lookup is read-only.** The cache primitive's `lookup_cache` walks the ledger; the call site emits the cache_hit event on hit (via `build_email_verification_cache_hit_payload` + `_safe_append`); the cost_incurred event on miss (via the existing `emit_reoon_cost_event` extended with the new fields). The cache primitive itself does NOT write to the ledger; the cache primitive does NOT modify the ledger schema beyond the cost event's content-additive extension.

**The lookup-walk cost at scale.** Each `lookup_cache(email)` walks `Ledger.all_events()` — at v1 scale (~5K total events; ~500 unique emails) the per-call cost is sub-millisecond. At Pillar I scale (50K-100K events) the per-call cost may compound; the per-week reviewer's P1 watch-list item tracks this. The mitigation path: a future `lookup_cache(..., index=preloaded_index)` kwarg (the same per-call-index pattern as ADR-0033's dedup primitive's deferred optimization). Week 4-5 ships the naive linear walk; the index parameter is a follow-up if/when benchmarks surface a bottleneck.

**Why the ledger-as-substrate (rejected: separate cache file; rejected: in-memory cache; rejected: SQLite-backed cache).** Three reasonable storage shapes:

* **(a) ledger-as-cache** (D156's choice — inherits D144). The ledger is the existing SoT for cost events; the cache derives. No new SoT row in `docs/SOURCES-OF-TRUTH.md`; no new file at `~/.outreach-factory/`; no new operator-visible state to back up.
* **(b) Separate cache file at `~/.outreach-factory/cache/email_verification.yml`** — REJECTED. Creates a new SoT row; duplicates information already in the ledger's `cost_incurred` events; introduces drift risk (the cache file and the ledger could disagree on a cached outcome — which is authoritative?).
* **(c) SQLite-backed cache** (Pillar G's analytics-storage precedent) — REJECTED as premature. SQLite mirror is the Pillar G analytics-storage primitive per PILLAR-PLAN §5 ("SQLite mirror of ledger, rebuilt nightly"); the cache primitive lives at the Pillar E layer (per-call lookup, not analytics). The existing ledger query primitive (`all_events`) handles cache lookup at v1 scale; SQLite is a future scaling primitive.

**Pin:** `tests/test_email_verification_cache.py::TestLookupCacheHappyPaths::test_pre_pillar_e_week_4_cost_event_without_email_is_treated_as_miss` verifies the content-additive seed behavior. `tests/test_multi_channel_coherence.py::TestEmailVerificationCache::test_cache_substrate_is_ledger_event_stream` verifies no auxiliary cache file is created + the substrate survives ledger reload.

### D157. TTL — 30-day default + inclusive-lower-bound semantics

Per ADR-0032 D144 the cache TTL is 30 days. D157 pins the constant:

```python
DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS: int = 30
```

**Why 30 days (rejected: 7 days; rejected: 90 days; rejected: unbounded).** Three plausible TTL values:

* **(a) 30 days** (D157's choice — inherits D144). Reoon's official accuracy guarantee bound. Beyond 30 days, the cached result may misrepresent the email's current deliverability (mailbox change, domain change, employee left); the operator's risk tolerance accepts re-verification at that point.
* **(b) 7 days** — REJECTED as too aggressive. Operators iterating on the queue (verifying the same prospect across a multi-week outreach cadence) would see redundant Reoon spend; the cost-avoidance benefit shrinks to the within-week window (operators don't typically re-verify the same email within 7 days; the TTL would rarely fire).
* **(c) 90 days** — REJECTED as too lax. Reoon's accuracy guarantee degrades beyond 30 days; a 90-day TTL would surface stale-cache failures to operators (an email cached as `safe` 60 days ago may now bounce). The asymmetric-failure-cost calculus (PILLAR-PLAN §0) — false-positive cache hit (stale `safe`) is one bounce in production (operator-visible; corrective via Pillar I evict); the 30-day bound is the right balance.
* **(d) Unbounded (cache forever)** — REJECTED. Pre-Reoon cost events would never expire; stale cache hits would compound; the operator's only recovery surface would be manual eviction. The TTL is the structural defense.

**The TTL boundary is INCLUSIVE on the lower bound.** An event at exactly `now - 30 days` IS a hit; an event at `now - 30 days - 1 second` is a miss. Matches the cooldown / budget rule convention per ADR-0002 + ADR-0006 (where `count >= max_count` blocks at-threshold; the asymmetric-failure-cost principle compels the at-boundary-as-still-valid choice — one extra cache hit is cheaper than one extra Reoon credit).

**Operator override.** The `lookup_cache(email, *, ttl_days=N)` kwarg lets callers override per-call. Operators can shell to the CLI with `--ttl-days N` for one-off lookups. Per-tenant override via Pillar I CLI is the future extension surface (TBD per Pillar I's ADR).

**Per ADR-0034 the constant is the SINGLE SOURCE OF TRUTH.** No second `30` literal elsewhere in the codebase; the per-week reviewer's P3 watch-list item tracks this. Future Pillar E weeks (or Pillar I) that need to reference the TTL import the constant.

**Pin:** `tests/test_multi_channel_coherence.py::TestEmailVerificationCache::test_cache_ttl_is_30_days` un-skipped + passing. `tests/test_email_verification_cache.py::TestTTLBoundary::test_event_at_exactly_ttl_boundary_is_hit` + `test_event_one_second_inside_ttl_is_hit` + `test_event_one_second_outside_ttl_is_miss` pin the boundary semantics individually.

### D158. Per-call-site integration — content-additive wrap inside `verify_with_reoon`

The cache primitive's integration is INSIDE `orchestrator/enrich_emails.py::verify_with_reoon` (single call site — structurally simpler than the dedup primitive's four-skill integration per ADR-0033 D152). The wrap is content-additive:

```python
def verify_with_reoon(
    email: str,
    api_key: str,
    *,
    led: "object | None" = None,           # NEW per D158
    person_id: str | None = None,          # NEW per D158
    run_id: str | None = None,             # NEW per D158
) -> dict:
    # Per ADR-0034 D158 — cache-lookup prelude. Only when the caller
    # opts in via `led`.
    if led is not None and _LEDGER_AVAILABLE and _cache is not None:
        try:
            cache_result = _cache.lookup_cache(email, ledger=led)
        except Exception as exc:
            sys.stderr.write(f"WARNING: ... falling through to HTTP\n")
            cache_result = None
        if cache_result is not None and cache_result.is_cache_hit:
            payload = _cache.build_email_verification_cache_hit_payload(
                cache_result, email, person_id=person_id,
            )
            _cache._safe_append(led, payload)
            return cache_result.cached_response

    # Cache miss: existing Reoon HTTP path UNCHANGED.
    params = urllib.parse.urlencode({...})
    ...
    data = json.loads(body)
    if "status" not in data:
        raise ValueError(...)

    # Per D156 — when caller opted in via `led`, this function is the
    # sole emitter of cost_incurred for Reoon (with the cache substrate
    # fields email + verification_response).
    if led is not None and _LEDGER_AVAILABLE:
        emit_reoon_cost_event(
            led, person_id=person_id, run_id=run_id,
            email=email, verification_response=data,
        )
    return data
```

**The wrap is content-additive.** The legacy two-arg signature `verify_with_reoon(email, api_key)` is preserved — pre-Pillar-E-Week-4 callers see no behavior change (no cache lookup; no cost emit from the function itself; the legacy `emit_reoon_cost_event` call at the call site remains the cost-emission surface). The Pillar E Week 4-5 `process_one` refactor moves the cost emit INSIDE `verify_with_reoon` via the new `led` kwarg path — the function becomes the sole authoritative emitter of cost_incurred (Reoon) + cache_hit events on the opt-in path.

**A cache-lookup failure MUST NOT block the verification.** Per the cache-as-FAST-PATH discipline (HANDOFF-pillar-e-week-4.md §Design-decisions), a broken cache falls through to the Reoon HTTP call with a stderr warning. The verification proceeds; the cache observability surface degrades; the operator sees the warning + the missing cache_hit event in dashboards.

**The cache hit's return value IS the cached Reoon response dict (verbatim).** Downstream code consuming `verify_with_reoon`'s return value (per `apply_verification_to_text`) sees the same shape on cache hit + cache miss — no caller awareness of the cache layer required. The cache primitive is transparent to non-observability consumers.

**`process_one` refactor (Week 4-5 — `orchestrator/enrich_emails.py`).** The single change to the existing `process_one` function:

```python
# Before (Pillar E pre-Week-4-5):
verification = verify_with_reoon(primary, reoon_key)
emit_reoon_cost_event(led, person_id=filepath.stem, run_id=run_id)

# After (Pillar E Week 4-5):
verification = verify_with_reoon(
    primary, reoon_key,
    led=led, person_id=filepath.stem, run_id=run_id,
)
# (cost emit moved inside verify_with_reoon)
```

The change is two lines moved into the call (the kwargs) + one line removed (the explicit cost emit). The function becomes the single source of truth for the cost-vs-cache-hit decision; the caller's responsibility shrinks to "call verify_with_reoon and pass led if you want observability."

**Why content-additive wrap (rejected: new function `verify_with_reoon_cached`; rejected: separate wrap inside `process_one`; rejected: move cost emit OUT of the function).** Three plausible integration shapes:

* **(a) Extend `verify_with_reoon` in-place with new kwargs** (D158's choice — inherits the handoff's design). Content-additive (legacy signature preserved); single call site to update (`process_one`); function becomes sole authoritative emitter of both cost + cache events.
* **(b) New function `verify_with_reoon_cached(email, api_key, *, led, person_id, run_id)`** — REJECTED. Two functions with overlapping behavior invites caller confusion (which do I call?); the existing function still has callers in test_enrichment_costs.py; maintaining two paths doubles the future change surface.
* **(c) Wrap inside `process_one` only (cache check before calling `verify_with_reoon`)** — REJECTED. Couples cache logic to one specific call site; future callers of `verify_with_reoon` (e.g., a Pillar G dashboard re-verifying for staleness audit) wouldn't get the cache benefit without duplicating the prelude.
* **(d) Move cost emit OUT of `verify_with_reoon` (sole-emitter ownership stays at the call site)** — REJECTED. The caller must then track cache hit / miss state to know whether to emit cost — the caller surface grows; the cache primitive's existence leaks into the caller's contract. The sole-emitter-inside-verify_with_reoon shape collapses the surface.

### D159. Cross-pillar audit row extension — `.planning/REVIEW-pillar-e-surface-audit.md`

Per ADR-0032 D146 the cross-pillar surface audit is the load-bearing anti-regression artifact. The Week 4-5 commit extends `.planning/REVIEW-pillar-e-surface-audit.md` with a new section walking the `email_verification_cache_hit` event class's consumer surface. Per consumer:

1. **`_idx_person`** — `email_verification_cache_hit` events carry `person_id` (the cached event's person_id, defaulting from the originating cost event); cache hits with non-null `person_id` DO land in the per-Person index. Every existing consumer (the Pillar A/B/C/D enumeration from Week 1 + 2 audits) is closed-set-protected or by-design-broadening:
   * `derived_stage` — closed dispatch table `_STAGE_BY_EVENT_TYPE`; the new event type is absent → **closed-set-protected, by-design**.
   * `reachable_pipeline_stages` — same dispatch table → **closed-set-protected**.
   * `derived_conversation_status` — literal-string filter on REPLY_EVENT_TYPES + suppression + state-change events → **closed-set-protected**.
   * `derived_conversation_outcome` — `type == "conversation_outcome"` filter → **closed-set-protected**.
   * `CrossChannelTouchRule.evaluate` — `endswith("_confirmed")` predicate → the new type does NOT match → **literal-string-filtered, by-design**.
   * `BudgetWindowCapRule.evaluate` — `type == "cost_incurred"` filter → cache_hit events are NOT cost_incurred (per D155 explicit) → **literal-string-filtered (`type == "cost_incurred"` is the load-bearing predicate)**.
   * `CooldownRule._confirmed_send_intent_pairs` — `type in {"send_intent", "send_confirmed"}` → **literal-string-filtered**.
   * `DomainThrottleRule.evaluate` — `type != "send_confirmed"` → cache_hit events don't match the loop guard → **literal-string-filtered**.
   * `Ledger.last_send_for` — `_INTENT_TYPES + _OUTCOME_TYPES` → cache_hit events absent → **closed-set-protected**.
   * Pass G's reply classifier idempotence index — `REPLY_EVENT_TYPES` filter → cache_hit events absent → **closed-set-protected**.
   * Pass M's auto-unsubscribe — `category=unsubscribe` filter → cache_hit events absent → **closed-set-protected**.
   * Pass N's conversation state machine — reply + classified + suppression + state-change filter → cache_hit events absent → **closed-set-protected**.
   * Pass O's conversation outcome — `*_confirmed` filter → cache_hit events absent → **closed-set-protected**.
   * Pillar D funnel CLI (`orchestrator/funnel.py::build_report`) — `reply_classified` + `conversation_outcome` filter → cache_hit events absent → **closed-set-protected**.

2. **`_idx_email` ledger index** (per `ledger.py:484-485`) — the new `email` field on cost events DOES populate `_idx_email` (which maps `email → set[person_id]`). The index already accepts events with `email` + `person_id` fields; the cost event extension lands in the existing index by design.
   * **Pre-Pillar-E-Week-4 consumer behavior**: `query_by_email(email)` returns the set of person_ids the ledger has associated with the email. Existing populators were the email-carrying events from Pillar A/B/C (`send_intent`, `reply_received`, etc.). The cache substrate adds Reoon cost events to the populator set — operator audit: "which Persons have I verified emails for?" gains Reoon-verified-only Persons (no other event class for them). Verdict: **by-design broadening; the existing consumer's contract (return set of person_ids per email) is preserved + the population set deliberately broadens**.

3. **`cost_incurred` schema extension** — the cost event gains `email` + `verification_response` fields. Every existing `cost_incurred` consumer enumerated in §1 above continues to function:
   * **`BudgetWindowCapRule.evaluate`** — sums `amount_usd`; ignores new fields. **UNCHANGED**.
   * **Pillar G future dashboards** — gain per-email cost-attribution + per-Person Reoon-spend-by-email-domain analytics. **BY-DESIGN BROADENING**.
   * **Pre-Pillar-E-Week-4 cost events** (lacking the new fields) — invisible to the cache (treated as miss); existing analytics consumers continue to function. **CONTENT-ADDITIVE — NO BREAKAGE**.

4. **`enrich_emails.verify_with_reoon` call signature extension** — the new kwargs `led` / `person_id` / `run_id` default to None; existing callers (test_enrichment_costs.py + the `process_one` legacy path until refactored) see no behavior change.
   * **Legacy CLI path** (`process_one` pre-Week-4-5 callers) — UNCHANGED. The two-arg signature still works; cache is not consulted; cost emit happens at the call site via `emit_reoon_cost_event`.
   * **Week 4-5 refactored `process_one`** — passes the new kwargs; cache prelude fires; cost emit moves inside the function.
   * **Test callers** (`tests/test_enrichment_costs.py`) — UNCHANGED. Tests call `emit_reoon_cost_event` directly without going through `verify_with_reoon`; the cost emit's content-additive extension preserves all assertions.

5. **`email_verification_cache_hit` SIBLING of `discovery_dedup_hit`** — both event classes are pre-action-decision cost-avoidance signals. The two are structurally analogous:
   | Field | `discovery_dedup_hit` (Pillar E Week 2) | `email_verification_cache_hit` (Pillar E Week 4-5) |
   |---|---|---|
   | `type` | `"discovery_dedup_hit"` | `"email_verification_cache_hit"` |
   | `person_id` | YES (existing match's id) | YES (cached event's person_id, defaulting) |
   | `channel` | `"none"` (dedup is channel-agnostic) | `"email"` (cache is email-specific) |
   | `_emitted_by` | `"discovery_dedup"` | `"email_verification_cache"` |
   | source attribution | `source_skill` + `source_list` | NONE (cache is operator-invocation-agnostic) |
   | content-payload field | `candidate_partial` + `matched_classes` | `cached_result` + `cached_at` + `cache_age_days` |

   **Audit verdict: structural symmetry — by-design.** Both events are pre-action cost-avoidance signals; both are consumed by Pillar G's per-source cost-attribution dashboards (the dashboards aggregate cache_hits + dedup_hits to compute the operator's per-skill + per-channel cost-avoidance hit-rate). The asymmetry in `channel` value reflects the asymmetric scope of the two primitives (dedup is channel-agnostic; cache is email-specific) — this asymmetry IS load-bearing per the Pillar G dashboard's per-channel filter behavior.

**Categories the Pillar E Week N+ per-week reviewer must verify (extending the Week 1 + 2 + 3 baseline):**

* **Does Week 4-5 broaden `_idx_person`?** YES — `email_verification_cache_hit` carries `person_id`. Every consumer verified closed-set-protected or by-design-broadening in §1 above.
* **Does Week 4-5 add a new `*_confirmed`-suffixed event?** NO. `CrossChannelTouchRule` unaffected.
* **Does Week 4-5 add to `_STAGE_BY_EVENT_TYPE`?** NO. The cache hit is observational, not a pipeline-stage advancement.
* **Does Week 4-5 add a new per-prospect dedup-index pattern analogous to `_idx_gmail_msg`?** NO. Week 4-5 uses the existing `_idx_email` index for the per-email lookup; no new index pattern.
* **Does Week 4-5 modify `enrollment.py` or any pre-existing reconcile pass?** NO. The cache primitive operates entirely inside `enrich_emails.py`'s wrap.
* **Does Week 4-5 extend the `identity_keys:` schema in a way that breaks pre-Pillar-E Person notes?** NO. The cache is email-keyed, not identity-keyed.
* **Does Week 4-5 add a new `cost_incurred` source name?** NO. The cache hit is EXPLICITLY distinct from `cost_incurred` (per D155 + ADR-0032 D144). Future Pillar E weeks must NOT add `cost_incurred.source=email_verification_cache` (that would contradict the cache-hit-is-cost-avoidance semantics).
* **Does Week 4-5 extend the `cost_incurred` schema with new fields?** YES — `email` + `verification_response` per D156. Content-additive; the existing `BudgetWindowCapRule` consumer ignores; the new `_idx_email` population is by-design.
* **Does Week 4-5 surface `source_list` in any operator-facing dashboard, CLI, or aggregation surface?** NO. The cache event does not carry `source_list` (the cache is email-keyed, not discovery-source-keyed). The Layer 1 D148 defense continues to pass.

**Pin:** `.planning/REVIEW-pillar-e-surface-audit.md` extended in this commit with the Week 4-5 section (§23+). Future Pillar E weeks consult the audit + extend it per the per-week-review-with-follow-up-commit discipline (Pillar A + B + C + D + E pattern).

## Alternatives considered

### D154-Alt1: Place the cache primitive inside `orchestrator/enrich_emails.py`

A new function `enrich_emails.lookup_cache` + the wrap inline in `verify_with_reoon`. **Rejected** because:

* Conflates cache-as-prevention with verification-as-action. `enrich_emails.py` today is the dispatcher-side CLI + the Reoon HTTP call + the cost emit. The cache primitive is a separate concern (pre-action lookup against the ledger event stream); merging into `enrich_emails.py` would inflate the module to include cache-derivation semantics + the event-payload-factory shape (the module already has 600+ LOC).
* The Pillar E Week 2 ADR-0033 D149 precedent — the dedup primitive is a SIBLING of `enrollment.py` (the wrapped call site), not inside it. The sibling-of-the-wrapped-call-site placement preserves both modules' single-purpose shape.
* `enrich_emails.py` would gain ledger-import semantics; the cache primitive lives at the integration layer; the existing function (`verify_with_reoon`) calls the cache; the cache itself depends on `ledger`. Putting the cache inside `enrich_emails.py` would shift `enrich_emails.py`'s dependency surface to include the ledger directly.

### D154-Alt2: Place the cache primitive inside `orchestrator/ledger.py`

A new `ledger.lookup_email_verification_cache` method on the Ledger class. **Rejected** because:

* `ledger.py` is the ledger primitive — its load-bearing exports are `Ledger`, `Event`, `query_by_*`, `all_events`, `funnel`. Adding a cache-lookup wrapper inside the same module would dilute the single-purpose shape.
* Inverted coupling — the cache depends on the ledger; the ledger does not depend on the cache. Putting the dependent inside the dependency creates the same code smell ADR-0026 D102 rejected for the classifier inside `reconcile.py`.
* The `Ledger` class's surface would grow with each new Pillar (Pillar E cache, Pillar F voice-corpus query, Pillar G dashboard query, ...). The single-purpose ledger primitive's append + query + indexer surface stays clean by keeping per-Pillar wrappers in their own modules.

### D154-Alt3: Spin up an `orchestrator/cache/` subpackage

`orchestrator/cache/__init__.py` + `orchestrator/cache/email_verification.py` + future siblings (Apollo cache, PDL cache, etc.). **Rejected** as over-organization for Week 4-5's scope (~500 LOC of cache primitive + tests). The single-file convention used by `discovery_dedup.py` + `reply_classifier.py` + `enrollment.py` + `identity.py` is the precedent for Pillar primitives. The subpackage rationale resurfaces in a future Pillar E (or Pillar G) week IF a second cache primitive lands; until then, the top-level placement is the right grain.

### D155-Alt1: Stamp `channel: "none"` instead of `"email"`

Mirror the dedup primitive's channel-agnostic stamp. **Rejected** because:

* The cache event IS email-channel-specific (the lookup key is an email; the cached outcome is Reoon's email-verification verdict). Stamping `"none"` would exclude the cache hit from per-email-channel dashboards — operator-confusing.
* Pillar G's per-channel cost-avoidance funnel needs the cache hits to land in the email channel for the per-channel hit-rate aggregation: `cache_hit_count_by_channel["email"] / (cache_hit_count_by_channel["email"] + cost_incurred_by_channel["email"])`. The `"none"` channel value would orphan cache hits from this aggregation.
* The asymmetry vs the dedup primitive's `"none"` IS by design — dedup operates over identity keys (channel-agnostic); cache operates over emails (email-specific). The "stamp the channel verbatim, no inference" discipline per Pillar D Week 1 D96 applies: the cache event's context IS email; the explicit stamp makes the attribution operator-visible.

### D155-Alt2: Omit the `channel` field on cache events entirely

The cache is email-specific by definition; the field is superfluous. **Rejected** because:

* Violates ADR-0014 D33 + ADR-0032 D146's channel-on-every-event invariant. Pillar G dashboards filtering by channel must see every event class with the field (per the invariant's "every event carries the field" rule).
* Per-event-class special cases in the dashboard layer (handle cache hits separately from other events) is exactly what the channel-on-every-event invariant prevents.
* The dedup primitive (per ADR-0033 D150) explicitly stamps `channel: "none"` to preserve the invariant; the cache primitive (per D155) stamps `channel: "email"` for the same reason — omission would be a regression of the discipline.

### D155-Alt3: Carry the full Reoon response dict in the `cached_result` event field

Serialize the full response per replay-completeness. **Rejected** because:

* The full Reoon response includes `status` + `overall_score` + `is_disposable` + various per-vendor metadata. Serialized into every cache hit event would inflate the ledger (every cache hit carries 200-500 bytes of nested data). The append-only growth scales with operator activity; carrying redundant data per cache hit compounds.
* The full response is ALREADY preserved on the originating `cost_incurred` event's `verification_response` field (per D156). Cache hit events carry the `cached_at` timestamp; operator audit drills back to the originating event for full fidelity.
* The status string (`cached_result`) is the operator-visible outcome label — sufficient for per-status aggregation (Pillar G's "how many `safe`-status cache hits this month?" query). The full payload would be operator-noise for the common dashboard use case.

### D156-Alt1: Add a separate cache event class instead of extending `cost_incurred`

A new `email_verification_completed` event class carrying `email` + `verification_response`, emitted alongside `cost_incurred` on every Reoon call. **Rejected** because:

* Adds a NEW event class for state that's already implicit in the existing `cost_incurred.source=reoon` events. The cache primitive's `lookup_cache(email)` would walk both event classes (or just the new one); the cost_incurred event would carry the cost; the new event would carry the response. The split is operator-confusing (which is authoritative for "did we verify this email?").
* The content-additive extension (adding `email` + `verification_response` to the existing `cost_incurred` event) is structurally cleaner — one event per Reoon call carries both the cost attribution AND the substrate; consumers querying for either find the same event.
* Per ADR-0032 D144 the rejected D144-Alt3 was exactly this shape (`email_verification_cache_state` as a sibling to cost_incurred). The same rejection rationale applies.

### D156-Alt2: Add a separate cache file at `~/.outreach-factory/cache/email_verification.yml`

A dedicated cache file with its own schema + read/write primitive. **Rejected** because:

* Creates a new SoT row in `docs/SOURCES-OF-TRUTH.md` — but the source-of-truth is Reoon (the external service) + the ledger's `cost_incurred` event already records the response. A separate cache file duplicates information.
* Reproducibility from ledger replay (I4) suffers — replaying the ledger reconstructs the cache state when the cache lives in the ledger; a separate cache file requires its own replay machinery.
* Operator-visible state grows by one file; per-pillar SoT registry growth is operator-visible cost.
* Per ADR-0032 D144's rejected D144-Alt1 — the same shape was already rejected at the foundation ADR level. This ADR inherits the rejection.

### D156-Alt3: Carry the verification_response on EVERY event class, not just cost_incurred

Add `verification_response` to `enrolled` events, `reply_received` events, etc. — every event class touching emails gains the cache substrate. **Rejected** because:

* Scope creep — the cache substrate's purpose is to back the cache primitive's `lookup_cache` query. Other event classes don't carry the response because they don't originate from Reoon — they would have to be JOINED to the originating cost event anyway.
* Single-responsibility — the `cost_incurred` event class is the natural home for the verification response (the response IS the cost; the cost IS billable for the response). Spreading the response across event classes dilutes the per-event single purpose.
* Storage cost — every event class would grow by 200-500 bytes per row; the ledger size compounds. The `cost_incurred` event class is the bounded surface (one event per billable Reoon call); other event classes are higher-volume.

### D157-Alt1: 7-day TTL (more aggressive eviction)

Re-verify every email at most once per week. **Rejected** because:

* Operators iterating on the queue (verifying the same prospect across a multi-week outreach cadence — typically 2-4 weeks per cold-touch sequence) would see redundant Reoon spend; the cost-avoidance benefit shrinks to the within-week window.
* Reoon's accuracy guarantee is ~30 days; a 7-day TTL is more conservative than necessary. The asymmetric-failure-cost calculus favors longer-as-tolerable (the false-positive cost is one bounce; the false-negative cost is one Reoon credit).
* The per-call override surface (`ttl_days` kwarg) lets operators with a stricter risk tolerance shorten on-demand; the 30-day default serves the common case.

### D157-Alt2: 90-day TTL (more permissive caching)

Allow caching beyond Reoon's accuracy guarantee. **Rejected** because:

* Reoon's accuracy degrades beyond 30 days; cached `safe` outcomes for emails that have since become invalid would produce stale-cache-hit bounces in production.
* The Pillar G dashboard's stale-cache-hit-rate would compound — operators investigating bounce-rate increases would find cache age as the root cause; the structural fix would be a TTL reduction. The 30-day default avoids the easily-avoidable failure mode.
* Per ADR-0032 D144 the 30-day TTL is the load-bearing default; this ADR inherits.

### D157-Alt3: Unbounded TTL (cache forever)

No expiration. **Rejected** because:

* The cache would accumulate stale-cache hits at compounding rates over operator-time. The only recovery surface would be manual eviction (Pillar I CLI's deferred `purge --email` extension).
* The asymmetric-failure-cost calculus is wrong — false-positive cache hits become a structural problem rather than a bounded one. The TTL is the structural defense.
* Per Reoon's accuracy guarantee + the existing bounce-handling flow per Pillar D Week 1's Pass B, the bounded TTL is the right grain.

### D158-Alt1: New function `verify_with_reoon_cached(email, api_key, *, led, person_id, run_id)` — separate cache path

Keep `verify_with_reoon` unchanged; add a new function for the cache-aware path. **Rejected** because:

* Two functions with overlapping behavior invites caller confusion (which do I call?). The existing function still has callers (test_enrichment_costs.py + the `process_one` legacy path); maintaining two paths doubles the future change surface.
* The content-additive extension of `verify_with_reoon` (new optional kwargs default None; legacy two-arg signature preserved) achieves the same goal without the two-function surface.
* The Pillar A I7 enforcement (cost is first-class) is cleaner with one function as the sole authoritative emitter — the caller has one entry point; the function controls the cost-vs-cache-hit dispatch atomically.

### D158-Alt2: Wrap inside `process_one` only (cache check before calling `verify_with_reoon`)

Move the cache logic to the call site rather than inside the wrapped function. **Rejected** because:

* Couples cache logic to one specific call site; future callers of `verify_with_reoon` (e.g., a Pillar G dashboard re-verifying for staleness audit; a Pillar I doctor preflight extension) wouldn't get the cache benefit without duplicating the prelude.
* The Pillar D Week 2 D102 precedent — the rule-based classifier is wrapped inside the classifier module's entry point, not at the reconcile-pass call site. The wrap-at-the-primitive-level pattern keeps the integration surface single.
* The wrap-at-call-site shape would scatter the cache discipline across N call sites instead of one. The Pillar E Week 2 dedup primitive's per-skill integration has N=4 (four discovery skills); the cache primitive has N=1 (one Reoon call site); wrapping at the call site for N=1 is no simpler than wrapping at the function — but it loses the future-callers-benefit property.

### D158-Alt3: Move the cost emit OUT of `verify_with_reoon` (sole-emitter ownership stays at the call site)

Keep the existing `process_one`-emits-cost shape; the function returns a tagged tuple `(verification_dict, was_cache_hit)` so the caller knows whether to emit cost. **Rejected** because:

* Return-value pollution — every caller must now destructure the tuple OR check a sentinel field on the returned dict. The function's contract grows.
* The caller's responsibility expands — `process_one` (and every future caller) must track cache hit / miss state to decide whether to call `emit_reoon_cost_event`. The cache primitive's existence leaks into the caller's contract.
* The sole-emitter-inside-`verify_with_reoon` shape (D158's choice) collapses the surface — the caller passes `led` + person attribution; the function emits the appropriate event; the caller doesn't need to know which.

### D159-Alt1: Spawn a code-reviewer agent for the audit extension

Use the `code-reviewer` agent type for a fresh-context audit. **Rejected for Week 4-5** mirroring ADR-0032 D146-Alt1 + ADR-0033 D153-Alt1's reasoning: the audit IS the load-bearing artifact + benefits from sharing context with the ADR's author. Pillar E Week 4-5's per-week independent reviewer (spawned post-commit per the standing convention) WILL re-audit the surfaces from a fresh-context perspective; the inline audit + the per-week-review audit are complementary.

### D159-Alt2: Skip the audit extension; rely on per-week reviews to catch broadening surfaces

Pillars A + B all relied on per-week reviews. **Rejected** mirroring ADR-0032 D146-Alt2 + ADR-0033 D153-Alt2's reasoning: the per-week reviewer's threshold for "ship-stopping" is biased toward "defer to holistic" for pre-existing surfaces. The audit IS the structural intervention against the Pass-A-class pattern; future Pillar E weeks' per-week reviewers consult the audit as the surface map + extend it; the discipline compounds.

### D159-Alt3: Defer the audit extension to a Week 4-5 follow-up commit

Ship the cache primitive + integration in the main commit; ship the audit extension in a follow-up. **Rejected** mirroring ADR-0033 D153-Alt3's reasoning: the audit extension IS part of the Week 4-5 deliverable per HANDOFF-pillar-e-week-4.md §"Validation gate". Splitting the commit risks the audit landing days/weeks after the code change it documents — exactly the gap the audit discipline is designed to prevent.

## Consequences

### Positive

- **The cache primitive MODULE is a clean Pillar E primitive.** Future Pillar E weeks (Week 6-8 tier auto-assignment) extend the discovery-primitive surface without churning the cache module.
- **The `email_verification_cache_hit` event class makes cost-avoidance operator-visible.** Pillar G's per-source-funnel dashboard reads these directly: "47% of Reoon calls were cache hits this month" = "$0.235 saved per 100 verifications" = "operators iterating on the same queue get bounded Reoon spend."
- **The cross-pillar surface audit (D159) continues the ADR-0032 D146 + ADR-0033 D153 discipline.** Every new event class extends the audit; the audit grows with the pillar; the Pass-A-class latent-bug pattern is foreclosed by construction.
- **The per-call-site integration discipline (D158) is the operator-readable contract.** `verify_with_reoon`'s docstring names the cache wrap explicitly; operators reading the function source see the cache check at the top of the function body.
- **The cost-event extension (D156) populates `_idx_email` with Reoon-verified emails** — operators auditing "which Persons have I verified emails for?" gain Reoon-verified-only Persons (no other event class for them). By-design broadening; the existing `query_by_email` contract is preserved.
- **The exit-criterion vehicle's Week 4-5 rows un-skip + pin the contract.** All 4 `TestEmailVerificationCache` rows pass; the cross-pillar coherence is locked in.
- **The Pillar A I1 invariant (single source of truth) is preserved.** The ledger remains the SoT for cost events + the cache substrate; no new files; no operator-visible state to back up.

### Negative

- **Pre-Pillar-E-Week-4 cost events are invisible to the cache.** Existing operators have no historical cache; the cache populates from the next Reoon call forward. **Mitigation:** the §Existing-operator seed names this trajectory; operators who want backfill can shell to `python -m orchestrator.email_verification_cache replay --since <date>` once the Pillar I CLI extension ships (deferred).
- **The cache lookup walks the entire `cost_incurred` event list per call.** At v1 scale (~5K cost events) the per-call cost is sub-millisecond; at Pillar I scale (50K-100K events) the per-call cost may compound. **Mitigation:** the naive implementation is fine at v1; if/when per-skill batch benchmarks show the walk as a bottleneck, a future Pillar E week adds a per-call index parameter (`lookup_cache(..., index=preloaded_index)`) without changing the function's contract. The per-week reviewer's P1 watch-list item tracks this.
- **The `cost_incurred` event schema is extended with `email` + `verification_response` fields.** Pre-existing consumers (BudgetWindowCapRule + ledger query API) are content-additive-compatible (extra fields ignored). **Mitigation:** the extension is verified in §D159 surface audit walk; the per-week reviewer's checklist explicitly names "does Week N extend the cost_incurred schema?" as a category.
- **The cache hit event REPLACES cost_incurred — a future contributor extending the cache primitive may accidentally co-emit both.** **Mitigation:** the structural defense is the wrap inside `verify_with_reoon`'s early-return on cache hit (the cost emit is in the cache-miss branch only); the audit's §Categories list pins this as a category; a regression test (`test_cache_hit_emits_cache_hit_event_not_cost_incurred`) verifies no co-emission.
- **The cache primitive's `lookup_cache` is read-only — no cache invalidation primitive in Week 4-5.** Operators who want to force-evict a cached email (e.g., after a bounce) must wait for Pillar I CLI's `purge --email` extension. **Mitigation:** the existing `bounce_detected` Pass B flow naturally surfaces stale-cache failures; operators correlating bounces to cache hits see the staleness pattern. The TTL bounds the maximum staleness window to 30 days.
- **The `email_verification_cache_hit` event is emit-only in Week 4-5 — no downstream consumer yet.** Pillar G dashboards land Weeks 31-42; until then, operators query via `python -m orchestrator.ledger grep --type email_verification_cache_hit`. **Mitigation:** the operator-visible surface is the ledger grep + the Pillar I CLI's eventual doctor preflight extension.

### Neutral / observability

- The `email_verification_cache_hit` events are queryable via the existing `query_by_person` + filter-by-type pattern. Pillar G's per-source-funnel dashboard reads these directly.
- The `_emitted_by: "email_verification_cache"` marker (per ADR-0010 D17 convention) lets operators filter cache-primitive output from other event sources in funnel queries.
- The `cache_age_days` field surfaces "how stale was this cache hit?" for operator audit — useful for tuning the TTL or for diagnosing stale-cache patterns.
- The `email` field on extended `cost_incurred` events lands in the existing `_idx_email` ledger index; operators gain per-email Reoon-spend attribution for free (no new index; no new query method).
- No new SoT introduced (per I1 invariant). The cache primitive emits events; the ledger remains the single SoT for the cache state + the cost event extension. No new files, no new YAML config, no new vault state.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT row added. The cache primitive emits events; the ledger remains the SoT for cost events + the cache substrate. The cache's READ side derives from the existing `cost_incurred.source=reoon` events; the WRITE side is the existing `emit_reoon_cost_event` path extended with `email` + `verification_response`. I1 holds.
- **I2 (two-phase commit on every external side effect):** The cache primitive is a pure FRAMEWORK operation (ledger walk + ledger append). The cache HIT path avoids the external Reoon call entirely (no external side effect to commit); the cache MISS path falls through to the existing Reoon HTTP call (whose two-phase commit semantics are preserved). The cost emit on miss extends the existing event with content-additive fields; no I2 contract change.
- **I3 (schema versioning):** The `email_verification_cache_hit` event carries `v: 1` stamped by `Ledger.append` per the existing event-versioning convention. The `cost_incurred` event's content-additive extension does NOT bump the schema version — pre-Pillar-E-Week-4 events lack the new fields; post-Pillar-E-Week-4 events have them; consumers ignore extras. The Pillar A I3 contract for additive schema changes is preserved (the version field discriminates breaking changes, not additive ones).
- **I4 (reproducible state):** `lookup_cache` is deterministic — the same ledger state + the same email + the same `now` clock produce the same result on every call. The cache primitive's emit is deterministic; replaying the ledger reconstructs the cache state as a function of the ledger's event order. The wall-clock dependency is pinned by the `now` kwarg for test reproducibility (per ADR-0031 D140 deterministic-clock precedent).
- **I5 (observable by default):** `email_verification_cache_hit` events carry `person_id` + `email` + `cached_result` + `cached_at` + `cache_age_days` + `channel` + `_emitted_by`. Pillar G dashboards have scalar-field queries for every dimension. The extended `cost_incurred` events carry `email` + `verification_response` — operators auditing "what did Reoon say for this email?" gain per-event-class lookup without joining to a separate cache store.
- **I6 (tests prove invariants):** `tests/test_email_verification_cache.py` ships 48 per-method unit tests (EmailVerificationCacheResult invariants × 7 + lookup_cache happy paths × 13 + TTL boundary × 5 + deterministic clock × 2 + build_*_payload contracts × 11 + module constants × 3 + ledger-error fallback × 1 + verify_with_reoon integration × 6). `tests/test_multi_channel_coherence.py::TestEmailVerificationCache` un-skipped 4 rows pin the integration-level contract. The load-bearing legal-liability + privacy invariants (D148) inherit the Layer 1 defense unchanged (the cache primitive does NOT introduce `source_list` aggregation).
- **I7 (cost is a first-class concern):** The cache primitive IS the cost-avoidance signal. `email_verification_cache_hit` events are the operator-visible "we saved a Reoon call" signal. Pillar G dashboards compute cost-avoidance hit-rate as `email_verification_cache_hit_count / (email_verification_cache_hit_count + cost_incurred.source=reoon count)`. The cache primitive itself does NOT emit `cost_incurred` (rule-based + framework-local; zero per-call cost).
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0034 row. The per-week trajectory in HANDOFF-pillar-e-week-6.md (TBD this commit) names planned ADRs 0035+.

Does not weaken any invariant. I7's enforcement extends to the cost-avoidance signal (the `email_verification_cache_hit` event makes Reoon-spend-avoidance operator-visible alongside the existing `cost_incurred` events).

### Downstream pillar impact

Per the Pillar A / B / C / D / E Week 1 + 2 + 3 convention (every ADR explicitly names cross-pillar impact):

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring is per-touch (not per-discovery-source or per-email); the cache primitive doesn't change Pillar F's contracts. The `email_verification_cache_hit` events surface "this email was re-verified" — Pillar F MAY consume this to suppress drafting for emails that have repeatedly bounced (TBD per Pillar F's ADR; today the bounce handling is Pillar D's auto-unsubscribe path).

* **Pillar G (observability).** Pillar G's cost-per-quality-prospect dashboard consumes `email_verification_cache_hit` events to compute the per-source cache-hit-rate. The Reoon-spend dashboard aggregates as: `total_reoon_spend = sum(cost_incurred.source=reoon.amount_usd)`; `cache_hit_rate = email_verification_cache_hit_count / (cache_hit_count + cost_incurred.source=reoon_count)`. Per the cache event's `channel: "email"` stamp, Pillar G's per-channel cost-avoidance dashboards surface email-channel cache hits in the email funnel. The new `email` field on `cost_incurred` events feeds the per-email cost-attribution drill-down ("which emails consume the most Reoon spend?").

* **Pillar H (daemon + dispatcher).** Pillar H's daemon dispatches the email-channel sends; the cache primitive is dispatcher-side (the daemon's `enrich_emails.py` invocation goes through the wrap automatically). Pillar H's per-stage parallelism limits become per-source-skill (per Pillar E Week 2 D152) + per-cache-hit-rate (a future Pillar H tuning: "if cache-hit-rate is high, throttle Reoon less aggressively because the marginal call is mostly cached anyway"). TBD per Pillar H's ADR.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-email cache. The Pillar I doctor preflight extends to check (a) the cache primitive's TTL constant is the single source of truth (no second `30` literal); (b) the cache-hit-rate per email over a rolling window (anomaly detection on an email that suddenly stops hitting cache — a sign of upstream Reoon emit issue or operator manual override); (c) the cost event extension's field shape (`email` + `verification_response`) is present on all post-Week-4-5 cost events. The Pillar I CLI ships `python -m orchestrator.email_verification_cache purge --email <addr>` (force-evict; operator override) + `python -m orchestrator.email_verification_cache replay --since <date>` (backfill historical events with the extended shape if possible) — both deferred from Week 4-5 scope.

* **Pillar J (security + compliance).** Pillar J's GDPR-forget transaction inherits the existing `forget_append` primitive (ADR-0004 §Decision step 2) + adds steps that purge cache events for a deleted subject. The cache event carries `person_id` (defaulting from the cached event's person_id); the existing `person_id`-keyed purge predicate covers them. The extended `cost_incurred` events also carry `verification_response` (which contains the email's Reoon-side metadata — `is_disposable`, `is_role_account`, etc.); Pillar J's purge MUST verify the cost event's `verification_response` field is purged alongside the `email` field (TBD per Pillar J's ADR). Pillar J's CAN-SPAM compliance gate is unchanged by Pillar E Week 4-5 — the cache primitive doesn't write to suppression YAML (that's Pillar D's auto-unsubscribe path).

## Migration / rollout

The Week 4-5 deliverable is the cache primitive module + the per-call-site integration in `enrich_emails.py` + the un-skipped coherence test rows + the cross-pillar audit row extension + the unit-test file.

**Operator-facing changes (Week 4-5):**

1. **No new pending migrations.** `runner.pending()` still returns 17 (the Pillar D + Pillar E Week 1-3 final state). The cache primitive is content-additive (NEW event class; cost event schema extension is content-additive — pre-existing consumers ignore extras). No schema changes to the ledger or vault that require a Pillar B migration.

2. **New module — `orchestrator/email_verification_cache.py`** — importable via `from orchestrator import email_verification_cache`. The public surface: `lookup_cache`, `build_email_verification_cache_hit_payload`, `EmailVerificationCacheResult`, `DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS`, `EMITTED_BY`, `CHANNEL_VALUE`. The CLI surface: `python orchestrator/email_verification_cache.py lookup --email <addr> [--ttl-days N] [--person-id <pid>] [--apply] [--json]`.

3. **`orchestrator/enrich_emails.py::verify_with_reoon` signature extended** with optional kwargs `led` / `person_id` / `run_id` (default None preserves the legacy signature). When the caller opts in via `led`, the function performs the cache lookup prelude + owns the cost emit.

4. **`orchestrator/enrich_emails.py::emit_reoon_cost_event` signature extended** with optional kwargs `email` / `verification_response` (default None preserves the legacy signature). The cost event now optionally carries the cache substrate fields.

5. **`orchestrator/enrich_emails.py::process_one` refactored** to pass the new kwargs to `verify_with_reoon` + drop the explicit `emit_reoon_cost_event` call (now handled inside the function). Operators running `enrich_emails.py` see no behavior change; cost events fire as today (with the extended substrate fields populating the cache for future lookups).

6. **New CLI subcommand — `python orchestrator/email_verification_cache.py lookup`** — the cache primitive's command-line surface. `--apply` flag controls whether the cache_hit event is appended to the ledger (live mode) or just reported (dry-run, the default).

7. **Existing operators with pre-Pillar-E-Week-4 cost events** see no change. The cache primitive is content-additive; pre-existing `cost_incurred` events stay unchanged + are invisible to the cache (treated as miss). The Week 4-5 commit's only modification to `enrich_emails.py` is the wrap extension + the signature extensions; no existing event is rewritten.

**Operator-facing changes (Pillar E Weeks 6-8+, planned):**

8. **Week 6-8 ships the tier auto-assignment primitive + the `tier_suggested` event class** (per ADR-0032 D145). Separate primitive; consumes Apollo organization_size + industry + funding_stage signals + the cache primitive's per-email metadata (e.g., `is_role_account` from the cached Reoon response). ADR-0035+ — TBD.

9. **Week 9-11 ships the per-skill `discovery_lineage:` stamping refactor + the coordinating vault migration** (per ADR-0032 D142 + D146). The `research-prospect` integration coincides. ADR-0036+ — TBD.

10. **Week 12's binding exit-criterion test (`TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`) un-skips.** With the dedup primitive (Week 2-3) + the cache primitive (this commit) + the tier-suggestion primitive (Week 6-8) + the per-skill lineage stamping (Week 9-11) shipped, the cross-cutting three-skills-one-day-one-credit-each scenario is testable end-to-end.

11. **Pillar I CLI extensions (Weeks 43-48)** — `python -m orchestrator.email_verification_cache purge --email <addr>` (force-evict) + `python -m orchestrator.email_verification_cache replay --since <date>` (backfill historical events). Deferred from Week 4-5 scope.

**The Week 4-5 commit's verification surface:**

```python
# 1. The cache primitive module exists + is importable.
$ python -c "from orchestrator.email_verification_cache import lookup_cache, EmailVerificationCacheResult, build_email_verification_cache_hit_payload, DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS, EMITTED_BY, CHANNEL_VALUE"

# 2. The cache primitive unit tests pass.
$ python -m pytest tests/test_email_verification_cache.py -v
# Expected: 48 per-method tests pass.

# 3. The coherence test vehicle's Week 4-5 rows un-skip + pass.
$ python -m pytest tests/test_multi_channel_coherence.py::TestEmailVerificationCache -v
# Expected: ALL 4 rows passing (no skips).

# 4. The cache CLI runs.
$ python orchestrator/email_verification_cache.py lookup --email dylan@example.com --json
# Expected: JSON output reporting miss (or hit if a recent Reoon cost event exists for the email).

# 5. The full suite is green at +N tests.
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 2466 passed (the +52 comes from: 48 new email_verification_cache unit tests + 4 un-skipped coherence rows).

# 6. ADR-0034 exists; README index gains the row; PILLAR-PLAN §6 Pillar E row updated.
$ ls docs/adr/0034-pillar-e-email-verification-cache.md
$ grep "0034" docs/adr/README.md
$ grep "Week 4-5 ✓" docs/PILLAR-PLAN.md
```

### Existing-operator seed

Pillar E Week 4-5 ships NO new migrations + NO new ledger-state primitives that require an existing-operator seed action.

**Bootstrap-step seed for existing operators (Yang):**

The Week 4-5 commit is content-additive — no operator action required. The cache primitive is callable via the new CLI; the `enrich_emails.py` dispatcher auto-integrates the cache prelude on the next Reoon-verification run.

For Yang specifically (the current sole operator), the pre-existing `cost_incurred.source=reoon` events (the historical Reoon spend) carry NEITHER the `email` nor the `verification_response` fields — they are invisible to the cache. The cache populates GOING FORWARD: the next `python orchestrator/enrich_emails.py` run that verifies a new email emits a Reoon cost event with the extended substrate; subsequent verifications within TTL find that event as the cache substrate. The first cache hit is operator-visible:

```bash
python -m orchestrator.ledger grep --type email_verification_cache_hit | head
```

If the operator wishes to backfill historical cost events with the extended shape (e.g., to seed the cache with all pre-Pillar-E-Week-4 verifications), the Pillar I CLI's `python -m orchestrator.email_verification_cache replay --since <date>` extension ships the one-time backfill ergonomic. The backfill requires re-fetching the Reoon response (the original response is not preserved in pre-Pillar-E-Week-4 events); operators with high pre-existing volume may prefer letting the cache populate organically over time.

The first Pillar E week that ships a vault migration requiring an existing-operator seed action (TBD — likely Pillar E Week 9-11's vault migration adding per-Person `discovery_lineage:` block) WILL include the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface the cache primitive integrates with (no engine change required).
- ADR-0002 (cooldown rules) — the inclusive-lower-bound boundary convention the TTL inherits (D157 boundary semantics).
- ADR-0003 (channel as first-class policy predicate) — the cross-channel rule whose behavior the cache events do NOT trigger (events don't end in `_confirmed`).
- ADR-0004 (suppression rules + GDPR-forget) — the `forget_append` primitive Pillar J's purge transaction extends to cache events.
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention the cache primitive extends content-additively (D156); the BudgetWindowCapRule consumer is unaffected by the extension.
- ADR-0009 (migration framework) — Pillar E vault/ledger migrations (Week 9-11+) will register into the existing framework; Week 4-5 ships ZERO migrations.
- ADR-0010 (ledger migrations) — the D17 `_emitted_by` convention the cache primitive's events inherit.
- ADR-0011 (vault migrations) — Pillar E Person note migrations (Week 9-11+) consume the existing `add_frontmatter_block_text` + `iter_person_notes` primitives.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — the D24 hybrid synthetic fixture pattern Pillar E Week 12 extends.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-event invariant the cache events inherit (with `channel: "email"` per D155); the D36 existing-operator-seed pattern Pillar E inherits; the D37 exit-criterion vehicle Pillar E extends.
- ADR-0025 (Pillar D foundation) — the D99 cross-pillar surface audit Pillar E mirrors per ADR-0032 D146 + extends per D159.
- ADR-0026 (Pillar D Week 2 — rule-based classifier) — **THE PRECEDENT FOR PILLAR E SIBLING PRIMITIVES.** D102 (classifier module placement — `orchestrator/reply_classifier.py`) → D154 (cache module placement — `orchestrator/email_verification_cache.py`). The sibling-of-the-wrapped-call-site placement pattern continues from ADR-0033 D149.
- ADR-0031 (Pillar D exit-criterion close) — the D136 deterministic-clock pattern the cache primitive's `now` kwarg inherits.
- ADR-0032 (Pillar E foundation) — D144 (email-verification cache shape — D155-D157 implement); D146 (cross-pillar surface audit D159 extends); D147 (exit-criterion vehicle scope; Week 4-5 un-skips 4 of 4 `TestEmailVerificationCache` rows).
- ADR-0033 (Pillar E Week 2 — pre-enrichment dedup primitive) — **THE SIBLING PRIMITIVE PRECEDENT.** D149 (dedup module placement) → D154 (cache module placement — same shape). D150 (dedup event emit-shape with `channel: "none"`) → D155 (cache event emit-shape with `channel: "email"` — asymmetric per the cache's email-specific scope). D152 (per-skill integration discipline — four skill sites) → D158 (per-call-site integration — one site). D153 (cross-pillar audit extension) → D159 (same pattern). The Week 3 amendment trajectory is the per-skill extension pattern; this ADR is a fresh ADR (not an amendment) because Week 4-5 ships a new pillar primitive with its own emit-shape + substrate + TTL decisions.
- `docs/PILLAR-PLAN.md` §2 Pillar E — exit criterion (binding text); §5 "What we will not do" — Pillar E adjacent constraints; §6 Pillar E row Notes column extended to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4-5 ✓" in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D157's 30-day TTL choice (false-positive cache hit is one bounce; false-negative is one Reoon credit; 30-day TTL bounds both).
- `docs/RISK-REGISTER.md` R001 (identity-graph false-merge cascade) — risk the cache primitive does NOT regress (the cache operates on emails, not identity keys). R018 + R019 + R020 (all named in ADR-0032 §Context) — the Week 4-5 implementation does not introduce new risks; R020 (email-verification cache staleness) is structurally mitigated by the 30-day TTL + the existing bounce-handling flow.
- `docs/SOURCES-OF-TRUTH.md` — no new row added (the cache primitive emits events; the ledger remains the SoT; the cost event extension is content-additive within the existing SoT).
- `.planning/REVIEW-pillar-e-surface-audit.md` — extended in this commit with the Week 4-5 section per D159.
- `.planning/HANDOFF-pillar-e-week-4.md` — the per-week handoff that scoped Week 4-5.
- `.planning/HANDOFF-pillar-e-week-6.md` — written in this commit; scopes Week 6-8 (the tier auto-assignment primitive per ADR-0032 D145).
- `orchestrator/email_verification_cache.py` — the primitive module D154 names.
- `orchestrator/enrich_emails.py` — the wrapped call site (`verify_with_reoon`) the cache primitive integrates with via the D158 prelude.
- `orchestrator/discovery_dedup.py` — the SIBLING primitive (per ADR-0033) whose shape this primitive mirrors.
- `orchestrator/ledger.py` — the substrate the cache primitive derives from (`all_events()`) + the cost-event extension's index population (`_idx_email`).
- `orchestrator/policy/budget.py` — the `cost_incurred` consumer whose behavior the schema extension does NOT change (content-additive — extra fields ignored).
- `tests/test_email_verification_cache.py` — the primitive's unit tests (48 tests).
- `tests/test_multi_channel_coherence.py::TestEmailVerificationCache` — the un-skipped 4 of 4 rows that pin the integration-level contract.
- `tests/test_enrichment_costs.py` — the pre-existing cost-emission tests that continue to pass under the content-additive schema extension.
- Forward-references (planned):
  - **ADR-0035+** (Pillar E Week 6-8): tier auto-assignment — `orchestrator/tier_assignment.py` + `tier_suggested` event + per-signal weights against Yang's operator-tagged corpus. May consume the cache primitive's per-email metadata (e.g., `is_role_account` from cached Reoon responses) as one of the firmographic-adjacent signals.
  - **ADR-0036+** (Pillar E Week 9-11): per-skill `discovery_lineage:` stamping refactor + the `research-prospect` integration + the coordinating vault migration (`vault/0005_add_discovery_lineage_to_identity_keys` — TBD shape).
  - **ADR-00NN** (Pillar E Week 12): exit-gate close — the binding three-skills-one-day exit-criterion test un-skips.
  - **Pillar G dashboards** (Weeks 31-42): cost-per-quality-prospect dashboard consuming `cost_incurred` + `discovery_dedup_hit` + `email_verification_cache_hit` events; per-source cost-avoidance funnel via cache hit-rate per email channel.
  - **Pillar I CLI** (Weeks 43-48): aggregation of per-ADR seed blocks + the cache primitive's `purge --email` + `replay --since` extensions + the doctor-preflight extension for cache-hit-rate anomaly detection + the per-skill stamping refactor's CLI surface.
  - **Pillar J GDPR-forget** (Weeks 49-52): the per-Person cache event purge step added to the existing `forget_append` flow + the verification_response field-level purge on the extended cost events.
