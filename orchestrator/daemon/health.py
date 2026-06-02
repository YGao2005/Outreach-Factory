"""Pillar H Week 1 + Week 4 + Week 4 follow-up + Week 5 + Week 5 follow-up
— daemon health endpoint primitive (per ADR-0060 D334 + D335 invariant 3;
Week 1 follow-up adds the ``runner: "DaemonRunner"`` type hint via
:data:`TYPE_CHECKING` import per per-week-reviewer P3-7 closure; Week 2 +
Week 2 follow-up + Week 3 did NOT materially modify this module; Week 3
follow-up extends module docstring naming each per-week ADR per per-week-
reviewer P3-5 closure; Week 5 + Week 5 follow-up did NOT materially modify
this module — but the W3 follow-up P3-5 closure's discipline-scope
extension to materially-unchanged modules in the same per-pillar package
+ the W5 follow-up P3-9 closure require this docstring to name Week 5 +
Week 5 follow-up so operators reading any single file in the per-pillar
package see the per-week trajectory; Week 4 lands :func:`serve_health_endpoint`
body wiring asyncio-
aiohttp HTTP server on ``127.0.0.1:8080`` per R036 + ``health_probe``
rate-limit per R038 + :func:`build_health_probe_payload` emit-shape
factory per ADR-0063 D345-D348 + ADR-0010 D17 + the Pillar E
:data:`EMITTED_BY` precedent + the Pillar H Week 3 follow-up P2-1
closure; Week 4 follow-up closes per-week-reviewer P2-1
framework-neutrality text drift at ADR-0063 D348 + the body's lazy-
import comment — the seam kwargs ``emit_fn`` + ``now_fn`` + ``bind_addr``
substitute BACKENDS (ledger + clock + IP), NOT HTTP server choice
(operators wanting alternative HTTP servers MUST fork the function
body) — the THIRD ADR-vs-actual-impl drift caught by the per-week-
reviewer's cross-pillar back-audit discipline (W2 P3-8 OTel Resource +
W3 P2-1 ``_emitted_by`` + W4 P2-1 framework-neutrality text); P2-2
``_compute_health_status`` ValueError swallow vs
:meth:`DaemonRunner.shutdown` refuse-loud asymmetry documented at the
docstring + pinned via regression-barrier test; P3-3/P3-4/P3-5 Week 4
placeholder semantics documented at field docstrings + pinned via
trajectory regression-barrier tests (``policy_loaded`` + Week 7+;
``last_reconcile_pass_age_seconds`` + Week 7+; ``outcome="degraded"``
unreachable through :func:`_compute_health_status` + Week 6+); P3-6
``bind_addr`` refuse-loud at boundary via :func:`ipaddress.ip_address`
per Pillar H Week 2 follow-up P2-1 next-tier-invariant-field
refuse-loud precedent; P3-8 Pillar I per-tenant per-container
``_handle_health`` closure-captures-runner trajectory documented; P3-9
:func:`build_health_probe_payload` ``remote_addr`` arg description
extended naming the Pillar I reverse-proxy ``X-Forwarded-For``
trajectory; P3-10 :func:`serve_health_endpoint` return type hint
narrowed via :data:`TYPE_CHECKING` import of
:class:`aiohttp.web.AppRunner`; NEW-1
:class:`HealthStatus.__post_init__` validates ``outcome`` +
``lifecycle_state`` in their closed-sets per defense-in-depth at the
JSON-serialized HTTP body boundary; NEW-2 Content-Type
``application/json`` regression-barrier test; NEW-3 Pillar I middleware
trajectory documented at :func:`serve_health_endpoint` docstring).

The Pillar H daemon serves a HTTP health endpoint on the configured
port (:attr:`DaemonConfig.health_port`, default 8080) that returns the
daemon's lifecycle state per :data:`DAEMON_LIFECYCLE_STATES` +
operator-readable diagnostic context. The endpoint follows the
Kubernetes readiness-probe convention:

* HTTP 200 + JSON body iff :attr:`HealthStatus.outcome != "unhealthy"`
  (the ``"ok"`` / ``"degraded"`` cases — daemon ``ready`` + ledger
  reachable + policy loaded).
* HTTP 503 + JSON body iff :attr:`HealthStatus.outcome == "unhealthy"`
  (the ``"initializing"`` / ``"draining"`` / ``"stopped"`` lifecycle
  states OR ledger unreachable OR policy load failed).

The endpoint binds to ``127.0.0.1`` by default per R036 (Pillar G
Week 4's security-by-default Prometheus exposition pattern per
ADR-0053 D291) — operators wanting cross-machine probes wire a
reverse proxy OR pass ``bind_addr="0.0.0.0"`` deliberately.

Each probe emits a ``health_probe`` ledger event per
:data:`DAEMON_NEW_EVENT_CLASSES` rate-limited at
:attr:`DaemonConfig.health_probe_rate_limit_seconds` per R038
mitigation (high-frequency k8s probes would inflate the ledger
without the rate-limit; default 30s caps a 10s-cadence probe at
~2880 events/day per single-tenant operator within the daemon's
diagnostic budget).

The Week 2 follow-up P2-1 closure validates
:attr:`DaemonConfig.health_probe_rate_limit_seconds >= 0` at
:func:`_validate_config`; that refuse-loud rule binds Week 4's
rate-limit arithmetic at :func:`serve_health_endpoint` body.

The Week 4 body uses **operator-deliberate test seam kwargs** per the
Pillar G TEST-ONLY convention + the Pillar H Week 2 / Week 3
precedent — production callers pass `port` + `runner`; tests inject
spies via `emit_fn` + `now_fn` + the operator-deliberate `bind_addr`.

**Framework-neutrality contract** per Pillar H Week 4 follow-up P2-1
closure (two-tiered):

1. **Operator-deliberate seam kwargs** (``emit_fn`` + ``now_fn`` +
   ``bind_addr``) — operators substitute alternative ledger backends +
   clock sources + bind addresses WITHOUT replacing the function body.
   The HTTP server choice (aiohttp) is NOT swappable via these seams.
2. **Operator fork** — operators wanting alternative HTTP servers
   (Tornado / FastAPI / Starlette / etc.) MUST replace the entire
   :func:`serve_health_endpoint` function body. The aiohttp dependency
   at ``requirements.txt`` is the v1 default; the dependency upper
   bound at ``aiohttp>=3.9,<4`` per Pillar H Week 4 follow-up P3-7
   closure preserves operator dependency-budget stability.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    # Forward reference import for the runner type hint on
    # :func:`serve_health_endpoint`. Pillar H Week 1 follow-up P3-7
    # closure — the circular-import workaround is the standard Python
    # pattern (the body imports DaemonRunner at runtime; the signature
    # uses the string forward-reference cost-free via
    # ``from __future__ import annotations``).
    from orchestrator.daemon.runner import DaemonRunner
    # Pillar H Week 4 follow-up P3-10 closure — narrow the
    # :func:`serve_health_endpoint` return type from ``Any`` to
    # :class:`aiohttp.web.AppRunner` via :data:`TYPE_CHECKING` import
    # (the body lazy-imports aiohttp.web per the framework-neutrality
    # contract; the signature uses the string forward-reference).
    from aiohttp.web import AppRunner


# ---------------------------------------------------------------------------
# Closed-sets — R031-shape regression-barrier per ADR-0060 D331
# ---------------------------------------------------------------------------


#: The THREE health probe outcomes per ADR-0060 D334.
#:
#: * ``"ok"`` — daemon in ``"ready"`` state + ledger reachable + policy
#:   loaded. HTTP 200.
#: * ``"degraded"`` — daemon in ``"ready"`` state but at least one
#:   degraded indicator (e.g., reconcile pass last-run-age beyond
#:   threshold; OTel exporter unreachable; per-stage worker pool
#:   saturated). HTTP 200 (k8s readiness probe permits traffic; the
#:   degraded state surfaces to the operator via the Pillar G overview
#:   dashboard's SLO violation panel + the per-Person panel's per-
#:   stage drift).
#: * ``"unhealthy"`` — daemon in ``"initializing"`` | ``"draining"`` |
#:   ``"stopped"`` state, OR ledger unreachable, OR policy load failed.
#:   HTTP 503 (k8s readiness probe blocks traffic).
#:
#: **Week 6+ trajectory per Pillar H Week 4 follow-up P3-5 closure** —
#: the ``"degraded"`` element is UNREACHABLE through
#: :func:`_compute_health_status` at Week 4 (the helper returns
#: ``"ok"`` or ``"unhealthy"`` only). The closed-set element STILL
#: appears here + :class:`HealthStatus` accepts it through direct
#: construction + :func:`build_health_probe_payload` accepts it; Week
#: 6+ extends :func:`_compute_health_status` with the actual
#: degraded-indicator computation per the per-stage worker pool
#: saturation signal. The regression-barrier test
#: ``TestComputeHealthStatus::test_degraded_outcome_unreachable_at_week_4_per_week_6_trajectory``
#: pins the Week 4 contract until Week 6+ deliberately extends.
HEALTH_PROBE_OUTCOMES: frozenset[str] = frozenset({
    "ok",
    "degraded",
    "unhealthy",
})


# ---------------------------------------------------------------------------
# Dataclasses — Week 1 shape only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthStatus:
    """The readiness probe's response payload per ADR-0060 D334.

    The JSON-serialized version of this dataclass is the HTTP body of
    every health endpoint response. Operators consuming via curl /
    k8s readiness probes / Grafana-as-code synthetic monitors see
    structured diagnostic context.

    Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 holds
    — the payload contains COUNTS + STATES + timestamps + version,
    NEVER ``person_id`` / body content / source_list. The
    ``last_reconcile_pass_age_seconds`` is the operator-visible signal
    for the per-pass cadence concern.

    Fields:

    * ``outcome`` — one of :data:`HEALTH_PROBE_OUTCOMES`. The HTTP
      status code derives from this (``"ok"`` / ``"degraded"`` → 200;
      ``"unhealthy"`` → 503).
    * ``lifecycle_state`` — one of
      :data:`DAEMON_LIFECYCLE_STATES`.
    * ``daemon_pid`` — daemon's OS PID.
    * ``daemon_version`` — daemon version string.
    * ``uptime_seconds`` — seconds since :attr:`DaemonRunner.started_at_ts`.
    * ``config_hash`` — operator-visible identity of the config
      (matches the ``daemon_started`` event's payload).
    * ``ledger_reachable`` — True iff the ledger directory exists +
      the most recent ``events-YYYY-MM-DD.jsonl`` file is writable.
    * ``policy_loaded`` — True iff Pillar A's policy engine has a
      live in-memory representation (not the YAML file existence —
      the per-rule validation pass succeeded at startup or at the
      most recent SIGHUP). **Week 4 placeholder per Pillar H Week 4
      follow-up P3-3 closure** — :func:`_compute_health_status` at
      Week 4 returns ``True iff lifecycle_state == "ready"``; Week 7+
      extends with the actual policy state inspection per the
      SIGHUP-driven :meth:`DaemonRunner.reload_policy` body. The
      regression-barrier test
      ``test_policy_loaded_is_lifecycle_state_proxy_at_week_4_per_week_7_trajectory``
      pins the Week 4 contract.
    * ``in_flight_task_count`` — current per-stage worker pool
      occupancy.
    * ``last_reconcile_pass_age_seconds`` — seconds since the last
      reconcile pass completed; operators tune k8s probes to flag
      ``"degraded"`` when this exceeds the per-pass cadence + 2×
      jitter. **Week 4 placeholder per Pillar H Week 4 follow-up
      P3-4 closure** — :func:`_compute_health_status` at Week 4
      hard-codes ``0``; Week 7+ wires the reconcile cadence (Pass A
      through O per the existing convention). The regression-barrier
      test
      ``test_last_reconcile_pass_age_seconds_is_zero_at_week_4_per_week_7_trajectory``
      pins the Week 4 contract.
    * ``ts`` — ISO-8601 UTC; the probe timestamp.

    The dataclass is FROZEN; lifecycle transitions produce a new
    :class:`HealthStatus` instance.

    **Construction-time validation per Pillar H Week 4 follow-up NEW-1
    closure** — :meth:`__post_init__` refuses-loud on ``outcome`` not
    in :data:`HEALTH_PROBE_OUTCOMES` OR ``lifecycle_state`` not in
    :data:`orchestrator.daemon.runner.DAEMON_LIFECYCLE_STATES`. The
    dataclass is serialized into the operator-facing HTTP body, so
    construction-time defense-in-depth catches direct
    ``HealthStatus(...)`` construction that bypasses the
    :func:`build_health_probe_payload` factory's own validation.
    """

    outcome: str
    lifecycle_state: str
    daemon_pid: int
    daemon_version: str
    uptime_seconds: int
    config_hash: str
    ledger_reachable: bool
    policy_loaded: bool
    in_flight_task_count: int
    last_reconcile_pass_age_seconds: int
    ts: str

    def __post_init__(self) -> None:
        # Pillar H Week 4 follow-up NEW-1 closure — refuse-loud on
        # closed-set membership at construction time per the JSON-
        # serialized HTTP body operator-facing surface defense-in-depth
        # convention.
        if self.outcome not in HEALTH_PROBE_OUTCOMES:
            raise ValueError(
                f"HealthStatus.outcome not in HEALTH_PROBE_OUTCOMES "
                f"({sorted(HEALTH_PROBE_OUTCOMES)!r}): {self.outcome!r}"
            )
        # Lazy import to avoid module-load-time circular import per the
        # health.py / runner.py framework convention.
        from orchestrator.daemon.runner import (  # noqa: PLC0415
            DAEMON_LIFECYCLE_STATES,
        )
        if self.lifecycle_state not in DAEMON_LIFECYCLE_STATES:
            raise ValueError(
                f"HealthStatus.lifecycle_state not in "
                f"DAEMON_LIFECYCLE_STATES "
                f"({sorted(DAEMON_LIFECYCLE_STATES)!r}): "
                f"{self.lifecycle_state!r}"
            )


# ---------------------------------------------------------------------------
# Pillar H Week 4 — `build_health_probe_payload` emit-shape factory
# (per ADR-0063 D346 + ADR-0010 D17 + Pillar H Week 3 follow-up P2-1)
# ---------------------------------------------------------------------------


def build_health_probe_payload(
    pid: int,
    outcome: str,
    lifecycle_state: str,
    remote_addr: str,
) -> dict[str, Any]:
    """Build the emit-shape payload for the ``health_probe`` event per
    ADR-0063 D346 + ADR-0010 D17 + the Pillar H Week 3 follow-up P2-1
    closure.

    Pillar H Week 4 ships the factory + the actual emit (at
    :func:`serve_health_endpoint`'s rate-limited handler). The factory
    shape mirrors the Pillar G ``build_*_payload`` convention per
    ADR-0010 D17 + the Pillar H Week 2 :func:`build_daemon_started_payload`
    + Week 3 :func:`build_daemon_stopping_payload` +
    :func:`build_daemon_stopped_payload` precedents — raw-primitive
    factory with refuse-loud at construction time per the Pillar G
    :func:`discovery_dedup.build_discovery_dedup_hit_payload` +
    Pillar H Week 2 follow-up P2-2 closure conventions.

    Args:
        pid: the daemon process's OS PID (must be ``> 0``).
        outcome: one of :data:`HEALTH_PROBE_OUTCOMES` (``"ok"`` |
            ``"degraded"`` | ``"unhealthy"``).
        lifecycle_state: one of
            :data:`orchestrator.daemon.runner.DAEMON_LIFECYCLE_STATES`
            (``"initializing"`` | ``"ready"`` | ``"draining"`` |
            ``"stopped"``).
        remote_addr: the IP address of the requesting client
            (operator-visible for filtering by source IP); MUST be
            non-empty. **Pillar I reverse-proxy trajectory per Week
            4 follow-up P3-9 closure** — at Pillar H Week 4 + v1
            single-tenant deployments the caller passes
            ``aiohttp.web.Request.remote`` (TCP-level remote address);
            for Pillar I reverse-proxy deployments with operator-
            deliberate ``bind_addr="0.0.0.0"``, ``request.remote``
            shows the proxy IP — Pillar I callers should extract
            ``X-Forwarded-For`` at the call site (the
            :func:`_handle_health` closure in
            :func:`serve_health_endpoint` is the v1 caller).

    Returns:
        A dict with the canonical ``health_probe`` event payload
        (pid + outcome + lifecycle_state + remote_addr +
        ``_emitted_by="daemon"``). The factory stamps ``_emitted_by``
        at the factory boundary per the Pillar H Week 3 follow-up
        P2-1 closure (the daemon module-level :data:`EMITTED_BY`
        constant mirroring Pillar E
        :data:`orchestrator.tier_assignment.EMITTED_BY` +
        :data:`orchestrator.discovery_lineage.EMITTED_BY` precedent).
        The ``type`` field is set by the caller (the emitter writes
        ``{"type": "health_probe", **build_..._payload(...)}``) and
        the ``ts`` field is auto-filled by :meth:`Ledger.append` via
        its ``setdefault("ts")`` contract. The ``channel`` field is
        OMITTED per ADR-0014 D33 (daemon lifecycle events tenant-
        process-scoped, not per-channel).

    Raises:
        :exc:`ValueError`: on invalid input per the Pillar H Week 2
            follow-up P2-2 closure raw-primitive factory convention.
            ``pid`` MUST be ``> 0`` (POSIX OS PIDs are positive);
            ``outcome`` MUST be in :data:`HEALTH_PROBE_OUTCOMES`;
            ``lifecycle_state`` MUST be in
            :data:`orchestrator.daemon.runner.DAEMON_LIFECYCLE_STATES`;
            ``remote_addr`` MUST be non-empty.
    """
    # Lazy imports to avoid module-load-time circular import (runner
    # imports nothing from health.py at module load time; the lazy
    # import here keeps the import graph minimal).
    from orchestrator.daemon.runner import (  # noqa: PLC0415
        DAEMON_LIFECYCLE_STATES,
        EMITTED_BY,
    )

    if pid <= 0:
        raise ValueError(
            f"build_health_probe_payload requires pid > 0; got {pid!r}. "
            f"OS PIDs are positive integers per POSIX."
        )
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
        raise ValueError(
            "build_health_probe_payload requires non-empty remote_addr "
            "(operator-visible source IP filter)."
        )
    return {
        "pid": pid,
        "outcome": outcome,
        "lifecycle_state": lifecycle_state,
        "remote_addr": remote_addr,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# Pillar H Week 4 — `_compute_health_status` helper
# ---------------------------------------------------------------------------


def _compute_health_status(
    runner: "DaemonRunner",
    now: datetime,
) -> HealthStatus:
    """Compute the current :class:`HealthStatus` from the
    :class:`DaemonRunner` state + the current UTC datetime.

    Per ADR-0063 D345 — the ``outcome`` field derives from the
    lifecycle state + the ledger + policy indicators:

    * ``"ok"`` — ``lifecycle_state == "ready"`` AND ledger reachable
      AND policy loaded.
    * ``"degraded"`` — ``lifecycle_state == "ready"`` BUT at least one
      degraded indicator (Week 4 returns ``"ok"`` when ready; Week 6+
      extends with degraded-indicator computation per the per-stage
      worker pool saturation signal).
    * ``"unhealthy"`` — ``lifecycle_state != "ready"`` OR ledger
      unreachable OR policy load failed.

    Args:
        runner: the :class:`DaemonRunner` to query.
        now: the current UTC datetime (for uptime computation +
            timestamp).

    Returns:
        A :class:`HealthStatus` with all 11 fields populated.

    **Malformed ``started_at_ts`` posture per Pillar H Week 4 follow-up
    P2-2 closure** — :func:`_compute_health_status` silently catches
    :exc:`ValueError` on malformed ``runner.started_at_ts`` and returns
    ``uptime_seconds=0`` (the health endpoint is the diagnostic surface
    OPERATORS USE TO DETECT this kind of issue; refusing-loud would
    defeat its purpose). This is the structural OPPOSITE of
    :meth:`DaemonRunner.shutdown` which refuses-loud upfront on the
    SAME malformed input per Pillar H Week 3 follow-up P2-2 closure.
    Both behaviors are INTENTIONAL and ASYMMETRIC — the shutdown body
    is an operator-deliberate state mutation that MUST refuse-loud on
    invariant violation; the health endpoint is the read-only
    diagnostic that MUST stay reachable. The regression-barrier test
    ``TestComputeHealthStatus::test_malformed_started_at_ts_surfaces_uptime_zero_NOT_raises``
    pins the asymmetry at test time so a future refactor does NOT
    accidentally homogenize the two paths.

    **Week 4 placeholder semantics per Pillar H Week 4 follow-up
    P3-3 / P3-4 / P3-5 closures** —

    * ``policy_loaded`` returns ``runner.lifecycle_state == "ready"``
      at Week 4 (Week 7+ wires the actual policy state inspection per
      the SIGHUP-driven :meth:`DaemonRunner.reload_policy` body).
    * ``last_reconcile_pass_age_seconds`` returns ``0`` at Week 4
      (Week 7+ wires the reconcile cadence per Pass A through O).
    * ``in_flight_task_count`` returns ``0`` at Week 4 (Week 5+
      wires the per-stage worker pool count).
    * ``outcome="degraded"`` is UNREACHABLE through this helper at
      Week 4 (helper returns ``"ok"`` or ``"unhealthy"`` only). Week
      6+ extends with the degraded-indicator computation per the
      per-stage worker pool saturation signal.

    Regression-barrier tests pin each placeholder so a future
    extension surfaces concurrent test updates.
    """
    ledger_reachable = runner.config.ledger_dir.exists()
    # Week 4: policy_loaded is True iff lifecycle_state is "ready"
    # (Week 7+ extends with the actual policy state inspection per
    # the SIGHUP-driven reload_policy body).
    policy_loaded = runner.lifecycle_state == "ready"

    if (
        runner.lifecycle_state == "ready"
        and ledger_reachable
        and policy_loaded
    ):
        outcome = "ok"
    else:
        outcome = "unhealthy"

    # Compute uptime via the same strptime convention as
    # DaemonRunner.shutdown (per Pillar H Week 3 follow-up P2-2 +
    # ADR-0061 D339 + _utc_iso_now contract).
    try:
        started_at = datetime.strptime(
            runner.started_at_ts, "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=timezone.utc)
        uptime_seconds = int((now - started_at).total_seconds())
    except ValueError:
        # Malformed started_at_ts — surface as 0 (NOT a crash; the
        # health endpoint is the diagnostic surface OPERATORS USE TO
        # DETECT this kind of issue; refusing-loud would defeat its
        # purpose). The DaemonRunner.shutdown body refuses-loud per
        # the Week 3 follow-up P2-2 closure when the operator initiates
        # shutdown; the health endpoint is the read-only diagnostic.
        uptime_seconds = 0

    ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    return HealthStatus(
        outcome=outcome,
        lifecycle_state=runner.lifecycle_state,
        daemon_pid=runner.pid,
        daemon_version=runner.version,
        uptime_seconds=uptime_seconds,
        config_hash=runner.config_hash,
        ledger_reachable=ledger_reachable,
        policy_loaded=policy_loaded,
        in_flight_task_count=0,  # Week 5+ wires per-stage pool count.
        last_reconcile_pass_age_seconds=0,  # Week 7+ wires reconcile cadence.
        ts=ts,
    )


# ---------------------------------------------------------------------------
# Pillar H Week 4 — `serve_health_endpoint` body
# ---------------------------------------------------------------------------


async def serve_health_endpoint(
    port: int,
    *,
    runner: "DaemonRunner",
    bind_addr: str = "127.0.0.1",
    emit_fn: Callable[[dict], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> "AppRunner":
    """Serve the HTTP health endpoint per ADR-0060 D334 + ADR-0063 D345.

    Pillar H Week 4 body wiring an asyncio-aiohttp HTTP server on
    ``{bind_addr}:{port}`` (default ``127.0.0.1:8080`` per R036
    security-by-default).

    1. Validate ``bind_addr`` parses as IP per Pillar H Week 4
       follow-up P3-6 closure (refuse-loud at boundary; invalid IP
       would raise :exc:`OSError` mid-startup AFTER OTel set-once
       burnt at Week 5+).
    2. Bind a HTTP server to ``{bind_addr}:<port>`` (default
       ``127.0.0.1`` per R036; operators wanting cross-machine probes
       MUST pass ``bind_addr="0.0.0.0"`` deliberately OR wire a reverse
       proxy).
    3. On each ``GET /health`` request, compute the current
       :class:`HealthStatus` from the :class:`DaemonRunner` +
       JSON-serialize + return HTTP 200 (outcome != "unhealthy") OR
       HTTP 503 (outcome == "unhealthy") per the k8s readiness-probe
       convention.
    4. Rate-limit the ``health_probe`` event emission at
       :attr:`DaemonConfig.health_probe_rate_limit_seconds` per R038
       (at-most-ONE event per N seconds; operators wanting per-request
       emits set to 0). The rate-limit state is per-server closure-
       scoped (NOT per-instance class attribute because the runner is
       frozen-dataclass; NOT module-level because Pillar I per-tenant
       fan-out would share state across tenants; the closure is the
       per-tenant-isolation-correct shape per ADR-0063 D346).

    Args:
        port: the TCP port to bind to.
        runner: the :class:`DaemonRunner` to query for health state.
        bind_addr: the IP address to bind to. Default ``"127.0.0.1"``
            per R036 (security-by-default). Operators wanting
            cross-machine probes pass ``"0.0.0.0"`` deliberately.
            Pillar H Week 4 follow-up P3-6 closure — refuse-loud at
            boundary via :func:`ipaddress.ip_address` (raises
            :exc:`ValueError` on invalid IP).
        emit_fn: test-only seam — appends a ``health_probe`` event to
            the ledger. Default lazy-constructs
            :class:`orchestrator.ledger.Ledger` from
            ``runner.config.ledger_dir`` + invokes
            :meth:`Ledger.append`. Tests inject spies that record
            the emit payloads + verify the rate-limit behavior.
        now_fn: test-only seam — returns the current UTC datetime.
            Default :func:`datetime.now` with timezone.utc. Tests
            inject deterministic clocks to verify rate-limit
            arithmetic + uptime computation are precise.

    Returns:
        The :class:`aiohttp.web.AppRunner` instance — the production
        caller (inside :meth:`DaemonRunner.run` at Week 5+) awaits
        this + retains the reference to call
        :meth:`AppRunner.cleanup` at graceful shutdown.
        :meth:`AppRunner.cleanup` waits for in-flight requests to
        complete before releasing the port (aiohttp's documented
        graceful-shutdown contract).

    Raises:
        :exc:`ValueError`: on invalid ``bind_addr`` (not a parseable
            IP address) per Pillar H Week 4 follow-up P3-6 closure.
        :exc:`RuntimeError`: on aiohttp startup failure (port in
            use, etc.). Operators see the daemon refuse-loud at
            startup per the framework convention per I5 + ADR-0001
            D2.

    **Framework-neutrality contract per Pillar H Week 4 follow-up
    P2-1 closure** (the THIRD ADR-vs-actual-impl drift caught in
    Pillar H by the cross-pillar back-audit discipline). Two-tiered:

    1. **Operator-deliberate seam kwargs** (``emit_fn`` + ``now_fn`` +
       ``bind_addr``) substitute BACKENDS (ledger backend + clock
       source + bind address) WITHOUT replacing the function body.
       Operators wanting alternative ledger backends (e.g., Kafka)
       pass ``emit_fn``; alternative clock sources pass ``now_fn``;
       alternative bind addresses pass ``bind_addr``. The HTTP server
       choice (aiohttp) is NOT swappable via these seams.
    2. **Operator fork** — operators wanting alternative HTTP servers
       (Tornado / FastAPI / Starlette / etc.) MUST replace the
       entire :func:`serve_health_endpoint` function body. The
       aiohttp dependency at ``requirements.txt`` is the v1 default;
       the upper bound at ``aiohttp>=3.9,<4`` per Pillar H Week 4
       follow-up P3-7 closure preserves dependency-budget stability.

    **Pillar I per-tenant trajectory per Pillar H Week 4 follow-up
    P3-8 closure** — the inner :func:`_handle_health` closure
    captures ``runner`` by reference. Pillar I per-tenant fan-out
    instantiates ONE :func:`serve_health_endpoint` per tenant
    container per ADR-0060 D335 invariant 1 (one daemon process per
    tenant); the closure captures the per-container runner cleanly.
    Operators wanting to swap runners (e.g., on tenant pause/resume)
    MUST :meth:`AppRunner.cleanup` the existing server + re-invoke
    :func:`serve_health_endpoint` with the new runner.

    **Pillar I middleware trajectory per Pillar H Week 4 follow-up
    NEW-3 closure** — :class:`aiohttp.web.Application` instantiated
    here has NO middlewares (v1 single-tenant + ``127.0.0.1`` bind
    default). Pillar I operators wanting middleware (auth /
    structured request logging / per-route rate-limiting at the HTTP
    boundary) MUST fork the function body to pass
    ``web.Application(middlewares=[...])``.
    """
    # Pillar H Week 4 follow-up P3-6 closure — refuse-loud at boundary
    # for invalid bind_addr. Invalid IP would raise OSError mid-startup
    # AFTER OTel set-once burnt at Week 5+ (when init_daemon →
    # serve_health_endpoint is wired sequentially); the Week 2 follow-up
    # P2-1 closure pattern (next-tier invariant-bearing field
    # refuse-loud at _validate_config) extends here to the boundary.
    import ipaddress  # noqa: PLC0415
    ipaddress.ip_address(bind_addr)  # raises ValueError on invalid

    # Lazy import — aiohttp is the Week 4 NEW dependency per ADR-0063
    # D348. The framework-neutrality contract is two-tiered (per
    # Pillar H Week 4 follow-up P2-1 closure): (a) operator-deliberate
    # seam kwargs `emit_fn` + `now_fn` + `bind_addr` substitute
    # BACKENDS (ledger + clock + IP) NOT the HTTP server choice;
    # (b) operators wanting alternative HTTP servers MUST fork this
    # function body (the aiohttp dependency at requirements.txt is
    # the v1 default; the upper bound `aiohttp>=3.9,<4` per W4 P3-7
    # closure preserves dependency-budget stability).
    from aiohttp import web  # noqa: PLC0415

    if emit_fn is None:
        # Lazy import + lazy ledger construction per the Pillar H
        # Week 3 DaemonRunner.shutdown precedent.
        from orchestrator.ledger import Ledger  # noqa: PLC0415
        ledger = Ledger(runner.config.ledger_dir)
        emit_fn = ledger.append
    if now_fn is None:
        now_fn = lambda: datetime.now(tz=timezone.utc)  # noqa: E731

    # Per-server rate-limit state (closure-scoped per ADR-0063 D346).
    # Single-cell mutable container; the closure mutates [0] on emit.
    last_emit_ts: list[datetime | None] = [None]

    async def _handle_health(request: web.Request) -> web.Response:
        now = now_fn()
        status = _compute_health_status(runner, now)

        # Rate-limit per R038 mitigation per ADR-0063 D346.
        rate_limit_seconds = runner.config.health_probe_rate_limit_seconds
        should_emit = (
            last_emit_ts[0] is None
            or (now - last_emit_ts[0]).total_seconds() >= rate_limit_seconds
        )
        if should_emit:
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

        # k8s readiness-probe convention per ADR-0063 D345:
        # outcome != "unhealthy" → 200 (ok/degraded permit traffic);
        # outcome == "unhealthy" → 503 (blocks traffic).
        http_status = 200 if status.outcome != "unhealthy" else 503
        return web.json_response(
            dataclasses.asdict(status),
            status=http_status,
        )

    app = web.Application()
    app.router.add_get("/health", _handle_health)
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    site = web.TCPSite(app_runner, bind_addr, port)
    await site.start()
    return app_runner
