# ADR-0063: Pillar H Week 4 — `serve_health_endpoint` body wiring asyncio-aiohttp HTTP server on `127.0.0.1:8080` per R036 + `health_probe` rate-limit per R038 + `build_health_probe_payload` emit-shape factory + per-pillar-H Grafana panel at `infra/grafana/dashboards/per_daemon.yml` + NEW pip dependency `aiohttp`

- **Status:** Accepted
- **Date:** 2026-05-27
- **Pillar:** H (Daemon + dispatcher — Week 4 health endpoint + Grafana panel)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0060 (Pillar H Week 1 foundation, D331-D336) pinned the daemon primitive shape; ADR-0061 (Pillar H Week 2, D337-D340) shipped `init_daemon` body + `EVENT_CLASS_CATALOG` extension + `build_daemon_started_payload`; ADR-0062 (Pillar H Week 3, D341-D344) shipped `attach_signal_handlers` body + `DaemonRunner.shutdown` body + the two stopping/stopped emit-shape factories + the `SHUTDOWN_REASONS` / `DAEMON_EXIT_REASONS` closed-sets. The Pillar H Week 3 follow-up commit `bdbde52` shipped 2 P2 + 6 P3 reviewer findings closures (the per-week-reviewer pattern at TWENTY-ONE consecutive weeks at start of Pillar H Week 4); the Week 3 follow-up added the `EMITTED_BY = "daemon"` module constant per the SECOND ADR-vs-actual-impl drift in Pillar H (the FIRST was Week 2 follow-up P3-8 OTel Resource rationale) + moved `started_at_ts` parsing UPFRONT in `DaemonRunner.shutdown` before state transition + added regression-barrier tests for the `object.__setattr__` escape hatch.

Pillar H Week 4 ships the **`serve_health_endpoint` body** wiring an asyncio-aiohttp HTTP server on `127.0.0.1:8080` per R036 (security-by-default) + the **`health_probe` rate-limit per R038** capping at-most-ONE `health_probe` ledger event per `DaemonConfig.health_probe_rate_limit_seconds` (default 30s) + the **`build_health_probe_payload`** emit-shape factory + the **per-pillar-H Grafana panel** at `infra/grafana/dashboards/per_daemon.yml` (NEW) rendering daemon lifecycle transitions over time + the per-stage parallelism limits + the health probe event rate + the per-event-class catalog count + daemon uptime. The four concerns this ADR resolves:

1. **The `serve_health_endpoint` body MUST run on the asyncio event loop per ADR-0060 D332's asyncio framework decision.** The Python stdlib's `http.server` is sync (would block the asyncio event loop); the canonical asyncio HTTP server choice is `aiohttp` (the AIO ecosystem's de-facto-standard) — chosen for: (a) asyncio-native (no thread-pool indirection); (b) lightweight (no Django/FastAPI framework overhead); (c) Pillar G framework adoption already wires Prometheus via the sync `prometheus_client.start_http_server`, but the Pillar H health endpoint runs INSIDE the daemon's asyncio event loop alongside the per-stage worker pool (Week 5+) — aiohttp fits the asyncio cooperative-scheduling model. The endpoint binds to `127.0.0.1:<port>` by default per R036 (matches the Pillar G Week 4 `start_prometheus_http_server` security-by-default convention per ADR-0053 D291); operators wanting cross-machine probes wire a reverse proxy or pass `bind_addr="0.0.0.0"` (deliberately).

2. **The HTTP server MUST return HTTP 200 + JSON body when `runner.lifecycle_state == "ready"` AND HTTP 503 + JSON body otherwise per the k8s readiness-probe convention.** The k8s readiness-probe convention treats HTTP 200 as "healthy + ready to receive traffic" and HTTP 503 as "unhealthy / not-ready". The daemon's lifecycle states map: `"ready"` → 200; `"initializing"` / `"draining"` / `"stopped"` → 503. The JSON body is the serialized `HealthStatus` dataclass (11 fields: `outcome` + `lifecycle_state` + `daemon_pid` + `daemon_version` + `uptime_seconds` + `config_hash` + `ledger_reachable` + `policy_loaded` + `in_flight_task_count` + `last_reconcile_pass_age_seconds` + `ts`). The `outcome` field is one of `HEALTH_PROBE_OUTCOMES` (`"ok"` / `"degraded"` / `"unhealthy"`); the HTTP status code derives from `outcome` per the documented mapping.

3. **The `health_probe` event MUST be rate-limited per R038 mitigation.** k8s readiness probes typically hit every 10s; without rate-limiting, a single-tenant deployment would emit ~8640 `health_probe` events per day inflating the ledger + the per-event-class catalog with low-signal noise. The rate-limit at-most-ONE event per `DaemonConfig.health_probe_rate_limit_seconds` (default 30s; operators wanting per-request emits set to 0) caps the emit rate at ~2880 events/day per single-tenant operator — within the daemon's diagnostic budget. The rate-limit primitive is per-process state on the `serve_health_endpoint`'s closure (NOT a per-instance class attribute) — operators wiring multiple daemons per process see independent rate-limit state per `serve_health_endpoint` invocation.

4. **The per-pillar-H Grafana panel MUST render the daemon's per-week-4 observability surface per ADR-0060 D332's trajectory.** The panel at `infra/grafana/dashboards/per_daemon.yml` (NEW; ~180 LOC) follows the Pillar G Week 4 `overview.yml` precedent + the Pillar G Week 10-11 `per_person.yml` per-pillar-locality convention. Five panels: (a) daemon lifecycle transitions over time (the `daemon_started` / `daemon_stopping` / `daemon_stopped` per-event-class rate over 1h via PromQL's `rate()`); (b) per-stage parallelism saturation (the `outreach_factory_events_total{event_class="daemon_stage_saturated"}` Week 6+ trajectory; Week 4 ships the panel with the placeholder query showing zero); (c) health probe event rate (the `outreach_factory_events_total{event_class="health_probe"}` rate); (d) per-event-class catalog count (the `outreach_factory_events_total` total by event_class); (e) daemon uptime (the `daemon_started.startup_seconds` distribution).

Risks this ADR mitigates by design: **R036** (Prometheus HTTP exposition security-by-default) extends to **R036'** (health endpoint security-by-default) via the same `127.0.0.1` bind default; **R037** (daemon process-restart silent state loss) mitigated by the reconcile loop + the health endpoint surfaces the post-restart state to operators; **R038** (health probe event-emission flood) directly mitigated by the rate-limit primitive; **R039** (per-Person primitive O(N) at v2 scale) preserves the Week 8-9 per-event-class indexing trajectory. The Pillar G framework adoption surfaces preserve verbatim. The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The Pillar H Week 1 + Week 1 follow-up + Week 2 + Week 2 follow-up + Week 3 + Week 3 follow-up surfaces preserve VERBATIM; Week 4 EXTENDS via `serve_health_endpoint` body + `health_probe` rate-limit + `build_health_probe_payload` factory + Grafana per_daemon.yml + aiohttp dependency.

## Decision

### D345. `serve_health_endpoint` body — asyncio-aiohttp HTTP server on `127.0.0.1:<port>` per R036 + k8s readiness-probe response shape

`orchestrator/daemon/health.py::serve_health_endpoint` body lands per the ADR-0060 D334 contract + the asyncio framework decision:

```python
async def serve_health_endpoint(
    port: int,
    *,
    runner: "DaemonRunner",
    bind_addr: str = "127.0.0.1",   # R036 security-by-default
    emit_fn: Callable[[dict], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> None:
    from aiohttp import web

    if emit_fn is None:
        from orchestrator.ledger import Ledger
        ledger = Ledger(runner.config.ledger_dir)
        emit_fn = ledger.append
    if now_fn is None:
        now_fn = lambda: datetime.now(tz=timezone.utc)

    # Per-server rate-limit state (closure-scoped).
    last_emit_ts: list[datetime | None] = [None]

    async def _handle_health(request: web.Request) -> web.Response:
        now = now_fn()
        status = _compute_health_status(runner, now)
        # Rate-limited emit per R038.
        if (
            last_emit_ts[0] is None
            or (now - last_emit_ts[0]).total_seconds()
            >= runner.config.health_probe_rate_limit_seconds
        ):
            emit_fn({
                "type": "health_probe",
                **build_health_probe_payload(
                    pid=runner.pid,
                    outcome=status.outcome,
                    lifecycle_state=status.lifecycle_state,
                    remote_addr=request.remote or "unknown",
                ),
            })
            last_emit_ts[0] = now
        http_status = 200 if status.outcome != "unhealthy" else 503
        return web.json_response(dataclasses.asdict(status), status=http_status)

    app = web.Application()
    app.router.add_get("/health", _handle_health)
    runner_obj = web.AppRunner(app)
    await runner_obj.setup()
    site = web.TCPSite(runner_obj, bind_addr, port)
    await site.start()
```

The body uses **operator-deliberate test seam kwargs** per the Pillar G TEST-ONLY convention + the Pillar H Week 2 / Week 3 precedent — production callers omit `emit_fn` + `now_fn`; tests inject spies. The `bind_addr` kwarg defaults to `"127.0.0.1"` per R036 + the Pillar G Week 4 `start_prometheus_http_server` precedent; operators wanting `"0.0.0.0"` MUST pass deliberately (security-by-default).

The `_compute_health_status(runner, now)` helper computes the 11-field `HealthStatus` dataclass from the runner's state:
- `outcome`: `"ok"` if `lifecycle_state == "ready"` AND ledger reachable AND policy loaded; `"degraded"` if `lifecycle_state == "ready"` BUT at least one degraded indicator; `"unhealthy"` otherwise.
- `lifecycle_state`: `runner.lifecycle_state` verbatim.
- `daemon_pid`: `runner.pid`.
- `daemon_version`: `runner.version`.
- `uptime_seconds`: `int((now - started_at).total_seconds())`.
- `config_hash`: `runner.config_hash`.
- `ledger_reachable`: True iff `runner.config.ledger_dir.exists()`.
- `policy_loaded`: True iff `runner._policy_rules` non-empty (Week 5+ wires the actual policy state; Week 4 returns True if `lifecycle_state == "ready"` otherwise False).
- `in_flight_task_count`: 0 at Week 4 (Week 5+ wires the per-stage worker pool count).
- `last_reconcile_pass_age_seconds`: 0 at Week 4 (Week 7+ wires the reconcile pass cadence; Week 4 placeholder).
- `ts`: ISO-8601 UTC per `_utc_iso_now`'s format.

Rejected alternatives:

* **Sync `http.server` instead of aiohttp** — rejected. Would block the asyncio event loop; the daemon's per-stage worker pool (Week 5+) shares the event loop; blocking is unacceptable.
* **FastAPI / Starlette** — rejected. Framework overhead exceeds the daemon's minimal needs (single endpoint, no middleware, no validation framework). aiohttp's `web.Application` + `web.json_response` covers the surface in ~20 LOC.
* **Run HTTP server in a thread via `asyncio.to_thread`** — rejected. Mixing threading + asyncio for the simplest single-endpoint server adds GIL contention without benefit; aiohttp's asyncio-native server is the canonical pattern.
* **Sync server via `prometheus_client.start_http_server` pattern (separate thread)** — rejected. The Prometheus exporter's pattern is sync-thread because Prometheus' instrumentation hooks are sync; the health endpoint's hooks (read `runner.lifecycle_state`) are sync but the server SHOULD run on the daemon's event loop for graceful-shutdown coordination (the shutdown body can `await runner_obj.cleanup()` at Week 5+).

### D346. `health_probe` rate-limit per R038 + `build_health_probe_payload` emit-shape factory

The rate-limit primitive is **per-server closure-scoped state** (NOT a class attribute on `DaemonRunner` because the runner is frozen-dataclass; NOT module-level state because multiple `serve_health_endpoint` invocations would share the rate-limit; NOT a per-instance class because the helper closure suffices). The closure captures `last_emit_ts: list[datetime | None]` (mutable container around the single-cell timestamp); each `_handle_health` invocation reads, compares against `runner.config.health_probe_rate_limit_seconds`, and writes if the interval elapsed.

`orchestrator/daemon/health.py::build_health_probe_payload` factory follows the Pillar G `build_*_payload` convention per ADR-0010 D17 + the Pillar H Week 2 follow-up P2-2 closure convention (raw-primitive factories validate at the factory boundary):

```python
def build_health_probe_payload(
    pid: int,
    outcome: str,
    lifecycle_state: str,
    remote_addr: str,
) -> dict[str, Any]:
    if pid <= 0:
        raise ValueError(f"build_health_probe_payload requires pid > 0; got {pid!r}.")
    if outcome not in HEALTH_PROBE_OUTCOMES:
        raise ValueError(
            f"build_health_probe_payload outcome not in HEALTH_PROBE_OUTCOMES "
            f"({sorted(HEALTH_PROBE_OUTCOMES)!r}): {outcome!r}"
        )
    if lifecycle_state not in DAEMON_LIFECYCLE_STATES:
        raise ValueError(
            f"build_health_probe_payload lifecycle_state not in "
            f"DAEMON_LIFECYCLE_STATES "
            f"({sorted(DAEMON_LIFECYCLE_STATES)!r}): {lifecycle_state!r}"
        )
    if not remote_addr:
        raise ValueError("build_health_probe_payload requires non-empty remote_addr.")
    return {
        "pid": pid,
        "outcome": outcome,
        "lifecycle_state": lifecycle_state,
        "remote_addr": remote_addr,
        "_emitted_by": EMITTED_BY,  # Pillar H Week 3 follow-up P2-1 closure
    }
```

The factory stamps `"_emitted_by": EMITTED_BY` at the factory boundary per the Pillar H Week 3 follow-up P2-1 closure (`EMITTED_BY = "daemon"` at `orchestrator/daemon/runner.py`). The factory OMITS `channel` per ADR-0014 D33 (daemon lifecycle events tenant-process-scoped). The `remote_addr` field is operator-visible for filtering by source IP (e.g., k8s readiness probes hit `127.0.0.1:8080` from inside the pod's kubelet; external probes from a reverse proxy show the proxy's address).

Rejected alternatives:

* **Per-`DaemonRunner` instance state** — rejected. The runner is a frozen dataclass per ADR-0060 D331; adding mutable state breaks the frozen invariant. The `object.__setattr__` escape hatch per ADR-0062 D342 is scoped to `lifecycle_state` only per the Pillar H Week 3 follow-up P3-1 closure.
* **Module-level state** — rejected. Multiple `serve_health_endpoint` invocations in the same process (Pillar I per-tenant fan-out trajectory) would share rate-limit state; the per-server closure is the per-tenant-isolation-correct shape.
* **Always emit + filter at consumer** — rejected. R038 mitigation requires emit-time rate-limiting; the consumer surfaces (Pillar G `collect_event_class_snapshots`) aggregate per-event-class counts + the catalog inflation is the structural concern.
* **Per-`remote_addr` rate-limit (cache last_emit_ts per IP)** — rejected. The k8s readiness probe model + the operator's diagnostic intent both treat the daemon as the rate-limit boundary, not per-probe-source. Pillar I per-tenant audit-tooling MAY extend with per-tenant rate-limits.

### D347. Per-pillar-H Grafana panel — `infra/grafana/dashboards/per_daemon.yml` rendering lifecycle transitions + parallelism saturation + health probe rate + catalog count + uptime

`infra/grafana/dashboards/per_daemon.yml` (NEW; ~180 LOC) follows the Pillar G Week 4 `overview.yml` + Pillar G Week 10-11 `per_person.yml` precedents. The dashboard is operator-readable YAML; future Grafana-provisioning code (or manual import) consumes this format per the Pillar G Week 4 `overview.yml` convention.

Five panels:

1. **Daemon lifecycle transitions (1h window)** — `rate(outreach_factory_events_total{event_class=~"daemon_(started|stopping|stopped)"}[1h])`; operators see the daemon restart cadence + graceful-shutdown frequency. Single time-series panel; legend `{{event_class}}`.

2. **Per-stage parallelism saturation (placeholder at Week 4; Week 6+ extends)** — `outreach_factory_events_total{event_class="daemon_stage_saturated"}`; Week 4 ships the panel with the placeholder query (returns zero at Week 4 because the per-stage worker pool body lands at Week 5+); Week 6 extends with the actual saturation event class per the per-stage backpressure body. Stat panel; threshold `>0` → red.

3. **Health probe event rate (1h window)** — `rate(outreach_factory_events_total{event_class="health_probe"}[1h])`; operators see whether the rate-limit per R038 is functioning (a deployed k8s readiness probe at 10s cadence with `health_probe_rate_limit_seconds=30` SHOULD show ~120 events/hour per single-tenant). Time-series panel.

4. **Per-event-class catalog count (24h cumulative)** — `sum by (event_class) (increase(outreach_factory_events_total{event_class=~"daemon_.*|health_probe|policy_reloaded"}[24h]))`; operators see the per-event-class accumulation across all FIVE Pillar H event classes per the per-pillar-foundation precedent. Bar chart panel.

5. **Daemon uptime (current)** — derived from the most recent `daemon_started.startup_seconds` + the time since the most recent `daemon_started` event. Stat panel; operators see "the daemon has been running for X seconds" + the structural commitment to the 24h uptime SLO per PILLAR-PLAN §2 Pillar H exit criterion.

Rejected alternatives:

* **Combine all Pillar H panels into `overview.yml`** — rejected. The per-pillar locality convention per Pillar G Week 10-11 `per_person.yml` + Pillar G Week 9 `cost.yml` separates per-pillar dashboards; operators navigate per-pillar tabs in Grafana.
* **Defer the dashboard to Week 12** — rejected. The Pillar H exit criterion per PILLAR-PLAN §2 Pillar H requires operators to answer "the daemon is running OK" via Grafana; landing the dashboard at Week 4 + extending at Week 6+ + Week 12 binding test verifies the operator's query-shape from the earliest possible point.
* **Single combined panel** — rejected. Five distinct operator concerns (restart cadence, saturation, probe rate, catalog count, uptime) each warrant a panel; the cell-level matrix coverage discipline at the dashboard level mirrors the per-test-class discipline at code level.

### D348. NEW pip dependency `aiohttp` + framework-neutrality contract preservation via two-tiered seam-vs-fork distinction

Add `aiohttp>=3.9,<4` to `orchestrator/requirements.txt` (upper bound added at Pillar H Week 4 follow-up P3-7 closure for dependency-budget stability against silent breakage on a future aiohttp 4.0 API change). The dependency is the asyncio-native HTTP server choice per D345's rationale.

The framework-neutrality contract is **two-tiered** per Pillar H Week 4 follow-up P2-1 closure (the THIRD ADR-vs-actual-impl drift caught in Pillar H by the cross-pillar back-audit discipline — W2 P3-8 OTel Resource rationale + W3 P2-1 `_emitted_by` audit-marker + W4 P2-1 framework-neutrality text. The original D348 text claimed operators could swap HTTP servers "via the test-only seam kwargs OR replace the entire `serve_health_endpoint` function" — the "via the test-only seam kwargs OR" framing was misleading; the seam kwargs `emit_fn` + `now_fn` + `bind_addr` substitute BACKENDS (ledger + clock + IP) but do NOT enable swapping aiohttp for Tornado/FastAPI):

1. **Operator-deliberate seam kwargs** (`emit_fn` + `now_fn` + `bind_addr`) — operators substitute alternative ledger backends (e.g., Kafka via custom `emit_fn`) + clock sources (deterministic test clocks via `now_fn`) + bind addresses (`"0.0.0.0"` for reverse-proxy deployments) WITHOUT replacing the function body. The HTTP server choice (aiohttp) is **NOT** swappable via these seams.
2. **Operator fork** — operators wanting alternative HTTP servers (Tornado / FastAPI / Starlette / etc.) MUST replace the entire `serve_health_endpoint` function body. The aiohttp dependency at `requirements.txt` is the v1 default; the upper bound at `aiohttp>=3.9,<4` per Pillar H Week 4 follow-up P3-7 closure preserves dependency-budget stability.

The regression-barrier test `TestServeHealthEndpoint::test_framework_neutrality_seam_kwargs_do_NOT_swap_http_server` pins the two-tiered contract at test time — asserting the seams produce aiohttp HTTP responses (verifying the seams do NOT swap the HTTP server choice).

Rejected alternatives:

* **Vendor a minimal HTTP server (no dep)** — rejected. The maintenance burden of a custom asyncio HTTP server (parser + routing + status handling) outweighs the cost of a well-maintained 3rd-party dep. aiohttp has 14M+ monthly downloads + Apache 2.0 license + mature asyncio integration.
* **Use `starlette` instead** — rejected. Starlette is the ASGI server framework; the daemon is NOT an ASGI app (no middleware needs); aiohttp's `web.Application` is the simpler-and-sufficient choice.
* **Use the OTel SDK's HTTP exporter as the health endpoint** — rejected. The OTel SDK ships separate exporter HTTP servers (OTLP / Jaeger); they're for trace/metric export, not for k8s readiness probes. The semantic surfaces are different.

## Consequences

The Pillar H Week 4 commit + its `serve_health_endpoint` body + `health_probe` rate-limit + `build_health_probe_payload` factory + per_daemon.yml Grafana dashboard + aiohttp dependency are **content-additive** at the framework boundary per the Pillar H Week 1/2/3 precedent. The daemon's operator-deliberate config (`DaemonConfig.health_port` + `health_probe_rate_limit_seconds`) preserves verbatim from Week 1; Week 4 wires the body that consumes the config.

The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The Pillar G framework adoption surfaces (OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension + READ-ONLY contract) preserve VERBATIM. The Pillar H Week 1 + follow-up + Week 2 + follow-up + Week 3 + follow-up surfaces preserve VERBATIM.

**FOUR coherence test stubs un-skip at this Week 4 commit** (per ADR-0060 D332's trajectory):
- `TestPillarHDaemon::test_health_endpoint_returns_200_on_ready` — verifies HTTP 200 + JSON body when runner is in `"ready"` state.
- `TestPillarHDaemon::test_health_endpoint_returns_503_on_draining` — verifies HTTP 503 + JSON body when runner is in `"draining"` state.
- `TestPillarHDaemon::test_health_probe_event_rate_limited_per_R038` — verifies at-most-ONE `health_probe` event per `health_probe_rate_limit_seconds`.
- `TestPillarHDaemonObservabilityIntegration::test_pillar_h_grafana_panel_renders_lifecycle_transitions` — verifies the per_daemon.yml dashboard YAML is valid + has the FIVE panels per D347.

Skipped at Week 4 (un-skipping at Week 5+ per ADR-0060 D332's trajectory):
- `TestPillarHDaemon::test_sighup_triggers_policy_reload` — Week 7+.
- `TestPillarHDaemon::test_daemon_run_transitions_initializing_to_ready` — Week 5+.
- `TestPillarHDaemon::test_per_stage_parallelism_limit_enforced` — Week 6+.
- `TestPillarHDaemon::test_per_event_class_index_at_startup` — Week 8-9.
- `TestPillarHDaemon::test_recovers_from_kill_9_via_reconcile` — Week 11.
- `TestPillarHDaemonObservabilityIntegration::test_daemon_per_stage_spans_consume_pillar_g_traced_stage` — Week 5+.
- `TestPillarHExitCriterion::test_daemon_24h_run_zero_anomalies_recovers_from_kill_9_reloads_policy` — Week 12.

§Downstream pillar impact across:
- **Pillar I (multi-tenant + OSS hardening)** — per-tenant fan-out wires one `serve_health_endpoint` per tenant container per ADR-0060 D335 invariant 1 + per-tenant health endpoint ports via `DaemonConfig.health_port` per-instance + per-tenant rate-limit state via per-server closure (no shared module-level state) + the `_emitted_by="daemon"` audit marker per ADR-0010 D17 extends naturally to per-tenant filtering via the `_emitted_by` + per-tenant `tenant_id` field combination.
- **Pillar J (security + compliance)** — the health endpoint MUST NOT expose any per-Person state (the `HealthStatus` dataclass shape preserves verbatim from Week 1; the privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 holds — the payload contains COUNTS + STATES + timestamps + version, NEVER `person_id` / body content / source_list); GDPR purge does NOT modify the health endpoint surface; OAuth token rotation at daemon startup preserves via the daemon's policy load step (Week 2 D337 step 5).

§Migration/rollout — operator action: NONE for existing operators (the daemon body lands at Week 5+; Week 4 ships the health endpoint + Grafana panel + rate-limit primitive but the daemon main loop body lands later); operators wanting to preview the health endpoint AFTER Week 5 will invoke `from orchestrator.daemon.health import serve_health_endpoint; asyncio.run(serve_health_endpoint(8080, runner=...))` and curl `http://127.0.0.1:8080/health`.

§Existing-operator seed — operator action: install the new aiohttp dependency via `pip install -r orchestrator/requirements.txt`; the daemon body lands at Week 5+ so no behavior change at Week 4 commit time; the Grafana per_daemon.yml is operator-deliberate (import into Grafana manually OR via grafonnet-Python provisioning code at Pillar I per-tenant fan-out).

Per-week-reviewer disciplines preservation across Pillar H Week 4 (compounded from Pillar F + Pillar G + Pillar H Weeks 1-3 + follow-ups):
- **Cell-level matrix coverage** — TWENTY-ONE consecutive weeks at start of Week 4 → TWENTY-TWO after Week 4 (the new test classes `TestServeHealthEndpoint` + `TestHealthProbePayload` + `TestComputeHealthStatus` extend the discipline; +24 net new daemon contract tests; the `TestPillarHDaemon` × 3 un-skips at Week 4 + `TestPillarHDaemonObservabilityIntegration::test_pillar_h_grafana_panel_renders_lifecycle_transitions` un-skip).
- **Behavioral-passthrough-not-signature-only** — EIGHTEEN consecutive weeks at start of Week 4 → NINETEEN after (TestServeHealthEndpoint's aiohttp-test-client pattern verifies the HTTP 200/503 response + JSON body shape behaviorally; TestHealthProbeRateLimit's spy-emit-fn pattern verifies the at-most-ONE-per-N-seconds rate-limit behaviorally).
- **Module-level docstring drift** — TWENTY consecutive weeks at start of Week 4 → TWENTY-ONE after (health.py module docstring extended naming Week 4 + ADR-0063 + D345-D348; runner.py + __init__.py module docstrings extended naming Week 4).
- **Per-pillar mirror constants parity** — the SEVEN closed-sets at runner.py from Week 3 follow-up preserve verbatim across Week 4; the `EMITTED_BY = "daemon"` module constant from Week 3 follow-up extends to the new `build_health_probe_payload` factory.
- **Cross-pillar back-audit** — the audit-vs-actual-API drift discipline (Week 1 follow-up `TestMigrationRunnerContract`) + the ADR-vs-actual-impl drift discipline (Week 2 follow-up P3-8 + Week 3 follow-up P2-1) BOTH preserve verbatim; the Week 4 author verifies ADR-0063 narrative claims match the actual aiohttp body's behavior + the actual `HealthStatus` payload shape.
- **Framework-neutrality contract** — the aiohttp dependency MUST preserve operator extension point via the test-only seam kwargs `emit_fn` + `now_fn` + the `bind_addr` operator-deliberate parameter; the contract preserves per Pillar H Week 2 follow-up P3-7 + Pillar G Week 4 + Week 5 framework-neutrality precedents.
- **Privacy invariant** — `HealthStatus` dataclass shape preserves verbatim from Week 1; the `build_health_probe_payload` factory output excludes `person_id` / body / source_list; the `_emitted_by="daemon"` audit marker is an operator-facing filter NOT a privacy field.

## References

- **ADR-0062** (Pillar H Week 3 — signal handler + shutdown bodies). D341-D344. **Pillar H Week 3 follow-up P2-1 `EMITTED_BY = "daemon"` module constant extends to `build_health_probe_payload` at this Week 4 commit per the Pillar E precedent + the established framework convention.**
- **ADR-0061** (Pillar H Week 2 — init_daemon body + EVENT_CLASS_CATALOG extension + build_daemon_started_payload factory). D337-D340. **The `build_*_payload` raw-primitive factory convention from D339 (+ Week 2 follow-up P2-2 closure on input validation) carries to `build_health_probe_payload` at this Week 4 commit.**
- **ADR-0060** (Pillar H foundation). D331-D336. **D334 health endpoint signature is the structural commitment Week 4 fulfills via the body; D335 invariant 4 graceful-shutdown structural commitment carries through Week 4 (the health endpoint runs on the daemon's event loop + cleans up on shutdown).**
- **ADR-0058** (Pillar G Week 10-11 — per-Person observability primitive). D322. **The per-pillar mirror constants parity discipline extends to the Pillar H Week 4 `build_health_probe_payload` factory's `EMITTED_BY = "daemon"` + the THREE closed-sets (`HEALTH_PROBE_OUTCOMES` + `DAEMON_LIFECYCLE_STATES`) consumed at the factory boundary.**
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + Grafana-as-code dashboard). D291 + D293. **The security-by-default `127.0.0.1` bind convention from D291 carries to `serve_health_endpoint`'s `bind_addr="127.0.0.1"` default per D345; the Grafana-as-code YAML format from D293 carries to per_daemon.yml at D347.**
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + service identity Resource). D282-D287. **The OTel `_SERVICE_NAME` + `_SERVICE_VERSION` Resource attributes preserve verbatim; the health endpoint surfaces `daemon_version` (= `_DAEMON_VERSION` = `_SERVICE_VERSION` per Week 2 follow-up P3-1 mirror parity).**
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive + OTel SDK framework decision + cross-pillar surface audit + exit-criterion vehicle scope + one-CLI-invocation invariant + per-Person observability surface). D272-D277. **D272's stateless contract preserves — the health endpoint reads `runner.lifecycle_state` (operator-readable) NOT a per-instance counter that diverges from the ledger.**
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. **The `PILLAR_F_LAYER_5_DRIFT_REASONS` BOTH-reasons structural protection preserves verbatim across the Week 4 commit; the health endpoint does NOT touch Layer 5.**
- **ADR-0031** (Pillar D Week 12 — funnel CLI deterministic-output contract). D140. **The `uptime_seconds` field in `HealthStatus` is `int(...)` (truncated to whole seconds for operator-readable display); the Grafana panel's per-event-class rate queries preserve byte-identical PromQL output per the determinism contract.**
- **ADR-0014** (Pillar C foundation — channel-on-every-event invariant). D33. **The `build_health_probe_payload` factory OMITS the `channel` field per the daemon-lifecycle-events-are-tenant-process-scoped rationale (mirrors Pillar H Week 3 `build_daemon_stopping_payload` + `build_daemon_stopped_payload`).**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17. **The factory stamps `"_emitted_by": EMITTED_BY` at the factory boundary (where `EMITTED_BY = "daemon"` is the module constant at `orchestrator/daemon/runner.py`) per the Pillar E `tier_assignment.EMITTED_BY` + `discovery_lineage.EMITTED_BY` precedent + the Pillar H Week 3 follow-up P2-1 closure.**
- **ADR-0001** (Pillar A foundation — declarative policy engine). D2 (refuse-loud convention). **The factory refuses-loud at every invalid input per the framework convention.**
- `.planning/REVIEW-pillar-h-surface-audit.md` — cross-pillar surface audit (Pillar H Week 1 baseline; Week 2 + Week 2 follow-up + Week 3 + Week 3 follow-up + Week 4 extensions at this commit per the per-week-handoff convention).
- `.planning/HANDOFF-pillar-h-week-4.md` — Pillar H Week 4 close summary + handoff to Pillar H Week 5 (this commit; gitignored).
- `docs/PILLAR-PLAN.md` §2 Pillar H + §6 Pillar H row Week 4 status flip + Notes column appended Week 4 close summary.
- `orchestrator/daemon/health.py` (Week 4 body) — `serve_health_endpoint` body + `_compute_health_status` helper + `build_health_probe_payload` factory + module docstring extension naming Week 4.
- `orchestrator/daemon/__init__.py` — re-exports `build_health_probe_payload`; `__all__` extension (17 → 18 names).
- `orchestrator/daemon/runner.py` — module docstring extension naming Week 4 (the `EMITTED_BY` constant from Week 3 follow-up is consumed by the new factory at health.py).
- `orchestrator/requirements.txt` — NEW `aiohttp>=3.9` dependency.
- `infra/grafana/dashboards/per_daemon.yml` — NEW Grafana dashboard with FIVE panels per D347.
- `tests/test_daemon.py` — `TestServeHealthEndpoint` × 6 NEW + `TestHealthProbePayload` × 8 NEW + `TestComputeHealthStatus` × 5 NEW + `TestPublicSurface` updated with `build_health_probe_payload`. Net new tests: +24 (145 → 169 contract-level tests; FOUR additional un-skipped via coherence test extension).
- `tests/test_multi_channel_coherence.py` — FOUR stubs un-skipped (`test_health_endpoint_returns_200_on_ready` + `test_health_endpoint_returns_503_on_draining` + `test_health_probe_event_rate_limited_per_R038` + `test_pillar_h_grafana_panel_renders_lifecycle_transitions`).
- `docs/adr/README.md` — ADR-0063 row added.
- `docs/SOURCES-OF-TRUTH.md` — daemon-state row Week 4 ADR-0063 reference.
