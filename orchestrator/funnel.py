"""Pillar D Week 12 + Pillar G Week 12 — attribution funnel + observability CLI.

Operator-facing CLI for the per-channel / per-category / per-method
breakdown of `reply_classified` + `conversation_outcome` events in
the ledger (Pillar D Week 12 baseline) **plus** the three binding
observability questions per ADR-0050 D275 + D276(a) + PILLAR-PLAN
§2 Pillar G (Pillar G Week 12 extension per ADR-0059 D325-D330):

1. **Why is dispatch slow today?** Per-channel send-latency p99 +
   per-channel ``send_failed`` / ``send_aborted`` counts + counts
   of operator-emitted ``slo_violation_detected`` events.
2. **Where am I losing prospects?** Per-stage funnel consulting
   :data:`ledger._STAGE_BY_EVENT_TYPE` per the Pillar G Week 1
   P3-2 carry-forward (Week 12 author closes this carry-forward).
3. **What did the gate refuse this week?** Per-rule
   ``policy_blocked`` counts + ``manual_override`` counts +
   per-source ``cost_incurred`` counts.

The CLI answers all three questions in ONE invocation per the
one-CLI-invocation invariant per ADR-0050 D276(a) — the structural
binding exit-criterion ``tests/test_multi_channel_coherence.py::
TestPillarGExitCriterion::test_operator_answers_three_questions_in_
one_cli_invocation``.

Per ADR-0031 D140 the output is **byte-identical** across consecutive
invocations against a fixed ledger state — the test surface in
``tests/test_multi_channel_coherence.py::TestPillarDExitCriterion::
test_100_message_synthetic_inbox_classifier_benchmark`` calls this
module twice and asserts identical stdout per the Pillar D exit-
criterion ROW 7 (preserved verbatim across Pillar G Week 12).

**Read-only contract.** Per ADR-0059 D325 the funnel CLI's
aggregations are **read-only** ledger walks (no ``led.append`` calls
inside ``build_report``). Operator-deliberate primitives at
:mod:`orchestrator.observability` (e.g.,
:func:`detect_slo_violations`, :func:`collect_cost_snapshots`)
emit diagnostic events when their closed-set discipline surfaces
drift — the funnel
CLI does NOT consume those primitives directly (their byte-identical
contract would conflict with this CLI's; instead the CLI walks the
ledger independently with mirror constants for the closed-sets).

Usage::

    python orchestrator/funnel.py --since 30d
    python orchestrator/funnel.py --since 30d --now 2026-05-23T12:00:00Z
    python orchestrator/funnel.py --since 30d --breakdown channel,category,classification_method
    python orchestrator/funnel.py --since 30d --json

The invocation form matches the rest of the ``orchestrator/`` modules —
bare-name imports + run-as-script-from-repo-root, per the orchestrator
package convention. The ``python -m orchestrator.funnel`` form does NOT
work (bare-name imports fail under package-style invocation).

The output JSON contains:

* ``window`` — the input args + computed since/now timestamps.
* ``totals`` — total event counts in the window for the two
  aggregated event classes (``reply_classified`` +
  ``conversation_outcome``).
* ``reply_classified_by_breakdown`` — sorted-key dict of
  ``"<channel>|<category>|<classification_method>"`` → count.
* ``conversation_outcome_by_breakdown`` — sorted-key dict of
  ``"<channel>|<outcome>"`` → count.
* ``attribution_by_outcome`` — sorted-key dict of
  ``"<outcome>"`` → ``{<attributed_touch_intent_id>: count, ...}``.
* ``dispatch_health`` (Pillar G Week 12) — sorted-key dict of the
  per-channel send-latency p99 + per-channel send_failed/aborted
  + slo_violation_detected counts answering binding question 1.
* ``prospect_funnel`` (Pillar G Week 12) — sorted-key dict of the
  per-stage funnel count consulting :data:`ledger._STAGE_BY_EVENT_TYPE`
  + the extended pipeline stages (``sent`` / ``replied`` /
  ``outcome_terminal``) answering binding question 2.
* ``gate_refusals`` (Pillar G Week 12) — sorted-key dict of the
  per-rule policy_blocked + manual_override + per-source cost
  counts answering binding question 3.

Determinism contract per ADR-0031 D140:

* All dict keys are sorted at every nesting level via
  ``json.dumps(..., sort_keys=True)``.
* All timestamps in the output (``since_iso`` / ``now_iso``) are
  computed from the input args, NOT from the wall clock at print
  time. The ``--now`` flag pins the clock for test reproducibility;
  production usage defaults to :func:`datetime.now(timezone.utc)`.
* p99 latency values are rounded to 3 decimal places to preserve
  byte-identical reproducibility under floating-point drift.
* No randomization in the aggregation paths.

The CLI exits 0 on success; ledger I/O failures propagate to a
non-zero exit per the existing ``orchestrator.reconcile`` convention.

**Privacy invariant** per I8 + ADR-0032 D148 + ADR-0038 D182 category
8 + ADR-0050 D276(b) + ADR-0058 D323. The funnel CLI's output is
COUNTS + AGGREGATES + scores; NEVER ``source_list`` / ``draft_body``
/ ``dossier_body`` / ``exemplar_body`` / ``claim_text`` /
``person_id``. Operators wanting per-Person drill-down consume the
ledger query surface directly (operator-deliberate access).

**Channel-on-every-event invariant** per ADR-0014 D33. Each
per-channel section preserves the invariant via the closed-set
discipline; the ``dispatch_health.per_channel_*`` keys are channel
names directly (no composite keys).

**Pillar G Week 12 follow-up (per-week-review findings):**

* P2-1 — :func:`_parse_iso` now promotes tz-naive timestamps to UTC
  so the latency p99 aggregation never raises ``TypeError`` on a
  mixed-awareness intent/confirmed pair (the ledger's auto-fill is
  always Z-suffixed, but operator-injected or migration-injected
  events can be tz-naive).
* P2-4 — Module-import-time regression barrier asserting
  ``set(ledger._STAGE_BY_EVENT_TYPE.values())`` ⊆
  ``set(_PILLAR_G_PIPELINE_STAGES)``. A Pillar H author extending
  the stage table without extending the funnel's pipeline stages
  tuple sees a loud ``RuntimeError`` at import time instead of an
  unhandled ``KeyError`` at the operator-facing CLI on the first
  event with the new stage.
* P3-4 — :func:`aggregate_cost_by_source` now routes events with a
  missing ``source`` field under the ``"none"`` sentinel key
  (mirroring :func:`aggregate_policy_blocked_by_rule`'s missing-rule
  fallback) so producer-side bugs surface immediately in the
  operator dashboard instead of vanishing.

Per-week-review track record at this follow-up: SIXTEEN consecutive
weeks of fresh-context reviewers catching P2s the inline author
missed (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8 + W9 + W10-11 +
W12 + W12 follow-up). The cell-level matrix coverage + behavioral-
passthrough-not-signature-only + module-level docstring drift
disciplines all hold.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# Bare imports per the orchestrator/ scripts' import convention.
import ledger as _ledger  # noqa: E402  (added by conftest.py sys.path shim)
# The funnel CLI implements its OWN read-only ledger walks per
# ADR-0059 D325 (the operator-deliberate primitives at
# :mod:`observability` emit diagnostic events which would break the
# byte-identical determinism contract per ADR-0031 D140 if invoked
# from inside ``build_report``).
import observability as _observability  # noqa: E402


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Default `--since` window — 30 days, matching the conversation TTL
#: default per ADR-0030 D132.
DEFAULT_SINCE: str = "30d"

#: Default breakdown for the `reply_classified` aggregation. Operators
#: tuning their classifier patterns query against this; Pillar G
#: dashboards consume the same aggregation surface.
DEFAULT_BREAKDOWN: tuple[str, ...] = (
    "channel", "category", "classification_method",
)

#: Event types this funnel aggregates. The two are the load-bearing
#: per-pillar outputs of Pillar D's classifier (Week 2-3) +
#: outcome-derivation (Week 9-11) substrate.
_REPLY_CLASSIFIED_TYPE: str = "reply_classified"
_CONVERSATION_OUTCOME_TYPE: str = "conversation_outcome"

#: Allowed breakdown fields per event class. Operators specifying an
#: invalid field via `--breakdown` see a refuse-loud error.
_REPLY_CLASSIFIED_FIELDS: frozenset[str] = frozenset({
    "channel", "category", "classification_method",
})
_CONVERSATION_OUTCOME_FIELDS: frozenset[str] = frozenset({
    "channel", "outcome",
})

# Pillar G Week 12 — pipeline stages for the per-stage funnel
# answering binding question 2 ("where am I losing prospects?"). The
# four pre-send stages come from :data:`ledger._STAGE_BY_EVENT_TYPE`
# (the regression-barrier per ADR-0050 D276 + the Pillar G Week 1
# P3-2 carry-forward closing this Week 12); the post-send stages
# extend with ``sent`` (``send_confirmed`` events; per ADR-0014 D33
# the per-channel ``*_confirmed`` events generalize the email
# ``send_confirmed`` shape) + ``replied`` (``reply_classified``) +
# ``outcome_terminal`` (``conversation_outcome``). The set's
# ordering preserves the pipeline-temporal ordering for the
# operator-facing read; per the JSON output's sort_keys=True
# determinism contract the JSON output sorts the keys
# alphabetically.
_PILLAR_G_PIPELINE_STAGES: tuple[str, ...] = (
    "queued",
    "researched",
    "drafted",
    "ready",
    "sent",
    "replied",
    "outcome_terminal",
)


# Pillar G Week 12 follow-up (per-week-review P2-4) — refuse-loud at
# module import if :data:`ledger._STAGE_BY_EVENT_TYPE` is ever
# extended with a stage name NOT in :data:`_PILLAR_G_PIPELINE_STAGES`.
# Without this barrier, :func:`aggregate_per_stage_funnel` would
# raise an unhandled ``KeyError`` at the operator-facing CLI on a code
# path that is not covered by the binding test (the binding test
# substrate uses the current four pre-send stages only). The
# regression-barrier mirrors the ``per-pillar mirror constants
# parity`` discipline introduced at Pillar G Week 10-11 + ADR-0058
# D322 + extended at Week 12's funnel CLI per ADR-0059 D329; the
# enforcement at import time means a Pillar H author extending
# :data:`ledger._STAGE_BY_EVENT_TYPE` sees the funnel surface fail
# loudly until they also extend :data:`_PILLAR_G_PIPELINE_STAGES`.
_stage_table_values_at_import: frozenset[str] = frozenset(
    _ledger._STAGE_BY_EVENT_TYPE.values()
)
_pipeline_stages_set_at_import: frozenset[str] = frozenset(
    _PILLAR_G_PIPELINE_STAGES
)
_stage_table_drift_at_import: frozenset[str] = (
    _stage_table_values_at_import - _pipeline_stages_set_at_import
)
if _stage_table_drift_at_import:
    raise RuntimeError(
        "orchestrator.funnel: ledger._STAGE_BY_EVENT_TYPE contains "
        f"stage(s) {sorted(_stage_table_drift_at_import)!r} not in "
        "_PILLAR_G_PIPELINE_STAGES; extend the funnel's pipeline "
        "stages tuple to match before consuming the per-stage funnel "
        "(per the per-pillar mirror constants parity discipline per "
        "ADR-0058 D322 + ADR-0059 D329)."
    )
del (
    _stage_table_values_at_import,
    _pipeline_stages_set_at_import,
    _stage_table_drift_at_import,
)

# Pillar G Week 12 — per-channel ``*_confirmed`` event types per the
# Pillar C two-phase commit convention per ADR-0014 D33. Mirrors
# :data:`observability._CONFIRMED_EVENT_TYPES_FOR_LATENCY`. Used by
# :func:`aggregate_per_channel_send_latency_p99` for the per-channel
# send-latency p99 + by :func:`aggregate_per_stage_funnel` for the
# extended ``sent`` stage count.
_CONFIRMED_TYPES_FOR_FUNNEL: frozenset[str] = frozenset({
    "send_confirmed",
    "li_invite_confirmed",
    "li_dm_confirmed",
    "tw_dm_confirmed",
    "calendar_booking_confirmed",
})

# Per-channel ``*_intent`` event types — the symmetric counterpart of
# :data:`_CONFIRMED_TYPES_FOR_FUNNEL` per the Pillar C two-phase
# commit convention. Used by
# :func:`aggregate_per_channel_send_latency_p99` for pairing intent +
# confirmed by ``intent_id``.
_INTENT_TYPES_FOR_FUNNEL: frozenset[str] = frozenset({
    "send_intent",
    "li_invite_intent",
    "li_dm_intent",
    "tw_dm_intent",
    "calendar_booking_intent",
})

# Per-channel ``*_failed`` event types — the dispatcher failure
# outcome per channel. Used by
# :func:`aggregate_per_channel_send_failed_aborted` for binding
# question 1's per-channel failure-count surface.
_FAILED_TYPES_FOR_FUNNEL: frozenset[str] = frozenset({
    "send_failed",
    "li_invite_failed",
    "li_dm_failed",
    "tw_dm_failed",
    "calendar_booking_failed",
})

# Per-channel ``*_aborted`` event types — the dispatcher operator-
# initiated abort outcome per channel. Calendar booking does NOT have
# an aborted shape per ADR-0019 D68 (the "user cancelled the booking"
# case is a separate event class). Used by
# :func:`aggregate_per_channel_send_failed_aborted`.
_ABORTED_TYPES_FOR_FUNNEL: frozenset[str] = frozenset({
    "send_aborted",
    "li_invite_aborted",
    "li_dm_aborted",
    "tw_dm_aborted",
})


def _channel_from_event(ev: object) -> str | None:
    """Return the channel name from an event, deriving from the type
    when no explicit ``channel`` field is present.

    Per ADR-0014 D33's channel-on-every-event invariant, every Pillar
    C dispatcher event SHOULD carry an explicit ``channel`` field. The
    invariant has held across Pillar C + D + E + F surfaces. For the
    funnel CLI's read-only walk, we additionally derive the channel
    from the event type prefix when the explicit field is absent (the
    derivation is the structural fallback per Pillar C's per-channel
    type convention; operators seeing the derived channel see the
    SAME aggregation as the explicit field).
    """
    ch = ev.get("channel")
    if isinstance(ch, str) and ch:
        return ch
    t = ev.get("type") or ""
    if not isinstance(t, str):
        return None
    # Per-channel type-prefix derivation; matches the per-channel two-
    # phase commit convention per ADR-0014 D33.
    if t.startswith("send_"):
        return "email"
    if t.startswith("li_invite_"):
        return "li_invite"
    if t.startswith("li_dm_"):
        return "li_dm"
    if t.startswith("tw_dm_"):
        return "tw_dm"
    if t.startswith("calendar_booking_"):
        return "calendar_booking"
    return None


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile per the standard NIST
    definition; mirrors :func:`observability._percentile`.

    Args:
        values: Non-empty list of numeric values; caller guards
            empty.
        p: Percentile rank in ``[0.0, 1.0]`` (NOT ``[0, 100]``).
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


def _parse_iso(s: str | None) -> datetime | None:
    """Parse an ISO 8601 UTC timestamp; return ``None`` on missing or
    malformed input. Mirrors :func:`observability._parse_iso_utc_for_slo`.

    Pillar G Week 12 follow-up (per-week-review P2-1) — naive
    timestamps (no ``Z`` suffix, no offset) are assumed UTC and
    promoted to tz-aware. This guards
    :func:`aggregate_per_channel_send_latency_p99`'s
    ``confirmed_ts - intent_ts`` subtraction from raising
    ``TypeError: can't subtract offset-naive and offset-aware
    datetimes`` when the ledger contains a mix of Z-suffixed
    timestamps (the :meth:`ledger.Ledger.append` auto-fill convention)
    and naive timestamps (operator-injected or migration-injected
    events that bypass auto-fill).
    """
    if not isinstance(s, str) or not s:
        return None
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        # Promote naive datetimes to UTC; matches the Z-suffix /
        # ``+00:00`` convention so subtraction in
        # ``aggregate_per_channel_send_latency_p99`` never crashes on
        # mixed-awareness pairs.
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Since-window parsing
# ---------------------------------------------------------------------------


_SINCE_RE = re.compile(r"^(\d+)([dhwm])$")


def parse_since(value: str, *, now: datetime) -> datetime:
    """Parse a since-window string of the form ``Nd`` / ``Nh`` / ``Nw`` / ``Nm``.

    * ``d`` — days
    * ``h`` — hours
    * ``w`` — weeks (7 days)
    * ``m`` — months (30 days; calendar-month approximation)

    Returns the resolved cutoff ``datetime`` (= ``now - value``).
    Raises :class:`ValueError` on malformed input.

    Examples:
        >>> from datetime import datetime, timezone
        >>> now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
        >>> parse_since("30d", now=now).isoformat()
        '2026-04-23T12:00:00+00:00'
    """
    m = _SINCE_RE.match(value.strip())
    if not m:
        raise ValueError(
            f"--since must be of the form Nd / Nh / Nw / Nm (got {value!r})"
        )
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "d":
        delta = timedelta(days=n)
    elif unit == "h":
        delta = timedelta(hours=n)
    elif unit == "w":
        delta = timedelta(weeks=n)
    elif unit == "m":
        delta = timedelta(days=n * 30)
    else:   # pragma: no cover — _SINCE_RE constrains to {d,h,w,m}
        raise ValueError(f"unknown since-unit: {unit!r}")
    return now - delta


def _iso(ts: datetime) -> str:
    """Stable ISO-8601 with millisecond precision + UTC anchor."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _composite_key(ev: dict, fields: Iterable[str]) -> str:
    """Build the ``<f1>|<f2>|...`` composite key from event fields.

    Missing or non-string fields render as the literal ``"none"`` so
    the key shape is uniform across events. Operators tuning their
    classifier seeing ``"none|interest|llm"`` in the funnel output
    immediately spot the missing-channel emit (the prior Week 1 P2-A
    surface; preserved here for visibility).
    """
    parts: list[str] = []
    for f in fields:
        v = ev.get(f)
        if isinstance(v, str) and v:
            parts.append(v)
        else:
            parts.append("none")
    return "|".join(parts)


def aggregate_reply_classified(
    led: _ledger.Ledger,
    *,
    since_iso: str,
    breakdown: Iterable[str] = DEFAULT_BREAKDOWN,
) -> tuple[int, dict[str, int]]:
    """Aggregate ``reply_classified`` events in the window.

    Returns ``(total, by_breakdown)`` where ``by_breakdown`` is a
    sorted-key dict (sorted ASCENDING by composite key).
    """
    bd = tuple(breakdown)
    for f in bd:
        if f not in _REPLY_CLASSIFIED_FIELDS:
            raise ValueError(
                f"unknown breakdown field for reply_classified: {f!r}. "
                f"Allowed: {sorted(_REPLY_CLASSIFIED_FIELDS)!r}"
            )
    counter: Counter[str] = Counter()
    total = 0
    for ev in led.all_events():
        if ev.get("type") != _REPLY_CLASSIFIED_TYPE:
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        total += 1
        counter[_composite_key(ev, bd)] += 1
    return total, dict(sorted(counter.items()))


def aggregate_conversation_outcomes(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> tuple[int, dict[str, int], dict[str, dict[str, int]]]:
    """Aggregate ``conversation_outcome`` events in the window.

    Returns:

    * ``total`` — count of outcome events in the window.
    * ``by_channel_outcome`` — sorted dict of ``"<channel>|<outcome>"``
      → count.
    * ``attribution_by_outcome`` — sorted-key 2-level dict of
      ``<outcome>`` → ``{<attributed_touch_intent_id>: count, ...}``.
      The intent-id sub-dict is sorted by key. Outcomes whose
      ``attributed_touch_intent_id`` is ``None`` use the literal
      ``"none"`` sentinel so the JSON output stays string-keyed.
    """
    by_channel_outcome: Counter[str] = Counter()
    attribution: dict[str, Counter[str]] = defaultdict(Counter)
    total = 0
    for ev in led.all_events():
        if ev.get("type") != _CONVERSATION_OUTCOME_TYPE:
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        total += 1
        ch = ev.get("channel") or "none"
        outcome = ev.get("outcome") or "none"
        by_channel_outcome[f"{ch}|{outcome}"] += 1
        iid = ev.get("attributed_touch_intent_id")
        key = iid if isinstance(iid, str) and iid else "none"
        attribution[outcome][key] += 1
    by_outcome_sorted: dict[str, dict[str, int]] = {
        k: dict(sorted(attribution[k].items()))
        for k in sorted(attribution.keys())
    }
    return (
        total,
        dict(sorted(by_channel_outcome.items())),
        by_outcome_sorted,
    )


# ---------------------------------------------------------------------------
# Pillar G Week 12 — read-only aggregations for the three binding
# questions per ADR-0050 D275 + D276(a) + PILLAR-PLAN §2 Pillar G
# ---------------------------------------------------------------------------


def aggregate_per_channel_send_latency_p99(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> dict[str, float]:
    """Aggregate per-channel send-latency p99 (seconds) over the
    window — answers binding question 1 ("why is dispatch slow today?").

    Pairs ``*_intent`` + ``*_confirmed`` events by ``intent_id``
    per the Pillar C two-phase commit convention per ADR-0014 D33;
    computes per-channel p99 via :func:`_percentile`. Latency is
    ``confirmed.ts - intent.ts`` in seconds.

    Returns a sorted-key dict of ``channel`` → ``p99_seconds`` (rounded
    to 3 decimals per the byte-identical determinism contract per
    ADR-0031 D140 — floating-point representation drift would break
    reproducibility without rounding).

    Channels with zero pairs in the window are OMITTED — operators
    seeing a missing channel see the dispatcher hasn't shipped for
    that channel in the window.
    """
    # Index intents in the window by intent_id, channel.
    intents: dict[str, tuple[str, datetime]] = {}
    for ev in led.all_events():
        t = ev.get("type")
        if t not in _INTENT_TYPES_FOR_FUNNEL:
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        intent_id = ev.get("intent_id")
        if not isinstance(intent_id, str) or not intent_id:
            continue
        ts_dt = _parse_iso(ts)
        if ts_dt is None:
            continue
        channel = _channel_from_event(ev) or "unknown"
        intents[intent_id] = (channel, ts_dt)

    # Walk confirmed events; pair by intent_id; accumulate per-channel
    # latencies.
    per_channel: dict[str, list[float]] = defaultdict(list)
    for ev in led.all_events():
        t = ev.get("type")
        if t not in _CONFIRMED_TYPES_FOR_FUNNEL:
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        intent_id = ev.get("intent_id")
        if not isinstance(intent_id, str) or not intent_id:
            continue
        paired = intents.get(intent_id)
        if paired is None:
            continue
        intent_channel, intent_ts = paired
        confirmed_ts = _parse_iso(ts)
        if confirmed_ts is None:
            continue
        latency = (confirmed_ts - intent_ts).total_seconds()
        if latency < 0:
            # Out-of-order pairing — skip; the deterministic-clock
            # contract per ADR-0034 D156 etc. guarantees this is
            # rare. Operators seeing a missing channel in the result
            # consult the ledger directly for diagnostics.
            continue
        per_channel[intent_channel].append(latency)

    out: dict[str, float] = {}
    for channel in sorted(per_channel.keys()):
        latencies = per_channel[channel]
        if not latencies:
            continue
        p99 = _percentile(latencies, 0.99)
        # Round to 3 decimals per the byte-identical determinism
        # contract per ADR-0031 D140. Float precision differs across
        # platforms; rounding pins the JSON output's value.
        out[channel] = round(p99, 3)
    return out


def aggregate_per_channel_send_failed_aborted(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> tuple[dict[str, int], dict[str, int]]:
    """Aggregate per-channel ``*_failed`` + ``*_aborted`` counts over
    the window — answers binding question 1's surface for "which
    dispatcher outcomes failed?"

    Returns ``(failed_by_channel, aborted_by_channel)`` — two sorted-
    key dicts of ``channel`` → ``count``. Channels with zero counts
    are OMITTED. The per-channel breakdown preserves the channel-on-
    every-event invariant per ADR-0014 D33.
    """
    failed: Counter[str] = Counter()
    aborted: Counter[str] = Counter()
    for ev in led.all_events():
        t = ev.get("type")
        if t not in _FAILED_TYPES_FOR_FUNNEL and t not in _ABORTED_TYPES_FOR_FUNNEL:
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        channel = _channel_from_event(ev) or "unknown"
        if t in _FAILED_TYPES_FOR_FUNNEL:
            failed[channel] += 1
        else:
            aborted[channel] += 1
    return dict(sorted(failed.items())), dict(sorted(aborted.items()))


def aggregate_slo_violation_detected_count(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> int:
    """Count ``slo_violation_detected`` events over the window —
    answers binding question 1's surface for "did the SLO detector
    fire?"

    Per ADR-0056 D309 the SLO detector emits one event per violation;
    counting them in window is the structural surface for operators
    asking "how many SLO violations did the detector fire this
    window?"
    """
    n = 0
    for ev in led.all_events():
        if ev.get("type") != "slo_violation_detected":
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        n += 1
    return n


def aggregate_per_stage_funnel(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> dict[str, int]:
    """Aggregate per-stage event counts over the window consulting
    :data:`ledger._STAGE_BY_EVENT_TYPE` — answers binding question 2
    ("where am I losing prospects?").

    The per-stage funnel surfaces:

    * ``queued`` ← ``enrolled`` events.
    * ``researched`` ← ``research_complete`` events.
    * ``drafted`` ← ``draft_complete`` events.
    * ``ready`` ← ``review_approved`` events.
    * ``sent`` ← per-channel ``*_confirmed`` events (the post-send
      stage; extends :data:`ledger._STAGE_BY_EVENT_TYPE` with the
      Pillar C dispatcher's outcome shape).
    * ``replied`` ← ``reply_classified`` events.
    * ``outcome_terminal`` ← ``conversation_outcome`` events.

    Pre-send stages are ALSO populated from ``state_transition`` events
    (``state_machine.record_transition``) by their ``to`` field — FINDING-1
    (golden-path harness; see .planning/GOLDEN-PATH-HARNESS.md): the production
    transition path emits
    ``state_transition``, not the completion markers, so without this the
    per-stage funnel was blind to real runs.

    Per the Pillar G Week 1 P3-2 carry-forward (DUE NOW per the Week
    10-11 handoff) the per-stage funnel MUST consult
    :data:`ledger._STAGE_BY_EVENT_TYPE`; Week 12 author closes this
    carry-forward by importing the table at runtime + using it as the
    structural commitment.

    Returns a sorted-key dict of ``stage`` → ``count``. Stages with
    zero events in the window are INCLUDED with count 0 — operators
    seeing the stage's count 0 see the funnel-drop point at the
    previous non-zero stage. The complete shape preserves the
    pipeline-temporal narrative.
    """
    stage_counts: dict[str, int] = {stage: 0 for stage in _PILLAR_G_PIPELINE_STAGES}
    # Pillar G Week 1 P3-2 carry-forward — consult the regression-
    # barrier table per ADR-0050 D276 + the closed-set discipline.
    stage_table = _ledger._STAGE_BY_EVENT_TYPE
    # FINDING-1 (golden-path harness; .planning/GOLDEN-PATH-HARNESS.md): the PRODUCTION transition path
    # (state_machine.record_transition) emits `state_transition` with a `to`
    # stage, NOT the research_complete/draft_complete/review_approved completion
    # markers in _STAGE_BY_EVENT_TYPE. Count those by `to` for the pre-send
    # stages only — `sent`/`replied`/`outcome_terminal` stay owned by their
    # outcome events below, so no double-count.
    pre_send_stages = frozenset(stage_table.values())
    for ev in led.all_events():
        t = ev.get("type") or ""
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        if t in stage_table:
            stage_counts[stage_table[t]] += 1
        elif t in _CONFIRMED_TYPES_FOR_FUNNEL:
            stage_counts["sent"] += 1
        elif t == "reply_classified":
            stage_counts["replied"] += 1
        elif t == "conversation_outcome":
            stage_counts["outcome_terminal"] += 1
        elif t == "state_transition":
            to_stage = ev.get("to")
            if to_stage in pre_send_stages:
                stage_counts[to_stage] += 1
    return dict(sorted(stage_counts.items()))


def aggregate_policy_blocked_by_rule(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> dict[str, int]:
    """Aggregate ``policy_blocked`` events by ``rule`` field over the
    window — answers binding question 3's surface for "which policy
    rules refused?"

    The ``rule`` field carries the firing rule's name per
    :class:`orchestrator.policy.types.Block`'s ``rule`` attribute +
    the send-gate's ``policy_blocked`` event emit at
    ``skills/send-outreach/scripts/send_queued.py``.

    Returns a sorted-key dict of ``rule`` → ``count``. Rules with
    zero refusals in the window are OMITTED. Events with missing
    ``rule`` field render under the literal ``"none"`` key per the
    existing ``_composite_key`` convention (operators spot missing-
    rule emits immediately).
    """
    counter: Counter[str] = Counter()
    for ev in led.all_events():
        if ev.get("type") != "policy_blocked":
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        rule = ev.get("rule") or ev.get("reason") or ""
        key = rule if isinstance(rule, str) and rule else "none"
        counter[key] += 1
    return dict(sorted(counter.items()))


def aggregate_manual_override_count(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> int:
    """Count ``manual_override`` events over the window — answers
    binding question 3's surface for "which sends did the operator
    manually override?"

    Per PILLAR-PLAN §2 Pillar G's binding text the
    ``manual_override`` count is the operator-deliberate compliance
    surface; the Week 7-8 SLO detector additionally raises a
    ``slo_violation_detected`` with ``slo_name=manual_override_count``
    when the count exceeds the threshold. The funnel CLI's count is
    the structural total.
    """
    n = 0
    for ev in led.all_events():
        if ev.get("type") != "manual_override":
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        n += 1
    return n


def aggregate_cost_by_source(
    led: _ledger.Ledger,
    *,
    since_iso: str,
) -> dict[str, int]:
    """Aggregate ``cost_incurred`` event counts by ``source`` field
    over the window — answers binding question 3's per-source cost
    surface.

    Per ADR-0057 D314 the ``cost_incurred`` event class carries a
    ``source`` field from the closed-set
    :data:`observability.COST_SOURCES_CATALOG`. The funnel CLI's
    aggregation is COUNTS only (per the privacy invariant per I8 +
    ADR-0050 D276(b) + ADR-0057 D316 — ``person_id`` is operator-
    confidential; the per-Person cost attribution lives at
    :func:`observability.collect_cost_snapshots` with operator-
    deliberate diagnostic emission).

    Returns a sorted-key dict of ``source`` → ``count``. Sources with
    zero events in the window are OMITTED.
    """
    counter: Counter[str] = Counter()
    for ev in led.all_events():
        if ev.get("type") != "cost_incurred":
            continue
        if ev.get("_recovered_by"):
            continue
        ts = ev.get("ts") or ""
        if ts < since_iso:
            continue
        # Pillar G Week 12 follow-up (per-week-review P3-4) —
        # producer-side bugs that drop the ``source`` field are
        # surfaced under the ``"none"`` sentinel rather than silently
        # dropped, mirroring :func:`aggregate_policy_blocked_by_rule`'s
        # missing-rule fallback.
        source = ev.get("source")
        key = source if isinstance(source, str) and source else "none"
        counter[key] += 1
    return dict(sorted(counter.items()))


# ---------------------------------------------------------------------------
# Report construction
# ---------------------------------------------------------------------------


def build_report(
    led: _ledger.Ledger,
    *,
    since: str = DEFAULT_SINCE,
    now: datetime | None = None,
    breakdown: Iterable[str] = DEFAULT_BREAKDOWN,
) -> dict:
    """Compute the full funnel report dict.

    Per ADR-0031 D140 — every key at every nesting level is sorted
    deterministically. Two invocations against the same ledger
    state with the same ``now`` MUST produce identical dicts.

    Production callers omit ``now`` → :func:`datetime.now(timezone.utc)`
    is used. Tests pass ``now`` for byte-identical reproducibility.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    since_dt = parse_since(since, now=now)
    since_iso = _iso(since_dt)
    now_iso = _iso(now)

    rc_total, rc_breakdown = aggregate_reply_classified(
        led, since_iso=since_iso, breakdown=breakdown,
    )
    co_total, co_by_channel_outcome, attribution = (
        aggregate_conversation_outcomes(led, since_iso=since_iso)
    )

    # Pillar G Week 12 — read-only aggregations for the three binding
    # questions per ADR-0050 D275 + D276(a) + PILLAR-PLAN §2 Pillar G.
    p99_per_channel = aggregate_per_channel_send_latency_p99(
        led, since_iso=since_iso,
    )
    failed_per_channel, aborted_per_channel = (
        aggregate_per_channel_send_failed_aborted(led, since_iso=since_iso)
    )
    slo_violation_count = aggregate_slo_violation_detected_count(
        led, since_iso=since_iso,
    )
    per_stage_funnel = aggregate_per_stage_funnel(led, since_iso=since_iso)
    policy_blocked_by_rule = aggregate_policy_blocked_by_rule(
        led, since_iso=since_iso,
    )
    manual_override_count = aggregate_manual_override_count(
        led, since_iso=since_iso,
    )
    cost_by_source = aggregate_cost_by_source(led, since_iso=since_iso)

    bd_list = list(breakdown)
    return {
        "window": {
            "since": since,
            "since_iso": since_iso,
            "now_iso": now_iso,
            "breakdown": bd_list,
        },
        "totals": {
            _REPLY_CLASSIFIED_TYPE: rc_total,
            _CONVERSATION_OUTCOME_TYPE: co_total,
        },
        "reply_classified_by_breakdown": rc_breakdown,
        "conversation_outcome_by_channel_outcome": co_by_channel_outcome,
        "attribution_by_outcome": attribution,
        # Pillar G Week 12 binding question 1 — "why is dispatch slow
        # today?"
        "dispatch_health": {
            "per_channel_send_latency_p99_seconds": p99_per_channel,
            "per_channel_send_failed_count": failed_per_channel,
            "per_channel_send_aborted_count": aborted_per_channel,
            "slo_violation_detected_count": slo_violation_count,
        },
        # Pillar G Week 12 binding question 2 — "where am I losing
        # prospects?"
        "prospect_funnel": {
            "per_stage_event_count": per_stage_funnel,
        },
        # Pillar G Week 12 binding question 3 — "what did the gate
        # refuse this week?"
        "gate_refusals": {
            "per_rule_policy_blocked_count": policy_blocked_by_rule,
            "manual_override_count": manual_override_count,
            "per_source_cost_event_count": cost_by_source,
        },
    }


def render_report(report: dict) -> str:
    """Render the report dict as deterministic JSON (sorted keys, trailing
    newline).

    The trailing newline matches the standard CLI tool convention so
    shell-redirected output ends cleanly. ``sort_keys=True`` is the
    load-bearing reproducibility primitive per ADR-0031 D140.
    """
    return json.dumps(report, sort_keys=True, indent=2) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_now(value: str) -> datetime:
    """Parse the optional ``--now`` argument.

    Accepts the standard ISO-8601 forms the framework's ts shape uses:

    * ``2026-05-23T12:00:00Z``
    * ``2026-05-23T12:00:00.000Z``
    * ``2026-05-23T12:00:00+00:00``

    Returns a UTC-anchored :class:`datetime`. Raises :class:`ValueError`
    on malformed input.
    """
    s = value.strip()
    # Python's fromisoformat doesn't accept the trailing 'Z' before 3.11;
    # normalize.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_breakdown(value: str) -> tuple[str, ...]:
    """Parse + validate the comma-separated ``--breakdown`` argument.

    Validates each field against :data:`_REPLY_CLASSIFIED_FIELDS` at
    parse time so operators passing a typo (e.g., ``--breakdown
    channel,categoy``) see the clean ``funnel: unknown breakdown
    field ...`` message + exit-code-2 contract rather than an uncaught
    exception from :func:`aggregate_reply_classified` mid-aggregation.

    The Week 12 per-week reviewer's P2-A finding pinned this: the
    earlier shape deferred validation to ``aggregate_reply_classified``
    which raised ``ValueError`` AFTER ``main()``'s ``try/except``,
    producing a Python traceback instead of the CLI's clean error.

    Raises :class:`ValueError` if any field is unknown or the input is
    empty.
    """
    parts = tuple(p.strip() for p in value.split(",") if p.strip())
    if not parts:
        raise ValueError("--breakdown must list at least one field")
    for f in parts:
        if f not in _REPLY_CLASSIFIED_FIELDS:
            raise ValueError(
                f"unknown breakdown field: {f!r}. "
                f"Allowed: {sorted(_REPLY_CLASSIFIED_FIELDS)!r}"
            )
    return parts


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python orchestrator/funnel.py",
        description=(
            "Pillar D attribution funnel — per-channel/category/method "
            "breakdown of classified replies + per-channel/outcome + "
            "attribution-by-touch breakdown of conversation outcomes. "
            "Output is byte-identical across consecutive invocations "
            "against a fixed ledger state per ADR-0031 D140."
        ),
    )
    parser.add_argument(
        "--since", default=DEFAULT_SINCE,
        help=(
            "Window — Nd / Nh / Nw / Nm (default: 30d). The funnel "
            "aggregates events whose ts >= now - since."
        ),
    )
    parser.add_argument(
        "--now",
        help=(
            "Pin the clock to a specific ISO timestamp. Production "
            "callers omit (the wall clock is used); tests pass for "
            "byte-identical reproducibility per ADR-0031 D140."
        ),
    )
    parser.add_argument(
        "--breakdown",
        default=",".join(DEFAULT_BREAKDOWN),
        help=(
            "Comma-separated breakdown fields for the reply_classified "
            "aggregation. Allowed: channel, category, "
            "classification_method. Default: channel,category,"
            "classification_method."
        ),
    )
    parser.add_argument(
        "--ledger-dir",
        help=(
            "Override the ledger directory (default: OUTREACH_FACTORY_"
            "LEDGER_DIR env var; else ~/.outreach-factory/ledger)."
        ),
    )
    parser.add_argument(
        "--json", dest="emit_json", action="store_true",
        help="Reserved for forward-compat. Currently the only output mode.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Returns the process exit code (0 success; 2 user-error).

    Per the Week 12 per-week reviewer's P2-A finding the try/except
    wraps every user-input parse step — ``--now`` + ``--breakdown`` +
    ``--since`` — so any malformed input produces the clean
    ``funnel: <message>\\n`` to stderr + exit 2, NOT an uncaught
    Python traceback mid-aggregation. The since-window validation
    via :func:`parse_since` is now called HERE (not inside
    :func:`build_report`) so the CLI error path is uniform across
    all three flags.
    """
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    try:
        now: datetime | None = _parse_now(args.now) if args.now else None
        breakdown = _parse_breakdown(args.breakdown)
        # Per P2-A — validate --since at parse time + capture the
        # effective `now` so build_report sees the SAME timestamp the
        # since-window was anchored against (avoids a subtle race
        # where build_report's wall-clock fallback advances between
        # the two calls).
        effective_now = now if now is not None else datetime.now(timezone.utc)
        parse_since(args.since, now=effective_now)
    except ValueError as exc:
        sys.stderr.write(f"funnel: {exc}\n")
        return 2

    ledger_dir = (
        Path(args.ledger_dir)
        if args.ledger_dir
        else Path(
            os.environ.get(
                "OUTREACH_FACTORY_LEDGER_DIR",
                str(Path.home() / ".outreach-factory" / "ledger"),
            )
        )
    )
    led = _ledger.Ledger(ledger_dir)
    report = build_report(
        led, since=args.since, now=effective_now, breakdown=breakdown,
    )
    sys.stdout.write(render_report(report))
    return 0


if __name__ == "__main__":   # pragma: no cover — CLI dispatch
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BREAKDOWN",
    "DEFAULT_SINCE",
    "aggregate_conversation_outcomes",
    "aggregate_cost_by_source",
    "aggregate_manual_override_count",
    "aggregate_per_channel_send_failed_aborted",
    "aggregate_per_channel_send_latency_p99",
    "aggregate_per_stage_funnel",
    "aggregate_policy_blocked_by_rule",
    "aggregate_reply_classified",
    "aggregate_slo_violation_detected_count",
    "build_report",
    "main",
    "parse_since",
    "render_report",
]
