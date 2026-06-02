# ADR-0056: Pillar G Week 7-8 — SLO violation detector, `slo_violation_detected` event class producer, operator-deliberate Slack webhook dispatcher, R032 synthetic-event exclusion, at-most-ONE-per-(slo_name,channel)-per-call rate-limit, `_SLO_NAMES` closed-enum

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 7-8 SLO violation detector + Slack webhook)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape + the OTel SDK + Prometheus exporter + Grafana-as-code framework decision per D273. D273's per-week trajectory table named **Week 7-8 as the SLO violation detector + `slo_violation_detected` event class emit + Slack webhook**. The `slo_violation_detected` event class was named at design-time in `OBSERVABILITY_NEW_EVENT_CLASSES` per D273's "two new event classes Pillar G adds" table; Week 1 shipped the closed-set membership; Week 7-8 ships the producer.

ADR-0051 (Pillar G Week 2, D278-D281) shipped the `collect_event_class_snapshots` body + the `observability_class_uncatalogued` diagnostic emit at-most-ONE per kind per call + R034 mitigation (diagnostic emit at every primitive call inflates ledger when catalog drift persists). The R034 rate-limit pattern (at-most-ONE per kind per call) is the structural pattern Week 7-8 inherits for `slo_violation_detected` (at-most-ONE per `(slo_name, channel)` per call).

ADR-0052 (Pillar G Week 3, D282-D287) shipped the OTel SDK initialization + the single canonical Meter scope `orchestrator.observability` at version `0.1.0` + the per-event-class `ObservableCounter` + the cumulative-counter semantics + the framework-neutrality contract + the default Resource-attribute closed-set. R035 (OTel SDK's set-once `set_meter_provider` enforcement) was introduced; Week 7-8 inherits at the `set_tracer_provider` extension per Week 5.

ADR-0053 (Pillar G Week 4, D288-D293) shipped the Prometheus exporter wiring + the per-channel send-latency `Histogram` instrument `outreach_factory_send_latency_seconds` + the reconcile success ratio `ObservableGauge` `outreach_factory_reconcile_success_ratio` + the Prometheus HTTP exposition server (127.0.0.1 security-by-default per R036) + the framework-default `View` set + the first Grafana-as-code dashboard. The two Week 4 metric instruments (`Histogram` + `ObservableGauge`) are the per-window aggregation surfaces operators consume via PromQL queries for SLO threshold evaluation; Week 7-8 ships the LEDGER-WALKING detector that complements the OTel SDK Prometheus surface (single source of truth = ledger per `docs/SOURCES-OF-TRUTH.md`).

ADR-0054 (Pillar G Week 5, D294-D299) shipped the OTel tracing initialization + the canonical Tracer scope `orchestrator.observability` at version `0.1.0` + the per-stage `traced_stage` context manager + the `_PIPELINE_STAGES` closed-set + the `_SPAN_ATTRIBUTES_ALLOWED` closed-set (privacy invariant per I8 + ADR-0050 D276(b) extended to span attributes) + the framework-neutrality contract for tracing + the **ZERO call-site wiring at Week 5** posture (D299) which explicitly deferred per-stage span instrumentation at the pipeline call sites to Week 6.

ADR-0055 (Pillar G Week 6, D300-D306) shipped the per-stage span instrumentation at 13 per-pillar Python call sites across the eight pipeline stages + the send-latency Histogram dispatcher integration at four of five dispatchers (calendar excluded per D306) + the privacy invariant propagation at call-site span emissions + the per-stage operation naming conventions. The Week 6 commit's per-stage span pattern (`traced_stage("<stage>", "<operation>", attributes={...})`) IS the seam Week 7-8 builds the Slack webhook dispatcher on top of.

Pillar G Week 7-8 ships the **SLO violation detector + the `slo_violation_detected` event class producer + the operator-deliberate Slack webhook dispatcher**. The seven concerns this ADR resolves:

1. **SLO violation detection grain.** PILLAR-PLAN §2 Pillar G's binding text names four SLO triggers: p99 send latency > 5s, reconcile success < 99%, bounce rate > 5%, any `manual_override` event. The framework MUST decide WHERE the detection happens — at the per-event ledger walk (ADR-0051 D278's `collect_event_class_snapshots` substrate), at the per-scrape OTel SDK Prometheus callback (ADR-0053 D290's `register_reconcile_success_ratio_gauge` pattern), OR at a dedicated per-call function (the Week 7-8 introduction). Per the per-week trajectory + the per-pillar Stable flip discipline at Week 12: a dedicated per-call function is the cleanest seam — operators call it from cron / from the `funnel.py` CLI extension at Week 12 + see the violations emitted to the ledger as `slo_violation_detected` events.

2. **`slo_violation_detected` event class payload schema.** The event class was named at design time at ADR-0050 D273; the payload schema MUST carry the SLO name + observed value + threshold + channel (per ADR-0014 D33's channel-on-every-event invariant) + window range. The closed-enum on `slo_name` MUST be mutually exclusive from `reconcile_drift.reason` per ADR-0049 D263 (the legacy-state-vs-new-defense-layer reason-precedence drift discipline NEW pattern from Pillar F Week 12 follow-up).

3. **Operator-configurable SLO thresholds.** PILLAR-PLAN §2 Pillar G's binding text pins thresholds (5s, 99%, 5%, 0) but operators with different scale profiles (higher-latency LinkedIn auth flows; expected baseline of weekly compliance approvals) MAY override per-SLO. The framework MUST pin the operator-override surface — a per-SLOConfig dataclass per ADR-0035 D162's `TierWeights` pattern + ADR-0049 D265's `SLOConfig` placeholder pattern.

4. **R032 synthetic-event exclusion.** ADR-0050 R032 named the risk: "SLO violation alerting false-positive on synthetic-data spike." The mitigation must be STRUCTURAL — events carrying the `_recovered_by` audit marker per ADR-0010 D17 (backfill / reconcile / migration_<id>) MUST be EXCLUDED from SLO evaluation. The mitigation lives at the detector's ledger-walk boundary; operators running migration backfills do NOT see synthetic-data spikes trip the alerts.

5. **At-most-ONE emit per (slo_name, channel) per call.** The rate-limit pattern carried forward from ADR-0051 D279's `observability_class_uncatalogued` diagnostic emit + R034 mitigation. The per-channel aggregation grain naturally enforces ONE violation per `(slo_name, channel)` pair (each SLO computes ONE aggregate per channel); the dedup-tracking-set is defensive belt-and-suspenders against future SLO compositions that might produce multiple per-pair violations.

6. **Slack webhook dispatcher posture.** Operator-deliberate opt-in per ADR-0050 D276(d) — the framework defaults to OFF (slack_webhook_url=None); operators wire the webhook URL via `SLOConfig`. The dispatcher MUST be best-effort (HTTP failure → False return; mirrors the `cost_incurred` emit + the per-channel histogram record posture per ADR-0055 D305). The dispatch MUST be wrapped in `traced_stage("send", "slack_webhook", attributes={"channel": ..., "reason": <slo_name>})` per the Week 6 per-stage span pattern + the privacy invariant per `_SPAN_ATTRIBUTES_ALLOWED` per ADR-0054 D297.

7. **Closed-set on SLO names.** The four SLO names (`send_latency_p99`, `reconcile_success_ratio`, `bounce_rate`, `manual_override_count`) MUST be a module-level frozenset per the R031-shape regression-barrier pattern extended to the SLO surface. The closed-set IS the regression-barrier — a future contributor adding a NEW SLO name without coordinating with this closed-set + the per-pillar ADR triggers refuse-loud at the SLOViolation construction boundary. The closed-set MUST be mutually exclusive from `reconcile_drift.reason` per ADR-0049 D263.

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED from ADR-0050 + ADR-0052 + ADR-0053 + ADR-0054 + ADR-0055; the closed-sets `EVENT_CLASS_CATALOG | OBSERVABILITY_NEW_EVENT_CLASSES` (Week 1) + `_PIPELINE_STAGES` (Week 5) + `_SPAN_ATTRIBUTES_ALLOWED` (Week 5) + `_SLO_NAMES` (Week 7-8, NEW) ARE the layered mitigation. Week 7-8's `_SLO_NAMES` closed-set EXTENDS R031's mitigation surface — a future SLO addition without coordinating with the closed-set surfaces refuse-loud at SLOViolation construction.

- **R032 (SLO violation alerting false-positive on synthetic-data spike)** — UNCHANGED + OPERATIONALLY LIVE at Week 7-8 via D311. The structural mitigation (events carrying `_recovered_by` audit marker per ADR-0010 D17 are EXCLUDED from SLO evaluation) is now in the detector body; operators running migration backfills do NOT see synthetic-data spikes trip alerts. R032 transitions from named-at-design-time (Week 1) to operationally-mitigated (Week 7-8).

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED. Week 7-8's SLO detector is stateless (re-walks the ledger per call); the per-Slack-webhook dispatch is per-call. Multi-process daemons (Pillar H scope) may need per-daemon-process SLO state to dedup webhook alerts across processes; Pillar H may surface per-daemon-process SLO state as a NEW concern.

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED + EXTENDED at Week 7-8 to the `slo_violation_detected` emit's at-most-ONE-per-(slo_name, channel)-per-call rate-limit pattern. The rate-limit caps the per-call emit rate at 4 (per-SLO) × N (per-channel) ≤ ~20 violations per call worst case; the ledger absorption is bounded.

- **R035 (OTel SDK's set-once `set_meter_provider` + `set_tracer_provider` enforcement)** — UNCHANGED. Week 7-8 consumes the existing global TracerProvider via `traced_stage`'s `get_tracer()` fall-through; tests bypass via `monkeypatch.setattr(observability, "get_tracer", ...)`.

- **R036 (Prometheus HTTP exposition server exposes per-process metrics)** — UNCHANGED. Week 7-8 does NOT introduce new HTTP exposition surfaces; the Slack webhook dispatcher is operator-side outbound (POST to operator's Slack workspace), NOT an inbound listener.

ZERO new R-risks surfaced at Week 7-8. The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + ADR-0055 D303 preserves the operator-choice posture across both metric + trace + alert surfaces; the closed-set discipline per `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` + `_SLO_NAMES` preserves the R031-shape regression-barrier; the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0051 D278 + ADR-0052 D284 + ADR-0053 D292 + ADR-0054 D297 + ADR-0055 D304 carries through to the `slo_violation_detected` event payload (closed-set keys only; ZERO privacy-disallowed keys) + the per-Slack-webhook span attributes (the two-key `{channel, reason}` set from `_SPAN_ATTRIBUTES_ALLOWED`).

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12. The Pillar G Week 1-6 surfaces preserve verbatim — `EVENT_CLASS_CATALOG` + `OBSERVABILITY_NEW_EVENT_CLASSES` + `_BREAKDOWN_DIMS_ALLOWED` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` + `MetricSnapshot` + `collect_event_class_snapshots` + `init_otel_meter_provider` + `register_event_class_observable_counter` + `get_send_latency_histogram` + `register_reconcile_success_ratio_gauge` + `init_otel_tracer_provider` + `traced_stage` + 13 per-call-site span wraps + 4-dispatcher histogram records.

## Decision

### D307. SLO violation detector — `detect_slo_violations(led, *, since_window, now, slo_config)`

`orchestrator/observability.py::detect_slo_violations` is the canonical per-call SLO violation detector. The function walks the ledger via `Ledger.all_events()`, applies the per-call window filter (`since = now - since_window`) + the R032 synthetic-event exclusion (events with `_recovered_by` are skipped), computes the four SLO aggregates per PILLAR-PLAN §2 Pillar G's binding text, and emits `slo_violation_detected` events at at-most-ONE per `(slo_name, channel)` per call.

```python
def detect_slo_violations(
    led: Ledger,
    *,
    since_window: timedelta,
    now: datetime | None = None,
    slo_config: SLOConfig | None = None,
) -> list[SLOViolation]:
```

**Per-SLO computation:**

1. **`send_latency_p99`** — per-channel. Pair intent + confirmed events by `intent_id` (per ADR-0014 D33's two-phase commit convention; 5 channels per `_INTENT_EVENT_TYPES_FOR_LATENCY` × `_CONFIRMED_EVENT_TYPES_FOR_LATENCY`); per-pair latency = `confirmed.ts - intent.ts`; per-channel p99 via `_percentile`. Per-channel violation when p99 > `slo_config.send_latency_p99_threshold_seconds` (default 5.0).
2. **`reconcile_success_ratio`** — global (`channel=None`). Ratio = `N_healed / (N_healed + N_drift)` over the window; vacuous success (no reconcile activity) → no violation. Violation when ratio < `slo_config.reconcile_success_ratio_threshold` (default 0.99).
3. **`bounce_rate`** — per-channel. Rate = `N_bounce / (N_bounce + N_confirmed)` over the window per channel; vacuous (zero denominator) → no violation. Per-channel violation when rate > `slo_config.bounce_rate_threshold` (default 0.05).
4. **`manual_override_count`** — global (`channel=None`). Count of `manual_override` events in the window. Violation when count > `slo_config.manual_override_count_threshold` (default 0).

**Stateless contract** per ADR-0050 D272 + R033 mitigation — no in-process cache; every call re-walks the ledger.

**Deterministic-clock contract** per ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278 + ADR-0056 D311. The `now` kwarg defaults to wall-clock; tests pass `now` for byte-identical reproducibility. `now` is stamped onto any `slo_violation_detected` events emitted by this call.

**Return shape:** `list[SLOViolation]` sorted by `(slo_name, channel)` for deterministic output per ADR-0031 D140.

### D308. `slo_violation_detected` event class producer + payload schema

The `slo_violation_detected` event class (named at design time at ADR-0050 D273; member of `OBSERVABILITY_NEW_EVENT_CLASSES`) now has a producer at `detect_slo_violations`. The payload schema:

```jsonc
{
    "type": "slo_violation_detected",
    "ts": "<ISO 8601 UTC>",
    "slo_name": "<one of _SLO_NAMES>",
    "slo_threshold": <float>,
    "observed_value": <float>,
    "channel": "<channel | null>",
    "window_seconds": <float>,
    "_emitted_by": "observability"
}
```

**The `channel` field per ADR-0014 D33's channel-on-every-event invariant** — `null` for global SLOs (`reconcile_success_ratio`, `manual_override_count`); the channel string for per-channel SLOs (`send_latency_p99`, `bounce_rate`). Operators consuming the per-event-class observability surface (via `collect_event_class_snapshots`) see per-channel SLO breakdown when passing `breakdown_by=("channel",)`.

**The `_emitted_by: "observability"` audit marker per ADR-0010 D17** — mirrors the `observability_class_uncatalogued` diagnostic emit's `_emitted_by` field per ADR-0051 D279. Pillar I per-tenant audit-tooling at OSS bring-up filters by `_emitted_by` to segregate framework-emitted events from operator-emitted events for per-operator override-rate dashboards.

**Payload privacy invariant per I8 + ADR-0050 D276(b)** — the payload carries ONLY the closed-set keys above; ZERO privacy-disallowed keys (`source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text`). The closed-set IS the structural commitment.

**`SLOViolation` dataclass** — the in-memory shape `detect_slo_violations` returns + the `slo_violation_detected` event class payload consumes:

```python
@dataclass(frozen=True)
class SLOViolation:
    slo_name: str          # one of _SLO_NAMES
    slo_threshold: float
    observed_value: float
    channel: str | None
    window_seconds: float
```

### D309. `SLOConfig` operator-configurable thresholds + Slack webhook URL

```python
@dataclass(frozen=True)
class SLOConfig:
    send_latency_p99_threshold_seconds: float = 5.0
    reconcile_success_ratio_threshold: float = 0.99
    bounce_rate_threshold: float = 0.05
    manual_override_count_threshold: int = 0
    slack_webhook_url: str | None = None
```

**Defaults match PILLAR-PLAN §2 Pillar G's binding text.** Operators override per-SLO via dataclass kwargs; the immutable frozen=True posture means operators construct ONE `SLOConfig` at framework startup + pass through dispatcher pipelines without mutation (mirrors `TierWeights` per ADR-0035 D162).

**`slack_webhook_url=None` is operator-deliberate OFF per ADR-0050 D276(d).** Absence = SLOs are observed via dashboard rendering only, no alerting fires. Operators wire the URL in `~/.outreach-factory/config.yml`'s `observability:` block (the NEW config-section convention named at ADR-0050 D276); the framework reads the URL at startup + threads it through `SLOConfig`.

### D310. At-most-ONE emit per `(slo_name, channel)` per call

The detector tracks emitted `(slo_name, channel)` pairs in a per-call set; each `slo_violation_detected` emit consults the set + skips re-emission. Mirrors the R034 mitigation pattern from ADR-0051 D279's `observability_class_uncatalogued` diagnostic emit (at-most-ONE per kind per call).

**Per-channel aggregation grain naturally enforces ONE violation per pair** — each SLO computes ONE aggregate per channel (p99 of per-channel latencies; per-channel bounce rate; global reconcile ratio; global override count). The dedup-tracking-set is defensive belt-and-suspenders against future SLO compositions (e.g., a per-channel `send_failed_rate` SLO might surface multiple per-pair violations in the same call grain).

**Worst-case emit rate per call**: 4 SLO names × ~5 channels = ~20 violations per call. R034 mitigation extends to the SLO emit surface — the rate-limit caps ledger absorption; multi-process operators running the detector every minute see ~20 × 60 × 24 = ~28800 emits/day worst-case if every SLO continuously violates. Operators consuming Pillar G dashboards continuously SHOULD fix the underlying SLO violations rather than receive sustained per-call emit; the rate-limit is a guardrail, not a target.

### D311. R032 synthetic-event exclusion via `_recovered_by` audit marker

The detector skips events carrying `_recovered_by` field (per ADR-0010 D17 audit marker convention) from ALL FOUR SLO aggregations. Backfill events (`_recovered_by: "backfill"` per `orchestrator/backfill_ledger.py`), reconcile-recovered events (`_recovered_by: "reconcile"` per `orchestrator/reconcile.py:_recovered_by` Pass B), migration-recovered events (`_recovered_by: "migration_<id>"` per `orchestrator/migrations/ledger/migration_0001.py`) are EXCLUDED.

**Structural mitigation per ADR-0050 R032.** The R032 risk ("SLO violation alerting false-positive on synthetic-data spike") was named at design time at Week 1; Week 7-8 ships the structural mitigation at the detector's ledger-walk boundary. Operators running migration backfills do NOT see synthetic-data spikes trip the SLO alerts.

**The `_recovered_by` filter applies to ALL SLO inputs:**

* `send_latency_p99` — backfill send_intent/send_confirmed pairs excluded.
* `reconcile_success_ratio` — reconcile-recovered drift/healed events excluded.
* `bounce_rate` — reconcile-recovered bounce events excluded (the `bounce_detected` event class carries `_recovered_by: "reconcile"` per `orchestrator/reconcile.py:891`).
* `manual_override_count` — backfill-synthesized manual_override events excluded.

### D312. Slack webhook dispatcher — `dispatch_slo_alert(violation, *, slack_webhook_url, http_post, tracer)`

```python
def dispatch_slo_alert(
    violation: SLOViolation,
    *,
    slack_webhook_url: str | None,
    http_post: Callable[[str, bytes, dict[str, str]], None] | None = None,
    tracer: Tracer | None = None,
) -> bool:
```

**Operator-deliberate opt-in posture per ADR-0050 D276(d).** When `slack_webhook_url` is `None` (default), the function returns `False` immediately + makes ZERO HTTP requests + emits ZERO spans. The no-op posture preserves the OSS bring-up trajectory — new operators evaluating the framework do NOT see surprise alerts.

**Per-stage span wrapping** per ADR-0055 D300-D303 pattern. The dispatch is wrapped in:

```python
with traced_stage(
    "send", "slack_webhook",
    attributes={"channel": ch_attr, "reason": violation.slo_name},
):
    # HTTP POST to Slack
```

* **Stage**: `"send"` (Slack webhook is an external API call from the framework's perspective).
* **Operation**: `"slack_webhook"` (the per-stage operation per ADR-0055 D303's convention).
* **Attributes**:
  - `channel` — the violating metric's channel (or `"none"` for global SLOs; OTel attributes do NOT accept `None` per spec — mirrors `register_event_class_observable_counter`'s convention per ADR-0052 D284).
  - `reason` — the SLO name from `_SLO_NAMES`. The `reason` attribute key is in `_SPAN_ATTRIBUTES_ALLOWED` per ADR-0054 D297; the value space is distinct from `reconcile_drift.reason` (the legacy-state-vs-new-defense-layer reason-precedence drift discipline per ADR-0049 §66 P2-2 + Week 12 follow-up).

**Best-effort posture** — HTTP failures are SWALLOWED + `False` returned. Mirrors the `cost_incurred` emit's try/except-best-effort posture in the dispatchers per ADR-0055 D305. The SLO alert dispatch failure does NOT propagate to the caller — the `slo_violation_detected` event is ALREADY in the ledger per `detect_slo_violations`; operators consult the ledger for the operator-visible audit trail.

**`http_post` injection seam for tests.** The default invocation uses stdlib `urllib.request.urlopen` for the POST (no new pip dep); tests pass a fake `http_post` callable for capture + failure injection. Mirrors the TEST-ONLY embed_fn + retrieve_fn seams per Pillar F.

**Slack payload schema:**

```jsonc
{
    "text": "SLO violation: <slo_name> (channel: <channel>) — observed <observed> vs threshold <threshold> over <window>s window.",
    "slo_name": "<slo_name>",
    "slo_threshold": <float>,
    "observed_value": <float>,
    "channel": "<channel | null>",
    "window_seconds": <float>
}
```

The `text` field is Slack-rendered (operators see this in their Slack channel); the structured fields carry the per-SLO diagnostic detail operators consume programmatically (Slack workflows / chatops).

### D313. `_SLO_NAMES` closed-set + mutual exclusion from `_DRIFT_REASONS`

```python
_SLO_NAMES: frozenset[str] = frozenset({
    "send_latency_p99",
    "reconcile_success_ratio",
    "bounce_rate",
    "manual_override_count",
})
```

**The closed-set IS the R031-shape regression-barrier** extended to the SLO surface + the `slo_violation_detected.slo_name` closed-enum. A future contributor adding a NEW SLO name without coordinating with this closed-set + the per-pillar ADR + the per-week reviewer's audit triggers refuse-loud at SLOViolation construction.

**Mutually exclusive from `reconcile_drift.reason` closed-enum** per ADR-0049 D263 + the legacy-state-vs-new-defense-layer reason-precedence drift discipline (NEW pattern from Pillar F Week 12 follow-up). The Pillar G Week 7-8 commit's regression-barrier test pins:

```python
from orchestrator.reconcile import _DRIFT_REASONS
assert _SLO_NAMES.isdisjoint(_DRIFT_REASONS)
```

Operators filtering Pillar I per-tenant audit-tooling by `reconcile_drift.reason` MUST NOT see SLO names bleeding into the drift-reason consumer surface; operators filtering the Slack webhook span's `reason` attribute MUST NOT confuse SLO names with drift reasons.

## Alternatives considered

### D307 alternatives (SLO violation detector grain)

1. **Compute SLO aggregates inside `register_reconcile_success_ratio_gauge`'s callback (and a similar callback for send-latency).** Rejected — the OTel callback is per-scrape (operator's Prometheus scrape interval, typically 30s); SLO evaluation is per-OPERATOR-RUN (e.g., from cron at 1h intervals). The OTel callback grain is too high-frequency for SLO threshold evaluation + the callback is read-only (cannot emit ledger events for the `slo_violation_detected` audit trail). The dedicated function at `detect_slo_violations` IS the operator-actionable grain.

2. **Compute SLO aggregates inside `collect_event_class_snapshots` (the Week 2 primitive).** Rejected — the per-event-class primitive is per-EVENT-CLASS aggregation grain (one snapshot per event class); SLO evaluation is per-SLO grain (compositions of multiple event classes per SLO — e.g., `bounce_rate` composes `bounce_detected` + `send_confirmed`). Coupling the SLO computation to `collect_event_class_snapshots` would N-times-ify the primitive's per-call cost + violate the per-event-class aggregation contract.

3. **Walk the Prometheus exposition format directly (parse `outreach_factory_send_latency_seconds_bucket` + compute p99 from buckets).** Rejected — the framework's source of truth is the LEDGER per `docs/SOURCES-OF-TRUTH.md`; the Prometheus exposition is a denormalized rebuildable view per ADR-0050 D272 + ADR-0053 D292. Computing the SLO from the denormalized view would (a) couple the SLO computation to operator-side `View` configuration (per-operator histogram bucket choices change the p99 computation); (b) miss the R032 synthetic-event exclusion at the bucket level (the Histogram does NOT carry `_recovered_by` per-record state); (c) make the detector untestable without an OTel SDK provider initialized. The ledger walk IS the canonical source.

4. **Make SLO violation detection PUSH-based via per-event hooks (e.g., the `send_confirmed` event's append site invokes the detector).** Rejected — push-based per-event hooks N-times-ify the per-event cost; the per-event hook AT the ledger append boundary would re-walk the ledger on every event (the detector requires the per-window aggregation). Pull-based per-call (cron / `funnel.py --check-slos`) IS the operator-actionable grain.

### D308 alternatives (`slo_violation_detected` event class payload schema)

1. **Carry the violating events' full payloads inside the `slo_violation_detected` event** (e.g., for `manual_override_count`, embed the full `manual_override` event payloads). Rejected — violates the privacy invariant per I8 (per-override `scope.person_id` MAY be operator-confidential per ADR-0032 D148); inflates the ledger size; couples the per-SLO payload to per-violating-event schema drift. Operators consume the per-violating-event details via the existing ledger query surface (`Ledger.all_events_for_person`); the `slo_violation_detected` event is the index, not the data.

2. **Use a single per-SLO event class per slo_name** (`send_latency_p99_violated`, `reconcile_success_ratio_violated`, ...). Rejected — N-times-ifies the event class set (`EVENT_CLASS_CATALOG` + `OBSERVABILITY_NEW_EVENT_CLASSES` would grow 4 entries instead of 1 per Week 7-8); operators filtering for "any SLO violation" would need to query 4 separate event classes; the closed-enum on `slo_name` provides the discriminator at the per-event payload level.

3. **Omit the `window_seconds` field** (operators MAY derive from the `ts` + the per-window convention). Rejected — the per-call window is operator-supplied via `since_window`; persisting the window seconds in the payload preserves the operator-actionable diagnostic context. Operators consuming the per-event-class observability surface (per ADR-0050 D272) want the window range at glance.

4. **Persist the `slo_threshold` value as the threshold-AT-THE-VIOLATION-TIME** (vs the operator's current `SLOConfig`'s threshold value). Accepted per the dataclass shape — the `SLOViolation.slo_threshold` captures the operator-supplied threshold at detection time; the `slo_violation_detected` event payload carries that value. Operators tightening / loosening thresholds over time see the per-violation-time threshold in the audit trail.

### D309 alternatives (`SLOConfig` operator-configurable thresholds)

1. **Source thresholds from `~/.outreach-factory/config.yml` at the detector's call site** (read the YAML on every `detect_slo_violations` call). Rejected — per-call YAML parse adds I/O cost + couples the detector to the YAML schema. The framework-wide convention (per ADR-0035 D162's `TierWeights` + ADR-0049 D265's `SLOConfig` placeholder) is operator constructs the config ONCE at startup + threads it through dispatcher pipelines via the dataclass.

2. **Use a flat-dict config (`dict[str, float]`) instead of a frozen dataclass.** Rejected — a flat-dict loses type safety + operator-readable defaults + the closed-enum on keys (a future operator typo `slo_send_latency_threshold` vs `send_latency_p99_threshold_seconds` would silently use the default). The dataclass IS the canonical operator-readable surface.

3. **Per-channel threshold overrides on `send_latency_p99` + `bounce_rate`** (e.g., `send_latency_p99_threshold_seconds_per_channel: dict[str, float]`). Rejected at Week 7-8 — operators wanting per-channel threshold overrides at OSS bring-up are a Pillar I per-tenant audit-tooling concern. The Week 7-8 framework default uses ONE threshold per SLO; per-channel overrides are a Pillar I extension.

### D310 alternatives (rate-limit on slo_violation_detected emit)

1. **No rate-limit; emit one event per violating sub-input** (e.g., for `manual_override_count`, emit one `slo_violation_detected` per `manual_override` event in the window). Rejected — N-times-ifies the ledger emit rate; operators running the detector every minute with N `manual_override` events per window would see N events per minute. The at-most-ONE-per-`(slo_name, channel)`-per-call rate-limit caps the emit rate.

2. **Rate-limit at the per-call grain across ALL SLOs (at-most-ONE total per call).** Rejected — operators investigating two simultaneously-violating SLOs (e.g., bounce_rate spike AND send_latency_p99 spike from a vendor outage) would see ONE event per call, losing the per-SLO discriminator. The per-`(slo_name, channel)` grain preserves the operator-actionable per-SLO surface.

3. **Rate-limit across calls (e.g., suppress re-emission within a 1h cool-down).** Rejected at Week 7-8 — cross-call rate-limit requires per-process state (per-`(slo_name, channel)` last-emit-timestamp cache); the stateless contract per ADR-0050 D272 + R033 mitigation rejects in-process state. Operators wanting cross-call dedup wire their Slack workspace's de-duplication rules (Slack Workflow Builder supports per-channel de-dup windows). The Pillar H scale revisit MAY surface per-daemon-process cross-call dedup as a NEW concern.

### D311 alternatives (R032 synthetic-event exclusion)

1. **Exclude events by event-type filter** (e.g., skip `migration_event` event class). Rejected — `migration_event` is a structural ledger event per Pillar B; the `_recovered_by` audit marker is the canonical per-event signal for synthetic events per ADR-0010 D17. Filtering by event-type would miss reconcile-recovered bounce events + backfill-recovered send pairs which are NOT in any `migration_*` event class.

2. **Make the exclusion operator-configurable** (e.g., `SLOConfig.exclude_recovered_events: bool = True`). Rejected — the exclusion is structurally load-bearing (R032 mitigation is structural, not preference). Operators wanting to AUDIT the per-recovered SLO impact consume the per-event-class observability surface (passing `breakdown_by=("_recovered_by",)`... wait, that's NOT in `_BREAKDOWN_DIMS_ALLOWED` per ADR-0050 D276(b)); operators querying the ledger directly via `python orchestrator/funnel.py --since N --include-recovered` see the per-recovered breakdown via the funnel CLI's audit posture. The detector's R032 exclusion is structural.

3. **Skip events with `migration_<id>` prefix only** (allow `backfill` + `reconcile` events into SLO evaluation). Rejected — backfill + reconcile events ARE synthetic per the same audit-marker convention; including them in SLO evaluation would trip alerts on operator-triggered backfills + reconcile passes (both are operator-deliberate per ADR-0050 R032's mitigation language). The full `_recovered_by` exclusion is the structural mitigation.

### D312 alternatives (Slack webhook dispatcher posture)

1. **Default ON with a hardcoded Slack workspace URL.** Rejected — Slack webhook URLs are operator-private; the framework cannot hardcode an operator-specific URL. ADR-0050 D276(d) explicitly named operator-deliberate opt-in as the default posture (asymmetric-failure-cost: surprise alerts on new operator setups).

2. **Use a different transport (e.g., email via SMTP, or Microsoft Teams via webhook).** Rejected at Week 7-8 — Slack is the most common operator surface for outbound alerts per the OSS bring-up trajectory + RETRO-pillar-f.md's framework-default discipline. Operators with Microsoft Teams / Discord / PagerDuty wire their backend via Slack-compatible webhook bridges (most chatops platforms ship Slack-webhook-format compatibility); Pillar I per-tenant audit-tooling MAY extend the dispatcher set with per-transport variants.

3. **Use a synchronous dispatcher that raises on HTTP failure** (operators see the failure at the call site). Rejected — the SLO alert dispatch is NOT the SLO violation source-of-truth; the `slo_violation_detected` event IS the SoT per the ledger-is-SoT discipline per `docs/SOURCES-OF-TRUTH.md`. The best-effort posture preserves the SoT + frees operators from coupling SLO detection to outbound HTTP reachability.

4. **Use a more elaborate Slack message format** (Slack Block Kit with buttons / dropdowns for per-alert acknowledgment). Rejected at Week 7-8 — Slack Block Kit messages require operator-side workflow configuration (the per-alert ack flow); the simpler `text` field + structured payload is operator-portable. Pillar I per-tenant audit-tooling MAY extend the dispatcher with per-tenant Block Kit templates.

### D313 alternatives (`_SLO_NAMES` closed-set)

1. **Open-set with no closed-enum check** (operators may name SLOs freely). Rejected — N-times-ifies the per-Person dashboard surface at Pillar G Week 10-11; operators consuming the per-`slo_name` filter would see drift across the per-pillar enumeration. The closed-set IS the R031-shape regression-barrier.

2. **Per-SLO sub-frozensets composed at module level** (`_SLO_NAMES_LATENCY` + `_SLO_NAMES_RELIABILITY` + ...). Rejected — creates the "look in N places" mental model per ADR-0050 D272-Alt2; the single closed-set is operator-readable + the per-SLO operator audit at the per-week reviewer's audit row.

3. **Combine `_SLO_NAMES` with `_DRIFT_REASONS`** (reuse the existing closed-set; treat SLO names as a sub-category of drift reasons). Rejected — the legacy-state-vs-new-defense-layer reason-precedence drift discipline per ADR-0049 §66 P2-2 + Week 12 follow-up explicitly named the discipline of keeping NEW closed-enums DISJOINT from existing reason enums. Operators filtering by `reconcile_drift.reason` (Pillar I per-tenant audit-tooling) MUST NOT see SLO names bleeding into the drift-reason consumer surface.

## Consequences

### Positive

- **The framework's SLO violation detection surface is now operationally complete at Week 7-8** — operators wiring `SLOConfig(slack_webhook_url=...)` + calling `detect_slo_violations(led, since_window=timedelta(days=1))` from cron see per-SLO violations emitted to the ledger as `slo_violation_detected` events + Slack alerts at the operator's workspace.
- **The `slo_violation_detected` event class producer ships at Week 7-8** — the second of the two `OBSERVABILITY_NEW_EVENT_CLASSES` named at design-time at ADR-0050 D273 now has a producer; both new event classes (observability_class_uncatalogued + slo_violation_detected) are now operationally LIVE.
- **The R032 synthetic-event exclusion is operationally LIVE** — operators running migration backfills do NOT see synthetic-data spikes trip the SLO alerts. The structural mitigation (skip events with `_recovered_by`) is in the detector body.
- **The closed-set discipline per `_SLO_NAMES` IS the R031-shape regression-barrier extended to the SLO surface** — a future contributor adding a NEW SLO name without coordinating with the closed-set + the per-pillar ADR + the per-week reviewer's audit triggers refuse-loud at SLOViolation construction.
- **The privacy invariant per I8 + ADR-0050 D276(b) + ADR-0054 D297 flows through to the slo_violation_detected event payload + the Slack webhook span attributes** — payload + span attributes carry ONLY closed-set keys; ZERO privacy-disallowed keys. Tests pin per the cell-level matrix coverage discipline (TestSLOPrivacyInvariantPayload).
- **The legacy-state-vs-new-defense-layer reason-precedence drift discipline holds at SEVEN consecutive weeks (Pillar F W12 + Pillar G W2-W6 + W7-W8)** — Week 7-8 introduces `_SLO_NAMES` as a NEW closed-enum DISJOINT from `_DRIFT_REASONS` per ADR-0049 D263; the regression-barrier test pins the disjointness (TestWeek7SLONamesClosedSet::test_slo_names_mutually_exclusive_from_drift_reasons).
- **The behavioral-passthrough-not-signature-only discipline holds at NINE consecutive weeks (Pillar F W8-W11 + Pillar G W3-W6 + W7-W8)** — Week 7-8 tests capture spans via `InMemorySpanExporter` + captured ledger events + fake `http_post` callable for the Slack webhook (TestDispatchSLOAlertSpanWiring, TestDispatchSLOAlertHttpSuccess).
- **The cell-level matrix coverage discipline holds at TWELVE consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8)** — Week 7-8 ships 49 new tests covering per-SLO cells (send-latency, reconcile, bounce, override) × per-channel × per-violation/non-violation × per-config-override × per-synthetic-exclusion + per-dispatch cells (default-off, success, failure, span-wiring, channel-none) + per-privacy-invariant + per-rate-limit + per-deterministic-clock + per-event-payload-shape + per-not-uncatalogued.
- **The module-level docstring drift discipline holds at ELEVEN consecutive weeks (Pillar F W8-W12 + Pillar G W2-W6 + W7-W8)** — the observability module docstring extension names Week 7-8 + ADR-0056 + the SLO detector + the slo_violation_detected event class producer.
- **The four `TestPillarGSLOAlerting` rows un-skip at Week 7-8** per ADR-0050 D275's trajectory (test_slo_alerting_default_is_off, test_slo_violation_detected_event_class_shape, test_synthetic_event_exclusion_from_slo_evaluation, test_manual_override_event_triggers_compliance_review_alert).
- **ZERO new R-risks** at Week 7-8 — the existing R031/R032/R033/R034/R035/R036 mitigations carry through verbatim; R032 transitions from named-at-design-time (Week 1) to operationally-mitigated (Week 7-8) via D311.

### Negative

- **The detector's per-call cost grows with the ledger size** — at v1 scale (~5K events) the per-call cost is sub-second; at v2 scale (~100K events) the per-call cost may surface as a per-cron-interval latency concern. Mitigation: operators query at appropriate intervals (1h is typical for SLO evaluation); Pillar H scale revisit may surface per-event-class indexing as a NEW concern.
- **The Slack webhook dispatcher couples the framework to Slack's outbound HTTP API** — operators with chatops backends outside Slack-compatible-webhook-format need a per-transport adapter at Pillar I per-tenant audit-tooling. The Week 7-8 default ships Slack-webhook-format only.
- **The `_SLO_NAMES` closed-set extension at future Pillar G weeks requires coordinated ADR + per-week reviewer audit** — a future contributor adding a new SLO (e.g., `cost_burn_rate` for Week 9 cost dashboard) MUST extend the closed-set + the per-pillar ADR's "new SLO names" table. Mitigation: the per-week-reviewer's cross-pillar back-audit discipline catches the structural drift.
- **The test surface grows by 49 tests** — `tests/test_observability.py` ships 49 NEW tests covering the cell-level matrix; file size grows from ~4200 LOC to ~5300+ LOC, still below the ~7500 LOC split threshold flagged by ADR-0037 D172.

### Neutral

- **The OTel scope version stays at `0.1.0`** per ADR-0052 D283 + ADR-0054 D295 — the Week 7-8 Slack webhook span is content-additive (new span under the same scope); operators consuming the OTLP / Prometheus export see the scope version unchanged.
- **No new pip dependencies at Week 7-8** — the Slack webhook dispatcher uses stdlib `urllib.request.urlopen` for HTTP POST. The OTel SDK's tracing surface is in `opentelemetry-sdk>=1.38` pinned at Week 3.
- **No ledger schema migration** — Week 7-8 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1-6).
- **One new event class producer** — Week 7-8 ships the `slo_violation_detected` event class producer (the closed-set member named at Week 1 + the producer at Week 7-8). ZERO new event classes beyond the Week 1 design-time enumeration.
- **No new operator-facing CLI surfaces** — Week 7-8 does NOT extend `orchestrator/funnel.py` or any other CLI; operators invoke `detect_slo_violations` programmatically from their cron setup. Week 12 may extend `funnel.py` to surface SLO violations as part of the one-CLI-invocation binding exit-criterion test.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — `slo_violation_detected` events are emitted to the ledger; the Prometheus exposition + Slack webhook are denormalized rebuildable views per `docs/SOURCES-OF-TRUTH.md`.
- **I2 (Atomicity contract).** Compliant — the SLO detector's `Ledger.append` for `slo_violation_detected` events is atomic per the existing ledger append contract. The Slack webhook dispatch is best-effort post-emit; ledger emit succeeds independently of webhook delivery.
- **I3 (Single source of truth).** Compliant — every SLO violation re-derives from the per-call ledger walk; no state cached at the detector level.
- **I4 (Determinism).** Compliant — the `now` kwarg controls the deterministic-clock stamp on `slo_violation_detected` event ts; tests pass `now` for byte-identical reproducibility per ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278.
- **I5 (Refuse loud).** Compliant — `_SLO_NAMES` is the closed-enum on the `slo_violation_detected.slo_name` payload field; the closed-set IS the R031-shape regression-barrier. SLOViolation construction with a name outside `_SLO_NAMES` triggers per-call refuse-loud (the SLOViolation dataclass + the per-call SLO computation only construct SLOViolations with names in the closed-set).
- **I6 (No silent state).** Compliant — every SLO violation is observable on the ledger (via the `slo_violation_detected` event class) + via the operator's tracing backend (via the per-Slack-webhook span); the Slack webhook delivery failure is observable via the dispatcher's `False` return value.
- **I7 (Refuse loud on broken pipelines).** Compliant — the detector's per-event ledger walk surfaces `observability_class_uncatalogued` diagnostics for any event class outside the catalog (per ADR-0051 D279); the `slo_violation_detected` event class is in `OBSERVABILITY_NEW_EVENT_CLASSES` so it does NOT trigger recursive uncatalogued diagnostics on subsequent calls (R031 stability per ADR-0050 D272).
- **I8 (Privacy invariant — operator-confidential fields).** Compliant per D308 + D312 — the `slo_violation_detected` event payload carries ONLY closed-set keys; the per-Slack-webhook span attributes carry ONLY the two-key `{channel, reason}` set from `_SPAN_ATTRIBUTES_ALLOWED`; ZERO privacy-disallowed keys (`source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text`).
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D308 — every `slo_violation_detected` event's `channel` field carries the violating metric's channel (`null` for global SLOs; the channel string for per-channel SLOs).
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 7-8 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected at structural level — Pillar G Week 7-8 does not extend any of the five layers; Layer 5 backstop preserved verbatim. The `manual_override_count` SLO indirectly surfaces operator-deliberate Layer 5 overrides via Pillar I per-tenant audit-tooling at OSS bring-up.

## Downstream pillar impact

- **Pillar G Week 9** (cost dashboard) — Week 9 may extend `_SLO_NAMES` with a `cost_burn_rate` SLO per the cost dashboard's per-source `cost_incurred` aggregation. The closed-set extension MUST coordinate with the per-week reviewer's audit + the per-pillar ADR's "new SLO names" table per the existing closed-set discipline.
- **Pillar G Week 10-11** (per-Person observability surface) — Week 10-11's per-Person dashboards consume the `slo_violation_detected` event class via the per-event-class observability surface (per ADR-0050 D277); the per-`slo_name` filter on the per-Person dashboard surfaces per-operator SLO violation patterns. Per-channel filter on `bounce_rate` SLO surfaces per-channel bounce trends.
- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — Week 12 composes the SLO detector + the per-Slack-webhook dispatcher + the per-Person dashboards + the per-stage tracing surface + the per-channel send-latency histogram + the cost dashboard into the one-CLI-invocation binding scenario per ADR-0050 D275 + PILLAR-PLAN §2 Pillar G's binding text. The `funnel.py --check-slos` extension MAY surface the SLO violations as part of the one-CLI-invocation answer to the three binding questions.
- **Pillar H (daemon + scale)** — the per-cron SLO detector at Week 7-8 is per-process; multi-process daemons may need per-daemon-process SLO state to dedup webhook alerts across processes (Pillar H scope per R033's multi-process state concern). The framework-neutrality contract per ADR-0054 D298 preserves the operator-choice posture at multi-machine scale.
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends `SLOConfig` with per-tenant threshold overrides + per-tenant Slack webhook URLs (already content-additive per the dataclass's frozen=True semantics — operators construct ONE `SLOConfig` per tenant). Per-tenant `_SLO_NAMES` extensions (e.g., per-tenant compliance SLOs) follow the closed-set discipline per the per-pillar foundation pattern. Per-tenant Slack workspace isolation: each tenant's `slack_webhook_url` points to a per-tenant Slack workspace; the framework neutrality preserves at multi-tenant scale.
- **Pillar J (GDPR purge)** — the `slo_violation_detected` event class payload carries NO `person_id` (the per-SLO aggregation grain is per-channel or global); GDPR purge does NOT need to extend to per-Person `slo_violation_detected` events. The `manual_override_count` SLO's underlying `manual_override` events DO carry `scope.person_id` (per ADR-0006 D5's override contract); Pillar J's per-Person GDPR purge transaction MUST extend to per-Person `manual_override` events independently of the SLO detector.

## Migration / rollout

- **Operator-side action required at Week 7-8 upgrade:** **NONE — content-additive.** The Week 7-8 commit adds `detect_slo_violations` + `dispatch_slo_alert` + `SLOConfig` + `SLOViolation` + `_SLO_NAMES` to `orchestrator/observability.py`; existing surfaces are PRESERVED verbatim. Operators upgrading from Week 6 to Week 7-8 see identical behavior — the detector is NOT auto-called at module load; operators invoke `detect_slo_violations` programmatically.
- **Recommended (optional):** operators wanting per-cron SLO violation detection + Slack alerting at Week 7-8:

  ```python
  from datetime import timedelta
  from observability import (
      SLOConfig,
      detect_slo_violations,
      dispatch_slo_alert,
  )

  # Operator wires Slack webhook URL from ~/.outreach-factory/config.yml.
  config = SLOConfig(
      slack_webhook_url="https://hooks.slack.com/services/T/B/X",
      # Per-SLO threshold overrides (optional).
      send_latency_p99_threshold_seconds=5.0,  # default
      reconcile_success_ratio_threshold=0.99,  # default
      bounce_rate_threshold=0.05,              # default
      manual_override_count_threshold=0,       # default
  )

  # Per-cron invocation (e.g., hourly).
  violations = detect_slo_violations(
      led,
      since_window=timedelta(hours=1),
      slo_config=config,
  )

  # Operator-deliberate dispatch: pass slack_webhook_url to each.
  for v in violations:
      dispatch_slo_alert(
          v,
          slack_webhook_url=config.slack_webhook_url,
      )
  ```

- **First detector run post-upgrade MAY surface synthetic-event-related noise** if the operator's ledger contains pre-Week-7-8 events with NO `_recovered_by` marker for synthetic-data events (e.g., pre-Pillar-B backfill events). Operators inspect the surfaced violations + manually verify against the underlying events; operators MAY re-run migrations to backfill the `_recovered_by` marker on legacy events.
- **No ledger schema migration** — Week 7-8 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes beyond the Week 1 design-time enumeration** — `slo_violation_detected` was named at design-time at ADR-0050 D273.
- **No new pip dependencies** — the Slack webhook dispatcher uses stdlib `urllib.request`.
- **OTel set-once caveat for tests:** tests use the existing `monkeypatch.setattr(observability, "get_tracer", ...)` pattern from `in_memory_tracer` fixture per ADR-0055.

## Existing-operator seed

Operator action required at Week 7-8: **NONE — content-additive.**

Recommended (optional): operators wanting per-cron SLO violation detection + Slack alerting at Week 7-8 invoke the canonical wiring per the Migration section above. Operators waiting for the framework-side cost dashboard see it land at Pillar G Week 9; per-Person observability dashboards at Pillar G Week 10-11; binding exit-criterion test at Pillar G Week 12.

## References

- **ADR-0055** (Pillar G Week 6 — Per-stage span instrumentation at the per-pillar Python call sites + send-latency Histogram dispatcher integration + per-stage operation naming conventions + privacy invariant propagation at call-site span emissions). D300-D306. The Week 6 per-stage span pattern IS the seam Week 7-8's Slack webhook dispatcher builds on; `traced_stage("send", "slack_webhook", ...)` mirrors the per-channel dispatcher pattern.
- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization + canonical Tracer scope + per-stage `traced_stage` context manager + `_PIPELINE_STAGES` closed-set + privacy invariant on span attributes via `_SPAN_ATTRIBUTES_ALLOWED` + framework-neutrality contract for tracing). D294-D299. The `_SPAN_ATTRIBUTES_ALLOWED` closed-set covers Week 7-8's `{channel, reason}` per-Slack-webhook span attributes.
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + per-channel send-latency Histogram + reconcile success ratio ObservableGauge + Prometheus HTTP exposition server + framework-default Views + first Grafana-as-code dashboard). D288-D293. Week 7-8's SLO detector computes per-window aggregates that complement the Week 4 metric instruments' per-scrape aggregates (operators query Prometheus directly for per-scrape p99; operators query the ledger via the detector for per-window SLO violations + audit trail).
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope + per-event-class ObservableCounter + cumulative-counter semantics + framework-neutrality contract + default Resource-attribute closed-set). D282-D287.
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281. The at-most-ONE-per-kind-per-call rate-limit pattern + R034 mitigation is the structural pattern Week 7-8 inherits for at-most-ONE-per-(slo_name, channel)-per-call.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. D273's per-week trajectory table named Week 7-8 as the SLO violation detector + Slack webhook ship week; the `slo_violation_detected` event class was named at design-time in `OBSERVABILITY_NEW_EVENT_CLASSES`. D276(d)'s operator-deliberate opt-in posture per the OSS bring-up trajectory.
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. D263's `_DRIFT_REASONS` closed-set is the legacy enum Week 7-8's `_SLO_NAMES` is mutually exclusive from per the legacy-state-vs-new-defense-layer reason-precedence drift discipline.
- **ADR-0042** (Pillar E Week 9-11 — discovery lineage primitive + idempotence key contract). D210 (closed-enum discipline). Week 7-8's `_SLO_NAMES` follows the same closed-enum pattern.
- **ADR-0038** (Pillar F foundation). D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields).
- **ADR-0035** (Pillar E Week 6-8 — tier auto-assignment primitive). D162 (`TierWeights` operator-configurable dataclass pattern; mirrors Week 7-8's `SLOConfig` shape).
- **ADR-0034** (Pillar E Week 1 — discovery dedup primitive + deterministic-clock contract). D154-D158.
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state). Week 7-8's `detect_slo_violations` return list is sorted by `(slo_name, channel)` for deterministic output.
- **ADR-0027** (Pillar D Week 4-5 — per-channel reply detection passes G/H/I/J). D109-D112.
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant). Week 7-8's `slo_violation_detected` event payload `channel` field carries the channel uniformly per this invariant.
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). Week 7-8's R032 mitigation consumes `_recovered_by` for synthetic-event exclusion; the `slo_violation_detected` event payload carries `_emitted_by: "observability"` per the audit-marker discipline.
- **ADR-0006** (Phase 5.0 policy engine — override contract). D5 (the `manual_override` event payload shape: `rule` + `expires_ts` + `scope` + `reason` + `approved_by`). Week 7-8's `manual_override_count` SLO consumes the event count; the audit trail (per-override rule + scope + reason + approved_by) is queried separately via the ledger query surface.
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2 §18 + Week 3 §19 + Week 4 §20 + Week 5 §21 + Week 6 §22 + Week 7-8 §23 extension per this commit).
- `.planning/HANDOFF-pillar-g-week-6.md` — Pillar G Week 6 close summary + Pillar G Week 7-8 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 7-8 close summary.
- `docs/RISK-REGISTER.md` R031 + R032 + R033 + R034 + R035 + R036 (no new R-rows at Week 7-8; R032 transitions from named-at-design-time to operationally-mitigated via D311).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 7-8 ADR-0056 references.
- `orchestrator/observability.py` — extended Week 7-8 with `SLOConfig` + `SLOViolation` + `_SLO_NAMES` + `detect_slo_violations` + `dispatch_slo_alert` + `_format_slo_slack_payload` + `_parse_iso_utc_for_slo` + `_percentile` + `_INTENT_EVENT_TYPES_FOR_LATENCY` + `_CONFIRMED_EVENT_TYPES_FOR_LATENCY`.
- `tests/test_observability.py` (extended Week 7-8) — 49 NEW tests covering the cell-level matrix per the per-week-reviewer discipline NOW TWELVE consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8).
- `tests/test_multi_channel_coherence.py::TestPillarGSLOAlerting` — four SKIPPED rows un-skipped at Week 7-8 per ADR-0050 D275's trajectory (test_slo_alerting_default_is_off, test_slo_violation_detected_event_class_shape, test_synthetic_event_exclusion_from_slo_evaluation, test_manual_override_event_triggers_compliance_review_alert).
