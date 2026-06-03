"""Daemon package: the long-running supervisor for the outreach pipeline.

Operations tier (advanced). An adopter who only sends cold email does not need
this; it is for running the pipeline continuously as a service.

Modules:
  runner   the lifecycle state machine, crash recovery, policy hot-reload, and
           the in-memory ledger indexes (see runner.py).
  health   the liveness/health endpoint (see health.py).

The package's public surface is re-exported below via __all__. Design history
is in ADR-0060 through ADR-0068.
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
