"""OpenTelemetry observability for the outreach pipeline (operations tier).

This is the FULL telemetry implementation: OTel metrics + tracing + a Prometheus
exposition surface. It is opt-in. The core send path uses the no-op shim
orchestrator/obs.py by default (enable this backend with OUTREACH_FACTORY_OTEL=1),
so an adopter who only sends cold email does not need the opentelemetry SDK.

What it provides:
  * Ledger-derived snapshots: per-event-class counts and per-source cost rollups
    (collect_event_class_snapshots / collect_cost_snapshots).
  * OTel meter + tracer setup (init_otel_meter_provider, init_otel_tracer_provider,
    get_meter, get_tracer) and the per-stage span helper (traced_stage).
  * Instruments: event-class observable counters, the send-latency histogram,
    the reconcile success-ratio gauge, the daemon index-freshness gauge.
  * Prometheus: a metric reader + HTTP exposition (init_prometheus_metric_reader,
    start_prometheus_http_server, render_prometheus_exposition).

A privacy invariant constrains which attributes may ride on spans/metrics (no
raw PII). Design history is in ADR-0050 through ADR-0058 and ADR-0067.
"""

from __future__ import annotations

import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Iterable, Iterator

from opentelemetry import metrics as _otel_metrics
from opentelemetry import trace as _otel_trace
from opentelemetry.metrics import (
    CallbackOptions,
    Histogram,
    Meter,
    Observation,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
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
from opentelemetry.sdk.trace.export import SpanProcessor
from opentelemetry.trace import Span, Tracer

if TYPE_CHECKING:    # pragma: no cover — import-only
    import ledger as _ledger
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics._internal.instrument import (
        _ObservableCounter,
        _ObservableGauge,
    )
    # Pillar H Week 8 NEW per ADR-0067 D361 — TYPE_CHECKING-guarded
    # import of :class:`orchestrator.daemon.EventClassIndex` for the
    # optional ``event_class_index`` kwarg on the per-Person primitives.
    # The kwarg's default is None → existing ledger-walk behavior is
    # preserved verbatim per ADR-0059 D325's READ-ONLY funnel CLI
    # contract; daemon-process callers pass the index for O(M_class)
    # per-call cost per R039 mitigation per ADR-0060 D336. The
    # TYPE_CHECKING-guard avoids module-load-time circular concern
    # (orchestrator.daemon imports orchestrator.observability at
    # module-top per Pillar H Week 5 follow-up P3-6 closure).
    from orchestrator.daemon.runner import EventClassIndex


# ---------------------------------------------------------------------------
# Closed-set enumerations — the regression-barrier per ADR-0050 D272
# ---------------------------------------------------------------------------


#: Closed-set enumeration of every Pillar A-F event class the primitive
#: expects to encounter. The catalog IS the regression-barrier per R031
#: (per ADR-0050 D272 + §Risks). A future contributor adding a NEW event
#: class without updating this catalog triggers
#: ``observability_class_uncatalogued`` emit at the per-call grain
#: (rate-limited to ONE per call) — operator-visible signal that the
#: catalog drifted from the actual ledger surface.
#:
#: Updates to this constant MUST coordinate with the pillar's foundation
#: ADR's "new event classes" table + the cross-pillar surface audit's
#: row 17 (the per-pillar event class enumeration).
#:
#: Last reviewed: 2026-05-27 (Pillar H Week 9 follow-up commit;
#: ADR-0067 D362-D363 W9 extension addendum + Pillar H Week 9 follow-up
#: P3-2 closure; 25 entries UNCHANGED at W9 — the W9 commit's invalidation
#: contract per ADR-0067 D362 consumes the existing closed-set without
#: extending the catalog; Pillar H Week 2 added FIVE daemon classes per
#: ADR-0061 D338; Pillar H Week 6 added ONE daemon class
#: ``daemon_stage_saturated`` per ADR-0065 D355; Pillar H Week 9 added
#: ZERO new daemon classes — the per-Ledger.append invalidation observer
#: + the ``outreach_factory_daemon_index_last_updated_timestamp``
#: ObservableGauge per ADR-0067 D363 do NOT extend the EVENT_CLASS_CATALOG;
#: the gauge is the operator SLO signal for invalidation stalls per the
#: per_daemon.yml dashboard panel #6).
#: The W6 follow-up NEW-1 closure surfaces the "Last reviewed" line drift
#: the prior pillar-H weeks' catalog extensions did not update at this
#: cross-pillar site; the W3 follow-up P3-5 closure's discipline-scope
#: extension to materially-unchanged modules applies to this comment
#: (the catalog body itself was extended at lines 528-538 + the Pillar H
#: Week 2 ADR-0061 D338 + Pillar H Week 6 ADR-0065 D355 narrative is
#: name-checked at the catalog comment block; this "Last reviewed" line
#: is the cross-pillar audit's operator-facing surface for the per-Pillar-
#: locality reconciliation).
EVENT_CLASS_CATALOG: frozenset[str] = frozenset({
    # ---------- Phase 5.5 + Pillar A — policy engine + ledger substrate
    "enrolled",
    "enrollment_skipped_exists",
    "enrollment_conflict",
    "needs_identity_upgrade",
    "identity_upgraded",
    "state_transition",
    "research_complete",
    "research_failed",
    "draft_complete",
    "draft_failed",
    "draft_rejected",
    "review_approved",
    "review_rejected",
    "policy_blocked",
    "cooldown_blocked",
    "dedup_blocked",
    "manual_override",
    "cost_incurred",
    # ---------- Pillar B — migration framework
    "migration_event",
    # ---------- Pillar C — multi-channel coherence
    # Email (Phase 5.5 — shipped)
    "send_intent",
    "send_confirmed",
    "send_failed",
    "send_aborted",
    "send_confirmed_orphan",
    "send_run_complete",
    # LinkedIn invite (Pillar C Week 2 — shipped)
    "li_invite_intent",
    "li_invite_confirmed",
    "li_invite_failed",
    "li_invite_aborted",
    # LinkedIn DM (Pillar C Week 3 — shipped)
    "li_dm_intent",
    "li_dm_confirmed",
    "li_dm_failed",
    "li_dm_aborted",
    # Twitter DM (Pillar C Week 5 — shipped)
    "tw_dm_intent",
    "tw_dm_confirmed",
    "tw_dm_failed",
    "tw_dm_aborted",
    # Calendar booking (Pillar C Week 6 — shipped; no ``_aborted``)
    "calendar_booking_intent",
    "calendar_booking_confirmed",
    "calendar_booking_failed",
    # Inbox
    "bounce_detected",
    "reply_received",
    # Reconcile
    "reconcile_drift",
    "reconcile_healed",
    # ---------- Pillar D — reply + conversation handling
    "reply_classified",
    "suppression_added",
    "conversation_state_changed",
    "conversation_outcome",
    "calendar_booking_cancelled",
    # ---------- Pillar E — discovery quality + lineage
    "discovery_dedup_hit",
    "discovery_dedup_conflict",
    "email_verification_cache_hit",
    "tier_suggested",
    # ---------- Pillar H — daemon + dispatcher (Week 2 catalog extension
    # per ADR-0061 D338 + Week 6 catalog extension per ADR-0065 D355;
    # mirrors orchestrator.daemon.DAEMON_NEW_EVENT_CLASSES per the per-
    # pillar mirror constants parity discipline)
    "daemon_started",
    "daemon_stopping",
    "daemon_stopped",
    "policy_reloaded",
    "health_probe",
    "daemon_stage_saturated",  # Pillar H Week 6 NEW per ADR-0065 D355
    # ---------- Pillar I — multi-tenant (Week 2 catalog extension per
    # ADR-0070 D376; mirrors orchestrator.multi_tenant.TENANT_NEW_EVENT_CLASSES
    # per the per-pillar mirror constants parity discipline per ADR-0050 D272)
    "tenant_provisioned",
    "tenant_paused",
    "tenant_resumed",
    "tenant_deprovisioned",
    "init_wizard_completed",
    "auth_token_refreshed",
    # ---------- Pillar J — security + compliance (Week 3 catalog extension
    # per ADR-0078 D393; mirrors orchestrator.security.SECURITY_NEW_EVENT_CLASSES
    # per the per-pillar mirror constants parity discipline per ADR-0050 D272).
    # auth_token_refreshed is NOT here-as-Pillar-J — it is Pillar I's reused
    # class (ADR-0070 D371), cataloged above. gdpr_forget + credentials_reencrypted
    # are cataloged now though their emitters (J6/J5) are FENCED — the catalog
    # enumerates known classes; emitter arrival is independent.
    "gdpr_forget",
    "audit_log_exported",
    "identity_keys_modified",
    "credentials_reencrypted",
})


#: Closed-set of breakdown dimensions ``collect_event_class_snapshots``
#: accepts at the per-call kwarg. Privacy-respecting per I8 +
#: ADR-0032 D148 + ADR-0038 D182 category 8.
#:
#: **Allowed** dimensions: ``channel`` (per ADR-0014 D33 channel-on-
#: every-event invariant; the per-event-class consumer surface) +
#: ``register`` (per ADR-0038 D181 the five Pillar F registers) +
#: ``source_skill`` (per ADR-0036 D170 the discovery_lineage closed
#: enum) + ``category`` (per ADR-0027 the reply_classified categories) +
#: ``classification_method`` (per ADR-0026 D104 the rule-or-llm
#: dispatch) + ``outcome`` (per ADR-0030 the conversation_outcome
#: closed enum) + ``reason`` (per ADR-0049 D263 the reconcile_drift
#: closed-enum) + ``result_state`` (per ADR-0043 D215 the
#: DraftQualityResult state enum) + ``event_class`` (the top-level
#: per-event-class breakdown).
#:
#: **DISALLOWED** dimensions per the privacy invariant per I8:
#:
#: * ``source_list`` — operator-private per ADR-0032 D148 (operator's
#:   curated discovery list names).
#: * ``draft_body`` — operator-confidential per ADR-0038 D182 + I8
#:   (the prose content of the draft).
#: * ``dossier_body`` — operator-confidential per ADR-0038 D182 + I8
#:   (the research dossier's prose content).
#: * ``exemplar_body`` — operator-confidential per ADR-0038 D182 + I8
#:   (the voice-corpus exemplar's prose content).
#: * ``claim_text`` — operator-confidential per ADR-0038 D182 + I8
#:   (the per-claim trace text from hallucination_detected events).
#:
#: A future Pillar G week extending this frozenset MUST verify the
#: dimension does NOT violate the privacy invariant + the audit row 17
#: extension documents the rationale.
_BREAKDOWN_DIMS_ALLOWED: frozenset[str] = frozenset({
    "channel",
    "register",
    "source_skill",
    "category",
    "classification_method",
    "outcome",
    "reason",
    "result_state",
    "event_class",
})


#: Closed-set of the TWO new Pillar G event classes (per ADR-0050 D273).
#: Both ship at Pillar G Weeks 2+ (catalog drift) and 7-8 (SLO
#: violation). They are NOT in :data:`EVENT_CLASS_CATALOG` because
#: that catalog enumerates the events the primitive CONSUMES; this set
#: enumerates the events the primitive EMITS.
#:
#: Both classes carry ``channel: <channel | null>`` per ADR-0014 D33
#: (the SLO violation's channel is per-rule-derived; the catalog drift's
#: channel is None — it's a per-call diagnostic).
OBSERVABILITY_NEW_EVENT_CLASSES: frozenset[str] = frozenset({
    # Pillar G Week 2 — per-call refuse-loud signal when the primitive
    # encounters an event type NOT in EVENT_CLASS_CATALOG. Carries the
    # unknown class name + count. Rate-limited to ONE emission per call.
    # R031 mitigation per ADR-0050 D272 + §Risks.
    "observability_class_uncatalogued",
    # Pillar G Week 7-8 — per-window SLO violation signal. Fires when
    # p99 send latency > 5s OR reconcile success < 99% OR bounce > 5% OR
    # ``manual_override`` count > 0 in the window. Carries the SLO name +
    # observed value + threshold. Channel: derived from violating
    # metric's channel (if applicable). Operator-actionable. R032
    # mitigation extends (synthetic-data spike exclusion via _recovered_by).
    "slo_violation_detected",
})


# ---------------------------------------------------------------------------
# MetricSnapshot — per-snapshot dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricSnapshot:
    """Per-event-class aggregation snapshot for one window.

    Per ADR-0050 D272 — the canonical per-snapshot shape Pillar G's
    per-week 2+ adapters consume uniformly. Fields:

    * ``event_class`` — the event-class name (e.g.,
      ``"reply_classified"``). Must be in :data:`EVENT_CLASS_CATALOG`.
    * ``channel`` — the channel value per ADR-0014 D33. None for
      events that do not carry a channel field (discovery/enrollment
      events; cost_incurred events; Pillar E primitive events; Pillar F
      draft-quality events with NULL channel — operator-deliberate per
      ADR-0014 D33).
    * ``total_count`` — count of matching events in the window.
    * ``per_breakdown_counts`` — sorted dict of
      ``"<composite-key>" -> count``. Composite key shape mirrors
      :func:`orchestrator.funnel._composite_key`. Constrained to
      dimensions in :data:`_BREAKDOWN_DIMS_ALLOWED`.
    * ``oldest_ts`` — ISO 8601 UTC of the earliest event in the
      window for this event class. ``None`` if no events.
    * ``newest_ts`` — ISO 8601 UTC of the latest event in the window
      for this event class. ``None`` if no events.

    **Immutable** (frozen=True) so consumers can safely share snapshots
    across dashboards + caches per the stateless-aggregation contract
    per ADR-0050 D272.
    """

    event_class: str
    channel: str | None
    total_count: int
    per_breakdown_counts: dict[str, int] = field(default_factory=dict)
    oldest_ts: str | None = None
    newest_ts: str | None = None


# ---------------------------------------------------------------------------
# Diagnostic emit kinds (Pillar G Week 2 per ADR-0051 D279)
# ---------------------------------------------------------------------------


#: Closed-set of ``kind`` field values on the
#: ``observability_class_uncatalogued`` diagnostic event class per
#: ADR-0051 D279. The diagnostic event class carries:
#:
#: * ``"uncatalogued"`` — the primitive encountered an event whose
#:   ``type`` is NOT in ``expected_classes | OBSERVABILITY_NEW_EVENT_
#:   CLASSES``. Catalog drift; R031 mitigation per ADR-0050 D272 +
#:   §Risks.
#: * ``"missing_ts"`` — the primitive encountered an event whose
#:   ``ts`` field is missing or empty. ts-missing refuse-loud posture
#:   per ADR-0051 D279 + the Pillar G Week 1 cross-pillar audit row
#:   11 P2-1 carry-forward.
#:
#: At-most-ONE emission per ``kind`` per call (so max six
#: diagnostic events per call across the six kinds — Week 10-11
#: extends from 3 to 6 per ADR-0058 D322). The payload's ``count``
#: field carries the total number of offending events of that kind
#: seen in the call; the ``offending_type`` (or ``offending_source``
#: for the cost kind / ``offending_value`` for the per-Pillar-F
#: catalog kinds) field carries the first-seen offending value
#: (operators investigate the producer).
#:
#: Week 9 extension (ADR-0057 D317):
#:
#: * ``"cost_source_uncatalogued"`` — the
#:   :func:`collect_cost_snapshots` primitive encountered a
#:   ``cost_incurred`` event whose ``source`` field is NOT in
#:   :data:`COST_SOURCES_CATALOG`. Catalog drift on the cost source
#:   surface; R031-shape mitigation per ADR-0050 D272 + ADR-0057
#:   D315.
#:
_DIAGNOSTIC_KINDS: frozenset[str] = frozenset({
    "uncatalogued",
    "missing_ts",
    "cost_source_uncatalogued",
})


# ---------------------------------------------------------------------------
# Composite-key helper (mirrors orchestrator.funnel._composite_key)
# ---------------------------------------------------------------------------


def _composite_key(ev: "_ledger.Event", fields: Iterable[str]) -> str:
    """Build the ``<f1>|<f2>|...`` composite key from event fields.

    Mirrors :func:`orchestrator.funnel._composite_key` per the
    deterministic-output contract per ADR-0031 D140 + ADR-0050
    D276(a) + ADR-0051 D278. Missing or non-string fields render
    as the literal ``"none"`` so the key shape is uniform across
    events. Operators reading the per-breakdown counts see
    ``"none|email"`` immediately if the per-event-class emit is
    missing a field.
    """
    parts: list[str] = []
    for f in fields:
        v = ev.get(f)
        if isinstance(v, str) and v:
            parts.append(v)
        else:
            parts.append("none")
    return "|".join(parts)


# ---------------------------------------------------------------------------
# Primitive — Pillar G Week 2 ships the body
# ---------------------------------------------------------------------------


def collect_event_class_snapshots(
    led: "_ledger.Ledger",
    *,
    since: datetime,
    now: datetime | None = None,
    expected_classes: frozenset[str] = EVENT_CLASS_CATALOG,
    breakdown_by: tuple[str, ...] = (),
) -> list[MetricSnapshot]:
    """Walk the ledger + produce one ``MetricSnapshot`` per event class.

    Per ADR-0050 D272 + ADR-0051 D278 — the per-event-class
    observability primitive. Pillar G Week 1 shipped the signature;
    Pillar G Week 2 ships the body.

    **Stateless contract** per ADR-0050 D272 + R033 mitigation — no
    in-process cache; every call re-walks the ledger via
    ``led.all_events()`` + filters by ``ts >= since`` + groups by
    event class. Per-call cost is O(N) at v1 scale (~5K events) →
    sub-second; Pillar H may revisit at multi-machine scale.

    **Deterministic-clock contract** per ADR-0034 D156 + ADR-0035
    D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278. The ``now``
    kwarg defaults to wall-clock; tests pass ``now`` for byte-
    identical reproducibility. ``now`` is the timestamp stamped onto
    any diagnostic events emitted by this call (see "Diagnostic
    emits" below).

    **Privacy-respecting per I8 + ADR-0032 D148 + ADR-0038 D182
    category 8.** The ``breakdown_by`` kwarg's dimensions MUST be in
    :data:`_BREAKDOWN_DIMS_ALLOWED`; dimensions outside the allowed
    set refuse-loud with ``ValueError`` (matching the closed-enum
    discipline per ADR-0042 D210 + ADR-0049 D263 + ADR-0050 D276(b)).

    **Permissive-aggregate-with-explicit-enumeration** per ADR-0050
    D272 + R031 mitigation. Events whose type is in
    ``expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES`` aggregate
    into per-class snapshots; events whose type is in neither set
    contribute to the ``"uncatalogued"`` diagnostic kind (see below).

    **ts-missing refuse-loud posture** per ADR-0051 D279 (Pillar G
    Week 1 cross-pillar audit row 11 P2-1 carry-forward). Events with
    missing or empty ``ts`` are NOT silently skipped (which is what
    :mod:`orchestrator.funnel`'s prior ``ts = ev.get("ts") or ""``
    posture did); they contribute to the ``"missing_ts"`` diagnostic
    kind (see below).

    **Channel-on-every-event invariant** per ADR-0014 D33 + ADR-0050
    D276(c) + ADR-0051 D281. ``MetricSnapshot.channel`` is the single
    non-null channel value if every in-window event of the class
    carries the same ``channel`` value; ``None`` otherwise (no
    channel field on events, OR multiple distinct channel values, OR
    a mix of channel and no-channel events). Operators wanting per-
    channel breakdown pass ``breakdown_by=("channel",)``.

    **Diagnostic emits** per ADR-0051 D279 — the primitive appends
    AT MOST ONE ``observability_class_uncatalogued`` event per
    ``kind`` per call to ``led``. Two kinds per ADR-0051 D279:

    * ``kind="uncatalogued"`` — fires when the call sees ≥1 event of
      a class NOT in ``expected_classes | OBSERVABILITY_NEW_EVENT_
      CLASSES``. Payload: ``{"offending_type": <first-seen>,
      "count": <total seen>, "channel": null, "_emitted_by":
      "observability"}``.
    * ``kind="missing_ts"`` — fires when the call sees ≥1 event with
      missing/empty ``ts`` field. Payload: ``{"offending_type":
      <first-seen>, "person_id": <first-seen if any>, "count":
      <total seen>, "channel": null, "_emitted_by":
      "observability"}``.

    The ``_emitted_by: "observability"`` audit marker matches the
    Pillar A-F per-event audit-marker discipline per ADR-0010 D17 +
    ADR-0049 §66 P2-2 carry-forward.

    Args:
        led: The ledger to walk. Must support :meth:`Ledger.all_events`
            (read) + :meth:`Ledger.append` (write for diagnostic emit).
        since: The window's lower bound. Events with ``ts >= since``
            (string-comparison on ISO 8601 UTC strings) are included.
        now: Optional deterministic-clock anchor. Production callers
            omit; tests pass for byte-identical reproducibility. Used
            as the ``ts`` field on diagnostic emits (if any).
        expected_classes: Closed-set of event classes to aggregate.
            Defaults to :data:`EVENT_CLASS_CATALOG`. The effective
            "known" set is ``expected_classes |
            OBSERVABILITY_NEW_EVENT_CLASSES`` (so diagnostic events
            this primitive itself emits do not trigger recursive
            uncatalogued diagnostics on the next call).
        breakdown_by: Tuple of breakdown dimensions (each in
            :data:`_BREAKDOWN_DIMS_ALLOWED`). Empty tuple means no
            per-breakdown counts; the snapshot's
            ``per_breakdown_counts`` field is an empty dict.

    Returns:
        List of :class:`MetricSnapshot` — one per event class with at
        least one in-window event with non-empty ``ts``. Event
        classes with zero qualifying events are NOT in the list
        (operators consult :data:`EVENT_CLASS_CATALOG` for the full
        enumeration). The list is sorted alphabetically by
        ``event_class`` per the deterministic-output contract per
        ADR-0031 D140 + ADR-0051 D280.

    Raises:
        ValueError: If any dimension in ``breakdown_by`` is not in
            :data:`_BREAKDOWN_DIMS_ALLOWED` (refuse-loud per I7 +
            ADR-0050 D276(b)).

    See also:
        :func:`orchestrator.funnel._composite_key` — the canonical
        composite-key shape this primitive's :func:`_composite_key`
        mirrors per ADR-0051 D278.
    """
    # 1. Refuse-loud on disallowed breakdown dims (privacy invariant
    # per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050
    # D276(b)).
    for dim in breakdown_by:
        if dim not in _BREAKDOWN_DIMS_ALLOWED:
            raise ValueError(
                "observability.collect_event_class_snapshots: "
                f"breakdown_by dimension {dim!r} is NOT in "
                "_BREAKDOWN_DIMS_ALLOWED. "
                f"Allowed: {sorted(_BREAKDOWN_DIMS_ALLOWED)!r}. "
                "Privacy invariant per I8 + ADR-0032 D148 + ADR-0038 "
                "D182 category 8 + ADR-0050 D276(b)."
            )

    # 2. Normalize `since` to an ISO 8601 UTC string for string-compare
    # against event ts (event ts is the canonical ISO string per
    # ledger.py:_now_iso).
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    since_iso = since.astimezone(timezone.utc).isoformat()

    # 3. Walk events. Track per-class counters + channels + per-
    # breakdown counts + oldest/newest ts; track diagnostic state for
    # rate-limited emits.
    known_classes = expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES

    counters: dict[str, int] = {}
    channels_per_class: dict[str, set[str | None]] = {}
    breakdown_per_class: dict[str, Counter[str]] = {}
    oldest_ts: dict[str, str] = {}
    newest_ts: dict[str, str] = {}

    uncatalogued_count: int = 0
    uncatalogued_sample_type: str | None = None
    missing_ts_count: int = 0
    missing_ts_sample_type: str | None = None
    missing_ts_sample_person_id: str | None = None

    for ev in led.all_events():
        ev_type = ev.type
        ev_ts = ev.ts

        # ts-missing posture per ADR-0051 D279 — refuse-loud
        # (rate-limited; first-seen offending type+person_id sampled).
        if not ev_ts:
            missing_ts_count += 1
            if missing_ts_sample_type is None:
                missing_ts_sample_type = ev_type
                missing_ts_sample_person_id = ev.get("person_id")
            continue

        # Window filter: events before `since` are out-of-scope.
        if ev_ts < since_iso:
            continue

        # Uncatalogued class posture per ADR-0050 D272 + ADR-0051
        # D279 — refuse-loud (rate-limited; first-seen offending type
        # sampled).
        if ev_type not in known_classes:
            uncatalogued_count += 1
            if uncatalogued_sample_type is None:
                uncatalogued_sample_type = ev_type
            continue

        # Aggregate.
        counters[ev_type] = counters.get(ev_type, 0) + 1
        ch = ev.get("channel")
        channels_per_class.setdefault(ev_type, set()).add(ch)

        if breakdown_by:
            key = _composite_key(ev, breakdown_by)
            breakdown_per_class.setdefault(ev_type, Counter())[key] += 1

        if ev_type not in oldest_ts or ev_ts < oldest_ts[ev_type]:
            oldest_ts[ev_type] = ev_ts
        if ev_type not in newest_ts or ev_ts > newest_ts[ev_type]:
            newest_ts[ev_type] = ev_ts

    # 4. Emit diagnostics — at-most-ONE per kind per call per ADR-0051
    # D279. The `_emitted_by: "observability"` audit marker matches
    # the per-event-class audit-marker discipline per ADR-0010 D17.
    now_iso = _now_iso(now)

    if uncatalogued_count > 0:
        led.append({
            "type": "observability_class_uncatalogued",
            "ts": now_iso,
            "kind": "uncatalogued",
            "offending_type": uncatalogued_sample_type,
            "count": uncatalogued_count,
            "channel": None,
            "_emitted_by": "observability",
        })
    if missing_ts_count > 0:
        led.append({
            "type": "observability_class_uncatalogued",
            "ts": now_iso,
            "kind": "missing_ts",
            "offending_type": missing_ts_sample_type,
            "person_id": missing_ts_sample_person_id,
            "count": missing_ts_count,
            "channel": None,
            "_emitted_by": "observability",
        })

    # 5. Build snapshots in deterministic alphabetical order by
    # `event_class` per ADR-0051 D280.
    snapshots: list[MetricSnapshot] = []
    for ev_type in sorted(counters.keys()):
        total = counters[ev_type]
        chs = channels_per_class.get(ev_type, set())
        non_null_chs = {c for c in chs if c}
        # channel-on-every-event invariant per ADR-0014 D33 + ADR-0051
        # D281 — homogeneous single non-null channel surfaces; any
        # other case (no channel / heterogeneous / mix of channel and
        # no-channel) surfaces as None.
        if len(chs) == 1 and len(non_null_chs) == 1:
            snap_channel: str | None = next(iter(non_null_chs))
        else:
            snap_channel = None
        per_breakdown = dict(
            sorted(breakdown_per_class.get(ev_type, Counter()).items())
        )
        snapshots.append(MetricSnapshot(
            event_class=ev_type,
            channel=snap_channel,
            total_count=total,
            per_breakdown_counts=per_breakdown,
            oldest_ts=oldest_ts.get(ev_type),
            newest_ts=newest_ts.get(ev_type),
        ))
    return snapshots


def _now_iso(now: datetime | None) -> str:
    """Stable ISO-8601 with millisecond precision + UTC anchor.

    Mirrors :func:`orchestrator.ledger._now_iso` per ADR-0051 D278.
    If ``now`` is provided, anchors there (deterministic-clock
    contract per ADR-0034 D156 + ADR-0035 D162); else wall-clock.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Cost dashboard (Pillar G Week 9 per ADR-0057 D314-D318)
# ---------------------------------------------------------------------------


#: Closed-set enumeration of every currently-emitting ``cost_incurred``
#: ``source`` value. The catalog IS the R031-shape regression-barrier
#: extended to the cost surface per ADR-0057 D315 — a future
#: contributor adding a NEW cost source without updating this catalog
#: triggers ``cost_source_uncatalogued`` diagnostic emit at the per-
#: call grain (rate-limited to ONE per call) — operator-visible signal
#: that the catalog drifted from the actual cost emission surface.
#:
#: Currently-emitting sources (per the ``cost_incurred`` emit walk at
#: Pillar G Week 9):
#:
#: * ``reoon`` — :mod:`orchestrator.enrich_emails` email-verification
#:   cost emit per ADR-0032 D146.
#: * ``reply_classifier_llm`` — :mod:`orchestrator.reply_classifier_
#:   llm` Anthropic LLM cost emit per ADR-0029 D126.
#: * ``gmail`` / ``linkedin_invite`` / ``linkedin_dm`` / ``twitter_dm``
#:   / ``calendar_booking`` —
#:   :mod:`skills.send-outreach.scripts.send_queued` per-channel
#:   dispatcher cost emits per ADR-0015 / ADR-0016 / ADR-0017 /
#:   ADR-0018 / ADR-0019.
#:
#: Updates to this constant MUST coordinate with the pillar's
#: foundation ADR's "new cost sources" table + the cross-pillar
#: surface audit's row 18 (the per-cost-source enumeration).
#:
#: Last reviewed: 2026-05-26 (Pillar G Week 9 commit; ADR-0057 D315).
COST_SOURCES_CATALOG: frozenset[str] = frozenset({
    "reoon",
    "reply_classifier_llm",
    "gmail",
    "linkedin_invite",
    "linkedin_dm",
    "twitter_dm",
    "calendar_booking",
})


#: Closed-set of breakdown dimensions :func:`collect_cost_snapshots`
#: accepts at the per-call ``breakdown_by`` kwarg. Privacy-respecting
#: per I8 + ADR-0032 D148 + ADR-0050 D276(b) + ADR-0057 D316.
#:
#: **Allowed** dimensions (three; mirrors the per-event-class
#: ``_BREAKDOWN_DIMS_ALLOWED`` shape but scoped to cost-payload
#: fields):
#:
#: * ``source`` — the per-cost-source aggregation grain (mirrors
#:   :data:`COST_SOURCES_CATALOG` members).
#: * ``channel`` — per ADR-0014 D33 channel-on-every-event invariant
#:   (when the cost event carries channel; many do NOT).
#: * ``model_or_endpoint`` — per the ``cost_incurred`` payload field
#:   (operators see per-model attribution for LLM cost; per-endpoint
#:   for verifier cost).
#:
#: **DISALLOWED** dimensions per the privacy invariant per I8:
#:
#: * ``person_id`` — operator-private per ADR-0032 D148 + I8 (per-
#:   prospect attribution flows through the ledger via
#:   :meth:`Ledger.all_events_for_person` for per-Person audit; the
#:   cost dashboard surface aggregates BY source, NOT BY person).
#: * ``run_id`` — operator-tenant per ADR-0010 D17 (Pillar I per-
#:   tenant audit-tooling scope).
#: * ``amount_usd`` — the value field, not a breakdown dimension.
#: * ``ts`` — the time field, not a breakdown dimension.
#: * Any other field — open-set rejection per the R031-shape
#:   regression-barrier discipline.
#:
#: A future Pillar G week extending this frozenset MUST verify the
#: dimension does NOT violate the privacy invariant + the audit row
#: 18 extension documents the rationale.
_COST_BREAKDOWN_DIMS_ALLOWED: frozenset[str] = frozenset({
    "source",
    "channel",
    "model_or_endpoint",
})


@dataclass(frozen=True)
class CostSnapshot:
    """Per-source cost aggregation snapshot for one window.

    Per ADR-0057 D314 — the canonical per-snapshot shape Pillar G's
    cost dashboards consume uniformly. Mirrors :class:`MetricSnapshot`
    shape per ADR-0050 D272 but scoped to the per-source cost surface.

    Fields:

    * ``source`` — the cost source (e.g., ``"reoon"``,
      ``"reply_classifier_llm"``, ``"gmail"``). Must be in
      :data:`COST_SOURCES_CATALOG` (unknown sources surface via the
      ``cost_source_uncatalogued`` diagnostic emit per ADR-0057 D317).
    * ``channel`` — the homogeneous channel value if every in-window
      ``cost_incurred`` event for the source carries the same
      ``channel`` value; ``None`` otherwise. Per ADR-0014 D33 channel-
      on-every-event invariant. Many cost sources do NOT carry
      ``channel`` (reoon / reply_classifier_llm); their snapshots
      have ``channel=None``. The per-dispatcher sources (gmail /
      linkedin_invite / etc.) MAY carry channel.
    * ``total_amount_usd`` — sum of ``amount_usd`` across in-window
      events for the source.
    * ``total_units`` — sum of ``units`` across in-window events.
    * ``event_count`` — count of in-window ``cost_incurred`` events
      for the source.
    * ``per_breakdown_event_count`` — sorted dict of
      ``"<composite-key>" -> event count``. Composite key shape
      mirrors :func:`_composite_key`. Constrained to dimensions in
      :data:`_COST_BREAKDOWN_DIMS_ALLOWED`.
    * ``per_breakdown_amount_usd`` — sorted dict of
      ``"<composite-key>" -> sum of amount_usd``. Same composite key
      shape; operators see per-breakdown spend.
    * ``oldest_ts`` — ISO 8601 UTC of the earliest in-window cost
      event for this source. ``None`` if no events.
    * ``newest_ts`` — ISO 8601 UTC of the latest in-window cost
      event for this source. ``None`` if no events.

    **Immutable** (frozen=True) so consumers can safely share
    snapshots across dashboards + caches per the stateless-aggregation
    contract per ADR-0050 D272.
    """

    source: str
    channel: str | None
    total_amount_usd: float
    total_units: int
    event_count: int
    per_breakdown_event_count: dict[str, int] = field(default_factory=dict)
    per_breakdown_amount_usd: dict[str, float] = field(default_factory=dict)
    oldest_ts: str | None = None
    newest_ts: str | None = None


def collect_cost_snapshots(
    led: "_ledger.Ledger",
    *,
    since: datetime,
    now: datetime | None = None,
    expected_sources: frozenset[str] = COST_SOURCES_CATALOG,
    breakdown_by: tuple[str, ...] = (),
) -> list[CostSnapshot]:
    """Walk the ledger + produce one :class:`CostSnapshot` per cost
    source.

    Per ADR-0057 D314 — the per-source cost aggregation primitive.
    Companion to :func:`collect_event_class_snapshots` (per-event-
    class grain); this primitive's grain is per-cost-source.

    **Stateless contract** per ADR-0050 D272 + R033 mitigation — no
    in-process cache; every call re-walks the ledger via
    ``led.all_events()`` + filters ``type == "cost_incurred"`` + ``ts
    >= since`` + groups by ``source``. Per-call cost is O(N) at v1
    scale (~5K events) → sub-second; Pillar H may revisit at multi-
    machine scale.

    **R032 synthetic-event exclusion** per ADR-0056 D311 + ADR-0057
    D314 — events carrying ``_recovered_by`` (backfill / reconcile /
    migration_<id> per ADR-0010 D17) are EXCLUDED from the cost
    aggregation. Operators running migration backfills do NOT see
    synthetic-data cost spikes; the structural mitigation preserves
    the per-operator cost-dashboard signal.

    **Deterministic-clock contract** per ADR-0034 D156 + ADR-0035
    D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278 + ADR-0056
    D311 + ADR-0057 D314. The ``now`` kwarg defaults to wall-clock;
    tests pass ``now`` for byte-identical reproducibility. ``now`` is
    the timestamp stamped onto any ``cost_source_uncatalogued``
    diagnostic emit triggered by this call.

    **Privacy-respecting** per I8 + ADR-0032 D148 + ADR-0050 D276(b)
    + ADR-0057 D316. The ``breakdown_by`` kwarg's dimensions MUST be
    in :data:`_COST_BREAKDOWN_DIMS_ALLOWED`; dimensions outside the
    allowed set refuse-loud with :class:`ValueError`. ``person_id``
    + ``run_id`` (operator-confidential per I8 + ADR-0010 D17) are
    NOT in the allowed set — operators consume per-Person cost
    attribution via the ledger query surface, NOT via the dashboard
    aggregation.

    **Permissive-aggregate-with-explicit-enumeration** per ADR-0050
    D272 + R031 mitigation + ADR-0057 D315. Events whose ``source``
    is in ``expected_sources`` aggregate into per-source snapshots;
    events whose ``source`` is NOT in ``expected_sources`` contribute
    to the ``cost_source_uncatalogued`` diagnostic kind (at-most-ONE
    emit per call per ADR-0051 D279 + R034 mitigation pattern; see
    "Diagnostic emits" below).

    **Deterministic output** per ADR-0031 D140 + ADR-0051 D280 + ADR-
    0057 D314. Snapshots sorted alphabetically by ``source`` for
    byte-identical reproducibility across consecutive calls against a
    fixed ledger state.

    **Channel-on-every-event invariant** per ADR-0014 D33 + ADR-0057
    D314. :class:`CostSnapshot`.``channel`` is the single non-null
    channel value if every in-window event of the source carries the
    same ``channel`` value; ``None`` otherwise (no channel field on
    events; OR multiple distinct channel values; OR a mix of channel
    and no-channel events). Operators wanting per-channel breakdown
    pass ``breakdown_by=("channel",)``.

    **Diagnostic emits** per ADR-0057 D317 — the primitive appends
    AT MOST ONE ``observability_class_uncatalogued`` event per kind
    per call. Week 9 introduces the third kind:

    * ``kind="cost_source_uncatalogued"`` — fires when the call sees
      ≥1 ``cost_incurred`` event with ``source`` NOT in
      ``expected_sources``. Payload:
      ``{"offending_source": <first-seen>, "count": <total seen>,
      "channel": null, "_emitted_by": "observability"}``.

    The ``_emitted_by: "observability"`` audit marker matches the
    Pillar A-F per-event audit-marker discipline per ADR-0010 D17.

    Args:
        led: The ledger to walk.
        since: The window's lower bound. Events with ``ts >= since``
            (string-comparison on ISO 8601 UTC strings) are included.
        now: Optional deterministic-clock anchor. Production callers
            omit; tests pass for byte-identical reproducibility.
            Used as the ``ts`` field on diagnostic emits (if any).
        expected_sources: Closed-set of cost sources to aggregate.
            Defaults to :data:`COST_SOURCES_CATALOG`. The effective
            "known" set is just ``expected_sources``; unlike
            :func:`collect_event_class_snapshots`, this primitive
            does NOT union with the diagnostic event-class set
            (cost sources and event classes are disjoint domains per
            ADR-0057 D315).
        breakdown_by: Tuple of breakdown dimensions (each in
            :data:`_COST_BREAKDOWN_DIMS_ALLOWED`). Empty tuple means
            no per-breakdown counts.

    Returns:
        List of :class:`CostSnapshot` — one per cost source with at
        least one in-window event. Sorted alphabetically by
        ``source`` per the deterministic-output contract.

    Raises:
        ValueError: If any dimension in ``breakdown_by`` is not in
            :data:`_COST_BREAKDOWN_DIMS_ALLOWED` (refuse-loud per I7
            + ADR-0050 D276(b) + ADR-0057 D316).
    """
    # 1. Refuse-loud on disallowed breakdown dims (privacy invariant
    # per I8 + ADR-0032 D148 + ADR-0050 D276(b) + ADR-0057 D316).
    for dim in breakdown_by:
        if dim not in _COST_BREAKDOWN_DIMS_ALLOWED:
            raise ValueError(
                "observability.collect_cost_snapshots: "
                f"breakdown_by dimension {dim!r} is NOT in "
                "_COST_BREAKDOWN_DIMS_ALLOWED. "
                f"Allowed: {sorted(_COST_BREAKDOWN_DIMS_ALLOWED)!r}. "
                "Privacy invariant per I8 + ADR-0032 D148 + ADR-0050 "
                "D276(b) + ADR-0057 D316."
            )

    # 2. Normalize `since` to an ISO 8601 UTC string for string-compare
    # against event ts.
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    since_iso = since.astimezone(timezone.utc).isoformat()

    # 3. Walk events. Track per-source counters + amount sums + unit
    # sums + channels + per-breakdown counts + oldest/newest ts;
    # track diagnostic state for rate-limited emits.
    event_counters: dict[str, int] = {}
    amount_sums: dict[str, float] = {}
    units_sums: dict[str, int] = {}
    channels_per_source: dict[str, set[str | None]] = {}
    breakdown_event_counts: dict[str, Counter[str]] = {}
    breakdown_amount_sums: dict[str, dict[str, float]] = {}
    oldest_ts: dict[str, str] = {}
    newest_ts: dict[str, str] = {}

    cost_source_uncatalogued_count: int = 0
    cost_source_uncatalogued_sample: str | None = None

    for ev in led.all_events():
        if ev.type != "cost_incurred":
            continue

        # R032 synthetic-event exclusion per ADR-0056 D311 + ADR-0057
        # D314 — events with _recovered_by are operator-deliberate
        # synthetic events and are excluded from the operator-visible
        # cost dashboard signal.
        if ev.get("_recovered_by"):
            continue

        ev_ts = ev.ts
        # Window filter: events before `since` are out-of-scope.
        if not ev_ts or ev_ts < since_iso:
            continue

        source = ev.get("source")

        # Uncatalogued cost source posture per ADR-0057 D317 — refuse-
        # loud (rate-limited; first-seen offending source sampled).
        if not isinstance(source, str) or source not in expected_sources:
            cost_source_uncatalogued_count += 1
            if cost_source_uncatalogued_sample is None:
                cost_source_uncatalogued_sample = (
                    source if isinstance(source, str) else ""
                )
            continue

        # Aggregate.
        event_counters[source] = event_counters.get(source, 0) + 1
        amount = ev.get("amount_usd", 0.0)
        try:
            amount_f = float(amount)
        except (TypeError, ValueError):
            amount_f = 0.0
        amount_sums[source] = amount_sums.get(source, 0.0) + amount_f
        units = ev.get("units", 0)
        try:
            units_i = int(units)
        except (TypeError, ValueError):
            units_i = 0
        units_sums[source] = units_sums.get(source, 0) + units_i

        ch = ev.get("channel")
        channels_per_source.setdefault(source, set()).add(ch)

        if breakdown_by:
            key = _composite_key(ev, breakdown_by)
            breakdown_event_counts.setdefault(
                source, Counter(),
            )[key] += 1
            sums_for_source = breakdown_amount_sums.setdefault(
                source, {},
            )
            sums_for_source[key] = sums_for_source.get(key, 0.0) + amount_f

        if source not in oldest_ts or ev_ts < oldest_ts[source]:
            oldest_ts[source] = ev_ts
        if source not in newest_ts or ev_ts > newest_ts[source]:
            newest_ts[source] = ev_ts

    # 4. Emit diagnostic — at-most-ONE per kind per call per ADR-0051
    # D279 + R034 mitigation + ADR-0057 D317. The `_emitted_by:
    # "observability"` audit marker matches the per-event audit-
    # marker discipline per ADR-0010 D17.
    if cost_source_uncatalogued_count > 0:
        led.append({
            "type": "observability_class_uncatalogued",
            "ts": _now_iso(now),
            "kind": "cost_source_uncatalogued",
            "offending_source": cost_source_uncatalogued_sample,
            "count": cost_source_uncatalogued_count,
            "channel": None,
            "_emitted_by": "observability",
        })

    # 5. Build snapshots in deterministic alphabetical order by
    # `source` per ADR-0031 D140 + ADR-0057 D314.
    snapshots: list[CostSnapshot] = []
    for source in sorted(event_counters.keys()):
        chs = channels_per_source.get(source, set())
        non_null_chs = {c for c in chs if c}
        # channel-on-every-event invariant per ADR-0014 D33 + ADR-0057
        # D314 — homogeneous single non-null channel surfaces; any
        # other case (no channel / heterogeneous / mix) surfaces None.
        if len(chs) == 1 and len(non_null_chs) == 1:
            snap_channel: str | None = next(iter(non_null_chs))
        else:
            snap_channel = None

        per_breakdown_event = dict(
            sorted(breakdown_event_counts.get(source, Counter()).items())
        )
        per_breakdown_amount = dict(
            sorted(breakdown_amount_sums.get(source, {}).items())
        )

        snapshots.append(CostSnapshot(
            source=source,
            channel=snap_channel,
            total_amount_usd=amount_sums.get(source, 0.0),
            total_units=units_sums.get(source, 0),
            event_count=event_counters[source],
            per_breakdown_event_count=per_breakdown_event,
            per_breakdown_amount_usd=per_breakdown_amount,
            oldest_ts=oldest_ts.get(source),
            newest_ts=newest_ts.get(source),
        ))
    return snapshots


# ---------------------------------------------------------------------------
# OTel SDK initialization (Pillar G Week 3 per ADR-0052 D282-D287)
# ---------------------------------------------------------------------------


#: The OTel Meter scope name for Pillar G's instruments. The load-
#: bearing OTel label per the per-pillar symmetry convention per
#: RETRO-pillar-f.md item 5 — every Pillar G instrument shares the
#: same Meter scope so operators consuming the OTLP / Prometheus
#: export see one canonical namespace.
_METER_NAME: str = "orchestrator.observability"

#: The OTel Meter scope version. Tracks the observability surface
#: revision (NOT the framework's pyproject version). Bumped at the
#: per-week ADR by Pillar G's later weeks when the per-event-class
#: instrument set extends in a non-backwards-compat way (e.g., Week
#: 4 Prometheus exporter wiring may add per-channel histograms +
#: reconcile success ratio).
_METER_VERSION: str = "0.1.0"

#: The default ``service.name`` Resource attribute per OTel semantic
#: conventions (``service.name``: the logical name of the service —
#: ``opentelemetry.semconv.resource``). Pillar G Week 3 pins this at
#: the framework name; Pillar I per-tenant audit-tooling at the OSS
#: bring-up trajectory MAY extend this via
#: :func:`init_otel_meter_provider`'s ``resource`` kwarg with per-
#: tenant labels.
_SERVICE_NAME: str = "outreach-factory"

#: The default ``service.version`` Resource attribute. Pillar G Week 3
#: pins ``"0.1.0"`` (the in-repo pyproject placeholder; the framework
#: ships without a real version source today). Future pillars MAY
#: source from ``pyproject.toml`` or git-describe; Week 3 prefers the
#: explicit pin to surface ZERO operator-side coupling at Week 3
#: ship.
_SERVICE_VERSION: str = "0.1.0"

#: The canonical instrument name for the per-event-class observable
#: counter per ADR-0052 D284. The ``outreach_factory_`` prefix is the
#: per-framework namespace (operators sharing a Prometheus pool see
#: per-framework metric segregation); the ``_events_total`` suffix
#: matches the Prometheus counter convention (monotonic cumulative
#: count over the process lifetime; operators query the per-window
#: rate via ``rate(outreach_factory_events_total[1h])``).
_INSTRUMENT_NAME_EVENTS_TOTAL: str = "outreach_factory_events_total"


def init_otel_meter_provider(
    *,
    resource: Resource | None = None,
    metric_readers: Iterable[MetricReader] = (),
    views: Iterable[View] | None = None,
    set_global: bool = True,
) -> MeterProvider:
    """Initialize an OTel :class:`MeterProvider` per ADR-0052 D282.

    Pillar G Week 3 ships the OTel SDK initialization. Per ADR-0050
    D273 + ADR-0052 D282 the framework is **OpenTelemetry SDK +
    Prometheus exporter + Grafana-as-code**; Week 3 lands the
    MeterProvider + Meter accessor + per-event-class
    :class:`ObservableCounter` wiring. Pillar G Week 4 (per ADR-0053
    D288-D293) adds the Prometheus exporter wiring + the bare metric
    set extension (per-channel send-latency histogram + reconcile
    success ratio) + the first Grafana-as-code dashboard.

    **Idempotency caveat per OTel spec.** The OTel Python SDK
    enforces ``set_meter_provider`` "set-once" semantics — subsequent
    calls log ``"Overriding of current MeterProvider is not
    allowed"`` and do NOT take effect. Tests pass ``set_global=False``
    to bypass this; production callers (single startup invocation)
    keep ``set_global=True``.

    **Framework-neutrality contract per ADR-0052 D286 + ADR-0053
    D293.** The ``metric_readers`` kwarg is the operator's choice of
    OTel reader (Prometheus / OTLP / in-memory for tests). Default is
    EMPTY tuple — the SDK accepts the MeterProvider with NO readers;
    instruments register, callbacks register, but no scrape fires
    until a reader is added. Week 4 ships :func:`init_prometheus_
    metric_reader` as the canonical Prometheus wiring; the exporter
    stays OPTIONAL (operators with OTLP backends skip it).

    **Default :class:`View` set per ADR-0053 D292.** The ``views``
    kwarg accepts operator-supplied :class:`View` instances; ``None``
    (the default) falls back to :func:`default_views` which pins the
    framework's recommended Views (the per-channel send-latency
    histogram bucket configuration). Operators passing ``views=()``
    (empty tuple) skip the framework defaults — useful for operators
    with custom histogram bucket strategies.

    **Resource-attribute closed-set per ADR-0052 D287.** The default
    Resource carries ``service.name`` + ``service.version`` from
    :data:`_SERVICE_NAME` + :data:`_SERVICE_VERSION` (plus the OTel
    SDK's auto-injected ``telemetry.sdk.*`` attributes). Operators
    extending Resource with per-tenant labels at Pillar I MUST
    preserve the two ``service.*`` keys + may add per-tenant keys
    (e.g., ``outreach_factory.tenant_id``).

    Args:
        resource: Optional :class:`Resource` override. Default carries
            ``service.name``/``service.version`` per
            :data:`_SERVICE_NAME` + :data:`_SERVICE_VERSION`.
        metric_readers: Iterable of :class:`MetricReader` instances
            (Prometheus exporter, OTLP exporter, in-memory reader,
            ...). Default is an empty tuple (no scraping until a
            reader is wired).
        views: Iterable of :class:`View` instances. Default is
            ``None`` — the framework substitutes :func:`default_views`
            (the recommended Views, including the per-channel send-
            latency histogram bucket configuration). Pass ``()`` to
            skip the framework defaults entirely.
        set_global: Whether to call
            :func:`opentelemetry.metrics.set_meter_provider` on the
            new provider. Default ``True``. Tests pass ``False`` to
            isolate each test's provider.

    Returns:
        The newly-constructed :class:`MeterProvider` instance.
    """
    if resource is None:
        resource = Resource.create({
            SERVICE_NAME: _SERVICE_NAME,
            SERVICE_VERSION: _SERVICE_VERSION,
        })
    if views is None:
        views = default_views()
    provider = MeterProvider(
        resource=resource,
        metric_readers=list(metric_readers),
        views=list(views),
    )
    if set_global:
        # OTel spec: set_meter_provider is set-once. If already set
        # globally, the SDK logs a warning + ignores. Tests pass
        # set_global=False to keep the provider local.
        _otel_metrics.set_meter_provider(provider)
    return provider


def get_meter(meter_provider: MeterProvider | None = None) -> Meter:
    """Return the Pillar G observability :class:`Meter` per ADR-0052 D283.

    The single canonical OTel scope ``"orchestrator.observability"``
    + version :data:`_METER_VERSION` per the per-pillar symmetry
    convention per RETRO-pillar-f.md item 5 — every Pillar G
    instrument shares this scope so operators consuming the OTLP /
    Prometheus export see one namespace.

    Args:
        meter_provider: Optional explicit :class:`MeterProvider` to
            source the Meter from. Default consults the global
            provider set by :func:`init_otel_meter_provider` (or the
            no-op default if Pillar G has not been initialized
            yet — operators calling :func:`get_meter` without prior
            :func:`init_otel_meter_provider` get a no-op Meter that
            doesn't surface failures, mirroring OTel's safe-default
            posture).

    Returns:
        A :class:`Meter` scoped at
        ``"orchestrator.observability"`` + :data:`_METER_VERSION`.
    """
    if meter_provider is None:
        return _otel_metrics.get_meter(_METER_NAME, _METER_VERSION)
    return meter_provider.get_meter(_METER_NAME, _METER_VERSION)


def register_event_class_observable_counter(
    led: "_ledger.Ledger",
    *,
    since_window: timedelta,
    now: Callable[[], datetime] | None = None,
    expected_classes: frozenset[str] = EVENT_CLASS_CATALOG,
    breakdown_by: tuple[str, ...] = (),
    meter: Meter | None = None,
) -> "_ObservableCounter":
    """Register the per-event-class :class:`ObservableCounter`.

    Per ADR-0052 D284 — the single canonical instrument for Pillar
    G's per-event-class metric emit. The callback closure walks the
    ledger via :func:`collect_event_class_snapshots` on each scrape
    + emits ONE :class:`Observation` per :class:`MetricSnapshot`
    carrying ``event_class`` + ``channel`` attributes.

    **Cumulative-counter semantics per ADR-0052 D285.** The
    instrument is an :class:`ObservableCounter` (monotonic non-
    decreasing) NOT a :class:`Gauge`. The per-event-class count is a
    monotonic process metric per Prometheus + OTel counter
    semantics — operators query the per-window rate via PromQL's
    ``rate()`` / ``increase()``. The ``since_window`` kwarg
    parametrizes the per-scrape rolling-window range (Week 3 ships
    the rolling-window primitive; Week 4 may switch to lifetime-
    cumulative on the Prometheus exporter side).

    **Stateless callback per ADR-0050 D272 + R033 mitigation.** The
    closure does NOT cache state across scrapes; every callback
    re-walks the ledger fully. The per-scrape cost is the same as
    one :func:`collect_event_class_snapshots` call (~O(N) at v1
    scale).

    **Channel-on-every-event invariant per ADR-0014 D33 +
    ADR-0051 D281.** The per-observation ``channel`` attribute
    surfaces :attr:`MetricSnapshot.channel` directly; the homogeneous
    case carries the single channel value (e.g., ``"email"``); the
    heterogeneous / no-channel / mix cases carry ``"none"`` (OTel
    attributes do NOT accept ``None`` values per the spec).

    **Diagnostic emit per ADR-0051 D279.** The per-scrape ledger
    walk MAY emit ``observability_class_uncatalogued`` diagnostic
    events into the ledger (the underlying
    :func:`collect_event_class_snapshots` writes the diagnostic);
    operators see the recurring signal in the per-event-class metric
    + investigate. R034 mitigation per ADR-0051 §Risks applies — at-
    most-ONE diagnostic per kind per scrape; operators fix the
    catalog promptly.

    Args:
        led: The ledger to walk per-scrape. Must support
            :meth:`Ledger.all_events` (read) +
            :meth:`Ledger.append` (write for diagnostic emit).
        since_window: The per-scrape rolling window
            (:class:`timedelta`). The callback computes the per-
            scrape ``since = now() - since_window``.
        now: Optional deterministic-clock function returning the
            "current time". Default is wall-clock
            (``datetime.now(timezone.utc)``); tests pass a captured-
            lambda for byte-identical reproducibility.
        expected_classes: Closed-set of event classes to aggregate.
            Defaults to :data:`EVENT_CLASS_CATALOG`. Forwarded to
            :func:`collect_event_class_snapshots`.
        breakdown_by: Forwarded to
            :func:`collect_event_class_snapshots`. Default is empty
            tuple; per-attribute breakdown surfaces via per-
            observation ``channel`` attribute alone.
        meter: Optional explicit :class:`Meter`. Default consults the
            global provider per :func:`get_meter`.

    Returns:
        The registered :class:`ObservableCounter` instrument.
    """
    if meter is None:
        meter = get_meter()

    if now is None:
        def _wall_clock_now() -> datetime:
            return datetime.now(timezone.utc)
        now = _wall_clock_now

    def _callback(_options: CallbackOptions) -> Iterable[Observation]:
        anchor = now()
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        since = anchor - since_window
        snapshots = collect_event_class_snapshots(
            led,
            since=since,
            now=anchor,
            expected_classes=expected_classes,
            breakdown_by=breakdown_by,
        )
        for snap in snapshots:
            # OTel attributes do NOT accept None per spec; surface
            # the heterogeneous/missing-channel case as the literal
            # "none" string mirroring _composite_key per ADR-0051
            # D280's deterministic-output contract.
            ch_attr = snap.channel if snap.channel is not None else "none"
            yield Observation(
                snap.total_count,
                {
                    "event_class": snap.event_class,
                    "channel": ch_attr,
                },
            )

    return meter.create_observable_counter(
        name=_INSTRUMENT_NAME_EVENTS_TOTAL,
        callbacks=[_callback],
        description=(
            "Per-event-class total event count from "
            "collect_event_class_snapshots — the Pillar G Week 3 OTel "
            "instrument per ADR-0052 D284. Monotonic cumulative per "
            "OTel counter semantics; operators query the per-window "
            "rate via PromQL's rate() / increase()."
        ),
        unit="1",
    )


# ---------------------------------------------------------------------------
# Prometheus exporter wiring (Pillar G Week 4 per ADR-0053 D288-D293)
# ---------------------------------------------------------------------------


#: The canonical instrument name for the per-channel send-latency
#: Histogram per ADR-0053 D289. Operators record per-send latency via
#: ``get_send_latency_histogram().record(elapsed_seconds, {"channel":
#: "email"})`` at the dispatch point. The ``_seconds`` suffix is the
#: Prometheus + OTel histogram unit convention (operators query the
#: p99 via PromQL's
#: ``histogram_quantile(0.99, rate(<name>_bucket[5m]))``).
_INSTRUMENT_NAME_SEND_LATENCY_SECONDS: str = \
    "outreach_factory_send_latency_seconds"

#: The canonical instrument name for the reconcile success ratio
#: ObservableGauge per ADR-0053 D290. The callback computes the per-
#: window ratio ``N_healed / (N_healed + N_drift)`` from the ledger;
#: vacuous success (no reconcile activity) → 1.0; drift-only → 0.0.
#: Operators query the ratio via PromQL's
#: ``outreach_factory_reconcile_success_ratio < 0.99`` for the 99% SLO
#: threshold per PILLAR-PLAN §2 Pillar G.
_INSTRUMENT_NAME_RECONCILE_SUCCESS_RATIO: str = \
    "outreach_factory_reconcile_success_ratio"

#: Pillar H Week 9 per ADR-0067 D363 — the canonical instrument name
#: for the daemon's per-event-class index freshness ObservableGauge.
#: Value is the Unix-epoch timestamp (seconds, float) of the most
#: recent index update (initial materialization at
#: :func:`orchestrator.daemon.init_daemon` Step 8 + each per-append
#: invalidation per ADR-0067 D362). Operators query the age in
#: seconds via PromQL's
#: ``time() - outreach_factory_daemon_index_last_updated_timestamp``;
#: the per_daemon.yml dashboard panel #6 renders the age + thresholds
#: RED at > 60s (operator SLO signal for invalidation stalls). The
#: ``_timestamp`` suffix is the Prometheus convention for absolute-
#: time gauges (consumers compute deltas client-side via ``time()``).
_INSTRUMENT_NAME_DAEMON_INDEX_LAST_UPDATED_TIMESTAMP: str = \
    "outreach_factory_daemon_index_last_updated_timestamp"

#: Framework-default explicit buckets for the send-latency Histogram
#: per ADR-0053 D289. Spans sub-millisecond to 10s; the 5s bucket is
#: explicit so the p99 SLO threshold per PILLAR-PLAN §2 Pillar G
#: (p99 send latency > 5s) is operator-queryable via PromQL's
#: ``histogram_quantile`` at the 5s boundary without interpolation.
#: Operators with different latency profiles pass their own
#: :class:`View` via :func:`init_otel_meter_provider`'s ``views``
#: kwarg.
_SEND_LATENCY_BUCKETS_SECONDS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)

#: Default Prometheus HTTP exposition server port per ADR-0053 D291.
#: Operator-deliberate: the framework does NOT auto-start the server
#: at this port. Operators wiring the Prometheus exposition externally
#: explicitly invoke :func:`start_prometheus_http_server` with this
#: default OR a custom port.
_DEFAULT_PROMETHEUS_PORT: int = 8000

#: Default Prometheus HTTP exposition server bind address per ADR-0053
#: D291. ``127.0.0.1`` (localhost) is the security-by-default posture
#: — operators deliberately expose externally via ``0.0.0.0`` (all
#: interfaces) IF they wire firewall + authentication separately.
_DEFAULT_PROMETHEUS_ADDR: str = "127.0.0.1"


def default_views() -> tuple[View, ...]:
    """Return the framework's default :class:`View` set per ADR-0053 D292.

    Pinned at Pillar G Week 4 with ONE View:

    * The per-channel send-latency Histogram bucket configuration —
      explicit buckets from :data:`_SEND_LATENCY_BUCKETS_SECONDS` so
      the OTel SDK's default histogram boundaries (0, 5, 10, 25, 50,
      75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000 — too
      coarse for the framework's sub-second send-latency profile) are
      OVERRIDDEN to the framework's recommended bucket set.

    Operators with different latency profiles (e.g., higher-latency
    LinkedIn auth flows) pass their own :class:`View` set via
    :func:`init_otel_meter_provider`'s ``views`` kwarg.

    Returns:
        A tuple of :class:`View` instances. Week 4 returns ONE view
        for the send-latency Histogram. Future Pillar G weeks MAY
        extend (e.g., Week 9 cost dashboard's per-source bucket
        configuration).
    """
    return (
        View(
            instrument_name=_INSTRUMENT_NAME_SEND_LATENCY_SECONDS,
            aggregation=ExplicitBucketHistogramAggregation(
                boundaries=_SEND_LATENCY_BUCKETS_SECONDS,
            ),
        ),
    )


def init_prometheus_metric_reader() -> "PrometheusMetricReader":
    """Return a :class:`PrometheusMetricReader` per ADR-0053 D288.

    The canonical Prometheus wiring for the Pillar G Week 4 framework-
    neutrality contract per ADR-0052 D286 + ADR-0053 D293 — operators
    pass the returned reader to :func:`init_otel_meter_provider`'s
    ``metric_readers=`` kwarg:

    .. code-block:: python

        from observability import (
            init_otel_meter_provider, init_prometheus_metric_reader,
            register_event_class_observable_counter,
            register_reconcile_success_ratio_gauge,
            start_prometheus_http_server,
        )

        reader = init_prometheus_metric_reader()
        provider = init_otel_meter_provider(metric_readers=[reader])
        register_event_class_observable_counter(
            led, since_window=timedelta(days=30),
        )
        register_reconcile_success_ratio_gauge(
            led, since_window=timedelta(days=30),
        )
        # Operator-deliberate: start the HTTP exposition server.
        start_prometheus_http_server(port=8000)

    The exporter is OPTIONAL per the framework-neutrality contract —
    operators with OTLP backends (Honeycomb / Datadog / Grafana Cloud)
    skip this entirely + wire their OTLP reader instead.

    Returns:
        A :class:`PrometheusMetricReader` instance. The reader
        registers a per-process Prometheus collector on
        :data:`prometheus_client.REGISTRY`; operators starting the
        HTTP exposition server via :func:`start_prometheus_http_server`
        consume from this same registry.
    """
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    return PrometheusMetricReader()


def get_send_latency_histogram(
    meter: Meter | None = None,
) -> Histogram:
    """Return the per-channel send-latency :class:`Histogram` per ADR-0053 D289.

    The canonical sync instrument for per-send latency tracking.
    Operators record at the dispatch point:

    .. code-block:: python

        histogram = get_send_latency_histogram()
        # ... dispatch send_intent + send_confirmed ...
        histogram.record(elapsed_seconds, {"channel": "email"})

    Per ADR-0053 D289 the instrument:

    * **Name:** :data:`_INSTRUMENT_NAME_SEND_LATENCY_SECONDS` =
      ``"outreach_factory_send_latency_seconds"``.
    * **Unit:** ``"s"`` (seconds; matches the Prometheus convention).
    * **Type:** :class:`Histogram` (sync; operators call ``.record()``
      with per-channel attribute).
    * **Buckets:** :data:`_SEND_LATENCY_BUCKETS_SECONDS` (explicit;
      applied via the default :class:`View` per :func:`default_views`).

    **Channel-on-every-event invariant per ADR-0014 D33 + ADR-0050
    D276(c) + ADR-0053 D289.** Operators MUST pass ``{"channel":
    <channel>}`` per the per-channel two-phase convention; the
    histogram aggregates per-channel automatically.

    **Week 4 ships the SHAPE; the dispatcher integration is
    a Pillar H + Pillar G Week 5-6 (tracing) concern.** Operators
    wanting the histogram populated today wire the
    ``histogram.record()`` call at their dispatcher's two-phase
    commit point.

    Args:
        meter: Optional explicit :class:`Meter`. Default consults
            the global provider per :func:`get_meter`.

    Returns:
        The :class:`Histogram` instrument.
    """
    if meter is None:
        meter = get_meter()
    return meter.create_histogram(
        name=_INSTRUMENT_NAME_SEND_LATENCY_SECONDS,
        unit="s",
        description=(
            "Per-channel send latency in seconds — Pillar G Week 4 "
            "Histogram instrument per ADR-0053 D289. Operators record "
            "at the two-phase commit point via "
            ".record(elapsed_seconds, {\"channel\": <channel>}). Query "
            "the per-channel p99 via PromQL's histogram_quantile(0.99, "
            "rate(outreach_factory_send_latency_seconds_bucket[5m]))."
        ),
    )


def register_reconcile_success_ratio_gauge(
    led: "_ledger.Ledger",
    *,
    since_window: timedelta,
    now: Callable[[], datetime] | None = None,
    meter: Meter | None = None,
) -> "_ObservableGauge":
    """Register the reconcile success ratio ObservableGauge per ADR-0053 D290.

    The callback closure walks the ledger via
    :func:`collect_event_class_snapshots` per scrape + computes the
    per-window ratio:

    .. math:: \\text{ratio} = \\frac{N_\\text{healed}}{N_\\text{healed}
              + N_\\text{drift}}

    where :math:`N_\\text{healed}` is the count of ``reconcile_healed``
    events in the window + :math:`N_\\text{drift}` is the count of
    ``reconcile_drift`` events in the window.

    **Edge cases:**

    * **Vacuous success (no reconcile activity).** When the window
      contains ZERO ``reconcile_healed`` AND ZERO ``reconcile_drift``
      events, the ratio is ``1.0`` (operationally interpreted as
      "no failures = success"). The PromQL SLO query
      ``outreach_factory_reconcile_success_ratio < 0.99`` does NOT
      fire on vacuous windows.
    * **Drift-only.** When the window contains drift events but ZERO
      heal events, the ratio is ``0.0`` (operationally interpreted as
      "all drift, no heal = total failure"). The PromQL SLO query
      fires.

    **Stateless callback per ADR-0050 D272 + R033 mitigation.** The
    closure does NOT cache state across scrapes; every callback
    re-walks the ledger fully via :func:`collect_event_class_snapshots`.

    **Cumulative vs point-in-time semantics per ADR-0053 D290.** The
    instrument is an :class:`ObservableGauge` (point-in-time ratio)
    NOT an :class:`ObservableCounter`. The reconcile success ratio
    is a per-window aggregate that may move up or down across scrapes
    as the window rolls; gauge semantics match.

    Args:
        led: The ledger to walk per-scrape. Must support
            :meth:`Ledger.all_events` (read) +
            :meth:`Ledger.append` (write for diagnostic emit).
        since_window: The per-scrape rolling window
            (:class:`timedelta`). The callback computes
            ``since = now() - since_window`` + invokes
            :func:`collect_event_class_snapshots`.
        now: Optional deterministic-clock callable returning the
            "current time". Default is wall-clock
            (``datetime.now(timezone.utc)``); tests pass a captured-
            lambda for byte-identical reproducibility.
        meter: Optional explicit :class:`Meter`. Default consults
            the global provider per :func:`get_meter`.

    Returns:
        The registered :class:`ObservableGauge` instrument.
    """
    if meter is None:
        meter = get_meter()

    if now is None:
        def _wall_clock_now() -> datetime:
            return datetime.now(timezone.utc)
        now = _wall_clock_now

    def _callback(_options: CallbackOptions) -> Iterable[Observation]:
        anchor = now()
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        since = anchor - since_window
        snapshots = collect_event_class_snapshots(
            led,
            since=since,
            now=anchor,
        )
        by_class = {s.event_class: s.total_count for s in snapshots}
        healed = by_class.get("reconcile_healed", 0)
        drift = by_class.get("reconcile_drift", 0)
        denom = healed + drift
        if denom == 0:
            # Vacuous success: no reconcile activity = no failures.
            ratio = 1.0
        else:
            ratio = healed / denom
        yield Observation(ratio, {})

    return meter.create_observable_gauge(
        name=_INSTRUMENT_NAME_RECONCILE_SUCCESS_RATIO,
        callbacks=[_callback],
        unit="1",
        description=(
            "Reconcile success ratio over the per-scrape rolling "
            "window — Pillar G Week 4 ObservableGauge per ADR-0053 "
            "D290. Computed as N_healed / (N_healed + N_drift) from "
            "collect_event_class_snapshots; vacuous success (no "
            "reconcile activity) → 1.0; drift-only → 0.0. Operators "
            "query via PromQL's "
            "outreach_factory_reconcile_success_ratio < 0.99 for the "
            "99% SLO threshold per PILLAR-PLAN §2 Pillar G."
        ),
    )


def register_daemon_index_observable_gauge(
    *,
    get_last_updated_ts_fn: Callable[[], float],
    meter: "Meter | None" = None,
):
    """Pillar H Week 9 per ADR-0067 D363 (W9 extension to ADR-0067 per
    ADR-0060 D336) — register the daemon's per-event-class index
    freshness Prometheus ObservableGauge.

    The gauge value is the Unix-epoch timestamp (seconds, float) of
    the most recent index update — initial materialization at
    :func:`orchestrator.daemon.init_daemon` Step 8 + each per-append
    invalidation per ADR-0067 D362. The
    :func:`orchestrator.daemon.init_daemon` Step 9.5 registration
    passes a closure that reads
    :attr:`DaemonRunner.event_class_index._last_updated_at_ts` so the
    gauge reflects the daemon's per-process index state.

    The dashboard panel #6 at
    :file:`infra/grafana/dashboards/per_daemon.yml` consumes this
    gauge via PromQL's
    ``time() - outreach_factory_daemon_index_last_updated_timestamp``
    to render the index age in seconds + threshold-color the panel
    RED at > 60s (operator SLO signal for invalidation stalls — if
    the observer registration silently broke OR the daemon stopped
    receiving appends, the age grows monotonically).

    **Cumulative vs point-in-time semantics per ADR-0053 D290.** The
    instrument is an :class:`ObservableGauge` (point-in-time
    timestamp) NOT an :class:`ObservableCounter`. The index age is
    a per-scrape point-in-time signal that may move forward OR stay
    static across scrapes; gauge semantics match.

    **Cross-process consistency note** — the gauge reflects ONLY the
    daemon-process's own appends to its registered :class:`Ledger`
    instance. Other-process appends (operator CLI / skill /
    standalone scripts) are NOT visible to the daemon-process index
    until the next daemon restart re-materializes per I3. Pillar I
    per-tenant fan-out per ADR-0060 D335 invariant 1 runs one daemon
    per tenant; the cross-process gap is a v1 single-tenant +
    concurrent-CLI concern documented at ADR-0067 W9 extension.

    **Best-effort registration** — :func:`init_daemon` Step 9.5
    catches exceptions from this registration + logs to stderr but
    does NOT propagate; the gauge is operator-observability
    scaffolding, NOT a daemon correctness contract. Operators
    running the daemon without the OTel SDK initialized (test
    substrate at unit-test scope OR no-op
    ``otel_meter_init_fn`` / ``prometheus_start_fn`` injection)
    get a silent no-op.

    Args:
        get_last_updated_ts_fn: zero-arg callable returning the
            Unix-epoch timestamp (float seconds) of the most recent
            index update. The daemon passes a closure capturing the
            :class:`DaemonRunner` instance:
            ``lambda: runner.event_class_index._last_updated_at_ts``.
            On scrape, the OTel SDK invokes this callback + emits
            the returned value as the gauge's per-scrape observation.
            Callbacks MUST be stateless per ADR-0050 D272 + R033
            mitigation.
        meter: Optional explicit :class:`Meter`. Default consults
            the global provider per :func:`get_meter`.

    Returns:
        The registered :class:`ObservableGauge` instrument.
    """
    if meter is None:
        meter = get_meter()

    def _callback(_options: CallbackOptions) -> Iterable[Observation]:
        yield Observation(get_last_updated_ts_fn(), {})

    return meter.create_observable_gauge(
        name=_INSTRUMENT_NAME_DAEMON_INDEX_LAST_UPDATED_TIMESTAMP,
        callbacks=[_callback],
        unit="s",
        description=(
            "Unix-epoch timestamp (seconds) of the most recent "
            "per-event-class index update at the daemon process — "
            "Pillar H Week 9 ObservableGauge per ADR-0067 D363 "
            "(W9 extension to ADR-0067 per ADR-0060 D336). Updated "
            "at daemon startup (initial materialization at "
            "init_daemon Step 8) + on every subsequent Ledger.append "
            "via the per-event-class index invalidation observer "
            "per ADR-0067 D362. Operators render the index age via "
            "PromQL's time() - "
            "outreach_factory_daemon_index_last_updated_timestamp; "
            "the per_daemon.yml dashboard panel #6 thresholds RED "
            "at > 60s (operator SLO signal for invalidation stalls)."
        ),
    )


def start_prometheus_http_server(
    port: int = _DEFAULT_PROMETHEUS_PORT,
    addr: str = _DEFAULT_PROMETHEUS_ADDR,
) -> None:
    """Start the Prometheus exposition HTTP server per ADR-0053 D291.

    Exposes the per-process Prometheus metrics on
    ``http://<addr>:<port>/metrics`` (the default Prometheus scrape
    target endpoint).

    **Operator-deliberate posture per ADR-0053 D291.** The framework
    does NOT auto-start the server — operators wiring the Prometheus
    exposition externally explicitly call this function at process
    startup. Pillar G Week 4 ships the function; production callers
    invoke it AFTER :func:`init_otel_meter_provider` (so the
    :class:`PrometheusMetricReader` is registered on the global
    :data:`prometheus_client.REGISTRY` before the HTTP server starts
    serving).

    **Default bind 127.0.0.1 (security-by-default) per ADR-0053 D291
    + R036 mitigation.** Operators deliberately expose externally by
    passing ``addr="0.0.0.0"`` IF they wire firewall + authentication
    separately. The framework default keeps the Prometheus endpoint
    localhost-only so a misconfigured deployment does NOT
    accidentally expose internal metrics on a public interface.

    Args:
        port: TCP port for the HTTP exposition server. Default
            :data:`_DEFAULT_PROMETHEUS_PORT` (``8000``).
        addr: Bind address for the HTTP exposition server. Default
            :data:`_DEFAULT_PROMETHEUS_ADDR` (``"127.0.0.1"`` —
            security-by-default).
    """
    # Lazy-import so framework-neutrality operators (skip Prometheus +
    # use OTLP) don't pull in prometheus_client at module load.
    from prometheus_client import start_http_server
    start_http_server(port=port, addr=addr)


def render_prometheus_exposition() -> bytes:
    """Render the Prometheus exposition format per ADR-0053 D288.

    Returns the same exposition string the HTTP exposition endpoint
    serves (per :func:`start_prometheus_http_server`); useful for
    tests that verify metric names + types + values WITHOUT starting
    an HTTP server.

    Per ADR-0053 D288 + D293 — the exposition format preserves the
    canonical instrument names (with ``_total`` suffix on counters,
    ``_bucket`` / ``_sum`` / ``_count`` suffixes on histograms,
    bare name on gauges). The ``# TYPE`` + ``# HELP`` headers
    surface for operators querying via curl.

    Returns:
        The Prometheus exposition format as ``bytes``.
    """
    from prometheus_client import REGISTRY, generate_latest
    return generate_latest(REGISTRY)


# ---------------------------------------------------------------------------
# OTel tracing initialization (Pillar G Week 5 per ADR-0054 D294-D299)
# ---------------------------------------------------------------------------


#: The OTel Tracer scope name for Pillar G's spans. Per ADR-0054 D295,
#: the SAME canonical scope as :data:`_METER_NAME` per the per-pillar-
#: symmetry-with-shared-aggregation pattern per RETRO-pillar-f.md item
#: 5 + ADR-0052 D283. Operators consuming the OTLP / Jaeger / Tempo /
#: Datadog tracing UI see ONE canonical namespace across both the
#: metric instruments + the trace spans.
#:
#: OTel SDK tracks Meters + Tracers in SEPARATE per-scope registries
#: internally — the same scope NAME + VERSION is used for both, but
#: the SDK does NOT confuse meter instruments with tracer spans.
_TRACER_NAME: str = "orchestrator.observability"

#: The OTel Tracer scope version. Per ADR-0054 D295, parallel to
#: :data:`_METER_VERSION` ``"0.1.0"``. Bumped at the per-week ADR by
#: future Pillar G weeks if the per-stage span set extends in a non-
#: backwards-compat way (e.g., a stage name change or a span attribute
#: closed-set extension that drops a previously-allowed key).
_TRACER_VERSION: str = "0.1.0"

#: The per-stage span name prefix per ADR-0054 D296. Span names follow
#: the convention ``"outreach_factory.<stage>.<operation>"`` (e.g.,
#: ``"outreach_factory.send.email"``). The prefix matches the per-
#: framework namespace per ADR-0052 D284's ``outreach_factory_`` metric
#: instrument prefix (period-separated for spans vs underscore-
#: separated for metrics — the OTel convention is period for trace
#: span names + underscore for Prometheus metric names).
_SPAN_NAME_PREFIX: str = "outreach_factory"

#: Closed-set of the eight pipeline stages per PILLAR-PLAN §2 Pillar G
#: + ADR-0050 D273's per-week trajectory table + ADR-0054 D296.
#:
#: Each stage maps to an operator-meaningful slice of the pipeline:
#:
#: * ``discovery`` — find leads (Pillar E + /find-leads + /find-funded-
#:   founders + /competitor-customers); emits ``discovery_dedup_hit``
#:   + ``discovery_dedup_conflict``.
#: * ``enrichment`` — discovery_lineage stamping + tier_assignment +
#:   email-verification cache (Pillar E primitives).
#: * ``research`` — research-prospect dossier (/research-prospect).
#: * ``draft`` — draft-outreach scaffold + prose composition
#:   (/draft-outreach); emits ``draft_complete``.
#: * ``review`` — humanizer-check + reconcile Pass C heal; emits
#:   ``review_approved`` + ``reconcile_drift`` + ``reconcile_healed``.
#: * ``send`` — dispatcher two-phase commit (per channel — email +
#:   li_invite + li_dm + tw_dm + calendar_booking); emits
#:   ``send_intent`` + ``send_confirmed`` + per-channel variants.
#: * ``reply`` — reply classifier + auto-unsubscribe (Pillar D);
#:   emits ``reply_classified`` + ``suppression_added`` +
#:   ``conversation_state_changed``.
#: * ``win_loss`` — conversation outcome derivation (Pillar D);
#:   emits ``conversation_outcome``.
#:
#: Future Pillar G weeks extending this frozenset MUST coordinate
#: with PILLAR-PLAN §2 Pillar G + ADR-0050 D273's per-week trajectory.
#: Adding a stage outside the eight surfaces a per-call refuse-loud
#: at :func:`traced_stage` (R031-shape closed-set mitigation extended
#: to the per-stage span surface).
_PIPELINE_STAGES: frozenset[str] = frozenset({
    "discovery",
    "enrichment",
    "research",
    "draft",
    "review",
    "send",
    "reply",
    "win_loss",
})


#: Closed-set of allowed span attribute keys per ADR-0054 D297 (the
#: privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category
#: 8 + ADR-0050 D276(b) extended to the per-span attribute surface).
#:
#: **Allowed** keys — superset of :data:`_BREAKDOWN_DIMS_ALLOWED` (the
#: nine metric breakdown dims) + the per-span-specific keys:
#:
#: * The nine metric breakdown dims: ``channel`` / ``register`` /
#:   ``source_skill`` / ``category`` / ``classification_method`` /
#:   ``outcome`` / ``reason`` / ``result_state`` / ``event_class``.
#: * Per-span-specific keys: ``person_id`` (the per-Person identifier
#:   per ADR-0010 D17; tracing surfaces consume per-Person spans);
#:   ``stage`` (the pipeline stage; auto-set by :func:`traced_stage`);
#:   ``operation`` (the per-stage operation; auto-set by
#:   :func:`traced_stage`).
#:
#: **DISALLOWED** keys per the privacy invariant per I8:
#:
#: * ``source_list`` — operator-private per ADR-0032 D148.
#: * ``draft_body`` — operator-confidential per ADR-0038 D182 + I8.
#: * ``dossier_body`` — operator-confidential per ADR-0038 D182 + I8.
#: * ``exemplar_body`` — operator-confidential per ADR-0038 D182 + I8.
#: * ``claim_text`` — operator-confidential per ADR-0038 D182 + I8.
#:
#: :func:`traced_stage` refuses-loud at attribute keys outside the
#: closed-set. Operators using the raw OTel
#: :meth:`Tracer.start_as_current_span` API directly bypass the
#: refuse-loud — the helper IS the canonical surface; the per-week-
#: reviewer's behavioral-passthrough-not-signature-only discipline
#: catches direct-API bypasses at audit time.
_SPAN_ATTRIBUTES_ALLOWED: frozenset[str] = frozenset({
    # Mirrors _BREAKDOWN_DIMS_ALLOWED (the metric breakdown surface).
    "channel",
    "register",
    "source_skill",
    "category",
    "classification_method",
    "outcome",
    "reason",
    "result_state",
    "event_class",
    # Per-span-specific keys.
    "person_id",
    "stage",
    "operation",
})


def init_otel_tracer_provider(
    *,
    resource: Resource | None = None,
    span_processors: Iterable[SpanProcessor] = (),
    set_global: bool = True,
) -> TracerProvider:
    """Initialize an OTel :class:`TracerProvider` per ADR-0054 D294.

    Pillar G Week 5 ships the OTel tracing initialization. Per
    ADR-0050 D273's per-week trajectory + ADR-0054 D294 the framework
    is **OpenTelemetry SDK** for both metrics + traces; Week 3 landed
    the :class:`MeterProvider` for metrics; Week 5 lands the
    :class:`TracerProvider` for traces. Both initializations share the
    same default :class:`Resource` (per :data:`_SERVICE_NAME` +
    :data:`_SERVICE_VERSION`) so operators consuming the OTLP export
    see one service-named resource across both metric + trace
    instruments.

    **Idempotency caveat per OTel spec.** The OTel Python SDK
    enforces ``set_tracer_provider`` "set-once" semantics (with a
    subtle nuance — the default :class:`NoOpTracerProvider` IS
    replaceable by a real provider; subsequent sets after a real
    provider is in place log a warning + do NOT take effect). Tests
    pass ``set_global=False`` to bypass; production callers (single
    startup invocation) keep ``set_global=True``. Mirrors the Week 3
    ``init_otel_meter_provider`` posture per ADR-0052 D282 + R035
    mitigation.

    **Framework-neutrality contract per ADR-0054 D298 (extending
    ADR-0052 D286 + ADR-0053 D288 to tracing).** The
    ``span_processors`` kwarg is the operator's choice of OTel
    :class:`SpanProcessor` (with the operator's chosen
    :class:`SpanExporter`: :class:`OTLPSpanExporter` for OTLP
    backends, :class:`JaegerExporter` for Jaeger, an in-memory
    exporter for tests, ...). Default is EMPTY tuple — the SDK
    accepts the TracerProvider with NO span processors; spans
    register, attributes register, but no export fires until a
    processor is added. Operators with OTLP backends wire their
    processor via this kwarg; the framework default ships ZERO
    span exporters so the framework is neutral to operator backend.

    **Default :class:`Resource` per ADR-0052 D287.** The default
    :class:`Resource` carries ``service.name`` + ``service.version``
    from :data:`_SERVICE_NAME` + :data:`_SERVICE_VERSION` (the SAME
    keys as :func:`init_otel_meter_provider`). Operators extending
    :class:`Resource` with per-tenant labels at Pillar I MUST
    preserve the two ``service.*`` keys + MAY add per-tenant keys
    (e.g., ``outreach_factory.tenant_id``).

    Args:
        resource: Optional :class:`Resource` override. Default
            carries ``service.name``/``service.version`` per
            :data:`_SERVICE_NAME` + :data:`_SERVICE_VERSION`.
        span_processors: Iterable of :class:`SpanProcessor` instances
            wrapping operator-chosen :class:`SpanExporter`. Default
            is an empty tuple (no span export until a processor is
            wired). Tests pass
            ``[SimpleSpanProcessor(InMemorySpanExporter())]``.
        set_global: Whether to call
            :func:`opentelemetry.trace.set_tracer_provider` on the
            new provider. Default ``True``. Tests pass ``False`` to
            isolate each test's provider.

    Returns:
        The newly-constructed :class:`TracerProvider` instance.
    """
    if resource is None:
        resource = Resource.create({
            SERVICE_NAME: _SERVICE_NAME,
            SERVICE_VERSION: _SERVICE_VERSION,
        })
    provider = TracerProvider(resource=resource)
    for sp in span_processors:
        provider.add_span_processor(sp)
    if set_global:
        # OTel spec: set_tracer_provider is set-once (after a real
        # provider replaces the default NoOpTracerProvider). If a
        # real provider is already set globally, the SDK logs a
        # warning + ignores. Tests pass set_global=False to keep
        # the provider local.
        _otel_trace.set_tracer_provider(provider)
    return provider


def get_tracer(tracer_provider: TracerProvider | None = None) -> Tracer:
    """Return the Pillar G observability :class:`Tracer` per ADR-0054 D295.

    The single canonical OTel scope ``"orchestrator.observability"``
    + version :data:`_TRACER_VERSION` per the per-pillar-symmetry-
    with-shared-aggregation pattern per RETRO-pillar-f.md item 5 +
    ADR-0052 D283. Operators consuming the OTLP / Jaeger / Tempo /
    Datadog tracing UI see ONE canonical scope across both metric
    instruments + trace spans.

    Args:
        tracer_provider: Optional explicit :class:`TracerProvider`
            to source the Tracer from. Default consults the global
            provider set by :func:`init_otel_tracer_provider` (or
            the no-op default if Pillar G has not been initialized
            yet — operators calling :func:`get_tracer` without prior
            :func:`init_otel_tracer_provider` get a no-op Tracer
            that doesn't surface failures, mirroring OTel's safe-
            default posture).

    Returns:
        A :class:`Tracer` scoped at ``"orchestrator.observability"``
        + :data:`_TRACER_VERSION`.
    """
    if tracer_provider is None:
        return _otel_trace.get_tracer(_TRACER_NAME, _TRACER_VERSION)
    return tracer_provider.get_tracer(_TRACER_NAME, _TRACER_VERSION)


@contextmanager
def traced_stage(
    stage: str,
    operation: str,
    *,
    attributes: dict[str, str] | None = None,
    tracer: Tracer | None = None,
) -> Iterator[Span]:
    """Context manager for per-stage span emit per ADR-0054 D296.

    The canonical per-stage span helper for Pillar G Week 5's
    tracing surface. Operators wiring per-stage spans at the
    pipeline call sites at Pillar G Week 6+ use this helper
    uniformly:

    .. code-block:: python

        with traced_stage(
            "send", "email",
            attributes={
                "channel": "email",
                "person_id": person.id,
            },
        ) as span:
            # ... two-phase commit dispatch ...
            histogram.record(elapsed_seconds, {"channel": "email"})

    **Span name convention per ADR-0054 D296** —
    ``"outreach_factory.<stage>.<operation>"`` (e.g.,
    ``"outreach_factory.send.email"``).

    **Closed-set stage validation per ADR-0054 D296.** The ``stage``
    MUST be in :data:`_PIPELINE_STAGES` (the eight pipeline stages
    per PILLAR-PLAN §2 Pillar G + ADR-0050 D273's trajectory). The
    refuse-loud at attribute time matches the R031-shape closed-set
    mitigation pattern per ADR-0050 D272 — a future contributor
    adding a span for an unrecognized stage triggers a per-call
    ``ValueError`` (operator-visible signal that the stage
    enumeration drifted from the per-pillar trajectory).

    **Privacy invariant on span attributes per ADR-0054 D297.** The
    ``attributes`` kwarg's keys MUST be in
    :data:`_SPAN_ATTRIBUTES_ALLOWED`; keys outside the closed-set
    refuse-loud with :class:`ValueError` (matching the closed-enum
    discipline per ADR-0042 D210 + ADR-0049 D263 + ADR-0050 D276(b)
    + ADR-0051 D278). The helper auto-sets ``stage`` + ``operation``
    attributes on every span; operators MAY override (but the auto-
    set values are the canonical source).

    **No-op posture when no provider initialized.** If
    :func:`init_otel_tracer_provider` has NOT been called, the OTel
    SDK's default :class:`NoOpTracerProvider` returns a
    :class:`NoOpTracer` whose :meth:`start_as_current_span` returns
    a no-op span. The helper is SAFE to call without prior
    initialization — operators wiring spans at the per-pillar call
    sites do NOT need to gate the helper invocations on
    initialization (mirroring the OTel SDK's safe-default posture).

    Args:
        stage: One of the eight pipeline stages in
            :data:`_PIPELINE_STAGES`. Refuse-loud at unknown values.
        operation: Free-form per-stage operation name (e.g.,
            ``"email"`` for the send stage, ``"find_leads"`` for
            the discovery stage). Must be non-empty.
        attributes: Optional dict of span attributes. Keys MUST be
            in :data:`_SPAN_ATTRIBUTES_ALLOWED`. The helper auto-
            sets ``stage`` + ``operation`` attributes; operators
            MAY override.
        tracer: Optional explicit :class:`Tracer`. Default consults
            the global provider per :func:`get_tracer`.

    Yields:
        The :class:`Span` (or no-op span if no provider
        initialized). Callers MAY set additional attributes on the
        yielded span via :meth:`Span.set_attribute` (with the same
        privacy invariant per I8 — the helper's closed-set check
        runs at attribute-dict time, not on subsequent
        ``set_attribute`` calls; the per-week-reviewer's
        behavioral-passthrough-not-signature-only discipline catches
        direct-API bypasses at audit time).

    Raises:
        ValueError: If ``stage`` is not in :data:`_PIPELINE_STAGES`,
            ``operation`` is empty, or any attribute key is not in
            :data:`_SPAN_ATTRIBUTES_ALLOWED`.
    """
    if stage not in _PIPELINE_STAGES:
        raise ValueError(
            "observability.traced_stage: stage "
            f"{stage!r} is NOT in _PIPELINE_STAGES. "
            f"Allowed: {sorted(_PIPELINE_STAGES)!r}. "
            "Per ADR-0054 D296 — the closed-set is the regression-"
            "barrier per the R031-shape mitigation extended to the "
            "per-stage span surface."
        )
    if not operation:
        raise ValueError(
            "observability.traced_stage: operation MUST be a non-"
            "empty string. Per ADR-0054 D296 — operation is the "
            "per-stage operation name (e.g., 'email' for the send "
            "stage)."
        )
    attrs: dict[str, str] = dict(attributes) if attributes else {}
    for key in attrs:
        if key not in _SPAN_ATTRIBUTES_ALLOWED:
            raise ValueError(
                "observability.traced_stage: attribute key "
                f"{key!r} is NOT in _SPAN_ATTRIBUTES_ALLOWED. "
                f"Allowed: {sorted(_SPAN_ATTRIBUTES_ALLOWED)!r}. "
                "Privacy invariant per I8 + ADR-0032 D148 + "
                "ADR-0038 D182 category 8 + ADR-0050 D276(b) + "
                "ADR-0054 D297."
            )
    # Auto-set stage + operation as canonical span attributes.
    attrs["stage"] = stage
    attrs["operation"] = operation
    if tracer is None:
        tracer = get_tracer()
    span_name = f"{_SPAN_NAME_PREFIX}.{stage}.{operation}"
    with tracer.start_as_current_span(
        span_name,
        attributes=attrs,
    ) as span:
        yield span


# ---------------------------------------------------------------------------
# SLO violation detector (Pillar G Week 7-8 per ADR-0056 D307-D313)
# ---------------------------------------------------------------------------


#: Closed-set of SLO names per PILLAR-PLAN §2 Pillar G binding text +
#: ADR-0056 D313. The four SLO triggers operators wire the framework
#: to fire against:
#:
#: * ``"send_latency_p99"`` — per-channel; fires when
#:   ``p99(send_intent->send_confirmed latency)`` over the window
#:   exceeds :attr:`SLOConfig.send_latency_p99_threshold_seconds`
#:   (default 5.0s per PILLAR-PLAN §2 Pillar G).
#: * ``"reconcile_success_ratio"`` — global (``channel=None``); fires
#:   when ``N_healed / (N_healed + N_drift)`` over the window is
#:   below :attr:`SLOConfig.reconcile_success_ratio_threshold`
#:   (default 0.99). Vacuous success (no reconcile activity) does
#:   NOT fire.
#: * ``"bounce_rate"`` — per-channel; fires when
#:   ``N_bounce / (N_bounce + N_confirmed)`` over the window exceeds
#:   :attr:`SLOConfig.bounce_rate_threshold` (default 0.05 = 5%).
#: * ``"manual_override_count"`` — global (``channel=None``); fires
#:   when ``count(manual_override)`` over the window exceeds
#:   :attr:`SLOConfig.manual_override_count_threshold` (default 0 —
#:   any manual_override fires the compliance review alert per
#:   PILLAR-PLAN §2 Pillar G's binding text).
#:
#: The closed-set IS the regression-barrier per the R031-shape
#: mitigation pattern extended to the SLO surface + the
#: ``slo_violation_detected.slo_name`` closed-enum. A future
#: contributor adding a NEW SLO name without coordinating with this
#: closed-set + the per-pillar ADR triggers refuse-loud at
#: :func:`detect_slo_violations`'s SLOViolation construction.
#:
#: **NEW closed-set** mutually exclusive from
#: ``reconcile_drift.reason`` (per ADR-0049 D263's closed-enum) per
#: the legacy-state-vs-new-defense-layer reason-precedence drift
#: discipline (NEW pattern surfaced at the Pillar F Week 12 follow-
#: up). The SLO span's ``reason`` attribute carries an ``_SLO_NAMES``
#: value, NOT a ``_DRIFT_REASONS`` value.
_SLO_NAMES: frozenset[str] = frozenset({
    "send_latency_p99",
    "reconcile_success_ratio",
    "bounce_rate",
    "manual_override_count",
})


@dataclass(frozen=True)
class SLOConfig:
    """Operator-configurable SLO thresholds + Slack webhook URL.

    Per ADR-0056 D309. Defaults match PILLAR-PLAN §2 Pillar G's
    binding text; operators override per-SLO threshold via instance
    kwargs. The ``slack_webhook_url`` field is ``None`` by default
    per the operator-deliberate opt-in posture per ADR-0050 D276(d)
    — operators wire the Slack alerting by passing a URL; absence
    means SLOs are observed via dashboard rendering only, no
    alerting fires.

    **Immutable** (``frozen=True``) — the config is a value object
    operators construct once at startup + pass to
    :func:`detect_slo_violations` + :func:`dispatch_slo_alert`.
    """

    #: p99 send-latency threshold in seconds. Default ``5.0`` per
    #: PILLAR-PLAN §2 Pillar G. Operators with different latency
    #: profiles (e.g., higher-latency LinkedIn auth) raise this.
    send_latency_p99_threshold_seconds: float = 5.0

    #: Reconcile success ratio threshold. Default ``0.99`` per
    #: PILLAR-PLAN §2 Pillar G. ``ratio = N_healed / (N_healed +
    #: N_drift)``; vacuous success → no violation.
    reconcile_success_ratio_threshold: float = 0.99

    #: Bounce rate threshold (per-channel). Default ``0.05`` (5%)
    #: per PILLAR-PLAN §2 Pillar G. ``rate = N_bounce / (N_bounce +
    #: N_confirmed)`` per channel.
    bounce_rate_threshold: float = 0.05

    #: manual_override count threshold. Default ``0`` per PILLAR-PLAN
    #: §2 Pillar G binding text ("any manual_override event triggers
    #: compliance review"). Operators with a non-zero baseline
    #: (e.g., expected weekly compliance approvals) raise this.
    manual_override_count_threshold: int = 0

    #: Slack webhook URL for SLO alert dispatch. Default ``None``
    #: per ADR-0050 D276(d) — operator-deliberate opt-in. Absence =
    #: SLOs observed via dashboard rendering only, no alerting
    #: fires. Operators store this in
    #: ``~/.outreach-factory/config.yml``'s ``observability:`` block
    #: + pass to :class:`SLOConfig` at framework startup.
    slack_webhook_url: str | None = None


@dataclass(frozen=True)
class SLOViolation:
    """Per-(slo_name, channel) violation snapshot per ADR-0056 D308.

    The structural commitment :func:`detect_slo_violations` returns
    + the ``slo_violation_detected`` event class consumes.

    Fields:

    * ``slo_name`` — one of :data:`_SLO_NAMES` (closed-enum per
      ADR-0056 D313).
    * ``slo_threshold`` — the threshold from the operator's
      :class:`SLOConfig`.
    * ``observed_value`` — the actual aggregate over the window.
    * ``channel`` — per ADR-0014 D33's channel-on-every-event
      invariant. ``None`` for global SLOs
      (``reconcile_success_ratio``, ``manual_override_count``);
      the channel string for per-channel SLOs
      (``send_latency_p99``, ``bounce_rate``).
    * ``window_seconds`` — the per-call window range in seconds
      (operator-supplied via :func:`detect_slo_violations`'s
      ``since_window`` kwarg).

    **Immutable** (``frozen=True``) — operators pass violations
    through dispatcher pipelines without mutation.
    """

    slo_name: str
    slo_threshold: float
    observed_value: float
    channel: str | None
    window_seconds: float


def _parse_iso_utc_for_slo(s: str | None) -> datetime | None:
    """Parse an ISO 8601 UTC timestamp; return ``None`` on missing
    or malformed input. Used by :func:`detect_slo_violations` for
    pairwise send-latency computation.

    Mirrors :func:`orchestrator.policy.budget._parse_iso_utc` per the
    deterministic-clock contract per ADR-0034 D156 + ADR-0035 D162.
    """
    if not s:
        return None
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        return datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile over ``values``.

    Per the standard NIST percentile definition (matches numpy's
    ``np.percentile`` default behavior). Used by
    :func:`detect_slo_violations` for p99 send-latency aggregation
    per ADR-0056 D307.

    Args:
        values: List of numeric values. MUST be non-empty (caller
            guards). Sorted in-place via :func:`sorted`.
        p: Percentile rank in ``[0.0, 1.0]`` (NOT ``[0, 100]``).

    Returns:
        The interpolated percentile value.
    """
    vs = sorted(values)
    if len(vs) == 1:
        return vs[0]
    k = (len(vs) - 1) * p
    f = int(k)
    c = min(f + 1, len(vs) - 1)
    if f == c:
        return vs[f]
    return vs[f] + (vs[c] - vs[f]) * (k - f)


# Per-channel ``_confirmed`` event types per ADR-0014 D33's per-channel
# two-phase commit convention. Each pairs with ``send_intent`` /
# ``li_invite_intent`` / ``li_dm_intent`` / ``tw_dm_intent`` /
# ``calendar_booking_intent`` by ``intent_id``.
_CONFIRMED_EVENT_TYPES_FOR_LATENCY: frozenset[str] = frozenset({
    "send_confirmed",
    "li_invite_confirmed",
    "li_dm_confirmed",
    "tw_dm_confirmed",
    "calendar_booking_confirmed",
})


_INTENT_EVENT_TYPES_FOR_LATENCY: frozenset[str] = frozenset({
    "send_intent",
    "li_invite_intent",
    "li_dm_intent",
    "tw_dm_intent",
    "calendar_booking_intent",
})


def detect_slo_violations(
    led: "_ledger.Ledger",
    *,
    since_window: timedelta,
    now: datetime | None = None,
    slo_config: SLOConfig | None = None,
) -> list[SLOViolation]:
    """Detect SLO violations + emit ``slo_violation_detected`` events.

    Per ADR-0056 D307-D313 — the Pillar G Week 7-8 SLO violation
    detector. Walks the ledger via :meth:`Ledger.all_events`, filters
    to the per-call window, applies the R032 synthetic-event
    exclusion (events with ``_recovered_by`` set), computes the
    four SLO aggregates per PILLAR-PLAN §2 Pillar G's binding text,
    and emits at-most-ONE ``slo_violation_detected`` event per
    ``(slo_name, channel)`` per call to ``led``.

    **Stateless contract** per ADR-0050 D272 + R033 mitigation — no
    in-process cache; every call re-walks the ledger.

    **Deterministic-clock contract** per ADR-0034 D156 + ADR-0035
    D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278 + ADR-0056
    D311. The ``now`` kwarg defaults to wall-clock; tests pass
    ``now`` for byte-identical reproducibility. ``now`` is stamped
    onto any ``slo_violation_detected`` events emitted by this call.

    **R032 synthetic-event exclusion per ADR-0056 D311.** Events
    carrying ``_recovered_by`` audit marker (backfill / reconcile /
    migration_<id> per ADR-0010 D17) are EXCLUDED from SLO
    evaluation. Operators running migration backfills do NOT see
    synthetic-data spikes trip the SLO alerts.

    **At-most-ONE emit per ``(slo_name, channel)`` per call** per
    ADR-0056 D310 — the rate-limit pattern carried forward from
    ADR-0051 D279's diagnostic emit + R034 mitigation. The per-
    channel aggregation grain naturally enforces ONE violation per
    ``(slo_name, channel)`` pair; the dedup tracking is defensive
    belt-and-suspenders.

    **Channel-on-every-event invariant** per ADR-0014 D33 + ADR-0056
    D308 — every violation's ``channel`` field carries the violating
    metric's channel (``None`` for global SLOs:
    ``reconcile_success_ratio``, ``manual_override_count``; the
    channel string for per-channel SLOs: ``send_latency_p99``,
    ``bounce_rate``).

    **Per-SLO computation per ADR-0056 D307:**

    1. ``send_latency_p99`` — pair intent + confirmed events by
       ``intent_id`` (per ADR-0014 D33's two-phase commit convention);
       per-pair latency = ``confirmed.ts - intent.ts``; per-channel
       p99 via :func:`_percentile`. Per-channel violation when
       p99 > threshold.
    2. ``reconcile_success_ratio`` — ``N_healed / (N_healed +
       N_drift)`` over the window; vacuous success → no violation.
       Violation when ratio < threshold.
    3. ``bounce_rate`` — per-channel ``N_bounce / (N_bounce +
       N_confirmed)`` over the window; vacuous (zero denominator) →
       no violation. Per-channel violation when rate > threshold.
    4. ``manual_override_count`` — count of ``manual_override``
       events in the window. Violation when count > threshold
       (default 0).

    Args:
        led: The ledger to walk + append diagnostic events to. Must
            support :meth:`Ledger.all_events` (read) +
            :meth:`Ledger.append` (write).
        since_window: The per-call window (:class:`timedelta`). The
            detector computes ``since = now - since_window``.
        now: Optional deterministic-clock anchor. Production callers
            omit; tests pass for byte-identical reproducibility.
            Used as the ``ts`` field on
            ``slo_violation_detected`` emits.
        slo_config: Optional :class:`SLOConfig` for threshold
            overrides + Slack webhook URL. Default :class:`SLOConfig`
            with the four threshold defaults per PILLAR-PLAN §2
            Pillar G + ``slack_webhook_url=None`` per ADR-0050
            D276(d).

    Returns:
        List of :class:`SLOViolation` — one per ``(slo_name, channel)``
        pair that violated its threshold. Sorted by
        ``(slo_name, channel)`` for deterministic output per ADR-0031
        D140 + ADR-0056 D308.

    See also:
        :func:`dispatch_slo_alert` — the Slack webhook dispatcher
        per ADR-0056 D312.
    """
    if slo_config is None:
        slo_config = SLOConfig()

    anchor = now if now is not None else datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    anchor = anchor.astimezone(timezone.utc)
    since = anchor - since_window
    since_iso = since.isoformat()
    window_seconds = since_window.total_seconds()

    # Per-channel send-latency pairs by intent_id.
    intents_by_iid: dict[str, "_ledger.Event"] = {}
    confirms_by_iid: dict[str, "_ledger.Event"] = {}

    # Reconcile aggregates.
    healed = 0
    drift = 0

    # Bounce rate inputs (per-channel).
    bounce_by_channel: dict[str, int] = {}
    confirmed_by_channel: dict[str, int] = {}

    # manual_override count.
    override_count = 0

    for ev in led.all_events():
        ev_type = ev.type
        ev_ts = ev.ts
        if not ev_ts or ev_ts < since_iso:
            continue
        # R032 synthetic-event exclusion per ADR-0056 D311.
        if ev.get("_recovered_by"):
            continue

        if ev_type in _INTENT_EVENT_TYPES_FOR_LATENCY:
            iid = ev.get("intent_id")
            if iid:
                intents_by_iid[iid] = ev
        elif ev_type in _CONFIRMED_EVENT_TYPES_FOR_LATENCY:
            iid = ev.get("intent_id")
            if iid:
                confirms_by_iid[iid] = ev
            # bounce_rate denominator.
            ch = ev.get("channel")
            if ch:
                confirmed_by_channel[ch] = (
                    confirmed_by_channel.get(ch, 0) + 1
                )
        elif ev_type == "reconcile_healed":
            healed += 1
        elif ev_type == "reconcile_drift":
            drift += 1
        elif ev_type == "bounce_detected":
            ch = ev.get("channel") or "email"
            bounce_by_channel[ch] = bounce_by_channel.get(ch, 0) + 1
        elif ev_type == "manual_override":
            override_count += 1

    # Compute per-channel send-latency p99.
    latencies_by_channel: dict[str, list[float]] = {}
    for iid, intent_ev in intents_by_iid.items():
        confirm_ev = confirms_by_iid.get(iid)
        if confirm_ev is None:
            continue
        t_intent = _parse_iso_utc_for_slo(intent_ev.ts)
        t_confirm = _parse_iso_utc_for_slo(confirm_ev.ts)
        if t_intent is None or t_confirm is None:
            continue
        latency = (t_confirm - t_intent).total_seconds()
        if latency < 0:
            continue
        ch = intent_ev.get("channel") or confirm_ev.get("channel")
        if not ch:
            continue
        latencies_by_channel.setdefault(ch, []).append(latency)

    violations: list[SLOViolation] = []

    # 1. send_latency_p99 — per-channel.
    for ch in sorted(latencies_by_channel.keys()):
        latencies = latencies_by_channel[ch]
        p99 = _percentile(latencies, 0.99)
        if p99 > slo_config.send_latency_p99_threshold_seconds:
            violations.append(SLOViolation(
                slo_name="send_latency_p99",
                slo_threshold=(
                    slo_config.send_latency_p99_threshold_seconds
                ),
                observed_value=p99,
                channel=ch,
                window_seconds=window_seconds,
            ))

    # 2. reconcile_success_ratio — global.
    denom_rec = healed + drift
    if denom_rec > 0:
        ratio = healed / denom_rec
        if ratio < slo_config.reconcile_success_ratio_threshold:
            violations.append(SLOViolation(
                slo_name="reconcile_success_ratio",
                slo_threshold=(
                    slo_config.reconcile_success_ratio_threshold
                ),
                observed_value=ratio,
                channel=None,
                window_seconds=window_seconds,
            ))

    # 3. bounce_rate — per-channel.
    all_channels = sorted(
        set(bounce_by_channel.keys()) | set(confirmed_by_channel.keys())
    )
    for ch in all_channels:
        b = bounce_by_channel.get(ch, 0)
        c = confirmed_by_channel.get(ch, 0)
        denom_br = b + c
        if denom_br == 0:
            continue
        rate = b / denom_br
        if rate > slo_config.bounce_rate_threshold:
            violations.append(SLOViolation(
                slo_name="bounce_rate",
                slo_threshold=slo_config.bounce_rate_threshold,
                observed_value=rate,
                channel=ch,
                window_seconds=window_seconds,
            ))

    # 4. manual_override_count — global.
    if override_count > slo_config.manual_override_count_threshold:
        violations.append(SLOViolation(
            slo_name="manual_override_count",
            slo_threshold=float(
                slo_config.manual_override_count_threshold
            ),
            observed_value=float(override_count),
            channel=None,
            window_seconds=window_seconds,
        ))

    # Emit slo_violation_detected events — at-most-ONE per
    # (slo_name, channel) per call per ADR-0056 D310.
    now_iso = _now_iso(anchor)
    emitted: set[tuple[str, str | None]] = set()
    for v in violations:
        key = (v.slo_name, v.channel)
        if key in emitted:
            continue
        emitted.add(key)
        led.append({
            "type": "slo_violation_detected",
            "ts": now_iso,
            "slo_name": v.slo_name,
            "slo_threshold": v.slo_threshold,
            "observed_value": v.observed_value,
            "channel": v.channel,
            "window_seconds": v.window_seconds,
            "_emitted_by": "observability",
        })

    # Sort for deterministic output per ADR-0031 D140 + ADR-0056 D308.
    violations.sort(key=lambda v: (v.slo_name, v.channel or ""))
    return violations


def _format_slo_slack_payload(v: SLOViolation) -> dict[str, object]:
    """Build the Slack webhook JSON payload for an SLO violation.

    Per ADR-0056 D312. The ``text`` field carries the Slack-rendered
    summary (operators see this in their Slack channel); the
    structured fields carry the per-SLO diagnostic detail operators
    consume programmatically (Slack workflows / chatops).
    """
    ch_suffix = f" (channel: {v.channel})" if v.channel else ""
    text = (
        f"SLO violation: {v.slo_name}{ch_suffix} — "
        f"observed {v.observed_value} vs threshold "
        f"{v.slo_threshold} over {v.window_seconds:.0f}s window."
    )
    return {
        "text": text,
        "slo_name": v.slo_name,
        "slo_threshold": v.slo_threshold,
        "observed_value": v.observed_value,
        "channel": v.channel,
        "window_seconds": v.window_seconds,
    }


def dispatch_slo_alert(
    violation: SLOViolation,
    *,
    slack_webhook_url: str | None,
    http_post: (
        Callable[[str, bytes, dict[str, str]], None] | None
    ) = None,
    tracer: Tracer | None = None,
) -> bool:
    """Dispatch a Slack alert for an SLO violation.

    Per ADR-0056 D312 — the Slack webhook dispatcher. Operator-
    deliberate opt-in posture per ADR-0050 D276(d): when
    ``slack_webhook_url`` is ``None`` (the default), the function
    returns ``False`` immediately + makes ZERO HTTP requests +
    emits ZERO spans (the no-op default per the OSS bring-up
    trajectory).

    **Wrapped in :func:`traced_stage`** per ADR-0056 D312 + the
    per-stage span pattern per ADR-0055 D300-D303. The Slack webhook
    invocation is a per-Slack-channel external API call; the span
    name is ``"outreach_factory.send.slack_webhook"``. Span
    attributes per ADR-0054 D297 + ADR-0056 D312:

    * ``channel`` — the violating metric's channel (or ``"none"``
      for global SLOs; OTel attributes do NOT accept ``None`` per
      spec).
    * ``reason`` — the SLO name (from :data:`_SLO_NAMES` closed-
      enum). The ``reason`` attribute key is shared with
      ``reconcile_drift.reason`` per ADR-0054 D297's
      :data:`_SPAN_ATTRIBUTES_ALLOWED` closed-set; the per-span
      value space is distinct (SLO names vs drift reasons) per the
      legacy-state-vs-new-defense-layer reason-precedence drift
      discipline.

    **Best-effort posture per ADR-0056 D312** (mirrors the
    ``cost_incurred`` emit + the per-channel histogram record posture
    per ADR-0055 D305). HTTP failures are SWALLOWED + ``False``
    returned; the SLO alert dispatch failure does NOT propagate to
    the caller (the SLO violation event is ALREADY in the ledger
    per :func:`detect_slo_violations`; operators consult the ledger
    for the operator-visible audit trail).

    Args:
        violation: The :class:`SLOViolation` to dispatch.
        slack_webhook_url: The Slack incoming webhook URL. ``None``
            (operator default per ADR-0050 D276(d)) means no
            dispatch — function returns ``False`` immediately.
        http_post: Optional dependency-injection seam for tests.
            Signature: ``(url, body_bytes, headers) -> None``
            (raises on failure). Default ``None`` uses stdlib
            :mod:`urllib.request` for the POST.
        tracer: Optional explicit :class:`Tracer`. Default consults
            the global provider per :func:`get_tracer`.

    Returns:
        ``True`` if the alert was dispatched successfully; ``False``
        if the webhook URL was ``None`` OR the HTTP POST raised.
    """
    if not slack_webhook_url:
        return False

    ch_attr: str = (
        violation.channel if violation.channel is not None else "none"
    )

    with traced_stage(
        "send", "slack_webhook",
        attributes={"channel": ch_attr, "reason": violation.slo_name},
        tracer=tracer,
    ):
        payload = _format_slo_slack_payload(violation)
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        try:
            if http_post is None:
                from urllib import request as _urllib_request
                req = _urllib_request.Request(
                    slack_webhook_url,
                    data=body,
                    headers=headers,
                    method="POST",
                )
                with _urllib_request.urlopen(req, timeout=5.0):
                    pass
            else:
                http_post(slack_webhook_url, body, headers)
            return True
        except Exception:
            return False


__all__ = [
    "COST_SOURCES_CATALOG",
    "CostSnapshot",
    "EVENT_CLASS_CATALOG",
    "MetricSnapshot",
    "OBSERVABILITY_NEW_EVENT_CLASSES",
    "SLOConfig",
    "SLOViolation",
    "collect_cost_snapshots",
    "collect_event_class_snapshots",
    "default_views",
    "detect_slo_violations",
    "dispatch_slo_alert",
    "get_meter",
    "get_send_latency_histogram",
    "get_tracer",
    "init_otel_meter_provider",
    "init_otel_tracer_provider",
    "init_prometheus_metric_reader",
    "register_daemon_index_observable_gauge",
    "register_event_class_observable_counter",
    "register_reconcile_success_ratio_gauge",
    "render_prometheus_exposition",
    "start_prometheus_http_server",
    "traced_stage",
]
