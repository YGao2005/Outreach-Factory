# ADR-0053: Pillar G Week 4 — Prometheus exporter wiring, per-channel send-latency Histogram, reconcile success ratio ObservableGauge, Prometheus HTTP exposition server posture, framework-default `View` set, first Grafana-as-code dashboard

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 4 Prometheus exporter + first Grafana dashboard)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape + the OTel SDK + Prometheus exporter + Grafana-as-code framework decision per D273. ADR-0051 (Pillar G Week 2, D278-D281) shipped the `collect_event_class_snapshots` body + the `observability_class_uncatalogued` diagnostic emit. ADR-0052 (Pillar G Week 3, D282-D287) shipped the OTel SDK initialization + the single canonical Meter scope `orchestrator.observability` + the per-event-class `outreach_factory_events_total` ObservableCounter + the cumulative-counter semantics + the framework-neutrality contract + the default Resource-attribute closed-set. The three prior weeks deliberately deferred the Prometheus exporter wiring + the bare metric set extension + the Grafana-as-code dashboard to Week 4 per the per-week trajectory at ADR-0050 D273.

Pillar G Week 4 ships the **Prometheus exporter wiring** + the **per-channel send-latency Histogram instrument** + the **reconcile success ratio ObservableGauge** + the **Prometheus HTTP exposition server** + the **framework-default `View` set** + the **first Grafana-as-code dashboard** at `infra/grafana/dashboards/overview.yml`. The six concerns this ADR resolves:

1. **Prometheus exporter wiring shape.** The OTel SDK + Prometheus exporter wiring per ADR-0050 D273 must (a) preserve the framework-neutrality contract per ADR-0052 D286 (operators with OTLP backends skip the Prometheus exporter); (b) expose the per-event-class metric via the Prometheus exposition format; (c) preserve the `_total` suffix on the counter instrument (the Prometheus naming convention per ADR-0052 D285); (d) ship a per-process HTTP exposition server with an operator-deliberate posture (default OFF; default bind 127.0.0.1).

2. **Per-channel send-latency Histogram instrument shape.** Per ADR-0050 D273's trajectory table + ADR-0052 D285's "Week 4 may add per-channel send-latency histogram as a SEPARATE instrument" — the per-channel send-latency Histogram MUST (a) carry the channel attribute uniformly per ADR-0014 D33; (b) use explicit histogram buckets spanning sub-millisecond to 10s with the 5s SLO threshold per PILLAR-PLAN §2 Pillar G as an explicit bucket boundary (so operators query the p99 SLO violation without bucket interpolation); (c) use the Prometheus + OTel unit convention with `_seconds` suffix.

3. **Reconcile success ratio instrument semantics.** Per PILLAR-PLAN §2 Pillar G's binding text — "reconcile success < 99%" alerting threshold — the reconcile success ratio MUST be (a) point-in-time (NOT cumulative; a ratio that may move up or down across scrapes as the window rolls); (b) bounded in [0, 1]; (c) operator-queryable via a simple PromQL inequality. The choice of ObservableGauge vs ObservableCounter vs synchronous Gauge is load-bearing.

4. **Prometheus HTTP exposition server posture.** The framework MUST decide whether to (a) auto-start the HTTP server at module import (forced-on; convenient but exposes metrics without operator consent); (b) operator-deliberate (the framework ships the function; operators explicitly invoke at startup); (c) defer entirely to the operator (no helper function). Per ADR-0052 D286 + R035 + the security-by-default discipline — operator-deliberate with a 127.0.0.1 bind default is the chosen posture.

5. **Framework-default `View` set.** The OTel SDK's default Histogram boundaries (0, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000) are too coarse for the framework's sub-second send-latency profile. The framework MUST ship default Views overriding the SDK defaults via `ExplicitBucketHistogramAggregation`. The `init_otel_meter_provider` signature MUST accept a `views=` kwarg accepting operator overrides per the framework-neutrality contract.

6. **First Grafana-as-code dashboard.** Per ADR-0050 D273 — "Grafana-as-code dashboards at `infra/grafana/`". Week 4 ships the first dashboard at `infra/grafana/dashboards/overview.yml` rendering the three binding exit-criterion questions per ADR-0050 D275. The dashboard format MUST be (a) operator-readable; (b) version-controllable in git; (c) consumable by future Grafana-provisioning code (or directly importable via Grafana's UI).

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED from ADR-0050 + ADR-0052; the closed-set `EVENT_CLASS_CATALOG | OBSERVABILITY_NEW_EVENT_CLASSES` IS the mitigation. The Week 4 Prometheus exporter consumes the same closed-set via the per-event-class ObservableCounter's callback closure.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED from ADR-0050 + ADR-0052; the stateless callback contract per ADR-0052 D284 preserves the mitigation. The Week 4 send-latency Histogram is a synchronous instrument — operators record per-channel at the dispatch point; the histogram aggregation is per-MeterProvider in-process.

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED from ADR-0051; the per-kind-per-call rate-limit holds. The Week 4 Prometheus scrape cycle does NOT change the diagnostic emit semantics — every scrape re-walks the ledger via the same `collect_event_class_snapshots` primitive.

- **R035 (OTel SDK's set-once `set_meter_provider` enforcement creates per-process global state)** — UNCHANGED from ADR-0052; the `set_global=False` kwarg for tests + production single-init at startup mitigation continues. The Week 4 Prometheus exporter wiring inherits the set-once posture.

- **R036 (NEW) — Prometheus HTTP exposition server exposes per-process metrics over the network.** The `start_prometheus_http_server(port=, addr=)` function exposes the framework's metrics on an HTTP endpoint. **Failure mode:** an operator binding to `0.0.0.0` (all interfaces) on a public-facing host without firewall + authentication separately wired exposes the framework's per-event-class counts + per-channel send latencies + reconcile success ratio to the public internet. The framework's metrics carry operator-confidential information about pipeline volumes + per-channel rates + reconcile drift counts; a malicious observer could infer operator activity patterns. Mitigation by design at ADR-0053 D291: (a) the framework default is `_DEFAULT_PROMETHEUS_ADDR = "127.0.0.1"` (localhost-only bind — operators on a single-host deployment see metrics; external observers see connection-refused); (b) operators deliberately expose externally via `addr="0.0.0.0"` IF they wire firewall + authentication separately (Pillar I per-tenant audit-tooling at OSS bring-up may surface a per-tenant auth wrapper); (c) the function is NOT auto-called at module import — operators explicitly invoke at startup.

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12. The Pillar G Week 1-3 surfaces preserve verbatim.

## Decision

### D288. Prometheus exporter wiring — `init_prometheus_metric_reader` at `orchestrator/observability.py`

`orchestrator/observability.py::init_prometheus_metric_reader()` is the canonical Prometheus reader factory. The signature + contract:

```python
def init_prometheus_metric_reader() -> PrometheusMetricReader:
    """Return a PrometheusMetricReader per ADR-0053 D288."""
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    return PrometheusMetricReader()
```

Operators wire the returned reader via `init_otel_meter_provider(metric_readers=[reader])` per ADR-0052 D286's framework-neutrality contract. The reader registers a per-process Prometheus collector on `prometheus_client.REGISTRY`; operators starting the HTTP exposition server via `start_prometheus_http_server` consume from this same registry.

**Lazy import.** The `prometheus_client` + `opentelemetry.exporter.prometheus` packages import only when the operator calls `init_prometheus_metric_reader` (or `start_prometheus_http_server` / `render_prometheus_exposition`). Operators with OTLP-only setups (no Prometheus exporter use) do NOT pay the import cost at module load — the framework-neutrality contract per ADR-0052 D286 is preserved.

Module placement: **co-located at `orchestrator/observability.py`** per ADR-0052 D282's per-pillar single-file mental model. The Week 4 surface adds ~280 LOC; total module size ~1160 LOC, well below the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266 + ADR-0050 D275.

### D289. Per-channel send-latency Histogram — `outreach_factory_send_latency_seconds`

`orchestrator/observability.py::get_send_latency_histogram(meter=None)` returns the canonical per-channel send-latency Histogram. The signature + contract:

```python
def get_send_latency_histogram(
    meter: Meter | None = None,
) -> Histogram:
    """Return the per-channel send-latency Histogram per ADR-0053 D289."""
    if meter is None:
        meter = get_meter()
    return meter.create_histogram(
        name=_INSTRUMENT_NAME_SEND_LATENCY_SECONDS,
        unit="s",
        description=...,
    )
```

**Instrument shape:**

- **Name:** `outreach_factory_send_latency_seconds` (per `_INSTRUMENT_NAME_SEND_LATENCY_SECONDS` module-level constant). The `outreach_factory_` prefix is the per-framework namespace per ADR-0052 D284; the `_seconds` suffix is the Prometheus + OTel histogram unit convention.
- **Unit:** `"s"` (seconds; matches the Prometheus convention).
- **Type:** `Histogram` (synchronous; operators call `.record()` with per-channel attribute).
- **Channel attribute on `.record()`:** Operators MUST pass `{"channel": <channel>}` per ADR-0014 D33's channel-on-every-event invariant + ADR-0050 D276(c). The histogram aggregates per-channel automatically.
- **Buckets:** `_SEND_LATENCY_BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)` — applied via the default View per `default_views()` per D292. The 5s bucket is explicit so the p99 SLO threshold per PILLAR-PLAN §2 Pillar G is operator-queryable via PromQL's `histogram_quantile` at the 5s boundary without interpolation.

**Synchronous instrument vs observable.** OTel Python SDK has no `ObservableHistogram` (as of 1.38) — synchronous Histogram is the only choice. The dispatcher integration is a Pillar H + Pillar G Week 5-6 (tracing) concern; Week 4 ships the SHAPE. Operators wanting the histogram populated today wire the `histogram.record()` call at their dispatcher's two-phase commit point in `skills/send-outreach/scripts/send_queued.py`.

### D290. Reconcile success ratio ObservableGauge — `outreach_factory_reconcile_success_ratio`

`orchestrator/observability.py::register_reconcile_success_ratio_gauge(led, *, since_window, now=None, meter=None)` registers the canonical reconcile success ratio ObservableGauge. The signature + contract:

```python
def register_reconcile_success_ratio_gauge(
    led: "_ledger.Ledger",
    *,
    since_window: timedelta,
    now: Callable[[], datetime] | None = None,
    meter: Meter | None = None,
) -> "_ObservableGauge":
    """Register the reconcile success ratio per ADR-0053 D290."""
```

**Instrument shape:**

- **Name:** `outreach_factory_reconcile_success_ratio` (per `_INSTRUMENT_NAME_RECONCILE_SUCCESS_RATIO` module-level constant). The `outreach_factory_` prefix is the per-framework namespace per ADR-0052 D284; NO suffix per the Prometheus gauge convention (gauges are bare metric names; only counters carry `_total`).
- **Unit:** `"1"` (ratio; dimensionless).
- **Type:** `ObservableGauge` (point-in-time; per-window aggregate that may move up or down across scrapes).
- **Callback:** Stateless closure (per ADR-0050 D272 + R033 mitigation). Walks the ledger via `collect_event_class_snapshots(led, since=anchor - since_window, now=anchor)` + computes:
  - `N_healed = snapshots[reconcile_healed].total_count` (default 0)
  - `N_drift = snapshots[reconcile_drift].total_count` (default 0)
  - `ratio = N_healed / (N_healed + N_drift)` if denominator > 0, else `1.0`

**Edge cases (operationally interpreted):**

| Window content | Denominator | Ratio | Operator interpretation |
|---|---|---|---|
| Empty (no reconcile activity) | 0 | **1.0** | Vacuous success (no failures = success) |
| Drift-only (no heal) | drift > 0 | **0.0** | Total failure |
| Drift + heal | drift + heal > 0 | `heal / (heal + drift)` | Per-window success rate |

The vacuous-success-returns-1.0 choice preserves the SLO query semantics per PILLAR-PLAN §2 Pillar G — `outreach_factory_reconcile_success_ratio < 0.99` does NOT fire on vacuous windows. Operators on idle pipelines see no false alerts.

### D291. Prometheus HTTP exposition server — `start_prometheus_http_server` + `render_prometheus_exposition`

`orchestrator/observability.py::start_prometheus_http_server(port=8000, addr="127.0.0.1")` starts the Prometheus exposition HTTP server. The signature + contract:

```python
def start_prometheus_http_server(
    port: int = _DEFAULT_PROMETHEUS_PORT,
    addr: str = _DEFAULT_PROMETHEUS_ADDR,
) -> None:
    """Start the Prometheus exposition HTTP server per ADR-0053 D291."""
    from prometheus_client import start_http_server
    start_http_server(port=port, addr=addr)
```

**Operator-deliberate posture per R036 mitigation:**

- **Default OFF.** The framework does NOT auto-start the HTTP server at module import. Operators wiring the Prometheus exposition externally explicitly call this function at process startup.
- **Default bind 127.0.0.1.** Security-by-default — operators on a single-host deployment see metrics; external observers see connection-refused. Operators deliberately expose externally via `addr="0.0.0.0"` IF they wire firewall + authentication separately.
- **Default port 8000.** `_DEFAULT_PROMETHEUS_PORT = 8000` — operators with conflicting port use pass `port=...`.

Companion function `render_prometheus_exposition()` returns the Prometheus exposition format as bytes (useful for tests + one-off operator calls without an HTTP server). Returns the same string the HTTP exposition endpoint serves.

### D292. Framework-default `View` set — `default_views()` + `init_otel_meter_provider(views=)`

`orchestrator/observability.py::default_views()` returns the framework's recommended `View` set. Week 4 returns ONE view — the per-channel send-latency Histogram bucket configuration:

```python
def default_views() -> tuple[View, ...]:
    return (
        View(
            instrument_name=_INSTRUMENT_NAME_SEND_LATENCY_SECONDS,
            aggregation=ExplicitBucketHistogramAggregation(
                boundaries=_SEND_LATENCY_BUCKETS_SECONDS,
            ),
        ),
    )
```

`init_otel_meter_provider` accepts a new `views=` kwarg:

- `views=None` (default) → `default_views()` applies (framework recommendation).
- `views=<iterable>` → operator-supplied views apply (overrides framework defaults).
- `views=()` → empty tuple; NO views (OTel SDK falls back to its default aggregation per instrument type).

Operators with different latency profiles pass their own View — e.g., higher-latency LinkedIn auth flows MAY want buckets up to 30s.

The default View pin overrides the OTel SDK default Histogram boundaries (0, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000) which are too coarse for sub-second send latencies.

### D293. First Grafana-as-code dashboard — `infra/grafana/dashboards/overview.yml`

`infra/grafana/dashboards/overview.yml` (NEW directory + NEW file) ships the first Grafana-as-code dashboard. The YAML format is a high-level operator-readable description of the dashboard structure — future Grafana-provisioning code (or a manual import into Grafana) consumes this format.

**Panels (rendering the three binding exit-criterion questions per ADR-0050 D275):**

1. **Per-event-class event rate (1h window)** — binding question 2 ("Where am I losing prospects?"). Query: `rate(outreach_factory_events_total[1h])` per-event-class + per-channel; operators see per-stage funnel drop-off via the per-event-class rates.
2. **Per-channel send-latency p99 (5m window)** — binding question 1 ("Why is dispatch slow today?"). Query: `histogram_quantile(0.99, sum(rate(outreach_factory_send_latency_seconds_bucket[5m])) by (le, channel))`; threshold line at 5s per PILLAR-PLAN §2 Pillar G.
3. **Reconcile success ratio (rolling window)** — operator-actionable SLO signal. Query: `outreach_factory_reconcile_success_ratio`; threshold steps at 0.95 (orange) + 0.99 (green) per PILLAR-PLAN §2 Pillar G.
4. **Per-event-class 24h cumulative breakdown** — binding question 3 ("What did the gate refuse this week?"). Query: `sum by (event_class) (increase(outreach_factory_events_total[24h]))`; operators inspect refusal event classes (`reconcile_drift`, `policy_blocked`, `cooldown_blocked`, `dedup_blocked`, `bounce_detected`, `hallucination_detected`).

**Carry-forwards documented inline (for future Pillar G weeks):**

- Week 5-6 (OTel tracing): adds per-stage span panels.
- Week 7-8 (SLO alerting): adds `slo_violation_detected` event panels + Slack webhook integration.
- Week 9 (cost dashboard): adds per-source cost panels.
- Week 10-11 (per-Person dashboards): adds per-register fidelity distribution + per-claim-type hallucination count + per-Person Layer 5 drift rate + per-operator override-rate panels.
- Week 12 (Stable flip): the binding exit-criterion test verifies operators answer all three questions via this dashboard + the funnel CLI in ONE invocation.

**Prometheus exposition format details (per Pillar G's metric naming convention):**

- Counter (`outreach_factory_events_total`): preserves `_total` suffix; Prometheus exposition surfaces as `# TYPE outreach_factory_events counter` + `outreach_factory_events_total{...}` lines.
- Histogram (`outreach_factory_send_latency_seconds`): surfaces as `_bucket` + `_sum` + `_count` metric family per Prometheus exposition spec.
- Gauge (`outreach_factory_reconcile_success_ratio`): surfaces as bare metric name (no suffix).

## Alternatives considered

### D288 alternatives (Prometheus exporter wiring)

1. **Hardcode the Prometheus exporter at init_otel_meter_provider's default.** Rejected — violates the framework-neutrality contract per ADR-0052 D286. Operators with OTLP backends (Honeycomb / Datadog / Grafana Cloud) would need to override the default BEFORE wiring their OTLP exporter; the explicit factory function preserves operator choice.

2. **Direct `prometheus_client.Counter` / `Gauge` instrumentation without OTel SDK.** Rejected — Pillar G Week 1's D273 picked the OTel SDK as the canonical observability framework for cross-vendor portability. Direct `prometheus_client` instrumentation would force operators with OTLP backends to dual-instrument; OTel SDK + Prometheus exporter preserves the framework-neutrality contract.

3. **Defer Prometheus exporter wiring to Pillar I OSS bring-up.** Rejected — Pillar G Week 4's binding-text in PILLAR-PLAN §2 Pillar G explicitly names "Prometheus metrics export"; the framework-neutrality contract per ADR-0052 D286 is preserved by ALSO supporting OTLP. Deferring Prometheus would defer the canonical default to a future pillar.

4. **Eager import of `prometheus_client` + `opentelemetry.exporter.prometheus` at module load.** Rejected — operators with OTLP-only setups would pay the import cost without using the Prometheus exporter; lazy import inside `init_prometheus_metric_reader` + `start_prometheus_http_server` + `render_prometheus_exposition` preserves the framework-neutrality contract's intent.

### D289 alternatives (per-channel send-latency Histogram shape)

1. **ObservableHistogram via callback walking ledger.** Rejected — OTel Python SDK 1.38 has no `ObservableHistogram` (only sync `Histogram`); we'd need to use `ObservableGauge` with bucket-shaped attributes, which is not the canonical Prometheus histogram exposition shape.

2. **One instrument per channel (`outreach_factory_send_latency_seconds_email`, `..._li_invite`, ...).** Rejected — N-times-ify the instrument set (~5 channels × 1 histogram = 5 instruments); the OTel convention is FEWER instruments × MORE attributes — the per-channel attribute on `.record()` IS the canonical shape.

3. **Cumulative latency counter (sum + count separately).** Rejected — operators querying p99 latency via PromQL's `histogram_quantile` need the explicit bucket distribution; separate sum + count loses the percentile query story.

4. **OTel SDK default Histogram boundaries (no View override).** Rejected — the SDK defaults (0, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000) are tuned for milliseconds; the framework's send-latency profile (sub-millisecond to ~10s) needs explicit boundaries. D292 ships the framework-default View overriding the SDK defaults.

### D290 alternatives (reconcile success ratio instrument shape)

1. **ObservableCounter (cumulative monotonic).** Rejected — the reconcile success RATIO is a per-window aggregate that may move up or down across scrapes (e.g., a window that previously had 0 drift now has 5 drift + 4 heal → ratio drops from 1.0 to 0.8). Counter semantics don't match.

2. **Two separate counters (`reconcile_drift_total` + `reconcile_healed_total`) with operator computing ratio in PromQL.** Rejected — operators querying the SLO threshold via `outreach_factory_reconcile_success_ratio < 0.99` is simpler than `outreach_factory_reconcile_healed_total / (outreach_factory_reconcile_healed_total + outreach_factory_reconcile_drift_total) < 0.99`; the ratio is operationally meaningful. ALSO — the per-event-class ObservableCounter per ADR-0052 D284 already surfaces `reconcile_drift` + `reconcile_healed` counts via the same `outreach_factory_events_total` instrument; the new ratio Gauge is a DERIVED metric for operator convenience.

3. **Synchronous Gauge with operator-pushed updates.** Rejected — the reconcile success ratio is a derived metric from the ledger; the per-Pass-C reconcile invocation would need to compute the ratio + push it on every reconcile. Stateless ObservableGauge callback per ADR-0050 D272 + R033 mitigation matches the existing per-event-class ObservableCounter design — every scrape re-walks the ledger.

4. **Ratio over a fixed rolling window (e.g., always 1h regardless of operator preference).** Rejected — operators tuning the SLO threshold for their cadence pass `since_window=` per the existing per-event-class instrument convention. The kwarg-controlled window preserves operator flexibility.

### D291 alternatives (Prometheus HTTP exposition server posture)

1. **Auto-start the HTTP server at module import.** Rejected — exposes metrics without operator consent + binds a port the operator may not have available + creates a side effect at module load (violates the explicit `init_otel_meter_provider` posture per ADR-0052 D282).

2. **Bind to `0.0.0.0` (all interfaces) by default.** Rejected — R036 surfaces: an operator on a public-facing host without firewall + authentication would expose internal metrics publicly. `127.0.0.1` (security-by-default) preserves the operator-deliberate posture.

3. **No helper function; defer entirely to operator code.** Rejected — operators wiring the Prometheus exposition without a framework helper would need to import `prometheus_client.start_http_server` themselves + risk inconsistent default port + bind addr. The framework helper documents the canonical default + preserves operator override via kwargs.

### D292 alternatives (framework-default `View` set)

1. **No default views (operators MUST configure).** Rejected — operators without OTel View expertise would see the OTel SDK's coarse default histogram buckets + get unusable percentile queries. The framework default is a sane choice operators can override.

2. **Default Views applied unconditionally (no `views=` kwarg).** Rejected — operators with different latency profiles (e.g., LinkedIn auth flows with higher latency) would need to fork the framework. The kwarg preserves operator override.

3. **Default Views as a global module constant (not a function).** Rejected — `View` objects are stateful inside OTel SDK (they accumulate registered instruments). Functions return fresh `View` instances per call, preserving test isolation + multi-MeterProvider scenarios.

### D293 alternatives (first Grafana-as-code dashboard format)

1. **Grafana JSON (the native dashboard format).** Rejected — JSON is verbose + machine-oriented; YAML is operator-readable + version-controllable. Future Pillar G weeks MAY add a JSON variant for direct Grafana import.

2. **Grafonnet-Python generator at runtime.** Rejected — adds a runtime dependency (`grafanalib` or `grafonnet`); operators consuming the YAML directly + future Grafana-provisioning code can generate JSON from the YAML when needed.

3. **One dashboard per binding question (3 dashboards instead of 1).** Rejected — the operator's three binding questions per ADR-0050 D275 are answered in ONE CLI invocation; splitting across 3 dashboards loses the cross-question coherence operators need.

4. **Dashboard provisioning YAML (Grafana's config file format) instead of a dashboard description YAML.** Rejected — provisioning YAML tells Grafana where to find dashboards; the dashboard itself still needs a format. The chosen YAML IS the dashboard description; future provisioning code wraps this.

## Consequences

### Positive

- **The framework's metrics are operator-visible via Prometheus exposition at Week 4** — operators wiring `init_prometheus_metric_reader()` + `start_prometheus_http_server()` at startup see the per-event-class counter + per-channel send-latency histogram + reconcile success ratio on the standard `http://127.0.0.1:8000/metrics` endpoint.
- **The framework-neutrality contract per ADR-0052 D286 is preserved at Week 4** — operators with OTLP backends skip `init_prometheus_metric_reader()` entirely + wire their own OTLP reader; the framework's instruments register the same way.
- **The first Grafana-as-code dashboard at `infra/grafana/dashboards/overview.yml`** answers the three binding exit-criterion questions per ADR-0050 D275 + surfaces the 99% reconcile success SLO + the 5s send-latency p99 SLO per PILLAR-PLAN §2 Pillar G.
- **The reconcile success ratio operator-actionable SLO signal is LIVE at Week 4** — operators query `outreach_factory_reconcile_success_ratio < 0.99` via Prometheus alerting (Week 7-8 ships the SLO alerting per ADR-0050 D273's trajectory).
- **The per-channel send-latency Histogram's framework-default buckets** preserve the 5s SLO threshold as an explicit bucket boundary — operators query `histogram_quantile(0.99, ...)` at the 5s boundary without bucket interpolation.
- **R036 NEW risk surfaced at design time** — the Prometheus HTTP exposition server's `127.0.0.1` security-by-default bind addresses an operationally-relevant misconfiguration before any operator hits it in production.
- **The framework-default `View` set** preserves operator-readable Histogram percentile queries via the explicit bucket configuration; operators with different latency profiles override via the `views=` kwarg.

### Negative

- **The Prometheus HTTP exposition server adds operational surface area** — operators must understand the bind address security implications + the default 8000 port may conflict with other services. Mitigation: the function is operator-deliberate (default OFF); the default bind is localhost-only; the default port is the Prometheus convention (operators expecting `:8000/metrics`).
- **The per-channel send-latency Histogram requires dispatcher integration to populate** — Week 4 ships the SHAPE; the actual dispatcher integration (calling `histogram.record(elapsed, {"channel": ...})` at the two-phase commit point in `skills/send-outreach/scripts/send_queued.py`) is a Pillar G Week 5-6 (tracing) + Pillar H concern. Operators querying the p99 send latency dashboard at Week 4 see an empty histogram until the dispatcher integration lands.
- **The framework-default `View` set may surprise operators with different latency profiles** — the sub-millisecond-to-10s bucket configuration matches the framework's email/LinkedIn send-latency profile; operators with higher-latency channels (e.g., calendar booking via Google Calendar API) may want bucket boundaries up to 30s. Mitigation: the `views=` kwarg accepts operator overrides.
- **The Grafana dashboard YAML format is NOT directly importable into Grafana** — operators need to generate JSON from the YAML OR import via a future provisioning code path. Mitigation: the YAML is operator-readable + version-controllable; future Pillar G weeks MAY ship a generator.

### Neutral

- **The OTel scope version stays at `0.1.0`** per ADR-0052 D283 — the Week 4 instrument additions are content-additive (new instruments under the same scope); operators consuming the OTLP / Prometheus export see the scope version unchanged.
- **The Pillar G Week 5-6 OTel tracing instrumentation will extend the framework-neutrality contract to tracing** — the `init_otel_tracer_provider` (or similar) will mirror the Week 3-4 `init_otel_meter_provider` posture (operator-supplied span exporters; default empty).

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — the Week 4 Prometheus exporter consumes the per-event-class ObservableCounter + the reconcile success ratio Gauge, both of which read from the ledger via `collect_event_class_snapshots`. The Prometheus exposition is a denormalized rebuildable view per `docs/SOURCES-OF-TRUTH.md`.
- **I2 (Atomicity contract).** Compliant — the Prometheus exporter's reading operations do NOT mutate the ledger. The reconcile success ratio callback uses the same stateless walk as the per-event-class ObservableCounter per ADR-0052 D284.
- **I3 (Single source of truth).** Compliant — every Prometheus scrape re-walks the ledger fully via the underlying primitive; no derived state cached at the Prometheus exporter level.
- **I4 (Determinism).** Compliant — the reconcile success ratio callback accepts a `now=` callable per ADR-0034 D156 + ADR-0052 D284; tests pass a captured-lambda for byte-identical reproducibility.
- **I5 (Refuse loud).** Compliant — the per-channel send-latency Histogram's per-channel attribute is operator-supplied at `.record()`; operators passing wrong-type values see OTel SDK validation refuse-loud. The reconcile success ratio Gauge's callback inherits the refuse-loud posture from `collect_event_class_snapshots` per ADR-0051 D279.
- **I6 (No silent state).** Compliant — every state change (the diagnostic emit when the primitive sees uncatalogued classes) is observable as a ledger event; the Week 4 Prometheus exporter does NOT add silent state.
- **I7 (Refuse loud on broken pipelines).** Compliant — the Prometheus exporter wiring's failure modes surface via OTel SDK warnings + Prometheus exposition errors.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — `_BREAKDOWN_DIMS_ALLOWED` refuse-loud is operationally LIVE; the Prometheus exporter wiring does NOT extend the breakdown dimensions.
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D289 — the per-channel send-latency Histogram's per-channel attribute on `.record()` carries the channel uniformly; the Prometheus exposition surfaces `channel="email"` / `channel="li_invite"` / ... labels per the OTel attribute convention.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 4 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — Pillar G Week 4 does not extend any of the five layers; it CONSUMES the per-Pillar-F event classes via the existing per-event-class ObservableCounter from ADR-0052 D284.

## Downstream pillar impact

- **Pillar G Week 5-6** (OTel tracing instrumentation through the pipeline) — extends the framework with `opentelemetry-api`'s `tracer` surface; the per-stage span instrumentation lands at the discovery → enrichment → research → draft → review → send → reply → win/loss pipeline. The Week 4 Prometheus exporter wiring is the metric surface; Week 5-6 lands the trace surface in parallel.
- **Pillar G Week 7-8** (SLO violation detector + `slo_violation_detected` event class emit) — consumes the Week 4 instruments. The per-window SLO check fires when `outreach_factory_reconcile_success_ratio < 0.99` OR `histogram_quantile(0.99, rate(outreach_factory_send_latency_seconds_bucket[5m])) > 5.0` OR bounce > 5% OR `manual_override` count > 0. The Slack webhook wiring follows the operator-deliberate posture per ADR-0050 D276(d).
- **Pillar G Week 9** (cost dashboard) — extends the per-event-class instrument with per-source breakdown (per the `cost_incurred.source` attribute). The Week 4 Grafana dashboard's panel template MAY be extended at Week 9 to include per-source cost panels.
- **Pillar G Week 10-11** (per-Person observability surface) — the per-Person dashboard adapters consume the Week 4 instruments per ADR-0050 D277 — per-register fidelity distribution + per-claim-type hallucination count + per-Person Layer 5 drift rate + per-operator override-rate panels.
- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — the binding scenario per ADR-0050 D275 verifies operators answer the three binding questions via the Week 4 Grafana dashboard + the funnel CLI in ONE invocation.
- **Pillar H (daemon + scale)** — the per-scrape stateless callbacks (Week 3's ObservableCounter + Week 4's ObservableGauge) preserve the multi-machine scale posture; the dispatcher integration for the send-latency Histogram lands at Pillar H's daemon-process two-phase commit instrumentation. R035 mitigation continues (per-daemon-process MeterProvider isolation).
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends the Prometheus exporter with per-tenant namespace + Grafana folder isolation; per-tenant SLO threshold overrides; per-tenant authentication wrapper on the Prometheus HTTP exposition server per R036 mitigation.
- **Pillar J (GDPR purge)** — the per-Person observability surface adapters (Pillar G Week 10-11) consume per-Person event classes; the GDPR-purge transaction extends to per-Person Prometheus metric series alongside the rest of the per-Person event set.

## Migration / rollout

- **Operator-side action required at Week 4 upgrade:** **NONE — content-additive.** The Week 4 commit adds new instruments + a new dashboard but preserves the Week 3 SDK initialization + per-event-class ObservableCounter verbatim. Operators upgrading from Week 3 to Week 4 see the framework's import surface extend (new public functions); existing Week 3 callsites continue to work.
- **Recommended (optional):** operators wanting to consume the Prometheus exposition at Week 4:
  ```python
  from observability import (
      init_otel_meter_provider, init_prometheus_metric_reader,
      register_event_class_observable_counter,
      register_reconcile_success_ratio_gauge,
      start_prometheus_http_server,
  )

  reader = init_prometheus_metric_reader()
  provider = init_otel_meter_provider(metric_readers=[reader])
  register_event_class_observable_counter(led, since_window=timedelta(days=30))
  register_reconcile_success_ratio_gauge(led, since_window=timedelta(days=30))
  start_prometheus_http_server(port=8000)
  # Prometheus scrapes http://127.0.0.1:8000/metrics
  ```
- **Operators with OTLP backends** skip `init_prometheus_metric_reader()` entirely + wire their OTLP reader via `init_otel_meter_provider(metric_readers=[otlp_reader])` per ADR-0052 D286's framework-neutrality contract.
- **Per-tenant migration at Pillar I** — content-additive at Pillar G Week 4; per-tenant audit-tooling at Pillar I extends the Prometheus exporter with per-tenant namespace + Grafana folder isolation.
- **No ledger schema migration** — Week 4 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1 + Week 2 + Week 3).
- **No new event classes** — Week 4 ships ZERO new event classes; the existing `observability_class_uncatalogued` + `slo_violation_detected` set per `OBSERVABILITY_NEW_EVENT_CLASSES` (Week 1) + the per-kind disambiguator on `observability_class_uncatalogued` (Week 2) are preserved verbatim.
- **No new pip dependencies** — Week 4 uses the three OTel packages pinned at Week 3 in `orchestrator/requirements.txt` (`opentelemetry-api>=1.38` + `opentelemetry-sdk>=1.38` + `opentelemetry-exporter-prometheus>=0.59b0`). The Prometheus HTTP server uses `prometheus_client` which is already a transitive dependency of `opentelemetry-exporter-prometheus`.

## Existing-operator seed

Operator action required at Week 4: **NONE — content-additive.**

Recommended (optional): operators wanting to consume the Prometheus exposition at Week 4 invoke the canonical wiring per the Migration section above. Operators wiring the Grafana dashboard at `infra/grafana/dashboards/overview.yml` see the four panels rendering the three binding exit-criterion questions per ADR-0050 D275.

## References

- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope + per-event-class ObservableCounter + cumulative-counter semantics + framework-neutrality contract + default Resource-attribute closed-set). D282-D287.
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. The Week 1 framework decision pinned OpenTelemetry SDK + Prometheus exporter + Grafana-as-code; Week 4 lands the Prometheus exporter wiring + the first Grafana dashboard per the trajectory at D273.
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. The Pillar G Week 4 commit preserves the Pillar F primitive surfaces + Layer 5 backstop verbatim.
- **ADR-0038** (Pillar F foundation). D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields).
- **ADR-0037** (Pillar E Week 12 close + Stable flip). D172 (Pillar E Stable flip discipline; ~7500 LOC split threshold flag for the cross-pillar coherence test vehicle).
- **ADR-0034** (Pillar E Week 1 — discovery dedup primitive + deterministic-clock contract). D156 (deterministic-clock kwarg discipline carried forward through Pillar E + F + G).
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state).
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant).
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers).
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2 §18 + Week 3 §19 + Week 4 §20 extension per this commit).
- `.planning/HANDOFF-pillar-g-week-3.md` — Pillar G Week 3 close summary + Pillar G Week 4 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 4 close summary.
- `docs/RISK-REGISTER.md` R031 + R032 + R033 (Pillar G Week 1 risks); R034 (Pillar G Week 2 — diagnostic emit at every primitive call inflates ledger when catalog drift persists); R035 (Pillar G Week 3 — OTel SDK's set-once `set_meter_provider` enforcement); R036 (NEW Week 4 — Prometheus HTTP exposition server exposes per-process metrics over the network; severity 1 / likelihood 2; default 127.0.0.1 bind mitigation).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 4 ADR-0053 references.
- `orchestrator/observability.py` — extended Week 4 with `init_prometheus_metric_reader` + `get_send_latency_histogram` + `register_reconcile_success_ratio_gauge` + `start_prometheus_http_server` + `render_prometheus_exposition` + `default_views` + the `views=` kwarg on `init_otel_meter_provider` + 5 new module-level constants.
- `tests/test_observability.py` (extended Week 4) — 52 NEW tests covering the cell-level matrix per the per-week-reviewer discipline NINE consecutive weeks (Pillar F W6-W12 + Pillar G W2 + W3).
- `infra/grafana/dashboards/overview.yml` (NEW Week 4) — first Grafana-as-code dashboard with four panels rendering the three binding exit-criterion questions per ADR-0050 D275 + the reconcile success ratio SLO panel.
