"""Pillar H Week 1 + Week 2 + Week 3 + Week 4 + Week 4 follow-up + Week 5
+ Week 5 follow-up + Week 6 + Week 6 follow-up + Week 7 + Week 7 follow-up
+ Week 8 + Week 8 follow-up + Week 9 + Week 9 follow-up + Week 10-11 + Week 10-11 follow-up — daemon foundation (per ADR-0060
D331-D336 + ADR-0061 D337-D340 + ADR-0062 D341-D344 + ADR-0067 D359-D363
+ W8 follow-up P2-1 closure (the SEVENTH ADR-vs-actual-impl drift in
Pillar H — EventClassIndex catalog scope extended to EVENT_CLASS_CATALOG
∪ OBSERVABILITY_NEW_EVENT_CLASSES per per-pillar mirror constants parity
with Pillar G's collect_event_class_snapshots consumer surface); Week 1 follow-up
extends public surface with :data:`DAEMON_POLICY_RELOAD_SIGNALS` +
:data:`POLICY_RELOAD_STATUSES` closed-sets per per-week-reviewer P3-2
+ P3-3 closures; Week 2 lands the :func:`init_daemon` body + the
:func:`build_daemon_started_payload` emit-shape factory + extends
:data:`observability.EVENT_CLASS_CATALOG` with the FIVE
:data:`DAEMON_NEW_EVENT_CLASSES` per ADR-0061 D338 + closes the Week 1
carry-forwards P3-1 startup ordering + P3-2 OTel set-once at daemon
startup per ADR-0061 D340; Week 2 follow-up extends :func:`_validate_config`
with P2-1 refuse-loud rules for next-tier invariant-bearing fields +
extends :func:`build_daemon_started_payload` with P2-2 input validation
per the Pillar G raw-primitive factory convention + adds P3-1 mirror
parity for :data:`_DAEMON_VERSION` ↔ :data:`observability._SERVICE_VERSION`
+ cell-coverage tests for :func:`_default_policy_load` per P3-2 +
cross-OS docstring note + known-config regression-barrier per P3-3 +
kwarg-override tests per P3-4 + per-Pillar-H locality docstring
extension per P3-5 + lazy-import consolidation per P3-6 + framework-
neutrality + OTel-after-policy rationale doc paragraphs per P3-7 +
P3-8; Week 3 ships :func:`attach_signal_handlers` body wiring asyncio
:meth:`AbstractEventLoop.add_signal_handler` for SIGTERM + SIGINT +
SIGHUP per ADR-0062 D341 + :meth:`DaemonRunner.shutdown` body with
lifecycle state transitions through ``"draining"`` → ``"stopped"``
via :func:`object.__setattr__` frozen-dataclass escape hatch per
ADR-0062 D342 + :func:`build_daemon_stopping_payload` +
:func:`build_daemon_stopped_payload` emit-shape factories per
ADR-0062 D343 + :data:`SHUTDOWN_REASONS` (``sigterm``/``sigint``/
``operator_requested``) + :data:`DAEMON_EXIT_REASONS` (``clean``/
``timeout``/``crash``) closed-sets per ADR-0062 D344; Week 3 follow-
up closes per-week-reviewer P2-1 ``_emitted_by`` audit-marker drift
across the THREE Pillar H emit-shape factories via NEW
:data:`EMITTED_BY` module constant + the Week 3 main commit's
docstring + ADR-0062 D343 narrative corrections; closes P2-2
``started_at_ts`` parse-after-state-transition concern by moving
the strptime to the TOP of :meth:`DaemonRunner.shutdown`; closes
P3-1 + P3-2 + P3-3 + P3-4 + P3-5 + P3-6 per the Week 3 follow-up
disciplines; Week 4 ships :func:`serve_health_endpoint` body wiring
asyncio-aiohttp HTTP server on ``127.0.0.1:8080`` per R036 +
``health_probe`` rate-limit per R038 +
:func:`build_health_probe_payload` emit-shape factory + per-pillar-H
Grafana panel at ``infra/grafana/dashboards/per_daemon.yml`` + NEW
pip dependency :mod:`aiohttp` per ADR-0063 D345-D348; Week 4
follow-up closes per-week-reviewer P2-1 framework-neutrality text
drift at ADR-0063 D348 (the THIRD ADR-vs-actual-impl drift caught
by the per-week-reviewer's cross-pillar back-audit discipline —
the seam kwargs substitute BACKENDS NOT HTTP server choice) +
P2-2 :func:`_compute_health_status` ValueError swallow vs
:meth:`DaemonRunner.shutdown` refuse-loud asymmetry documented +
P3-1 / P3-2 module-docstring HEADER drift across :mod:`__init__`
+ :mod:`runner` naming Week 4 + P3-3 / P3-4 / P3-5 Week 4
placeholder semantics documented + P3-6 ``bind_addr`` refuse-loud
at :func:`serve_health_endpoint` boundary + P3-7 ``aiohttp`` upper
bound at ``aiohttp>=3.9,<4`` + P3-8 / P3-9 Pillar I trajectory
documentation + P3-10 :func:`serve_health_endpoint` return type
narrowed + NEW-1 :class:`HealthStatus.__post_init__` validation +
NEW-2 Content-Type test + NEW-3 Pillar I middleware trajectory
documented; Week 5 ships :meth:`DaemonRunner.run` body wiring the
asyncio event loop per ADR-0064 D349-D352 — initializing→ready
transition + ``daemon_started`` emit + signal handler wiring +
health endpoint start + per-stage worker pool SKELETON wrapped in
:func:`observability.traced_stage` per ADR-0055 D300 + graceful
shutdown coordination via :meth:`AppRunner.cleanup`; Week 5
follow-up closes per-week-reviewer P1-1
``traced_stage(stage)`` vs production
``traced_stage(stage, operation)`` signature drift — the FOURTH
ADR-vs-actual-impl drift in Pillar H (the prior three: W2 P3-8
OTel Resource rationale; W3 P2-1 ``_emitted_by`` audit-marker; W4
P2-1 framework-neutrality text); the Week 5 main commit's body
invoked with one arg + 8 tests passed BUT production default
broke on the FIRST per-stage tick + the W5 follow-up commit
aligns body + spy + ADR-0064 D350 narrative; closes P2-1
pre-iteration sanity-tick redundancy via removal; closes P2-2
cleanup-on-exception path regression-barrier gap; closes P2-3
``tick_seconds <= 0`` boundary refuse-loud per Pillar H Week 2
follow-up P2-1's per-tier-invariant-field discipline; closes P2-4
:func:`asyncio.get_running_loop` cryptic-error via
operator-readable wrap; closes P3-1 + NEW-1 seven-step vs
eight-step ordering drift via docstring + ADR-0064 D349
alignment; closes P3-2 ``_StubAppRunner`` DRY violation via
shared :mod:`tests._daemon_test_helpers` per the W3 follow-up
P3-6 closure precedent; closes P3-3 ``started_at_ts`` past-date
magic constant via module-level named constant; closes P3-4
``loop`` kwarg type narrowing from ``Any | None`` to
``asyncio.AbstractEventLoop | None``; closes P3-5
``health_app_runner`` naming-conflict rename to
``health_aiohttp_runner``; closes P3-6 + NEW-3 + NEW-4
lazy-import inconsistency via module-top imports of
:mod:`orchestrator.ledger` + :mod:`orchestrator.observability`
(health.py stays lazy per circular-import-avoidance); closes
P3-8 ``emit_fn`` Ledger lazy-construction trajectory docs; closes
P3-9 :mod:`orchestrator.daemon.health` module-docstring drift via
Week 5 follow-up naming extension per the W3 follow-up P3-5
closure's materially-unchanged-module scope; REFUTES NEW-2
``startup_seconds`` rounding concern (factory rounds at boundary
per ADR-0031 D140); closes NEW-5 ``object.__setattr__``
escape-hatch run()-side regression-barrier gap; closes NEW-6
:exc:`asyncio.CancelledError` propagation documentation); Week 6
ships per-stage worker pool actual parallelism via
:class:`asyncio.Semaphore` bounded by
:attr:`DaemonConfig.parallelism_limits[stage]` at the
per-FUNNEL-stage granularity per ADR-0065 D353-D355 + NEW
:func:`build_daemon_stage_saturated_payload` raw-primitive
emit-shape factory + NEW ``"daemon_stage_saturated"`` event
class joins :data:`DAEMON_NEW_EVENT_CLASSES` (5 → 6) +
:data:`observability.EVENT_CLASS_CATALOG` (24 → 25) + funnel-
vs-observability stage bridging via TWO ORTHOGONAL per-tick
iterations preserving the two intentionally-distinct
closed-sets per Pillar H Week 1 follow-up P3-5 closure + ONE
coherence stub un-skipped at Week 6
(:meth:`TestPillarHDaemon.test_per_stage_parallelism_limit_enforced`);
Week 6 follow-up closes per-week-reviewer P2-1 behavioral-
passthrough gap at the body-level Semaphore saturation
emit path via NEW :func:`semaphore_factory_fn` test-only
seam at :meth:`DaemonRunner.run` + NEW
:meth:`TestDaemonRunBody.test_daemon_stage_saturated_emits_when_semaphore_locked`
regression-barrier; closes P2-2 ADR-0065 D353 narrative-
vs-code-example INTERNAL drift (the FIFTH ADR-vs-actual-
impl drift in Pillar H caught by the per-week-reviewer's
cross-pillar back-audit discipline); closes P3-1 + P3-2 +
P3-3 + NEW-2 lazy-import inconsistency via STYLE
STANDARDIZATION across the THREE
:data:`funnel._PILLAR_G_PIPELINE_STAGES` lazy-import sites
at runner.py (all three now use ``from orchestrator.funnel
import _PILLAR_G_PIPELINE_STAGES``; the prior
``_validate_config`` site used ``import funnel as _funnel``)
+ extended import-block comment naming the deeper
production-fragility rationale (funnel uses bare-name
``import ledger`` requiring the conftest.py sys.path shim
which is test-only) — the lazy form is REQUIRED not
optional; closes P3-4 + NEW-1 :mod:`orchestrator.observability`
"Last reviewed" line bump naming Pillar H Week 2 + Week 6
catalog extensions; closes P3-5 + P3-6 + P3-7 + NEW-3 +
NEW-6 + NEW-7 "FIVE → SIX" docstring drifts at NINE sites
(runner.py:409 closed-set comment + __init__.py:143-145
public-surface bullet + test_observability.py × 2 sites +
test_daemon.py × 3 sites + test_multi_channel_coherence.py
× 1 site); closes P3-8 :file:`infra/grafana/dashboards/per_daemon.yml`
"FIVE → SIX" drift at panel 4 + carry-forwards section
Week 5 → Week 6 attribution correction + dashboard header
"Week 4 → Week 4 + Week 6"; closes P3-9 + P3-10 factory
docstring semantic clarification at ``in_flight_count`` +
``asyncio.Semaphore`` waiter-case asymmetry; closes P3-11
(folded into P2-1's regression-barrier — the new test
verifies the body's iteration source is
:data:`_PILLAR_G_PIPELINE_STAGES` via the per-funnel-stage
saturation emit's ``stage`` field distribution); REFUTES
pre-identified weak spot #6 (factory's upper-edge IS
implicitly tested via ``_valid_kwargs``); ZERO new ADRs
(the follow-up's fixes are: ADR-0065 D353 narrative
correction + module-top imports + closed-set docstring
fixes + per_daemon.yml updates + the new test-only seam
+ the behavioral-passthrough regression-barrier — all in
the spirit of ADR-0065's existing decisions per the per-
pillar-foundation precedent from Pillar G Week 12 follow-up
`43612a8` + Pillar H Week 1-5 follow-ups); Week 7 ships
:meth:`DaemonRunner.reload_policy` body per ADR-0066 D356
+ NEW :func:`build_policy_reloaded_payload` factory per
ADR-0066 D357 + reconcile passes integration via
:data:`_STAGE_TO_PASSES` per-funnel-stage → per-pass
mapping + :func:`_default_dispatch_for_stage` async helper
invoking :func:`reconcile.reconcile` via
:func:`asyncio.to_thread` per ADR-0066 D358 (pure-framework
passes only at v1 — channel-dispatch deferred to Week 8+);
:class:`DaemonConfig` extended with THREE optional Path
fields (``policy_dir`` / ``people_dir`` /
``suppressions_dir``); :class:`DaemonRunner` extended with
``policy_state: _PolicyState`` mutable holder for runtime
policy state; ONE coherence stub un-skipped at Week 7
(:meth:`TestPillarHDaemon.test_sighup_triggers_policy_reload`);
Week 8 ships :class:`EventClassIndex` +
:class:`PersonEventIndex` in-memory mutable-holder
dataclasses per ADR-0067 D359 + NEW
:func:`_materialize_indexes` single-walk dual-index
materialization helper per ADR-0067 D360 + NEW
:func:`init_daemon` Step 8 (inserted between Prometheus
exposition Step 7 + the now-renumbered Step 9 DaemonRunner
construction) wiring the materialization at daemon startup
per ADR-0060 D336 (R039 mitigation — Pillar G per-Person
primitives' per-call O(N) ledger walk at v2 scale ~100K
events drops to O(M_class) when daemon-process consumers
pass the ``event_class_index`` kwarg per ADR-0067 D361);
:class:`DaemonRunner` extended with TWO new fields
(``event_class_index`` + ``person_event_index``); NEW
``index_materialize_fn`` test-only seam at
:func:`init_daemon`; per-Person primitives at
:mod:`orchestrator.observability` extended with optional
``event_class_index`` kwarg per ADR-0067 D361 preserving
the Pillar G READ-ONLY funnel CLI contract per ADR-0059
D325 (the kwarg's None default preserves the existing
ledger-walk behavior verbatim); ONE coherence stub
un-skipped at Week 8
(:meth:`TestPillarHDaemon.test_per_event_class_index_at_startup`);
Week 9 ships per-event-class index invalidation on
:meth:`Ledger.append` per ADR-0067 D362 (W9 extension to
ADR-0067 per ADR-0060 D336's per-week trajectory) via NEW
:meth:`Ledger.append_observer` post-append observer seam at
:mod:`orchestrator.ledger` (cross-pillar surface extension) +
NEW :func:`_invalidate_indexes_on_append` per-event
invalidation helper + NEW :func:`_install_index_invalidation_observer`
registration helper invoked at NEW :func:`init_daemon` Step 8.5 +
NEW :attr:`DaemonRunner.ledger` field lifting the daemon's
Ledger instance out of the Week 8 init_daemon-body-local
scope + NEW :attr:`EventClassIndex._last_updated_at_ts` +
:attr:`PersonEventIndex._last_updated_at_ts` Unix-epoch
float fields advanced on every index update + NEW
:func:`observability.register_daemon_index_observable_gauge`
registration helper for the operator-visible freshness gauge
``outreach_factory_daemon_index_last_updated_timestamp`` per
ADR-0067 D363 + the Grafana panel #6 at
:file:`infra/grafana/dashboards/per_daemon.yml` rendering
``time() - <gauge>`` as the index age in seconds (RED if
> 60s — operator SLO signal for invalidation stalls) + ONE
coherence stub added + un-skipped at Week 9
(:meth:`TestPillarHDaemon.test_index_invalidates_on_ledger_append`).

This package is the Pillar H daemon + dispatcher per PILLAR-PLAN §2 Pillar H.
Pillar H replaces the ``claude -p`` loop with a standalone Python daemon
that operational systems can manage with standard ops tooling: systemd /
healthchecks / graceful shutdown / live policy reload / structured logs /
OTel hooks (the Pillar G framework adoption per ADR-0050 D273 +
ADR-0052-0056 preserves verbatim across the daemon).

Pillar H Week 1 scope per ADR-0060 D331 — **module shape + dataclasses
+ closed-sets + primitive signatures only**. The bodies land at Pillar H
Week 2+ per the per-pillar-foundation precedent (Pillar G Week 1 shipped
`MetricSnapshot` + `EVENT_CLASS_CATALOG` + `collect_event_class_snapshots`
signature; Week 2 shipped the body).

Public surface (re-exported below):

* :class:`DaemonConfig` — frozen dataclass; daemon initialization
  parameters (vault dir, ledger dir, parallelism limits, health port,
  graceful shutdown deadline, policy reload signal).
* :class:`DaemonRunner` — the main-loop primitive. Owns the per-stage
  dispatch + the backpressure + the lifecycle transitions + the
  signal handlers + the health endpoint. Week 1 signature only; Week
  5+ body.
* :class:`HealthStatus` — frozen dataclass; the readiness probe's
  output payload.
* :class:`PolicyReloadResult` — frozen dataclass; the SIGHUP-driven
  policy reload outcome.
* :data:`DAEMON_LIFECYCLE_STATES` — closed-set of the FOUR daemon
  lifecycle states (initializing / ready / draining / stopped).
* :data:`HEALTH_PROBE_OUTCOMES` — closed-set of the THREE health
  probe outcomes (ok / degraded / unhealthy).
* :data:`DAEMON_NEW_EVENT_CLASSES` — closed-set of the SIX new
  Pillar H event classes (``daemon_started`` + ``daemon_stopping``
  + ``daemon_stopped`` + ``policy_reloaded`` + ``health_probe`` +
  ``daemon_stage_saturated``; Pillar H Week 2 added FIVE per ADR-0061
  D338 + Pillar H Week 6 added ``daemon_stage_saturated`` per ADR-0065
  D355; the W6 follow-up P3-6 closure surfaces the FIVE → SIX docstring
  drift the W6 main commit author missed at this site).
* :data:`DAEMON_POLICY_RELOAD_SIGNALS` — closed-set of valid signal
  names for :attr:`DaemonConfig.policy_reload_signal` (Pillar H Week
  1 follow-up P3-2 closure; ``None`` is the operator-deliberate
  opt-out documented separately).
* :data:`POLICY_RELOAD_STATUSES` — closed-set of valid
  :attr:`PolicyReloadResult.status` values (``applied`` /
  ``failed_unchanged``; Pillar H Week 1 follow-up P3-3 closure).
* :func:`init_daemon` — instantiate a :class:`DaemonRunner` from a
  :class:`DaemonConfig` (Week 1 signature; **Week 2 body** per
  ADR-0061 D337 — applies migrations → loads policy → initializes
  OTel SDK → starts Prometheus exporter → constructs runner in
  ``"initializing"`` state; accepts test-only seam kwargs per the
  Pillar G TEST-ONLY convention).
* :func:`build_daemon_started_payload` — emit-shape factory for the
  ``daemon_started`` event per ADR-0061 D339 (Week 2 ships the
  factory; Week 5+ ships the actual transition + emit).
* :func:`build_daemon_stage_saturated_payload` — emit-shape factory
  for the ``daemon_stage_saturated`` event per ADR-0065 D355 (Pillar
  H Week 6 NEW). 5-key payload: pid + stage + parallelism_limit +
  in_flight_count + ``_emitted_by="daemon"``. Refuses-loud on
  observability stages per the W6 P3-5 closure's funnel-vs-
  observability orthogonality.
* :func:`build_policy_reloaded_payload` — emit-shape factory for the
  ``policy_reloaded`` event per ADR-0066 D357 (Pillar H Week 7 NEW).
  6-key payload: pid + source_path + prior_content_hash +
  new_content_hash + status + ``_emitted_by="daemon"``. Refuses-loud
  on invalid status per the closed-set + the Pillar H Week 1
  follow-up P3-3 closure's regression-barrier.
* :func:`attach_signal_handlers` — wire SIGTERM + SIGINT (graceful
  shutdown) + SIGHUP (policy reload) to a :class:`DaemonRunner` (Week
  3 body).
* :func:`serve_health_endpoint` — HTTP health endpoint on the
  configured port (Week 4 body).
* :class:`EventClassIndex` — Pillar H Week 8 NEW per ADR-0067 D359.
  In-memory mutable-holder dataclass keyed by event class; the
  daemon-process per-Person primitive consumer surface per ADR-0067
  D361 gets O(M_class) per-call cost instead of the O(N) full-
  ledger walk. Populated at :func:`init_daemon` Step 8 by walking
  the ledger once; rebuildable from the ledger per I3; Week 9
  ships invalidation on :meth:`Ledger.append`. **W8 follow-up P2-1
  closure** — catalog scope EXTENDED to
  ``EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES``
  mirroring the Pillar G :func:`collect_event_class_snapshots`
  consumer surface precedent (the SEVENTH ADR-vs-actual-impl drift
  in Pillar H caught by the per-week-reviewer's cross-pillar
  back-audit discipline).
* :class:`PersonEventIndex` — Pillar H Week 8 NEW per ADR-0067 D359.
  In-memory mutable-holder dataclass keyed by ``person_id``;
  future Pillar I per-tenant per-Person operator dashboard consumer
  surface.

**Pillar H Week 9 internal helpers** (NOT in :data:`__all__` per
the Python convention for ``_``-prefixed names; importable via
``from orchestrator.daemon.runner import _install_index_invalidation_observer``
+ ``from orchestrator.daemon.runner import _invalidate_indexes_on_append``
for direct test consumption + Pillar I per-tenant audit-tooling
extension):

* :func:`runner._invalidate_indexes_on_append` — Pillar H Week 9
  NEW per ADR-0067 D362 (W9 extension to ADR-0067 per ADR-0060
  D336). Per-event invalidation helper mutating both
  :class:`EventClassIndex` + :class:`PersonEventIndex` in-place on
  each :meth:`Ledger.append`; advances both indexes'
  ``_last_updated_at_ts`` for the operator-visible Prometheus
  freshness gauge per ADR-0067 D363.
* :func:`runner._install_index_invalidation_observer` — Pillar H
  Week 9 NEW per ADR-0067 D362. Registration helper invoked at
  :func:`init_daemon` Step 8.5 (NEW between Step 8 materialization
  + the Step 9 DaemonRunner construction); registers a
  closure observer on the daemon's :class:`Ledger` instance that
  delegates to :func:`_invalidate_indexes_on_append` per append.

**Pillar H load-bearing invariants** per ADR-0060 D335 (four invariants,
analogous to Pillar G Week 1 four invariants per ADR-0050 D276):

1. **Process-isolation** — each daemon instance is one OS process; multi-
   tenant fan-out (Pillar I scope) wires one daemon per tenant. The
   per-process Ledger contract (ADR-0050 D276(d) single-tenant) preserves.
2. **Atomicity-preservation-across-process-boundary** — the ledger's
   append-only contract per I2 holds across daemon restarts; the
   two-phase intent/confirmed pairs per ADR-0014 D33 still complete
   via reconcile passes (Pass A through O) if the daemon crashes
   between phases. The daemon contributes NO new state that bypasses
   the ledger.
3. **Graceful-shutdown** — on SIGTERM / SIGINT the daemon transitions
   to ``draining``, completes in-flight per-stage tasks within the
   configured deadline, emits ``daemon_stopping`` + ``daemon_stopped``
   ledger events, then exits with code 0. The reconcile loop is the
   recovery backstop for tasks that don't complete within the deadline.
4. **Live-reload-policy** — on SIGHUP the daemon re-reads the policy
   YAML files (per Pillar A) + emits ``policy_reloaded`` with the prior
   + new content hashes; no restart required. Cooldown / suppression
   / sending-window / budget rule changes take effect at the next
   per-stage tick.

Per-pillar framework dependencies (compounded across Pillar A-G):

* **Pillar A** policy engine — the daemon's pre-flight gate at each
  per-stage tick consults :func:`orchestrator.policy.evaluate` per the
  existing convention; SIGHUP triggers a re-read.
* **Pillar B** migration framework — the daemon runs pending migrations
  at startup before entering the ``ready`` state (per ADR-0009 D9's
  "migrations are idempotent + auto-applied" contract).
* **Pillar C** per-channel two-phase commit — the daemon's per-stage
  dispatch preserves the existing per-channel intent/confirmed shape
  per ADR-0014 D33.
* **Pillar D** reconcile loop — the daemon spawns the reconcile passes
  (Pass A through O) per the existing convention; the per-pass
  cadence is configured per :class:`DaemonConfig` per-pass kwargs.
* **Pillar E** discovery dedup + cache + tier + lineage primitives —
  consumed by the per-stage discovery dispatch; daemon does NOT modify.
* **Pillar F** voice corpus + Layer 5 backstop — consumed by the
  per-stage draft + reconcile dispatches; daemon does NOT modify.
* **Pillar G** observability — the daemon emits ``daemon_started`` +
  ``daemon_stopping`` + ``daemon_stopped`` + ``policy_reloaded`` +
  ``health_probe`` events per ADR-0050 D272's per-event-class catalog
  + extends ``EVENT_CLASS_CATALOG`` via the Pillar H additions per
  D331 + the per-call ``collect_event_class_snapshots`` aggregates the
  Pillar H event classes uniformly with prior pillars.

See ``docs/adr/0060-pillar-h-foundation.md`` for the full Week 1 ADR.

**Pillar H Week 10-11 extension** per ADR-0068 D364-D366 — crash recovery
hardening per ADR-0060 D335 invariant 2 trajectory. Three structural
extensions to the public surface:

1. NEW :func:`_recover_from_prior_crash` helper re-exported from
   :mod:`runner` — synthesizes ``daemon_stopped(exit_reason="crash",
   _recovered_by="reconcile")`` events for any prior ``daemon_started``
   events lacking matching ``daemon_stopped`` events (matched by PID).
   Invoked at :func:`init_daemon` Step 4.5 (NEW between W2 Step 4
   migration apply + W2 Step 5 policy load) per ADR-0068 D364.
2. NEW :class:`DaemonConfig` field ``reconcile_passes_at_startup:
   str | None = None`` per ADR-0068 D366 — operator-deliberate opt-in
   for pre-flight reconcile pass invocation at :func:`init_daemon` Step
   4.6 (NEW between W10-11 Step 4.5 crash-recovery synthesis + W2 Step
   5 policy load). Default ``None`` = no pre-flight reconcile (test
   substrate + dev path); production operators set ``"A"`` or
   ``"A,B,D,E,F,H,I,J"`` for auto-recovery of orphan ``send_intent``
   events on every daemon restart.
3. NEW :func:`init_daemon` test-only seam kwargs ``crash_recovery_fn``
   + ``reconcile_at_startup_fn`` + ``crash_recovery_now_fn`` per the
   Pillar G TEST-ONLY embed_fn convention + the per-pillar-H seam-vs-
   fork two-tiered distinction per the W4 follow-up P2-1 closure.

The W3 commit per ADR-0062 D344 pre-reserved ``DAEMON_EXIT_REASONS``
``"crash"`` for this W10-11 trajectory; the W10-11 commit operationally
lands the synthesis. The R032 synthetic-event exclusion per ADR-0056
D311's ``_recovered_by`` filter naturally excludes the synthesized
events from Pillar G SLO aggregation. The Grafana Panel #7 (NEW at
W10-11) at ``infra/grafana/dashboards/per_daemon.yml`` renders the
``daemon_stopped`` event's ``exit_reason`` distribution (clean /
timeout / crash) as an operator SLO signal.

See ``docs/adr/0068-pillar-h-week-10-11-crash-recovery-hardening.md``
for the full W10-11 ADR.

**Pillar H Week 12 — Pillar H STABLE flip + binding exit-criterion + retrospective + handoff to Pillar I** per ADR-0069 D367-D370. THE FINAL per-pillar-H trajectory week per ADR-0060 D332's trajectory table closing at Week 12:

* D367 — binding exit-criterion test un-skip at
  :meth:`tests.test_multi_channel_coherence.TestPillarHExitCriterion.test_daemon_24h_run_zero_anomalies_recovers_from_kill_9_reloads_policy`
  per ADR-0060 D334's 6-row scope. The SIX-row composite test
  verifies 24h-zero-anomaly + ``kill -9`` recovery via W10-11
  synthesis + SIGHUP-equivalent ``reload_policy()`` + SIGTERM-
  equivalent ``shutdown("sigterm")`` + Pillar G framework adoption
  preservation + privacy invariant per I8 across ALL SIX Pillar H
  event classes.
* D368 — **Pillar H STABLE flip at docs/PILLAR-PLAN.md §6 Pillar
  H row** — Status flipped from "In progress as of 2026-05-26" to
  "Stable as of 2026-05-28". Pillar H joins the STABLE pillars
  (A + B + C + D + E + F + G); the per-pillar-week trajectory is
  COMPLETE.
* D369 — Pillar H retrospective at ``.planning/RETRO-pillar-h.md``
  per the per-pillar-foundation precedent.
* D370 — Handoff to Pillar I at
  ``.planning/HANDOFF-pillar-i-week-1.md`` per the per-pillar
  trajectory bridge. Pillar I unblocked from "Pillar H stable"
  dependency per ADR-0060 §Downstream pillar impact.

ZERO new operator-visible surface changes at Week 12 — the
``__all__`` export list preserves verbatim from the W10-11 follow-up
base. The Week 12 commit ONLY adds the binding test body + the
Stable flip docs + ADR-0069 + retrospective + Pillar I handoff.

See ``docs/adr/0069-pillar-h-week-12-binding-exit-criterion-stable-flip.md``
for the full W12 ADR.

**Pillar H Week 12 follow-up** per the per-week-reviewer's independent
review of the W12 main commit `e6bad16`: 0 P1 + 0 P2 + 3 P3 addressed —
the **TENTH consecutive ADR-vs-actual-impl drift in Pillar H** caught by
the per-week-reviewer's cross-pillar back-audit discipline at the W12
main review (the prior NINE drifts at W2 → W10-11 main; THREE P1
escalations at W5 + W7 + W10-11):

* P3-1 — TENTH ADR-vs-actual-impl drift: "EVENT_CLASS_CATALOG stays at
  25" absolute-count claim at ADR-0069 §Consequences (Neutral) +
  ADR-0068 §Consequences (Neutral) was empirically wrong (actual count
  is 63 entries spanning Pillar A-H + Phase 5.5 surfaces); narrative
  propagated from ADR-0065's W6 narrative. Severity P3 (narrative-only;
  no production code path broken — the substantive "ZERO new event
  classes" claim is correct + pinned by the existing
  ``len(DAEMON_NEW_EVENT_CLASSES) == 6`` regression-barrier).
  **P3-1 CLOSED** via ADR-0069 + ADR-0068 narrative corrections + NEW
  :class:`tests.test_daemon.TestW12FollowupCatalogClaimSubstantive` × 2
  regression-barriers explicitly naming the substantive claim + the
  TENTH drift trace.
* P3-2 — HANDOFF-pillar-i-week-1.md said "NINE Pillar H closed-sets"
  but the actual count is EIGHT (7 explicit closed-sets + 1 implicit
  ``_PIPELINE_STAGES`` mirror); **CLOSED** via HANDOFF narrative
  correction.
* P3-3 — discipline-counts narrative inconsistency across runner.py
  docstring vs ADR-0069 vs RETRO vs HANDOFF; **CLOSED** via
  standardization on post-W12 framing (THIRTY-SIX / THIRTY-THREE /
  THIRTY-FIVE post-W12 main; THIRTY-SEVEN / THIRTY-FOUR / THIRTY-SIX
  post-W12 follow-up).

ZERO new ADRs at the W12 follow-up. 4181 passing post-W12 follow-up
(was 4179 + 2 net new W12-follow-up regression-barriers). Per-week-
reviewer disciplines status after W12 follow-up: cell-level matrix
coverage **THIRTY-SEVEN** consecutive weeks + behavioral-passthrough-
not-signature-only **THIRTY-FOUR** consecutive weeks + module-level
docstring drift **THIRTY-SIX** consecutive weeks + per-pillar mirror
constants parity PRESERVED + cross-pillar back-audit EXTENDED to **TEN
consecutive Pillar H weeks** of ADR-vs-actual-impl drift catches.

**Pillar H Week 12 + follow-up is REVIEWED + CLOSED.** Pillar H is
STABLE 2026-05-28. Pillar I + J unblocked from "Pillar H stable"
dependency per ADR-0060 §Downstream pillar impact.

**Pillar I Week 1 — multi-tenant + OSS hardening foundation** per
ADR-0070 D371-D376 (2026-05-28). Pillar I extends the daemon surface
with per-tenant fan-out per ADR-0070 D371 + ADR-0060 §Downstream pillar
impact. The Pillar H daemon module preserves verbatim at Pillar I Week
1 (the multi-tenant package is NEW at ``orchestrator/multi_tenant/``;
the daemon module is unchanged at the public surface). Pillar I Week 2
extends :class:`DaemonConfig` with optional ``tenant_id: str | None =
None`` field per ADR-0071 — None default preserves single-tenant
operators; non-empty string opts into per-tenant mode. The ``tenant_id``
factors into ``_compute_config_hash`` so operators querying
:attr:`DaemonRunner.config_hash` see drift across tenants.

Pillar I per-tenant extension trajectory (Weeks 2-6 per ADR-0070 D376):

* **Week 2** — :class:`DaemonConfig` extends with ``tenant_id`` field +
  per-tenant ledger directory resolution via
  :func:`orchestrator.multi_tenant.resolve_per_tenant_ledger_dir` + per-
  tenant policy directory resolution + ``observability.EVENT_CLASS_CATALOG``
  extension with the SIX Pillar I event classes per
  :data:`orchestrator.multi_tenant.TENANT_NEW_EVENT_CLASSES` (Week 1
  ships DISJOINT; Week 2 ships SUBSET per the per-pillar mirror
  constants parity discipline).
* **Week 3** — per-tenant Docker container orchestration via
  ``docker-compose.yml`` + ``Dockerfile`` (one daemon process per
  tenant per ADR-0060 D335 invariant 1); per-tenant Grafana folder
  isolation extends ``infra/grafana/dashboards/per_daemon.yml``.
* **Week 4** — init wizard body invokes :func:`init_daemon` per-tenant
  at first-run; per-tenant Gmail/LinkedIn OAuth flows emit
  ``auth_token_refreshed`` events; ``init_wizard_completed`` event
  emits at end.
* **Week 5** — CI bring-up + per-tenant contention regression-barrier
  (R040 mitigation) + startup-latency regression-barrier (R041
  mitigation).
* **Week 6** — Pillar I binding exit-criterion test un-skip + Pillar I
  Stable flip + retrospective + handoff to Pillar J.

Pillar I per-tenant audit-tooling MAY extend :func:`_recover_from_prior_crash`
with per-tenant labels (per ADR-0068 §Existing-operator seed) at Week 2+;
:class:`EventClassIndex` + :class:`PersonEventIndex` MAY extend with
per-tenant labels at Week 2+ per the W8 follow-up P3-6 deferred item.

Per-tenant cross-tenant isolation invariant per ADR-0070 D375 invariant
(a) — tenant A's daemon process MUST NOT leak tenant B's per-Person
data; the per-tenant Docker container model enforces this at runtime;
the per-tenant daemon process boundary enforces this at the API
surface; the privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058
D323 + ADR-0060 D335 EXTENDS to per-tenant.

See ``docs/adr/0070-pillar-i-foundation.md`` for the full Pillar I
Week 1 foundation ADR.

**Pillar I Week 1 follow-up** per the per-week-reviewer's independent
review of the Pillar I Week 1 main commit `264f13d`: 0 P1 + 0 P2 + 3
P3 + 6 REFUTED addressed — the **FIRST Pillar I ADR-vs-actual-impl
drift** caught by the per-week-reviewer's cross-pillar back-audit
discipline extending the Pillar H TEN consecutive catches (per the
W12 follow-up P3-1 closure) to **ELEVEN consecutive weeks across the
Pillar H + Pillar I trajectory**. P3-1 closure — "18 P3 concerns"
narrative claim corrected to "15 P3 + 1 Deferred" (off-by-three
narrative drift); P3-2 closure — "NINE consecutive ADR-vs-actual-impl
drift catches" stale count corrected to "TEN" per the W12 follow-up
P3-1 closure; P3-3 closure — discipline-counts narrative drift in
HANDOFF lines 80-82 standardized to post-W12-follow-up framing. See
``docs/adr/0070-pillar-i-foundation.md`` §"Pillar I Week 1 follow-up
addendum" for the full closure narrative.
"""

from __future__ import annotations

from orchestrator.daemon.runner import (
    DAEMON_EXIT_REASONS,
    DAEMON_LIFECYCLE_STATES,
    DAEMON_NEW_EVENT_CLASSES,
    DAEMON_POLICY_RELOAD_SIGNALS,
    POLICY_RELOAD_STATUSES,
    SHUTDOWN_REASONS,
    DaemonConfig,
    DaemonRunner,
    EventClassIndex,
    PersonEventIndex,
    PolicyReloadResult,
    _recover_from_prior_crash,
    attach_signal_handlers,
    build_daemon_stage_saturated_payload,
    build_daemon_started_payload,
    build_daemon_stopped_payload,
    build_daemon_stopping_payload,
    build_policy_reloaded_payload,
    init_daemon,
)
from orchestrator.daemon.health import (
    HEALTH_PROBE_OUTCOMES,
    HealthStatus,
    build_health_probe_payload,
    serve_health_endpoint,
)


__all__ = [
    "DAEMON_EXIT_REASONS",
    "DAEMON_LIFECYCLE_STATES",
    "DAEMON_NEW_EVENT_CLASSES",
    "DAEMON_POLICY_RELOAD_SIGNALS",
    "DaemonConfig",
    "DaemonRunner",
    "EventClassIndex",
    "HEALTH_PROBE_OUTCOMES",
    "HealthStatus",
    "POLICY_RELOAD_STATUSES",
    "PersonEventIndex",
    "PolicyReloadResult",
    "SHUTDOWN_REASONS",
    # Pillar H Week 10-11 NEW per ADR-0068 D364 — crash-recovery
    # synthesis helper re-exported from runner.py for Pillar I per-tenant
    # audit-tooling's potential consumer (the per-tenant audit-tooling MAY
    # call the helper with a per-tenant Ledger). Test substrate at
    # tests/test_daemon.py consumes it directly via the same re-export.
    "_recover_from_prior_crash",
    "attach_signal_handlers",
    "build_daemon_stage_saturated_payload",
    "build_daemon_started_payload",
    "build_daemon_stopped_payload",
    "build_daemon_stopping_payload",
    "build_health_probe_payload",
    "build_policy_reloaded_payload",
    "init_daemon",
    "serve_health_endpoint",
]
