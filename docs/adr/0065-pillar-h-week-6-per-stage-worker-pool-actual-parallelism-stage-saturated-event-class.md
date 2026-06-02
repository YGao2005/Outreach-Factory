# ADR-0065: Pillar H Week 6 — Per-stage worker pool actual parallelism via `asyncio.Semaphore` bounded by `DaemonConfig.parallelism_limits` + NEW `daemon_stage_saturated` event class + funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations

- **Status:** Accepted
- **Date:** 2026-05-27
- **Pillar:** H (Daemon + dispatcher — Week 6 per-stage worker pool actual parallelism + backpressure semantics + per-stage saturation event class)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0060 (Pillar H Week 1 foundation, D331-D336) pinned the daemon primitive shape; ADR-0061 (Pillar H Week 2, D337-D340) shipped `init_daemon` body + `EVENT_CLASS_CATALOG` extension + `build_daemon_started_payload`; ADR-0062 (Pillar H Week 3, D341-D344) shipped `attach_signal_handlers` body + `DaemonRunner.shutdown` body + stopping/stopped emit factories + `SHUTDOWN_REASONS` / `DAEMON_EXIT_REASONS` closed-sets; ADR-0063 (Pillar H Week 4, D345-D348) shipped `serve_health_endpoint` body + `health_probe` rate-limit + per_daemon.yml Grafana panel + NEW aiohttp dependency; ADR-0064 (Pillar H Week 5, D349-D352) shipped `DaemonRunner.run` async body wiring the asyncio event loop + per-stage worker pool SKELETON + per-stage span integration via `observability.traced_stage` + graceful-shutdown coordination via `AppRunner.cleanup`. The Pillar H Week 5 follow-up commit `544e5d5` shipped 1 P1 + 4 P2 + 9 P3 + 6 NEW reviewer findings closures (the per-week-reviewer pattern at TWENTY-FIVE consecutive weeks at start of Pillar H Week 6); the Week 5 follow-up closed the FOURTH ADR-vs-actual-impl drift in Pillar H — production `observability.traced_stage(stage, operation, ...)` signature alignment + `traced_stage_fn(stage, "tick")` body fix + spy signature widening + behavioral-passthrough regression-barrier + ADR-0064 D349 narrative "seven-step" → "eight-step ordering" alignment + 14 other closures.

Pillar H Week 6 ships the **per-stage worker pool actual parallelism** via `asyncio.Semaphore` bounded by `DaemonConfig.parallelism_limits[stage]` per the per-FUNNEL-stage granularity + NEW `daemon_stage_saturated` event class + factory + EVENT_CLASS_CATALOG extension (5 → 6 elements) + funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations. The three concerns this ADR resolves:

1. **The per-stage worker pool body MUST enforce `DaemonConfig.parallelism_limits` via `asyncio.Semaphore` per stage.** Week 5 shipped the SKELETON — the body's tick loop iterated over `_PIPELINE_STAGES` (observability stages) with `pass` body. Week 6 wires the actual concurrent dispatch substrate via `asyncio.Semaphore(parallelism_limits[stage])` per FUNNEL stage (one Semaphore per stage in `_PILLAR_G_PIPELINE_STAGES`; the Semaphore is the structural commitment that scales to Week 7+'s actual per-stage dispatch via `async with sem: dispatch_fn(stage)`). The semaphores are constructed once at `run()` startup as a new **Step 5.5** (after Step 5's start-health-endpoint + before Step 6's tick loop entry; the construction site is between Steps 5 and 6 because the per-stage worker pool depends on the runner being fully initialized through the prior steps — refuse-loud check (Step 1) + lifecycle transition (Step 2) + daemon_started emit (Step 3) + signal handler wiring (Step 4) + health endpoint start (Step 5) — before the per-stage worker pool tick loop fires). They're scoped to the run() invocation per the per-tenant fan-out invariant per ADR-0060 D335 invariant 1 (one daemon process per tenant container; one set of Semaphores per daemon process; per-tenant isolation by construction).

   **Pillar H Week 6 follow-up P2-2 closure** — the prior D353 narrative said "after Step 1's refuse-loud + Step 2's lifecycle transition + before Step 6's tick loop entry" while the code example below + the actual body construct AFTER Step 5 (start health endpoint), NOT after Step 2. The narrative-vs-code-example INTERNAL drift is the **FIFTH ADR-vs-actual-impl drift in Pillar H** caught by the per-week-reviewer's cross-pillar back-audit discipline (the prior four: W2 P3-8 OTel Resource rationale; W3 P2-1 `_emitted_by` audit-marker; W4 P2-1 framework-neutrality text; W5 P1-1 `traced_stage` signature). The W6 follow-up commit aligns the narrative to "after Step 5's start-health-endpoint + before Step 6's tick loop entry" matching the code example + the body's actual placement; the per-pillar-week-reviewer pattern's structural value compounds at FIVE consecutive Pillar H weeks of ADR-vs-actual-impl drift catches.

2. **Funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations.** The Pillar H Week 1 follow-up P3-5 closure established the `funnel._PILLAR_G_PIPELINE_STAGES` (7 elements: `queued` / `researched` / `drafted` / `ready` / `sent` / `replied` / `outcome_terminal`) vs `observability._PIPELINE_STAGES` (8 elements: `discovery` / `enrichment` / `research` / `draft` / `review` / `send` / `reply` / `win_loss`) as INTENTIONALLY DISTINCT closed-sets — funnel stages track per-Person funnel progression (the operator-observable per-pipeline-event stage transitions); observability stages track per-span dims (the pipeline operations regardless of which prospect they're applied to). Week 6's per-stage worker pool is bounded by `DaemonConfig.parallelism_limits` whose keys correspond to FUNNEL stages (per ADR-0060 D331 + Week 2 follow-up P2-1 closure's `_validate_config` refuse-loud on key mismatch). Week 5's per-stage span loop iterates OBSERVABILITY stages. The Week 6 body ships TWO ORTHOGONAL per-tick iterations rather than a 1-to-many mapping table (rejected: the `researched` funnel stage conceptually spans both `enrichment` + `research` observability stages — a mapping would require operator-arbitrary disambiguation; cleaner to preserve the orthogonal closed-sets).

3. **NEW `daemon_stage_saturated` event class signals per-stage backpressure to operators.** When a per-funnel-stage `asyncio.Semaphore` is exhausted (all slots acquired), the daemon's tick loop emits `daemon_stage_saturated` per stage per tick. Operators consume via the Pillar H Grafana panel 2 placeholder at `infra/grafana/dashboards/per_daemon.yml` (currently `outreach_factory_events_total{event_class="daemon_stage_saturated"} or vector(0)` per ADR-0063 D347); the Week 6 commit completes the panel 2 placeholder consumer + the Week 6 author updates the dashboard YAML threshold from `>0` red to operator-tunable. The event class joins `DAEMON_NEW_EVENT_CLASSES` (5 → 6) + `EVENT_CLASS_CATALOG` (extends the Week 2 ADR-0061 D338 catalog extension via the same per-pillar locality convention) + NEW `build_daemon_stage_saturated_payload(pid, stage, parallelism_limit, in_flight_count) -> dict` raw-primitive emit-shape factory per the Pillar H Week 3 follow-up P2-1 closure's `_emitted_by="daemon"` factory-boundary stamp.

Risks this ADR mitigates by design: **R037** (daemon process-restart silent state loss) PRESERVED via lifecycle state transitions through `object.__setattr__` per ADR-0062 D342 + W3 follow-up P3-1; **R038** (health probe event-emission flood) PRESERVED via Week 4 closure-scoped rate-limit; **R039** (per-Person primitive O(N) ledger walk at v2 scale) PRESERVES the Week 8-9 per-event-class indexing trajectory. The Pillar G framework adoption surfaces preserve verbatim — the per-stage span integration via `observability.traced_stage(stage, "tick")` from the Week 5 follow-up P1-1 closure preserves at Week 6 (the per-observability-stage span loop continues to iterate over `_PIPELINE_STAGES`; the per-funnel-stage worker pool loop is orthogonal). The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The Pillar H Weeks 1-5 + 5 follow-ups surfaces preserve VERBATIM; Week 6 EXTENDS via per-stage worker pool actual parallelism + `daemon_stage_saturated` event class + factory + catalog extension + funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations.

## Decision

### D353. Per-stage worker pool actual parallelism via `asyncio.Semaphore` bounded by `DaemonConfig.parallelism_limits[stage]` at the FUNNEL stage granularity

`orchestrator/daemon/runner.py::DaemonRunner.run` body extends Step 6 with per-stage Semaphore construction + per-funnel-stage worker pool tick:

```python
# After Step 5 (start health endpoint), BEFORE Step 6 (per-stage tick loop):
# Construct per-funnel-stage Semaphores bounded by parallelism_limits.
from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES
stage_semaphores: dict[str, asyncio.Semaphore] = {
    stage: asyncio.Semaphore(self.config.parallelism_limits[stage])
    for stage in _PILLAR_G_PIPELINE_STAGES
}

# Step 6: per-stage tick loop with TWO ORTHOGONAL iterations.
try:
    while self.lifecycle_state == "ready":
        await asyncio.sleep(tick_seconds)
        if self.lifecycle_state != "ready":
            break

        # 6a. Per-observability-stage span tick (Week 5 contract preserved).
        for stage in sorted(_observability._PIPELINE_STAGES):
            with traced_stage_fn(stage, "tick"):
                pass  # Week 7+ ships actual per-stage dispatch.

        # 6b. Per-funnel-stage worker pool tick (Week 6 NEW).
        for stage in sorted(_PILLAR_G_PIPELINE_STAGES):
            sem = stage_semaphores[stage]
            if sem.locked():
                # Saturation backpressure signal per D355.
                emit_fn({
                    "type": "daemon_stage_saturated",
                    **build_daemon_stage_saturated_payload(
                        pid=self.pid,
                        stage=stage,
                        parallelism_limit=self.config.parallelism_limits[stage],
                        in_flight_count=self.config.parallelism_limits[stage],
                    ),
                })
                continue
            # Week 6 SKELETON — actual per-stage dispatch lands at Week 7+.
            # Week 7+ extends with: async with sem: await dispatch_fn(stage)
            # The Semaphore is the structural commitment + the operator-
            # deliberate parallelism contract per ADR-0060 D331.
finally:
    await health_aiohttp_runner.cleanup()
```

The body's structural commitments:

* **Semaphore-per-stage isolation** — one Semaphore per funnel stage; per-stage saturation is independent (e.g., `sent` stage saturated does NOT block `queued` stage dispatch).
* **Operator-deliberate parallelism limits** — `DaemonConfig.parallelism_limits[stage]` is operator-deliberate per ADR-0060 D331 + Week 1 follow-up P3-1/P3-5 docstring extension naming send-side vs receive-side semantics + Week 2 follow-up P2-1 closure's refuse-loud rules (parallelism_limits ≥ 1 per stage at `_validate_config`).
* **Per-tick saturation signal** — operators see `daemon_stage_saturated` emits at the same per-tick cadence as the per-stage span emits; the cross-pillar back-audit discipline carries (the W3 follow-up P2-1 closure's `_emitted_by="daemon"` factory-boundary stamp extends to `build_daemon_stage_saturated_payload` per D355).
* **No-op posture at Week 6 SKELETON** — the actual per-stage dispatch body (`async with sem: dispatch_fn(stage)`) lands at Week 7+ per ADR-0060 D332's per-week trajectory. At Week 6, `sem.locked()` will only be True if a test injects a pre-acquired Semaphore (the regression-barrier exercises this). In production at Week 6, no actual dispatch happens, so `sem.locked()` returns False at every tick + `daemon_stage_saturated` does NOT emit. The structural commitment is the SCAFFOLDING — Week 7+ adds the dispatch.

Rejected alternatives:

* **Use `threading.Semaphore` instead of `asyncio.Semaphore`** — rejected. The asyncio framework decision per ADR-0060 D332 requires asyncio primitives; threading.Semaphore would not cooperate with the asyncio event loop.
* **Single shared Semaphore across all stages (one global limit)** — rejected. Operators want per-stage tuning (e.g., `sent` stage's per-channel rate-limit at Pillar A is the dominant constraint; `queued` stage's discovery I/O is a different constraint).
* **Construct Semaphores at module-load-time (class-level field)** — rejected. The Semaphore's value is per-config (operators override `parallelism_limits` at DaemonConfig construction); per-instance construction at `run()` startup is the correct scope.
* **Defer to Week 7+ when actual dispatch lands** — rejected. The per-pillar-week trajectory at ADR-0060 D332 sequences Week 6 (parallelism limits + backpressure) before Week 7 (reload_policy + reconcile passes). Week 6's SKELETON is the test-time barrier pinning the per-stage Semaphore contract + the `daemon_stage_saturated` event class shape before Week 7's actual dispatch.

### D354. Funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations

The Pillar H Week 1 follow-up P3-5 closure established `funnel._PILLAR_G_PIPELINE_STAGES` (7 elements) vs `observability._PIPELINE_STAGES` (8 elements) as intentionally distinct closed-sets. Week 6's per-stage worker pool is bounded by `parallelism_limits` (whose keys correspond to FUNNEL stages); Week 5's per-stage span loop iterates OBSERVABILITY stages. The Week 6 body ships TWO ORTHOGONAL per-tick iterations:

* **Iteration 6a (Week 5 preserved)** — `for stage in sorted(_observability._PIPELINE_STAGES): with traced_stage_fn(stage, "tick"): pass`. Per-tick produces 8 per-span wraps.
* **Iteration 6b (Week 6 NEW)** — `for stage in sorted(_PILLAR_G_PIPELINE_STAGES): if semaphore.locked() → emit daemon_stage_saturated; else pass (Week 7+ ships dispatch)`. Per-tick produces up-to-7 saturation emits.

The cross-pillar coherence test `test_daemon_per_stage_spans_consume_pillar_g_traced_stage` continues to verify all 8 observability stages are wrapped in `traced_stage` per tick (the Week 5 contract preserves verbatim). The NEW coherence test `test_per_stage_parallelism_limit_enforced` un-skipped at Week 6 verifies the per-funnel-stage Semaphore bounds + the `daemon_stage_saturated` emit on saturation.

The orthogonal-iterations design preserves the structural independence of the two closed-sets; future Pillar I per-tenant fan-out extensions to both surfaces (per-tenant per-funnel-stage parallelism + per-tenant per-observability-stage spans) extend each iteration independently without coupling.

Rejected alternatives:

* **1-to-many mapping table** (funnel stage → observability stage) — rejected. The `researched` funnel stage conceptually spans both `enrichment` + `research` observability stages; an arbitrary mapping would introduce operator-confusing asymmetry. The orthogonal-iterations design is cleaner.
* **Unify the two closed-sets** (drop one in favor of the other) — rejected. The Pillar G framework adoption per ADR-0054 D294 requires `_PIPELINE_STAGES` for `traced_stage`'s refuse-loud; the Pillar G funnel CLI per ADR-0031 D140 requires `_PILLAR_G_PIPELINE_STAGES` for per-pipeline-event stage progression. They serve distinct purposes.
* **Iterate over `parallelism_limits.keys()` for BOTH iterations** (drop the observability per-stage span loop) — rejected. The Pillar G framework adoption surface preservation per the per-pillar-foundation precedent requires the per-observability-stage span loop to preserve verbatim across the daemon.

### D355. NEW `daemon_stage_saturated` event class + factory + DAEMON_NEW_EVENT_CLASSES extension (5 → 6) + EVENT_CLASS_CATALOG extension

The NEW `daemon_stage_saturated` event class joins:

* `orchestrator/daemon/runner.py::DAEMON_NEW_EVENT_CLASSES` (5 → 6 elements; the per-pillar closed-set per the Pillar H Week 2 ADR-0061 D338's locality convention).
* `orchestrator/observability.py::EVENT_CLASS_CATALOG` (24 → 25 elements; the cross-pillar catalog per the Pillar H Week 2 catalog-extension pattern + the Week 1 follow-up P3-5 closure's per-pillar locality convention).

NEW factory at `orchestrator/daemon/runner.py`:

```python
def build_daemon_stage_saturated_payload(
    *, pid: int, stage: str, parallelism_limit: int, in_flight_count: int,
) -> dict:
    """Build the daemon_stage_saturated event payload per ADR-0065 D355.

    Refuse-loud at factory boundary per the Pillar H Week 2 follow-up
    P2-2 closure convention. Factory stamps _emitted_by="daemon" per
    the Pillar H Week 3 follow-up P2-1 closure's factory-boundary
    audit-marker discipline.
    """
    # POSIX pid > 0
    if pid <= 0:
        raise ValueError(...)
    # stage MUST be in _PILLAR_G_PIPELINE_STAGES (funnel stages; refuses
    # observability stages or unknown values per the Week 1 follow-up
    # P3-5 closure's two-closed-sets distinction).
    if stage not in _PILLAR_G_PIPELINE_STAGES:
        raise ValueError(...)
    # parallelism_limit >= 1 per Week 2 follow-up P2-1 closure.
    if parallelism_limit < 1:
        raise ValueError(...)
    # in_flight_count ∈ [0, parallelism_limit].
    if not (0 <= in_flight_count <= parallelism_limit):
        raise ValueError(...)
    return {
        "pid": pid,
        "stage": stage,
        "parallelism_limit": parallelism_limit,
        "in_flight_count": in_flight_count,
        "_emitted_by": EMITTED_BY,  # "daemon" per W3 follow-up P2-1
    }
```

The factory output is a 5-key dict (pid + stage + parallelism_limit + in_flight_count + _emitted_by); OMITS `channel` per ADR-0014 D33 (daemon lifecycle events are tenant-process-scoped NOT per-channel; per-channel saturation would be a separate Pillar C concern); OMITS `ts` + `type` per the Pillar H Week 3 follow-up P2-1 closure correction (the framework's `Ledger.append` only auto-fills `setdefault("v")` + `setdefault("ts")`; the `type` field is set by the caller per the existing emit convention).

Operators consume via:

* The Pillar H Grafana panel 2 placeholder at `infra/grafana/dashboards/per_daemon.yml` (the placeholder consumer goes live at Week 6 commit — the `or vector(0)` fallback no longer fires when actual saturation events exist in the ledger).
* The funnel CLI per ADR-0059 D325's READ-ONLY contract (operators query `python orchestrator/funnel.py status` to see per-stage saturation counts in the 24h window).
* Future Pillar I per-tenant audit-tooling filters by `_emitted_by="daemon"` + `tenant_id` (Pillar I trajectory).

Rejected alternatives:

* **Add saturation as a per-stage span attribute** instead of a separate event class — rejected. The per-stage span surface per ADR-0054 D297 has a closed-set of allowed attributes; adding `saturated: bool` would extend that closed-set + couple the per-stage span surface to the per-funnel-stage parallelism semantics. Cleaner to keep them orthogonal.
* **Per-stage saturation as a Prometheus counter** instead of a ledger event — rejected. The ledger-event-class pattern per ADR-0050 D272 + the per-pillar mirror constants parity discipline per Pillar H Week 1 + the cross-pillar back-audit discipline + the per-Person observability surface adapter pattern all extend uniformly to `daemon_stage_saturated`. A Prometheus-only counter would lose the ledger-as-SoT property per I1.
* **Single `daemon_backpressure_signal` event class with `(stage, kind)` discriminator** — rejected. The closed-set discipline per ADR-0050 D272's R031-shape mitigation pattern favors per-event-class shapes over discriminated unions; the cell-level matrix coverage discipline catches per-event-class shape drift at test time.

## Consequences

The Pillar H Week 6 commit + its per-stage worker pool actual parallelism + `daemon_stage_saturated` event class + factory + catalog extension + funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations are **content-additive** at the framework boundary per the Pillar H Week 1-5 precedent. The daemon's operator-deliberate config (`DaemonConfig.parallelism_limits` per ADR-0060 D331) preserves verbatim from Week 1; Week 6 wires the body that consumes the config.

The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The Pillar G framework adoption surfaces (OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension + READ-ONLY contract) preserve VERBATIM. The Pillar H Week 1 + follow-up + Week 2 + follow-up + Week 3 + follow-up + Week 4 + follow-up + Week 5 + follow-up surfaces preserve VERBATIM.

**ONE coherence test stub un-skips at this Week 6 commit** (per ADR-0060 D332's trajectory):
- `TestPillarHDaemon::test_per_stage_parallelism_limit_enforced` — verifies per-funnel-stage `asyncio.Semaphore` bounded by `parallelism_limits[stage]` + `daemon_stage_saturated` emit on saturation.

Skipped at Week 6 (un-skipping at Week 7+ per ADR-0060 D332's trajectory):
- `TestPillarHDaemon::test_sighup_triggers_policy_reload` — Week 7+.
- `TestPillarHDaemon::test_per_event_class_index_at_startup` — Week 8-9.
- `TestPillarHDaemon::test_recovers_from_kill_9_via_reconcile` — Week 11.
- `TestPillarHExitCriterion::test_daemon_24h_run_zero_anomalies_recovers_from_kill_9_reloads_policy` — Week 12.

§Downstream pillar impact across:
- **Pillar I (multi-tenant + OSS hardening)** — per-tenant fan-out wires one Semaphore-per-funnel-stage set per tenant container per ADR-0060 D335 invariant 1 + per-tenant `parallelism_limits` per `DaemonConfig` per tenant + per-tenant `daemon_stage_saturated` emit with `tenant_id` extension via the per-pillar mirror constants parity discipline.
- **Pillar J (security + compliance)** — `daemon_stage_saturated` payload does NOT expose any per-Person state (the 5-key contract excludes person_id / body / source_list per I8 + ADR-0050 D276(b) + ADR-0058 D323); GDPR purge does NOT modify the saturation emit surface; SLSA supply-chain attestation extends to `_DAEMON_VERSION` constant.

§Migration/rollout — operator action: NONE for existing operators. The Week 6 body lands at the per-week trajectory; the actual per-stage dispatch (Week 7+) lands incrementally. Operators wanting per-stage saturation visibility see the panel 2 placeholder at per_daemon.yml light up when Week 7+'s actual dispatch begins saturating; at Week 6 the placeholder continues to read `or vector(0)` because no actual dispatch is running yet.

§Existing-operator seed — operator action: NONE; recommended preview: invoke `asyncio.run(runner.run())` after `init_daemon` returns the runner + observe the per-stage Semaphores via test-only seam introspection (the Week 6 contract pins the Semaphore construction at test time; production operators don't directly observe the Semaphores).

Per-week-reviewer disciplines preservation across Pillar H Week 6 (compounded from Pillar F + Pillar G + Pillar H Weeks 1-5 + 5 follow-ups):
- **Cell-level matrix coverage** — TWENTY-FIVE consecutive weeks at start of Week 6 → TWENTY-SIX after Week 6 (the new test class `TestDaemonStageSaturatedPayload` × ~6 cells + per-stage Semaphore verification at `TestDaemonRunBody` × ~3 cells + coherence un-skip extend the discipline).
- **Behavioral-passthrough-not-signature-only** — TWENTY-TWO consecutive weeks at start of Week 6 → TWENTY-THREE after (the per-stage Semaphore tests inject pre-acquired Semaphores + verify the saturation emit at behavioral level; the per-week-reviewer's behavioral-passthrough discipline catches spy-vs-production drift).
- **Module-level docstring drift** — TWENTY-FOUR consecutive weeks at start of Week 6 → TWENTY-FIVE after (runner.py + __init__.py + observability.py module docstrings extended naming Week 6 + ADR-0065 + D353-D355; health.py preserves verbatim per the W3 follow-up P3-5 closure's discipline-scope-extension to materially-unchanged modules).
- **Per-pillar mirror constants parity** — EXTENDED via DAEMON_NEW_EVENT_CLASSES (5 → 6) + EVENT_CLASS_CATALOG (24 → 25) joint extension preserving the per-pillar locality convention.
- **Cross-pillar back-audit** — the audit-vs-actual-API drift discipline (W1 follow-up `TestMigrationRunnerContract`) + the ADR-vs-actual-impl drift discipline (W2 follow-up P3-8 + W3 follow-up P2-1 + W4 follow-up P2-1 + W5 follow-up P1-1 — FOUR consecutive Pillar H weeks of ADR-vs-actual-impl drift discipline) BOTH preserve verbatim; the Week 6 author verified ADR-0065 narrative claims match the actual body's behavior + the Semaphore construction site + the saturation emit shape before commit.
- **Framework-neutrality contract** — Week 6's per-stage worker pool extension preserves the test-only seam kwargs per the W4 follow-up P2-1 closure's two-tiered seam-vs-fork distinction (operators wanting alternative parallelism primitives — `threading.Semaphore` / `asyncio.BoundedSemaphore` / etc. — MUST fork the function body; the asyncio framework choice per ADR-0060 D332 is the v1 default).
- **Privacy invariant** — `daemon_stage_saturated` payload's 5-key shape excludes person_id / body / source_list per the W4 follow-up TestComputeHealthStatus precedent + the per-Person observability surface adapter pattern.

## References

- **ADR-0064** (Pillar H Week 5 — `DaemonRunner.run` async body wiring the asyncio event loop). D349-D352. **D349's eight-step ordering preserves at Week 6 + Step 6 extends with the per-funnel-stage worker pool tick (Iteration 6b NEW) preserving the per-observability-stage span tick (Iteration 6a Week 5 preserved); D350's per-stage span integration via `observability.traced_stage(stage, "tick")` preserves verbatim; D352's graceful-shutdown coordination via `AppRunner.cleanup` preserves verbatim.**
- **ADR-0063** (Pillar H Week 4 — serve_health_endpoint body + per-pillar-H Grafana panel). D345-D348. **D347's panel 2 placeholder consumer (`outreach_factory_events_total{event_class="daemon_stage_saturated"} or vector(0)`) goes live at Week 6 commit; the `or vector(0)` fallback no longer fires when actual saturation events exist in the ledger.**
- **ADR-0062** (Pillar H Week 3 — signal handler + shutdown bodies). D341-D344. **D342's `object.__setattr__` frozen-dataclass escape hatch + Week 3 follow-up P3-1 closure (ONLY lifecycle_state mutates) preserve verbatim across Week 6; Week 6 does NOT modify the lifecycle state machine.**
- **ADR-0061** (Pillar H Week 2 — init_daemon body + EVENT_CLASS_CATALOG extension + build_daemon_started_payload factory). D337-D340. **D338's EVENT_CLASS_CATALOG extension pattern (Week 2 added FIVE Pillar H classes) extends at Week 6 with the SIXTH `daemon_stage_saturated` class per the per-pillar locality convention.**
- **ADR-0060** (Pillar H foundation). D331-D336. **D331's `DaemonConfig.parallelism_limits` field + D332's asyncio framework decision are the structural commitment Week 6 fulfills via the per-funnel-stage Semaphore body; D335 invariant 1 (one daemon process per tenant) is the per-tenant isolation invariant the per-Semaphore construction preserves.**
- **ADR-0059** (Pillar G Week 12 — binding exit-criterion + funnel CLI extension + READ-ONLY contract). D325-D330. **The funnel CLI READ-ONLY contract preserves verbatim across Week 6; the daemon's per-stage saturation emit is consumed via the funnel CLI's per-event-class observability primitive at status reports.**
- **ADR-0055** (Pillar G Week 6 — per-stage span wiring). D300. **The `observability.traced_stage(stage, operation, ...)` helper preserves verbatim across Week 6; the per-observability-stage span loop at Iteration 6a continues to wrap each per-observability-stage tick.**
- **ADR-0054** (Pillar G Week 5 — OTel TracerProvider initialization). D294-D298. **The `_PIPELINE_STAGES` 8-element closed-set per ADR-0055 D300 + the `_SPAN_ATTRIBUTES_ALLOWED` closed-set per D297 preserve verbatim across Week 6.**
- **ADR-0050** (Pillar G Week 1 foundation). D272-D277. **D272's stateless contract preserves — the daemon's run() body emits `daemon_stage_saturated` via the `Ledger.append` surface NOT a per-instance counter; D276(b) privacy invariant per I8 preserves at the factory payload boundary.**
- **ADR-0031** (Pillar D Week 12 — funnel CLI deterministic-output contract). D140. **The Week 6 body's per-stage tick iterates over `sorted(_PILLAR_G_PIPELINE_STAGES)` per the determinism contract; the saturation emit payload uses raw primitives without rounding.**
- **ADR-0014** (Pillar C foundation — channel-on-every-event invariant). D33. **The `daemon_stage_saturated` payload OMITS the `channel` field per the daemon-lifecycle-events-are-tenant-process-scoped rationale (mirrors Pillar H Week 2-5 factories).**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17. **The factory boundary `_emitted_by` stamping per Week 3 follow-up P2-1 closure preserves at Week 6's `daemon_stage_saturated` emit factory.**
- **ADR-0001** (Pillar A foundation — declarative policy engine). D2 (refuse-loud convention). **The factory's refuse-loud on invalid `stage` / `parallelism_limit` / `in_flight_count` per the framework convention.**
- `.planning/REVIEW-pillar-h-surface-audit.md` — cross-pillar surface audit; §28 NEW Week 6 extension (gitignored).
- `.planning/HANDOFF-pillar-h-week-6.md` — Pillar H Week 6 close summary + handoff to Pillar H Week 7 (this commit; gitignored).
- `docs/PILLAR-PLAN.md` §2 Pillar H + §6 Pillar H row Week 6 status flip + Notes column appended Week 6 close summary.
- `orchestrator/daemon/runner.py` (Week 6 body) — `DaemonRunner.run` body extends Step 6 with per-funnel-stage Semaphore construction + Iteration 6b + `build_daemon_stage_saturated_payload` factory + `daemon_stage_saturated` joins DAEMON_NEW_EVENT_CLASSES + module docstring extension naming Week 6.
- `orchestrator/daemon/__init__.py` — re-export `build_daemon_stage_saturated_payload` + `__all__` extension 18 → 19 names + module docstring extension naming Week 6.
- `orchestrator/observability.py` — EVENT_CLASS_CATALOG extension (24 → 25; adds `daemon_stage_saturated` per the per-pillar locality convention + the Pillar H Week 2 catalog-extension precedent).
- `tests/test_daemon.py` — NEW `TestDaemonStageSaturatedPayload` × ~6 cells (factory shape + refuse-loud on invalid inputs + `_emitted_by="daemon"` audit marker + omit channel + omit ts/type) + extended `TestDaemonRunBody` with Semaphore verification.
- `tests/test_multi_channel_coherence.py` — ONE stub un-skipped (`test_per_stage_parallelism_limit_enforced`).
- `docs/adr/README.md` — ADR-0065 row added.
- `docs/SOURCES-OF-TRUTH.md` — daemon-state row Week 6 ADR-0065 reference.

## Pillar H Week 6 follow-up — per-week review findings addendum

**Date:** 2026-05-27. **Author:** Pillar H Week 6 follow-up commit (the per-week-reviewer pattern at TWENTY-SIX consecutive weeks; see `.planning/REVIEW-pillar-h-surface-audit.md` §29).

The Week 6 main commit `f6e66e7` was reviewed by a fresh-context agent. Findings: **0 P1 + 2 P2 + 11 P3 + 7 NEW addressed + 1 REFUTED**. ZERO new ADRs — all closures are in the spirit of ADR-0065's existing decisions per the per-pillar-foundation precedent.

**P2-1** — No behavioral-passthrough body-level Semaphore-saturation regression-barrier. The W5 P1-1 closure established that behavioral-passthrough tests MUST exercise the production default; the W6 main commit's coherence test verified the factory contract only — the body's Iteration 6b emit path was structurally untested. CLOSED via NEW `semaphore_factory_fn` test-only seam at `DaemonRunner.run` (default `asyncio.Semaphore`; tests inject always-locked subclass) + NEW `TestDaemonRunBody::test_daemon_stage_saturated_emits_when_semaphore_locked_per_w6_followup_p2_1` regression-barrier verifying the body's `sem.locked()` check + the `daemon_stage_saturated` emit + every funnel stage represented in the saturation emit set + `_emitted_by="daemon"` on every emit.

**P2-2** — D353 narrative-vs-code-example INTERNAL drift (the FIFTH ADR-vs-actual-impl drift in Pillar H). The narrative paragraph said "after Step 2's lifecycle transition" but the code example + the actual body construct AFTER Step 5 (start health endpoint). CLOSED via D353 narrative alignment above (the narrative now matches the code example + the body's actual placement at the new Step 5.5).

**P3-1 + P3-2 + P3-3 + NEW-2** — Lazy-import inconsistency across the THREE `_PILLAR_G_PIPELINE_STAGES` sites. CLOSED via STYLE STANDARDIZATION — all three sites now use `from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES` (the `_validate_config` site previously used the bare-module form `import funnel as _funnel`). The W6 follow-up reviewer surfaced a NEW finding beyond the pre-identified P3-1/2/3/NEW-2 closures: the lazy form is REQUIRED (not optional defense-in-depth) because `orchestrator/funnel.py`'s module body does bare-name `import ledger` (line 152) requiring `orchestrator/` on `sys.path` (test-only sys.path shim via `tests/conftest.py`); module-top promotion would break production-import-time from a clean Python process. The W5 follow-up P3-6 "module-top imports when no circular dependency exists" discipline does NOT generalize to funnel because the production-fragility concern is orthogonal to the circular-dependency concern. The W6 follow-up extends the import-block comment naming the deeper rationale.

**P3-4 + NEW-1** — `observability.py` module HEADER cross-pillar discipline-scope question + "Last reviewed" line bump. CLOSED via the "Last reviewed" line update at `observability.py:457` naming Pillar H Week 2 + Week 6 catalog extensions per the W3 follow-up P3-5 closure's materially-unchanged-module scope; the module HEADER itself stays unchanged per the cross-pillar locality convention (the HEADER documents Pillar G's pillar identity; the catalog comment block at lines 528-538 names Pillar H Week 2 + Week 6 extensions for the per-Pillar-H locality).

**P3-5 + P3-6 + P3-7 + NEW-3 + NEW-6 + NEW-7** — "FIVE → SIX" docstring drifts across NINE sites. CLOSED via per-site updates:
- `runner.py:409` closed-set comment FIVE → SIX
- `__init__.py:143-145` public-surface bullet FIVE → SIX + added `daemon_stage_saturated` enumeration
- `test_observability.py:328 + 352` test docstrings FIVE → SIX
- `test_daemon.py:59 + 191 + 2032` test docstrings + class docstring FIVE → SIX
- `test_multi_channel_coherence.py:9498` class docstring FIVE → SIX
- `TestEventClassCatalogPillarHWeek2Extension` class docstring extended with Week 6 catalog extension reference

**P3-8** — `per_daemon.yml` "FIVE → SIX" drift + carry-forwards section Week 5 → Week 6 attribution correction + dashboard description "Week 4 → Week 4 + Week 6". CLOSED via FIVE per-site updates at the YAML (header comment + dashboard description + panel 4 description + carry-forwards section + Week 6 carry-forward entry naming the actual landing week per ADR-0065 D355).

**P3-9 + P3-10** — Factory docstring `in_flight_count` semantic clarification + `asyncio.Semaphore` waiter-case asymmetry documentation. CLOSED via extended Args section at `build_daemon_stage_saturated_payload` naming the factory-wide-vs-body-emit-narrow asymmetry + the asyncio Semaphore's `locked()` returns True iff `_value == 0` (queued waiters tracked in separate FIFO not affecting locked()); Week 7+ MAY surface `waiter_count` as a separate backpressure field via the closed-set discipline.

**P3-11** — No regression-barrier on per-funnel-stage Semaphore construction iteration source. CLOSED via folding into P2-1's regression-barrier — the new test verifies the body's iteration source is `_PILLAR_G_PIPELINE_STAGES` via the per-funnel-stage saturation emit's `stage` field distribution (the set of distinct `stage` values in the saturation emits equals `set(_PILLAR_G_PIPELINE_STAGES)` per the test's assertion).

**REFUTED** — Pre-identified weak spot #6 (factory's `in_flight_count == parallelism_limit` upper-edge IS implicitly tested via `_valid_kwargs`'s `parallelism_limit=4, in_flight_count=4` consumed by `test_payload_shape_pins_per_adr_0065_d355`).

### Per-week-reviewer disciplines status after Week 6 follow-up

- **Cell-level matrix coverage**: TWENTY-SEVEN consecutive weeks (the new behavioral-passthrough regression-barrier extends the discipline at the body-level Semaphore saturation emit path).
- **Behavioral-passthrough-not-signature-only**: TWENTY-FOUR consecutive weeks (the new test exercises the production default `asyncio.Semaphore` via the test-only spy subclass + verifies body-level emit path — the same shape as the W5 P1-1 closure's canonical demonstration).
- **Module-level docstring drift**: TWENTY-SIX consecutive weeks (the NINE "FIVE → SIX" docstring drift closures + the `observability.py:457` "Last reviewed" line bump + per_daemon.yml dashboard + panel 4 + carry-forwards section all extend the discipline).
- **Per-pillar mirror constants parity**: PRESERVED (the closed-set count was already correct at 6 elements; the W6 follow-up fixes the docstring drift at the surface where operators read the count).
- **Cross-pillar back-audit**: EXTENDED via P2-2's FIFTH ADR-vs-actual-impl drift catch in Pillar H (W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2); the per-week-reviewer pattern's structural value compounds at FIVE consecutive Pillar H weeks of ADR-vs-actual-impl drift catches.
- **Framework-neutrality contract**: PRESERVED via the new `semaphore_factory_fn` test-only seam following the W4 follow-up P2-1 closure's two-tiered seam-vs-fork distinction — the asyncio framework choice per ADR-0060 D332 remains the v1 default; operators wanting alternative concurrency models MUST fork the function body.
- **Privacy invariant**: CONFIRMED — the new test does NOT introduce any new payload fields; the 5-key `daemon_stage_saturated` shape preserves verbatim.
