# ADR-0061: Pillar H Week 2 — `init_daemon` body with strict startup ordering invariant, `EVENT_CLASS_CATALOG` extension with FIVE daemon event classes, `build_daemon_started_payload` emit-shape factory, Pillar H Week 1 P3-1 + P3-2 carry-forward closures

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** H (Daemon + dispatcher — Week 2 primitive body)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0060 (Pillar H Week 1 foundation, D331-D336) pinned the daemon primitive shape — `DaemonConfig` + `DaemonRunner` + `PolicyReloadResult` + `HealthStatus` frozen dataclasses + `DAEMON_LIFECYCLE_STATES` + `DAEMON_NEW_EVENT_CLASSES` + `HEALTH_PROBE_OUTCOMES` closed-sets + `init_daemon` + `attach_signal_handlers` + `serve_health_endpoint` + `DaemonRunner.run` + `shutdown` + `reload_policy` primitive signatures — at `orchestrator/daemon/`. The Week 1 commit shipped the module shape + the closed-set frozensets + the dataclasses + the signatures (bodies raise `NotImplementedError`). The Week 1 cross-pillar surface audit at `.planning/REVIEW-pillar-h-surface-audit.md` recorded **TWO P3 carry-forwards** to be addressed at this Week 2 commit: **P3-1** (`init_daemon` body MUST verify the startup ordering invariant via a regression-barrier test) + **P3-2** (`init_daemon` body wires `init_otel_meter_provider` + `init_otel_tracer_provider` from the asyncio startup sequence per R035 set-once enforcement). The Pillar H Week 1 follow-up commit `452d7ae` shipped 2 P2 + 7 P3 reviewer findings closures (the per-week-reviewer pattern's structural value at SEVENTEEN consecutive weeks at start of Pillar H Week 2); the Week 1 follow-up also added the `TestInitDaemonValidation` × 6 skipped stubs pinning the Week 2 validator's behavioral contract per the "Week-N stubs pin the test the Week-(N+1) body un-skips" discipline.

Pillar H Week 2 ships the **`init_daemon` body** + the **`EVENT_CLASS_CATALOG` extension** + the **`build_daemon_started_payload` emit-shape factory** + closes the Pillar H Week 1 carry-forwards P3-1 + P3-2. The four concerns this ADR resolves:

1. **The `init_daemon` body MUST follow a strict startup ordering invariant.** Per the Pillar H Week 1 audit §2 + ADR-0060 D335 invariant 2 (atomicity-preservation-across-process-boundary): the daemon's startup MUST apply pending ledger migrations BEFORE loading Pillar A policy (per ADR-0009 D9 — operators bumping a policy version need the migrated ledger to read prior rule state correctly). The OTel SDK + Prometheus exporter init MUST happen AFTER policy load — the rationale per R035 set-once enforcement: a failed-startup that DID set the global MeterProvider / TracerProvider cannot be cleanly retried in-process without test-only `set_global=False`. Placing OTel AFTER migrations + policy means a migration / policy failure does NOT burn the global OTel state — the failed daemon process exits + a fresh process retries cleanly from Step 1. (Pillar H Week 2 follow-up P3-8 closure — the original rationale claimed "the OTel `Resource` carries the operator-deliberate service identity from the loaded policy" but `init_otel_meter_provider` at `observability.py:2262-2266` builds the default Resource from `_SERVICE_NAME` + `_SERVICE_VERSION`, with no consumer of the loaded policy; the corrected rationale is the set-once-burnout-on-failed-startup concern.) The startup ordering is: (1) validate config → (2) compute hash → (3) resolve PID + ts + version → (4) apply migrations → (5) load policy → (6) init OTel meter + tracer → (7) start Prometheus exporter → (8) construct runner in `"initializing"` state. D337 pins the ordering; D340 binds the regression-barrier test.

2. **The `EVENT_CLASS_CATALOG` extension — Pillar H daemon event classes JOIN the catalog.** Per ADR-0060 D331 the FIVE Pillar H event classes (`daemon_started` + `daemon_stopping` + `daemon_stopped` + `policy_reloaded` + `health_probe`) live in `DAEMON_NEW_EVENT_CLASSES`. At Week 1, the catalog DISJOINT regression-barrier test pinned the closed-set; at Week 2, the test FLIPS to SUBSET (`DAEMON_NEW_EVENT_CLASSES.issubset(EVENT_CLASS_CATALOG)`). The asymmetry vs Pillar G's `OBSERVABILITY_NEW_EVENT_CLASSES` (which stays DISJOINT from the catalog because observability EMITS those two classes itself) is that the daemon's events are emitted BY the daemon process + CONSUMED BY observability via the per-event-class catalog aggregation surface. D338 implements the extension.

3. **The `daemon_started` emit-shape factory — payload structure pinned at Week 2 + the actual transition + emit lands at Week 5+.** Per ADR-0060 D332's per-week trajectory, the daemon's `"initializing" → "ready"` transition lands at Pillar H Week 5+ (`DaemonRunner.run` body). Pillar H Week 2 ships the **payload-building factory** `build_daemon_started_payload(pid, version, config_hash, startup_seconds) -> dict` per the Pillar G `build_*_payload` convention per ADR-0010 D17. The factory pins the canonical payload shape at Week 2 so the Week 5+ author + the per-week reviewer reference one source of truth. D339 implements the factory.

4. **The Pillar H Week 1 carry-forwards close concurrently with the body.** P3-1 (startup ordering regression-barrier) closes via `TestInitDaemonBody::test_startup_ordering_invariant_per_adr_0061_d340_P3_1` — the spy pattern records each step's invocation; the assertion pins the order matches the ADR-0061 D337 contract. P3-2 (OTel set-once at daemon startup) closes via `TestInitDaemonBody::test_otel_set_once_at_daemon_startup_per_adr_0061_d340_P3_2` — the OTel SDK init functions are invoked EXACTLY ONCE per `init_daemon` call. D340 binds the two closures.

Risks this ADR mitigates by design: **R005 / R016 / R023 / R033 / R037 / R038 / R039** all continue mitigated per ADR-0060 D335 + D336; the Week 2 body satisfies the structural commitments without surfacing new risks. **R035 (OTel set-once enforcement)** is now OPERATIONALLY ENFORCED at the daemon's startup site per the P3-2 carry-forward closure — operators invoking `python orchestrator/funnel.py` outside the daemon continue to use the existing `set_global=False` test pattern.

The Pillar G framework adoption surfaces (OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension) preserve verbatim across this Week 2 commit. The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The brand-and-legal-liability invariant + the privacy invariant + the FIVE-layer hallucination-detection defense all hold with FULL weight.

## Decision

### D337. `init_daemon` body — strict startup ordering invariant + test-only seam kwargs per the Pillar G TEST-ONLY convention

`orchestrator/daemon/runner.py::init_daemon` body lands per the ADR-0060 D331 contract + this ADR's strict startup ordering invariant:

```python
def init_daemon(
    config: DaemonConfig,
    *,
    pid_fn: Callable[[], int] = os.getpid,
    ts_fn: Callable[[], str] = _utc_iso_now,
    version: str = _DAEMON_VERSION,
    migration_apply_fn: Callable[[], None] | None = None,
    policy_load_fn: Callable[[Path], list] = _default_policy_load,
    policy_dir: Path | None = None,
    otel_meter_init_fn: Callable[..., Any] | None = None,
    otel_tracer_init_fn: Callable[..., Any] | None = None,
    prometheus_start_fn: Callable[..., None] | None = None,
    prometheus_port: int | None = None,
    prometheus_addr: str | None = None,
) -> DaemonRunner:
    # Step 1: validate (refuse-loud BEFORE side-effecting steps)
    _validate_config(config)
    # Step 2: compute hash
    config_hash = _compute_config_hash(config)
    # Step 3: resolve identity
    pid = pid_fn()
    started_at_ts = ts_fn()
    # Step 4: apply migrations (BEFORE policy)
    (migration_apply_fn or _default_migration_apply)()
    # Step 5: load policy (AFTER migrations)
    policy_load_fn(policy_dir or config.vault_dir.parent / "policies")
    # Step 6: init OTel (set-once per R035)
    (otel_meter_init_fn or _default_otel_meter_init)()
    (otel_tracer_init_fn or _default_otel_tracer_init)()
    # Step 7: start Prometheus (AFTER OTel meter init)
    (prometheus_start_fn or _default_prometheus_start)(...)
    # Step 8: construct runner in "initializing" state
    return DaemonRunner(...)
```

The body uses **operator-deliberate test seams** per the Pillar G TEST-ONLY convention (the `set_global=False` parameter in `observability.init_otel_meter_provider` per ADR-0052 D282; the `embed_fn` + `retrieve_fn` parameters in `voice_corpus.retrieve_top_k` per ADR-0039) — `init_daemon` accepts function-typed kwargs defaulting to the production functions; tests inject spies to verify the startup ordering invariant + mock the side-effecting steps without applying real migrations or starting real HTTP servers.

**Config validation rules** per the Pillar H Week 1 follow-up P3-2 + P3-6 closures: `vault_dir` + `ledger_dir` MUST exist on-disk; `health_port` MUST be in `1..65535`; `parallelism_limits` keys MUST equal `funnel._PILLAR_G_PIPELINE_STAGES`; `policy_reload_signal` MUST be in `DAEMON_POLICY_RELOAD_SIGNALS` OR equal `None`. Refuse-loud via `ValueError` per I5 + ADR-0001 D2.

**Config hash** is SHA-256 of canonical-JSON-encoded dataclass fields (paths serialized as strings; dict keys sorted). The hash is 64 hex chars; operators query to detect config drift across restarts.

**Startup timestamp** is ISO-8601 UTC with Z suffix + millisecond precision per ADR-0010 D17's ts convention. The `daemon_started` event payload + `DaemonRunner.started_at_ts` + `HealthStatus.uptime_seconds` derivation all consume this.

### D338. `EVENT_CLASS_CATALOG` extension — FIVE Pillar H event classes JOIN the catalog

`orchestrator/observability.py::EVENT_CLASS_CATALOG` extends with the FIVE Pillar H event classes from `DAEMON_NEW_EVENT_CLASSES`:

```python
EVENT_CLASS_CATALOG: frozenset[str] = frozenset({
    # ... Pillar A-F classes preserved verbatim ...
    # ---------- Pillar H — daemon + dispatcher (Week 2 catalog extension
    # per ADR-0061 D338; mirrors orchestrator.daemon.DAEMON_NEW_EVENT_CLASSES
    # per the per-pillar mirror constants parity discipline)
    "daemon_started",
    "daemon_stopping",
    "daemon_stopped",
    "policy_reloaded",
    "health_probe",
})
```

The Week 1 `test_disjoint_from_event_class_catalog_at_pillar_h_week_1` test FLIPS to `test_subset_of_event_class_catalog_at_pillar_h_week_2` (rename + invert assertion). The asymmetric assertion vs Pillar G's `OBSERVABILITY_NEW_EVENT_CLASSES` (which stays DISJOINT per `TestModuleConstants::test_observability_new_event_classes_disjoint_from_catalog`) is that:

* Pillar G's classes (`observability_class_uncatalogued` + `slo_violation_detected`) are observability's OWN emissions — diagnostic + operational events generated by the observability primitive itself. Catalog inclusion would create a recursive-uncatalogued loop (observability would emit `observability_class_uncatalogued` every time it encountered its own `slo_violation_detected` emit).
* Pillar H's classes (`daemon_started` + `daemon_stopping` + `daemon_stopped` + `policy_reloaded` + `health_probe`) are emitted BY the daemon process + CONSUMED BY observability via `collect_event_class_snapshots`. Catalog inclusion is necessary for operators to query per-event-class aggregations across the daemon lifecycle.

The regression-barrier test per the per-pillar mirror constants parity discipline at `tests/test_observability.py::TestEventClassCatalogPillarHWeek2Extension` + the symmetric test at `tests/test_daemon.py::TestEventClassCatalogPillarHWeek2Extension` pin the SUBSET invariant at both per-pillar localities (test-time barrier per the cross-pillar back-audit discipline).

### D339. `build_daemon_started_payload` emit-shape factory — Week 2 ships factory; Week 5+ ships actual transition + emit

`orchestrator/daemon/runner.py::build_daemon_started_payload` lands the canonical payload shape for the `daemon_started` event:

```python
def build_daemon_started_payload(
    pid: int,
    version: str,
    config_hash: str,
    startup_seconds: float,
) -> dict[str, Any]:
    return {
        "pid": pid,
        "version": version,
        "config_hash": config_hash,
        "startup_seconds": round(startup_seconds, 3),
    }
```

The factory output is a dict with exactly four keys: `pid` + `version` + `config_hash` + `startup_seconds`. The `type`, `ts`, and `_emitted_by` fields are auto-filled by `Ledger.append` per ADR-0010 D17's per-event factory convention. The `channel` field is OMITTED per ADR-0014 D33 (the channel-on-every-event invariant applies at the dispatcher layer; daemon lifecycle events are tenant-process-scoped, not per-channel; the consumer surface treats absence as `None` per ADR-0050 D272).

`startup_seconds` is rounded to 3 decimal places per ADR-0031 D140 deterministic-output contract. Operators query the `daemon_started` event's payload to:
* Identify the daemon binary across restarts (`version`).
* Detect config drift across restarts (`config_hash`).
* Profile startup-time regressions (`startup_seconds`).

Pillar H Week 2 ships the **factory only** — the actual transition + ledger append happens at Pillar H Week 5+ when `DaemonRunner.run` transitions from `"initializing"` to `"ready"`. The Week 2 commit pins the payload shape so the Week 5+ implementation + the per-week reviewer's behavioral-passthrough verification has one source of truth.

### D340. Pillar H Week 1 P3-1 + P3-2 carry-forward closures — regression-barrier tests for the startup ordering invariant + OTel set-once enforcement

**P3-1 closure** — `tests/test_daemon.py::TestInitDaemonBody::test_startup_ordering_invariant_per_adr_0061_d340_P3_1` uses the spy pattern to record each startup step's invocation, then asserts the order matches the ADR-0061 D337 contract:

```python
call_order: list[str] = []
init_daemon(
    config,
    migration_apply_fn=lambda: call_order.append("migrations"),
    policy_load_fn=lambda _dir: (call_order.append("policy") or []),
    otel_meter_init_fn=lambda *a, **kw: call_order.append("otel_meter"),
    otel_tracer_init_fn=lambda *a, **kw: call_order.append("otel_tracer"),
    prometheus_start_fn=lambda *a, **kw: call_order.append("prometheus"),
)
assert call_order == [
    "migrations",   # Step 4 (BEFORE policy per ADR-0009 D9)
    "policy",       # Step 5 (AFTER migrations)
    "otel_meter",   # Step 6 (set-once per R035)
    "otel_tracer",  # Step 6 (set-once per R035)
    "prometheus",   # Step 7 (AFTER OTel meter init)
]
```

**P3-2 closure** — `tests/test_daemon.py::TestInitDaemonBody::test_otel_set_once_at_daemon_startup_per_adr_0061_d340_P3_2` counts each OTel SDK init's invocations across one `init_daemon` call:

```python
meter_calls = 0
tracer_calls = 0
def _meter_init(*a, **kw):
    nonlocal meter_calls; meter_calls += 1
def _tracer_init(*a, **kw):
    nonlocal tracer_calls; tracer_calls += 1
init_daemon(config, otel_meter_init_fn=_meter_init, otel_tracer_init_fn=_tracer_init, ...)
assert meter_calls == 1
assert tracer_calls == 1
```

The OTel SDK's own set-once semantics handles the "already set" idempotency per Pillar G Week 3 + ADR-0052 D282 convention; the daemon's `init_daemon` is the operator-deliberate set-once site. Operators invoking `python orchestrator/funnel.py` outside the daemon use the existing `set_global=False` test pattern.

Both regression-barrier tests un-skip at this Week 2 commit (Week 1 follow-up shipped them as skipped stubs per the "Week-N stubs pin the test the Week-(N+1) body un-skips" discipline).

## Alternatives considered

### D337 alternatives (init_daemon body + startup ordering)

1. **Apply policy BEFORE migrations — invert the ordering.** Rejected per ADR-0009 D9's "migrations are idempotent + auto-applied at startup" contract — operators bumping a policy version need the migrated ledger to read prior rule state correctly. Inverting the order would surface as: policy YAML references a column that the prior ledger schema lacks → policy load fails → daemon never reaches `"ready"`. The migrations-first ordering is the structural commitment Weeks 7+ `reload_policy` body satisfies (SIGHUP-driven reload does NOT re-apply migrations).

2. **Skip the test-only seam kwargs; have `init_daemon` always call the real functions.** Rejected per the Pillar G TEST-ONLY convention (the `set_global=False` parameter in `observability.init_otel_meter_provider` per ADR-0052 D282; the `embed_fn` + `retrieve_fn` parameters in `voice_corpus.retrieve_top_k` per ADR-0039) — testing the startup ordering invariant requires injecting spies; testing the validation surfaces requires constructing invalid configs without side-effects; the kwargs ARE the test substrate. Production callers omit all kwargs.

3. **Validate config AFTER the migrations + policy load steps.** Rejected per I5 + ADR-0001 D2 refuse-loud convention — config validation should run BEFORE any side-effecting step so operators see the structural error immediately rather than after the per-stage worker pool's startup attempt. The Week 2 body validates first; the Week 1 follow-up P3-6 closure's `TestInitDaemonValidation` × 8 tests verify the validation surfaces.

4. **Make `init_daemon` async.** Considered + REJECTED — the asyncio framework decision per ADR-0060 D332 picks asyncio for the per-stage worker pool's concurrency model, BUT the startup sequence is single-threaded synchronous setup (migration → policy → OTel → Prometheus). Making `init_daemon` async would force callers (production daemon entrypoint + tests) to wrap in `asyncio.run()` for a body that has no `await` points. The synchronous body matches the operator-visible startup model.

### D338 alternatives (EVENT_CLASS_CATALOG extension)

1. **Keep Pillar H classes DISJOINT from the catalog (mirror Pillar G's pattern).** Rejected — Pillar G's classes are observability's OWN emissions (recursive-uncatalogued loop risk if added to catalog); Pillar H's classes are emitted BY the daemon + CONSUMED BY observability (no recursion concern; catalog inclusion enables per-event-class aggregation across the daemon lifecycle). The asymmetric pattern is intentional + documented at D338's narrative.

2. **Add daemon classes to a SEPARATE `DAEMON_EVENT_CATALOG` frozenset instead of extending `EVENT_CLASS_CATALOG`.** Rejected — the per-event-class observability primitive's per-call `collect_event_class_snapshots` accepts a single `expected_classes` kwarg (default `EVENT_CLASS_CATALOG`); a separate catalog would force operators to pass two arguments + the primitive's stateless contract per ADR-0050 D272 would split across two catalogs. The single catalog with per-pillar comment sections is the operator-readable shape.

3. **Defer the catalog extension to Pillar H Week 3 (signal handler bodies + emit transitions).** Rejected per the per-pillar mirror constants parity discipline — the closed-set extension MUST land concurrently with the body that emits the events. The Week 5+ `DaemonRunner.run` body emits `daemon_started`; the Week 3 signal handler body emits `daemon_stopping` + `daemon_stopped`; the catalog extension at Week 2 (BEFORE any emit happens) means the per-call `collect_event_class_snapshots` aggregation surface is ready when the Weeks 3/5 emits arrive.

### D339 alternatives (daemon_started payload factory)

1. **Skip the payload factory; have the Week 5 `DaemonRunner.run` body inline the dict construction.** Rejected per the Pillar G `build_*_payload` convention per ADR-0010 D17 + the 10 existing per-event payload factories at `orchestrator/discovery_lineage.py` + `orchestrator/reply_classifier_llm.py` + `orchestrator/reply_classifier.py` + `orchestrator/email_verification_cache.py` + `orchestrator/discovery_dedup.py` + `orchestrator/voice_corpus.py` + `orchestrator/draft_quality.py` — the factory pattern is the per-pillar canonical shape. Inlining at Week 5 would force the Week 5 reviewer + Pillar I tenant-scoped extensions to extract the factory later.

2. **Add `channel` field to the payload (set to `None` explicitly).** Rejected per ADR-0014 D33 channel-on-every-event invariant — the channel field applies at the dispatcher layer; daemon lifecycle events are tenant-process-scoped, not per-channel. The consumer surface treats absence as `None` per ADR-0050 D272's `MetricSnapshot.channel` field documentation. Adding the explicit `None` would mislead operators reading the payload + add noise to the per-event-class aggregation breakdown_by output.

3. **Add `started_at_ts` field to the payload (in addition to ts auto-fill).** Rejected — ledger event `ts` auto-fill per ADR-0010 D17 IS the event's timestamp; the daemon's startup timestamp is operator-readable via `DaemonRunner.started_at_ts` + `HealthStatus.uptime_seconds` derivation. A redundant `started_at_ts` field in the payload would diverge from auto-fill on operator-injected migration backfills + create reconciliation ambiguity.

4. **Make the factory return the full event dict (including type + ts + _emitted_by).** Rejected per ADR-0010 D17's per-event factory convention — factories return the per-event payload MINUS framework-managed fields. `Ledger.append` injects `type` + `ts` + `_emitted_by` per the existing convention; factories that return the full event dict would either (a) duplicate auto-fill logic (drift risk) OR (b) force callers to strip the framework fields before append. The minus-framework-fields shape is the canonical convention across all 10 existing factories.

### D340 alternatives (P3-1 + P3-2 carry-forward closures)

1. **Defer P3-1 + P3-2 closures to Pillar H Week 5 (when `DaemonRunner.run` body lands).** Rejected per the Pillar H Week 1 follow-up's "Week-N stubs pin the test the Week-(N+1) body un-skips" discipline — the `TestInitDaemonValidation` × 6 stubs shipped at Week 1 follow-up specifically anticipate Week 2 closure. Deferring to Week 5 would leave 6 skipped stubs through Weeks 3 + 4 with no documented un-skip trajectory + waste per-week-reviewer attention on the "why are these still skipped?" question.

2. **Close P3-2 only (OTel set-once) at Week 2; defer P3-1 (startup ordering) to Week 3 with signal handler bodies.** Rejected — the startup ordering invariant SPANS migrations + policy + OTel + Prometheus; Week 2's `init_daemon` body IS the ordering's structural commitment. A Week 3 signal handler body doesn't add ordering steps (signal handlers are AFTER startup); deferring the regression-barrier would surface the test+body asymmetry at Week 3 reviewer time.

3. **Use mocking library (`unittest.mock`) instead of the spy pattern with function-typed kwargs.** Considered + REJECTED — the function-typed kwargs ARE the test substrate; the spy pattern with explicit `call_order.append(...)` is operator-readable + framework-independent. `unittest.mock` introduces a third-party dependency at the test substrate + obscures the call-order assertion behind `Mock.assert_called_*` invocation patterns. The spy-with-list pattern matches the Pillar G Week 2 + Week 7-8 test substrate conventions.

## Consequences

### Positive

- **Pillar H Week 2's `init_daemon` body satisfies the structural commitments Weeks 3-12 build on.** The body's startup ordering invariant + the OTel set-once enforcement + the config validation are pinned at Week 2; Weeks 3+ implementations extend WITHOUT re-deciding the framework choice.
- **The per-pillar mirror constants parity discipline EXTENDS via the `EVENT_CLASS_CATALOG` symmetric assertion.** The per-test-time barrier at both per-pillar localities catches a future Pillar I per-tenant event class divergence.
- **The Pillar H Week 1 carry-forwards P3-1 + P3-2 close concurrently with the body.** The per-week-handoff convention's "carry-forwards close at the next per-week commit" discipline holds at SEVENTEEN consecutive weeks at start of Pillar H Week 2 → EIGHTEEN at this Week 2 commit.
- **The `build_daemon_started_payload` factory pins the payload shape Week 5+ implementation satisfies.** The per-pillar `build_*_payload` convention extends to Pillar H; operators consuming the per-event-class aggregation surface see the canonical payload shape across all 10+ per-event factories.
- **The test-only seam kwargs preserve the Pillar G TEST-ONLY convention.** Production callers omit all kwargs; tests inject spies to verify the startup ordering invariant + mock side-effecting steps without applying real migrations or starting real HTTP servers.
- **The cell-level matrix coverage discipline EXTENDS via the +24 net new daemon tests** (60 → 73 contract tests at test_daemon.py; +3 at test_observability.py; +2 un-skips at test_multi_channel_coherence.py).

### Negative

- **The `init_daemon` body's lazy imports (funnel + observability + policy + migrations) compound the daemon's module-load complexity.** The lazy-import pattern is the standard Python convention for breaking circular import cycles + keeping the daemon's module-load minimal; the per-week reviewer's "minimum import surface" check verifies the daemon imports nothing at module-load time beyond `dataclasses` + `pathlib` + `hashlib` + `json` + `os` + `datetime`. The lazy imports run at the FIRST `init_daemon` call; tests verify via the seam kwargs.
- **The `_default_policy_load` helper scans `policy_dir` for `*.yml` files.** The convention is operator-deliberate per Pillar A — operators wanting non-YAML policy formats wire via the `policy_load_fn` kwarg. Missing `policy_dir` returns an empty list (operator-deliberate posture for fresh deployments without policy YAML); the per-send gate refuses-loud per Pillar A convention if no rules are wired.
- **The Prometheus exporter port + addr default to Pillar G's `observability._DEFAULT_PROMETHEUS_PORT` + `_DEFAULT_PROMETHEUS_ADDR`** (8000 + `127.0.0.1`) — operators wanting cross-machine probes wire a reverse proxy per R036 + ADR-0053 D291's security-by-default pattern. The daemon's health endpoint uses `DaemonConfig.health_port` (default 8080); the two ports are distinct.

### Neutral

- **No new pip dependencies at Pillar H Week 2.** The body uses stdlib (`hashlib` + `json` + `os` + `datetime`) + the Pillar G OTel SDK + Prometheus deps already wired at Pillar G Week 3 + Week 4.
- **No new ledger migrations at Pillar H Week 2.** Pending count stays at 19 (UNCHANGED from Pillar G Week 12 + Pillar H Week 1 + Week 1 follow-up).
- **No new R-risks at Pillar H Week 2.** The existing R031-R039 mitigations carry through verbatim; the Week 2 body satisfies the structural commitments.
- **No changes to the Pillar G framework adoption surfaces.** OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + Grafana per-Person dashboard + funnel CLI extension all preserve verbatim. The daemon CONSUMES these surfaces.
- **No changes to the binding exit-criterion tests of Pillar D / E / F / G.** All four STAY GREEN across the Pillar H Week 2 commit.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — the daemon's per-stage worker pool emits structured events to the ledger; the ledger remains the source of truth. The `build_daemon_started_payload` factory output excludes `person_id` / body content / source_list per the privacy invariant.
- **I2 (Atomicity contract).** Compliant + EXTENDED — D337's startup ordering invariant (migrations → policy → OTel → Prometheus → ready) preserves the atomicity-preservation-across-process-boundary invariant per ADR-0060 D335 invariant 2.
- **I3 (Single source of truth).** Compliant — the EVENT_CLASS_CATALOG is the single SoT for per-event-class aggregation per ADR-0050 D272; the per-pillar mirror constants parity discipline pins parity at test time.
- **I4 (Determinism).** Compliant — the `build_daemon_started_payload` factory rounds `startup_seconds` to 3 decimal places per ADR-0031 D140; the config hash is stable across runs.
- **I5 (Refuse loud).** Compliant — `_validate_config` refuses-loud via `ValueError` at every invalid kwarg per the framework convention + ADR-0001 D2.
- **I6 (No silent state).** Compliant — every startup step's structural change emits a ledger event (Week 5+ ships the `daemon_started` emit per the Week 2 factory).
- **I7 (Refuse loud on broken pipelines).** Compliant — invalid config refuses-loud at startup; missing migration / policy load surfaces as `MigrationRunner.apply()` raise / `load_rules_from_yaml` raise.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — the `daemon_started` payload contains pid + version + config_hash + startup_seconds; NEVER `person_id` / body content / source_list. The Pillar H Week 1 follow-up extended the per-week-reviewer's privacy invariant check to the test-time barrier; this Week 2 commit preserves the barrier verbatim.
- **The channel-on-every-event invariant per ADR-0014 D33** — Unaffected — the FIVE Pillar H event classes (now in EVENT_CLASS_CATALOG) are daemon-lifecycle events WITHOUT channel context; the per-channel two-phase commit invariant preserves verbatim at the dispatcher layer.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — the daemon does NOT modify the per-send gate; the CAN-SPAM compliance per Pillar D preserves verbatim.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — the daemon does NOT modify the Layer 1-5 surfaces; the Pillar F primitive surfaces + Layer 5 backstop preserve verbatim.
- **The one-CLI-invocation invariant per ADR-0050 D276(a)** — Preserved — operators invoking `python orchestrator/funnel.py --since N` from outside the daemon get the same byte-identical output per ADR-0031 D140; the daemon's `init_daemon` body is the operator-deliberate set-once site for OTel + Prometheus per R035 + R036.
- **The READ-ONLY funnel CLI contract per ADR-0059 D325** — Preserved — the daemon does NOT modify `funnel.build_report`; the `init_daemon` body's policy load consumes Pillar A unchanged.
- **The byte-identical determinism contract per ADR-0031 D140** — Preserved — the `build_daemon_started_payload` factory's `round(startup_seconds, 3)` preserves byte-identical output across consecutive emits for identical input.

## Downstream pillar impact

- **Pillar I (OSS bring-up + multi-tenant).** Per-tenant fan-out at the daemon process boundary — Pillar I authors run one `init_daemon` invocation per tenant + the test-only seam kwargs enable per-tenant test substrates without cross-process interference. The Pillar I author MAY extend `EVENT_CLASS_CATALOG` with per-tenant event classes via the catalog's per-pillar comment-section pattern; the `build_daemon_started_payload` factory MAY extend with per-tenant labels via the per-pillar mirror constants parity discipline (Pillar I extension adds `tenant_id` to the payload + the regression-barrier test pins the extension). The Pillar I per-tenant docker-compose surface invokes `init_daemon` once per tenant container.
- **Pillar J (Security + compliance).** GDPR-purge transaction per ADR-0050 §Downstream extends to the daemon's `_compute_config_hash` — a per-Person purge does NOT modify the daemon's config hash (the hash is operator-config-derived, NOT per-Person-derived); the Pillar J author's per-Person purge primitive consumes the per-Person primitives at observability per ADR-0058 D319-D324 + the daemon's per-stage worker pool respects the purge per the per-Person lock primitive. OAuth token rotation per Pillar J extends to the daemon's startup — the daemon's `init_daemon` body wires per-channel token refresh at pre-flight (TBD Pillar J trajectory; the structural surface lands at this Week 2 commit via the policy load step's operator-deliberate posture). SLSA supply-chain attestation per Pillar J extends to the daemon's `_DAEMON_VERSION` constant + the per-pillar trajectory bumps coordinate with PILLAR-PLAN §6 Pillar H row.

## Migration / rollout

- **Operator-side action required at Pillar H Week 2 upgrade:** **NONE — content-additive at the framework boundary.** The Week 2 commit adds the `init_daemon` body + the `EVENT_CLASS_CATALOG` extension + the `build_daemon_started_payload` factory + the test class additions. Operators continue to invoke `python orchestrator/funnel.py --since N` + the per-skill `claude /find-leads` / `/research-prospect` / `/draft-outreach` / `/send-outreach` surfaces unchanged.
- **Recommended (optional):** operators wanting to PREVIEW the Pillar H daemon body invoke `python -c "from pathlib import Path; from orchestrator.daemon import DaemonConfig, init_daemon; r = init_daemon(DaemonConfig(vault_dir=Path('~/Documents/...'), ledger_dir=Path('~/.outreach-factory/ledger/'))); print(r)"` after applying pending migrations via `python -m orchestrator.migrations`. The body returns a `DaemonRunner` in `"initializing"` state; the actual transition to `"ready"` + the per-stage dispatch loop land at Pillar H Week 5+.
- **No ledger schema migration** — Week 2 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **EVENT_CLASS_CATALOG extension is content-additive** — operators running `collect_event_class_snapshots` against a ledger WITHOUT daemon events see zero snapshots for the FIVE new classes (the per-call walk emits empty snapshots per ADR-0050 D272's stateless contract). Operators running the daemon at Week 5+ see the per-event-class aggregation surface populate.
- **No new pip dependencies at Pillar H Week 2** — the body uses stdlib + the existing Pillar G OTel SDK + Prometheus deps.

## Existing-operator seed

Operator action required at Pillar H Week 2: **NONE — content-additive at the framework boundary.**

Recommended (optional): operators following the Pillar H per-week trajectory consume the per-week handoff docs at `.planning/HANDOFF-pillar-h-week-N.md` + the per-week ADRs at `docs/adr/006N-pillar-h-week-N-*.md`. Operators wanting the Pillar H daemon-as-systemd-service wait for Pillar H Week 5+ per ADR-0060 D332's trajectory.

## References

- **ADR-0060** (Pillar H Week 1 foundation — daemon module shape + closed-sets + dataclasses + signatures + cross-pillar audit + exit-criterion vehicle + load-bearing invariants + per-event-class indexing trajectory). D331-D336. **D331's daemon primitive shape is the structural commitment this Week 2 body satisfies; D335 invariant 2 (atomicity-preservation-across-process-boundary) is the startup ordering invariant's structural commitment.**
- **ADR-0059** (Pillar G Week 12 — binding exit-criterion + funnel CLI extension + Pillar G Stable flip + retrospective + handoff to Pillar H). D325-D330. **D325's READ-ONLY funnel CLI contract preserves across the daemon process boundary; D326 stage table mapping consumed by the daemon's per-stage worker pool at Week 5+.**
- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector + `slo_violation_detected` producer + Slack webhook). D307-D313. **D311's `_recovered_by` synthetic-event exclusion preserves verbatim across the daemon.**
- **ADR-0055** (Pillar G Week 6 — Per-stage span instrumentation). D300-D306. **The daemon's per-stage worker pool consumes the per-stage spans verbatim at Week 5+.**
- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization + canonical Tracer scope). D294-D299. **The daemon's `init_daemon` body wires `init_otel_tracer_provider` at Step 6 per the startup ordering invariant.**
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + first Grafana-as-code dashboard). D288-D293. **D291's Prometheus HTTP exposition server's `127.0.0.1` security-by-default bind generalizes to the daemon's Step 7.**
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope). D282-D287. **D282's set-once semantics is the structural commitment the daemon's `init_daemon` body satisfies at Step 6; D286's framework-neutrality contract generalizes to the asyncio choice per ADR-0060 D332.**
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event verification). D278-D281. **The per-pillar-Week-2 precedent for this ADR's structure — Pillar G Week 1 shipped signature; Week 2 shipped body + diagnostic emit factory + carry-forward closures; Pillar H follows the same shape.**
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. **The per-pillar-foundation precedent extends to Pillar H Week 2.**
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. **The Layer 5 backstop preserves verbatim across the daemon.**
- **ADR-0031** (Pillar D Week 12 — funnel CLI deterministic-output contract). D140. **The `build_daemon_started_payload` factory's `round(startup_seconds, 3)` preserves byte-identical output per the determinism contract.**
- **ADR-0014** (Pillar C foundation — channel-on-every-event invariant). D33. **The `daemon_started` payload OMITS the `channel` field per the daemon-lifecycle-events-are-tenant-process-scoped rationale; the consumer surface treats absence as `None`.**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). **The `build_daemon_started_payload` factory mirrors the 10+ per-event factory convention; the `type` + `ts` + `_emitted_by` framework-managed fields are auto-filled by `Ledger.append`.**
- **ADR-0009** (Pillar B foundation — migration framework + idempotent auto-apply contract). D9. **The daemon's `init_daemon` body at Step 4 wires `MigrationRunner.apply()` per the existing contract (the Pillar H Week 1 follow-up P2-1 regression-barrier closure pins the actual API name).**
- **ADR-0001** (Pillar A foundation — declarative policy engine). D2 (refuse-loud convention). **The daemon's `_validate_config` refuses-loud at Step 1 per the framework convention.**
- `.planning/REVIEW-pillar-h-surface-audit.md` — cross-pillar surface audit (Pillar H Week 1 baseline; Week 2 extension at this commit per the per-week-handoff convention).
- `.planning/HANDOFF-pillar-h-week-2.md` — Pillar H Week 2 close summary + handoff to Pillar H Week 3 (this commit; gitignored).
- `docs/PILLAR-PLAN.md` §2 Pillar H + §6 Pillar H row Week 2 status flip + Notes column appended Week 2 close summary.
- `orchestrator/daemon/runner.py` (Week 2 body) — `init_daemon` body + `build_daemon_started_payload` factory + `_validate_config` + `_compute_config_hash` + `_utc_iso_now` + `_default_policy_load` + `_DAEMON_VERSION` constant per D337 + D339.
- `orchestrator/observability.py` — `EVENT_CLASS_CATALOG` extension with FIVE Pillar H event classes per D338.
- `tests/test_daemon.py` — `TestInitDaemonValidation` × 8 un-skipped + `TestInitDaemonBody` × 6 NEW + `TestDaemonStartedPayload` × 4 NEW + `TestEventClassCatalogPillarHWeek2Extension` × 2 NEW + `test_disjoint_from_event_class_catalog_at_pillar_h_week_1` RENAMED + INVERTED to `test_subset_of_event_class_catalog_at_pillar_h_week_2`.
- `tests/test_observability.py` — `TestEventClassCatalogPillarHWeek2Extension` × 3 NEW (per-Pillar-G locality symmetric to the per-Pillar-H locality).
- `tests/test_multi_channel_coherence.py` — `TestPillarHDaemon::test_init_daemon_returns_initializing_runner` un-skipped + body lands; `TestPillarHDaemonObservabilityIntegration::test_daemon_event_classes_join_observability_catalog` un-skipped + body lands.
