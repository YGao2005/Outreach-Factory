# ADR-0052: Pillar G Week 3 — OTel SDK initialization, single canonical `Meter` scope, per-event-class `ObservableCounter` registration with stateless callback, cumulative-counter semantics, framework-neutrality contract, default `Resource`-attribute closed-set

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 3 OTel SDK initialization)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape + the OTel SDK framework decision per D273 + the per-week trajectory table naming Week 3 as the OTel SDK initialization. ADR-0051 (Pillar G Week 2, D278-D281) shipped the `collect_event_class_snapshots` body + the `observability_class_uncatalogued` diagnostic emit + the deterministic snapshot ordering + the channel-on-every-event invariant verification. Both prior weeks deliberately DID NOT import OTel — the framework decision was pinned but the runtime initialization was deferred until Week 3 per the per-week trajectory.

Pillar G Week 3 ships the **OTel SDK initialization** + the **single canonical `Meter` scope** + the **per-event-class `ObservableCounter` instrument registration**. The six concerns this ADR resolves:

1. **OTel SDK initialization shape.** The framework now imports `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-prometheus` per ADR-0050 §Migration/rollout. The runtime initialization must (a) configure a `MeterProvider` with a service-named `Resource`; (b) be idempotent under OTel's set-once `set_meter_provider` enforcement; (c) accept operator-supplied `metric_readers` for cross-vendor portability per D273's framework-neutrality contract.

2. **Single canonical `Meter` scope.** Per RETRO-pillar-f.md item 5 (the per-pillar-symmetry-with-shared-aggregation pattern carried forward from Pillar D's per-channel reply detection + Pillar E's per-skill integration + Pillar F's per-register adapters): Pillar G's OTel scope MUST be a single canonical label so operators consuming the OTLP / Prometheus export see one namespace. Splitting across per-pillar-G-week sub-scopes (e.g., `orchestrator.observability.alerting` for Week 7-8 + `orchestrator.observability.cost` for Week 9) would create the "look in three places" mental model the Pillar G Week 1 audit row 17 + ADR-0050 D272's closed-set discipline rejects.

3. **Per-event-class `ObservableCounter` instrument shape.** The Week 3 instrument's data shape must align with (a) the per-event-class aggregation `MetricSnapshot` from `collect_event_class_snapshots` per ADR-0051 D278 — ONE Observation per snapshot; (b) the channel-on-every-event invariant per ADR-0014 D33 + ADR-0051 D281 — the per-Observation `channel` attribute surfaces the homogeneous channel value OR the literal `"none"` (because OTel attributes do NOT accept `None`); (c) the deterministic-output contract per ADR-0031 D140 + ADR-0051 D280 — the per-scrape ledger walk re-aggregates from the stateless `collect_event_class_snapshots`; no per-scrape cache substrate.

4. **Cumulative-counter semantics vs gauge.** The per-event-class count is a monotonic process metric (events are append-only per the Phase 5.5 ledger contract). Per the Prometheus + OTel counter convention, the per-event-class instrument is an `ObservableCounter` (cumulative non-decreasing) NOT a `Gauge` (point-in-time). Operators query the per-window rate via PromQL's `rate()` / `increase()` over the window — this is the canonical Prometheus query pattern; switching to `Gauge` would force operators into a non-standard query shape + lose the Prometheus alerting + recording rule ecosystem.

5. **Framework-neutrality contract.** Per D273 + ADR-0050 D274 cross-pillar audit category 4: operators with different observability backends (Honeycomb / Datadog / Grafana Cloud / self-hosted Prometheus / OTLP collector) MUST be able to wire their own `MetricReader` without code changes to the framework. The `init_otel_meter_provider(metric_readers=...)` kwarg is the operator escape hatch. Week 3 ships with EMPTY readers by default — the MeterProvider accepts no readers; instruments register, callbacks register, but no scrape fires until a reader is added (Week 4 lands the Prometheus exporter wiring).

6. **Default `Resource`-attribute closed-set.** The OTel SDK auto-injects `telemetry.sdk.*` attributes per the OTel resource semantic conventions; the framework default Resource carries `service.name` + `service.version` per OTel's `opentelemetry.semconv.resource` conventions. Operators extending Resource with per-tenant labels at Pillar I OSS bring-up MUST be able to preserve the framework's `service.*` keys while adding per-tenant keys (e.g., `outreach_factory.tenant_id`).

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED from ADR-0050; the closed-set `EVENT_CLASS_CATALOG | OBSERVABILITY_NEW_EVENT_CLASSES` IS the mitigation. The OTel wrapper at Week 3 consumes this same closed-set via `collect_event_class_snapshots`'s `expected_classes` kwarg.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED from ADR-0050; the stateless callback contract per D284 preserves the mitigation. Every OTel scrape re-walks the ledger fully via the underlying primitive; no cross-scrape cache substrate.

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED from ADR-0051; the per-kind-per-call rate-limit holds per Pillar G Week 2's commitment. The OTel scrape cycle MAY surface more frequent per-call invocations (e.g., Prometheus's 15s default scrape interval) — operators see ~5760 scrapes/day at default + up to two diagnostics/scrape × 5760 = ~11520 diagnostics/day per single-tenant operator in worst-case catalog-drift state. Pillar I per-tenant audit-tooling filters `_emitted_by: "observability"` from the per-operator dashboards.

- **R035 (NEW) — OTel SDK's set-once `set_meter_provider` enforcement creates per-process global state.** The OTel Python SDK enforces "set-once" semantics on `metrics.set_meter_provider` — subsequent calls log `"Overriding of current MeterProvider is not allowed"` and do NOT take effect. Operators running multiple framework invocations in the same Python process (e.g., a long-running daemon at Pillar H + a manual `python orchestrator/funnel.py` invocation in the same interpreter) would see the FIRST init's provider persist; subsequent inits silently no-op. Mitigation by design: `set_global=False` kwarg gives tests an escape hatch; production callers initialize ONCE at startup per the OTel spec. Pillar H may revisit at multi-machine scale (e.g., per-daemon-process MeterProvider isolation).

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12.

## Decision

### D282. OTel SDK initialization — `init_otel_meter_provider` at `orchestrator/observability.py`

`orchestrator/observability.py::init_otel_meter_provider(*, resource=None, metric_readers=(), set_global=True)` is the canonical OTel SDK initialization entry point. The signature + contract:

```python
def init_otel_meter_provider(
    *,
    resource: Resource | None = None,
    metric_readers: Iterable[MetricReader] = (),
    set_global: bool = True,
) -> MeterProvider:
    """Initialize an OTel MeterProvider per ADR-0052 D282."""
    if resource is None:
        resource = Resource.create({
            SERVICE_NAME: _SERVICE_NAME,
            SERVICE_VERSION: _SERVICE_VERSION,
        })
    provider = MeterProvider(
        resource=resource,
        metric_readers=list(metric_readers),
    )
    if set_global:
        _otel_metrics.set_meter_provider(provider)
    return provider
```

Module placement: **co-locate with the Pillar G Week 2 body at `orchestrator/observability.py`** (NOT a sibling sub-module). The Week 3 surface adds ~250 LOC; the file's total stays well below the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266 + ADR-0050 D275. Co-location preserves the per-pillar single-file mental model (operators reading `orchestrator/observability.py` see the full Pillar G surface in one place); a sub-module split would create the "look in two places" pattern Pillar D Week 12 + Pillar E Week 12 + Pillar F Week 12 + Pillar G Week 1 + Pillar G Week 2 all rejected.

Idempotency caveat: OTel Python SDK enforces "set-once" on `set_meter_provider`. The `set_global=False` kwarg gives tests an escape hatch (each test creates a local provider, passes it explicitly through `get_meter(meter_provider=...)` + the instrument-registration `meter=` kwarg). Production callers initialize ONCE at startup with `set_global=True`.

### D283. Single canonical OTel `Meter` scope — `orchestrator.observability` + version `0.1.0`

`orchestrator/observability.py::get_meter()` returns the canonical Pillar G `Meter`. The module-level constants:

```python
_METER_NAME: str = "orchestrator.observability"
_METER_VERSION: str = "0.1.0"
```

`get_meter(meter_provider=None)` consults the global provider (set by `init_otel_meter_provider(set_global=True)`) by default; tests pass `meter_provider=` to source from an explicit local provider.

**Per-pillar symmetry contract per RETRO-pillar-f.md item 5.** Every Pillar G instrument (Week 3's `outreach_factory_events_total`; Week 4's per-channel histogram + reconcile success ratio; Week 7-8's `slo_violation_detected` gauge; Week 9's cost dashboard counters; Week 10-11's per-Person dashboard counters) SHARES this single scope. The per-pillar-G-week instruments are LABELED via OTel attributes — NOT via per-scope sub-namespaces.

The version `0.1.0` bumps at the per-week ADR when the per-event-class instrument set extends in a non-backwards-compat way. Week 3 ships `0.1.0`; Week 4 MAY bump to `0.2.0` if the per-channel histogram instrument introduces a breaking change to operators consuming the Week 3 `outreach_factory_events_total` shape.

### D284. Per-event-class `ObservableCounter` instrument registration — `register_event_class_observable_counter`

`orchestrator/observability.py::register_event_class_observable_counter(led, *, since_window, now=None, expected_classes=EVENT_CLASS_CATALOG, breakdown_by=(), meter=None)` registers the single canonical instrument. The signature + contract:

```python
def register_event_class_observable_counter(
    led: "_ledger.Ledger",
    *,
    since_window: timedelta,
    now: Callable[[], datetime] | None = None,
    expected_classes: frozenset[str] = EVENT_CLASS_CATALOG,
    breakdown_by: tuple[str, ...] = (),
    meter: Meter | None = None,
) -> "_ObservableCounter":
    """Register the per-event-class ObservableCounter per ADR-0052 D284."""
```

The instrument's canonical attributes:

- **Name:** `outreach_factory_events_total` (per `_INSTRUMENT_NAME_EVENTS_TOTAL` module-level constant).
- **Unit:** `"1"` (count semantics per OTel + Prometheus convention).
- **Description:** names `collect_event_class_snapshots` (the Week 2 primitive consumed under the hood) + the cumulative-counter semantics + the per-window rate query via PromQL's `rate()` / `increase()`.
- **Callback:** a closure capturing `led` + `since_window` + `now` + `expected_classes` + `breakdown_by`; on each scrape it computes `since = now() - since_window` + invokes `collect_event_class_snapshots(led, since=since, now=now(), expected_classes=expected_classes, breakdown_by=breakdown_by)` + yields ONE `Observation` per `MetricSnapshot`. Each Observation carries `event_class` + `channel` attributes (the `channel` attribute coerces `None` to the literal string `"none"` per the OTel-attribute-cannot-be-None workaround).

**Stateless callback per ADR-0050 D272 + R033 mitigation.** The closure does NOT cache state across scrapes; every callback re-walks the ledger fully. The per-scrape cost is the same as one `collect_event_class_snapshots` call (~O(N) at v1 scale).

**Diagnostic emit at every scrape per ADR-0051 D279.** The per-scrape ledger walk MAY emit `observability_class_uncatalogued` diagnostics into the ledger (the underlying `collect_event_class_snapshots` writes them); operators see the recurring signal in the per-event-class metric + investigate. R034 + R035's worst-case interaction: a Prometheus scrape interval of 15s × 86400s/day × at-most-TWO diagnostics/scrape = up to 11520 diagnostics/day per single-tenant operator in worst-case catalog-drift state. Mitigation: per-kind-per-call rate-limit holds; operators fix the catalog promptly when they see the recurring signal; Pillar I per-tenant audit-tooling filters `_emitted_by: "observability"` from per-operator dashboards.

### D285. Cumulative-counter semantics — `ObservableCounter` (NOT `Gauge`)

The per-event-class instrument is an `ObservableCounter` (cumulative monotonic non-decreasing). Per the Prometheus + OTel counter convention:

- **Cumulative semantics:** the count is the per-window event count from the per-call ledger walk; the per-call walk's window is `now - since_window`. Across consecutive scrapes against a fixed ledger state with a fixed `since_window`, the value is the SAME (the window's event count is stable). Under continuous appending to the ledger, the value GROWS — consistent with monotonic counter semantics.

- **Rate query pattern:** operators query the per-window rate via PromQL's `rate(outreach_factory_events_total[1h])` (the per-second rate over the last 1h) OR `increase(outreach_factory_events_total[1h])` (the total increase over 1h). This is the canonical Prometheus query pattern; switching to `Gauge` would force operators into non-standard queries + lose the Prometheus alerting + recording rule ecosystem.

- **`_total` suffix:** the Prometheus counter naming convention (any counter SHOULD end in `_total`). The OTel SDK's Prometheus exporter at Week 4 surfaces the instrument WITHOUT the `_total` suffix by default; the framework MUST configure the exporter to preserve the suffix OR rely on the OTel default's name-preservation. Week 4's ADR pins this detail.

The `since_window` kwarg parametrizes the per-scrape rolling-window range. Week 3 ships a rolling-window primitive (operator controls the window via the kwarg); Week 4 MAY switch to lifetime-cumulative on the Prometheus exporter side (the exporter computes cumulative from per-scrape rolling) IF the operator-side query story benefits.

### D286. Framework-neutrality contract — operator-supplied `MetricReader` via the `metric_readers` kwarg

Per ADR-0050 D273 + ADR-0050 D274 cross-pillar audit category 4: the framework MUST be neutral to the operator's observability backend. The `init_otel_meter_provider(metric_readers=...)` kwarg is the operator escape hatch:

| Operator backend | `metric_readers` value | Wired at |
|---|---|---|
| Self-hosted Prometheus | `[PrometheusMetricReader()]` | Pillar G Week 4 ships the canonical wiring at `orchestrator/observability.py` (or a sub-module `_prometheus_exporter.py` if surface grows) |
| OTLP collector (Honeycomb / Datadog / Grafana Cloud) | `[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=...))]` | Operator-side; framework does NOT ship the OTLP exporter import (per ADR-0050 §Migration/rollout — only the three core OTel packages) |
| In-memory (tests) | `[InMemoryMetricReader()]` | Test fixtures at `tests/test_observability.py` |
| No exporter (Week 3 default) | `[]` (empty) | Week 3 ships the default; Week 4 adds the canonical Prometheus exporter wiring |

**Week 3 default = empty `metric_readers`.** The MeterProvider accepts no readers; instruments register, callbacks register, but no scrape fires until a reader is added. This preserves the framework-neutrality contract — operators with vendor-specific backends can wire their reader BEFORE Pillar G Week 4's Prometheus-default lands.

### D287. Default `Resource`-attribute closed-set — `service.name` + `service.version` + the OTel SDK auto-injected `telemetry.sdk.*`

The framework default `Resource` carries TWO operator-overridable keys + the OTel SDK auto-injected keys:

```python
Resource.create({
    SERVICE_NAME: "outreach-factory",       # service.name
    SERVICE_VERSION: "0.1.0",               # service.version
})
# OTel SDK auto-injects:
#   telemetry.sdk.language: "python"
#   telemetry.sdk.name:     "opentelemetry"
#   telemetry.sdk.version:  "1.38.0"
```

**Operator extension via `init_otel_meter_provider(resource=...)`.** Pillar I per-tenant audit-tooling at OSS bring-up extends Resource with per-tenant labels:

```python
operator_resource = Resource.create({
    SERVICE_NAME: "outreach-factory",
    SERVICE_VERSION: "0.1.0",
    "outreach_factory.tenant_id": "tenant-a",       # operator key
    "outreach_factory.environment": "prod",         # operator key
})
init_otel_meter_provider(resource=operator_resource)
```

The framework's `service.*` keys are PRESERVABLE in the operator-extended set — operators just include both framework + operator keys in their `Resource.create` call.

**Module-level constants pinning the default values:**

```python
_SERVICE_NAME: str = "outreach-factory"
_SERVICE_VERSION: str = "0.1.0"
```

Future Pillar G weeks MAY bump `_SERVICE_VERSION` when the per-event-class instrument set extends in a way that affects downstream provenance tracking; the bump is operator-visible via the OTLP / Prometheus Resource attributes.

## Alternatives considered

### D282 alternatives (OTel SDK initialization shape)

1. **Top-level `__init__.py` invocation auto-initializes the MeterProvider on import.** Rejected — auto-initialization-on-import creates side effects at module load time; operators running tests or one-off scripts get unexpected OTel scrapes; the OTel set-once semantics enforce ONE init per process which conflicts with multi-test isolation. Explicit `init_otel_meter_provider()` calls preserve operator control.

2. **Sub-module at `orchestrator/observability/_otel_init.py` (deferred sub-module per ADR-0050 D273's "if surface grows" hint).** Rejected at Week 3 — the OTel surface at Week 3 is ~250 LOC; co-located at `orchestrator/observability.py` keeps the file at ~880 LOC, well below the ~7500 LOC split threshold. Sub-module split would create the "look in two places" mental model. Future Pillar G weeks MAY split if the OTel surface grows past the threshold (e.g., Week 4's Prometheus exporter wiring + Week 7-8's SLO alerting + Week 10-11's per-Person dashboards together push the file past the threshold).

3. **Initialize via `pyproject.toml` `[tool.opentelemetry]` config block.** Rejected — operator-side configuration via pyproject is an OTel community trajectory but not yet a stable feature; framework's explicit Python API preserves portability across operator backends. Pillar I OSS bring-up may revisit if the OTel community standardizes a config block convention.

4. **Defer the runtime initialization to Pillar G Week 4 (ship only the Prometheus exporter wiring at Week 3).** Rejected — the per-week trajectory at ADR-0050 D273's table names Week 3 as the OTel SDK initialization; Week 4 lands the Prometheus exporter on top of the Week 3 initialization. Deferring would compress two weeks into one + lose the per-week scope discipline.

### D283 alternatives (`Meter` scope name)

1. **Per-Pillar-G-week sub-scopes (`orchestrator.observability.events` + `orchestrator.observability.alerting` + `orchestrator.observability.cost` + `orchestrator.observability.per_person`).** Rejected — operators consuming the OTLP / Prometheus export see one namespace per the per-pillar-symmetry-with-shared-aggregation pattern per RETRO-pillar-f.md item 5. Per-week sub-scopes would force operators to enumerate per-Pillar-G-week scopes to find the metric they want; single canonical scope preserves operator ergonomics.

2. **Per-event-class sub-scopes (`orchestrator.observability.send_intent` + `orchestrator.observability.send_confirmed` + ...).** Rejected — the per-event-class aggregation is the instrument's RESPONSIBILITY; the Meter scope is a higher-level grouping. Per-event-class sub-scopes would N-times-ify the OTel scope set (~50 scopes); operators consuming the OTLP export would see thousands of metric-per-scope rows.

3. **Match the Python module path verbatim (`orchestrator.observability`).** Accepted — the chosen design. Predictable for operators inspecting the OTLP / Prometheus export; mirrors the Python import path operators see in tracebacks.

### D284 alternatives (per-event-class instrument shape)

1. **One instrument per event class (`outreach_factory_send_intent_total` + `outreach_factory_send_confirmed_total` + ...).** Rejected — N-times-ify the instrument set (~50 instruments); operators consuming the Prometheus export see 50+ metric names instead of one. The OTel convention is FEWER instruments × MORE attributes — the `outreach_factory_events_total` instrument with `event_class` + `channel` attributes IS the canonical shape.

2. **One instrument per (event_class, channel) pair (~200 instruments at ~50 classes × 4 channels).** Rejected — the cross-product N×M-ifies the instrument set even further; operators query the per-channel rate via the attribute-based filter `outreach_factory_events_total{event_class="send_intent", channel="email"}` which IS the canonical Prometheus query shape.

3. **Use `create_counter` (synchronous) + push observations at every `Ledger.append`.** Rejected — push-on-append couples the observability concern to the producer-side ledger primitive; ADR-0050 D272 + ADR-0051 D278 explicitly chose CONSUMER-SIDE aggregation. The push-on-append pattern would inflate the producer's per-append cost (every append calls OTel's instrumentation machinery) + create the cache-substrate-divergence concern per R033.

4. **Use `create_observable_gauge` (point-in-time gauge).** Rejected — gauge semantics don't match the per-event-class count (which is monotonic, not point-in-time). See D285 + alternatives.

### D285 alternatives (cumulative-counter semantics)

1. **`Gauge` (point-in-time).** Rejected — the per-event-class count is monotonic (events are append-only); a gauge would force operators into a non-standard query shape + lose the Prometheus `rate()` / `increase()` ecosystem.

2. **`UpDownCounter` (bidirectional cumulative).** Rejected — events are append-only at the Phase 5.5 ledger; counts only grow, never shrink. UpDownCounter would surface non-monotonic semantics operators don't need.

3. **`Histogram` (per-event timing distribution).** Rejected — the per-event-class instrument tracks COUNTS, not per-event timings. Future Pillar G Week 4 adds the per-channel send-latency histogram as a SEPARATE instrument; the per-event-class counter is a different concern.

### D286 alternatives (framework-neutrality contract)

1. **Hard-code the Prometheus exporter at Week 3.** Rejected — operators with Honeycomb / Datadog / Grafana Cloud would need to re-instrument; the OTel SDK's vendor-neutral instrumentation surface IS the cross-vendor portability story per ADR-0050 D273. The `metric_readers=` kwarg lets operators wire any OTel `MetricReader`.

2. **Initialize with a default `PrometheusMetricReader()` + let operators override.** Rejected at Week 3 — Week 3's default is EMPTY readers (per the per-week trajectory); Week 4 lands the Prometheus exporter as the canonical default. Initializing with Prometheus at Week 3 would force operators with OTLP backends to override BEFORE Pillar G Week 4 ships.

3. **Per-tenant `MetricReader` factories at Pillar I OSS bring-up.** Accepted as a forward-reference — Pillar I per-tenant audit-tooling will surface per-tenant `MetricReader` configuration; Pillar G Week 3 ships the framework-neutrality contract that Pillar I extends.

### D287 alternatives (`Resource`-attribute closed-set)

1. **No default Resource — let operators supply.** Rejected — operators without OTel expertise should see a sane default; the framework's `service.name` + `service.version` pin makes the OTLP export immediately recognizable in operator backends.

2. **Hardcode operator-specific keys (e.g., `outreach_factory.tenant_id`).** Rejected — per-tenant labels are Pillar I scope (per ADR-0050 D276(d)); Pillar G Week 3 is single-tenant. The framework default preserves the operator-extension path via the `resource=` kwarg.

3. **Auto-detect Resource attributes from the environment (e.g., `OTEL_RESOURCE_ATTRIBUTES` env var).** Accepted as a future extension — the OTel SDK auto-detects this env var by default; the framework default Resource merges with auto-detected attributes per OTel SDK behavior. Pillar G Week 3 does NOT explicitly opt out; operators setting `OTEL_RESOURCE_ATTRIBUTES` see their attributes in the export.

## Consequences

### Positive

- **The framework is now OTel-instrumented at Week 3** — operators consuming the OTLP / Prometheus export see the per-event-class count via the canonical `outreach_factory_events_total` instrument. The Week 4 commit adds the Prometheus exporter wiring + the first Grafana dashboard.
- **The framework-neutrality contract is operationally LIVE** — operators with different observability backends wire their reader via `init_otel_meter_provider(metric_readers=...)` without code changes to the framework.
- **The cumulative-counter semantics align with the Prometheus + OTel ecosystem** — operators query the per-window rate via PromQL's `rate()` / `increase()`; alerting + recording rules follow the canonical patterns.
- **The single canonical OTel scope `orchestrator.observability` preserves the per-pillar-symmetry-with-shared-aggregation pattern** — every Pillar G instrument shares the scope; operators see one namespace.
- **The default Resource carries `service.name` + `service.version`** — operators see the framework's name in the OTLP export; per-tenant extensions preserve the framework keys.
- **R035 NEW risk surfaced at design time** — operators running multiple framework invocations in the same Python process see the OTel set-once enforcement; the `set_global=False` kwarg gives tests an escape hatch + production callers initialize ONCE at startup per the OTel spec.
- **The per-event-class `ObservableCounter` callback is stateless per ADR-0050 D272 + R033 mitigation** — every scrape re-walks the ledger fully; no per-scrape cache substrate.
- **The channel-on-every-event invariant per ADR-0014 D33 + ADR-0051 D281 flows through the OTel wrapper** — the per-Observation `channel` attribute surfaces the homogeneous channel value OR the literal `"none"` (because OTel attributes do NOT accept `None`).

### Negative

- **The framework now imports `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-prometheus`** — operators upgrading from Pillar G Week 2 must `pip install` the three packages (per ADR-0050 §Migration/rollout). The `requirements.txt` extension at Week 3 lists the canonical version pins.
- **OTel set-once enforcement creates per-process global state (R035)** — operators running multiple framework invocations in the same Python process see the FIRST init's provider persist; subsequent inits silently no-op. Mitigation: `set_global=False` kwarg for tests; production callers initialize ONCE.
- **The per-scrape diagnostic emit MAY inflate R034's worst-case ledger volume** — Prometheus's 15s default scrape × 86400s/day × at-most-TWO diagnostics/scrape = up to 11520 diagnostics/day per single-tenant operator in worst-case catalog-drift state. Mitigation: operators fix the catalog promptly; Pillar I per-tenant audit-tooling filters `_emitted_by: "observability"` from per-operator dashboards.
- **The test surface adds ~470 LOC** — `tests/test_observability.py` ships 39 NEW tests (~470 LOC) covering the cell-level matrix per the Pillar F Week 6-12 + Pillar G Week 2 per-week-reviewer discipline. The LOC is content-additive; the file is well below the ~7500 LOC split threshold.

### Neutral

- **The OTel scope version `0.1.0` is the first pin per ADR-0052 D283** — bumps at the per-week ADR when the per-event-class instrument set extends in a non-backwards-compat way. Operators consuming the OTLP / Prometheus export see the scope version in the metric metadata.
- **The Pillar G Week 4 Prometheus exporter wiring is decoupled from Week 3's SDK initialization** — Week 4 adds `init_prometheus_exporter()` (or similar) that creates + returns a `PrometheusMetricReader`; operators pass it to `init_otel_meter_provider(metric_readers=[exporter])`. The framework's separation of concerns IS the framework-neutrality contract.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — the OTel wrapper consumes `collect_event_class_snapshots` which reads from the ledger; the OTel export is a denormalized rebuildable view per `docs/SOURCES-OF-TRUTH.md`. The diagnostic emit at every scrape writes to the ledger (the same write surface as Week 2); the ledger remains SoT.
- **I2 (Atomicity contract).** Compliant — the OTel wrapper's callback uses `Ledger.append` (via the underlying primitive) which is atomic per the Phase 5.5 contract.
- **I3 (Single source of truth).** Compliant — every scrape re-walks the ledger fully; no derived state cached at the OTel wrapper level.
- **I4 (Determinism).** Compliant per the deterministic-clock contract per ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278 — the `now=` callable kwarg controls the per-scrape anchor; tests pass a captured-lambda for byte-identical reproducibility.
- **I5 (Refuse loud).** Compliant — `breakdown_by` disallowed dims raise `ValueError` at scrape time per the privacy invariant; ts-missing events emit the `kind="missing_ts"` diagnostic per ADR-0051 D279.
- **I6 (No silent state).** Compliant — every state change (the diagnostic emit) is observable as a ledger event; the OTel wrapper does NOT cache state across scrapes.
- **I7 (Refuse loud on broken pipelines).** Compliant per the same ts-missing + uncatalogued diagnostic posture inherited from ADR-0051 D279.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — `_BREAKDOWN_DIMS_ALLOWED` refuse-loud is operationally LIVE at the OTel wrapper (the `breakdown_by` kwarg forwards to the primitive's validation).
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D284 — `MetricSnapshot.channel` surfaces directly to the per-Observation `channel` attribute (with `None` coerced to `"none"` literal for OTel-attribute compatibility).
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 3 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — Pillar G Week 3 does not extend any of the five layers; it CONSUMES the per-Pillar-F event classes + the Layer 5 `reconcile_drift.reason` via the per-Person dashboard adapter trajectory at D277 (Week 10-11 implementation).

## Downstream pillar impact

- **Pillar G Week 4** (Prometheus exporter wiring + first Grafana dashboard) — extends the framework with `init_prometheus_exporter()` (or similar) returning a `PrometheusMetricReader`; operators pass it to `init_otel_meter_provider(metric_readers=[exporter])`. The Week 3 framework-neutrality contract IS the seam Week 4 builds on. The first Grafana dashboard at `infra/grafana/dashboards/overview.yml` consumes the `outreach_factory_events_total` instrument for the operator-visible per-event-class + per-channel rate display.
- **Pillar G Week 5-6** (OTel tracing instrumentation through the pipeline) — adds the `opentelemetry-api`'s `tracer` surface; the per-stage span instrumentation lands at the discovery → enrichment → research → draft → review → send → reply → win/loss pipeline. The Week 3 OTel SDK initialization is the seam — tracing initialization extends `init_otel_meter_provider` (or adds a sibling `init_otel_tracer_provider`) that consumes the same `Resource` per the framework-neutrality contract.
- **Pillar G Week 7-8** (SLO violation detector + `slo_violation_detected` event class emit) — adds the per-window SLO check + the Slack webhook wiring. The SLO check's per-window aggregation reuses `collect_event_class_snapshots`; the `slo_violation_detected` emit follows the same Ledger.append pattern as the Week 2 `observability_class_uncatalogued` diagnostic.
- **Pillar G Week 9** (cost dashboard) — extends the per-event-class instrument with per-source breakdown (per the `cost_incurred.source` attribute). The Week 3 `breakdown_by` kwarg + the privacy invariant per `_BREAKDOWN_DIMS_ALLOWED` IS the seam (Week 9 MAY extend `_BREAKDOWN_DIMS_ALLOWED` to include `source` if the per-tenant cost dashboard at Pillar I needs it — Pillar G's single-tenant scope keeps the per-source breakdown within the existing closed-set).
- **Pillar G Week 10-11** (per-Person observability surface) — the per-Person dashboard adapters CONSUME the per-event-class `ObservableCounter` instrument via the framework-neutrality contract (operators wire a per-Person `MetricReader` OR consume the OTLP export); the per-Pillar-F event class consumption per ADR-0050 D277 flows through the same instrument.
- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — composes the primitive + the SLO alerting + the per-Person dashboards into the one-CLI-invocation binding scenario per ADR-0050 D275 + PILLAR-PLAN §2 Pillar G's binding text. The OTel framework decision per ADR-0050 D273 + ADR-0052 D282-D287 is the foundation Week 12 closes against.
- **Pillar H (daemon + scale)** — the per-scrape stateless callback's O(N) cost may grow at multi-machine scale; Pillar H may revisit (e.g., per-event-class index in the ledger; per-window cache substrate). The framework-neutrality contract is preserved at multi-machine scale per the OTel SDK's multi-process posture; R035 (OTel set-once enforcement) creates per-process state — Pillar H's multi-machine daemon may need per-daemon-process MeterProvider isolation.
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends `Resource` with per-tenant labels; the framework's `service.*` keys are preservable. Per-tenant `MetricReader` configuration follows the framework-neutrality contract (operators wire per-tenant readers per the Pillar I per-tenant config substrate).
- **Pillar J (GDPR purge)** — the diagnostic events MAY carry `person_id` (in the `kind="missing_ts"` case); Pillar J's per-Person purge transaction extends to the per-scrape diagnostic events alongside the rest of the per-Person event set. The R034 mitigation per ADR-0051 D279 + R035 mitigation per this ADR's design preserves the per-Person purge boundary.

## Migration / rollout

- **Operator-side action required at Week 3 upgrade:** **`pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-prometheus`** per the `orchestrator/requirements.txt` extension. The three packages are MIT/Apache 2.0; no commercial license concerns.
- **First call post-upgrade:** operators running `python -c "from orchestrator.observability import init_otel_meter_provider, register_event_class_observable_counter; ..."` see the OTel surface immediately available. Production callers initialize ONCE at startup with `init_otel_meter_provider()`; subsequent process inits silently no-op per OTel's set-once enforcement.
- **Per-tenant migration at Pillar I** — content-additive at Pillar G Week 3; per-tenant audit-tooling at Pillar I extends `Resource` with per-tenant labels.
- **No ledger schema migration** — Week 3 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1 + Week 2).
- **No new event classes** — Week 3 ships ZERO new event classes; the existing `observability_class_uncatalogued` + `slo_violation_detected` set per `OBSERVABILITY_NEW_EVENT_CLASSES` (Week 1) + the per-kind disambiguator on `observability_class_uncatalogued` (Week 2) are preserved verbatim.
- **OTel set-once caveat for tests:** tests pass `set_global=False` to bypass OTel's set-once enforcement; production callers keep `set_global=True` (the default).
- **Week 4 will ADD Prometheus exporter wiring** — operators wiring the Prometheus exporter at Week 4 will see the `outreach_factory_events_total` metric on the Prometheus exposition endpoint; Week 3 leaves the exporter wiring to the operator per the framework-neutrality contract.

## Existing-operator seed

Operator action required at Week 3: **`pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-prometheus`** (per the `orchestrator/requirements.txt` extension).

Recommended (optional): operators wanting to consume the OTel surface at Week 3 invoke `init_otel_meter_provider()` at startup + `register_event_class_observable_counter(led, since_window=timedelta(days=30))` for the per-event-class instrument. The Week 3 default is EMPTY readers — operators wiring a Prometheus exporter at Week 4 (or a vendor-specific OTLP exporter today) pass it via `init_otel_meter_provider(metric_readers=[exporter])`.

## References

- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. The Week 1 framework decision pinned the OTel SDK + Prometheus exporter + Grafana-as-code; Week 3 lands the runtime initialization per the trajectory at D273.
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. The Pillar G Week 3 commit preserves the Pillar F primitive surfaces + Layer 5 backstop verbatim.
- **ADR-0038** (Pillar F foundation). D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields).
- **ADR-0037** (Pillar E Week 12 close + Stable flip). D172 (Pillar E Stable flip discipline; ~7500 LOC split threshold flag for the cross-pillar coherence test vehicle).
- **ADR-0034** (Pillar E Week 1 — discovery dedup primitive + deterministic-clock contract). D156 (deterministic-clock kwarg discipline carried forward through Pillar E + F + G).
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state).
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant).
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers).
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2 §18 + Week 3 §19 extension per this commit).
- `.planning/HANDOFF-pillar-g-week-2.md` — Pillar G Week 2 close summary + Pillar G Week 3 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 3 close summary.
- `docs/RISK-REGISTER.md` R031 + R032 + R033 (Pillar G Week 1 risks); R034 (Pillar G Week 2 — diagnostic emit at every primitive call inflates ledger when catalog drift persists); R035 (NEW Week 3 — OTel SDK's set-once `set_meter_provider` enforcement creates per-process global state; severity 1 / likelihood 2; `set_global=False` mitigation for tests + production single-init).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 3 ADR-0052 references.
- `orchestrator/observability.py` — the Pillar G Week 1 module shape + the Week 2 primitive body + the Week 3 OTel SDK initialization + Meter accessor + per-event-class ObservableCounter registration.
- `orchestrator/requirements.txt` — Pillar G Week 3 adds `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-prometheus` per ADR-0050 §Migration/rollout.
- `tests/test_observability.py` (extended Week 3) — 39 NEW tests covering the cell-level matrix per the Pillar F Week 6-12 + Pillar G Week 2 per-week-reviewer discipline.
- `tests/test_multi_channel_coherence.py::TestPillarGObservability::test_observability_framework_is_opentelemetry_sdk` (UN-SKIPPED Week 3) — verifies the OTel SDK framework choice via the public surface + the canonical Meter scope name + the canonical instrument name.
