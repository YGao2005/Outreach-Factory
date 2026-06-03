"""Offline tests for the health-gated warming-ramp policy (orchestrator/warming.py).

Core tier (NOT in conftest._OPERATIONS_TEST_FILES): warming is an onboarding +
guardrail job. Every test is fully offline. Event objects are fabricated as
plain dicts matching the ledger read shape (``e.get("type")``, ``e["ts"]``) the
status command reads, so no Ledger / disk / network is touched.

Covered:
  * the per-week schedule (week 1 small, ramps to the cap, steady after)
  * the cap clamp (effective_ceiling <= daily_send_cap always)
  * start_date inference from the earliest send_confirmed in the ledger
  * the health-gate HOLD on a high trailing bounce rate (no escalation)
  * the boundary just below vs just above the bounce threshold
  * an empty ledger yields the week-1 ceiling with health ok
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator import warming
from orchestrator.warming import RampDecision, compute_ramp


# --------------------------------------------------------------------------
# Helpers - fabricate ledger-shaped event dicts.
# --------------------------------------------------------------------------

NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    """Ledger ts shape: ISO-8601 UTC, millisecond precision, trailing 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _send(ts: datetime, *, channel: str = "email") -> dict:
    """A send_confirmed event the way the status command reads it."""
    return {"v": 1, "type": "send_confirmed", "channel": channel, "ts": _iso(ts)}


def _bounce(ts: datetime) -> dict:
    return {"v": 1, "type": "bounce_detected", "ts": _iso(ts)}


def _sends(n: int, *, at: datetime) -> list[dict]:
    """``n`` send_confirmed events at distinct sub-second offsets around ``at``."""
    return [_send(at + timedelta(milliseconds=i)) for i in range(n)]


# --------------------------------------------------------------------------
# Per-week schedule
# --------------------------------------------------------------------------


def test_week1_is_small_and_below_cap():
    d = compute_ramp(now=NOW, start_date=NOW, daily_send_cap=50, events=[])
    assert d.week_index == 1
    assert d.health == "ok"
    assert not d.held
    # Week 1 default is 20% of 50 = 10, well under the cap.
    assert d.base_ceiling == 10
    assert d.effective_ceiling == 10
    assert d.effective_ceiling < 50


def test_schedule_ramps_up_week_over_week():
    cap = 50
    ceilings = []
    for week in range(0, 7):
        now = NOW + timedelta(days=7 * week)
        d = compute_ramp(now=now, start_date=NOW, daily_send_cap=cap, events=[])
        assert d.week_index == week + 1
        ceilings.append(d.base_ceiling)
    # Default fractions (.2 .4 .6 .8 1.0) of 50 -> 10 20 30 40 50, then steady.
    assert ceilings == [10, 20, 30, 40, 50, 50, 50]


def test_steadies_at_cap_after_schedule_ends():
    far = NOW + timedelta(days=7 * 20)  # week 21
    d = compute_ramp(now=far, start_date=NOW, daily_send_cap=50, events=[])
    assert d.base_ceiling == 50
    assert d.effective_ceiling == 50


def test_week1_floor_applies_for_a_small_cap():
    # 20% of 8 = 1.6 -> rounds to 2, but the week-1 floor is 5.
    d = compute_ramp(now=NOW, start_date=NOW, daily_send_cap=8, events=[])
    assert d.week_index == 1
    assert d.base_ceiling == 5
    assert d.effective_ceiling == 5


def test_days_before_start_date_report_week_1():
    before = NOW - timedelta(days=3)
    d = compute_ramp(now=before, start_date=NOW, daily_send_cap=50, events=[])
    assert d.week_index == 1


# --------------------------------------------------------------------------
# Cap clamp
# --------------------------------------------------------------------------


def test_effective_ceiling_never_exceeds_cap_even_with_absolute_schedule():
    # Absolute steps that blow past the cap must clamp to the cap.
    d = compute_ramp(
        now=NOW + timedelta(days=7 * 4), start_date=NOW, daily_send_cap=25,
        events=[], schedule=[10, 100, 1000, 5000],
    )
    assert d.base_ceiling <= 25
    assert d.effective_ceiling <= 25


def test_cap_floor_of_one():
    # A pathological cap of 0 still yields a usable >=1 ceiling.
    d = compute_ramp(now=NOW, start_date=NOW, daily_send_cap=0, events=[])
    assert d.effective_ceiling >= 1


def test_weeks_to_full_int_schedule_ramps_to_cap():
    cap = 30
    last = compute_ramp(
        now=NOW + timedelta(days=7 * 3), start_date=NOW, daily_send_cap=cap,
        events=[], schedule=4,  # weeks_to_full = 4
    )
    assert last.week_index == 4
    assert last.base_ceiling == cap
    first = compute_ramp(
        now=NOW, start_date=NOW, daily_send_cap=cap, events=[], schedule=4,
    )
    assert first.base_ceiling <= cap
    assert first.base_ceiling < last.base_ceiling


# --------------------------------------------------------------------------
# start_date inference
# --------------------------------------------------------------------------


def test_start_date_inferred_from_earliest_send_confirmed():
    # Earliest confirmed send is 15 days ago -> we should be in week 3.
    first_send = NOW - timedelta(days=15)
    events = [
        _send(first_send),
        _send(NOW - timedelta(days=2)),
        _send(NOW - timedelta(days=1)),
    ]
    d = compute_ramp(now=NOW, start_date=None, daily_send_cap=50, events=events)
    assert d.week_index == 3
    assert any("inferred" in r for r in d.reasons)


def test_explicit_start_date_overrides_inference():
    # Even though the earliest send is 15 days ago, an explicit start_date of
    # 1 day ago pins us to week 1.
    events = [_send(NOW - timedelta(days=15))]
    d = compute_ramp(
        now=NOW, start_date=NOW - timedelta(days=1),
        daily_send_cap=50, events=events,
    )
    assert d.week_index == 1


def test_no_sends_yet_is_week_1_health_ok():
    d = compute_ramp(now=NOW, start_date=None, daily_send_cap=50, events=[])
    assert d.week_index == 1
    assert d.health == "ok"
    assert not d.held
    assert d.bounce_rate == 0.0
    assert d.sends_window == 0
    assert any("no sends yet" in r for r in d.reasons)


# --------------------------------------------------------------------------
# Empty ledger
# --------------------------------------------------------------------------


def test_empty_ledger_yields_week1_ceiling_health_ok():
    d = compute_ramp(now=NOW, start_date=None, daily_send_cap=40, events=[])
    assert isinstance(d, RampDecision)
    assert d.week_index == 1
    assert d.health == "ok"
    assert not d.held
    # 20% of 40 = 8.
    assert d.effective_ceiling == 8


# --------------------------------------------------------------------------
# Health gate - HOLD on high bounce rate
# --------------------------------------------------------------------------


def test_high_bounce_rate_holds_the_ramp():
    # We are in week 4 (start 22 days ago); base ceiling would be 40/50.
    start = NOW - timedelta(days=22)
    recent = NOW - timedelta(days=1)
    # 10 confirmed sends, 3 bounces -> 30% bounce rate, way over the 5% gate.
    events = [_send(start)] + _sends(10, at=recent) + [
        _bounce(recent + timedelta(hours=1)),
        _bounce(recent + timedelta(hours=2)),
        _bounce(recent + timedelta(hours=3)),
    ]
    d = compute_ramp(now=NOW, start_date=start, daily_send_cap=50, events=events)
    assert d.week_index == 4
    assert d.health == "degraded"
    assert d.held is True
    # The ramp must NOT escalate to this week's higher ceiling.
    assert d.effective_ceiling < d.base_ceiling
    # It holds at the prior (week 3) ceiling = 30, not week 4's 40.
    assert d.effective_ceiling == 30
    assert any(r.startswith("HELD") for r in d.reasons)


def test_held_ceiling_still_clamped_to_cap():
    start = NOW - timedelta(days=40)  # steady-state week
    recent = NOW - timedelta(days=1)
    events = [_send(start)] + _sends(4, at=recent) + [_bounce(recent)]
    d = compute_ramp(now=NOW, start_date=start, daily_send_cap=25, events=events)
    assert d.held is True
    assert d.effective_ceiling <= 25


def test_degraded_health_never_escalates_above_floor():
    # Property: when degraded, effective_ceiling <= the prior week's ceiling.
    start = NOW - timedelta(days=22)  # week 4
    recent = NOW - timedelta(days=1)
    events = [_send(start)] + _sends(5, at=recent) + [_bounce(recent), _bounce(recent)]
    d = compute_ramp(now=NOW, start_date=start, daily_send_cap=50, events=events)
    floor = warming._ceiling_for_week(d.week_index - 1, warming.normalize_schedule(None, daily_send_cap=50))
    assert d.effective_ceiling <= floor


# --------------------------------------------------------------------------
# Threshold boundary - just below vs just above
# --------------------------------------------------------------------------


def test_bounce_rate_just_below_threshold_is_ok():
    # 20 sends, 1 bounce -> 5.0% exactly == threshold; NOT over -> ok.
    recent = NOW - timedelta(days=1)
    events = _sends(20, at=recent) + [_bounce(recent)]
    d = compute_ramp(
        now=NOW, start_date=NOW - timedelta(days=22),
        daily_send_cap=50, events=events,
    )
    assert pytest.approx(d.bounce_rate, abs=1e-9) == 0.05
    assert d.health == "ok"
    assert not d.held
    assert d.effective_ceiling == d.base_ceiling


def test_bounce_rate_just_above_threshold_holds():
    # 16 sends, 1 bounce -> 6.25% > 5% gate -> degraded + held.
    recent = NOW - timedelta(days=1)
    events = _sends(16, at=recent) + [_bounce(recent)]
    d = compute_ramp(
        now=NOW, start_date=NOW - timedelta(days=22),
        daily_send_cap=50, events=events,
    )
    assert d.bounce_rate > 0.05
    assert d.health == "degraded"
    assert d.held is True


def test_bounces_outside_window_do_not_degrade_health():
    # The bounce is 10 days ago, outside the default 7-day window.
    recent = NOW - timedelta(days=1)
    old = NOW - timedelta(days=10)
    events = _sends(10, at=recent) + [_bounce(old)]
    d = compute_ramp(
        now=NOW, start_date=NOW - timedelta(days=22),
        daily_send_cap=50, events=events,
    )
    assert d.bounce_rate == 0.0
    assert d.health == "ok"
    assert not d.held


def test_custom_threshold_is_respected():
    # 20 sends, 2 bounces -> 10%. Under a 15% gate -> ok.
    recent = NOW - timedelta(days=1)
    events = _sends(20, at=recent) + [_bounce(recent), _bounce(recent + timedelta(minutes=1))]
    d = compute_ramp(
        now=NOW, start_date=NOW - timedelta(days=22),
        daily_send_cap=50, events=events, bounce_threshold=0.15,
    )
    assert d.health == "ok"
    assert not d.held


# --------------------------------------------------------------------------
# RampDecision shape + status_line
# --------------------------------------------------------------------------


def test_ramp_decision_is_frozen_dataclass():
    d = compute_ramp(now=NOW, start_date=NOW, daily_send_cap=50, events=[])
    with pytest.raises(Exception):
        d.effective_ceiling = 999  # type: ignore[misc]


def test_status_line_ok_and_held_render():
    # The factory bans em/en dashes everywhere, including status output.
    _EM_DASH = chr(0x2014)
    _EN_DASH = chr(0x2013)

    ok = compute_ramp(now=NOW, start_date=NOW, daily_send_cap=50, events=[])
    line = warming.status_line(ok, total=warming.total_weeks(daily_send_cap=50))
    assert "warming ceiling" in line
    assert "health ok" in line
    assert _EM_DASH not in line and _EN_DASH not in line

    start = NOW - timedelta(days=22)
    recent = NOW - timedelta(days=1)
    events = [_send(start)] + _sends(10, at=recent) + [_bounce(recent), _bounce(recent)]
    held = compute_ramp(now=NOW, start_date=start, daily_send_cap=50, events=events)
    held_line = warming.status_line(held, total=warming.total_weeks(daily_send_cap=50))
    assert "HELD" in held_line
    assert _EM_DASH not in held_line and _EN_DASH not in held_line


def test_naive_now_is_treated_as_utc():
    naive = datetime(2026, 6, 2, 12, 0, 0)  # no tzinfo
    d = compute_ramp(now=naive, start_date=naive, daily_send_cap=50, events=[])
    assert d.week_index == 1
    assert d.health == "ok"
