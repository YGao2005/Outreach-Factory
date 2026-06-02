# ADR-0054: Pillar G Week 5 — OTel tracing initialization, canonical `Tracer` scope, per-stage `traced_stage` context manager, `_PIPELINE_STAGES` closed-set, privacy invariant on span attributes via `_SPAN_ATTRIBUTES_ALLOWED`, framework-neutrality contract for tracing, zero call-site wiring at Week 5

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 5 OTel tracing initialization + per-stage span instrumentation pattern)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape + the OTel SDK + Prometheus exporter + Grafana-as-code framework decision per D273. ADR-0051 (Pillar G Week 2, D278-D281) shipped the `collect_event_class_snapshots` body + the `observability_class_uncatalogued` diagnostic emit. ADR-0052 (Pillar G Week 3, D282-D287) shipped the OTel SDK initialization (`init_otel_meter_provider`) + the single canonical Meter scope `orchestrator.observability` + the per-event-class `outreach_factory_events_total` ObservableCounter + the cumulative-counter semantics + the framework-neutrality contract + the default Resource-attribute closed-set. ADR-0053 (Pillar G Week 4, D288-D293) shipped the Prometheus exporter wiring + the per-channel send-latency Histogram + the reconcile success ratio ObservableGauge + the Prometheus HTTP exposition server + the framework-default View set + the first Grafana-as-code dashboard. The four prior weeks landed the **metric instrumentation surface** end-to-end (Week 3-4: instruments + exporter wiring + dashboard). The per-week trajectory at ADR-0050 D273's table names **Weeks 5-6 as OTel tracing instrumentation through the discovery → enrichment → research → draft → review → send → reply → win/loss pipeline**.

Pillar G Week 5 ships the **OTel tracing initialization** + the **canonical `Tracer` scope** + the **per-stage span instrumentation PATTERN** (`traced_stage` context manager + `_PIPELINE_STAGES` closed-set + `_SPAN_ATTRIBUTES_ALLOWED` closed-set + privacy invariant on span attributes + framework-neutrality contract for tracing). The six concerns this ADR resolves:

1. **OTel tracing initialization shape.** The framework already imports `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-prometheus` per Week 3's `orchestrator/requirements.txt` extension. The trace SDK lives at `opentelemetry.sdk.trace` (sibling of `opentelemetry.sdk.metrics`); no new pip dependency at Week 5. The runtime initialization must (a) configure a `TracerProvider` with a service-named `Resource` (the SAME default Resource as Week 3's MeterProvider for per-pillar symmetry); (b) be idempotent under OTel's set-once `set_tracer_provider` enforcement; (c) accept operator-supplied `span_processors` for cross-vendor portability per D273's framework-neutrality contract.

2. **Canonical `Tracer` scope.** Per the per-pillar-symmetry pattern from RETRO-pillar-f.md item 5 + ADR-0052 D283: Pillar G's `Tracer` scope MUST share the canonical `orchestrator.observability` + version `0.1.0` with the existing Meter scope. Operators consuming the OTLP / Jaeger / Tempo / Datadog tracing UI see ONE namespace across both metric instruments + trace spans. The OTel SDK tracks Meters + Tracers in SEPARATE per-scope registries internally, but the scope name + version IS the load-bearing label operators see in the OTLP export.

3. **Per-stage span instrumentation pattern.** The pipeline has eight load-bearing stages per PILLAR-PLAN §2 Pillar G's binding text: discovery → enrichment → research → draft → review → send → reply → win/loss. The framework MUST decide whether to (a) provide a canonical context-manager helper (operators wire `with traced_stage("send", "email", attributes={"channel": "email"}): ...` at each call site); (b) provide a decorator (`@traced_stage("send", "email")` wrapping functions); (c) leave operators to call `tracer.start_as_current_span(...)` directly. The context-manager choice preserves the cell-level matrix coverage discipline (NOW TEN consecutive weeks at Week 5) — the helper validates stage + attribute closed-sets at the per-call site; (b) decorator-only would force callers into function-level granularity which doesn't fit the multi-phase commit + multi-step research patterns the existing Pillar A-F surfaces use; (c) raw OTel API loses the closed-set discipline.

4. **Privacy invariant on span attributes.** The privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) extends to per-span attributes — operators wiring spans at the per-pillar call sites MUST NOT pass `source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text` as span attribute values. The framework MUST provide a closed-set regression-barrier (`_SPAN_ATTRIBUTES_ALLOWED`) mirroring `_BREAKDOWN_DIMS_ALLOWED` for metrics. The helper refuses-loud at attribute validation time.

5. **Framework-neutrality contract for tracing.** Per ADR-0052 D286 + ADR-0053 D288 carried forward — operators with different observability backends (Honeycomb / Datadog / Grafana Cloud / Jaeger / Tempo / Zipkin / self-hosted OTLP collector) MUST be able to wire their own `SpanProcessor` (with the operator's chosen `SpanExporter`) without code changes to the framework. The `init_otel_tracer_provider(span_processors=...)` kwarg is the operator escape hatch. Week 5 ships with EMPTY processors by default — the TracerProvider accepts the no-processor configuration; spans register, attributes register, but no export fires until a processor is added.

6. **ZERO call-site wiring at Week 5 vs at Week 6.** The per-week trajectory at ADR-0050 D273's table groups Weeks 5-6 together for "OTel tracing instrumentation through the pipeline." The natural split is **Week 5 = infrastructure + PATTERN** (init + tracer + helper + closed-sets + privacy invariant + framework-neutrality contract + tests + ADR + audit + handoff); **Week 6 = APPLICATION** (wire `traced_stage` at the per-pillar call sites across discovery → enrichment → research → draft → review → send → reply → win/loss + complete the Week 4 dispatcher integration carry-forward for the send-latency Histogram). The split preserves the per-week scope discipline + matches the Week 3-4 pattern (Week 3 = SDK init + ObservableCounter; Week 4 = exporter + Histogram + Gauge + dashboard).

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED from ADR-0050 + ADR-0052 + ADR-0053; the closed-set `EVENT_CLASS_CATALOG | OBSERVABILITY_NEW_EVENT_CLASSES` IS the mitigation. The Week 5 `_PIPELINE_STAGES` closed-set extends the R031-shape mitigation pattern to the per-stage span surface — a future contributor adding a span for an unrecognized stage triggers a per-call refuse-loud at `traced_stage`.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED from ADR-0050 + ADR-0052 + ADR-0053; the stateless callback contract per ADR-0052 D284 preserves the mitigation. The Week 5 tracing surface is per-span (operators emit at the per-call grain); the OTel TracerProvider's span aggregation is per-process — Pillar H's multi-process daemon may need per-daemon-process TracerProvider isolation (mirroring R035's per-MeterProvider concern).

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED from ADR-0051; the per-kind-per-call rate-limit holds. Week 5 tracing does NOT touch the ledger diagnostic emit surface — spans go via OTel SDK, NOT via `Ledger.append`. The Pillar G ledger surface stays at the existing `observability_class_uncatalogued` + `slo_violation_detected` enumeration.

- **R035 (OTel SDK's set-once `set_meter_provider` enforcement creates per-process global state)** — UNCHANGED + EXTENDED at Week 5; the `set_global=False` kwarg on `init_otel_tracer_provider` mirrors the Week 3 `init_otel_meter_provider` mitigation. The OTel `set_tracer_provider` has a subtle nuance — the default `NoOpTracerProvider` IS replaceable by a real provider; subsequent sets after a real provider is in place log a warning + do NOT take effect. Tests pass `set_global=False`; production callers initialize ONCE at startup with `set_global=True`.

- **R036 (Prometheus HTTP exposition server exposes per-process metrics over the network)** — UNCHANGED from ADR-0053; the `127.0.0.1` security-by-default bind + operator-deliberate posture mitigation continues. Week 5 tracing does NOT add a new HTTP exposition surface — spans flow through operator-wired `SpanProcessor` + `SpanExporter` to operator-chosen backends; there is no framework-provided HTTP exposition for traces.

ZERO new R-risks surfaced at Week 5. The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + this ADR's D298 preserves the operator-choice posture; the closed-set discipline per `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` preserves the R031-shape regression-barrier; the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0051 D278 + ADR-0052 D284 + ADR-0053 D292 carries through to per-span attributes via D297.

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12. The Pillar G Week 1-4 surfaces preserve verbatim.

## Decision

### D294. OTel tracing initialization — `init_otel_tracer_provider` at `orchestrator/observability.py`

`orchestrator/observability.py::init_otel_tracer_provider(*, resource=None, span_processors=(), set_global=True)` is the canonical OTel tracing initialization entry point. The signature + contract:

```python
def init_otel_tracer_provider(
    *,
    resource: Resource | None = None,
    span_processors: Iterable[SpanProcessor] = (),
    set_global: bool = True,
) -> TracerProvider:
    """Initialize an OTel TracerProvider per ADR-0054 D294."""
    if resource is None:
        resource = Resource.create({
            SERVICE_NAME: _SERVICE_NAME,
            SERVICE_VERSION: _SERVICE_VERSION,
        })
    provider = TracerProvider(resource=resource)
    for sp in span_processors:
        provider.add_span_processor(sp)
    if set_global:
        _otel_trace.set_tracer_provider(provider)
    return provider
```

Module placement: **co-located at `orchestrator/observability.py`** per ADR-0052 D282 + ADR-0053 D288's per-pillar single-file mental model. The Week 5 surface adds ~360 LOC; total module size ~1760 LOC, well below the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266 + ADR-0050 D275 + ADR-0052 D282 + ADR-0053 D288.

**Idempotency caveat per OTel spec.** The OTel Python SDK enforces "set-once" on `set_tracer_provider` (with the subtle nuance — the default `NoOpTracerProvider` IS replaceable by a real provider; subsequent sets after a real provider is in place log a warning + do NOT take effect). The `set_global=False` kwarg gives tests an escape hatch; production callers initialize ONCE at startup with `set_global=True`. Mirrors the Week 3 `init_otel_meter_provider` posture per ADR-0052 D282 + R035 mitigation.

**Default `Resource` per ADR-0052 D287 carried forward.** The default Resource carries `service.name` + `service.version` from `_SERVICE_NAME` + `_SERVICE_VERSION` (the SAME keys as `init_otel_meter_provider`); the OTel SDK auto-injects `telemetry.sdk.*` attributes. Operators extending Resource at Pillar I OSS bring-up preserve the framework's `service.*` keys + MAY add per-tenant keys (e.g., `outreach_factory.tenant_id`).

### D295. Single canonical OTel `Tracer` scope — `orchestrator.observability` + version `0.1.0`

`orchestrator/observability.py::get_tracer(tracer_provider=None)` returns the canonical Pillar G `Tracer`. The module-level constants:

```python
_TRACER_NAME: str = "orchestrator.observability"
_TRACER_VERSION: str = "0.1.0"
```

`get_tracer(tracer_provider=None)` consults the global provider (set by `init_otel_tracer_provider(set_global=True)`) by default; tests pass `tracer_provider=` to source from an explicit local provider.

**Per-pillar-symmetry contract per RETRO-pillar-f.md item 5 + ADR-0052 D283 EXTENDED to tracing.** The Tracer scope name + version MATCH the Meter scope name + version. Operators consuming the OTLP export see ONE canonical `orchestrator.observability` scope across BOTH metric instruments (`outreach_factory_events_total` + `outreach_factory_send_latency_seconds` + `outreach_factory_reconcile_success_ratio`) AND trace spans (`outreach_factory.send.email` + `outreach_factory.discovery.find_leads` + ...). The OTel SDK tracks Meters + Tracers in SEPARATE per-scope registries internally — the same scope NAME + VERSION used for both does NOT confuse the SDK.

A regression-barrier test `TestPillarGScopeParityWithMeter::test_tracer_name_matches_meter_name` pins this contract.

### D296. Per-stage span instrumentation pattern — `traced_stage` context manager + `_PIPELINE_STAGES` closed-set

`orchestrator/observability.py::traced_stage(stage, operation, *, attributes=None, tracer=None)` is the canonical per-stage span helper. The signature + contract:

```python
@contextmanager
def traced_stage(
    stage: str,
    operation: str,
    *,
    attributes: dict[str, str] | None = None,
    tracer: Tracer | None = None,
) -> Iterator[Span]:
    """Context manager for per-stage span emit per ADR-0054 D296."""
    if stage not in _PIPELINE_STAGES:
        raise ValueError(...)
    if not operation:
        raise ValueError(...)
    attrs = dict(attributes) if attributes else {}
    for key in attrs:
        if key not in _SPAN_ATTRIBUTES_ALLOWED:
            raise ValueError(...)
    attrs["stage"] = stage
    attrs["operation"] = operation
    if tracer is None:
        tracer = get_tracer()
    span_name = f"{_SPAN_NAME_PREFIX}.{stage}.{operation}"
    with tracer.start_as_current_span(
        span_name, attributes=attrs,
    ) as span:
        yield span
```

**The closed-set `_PIPELINE_STAGES`:**

```python
_PIPELINE_STAGES: frozenset[str] = frozenset({
    "discovery",
    "enrichment",
    "research",
    "draft",
    "review",
    "send",
    "reply",
    "win_loss",
})
```

Each stage maps to an operator-meaningful slice of the pipeline (per the per-stage description at `orchestrator/observability.py`'s module docstring). The closed-set IS the regression-barrier per the R031-shape mitigation pattern — a future contributor adding a span for an unrecognized stage triggers a per-call `ValueError` (operator-visible signal that the stage enumeration drifted from PILLAR-PLAN §2 Pillar G's binding text + ADR-0050 D273's per-week trajectory).

**Span name convention per the framework prefix.** Span names follow `outreach_factory.<stage>.<operation>` (e.g., `outreach_factory.send.email`, `outreach_factory.discovery.find_leads`). The `outreach_factory` prefix matches the per-framework namespace per ADR-0052 D284's `outreach_factory_` metric instrument prefix (period-separated for spans vs underscore-separated for metrics — the OTel convention).

**Auto-set attributes per the per-stage symmetry.** The helper auto-sets `stage` + `operation` attributes on every span. Operators MAY pass additional attributes via the `attributes=` kwarg; the auto-set values are the canonical source (operators overriding via `attributes={"stage": "other"}` see their value preserved at attribute validation time + the helper's auto-set overrides at insertion time).

**No-op posture when no provider initialized.** The OTel SDK's default `NoOpTracerProvider` returns a `NoOpTracer` whose `start_as_current_span` returns a no-op span. The helper is SAFE to call without prior `init_otel_tracer_provider` — operators wiring spans at the per-pillar call sites at Week 6 do NOT need to gate the helper invocations on initialization (mirroring OTel SDK's safe-default posture). The closed-set validation runs BEFORE the span is created, so refuse-loud STILL fires even at no-op posture.

### D297. Privacy invariant on span attributes — `_SPAN_ATTRIBUTES_ALLOWED` closed-set

`orchestrator/observability.py::_SPAN_ATTRIBUTES_ALLOWED` is the closed-set frozenset of allowed span attribute keys:

```python
_SPAN_ATTRIBUTES_ALLOWED: frozenset[str] = frozenset({
    # Mirrors _BREAKDOWN_DIMS_ALLOWED (the metric breakdown surface).
    "channel",
    "register",
    "source_skill",
    "category",
    "classification_method",
    "outcome",
    "reason",
    "result_state",
    "event_class",
    # Per-span-specific keys.
    "person_id",
    "stage",
    "operation",
})
```

**Twelve allowed keys** = nine breakdown dims from `_BREAKDOWN_DIMS_ALLOWED` (the metric breakdown surface — preserves per-pillar-symmetry-with-shared-aggregation) + three per-span-specific keys (`person_id` for the per-Person observability surface per ADR-0050 D277; `stage` + `operation` auto-set by `traced_stage`).

**DISALLOWED keys per the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0051 D278 + ADR-0052 D284 + ADR-0053 D292:**

- `source_list` — operator-private (operator's curated discovery list names).
- `draft_body` — operator-confidential (the prose content of the draft).
- `dossier_body` — operator-confidential (the research dossier's prose content).
- `exemplar_body` — operator-confidential (the voice-corpus exemplar's prose content).
- `claim_text` — operator-confidential (the per-claim trace text from `hallucination_detected` events).

`traced_stage` refuses-loud at attribute keys outside the closed-set. The regression-barrier test `TestSpanAttributesClosedSetPrivacy::test_disallowed_key_refuses_loud` is parametrized over the five disallowed keys.

**Operator-deliberate bypass.** Operators using the raw OTel `Tracer.start_as_current_span` API directly + `span.set_attribute("draft_body", "...")` bypass the helper's refuse-loud. The helper IS the canonical surface; the per-week-reviewer's behavioral-passthrough-not-signature-only discipline catches direct-API bypasses at audit time. Pillar I per-tenant audit-tooling MAY surface a per-tenant span-attribute filter at OSS bring-up; Pillar G Week 5 ships the helper-level mitigation.

### D298. Framework-neutrality contract for tracing — operator-supplied `SpanProcessor` via the `span_processors` kwarg

Per ADR-0052 D286 + ADR-0053 D288 carried forward to tracing: the framework MUST be neutral to the operator's observability backend. The `init_otel_tracer_provider(span_processors=...)` kwarg is the operator escape hatch:

| Operator backend | `span_processors` value | Wired at |
|---|---|---|
| OTLP collector (Honeycomb / Datadog / Grafana Cloud / self-hosted) | `[BatchSpanProcessor(OTLPSpanExporter(endpoint=...))]` | Operator-side; framework does NOT ship the OTLP exporter import (per ADR-0050 §Migration/rollout — only the three core OTel packages) |
| Jaeger | `[BatchSpanProcessor(JaegerExporter(...))]` | Operator-side; jaeger-client + opentelemetry-exporter-jaeger pip-installed by operator |
| Zipkin | `[BatchSpanProcessor(ZipkinExporter(...))]` | Operator-side |
| Console (debug) | `[SimpleSpanProcessor(ConsoleSpanExporter())]` | Operator-side; `ConsoleSpanExporter` is in `opentelemetry-sdk` so no extra pip dep |
| In-memory (tests) | `[SimpleSpanProcessor(InMemorySpanExporter())]` | Test fixtures at `tests/test_observability.py` |
| No exporter (Week 5 default) | `[]` (empty) | Week 5 ships the default; Week 6 lands the per-call-site wiring (operators with backends-wired-at-startup see spans flow through; operators with no backend see spans silently dropped at the TracerProvider) |

**Week 5 default = empty `span_processors`.** The TracerProvider accepts no processors; spans register, attributes register, but no export fires until a processor is added. This preserves the framework-neutrality contract — operators with vendor-specific backends wire their processor BEFORE Pillar G Week 6's per-call-site wiring lands.

**No new pip dependencies at Week 5.** The OTel SDK's tracing surface lives at `opentelemetry.sdk.trace` (sibling of `opentelemetry.sdk.metrics`); both are in `opentelemetry-sdk>=1.38` pinned at Week 3 in `orchestrator/requirements.txt`. Week 5 imports `TracerProvider`, `SpanProcessor`, `Span`, `Tracer` from the existing dependency.

### D299. ZERO call-site wiring at Week 5 — defer to Week 6 per the per-week-split trajectory

The per-week trajectory at ADR-0050 D273's table groups Weeks 5-6 together for "OTel tracing instrumentation through the pipeline." Week 5 ships the **infrastructure + PATTERN**; Week 6 wires the per-stage spans at the pipeline call sites + completes the Week 4 carry-forward for the send-latency Histogram dispatcher integration.

**Week 5 scope (this commit):**

- OTel tracing initialization (`init_otel_tracer_provider`)
- Canonical Tracer accessor (`get_tracer`)
- Per-stage span helper (`traced_stage` context manager)
- Closed-sets (`_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED`)
- Privacy invariant on span attributes (refuse-loud)
- Framework-neutrality contract (empty `span_processors` default)
- Tests (~66 new tests covering cell-level matrix)
- ADR-0054 (this document)
- Cross-pillar audit §21 extension
- Per-week handoff doc

**Week 6 scope (next commit):**

- Wire `traced_stage("discovery", "find_leads", ...)` at the Pillar E discovery primitives' call sites
- Wire `traced_stage("enrichment", "stamp_lineage", ...)` at the Pillar E enrichment call sites
- Wire `traced_stage("research", "voice_corpus_retrieve", ...)` at the Pillar F voice-corpus retrieval
- Wire `traced_stage("draft", "score_draft", ...)` at the Pillar F draft-quality scoring
- Wire `traced_stage("review", "draft_quality_score", ...)` at the Pillar F per-Layer call sites
- Wire `traced_stage("send", "email", ...)` at the Pillar C dispatcher's two-phase commit + complete the Week 4 carry-forward for `histogram.record(elapsed, {"channel": ...})`
- Wire `traced_stage("reply", "classify", ...)` at the Pillar D reply classifier
- Wire `traced_stage("win_loss", "derive_outcome", ...)` at the Pillar D conversation outcomes

The split preserves the per-week scope discipline + matches the Week 3-4 pattern (Week 3 = SDK init + ObservableCounter; Week 4 = exporter + Histogram + Gauge + dashboard). Operators querying tracing at the end of Week 5 see EMPTY span exports (no call sites wired); operators at end of Week 6 see spans flowing through the eight pipeline stages.

## Alternatives considered

### D294 alternatives (OTel tracing initialization shape)

1. **Combine `init_otel_tracer_provider` + `init_otel_meter_provider` into a single `init_otel_observability()` function.** Rejected — the OTel SDK has separate `MeterProvider` + `TracerProvider` classes with distinct configuration surfaces (e.g., `views=` is metric-specific; `span_processors=` is trace-specific). A combined function would force operators wanting ONLY traces (no metrics) into a kwarg-explosion shape; the two-function split mirrors the OTel SDK's natural division.

2. **Auto-initialize the TracerProvider at module import via a side effect.** Rejected — auto-initialization-on-import creates side effects at module load time (same anti-pattern as ADR-0052 D282's rejected alternative). Operators running tests or one-off scripts get unexpected OTel scrapes; the OTel set-once semantics enforce ONE init per process which conflicts with multi-test isolation. Explicit `init_otel_tracer_provider()` calls preserve operator control.

3. **Defer the TracerProvider init to Pillar G Week 6 (ship only the helper at Week 5).** Rejected — the helper requires a Tracer to function; the Tracer requires a TracerProvider (or the OTel default NoOpTracerProvider). Without `init_otel_tracer_provider` at Week 5, tests of the helper would have to use the global NoOpTracerProvider (which silently drops spans + can't be captured by tests). The Week 5 init function is REQUIRED for tests of the helper.

4. **Sub-module at `orchestrator/observability/_tracing.py` (per ADR-0052 D282's "sub-module if surface grows" hint).** Rejected at Week 5 — the Week 5 surface adds ~360 LOC; co-located at `orchestrator/observability.py` keeps the file at ~1760 LOC, well below the ~7500 LOC split threshold. Sub-module split would create the "look in two places" mental model. Future Pillar G weeks MAY split if the tracing surface grows past the threshold (e.g., Week 6's per-call-site wiring + Week 7-8's SLO tracing instrumentation + Week 10-11's per-Person tracing surfaces together push the file past the threshold).

### D295 alternatives (Tracer scope name + version)

1. **Distinct Tracer scope `orchestrator.observability.trace` (NOT shared with Meter).** Rejected — splits the canonical scope; operators consuming the OTLP export would see TWO scopes (`orchestrator.observability` for metrics, `orchestrator.observability.trace` for traces) requiring per-scope joining at query time. The per-pillar-symmetry contract per RETRO-pillar-f.md item 5 + ADR-0052 D283 picks ONE scope across both instrument types.

2. **Bump the Tracer scope version to `"0.2.0"` to distinguish from Meter.** Rejected — version bumps are reserved for non-backwards-compat changes per ADR-0052 D283's "bump at non-backwards-compat extension" discipline. Week 5 adds the trace surface alongside the metric surface; this is content-additive, not breaking. Both surfaces share `"0.1.0"`.

3. **Per-stage Tracer scopes (`orchestrator.observability.send`, `orchestrator.observability.draft`, ...).** Rejected — N-times-ifies the scope set; operators consuming the OTLP export see eight per-stage scopes. Per ADR-0052 D283's per-pillar-symmetry contract: ONE scope per pillar. The per-stage discrimination happens via span name (`outreach_factory.<stage>.<operation>`) + attributes (`stage="send"`), NOT via per-scope sub-namespaces.

### D296 alternatives (per-stage span instrumentation pattern)

1. **Decorator-only (`@traced_stage("send", "email") def send_email(...): ...`).** Rejected — decorators force function-level granularity which doesn't fit the multi-phase commit patterns (e.g., a single Pillar C two-phase send has `send_intent` write → external API call → `send_confirmed` write; operators want SEPARATE spans for the API call + the ledger writes within the function). Context-manager fits inline span emit at fine-grained call sites.

2. **Raw `tracer.start_as_current_span(name, attributes=)` (no helper).** Rejected — loses the closed-set discipline (operators can pass any attribute key + any span name); a Pillar G contributor adding a new stage would have to coordinate the new span name across N+ call sites manually + risks privacy invariant violations. The helper IS the canonical surface that enforces both closed-sets.

3. **Open-set stage parameter (`stage: str` with no `_PIPELINE_STAGES` closed-set).** Rejected — loses the R031-shape regression-barrier. A future contributor adding `traced_stage("inbox_inspection", "scan")` (a non-existent stage in PILLAR-PLAN §2 Pillar G's binding text) would silently broaden the per-stage span surface. The closed-set IS the operator-visible refuse-loud signal that the stage enumeration drifted.

4. **Auto-set fewer attributes (only `stage`, NOT `operation`).** Rejected — `operation` is the per-stage sub-discriminator (e.g., the `send` stage has `email` + `li_invite` + `li_dm` + `tw_dm` + `calendar_booking` operations). Operators querying tracing UIs filter by `operation="email"` to isolate the per-channel send latency; without `operation` on the span attribute set, operators would have to parse the span name suffix manually.

### D297 alternatives (privacy invariant on span attributes)

1. **No closed-set on span attributes (let operators pass anything).** Rejected — privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) explicitly forbids `source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text` in observability aggregations. The same invariant carries through to per-span attributes — a span attribute leaking a draft body would expose operator-confidential content to the tracing UI consumer.

2. **Smaller closed-set (only the breakdown dims, no per-span keys).** Rejected — `person_id` is required for the per-Person observability surface per ADR-0050 D277 + the Week 10-11 per-Person dashboard adapters; `stage` + `operation` are auto-set by the helper itself + form the per-stage span discrimination. The three per-span-specific keys are LOAD-BEARING for the per-stage observability surface.

3. **Larger closed-set (include `email`, `domain`, `name`, ...).** Rejected — `email` + `domain` + `name` are operator-confidential PII; tracing UIs render attributes verbatim + would expose PII to anyone with tracing UI access. Pillar J GDPR-purge transaction stays at the per-Person event surface; per-span PII would create a NEW purge surface. The closed-set deliberately excludes PII.

### D298 alternatives (framework-neutrality contract for tracing)

1. **Hardcode the OTLP exporter as the default at Week 5.** Rejected — violates the framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288. Operators with Jaeger / Zipkin / vendor-specific exporters would need to override the default; the explicit `span_processors=` kwarg preserves operator choice.

2. **Initialize with a default `SimpleSpanProcessor(ConsoleSpanExporter())` for debug.** Rejected at Week 5 — the framework default is OPERATOR-CONTROLLED (empty `span_processors`); a default `ConsoleSpanExporter` would flood stdout in test environments + production operators rarely want console output. Operators wanting console debug pass `span_processors=[SimpleSpanProcessor(ConsoleSpanExporter())]` deliberately.

3. **Defer tracing initialization to a separate `init_otel_tracing_pipeline()` function with auto-detection of operator backend via env var (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_EXPORTER`, ...).** Accepted as a future extension — the OTel SDK auto-detects these env vars by default; the framework default Resource merges with auto-detected attributes per OTel SDK behavior. Pillar G Week 5 does NOT explicitly opt out; operators setting `OTEL_EXPORTER_OTLP_ENDPOINT` see their exporter wired (via the SDK's auto-detection) WITHOUT framework-side config.

### D299 alternatives (Week 5 scope vs Week 6 scope)

1. **Wire ALL eight pipeline stages' call sites at Week 5.** Rejected — the per-week trajectory at ADR-0050 D273 groups Weeks 5-6 together; the natural split is Week 5 = infrastructure + PATTERN, Week 6 = APPLICATION. Wiring all eight stages in one week would compress two weeks' scope + lose the per-week scope discipline + risk breaking the Pillar D + E + F binding exit-criterion tests (each call site needs careful integration to avoid breaking existing tests). The split matches Week 3-4 (Week 3 = SDK + ObservableCounter; Week 4 = exporter + Histogram + Gauge + dashboard).

2. **Wire ONE call site at Week 5 (the dispatcher + Week 4 carry-forward).** Rejected at Week 5 — the dispatcher integration carries the `histogram.record(elapsed, {"channel": ...})` per the Week 4 carry-forward + the per-stage send span instrumentation. Wiring just the dispatcher leaves the other seven stages for Week 6 which is the planned scope; consolidating to Week 6 keeps the call-site work bundled. Operators wanting span emit BEFORE Week 6 use `traced_stage` directly at their own call sites; the helper is operator-visible at Week 5.

3. **Defer the helper itself to Week 6.** Rejected — the helper's design is INDEPENDENT of the call-site wiring. Testing the helper requires the TracerProvider + Tracer surface (D294 + D295); the closed-set validation requires the closed-sets (D296 + D297); the framework-neutrality contract requires the operator-controlled `span_processors=` kwarg (D298). Bundling helper + infrastructure at Week 5 preserves the per-week scope discipline (Week 5 = SHAPE ships; Week 6 = APPLICATION wires).

## Consequences

### Positive

- **The framework is now OTel-tracing-instrumented at Week 5** — operators consuming the OTLP / Jaeger / Tempo / Datadog tracing UI see the per-stage span surface via the canonical `outreach_factory.<stage>.<operation>` span names. The Week 6 commit wires the per-call-site invocations.
- **The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 EXTENDS to tracing at Week 5** — operators with different observability backends (OTLP collectors, Jaeger, Zipkin, ...) wire their `SpanProcessor` via `init_otel_tracer_provider(span_processors=...)` without code changes to the framework.
- **The per-pillar-symmetry contract holds at the canonical scope `orchestrator.observability` + version `0.1.0`** — every Pillar G instrument (metric + trace) shares the scope; operators see one namespace.
- **The closed-set discipline per `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` is the regression-barrier per the R031-shape mitigation pattern** extended to the per-stage span surface — a future contributor adding a span for an unrecognized stage OR a privacy-relevant attribute triggers per-call refuse-loud.
- **The privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) flows through to per-span attributes** — `traced_stage` refuses-loud on `source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text`.
- **The `traced_stage` no-op posture preserves operator ergonomics** — operators wiring spans at the per-pillar call sites at Week 6 do NOT need to gate the helper invocations on initialization; the OTel SDK's NoOpTracerProvider silently accepts span emit.
- **The behavioral-passthrough-not-signature-only discipline holds at SEVEN consecutive weeks (Pillar F W8-W11 + Pillar G W3 + W4 + W5)** — Week 5 tests capture spans via `InMemorySpanExporter` + verify span name + attributes + parent-child relationships (NOT signature-only).
- **The cell-level matrix coverage discipline holds at TEN consecutive weeks (Pillar F W6-W12 + Pillar G W2 + W3 + W4 + W5)** — Week 5 ships 66 new tests covering per-constant + per-init-cell + per-helper-cell + per-attribute-cell + per-stage-cell + per-privacy-cell coverage.
- **ZERO new R-risks** at Week 5 — the existing R031/R033/R034/R035/R036 mitigations carry through verbatim.

### Negative

- **The TracerProvider creates per-process global state (R035 EXTENDED)** — operators running multiple framework invocations in the same Python process see the FIRST init's provider persist; subsequent inits silently no-op. Mitigation: `set_global=False` kwarg for tests; production callers initialize ONCE.
- **The per-stage call-site wiring at Week 6 is deferred** — operators querying tracing at the end of Week 5 see EMPTY span exports (no call sites wired). Week 6 lands the per-stage wiring.
- **The helper's closed-set check at attribute time does NOT catch direct-OTel-API bypasses** — operators using `tracer.start_as_current_span("...").set_attribute("draft_body", ...)` directly bypass the privacy invariant. Mitigation: the helper IS the canonical surface; the per-week-reviewer's behavioral-passthrough-not-signature-only discipline catches direct-API bypasses at audit time; Pillar I per-tenant audit-tooling MAY add per-tenant span-attribute filters at OSS bring-up.
- **The test surface grows by ~960 LOC** — `tests/test_observability.py` ships 66 NEW tests (~960 LOC) covering the cell-level matrix; file size grows from ~2620 LOC to ~3580 LOC, still below the ~7500 LOC split threshold.

### Neutral

- **The OTel scope version stays at `0.1.0`** per ADR-0052 D283 — the Week 5 trace surface is content-additive (new surface under the same scope); operators consuming the OTLP export see the scope version unchanged.
- **No new pip dependencies at Week 5** — the OTel SDK's tracing surface lives at `opentelemetry.sdk.trace` (sibling of `opentelemetry.sdk.metrics`); both are in `opentelemetry-sdk>=1.38` pinned at Week 3.
- **No ledger schema migration** — Week 5 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1 + 2 + 3 + 4).
- **No new event classes** — Week 5 ships ZERO new event classes; spans go via OTel SDK, NOT via `Ledger.append`. The existing `observability_class_uncatalogued` + `slo_violation_detected` set per `OBSERVABILITY_NEW_EVENT_CLASSES` (Week 1) + the per-kind disambiguator on `observability_class_uncatalogued` (Week 2) are preserved verbatim.
- **No new operator-facing CLI surfaces** — Week 5 does NOT extend `orchestrator/funnel.py` or any other CLI; the tracing surface flows through the OTel SDK to operator-chosen backends.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — Week 5 tracing does NOT touch the ledger surface; spans go via OTel SDK. The Prometheus exposition is a denormalized rebuildable view per `docs/SOURCES-OF-TRUTH.md`; the OTLP trace export at Week 6 is similarly denormalized.
- **I2 (Atomicity contract).** Compliant — the Week 5 tracing surface is read-only at the helper level; `traced_stage` does NOT mutate the ledger.
- **I3 (Single source of truth).** Compliant — every span emit re-derives from the per-call context; no state cached at the helper level.
- **I4 (Determinism).** Compliant — the helper does NOT depend on wall-clock; span timestamps are managed by the OTel SDK. The deterministic-clock contract per ADR-0034 D156 carries through to the underlying TracerProvider's span timestamps via OTel's per-span start/end clock kwargs (operators MAY pass deterministic clocks for byte-identical span timestamps in tests).
- **I5 (Refuse loud).** Compliant — `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` refuse-loud at the helper's attribute validation time.
- **I6 (No silent state).** Compliant — every state change (span emit) is observable as a span on the operator's tracing backend; the helper does NOT cache state across calls.
- **I7 (Refuse loud on broken pipelines).** Compliant per the same refuse-loud posture at the helper.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — `_SPAN_ATTRIBUTES_ALLOWED` refuse-loud is operationally LIVE; the helper's attribute validation runs at the per-call site.
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D296 — `traced_stage` accepts the `channel` attribute (it's in `_SPAN_ATTRIBUTES_ALLOWED`); operators wire `attributes={"channel": "email"}` at the per-stage call sites.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 5 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — Pillar G Week 5 does not extend any of the five layers; Week 6 wires `traced_stage("review", ...)` at the per-Layer call sites for operator-visible per-Layer tracing.

## Downstream pillar impact

- **Pillar G Week 6** (per-stage span instrumentation at the pipeline call sites) — the Week 5 infrastructure IS the seam Week 6 builds on. Week 6 wires `traced_stage("discovery", "find_leads", ...)` at the Pillar E discovery primitives + `traced_stage("send", "email", ...)` at the Pillar C dispatcher + completes the Week 4 carry-forward for the send-latency Histogram dispatcher integration via `histogram.record(elapsed, {"channel": ...})` co-located with the send span emit.
- **Pillar G Week 7-8** (SLO violation detector + `slo_violation_detected` event class emit + Slack webhook wiring) — extends the tracing surface with per-Slack-alert spans (the SLO check's per-window aggregation reuses `collect_event_class_snapshots`; the Slack webhook dispatch wraps in `traced_stage("send", "slack_webhook", ...)` for operator-visible tracing of the alert dispatch latency).
- **Pillar G Week 9** (cost dashboard) — extends the per-stage span surface with per-source `cost_incurred` spans (the per-source breakdown surfaces as the `source_skill` span attribute, already in `_SPAN_ATTRIBUTES_ALLOWED`).
- **Pillar G Week 10-11** (per-Person observability surface) — the per-Person dashboard adapters CONSUME the per-stage span surface via the tracing backend's per-Person filter (`person_id` is in `_SPAN_ATTRIBUTES_ALLOWED`); operators query per-Person trajectories via the tracing UI's per-Person filter.
- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — composes the per-stage tracing surface + the SLO alerting + the per-Person dashboards into the one-CLI-invocation binding scenario per ADR-0050 D275 + PILLAR-PLAN §2 Pillar G's binding text.
- **Pillar H (daemon + scale)** — the per-process TracerProvider's set-once enforcement (R035 EXTENDED to tracing) creates per-process state; multi-process daemons may need per-daemon-process TracerProvider isolation. The framework-neutrality contract per D298 is preserved at multi-machine scale.
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends `Resource` with per-tenant labels (already content-additive per ADR-0052 D287); per-tenant `SpanProcessor` configuration follows the framework-neutrality contract per D298. Per-tenant span-attribute filters MAY surface here (e.g., per-tenant `_SPAN_ATTRIBUTES_ALLOWED` extensions for operator-confidential per-tenant labels).
- **Pillar J (GDPR purge)** — the per-Person span attribute `person_id` extends Pillar J's per-Person purge transaction to per-Person spans alongside the rest of the per-Person event set. Operators querying per-Person spans via the tracing backend's per-Person filter see the purged state immediately after the purge transaction lands.

## Migration / rollout

- **Operator-side action required at Week 5 upgrade:** **NONE — content-additive.** The Week 5 commit adds new public functions + closed-sets but preserves the Week 1-4 surfaces verbatim. Operators upgrading from Week 4 to Week 5 see the framework's import surface extend (new public functions: `init_otel_tracer_provider` + `get_tracer` + `traced_stage`); existing Week 1-4 callsites continue to work.
- **Recommended (optional):** operators wanting to consume the OTel tracing surface at Week 5:
  ```python
  from observability import (
      init_otel_tracer_provider,
      get_tracer,
      traced_stage,
  )
  from opentelemetry.sdk.trace.export import BatchSpanProcessor
  from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
      OTLPSpanExporter,
  )

  # Operator-supplied OTLP exporter (Honeycomb / Datadog / ...).
  exporter = OTLPSpanExporter(endpoint="https://api.honeycomb.io/v1/traces")
  init_otel_tracer_provider(
      span_processors=[BatchSpanProcessor(exporter)],
  )

  # Operator wires spans at their own call sites BEFORE Pillar G
  # Week 6 lands the framework-side per-stage call-site wiring.
  with traced_stage(
      "send", "email",
      attributes={"channel": "email", "person_id": "p_001"},
  ) as span:
      # ... dispatch logic ...
      pass
  ```
- **Operators with OTLP backends** install their backend's OTLP exporter package separately (`pip install opentelemetry-exporter-otlp-proto-http` for HTTP OTLP; or vendor-specific package for Honeycomb / Datadog / Grafana Cloud) — the framework does NOT ship the OTLP exporter import.
- **Per-tenant migration at Pillar I** — content-additive at Pillar G Week 5; per-tenant audit-tooling at Pillar I extends `Resource` with per-tenant labels (preserves framework `service.*` keys per D294).
- **No ledger schema migration** — Week 5 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes** — Week 5 ships ZERO new event classes (spans flow via OTel SDK, not via `Ledger.append`).
- **No new pip dependencies** — Week 5 uses the three OTel packages pinned at Week 3 (`opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-prometheus`). The trace SDK lives at `opentelemetry.sdk.trace` — included in `opentelemetry-sdk`.
- **OTel set-once caveat for tests:** tests pass `set_global=False` to bypass OTel's set-once enforcement; production callers keep `set_global=True` (the default). Mirrors the Week 3 mitigation per ADR-0052 D282.

## Existing-operator seed

Operator action required at Week 5: **NONE — content-additive.**

Recommended (optional): operators wanting to consume the OTel tracing surface at Week 5 invoke the canonical wiring per the Migration section above + use `traced_stage` at their own call sites. Operators waiting for the framework-side per-stage wiring see it land at Pillar G Week 6.

## References

- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring, per-channel send-latency Histogram, reconcile success ratio ObservableGauge, Prometheus HTTP exposition server, framework-default View set, first Grafana-as-code dashboard). D288-D293.
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope + per-event-class ObservableCounter + cumulative-counter semantics + framework-neutrality contract + default Resource-attribute closed-set). D282-D287.
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. The Week 1 framework decision pinned OpenTelemetry SDK + Prometheus exporter + Grafana-as-code; D273's per-week trajectory table names Weeks 5-6 as OTel tracing instrumentation through the discovery → enrichment → research → draft → review → send → reply → win/loss pipeline.
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. The Pillar G Week 5 commit preserves the Pillar F primitive surfaces + Layer 5 backstop verbatim.
- **ADR-0038** (Pillar F foundation). D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields).
- **ADR-0037** (Pillar E Week 12 close + Stable flip). D172 (Pillar E Stable flip discipline; ~7500 LOC split threshold flag for the cross-pillar coherence test vehicle).
- **ADR-0034** (Pillar E Week 1 — discovery dedup primitive + deterministic-clock contract). D156 (deterministic-clock kwarg discipline carried forward through Pillar E + F + G).
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state).
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant).
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers).
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2 §18 + Week 3 §19 + Week 4 §20 + Week 5 §21 extension per this commit).
- `.planning/HANDOFF-pillar-g-week-4.md` — Pillar G Week 4 close summary + Pillar G Week 5 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 5 close summary.
- `docs/RISK-REGISTER.md` R031 + R032 + R033 (Pillar G Week 1 risks); R034 (Pillar G Week 2 — diagnostic emit at every primitive call inflates ledger when catalog drift persists); R035 (Pillar G Week 3 — OTel SDK's set-once `set_meter_provider` enforcement, EXTENDED at Week 5 to `set_tracer_provider`); R036 (Pillar G Week 4 — Prometheus HTTP exposition server). NO new R-risks at Week 5.
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 5 ADR-0054 references.
- `orchestrator/observability.py` — extended Week 5 with `init_otel_tracer_provider` + `get_tracer` + `traced_stage` + 5 new module-level constants (`_TRACER_NAME`, `_TRACER_VERSION`, `_SPAN_NAME_PREFIX`, `_PIPELINE_STAGES`, `_SPAN_ATTRIBUTES_ALLOWED`) + extended `__all__`.
- `tests/test_observability.py` (extended Week 5) — 66 NEW tests covering the cell-level matrix per the per-week-reviewer discipline now TEN consecutive weeks (Pillar F W6-W12 + Pillar G W2 + W3 + W4 + W5).
