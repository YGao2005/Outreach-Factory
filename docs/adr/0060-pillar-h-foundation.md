# ADR-0060: Pillar H foundation — daemon + dispatcher primitive shape, asyncio framework decision, cross-pillar integration audit, exit-criterion vehicle scope, per-daemon load-bearing invariants, per-event-class indexing trajectory

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** H (Daemon + dispatcher — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0008 shipped Pillar A (declarative policy engine). ADRs 0009-0013 shipped Pillar B (migration framework + synthetic-replay exit-criterion vehicle). ADRs 0014-0024 shipped Pillar C (multi-channel coherence — four channels, six reconcile passes, five per-channel policy migrations). ADRs 0025-0031 shipped Pillar D (reply + conversation handling — rule + LLM classifier, auto-unsubscribe, conversation state machine, win/loss attribution, funnel CLI). ADRs 0032-0037 shipped Pillar E (discovery quality + lineage — dedup + email-verification cache + tier auto-assignment + discovery_lineage stamping + three-skills-one-day binding exit-criterion). ADRs 0038-0049 shipped Pillar F (voice corpus + draft quality — voice-corpus schema + canonical location, embedding-retrieval primitive, per-register adapters, threshold loader + CLI, FIVE-layer hallucination-detection defense across Layers 1-5, per-claim-type corpus + measurement, voice-fidelity scoring, fuzzy-match Layer 3 extension, Layer 4 post-engine guard, Layer 3 corpus revision with paraphrased-ready pairs + bound tightening, and Layer 5 reconcile heal-pass refusal closing the FIVE-layer defense + binding 200-draft eval set + Stable flip). ADRs 0050-0059 shipped Pillar G (Observability — per-event-class observability primitive + OTel SDK metrics + Prometheus exporter + Grafana-as-code first dashboard + OTel tracing + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + Grafana per-Person dashboard + funnel CLI extension with three binding-question report sections + Stable flip). **Pillar G is Stable as of 2026-05-26.** Pillars H / I / J are unblocked from the "G stable" dependency.

Pillar H — Daemon + dispatcher (`docs/PILLAR-PLAN.md` §2 Pillar H, Weeks 37-48) — extends the substrate at the operational-systems end: every operator's production deployment needs standard ops tooling (systemd / healthchecks / graceful shutdown / live policy reload / structured logs / OTel hooks), and the framework's existing `claude -p` loop is not a fit for the operational shape. The substrate is in place — Pillar A's policy engine + Pillar B's migration framework + Pillar C's per-channel two-phase commit + Pillar D's reconcile loop + Pillar E's discovery primitives + Pillar F's draft-quality + Pillar G's OTel SDK + Prometheus + Grafana — what Pillar H Week 1 needs is the **convention-setting decisions** the next eleven weeks build on.

Pillar G's Week 12 retrospective (`.planning/RETRO-pillar-g.md` §"What to do differently in Pillar H") named TEN carry-forward recommendations: (1) land the Pillar H exit-criterion test in Week 1, NOT Week N (Pillar D + E + F + G Week 1 each shipped binding test stubs); (2) audit pre-existing surfaces for Pillar H scale concerns (every prior pillar's Week 1 audit caught ≥1 P2); (3) continue the per-week-handoff + per-week-review-with-follow-up-commit + per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact + holistic-exit-review discipline; (4) design Pillar H's per-daemon load-bearing invariants at Week 1; (5) design the per-event-class-symmetry-with-shared-aggregation pattern at Week 1 (Pillar G shipped four framework adoptions via the shared framework-neutrality contract); (6) apply the FIVE per-week-reviewer disciplines that held SIXTEEN consecutive weeks (cell-level matrix coverage + behavioral-passthrough-not-signature-only + legacy-state-vs-new-defense-layer reason-precedence drift + cross-pillar back-audit + module-level docstring drift + per-pillar mirror constants parity); (7) the TEST-ONLY embed_fn + retrieve_fn seam preservation pattern generalizes; (8) the Week 12 READ-ONLY funnel CLI contract generalizes; (9) the framework-neutrality contract generalizes (Pillar H's daemon framework choice follows the same operator-deliberate set-once posture per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298); (10) the closed-set discipline + the privacy invariant generalize.

The six concerns this ADR's design resolves:

1. **Daemon primitive shape must be pinned before per-week 2+ adapters ship.** PILLAR-PLAN §2 Pillar H names the daemon's operational shape — standalone Python daemon, NOT a `claude -p` loop — but does not pin the per-process API surface. D331 pins `orchestrator/daemon/` package shape: `DaemonConfig` (frozen dataclass) + `DaemonRunner` (frozen dataclass with `run` / `shutdown` / `reload_policy` / `health` methods) + `PolicyReloadResult` + `HealthStatus` + `DAEMON_LIFECYCLE_STATES` closed-set + `DAEMON_NEW_EVENT_CLASSES` closed-set + `HEALTH_PROBE_OUTCOMES` closed-set + `init_daemon` + `attach_signal_handlers` + `serve_health_endpoint` signatures. The Week 1 commit ships the module shape + signatures; Weeks 2-12 ship the implementation bodies per D332's per-week trajectory table.

2. **Daemon framework decision — asyncio vs threading vs multiprocessing.** PILLAR-PLAN §2 Pillar H names "per-stage parallelism limits with backpressure" without specifying the concurrency framework. The Week 1 commit pins the choice so per-week implementations don't reopen the question. D332 picks **asyncio** (single-process / cooperative scheduling) as the canonical concurrency framework. Per the rationale at D332: the framework's I/O surfaces are network-bound (Gmail / LinkedIn / Apollo / PDL / Reoon / Twitter / Ledger I/O / vault I/O); asyncio's cooperative scheduling fits the workload shape; the Ledger's append-only contract per I2 + the per-Person lock primitive per Phase 5.5 + the per-channel two-phase commit per ADR-0014 D33 ALL hold under asyncio's single-thread model without additional synchronization; Pillar G's OTel SDK initialization + Prometheus exporter + per-stage spans are async-context-friendly; the sync per-channel SDKs (Gmail / LinkedIn) wrap via `asyncio.to_thread`. The rationale + 3+ rejected alternatives at D332.

3. **Cross-pillar surface audit — THE load-bearing anti-regression decision.** Per Pillar A/B/C/D/E/F/G Week 1 precedents (every prior pillar's Week 1 audit caught ≥1 pre-existing P2): Pillar A surfaced policy-engine version concerns; Pillar B surfaced `ledger/0002`'s channel-field gap; Pillar C surfaced Pass A's channel-filter gap; Pillar D surfaced Pass B's channel-on-every-event gap; Pillar E surfaced `needs_identity_upgrade`'s source-attribution gap; Pillar F surfaced the all-cited-claims-path vacuity gap in `tests/test_multi_channel_coherence.py::TestHallucinationDetection`; Pillar G surfaced `funnel.py`'s ts-missing posture gap. Pillar H Week 1's per-week reviewer MUST audit existing Pillar A/B/C/D/E/F/G surfaces for symmetric assumptions when Pillar H's commit silently introduces the daemon's process-boundary + per-stage worker pool. D333 pins the audit + names the load-bearing concerns: (a) does the Pillar B migration framework's auto-apply contract hold under the daemon's startup ordering? (b) does the per-Person lock primitive per Phase 5.5 hold under asyncio's cooperative scheduling? (c) does the Pillar G stateless-aggregation contract per R033 hold when the daemon runs the funnel CLI in-process? (d) does the per-channel two-phase commit per ADR-0014 D33 hold across daemon restarts? `.planning/REVIEW-pillar-h-surface-audit.md` is the load-bearing artifact future Pillar H weeks extend.

4. **The Pillar H exit-criterion verification vehicle must exist in Week 1.** Per PILLAR-PLAN §2 Pillar H binding text: *"24h continuous run against synthetic vault with 1000 prospects produces zero anomalies; recovers cleanly from `kill -9`; reloads cooldown rule changes without restart."* Without the vehicle landing in Week 1, the cross-cutting properties (24h-duration zero-anomaly + crash-recovery + policy-hot-reload + observability-integration + privacy-invariant) would only surface end-of-pillar, repeating Pillar B Week 5 + Pillar C Week 12 + Pillar D Week 12 + Pillar E Week 12 + Pillar F Week 12 + Pillar G Week 12's pattern. D334 names the vehicle scope: `tests/test_multi_channel_coherence.py` is EXTENDED with `TestPillarHDaemon` + `TestPillarHDaemonObservabilityIntegration` + `TestPillarHExitCriterion` test classes (Option A per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 + ADR-0050 D275 single-file rationale inherited). The file currently sits at ~9000 LOC — well past the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266 + the Pillar G Week 12 retrospective — but the Pillar H Week 1 commit does NOT split (the per-pillar test classes' Week 1 stubs belong adjacent to the per-pillar primitive contracts they verify; the split argument resurfaces if Pillar H's Week 2+ commits add another ~1500 LOC, becoming a Pillar H Week N reviewer's call).

5. **Per-daemon load-bearing invariants.** Per RETRO-pillar-g.md item 4 (continuing Pillar D Week 1's CAN-SPAM precedent per ADR-0025 D97 + Pillar E Week 1's privacy precedent per ADR-0032 D148 + Pillar F Week 1's hallucination-detection FIVE-layer precedent per ADR-0038 D180 + Pillar G Week 1's four invariants per ADR-0050 D276) — Pillar H ships its load-bearing invariants at Week 1. D335 names FOUR: (a) **process-isolation** — one daemon process per tenant; per-process Ledger contract preserves per ADR-0050 D276(d); multi-tenant fan-out is Pillar I scope; (b) **atomicity-preservation-across-process-boundary** — the ledger's append-only contract per I2 holds across daemon restarts; the per-channel two-phase intent/confirmed pairs per ADR-0014 D33 still complete via the reconcile loop (Pass A through O) if the daemon crashes between phases; the daemon contributes NO new state that bypasses the ledger; (c) **graceful-shutdown** — on SIGTERM / SIGINT the daemon transitions to `"draining"`, completes in-flight per-stage tasks within `DaemonConfig.graceful_shutdown_seconds`, emits `daemon_stopping` + `daemon_stopped` ledger events, then exits with code 0; the reconcile loop is the recovery backstop for tasks exceeding the deadline; (d) **live-reload-policy** — on SIGHUP the daemon re-reads the policy YAML files per Pillar A + emits `policy_reloaded` with prior + new content hashes; no restart required; cooldown / suppression / sending-window / budget rule changes take effect at the next per-stage tick.

6. **Per-event-class indexing trajectory — R039 mitigation pattern.** Pillar G's per-Person primitives' per-call O(N) ledger walk (per ADR-0050 D272 + R033 mitigation pattern) is calibrated for v1 scale (~5K events sub-second); the per-call cost at v2 scale (~100K events) surfaces as a per-cron-interval latency concern per the Pillar G retrospective's "What surprised" item 4. D336 pins Pillar H's structural mitigation: the daemon materializes a per-event-class index at startup (denormalized from the ledger; rebuildable per I3; invalidated on `Ledger.append`); the per-call observability primitive aggregations consult the index instead of walking `Ledger.all_events()` directly. The implementation lands at Pillar H Week 8-9 per the per-week trajectory table; the Week 1 commit pins the framework decision + the index's structural commitment (operator-visible per the `daemon_started` event's payload + the per-pillar-G dashboard's index-age panel).

Risks this ADR mitigates by design: **R005 (Gmail API quota exhaustion)** continues mitigated by per-channel rate-limit policies; the daemon's per-stage worker pool's `send` parallelism limit per `DaemonConfig.parallelism_limits["sent"]` (default 1) provides additional structural rate-limiting. **R016 (LLM cost runaway)** continues mitigated by Pillar A's budget rules; the daemon's per-stage `drafted` parallelism limit caps per-window concurrent LLM calls. **R023 (hallucination-detection false-negative)** continues mitigated by Pillar F's FIVE-layer defense closed at Layer 5 per ADR-0049 D262; the daemon does NOT modify the Layer 5 backstop. **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED at single-tenant; Pillar I multi-tenant fan-out will revisit per the Pillar I per-tenant audit-tooling trajectory.

Three new risks surface in this ADR's authoring + named in `docs/RISK-REGISTER.md`:

- **R037 (Daemon process-restart silent state loss)** — operators restarting the daemon for any reason (config change / migration / OS patch / crash recovery) MAY have in-flight per-stage tasks (e.g., a `send_intent` event written but the `send_confirmed` event not yet emitted because Gmail API is rate-limited). Without structural mitigation, these in-flight tasks could appear "lost" — operators querying the funnel CLI's `prospect_funnel` panel would see the prospect stuck at `sent` stage without a corresponding `*_confirmed` event. Mitigation by design: D335 invariant 2 — the atomicity-preservation-across-process-boundary invariant pins the reconcile loop (Pass A through O) as the structural recovery backstop. Pass A specifically handles `send_intent` recovery via the X-Outreach-Intent-Id header; the daemon's per-stage worker pool does NOT bypass the ledger. The Pillar G dashboard surfaces the per-stage drift via the existing `prospect_funnel` panel + per-channel `*_failed` / `*_aborted` count.

- **R038 (Health probe event-emission flood)** — k8s readiness probes typically hit the health endpoint every 10s (configurable); without rate-limiting, the `health_probe` event would emit ~8640 events/day per single-tenant operator + bloat the ledger + dominate the per-event-class catalog's observability_class_uncatalogued diagnostic rate per R034. Severity 2 / likelihood 3 (k8s deployments are the production-target shape per the OSS bring-up trajectory at Pillar I). Mitigation by design: D334 + D335's `DaemonConfig.health_probe_rate_limit_seconds` (default 30s) — at-most-ONE `health_probe` event per 30s window per single-tenant operator caps the rate at ~2880 events/day (a 3x reduction from the unmitigated 8640/day). Operators wanting per-request probe events set the limit to 0; the structural barrier is the framework default. The Pillar G Week 4's per-pillar Prometheus exporter exposition surface MAY be the preferred operator-visible probe surface at sustained-high-rate (Prometheus metrics aggregation does NOT require per-probe ledger append); the `health_probe` event is the operator-debugging surface.

- **R039 (Per-Person primitive's O(N) ledger walk at daemon-cron-interval cost)** — the Pillar G per-Person primitives per ADR-0058 D319-D324 walk `Ledger.all_events()` per call; the v1 scale (~5K events) cost is sub-second; the v2 scale (~100K events) cost at daemon's per-cron-interval (typically 1m) MAY surface as a per-event-class indexing concern. Severity 2 / likelihood 3 (single-tenant operators at v2 scale would see the latency surface in the per-Person dashboard's panel-render time). Mitigation by design: D336 — Pillar H Week 8-9 ships the per-event-class index materialization at daemon startup; the per-call observability primitive aggregations consult the index instead of walking `Ledger.all_events()`. The index is denormalized (rebuildable per I3) + invalidated on `Ledger.append`. Operators on v1 scale do NOT see the latency concern; the index is structurally a no-op at v1 scale. Pillar I multi-tenant fan-out may revisit per-tenant indexing per the per-tenant audit-tooling trajectory.

The Pillar G framework adoption surfaces (OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension) preserve verbatim. The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The brand-and-legal-liability invariant + the privacy invariant + the FIVE-layer hallucination-detection defense all hold with FULL weight.

## Decision

### D331. `orchestrator/daemon/` package shape — module + dataclasses + closed-sets + signatures

Pillar H ships the `orchestrator/daemon/` package (NEW Week 1; Week 2+ ships the bodies). The Week 1 commit ships the **package shape** + **the closed-set enumeration of daemon lifecycle states + new event classes + health probe outcomes** + **the `DaemonConfig` / `DaemonRunner` / `PolicyReloadResult` / `HealthStatus` dataclasses** + **the `init_daemon` / `attach_signal_handlers` / `serve_health_endpoint` / `DaemonRunner.run` / `shutdown` / `reload_policy` primitive signatures**. The Week 2+ commits ship the implementation bodies per D332's per-week trajectory table.

The contract:

```python
# Pillar H Week 1 ships the contract; Weeks 2-12 ship the bodies.
from orchestrator.daemon import (
    DaemonConfig,            # frozen dataclass — initialization params
    DaemonRunner,            # frozen dataclass — main-loop primitive
    PolicyReloadResult,      # frozen dataclass — SIGHUP outcome
    HealthStatus,            # frozen dataclass — readiness probe output
    DAEMON_LIFECYCLE_STATES, # frozenset — 4 states
    DAEMON_NEW_EVENT_CLASSES,# frozenset — 5 new Pillar H event classes
    HEALTH_PROBE_OUTCOMES,   # frozenset — 3 probe outcomes
    init_daemon,             # (DaemonConfig) -> DaemonRunner   [Week 2]
    attach_signal_handlers,  # (DaemonRunner) -> None           [Week 3]
    serve_health_endpoint,   # (int, *, runner=…) -> None       [Week 4]
)

config = DaemonConfig(
    vault_dir=Path("..."), ledger_dir=Path("..."),
    health_port=8080,
    parallelism_limits={"queued": 1, ..., "outcome_terminal": 1},
    graceful_shutdown_seconds=30,
    policy_reload_signal="SIGHUP",
    health_probe_rate_limit_seconds=30,
)
runner = init_daemon(config)       # Week 2+ body
attach_signal_handlers(runner)     # Week 3+ body
exit_code = runner.run()           # Week 5+ body
```

**FIVE new event classes** at `DAEMON_NEW_EVENT_CLASSES` per the per-pillar-foundation precedent (Pillar G Week 1 added two new classes via `OBSERVABILITY_NEW_EVENT_CLASSES`; Pillar H adds five via `DAEMON_NEW_EVENT_CLASSES`):

* `daemon_started` — emit on `initializing → ready` transition; payload: `pid` + `version` + `config_hash` + `startup_seconds` + `ts`.
* `daemon_stopping` — emit on `ready → draining` transition; payload: `pid` + `reason` (`sigterm` | `sigint` | `operator_requested`) + `drain_deadline_ts` + `in_flight_task_count` + `ts`.
* `daemon_stopped` — emit before process exit; payload: `pid` + `exit_reason` (`clean` | `timeout` | `crash`) + `uptime_seconds` + `in_flight_task_count_at_exit` + `ts`.
* `policy_reloaded` — emit on SIGHUP-driven policy re-read; payload: `pid` + `source_path` + `prior_content_hash` + `new_content_hash` + `status` (`applied` | `failed_unchanged`) + `ts`.
* `health_probe` — emit on health endpoint hit (rate-limited per R038); payload: `pid` + `outcome` + `lifecycle_state` + `remote_addr` + `ts`.

Pillar H Week 2 extends `observability.EVENT_CLASS_CATALOG` with these five classes; the per-call `collect_event_class_snapshots` aggregates them uniformly with prior-pillar event classes per ADR-0050 D272. The Week 1 commit pins the closed-set; the Week 2 catalog extension is the symmetric assertion.

**FOUR daemon lifecycle states** at `DAEMON_LIFECYCLE_STATES`:

* `"initializing"` — process started; pre-flight checks running (migrations applied per Pillar B + policy YAML loaded per Pillar A + OTel SDK initialized per Pillar G Week 3 + Prometheus exporter listening per Pillar G Week 4); health endpoint returns 503.
* `"ready"` — pre-flight complete; per-stage dispatch running; reconcile passes running; health endpoint returns 200.
* `"draining"` — graceful shutdown initiated via SIGTERM / SIGINT; in-flight per-stage tasks complete within `DaemonConfig.graceful_shutdown_seconds`; no new per-stage tasks accepted; health endpoint returns 503.
* `"stopped"` — drain complete; daemon process exits; `daemon_stopped` event emits before exit.

Pillar I MAY add a `"paused"` per-tenant state for tenant-level pause without process exit per the per-tenant audit-tooling trajectory; Pillar H Week 1 ships the FOUR states only. The closed-set discipline + the regression-barrier test pins the contract.

**THREE health probe outcomes** at `HEALTH_PROBE_OUTCOMES`:

* `"ok"` — daemon in `"ready"` state + ledger reachable + policy loaded; HTTP 200.
* `"degraded"` — daemon in `"ready"` state but at least one degraded indicator (reconcile pass last-run-age beyond threshold; OTel exporter unreachable; per-stage worker pool saturated); HTTP 200 (k8s readiness probe permits traffic; degraded surfaces to operator via Pillar G overview dashboard's SLO panel).
* `"unhealthy"` — daemon NOT in `"ready"` state OR ledger unreachable OR policy load failed; HTTP 503 (k8s readiness probe blocks traffic).

**Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323** holds across the daemon surface. The `HealthStatus` dataclass contains COUNTS + STATES + timestamps + version; NEVER `person_id` / body content / source_list. The `health_probe` event's payload contains `outcome` + `lifecycle_state` + `remote_addr` + `ts`; NEVER any per-Person field. The Pillar H per-week-reviewer's privacy invariant check is the structural barrier.

### D332. Asyncio framework decision + per-week trajectory table

The Pillar H daemon is **single-process / single-thread / asyncio-cooperative-scheduling** at Week 1. The per-stage worker pool uses asyncio's task primitive (`asyncio.create_task`) with per-stage semaphores (`asyncio.Semaphore`) bounded by `DaemonConfig.parallelism_limits`.

Rationale (the four reasons per the Context section):

* Network-bound workload — Gmail / LinkedIn / Twitter / Apollo / PDL / Reoon / Ledger / vault all I/O-bound + async-cooperative-friendly.
* Existing contract preservation — Ledger append-only + per-Person lock + per-channel two-phase commit all hold under asyncio's single-thread model.
* Pillar G framework adoption preservation — OTel SDK init + Prometheus exporter + per-stage spans + Histogram all async-context-friendly.
* Sync per-channel SDK wrapping — Gmail / LinkedIn / Twitter SDKs are sync; `asyncio.to_thread` wraps them per the standard pattern.

Multi-process / per-tenant fan-out (one daemon process per tenant) is Pillar I scope; Pillar H Week 1 ships single-tenant per ADR-0050 D276(d).

**Per-week trajectory table** (the structural commitment Weeks 2-12 satisfy; matches Pillar G Week 1's D273 trajectory shape):

| Week | Deliverable | New ADR? |
|---|---|---|
| 1 | Daemon module shape + closed-sets + dataclasses + signatures + cross-pillar surface audit + exit-criterion vehicle (this commit, ADR-0060) | ADR-0060 |
| 2 | `init_daemon` body + EVENT_CLASS_CATALOG extension + `daemon_started` emit | ADR-0061 |
| 3 | `attach_signal_handlers` body + `DaemonRunner.shutdown` body + `daemon_stopping` + `daemon_stopped` emits | ADR-0062 |
| 4 | `serve_health_endpoint` body + `health_probe` rate-limit per R038 + per-pillar-H Grafana panel at `infra/grafana/dashboards/per_daemon.yml` | ADR-0063 |
| 5 | `DaemonRunner.run` body + per-stage worker pool + asyncio event loop + per-stage span integration per ADR-0055 D300 | ADR-0064 |
| 6 | Per-stage parallelism limits + backpressure semaphores + per-stage worker saturation Grafana panel | ADR-0065 |
| 7 | `reload_policy` body + SIGHUP wiring + Pillar A policy engine re-read + `policy_reloaded` emit | ADR-0066 |
| 8 | Per-event-class index materialization at startup per R039 + ledger-walk-avoidance at per-Person primitives | ADR-0067 |
| 9 | Per-event-class index invalidation on `Ledger.append` + index-age dashboard panel | ADR-0067 (continued) |
| 10-11 | Crash recovery hardening — `kill -9` test substrate + reconcile loop integration + Pass A/B/C tightening + per-pillar-H Grafana drill-down | ADR-0068 |
| 12 | Binding exit-criterion test un-skip + Pillar H Stable flip + retrospective + handoff to Pillar I | ADR-0069 |

Pillar G's per-week-handoff convention + per-week-review-with-follow-up-commit + per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact + holistic-exit-review discipline all carry-forward to Pillar H weeks.

### D333. Cross-pillar surface audit at `.planning/REVIEW-pillar-h-surface-audit.md`

`.planning/REVIEW-pillar-h-surface-audit.md` is the load-bearing anti-regression artifact future Pillar H weeks extend. The Week 1 audit walks every Pillar A/B/C/D/E/F/G surface that touches process lifecycle / per-stage dispatch / reconcile loop / OTel SDK init / Prometheus exporter / per-Person primitives / funnel CLI for whether Pillar H's daemon process-boundary silently broadens the assumption space.

The audit's load-bearing concerns:

* **Pillar B migration framework's auto-apply contract** — `MigrationRunner.apply()` is currently called from `claude -p` startup; the daemon's `init_daemon` body MUST call it from the asyncio startup sequence + emit `migration_event` per ADR-0009 D9. The daemon does NOT bypass the migration framework.
* **Per-Person lock primitive per Phase 5.5** — file-based locks via `fcntl` on the Person's directory; under asyncio's single-thread model the per-Person lock acquire is sequenced via `asyncio.Lock` + `asyncio.to_thread(fcntl.flock, …)`; the contract holds. Multi-process per-tenant fan-out (Pillar I scope) is when the file-based lock primitive proves its cross-process value.
* **Pillar G stateless-aggregation contract per R033** — `observability.collect_event_class_snapshots` re-walks the ledger per call; the daemon does NOT cache the aggregations. The funnel CLI's READ-ONLY contract per ADR-0059 D325 + the byte-identical determinism per ADR-0031 D140 both preserve.
* **Per-channel two-phase commit per ADR-0014 D33** — `send_intent` + `send_confirmed` pairs survive daemon restart via Pass A recovery; the daemon contributes NO new state that bypasses the ledger. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN.
* **Pillar F Layer 5 backstop per ADR-0049 D262** — Pass C's `ratifies_ready` predicate refuses heal-to-`ready` without a corresponding `draft_ready` event; the daemon's per-stage `ready` dispatch consults the same Pass C check; the FIVE-layer defense closed at Layer 5 preserves verbatim across the daemon.

The audit's per-week-reviewer carry-forward checklist applies the SEVEN compounded disciplines from Pillar G Week 12 follow-up:

* Cell-level matrix coverage (SIXTEEN consecutive weeks at start of Pillar H Week 1).
* Behavioral-passthrough-not-signature-only (THIRTEEN consecutive weeks).
* Cross-claim-type extraction cascade (does NOT apply at Pillar H Week 1 — daemon is not a corpus-pair primitive).
* Legacy-state-vs-new-defense-layer tension (Pillar H preserves every Pillar A/B/C/D/E/F/G primitive verbatim).
* Legacy-state-vs-new-defense-layer reason-precedence drift (Pillar H preserves the `PILLAR_F_LAYER_5_DRIFT_REASONS` BOTH-reasons structural protection).
* Cross-pillar back-audit (the audit's purpose).
* Module-level docstring drift (FIFTEEN consecutive weeks; Pillar H Week 1 extends `orchestrator/daemon/*` module docstrings naming Week 1 + ADR-0060 + D331-D336).
* Per-pillar mirror constants parity (the FIVE Pillar H event classes mirror the closed-set discipline per ADR-0050 D272 + ADR-0058 D322; Pillar H Week 2 adds the catalog extension regression-barrier test).

### D334. Exit-criterion vehicle scope at `tests/test_multi_channel_coherence.py`

`tests/test_multi_channel_coherence.py` extends with THREE new test classes:

* `TestPillarHDaemon` — per-week trajectory stubs (10 rows) un-skipping progressively as the per-week bodies land.
* `TestPillarHDaemonObservabilityIntegration` — Pillar H ↔ Pillar G integration stubs (3 rows) for the catalog extension + Grafana panel + per-stage span integration.
* `TestPillarHExitCriterion::test_daemon_24h_run_zero_anomalies_recovers_from_kill_9_reloads_policy` — the binding exit-criterion test stub (1 row) un-skipped at Pillar H Week 12.

The binding test verifies SIX rows (24h-duration zero-anomaly + crash-recovery + policy-hot-reload + graceful-shutdown + observability-framework-preservation + privacy-invariant); the substrate is the 1000-prospect synthetic vault per PILLAR-PLAN §2 Pillar H exit criterion; the 24h-run compresses to a 1000-stage-tick fixture under the test (100ms × 1000 = 100s runtime).

Pillar G Week 1 (per ADR-0050 D275) shipped 12 stub rows (TestPillarGObservability × 7 + TestPillarGSLOAlerting × 4 + TestPillarGExitCriterion × 1); Pillar H Week 1 ships 14 stub rows (TestPillarHDaemon × 10 + TestPillarHDaemonObservabilityIntegration × 3 + TestPillarHExitCriterion × 1) matching the scale of the per-week trajectory + the Pillar G consumer surface.

### D335. Per-daemon load-bearing invariants (FOUR; analogous to Pillar G Week 1 D276 FOUR invariants)

1. **Process-isolation.** One daemon process per tenant. The per-process Ledger contract preserves per ADR-0050 D276(d). Multi-tenant fan-out is Pillar I scope per the per-tenant audit-tooling trajectory; Pillar H Week 1 ships single-tenant. The Pillar I author wiring multi-tenant runs one daemon process per tenant + isolates the Ledger directories.

2. **Atomicity-preservation-across-process-boundary.** The ledger's append-only contract per I2 holds across daemon restarts. The per-channel two-phase intent/confirmed pairs per ADR-0014 D33 still complete via the reconcile loop (Pass A through O) if the daemon crashes between phases. The daemon contributes NO new state that bypasses the ledger — every per-stage tick's structural change emits a ledger event; every operator-visible state derives from the ledger walk. R037 mitigation pattern.

3. **Graceful-shutdown.** On SIGTERM / SIGINT the daemon transitions to `"draining"`, completes in-flight per-stage tasks within `DaemonConfig.graceful_shutdown_seconds`, emits `daemon_stopping` + `daemon_stopped` ledger events, then exits with code 0. The reconcile loop is the recovery backstop for tasks exceeding the deadline (Pass A specifically handles `send_intent` recovery via the X-Outreach-Intent-Id header). The `daemon_stopped` event's payload carries `exit_reason` (`clean` | `timeout` | `crash`) for operator-visible diagnosis.

4. **Live-reload-policy.** On SIGHUP the daemon re-reads the policy YAML files per Pillar A's policy engine + emits `policy_reloaded` with prior + new content hashes; no restart required. Cooldown / suppression / sending-window / budget rule changes take effect at the next per-stage tick. The reload is operator-deliberate per the SIGHUP convention; the daemon does NOT auto-reload on file change (operators wanting auto-reload wire `inotifywait` + `kill -HUP`). The `policy_reloaded` event's `status` field carries `"applied"` | `"failed_unchanged"` for operator-visible parse error diagnosis (the parse error message surfaces in the event's `parse_error` field — operator-readable, NOT a Python traceback).

### D336. Per-event-class indexing trajectory (R039 mitigation)

Pillar H Week 8-9 ships per-event-class index materialization at daemon startup + invalidation on `Ledger.append`. The index is denormalized from the ledger (rebuildable per I3) + invalidated on each `Ledger.append`; the per-call observability primitive aggregations consult the index instead of walking `Ledger.all_events()` directly.

The index structure:

```python
# In-memory at the DaemonRunner level (NOT persisted; rebuilt at startup).
EventClassIndex = dict[str, list[dict]]   # event_class → events in time-order
PersonEventIndex = dict[str, list[dict]]  # person_id → per-Person events
```

The per-Person primitives at `observability.collect_per_person_*` consume `PersonEventIndex` directly at Week 8 (lookup by `person_id` is O(1); the per-Person primitive's per-call cost drops from O(N) to O(M) where M = events for that Person, typically tens). The funnel CLI's READ-ONLY contract per ADR-0059 D325 preserves; the funnel CLI's `aggregate_per_stage_funnel` walks the index instead of the ledger when invoked from the daemon process (operators invoking `python orchestrator/funnel.py` outside the daemon continue to walk the ledger directly — the indexes are daemon-process-local).

The index's invalidation contract: every `Ledger.append` triggers an in-memory index update; the contract preserves the byte-identical determinism per ADR-0031 D140 because the index reflects the ledger's current state exactly. The Pillar G observability primitives' stateless contract per ADR-0050 D272 + R033 mitigation is preserved at the per-process level — the index is per-process state, not cross-process; multi-tenant operators (Pillar I) run one daemon per tenant.

Pillar I per-tenant audit-tooling MAY extend the index with per-tenant labels per the multi-tenant fan-out trajectory; Pillar H Week 1 ships the single-tenant framework + the per-week-8-9 trajectory.

## Alternatives considered

### D331 alternatives (daemon primitive shape)

1. **Ship a thin systemd wrapper around the existing `claude -p` loop instead of a Python daemon.** Rejected per PILLAR-PLAN §2 Pillar H — the binding text explicitly names the Pillar H deliverable as a standalone Python daemon, NOT a `claude -p` loop. The `claude -p` loop's startup overhead (LLM API call per loop iteration) is incompatible with the 24h zero-anomaly exit criterion (~28800 LLM calls/day just for the loop = $$$); the per-stage worker pool needs in-process state that the `claude -p` loop cannot preserve across iterations.

2. **Ship a multiprocess daemon (one process per per-channel dispatcher).** Rejected at Pillar H Week 1 — multi-process per-channel fan-out forces cross-process Ledger contention (file-based locks via `fcntl` cross-process — slow; cross-process state divergence — error-prone; cross-process OTel SDK init — Pillar G's `set_global=True` enforcement conflicts). The single-process / asyncio model preserves the existing contract. Pillar I multi-tenant fan-out (one daemon per tenant) is a different shape — per-tenant ledger directories are operator-isolated by-construction.

3. **Ship a threaded daemon (one thread per per-stage worker).** Rejected per D332 — Python's GIL caps cooperative I/O concurrency to single-thread effective parallelism; asyncio's cooperative scheduling matches the workload shape without threading's complexity (per-thread lock acquire/release on the per-Person lock primitive + per-channel state). The sync per-channel SDK calls wrap via `asyncio.to_thread` — single-thread default with thread-pool wrapping for sync sub-calls.

4. **Defer the daemon module to Pillar H Week 2.** Rejected per the per-pillar-foundation precedent — Pillar G Week 1 (ADR-0050 D272) shipped the per-event-class observability primitive module + signature at Week 1 + the body at Week 2. The Week 1 commit's module shape is the structural commitment Weeks 2-12 satisfy; deferring would force the per-week-2+ ADRs to also pin the module shape (double-deciding the same question).

### D332 alternatives (concurrency framework)

1. **threading.** Rejected per the Python GIL constraint — even with `concurrent.futures.ThreadPoolExecutor`, the GIL serializes Python-bytecode execution; the per-stage worker pool's effective parallelism caps at network-I/O cooperative scheduling, which is exactly what asyncio provides without threading's per-thread state complexity + per-thread lock acquire/release. The Ledger.append's `fcntl.flock` would need per-thread lock-acquire semantics; asyncio's `asyncio.Lock` is simpler.

2. **multiprocessing.** Rejected per D331 alternative 2 — cross-process Ledger contention + cross-process OTel SDK init conflict + cross-process state divergence are all complexity-amplifiers. The single-tenant scope per ADR-0050 D276(d) does not need multi-process at Pillar H; multi-tenant fan-out at Pillar I uses one daemon process per tenant, which is the same single-process model replicated.

3. **anyio (asyncio compat layer).** Considered + REJECTED — anyio's value-add is trio compatibility; the framework's existing async code (Pillar G's OTel SDK init + the per-pillar tests) is asyncio-native; trio compatibility is not a Pillar H goal. Asyncio is the framework default + the operator-tested choice (every prior pillar's async code uses asyncio).

4. **gevent (greenlet-based).** Rejected — gevent's monkey-patching of the standard library introduces cross-cutting risk (the per-pillar SDKs (Gmail / LinkedIn / Twitter) + the per-pillar-G OTel SDK + the Pillar B migration framework's I/O paths all assume non-monkey-patched stdlib); the operator-debugging surface (e.g., `pdb`) breaks under monkey-patching. Asyncio's explicit-async / cooperative-yield model is more operator-debuggable.

### D333 alternatives (cross-pillar surface audit scope)

1. **Skip the audit at Pillar H Week 1; defer to Pillar H Week 6 + the per-pillar-week trajectory.** Rejected per every prior pillar's Week 1 audit caught ≥1 P2 — the audit's structural value is at Week 1, before the per-week 2+ commits accumulate symmetric-assumption regressions. Pillar G Week 1's audit caught the `funnel.py` ts-missing posture P2 + closed at Week 2 per the per-week-handoff convention.

2. **Audit ONLY the immediately-adjacent surfaces (Pillar B migration framework + Pillar G observability) — defer Pillar A/C/D/E/F to per-pillar-H per-week audits.** Rejected per the per-pillar-foundation precedent — every prior pillar audited ALL prior pillars at Week 1 (Pillar E's audit walked Pillar A/B/C/D; Pillar F's audit walked Pillar A/B/C/D/E; Pillar G's audit walked Pillar A/B/C/D/E/F). The audit's structural value is the cross-pillar back-audit discipline; narrowing the scope at Week 1 would lose the structural value.

3. **Audit at the per-pillar-foundation ADR level only — do NOT extend per-week.** Rejected — every prior pillar's audit grew with per-week extensions (Pillar G's audit grew from ~500 LOC at Week 1 to ~3100 LOC at Week 12 + Week 12 follow-up); the per-week extension is the per-week-reviewer's load-bearing checklist row. Without per-week extension, the per-week-reviewer pattern's value compounds less.

### D334 alternatives (exit-criterion vehicle scope)

1. **Ship the binding test in a separate `tests/test_daemon_24h.py` instead of extending the cross-pillar coherence vehicle.** Rejected per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 + ADR-0050 D275 — the single-file canonical vehicle (`tests/test_multi_channel_coherence.py`) is the operator-readable cross-pillar coherence surface. Separating Pillar H's binding test would split the operator's reading surface; the per-pillar-foundation precedent's single-file rationale generalizes.

2. **Use a real 24h run instead of a 100-stage-tick compressed fixture.** Rejected per the practical operator-time constraint — a 24h run cannot be a unit test; the structural commitment (zero-anomaly + crash-recovery + policy-hot-reload + observability-preservation + privacy-invariant) compresses to the 100-stage-tick fixture without losing coverage. Operators wanting a real 24h run wire it as a Pillar I CI surface per the OSS bring-up trajectory.

3. **Skip the binding test stub at Week 1; defer to Week 12.** Rejected per the per-pillar-foundation precedent — Pillar D + E + F + G Week 1 each shipped the binding test stub at Week 1 (un-skipped at Week 12). The Week 1 stub commits the structural commitment to the binding test's per-row verification scope; the per-pillar-week trajectory + the per-week-reviewer's per-row coverage check both reference the stub.

### D335 alternatives (per-daemon load-bearing invariants)

1. **Skip the FOUR invariants at Week 1; defer to per-pillar-week ADRs.** Rejected per the per-pillar-foundation precedent — Pillar D's CAN-SPAM legal-liability invariant landed at Pillar D Week 1 per ADR-0025 D97; Pillar F's FIVE-layer defense landed at Pillar F Week 1 per ADR-0038 D180; Pillar G's FOUR invariants landed at Pillar G Week 1 per ADR-0050 D276. The Week 1 invariants are the structural commitments Weeks 2-12 satisfy.

2. **Define only TWO invariants (graceful-shutdown + live-reload); defer process-isolation + atomicity-preservation to per-week.** Rejected — the four invariants are mutually-coupled (process-isolation enables the per-process Ledger contract; atomicity-preservation makes graceful-shutdown safe; live-reload requires the policy YAML to be re-parseable in-process). Splitting would weaken the structural commitment.

3. **Add a FIFTH invariant: per-stage backpressure (operator-visible queue depth).** Considered + REJECTED at Week 1 — backpressure is a Week 6 deliverable per D332's trajectory; the per-stage parallelism limits at `DaemonConfig.parallelism_limits` + the asyncio semaphore implementation are the Week 6 commitment. The Week 1 invariants are operator-visible-state commitments; backpressure is per-week-implementation discipline.

### D336 alternatives (per-event-class indexing trajectory)

1. **Persist the index to disk (write-through to a `~/.outreach-factory/index/` directory).** Rejected — the index is denormalized from the ledger (rebuildable per I3); persisting introduces cross-process state coherence concerns (the index's on-disk state can diverge from the ledger's on-disk state on crash). The in-memory + per-process index is structurally simpler + rebuilds at daemon startup in seconds (linear scan of the ledger's daily-rotation JSONL files; v2 scale ~100K events → ~30s startup time).

2. **Index every event class (not just the per-Person + per-stage classes).** Rejected at Pillar H Week 1 — the per-event-class indexing concern surfaces at the per-Person + per-stage + per-channel-latency primitives (the primitives Pillar G shipped + Pillar H's per-stage worker pool consumes); the other event classes (e.g., per-pass reconcile events, per-policy `policy_blocked`) are consumed by the funnel CLI's READ-ONLY walk at operator-invocation cadence, not at per-cron-interval cadence. The per-event-class indexing's value-add is the per-cron-interval surface; the per-operator-invocation surface walks the ledger directly without index need.

3. **Defer the indexing to Pillar I per-tenant scope.** Rejected per the Pillar G retrospective's "What surprised" item 4 — the per-Person primitives' per-call O(N) cost concern at v2 scale ~100K events is single-tenant at scale; the per-tenant indexing extension is Pillar I's value-add but the single-tenant indexing is Pillar H's structural fix. Pillar I authors extend the per-tenant labels; the structural fix is single-tenant first.

## Consequences

### Positive

- **Pillar H Week 1's framework decisions are pinned before per-week 2+ implementations.** D331 pins the daemon module shape; D332 pins the asyncio framework; D335 pins the four load-bearing invariants; D336 pins the per-event-class indexing trajectory. Weeks 2-12 satisfy the structural commitments without re-deciding the framework choice.
- **The per-pillar-foundation precedent extends to Pillar H.** Pillar D + E + F + G all shipped Week 1 with module shape + signature + binding test stub + cross-pillar audit + load-bearing invariants; Pillar H Week 1 follows the same pattern.
- **The per-week-reviewer's checklist for Pillar H carries the SIXTEEN-consecutive-weeks track record forward.** Cell-level matrix coverage + behavioral-passthrough + module-level docstring drift + cross-pillar back-audit + per-pillar mirror constants parity + legacy-state-vs-new-defense-layer tension + reason-precedence drift — all carry-forward.
- **The closed-set discipline extends to Pillar H** — `DAEMON_LIFECYCLE_STATES` + `DAEMON_NEW_EVENT_CLASSES` + `HEALTH_PROBE_OUTCOMES` are R031-shape regression-barriers + the Week 2 catalog extension's symmetric-assertion regression-barrier test catches drift.
- **The privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 holds across the daemon surface.** The `HealthStatus` dataclass + the `health_probe` event payload + every Pillar H ledger event excludes `person_id` / body content / source_list.
- **The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 extends to Pillar H** — the asyncio choice is the framework default; operators wanting trio / threading wire via the per-pillar-H framework-neutrality contract (TBD if the operator-deliberate alternative materializes; the Pillar H Week 5 implementation lands the structural surface).

### Negative

- **The Pillar H Week 1 commit is larger than Pillar G Week 1's commit** — Pillar G Week 1 shipped ~140 LOC at `observability.py` (signature only); Pillar H Week 1 ships the `orchestrator/daemon/` package at ~500 LOC (three modules: `__init__.py` + `runner.py` + `health.py`) + ADR-0060 ~500 LOC + the cross-pillar audit ~500 LOC + tests/test_daemon.py ~400 LOC + test_multi_channel_coherence.py Pillar H stubs ~200 LOC. The per-pillar-foundation precedent's per-week-1-commit-size growth across Pillar D + E + F + G + H is monotonic (each Week 1 ships more than the prior); Pillar H's growth reflects the daemon's structural complexity.
- **The daemon's `init_daemon` body at Week 2 + the per-week-3+ bodies represent significant per-week implementation work.** The per-week-2+ ADRs (ADR-0061 through ADR-0069) will be commensurately substantial; the per-pillar-week trajectory budget (12 weeks) matches Pillar G's (12 weeks for the framework adoption pillar).
- **The single-tenant scope per D335 invariant 1 + ADR-0050 D276(d) is a deferral to Pillar I.** Operators wanting multi-tenant at the framework boundary (e.g., a single daemon process serving multiple tenant ledgers) cannot get it from Pillar H; the per-tenant audit-tooling at Pillar I is the operator-visible delivery.
- **The asyncio framework choice locks-in Python 3.7+ + the asyncio idiom.** Operators preferring trio / curio / gevent wire via the per-pillar-H framework-neutrality contract (TBD); the framework default + the test substrate use asyncio. The Pillar H Week 5+ implementation surfaces the contract's edges.

### Neutral

- **No new pip dependencies at Pillar H Week 1.** The daemon module's Week 1 surface is stdlib (`dataclasses` + `pathlib` + `re`); the Week 2+ bodies add `aiohttp` (for the health endpoint at Week 4 per D334) + the existing Pillar G OTel SDK + Prometheus deps.
- **No new ledger migrations at Pillar H Week 1.** The pending count stays at 19 (UNCHANGED from Pillar G Week 12). Pillar H MAY ship migrations if the per-event-class index requires per-event indexing per D336's trajectory (Pillar H Week 8-9 scope).
- **No new event classes at Pillar H Week 1 in `EVENT_CLASS_CATALOG`.** The FIVE new event classes at `DAEMON_NEW_EVENT_CLASSES` are named at design time; the Week 2 catalog extension is the symmetric-assertion regression-barrier test target.
- **No changes to the Pillar G framework adoption surfaces.** OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + Grafana per-Person dashboard + funnel CLI extension all preserve verbatim. The daemon CONSUMES these surfaces.
- **No changes to the binding exit-criterion tests of Pillar D / E / F / G.** All four STAY GREEN across the Pillar H Week 1 commit + the Pillar H Week 1 follow-up commit (if any P2s surface per the per-week-reviewer pattern).

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — the daemon's per-stage worker pool emits structured events to the ledger; the ledger remains the source of truth. The per-event-class index per D336 is denormalized (rebuildable per I3) + invalidated on `Ledger.append`.
- **I2 (Atomicity contract).** Compliant + EXTENDED — D335 invariant 2 (atomicity-preservation-across-process-boundary) is the structural commitment. The daemon contributes NO new state that bypasses the ledger; the per-channel two-phase intent/confirmed pairs per ADR-0014 D33 still complete via the reconcile loop.
- **I3 (Single source of truth).** Compliant — every observability primitive's aggregation derives from the per-call ledger walk OR the per-event-class index (rebuildable from the ledger); no cached cross-process state.
- **I4 (Determinism).** Compliant — D334 + the binding exit-criterion test ROW 5 + the funnel CLI's byte-identical contract per ADR-0031 D140 all preserve.
- **I5 (Refuse loud).** Compliant — the daemon's pre-flight checks (migrations applied + policy loaded + OTel SDK initialized + Prometheus exporter listening) MUST all succeed before transition to `"ready"`; failure refuses-loud via the `daemon_started` event's absence + operator-visible exit code.
- **I6 (No silent state).** Compliant — every per-stage tick's structural change emits a ledger event; every operator-visible state derives from the ledger walk; the per-event-class index is operator-visible via the daemon's startup `daemon_started` event payload + the per-pillar-H Grafana panel.
- **I7 (Refuse loud on broken pipelines).** Compliant — D335 invariant 3 (graceful-shutdown) + invariant 4 (live-reload-policy) both refuse-loud on failure (e.g., policy parse error surfaces in the `policy_reloaded` event's `status: failed_unchanged` + `parse_error` field). The Pillar A policy engine's existing refuse-loud per ADR-0001 D2 carries through.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — D335 invariant 1 + every Pillar H ledger event payload + the `HealthStatus` dataclass + the per-event-class index all exclude `person_id` / body content / source_list. The Pillar H per-week-reviewer's privacy invariant check is the structural barrier.
- **The channel-on-every-event invariant per ADR-0014 D33** — Unaffected — Pillar H's daemon does NOT introduce new event classes that carry `channel` directly (the FIVE Pillar H event classes are daemon-lifecycle events without channel context); the per-channel two-phase commit per ADR-0014 D33 preserves verbatim at the dispatcher layer.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — the daemon does NOT modify the per-send gate; the CAN-SPAM compliance per Pillar D preserves verbatim.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — the daemon does NOT modify the Layer 1-5 surfaces; the Pillar F primitive surfaces + Layer 5 backstop preserve verbatim.
- **The one-CLI-invocation invariant per ADR-0050 D276(a)** — Preserved — operators invoking `python orchestrator/funnel.py --since N` from outside the daemon get the same byte-identical output per ADR-0031 D140; the daemon's per-event-class index per D336 is daemon-process-local + does NOT alter the funnel CLI's output shape.
- **The READ-ONLY funnel CLI contract per ADR-0059 D325** — Preserved — the daemon does NOT modify `funnel.build_report`; the per-event-class index is internal to the daemon process + transparent to the funnel CLI.
- **The byte-identical determinism contract per ADR-0031 D140** — Preserved — the daemon's per-event-class index reflects the ledger's current state exactly; the funnel CLI's output stays byte-identical across consecutive invocations against fixed ledger state.

## Downstream pillar impact

- **Pillar I (OSS bring-up + multi-tenant).** Per-tenant fan-out at the daemon process boundary — one daemon process per tenant; per-tenant ledger directory isolation; per-tenant policy YAML files; per-tenant Grafana folder isolation per Pillar G Week 4 + the per-tenant audit-tooling trajectory. The Pillar I author MAY extend `DAEMON_LIFECYCLE_STATES` with `"paused"` for tenant-level pause without process exit + extend the per-event-class index with per-tenant labels. Pillar I's CI bring-up consumes the daemon's docker-compose surface (one container per daemon process).
- **Pillar J (Security + compliance).** GDPR-purge transaction per ADR-0050 §Downstream extends to the per-event-class index — a per-Person purge invalidates the per-Person index entries + emits the per-Person purge event. The daemon's per-stage worker pool respects the purge — operators invoking `policy.py forget --person <id>` see the purge propagate to the in-memory index + the per-stage worker pool's queue. OAuth token rotation per Pillar J extends to the daemon's startup — the daemon refreshes per-channel tokens at pre-flight + emits `auth_token_refreshed` events. SLSA supply-chain attestation per Pillar J extends to the daemon's container image + the systemd service file.

## Migration / rollout

- **Operator-side action required at Pillar H Week 1 upgrade:** **NONE — content-additive at the framework boundary.** The Week 1 commit adds the `orchestrator/daemon/` package + the tests + the ADR + the audit doc + the test class stubs in `tests/test_multi_channel_coherence.py`. Operators continue to invoke `python orchestrator/funnel.py --since N` + the per-skill `claude /find-leads` / `/research-prospect` / `/draft-outreach` / `/send-outreach` surfaces unchanged.
- **Recommended (optional):** operators wanting to PREVIEW the Pillar H daemon surface at Week 1 do NOT have a body to invoke (the Week 1 commit ships signatures + `NotImplementedError` raises); the operator-visible daemon ships at Pillar H Week 2+.
- **No ledger schema migration** — Week 1 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes in `EVENT_CLASS_CATALOG`** — Week 1 ships the FIVE classes at `DAEMON_NEW_EVENT_CLASSES` as a named-at-design-time closed-set; the Week 2 catalog extension is the symmetric-assertion regression-barrier test target.
- **No new pip dependencies at Pillar H Week 1** — the daemon module's Week 1 surface is stdlib (`dataclasses` + `pathlib` + `re`); Week 4 adds `aiohttp` for the health endpoint.

## Existing-operator seed

Operator action required at Pillar H Week 1: **NONE — content-additive at the framework boundary.**

Recommended (optional): operators following the Pillar H per-week trajectory consume the per-week handoff docs at `.planning/HANDOFF-pillar-h-week-N.md` + the per-week ADRs at `docs/adr/006N-pillar-h-week-N-*.md`. Operators waiting for the Pillar H daemon land the body at Pillar H Week 5+ per D332's trajectory.

## References

- **ADR-0059** (Pillar G Week 12 — binding exit-criterion + funnel CLI extension + Pillar G Stable flip + retrospective + handoff to Pillar H). D325-D330. **D325's READ-ONLY funnel CLI contract preserves across the daemon process boundary** per ADR-0060 D335 invariant 2.
- **ADR-0058** (Pillar G Week 10-11 — per-Person observability surface adapters consuming Pillar F's four event classes + Layer 5 `reconcile_drift.reason` value). D319-D324. **D321's BOTH-legacy-and-new reason-precedence drift discipline preserves across the daemon.**
- **ADR-0057** (Pillar G Week 9 — cost dashboard rendering + per-source `cost_incurred` aggregation primitive). D314-D318.
- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector + `slo_violation_detected` event class producer + Slack webhook dispatcher + R032 synthetic-event exclusion + `_SLO_NAMES` closed-enum). D307-D313.
- **ADR-0055** (Pillar G Week 6 — Per-stage span instrumentation at the per-pillar Python call sites + send-latency Histogram dispatcher integration). D300-D306. **The daemon's per-stage worker pool consumes the per-stage spans + the dispatcher Histogram preserve verbatim.**
- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization + canonical Tracer scope + per-stage `traced_stage` context manager). D294-D299. **The daemon's startup wires `init_otel_tracer_provider` per Week 2 + the per-stage spans wrap the daemon's per-stage worker pool's per-stage tick.**
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + per-channel send-latency Histogram + reconcile success ratio ObservableGauge + first Grafana-as-code dashboard). D288-D293. **D291's Prometheus HTTP exposition server's `127.0.0.1` security-by-default bind generalizes to the daemon's health endpoint per ADR-0060 D334.**
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope). D282-D287. **D286's framework-neutrality contract generalizes to the asyncio framework choice per ADR-0060 D332.**
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. **The per-pillar-foundation precedent for Pillar H Week 1's structure.**
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip + retrospective). D262-D271. **The Layer 5 backstop preserves verbatim across the daemon.**
- **ADR-0038** (Pillar F foundation — FIVE-layer hallucination-detection defense). D180. **The Pillar F FIVE-layer defense preserves verbatim across the daemon.**
- **ADR-0037** (Pillar E Week 12 — Pillar E Stable flip). D172. **The cumulative single-file coherence vehicle's ~7500 LOC split threshold remains LIVE at Pillar H Week 1 (~9000 LOC); Pillar H Week 12 may surface the split argument again.**
- **ADR-0033** (Pillar E Week 2 — pre-enrichment dedup primitive). D149-D153. **The discovery dedup primitive surface preserves verbatim across the daemon.**
- **ADR-0032** (Pillar E foundation — discovery quality + lineage). D148's privacy invariant. **Preserved across the daemon.**
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract). **Preserved across the daemon process boundary.**
- **ADR-0025** (Pillar D foundation). D97 (legal-liability invariant — CAN-SPAM compliance). D101 (Pillar D foundation's single-file coherence vehicle). **The CAN-SPAM invariant preserves verbatim across the daemon.**
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant). **Preserved across the daemon's per-stage dispatch surface.**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). **R032's synthetic-event exclusion preserves verbatim across the daemon.**
- **ADR-0009** (Pillar B foundation — migration framework + idempotent auto-apply contract). D9. **The daemon's `init_daemon` body at Week 2 wires `MigrationRunner.apply()` at the asyncio startup sequence per ADR-0060 D335 invariant 2.**
- **ADR-0001** (Pillar A foundation — declarative policy engine). D2 (refuse-loud convention). **Preserved across the daemon's pre-flight gate.**
- `.planning/REVIEW-pillar-h-surface-audit.md` — cross-pillar surface audit (Pillar H Week 1 baseline; Week 2-12 sections per the per-week-handoff convention).
- `.planning/HANDOFF-pillar-h-week-1.md` — Pillar H Week 1 close summary + handoff to Pillar H Week 2.
- `.planning/RETRO-pillar-g.md` — Pillar G retrospective (calibration + what to do differently in Pillar H + carry-forwards into Pillar H).
- `docs/PILLAR-PLAN.md` §2 Pillar H + §6 Pillar H row Week 1 status flip + Notes column appended Week 1 close summary.
- `docs/RISK-REGISTER.md` R037 + R038 + R039 NEW.
- `docs/SOURCES-OF-TRUTH.md` — daemon-state row added with Pillar H Week 1 ADR-0060 reference.
- `orchestrator/daemon/` (NEW package: `__init__.py` + `runner.py` + `health.py`) — Pillar H Week 1 module shape + closed-sets + dataclasses + signatures per D331.
- `tests/test_daemon.py` (NEW; ~400 LOC + 34 contract-level tests) — covers the closed-sets + dataclass invariants + primitive signatures.
- `tests/test_multi_channel_coherence.py` extended with `TestPillarHDaemon` × 10 + `TestPillarHDaemonObservabilityIntegration` × 3 + `TestPillarHExitCriterion` × 1 stubs (14 rows skipped at Week 1; un-skipping progressively per D332's trajectory).
