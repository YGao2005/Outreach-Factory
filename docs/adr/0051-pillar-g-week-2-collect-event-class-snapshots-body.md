# ADR-0051: Pillar G Week 2 — `collect_event_class_snapshots` body, `observability_class_uncatalogued` diagnostic emit with `kind` field, ts-missing refuse-loud posture, deterministic snapshot ordering, channel-on-every-event invariant verification

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 2 primitive body)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape — `MetricSnapshot` frozen dataclass + `EVENT_CLASS_CATALOG` closed-set frozenset enumerating Pillar A-F event classes + `_BREAKDOWN_DIMS_ALLOWED` privacy-respecting closed-set + `OBSERVABILITY_NEW_EVENT_CLASSES` frozenset (the two NEW Pillar G classes: `observability_class_uncatalogued` + `slo_violation_detected`) + `collect_event_class_snapshots` SIGNATURE — at `orchestrator/observability.py`. The Week 1 commit shipped the contract + the closed-set frozensets + the dataclass + the signature (body raises `NotImplementedError`). The Week 1 cross-pillar surface audit at `.planning/REVIEW-pillar-g-surface-audit.md` recorded **ONE P2 carry-forward (load-bearing) + THREE P3 carry-forward** to be addressed at this Week 2 commit.

Pillar G Week 2 ships the **primitive body** + the **`observability_class_uncatalogued` emit** per the ADR-0050 D273 trajectory table. The four concerns this ADR resolves:

1. **The `collect_event_class_snapshots` body must walk the ledger statelessly, aggregate by event class, and emit one `MetricSnapshot` per qualifying class.** Per ADR-0050 D272's stateless-aggregation contract (the R033 cache-substrate-divergence mitigation), every call re-walks `Ledger.all_events()` + filters by window + groups by event class. The body's per-call cost is O(N) at v1 scale (~5K events) → sub-second; Pillar H may revisit at multi-machine scale per ADR-0050 §Downstream pillar impact.

2. **The ts-missing posture — silent-skip vs refuse-loud vs separate-bucket.** Per the Pillar G Week 1 cross-pillar surface audit row 11 P2-1 (LOAD-BEARING carry-forward): the existing `orchestrator/funnel.py::aggregate_reply_classified` filter at `funnel.py:205` uses `ts = ev.get("ts") or ""` followed by `if ts < since_iso: continue` — events with missing `ts` get `ts = ""` (empty string), which sorts BEFORE every valid ISO timestamp, so they are silently SKIPPED with no operator-visible diagnostic. The audit recommended Pillar G Week 2 pick (b) refuse-loud (per I7 refuse-loud convention) over (a) inherit-silent-skip and (c) separate-bucket. D279 implements (b).

3. **The `observability_class_uncatalogued` diagnostic emit's payload shape — one event class with a `kind` field vs separate event classes per anomaly.** The Pillar G Week 1 audit row 11 explicitly recommended *extending* the closed-set `observability_class_uncatalogued` diagnostic event to include ts-missing records (single event class; the `kind` field disambiguates `"uncatalogued"` vs `"missing_ts"`). D279 implements the recommendation; the rejected alternative (separate event class `observability_event_missing_ts`) is documented at D279's alternatives.

4. **Deterministic output + channel-on-every-event invariant verification.** Pillar G's primitive output feeds into the funnel CLI per ADR-0050 D276(a)'s one-CLI-invocation invariant + the Pillar D Week 12 byte-identical determinism contract per ADR-0031 D140. The Week 2 commit MUST verify (a) the snapshot list is sorted alphabetically by `event_class` (deterministic ordering); (b) the `per_breakdown_counts` dict is alphabetically sorted (operator-readable order); (c) the `MetricSnapshot.channel` field carries the single channel value when all in-window events of the class are homogeneous + None when heterogeneous/missing (channel-on-every-event invariant per ADR-0014 D33 + the Pillar G Week 1 audit row 11 P3-1 carry-forward).

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens the consumer surface)** — UNCHANGED from ADR-0050; D278's implementation IS the mitigation (the closed-set `EVENT_CLASS_CATALOG | OBSERVABILITY_NEW_EVENT_CLASSES` is the catalog drift detector + `observability_class_uncatalogued` emit is the operator-visible signal).
- **R034 (Diagnostic emit at every primitive call inflates the ledger when catalog drift persists)** — NEW. When operators consume Pillar G dashboards continuously (e.g., Grafana auto-refresh hitting the primitive every minute) AND the catalog is in drift (e.g., a new event class shipped without updating `EVENT_CLASS_CATALOG`), the primitive emits `observability_class_uncatalogued` per call → up to ~1440 diagnostics per day per drift-condition. Mitigation by design: at-most-ONE emission per `kind` per call (NOT per-event-per-call); the per-day cap is ~2880 diagnostics (two kinds × 1440 calls). Operators see the recurring signal in the dashboard + fix the catalog. Pillar I per-tenant audit-tooling extends to filter `_emitted_by: "observability"` diagnostics out of the per-tenant per-operator override-rate dashboards. Severity 1 / likelihood 2 — DOWNGRADED from initial assessment because the per-call rate-limit caps the worst case at ~2880 diagnostics/day per single-tenant operator.

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12.

## Decision

### D278. `collect_event_class_snapshots` body — stateless per-call ledger walk + closed-set aggregation + composite-key mirror of `funnel._composite_key`

`orchestrator/observability.py::collect_event_class_snapshots` body lands per the ADR-0050 D272 contract:

```python
def collect_event_class_snapshots(
    led: Ledger,
    *,
    since: datetime,
    now: datetime | None = None,
    expected_classes: frozenset[str] = EVENT_CLASS_CATALOG,
    breakdown_by: tuple[str, ...] = (),
) -> list[MetricSnapshot]:
    # 1. Refuse-loud on disallowed breakdown dims (privacy invariant).
    # 2. Normalize `since` to ISO string for string-compare on ts.
    # 3. Walk `led.all_events()`:
    #    - track ts-missing diagnostic state (rate-limited);
    #    - skip events with ts < since;
    #    - track uncatalogued diagnostic state (rate-limited);
    #    - aggregate qualifying events per event class (count + channel
    #      set + per-breakdown counter + oldest/newest ts).
    # 4. Emit diagnostics — at-most-ONE per kind per call.
    # 5. Return snapshots sorted alphabetically by event_class.
```

The "known classes" set is `expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES` — Pillar G's own diagnostic emits aggregate as normal (preventing the recursive-uncatalogued infinite loop where the next call sees the previous call's `observability_class_uncatalogued` event and emits another diagnostic).

The `_composite_key` helper mirrors `orchestrator.funnel._composite_key` per the deterministic-output contract per ADR-0031 D140 + ADR-0050 D276(a). Missing or non-string fields render as the literal `"none"`; multi-field composite keys are pipe-delimited.

The stateless contract is preserved per ADR-0050 D272 + R033 mitigation — no module-level state; every call re-walks the ledger.

### D279. `observability_class_uncatalogued` diagnostic emit — single event class with `kind` field; at-most-ONE per kind per call; ts-missing refuse-loud posture

When the primitive's walk encounters either (a) an event with `type` NOT in `expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES` OR (b) an event with missing or empty `ts`, it tracks the offending event's `type` (first-seen) + total count + (for case b only) `person_id` (first-seen if any). After the walk completes, it emits AT MOST ONE `observability_class_uncatalogued` event PER KIND per call:

```jsonc
// kind="uncatalogued" — catalog drift (R031 mitigation)
{
  "type": "observability_class_uncatalogued",
  "ts": "<now ISO>",
  "kind": "uncatalogued",
  "offending_type": "<first-seen-unknown-class>",
  "count": <total seen in call>,
  "channel": null,
  "_emitted_by": "observability",
  "v": 1
}
// kind="missing_ts" — ts-missing posture (P2-1 carry-forward)
{
  "type": "observability_class_uncatalogued",
  "ts": "<now ISO>",
  "kind": "missing_ts",
  "offending_type": "<first-seen-ts-missing-class>",
  "person_id": "<first-seen-person-id-or-null>",
  "count": <total seen in call>,
  "channel": null,
  "_emitted_by": "observability",
  "v": 1
}
```

Two-kind closed-set per `_DIAGNOSTIC_KINDS = frozenset({"uncatalogued", "missing_ts"})`. The Pillar G Week 1 cross-pillar audit row 11's P2-1 carry-forward recommended option (b) refuse-loud — D279 picks (b) by emitting the diagnostic with `kind="missing_ts"`. The `_emitted_by: "observability"` audit marker matches the per-event audit-marker discipline per ADR-0010 D17 (mirrors the `_recovered_by` marker on Pass C reconcile emits per ADR-0049 D262).

The "ts-missing event" is NOT aggregated into the per-class snapshot — it contributes ONLY to the `kind="missing_ts"` diagnostic. Operators investigating the producer use the diagnostic's `offending_type` + `person_id` + ledger `_emitted_by` audit-trail to locate the producer.

### D280. Deterministic snapshot ordering — alphabetical by `event_class` + sorted `per_breakdown_counts`

`collect_event_class_snapshots` returns the snapshot list sorted alphabetically by `event_class` per the deterministic-output contract per ADR-0031 D140 + ADR-0050 D276(a). Each snapshot's `per_breakdown_counts` dict is constructed via `dict(sorted(...))` — Python 3.7+ guarantees dict insertion order = iteration order, so operators reading the JSON output of the funnel CLI's Pillar G extension at Week 3+ see the per-breakdown counts in ascending alphabetical key order.

The byte-identical-across-consecutive-calls contract per ADR-0031 D140 holds at the primitive level when (a) the ledger state is fixed; (b) the `now` kwarg is fixed (the diagnostic emit's `ts` field IS sensitive to `now`); (c) the diagnostic emit's per-call rate-limiting holds. Tests pass `now=` for byte-identical reproducibility per ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265.

### D281. Channel-on-every-event invariant — `MetricSnapshot.channel` surfaces homogeneous channel; None on heterogeneous / missing

Per ADR-0014 D33's channel-on-every-event invariant + ADR-0050 D276(c) + the Pillar G Week 1 cross-pillar audit row 11 P3-1 carry-forward, `MetricSnapshot.channel` is computed as:

```python
# Inside collect_event_class_snapshots's snapshot-building loop:
chs = channels_per_class.get(ev_type, set())
non_null_chs = {c for c in chs if c}
if len(chs) == 1 and len(non_null_chs) == 1:
    snap.channel = next(iter(non_null_chs))   # single homogeneous channel
else:
    snap.channel = None                       # heterogeneous / missing / mix
```

The interpretation:

- **Single homogeneous channel** (e.g., `send_intent` events all carry `channel="email"` per the per-channel two-phase convention) → `snap.channel = "email"`. Operators read the per-class channel directly.
- **No channel field** (e.g., `enrolled`, `cost_incurred`, Pillar E primitive events, Pillar F draft-quality events) → `snap.channel = None`. Operators consult the per-event-class semantic (the class doesn't carry channel by design per ADR-0014 D33).
- **Heterogeneous channels** (e.g., `reply_classified` events with `channel` in `{email, linkedin, twitter}`) → `snap.channel = None`. Operators pass `breakdown_by=("channel",)` to get per-channel counts inside `per_breakdown_counts`.
- **Mix of channel-present and channel-missing within a single class** (pathological — usually indicates a producer bug where one emit site forgot to include the channel field) → `snap.channel = None`. Operators see the inconsistency via the per-breakdown breakdown showing `"none"` keys alongside channel-named keys.

The `_BREAKDOWN_DIMS_ALLOWED` frozenset already includes `channel` at ADR-0050 D272's Week 1 ship — the Pillar G Week 1 audit P3-1 carry-forward is satisfied by the Week 1 commit's frozenset shape; the Week 2 test surface adds an explicit regression-barrier test (`tests/test_observability.py::TestModuleConstants::test_breakdown_dims_allowed_includes_channel_P3_1`).

A future Pillar G Week 3+ commit MAY extend D281 to refuse-loud on the pathological "mix of channel-present and channel-missing" cell when applicable (per the per-event-class channel-required catalog at ADR-0014 D33 — the per-channel two-phase + reply + reconcile events are channel-required; discovery / enrollment / cost / Pillar E / Pillar F draft-quality are exempt). D281 defers the catalog-driven refuse-loud to a future week; Week 2's posture is "surface the inconsistency via the snapshot's channel=None + per_breakdown_counts['none|...'] cells."

## Alternatives considered

### D278 alternatives (`collect_event_class_snapshots` body)

1. **Stateful primitive with module-level cache + per-call cache-hit check.** Rejected — violates ADR-0050 D272's stateless contract + R033 mitigation. The cache-substrate-divergence risk on multi-process operators (Pillar H daemon + manual CLI + Grafana auto-refresh all hitting the same ledger but computing at different windows) is the design's core concern.
2. **Subprocess CLI invocation that returns a JSON blob (Pillar D Week 12 funnel CLI's pattern).** Rejected — the funnel CLI is an OPERATOR-facing surface (subprocess overhead acceptable for batch reads). Pillar G's primitive is INTERNAL to Pillar G's per-pillar adapters (Pillar G Week 3 OTel SDK init + Week 4 Prometheus exporter + Week 10-11 per-Person dashboards). Subprocess overhead would dominate the per-class-per-snapshot cost.
3. **Async ledger walk via `anyio` task-group.** Rejected — the ledger's `all_events()` is a sync method returning an in-memory list; async wrap-up adds complexity without per-call cost reduction at v1 scale (~5K events). Pillar H may revisit if multi-process scale surfaces.
4. **Use `Ledger._idx_person` to walk per-Person instead of `Ledger.all_events()`.** Rejected — the primitive aggregates per event class, not per Person. Walking `_idx_person` would iterate persons (~hundreds) × per-Person events (~tens) = ~thousands of dict lookups vs the ~5K single-pass walk of `all_events()`. The per-Person walk is also incomplete (events without `person_id` — e.g., `migration_event`, `send_run_complete` — would be missed).

### D279 alternatives (`observability_class_uncatalogued` diagnostic emit)

1. **Separate event class `observability_event_missing_ts` for the ts-missing case (vs single class with `kind` field).** Rejected — the Pillar G Week 1 cross-pillar audit row 11 explicitly recommended *extending* the existing `observability_class_uncatalogued` event class. Adding a third class to `OBSERVABILITY_NEW_EVENT_CLASSES` (currently two classes per ADR-0050 D273) would amend the Week 1 foundation's closed-set commitment. The single-class + `kind` field design keeps the closed-set at two members + preserves the contract-level invariant test `test_observability_new_event_classes_frozenset` un-changed.
2. **Silent-skip the ts-missing event (inherit `funnel.py:205`'s legacy behavior).** Rejected — the audit's P2-1 carry-forward explicitly named the silent-skip behavior as the load-bearing P2 carry-forward; the framework's I7 refuse-loud convention requires that operator-invisible producer bugs surface via the diagnostic event.
3. **Refuse-loud at the call boundary via `ValueError`-on-ts-missing.** Rejected — ts-missing events are a producer-side bug; the primitive's call site (a Pillar G dashboard adapter OR the funnel CLI's extension at Week 3+) is downstream of the producer. Refusing at the call boundary would break the dashboard rendering on every operator-visible ts-missing event — operators would see broken dashboards instead of the diagnostic event surfacing the bug. The diagnostic-emit posture preserves dashboard functionality while surfacing the producer-side bug to operators via the per-`_emitted_by: "observability"` ledger query.
4. **Per-call hard cap on diagnostic emits (e.g., AT MOST 10 emits across both kinds).** Rejected — at-most-ONE per kind per call IS the rate-limit; doubling to two kinds × ONE = at-most-TWO per call IS the cap. A higher cap would amplify R034 (ledger inflation); a tighter cap (e.g., one diagnostic across both kinds) would lose the per-kind distinction operators need for triage.

### D280 alternatives (deterministic ordering)

1. **Random / insertion-order snapshot list.** Rejected — violates the deterministic-output contract per ADR-0031 D140 + ADR-0050 D276(a). Operators running `python orchestrator/funnel.py --since 30d` twice against a fixed ledger state would see different JSON output across the two calls. The byte-identical-across-consecutive-invocations property is the funnel CLI's contract.
2. **Per-pillar grouping (Pillar A's classes first, then Pillar B, ...).** Rejected — adds coupling to the per-pillar foundation ADR's event-class enumeration order; if a pillar's enumeration order shifts (a class moves to a different ADR row), the snapshot order drifts. Alphabetical is stable across ADR amendments.
3. **Sort by `total_count` descending (largest-volume classes first).** Rejected — count-based ordering is RUN-time-dependent (a single new event changes the snapshot order). The deterministic-output contract requires byte-identical across consecutive calls; alphabetical preserves this.

### D281 alternatives (channel-on-every-event invariant)

1. **One snapshot per `(event_class, channel)` pair (instead of one snapshot per event_class).** Rejected — the existing `test_metric_snapshot_shape` test pins ONE snapshot per class shape. The `(class, channel)` cross-product would N×M-ify the snapshot list; operators consuming the primitive via per-Person dashboards (D277 trajectory at Week 10-11) would see ~50 classes × ~4 channels = ~200 snapshots per call instead of ~50.
2. **Always set `MetricSnapshot.channel = None` (defer per-channel breakdown to the breakdown_by kwarg).** Rejected — for the homogeneous-single-channel case (e.g., `send_intent` is always `channel="email"`), operators read the per-class channel directly from `snap.channel` without passing `breakdown_by=("channel",)`. The homogeneous case is the COMMON case at the Pillar D Week 12 funnel CLI's existing breakdown shape; preserving this affordance is operator-ergonomic.
3. **Refuse-loud on the pathological "mix of channel-present and channel-missing" case at Week 2.** Rejected (deferred to Week 3+) — the per-event-class channel-required catalog (which classes carry channel by ADR-0014 D33 vs which are exempt) is implicit in the per-pillar foundation ADRs' "new event classes" tables; making it explicit at Week 2 would require introducing a new module-level closed-set (e.g., `_CHANNEL_REQUIRED_CLASSES`). The Week 2 posture surfaces the inconsistency via `snap.channel=None`; Week 3+ may extend.

## Consequences

### Positive

- **R031 mitigation operationalized** — the catalog drift detector is LIVE; future event-class additions without updating `EVENT_CLASS_CATALOG` surface immediately via `observability_class_uncatalogued` events visible to operators.
- **P2-1 carry-forward from Pillar G Week 1 cross-pillar audit row 11 resolved** — the ts-missing posture is REFUSE-LOUD; the `funnel.py:205` silent-skip bug class no longer occurs in the new primitive.
- **P3-1 carry-forward from Pillar G Week 1 cross-pillar audit row 11 resolved** — the `_BREAKDOWN_DIMS_ALLOWED` frozenset's channel inclusion is now pinned by a regression-barrier test.
- **The deterministic-output contract per ADR-0031 D140 holds at the primitive level** — Pillar G Week 3+ funnel CLI extensions inherit the byte-identical-across-consecutive-calls property.
- **The channel-on-every-event invariant per ADR-0014 D33 has a per-snapshot surface** — operators read the per-class channel directly from `MetricSnapshot.channel` in the homogeneous case.
- **The privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 has a regression-barrier surface** — every disallowed breakdown dim refuses-loud at the primitive's call boundary.

### Negative

- **The primitive is now side-effectful** — `collect_event_class_snapshots` writes to the ledger (the diagnostic emit). Pillar G Week 1's signature did not promise side-effect-freedom, but operators expecting a pure-read primitive may be surprised. The module docstring + the `Side effects` section of the primitive's docstring document this clearly.
- **R034 (NEW) — diagnostic emit at every primitive call inflates the ledger when catalog drift persists** — operators consuming Pillar G dashboards continuously (Grafana auto-refresh) MAY see ~2880 diagnostics/day per single-tenant operator if the catalog is in drift. Mitigation: at-most-ONE per kind per call; operators fix the catalog promptly when they see the recurring signal.
- **The test surface adds ~570 LOC** — `tests/test_observability.py` ships 56 tests covering the cell-level matrix (every disallowed dim × every allowed dim × per-Pillar-A-F class sample × every channel cell × every diagnostic kind × every deterministic-clock cell × recursive-uncatalogued protection × empty/out-of-window edge cases). The LOC is content-additive; the file is well below the ~7500 LOC split threshold flagged by ADR-0037 D172.

### Neutral

- **The primitive's per-call cost stays at O(N)** — the per-Pass-C reconcile heal's existing per-call cost is also O(N) per ADR-0049 D264; Pillar G's primitive consumes the same `all_events()` walk pattern. Pillar H may revisit at multi-machine scale.
- **The `_emitted_by: "observability"` audit marker matches the `_recovered_by` pattern from ADR-0049 D262** — Pillar I per-tenant audit-tooling consuming `_emitted_by` for per-pillar provenance filtering inherits the new marker uniformly.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — Pillar G's primitive WRITES to the ledger (the diagnostic emit) per the existing append-only contract. The ledger remains SoT; the snapshot list is a denormalized rebuildable view per `docs/SOURCES-OF-TRUTH.md`.
- **I2 (Atomicity contract).** Compliant — the primitive's diagnostic emits use `Ledger.append` which is atomic per the existing Phase 5.5 contract.
- **I3 (Single source of truth).** Compliant — the snapshot list is computed from the ledger every call; no derived state is cached.
- **I4 (Determinism).** Compliant per D280 — alphabetical snapshot ordering + sorted per-breakdown-counts + `now` kwarg for deterministic-clock + the diagnostic emit's per-call rate-limit.
- **I5 (Refuse loud).** Compliant per D279 (ts-missing posture) + D278 (uncatalogued posture) + the privacy invariant per breakdown_by refuse-loud.
- **I6 (No silent state).** Compliant — every state change (the diagnostic emit) is observable as a ledger event.
- **I7 (Refuse loud on broken pipelines).** Compliant per D279 — silent-skip is rejected; refuse-loud via the diagnostic emit is the posture.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — `_BREAKDOWN_DIMS_ALLOWED` refuse-loud is operationally LIVE; `source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text` all refuse-loud at the breakdown_by validation step.
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D281 — `MetricSnapshot.channel` surfaces homogeneous channels + None on the heterogeneous/missing cases.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 2 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — Pillar G Week 2 does not extend any of the five layers; it CONSUMES the Layer 5 `reconcile_drift.reason: "ready_without_draft_ready_event"` via the per-Person dashboard adapter trajectory at D277 (Week 10-11 implementation).

## Downstream pillar impact

- **Pillar G Week 3-4** (OTel SDK initialization + Prometheus exporter + first Grafana dashboard) — consumes `collect_event_class_snapshots` as the per-event-class metric source. The OTel SDK's `Meter` adapter wraps the primitive's snapshots into OTel `ObservableCounter` instruments + the Prometheus exporter pulls from the OTel SDK's collector. No changes to the primitive surface anticipated.
- **Pillar G Week 5-6** (OTel tracing instrumentation through the pipeline) — orthogonal to the per-event-class primitive; instrumentation lands at the per-pipeline-stage call sites (discovery → enrichment → research → draft → review → send → reply → win/loss). The trace context propagation is a separate primitive (`opentelemetry-api`'s `tracer.start_as_current_span`); no changes to `collect_event_class_snapshots`.
- **Pillar G Week 7-8** (SLO violation detector + `slo_violation_detected` event class emit) — consumes the primitive's snapshots to compute per-window SLO state (p99 send latency / reconcile success / bounce / `manual_override` count). The SLO detector is a NEW per-call primitive (separate from `collect_event_class_snapshots`); the diagnostic emit pattern at D279 generalizes (at-most-ONE `slo_violation_detected` per (SLO, window) per call).
- **Pillar G Week 9** (cost dashboard) — consumes the primitive's snapshots filtered to `cost_incurred` event class + breakdown by `source` (per the existing `cost_incurred` payload shape per ADR-0006). The `source` dim is NOT in `_BREAKDOWN_DIMS_ALLOWED` at Week 2's ship (Week 9 amendment adds it OR the per-tenant cost dashboard at Pillar I per ADR-0050 §Downstream pillar impact uses a separate primitive).
- **Pillar G Week 10-11** (per-Person observability surface adapters consuming Pillar F event classes + Layer 5 reason) — consumes the primitive's snapshots filtered to Pillar F event classes + the Layer 5 `reconcile_drift.reason` value. The per-Person Layer 5 drift dashboard MUST subscribe to BOTH `vault_ahead_of_ledger` AND `ready_without_draft_ready_event` per the Pillar F Week 12 follow-up's NEW pattern per ADR-0049 §66 P2-2 + the Pillar G Week 1 cross-pillar audit row 12 — the breakdown is `breakdown_by=("reason",)`.
- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — composes the primitive + the SLO alerting + the per-Person dashboards into the one-CLI-invocation binding scenario per ADR-0050 D275 + PILLAR-PLAN §2 Pillar G's binding text.
- **Pillar H (daemon + scale)** — the primitive's per-call O(N) cost may grow at multi-machine scale; Pillar H may revisit (e.g., per-event-class index in the ledger; per-window cache substrate). The stateless contract per ADR-0050 D272 + R033 is preserved at v1 scale.
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends to filter `_emitted_by: "observability"` diagnostics out of the per-tenant per-operator override-rate dashboards (the diagnostic events are framework-internal, not per-operator outreach activity).
- **Pillar J (GDPR purge)** — the diagnostic events MAY carry `person_id` (in the `kind="missing_ts"` case); Pillar J's per-Person purge transaction extends to delete `observability_class_uncatalogued` events with the purged Person's id alongside the rest of the per-Person event set.

## Migration / rollout

- **Operator-side action required at Week 2 upgrade:** NONE — the primitive is internal to Pillar G (Week 2 ships the body; Week 3+ adds operator-facing surfaces). The diagnostic emit is content-additive; the existing Pillar A-F event classes are unchanged.
- **First call post-upgrade** — operators running `python -c "from orchestrator.observability import collect_event_class_snapshots; ..."` (or, more commonly, Pillar G Week 3+'s OTel-wrapped dashboard adapter) MAY see the diagnostic event surface IF the ledger contains any pre-Week-2 events with missing `ts` (e.g., events from a custom migration that bypassed `Ledger.append`'s auto-fill). Operators investigate the producer via the `_emitted_by` audit trail + fix the producer.
- **Per-tenant migration at Pillar I** — content-additive at Pillar G Week 2; per-tenant audit-tooling at Pillar I extends to filter on the new `_emitted_by: "observability"` marker.
- **No ledger schema migration** — Week 2 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1).
- **OTel SDK install (Week 3+)** — Pillar G Week 2 does NOT install `opentelemetry-api` / `opentelemetry-sdk` / `opentelemetry-exporter-prometheus`. Week 3 lands the install per ADR-0050 D273's trajectory. Pillar G Week 2's primitive body has NO OTel imports.

## Existing-operator seed

Operator action required at Week 2: **NONE**.

Recommended (optional): operators consuming the primitive via a manual `python -c` invocation should pass `now=` for byte-identical reproducibility OR use the upcoming Pillar G Week 3+ OTel-wrapped dashboard adapter (which handles `now=wall-clock` internally).

## References

- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277.
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262 (Layer 5 module placement); D263 (Pass C refusal semantics + new `reconcile_drift.reason` value); §66 P2-2 (legacy-state-vs-new-defense-layer reason-precedence drift NEW pattern at Pillar F Week 12 follow-up).
- **ADR-0038** (Pillar F foundation). D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields).
- **ADR-0037** (Pillar E Week 12 close + Stable flip). D172 (Pillar E Stable flip discipline — the per-pillar binding exit-criterion test un-skip gates the Stable flip).
- **ADR-0032** (Pillar E foundation). D148 (privacy invariant on `source_list`).
- **ADR-0031** (Pillar D Week 12 funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state).
- **ADR-0027** (Pillar D Week 1 — `reply_classified` payload shape). The `category` / `classification_method` breakdown dims inherit from this ADR.
- **ADR-0025** (Pillar D foundation). D97 (brand-and-legal-liability invariant). D99 (cross-pillar audit precedent — every prior pillar's Week 1 audit caught ≥1 pre-existing P2).
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant).
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers).
- **ADR-0006** (Pillar A budget framework + `cost_incurred` event class).
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2 extension at §18 per this commit).
- `.planning/HANDOFF-pillar-g-week-1.md` — Pillar G Week 1 close summary + Pillar G Week 2 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 2 close summary.
- `docs/RISK-REGISTER.md` R031 + R032 + R033 (Pillar G Week 1 risks); R034 (NEW Week 2 — diagnostic emit at every primitive call inflates ledger when catalog drift persists; severity 1 / likelihood 2; per-kind-per-call rate-limit mitigation).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row + the diagnostic emit's `observability_class_uncatalogued` event class row.
- `orchestrator/observability.py` — the Pillar G Week 1 module shape + the Week 2 primitive body.
- `orchestrator/funnel.py:163-180` — `_composite_key` helper this primitive's `_composite_key` mirrors per D278.
- `orchestrator/ledger.py:390-420` — `Ledger.append` (the diagnostic emit's write surface).
- `tests/test_observability.py` (NEW Week 2) — per-primitive test surface with 56 tests covering the cell-level matrix per the Pillar F Week 6-12 per-week-reviewer discipline.
- `tests/test_multi_channel_coherence.py::TestPillarGObservability` (extended Week 2) — TWO previously-SKIPPED rows un-skipped: `test_collect_event_class_snapshots_walks_every_pillar_a_through_f_event_class` + `test_privacy_invariant_breakdown_dims_refuse_loud`.
