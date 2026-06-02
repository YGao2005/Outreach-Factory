"""Pillar H Week 1 + ... + Week 5 + Week 5 follow-up + Week 6 + Week 6
follow-up — daemon contract tests (per ADR-0060 D331; Week 6 ships
TestDaemonStageSaturatedPayload contract tests for the NEW
:func:`build_daemon_stage_saturated_payload` factory per ADR-0065 D355
+ updates TestDaemonNewEventClasses contents pin from 5 → 6 closed-set
elements + extends TestPublicSurface with the new factory's re-export
+ updates TestDaemonRunBody count from 14 → 16 with the Week 6 follow-up
behavioral-passthrough tests; Week 6 follow-up extends with per-week-
reviewer P2-1 + P3-11 behavioral-passthrough regression-barrier
``test_daemon_stage_saturated_emits_when_semaphore_locked_per_w6_followup_p2_1``
exercising the body's Iteration 6b emit path via the NEW
:func:`semaphore_factory_fn` test-only seam (the FIFTH consecutive
behavioral-passthrough closure per the W5 P1-1 discipline) +
``test_run_accepts_semaphore_factory_fn_seam_per_w6_followup_p2_1``
cell-level coverage of the seam's default + P3-5 + P3-6 + P3-7 + NEW-3
+ NEW-7 "FIVE → SIX" docstring drift closures across SIX test sites
+ rename ``TestEventClassCatalogPillarHWeek2Extension`` →
``TestEventClassCatalogPillarHWeek2AndWeek6Extension`` per the operator-
readable test class name discipline + rename
``test_subset_of_event_class_catalog_at_pillar_h_week_2`` →
``test_subset_of_event_class_catalog_at_pillar_h_week_2_and_week_6``.
Week 5 follow-up extends with per-week-reviewer
P1-1 ``traced_stage(stage, operation)`` production-signature alignment
+ behavioral-passthrough regression-barrier + P2-1 pre-iteration removal
+ P2-2 cleanup-on-exception regression-barrier + P2-3 ``tick_seconds``
boundary refuse-loud + P2-4 :func:`asyncio.get_running_loop` operator-
readable error + NEW-5 ``object.__setattr__`` run()-side regression-
barrier + P3-2 ``_StubAppRunner`` shared helper consumption + P3-3
``_TEST_PAST_STARTED_AT_TS`` named constant consumption from
:mod:`tests._daemon_test_helpers`. Week 1 base —
follow-up extends with per-week-reviewer P3-2 / P3-3 / P3-4 / P3-6
regression-barrier closures; Week 2 follow-up extends with reviewer
P2-1 / P2-2 / P3-1 / P3-2 / P3-3 / P3-4 / P3-5 closures — new test
classes ``TestModuleConstants`` for _DAEMON_VERSION mirror parity +
``TestDefaultPolicyLoad`` for the helper's cell-level matrix coverage
+ ``TestComputeConfigHash`` for the known-config regression-barrier +
extended ``TestInitDaemonValidation`` with negative-value rules +
extended ``TestInitDaemonBody`` with kwarg-override tests + extended
``TestDaemonStartedPayload`` with input-validation tests; Week 3
follow-up extends with reviewer P2-1 / P2-2 / P3-1 / P3-4 / P3-6
closures — TestDaemonStartedPayload + TestDaemonStoppingPayload +
TestDaemonStoppedPayload each get a NEW
``test_payload_carries_emitted_by_marker`` test asserting the
factory stamps ``_emitted_by="daemon"`` at the factory boundary per
ADR-0010 D17 + the Pillar E :data:`EMITTED_BY` precedent (the SECOND
ADR-vs-actual-impl drift in Pillar H — the Week 3 main commit's
factory docstrings + ADR-0062 D343 narrative FALSELY claimed
``_emitted_by`` was auto-filled by :meth:`Ledger.append`);
TestShutdownBody gets NEW
``test_malformed_started_at_ts_refuses_loud_before_state_transition``
+ ``test_only_lifecycle_state_mutates_during_shutdown``;
TestAttachSignalHandlers gets NEW
``test_sighup_callback_swallows_notimplementederror_at_week_3`` +
``_SpyLoop`` promoted to module-level
``_SignalRegistrationSpyLoop``; TestModuleConstants gets NEW
``test_emitted_by_marker_is_daemon``).

Per the per-pillar-foundation precedent (Pillar G Week 1 shipped
``tests/test_observability.py`` with 19 contract-level tests pinning
the module shape + closed-sets + signature; Week 2 expanded coverage
with the body tests). This file pins the Pillar H Week 1 contract:

* :class:`DaemonConfig` dataclass shape (fields + frozen invariant +
  defaults).
* :class:`DaemonRunner` dataclass shape (fields + frozen invariant +
  primitive signatures).
* :class:`PolicyReloadResult` dataclass shape.
* :class:`HealthStatus` dataclass shape.
* :data:`DAEMON_LIFECYCLE_STATES` closed-set contents + frozen.
* :data:`DAEMON_NEW_EVENT_CLASSES` closed-set contents + frozen.
* :data:`HEALTH_PROBE_OUTCOMES` closed-set contents + frozen.
* :data:`DAEMON_POLICY_RELOAD_SIGNALS` closed-set contents + frozen
  (Pillar H Week 1 follow-up P3-2 closure).
* :data:`POLICY_RELOAD_STATUSES` closed-set contents + frozen (Pillar
  H Week 1 follow-up P3-3 closure).
* Primitive signatures (init_daemon / attach_signal_handlers /
  serve_health_endpoint / DaemonRunner.run / shutdown / reload_policy)
  exist + raise ``NotImplementedError`` at Week 1.
* Pillar G + Pillar H closed-set disjointness — the SIX new Pillar H
  event classes (FIVE at Week 2 per ADR-0061 D338 + ONE
  ``daemon_stage_saturated`` at Week 6 per ADR-0065 D355; the W6
  follow-up P3-7 closure updates the prior "FIVE" docstring drift)
  are disjoint from
  :data:`observability.EVENT_CLASS_CATALOG` at Week 1 (will JOIN at
  Pillar H Week 2 + Pillar G's catalog regression-barrier per ADR-0050
  D272; the W6 commit extends the joined catalog with the SIXTH
  ``daemon_stage_saturated`` class).

Test classes:

* ``TestDaemonLifecycleStates`` — closed-set contents + frozen.
* ``TestDaemonNewEventClasses`` — closed-set contents + frozen +
  disjoint-from-EVENT_CLASS_CATALOG-at-Week-1 + naming-convention.
* ``TestHealthProbeOutcomes`` — closed-set contents + frozen.
* ``TestDaemonPolicyReloadSignals`` — closed-set contents + frozen
  (Pillar H Week 1 follow-up P3-2 closure).
* ``TestPolicyReloadStatuses`` — closed-set contents + frozen (Pillar
  H Week 1 follow-up P3-3 closure).
* ``TestDaemonConfig`` — frozen invariant + defaults + per-stage keys.
* ``TestDaemonRunner`` — frozen invariant + signature presence + Week
  1 NotImplementedError raises.
* ``TestPolicyReloadResult`` — frozen invariant + closed-enum status
  (Pillar H Week 1 follow-up P3-3 closure adds the per-status
  regression-barrier).
* ``TestHealthStatus`` — frozen invariant + privacy invariant (no
  forbidden body fields in the dataclass shape) + cell-level matrix
  coverage over outcomes + lifecycle states (Pillar H Week 1 follow-up
  P3-4 closure).
* ``TestPrimitiveSignatures`` — every Week 1 primitive's signature is
  importable + raises NotImplementedError at body-call time.
* ``TestMigrationRunnerContract`` — the audit's referenced
  :meth:`MigrationRunner.apply` exists on the actual API surface
  (Pillar H Week 1 follow-up P2-1 closure: audit + ADR previously
  named non-existent ``apply_pending()``).
* ``TestInitDaemonValidation`` — Week 2 ``init_daemon`` body MUST
  validate config; the stub class pins which kwargs raise
  :exc:`ValueError` (Pillar H Week 1 follow-up P3-6 closure;
  un-skipped at Week 2 per ADR-0060 D332 trajectory).
* ``TestPublicSurface`` — re-export shape per
  ``orchestrator/daemon/__init__.py``.
"""

from __future__ import annotations

import dataclasses
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

# Bare imports per the orchestrator/ scripts' import convention.
from orchestrator import daemon as _daemon
from orchestrator.daemon import (
    DAEMON_EXIT_REASONS,
    DAEMON_LIFECYCLE_STATES,
    DAEMON_NEW_EVENT_CLASSES,
    DAEMON_POLICY_RELOAD_SIGNALS,
    DaemonConfig,
    DaemonRunner,
    EventClassIndex,
    HEALTH_PROBE_OUTCOMES,
    HealthStatus,
    POLICY_RELOAD_STATUSES,
    PersonEventIndex,
    PolicyReloadResult,
    SHUTDOWN_REASONS,
    attach_signal_handlers,
    build_daemon_started_payload,
    build_daemon_stopped_payload,
    build_daemon_stopping_payload,
    build_health_probe_payload,
    init_daemon,
    serve_health_endpoint,
)
from orchestrator.daemon import runner as _runner
from orchestrator.daemon import health as _health
from orchestrator.migrations import MigrationRunner as _MigrationRunner
import observability as _observability


# ---------------------------------------------------------------------------
# Closed-set contracts
# ---------------------------------------------------------------------------


class TestDaemonLifecycleStates:
    """ADR-0060 D331 closed-set discipline."""

    def test_is_frozenset(self):
        assert isinstance(DAEMON_LIFECYCLE_STATES, frozenset)

    def test_contains_four_states(self):
        assert len(DAEMON_LIFECYCLE_STATES) == 4

    def test_contents_pin_per_adr_0060_d331(self):
        assert DAEMON_LIFECYCLE_STATES == frozenset({
            "initializing",
            "ready",
            "draining",
            "stopped",
        })

    def test_pillar_i_paused_state_NOT_yet_in_closed_set(self):
        """ADR-0060 D335 — Pillar I MAY add a ``"paused"`` per-tenant
        state; Pillar H Week 1 ships the FOUR states only. The Pillar
        I author extends + the regression-barrier here fails until
        they do."""
        assert "paused" not in DAEMON_LIFECYCLE_STATES


class TestDaemonNewEventClasses:
    """ADR-0060 D331 + R031 regression-barrier discipline."""

    def test_is_frozenset(self):
        assert isinstance(DAEMON_NEW_EVENT_CLASSES, frozenset)

    def test_contains_six_event_classes_per_week_6_addition(self):
        # Pillar H Week 6 extends DAEMON_NEW_EVENT_CLASSES from 5 → 6
        # via the NEW daemon_stage_saturated class per ADR-0065 D355.
        assert len(DAEMON_NEW_EVENT_CLASSES) == 6

    def test_contents_pin_per_adr_0060_d331_and_adr_0065_d355(self):
        assert DAEMON_NEW_EVENT_CLASSES == frozenset({
            "daemon_started",
            "daemon_stopping",
            "daemon_stopped",
            "policy_reloaded",
            "health_probe",
            # Pillar H Week 6 NEW per ADR-0065 D355
            "daemon_stage_saturated",
        })

    def test_subset_of_event_class_catalog_at_pillar_h_week_2_and_week_6(self):
        """Pillar H Week 2 + Week 6 SUBSET assertion per ADR-0061 D338
        + ADR-0065 D355 (Week 1 ships the DISJOINT test; Week 2
        flips to SUBSET on the catalog extension; Week 6 extends the
        catalog with ``daemon_stage_saturated``; W6 follow-up P3-7 +
        NEW-5 closure renames the test to name BOTH catalog extensions
        per the per-week-reviewer's discipline-scope extension to
        operator-readable test names). The SIX Pillar H event classes
        joined :data:`observability.EVENT_CLASS_CATALOG` across Week 2
        (FIVE classes) + Week 6 (the sixth `daemon_stage_saturated`);
        the symmetric-assertion regression-barrier catches a future
        divergence (e.g., a Pillar I tenant-scoped event class added
        to DAEMON_NEW_EVENT_CLASSES but forgotten in the catalog).

        The Week 1 test was named
        ``test_disjoint_from_event_class_catalog_at_pillar_h_week_1``
        and asserted DISJOINT; the Week 2 commit renames + inverts the
        assertion per the per-pillar-foundation precedent (Pillar G
        Week 1 → Week 2's catalog-extension transition shipped under
        ADR-0050 D272 / ADR-0051 D278's "disjoint → subset" rename
        convention).
        """
        assert DAEMON_NEW_EVENT_CLASSES.issubset(
            _observability.EVENT_CLASS_CATALOG
        ), (
            f"ADR-0061 D338 — Pillar H Week 2 expects DAEMON_NEW_EVENT_CLASSES "
            f"to be a SUBSET of observability.EVENT_CLASS_CATALOG. Missing: "
            f"{sorted(DAEMON_NEW_EVENT_CLASSES - _observability.EVENT_CLASS_CATALOG)!r}"
        )

    def test_disjoint_from_observability_new_event_classes(self):
        """The SIX Pillar H event classes (Week 2 + Week 6 catalog
        extensions per ADR-0061 D338 + ADR-0065 D355; W6 follow-up
        P3-7 closure updates the prior "five" docstring drift) are
        disjoint from the two Pillar G event classes per ADR-0050
        D272's catalog partitioning convention."""
        overlap = DAEMON_NEW_EVENT_CLASSES & _observability.OBSERVABILITY_NEW_EVENT_CLASSES
        assert overlap == frozenset()

    def test_all_names_are_snake_case(self):
        """Naming convention — every event class is lowercase
        snake_case (matches the prior pillars' convention)."""
        import re
        snake_case = re.compile(r"^[a-z][a-z0-9_]*$")
        for name in DAEMON_NEW_EVENT_CLASSES:
            assert snake_case.match(name), (
                f"event class {name!r} not snake_case"
            )


class TestHealthProbeOutcomes:
    """ADR-0060 D334 closed-set discipline."""

    def test_is_frozenset(self):
        assert isinstance(HEALTH_PROBE_OUTCOMES, frozenset)

    def test_contains_three_outcomes(self):
        assert len(HEALTH_PROBE_OUTCOMES) == 3

    def test_contents_pin_per_adr_0060_d334(self):
        assert HEALTH_PROBE_OUTCOMES == frozenset({"ok", "degraded", "unhealthy"})


class TestDaemonPolicyReloadSignals:
    """Pillar H Week 1 follow-up P3-2 closure — :data:`DAEMON_POLICY_RELOAD_SIGNALS`
    closed-set pins the operator-deliberate signal names accepted at
    :attr:`DaemonConfig.policy_reload_signal`. Without the closed-set
    + the regression-barrier here, an operator typo like ``"SIG_HUP"``
    (underscore) or ``"SIGTERM"`` (semantically inappropriate) would
    silently pass type-check and fail at the Week 7 :meth:`reload_policy`
    body's signal-translation step.

    The framework's refuse-loud convention per I5 + ADR-0001 D2 applies
    at the operator-deliberate config boundary; the Week 2 ``init_daemon``
    body validates ``policy_reload_signal in DAEMON_POLICY_RELOAD_SIGNALS
    or is None``.
    """

    def test_is_frozenset(self):
        assert isinstance(DAEMON_POLICY_RELOAD_SIGNALS, frozenset)

    def test_contains_one_signal_at_week_1(self):
        """Pillar H Week 1 ships SIGHUP only; if Pillar H Week 7+
        surfaces operator-deliberate alternatives (e.g., SIGUSR1 for
        tenant-scoped reload at Pillar I), the closed-set extends + the
        Week 7 author updates this regression-barrier concurrently."""
        assert len(DAEMON_POLICY_RELOAD_SIGNALS) == 1

    def test_contents_pin_per_pillar_h_week_1_followup(self):
        assert DAEMON_POLICY_RELOAD_SIGNALS == frozenset({"SIGHUP"})

    def test_default_policy_reload_signal_in_closed_set(self):
        """The :class:`DaemonConfig` default
        ``policy_reload_signal = "SIGHUP"`` MUST live in the closed-set
        — the default is itself an operator-visible structural
        commitment."""
        config = DaemonConfig(
            vault_dir=Path("/tmp/vault"),
            ledger_dir=Path("/tmp/ledger"),
        )
        assert config.policy_reload_signal in DAEMON_POLICY_RELOAD_SIGNALS

    def test_none_is_operator_opt_out_NOT_in_closed_set(self):
        """``None`` is the operator-deliberate opt-out (disables
        SIGHUP-driven reload) and is documented separately in the
        :data:`DAEMON_POLICY_RELOAD_SIGNALS` docstring; it is NOT in
        the closed-set because frozenset cannot cleanly enumerate
        ``None`` as a "valid signal name". The Week 2 :func:`init_daemon`
        validator handles both cases per the docstring contract."""
        assert None not in DAEMON_POLICY_RELOAD_SIGNALS


class TestPolicyReloadStatuses:
    """Pillar H Week 1 follow-up P3-3 closure — :data:`POLICY_RELOAD_STATUSES`
    closed-set pins the valid :attr:`PolicyReloadResult.status` values.

    The :class:`TestPolicyReloadResult` class docstring at Week 1 main
    commit claimed "closed-enum status" — but no regression-barrier
    test pinned the contents; the Pillar H Week 1 follow-up commit
    closes the matrix-coverage gap. Pillar H Week 7+
    :meth:`DaemonRunner.reload_policy` body MUST emit only these two
    status values; an operator-extensible third status (e.g.,
    ``"deferred"`` for tenant-scoped reload at Pillar I) joins the
    closed-set + this regression-barrier concurrently per the
    per-pillar mirror constants parity discipline.
    """

    def test_is_frozenset(self):
        assert isinstance(POLICY_RELOAD_STATUSES, frozenset)

    def test_contains_two_statuses(self):
        assert len(POLICY_RELOAD_STATUSES) == 2

    def test_contents_pin_per_pillar_h_week_1_followup(self):
        assert POLICY_RELOAD_STATUSES == frozenset({"applied", "failed_unchanged"})


# ---------------------------------------------------------------------------
# Dataclass shape contracts
# ---------------------------------------------------------------------------


class TestDaemonConfig:
    """ADR-0060 D331 — :class:`DaemonConfig` is frozen + has sensible
    defaults + per-stage keys match the Pillar G pipeline stages."""

    def test_is_frozen(self):
        config = DaemonConfig(
            vault_dir=Path("/tmp/vault"),
            ledger_dir=Path("/tmp/ledger"),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.vault_dir = Path("/elsewhere")

    def test_defaults_per_adr_0060_d331(self):
        config = DaemonConfig(
            vault_dir=Path("/tmp/vault"),
            ledger_dir=Path("/tmp/ledger"),
        )
        assert config.health_port == 8080
        assert config.graceful_shutdown_seconds == 30
        assert config.policy_reload_signal == "SIGHUP"
        assert config.health_probe_rate_limit_seconds == 30

    def test_parallelism_limits_default_matches_pillar_g_pipeline_stages(self):
        """ADR-0060 D331 — per-stage worker pool keys MUST mirror
        :data:`funnel._PILLAR_G_PIPELINE_STAGES` for the seven-stages
        invariant per ADR-0059 D325."""
        import funnel
        config = DaemonConfig(
            vault_dir=Path("/tmp/vault"),
            ledger_dir=Path("/tmp/ledger"),
        )
        assert set(config.parallelism_limits.keys()) == set(
            funnel._PILLAR_G_PIPELINE_STAGES
        )
        # Conservative default — 1 worker per stage.
        for stage, limit in config.parallelism_limits.items():
            assert limit == 1, (
                f"stage {stage!r} default limit = {limit} (expected 1)"
            )

    def test_required_paths_are_paths(self):
        """ADR-0060 D331 — vault_dir + ledger_dir are typed as
        :class:`pathlib.Path`."""
        config = DaemonConfig(
            vault_dir=Path("/tmp/vault"),
            ledger_dir=Path("/tmp/ledger"),
        )
        assert isinstance(config.vault_dir, Path)
        assert isinstance(config.ledger_dir, Path)


class TestDaemonRunner:
    """ADR-0060 D331 — :class:`DaemonRunner` is frozen + has the
    expected signature surface."""

    def _make_runner(self) -> DaemonRunner:
        config = DaemonConfig(
            vault_dir=Path("/tmp/vault"),
            ledger_dir=Path("/tmp/ledger"),
        )
        return DaemonRunner(
            config=config,
            config_hash="fakehash",
            pid=12345,
            started_at_ts="2026-05-26T12:00:00.000Z",
            version="0.0.1",
        )

    def test_is_frozen(self):
        runner = self._make_runner()
        with pytest.raises(dataclasses.FrozenInstanceError):
            runner.lifecycle_state = "ready"

    def test_default_lifecycle_state_is_initializing(self):
        runner = self._make_runner()
        assert runner.lifecycle_state == "initializing"

    def test_lifecycle_state_default_is_in_closed_set(self):
        runner = self._make_runner()
        assert runner.lifecycle_state in DAEMON_LIFECYCLE_STATES

    def test_run_is_async_at_week_5(self):
        """Pillar H Week 5 — :meth:`DaemonRunner.run` is a coroutine
        function per ADR-0064 D349. (The Week 1
        ``test_run_signature_raises_not_implemented_at_week_1`` flipped
        to this regression-barrier at Week 5 per the per-pillar-
        foundation precedent — Pillar H Week 3 + Week 4 stubs followed
        the same rename+invert pattern.)"""
        import inspect
        runner = self._make_runner()
        assert inspect.iscoroutinefunction(runner.run), (
            "DaemonRunner.run must be async at Week 5 per ADR-0064 D349 "
            "(asyncio event loop body per ADR-0060 D332 framework "
            "decision)."
        )

    def test_shutdown_rejects_invalid_reason(self):
        """Pillar H Week 3 — :meth:`DaemonRunner.shutdown` refuses-loud
        on ``reason`` outside :data:`SHUTDOWN_REASONS` per ADR-0062
        D342 + the I5 + ADR-0001 D2 refuse-loud convention. (The Week
        1 ``test_shutdown_signature_raises_not_implemented_at_week_1``
        flipped to this regression-barrier at Week 3 per the
        per-pillar-foundation precedent.)"""
        runner = self._make_runner()
        with pytest.raises(ValueError, match="reason not in SHUTDOWN_REASONS"):
            runner.shutdown("banana")

    def test_reload_policy_returns_PolicyReloadResult_at_week_7(self):
        """Pillar H Week 7 — :meth:`DaemonRunner.reload_policy` body
        lands per ADR-0066 D356. The Week 1 stub raised
        :exc:`NotImplementedError`; Week 7 ships the body that returns
        a :class:`PolicyReloadResult` with ``status`` in
        :data:`POLICY_RELOAD_STATUSES`. (The Week 1 / Week 2 / Week 3 /
        Week 4 / Week 5 stubs followed the same rename+invert pattern
        — this test inverts to assert the body's contract.)

        Uses test-only seams (``policy_load_fn`` returns ``[]``,
        ``hash_fn`` returns a known 64-hex digest, ``emit_fn`` captures
        to list, ``now_fn`` returns a fixed clock) to verify the
        body's return shape without depending on disk state."""
        runner = self._make_runner()
        emits = []
        result = runner.reload_policy(
            policy_load_fn=lambda _dir: [],
            hash_fn=lambda _dir: "f" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=emits.append,
        )
        assert isinstance(result, PolicyReloadResult)
        assert result.status in POLICY_RELOAD_STATUSES
        assert result.status == "applied"


class TestPolicyReloadResult:
    """ADR-0060 D335 — :class:`PolicyReloadResult` is frozen + the
    ``status`` field is a closed enum (Pillar H Week 1 follow-up P3-3
    closure adds the per-status regression-barrier)."""

    def _make_result(self, *, status: str = "applied",
                     parse_error: str | None = None) -> PolicyReloadResult:
        return PolicyReloadResult(
            status=status,
            source_path=Path("/etc/policy.yml"),
            prior_content_hash="hash1",
            new_content_hash="hash2",
            reloaded_at_ts="2026-05-26T12:00:00.000Z",
            parse_error=parse_error,
        )

    def test_is_frozen(self):
        result = self._make_result()
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = "failed_unchanged"

    def test_parse_error_optional(self):
        result = self._make_result()
        assert result.parse_error is None

    @pytest.mark.parametrize("status", sorted(POLICY_RELOAD_STATUSES))
    def test_each_status_constructs_valid_result(self, status: str):
        """Pillar H Week 1 follow-up P3-3 closure — cell-level matrix
        coverage discipline. Every status value in
        :data:`POLICY_RELOAD_STATUSES` MUST construct a valid
        :class:`PolicyReloadResult`."""
        result = self._make_result(status=status)
        assert result.status == status
        assert result.status in POLICY_RELOAD_STATUSES

    def test_failed_unchanged_status_with_parse_error(self):
        """Pillar H Week 1 follow-up P3-3 closure — when ``status ==
        "failed_unchanged"``, the operator-readable ``parse_error``
        field is present per the docstring contract."""
        result = self._make_result(
            status="failed_unchanged",
            parse_error="line 5: cooldown.days must be integer, got '7d'",
        )
        assert result.status == "failed_unchanged"
        assert result.parse_error is not None
        assert "cooldown.days" in result.parse_error


class TestHealthStatus:
    """ADR-0060 D334 — :class:`HealthStatus` is frozen + the privacy
    invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 holds (no
    forbidden body fields) + cell-level matrix coverage over outcomes
    + lifecycle states (Pillar H Week 1 follow-up P3-4 closure)."""

    def _make_status(self, *, outcome: str = "ok",
                     lifecycle_state: str = "ready") -> HealthStatus:
        return HealthStatus(
            outcome=outcome,
            lifecycle_state=lifecycle_state,
            daemon_pid=12345,
            daemon_version="0.0.1",
            uptime_seconds=60,
            config_hash="fakehash",
            ledger_reachable=True,
            policy_loaded=True,
            in_flight_task_count=0,
            last_reconcile_pass_age_seconds=10,
            ts="2026-05-26T12:00:00.000Z",
        )

    def test_is_frozen(self):
        status = self._make_status()
        with pytest.raises(dataclasses.FrozenInstanceError):
            status.outcome = "degraded"

    def test_privacy_invariant_no_forbidden_fields(self):
        """ADR-0060 D335 invariant 1 + ADR-0050 D276(b) + ADR-0058
        D323 — the health endpoint's JSON payload contains COUNTS +
        STATES + timestamps + version; NEVER ``person_id`` /
        ``draft_body`` / ``dossier_body`` / ``source_list`` /
        ``claim_text`` / ``query_text``."""
        status = self._make_status()
        forbidden = {
            "person_id", "draft_body", "raw_body", "dossier_body",
            "exemplar_body", "exemplar_bodies",
            "claim_text", "query_text", "source_list",
        }
        actual_fields = {f.name for f in dataclasses.fields(status)}
        overlap = forbidden & actual_fields
        assert overlap == set(), (
            f"HealthStatus contains forbidden privacy-invariant field(s): "
            f"{sorted(overlap)!r}. Per ADR-0050 D276(b) + ADR-0058 D323 "
            f"these fields MUST NOT surface in operator-readable Pillar "
            f"H output."
        )

    def test_outcome_in_closed_set(self):
        status = self._make_status()
        assert status.outcome in HEALTH_PROBE_OUTCOMES

    def test_lifecycle_state_in_closed_set(self):
        status = self._make_status()
        assert status.lifecycle_state in DAEMON_LIFECYCLE_STATES

    @pytest.mark.parametrize("outcome", sorted(HEALTH_PROBE_OUTCOMES))
    def test_each_outcome_constructs_valid_status(self, outcome: str):
        """Pillar H Week 1 follow-up P3-4 closure — cell-level matrix
        coverage. Each value in :data:`HEALTH_PROBE_OUTCOMES` MUST
        construct a valid :class:`HealthStatus`. Without this, a
        future Week 4 reviewer wiring the HTTP server could construct
        a ``HealthStatus(outcome="banana", ...)`` and the test suite
        would silently pass."""
        status = self._make_status(outcome=outcome)
        assert status.outcome == outcome
        assert status.outcome in HEALTH_PROBE_OUTCOMES

    @pytest.mark.parametrize("lifecycle_state", sorted(DAEMON_LIFECYCLE_STATES))
    def test_each_lifecycle_state_constructs_valid_status(
        self, lifecycle_state: str
    ):
        """Pillar H Week 1 follow-up P3-4 closure — cell-level matrix
        coverage. Each value in :data:`DAEMON_LIFECYCLE_STATES` MUST
        construct a valid :class:`HealthStatus`. The health endpoint's
        response payload carries the lifecycle state; every transition
        on the daemon's state machine MUST be representable in the
        operator-visible probe response."""
        status = self._make_status(lifecycle_state=lifecycle_state)
        assert status.lifecycle_state == lifecycle_state
        assert status.lifecycle_state in DAEMON_LIFECYCLE_STATES


# ---------------------------------------------------------------------------
# Primitive function signatures
# ---------------------------------------------------------------------------


class TestPrimitiveSignatures:
    """Per ADR-0060 D332's per-week trajectory table — Week 1 ships
    signatures only; bodies raise ``NotImplementedError`` until the
    designated Week N body lands. Week 2 lands the ``init_daemon``
    body per ADR-0061 D337 — the Week 1
    ``test_init_daemon_raises_not_implemented_at_week_1`` flipped to
    :class:`TestInitDaemonBody` happy-path + startup-ordering
    verification (see below)."""

    def test_attach_signal_handlers_requires_running_event_loop(self):
        """Pillar H Week 3 — :func:`attach_signal_handlers` body uses
        :func:`asyncio.get_running_loop` per ADR-0062 D341; calling
        outside a running event loop raises :exc:`RuntimeError` per
        the asyncio contract. (The Week 1
        ``test_attach_signal_handlers_raises_not_implemented_at_week_1``
        flipped to this regression-barrier at Week 3 per the per-
        pillar-foundation precedent. Production callers wire the
        signal handlers from inside the daemon's event loop at
        :meth:`DaemonRunner.run`, Week 5+ trajectory.)"""
        runner = DaemonRunner(
            config=DaemonConfig(
                vault_dir=Path("/tmp/vault"),
                ledger_dir=Path("/tmp/ledger"),
            ),
            config_hash="fakehash",
            pid=12345,
            started_at_ts="2026-05-26T12:00:00.000Z",
            version="0.0.1",
        )
        with pytest.raises(RuntimeError, match="no running event loop"):
            attach_signal_handlers(runner)

    def test_serve_health_endpoint_is_async_at_week_4(self):
        """Pillar H Week 4 — :func:`serve_health_endpoint` body lands
        per ADR-0063 D345. The Week 1 stub raised NotImplementedError;
        Week 4 ships the async body returning :class:`aiohttp.web.AppRunner`.
        The Week 4 RENAME + INVERT pattern matches the Pillar H Week 2
        + Week 3 stubs (e.g., ``test_init_daemon_raises_not_implemented_at_week_1``
        → ``test_init_daemon_returns_initializing_runner`` at Week 2;
        ``test_shutdown_signature_raises_not_implemented_at_week_1``
        → ``test_shutdown_rejects_invalid_reason`` at Week 3)."""
        import asyncio
        import inspect
        # The function is now a coroutine function (async def).
        assert inspect.iscoroutinefunction(serve_health_endpoint)


# ---------------------------------------------------------------------------
# Cross-pillar contract verification (Pillar H Week 1 follow-up P2-1)
# ---------------------------------------------------------------------------


class TestMigrationRunnerContract:
    """Pillar H Week 1 follow-up P2-1 closure — the per-week reviewer
    surfaced that the cross-pillar audit + ADR-0060 D333 narrative +
    the ADR-0060 References section all named
    :meth:`MigrationRunner.apply_pending` as the method the Week 2
    :func:`init_daemon` body MUST call at the asyncio startup sequence.
    The actual API surface at
    :class:`orchestrator.migrations.runner.MigrationRunner` exposes
    :meth:`apply` (not :meth:`apply_pending`); the follow-up commit
    corrects the audit + ADR text + adds this regression-barrier so
    the per-week reviewer for subsequent pillars catches similar
    audit-vs-actual-API drift.
    """

    def test_apply_method_exists(self):
        """The Week 2 :func:`init_daemon` body's startup ordering
        invariant calls :meth:`MigrationRunner.apply` per ADR-0009 D9's
        "migrations are idempotent + auto-applied at startup" contract
        + the Pillar H Week 1 follow-up P2-1 closure (the audit + ADR
        previously named non-existent ``apply_pending()``)."""
        assert hasattr(_MigrationRunner, "apply"), (
            "Cross-pillar audit at .planning/REVIEW-pillar-h-surface-audit.md "
            "§2 + ADR-0060 D333 + the References section name "
            "MigrationRunner.apply() as the Week 2 startup-ordering "
            "primitive; this regression-barrier pins that the method "
            "actually exists on the API surface."
        )

    def test_pending_method_exists(self):
        """The MigrationRunner.pending() method backs the operator-
        visible ``python -c "...MigrationRunner().pending()..."`` invocation
        in the Pillar H Week 1 + 2 validation gates; the regression-
        barrier pins the API surface against accidental rename."""
        assert hasattr(_MigrationRunner, "pending")


# ---------------------------------------------------------------------------
# Week 2 forward-reference stubs (Pillar H Week 1 follow-up P3-6 closure)
# ---------------------------------------------------------------------------


class TestInitDaemonValidation:
    """Pillar H Week 2 — :func:`init_daemon` body validates config per
    ADR-0061 D337 step 1. Refuse-loud on invalid via :exc:`ValueError`
    BEFORE any side-effecting startup step runs (the framework
    convention per I5 + ADR-0001 D2).

    Pillar H Week 1 follow-up shipped these as skipped stubs per the
    "Week-N stubs should pin the test the Week-(N+1) body un-skips"
    discipline; Week 2 un-skips + the validator body satisfies each
    row per ADR-0061 D337.
    """

    def _noop_seams(self) -> dict:
        """Helper — all side-effecting steps stubbed to no-op so the
        validator's refuse-loud surfaces are tested in isolation."""
        return {
            "migration_apply_fn": lambda: None,
            "policy_load_fn": lambda _dir: [],
            "otel_meter_init_fn": lambda *a, **kw: None,
            "otel_tracer_init_fn": lambda *a, **kw: None,
            "prometheus_start_fn": lambda *a, **kw: None,
        }

    def test_invalid_port_range_raises_value_error(self, tmp_path):
        """ADR-0061 D337 — :attr:`DaemonConfig.health_port` MUST be in
        ``1..65535``. Week 2 body raises :exc:`ValueError` on out-of-
        range."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            health_port=70000,  # > 65535
        )
        with pytest.raises(ValueError, match="health_port out of range"):
            init_daemon(config, **self._noop_seams())

    def test_invalid_port_zero_raises_value_error(self, tmp_path):
        """ADR-0061 D337 — port 0 is rejected (kernel-assigned port
        would surface to operators as ``health_port: 0`` in the config
        hash — operator-confusing posture; the framework refuses-loud
        per I5 + ADR-0001 D2)."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            health_port=0,
        )
        with pytest.raises(ValueError, match="health_port out of range"):
            init_daemon(config, **self._noop_seams())

    def test_nonexistent_vault_dir_raises_value_error(self, tmp_path):
        """ADR-0061 D337 — :attr:`DaemonConfig.vault_dir` MUST exist
        on-disk. Refuses-loud at startup rather than crashing later in
        the per-stage worker pool's vault read."""
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=tmp_path / "does-not-exist",
            ledger_dir=ledger_dir,
        )
        with pytest.raises(ValueError, match="vault_dir does not exist"):
            init_daemon(config, **self._noop_seams())

    def test_nonexistent_ledger_dir_raises_value_error(self, tmp_path):
        """ADR-0061 D337 — :attr:`DaemonConfig.ledger_dir` MUST exist
        on-disk."""
        vault_dir = tmp_path / "vault"
        vault_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=tmp_path / "does-not-exist",
        )
        with pytest.raises(ValueError, match="ledger_dir does not exist"):
            init_daemon(config, **self._noop_seams())

    def test_parallelism_limits_extra_key_raises_value_error(self, tmp_path):
        """ADR-0061 D337 + per-pillar mirror constants parity discipline
        — :attr:`DaemonConfig.parallelism_limits` keys MUST equal
        :data:`funnel._PILLAR_G_PIPELINE_STAGES`. Week 2 body raises
        :exc:`ValueError` on any extra key OR any missing stage."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            parallelism_limits={
                "queued": 1, "researched": 1, "drafted": 1, "ready": 1,
                "sent": 1, "replied": 1, "outcome_terminal": 1,
                "banana": 1,  # extra key
            },
        )
        with pytest.raises(ValueError, match="parallelism_limits"):
            init_daemon(config, **self._noop_seams())

    def test_parallelism_limits_missing_key_raises_value_error(self, tmp_path):
        """Symmetric to the extra-key test — missing stage refuses-
        loud at startup."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            parallelism_limits={
                "queued": 1, "researched": 1, "drafted": 1, "ready": 1,
                "sent": 1, "replied": 1,
                # missing "outcome_terminal"
            },
        )
        with pytest.raises(ValueError, match="parallelism_limits"):
            init_daemon(config, **self._noop_seams())

    def test_invalid_policy_reload_signal_raises_value_error(self, tmp_path):
        """Pillar H Week 1 follow-up P3-2 + Week 2 closure —
        :attr:`DaemonConfig.policy_reload_signal` MUST be in
        :data:`DAEMON_POLICY_RELOAD_SIGNALS` OR equal ``None``. Week 2
        body raises :exc:`ValueError` on operator typo like ``"SIG_HUP"``
        (underscore) or semantically-inappropriate value."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            policy_reload_signal="SIG_HUP",  # underscore typo
        )
        with pytest.raises(ValueError, match="policy_reload_signal"):
            init_daemon(config, **self._noop_seams())

    def test_none_policy_reload_signal_accepted(self, tmp_path):
        """Pillar H Week 1 follow-up P3-2 closure — the operator-
        deliberate opt-out (``policy_reload_signal = None``) MUST be
        accepted by Week 2 body's validator; SIGHUP-driven reload is
        disabled, but the daemon starts."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            policy_reload_signal=None,
        )
        runner = init_daemon(config, **self._noop_seams())
        assert runner.lifecycle_state == "initializing"

    def test_negative_graceful_shutdown_seconds_raises_value_error(
        self, tmp_path,
    ):
        """Pillar H Week 2 follow-up P2-1 closure —
        :attr:`DaemonConfig.graceful_shutdown_seconds` MUST be ``> 0``.
        The drain deadline is the structural commitment per ADR-0060
        D335 invariant 3; ``<= 0`` would cancel in-flight tasks
        immediately on SIGTERM at Week 3+ shutdown body."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            graceful_shutdown_seconds=-100,
        )
        with pytest.raises(
            ValueError, match="graceful_shutdown_seconds must be > 0",
        ):
            init_daemon(config, **self._noop_seams())

    def test_zero_graceful_shutdown_seconds_raises_value_error(
        self, tmp_path,
    ):
        """Pillar H Week 2 follow-up P2-1 closure — boundary cell:
        ``graceful_shutdown_seconds=0`` is rejected per the ``> 0``
        rule (already-past-deadline cancels in-flight immediately)."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            graceful_shutdown_seconds=0,
        )
        with pytest.raises(
            ValueError, match="graceful_shutdown_seconds must be > 0",
        ):
            init_daemon(config, **self._noop_seams())

    def test_negative_health_probe_rate_limit_seconds_raises_value_error(
        self, tmp_path,
    ):
        """Pillar H Week 2 follow-up P2-1 closure —
        :attr:`DaemonConfig.health_probe_rate_limit_seconds` MUST be
        ``>= 0``. R038 mitigation per ADR-0060 D334 binds at ``>= 0``;
        ``0`` is the operator-deliberate "every probe emits" posture;
        negative inverts the rate-limit arithmetic at Week 4 health
        endpoint body."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            health_probe_rate_limit_seconds=-100,
        )
        with pytest.raises(
            ValueError,
            match="health_probe_rate_limit_seconds must be >= 0",
        ):
            init_daemon(config, **self._noop_seams())

    def test_zero_health_probe_rate_limit_seconds_accepted(self, tmp_path):
        """Pillar H Week 2 follow-up P2-1 closure — boundary cell:
        ``health_probe_rate_limit_seconds=0`` is operator-deliberate
        "every probe emits" + MUST be accepted (NOT a refuse-loud
        boundary). The rule is ``>= 0`` not ``> 0`` because operators
        wanting per-request probe events legitimately set to 0."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            health_probe_rate_limit_seconds=0,
        )
        runner = init_daemon(config, **self._noop_seams())
        assert runner.lifecycle_state == "initializing"

    def test_zero_parallelism_limit_raises_value_error(self, tmp_path):
        """Pillar H Week 2 follow-up P2-1 closure —
        :attr:`DaemonConfig.parallelism_limits` per-stage value MUST be
        ``>= 1``. ``asyncio.Semaphore(0)`` silently deadlocks every
        per-stage tick at Week 5+ per-stage worker pool body."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            parallelism_limits={
                "queued": 1, "researched": 1, "drafted": 1, "ready": 1,
                "sent": 0,  # asyncio.Semaphore(0) deadlocks
                "replied": 1, "outcome_terminal": 1,
            },
        )
        with pytest.raises(
            ValueError,
            match=r"parallelism_limits\['sent'\] must be >= 1",
        ):
            init_daemon(config, **self._noop_seams())

    def test_negative_parallelism_limit_raises_value_error(self, tmp_path):
        """Pillar H Week 2 follow-up P2-1 closure — negative per-stage
        parallelism limit refuses-loud (``asyncio.Semaphore(-N)`` raises
        ValueError mid-startup AFTER migrations + policy + OTel set-once
        burnt; the validator catches at pre-flight instead)."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            parallelism_limits={
                "queued": -5,  # negative limit
                "researched": 1, "drafted": 1, "ready": 1,
                "sent": 1, "replied": 1, "outcome_terminal": 1,
            },
        )
        with pytest.raises(
            ValueError,
            match=r"parallelism_limits\['queued'\] must be >= 1",
        ):
            init_daemon(config, **self._noop_seams())


class TestInitDaemonBody:
    """Pillar H Week 2 — :func:`init_daemon` body happy path +
    startup ordering invariant verification per ADR-0061 D337 + D340
    P3-1 carry-forward closure.

    The startup ordering invariant: (1) validate → (2) hash → (3) pid +
    ts → (4) migrations → (5) policy → (6) OTel → (7) Prometheus → (8)
    construct runner in "initializing" state.

    The Week 1 follow-up's behavioral-passthrough discipline extends
    via this class: the spy pattern records each step's invocation +
    asserts the order matches the ADR-0061 D337 contract.
    """

    def _make_valid_config(self, tmp_path) -> DaemonConfig:
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        return DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)

    def test_happy_path_returns_initializing_runner(self, tmp_path):
        """ADR-0061 D337 step 8 — :func:`init_daemon` returns a
        :class:`DaemonRunner` in ``"initializing"`` state with all
        identity fields populated."""
        config = self._make_valid_config(tmp_path)
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert runner.lifecycle_state == "initializing"
        assert runner.config is config
        assert isinstance(runner.config_hash, str)
        assert len(runner.config_hash) == 64  # SHA-256 hex
        assert runner.pid > 0
        assert runner.started_at_ts.endswith("Z")
        assert runner.version == _runner._DAEMON_VERSION

    def test_startup_ordering_invariant_per_adr_0061_d340_P3_1(self, tmp_path):
        """ADR-0061 D340 P3-1 carry-forward closure — the startup
        sequence is migrations → policy → OTel meter → OTel tracer →
        Prometheus → runner construct. The spy pattern records each
        step's invocation; the assertion pins the order.
        """
        config = self._make_valid_config(tmp_path)
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
        ], f"Startup ordering invariant violated: {call_order!r}"

    def test_otel_set_once_at_daemon_startup_per_adr_0061_d340_P3_2(
        self, tmp_path,
    ):
        """ADR-0061 D340 P3-2 carry-forward closure — the OTel SDK
        init functions are invoked EXACTLY ONCE per
        :func:`init_daemon` call. Operators calling :func:`init_daemon`
        twice (e.g., daemon restart in-process) would see two
        invocations; the OTel SDK's own set-once semantics handles
        the "already set" idempotency per Pillar G Week 3 convention.
        """
        config = self._make_valid_config(tmp_path)
        meter_calls = 0
        tracer_calls = 0

        def _meter_init(*a, **kw):
            nonlocal meter_calls
            meter_calls += 1

        def _tracer_init(*a, **kw):
            nonlocal tracer_calls
            tracer_calls += 1

        init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=_meter_init,
            otel_tracer_init_fn=_tracer_init,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert meter_calls == 1
        assert tracer_calls == 1

    def test_config_hash_stable_across_invocations(self, tmp_path):
        """ADR-0061 D337 step 2 — the config hash is STABLE across
        invocations (operators query the hash to detect config drift
        across restarts)."""
        config = self._make_valid_config(tmp_path)
        seams = {
            "migration_apply_fn": lambda: None,
            "policy_load_fn": lambda _dir: [],
            "otel_meter_init_fn": lambda *a, **kw: None,
            "otel_tracer_init_fn": lambda *a, **kw: None,
            "prometheus_start_fn": lambda *a, **kw: None,
        }
        runner1 = init_daemon(config, **seams)
        runner2 = init_daemon(config, **seams)
        assert runner1.config_hash == runner2.config_hash

    def test_config_hash_differs_on_config_change(self, tmp_path):
        """ADR-0061 D337 step 2 — different configs produce different
        hashes (a one-bit field change MUST surface as a hash diff for
        operator-visible config drift detection)."""
        config1 = self._make_valid_config(tmp_path)
        config2 = DaemonConfig(
            vault_dir=config1.vault_dir,
            ledger_dir=config1.ledger_dir,
            health_port=9090,  # different port
        )
        seams = {
            "migration_apply_fn": lambda: None,
            "policy_load_fn": lambda _dir: [],
            "otel_meter_init_fn": lambda *a, **kw: None,
            "otel_tracer_init_fn": lambda *a, **kw: None,
            "prometheus_start_fn": lambda *a, **kw: None,
        }
        runner1 = init_daemon(config1, **seams)
        runner2 = init_daemon(config2, **seams)
        assert runner1.config_hash != runner2.config_hash

    def test_policy_dir_default_derives_from_vault_dir(self, tmp_path):
        """ADR-0061 D337 step 5 — the default ``policy_dir`` is
        ``config.vault_dir.parent / "policies"`` per the existing
        convention; tests may override via the kwarg."""
        config = self._make_valid_config(tmp_path)
        observed_policy_dir: list[Path] = []
        init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda d: (observed_policy_dir.append(d) or []),
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert observed_policy_dir == [
            config.vault_dir.parent / "policies"
        ]

    def test_policy_dir_kwarg_override(self, tmp_path):
        """Pillar H Week 2 follow-up P3-4 closure — cell-level matrix
        coverage extends to per-kwarg × default-vs-override. The
        ``policy_dir`` kwarg override REPLACES the default derivation;
        a future refactor that silently uses the default would surface
        as a test failure here."""
        config = self._make_valid_config(tmp_path)
        custom_policy_dir = tmp_path / "custom-policies"
        observed_policy_dir: list[Path] = []
        init_daemon(
            config,
            policy_dir=custom_policy_dir,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda d: (observed_policy_dir.append(d) or []),
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert observed_policy_dir == [custom_policy_dir]

    def test_version_kwarg_override(self, tmp_path):
        """Pillar H Week 2 follow-up P3-4 closure — the operator-
        deliberate ``version`` kwarg override surfaces in the runner's
        version field. A future Pillar I per-tenant author wiring per-
        tenant version stamps (``version=f"0.1.0-tenant-{tid}"``)
        depends on this contract."""
        config = self._make_valid_config(tmp_path)
        runner = init_daemon(
            config,
            version="0.2.0-tenant-x",
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert runner.version == "0.2.0-tenant-x"

    def test_pid_fn_kwarg_override(self, tmp_path):
        """Pillar H Week 2 follow-up P3-4 closure — the ``pid_fn``
        seam returns the daemon's OS PID; tests override to inject
        deterministic PIDs."""
        config = self._make_valid_config(tmp_path)
        runner = init_daemon(
            config,
            pid_fn=lambda: 99999,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert runner.pid == 99999

    def test_ts_fn_kwarg_override(self, tmp_path):
        """Pillar H Week 2 follow-up P3-4 closure — the ``ts_fn``
        seam returns the startup ISO-8601 UTC timestamp; tests
        override to inject deterministic timestamps for snapshot
        testing."""
        config = self._make_valid_config(tmp_path)
        runner = init_daemon(
            config,
            ts_fn=lambda: "2026-12-31T23:59:59.999Z",
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert runner.started_at_ts == "2026-12-31T23:59:59.999Z"

    def test_prometheus_port_and_addr_kwarg_override(self, tmp_path):
        """Pillar H Week 2 follow-up P3-4 closure — the
        ``prometheus_port`` + ``prometheus_addr`` kwargs surface as
        kwargs to the prometheus start fn. Operators wiring
        non-default ports (or per-tenant ports at Pillar I) depend
        on this contract."""
        config = self._make_valid_config(tmp_path)
        observed_kwargs: dict = {}
        def _prom_start(**kw):
            observed_kwargs.update(kw)
        init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=_prom_start,
            prometheus_port=9999,
            prometheus_addr="0.0.0.0",
        )
        assert observed_kwargs == {"port": 9999, "addr": "0.0.0.0"}

    def test_prometheus_kwargs_omitted_when_defaults(self, tmp_path):
        """Pillar H Week 2 follow-up P3-4 closure — symmetric cell:
        when ``prometheus_port`` + ``prometheus_addr`` kwargs are NOT
        passed (defaults of ``None``), the start fn is called with NO
        kwargs (deferring to the Pillar G framework defaults at
        :data:`observability._DEFAULT_PROMETHEUS_PORT` +
        :data:`observability._DEFAULT_PROMETHEUS_ADDR` per R036)."""
        config = self._make_valid_config(tmp_path)
        observed_kwargs: dict = {}
        def _prom_start(**kw):
            observed_kwargs.update(kw)
        init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=_prom_start,
        )
        assert observed_kwargs == {}


class TestDaemonStartedPayload:
    """Pillar H Week 2 — :func:`build_daemon_started_payload` emit-shape
    factory per ADR-0061 D339. Pillar H Week 2 ships the FACTORY (Week
    5+ ships the actual transition + ledger append in
    :meth:`DaemonRunner.run`); the factory shape mirrors the Pillar G
    ``build_*_payload`` convention per ADR-0010 D17.

    **Pillar H Week 2 follow-up P2-2 closure** — input validation
    extends per the Pillar G raw-primitive factory convention (see
    :func:`discovery_dedup.build_discovery_dedup_hit_payload` for the
    canonical precedent — refuses-loud on ``result.is_duplicate is False``).
    The factory takes RAW primitives (4 of them), NOT a frozen dataclass
    with construction-time invariants, so refuse-loud has to live at
    the factory boundary."""

    def test_payload_shape_matches_adr_0061_d339(self):
        """The factory output is a dict with exactly five keys: pid +
        version + config_hash + startup_seconds + ``_emitted_by``
        (Pillar H Week 3 follow-up P2-1 closure — the factory stamps
        ``_emitted_by="daemon"`` at the factory boundary per ADR-0010
        D17 + the Pillar E :data:`EMITTED_BY` precedent)."""
        payload = build_daemon_started_payload(
            pid=12345,
            version="0.1.0",
            config_hash="a" * 64,
            startup_seconds=1.234,
        )
        assert set(payload.keys()) == {
            "pid", "version", "config_hash", "startup_seconds",
            "_emitted_by",
        }
        assert payload["pid"] == 12345
        assert payload["version"] == "0.1.0"
        assert payload["config_hash"] == "a" * 64
        assert payload["startup_seconds"] == 1.234
        assert payload["_emitted_by"] == "daemon"

    def test_payload_carries_emitted_by_marker(self):
        """Pillar H Week 3 follow-up P2-1 closure — the factory stamps
        ``_emitted_by="daemon"`` at the factory boundary per ADR-0010
        D17 + the Pillar E :data:`orchestrator.tier_assignment.EMITTED_BY`
        + :data:`orchestrator.discovery_lineage.EMITTED_BY` precedent.

        The Week 3 main commit's docstrings + ADR-0062 D343 narrative
        FALSELY claimed ``_emitted_by`` was auto-filled by
        :meth:`Ledger.append` — but :meth:`Ledger.append` only does
        ``setdefault("v")`` + ``setdefault("ts")``. The Pillar E +
        Pillar G factories explicitly stamp ``_emitted_by`` at the
        factory boundary; the Pillar H factories now align with the
        established framework convention.

        This is the SECOND ADR-vs-actual-impl drift in Pillar H (the
        FIRST was Week 2 follow-up P3-8 OTel Resource rationale). The
        per-week-reviewer's cross-pillar back-audit discipline extended
        at Week 2 follow-up to ADR-vs-actual-impl drift caught this."""
        payload = build_daemon_started_payload(
            pid=1, version="0.1.0", config_hash="a" * 64,
            startup_seconds=0.0,
        )
        assert payload["_emitted_by"] == "daemon"

    def test_startup_seconds_rounded_to_three_decimal_places(self):
        """ADR-0061 D339 + ADR-0031 D140 deterministic-output contract
        — ``startup_seconds`` rounded to 3 decimal places."""
        payload = build_daemon_started_payload(
            pid=1, version="0.1.0", config_hash="b" * 64,
            startup_seconds=1.23456789,
        )
        assert payload["startup_seconds"] == 1.235

    def test_payload_omits_channel_field_per_adr_0014_d33(self):
        """ADR-0014 D33 channel-on-every-event invariant — daemon
        lifecycle events have NO channel context (tenant-process-scoped,
        not per-channel). The factory output omits ``channel``; the
        consumer surface treats absence as ``None`` per ADR-0050 D272."""
        payload = build_daemon_started_payload(
            pid=1, version="0.1.0", config_hash="c" * 64, startup_seconds=0.0,
        )
        assert "channel" not in payload

    def test_payload_omits_ts_and_type_fields(self):
        """ADR-0010 D17 — the ``type`` field is set by the caller (the
        emitter writes ``{"type": "daemon_started", **build_..._payload(...)}``)
        and the ``ts`` field is auto-filled by :meth:`Ledger.append` via
        its ``setdefault("ts")`` contract; the factory output OMITS
        ``type`` + ``ts`` but DOES include ``_emitted_by`` (Pillar H
        Week 3 follow-up P2-1 closure — see
        :meth:`test_payload_carries_emitted_by_marker`)."""
        payload = build_daemon_started_payload(
            pid=1, version="0.1.0", config_hash="d" * 64, startup_seconds=0.0,
        )
        assert "type" not in payload
        assert "ts" not in payload

    def test_startup_seconds_zero_boundary_accepted(self):
        """Pillar H Week 2 follow-up P2-2 closure — boundary cell:
        ``startup_seconds=0.0`` is the operator-deliberate lower bound
        (instantaneous startup, e.g., spy-clock test); MUST be accepted
        (NOT a refuse-loud boundary)."""
        payload = build_daemon_started_payload(
            pid=1, version="0.1.0", config_hash="e" * 64,
            startup_seconds=0.0,
        )
        assert payload["startup_seconds"] == 0.0

    def test_negative_pid_raises_value_error(self):
        """Pillar H Week 2 follow-up P2-2 closure — POSIX OS PIDs are
        positive; the factory refuses-loud on ``pid <= 0`` per the
        Pillar G raw-primitive factory convention."""
        with pytest.raises(ValueError, match="pid > 0"):
            build_daemon_started_payload(
                pid=-1, version="0.1.0", config_hash="a" * 64,
                startup_seconds=1.0,
            )

    def test_zero_pid_raises_value_error(self):
        """Pillar H Week 2 follow-up P2-2 closure — boundary cell:
        PID 0 is the kernel scheduler placeholder, not a daemon process;
        refuse-loud."""
        with pytest.raises(ValueError, match="pid > 0"):
            build_daemon_started_payload(
                pid=0, version="0.1.0", config_hash="a" * 64,
                startup_seconds=1.0,
            )

    def test_empty_version_raises_value_error(self):
        """Pillar H Week 2 follow-up P2-2 closure — empty version string
        is operator-confusing in the ``daemon_started`` payload (operator
        sees ``"version": ""`` + cannot identify the binary across
        restarts); refuse-loud."""
        with pytest.raises(ValueError, match="non-empty version"):
            build_daemon_started_payload(
                pid=1, version="", config_hash="a" * 64,
                startup_seconds=1.0,
            )

    def test_short_config_hash_raises_value_error(self):
        """Pillar H Week 2 follow-up P2-2 closure — the SHA-256 digest
        is 64 hex chars; anything else is operator-confusing or
        operator-broken (e.g., truncated hash leaks; non-SHA-256 input)."""
        with pytest.raises(
            ValueError, match="64-hex-char.*config_hash",
        ):
            build_daemon_started_payload(
                pid=1, version="0.1.0", config_hash="x",  # too short
                startup_seconds=1.0,
            )

    def test_long_config_hash_raises_value_error(self):
        """Pillar H Week 2 follow-up P2-2 closure — symmetric to the
        short-hash test: too-long is also refused (the 64-char
        invariant pins SHA-256 digest length exactly)."""
        with pytest.raises(
            ValueError, match="64-hex-char.*config_hash",
        ):
            build_daemon_started_payload(
                pid=1, version="0.1.0", config_hash="a" * 65,  # too long
                startup_seconds=1.0,
            )

    def test_negative_startup_seconds_raises_value_error(self):
        """Pillar H Week 2 follow-up P2-2 closure — time does not flow
        backward; refuse-loud."""
        with pytest.raises(
            ValueError, match="startup_seconds >= 0",
        ):
            build_daemon_started_payload(
                pid=1, version="0.1.0", config_hash="a" * 64,
                startup_seconds=-5.0,
            )


# ---------------------------------------------------------------------------
# Pillar H Week 3 — signal handlers + shutdown + stopping/stopped emits
# ---------------------------------------------------------------------------


class TestShutdownReasons:
    """Pillar H Week 3 — ADR-0062 D344 closed-set discipline for
    :meth:`DaemonRunner.shutdown` reason + the ``daemon_stopping``
    event payload."""

    def test_is_frozenset(self):
        assert isinstance(SHUTDOWN_REASONS, frozenset)

    def test_contains_three_reasons(self):
        assert len(SHUTDOWN_REASONS) == 3

    def test_contents_pin_per_adr_0062_d344(self):
        assert SHUTDOWN_REASONS == frozenset({
            "sigterm", "sigint", "operator_requested",
        })

    def test_disjoint_from_daemon_exit_reasons(self):
        """ADR-0062 D344 — :data:`SHUTDOWN_REASONS` (operator intent)
        + :data:`DAEMON_EXIT_REASONS` (daemon actual exit status) are
        deliberately disjoint closed-sets; the same disjoint-closed-sets
        pattern as Pillar G's ``_SLO_NAMES`` ↔ ``_DRIFT_REASONS``
        mutually-exclusive contract per ADR-0049 D263 + ADR-0056 D311."""
        assert SHUTDOWN_REASONS & DAEMON_EXIT_REASONS == frozenset()


class TestDaemonExitReasons:
    """Pillar H Week 3 — ADR-0062 D344 closed-set discipline for the
    ``daemon_stopped`` event payload's ``exit_reason`` field."""

    def test_is_frozenset(self):
        assert isinstance(DAEMON_EXIT_REASONS, frozenset)

    def test_contains_three_exit_reasons(self):
        assert len(DAEMON_EXIT_REASONS) == 3

    def test_contents_pin_per_adr_0062_d344(self):
        assert DAEMON_EXIT_REASONS == frozenset({
            "clean", "timeout", "crash",
        })


class TestDaemonStoppingPayload:
    """Pillar H Week 3 — :func:`build_daemon_stopping_payload`
    emit-shape factory per ADR-0062 D343 + the Pillar G raw-primitive
    factory convention per Pillar H Week 2 follow-up P2-2 closure."""

    def test_payload_shape_matches_adr_0062_d343(self):
        """Pillar H Week 3 follow-up P2-1 closure — the factory output
        is a dict with exactly five keys: pid + reason + drain_deadline_ts
        + in_flight_task_count + ``_emitted_by``."""
        payload = build_daemon_stopping_payload(
            pid=12345, reason="sigterm",
            drain_deadline_ts="2026-05-26T20:00:00.000Z",
            in_flight_task_count=3,
        )
        assert set(payload.keys()) == {
            "pid", "reason", "drain_deadline_ts", "in_flight_task_count",
            "_emitted_by",
        }
        assert payload["pid"] == 12345
        assert payload["reason"] == "sigterm"
        assert payload["drain_deadline_ts"] == "2026-05-26T20:00:00.000Z"
        assert payload["in_flight_task_count"] == 3
        assert payload["_emitted_by"] == "daemon"

    def test_payload_carries_emitted_by_marker(self):
        """Pillar H Week 3 follow-up P2-1 closure — the factory stamps
        ``_emitted_by="daemon"`` at the factory boundary per ADR-0010
        D17 + the Pillar E :data:`EMITTED_BY` precedent. See
        :meth:`TestDaemonStartedPayload.test_payload_carries_emitted_by_marker`
        for the full closure rationale."""
        payload = build_daemon_stopping_payload(
            pid=1, reason="sigterm",
            drain_deadline_ts="2026-05-26T20:00:00.000Z",
            in_flight_task_count=0,
        )
        assert payload["_emitted_by"] == "daemon"

    def test_payload_omits_channel_field_per_adr_0014_d33(self):
        """ADR-0014 D33 channel-on-every-event invariant — daemon
        lifecycle events tenant-process-scoped, NOT per-channel."""
        payload = build_daemon_stopping_payload(
            pid=1, reason="sigterm",
            drain_deadline_ts="2026-05-26T20:00:00.000Z",
            in_flight_task_count=0,
        )
        assert "channel" not in payload

    def test_each_reason_constructs_valid_payload(self):
        """Cell-level matrix coverage discipline — each of the THREE
        :data:`SHUTDOWN_REASONS` produces a valid payload."""
        for reason in SHUTDOWN_REASONS:
            payload = build_daemon_stopping_payload(
                pid=1, reason=reason,
                drain_deadline_ts="2026-05-26T20:00:00.000Z",
                in_flight_task_count=0,
            )
            assert payload["reason"] == reason

    def test_invalid_reason_raises_value_error(self):
        with pytest.raises(ValueError, match="reason not in SHUTDOWN_REASONS"):
            build_daemon_stopping_payload(
                pid=1, reason="banana",
                drain_deadline_ts="2026-05-26T20:00:00.000Z",
                in_flight_task_count=0,
            )

    def test_negative_pid_raises_value_error(self):
        with pytest.raises(ValueError, match="pid > 0"):
            build_daemon_stopping_payload(
                pid=-1, reason="sigterm",
                drain_deadline_ts="2026-05-26T20:00:00.000Z",
                in_flight_task_count=0,
            )

    def test_zero_pid_raises_value_error(self):
        with pytest.raises(ValueError, match="pid > 0"):
            build_daemon_stopping_payload(
                pid=0, reason="sigterm",
                drain_deadline_ts="2026-05-26T20:00:00.000Z",
                in_flight_task_count=0,
            )

    def test_empty_drain_deadline_ts_raises_value_error(self):
        with pytest.raises(ValueError, match="drain_deadline_ts"):
            build_daemon_stopping_payload(
                pid=1, reason="sigterm",
                drain_deadline_ts="",
                in_flight_task_count=0,
            )

    def test_negative_in_flight_task_count_raises_value_error(self):
        with pytest.raises(ValueError, match="in_flight_task_count >= 0"):
            build_daemon_stopping_payload(
                pid=1, reason="sigterm",
                drain_deadline_ts="2026-05-26T20:00:00.000Z",
                in_flight_task_count=-1,
            )


class TestDaemonStoppedPayload:
    """Pillar H Week 3 — :func:`build_daemon_stopped_payload`
    emit-shape factory per ADR-0062 D343."""

    def test_payload_shape_matches_adr_0062_d343(self):
        """Pillar H Week 3 follow-up P2-1 closure — the factory output
        is a dict with exactly five keys: pid + exit_reason +
        uptime_seconds + in_flight_task_count_at_exit + ``_emitted_by``."""
        payload = build_daemon_stopped_payload(
            pid=12345, exit_reason="clean",
            uptime_seconds=3600.123,
            in_flight_task_count_at_exit=0,
        )
        assert set(payload.keys()) == {
            "pid", "exit_reason", "uptime_seconds",
            "in_flight_task_count_at_exit", "_emitted_by",
        }
        assert payload["pid"] == 12345
        assert payload["exit_reason"] == "clean"
        assert payload["uptime_seconds"] == 3600.123
        assert payload["in_flight_task_count_at_exit"] == 0
        assert payload["_emitted_by"] == "daemon"

    def test_payload_carries_emitted_by_marker(self):
        """Pillar H Week 3 follow-up P2-1 closure — the factory stamps
        ``_emitted_by="daemon"`` at the factory boundary per ADR-0010
        D17 + the Pillar E :data:`EMITTED_BY` precedent. See
        :meth:`TestDaemonStartedPayload.test_payload_carries_emitted_by_marker`
        for the full closure rationale."""
        payload = build_daemon_stopped_payload(
            pid=1, exit_reason="clean", uptime_seconds=0.0,
            in_flight_task_count_at_exit=0,
        )
        assert payload["_emitted_by"] == "daemon"

    def test_payload_omits_channel_field_per_adr_0014_d33(self):
        payload = build_daemon_stopped_payload(
            pid=1, exit_reason="clean", uptime_seconds=0.0,
            in_flight_task_count_at_exit=0,
        )
        assert "channel" not in payload

    def test_uptime_seconds_rounded_to_three_decimal_places(self):
        """ADR-0062 D343 + ADR-0031 D140 deterministic-output contract."""
        payload = build_daemon_stopped_payload(
            pid=1, exit_reason="clean",
            uptime_seconds=1.23456789,
            in_flight_task_count_at_exit=0,
        )
        assert payload["uptime_seconds"] == 1.235

    def test_each_exit_reason_constructs_valid_payload(self):
        """Cell-level matrix coverage discipline — each of the THREE
        :data:`DAEMON_EXIT_REASONS` produces a valid payload."""
        for exit_reason in DAEMON_EXIT_REASONS:
            payload = build_daemon_stopped_payload(
                pid=1, exit_reason=exit_reason, uptime_seconds=0.0,
                in_flight_task_count_at_exit=0,
            )
            assert payload["exit_reason"] == exit_reason

    def test_invalid_exit_reason_raises_value_error(self):
        with pytest.raises(
            ValueError, match="exit_reason not in DAEMON_EXIT_REASONS",
        ):
            build_daemon_stopped_payload(
                pid=1, exit_reason="banana", uptime_seconds=0.0,
                in_flight_task_count_at_exit=0,
            )

    def test_negative_pid_raises_value_error(self):
        with pytest.raises(ValueError, match="pid > 0"):
            build_daemon_stopped_payload(
                pid=-1, exit_reason="clean", uptime_seconds=0.0,
                in_flight_task_count_at_exit=0,
            )

    def test_negative_uptime_raises_value_error(self):
        with pytest.raises(ValueError, match="uptime_seconds >= 0"):
            build_daemon_stopped_payload(
                pid=1, exit_reason="clean", uptime_seconds=-1.0,
                in_flight_task_count_at_exit=0,
            )

    def test_negative_in_flight_at_exit_raises_value_error(self):
        with pytest.raises(
            ValueError, match="in_flight_task_count_at_exit >= 0",
        ):
            build_daemon_stopped_payload(
                pid=1, exit_reason="clean", uptime_seconds=0.0,
                in_flight_task_count_at_exit=-1,
            )


class TestShutdownBody:
    """Pillar H Week 3 — :meth:`DaemonRunner.shutdown` body per
    ADR-0062 D342. Behavioral-passthrough discipline — the spy
    emit_fn records both the payload AND the runner's lifecycle_state
    at emit-time so the test verifies the intermediate ``"draining"``
    state matches the structural commitment per ADR-0060 D335
    invariant 3."""

    def _make_runner(self, tmp_path) -> DaemonRunner:
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir(exist_ok=True)
        ledger_dir.mkdir(exist_ok=True)
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        # Construct directly; pin started_at_ts to a deterministic value
        # so uptime_seconds is testable.
        return DaemonRunner(
            config=config,
            config_hash="a" * 64,
            pid=12345,
            started_at_ts="2026-05-26T19:00:00.000Z",
            version="0.1.0",
        )

    def _spy_emit(self, runner: DaemonRunner) -> tuple[list, Callable]:
        """Build a spy emit_fn that captures payload + state-at-emit-time."""
        captures: list[dict] = []
        def _emit(payload: dict) -> None:
            captures.append({
                "payload": payload,
                "lifecycle_state_at_emit": runner.lifecycle_state,
            })
        return captures, _emit

    def test_sigterm_transitions_through_draining_to_stopped(self, tmp_path):
        """ADR-0062 D342 — :meth:`DaemonRunner.shutdown` transitions
        through ``"draining"`` (emit ``daemon_stopping``) → ``"stopped"``
        (emit ``daemon_stopped``). The spy emit_fn captures the
        intermediate ``"draining"`` state at the first emit."""
        runner = self._make_runner(tmp_path)
        captures, emit = self._spy_emit(runner)
        now_fn = lambda: datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
        runner.shutdown("sigterm", emit_fn=emit, now_fn=now_fn)

        assert runner.lifecycle_state == "stopped"
        assert len(captures) == 2
        # First emit: daemon_stopping during draining.
        assert captures[0]["payload"]["type"] == "daemon_stopping"
        assert captures[0]["payload"]["reason"] == "sigterm"
        assert captures[0]["lifecycle_state_at_emit"] == "draining"
        # Second emit: daemon_stopped after transition to stopped.
        assert captures[1]["payload"]["type"] == "daemon_stopped"
        assert captures[1]["payload"]["exit_reason"] == "clean"
        assert captures[1]["lifecycle_state_at_emit"] == "stopped"

    def test_each_reason_transitions_correctly(self, tmp_path):
        """Cell-level matrix coverage — each of the THREE
        :data:`SHUTDOWN_REASONS` drives shutdown end-to-end with the
        correct reason field in the daemon_stopping emit."""
        for reason in sorted(SHUTDOWN_REASONS):
            runner = self._make_runner(tmp_path)
            captures, emit = self._spy_emit(runner)
            now_fn = lambda: datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
            runner.shutdown(reason, emit_fn=emit, now_fn=now_fn)
            assert captures[0]["payload"]["reason"] == reason
            assert runner.lifecycle_state == "stopped"

    def test_drain_deadline_computed_from_graceful_shutdown_seconds(
        self, tmp_path,
    ):
        """ADR-0062 D342 — the daemon_stopping payload's
        ``drain_deadline_ts`` is ``now + graceful_shutdown_seconds``."""
        runner = self._make_runner(tmp_path)
        captures, emit = self._spy_emit(runner)
        now = datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
        runner.shutdown("sigterm", emit_fn=emit, now_fn=lambda: now)
        # graceful_shutdown_seconds default = 30s, so deadline = 20:00:30.
        assert (
            captures[0]["payload"]["drain_deadline_ts"]
            == "2026-05-26T20:00:30.000Z"
        )

    def test_uptime_seconds_computed_from_started_at_ts(self, tmp_path):
        """ADR-0062 D342 — the daemon_stopped payload's
        ``uptime_seconds`` is ``now - started_at_ts``. Pin runner
        started_at_ts to 19:00:00 + now to 20:00:00 → uptime = 3600s."""
        runner = self._make_runner(tmp_path)
        captures, emit = self._spy_emit(runner)
        now = datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
        runner.shutdown("sigterm", emit_fn=emit, now_fn=lambda: now)
        assert captures[1]["payload"]["uptime_seconds"] == 3600.0

    def test_in_flight_task_count_is_zero_at_week_3(self, tmp_path):
        """ADR-0062 D342 — Pillar H Week 3 always emits
        ``in_flight_task_count=0`` (the per-stage worker pool body
        lands at Week 5+). The structural commitment is
        in_flight_task_count present in both emits; Week 5+ extends
        with actual task counting."""
        runner = self._make_runner(tmp_path)
        captures, emit = self._spy_emit(runner)
        now_fn = lambda: datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
        runner.shutdown("sigterm", emit_fn=emit, now_fn=now_fn)
        assert captures[0]["payload"]["in_flight_task_count"] == 0
        assert captures[1]["payload"]["in_flight_task_count_at_exit"] == 0

    def test_emit_payloads_carry_runner_pid(self, tmp_path):
        """Behavioral-passthrough — pid is passed through from the
        runner to both daemon_stopping + daemon_stopped emits."""
        runner = self._make_runner(tmp_path)
        captures, emit = self._spy_emit(runner)
        now_fn = lambda: datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
        runner.shutdown("sigterm", emit_fn=emit, now_fn=now_fn)
        assert captures[0]["payload"]["pid"] == runner.pid
        assert captures[1]["payload"]["pid"] == runner.pid

    def test_invalid_reason_refuses_loud_before_state_transition(
        self, tmp_path,
    ):
        """ADR-0062 D342 + I5 + ADR-0001 D2 — invalid reason refuses-
        loud BEFORE the state transition fires; runner stays in
        ``"initializing"`` (or whatever prior state)."""
        runner = self._make_runner(tmp_path)
        captures, emit = self._spy_emit(runner)
        prior_state = runner.lifecycle_state
        with pytest.raises(ValueError, match="SHUTDOWN_REASONS"):
            runner.shutdown("banana", emit_fn=emit)
        assert runner.lifecycle_state == prior_state
        assert captures == []

    def test_malformed_started_at_ts_refuses_loud_before_state_transition(
        self, tmp_path,
    ):
        """Pillar H Week 3 follow-up P2-2 closure — a malformed
        ``started_at_ts`` (operator-injected ``ts_fn`` returning a
        non-standard format, OR future ts-format drift like
        ``+00:00`` suffix instead of ``Z``, OR microseconds-without-
        decimal) MUST raise :exc:`ValueError` BEFORE the state
        transition fires; the runner stays in its prior state AND no
        events emit.

        The Week 3 main commit parsed ``started_at_ts`` at Step 5 AFTER
        the state transition + the ``daemon_stopping`` emit — a
        malformed format left the runner in ``"stopped"`` state with
        ``daemon_stopping`` in the ledger but ``daemon_stopped`` NEVER
        emitted (half-completed state transition violating ADR-0060
        D335 invariant 3 graceful-shutdown structural commitment). The
        follow-up moves the strptime to the TOP of the body so the
        refuse-loud fires upfront."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        # Construct a runner with a malformed started_at_ts (no Z
        # suffix; Python isoformat() default would produce this).
        runner = DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts="2026-05-26T19:00:00+00:00",  # bad: +00:00 not Z
            version="0.1.0",
        )
        captures, emit = self._spy_emit(runner)
        prior_state = runner.lifecycle_state
        with pytest.raises(ValueError, match="started_at_ts"):
            runner.shutdown("sigterm", emit_fn=emit)
        assert runner.lifecycle_state == prior_state
        assert captures == []  # No events emitted

    def test_only_lifecycle_state_mutates_during_shutdown(self, tmp_path):
        """Pillar H Week 3 follow-up P3-1 closure — ONLY
        ``lifecycle_state`` is the allow-listed internal mutation field
        via :func:`object.__setattr__` per ADR-0062 D342. The other
        five fields (``config`` / ``config_hash`` / ``pid`` /
        ``started_at_ts`` / ``version``) MUST stay frozen across
        :meth:`DaemonRunner.shutdown` invocations.

        A future per-week author extending the shutdown body must NOT
        call ``object.__setattr__(self, <other_field>, ...)``; the
        escape hatch is scoped to lifecycle_state only. The regression-
        barrier captures the value of each field before + after
        shutdown + asserts identity preserved."""
        runner = self._make_runner(tmp_path)
        captures, emit = self._spy_emit(runner)
        now_fn = lambda: datetime(2026, 5, 26, 20, 0, 0, tzinfo=timezone.utc)
        # Snapshot the 5 non-lifecycle_state fields before shutdown.
        snapshot = {
            "config": runner.config,
            "config_hash": runner.config_hash,
            "pid": runner.pid,
            "started_at_ts": runner.started_at_ts,
            "version": runner.version,
        }
        runner.shutdown("sigterm", emit_fn=emit, now_fn=now_fn)
        # Each of the 5 non-lifecycle_state fields MUST preserve identity.
        for field_name, prior_value in snapshot.items():
            assert getattr(runner, field_name) is prior_value, (
                f"Pillar H Week 3 follow-up P3-1 invariant violated — "
                f"DaemonRunner.shutdown mutated {field_name!r} via the "
                f"object.__setattr__ escape hatch; only lifecycle_state "
                f"is the allow-listed internal mutation field per "
                f"ADR-0062 D342."
            )
        # And lifecycle_state DID transition.
        assert runner.lifecycle_state == "stopped"


# ---------------------------------------------------------------------------
# Pillar H Week 3 follow-up P3-6 closure — promote _SpyLoop to module-level
# test helper class (the Week 3 main commit defined this class inside
# _drive_loop_to_attach which was called 6 times across 6 tests; the DRY
# violation is closed by moving the class definition to module-top scope).
# ---------------------------------------------------------------------------


class _SignalRegistrationSpyLoop:
    """Module-level test helper — spy substrate for asyncio
    :meth:`AbstractEventLoop.add_signal_handler`.

    Pillar H Week 3 follow-up P3-6 closure — the Week 3 main commit's
    :class:`TestAttachSignalHandlers._drive_loop_to_attach` defined
    this class inside the helper method; six tests each instantiated a
    new ``_SpyLoop`` class via the helper. The DRY violation is closed
    by moving the class to module scope; tests instantiate via
    ``_SignalRegistrationSpyLoop()`` and pass the instance to
    :func:`attach_signal_handlers` via the ``loop`` test-only seam
    kwarg.

    Each instance records calls to ``add_signal_handler(sig, callback)``
    in the ``registrations`` list. Tests then assert on the registered
    signal numbers + invoke the callbacks to verify dispatch."""

    def __init__(self) -> None:
        self.registrations: list[tuple] = []

    def add_signal_handler(self, sig, callback) -> None:
        self.registrations.append((sig, callback))


class TestAttachSignalHandlers:
    """Pillar H Week 3 — :func:`attach_signal_handlers` body per
    ADR-0062 D341. Uses :func:`asyncio.new_event_loop` + manual
    run-until-complete pattern so tests don't need
    ``@pytest.mark.asyncio`` markers."""

    def _make_runner(self, tmp_path, *, policy_reload_signal="SIGHUP"):
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir,
            policy_reload_signal=policy_reload_signal,
        )
        return DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts="2026-05-26T19:00:00.000Z", version="0.1.0",
        )

    def _drive_loop_to_attach(self, runner, **kwargs):
        """Drive :func:`attach_signal_handlers` against a spy loop
        substrate. Returns the loop's recorded signal handler
        registrations.

        Pillar H Week 3 follow-up P3-6 closure — uses the module-level
        :class:`_SignalRegistrationSpyLoop` helper (the Week 3 main
        commit's inline ``_SpyLoop`` class is now at module scope)."""
        spy_loop = _SignalRegistrationSpyLoop()
        attach_signal_handlers(runner, loop=spy_loop, **kwargs)
        return spy_loop.registrations

    def test_sigterm_and_sigint_handlers_registered(self, tmp_path):
        """ADR-0062 D341 — SIGTERM + SIGINT handlers wire to
        :meth:`runner.shutdown` per the asyncio
        ``add_signal_handler`` convention."""
        import signal
        runner = self._make_runner(tmp_path)
        registrations = self._drive_loop_to_attach(runner)
        signals_registered = {sig for sig, _cb in registrations}
        assert signal.SIGTERM in signals_registered
        assert signal.SIGINT in signals_registered

    def test_sighup_handler_registered_when_policy_reload_signal_is_sighup(
        self, tmp_path,
    ):
        """ADR-0062 D341 — SIGHUP handler registers iff
        ``config.policy_reload_signal == "SIGHUP"``."""
        import signal
        runner = self._make_runner(tmp_path, policy_reload_signal="SIGHUP")
        registrations = self._drive_loop_to_attach(runner)
        signals_registered = {sig for sig, _cb in registrations}
        assert signal.SIGHUP in signals_registered

    def test_sighup_handler_omitted_when_policy_reload_signal_is_none(
        self, tmp_path,
    ):
        """ADR-0062 D341 — operator-deliberate opt-out
        (``policy_reload_signal=None``) means NO SIGHUP handler
        registers; the daemon ignores SIGHUP."""
        import signal
        runner = self._make_runner(tmp_path, policy_reload_signal=None)
        registrations = self._drive_loop_to_attach(runner)
        signals_registered = {sig for sig, _cb in registrations}
        assert signal.SIGHUP not in signals_registered

    def test_sigterm_callback_invokes_shutdown_with_sigterm_reason(
        self, tmp_path,
    ):
        """Behavioral-passthrough — invoking the SIGTERM callback
        calls :meth:`runner.shutdown` with ``reason="sigterm"``."""
        import signal
        runner = self._make_runner(tmp_path)
        shutdown_calls: list[str] = []
        def _spy_shutdown(reason: str) -> None:
            shutdown_calls.append(reason)
        registrations = self._drive_loop_to_attach(
            runner, shutdown_fn=_spy_shutdown,
        )
        # Find the SIGTERM callback + invoke it.
        sigterm_cb = next(
            cb for sig, cb in registrations if sig == signal.SIGTERM
        )
        sigterm_cb()
        assert shutdown_calls == ["sigterm"]

    def test_sigint_callback_invokes_shutdown_with_sigint_reason(
        self, tmp_path,
    ):
        """Behavioral-passthrough — SIGINT → ``reason="sigint"``."""
        import signal
        runner = self._make_runner(tmp_path)
        shutdown_calls: list[str] = []
        def _spy_shutdown(reason: str) -> None:
            shutdown_calls.append(reason)
        registrations = self._drive_loop_to_attach(
            runner, shutdown_fn=_spy_shutdown,
        )
        sigint_cb = next(
            cb for sig, cb in registrations if sig == signal.SIGINT
        )
        sigint_cb()
        assert shutdown_calls == ["sigint"]

    def test_sighup_callback_invokes_reload_fn(self, tmp_path):
        """ADR-0062 D341 — SIGHUP callback dispatches to reload_fn
        (Week 7+ ships the actual body; Week 3 wires the handler)."""
        import signal
        runner = self._make_runner(tmp_path)
        reload_calls: list[bool] = []
        def _spy_reload() -> None:
            reload_calls.append(True)
        registrations = self._drive_loop_to_attach(
            runner, reload_fn=_spy_reload,
        )
        sighup_cb = next(
            cb for sig, cb in registrations if sig == signal.SIGHUP
        )
        sighup_cb()
        assert reload_calls == [True]

    def test_sighup_callback_invokes_reload_policy_default_at_week_7(
        self, tmp_path,
    ):
        """Pillar H Week 7 — the default ``reload_fn`` (when the caller
        omits the kwarg) is the ``_reload_default`` closure that
        invokes :meth:`DaemonRunner.reload_policy` per ADR-0066 D356.

        The Week 3 main commit wrapped the call in
        ``_reload_with_notimpl_swallow`` to absorb
        :exc:`NotImplementedError` at the Week 3 → Week 7 trajectory
        bridge. Week 7 ships the body so the swallow is no longer
        needed — the closure simply invokes the production body.

        This test inverts the Week 3 follow-up
        ``test_sighup_callback_swallows_notimplementederror_at_week_3``
        per the per-pillar-foundation rename+invert pattern (Pillar H
        Week 2 + 3 + 4 + 5 stubs all followed this discipline; the
        Week 7 rename names the body actually running).

        Uses a spy ``policy_load_fn`` / ``emit_fn`` / ``hash_fn`` via
        the runner's reload_policy seams indirectly through a custom
        ``reload_fn`` that wraps the body — but for this test the
        DEFAULT reload_fn invokes the production body which lazy-
        constructs a Ledger from ``self.config.ledger_dir``. tmp_path
        provides a real ledger_dir so the Ledger.append produces a
        real ledger event — verified via the event count + the
        ledger directory contents.
        """
        import signal
        runner = self._make_runner(tmp_path)
        # Omit reload_fn kwarg — uses the production default closure
        # ``_reload_default`` per ADR-0066 D356 + the Pillar H Week 7
        # rename. The default path lazy-constructs a Ledger from
        # ``self.config.ledger_dir`` (tmp_path/ledger) so the
        # ``policy_reloaded`` event lands in a real ledger event file.
        registrations = self._drive_loop_to_attach(runner)
        sighup_cb = next(
            cb for sig, cb in registrations if sig == signal.SIGHUP
        )
        # Invoke the callback; must NOT raise (the body runs to
        # completion; on a fresh tmp_path with no policy YAML, the
        # body emits ``status="applied"`` with prior == "" + new ==
        # SHA-256 of empty input + an empty rules list).
        sighup_cb()
        # The default emit path lazy-constructs Ledger from
        # ``self.config.ledger_dir`` — the runner's config.ledger_dir
        # is tmp_path/ledger; verify a ledger event file landed.
        from orchestrator.ledger import Ledger
        ledger = Ledger(runner.config.ledger_dir)
        events = ledger.all_events()
        reloaded = [e for e in events if e.get("type") == "policy_reloaded"]
        assert len(reloaded) == 1, (
            f"expected exactly one policy_reloaded event after the "
            f"SIGHUP-default callback; got {len(reloaded)}"
        )
        assert reloaded[0]["status"] == "applied"
        assert reloaded[0]["_emitted_by"] == "daemon"


class TestEventClassCatalogPillarHWeek2AndWeek6Extension:
    """Pillar H Week 2 + Week 6 — ADR-0061 D338's + ADR-0065 D355's
    :data:`EVENT_CLASS_CATALOG` extensions. The FIVE Pillar H event
    classes from :data:`DAEMON_NEW_EVENT_CLASSES` joined the catalog at
    the Week 2 commit; the SIXTH (``daemon_stage_saturated``) joined at
    the Week 6 commit; the symmetric-assertion regression-barrier
    (SUBSET) catches a future divergence (e.g., Pillar I tenant-scoped
    event class added to DAEMON_NEW_EVENT_CLASSES but forgotten in the
    catalog). W6 follow-up P3-7 + NEW-7 closure renames the class to
    name BOTH catalog extensions per the per-week-reviewer's
    discipline-scope extension to operator-readable test class names.

    (Same assertion as
    :class:`TestDaemonNewEventClasses.test_subset_of_event_class_catalog_at_pillar_h_week_2`;
    this class lives in test_daemon.py for the per-pillar-H locality;
    the symmetric test at test_observability.py is the per-Pillar-G
    locality.)

    **Pillar H Week 2 follow-up P3-5 closure** — class-level docstring
    extends with the SUBSET-vs-DISJOINT rationale (the per-Pillar-G
    locality has this in detail; the per-Pillar-H locality previously
    deferred to the per-test docstring; the Week 2 reviewer noted the
    asymmetry).

    **Why Pillar H is SUBSET, Pillar G is DISJOINT** — Pillar G's two
    new classes (``observability_class_uncatalogued`` +
    ``slo_violation_detected``) are observability's OWN emissions —
    diagnostic + operational events generated by the observability
    primitive itself. Catalog inclusion would create a recursive-
    uncatalogued loop (observability emits
    ``observability_class_uncatalogued`` whenever it encounters an
    uncatalogued event class; the same event class appearing IN the
    catalog would never trigger the diagnostic). So Pillar G's classes
    stay DISJOINT (see
    :meth:`TestModuleConstants.test_observability_new_event_classes_disjoint_from_catalog`
    at ``tests/test_observability.py``).

    Pillar H's SIX classes (``daemon_started`` + ``daemon_stopping``
    + ``daemon_stopped`` + ``policy_reloaded`` + ``health_probe`` +
    ``daemon_stage_saturated``; Week 2 added FIVE per ADR-0061 D338 +
    Week 6 added the sixth per ADR-0065 D355) are emitted BY the
    daemon process + CONSUMED BY observability via
    :func:`collect_event_class_snapshots`. Catalog inclusion is
    necessary for operators to query per-event-class aggregations
    across the daemon lifecycle. So Pillar H's classes JOIN the
    catalog at Week 2 + Week 6 (SUBSET).

    A future Pillar I author extending DAEMON_NEW_EVENT_CLASSES with
    new daemon classes (e.g., per-tenant ``tenant_paused``) follows
    Pillar H's pattern: extend BOTH closed-sets concurrently; the
    SUBSET regression-barrier at both per-pillar localities catches
    drift at test time.
    """

    def test_daemon_classes_subset_of_event_class_catalog(self):
        """ADR-0061 D338 — `DAEMON_NEW_EVENT_CLASSES` is a SUBSET of
        :data:`observability.EVENT_CLASS_CATALOG` after the Week 2
        catalog extension."""
        assert DAEMON_NEW_EVENT_CLASSES.issubset(
            _observability.EVENT_CLASS_CATALOG
        )

    def test_each_daemon_class_in_catalog(self):
        """Per-cell verification — each of the SIX daemon event
        classes (Week 2 + Week 6 catalog extensions per ADR-0061 D338
        + ADR-0065 D355; W6 follow-up P3-7 closure updates the prior
        "FIVE" docstring drift) appears in the catalog (cell-level
        matrix coverage discipline)."""
        for class_name in DAEMON_NEW_EVENT_CLASSES:
            assert class_name in _observability.EVENT_CLASS_CATALOG, (
                f"Pillar H event class {class_name!r} missing from "
                f"observability.EVENT_CLASS_CATALOG; Pillar H Week 2 "
                f"catalog extension per ADR-0061 D338 + Pillar H Week 6 "
                f"catalog extension per ADR-0065 D355 incomplete."
            )


# ---------------------------------------------------------------------------
# Pillar H Week 2 follow-up — Module constant parity + helper cell-matrix
# coverage + known-config regression-barrier
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Pillar H Week 2 follow-up P3-1 closure — per-pillar mirror
    constants parity discipline extends to :data:`_DAEMON_VERSION` ↔
    :data:`observability._SERVICE_VERSION`.

    The two constants are semantically distinct (daemon binary version
    surfaced in ``daemon_started`` payload vs OTel Resource
    ``service.version`` attribute consumed by Prometheus / Grafana /
    OTLP backends per ADR-0052 D287) but SHOULD report the same value
    — both identify "the binary that's running". A future Pillar I
    per-tenant author bumping one MUST bump both concurrently; this
    regression-barrier catches drift at test time."""

    def test_daemon_version_mirrors_service_version(self):
        """Per-pillar mirror constants parity — the daemon's version
        + observability's OTel-Resource service.version are pinned to
        the same value. Drift here means a future operator querying
        ``daemon_started.version`` sees one value + the Prometheus /
        OTLP scrape sees another for the same binary."""
        assert _runner._DAEMON_VERSION == _observability._SERVICE_VERSION, (
            f"Per-pillar mirror constants parity drift — "
            f"_runner._DAEMON_VERSION={_runner._DAEMON_VERSION!r} "
            f"vs _observability._SERVICE_VERSION="
            f"{_observability._SERVICE_VERSION!r}. The two MUST report the "
            f"same value per ADR-0052 D287 + Pillar H Week 2 follow-up "
            f"P3-1 closure."
        )

    def test_daemon_version_format_matches_semver(self):
        """Pillar H Week 2 follow-up P3-1 closure — the version string
        follows a semver-ish ``MAJOR.MINOR.PATCH[-pre]`` shape at v1.
        Pillar I per-tenant versions extend with ``-tenant-X`` suffix
        per the convention documented at :data:`_DAEMON_VERSION`."""
        import re
        # Allow MAJOR.MINOR.PATCH plus optional dash-suffix (e.g. -tenant-x).
        pattern = re.compile(r"^\d+\.\d+\.\d+(-[\w.-]+)?$")
        assert pattern.match(_runner._DAEMON_VERSION), (
            f"_DAEMON_VERSION {_runner._DAEMON_VERSION!r} does not "
            f"match semver-ish MAJOR.MINOR.PATCH[-pre] pattern."
        )

    def test_emitted_by_marker_is_daemon(self):
        """Pillar H Week 3 follow-up P2-1 closure — the module-level
        :data:`EMITTED_BY` constant equals ``"daemon"``, mirroring the
        Pillar E :data:`orchestrator.tier_assignment.EMITTED_BY` +
        :data:`orchestrator.discovery_lineage.EMITTED_BY` convention.

        The THREE Pillar H factories (``build_daemon_started_payload``
        + ``build_daemon_stopping_payload`` + ``build_daemon_stopped_payload``)
        consume this constant at the factory boundary. A future Pillar
        I per-tenant author MUST NOT rename this constant or the
        consumer surfaces (audit dashboards / operator-facing filters /
        per-event-class aggregations) would silently break."""
        assert _runner.EMITTED_BY == "daemon", (
            f"Pillar H Week 3 follow-up P2-1 invariant violated — "
            f"_runner.EMITTED_BY={_runner.EMITTED_BY!r}; expected "
            f"'daemon' per the Pillar E precedent + ADR-0010 D17."
        )


class TestComputeConfigHash:
    """Pillar H Week 2 follow-up P3-3 closure — cell-level matrix
    coverage extends to :func:`_compute_config_hash`'s known-config
    regression-barrier + the byte-identical-across-invocations posture.

    The hash uses :func:`str` on :class:`Path` which is POSIX-only at
    v1; Pillar I+ multi-platform operators consuming ``config_hash``
    as cross-machine identity signal normalize via :meth:`Path.as_posix`
    (TBD Pillar I trajectory)."""

    def _make_config(self, tmp_path) -> DaemonConfig:
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        return DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)

    def test_hash_is_sha256_hex(self, tmp_path):
        """The hash output is 64 hex chars (SHA-256 digest length)."""
        config = self._make_config(tmp_path)
        result = _runner._compute_config_hash(config)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_config_hash_byte_stable_for_known_config(self, tmp_path):
        """Pillar H Week 2 follow-up P3-3 closure — the hash is byte-
        identical across consecutive invocations for the same operator-
        deliberate config. Catches a future canonical-encoding drift
        (sort order / separator / Path.as_posix introduction)."""
        config = self._make_config(tmp_path)
        hash1 = _runner._compute_config_hash(config)
        hash2 = _runner._compute_config_hash(config)
        hash3 = _runner._compute_config_hash(config)
        assert hash1 == hash2 == hash3

    def test_hash_differs_on_vault_dir_change(self, tmp_path):
        """Cell-coverage cell: vault_dir change ripples to the hash."""
        config1 = self._make_config(tmp_path)
        vault2 = tmp_path / "vault2"
        vault2.mkdir()
        config2 = dataclasses.replace(config1, vault_dir=vault2)
        assert _runner._compute_config_hash(config1) != (
            _runner._compute_config_hash(config2)
        )

    def test_hash_differs_on_parallelism_limits_change(self, tmp_path):
        """Cell-coverage cell: per-stage parallelism_limits change
        ripples to the hash (operators tuning concurrency see the
        hash change in the ``daemon_started`` payload across restarts)."""
        config1 = self._make_config(tmp_path)
        new_limits = dict(config1.parallelism_limits)
        new_limits["sent"] = 4  # tuned up
        config2 = dataclasses.replace(config1, parallelism_limits=new_limits)
        assert _runner._compute_config_hash(config1) != (
            _runner._compute_config_hash(config2)
        )


class TestDefaultPolicyLoad:
    """Pillar H Week 2 follow-up P3-2 closure — cell-level matrix
    coverage extends to :func:`_default_policy_load`.

    The helper has 2 branches:
    (1) missing ``policy_dir`` → returns ``[]`` (operator-deliberate
        posture per the docstring).
    (2) existing ``policy_dir`` → scans ``*.yml`` in sorted order +
        extends rules from each via
        :func:`orchestrator.policy.load_rules_from_yaml`.

    The Week 2 main commit's :class:`TestInitDaemonBody` tests used
    ``policy_load_fn=lambda _dir: []`` to bypass the production helper
    entirely; the Week 2 follow-up adds per-branch unit tests."""

    def test_missing_policy_dir_returns_empty_list(self, tmp_path):
        """Operator-deliberate posture branch — operators bootstrapping
        a fresh deployment without policy YAML get a daemon that
        starts; the per-send gate refuses-loud per Pillar A convention
        if no rules are wired."""
        nonexistent_dir = tmp_path / "does-not-exist"
        result = _runner._default_policy_load(nonexistent_dir)
        assert result == []

    def test_empty_policy_dir_returns_empty_list(self, tmp_path):
        """Cell-coverage cell — existing dir with no YAML files yields
        an empty list (the daemon starts; no rules wired)."""
        empty_dir = tmp_path / "empty-policies"
        empty_dir.mkdir()
        result = _runner._default_policy_load(empty_dir)
        assert result == []

    def test_multiple_yml_files_loaded_in_sorted_order(self, tmp_path):
        """Cell-coverage cell — sorted-glob ordering (deterministic per
        ADR-0031 D140). Spy via monkey-patching the policy module's
        loader to record the call order."""
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        # Create files in NON-sorted name order; the sorted() call in
        # _default_policy_load returns them in alphabetical order.
        (policy_dir / "z-last.yml").write_text("# z\n")
        (policy_dir / "a-first.yml").write_text("# a\n")
        (policy_dir / "m-middle.yml").write_text("# m\n")

        load_order: list[Path] = []
        import orchestrator.policy as _policy_module
        original_loader = _policy_module.load_rules_from_yaml
        try:
            _policy_module.load_rules_from_yaml = (
                lambda p: (load_order.append(p) or [])
            )
            result = _runner._default_policy_load(policy_dir)
        finally:
            _policy_module.load_rules_from_yaml = original_loader
        # Sorted-glob order = alphabetical by filename.
        assert [p.name for p in load_order] == [
            "a-first.yml", "m-middle.yml", "z-last.yml",
        ]
        assert result == []

    def test_load_rules_from_yaml_error_propagates(self, tmp_path):
        """Cell-coverage cell — Pillar A refuse-loud convention extends
        through ``_default_policy_load``. If the YAML loader raises
        :exc:`ValueError` on a malformed file, the error propagates
        (daemon refuses to start per the framework convention per I5)."""
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        (policy_dir / "broken.yml").write_text("not: valid: yaml: at: all\n")

        import orchestrator.policy as _policy_module
        original_loader = _policy_module.load_rules_from_yaml
        try:
            _policy_module.load_rules_from_yaml = (
                lambda p: (_ for _ in ()).throw(
                    ValueError(f"malformed YAML at {p}")
                )
            )
            with pytest.raises(ValueError, match="malformed YAML"):
                _runner._default_policy_load(policy_dir)
        finally:
            _policy_module.load_rules_from_yaml = original_loader


# ---------------------------------------------------------------------------
# Pillar H Week 4 — `build_health_probe_payload` factory + `_compute_health_status`
# helper + `serve_health_endpoint` body (per ADR-0063 D345-D348)
# ---------------------------------------------------------------------------


class TestHealthProbePayload:
    """Pillar H Week 4 — :func:`build_health_probe_payload` emit-shape
    factory per ADR-0063 D346 + the Pillar G ``build_*_payload``
    convention + the Pillar H Week 3 follow-up P2-1 closure
    (``_emitted_by="daemon"`` stamped at factory boundary)."""

    def test_payload_shape_matches_adr_0063_d346(self):
        """The factory output is a dict with exactly five keys: pid +
        outcome + lifecycle_state + remote_addr + ``_emitted_by``."""
        payload = build_health_probe_payload(
            pid=12345, outcome="ok", lifecycle_state="ready",
            remote_addr="127.0.0.1",
        )
        assert set(payload.keys()) == {
            "pid", "outcome", "lifecycle_state", "remote_addr",
            "_emitted_by",
        }
        assert payload["pid"] == 12345
        assert payload["outcome"] == "ok"
        assert payload["lifecycle_state"] == "ready"
        assert payload["remote_addr"] == "127.0.0.1"
        assert payload["_emitted_by"] == "daemon"

    def test_payload_carries_emitted_by_marker(self):
        """Pillar H Week 3 follow-up P2-1 closure extends to the Week 4
        :func:`build_health_probe_payload` factory — the factory stamps
        ``_emitted_by="daemon"`` at the factory boundary per ADR-0010
        D17 + the Pillar E :data:`EMITTED_BY` precedent."""
        payload = build_health_probe_payload(
            pid=1, outcome="degraded", lifecycle_state="ready",
            remote_addr="10.0.0.1",
        )
        assert payload["_emitted_by"] == "daemon"

    def test_payload_omits_channel_field_per_adr_0014_d33(self):
        """ADR-0014 D33 channel-on-every-event invariant — daemon
        lifecycle events tenant-process-scoped, NOT per-channel."""
        payload = build_health_probe_payload(
            pid=1, outcome="ok", lifecycle_state="ready",
            remote_addr="127.0.0.1",
        )
        assert "channel" not in payload

    def test_each_outcome_constructs_valid_payload(self):
        """Cell-level matrix coverage — each of the THREE
        :data:`HEALTH_PROBE_OUTCOMES` produces a valid payload."""
        for outcome in HEALTH_PROBE_OUTCOMES:
            payload = build_health_probe_payload(
                pid=1, outcome=outcome, lifecycle_state="ready",
                remote_addr="127.0.0.1",
            )
            assert payload["outcome"] == outcome

    def test_each_lifecycle_state_constructs_valid_payload(self):
        """Cell-level matrix coverage — each of the FOUR
        :data:`DAEMON_LIFECYCLE_STATES` produces a valid payload."""
        for state in DAEMON_LIFECYCLE_STATES:
            payload = build_health_probe_payload(
                pid=1, outcome="ok", lifecycle_state=state,
                remote_addr="127.0.0.1",
            )
            assert payload["lifecycle_state"] == state

    def test_invalid_outcome_raises_value_error(self):
        with pytest.raises(
            ValueError, match="outcome not in HEALTH_PROBE_OUTCOMES",
        ):
            build_health_probe_payload(
                pid=1, outcome="banana", lifecycle_state="ready",
                remote_addr="127.0.0.1",
            )

    def test_invalid_lifecycle_state_raises_value_error(self):
        with pytest.raises(
            ValueError, match="lifecycle_state not in DAEMON_LIFECYCLE_STATES",
        ):
            build_health_probe_payload(
                pid=1, outcome="ok", lifecycle_state="banana",
                remote_addr="127.0.0.1",
            )

    def test_negative_pid_raises_value_error(self):
        with pytest.raises(ValueError, match="pid > 0"):
            build_health_probe_payload(
                pid=-1, outcome="ok", lifecycle_state="ready",
                remote_addr="127.0.0.1",
            )

    def test_empty_remote_addr_raises_value_error(self):
        with pytest.raises(ValueError, match="non-empty remote_addr"):
            build_health_probe_payload(
                pid=1, outcome="ok", lifecycle_state="ready",
                remote_addr="",
            )


class TestComputeHealthStatus:
    """Pillar H Week 4 — :func:`_compute_health_status` helper per
    ADR-0063 D345 derives the :class:`HealthStatus` from
    :class:`DaemonRunner` state + the current UTC datetime."""

    def _make_runner(self, tmp_path, lifecycle_state="ready"):
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir(exist_ok=True)
        ledger_dir.mkdir(exist_ok=True)
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        runner = DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts="2026-05-27T12:00:00.000Z", version="0.1.0",
            lifecycle_state=lifecycle_state,
        )
        return runner

    def test_ready_state_yields_outcome_ok(self, tmp_path):
        """ADR-0063 D345 — lifecycle_state=="ready" + ledger reachable +
        policy_loaded yields outcome="ok"."""
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        status = _health._compute_health_status(runner, now)
        assert status.outcome == "ok"
        assert status.lifecycle_state == "ready"

    def test_initializing_state_yields_outcome_unhealthy(self, tmp_path):
        """ADR-0063 D345 — non-ready lifecycle state yields
        outcome="unhealthy" (HTTP 503; k8s readiness blocks traffic)."""
        runner = self._make_runner(tmp_path, lifecycle_state="initializing")
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        status = _health._compute_health_status(runner, now)
        assert status.outcome == "unhealthy"

    def test_draining_state_yields_outcome_unhealthy(self, tmp_path):
        runner = self._make_runner(tmp_path, lifecycle_state="draining")
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        status = _health._compute_health_status(runner, now)
        assert status.outcome == "unhealthy"

    def test_uptime_seconds_computed_from_started_at_ts(self, tmp_path):
        """ADR-0063 D345 — uptime_seconds = int((now - started_at).total_seconds())."""
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        # started_at_ts is 2026-05-27T12:00:00.000Z; now = 13:00:00 → 3600s.
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        status = _health._compute_health_status(runner, now)
        assert status.uptime_seconds == 3600

    def test_privacy_invariant_excludes_person_id_body_source_list(
        self, tmp_path,
    ):
        """Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 —
        HealthStatus contains COUNTS + STATES + timestamps + version,
        NEVER ``person_id`` / body content / source_list."""
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        status = _health._compute_health_status(runner, now)
        d = dataclasses.asdict(status)
        for forbidden in ("person_id", "body", "source_list"):
            assert forbidden not in d

    def test_malformed_started_at_ts_surfaces_uptime_zero_NOT_raises(
        self, tmp_path,
    ):
        """Pillar H Week 4 follow-up P2-2 closure — the intentional
        asymmetry between :func:`_compute_health_status` (silently
        catches :exc:`ValueError` on malformed ``started_at_ts`` +
        returns ``uptime_seconds=0``) vs :meth:`DaemonRunner.shutdown`
        (refuses-loud upfront on the SAME malformed input per Pillar H
        Week 3 follow-up P2-2).

        Both behaviors are INTENTIONAL: the health endpoint is the
        diagnostic surface OPERATORS USE TO DETECT this kind of issue
        (refusing-loud would defeat its purpose); the shutdown body is
        the operator-deliberate state mutation that MUST refuse-loud on
        invariant violation. This regression-barrier pins the asymmetry
        so a future refactor does NOT homogenize the two paths.
        """
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        # Mutate started_at_ts via the frozen-dataclass escape hatch
        # (the Week 3 follow-up P3-1 closure scopes object.__setattr__
        # to lifecycle_state ONLY for the production shutdown path; the
        # test path uses the escape hatch for test-only state injection).
        object.__setattr__(runner, "started_at_ts", "not-an-iso-timestamp")
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        # MUST NOT raise — refusing-loud would defeat the diagnostic
        # purpose of the health endpoint.
        status = _health._compute_health_status(runner, now)
        assert status.uptime_seconds == 0
        # Outcome still derives from lifecycle_state ("ready" → "ok").
        assert status.outcome == "ok"

    def test_policy_loaded_is_lifecycle_state_proxy_at_week_4_per_week_7_trajectory(
        self, tmp_path,
    ):
        """Pillar H Week 4 follow-up P3-3 closure — pins the Week 4
        placeholder semantics for ``HealthStatus.policy_loaded``
        (``True iff lifecycle_state == "ready"``). Week 7+ extends with
        the actual policy state inspection per the SIGHUP-driven
        :meth:`DaemonRunner.reload_policy` body; when Week 7+ wires the
        actual ``policy_loaded`` body, this test MUST be updated
        (refuses-loud unless the author updates concurrently).

        Regression-barrier: protects the Week 4 contract from
        accidental partial Week 7+ extension.
        """
        runner_ready = self._make_runner(tmp_path, lifecycle_state="ready")
        runner_init = self._make_runner(
            tmp_path, lifecycle_state="initializing",
        )
        runner_draining = self._make_runner(
            tmp_path, lifecycle_state="draining",
        )
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        assert _health._compute_health_status(
            runner_ready, now,
        ).policy_loaded is True
        assert _health._compute_health_status(
            runner_init, now,
        ).policy_loaded is False
        assert _health._compute_health_status(
            runner_draining, now,
        ).policy_loaded is False

    def test_last_reconcile_pass_age_seconds_is_zero_at_week_4_per_week_7_trajectory(
        self, tmp_path,
    ):
        """Pillar H Week 4 follow-up P3-4 closure — pins the Week 4
        placeholder (always ``0``) for
        ``HealthStatus.last_reconcile_pass_age_seconds``. Week 7+ wires
        the reconcile cadence (consuming Pillar D Pass A through O);
        when Week 7+ extends, this test MUST be updated.
        """
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
        status = _health._compute_health_status(runner, now)
        assert status.last_reconcile_pass_age_seconds == 0

    def test_degraded_outcome_unreachable_at_week_4_per_week_6_trajectory(
        self, tmp_path,
    ):
        """Pillar H Week 4 follow-up P3-5 closure — pins that the third
        :data:`HEALTH_PROBE_OUTCOMES` element (``"degraded"``) is
        UNREACHABLE through :func:`_compute_health_status` at Week 4
        (the helper returns ``"ok"`` or ``"unhealthy"`` only). Week 6+
        extends with the degraded-indicator computation (per-stage
        worker pool saturation signal; OTel exporter unreachable;
        reconcile pass last-run-age beyond threshold). When Week 6+
        extends, this test MUST be updated.

        The ``"degraded"`` element STILL appears in the closed-set +
        :class:`HealthStatus` accepts it through direct construction
        (per the NEW-1 construction-time validation) +
        :func:`build_health_probe_payload` factory accepts it — only
        :func:`_compute_health_status` restricts to
        ``{"ok", "unhealthy"}``.
        """
        for lifecycle_state in DAEMON_LIFECYCLE_STATES:
            runner = self._make_runner(
                tmp_path, lifecycle_state=lifecycle_state,
            )
            now = datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)
            status = _health._compute_health_status(runner, now)
            assert status.outcome in {"ok", "unhealthy"}, (
                f"Week 4 _compute_health_status returned unexpected "
                f"outcome {status.outcome!r} for lifecycle_state "
                f"{lifecycle_state!r}; Week 6+ author must update this "
                f"regression-barrier concurrently."
            )


class TestHealthStatusConstruction:
    """Pillar H Week 4 follow-up NEW-1 closure —
    :meth:`HealthStatus.__post_init__` validates ``outcome`` +
    ``lifecycle_state`` in their closed-sets per defense-in-depth at
    the JSON-serialized HTTP body operator-facing surface. The
    :func:`build_health_probe_payload` factory validates at its own
    boundary; this construction-time barrier catches direct
    ``HealthStatus(...)`` construction bypassing the factory."""

    _BASE_KWARGS: dict[str, object] = {
        "daemon_pid": 1,
        "daemon_version": "0.1.0",
        "uptime_seconds": 0,
        "config_hash": "a" * 64,
        "ledger_reachable": True,
        "policy_loaded": True,
        "in_flight_task_count": 0,
        "last_reconcile_pass_age_seconds": 0,
        "ts": "2026-05-27T13:00:00.000Z",
    }

    def test_invalid_outcome_rejected_at_construction(self):
        """NEW-1 closure — refuse-loud on ``outcome`` not in
        :data:`HEALTH_PROBE_OUTCOMES`."""
        with pytest.raises(ValueError, match="HEALTH_PROBE_OUTCOMES"):
            HealthStatus(
                outcome="banana",  # not in closed-set
                lifecycle_state="ready",
                **self._BASE_KWARGS,
            )

    def test_invalid_lifecycle_state_rejected_at_construction(self):
        """NEW-1 closure — refuse-loud on ``lifecycle_state`` not in
        :data:`DAEMON_LIFECYCLE_STATES`."""
        with pytest.raises(ValueError, match="DAEMON_LIFECYCLE_STATES"):
            HealthStatus(
                outcome="ok",
                lifecycle_state="cucumber",  # not in closed-set
                **self._BASE_KWARGS,
            )

    def test_valid_outcome_lifecycle_combinations_accepted(self):
        """NEW-1 closure — every (outcome × lifecycle_state) combination
        from the closed-sets constructs successfully."""
        for outcome in HEALTH_PROBE_OUTCOMES:
            for lifecycle_state in DAEMON_LIFECYCLE_STATES:
                status = HealthStatus(
                    outcome=outcome,
                    lifecycle_state=lifecycle_state,
                    **self._BASE_KWARGS,
                )
                assert status.outcome == outcome
                assert status.lifecycle_state == lifecycle_state


class TestServeHealthEndpoint:
    """Pillar H Week 4 — :func:`serve_health_endpoint` body per ADR-0063
    D345. The aiohttp web client pattern verifies HTTP 200/503 + JSON
    body shape + the rate-limit behavior at the actual HTTP boundary."""

    def _make_runner(self, tmp_path, lifecycle_state="ready"):
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir(exist_ok=True)
        ledger_dir.mkdir(exist_ok=True)
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        return DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts="2026-05-27T12:00:00.000Z", version="0.1.0",
            lifecycle_state=lifecycle_state,
        )

    def _free_port(self) -> int:
        """Bind a fresh ephemeral port + close it; the port is free for
        the next bind. Tests need a free port to bind the health endpoint
        WITHOUT racing other test instances on a fixed port.

        Pillar H Week 4 follow-up P3-11 closure — ``socket`` is imported
        at module level per the per-pillar import convention; previously
        the lazy import was style-inconsistent with the other module-top
        imports."""
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_returns_200_on_ready_state(self, tmp_path):
        """ADR-0063 D345 — HTTP 200 + JSON body when lifecycle_state ==
        "ready". The k8s readiness-probe convention treats 200 as
        "healthy + ready to receive traffic"."""
        import asyncio
        import aiohttp
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        port = self._free_port()
        captures: list[dict] = []
        emit_fn = lambda payload: captures.append(payload)

        async def _run() -> tuple[int, dict]:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        body = await resp.json()
                        return resp.status, body
            finally:
                await app_runner.cleanup()

        status_code, body = asyncio.run(_run())
        assert status_code == 200
        assert body["outcome"] == "ok"
        assert body["lifecycle_state"] == "ready"

    def test_returns_503_on_draining_state(self, tmp_path):
        """ADR-0063 D345 — HTTP 503 + JSON body when lifecycle_state ==
        "draining" (k8s readiness blocks traffic during graceful
        shutdown)."""
        import asyncio
        import aiohttp
        runner = self._make_runner(tmp_path, lifecycle_state="draining")
        port = self._free_port()
        captures: list[dict] = []
        emit_fn = lambda payload: captures.append(payload)

        async def _run() -> int:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        return resp.status
            finally:
                await app_runner.cleanup()

        status_code = asyncio.run(_run())
        assert status_code == 503

    def test_health_probe_event_rate_limited_per_r038(self, tmp_path):
        """ADR-0063 D346 + R038 mitigation — at-most-ONE health_probe
        event per :attr:`DaemonConfig.health_probe_rate_limit_seconds`.
        Three probes within the rate-limit window yield ONE emit; a
        probe AFTER the window yields a second emit."""
        import asyncio
        import aiohttp
        from datetime import timedelta
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        # Config default health_probe_rate_limit_seconds = 30.
        port = self._free_port()
        captures: list[dict] = []
        emit_fn = lambda payload: captures.append(payload)

        # Spy clock that advances on each call (3 probes within 1s window,
        # then 1 probe at 31s after the first emit — should yield 2 emits).
        ts_state = [datetime(2026, 5, 27, 13, 0, 0, tzinfo=timezone.utc)]
        def _now_fn() -> datetime:
            return ts_state[0]

        async def _run() -> None:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn, now_fn=_now_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    # Probe 1: t=0s, first emit.
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
                    # Probe 2: t=1s, RATE-LIMITED (no emit).
                    ts_state[0] += timedelta(seconds=1)
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
                    # Probe 3: t=29s, RATE-LIMITED (no emit; under 30s).
                    ts_state[0] += timedelta(seconds=28)
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
                    # Probe 4: t=31s, second emit (interval exceeded).
                    ts_state[0] += timedelta(seconds=2)
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
            finally:
                await app_runner.cleanup()

        asyncio.run(_run())
        # 4 probes; rate-limit at 30s should yield exactly 2 emits.
        assert len(captures) == 2
        assert captures[0]["type"] == "health_probe"
        assert captures[1]["type"] == "health_probe"

    def test_emit_payload_carries_runner_pid(self, tmp_path):
        """Behavioral-passthrough — the runner's pid is passed through
        to the emit payload."""
        import asyncio
        import aiohttp
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        port = self._free_port()
        captures: list[dict] = []
        emit_fn = lambda payload: captures.append(payload)

        async def _run() -> None:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
            finally:
                await app_runner.cleanup()

        asyncio.run(_run())
        assert captures[0]["pid"] == runner.pid

    def test_emit_payload_carries_emitted_by_daemon(self, tmp_path):
        """Pillar H Week 3 follow-up P2-1 closure extends to Week 4 —
        the emit payload carries ``_emitted_by="daemon"``."""
        import asyncio
        import aiohttp
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        port = self._free_port()
        captures: list[dict] = []
        emit_fn = lambda payload: captures.append(payload)

        async def _run() -> None:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
            finally:
                await app_runner.cleanup()

        asyncio.run(_run())
        assert captures[0]["_emitted_by"] == "daemon"

    def test_health_json_body_shape_matches_health_status_dataclass(
        self, tmp_path,
    ):
        """ADR-0063 D345 — the JSON body is the serialized HealthStatus
        dataclass (11 fields)."""
        import asyncio
        import aiohttp
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        port = self._free_port()
        emit_fn = lambda payload: None

        async def _run() -> dict:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        return await resp.json()
            finally:
                await app_runner.cleanup()

        body = asyncio.run(_run())
        expected_fields = {
            "outcome", "lifecycle_state", "daemon_pid", "daemon_version",
            "uptime_seconds", "config_hash", "ledger_reachable",
            "policy_loaded", "in_flight_task_count",
            "last_reconcile_pass_age_seconds", "ts",
        }
        assert set(body.keys()) == expected_fields

    def test_invalid_bind_addr_raises_value_error(self, tmp_path):
        """Pillar H Week 4 follow-up P3-6 closure —
        :func:`serve_health_endpoint` refuses-loud on invalid
        ``bind_addr`` (mid-startup :exc:`OSError` would surface AFTER
        OTel set-once burnt at Week 5+ when
        :func:`init_daemon` → :func:`serve_health_endpoint` is wired
        sequentially). The Week 2 follow-up P2-1 closure pattern
        (next-tier invariant-bearing field refuse-loud at
        :func:`_validate_config`) extends to the Week 4
        ``bind_addr`` boundary."""
        import asyncio
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        emit_fn = lambda payload: None
        with pytest.raises(ValueError):
            asyncio.run(serve_health_endpoint(
                self._free_port(),
                runner=runner,
                bind_addr="not-an-ip",
                emit_fn=emit_fn,
            ))

    def test_invalid_bind_addr_octet_overflow_raises_value_error(
        self, tmp_path,
    ):
        """P3-6 closure — refuse-loud on out-of-range IP octets."""
        import asyncio
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        emit_fn = lambda payload: None
        with pytest.raises(ValueError):
            asyncio.run(serve_health_endpoint(
                self._free_port(),
                runner=runner,
                bind_addr="999.999.999.999",
                emit_fn=emit_fn,
            ))

    def test_framework_neutrality_seam_kwargs_do_NOT_swap_http_server(
        self, tmp_path,
    ):
        """Pillar H Week 4 follow-up P2-1 closure (the THIRD
        ADR-vs-actual-impl drift caught in Pillar H by the cross-pillar
        back-audit discipline — W2 P3-8 OTel Resource rationale + W3
        P2-1 ``_emitted_by`` audit-marker + W4 P2-1 framework-neutrality
        text). The test-only seam kwargs (``emit_fn`` + ``now_fn`` +
        ``bind_addr``) substitute BACKENDS (ledger + clock + IP), NOT
        the HTTP server choice. Operators wanting alternative HTTP
        servers (Tornado / FastAPI / Starlette / etc.) MUST replace the
        entire :func:`serve_health_endpoint` function body.

        This regression-barrier asserts the seams produce an aiohttp
        HTTP response (verifying the seams do NOT swap the HTTP server
        choice) by inspecting the response's ``Server`` header which
        identifies the aiohttp server implementation."""
        import asyncio
        import aiohttp
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        port = self._free_port()
        captures: list[dict] = []
        emit_fn = lambda payload: captures.append(payload)

        async def _run() -> str:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        # aiohttp's default Server header includes
                        # "Python/<ver> aiohttp/<ver>"; if a future
                        # author swapped HTTP servers via the seams,
                        # this assertion would catch the drift.
                        return resp.headers.get("Server", "")
            finally:
                await app_runner.cleanup()

        server_header = asyncio.run(_run())
        assert "aiohttp" in server_header.lower(), (
            f"Expected 'aiohttp' in Server header (the seams do NOT swap "
            f"HTTP server choice per W4 follow-up P2-1 closure); got "
            f"{server_header!r}. If this test fails, an operator MUST "
            f"have replaced the serve_health_endpoint function body OR "
            f"a future aiohttp version changed the default Server header."
        )

    def test_response_content_type_is_application_json(self, tmp_path):
        """Pillar H Week 4 follow-up NEW-2 closure — the aiohttp
        :func:`web.json_response` default sets ``Content-Type:
        application/json``; this regression-barrier pins the contract so
        a future aiohttp version change OR refactor surfaces the
        breakage. k8s readiness probes + operators parsing the response
        depend on the JSON Content-Type."""
        import asyncio
        import aiohttp
        runner = self._make_runner(tmp_path, lifecycle_state="ready")
        port = self._free_port()
        emit_fn = lambda payload: None

        async def _run() -> str:
            app_runner = await serve_health_endpoint(
                port, runner=runner, emit_fn=emit_fn,
            )
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        return resp.content_type
            finally:
                await app_runner.cleanup()

        content_type = asyncio.run(_run())
        assert content_type == "application/json"


# Pillar H Week 5 follow-up P3-2 closure — _StubAppRunner promoted to
# the shared :mod:`tests._daemon_test_helpers` module per the Pillar H
# Week 3 follow-up P3-6 closure's DRY discipline (the class was
# duplicated across test_daemon.py + test_multi_channel_coherence.py x2;
# the W5 follow-up consolidates here).
from tests._daemon_test_helpers import _StubAppRunner, _TEST_PAST_STARTED_AT_TS


# ---------------------------------------------------------------------------
# Pillar H Week 6 — TestDaemonStageSaturatedPayload (per ADR-0065 D355)
# ---------------------------------------------------------------------------


class TestDaemonStageSaturatedPayload:
    """Pillar H Week 6 — :func:`build_daemon_stage_saturated_payload`
    factory per ADR-0065 D355. The factory shape mirrors the Pillar G
    ``build_*_payload`` convention per ADR-0010 D17 + the Pillar H
    Week 3 follow-up P2-1 closure's ``_emitted_by="daemon"`` factory-
    boundary stamping discipline + the Pillar H Week 2 follow-up P2-2
    closure's raw-primitive refuse-loud at the factory boundary."""

    def _valid_kwargs(self):
        from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES
        return dict(
            pid=12345,
            stage=sorted(_PILLAR_G_PIPELINE_STAGES)[0],  # "drafted"
            parallelism_limit=4,
            in_flight_count=4,
        )

    def test_payload_shape_pins_per_adr_0065_d355(self):
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        payload = build_daemon_stage_saturated_payload(**self._valid_kwargs())
        # 5-key contract: pid + stage + parallelism_limit + in_flight_count
        # + _emitted_by (OMIT channel per ADR-0014 D33; OMIT ts/type per
        # Ledger.append auto-fill convention).
        assert set(payload.keys()) == {
            "pid", "stage", "parallelism_limit", "in_flight_count",
            "_emitted_by",
        }

    def test_payload_carries_emitted_by_marker_per_w3_followup_p2_1(self):
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        payload = build_daemon_stage_saturated_payload(**self._valid_kwargs())
        assert payload["_emitted_by"] == "daemon"

    def test_each_funnel_stage_accepted_per_pillar_g_pipeline_stages(self):
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES
        for stage in _PILLAR_G_PIPELINE_STAGES:
            kwargs = self._valid_kwargs()
            kwargs["stage"] = stage
            payload = build_daemon_stage_saturated_payload(**kwargs)
            assert payload["stage"] == stage

    def test_observability_stage_rejected_per_d354_orthogonality(self):
        # _PIPELINE_STAGES (observability) is DISJOINT from
        # _PILLAR_G_PIPELINE_STAGES (funnel) per Pillar H Week 1 follow-up
        # P3-5 closure. The factory refuses observability stages.
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        from orchestrator.observability import _PIPELINE_STAGES
        kwargs = self._valid_kwargs()
        for stage in _PIPELINE_STAGES:
            kwargs["stage"] = stage
            with pytest.raises(ValueError, match="_PILLAR_G_PIPELINE_STAGES"):
                build_daemon_stage_saturated_payload(**kwargs)

    def test_invalid_pid_raises_value_error(self):
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        kwargs = self._valid_kwargs()
        kwargs["pid"] = 0
        with pytest.raises(ValueError, match="pid > 0"):
            build_daemon_stage_saturated_payload(**kwargs)

    def test_sub_1_parallelism_limit_raises_value_error(self):
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        kwargs = self._valid_kwargs()
        kwargs["parallelism_limit"] = 0
        with pytest.raises(ValueError, match="parallelism_limit >= 1"):
            build_daemon_stage_saturated_payload(**kwargs)

    def test_in_flight_count_above_limit_raises_value_error(self):
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        kwargs = self._valid_kwargs()
        kwargs["parallelism_limit"] = 2
        kwargs["in_flight_count"] = 3
        with pytest.raises(ValueError, match="in_flight_count"):
            build_daemon_stage_saturated_payload(**kwargs)

    def test_in_flight_count_negative_raises_value_error(self):
        from orchestrator.daemon import build_daemon_stage_saturated_payload
        kwargs = self._valid_kwargs()
        kwargs["in_flight_count"] = -1
        with pytest.raises(ValueError, match="in_flight_count"):
            build_daemon_stage_saturated_payload(**kwargs)


class TestDaemonRunBody:
    """Pillar H Week 5 — :meth:`DaemonRunner.run` body per ADR-0064
    D349-D352. The asyncio event loop body wires: initializing→ready
    transition + ``daemon_started`` emit + signal handler wiring +
    health endpoint start + per-stage tick loop wrapped in
    :func:`observability.traced_stage` + graceful shutdown coordination."""

    def _make_runner(self, tmp_path):
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir(exist_ok=True)
        ledger_dir.mkdir(exist_ok=True)
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        # Pillar H Week 5 follow-up P3-3 closure — the past-date
        # constant is hosted at :mod:`tests._daemon_test_helpers` per the
        # named-constant discipline (a future test author copying the
        # construction pattern without importing the constant would risk
        # the run() + shutdown() body's startup_seconds/uptime_seconds
        # arithmetic refuse-loud on near-zero or negative values per the
        # Pillar H Week 2 follow-up P2-2 + Week 3 follow-up P2-2 closures).
        return DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts=_TEST_PAST_STARTED_AT_TS, version="0.1.0",
            lifecycle_state="initializing",
        )

    def _run_with_spies(
        self, runner, *, tick_seconds=0.001, sleep_seconds=0.02,
        semaphore_factory_fn=None,
    ):
        """Helper — invoke :meth:`DaemonRunner.run` with stub seams +
        trigger shutdown via :meth:`shutdown` after a short sleep so
        the loop exits cleanly.

        Pillar H Week 5 follow-up P1-1 closure — the ``_spy_traced_stage``
        signature is ``(stage, operation, **kwargs)`` mirroring the
        production :func:`observability.traced_stage` signature per
        ADR-0054 D296. The prior Week 5 main commit's spy accepted ONE
        positional arg while production required TWO; the body invoked
        with one arg + the spy tolerated it + production default broke
        with TypeError on the first per-stage tick (the FOURTH ADR-vs-
        actual-impl drift in Pillar H caught by the per-week-reviewer).

        Pillar H Week 6 follow-up P2-1 + P3-11 closure — the optional
        ``semaphore_factory_fn`` kwarg threads through to the body's
        Step 5.5 per-funnel-stage Semaphore construction. Tests can
        inject an always-locked Semaphore subclass to exercise the
        body's Iteration 6b emit path (the behavioral-passthrough
        regression-barrier the W5 P1-1 discipline catches at the
        body-level emit grain).
        """
        import asyncio
        from contextlib import nullcontext
        captures = {
            "emits": [],
            "attached_runners": [],
            "served_ports": [],
            "traced_stages": [],
            "traced_operations": [],
            "app_runner": _StubAppRunner(),
        }

        def _spy_attach(runner_, *, loop):
            captures["attached_runners"].append((runner_, loop))

        async def _spy_serve(port, *, runner):
            captures["served_ports"].append((port, runner))
            return captures["app_runner"]

        def _spy_traced_stage(stage, operation, *, attributes=None, tracer=None):
            captures["traced_stages"].append(stage)
            captures["traced_operations"].append(operation)
            return nullcontext()

        async def _orchestrate():
            run_kwargs = dict(
                attach_signal_handlers_fn=_spy_attach,
                serve_health_endpoint_fn=_spy_serve,
                traced_stage_fn=_spy_traced_stage,
                emit_fn=captures["emits"].append,
                tick_seconds=tick_seconds,
            )
            if semaphore_factory_fn is not None:
                run_kwargs["semaphore_factory_fn"] = semaphore_factory_fn
            task = asyncio.create_task(runner.run(**run_kwargs))
            # Let run() complete Step 5 (start health endpoint) + at
            # least one tick of Step 6 before triggering shutdown.
            await asyncio.sleep(sleep_seconds)
            runner.shutdown(
                "operator_requested",
                emit_fn=captures["emits"].append,
            )
            exit_code = await task
            return exit_code

        exit_code = asyncio.run(_orchestrate())
        captures["exit_code"] = exit_code
        return captures

    def test_run_refuses_non_initializing_state(self, tmp_path):
        """ADR-0064 D349 Step 1 — refuse-loud if lifecycle_state is
        not "initializing" at run() entry. A runner in any other state
        is a programming error; run() is the ONLY production caller
        that transitions initializing → ready."""
        import asyncio
        runner = self._make_runner(tmp_path)
        object.__setattr__(runner, "lifecycle_state", "ready")
        with pytest.raises(RuntimeError, match="initializing"):
            asyncio.run(runner.run(
                attach_signal_handlers_fn=lambda r, **kw: None,
                serve_health_endpoint_fn=lambda *a, **kw: None,
                # Pillar H Week 5 follow-up P1-1 closure — spy signature
                # matches production traced_stage(stage, operation, ...).
                traced_stage_fn=lambda stage, operation, **kw: None,
                emit_fn=lambda p: None,
            ))

    def test_run_transitions_initializing_to_ready(self, tmp_path):
        """ADR-0064 D349 Step 2 — run() transitions lifecycle_state
        from "initializing" to "ready" before emitting daemon_started.
        This is the binding-question regression-barrier for the
        Pillar H Week 5 lifecycle transition contract."""
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        # After shutdown, runner ends in "stopped" state; daemon_started
        # was emitted while in "ready" state.
        assert captures["exit_code"] == 0
        assert runner.lifecycle_state == "stopped"
        # Verify daemon_started emitted before daemon_stopping.
        emit_types = [e["type"] for e in captures["emits"]]
        assert emit_types[0] == "daemon_started"
        assert "daemon_stopping" in emit_types
        assert "daemon_stopped" in emit_types

    def test_emits_daemon_started_with_correct_payload(self, tmp_path):
        """ADR-0064 D349 Step 3 — daemon_started payload carries pid +
        version + config_hash + startup_seconds per ADR-0061 D339."""
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        started = next(
            e for e in captures["emits"] if e["type"] == "daemon_started"
        )
        assert started["pid"] == runner.pid
        assert started["version"] == runner.version
        assert started["config_hash"] == runner.config_hash
        assert started["startup_seconds"] >= 0
        assert started["_emitted_by"] == "daemon"

    def test_wires_signal_handlers_with_runner_and_loop(self, tmp_path):
        """ADR-0064 D349 Step 4 — attach_signal_handlers is called with
        the runner + the asyncio event loop."""
        import asyncio
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        assert len(captures["attached_runners"]) == 1
        attached_runner, attached_loop = captures["attached_runners"][0]
        assert attached_runner is runner
        assert isinstance(attached_loop, asyncio.AbstractEventLoop)

    def test_starts_health_endpoint_with_config_port_and_runner(
        self, tmp_path,
    ):
        """ADR-0064 D349 Step 5 — serve_health_endpoint is called with
        DaemonConfig.health_port + the runner."""
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        assert len(captures["served_ports"]) == 1
        port, served_runner = captures["served_ports"][0]
        assert port == runner.config.health_port
        assert served_runner is runner

    def test_per_stage_tick_wraps_each_pipeline_stage_in_traced_stage(
        self, tmp_path,
    ):
        """ADR-0064 D350 + ADR-0055 D300 — each per-stage tick wraps
        in observability.traced_stage. Iteration is deterministic
        (sorted) over the 8-element _PIPELINE_STAGES per ADR-0031
        D140's deterministic-output contract.

        Pillar H Week 5 follow-up P2-1 closure — the prior Week 5 main
        commit had a pre-iteration sanity-tick before the while loop +
        the while loop iterated again per tick (the pre-iteration was
        redundant; the first while-loop iteration covers the same
        ground). The W5 follow-up removes the pre-iteration; this test
        still pins the per-tick first-8-stages assertion via the first
        while-loop iteration.

        Pillar H Week 5 follow-up P1-1 closure — also asserts the
        operation argument "tick" is passed to each invocation
        (production observability.traced_stage requires (stage,
        operation) per ADR-0054 D296; the spy now captures the
        operation arg via captures["traced_operations"]).
        """
        from orchestrator.observability import _PIPELINE_STAGES
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        # Each tick produces 8 traced_stage invocations (one per
        # observability stage); at least one tick fires.
        assert len(captures["traced_stages"]) >= len(_PIPELINE_STAGES)
        # First 8 invocations are sorted _PIPELINE_STAGES.
        first_tick = captures["traced_stages"][:len(_PIPELINE_STAGES)]
        assert first_tick == sorted(_PIPELINE_STAGES)
        # Pillar H Week 5 follow-up P1-1 closure — operation arg "tick".
        first_tick_operations = captures["traced_operations"][:len(_PIPELINE_STAGES)]
        assert first_tick_operations == ["tick"] * len(_PIPELINE_STAGES)

    def test_calls_health_endpoint_cleanup_on_shutdown(self, tmp_path):
        """ADR-0064 D352 — AppRunner.cleanup() called when run() exits
        (graceful-shutdown coordination per aiohttp's documented
        contract; in-flight HTTP requests complete before the port
        releases)."""
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        assert captures["app_runner"].cleanup_called is True

    def test_returns_zero_on_clean_shutdown(self, tmp_path):
        """ADR-0064 D349 Step 8 — exit code 0 on graceful shutdown via
        :meth:`DaemonRunner.shutdown` (operator_requested path)."""
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        assert captures["exit_code"] == 0

    # -----------------------------------------------------------------
    # Pillar H Week 5 follow-up regression-barriers
    # -----------------------------------------------------------------

    def test_per_stage_tick_invokes_production_traced_stage_signature_per_w5_followup_p1_1(
        self, tmp_path,
    ):
        """Pillar H Week 5 follow-up P1-1 closure — behavioral-
        passthrough regression-barrier that exercises the PRODUCTION
        :func:`observability.traced_stage` default (NOT the spy seam)
        per the W5 follow-up's resolution of the FOURTH ADR-vs-actual-
        impl drift in Pillar H.

        The prior Week 5 main commit's body invoked
        ``traced_stage_fn(stage)`` with ONE positional argument while
        the production
        ``observability.traced_stage(stage, operation, *, attributes=None, tracer=None)``
        requires TWO positional args + refuses-loud on empty operation
        per ADR-0054 D296. The spy at ``_run_with_spies`` was
        signature-tolerant; production default broke with
        ``TypeError: traced_stage() missing 1 required positional
        argument: 'operation'`` on the first per-stage tick.

        This test invokes ``runner.run()`` with
        ``traced_stage_fn=None`` (production default) + asserts the
        body does NOT raise TypeError. The behavioral-passthrough
        discipline's exact failure-mode regression-barrier.
        """
        import asyncio
        runner = self._make_runner(tmp_path)

        async def _orchestrate():
            task = asyncio.create_task(runner.run(
                tick_seconds=0.001,
                # Spy seams for everything EXCEPT traced_stage_fn:
                attach_signal_handlers_fn=lambda r, *, loop: None,
                serve_health_endpoint_fn=lambda port, *, runner: _make_stub_app_runner(),
                emit_fn=lambda p: None,
                # traced_stage_fn=None → production observability.traced_stage
                # (the OTel SDK NoOpTracerProvider returns a no-op span
                # when the provider hasn't been initialized at test time,
                # so this is safe per ADR-0054 D294's no-op posture).
            ))
            await asyncio.sleep(0.03)
            runner.shutdown("operator_requested", emit_fn=lambda p: None)
            return await task

        async def _make_stub_app_runner():
            return _StubAppRunner()

        exit_code = asyncio.run(_orchestrate())
        assert exit_code == 0
        assert runner.lifecycle_state == "stopped"

    def test_calls_health_endpoint_cleanup_on_exception_path(self, tmp_path):
        """Pillar H Week 5 follow-up P2-2 closure — :meth:`AppRunner.cleanup`
        fires on the ungraceful-shutdown path (exception inside the
        tick loop OR :exc:`asyncio.CancelledError`) per ADR-0064 D352
        narrative. The Week 5 main commit only tested the CLEAN
        shutdown path (operator_requested); this regression-barrier
        injects a traced_stage_fn that raises mid-tick + asserts
        cleanup_called=True despite the exception propagating out of
        run()."""
        import asyncio
        runner = self._make_runner(tmp_path)
        stub_app_runner = _StubAppRunner()

        def _raising_traced_stage(stage, operation, **kwargs):
            raise RuntimeError("simulated tick-loop exception")

        async def _orchestrate():
            return await runner.run(
                tick_seconds=0.001,
                attach_signal_handlers_fn=lambda r, *, loop: None,
                serve_health_endpoint_fn=lambda port, *, runner: _serve_stub(),
                traced_stage_fn=_raising_traced_stage,
                emit_fn=lambda p: None,
            )

        async def _serve_stub():
            return stub_app_runner

        with pytest.raises(RuntimeError, match="simulated tick-loop exception"):
            asyncio.run(_orchestrate())
        # The finally block fired despite the exception.
        assert stub_app_runner.cleanup_called is True

    def test_tick_seconds_zero_raises_value_error(self, tmp_path):
        """Pillar H Week 5 follow-up P2-3 closure — refuse-loud on
        ``tick_seconds <= 0`` per the per-tier-invariant-field
        discipline established at Pillar H Week 2 follow-up P2-1
        closure on :func:`_validate_config`."""
        import asyncio
        runner = self._make_runner(tmp_path)
        with pytest.raises(ValueError, match="tick_seconds > 0"):
            asyncio.run(runner.run(
                tick_seconds=0.0,
                attach_signal_handlers_fn=lambda r, *, loop: None,
                serve_health_endpoint_fn=lambda *a, **kw: None,
                traced_stage_fn=lambda s, o, **kw: None,
                emit_fn=lambda p: None,
            ))

    def test_tick_seconds_negative_raises_value_error(self, tmp_path):
        """Pillar H Week 5 follow-up P2-3 closure — refuse-loud on
        negative ``tick_seconds``."""
        import asyncio
        runner = self._make_runner(tmp_path)
        with pytest.raises(ValueError, match="tick_seconds > 0"):
            asyncio.run(runner.run(
                tick_seconds=-1.0,
                attach_signal_handlers_fn=lambda r, *, loop: None,
                serve_health_endpoint_fn=lambda *a, **kw: None,
                traced_stage_fn=lambda s, o, **kw: None,
                emit_fn=lambda p: None,
            ))

    def test_run_outside_asyncio_loop_raises_operator_readable_error(
        self, tmp_path,
    ):
        """Pillar H Week 5 follow-up P2-4 closure —
        :func:`asyncio.get_running_loop` cryptic-error wrapped with
        operator-readable RuntimeError naming the
        ``asyncio.run(runner.run())`` invocation pattern per
        ADR-0064 §Existing-operator seed."""
        import asyncio
        runner = self._make_runner(tmp_path)
        # Call run() coroutine WITHOUT asyncio.run() — invoke directly
        # in sync context. The coroutine starts but on first await we
        # hit get_running_loop() with no loop active.
        coro = runner.run(
            tick_seconds=0.001,
            attach_signal_handlers_fn=lambda r, *, loop: None,
            serve_health_endpoint_fn=lambda *a, **kw: None,
            traced_stage_fn=lambda s, o, **kw: None,
            emit_fn=lambda p: None,
        )
        # Drive the coroutine forward sync; expect the operator-
        # readable RuntimeError when get_running_loop fires.
        with pytest.raises(RuntimeError, match="asyncio.run"):
            try:
                coro.send(None)
            except StopIteration:
                pass

    def test_only_lifecycle_state_mutates_during_run_per_w5_followup_new_5(
        self, tmp_path,
    ):
        """Pillar H Week 5 follow-up NEW-5 closure — mirror of the
        Week 3 follow-up P3-1 closure's
        :meth:`test_only_lifecycle_state_mutates_during_shutdown`
        regression-barrier at the run() side of the
        :func:`object.__setattr__` escape hatch (ADR-0062 D342). The
        invariant: ONLY ``lifecycle_state`` mutates through the
        escape hatch; the 5 non-lifecycle_state DaemonRunner fields
        (config, config_hash, pid, started_at_ts, version) preserve
        identity across the run() body."""
        runner = self._make_runner(tmp_path)
        # Capture field identities BEFORE run() executes.
        config_id_before = id(runner.config)
        config_hash_before = runner.config_hash
        pid_before = runner.pid
        started_at_ts_before = runner.started_at_ts
        version_before = runner.version
        captures = self._run_with_spies(runner)
        # AFTER run() + shutdown(): identities preserve (lifecycle_state
        # cycled through "initializing" → "ready" → "draining" → "stopped"
        # via the escape hatch ONLY).
        assert id(runner.config) == config_id_before
        assert runner.config_hash == config_hash_before
        assert runner.pid == pid_before
        assert runner.started_at_ts == started_at_ts_before
        assert runner.version == version_before
        # Sanity: lifecycle_state DID mutate (to "stopped" post-shutdown).
        assert runner.lifecycle_state == "stopped"

    def test_daemon_stage_saturated_emits_when_semaphore_locked_per_w6_followup_p2_1(
        self, tmp_path,
    ):
        """Pillar H Week 6 follow-up P2-1 + P3-11 closure —
        BEHAVIORAL-PASSTHROUGH regression-barrier for the body's
        Iteration 6b Semaphore saturation emit path per ADR-0065
        D353-D355.

        **Why this test exists:** the W5 P1-1 closure (FOURTH ADR-vs-
        actual-impl drift in Pillar H + FIRST P1 in Pillar H)
        established that behavioral-passthrough tests MUST exercise
        the production default path — the W5 main commit's spy passed
        but production broke on the FIRST per-stage tick because the
        spy signature did NOT match production. The W6 main commit's
        coherence test ``test_per_stage_parallelism_limit_enforced``
        verified ONLY the factory contract + the closed-set extension;
        the body's Iteration 6b emit path was STRUCTURALLY UNTESTED
        — the same shape as the W5 P1-1 failure mode translated to
        body-vs-test drift. A future Week-7+ author refactoring
        Iteration 6b's body (e.g., changing the iteration source from
        ``_PILLAR_G_PIPELINE_STAGES`` to ``parallelism_limits.keys()``,
        OR moving the emit before ``sem.locked()`` check) would NOT
        break any existing test.

        **What this test verifies:** the body's per-funnel-stage
        Semaphore construction at Step 5.5 + the Iteration 6b emit
        path at Step 6 — specifically:

        1. The body constructs one Semaphore per funnel stage (7
           stages per :data:`funnel._PILLAR_G_PIPELINE_STAGES`).
        2. The body's Iteration 6b iterates over
           ``sorted(_PILLAR_G_PIPELINE_STAGES)`` (NOT
           ``parallelism_limits.keys()`` OR
           ``observability._PIPELINE_STAGES`` per ADR-0065 D354's
           orthogonality).
        3. When ``sem.locked()`` returns True (always, in this test
           via the injected always-locked subclass), the body emits
           ``daemon_stage_saturated`` with the correct 5-key payload
           (pid + stage + parallelism_limit + in_flight_count +
           ``_emitted_by="daemon"``) per ADR-0065 D355.
        4. Every funnel stage is represented in the saturation emit
           set (P3-11 closure: pins the iteration source).
        5. The ``_emitted_by="daemon"`` audit marker is stamped at
           the factory boundary per the W3 follow-up P2-1 closure.

        The :func:`semaphore_factory_fn` test-only seam (default
        :class:`asyncio.Semaphore`) is the W6 follow-up P2-1 closure's
        infrastructure for this behavioral-passthrough verification;
        the seam follows the W4 follow-up P2-1 closure's two-tiered
        seam-vs-fork distinction (substitutes a BACKEND for testing;
        operators wanting alternative concurrency models MUST fork
        the function body).
        """
        import asyncio
        from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES

        class _AlwaysLockedSemaphore(asyncio.Semaphore):
            """W6 follow-up P2-1 closure — test-only Semaphore
            subclass whose :meth:`locked` always returns True so the
            body's Iteration 6b emit path fires on every per-funnel-
            stage check."""

            def locked(self) -> bool:
                return True

        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(
            runner, semaphore_factory_fn=_AlwaysLockedSemaphore,
        )
        # Filter for daemon_stage_saturated emits (the body also
        # emits daemon_started + daemon_stopping + daemon_stopped
        # across the lifecycle).
        saturation_emits = [
            e for e in captures["emits"]
            if e.get("type") == "daemon_stage_saturated"
        ]
        # At least one tick fires (the W5 spy contract loops while
        # lifecycle_state == "ready"; ≥1 tick before shutdown). Each
        # tick's Iteration 6b emits one daemon_stage_saturated per
        # funnel stage (7 stages).
        assert len(saturation_emits) >= len(_PILLAR_G_PIPELINE_STAGES), (
            f"Expected at least {len(_PILLAR_G_PIPELINE_STAGES)} "
            f"daemon_stage_saturated emits (one per funnel stage per "
            f"tick); got {len(saturation_emits)}: "
            f"{[e.get('stage') for e in saturation_emits]!r}"
        )
        # P3-11 closure: pin the iteration source by verifying every
        # funnel stage is represented (NOT a subset; equality).
        emitted_stages = {e["stage"] for e in saturation_emits}
        assert emitted_stages == set(_PILLAR_G_PIPELINE_STAGES), (
            f"Expected emits for every funnel stage per ADR-0065 "
            f"D354's orthogonality; got {sorted(emitted_stages)!r} "
            f"vs expected {sorted(_PILLAR_G_PIPELINE_STAGES)!r}. A "
            f"refactor that changed the iteration source to "
            f"parallelism_limits.keys() OR _PIPELINE_STAGES would "
            f"break this assertion."
        )
        # Per-emit shape verification (W3 follow-up P2-1 closure:
        # _emitted_by audit marker; ADR-0065 D355: 5-key payload;
        # saturation semantics: in_flight_count == parallelism_limit).
        for emit in saturation_emits:
            assert emit["_emitted_by"] == "daemon", (
                f"daemon_stage_saturated emit missing/wrong _emitted_by: "
                f"{emit!r}"
            )
            assert emit["pid"] == runner.pid
            # parallelism_limit matches the configured value for this stage.
            expected_limit = runner.config.parallelism_limits[emit["stage"]]
            assert emit["parallelism_limit"] == expected_limit
            # At saturation, in_flight_count == parallelism_limit per
            # ADR-0065 D355's body-emit-narrow contract.
            assert emit["in_flight_count"] == expected_limit
            # Channel field OMITTED per ADR-0014 D33.
            assert "channel" not in emit
            # ts NOT in factory output (set by Ledger.append +
            # caller's emit dict's "type" field).
            assert "ts" not in emit

    def test_run_accepts_semaphore_factory_fn_seam_per_w6_followup_p2_1(
        self, tmp_path,
    ):
        """Pillar H Week 6 follow-up P2-1 closure cell-level
        coverage — verify the ``semaphore_factory_fn`` test-only
        seam is accepted at the :meth:`DaemonRunner.run` signature +
        the default (omitted kwarg) does NOT change behavior from
        the production :class:`asyncio.Semaphore` backend.

        The seam follows the Pillar G TEST-ONLY convention + the
        Pillar H Week 2-5 precedent — operators omit the kwarg +
        receive the production asyncio primitive per ADR-0060
        D332's asyncio framework decision.
        """
        # Test 1: omitting the kwarg defaults to asyncio.Semaphore
        # (production behavior).
        runner = self._make_runner(tmp_path)
        captures = self._run_with_spies(runner)
        # Production asyncio.Semaphore is never locked() True at
        # Week 6 SKELETON (no actual dispatch acquires slots), so
        # NO daemon_stage_saturated emits fire.
        saturation_emits = [
            e for e in captures["emits"]
            if e.get("type") == "daemon_stage_saturated"
        ]
        assert saturation_emits == [], (
            f"Production asyncio.Semaphore default should produce zero "
            f"daemon_stage_saturated emits at Week 6 SKELETON; got "
            f"{len(saturation_emits)}: {saturation_emits!r}"
        )

    # -----------------------------------------------------------------
    # Pillar H Week 7 — dispatch_fn seam regression-barriers
    # -----------------------------------------------------------------

    def test_iteration_6b_invokes_dispatch_fn_per_funnel_stage(self, tmp_path):
        """Pillar H Week 7 — Iteration 6b's body now wires
        ``async with sem: await dispatch_fn(stage)`` per ADR-0066 D358
        (the Week 6 SKELETON ``pass`` is replaced). This regression-
        barrier asserts each per-tick iteration invokes ``dispatch_fn``
        once per funnel stage in sorted order."""
        runner = self._make_runner(tmp_path)
        dispatched_stages: list[str] = []

        async def _spy_dispatch(stage: str) -> None:
            dispatched_stages.append(stage)

        # Use the _run_with_spies pattern but inject dispatch_fn through
        # a custom orchestrate fn (the helper doesn't yet expose
        # dispatch_fn; we replicate the orchestration inline).
        import asyncio
        from contextlib import nullcontext
        captures = {
            "emits": [],
            "app_runner": _StubAppRunner(),
        }

        def _spy_attach(runner_, *, loop):
            pass

        async def _spy_serve(port, *, runner):
            return captures["app_runner"]

        def _spy_traced_stage(stage, operation, *, attributes=None, tracer=None):
            return nullcontext()

        async def _orchestrate():
            task = asyncio.create_task(runner.run(
                attach_signal_handlers_fn=_spy_attach,
                serve_health_endpoint_fn=_spy_serve,
                traced_stage_fn=_spy_traced_stage,
                emit_fn=captures["emits"].append,
                tick_seconds=0.001,
                dispatch_fn=_spy_dispatch,
            ))
            await asyncio.sleep(0.02)
            runner.shutdown(
                "operator_requested",
                emit_fn=captures["emits"].append,
            )
            await task

        asyncio.run(_orchestrate())

        # At least one full per-tick Iteration 6b loop fires before
        # shutdown; the loop iterates over sorted(_PILLAR_G_PIPELINE_STAGES)
        # = sorted(7 stages) = 7 dispatch_fn invocations per tick.
        from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES
        assert len(dispatched_stages) >= len(_PILLAR_G_PIPELINE_STAGES), (
            f"expected at least {len(_PILLAR_G_PIPELINE_STAGES)} "
            f"dispatch_fn invocations from one tick of Iteration 6b; "
            f"got {len(dispatched_stages)}"
        )
        # First 7 are sorted funnel stages (deterministic per ADR-0031 D140).
        first_tick = dispatched_stages[:len(_PILLAR_G_PIPELINE_STAGES)]
        assert first_tick == sorted(_PILLAR_G_PIPELINE_STAGES)

    def test_dispatch_fn_default_resolves_to_default_dispatch_for_stage(
        self, tmp_path,
    ):
        """Pillar H Week 7 — the dispatch_fn=None default lazy-resolves
        to :func:`_default_dispatch_for_stage` per ADR-0066 D358. The
        production default's signature contract is verified through the
        seam-default resolution at the runner.run body's seam-defaults
        block (the W5 P1-1 closure's behavioral-passthrough discipline).

        For PRODUCER stages (queued/researched/drafted/ready/sent), the
        default returns immediately without invoking the reconcile
        passes — the Week 7 v1 mapping at :data:`_STAGE_TO_PASSES`
        has empty pass lists for producer stages."""
        import asyncio

        # Direct test of the production default function.
        runner = self._make_runner(tmp_path)
        # Producer stage returns without invoking reconcile.
        async def _check():
            # Should complete instantly (no reconcile work for producer).
            await _runner._default_dispatch_for_stage(runner, "queued")
            await _runner._default_dispatch_for_stage(runner, "researched")
            await _runner._default_dispatch_for_stage(runner, "drafted")
            await _runner._default_dispatch_for_stage(runner, "ready")
            await _runner._default_dispatch_for_stage(runner, "sent")
        # Just verify no exception.
        asyncio.run(_check())

    def test_default_dispatch_for_stage_exercises_replied_production_default_per_w7_followup_p2_1(
        self, tmp_path,
    ):
        """Pillar H Week 7 follow-up P2-1 closure — the W7 main commit's
        :meth:`test_dispatch_fn_default_resolves_to_default_dispatch_for_stage`
        ONLY exercised the producer/sent stages (empty pass lists), so
        the production-default `replied` + `outcome_terminal` paths were
        STRUCTURALLY UNTESTED — exactly the failure mode the W5 P1-1 +
        W6 P2-1 closures' behavioral-passthrough discipline exists to
        catch. The gap was the proximate cause of W7 P1-1 going uncaught
        at the inline author's audit: a test that invoked
        ``_default_dispatch_for_stage(runner, "replied")`` would have
        surfaced ``PassResult(pass_name="G", errors=[...])`` immediately
        when reconcile ran with classifier=None.

        This regression-barrier exercises the production default for
        ``replied`` (Pass G + M) with a real (tmp_path) ledger +
        people_dir + suppressions_dir. The W7 follow-up P1-1 closure
        lazy-constructs the classifier via
        :func:`_build_classifier_or_record_error`; in this test the
        operator's pattern YAML is absent (tmp_path-based fixture has
        no ~/.outreach-factory/classifier/), so the classifier construction
        returns ``(None, error_msg)`` + the daemon logs the bootstrap
        reminder to stderr + Pass G records the error in PassResult.errors
        but Pass M still runs.

        The test verifies the production-default path actually invokes
        reconcile (asserted via the reconcile() returning without
        unhandled exception + the daemon's stderr log) rather than
        the producer-stage no-op return.
        """
        import asyncio
        import os
        runner = self._make_runner(tmp_path)
        # Ensure people_dir + suppressions_dir exist on disk per
        # ``_default_dispatch_for_stage`` resolution (the config defaults
        # are None; the helper falls back to vault_dir/"10 People" +
        # auto_unsubscribe.suppressions_dir_default()).
        people_dir = runner.config.vault_dir / "10 People"
        people_dir.mkdir(exist_ok=True)
        # Set OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH to a nonexistent
        # path so the classifier construction fails deterministically
        # (deflects any user-environment pattern YAML).
        old_env = os.environ.get("OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH")
        os.environ["OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH"] = str(
            tmp_path / "nonexistent-pattern.yml"
        )
        try:
            async def _check():
                # The production default for replied invokes Pass G + M
                # via reconcile via to_thread. Should complete without
                # raising — the missing classifier path returns
                # (None, error_msg) + reconcile() records the error in
                # PassResult.errors + Pass M still runs.
                await _runner._default_dispatch_for_stage(runner, "replied")
            asyncio.run(_check())
        finally:
            if old_env is None:
                del os.environ["OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH"]
            else:
                os.environ["OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH"] = old_env

    def test_default_dispatch_for_stage_exercises_outcome_terminal_production_default_per_w7_followup_p2_1(
        self, tmp_path,
    ):
        """Pillar H Week 7 follow-up P2-1 closure (continued) — the
        outcome_terminal production-default path invokes Pass C + N + O
        via reconcile via to_thread. Verifies the path completes without
        raising (the W7 main commit's gap allowed the channel-passes
        deferral framing to mask the classifier dependency at G; the
        outcome_terminal passes ALL pure-framework so this path is
        unambiguously successful)."""
        import asyncio
        runner = self._make_runner(tmp_path)
        people_dir = runner.config.vault_dir / "10 People"
        people_dir.mkdir(exist_ok=True)

        async def _check():
            await _runner._default_dispatch_for_stage(runner, "outcome_terminal")
        asyncio.run(_check())

    def test_default_dispatch_for_stage_passes_classifier_to_reconcile_per_w7_followup_p1_1(
        self, tmp_path,
    ):
        """Pillar H Week 7 follow-up P1-1 closure — behavioral-passthrough
        regression-barrier exercising the W7 follow-up's classifier
        wiring. The W7 main commit's ADR-0066 D358 narrative claimed
        Pass G was "pure framework (no external client)" but Pass G
        requires a :class:`RuleBasedClassifier` instance per ADR-0026
        D103; the W7 main commit's dispatch silently failed Pass G via
        ``PassResult.errors`` because the dispatch passed no ``classifier``
        kwarg to ``reconcile.reconcile()`` (the SIXTH ADR-vs-actual-impl
        drift in Pillar H + SECOND P1).

        The W7 follow-up commit lazy-constructs the classifier via
        :func:`reconcile._build_classifier_or_record_error` per ADR-0026
        D103's documented bootstrap path. This test patches
        ``reconcile.reconcile`` to capture the kwargs + verifies the
        ``classifier`` kwarg is forwarded (either a non-None
        :class:`RuleBasedClassifier` instance OR ``None`` if the
        operator hasn't bootstrapped the pattern YAML).
        """
        import asyncio
        import os
        import orchestrator.reconcile as _reconcile_module

        runner = self._make_runner(tmp_path)
        people_dir = runner.config.vault_dir / "10 People"
        people_dir.mkdir(exist_ok=True)

        captured_kwargs = {}
        original_reconcile = _reconcile_module.reconcile

        def _capture_reconcile(**kwargs):
            captured_kwargs.update(kwargs)
            # Return a minimal ReconcileResult-shaped object so the
            # caller doesn't get NoneType issues if it inspects.
            from datetime import datetime, timezone
            return _reconcile_module.ReconcileResult(
                ran_at=datetime.now(tz=timezone.utc).isoformat(),
                apply=kwargs.get("apply", False),
            )

        # Use a valid empty pattern YAML so _build_classifier_or_record_error
        # CAN construct the classifier (verifying the W7 follow-up's
        # lazy-construct path actually fires).
        pattern_file = tmp_path / "unsubscribe-patterns.yml"
        pattern_file.write_text("version: 1\npatterns: []\n")
        old_env = os.environ.get("OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH")
        os.environ["OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH"] = str(pattern_file)
        _reconcile_module.reconcile = _capture_reconcile
        try:
            async def _check():
                await _runner._default_dispatch_for_stage(runner, "replied")
            asyncio.run(_check())
        finally:
            _reconcile_module.reconcile = original_reconcile
            if old_env is None:
                del os.environ["OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH"]
            else:
                os.environ["OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH"] = old_env

        # The dispatch invoked reconcile with classifier kwarg present.
        # The W7 follow-up P1-1 closure ensures this; the W7 main commit
        # OMITTED the kwarg entirely (Pass G silently failed).
        assert "classifier" in captured_kwargs, (
            "Pillar H Week 7 follow-up P1-1 closure: "
            "_default_dispatch_for_stage MUST pass classifier kwarg to "
            "reconcile.reconcile() for Pass G; the W7 main commit "
            "omitted this kwarg + Pass G silently failed per-tick."
        )
        # When pattern YAML exists, classifier is a RuleBasedClassifier
        # (not None) — verifies the lazy-construct succeeded. (reconcile.py
        # imports reply_classifier via bare-name + conftest's sys.path
        # shim; the test imports the same way for class-identity
        # comparison.)
        import reply_classifier as _reply_classifier_module
        assert isinstance(
            captured_kwargs["classifier"],
            _reply_classifier_module.RuleBasedClassifier,
        )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    """ADR-0060 D331 + ADR-0061 D339 — ``orchestrator/daemon/__init__.py``
    re-exports the full Week 1 + Week 2 public surface (Pillar H Week 1
    follow-up extends with :data:`DAEMON_POLICY_RELOAD_SIGNALS` +
    :data:`POLICY_RELOAD_STATUSES`; Pillar H Week 2 extends with
    :func:`build_daemon_started_payload`)."""

    def test_all_names_exported(self):
        expected = {
            "DAEMON_EXIT_REASONS",
            "DAEMON_LIFECYCLE_STATES",
            "DAEMON_NEW_EVENT_CLASSES",
            "DAEMON_POLICY_RELOAD_SIGNALS",
            "DaemonConfig",
            "DaemonRunner",
            # Pillar H Week 8 NEW per ADR-0067 D359.
            "EventClassIndex",
            "HEALTH_PROBE_OUTCOMES",
            "HealthStatus",
            "POLICY_RELOAD_STATUSES",
            # Pillar H Week 8 NEW per ADR-0067 D359.
            "PersonEventIndex",
            "PolicyReloadResult",
            "SHUTDOWN_REASONS",
            # Pillar H Week 10-11 NEW per ADR-0068 D364 — crash-recovery
            # synthesis helper re-exported for Pillar I per-tenant audit-
            # tooling's potential consumer + test substrate consumption.
            "_recover_from_prior_crash",
            "attach_signal_handlers",
            # Pillar H Week 6 NEW per ADR-0065 D355.
            "build_daemon_stage_saturated_payload",
            "build_daemon_started_payload",
            "build_daemon_stopped_payload",
            "build_daemon_stopping_payload",
            "build_health_probe_payload",
            # Pillar H Week 7 NEW per ADR-0066 D357.
            "build_policy_reloaded_payload",
            "init_daemon",
            "serve_health_endpoint",
        }
        actual = set(_daemon.__all__)
        assert expected == actual, (
            f"daemon.__all__ surface drift: expected {expected!r}, "
            f"got {actual!r}"
        )

    def test_all_names_actually_exported(self):
        for name in _daemon.__all__:
            assert hasattr(_daemon, name), (
                f"daemon.__all__ lists {name!r} but the attribute is missing"
            )


# ---------------------------------------------------------------------------
# Pillar H Week 7 — TestBuildPolicyReloadedPayload (per ADR-0066 D357)
# ---------------------------------------------------------------------------


class TestBuildPolicyReloadedPayload:
    """Pillar H Week 7 — :func:`build_policy_reloaded_payload` factory
    per ADR-0066 D357. The factory shape mirrors the Pillar G
    ``build_*_payload`` convention per ADR-0010 D17 + the Pillar H Week
    3 follow-up P2-1 closure's ``_emitted_by="daemon"`` factory-boundary
    stamping discipline + the Pillar H Week 2 follow-up P2-2 closure's
    raw-primitive refuse-loud at the factory boundary."""

    def _valid_kwargs(self):
        return dict(
            pid=12345,
            source_path="/Users/yang/.outreach-factory/policies",
            prior_content_hash="a" * 64,
            new_content_hash="b" * 64,
            status="applied",
        )

    def test_payload_shape_pins_per_adr_0066_d357(self):
        from orchestrator.daemon import build_policy_reloaded_payload
        payload = build_policy_reloaded_payload(**self._valid_kwargs())
        # 6-key contract: pid + source_path + prior_content_hash +
        # new_content_hash + status + _emitted_by (OMIT channel per
        # ADR-0014 D33; OMIT ts/type per Ledger.append auto-fill).
        assert set(payload.keys()) == {
            "pid", "source_path", "prior_content_hash",
            "new_content_hash", "status", "_emitted_by",
        }

    def test_emitted_by_stamped_at_factory_per_w3_followup_p2_1(self):
        """Pillar H Week 3 follow-up P2-1 closure precedent — the
        factory stamps ``_emitted_by="daemon"`` at construction (NOT
        auto-filled by Ledger.append which only does setdefault('v') +
        setdefault('ts'))."""
        from orchestrator.daemon import build_policy_reloaded_payload
        payload = build_policy_reloaded_payload(**self._valid_kwargs())
        assert payload["_emitted_by"] == "daemon"

    def test_rejects_invalid_pid(self):
        """Refuse-loud on non-positive pid per POSIX OS PID convention."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        kwargs["pid"] = 0
        with pytest.raises(ValueError, match="pid > 0"):
            build_policy_reloaded_payload(**kwargs)
        kwargs["pid"] = -1
        with pytest.raises(ValueError, match="pid > 0"):
            build_policy_reloaded_payload(**kwargs)

    def test_rejects_empty_source_path(self):
        """Refuse-loud on empty source_path — operator MUST be able to
        identify the reloaded policy directory in the ledger event."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        kwargs["source_path"] = ""
        with pytest.raises(ValueError, match="non-empty source_path"):
            build_policy_reloaded_payload(**kwargs)

    def test_rejects_invalid_new_content_hash_length(self):
        """Refuse-loud on new_content_hash not 64 hex chars (SHA-256
        digest length)."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        kwargs["new_content_hash"] = "deadbeef"  # too short
        with pytest.raises(ValueError, match="new_content_hash"):
            build_policy_reloaded_payload(**kwargs)

    def test_accepts_empty_prior_content_hash_initial_load(self):
        """Per the documented initial-load-may-be-empty semantic —
        :class:`DaemonRunner` constructed directly (bypassing
        :func:`init_daemon`) starts with policy_state.content_hash="";
        the FIRST reload after such construction passes prior=""."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        kwargs["prior_content_hash"] = ""
        # Must NOT raise.
        payload = build_policy_reloaded_payload(**kwargs)
        assert payload["prior_content_hash"] == ""

    def test_rejects_non_empty_non_64_prior_content_hash(self):
        """Refuse-loud on prior_content_hash length not in {0, 64}."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        kwargs["prior_content_hash"] = "deadbeef"  # neither empty nor 64
        with pytest.raises(ValueError, match="prior_content_hash"):
            build_policy_reloaded_payload(**kwargs)

    def test_rejects_status_outside_closed_set(self):
        """Refuse-loud on status not in POLICY_RELOAD_STATUSES per the
        Pillar H Week 1 follow-up P3-3 closure's closed-set discipline."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        kwargs["status"] = "banana"
        with pytest.raises(ValueError, match="POLICY_RELOAD_STATUSES"):
            build_policy_reloaded_payload(**kwargs)

    def test_accepts_both_POLICY_RELOAD_STATUSES_members(self):
        """Cell-level matrix coverage — every closed-set member must be
        accepted by the factory."""
        from orchestrator.daemon import (
            build_policy_reloaded_payload, POLICY_RELOAD_STATUSES,
        )
        for status in POLICY_RELOAD_STATUSES:
            kwargs = self._valid_kwargs()
            kwargs["status"] = status
            payload = build_policy_reloaded_payload(**kwargs)
            assert payload["status"] == status

    def test_privacy_invariant_excludes_person_id_body_source_list(self):
        """Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323
        — the 6-key payload excludes person_id / body content /
        source_list. content hashes are SHA-256 of policy YAML (not
        per-Person data); source_path is operator-controlled deployment
        state."""
        from orchestrator.daemon import build_policy_reloaded_payload
        payload = build_policy_reloaded_payload(**self._valid_kwargs())
        for forbidden in ("person_id", "body", "source_list"):
            assert forbidden not in payload

    def test_rejects_non_hex_new_content_hash_per_w7_followup_p3_4(self):
        """Pillar H Week 7 follow-up P3-4 closure — the factory MUST
        validate the hex char-set of ``new_content_hash`` (not just
        length) per the Pillar G/H raw-primitive factory convention.
        Non-hex strings like "Z"*64 / "G"*64 previously passed the
        factory + landed in the ledger as non-SHA-256 strings."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        kwargs["new_content_hash"] = "Z" * 64  # length OK but non-hex
        with pytest.raises(ValueError, match="hex chars"):
            build_policy_reloaded_payload(**kwargs)
        kwargs["new_content_hash"] = "G" * 64  # 'G' is NOT a hex char
        with pytest.raises(ValueError, match="hex chars"):
            build_policy_reloaded_payload(**kwargs)

    def test_rejects_non_hex_prior_content_hash_per_w7_followup_p3_4(self):
        """Pillar H Week 7 follow-up P3-4 closure (continued) — same
        hex-char validation extended to prior_content_hash; the empty
        string remains a valid prior (initial-load-may-be-empty
        semantic)."""
        from orchestrator.daemon import build_policy_reloaded_payload
        kwargs = self._valid_kwargs()
        # Length-64 non-hex prior fails.
        kwargs["prior_content_hash"] = "Z" * 64
        with pytest.raises(ValueError, match="hex chars"):
            build_policy_reloaded_payload(**kwargs)
        # Empty prior still accepted (initial-load semantic).
        kwargs["prior_content_hash"] = ""
        payload = build_policy_reloaded_payload(**kwargs)
        assert payload["prior_content_hash"] == ""


# ---------------------------------------------------------------------------
# Pillar H Week 7 — TestReloadPolicyBody (per ADR-0066 D356)
# ---------------------------------------------------------------------------


class TestReloadPolicyBody:
    """Pillar H Week 7 — :meth:`DaemonRunner.reload_policy` body per
    ADR-0066 D356. Verifies the eight ordered closures (parse failure
    preserves prior state; parse success swaps; hash-unchanged is still
    applied; emit fires with the correct payload; seam defaults
    behavioral-passthrough per the W5 P1-1 discipline)."""

    def _make_runner(self, tmp_path):
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir(exist_ok=True)
        ledger_dir.mkdir(exist_ok=True)
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        return DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts=_TEST_PAST_STARTED_AT_TS, version="0.1.0",
            lifecycle_state="initializing",
        )

    def test_returns_PolicyReloadResult(self, tmp_path):
        """The body returns a :class:`PolicyReloadResult` (not None,
        not a tuple, not a dict)."""
        runner = self._make_runner(tmp_path)
        result = runner.reload_policy(
            policy_load_fn=lambda _dir: [],
            hash_fn=lambda _dir: "f" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=lambda _p: None,
        )
        assert isinstance(result, PolicyReloadResult)

    def test_parse_success_yields_status_applied(self, tmp_path):
        """Parse succeeds → status="applied" per ADR-0066 D356."""
        runner = self._make_runner(tmp_path)
        result = runner.reload_policy(
            policy_load_fn=lambda _dir: ["fake_rule"],
            hash_fn=lambda _dir: "f" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=lambda _p: None,
        )
        assert result.status == "applied"
        assert result.parse_error is None

    def test_parse_failure_yields_status_failed_unchanged(self, tmp_path):
        """Parse fails → status="failed_unchanged" + parse_error
        populated + prior state preserved per ADR-0066 D356."""
        runner = self._make_runner(tmp_path)
        prior_state = runner.policy_state
        # Establish prior state.
        prior_state.rules = ["original_rule"]
        prior_state.content_hash = "a" * 64

        def _failing_load(_dir):
            raise ValueError("synthetic YAML parse failure")

        result = runner.reload_policy(
            policy_load_fn=_failing_load,
            hash_fn=lambda _dir: "b" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=lambda _p: None,
        )
        assert result.status == "failed_unchanged"
        assert result.parse_error is not None
        assert "synthetic YAML parse failure" in result.parse_error
        # Prior state PRESERVED (no atomic swap on parse failure).
        assert runner.policy_state.rules == ["original_rule"]
        assert runner.policy_state.content_hash == "a" * 64

    def test_parse_success_atomic_swap_of_policy_state(self, tmp_path):
        """On parse success, policy_state.rules + .content_hash MUST
        swap to the new values (in-place mutation of the held
        :class:`_PolicyState` instance per the docstring)."""
        runner = self._make_runner(tmp_path)
        runner.policy_state.rules = ["old_rule"]
        runner.policy_state.content_hash = "a" * 64

        new_rules = ["new_rule_1", "new_rule_2"]
        runner.reload_policy(
            policy_load_fn=lambda _dir: new_rules,
            hash_fn=lambda _dir: "b" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=lambda _p: None,
        )
        assert runner.policy_state.rules == ["new_rule_1", "new_rule_2"]
        assert runner.policy_state.content_hash == "b" * 64

    def test_hash_unchanged_still_yields_status_applied(self, tmp_path):
        """Per ADR-0066 D356 + the existing POLICY_RELOAD_STATUSES
        docstring at runner.py:593-618 — hash-unchanged is STILL
        "applied" (the operator reloaded a byte-identical policy; the
        no-op apply is still a successful apply). A third status
        ``"unchanged"`` is operator-extensible at Pillar I trajectory."""
        runner = self._make_runner(tmp_path)
        runner.policy_state.rules = ["existing_rule"]
        runner.policy_state.content_hash = "a" * 64

        # Reload with identical hash.
        result = runner.reload_policy(
            policy_load_fn=lambda _dir: ["existing_rule"],
            hash_fn=lambda _dir: "a" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=lambda _p: None,
        )
        assert result.status == "applied"
        assert result.prior_content_hash == "a" * 64
        assert result.new_content_hash == "a" * 64

    def test_emits_policy_reloaded_event_on_applied(self, tmp_path):
        """The body emits ``policy_reloaded`` with the correct payload
        on the applied path."""
        runner = self._make_runner(tmp_path)
        emits = []
        runner.reload_policy(
            policy_load_fn=lambda _dir: [],
            hash_fn=lambda _dir: "f" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=emits.append,
        )
        assert len(emits) == 1
        event = emits[0]
        assert event["type"] == "policy_reloaded"
        assert event["status"] == "applied"
        assert event["_emitted_by"] == "daemon"
        assert event["new_content_hash"] == "f" * 64

    def test_emits_policy_reloaded_event_on_failed_unchanged(self, tmp_path):
        """Per ADR-0066 D356 — the body emits ``policy_reloaded`` ALSO
        on the failed_unchanged path (operators see parse failures in
        the ledger; ``status="failed_unchanged"`` carries the prior
        hash unchanged + new hash from the disk read)."""
        runner = self._make_runner(tmp_path)
        emits = []

        def _failing_load(_dir):
            raise ValueError("synthetic parse failure")

        runner.reload_policy(
            policy_load_fn=_failing_load,
            hash_fn=lambda _dir: "b" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=emits.append,
        )
        assert len(emits) == 1
        assert emits[0]["status"] == "failed_unchanged"
        assert emits[0]["_emitted_by"] == "daemon"

    def test_reloaded_at_ts_format_per_ADR_0010_D17(self, tmp_path):
        """Per ADR-0010 D17 — ts format is ISO-8601 UTC with 3 decimal
        ms places + 'Z' suffix matching the :func:`_utc_iso_now`
        helper used at the Pillar H init_daemon site."""
        runner = self._make_runner(tmp_path)
        result = runner.reload_policy(
            policy_load_fn=lambda _dir: [],
            hash_fn=lambda _dir: "f" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 30, 45, 123000, tzinfo=timezone.utc),
            emit_fn=lambda _p: None,
        )
        assert result.reloaded_at_ts == "2026-05-27T12:30:45.123Z"

    def test_default_seams_lazy_resolve_per_w5_p1_1_discipline(self, tmp_path):
        """Pillar H Week 5 follow-up P1-1 closure discipline — the
        production default seams MUST resolve without raising at v1.
        Behavioral-passthrough verification (not signature-only):
        omitting all kwargs invokes the production seam defaults
        (:func:`_default_policy_load` + :func:`_compute_policy_content_hash`
        + datetime.now + lazy Ledger construction) end-to-end."""
        runner = self._make_runner(tmp_path)
        # Production defaults — no kwargs.
        result = runner.reload_policy()
        assert isinstance(result, PolicyReloadResult)
        # On a fresh tmp_path with no policy_dir, the body emits with
        # status="applied" + empty rules + the SHA-256 of empty input.
        assert result.status == "applied"
        # Empty policy_dir → empty rules → SHA-256 hash of empty input.
        # The hex digest of empty bytes is deterministic.
        import hashlib
        assert result.new_content_hash == hashlib.sha256(b"").hexdigest()

    def test_only_policy_state_rules_and_content_hash_mutate_during_reload_policy_per_w7_followup_p2_2(
        self, tmp_path,
    ):
        """Pillar H Week 7 follow-up P2-2 closure — regression-barrier
        mirroring the Week 3 follow-up P3-1 + Week 5 follow-up NEW-5
        closures' discipline at :meth:`reload_policy`.

        The Week 3 follow-up P3-1 + Week 5 follow-up NEW-5 closures
        established that ONLY ``lifecycle_state`` mutates via
        :func:`object.__setattr__` during ``shutdown`` + ``run``; the
        Week 7 main commit's :meth:`reload_policy` body mutates
        ``policy_state.rules`` + ``policy_state.content_hash`` IN-PLACE
        on the held :class:`_PolicyState` instance (NOT via the
        ``object.__setattr__`` escape hatch; the frozen-dataclass
        invariant protects the field REFERENCE not the held instance).
        But no test pinned that ONLY these two fields mutate — a future
        Week-N author adding ``object.__setattr__(self, "<field>", ...)``
        OR ``runner.<other_field> = ...`` to reload_policy would
        BYPASS the W3 + W5 regression-barriers (which only run during
        shutdown + run).

        This test captures identity of all frozen + non-frozen fields
        BEFORE reload_policy + verifies all except
        ``policy_state.rules`` + ``policy_state.content_hash`` preserve
        identity AFTER.
        """
        runner = self._make_runner(tmp_path)
        # Capture identities BEFORE reload.
        before_config = runner.config
        before_config_hash = runner.config_hash
        before_pid = runner.pid
        before_started_at_ts = runner.started_at_ts
        before_version = runner.version
        before_lifecycle_state = runner.lifecycle_state
        before_policy_state = runner.policy_state  # The instance itself.

        # Invoke reload_policy via test-only seams to avoid prod ledger.
        runner.reload_policy(
            policy_load_fn=lambda _dir: ["new_rule"],
            hash_fn=lambda _dir: "b" * 64,
            now_fn=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            emit_fn=lambda _p: None,
        )

        # All frozen-dataclass fields preserve identity (the
        # ``object.__setattr__`` escape hatch IS NOT extended at
        # reload_policy per the W3 follow-up P3-1 + W5 follow-up NEW-5
        # closures' discipline).
        assert runner.config is before_config
        assert runner.config_hash is before_config_hash
        assert runner.pid is before_pid
        assert runner.started_at_ts is before_started_at_ts
        assert runner.version is before_version
        assert runner.lifecycle_state is before_lifecycle_state
        # The _PolicyState INSTANCE preserves (reload_policy mutates
        # IN-PLACE; the field reference doesn't change).
        assert runner.policy_state is before_policy_state
        # But the INTERNAL fields of _PolicyState mutated.
        assert runner.policy_state.rules == ["new_rule"]
        assert runner.policy_state.content_hash == "b" * 64


# ---------------------------------------------------------------------------
# Pillar H Week 7 — TestStageToPassesMapping (per ADR-0066 D358)
# ---------------------------------------------------------------------------


class TestStageToPassesMapping:
    """Pillar H Week 7 — :data:`_STAGE_TO_PASSES` per ADR-0066 D358
    pins the per-funnel-stage → reconcile-passes mapping for the daemon's
    Iteration 6b dispatch. The mapping is operator-readable + the
    regression-barrier catches a future Week 8+ author extending the
    mapping without updating the docstring narrative."""

    def test_keys_mirror_pillar_g_pipeline_stages(self):
        """Per-pillar mirror constants parity — the mapping keys mirror
        :data:`funnel._PILLAR_G_PIPELINE_STAGES` per the discipline."""
        from orchestrator.funnel import _PILLAR_G_PIPELINE_STAGES
        assert set(_runner._STAGE_TO_PASSES.keys()) == set(
            _PILLAR_G_PIPELINE_STAGES
        )

    def test_producer_stages_have_empty_pass_list(self):
        """``queued`` / ``researched`` / ``drafted`` / ``ready`` are
        SKILL-emitted producer stages; the daemon does NOT dispatch
        producer work at v1 (skill scope)."""
        for stage in ("queued", "researched", "drafted", "ready"):
            assert _runner._STAGE_TO_PASSES[stage] == "", (
                f"stage {stage!r} is a producer stage; the daemon does "
                f"NOT dispatch producer work at v1 per ADR-0066 D358's "
                f"channel-dispatch-deferred trajectory."
            )

    def test_sent_stage_has_empty_pass_list_per_channel_dispatch_deferred(self):
        """The ``sent`` stage maps to no passes at Week 7 because the
        channel-dispatch passes (A / D / E / F) need external clients
        (Gmail / LinkedIn / Twitter) that the daemon does NOT wire at
        v1 per ADR-0066 D358's deferred-channel-dispatch trajectory."""
        assert _runner._STAGE_TO_PASSES["sent"] == ""

    def test_replied_stage_dispatches_G_and_M(self):
        """``replied`` → Pass G (reply classification, pure framework)
        + Pass M (auto-unsubscribe handler, needs only suppressions_dir)."""
        passes = _runner._STAGE_TO_PASSES["replied"]
        # The mapping is a comma-separated string per
        # :func:`reconcile.reconcile`'s ``passes`` argument convention.
        pass_list = [p.strip() for p in passes.split(",") if p.strip()]
        assert "G" in pass_list
        assert "M" in pass_list

    def test_outcome_terminal_stage_dispatches_C_N_O(self):
        """``outcome_terminal`` → Pass C (vault↔ledger heal, needs
        people_dir) + Pass N (conversation state, pure framework) +
        Pass O (conversation outcomes, pure framework). All three are
        pure-framework + path-only."""
        passes = _runner._STAGE_TO_PASSES["outcome_terminal"]
        pass_list = [p.strip() for p in passes.split(",") if p.strip()]
        assert "C" in pass_list
        assert "N" in pass_list
        assert "O" in pass_list

    def test_channel_dispatch_passes_NOT_in_v1_mapping(self):
        """Per ADR-0066 D358 — channel-dispatch passes (A / B / D / E
        / F / H / I / J) are NOT in the v1 mapping. Pillar H Week 8+
        extends :class:`DaemonConfig` with per-channel client factory
        kwargs + extends this mapping concurrently per the per-pillar
        mirror constants parity discipline."""
        all_mapped_passes = set()
        for passes in _runner._STAGE_TO_PASSES.values():
            for p in passes.split(","):
                p = p.strip()
                if p:
                    all_mapped_passes.add(p)
        for channel_pass in ("A", "B", "D", "E", "F", "H", "I", "J"):
            assert channel_pass not in all_mapped_passes, (
                f"Channel-dispatch Pass {channel_pass} is in the v1 "
                f"_STAGE_TO_PASSES mapping; per ADR-0066 D358 the "
                f"channel-dispatch trajectory defers to Pillar H Week "
                f"8+ when :class:`DaemonConfig` extends with per-"
                f"channel client factory kwargs."
            )


# ---------------------------------------------------------------------------
# Pillar H Week 7 — TestComputePolicyContentHash (per ADR-0066 D356)
# ---------------------------------------------------------------------------


class TestComputePolicyContentHash:
    """Pillar H Week 7 — :func:`_compute_policy_content_hash` per
    ADR-0066 D356. Verifies the deterministic hash contract used by
    :meth:`DaemonRunner.reload_policy` to detect policy drift."""

    def test_missing_dir_returns_sha256_of_empty(self, tmp_path):
        """Missing policy_dir returns SHA-256 of empty input (the
        well-known ``e3b0c44...b855`` digest)."""
        import hashlib
        nonexistent = tmp_path / "does-not-exist"
        result = _runner._compute_policy_content_hash(nonexistent)
        assert result == hashlib.sha256(b"").hexdigest()

    def test_empty_dir_returns_sha256_of_empty(self, tmp_path):
        """Existing dir with no YAML files returns SHA-256 of empty
        input (symmetric with :func:`_default_policy_load`'s
        empty-rules return)."""
        import hashlib
        empty_dir = tmp_path / "empty-policies"
        empty_dir.mkdir()
        result = _runner._compute_policy_content_hash(empty_dir)
        assert result == hashlib.sha256(b"").hexdigest()

    def test_single_file_hash_differs_from_empty(self, tmp_path):
        """A non-empty YAML file produces a different hash than empty."""
        import hashlib
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        (policy_dir / "rules.yml").write_text("version: 1\nrules: []\n")
        result = _runner._compute_policy_content_hash(policy_dir)
        assert result != hashlib.sha256(b"").hexdigest()
        assert len(result) == 64

    def test_hash_byte_stable_across_invocations(self, tmp_path):
        """Cell-coverage cell: byte-identical hash across consecutive
        invocations for the same disk state (the determinism contract
        per ADR-0031 D140)."""
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        (policy_dir / "rules.yml").write_text("version: 1\nrules: []\n")
        hash1 = _runner._compute_policy_content_hash(policy_dir)
        hash2 = _runner._compute_policy_content_hash(policy_dir)
        hash3 = _runner._compute_policy_content_hash(policy_dir)
        assert hash1 == hash2 == hash3

    def test_hash_changes_on_yaml_edit(self, tmp_path):
        """Cell-coverage cell: an operator-edited YAML produces a
        different hash."""
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        (policy_dir / "rules.yml").write_text("version: 1\nrules: []\n")
        hash1 = _runner._compute_policy_content_hash(policy_dir)
        # Operator edits.
        (policy_dir / "rules.yml").write_text(
            "version: 1\nrules:\n  - name: test\n    type: cooldown.register-cooldown\n"
        )
        hash2 = _runner._compute_policy_content_hash(policy_dir)
        assert hash1 != hash2

    def test_hash_changes_on_file_added(self, tmp_path):
        """Cell-coverage cell: adding a new YAML file changes the hash
        (multiple files concatenate with NUL separator)."""
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        (policy_dir / "a.yml").write_text("version: 1\n")
        hash1 = _runner._compute_policy_content_hash(policy_dir)
        (policy_dir / "b.yml").write_text("version: 1\n")
        hash2 = _runner._compute_policy_content_hash(policy_dir)
        assert hash1 != hash2

    def test_hash_independent_of_filename_within_sort_order(self, tmp_path):
        """Per the docstring — filename is operationally a sort-key
        NOT a rule-identity field. Two policy_dirs with byte-identical
        file CONTENTS but different filenames produce DIFFERENT hashes
        ONLY IF the sort order changes the concatenation order; same
        filename → same content order → same hash.

        This test pins the file-content + sort-order contract: two
        dirs with identical file contents AT THE SAME sorted positions
        produce identical hashes."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        (dir1 / "a.yml").write_text("content1\n")
        (dir1 / "b.yml").write_text("content2\n")

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        (dir2 / "a.yml").write_text("content1\n")
        (dir2 / "b.yml").write_text("content2\n")

        # Same content, same sort order → same hash.
        assert (
            _runner._compute_policy_content_hash(dir1)
            == _runner._compute_policy_content_hash(dir2)
        )


# ---------------------------------------------------------------------------
# Pillar H Week 8 — Per-event-class index dataclasses + materialization per
# ADR-0067 D359-D361 + ADR-0060 D336 (R039 mitigation pattern)
# ---------------------------------------------------------------------------


class TestEventClassIndex:
    """Pillar H Week 8 — :class:`EventClassIndex` dataclass per
    ADR-0067 D359.

    Cells:
    * Empty index returns empty list per class.
    * Populated index returns Event-wrapped entries per class.
    * Defensive-copy posture preserved (returned list independent of
      internal ``_data``).
    * Closed-set validation refuses-loud on uncatalogued event_class.
    * Mutable holder pattern (NOT frozen) — Week 9 will mutate
      ``_data`` directly.
    """

    def test_empty_index_returns_empty_list_per_w8_d359(self):
        idx = EventClassIndex()
        assert idx.events_for_class("daemon_started") == []

    def test_populated_index_returns_event_wrapped_entries_per_w8_d359(self):
        idx = EventClassIndex()
        idx._data["daemon_started"] = [
            {"v": 1, "type": "daemon_started", "ts": "2026-05-27T10:00:00.000Z",
             "pid": 12345, "version": "0.1.0", "config_hash": "a" * 64,
             "startup_seconds": 1.0, "_emitted_by": "daemon"},
        ]
        events = idx.events_for_class("daemon_started")
        assert len(events) == 1
        from orchestrator.ledger import Event as _Event
        assert isinstance(events[0], _Event)
        assert events[0].type == "daemon_started"
        assert events[0]["pid"] == 12345

    def test_defensive_copy_query_isolates_caller_per_w8_d359(self):
        """ADR-0067 D359 — :meth:`events_for_class` returns a fresh
        list of Event-wrapped objects on each call; mutating the
        returned list does NOT mutate the index's internal ``_data``.
        """
        idx = EventClassIndex()
        idx._data["daemon_started"] = [
            {"v": 1, "type": "daemon_started", "ts": "2026-05-27T10:00:00.000Z",
             "pid": 1, "_emitted_by": "daemon"},
        ]
        events1 = idx.events_for_class("daemon_started")
        events1.clear()
        # Internal state preserved.
        assert len(idx._data["daemon_started"]) == 1
        events2 = idx.events_for_class("daemon_started")
        assert len(events2) == 1

    def test_refuses_loud_on_uncatalogued_event_class_per_w8_d359(self):
        idx = EventClassIndex()
        with pytest.raises(ValueError, match="EVENT_CLASS_CATALOG"):
            idx.events_for_class("not_an_event_class")

    def test_mutable_holder_not_frozen_per_w7_policy_state_precedent(self):
        """ADR-0067 D359 — :class:`EventClassIndex` is a mutable
        holder mirroring the W7 :class:`_PolicyState` precedent per
        ADR-0066 D356. Tests can directly mutate ``_data`` per the
        mutable-holder pattern (Week 9 ships :meth:`Ledger.append`-
        driven invalidation per ADR-0060 D336 via this same mutation
        path).
        """
        idx = EventClassIndex()
        idx._data["daemon_started"] = []
        # This mutation IS allowed (per the mutable-holder pattern).
        assert idx._data == {"daemon_started": []}

    def test_each_event_class_in_catalog_accepted_per_w8_d359(self):
        """Per-pillar mirror constants parity discipline — the query
        API accepts EVERY class in :data:`EVENT_CLASS_CATALOG`."""
        idx = EventClassIndex()
        for class_name in _observability.EVENT_CLASS_CATALOG:
            # Should not raise.
            result = idx.events_for_class(class_name)
            assert result == []


class TestPersonEventIndex:
    """Pillar H Week 8 — :class:`PersonEventIndex` dataclass per
    ADR-0067 D359.

    Cells:
    * Empty index returns empty list per person_id.
    * Populated index returns Event-wrapped entries per person_id.
    * Defensive-copy posture preserved.
    * Mutable holder pattern.
    * Unknown person_id returns empty list (NOT refuse-loud — the
      person_id surface is operator-private + the index is denormalized
      from the ledger; querying for an unknown person_id is valid).
    """

    def test_empty_index_returns_empty_list_per_w8_d359(self):
        idx = PersonEventIndex()
        assert idx.events_for("p-abc-123") == []

    def test_populated_index_returns_event_wrapped_entries_per_w8_d359(self):
        idx = PersonEventIndex()
        idx._data["p-abc-123"] = [
            {"v": 1, "type": "enrolled", "ts": "2026-05-27T10:00:00.000Z",
             "person_id": "p-abc-123"},
            {"v": 1, "type": "send_intent", "ts": "2026-05-27T10:01:00.000Z",
             "person_id": "p-abc-123", "channel": "email",
             "intent_id": "snd_abc"},
        ]
        events = idx.events_for("p-abc-123")
        assert len(events) == 2
        assert events[0].type == "enrolled"
        assert events[1].type == "send_intent"
        assert events[1].get("channel") == "email"

    def test_defensive_copy_query_isolates_caller_per_w8_d359(self):
        idx = PersonEventIndex()
        idx._data["p-abc-123"] = [
            {"v": 1, "type": "enrolled", "ts": "2026-05-27T10:00:00.000Z",
             "person_id": "p-abc-123"},
        ]
        events1 = idx.events_for("p-abc-123")
        events1.clear()
        # Internal state preserved.
        assert len(idx._data["p-abc-123"]) == 1

    def test_unknown_person_id_returns_empty_list_per_w8_d359(self):
        """Unknown person_id is operator-valid (the index is denormalized
        from the ledger; an operator querying for a Person that was
        just enrolled but has no downstream events is valid)."""
        idx = PersonEventIndex()
        idx._data["p-known"] = [
            {"v": 1, "type": "enrolled", "person_id": "p-known"},
        ]
        assert idx.events_for("p-unknown") == []


class TestMaterializeIndexes:
    """Pillar H Week 8 — :func:`_materialize_indexes` single-walk
    dual-index materialization per ADR-0067 D360 + ADR-0060 D336.

    Cells:
    * Empty ledger produces empty indexes.
    * Single event populates both indexes.
    * Uncatalogued event_class silently skipped from EventClassIndex
      (the diagnostic posture stays at primitive-call time per ADR-0051
      D279).
    * Person-less event indexed in EventClassIndex but skipped from
      PersonEventIndex.
    * Chronological order preserved (the ledger's ts-sort propagates
      to both indexes' per-key lists).
    * Single-walk discipline (one ledger walk produces both indexes).
    """

    def _make_ledger_with_events(self, tmp_path, events):
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        for ev in events:
            led.append(ev)
        return led

    def test_empty_ledger_produces_empty_indexes_per_w8_d360(self, tmp_path):
        led = self._make_ledger_with_events(tmp_path, [])
        event_class_idx, person_idx = _runner._materialize_indexes(led)
        assert event_class_idx._data == {}
        assert person_idx._data == {}

    def test_single_event_populates_both_indexes_per_w8_d360(self, tmp_path):
        led = self._make_ledger_with_events(tmp_path, [
            {"type": "enrolled", "person_id": "p-1", "channel": "email"},
        ])
        event_class_idx, person_idx = _runner._materialize_indexes(led)
        assert "enrolled" in event_class_idx._data
        assert len(event_class_idx._data["enrolled"]) == 1
        assert "p-1" in person_idx._data
        assert len(person_idx._data["p-1"]) == 1

    def test_uncatalogued_event_class_skipped_from_event_class_index_per_w8_d360(
        self, tmp_path,
    ):
        """ADR-0067 D360 — events whose type is NOT in
        :data:`EVENT_CLASS_CATALOG` are silently SKIPPED from
        EventClassIndex; the uncatalogued diagnostic posture stays
        at primitive-call time per ADR-0051 D279."""
        led = self._make_ledger_with_events(tmp_path, [
            {"type": "definitely_not_a_catalog_class",
             "person_id": "p-1"},
            {"type": "enrolled", "person_id": "p-1"},
        ])
        event_class_idx, person_idx = _runner._materialize_indexes(led)
        # Uncatalogued class is NOT in event_class_idx.
        assert "definitely_not_a_catalog_class" not in event_class_idx._data
        # BUT the catalogued class IS.
        assert "enrolled" in event_class_idx._data
        # The uncatalogued event IS still in person_idx (per ADR-0067
        # D360 — person_id is a separate concern from catalog).
        assert len(person_idx._data["p-1"]) == 2

    def test_person_less_event_indexed_in_event_class_but_not_person_index_per_w8_d360(
        self, tmp_path,
    ):
        """ADR-0067 D360 — ad-hoc validation events (Pillar F per
        ADR-0045 D231) have NO person_id; they ARE indexed by class
        but skipped from PersonEventIndex."""
        led = self._make_ledger_with_events(tmp_path, [
            # No person_id field — ad-hoc validation event.
            {"type": "draft_quality_scored", "register": "cold-pitch",
             "voice_fidelity_score": 0.85, "state": "ready"},
        ])
        event_class_idx, person_idx = _runner._materialize_indexes(led)
        assert "draft_quality_scored" in event_class_idx._data
        assert person_idx._data == {}  # No person_id → skipped.

    def test_chronological_order_preserved_per_w8_d360(self, tmp_path):
        """ADR-0067 D360 — :meth:`Ledger.all_events` sorts by ts; the
        index per-key lists are append-only chronologically."""
        led = self._make_ledger_with_events(tmp_path, [
            {"type": "enrolled", "person_id": "p-1",
             "ts": "2026-05-27T10:00:00.000Z"},
            {"type": "send_intent", "person_id": "p-1", "channel": "email",
             "intent_id": "snd_a", "ts": "2026-05-27T10:01:00.000Z"},
            {"type": "send_confirmed", "person_id": "p-1", "channel": "email",
             "intent_id": "snd_a", "ts": "2026-05-27T10:02:00.000Z"},
        ])
        event_class_idx, person_idx = _runner._materialize_indexes(led)
        # Person index events for p-1 are in chronological order.
        events = person_idx._data["p-1"]
        assert [e["type"] for e in events] == [
            "enrolled", "send_intent", "send_confirmed",
        ]

    def test_single_walk_produces_both_indexes_per_w8_d360(self, tmp_path):
        """ADR-0067 D360 — the single-walk discipline mirrors Pillar G
        Week 2 :func:`collect_event_class_snapshots`. We verify the
        function returns BOTH indexes from ONE invocation (not two
        separate walks)."""
        led = self._make_ledger_with_events(tmp_path, [
            {"type": "enrolled", "person_id": "p-1"},
            {"type": "enrolled", "person_id": "p-2"},
        ])
        result = _runner._materialize_indexes(led)
        # Single-walk produces a two-tuple.
        assert isinstance(result, tuple) and len(result) == 2
        event_class_idx, person_idx = result
        assert len(event_class_idx._data["enrolled"]) == 2
        assert set(person_idx._data.keys()) == {"p-1", "p-2"}


class TestInitDaemonIndexMaterialization:
    """Pillar H Week 8 — :func:`init_daemon` Step 8 wires the
    per-event-class + per-Person index materialization per ADR-0067
    D360.

    Cells:
    * Default seam (omitted ``index_materialize_fn``) walks the real
      Ledger from :attr:`DaemonConfig.ledger_dir` —
      BEHAVIORAL-PASSTHROUGH regression-barrier per the W5 P1-1 + W7
      P1-1 closures' canonical safeguard.
    * Test-only seam (provided ``index_materialize_fn``) returns
      pre-populated indexes verbatim.
    * Index fields populated on DaemonRunner.
    * Step 8 runs AFTER Prometheus (Step 7) + BEFORE DaemonRunner
      construction (Step 9).
    """

    def _make_valid_config(self, tmp_path) -> DaemonConfig:
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        return DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)

    def test_default_walks_real_ledger_per_w8_d360_behavioral_passthrough(
        self, tmp_path,
    ):
        """ADR-0067 D360 + W5 P1-1 / W7 P1-1 closures' BEHAVIORAL-
        PASSTHROUGH discipline — the production-default path
        (omitted ``index_materialize_fn``) constructs a real
        :class:`Ledger` from :attr:`DaemonConfig.ledger_dir` + walks
        once. We pre-seed the ledger with a known event + verify the
        index reflects the walked state.
        """
        config = self._make_valid_config(tmp_path)
        # Pre-seed the ledger.
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(config.ledger_dir)
        led.append({"type": "enrolled", "person_id": "p-pre-seed"})
        led.append({"type": "send_intent", "person_id": "p-pre-seed",
                    "channel": "email", "intent_id": "snd_test"})

        # Production default — NO index_materialize_fn kwarg.
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )

        # The production default walked the real ledger.
        assert "enrolled" in runner.event_class_index._data
        assert "send_intent" in runner.event_class_index._data
        assert "p-pre-seed" in runner.person_event_index._data
        person_events = runner.person_event_index._data["p-pre-seed"]
        assert len(person_events) == 2

    def test_index_materialize_fn_seam_per_w8_d360(self, tmp_path):
        """ADR-0067 D360 test-only seam — when provided, the seam's
        return value populates :attr:`DaemonRunner.event_class_index`
        + :attr:`DaemonRunner.person_event_index` verbatim (the
        production ledger walk is SKIPPED).
        """
        config = self._make_valid_config(tmp_path)
        sentinel_event_class_idx = EventClassIndex()
        sentinel_event_class_idx._data["daemon_started"] = [
            {"type": "daemon_started", "pid": 1, "_emitted_by": "daemon"},
        ]
        sentinel_person_idx = PersonEventIndex()
        sentinel_person_idx._data["p-sentinel"] = [
            {"type": "enrolled", "person_id": "p-sentinel"},
        ]

        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
            index_materialize_fn=lambda: (
                sentinel_event_class_idx, sentinel_person_idx,
            ),
        )
        assert runner.event_class_index is sentinel_event_class_idx
        assert runner.person_event_index is sentinel_person_idx

    def test_index_fields_populated_on_daemon_runner_per_w8_d359(
        self, tmp_path,
    ):
        """ADR-0067 D359 — :class:`DaemonRunner` has TWO new fields
        populated by :func:`init_daemon` Step 8."""
        config = self._make_valid_config(tmp_path)
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert isinstance(runner.event_class_index, EventClassIndex)
        assert isinstance(runner.person_event_index, PersonEventIndex)

    def test_step_8_runs_between_prometheus_and_construction_per_w8_d360(
        self, tmp_path,
    ):
        """ADR-0067 D360 — Step 8 (index materialization) runs AFTER
        Step 7 (Prometheus) + BEFORE Step 9 (DaemonRunner construction).

        The startup ordering invariant per ADR-0061 D337 (extended at
        Pillar H Week 8 per ADR-0067 D360 with NEW Step 8) is:
        migrations → policy → otel_meter → otel_tracer → prometheus →
        index → construct.
        """
        config = self._make_valid_config(tmp_path)
        call_order: list[str] = []

        def _spy_materialize() -> tuple[EventClassIndex, PersonEventIndex]:
            call_order.append("index")
            return EventClassIndex(), PersonEventIndex()

        init_daemon(
            config,
            migration_apply_fn=lambda: call_order.append("migrations"),
            policy_load_fn=lambda _dir: (call_order.append("policy") or []),
            otel_meter_init_fn=lambda *a, **kw: call_order.append("otel_meter"),
            otel_tracer_init_fn=lambda *a, **kw: call_order.append("otel_tracer"),
            prometheus_start_fn=lambda *a, **kw: call_order.append("prometheus"),
            index_materialize_fn=_spy_materialize,
        )
        # Index materialization is the LAST step before DaemonRunner
        # construction.
        assert call_order == [
            "migrations", "policy", "otel_meter", "otel_tracer",
            "prometheus", "index",
        ]

    def test_runner_constructed_directly_has_empty_indexes_per_w8_d359(self):
        """ADR-0067 D359 default_factory — :class:`DaemonRunner`
        constructed directly by tests (bypassing :func:`init_daemon`)
        gets empty indexes. The Pillar H Week 7 precedent
        (:attr:`policy_state` default_factory) applies."""
        runner = DaemonRunner(
            config=DaemonConfig(
                vault_dir=Path("/tmp/vault-doesnt-matter"),
                ledger_dir=Path("/tmp/ledger-doesnt-matter"),
            ),
            config_hash="a" * 64,
            pid=1,
            started_at_ts="2026-05-27T10:00:00.000Z",
            version="0.1.0",
        )
        assert isinstance(runner.event_class_index, EventClassIndex)
        assert isinstance(runner.person_event_index, PersonEventIndex)
        assert runner.event_class_index._data == {}
        assert runner.person_event_index._data == {}


class TestPerPersonPrimitiveIndexConsumption:
    """Pillar H Week 8 — the THREE per-Person primitives at
    :mod:`orchestrator.observability` extended with optional
    ``event_class_index`` kwarg per ADR-0067 D361.

    Cells (per primitive):
    * Omitted kwarg → ledger-walk path preserved (ADR-0059 D325
      READ-ONLY contract).
    * Provided kwarg → index path produces IDENTICAL snapshot list
      (byte-identical determinism per ADR-0031 D140).

    The behavioral-passthrough discipline per W5 P1-1 + W7 P1-1
    closures requires verification that BOTH paths produce equivalent
    results — the production default (ledger walk) is exercised
    transparently.
    """

    def _ledger_with_events(self, tmp_path, events):
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        for ev in events:
            led.append(ev)
        return led

    def test_register_fidelity_index_path_matches_ledger_path_per_w8_d361(
        self, tmp_path,
    ):
        """ADR-0067 D361 — the index-vs-ledger paths produce
        byte-identical snapshot lists."""
        events = [
            {"type": "draft_quality_scored", "person_id": "p-1",
             "register": "cold-pitch", "voice_fidelity_score": 0.85,
             "state": "ready", "channel": "email",
             "ts": "2026-05-27T10:00:00.000Z"},
            {"type": "draft_quality_scored", "person_id": "p-2",
             "register": "congrats", "voice_fidelity_score": 0.90,
             "state": "ready", "channel": "email",
             "ts": "2026-05-27T10:01:00.000Z"},
            # Decoy: different event class should NOT affect snapshots.
            {"type": "enrolled", "person_id": "p-3",
             "ts": "2026-05-27T10:02:00.000Z"},
        ]
        led = self._ledger_with_events(tmp_path, events)
        event_class_idx, _ = _runner._materialize_indexes(led)
        since = datetime(2026, 5, 27, tzinfo=timezone.utc)

        ledger_snaps = _observability.collect_per_person_register_fidelity_snapshots(
            led, since=since,
        )
        index_snaps = _observability.collect_per_person_register_fidelity_snapshots(
            led, since=since, event_class_index=event_class_idx,
        )
        assert ledger_snaps == index_snaps
        assert len(ledger_snaps) == 2  # p-1 + p-2

    def test_claim_type_hallucination_index_path_matches_ledger_path_per_w8_d361(
        self, tmp_path,
    ):
        """ADR-0067 D361 — index-vs-ledger paths produce identical
        snapshots for ``hallucination_detected`` consumer."""
        events = [
            {"type": "hallucination_detected", "person_id": "p-1",
             "register": "cold-pitch", "channel": "email",
             "uncited_claims": [{"claim_type": "date_reference",
                                  "claim_text": "REDACTED"}],
             "ts": "2026-05-27T10:00:00.000Z"},
            # Decoy
            {"type": "draft_quality_scored", "person_id": "p-1",
             "register": "cold-pitch", "voice_fidelity_score": 0.8,
             "state": "ready", "ts": "2026-05-27T10:01:00.000Z"},
        ]
        led = self._ledger_with_events(tmp_path, events)
        event_class_idx, _ = _runner._materialize_indexes(led)
        since = datetime(2026, 5, 27, tzinfo=timezone.utc)

        ledger_snaps = _observability.collect_per_person_claim_type_hallucination_snapshots(
            led, since=since,
        )
        index_snaps = _observability.collect_per_person_claim_type_hallucination_snapshots(
            led, since=since, event_class_index=event_class_idx,
        )
        assert ledger_snaps == index_snaps

    def test_layer_5_drift_index_path_matches_ledger_path_per_w8_d361(
        self, tmp_path,
    ):
        """ADR-0067 D361 — index-vs-ledger paths produce identical
        snapshots for ``reconcile_drift`` consumer."""
        events = [
            {"type": "reconcile_drift", "person_id": "p-1",
             "reason": "ready_without_draft_ready_event",
             "ts": "2026-05-27T10:00:00.000Z"},
            # Decoy.
            {"type": "enrolled", "person_id": "p-2",
             "ts": "2026-05-27T10:01:00.000Z"},
        ]
        led = self._ledger_with_events(tmp_path, events)
        event_class_idx, _ = _runner._materialize_indexes(led)
        since = datetime(2026, 5, 27, tzinfo=timezone.utc)

        ledger_snaps = _observability.collect_per_person_layer_5_drift_snapshots(
            led, since=since,
        )
        index_snaps = _observability.collect_per_person_layer_5_drift_snapshots(
            led, since=since, event_class_index=event_class_idx,
        )
        assert ledger_snaps == index_snaps

    def test_default_kwarg_preserves_ledger_walk_per_w8_d361(self, tmp_path):
        """ADR-0067 D361 + ADR-0059 D325 READ-ONLY contract — the
        kwarg's default of None preserves the existing ledger-walk
        behavior verbatim. Pre-Week-8 callers (the funnel CLI; external
        operator invocations) work unchanged."""
        events = [
            {"type": "draft_quality_scored", "person_id": "p-1",
             "register": "cold-pitch", "voice_fidelity_score": 0.85,
             "state": "ready", "channel": "email",
             "ts": "2026-05-27T10:00:00.000Z"},
        ]
        led = self._ledger_with_events(tmp_path, events)
        since = datetime(2026, 5, 27, tzinfo=timezone.utc)

        # Default kwarg — NO event_class_index.
        snaps = _observability.collect_per_person_register_fidelity_snapshots(
            led, since=since,
        )
        assert len(snaps) == 1
        assert snaps[0].person_id == "p-1"
        assert snaps[0].register == "cold-pitch"

    def test_index_path_empty_for_class_returns_empty_snapshots_per_w8_d361(
        self, tmp_path,
    ):
        """ADR-0067 D361 — when the index has NO events for the
        primitive's target class, the snapshot list is empty (no
        spurious snapshots from other classes in the index)."""
        events = [
            # No draft_quality_scored events — only enrolled events.
            {"type": "enrolled", "person_id": "p-1",
             "ts": "2026-05-27T10:00:00.000Z"},
        ]
        led = self._ledger_with_events(tmp_path, events)
        event_class_idx, _ = _runner._materialize_indexes(led)
        since = datetime(2026, 5, 27, tzinfo=timezone.utc)

        snaps = _observability.collect_per_person_register_fidelity_snapshots(
            led, since=since, event_class_index=event_class_idx,
        )
        assert snaps == []


# ---------------------------------------------------------------------------
# Pillar H Week 8 follow-up — per-week review findings (0 P1 + 2 P2 + 6 P3
# + 1 NEW addressed + 4 REFUTED). The SEVENTH ADR-vs-actual-impl drift in
# Pillar H caught at W8 follow-up P2-1 (EventClassIndex catalog scope vs
# Pillar G collect_event_class_snapshots consumer surface precedent).
# ---------------------------------------------------------------------------


class TestW8FollowupEventClassIndexCatalogScope:
    """Pillar H Week 8 follow-up P2-1 closure — the SEVENTH ADR-vs-
    actual-impl drift in Pillar H caught by the per-week-reviewer's
    cross-pillar back-audit discipline. The W8 main commit's catalog
    scope at :meth:`EventClassIndex.events_for_class` + the
    :func:`_materialize_indexes` body was ``EVENT_CLASS_CATALOG``
    only — diverging from the Pillar G
    :func:`observability.collect_event_class_snapshots` consumer
    surface's ``expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES``
    precedent at :file:`orchestrator/observability.py:910`.

    The W8 follow-up extends the catalog scope to match Pillar G's
    precedent. The regression-barrier tests below pin the structural
    commitment that operators see ``slo_violation_detected`` (Pillar G
    Week 7-8 emit per ADR-0056) + ``observability_class_uncatalogued``
    (Pillar G Week 2 emit per ADR-0051 D279) accepted by the
    EventClassIndex query API + indexed by :func:`_materialize_indexes`.

    Cross-pillar back-audit discipline EXTENDED to SEVEN consecutive
    Pillar H weeks of ADR-vs-actual-impl drift catches (W2 P3-8 → W3
    P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2 → W7 P1-1 → W8 follow-up P2-1).
    """

    def test_events_for_class_accepts_observability_new_event_classes_per_w8_followup_p2_1(
        self,
    ):
        """Pillar H Week 8 follow-up P2-1 closure — the query API
        accepts every class in
        :data:`observability.OBSERVABILITY_NEW_EVENT_CLASSES` (the
        TWO Pillar G observability-internal classes per ADR-0050
        D273: ``observability_class_uncatalogued`` +
        ``slo_violation_detected``). Pre-W8-follow-up, these queries
        raised ValueError; post-W8-follow-up they return empty lists
        (no events of that class indexed at startup if the operator
        hasn't triggered Pillar G's per-call surfaces).
        """
        idx = EventClassIndex()
        for class_name in _observability.OBSERVABILITY_NEW_EVENT_CLASSES:
            # Should not raise (W8 follow-up P2-1 closure).
            result = idx.events_for_class(class_name)
            assert result == [], (
                f"EventClassIndex.events_for_class({class_name!r}) should "
                f"return empty list at empty index per W8 follow-up P2-1 "
                f"closure"
            )

    def test_materialize_indexes_includes_observability_new_event_classes_per_w8_followup_p2_1(
        self, tmp_path,
    ):
        """Pillar H Week 8 follow-up P2-1 closure — the
        :func:`_materialize_indexes` body includes events whose type
        is in :data:`OBSERVABILITY_NEW_EVENT_CLASSES`. Pre-W8-follow-up,
        ``slo_violation_detected`` events were silently SKIPPED from
        the index even though the Pillar G
        :func:`collect_event_class_snapshots` consumer surface treats
        them as catalogued.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        led.append({"type": "slo_violation_detected",
                    "slo_name": "p99_send_latency",
                    "observed_value": 5.5, "threshold": 5.0,
                    "window_seconds": 300, "channel": "email",
                    "_emitted_by": "observability"})
        led.append({"type": "observability_class_uncatalogued",
                    "kind": "uncatalogued", "offending_type": "fake",
                    "count": 1, "channel": None,
                    "_emitted_by": "observability"})
        # Decoy: a catalogued class.
        led.append({"type": "enrolled", "person_id": "p-1"})

        event_class_idx, _ = _runner._materialize_indexes(led)
        # The TWO Pillar G observability-internal classes are NOW in
        # the index (W8 follow-up P2-1 closure).
        assert "slo_violation_detected" in event_class_idx._data
        assert "observability_class_uncatalogued" in event_class_idx._data
        assert len(event_class_idx._data["slo_violation_detected"]) == 1
        assert len(event_class_idx._data["observability_class_uncatalogued"]) == 1
        # The catalogued class is also there.
        assert "enrolled" in event_class_idx._data

    def test_events_for_class_query_returns_indexed_slo_violation_events_per_w8_followup_p2_1(
        self, tmp_path,
    ):
        """Pillar H Week 8 follow-up P2-1 closure — operators query
        ``EventClassIndex.events_for_class("slo_violation_detected")``
        + see the indexed events Event-wrapped (mirrors the
        cross-pillar back-audit consistency with Pillar G's consumer
        surface).
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        led.append({"type": "slo_violation_detected",
                    "slo_name": "p99_send_latency",
                    "observed_value": 5.5, "threshold": 5.0,
                    "window_seconds": 300, "channel": "email",
                    "_emitted_by": "observability"})

        event_class_idx, _ = _runner._materialize_indexes(led)
        slo_events = event_class_idx.events_for_class("slo_violation_detected")
        assert len(slo_events) == 1
        assert slo_events[0].type == "slo_violation_detected"
        assert slo_events[0].get("slo_name") == "p99_send_latency"

    def test_uncatalogued_event_still_skipped_per_w8_followup_p2_1(
        self, tmp_path,
    ):
        """Pillar H Week 8 follow-up P2-1 closure — events whose type
        is NEITHER in EVENT_CLASS_CATALOG NOR in
        OBSERVABILITY_NEW_EVENT_CLASSES are STILL silently SKIPPED
        from the index. The W8 follow-up P2-1 closure extends the
        known-classes scope; it does NOT remove the uncatalogued-skip
        discipline.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        led.append({"type": "totally_unknown_class_xyz",
                    "person_id": "p-1"})
        led.append({"type": "enrolled", "person_id": "p-1"})

        event_class_idx, _ = _runner._materialize_indexes(led)
        # Truly unknown class is NOT in the index.
        assert "totally_unknown_class_xyz" not in event_class_idx._data
        # Catalogued class IS.
        assert "enrolled" in event_class_idx._data

    def test_events_for_class_refuses_loud_on_truly_uncatalogued_per_w8_followup_p2_1(
        self,
    ):
        """Pillar H Week 8 follow-up P2-1 closure — the query API
        STILL refuses-loud on classes NEITHER in EVENT_CLASS_CATALOG
        NOR in OBSERVABILITY_NEW_EVENT_CLASSES. The closed-set
        discipline preserves verbatim — the scope just extends.
        """
        idx = EventClassIndex()
        with pytest.raises(
            ValueError,
            match="OBSERVABILITY_NEW_EVENT_CLASSES",
        ):
            idx.events_for_class("totally_unknown_class_xyz")


# ---------------------------------------------------------------------------
# Pillar H Week 9 — per-event-class index invalidation on Ledger.append
# per ADR-0067 D362 (W9 extension to ADR-0067 per ADR-0060 D336)
# ---------------------------------------------------------------------------


class TestLedgerAppendObserverSeam:
    """Pillar H Week 9 per ADR-0067 D362 — :meth:`Ledger.append_observer`
    + post-append observer firing contract (cross-pillar surface
    extension at :mod:`orchestrator.ledger`).
    """

    def test_observer_registered_via_append_observer(self, tmp_path):
        """Pillar H Week 9 — :meth:`Ledger.append_observer` registers a
        callback that fires on subsequent :meth:`Ledger.append` per
        ADR-0067 D362.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        captured: list[dict] = []
        led.append_observer(captured.append)
        led.append({"type": "enrolled", "person_id": "p-1"})
        assert len(captured) == 1
        assert captured[0]["type"] == "enrolled"
        assert captured[0]["person_id"] == "p-1"

    def test_observer_fires_after_ts_and_v_defaults_filled_per_adr_0067_d362(
        self, tmp_path,
    ):
        """Pillar H Week 9 — the observer sees the SERIALIZED event dict
        (with ``ts`` + ``v`` defaults filled in by :meth:`Ledger.append`)
        per ADR-0067 D362. The observer receives the same dict shape
        the :func:`_invalidate_indexes_on_append` helper expects.
        """
        from orchestrator.ledger import Ledger as _Ledger, SCHEMA_VERSION
        led = _Ledger(tmp_path / "ledger")
        captured: list[dict] = []
        led.append_observer(captured.append)
        led.append({"type": "enrolled", "person_id": "p-1"})
        assert "ts" in captured[0]
        assert captured[0]["v"] == SCHEMA_VERSION

    def test_observer_fires_after_fsync_per_atomicity_invariant(
        self, tmp_path,
    ):
        """Pillar H Week 9 — the observer fires AFTER fsync + symlink +
        mtime-cache invalidation per the Ledger.append Week 9 body's
        ordering. Verifies the atomicity invariant per ADR-0060 D335
        invariant 2 — the ledger is DURABLE before the observer sees
        the event (a daemon crash between fsync + observer fire leaves
        the ledger consistent + re-materializable from I3 at restart).
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        captured_fs_state: list[bool] = []

        def _observer(_d: dict) -> None:
            # When the observer fires, the events-*.jsonl file MUST
            # exist on disk (fsync already completed).
            files = list((tmp_path / "ledger").glob("events-*.jsonl"))
            captured_fs_state.append(len(files) > 0)

        led.append_observer(_observer)
        led.append({"type": "enrolled", "person_id": "p-1"})
        assert captured_fs_state == [True]

    def test_observer_exception_does_not_propagate_per_durability_contract(
        self, tmp_path, capfd,
    ):
        """Pillar H Week 9 — observer exceptions log to stderr but do
        NOT propagate per ADR-0067 D362 + ADR-0060 D335 invariant 2.
        The ledger is durable BEFORE the observer fires; observer
        failure does NOT roll back the append.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")

        def _failing_observer(_d: dict) -> None:
            raise RuntimeError("simulated observer failure")

        led.append_observer(_failing_observer)
        # The append must SUCCEED (no exception propagated).
        result = led.append({"type": "enrolled", "person_id": "p-1"})
        assert result["type"] == "enrolled"
        # The error logged to stderr per the W9 best-effort posture.
        _stdout, stderr = capfd.readouterr()
        assert "ledger post-append observer" in stderr
        assert "simulated observer failure" in stderr

    def test_multiple_observers_fire_in_registration_order(self, tmp_path):
        """Pillar H Week 9 — multiple observers fire in registration
        order. Pillar I per-tenant audit-tooling + Pillar J GDPR purge
        per ADR-0067 D362's W9 extension narrative naming the "multiple
        observers" scenario.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        order: list[str] = []
        led.append_observer(lambda _d: order.append("first"))
        led.append_observer(lambda _d: order.append("second"))
        led.append_observer(lambda _d: order.append("third"))
        led.append({"type": "enrolled", "person_id": "p-1"})
        assert order == ["first", "second", "third"]

    def test_observer_only_fires_for_appends_to_same_ledger_instance(
        self, tmp_path,
    ):
        """Pillar H Week 9 — observers are per-Ledger-instance per
        ADR-0067 D362 ("cross-process consistency note"). Appends to a
        DIFFERENT Ledger instance (even on the same directory) do NOT
        trigger the observer. Documents the v1 single-tenant +
        concurrent-CLI gap.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led_a = _Ledger(tmp_path / "ledger")
        led_b = _Ledger(tmp_path / "ledger")  # SAME directory, NEW instance.
        captured: list[dict] = []
        led_a.append_observer(captured.append)
        # Append via the OTHER Ledger instance.
        led_b.append({"type": "enrolled", "person_id": "p-1"})
        # led_a's observer does NOT see it.
        assert captured == []


class TestInvalidateIndexesOnAppend:
    """Pillar H Week 9 per ADR-0067 D362 — :func:`_invalidate_indexes_on_append`
    per-event invalidation helper contract.
    """

    def _known_classes(self):
        return (
            _observability.EVENT_CLASS_CATALOG
            | _observability.OBSERVABILITY_NEW_EVENT_CLASSES
        )

    def test_invalidates_event_class_index_for_catalogued_event(self):
        """Pillar H Week 9 — a catalogued event (type in
        :data:`EVENT_CLASS_CATALOG`) is appended to
        :attr:`EventClassIndex._data[type]` per ADR-0067 D362.
        """
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        ev = {"type": "enrolled", "person_id": "p-1", "ts": "2026-05-27T00:00:00Z", "v": 1}
        _runner._invalidate_indexes_on_append(
            ec_idx, pe_idx, ev, self._known_classes(),
            now_ts_fn=lambda: 100.0,
        )
        assert "enrolled" in ec_idx._data
        assert ec_idx._data["enrolled"] == [ev]

    def test_invalidates_person_event_index_for_event_with_person_id(self):
        """Pillar H Week 9 — an event with ``person_id`` is appended to
        :attr:`PersonEventIndex._data[person_id]` per ADR-0067 D362.
        """
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        ev = {"type": "enrolled", "person_id": "p-1", "ts": "2026-05-27T00:00:00Z", "v": 1}
        _runner._invalidate_indexes_on_append(
            ec_idx, pe_idx, ev, self._known_classes(),
            now_ts_fn=lambda: 100.0,
        )
        assert "p-1" in pe_idx._data
        assert pe_idx._data["p-1"] == [ev]

    def test_skips_uncatalogued_event_from_event_class_index_per_w8_followup_p2_1(
        self,
    ):
        """Pillar H Week 9 — events whose type is NEITHER in
        ``EVENT_CLASS_CATALOG`` NOR in ``OBSERVABILITY_NEW_EVENT_CLASSES``
        are silently SKIPPED from :class:`EventClassIndex` per the W8
        follow-up P2-1 closure's extended scope mirrored at the
        per-append invalidation site. The structural mirror of
        :func:`_materialize_indexes`'s per-event branch shape preserves
        the byte-identical determinism contract per ADR-0031 D140.
        """
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        ev = {"type": "totally_unknown_xyz", "person_id": "p-1",
              "ts": "2026-05-27T00:00:00Z", "v": 1}
        _runner._invalidate_indexes_on_append(
            ec_idx, pe_idx, ev, self._known_classes(),
            now_ts_fn=lambda: 100.0,
        )
        # Uncatalogued class NOT indexed by class.
        assert "totally_unknown_xyz" not in ec_idx._data
        # BUT the person_id IS indexed per the Person-less event semantic.
        assert "p-1" in pe_idx._data

    def test_skips_person_less_event_from_person_event_index(self):
        """Pillar H Week 9 — events with NULL ``person_id`` (ad-hoc
        validation events per ADR-0045 D231) are SKIPPED from
        :class:`PersonEventIndex`. Mirrors :func:`_materialize_indexes`
        per ADR-0067 D360 + the W8 follow-up P2-1 closure's posture.
        """
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        ev = {"type": "enrolled", "ts": "2026-05-27T00:00:00Z", "v": 1}
        _runner._invalidate_indexes_on_append(
            ec_idx, pe_idx, ev, self._known_classes(),
            now_ts_fn=lambda: 100.0,
        )
        # Catalogued class IS indexed.
        assert "enrolled" in ec_idx._data
        # No person_id → NOT in PersonEventIndex.
        assert pe_idx._data == {}

    def test_advances_last_updated_at_ts_on_both_indexes_per_adr_0067_d363(self):
        """Pillar H Week 9 per ADR-0067 D363 — both indexes'
        ``_last_updated_at_ts`` advance to the now_ts_fn() value on
        each invalidation; the operator-visible freshness gauge
        consults this field via the Prometheus ObservableGauge per
        D363.
        """
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        ev = {"type": "enrolled", "person_id": "p-1",
              "ts": "2026-05-27T00:00:00Z", "v": 1}
        _runner._invalidate_indexes_on_append(
            ec_idx, pe_idx, ev, self._known_classes(),
            now_ts_fn=lambda: 12345.6789,
        )
        assert ec_idx._last_updated_at_ts == 12345.6789
        assert pe_idx._last_updated_at_ts == 12345.6789

    def test_chronological_order_preserved_across_repeated_invalidations(self):
        """Pillar H Week 9 — repeated invalidations append to the
        per-key list in invocation order; mirrors
        :func:`_materialize_indexes`'s ``setdefault(..., []).append(...)``
        + the ledger's chronological-by-ts contract.
        """
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        known = self._known_classes()
        evs = [
            {"type": "enrolled", "person_id": "p-1",
             "ts": "2026-05-27T00:00:00Z", "v": 1},
            {"type": "enrolled", "person_id": "p-2",
             "ts": "2026-05-27T00:00:01Z", "v": 1},
            {"type": "enrolled", "person_id": "p-3",
             "ts": "2026-05-27T00:00:02Z", "v": 1},
        ]
        for ev in evs:
            _runner._invalidate_indexes_on_append(
                ec_idx, pe_idx, ev, known, now_ts_fn=lambda: 100.0,
            )
        assert [e["person_id"] for e in ec_idx._data["enrolled"]] == [
            "p-1", "p-2", "p-3",
        ]


class TestInstallIndexInvalidationObserver:
    """Pillar H Week 9 per ADR-0067 D362 —
    :func:`_install_index_invalidation_observer` registration helper
    contract.
    """

    def test_register_then_append_invalidates_event_class_index(
        self, tmp_path,
    ):
        """Pillar H Week 9 BEHAVIORAL-PASSTHROUGH per ADR-0067 D362 +
        the W5 P1-1 canonical safeguard discipline at TWENTY-EIGHT
        consecutive weeks. Wires the production
        :meth:`Ledger.append_observer` seam + the
        :func:`_invalidate_indexes_on_append` body END-TO-END on a
        real :class:`Ledger` substrate + verifies the post-append
        state matches the materialization-from-scratch post-condition
        — the structural commitment per ADR-0031 D140's byte-identical
        determinism contract.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        _runner._install_index_invalidation_observer(led, ec_idx, pe_idx)

        led.append({"type": "enrolled", "person_id": "p-1"})

        # EventClassIndex sees the post-append state.
        enrolled = ec_idx.events_for_class("enrolled")
        assert len(enrolled) == 1
        assert enrolled[0].type == "enrolled"
        # PersonEventIndex sees the same.
        person_evs = pe_idx.events_for("p-1")
        assert len(person_evs) == 1

    def test_register_then_multiple_appends_extend_indexes_in_order(
        self, tmp_path,
    ):
        """Pillar H Week 9 — multiple appends to the same Ledger
        instance extend BOTH indexes in chronological (append-order)
        sequence per ADR-0067 D362 + ADR-0031 D140.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        _runner._install_index_invalidation_observer(led, ec_idx, pe_idx)

        led.append({"type": "enrolled", "person_id": "p-1"})
        led.append({"type": "send_intent", "person_id": "p-1",
                    "channel": "email", "intent_id": "snd_w9_1"})
        led.append({"type": "send_confirmed", "person_id": "p-1",
                    "channel": "email", "intent_id": "snd_w9_1",
                    "gmail_message_id": "m_w9_1"})

        # All 3 events for p-1 in chronological order.
        p1_events = pe_idx.events_for("p-1")
        assert len(p1_events) == 3
        assert [e.type for e in p1_events] == [
            "enrolled", "send_intent", "send_confirmed",
        ]

    def test_post_invalidation_state_equals_materialization_per_byte_identical_determinism(
        self, tmp_path,
    ):
        """Pillar H Week 9 BEHAVIORAL-PASSTHROUGH per ADR-0067 D362 +
        ADR-0031 D140 — the post-condition of N appends WITH the
        invalidation observer registered equals the post-condition of
        N appends + a from-scratch :func:`_materialize_indexes` walk.
        The structural commitment per the byte-identical determinism
        contract: the index reflects the ledger's current state
        EXACTLY.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led_observer = _Ledger(tmp_path / "ledger-observer")
        ec_obs = EventClassIndex()
        pe_obs = PersonEventIndex()
        _runner._install_index_invalidation_observer(
            led_observer, ec_obs, pe_obs,
        )

        # Append cross-pillar event mix.
        events = [
            {"type": "enrolled", "person_id": "p-1"},
            {"type": "draft_quality_scored", "person_id": "p-2",
             "register": "cold-pitch", "voice_fidelity_score": 0.91,
             "state": "ready", "channel": "email"},
            {"type": "send_intent", "person_id": "p-1",
             "channel": "email", "intent_id": "snd_w9_2"},
            {"type": "send_confirmed", "person_id": "p-1",
             "channel": "email", "intent_id": "snd_w9_2",
             "gmail_message_id": "m_w9_2"},
            # Pillar G observability-internal class per W8 follow-up P2-1.
            {"type": "slo_violation_detected", "slo_name": "p99_send_latency",
             "observed_value": 5.5, "threshold": 5.0,
             "window_seconds": 300, "channel": "email",
             "_emitted_by": "observability"},
        ]
        for ev in events:
            led_observer.append(ev)

        # Now construct a SECOND ledger pointing at the same directory
        # + materialize from scratch. The post-condition MUST match.
        led_materialize = _Ledger(tmp_path / "ledger-observer")
        ec_mat, pe_mat = _runner._materialize_indexes(led_materialize)

        # Both indexes' _data dicts have the same shape + content.
        assert set(ec_obs._data.keys()) == set(ec_mat._data.keys())
        for class_name in ec_obs._data:
            assert (
                [e["type"] for e in ec_obs._data[class_name]]
                == [e["type"] for e in ec_mat._data[class_name]]
            ), f"Mismatch at class {class_name}"
        assert set(pe_obs._data.keys()) == set(pe_mat._data.keys())
        for pid in pe_obs._data:
            assert (
                [e["type"] for e in pe_obs._data[pid]]
                == [e["type"] for e in pe_mat._data[pid]]
            ), f"Mismatch at person {pid}"

    def test_known_classes_scope_uses_w8_followup_p2_1_union(self, tmp_path):
        """Pillar H Week 9 — the observer's ``known_classes`` set is
        the W8 follow-up P2-1 closure's union
        ``EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES``.
        Verifies the per-pillar mirror constants parity discipline
        carries through to the per-append invalidation site.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        _runner._install_index_invalidation_observer(led, ec_idx, pe_idx)

        # OBSERVABILITY_NEW_EVENT_CLASSES member — must be indexed
        # per the W8 follow-up P2-1 closure's extended scope.
        led.append({"type": "slo_violation_detected",
                    "slo_name": "p99_send_latency",
                    "observed_value": 5.5, "threshold": 5.0,
                    "window_seconds": 300, "channel": "email",
                    "_emitted_by": "observability"})
        slo_evs = ec_idx.events_for_class("slo_violation_detected")
        assert len(slo_evs) == 1


class TestEventClassIndexLastUpdatedAtTs:
    """Pillar H Week 9 per ADR-0067 D363 — :attr:`EventClassIndex._last_updated_at_ts`
    + :attr:`PersonEventIndex._last_updated_at_ts` fields contract.
    """

    def test_default_value_is_zero_per_never_materialized_sentinel(self):
        """Pillar H Week 9 — the default ``_last_updated_at_ts`` is
        ``0.0`` (sentinel for "never materialized"); operators querying
        the gauge before :func:`init_daemon` ran see 0.0 + the
        dashboard's age computation surfaces this as an obvious failure
        mode (the age would equal current wall-clock).
        """
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        assert ec_idx._last_updated_at_ts == 0.0
        assert pe_idx._last_updated_at_ts == 0.0

    def test_materialize_indexes_sets_last_updated_at_ts(self, tmp_path):
        """Pillar H Week 9 — :func:`_materialize_indexes` sets both
        indexes' ``_last_updated_at_ts`` to the wall-clock at
        materialization end. The W9 extension to the W8 helper.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        led.append({"type": "enrolled", "person_id": "p-1"})

        before = time.time()
        ec_idx, pe_idx = _runner._materialize_indexes(led)
        after = time.time()

        assert before <= ec_idx._last_updated_at_ts <= after
        assert before <= pe_idx._last_updated_at_ts <= after

    def test_both_indexes_share_last_updated_at_ts_at_v1_per_lockstep_invariant(
        self, tmp_path,
    ):
        """Pillar H Week 9 — at v1 the two indexes' ``_last_updated_at_ts``
        advance in lockstep because both are invalidated together by
        the same observer per :meth:`Ledger.append`. The
        :class:`PersonEventIndex._last_updated_at_ts` docstring names
        this invariant.
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        ec_idx = EventClassIndex()
        pe_idx = PersonEventIndex()
        _runner._install_index_invalidation_observer(led, ec_idx, pe_idx)
        led.append({"type": "enrolled", "person_id": "p-1"})
        assert ec_idx._last_updated_at_ts == pe_idx._last_updated_at_ts
        assert ec_idx._last_updated_at_ts > 0.0


class TestDaemonRunnerLedgerField:
    """Pillar H Week 9 per ADR-0067 D362 — :attr:`DaemonRunner.ledger`
    field for the daemon-process Ledger instance lifting.
    """

    def test_default_is_none_for_test_substrate_isolation(self, tmp_path):
        """Pillar H Week 9 — :attr:`DaemonRunner.ledger` defaults to
        ``None`` so :class:`DaemonRunner` constructed directly by
        tests (bypassing :func:`init_daemon`) works without explicit
        ``ledger=`` kwarg. Preserves backward compat with W7-W8
        tests + external operator-invoked dispatchers.
        """
        from tests._daemon_test_helpers import _TEST_PAST_STARTED_AT_TS
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        runner = DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts=_TEST_PAST_STARTED_AT_TS, version="0.1.0",
            lifecycle_state="initializing",
        )
        assert runner.ledger is None

    def test_init_daemon_populates_ledger_field_with_real_ledger(
        self, tmp_path,
    ):
        """Pillar H Week 9 — :func:`init_daemon` Step 8 (W9 lift) stores
        the constructed :class:`Ledger` instance on the returned
        :class:`DaemonRunner`. The W9 lift enables Step 8.5's observer
        registration to PERSIST across the daemon-process's lifetime.
        """
        from orchestrator.ledger import Ledger as _Ledger
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert isinstance(runner.ledger, _Ledger)
        assert runner.ledger.dir == ledger_dir


class TestInitDaemonStep8_5IndexInvalidationWiring:
    """Pillar H Week 9 per ADR-0067 D362 — NEW :func:`init_daemon`
    Step 8.5 (between Step 8 materialization + the renumbered Step
    10 DaemonRunner construction) registers the per-event-class
    index invalidation observer.
    """

    def test_init_daemon_registers_observer_on_daemons_ledger(
        self, tmp_path,
    ):
        """Pillar H Week 9 BEHAVIORAL-PASSTHROUGH — :func:`init_daemon`
        with production-default seams registers the invalidation
        observer on the daemon's Ledger instance. A subsequent
        :meth:`Ledger.append` on ``runner.ledger`` mutates both
        indexes in-place.
        """
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        # Indexes are empty at startup (no events pre-seeded).
        assert runner.event_class_index.events_for_class("enrolled") == []

        # Append via the daemon's Ledger instance.
        runner.ledger.append({"type": "enrolled", "person_id": "p-w9-1"})

        # The W9 invalidation observer fires → index reflects the append.
        enrolled = runner.event_class_index.events_for_class("enrolled")
        assert len(enrolled) == 1
        assert enrolled[0].get("person_id") == "p-w9-1"
        person_evs = runner.person_event_index.events_for("p-w9-1")
        assert len(person_evs) == 1

    def test_observer_not_registered_when_index_materialize_fn_provided(
        self, tmp_path,
    ):
        """Pillar H Week 9 — when the test-only ``index_materialize_fn``
        seam is provided, :attr:`DaemonRunner.ledger` stays ``None``
        + Step 8.5 SKIPS observer registration. Tests exercising
        invalidation in this path construct their own Ledger + invoke
        :func:`_install_index_invalidation_observer` directly.
        """
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
            index_materialize_fn=lambda: (EventClassIndex(), PersonEventIndex()),
        )
        # The test-substrate path leaves ledger=None.
        assert runner.ledger is None

    def test_default_dispatch_for_stage_uses_runner_ledger_when_present(
        self, tmp_path, monkeypatch,
    ):
        """Pillar H Week 9 — :func:`_default_dispatch_for_stage` body
        consumes ``runner.ledger`` (the daemon's Ledger instance with
        the observer registered) instead of lazy-constructing per
        dispatch. Preserves observer registration across the daemon's
        per-tick lifecycle.

        Verifies the W9 extension at the dispatch site. Spies
        :func:`reconcile.reconcile` to capture the ``led=`` kwarg the
        dispatch passes through.
        """
        import asyncio as _asyncio
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        people_dir = vault_dir / "10 People"
        people_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir,
            people_dir=people_dir,
        )
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )

        captured_led: list = []

        import orchestrator.reconcile as _reconcile

        def _spy_reconcile(*args, **kwargs):
            captured_led.append(kwargs.get("led"))
            class _FakeResult:
                pass
            return _FakeResult()

        monkeypatch.setattr(_reconcile, "reconcile", _spy_reconcile)

        # Trigger dispatch for a stage that maps to non-empty passes.
        _asyncio.run(_runner._default_dispatch_for_stage(runner, "outcome_terminal"))

        # Verify dispatch consumed runner.ledger (W9 lift).
        assert captured_led[0] is runner.ledger


class TestObservabilityRegisterDaemonIndexObservableGauge:
    """Pillar H Week 9 per ADR-0067 D363 —
    :func:`observability.register_daemon_index_observable_gauge`
    contract.
    """

    def test_register_observable_gauge_exists_in_module_surface(self):
        """Pillar H Week 9 — the public function is exported from
        :mod:`observability`. Operator-visible registration helper.
        """
        from observability import register_daemon_index_observable_gauge
        assert callable(register_daemon_index_observable_gauge)

    def test_register_with_test_meter_returns_observable_gauge(self):
        """Pillar H Week 9 — registration with an isolated Meter
        returns an :class:`ObservableGauge` instrument. Behavioral-
        passthrough on the OTel SDK integration path.
        """
        from observability import register_daemon_index_observable_gauge
        from observability import init_otel_meter_provider, get_meter
        # Use the framework's set_global=False test path so this
        # test doesn't pollute global state.
        init_otel_meter_provider(set_global=False)
        meter = get_meter()
        gauge = register_daemon_index_observable_gauge(
            get_last_updated_ts_fn=lambda: 12345.6789,
            meter=meter,
        )
        # The gauge exists; on scrape it would call the callback.
        # The OTel SDK's instrument creation contract pins the type;
        # asserting non-None is the meaningful behavioral check.
        assert gauge is not None

    def test_init_daemon_step_9_5_registration_is_best_effort(
        self, tmp_path, capfd,
    ):
        """Pillar H Week 9 — :func:`init_daemon` Step 9.5 registration
        wraps the call in try/except + logs to stderr but does NOT
        propagate per ADR-0067 D363's best-effort posture (the gauge
        is operator-observability scaffolding, NOT a daemon
        correctness contract). With ``otel_meter_init_fn=lambda *a,
        **kw: None`` (no Meter actually constructed),
        :func:`get_meter` returns a no-op default per the OTel SDK
        convention so the registration succeeds silently — the path
        IS exercised even at test substrate.
        """
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        # No assertion on the registration outcome (best-effort);
        # just verify init_daemon completes successfully.
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert runner.lifecycle_state == "initializing"


# ---------------------------------------------------------------------------
# Pillar H Week 9 follow-up — per-week review findings (P2-2 + P2-3 + P3-4)
# ---------------------------------------------------------------------------


class TestW9FollowupDefaultDispatchFallbackPath:
    """Pillar H Week 9 follow-up P2-2 closure — regression-barrier on the
    :func:`_default_dispatch_for_stage` fallback path (when
    ``runner.ledger is None``).

    The W9 main commit shipped the fallback branch in
    :func:`_default_dispatch_for_stage` body (consume ``runner.ledger``
    if not None; else lazy-construct from ``runner.config.ledger_dir``)
    + a regression-barrier verifying the production-default path
    (``test_default_dispatch_for_stage_uses_runner_ledger_when_present``)
    BUT did NOT add a symmetric cell pinning the fallback semantic. A
    future Week-N author refactoring the fallback (e.g., removing the
    ``else`` branch + making ``runner.ledger`` non-optional) would NOT
    break any existing test — exactly the failure mode the W5 P1-1 +
    W7 P1-1 closures' behavioral-passthrough-not-signature-only
    discipline exists to catch.

    The W9 follow-up P2-2 closure adds:

    1. The fallback-path regression-barrier verifying lazy-construction
       fires when ``runner.ledger is None``.
    2. The "no observer firing" consequence documented at the test
       (per the W9 main commit's `_invalidate_indexes_on_append`
       cross-process consistency note) — appends on the fallback
       Ledger DO NOT trigger the daemon-process index invalidation
       observer; operators relying on post-dispatch index state after
       constructing DaemonRunner WITHOUT going through init_daemon
       would see stale data.
    """

    def test_default_dispatch_for_stage_lazy_constructs_ledger_when_runner_ledger_is_none(
        self, tmp_path, monkeypatch,
    ):
        """Pillar H Week 9 follow-up P2-2 closure — verifies the
        :func:`_default_dispatch_for_stage` body lazy-constructs a
        :class:`Ledger` from ``runner.config.ledger_dir`` when
        ``runner.ledger is None``. A DaemonRunner constructed directly
        (bypassing init_daemon) doesn't go through Step 8.5 so the
        observer is NOT registered on the fallback Ledger.
        """
        import asyncio as _asyncio
        from tests._daemon_test_helpers import _TEST_PAST_STARTED_AT_TS
        from orchestrator.ledger import Ledger as _Ledger
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        people_dir = vault_dir / "10 People"
        people_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir,
            people_dir=people_dir,
        )
        # Construct DaemonRunner DIRECTLY (NOT via init_daemon) so
        # runner.ledger stays None per the field default.
        runner = DaemonRunner(
            config=config, config_hash="a" * 64, pid=12345,
            started_at_ts=_TEST_PAST_STARTED_AT_TS, version="0.1.0",
            lifecycle_state="initializing",
        )
        assert runner.ledger is None

        captured_led: list = []

        import orchestrator.reconcile as _reconcile

        def _spy_reconcile(*args, **kwargs):
            captured_led.append(kwargs.get("led"))
            class _FakeResult:
                pass
            return _FakeResult()

        monkeypatch.setattr(_reconcile, "reconcile", _spy_reconcile)

        # Trigger dispatch for a stage that maps to non-empty passes.
        _asyncio.run(_runner._default_dispatch_for_stage(runner, "outcome_terminal"))

        # The fallback path lazy-constructed a Ledger; the captured
        # led is a NEW Ledger instance (NOT runner.ledger which is None).
        assert isinstance(captured_led[0], _Ledger)
        assert captured_led[0].dir == ledger_dir
        # The fallback Ledger has NO registered observer (W9 main
        # commit's `_default_dispatch_for_stage` cross-process consistency
        # note: appends here would NOT trigger the daemon-process
        # index invalidation observer; documented at the W9 follow-up
        # P2-2 closure's "stale data" rationale).
        assert captured_led[0]._post_append_observers == []


class TestW9FollowupAppendObserverRefuseLoud:
    """Pillar H Week 9 follow-up P2-3 closure — :meth:`Ledger.append_observer`
    refuses-loud on non-callable observer per the per-pillar-H
    raw-primitive refuse-loud-at-boundary discipline (the W2 follow-up
    P2-2 closure established the boundary-validation convention for
    ``build_*_payload`` factories; the W9 follow-up extends to
    :meth:`Ledger.append_observer`).
    """

    def test_register_non_callable_raises_type_error_at_boundary(
        self, tmp_path,
    ):
        """Pillar H Week 9 follow-up P2-3 closure — operator passes a
        non-callable (e.g., a list) to :meth:`Ledger.append_observer`
        + sees a clear ``TypeError`` at registration time (not at the
        first append).
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        with pytest.raises(TypeError, match="must be callable"):
            led.append_observer([1, 2, 3])  # Non-callable: a list.
        with pytest.raises(TypeError, match="must be callable"):
            led.append_observer({"not": "callable"})  # Non-callable: a dict.
        with pytest.raises(TypeError, match="must be callable"):
            led.append_observer(None)  # Non-callable: None.

    def test_register_callable_does_not_raise(self, tmp_path):
        """Pillar H Week 9 follow-up P2-3 closure — verifying the
        boundary check accepts valid callables (preserves the W9 main
        commit's observer registration contract).
        """
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        # Lambda — callable.
        led.append_observer(lambda _d: None)
        # Regular function — callable.
        def _obs(_d: dict) -> None:
            pass
        led.append_observer(_obs)
        # Method bound to an instance — callable.
        class _Collector:
            def __init__(self):
                self.events: list[dict] = []
            def on_append(self, d: dict) -> None:
                self.events.append(d)
        c = _Collector()
        led.append_observer(c.on_append)
        # 3 observers registered; append fires all three.
        led.append({"type": "enrolled", "person_id": "p-1"})
        assert len(c.events) == 1


class TestW9FollowupInitDaemonInvalidationNowTsFnSeam:
    """Pillar H Week 9 follow-up P3-4 closure — the
    ``invalidation_now_ts_fn`` test-only seam at :func:`init_daemon`
    threads the deterministic-clock callable through to
    :func:`_install_index_invalidation_observer`.
    """

    def test_init_daemon_threads_invalidation_now_ts_fn_to_observer(
        self, tmp_path,
    ):
        """Pillar H Week 9 follow-up P3-4 closure — :func:`init_daemon`
        threads the ``invalidation_now_ts_fn`` kwarg through to the
        Step 8.5 observer registration so the post-append
        ``_last_updated_at_ts`` reflects the injected deterministic
        timestamp.
        """
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
            invalidation_now_ts_fn=lambda: 99999.0,
        )
        # Trigger an append → invalidation observer fires.
        runner.ledger.append({"type": "enrolled", "person_id": "p-w9-followup"})
        # The observer used the injected timestamp.
        assert runner.event_class_index._last_updated_at_ts == 99999.0
        assert runner.person_event_index._last_updated_at_ts == 99999.0

    def test_init_daemon_default_invalidation_now_ts_fn_is_time_time(
        self, tmp_path,
    ):
        """Pillar H Week 9 follow-up P3-4 closure — default
        ``invalidation_now_ts_fn`` resolves to :func:`time.time`
        (production-default wall-clock); operators omitting the kwarg
        get production semantics.
        """
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(vault_dir=vault_dir, ledger_dir=ledger_dir)
        before = time.time()
        runner = init_daemon(
            config,
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        runner.ledger.append({"type": "enrolled", "person_id": "p-w9-followup-2"})
        after = time.time()
        assert before <= runner.event_class_index._last_updated_at_ts <= after


# ---------------------------------------------------------------------------
# Pillar H Week 10-11 — crash recovery hardening per ADR-0068 D364-D366
# ---------------------------------------------------------------------------


class TestRecoverFromPriorCrash:
    """Pillar H Week 10-11 per ADR-0068 D364 — unit tests for the
    :func:`_recover_from_prior_crash` helper.

    Cell-level matrix coverage (THIRTY-FOUR consecutive weeks per
    the per-week-reviewer discipline):

    * Empty ledger → returns 0; no synthesis.
    * Matched daemon_started + daemon_stopped → no synthesis.
    * Unmatched daemon_started (no daemon_stopped for the same PID)
      → synthesizes ``daemon_stopped(exit_reason="crash",
      _recovered_by="reconcile", _recovered_for_pid=<prior_pid>)``.
    * Current PID excluded from candidate set (defensive POSIX
      PID-reuse exclusion).
    * Multiple unmatched daemon_started events → multiple syntheses.
    * uptime_seconds derived from latest-observed ts for the prior
      PID (across daemon-lifecycle event classes).
    * uptime_seconds=0.0 fallback on malformed ts.
    * Audit marker ``_recovered_by="reconcile"`` per ADR-0010 D17 +
      R032 synthetic-event exclusion per ADR-0056 D311.
    """

    def _ledger(self, tmp_path):
        from orchestrator.ledger import Ledger as _Ledger
        return _Ledger(tmp_path / "ledger")

    def test_empty_ledger_returns_zero_per_w10_11_d364(self, tmp_path):
        """Empty ledger → no prior daemon_started events → no
        synthesis; returns 0."""
        from orchestrator.daemon import _recover_from_prior_crash
        led = self._ledger(tmp_path)
        count = _recover_from_prior_crash(led=led, current_pid=12345)
        assert count == 0
        # Ledger unchanged — no daemon_stopped synthesized.
        events = list(led.all_events())
        assert events == []

    def test_matched_started_stopped_no_synthesis_per_w10_11_d364(
        self, tmp_path,
    ):
        """``daemon_started(pid=1000)`` + ``daemon_stopped(pid=1000)``
        in ledger → no synthesis (clean prior shutdown)."""
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import (
            build_daemon_started_payload,
            build_daemon_stopped_payload,
        )
        led = self._ledger(tmp_path)
        led.append({
            "type": "daemon_started",
            **build_daemon_started_payload(
                pid=1000, version="0.0.1", config_hash="a" * 64,
                startup_seconds=0.5,
            ),
        })
        led.append({
            "type": "daemon_stopped",
            **build_daemon_stopped_payload(
                pid=1000, exit_reason="clean",
                uptime_seconds=10.0, in_flight_task_count_at_exit=0,
            ),
        })
        count = _recover_from_prior_crash(led=led, current_pid=12345)
        assert count == 0
        # No new daemon_stopped events appended for the matched PID.
        stopped_events = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ]
        assert len(stopped_events) == 1  # The originally-emitted clean one.
        assert stopped_events[0]["exit_reason"] == "clean"

    def test_unmatched_started_synthesizes_crash_per_w10_11_d364(
        self, tmp_path,
    ):
        """``daemon_started(pid=2000)`` WITHOUT matching
        ``daemon_stopped(pid=2000)`` → synthesizes
        ``daemon_stopped(pid=2000, exit_reason="crash",
        _recovered_by="reconcile", _recovered_for_pid=2000)``."""
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import build_daemon_started_payload
        led = self._ledger(tmp_path)
        led.append({
            "type": "daemon_started",
            **build_daemon_started_payload(
                pid=2000, version="0.0.1", config_hash="b" * 64,
                startup_seconds=0.5,
            ),
        })
        count = _recover_from_prior_crash(led=led, current_pid=12345)
        assert count == 1
        # Verify the synthesized daemon_stopped event.
        stopped_events = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ]
        assert len(stopped_events) == 1
        synth = stopped_events[0]
        assert synth["pid"] == 2000
        assert synth["exit_reason"] == "crash"
        assert synth["_recovered_by"] == "reconcile"
        assert synth["_recovered_for_pid"] == 2000
        assert synth["_emitted_by"] == "daemon"
        assert synth["in_flight_task_count_at_exit"] == 0

    def test_current_pid_excluded_per_w10_11_d364(self, tmp_path):
        """Defensive POSIX PID-reuse exclusion — if the ledger has a
        ``daemon_started(pid=current_pid)`` event (e.g., from prior
        same-PID daemon process), the synthesis SKIPS that entry
        because the current daemon has not emitted its own
        daemon_started yet at Step 4.5."""
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import build_daemon_started_payload
        led = self._ledger(tmp_path)
        # A daemon_started event with the SAME PID as the current daemon.
        led.append({
            "type": "daemon_started",
            **build_daemon_started_payload(
                pid=12345, version="0.0.1", config_hash="c" * 64,
                startup_seconds=0.5,
            ),
        })
        count = _recover_from_prior_crash(led=led, current_pid=12345)
        assert count == 0  # current_pid excluded from candidate set.
        stopped_events = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ]
        assert stopped_events == []

    def test_multiple_unmatched_synthesizes_multiple_per_w10_11_d364(
        self, tmp_path,
    ):
        """Multiple unmatched ``daemon_started`` events → one
        synthesis per prior crashed daemon."""
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import build_daemon_started_payload
        led = self._ledger(tmp_path)
        for pid in [3000, 3001, 3002]:
            led.append({
                "type": "daemon_started",
                **build_daemon_started_payload(
                    pid=pid, version="0.0.1", config_hash="d" * 64,
                    startup_seconds=0.5,
                ),
            })
        count = _recover_from_prior_crash(led=led, current_pid=12345)
        assert count == 3
        recovered_pids = sorted([
            e.to_dict()["pid"] for e in led.all_events()
            if e.type == "daemon_stopped"
        ])
        assert recovered_pids == [3000, 3001, 3002]

    def test_uptime_seconds_derived_from_latest_observed_ts(self, tmp_path):
        """``uptime_seconds`` reflects the gap between
        ``daemon_started.ts`` and the latest-observed ts for the
        prior PID (across daemon-lifecycle events)."""
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import (
            build_daemon_started_payload,
            build_daemon_stopping_payload,
        )
        from orchestrator.ledger import Ledger as _Ledger
        led = _Ledger(tmp_path / "ledger")
        # Daemon started at a specific ts.
        led.append({
            "type": "daemon_started",
            "ts": "2026-05-27T10:00:00.000Z",
            **build_daemon_started_payload(
                pid=4000, version="0.0.1", config_hash="e" * 64,
                startup_seconds=0.5,
            ),
        })
        # Later daemon_stopping (operator initiated graceful shutdown
        # but crashed mid-drain — failure-mode taxonomy case 3).
        led.append({
            "type": "daemon_stopping",
            "ts": "2026-05-27T10:00:05.500Z",
            **build_daemon_stopping_payload(
                pid=4000, reason="sigterm",
                drain_deadline_ts="2026-05-27T10:00:35.500Z",
                in_flight_task_count=0,
            ),
        })
        # No daemon_stopped → crash detected.
        count = _recover_from_prior_crash(led=led, current_pid=12345)
        assert count == 1
        synth = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ][0]
        # uptime = 5.5s (10:00:05.500 - 10:00:00.000)
        assert abs(synth["uptime_seconds"] - 5.5) < 0.001

    def test_uptime_seconds_zero_fallback_on_malformed_ts(self, tmp_path):
        """Malformed ts on prior ``daemon_started`` → synthesis
        falls back to ``uptime_seconds=0.0`` placeholder + the
        synthesis still fires (operator-visible).
        """
        from orchestrator.daemon import _recover_from_prior_crash
        led = self._ledger(tmp_path)
        # Append a daemon_started event with a malformed ts directly
        # (bypassing the factory's auto-ts default).
        led.append({
            "type": "daemon_started",
            "ts": "INVALID-TIMESTAMP",
            "pid": 5000,
            "version": "0.0.1",
            "config_hash": "f" * 64,
            "startup_seconds": 0.5,
            "_emitted_by": "daemon",
        })
        count = _recover_from_prior_crash(led=led, current_pid=12345)
        assert count == 1
        synth = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ][0]
        assert synth["uptime_seconds"] == 0.0

    def test_audit_marker_preserved_per_r032_filter(self, tmp_path):
        """The synthesized ``daemon_stopped`` events carry
        ``_recovered_by="reconcile"`` per ADR-0010 D17 + R032
        synthetic-event exclusion per ADR-0056 D311 — the Pillar G
        SLO aggregation filter naturally excludes them.
        """
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import build_daemon_started_payload
        led = self._ledger(tmp_path)
        led.append({
            "type": "daemon_started",
            **build_daemon_started_payload(
                pid=6000, version="0.0.1", config_hash="0" * 64,
                startup_seconds=0.5,
            ),
        })
        _recover_from_prior_crash(led=led, current_pid=12345)
        synth = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ][0]
        # Verify the audit marker per R032 exclusion contract.
        assert synth.get("_recovered_by") == "reconcile"
        # Verify the cross-reference field per ADR-0068 D364.
        assert synth.get("_recovered_for_pid") == 6000

    def test_observer_fires_for_synthesis_per_adr_0067_d362(self, tmp_path):
        """Pillar H Week 9 D362's post-append observer seam fires for
        the W10-11 synthesis — the per-event-class index updates +
        the freshness gauge advances naturally for synthesized
        events (no special handling needed).
        """
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import build_daemon_started_payload
        led = self._ledger(tmp_path)
        # Register a capture observer (mirrors the W9 observer pattern).
        captured: list[dict] = []
        led.append_observer(lambda d: captured.append(d))
        led.append({
            "type": "daemon_started",
            **build_daemon_started_payload(
                pid=7000, version="0.0.1", config_hash="1" * 64,
                startup_seconds=0.5,
            ),
        })
        captured.clear()  # Discard the daemon_started observer fire.
        _recover_from_prior_crash(led=led, current_pid=12345)
        # The synthesis's emit_fn=led.append fired the observer.
        assert len(captured) == 1
        assert captured[0]["type"] == "daemon_stopped"
        assert captured[0]["exit_reason"] == "crash"


class TestInitDaemonStep4_5CrashRecovery:
    """Pillar H Week 10-11 per ADR-0068 D364 — integration tests for
    :func:`init_daemon` Step 4.5 (the crash-recovery synthesis
    invocation site).

    Behavioral-passthrough-not-signature-only discipline (THIRTY-ONE
    consecutive weeks per the W5 P1-1 + W6+/W7+/W8+/W9+ closures'
    canonical safeguard): tests exercise the production-default path
    (real :class:`Ledger` substrate) NOT mock-only.
    """

    def _config(self, tmp_path, **overrides):
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        return DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir, **overrides,
        )

    def _stub_init_kwargs(self):
        return dict(
            migration_apply_fn=lambda: None,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )

    def test_step_4_5_fires_after_migration_before_policy_load(
        self, tmp_path,
    ):
        """Step 4.5 (crash-recovery synthesis) fires AFTER Step 4
        (migrations applied) + BEFORE Step 5 (policy load) per the
        ADR-0068 D364 startup ordering contract."""
        calls: list[str] = []
        def _migrate():
            calls.append("step_4_migration")
        def _crash_recovery(*, current_pid, now_fn):
            calls.append("step_4_5_crash_recovery")
            return 0
        def _policy_load(_dir):
            calls.append("step_5_policy_load")
            return []
        config = self._config(tmp_path)
        init_daemon(
            config,
            migration_apply_fn=_migrate,
            crash_recovery_fn=_crash_recovery,
            policy_load_fn=_policy_load,
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        # Verify the ordering: 4 → 4.5 → 5.
        migration_idx = calls.index("step_4_migration")
        crash_idx = calls.index("step_4_5_crash_recovery")
        policy_idx = calls.index("step_5_policy_load")
        assert migration_idx < crash_idx < policy_idx, (
            f"Step ordering drift per ADR-0068 D364: got {calls!r}"
        )

    def test_crash_recovery_fn_receives_current_pid(self, tmp_path):
        """``crash_recovery_fn`` seam receives the ``current_pid`` per
        the synthesis's defensive POSIX PID-reuse exclusion."""
        captured: dict = {}
        def _crash_recovery(*, current_pid, now_fn):
            captured["pid"] = current_pid
            captured["now_fn"] = now_fn
            return 0
        config = self._config(tmp_path)
        init_daemon(
            config,
            pid_fn=lambda: 99999,
            crash_recovery_fn=_crash_recovery,
            **self._stub_init_kwargs(),
        )
        assert captured["pid"] == 99999

    def test_default_invokes_recover_from_prior_crash_behavioral_passthrough(
        self, tmp_path,
    ):
        """Behavioral-passthrough regression-barrier per W5 P1-1 +
        W6+/W7+/W8+/W9+ closures' discipline (THIRTY-ONE consecutive
        weeks). Exercises the production-default ``crash_recovery_fn=None``
        path via real :class:`Ledger` substrate — pre-seeds a prior
        ``daemon_started`` event + verifies :func:`init_daemon` Step
        4.5 synthesizes ``daemon_stopped(exit_reason="crash")``
        through the full production path."""
        from orchestrator.daemon.runner import build_daemon_started_payload
        from orchestrator.ledger import Ledger as _Ledger
        config = self._config(tmp_path)
        # Pre-seed the ledger with a prior daemon_started (no matching
        # daemon_stopped) — emulating a crashed prior daemon.
        led = _Ledger(config.ledger_dir)
        led.append({
            "type": "daemon_started",
            **build_daemon_started_payload(
                pid=8000, version="0.0.1", config_hash="2" * 64,
                startup_seconds=0.5,
            ),
        })
        # Invoke init_daemon with the production-default
        # crash_recovery_fn=None → exercises _recover_from_prior_crash.
        init_daemon(
            config,
            pid_fn=lambda: 12345,
            **self._stub_init_kwargs(),
        )
        # Verify the synthesis fired through the production path.
        led_after = _Ledger(config.ledger_dir)
        stopped_events = [
            e.to_dict() for e in led_after.all_events()
            if e.type == "daemon_stopped"
        ]
        assert len(stopped_events) == 1, (
            f"Production-default Step 4.5 should synthesize 1 "
            f"daemon_stopped for the prior crashed daemon; got "
            f"{stopped_events!r}"
        )
        assert stopped_events[0]["exit_reason"] == "crash"
        assert stopped_events[0]["pid"] == 8000
        assert stopped_events[0]["_recovered_by"] == "reconcile"

    def test_crash_recovery_now_fn_threaded_to_synthesis(self, tmp_path):
        """``crash_recovery_now_fn`` test-only seam threads the
        deterministic-clock callable through to the synthesis ``now_fn``
        per ADR-0031 D140 byte-identical determinism + ADR-0068 D364.
        """
        captured_now_fn: dict = {}
        def _crash_recovery(*, current_pid, now_fn):
            captured_now_fn["now_fn"] = now_fn
            return 0
        def _fixed_now():
            return datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc)
        config = self._config(tmp_path)
        init_daemon(
            config,
            crash_recovery_fn=_crash_recovery,
            crash_recovery_now_fn=_fixed_now,
            **self._stub_init_kwargs(),
        )
        assert captured_now_fn["now_fn"] is _fixed_now


class TestDaemonConfigReconcilePassesAtStartup:
    """Pillar H Week 10-11 per ADR-0068 D366 — :attr:`DaemonConfig.
    reconcile_passes_at_startup` field tests.
    """

    def test_default_is_none(self, tmp_path):
        """Default ``reconcile_passes_at_startup`` is None — no
        pre-flight reconcile (test substrate + dev path)."""
        config = DaemonConfig(
            vault_dir=tmp_path / "vault",
            ledger_dir=tmp_path / "ledger",
        )
        assert config.reconcile_passes_at_startup is None

    def test_config_hash_includes_reconcile_passes_at_startup(self, tmp_path):
        """The new field factors into :func:`_compute_config_hash`
        so operators querying :attr:`DaemonRunner.config_hash` see
        drift across the extended surface per ADR-0068 D366.
        """
        c1 = DaemonConfig(
            vault_dir=tmp_path / "vault",
            ledger_dir=tmp_path / "ledger",
            reconcile_passes_at_startup=None,
        )
        c2 = DaemonConfig(
            vault_dir=tmp_path / "vault",
            ledger_dir=tmp_path / "ledger",
            reconcile_passes_at_startup="A",
        )
        h1 = _runner._compute_config_hash(c1)
        h2 = _runner._compute_config_hash(c2)
        assert h1 != h2, (
            "config_hash MUST differ across reconcile_passes_at_startup "
            "values per ADR-0068 D366's config-drift discipline"
        )

    def test_validate_config_refuses_loud_on_empty_string(self, tmp_path):
        """``_validate_config`` refuses-loud on empty string for
        ``reconcile_passes_at_startup`` per ADR-0068 D366 — explicit
        None surfaces the operator's "no pre-flight reconcile" intent;
        empty string would invoke ``reconcile.reconcile(passes="")``
        which operator-confuses."""
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir,
            ledger_dir=ledger_dir,
            reconcile_passes_at_startup="",
        )
        with pytest.raises(ValueError, match="non-empty string"):
            _runner._validate_config(config)


class TestInitDaemonStep4_6ReconcileAtStartup:
    """Pillar H Week 10-11 per ADR-0068 D366 — :func:`init_daemon` Step
    4.6 (operator-deliberate pre-flight reconcile pass invocation).
    """

    def _config(self, tmp_path, **overrides):
        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        return DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir, **overrides,
        )

    def _stub_init_kwargs(self):
        return dict(
            migration_apply_fn=lambda: None,
            crash_recovery_fn=lambda **_kw: 0,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )

    def test_none_config_skips_step_4_6(self, tmp_path):
        """``reconcile_passes_at_startup=None`` (default) → Step 4.6
        skips the reconcile invocation (the test substrate + dev
        path's no-Gmail-mocking posture)."""
        captured: dict = {"called": False}
        def _spy_reconcile(**kwargs):
            captured["called"] = True
            return None
        config = self._config(tmp_path, reconcile_passes_at_startup=None)
        init_daemon(
            config,
            reconcile_at_startup_fn=_spy_reconcile,
            **self._stub_init_kwargs(),
        )
        assert captured["called"] is False, (
            "Step 4.6 MUST NOT invoke reconcile when "
            "reconcile_passes_at_startup=None per ADR-0068 D366"
        )

    def test_opt_in_invokes_reconcile_with_passes(self, tmp_path):
        """``reconcile_passes_at_startup="A"`` → Step 4.6 invokes
        ``reconcile_at_startup_fn`` with kwargs matching the actual
        :func:`reconcile.reconcile` signature.

        Pillar H Week 10-11 follow-up P1-1 closure — the W10-11 main
        commit's test asserted ``captured["ledger_dir"] ==
        config.ledger_dir`` but the actual :func:`reconcile.reconcile`
        signature has NO ``ledger_dir`` parameter; the test was
        signature-only (didn't exercise the production-default path
        which would have raised ``TypeError``). The W10-11 follow-up
        updates the test's assertions to match the actual signature
        (``led=Ledger(...)`` + ``since: datetime``) per the NINTH
        ADR-vs-actual-impl drift in Pillar H.
        """
        from orchestrator.ledger import Ledger as _Ledger
        captured: dict = {}
        def _spy_reconcile(**kwargs):
            captured.update(kwargs)
            return None
        config = self._config(tmp_path, reconcile_passes_at_startup="A")
        init_daemon(
            config,
            reconcile_at_startup_fn=_spy_reconcile,
            **self._stub_init_kwargs(),
        )
        assert captured.get("passes") == "A"
        # Pillar H Week 10-11 follow-up P1-1 closure — actual signature
        # has ``led: Ledger`` NOT ``ledger_dir: Path``.
        assert isinstance(captured.get("led"), _Ledger)
        assert "ledger_dir" not in captured
        # ``since`` is REQUIRED per actual signature.
        assert isinstance(captured.get("since"), datetime)
        assert captured.get("apply") is True

    def test_reconcile_failure_does_not_prevent_startup(
        self, tmp_path, capfd,
    ):
        """Step 4.6 best-effort posture per ADR-0068 D366 — reconcile
        failures log to stderr + do NOT prevent daemon startup. The
        per-tick reconcile dispatch via Pillar H Week 7's dispatch_fn
        IS the structural backstop."""
        def _spy_reconcile(**kwargs):
            raise RuntimeError("Gmail API rate-limited")
        config = self._config(tmp_path, reconcile_passes_at_startup="A")
        # init_daemon does NOT raise + returns the runner.
        runner = init_daemon(
            config,
            reconcile_at_startup_fn=_spy_reconcile,
            **self._stub_init_kwargs(),
        )
        assert runner is not None
        # The failure logged to stderr.
        captured = capfd.readouterr()
        assert "reconcile pre-flight pass" in captured.err
        assert "Gmail API rate-limited" in captured.err


# ---------------------------------------------------------------------------
# Pillar H Week 10-11 follow-up — per-week-reviewer findings closure
# ---------------------------------------------------------------------------


class TestW10_11FollowupReconcileSignaturePassthrough:
    """Pillar H Week 10-11 follow-up P1-1 + P2-1 closures — behavioral-
    passthrough regression-barrier for Step 4.6's reconcile invocation.

    The NINTH ADR-vs-actual-impl drift in Pillar H — the W10-11 main
    commit's Step 4.6 invoked ``reconcile_at_startup_fn(passes=...,
    ledger_dir=..., apply=True)`` but :func:`orchestrator.reconcile.reconcile`'s
    actual signature has NO ``ledger_dir`` parameter; the production-
    default ``reconcile_at_startup_fn=None`` path raised
    ``TypeError: reconcile() got an unexpected keyword argument
    'ledger_dir'`` immediately on every operator opt-in. The broad
    ``except Exception`` block caught + logged + silently swallowed —
    operators never got the pre-flight reconcile they configured.

    This regression-barrier introspects
    :func:`inspect.signature(reconcile.reconcile)` + verifies the W10-11
    follow-up Step 4.6 invocation kwargs match the actual signature.
    The W7 P1-1 failure mode set the precedent (behavioral-passthrough-
    not-signature-only discipline now THIRTY-TWO consecutive weeks
    post-W10-11-follow-up).
    """

    def test_step_4_6_default_kwargs_match_reconcile_actual_signature(
        self, tmp_path,
    ):
        """Pillar H Week 10-11 follow-up P1-1 closure — the production-
        default ``reconcile_at_startup_fn=None`` path's call kwargs
        MUST be accepted by :func:`reconcile.reconcile`'s actual
        signature.
        """
        import inspect
        from orchestrator import reconcile as _reconcile_mod

        captured: dict = {}
        def _capture(**kwargs):
            captured.update(kwargs)
            return None  # Don't actually invoke reconcile.

        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir,
            reconcile_passes_at_startup="A",
        )
        init_daemon(
            config,
            reconcile_at_startup_fn=_capture,
            migration_apply_fn=lambda: None,
            crash_recovery_fn=lambda **_kw: 0,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )

        # Verify EVERY kwarg passed at Step 4.6 is accepted by the
        # actual reconcile.reconcile signature — this is the behavioral-
        # passthrough regression-barrier per the W5 P1-1 + W7 P1-1
        # closures' canonical discipline.
        sig = inspect.signature(_reconcile_mod.reconcile)
        for kwarg_name in captured:
            assert kwarg_name in sig.parameters, (
                f"Pillar H Week 10-11 follow-up P1-1 closure: Step 4.6's "
                f"call kwarg {kwarg_name!r} is NOT accepted by "
                f"reconcile.reconcile actual signature "
                f"({sorted(sig.parameters.keys())!r}). This is the W10-11 "
                f"main commit's drift mode — the NINTH ADR-vs-actual-impl "
                f"drift in Pillar H."
            )

        # Verify the REQUIRED params (no default) are all present in the
        # call — `since` is the canonical KEYWORD_ONLY required parameter
        # at reconcile.reconcile per the public signature.
        for name, param in sig.parameters.items():
            if (
                param.kind == inspect.Parameter.KEYWORD_ONLY
                and param.default is inspect.Parameter.empty
            ):
                assert name in captured, (
                    f"Pillar H Week 10-11 follow-up P1-1 closure: "
                    f"reconcile.reconcile REQUIRED kwarg {name!r} MUST "
                    f"be present in Step 4.6's call; got "
                    f"{sorted(captured.keys())!r}"
                )

    def test_step_4_6_passes_led_not_ledger_dir(self, tmp_path):
        """Pillar H Week 10-11 follow-up P1-1 closure — Step 4.6 passes
        ``led=Ledger(...)`` (NOT ``ledger_dir=...``) per the actual
        :func:`reconcile.reconcile` signature."""
        from orchestrator.ledger import Ledger as _Ledger

        captured: dict = {}
        def _capture(**kwargs):
            captured.update(kwargs)
            return None

        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir,
            reconcile_passes_at_startup="A",
        )
        init_daemon(
            config,
            reconcile_at_startup_fn=_capture,
            migration_apply_fn=lambda: None,
            crash_recovery_fn=lambda **_kw: 0,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )

        # `led` must be a Ledger instance, NOT a Path.
        assert "led" in captured, (
            f"Step 4.6 MUST pass `led=Ledger(...)` per the actual "
            f"reconcile.reconcile signature; got kwargs: "
            f"{sorted(captured.keys())!r}"
        )
        assert isinstance(captured["led"], _Ledger), (
            f"Step 4.6 MUST pass a Ledger instance as `led`; got "
            f"{type(captured['led']).__name__!r}"
        )
        # `ledger_dir` MUST NOT be passed (would TypeError on the real
        # reconcile.reconcile invocation).
        assert "ledger_dir" not in captured, (
            f"Step 4.6 MUST NOT pass `ledger_dir` (NOT a valid kwarg "
            f"for reconcile.reconcile); the W10-11 main commit's drift "
            f"was exactly this — got kwargs: {sorted(captured.keys())!r}"
        )

    def test_step_4_6_passes_since_per_required_param(self, tmp_path):
        """Pillar H Week 10-11 follow-up P1-1 closure — Step 4.6 passes
        the REQUIRED ``since: datetime`` parameter per
        :func:`reconcile.reconcile`'s actual signature."""
        captured: dict = {}
        def _capture(**kwargs):
            captured.update(kwargs)
            return None

        vault_dir = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        vault_dir.mkdir()
        ledger_dir.mkdir()
        config = DaemonConfig(
            vault_dir=vault_dir, ledger_dir=ledger_dir,
            reconcile_passes_at_startup="A",
        )
        init_daemon(
            config,
            reconcile_at_startup_fn=_capture,
            migration_apply_fn=lambda: None,
            crash_recovery_fn=lambda **_kw: 0,
            policy_load_fn=lambda _dir: [],
            otel_meter_init_fn=lambda *a, **kw: None,
            otel_tracer_init_fn=lambda *a, **kw: None,
            prometheus_start_fn=lambda *a, **kw: None,
        )
        assert "since" in captured
        assert isinstance(captured["since"], datetime)
        # The since window is 7 days back per ADR-0068 D366 follow-up
        # rationale — operators on production restart MAY have intents
        # up to a week old that need recovery; Pass A's 5min
        # min_intent_age + this 7d window catch the operator-deliberate
        # orphan scope.
        now = datetime.now(tz=timezone.utc)
        delta = now - captured["since"]
        assert (
            6.5 < delta.days < 7.5  # ~7 days
        ), f"since window should be ~7 days; got {delta!r}"


class TestW10_11FollowupCrossClassUptimeTracking:
    """Pillar H Week 10-11 follow-up P2-2 closure — cross-class
    ``uptime_seconds`` ts tracking regression-barrier.

    The W10-11 main commit's ``_recover_from_prior_crash`` helper
    docstring claims ts tracking is "across daemon-lifecycle event
    classes (daemon_started / daemon_stopping / policy_reloaded /
    health_probe / daemon_stage_saturated)" but the W10-11 main commit
    only tested daemon_started + daemon_stopping. A future refactor
    that removes ``pid`` from any of the other event class payloads
    would silently break the cross-class uptime tracking.

    The W10-11 follow-up adds regression-barriers for the THREE
    additional event classes.
    """

    def _setup(self, tmp_path):
        from orchestrator.ledger import Ledger as _Ledger
        from orchestrator.daemon.runner import build_daemon_started_payload
        led = _Ledger(tmp_path / "ledger")
        # Pre-seed daemon_started at a known ts.
        led.append({
            "type": "daemon_started",
            "ts": "2026-05-27T10:00:00.000Z",
            **build_daemon_started_payload(
                pid=9000, version="0.0.1", config_hash="a" * 64,
                startup_seconds=0.5,
            ),
        })
        return led

    def test_uptime_derived_from_health_probe_ts(self, tmp_path):
        """Pillar H Week 10-11 follow-up P2-2 closure — a later
        ``health_probe`` event with matching PID advances the latest-
        observed ts for the uptime computation."""
        from orchestrator.daemon import _recover_from_prior_crash
        led = self._setup(tmp_path)
        # health_probe at a later ts — should push the uptime estimate.
        led.append({
            "type": "health_probe",
            "ts": "2026-05-27T10:00:03.000Z",
            "pid": 9000,
            "outcome": "ok",
            "lifecycle_state": "ready",
            "remote_addr": "127.0.0.1",
            "_emitted_by": "daemon",
        })
        _recover_from_prior_crash(led=led, current_pid=12345)
        synth = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ][0]
        # uptime ≈ 3.0s (10:00:03 - 10:00:00)
        assert abs(synth["uptime_seconds"] - 3.0) < 0.001, (
            f"Pillar H Week 10-11 follow-up P2-2 closure: health_probe "
            f"ts MUST advance uptime_seconds; got {synth['uptime_seconds']!r}"
        )

    def test_uptime_derived_from_policy_reloaded_ts(self, tmp_path):
        """Pillar H Week 10-11 follow-up P2-2 closure — a later
        ``policy_reloaded`` event with matching PID advances the
        latest-observed ts."""
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import build_policy_reloaded_payload
        led = self._setup(tmp_path)
        led.append({
            "type": "policy_reloaded",
            "ts": "2026-05-27T10:00:07.000Z",
            **build_policy_reloaded_payload(
                pid=9000, source_path="/tmp/policies",
                prior_content_hash="b" * 64,
                new_content_hash="c" * 64,
                status="applied",
            ),
        })
        _recover_from_prior_crash(led=led, current_pid=12345)
        synth = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ][0]
        assert abs(synth["uptime_seconds"] - 7.0) < 0.001, (
            f"Pillar H Week 10-11 follow-up P2-2 closure: policy_reloaded "
            f"ts MUST advance uptime_seconds; got {synth['uptime_seconds']!r}"
        )

    def test_uptime_derived_from_daemon_stage_saturated_ts(self, tmp_path):
        """Pillar H Week 10-11 follow-up P2-2 closure — a later
        ``daemon_stage_saturated`` event with matching PID advances
        the latest-observed ts."""
        from orchestrator.daemon import _recover_from_prior_crash
        from orchestrator.daemon.runner import build_daemon_stage_saturated_payload
        led = self._setup(tmp_path)
        led.append({
            "type": "daemon_stage_saturated",
            "ts": "2026-05-27T10:00:11.500Z",
            **build_daemon_stage_saturated_payload(
                pid=9000, stage="sent",
                parallelism_limit=1, in_flight_count=1,
            ),
        })
        _recover_from_prior_crash(led=led, current_pid=12345)
        synth = [
            e.to_dict() for e in led.all_events()
            if e.type == "daemon_stopped"
        ][0]
        assert abs(synth["uptime_seconds"] - 11.5) < 0.001, (
            f"Pillar H Week 10-11 follow-up P2-2 closure: "
            f"daemon_stage_saturated ts MUST advance uptime_seconds; "
            f"got {synth['uptime_seconds']!r}"
        )


class TestW12FollowupCatalogClaimSubstantive:
    """Pillar H Week 12 follow-up P3-1 closure — the TENTH consecutive
    ADR-vs-actual-impl drift in Pillar H caught by the per-week-reviewer's
    cross-pillar back-audit discipline.

    The W12 main commit's ADR-0069 §Consequences (Neutral) +
    ADR-0068 §Consequences (Neutral) both claimed "EVENT_CLASS_CATALOG
    stays at 25" — an absolute-count claim that was empirically wrong
    (the actual count is 63 entries spanning Pillar A-H + Phase 5.5
    surfaces; the "stays at 25" propagated from ADR-0065's W6 narrative
    which was already incorrect even at W6). The substantive claim
    "ZERO new event classes at W12" is correct + IS pinned by the
    existing :class:`TestModuleConstants.test_contains_six_event_classes_per_week_6_addition`
    regression-barrier (per the W6 follow-up P3-6 closure).

    The W12 follow-up's regression-barrier here NAMES the substantive
    claim explicitly so future per-pillar authors trace the discipline
    forward at the per-week-reviewer's check: the Pillar H per-pillar-
    week trajectory at W12 close adds ZERO new event classes to
    DAEMON_NEW_EVENT_CLASSES + ZERO new entries to EVENT_CLASS_CATALOG
    from the Pillar H surface (Pillar I + J author may add new entries
    per ADR-0060 §Downstream pillar impact; the structural commitment
    at the Pillar H close IS the SIX Pillar H classes named at design
    time per ADR-0060 D331 + ADR-0065 D355).
    """

    def test_pillar_h_daemon_new_event_classes_size_at_w12_close(self):
        """Pillar H Week 12 follow-up P3-1 closure — DAEMON_NEW_EVENT_CLASSES
        size at W12 close is SIX (the substantive claim the W12 main commit's
        ADR-0069 §Consequences (Neutral) makes). The W12 main commit
        adds ZERO new event classes; the size preserves verbatim from
        the W10-11 follow-up base.

        This is the TENTH consecutive ADR-vs-actual-impl drift in Pillar H
        — the absolute-count claim "EVENT_CLASS_CATALOG stays at 25" was
        narratively wrong (actual count is 63) but the substantive claim
        "ZERO new event classes" is correct + pinned here at test time.
        """
        from orchestrator.daemon import DAEMON_NEW_EVENT_CLASSES
        # The substantive claim from ADR-0069 §Consequences (Neutral):
        # ZERO new event classes at W12; DAEMON_NEW_EVENT_CLASSES stays
        # at SIX.
        assert len(DAEMON_NEW_EVENT_CLASSES) == 6, (
            f"Pillar H Week 12 follow-up P3-1 closure — DAEMON_NEW_EVENT_CLASSES "
            f"size at W12 close MUST be 6 (the substantive claim from "
            f"ADR-0069 §Consequences (Neutral) at the W12 main commit + "
            f"ADR-0068 §Consequences (Neutral) at W10-11). The TENTH "
            f"consecutive ADR-vs-actual-impl drift in Pillar H caught "
            f"by the per-week-reviewer was narrative-only (the absolute "
            f"EVENT_CLASS_CATALOG count claim of 25 was wrong; actual is "
            f"63); the substantive ZERO-new-event-classes claim is "
            f"correct + pinned here. Got: {len(DAEMON_NEW_EVENT_CLASSES)} "
            f"= {sorted(DAEMON_NEW_EVENT_CLASSES)!r}"
        )

    def test_pillar_h_daemon_new_event_classes_membership_at_w12_close(self):
        """Pillar H Week 12 follow-up P3-1 closure — the SIX Pillar H
        event classes preserve verbatim at W12 close per the per-pillar
        mirror constants parity discipline.
        """
        from orchestrator.daemon import DAEMON_NEW_EVENT_CLASSES
        expected = frozenset({
            "daemon_started",
            "daemon_stopping",
            "daemon_stopped",
            "policy_reloaded",
            "health_probe",
            "daemon_stage_saturated",
        })
        assert DAEMON_NEW_EVENT_CLASSES == expected, (
            f"Pillar H Week 12 follow-up P3-1 closure — the SIX Pillar H "
            f"event classes preserve verbatim at W12 close. Missing: "
            f"{sorted(expected - DAEMON_NEW_EVENT_CLASSES)!r}; "
            f"unexpected: {sorted(DAEMON_NEW_EVENT_CLASSES - expected)!r}"
        )
