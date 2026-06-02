# ADR-0064: Pillar H Week 5 — `DaemonRunner.run` async body wiring the asyncio event loop + per-stage worker pool skeleton + per-stage span integration consuming `observability.traced_stage` + graceful-shutdown coordination via `AppRunner.cleanup`

- **Status:** Accepted
- **Date:** 2026-05-27
- **Pillar:** H (Daemon + dispatcher — Week 5 main loop body + per-stage spans + graceful shutdown coordination)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0060 (Pillar H Week 1 foundation, D331-D336) pinned the daemon primitive shape; ADR-0061 (Pillar H Week 2, D337-D340) shipped `init_daemon` body + `EVENT_CLASS_CATALOG` extension + `build_daemon_started_payload`; ADR-0062 (Pillar H Week 3, D341-D344) shipped `attach_signal_handlers` body + `DaemonRunner.shutdown` body + the two stopping/stopped emit-shape factories + the `SHUTDOWN_REASONS` / `DAEMON_EXIT_REASONS` closed-sets; ADR-0063 (Pillar H Week 4, D345-D348) shipped `serve_health_endpoint` body wiring asyncio-aiohttp HTTP server + `health_probe` rate-limit per R038 + `build_health_probe_payload` factory + per_daemon.yml Grafana dashboard + NEW aiohttp pip dependency. The Pillar H Week 4 follow-up commit `4c0f4dd` shipped 2 P2 + 11 P3 + 3 NEW reviewer findings closures (the per-week-reviewer pattern at TWENTY-THREE consecutive weeks at start of Pillar H Week 5); the Week 4 follow-up added the framework-neutrality two-tiered seam-vs-fork distinction at ADR-0063 D348 per the THIRD ADR-vs-actual-impl drift in Pillar H + `HealthStatus.__post_init__` closed-set validation + `bind_addr` refuse-loud at boundary + Week 4/6/7 trajectory regression-barriers (policy_loaded + last_reconcile_pass_age_seconds + outcome="degraded") + module-docstring HEADER drift across health.py + runner.py + __init__.py + Pillar I trajectory documentation (per-tenant + middleware + X-Forwarded-For).

Pillar H Week 5 ships the **`DaemonRunner.run` async body** wiring the asyncio event loop per the Pillar H foundation's structural commitment + the per-stage worker pool **skeleton** + the per-stage **span integration** consuming `observability.traced_stage` + the **graceful-shutdown coordination** via the Week 4 `AppRunner.cleanup` contract. The four concerns this ADR resolves:

1. **The `DaemonRunner.run` body MUST be async per ADR-0060 D332's asyncio framework decision.** Week 1 declared `def run(self) -> int:` (sync stub); Week 5 changes to `async def run(self) -> int:` because the body invokes `serve_health_endpoint` (async; Week 4 body), `AppRunner.cleanup` (async), `asyncio.sleep` (per-stage tick cadence), and runs inside the asyncio event loop alongside the per-stage worker pool's `asyncio.create_task` calls at Week 6+. The signature change follows the per-pillar-foundation precedent — Week 1 stubs flip at the body week (Pillar H Week 2 `init_daemon` body, Week 3 `shutdown` body, Week 4 `serve_health_endpoint` body all followed the rename+invert pattern; Week 5 `run` body follows the same pattern at the `test_run_signature_raises_not_implemented_at_week_1` → `test_run_is_async_at_week_5` rename).

2. **The per-stage worker pool dispatch loop ships as a SKELETON at Week 5; actual concurrent dispatch via `asyncio.Semaphore` lands at Week 6+.** The Week 5 skeleton iterates over `observability._PIPELINE_STAGES` (the 8-element closed-set required by `traced_stage`'s refuse-loud at unknown values) in sorted order per ADR-0031 D140's deterministic-output contract; each per-stage tick wraps in `traced_stage` per ADR-0055 D300 + ADR-0064 D350; the loop body itself is `pass` at Week 5 (Week 6+ wires the actual per-stage dispatch via `asyncio.create_task` bounded by `asyncio.Semaphore(DaemonConfig.parallelism_limits[stage])`). The skeleton's structural purpose: pin the per-stage span integration AT TEST TIME via the binding-question coherence test `test_daemon_per_stage_spans_consume_pillar_g_traced_stage` so Week 6+ extends the body without re-litigating the Pillar G framework adoption contract.

3. **The per-stage span integration MUST consume `observability.traced_stage` per ADR-0055 D300.** The Pillar G framework adoption surfaces (OTel SDK metrics + traces + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension + READ-ONLY contract) preserve verbatim across the daemon; the Week 5 `run` body wraps each per-stage tick in `traced_stage(stage)` per the documented operator-deliberate test seam kwarg `traced_stage_fn` (default uses the production `observability.traced_stage`; tests inject spies that record per-stage invocations). The integration is the cross-pillar back-audit surface pinning the structural commitment that future Pillar I per-tenant fan-out extensions preserve the per-stage span contract.

4. **The graceful-shutdown coordination MUST release the health endpoint's `AppRunner` port via `cleanup()`.** ADR-0063 D345's `serve_health_endpoint` returns the `aiohttp.web.AppRunner` instance for the production caller (Week 5+'s `DaemonRunner.run` body) to retain. Week 5's body retains the reference via local variable + calls `await health_app_runner.cleanup()` in the `finally` clause of the tick loop's `try` block; aiohttp's documented graceful-shutdown contract waits for in-flight HTTP requests to complete before releasing the port. The coordination ensures k8s readiness probes hitting `/health` during the daemon's graceful-shutdown window receive a clean response before the daemon transitions to `"stopped"`.

Risks this ADR mitigates by design: **R037** (daemon process-restart silent state loss) PRESERVED via the lifecycle state transitions through the documented `object.__setattr__` escape hatch per ADR-0062 D342 + the per-pillar-H lifecycle is the internal allow-listed mutation site; the binding-question coherence test pins the cross-pillar surface; **R038** (health probe event-emission flood) PRESERVED via the Week 4 closure-scoped rate-limit cell at `serve_health_endpoint`; the Week 5 body retains the `AppRunner` reference but the rate-limit state is per-server closure-scoped so each daemon process has independent rate-limit; **R039** (per-Person primitive O(N) ledger walk at v2 scale) PRESERVES the Week 8-9 per-event-class indexing trajectory. The Pillar G framework adoption surfaces preserve verbatim. The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The Pillar H Week 1 + Week 1 follow-up + Week 2 + Week 2 follow-up + Week 3 + Week 3 follow-up + Week 4 + Week 4 follow-up surfaces preserve VERBATIM; Week 5 EXTENDS via `DaemonRunner.run` body + per-stage worker pool skeleton + per-stage span integration + graceful-shutdown coordination.

## Decision

### D349. `DaemonRunner.run` async body wiring the asyncio event loop — eight-step ordering + test-only seam kwargs

**Pillar H Week 5 follow-up P3-1 + NEW-1 closure** — the prior Week 5 main commit's ADR-0064 narrative said "seven-step ordering" while the docstring + comments enumerated 8 steps (Steps 1-8); this is the FIFTH micro-instance of ADR-vs-actual-impl drift in Pillar H (the FOURTH being W5 follow-up P1-1's `traced_stage(stage)` vs production `traced_stage(stage, operation)`). The W5 follow-up commit aligns ADR + docstring to "eight-step ordering" (cleanup at Step 7 + return at Step 8 are distinct because Step 7's `await health_aiohttp_runner.cleanup()` may block on in-flight HTTP requests per aiohttp's documented graceful-shutdown contract while Step 8 is the unconditional exit-code return).

`orchestrator/daemon/runner.py::DaemonRunner.run` body lands per ADR-0060 D331 + the asyncio framework decision per D332:

```python
async def run(
    self,
    *,
    attach_signal_handlers_fn: Callable | None = None,
    serve_health_endpoint_fn: Callable | None = None,
    traced_stage_fn: Callable | None = None,
    emit_fn: Callable[[dict], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    tick_seconds: float = 1.0,
    loop: Any | None = None,
) -> int:
    # Step 1: Refuse-loud if lifecycle_state != "initializing".
    if self.lifecycle_state != "initializing":
        raise RuntimeError(...)

    # Resolve test-only seam defaults (emit_fn / now_fn / attach_signal_handlers_fn /
    # serve_health_endpoint_fn / traced_stage_fn / loop).

    # Step 2: Transition initializing → ready via object.__setattr__
    # per the frozen-dataclass escape hatch per ADR-0062 D342 + the
    # Week 3 follow-up P3-1 closure (ONLY lifecycle_state mutates).
    object.__setattr__(self, "lifecycle_state", "ready")

    # Step 3: Emit daemon_started with startup_seconds = now - started_at_ts.
    emit_fn({
        "type": "daemon_started",
        **build_daemon_started_payload(
            pid=self.pid,
            version=self.version,
            config_hash=self.config_hash,
            startup_seconds=startup_seconds,
        ),
    })

    # Step 4: Wire signal handlers (SIGTERM/SIGINT/SIGHUP).
    attach_signal_handlers_fn(self, loop=loop)

    # Step 5: Start the health endpoint server + retain AppRunner reference.
    health_app_runner = await serve_health_endpoint_fn(
        self.config.health_port,
        runner=self,
    )

    # Step 6: Per-stage worker pool dispatch loop SKELETON.
    # (Pillar H Week 5 follow-up P2-1 closure removed the pre-iteration
    # sanity-tick — the first while-loop iteration covered the same
    # ground; the pre-iteration was redundant.)
    try:
        while self.lifecycle_state == "ready":
            await asyncio.sleep(tick_seconds)
            if self.lifecycle_state != "ready":
                break
            for stage in sorted(_observability._PIPELINE_STAGES):
                # Pillar H Week 5 follow-up P1-1 closure — operation
                # argument "tick" matches production
                # observability.traced_stage(stage, operation, ...)
                # signature per ADR-0054 D296. Week 6+ replaces "tick"
                # with per-stage operation names.
                with traced_stage_fn(stage, "tick"):
                    pass  # Week 6+ ships actual per-stage dispatch.
    finally:
        # Step 7: Graceful shutdown coordination per D352.
        await health_aiohttp_runner.cleanup()

    # Step 8: Return 0 on clean shutdown.
    return 0
```

The body's eight-step ordering is **structurally load-bearing** per ADR-0060 D335 invariant 3 (graceful-shutdown):
- Step 1 refuses-loud on non-initializing state per the per-pillar-H lifecycle state machine + R032 synthetic-event exclusion (a runner re-invoking run() would emit a SECOND daemon_started event diverging from the per-event-class observability primitive's stateless contract per ADR-0050 D272).
- Step 2 transitions via `object.__setattr__` per the documented Pillar H Week 3 + Week 3 follow-up P3-1 closure convention (ONLY lifecycle_state mutates through the escape hatch; the regression-barrier test `test_only_lifecycle_state_mutates_during_shutdown` pins the contract).
- Step 3 emits `daemon_started` AFTER the ready transition so a future operator reading the ledger sees `daemon_started` events correlate with the `"ready"` state.
- Step 4 wires signal handlers AFTER `daemon_started` emit so a SIGTERM arriving immediately after `daemon_started` cleanly transitions to draining without racing the emit.
- Step 5 starts the health endpoint AFTER signal handlers so k8s readiness probes hitting `/health` immediately after startup see the wired-but-not-yet-traffic state.
- Step 6 enters the per-stage tick loop AFTER the health endpoint starts so operators see the daemon's lifecycle progress in real time.
- Step 7 calls `AppRunner.cleanup()` in the `finally` block so graceful + ungraceful shutdown paths both release the port.

The body uses **operator-deliberate test seam kwargs** per the Pillar G TEST-ONLY convention + the Pillar H Week 2 / Week 3 / Week 4 precedent. Production callers omit all kwargs; tests inject spies to verify the eight-step ordering invariant + the per-stage span integration + the graceful-shutdown coordination without registering real OS signal handlers (which conflict with pytest's own signal handling), binding real HTTP ports (port contention), or wiring real OTel spans (test overhead). **Pillar H Week 5 follow-up P1-1 closure** — the `traced_stage_fn` spy MUST match production's `observability.traced_stage(stage: str, operation: str, *, attributes=None, tracer=None)` signature per ADR-0054 D296. The prior Week 5 main commit's body invoked `traced_stage_fn(stage)` with one positional argument + the spy accepted one arg; the 8 contract-level tests passed BUT the production default `traced_stage_fn=None` lazy-resolved to `observability.traced_stage` which refused-loud on missing `operation` argument — `TypeError: traced_stage() missing 1 required positional argument: 'operation'`. This was the FOURTH ADR-vs-actual-impl drift in Pillar H (W2 P3-8 OTel Resource → W3 P2-1 `_emitted_by` → W4 P2-1 framework-neutrality text → W5 P1-1 `traced_stage` signature); the W5 follow-up commit aligns the body, the spy, and the ADR.

Rejected alternatives:

* **Keep `run` synchronous + spawn an event loop internally via `asyncio.run`** — rejected. Mixing sync wrapper + async body adds GIL contention without benefit; the daemon's per-stage worker pool at Week 6+ must run on the SAME event loop as the health endpoint's `web.Application` + the signal handlers' `loop.add_signal_handler`. The async-from-top approach is the canonical asyncio pattern.
* **Use `threading.Thread` for per-stage workers instead of asyncio** — rejected. The framework decision at ADR-0060 D332 is asyncio (single-process / single-thread / cooperative scheduling). Threading adds per-thread lock complexity for the per-Person lock primitive + violates the asyncio framework contract.
* **Embed the per-stage tick loop body inline (no `traced_stage` wrap) at Week 5** — rejected. The per-stage span integration is the binding-question coherence test's scope per ADR-0064 D350; landing the wrap at Week 5 pins the cross-pillar surface AT TEST TIME so Week 6+ extends the body inside the wrap without re-litigating the Pillar G framework adoption contract.
* **Defer the body to Week 6 (same week as per-stage parallelism limits)** — rejected. The per-pillar-week trajectory at ADR-0060 D332 sequences Week 5 (run body + per-stage spans) before Week 6 (parallelism limits) so the per-week-reviewer's cell-level-matrix-coverage discipline catches signature + structural issues at Week 5 before the more complex parallelism semantics land at Week 6.

### D350. Per-stage span integration consuming `observability.traced_stage` per ADR-0055 D300

The Week 5 body's per-stage tick loop wraps each per-stage tick in `observability.traced_stage(stage, "tick")`. Iteration is over `sorted(observability._PIPELINE_STAGES)` (the 8-element closed-set per ADR-0054 D294 + ADR-0055 D300; required by `traced_stage`'s refuse-loud at unknown values).

**Pillar H Week 5 follow-up P1-1 closure** — the prior Week 5 main commit's body invoked `traced_stage_fn(stage)` with ONE positional argument while production `observability.traced_stage(stage: str, operation: str, *, attributes=None, tracer=None)` requires TWO positional arguments + refuses-loud on empty `operation` per ADR-0054 D296. The W5 follow-up commit passes the operation argument `"tick"` at the Week 5 skeleton (Week 6+ replaces with per-stage actual operation names like `"email"` for the send stage); the spy at `_run_with_spies` also gains the `operation` parameter so the per-week-reviewer's behavioral-passthrough-not-signature-only discipline catches future signature drift.

The integration is the cross-pillar surface pinning the structural commitment that:

1. The Pillar G OTel tracing initialization per ADR-0054 D294 + the per-stage span wiring per ADR-0055 D300 preserve verbatim across the daemon.
2. Future Pillar I per-tenant fan-out extensions to the per-stage worker pool wrap each per-tenant dispatch in `traced_stage` with per-tenant attributes (per the Pillar I trajectory at ADR-0060 D332).
3. The funnel CLI per-Person primitive's per-stage span consumption per ADR-0059 D325 is symmetric with the daemon's per-stage span emission per this ADR.

The `traced_stage_fn` test-only seam kwarg substitutes the production `observability.traced_stage` with a spy that records per-stage invocations + returns a `nullcontext()` (or other context manager). Tests verify the iteration order + the per-tick wrap count via the spy's records.

Rejected alternatives:

* **Use a custom span helper instead of `observability.traced_stage`** — rejected. The Pillar G framework adoption per ADR-0050 D273 is OpenTelemetry SDK; the canonical per-stage span helper is `observability.traced_stage` per ADR-0055 D300. Custom helpers would diverge from the Pillar G surface + complicate Pillar I per-tenant audit-tooling.
* **Iterate over `parallelism_limits.keys()` (7-element funnel pipeline stages) instead of `_PIPELINE_STAGES` (8-element observability stages)** — rejected. The two closed-sets are intentionally distinct per Pillar H Week 1 follow-up P3-5 closure (funnel stages = per-pipeline-event stages for the operator-observable funnel progression; observability stages = per-span dims for traced_stage). `traced_stage` refuses-loud on stages outside `_PIPELINE_STAGES`; iterating over funnel stages would cause refuse-loud on the first `queued` iteration.
* **Wrap the ENTIRE tick (not per-stage) in a single span** — rejected. The per-stage span granularity is the Pillar G per-stage dispatch contract per ADR-0055 D300; aggregating into a single tick span would lose the per-stage observability surface.

### D351. Reconcile loop integration (Pass A through O) is Week 7+ trajectory; Week 5 SKELETON loop is the test-time barrier

The Week 5 body's per-stage tick loop body is `pass` at the placeholder. The reconcile passes (Pass A through O per the existing Pillar D convention) integrate at Week 7+ per ADR-0060 D332's per-week trajectory.

The Week 5 SKELETON is the test-time barrier pinning the per-stage span integration + the lifecycle state machine + the graceful-shutdown coordination. Week 6 ships the per-stage worker pool parallelism via `asyncio.Semaphore` bounded by `DaemonConfig.parallelism_limits`; Week 7 ships the reconcile passes inside the tick loop. The SKELETON's purpose: catch signature + structural issues at Week 5 before the more complex semantics land at Weeks 6 and 7.

Rejected alternatives:

* **Bundle reconcile passes integration at Week 5** — rejected. The per-pillar-week trajectory at ADR-0060 D332 sequences Week 5 (run body + per-stage spans) before Week 7 (reconcile passes) so each week's scope is reviewable at the per-week-reviewer cadence; bundling would violate the per-pillar-foundation precedent.
* **Skip the per-stage tick loop body entirely at Week 5** — rejected. The per-stage span integration is the cross-pillar surface pinning the structural commitment; the tick loop MUST execute at least once per tick to verify the spans land at test time.
* **Use a single `await asyncio.sleep(tick_seconds)` as the loop body** — rejected. The per-stage tick is the structural commitment that scales to Week 6+ parallelism via `asyncio.Semaphore`; landing a no-op sleep would not pin the per-stage span integration.

### D352. Graceful-shutdown coordination via `AppRunner.cleanup` per the aiohttp documented contract

The Week 5 body retains the `aiohttp.web.AppRunner` reference returned by `serve_health_endpoint` (per ADR-0063 D345's return type hint + the Week 4 follow-up P3-10 closure that narrowed the type via `TYPE_CHECKING`). The `try`/`finally` block calls `await health_app_runner.cleanup()` in the `finally` clause so:

1. **Clean shutdown path** (graceful `shutdown("operator_requested")` from CLI OR `shutdown("sigterm")` from k8s pod lifecycle OR `shutdown("sigint")` from operator Ctrl+C) — the tick loop sees `lifecycle_state != "ready"` after the shutdown body transitions to `"draining"` per Pillar H Week 3 ADR-0062 D342; the `finally` block fires + cleans up the health endpoint port; the run() body returns 0.
2. **Ungraceful shutdown path** (exception inside the tick loop OR cancellation via task.cancel()) — the `finally` block still fires; the health endpoint port releases.

The aiohttp `AppRunner.cleanup()` contract waits for in-flight HTTP requests to complete before releasing the port (per aiohttp's documented graceful shutdown). k8s readiness probes hitting `/health` during the daemon's graceful-shutdown window receive a clean response before the daemon transitions to `"stopped"`.

Rejected alternatives:

* **Skip `AppRunner.cleanup()` and rely on process exit to release the port** — rejected. Process exit doesn't wait for in-flight requests; k8s readiness probes hitting `/health` during shutdown could see connection-reset errors instead of clean responses. The cleanup is the structural commitment per ADR-0060 D335 invariant 3 (graceful-shutdown).
* **Call `cleanup()` BEFORE the lifecycle state transitions to `"stopped"` (i.e., during `"draining"`)** — rejected. The `"draining"` state is the operator-readable signal that the daemon is gracefully shutting down; k8s readiness probes hitting `/health` during `"draining"` should see HTTP 503 (blocks traffic) BUT receive a clean response (not connection-reset). Calling `cleanup()` during `"draining"` would release the port mid-drain.
* **Use a separate `asyncio.Lock` to coordinate cleanup with the shutdown body** — rejected. The `try`/`finally` clause is the canonical Python pattern for cleanup; an asyncio lock adds complexity without benefit. The shutdown body's lifecycle state transitions + the run() body's lifecycle state polling are the coordination primitive.

## Consequences

The Pillar H Week 5 commit + its `DaemonRunner.run` async body + per-stage worker pool skeleton + per-stage span integration + graceful-shutdown coordination are **content-additive** at the framework boundary per the Pillar H Week 1/2/3/4 precedent. The daemon's operator-deliberate config (`DaemonConfig.health_port` + `parallelism_limits`) preserves verbatim from Week 1; Week 5 wires the body that consumes the config.

The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The Pillar G framework adoption surfaces (OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension + READ-ONLY contract) preserve VERBATIM. The Pillar H Week 1 + follow-up + Week 2 + follow-up + Week 3 + follow-up + Week 4 + follow-up surfaces preserve VERBATIM.

**TWO coherence test stubs un-skip at this Week 5 commit** (per ADR-0060 D332's trajectory):
- `TestPillarHDaemon::test_daemon_run_transitions_initializing_to_ready` — verifies `DaemonRunner.run` transitions lifecycle_state from `"initializing"` to `"ready"` + emits `daemon_started`.
- `TestPillarHDaemonObservabilityIntegration::test_daemon_per_stage_spans_consume_pillar_g_traced_stage` — verifies the daemon's per-stage tick wraps in `observability.traced_stage` for every stage in `_PIPELINE_STAGES`.

Skipped at Week 5 (un-skipping at Week 6+ per ADR-0060 D332's trajectory):
- `TestPillarHDaemon::test_sighup_triggers_policy_reload` — Week 7+.
- `TestPillarHDaemon::test_per_stage_parallelism_limit_enforced` — Week 6+.
- `TestPillarHDaemon::test_per_event_class_index_at_startup` — Week 8-9.
- `TestPillarHDaemon::test_recovers_from_kill_9_via_reconcile` — Week 11.
- `TestPillarHExitCriterion::test_daemon_24h_run_zero_anomalies_recovers_from_kill_9_reloads_policy` — Week 12.

§Downstream pillar impact across:
- **Pillar I (multi-tenant + OSS hardening)** — per-tenant fan-out wires one `DaemonRunner.run` per tenant container per ADR-0060 D335 invariant 1 + per-tenant per-stage span attributes via Pillar I trajectory extensions to `traced_stage` + per-tenant `_emitted_by` audit marker preservation + per-tenant graceful-shutdown coordination via independent `AppRunner` instances per tenant + the per-pillar mirror constants parity discipline extends to per-tenant `tenant_id` fields on lifecycle payloads.
- **Pillar J (security + compliance)** — `DaemonRunner.run` body MUST NOT expose any per-Person state in the per-stage span attributes (the `_SPAN_ATTRIBUTES_ALLOWED` closed-set per ADR-0054 D297 preserves the privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323); GDPR purge does NOT modify the run() body surface; SLSA supply-chain attestation extends to `daemon_started` emit's `_DAEMON_VERSION` constant.

§Migration/rollout — operator action: NONE for existing operators (the daemon body lands at Week 5 but the per-stage worker pool parallelism + the reconcile passes integration land at Weeks 6 + 7; operators wanting to preview the daemon at Week 5 invoke `asyncio.run(runner.run())` after `init_daemon` returns the runner). The per-stage tick loop's `tick_seconds` default (1.0s) is conservative; operators tune up at Week 6+ via a `DaemonConfig.tick_seconds` field extension (the field doesn't exist at Week 5; the kwarg is test-only-seam-injected for now).

§Existing-operator seed — operator action: NONE; recommended preview: invoke `from orchestrator.daemon import init_daemon, DaemonConfig; import asyncio; runner = init_daemon(DaemonConfig(...)); asyncio.run(runner.run())` after applying pending migrations via `python -m orchestrator.migrations`; the daemon enters the per-stage tick loop + responds to SIGTERM/SIGINT/SIGHUP signals + serves `/health` at `127.0.0.1:8080`.

Per-week-reviewer disciplines preservation across Pillar H Week 5 (compounded from Pillar F + Pillar G + Pillar H Weeks 1-4 + follow-ups):
- **Cell-level matrix coverage** — TWENTY-THREE consecutive weeks at start of Week 5 → TWENTY-FOUR after Week 5 (the new test class `TestDaemonRunBody` × 8 cells extends the discipline; 1 Week-1-stub rename+invert; the `TestPillarHDaemon` × 1 un-skip + `TestPillarHDaemonObservabilityIntegration` × 1 un-skip).
- **Behavioral-passthrough-not-signature-only** — TWENTY consecutive weeks at start of Week 5 → TWENTY-ONE after (the `_run_with_spies` helper at `TestDaemonRunBody` verifies the seven-step ordering + the per-stage span integration + the graceful-shutdown coordination behaviorally; the coherence test un-skips verify the cross-pillar surface at test time).
- **Module-level docstring drift** — TWENTY-TWO consecutive weeks at start of Week 5 → TWENTY-THREE after (runner.py + __init__.py module docstrings extended naming Week 5 + ADR-0064 + D349-D352; health.py preserves verbatim — Week 5 does NOT modify health.py).
- **Per-pillar mirror constants parity** — the SEVEN closed-sets at runner.py + the THREE at health.py preserve verbatim across Week 5; the `EMITTED_BY = "daemon"` constant from Week 3 follow-up continues to extend to the run() body's `daemon_started` emit via `build_daemon_started_payload`'s factory-boundary stamp.
- **Cross-pillar back-audit** — the audit-vs-actual-API drift discipline (Week 1 follow-up `TestMigrationRunnerContract`) + the ADR-vs-actual-impl drift discipline (Week 2 follow-up P3-8 + Week 3 follow-up P2-1 + Week 4 follow-up P2-1) BOTH preserve verbatim; the Week 5 author verifies ADR-0064 narrative claims match the actual run() body's behavior + the per-stage span integration + the graceful-shutdown coordination before commit.
- **Framework-neutrality contract** — Week 5's `DaemonRunner.run` body uses test-only seam kwargs (`attach_signal_handlers_fn` + `serve_health_endpoint_fn` + `traced_stage_fn` + `emit_fn` + `now_fn` + `tick_seconds` + `loop`) per the Pillar G TEST-ONLY convention + Pillar H Week 2-4 precedent; the framework-neutrality contract is two-tiered per Pillar H Week 4 follow-up P2-1 closure (seam kwargs substitute BACKENDS; operators wanting alternative concurrency models — gevent / trio / threading — MUST fork the function body per the per-pillar-H precedent).
- **Privacy invariant** — `DaemonRunner.run` body does NOT expose any per-Person state; the per-stage span attributes are limited to the `_SPAN_ATTRIBUTES_ALLOWED` closed-set per ADR-0054 D297; `TestComputeHealthStatus::test_privacy_invariant_excludes_person_id_body_source_list` regression-barrier preserves verbatim.

## References

- **ADR-0063** (Pillar H Week 4 — serve_health_endpoint body + health_probe rate-limit + per-pillar-H Grafana panel + aiohttp dep). D345-D348. **D345's `AppRunner` return type is the structural commitment Week 5's run() body retains for graceful-shutdown cleanup per D352; the Week 4 follow-up P3-10 closure's TYPE_CHECKING import of `AppRunner` is consumed by Week 5's run() body return type chain.**
- **ADR-0062** (Pillar H Week 3 — signal handler + shutdown bodies). D341-D344. **D342's `object.__setattr__` frozen-dataclass escape hatch + Week 3 follow-up P3-1 closure (ONLY lifecycle_state mutates) extends to Week 5's `run()` body's initializing→ready transition + the per-pillar-H lifecycle state machine.**
- **ADR-0061** (Pillar H Week 2 — init_daemon body + EVENT_CLASS_CATALOG extension + build_daemon_started_payload factory). D337-D340. **D339's `build_daemon_started_payload` raw-primitive factory + Week 2 follow-up P2-2 closure on input validation + Week 3 follow-up P2-1 closure on `_emitted_by` audit marker stamping at factory boundary all extend to Week 5's `daemon_started` emit at Step 3 of the run() body.**
- **ADR-0060** (Pillar H foundation). D331-D336. **D331's `DaemonRunner.run` signature + D332's asyncio framework decision + per-week trajectory table sequencing Week 5 (run body + per-stage spans) before Week 6 (parallelism limits) + Week 7 (reload_policy + reconcile passes) is the structural commitment Week 5 fulfills via the body; D335 invariant 3 graceful-shutdown structural commitment is OPERATIONAL via Week 5's `try`/`finally` block + `AppRunner.cleanup()`.**
- **ADR-0059** (Pillar G Week 12 — binding exit-criterion + funnel CLI extension + READ-ONLY contract). D325-D330. **The funnel CLI READ-ONLY contract preserves verbatim across Week 5; the daemon's per-stage tick loop does NOT modify funnel CLI surfaces.**
- **ADR-0055** (Pillar G Week 6 — per-stage span wiring). D300. **The `observability.traced_stage` helper is the canonical per-stage span surface; Week 5's `run()` body wraps each per-stage tick in `traced_stage(stage)` per D350.**
- **ADR-0054** (Pillar G Week 5 — OTel TracerProvider initialization). D294-D298. **The OTel `TracerProvider` initialization per D294 + the `_PIPELINE_STAGES` 8-element closed-set per ADR-0055 D300 + the `_SPAN_ATTRIBUTES_ALLOWED` closed-set per D297 all preserve verbatim across Week 5; `traced_stage` refuses-loud on stages outside `_PIPELINE_STAGES`.**
- **ADR-0050** (Pillar G Week 1 foundation). D272-D277. **D272's stateless contract preserves — the daemon's run() body emits `daemon_started` via the `Ledger.append` surface NOT a per-instance counter; D276(b) privacy invariant per I8 preserves at the per-stage span attribute boundary.**
- **ADR-0031** (Pillar D Week 12 — funnel CLI deterministic-output contract). D140. **The Week 5 body's per-stage tick iterates over `sorted(_PIPELINE_STAGES)` per the determinism contract; `startup_seconds` rounded to 3 dp per the existing factory convention.**
- **ADR-0014** (Pillar C foundation — channel-on-every-event invariant). D33. **The `daemon_started` payload OMITS the `channel` field per the daemon-lifecycle-events-are-tenant-process-scoped rationale (mirrors Pillar H Week 2-4 factories).**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17. **The factory boundary `_emitted_by` stamping per Week 3 follow-up P2-1 closure preserves at Week 5's `daemon_started` emit.**
- **ADR-0001** (Pillar A foundation — declarative policy engine). D2 (refuse-loud convention). **Step 1's `lifecycle_state != "initializing"` refuse-loud per the framework convention.**
- `.planning/REVIEW-pillar-h-surface-audit.md` — cross-pillar surface audit; §26 NEW Week 5 extension (gitignored).
- `.planning/HANDOFF-pillar-h-week-5.md` — Pillar H Week 5 close summary + handoff to Pillar H Week 6 (this commit; gitignored).
- `docs/PILLAR-PLAN.md` §2 Pillar H + §6 Pillar H row Week 5 status flip + Notes column appended Week 5 close summary.
- `orchestrator/daemon/runner.py` (Week 5 body) — `DaemonRunner.run` async body + module docstring extension naming Week 5.
- `orchestrator/daemon/__init__.py` — module docstring extension naming Week 5.
- `tests/test_daemon.py` — Week 1 stub `test_run_signature_raises_not_implemented_at_week_1` RENAMED + INVERTED to `test_run_is_async_at_week_5` per the per-pillar-foundation precedent; NEW `TestDaemonRunBody` × 8 + `_StubAppRunner` helper. Net new tests: +8 (176 → 184 contract-level tests; TWO additional un-skipped via coherence test extension).
- `tests/test_multi_channel_coherence.py` — TWO stubs un-skipped (`test_daemon_run_transitions_initializing_to_ready` + `test_daemon_per_stage_spans_consume_pillar_g_traced_stage`).
- `docs/adr/README.md` — ADR-0064 row added.
- `docs/SOURCES-OF-TRUTH.md` — daemon-state row Week 5 ADR-0064 reference.

## Pillar H Week 5 follow-up addendum

The Pillar H Week 5 follow-up commit (1 P1 + 4 P2 + 9 P3 + 6 NEW addressed; 1 NEW REFUTED) closes per-week-reviewer findings on commit `4cd4515`. **The structural value of the per-week-reviewer pattern compounds at Pillar H Week 5: TWENTY-FIVE consecutive weeks of cell-level-matrix-coverage discipline + behavioral-passthrough-not-signature-only discipline + ADR-vs-actual-impl drift discipline — the FOURTH ADR-vs-actual-impl drift in Pillar H (W2 P3-8 + W3 P2-1 + W4 P2-1 + W5 P1-1) was caught at Week 5 + the FIRST P1 escalation in Pillar H reflects that the spy-signature-mismatch broke the framework-neutrality contract in a way the prior drift findings did not.**

The closures are content-additive in the spirit of ADR-0064's existing decisions per the per-pillar-foundation precedent (Pillar G Week 12 follow-up `43612a8` + Pillar H Week 1 follow-up `452d7ae` + Week 2 follow-up `9954fd5` + Week 3 follow-up `bdbde52` + Week 4 follow-up `4c0f4dd`). ZERO new ADRs.

- **P1-1** (`traced_stage(stage)` vs production `traced_stage(stage, operation)` signature drift) CLOSED via `orchestrator/daemon/runner.py` body invokes `traced_stage_fn(stage, "tick")` + `tests/test_daemon.py::TestDaemonRunBody._run_with_spies` spy gains `operation` parameter + NEW `test_per_stage_tick_invokes_production_traced_stage_signature_per_w5_followup_p1_1` behavioral-passthrough regression-barrier exercising the production `observability.traced_stage` default (via the OTel SDK's no-op posture per ADR-0054 D294's safe-default contract) + ADR-0064 D350 narrative + the Week 5 follow-up cross-references in this addendum.
- **P2-1** (pre-iteration sanity-tick redundancy with the while-loop iteration) CLOSED via removal of the pre-iteration; the test `test_per_stage_tick_wraps_each_pipeline_stage_in_traced_stage` still pins the per-tick first-8-stages assertion via the first while-loop iteration; ADR-0064 D349 example code updated.
- **P2-2** (cleanup-on-exception regression-barrier gap for the ungraceful-shutdown path) CLOSED via NEW `test_calls_health_endpoint_cleanup_on_exception_path` injecting a `traced_stage_fn` that raises RuntimeError mid-tick + asserts `_StubAppRunner.cleanup_called is True` despite the exception propagating out of `run()`.
- **P2-3** (`tick_seconds <= 0` boundary refuse-loud) CLOSED via `if tick_seconds <= 0: raise ValueError(...)` at top of `run()` + NEW `test_tick_seconds_zero_raises_value_error` + `test_tick_seconds_negative_raises_value_error` regression-barriers; matches the Pillar H Week 2 follow-up P2-1 closure's per-tier-invariant-field discipline.
- **P2-4** (`asyncio.get_running_loop()` cryptic-error) CLOSED via try/except wrap that raises operator-readable RuntimeError naming `asyncio.run(runner.run())` invocation pattern + NEW `test_run_outside_asyncio_loop_raises_operator_readable_error` regression-barrier.
- **P3-1 + NEW-1** (seven-step vs eight-step ordering drift across ADR + docstring + comments + commit message) CLOSED via ADR-0064 D349 + the body's docstring + comments all aligned to "eight-step ordering".
- **P3-2** (`_StubAppRunner` duplicated three times — at `tests/test_daemon.py:2967` + `tests/test_multi_channel_coherence.py:9306` + `tests/test_multi_channel_coherence.py:9475`) CLOSED via promotion to shared `tests/_daemon_test_helpers.py` module per the W3 follow-up P3-6 closure's DRY discipline.
- **P3-3** (`started_at_ts="2020-01-01T00:00:00.000Z"` magic constant) CLOSED via `_TEST_PAST_STARTED_AT_TS` named constant at `tests/_daemon_test_helpers.py` with docstring naming the past-date determinism requirement.
- **P3-4** (`loop: Any | None = None` type hint) CLOSED via narrowed type hint to `loop: asyncio.AbstractEventLoop | None = None` mirroring the W4 follow-up P3-10 closure's TYPE_CHECKING narrowing of `serve_health_endpoint` return type.
- **P3-5** (`health_app_runner` variable name conflicts with the `runner` parameter) CLOSED via rename to `health_aiohttp_runner` so operators see the aiohttp.web.AppRunner instance is distinct from the DaemonRunner `self`.
- **P3-6 + NEW-3 + NEW-4** (lazy imports of `Ledger` + `observability` + `serve_health_endpoint` inside `run()` body) CLOSED via module-top `from orchestrator.ledger import Ledger` + `from orchestrator import observability as _observability` (`orchestrator.daemon.health` MUST stay lazy per the W4 follow-up NEW-1 circular-import-avoidance pattern — health.py imports `EMITTED_BY` + `DAEMON_LIFECYCLE_STATES` from runner.py at function bodies).
- **P3-7** (`_PIPELINE_STAGES` leading underscore consumed cross-module) DEFERRED — documented at the import-site comment + module docstring naming Pillar I per-tenant fan-out trajectory where the per-pillar-G public-API rename would coordinate; the leading-underscore-consumed-across-modules is an established convention at this codebase (mirror parity discipline accepts).
- **P3-8** (`emit_fn` Ledger lazy-construction trajectory documentation) CLOSED via docstring sentence naming the once-per-`run()`-call construction posture + the Pillar I per-tenant fan-out trajectory (one `run()` per tenant container per ADR-0060 D335 invariant 1, so each tenant's Ledger is independently constructed).
- **P3-9** (`orchestrator/daemon/health.py` module-docstring drift — Week 5 not named at materially-unchanged module per the W3 follow-up P3-5 closure's scope extension to per-pillar-package materially-unchanged modules) CLOSED via health.py module-docstring extension naming Week 5 + Week 5 follow-up.
- **NEW-2** (`startup_seconds` rounding concern at body vs factory boundary) **REFUTED** — the `build_daemon_started_payload` factory at `orchestrator/daemon/runner.py:1335` already rounds `startup_seconds` to 3 dp at the factory boundary per ADR-0031 D140's determinism contract; the body's unrounded `total_seconds()` is consumed by the factory's rounding step. The W5 follow-up commit adds a comment at the body site naming the REFUTATION so future reviewers don't re-litigate.
- **NEW-5** (run()-side regression-barrier for `object.__setattr__` escape-hatch — the W3 follow-up P3-1 closure added `test_only_lifecycle_state_mutates_during_shutdown` at the shutdown side but no equivalent existed at the run() side) CLOSED via NEW `test_only_lifecycle_state_mutates_during_run_per_w5_followup_new_5` mirroring the W3 closure's discipline at the run() body's Step 2 transition.
- **NEW-6** (`asyncio.CancelledError` propagation documentation gap) CLOSED via docstring `Raises` section extension naming the `finally` block's cleanup guarantee under task.cancel() per asyncio's documented cancellation semantics.

Per-week-reviewer disciplines status after follow-up: **cell-level matrix coverage TWENTY-FIVE consecutive weeks** (Pillar F W6-W12 + Pillar G W2-W12 + W12 follow-up + Pillar H W1 follow-up + Pillar H W2 + W2 follow-up + W3 + W3 follow-up + W4 + W4 follow-up + W5 + W5 follow-up; +6 net new daemon contract tests 184 → 190) + **behavioral-passthrough-not-signature-only TWENTY-TWO consecutive weeks** (the test_per_stage_tick_invokes_production_traced_stage_signature_per_w5_followup_p1_1 regression-barrier exercises production traced_stage at test time NOT just the spy seam — the exact failure mode the discipline exists to catch) + **module-level docstring drift TWENTY-FOUR consecutive weeks** (runner.py + __init__.py + health.py module docstrings ALL extended naming Week 5 follow-up per the W3 follow-up P3-5 closure's materially-unchanged-module scope extension) + **per-pillar mirror constants parity** SEVEN closed-sets at runner.py + THREE at health.py preserve verbatim + **cross-pillar back-audit** the FOURTH ADR-vs-actual-impl drift in Pillar H surfaced + closed (W2 P3-8 + W3 P2-1 + W4 P2-1 + W5 P1-1) + **framework-neutrality contract** RESTORED (the seam-kwargs path is now production-default-compatible; operators wanting alternative concurrency models still MUST fork the run() body per the W4 follow-up P2-1 two-tiered seam-vs-fork distinction) + **privacy invariant** PRESERVED (the per-stage span attribute closed-set per ADR-0054 D297 + the daemon's lifecycle payload exclusion of person_id/body/source_list preserve verbatim).

The Pillar D + E + F + G binding exit-criterion tests STAY GREEN across the W5 follow-up. The Pillar G framework adoption surfaces preserve VERBATIM. The Pillar H Weeks 1-5 surfaces preserve VERBATIM; the follow-up only EXTENDS via the closure categories per the per-pillar-foundation precedent.
