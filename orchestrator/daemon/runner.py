"""Pillar H Week 1 + Week 2 + Week 3 + Week 4 + Week 4 follow-up + Week 5
+ Week 5 follow-up + Week 6 + Week 6 follow-up + Week 7 + Week 7 follow-up
+ Week 8 + Week 8 follow-up + Week 9 + Week 9 follow-up — daemon runner primitive (per ADR-0060
D331 + D332 + D335 + D336 + ADR-0061 D337 + D339 + D340 + ADR-0062 D341 +
D342 + D343 + D344 + ADR-0067 D359-D363 + W8 follow-up P2-1 closure
(the SEVENTH ADR-vs-actual-impl drift in Pillar H — the EventClassIndex
catalog scope extended to EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES
mirroring the Pillar G collect_event_class_snapshots consumer surface
precedent per per-pillar mirror constants parity discipline); Week 1 follow-up extends with :data:`DAEMON_POLICY_RELOAD_SIGNALS`
+ :data:`POLICY_RELOAD_STATUSES` closed-sets per per-week-reviewer P3-2 +
P3-3 closures; Week 2 follow-up extends :func:`_validate_config` with
refuse-loud rules for negative :attr:`DaemonConfig.graceful_shutdown_seconds`
+ negative :attr:`DaemonConfig.health_probe_rate_limit_seconds` + sub-1
:attr:`DaemonConfig.parallelism_limits` values per per-week-reviewer P2-1
closure + extends :func:`build_daemon_started_payload` with input
validation per per-week-reviewer P2-2 closure + adds :data:`_DAEMON_VERSION`
↔ :data:`observability._SERVICE_VERSION` parity comment per P3-1 closure
+ extends :func:`_compute_config_hash` docstring with cross-OS note per
P3-3 closure + refactors :func:`init_daemon` lazy imports per P3-6 closure
+ extends :func:`init_daemon` docstring with framework-neutrality extension
point + OTel-after-policy rationale per P3-7 + P3-8 closures; Week 3
ships :func:`attach_signal_handlers` body wiring asyncio
:meth:`AbstractEventLoop.add_signal_handler` for SIGTERM + SIGINT +
SIGHUP per ADR-0062 D341 + :meth:`DaemonRunner.shutdown` body with
lifecycle state transitions via :func:`object.__setattr__` frozen-
dataclass escape hatch per ADR-0062 D342 + :func:`build_daemon_stopping_payload`
+ :func:`build_daemon_stopped_payload` emit-shape factories per ADR-0062
D343 + :data:`SHUTDOWN_REASONS` + :data:`DAEMON_EXIT_REASONS` closed-sets
per ADR-0062 D344; Week 3 follow-up closes per-week-reviewer P2-1
``_emitted_by`` audit-marker drift — the THREE Pillar H emit-shape
factories (``build_daemon_started_payload`` / ``_stopping_payload`` /
``_stopped_payload``) previously OMITTED ``_emitted_by`` while their
docstrings + ADR-0062 D343 narrative FALSELY claimed auto-fill by
:meth:`Ledger.append` (the SECOND ADR-vs-actual-impl drift in Pillar
H per the per-week-reviewer's ADR-vs-actual-impl drift discipline
extended at Week 2 follow-up P3-8); closes P2-2 ``started_at_ts``
parse-after-state-transition half-completed-state concern by moving
the strptime to the TOP of :meth:`DaemonRunner.shutdown` BEFORE the
state transition; closes P3-1 ``object.__setattr__`` escape-hatch
unprotected-fields concern via :meth:`TestShutdownBody.test_only_lifecycle_state_mutates_during_shutdown`
regression-barrier + an explicit comment at the escape-hatch site;
closes P3-2 + P3-3 lazy-import-inconsistency via module-top
:mod:`asyncio` + :mod:`signal` + :data:`timedelta` imports; closes
P3-4 ``_reload_with_notimpl_swallow`` stderr-log behavioral-
passthrough gap via :meth:`TestAttachSignalHandlers.test_sighup_callback_swallows_notimplementederror_at_week_3`;
closes P3-5 :mod:`orchestrator.daemon.health` module-docstring
drift via the Week 3 + Week 3 follow-up naming extension; closes P3-6
``_SpyLoop`` DRY violation via the module-level
``_SignalRegistrationSpyLoop`` test helper class; REFUTES P3-7
``SHUTDOWN_REASONS`` × factory-acceptance structural-invariant
concern as adequately covered by the existing cell-level matrix
coverage (``TestDaemonStoppingPayload::test_each_reason_constructs_valid_payload``
+ ``test_invalid_reason_raises_value_error`` + ``TestShutdownReasons::test_contents_pin_per_adr_0062_d344``
collectively pin the bidirectional invariant); Week 4 extends Pillar
H's surface at ``orchestrator/daemon/health.py`` with the
:func:`serve_health_endpoint` body wiring asyncio-aiohttp HTTP
server on ``127.0.0.1:8080`` per R036 + ``health_probe`` rate-limit
per R038 + :func:`build_health_probe_payload` emit-shape factory
+ per-pillar-H Grafana panel at ``infra/grafana/dashboards/per_daemon.yml``
+ NEW pip dependency :mod:`aiohttp` per ADR-0063 D345-D348; the
:data:`EMITTED_BY` constant introduced at Week 3 follow-up is
consumed by the Week 4 factory at health.py via lazy import to
avoid module-load-time circular import; Week 4 follow-up closes
per-week-reviewer P2-1 framework-neutrality text drift at ADR-0063
D348 + the health.py body's lazy-import comment — the seam kwargs
substitute BACKENDS NOT HTTP server choice (the THIRD ADR-vs-actual-
impl drift caught by the per-week-reviewer's cross-pillar back-audit
discipline) + P2-2 :func:`_compute_health_status` ValueError swallow
vs :meth:`DaemonRunner.shutdown` refuse-loud asymmetry documented +
P3-3 / P3-4 / P3-5 Week 4 placeholder semantics documented at field
docstrings + pinned via trajectory regression-barrier tests + P3-6
``bind_addr`` refuse-loud at boundary via :func:`ipaddress.ip_address`
+ P3-7 ``aiohttp`` upper bound at ``aiohttp>=3.9,<4`` +
P3-8 / P3-9 Pillar I per-tenant per-container closure + reverse-proxy
``X-Forwarded-For`` trajectories documented + P3-10
:func:`serve_health_endpoint` return type hint narrowed via
:data:`TYPE_CHECKING` import of :class:`aiohttp.web.AppRunner` +
NEW-1 :class:`HealthStatus.__post_init__` validates ``outcome`` +
``lifecycle_state`` in their closed-sets + NEW-2 Content-Type
``application/json`` regression-barrier test + NEW-3 Pillar I
middleware trajectory documented at :func:`serve_health_endpoint`
docstring; Week 5 ships :meth:`DaemonRunner.run` body wiring the
asyncio event loop per ADR-0064 D349 — seven-step ordering
(refuse-loud non-initializing → initializing→ready transition via
:func:`object.__setattr__` → ``daemon_started`` emit → wire signal
handlers via :func:`attach_signal_handlers` → start health endpoint
via :func:`serve_health_endpoint` + retain :class:`AppRunner`
reference → per-stage worker pool skeleton iterating over sorted
:data:`observability._PIPELINE_STAGES` wrapped in
:func:`observability.traced_stage` per ADR-0064 D350 + ADR-0055
D300 → graceful shutdown coordination via :meth:`AppRunner.cleanup`
per ADR-0064 D352 → return exit code 0); test-only seam kwargs
(``attach_signal_handlers_fn`` + ``serve_health_endpoint_fn`` +
``traced_stage_fn`` + ``emit_fn`` + ``now_fn`` + ``tick_seconds`` +
``loop``) preserve framework-neutrality per Pillar G TEST-ONLY
convention + Pillar H Week 2-4 precedent); Week 5 follow-up closes
per-week-reviewer P1-1 ``traced_stage(stage)`` vs production
``traced_stage(stage, operation)`` signature drift — the FOURTH
ADR-vs-actual-impl drift in Pillar H per the per-week-reviewer's
cross-pillar back-audit discipline (the prior three: Week 2
follow-up P3-8 OTel Resource rationale; Week 3 follow-up P2-1
``_emitted_by`` audit-marker; Week 4 follow-up P2-1
framework-neutrality text); Week 5 main commit's body invoked
``traced_stage_fn(stage)`` with one arg + the spy tolerated it
+ 8 tests passed BUT production default broke with
``TypeError: traced_stage() missing 1 required positional
argument: 'operation'`` on the FIRST per-stage tick (the
behavioral-passthrough-not-signature-only discipline's exact
failure mode); the W5 follow-up commit aligns body + spy + ADR-0064
D350 narrative + adds
:meth:`TestDaemonRunBody.test_per_stage_tick_invokes_production_traced_stage_signature_per_w5_followup_p1_1`
regression-barrier exercising the production
``observability.traced_stage`` default; closes P2-1 pre-iteration
sanity-tick redundancy concern by REMOVING the pre-iteration (the
first while-loop iteration covers the same ground); closes P2-2
cleanup-on-exception path regression-barrier gap via
:meth:`TestDaemonRunBody.test_calls_health_endpoint_cleanup_on_exception_path`;
closes P2-3 ``tick_seconds <= 0`` validation gap via boundary
refuse-loud + regression-barrier tests; closes P2-4
:func:`asyncio.get_running_loop` cryptic-error concern via
operator-readable RuntimeError + regression-barrier test; closes
P3-1 + NEW-1 seven-step vs eight-step ordering drift via
docstring + ADR-0064 D349 alignment to "eight-step ordering";
closes P3-2 ``_StubAppRunner`` DRY violation via shared
``tests/_daemon_test_helpers.py`` helper module consumed by both
:mod:`tests.test_daemon` + :mod:`tests.test_multi_channel_coherence`;
closes P3-3 ``started_at_ts`` past-date magic constant via
module-level ``_TEST_PAST_STARTED_AT_TS`` + comment naming the
past-date determinism requirement; closes P3-4 ``loop`` kwarg
type narrowing from ``Any | None`` to
``asyncio.AbstractEventLoop | None``; closes P3-5
``health_app_runner`` naming-conflict via rename to
``health_aiohttp_runner`` (operators reading the code see two
distinct "runner" concepts disambiguated); closes P3-6 + NEW-3
+ NEW-4 lazy-import inconsistency via module-top imports of
:mod:`orchestrator.ledger` + :mod:`orchestrator.observability`
(:mod:`orchestrator.daemon.health` MUST stay lazy due to
circular-import-avoidance per the Week 4 follow-up NEW-1 closure
pattern); closes P3-8 ``emit_fn`` Ledger lazy-construction
trajectory documentation; closes P3-9 :mod:`orchestrator.daemon.health`
module docstring drift via Week 5 follow-up naming extension per
the W3 follow-up P3-5 closure's scope-extension to materially-
unchanged modules in the same per-pillar package; closes NEW-2
``startup_seconds`` rounding concern REFUTED (the
:func:`build_daemon_started_payload` factory already rounds to 3
dp at the factory boundary per ADR-0031 D140 — the determinism
contract is preserved); closes NEW-5
``object.__setattr__`` escape-hatch run()-side regression-barrier
gap via :meth:`TestDaemonRunBody.test_only_lifecycle_state_mutates_during_run`
mirroring the Week 3 follow-up P3-1 closure's discipline at
:meth:`shutdown`; closes NEW-6 :exc:`asyncio.CancelledError`
propagation documentation via docstring Raises section
extension naming the ``finally`` block's cleanup guarantee;
Week 6 ships per-stage worker pool actual parallelism via
:class:`asyncio.Semaphore` bounded by
:attr:`DaemonConfig.parallelism_limits[stage]` at the per-
FUNNEL-stage granularity per ADR-0065 D353 + NEW
:func:`build_daemon_stage_saturated_payload` raw-primitive
emit-shape factory per ADR-0065 D355 stamping
``_emitted_by="daemon"`` at the factory boundary per the
Pillar H Week 3 follow-up P2-1 closure convention + NEW
``"daemon_stage_saturated"`` event class joins
:data:`DAEMON_NEW_EVENT_CLASSES` (5 → 6) +
:data:`observability.EVENT_CLASS_CATALOG` (24 → 25) via
the per-pillar locality convention from Pillar H Week 2
ADR-0061 D338 + the per-pillar mirror constants parity
discipline + funnel-vs-observability stage bridging via
TWO ORTHOGONAL per-tick iterations per ADR-0065 D354 —
Iteration 6a per-observability-stage span tick over
sorted(:data:`observability._PIPELINE_STAGES`) preserves
Week 5 contract verbatim + Iteration 6b per-funnel-stage
worker pool tick over sorted(:data:`funnel._PILLAR_G_PIPELINE_STAGES`)
with :meth:`asyncio.Semaphore.locked` check + emit
``daemon_stage_saturated`` on saturation; the two closed-
sets are intentionally distinct per Pillar H Week 1 follow-
up P3-5 closure (funnel stages = per-pipeline-event stages
for operator-observable funnel progression; observability
stages = per-span dims for traced_stage); ONE coherence
stub un-skipped at Week 6 (:meth:`TestPillarHDaemon.test_per_stage_parallelism_limit_enforced`);
Week 6 follow-up closes per-week-reviewer P2-1 behavioral-
passthrough gap at the body-level Semaphore saturation
emit path via NEW :func:`semaphore_factory_fn` test-only
seam + NEW
:meth:`TestDaemonRunBody.test_daemon_stage_saturated_emits_when_semaphore_locked`
regression-barrier mirroring the W5 P1-1 closure's
behavioral-passthrough-not-signature-only discipline; closes
P2-2 ADR-0065 D353 narrative-vs-code-example INTERNAL drift
(the FIFTH ADR-vs-actual-impl drift in Pillar H — the
narrative said "after Step 2's lifecycle transition" but
the code example + actual body construct after Step 5's
start health endpoint; the prior four Pillar H drifts: W2
P3-8 OTel Resource rationale; W3 P2-1 ``_emitted_by``
audit-marker; W4 P2-1 framework-neutrality text; W5 P1-1
``traced_stage`` signature) via ADR-0065 D353 narrative
alignment + the body's Step 5.5 site comment naming the
W6 follow-up P2-2 closure; closes P3-1 + P3-2 + P3-3 +
NEW-2 lazy-import inconsistency via STYLE STANDARDIZATION
across the THREE :data:`funnel._PILLAR_G_PIPELINE_STAGES`
lazy-import sites (all three now use ``from
orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES``;
the prior :func:`_validate_config` site used the bare-module
form ``import funnel as _funnel``) + extended import-block
comment naming the DEEPER production-fragility rationale —
the lazy form is REQUIRED (not optional defense-in-depth)
because :mod:`orchestrator.funnel` does bare-name ``import
ledger`` at module load (line 152) requiring
:file:`orchestrator/` on ``sys.path``, added at test time
by :file:`tests/conftest.py` but NOT at production-import
time from a clean Python process; the W5 follow-up P3-6
"module-top imports when no circular dependency exists"
discipline does NOT generalize to funnel because the
production-fragility concern is orthogonal to the circular-
dependency concern; the per-week-reviewer's NEW finding
beyond P3-1/2/3/NEW-2 expanded this rationale at the W6
follow-up; closes
P3-4 :mod:`orchestrator.observability` module HEADER
cross-pillar discipline-scope question via "Last reviewed"
line bump at observability.py:457 naming Pillar H Week 2 +
Week 6 catalog extensions per the W3 follow-up P3-5
closure's materially-unchanged-module scope (the HEADER
itself is cross-pillar so stays unchanged per the
locality convention; the "Last reviewed" line is the
operator-facing surface for catalog modifications); closes
P3-5 :data:`DAEMON_NEW_EVENT_CLASSES` docstring "FIVE →
SIX" drift at the closed-set definition site itself +
P3-6 :mod:`orchestrator.daemon.__init__` public-surface
bullet "FIVE → SIX" drift + P3-7 test docstring "FIVE →
SIX" drifts across SIX test sites (test_observability.py
+ test_daemon.py + test_multi_channel_coherence.py) + P3-8
:file:`infra/grafana/dashboards/per_daemon.yml` "FIVE →
SIX" drift at panel 4 description + carry-forwards section
Week 5 attribution correction (daemon_stage_saturated
landed at Week 6 NOT Week 5 per ADR-0065 D355 + the per-
pillar-week trajectory at ADR-0060 D332) + dashboard
description "Week 4 → Week 4 + Week 6"; closes P3-9
factory docstring "Week 7+ flexibility" semantic
clarification + P3-10 :class:`asyncio.Semaphore` waiter-
case semantic asymmetry documentation note at the factory
docstring; closes P3-11 (folded into P2-1's regression-
barrier — the new test verifies the body's iteration
source is :data:`_PILLAR_G_PIPELINE_STAGES` via the per-
funnel-stage saturation emit's ``stage`` field
distribution); REFUTES pre-identified weak spot #6
(factory's ``in_flight_count == parallelism_limit`` upper-
edge IS implicitly tested via
:meth:`TestDaemonStageSaturatedPayload._valid_kwargs`'s
``parallelism_limit=4, in_flight_count=4``); closes NEW-1
:file:`orchestrator/observability.py` "Last reviewed" line
2026-05-25 → 2026-05-27 + NEW-3 + NEW-6 + NEW-7 (folded
into P3-6 + P3-7 closures); Week 7 ships
:meth:`DaemonRunner.reload_policy` body per ADR-0066 D356
+ NEW :func:`build_policy_reloaded_payload` raw-primitive
emit-shape factory per ADR-0066 D357 + reconcile passes
integration via NEW :data:`_STAGE_TO_PASSES` per-funnel-
stage → per-pass mapping + NEW :func:`_default_dispatch_for_stage`
async helper that invokes :func:`reconcile.reconcile` via
:func:`asyncio.to_thread` per ADR-0066 D358 + NEW
:func:`_compute_policy_content_hash` SHA-256 of canonical
YAML bytes + NEW :class:`_PolicyState` mutable holder for
runtime policy state on :class:`DaemonRunner` (mutated
in-place by reload_policy without extending the
``object.__setattr__`` escape hatch beyond lifecycle_state
per Pillar H Week 3 follow-up P3-1 + Week 5 follow-up
NEW-5 closures) + Iteration 6b dispatch wires
``async with sem: await dispatch_fn(stage)`` replacing the
Week 6 SKELETON pass; ONE coherence stub un-skipped at
Week 7 (:meth:`TestPillarHDaemon.test_sighup_triggers_policy_reload`);
W3 ``_reload_with_notimpl_swallow`` RENAMED to
``_reload_default`` per the Week 3 → Week 7 trajectory
bridge no longer needing the NotImplementedError swallow;
W1 ``test_reload_policy_signature_raises_not_implemented_at_week_1``
+ W3 ``test_sighup_callback_swallows_notimplementederror_at_week_3``
RENAMED + INVERTED to W7 contract per the per-pillar-
foundation rename+invert pattern;
:class:`DaemonConfig` extended with THREE optional Path
fields (``policy_dir`` / ``people_dir`` /
``suppressions_dir``) flowing into the config_hash;
:class:`DaemonRunner` extended with ``policy_state``
field; :func:`init_daemon` Step 5 extended to capture
loaded rules + compute initial content hash + populate
the :class:`_PolicyState` holder; Week 8 ships
:class:`EventClassIndex` + :class:`PersonEventIndex`
in-memory mutable-holder dataclasses per ADR-0067 D359
+ NEW :func:`_materialize_indexes` single-walk dual-index
materialization helper per ADR-0067 D360 + NEW
:func:`init_daemon` Step 8 (inserted between Prometheus
exposition Step 7 + the now-renumbered Step 9
DaemonRunner construction) wiring the materialization
at daemon startup per ADR-0060 D336 (R039 mitigation
pattern — Pillar G per-Person primitives' per-call
O(N) ledger walk at v2 scale ~100K events drops to
O(M_class) when daemon-process consumers pass the
``event_class_index`` kwarg) + :class:`DaemonRunner`
extended with TWO new fields (``event_class_index`` +
``person_event_index``); NEW ``index_materialize_fn``
test-only seam at :func:`init_daemon`; per-Person
primitives at :mod:`orchestrator.observability` extended
with optional ``event_class_index`` kwarg per ADR-0067
D361 preserving the Pillar G READ-ONLY funnel CLI
contract per ADR-0059 D325 (the kwarg's None default
preserves the existing ledger-walk behavior verbatim);
ONE coherence stub un-skipped at Week 8
(:meth:`TestPillarHDaemon.test_per_event_class_index_at_startup`);
Week 9 ships per-event-class index invalidation on
:meth:`Ledger.append` per ADR-0067 D362 (W9 extension to ADR-0067
per ADR-0060 D336's per-week trajectory) via:

* NEW :meth:`Ledger.append_observer` post-append observer seam at
  :mod:`orchestrator.ledger` (cross-pillar surface extension) +
  observer firing AFTER fsync + symlink + mtime invalidation
  (operators see the index updated POST durable commit; observer
  failure logs to stderr but does NOT propagate per ADR-0060 D335
  invariant 2's atomicity contract).
* NEW :func:`_invalidate_indexes_on_append` per-event invalidation
  helper that mirrors :func:`_materialize_indexes`'s per-event
  branch shape so the post-condition equals "re-materialize from a
  ledger walk that ends at this event" — the byte-identical
  determinism contract per ADR-0031 D140 holds via this structural
  equivalence.
* NEW :func:`_install_index_invalidation_observer` registration
  helper invoked at NEW :func:`init_daemon` Step 8.5 between Step
  8 materialization + Step 9 DaemonRunner
  construction.
* NEW :attr:`DaemonRunner.ledger` field lifting the daemon's
  Ledger instance out of the Week 8 init_daemon-body-local scope
  so the observer registration persists across all daemon-process
  appends; :func:`_default_dispatch_for_stage` body extended to
  consume ``runner.ledger`` (fallback to lazy construction when
  ``runner.ledger is None`` preserves backward compat with pre-W9
  tests + external dispatchers that construct DaemonRunner
  directly).
* NEW :attr:`EventClassIndex._last_updated_at_ts` +
  :attr:`PersonEventIndex._last_updated_at_ts` Unix-epoch float
  fields advanced on every index update (materialization +
  per-append invalidation); the operator-visible
  ``outreach_factory_daemon_index_last_updated_timestamp``
  Prometheus observable gauge per ADR-0067 D363 consults this
  field via a closure registered at :func:`init_daemon` Step 9.5.
* NEW :func:`observability.register_daemon_index_observable_gauge`
  registration helper for the operator-visible freshness gauge
  per ADR-0067 D363; the Grafana panel #6 at
  :file:`infra/grafana/dashboards/per_daemon.yml` renders
  ``time() - <gauge>`` as the index age in seconds + goes RED
  if age > 60s (operator SLO signal for invalidation stalls).
* ONE coherence stub added + un-skipped at Week 9
  (:meth:`TestPillarHDaemon.test_index_invalidates_on_ledger_append`)
  pinning the cross-pillar coherence surface that
  :meth:`Ledger.append` triggers in-place index mutation visible
  to subsequent :meth:`EventClassIndex.events_for_class` queries
  per ADR-0067 D362.

**Pillar H Week 9 follow-up** (per per-week-reviewer findings on
commit ``fb0196d`` — **0 P1 + 3 P2 + 6 P3 + 1 NEW addressed +
4 REFUTED**, **EIGHTH ADR-vs-actual-impl drift in Pillar H** caught
by the per-week-reviewer's cross-pillar back-audit discipline):
P2-1 Step 9 / Step 10 numbering narrative-vs-code drift CLOSED via
narrative correction at runner.py + __init__.py + ledger.py module
docstrings + ADR-0067 W9 extension addendum (the W9 main commit
narrative claimed "renumbered Step 10 DaemonRunner construction"
but the actual code at runner.py:3832 still labels DaemonRunner
construction as Step 9 — no renumber occurred at W9; the W9 gauge
registration at Step 9.5 inserts AFTER existing Step 9 NOT
renumbering it; the prior SEVEN ADR-vs-actual-impl drifts: W2 P3-8
OTel Resource → W3 P2-1 ``_emitted_by`` → W4 P2-1 framework-
neutrality → W5 P1-1 ``traced_stage`` signature → W6 P2-2 Step 5.5
ordering → W7 P1-1 Pass G classifier dependency → W8 follow-up P2-1
EventClassIndex catalog scope); P2-2 NEW regression-barrier
:meth:`TestW9FollowupDefaultDispatchFallbackPath.test_default_dispatch_for_stage_lazy_constructs_ledger_when_runner_ledger_is_none`
pinning the fallback semantic of
:func:`_default_dispatch_for_stage` (the W9 main commit verified the
production path WITH ``runner.ledger`` populated but NOT the
fallback when DaemonRunner is constructed directly bypassing
init_daemon); P2-3 NEW :meth:`Ledger.append_observer` refuse-loud at
boundary on non-callable observer per the per-pillar-H raw-primitive
refuse-loud-at-boundary discipline (W2 follow-up P2-2 precedent) +
NEW regression-barriers at
:class:`TestW9FollowupAppendObserverRefuseLoud`; P3-1
:attr:`PersonEventIndex._last_updated_at_ts` docstring test-name
attribution drift CLOSED via correction to actual
``TestEventClassIndexLastUpdatedAtTs::test_both_indexes_share_last_updated_at_ts_at_v1_per_lockstep_invariant``;
P3-2 :data:`observability.EVENT_CLASS_CATALOG` "Last reviewed" line
bumped to 2026-05-27 (Pillar H Week 9 follow-up commit) per the W3
follow-up P3-5 closure's discipline-scope extension to materially-
changed modules at observability.py; P3-3 :attr:`DaemonRunner.ledger`
field declaration ``= None`` pattern noted as bare-assignment
consistent with the existing :attr:`DaemonRunner.lifecycle_state`
field's bare-assignment pattern (the W9 main commit message's
``field(default=None)`` phrasing was functionally identical but
narrative-vs-code drifted); P3-4 :func:`init_daemon` NEW
``invalidation_now_ts_fn: Callable[[], float] = time.time`` kwarg
threading the deterministic-clock callable through to
:func:`_install_index_invalidation_observer` at Step 8.5 +
:class:`TestW9FollowupInitDaemonInvalidationNowTsFnSeam` cell
coverage; P3-5
:func:`_invalidate_indexes_on_append` partial-mutation invariant
documented at the docstring (if ``now_ts_fn`` raises, the per-index
``_data`` mutations have already occurred but ``_last_updated_at_ts``
fields stay stale — operator-readable failure-mode posture); P3-6
:func:`_install_index_invalidation_observer` ``known_classes``
documentation clarification (the W9 main commit's "frozenset is
immutable" rationale was operator-confusing because the captured
set is the UNION computed at call time NOT either operand directly;
the W9 follow-up clarifies); NEW-1 ADR-0067 W9 extension addendum
example code annotation ``frozenset[str]`` aligned with the actual
:func:`_invalidate_indexes_on_append` signature (the W9 main commit's
signature used string-quoted ``"frozenset[str]"`` while the ADR
example used bare ``frozenset[str]``; the W9 follow-up unquotes at
the function signature since ``from __future__ import annotations``
makes the string quotes redundant). REFUTED #1 + #2 + #3 + #4 (the
W9 main commit's pre-identified weak spots #2 observer-exception
logging test pollution + #3 best-effort gauge registration test
pollution + reviewer concerns #8 atomicity invariant + #9
byte-identical determinism all preserved verbatim per the existing
regression-barrier tests + the careful re-reading of the
:meth:`Ledger.append` body's ordering).

This module is the structural commitment Pillar H's per-week 2+
implementations build on. Week 1 ships the **module shape** + **the
closed-set enumeration of Pillar H daemon lifecycle states** + **the
:class:`DaemonConfig` + :class:`DaemonRunner` + :class:`PolicyReloadResult`
dataclasses** + **the primitive signatures**. The Week 2+ commits ship
the implementation bodies per ADR-0060 D332's per-week trajectory table.

**Pillar H Week 1 follow-up** (per per-week-reviewer findings on commit
`338e408`) — closes P3-2 by adding :data:`DAEMON_POLICY_RELOAD_SIGNALS`
closed-set + P3-3 by adding :data:`POLICY_RELOAD_STATUSES` closed-set +
P3-1/P3-5 by extending :class:`DaemonConfig.parallelism_limits` docstring
naming the send-side / receive-side semantics + the
:data:`observability._PIPELINE_STAGES` vs
:data:`funnel._PILLAR_G_PIPELINE_STAGES` distinction. The per-week-
reviewer disciplines (cell-level matrix coverage + module-level docstring
drift + per-pillar mirror constants parity) extend to Pillar H Week 1
follow-up.

**Pillar H Week 2** ships the :func:`init_daemon` body + the
:func:`build_daemon_started_payload` emit-shape factory + closes the
Pillar H Week 1 carry-forwards P3-1 (startup ordering invariant) + P3-2
(OTel set-once at daemon startup) per ADR-0061 D337-D340. The
:func:`init_daemon` body follows the STRICT startup ordering invariant
per ADR-0061 D337:

1. Validate config (path existence + port range + parallelism limits +
   policy_reload_signal closed-set per the Week 1 follow-up P3-2/P3-6).
2. Compute the config hash (stable across runs; SHA-256 of the
   canonical-JSON-encoded dataclass fields).
3. Resolve daemon's PID + ISO-8601 startup timestamp + version.
4. Apply pending ledger migrations via :meth:`MigrationRunner.apply`
   (BEFORE policy load per ADR-0009 D9 + ADR-0061 D340 P3-1 closure).
5. Load Pillar A policy YAML files via
   :func:`orchestrator.policy.load_rules_from_yaml` over the policy
   directory (AFTER migrations).
6. Initialize OTel SDK via :func:`observability.init_otel_meter_provider`
   + :func:`observability.init_otel_tracer_provider` (set-once at
   daemon startup per R035 + ADR-0061 D340 P3-2 closure).
7. Start Prometheus HTTP exposition via
   :func:`observability.start_prometheus_http_server` at ``127.0.0.1``
   per R036 (security-by-default).
8. Construct + return :class:`DaemonRunner` in ``"initializing"``
   state (the actual transition to ``"ready"`` lands at Week 5+'s
   :meth:`DaemonRunner.run` body).

The body uses **operator-deliberate test seams** per the Pillar G pattern
(``set_global=False`` in observability tests; ``TEST-ONLY embed_fn`` +
``retrieve_fn`` in voice corpus tests per ADR-0039) — :func:`init_daemon`
accepts function-typed kwargs defaulting to the production functions;
tests inject spies to verify the startup ordering invariant + mock the
side-effecting steps without applying real migrations or starting real
HTTP servers.

**Pillar H framework decision** per ADR-0060 D332 — the daemon is
**single-process** at Pillar H Week 1; multi-process / per-tenant
fan-out is Pillar I scope per ADR-0050 D276(d). The per-stage
parallelism within a single daemon process uses **asyncio** (NOT
threading or multiprocessing) per the rationale at ADR-0060 D332:

* The framework's I/O surfaces (Gmail API + LinkedIn MCP + Twitter
  scraping + Apollo / PDL / Reoon + Ledger I/O + vault I/O) are
  network-bound; asyncio's cooperative scheduling fits the workload
  shape.
* The Ledger's append-only contract per I2 + the per-Person lock
  primitive per Phase 5.5 + the per-channel two-phase commit per
  ADR-0014 D33 ALL hold under asyncio's single-process / single-thread
  model without additional synchronization.
* Pillar G's OTel SDK initialization per ADR-0052 D282 + the
  Prometheus exporter per ADR-0053 D288 + the per-stage spans per
  ADR-0055 D300 are async-context-friendly; the daemon's per-stage
  dispatch wraps existing :func:`observability.traced_stage` calls
  per the existing convention.
* The Pillar C dispatchers' per-channel SDKs (Gmail / LinkedIn / etc.)
  are sync; the daemon's per-stage worker pool wraps them via
  :func:`asyncio.to_thread` per the standard pattern.

**Pillar H load-bearing invariants** per ADR-0060 D335:

1. Process-isolation — one daemon process per tenant; per-process
   Ledger contract preserves per ADR-0050 D276(d).
2. Atomicity-preservation-across-process-boundary — the ledger's
   append-only contract per I2 holds across daemon restarts; the
   reconcile loop is the structural recovery backstop.
3. Graceful-shutdown — SIGTERM / SIGINT triggers ``draining`` state;
   in-flight per-stage tasks complete within the configured deadline;
   ``daemon_stopping`` + ``daemon_stopped`` ledger events emit.
4. Live-reload-policy — SIGHUP triggers re-read of policy YAML files
   per Pillar A's policy engine; ``policy_reloaded`` event emits with
   prior + new content hashes.

**Per-event-class indexing trajectory** per ADR-0060 D336 (R039
mitigation pattern — the Pillar G per-Person primitives' per-call O(N)
ledger walk at v2 scale ~100K events surfaces as a per-cron-interval
latency concern per ADR-0050 D272 + R033 mitigation pattern; Pillar H
MAY surface per-event-class indexing at the daemon's startup as a
NEW concern. Pillar H Week 1 ships the framework decision via D332's
per-week trajectory table; the indexing implementation lands at Pillar
H Week 8-9 per the trajectory).

The Week 1 contract:

```python
from orchestrator.daemon.runner import (
    DaemonConfig,
    DaemonRunner,
    init_daemon,
    DAEMON_LIFECYCLE_STATES,
)

config = DaemonConfig(
    vault_dir=Path("/path/to/vault"),
    ledger_dir=Path("/path/to/ledger"),
    health_port=8080,
    parallelism_limits={"discovery": 4, "send": 2},
    graceful_shutdown_seconds=30,
)
runner = init_daemon(config)
exit_code = runner.run()   # Week 5+ body
```

**Pillar H Week 10-11 + Week 10-11 follow-up** (per ADR-0068 D364-D366 —
crash recovery hardening per ADR-0060 D335 invariant 2 trajectory; the
W10-11 follow-up closes per-week-reviewer findings on commit `4c0da3e`:
**1 P1 + 2 P2 + 4 P3 + 7 REFUTED addressed** — **NINTH ADR-vs-actual-impl
drift in Pillar H + THIRD P1 in Pillar H** caught by the per-week-
reviewer's cross-pillar back-audit discipline at the W10-11 main review.
P1-1 the W10-11 main commit's Step 4.6 invoked
``reconcile_at_startup_fn(passes=..., ledger_dir=..., apply=True)`` but
``orchestrator.reconcile.reconcile``'s actual signature has NO
``ledger_dir`` parameter — it takes ``led: Ledger`` (NOT ``ledger_dir``)
+ ``since: datetime`` (REQUIRED, no default); the production-default
``reconcile_at_startup_fn=None`` path raised ``TypeError`` which the
broad ``except Exception`` block caught + silently swallowed; operators
opting in to ``reconcile_passes_at_startup="A"`` got NO pre-flight
reconcile per the W7 P1-1 failure-mode-repeat. P1-1 CLOSED via Step
4.6 body correction using actual reconcile.reconcile signature
(``led=Ledger(config.ledger_dir)`` + ``since=now - timedelta(days=7)``)
+ NEW ``TestW10_11FollowupReconcileSignaturePassthrough`` × 3
behavioral-passthrough regression-barriers introspecting
``inspect.signature(reconcile.reconcile)`` to verify call kwargs match
the actual signature. P2-1 closure (behavioral-passthrough gap that
allowed P1-1 to ship) addressed via the SAME × 3 tests; P2-2 closure
(cross-class uptime tracking documented-but-untested for
``policy_reloaded`` / ``health_probe`` / ``daemon_stage_saturated``
event classes) addressed via NEW ``TestW10_11FollowupCrossClassUptimeTracking``
× 3 regression-barriers; P3-1 + P3-2 + P3-3 + P3-4 closures via
docstring + ADR addendum corrections. 4178 passing post-W10-11
follow-up (was 4172 + 6 net new follow-up tests); per-week-reviewer
disciplines at THIRTY-FIVE consecutive weeks cell-level matrix
coverage + THIRTY-TWO behavioral-passthrough + THIRTY-FOUR module
docstring drift + **NINE consecutive Pillar H weeks of ADR-vs-actual-
impl drift catches** (THREE P1 escalations: W5 + W7 + W10-11).

**Pillar H Week 10-11 main** (per ADR-0068 D364-D366 — crash recovery
hardening per ADR-0060 D335 invariant 2 trajectory):

* NEW :func:`_recover_from_prior_crash` helper synthesizes
  ``daemon_stopped(exit_reason="crash", _recovered_by="reconcile")``
  events for any prior ``daemon_started`` events lacking matching
  ``daemon_stopped`` events (matched by PID). The crash detection is
  ledger-walk-based per ADR-0060 D335 invariant 2 (the daemon
  contributes NO new state that bypasses the ledger); the synthesis
  uses the existing :func:`build_daemon_stopped_payload` factory +
  the existing ``_recovered_by`` audit-marker convention per ADR-0010
  D17. The W3 commit per ADR-0062 D344 pre-reserved
  ``exit_reason="crash"`` for this W10-11 trajectory.
* NEW :func:`init_daemon` Step 4.5 invokes
  :func:`_recover_from_prior_crash` BEFORE Step 5 (policy load) — a
  policy parse error MUST NOT prevent crash-recovery synthesis. The
  insertion is symmetric with Step 8.5 (W9 invalidation observer) +
  Step 9.5 (W9 gauge registration) per the per-pillar-H half-step
  convention.
* NEW :func:`init_daemon` Step 4.6 invokes
  :func:`reconcile.reconcile(passes=value, apply=True, ...)` when
  :attr:`DaemonConfig.reconcile_passes_at_startup` is set
  (operator-deliberate opt-in). Default ``None`` = no pre-flight
  reconcile (test substrate + dev path); production operators set
  ``"A"`` (Gmail intent recovery only) or ``"A,B,D,E,F,H,I,J"`` (the
  full intent-recovery pass set). Failures log to stderr + do NOT
  prevent daemon startup — the per-tick reconcile dispatch via Pillar
  H Week 7's ``dispatch_fn`` IS the structural backstop; pre-flight
  is operator convenience.
* NEW :class:`DaemonConfig` field ``reconcile_passes_at_startup:
  str | None = None`` per ADR-0068 D366 — operator-deliberate opt-in
  with refuse-loud validation at :func:`_validate_config`
  (non-empty-string-or-None constraint). Factors into
  :func:`_compute_config_hash` so operators querying
  :attr:`DaemonRunner.config_hash` detect config drift across the
  extended surface.
* NEW :func:`init_daemon` kwargs: ``crash_recovery_fn`` (test-only
  seam substituting the synthesis BACKEND at Step 4.5) +
  ``reconcile_at_startup_fn`` (test-only seam substituting the
  pre-flight reconcile BACKEND at Step 4.6) + ``crash_recovery_now_fn``
  (test-only seam threading the deterministic-clock callable through
  to the synthesis ``now_fn`` per ADR-0031 D140 byte-identical
  determinism). The seams follow the Pillar G TEST-ONLY embed_fn
  convention + the per-pillar-H seam-vs-fork two-tiered distinction
  per the W4 follow-up P2-1 closure.
* NEW Grafana Panel #7 at
  :file:`infra/grafana/dashboards/per_daemon.yml` rendering
  ``daemon_stopped`` event's ``exit_reason`` distribution (clean /
  timeout / crash) per ADR-0062 D344 + the W10-11 trajectory. The
  panel goes RED if crash count > 0 (operator SLO signal for crashes
  in the current daemon process lifetime).
* ONE coherence stub un-skipped at Week 10-11
  (:meth:`TestPillarHDaemon.test_recovers_from_kill_9_via_reconcile`)
  pinning the cross-pillar coherence surface that pre-seeded
  daemon_started without matching daemon_stopped triggers crash
  recovery synthesis at the next :func:`init_daemon` startup.

**Pillar H Week 12** (per ADR-0069 D367-D370 — binding exit-criterion
test un-skip + Pillar H Stable flip + Pillar H retrospective +
handoff to Pillar I; THE FINAL per-pillar-H trajectory week per
ADR-0060 D332's trajectory table closing at Week 12):

* D367 — binding exit-criterion test un-skip at
  :meth:`TestPillarHExitCriterion.test_daemon_24h_run_zero_anomalies_recovers_from_kill_9_reloads_policy`
  per ADR-0060 D334's 6-row scope. The SIX-row composite test
  verifies (ROW 1) 24h-zero-anomaly via compressed
  ``tick_seconds=0.001`` per-stage tick loop with ``traced_stage_fn``
  spy capturing every Pillar G ``_PIPELINE_STAGES`` consumption;
  (ROW 2) ``kill -9`` recovery via the W10-11
  :func:`_recover_from_prior_crash` synthesis at
  :func:`init_daemon` Step 4.5 fires for pre-seeded
  ``daemon_started(pid=fake_prior_pid)`` lacking matching
  ``daemon_stopped`` — synthesized
  ``daemon_stopped(exit_reason="crash", _recovered_by="reconcile",
  _recovered_for_pid=fake_prior_pid)`` event lands in the ledger;
  (ROW 3) SIGHUP-equivalent in-process :meth:`runner.reload_policy`
  emits ``policy_reloaded(status="applied", prior_content_hash,
  new_content_hash)`` event with 64-hex-char SHA-256 per ADR-0066
  D357; (ROW 4) SIGTERM-equivalent in-process
  :meth:`runner.shutdown("sigterm")` transitions lifecycle through
  ``"draining"`` → ``"stopped"`` + emits
  ``daemon_stopping(reason="sigterm")`` +
  ``daemon_stopped(exit_reason="clean")`` events +
  :meth:`runner.run` task exits with code 0; (ROW 5) Pillar G
  observability framework adoption surfaces preserve verbatim —
  SIX Pillar H event classes in
  :data:`observability.EVENT_CLASS_CATALOG`; per-event-class index
  materialized at Step 8 contains W10-11 synthesized event (W9
  observer at Step 8.5 fires for Step 4.5 synthesis); R032
  synthetic-event exclusion per ADR-0056 D311 preserves (exactly
  ONE ``_recovered_by="reconcile"`` event in final ledger);
  traced_stage consumed for every pipeline stage; (ROW 6) privacy
  invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 — NO body /
  NO person_id / NO source_list / NO claim_text / NO query_text /
  NO exemplar_body / NO dossier_body / NO raw_body / NO draft_body
  in any daemon-emitted event payload across ALL SIX Pillar H
  event classes.

* D368 — **Pillar H STABLE flip at docs/PILLAR-PLAN.md §6 Pillar H
  row** — Status flipped from "In progress as of 2026-05-26" to
  "Stable as of 2026-05-28". Pillar H joins the STABLE pillars
  (A + B + C + D + E + F + G); the per-pillar-week trajectory is
  COMPLETE; the operator-visible surface (DaemonConfig +
  DaemonRunner + init_daemon + attach_signal_handlers +
  serve_health_endpoint + SIX emit factories + EIGHT closed-sets +
  per-event-class index materialization + per-append observer seam
  + crash-recovery synthesis + operator-deliberate pre-flight
  reconcile + Grafana per-daemon dashboard with SEVEN panels) is
  the v1 commitment. The Pillar H exit criterion per PILLAR-PLAN
  §2 Pillar H binding text ("24h continuous run against synthetic
  vault with 1000 prospects produces zero anomalies; recovers
  cleanly from `kill -9`; reloads cooldown rule changes without
  restart") is OPERATIONALLY MET via the binding exit-criterion
  test.

* D369 — Pillar H retrospective at ``.planning/RETRO-pillar-h.md``
  per the per-pillar-foundation precedent (Pillar D + E + F + G all
  shipped retros at their Stable-flip commits). Calibration headline
  12:3 (slower than Pillar G's 12:2 but matches the daemon + scale
  structural complexity); 21 total commits across 12 weeks (1.75
  commits per week average); NINE consecutive ADR-vs-actual-impl
  drift catches with THREE P1 escalations (W5 traced_stage
  signature + W7 Pass G classifier + W10-11 reconcile signature) —
  per-week-reviewer pattern's empirical structural value at the
  daemon + scale grain is now non-trivial; future Pillar I + J
  authors carry the discipline forward with full reviewer attention
  from Day 1.

* D370 — Handoff to Pillar I at
  ``.planning/HANDOFF-pillar-i-week-1.md`` per the per-pillar
  trajectory bridge. Captures: the Pillar H surfaces Pillar I
  extends (per-tenant fan-out at the daemon process boundary;
  per-tenant ledger directories; per-tenant policy YAML files;
  per-tenant Grafana folder isolation); the per-pillar mirror
  constants parity discipline at Pillar I's per-tenant audit-
  tooling; the deferred items the Pillar I author addresses (W7
  follow-up NEW-2 + W8 follow-up P3-6). Pillar I unblocked from
  "Pillar H stable" dependency per ADR-0060 §Downstream pillar
  impact.

* ZERO new event classes / closed-sets / emit-shape factories /
  test-only seams / ledger migrations / pip dependencies / R-risks
  at Week 12. The Pillar G framework adoption surfaces preserve
  VERBATIM. The Pillar B Ledger surface preserves verbatim. The
  Pillar F primitive surfaces + Layer 5 backstop preserve verbatim.
  The Pillar D + E + F + G binding exit-criterion tests STAY GREEN
  at all five rows. The Pillar H Weeks 1-11 + 10 follow-ups surfaces
  preserve VERBATIM; Week 12 ONLY adds the binding test body + the
  Stable flip docs + ADR-0069 + retrospective + Pillar I handoff.

* 4179 passing post-Week-12 (was 4178 + 1 net new — the W12
  binding exit-criterion test); 13 skipped (down from 14 — W12
  binding test un-skipped). Per-week-reviewer disciplines status:
  cell-level matrix coverage **THIRTY-SIX** consecutive weeks +
  behavioral-passthrough-not-signature-only **THIRTY-THREE**
  consecutive weeks + module-level docstring drift **THIRTY-FIVE**
  consecutive weeks + per-pillar mirror constants parity PRESERVED
  + cross-pillar back-audit (NINE consecutive Pillar H weeks of
  ADR-vs-actual-impl drift catches at W2 → W10-11 main; per-week-
  reviewer at Phase 3 catches any TENTH drift) + framework-
  neutrality contract PRESERVED via the W12 binding test's
  ``traced_stage_fn`` + ``serve_health_endpoint_fn`` +
  ``attach_signal_handlers_fn`` substitution + privacy invariant
  OPERATIONALLY VERIFIED at the binding test ROW 6 + atomicity-
  preservation per ADR-0060 D335 invariant 2 OPERATIONALLY
  VERIFIED at ROW 2 + ROW 4 + byte-identical determinism per
  ADR-0031 D140 PRESERVED via the W10-11 ``now_fn`` seam + the
  per-event-class index rebuildability per I3.

**Pillar H Week 12 follow-up** per the per-week-reviewer's independent
review of the W12 main commit (`e6bad16`): 0 P1 + 0 P2 + 3 P3
addressed — the **TENTH consecutive ADR-vs-actual-impl drift in
Pillar H** caught by the per-week-reviewer's cross-pillar back-audit
discipline at the W12 main review (the prior NINE: W2 P3-8 OTel
Resource rationale → W3 P2-1 ``_emitted_by`` audit-marker → W4 P2-1
framework-neutrality → W5 P1-1 ``traced_stage`` signature → W6 P2-2
Step 5.5 ordering → W7 P1-1 Pass G classifier → W8 follow-up P2-1
EventClassIndex catalog → W9 follow-up P2-1 Step 9/Step 10 narrative
→ W10-11 main P1-1 reconcile signature):

* **P3-1 closure — TENTH ADR-vs-actual-impl drift in Pillar H.** The
  W12 main commit's ADR-0069 §Consequences (Neutral) +
  ADR-0068 §Consequences (Neutral) both claimed "EVENT_CLASS_CATALOG
  stays at 25" — an absolute-count claim that was empirically wrong
  (actual count is 63 entries spanning Pillar A-H + Phase 5.5
  surfaces; the "stays at 25" propagated from ADR-0065's W6 narrative
  which was already incorrect at W6). The substantive claim "ZERO
  new event classes at W12" IS correct + IS pinned by the existing
  ``len(DAEMON_NEW_EVENT_CLASSES) == 6`` regression-barrier at
  :class:`tests.test_daemon.TestModuleConstants` per the W6 follow-up
  P3-6 closure. **Severity P3** (narrative-only; no production code
  path broken). **P3-1 CLOSED** via ADR-0069 §Consequences (Neutral)
  + ADR-0068 §Consequences (Neutral) absolute-count claim correction
  + NEW :class:`tests.test_daemon.TestW12FollowupCatalogClaimSubstantive`
  × 2 regression-barriers explicitly naming the substantive claim +
  the TENTH drift trace.

* **P3-2 closure — HANDOFF-pillar-i-week-1.md narrative inconsistency
  ("NINE Pillar H closed-sets" vs ADR-0069 + RETRO "EIGHT").** The
  W12 main commit's HANDOFF said "NINE" but the actual count is
  EIGHT (7 explicit closed-sets exported from
  :mod:`orchestrator.daemon` — :data:`DAEMON_EXIT_REASONS` +
  :data:`DAEMON_LIFECYCLE_STATES` + :data:`DAEMON_NEW_EVENT_CLASSES`
  + :data:`DAEMON_POLICY_RELOAD_SIGNALS` + :data:`HEALTH_PROBE_OUTCOMES`
  + :data:`POLICY_RELOAD_STATUSES` + :data:`SHUTDOWN_REASONS` + 1
  implicit :data:`_PIPELINE_STAGES` mirror at the per-stage tick
  loop). **P3-2 CLOSED** via HANDOFF-pillar-i-week-1.md narrative
  correction.

* **P3-3 closure — discipline-counts narrative inconsistency across
  runner.py docstring vs ADR-0069 vs RETRO vs HANDOFF.** The W12
  main commit used a mix of pre-W12 framing (THIRTY-FIVE / THIRTY-TWO
  / THIRTY-FOUR; counts up to but NOT including W12) at ADR-0069
  §Consequences (Positive) + RETRO + HANDOFF "after Pillar I Week
  1" projection, vs post-W12 framing (THIRTY-SIX / THIRTY-THREE /
  THIRTY-FIVE; counts INCLUDE W12 itself) at runner.py docstring +
  the W12 commit message. The W10-11 follow-up convention
  ("THIRTY-FIVE consecutive weeks after Week 10-11 follow-up"
  counts the W10-11 follow-up commit itself) is canonical: the
  count INCLUDES the current commit. **P3-3 CLOSED** via
  standardization on post-W12 framing across ADR-0069 §Consequences
  (Positive) + RETRO + HANDOFF (THIRTY-SIX / THIRTY-THREE /
  THIRTY-FIVE post-W12 main; THIRTY-SEVEN / THIRTY-FOUR / THIRTY-SIX
  post-W12 follow-up; THIRTY-EIGHT / THIRTY-FIVE / THIRTY-SEVEN at
  Pillar I Week 1 close).

ZERO new ADRs at the W12 follow-up (the follow-up's fixes are
narrative-correction + ONE regression-barrier test class — all in
the spirit of ADR-0069's existing decisions per the per-pillar-
foundation precedent from Pillar G Week 12 follow-up `43612a8` +
Pillar H Week 1-11 follow-ups). 4181 passing post-W12 follow-up
(was 4179 + 2 net new — :meth:`TestW12FollowupCatalogClaimSubstantive.test_pillar_h_daemon_new_event_classes_size_at_w12_close`
+ :meth:`TestW12FollowupCatalogClaimSubstantive.test_pillar_h_daemon_new_event_classes_membership_at_w12_close`);
13 skipped UNCHANGED. Per-week-reviewer disciplines status after
W12 follow-up: cell-level matrix coverage **THIRTY-SEVEN**
consecutive weeks (post-W12-follow-up framing — adds the W12
follow-up itself per the W10-11 follow-up convention) +
behavioral-passthrough-not-signature-only **THIRTY-FOUR**
consecutive weeks + module-level docstring drift **THIRTY-SIX**
consecutive weeks (runner.py + ``__init__.py`` module docstrings
extended naming Pillar H Week 12 follow-up + the THREE closure
categories) + per-pillar mirror constants parity PRESERVED +
cross-pillar back-audit EXTENDED to **TEN consecutive Pillar H
weeks** of ADR-vs-actual-impl drift catches (W2 → W12 main; THREE
P1 escalations at W5 + W7 + W10-11).

**Pillar H Week 12 + follow-up is REVIEWED + CLOSED.** Pillar H is
STABLE 2026-05-28. The per-pillar-H trajectory CLOSES at TWENTY-TWO
total commits (Week 1 + Week 1 follow-up + W2 + W2 follow-up + W3 +
W3 follow-up + W4 + W4 follow-up + W5 + W5 follow-up + W6 + W6
follow-up + W7 + W7 follow-up + W8 + W8 follow-up + W9 + W9
follow-up + W10-11 + W10-11 follow-up + W12 + W12 follow-up). Pillar
I + J unblocked from "Pillar H stable" dependency per ADR-0060
§Downstream pillar impact.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    # Pillar H Week 7 follow-up P3-9 closure — TYPE_CHECKING-guarded
    # import for :class:`_PolicyState.rules` field's narrowed type per
    # the W4 follow-up P3-10 closure precedent (the same discipline
    # narrowed :func:`serve_health_endpoint`'s return type).
    from orchestrator.policy import Rule

# Pillar H Week 5 follow-up P3-6 + NEW-3 + NEW-4 closures: lazy imports
# inside :meth:`DaemonRunner.run` body promoted to module-top per the
# Pillar H Week 3 follow-up P3-2 + P3-3 closures' lazy-import-inconsistency
# discipline. The :mod:`orchestrator.ledger` + :mod:`orchestrator.observability`
# modules do NOT import from :mod:`orchestrator.daemon` (verified at
# Pillar H Week 5 follow-up time), so module-top imports are safe.
# :mod:`orchestrator.daemon.health` MUST stay lazy because health.py
# imports :data:`EMITTED_BY` + :data:`DAEMON_LIFECYCLE_STATES` from this
# module at function bodies (per Week 4 follow-up NEW-1 closure's
# circular-import-avoidance pattern); module-top import would break
# module-load-time ordering.
#
# Pillar H Week 6 follow-up P3-1 + P3-2 + P3-3 + NEW-2 closures rationale
# extension: the THREE lazy-import sites of
# :data:`funnel._PILLAR_G_PIPELINE_STAGES` (inside :meth:`DaemonRunner.run`
# Step 5.5 + :func:`_validate_config` + :func:`build_daemon_stage_saturated_payload`)
# MUST stay lazy. The reason is NOT the circular-dependency concern (funnel
# does NOT import daemon — verified at W6 follow-up commit time) BUT the
# DEEPER production-fragility issue:
# :mod:`orchestrator.funnel`'s module body does ``import ledger as _ledger``
# (bare-name, line 152) which requires :file:`orchestrator/` on ``sys.path``
# — added at test time by :file:`tests/conftest.py` lines 23-25 but NOT
# at production-import time. A module-top ``from orchestrator.funnel import
# _PILLAR_G_PIPELINE_STAGES`` would trigger funnel's module-load → bare
# ``import ledger`` → :exc:`ModuleNotFoundError` in operators invoking
# ``from orchestrator.daemon import init_daemon`` from a clean Python
# process. The lazy form defers funnel's module-load to call-time when
# operators (or the daemon's own bootstrap wrapper) have arranged
# ``sys.path`` correctly. The Week 6 follow-up reviewer NEW finding
# beyond P3-1/2/3/NEW-2 expanded the rationale; the closures instead
# STANDARDIZE the lazy-import STYLE across the three sites (all three
# now use ``from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES``
# rather than the prior _validate_config site's ``import funnel as _funnel``)
# + extend the per-site comments naming the production-fragility rationale.
# A future Pillar I + dev-tooling phase that converts funnel.py to use
# ``from orchestrator.ledger import Ledger`` qualified imports could
# revisit the module-top promotion uniformly across daemon + funnel +
# all other orchestrator/ siblings; until then, lazy is the production-
# safe form.
from orchestrator.ledger import Ledger
from orchestrator import observability as _observability


# ---------------------------------------------------------------------------
# Module constants — Pillar H Week 2 per ADR-0061 D337
# ---------------------------------------------------------------------------


#: Per ADR-0010 D17 — every per-pillar event factory stamps an
#: ``_emitted_by`` marker into the per-event payload for operator-facing
#: filterability (e.g., "show me all events emitted by the daemon
#: subsystem"). Pillar H Week 3 follow-up P2-1 closure: the daemon's
#: lifecycle event factories (``build_daemon_started_payload`` /
#: ``_stopping_payload`` / ``_stopped_payload``) consume this constant
#: at the factory boundary per the Pillar E
#: :data:`orchestrator.tier_assignment.EMITTED_BY` +
#: :data:`orchestrator.discovery_lineage.EMITTED_BY` precedent.
#:
#: **Pillar H Week 3 follow-up P2-1 closure rationale** — the SECOND
#: ADR-vs-actual-impl drift in Pillar H (the FIRST was Week 2 follow-up
#: P3-8 OTel Resource rationale). The Week 3 main commit's factory
#: docstrings + ADR-0062 D343 narrative FALSELY claimed ``_emitted_by``
#: was "auto-filled by :meth:`Ledger.append`" — but
#: :meth:`Ledger.append` only does ``setdefault("v")`` +
#: ``setdefault("ts")``. The Pillar E + Pillar G factories explicitly
#: set ``_emitted_by`` at the factory boundary; the Pillar H factories
#: were inconsistent. The Week 3 follow-up commit aligns Pillar H with
#: the established framework convention + corrects the ADR + docstring
#: text + adds regression-barrier tests at
#: :meth:`tests.test_daemon.TestDaemonStartedPayload.test_payload_carries_emitted_by_marker`
#: + the equivalent at the two new factories.
EMITTED_BY: str = "daemon"


#: Pillar H daemon version string surfaced in :class:`DaemonRunner.version`
#: + the ``daemon_started`` event payload per ADR-0061 D339. Operators
#: query this to identify the daemon binary across restarts; future
#: per-week trajectory bumps coordinate with PILLAR-PLAN §6 Pillar H row.
#:
#: **Pillar H Week 2 follow-up P3-1 closure** — mirrors
#: :data:`observability._SERVICE_VERSION` (currently ``"0.1.0"``). The two
#: constants are semantically distinct (daemon binary version surfaced in
#: ``daemon_started`` payload vs OTel Resource ``service.version`` attribute
#: consumed by Prometheus / Grafana / OTLP backends per ADR-0052 D287) but
#: SHOULD report the same value — both identify "the binary that's running."
#: The per-pillar mirror constants parity discipline (introduced at Pillar
#: G Week 10-11 + ADR-0058 D322 + extended at Pillar G Week 12 follow-up)
#: applies here; the regression-barrier test at
#: :meth:`tests.test_daemon.TestModuleConstants.test_daemon_version_mirrors_service_version`
#: pins parity at test time. A future Pillar I per-tenant author bumping
#: one MUST bump both concurrently.
_DAEMON_VERSION: str = "0.1.0"


# ---------------------------------------------------------------------------
# Closed-sets — R031-shape regression-barriers per ADR-0050 D276 + R037
# (NEW at Pillar H Week 1)
# ---------------------------------------------------------------------------


#: The FOUR daemon lifecycle states per ADR-0060 D335.
#:
#: * ``"initializing"`` — process started; running pre-flight checks
#:   (migrations applied per Pillar B + policy YAML loaded per Pillar A
#:   + OTel SDK initialized per Pillar G Week 3 + Prometheus exporter
#:   listening per Pillar G Week 4). The health endpoint returns 503
#:   in this state.
#: * ``"ready"`` — pre-flight complete; per-stage dispatch running;
#:   reconcile passes running. The health endpoint returns 200.
#: * ``"draining"`` — graceful shutdown initiated via SIGTERM / SIGINT;
#:   in-flight per-stage tasks complete within
#:   ``DaemonConfig.graceful_shutdown_seconds``; no new per-stage tasks
#:   accepted. The health endpoint returns 503.
#: * ``"stopped"`` — drain complete; daemon process exits. The
#:   ``daemon_stopped`` event emits before exit.
#:
#: Pillar I MAY add per-tenant states (``"paused"`` for tenant-level
#: pause without process exit) per the per-tenant audit-tooling
#: trajectory; Pillar H Week 1 ships the FOUR states only.
DAEMON_LIFECYCLE_STATES: frozenset[str] = frozenset({
    "initializing",
    "ready",
    "draining",
    "stopped",
})


#: The SIX new Pillar H event classes per ADR-0060 D331 + ADR-0065 D355
#: (Pillar H Week 6 follow-up P3-5 closure: the prefix comment was
#: previously frozen at "FIVE" despite the closed-set body having SIX
#: entries after the Week 6 catalog extension; the per-pillar mirror
#: constants parity regression-barrier at
#: :meth:`tests.test_daemon.TestDaemonNewEventClasses.test_contains_six_event_classes_per_week_6_addition`
#: pins the count but did NOT catch the comment drift before the Week 6
#: follow-up). Subset of Pillar G's :data:`observability.EVENT_CLASS_CATALOG`
#: per the per-pillar-foundation precedent (Pillar G Week 1 added two
#: new classes via ``OBSERVABILITY_NEW_EVENT_CLASSES``; Pillar H adds
#: SIX via ``DAEMON_NEW_EVENT_CLASSES`` — FIVE at Week 2 per ADR-0061
#: D338 + ONE at Week 6 per ADR-0065 D355).
#:
#: Each event class has its emit-shape pinned at Pillar H's per-week
#: ADR + Pillar G's catalog regression-barrier test per ADR-0051 D279.
#: The per-event-class observability primitive aggregates these
#: uniformly with prior-pillar event classes per ADR-0050 D272.
#:
#: * ``"daemon_started"`` — emit on transition from ``initializing``
#:   to ``ready``. Payload: ``pid`` + ``version`` + ``config_hash`` +
#:   ``startup_seconds`` + ``ts``. Operators query this to determine
#:   "when did the daemon last restart?"
#: * ``"daemon_stopping"`` — emit on transition from ``ready`` to
#:   ``draining``. Payload: ``pid`` + ``reason`` (``sigterm`` |
#:   ``sigint`` | ``operator_requested``) + ``drain_deadline_ts`` +
#:   ``in_flight_task_count`` + ``ts``. Operators query this to see
#:   "why did the daemon stop?"
#: * ``"daemon_stopped"`` — emit before process exit. Payload: ``pid``
#:   + ``exit_reason`` (``clean`` | ``timeout`` | ``crash``) +
#:   ``uptime_seconds`` + ``in_flight_task_count_at_exit`` + ``ts``.
#: * ``"policy_reloaded"`` — emit on SIGHUP-driven policy re-read.
#:   Payload: ``pid`` + ``source_path`` + ``prior_content_hash`` +
#:   ``new_content_hash`` + ``status`` (``applied`` |
#:   ``failed_unchanged``) + ``ts``. The diff is operator-visible
#:   via the two hashes.
#: * ``"health_probe"`` — emit on health endpoint hit. Payload: ``pid``
#:   + ``outcome`` (one of :data:`HEALTH_PROBE_OUTCOMES`) +
#:   ``lifecycle_state`` (one of :data:`DAEMON_LIFECYCLE_STATES`) +
#:   ``remote_addr`` + ``ts``. R038 mitigation pattern (high-frequency
#:   health probes from k8s readiness checks would inflate the ledger;
#:   rate-limit via the at-most-ONE-per-N-seconds pattern per ADR-0060
#:   D335).
#: * ``"daemon_stage_saturated"`` (Pillar H Week 6 NEW per ADR-0065 D355) —
#:   emit per-tick per-funnel-stage when the corresponding
#:   :class:`asyncio.Semaphore` bounded by
#:   :attr:`DaemonConfig.parallelism_limits` is exhausted (all slots
#:   acquired). Payload: ``pid`` + ``stage`` (one of
#:   :data:`funnel._PILLAR_G_PIPELINE_STAGES`) + ``parallelism_limit`` +
#:   ``in_flight_count`` + ``_emitted_by="daemon"`` + ``ts``. Operators
#:   consume via the Pillar H Grafana panel 2 at
#:   ``infra/grafana/dashboards/per_daemon.yml`` (the panel 2 placeholder
#:   from Pillar H Week 4 ADR-0063 D347 goes live at Week 6 commit).
DAEMON_NEW_EVENT_CLASSES: frozenset[str] = frozenset({
    "daemon_started",
    "daemon_stopping",
    "daemon_stopped",
    "policy_reloaded",
    "health_probe",
    "daemon_stage_saturated",
})


#: The closed-set of Unix signal names valid for
#: :attr:`DaemonConfig.policy_reload_signal` per ADR-0060 D335 invariant
#: 4 + the Pillar H Week 1 follow-up P3-2 closure.
#:
#: ``None`` is also valid for :attr:`DaemonConfig.policy_reload_signal`
#: as the operator-deliberate opt-out (disables SIGHUP-driven reload);
#: it is NOT in the closed-set because :class:`frozenset` cannot
#: contain ``None`` as a clean enumeration of "valid signal names."
#: The Week 2 :func:`init_daemon` body validates ``config.policy_reload_signal
#: in DAEMON_POLICY_RELOAD_SIGNALS or config.policy_reload_signal is None``
#: per the refuse-loud convention per I5 + ADR-0001 D2 (operator typo
#: like ``"SIG_HUP"`` with underscore would silently never trigger reload
#: without this barrier).
#:
#: Pillar H Week 1 ships :data:`SIGHUP` only; if Pillar H Week 7+ surfaces
#: operator-deliberate alternatives (e.g., :data:`SIGUSR1` for tenant-
#: scoped reload at Pillar I), the closed-set extends with the new
#: signal name + the Week 7 author updates the regression-barrier test.
DAEMON_POLICY_RELOAD_SIGNALS: frozenset[str] = frozenset({
    "SIGHUP",
})


#: The closed-set of valid :attr:`PolicyReloadResult.status` values per
#: ADR-0060 D335 invariant 4 + the Pillar H Week 1 follow-up P3-3
#: closure (the TestPolicyReloadResult class docstring claimed "closed-
#: enum status" at Week 1 main commit but no regression-barrier test
#: pinned the contents — the Pillar H Week 1 follow-up commit closes
#: the matrix-coverage gap with :class:`TestPolicyReloadStatuses` + a
#: closed-set definition that future per-week-reviewers can grep).
#:
#: * ``"applied"`` — the SIGHUP-driven reload succeeded; new policy
#:   is live; cooldown / suppression / sending-window / budget rule
#:   changes take effect at the next per-stage tick.
#: * ``"failed_unchanged"`` — the YAML parse or per-rule validation
#:   failed; the prior policy remains live; operators see the
#:   ``failed_unchanged`` status in the ``policy_reloaded`` event +
#:   :attr:`PolicyReloadResult.parse_error` carries an operator-
#:   readable error (NOT a Python traceback).
#:
#: Pillar H Week 7+ :meth:`DaemonRunner.reload_policy` body MUST emit
#: only these two status values; an operator-extensible third status
#: (e.g., ``"deferred"`` for tenant-scoped reload at Pillar I) joins
#: the closed-set + the regression-barrier test concurrently with the
#: implementation per the per-pillar mirror constants parity discipline.
POLICY_RELOAD_STATUSES: frozenset[str] = frozenset({
    "applied",
    "failed_unchanged",
})


#: Pillar H Week 7 — the per-funnel-stage → reconcile-passes mapping per
#: ADR-0066 D358. The :meth:`DaemonRunner.run` body's Iteration 6b
#: dispatches the per-funnel-stage reconcile work through
#: :func:`_default_dispatch_for_stage`, which consults this mapping to
#: decide which reconcile passes (defined in :mod:`orchestrator.reconcile`)
#: to invoke for the given funnel stage.
#:
#: **Pure-framework passes only at Week 7** — channel-dispatch passes
#: (A: Gmail intent recovery / B: Gmail replies / D: LinkedIn invite
#: intent / E: LinkedIn DM intent / F: Twitter DM intent / H: LinkedIn
#: invite acceptance / I: LinkedIn DM reply / J: Twitter DM reply) all
#: require per-channel client construction (gmail / linkedin / twitter
#: clients) that the daemon does NOT wire at v1. The :data:`DaemonConfig`
#: surface intentionally omits per-channel client config — operators
#: invoking the per-channel passes from the daemon at Week 8+ extend
#: :data:`DaemonConfig` with per-channel client factory kwargs + the
#: dispatch mapping concurrently per the per-pillar mirror constants
#: parity discipline. Until then, operators invoke channel-dispatch
#: passes from the existing reconcile CLI
#: (``python -m orchestrator.reconcile --passes A,B,D,E,F,H,I,J ...``).
#:
#: The pure-framework passes (C: vault↔ledger heal / G: reply
#: classification / M: auto-unsubscribe handler / N: conversation
#: state machine / O: conversation outcomes) consume ONLY
#: framework-level state — :class:`orchestrator.ledger.Ledger` +
#: :attr:`DaemonRunner.people_dir` + :attr:`DaemonRunner.suppressions_dir`
#: — so the daemon CAN dispatch them at Week 7.
#:
#: Per-stage trajectory:
#:
#: * **Producer stages** (``queued`` / ``researched`` / ``drafted`` /
#:   ``ready``) — these are SKILL-emitted events from
#:   ``/find-leads`` / ``/research-prospect`` / ``/draft-outreach`` /
#:   ``humanizer``; the daemon does NOT dispatch producer work at v1
#:   (skill scope). Empty pass list. Week 8+ may extend if operators
#:   want daemon-driven discovery / research / drafting.
#: * **``sent``** — empty at v1 (channel-dispatch passes A/D/E/F all
#:   need external clients; trajectory at Week 8+). Operators invoke
#:   the reconcile CLI for these passes today.
#: * **``replied``** — Pass G (reply classification, pure framework)
#:   + Pass M (auto-unsubscribe handler, needs only suppressions_dir).
#:   Channel-reply detection (Pass B / H / I / J) deferred per the
#:   channel-dispatch trajectory.
#: * **``outcome_terminal``** — Pass C (vault↔ledger heal, needs only
#:   people_dir) + Pass N (conversation state machine, pure framework)
#:   + Pass O (conversation outcomes, pure framework). All three pure-
#:   framework + path-only; the daemon CAN dispatch at Week 7.
#:
#: Pillar I per-tenant fan-out per ADR-0060 D335 invariant 1 extends
#: this mapping with per-tenant pass-scoping (one daemon process per
#: tenant; each tenant's pass dispatch is isolated by the per-process
#: scope). The regression-barrier test at
#: :class:`tests.test_daemon.TestStageToPassesMapping` pins the v1
#: contents + the per-pillar mirror constants parity discipline.
_STAGE_TO_PASSES: dict[str, str] = {
    "queued": "",  # Producer stage — skill scope, daemon no-op at v1.
    "researched": "",  # Producer stage — skill scope.
    "drafted": "",  # Producer stage — skill scope.
    "ready": "",  # Producer stage — skill scope.
    "sent": "",  # Channel-dispatch passes (A/D/E/F) deferred per ADR-0066 D358.
    "replied": "G,M",  # Reply classification + auto-unsubscribe handler.
    "outcome_terminal": "C,N,O",  # Vault heal + conversation state + outcomes.
}


#: The closed-set of valid ``reason`` values for :meth:`DaemonRunner.shutdown`
#: + the ``daemon_stopping`` event payload's ``reason`` field per ADR-0062
#: D344. Pillar H Week 3 ships THREE reasons:
#:
#: * ``"sigterm"`` — operator / orchestrator (systemd / k8s) sent SIGTERM;
#:   the canonical graceful-shutdown signal per the POSIX convention.
#: * ``"sigint"`` — operator sent SIGINT (typically Ctrl+C); same
#:   graceful-shutdown semantics as SIGTERM but distinguished in the
#:   ``daemon_stopping`` event so operators can correlate dashboards.
#: * ``"operator_requested"`` — operator invoked
#:   :meth:`DaemonRunner.shutdown` via the daemon's CLI shutdown
#:   surface (e.g., admin endpoint at Week 5+ scope; explicit
#:   :meth:`DaemonRunner.shutdown` call from a test substrate or
#:   programmatic shutdown).
#:
#: Pillar I per-tenant audit-tooling MAY extend with per-tenant reasons
#: (e.g., ``"tenant_quota_exceeded"``) per the per-pillar-foundation
#: precedent + the per-pillar mirror constants parity discipline; the
#: regression-barrier test at
#: :meth:`tests.test_daemon.TestShutdownReasons.test_contents_pin_per_adr_0062_d344`
#: pins Pillar H Week 3 contents.
SHUTDOWN_REASONS: frozenset[str] = frozenset({
    "sigterm",
    "sigint",
    "operator_requested",
})


#: The closed-set of valid ``exit_reason`` values for the ``daemon_stopped``
#: event payload per ADR-0062 D344. Pillar H Week 3 ships THREE exit
#: reasons:
#:
#: * ``"clean"`` — drain completed within
#:   :attr:`DaemonConfig.graceful_shutdown_seconds`; all in-flight per-
#:   stage tasks finished; process exits with code 0. (Week 3 always
#:   emits ``"clean"`` because the actual per-stage worker pool lands
#:   at Week 5+; Week 5+ extends emit logic to surface ``"timeout"``
#:   when drain exceeds deadline.)
#: * ``"timeout"`` — drain exceeded the configured deadline; in-flight
#:   tasks were cancelled; process exits with code 124 (per the
#:   established Pillar D Pass A through O exit code convention).
#: * ``"crash"`` — daemon process crashed before clean drain; this
#:   value is emitted ONLY when a crash-recovery path through Pass C+
#:   per ADR-0014 D33 backfills the ``daemon_stopped`` event from a
#:   prior crash (Pillar H Week 10-11 trajectory). Process exits with
#:   code 1.
#:
#: ``SHUTDOWN_REASONS`` (the operator's INTENT) and ``DAEMON_EXIT_REASONS``
#: (the daemon's ACTUAL exit status) are deliberately disjoint closed-sets
#: per ADR-0062 D344's rationale — intent and outcome are operationally
#: distinct in the same way Pillar G's :data:`observability._SLO_NAMES`
#: + :data:`_DRIFT_REASONS` are mutually exclusive per ADR-0049 D263 +
#: ADR-0056 D311.
DAEMON_EXIT_REASONS: frozenset[str] = frozenset({
    "clean",
    "timeout",
    "crash",
})


# ---------------------------------------------------------------------------
# Dataclasses — Week 1 shape only; bodies in Week 2-12
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DaemonConfig:
    """Frozen dataclass for daemon initialization parameters per
    ADR-0060 D331.

    Operator-deliberate config (no defaults for paths; reasonable
    defaults for limits + timeouts). The config is hashed to populate
    :attr:`DaemonRunner.config_hash` so ``daemon_started`` +
    ``policy_reloaded`` events carry an operator-visible config
    identity.

    Fields:

    * ``vault_dir`` — path to the Obsidian vault root. Per the
      existing convention `~/Documents/...`. Required.
    * ``ledger_dir`` — path to the ledger root. Per the existing
      convention `~/.outreach-factory/ledger/`. Required.
    * ``health_port`` — TCP port for the health endpoint. Default
      8080. ``127.0.0.1`` bind by default per R036 (Pillar G Week 4's
      security-by-default Prometheus exposition pattern) — operators
      wanting cross-machine probes wire a reverse proxy.
    * ``parallelism_limits`` — per-stage maximum concurrent tasks.
      Keys are the seven stages from
      :data:`funnel._PILLAR_G_PIPELINE_STAGES`. Default: 1 per stage
      (conservative; operators tune up per their I/O headroom). Pillar
      H Week 5 + ADR-0060 D332's trajectory ships the per-stage worker
      pool body.

      **Per-stage semantics** (Pillar H Week 1 follow-up P3-1 closure):

      * **Send-side stages** (``queued`` / ``researched`` / ``drafted``
        / ``ready`` / ``sent``) — the limit caps max concurrent
        send-pipeline tasks the per-stage worker pool dispatches. The
        ``sent`` stage's limit is the structural rate-limit on
        outbound dispatcher concurrency (Gmail / LinkedIn / Twitter
        SDK calls wrapped via :func:`asyncio.to_thread` per ADR-0060
        D332); the bound matches the per-channel rate-limit policy
        per Pillar A.
      * **Receive-side stages** (``replied`` / ``outcome_terminal``) —
        the limit caps max concurrent classifier / reconcile dispatch
        tasks the per-stage worker pool runs. ``replied`` consumes
        inbound IMAP poll / LinkedIn unread events into
        :func:`reply_classifier.classify` per ADR-0026; ``outcome_terminal``
        consumes :func:`conversation_outcomes.derive_outcome` per
        Pass O per ADR-0030. The default 1 is conservative; operators
        tune up if the per-stage worker pool is the bottleneck.

      **Closed-set mirror** (Pillar H Week 1 follow-up P3-5 closure):

      This 7-stage tuple mirrors :data:`funnel._PILLAR_G_PIPELINE_STAGES`
      (the per-pipeline-event stage closed-set per ADR-0059 D325). The
      complementary :data:`observability._PIPELINE_STAGES` is an
      8-stage frozenset for :func:`traced_stage` span attributes (per
      ADR-0055 D300) — semantically distinct. The daemon's per-stage
      worker pool uses the funnel 7-stage tuple because parallelism is
      bounded per pipeline-event stage (the operator-observable funnel
      progression), NOT per span dim (the operator-observable tracing
      facet). The
      :meth:`tests.test_daemon.TestDaemonConfig.test_parallelism_limits_default_matches_pillar_g_pipeline_stages`
      regression-barrier pins the mirror parity at test time per the
      per-pillar mirror constants parity discipline.
    * ``graceful_shutdown_seconds`` — max time to drain in-flight
      tasks on SIGTERM / SIGINT before forcing exit. Default 30.
      Reconcile loop is the recovery backstop for tasks that don't
      complete within the deadline.
    * ``policy_reload_signal`` — Unix signal that triggers policy
      re-read. Default ``SIGHUP``. Operators may disable via
      ``None``.
    * ``health_probe_rate_limit_seconds`` — minimum interval between
      consecutive ``health_probe`` event emits per R038 mitigation.
      Default 30s. Operators wanting per-request probe events set to
      0; production k8s health probes typically hit every 10s so
      30s rate-limit caps at ~2880 emits/day per single-tenant
      operator.
    * ``policy_dir`` — directory containing the Pillar A policy YAML
      files. Default ``None`` resolves at :func:`init_daemon` time to
      ``vault_dir.parent / "policies"`` (matching the existing
      ``MigrationRunner`` convention per :class:`MigrationRunner`'s
      ``policy_dir`` default). Pillar H Week 7 +
      :meth:`DaemonRunner.reload_policy` re-reads this directory on
      SIGHUP per ADR-0066 D356.
    * ``people_dir`` — directory containing Person notes
      (``*.md`` with ``id:`` frontmatter). Default ``None`` resolves
      at :func:`init_daemon` time to ``vault_dir / "10 People"``
      (matching :data:`migration_0003_baseline_li_invite_history.
      PEOPLE_SUBDIR`). Consumed by Pillar D Pass C (vault↔ledger heal)
      dispatched from the daemon at Pillar H Week 7's per-funnel-stage
      ``outcome_terminal`` tick per ADR-0066 D358.
    * ``suppressions_dir`` — directory containing suppression YAML
      files (per Pillar A's auto-unsubscribe convention). Default
      ``None`` resolves at :func:`init_daemon` time to
      :func:`auto_unsubscribe.suppressions_dir_default` (``~/.outreach-
      factory/suppressions/``). Consumed by Pillar D Pass M
      (auto-unsubscribe handler) dispatched from the daemon at Pillar
      H Week 7's per-funnel-stage ``replied`` tick per ADR-0066 D358.

    Per ADR-0060 D331 the dataclass is FROZEN; mutating fields after
    construction raises ``FrozenInstanceError`` per the standard
    dataclass contract. Re-construct via :func:`dataclasses.replace`.

    Pillar H Week 7 extension — the THREE new optional ``Path | None``
    fields (``policy_dir`` + ``people_dir`` + ``suppressions_dir``)
    factor into :func:`_compute_config_hash` so operators querying
    :attr:`DaemonRunner.config_hash` detect config drift across the
    extended surface; the canonical-JSON serializer renders ``None``
    when unset (consistent with the framework's existing posture for
    optional path fields) and stringifies the resolved Path otherwise.
    """

    vault_dir: Path
    ledger_dir: Path
    health_port: int = 8080
    parallelism_limits: dict[str, int] = field(default_factory=lambda: {
        "queued": 1,
        "researched": 1,
        "drafted": 1,
        "ready": 1,
        "sent": 1,
        "replied": 1,
        "outcome_terminal": 1,
    })
    graceful_shutdown_seconds: int = 30
    policy_reload_signal: str | None = "SIGHUP"
    health_probe_rate_limit_seconds: int = 30
    #: Pillar H Week 7 — optional policy YAML directory per ADR-0066 D356.
    #: Default ``None`` resolves at :func:`init_daemon` time to
    #: ``vault_dir.parent / "policies"`` (the existing convention from
    #: :class:`MigrationRunner`).
    policy_dir: Path | None = None
    #: Pillar H Week 7 — optional Person-notes directory per ADR-0066
    #: D358. Default ``None`` resolves at :func:`init_daemon` time to
    #: ``vault_dir / "10 People"`` (mirroring
    #: :data:`migration_0003_baseline_li_invite_history.PEOPLE_SUBDIR`).
    people_dir: Path | None = None
    #: Pillar H Week 7 — optional suppressions YAML directory per
    #: ADR-0066 D358. Default ``None`` resolves at :func:`init_daemon`
    #: time to :func:`auto_unsubscribe.suppressions_dir_default`.
    suppressions_dir: Path | None = None
    #: Pillar H Week 10-11 NEW per ADR-0068 D366 — optional reconcile
    #: pass list to invoke at daemon startup AFTER crash-recovery
    #: synthesis (Step 4.5) + BEFORE policy load (Step 5). Default
    #: ``None`` = no pre-flight reconcile (test substrate + dev path;
    #: no Gmail / LinkedIn / Twitter SDK calls at startup). Operators
    #: on production set to ``"A"`` (Gmail intent recovery only) or
    #: ``"A,B,D,E,F,H,I,J"`` (the full intent-recovery pass set per
    #: ADR-0014/0017/0018/0027). When set, :func:`init_daemon` Step
    #: 4.6 invokes :func:`reconcile.reconcile(passes=value, apply=True,
    #: ...)` synchronously; failures log to stderr + do NOT prevent
    #: daemon startup (the per-tick reconcile dispatch via Pillar H
    #: Week 7's ``dispatch_fn`` IS the structural backstop; pre-flight
    #: is operator convenience). The R037 mitigation pattern per
    #: ADR-0060 §Risks is operationally landed at Pillar H Week 10-11.
    reconcile_passes_at_startup: str | None = None
    #: Pillar I Week 2 NEW per ADR-0070 D371 + D376 — optional per-tenant
    #: identifier. Default ``None`` preserves single-tenant operators
    #: (the framework default per the single-tenant-first trajectory per
    #: ADR-0070 D371); a non-empty string opts into per-tenant mode (one
    #: daemon process per tenant per ADR-0060 D335 invariant 1). When set,
    #: it factors into :func:`_compute_config_hash` so operators querying
    #: :attr:`DaemonRunner.config_hash` see distinct per-tenant config
    #: identities. Per-tenant ledger / policy directories are resolved via
    #: :func:`orchestrator.multi_tenant.resolve_per_tenant_ledger_dir` /
    #: :func:`resolve_per_tenant_policy_dir` from the tenant_id.
    tenant_id: str | None = None


@dataclass(frozen=True)
class PolicyReloadResult:
    """Frozen dataclass for the SIGHUP-driven policy reload outcome
    per ADR-0060 D335.

    * ``status`` — ``"applied"`` (the reload succeeded + new policy
      is live) | ``"failed_unchanged"`` (the YAML parse / validation
      failed; the prior policy remains live; operators see the
      ``failed_unchanged`` status in the ``policy_reloaded`` event +
      can correct via the source file).
    * ``source_path`` — path to the reloaded policy YAML.
    * ``prior_content_hash`` — content hash of the policy at the time
      of the last successful load.
    * ``new_content_hash`` — content hash of the policy at the time
      of the reload attempt.
    * ``parse_error`` — present iff ``status == "failed_unchanged"``;
      operator-readable error message (NOT a Python traceback).
    * ``reloaded_at_ts`` — ISO-8601 UTC; the reload attempt's timestamp.

    The diff between ``prior_content_hash`` + ``new_content_hash`` is
    operator-visible via the ``policy_reloaded`` event's payload.
    Pillar I per-tenant audit-tooling MAY surface a per-tenant
    policy-reload-rate dashboard consuming this event class.
    """

    status: str  # "applied" | "failed_unchanged"
    source_path: Path
    prior_content_hash: str
    new_content_hash: str
    reloaded_at_ts: str
    parse_error: str | None = None


@dataclass
class _PolicyState:
    """Pillar H Week 7 — mutable holder for runtime policy state per
    ADR-0066 D356.

    The :class:`DaemonRunner` is FROZEN, but
    :meth:`DaemonRunner.reload_policy` MUST swap the currently-effective
    policy rules + content hash on a successful reload — the frozen
    invariant protects field RE-ASSIGNMENT (e.g.,
    ``runner.policy_state = new_state`` is refused) but allows MUTATING
    the held :class:`_PolicyState` instance directly
    (``runner.policy_state.rules = ...`` is permitted because
    :attr:`DaemonRunner.policy_state` is a reference field).

    Two fields:

    * ``rules`` — the loaded :class:`orchestrator.policy.Rule` instances
      (or empty list if no policy YAML files have been loaded yet).
    * ``content_hash`` — SHA-256 hex digest of the canonical-bytes
      representation of all YAML files under the policy directory
      (sorted by filename for determinism; computed by
      :func:`_compute_policy_content_hash`). Empty string ``""`` if
      no files have been loaded yet.

    **Why a separate mutable holder rather than extending the
    ``object.__setattr__`` escape hatch?** The Pillar H Week 3
    follow-up P3-1 closure + Week 5 follow-up NEW-5 closure scoped the
    frozen-dataclass escape hatch to :attr:`DaemonRunner.lifecycle_state`
    ONLY (with explicit regression-barriers at
    :meth:`TestShutdownBody.test_only_lifecycle_state_mutates_during_shutdown`
    + :meth:`TestDaemonRunBody.test_only_lifecycle_state_mutates_during_run_per_w5_followup_new_5`).
    Extending the escape hatch to a SECOND field would weaken the
    discipline + force the regression-barriers to handle two
    explicitly-allowed-mutating fields. A separate mutable holder
    preserves the lifecycle_state-only escape hatch + makes the policy
    state's mutability operator-readable at the field declaration.

    Pillar I per-tenant fan-out per ADR-0060 D335 invariant 1 extends
    naturally — each tenant container's :class:`DaemonRunner` holds an
    independent :class:`_PolicyState`; per-tenant policy reloads do not
    affect other tenants.

    The dataclass is :func:`dataclasses.dataclass` (NOT frozen). The
    underscore prefix marks it as a private implementation detail — the
    public surface is :meth:`DaemonRunner.reload_policy` returning a
    :class:`PolicyReloadResult`.
    """

    #: Pillar H Week 7 follow-up P3-9 closure — type narrowed via
    #: TYPE_CHECKING-guarded import of :class:`orchestrator.policy.Rule`
    #: per the W4 follow-up P3-10 closure precedent (the same
    #: discipline narrowed :func:`serve_health_endpoint`'s return
    #: type). The W7 main commit declared ``rules: list`` (implicit
    #: ``list[Any]``); operators reading the field saw no type info.
    rules: "list[Rule]" = field(default_factory=list)
    content_hash: str = ""


@dataclass
class EventClassIndex:
    """Pillar H Week 8 — in-memory per-event-class index per ADR-0060
    D336 + ADR-0067 D359.

    Denormalized projection of the ledger keyed by event class. The
    daemon-process consumer (the per-Person primitives via the
    optional ``event_class_index`` kwarg per ADR-0067 D361) gets
    O(M_class) per-call cost instead of the O(N) full-ledger walk.

    **Mutable holder pattern** mirroring the Pillar H Week 7
    :class:`_PolicyState` precedent per ADR-0066 D356. The
    :class:`DaemonRunner` is FROZEN but :class:`EventClassIndex` is
    NOT — Pillar H Week 9 ships :meth:`Ledger.append`-driven
    invalidation per ADR-0060 D336 (the held instance is mutated
    in-place; the field REFERENCE on :class:`DaemonRunner` is still
    protected by the frozen invariant). This is the documented
    alternative to extending the :func:`object.__setattr__` escape
    hatch per the Pillar H Week 3 follow-up P3-1 + Week 5 follow-up
    NEW-5 + Week 7 P3-1 closures' lifecycle_state-only scope.

    **Privacy invariant** per I8 + ADR-0050 D276(b) + ADR-0058 D323.
    The index stores event DICT views (with the same fields as the
    ledger event); no body / source_list / draft body is materialized
    that isn't already in the ledger. The :meth:`events_for_class`
    query returns Event-wrapped objects (identical shape to
    :meth:`Ledger.all_events`) so operators consuming the index get
    the same surface they get from the ledger.

    **Defensive-copy query** — :meth:`events_for_class` returns a
    fresh list of Event-wrapped objects on each call; operators
    mutating the returned list do NOT mutate the index's internal
    ``_data``. Week 9's invalidation will mutate ``_data`` directly;
    the defensive-copy posture insulates callers from concurrent
    mutation.

    Refuses-loud on uncatalogued event_class per the closed-set
    discipline + the per-pillar mirror constants parity discipline.

    **Pillar H Week 9 — :attr:`_last_updated_at_ts` field** per
    ADR-0067 D362 (W9 extension to ADR-0067 per ADR-0060 D336).
    Unix-epoch timestamp (seconds, float) set by
    :func:`_materialize_indexes` at daemon startup + by the
    per-append invalidation observer
    (:func:`_install_index_invalidation_observer`) on every
    subsequent :meth:`Ledger.append`. The Prometheus observable
    gauge ``outreach_factory_daemon_index_last_updated_timestamp``
    registered at :func:`init_daemon` Step 9.5 via
    :func:`observability.register_daemon_index_observable_gauge`
    consults this field to expose the index freshness as an
    operator SLO signal per ADR-0067 D363 (the Grafana panel #6
    at :file:`infra/grafana/dashboards/per_daemon.yml` renders
    ``time() - <gauge>`` as the index age in seconds; goes RED
    if age > 60s).
    """

    _data: dict[str, list[dict]] = field(default_factory=dict)
    #: Pillar H Week 9 per ADR-0067 D362 — Unix-epoch timestamp
    #: (seconds, float) advanced on every index update. Set initially
    #: to 0.0 (sentinel for "never materialized"); :func:`_materialize_indexes`
    #: sets it to ``time.time()`` at daemon startup; the per-append
    #: invalidation observer advances it on each :meth:`Ledger.append`.
    #: The Prometheus gauge per ADR-0067 D363 consults this field via
    #: a closure registered at :func:`init_daemon` Step 9.5.
    _last_updated_at_ts: float = field(default=0.0)

    def events_for_class(self, event_class: str) -> "list":
        """Return Event-wrapped chronologically-sorted events for the
        given class.

        Refuses-loud on ``event_class`` outside the "known classes"
        set — :data:`observability.EVENT_CLASS_CATALOG` ∪
        :data:`observability.OBSERVABILITY_NEW_EVENT_CLASSES` (the
        Pillar H Week 8 follow-up P2-1 closure extends the scope to
        match Pillar G's :func:`collect_event_class_snapshots`
        consumer surface precedent per the per-pillar mirror constants
        parity discipline).

        Args:
            event_class: One of :data:`EVENT_CLASS_CATALOG` ∪
                :data:`OBSERVABILITY_NEW_EVENT_CLASSES` (~27 classes
                at v1 post-W8-follow-up).

        Returns:
            List of :class:`orchestrator.ledger.Event` — chronologically
            sorted (the ledger preserves ts-order on
            :meth:`Ledger.all_events`). Empty list if no events of the
            given class have been indexed.

        Raises:
            ValueError: If ``event_class`` not in
                :data:`EVENT_CLASS_CATALOG` ∪
                :data:`OBSERVABILITY_NEW_EVENT_CLASSES` per the
                closed-set discipline (the W8 follow-up P2-1
                closure's extended scope).
        """
        # Pillar H Week 8 follow-up P2-1 closure — the SEVENTH ADR-vs-
        # actual-impl drift in Pillar H caught by the per-week-reviewer's
        # cross-pillar back-audit discipline (the prior SIX: W2 P3-8 OTel
        # Resource rationale; W3 P2-1 ``_emitted_by`` audit-marker; W4
        # P2-1 framework-neutrality text; W5 P1-1 ``traced_stage``
        # signature; W6 P2-2 Step 5.5 ordering; W7 P1-1 Pass G classifier
        # dependency). The W8 main commit's catalog scope at this query
        # boundary was ``EVENT_CLASS_CATALOG`` only — diverging from the
        # Pillar G :func:`observability.collect_event_class_snapshots`
        # consumer surface precedent at
        # :file:`orchestrator/observability.py:910` which uses
        # ``expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES`` as its
        # "known classes" set. The W8 follow-up extends the catalog
        # scope to match per the per-pillar mirror constants parity
        # discipline — operators querying for ``slo_violation_detected``
        # (Pillar G Week 7-8 emit per ADR-0056) or
        # ``observability_class_uncatalogued`` (Pillar G Week 2 emit per
        # ADR-0051 D279) now see the EventClassIndex query API accept
        # them + the :func:`_materialize_indexes` body include them in
        # the index. ADR-0067 D359 narrative corrected (the W8 follow-up
        # addendum) naming the SEVENTH ADR-vs-actual-impl drift + the
        # extended catalog scope.
        #
        # Lazy import of :class:`Event` avoids module-top circular
        # concern with :mod:`orchestrator.ledger` (Event class is
        # imported lazily here per the per-pillar-H lazy-import
        # discipline; :mod:`observability` is already module-top per
        # Pillar H Week 5 follow-up P3-6).
        known_classes = (
            _observability.EVENT_CLASS_CATALOG
            | _observability.OBSERVABILITY_NEW_EVENT_CLASSES
        )
        if event_class not in known_classes:
            raise ValueError(
                f"EventClassIndex.events_for_class: event_class "
                f"{event_class!r} not in "
                f"observability.EVENT_CLASS_CATALOG | "
                f"observability.OBSERVABILITY_NEW_EVENT_CLASSES. "
                f"Per Pillar H Week 8 ADR-0067 D359 closed-set "
                f"discipline + the per-pillar mirror constants parity "
                f"discipline + the W8 follow-up P2-1 closure's "
                f"SEVENTH ADR-vs-actual-impl drift closure."
            )
        from orchestrator.ledger import Event as _Event  # noqa: PLC0415
        return [_Event.from_dict(d) for d in self._data.get(event_class, [])]


@dataclass
class PersonEventIndex:
    """Pillar H Week 8 — in-memory per-Person index per ADR-0060 D336
    + ADR-0067 D359.

    Denormalized projection of the ledger keyed by ``person_id``. The
    daemon-process consumer (future Pillar I per-tenant per-Person
    operator dashboard's "show me all events for this Person" surface)
    gets O(M_person) per-call cost instead of the O(N) full-ledger
    walk.

    **Mutable holder pattern** mirroring :class:`EventClassIndex` +
    the Pillar H Week 7 :class:`_PolicyState` precedent per ADR-0066
    D356. The :class:`DaemonRunner` is FROZEN but :class:`PersonEventIndex`
    is NOT — Pillar H Week 9 ships :meth:`Ledger.append`-driven
    invalidation per ADR-0060 D336.

    **Privacy invariant** per I8 + ADR-0050 D276(b) + ADR-0058 D323.
    The index is keyed by ``person_id`` (operator-private operationally
    per the Person/Identity separation in Phase 5.5). The keyed
    surface is daemon-process-local + rebuilt from the ledger at
    startup — the daemon contributes NO new state that bypasses the
    ledger per ADR-0060 D335 invariant 2. The stored ``_data`` values
    are event DICT views (with the same fields as the ledger event);
    no body / source_list / draft body is materialized that isn't
    already in the ledger.

    **Defensive-copy query** — :meth:`events_for` returns a fresh
    list of Event-wrapped objects on each call (mirrors
    :class:`EventClassIndex`'s defensive-copy posture).

    Events with NULL ``person_id`` are SKIPPED from the index at
    materialization time per the "Person-less events bucket"
    convention per ADR-0045 D231 (ad-hoc validation events do NOT
    have person_id; they are still indexed in :class:`EventClassIndex`
    by type).

    **Pillar H Week 9 — :attr:`_last_updated_at_ts` field** per
    ADR-0067 D362 (W9 extension to ADR-0067 per ADR-0060 D336).
    Mirrors the :class:`EventClassIndex._last_updated_at_ts` field —
    both indexes are invalidated together by the same observer per
    :meth:`Ledger.append` so the two ``_last_updated_at_ts``
    timestamps advance in lockstep at v1 (the v1 invariant is
    documented + pinned by the regression-barrier test
    ``TestEventClassIndexLastUpdatedAtTs::test_both_indexes_share_last_updated_at_ts_at_v1_per_lockstep_invariant``;
    Pillar H Week 9 follow-up P3-1 closure corrects the W9 main
    commit's test-name attribution drift mirroring the W8 follow-up
    P3-1 + P3-2 closures' discipline at the same site).
    """

    _data: dict[str, list[dict]] = field(default_factory=dict)
    #: Pillar H Week 9 per ADR-0067 D362 — Unix-epoch timestamp
    #: (seconds, float) advanced on every index update. See
    #: :class:`EventClassIndex._last_updated_at_ts` for the canonical
    #: docstring. Both indexes share the same invalidation observer
    #: so the timestamps advance in lockstep at v1.
    _last_updated_at_ts: float = field(default=0.0)

    def events_for(self, person_id: str) -> "list":
        """Return Event-wrapped chronologically-sorted events for the
        given Person.

        Args:
            person_id: The Person identifier (operator-private per
                I8 + the Person/Identity separation in Phase 5.5).

        Returns:
            List of :class:`orchestrator.ledger.Event` — chronologically
            sorted. Empty list if no events for the given Person have
            been indexed (e.g., the Person was just enrolled but no
            downstream events exist yet, OR the Person is not in the
            ledger at all).
        """
        from orchestrator.ledger import Event as _Event  # noqa: PLC0415
        return [_Event.from_dict(d) for d in self._data.get(person_id, [])]


@dataclass(frozen=True)
class DaemonRunner:
    """The Pillar H daemon main-loop primitive per ADR-0060 D331.

    Week 1 ships the **signature only** (this dataclass + the
    :meth:`run` / :meth:`shutdown` / :meth:`reload_policy` / :meth:`health`
    method signatures; all bodies raise ``NotImplementedError`` until
    Pillar H Week 5+ ships the per-week trajectory bodies per ADR-0060
    D332).

    Fields:

    * ``config`` — the :class:`DaemonConfig` passed to :func:`init_daemon`.
    * ``config_hash`` — operator-visible identity of the config; hashed
      from the dataclass's frozen fields. Populated by :func:`init_daemon`.
    * ``pid`` — the daemon process's OS PID. Populated by
      :func:`init_daemon`.
    * ``started_at_ts`` — ISO-8601 UTC; the daemon's start timestamp.
    * ``version`` — the daemon's version string. Operator-visible in
      ``daemon_started`` event's payload.
    * ``lifecycle_state`` — current state from
      :data:`DAEMON_LIFECYCLE_STATES`. Set to ``"initializing"`` by
      :func:`init_daemon`; transitions via per-week primitives.

    The dataclass is FROZEN; lifecycle transitions go through
    :func:`dataclasses.replace` (per Pillar G Week 5's OTel state
    transitions per ADR-0054 D294 + the per-event-class observability
    primitive's stateless contract per ADR-0050 D272 + R033 mitigation).
    The Week 5+ implementation manages transitions via the per-stage
    worker pool's state.
    """

    config: DaemonConfig
    config_hash: str
    pid: int
    started_at_ts: str
    version: str
    lifecycle_state: str = "initializing"
    #: Pillar H Week 7 — mutable holder for runtime policy state per
    #: ADR-0066 D356. The :class:`_PolicyState` instance is mutated
    #: in-place by :meth:`reload_policy` (the frozen-dataclass
    #: invariant protects the field reference, not the held instance).
    #: Defaults to an empty :class:`_PolicyState` (no rules loaded;
    #: content_hash=``""``) so :class:`DaemonRunner` constructed
    #: directly by tests (bypassing :func:`init_daemon`) works without
    #: explicit ``policy_state`` kwarg; :func:`init_daemon` populates
    #: at startup by reading :attr:`DaemonConfig.policy_dir` (or the
    #: ``vault_dir.parent / "policies"`` default).
    policy_state: _PolicyState = field(default_factory=_PolicyState)
    #: Pillar H Week 8 — in-memory per-event-class index per ADR-0067
    #: D359 + ADR-0060 D336 (R039 mitigation pattern). Populated at
    #: :func:`init_daemon` Step 8 by walking the ledger once; query
    #: API at :meth:`EventClassIndex.events_for_class` is O(M_class).
    #: The held instance is MUTABLE (Week 9 ships :meth:`Ledger.append`-
    #: driven invalidation per ADR-0060 D336); the field REFERENCE is
    #: protected by the frozen-dataclass invariant.
    #:
    #: Defaults to an empty :class:`EventClassIndex` so
    #: :class:`DaemonRunner` constructed directly by tests (bypassing
    #: :func:`init_daemon`) works without explicit ``event_class_index``
    #: kwarg.
    event_class_index: EventClassIndex = field(default_factory=EventClassIndex)
    #: Pillar H Week 9 per ADR-0067 D362 — the daemon-process Ledger
    #: instance. Populated by :func:`init_daemon` Step 8 (lifted from
    #: the Week 8 local-only construction); :func:`init_daemon` Step 8.5
    #: (NEW) registers the per-event-class index invalidation observer
    #: on this Ledger instance so every subsequent
    #: :meth:`Ledger.append` mutates both indexes in-place. The
    #: :func:`_default_dispatch_for_stage` body consumes
    #: ``runner.ledger`` (if not None) instead of lazy-constructing a
    #: new :class:`Ledger` per dispatch — preserving the observer
    #: registration across all daemon-process appends.
    #:
    #: Defaults to ``None`` so :class:`DaemonRunner` constructed
    #: directly by tests (bypassing :func:`init_daemon`) works without
    #: explicit ``ledger`` kwarg; :func:`_default_dispatch_for_stage`
    #: falls back to lazy-construction when ``runner.ledger is None``
    #: (preserves backward compat with W7-W8 tests + external
    #: operator-invoked dispatchers).
    ledger: "Ledger | None" = None
    #: Pillar H Week 8 — in-memory per-Person index per ADR-0067 D359
    #: + ADR-0060 D336. Populated at :func:`init_daemon` Step 8 by
    #: walking the ledger once; query API at
    #: :meth:`PersonEventIndex.events_for` is O(M_person). The held
    #: instance is MUTABLE (Week 9 ships invalidation); the field
    #: REFERENCE is protected by the frozen-dataclass invariant.
    person_event_index: PersonEventIndex = field(default_factory=PersonEventIndex)

    async def run(
        self,
        *,
        attach_signal_handlers_fn: Callable[..., Any] | None = None,
        serve_health_endpoint_fn: Callable[..., Any] | None = None,
        traced_stage_fn: Callable[..., Any] | None = None,
        emit_fn: Callable[[dict], Any] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        tick_seconds: float = 1.0,
        loop: asyncio.AbstractEventLoop | None = None,
        # Pillar H Week 6 follow-up P2-1 + P3-11 closure: test-only seam
        # for behavioral-passthrough regression-barrier on the Iteration
        # 6b Semaphore saturation emit path. Default :class:`asyncio.Semaphore`
        # is the production backend; tests inject an always-locked subclass
        # to exercise the body's ``sem.locked()`` check + the
        # ``daemon_stage_saturated`` emit per ADR-0065 D355. The seam
        # follows the Pillar G TEST-ONLY convention + the Pillar H Week
        # 2-5 precedent — it substitutes a BACKEND (the asyncio
        # primitive) per the W4 follow-up P2-1 closure's two-tiered
        # seam-vs-fork distinction; operators wanting alternative
        # concurrency models (threading / trio / gevent) MUST fork the
        # function body per the per-pillar-H precedent.
        semaphore_factory_fn: Callable[[int], Any] | None = None,
        # Pillar H Week 7 — test-only seam for the Iteration 6b per-
        # funnel-stage dispatch per ADR-0066 D358. Production default
        # (``None``) lazy-resolves to :func:`_default_dispatch_for_stage`
        # — a closure over ``self`` that invokes the pure-framework
        # reconcile passes from :data:`_STAGE_TO_PASSES` for the given
        # funnel stage via :func:`asyncio.to_thread` (the reconcile
        # functions are sync). Tests inject spies that capture
        # (stage, call_count) for behavioral-passthrough verification of
        # the per-funnel-stage tick contract. The seam preserves the
        # framework-neutrality contract per the W4 follow-up P2-1
        # closure's two-tiered seam-vs-fork distinction: substitutes a
        # BACKEND (the reconcile-passes dispatch path) for test-time
        # injection; operators wanting alternative dispatch frameworks
        # (e.g., distributed task queue) MUST fork the function body.
        # Pillar H Week 7 follow-up P3-1 + P3-6 closure — type
        # narrowed from ``Callable[[str], Any]`` to
        # ``Callable[[str], Awaitable[None]]`` to match the body's
        # ``await dispatch_fn(stage)`` invocation. The Awaitable import
        # was added to the module-top imports per the W5 follow-up
        # P3-6+NEW-3+NEW-4 closures' module-top-imports discipline.
        dispatch_fn: Callable[[str], Awaitable[None]] | None = None,
    ) -> int:
        """Main-loop entry point per ADR-0060 D331 + ADR-0064 D349.

        **Pillar H Week 5 body** wiring the asyncio event loop per
        ADR-0064 D349. The body executes eight ordered steps (Pillar
        H Week 5 follow-up P3-1 + NEW-1 closure renumber: prior W5
        narrative called this "seven-step" while the docstring
        enumerated 8; ADR-0064 D349 rewritten to "eight-step
        ordering" so narrative + code agree):

        1. Refuse-loud if ``lifecycle_state != "initializing"``
           (a runner constructed in any other state via :func:`init_daemon`
           would be a programming error; run() is the ONLY production
           caller that transitions initializing → ready).
        2. Transition lifecycle state from ``"initializing"`` to
           ``"ready"`` via :func:`object.__setattr__` per the Pillar H
           Week 3 frozen-dataclass escape hatch convention per ADR-0062
           D342; the per-pillar-H lifecycle is the internal allow-
           listed mutation site (the Pillar H Week 5 follow-up NEW-5
           closure adds
           :meth:`TestDaemonRunBody.test_only_lifecycle_state_mutates_during_run`
           regression-barrier mirroring the Week 3 follow-up P3-1
           closure's discipline at :meth:`shutdown`).
        3. Emit ``daemon_started`` event via
           :func:`build_daemon_started_payload` + ``emit_fn`` (default
           lazy-constructs :class:`orchestrator.ledger.Ledger`); the
           ``startup_seconds`` field carries ``now - started_at_ts``.
        4. Wire signal handlers via :func:`attach_signal_handlers`
           (SIGTERM → shutdown("sigterm"); SIGINT → shutdown("sigint");
           SIGHUP → reload_policy with NotImplementedError swallow at
           Week 3 trajectory bridge per ADR-0062 D341).
        5. Start the health endpoint server via
           :func:`serve_health_endpoint` (returns the
           :class:`aiohttp.web.AppRunner` instance; retain for graceful
           shutdown cleanup at Step 7).
        6. Per-stage worker pool dispatch loop **skeleton** per
           ADR-0064 D349 — iterate over sorted
           :data:`observability._PIPELINE_STAGES` (deterministic
           ordering per ADR-0031 D140) + wrap each per-stage tick in
           :func:`observability.traced_stage` per ADR-0064 D350 +
           ADR-0055 D300 (the Pillar H Week 5 follow-up P1-1 closure
           passes the operation argument ``"tick"`` at the Week 5
           skeleton; Week 6+ replaces ``"tick"`` with per-stage actual
           operation names like ``"email"`` for the send stage). Week
           6+ extends with actual concurrent dispatch via
           :class:`asyncio.Semaphore` bounded by
           :attr:`DaemonConfig.parallelism_limits`. The loop exits
           when ``lifecycle_state != "ready"`` (set by
           :meth:`shutdown` via the frozen-dataclass escape hatch).
        7. Graceful shutdown coordination per ADR-0064 D352 —
           :meth:`AppRunner.cleanup` waits for in-flight HTTP
           requests to complete before releasing the health
           endpoint's port (aiohttp's documented graceful shutdown
           contract). The ``try``/``finally`` block ensures cleanup
           fires on BOTH the clean-shutdown path (lifecycle_state
           transitions out of "ready") AND the ungraceful path
           (exception inside the tick loop OR
           :exc:`asyncio.CancelledError` propagating from
           ``task.cancel()``). The Pillar H Week 5 follow-up P2-2
           closure adds
           :meth:`TestDaemonRunBody.test_calls_health_endpoint_cleanup_on_exception_path`
           regression-barrier pinning the ungraceful-shutdown path
           at test time.
        8. Return ``0`` on clean shutdown.

        Args:
            attach_signal_handlers_fn: test-only seam — substitutes
                :func:`attach_signal_handlers`. Default uses production
                signal wiring; tests inject a spy to avoid real OS
                signal handler registration (which conflicts with
                pytest's own signal handling).
            serve_health_endpoint_fn: test-only seam — substitutes
                :func:`serve_health_endpoint`. Default uses production
                aiohttp server; tests inject a spy that returns a
                stub AppRunner with an async ``cleanup`` method (to
                avoid real HTTP port binding).
            traced_stage_fn: test-only seam — substitutes
                :func:`observability.traced_stage`. Default uses
                production OTel span wrapping; tests inject a spy
                that records per-stage invocations. **The spy's
                signature MUST match production's
                ``traced_stage(stage: str, operation: str, *,
                attributes=None, tracer=None)``** per the Pillar H
                Week 5 follow-up P1-1 closure (the prior Week 5
                main commit's spy accepted ONE positional arg + the
                body invoked ``traced_stage_fn(stage)`` with one
                arg — production default broke with
                ``TypeError: traced_stage() missing 1 required
                positional argument: 'operation'`` because
                production ``observability.traced_stage`` requires
                ``operation`` as the second positional argument +
                refuses-loud on empty operation per ADR-0054 D296;
                the FOURTH ADR-vs-actual-impl drift in Pillar H per
                the per-week-reviewer's cross-pillar back-audit
                discipline; the W5 follow-up commit aligns body +
                spy + ADR-0064 D350 narrative).
            emit_fn: test-only seam — substitutes
                :meth:`Ledger.append`. Default lazy-constructs
                :class:`orchestrator.ledger.Ledger` from
                ``self.config.ledger_dir`` **once per run() call** per
                the Pillar H Week 5 follow-up P3-8 closure (Step 1's
                refuse-loud on non-initializing state prevents re-
                invocation of run() within the same DaemonRunner
                lifecycle; Pillar I per-tenant fan-out invokes one
                ``run()`` per tenant container per ADR-0060 D335
                invariant 1, so each tenant's Ledger is independently
                constructed). Tests inject a list-append spy to
                capture daemon_started emit.
            now_fn: test-only seam — substitutes :func:`datetime.now`.
                Default returns ``datetime.now(tz=timezone.utc)``;
                tests inject deterministic clocks to verify
                ``startup_seconds`` arithmetic is precise.
            tick_seconds: per-stage tick cadence (default 1.0s).
                Tests inject very small values (e.g., 0.001) to make
                the loop iterate fast. **MUST be > 0** per the
                Pillar H Week 5 follow-up P2-3 closure — refuse-loud
                on ``<= 0`` matches the Pillar H Week 2 follow-up
                P2-1 closure's "next-tier invariant-bearing field
                refuse-loud at boundary" discipline (per-tier
                invariant: ``tick_seconds=0`` would cause a tight
                busy-loop without asyncio.sleep cooperation;
                negative values raise ValueError inside
                asyncio.sleep with a less operator-readable
                message). A future
                ``DaemonConfig.tick_seconds`` field extension at
                Week 6+ would supersede this kwarg for production
                operators (the kwarg remains for test-only-seam
                injection).
            loop: the asyncio event loop. Default uses
                :func:`asyncio.get_running_loop`. **MUST be invoked
                from within an active asyncio event loop** —
                operators calling ``runner.run()`` directly from
                synchronous code get a
                :exc:`RuntimeError` with operator-readable wording
                per the Pillar H Week 5 follow-up P2-4 closure.
                Canonical operator pattern is
                ``asyncio.run(runner.run())`` per ADR-0064
                §Existing-operator seed.
            semaphore_factory_fn: test-only seam — substitutes
                :class:`asyncio.Semaphore` constructor. Default uses
                the production asyncio primitive per ADR-0060 D332's
                asyncio framework decision; tests inject an
                always-locked subclass (e.g.,
                ``class _AlwaysLockedSemaphore(asyncio.Semaphore):
                def locked(self): return True``) to exercise the body's
                Iteration 6b ``sem.locked()`` check + the
                ``daemon_stage_saturated`` emit path per ADR-0065
                D355. The seam follows the Pillar G TEST-ONLY
                convention + the Pillar H Week 2-5 precedent —
                substitutes a BACKEND per the W4 follow-up P2-1
                closure's two-tiered seam-vs-fork distinction.
                **The Pillar H Week 6 follow-up P2-1 + P3-11 closures**
                introduce this seam to fix the behavioral-passthrough
                gap at the body-level Semaphore saturation path (the
                W6 main commit's coherence test only exercised the
                factory; the body's Iteration 6b emit path was
                structurally untested — the same shape as the W5 P1-1
                spy-vs-production drift failure mode the discipline is
                designed to catch).

        Returns:
            The process exit code: ``0`` on clean shutdown via
            :meth:`shutdown` (graceful-shutdown path). Week 6+
            extends with non-zero codes for drain-timeout + crash
            paths per ADR-0062 D344 + ADR-0064 trajectory.

        Raises:
            :exc:`RuntimeError`: if ``lifecycle_state != "initializing"``
                at run() entry per Step 1 OR if invoked outside an
                asyncio event loop (no running loop available for
                ``asyncio.get_running_loop()``) per the Pillar H
                Week 5 follow-up P2-4 closure.
            :exc:`ValueError`: if ``tick_seconds <= 0`` per the
                Pillar H Week 5 follow-up P2-3 closure.
            :exc:`asyncio.CancelledError`: propagates from
                ``task.cancel()`` per asyncio's documented
                cancellation semantics; the ``finally`` block at
                Step 7 still fires + releases the health endpoint
                port before the CancelledError reaches the caller
                per the Pillar H Week 5 follow-up NEW-6 closure.

        **Framework-neutrality contract per Pillar H Week 4 follow-up
        P2-1 closure** — the test-only seam kwargs substitute
        BACKENDS (ledger + clock + signal wiring + HTTP server +
        tracer) WITHOUT replacing the function body. Operators
        wanting alternative concurrency models (gevent / trio /
        threading) MUST replace the entire :meth:`run` body per the
        per-pillar-H precedent; the asyncio framework choice per
        ADR-0060 D332 is the v1 default.
        """
        # Step 1: Refuse-loud on non-initializing state.
        if self.lifecycle_state != "initializing":
            raise RuntimeError(
                f"DaemonRunner.run requires lifecycle_state == "
                f"'initializing'; got {self.lifecycle_state!r}. "
                f"init_daemon constructs the runner in 'initializing' "
                f"state; run() is the ONLY production caller that "
                f"transitions initializing → ready per ADR-0064 D349."
            )

        # Pillar H Week 5 follow-up P2-3 closure: refuse-loud on
        # tick_seconds <= 0 per the per-tier-invariant-field discipline
        # established at Pillar H Week 2 follow-up P2-1 closure on
        # _validate_config (next-tier invariant-bearing fields refuse
        # loud at boundary BEFORE the body executes side effects). The
        # zero case would cause a tight busy-loop; the negative case
        # would raise inside asyncio.sleep with a less operator-readable
        # message. Aligning the boundary discipline preserves the
        # Pillar G Week 4 + Pillar H Week 2-4 + Pillar H Week 5 + Week
        # 5 follow-up convention.
        if tick_seconds <= 0:
            raise ValueError(
                f"DaemonRunner.run requires tick_seconds > 0; "
                f"got {tick_seconds!r}. The per-stage tick loop's "
                f"asyncio.sleep cadence MUST be strictly positive to "
                f"yield cooperatively to the asyncio event loop per "
                f"ADR-0060 D332's asyncio framework decision. Pillar "
                f"H Week 5 follow-up P2-3 closure."
            )

        # Resolve test-only seam defaults.
        if emit_fn is None:
            ledger = Ledger(self.config.ledger_dir)
            emit_fn = ledger.append
        if now_fn is None:
            now_fn = lambda: datetime.now(tz=timezone.utc)  # noqa: E731
        if attach_signal_handlers_fn is None:
            attach_signal_handlers_fn = attach_signal_handlers
        if serve_health_endpoint_fn is None:
            # health.py imports EMITTED_BY + DAEMON_LIFECYCLE_STATES from
            # runner.py at function bodies; module-top import would
            # create circular import at module load time per Pillar H
            # Week 4 follow-up NEW-1 closure's circular-import-avoidance
            # pattern. Keep this import lazy.
            from orchestrator.daemon.health import (  # noqa: PLC0415
                serve_health_endpoint,
            )
            serve_health_endpoint_fn = serve_health_endpoint
        if traced_stage_fn is None:
            traced_stage_fn = _observability.traced_stage
        if semaphore_factory_fn is None:
            # Pillar H Week 6 follow-up P2-1 + P3-11 closure: default to
            # the production :class:`asyncio.Semaphore` backend per
            # ADR-0065 D353. Tests inject an always-locked subclass to
            # exercise the body's Iteration 6b emit path; production
            # callers receive the asyncio primitive per ADR-0060 D332's
            # asyncio framework decision.
            semaphore_factory_fn = asyncio.Semaphore
        if dispatch_fn is None:
            # Pillar H Week 7 — default Iteration 6b dispatch is a
            # closure over ``self`` invoking
            # :func:`_default_dispatch_for_stage` per ADR-0066 D358.
            # The closure adapts the production
            # :func:`_default_dispatch_for_stage(runner, stage)`
            # signature to the dispatch_fn seam contract
            # ``Callable[[str], Awaitable[None]]`` so the test seam
            # (which captures only the stage argument) is symmetric
            # with the production default's invocation site.
            async def _default_dispatch(stage: str) -> None:
                await _default_dispatch_for_stage(self, stage)
            dispatch_fn = _default_dispatch
        if loop is None:
            # Pillar H Week 5 follow-up P2-4 closure: wrap
            # asyncio.get_running_loop() with operator-readable
            # error so operators invoking runner.run() outside an
            # asyncio context get a self-documenting message instead
            # of the stdlib's "no running event loop" cryptic.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError as exc:
                raise RuntimeError(
                    "DaemonRunner.run requires an active asyncio "
                    "event loop. Invoke via asyncio.run(runner.run()) "
                    "per ADR-0064 §Existing-operator seed. Pillar H "
                    "Week 5 follow-up P2-4 closure."
                ) from exc

        # Step 2: Transition initializing → ready via the per-pillar-H
        # frozen-dataclass escape hatch per ADR-0062 D342 + the Pillar H
        # Week 3 follow-up P3-1 closure (ONLY lifecycle_state mutates
        # via object.__setattr__). The Pillar H Week 5 follow-up NEW-5
        # closure adds the regression-barrier
        # TestDaemonRunBody.test_only_lifecycle_state_mutates_during_run
        # mirroring the Week 3 follow-up P3-1 closure's discipline.
        object.__setattr__(self, "lifecycle_state", "ready")

        # Step 3: Emit daemon_started. Compute startup_seconds as the
        # interval between started_at_ts (init_daemon's stamp) and now.
        # The build_daemon_started_payload factory rounds startup_seconds
        # to 3 dp at the factory boundary per ADR-0031 D140; the body's
        # unrounded total_seconds() is consumed by the factory's
        # rounding step (Pillar H Week 5 follow-up NEW-2 REFUTATION:
        # the determinism contract is preserved at the factory boundary).
        started_at = datetime.strptime(
            self.started_at_ts, "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=timezone.utc)
        startup_seconds = (now_fn() - started_at).total_seconds()
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

        # Step 5: Start the health endpoint server. Retain the
        # AppRunner reference for graceful shutdown cleanup at Step 7.
        # Pillar H Week 5 follow-up P3-5 closure renames
        # health_app_runner → health_aiohttp_runner so operators
        # reading the code don't conflate the aiohttp.web.AppRunner
        # ("aiohttp_runner") with the DaemonRunner self reference.
        health_aiohttp_runner = await serve_health_endpoint_fn(
            self.config.health_port,
            runner=self,
        )

        # Step 5.5 (Week 6 extension per ADR-0065 D353-D355; Pillar H
        # Week 6 follow-up P2-2 closure ordering correction):
        # Pre-loop: construct per-funnel-stage asyncio.Semaphore
        # bounded by DaemonConfig.parallelism_limits per ADR-0065
        # D353. The Semaphores are scoped to this run() invocation +
        # per-tenant-isolated by construction per ADR-0060 D335
        # invariant 1 (one daemon process per tenant; one
        # Semaphore-set per daemon process). Construction happens
        # AFTER Step 5 (start health endpoint) + BEFORE Step 6 (tick
        # loop entry); the W6 follow-up P2-2 closure corrected the
        # ADR-0065 D353 narrative which previously said "after Step 2's
        # lifecycle transition" — the FIFTH ADR-vs-actual-impl drift
        # in Pillar H (W2 P3-8 OTel Resource → W3 P2-1 _emitted_by →
        # W4 P2-1 framework-neutrality text → W5 P1-1 traced_stage
        # signature → W6 P2-2 Semaphore construction site ordering).
        #
        # The :data:`_PILLAR_G_PIPELINE_STAGES` import remains LAZY
        # per the Pillar H Week 6 follow-up P3-1 + P3-2 + P3-3 + NEW-2
        # closures' standardized form: ``from orchestrator.funnel
        # import _PILLAR_G_PIPELINE_STAGES`` at all three lazy sites
        # (the prior _validate_config site used ``import funnel as
        # _funnel`` — the W6 follow-up unifies the style). Lazy is
        # required because :mod:`orchestrator.funnel`'s module body
        # does bare-name ``import ledger`` (line 152) requiring
        # :file:`orchestrator/` on ``sys.path`` — present at test time
        # via :file:`tests/conftest.py` but NOT at production-import
        # time from a clean Python process. Lazy defers funnel's
        # module-load to call-time when the daemon's bootstrap
        # wrapper has arranged ``sys.path`` correctly. See the
        # module-top import block comment for full rationale.
        #
        # The :func:`semaphore_factory_fn` test-only seam (default
        # :class:`asyncio.Semaphore`) supports the Pillar H Week 6
        # follow-up P2-1 + P3-11 closures' behavioral-passthrough
        # regression-barrier — tests inject an always-locked
        # Semaphore subclass to exercise Iteration 6b's emit path.
        # The seam follows the Pillar G TEST-ONLY convention + the
        # Pillar H Week 2-5 precedent; production callers omit the
        # kwarg + receive the production :class:`asyncio.Semaphore`
        # backend. The framework-neutrality contract per the W4
        # follow-up P2-1 closure preserves — the asyncio framework
        # choice per ADR-0060 D332 remains the v1 default; operators
        # wanting alternative concurrency models (threading / trio /
        # gevent) MUST fork the function body.
        from orchestrator.funnel import (  # noqa: PLC0415
            _PILLAR_G_PIPELINE_STAGES,
        )
        stage_semaphores: dict[str, asyncio.Semaphore] = {
            stage: semaphore_factory_fn(self.config.parallelism_limits[stage])
            for stage in _PILLAR_G_PIPELINE_STAGES
        }

        # Per-stage tick loop with TWO ORTHOGONAL iterations per
        # ADR-0065 D354:
        # - Iteration 6a (Week 5 preserved): per-observability-stage
        #   span tick over sorted(_PIPELINE_STAGES) — 8 wraps per
        #   tick; preserves the Pillar G framework adoption surface
        #   per ADR-0055 D300 + the Week 5 follow-up P1-1 closure's
        #   (stage, "tick") signature.
        # - Iteration 6b (Week 6 NEW): per-funnel-stage worker pool
        #   tick over sorted(_PILLAR_G_PIPELINE_STAGES) — 7 stages
        #   per tick; Semaphore.locked() check + daemon_stage_saturated
        #   emit on saturation; Week 7+ wires actual per-funnel-stage
        #   dispatch via `async with sem: await dispatch_fn(stage)`.
        #
        # The two iterations are ORTHOGONAL because the two closed-
        # sets are intentionally distinct per Pillar H Week 1 follow-
        # up P3-5 closure (funnel stages = per-pipeline-event stages
        # for operator-observable funnel progression; observability
        # stages = per-span dims for traced_stage). A 1-to-many
        # mapping would require operator-arbitrary disambiguation at
        # the `researched` funnel stage which conceptually spans both
        # `enrichment` + `research` observability stages — rejected
        # per ADR-0065 D354.
        try:
            while self.lifecycle_state == "ready":
                await asyncio.sleep(tick_seconds)
                if self.lifecycle_state != "ready":
                    break
                # Iteration 6a — per-observability-stage span tick.
                for stage in sorted(_observability._PIPELINE_STAGES):
                    with traced_stage_fn(stage, "tick"):
                        pass  # Week 7+ ships actual per-stage dispatch.
                # Iteration 6b — per-funnel-stage worker pool tick.
                for stage in sorted(_PILLAR_G_PIPELINE_STAGES):
                    sem = stage_semaphores[stage]
                    if sem.locked():
                        # Saturation backpressure signal per
                        # ADR-0065 D355. With the Week 7 dispatch
                        # body wired, the Semaphore CAN be locked
                        # when concurrent per-tick dispatches are
                        # in flight (the per-stage parallelism
                        # budget per :attr:`DaemonConfig.parallelism_limits`).
                        # The in_flight_count is computed as
                        # parallelism_limit at saturation (the
                        # Semaphore is locked iff all slots acquired);
                        # Week 8+ may extend with sub-limit
                        # in_flight tracking as a backpressure-
                        # trending metric per ADR-0065 D355's
                        # waiter-case asymmetry note.
                        limit = self.config.parallelism_limits[stage]
                        emit_fn({
                            "type": "daemon_stage_saturated",
                            **build_daemon_stage_saturated_payload(
                                pid=self.pid,
                                stage=stage,
                                parallelism_limit=limit,
                                in_flight_count=limit,
                            ),
                        })
                        continue
                    # Pillar H Week 7 — actual per-funnel-stage
                    # dispatch per ADR-0066 D358. The semaphore
                    # bounds concurrent dispatch to the operator-
                    # deliberate parallelism budget per ADR-0060
                    # D331; the dispatch_fn seam invokes the
                    # per-stage reconcile-passes mapping via
                    # :func:`_default_dispatch_for_stage` (default)
                    # OR a test-injected spy.
                    async with sem:
                        await dispatch_fn(stage)
        finally:
            # Step 7: Graceful shutdown coordination per ADR-0064 D352.
            # AppRunner.cleanup() waits for in-flight HTTP requests to
            # complete before releasing the port (aiohttp's documented
            # graceful shutdown contract). The try/finally ensures
            # cleanup fires on BOTH the clean-shutdown path (lifecycle
            # transitions to "draining" + "stopped" per Pillar H Week 3
            # ADR-0062 D342) AND the ungraceful path (exception inside
            # the tick loop OR asyncio.CancelledError propagating from
            # task.cancel()).
            await health_aiohttp_runner.cleanup()

        # Step 8: Return 0 on clean shutdown.
        return 0

    def shutdown(
        self,
        reason: str,
        *,
        emit_fn: Callable[[dict], Any] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """Trigger graceful shutdown per ADR-0060 D335 invariant 3 +
        ADR-0062 D342.

        **Pillar H Week 3 body.** Transitions lifecycle state through
        ``"draining"`` (emit ``daemon_stopping``) → ``"stopped"`` (emit
        ``daemon_stopped``). Callers include the signal handlers attached
        via :func:`attach_signal_handlers` + operators invoking the
        daemon's CLI shutdown surface (Week 5+ scope) + tests via the
        emit_fn seam.

        The state transition uses :func:`object.__setattr__` per the
        documented Python frozen-dataclass escape hatch — the frozen
        invariant still holds for normal operator/external mutation,
        but the daemon's per-pillar-H lifecycle transitions are the
        internal allow-listed mutation site per ADR-0062 D342.

        Week 3 ships the **structural shape** (state transition + emit
        sequence + reason validation); the actual per-stage drain loop
        (await in-flight tasks within the deadline) lands at Pillar H
        Week 5+'s :meth:`DaemonRunner.run` body per ADR-0060 D332's
        trajectory + ADR-0062 D342 narrative. Week 3 ALWAYS emits
        ``exit_reason="clean"`` because there are no per-stage tasks
        to drain yet; Week 5+ extends with the timeout/crash path
        selection.

        Args:
            reason: one of :data:`SHUTDOWN_REASONS` (``"sigterm"`` |
                ``"sigint"`` | ``"operator_requested"``). Refuses-loud
                via :exc:`ValueError` on values outside the closed-set
                per the per-pillar mirror constants parity discipline +
                I5 + ADR-0001 D2.
            emit_fn: test-only seam — appends a daemon-lifecycle event
                to the ledger. Default lazy-constructs
                :class:`orchestrator.ledger.Ledger` from
                ``self.config.ledger_dir`` + invokes
                :meth:`Ledger.append`. Tests inject spies that record
                the emit payloads + the runner's lifecycle_state at
                emit-time (the cell-level matrix coverage discipline).
            now_fn: test-only seam — returns the current UTC datetime.
                Default :func:`datetime.now` with timezone.utc. Tests
                inject deterministic clocks to verify uptime + drain
                deadline computations are precise.

        Raises:
            :exc:`ValueError`: on ``reason`` outside
                :data:`SHUTDOWN_REASONS`.
        """
        # Pre-flight validation: refuse-loud on invalid reason BEFORE
        # any state transition or side-effect fires (the framework
        # convention per I5 + ADR-0001 D2).
        if reason not in SHUTDOWN_REASONS:
            raise ValueError(
                f"DaemonRunner.shutdown reason not in SHUTDOWN_REASONS "
                f"({sorted(SHUTDOWN_REASONS)!r}): {reason!r}"
            )

        if now_fn is None:
            now_fn = lambda: datetime.now(tz=timezone.utc)  # noqa: E731
        if emit_fn is None:
            # Lazy import + lazy ledger construction. Operators invoking
            # shutdown outside the daemon process (e.g., admin CLI) get
            # the production emit path; tests inject spies via the seam.
            from orchestrator.ledger import Ledger  # noqa: PLC0415
            ledger = Ledger(self.config.ledger_dir)
            emit_fn = ledger.append

        # Pillar H Week 3 follow-up P2-2 closure — parse started_at_ts
        # UPFRONT, BEFORE any state transition, so a malformed format
        # raises ValueError BEFORE the runner transitions to "draining"
        # + emits daemon_stopping. The Week 3 main commit parsed
        # started_at_ts at Step 5 AFTER the state transition + the
        # daemon_stopping emit — a malformed started_at_ts left the
        # runner in "stopped" state with daemon_stopping in the ledger
        # but daemon_stopped NEVER emitted (half-completed state
        # transition violating ADR-0060 D335 invariant 3 graceful-
        # shutdown structural commitment).
        try:
            started_at = datetime.strptime(
                self.started_at_ts, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValueError(
                f"DaemonRunner.shutdown could not parse started_at_ts "
                f"{self.started_at_ts!r} as %Y-%m-%dT%H:%M:%S.%fZ format "
                f"per ADR-0061 D339 + the :func:`_utc_iso_now` contract. "
                f"Refusing-loud BEFORE state transition per ADR-0060 D335 "
                f"invariant 3 graceful-shutdown structural commitment "
                f"(Pillar H Week 3 follow-up P2-2 closure)."
            ) from exc

        # Compute all derived values upfront (drain_deadline / uptime)
        # so the emit-time work is pure dict construction; the state
        # transition + emit sequence is atomic-within-the-method.
        now = now_fn()
        drain_deadline = now + timedelta(
            seconds=self.config.graceful_shutdown_seconds,
        )
        drain_deadline_ts = drain_deadline.strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        uptime_seconds = (now - started_at).total_seconds()
        in_flight_task_count = 0
        in_flight_task_count_at_exit = 0

        # Step 1: transition to "draining" via the documented frozen-
        # dataclass escape hatch per ADR-0062 D342. The lifecycle_state
        # mutation is the per-pillar-H internal allow-listed site;
        # operator/external mutation continues to refuse-loud via the
        # frozen-dataclass FrozenInstanceError.
        #
        # Pillar H Week 3 follow-up P3-1 closure — ONLY ``lifecycle_state``
        # is the allow-listed internal mutation field via
        # :func:`object.__setattr__` per ADR-0062 D342. Mutating other
        # fields (``config`` / ``config_hash`` / ``pid`` / ``started_at_ts``
        # / ``version``) via the same escape hatch is OUT OF SCOPE; a
        # future per-week author extending the shutdown body MUST NOT
        # call ``object.__setattr__(self, <other_field>, ...)``. The
        # regression-barrier at
        # :meth:`tests.test_daemon.TestShutdownBody.test_only_lifecycle_state_mutates_during_shutdown`
        # pins the structural commitment.
        object.__setattr__(self, "lifecycle_state", "draining")

        # Step 2: emit daemon_stopping while in "draining" state.
        emit_fn({
            "type": "daemon_stopping",
            **build_daemon_stopping_payload(
                pid=self.pid,
                reason=reason,
                drain_deadline_ts=drain_deadline_ts,
                in_flight_task_count=in_flight_task_count,
            ),
        })

        # Step 3: skip drain (no in-flight tasks at this trajectory
        # point — Week 5+'s DaemonRunner.run body wires the per-stage
        # worker pool + the drain loop).

        # Step 4: transition to "stopped" (same allow-listed escape
        # hatch + same field as Step 1; see P3-1 comment above).
        object.__setattr__(self, "lifecycle_state", "stopped")

        # Step 5: emit daemon_stopped. Week 3 always emits
        # exit_reason="clean" (no drain timeout possible without
        # in-flight tasks); Week 5+ extends with timeout/crash path
        # selection per ADR-0062 D344.
        emit_fn({
            "type": "daemon_stopped",
            **build_daemon_stopped_payload(
                pid=self.pid,
                exit_reason="clean",
                uptime_seconds=uptime_seconds,
                in_flight_task_count_at_exit=in_flight_task_count_at_exit,
            ),
        })

    def reload_policy(
        self,
        *,
        policy_load_fn: Callable[[Path], list] | None = None,
        emit_fn: Callable[[dict], Any] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        hash_fn: Callable[[Path], str] | None = None,
    ) -> PolicyReloadResult:
        """Re-read the policy YAML per ADR-0060 D335 invariant 4 +
        ADR-0066 D356.

        **Pillar H Week 7 body.** Re-reads the policy directory at
        :attr:`DaemonConfig.policy_dir` (resolved to
        ``vault_dir.parent / "policies"`` at :func:`init_daemon` time if
        unset), computes the new content hash, attempts to parse +
        validate the YAML rules, atomically swaps the in-memory policy
        state on success, emits ``policy_reloaded`` with the prior +
        new content hashes, + returns a :class:`PolicyReloadResult`.

        Per the per-pillar mirror constants parity discipline + the
        existing :data:`POLICY_RELOAD_STATUSES` closed-set per the
        Pillar H Week 1 follow-up P3-3 closure, the body emits ONLY
        the two values ``{"applied", "failed_unchanged"}``:

        * **``"applied"``** — the parse + validation succeeded; the new
          rules are now LIVE in :attr:`DaemonRunner.policy_state.rules`.
          ``prior_content_hash`` carries the hash of the last-applied
          policy (loaded at :func:`init_daemon` time OR by a prior
          successful reload); ``new_content_hash`` carries the hash of
          the just-loaded policy. **Hash-unchanged is still ``"applied"``**
          (operators reloading a byte-identical policy DO see an
          ``applied`` status with ``prior == new``; the reload was a
          successful no-op apply). The
          :data:`POLICY_RELOAD_STATUSES` docstring + ADR-0060 D335
          establish this — a third status ``"unchanged"`` is operator-
          extensible at Pillar I per-tenant trajectory (the closed-set
          extends + the regression-barrier test pins concurrently).
        * **``"failed_unchanged"``** — the parse OR validation FAILED;
          the prior policy state is preserved verbatim (no atomic swap);
          :attr:`PolicyReloadResult.parse_error` carries an operator-
          readable error message (NOT a Python traceback); operators
          see ``failed_unchanged`` in the ``policy_reloaded`` event +
          can correct via the source file then send SIGHUP again.

        **Atomic swap contract.** On parse success, the swap mutates
        :attr:`policy_state.rules` + :attr:`policy_state.content_hash`
        IN PLACE on the held :class:`_PolicyState` instance — the frozen
        :class:`DaemonRunner` invariant protects the field reference
        (:attr:`policy_state` itself cannot be reassigned), NOT the
        held instance's internal mutability. The swap is atomic from
        the per-tick dispatch viewpoint because both fields mutate
        within the synchronous body of :meth:`reload_policy` (no
        ``await`` between the two mutations; the SIGHUP handler runs
        on the asyncio event loop's main thread per the asyncio
        convention so no interleaving with the per-stage tick is
        possible).

        Args:
            policy_load_fn: test-only seam — loads policy rules from a
                directory. Default :func:`_default_policy_load`.
                Operators wanting alternative YAML parsers / schema
                validators inject here. The framework-neutrality
                contract per the W4 follow-up P2-1 closure preserves —
                the seam substitutes a BACKEND (the YAML loader); the
                actual rule-class registry per :data:`policy.RULE_REGISTRY`
                + the canonical YAML format per ADR-0001 are framework
                invariants.
            emit_fn: test-only seam — appends the ``policy_reloaded``
                event to the ledger. Default lazy-constructs
                :class:`orchestrator.ledger.Ledger` from
                ``self.config.ledger_dir`` + invokes
                :meth:`Ledger.append`. Tests inject spies that record
                emit payloads.
            now_fn: test-only seam — returns the current UTC datetime.
                Default :func:`datetime.now` with timezone.utc. Tests
                inject deterministic clocks to verify
                :attr:`PolicyReloadResult.reloaded_at_ts` is precise.
            hash_fn: test-only seam — computes the content hash of a
                policy directory. Default
                :func:`_compute_policy_content_hash`. Tests inject
                deterministic hashes; operators wanting alternative
                content-fingerprint algorithms (e.g., BLAKE3) inject
                here while preserving the 64-hex-char SHA-256 shape
                per the per-pillar mirror constants parity discipline.

        Returns:
            :class:`PolicyReloadResult` with ``status`` in
            :data:`POLICY_RELOAD_STATUSES`, ``source_path`` set to
            :attr:`DaemonConfig.policy_dir` (or its resolved default),
            ``prior_content_hash`` (the hash currently live in
            :attr:`policy_state.content_hash` BEFORE the reload —
            empty string if the daemon was constructed via direct
            :class:`DaemonRunner` construction bypassing
            :func:`init_daemon`), ``new_content_hash`` (the hash of the
            disk state at reload time), ``reloaded_at_ts`` (ISO-8601
            UTC from ``now_fn``), + ``parse_error`` (None on
            ``status="applied"``; populated on ``"failed_unchanged"``).

        Raises:
            (No exceptions raised under normal operation.) The body
            catches parse / validation errors at the
            :func:`policy_load_fn` invocation boundary + surfaces them
            via the ``failed_unchanged`` return path. Errors from the
            hash computation (e.g., :exc:`PermissionError` reading the
            policy directory) DO propagate — those are operator
            environment issues, not policy content issues, + the
            existing daemon error handling (the asyncio loop's
            unhandled-exception path) surfaces them.

        See ADR-0066 D356 for the full design rationale (rejected
        alternatives: signal-driven re-evaluation, file-mtime
        detection, polling) + ADR-0060 D335 invariant 4 for the
        SIGHUP-driven contract + the Pillar H Week 3 follow-up P2-1
        closure's ``_emitted_by="daemon"`` audit-marker discipline (the
        :func:`build_policy_reloaded_payload` factory stamps this at
        the factory boundary).
        """
        # Resolve test-only seam defaults.
        if policy_load_fn is None:
            policy_load_fn = _default_policy_load
        if hash_fn is None:
            hash_fn = _compute_policy_content_hash
        if now_fn is None:
            now_fn = lambda: datetime.now(tz=timezone.utc)  # noqa: E731
        if emit_fn is None:
            # Lazy ledger construction — mirrors the :meth:`shutdown`
            # body's seam-default pattern at runner.py:1382-1388.
            ledger = Ledger(self.config.ledger_dir)
            emit_fn = ledger.append

        # Resolve the effective policy directory. Production daemons
        # invoked via :func:`init_daemon` already have config.policy_dir
        # resolved; tests constructing :class:`DaemonRunner` directly
        # may have config.policy_dir=None — derive the default via the
        # same ``vault_dir.parent / "policies"`` convention used by
        # :func:`init_daemon`'s Step 5.
        if self.config.policy_dir is not None:
            policy_dir = self.config.policy_dir
        else:
            policy_dir = self.config.vault_dir.parent / "policies"

        # Capture the prior content hash BEFORE any disk read (the
        # operator-visible prior state at the moment SIGHUP arrived).
        prior_content_hash = self.policy_state.content_hash

        # Compute the new content hash from the disk state.
        new_content_hash = hash_fn(policy_dir)

        reloaded_at_ts = (
            now_fn().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        )

        # Attempt to load + parse the policy from disk.
        try:
            new_rules = policy_load_fn(policy_dir)
        except Exception as exc:  # noqa: BLE001
            # Parse / validation failure. Preserve the prior policy
            # state (no atomic swap); emit `policy_reloaded` with
            # status=failed_unchanged + parse_error.
            parse_error = f"{type(exc).__name__}: {exc}"
            result = PolicyReloadResult(
                status="failed_unchanged",
                source_path=policy_dir,
                prior_content_hash=prior_content_hash,
                new_content_hash=new_content_hash,
                reloaded_at_ts=reloaded_at_ts,
                parse_error=parse_error,
            )
            emit_fn({
                "type": "policy_reloaded",
                **build_policy_reloaded_payload(
                    pid=self.pid,
                    source_path=str(policy_dir),
                    prior_content_hash=prior_content_hash,
                    new_content_hash=new_content_hash,
                    status="failed_unchanged",
                ),
            })
            return result

        # Parse succeeded. Atomic swap of the in-memory policy state
        # (the frozen-dataclass invariant protects field RE-ASSIGNMENT;
        # mutating the held :class:`_PolicyState` instance in place is
        # the documented pattern per the class's docstring).
        self.policy_state.rules = new_rules
        self.policy_state.content_hash = new_content_hash

        result = PolicyReloadResult(
            status="applied",
            source_path=policy_dir,
            prior_content_hash=prior_content_hash,
            new_content_hash=new_content_hash,
            reloaded_at_ts=reloaded_at_ts,
            parse_error=None,
        )
        emit_fn({
            "type": "policy_reloaded",
            **build_policy_reloaded_payload(
                pid=self.pid,
                source_path=str(policy_dir),
                prior_content_hash=prior_content_hash,
                new_content_hash=new_content_hash,
                status="applied",
            ),
        })
        return result


# ---------------------------------------------------------------------------
# Primitive function signatures — Week 1 shape only
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pillar H Week 2 — init_daemon body helpers + payload factory
# (per ADR-0061 D337 + D339 + D340)
# ---------------------------------------------------------------------------


def _utc_iso_now() -> str:
    """Return the current UTC timestamp in ISO-8601 with Z suffix per
    ADR-0010 D17's ts convention. Pillar H Week 2 ``daemon_started``
    payload + :attr:`DaemonRunner.started_at_ts` consume this."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _compute_config_hash(config: DaemonConfig) -> str:
    """Compute a stable SHA-256 hash of the :class:`DaemonConfig` per
    ADR-0061 D337. Operators query the hash (surfaced in the
    ``daemon_started`` event payload + :attr:`HealthStatus.config_hash`)
    to detect config drift across restarts.

    The hash is computed over the canonical JSON encoding of the
    frozen dataclass fields (paths serialized as strings; dict keys
    sorted; floats rejected per the int-typed fields):

    * ``vault_dir`` / ``ledger_dir`` as string paths.
    * ``health_port`` / ``graceful_shutdown_seconds`` /
      ``health_probe_rate_limit_seconds`` as integers.
    * ``policy_reload_signal`` as string or null.
    * ``parallelism_limits`` as a dict with sorted keys.
    * ``policy_dir`` / ``people_dir`` / ``suppressions_dir`` as
      string paths or null (Pillar H Week 7 extension per ADR-0066
      D356 + D358 — operators querying ``config_hash`` see drift
      across the extended surface).

    The hash is 64 hexadecimal chars (SHA-256 digest length); the
    first 16 chars are operator-readable for casual identity checks.

    **Pillar H Week 2 follow-up P3-3 closure** — cross-OS path-separator
    note: :func:`str` on a :class:`Path` differs across POSIX vs Windows
    (forward vs back slashes). Pillar H targets POSIX-only at v1 per
    `docs/PILLAR-PLAN.md` §2 Pillar H. Pillar I+ multi-platform operators
    consuming ``config_hash`` as a cross-machine identity signal should
    normalize via :meth:`Path.as_posix` before hashing (TBD Pillar I
    trajectory). The regression-barrier test at
    :meth:`tests.test_daemon.TestComputeConfigHash.test_config_hash_byte_stable_for_known_config`
    pins the byte-identical-across-invocations posture for a known config.
    """
    payload = {
        "vault_dir": str(config.vault_dir),
        "ledger_dir": str(config.ledger_dir),
        "health_port": config.health_port,
        "graceful_shutdown_seconds": config.graceful_shutdown_seconds,
        "policy_reload_signal": config.policy_reload_signal,
        "health_probe_rate_limit_seconds": config.health_probe_rate_limit_seconds,
        "parallelism_limits": dict(sorted(config.parallelism_limits.items())),
        # Pillar H Week 7 — optional path fields per ADR-0066 D356 +
        # D358. ``None`` renders as JSON null; resolved Paths stringify
        # per the existing convention.
        "policy_dir": str(config.policy_dir) if config.policy_dir is not None else None,
        "people_dir": str(config.people_dir) if config.people_dir is not None else None,
        "suppressions_dir": str(config.suppressions_dir) if config.suppressions_dir is not None else None,
        # Pillar H Week 10-11 per ADR-0068 D366 — operator-deliberate
        # pre-flight reconcile pass list. ``None`` renders as JSON null;
        # the resulting string (e.g., ``"A"`` or ``"A,B,D,E,F,H,I,J"``)
        # is serialized verbatim. Operators querying ``config_hash``
        # see drift across this surface.
        "reconcile_passes_at_startup": config.reconcile_passes_at_startup,
        # Pillar I Week 2 per ADR-0070 D371 — optional per-tenant
        # identifier. ``None`` renders as JSON null (single-tenant
        # operators); a non-empty string is serialized verbatim so
        # per-tenant daemons have distinct config identities.
        "tenant_id": config.tenant_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_config(config: DaemonConfig) -> None:
    """Validate :class:`DaemonConfig` per ADR-0061 D337 + the Pillar H
    Week 1 follow-up P3-2 + P3-6 closures. Refuse-loud on invalid via
    :exc:`ValueError` (the framework convention per I5 + ADR-0001 D2)
    BEFORE any side-effecting startup step runs.

    Validation rules (each rule corresponds to a row in the Pillar H
    Week 1 follow-up :class:`tests.test_daemon.TestInitDaemonValidation`
    test class which un-skips at this Week 2 commit):

    * ``vault_dir`` MUST exist on-disk (refuses-loud at startup rather
      than crashing later in the per-stage worker pool's vault read).
    * ``ledger_dir`` MUST exist on-disk (same rationale).
    * ``health_port`` MUST be in ``1..65535`` per the TCP port range
      convention.
    * ``parallelism_limits`` keys MUST equal
      :data:`funnel._PILLAR_G_PIPELINE_STAGES` per the per-pillar
      mirror constants parity discipline + ADR-0061 D337 startup
      ordering invariant.
    * ``policy_reload_signal`` MUST be in
      :data:`DAEMON_POLICY_RELOAD_SIGNALS` OR equal ``None`` (the
      operator-deliberate opt-out).

    **Pillar H Week 2 follow-up P2-1 closure** — three additional
    refuse-loud rules pin the NEXT-TIER invariant-bearing fields the
    Week 1 follow-up reviewer did not name (the per-week-reviewer-as-
    coverage-extender pattern; each week's reviewer extends the
    validation surface to the next tier):

    * ``graceful_shutdown_seconds`` MUST be ``> 0`` — Week 3+ shutdown
      body would interpret ``<= 0`` as an already-past drain deadline,
      cancelling in-flight tasks immediately (the structural commitment
      per ADR-0060 D335 invariant 3 would be broken silently).
    * ``health_probe_rate_limit_seconds`` MUST be ``>= 0`` — Week 4
      health endpoint body interprets negative as either always-emit OR
      never-emit (inverted arithmetic); R038 mitigation is structurally
      broken.
    * each ``parallelism_limits[stage]`` MUST be ``>= 1`` — Week 5+
      per-stage worker pool body wires :class:`asyncio.Semaphore` per
      stage; ``Semaphore(0)`` silently deadlocks every per-stage tick;
      ``Semaphore(-N)`` raises :exc:`ValueError` mid-startup AFTER
      migrations + policy + OTel set-once burnt.
    """
    # vault_dir + ledger_dir existence.
    if not config.vault_dir.exists():
        raise ValueError(
            f"DaemonConfig.vault_dir does not exist: {config.vault_dir!s}"
        )
    if not config.ledger_dir.exists():
        raise ValueError(
            f"DaemonConfig.ledger_dir does not exist: {config.ledger_dir!s}"
        )

    # health_port range.
    if not (1 <= config.health_port <= 65535):
        raise ValueError(
            f"DaemonConfig.health_port out of range 1..65535: "
            f"{config.health_port!r}"
        )

    # parallelism_limits keys mirror funnel._PILLAR_G_PIPELINE_STAGES.
    # Pillar H Week 6 follow-up P3-3 closure: the prior lazy ``import
    # funnel as _funnel`` here used the bare-module syntax while the
    # other two lazy sites used ``from orchestrator.funnel import
    # _PILLAR_G_PIPELINE_STAGES`` — style-inconsistent. All three sites
    # now use the same ``from orchestrator.funnel import`` form. Lazy
    # is required because :mod:`orchestrator.funnel`'s module body does
    # bare-name ``import ledger`` (line 152) requiring ``orchestrator/``
    # on ``sys.path`` (test-only sys.path shim via conftest.py); the
    # module-top import block at this file's top documents the full
    # production-fragility rationale.
    from orchestrator.funnel import (  # noqa: PLC0415
        _PILLAR_G_PIPELINE_STAGES,
    )
    expected_stages = set(_PILLAR_G_PIPELINE_STAGES)
    actual_stages = set(config.parallelism_limits.keys())
    if actual_stages != expected_stages:
        extra = actual_stages - expected_stages
        missing = expected_stages - actual_stages
        msg = (
            f"DaemonConfig.parallelism_limits keys do not match "
            f"funnel._PILLAR_G_PIPELINE_STAGES"
        )
        if extra:
            msg += f"; extra keys: {sorted(extra)!r}"
        if missing:
            msg += f"; missing keys: {sorted(missing)!r}"
        raise ValueError(msg)

    # policy_reload_signal closed-set per Pillar H Week 1 follow-up P3-2.
    if (
        config.policy_reload_signal is not None
        and config.policy_reload_signal not in DAEMON_POLICY_RELOAD_SIGNALS
    ):
        raise ValueError(
            f"DaemonConfig.policy_reload_signal not in "
            f"DAEMON_POLICY_RELOAD_SIGNALS ({sorted(DAEMON_POLICY_RELOAD_SIGNALS)!r}) "
            f"and not None: {config.policy_reload_signal!r}"
        )

    # Pillar H Week 2 follow-up P2-1 closure — next-tier invariant-bearing
    # fields the Week 1 follow-up reviewer did not name. The refuse-loud
    # rules below pin the structural commitments per ADR-0060 D335
    # invariants 3 (graceful-shutdown deadline) + R038 (health probe rate-
    # limit) + the Pillar H Week 5+ per-stage worker pool's asyncio.Semaphore
    # construction contract.

    # graceful_shutdown_seconds > 0 (drain deadline cannot be already-past).
    if config.graceful_shutdown_seconds <= 0:
        raise ValueError(
            f"DaemonConfig.graceful_shutdown_seconds must be > 0: "
            f"{config.graceful_shutdown_seconds!r} (the drain deadline is "
            f"the structural commitment per ADR-0060 D335 invariant 3; "
            f"<= 0 cancels in-flight tasks immediately on SIGTERM)"
        )

    # health_probe_rate_limit_seconds >= 0 (0 is operator-deliberate
    # "every probe emits"; negative inverts the rate-limit arithmetic).
    if config.health_probe_rate_limit_seconds < 0:
        raise ValueError(
            f"DaemonConfig.health_probe_rate_limit_seconds must be >= 0: "
            f"{config.health_probe_rate_limit_seconds!r} (R038 mitigation "
            f"per ADR-0060 D334 binds at >= 0; 0 means every probe emits; "
            f"negative inverts the rate-limit arithmetic)"
        )

    # parallelism_limits values >= 1 (asyncio.Semaphore(0) deadlocks
    # every per-stage tick; asyncio.Semaphore(<0) raises ValueError).
    for stage, limit in config.parallelism_limits.items():
        if limit < 1:
            raise ValueError(
                f"DaemonConfig.parallelism_limits[{stage!r}] must be >= 1: "
                f"{limit!r} (per-stage worker pool requires >= 1 worker; "
                f"asyncio.Semaphore(0) deadlocks every per-stage tick; "
                f"asyncio.Semaphore(<0) raises ValueError mid-startup)"
            )

    # Pillar H Week 10-11 per ADR-0068 D366 — reconcile_passes_at_startup
    # MUST be a non-empty string of comma-separated pass names if set
    # (None is the operator-deliberate "no pre-flight reconcile" default;
    # empty string would invoke reconcile.reconcile(passes="") which
    # operator-confuses as "all passes" vs "no passes"; explicit None
    # surfaces the operator's intent).
    if config.reconcile_passes_at_startup is not None:
        if not isinstance(config.reconcile_passes_at_startup, str):
            raise ValueError(
                f"DaemonConfig.reconcile_passes_at_startup must be str | "
                f"None; got "
                f"{type(config.reconcile_passes_at_startup).__name__!r} "
                f"(value: {config.reconcile_passes_at_startup!r}). Per "
                f"ADR-0068 D366."
            )
        if not config.reconcile_passes_at_startup.strip():
            raise ValueError(
                f"DaemonConfig.reconcile_passes_at_startup must be "
                f"non-empty string (e.g., 'A' for Gmail intent recovery "
                f"only, 'A,B,D,E,F,H,I,J' for the full intent-recovery "
                f"pass set per ADR-0014/0017/0018/0027); got "
                f"{config.reconcile_passes_at_startup!r}. Set to None to "
                f"disable pre-flight reconcile (the test substrate + dev "
                f"path default). Per ADR-0068 D366."
            )


def _default_policy_load(policy_dir: Path) -> list:
    """Default policy load fn for :func:`init_daemon` per ADR-0061 D337
    step 5. Scans ``policy_dir`` for ``*.yml`` files + calls
    :func:`orchestrator.policy.load_rules_from_yaml` on each in sorted
    order (deterministic per ADR-0031 D140). Returns the concatenated
    list of rules.

    Missing ``policy_dir`` returns an empty list (operator-deliberate
    posture — operators bootstrapping a fresh deployment without policy
    YAML get a daemon that starts; the per-send gate refuses-loud per
    Pillar A convention if no rules are wired).
    """
    if not policy_dir.exists():
        return []
    # Lazy import to keep daemon import-graph minimal.
    from orchestrator import policy as _policy  # noqa: PLC0415
    rules = []
    for yml_path in sorted(policy_dir.glob("*.yml")):
        rules.extend(_policy.load_rules_from_yaml(yml_path))
    return rules


def _compute_policy_content_hash(policy_dir: Path) -> str:
    """Compute a stable SHA-256 hash of the policy directory contents
    per Pillar H Week 7 + ADR-0066 D356.

    Scans ``policy_dir`` for ``*.yml`` files in sorted order
    (deterministic per ADR-0031 D140), reads each file's raw bytes,
    concatenates with a NUL separator (so two files don't collide via
    byte-boundary ambiguity), + returns the SHA-256 hex digest.

    The hash is operator-meaningful as an identity signal for "what
    policy is currently live": two daemons running the same set of
    policy YAML files (byte-identical) produce the same hash; an
    operator-edited rule produces a different hash; SIGHUP-driven
    :meth:`DaemonRunner.reload_policy` surfaces the prior + new hashes
    in the ``policy_reloaded`` event per ADR-0066 D357.

    A missing ``policy_dir`` returns the SHA-256 of empty input
    (``e3b0c44...b855`` — the well-known SHA-256 of the empty byte
    string) — operators bootstrapping a fresh deployment without policy
    YAML get a deterministic + well-defined hash rather than a special
    sentinel value. This is symmetric with :func:`_default_policy_load`
    returning an empty list for the missing-policy_dir case.

    **Why not hash each file separately + concatenate hex digests?**
    The two-step approach is theoretically isomorphic (per the
    Merkle-Damgård construction's pre-image resistance property) but
    operator-confusing because the hex output is twice as long. The
    flat concatenation of canonical-bytes is operator-readable + the
    NUL separator + sorted-filename ordering preserves determinism
    across filesystems / OS path-separator variations.

    **Why not include filenames in the hash?** Operators renaming
    files (e.g., ``cooldown.yml`` → ``01-cooldown.yml`` to control
    load order via filesystem sort) would see the hash change even
    though the rule contents are byte-identical. The filename is
    operationally a sort-key, not a rule-identity field — including
    it would surface false-positive ``policy_reloaded`` events.

    Pillar I per-tenant fan-out per ADR-0060 D335 invariant 1 extends
    naturally — each tenant container's policy_dir produces an
    independent hash; per-tenant ``policy_reloaded`` events carry the
    per-tenant hash via the existing :func:`build_policy_reloaded_payload`
    factory's ``source_path`` field (the tenant-scoped path identifies
    the tenant).
    """
    if not policy_dir.exists():
        return hashlib.sha256(b"").hexdigest()
    h = hashlib.sha256()
    for yml_path in sorted(policy_dir.glob("*.yml")):
        h.update(yml_path.read_bytes())
        h.update(b"\x00")  # NUL separator per the docstring rationale.
    return h.hexdigest()


def _materialize_indexes(led: Ledger) -> "tuple[EventClassIndex, PersonEventIndex]":
    """Pillar H Week 8 — single-walk dual-index materialization per
    ADR-0067 D360 + ADR-0060 D336.

    Walks the ledger ONCE; populates both :class:`EventClassIndex` +
    :class:`PersonEventIndex` for the daemon process. The single-walk
    discipline mirrors the Pillar G Week 2 :func:`collect_event_class_snapshots`
    body's single-walk pattern per ADR-0051 D278 — operators
    auditing the daemon's startup cost see ONE ledger walk, not two.

    **Uncatalogued events skipped at index-population time** —
    events whose ``type`` is NOT in the "known classes" set
    (:data:`observability.EVENT_CLASS_CATALOG` ∪
    :data:`observability.OBSERVABILITY_NEW_EVENT_CLASSES`) are
    silently SKIPPED from :class:`EventClassIndex` (the
    :func:`observability.collect_event_class_snapshots` primitive's
    uncatalogued diagnostic posture per ADR-0050 D272 + ADR-0051
    D279 fires at primitive-call time, NOT at index-population
    time; pre-allocating a per-class bucket for known classes at
    index-population time would be redundant work without value at
    v1 scale ~5K events or v2 scale ~100K events). The catalog
    membership check ``ev_type in known_classes`` is the closed-set
    discipline per the per-pillar mirror constants parity.

    **Pillar H Week 8 follow-up P2-1 closure** — the W8 main commit
    used ``catalog = _observability.EVENT_CLASS_CATALOG`` only,
    diverging from the Pillar G :func:`collect_event_class_snapshots`
    consumer surface's ``expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES``
    precedent (the SEVENTH ADR-vs-actual-impl drift in Pillar H caught
    by the per-week-reviewer's cross-pillar back-audit discipline).
    The W8 follow-up extends the catalog scope to match Pillar G's
    precedent — operators now see ``slo_violation_detected`` (Pillar G
    Week 7-8 emit per ADR-0056) + ``observability_class_uncatalogued``
    (Pillar G Week 2 emit per ADR-0051 D279) indexed by the daemon at
    startup + queryable via :meth:`EventClassIndex.events_for_class`.

    **Lazy-allocation per the v1/v2 scale rationale** — the body uses
    ``setdefault(ev_type, []).append(ev_dict)`` rather than pre-
    allocating an empty list for every known class. The lazy form
    means only classes WITH events have buckets in ``_data``; operators
    querying for a class with zero in-window events get an empty list
    via the ``self._data.get(event_class, [])`` default. The trade-off
    favored lazy at v1 (~5K events with ~25 catalog classes — most
    classes have non-zero counts) + v2 (~100K events with ~25 catalog
    classes — same). Pre-allocation would force ~25 empty dict entries
    per startup without operator value.

    **Person-less events skipped from PersonEventIndex** — events
    with NULL ``person_id`` (ad-hoc validation events per ADR-0045
    D231) are skipped from :class:`PersonEventIndex`; they ARE
    still indexed in :class:`EventClassIndex` by their type. This
    preserves the per-Person primitive's existing "person_id=None
    bucket" semantics per the Pillar G Week 10-11 per-Person
    observability surface adapter pattern.

    **Chronological preservation** —
    :meth:`Ledger.all_events` sorts by ``ts`` per
    :meth:`Ledger._load_events`; both indexes' per-key lists are
    append-only chronologically.

    Args:
        led: the ledger to walk.

    Returns:
        Two-tuple ``(event_class_idx, person_idx)`` populated from
        the single walk.
    """
    event_class_idx = EventClassIndex()
    person_idx = PersonEventIndex()
    # Pillar H Week 8 follow-up P2-1 closure — known_classes is the
    # union of EVENT_CLASS_CATALOG + OBSERVABILITY_NEW_EVENT_CLASSES
    # mirroring the Pillar G :func:`collect_event_class_snapshots`
    # consumer surface precedent at observability.py:910. The W8 main
    # commit's ``catalog = EVENT_CLASS_CATALOG`` only was the SEVENTH
    # ADR-vs-actual-impl drift in Pillar H; the follow-up aligns the
    # scope per the per-pillar mirror constants parity discipline.
    known_classes = (
        _observability.EVENT_CLASS_CATALOG
        | _observability.OBSERVABILITY_NEW_EVENT_CLASSES
    )
    for ev in led.all_events():
        ev_dict = ev.to_dict()
        ev_type = ev.type
        if ev_type in known_classes:
            event_class_idx._data.setdefault(ev_type, []).append(ev_dict)
        pid = ev.person_id
        if pid is not None:
            person_idx._data.setdefault(pid, []).append(ev_dict)
    # Pillar H Week 9 per ADR-0067 D362 — stamp the materialization
    # timestamp on both indexes for the operator-visible freshness
    # gauge per ADR-0067 D363. The same field is advanced by the
    # per-append invalidation observer on each subsequent
    # :meth:`Ledger.append`; at v1 with materialization happening
    # ONCE at daemon startup + invalidation happening on every
    # append, the timestamp reflects "time since last index update"
    # — an operator SLO signal for invalidation stalls.
    now_ts = time.time()
    event_class_idx._last_updated_at_ts = now_ts
    person_idx._last_updated_at_ts = now_ts
    return event_class_idx, person_idx


def _invalidate_indexes_on_append(
    event_class_index: "EventClassIndex",
    person_event_index: "PersonEventIndex",
    ev_dict: dict,
    known_classes: frozenset[str],
    now_ts_fn: Callable[[], float] = time.time,
) -> None:
    """Pillar H Week 9 per ADR-0067 D362 — in-place index invalidation
    for ONE appended event per ADR-0060 D336.

    Mutates ``event_class_index._data`` + ``person_event_index._data``
    in-place + advances both indexes' ``_last_updated_at_ts``. The
    body mirrors :func:`_materialize_indexes`'s per-event branch shape
    so the invalidation post-condition equals
    "re-materialize from a ledger walk that ends at this event" — the
    byte-identical determinism contract per ADR-0031 D140 holds via
    this structural equivalence (the test-class
    ``TestIndexInvalidationOnLedgerAppend`` pins this invariant
    by asserting ``materialized_indexes == observed-state-after-N-appends``
    for cross-pillar event-mix scenarios).

    Args:
        event_class_index: the daemon's per-event-class index holder
            (mutated in-place per the Pillar H Week 7 :class:`_PolicyState`
            mutable-holder precedent per ADR-0066 D356).
        person_event_index: the daemon's per-Person index holder.
        ev_dict: the serialized event dict (from :meth:`Ledger.append`'s
            post-fsync observer fire). Carries the same fields as the
            ledger event (``type`` + ``ts`` + ``v`` + ``person_id``
            optional + per-event-class fields).
        known_classes: the closed-set of event_class values to index
            in the per-event-class index. The canonical v1 scope per
            the Pillar H Week 8 follow-up P2-1 closure is
            :data:`observability.EVENT_CLASS_CATALOG` ∪
            :data:`observability.OBSERVABILITY_NEW_EVENT_CLASSES`.
            Events whose type is OUTSIDE this scope are silently
            skipped from :class:`EventClassIndex` (the
            ``observability_class_uncatalogued`` diagnostic posture
            per ADR-0050 D272 + ADR-0051 D279 fires at primitive-call
            time NOT at invalidation time — same posture as
            :func:`_materialize_indexes` per the W8 follow-up P2-1
            closure).
        now_ts_fn: test-only seam — returns the current Unix-epoch
            timestamp (float seconds). Default :func:`time.time`;
            tests inject a deterministic-clock fake for byte-identical
            reproducibility per ADR-0031 D140.

    **Person-less events skipped from PersonEventIndex** per ADR-0045
    D231 — events with NULL ``person_id`` (ad-hoc validation events)
    are indexed in :class:`EventClassIndex` by type but NOT in
    :class:`PersonEventIndex`. Mirrors :func:`_materialize_indexes`.

    **Cross-process consistency note** — this observer fires for
    appends made on the SAME :class:`Ledger` instance (per-daemon-
    process). Other-process appends (operator running
    ``python orchestrator/funnel.py`` OR the ``/send-outreach`` skill
    OR direct CLI invocations) are NOT visible to the daemon-process
    index until the next daemon-process restart re-walks the ledger
    via :func:`_materialize_indexes`. Pillar I per-tenant fan-out per
    ADR-0060 D335 invariant 1 runs one daemon process per tenant; the
    cross-process gap is a v1 single-tenant + concurrent-CLI concern
    documented at ADR-0067 W9 extension addendum.

    **Pillar H Week 9 follow-up P3-5 closure — partial-mutation
    invariant under exception.** The body's four sub-steps (event_class_index
    mutation → person_event_index mutation → now_ts_fn call →
    timestamp assignment to both indexes) are NOT atomic; if
    ``now_ts_fn()`` raises (production default :func:`time.time` does
    NOT raise in practice; test-only deterministic-clock fakes MAY
    raise), the per-index ``_data`` mutations have already occurred
    + propagate to operators querying the index; the
    ``_last_updated_at_ts`` fields stay at their PRIOR values. The
    failure-mode posture is "data updated, timestamps stale" —
    operators querying the freshness gauge see staleness even though
    the data IS current. The W9 follow-up documents this posture for
    operator-readability; the production-default ``now_ts_fn=time.time``
    does NOT raise so the partial-mutation window is test-only at v1.
    """
    ev_type = ev_dict.get("type")
    if isinstance(ev_type, str) and ev_type in known_classes:
        event_class_index._data.setdefault(ev_type, []).append(ev_dict)
    pid = ev_dict.get("person_id")
    if pid is not None and isinstance(pid, str):
        person_event_index._data.setdefault(pid, []).append(ev_dict)
    now_ts = now_ts_fn()
    event_class_index._last_updated_at_ts = now_ts
    person_event_index._last_updated_at_ts = now_ts


def _install_index_invalidation_observer(
    led: "Ledger",
    event_class_index: "EventClassIndex",
    person_event_index: "PersonEventIndex",
    now_ts_fn: Callable[[], float] = time.time,
) -> None:
    """Pillar H Week 9 per ADR-0067 D362 — register the per-event-class
    index invalidation observer on the daemon's Ledger instance per
    ADR-0060 D336.

    Called once at :func:`init_daemon` Step 8.5 (NEW between the W8
    Step 8 materialization + Step 9 DaemonRunner
    construction). The registered closure captures
    ``known_classes`` + ``event_class_index`` + ``person_event_index``
    + ``now_ts_fn`` + delegates to
    :func:`_invalidate_indexes_on_append` on each subsequent
    :meth:`Ledger.append`.

    The ``known_classes`` set is computed ONCE at registration time
    (the union expression
    ``EVENT_CLASS_CATALOG | OBSERVABILITY_NEW_EVENT_CLASSES`` is
    evaluated at the function call site, producing a NEW frozenset
    that the inner ``_observer`` closure captures by reference; the
    captured set is itself immutable so subsequent reads see a
    consistent view). The operands ``EVENT_CLASS_CATALOG`` +
    ``OBSERVABILITY_NEW_EVENT_CLASSES`` are module-level frozenset
    constants that don't mutate at runtime per the Pillar G + Pillar
    H closed-set discipline. Future cross-pillar extensions adding
    new catalog classes would require a daemon process restart to
    re-register the observer with the extended scope — operator-
    acceptable at v1 because catalog extensions ship via code change
    + commit, NOT via runtime injection. **Pillar H Week 9 follow-up
    P3-6 closure** — the W9 main commit's docstring phrased this as
    "frozenset is immutable; the OBSERVABILITY_NEW_EVENT_CLASSES +
    EVENT_CLASS_CATALOG are module-level constants" which was
    technically correct but operator-confusing because the captured
    set is the UNION (computed at call time) NOT either operand
    directly; the W9 follow-up clarifies the rationale.

    **Atomicity invariant** per ADR-0060 D335 invariant 2 + Phase 5.5
    + ADR-0031 D140 — the observer fires AFTER
    :meth:`Ledger.append`'s fsync + symlink + mtime invalidation
    (per :meth:`Ledger.append` Week 9 extension); the ledger is
    durable BEFORE the index updates. A daemon crash BETWEEN the
    fsync + the observer fire leaves the ledger consistent +
    re-materializable from the ledger per I3 at next daemon startup;
    no operator-visible inconsistency.

    Args:
        led: the daemon's :class:`Ledger` instance (lifted to
            :attr:`DaemonRunner.ledger` per the W9 W8 → W9 lift).
        event_class_index: the daemon's per-event-class index holder.
        person_event_index: the daemon's per-Person index holder.
        now_ts_fn: test-only seam threaded through to the closure
            (returns Unix-epoch float seconds; default
            :func:`time.time`).
    """
    known_classes = (
        _observability.EVENT_CLASS_CATALOG
        | _observability.OBSERVABILITY_NEW_EVENT_CLASSES
    )

    def _observer(ev_dict: dict) -> None:
        _invalidate_indexes_on_append(
            event_class_index,
            person_event_index,
            ev_dict,
            known_classes,
            now_ts_fn=now_ts_fn,
        )

    led.append_observer(_observer)


def _recover_from_prior_crash(
    *,
    led: "Ledger",
    current_pid: int,
    now_fn: Callable[[], datetime] | None = None,
    emit_fn: Callable[[dict], dict] | None = None,
) -> int:
    """Pillar H Week 10-11 per ADR-0068 D364 — synthesize ``daemon_stopped``
    events for crashed prior daemons per ADR-0060 D335 invariant 2
    (atomicity-preservation-across-process-boundary).

    A daemon process is detected as crashed when the ledger has a
    ``daemon_started(pid=P)`` event without a matching subsequent
    ``daemon_stopped(pid=P)`` event. The synthesis appends a
    ``daemon_stopped`` event for each such unmatched prior daemon with:

    * ``exit_reason="crash"`` per :data:`DAEMON_EXIT_REASONS` (W3 commit
      per ADR-0062 D344 pre-reserved this value for the W10-11
      trajectory).
    * ``pid`` = prior daemon's PID (from the ``daemon_started`` payload).
    * ``uptime_seconds`` = ``last_observed_ts_for_pid - started_at_ts``;
      surfaces ``0.0`` if no later events exist for the prior PID.
    * ``in_flight_task_count_at_exit=0`` (cannot be reconstructed from
      ledger walk; the operator-visible v1 placeholder; Pillar I
      per-tenant audit-tooling MAY extend with reconciliation against
      the per-tenant work queue).
    * ``_recovered_by="reconcile"`` audit marker per ADR-0010 D17 +
      R032 synthetic-event exclusion per ADR-0056 D311 — the Pillar G
      SLO aggregation naturally filters the synthesized events out.
    * ``_recovered_for_pid`` field naming the prior PID being
      recovered (the same value as ``pid`` but semantically explicit
      for operator cross-reference).

    **Where the synthesis fires** — :func:`init_daemon` Step 4.5 (NEW
    between W2 Step 4 migration apply + W2 Step 5 policy load).
    Symmetric with W9 Step 8.5 (index invalidation observer install) +
    W9 Step 9.5 (gauge registration) per the per-pillar-H half-step
    convention.

    **Skips the current daemon's PID** — the current daemon has NOT
    emitted its own ``daemon_started`` event yet at Step 4.5 (that
    emit lands at :meth:`DaemonRunner.run` Step 3); the synthesis
    correctly excludes ``current_pid`` from the candidate set, but the
    exclusion is defensive (no prior ``daemon_started`` should carry
    the current daemon's PID at Step 4.5 unless the operator restarted
    a daemon with PID-recycling — POSIX PID-reuse on long-running
    systems IS possible per :func:`os.fork` semantics).

    **Atomicity contract per ADR-0060 D335 invariant 2** — each synthesis
    fires :meth:`Ledger.append` per the existing emit-shape factory +
    the standard audit-marker discipline. The W9 post-append observer
    seam per ADR-0067 D362 fires for each synthesis (the per-event-class
    index updates naturally; the freshness gauge advances). The
    synthesis is operator-deliberately durable BEFORE the daemon
    transitions to ``"ready"``.

    **Failure-mode coverage** (see ADR-0068 D364's failure-mode
    taxonomy):

    * Case (1) — ungraceful exit BEFORE first fsync — N/A by
      construction (no ledger event exists for the daemon).
    * Case (2) — ungraceful exit AFTER ``daemon_started`` BUT BEFORE
      ``daemon_stopping`` — synthesized as ``daemon_stopped(crash)``.
    * Case (3) — ungraceful exit AFTER ``daemon_stopping`` BUT BEFORE
      ``daemon_stopped`` — synthesized as ``daemon_stopped(crash)``
      (the prior ``daemon_stopping`` preserves operator-visible
      context — INTENT was clean shutdown, actual OUTCOME was crash).
    * Case (4) — ungraceful exit DURING ``reload_policy`` — handled by
      the W7 atomicity contract per ADR-0066 D356; the policy YAML on
      disk is the source of truth + re-loaded at Step 5.
    * Case (5) — ungraceful exit BETWEEN ``send_intent`` + ``send_confirmed``
      — handled by Pass A per ADR-0014 D33 + ADR-0015's existing
      recovery surface; W10-11 D366 wires the operator-deliberate
      pre-flight invocation as an opt-in.

    **Privacy invariant per I8 + ADR-0050 D276(b)** — the synthesized
    event payload contains pid + exit_reason + uptime_seconds +
    in_flight_task_count_at_exit + audit markers. NO ``person_id`` /
    body content / source_list.

    **Byte-identical determinism contract per ADR-0031 D140** — the
    synthesis is deterministic given a fixed ledger state + a fixed
    ``now_fn``; the synthesis-time ``ts`` is the runtime stamp.

    Args:
        led: the daemon's :class:`Ledger` instance (lazy-constructed
            at Step 4.5 if not already constructed for the index walk
            at Step 8). The walk is O(N) at startup; v2 scale ~100K
            events surfaces as ~10s startup latency (operator-acceptable
            for the recovery structural value).
        current_pid: the current daemon's PID (excluded from the
            synthesis candidate set per the defensive POSIX-PID-reuse
            exclusion).
        now_fn: test-only seam — returns current datetime for the
            stamp on the synthesized event. Default
            ``lambda: datetime.now(tz=timezone.utc)``.
        emit_fn: test-only seam — emit function for the synthesized
            event. Default ``led.append``.

    Returns:
        Count of recovered crashes (number of ``daemon_stopped`` events
        synthesized). Zero means no prior crashes detected (the v1
        clean-restart case).
    """
    if now_fn is None:
        now_fn = lambda: datetime.now(tz=timezone.utc)  # noqa: E731
    if emit_fn is None:
        emit_fn = led.append

    # Walk the ledger ONCE; build the per-PID started + stopped
    # indices + the per-PID last-observed ts. The walk is O(N) at
    # startup per ADR-0060 D335 invariant 2's recovery contract;
    # v1 scale (~5K events) is sub-second; v2 scale (~100K events)
    # is ~10s — operator-acceptable for the recovery structural value.
    started_by_pid: dict[int, dict] = {}
    stopped_pids: set[int] = set()
    last_ts_by_pid: dict[int, str] = {}

    for ev in led.all_events():
        ev_dict = ev.to_dict()
        ev_type = ev_dict.get("type")
        ev_pid = ev_dict.get("pid")
        ev_ts = ev_dict.get("ts")
        if ev_type == "daemon_started":
            if (
                isinstance(ev_pid, int)
                and ev_pid > 0
                and ev_pid != current_pid
            ):
                started_by_pid[ev_pid] = ev_dict
        elif ev_type == "daemon_stopped":
            if isinstance(ev_pid, int) and ev_pid > 0:
                stopped_pids.add(ev_pid)
        # Track latest-observed ts per PID across ANY daemon-lifecycle
        # event class so the synthesized uptime_seconds reflects the
        # last-known-live point of the prior daemon (operators see
        # "the prior daemon was last alive at <ts>"). Only daemon-
        # lifecycle events carry ``pid`` per ADR-0060 D331's
        # privacy-invariant scope; non-daemon events don't surface
        # here.
        if (
            isinstance(ev_pid, int)
            and ev_pid > 0
            and ev_pid != current_pid
            and isinstance(ev_ts, str)
        ):
            existing = last_ts_by_pid.get(ev_pid)
            if existing is None or ev_ts > existing:
                last_ts_by_pid[ev_pid] = ev_ts

    # Synthesize daemon_stopped for unmatched daemon_started events.
    recovered_count = 0
    now = now_fn()
    for prior_pid, started_event in started_by_pid.items():
        if prior_pid in stopped_pids:
            continue
        # Compute uptime_seconds from started_at_ts to last-observed-ts
        # for the prior PID; fall back to 0.0 if parsing fails or no
        # later events exist (the synthesis-time placeholder per
        # ADR-0068 D364).
        started_at_ts = started_event.get("ts", "")
        latest_observed_ts = last_ts_by_pid.get(prior_pid, started_at_ts)
        uptime_seconds = 0.0
        try:
            started_at = datetime.strptime(
                started_at_ts, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
            latest_observed = datetime.strptime(
                latest_observed_ts, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
            uptime_seconds = max(
                0.0, (latest_observed - started_at).total_seconds(),
            )
        except (ValueError, TypeError):
            # Malformed ts on the prior event — fall back to 0.0
            # placeholder. Operators see the synthesis fired with
            # uptime=0.0 + investigate via ledger inspection.
            uptime_seconds = 0.0
        emit_fn({
            "type": "daemon_stopped",
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            **build_daemon_stopped_payload(
                pid=prior_pid,
                exit_reason="crash",
                uptime_seconds=uptime_seconds,
                in_flight_task_count_at_exit=0,
            ),
            "_recovered_by": "reconcile",
            "_recovered_for_pid": prior_pid,
        })
        recovered_count += 1

    return recovered_count


async def _default_dispatch_for_stage(
    runner: "DaemonRunner", stage: str,
) -> None:
    """Default per-funnel-stage dispatch per ADR-0066 D358.

    Pillar H Week 7 wires the Iteration 6b body
    (:meth:`DaemonRunner.run`) to invoke this function (via the
    ``dispatch_fn`` test-only seam at the call site) for every
    per-funnel-stage tick that is NOT semaphore-saturated. The body:

    1. Consults :data:`_STAGE_TO_PASSES` to determine which reconcile
       passes (defined in :mod:`orchestrator.reconcile`) to invoke for
       this funnel stage. An empty pass list (producer stages
       ``queued``/``researched``/``drafted``/``ready`` + the
       channel-dispatch-deferred ``sent``) returns immediately — no
       reconcile work for the daemon at v1.
    2. Invokes :func:`reconcile` via :func:`asyncio.to_thread` (the
       reconcile passes are SYNC; the daemon's tick loop is async).
       The default ``since`` window is the last 24 hours per
       :data:`reconcile.QUICK_WINDOW`. The ``apply=True`` flag enables
       state-mutating passes (Pass C heals vault; Pass M writes
       suppression YAML; Pass G + N + O emit derived events).

    **Pure-framework + classifier-dependent passes only at Week 7** —
    the v1 :data:`_STAGE_TO_PASSES` mapping includes ONLY passes that
    consume framework state (ledger + people_dir + suppressions_dir) +
    Pass G's :class:`~orchestrator.reply_classifier.RuleBasedClassifier`
    (constructed via :func:`reconcile._build_classifier_or_record_error`
    from ``~/.outreach-factory/classifier/unsubscribe-patterns.yml`` per
    ADR-0026 D103 — the same bootstrap operators do for the reconcile
    CLI):

    * Pass C (vault↔ledger heal) — needs ``people_dir``.
    * Pass G (reply classification) — needs
      :class:`RuleBasedClassifier` (constructed via
      :func:`reconcile._build_classifier_or_record_error`; operator
      bootstraps the pattern YAML per ADR-0026 D103). **Pillar H Week 7
      follow-up P1-1 closure** — the W7 main commit's ADR-0066 D358
      narrative claim "Pass G (reply classification) — pure framework
      (no external client)" was the **SIXTH ADR-vs-actual-impl drift in
      Pillar H** caught by the per-week-reviewer's cross-pillar
      back-audit discipline (the prior FIVE: W2 P3-8 → W3 P2-1 → W4
      P2-1 → W5 P1-1 → W6 P2-2). Pass G's classifier dependency was
      missed — operator bootstraps the pattern file but the daemon's
      dispatch did NOT construct the classifier; every per-tick
      ``replied``-stage dispatch silently failed via
      ``PassResult.errors`` discarded at the dispatch caller. The W7
      follow-up commit lazy-constructs the classifier here.
    * Pass M (auto-unsubscribe handler) — needs ``suppressions_dir``.
    * Pass N (conversation state machine) — pure framework.
    * Pass O (conversation outcomes) — pure framework.

    Channel-dispatch passes (A / B / D / E / F / H / I / J) require
    per-channel client construction (Gmail / LinkedIn / Twitter) that
    the daemon does NOT wire at v1 — operators invoke those passes from
    the existing ``python -m orchestrator.reconcile`` CLI per ADR-0066
    D358's deferred-channel-dispatch trajectory. Pillar H Week 8+
    extends :class:`DaemonConfig` + this dispatch with per-channel
    client factory kwargs concurrently per the per-pillar mirror
    constants parity discipline.

    **Classifier missing-bootstrap posture.** If the operator has NOT
    bootstrapped the pattern YAML at
    ``~/.outreach-factory/classifier/unsubscribe-patterns.yml``,
    :func:`reconcile._build_classifier_or_record_error` returns
    ``(None, error_msg)`` — the dispatch passes ``classifier=None`` to
    :func:`reconcile.reconcile` which records the error in
    ``PassResult.errors`` per the existing reconcile CLI behavior. The
    error is logged to stderr once per tick (operators see the
    bootstrap reminder in the daemon's log stream) but the daemon does
    NOT crash on the missing pattern file — Pass G is the only
    classifier-dependent pass at v1, and Pass M (auto-unsubscribe) +
    Pass C (vault heal) + Pass N (conversation state) + Pass O
    (conversation outcomes) run independently.

    **Idempotency contract.** The reconcile passes are idempotent by
    design per Pillar D's ADR-0014 D33 + ADR-0025 D97-D100 contracts
    — the per-(mid, channel) idempotence keys at Pass A / B / G + the
    per-(thread_id) idempotence at Pass N / O prevent double-emit if
    the daemon's per-tick dispatch invokes the same pass multiple times
    within a single reconcile cycle. The asyncio.Semaphore at the
    Iteration 6b call site bounds CONCURRENT dispatch to
    :attr:`DaemonConfig.parallelism_limits[stage]` per ADR-0060 D331;
    the per-tick LOOP frequency is bounded by ``tick_seconds`` per
    :meth:`DaemonRunner.run`.

    **Error handling.** Exceptions from the reconcile passes propagate
    out of this function — the daemon's tick loop's outer try/finally
    block at :meth:`DaemonRunner.run` Step 7 catches at the
    :func:`AppRunner.cleanup` site (the W5 follow-up P2-2 closure's
    cleanup-on-exception regression-barrier discipline). Operators see
    the error in the daemon's stderr + the daemon exits non-zero. The
    asyncio.CancelledError propagation contract per the W5 follow-up
    NEW-6 closure preserves.

    Pillar I per-tenant fan-out per ADR-0060 D335 invariant 1 — each
    tenant container's :class:`DaemonRunner` dispatches per its own
    people_dir + suppressions_dir + ledger; the per-tenant isolation
    is structural via the per-container :class:`DaemonRunner` instance.
    """
    passes = _STAGE_TO_PASSES.get(stage, "")
    if not passes:
        return  # Producer stage OR channel-dispatch deferred per ADR-0066 D358.

    # Lazy imports to keep the daemon import-graph minimal at startup.
    # The reconcile + auto_unsubscribe modules import heavy dependencies
    # (yaml, multiple Pillar D modules) that are only needed when the
    # daemon's per-stage tick actually dispatches reconcile work.
    from datetime import timedelta  # noqa: PLC0415
    import orchestrator.reconcile as _reconcile  # noqa: PLC0415

    # Resolve effective paths.
    people_dir = runner.config.people_dir
    if people_dir is None:
        people_dir = runner.config.vault_dir / "10 People"
    suppressions_dir = runner.config.suppressions_dir
    if suppressions_dir is None:
        from orchestrator import auto_unsubscribe as _au  # noqa: PLC0415
        suppressions_dir = _au.suppressions_dir_default()

    # Pillar H Week 9 per ADR-0067 D362 — consume the daemon's own
    # :class:`Ledger` instance (with the per-event-class index
    # invalidation observer registered at :func:`init_daemon` Step 8.5)
    # if present; falls back to lazy construction for backward compat
    # with pre-Week-9 tests + external operator-invoked dispatchers
    # that construct :class:`DaemonRunner` directly without
    # ``ledger=`` kwarg. The fallback path's appends do NOT trigger
    # the index invalidation observer (no observer registered on the
    # ephemeral Ledger); operators relying on per-Person primitive
    # consumption of the index after such ephemeral appends would see
    # stale data — at v1 single-tenant single-process the daemon's
    # production-default path goes through ``runner.ledger`` so this
    # only affects unit-test scope.
    if runner.ledger is not None:
        led = runner.ledger
    else:
        led = Ledger(runner.config.ledger_dir)

    # Pillar H Week 7 follow-up P1-1 closure: lazy-construct the
    # :class:`~orchestrator.reply_classifier.RuleBasedClassifier` for
    # Pass G per ADR-0026 D103. The W7 main commit's ADR-0066 D358
    # narrative claim "Pass G — pure framework (no external client)"
    # was the SIXTH ADR-vs-actual-impl drift in Pillar H (the prior
    # FIVE: W2 P3-8 OTel Resource → W3 P2-1 _emitted_by → W4 P2-1
    # framework-neutrality → W5 P1-1 traced_stage signature → W6 P2-2
    # Step 5.5 ordering). Pass G needs a classifier instance + the
    # daemon dispatch silently failed per-tick via
    # ``PassResult.errors`` discarded by the dispatch caller. The
    # W7 follow-up constructs the classifier here via the same helper
    # the reconcile CLI uses (operator-symmetric bootstrap path).
    #
    # If the operator hasn't bootstrapped the pattern YAML at
    # ``~/.outreach-factory/classifier/unsubscribe-patterns.yml``,
    # :func:`_build_classifier_or_record_error` returns
    # ``(None, error_msg)`` — the dispatch passes ``classifier=None``
    # to :func:`reconcile.reconcile` which records the error in
    # ``PassResult.errors`` per the existing CLI behavior + the daemon
    # logs the error to stderr once per tick so operators see the
    # bootstrap reminder in the daemon's log stream.
    classifier, classifier_err = _reconcile._build_classifier_or_record_error(
        _reconcile._classifier_pattern_path_default()
    )
    if classifier_err is not None:
        import sys  # noqa: PLC0415
        print(
            f"WARNING: Pillar H daemon dispatch at stage={stage!r} cannot "
            f"construct classifier: {classifier_err}. Pass G (reply "
            f"classification) will be skipped per-tick until the operator "
            f"bootstraps the pattern YAML per ADR-0026 D103. The other "
            f"passes (C/M/N/O) continue to run.",
            file=sys.stderr,
        )

    # The reconcile passes are sync; bridge to async via to_thread per
    # ADR-0060 D332's asyncio framework decision.
    await asyncio.to_thread(
        _reconcile.reconcile,
        passes=passes,
        since=datetime.now(tz=timezone.utc) - _reconcile.QUICK_WINDOW,
        led=led,
        people_dir=people_dir,
        suppressions_dir=suppressions_dir,
        classifier=classifier,
        apply=True,
        persist_status=False,  # Daemon's tick loop is the persistence cadence.
    )


def build_daemon_started_payload(
    pid: int,
    version: str,
    config_hash: str,
    startup_seconds: float,
) -> dict[str, Any]:
    """Build the emit-shape payload for the ``daemon_started`` event
    per ADR-0061 D339.

    Pillar H Week 2 ships the **factory** (not the actual emit); the
    actual transition + ledger append happens at Pillar H Week 5+ when
    :meth:`DaemonRunner.run` transitions from ``"initializing"`` to
    ``"ready"`` per ADR-0060 D332's per-week trajectory. The factory
    shape mirrors the Pillar G ``build_*_payload`` convention per
    ADR-0010 D17 + the channel-on-every-event invariant per ADR-0014
    D33 (the ``daemon_started`` event has NO channel context — daemon
    lifecycle events are tenant-process-scoped, not per-channel; the
    payload omits the ``channel`` key; the consumer surface
    (:func:`collect_event_class_snapshots`) treats absence as ``None``
    per ADR-0050 D272).

    Args:
        pid: the daemon process's OS PID (from :func:`os.getpid` at
            startup).
        version: the daemon version string from :data:`_DAEMON_VERSION`.
        config_hash: the SHA-256 hash of the :class:`DaemonConfig` from
            :func:`_compute_config_hash`. Operators query to detect
            config drift across restarts.
        startup_seconds: float seconds the startup sequence took
            (migrations + policy + OTel + Prometheus); rounded to 3
            decimal places per ADR-0031 D140 deterministic-output
            contract.

    Returns:
        A dict with the canonical ``daemon_started`` event payload.
        The factory stamps ``_emitted_by="daemon"`` at the factory
        boundary per ADR-0010 D17 + the Pillar E
        :data:`orchestrator.tier_assignment.EMITTED_BY` +
        :data:`orchestrator.discovery_lineage.EMITTED_BY` precedent
        (Pillar H Week 3 follow-up P2-1 closure — the Week 3 main
        commit's docstring FALSELY claimed ``_emitted_by`` was "auto-
        filled by :meth:`Ledger.append`" but
        :meth:`Ledger.append` only does ``setdefault("v")`` +
        ``setdefault("ts")``; the factory has to stamp the audit
        marker itself). The ``type`` field is set by the caller (the
        emitter writes ``{"type": "daemon_started", **build_..._payload(...)}``)
        and ``ts`` is auto-filled by :meth:`Ledger.append`.

    Raises:
        :exc:`ValueError`: on invalid input per the Pillar H Week 2
            follow-up P2-2 closure (the Pillar G factory convention for
            raw-primitive payloads — see
            :func:`discovery_dedup.build_discovery_dedup_hit_payload`
            for the canonical precedent — validates at the factory
            boundary because there is no upstream invariant-bearing
            dataclass). ``pid`` MUST be ``> 0`` (POSIX OS PIDs are
            positive); ``version`` MUST be non-empty (operators see
            empty version in the ``daemon_started`` payload as a
            diagnostic failure); ``config_hash`` MUST be 64 hex chars
            (SHA-256 digest length per :func:`_compute_config_hash`
            contract); ``startup_seconds`` MUST be ``>= 0.0`` (time
            does not flow backward).
    """
    # Pillar H Week 2 follow-up P2-2 closure — input validation per the
    # Pillar G raw-primitive factory convention (see
    # discovery_dedup.build_discovery_dedup_hit_payload's refuse-loud at
    # construction for the canonical precedent). The factory takes raw
    # primitives (pid + version + config_hash + startup_seconds), NOT a
    # frozen dataclass with construction-time invariants — so the refuse-
    # loud has to live at the factory boundary.
    if pid <= 0:
        raise ValueError(
            f"build_daemon_started_payload requires pid > 0; got {pid!r}. "
            f"OS PIDs are positive integers per POSIX."
        )
    if not version:
        raise ValueError(
            "build_daemon_started_payload requires non-empty version; "
            "the production default is _DAEMON_VERSION (currently '0.1.0')."
        )
    if len(config_hash) != 64:
        raise ValueError(
            f"build_daemon_started_payload requires 64-hex-char "
            f"config_hash (SHA-256 digest); got len={len(config_hash)} "
            f"({config_hash!r})."
        )
    if startup_seconds < 0.0:
        raise ValueError(
            f"build_daemon_started_payload requires startup_seconds >= 0; "
            f"got {startup_seconds!r}. Time does not flow backward."
        )
    return {
        "pid": pid,
        "version": version,
        "config_hash": config_hash,
        "startup_seconds": round(startup_seconds, 3),
        "_emitted_by": EMITTED_BY,
    }


def build_daemon_stopping_payload(
    pid: int,
    reason: str,
    drain_deadline_ts: str,
    in_flight_task_count: int,
) -> dict[str, Any]:
    """Build the emit-shape payload for the ``daemon_stopping`` event
    per ADR-0062 D343.

    Pillar H Week 3 ships the factory + the actual emit (at
    :meth:`DaemonRunner.shutdown` Step 2). The factory shape mirrors
    the Pillar G ``build_*_payload`` convention per ADR-0010 D17 + the
    Pillar H Week 2 :func:`build_daemon_started_payload` precedent —
    raw-primitive factory with refuse-loud at construction time per
    the Pillar G :func:`discovery_dedup.build_discovery_dedup_hit_payload`
    + Pillar H Week 2 follow-up P2-2 closure conventions.

    Args:
        pid: the daemon process's OS PID (must be ``> 0``).
        reason: one of :data:`SHUTDOWN_REASONS` (``"sigterm"`` |
            ``"sigint"`` | ``"operator_requested"``).
        drain_deadline_ts: ISO-8601 UTC timestamp of the drain
            deadline (``now + DaemonConfig.graceful_shutdown_seconds``);
            operators query the deadline to bound observability dashboards.
        in_flight_task_count: number of per-stage tasks running at
            the time of the shutdown signal. Week 3 always emits 0 (the
            per-stage worker pool body lands at Week 5+); Week 5+
            extends with actual task counting.

    Returns:
        A dict with the canonical ``daemon_stopping`` event payload
        (pid + reason + drain_deadline_ts + in_flight_task_count +
        ``_emitted_by="daemon"``). The factory stamps ``_emitted_by``
        at the factory boundary per ADR-0010 D17 + the Pillar E
        :data:`EMITTED_BY` precedent (Pillar H Week 3 follow-up P2-1
        closure — the Week 3 main commit's docstring FALSELY claimed
        auto-fill by :meth:`Ledger.append`). The ``type`` field is
        set by the caller (the emitter writes
        ``{"type": "daemon_stopping", **build_..._payload(...)}``)
        and ``ts`` is auto-filled by :meth:`Ledger.append`. The
        ``channel`` field is OMITTED per ADR-0014 D33 (daemon
        lifecycle events are tenant-process-scoped, not per-channel).

    Raises:
        :exc:`ValueError`: on invalid input per the Pillar H Week 2
            follow-up P2-2 closure raw-primitive factory convention.
    """
    if pid <= 0:
        raise ValueError(
            f"build_daemon_stopping_payload requires pid > 0; got {pid!r}. "
            f"OS PIDs are positive integers per POSIX."
        )
    if reason not in SHUTDOWN_REASONS:
        raise ValueError(
            f"build_daemon_stopping_payload reason not in SHUTDOWN_REASONS "
            f"({sorted(SHUTDOWN_REASONS)!r}): {reason!r}"
        )
    if not drain_deadline_ts:
        raise ValueError(
            "build_daemon_stopping_payload requires non-empty "
            "drain_deadline_ts (ISO-8601 UTC with Z suffix per ADR-0010 D17)."
        )
    if in_flight_task_count < 0:
        raise ValueError(
            f"build_daemon_stopping_payload requires "
            f"in_flight_task_count >= 0; got {in_flight_task_count!r}."
        )
    return {
        "pid": pid,
        "reason": reason,
        "drain_deadline_ts": drain_deadline_ts,
        "in_flight_task_count": in_flight_task_count,
        "_emitted_by": EMITTED_BY,
    }


def build_daemon_stopped_payload(
    pid: int,
    exit_reason: str,
    uptime_seconds: float,
    in_flight_task_count_at_exit: int,
) -> dict[str, Any]:
    """Build the emit-shape payload for the ``daemon_stopped`` event
    per ADR-0062 D343.

    Pillar H Week 3 ships the factory + the actual emit (at
    :meth:`DaemonRunner.shutdown` Step 5). The factory shape mirrors
    the Pillar G ``build_*_payload`` convention per ADR-0010 D17 + the
    Pillar H Week 2 :func:`build_daemon_started_payload` precedent.

    Args:
        pid: the daemon process's OS PID (must be ``> 0``).
        exit_reason: one of :data:`DAEMON_EXIT_REASONS` (``"clean"`` |
            ``"timeout"`` | ``"crash"``). Week 3 always emits
            ``"clean"`` (no per-stage drain to time out); Week 5+
            extends.
        uptime_seconds: float seconds from
            :attr:`DaemonRunner.started_at_ts` to the shutdown
            timestamp; rounded to 3 decimal places per ADR-0031 D140.
        in_flight_task_count_at_exit: number of per-stage tasks
            still running at exit (after drain). Week 3 always emits
            0; Week 5+ extends.

    Returns:
        A dict with the canonical ``daemon_stopped`` event payload
        (pid + exit_reason + uptime_seconds + in_flight_task_count_at_exit
        + ``_emitted_by="daemon"``). The factory stamps ``_emitted_by``
        at the factory boundary per ADR-0010 D17 + the Pillar E
        :data:`EMITTED_BY` precedent (Pillar H Week 3 follow-up P2-1
        closure). The ``type`` field is set by the caller and ``ts``
        is auto-filled by :meth:`Ledger.append`. The ``channel`` field
        is OMITTED per ADR-0014 D33.

    Raises:
        :exc:`ValueError`: on invalid input per the Pillar H Week 2
            follow-up P2-2 closure raw-primitive factory convention.
    """
    if pid <= 0:
        raise ValueError(
            f"build_daemon_stopped_payload requires pid > 0; got {pid!r}. "
            f"OS PIDs are positive integers per POSIX."
        )
    if exit_reason not in DAEMON_EXIT_REASONS:
        raise ValueError(
            f"build_daemon_stopped_payload exit_reason not in "
            f"DAEMON_EXIT_REASONS ({sorted(DAEMON_EXIT_REASONS)!r}): "
            f"{exit_reason!r}"
        )
    if uptime_seconds < 0.0:
        raise ValueError(
            f"build_daemon_stopped_payload requires uptime_seconds >= 0; "
            f"got {uptime_seconds!r}. Time does not flow backward."
        )
    if in_flight_task_count_at_exit < 0:
        raise ValueError(
            f"build_daemon_stopped_payload requires "
            f"in_flight_task_count_at_exit >= 0; got "
            f"{in_flight_task_count_at_exit!r}."
        )
    return {
        "pid": pid,
        "exit_reason": exit_reason,
        "uptime_seconds": round(uptime_seconds, 3),
        "in_flight_task_count_at_exit": in_flight_task_count_at_exit,
        "_emitted_by": EMITTED_BY,
    }


def build_daemon_stage_saturated_payload(
    *,
    pid: int,
    stage: str,
    parallelism_limit: int,
    in_flight_count: int,
) -> dict[str, Any]:
    """Build the emit-shape payload for the ``daemon_stage_saturated``
    event per ADR-0065 D355 (Pillar H Week 6 NEW).

    Emitted per-tick per-funnel-stage when the corresponding
    :class:`asyncio.Semaphore` bounded by
    :attr:`DaemonConfig.parallelism_limits` is exhausted (all slots
    acquired). Operators consume via the Pillar H Grafana panel 2 at
    ``infra/grafana/dashboards/per_daemon.yml`` (the panel 2 placeholder
    from Pillar H Week 4 ADR-0063 D347 goes live at Week 6 commit).

    Args:
        pid: the daemon process's OS PID (must be ``> 0``).
        stage: one of :data:`funnel._PILLAR_G_PIPELINE_STAGES` (the
            FUNNEL stages — refuses-loud on
            :data:`observability._PIPELINE_STAGES` values or unknown
            values per the Pillar H Week 1 follow-up P3-5 closure's
            two-closed-sets distinction). The funnel stages bound
            :attr:`DaemonConfig.parallelism_limits`'s keys per ADR-0060
            D331 + Week 2 follow-up P2-1 closure's ``_validate_config``
            refuse-loud.
        parallelism_limit: the configured per-stage parallelism limit
            (``DaemonConfig.parallelism_limits[stage]``); must be
            ``>= 1`` per Pillar H Week 2 follow-up P2-1 closure's
            refuse-loud at config validation.
        in_flight_count: the current in-flight task count at this
            stage; MUST be in ``[0, parallelism_limit]``. At Week 6
            SKELETON, the body emits this event ONLY when
            ``asyncio.Semaphore.locked()`` returns True (all slots
            acquired) so the body's call site ALWAYS passes
            ``in_flight_count=parallelism_limit``; the factory's
            wider acceptance range ``[0, parallelism_limit]`` is
            forward-compatible scaffolding for Week 7+'s actual
            per-stage dispatch body where ``in_flight_count`` may
            be reported below saturation as a backpressure-trending
            metric (e.g., ``in_flight_count=3 / parallelism_limit=4``
            signals "near-saturation but not at-limit").

            **Pillar H Week 6 follow-up P3-9 + P3-10 closure** —
            documents the factory-wide-vs-body-emit-narrow asymmetry
            + the :class:`asyncio.Semaphore` waiter-case semantic:
            asyncio's Semaphore is a counting primitive whose
            ``locked()`` returns True iff ``_value == 0``; queued
            waiters (tasks blocked on ``acquire()``) are tracked in
            a separate FIFO but do NOT affect ``locked()``. At
            saturation the in-flight count equals the parallelism
            limit (no slots available); waiter count is a SEPARATE
            backpressure signal Week 7+ MAY surface via an extended
            ``waiter_count`` field (the closed-set discipline per
            ADR-0050 D272's R031-shape mitigation extends naturally
            to additional fields at the factory boundary).

    Returns:
        A dict with the canonical ``daemon_stage_saturated`` event
        payload (pid + stage + parallelism_limit + in_flight_count +
        ``_emitted_by="daemon"``). The factory stamps ``_emitted_by``
        at the factory boundary per ADR-0010 D17 + the Pillar E
        :data:`EMITTED_BY` precedent + the Pillar H Week 3 follow-up
        P2-1 closure. The ``type`` field is set by the caller and
        ``ts`` is auto-filled by :meth:`Ledger.append`. The ``channel``
        field is OMITTED per ADR-0014 D33 (daemon lifecycle events
        are tenant-process-scoped NOT per-channel; per-channel
        saturation would be a separate Pillar C concern).

    Raises:
        :exc:`ValueError`: on invalid input per the Pillar H Week 2
            follow-up P2-2 closure raw-primitive factory convention.
    """
    # Pillar H Week 6 follow-up P3-1 closure: the lazy import here uses
    # the standardized ``from orchestrator.funnel import`` form aligned
    # with the other two lazy sites (the W6 follow-up reviewer found
    # the THREE sites had inconsistent forms — DaemonRunner.run + this
    # factory used ``from orchestrator.funnel import``; _validate_config
    # used ``import funnel as _funnel``). Lazy is required because
    # :mod:`orchestrator.funnel`'s module body does bare-name
    # ``import ledger`` requiring ``orchestrator/`` on ``sys.path``
    # (test-only sys.path shim via conftest.py); the module-top import
    # block at this file's top documents the full production-fragility
    # rationale.
    from orchestrator.funnel import (  # noqa: PLC0415
        _PILLAR_G_PIPELINE_STAGES,
    )
    if pid <= 0:
        raise ValueError(
            f"build_daemon_stage_saturated_payload requires pid > 0; "
            f"got {pid!r}. OS PIDs are positive integers per POSIX."
        )
    if stage not in _PILLAR_G_PIPELINE_STAGES:
        raise ValueError(
            f"build_daemon_stage_saturated_payload stage not in "
            f"_PILLAR_G_PIPELINE_STAGES "
            f"({sorted(_PILLAR_G_PIPELINE_STAGES)!r}): {stage!r}. "
            f"Per ADR-0065 D355 + the Pillar H Week 1 follow-up P3-5 "
            f"closure's two-closed-sets distinction (funnel stages = "
            f"per-pipeline-event stages for the operator-observable "
            f"funnel progression; observability stages = per-span dims "
            f"for traced_stage). daemon_stage_saturated is emitted at "
            f"the funnel-stage granularity per the per-stage worker "
            f"pool's Semaphore-per-funnel-stage construction at "
            f"DaemonRunner.run Step 6 + ADR-0060 D331."
        )
    if parallelism_limit < 1:
        raise ValueError(
            f"build_daemon_stage_saturated_payload requires "
            f"parallelism_limit >= 1; got {parallelism_limit!r}. "
            f"Per Pillar H Week 2 follow-up P2-1 closure's "
            f"_validate_config refuse-loud rule."
        )
    if not (0 <= in_flight_count <= parallelism_limit):
        raise ValueError(
            f"build_daemon_stage_saturated_payload requires "
            f"0 <= in_flight_count <= parallelism_limit "
            f"(parallelism_limit={parallelism_limit!r}); "
            f"got in_flight_count={in_flight_count!r}. Per ADR-0065 "
            f"D355's per-stage Semaphore contract — the Semaphore's "
            f"value cannot exceed the operator-deliberate "
            f"parallelism_limits[stage] per ADR-0060 D331."
        )
    return {
        "pid": pid,
        "stage": stage,
        "parallelism_limit": parallelism_limit,
        "in_flight_count": in_flight_count,
        "_emitted_by": EMITTED_BY,
    }


def build_policy_reloaded_payload(
    *,
    pid: int,
    source_path: str,
    prior_content_hash: str,
    new_content_hash: str,
    status: str,
) -> dict[str, Any]:
    """Build the emit-shape payload for the ``policy_reloaded`` event
    per ADR-0066 D357 (Pillar H Week 7 NEW factory; the ``policy_reloaded``
    event class itself joined :data:`DAEMON_NEW_EVENT_CLASSES` +
    :data:`observability.EVENT_CLASS_CATALOG` at Pillar H Week 2 per
    ADR-0061 D338's per-pillar locality convention — Week 7 ships the
    BODY + the FACTORY for it).

    Emitted exactly-once per :meth:`DaemonRunner.reload_policy`
    invocation (SIGHUP-driven OR test-substrate-driven) with the prior +
    new content hashes + the reload status. Operators consume via the
    Pillar H per_daemon.yml Grafana dashboard's
    policy-reload-frequency panel (trajectory at Pillar H Week 8+
    extension to per_daemon.yml).

    Args:
        pid: the daemon process's OS PID (must be ``> 0``). Tenant
            scope per ADR-0060 D335 invariant 1 — one daemon process
            per tenant; pid uniquely identifies the tenant at the
            cross-pillar audit-tooling level.
        source_path: string path to the policy directory (or file)
            that the reload targeted. MUST be non-empty per the
            framework's raw-primitive refuse-loud convention. Note
            this is a STRING (not :class:`pathlib.Path`) because the
            JSON-serialized ledger event surface requires a stringifiable
            payload — the caller stringifies via ``str(policy_dir)``
            at the emit site.
        prior_content_hash: SHA-256 hex digest (64 chars) of the
            policy state EFFECTIVE BEFORE the reload. Empty string
            ``""`` is allowed at the FIRST reload after a daemon
            constructed via direct :class:`DaemonRunner` construction
            bypassing :func:`init_daemon` (which populates the initial
            hash); production daemons through :func:`init_daemon` will
            have a non-empty prior_content_hash by Week 7's
            :func:`init_daemon` extension. The factory accepts BOTH a
            64-hex-char SHA-256 digest AND the empty string per this
            documented "initial-load-may-be-empty" semantic.
        new_content_hash: SHA-256 hex digest (64 chars) of the policy
            disk state at the reload attempt. MUST be exactly 64 hex
            chars (no empty-string allowance here — the new hash is
            always computed at reload time per ADR-0066 D356).
        status: one of :data:`POLICY_RELOAD_STATUSES`
            (``"applied"`` | ``"failed_unchanged"``). The closed-set
            membership is enforced at the factory boundary per the
            Pillar H Week 6 :func:`build_daemon_stage_saturated_payload`
            precedent. Pillar I per-tenant per-tenant trajectory may
            extend the closed-set per the per-pillar mirror constants
            parity discipline.

    Returns:
        A dict with the canonical ``policy_reloaded`` event payload —
        a 6-key shape: ``pid`` + ``source_path`` + ``prior_content_hash``
        + ``new_content_hash`` + ``status`` + ``_emitted_by="daemon"``.
        The factory stamps ``_emitted_by`` at the factory boundary per
        ADR-0010 D17 + the Pillar H Week 3 follow-up P2-1 closure's
        audit-marker discipline. The ``type`` field is set by the
        caller (the emitter writes ``{"type": "policy_reloaded",
        **build_policy_reloaded_payload(...)}``) and ``ts`` is
        auto-filled by :meth:`Ledger.append`. The ``channel`` field is
        OMITTED per ADR-0014 D33 (daemon lifecycle events are
        tenant-process-scoped NOT per-channel).

        **Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323
        CONFIRMED** — the 6-key payload excludes ``person_id`` / body
        content / ``source_list``; content hashes are SHA-256 of
        policy YAML files (not per-Person data). The
        ``source_path`` field stringifies a directory path
        (e.g., ``/Users/yang/.outreach-factory/policies``) which is
        operator-controlled deployment state, not user PII.

    Raises:
        :exc:`ValueError`: on invalid input per the Pillar H Week 2
            follow-up P2-2 closure raw-primitive factory convention.
            Specifically:

            * ``pid <= 0`` → not a POSIX OS PID
            * empty ``source_path`` → not operator-actionable
            * ``new_content_hash`` length != 64 → not a SHA-256 digest
            * ``prior_content_hash`` length not in ``{0, 64}`` →
              violates the documented "initial-load-may-be-empty"
              semantic
            * ``status not in POLICY_RELOAD_STATUSES`` → violates the
              per-pillar mirror constants parity discipline + the
              Pillar H Week 1 follow-up P3-3 closure's closed-set
              regression-barrier
    """
    if pid <= 0:
        raise ValueError(
            f"build_policy_reloaded_payload requires pid > 0; "
            f"got {pid!r}. OS PIDs are positive integers per POSIX."
        )
    if not source_path:
        raise ValueError(
            "build_policy_reloaded_payload requires non-empty "
            "source_path; the operator's policy directory MUST be "
            "identifiable in the ledger event payload per ADR-0066 "
            "D357. The :func:`init_daemon` body resolves "
            "config.policy_dir to ``vault_dir.parent / 'policies'`` "
            "if unset; the resulting Path stringifies to a non-empty "
            "string."
        )
    if len(new_content_hash) != 64:
        raise ValueError(
            f"build_policy_reloaded_payload requires 64-hex-char "
            f"new_content_hash (SHA-256 digest); got len="
            f"{len(new_content_hash)} ({new_content_hash!r})."
        )
    # Pillar H Week 7 follow-up P3-4 closure — hex-char validation
    # mirrors the Pillar G/H raw-primitive factory convention (length +
    # char-set validation; the W7 main commit's factory only validated
    # length). Non-hex strings like "Z"*64 / "G"*64 previously passed
    # the factory + landed in the ledger as non-SHA-256 strings.
    if not all(c in "0123456789abcdef" for c in new_content_hash):
        raise ValueError(
            f"build_policy_reloaded_payload requires new_content_hash "
            f"to be lowercase hex chars (SHA-256 digest); got "
            f"{new_content_hash!r}. Pillar H Week 7 follow-up P3-4 "
            f"closure."
        )
    if len(prior_content_hash) not in {0, 64}:
        raise ValueError(
            f"build_policy_reloaded_payload requires "
            f"prior_content_hash to be either empty (initial reload) "
            f"or 64-hex-char SHA-256 digest; got len="
            f"{len(prior_content_hash)} ({prior_content_hash!r}). "
            f"Per the documented initial-load-may-be-empty semantic "
            f"in :func:`build_policy_reloaded_payload`'s Args section."
        )
    if prior_content_hash and not all(
        c in "0123456789abcdef" for c in prior_content_hash
    ):
        raise ValueError(
            f"build_policy_reloaded_payload requires "
            f"prior_content_hash to be empty OR lowercase hex chars "
            f"(SHA-256 digest); got {prior_content_hash!r}. Pillar H "
            f"Week 7 follow-up P3-4 closure."
        )
    if status not in POLICY_RELOAD_STATUSES:
        raise ValueError(
            f"build_policy_reloaded_payload status not in "
            f"POLICY_RELOAD_STATUSES "
            f"({sorted(POLICY_RELOAD_STATUSES)!r}): {status!r}. "
            f"Per Pillar H Week 1 follow-up P3-3 closure's closed-set "
            f"regression-barrier + ADR-0060 D335 invariant 4."
        )
    return {
        "pid": pid,
        "source_path": source_path,
        "prior_content_hash": prior_content_hash,
        "new_content_hash": new_content_hash,
        "status": status,
        "_emitted_by": EMITTED_BY,
    }


def init_daemon(
    config: DaemonConfig,
    *,
    # Test-only seams per the Pillar G TEST-ONLY embed_fn convention +
    # ADR-0061 D337 step 8. Production callers omit all kwargs;
    # tests inject spies to verify startup ordering + mock side-effecting
    # steps without applying real migrations / starting real HTTP servers.
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
    # Pillar H Week 8 NEW per ADR-0067 D360 — test-only seam for the
    # per-event-class index materialization at Step 8. Production
    # callers omit; the default lazy-constructs a :class:`Ledger`
    # from :attr:`DaemonConfig.ledger_dir` + invokes
    # :func:`_materialize_indexes`. Tests inject pre-populated indexes
    # to skip the ledger walk for unit-test substrate isolation. The
    # seam follows the Pillar G TEST-ONLY embed_fn convention + the
    # per-pillar-H seam-vs-fork two-tiered distinction per the W4
    # follow-up P2-1 closure.
    index_materialize_fn: Callable[
        [], "tuple[EventClassIndex, PersonEventIndex]"
    ] | None = None,
    # Pillar H Week 9 follow-up P3-4 closure — test-only seam threading
    # the deterministic-clock callable through :func:`init_daemon` to the
    # :func:`_install_index_invalidation_observer` registration at Step
    # 8.5. Production callers omit; the default :func:`time.time`
    # preserves wall-clock semantics. Tests injecting deterministic
    # timestamps through the FULL init_daemon path (rather than bypassing
    # via direct :func:`_install_index_invalidation_observer` call) get
    # byte-identical reproducibility per ADR-0031 D140 across the
    # observer-fire path + the freshness gauge per ADR-0067 D363.
    invalidation_now_ts_fn: Callable[[], float] = time.time,
    # Pillar H Week 10-11 NEW per ADR-0068 D364 — test-only seam for the
    # crash-recovery synthesis at Step 4.5. Production callers omit; the
    # default invokes :func:`_recover_from_prior_crash` on a Ledger
    # constructed from :attr:`DaemonConfig.ledger_dir`. Tests inject a
    # spy to verify the synthesis fires at the correct step + with the
    # correct current_pid + to capture the recovery count without
    # touching a real ledger. The seam follows the Pillar G TEST-ONLY
    # embed_fn convention + the per-pillar-H seam-vs-fork two-tiered
    # distinction per the W4 follow-up P2-1 closure.
    crash_recovery_fn: Callable[..., int] | None = None,
    # Pillar H Week 10-11 NEW per ADR-0068 D366 — test-only seam for the
    # operator-deliberate pre-flight reconcile pass invocation at Step
    # 4.6. Production callers omit; when
    # :attr:`DaemonConfig.reconcile_passes_at_startup` is set, the
    # default invokes :func:`reconcile.reconcile(passes=value,
    # apply=True, ...)`. Tests inject a spy to verify the invocation
    # fires at the correct step + with the correct passes + to capture
    # the call without performing real Gmail / LinkedIn / Twitter SDK
    # calls.
    reconcile_at_startup_fn: Callable[..., Any] | None = None,
    # Pillar H Week 10-11 NEW per ADR-0068 D364 — test-only seam
    # threading the deterministic-clock callable through to the
    # :func:`_recover_from_prior_crash` synthesis at Step 4.5. Production
    # callers omit; the default uses wall-clock per the documented
    # synthesis ``now_fn`` default. Tests injecting deterministic
    # timestamps through the FULL init_daemon path get byte-identical
    # reproducibility per ADR-0031 D140 across the synthesis path's
    # ``ts`` stamp + the recovered ``uptime_seconds`` derivation.
    crash_recovery_now_fn: Callable[[], datetime] | None = None,
) -> DaemonRunner:
    """Instantiate a :class:`DaemonRunner` from a :class:`DaemonConfig`
    per ADR-0060 D331 + ADR-0061 D337-D340 + ADR-0067 D360.

    **Pillar H Week 2 + Week 8 body.** Follows the STRICT startup ordering
    invariant per ADR-0061 D337 (extended at Pillar H Week 8 per ADR-0067
    D360 with NEW Step 8 — per-event-class index materialization; the
    original Step 8 DaemonRunner construction renumbered to Step 9):

    1. Validate the config (refuse-loud on invalid per the Pillar H
       Week 1 follow-up P3-2 + P3-6 closures).
    2. Compute the config hash (stable across runs).
    3. Resolve the daemon's PID + ISO-8601 startup timestamp + version.
    4. Apply pending ledger migrations via :meth:`MigrationRunner.apply`
       (BEFORE policy load per ADR-0009 D9's idempotent auto-apply
       contract + ADR-0061 D340 P3-1 carry-forward closure).
    5. Load Pillar A policy YAML via :func:`policy.load_rules_from_yaml`
       (AFTER migrations).
    6. Initialize OTel SDK via
       :func:`observability.init_otel_meter_provider` +
       :func:`observability.init_otel_tracer_provider` (set-once at
       daemon startup per R035 + ADR-0061 D340 P3-2 carry-forward
       closure; this is the operator-deliberate set-once site —
       operators invoking ``python orchestrator/funnel.py`` outside
       the daemon use the existing ``set_global=False`` test pattern).
    7. Start Prometheus HTTP exposition via
       :func:`observability.start_prometheus_http_server` at
       ``127.0.0.1`` per R036 security-by-default.
    8. NEW per ADR-0067 D360 — materialize the per-event-class +
       per-Person indexes via :func:`_materialize_indexes` (R039
       mitigation per ADR-0060 D336). The walk is O(N) at startup;
       per-call lookups from the daemon-process per-Person primitives
       drop to O(M_class) when callers pass the index via the new
       optional ``event_class_index`` kwarg per ADR-0067 D361. The
       index is daemon-process-local + rebuildable from the ledger
       per I3; Week 9 ships :meth:`Ledger.append`-driven invalidation
       per ADR-0060 D336.
    9. Construct + return :class:`DaemonRunner` in ``"initializing"``
       state. The actual transition to ``"ready"`` + the
       ``daemon_started`` event emit lands at Week 5+'s
       :meth:`DaemonRunner.run` body per ADR-0060 D332.

    Args:
        config: the :class:`DaemonConfig` (frozen).
        pid_fn: test-only seam — returns the daemon's OS PID. Default
            :func:`os.getpid`.
        ts_fn: test-only seam — returns the startup ISO-8601 UTC
            timestamp. Default :func:`_utc_iso_now`.
        version: the daemon version string. Default
            :data:`_DAEMON_VERSION`.
        migration_apply_fn: test-only seam — applies pending migrations.
            Default constructs :class:`MigrationRunner` + calls
            :meth:`apply` (per the Pillar H Week 1 follow-up P2-1
            regression-barrier closure naming the actual API).
        policy_load_fn: test-only seam — loads policy rules from a
            directory. Default :func:`_default_policy_load`.
        policy_dir: optional policy directory override; default is
            ``config.vault_dir.parent / "policies"`` per the existing
            convention. Tests pass a synthetic dir.
        otel_meter_init_fn: test-only seam — initializes the OTel
            MeterProvider. Default
            :func:`observability.init_otel_meter_provider`.
        otel_tracer_init_fn: test-only seam — initializes the OTel
            TracerProvider. Default
            :func:`observability.init_otel_tracer_provider`.
        prometheus_start_fn: test-only seam — starts the Prometheus
            HTTP exposition server. Default
            :func:`observability.start_prometheus_http_server`.
        prometheus_port: test-only seam — Prometheus port override.
            Default ``None`` falls back to the Pillar G framework
            default (``observability._DEFAULT_PROMETHEUS_PORT``).
        prometheus_addr: test-only seam — Prometheus bind addr
            override. Default ``None`` falls back to
            ``observability._DEFAULT_PROMETHEUS_ADDR`` (``"127.0.0.1"``
            per R036).
        index_materialize_fn: Pillar H Week 8 NEW per ADR-0067 D360 —
            test-only seam returning a two-tuple
            ``(EventClassIndex, PersonEventIndex)``. Default
            ``None`` → lazy-constructs a :class:`Ledger` from
            :attr:`DaemonConfig.ledger_dir` + walks once via
            :func:`_materialize_indexes`. Tests inject pre-populated
            indexes to skip the ledger walk for unit-test substrate
            isolation. The seam follows the Pillar G TEST-ONLY
            embed_fn convention + the per-pillar-H seam-vs-fork
            two-tiered distinction per the W4 follow-up P2-1
            closure (the seam substitutes a BACKEND — the index
            materialization path — for test-time injection;
            operators wanting alternative index shapes — e.g.,
            persistent SQLite-backed index — MUST fork the function
            body per the per-pillar-H precedent).

    Returns:
        A :class:`DaemonRunner` in ``"initializing"`` state. The
        :attr:`DaemonRunner.config_hash` matches
        :func:`_compute_config_hash` output for the given config;
        :attr:`DaemonRunner.pid` matches ``pid_fn()`` output;
        :attr:`DaemonRunner.started_at_ts` matches ``ts_fn()`` output.

    Raises:
        :exc:`ValueError`: on invalid config per
            :func:`_validate_config` (vault_dir / ledger_dir
            non-existent; health_port out of range; parallelism_limits
            keys mismatch; policy_reload_signal not in closed-set;
            Pillar H Week 2 follow-up P2-1 closure extends with
            non-positive ``graceful_shutdown_seconds`` + negative
            ``health_probe_rate_limit_seconds`` + sub-1
            ``parallelism_limits`` values).

    **Framework-neutrality extension point** (Pillar H Week 2 follow-up
    P3-7 closure) per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 —
    the test-only seam kwargs are ALSO the operator framework-neutrality
    extension point. Operators with OTLP / Jaeger / alternative backends
    inject custom OTel readers / span processors / Prometheus alternatives
    via ``otel_meter_init_fn`` + ``otel_tracer_init_fn`` +
    ``prometheus_start_fn`` kwargs. The kwargs are documented as
    "test-only seams" because tests are the primary consumer at v1, but
    production multi-backend operators consume them too:

    .. code-block:: python

        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        import observability as _obs

        init_daemon(
            config,
            otel_meter_init_fn=lambda: _obs.init_otel_meter_provider(
                metric_readers=[my_otlp_metric_reader],
            ),
            otel_tracer_init_fn=lambda: _obs.init_otel_tracer_provider(
                span_processors=[BatchSpanProcessor(OTLPSpanExporter())],
            ),
        )

    **OTel-after-policy ordering rationale** (Pillar H Week 2 follow-up
    P3-8 closure) — the OTel SDK init runs at Step 6, AFTER migrations
    (Step 4) + policy load (Step 5). The structural rationale per R035
    set-once enforcement: a failed-startup that DID set the global
    MeterProvider / TracerProvider cannot be cleanly retried in-process
    without test-only ``set_global=False``. Placing OTel AFTER migrations
    + policy means a migration / policy failure does NOT burn the global
    OTel state — the failed daemon process exits + a fresh process
    retries cleanly from Step 1. (The original ADR-0061 D337 rationale
    naming "the OTel ``Resource`` carries the operator-deliberate
    service identity from the loaded policy" was incorrect — the OTel
    Resource at :func:`observability.init_otel_meter_provider` is built
    from :data:`observability._SERVICE_NAME` + :data:`_SERVICE_VERSION`,
    with no consumer of the loaded policy; the corrected rationale is
    the set-once-burnout-on-failed-startup concern.)
    """
    # Step 1: validate (refuse-loud BEFORE any side-effecting step).
    _validate_config(config)

    # Step 2: compute hash.
    config_hash = _compute_config_hash(config)

    # Step 3: resolve identity.
    pid = pid_fn()
    started_at_ts = ts_fn()

    # Step 4: apply pending ledger migrations (BEFORE policy load per
    # the startup ordering invariant; ADR-0061 D340 P3-1 closure).
    if migration_apply_fn is None:
        # Lazy import to keep daemon import-graph minimal.
        from orchestrator.migrations import MigrationRunner  # noqa: PLC0415
        MigrationRunner().apply()
    else:
        migration_apply_fn()

    # Step 4.5: NEW per ADR-0068 D364 — crash-recovery synthesis per
    # ADR-0060 D335 invariant 2 (atomicity-preservation-across-process-
    # boundary). Synthesizes ``daemon_stopped(exit_reason="crash",
    # _recovered_by="reconcile")`` events for any prior daemon_started
    # events that lack matching daemon_stopped events (matched by PID).
    # Runs AFTER Step 4 (migrations applied; ledger schema current) +
    # BEFORE Step 5 (policy load; a parse error MUST NOT prevent
    # crash-recovery synthesis) + BEFORE Step 8 (index materialization;
    # the synthesized events flow into the indexes naturally at Step 8).
    #
    # The synthesis is operator-transparent at v1 — operators upgrading
    # to W10-11 see synthesized ``daemon_stopped`` events appear in the
    # ledger for any prior crashed daemons; the R032 synthetic-event
    # exclusion per ADR-0056 D311's ``_recovered_by`` filter naturally
    # excludes them from Pillar G SLO aggregation. The current daemon's
    # PID is defensively excluded from the synthesis candidate set per
    # the POSIX PID-reuse semantic.
    #
    # The seam ``crash_recovery_fn`` substitutes the synthesis BACKEND
    # for test injection per the W4 follow-up P2-1 seam-vs-fork two-
    # tiered distinction; production callers omit + receive the default
    # :func:`_recover_from_prior_crash` invocation.
    if crash_recovery_fn is None:
        # Lazy-construct a Ledger for the crash-recovery walk. The same
        # Ledger instance is REUSED at Step 8 (index materialization) +
        # Step 8.5 (observer install) per the W9 lift — but the W10-11
        # synthesis runs BEFORE Step 8, so the Step 8 path constructs
        # its own Ledger via the existing W8 default. Operators auditing
        # the startup cost see TWO Ledger walks at W10-11 (the W10-11
        # recovery walk + the W8 materialization walk); v1 scale ~5K
        # events is sub-second total. Pillar I per-tenant trajectory MAY
        # consolidate to a single walk if startup latency becomes a
        # constraint.
        _recovery_led = Ledger(config.ledger_dir)
        _recover_from_prior_crash(
            led=_recovery_led,
            current_pid=pid,
            now_fn=crash_recovery_now_fn,
        )
    else:
        crash_recovery_fn(current_pid=pid, now_fn=crash_recovery_now_fn)

    # Step 4.6: NEW per ADR-0068 D366 — operator-deliberate reconcile
    # pre-flight pass invocation per ADR-0060 D335 invariant 2's R037
    # mitigation. Runs AFTER Step 4.5's crash-recovery synthesis +
    # BEFORE Step 5's policy load. Default config.reconcile_passes_at_startup
    # is None (test substrate + dev path; no Gmail / LinkedIn / Twitter
    # SDK calls at startup); production operators set to "A" (Gmail
    # intent recovery only) or "A,B,D,E,F,H,I,J" (the full intent-
    # recovery pass set per ADR-0014/0017/0018/0027). Failures log to
    # stderr + do NOT prevent daemon startup — the per-tick reconcile
    # dispatch via Pillar H Week 7's ``dispatch_fn`` IS the structural
    # backstop; pre-flight is operator convenience.
    #
    # Pillar H Week 10-11 follow-up P1-1 closure (the NINTH ADR-vs-
    # actual-impl drift in Pillar H caught by the per-week-reviewer's
    # cross-pillar back-audit discipline at the W10-11 main review;
    # the prior EIGHT: W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2
    # → W7 P1-1 → W8 follow-up P2-1 → W9 follow-up P2-1) — the W10-11
    # main commit's invocation called
    # ``reconcile_at_startup_fn(passes=..., ledger_dir=..., apply=True)``
    # but :func:`orchestrator.reconcile.reconcile`'s actual signature has
    # NO ``ledger_dir`` parameter; it takes ``led: Ledger`` (NOT
    # ``ledger_dir``) + ``since: datetime`` (REQUIRED, no default). The
    # production-default ``reconcile_at_startup_fn=None`` path lazy-
    # imported the actual reconcile + raised ``TypeError: reconcile() got
    # an unexpected keyword argument 'ledger_dir'`` which was caught by
    # the broad ``except Exception`` + logged + silently swallowed —
    # operators opting in via ``DaemonConfig(reconcile_passes_at_startup
    # ="A")`` got the §Existing-operator-seed-recommended config but NO
    # pre-flight reconcile (the W7 P1-1 failure mode repeats exactly).
    # The follow-up uses the actual signature: ``led=Ledger(...)`` +
    # ``since=now - timedelta(days=7)`` (operator-deliberate orphan
    # scope; Pass A's min_intent_age=5min + this 7-day window catch the
    # operator's intent-recovery scope). The behavioral-passthrough
    # regression-barrier
    # ``TestW10_11FollowupReconcileSignaturePassthrough`` introspects
    # :func:`inspect.signature(reconcile.reconcile)` + verifies the
    # call kwargs match the actual signature (would have caught P1-1
    # directly per the W5 P1-1 + W7 P1-1 + W8 + W9 closures'
    # behavioral-passthrough-not-signature-only discipline now THIRTY-
    # TWO consecutive weeks).
    if config.reconcile_passes_at_startup is not None:
        if reconcile_at_startup_fn is None:
            # Lazy import: reconcile pulls heavy Pillar D / Gmail /
            # LinkedIn / Twitter SDK code that's only needed when the
            # operator opts in to pre-flight reconcile.
            from orchestrator import reconcile as _reconcile_mod  # noqa: PLC0415
            reconcile_at_startup_fn = _reconcile_mod.reconcile
        try:
            # Pillar H Week 10-11 follow-up P1-1 closure — use the actual
            # reconcile.reconcile signature: led=Ledger(...) + since=...
            # (NOT the broken ledger_dir=... that the W10-11 main commit
            # used). The 7-day since window catches operator-deliberate
            # orphan intents up to a week old; Pass A's min_intent_age=5min
            # threshold filters the "too-young" intent case naturally.
            _recovery_led = Ledger(config.ledger_dir)
            _since = datetime.now(tz=timezone.utc) - timedelta(days=7)
            reconcile_at_startup_fn(
                passes=config.reconcile_passes_at_startup,
                since=_since,
                led=_recovery_led,
                apply=True,
                persist_status=False,
            )
        except Exception as _exc:  # noqa: BLE001 — best-effort pre-flight
            # The per-tick reconcile dispatch via Pillar H Week 7's
            # dispatch_fn is the structural backstop per ADR-0068 D366;
            # orphan intents detected at startup but not recovered will
            # surface at the next per-tick send-stage dispatch.
            #
            # Common operator-deliberate failure modes at the pre-flight:
            # (a) Pass A invoked without ``gmail`` kwarg → AttributeError
            # on the first ``gmail.search_messages`` call → caught + logged
            # (operators wanting Pass A's full recovery wire ``gmail``
            # via a future DaemonConfig.gmail_client_factory per Pillar
            # I trajectory; v1 operators see only the orphan-but-unqueried
            # post-flight state which the per-tick dispatch surfaces).
            # (b) Reconcile pass parse error / unknown pass letter →
            # ValueError → caught + logged.
            # (c) Ledger lock contention / disk full → OSError → caught
            # + logged.
            print(
                f"WARNING: init_daemon reconcile pre-flight pass "
                f"{config.reconcile_passes_at_startup!r} failed "
                f"({type(_exc).__name__}: {_exc}); the daemon continues "
                f"startup. The per-tick reconcile dispatch via Pillar H "
                f"Week 7's dispatch_fn IS the structural backstop. Per "
                f"ADR-0068 D366 + Pillar H Week 10-11 follow-up P1-1 "
                f"closure (the NINTH ADR-vs-actual-impl drift in Pillar "
                f"H caught by the per-week-reviewer).",
                file=sys.stderr,
            )

    # Step 5: load Pillar A policy (AFTER migrations).
    # Pillar H Week 7 — precedence chain for the effective policy
    # directory per ADR-0066 D356:
    #   1. ``policy_dir`` init_daemon kwarg (operator one-shot override
    #      / test injection) if not None;
    #   2. else :attr:`DaemonConfig.policy_dir` (operator-deliberate
    #      frozen-dataclass config field — new at Week 7) if not None;
    #   3. else the convention default ``vault_dir.parent / "policies"``
    #      (matches the existing :class:`MigrationRunner` default).
    if policy_dir is not None:
        effective_policy_dir = policy_dir
    elif config.policy_dir is not None:
        effective_policy_dir = config.policy_dir
    else:
        effective_policy_dir = config.vault_dir.parent / "policies"
    # Pillar H Week 7 — capture the loaded rules + the initial content
    # hash for the :class:`_PolicyState` holder that
    # :meth:`DaemonRunner.reload_policy` swaps on SIGHUP per ADR-0066
    # D356. Prior to Week 7 the Step 5 load fn's return value was
    # DISCARDED; Week 7 captures + plumbs through to the
    # :class:`DaemonRunner` constructor so the daemon's runtime policy
    # state is operator-observable + reload-swappable.
    initial_rules = policy_load_fn(effective_policy_dir)
    initial_content_hash = _compute_policy_content_hash(effective_policy_dir)
    initial_policy_state = _PolicyState(
        rules=list(initial_rules),
        content_hash=initial_content_hash,
    )

    # Steps 6 + 7: initialize OTel SDK (set-once at daemon startup per
    # R035 + ADR-0061 D340 P3-2 closure) + start Prometheus HTTP
    # exposition at 127.0.0.1 per R036. The Pillar H Week 2 follow-up
    # P3-6 closure consolidates the formerly-duplicated lazy import of
    # ``observability`` to ONE site (the prior shape lazy-imported twice;
    # Python's import-cache made both calls cheap but the code read as
    # if both were needed).
    if (
        otel_meter_init_fn is None
        or otel_tracer_init_fn is None
        or prometheus_start_fn is None
    ):
        import observability as _obs  # noqa: PLC0415
        if otel_meter_init_fn is None:
            otel_meter_init_fn = _obs.init_otel_meter_provider
        if otel_tracer_init_fn is None:
            otel_tracer_init_fn = _obs.init_otel_tracer_provider
        if prometheus_start_fn is None:
            prometheus_start_fn = _obs.start_prometheus_http_server
    # Step 6: OTel SDK init (set-once per R035).
    otel_meter_init_fn()
    otel_tracer_init_fn()
    # Step 7: Prometheus exposition (build kwargs only if operator/test
    # overrode the defaults; defaults of None defer to the Pillar G
    # framework's _DEFAULT_PROMETHEUS_PORT + _DEFAULT_PROMETHEUS_ADDR).
    prom_kwargs: dict[str, Any] = {}
    if prometheus_port is not None:
        prom_kwargs["port"] = prometheus_port
    if prometheus_addr is not None:
        prom_kwargs["addr"] = prometheus_addr
    prometheus_start_fn(**prom_kwargs)

    # Step 8: per ADR-0067 D360 — materialize the per-event-class +
    # per-Person indexes (R039 mitigation per ADR-0060 D336). The walk
    # is O(N) at startup; per-call lookups from the daemon-process
    # per-Person primitives drop to O(M_class) when callers pass the
    # index via the optional ``event_class_index`` kwarg per
    # ADR-0067 D361. The default lazy-constructs a :class:`Ledger`
    # from :attr:`DaemonConfig.ledger_dir` + walks once via
    # :func:`_materialize_indexes`; tests inject pre-populated indexes
    # via the ``index_materialize_fn`` test-only seam per ADR-0067 D360.
    #
    # Pillar H Week 9 per ADR-0067 D362 — the Ledger instance is now
    # LIFTED out of the local scope + stored on the returned
    # :class:`DaemonRunner` (NEW :attr:`DaemonRunner.ledger` field) so
    # the per-event-class index invalidation observer installed at
    # NEW Step 8.5 below fires on every subsequent
    # :meth:`Ledger.append` made on this Ledger instance. The
    # :func:`_default_dispatch_for_stage` body consumes
    # ``runner.ledger`` instead of lazy-constructing per dispatch —
    # preserving observer registration across all daemon-process
    # appends. When ``index_materialize_fn`` is provided (test substrate
    # isolation), ``daemon_ledger`` stays ``None`` — tests that
    # exercise the invalidation contract construct their own Ledger
    # + use :func:`_install_index_invalidation_observer` directly.
    if index_materialize_fn is None:
        daemon_ledger: "Ledger | None" = Ledger(config.ledger_dir)
        event_class_idx, person_idx = _materialize_indexes(daemon_ledger)
    else:
        daemon_ledger = None
        event_class_idx, person_idx = index_materialize_fn()

    # Step 8.5: NEW per ADR-0067 D362 (W9 extension to ADR-0067 per
    # ADR-0060 D336) — register the per-event-class index invalidation
    # observer on the daemon's Ledger instance. Every subsequent
    # :meth:`Ledger.append` triggers in-place mutation of both indexes
    # + advances each index's ``_last_updated_at_ts`` for the
    # Prometheus freshness gauge per ADR-0067 D363. Only runs when
    # the production Ledger was constructed (the test-substrate path
    # at Step 8 above sets ``daemon_ledger=None``); tests exercising
    # the invalidation contract construct their own Ledger + call
    # :func:`_install_index_invalidation_observer` directly via the
    # exported helper.
    if daemon_ledger is not None:
        _install_index_invalidation_observer(
            daemon_ledger, event_class_idx, person_idx,
            now_ts_fn=invalidation_now_ts_fn,
        )

    # Step 9: construct + return DaemonRunner in "initializing" state.
    # Pillar H Week 7 extension: pass the populated :class:`_PolicyState`
    # so :meth:`DaemonRunner.reload_policy` sees the operator's initial
    # policy load as the prior state on the first SIGHUP-driven reload.
    # Pillar H Week 8 extension per ADR-0067 D360 — pass the populated
    # :class:`EventClassIndex` + :class:`PersonEventIndex` so the
    # daemon-process per-Person primitive consumers can consult the
    # index via the optional ``event_class_index`` kwarg per ADR-0067
    # D361 (R039 mitigation per ADR-0060 D336). The renumbering from
    # Step 8 → Step 9 is the W8 D360 step insertion (NEW Step 8
    # before the previously-Step-8 DaemonRunner construction).
    # Pillar H Week 9 extension per ADR-0067 D362 — pass the daemon's
    # Ledger instance (NEW :attr:`DaemonRunner.ledger` field) so
    # :func:`_default_dispatch_for_stage` consumes the SAME Ledger
    # instance the observer is registered on; cross-tick observer
    # firing is preserved.
    runner = DaemonRunner(
        config=config,
        config_hash=config_hash,
        pid=pid,
        started_at_ts=started_at_ts,
        version=version,
        lifecycle_state="initializing",
        policy_state=initial_policy_state,
        event_class_index=event_class_idx,
        ledger=daemon_ledger,
        person_event_index=person_idx,
    )

    # Step 9.5: NEW per ADR-0067 D363 (W9 extension to ADR-0067 per
    # ADR-0060 D336) — register the daemon-index-age Prometheus
    # observable gauge so operators see the index freshness via the
    # ``outreach_factory_daemon_index_last_updated_timestamp`` gauge +
    # the per_daemon.yml dashboard panel #6 (which renders ``time() -
    # <gauge>`` as the index age; RED if > 60s — operator SLO signal
    # for invalidation stalls). The gauge consults
    # :attr:`runner.event_class_index._last_updated_at_ts` per scrape.
    # Operators omitting the production OTel SDK init paths
    # (test substrate at unit-test scope OR no-op
    # otel_meter_init_fn / prometheus_start_fn injection) get a
    # silent no-op — the gauge registration is best-effort + does
    # NOT prevent daemon startup if the OTel SDK is uninitialized.
    try:
        _observability.register_daemon_index_observable_gauge(
            get_last_updated_ts_fn=(
                lambda: runner.event_class_index._last_updated_at_ts
            ),
        )
    except Exception as _exc:  # noqa: BLE001 — best-effort registration
        # Silent at the daemon startup path — the gauge is operator-
        # observability scaffolding, NOT a daemon correctness contract.
        # Operators who care about the gauge see the registration
        # failure via the Pillar G OTel SDK's own diagnostics (the
        # OTel SDK logs to stderr on Meter construction failure per
        # the existing convention).
        print(
            f"WARNING: register_daemon_index_observable_gauge failed "
            f"({type(_exc).__name__}: {_exc}); the operator-visible "
            f"index-age gauge per ADR-0067 D363 will not surface on "
            f"the Prometheus exposition for this daemon process. "
            f"Re-run init_daemon after fixing the OTel SDK init OR "
            f"consult the per_daemon.yml panel 6 troubleshooting "
            f"section.",
            file=sys.stderr,
        )

    return runner


def attach_signal_handlers(
    runner: DaemonRunner,
    *,
    loop: Any | None = None,
    shutdown_fn: Callable[[str], None] | None = None,
    reload_fn: Callable[[], Any] | None = None,
) -> None:
    """Wire SIGTERM + SIGINT (graceful shutdown) + SIGHUP (policy
    reload) to the :class:`DaemonRunner` per ADR-0060 D335 invariants
    3 + 4 + ADR-0062 D341.

    **Pillar H Week 3 body.** Uses
    :meth:`asyncio.AbstractEventLoop.add_signal_handler` per the
    ADR-0060 D332 asyncio framework decision:

    * SIGTERM → :meth:`DaemonRunner.shutdown` with reason ``"sigterm"``.
    * SIGINT → :meth:`DaemonRunner.shutdown` with reason ``"sigint"``.
    * SIGHUP (iff ``config.policy_reload_signal == "SIGHUP"``) →
      :meth:`DaemonRunner.reload_policy`. Week 3 wired the handler with
      ``_reload_with_notimpl_swallow`` (NotImplementedError swallow at
      the Week 3 → Week 7 trajectory bridge); Pillar H Week 7 ships
      the body per ADR-0066 D356 + RENAMES the closure to
      ``_reload_default`` (the body actually runs; the swallow is no
      longer needed). Pillar H Week 7 follow-up P3-2 closure updates
      this docstring to name the Week 7 actual-body landing.

    The signal handlers run on the asyncio event loop's main thread
    per the asyncio convention; the actual shutdown / reload work runs
    on the same loop via the bound callable.

    Args:
        runner: the :class:`DaemonRunner` to attach signals to. The
            handler callbacks bind to :meth:`runner.shutdown` +
            :meth:`runner.reload_policy` at attach time.
        loop: test-only seam — the asyncio event loop. Default
            :func:`asyncio.get_running_loop()`; production callers
            (inside :meth:`DaemonRunner.run` at Week 5+) get the
            current loop; tests inject a substrate loop.
        shutdown_fn: test-only seam — the shutdown callable. Default
            :meth:`runner.shutdown`; tests inject spies to verify
            signal-to-callback wiring without invoking the actual
            shutdown body.
        reload_fn: test-only seam — the reload callable. Default
            ``_reload_default`` closure invoking
            :meth:`runner.reload_policy` (Pillar H Week 7 follow-up
            P3-2 closure — the W3 main commit's
            ``_reload_with_notimpl_swallow`` was RENAMED at Week 7 per
            ADR-0066 D356's body landing; the swallow is no longer
            needed because the body actually runs); tests inject spies.
    """
    if loop is None:
        loop = asyncio.get_running_loop()

    if shutdown_fn is None:
        shutdown_fn = runner.shutdown

    if reload_fn is None:
        # Pillar H Week 7 — the reload_policy body now lands per
        # ADR-0066 D356 + ADR-0060 D332's trajectory; the prior Week 3
        # ``_reload_with_notimpl_swallow`` closure (which caught
        # NotImplementedError + logged to stderr at the Week 3 → Week 7
        # trajectory bridge) is RENAMED to ``_reload_default`` + no
        # longer swallows (the body actually runs).
        #
        # The closure adapts the kwarg-less signal-handler signature
        # (asyncio's :meth:`add_signal_handler` invokes the callback
        # with no args) to :meth:`DaemonRunner.reload_policy`'s kwarg-
        # only signature; the return value (a :class:`PolicyReloadResult`)
        # is discarded by the signal handler — operators consume via
        # the ``policy_reloaded`` event in the ledger which the body's
        # ``emit_fn`` seam (default lazy-constructs
        # :class:`orchestrator.ledger.Ledger`) populates.
        def _reload_default() -> None:
            runner.reload_policy()
        reload_fn = _reload_default

    loop.add_signal_handler(signal.SIGTERM, lambda: shutdown_fn("sigterm"))
    loop.add_signal_handler(signal.SIGINT, lambda: shutdown_fn("sigint"))

    if runner.config.policy_reload_signal == "SIGHUP":
        loop.add_signal_handler(signal.SIGHUP, reload_fn)
