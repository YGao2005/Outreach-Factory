# ADR-0057: Pillar G Week 9 — cost dashboard rendering, per-source `cost_incurred` aggregation primitive, `CostSnapshot` dataclass, `COST_SOURCES_CATALOG` closed-set, `cost_source_uncatalogued` diagnostic kind extension, `_SLO_NAMES` extension PUNT decision

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 9 cost dashboard)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape + the OTel SDK + Prometheus exporter + Grafana-as-code framework decision per D273. D273's per-week trajectory table named **Week 9 as the cost dashboard rendering + per-source `cost_incurred` aggregation**.

ADR-0051 (Pillar G Week 2, D278-D281) shipped the `collect_event_class_snapshots` body + the `observability_class_uncatalogued` diagnostic emit + R034 mitigation (diagnostic emit at every primitive call inflates ledger when catalog drift persists). The at-most-ONE-per-kind-per-call rate-limit pattern is the structural pattern Week 9 inherits for the new `cost_source_uncatalogued` diagnostic kind.

ADR-0052 (Pillar G Week 3, D282-D287) + ADR-0053 (Pillar G Week 4, D288-D293) shipped the OTel SDK initialization + the per-channel send-latency Histogram + the reconcile success ratio ObservableGauge + the Prometheus HTTP exposition server + the first Grafana-as-code dashboard. The Week 4 `outreach_factory_events_total` ObservableCounter (filtered by `event_class="cost_incurred"`) IS the OTel-side metric the Week 9 Grafana panels render via PromQL.

ADR-0054 (Pillar G Week 5, D294-D299) + ADR-0055 (Pillar G Week 6, D300-D306) shipped the OTel tracing initialization + per-stage `traced_stage` context manager + per-stage span instrumentation at 13 per-pillar call sites + send-latency Histogram dispatcher integration at four of five dispatchers. Week 9 does NOT modify these surfaces; they preserve verbatim.

ADR-0056 (Pillar G Week 7-8, D307-D313) shipped the SLO violation detector + `slo_violation_detected` event class producer + operator-deliberate Slack webhook dispatcher + R032 synthetic-event exclusion + `_SLO_NAMES` closed-set. D313 named the closed-set extension trajectory: future weeks MAY extend `_SLO_NAMES` with new SLOs (e.g., `cost_burn_rate`) per the per-pillar foundation pattern. Week 9 PUNTS on that extension — the rationale below.

Pillar G Week 9 ships the **per-source cost aggregation primitive + the Grafana cost dashboard YAML + the `cost_source_uncatalogued` diagnostic kind extension**. The five concerns this ADR resolves:

1. **Per-source cost aggregation grain.** PILLAR-PLAN §2 Pillar G's binding text names: *"Cost dashboard (Anthropic + Apollo + PDL + Reoon + Gmail quota)."* The framework MUST decide WHERE the aggregation happens — at the existing `collect_event_class_snapshots` (per-event-class grain), at a NEW sibling primitive `collect_cost_snapshots` (per-cost-source grain), OR at a hybrid extension of `collect_event_class_snapshots` (with per-source breakdown). Per the per-pillar symmetry-with-shared-helper pattern per RETRO-pillar-f.md item 5 + the per-event-class observability primitive's per-event-class grain mismatch with the per-source cost grain, a dedicated sibling primitive is the cleanest seam.

2. **`CostSnapshot` dataclass + `COST_SOURCES_CATALOG` closed-set.** The per-source cost aggregation MUST surface a per-snapshot shape Pillar G dashboards consume uniformly + a closed-set of expected sources for the R031-shape regression-barrier. `CostSnapshot` mirrors `MetricSnapshot` shape per ADR-0050 D272 but scoped to the cost surface; `COST_SOURCES_CATALOG` enumerates the seven currently-emitting sources per the cost emission walk + the per-pillar foundation pattern.

3. **Privacy invariant on the cost surface.** The `cost_incurred` payload carries `person_id` + `run_id` per ADR-0006's "Cost ledger contract" — both operator-confidential per I8 + ADR-0032 D148 + ADR-0010 D17. The per-source aggregation primitive's `breakdown_by` kwarg MUST refuse-loud on these fields; operators consume per-Person cost attribution via `Ledger.all_events_for_person` (the ledger query surface), NOT via the dashboard aggregation. The privacy invariant flows through via a NEW `_COST_BREAKDOWN_DIMS_ALLOWED` closed-set (mirrors `_BREAKDOWN_DIMS_ALLOWED` shape per ADR-0050 D276(b)).

4. **`cost_source_uncatalogued` diagnostic kind extension.** A future contributor adding a NEW cost source without updating `COST_SOURCES_CATALOG` triggers refuse-loud at the primitive's ledger-walk boundary — the diagnostic event class `observability_class_uncatalogued` already exists per ADR-0051 D279 with two `kind` values (`uncatalogued` + `missing_ts`); Week 9 extends `_DIAGNOSTIC_KINDS` to three values by adding `cost_source_uncatalogued`. The extension preserves R031 + R034 mitigations (single event class for catalog-drift diagnostics; at-most-ONE per kind per call rate-limit).

5. **`_SLO_NAMES` extension decision — PUNT on `cost_burn_rate`.** PILLAR-PLAN §2 Pillar G's binding text enumerates exactly four SLO triggers (p99 send latency > 5s + reconcile success < 99% + bounce > 5% + `manual_override` count > 0); the closed-set `_SLO_NAMES` per ADR-0056 D313 IS the regression-barrier extended to the SLO surface. Adding `cost_burn_rate` would extend the closed-set beyond the binding text. Operators wanting cost SLO alerting wire Grafana alert rules on the per-source cost panel's PromQL queries (Grafana's alerting framework operates on PromQL queries); the closed-set discipline stays tight to PILLAR-PLAN's binding four.

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED + EXTENDED. The closed-set discipline (`EVENT_CLASS_CATALOG` + `OBSERVABILITY_NEW_EVENT_CLASSES` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` + `_SLO_NAMES`) extends with `COST_SOURCES_CATALOG` at Week 9. The closed-set IS the R031-shape regression-barrier extended to the cost surface — a future contributor adding a NEW cost source without coordinating with the closed-set triggers the `cost_source_uncatalogued` diagnostic emit (operator-visible signal).

- **R032 (SLO violation alerting false-positive on synthetic-data spike)** — UNCHANGED. The structural mitigation (events with `_recovered_by` are EXCLUDED) extends to the cost aggregation primitive — operators running migration backfills do NOT see synthetic-data cost spikes on the cost dashboard. The exclusion preserves the per-operator cost-dashboard signal.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED. Week 9's `collect_cost_snapshots` is stateless (re-walks the ledger per call); multi-process daemons (Pillar H scope) consume per-process aggregations independently. Prometheus pull-based aggregation downstream handles cross-process aggregation per ADR-0050 D272.

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED + EXTENDED. Week 9's `cost_source_uncatalogued` diagnostic emit follows the at-most-ONE-per-kind-per-call rate-limit pattern from ADR-0051 D279; the per-call emit rate caps at 1 cost-source-uncatalogued diagnostic per call (worst case ~1440/day per single-tenant operator at 1-minute polling cadence; same order-of-magnitude as the existing uncatalogued + missing_ts kinds).

- **R035 (OTel SDK's set-once `set_meter_provider` + `set_tracer_provider` enforcement)** — UNCHANGED. Week 9 consumes the existing global MeterProvider via the `outreach_factory_events_total` filtered by `event_class="cost_incurred"`; ZERO new OTel SDK initialization at Week 9.

- **R036 (Prometheus HTTP exposition server exposes per-process metrics)** — UNCHANGED. Week 9 does NOT introduce new HTTP exposition surfaces; the Grafana cost dashboard panels render via PromQL queries against the existing exposition.

ZERO new R-risks surfaced at Week 9. The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + ADR-0055 D303 + ADR-0056 D311 preserves the operator-choice posture; the closed-set discipline per `COST_SOURCES_CATALOG` extends the R031-shape regression-barrier to the cost surface; the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0051 D278 + ADR-0052 D284 + ADR-0053 D292 + ADR-0054 D297 + ADR-0055 D304 + ADR-0056 D308 carries through to the cost aggregation primitive's `_COST_BREAKDOWN_DIMS_ALLOWED` closed-set (NEVER `person_id` / `run_id` / `source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text`).

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12. The Pillar G Week 1-8 surfaces preserve verbatim — `EVENT_CLASS_CATALOG` + `OBSERVABILITY_NEW_EVENT_CLASSES` + `_BREAKDOWN_DIMS_ALLOWED` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` + `_SLO_NAMES` + `MetricSnapshot` + `collect_event_class_snapshots` + `init_otel_meter_provider` + `register_event_class_observable_counter` + `get_send_latency_histogram` + `register_reconcile_success_ratio_gauge` + `init_otel_tracer_provider` + `traced_stage` + 13 per-call-site span wraps + 4-dispatcher histogram records + `detect_slo_violations` + `dispatch_slo_alert` + `SLOConfig` + `SLOViolation`.

## Decision

### D314. Per-source cost aggregation primitive — `collect_cost_snapshots(led, *, since, now, expected_sources, breakdown_by)`

`orchestrator/observability.py::collect_cost_snapshots` is the canonical per-call per-source cost aggregation primitive. The function walks the ledger via `Ledger.all_events()`, filters `type == "cost_incurred"`, applies the per-call window filter (`ts >= since_iso`) + the R032 synthetic-event exclusion (events with `_recovered_by` are skipped), aggregates per `source`, and returns a list of `CostSnapshot` sorted alphabetically by `source` for deterministic output per ADR-0031 D140.

```python
def collect_cost_snapshots(
    led: Ledger,
    *,
    since: datetime,
    now: datetime | None = None,
    expected_sources: frozenset[str] = COST_SOURCES_CATALOG,
    breakdown_by: tuple[str, ...] = (),
) -> list[CostSnapshot]:
```

**Stateless contract** per ADR-0050 D272 + R033 mitigation — no in-process cache; every call re-walks the ledger. Per-call cost is O(N) at v1 scale (~5K events) → sub-second; Pillar H may revisit at multi-machine scale.

**R032 synthetic-event exclusion** per ADR-0056 D311 — events carrying `_recovered_by` (backfill / reconcile / migration_<id> per ADR-0010 D17) are EXCLUDED from the cost aggregation. Operators running migration backfills do NOT see synthetic-data cost spikes; the structural mitigation preserves the per-operator cost-dashboard signal across the framework's aggregation surfaces.

**Deterministic-clock contract** per ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278 + ADR-0056 D311. The `now` kwarg defaults to wall-clock; tests pass `now` for byte-identical reproducibility. `now` is the timestamp stamped onto any `cost_source_uncatalogued` diagnostic emit triggered by this call.

**Return shape:** `list[CostSnapshot]` sorted by `source` for deterministic output per ADR-0031 D140 + ADR-0051 D280.

### D315. `CostSnapshot` dataclass + `COST_SOURCES_CATALOG` closed-set

```python
@dataclass(frozen=True)
class CostSnapshot:
    source: str                                       # one of COST_SOURCES_CATALOG
    channel: str | None                               # homogeneous per ADR-0014 D33
    total_amount_usd: float                           # sum of amount_usd
    total_units: int                                  # sum of units
    event_count: int                                  # count of cost_incurred events
    per_breakdown_event_count: dict[str, int]         # sorted dict by composite-key
    per_breakdown_amount_usd: dict[str, float]        # sorted dict by composite-key
    oldest_ts: str | None                             # earliest in-window ts
    newest_ts: str | None                             # latest in-window ts
```

**Frozen dataclass** so consumers can safely share snapshots across dashboards + caches per the stateless-aggregation contract. Mirrors `MetricSnapshot` shape per ADR-0050 D272 but scoped to the cost surface.

**`COST_SOURCES_CATALOG` closed-set** — the seven currently-emitting cost sources per the cost emission walk:

```python
COST_SOURCES_CATALOG: frozenset[str] = frozenset({
    "reoon",                  # email-verification via orchestrator/enrich_emails.py
    "reply_classifier_llm",   # Anthropic LLM via orchestrator/reply_classifier_llm.py
    "gmail",                  # email send via skills/send-outreach/scripts/send_queued.py
    "linkedin_invite",        # LinkedIn invite
    "linkedin_dm",            # LinkedIn DM
    "twitter_dm",             # Twitter DM
    "calendar_booking",       # Calendar booking
})
```

**Disjoint from `EVENT_CLASS_CATALOG` + `_SLO_NAMES`** — cost source names MUST NOT collide with event class names (the catalogs are distinct R031-shape regression-barriers; the per-pillar audit walks each catalog independently); cost source names MUST be DISJOINT from `_SLO_NAMES` per the legacy-state-vs-new-defense-layer reason-precedence drift discipline per ADR-0049 D263 + ADR-0056 D313 (operators filtering on `slo_name` or `reconcile_drift.reason` MUST NOT see cost source names bleeding in).

**Channel-on-every-event invariant** per ADR-0014 D33 + ADR-0050 D276(c) + ADR-0051 D281. `CostSnapshot.channel` is the homogeneous channel value if every in-window cost event for the source carries the same `channel` value; `None` otherwise. Many cost sources do NOT carry `channel` (reoon / reply_classifier_llm — their events have `channel=None`); the per-dispatcher sources (gmail / linkedin_invite / etc.) MAY carry channel via their per-channel emit context.

### D316. `_COST_BREAKDOWN_DIMS_ALLOWED` privacy-respecting closed-set

```python
_COST_BREAKDOWN_DIMS_ALLOWED: frozenset[str] = frozenset({
    "source",                 # per-source aggregation grain
    "channel",                # per ADR-0014 D33 channel-on-every-event
    "model_or_endpoint",      # per cost_incurred payload field
})
```

**Allowed dimensions** mirror the per-event-class `_BREAKDOWN_DIMS_ALLOWED` shape but scoped to cost-payload fields per ADR-0006's "Cost ledger contract":

* `source` — the per-cost-source aggregation grain.
* `channel` — per ADR-0014 D33 (when the cost event carries channel).
* `model_or_endpoint` — per the `cost_incurred.model_or_endpoint` payload field (LLM model name / verifier endpoint).

**DISALLOWED dimensions** per the privacy invariant per I8 + ADR-0032 D148 + ADR-0010 D17:

* `person_id` — operator-private per ADR-0032 D148 + I8. Per-prospect cost attribution flows through `Ledger.all_events_for_person` (the per-Person ledger query surface), NOT via the dashboard aggregation.
* `run_id` — operator-tenant per ADR-0010 D17 (Pillar I per-tenant audit-tooling scope).
* Any other field — open-set rejection per the R031-shape regression-barrier discipline (per the closed-set rejection in the primitive's `breakdown_by` kwarg).

**Refuse-loud contract** — the primitive's `breakdown_by` kwarg validates against the closed-set + raises `ValueError` on any disallowed dimension. The ValueError mirrors `collect_event_class_snapshots`'s contract per ADR-0051 D278 + the closed-enum discipline per ADR-0042 D210.

### D317. `cost_source_uncatalogued` diagnostic kind extension

`_DIAGNOSTIC_KINDS` closed-set extends from 2 to 3 values at Week 9:

```python
_DIAGNOSTIC_KINDS: frozenset[str] = frozenset({
    "uncatalogued",                # Week 2 — collect_event_class_snapshots' catalog drift
    "missing_ts",                  # Week 2 — ts-missing refuse-loud
    "cost_source_uncatalogued",    # Week 9 — collect_cost_snapshots' catalog drift (NEW)
})
```

**Single event class** — the new kind value reuses the existing `observability_class_uncatalogued` event class per ADR-0051 D279. Operators consuming the per-event-class observability surface (per ADR-0050 D272) see all three kinds via a single event class filter; the per-kind discriminator is the `kind` field. The single-event-class shape preserves the per-pillar foundation's closed-set at TWO members (`OBSERVABILITY_NEW_EVENT_CLASSES = {"observability_class_uncatalogued", "slo_violation_detected"}`) — Week 9 does NOT extend the event class set.

**Diagnostic payload schema** for the new kind:

```jsonc
{
    "type": "observability_class_uncatalogued",
    "ts": "<ISO 8601 UTC>",
    "kind": "cost_source_uncatalogued",
    "offending_source": "<first-seen unknown source>",
    "count": <int>,
    "channel": null,
    "_emitted_by": "observability"
}
```

The `offending_source` field carries the first-seen unknown source (operators investigate the producer); the `count` field carries the total seen in the call; the `channel: null` matches the cost-event's per-source-grain (cost dashboards aggregate by source, not by channel).

**At-most-ONE per kind per call** per ADR-0051 D279 + R034 mitigation pattern. The per-call diagnostic rate-limit caps the per-call emit rate at 1 cost-source-uncatalogued diagnostic per call; the worst case (sustained catalog drift over 24h with 1-minute polling cadence) emits ~1440/day per single-tenant operator — same order-of-magnitude as the existing uncatalogued + missing_ts kinds.

### D318. Grafana cost dashboard `infra/grafana/dashboards/cost.yml` + `_SLO_NAMES` extension PUNT decision

Week 9 ships `infra/grafana/dashboards/cost.yml` (NEW) — operator-readable YAML describing three panels rendering the cost dashboard's binding question (PILLAR-PLAN §2 Pillar G: *"Cost dashboard (Anthropic + Apollo + PDL + Reoon + Gmail quota)."*):

1. **Per-source cost event rate (1h window)** — `rate(outreach_factory_events_total{event_class="cost_incurred"}[1h])` rendered as a time-series with per-channel legend.
2. **Per-source 24h cumulative cost event count** — `sum by (channel) (increase(outreach_factory_events_total{event_class="cost_incurred"}[24h]))` rendered as a bar chart.
3. **Total cost events (24h rolling)** — `sum(increase(outreach_factory_events_total{event_class="cost_incurred"}[24h]))` rendered as a stat panel for the aggregate spend cadence.

The panels render via the Week 3 `outreach_factory_events_total` `ObservableCounter` per ADR-0052 D284 — the same OTel-side metric the overview dashboard renders, scoped to the `event_class="cost_incurred"` filter. The OTel SDK's per-event-class counter callback re-walks the ledger via `collect_event_class_snapshots` per scrape; the per-source aggregation surfaces via the `channel` attribute (per ADR-0052 D284's channel-on-every-event invariant flowing through to the OTel Observation attributes).

**`_SLO_NAMES` extension PUNT** — Week 9 does NOT extend `_SLO_NAMES` with `cost_burn_rate`. The closed-set stays at exactly four members per ADR-0056 D313:

```python
_SLO_NAMES: frozenset[str] = frozenset({
    "send_latency_p99",
    "reconcile_success_ratio",
    "bounce_rate",
    "manual_override_count",
})
```

Rationale: PILLAR-PLAN §2 Pillar G's binding text enumerates exactly four SLO triggers; the closed-set IS the regression-barrier kept tight to the binding text. Operators wanting cost SLO alerting wire their own Grafana alert rule on the cost dashboard's PromQL queries (Grafana's alerting framework operates on PromQL queries against the panel metrics). Pillar I per-tenant audit-tooling at OSS bring-up MAY extend the closed-set with per-tenant compliance SLOs per the per-pillar foundation pattern.

## Alternatives considered

### D314 alternatives (per-source cost aggregation primitive grain)

1. **Extend `collect_event_class_snapshots` with a per-source breakdown** (the existing primitive's `breakdown_by=("source",)` would produce per-source counts in `per_breakdown_counts`). Rejected — the per-event-class primitive's grain is one snapshot per event class; per-source aggregation needs ONE snapshot per source. Operators consuming the dashboard want per-source `total_amount_usd` + `total_units` (NOT just counts), which require source as the per-snapshot key, not as a breakdown dimension.

2. **Compute per-source aggregation inside the OTel SDK ObservableCounter callback** (the Week 3 per-event-class counter would N-times-ify the per-source observations). Rejected — the OTel ObservableCounter grain is per-event-class (one observation per `MetricSnapshot`); coupling per-source aggregation to the OTel callback would (a) N-times-ify the per-scrape cost (one observation per source per scrape); (b) couple the per-source aggregation to operator-side Prometheus scrape interval (typically 30s); (c) miss the per-source aggregation's per-call audit trail (operators wanting per-source spend at glance via the per-call primitive's return value would have to query Prometheus). The dedicated primitive IS the operator-actionable grain.

3. **Make the primitive accept an arbitrary event class filter + an arbitrary aggregation field** (e.g., `collect_aggregation(led, *, event_class, aggregate_by_field)`). Rejected — open-set generalization N-times-ifies the per-primitive contract surface; the per-cost-source aggregation is a named operator-facing concern per PILLAR-PLAN §2 Pillar G binding text. The Week 9 framework default ships the per-cost-source aggregation; future per-pillar weeks adding per-aggregation primitives follow the per-pillar foundation ADR pattern (Week N ADR enumerates the new primitive in the per-pillar trajectory table).

4. **Walk the Prometheus exposition format directly (parse `outreach_factory_events_total{event_class="cost_incurred"}`).** Rejected — the framework's source of truth is the LEDGER per `docs/SOURCES-OF-TRUTH.md`; the Prometheus exposition is a denormalized rebuildable view per ADR-0050 D272 + ADR-0053 D292. Computing the per-source aggregation from the denormalized view would (a) couple the aggregation to operator-side `View` configuration; (b) miss the R032 synthetic-event exclusion at the metric level (the counter does NOT carry `_recovered_by` per-record state); (c) make the primitive untestable without an OTel SDK provider initialized. The ledger walk IS the canonical source.

### D315 alternatives (`CostSnapshot` dataclass + `COST_SOURCES_CATALOG` closed-set)

1. **Open-set sources walk** (the primitive collects every distinct `source` value encountered + emits one snapshot per unique source). Rejected — loses the structural commitment per R031 mitigation; if the cost aggregator quietly absorbs any new source value, dashboards drift silently from the per-source binding events. The closed-set enforces the per-pillar foundation ADR's discipline — every new cost source MUST coordinate with the catalog.

2. **Per-pillar sub-frozensets** (`_COST_SOURCES_PILLAR_C` + `_COST_SOURCES_PILLAR_D` + `_COST_SOURCES_PILLAR_E`). Rejected — creates the "look in N places" mental model per ADR-0050 D272-Alt2; the single closed-set is operator-readable + the per-source operator audit at the per-week reviewer's audit row 18.

3. **Combine `COST_SOURCES_CATALOG` with `EVENT_CLASS_CATALOG`** (treat cost sources as a sub-category of event classes). Rejected — cost sources and event classes are DISJOINT domains (event classes are the `ev.type` field's enumerated values; cost sources are the `cost_incurred.source` payload field's enumerated values). Conflating them N-times-ifies operator filtering surfaces (operators filtering by `event_class` would see source values bleeding into the event class set).

4. **Use a flat-dict shape `dict[str, dict[str, float]]` instead of `CostSnapshot` dataclass.** Rejected — a flat-dict loses type safety + operator-readable field names + the immutability discipline. The dataclass IS the canonical operator-readable shape mirroring `MetricSnapshot` per ADR-0050 D272.

### D316 alternatives (`_COST_BREAKDOWN_DIMS_ALLOWED` privacy-respecting closed-set)

1. **Reuse the existing `_BREAKDOWN_DIMS_ALLOWED` closed-set** (the per-event-class breakdown set already excludes privacy-sensitive fields). Rejected — the per-event-class breakdown set has nine dimensions (channel + register + source_skill + category + classification_method + outcome + reason + result_state + event_class); most are NOT applicable to the cost surface (cost events do NOT carry `register` / `source_skill` / `category` / etc.). Reusing the broader set would dilute the per-cost-surface meaning + risk allowing dimensions that happen to share a key name but mean different things (e.g., `event_class` is meaningful on per-event-class snapshots but tautological on per-cost-source snapshots).

2. **Add `person_id` and `run_id` to the allowed set** (operators want per-person + per-run cost attribution). Rejected — `person_id` is operator-private per ADR-0032 D148 + I8; per-prospect cost attribution flows through `Ledger.all_events_for_person` (the per-Person ledger query surface), NOT via the dashboard aggregation surface. `run_id` is operator-tenant per ADR-0010 D17 (Pillar I per-tenant audit-tooling scope). The structural privacy invariant per I8 + ADR-0050 D276(b) requires the closed-set excludes these.

3. **Make the breakdown dim set operator-configurable** (e.g., a kwarg `allowed_dims=...`). Rejected — operator-configurable breakdown surface would invite per-operator privacy invariant violations (operators MAY accidentally add `person_id` to their per-tenant breakdown config). The closed-set IS the structural commitment per I8 + R031.

### D317 alternatives (`cost_source_uncatalogued` diagnostic kind extension)

1. **Add a NEW event class `cost_source_uncatalogued`** (extends `OBSERVABILITY_NEW_EVENT_CLASSES` to three members). Rejected — extending the per-pillar foundation ADR's "new event classes" table from two to three members is a load-bearing decision (the closed-set was named at ADR-0050 D273 with two members); adding a third would require coordinating with the per-pillar audit + the regression-barrier test pinning the catalog membership. The kind-extension approach is content-additive (the closed-set extension is at the per-kind level, not at the per-event-class level); the existing event class consumer surface preserves verbatim.

2. **Use the existing `"uncatalogued"` kind value** (the primitive emits with `kind="uncatalogued"` + the `offending_type` field carries the source value). Rejected — would mix per-event-class catalog drifts with per-cost-source catalog drifts under the same kind label; operators filtering on `kind="uncatalogued"` would see both drift types conflated. The per-kind discrimination preserves the per-catalog signal.

3. **Add a per-call `expected_sources` kwarg without the catalog closed-set** (the primitive accepts any caller-supplied set; refuses-loud on unknown sources). Rejected — caller-supplied without a framework default would (a) re-introduce the discoverability problem (operators wouldn't know what sources to expect); (b) drift from the per-pillar foundation pattern (Pillar A-F foundation ADRs each pin a closed-set). The framework default (`expected_sources=COST_SOURCES_CATALOG`) IS the operator-readable surface; the kwarg override is the test-only seam.

### D318 alternatives (Grafana cost dashboard panel set + `_SLO_NAMES` extension PUNT)

1. **Extend `_SLO_NAMES` with `cost_burn_rate`** (per the ADR-0056 D313 closed-set extension trajectory). Rejected at Week 9 — PILLAR-PLAN §2 Pillar G's binding text enumerates exactly four SLO triggers (p99 send latency, reconcile success, bounce rate, `manual_override` count); adding `cost_burn_rate` extends the closed-set beyond the binding text. The closed-set discipline stays tight to the binding four; operators wanting cost SLO alerting wire Grafana alert rules on the cost dashboard's PromQL queries (Grafana's alerting framework operates on PromQL). Pillar I per-tenant audit-tooling at OSS bring-up MAY extend the closed-set with per-tenant compliance SLOs.

2. **Use a separate per-source counter instrument** (e.g., `outreach_factory_cost_total{source=...}` instead of filtering the existing `outreach_factory_events_total{event_class="cost_incurred"}`). Rejected — N-times-ifies the OTel instrument set (each new per-event-class surface would surface as a new instrument); the per-event-class counter's per-attribute breakdown is the canonical surface; PromQL filtering on `event_class="cost_incurred"` IS the operator-readable consumer pattern.

3. **Add per-source amount_usd as a separate metric** (e.g., a new ObservableGauge `outreach_factory_cost_amount_usd`). Rejected — adding a new instrument N-times-ifies the OTel surface area; the per-event-rate dashboard surfaces the per-source emission cadence, which is the operator-actionable signal for runaway dispatchers. Per-source amount_usd is consumed via the per-call `collect_cost_snapshots` primitive (the per-call audit trail); the per-scrape Prometheus metric surfaces the per-source event count. Pillar I per-tenant audit-tooling MAY extend with a per-source amount-USD ObservableGauge.

4. **Add Slack webhook alerts for cost dashboard panels** (mirrors the SLO violation Slack webhook per ADR-0056 D312). Rejected at Week 9 — the cost dashboard is a dashboard, not an alerting surface; operators wanting cost alerts wire Grafana alert rules (Grafana's alerting framework integrates with Slack natively). The Week 7-8 Slack webhook dispatcher is the SLO violation alerting surface; the Week 9 cost dashboard is the per-source spend visibility surface.

## Consequences

### Positive

- **The framework's cost dashboard surface is now operationally complete at Week 9** — operators wiring `collect_cost_snapshots(led, since=parse_since("30d"))` see per-source spend over the rolling window + per-channel breakdown + per-model_or_endpoint breakdown; operators consuming the Grafana cost dashboard see per-source cost event rate + per-source 24h cumulative event count + total cost events.
- **The closed-set discipline per `COST_SOURCES_CATALOG` IS the R031-shape regression-barrier extended to the cost surface** — a future contributor adding a NEW cost source without coordinating with the closed-set + the per-pillar ADR triggers refuse-loud at the `cost_source_uncatalogued` diagnostic emit.
- **The privacy invariant per I8 + ADR-0050 D276(b) flows through to the cost aggregation surface** via the NEW `_COST_BREAKDOWN_DIMS_ALLOWED` closed-set — `person_id` + `run_id` refuse-loud at the `breakdown_by` kwarg; per-Person cost attribution flows through the ledger query surface, NOT via the dashboard aggregation. The privacy invariant test pins the closed-set membership.
- **The legacy-state-vs-new-defense-layer reason-precedence drift discipline holds at EIGHT consecutive weeks (Pillar F W12 + Pillar G W2-W6 + W7-W8 + W9)** — Week 9 introduces `COST_SOURCES_CATALOG` as a NEW closed-set DISJOINT from `EVENT_CLASS_CATALOG` + `_SLO_NAMES` + `_DRIFT_REASONS`; the regression-barrier tests pin the disjointness.
- **The behavioral-passthrough-not-signature-only discipline holds at TEN consecutive weeks (Pillar F W8-W11 + Pillar G W3-W6 + W7-W8 + W9)** — Week 9 tests capture per-call diagnostic events + per-source aggregation totals via the ledger query surface (TestWeek9BehavioralPassthrough).
- **The cell-level matrix coverage discipline holds at THIRTEEN consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8 + W9)** — Week 9 ships 56 new tests covering per-source × per-event count × per-amount sum × per-channel × per-breakdown × per-R032-exclusion × per-uncatalogued × per-privacy-invariant × per-deterministic-clock × per-deterministic-ordering cells.
- **The module-level docstring drift discipline holds at TWELVE consecutive weeks (Pillar F W8-W12 + Pillar G W2-W6 + W7-W8 + W9)** — the observability module docstring extension names Week 9 + ADR-0057 + the cost dashboard primitive + the COST_SOURCES_CATALOG closed-set + the cost_source_uncatalogued diagnostic kind extension.
- **ZERO new R-risks** at Week 9 — the existing R031/R032/R033/R034/R035/R036 mitigations carry through verbatim; the closed-set discipline extends R031 to the cost surface; R032's `_recovered_by` exclusion extends to the cost aggregation.

### Negative

- **The per-call cost grows with the ledger size** — at v1 scale (~5K events) the per-call cost is sub-second; at v2 scale (~100K events) the per-call cost may surface as a per-cron-interval latency concern. Mitigation: operators query at appropriate intervals (1h is typical for cost dashboard refresh); Pillar H scale revisit may surface per-event-class indexing as a NEW concern.
- **Per-tenant cost attribution is deferred to Pillar I** — the Week 9 framework default is single-tenant per ADR-0050 D276(d); operators with multi-tenant cost attribution needs consume the per-Person ledger query surface for now (`Ledger.all_events_for_person` + filter by `type == "cost_incurred"`). Pillar I per-tenant audit-tooling at OSS bring-up extends with per-tenant cost dashboards.
- **The `COST_SOURCES_CATALOG` extension at future Pillar G weeks requires coordinated ADR + per-week reviewer audit** — a future contributor adding a new cost source (e.g., `apollo` / `pdl` when Pillar E discovery cost emits land) MUST extend the closed-set + the per-pillar ADR's "new cost sources" table. Mitigation: the per-week-reviewer's cross-pillar back-audit discipline catches the structural drift.
- **The test surface grows by 56 tests** — `tests/test_observability.py` ships 56 NEW tests covering the cell-level matrix; file size grows from ~5550 LOC to ~6300+ LOC, still below the ~7500 LOC split threshold flagged by ADR-0037 D172.
- **The Week 9 ship does NOT extend `_SLO_NAMES` with `cost_burn_rate`** — operators wanting cost SLO alerting wire Grafana alert rules on the cost dashboard's PromQL queries. The closed-set extension at a future Pillar G week MAY revisit; Pillar I per-tenant audit-tooling MAY extend with per-tenant compliance SLOs.

### Neutral

- **The OTel scope version stays at `0.1.0`** per ADR-0052 D283 + ADR-0054 D295 — the Week 9 cost dashboard renders via the existing `outreach_factory_events_total` ObservableCounter filtered by `event_class="cost_incurred"`; ZERO new OTel instruments at Week 9.
- **No new pip dependencies at Week 9** — `collect_cost_snapshots` is implemented in stdlib (`Counter`, `dataclasses.dataclass`, `datetime`, `typing`); the Grafana YAML is operator-readable text.
- **No ledger schema migration** — Week 9 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1-8). The `cost_incurred` event class is ALREADY in `EVENT_CLASS_CATALOG` per ADR-0050 D272 (recursive-protection — `cost_incurred` events do NOT trigger uncatalogued diagnostics).
- **No new event classes** — Week 9 ships ZERO new event classes. The `cost_source_uncatalogued` is a NEW `kind` value on the existing `observability_class_uncatalogued` event class (Week 9 extends `_DIAGNOSTIC_KINDS` from 2 to 3 values; `OBSERVABILITY_NEW_EVENT_CLASSES` stays at 2 members).
- **No new operator-facing CLI surfaces** — Week 9 does NOT extend `orchestrator/funnel.py` or any other CLI; operators invoke `collect_cost_snapshots` programmatically OR consume via the Grafana cost dashboard. Week 12 may extend `funnel.py` to surface per-source cost as part of the one-CLI-invocation binding exit-criterion test.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — cost events are emitted to the ledger; the cost dashboard's Prometheus exposition + Grafana panels are denormalized rebuildable views per `docs/SOURCES-OF-TRUTH.md`.
- **I2 (Atomicity contract).** Compliant — `collect_cost_snapshots`'s diagnostic emit via `Ledger.append` for `observability_class_uncatalogued` events with `kind="cost_source_uncatalogued"` is atomic per the existing ledger append contract.
- **I3 (Single source of truth).** Compliant — every cost aggregation re-derives from the per-call ledger walk; no state cached at the primitive level.
- **I4 (Determinism).** Compliant — the `now` kwarg controls the deterministic-clock stamp on the diagnostic emit ts; the return list is sorted by `source` for byte-identical reproducibility across consecutive calls against a fixed ledger state per ADR-0031 D140 + ADR-0051 D280.
- **I5 (Refuse loud).** Compliant — `COST_SOURCES_CATALOG` is the closed-set on cost sources; unknown sources trigger the `cost_source_uncatalogued` diagnostic emit. `_COST_BREAKDOWN_DIMS_ALLOWED` is the closed-set on breakdown dimensions; disallowed dims raise ValueError.
- **I6 (No silent state).** Compliant — every cost source catalog drift is observable on the ledger (via the `cost_source_uncatalogued` diagnostic event class kind); the per-call rate-limit caps emission but ZERO events are silently dropped.
- **I7 (Refuse loud on broken pipelines).** Compliant — the primitive's per-event ledger walk surfaces `cost_source_uncatalogued` diagnostics for any source outside the catalog; the diagnostic event surfaces operator-visible catalog drift signal.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant per D316 — the `_COST_BREAKDOWN_DIMS_ALLOWED` closed-set excludes `person_id` + `run_id`; the cost aggregation surface aggregates by source + channel + model_or_endpoint ONLY. Per-Person cost attribution flows through the ledger query surface.
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D315 — `CostSnapshot.channel` is the homogeneous channel value if every in-window event for the source carries the same `channel`; None otherwise (the cost-events that do NOT carry channel surface as `CostSnapshot.channel = None` per the existing `MetricSnapshot.channel` precedent).
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 9 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected at structural level — Pillar G Week 9 does not extend any of the five layers; Layer 5 backstop preserved verbatim.

## Downstream pillar impact

- **Pillar G Week 10-11** (per-Person observability surface) — Week 10-11's per-Person dashboards MAY extend with per-Person cost attribution. The per-Person cost surface consumes `cost_incurred.person_id` via `Ledger.all_events_for_person`, NOT via the Week 9 cost dashboard's per-source aggregation. The privacy invariant per I8 + ADR-0050 D276(b) holds at the per-Person ledger query surface (operators see per-Person spend via the per-Person dashboard's ledger query); the per-source dashboard aggregation preserves the per-source-only-aggregation contract.
- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — Week 12 composes the per-source cost dashboard + the per-event-class observability dashboard + the per-channel send-latency histogram + the reconcile success ratio gauge + the SLO violation detector + the Slack webhook dispatcher into the one-CLI-invocation binding scenario per ADR-0050 D275 + PILLAR-PLAN §2 Pillar G's binding text. The `funnel.py --cost-by-source` extension MAY surface the per-source cost as part of the one-CLI-invocation answer to the binding question.
- **Pillar H (daemon + scale)** — the per-call cost aggregation primitive is stateless + per-process; multi-process daemons consume per-process aggregations independently. Pillar H may surface per-event-class indexing (for cost_incurred specifically) as a NEW concern at multi-machine scale; the closed-set discipline preserves the per-source consumer surface at multi-machine scale.
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends `COST_SOURCES_CATALOG` with per-tenant cost sources (e.g., per-tenant Apollo + PDL providers when those discovery cost emits land at Pillar E's downstream extension). Per-tenant cost attribution adds a per-tenant label to the cost metric + per-tenant dashboard folders. The closed-set discipline per the per-pillar foundation pattern preserves the per-tenant audit-tooling's per-source enumeration contract.
- **Pillar J (GDPR purge)** — per-Person `cost_incurred` events are subject to per-Person GDPR purge per ADR-0049 §Downstream pillar impact. The Week 9 cost aggregation primitive's `_recovered_by` exclusion does NOT block the Pillar J purge transaction (the purge is operator-deliberate; the `_recovered_by` exclusion is operator-deliberate-backfill specific). The `cost_source_uncatalogued` diagnostic event class with kind extension does NOT carry `person_id` (the diagnostic is per-call grain, not per-Person); Pillar J's per-Person purge does NOT need to extend to the diagnostic events independently.

## Migration / rollout

- **Operator-side action required at Week 9 upgrade:** **NONE — content-additive.** The Week 9 commit adds `collect_cost_snapshots` + `CostSnapshot` + `COST_SOURCES_CATALOG` + `_COST_BREAKDOWN_DIMS_ALLOWED` + extends `_DIAGNOSTIC_KINDS` from 2 to 3 + creates `infra/grafana/dashboards/cost.yml`; existing surfaces are PRESERVED verbatim. Operators upgrading from Week 7-8 to Week 9 see identical behavior — the primitive is NOT auto-called at module load; operators invoke `collect_cost_snapshots` programmatically OR consume via the Grafana cost dashboard.
- **Recommended (optional):** operators wanting per-source cost monitoring at Week 9:

  ```python
  from datetime import datetime, timedelta, timezone

  from observability import collect_cost_snapshots

  now = datetime.now(timezone.utc)
  snapshots = collect_cost_snapshots(
      led,
      since=now - timedelta(days=30),
      now=now,
  )
  for snap in snapshots:
      print(
          f"{snap.source}: ${snap.total_amount_usd:.4f} "
          f"({snap.event_count} events)"
      )
  ```

- **First primitive run post-upgrade MAY surface `cost_source_uncatalogued` diagnostics** if the operator's ledger contains pre-Week-9 cost events with `source` values NOT in `COST_SOURCES_CATALOG` (e.g., legacy cost emits from prior framework versions OR operator-script-injected cost events). Operators inspect the surfaced diagnostics + coordinate the closed-set extension via the per-pillar foundation ADR pattern.
- **No ledger schema migration** — Week 9 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes** — Week 9 ships ZERO new event classes. The `cost_source_uncatalogued` is a NEW kind value on the existing `observability_class_uncatalogued` event class.
- **No new pip dependencies** — `collect_cost_snapshots` is stdlib (`Counter`, `dataclasses`, `datetime`, `typing`); the Grafana YAML is operator-readable text.

## Existing-operator seed

Operator action required at Week 9: **NONE — content-additive.**

Recommended (optional): operators wanting per-source cost monitoring at Week 9 invoke the canonical wiring per the Migration section above. Operators waiting for the framework-side per-Person observability dashboards see them land at Pillar G Week 10-11; binding exit-criterion test at Pillar G Week 12.

## References

- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector + `slo_violation_detected` event class producer + Slack webhook dispatcher + R032 synthetic-event exclusion + at-most-ONE-per-(slo_name, channel)-per-call rate-limit + `_SLO_NAMES` closed-enum). D307-D313. D313's closed-set extension trajectory is the pattern Week 9 PUNTS on for `cost_burn_rate`; the Week 9 `COST_SOURCES_CATALOG` closed-set follows the same R031-shape regression-barrier pattern extended to a different surface.
- **ADR-0055** (Pillar G Week 6 — Per-stage span instrumentation + send-latency Histogram dispatcher integration). D300-D306. Week 9 preserves the per-call-site span wiring verbatim.
- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization + canonical Tracer scope + per-stage `traced_stage` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED`). D294-D299. Week 9 preserves the tracing initialization + closed-sets verbatim.
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + per-channel send-latency Histogram + reconcile success ratio ObservableGauge + Prometheus HTTP exposition server + framework-default Views + first Grafana-as-code dashboard). D288-D293. Week 9's cost dashboard YAML mirrors the Week 4 overview dashboard's structure + renders via the per-event-class `outreach_factory_events_total` ObservableCounter per D284.
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope + per-event-class ObservableCounter + cumulative-counter semantics + framework-neutrality contract). D282-D287. Week 9 consumes the per-event-class ObservableCounter via the `event_class="cost_incurred"` filter in PromQL.
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281. Week 9's `cost_source_uncatalogued` diagnostic kind extension follows the at-most-ONE-per-kind-per-call rate-limit pattern + R034 mitigation from D279.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. D273's per-week trajectory table named Week 9 as the cost dashboard ship week.
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. D263's `_DRIFT_REASONS` closed-set is the legacy enum Week 9's `COST_SOURCES_CATALOG` is mutually exclusive from per the legacy-state-vs-new-defense-layer reason-precedence drift discipline.
- **ADR-0042** (Pillar E Week 9-11 — discovery lineage primitive + idempotence key contract). D210 (closed-enum discipline). Week 9's `COST_SOURCES_CATALOG` follows the same closed-enum pattern.
- **ADR-0038** (Pillar F foundation). D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields).
- **ADR-0035** (Pillar E Week 6-8 — tier auto-assignment primitive). D162 (`TierWeights` operator-configurable dataclass pattern; mirrors Week 9's `CostSnapshot` frozen-dataclass shape).
- **ADR-0034** (Pillar E Week 1 — discovery dedup primitive + deterministic-clock contract). D154-D158.
- **ADR-0032** (Pillar E foundation). D148 (privacy invariant — operator-confidential `source_list` field).
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state). Week 9's `collect_cost_snapshots` return list is sorted by `source` for deterministic output.
- **ADR-0029** (Pillar D Week 6 — LLM-fallback classifier). D125-D126 (Anthropic LLM cost ledger contract; `source="reply_classifier_llm"`).
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant). Week 9's `CostSnapshot.channel` field surfaces the channel uniformly per this invariant (None for cost events without channel; homogeneous channel value when present).
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). Week 9's R032 mitigation consumes `_recovered_by` for synthetic-event exclusion; the `cost_source_uncatalogued` diagnostic carries `_emitted_by: "observability"`.
- **ADR-0006** (Phase 5.0 policy engine — budget rules + cost events). D5 (cost_incurred event payload shape: `source` + `amount_usd` + `units` + `model_or_endpoint` + `person_id` + `run_id`). Week 9's `collect_cost_snapshots` consumes this payload shape.
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2-8 sections + Week 9 §24 extension per this commit).
- `.planning/HANDOFF-pillar-g-week-7.md` — Pillar G Week 7-8 close summary + Pillar G Week 9 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 9 close summary.
- `docs/RISK-REGISTER.md` R031-R036 (no new R-rows at Week 9; R031 mitigation surface extends to cost dashboard via `COST_SOURCES_CATALOG`; R032 mitigation extends to cost aggregation via `_recovered_by` exclusion).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 9 ADR-0057 references.
- `orchestrator/observability.py` — extended Week 9 with `COST_SOURCES_CATALOG` + `_COST_BREAKDOWN_DIMS_ALLOWED` + `CostSnapshot` + `collect_cost_snapshots` + `_DIAGNOSTIC_KINDS` extended from 2 to 3 values.
- `tests/test_observability.py` (extended Week 9) — 56 NEW tests covering the cell-level matrix per the per-week-reviewer discipline NOW THIRTEEN consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8 + W9).
- `infra/grafana/dashboards/cost.yml` (NEW) — operator-readable Grafana dashboard YAML rendering the cost dashboard's binding question per PILLAR-PLAN §2 Pillar G.
