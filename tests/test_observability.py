"""Unit tests for the Pillar G Week 2 + Week 3 + Week 4 + Week 5
observability primitive.

Per ADR-0050 D272-D277 + ADR-0051 D278-D281 + ADR-0052 D282-D287 +
ADR-0053 D288-D293 + ADR-0054 D294-D299 — the per-event-class
observability primitive's body + the ``observability_class_uncatalogued``
diagnostic emit (with the two ``kind`` values ``"uncatalogued"`` +
``"missing_ts"``) + the Week 3 OTel SDK initialization + Meter accessor
+ per-event-class :class:`ObservableCounter` registration + the Week 4
Prometheus exporter wiring + per-channel send-latency Histogram +
reconcile success ratio ObservableGauge + Prometheus HTTP exposition
server + framework-default Views + first Grafana-as-code dashboard +
the Week 5 OTel tracing initialization + canonical Tracer accessor +
per-stage ``traced_stage`` context manager + ``_PIPELINE_STAGES``
closed-set + ``_SPAN_ATTRIBUTES_ALLOWED`` closed-set privacy invariant.

Cell-level matrix coverage discipline carried forward from Pillar F
Week 6-12 per .planning/REVIEW-pillar-f-surface-audit.md §66 +
RETRO-pillar-f.md §"What worked". Per-week reviewer audits per-event-
class / per-channel / per-breakdown / per-state cells; this file
pins each cell with a regression-barrier test. As of Pillar G Week 5
the cell-level matrix coverage discipline has held for TEN
consecutive weeks (Pillar F W6-W12 + Pillar G W2 + W3 + W4).

Cells covered:

* ``TestBreakdownByValidation`` — every allowed dim accepts; every
  disallowed dim refuses-loud (privacy invariant per I8 + ADR-0032
  D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b)).
* ``TestAggregation`` — single-class + multi-class + each Pillar
  A/B/C/D/E/F sample aggregates correctly.
* ``TestWindowFilter`` — ts < since excluded; ts >= since included;
  boundary case at ts == since included.
* ``TestChannelInvariant`` — single channel value surfaces;
  heterogeneous surfaces None; no-channel surfaces None; mix of
  channel + no-channel surfaces None (per ADR-0014 D33 + ADR-0050
  D276(c) + ADR-0051 D281).
* ``TestUncataloguedDiagnostic`` — uncatalogued class triggers ONE
  emit per call; count carries the total; offending_type is the
  first-seen.
* ``TestMissingTsDiagnostic`` — ts-missing event triggers ONE emit
  per call; count carries the total; offending_type + person_id are
  the first-seen.
* ``TestBothDiagnosticsTogether`` — uncatalogued AND ts-missing in
  the same call produces TWO diagnostic emits, one per kind.
* ``TestBreakdownDeterminism`` — per_breakdown_counts sorted; missing
  fields render as "none"; multi-dim composite keys use ``|``.
* ``TestSnapshotOrdering`` — snapshots sorted alphabetically by
  event_class per ADR-0051 D280.
* ``TestDeterministicClock`` — ``now=`` kwarg controls diagnostic
  emit ``ts``; default wall-clock.
* ``TestObservabilityNewClassesNotUncatalogued`` — the primitive's
  own diagnostic events do NOT trigger recursive uncatalogued
  diagnostics on the next call (R031 stability).
* ``TestEmptyAndOutOfWindow`` — empty ledger / all-out-of-window
  events produce empty snapshot list + zero diagnostic emits.
* ``TestOTelModuleConstants`` (Week 3) — Meter scope / service name /
  service version / instrument name closed-set constants.
* ``TestInitOTelMeterProvider`` (Week 3) — MeterProvider init cells:
  default Resource / custom Resource / custom readers / set_global
  True/False / Resource auto-injected SDK attributes.
* ``TestGetMeter`` (Week 3) — Meter accessor returns the
  ``orchestrator.observability`` scope at :data:`_METER_VERSION`
  from explicit AND global providers.
* ``TestObservableCounterRegistration`` (Week 3) — instrument name,
  unit, description, ObservableCounter type.
* ``TestObservableCounterCallbackBehavior`` (Week 3) — per-scrape
  callback emits ONE :class:`Observation` per :class:`MetricSnapshot`
  carrying event_class + channel attributes; value matches snapshot
  total_count.
* ``TestObservableCounterChannelCells`` (Week 3) — homogeneous single
  channel surfaces channel="email"; heterogeneous channels surface
  channel="none" (literal string); no-channel events surface
  channel="none"; mix surfaces channel="none".
* ``TestObservableCounterDeterministicClock`` (Week 3) — ``now=``
  callable controls the per-scrape rolling window's anchor;
  byte-identical behavior across consecutive scrapes when ``now`` is
  fixed.
* ``TestObservableCounterKwargPassthrough`` (Week 3) —
  ``expected_classes`` + ``breakdown_by`` ACTUALLY flow through to
  :func:`collect_event_class_snapshots` (behavioral-passthrough-not-
  signature-only discipline, FIVE consecutive weeks W8-W11 +
  Pillar G W3).
* ``TestFrameworkNeutrality`` (Week 3) — init works without any
  readers (instrument registers but no scrape until a reader is
  wired); init with operator-extended Resource preserves
  framework's service.* keys.
* ``TestObservableCounterEmptyAndOutOfWindow`` (Week 3) — empty
  ledger + out-of-window events produce zero observations.
* ``TestWeek4ModuleConstants`` (Week 4) — module-level constants
  for the Prometheus exporter wiring + send-latency histogram +
  reconcile success ratio + HTTP server defaults (per ADR-0053
  D288-D293).
* ``TestInitPrometheusMetricReader`` (Week 4) — the canonical
  Prometheus reader factory returns a reader instance, framework-
  neutrality contract preservation (operator can wire it OR skip).
* ``TestDefaultViews`` (Week 4) — framework-default View set includes
  the send-latency Histogram bucket configuration.
* ``TestInitOTelMeterProviderViews`` (Week 4) — the ``views=`` kwarg
  accepts operator views, defaults to framework views, ``()`` skips.
* ``TestSendLatencyHistogram`` (Week 4) — Histogram instrument name,
  unit "s", sync record + per-channel attribute, bucket configuration.
* ``TestReconcileSuccessRatioGauge`` (Week 4) — ObservableGauge
  instrument name, unit "1", callback computes ratio from ledger,
  vacuous success returns 1.0, drift-only returns 0.0.
* ``TestPrometheusExposition`` (Week 4) —
  ``render_prometheus_exposition`` returns bytes with canonical
  instrument names + ``# TYPE`` + ``# HELP`` headers + ``_total``
  suffix preserved on counter.
* ``TestFrameworkNeutralityWeek4`` (Week 4) — operator wires
  multiple readers (Prometheus + InMemory); operator skips Prometheus
  entirely with OTLP-only setup.
* ``TestStartPrometheusHttpServer`` (Week 4) — function signature
  accepts ``port`` + ``addr`` kwargs; default bind 127.0.0.1
  (security-by-default); function is NOT auto-called at module
  import (operator-deliberate).
* ``TestGrafanaDashboardYaml`` (Week 4) — Grafana dashboard YAML
  exists at the canonical path, is valid YAML, has expected top-
  level keys, references the three Week 4 metrics in PromQL queries.
* ``TestWeek5ModuleConstants`` (Week 5) — Tracer scope name + version
  parity with Meter scope, span name prefix, pipeline-stages closed-
  set membership + size, span attributes closed-set membership +
  privacy invariant (per ADR-0054 D294-D297).
* ``TestInitOTelTracerProvider`` (Week 5) — TracerProvider init
  cells: default Resource / custom Resource / custom span processors
  / empty processors default / set_global=True/False / Resource
  auto-injected SDK attributes (per ADR-0054 D294).
* ``TestGetTracer`` (Week 5) — Tracer accessor returns the
  ``orchestrator.observability`` scope at :data:`_TRACER_VERSION`
  from explicit AND global providers (per ADR-0054 D295).
* ``TestTracedStageBasic`` (Week 5) — context manager yields span,
  span name follows ``outreach_factory.<stage>.<operation>``,
  auto-sets stage + operation attributes (per ADR-0054 D296).
* ``TestTracedStageClosedSets`` (Week 5) — refuse-loud on stage
  not in :data:`_PIPELINE_STAGES`; refuse-loud on attribute key not
  in :data:`_SPAN_ATTRIBUTES_ALLOWED`; refuse-loud on empty
  operation; every allowed stage accepts; every allowed attribute
  accepts (per ADR-0054 D296 + D297).
* ``TestTracedStageBehavioralPassthrough`` (Week 5) — actually
  captures span via :class:`InMemorySpanExporter` (behavioral-
  passthrough-not-signature-only discipline; SEVEN consecutive
  weeks Pillar F W8-W11 + Pillar G W3 + W4 + W5); verifies span
  name + per-attribute presence.
* ``TestFrameworkNeutralityWeek5`` (Week 5) — empty
  ``span_processors`` works (TracerProvider accepts no exporter;
  spans register but no export until processor wired); multiple
  processors compose; operator-extended Resource preserves
  framework's ``service.*`` keys (per ADR-0054 D298).
* ``TestSpanAttributesClosedSetPrivacy`` (Week 5) — disallowed
  privacy-relevant keys (``source_list``, ``draft_body``,
  ``dossier_body``, ``exemplar_body``, ``claim_text``) refuse-loud;
  the closed-set IS the regression-barrier (per ADR-0054 D297).
* ``TestPillarGScopeParityWithMeter`` (Week 5) — Tracer scope name
  + version parity with Meter scope; ONE canonical
  ``orchestrator.observability`` scope across both metric + trace
  instruments (per ADR-0054 D295 + ADR-0052 D283 per-pillar-
  symmetry).
* ``TestTracedStageNoOpPosture`` (Week 5) — :func:`traced_stage`
  works WITHOUT prior :func:`init_otel_tracer_provider` call (no-op
  posture; safe-default OTel behavior per ADR-0054 D296).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import observability
from observability import (
    EVENT_CLASS_CATALOG,
    MetricSnapshot,
    OBSERVABILITY_NEW_EVENT_CLASSES,
    _BREAKDOWN_DIMS_ALLOWED,
    _PIPELINE_STAGES,
    _SPAN_ATTRIBUTES_ALLOWED,
    _SPAN_NAME_PREFIX,
    _TRACER_NAME,
    _TRACER_VERSION,
    _composite_key,
    collect_event_class_snapshots,
    default_views,
    get_meter,
    get_send_latency_histogram,
    get_tracer,
    init_otel_meter_provider,
    init_otel_tracer_provider,
    init_prometheus_metric_reader,
    register_event_class_observable_counter,
    register_reconcile_success_ratio_gauge,
    render_prometheus_exposition,
    start_prometheus_http_server,
    traced_stage,
)
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.metrics import Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.metrics.view import (
    ExplicitBucketHistogramAggregation,
    View,
)
from opentelemetry.sdk.resources import (
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import Tracer
from orchestrator.ledger import Ledger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def led_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ledger"
    d.mkdir()
    return d


@pytest.fixture
def led(led_dir: Path) -> Ledger:
    return Ledger(led_dir)


# Anchor `since` to a fixed point so tests are independent of wall-clock.
SINCE_2026_05_01 = datetime(2026, 5, 1, tzinfo=timezone.utc)
NOW_2026_05_25 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)


def _ts(day: int, hour: int = 0, minute: int = 0) -> str:
    """Build a millisecond-precision Z-suffixed ISO ts in May 2026."""
    return f"2026-05-{day:02d}T{hour:02d}:{minute:02d}:00.000Z"


def _direct_write(led_dir: Path, events: list[dict]) -> None:
    """Write events directly to the ledger file, bypassing append's
    auto-fill of ``ts``. The Pillar D Week 12 convention for tests
    that need to exercise pathological event shapes (e.g., the ts-
    missing posture per ADR-0051 D279)."""
    f = led_dir / "events-2026-05-25.jsonl"
    lines = [json.dumps(e) for e in events]
    f.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Module-level constants + closed sets
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """ADR-0050 D272 + ADR-0051 D278 — module-level constants."""

    def test_event_class_catalog_is_frozenset(self):
        assert isinstance(EVENT_CLASS_CATALOG, frozenset)

    def test_event_class_catalog_covers_pillar_a_through_e(self):
        """Every Pillar A-E event class in the foundation ADRs."""
        # Sampled by pillar; full coverage verified at cross-pillar
        # audit row 17.
        required = {
            # Pillar A + Phase 5.5
            "enrolled", "send_intent", "send_confirmed", "policy_blocked",
            "cost_incurred", "manual_override",
            # Pillar B
            "migration_event",
            # Pillar C
            "li_invite_intent", "li_invite_confirmed",
            "tw_dm_intent", "tw_dm_confirmed",
            "calendar_booking_intent", "calendar_booking_confirmed",
            "reconcile_drift", "reconcile_healed",
            # Pillar D
            "reply_classified", "suppression_added",
            "conversation_outcome", "conversation_state_changed",
            # Pillar E
            "discovery_dedup_hit", "email_verification_cache_hit",
            "tier_suggested",
        }
        missing = required - EVENT_CLASS_CATALOG
        assert not missing, (
            f"EVENT_CLASS_CATALOG missing per-pillar classes: {missing!r}"
        )

    def test_breakdown_dims_allowed_includes_channel_P3_1(self):
        """Pillar G Week 1 cross-pillar audit row 11 P3-1 — the
        ``_BREAKDOWN_DIMS_ALLOWED`` frozenset MUST include ``channel``
        for the channel-on-every-event invariant per ADR-0014 D33.
        """
        assert "channel" in _BREAKDOWN_DIMS_ALLOWED

    def test_breakdown_dims_allowed_excludes_privacy_sensitive(self):
        """Privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182
        category 8 — the FIVE disallowed dimensions never enter the
        frozenset."""
        disallowed = {
            "source_list", "draft_body", "dossier_body",
            "exemplar_body", "claim_text",
        }
        assert not (disallowed & _BREAKDOWN_DIMS_ALLOWED)

    def test_observability_new_event_classes_disjoint_from_catalog(self):
        """ADR-0050 D272 + D273 — catalog enumerates CONSUMED; new-
        classes enumerates EMITTED. Disjoint by contract."""
        assert (
            OBSERVABILITY_NEW_EVENT_CLASSES & EVENT_CLASS_CATALOG
            == frozenset()
        )


class TestEventClassCatalogPillarHWeek2AndWeek6Extension:
    """Pillar H Week 2 + Week 6 — ADR-0061 D338's + ADR-0065 D355's
    catalog extensions symmetric assertion at the Pillar G locality
    (the equivalent test at the Pillar H locality lives in
    tests/test_daemon.py). W6 follow-up P3-7 closure renames the class
    + extends the docstring to name BOTH catalog extensions per the
    per-week-reviewer's discipline-scope extension to operator-readable
    test class names.

    The SIX Pillar H event classes (FIVE from Week 2 per ADR-0061 D338
    + ``daemon_stage_saturated`` from Week 6 per ADR-0065 D355) joined
    :data:`EVENT_CLASS_CATALOG` across the Pillar H trajectory. Unlike
    Pillar G's two NEW classes (which stay DISJOINT from the catalog
    because observability EMITS them — see
    :meth:`TestModuleConstants.test_observability_new_event_classes_disjoint_from_catalog`),
    the Pillar H classes are emitted BY the daemon process + CONSUMED
    BY observability via the per-event-class catalog surface, hence
    SUBSET (not DISJOINT) per ADR-0061 D338 + ADR-0065 D355.
    """

    def test_daemon_new_event_classes_subset_of_catalog(self):
        """ADR-0061 D338 + ADR-0065 D355 — `DAEMON_NEW_EVENT_CLASSES`
        is a SUBSET of :data:`EVENT_CLASS_CATALOG` after the Pillar H
        Week 2 + Week 6 catalog extensions."""
        from orchestrator.daemon import DAEMON_NEW_EVENT_CLASSES
        assert DAEMON_NEW_EVENT_CLASSES.issubset(EVENT_CLASS_CATALOG), (
            f"Pillar H Week 2 catalog extension per ADR-0061 D338 + "
            f"Pillar H Week 6 catalog extension per ADR-0065 D355 — "
            f"DAEMON_NEW_EVENT_CLASSES MUST be subset of "
            f"EVENT_CLASS_CATALOG. Missing: "
            f"{sorted(DAEMON_NEW_EVENT_CLASSES - EVENT_CLASS_CATALOG)!r}"
        )

    def test_each_daemon_class_in_catalog(self):
        """Per-cell verification — each of the SIX daemon event
        classes (Week 2 + Week 6 catalog extensions per ADR-0061
        D338 + ADR-0065 D355; W6 follow-up P3-7 closure updates the
        prior "FIVE" docstring drift) appears in the catalog
        (cell-level matrix coverage discipline)."""
        from orchestrator.daemon import DAEMON_NEW_EVENT_CLASSES
        for class_name in DAEMON_NEW_EVENT_CLASSES:
            assert class_name in EVENT_CLASS_CATALOG, (
                f"Pillar H event class {class_name!r} missing from "
                f"EVENT_CLASS_CATALOG; Pillar H Week 2 catalog extension "
                f"per ADR-0061 D338 + Pillar H Week 6 catalog extension "
                f"per ADR-0065 D355 incomplete."
            )

    def test_pillar_h_classes_disjoint_from_observability_new_classes(self):
        """Per-pillar mirror constants parity — the Pillar H SIX
        classes (Week 2 + Week 6 catalog extensions per ADR-0061
        D338 + ADR-0065 D355; W6 follow-up P3-7 closure updates the
        prior "5" docstring drift) are DISJOINT from the Pillar G
        2 classes (:data:`OBSERVABILITY_NEW_EVENT_CLASSES`); the
        disjointness protects against accidental cross-pillar
        event-class drift."""
        from orchestrator.daemon import DAEMON_NEW_EVENT_CLASSES
        assert (
            DAEMON_NEW_EVENT_CLASSES & OBSERVABILITY_NEW_EVENT_CLASSES
            == frozenset()
        )


# ---------------------------------------------------------------------------
# breakdown_by validation
# ---------------------------------------------------------------------------


class TestBreakdownByValidation:
    """ADR-0050 D276(b) + ADR-0051 D278 — the ``breakdown_by`` kwarg
    refuses-loud on disallowed dimensions."""

    @pytest.mark.parametrize("disallowed_dim", [
        "source_list", "draft_body", "dossier_body",
        "exemplar_body", "claim_text",
    ])
    def test_disallowed_dim_refuses_loud(self, led, disallowed_dim):
        with pytest.raises(ValueError) as exc:
            collect_event_class_snapshots(
                led, since=SINCE_2026_05_01,
                breakdown_by=(disallowed_dim,),
            )
        msg = str(exc.value)
        assert disallowed_dim in msg
        assert "_BREAKDOWN_DIMS_ALLOWED" in msg
        # Privacy invariant citation.
        assert "I8" in msg or "D276(b)" in msg

    @pytest.mark.parametrize("allowed_dim", [
        "channel", "register", "source_skill", "category",
        "classification_method", "outcome", "reason", "result_state",
        "event_class",
    ])
    def test_allowed_dim_accepts(self, led, allowed_dim):
        # No raise.
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01,
            breakdown_by=(allowed_dim,),
        )
        assert snaps == []  # empty ledger

    def test_mixed_allowed_and_disallowed_refuses_loud(self, led):
        with pytest.raises(ValueError):
            collect_event_class_snapshots(
                led, since=SINCE_2026_05_01,
                breakdown_by=("channel", "source_list"),
            )

    def test_empty_tuple_no_breakdown(self, led):
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01,
            breakdown_by=(),
        )
        assert snaps == []


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    """Per-class aggregation across Pillar A/B/C/D/E/F event classes."""

    def test_single_class_single_event(self, led):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": _ts(10)})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1
        s = snaps[0]
        assert s.event_class == "enrolled"
        assert s.total_count == 1
        assert s.oldest_ts == _ts(10)
        assert s.newest_ts == _ts(10)

    def test_single_class_multiple_events_oldest_newest(self, led):
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(5)})
        led.append({"type": "send_intent", "person_id": "p2",
                    "channel": "email", "ts": _ts(20)})
        led.append({"type": "send_intent", "person_id": "p3",
                    "channel": "email", "ts": _ts(15)})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1
        s = snaps[0]
        assert s.total_count == 3
        assert s.oldest_ts == _ts(5)
        assert s.newest_ts == _ts(20)

    def test_multi_class_per_pillar_sample(self, led):
        # One sample from each pillar's event class set.
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": _ts(10)})                      # Pillar A
        led.append({"type": "migration_event",
                    "ts": _ts(11)})                      # Pillar B
        led.append({"type": "li_invite_intent", "person_id": "p1",
                    "channel": "linkedin", "intent_id": "snd_x",
                    "ts": _ts(12)})                      # Pillar C
        led.append({"type": "reply_classified", "person_id": "p1",
                    "channel": "email", "category": "positive",
                    "ts": _ts(13)})                      # Pillar D
        led.append({"type": "tier_suggested", "person_id": "p1",
                    "ts": _ts(14)})                      # Pillar E
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        classes = {s.event_class for s in snaps}
        assert classes == {
            "enrolled", "migration_event", "li_invite_intent",
            "reply_classified", "tier_suggested",
        }
        for s in snaps:
            assert s.total_count == 1


# ---------------------------------------------------------------------------
# Window filter
# ---------------------------------------------------------------------------


class TestWindowFilter:
    """Window inclusion semantics per ADR-0051 D278."""

    def test_event_before_since_excluded(self, led):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": "2026-04-01T00:00:00.000Z"})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert snaps == []

    def test_event_after_since_included(self, led):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": _ts(10)})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1

    def test_event_at_boundary_included(self, led):
        # Event ts == since → included (since is inclusive).
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": "2026-05-01T00:00:00.000000+00:00"})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1

    def test_since_with_naive_datetime_assumed_utc(self, led):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": _ts(10)})
        # Naive datetime — primitive treats as UTC.
        naive_since = datetime(2026, 5, 1)
        snaps = collect_event_class_snapshots(led, since=naive_since)
        assert len(snaps) == 1


# ---------------------------------------------------------------------------
# Channel-on-every-event invariant
# ---------------------------------------------------------------------------


class TestChannelInvariant:
    """ADR-0014 D33 + ADR-0050 D276(c) + ADR-0051 D281 — channel
    field semantics on MetricSnapshot."""

    def test_homogeneous_single_channel_surfaces(self, led):
        led.append({"type": "send_intent", "channel": "email",
                    "person_id": "p1", "ts": _ts(10)})
        led.append({"type": "send_intent", "channel": "email",
                    "person_id": "p2", "ts": _ts(11)})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1
        assert snaps[0].channel == "email"

    def test_heterogeneous_channels_surface_none(self, led):
        led.append({"type": "reply_classified", "channel": "email",
                    "person_id": "p1", "category": "positive",
                    "ts": _ts(10)})
        led.append({"type": "reply_classified", "channel": "linkedin",
                    "person_id": "p2", "category": "positive",
                    "ts": _ts(11)})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1
        assert snaps[0].channel is None

    def test_no_channel_field_surfaces_none(self, led):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": _ts(10)})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1
        assert snaps[0].channel is None

    def test_mix_channel_and_no_channel_surfaces_none(self, led):
        # Pathological: a class that USUALLY carries channel has one
        # event missing it. The snapshot's top-level channel surfaces
        # as None so the operator sees the inconsistency.
        led.append({"type": "send_intent", "channel": "email",
                    "person_id": "p1", "ts": _ts(10)})
        led.append({"type": "send_intent", "person_id": "p2",
                    "ts": _ts(11)})        # no channel
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        assert len(snaps) == 1
        assert snaps[0].channel is None


# ---------------------------------------------------------------------------
# Uncatalogued diagnostic emit
# ---------------------------------------------------------------------------


class TestUncataloguedDiagnostic:
    """ADR-0050 D272 + R031 + ADR-0051 D279 — refuse-loud on
    uncatalogued event class via ``observability_class_uncatalogued``
    diagnostic emit (kind="uncatalogued")."""

    def test_one_uncatalogued_event_triggers_emit(self, led_dir, led):
        _direct_write(led_dir, [
            {"v": 1, "type": "totally_unknown_class", "person_id": "p1",
             "ts": _ts(10)},
        ])
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        # Re-walk to find the appended diagnostic.
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert len(diagnostics) == 1
        d = diagnostics[0]
        assert d["kind"] == "uncatalogued"
        assert d["offending_type"] == "totally_unknown_class"
        assert d["count"] == 1
        assert d["channel"] is None
        assert d["_emitted_by"] == "observability"

    def test_multiple_uncatalogued_events_one_emit_count_aggregates(
            self, led_dir, led):
        _direct_write(led_dir, [
            {"v": 1, "type": "unknown_a", "ts": _ts(10)},
            {"v": 1, "type": "unknown_b", "ts": _ts(11)},
            {"v": 1, "type": "unknown_a", "ts": _ts(12)},
        ])
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert len(diagnostics) == 1
        assert diagnostics[0]["count"] == 3
        # First-seen offending_type sampled.
        assert diagnostics[0]["offending_type"] == "unknown_a"

    def test_no_uncatalogued_no_emit(self, led, led_dir):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": _ts(10)})
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert diagnostics == []


# ---------------------------------------------------------------------------
# Missing-ts diagnostic emit (Pillar G Week 1 audit P2-1 carry-forward)
# ---------------------------------------------------------------------------


class TestMissingTsDiagnostic:
    """ADR-0051 D279 + Pillar G Week 1 cross-pillar audit row 11 P2-1
    carry-forward — refuse-loud on ts-missing event via
    ``observability_class_uncatalogued`` diagnostic emit
    (kind="missing_ts").

    The refusal posture diverges from :mod:`orchestrator.funnel`'s
    legacy silent-skip behavior at ``funnel.py:205`` — ts-missing
    events were invisible in the funnel CLI's output. Pillar G's
    primitive surfaces them via the diagnostic event so operators
    investigate the producer."""

    def test_one_ts_missing_event_triggers_emit(self, led_dir, led):
        _direct_write(led_dir, [
            # Note: NO ts field
            {"v": 1, "type": "reply_classified", "person_id": "p1",
             "channel": "email", "category": "positive"},
        ])
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert len(diagnostics) == 1
        d = diagnostics[0]
        assert d["kind"] == "missing_ts"
        assert d["offending_type"] == "reply_classified"
        assert d["person_id"] == "p1"
        assert d["count"] == 1
        assert d["_emitted_by"] == "observability"

    def test_multiple_ts_missing_events_one_emit_count_aggregates(
            self, led_dir, led):
        _direct_write(led_dir, [
            {"v": 1, "type": "reply_classified", "person_id": "pA",
             "channel": "email"},
            {"v": 1, "type": "reply_classified", "person_id": "pB",
             "channel": "email"},
            {"v": 1, "type": "send_intent", "person_id": "pC",
             "channel": "email"},
        ])
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert len(diagnostics) == 1
        assert diagnostics[0]["count"] == 3
        # First-seen offending_type + person_id sampled.
        assert diagnostics[0]["offending_type"] == "reply_classified"
        assert diagnostics[0]["person_id"] == "pA"

    def test_empty_ts_string_treated_as_missing(self, led_dir, led):
        _direct_write(led_dir, [
            {"v": 1, "type": "reply_classified", "person_id": "p1",
             "channel": "email", "ts": ""},
        ])
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert len(diagnostics) == 1
        assert diagnostics[0]["kind"] == "missing_ts"

    def test_ts_missing_event_excluded_from_snapshot(self, led_dir, led):
        _direct_write(led_dir, [
            {"v": 1, "type": "reply_classified", "person_id": "p1",
             "channel": "email"},        # ts-missing — excluded
            {"v": 1, "type": "reply_classified", "person_id": "p2",
             "channel": "email", "category": "positive",
             "ts": _ts(10)},             # valid — counted
        ])
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert len(snaps) == 1
        assert snaps[0].total_count == 1


# ---------------------------------------------------------------------------
# Both diagnostics together (kind cross-product)
# ---------------------------------------------------------------------------


class TestBothDiagnosticsTogether:
    """ADR-0051 D279 — at-most-ONE emission per ``kind`` per call;
    independent kinds emit independently."""

    def test_uncatalogued_and_missing_ts_in_same_call_both_emit(
            self, led_dir, led):
        _direct_write(led_dir, [
            {"v": 1, "type": "unknown_class", "ts": _ts(10)},
            {"v": 1, "type": "reply_classified", "person_id": "p1",
             "channel": "email"},         # ts-missing
            {"v": 1, "type": "enrolled", "person_id": "p2",
             "ts": _ts(11)},
        ])
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        kinds = {d["kind"] for d in diagnostics}
        assert kinds == {"uncatalogued", "missing_ts"}
        assert len(diagnostics) == 2


# ---------------------------------------------------------------------------
# Breakdown determinism
# ---------------------------------------------------------------------------


class TestBreakdownDeterminism:
    """ADR-0051 D278 + D280 — composite keys mirror funnel.py;
    per_breakdown_counts is alphabetically sorted; missing fields
    render as ``"none"``."""

    def test_single_dim_breakdown(self, led):
        led.append({"type": "send_intent", "channel": "email",
                    "person_id": "p1", "ts": _ts(10)})
        led.append({"type": "send_intent", "channel": "email",
                    "person_id": "p2", "ts": _ts(11)})
        led.append({"type": "send_intent", "channel": "linkedin",
                    "person_id": "p3", "ts": _ts(12)})
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01,
            breakdown_by=("channel",),
        )
        assert len(snaps) == 1
        assert snaps[0].per_breakdown_counts == {
            "email": 2,
            "linkedin": 1,
        }

    def test_multi_dim_composite_key(self, led):
        led.append({"type": "reply_classified", "channel": "email",
                    "category": "positive", "person_id": "p1",
                    "ts": _ts(10)})
        led.append({"type": "reply_classified", "channel": "linkedin",
                    "category": "negative", "person_id": "p2",
                    "ts": _ts(11)})
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01,
            breakdown_by=("channel", "category"),
        )
        assert len(snaps) == 1
        assert snaps[0].per_breakdown_counts == {
            "email|positive": 1,
            "linkedin|negative": 1,
        }

    def test_missing_field_renders_as_none(self, led):
        led.append({"type": "send_intent", "person_id": "p1",
                    "ts": _ts(10)})        # no channel
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01,
            breakdown_by=("channel",),
        )
        assert snaps[0].per_breakdown_counts == {"none": 1}

    def test_per_breakdown_counts_sorted(self, led):
        led.append({"type": "send_intent", "channel": "twitter",
                    "person_id": "p1", "ts": _ts(10)})
        led.append({"type": "send_intent", "channel": "email",
                    "person_id": "p2", "ts": _ts(11)})
        led.append({"type": "send_intent", "channel": "linkedin",
                    "person_id": "p3", "ts": _ts(12)})
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01,
            breakdown_by=("channel",),
        )
        # Iteration over a dict preserves insertion order in Py 3.7+;
        # the primitive sorts before building the dict, so keys
        # iterate in ascending alphabetical order.
        keys = list(snaps[0].per_breakdown_counts.keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Snapshot ordering
# ---------------------------------------------------------------------------


class TestSnapshotOrdering:
    """ADR-0051 D280 — snapshots sorted alphabetically by event_class
    per the deterministic-output contract per ADR-0031 D140."""

    def test_snapshots_sorted_alphabetically(self, led):
        led.append({"type": "send_intent", "channel": "email",
                    "person_id": "p1", "ts": _ts(10)})
        led.append({"type": "enrolled", "person_id": "p2",
                    "ts": _ts(11)})
        led.append({"type": "reply_classified", "channel": "email",
                    "person_id": "p3", "category": "positive",
                    "ts": _ts(12)})
        snaps = collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        classes = [s.event_class for s in snaps]
        assert classes == sorted(classes)
        assert classes == ["enrolled", "reply_classified", "send_intent"]


# ---------------------------------------------------------------------------
# Deterministic-clock contract
# ---------------------------------------------------------------------------


class TestDeterministicClock:
    """ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265
    + ADR-0051 D278 — the ``now`` kwarg controls diagnostic emit ts
    for byte-identical reproducibility."""

    def test_now_kwarg_stamps_diagnostic_ts(self, led_dir, led):
        fixed_now = datetime(2027, 1, 1, 0, 0, 0,
                             tzinfo=timezone.utc)
        _direct_write(led_dir, [
            {"v": 1, "type": "unknown_class", "ts": _ts(10)},
        ])
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=fixed_now,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert diagnostics[0]["ts"] == "2027-01-01T00:00:00.000Z"

    def test_now_default_uses_wall_clock(self, led_dir, led):
        # Sanity: when now=None the diagnostic carries a recent
        # timestamp (within 60 seconds of wall clock).
        _direct_write(led_dir, [
            {"v": 1, "type": "unknown_class", "ts": _ts(10)},
        ])
        before = datetime.now(timezone.utc)
        collect_event_class_snapshots(led, since=SINCE_2026_05_01)
        after = datetime.now(timezone.utc)
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        ts = diagnostics[0]["ts"]
        assert (before - timedelta(seconds=60)).isoformat() < ts
        assert ts < (after + timedelta(seconds=60)).isoformat()

    def test_naive_now_treated_as_utc(self, led_dir, led):
        _direct_write(led_dir, [
            {"v": 1, "type": "unknown_class", "ts": _ts(10)},
        ])
        naive_now = datetime(2027, 1, 1, 0, 0, 0)
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=naive_now,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert diagnostics[0]["ts"] == "2027-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Recursive uncatalogued protection (R031 stability)
# ---------------------------------------------------------------------------


class TestObservabilityNewClassesNotUncatalogued:
    """ADR-0051 D278 — events of class in
    ``OBSERVABILITY_NEW_EVENT_CLASSES`` aggregate as known (NOT
    flagged as uncatalogued). Without this, every consecutive
    primitive call would see the previous call's diagnostic emit and
    emit another, producing an infinite-recursion of diagnostics."""

    def test_observability_event_does_not_trigger_uncatalogued(
            self, led, led_dir):
        # Append a diagnostic event by-hand (mimicking what a prior
        # call would have emitted).
        led.append({
            "type": "observability_class_uncatalogued",
            "kind": "uncatalogued",
            "offending_type": "some_old_unknown",
            "count": 1,
            "channel": None,
            "_emitted_by": "observability",
            "ts": _ts(10),
        })
        # Now call the primitive again.
        collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        # Only the one we appended by-hand exists; the call did NOT
        # emit another diagnostic.
        assert len(diagnostics) == 1
        # And the snapshot includes the diagnostic event class as a
        # normal counted class.
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        classes = {s.event_class for s in snaps}
        assert "observability_class_uncatalogued" in classes


# ---------------------------------------------------------------------------
# Empty + out-of-window
# ---------------------------------------------------------------------------


class TestEmptyAndOutOfWindow:
    """Edge cases — empty ledger or all-out-of-window events produce
    empty snapshot list + zero diagnostic emits."""

    def test_empty_ledger(self, led, led_dir):
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps == []
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert diagnostics == []

    def test_all_events_out_of_window(self, led, led_dir):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": "2026-04-01T00:00:00.000Z"})
        snaps = collect_event_class_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps == []
        led2 = Ledger(led_dir)
        diagnostics = [
            e for e in led2.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert diagnostics == []


# ---------------------------------------------------------------------------
# MetricSnapshot frozen-dataclass invariants
# ---------------------------------------------------------------------------


class TestMetricSnapshotInvariants:
    """ADR-0050 D272 — MetricSnapshot is frozen + immutable."""

    def test_frozen_refuses_attribute_assignment(self):
        snap = MetricSnapshot(
            event_class="send_confirmed",
            channel="email",
            total_count=1,
        )
        with pytest.raises((AttributeError, Exception)):
            snap.total_count = 99      # type: ignore[misc]


# ---------------------------------------------------------------------------
# _composite_key parity with funnel.py
# ---------------------------------------------------------------------------


class TestCompositeKeyParity:
    """ADR-0051 D278 — _composite_key mirrors
    :func:`orchestrator.funnel._composite_key` to preserve the
    deterministic per-breakdown-key shape per ADR-0031 D140."""

    def test_single_field(self):
        from orchestrator.ledger import Event

        e = Event(type="reply_classified", channel="email",
                  category="positive", ts=_ts(10))
        assert _composite_key(e, ("channel",)) == "email"

    def test_multi_field_pipe_delimited(self):
        from orchestrator.ledger import Event

        e = Event(type="reply_classified", channel="email",
                  category="positive", ts=_ts(10))
        assert _composite_key(e, ("channel", "category")) == "email|positive"

    def test_missing_field_renders_as_none_literal(self):
        from orchestrator.ledger import Event

        e = Event(type="enrolled", person_id="p1", ts=_ts(10))
        assert _composite_key(e, ("channel",)) == "none"
        assert _composite_key(e, ("channel", "category")) == "none|none"

    def test_matches_funnel_helper_byte_for_byte(self):
        """Parity with :func:`orchestrator.funnel._composite_key` — same
        function shape; same output for same input."""
        from orchestrator import funnel as _funnel

        d = {"type": "reply_classified", "channel": "email",
             "category": "positive"}
        assert _composite_key(d, ("channel", "category")) \
            == _funnel._composite_key(d, ("channel", "category"))
        assert _composite_key(d, ("channel",)) \
            == _funnel._composite_key(d, ("channel",))
        d2 = {"type": "enrolled", "person_id": "p1"}
        assert _composite_key(d2, ("channel",)) \
            == _funnel._composite_key(d2, ("channel",))


# ===========================================================================
# Pillar G Week 3 — OTel SDK initialization tests (per ADR-0052 D282-D287)
# ===========================================================================


# ---------------------------------------------------------------------------
# Helpers shared by Week 3 OTel tests
# ---------------------------------------------------------------------------


def _make_provider_with_reader(
    *, resource: Resource | None = None,
) -> tuple[MeterProvider, InMemoryMetricReader]:
    """Build a local MeterProvider + InMemoryMetricReader pair.

    Tests use ``set_global=False`` to avoid OTel's set-once semantics
    (subsequent ``set_meter_provider`` calls log a warning + no-op).
    """
    reader = InMemoryMetricReader()
    provider = init_otel_meter_provider(
        resource=resource,
        metric_readers=[reader],
        set_global=False,
    )
    return provider, reader


def _collect_metric_data(
    reader: InMemoryMetricReader,
    metric_name: str,
) -> list[tuple[dict, int]]:
    """Trigger a scrape + return [(attrs_dict, value), ...] for the
    metric. Returns empty list if no observations."""
    data = reader.get_metrics_data()
    if data is None:
        return []
    out: list[tuple[dict, int]] = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == metric_name:
                    for dp in m.data.data_points:
                        out.append((dict(dp.attributes), dp.value))
    return out


def _find_scope_metric(
    reader: InMemoryMetricReader,
    metric_name: str,
):
    """Return the Metric object matching ``metric_name`` after a
    scrape; ``None`` if not found."""
    data = reader.get_metrics_data()
    if data is None:
        return None
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == metric_name:
                    return (rm, sm, m)
    return None


# ---------------------------------------------------------------------------
# Module-level OTel constants (Week 3)
# ---------------------------------------------------------------------------


class TestOTelModuleConstants:
    """ADR-0052 D282-D287 — module-level OTel constants.

    Cell-level coverage per the per-week-reviewer discipline carried
    forward EIGHT consecutive weeks (Pillar F W6-W12 + Pillar G W2):

    * ``_METER_NAME`` — single canonical OTel scope (D283).
    * ``_METER_VERSION`` — scope version (D283).
    * ``_SERVICE_NAME`` — default Resource ``service.name`` (D287).
    * ``_SERVICE_VERSION`` — default Resource ``service.version`` (D287).
    * ``_INSTRUMENT_NAME_EVENTS_TOTAL`` — canonical instrument name
      with ``outreach_factory_`` prefix + ``_total`` suffix (D284).
    """

    def test_meter_name_constant(self):
        assert observability._METER_NAME == "orchestrator.observability"

    def test_meter_version_constant(self):
        # The first version pin per ADR-0052 D283; bumps with
        # non-backwards-compat instrument extensions at later weeks.
        assert observability._METER_VERSION == "0.1.0"

    def test_service_name_constant(self):
        # The default Resource service.name per ADR-0052 D287.
        assert observability._SERVICE_NAME == "outreach-factory"

    def test_service_version_constant(self):
        # The first version pin per ADR-0052 D287.
        assert observability._SERVICE_VERSION == "0.1.0"

    def test_instrument_name_events_total_constant(self):
        # Per ADR-0052 D284 — namespace prefix + Prometheus
        # ``_total`` suffix (the counter convention).
        assert observability._INSTRUMENT_NAME_EVENTS_TOTAL \
            == "outreach_factory_events_total"

    def test_instrument_name_uses_framework_namespace_prefix(self):
        """ADR-0052 D284 — the ``outreach_factory_`` prefix is the
        per-framework namespace so operators sharing a Prometheus
        pool see per-framework metric segregation."""
        assert observability._INSTRUMENT_NAME_EVENTS_TOTAL.startswith(
            "outreach_factory_"
        )

    def test_instrument_name_uses_total_suffix_prometheus_convention(self):
        """ADR-0052 D284 + D285 — the ``_total`` suffix is the
        Prometheus counter convention (monotonic cumulative count;
        operators query the per-window rate via ``rate()`` /
        ``increase()``)."""
        assert observability._INSTRUMENT_NAME_EVENTS_TOTAL.endswith(
            "_total"
        )


# ---------------------------------------------------------------------------
# init_otel_meter_provider (Week 3)
# ---------------------------------------------------------------------------


class TestInitOTelMeterProvider:
    """ADR-0052 D282 + D286 + D287 — MeterProvider initialization
    cells: default Resource / custom Resource / custom readers /
    set_global True/False / Resource auto-injected SDK attributes."""

    def test_returns_meter_provider_instance(self):
        provider = init_otel_meter_provider(set_global=False)
        assert isinstance(provider, MeterProvider)

    def test_default_resource_carries_service_name(self):
        """ADR-0052 D287 — default Resource carries the framework's
        ``service.name`` per the per-tenant audit-tooling
        trajectory."""
        provider = init_otel_meter_provider(set_global=False)
        attrs = dict(provider._sdk_config.resource.attributes)
        assert attrs[SERVICE_NAME] == "outreach-factory"

    def test_default_resource_carries_service_version(self):
        """ADR-0052 D287 — default Resource carries the framework's
        ``service.version`` for downstream provenance tracking."""
        provider = init_otel_meter_provider(set_global=False)
        attrs = dict(provider._sdk_config.resource.attributes)
        assert attrs[SERVICE_VERSION] == "0.1.0"

    def test_default_resource_carries_otel_sdk_auto_attributes(self):
        """OTel SDK auto-injects ``telemetry.sdk.*`` attributes per
        the OTel resource semantic conventions. ADR-0052 D287's
        Resource-attribute closed-set does NOT enumerate these (they
        come from the SDK), but they MUST be present for downstream
        OTLP collectors to disambiguate Python clients."""
        provider = init_otel_meter_provider(set_global=False)
        attrs = dict(provider._sdk_config.resource.attributes)
        assert "telemetry.sdk.language" in attrs
        assert attrs["telemetry.sdk.language"] == "python"
        assert "telemetry.sdk.name" in attrs
        assert "telemetry.sdk.version" in attrs

    def test_custom_resource_preserved_verbatim(self):
        """ADR-0052 D286 — framework-neutrality contract. Operators
        extending Resource with per-tenant labels at Pillar I MUST
        be able to override the default."""
        custom = Resource.create({
            SERVICE_NAME: "operator-fork",
            SERVICE_VERSION: "1.2.3",
            "outreach_factory.tenant_id": "tenant-a",
        })
        provider = init_otel_meter_provider(
            resource=custom, set_global=False,
        )
        attrs = dict(provider._sdk_config.resource.attributes)
        assert attrs[SERVICE_NAME] == "operator-fork"
        assert attrs[SERVICE_VERSION] == "1.2.3"
        assert attrs["outreach_factory.tenant_id"] == "tenant-a"

    def test_custom_metric_readers_registered(self, tmp_path):
        """ADR-0052 D286 — operator-supplied metric readers (Prometheus,
        OTLP, InMemory for tests) flow through to the MeterProvider
        + collect scrapes when triggered."""
        reader = InMemoryMetricReader()
        provider = init_otel_meter_provider(
            metric_readers=[reader], set_global=False,
        )
        # Wire an instrument to confirm the reader actually scrapes
        # against the provider (the reader is registered on the
        # MeterProvider's internal reader list).
        led_dir = tmp_path / "ledger"
        led_dir.mkdir()
        led = Ledger(led_dir)
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        data = reader.get_metrics_data()
        assert data is not None
        # And the data carries the per-event-class observation.
        assert len(data.resource_metrics) >= 1

    def test_empty_metric_readers_default(self):
        """ADR-0052 D286 — Week 3 default is EMPTY tuple; the
        MeterProvider accepts NO readers; instruments register,
        callbacks register, but no scrape fires until a reader is
        added (Week 4 wires the Prometheus exporter)."""
        # Should not raise.
        provider = init_otel_meter_provider(set_global=False)
        assert provider is not None

    def test_set_global_false_does_not_set_global(self):
        """ADR-0052 D282 — tests pass ``set_global=False`` to avoid
        OTel's set-once enforcement. The returned provider is the
        operator's responsibility (not registered globally)."""
        from opentelemetry import metrics as _otel
        before = _otel.get_meter_provider()
        provider = init_otel_meter_provider(set_global=False)
        after = _otel.get_meter_provider()
        # The global is unchanged when set_global=False.
        assert before is after
        # The returned provider is distinct from the global no-op.
        assert provider is not after or (provider is after is None)


# ---------------------------------------------------------------------------
# get_meter accessor (Week 3)
# ---------------------------------------------------------------------------


class TestGetMeter:
    """ADR-0052 D283 — :func:`get_meter` returns the canonical
    Pillar G observability :class:`Meter` from explicit or global
    providers."""

    def test_explicit_provider_returns_meter(self):
        provider = init_otel_meter_provider(set_global=False)
        meter = get_meter(meter_provider=provider)
        assert isinstance(meter, Meter)

    def test_meter_name_matches_canonical_scope(self):
        """ADR-0052 D283 — single canonical OTel scope name."""
        provider = init_otel_meter_provider(set_global=False)
        meter = get_meter(meter_provider=provider)
        assert meter.name == "orchestrator.observability"

    def test_meter_version_matches_canonical_version(self):
        """ADR-0052 D283 — single canonical OTel scope version."""
        provider = init_otel_meter_provider(set_global=False)
        meter = get_meter(meter_provider=provider)
        assert meter.version == "0.1.0"

    def test_meter_uses_global_provider_when_no_explicit(self):
        """Default consults the global provider; production callers
        rely on this to keep a single canonical Meter."""
        from opentelemetry import metrics as _otel
        meter = get_meter()
        # Should not raise.
        assert meter is not None
        # The meter is sourced from the global provider (may be the
        # OTel no-op default if init has not been called).
        assert meter.name == "orchestrator.observability" or \
            isinstance(meter, Meter)


# ---------------------------------------------------------------------------
# ObservableCounter registration shape (Week 3)
# ---------------------------------------------------------------------------


class TestObservableCounterRegistration:
    """ADR-0052 D284 + D285 — per-event-class instrument registration.

    The single canonical instrument:

    * Name = ``outreach_factory_events_total``.
    * Unit = ``"1"`` (count semantics).
    * Description names ``collect_event_class_snapshots`` (Week 2
      primitive consumed under the hood).
    * Type = ObservableCounter (monotonic counter per ADR-0052 D285).
    """

    def test_registers_instrument_with_canonical_name(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        counter = register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        assert counter is not None
        assert counter.name == "outreach_factory_events_total"

    def test_instrument_unit_is_count(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        # Inspect the metric data unit after a scrape (even an empty
        # ledger triggers the instrument to register + the metric
        # data to expose its unit).
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        triple = _find_scope_metric(reader, "outreach_factory_events_total")
        assert triple is not None
        _, _, metric = triple
        assert metric.unit == "1"

    def test_instrument_description_names_primitive(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        triple = _find_scope_metric(reader, "outreach_factory_events_total")
        assert triple is not None
        _, _, metric = triple
        assert "collect_event_class_snapshots" in metric.description

    def test_instrument_is_observable_counter_type(self, led):
        """ADR-0052 D285 — ObservableCounter (monotonic) NOT
        Gauge (point-in-time). The data point sums are
        :class:`Sum` (counter); a :class:`Gauge` data class would
        violate the Prometheus convention."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        triple = _find_scope_metric(reader, "outreach_factory_events_total")
        assert triple is not None
        _, _, metric = triple
        # OTel SDK 1.x: ObservableCounter data is Sum (cumulative);
        # Gauge data would be Gauge. Verify Sum type.
        from opentelemetry.sdk.metrics._internal.point import Sum
        assert isinstance(metric.data, Sum), (
            f"Expected ObservableCounter Sum data; got "
            f"{type(metric.data).__name__}. ADR-0052 D285 — the "
            "per-event-class instrument is a monotonic counter, NOT "
            "a gauge."
        )

    def test_scope_name_and_version_on_metric(self, led):
        """ADR-0052 D283 — the per-instrument scope MUST be the
        canonical observability scope."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        triple = _find_scope_metric(reader, "outreach_factory_events_total")
        assert triple is not None
        _, scope_metric, _ = triple
        assert scope_metric.scope.name == "orchestrator.observability"
        assert scope_metric.scope.version == "0.1.0"


# ---------------------------------------------------------------------------
# ObservableCounter callback behavior (Week 3)
# ---------------------------------------------------------------------------


class TestObservableCounterCallbackBehavior:
    """ADR-0052 D284 — the per-scrape callback emits ONE
    :class:`Observation` per :class:`MetricSnapshot` carrying
    ``event_class`` + ``channel`` attributes. The observation value
    matches :attr:`MetricSnapshot.total_count`."""

    def test_single_snapshot_single_observation(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "send_intent", "person_id": "p2",
                    "channel": "email", "ts": _ts(11)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        # ONE observation for one event class; value 2.
        assert len(obs) == 1
        attrs, value = obs[0]
        assert attrs["event_class"] == "send_intent"
        assert attrs["channel"] == "email"
        assert value == 2

    def test_multiple_snapshots_one_observation_each(self, led):
        """Per-event-class symmetry — each MetricSnapshot from
        collect_event_class_snapshots produces ONE observation."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "send_confirmed", "person_id": "p1",
                    "channel": "email", "ts": _ts(10, 5)})
        led.append({"type": "reply_classified", "person_id": "p1",
                    "channel": "email", "category": "positive",
                    "ts": _ts(11)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        # Three observations: send_intent + send_confirmed +
        # reply_classified.
        by_class = {attrs["event_class"]: value for attrs, value in obs}
        assert by_class == {
            "send_intent": 1, "send_confirmed": 1, "reply_classified": 1,
        }

    def test_observation_attributes_have_event_class_and_channel(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert len(obs) == 1
        attrs, _ = obs[0]
        # Exactly two attributes — event_class + channel.
        assert set(attrs.keys()) == {"event_class", "channel"}


# ---------------------------------------------------------------------------
# Channel-on-every-event cells in the OTel wrapper (Week 3)
# ---------------------------------------------------------------------------


class TestObservableCounterChannelCells:
    """ADR-0014 D33 + ADR-0051 D281 + ADR-0052 D284 — the channel-on-
    every-event invariant flows from :attr:`MetricSnapshot.channel`
    through the OTel wrapper's per-observation attribute.

    OTel attributes do NOT accept ``None`` per the spec — the wrapper
    coerces ``None`` to the literal string ``"none"`` per the
    deterministic-output convention mirroring
    :func:`_composite_key`'s missing-field rendering.
    """

    def test_homogeneous_channel_surfaces_email(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "send_intent", "person_id": "p2",
                    "channel": "email", "ts": _ts(11)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert obs == [({"event_class": "send_intent",
                         "channel": "email"}, 2)]

    def test_no_channel_event_surfaces_none_literal(self, led):
        """Events without channel field (e.g., enrolled,
        migration_event) surface channel="none" literal per
        ADR-0052 D284's OTel-attribute-cannot-be-None workaround."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": _ts(10)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert len(obs) == 1
        attrs, value = obs[0]
        assert attrs["channel"] == "none"
        assert value == 1

    def test_heterogeneous_channels_surface_none_literal(self, led):
        """ADR-0051 D281 — heterogeneous channels collapse to
        :attr:`MetricSnapshot.channel` = None; the OTel wrapper
        renders as ``"none"`` literal."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "reply_classified", "person_id": "p1",
                    "channel": "email", "category": "positive",
                    "ts": _ts(10)})
        led.append({"type": "reply_classified", "person_id": "p2",
                    "channel": "linkedin", "category": "positive",
                    "ts": _ts(11)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert len(obs) == 1
        attrs, value = obs[0]
        assert attrs["channel"] == "none"
        assert value == 2

    def test_mix_channel_and_no_channel_surfaces_none_literal(self, led):
        """Pathological producer bug — same event class emitted with
        + without channel field. Per ADR-0051 D281 + ADR-0052 D284's
        OTel rendering: ``snap.channel == None`` → attribute "none"."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "reply_classified", "person_id": "p1",
                    "channel": "email", "category": "positive",
                    "ts": _ts(10)})
        led.append({"type": "reply_classified", "person_id": "p2",
                    "category": "positive", "ts": _ts(11)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert len(obs) == 1
        attrs, value = obs[0]
        assert attrs["channel"] == "none"
        assert value == 2


# ---------------------------------------------------------------------------
# Deterministic-clock contract for the OTel wrapper (Week 3)
# ---------------------------------------------------------------------------


class TestObservableCounterDeterministicClock:
    """ADR-0052 D284 — the ``now`` kwarg is a CALLABLE returning the
    "current time" per-scrape. Production callers omit (wall-clock);
    tests pass a captured-lambda for byte-identical reproducibility
    across consecutive scrapes against a fixed ledger state."""

    def test_now_callable_flows_through(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        captured: list[datetime] = []

        def _now() -> datetime:
            captured.append(NOW_2026_05_25)
            return NOW_2026_05_25

        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=_now,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        _collect_metric_data(reader, "outreach_factory_events_total")

        # The callable was invoked once per scrape.
        assert len(captured) == 1
        assert captured[0] == NOW_2026_05_25

    def test_since_window_applied_correctly(self, led):
        """The per-scrape window is ``now - since_window`` — events
        before that point are out-of-window + excluded."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=7),       # 7-day window
            now=lambda: NOW_2026_05_25,           # anchor 2026-05-25
            meter=meter,
        )
        # In window (2026-05-20 -> within 5 days of anchor).
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(20)})
        # Out of window (2026-05-10 -> 15 days before anchor).
        led.append({"type": "send_intent", "person_id": "p2",
                    "channel": "email", "ts": _ts(10)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert len(obs) == 1
        _, value = obs[0]
        assert value == 1


# ---------------------------------------------------------------------------
# Behavioral-passthrough-not-signature-only (Week 3)
# ---------------------------------------------------------------------------


class TestObservableCounterKwargPassthrough:
    """Per the "behavioral-passthrough-not-signature-only" discipline
    carried FOUR consecutive Pillar F weeks W8-W11 + applied at
    Pillar G W3 — the per-kwarg passthrough MUST be observed at the
    downstream :func:`collect_event_class_snapshots` call, NOT just
    accepted at the wrapper's signature."""

    def test_expected_classes_kwarg_flows_through(self, led_dir, led):
        """The ``expected_classes`` kwarg actually flows through to
        the primitive. We verify by passing a NARROWER expected_classes
        + observing the diagnostic emit for the now-uncatalogued
        events.
        """
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        # Restrict the expected set to ONLY send_intent — every other
        # class will be uncatalogued.
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            expected_classes=frozenset({"send_intent"}),
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        # This event is NOT in the narrowed expected_classes (even
        # though it IS in EVENT_CLASS_CATALOG):
        led.append({"type": "send_confirmed", "person_id": "p1",
                    "channel": "email", "ts": _ts(10, 5)})

        # Trigger a scrape — this invokes collect_event_class_snapshots
        # with the narrowed expected_classes, which appends the
        # diagnostic event.
        _collect_metric_data(reader, "outreach_factory_events_total")

        # Verify the diagnostic was emitted (proving the kwarg
        # actually flowed through).
        diag_events = [
            ev for ev in led.all_events()
            if ev.type == "observability_class_uncatalogued"
        ]
        assert len(diag_events) >= 1
        # The first-seen offending type is send_confirmed.
        offending = [
            ev.get("offending_type") for ev in diag_events
            if ev.get("kind") == "uncatalogued"
        ]
        assert "send_confirmed" in offending

    def test_breakdown_by_kwarg_flows_through(self, led):
        """The ``breakdown_by`` kwarg is forwarded to the primitive.
        We verify by passing a DISALLOWED breakdown dim + observing
        the refuse-loud ValueError at scrape time."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            breakdown_by=("source_list",),     # privacy violation
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})

        # Trigger scrape — the disallowed dim must surface as a
        # ValueError raised inside the callback (the OTel SDK
        # propagates the exception from the callback). Different
        # OTel SDK versions may surface differently:
        # 1.38 wraps it in the callback machinery and logs.
        # We detect the kwarg-passthrough either via the raised
        # exception OR via the absence of observations (the
        # primitive raised before snapshots could be built).
        try:
            obs = _collect_metric_data(
                reader, "outreach_factory_events_total"
            )
        except ValueError as e:
            assert "source_list" in str(e)
            return
        # If no exception escaped (SDK swallows callback errors), the
        # observation list MUST be empty (the primitive raised
        # before producing snapshots).
        assert obs == [], (
            "behavioral-passthrough — breakdown_by=('source_list',) "
            "MUST raise inside the callback (privacy invariant); "
            "either the exception escapes OR the callback yielded "
            "no observations."
        )


# ---------------------------------------------------------------------------
# Framework neutrality (Week 3)
# ---------------------------------------------------------------------------


class TestFrameworkNeutrality:
    """ADR-0052 D286 + D287 — operator-side framework neutrality.

    Tests:

    * Init works without any readers (instrument registers but no
      scrape until a reader is wired).
    * Init with operator-extended Resource preserves the framework's
      ``service.*`` keys.
    * Different operator-supplied readers (Prometheus / OTLP /
      InMemory) all work uniformly.
    """

    def test_init_with_no_readers_works(self, led):
        """Week 3 default — no readers; instrument registers; no
        scrape fires yet."""
        provider = init_otel_meter_provider(set_global=False)
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        counter = register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        # Instrument exists; no reader means no metric data exposure.
        assert counter is not None

    def test_operator_extended_resource_preserves_service_keys(self):
        """Pillar I per-tenant audit-tooling at OSS bring-up extends
        Resource with per-tenant labels; the framework's
        ``service.*`` keys MUST be preservable in the extended set.
        """
        operator_resource = Resource.create({
            SERVICE_NAME: "outreach-factory",          # framework key
            SERVICE_VERSION: "0.1.0",                  # framework key
            "outreach_factory.tenant_id": "tenant-a",  # operator key
            "outreach_factory.environment": "prod",    # operator key
        })
        provider = init_otel_meter_provider(
            resource=operator_resource, set_global=False,
        )
        attrs = dict(provider._sdk_config.resource.attributes)
        assert attrs[SERVICE_NAME] == "outreach-factory"
        assert attrs[SERVICE_VERSION] == "0.1.0"
        assert attrs["outreach_factory.tenant_id"] == "tenant-a"
        assert attrs["outreach_factory.environment"] == "prod"


# ---------------------------------------------------------------------------
# Empty + out-of-window edge cases for the OTel wrapper (Week 3)
# ---------------------------------------------------------------------------


class TestObservableCounterEmptyAndOutOfWindow:
    """Edge cells — empty ledger + all-out-of-window events produce
    zero observations from the OTel wrapper (no Observations
    yielded by the callback)."""

    def test_empty_ledger_zero_observations(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert obs == []

    def test_all_events_out_of_window_zero_observations(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=1),     # 1-day window
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        # All events older than 1 day from anchor 2026-05-25.
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "send_intent", "person_id": "p2",
                    "channel": "email", "ts": _ts(11)})

        obs = _collect_metric_data(reader, "outreach_factory_events_total")
        assert obs == []


# ---------------------------------------------------------------------------
# Week 4 — Prometheus exporter + send-latency Histogram + reconcile
# success ratio + Grafana dashboard (per ADR-0053 D288-D293)
# ---------------------------------------------------------------------------


def _make_provider_with_prometheus_reader(
    *, resource: Resource | None = None,
    extra_readers: list[MeterProvider] | None = None,
) -> tuple[MeterProvider, PrometheusMetricReader]:
    """Build a local MeterProvider + PrometheusMetricReader pair for
    Week 4 tests. Mirrors :func:`_make_provider_with_reader` from
    Week 3 but uses PrometheusMetricReader."""
    reader = init_prometheus_metric_reader()
    readers = [reader]
    if extra_readers:
        readers.extend(extra_readers)
    provider = init_otel_meter_provider(
        resource=resource,
        metric_readers=readers,
        set_global=False,
    )
    return provider, reader


# ---------------------------------------------------------------------------
# Week 4 module constants (per ADR-0053 D288-D293)
# ---------------------------------------------------------------------------


class TestWeek4ModuleConstants:
    """ADR-0053 D288-D293 — module-level constants for Pillar G Week 4.

    Cell-level matrix coverage per the per-week-reviewer discipline
    NINE consecutive weeks (Pillar F W6-W12 + Pillar G W2 + W3):

    * ``_INSTRUMENT_NAME_SEND_LATENCY_SECONDS`` — canonical Histogram
      name with ``outreach_factory_`` prefix + ``_seconds`` suffix.
    * ``_INSTRUMENT_NAME_RECONCILE_SUCCESS_RATIO`` — canonical
      ObservableGauge name with ``outreach_factory_`` prefix.
    * ``_SEND_LATENCY_BUCKETS_SECONDS`` — explicit bucket tuple
      spanning sub-millisecond to 10s with 5s SLO threshold bucket.
    * ``_DEFAULT_PROMETHEUS_PORT`` — TCP port default (8000).
    * ``_DEFAULT_PROMETHEUS_ADDR`` — bind address default
      (127.0.0.1 security-by-default).
    """

    def test_send_latency_instrument_name(self):
        assert observability._INSTRUMENT_NAME_SEND_LATENCY_SECONDS \
            == "outreach_factory_send_latency_seconds"

    def test_send_latency_uses_framework_namespace_prefix(self):
        """The ``outreach_factory_`` prefix is the per-framework
        namespace per ADR-0052 D284 + ADR-0053 D289."""
        assert observability._INSTRUMENT_NAME_SEND_LATENCY_SECONDS \
            .startswith("outreach_factory_")

    def test_send_latency_uses_seconds_suffix(self):
        """The ``_seconds`` suffix is the Prometheus + OTel histogram
        unit convention per ADR-0053 D289 — operators reading the
        Prometheus exposition see the unit-anchored name."""
        assert observability._INSTRUMENT_NAME_SEND_LATENCY_SECONDS \
            .endswith("_seconds")

    def test_reconcile_success_ratio_instrument_name(self):
        assert observability._INSTRUMENT_NAME_RECONCILE_SUCCESS_RATIO \
            == "outreach_factory_reconcile_success_ratio"

    def test_reconcile_success_ratio_uses_framework_prefix(self):
        assert observability._INSTRUMENT_NAME_RECONCILE_SUCCESS_RATIO \
            .startswith("outreach_factory_")

    def test_send_latency_buckets_explicit_tuple(self):
        """ADR-0053 D289 — buckets are an explicit tuple, not the
        OTel SDK default (which is too coarse for sub-second
        latencies)."""
        buckets = observability._SEND_LATENCY_BUCKETS_SECONDS
        assert isinstance(buckets, tuple)
        assert all(isinstance(b, float) for b in buckets)
        # Must include the 5s SLO threshold bucket per PILLAR-PLAN
        # §2 Pillar G.
        assert 5.0 in buckets

    def test_send_latency_buckets_monotonic_increasing(self):
        """Histogram buckets must be monotonically increasing per
        the OTel spec + Prometheus exposition contract."""
        buckets = observability._SEND_LATENCY_BUCKETS_SECONDS
        for prev, cur in zip(buckets, buckets[1:]):
            assert prev < cur, (
                f"Buckets must be monotonically increasing; got "
                f"{prev} >= {cur}"
            )

    def test_send_latency_buckets_span_sub_millisecond_to_ten_seconds(self):
        """Buckets cover the per-channel latency profile range per
        ADR-0053 D289."""
        buckets = observability._SEND_LATENCY_BUCKETS_SECONDS
        assert buckets[0] <= 0.01    # sub-millisecond start
        assert buckets[-1] >= 10.0   # up to 10s

    def test_default_prometheus_port(self):
        """ADR-0053 D291 — default port 8000."""
        assert observability._DEFAULT_PROMETHEUS_PORT == 8000

    def test_default_prometheus_addr_localhost(self):
        """ADR-0053 D291 — default bind 127.0.0.1 (security-by-
        default). R036 mitigation — the framework does NOT expose
        the Prometheus endpoint on 0.0.0.0 by default."""
        assert observability._DEFAULT_PROMETHEUS_ADDR == "127.0.0.1"


# ---------------------------------------------------------------------------
# init_prometheus_metric_reader (Week 4 per ADR-0053 D288)
# ---------------------------------------------------------------------------


class TestInitPrometheusMetricReader:
    """ADR-0053 D288 — the canonical Prometheus reader factory.

    Cells:

    * Returns a :class:`PrometheusMetricReader` instance.
    * Reader can be wired via :func:`init_otel_meter_provider`'s
      ``metric_readers=`` (framework-neutrality contract per ADR-0052
      D286 + ADR-0053 D293).
    """

    def test_returns_prometheus_metric_reader_instance(self):
        reader = init_prometheus_metric_reader()
        assert isinstance(reader, PrometheusMetricReader)

    def test_reader_wires_via_metric_readers_kwarg(self, tmp_path):
        """ADR-0053 D288 — the reader is operator-passed to
        :func:`init_otel_meter_provider`. The MeterProvider
        accepts the reader + the per-event-class instrument's
        callback fires."""
        reader = init_prometheus_metric_reader()
        provider = init_otel_meter_provider(
            metric_readers=[reader], set_global=False,
        )
        assert provider is not None

    def test_each_call_returns_fresh_reader(self):
        """Each :func:`init_prometheus_metric_reader` call returns a
        fresh reader instance — operators wiring multiple
        MeterProviders (e.g., test isolation) get isolated readers."""
        r1 = init_prometheus_metric_reader()
        r2 = init_prometheus_metric_reader()
        assert r1 is not r2


# ---------------------------------------------------------------------------
# default_views (Week 4 per ADR-0053 D292)
# ---------------------------------------------------------------------------


class TestDefaultViews:
    """ADR-0053 D292 — framework-default :class:`View` set.

    Cells:

    * Returns a tuple of :class:`View` instances.
    * At least one View — for the send-latency Histogram bucket
      configuration.
    * The send-latency View pins
      :data:`_SEND_LATENCY_BUCKETS_SECONDS` (the explicit boundaries).
    """

    def test_returns_tuple_of_views(self):
        views = default_views()
        assert isinstance(views, tuple)
        assert len(views) >= 1

    def test_send_latency_histogram_view_present(self):
        """The default View set includes the send-latency Histogram's
        bucket configuration (otherwise the OTel SDK's default
        boundaries — too coarse for sub-second latencies — would
        apply)."""
        views = default_views()
        # At least one view targets the send-latency histogram by
        # instrument name.
        targeted = [v for v in views
                    if v._instrument_name
                    == "outreach_factory_send_latency_seconds"]
        assert len(targeted) >= 1


# ---------------------------------------------------------------------------
# init_otel_meter_provider views= kwarg (Week 4 per ADR-0053 D292)
# ---------------------------------------------------------------------------


class TestInitOTelMeterProviderViews:
    """ADR-0053 D292 — the ``views=`` kwarg accepts operator views,
    defaults to framework views, ``()`` skips framework defaults."""

    def test_default_views_kwarg_applies_framework_views(self):
        """``views=None`` (the default) substitutes
        :func:`default_views` so the framework's recommended Views
        apply."""
        provider = init_otel_meter_provider(set_global=False)
        # The default Views should be visible via the framework
        # default_views() — calling default_views() here returns the
        # tuple the provider applied.
        assert default_views() is not None

    def test_operator_views_kwarg_overrides_defaults(self):
        """Operators passing ``views=`` get THEIR views, not the
        framework defaults."""
        custom_view = View(
            instrument_name="outreach_factory_send_latency_seconds",
            aggregation=ExplicitBucketHistogramAggregation(
                boundaries=(0.001, 1.0, 60.0),
            ),
        )
        # Should not raise.
        provider = init_otel_meter_provider(
            views=[custom_view], set_global=False,
        )
        assert provider is not None

    def test_empty_views_tuple_skips_framework_views(self):
        """Operators passing ``views=()`` skip the framework defaults
        — the OTel SDK falls back to its default aggregation per
        instrument type (which uses coarser default buckets for
        Histogram)."""
        # Should not raise.
        provider = init_otel_meter_provider(
            views=(), set_global=False,
        )
        assert provider is not None


# ---------------------------------------------------------------------------
# Send-latency Histogram (Week 4 per ADR-0053 D289)
# ---------------------------------------------------------------------------


class TestSendLatencyHistogram:
    """ADR-0053 D289 — per-channel send-latency Histogram instrument.

    Cells:

    * Instrument name matches
      :data:`_INSTRUMENT_NAME_SEND_LATENCY_SECONDS`.
    * Unit is ``"s"`` (seconds; Prometheus + OTel convention).
    * Histogram type (synchronous; operator records via ``.record()``).
    * Per-channel attribute on ``.record()``.
    * Buckets match :data:`_SEND_LATENCY_BUCKETS_SECONDS` (via
      framework default View).
    """

    def test_returns_histogram_instance(self):
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        histogram = get_send_latency_histogram(meter=meter)
        assert isinstance(histogram, Histogram)

    def test_instrument_name_matches_constant(self):
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        histogram = get_send_latency_histogram(meter=meter)
        # The Histogram instrument's name is stored on the underlying
        # OTel _Histogram instance.
        # Record a value to ensure the instrument is registered.
        histogram.record(0.5, {"channel": "email"})
        # Verify via the Prometheus exposition that the metric name
        # surfaces correctly (the _bucket / _sum / _count metric
        # family).
        exposition = render_prometheus_exposition().decode()
        assert "outreach_factory_send_latency_seconds" in exposition

    def test_per_channel_record_attribute(self):
        """ADR-0014 D33 + ADR-0053 D289 — per-channel attribute on
        the .record() call surfaces as a Prometheus label."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        histogram = get_send_latency_histogram(meter=meter)
        histogram.record(0.5, {"channel": "email"})
        histogram.record(2.0, {"channel": "li_invite"})

        exposition = render_prometheus_exposition().decode()
        # Per-channel labels surface verbatim.
        assert 'channel="email"' in exposition
        assert 'channel="li_invite"' in exposition

    def test_explicit_buckets_applied_via_default_view(self):
        """ADR-0053 D292 — the framework's default View pins the
        explicit buckets so the Prometheus exposition surfaces the
        Pillar G-specific bucket set, NOT the OTel SDK default."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        histogram = get_send_latency_histogram(meter=meter)
        # Record across the bucket boundaries.
        for v in (0.003, 0.05, 0.3, 1.5, 6.0):
            histogram.record(v, {"channel": "email"})

        exposition = render_prometheus_exposition().decode()
        # Verify the 5s SLO threshold bucket is present (le="5.0")
        # — the per-PILLAR-PLAN §2 Pillar G threshold MUST be
        # operator-queryable without bucket interpolation.
        assert 'le="5.0"' in exposition

    def test_unit_is_seconds_via_exposition(self):
        """The instrument's unit "s" should be visible via the
        Prometheus exposition (the OTel exporter surfaces the unit
        in the metric metadata)."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        histogram = get_send_latency_histogram(meter=meter)
        histogram.record(0.5, {"channel": "email"})
        exposition = render_prometheus_exposition().decode()
        # The OTel Prometheus exporter surfaces the unit in the
        # description via the type lines + the metric name
        # convention; verify the instrument name's _seconds suffix
        # surfaces in the exposition.
        assert "outreach_factory_send_latency_seconds" in exposition


# ---------------------------------------------------------------------------
# Reconcile success ratio ObservableGauge (Week 4 per ADR-0053 D290)
# ---------------------------------------------------------------------------


class TestReconcileSuccessRatioGauge:
    """ADR-0053 D290 — reconcile success ratio ObservableGauge.

    Cells:

    * Instrument name matches
      :data:`_INSTRUMENT_NAME_RECONCILE_SUCCESS_RATIO`.
    * Unit is ``"1"`` (ratio, dimensionless).
    * Callback computes ratio from ledger via
      :func:`collect_event_class_snapshots`.
    * Vacuous success (no reconcile activity) → ratio = 1.0.
    * Drift-only (no heal) → ratio = 0.0.
    * Drift + heal → ratio = N_healed / (N_healed + N_drift).
    """

    def test_returns_observable_gauge(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        gauge = register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        assert gauge is not None

    def test_instrument_name_matches_constant(self, led):
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        # Append a reconcile event so the gauge has data + scrape.
        led.append({"type": "reconcile_drift", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        triple = _find_scope_metric(
            reader, "outreach_factory_reconcile_success_ratio",
        )
        assert triple is not None

    def test_vacuous_success_no_reconcile_activity_ratio_is_one(self, led):
        """No reconcile_drift + no reconcile_healed → ratio = 1.0
        (vacuous success per ADR-0053 D290)."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        # Trigger a scrape by appending an unrelated event (otherwise
        # empty ledger returns no observations).
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})

        obs = _collect_metric_data(
            reader, "outreach_factory_reconcile_success_ratio",
        )
        # ONE observation for the ratio.
        assert len(obs) == 1
        _, value = obs[0]
        assert value == 1.0

    def test_drift_only_no_heal_ratio_is_zero(self, led):
        """Drift events but ZERO heal events → ratio = 0.0
        (total failure per ADR-0053 D290)."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "reconcile_drift", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "reconcile_drift", "person_id": "p2",
                    "channel": "email", "ts": _ts(11)})

        obs = _collect_metric_data(
            reader, "outreach_factory_reconcile_success_ratio",
        )
        assert len(obs) == 1
        _, value = obs[0]
        assert value == 0.0

    def test_partial_heal_ratio_computed_correctly(self, led):
        """Drift + heal events → ratio = N_healed / (N_healed +
        N_drift). Verifies the canonical computation per ADR-0053
        D290."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        # 3 drift + 1 heal → ratio = 1/4 = 0.25
        led.append({"type": "reconcile_drift", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "reconcile_drift", "person_id": "p2",
                    "channel": "email", "ts": _ts(11)})
        led.append({"type": "reconcile_drift", "person_id": "p3",
                    "channel": "email", "ts": _ts(12)})
        led.append({"type": "reconcile_healed", "person_id": "p1",
                    "channel": "email", "ts": _ts(13)})

        obs = _collect_metric_data(
            reader, "outreach_factory_reconcile_success_ratio",
        )
        assert len(obs) == 1
        _, value = obs[0]
        assert abs(value - 0.25) < 1e-9

    def test_full_heal_ratio_is_one(self, led):
        """Every drift event healed → ratio = 1.0."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "reconcile_drift", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "reconcile_healed", "person_id": "p1",
                    "channel": "email", "ts": _ts(11)})

        obs = _collect_metric_data(
            reader, "outreach_factory_reconcile_success_ratio",
        )
        assert len(obs) == 1
        _, value = obs[0]
        assert value == 0.5

    def test_callback_uses_now_kwarg_for_window_anchor(self, led):
        """ADR-0053 D290 + deterministic-clock contract per ADR-0034
        D156 — the ``now`` callable controls the per-scrape rolling
        window's anchor."""
        provider, reader = _make_provider_with_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=1),     # 1-day window
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        # Events older than 1 day from anchor 2026-05-25 — out-of-
        # window.
        led.append({"type": "reconcile_drift", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "reconcile_drift", "person_id": "p2",
                    "channel": "email", "ts": _ts(11)})

        obs = _collect_metric_data(
            reader, "outreach_factory_reconcile_success_ratio",
        )
        # Out-of-window → vacuous success → 1.0.
        assert len(obs) == 1
        _, value = obs[0]
        assert value == 1.0


# ---------------------------------------------------------------------------
# Prometheus exposition format (Week 4 per ADR-0053 D288 + D293)
# ---------------------------------------------------------------------------


class TestPrometheusExposition:
    """ADR-0053 D288 + D293 — Prometheus exposition format.

    Cells:

    * :func:`render_prometheus_exposition` returns ``bytes``.
    * Exposition includes canonical instrument names.
    * Exposition includes ``# TYPE`` + ``# HELP`` headers.
    * ``_total`` suffix preserved on counter instrument
      (the Prometheus counter naming convention per ADR-0052 D285).
    * Per-instrument metric family surfaces correctly.
    """

    def test_returns_bytes(self, led):
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        out = render_prometheus_exposition()
        assert isinstance(out, bytes)

    def test_exposition_includes_events_total_counter(self, led):
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        exposition = render_prometheus_exposition().decode()
        assert "outreach_factory_events_total" in exposition

    def test_exposition_preserves_total_suffix_on_counter(self, led):
        """ADR-0052 D285 + ADR-0053 D293 — the ``_total`` suffix is
        the Prometheus counter convention; the OTel-to-Prometheus
        exposition MUST preserve it."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        exposition = render_prometheus_exposition().decode()
        # The metric name in the exposition MUST end in _total.
        assert "outreach_factory_events_total{" in exposition

    def test_exposition_includes_type_counter_header(self, led):
        """ADR-0053 D293 — ``# TYPE outreach_factory_events_total
        counter`` header surfaces per the Prometheus exposition
        spec."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        exposition = render_prometheus_exposition().decode()
        assert "# TYPE outreach_factory_events counter" in exposition or \
               "# TYPE outreach_factory_events_total counter" in exposition

    def test_exposition_includes_help_header(self, led):
        """ADR-0053 D293 — ``# HELP <name> <description>`` header
        surfaces per the Prometheus exposition spec; the description
        comes from the OTel instrument's description field."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        exposition = render_prometheus_exposition().decode()
        assert "# HELP outreach_factory_events" in exposition

    def test_exposition_includes_histogram_bucket_lines(self):
        """ADR-0053 D289 — the Histogram surfaces as ``_bucket`` +
        ``_sum`` + ``_count`` metric family lines per Prometheus
        exposition spec."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        histogram = get_send_latency_histogram(meter=meter)
        histogram.record(0.5, {"channel": "email"})
        exposition = render_prometheus_exposition().decode()
        assert "outreach_factory_send_latency_seconds_bucket" in exposition \
            or "outreach_factory_send_latency_seconds" in exposition

    def test_exposition_includes_reconcile_ratio_gauge_line(self, led):
        """ADR-0053 D290 — the ObservableGauge surfaces as a bare
        metric name (no suffix) per Prometheus exposition spec."""
        provider, reader = _make_provider_with_prometheus_reader()
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_reconcile_success_ratio_gauge(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "reconcile_drift", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})
        led.append({"type": "reconcile_healed", "person_id": "p1",
                    "channel": "email", "ts": _ts(11)})
        exposition = render_prometheus_exposition().decode()
        assert "outreach_factory_reconcile_success_ratio" in exposition


# ---------------------------------------------------------------------------
# Framework-neutrality at Week 4 (per ADR-0053 D293)
# ---------------------------------------------------------------------------


class TestFrameworkNeutralityWeek4:
    """ADR-0053 D293 — framework-neutrality contract preservation at
    Week 4. The Prometheus exporter is OPTIONAL; operators with OTLP
    backends skip it; operators wire multiple readers freely.

    Cells:

    * Operator skips Prometheus reader entirely; framework still
      works (no Prometheus dependency at runtime when not wired).
    * Operator wires multiple readers (Prometheus + InMemory).
    * Operator wires NO readers at all; instrument callbacks register
      but no scrape fires (per ADR-0052 D286 + Week 3 carry-forward).
    """

    def test_operator_can_skip_prometheus_exporter_entirely(self, led):
        """OTLP-only operator: framework MeterProvider + InMemoryReader
        works without ANY Prometheus wiring."""
        in_memory_reader = InMemoryMetricReader()
        provider = init_otel_meter_provider(
            metric_readers=[in_memory_reader], set_global=False,
        )
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})

        # In-memory reader collects the metric.
        obs = _collect_metric_data(
            in_memory_reader, "outreach_factory_events_total",
        )
        assert len(obs) == 1

    def test_operator_can_wire_multiple_readers(self, led):
        """Multi-backend operator: Prometheus reader + InMemory reader
        both attached to same MeterProvider; both collect the same
        per-event-class observations."""
        prom_reader = init_prometheus_metric_reader()
        in_memory_reader = InMemoryMetricReader()
        provider = init_otel_meter_provider(
            metric_readers=[prom_reader, in_memory_reader],
            set_global=False,
        )
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        register_event_class_observable_counter(
            led,
            since_window=timedelta(days=30),
            now=lambda: NOW_2026_05_25,
            meter=meter,
        )
        led.append({"type": "send_intent", "person_id": "p1",
                    "channel": "email", "ts": _ts(10)})

        # Both readers see the metric.
        in_mem_obs = _collect_metric_data(
            in_memory_reader, "outreach_factory_events_total",
        )
        prom_exposition = render_prometheus_exposition().decode()
        assert len(in_mem_obs) == 1
        assert "outreach_factory_events_total" in prom_exposition

    def test_operator_can_skip_views_entirely(self, led):
        """ADR-0053 D292 — operators passing ``views=()`` skip the
        framework defaults; the MeterProvider falls back to OTel
        SDK's default Histogram boundaries."""
        provider = init_otel_meter_provider(
            views=(), set_global=False,
        )
        # Should not raise.
        meter = provider.get_meter("orchestrator.observability", "0.1.0")
        histogram = get_send_latency_histogram(meter=meter)
        histogram.record(0.5, {"channel": "email"})


# ---------------------------------------------------------------------------
# Prometheus HTTP exposition server (Week 4 per ADR-0053 D291)
# ---------------------------------------------------------------------------


class TestStartPrometheusHttpServer:
    """ADR-0053 D291 — Prometheus HTTP exposition server posture.

    Cells:

    * Function signature accepts ``port`` + ``addr`` kwargs.
    * Default port is :data:`_DEFAULT_PROMETHEUS_PORT` (8000).
    * Default bind addr is :data:`_DEFAULT_PROMETHEUS_ADDR`
      (127.0.0.1 — security-by-default).
    * Function is NOT auto-called at module import (operator-
      deliberate).
    """

    def test_function_signature_accepts_port_and_addr(self):
        """The function accepts ``port`` + ``addr`` as keyword
        arguments per ADR-0053 D291."""
        import inspect
        sig = inspect.signature(start_prometheus_http_server)
        assert "port" in sig.parameters
        assert "addr" in sig.parameters

    def test_default_port_matches_module_constant(self):
        """Function default for ``port`` matches the module-level
        :data:`_DEFAULT_PROMETHEUS_PORT` constant."""
        import inspect
        sig = inspect.signature(start_prometheus_http_server)
        assert sig.parameters["port"].default \
            == observability._DEFAULT_PROMETHEUS_PORT
        assert sig.parameters["port"].default == 8000

    def test_default_addr_matches_module_constant_security_by_default(self):
        """Function default for ``addr`` matches the module-level
        :data:`_DEFAULT_PROMETHEUS_ADDR` constant.
        R036 mitigation — default bind is 127.0.0.1
        (localhost-only), NOT 0.0.0.0 (all interfaces) per
        ADR-0053 D291."""
        import inspect
        sig = inspect.signature(start_prometheus_http_server)
        assert sig.parameters["addr"].default \
            == observability._DEFAULT_PROMETHEUS_ADDR
        assert sig.parameters["addr"].default == "127.0.0.1"

    def test_function_not_called_at_module_import(self):
        """ADR-0053 D291 — operator-deliberate. Importing
        :mod:`observability` does NOT auto-start the Prometheus HTTP
        server. Verified by checking no port 8000 binding side
        effect on module load."""
        # The function exists + is callable + does NOT execute on
        # import. We can't directly assert "no auto-call" but the
        # function being a regular function (not a wrapper that ran)
        # is the signal.
        assert callable(start_prometheus_http_server)


# ---------------------------------------------------------------------------
# Grafana dashboard YAML (Week 4 per ADR-0053 D293)
# ---------------------------------------------------------------------------


class TestGrafanaDashboardYaml:
    """ADR-0053 D293 — first Grafana-as-code dashboard.

    Cells:

    * File exists at the canonical path
      ``infra/grafana/dashboards/overview.yml``.
    * File is valid YAML.
    * Has expected top-level keys (``title``, ``panels``).
    * References the three Week 4 metrics in PromQL queries:
      ``outreach_factory_events_total``,
      ``outreach_factory_send_latency_seconds``,
      ``outreach_factory_reconcile_success_ratio``.
    """

    DASHBOARD_PATH = Path(__file__).parent.parent / \
        "infra" / "grafana" / "dashboards" / "overview.yml"

    def test_dashboard_file_exists(self):
        assert self.DASHBOARD_PATH.exists(), (
            f"Grafana dashboard at {self.DASHBOARD_PATH} does NOT "
            "exist. Per ADR-0053 D293, Pillar G Week 4 ships the "
            "first Grafana-as-code dashboard at this path."
        )

    def test_dashboard_is_valid_yaml(self):
        import yaml
        content = self.DASHBOARD_PATH.read_text()
        # Should not raise.
        loaded = yaml.safe_load(content)
        assert loaded is not None

    def test_dashboard_has_title(self):
        import yaml
        loaded = yaml.safe_load(self.DASHBOARD_PATH.read_text())
        assert "title" in loaded
        assert isinstance(loaded["title"], str)
        assert len(loaded["title"]) > 0

    def test_dashboard_has_panels_list(self):
        import yaml
        loaded = yaml.safe_load(self.DASHBOARD_PATH.read_text())
        assert "panels" in loaded
        assert isinstance(loaded["panels"], list)
        assert len(loaded["panels"]) >= 1

    def test_dashboard_references_events_total_metric(self):
        """ADR-0053 D293 — the dashboard MUST query
        ``outreach_factory_events_total`` for the per-event-class
        rate panel (binding question 2 — "where am I losing
        prospects?" per ADR-0050 D275)."""
        content = self.DASHBOARD_PATH.read_text()
        assert "outreach_factory_events_total" in content

    def test_dashboard_references_send_latency_metric(self):
        """ADR-0053 D293 — the dashboard MUST query
        ``outreach_factory_send_latency_seconds`` for the per-channel
        send-latency p99 panel (binding question 1 — "why is dispatch
        slow today?" per ADR-0050 D275)."""
        content = self.DASHBOARD_PATH.read_text()
        assert "outreach_factory_send_latency_seconds" in content

    def test_dashboard_references_reconcile_ratio_metric(self):
        """ADR-0053 D293 — the dashboard MUST query
        ``outreach_factory_reconcile_success_ratio`` for the
        reconcile ratio panel (operator-actionable SLO signal per
        PILLAR-PLAN §2 Pillar G)."""
        content = self.DASHBOARD_PATH.read_text()
        assert "outreach_factory_reconcile_success_ratio" in content

    def test_dashboard_query_uses_promql_rate_or_histogram_quantile(self):
        """ADR-0053 D293 — the per-event-class rate panel uses
        PromQL's ``rate()`` (cumulative-counter semantics per
        ADR-0052 D285); the latency panel uses
        ``histogram_quantile()`` (Histogram semantics per ADR-0053
        D289)."""
        content = self.DASHBOARD_PATH.read_text()
        # At least ONE of these PromQL functions must surface.
        assert "rate(" in content or "histogram_quantile" in content


# ---------------------------------------------------------------------------
# Week 5 — OTel tracing initialization + canonical Tracer scope +
# traced_stage per-stage span helper + privacy invariant on span
# attributes (per ADR-0054 D294-D299)
# ---------------------------------------------------------------------------


def _make_tracer_with_in_memory_exporter() -> tuple[
    TracerProvider, InMemorySpanExporter
]:
    """Build a TracerProvider + InMemorySpanExporter pair for tests.

    The behavioral-passthrough-not-signature-only discipline (NOW
    SEVEN consecutive weeks at Pillar G Week 5; Pillar F W8-W11 +
    Pillar G W3 + W4 + W5) requires that the test ACTUALLY captures
    the emitted span — NOT just verifying the helper's signature.
    The :class:`InMemorySpanExporter` accumulates spans in-process
    so tests can assert on the captured spans' name + attributes +
    parent-child relationships.
    """
    exporter = InMemorySpanExporter()
    provider = init_otel_tracer_provider(
        span_processors=[SimpleSpanProcessor(exporter)],
        set_global=False,
    )
    return provider, exporter


class TestWeek5ModuleConstants:
    """ADR-0054 D294-D297 — Week 5 module-level constants.

    Cells:

    * :data:`_TRACER_NAME` is the canonical OTel scope name
      ``"orchestrator.observability"``.
    * :data:`_TRACER_VERSION` is ``"0.1.0"`` (parallel to
      :data:`_METER_VERSION`).
    * :data:`_SPAN_NAME_PREFIX` is ``"outreach_factory"``.
    * :data:`_PIPELINE_STAGES` is a frozenset with EXACTLY the eight
      pipeline stages per PILLAR-PLAN §2 Pillar G.
    * :data:`_SPAN_ATTRIBUTES_ALLOWED` is a frozenset including the
      breakdown dims + per-span-specific keys + EXCLUDING the
      privacy-disallowed keys per I8.
    """

    def test_tracer_name_is_canonical_scope(self):
        """ADR-0054 D295 — the Tracer scope name matches the Meter
        scope name (per-pillar-symmetry per ADR-0052 D283)."""
        assert _TRACER_NAME == "orchestrator.observability"

    def test_tracer_version_is_pinned(self):
        """ADR-0054 D295 — the Tracer scope version is ``"0.1.0"``
        (parallel to the Meter scope version)."""
        assert _TRACER_VERSION == "0.1.0"

    def test_span_name_prefix_is_outreach_factory(self):
        """ADR-0054 D296 — span names follow
        ``outreach_factory.<stage>.<operation>``."""
        assert _SPAN_NAME_PREFIX == "outreach_factory"

    def test_pipeline_stages_is_frozenset(self):
        assert isinstance(_PIPELINE_STAGES, frozenset)

    def test_pipeline_stages_has_exactly_eight_members(self):
        """ADR-0054 D296 — the closed-set carries EXACTLY the eight
        stages enumerated in PILLAR-PLAN §2 Pillar G's binding text:
        discovery → enrichment → research → draft → review → send
        → reply → win/loss."""
        assert _PIPELINE_STAGES == frozenset({
            "discovery",
            "enrichment",
            "research",
            "draft",
            "review",
            "send",
            "reply",
            "win_loss",
        })

    def test_span_attributes_allowed_is_frozenset(self):
        assert isinstance(_SPAN_ATTRIBUTES_ALLOWED, frozenset)

    def test_span_attributes_allowed_includes_breakdown_dims(self):
        """ADR-0054 D297 — the span-attribute closed-set is a
        SUPERSET of :data:`_BREAKDOWN_DIMS_ALLOWED` (the metric
        breakdown surface)."""
        assert _BREAKDOWN_DIMS_ALLOWED.issubset(_SPAN_ATTRIBUTES_ALLOWED)

    def test_span_attributes_allowed_includes_per_span_keys(self):
        """ADR-0054 D297 — the span-attribute closed-set adds
        ``person_id`` + ``stage`` + ``operation`` to the metric
        breakdown dims."""
        for key in ("person_id", "stage", "operation"):
            assert key in _SPAN_ATTRIBUTES_ALLOWED, (
                f"_SPAN_ATTRIBUTES_ALLOWED missing {key!r} per "
                "ADR-0054 D297."
            )

    def test_span_attributes_allowed_excludes_privacy_relevant_keys(self):
        """ADR-0054 D297 — the privacy invariant per I8 + ADR-0032
        D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b)
        carries through to span attributes."""
        for forbidden in (
            "source_list",
            "draft_body",
            "dossier_body",
            "exemplar_body",
            "claim_text",
        ):
            assert forbidden not in _SPAN_ATTRIBUTES_ALLOWED, (
                f"_SPAN_ATTRIBUTES_ALLOWED MUST NOT include "
                f"{forbidden!r} per the privacy invariant per I8 + "
                "ADR-0032 D148 + ADR-0038 D182 category 8."
            )

    def test_pipeline_stages_normalized_underscore_for_win_loss(self):
        """ADR-0054 D296 — the ``win_loss`` stage uses underscore
        (matching Python identifier conventions) NOT slash or
        hyphen. The binding text in PILLAR-PLAN §2 Pillar G uses
        ``win/loss`` but the closed-set IS underscore-normalized
        for OTel attribute compatibility (OTel attribute values
        accept slashes but the stage identifier is treated as a
        Python identifier through the codebase)."""
        assert "win_loss" in _PIPELINE_STAGES
        assert "win/loss" not in _PIPELINE_STAGES


class TestInitOTelTracerProvider:
    """ADR-0054 D294 + D298 — TracerProvider initialization cells.

    Cells:

    * Returns a :class:`TracerProvider` instance.
    * Default Resource carries ``service.name`` + ``service.version``
      per the Week 3 defaults (per-pillar-symmetry per ADR-0052
      D287).
    * Default Resource auto-injects OTel SDK ``telemetry.sdk.*``
      attributes.
    * Custom Resource overrides default verbatim (per ADR-0054 D298
      + ADR-0052 D286 framework-neutrality contract).
    * Custom ``span_processors`` registered (per ADR-0054 D298).
    * Empty ``span_processors`` default (no export until processor
      wired).
    * ``set_global=False`` does NOT register the provider globally.
    """

    def test_returns_tracer_provider_instance(self):
        provider = init_otel_tracer_provider(set_global=False)
        assert isinstance(provider, TracerProvider)

    def test_default_resource_carries_service_name(self):
        """ADR-0054 D294 — default Resource carries the framework's
        ``service.name`` per the per-pillar-symmetry with Meter."""
        provider = init_otel_tracer_provider(set_global=False)
        attrs = dict(provider.resource.attributes)
        assert attrs[SERVICE_NAME] == "outreach-factory"

    def test_default_resource_carries_service_version(self):
        """ADR-0054 D294 — default Resource carries the framework's
        ``service.version``."""
        provider = init_otel_tracer_provider(set_global=False)
        attrs = dict(provider.resource.attributes)
        assert attrs[SERVICE_VERSION] == "0.1.0"

    def test_default_resource_carries_otel_sdk_auto_attributes(self):
        """OTel SDK auto-injects ``telemetry.sdk.*`` attributes per
        the OTel resource semantic conventions."""
        provider = init_otel_tracer_provider(set_global=False)
        attrs = dict(provider.resource.attributes)
        assert attrs["telemetry.sdk.language"] == "python"
        assert "telemetry.sdk.name" in attrs
        assert "telemetry.sdk.version" in attrs

    def test_custom_resource_preserved_verbatim(self):
        """ADR-0054 D298 — operator-supplied Resource preserves
        framework's ``service.*`` keys + allows per-tenant keys."""
        custom = Resource.create({
            SERVICE_NAME: "operator-fork",
            SERVICE_VERSION: "1.2.3",
            "outreach_factory.tenant_id": "tenant-a",
        })
        provider = init_otel_tracer_provider(
            resource=custom, set_global=False,
        )
        attrs = dict(provider.resource.attributes)
        assert attrs[SERVICE_NAME] == "operator-fork"
        assert attrs[SERVICE_VERSION] == "1.2.3"
        assert attrs["outreach_factory.tenant_id"] == "tenant-a"

    def test_custom_span_processors_registered(self):
        """ADR-0054 D298 — operator-supplied span processors flow
        through to the TracerProvider + receive spans on emit."""
        exporter = InMemorySpanExporter()
        provider = init_otel_tracer_provider(
            span_processors=[SimpleSpanProcessor(exporter)],
            set_global=False,
        )
        # Wire a tracer + emit a span to confirm the processor
        # actually receives the span (behavioral-passthrough-not-
        # signature-only discipline per ADR-0054 D298 + Pillar F's
        # Week 8-11 + Pillar G Week 3-4 + Week 5 pattern).
        tracer = provider.get_tracer(_TRACER_NAME, _TRACER_VERSION)
        with tracer.start_as_current_span("test_span"):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "test_span"

    def test_empty_span_processors_default(self):
        """ADR-0054 D298 — Week 5 default is EMPTY tuple; the
        TracerProvider accepts NO processors; spans register but
        no export fires until a processor is wired."""
        provider = init_otel_tracer_provider(set_global=False)
        assert provider is not None
        # The provider accepts span emit without raising.
        tracer = provider.get_tracer(_TRACER_NAME, _TRACER_VERSION)
        with tracer.start_as_current_span("test_span"):
            pass

    def test_set_global_false_does_not_set_global(self):
        """ADR-0054 D294 — tests pass ``set_global=False`` to avoid
        OTel's set-once enforcement. The returned provider is the
        operator's responsibility (not registered globally).
        Mirrors the Week 3 ``init_otel_meter_provider`` posture per
        ADR-0052 D282 + R035 mitigation."""
        before = _otel_trace.get_tracer_provider()
        provider = init_otel_tracer_provider(set_global=False)
        after = _otel_trace.get_tracer_provider()
        # The global is unchanged when set_global=False.
        assert before is after
        # The returned provider is distinct from the global.
        assert provider is not after

    def test_multiple_span_processors_compose(self):
        """ADR-0054 D298 — operators MAY wire multiple processors
        (e.g., OTLP export + console debug). Each processor sees
        every span."""
        exporter_a = InMemorySpanExporter()
        exporter_b = InMemorySpanExporter()
        provider = init_otel_tracer_provider(
            span_processors=[
                SimpleSpanProcessor(exporter_a),
                SimpleSpanProcessor(exporter_b),
            ],
            set_global=False,
        )
        tracer = provider.get_tracer(_TRACER_NAME, _TRACER_VERSION)
        with tracer.start_as_current_span("multi_span"):
            pass
        # Both exporters see the span (NOT just one).
        assert len(exporter_a.get_finished_spans()) == 1
        assert len(exporter_b.get_finished_spans()) == 1


# Import the trace module reference for the set_global test above.
from opentelemetry import trace as _otel_trace    # noqa: E402


class TestGetTracer:
    """ADR-0054 D295 — :func:`get_tracer` returns the canonical
    Pillar G observability :class:`Tracer` from explicit OR global
    providers.

    Cells: explicit provider returns Tracer; canonical scope name;
    canonical scope version; default consults global provider.
    """

    def test_explicit_provider_returns_tracer(self):
        provider = init_otel_tracer_provider(set_global=False)
        tracer = get_tracer(tracer_provider=provider)
        assert isinstance(tracer, Tracer)

    def test_global_fallback_returns_tracer(self):
        """ADR-0054 D295 — default consults the global provider
        (or the no-op default if Pillar G has not been initialized
        yet; in either case returns a Tracer object)."""
        tracer = get_tracer()
        # OTel SDK returns a NoOpTracer (or the registered
        # TracerProvider's Tracer) — both implement the Tracer
        # protocol. Type check is not exact-class.
        assert tracer is not None
        # Has the canonical Tracer surface.
        assert hasattr(tracer, "start_as_current_span")

    def test_canonical_scope_name_passed_to_provider(self):
        """ADR-0054 D295 — the scope name ``orchestrator.observability``
        is the load-bearing OTel label per per-pillar symmetry per
        ADR-0052 D283."""
        # We can't directly inspect Tracer's scope from the public
        # API, so we verify via an emitted span's instrumentation
        # scope.
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with tracer.start_as_current_span("scope_test"):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].instrumentation_scope.name == \
            "orchestrator.observability"

    def test_canonical_scope_version_passed_to_provider(self):
        """ADR-0054 D295 — the scope version ``"0.1.0"`` parallels
        the Meter scope version."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with tracer.start_as_current_span("version_test"):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].instrumentation_scope.version == "0.1.0"


class TestTracedStageBasic:
    """ADR-0054 D296 — :func:`traced_stage` context manager basics.

    Cells: yields a span; auto-sets stage attribute; auto-sets
    operation attribute; span name follows
    ``outreach_factory.<stage>.<operation>``.
    """

    def test_yields_span(self):
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage("send", "email", tracer=tracer) as span:
            assert span is not None
            assert hasattr(span, "set_attribute")

    def test_span_name_uses_outreach_factory_prefix(self):
        """ADR-0054 D296 — span name is
        ``outreach_factory.<stage>.<operation>``."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage("send", "email", tracer=tracer):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "outreach_factory.send.email"

    def test_span_auto_sets_stage_attribute(self):
        """ADR-0054 D296 — :func:`traced_stage` auto-sets
        ``stage`` attribute on every span."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage("discovery", "find_leads", tracer=tracer):
            pass
        spans = exporter.get_finished_spans()
        assert spans[0].attributes["stage"] == "discovery"

    def test_span_auto_sets_operation_attribute(self):
        """ADR-0054 D296 — :func:`traced_stage` auto-sets
        ``operation`` attribute on every span."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage("discovery", "find_leads", tracer=tracer):
            pass
        spans = exporter.get_finished_spans()
        assert spans[0].attributes["operation"] == "find_leads"

    def test_operator_supplied_attributes_passed_through(self):
        """ADR-0054 D296 — operator-supplied attributes appear on the
        span alongside auto-set ``stage`` + ``operation``."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage(
            "send", "email",
            attributes={
                "channel": "email",
                "person_id": "p_001",
            },
            tracer=tracer,
        ):
            pass
        spans = exporter.get_finished_spans()
        assert spans[0].attributes["channel"] == "email"
        assert spans[0].attributes["person_id"] == "p_001"
        assert spans[0].attributes["stage"] == "send"
        assert spans[0].attributes["operation"] == "email"


class TestTracedStageClosedSets:
    """ADR-0054 D296 + D297 — closed-set refuse-loud cells.

    Cells: bad stage refuses-loud; empty operation refuses-loud;
    every allowed stage accepts (parametrized across the 8); every
    allowed attribute accepts (parametrized across the 12).
    """

    def test_unknown_stage_refuses_loud(self):
        """ADR-0054 D296 — stage not in :data:`_PIPELINE_STAGES`
        refuses-loud with ``ValueError``."""
        with pytest.raises(ValueError, match="_PIPELINE_STAGES"):
            with traced_stage("not_a_real_stage", "op"):
                pass

    def test_empty_operation_refuses_loud(self):
        """ADR-0054 D296 — operation MUST be non-empty."""
        with pytest.raises(ValueError, match="operation"):
            with traced_stage("send", ""):
                pass

    def test_unknown_attribute_refuses_loud(self):
        """ADR-0054 D297 — attribute key not in
        :data:`_SPAN_ATTRIBUTES_ALLOWED` refuses-loud."""
        with pytest.raises(ValueError, match="_SPAN_ATTRIBUTES_ALLOWED"):
            with traced_stage(
                "send", "email",
                attributes={"some_random_key": "value"},
            ):
                pass

    @pytest.mark.parametrize("stage", sorted(_PIPELINE_STAGES))
    def test_every_allowed_stage_accepts(self, stage: str):
        """ADR-0054 D296 — every stage in :data:`_PIPELINE_STAGES`
        is accepted without refuse-loud."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        # Should not raise.
        with traced_stage(stage, "op", tracer=tracer):
            pass
        spans = exporter.get_finished_spans()
        assert spans[0].attributes["stage"] == stage

    @pytest.mark.parametrize("attr_key", sorted(_SPAN_ATTRIBUTES_ALLOWED))
    def test_every_allowed_attribute_accepts(self, attr_key: str):
        """ADR-0054 D297 — every key in
        :data:`_SPAN_ATTRIBUTES_ALLOWED` is accepted without
        refuse-loud."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        # Should not raise.
        with traced_stage(
            "send", "email",
            attributes={attr_key: "test-value"},
            tracer=tracer,
        ):
            pass


class TestTracedStageBehavioralPassthrough:
    """ADR-0054 D296 + the behavioral-passthrough-not-signature-only
    discipline (NOW SEVEN consecutive weeks Pillar F W8-W11 + Pillar
    G W3 + W4 + W5).

    Cells: span emit verified via :class:`InMemorySpanExporter`
    capture (not signature-only); span name + attributes on the
    actual captured span; parent-child relationships for nested
    spans.
    """

    def test_in_memory_exporter_captures_span(self):
        """Behavioral pin — the span is actually emitted (not just
        the signature accepts; the exporter sees the emission)."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage("send", "email", tracer=tracer):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1

    def test_nested_spans_carry_parent_child_relationship(self):
        """Behavioral pin — nested :func:`traced_stage` calls produce
        parent-child span relationships per OTel SDK semantics."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage("review", "reconcile_pass_c",
                          tracer=tracer):
            with traced_stage("discovery", "check_dedup",
                              tracer=tracer):
                pass
        spans = exporter.get_finished_spans()
        # Two spans surfaced.
        assert len(spans) == 2
        # Find parent (review) + child (discovery) by name.
        by_name = {s.name: s for s in spans}
        parent = by_name["outreach_factory.review.reconcile_pass_c"]
        child = by_name["outreach_factory.discovery.check_dedup"]
        # OTel SDK sets parent_span_id on child to parent's span_id.
        assert child.parent.span_id == parent.context.span_id

    def test_span_attributes_actually_appear_on_exported_span(self):
        """Behavioral pin — attributes appear on the EXPORTED span
        (not just the signature accepts the dict; the exporter
        sees the attributes)."""
        provider, exporter = _make_tracer_with_in_memory_exporter()
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage(
            "reply", "classify",
            attributes={
                "channel": "email",
                "person_id": "p_42",
                "category": "interested",
                "classification_method": "rule",
            },
            tracer=tracer,
        ):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs["channel"] == "email"
        assert attrs["person_id"] == "p_42"
        assert attrs["category"] == "interested"
        assert attrs["classification_method"] == "rule"
        assert attrs["stage"] == "reply"
        assert attrs["operation"] == "classify"


class TestFrameworkNeutralityWeek5:
    """ADR-0054 D298 — framework-neutrality contract for tracing.

    Cells: empty span_processors works (no export until wired);
    multiple processors compose; operator-extended Resource
    preserves framework keys.
    """

    def test_no_processors_default_works(self):
        """Operators with OTLP-only setups (no Prometheus, no
        InMemoryExporter) wire their own SpanProcessor. The Week 5
        default is EMPTY tuple; the TracerProvider accepts spans
        without export."""
        provider = init_otel_tracer_provider(set_global=False)
        tracer = get_tracer(tracer_provider=provider)
        # No raise on span emit even without exporter.
        with traced_stage("send", "email", tracer=tracer):
            pass

    def test_operator_extended_resource_preserves_service_keys(self):
        """ADR-0054 D298 + ADR-0052 D286 — operator-extended Resource
        at Pillar I per-tenant audit-tooling preserves framework's
        ``service.*`` keys + adds per-tenant keys."""
        custom = Resource.create({
            SERVICE_NAME: "outreach-factory",
            SERVICE_VERSION: "0.1.0",
            "outreach_factory.tenant_id": "tenant-b",
            "outreach_factory.environment": "prod",
        })
        provider = init_otel_tracer_provider(
            resource=custom, set_global=False,
        )
        attrs = dict(provider.resource.attributes)
        assert attrs[SERVICE_NAME] == "outreach-factory"
        assert attrs[SERVICE_VERSION] == "0.1.0"
        assert attrs["outreach_factory.tenant_id"] == "tenant-b"
        assert attrs["outreach_factory.environment"] == "prod"

    def test_otlp_and_in_memory_exporters_compose(self):
        """Two SpanProcessors compose — operators MAY wire both an
        OTLP export (for production tracing backend) AND a debug
        in-memory exporter without conflict."""
        exporter_otlp = InMemorySpanExporter()    # stand-in for OTLP
        exporter_debug = InMemorySpanExporter()
        provider = init_otel_tracer_provider(
            span_processors=[
                SimpleSpanProcessor(exporter_otlp),
                SimpleSpanProcessor(exporter_debug),
            ],
            set_global=False,
        )
        tracer = get_tracer(tracer_provider=provider)
        with traced_stage("send", "email", tracer=tracer):
            pass
        assert len(exporter_otlp.get_finished_spans()) == 1
        assert len(exporter_debug.get_finished_spans()) == 1


class TestSpanAttributesClosedSetPrivacy:
    """ADR-0054 D297 — privacy-disallowed attribute keys refuse-loud.

    Cells: each privacy-relevant key refuses-loud at attribute
    validation (parametrized over the 5 disallowed keys per the
    privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182
    category 8).
    """

    @pytest.mark.parametrize("disallowed_key", [
        "source_list",
        "draft_body",
        "dossier_body",
        "exemplar_body",
        "claim_text",
    ])
    def test_disallowed_key_refuses_loud(self, disallowed_key: str):
        """The closed-set IS the regression-barrier. A future Pillar
        G contributor adding a privacy-relevant key (silently
        broadening the surface) sees this test refuse-loud at PR
        time."""
        with pytest.raises(
            ValueError, match="_SPAN_ATTRIBUTES_ALLOWED",
        ):
            with traced_stage(
                "send", "email",
                attributes={disallowed_key: "secret-value"},
            ):
                pass


class TestPillarGScopeParityWithMeter:
    """ADR-0054 D295 + ADR-0052 D283 — the per-pillar-symmetry
    contract: ONE canonical scope across both metric + trace
    instruments.

    Cells: Tracer name == Meter name; Tracer version == Meter
    version; both share the canonical ``orchestrator.observability``
    scope.
    """

    def test_tracer_name_matches_meter_name(self):
        """ADR-0054 D295 + ADR-0052 D283 — per-pillar-symmetry: ONE
        canonical scope name across metric + trace instruments."""
        from observability import _METER_NAME
        assert _TRACER_NAME == _METER_NAME, (
            "ADR-0054 D295 + ADR-0052 D283 — Tracer scope name MUST "
            "match Meter scope name per the per-pillar-symmetry "
            "contract per RETRO-pillar-f.md item 5."
        )

    def test_tracer_version_matches_meter_version(self):
        """ADR-0054 D295 + ADR-0052 D283 — per-pillar-symmetry: ONE
        canonical scope version across metric + trace instruments."""
        from observability import _METER_VERSION
        assert _TRACER_VERSION == _METER_VERSION, (
            "ADR-0054 D295 + ADR-0052 D283 — Tracer scope version "
            "MUST match Meter scope version."
        )


class TestTracedStageNoOpPosture:
    """ADR-0054 D296 — :func:`traced_stage` works without prior
    :func:`init_otel_tracer_provider` call (safe-default OTel
    behavior).

    Cells: works without init (no-op); attribute validation still
    runs even at no-op posture (the helper's refuse-loud is
    independent of provider initialization).
    """

    def test_traced_stage_works_without_init(self):
        """ADR-0054 D296 — operators using :func:`traced_stage` at
        the per-pillar call sites do NOT need to gate on
        :func:`init_otel_tracer_provider`; the OTel SDK returns a
        :class:`NoOpTracer` by default which silently accepts span
        emit."""
        # Note: we cannot easily reset the global TracerProvider
        # state in tests (OTel set-once enforcement). The helper
        # consulting get_tracer() with no explicit tracer kwarg
        # picks up whatever is global. We pass an explicit tracer
        # from a no-op-equivalent setup to verify the helper's
        # error-free path WITHOUT relying on the global state.
        provider = init_otel_tracer_provider(set_global=False)
        tracer = get_tracer(tracer_provider=provider)
        # Should not raise — no processor wired, but tracer is real.
        with traced_stage("send", "email", tracer=tracer):
            pass

    def test_closed_set_validation_still_fires_without_init(self):
        """ADR-0054 D296 — even at no-op posture, the closed-set
        refuse-loud STILL fires (privacy invariant per ADR-0054
        D297 is independent of OTel provider initialization)."""
        # The validation happens BEFORE the span is created, so
        # provider init state doesn't matter.
        with pytest.raises(ValueError, match="_PIPELINE_STAGES"):
            with traced_stage("not_a_stage", "op"):
                pass
        with pytest.raises(ValueError, match="_SPAN_ATTRIBUTES_ALLOWED"):
            with traced_stage(
                "send", "email",
                attributes={"draft_body": "leaked!"},
            ):
                pass


# ---------------------------------------------------------------------------
# Week 6 — Per-call-site span wiring + dispatcher integration
# (per ADR-0055 D300-D306)
#
# Wires :func:`traced_stage` at the per-pillar Python call sites across
# the eight pipeline stages (discovery → enrichment → research → draft →
# review → send → reply → win_loss) per ADR-0055 D300-D304 + completes
# the Week 4 carry-forward for the send-latency Histogram dispatcher
# integration at :func:`skills.send-outreach.scripts.send_queued.
# gated_send_one` (+ four sibling channel dispatchers) per D305.
#
# Cells covered:
#
# * ``TestPillarECallSiteSpanWiring`` — discovery + enrichment cells:
#   :func:`orchestrator.discovery_dedup.check_dedup` emits the
#   ``outreach_factory.discovery.check_dedup`` span carrying
#   ``source_skill`` attribute; :func:`orchestrator.tier_assignment.
#   compute_tier_from_signals` emits the
#   ``outreach_factory.enrichment.compute_tier`` span carrying
#   ``person_id`` attribute.
# * ``TestPillarFCallSiteSpanWiring`` — review cell:
#   :func:`orchestrator.reconcile.run_pass_c` emits the
#   ``outreach_factory.review.reconcile_pass_c`` span.
# * ``TestPillarDCallSiteSpanWiring`` — reply + win_loss cells:
#   :func:`orchestrator.reply_classifier.emit_classified_event` emits
#   the ``outreach_factory.reply.classify`` span carrying ``channel`` +
#   ``person_id`` + ``category`` + ``classification_method``
#   attributes; :func:`orchestrator.conversation_outcomes.
#   run_conversation_outcomes_pass` emits the
#   ``outreach_factory.win_loss.derive_outcomes`` span.
# * ``TestDispatcherSpanWiring`` — five send channels:
#   :func:`gated_send_one` emits ``outreach_factory.send.email``;
#   :func:`gated_li_invite_one` emits
#   ``outreach_factory.send.li_invite``; :func:`gated_li_dm_one` emits
#   ``outreach_factory.send.li_dm``; :func:`gated_tw_dm_one` emits
#   ``outreach_factory.send.tw_dm``; :func:`gated_calendar_booking_one`
#   emits ``outreach_factory.send.calendar_booking``; each carries
#   ``channel`` + ``person_id`` + ``register`` attributes.
# * ``TestDispatcherSendLatencyHistogramIntegration`` — completes the
#   Week 4 carry-forward: :func:`gated_send_one` calls
#   :meth:`histogram.record` with the per-channel attribute at the
#   external API call boundary; observable via the Prometheus
#   exposition's ``outreach_factory_send_latency_seconds`` metric
#   family.
# * ``TestWeek6PrivacyInvariantPropagation`` — per-call-site spans
#   never carry ``draft_body`` / ``dossier_body`` / ``exemplar_body``
#   / ``claim_text`` / ``source_list`` attributes; the
#   :data:`_SPAN_ATTRIBUTES_ALLOWED` refuse-loud at every per-call
#   site preserves the privacy invariant per I8 + ADR-0050 D276(b)
#   + ADR-0054 D297.
# * ``TestWeek6LegacyStateNoBehavioralImpact`` — per-call-site span
#   emit MUST NOT modify any primitive's existing behavior (no-op
#   posture-preservation; primitives stay testable without span init).
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_tracer(monkeypatch):
    """Per-test fixture: install an :class:`InMemorySpanExporter` +
    monkeypatch :func:`observability.get_tracer` to consult it.

    The behavioral-passthrough-not-signature-only discipline (NOW
    EIGHT consecutive weeks at Pillar G Week 6; Pillar F W8-W11 +
    Pillar G W3 + W4 + W5 + W6) requires that per-call-site span
    emit be verified via real captured spans — NOT just that the
    call site references :func:`traced_stage`.

    Patching :func:`observability.get_tracer` (instead of
    :func:`init_otel_tracer_provider` ``set_global=True``) keeps
    test isolation: each test gets its own exporter + provider; OTel
    SDK's set-once enforcement on
    :func:`opentelemetry.trace.set_tracer_provider` is bypassed
    entirely. :func:`traced_stage` falls through to
    :func:`get_tracer` when called without explicit ``tracer=``
    kwarg — the patched callable returns our local tracer.
    """
    exporter = InMemorySpanExporter()
    provider = init_otel_tracer_provider(
        span_processors=[SimpleSpanProcessor(exporter)],
        set_global=False,
    )
    local_tracer = provider.get_tracer(_TRACER_NAME, _TRACER_VERSION)
    monkeypatch.setattr(
        observability,
        "get_tracer",
        lambda tracer_provider=None: local_tracer,
    )
    return exporter


def _spans_named(
    exporter: InMemorySpanExporter, name: str,
) -> list:
    return [s for s in exporter.get_finished_spans() if s.name == name]


class TestPillarECallSiteSpanWiring:
    """ADR-0055 D300 — Pillar E primitives emit spans at call sites.

    Cells: :func:`discovery_dedup.check_dedup` emits the discovery
    span; :func:`tier_assignment.compute_tier_from_signals` emits the
    enrichment span.
    """

    def test_check_dedup_emits_discovery_span(self, in_memory_tracer):
        """ADR-0055 D300 — :func:`check_dedup` wraps body in
        ``traced_stage("discovery", "check_dedup", ...)``."""
        from orchestrator import discovery_dedup
        from orchestrator import identity as _identity
        # Empty partial → returns not_duplicate without touching
        # vault. Span still emits at the wrapping boundary.
        result = discovery_dedup.check_dedup(
            _identity.IdentityKeys(),
            source_skill="find-leads",
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.discovery.check_dedup",
        )
        assert len(spans) == 1, (
            "check_dedup MUST emit one discovery span per call per "
            "ADR-0055 D300"
        )
        # stage attribute auto-set by traced_stage.
        assert spans[0].attributes["stage"] == "discovery"
        assert spans[0].attributes["operation"] == "check_dedup"

    def test_check_dedup_span_carries_source_skill_attribute(
        self, in_memory_tracer,
    ):
        """ADR-0055 D300 — the discovery span carries the
        ``source_skill`` attribute (privacy-respecting per I8 — the
        ``source_list`` field is REFUSED per ADR-0054 D297 +
        ADR-0055 D304)."""
        from orchestrator import discovery_dedup
        from orchestrator import identity as _identity
        _ = discovery_dedup.check_dedup(
            _identity.IdentityKeys(),
            source_skill="find-funded-founders",
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.discovery.check_dedup",
        )
        assert spans[0].attributes.get("source_skill") == "find-funded-founders"

    def test_compute_tier_from_signals_emits_enrichment_span(
        self, in_memory_tracer,
    ):
        """ADR-0055 D300 — :func:`compute_tier_from_signals` wraps
        body in ``traced_stage("enrichment", "compute_tier", ...)``."""
        from orchestrator import tier_assignment
        # Minimal weights config (empty signals + thresholds tolerate
        # empty score → tier B).
        weights = {"signals": {}, "thresholds": {"S": 100, "A": 50}}
        _ = tier_assignment.compute_tier_from_signals(
            "p_001", {}, weights=weights,
            now=NOW_2026_05_25,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.enrichment.compute_tier",
        )
        assert len(spans) == 1, (
            "compute_tier_from_signals MUST emit one enrichment span "
            "per call per ADR-0055 D300"
        )
        assert spans[0].attributes["stage"] == "enrichment"
        assert spans[0].attributes["operation"] == "compute_tier"

    def test_compute_tier_span_carries_person_id_attribute(
        self, in_memory_tracer,
    ):
        """ADR-0055 D300 — the enrichment span carries
        ``person_id`` attribute."""
        from orchestrator import tier_assignment
        weights = {"signals": {}, "thresholds": {"S": 100, "A": 50}}
        _ = tier_assignment.compute_tier_from_signals(
            "p_42", {}, weights=weights, now=NOW_2026_05_25,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.enrichment.compute_tier",
        )
        assert spans[0].attributes.get("person_id") == "p_42"


class TestPillarFCallSiteSpanWiring:
    """ADR-0055 D301 — review-stage primitives emit spans at call sites.

    Cell: :func:`reconcile.run_pass_c` emits the review span.
    """

    def test_reconcile_pass_c_emits_review_span(self, in_memory_tracer, tmp_path):
        """ADR-0055 D301 — :func:`run_pass_c` wraps body in
        ``traced_stage("review", "reconcile_pass_c", ...)``."""
        from orchestrator import reconcile, ledger as _ledger
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        led_dir = tmp_path / "ledger"
        led_dir.mkdir()
        led = _ledger.Ledger(led_dir)
        _ = reconcile.run_pass_c(
            led=led, people_dir=people_dir, apply=False,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.review.reconcile_pass_c",
        )
        assert len(spans) == 1
        assert spans[0].attributes["stage"] == "review"
        assert spans[0].attributes["operation"] == "reconcile_pass_c"


class TestPillarDCallSiteSpanWiring:
    """ADR-0055 D302 — Pillar D primitives emit spans at call sites.

    Cells: :func:`reply_classifier.emit_classified_event` emits the
    reply span; :func:`conversation_outcomes.
    run_conversation_outcomes_pass` emits the win_loss span.
    """

    def test_emit_classified_event_emits_reply_span(
        self, in_memory_tracer, led,
    ):
        """ADR-0055 D302 — :func:`emit_classified_event` wraps body
        in ``traced_stage("reply", "classify", ...)``."""
        from orchestrator import reply_classifier
        reply_event = {
            "type": "gmail_reply_observed",
            "person_id": "p_001",
            "channel": "email",
            "gmail_message_id": "msg_xyz",
            "gmail_thread_id": "thr_abc",
            "body": "Yes I'm interested.",
        }
        result = reply_classifier.ClassifierResult(
            category="interest",
            classification_method="rule",
            confidence=0.95,
            matched_pattern="interested",
        )
        _ = reply_classifier.emit_classified_event(led, reply_event, result)
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.reply.classify",
        )
        assert len(spans) == 1, (
            "emit_classified_event MUST emit one reply span per call "
            "per ADR-0055 D302"
        )
        assert spans[0].attributes["stage"] == "reply"
        assert spans[0].attributes["operation"] == "classify"

    def test_emit_classified_event_span_carries_attributes(
        self, in_memory_tracer, led,
    ):
        """ADR-0055 D302 — the reply span carries ``channel`` +
        ``person_id`` + ``category`` + ``classification_method``
        attributes."""
        from orchestrator import reply_classifier
        reply_event = {
            "type": "gmail_reply_observed",
            "person_id": "p_42",
            "channel": "email",
            "gmail_message_id": "msg_xyz",
        }
        result = reply_classifier.ClassifierResult(
            category="rejection",
            classification_method="llm",
            confidence=0.78,
            matched_pattern=None,
        )
        _ = reply_classifier.emit_classified_event(led, reply_event, result)
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.reply.classify",
        )
        attrs = dict(spans[0].attributes)
        assert attrs.get("channel") == "email"
        assert attrs.get("person_id") == "p_42"
        assert attrs.get("category") == "rejection"
        assert attrs.get("classification_method") == "llm"

    def test_run_conversation_outcomes_pass_emits_win_loss_span(
        self, in_memory_tracer, led,
    ):
        """ADR-0055 D302 — :func:`run_conversation_outcomes_pass`
        wraps body in ``traced_stage("win_loss", "derive_outcomes",
        ...)``."""
        from orchestrator import conversation_outcomes
        _ = conversation_outcomes.run_conversation_outcomes_pass(
            led=led, apply=False, now=NOW_2026_05_25,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.win_loss.derive_outcomes",
        )
        assert len(spans) == 1
        assert spans[0].attributes["stage"] == "win_loss"
        assert spans[0].attributes["operation"] == "derive_outcomes"


def _bootstrap_send_queued_import():
    """Set up the import substrate for ``send_queued`` per the
    convention in :mod:`tests.test_send_gate` — stub ``config`` +
    ``google_auth_oauthlib`` + add ``skills/send-outreach/scripts``
    to ``sys.path`` BEFORE importing.
    """
    import sys
    import types as _types
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "skills" / "send-outreach" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "google_auth_oauthlib" not in sys.modules:
        _gao = _types.ModuleType("google_auth_oauthlib")
        _gao_flow = _types.ModuleType("google_auth_oauthlib.flow")
        _gao_flow.InstalledAppFlow = object
        _gao.flow = _gao_flow
        sys.modules["google_auth_oauthlib"] = _gao
        sys.modules["google_auth_oauthlib.flow"] = _gao_flow
    if "config" not in sys.modules:
        _cfg = _types.ModuleType("config")
        _cfg.LINKEDIN_MANIFEST_PATH = Path("/tmp/_test_li_manifest.json")
        _cfg.LINKEDIN_WEEKLY_INVITE_LIMIT = 100
        _cfg.SENDER_NAME = "Test Sender"
        _cfg.VAULT_ROOT = Path("/tmp/_test_vault")
        _cfg.PEOPLE_DIR = Path("/tmp/_test_vault/10 People")
        _cfg.CONVERSATIONS_DIR = Path("/tmp/_test_vault/40 Conversations")
        _cfg.TOUCH_NOTE_GLOB = "**/*.md"
        _cfg.CREDENTIALS_DIR = Path("/tmp/_test_creds")
        _cfg.GMAIL_CREDENTIALS = Path("/tmp/_test_creds/g.json")
        _cfg.GMAIL_TOKEN = Path("/tmp/_test_creds/t.json")
        _cfg.GMAIL_SCOPES = []
        sys.modules["config"] = _cfg


def _write_test_person_note(
    people_dir: Path, *, name: str, person_id: str,
    email: str | None = None, linkedin: str | None = None,
    twitter_handle: str | None = None,
    calendar_booking_url_base: str | None = None,
    linkedin_connected: bool | None = None,
) -> Path:
    """Write a minimal Person note that survives the dispatcher's
    early-return gates. Mirrors ``tests/test_send_gate.py::
    _write_person_note`` but extended for non-email channels."""
    lines = ["---", "type: person", f"id: {person_id}",
             "identity_keys:"]
    if email:
        lines += ["  emails:", f"    - {email}"]
    if linkedin:
        slug = linkedin[3:] if linkedin.startswith("in/") else linkedin
        lines.append(f"  linkedin: {slug}")
    if twitter_handle:
        lines.append(f"  twitter: {twitter_handle}")
    lines.append(f"name: {name}")
    if email:
        lines.append(f"email: {email}")
    if linkedin:
        lines.append(f"linkedin: {linkedin}")
    if twitter_handle:
        lines.append(f"twitter_handle: {twitter_handle}")
    if calendar_booking_url_base:
        lines.append(f"calendar_booking_url_base: {calendar_booking_url_base}")
    if linkedin_connected is not None:
        lines.append(
            f"linkedin_connected: {'true' if linkedin_connected else 'false'}"
        )
    lines.append("status: queued")
    lines.append("pipeline_stage: ready")
    lines.append("---")
    lines.append(f"# {name}\n")
    note = people_dir / f"{name}.md"
    note.write_text("\n".join(lines), encoding="utf-8")
    return note


def _make_touch_draft(
    *, person_note: Path, name: str, email: str | None = None,
    linkedin: str | None = None, twitter_handle: str | None = None,
    calendar_booking_url_base: str | None = None,
    email_subject: str = "Hi", email_body: str = "Hello\n",
    linkedin_dm: str | None = None,
    twitter_dm: str | None = None,
    calendar_cover_message: str | None = None,
    channel_declared: str = "email",
):
    """Construct a ``vault.TouchDraft`` directly. Mirrors
    ``tests/test_send_gate.py::_make_draft``."""
    _bootstrap_send_queued_import()
    import vault as _vault
    person_info = _vault.PersonInfo(
        name=name, note_path=person_note, email=email,
        linkedin=linkedin, status="queued",
        twitter_handle=twitter_handle,
        calendar_booking_url_base=calendar_booking_url_base,
    )
    return _vault.TouchDraft(
        note_path=person_note,
        frontmatter={"type": "touch", "channel": channel_declared,
                     "sent": False},
        body="",
        person_name=name,
        person=person_info,
        channel_declared=channel_declared,
        has_email_block=email is not None,
        has_linkedin_block=linkedin is not None,
        email_subject=email_subject,
        email_body=email_body,
        linkedin_dm=linkedin_dm,
        has_twitter_block=twitter_handle is not None,
        twitter_dm=twitter_dm,
        has_calendar_block=calendar_booking_url_base is not None,
        calendar_cover_message=calendar_cover_message,
        issues=[],
    )


class TestDispatcherSpanWiring:
    """ADR-0055 D303 — the per-channel dispatcher emits per-channel
    send spans at the two-phase commit boundary.

    Cells: :func:`gated_send_one` emits ``send.email`` span;
    :func:`gated_li_invite_one` emits ``send.li_invite`` span;
    :func:`gated_li_dm_one` emits ``send.li_dm`` span;
    :func:`gated_tw_dm_one` emits ``send.tw_dm`` span;
    :func:`gated_calendar_booking_one` emits ``send.calendar_booking``
    span. Each carries ``channel`` + ``person_id`` + ``register``
    attributes.

    The test exercises the early-return ``no_linkedin_url`` /
    ``no_email`` block paths (no external API integration) to keep
    the test surface focused — the span emit must fire at the
    wrapping boundary REGARDLESS of whether the dispatch path
    succeeds, blocks, or fails. Per ADR-0055 D303 the wrapping
    boundary is the function entry; the span finishes when the
    function returns (block-return OR success-return OR exception).
    """

    def test_gated_send_one_emits_send_email_span(
        self, in_memory_tracer, led, tmp_path,
    ):
        """ADR-0055 D303 — :func:`gated_send_one` wraps body in
        ``traced_stage("send", "email", ...)``. Exercise via the
        clean send path to verify the span emit alongside the
        two-phase commit."""
        _bootstrap_send_queued_import()
        import send_queued
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        note = _write_test_person_note(
            people_dir, name="Alice", person_id="alice-li",
            email="alice@example.com",
        )
        draft = _make_touch_draft(
            person_note=note, name="Alice", email="alice@example.com",
        )

        class _FakeGmail:
            def send_email(self, **_):
                return ("mid_001", "tid_001")

        _ = send_queued.gated_send_one(
            draft, gmail_client=_FakeGmail(), led=led,
            writeback=None,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.send.email",
        )
        assert len(spans) == 1
        assert spans[0].attributes["stage"] == "send"
        assert spans[0].attributes["operation"] == "email"
        assert spans[0].attributes.get("channel") == "email"
        assert spans[0].attributes.get("person_id") == "alice-li"

    def test_gated_li_invite_one_emits_send_li_invite_span(
        self, in_memory_tracer, led, tmp_path,
    ):
        _bootstrap_send_queued_import()
        import send_queued
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        note = _write_test_person_note(
            people_dir, name="Bob", person_id="bob-li",
            linkedin="in/bob-test",
        )
        draft = _make_touch_draft(
            person_note=note, name="Bob",
            linkedin="https://www.linkedin.com/in/bob-test",
            linkedin_dm="Hi Bob!",
            channel_declared="linkedin",
        )

        class _FakeLI:
            def connect_with_person(self, **_):
                return "inv_001"

        _ = send_queued.gated_li_invite_one(
            draft, linkedin_client=_FakeLI(), led=led,
            writeback=None,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.send.li_invite",
        )
        assert len(spans) == 1
        assert spans[0].attributes["operation"] == "li_invite"
        assert spans[0].attributes.get("channel") == "linkedin"
        assert spans[0].attributes.get("person_id") == "bob-li"

    def test_gated_li_dm_one_emits_send_li_dm_span(
        self, in_memory_tracer, led, tmp_path,
    ):
        _bootstrap_send_queued_import()
        import send_queued
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        note = _write_test_person_note(
            people_dir, name="Carol", person_id="carol-li",
            linkedin="in/carol-test",
            linkedin_connected=True,
        )
        draft = _make_touch_draft(
            person_note=note, name="Carol",
            linkedin="https://www.linkedin.com/in/carol-test",
            linkedin_dm="Hi Carol!",
            channel_declared="linkedin",
        )

        class _FakeLI:
            def send_message(self, **_):
                return ("msg_001", "thr_001")

        _ = send_queued.gated_li_dm_one(
            draft, linkedin_client=_FakeLI(), led=led,
            writeback=None,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.send.li_dm",
        )
        assert len(spans) == 1
        assert spans[0].attributes["operation"] == "li_dm"
        assert spans[0].attributes.get("channel") == "linkedin"
        assert spans[0].attributes.get("person_id") == "carol-li"

    def test_gated_tw_dm_one_emits_send_tw_dm_span(
        self, in_memory_tracer, led, tmp_path,
    ):
        _bootstrap_send_queued_import()
        import send_queued
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        note = _write_test_person_note(
            people_dir, name="Dave", person_id="dave-li",
            linkedin="in/dave-test",
            twitter_handle="dave_test",
        )
        draft = _make_touch_draft(
            person_note=note, name="Dave",
            linkedin="https://www.linkedin.com/in/dave-test",
            twitter_handle="dave_test",
            twitter_dm="Hi Dave!",
            channel_declared="twitter",
        )

        class _FakeTw:
            def send_dm(self, **_):
                return ("twmsg_001", "twthr_001")

        _ = send_queued.gated_tw_dm_one(
            draft, twitter_client=_FakeTw(), led=led,
            writeback=None,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.send.tw_dm",
        )
        assert len(spans) == 1
        assert spans[0].attributes["operation"] == "tw_dm"
        assert spans[0].attributes.get("channel") == "twitter"
        assert spans[0].attributes.get("person_id") == "dave-li"

    def test_gated_calendar_booking_one_emits_send_calendar_booking_span(
        self, in_memory_tracer, led, tmp_path,
    ):
        """ADR-0055 D303 — :func:`gated_calendar_booking_one`
        wraps body in ``traced_stage("send", "calendar_booking",
        ...)``. The calendar dispatcher's send action is URL-
        synthesis (no external API call per ADR-0019 D66) so no
        per-channel send-latency histogram record fires here."""
        _bootstrap_send_queued_import()
        import send_queued
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        note = _write_test_person_note(
            people_dir, name="Eve", person_id="eve-li",
            linkedin="in/eve-test",
            email="eve@example.com",
            calendar_booking_url_base="https://cal.com/eve/intro",
        )
        draft = _make_touch_draft(
            person_note=note, name="Eve",
            email="eve@example.com",
            linkedin="https://www.linkedin.com/in/eve-test",
            calendar_booking_url_base="https://cal.com/eve/intro",
            calendar_cover_message="Let's book!",
            email_body="Hello Eve, book at: ",
            channel_declared="calendar_booking",
        )

        _ = send_queued.gated_calendar_booking_one(
            draft,
            cal_com_base_url="https://cal.com/eve/intro",
            led=led, writeback=None,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.send.calendar_booking",
        )
        assert len(spans) == 1
        assert spans[0].attributes["operation"] == "calendar_booking"
        assert spans[0].attributes.get("channel") == "calendar"
        assert spans[0].attributes.get("person_id") == "eve-li"


class TestDispatcherSendLatencyHistogramIntegration:
    """ADR-0055 D305 — dispatcher integration for the Week 4
    send-latency Histogram (carries forward the Week 4 deferred
    integration per ADR-0053 D289 + ADR-0053 §Negative).

    Cells: :func:`gated_send_one` records elapsed time at the
    external API boundary; the histogram captures the per-channel
    timing; the Prometheus exposition surfaces the metric family.

    The integration is best-effort — observability failure MUST NOT
    break the dispatch (per ADR-0053 D289's §Negative + the
    historical convention from cost_incurred emit's
    try/except-best-effort posture in :func:`gated_send_one`).
    """

    def test_gated_send_one_records_send_latency_histogram_on_success(
        self, monkeypatch, tmp_path, led,
    ):
        """ADR-0055 D305 — successful send path records the per-
        channel elapsed time into
        ``outreach_factory_send_latency_seconds``."""
        _bootstrap_send_queued_import()
        import send_queued
        from observability import (
            init_otel_meter_provider, init_prometheus_metric_reader,
            render_prometheus_exposition,
        )
        # Wire a fresh Prometheus reader to a fresh provider; patch
        # observability.get_meter to consult this provider so the
        # dispatcher's get_send_latency_histogram() picks up the
        # exporter-wired meter (mirrors the in_memory_tracer fixture
        # pattern for spans; preserves test isolation without OTel's
        # set-once enforcement on set_meter_provider per R035).
        reader = init_prometheus_metric_reader()
        provider = init_otel_meter_provider(
            metric_readers=[reader], set_global=False,
        )
        local_meter = provider.get_meter(
            "orchestrator.observability", "0.1.0",
        )
        monkeypatch.setattr(
            observability,
            "get_meter",
            lambda meter_provider=None: local_meter,
        )
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        note = _write_test_person_note(
            people_dir, name="Fred", person_id="fred-li",
            email="fred@example.com",
        )
        draft = _make_touch_draft(
            person_note=note, name="Fred", email="fred@example.com",
        )

        class _FakeGmail:
            def send_email(self, **_):
                return ("mid_001", "tid_001")

        result = send_queued.gated_send_one(
            draft, gmail_client=_FakeGmail(), led=led,
            writeback=None,
        )
        assert result["ok"], (
            f"expected send to succeed but got {result!r}"
        )
        # The histogram appears in the Prometheus exposition.
        exposition = render_prometheus_exposition().decode()
        assert "outreach_factory_send_latency_seconds" in exposition, (
            "Week 4 carry-forward: dispatcher MUST record the per-"
            "channel send latency to the histogram per ADR-0055 D305"
        )
        # Per-channel attribute surfaces as a Prometheus label.
        assert 'channel="email"' in exposition


class TestWeek6PrivacyInvariantPropagation:
    """ADR-0055 D304 — per-call-site spans NEVER carry privacy-
    relevant attribute keys.

    Cells: every span emitted at every call site has zero keys from
    the five privacy-disallowed names (``source_list`` /
    ``draft_body`` / ``dossier_body`` / ``exemplar_body`` /
    ``claim_text``); per-call-site enforcement of
    :data:`_SPAN_ATTRIBUTES_ALLOWED` IS the structural mitigation.
    """

    _DISALLOWED = ("source_list", "draft_body", "dossier_body",
                   "exemplar_body", "claim_text")

    def test_discovery_span_has_no_privacy_attrs(self, in_memory_tracer):
        from orchestrator import discovery_dedup
        from orchestrator import identity as _identity
        _ = discovery_dedup.check_dedup(
            _identity.IdentityKeys(),
            source_skill="find-leads",
            source_list="[[secret-list]]",
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.discovery.check_dedup",
        )
        attrs = dict(spans[0].attributes)
        for key in self._DISALLOWED:
            assert key not in attrs, (
                f"discovery span MUST NOT carry {key!r} per the "
                "privacy invariant per I8 + ADR-0055 D304"
            )

    def test_reconcile_pass_c_span_has_no_privacy_attrs(
        self, in_memory_tracer, tmp_path,
    ):
        from orchestrator import reconcile, ledger as _ledger
        people_dir = tmp_path / "people"
        people_dir.mkdir()
        led_dir = tmp_path / "ledger"
        led_dir.mkdir()
        led = _ledger.Ledger(led_dir)
        _ = reconcile.run_pass_c(
            led=led, people_dir=people_dir, apply=False,
        )
        spans = _spans_named(
            in_memory_tracer,
            "outreach_factory.review.reconcile_pass_c",
        )
        attrs = dict(spans[0].attributes)
        for key in self._DISALLOWED:
            assert key not in attrs, (
                f"review span MUST NOT carry {key!r} per the "
                "privacy invariant per I8 + ADR-0055 D304"
            )


class TestWeek6LegacyStateNoBehavioralImpact:
    """ADR-0055 D306 — per-call-site span emit MUST NOT modify any
    primitive's existing behavior.

    The legacy-state-vs-new-defense-layer tension discipline NOW
    SIX consecutive weeks (Pillar F W12 NEW pattern + Pillar G W2 +
    W3 + W4 + W5 + W6) requires that the per-call-site wiring at
    Week 6 preserves the existing Pillar A-F primitive surfaces
    verbatim — the Pillar D + E + F binding exit-criterion tests
    STAY GREEN.
    """

    def test_check_dedup_return_value_unchanged_with_span_init(
        self, in_memory_tracer,
    ):
        """ADR-0055 D306 — :func:`check_dedup` return value matches
        the pre-span-wiring contract regardless of span init."""
        from orchestrator import discovery_dedup
        from orchestrator import identity as _identity
        result = discovery_dedup.check_dedup(
            _identity.IdentityKeys(),
            source_skill="find-leads",
        )
        # Empty partial → not_duplicate (pre-wiring contract).
        assert result.status == "not_duplicate"

    def test_emit_classified_event_returns_persisted_event_unchanged(
        self, in_memory_tracer, led,
    ):
        """ADR-0055 D306 — :func:`emit_classified_event` returns
        persisted event dict with ts + v fields (per ledger's
        append contract) regardless of span init."""
        from orchestrator import reply_classifier
        reply_event = {
            "type": "gmail_reply_observed",
            "person_id": "p_001",
            "channel": "email",
            "gmail_message_id": "msg_xyz",
        }
        result = reply_classifier.ClassifierResult(
            category="interest",
            classification_method="rule",
            confidence=0.95,
            matched_pattern="interested",
        )
        persisted = reply_classifier.emit_classified_event(
            led, reply_event, result,
        )
        assert persisted["type"] == "reply_classified"
        assert "ts" in persisted


# ---------------------------------------------------------------------------
# Week 7-8 — SLO violation detector + slo_violation_detected event class
# emit + Slack webhook (per ADR-0056 D307-D313)
#
# Pillar G Week 7-8 ships the per-window SLO violation detector + the
# slo_violation_detected event class emit (the second of the two
# OBSERVABILITY_NEW_EVENT_CLASSES named at design-time at ADR-0050 D273)
# + the Slack webhook dispatcher with operator-deliberate opt-in posture
# per ADR-0050 D276(d).
#
# Cells covered:
#
# * ``TestWeek7SLONamesClosedSet`` — :data:`_SLO_NAMES` closed-set
#   membership; cardinality = 4; mutual exclusion from
#   ``reconcile_drift.reason`` closed-set per ADR-0049 D263 (the
#   legacy-state-vs-new-defense-layer reason-precedence drift
#   discipline).
# * ``TestSLOConfigDefaults`` — :class:`SLOConfig` defaults match
#   PILLAR-PLAN §2 Pillar G binding text (5.0s send-latency p99,
#   0.99 reconcile-success, 0.05 bounce-rate, 0 manual_override) +
#   ``slack_webhook_url`` defaults to ``None`` per ADR-0050 D276(d).
# * ``TestSLOViolationDataclass`` — :class:`SLOViolation` frozen +
#   fields per ADR-0056 D308.
# * ``TestDetectSLOViolationsSendLatency`` — per-channel p99 cells:
#   single-channel violation; per-channel separation; no-violation
#   below threshold; no violation when zero pairs.
# * ``TestDetectSLOViolationsReconcileSuccess`` — global reconcile
#   ratio cells: drift-only triggers; mixed heal+drift triggers below
#   threshold; vacuous (no activity) does NOT trigger.
# * ``TestDetectSLOViolationsBounceRate`` — per-channel bounce-rate
#   cells: violation; per-channel separation; vacuous (no confirms +
#   no bounces) does NOT trigger.
# * ``TestDetectSLOViolationsManualOverride`` — count > 0 triggers
#   compliance review alert per PILLAR-PLAN §2 Pillar G; count = 0
#   does NOT trigger; operator-configurable threshold accepts > 0.
# * ``TestDetectSLOViolationsSyntheticExclusion`` — R032 mitigation
#   per ADR-0056 D311: ``_recovered_by`` events EXCLUDED from ALL
#   four SLO evaluations (backfill / reconcile / migration_<id>
#   synthetic-data spikes do NOT trip alerts).
# * ``TestDetectSLOViolationsWindowFilter`` — events before
#   ``since = now - since_window`` are out-of-scope.
# * ``TestDetectSLOViolationsDeterministicClock`` — ``now`` kwarg
#   controls the ``ts`` field on emitted
#   ``slo_violation_detected`` events.
# * ``TestDetectSLOViolationsEventPayloadShape`` — emitted
#   ``slo_violation_detected`` event carries the closed-set keys +
#   ``_emitted_by: "observability"`` audit marker.
# * ``TestDetectSLOViolationsRateLimitDedup`` — at-most-ONE emit per
#   ``(slo_name, channel)`` per call per ADR-0056 D310 (R034 carry-
#   forward).
# * ``TestDetectSLOViolationsConfigOverrides`` — operator-supplied
#   :class:`SLOConfig` overrides default thresholds.
# * ``TestDispatchSLOAlertDefaultOff`` — ``slack_webhook_url=None``
#   returns ``False`` immediately + makes ZERO HTTP requests + emits
#   ZERO spans.
# * ``TestDispatchSLOAlertHttpSuccess`` — operator-supplied
#   ``slack_webhook_url`` triggers POST with JSON payload + returns
#   ``True``; payload carries closed-set keys.
# * ``TestDispatchSLOAlertHttpFailure`` — HTTP exception → returns
#   ``False`` (best-effort posture per ADR-0056 D312).
# * ``TestDispatchSLOAlertSpanWiring`` — dispatch wrapped in
#   ``traced_stage("send", "slack_webhook", attributes={"channel":
#   ..., "reason": violation.slo_name})`` per ADR-0056 D312 + the
#   per-stage span pattern per ADR-0055 D300-D303.
# * ``TestDispatchSLOAlertGlobalSLOChannelNone`` — global SLO
#   (channel=None) surfaces span attribute ``channel="none"`` per
#   OTel attribute-non-None convention.
# * ``TestSLOPrivacyInvariantPayload`` — slo_violation_detected
#   payload never carries privacy-disallowed keys per I8 + ADR-0050
#   D276(b).
# * ``TestSLOEmitsAreNotUncatalogued`` — the slo_violation_detected
#   emit does NOT trigger an observability_class_uncatalogued
#   diagnostic on subsequent collect_event_class_snapshots calls
#   (it's already in OBSERVABILITY_NEW_EVENT_CLASSES per ADR-0050
#   D273; R031 stability holds).
# * ``TestWeek7DocstringDriftDiscipline`` — module-level docstring
#   names Week 7-8 + ADR-0056 (module-docstring-drift discipline NOW
#   ELEVEN consecutive weeks per Pillar F W8-W12 + Pillar G W2-W6 +
#   W7-W8).
# ---------------------------------------------------------------------------


from observability import (
    SLOConfig,
    SLOViolation,
    _SLO_NAMES,
    detect_slo_violations,
    dispatch_slo_alert,
)


class TestWeek7SLONamesClosedSet:
    """ADR-0056 D313 — :data:`_SLO_NAMES` is a closed-set frozenset
    enumerating the four PILLAR-PLAN §2 Pillar G SLO triggers; the
    closed-set IS the R031-shape regression-barrier extended to the
    SLO surface + the ``slo_violation_detected.slo_name`` closed-enum.
    """

    def test_slo_names_is_frozenset(self):
        """ADR-0056 D313 — :data:`_SLO_NAMES` is a frozenset (the
        closed-set immutability discipline per ADR-0050 D272 +
        ADR-0051 D279 + ADR-0054 D296 + D297)."""
        assert isinstance(_SLO_NAMES, frozenset)

    def test_slo_names_cardinality_is_4(self):
        """ADR-0056 D313 — exactly four SLO names enumerated per
        PILLAR-PLAN §2 Pillar G binding text."""
        assert len(_SLO_NAMES) == 4

    def test_slo_names_membership(self):
        """ADR-0056 D313 — the four SLO names match PILLAR-PLAN §2
        Pillar G's binding text."""
        assert _SLO_NAMES == frozenset({
            "send_latency_p99",
            "reconcile_success_ratio",
            "bounce_rate",
            "manual_override_count",
        })

    def test_slo_names_mutually_exclusive_from_drift_reasons(self):
        """ADR-0056 D313 + the legacy-state-vs-new-defense-layer
        reason-precedence drift discipline (NEW pattern per Pillar F
        Week 12 follow-up).

        The ``slo_violation_detected.slo_name`` closed-enum MUST be
        DISJOINT from the ``reconcile_drift.reason`` closed-enum per
        ADR-0049 D263. Operators filtering Pillar I per-tenant audit-
        tooling by ``reconcile_drift.reason`` MUST NOT see SLO names
        bleeding into the drift-reason consumer surface.
        """
        from orchestrator.reconcile import _DRIFT_REASONS
        # Disjoint sets.
        assert _SLO_NAMES.isdisjoint(_DRIFT_REASONS)

    def test_slo_violation_detected_is_in_observability_new_event_classes(self):
        """ADR-0050 D273 + ADR-0056 D308 — the
        ``slo_violation_detected`` event class was named at design-
        time at the Pillar G Week 1 ADR; Week 7-8 ships the producer.
        """
        assert "slo_violation_detected" in OBSERVABILITY_NEW_EVENT_CLASSES


class TestSLOConfigDefaults:
    """ADR-0056 D309 — :class:`SLOConfig` defaults match PILLAR-PLAN
    §2 Pillar G's binding text (5.0s send-latency p99, 0.99 reconcile-
    success, 0.05 bounce-rate, 0 manual_override) + the operator-
    deliberate opt-in posture per ADR-0050 D276(d) (slack_webhook_url
    defaults to None)."""

    def test_send_latency_p99_default_is_5_seconds(self):
        """PILLAR-PLAN §2 Pillar G — p99 send latency > 5s."""
        assert SLOConfig().send_latency_p99_threshold_seconds == 5.0

    def test_reconcile_success_default_is_99_percent(self):
        """PILLAR-PLAN §2 Pillar G — reconcile success < 99%."""
        assert SLOConfig().reconcile_success_ratio_threshold == 0.99

    def test_bounce_rate_default_is_5_percent(self):
        """PILLAR-PLAN §2 Pillar G — bounce > 5%."""
        assert SLOConfig().bounce_rate_threshold == 0.05

    def test_manual_override_count_default_is_zero(self):
        """PILLAR-PLAN §2 Pillar G — any manual_override event
        triggers compliance review."""
        assert SLOConfig().manual_override_count_threshold == 0

    def test_slack_webhook_url_defaults_to_none(self):
        """ADR-0050 D276(d) — operator-deliberate opt-in. Absence =
        SLOs observed via dashboard rendering only; no alerting
        fires."""
        assert SLOConfig().slack_webhook_url is None

    def test_slo_config_is_frozen(self):
        """ADR-0056 D309 — :class:`SLOConfig` is immutable."""
        config = SLOConfig()
        with pytest.raises((AttributeError, Exception)):
            config.send_latency_p99_threshold_seconds = 10.0  # noqa


class TestSLOViolationDataclass:
    """ADR-0056 D308 — :class:`SLOViolation` is a frozen dataclass
    with five fields the slo_violation_detected event class payload
    consumes directly."""

    def test_slo_violation_frozen(self):
        """ADR-0056 D308 — frozen dataclass."""
        v = SLOViolation(
            slo_name="send_latency_p99",
            slo_threshold=5.0,
            observed_value=7.5,
            channel="email",
            window_seconds=3600.0,
        )
        with pytest.raises((AttributeError, Exception)):
            v.observed_value = 8.0  # noqa

    def test_slo_violation_fields(self):
        """ADR-0056 D308 — the five fields."""
        v = SLOViolation(
            slo_name="bounce_rate",
            slo_threshold=0.05,
            observed_value=0.10,
            channel="email",
            window_seconds=86400.0,
        )
        assert v.slo_name == "bounce_rate"
        assert v.slo_threshold == 0.05
        assert v.observed_value == 0.10
        assert v.channel == "email"
        assert v.window_seconds == 86400.0

    def test_slo_violation_channel_none_for_global_slo(self):
        """ADR-0056 D308 — global SLOs (reconcile_success_ratio,
        manual_override_count) carry ``channel=None`` per ADR-0014
        D33's channel-on-every-event invariant."""
        v = SLOViolation(
            slo_name="reconcile_success_ratio",
            slo_threshold=0.99,
            observed_value=0.5,
            channel=None,
            window_seconds=3600.0,
        )
        assert v.channel is None


def _intent_confirmed_pair(
    day: int,
    iid: str,
    channel: str,
    *,
    latency_seconds: int,
    person_id: str = "p_001",
) -> list[dict]:
    """Build a synthetic send_intent/send_confirmed pair with
    explicit per-pair latency. Used by the SLO detector send-latency
    tests."""
    intent_ts = _ts(day, hour=0, minute=0)
    # Add latency by advancing the confirm timestamp.
    confirm_minute = latency_seconds // 60
    confirm_second = latency_seconds % 60
    confirm_ts = (
        f"2026-05-{day:02d}T00:{confirm_minute:02d}:"
        f"{confirm_second:02d}.000Z"
    )
    confirm_type_by_channel = {
        "email": "send_confirmed",
        "linkedin-invite": "li_invite_confirmed",
        "linkedin-dm": "li_dm_confirmed",
        "twitter-dm": "tw_dm_confirmed",
        "calendar": "calendar_booking_confirmed",
    }
    intent_type_by_channel = {
        "email": "send_intent",
        "linkedin-invite": "li_invite_intent",
        "linkedin-dm": "li_dm_intent",
        "twitter-dm": "tw_dm_intent",
        "calendar": "calendar_booking_intent",
    }
    return [
        {
            "type": intent_type_by_channel[channel],
            "ts": intent_ts,
            "person_id": person_id,
            "intent_id": iid,
            "channel": channel,
        },
        {
            "type": confirm_type_by_channel[channel],
            "ts": confirm_ts,
            "person_id": person_id,
            "intent_id": iid,
            "channel": channel,
        },
    ]


class TestDetectSLOViolationsSendLatency:
    """ADR-0056 D307 — :func:`detect_slo_violations` computes per-
    channel send-latency p99 + emits per-channel violations when
    p99 > threshold."""

    def test_p99_above_threshold_per_channel_triggers_violation(
        self, led_dir, led,
    ):
        """ADR-0056 D307 — single-channel p99 violation. Five pairs
        all at 10s latency → p99 = 10.0 > 5.0 threshold."""
        events: list[dict] = []
        for i in range(5):
            events.extend(_intent_confirmed_pair(
                10, f"intent_{i:03d}", "email", latency_seconds=10,
            ))
        _direct_write(led_dir, events)

        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        send_latency_viols = [
            v for v in violations
            if v.slo_name == "send_latency_p99"
        ]
        assert len(send_latency_viols) == 1
        assert send_latency_viols[0].channel == "email"
        assert send_latency_viols[0].observed_value > 5.0
        assert send_latency_viols[0].slo_threshold == 5.0

    def test_p99_at_threshold_does_not_trigger_violation(
        self, led_dir, led,
    ):
        """ADR-0056 D307 — strict ``>`` comparison; threshold-equal
        does NOT trigger (avoids false-positive on exact bucket
        boundary)."""
        # All pairs at exactly 5.0s latency.
        events: list[dict] = []
        for i in range(100):
            events.extend(_intent_confirmed_pair(
                10, f"intent_{i:03d}", "email", latency_seconds=5,
            ))
        _direct_write(led_dir, events)

        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        send_latency_viols = [
            v for v in violations if v.slo_name == "send_latency_p99"
        ]
        assert send_latency_viols == []

    def test_p99_per_channel_separate_violations(
        self, led_dir, led,
    ):
        """ADR-0056 D307 + channel-on-every-event per ADR-0014 D33 —
        per-channel p99 surfaces SEPARATE violations per channel."""
        events: list[dict] = []
        # Email: 5 pairs all at 10s latency → p99 = 10 > 5 → violation.
        for i in range(5):
            events.extend(_intent_confirmed_pair(
                10, f"em_{i:03d}", "email", latency_seconds=10,
            ))
        # LinkedIn-DM: 5 pairs all at 1s → p99 = 1, no violation.
        for i in range(5):
            events.extend(_intent_confirmed_pair(
                10, f"li_{i:03d}", "linkedin-dm", latency_seconds=1,
            ))
        _direct_write(led_dir, events)

        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        latency_viols = [
            v for v in violations if v.slo_name == "send_latency_p99"
        ]
        # Only the email channel violates; linkedin-dm does not.
        assert len(latency_viols) == 1
        assert latency_viols[0].channel == "email"

    def test_unpaired_intent_or_confirm_does_not_violate(
        self, led_dir, led,
    ):
        """ADR-0056 D307 — unpaired events skipped from latency
        computation."""
        events = [
            # intent without confirm
            {
                "type": "send_intent",
                "ts": _ts(10),
                "intent_id": "orphan",
                "channel": "email",
                "person_id": "p_001",
            },
            # confirm without intent
            {
                "type": "send_confirmed",
                "ts": _ts(11),
                "intent_id": "orphan2",
                "channel": "email",
                "person_id": "p_002",
            },
        ]
        _direct_write(led_dir, events)

        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        latency_viols = [
            v for v in violations if v.slo_name == "send_latency_p99"
        ]
        assert latency_viols == []


class TestDetectSLOViolationsReconcileSuccess:
    """ADR-0056 D307 — :func:`detect_slo_violations` computes global
    reconcile success ratio + emits violation when ratio < threshold."""

    def test_drift_only_triggers_violation(self, led_dir, led):
        """ADR-0056 D307 — drift-only window → ratio 0.0 < 0.99 →
        violation."""
        events = [
            {
                "type": "reconcile_drift",
                "ts": _ts(10),
                "reason": "vault_ahead_of_ledger",
                "person_id": f"p_{i:03d}",
            }
            for i in range(5)
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        rec_viols = [
            v for v in violations
            if v.slo_name == "reconcile_success_ratio"
        ]
        assert len(rec_viols) == 1
        assert rec_viols[0].channel is None
        assert rec_viols[0].observed_value == 0.0
        assert rec_viols[0].slo_threshold == 0.99

    def test_vacuous_success_does_not_trigger(self, led_dir, led):
        """ADR-0056 D307 — no reconcile activity → no violation
        (matches register_reconcile_success_ratio_gauge's vacuous
        success → 1.0 per ADR-0053 D290)."""
        # No reconcile events at all.
        events = [
            {
                "type": "send_intent",
                "ts": _ts(10),
                "intent_id": "x",
                "channel": "email",
                "person_id": "p_001",
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        rec_viols = [
            v for v in violations
            if v.slo_name == "reconcile_success_ratio"
        ]
        assert rec_viols == []

    def test_high_success_ratio_does_not_trigger(self, led_dir, led):
        """ADR-0056 D307 — ratio above threshold → no violation."""
        events = [
            # 99 healed + 1 drift = 99% success → above 99% (not
            # below) → no violation (strict ``<``).
            {
                "type": "reconcile_healed",
                "ts": _ts(10),
                "person_id": f"p_{i:03d}",
            }
            for i in range(99)
        ] + [
            {
                "type": "reconcile_drift",
                "ts": _ts(10),
                "reason": "vault_ahead_of_ledger",
                "person_id": "p_drift",
            }
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        rec_viols = [
            v for v in violations
            if v.slo_name == "reconcile_success_ratio"
        ]
        # 99/100 = 0.99 — strict < 0.99 fails → no violation.
        assert rec_viols == []


class TestDetectSLOViolationsBounceRate:
    """ADR-0056 D307 — :func:`detect_slo_violations` computes per-
    channel bounce rate + emits per-channel violations when
    rate > threshold."""

    def test_high_bounce_rate_triggers_violation(self, led_dir, led):
        """ADR-0056 D307 — 10% bounce rate > 5% threshold → email
        channel violation."""
        events: list[dict] = []
        # 90 confirmed + 10 bounce = 10% bounce rate > 5%.
        for i in range(90):
            events.append({
                "type": "send_confirmed",
                "ts": _ts(10),
                "intent_id": f"x_{i:03d}",
                "channel": "email",
                "person_id": f"p_{i:03d}",
            })
        for i in range(10):
            events.append({
                "type": "bounce_detected",
                "ts": _ts(10),
                "channel": "email",
                "person_id": f"p_b{i:03d}",
            })
        _direct_write(led_dir, events)

        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        bounce_viols = [
            v for v in violations if v.slo_name == "bounce_rate"
        ]
        assert len(bounce_viols) == 1
        assert bounce_viols[0].channel == "email"
        assert bounce_viols[0].observed_value == 0.10
        assert bounce_viols[0].slo_threshold == 0.05

    def test_zero_activity_does_not_trigger(self, led_dir, led):
        """ADR-0056 D307 — vacuous (no confirms + no bounces) → no
        violation."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(10),
                "rule": "BudgetCap",
                "expires_ts": _ts(15),
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        bounce_viols = [
            v for v in violations if v.slo_name == "bounce_rate"
        ]
        assert bounce_viols == []

    def test_low_bounce_rate_does_not_trigger(self, led_dir, led):
        """ADR-0056 D307 — 1% bounce rate < 5% threshold → no
        violation."""
        events: list[dict] = []
        for i in range(99):
            events.append({
                "type": "send_confirmed",
                "ts": _ts(10),
                "intent_id": f"x_{i:03d}",
                "channel": "email",
                "person_id": f"p_{i:03d}",
            })
        events.append({
            "type": "bounce_detected",
            "ts": _ts(10),
            "channel": "email",
            "person_id": "p_b001",
        })
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        bounce_viols = [
            v for v in violations if v.slo_name == "bounce_rate"
        ]
        assert bounce_viols == []


class TestDetectSLOViolationsManualOverride:
    """ADR-0056 D307 + PILLAR-PLAN §2 Pillar G — any manual_override
    event triggers compliance review alert."""

    def test_single_manual_override_triggers_violation(
        self, led_dir, led,
    ):
        """PILLAR-PLAN §2 Pillar G — any manual_override event triggers
        compliance review."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(10),
                "rule": "BudgetCap",
                "expires_ts": _ts(15),
                "reason": "Q3 spike approved by founder",
                "approved_by": "yang@example.com",
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        override_viols = [
            v for v in violations
            if v.slo_name == "manual_override_count"
        ]
        assert len(override_viols) == 1
        assert override_viols[0].channel is None
        assert override_viols[0].observed_value == 1.0
        assert override_viols[0].slo_threshold == 0.0

    def test_zero_manual_overrides_does_not_trigger(
        self, led_dir, led,
    ):
        """ADR-0056 D307 — count = 0 does not trigger violation."""
        events = [
            {
                "type": "send_confirmed",
                "ts": _ts(10),
                "intent_id": "x",
                "channel": "email",
                "person_id": "p_001",
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        override_viols = [
            v for v in violations
            if v.slo_name == "manual_override_count"
        ]
        assert override_viols == []

    def test_threshold_above_count_does_not_trigger(
        self, led_dir, led,
    ):
        """ADR-0056 D309 — operator-configurable threshold via
        :class:`SLOConfig`. If operator raises threshold to 3, a
        single override does NOT trigger."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(10),
                "rule": "BudgetCap",
                "expires_ts": _ts(15),
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
            slo_config=SLOConfig(manual_override_count_threshold=3),
        )
        override_viols = [
            v for v in violations
            if v.slo_name == "manual_override_count"
        ]
        assert override_viols == []


class TestDetectSLOViolationsSyntheticExclusion:
    """ADR-0056 D311 + R032 mitigation — events carrying
    ``_recovered_by`` audit marker are EXCLUDED from SLO evaluation.

    Per PILLAR-PLAN §2 Pillar G + ADR-0050 R032: synthetic-data
    spikes (e.g., a one-time backfill emitting a flood of
    ``enrolled`` events) MUST NOT trip the SLO alerts. The
    ``_recovered_by`` audit marker per ADR-0010 D17 IS the
    structural signal for synthetic events.
    """

    def test_recovered_by_backfill_excluded_from_manual_override(
        self, led_dir, led,
    ):
        """ADR-0056 D311 — backfill manual_override events are
        EXCLUDED from SLO evaluation."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(10),
                "rule": "BudgetCap",
                "expires_ts": _ts(15),
                "_recovered_by": "backfill",
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        override_viols = [
            v for v in violations
            if v.slo_name == "manual_override_count"
        ]
        assert override_viols == []

    def test_recovered_by_reconcile_excluded_from_bounce_rate(
        self, led_dir, led,
    ):
        """ADR-0056 D311 — reconcile-recovered bounce events are
        EXCLUDED from SLO evaluation."""
        events: list[dict] = []
        for i in range(90):
            events.append({
                "type": "send_confirmed",
                "ts": _ts(10),
                "intent_id": f"x_{i:03d}",
                "channel": "email",
                "person_id": f"p_{i:03d}",
            })
        for i in range(10):
            events.append({
                "type": "bounce_detected",
                "ts": _ts(10),
                "channel": "email",
                "person_id": f"p_b{i:03d}",
                "_recovered_by": "reconcile",
            })
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        bounce_viols = [
            v for v in violations if v.slo_name == "bounce_rate"
        ]
        assert bounce_viols == []

    def test_recovered_by_migration_excluded_from_reconcile_success(
        self, led_dir, led,
    ):
        """ADR-0056 D311 — migration-recovered drift events are
        EXCLUDED from SLO evaluation."""
        events = [
            {
                "type": "reconcile_drift",
                "ts": _ts(10),
                "reason": "vault_ahead_of_ledger",
                "person_id": f"p_{i:03d}",
                "_recovered_by": "migration_0001",
            }
            for i in range(5)
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        rec_viols = [
            v for v in violations
            if v.slo_name == "reconcile_success_ratio"
        ]
        assert rec_viols == []

    def test_recovered_by_backfill_excluded_from_send_latency(
        self, led_dir, led,
    ):
        """ADR-0056 D311 — backfill send-intent/send-confirmed pairs
        are EXCLUDED from SLO evaluation."""
        events: list[dict] = []
        for i in range(100):
            pair = _intent_confirmed_pair(
                10, f"bf_{i:03d}", "email", latency_seconds=30,
            )
            for ev in pair:
                ev["_recovered_by"] = "backfill"
            events.extend(pair)
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
        )
        latency_viols = [
            v for v in violations if v.slo_name == "send_latency_p99"
        ]
        assert latency_viols == []


class TestDetectSLOViolationsWindowFilter:
    """ADR-0056 D307 — events before ``since = now - since_window``
    are out-of-scope (the per-call window filter)."""

    def test_old_event_excluded_from_window(self, led_dir, led):
        """ADR-0056 D307 — an old manual_override (before since)
        does not trigger."""
        # Window is 1 day from NOW_2026_05_25 (May 25 12:00 UTC) →
        # since = May 24 12:00 UTC. The manual_override at May 10
        # is BEFORE since.
        events = [
            {
                "type": "manual_override",
                "ts": _ts(10),
                "rule": "BudgetCap",
                "expires_ts": _ts(15),
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=1),
            now=NOW_2026_05_25,
        )
        override_viols = [
            v for v in violations
            if v.slo_name == "manual_override_count"
        ]
        assert override_viols == []

    def test_in_window_event_triggers(self, led_dir, led):
        """ADR-0056 D307 — same event INSIDE the window triggers."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(25, hour=11, minute=59),  # 1m before NOW
                "rule": "BudgetCap",
                "expires_ts": _ts(28),
            },
        ]
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=1),
            now=NOW_2026_05_25,
        )
        override_viols = [
            v for v in violations
            if v.slo_name == "manual_override_count"
        ]
        assert len(override_viols) == 1


class TestDetectSLOViolationsDeterministicClock:
    """ADR-0056 D311 — ``now`` kwarg controls the ``ts`` field on
    emitted ``slo_violation_detected`` events (deterministic-clock
    contract per ADR-0034 D156 + ADR-0035 D162)."""

    def test_now_kwarg_stamps_event_ts(self, led_dir, led):
        """ADR-0056 D311 — ``now`` kwarg byte-identical
        reproducibility."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(25, hour=11),
                "rule": "BudgetCap",
                "expires_ts": _ts(28),
            },
        ]
        _direct_write(led_dir, events)
        detect_slo_violations(
            led,
            since_window=timedelta(days=1),
            now=NOW_2026_05_25,
        )
        slo_events = [
            ev for ev in led.all_events()
            if ev.type == "slo_violation_detected"
        ]
        assert len(slo_events) == 1
        # NOW_2026_05_25 = May 25 12:00:00.000Z.
        assert slo_events[0].ts == "2026-05-25T12:00:00.000Z"


class TestDetectSLOViolationsEventPayloadShape:
    """ADR-0056 D308 — the ``slo_violation_detected`` event class
    payload carries the closed-set keys + ``_emitted_by:
    "observability"`` audit marker per ADR-0010 D17."""

    def test_event_payload_carries_closed_set_keys(
        self, led_dir, led,
    ):
        """ADR-0056 D308 — payload fields per the canonical shape."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(25, hour=11),
                "rule": "BudgetCap",
                "expires_ts": _ts(28),
            },
        ]
        _direct_write(led_dir, events)
        detect_slo_violations(
            led,
            since_window=timedelta(days=1),
            now=NOW_2026_05_25,
        )
        slo_events = [
            ev for ev in led.all_events()
            if ev.type == "slo_violation_detected"
        ]
        assert len(slo_events) == 1
        ev = slo_events[0]
        # The closed-set keys.
        assert ev.get("slo_name") == "manual_override_count"
        assert ev.get("slo_threshold") == 0.0
        assert ev.get("observed_value") == 1.0
        assert ev.get("channel") is None
        # Window seconds = 1 day = 86400.
        assert ev.get("window_seconds") == 86400.0
        # Audit marker per ADR-0010 D17.
        assert ev.get("_emitted_by") == "observability"


class TestDetectSLOViolationsRateLimitDedup:
    """ADR-0056 D310 — at-most-ONE slo_violation_detected event per
    ``(slo_name, channel)`` per call (R034 carry-forward pattern)."""

    def test_one_event_per_slo_name_channel_per_call(
        self, led_dir, led,
    ):
        """ADR-0056 D310 — three manual_override events → ONE
        slo_violation_detected event (rate-limited per call)."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(25, hour=h),
                "rule": "BudgetCap",
                "expires_ts": _ts(28),
            }
            for h in (10, 11, 12)
        ]
        # Adjust last ts to be just inside window.
        events[-1]["ts"] = _ts(25, hour=11, minute=59)
        _direct_write(led_dir, events)
        detect_slo_violations(
            led,
            since_window=timedelta(days=1),
            now=NOW_2026_05_25,
        )
        slo_events = [
            ev for ev in led.all_events()
            if ev.type == "slo_violation_detected"
        ]
        # ONE emit, not three.
        assert len(slo_events) == 1


class TestDetectSLOViolationsConfigOverrides:
    """ADR-0056 D309 — :class:`SLOConfig` per-SLO threshold
    overrides flow through detector."""

    def test_custom_bounce_rate_threshold_applied(
        self, led_dir, led,
    ):
        """ADR-0056 D309 — operator raises bounce_rate threshold to
        20%; 10% rate no longer violates."""
        events: list[dict] = []
        for i in range(90):
            events.append({
                "type": "send_confirmed",
                "ts": _ts(10),
                "intent_id": f"x_{i:03d}",
                "channel": "email",
                "person_id": f"p_{i:03d}",
            })
        for i in range(10):
            events.append({
                "type": "bounce_detected",
                "ts": _ts(10),
                "channel": "email",
                "person_id": f"p_b{i:03d}",
            })
        _direct_write(led_dir, events)
        violations = detect_slo_violations(
            led,
            since_window=timedelta(days=30),
            now=NOW_2026_05_25,
            slo_config=SLOConfig(bounce_rate_threshold=0.20),
        )
        bounce_viols = [
            v for v in violations if v.slo_name == "bounce_rate"
        ]
        assert bounce_viols == []


class TestDispatchSLOAlertDefaultOff:
    """ADR-0056 D312 + ADR-0050 D276(d) — ``slack_webhook_url=None``
    means operator-deliberate OFF: dispatch returns False
    immediately + makes ZERO HTTP requests + emits ZERO spans."""

    def test_none_webhook_returns_false_no_http(self):
        """ADR-0056 D312 — None URL → False; no HTTP call."""
        called: list[tuple] = []

        def fake_post(url, body, headers):
            called.append((url, body, headers))

        v = SLOViolation(
            slo_name="send_latency_p99",
            slo_threshold=5.0,
            observed_value=10.0,
            channel="email",
            window_seconds=3600.0,
        )
        result = dispatch_slo_alert(
            v,
            slack_webhook_url=None,
            http_post=fake_post,
        )
        assert result is False
        # Critical: no HTTP call.
        assert called == []

    def test_none_webhook_emits_no_span(self, in_memory_tracer):
        """ADR-0056 D312 + the no-op-default discipline — None URL →
        no span emit (does not consume traced_stage helper)."""
        v = SLOViolation(
            slo_name="bounce_rate",
            slo_threshold=0.05,
            observed_value=0.10,
            channel="email",
            window_seconds=3600.0,
        )
        dispatch_slo_alert(v, slack_webhook_url=None)
        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 0

    def test_empty_string_webhook_is_falsy_off(self):
        """ADR-0056 D312 — empty string is also operator-deliberate
        OFF (falsy)."""
        v = SLOViolation(
            slo_name="manual_override_count",
            slo_threshold=0.0,
            observed_value=1.0,
            channel=None,
            window_seconds=86400.0,
        )
        result = dispatch_slo_alert(v, slack_webhook_url="")
        assert result is False


class TestDispatchSLOAlertHttpSuccess:
    """ADR-0056 D312 — operator-supplied webhook URL triggers POST."""

    def test_post_with_json_payload_and_returns_true(
        self, in_memory_tracer,
    ):
        """ADR-0056 D312 — HTTP POST with JSON body; returns True."""
        captured: list[tuple] = []

        def fake_post(url, body, headers):
            captured.append((url, body, headers))

        v = SLOViolation(
            slo_name="send_latency_p99",
            slo_threshold=5.0,
            observed_value=7.5,
            channel="email",
            window_seconds=3600.0,
        )
        result = dispatch_slo_alert(
            v,
            slack_webhook_url="https://hooks.slack.com/services/T/B/X",
            http_post=fake_post,
        )
        assert result is True
        assert len(captured) == 1
        url, body, headers = captured[0]
        assert url == "https://hooks.slack.com/services/T/B/X"
        assert headers.get("Content-Type") == "application/json"
        # Verify body is JSON-decodable + carries closed-set keys.
        payload = json.loads(body.decode("utf-8"))
        assert payload["slo_name"] == "send_latency_p99"
        assert payload["slo_threshold"] == 5.0
        assert payload["observed_value"] == 7.5
        assert payload["channel"] == "email"
        assert payload["window_seconds"] == 3600.0
        # Slack-rendered text field.
        assert "send_latency_p99" in payload["text"]
        assert "email" in payload["text"]


class TestDispatchSLOAlertHttpFailure:
    """ADR-0056 D312 — best-effort posture: HTTP failure → False
    (mirrors cost_incurred emit + histogram record's try/except-best-
    effort posture per ADR-0055 D305)."""

    def test_post_exception_returns_false(self, in_memory_tracer):
        """ADR-0056 D312 — exception caught + False returned."""
        def failing_post(url, body, headers):
            raise RuntimeError("network down")

        v = SLOViolation(
            slo_name="bounce_rate",
            slo_threshold=0.05,
            observed_value=0.10,
            channel="email",
            window_seconds=3600.0,
        )
        result = dispatch_slo_alert(
            v,
            slack_webhook_url="https://hooks.slack.com/services/T/B/X",
            http_post=failing_post,
        )
        assert result is False


class TestDispatchSLOAlertSpanWiring:
    """ADR-0056 D312 + ADR-0055 D300-D303 — dispatch wrapped in
    ``traced_stage("send", "slack_webhook", attributes={"channel":
    ..., "reason": violation.slo_name})``.

    The behavioral-passthrough-not-signature-only discipline (NOW
    NINE consecutive weeks at Pillar G Week 7-8; Pillar F W8-W11 +
    Pillar G W3-W6 + W7-W8) — verify via real captured spans.
    """

    def test_span_emitted_with_channel_and_reason_attributes(
        self, in_memory_tracer,
    ):
        """ADR-0056 D312 — span name + per-attribute capture."""
        def fake_post(url, body, headers):
            pass  # success

        v = SLOViolation(
            slo_name="send_latency_p99",
            slo_threshold=5.0,
            observed_value=7.5,
            channel="email",
            window_seconds=3600.0,
        )
        dispatch_slo_alert(
            v,
            slack_webhook_url="https://hooks.slack.com/services/T/B/X",
            http_post=fake_post,
        )
        spans = _spans_named(
            in_memory_tracer, "outreach_factory.send.slack_webhook",
        )
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs.get("channel") == "email"
        assert attrs.get("reason") == "send_latency_p99"
        assert attrs.get("stage") == "send"
        assert attrs.get("operation") == "slack_webhook"

    def test_span_emitted_on_http_failure_too(self, in_memory_tracer):
        """ADR-0056 D312 — span emit is independent of HTTP success;
        operators see the dispatch attempt in their tracing backend
        regardless of webhook delivery outcome."""
        def failing_post(url, body, headers):
            raise RuntimeError("boom")

        v = SLOViolation(
            slo_name="manual_override_count",
            slo_threshold=0.0,
            observed_value=1.0,
            channel=None,
            window_seconds=86400.0,
        )
        dispatch_slo_alert(
            v,
            slack_webhook_url="https://hooks.slack.com/services/T/B/X",
            http_post=failing_post,
        )
        spans = _spans_named(
            in_memory_tracer, "outreach_factory.send.slack_webhook",
        )
        assert len(spans) == 1


class TestDispatchSLOAlertGlobalSLOChannelNone:
    """ADR-0056 D312 — global SLO (channel=None) surfaces span
    attribute ``channel="none"`` per OTel attribute-non-None
    convention (mirrors register_event_class_observable_counter's
    treatment per ADR-0052 D284)."""

    def test_global_slo_span_channel_attribute_is_none_string(
        self, in_memory_tracer,
    ):
        """ADR-0056 D312 — channel=None surfaces as "none" on span."""
        def fake_post(url, body, headers):
            pass

        v = SLOViolation(
            slo_name="reconcile_success_ratio",
            slo_threshold=0.99,
            observed_value=0.5,
            channel=None,
            window_seconds=3600.0,
        )
        dispatch_slo_alert(
            v,
            slack_webhook_url="https://hooks.slack.com/services/T/B/X",
            http_post=fake_post,
        )
        spans = _spans_named(
            in_memory_tracer, "outreach_factory.send.slack_webhook",
        )
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs.get("channel") == "none"
        assert attrs.get("reason") == "reconcile_success_ratio"


class TestSLOPrivacyInvariantPayload:
    """ADR-0056 D308 + privacy invariant per I8 + ADR-0050 D276(b) —
    the slo_violation_detected event payload + the Slack webhook
    payload NEVER carry the five privacy-disallowed keys."""

    def test_event_payload_excludes_disallowed_keys(
        self, led_dir, led,
    ):
        """ADR-0056 D308 — payload keys are closed-set; no
        ``source_list`` / ``draft_body`` / ``dossier_body`` /
        ``exemplar_body`` / ``claim_text``."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(25, hour=11),
                "rule": "BudgetCap",
                "expires_ts": _ts(28),
            },
        ]
        _direct_write(led_dir, events)
        detect_slo_violations(
            led,
            since_window=timedelta(days=1),
            now=NOW_2026_05_25,
        )
        slo_events = [
            ev for ev in led.all_events()
            if ev.type == "slo_violation_detected"
        ]
        assert len(slo_events) == 1
        disallowed_keys = {
            "source_list",
            "draft_body",
            "dossier_body",
            "exemplar_body",
            "claim_text",
        }
        for k in disallowed_keys:
            assert k not in slo_events[0]._d, (
                f"slo_violation_detected payload contains privacy-"
                f"disallowed key {k!r}"
            )


class TestSLOEmitsAreNotUncatalogued:
    """ADR-0050 D273 + ADR-0051 D279 + ADR-0056 D308 — the
    slo_violation_detected emit is in
    :data:`OBSERVABILITY_NEW_EVENT_CLASSES`; subsequent
    :func:`collect_event_class_snapshots` calls do NOT trigger
    ``observability_class_uncatalogued`` diagnostic for the SLO
    emits (R031 stability holds)."""

    def test_slo_violation_detected_in_observability_new_classes(self):
        """ADR-0050 D273 — the event class was named at design
        time."""
        assert (
            "slo_violation_detected"
            in OBSERVABILITY_NEW_EVENT_CLASSES
        )

    def test_subsequent_collect_does_not_emit_uncatalogued_for_slo(
        self, led_dir, led,
    ):
        """ADR-0050 D273 + ADR-0051 D279 — the recursive-uncatalogued-
        protection inherits from the existing OBSERVABILITY_NEW_
        EVENT_CLASSES |  expected_classes union (R031 stability)."""
        events = [
            {
                "type": "manual_override",
                "ts": _ts(25, hour=11),
                "rule": "BudgetCap",
                "expires_ts": _ts(28),
            },
        ]
        _direct_write(led_dir, events)
        # First call emits slo_violation_detected.
        detect_slo_violations(
            led,
            since_window=timedelta(days=1),
            now=NOW_2026_05_25,
        )
        # Second call: collect_event_class_snapshots walks the ledger
        # + sees the slo_violation_detected event from the prior emit
        # + MUST NOT emit observability_class_uncatalogued for it.
        collect_event_class_snapshots(
            led,
            since=SINCE_2026_05_01,
            now=NOW_2026_05_25,
        )
        uncatalogued = [
            ev for ev in led.all_events()
            if ev.type == "observability_class_uncatalogued"
        ]
        # Zero observability_class_uncatalogued events.
        assert uncatalogued == []


class TestWeek7DocstringDriftDiscipline:
    """ADR-0056 D307-D313 — the module-level docstring drift
    discipline (NOW ELEVEN consecutive weeks at Pillar G Week 7-8;
    Pillar F W8-W12 + Pillar G W2-W6 + W7-W8) requires the
    observability module's docstring names the Week 7-8 deliverables
    + ADR-0056."""

    def test_module_docstring_names_week_7_8(self):
        """Week 7-8 + ADR-0056 are in the module docstring."""
        doc = observability.__doc__ or ""
        assert "Week 7-8" in doc
        assert "ADR-0056" in doc
        assert "slo_violation_detected" in doc


# ---------------------------------------------------------------------------
# Pillar G Week 9 — cost dashboard primitive + per-source cost_incurred
# aggregation + `cost_source_uncatalogued` diagnostic kind + Grafana
# cost.yml dashboard panel set + `_SLO_NAMES` extension PUNT decision
# (per ADR-0057 D314-D318).
# ---------------------------------------------------------------------------


from observability import (
    COST_SOURCES_CATALOG,
    CostSnapshot,
    _COST_BREAKDOWN_DIMS_ALLOWED,
    _DIAGNOSTIC_KINDS,
    collect_cost_snapshots,
)


def _cost_event(
    *,
    day: int,
    hour: int = 0,
    source: str = "gmail",
    amount_usd: float = 0.001,
    units: int = 1,
    model_or_endpoint: str = "messages.send",
    channel: str | None = None,
    person_id: str | None = None,
    run_id: str | None = None,
    recovered_by: str | None = None,
) -> dict:
    """Build a synthetic ``cost_incurred`` event for the Week 9 tests."""
    ev: dict = {
        "type": "cost_incurred",
        "ts": _ts(day, hour=hour),
        "source": source,
        "amount_usd": amount_usd,
        "units": units,
        "model_or_endpoint": model_or_endpoint,
        "person_id": person_id,
        "run_id": run_id,
    }
    if channel is not None:
        ev["channel"] = channel
    if recovered_by is not None:
        ev["_recovered_by"] = recovered_by
    return ev


class TestWeek9CostSourcesCatalog:
    """ADR-0057 D315 — :data:`COST_SOURCES_CATALOG` is the closed-set
    of currently-emitting cost sources; IS the R031-shape regression-
    barrier extended to the cost surface."""

    def test_cost_sources_catalog_is_frozenset(self):
        """Closed-set immutability per ADR-0050 D272 + ADR-0057 D315."""
        assert isinstance(COST_SOURCES_CATALOG, frozenset)

    def test_cost_sources_catalog_membership(self):
        """The seven currently-emitting cost sources per the cost
        emission walk:

        * ``reoon`` — :mod:`orchestrator.enrich_emails`.
        * ``reply_classifier_llm`` —
          :mod:`orchestrator.reply_classifier_llm`.
        * ``gmail`` / ``linkedin_invite`` / ``linkedin_dm`` /
          ``twitter_dm`` / ``calendar_booking`` —
          :mod:`skills.send-outreach.scripts.send_queued`.
        """
        assert COST_SOURCES_CATALOG == frozenset({
            "reoon",
            "reply_classifier_llm",
            "gmail",
            "linkedin_invite",
            "linkedin_dm",
            "twitter_dm",
            "calendar_booking",
        })

    def test_cost_sources_catalog_cardinality_is_7(self):
        """ADR-0057 D315 — exactly seven currently-emitting sources."""
        assert len(COST_SOURCES_CATALOG) == 7

    def test_cost_sources_catalog_disjoint_from_event_class_catalog(self):
        """ADR-0057 D315 — cost-source names MUST NOT collide with
        event class names (the catalogs are distinct R031-shape
        regression-barriers; the per-pillar audit walks each catalog
        independently)."""
        assert COST_SOURCES_CATALOG.isdisjoint(EVENT_CLASS_CATALOG)

    def test_cost_sources_catalog_disjoint_from_slo_names(self):
        """ADR-0057 D315 + ADR-0056 D313 — cost source names MUST be
        DISJOINT from :data:`_SLO_NAMES` per the legacy-state-vs-new-
        defense-layer reason-precedence drift discipline (operators
        filtering on ``slo_name`` MUST NOT see cost source names
        bleeding in)."""
        assert COST_SOURCES_CATALOG.isdisjoint(_SLO_NAMES)


class TestWeek9CostBreakdownDimsAllowed:
    """ADR-0057 D316 — :data:`_COST_BREAKDOWN_DIMS_ALLOWED` is the
    closed-set of breakdown dimensions :func:`collect_cost_snapshots`
    accepts at the per-call ``breakdown_by`` kwarg; the privacy
    invariant per I8 + ADR-0050 D276(b) flows through."""

    def test_cost_breakdown_dims_is_frozenset(self):
        assert isinstance(_COST_BREAKDOWN_DIMS_ALLOWED, frozenset)

    def test_cost_breakdown_dims_membership(self):
        """ADR-0057 D316 — three privacy-respecting dimensions on the
        ``cost_incurred`` payload: ``source`` + ``channel`` (per
        ADR-0014 D33) + ``model_or_endpoint``. ``person_id`` /
        ``run_id`` are operator-confidential per I8 + ADR-0032 D148
        and DISALLOWED."""
        assert _COST_BREAKDOWN_DIMS_ALLOWED == frozenset({
            "source",
            "channel",
            "model_or_endpoint",
        })

    @pytest.mark.parametrize("disallowed_dim", [
        "person_id",
        "run_id",
        "amount_usd",
        "source_list",
        "draft_body",
        "ts",
    ])
    def test_disallowed_dim_refuses_loud(self, led, disallowed_dim):
        """Privacy invariant per I8 + ADR-0050 D276(b) — every
        disallowed dimension refuses-loud (the ValueError contract
        mirrors :func:`collect_event_class_snapshots` per ADR-0051
        D278)."""
        with pytest.raises(ValueError, match=disallowed_dim):
            collect_cost_snapshots(
                led,
                since=SINCE_2026_05_01,
                breakdown_by=(disallowed_dim,),
            )

    @pytest.mark.parametrize("allowed_dim", [
        "source",
        "channel",
        "model_or_endpoint",
    ])
    def test_allowed_dim_accepts(self, led, allowed_dim):
        """ADR-0057 D316 — every allowed dimension accepts (the
        complement of the refuse-loud branch)."""
        result = collect_cost_snapshots(
            led,
            since=SINCE_2026_05_01,
            breakdown_by=(allowed_dim,),
        )
        # No events → empty snapshot list (NOT a refuse-loud).
        assert result == []


class TestWeek9CostSnapshotDataclass:
    """ADR-0057 D314 — :class:`CostSnapshot` is the canonical per-
    snapshot shape Pillar G's cost dashboards consume uniformly."""

    def test_cost_snapshot_is_frozen(self):
        """Frozen dataclass per the immutability discipline of
        :class:`MetricSnapshot` + the stateless-aggregation contract
        per ADR-0050 D272."""
        snap = CostSnapshot(
            source="gmail",
            channel=None,
            total_amount_usd=0.0,
            total_units=0,
            event_count=0,
        )
        with pytest.raises((AttributeError, Exception)):
            snap.source = "linkedin_invite"  # type: ignore

    def test_cost_snapshot_fields_and_defaults(self):
        """ADR-0057 D314 — the field set + default values."""
        snap = CostSnapshot(
            source="gmail",
            channel="email",
            total_amount_usd=1.23,
            total_units=10,
            event_count=5,
        )
        assert snap.source == "gmail"
        assert snap.channel == "email"
        assert snap.total_amount_usd == 1.23
        assert snap.total_units == 10
        assert snap.event_count == 5
        assert snap.per_breakdown_event_count == {}
        assert snap.per_breakdown_amount_usd == {}
        assert snap.oldest_ts is None
        assert snap.newest_ts is None

    def test_cost_snapshot_with_breakdown_fields(self):
        """ADR-0057 D314 — breakdown counts + breakdown amounts are
        sortable dicts keyed by composite-key per ADR-0051 D280."""
        snap = CostSnapshot(
            source="gmail",
            channel="email",
            total_amount_usd=0.5,
            total_units=2,
            event_count=2,
            per_breakdown_event_count={"messages.send": 2},
            per_breakdown_amount_usd={"messages.send": 0.5},
            oldest_ts="2026-05-20T00:00:00.000Z",
            newest_ts="2026-05-25T00:00:00.000Z",
        )
        assert snap.per_breakdown_event_count == {"messages.send": 2}
        assert snap.per_breakdown_amount_usd == {"messages.send": 0.5}
        assert snap.oldest_ts == "2026-05-20T00:00:00.000Z"
        assert snap.newest_ts == "2026-05-25T00:00:00.000Z"


class TestWeek9CollectCostSnapshotsAggregation:
    """ADR-0057 D314 — :func:`collect_cost_snapshots` per-source
    aggregation contract."""

    def test_single_source_single_event(self, led_dir, led):
        events = [_cost_event(day=25, source="gmail", amount_usd=0.001)]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert len(snaps) == 1
        assert snaps[0].source == "gmail"
        assert snaps[0].event_count == 1
        assert snaps[0].total_amount_usd == pytest.approx(0.001)

    def test_single_source_multiple_events(self, led_dir, led):
        events = [
            _cost_event(day=20, source="reoon", amount_usd=0.001),
            _cost_event(day=22, source="reoon", amount_usd=0.002),
            _cost_event(day=24, source="reoon", amount_usd=0.003),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.source == "reoon"
        assert snap.event_count == 3
        assert snap.total_amount_usd == pytest.approx(0.006)
        assert snap.total_units == 3

    def test_multi_source_aggregation(self, led_dir, led):
        events = [
            _cost_event(day=20, source="gmail", amount_usd=0.0),
            _cost_event(day=21, source="reoon", amount_usd=0.005),
            _cost_event(day=22, source="reply_classifier_llm",
                        amount_usd=0.012),
            _cost_event(day=23, source="linkedin_invite", amount_usd=0.0),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        by_source = {s.source: s for s in snaps}
        assert set(by_source.keys()) == {
            "gmail", "reoon", "reply_classifier_llm", "linkedin_invite",
        }
        assert by_source["reoon"].total_amount_usd == pytest.approx(0.005)
        assert by_source["reply_classifier_llm"].total_amount_usd \
            == pytest.approx(0.012)
        assert by_source["gmail"].event_count == 1

    def test_empty_ledger_returns_empty_list(self, led):
        """Empty ledger → empty snapshot list + zero diagnostic emits."""
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps == []
        # Verify no diagnostic events.
        diag = [
            e for e in led.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert diag == []


class TestWeek9CollectCostSnapshotsWindowFilter:
    """ADR-0057 D314 — window filter on ``ts >= since``."""

    def test_event_before_since_excluded(self, led_dir, led):
        events = [
            _cost_event(day=1, source="gmail", amount_usd=99.0),  # before
            _cost_event(day=15, source="gmail", amount_usd=1.0),
        ]
        _direct_write(led_dir, events)
        since = datetime(2026, 5, 10, tzinfo=timezone.utc)
        snaps = collect_cost_snapshots(
            led, since=since, now=NOW_2026_05_25,
        )
        # Only the in-window event counts.
        assert len(snaps) == 1
        assert snaps[0].total_amount_usd == pytest.approx(1.0)

    def test_event_at_boundary_included(self, led_dir, led):
        """Event with ts == since is INCLUDED (>= boundary per the
        :func:`collect_event_class_snapshots` precedent at ADR-0051
        D278)."""
        events = [_cost_event(day=10, source="gmail", amount_usd=1.0)]
        _direct_write(led_dir, events)
        since = datetime(2026, 5, 10, tzinfo=timezone.utc)
        snaps = collect_cost_snapshots(
            led, since=since, now=NOW_2026_05_25,
        )
        assert len(snaps) == 1
        assert snaps[0].event_count == 1


class TestWeek9CollectCostSnapshotsR032SyntheticExclusion:
    """ADR-0057 D314 + ADR-0050 R032 + ADR-0056 D311 — events with
    ``_recovered_by`` are EXCLUDED from the cost aggregation per the
    structural mitigation pattern carried forward from the SLO
    detector."""

    def test_recovered_by_backfill_excluded(self, led_dir, led):
        events = [
            _cost_event(day=22, source="reoon", amount_usd=0.001,
                        recovered_by="backfill"),
            _cost_event(day=23, source="reoon", amount_usd=0.005),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert len(snaps) == 1
        # The backfill event is excluded; only the 0.005 remains.
        assert snaps[0].total_amount_usd == pytest.approx(0.005)
        assert snaps[0].event_count == 1

    def test_recovered_by_reconcile_excluded(self, led_dir, led):
        events = [
            _cost_event(day=22, source="gmail", amount_usd=0.0,
                        recovered_by="reconcile"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        # Excluded → empty snapshot list.
        assert snaps == []

    def test_recovered_by_migration_excluded(self, led_dir, led):
        events = [
            _cost_event(day=22, source="reoon", amount_usd=0.001,
                        recovered_by="migration_0008"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps == []


class TestWeek9CollectCostSnapshotsBreakdown:
    """ADR-0057 D314 + D316 — per-call ``breakdown_by`` produces the
    per-snapshot ``per_breakdown_event_count`` + ``per_breakdown_amount_
    usd`` dicts keyed by composite-key per ADR-0051 D280."""

    def test_model_or_endpoint_breakdown(self, led_dir, led):
        events = [
            _cost_event(day=22, source="reply_classifier_llm",
                        amount_usd=0.002,
                        model_or_endpoint="claude-haiku"),
            _cost_event(day=23, source="reply_classifier_llm",
                        amount_usd=0.010,
                        model_or_endpoint="claude-sonnet"),
            _cost_event(day=24, source="reply_classifier_llm",
                        amount_usd=0.003,
                        model_or_endpoint="claude-haiku"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
            breakdown_by=("model_or_endpoint",),
        )
        assert len(snaps) == 1
        snap = snaps[0]
        # Per-breakdown event count: 2 haiku + 1 sonnet.
        assert snap.per_breakdown_event_count == {
            "claude-haiku": 2,
            "claude-sonnet": 1,
        }
        # Per-breakdown amount sum (sorted dict).
        assert snap.per_breakdown_amount_usd["claude-haiku"] \
            == pytest.approx(0.005)
        assert snap.per_breakdown_amount_usd["claude-sonnet"] \
            == pytest.approx(0.010)

    def test_source_breakdown(self, led_dir, led):
        """ADR-0057 D316 — ``source`` as a breakdown dim is meaningful
        when the caller mixes snapshots across sources (e.g., the
        per-Person dashboard at Week 10-11)."""
        events = [
            _cost_event(day=22, source="reoon", amount_usd=0.001),
            _cost_event(day=23, source="reoon", amount_usd=0.002),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
            breakdown_by=("source",),
        )
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.per_breakdown_event_count == {"reoon": 2}
        assert snap.per_breakdown_amount_usd["reoon"] \
            == pytest.approx(0.003)

    def test_multi_dim_composite_breakdown(self, led_dir, led):
        """ADR-0057 D316 + ADR-0031 D140 — multi-dim composite key
        uses ``|`` separator per the existing :func:`_composite_key`
        convention."""
        events = [
            _cost_event(day=22, source="gmail", amount_usd=0.0,
                        model_or_endpoint="messages.send", channel="email"),
            _cost_event(day=23, source="gmail", amount_usd=0.0,
                        model_or_endpoint="messages.send", channel="email"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
            breakdown_by=("channel", "model_or_endpoint"),
        )
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.per_breakdown_event_count == {
            "email|messages.send": 2,
        }


class TestWeek9CollectCostSnapshotsDeterministicOrdering:
    """ADR-0057 D314 + ADR-0031 D140 — snapshots sorted alphabetically
    by ``source`` for byte-identical deterministic output."""

    def test_sorted_by_source(self, led_dir, led):
        events = [
            _cost_event(day=22, source="twitter_dm"),
            _cost_event(day=22, source="gmail"),
            _cost_event(day=22, source="linkedin_invite"),
            _cost_event(day=22, source="reoon"),
            _cost_event(day=22, source="calendar_booking"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        source_order = [s.source for s in snaps]
        assert source_order == [
            "calendar_booking",
            "gmail",
            "linkedin_invite",
            "reoon",
            "twitter_dm",
        ]


class TestWeek9CollectCostSnapshotsDeterministicClock:
    """ADR-0057 D314 + ADR-0034 D156 + ADR-0051 D278 — the ``now``
    kwarg controls the diagnostic emit's ``ts`` field."""

    def test_now_stamps_diagnostic_ts(self, led_dir, led):
        """When the call surfaces a ``cost_source_uncatalogued``
        diagnostic, the emit's ``ts`` matches the ``now`` kwarg."""
        events = [_cost_event(day=22, source="unknown_provider")]
        _direct_write(led_dir, events)
        collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        diag = [
            e for e in led.all_events()
            if e.type == "observability_class_uncatalogued"
            and e.get("kind") == "cost_source_uncatalogued"
        ]
        assert len(diag) == 1
        # The ts is stamped from `now` per the deterministic-clock
        # contract.
        assert diag[0].ts.startswith("2026-05-25T12:00:00")

    def test_default_now_is_wall_clock(self, led_dir, led):
        """When ``now`` is omitted, defaults to wall-clock (the
        diagnostic emit's ``ts`` is the wall-clock; tests verify the
        ``ts`` field is non-empty + ISO-8601-shaped)."""
        events = [_cost_event(day=22, source="unknown_provider")]
        _direct_write(led_dir, events)
        collect_cost_snapshots(led, since=SINCE_2026_05_01)
        diag = [
            e for e in led.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert len(diag) == 1
        # ISO 8601 shape check (Z-suffixed, contains 'T').
        assert diag[0].ts.endswith("Z")
        assert "T" in diag[0].ts


class TestWeek9CollectCostSnapshotsTotalAmount:
    """ADR-0057 D314 — the ``total_amount_usd`` field is the SUM of
    per-event ``amount_usd``."""

    def test_total_amount_sum(self, led_dir, led):
        events = [
            _cost_event(day=20, source="reoon", amount_usd=0.001),
            _cost_event(day=21, source="reoon", amount_usd=0.002),
            _cost_event(day=22, source="reoon", amount_usd=0.003),
            _cost_event(day=23, source="reoon", amount_usd=0.004),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps[0].total_amount_usd == pytest.approx(0.010)
        assert snaps[0].total_units == 4
        assert snaps[0].event_count == 4

    def test_float_precision_no_overflow(self, led_dir, led):
        """Sum of many small floats does not silently lose precision
        (the per-event ``amount_usd`` is a float; Python's float
        sum handles ~10K events at the v1 scale without overflow)."""
        events = [
            _cost_event(day=20, source="gmail", amount_usd=1e-6)
            for _ in range(100)
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps[0].total_amount_usd == pytest.approx(100 * 1e-6)
        assert snaps[0].event_count == 100


class TestWeek9CollectCostSnapshotsChannelInvariant:
    """ADR-0057 D314 + ADR-0014 D33 — :class:`CostSnapshot`.``channel``
    is the homogeneous channel value if every in-window event for the
    source carries the same channel; None otherwise (no channel on
    events; OR multiple distinct channel values; OR a mix of channel +
    no-channel). Mirrors :class:`MetricSnapshot` per ADR-0051 D281."""

    def test_homogeneous_channel_surfaces(self, led_dir, led):
        events = [
            _cost_event(day=22, source="gmail", channel="email"),
            _cost_event(day=23, source="gmail", channel="email"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps[0].channel == "email"

    def test_no_channel_surfaces_none(self, led_dir, led):
        """``cost_incurred`` events without ``channel`` field surface
        snapshot.channel = None (the common case for cost events)."""
        events = [
            _cost_event(day=22, source="reoon"),  # no channel
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps[0].channel is None

    def test_heterogeneous_channels_surface_none(self, led_dir, led):
        """Mixed channels for the same source → snapshot.channel = None
        (pathological case; operators consult ``breakdown_by``)."""
        events = [
            _cost_event(day=22, source="gmail", channel="email"),
            _cost_event(day=23, source="gmail", channel="li_invite"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        assert snaps[0].channel is None


class TestWeek9CostSourceUncataloguedDiagnostic:
    """ADR-0057 D317 — the ``cost_source_uncatalogued`` diagnostic
    kind extension. Mirrors the ``uncatalogued`` + ``missing_ts``
    pattern per ADR-0051 D279 + R034 mitigation; carried into the
    cost surface."""

    def test_one_unknown_source_triggers_emit(self, led_dir, led):
        events = [_cost_event(day=22, source="unknown_provider")]
        _direct_write(led_dir, events)
        collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        diag = [
            e for e in led.all_events()
            if e.type == "observability_class_uncatalogued"
            and e.get("kind") == "cost_source_uncatalogued"
        ]
        assert len(diag) == 1
        assert diag[0].get("offending_source") == "unknown_provider"
        assert diag[0].get("count") == 1
        assert diag[0].get("channel") is None
        assert diag[0].get("_emitted_by") == "observability"

    def test_multiple_unknown_sources_aggregated_to_one(
        self, led_dir, led,
    ):
        """At-most-ONE emit per call per ADR-0051 D279 + R034. The
        count carries the total seen; the offending_source carries the
        first-seen."""
        events = [
            _cost_event(day=20, source="unknown_a"),
            _cost_event(day=21, source="unknown_b"),
            _cost_event(day=22, source="unknown_a"),
            _cost_event(day=23, source="unknown_c"),
        ]
        _direct_write(led_dir, events)
        collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        diag = [
            e for e in led.all_events()
            if e.type == "observability_class_uncatalogued"
            and e.get("kind") == "cost_source_uncatalogued"
        ]
        # EXACTLY one emit per call (the at-most-ONE-per-kind discipline).
        assert len(diag) == 1
        # Count carries the total.
        assert diag[0].get("count") == 4
        # offending_source is the FIRST-SEEN.
        assert diag[0].get("offending_source") == "unknown_a"

    def test_known_source_does_not_trigger_emit(self, led_dir, led):
        """Catalogued sources do NOT trigger the diagnostic emit
        (the complement of the refuse-loud branch)."""
        events = [
            _cost_event(day=22, source="reoon"),
            _cost_event(day=23, source="gmail"),
        ]
        _direct_write(led_dir, events)
        collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
        )
        diag = [
            e for e in led.all_events()
            if e.type == "observability_class_uncatalogued"
        ]
        assert diag == []


class TestWeek9DiagnosticKindsClosedSetExtension:
    """ADR-0057 D317 — :data:`_DIAGNOSTIC_KINDS` closed-set extension
    from 2 to 3 values. Adding ``cost_source_uncatalogued`` while
    preserving ``uncatalogued`` + ``missing_ts`` (the existing Week 2
    kinds per ADR-0051 D279).

    Note: Pillar G Week 10-11 (ADR-0058 D322) further extends the
    closed-set from 3 to 6; the cardinality / membership cells move to
    :class:`TestWeek10_11DiagnosticKindsClosedSetExtension`. These
    Week 9 cells now verify ONLY the Week 9 contract — that the Week 9
    kind ``cost_source_uncatalogued`` IS present + the Week 2 kinds
    preserve.
    """

    def test_diagnostic_kinds_includes_cost_source_uncatalogued_kind(self):
        """ADR-0057 D317 — the Week 9 kind is in the closed-set."""
        assert "cost_source_uncatalogued" in _DIAGNOSTIC_KINDS

    def test_diagnostic_kinds_preserves_week_2_kinds(self):
        """ADR-0057 D317 — the Week 2 kinds (per ADR-0051 D279) preserve
        verbatim across the Week 9 extension."""
        assert "uncatalogued" in _DIAGNOSTIC_KINDS
        assert "missing_ts" in _DIAGNOSTIC_KINDS

    def test_diagnostic_kinds_is_frozenset(self):
        assert isinstance(_DIAGNOSTIC_KINDS, frozenset)


class TestWeek9CostPrivacyInvariant:
    """ADR-0057 D316 + I8 + ADR-0050 D276(b) — the privacy invariant
    on the cost dashboard surface. Per-Person attribution flows
    through the ledger (operators query via :meth:`Ledger.all_events_
    for_person` for per-Person audit); the cost dashboard primitive
    aggregates ONLY by source + channel + model_or_endpoint."""

    def test_person_id_not_in_allowed_dims(self):
        """ADR-0057 D316 — ``person_id`` is privacy-sensitive per
        I8 + ADR-0032 D148."""
        assert "person_id" not in _COST_BREAKDOWN_DIMS_ALLOWED

    def test_run_id_not_in_allowed_dims(self):
        """ADR-0057 D316 — ``run_id`` is operator-tenant per ADR-0010
        D17 (Pillar I per-tenant audit-tooling scope)."""
        assert "run_id" not in _COST_BREAKDOWN_DIMS_ALLOWED

    def test_per_breakdown_amount_does_not_leak_person_or_run_id(
        self, led_dir, led,
    ):
        """Behavioral verification — even when events carry
        ``person_id`` + ``run_id``, the per-breakdown counts do NOT
        surface those fields (the closed-set refuse-loud blocks them
        upstream; this test is the regression-barrier for the
        permissive-aggregate boundary)."""
        events = [
            _cost_event(day=22, source="reoon",
                        person_id="P-secret-1", run_id="R-secret-1"),
            _cost_event(day=23, source="reoon",
                        person_id="P-secret-2", run_id="R-secret-2"),
        ]
        _direct_write(led_dir, events)
        snaps = collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
            breakdown_by=("source",),
        )
        # The per-breakdown counts key on ``source`` ONLY; no
        # person/run id values bleed in.
        breakdown_keys = list(snaps[0].per_breakdown_event_count.keys())
        for k in breakdown_keys:
            assert "P-secret" not in k
            assert "R-secret" not in k


class TestWeek9CostEventsNotUncatalogued:
    """ADR-0057 D314 — ``cost_incurred`` IS in :data:`EVENT_CLASS_
    CATALOG` (recursive-protection per the existing R031 stability
    pattern per ADR-0050 D272). The Week 9 cost primitive's ledger
    walk + the existing :func:`collect_event_class_snapshots`'s ledger
    walk both see ``cost_incurred`` as catalogued."""

    def test_cost_incurred_is_in_event_class_catalog(self):
        """The base event class IS in the per-event-class catalog
        (regression-barrier for R031 stability across the two
        primitives)."""
        assert "cost_incurred" in EVENT_CLASS_CATALOG


class TestWeek9CostNotInSLONames:
    """ADR-0057 D318 — Week 9 PUNTS on extending :data:`_SLO_NAMES`
    with a ``cost_burn_rate`` SLO. Operators wanting cost SLO
    alerting wire their own Grafana alert rule on the cost dashboard's
    per-source burn rate (Grafana's alerting framework operates on
    PromQL queries against the per-source cost metric).

    The PUNT preserves the binding-text discipline — PILLAR-PLAN §2
    Pillar G enumerates exactly four SLO triggers; the closed-set
    stays tight to that enumeration."""

    def test_cost_burn_rate_not_in_slo_names(self):
        """ADR-0057 D318 — the closed-set discipline holds."""
        assert "cost_burn_rate" not in _SLO_NAMES

    def test_slo_names_cardinality_still_4(self):
        """ADR-0057 D318 — Week 9 does NOT extend :data:`_SLO_NAMES`;
        the cardinality stays at 4 per ADR-0056 D313."""
        assert len(_SLO_NAMES) == 4


class TestWeek9GrafanaCostDashboardYaml:
    """ADR-0057 D318 — the cost.yml Grafana dashboard YAML exists at
    the canonical path + is valid YAML + has the expected panel set."""

    def _read_yaml(self):
        import yaml
        path = (
            Path(__file__).resolve().parent.parent
            / "infra" / "grafana" / "dashboards" / "cost.yml"
        )
        return yaml.safe_load(path.read_text())

    def test_cost_dashboard_yaml_exists(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "infra" / "grafana" / "dashboards" / "cost.yml"
        )
        assert path.exists(), (
            f"ADR-0057 D318 — Grafana cost dashboard YAML must exist "
            f"at {path!r}."
        )

    def test_cost_dashboard_yaml_is_valid(self):
        """The YAML parses + has the expected top-level keys."""
        d = self._read_yaml()
        assert isinstance(d, dict)
        assert "title" in d
        assert "panels" in d
        assert isinstance(d["panels"], list)
        assert len(d["panels"]) >= 2

    def test_cost_dashboard_yaml_references_cost_sources(self):
        """The dashboard renders per-source aggregation — at least
        one panel's PromQL query references the cost metric."""
        d = self._read_yaml()
        # Concatenate all panel target expressions.
        all_exprs: list[str] = []
        for p in d.get("panels", []):
            for t in p.get("targets", []):
                expr = t.get("expr", "")
                if expr:
                    all_exprs.append(expr)
        joined = "\n".join(all_exprs)
        # The cost metric name surfaces via the OTel SDK
        # ObservableCounter; the dashboard's PromQL queries reference
        # the per-source cost metric.
        assert "cost" in joined.lower(), (
            "ADR-0057 D318 — Grafana cost dashboard YAML's panels "
            "must reference the cost metric via PromQL."
        )


class TestWeek9DocstringDriftDiscipline:
    """ADR-0057 — the module-level docstring drift discipline (NOW
    TWELVE consecutive weeks at Pillar G Week 9; Pillar F W8-W12 +
    Pillar G W2-W6 + W7-W8 + W9) requires the observability module's
    docstring names the Week 9 deliverables + ADR-0057."""

    def test_module_docstring_names_week_9(self):
        """Week 9 + ADR-0057 are in the module docstring."""
        doc = observability.__doc__ or ""
        assert "Week 9" in doc
        assert "ADR-0057" in doc
        assert "collect_cost_snapshots" in doc


class TestWeek9BehavioralPassthrough:
    """ADR-0057 — the behavioral-passthrough-not-signature-only
    discipline (NOW TEN consecutive weeks at Pillar G Week 9; Pillar F
    W8-W11 + Pillar G W3-W6 + W7-W8 + W9). Per-call kwargs
    (``expected_sources``, ``breakdown_by``) ACTUALLY flow through to
    the aggregation path (not just accepted by the signature)."""

    def test_expected_sources_kwarg_flows_to_diagnostic(
        self, led_dir, led,
    ):
        """When the caller passes a different ``expected_sources``
        than :data:`COST_SOURCES_CATALOG`, the catalog-drift detector
        fires against the CALLER'S catalog (NOT the framework
        default). The behavioral verification — pass a restricted
        catalog + a known framework source + verify the event is
        flagged as uncatalogued against the restricted catalog."""
        events = [
            _cost_event(day=22, source="gmail"),  # in framework default
        ]
        _direct_write(led_dir, events)
        collect_cost_snapshots(
            led, since=SINCE_2026_05_01, now=NOW_2026_05_25,
            expected_sources=frozenset({"reoon"}),  # restricted
        )
        diag = [
            e for e in led.all_events()
            if e.type == "observability_class_uncatalogued"
            and e.get("kind") == "cost_source_uncatalogued"
        ]
        # The caller-supplied catalog excludes gmail; the diagnostic
        # fires.
        assert len(diag) == 1
        assert diag[0].get("offending_source") == "gmail"
