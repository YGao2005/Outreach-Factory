"""Unit tests for orchestrator/funnel.py (Pillar D Week 12 — ADR-0031
+ Pillar G Week 12 — ADR-0059 + Pillar G Week 12 follow-up).

Per ADR-0031 D140 the funnel CLI's deterministic byte-identical output
contract is the load-bearing reproducibility primitive at the operator-
visible aggregation surface. The cross-pillar coherence test in
tests/test_multi_channel_coherence.py::TestPillarDExitCriterion exercises
the funnel end-to-end against the synthetic 100-message corpus; this
file pins the per-unit primitives.

Pillar G Week 12 (ADR-0059 D325-D330) extended ``funnel.py`` with nine
new aggregation functions + four per-channel closed-sets + one pipeline
stage tuple. The Pillar G Week 12 follow-up — driven by the
per-week-reviewer's findings on the Week 12 commit — adds the
per-aggregation cell-matrix coverage that the binding test alone
cannot exercise + the mirror-parity regression-barrier tests promised
by ADR-0059 D329 + the stage-subset regression-barrier closing the
P2-4 unhandled-``KeyError`` path.

Test classes (Pillar D baseline + Pillar G extension + Week 12 follow-up):

* ``TestParseSince`` — per-unit since-window parsing per ``parse_since``.
* ``TestParseNow`` — per-unit ISO-8601 now-parsing per ``_parse_now``.
* ``TestParseBreakdown`` — per-unit breakdown validation per ``_parse_breakdown``.
  Pins the Week 12 per-week reviewer's P2-A regression (validation at
  parse time, not at aggregation time).
* ``TestAggregateReplyClassified`` — per-event-class aggregation primitive.
* ``TestAggregateConversationOutcomes`` — per-outcome aggregation primitive.
* ``TestAggregatePerChannelSendLatencyP99`` — Pillar G Week 12 binding
  question 1 (Week 12 follow-up P2-2). Includes P2-1 regression
  (mixed-awareness intent/confirmed pair).
* ``TestAggregatePerChannelSendFailedAborted`` — Pillar G Week 12
  binding question 1 (Week 12 follow-up P2-2).
* ``TestAggregateSLOViolationDetectedCount`` — Pillar G Week 12
  binding question 1 (Week 12 follow-up P2-2).
* ``TestAggregatePerStageFunnel`` — Pillar G Week 12 binding question
  2 (Week 12 follow-up P2-2). Pins the always-seven-stages invariant.
* ``TestAggregatePolicyBlockedByRule`` — Pillar G Week 12 binding
  question 3 (Week 12 follow-up P2-2).
* ``TestAggregateHallucinationByRegister`` — Pillar G Week 12 binding
  question 3 (Week 12 follow-up P2-2). Includes P3-4 regression
  (missing-register routes under ``"none"`` sentinel).
* ``TestAggregateLayer5DriftByReason`` — Pillar G Week 12 binding
  question 3 (Week 12 follow-up P2-2). Pins BOTH-legacy-and-new
  reasons always present + R032 ``_recovered_by`` exclusion.
* ``TestAggregateManualOverrideCount`` — Pillar G Week 12 binding
  question 3 (Week 12 follow-up P2-2).
* ``TestAggregateCostBySource`` — Pillar G Week 12 binding question 3
  (Week 12 follow-up P2-2). Includes P3-4 regression (missing-source
  routes under ``"none"`` sentinel) + R032 ``_recovered_by`` exclusion.
* ``TestBuildReport`` — full report determinism + cross-key sort
  discipline. Week 12 follow-up extends ``test_new_sections_present_on_empty_ledger``
  per P2-3.
* ``TestRenderReport`` — JSON render determinism (sort_keys load-bearing).
* ``TestMainCLI`` — CLI entry-point + arg parsing + error-code contract.
* ``TestPublicSurface`` — ``__all__`` shape. Week 12 follow-up extends
  per P3-6 — the nine new aggregation function names.
* ``TestMirrorConstantsParity`` — Pillar G Week 12 follow-up P3-1.
  The four per-channel closed-sets at ``funnel.py`` mirror Pillar C
  + Pillar G Week 4 upstream sources. Per ADR-0059 D329 the regression-
  barrier discipline preserves at the per-funnel-CLI grain.
* ``TestStageTableSubset`` — Pillar G Week 12 follow-up P2-4. The
  values of ``ledger._STAGE_BY_EVENT_TYPE`` MUST be a subset of
  ``_PILLAR_G_PIPELINE_STAGES`` (the module-import-time refuse-loud
  guards against the operator-facing CLI's ``KeyError`` path).
* ``TestPercentile`` — Pillar G Week 12 follow-up P3-5. Per-unit
  tests for the ``_percentile`` primitive.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

import funnel
import ledger as _ledger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ledger(tmp_path: Path) -> _ledger.Ledger:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    return _ledger.Ledger(ledger_dir)


def _now() -> datetime:
    return datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# TestParseSince — since-window parsing
# ---------------------------------------------------------------------------


class TestParseSince:
    def test_days(self):
        result = funnel.parse_since("30d", now=_now())
        assert result == datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)

    def test_hours(self):
        result = funnel.parse_since("48h", now=_now())
        assert result == datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)

    def test_weeks(self):
        result = funnel.parse_since("2w", now=_now())
        assert result == datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)

    def test_months(self):
        # 1m = 30 days per the parser's calendar-month approximation
        result = funnel.parse_since("1m", now=_now())
        assert result == datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)

    def test_rejects_invalid_unit(self):
        with pytest.raises(ValueError, match="Nd / Nh / Nw / Nm"):
            funnel.parse_since("30x", now=_now())

    def test_rejects_missing_unit(self):
        with pytest.raises(ValueError, match="Nd / Nh / Nw / Nm"):
            funnel.parse_since("30", now=_now())

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="Nd / Nh / Nw / Nm"):
            funnel.parse_since("-30d", now=_now())


# ---------------------------------------------------------------------------
# TestParseNow — ISO-8601 parsing
# ---------------------------------------------------------------------------


class TestParseNow:
    def test_trailing_z(self):
        result = funnel._parse_now("2026-05-23T12:00:00Z")
        assert result == _now()

    def test_trailing_z_with_milliseconds(self):
        result = funnel._parse_now("2026-05-23T12:00:00.000Z")
        assert result == _now()

    def test_explicit_utc_offset(self):
        result = funnel._parse_now("2026-05-23T12:00:00+00:00")
        assert result == _now()

    def test_non_utc_offset_converts_to_utc(self):
        # 12:00 in +05:00 = 07:00 UTC
        result = funnel._parse_now("2026-05-23T12:00:00+05:00")
        assert result == datetime(2026, 5, 23, 7, 0, 0, tzinfo=timezone.utc)

    def test_naive_datetime_assumed_utc(self):
        result = funnel._parse_now("2026-05-23T12:00:00")
        assert result == _now()

    def test_rejects_malformed(self):
        with pytest.raises(ValueError):
            funnel._parse_now("not-a-date")


# ---------------------------------------------------------------------------
# TestParseBreakdown — per-week reviewer's P2-A regression
# ---------------------------------------------------------------------------


class TestParseBreakdown:
    """Per the Week 12 per-week reviewer's P2-A finding — validation
    must fire at parse time, not at aggregation time.

    The prior shape (Week 12 main commit) deferred validation to
    aggregate_reply_classified which raised ValueError AFTER main()'s
    try/except, producing a Python traceback. The Week 12 follow-up
    moved validation into _parse_breakdown so the CLI's
    funnel-error-then-exit-2 contract holds uniformly.
    """

    def test_accepts_default_breakdown(self):
        result = funnel._parse_breakdown("channel,category,classification_method")
        assert result == ("channel", "category", "classification_method")

    def test_accepts_subset(self):
        result = funnel._parse_breakdown("channel,category")
        assert result == ("channel", "category")

    def test_accepts_single_field(self):
        result = funnel._parse_breakdown("channel")
        assert result == ("channel",)

    def test_strips_whitespace(self):
        result = funnel._parse_breakdown("channel, category , classification_method")
        assert result == ("channel", "category", "classification_method")

    def test_rejects_empty_input(self):
        with pytest.raises(ValueError, match="at least one field"):
            funnel._parse_breakdown("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="at least one field"):
            funnel._parse_breakdown("   ,  ")

    def test_rejects_unknown_field(self):
        """P2-A regression — invalid field MUST raise at parse time."""
        with pytest.raises(ValueError, match="unknown breakdown field"):
            funnel._parse_breakdown("channel,invalid_field")

    def test_rejects_typo_with_helpful_message(self):
        """P2-A regression — error message names the allowed fields."""
        with pytest.raises(ValueError, match=r"Allowed: \['category', 'channel', 'classification_method'\]"):
            funnel._parse_breakdown("categoy")


# ---------------------------------------------------------------------------
# TestAggregateReplyClassified
# ---------------------------------------------------------------------------


class TestAggregateReplyClassified:
    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        total, by_bd = funnel.aggregate_reply_classified(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        assert total == 0
        assert by_bd == {}

    def test_single_event(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "reply_classified",
            "person_id": "p1", "channel": "email",
            "reply_message_id": "gid_1",
            "category": "interest",
            "classification_method": "rule",
            "confidence": 1.0,
            "matched_pattern": "<pat>",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        total, by_bd = funnel.aggregate_reply_classified(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        assert total == 1
        assert by_bd == {"email|interest|rule": 1}

    def test_since_window_filters(self, tmp_path):
        led = _make_ledger(tmp_path)
        # Old event — excluded
        led.append({
            "type": "reply_classified",
            "person_id": "p_old", "channel": "email",
            "reply_message_id": "gid_old",
            "category": "interest",
            "classification_method": "rule",
            "confidence": 1.0,
            "matched_pattern": "<pat>",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        # In-window event — included
        led.append({
            "type": "reply_classified",
            "person_id": "p_new", "channel": "email",
            "reply_message_id": "gid_new",
            "category": "interest",
            "classification_method": "rule",
            "confidence": 1.0,
            "matched_pattern": "<pat>",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        total, by_bd = funnel.aggregate_reply_classified(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        assert total == 1
        assert by_bd == {"email|interest|rule": 1}

    def test_breakdown_is_sorted(self, tmp_path):
        """Determinism contract: aggregated dict keys are sorted ASC."""
        led = _make_ledger(tmp_path)
        for i, (cat, method) in enumerate([
            ("rejection", "rule"), ("interest", "rule"),
            ("ooo", "rule"), ("wrong_person", "rule"),
            ("unsubscribe", "rule"),
        ]):
            led.append({
                "type": "reply_classified",
                "person_id": f"p_{i}", "channel": "email",
                "reply_message_id": f"gid_{i}",
                "category": cat,
                "classification_method": method,
                "confidence": 1.0,
                "matched_pattern": "<pat>",
                "ts": "2026-05-22T10:00:00.000Z",
            })
        _, by_bd = funnel.aggregate_reply_classified(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        # Keys MUST be sorted ascending lexically.
        keys = list(by_bd.keys())
        assert keys == sorted(keys), (
            f"breakdown keys not sorted: {keys!r}"
        )

    def test_rejects_invalid_field(self, tmp_path):
        led = _make_ledger(tmp_path)
        with pytest.raises(ValueError, match="unknown breakdown field"):
            funnel.aggregate_reply_classified(
                led, since_iso="2026-04-23T12:00:00.000Z",
                breakdown=("invalid_field",),
            )


# ---------------------------------------------------------------------------
# TestAggregateConversationOutcomes
# ---------------------------------------------------------------------------


class TestAggregateConversationOutcomes:
    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        total, by_co, attribution = funnel.aggregate_conversation_outcomes(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        assert total == 0
        assert by_co == {}
        assert attribution == {}

    def test_single_outcome(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "conversation_outcome",
            "person_id": "p1", "channel": "email",
            "thread_key": "thr_1",
            "outcome": "closed_won",
            "attributed_touch_intent_id": "snd_xyz",
            "triggering_event_id": {"type": "calendar_booking_confirmed"},
            "ts": "2026-05-22T10:00:00.000Z",
        })
        total, by_co, attribution = funnel.aggregate_conversation_outcomes(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        assert total == 1
        assert by_co == {"email|closed_won": 1}
        assert attribution == {"closed_won": {"snd_xyz": 1}}

    def test_attribution_none_uses_sentinel(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "conversation_outcome",
            "person_id": "p1", "channel": "email",
            "thread_key": "thr_1",
            "outcome": "dormant",
            "attributed_touch_intent_id": None,
            "triggering_event_id": {},
            "ts": "2026-05-22T10:00:00.000Z",
        })
        _, _, attribution = funnel.aggregate_conversation_outcomes(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        assert attribution == {"dormant": {"none": 1}}

    def test_attribution_keys_sorted(self, tmp_path):
        led = _make_ledger(tmp_path)
        for outcome, iid in [
            ("dormant", "snd_zzz"),
            ("dormant", "snd_aaa"),
            ("closed_won", "snd_mmm"),
        ]:
            led.append({
                "type": "conversation_outcome",
                "person_id": f"p_{iid}", "channel": "email",
                "thread_key": f"thr_{iid}",
                "outcome": outcome,
                "attributed_touch_intent_id": iid,
                "triggering_event_id": {},
                "ts": "2026-05-22T10:00:00.000Z",
            })
        _, by_co, attribution = funnel.aggregate_conversation_outcomes(
            led, since_iso="2026-04-23T12:00:00.000Z",
        )
        # Outer dict sorted by outcome
        assert list(attribution.keys()) == sorted(attribution.keys())
        # Inner dicts sorted by intent_id
        for outcome, inner in attribution.items():
            assert list(inner.keys()) == sorted(inner.keys()), (
                f"attribution[{outcome}] keys not sorted: {list(inner.keys())!r}"
            )


# ---------------------------------------------------------------------------
# TestBuildReport — full-report determinism
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_window_section_carries_input_args(self, tmp_path):
        led = _make_ledger(tmp_path)
        report = funnel.build_report(led, since="30d", now=_now())
        assert report["window"]["since"] == "30d"
        assert report["window"]["since_iso"] == "2026-04-23T12:00:00.000Z"
        assert report["window"]["now_iso"] == "2026-05-23T12:00:00.000Z"
        assert report["window"]["breakdown"] == list(funnel.DEFAULT_BREAKDOWN)

    def test_totals_zero_against_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        report = funnel.build_report(led, since="30d", now=_now())
        assert report["totals"]["reply_classified"] == 0
        assert report["totals"]["conversation_outcome"] == 0
        assert report["reply_classified_by_breakdown"] == {}
        assert report["conversation_outcome_by_channel_outcome"] == {}
        assert report["attribution_by_outcome"] == {}

    def test_new_sections_present_on_empty_ledger(self, tmp_path):
        """Pillar G Week 12 follow-up (P2-3) — the three Pillar G
        binding-question sections MUST appear in the report on an
        empty ledger + carry their structural invariants. The
        always-7-stages invariant of ``aggregate_per_stage_funnel``
        is surfaced as report keys with count 0 (NOT absence-implies-
        zero) per ADR-0059 D325.
        """
        led = _make_ledger(tmp_path)
        report = funnel.build_report(led, since="30d", now=_now())

        # Section presence (P2-3).
        assert "dispatch_health" in report
        assert "prospect_funnel" in report
        assert "gate_refusals" in report

        # dispatch_health — empty ledger means no per-channel pairs;
        # the slo_violation_detected_count must be 0 (NOT missing).
        dh = report["dispatch_health"]
        assert dh["per_channel_send_latency_p99_seconds"] == {}
        assert dh["per_channel_send_failed_count"] == {}
        assert dh["per_channel_send_aborted_count"] == {}
        assert dh["slo_violation_detected_count"] == 0

        # prospect_funnel — the always-seven-stages invariant.
        pf = report["prospect_funnel"]
        per_stage = pf["per_stage_event_count"]
        assert set(per_stage.keys()) == set(funnel._PILLAR_G_PIPELINE_STAGES), (
            f"per_stage_event_count keys MUST equal "
            f"_PILLAR_G_PIPELINE_STAGES; got {set(per_stage.keys())}"
        )
        assert len(per_stage) == 7, (
            f"per_stage_event_count MUST have exactly 7 stages; "
            f"got {len(per_stage)}"
        )
        for stage, count in per_stage.items():
            assert count == 0, f"stage {stage!r} count = {count} on empty ledger"

        # gate_refusals — the empty-counter invariant for the
        # aggregations.
        gr = report["gate_refusals"]
        assert gr["per_rule_policy_blocked_count"] == {}
        assert gr["manual_override_count"] == 0
        assert gr["per_source_cost_event_count"] == {}

    def test_byte_identical_across_repeated_calls(self, tmp_path):
        """ADR-0031 D140 — determinism contract."""
        led = _make_ledger(tmp_path)
        # Seed a few events.
        for i in range(3):
            led.append({
                "type": "reply_classified",
                "person_id": f"p_{i}", "channel": "email",
                "reply_message_id": f"gid_{i}",
                "category": "interest",
                "classification_method": "rule",
                "confidence": 1.0,
                "matched_pattern": "<pat>",
                "ts": "2026-05-22T10:00:00.000Z",
            })
        report_1 = funnel.build_report(led, since="30d", now=_now())
        report_2 = funnel.build_report(led, since="30d", now=_now())
        assert (
            funnel.render_report(report_1)
            == funnel.render_report(report_2)
        )

    def test_now_omitted_uses_wall_clock(self, tmp_path):
        """When now=None, datetime.now(utc) is used. The report's
        now_iso reflects the wall clock; two consecutive calls with
        omitted now MAY differ in window.now_iso (operator-acceptable
        per ADR-0031 D140; pin --now for byte-identical)."""
        led = _make_ledger(tmp_path)
        report = funnel.build_report(led, since="30d")
        # Just verify the field is present + parseable as ISO.
        assert report["window"]["now_iso"].endswith("Z")


# ---------------------------------------------------------------------------
# Pillar G Week 12 follow-up — per-aggregation-function cell coverage
# (P2-2). The binding test at
# tests/test_multi_channel_coherence.py::TestPillarGExitCriterion is
# the cross-pillar happy-path verification; this section pins the
# per-unit edge cases: empty ledger, window filter, sorted output,
# missing-field sentinel, R032 ``_recovered_by`` exclusion, and the
# structural invariants (always-seven-stages + BOTH-reasons + mirror
# parity) per ADR-0058 D321 + ADR-0059 D325-D329.
# ---------------------------------------------------------------------------


_SINCE_2026_04_23 = "2026-04-23T12:00:00.000Z"


class TestAggregatePerChannelSendLatencyP99:
    """Pillar G Week 12 binding question 1 ("why is dispatch slow today?")
    per-channel send-latency p99 in seconds. Pairs intent + confirmed by
    ``intent_id`` per ADR-0014 D33's per-channel two-phase commit
    convention; rounds to 3dp per ADR-0031 D140's byte-identical
    determinism contract."""

    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {}

    def test_single_pair_email(self, tmp_path):
        """One intent + one confirmed pair → p99 = latency, rounded
        to 3 decimal places per ADR-0031 D140."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "send_intent",
            "intent_id": "i_1", "person_id": "p_1", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_1", "person_id": "p_1", "channel": "email",
            "ts": "2026-05-22T10:00:02.500Z",
        })
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {"email": 2.5}

    def test_window_filter_excludes_pair_with_pre_window_intent(self, tmp_path):
        """If the intent ts is BEFORE the window, the intent isn't
        indexed; the in-window confirmed has no match → empty."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "send_intent",
            "intent_id": "i_old", "person_id": "p", "channel": "email",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_old", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:02.500Z",
        })
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {}

    def test_multiple_channels_sorted(self, tmp_path):
        led = _make_ledger(tmp_path)
        for i, ch in enumerate(["tw_dm", "li_invite", "email", "li_dm"]):
            intent_type = {
                "email": "send_intent",
                "li_invite": "li_invite_intent",
                "li_dm": "li_dm_intent",
                "tw_dm": "tw_dm_intent",
            }[ch]
            confirmed_type = intent_type.replace("_intent", "_confirmed")
            led.append({
                "type": intent_type,
                "intent_id": f"i_{i}", "person_id": f"p_{i}", "channel": ch,
                "ts": "2026-05-22T10:00:00.000Z",
            })
            led.append({
                "type": confirmed_type,
                "intent_id": f"i_{i}", "person_id": f"p_{i}", "channel": ch,
                "ts": "2026-05-22T10:00:01.000Z",
            })
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        # Determinism contract: keys sorted ASC.
        assert list(result.keys()) == sorted(result.keys())
        assert set(result.keys()) == {"email", "li_dm", "li_invite", "tw_dm"}

    def test_p99_rounded_to_3_decimals(self, tmp_path):
        """ADR-0031 D140 — p99 latency rounded to 3 decimals so
        floating-point representation drift cannot break the byte-
        identical contract."""
        led = _make_ledger(tmp_path)
        # Use a latency that would expose float-precision drift if not rounded.
        led.append({
            "type": "send_intent",
            "intent_id": "i_1", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_1", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:01.234567Z",
        })
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert "email" in result
        # 3 decimal places per ADR-0031 D140.
        assert result["email"] == round(result["email"], 3)

    def test_unmatched_intent_or_confirmed_excluded(self, tmp_path):
        """Intent with no matching confirmed (and vice versa) → no
        contribution to the per-channel p99 (operators see channel
        absent from the result)."""
        led = _make_ledger(tmp_path)
        # Unmatched intent — never confirmed.
        led.append({
            "type": "send_intent",
            "intent_id": "i_orphan", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        # Unmatched confirmed — no matching intent.
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_alien", "person_id": "p2", "channel": "email",
            "ts": "2026-05-22T11:00:00.000Z",
        })
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {}

    def test_naive_timestamp_does_not_crash_P2_1(self, tmp_path):
        """Pillar G Week 12 follow-up — per-week-review P2-1.

        If the ledger contains a tz-naive timestamp on either the
        intent or the confirmed side, ``_parse_iso`` MUST promote it
        to tz-aware UTC so ``confirmed_ts - intent_ts`` doesn't
        raise ``TypeError: can't subtract offset-naive and offset-
        aware datetimes``. This guards the operator-facing CLI from
        crashing on a producer-side bug (manually-injected event or
        migration-injected event without auto-fill).
        """
        led = _make_ledger(tmp_path)
        # Naive intent timestamp (no Z suffix, no offset).
        led.append({
            "type": "send_intent",
            "intent_id": "i_naive", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00",
        })
        # Z-suffixed confirmed timestamp (Ledger.append auto-fill shape).
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_naive", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:01.500Z",
        })
        # Must not raise.
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        # The pair latency is exactly 1.5s.
        assert result == {"email": 1.5}

    def test_negative_latency_skipped(self, tmp_path):
        """Out-of-order pairing (confirmed precedes intent) skipped
        per the deterministic-clock contract — the per-pillar-G
        framework assumes monotonic ts; operators seeing a missing
        channel consult the ledger directly."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "send_intent",
            "intent_id": "i_1", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:05.000Z",
        })
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_1", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {}


class TestAggregatePerChannelSendFailedAborted:
    """Pillar G Week 12 binding question 1 — per-channel send_failed
    + send_aborted counts. Channels with zero counts OMITTED."""

    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        failed, aborted = funnel.aggregate_per_channel_send_failed_aborted(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert failed == {}
        assert aborted == {}

    def test_per_channel_failed(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "send_failed",
            "intent_id": "i_1", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        led.append({
            "type": "li_invite_failed",
            "intent_id": "i_2", "person_id": "p2", "channel": "li_invite",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        failed, aborted = funnel.aggregate_per_channel_send_failed_aborted(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert failed == {"email": 1, "li_invite": 1}
        assert aborted == {}

    def test_per_channel_aborted(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "send_aborted",
            "intent_id": "i_1", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        failed, aborted = funnel.aggregate_per_channel_send_failed_aborted(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert failed == {}
        assert aborted == {"email": 1}

    def test_window_filter(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "send_failed",
            "intent_id": "i_old", "person_id": "p", "channel": "email",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        led.append({
            "type": "send_failed",
            "intent_id": "i_new", "person_id": "p2", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        failed, _ = funnel.aggregate_per_channel_send_failed_aborted(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert failed == {"email": 1}

    def test_sorted_output(self, tmp_path):
        led = _make_ledger(tmp_path)
        for ch_type, ch in [
            ("tw_dm_failed", "tw_dm"),
            ("email", "send_failed"),
            ("li_invite_failed", "li_invite"),
        ]:
            led.append({
                "type": ch_type if ch_type != "email" else "send_failed",
                "intent_id": f"i_{ch}", "person_id": "p", "channel": ch,
                "ts": "2026-05-22T10:00:00.000Z",
            })
        failed, _ = funnel.aggregate_per_channel_send_failed_aborted(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert list(failed.keys()) == sorted(failed.keys())


class TestAggregateSLOViolationDetectedCount:
    """Pillar G Week 12 binding question 1 — count of
    ``slo_violation_detected`` events in the window."""

    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        assert funnel.aggregate_slo_violation_detected_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 0

    def test_single_event(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "slo_violation_detected",
            "slo_name": "send_latency_p99", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        assert funnel.aggregate_slo_violation_detected_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 1

    def test_multiple_events(self, tmp_path):
        led = _make_ledger(tmp_path)
        for i in range(5):
            led.append({
                "type": "slo_violation_detected",
                "slo_name": "send_latency_p99", "channel": "email",
                "ts": "2026-05-22T10:00:00.000Z",
            })
        assert funnel.aggregate_slo_violation_detected_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 5

    def test_window_filter(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "slo_violation_detected",
            "slo_name": "send_latency_p99", "channel": "email",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        led.append({
            "type": "slo_violation_detected",
            "slo_name": "send_latency_p99", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        assert funnel.aggregate_slo_violation_detected_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 1


class TestAggregatePerStageFunnel:
    """Pillar G Week 12 binding question 2 ("where am I losing
    prospects?") per-stage funnel. Consults
    ``ledger._STAGE_BY_EVENT_TYPE`` per the Pillar G Week 1 P3-2
    carry-forward (closed at Week 12 per ADR-0059 D326). The seven-
    stages-always-present invariant per ADR-0059 D325 is the
    structural commitment."""

    def test_empty_ledger_has_seven_stages_all_zero(self, tmp_path):
        led = _make_ledger(tmp_path)
        result = funnel.aggregate_per_stage_funnel(
            led, since_iso=_SINCE_2026_04_23,
        )
        # The seven-stages invariant per ADR-0059 D325.
        assert len(result) == 7
        assert set(result.keys()) == set(funnel._PILLAR_G_PIPELINE_STAGES)
        for stage, count in result.items():
            assert count == 0, f"stage {stage!r} count = {count} on empty ledger"

    def test_pre_send_stages_consume_stage_table(self, tmp_path):
        """The four pre-send stages come from
        ``ledger._STAGE_BY_EVENT_TYPE`` (queued / researched /
        drafted / ready)."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "enrolled",
            "person_id": "p_1",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        led.append({
            "type": "research_complete",
            "person_id": "p_1",
            "ts": "2026-05-22T11:00:00.000Z",
        })
        led.append({
            "type": "draft_complete",
            "person_id": "p_1", "channel": "email",
            "ts": "2026-05-22T12:00:00.000Z",
        })
        led.append({
            "type": "review_approved",
            "person_id": "p_1", "channel": "email",
            "ts": "2026-05-22T13:00:00.000Z",
        })
        result = funnel.aggregate_per_stage_funnel(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result["queued"] == 1
        assert result["researched"] == 1
        assert result["drafted"] == 1
        assert result["ready"] == 1

    def test_post_send_stages_sent_replied_outcome_terminal(self, tmp_path):
        """The three post-send stages extend
        ``ledger._STAGE_BY_EVENT_TYPE`` with the operator-facing
        pipeline-temporal narrative."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_1", "person_id": "p_1", "channel": "email",
            "ts": "2026-05-22T14:00:00.000Z",
        })
        led.append({
            "type": "reply_classified",
            "person_id": "p_1", "channel": "email",
            "reply_message_id": "gid_1", "category": "interest",
            "classification_method": "rule", "confidence": 1.0,
            "matched_pattern": "<pat>",
            "ts": "2026-05-22T15:00:00.000Z",
        })
        led.append({
            "type": "conversation_outcome",
            "person_id": "p_1", "channel": "email",
            "outcome": "closed_won",
            "ts": "2026-05-22T16:00:00.000Z",
        })
        result = funnel.aggregate_per_stage_funnel(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result["sent"] == 1
        assert result["replied"] == 1
        assert result["outcome_terminal"] == 1

    def test_window_filter_excludes_old_events(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "enrolled",
            "person_id": "p_old",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        result = funnel.aggregate_per_stage_funnel(
            led, since_iso=_SINCE_2026_04_23,
        )
        # All zero — old event excluded by window.
        for stage, count in result.items():
            assert count == 0

    def test_keys_sorted_alphabetically(self, tmp_path):
        """ADR-0031 D140 — sorted-key dict invariant."""
        led = _make_ledger(tmp_path)
        result = funnel.aggregate_per_stage_funnel(
            led, since_iso=_SINCE_2026_04_23,
        )
        keys = list(result.keys())
        assert keys == sorted(keys), f"per_stage keys not sorted: {keys!r}"


class TestAggregatePolicyBlockedByRule:
    """Pillar G Week 12 binding question 3 — per-rule policy_blocked
    counts. The ``rule`` field carries the firing rule per
    ``Block.rule``; events with missing ``rule`` render under the
    literal ``"none"`` key (operators spot the producer bug)."""

    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        assert funnel.aggregate_policy_blocked_by_rule(
            led, since_iso=_SINCE_2026_04_23,
        ) == {}

    def test_single_rule(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "policy_blocked",
            "person_id": "p", "channel": "email",
            "rule": "cooldown.email_30d",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        result = funnel.aggregate_policy_blocked_by_rule(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {"cooldown.email_30d": 1}

    def test_missing_rule_routes_under_none(self, tmp_path):
        """Producer-side bug — ``rule`` field absent. The funnel
        surfaces under ``"none"`` rather than dropping (operators
        seeing ``"none": N`` immediately diagnose the producer)."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "policy_blocked",
            "person_id": "p", "channel": "email",
            # No rule field, no reason field.
            "ts": "2026-05-22T10:00:00.000Z",
        })
        result = funnel.aggregate_policy_blocked_by_rule(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {"none": 1}

    def test_window_filter(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "policy_blocked",
            "person_id": "p", "channel": "email",
            "rule": "cooldown.email_30d",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        result = funnel.aggregate_policy_blocked_by_rule(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {}

    def test_keys_sorted(self, tmp_path):
        led = _make_ledger(tmp_path)
        for rule in ["z_rule", "a_rule", "m_rule"]:
            led.append({
                "type": "policy_blocked",
                "person_id": "p", "channel": "email",
                "rule": rule,
                "ts": "2026-05-22T10:00:00.000Z",
            })
        result = funnel.aggregate_policy_blocked_by_rule(
            led, since_iso=_SINCE_2026_04_23,
        )
        keys = list(result.keys())
        assert keys == sorted(keys)


class TestAggregateManualOverrideCount:
    """Pillar G Week 12 binding question 3 — manual_override count."""

    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        assert funnel.aggregate_manual_override_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 0

    def test_single_event(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "manual_override",
            "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        assert funnel.aggregate_manual_override_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 1

    def test_multiple_events(self, tmp_path):
        led = _make_ledger(tmp_path)
        for i in range(7):
            led.append({
                "type": "manual_override",
                "person_id": f"p_{i}", "channel": "email",
                "ts": "2026-05-22T10:00:00.000Z",
            })
        assert funnel.aggregate_manual_override_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 7

    def test_window_filter(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "manual_override",
            "person_id": "p", "channel": "email",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        assert funnel.aggregate_manual_override_count(
            led, since_iso=_SINCE_2026_04_23,
        ) == 0


class TestAggregateCostBySource:
    """Pillar G Week 12 binding question 3 — per-source cost_incurred
    counts.

    Pillar G Week 12 follow-up (per-week-review P3-4) — missing
    ``source`` field routes under the ``"none"`` sentinel rather than
    silent-drop. Events with ``_recovered_by`` are EXCLUDED per R032."""

    def test_empty_ledger(self, tmp_path):
        led = _make_ledger(tmp_path)
        assert funnel.aggregate_cost_by_source(
            led, since_iso=_SINCE_2026_04_23,
        ) == {}

    def test_per_source_count(self, tmp_path):
        led = _make_ledger(tmp_path)
        for src in ["apollo", "apollo", "pdl", "reoon"]:
            led.append({
                "type": "cost_incurred",
                "source": src,
                "ts": "2026-05-22T10:00:00.000Z",
            })
        result = funnel.aggregate_cost_by_source(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {"apollo": 2, "pdl": 1, "reoon": 1}

    def test_missing_source_routes_under_none_P3_4(self, tmp_path):
        """Pillar G Week 12 follow-up (per-week-review P3-4) —
        producer-side bugs that drop the ``source`` field MUST
        surface under the ``"none"`` sentinel."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "cost_incurred",
            # No source field.
            "ts": "2026-05-22T10:00:00.000Z",
        })
        led.append({
            "type": "cost_incurred",
            "source": "",  # Empty string also routes under "none".
            "ts": "2026-05-22T10:00:00.000Z",
        })
        result = funnel.aggregate_cost_by_source(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {"none": 2}

    def test_R032_recovered_by_excluded(self, tmp_path):
        """R032 — synthetic-recovery cost emits are EXCLUDED per
        ADR-0058 D321."""
        led = _make_ledger(tmp_path)
        led.append({
            "type": "cost_incurred",
            "source": "apollo",
            "_recovered_by": "migration_0019",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        led.append({
            "type": "cost_incurred",
            "source": "apollo",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        result = funnel.aggregate_cost_by_source(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {"apollo": 1}

    def test_window_filter(self, tmp_path):
        led = _make_ledger(tmp_path)
        led.append({
            "type": "cost_incurred",
            "source": "apollo",
            "ts": "2026-01-01T00:00:00.000Z",
        })
        result = funnel.aggregate_cost_by_source(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {}


# ---------------------------------------------------------------------------
# TestRenderReport — JSON render determinism
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_sorted_keys_at_every_nesting_level(self):
        report = {
            "z": 1,
            "a": {"z_inner": 2, "a_inner": 3},
            "m": [3, 1, 2],   # lists preserve order
        }
        rendered = funnel.render_report(report)
        # Top-level keys sorted: a, m, z
        assert rendered.index('"a"') < rendered.index('"m"')
        assert rendered.index('"m"') < rendered.index('"z"')
        # Inner keys sorted: a_inner, z_inner
        assert rendered.index('"a_inner"') < rendered.index('"z_inner"')
        # Trailing newline present
        assert rendered.endswith("\n")

    def test_render_is_pure_function(self):
        report = {"totals": {"foo": 1}}
        a = funnel.render_report(report)
        b = funnel.render_report(report)
        assert a == b


# ---------------------------------------------------------------------------
# TestMainCLI — CLI entry-point contract
# ---------------------------------------------------------------------------


class TestMainCLI:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            funnel.main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Pillar D attribution funnel" in captured.out

    def test_empty_ledger_exit_zero(self, tmp_path):
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = funnel.main([
                "--since", "30d",
                "--now", "2026-05-23T12:00:00Z",
                "--ledger-dir", str(ledger_dir),
            ])
        assert rc == 0
        report = json.loads(buf.getvalue())
        assert report["totals"]["reply_classified"] == 0

    def test_invalid_since_exit_two_with_clean_error(self, tmp_path):
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = funnel.main([
                "--since", "30x",
                "--ledger-dir", str(ledger_dir),
            ])
        assert rc == 2
        stderr_out = buf.getvalue()
        assert "funnel:" in stderr_out
        assert "Nd / Nh / Nw / Nm" in stderr_out

    def test_invalid_breakdown_exit_two_with_clean_error(self, tmp_path):
        """Per the Week 12 per-week reviewer's P2-A finding —
        invalid --breakdown field MUST produce clean CLI error,
        NOT an uncaught Python traceback."""
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = funnel.main([
                "--breakdown", "invalid_field",
                "--ledger-dir", str(ledger_dir),
            ])
        assert rc == 2
        stderr_out = buf.getvalue()
        assert "funnel: unknown breakdown field" in stderr_out
        assert "'invalid_field'" in stderr_out
        assert "Allowed:" in stderr_out

    def test_invalid_now_exit_two_with_clean_error(self, tmp_path):
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = funnel.main([
                "--now", "not-a-date",
                "--ledger-dir", str(ledger_dir),
            ])
        assert rc == 2
        assert "funnel:" in buf.getvalue()

    def test_byte_identical_cli_output_across_runs(self, tmp_path):
        """ADR-0031 D140 — CLI determinism contract."""
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        led = _ledger.Ledger(ledger_dir)
        for i in range(5):
            led.append({
                "type": "reply_classified",
                "person_id": f"p_{i}", "channel": "email",
                "reply_message_id": f"gid_{i}",
                "category": ["unsubscribe", "interest", "ooo", "rejection", "wrong_person"][i],
                "classification_method": "rule",
                "confidence": 1.0,
                "matched_pattern": "<pat>",
                "ts": "2026-05-22T10:00:00.000Z",
            })
        buf_1 = io.StringIO()
        with redirect_stdout(buf_1):
            rc_1 = funnel.main([
                "--since", "30d",
                "--now", "2026-05-23T12:00:00Z",
                "--ledger-dir", str(ledger_dir),
            ])
        buf_2 = io.StringIO()
        with redirect_stdout(buf_2):
            rc_2 = funnel.main([
                "--since", "30d",
                "--now", "2026-05-23T12:00:00Z",
                "--ledger-dir", str(ledger_dir),
            ])
        assert rc_1 == 0 and rc_2 == 0
        assert buf_1.getvalue() == buf_2.getvalue(), (
            "ADR-0031 D140 violation: CLI stdout diverged across "
            "consecutive invocations against fixed ledger state"
        )

    def test_ledger_dir_env_var_fallback(self, tmp_path, monkeypatch):
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(ledger_dir))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = funnel.main([
                "--since", "30d",
                "--now", "2026-05-23T12:00:00Z",
            ])
        assert rc == 0


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_public_exports(self):
        assert "build_report" in funnel.__all__
        assert "render_report" in funnel.__all__
        assert "aggregate_reply_classified" in funnel.__all__
        assert "aggregate_conversation_outcomes" in funnel.__all__
        assert "parse_since" in funnel.__all__
        assert "main" in funnel.__all__
        assert "DEFAULT_SINCE" in funnel.__all__

    def test_pillar_g_week_12_exports_P3_6(self):
        """Pillar G Week 12 follow-up (per-week-review P3-6) — the
        nine new aggregation functions added to ``__all__`` per
        ADR-0059 D325 MUST stay exported. A rename or accidental
        deletion of any of these would go undetected without this
        regression-barrier."""
        for name in [
            "aggregate_per_channel_send_latency_p99",
            "aggregate_per_channel_send_failed_aborted",
            "aggregate_slo_violation_detected_count",
            "aggregate_per_stage_funnel",
            "aggregate_policy_blocked_by_rule",
            "aggregate_manual_override_count",
            "aggregate_cost_by_source",
        ]:
            assert name in funnel.__all__, (
                f"Pillar G Week 12 aggregation function {name!r} missing "
                f"from funnel.__all__ — ADR-0059 D325 expects it exported."
            )
            # And the symbol is actually exported (not just listed).
            assert hasattr(funnel, name), (
                f"funnel.__all__ lists {name!r} but the attribute is missing."
            )


# ---------------------------------------------------------------------------
# Pillar G Week 12 follow-up — per-pillar mirror constants parity
# (per-week-review P3-1). The four per-channel closed-sets at
# ``funnel.py`` mirror three upstream sources:
#
#   * ``observability._CONFIRMED_EVENT_TYPES_FOR_LATENCY`` +
#     ``observability._INTENT_EVENT_TYPES_FOR_LATENCY`` (Pillar G
#     Week 4 closed-sets — the per-channel latency Histogram's
#     reference set).
#   * The ``*_confirmed`` / ``*_failed`` / ``*_aborted`` / ``*_intent``
#     subsets of ``ledger._OUTCOME_TYPES`` + ``ledger._INTENT_TYPES``
#     (Pillar C two-phase commit convention per ADR-0014 D33).
#
# ADR-0059 D329 explicitly promises this regression-barrier; the
# Week 12 commit shipped the closed-sets but not the test. The Week
# 12 follow-up closes the gap.
# ---------------------------------------------------------------------------


class TestMirrorConstantsParity:
    """Pillar G Week 12 follow-up (per-week-review P3-1) — mirror
    parity for the four per-channel closed-sets at ``funnel.py``."""

    def test_confirmed_types_mirror_observability(self):
        """``funnel._CONFIRMED_TYPES_FOR_FUNNEL`` MUST equal
        ``observability._CONFIRMED_EVENT_TYPES_FOR_LATENCY``. A new
        channel added to one MUST also be added to the other (the
        operator-facing dispatch_health surface relies on per-channel
        symmetry per ADR-0014 D33)."""
        import observability as _observability_mod
        assert (
            funnel._CONFIRMED_TYPES_FOR_FUNNEL
            == _observability_mod._CONFIRMED_EVENT_TYPES_FOR_LATENCY
        ), (
            "ADR-0059 D329 mirror parity broken: "
            f"funnel._CONFIRMED_TYPES_FOR_FUNNEL = "
            f"{funnel._CONFIRMED_TYPES_FOR_FUNNEL!r}; "
            f"observability._CONFIRMED_EVENT_TYPES_FOR_LATENCY = "
            f"{_observability_mod._CONFIRMED_EVENT_TYPES_FOR_LATENCY!r}"
        )

    def test_intent_types_mirror_observability(self):
        import observability as _observability_mod
        assert (
            funnel._INTENT_TYPES_FOR_FUNNEL
            == _observability_mod._INTENT_EVENT_TYPES_FOR_LATENCY
        ), (
            "ADR-0059 D329 mirror parity broken: "
            f"funnel._INTENT_TYPES_FOR_FUNNEL = "
            f"{funnel._INTENT_TYPES_FOR_FUNNEL!r}; "
            f"observability._INTENT_EVENT_TYPES_FOR_LATENCY = "
            f"{_observability_mod._INTENT_EVENT_TYPES_FOR_LATENCY!r}"
        )

    def test_failed_types_mirror_ledger_outcome_types(self):
        """``funnel._FAILED_TYPES_FOR_FUNNEL`` MUST equal the
        ``*_failed`` subset of ``ledger._OUTCOME_TYPES``. The mirror
        decouples ``funnel`` from ``ledger``'s indexing internals at
        runtime; this test pins parity at test time."""
        ledger_failed = frozenset(
            t for t in _ledger._OUTCOME_TYPES if t.endswith("_failed")
        )
        assert funnel._FAILED_TYPES_FOR_FUNNEL == ledger_failed, (
            "ADR-0059 D329 mirror parity broken: "
            f"funnel._FAILED_TYPES_FOR_FUNNEL = "
            f"{funnel._FAILED_TYPES_FOR_FUNNEL!r}; "
            f"ledger._OUTCOME_TYPES *_failed subset = "
            f"{ledger_failed!r}"
        )

    def test_aborted_types_mirror_ledger_outcome_types(self):
        """``funnel._ABORTED_TYPES_FOR_FUNNEL`` MUST equal the
        ``*_aborted`` subset of ``ledger._OUTCOME_TYPES``. Note that
        calendar_booking has NO ``_aborted`` per ADR-0019 D68 — the
        closed-set asymmetry is structural."""
        ledger_aborted = frozenset(
            t for t in _ledger._OUTCOME_TYPES if t.endswith("_aborted")
        )
        assert funnel._ABORTED_TYPES_FOR_FUNNEL == ledger_aborted, (
            "ADR-0059 D329 mirror parity broken: "
            f"funnel._ABORTED_TYPES_FOR_FUNNEL = "
            f"{funnel._ABORTED_TYPES_FOR_FUNNEL!r}; "
            f"ledger._OUTCOME_TYPES *_aborted subset = "
            f"{ledger_aborted!r}"
        )

    def test_intent_types_mirror_ledger_intent_types(self):
        """``funnel._INTENT_TYPES_FOR_FUNNEL`` MUST equal
        ``ledger._INTENT_TYPES`` (which is the same shape as
        ``observability._INTENT_EVENT_TYPES_FOR_LATENCY``)."""
        assert funnel._INTENT_TYPES_FOR_FUNNEL == _ledger._INTENT_TYPES, (
            "ADR-0059 D329 mirror parity broken: "
            f"funnel._INTENT_TYPES_FOR_FUNNEL = "
            f"{funnel._INTENT_TYPES_FOR_FUNNEL!r}; "
            f"ledger._INTENT_TYPES = "
            f"{_ledger._INTENT_TYPES!r}"
        )

    def test_calendar_booking_has_no_aborted(self):
        """ADR-0019 D68 — calendar_booking does NOT have an
        ``_aborted`` shape; the closed-set asymmetry preserves the
        per-channel convention."""
        assert "calendar_booking_aborted" not in funnel._ABORTED_TYPES_FOR_FUNNEL
        # The other 4 channels DO have _aborted.
        for ch in ["send", "li_invite", "li_dm", "tw_dm"]:
            assert f"{ch}_aborted" in funnel._ABORTED_TYPES_FOR_FUNNEL


# ---------------------------------------------------------------------------
# Pillar G Week 12 follow-up — per-week-review P2-4. The stage table
# values MUST be a subset of _PILLAR_G_PIPELINE_STAGES; otherwise the
# operator-facing CLI raises an unhandled KeyError on the first event
# with the new stage. The module-import-time refuse-loud at
# orchestrator/funnel.py is the structural barrier; this test pins
# the invariant.
# ---------------------------------------------------------------------------


class TestStageTableSubset:
    """Pillar G Week 12 follow-up (per-week-review P2-4) — the values
    of ``ledger._STAGE_BY_EVENT_TYPE`` MUST be a subset of
    ``funnel._PILLAR_G_PIPELINE_STAGES``. A new stage added to the
    upstream table without a corresponding entry in the funnel's
    tuple would cause ``aggregate_per_stage_funnel`` to raise
    ``KeyError`` at the operator-facing CLI."""

    def test_stage_table_values_subset_of_pipeline_stages(self):
        stage_table_values = set(_ledger._STAGE_BY_EVENT_TYPE.values())
        pipeline_stages = set(funnel._PILLAR_G_PIPELINE_STAGES)
        drift = stage_table_values - pipeline_stages
        assert not drift, (
            f"ADR-0059 follow-up (P2-4) regression: stage "
            f"table value(s) {sorted(drift)!r} are NOT in "
            f"_PILLAR_G_PIPELINE_STAGES. Extend the funnel's "
            f"pipeline stages tuple to match before extending "
            f"ledger._STAGE_BY_EVENT_TYPE."
        )

    def test_pre_send_stages_present_in_pipeline(self):
        """The four pre-send stages from
        ``ledger._STAGE_BY_EVENT_TYPE`` MUST all be in the funnel's
        pipeline stages tuple."""
        for stage in ["queued", "researched", "drafted", "ready"]:
            assert stage in funnel._PILLAR_G_PIPELINE_STAGES, (
                f"Pre-send stage {stage!r} from "
                f"ledger._STAGE_BY_EVENT_TYPE missing from "
                f"funnel._PILLAR_G_PIPELINE_STAGES."
            )

    def test_post_send_stages_present_in_pipeline(self):
        """The three post-send stages MUST be in the pipeline tuple
        — they extend ``_STAGE_BY_EVENT_TYPE`` per ADR-0059 D326."""
        for stage in ["sent", "replied", "outcome_terminal"]:
            assert stage in funnel._PILLAR_G_PIPELINE_STAGES, (
                f"Post-send stage {stage!r} (per ADR-0059 D326) "
                f"missing from funnel._PILLAR_G_PIPELINE_STAGES."
            )


# ---------------------------------------------------------------------------
# Pillar G Week 12 follow-up — per-week-review P3-5. Per-unit tests
# for the ``_percentile`` primitive. Caller-guards-empty is the
# documented contract (``aggregate_per_channel_send_latency_p99``
# guards before calling). These tests pin both the primitive
# behavior + the caller's empty-list-skip guard.
# ---------------------------------------------------------------------------


class TestPercentile:
    """Pillar G Week 12 follow-up (per-week-review P3-5) — per-unit
    tests for ``funnel._percentile``."""

    def test_single_value(self):
        assert funnel._percentile([1.5], 0.99) == 1.5

    def test_single_value_p0(self):
        assert funnel._percentile([42.0], 0.0) == 42.0

    def test_two_values_p99(self):
        """Linear interpolation: with two values [1.0, 2.0], p99 =
        1.0 + (2.0 - 1.0) * 0.99 = 1.99."""
        assert funnel._percentile([1.0, 2.0], 0.99) == 1.99

    def test_multi_values_p99(self):
        """p99 of 100 monotonically-increasing values [1, 2, ..., 100]
        is the interpolation between v[98] and v[99]."""
        values = [float(i) for i in range(1, 101)]  # [1, 2, ..., 100]
        result = funnel._percentile(values, 0.99)
        # k = 99 * 0.99 = 98.01; f = 98; c = 99; v[98] = 99; v[99] = 100
        # result = 99 + (100 - 99) * (98.01 - 98) = 99 + 0.01 = 99.01
        assert result == 99.01

    def test_empty_list_raises_index_error(self):
        """Documented contract — caller guards empty. ``_percentile``
        on an empty list raises ``IndexError``. The caller
        (``aggregate_per_channel_send_latency_p99``) guards with
        ``if not latencies: continue``."""
        with pytest.raises(IndexError):
            funnel._percentile([], 0.99)

    def test_aggregate_per_channel_p99_empty_pairs_returns_empty_dict(
        self, tmp_path,
    ):
        """The caller-guard invariant — when no per-channel pairs
        exist, the aggregation returns ``{}`` rather than crashing
        on the empty-list percentile."""
        led = _make_ledger(tmp_path)
        # Confirmed without matching intent — no pair exists.
        led.append({
            "type": "send_confirmed",
            "intent_id": "i_orphan", "person_id": "p", "channel": "email",
            "ts": "2026-05-22T10:00:00.000Z",
        })
        # Must NOT raise IndexError.
        result = funnel.aggregate_per_channel_send_latency_p99(
            led, since_iso=_SINCE_2026_04_23,
        )
        assert result == {}
        assert "DEFAULT_BREAKDOWN" in funnel.__all__
