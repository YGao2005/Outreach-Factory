"""Unit tests for the follow-up cadence engine (orchestrator/followup.py).

The engine is the deterministic timing/eligibility brain: a pure read over the
ledger that returns who is due for which follow-up touch now. These tests pin
the eligibility math (business-day delays, max_touches cap, terminator
cancellation, the opt-in gate) and the config parser's refuse-loud validation.

The binding golden-path / no-bypass proofs live in
tests/golden_path/test_l0_spine_liveness.py + tests/test_followup_send_gate.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from orchestrator import followup
from orchestrator.followup import (
    CadenceConfig,
    FollowupStep,
    business_days_between,
    cadence_config_from_dict,
    compute_due_followups,
    derive_followup_steps,
    is_followup_due,
)

UTC = timezone.utc
NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)  # a Wednesday


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _confirmed(pid: str, *, ts: datetime, intent_id: str = "snd_x",
               channel: str = "email") -> dict:
    return {"type": "send_confirmed", "person_id": pid, "intent_id": intent_id,
            "channel": channel, "ts": _iso(ts)}


def _enabled(**kw) -> CadenceConfig:
    """A cadence with enabled=True and the default 3/5 steps unless overridden."""
    base = dict(enabled=True)
    base.update(kw)
    return CadenceConfig(**base)


# ---------------------------------------------------------------------------
# Business-day arithmetic
# ---------------------------------------------------------------------------


def _bd_reference(start: date, end: date) -> int:
    """Brute-force reference: weekdays strictly after `start`, through `end`."""
    if end <= start:
        return 0
    n = 0
    d = start + timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def test_business_days_between_matches_reference_over_a_wide_range():
    anchor = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)  # Thursday
    for back in range(0, 90):
        start = anchor + timedelta(days=back)
        for span in range(0, 40):
            end = start + timedelta(days=span)
            assert business_days_between(start, end) == _bd_reference(
                start.date(), end.date()
            ), f"mismatch start={start.date()} end={end.date()}"


def test_business_days_between_known_cases():
    mon = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)   # Monday
    assert mon.weekday() == 0
    # Mon -> Thu = Tue, Wed, Thu = 3.
    assert business_days_between(mon, datetime(2026, 6, 4, 10, 0, tzinfo=UTC)) == 3
    fri = datetime(2026, 6, 5, 10, 0, tzinfo=UTC)    # Friday
    assert fri.weekday() == 4
    # Fri -> next Wed = Mon, Tue, Wed = 3 (Sat/Sun skipped).
    assert business_days_between(fri, datetime(2026, 6, 10, 10, 0, tzinfo=UTC)) == 3
    # Same day / earlier end -> 0.
    assert business_days_between(mon, mon) == 0
    assert business_days_between(mon, mon - timedelta(days=2)) == 0


# ---------------------------------------------------------------------------
# Opt-in gate
# ---------------------------------------------------------------------------


def test_disabled_returns_empty_even_when_due():
    events = [_confirmed("p1", ts=NOW - timedelta(days=30))]
    assert compute_due_followups(events, CadenceConfig(enabled=False), now=NOW) == []
    # Default cadence is opt-in off.
    assert compute_due_followups(events, now=NOW) == []
    assert is_followup_due(events, "p1", now=NOW) is None


# ---------------------------------------------------------------------------
# Core "due" math
# ---------------------------------------------------------------------------


def test_single_touch_delay_elapsed_is_due_at_step_1():
    last = NOW - timedelta(days=14)  # well past 3 business days
    events = [_confirmed("p1", ts=last, intent_id="snd_cold")]
    actions = compute_due_followups(events, _enabled(), now=NOW)
    assert len(actions) == 1
    a = actions[0]
    assert a.person_id == "p1"
    assert a.next_step == 1          # first follow-up
    assert a.touch_no == 2           # touch 2
    assert a.after_business_days == 3
    assert a.last_touch_intent_id == "snd_cold"
    assert a.register == followup.FOLLOWUP_REGISTER


def test_delay_not_elapsed_is_not_due():
    events = [_confirmed("p1", ts=NOW)]  # 0 business days waited
    assert compute_due_followups(events, _enabled(), now=NOW) == []


def test_boundary_exactly_at_delay_is_due_one_short_is_not():
    last = NOW - timedelta(days=7)
    waited = business_days_between(last, NOW)
    assert waited >= 2  # a week always has >= 2 business days after the start day
    events = [_confirmed("p1", ts=last)]
    due = _enabled(steps=(FollowupStep(waited),))
    not_due = _enabled(steps=(FollowupStep(waited + 1),))
    assert len(compute_due_followups(events, due, now=NOW)) == 1
    assert compute_due_followups(events, not_due, now=NOW) == []


def test_second_follow_up_uses_step_2_delay_and_is_touch_3():
    cold = NOW - timedelta(days=30)
    f1 = NOW - timedelta(days=14)
    events = [
        _confirmed("p1", ts=cold, intent_id="snd_cold"),
        _confirmed("p1", ts=f1, intent_id="snd_f1"),
    ]
    actions = compute_due_followups(events, _enabled(), now=NOW)
    assert len(actions) == 1
    a = actions[0]
    assert a.next_step == 2          # second follow-up
    assert a.touch_no == 3           # touch 3
    assert a.after_business_days == 5
    assert a.last_touch_intent_id == "snd_f1"


def test_max_touches_cap_blocks_a_fourth_touch():
    # cold + 2 follow-ups already confirmed = 3 touches = max_touches.
    events = [
        _confirmed("p1", ts=NOW - timedelta(days=40), intent_id="snd_cold"),
        _confirmed("p1", ts=NOW - timedelta(days=30), intent_id="snd_f1"),
        _confirmed("p1", ts=NOW - timedelta(days=20), intent_id="snd_f2"),
    ]
    assert compute_due_followups(events, _enabled(), now=NOW) == []


def test_more_steps_than_max_touches_still_capped_by_max_touches():
    # 3 steps configured but max_touches=2 -> at most ONE follow-up ever.
    cadence = _enabled(max_touches=2, steps=(FollowupStep(1), FollowupStep(1), FollowupStep(1)))
    two_touches = [
        _confirmed("p1", ts=NOW - timedelta(days=40), intent_id="snd_cold"),
        _confirmed("p1", ts=NOW - timedelta(days=20), intent_id="snd_f1"),
    ]
    assert compute_due_followups(two_touches, cadence, now=NOW) == []


def test_no_confirmed_touch_is_never_due():
    # A send_intent with no send_confirmed is not a touch.
    events = [{"type": "send_intent", "person_id": "p1", "intent_id": "snd_x",
               "channel": "email", "ts": _iso(NOW - timedelta(days=30))}]
    assert compute_due_followups(events, _enabled(), now=NOW) == []


def test_non_email_confirmed_send_is_not_a_touch():
    events = [_confirmed("p1", ts=NOW - timedelta(days=30), channel="linkedin")]
    assert compute_due_followups(events, _enabled(), now=NOW) == []


# ---------------------------------------------------------------------------
# Terminator cancellation (re-derived from the ledger every run)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("term_type", ["reply_received", "suppression_added",
                                       "bounce_detected", "followup_stopped"])
def test_terminator_after_last_touch_cancels(term_type):
    last = NOW - timedelta(days=14)
    events = [
        _confirmed("p1", ts=last),
        {"type": term_type, "person_id": "p1", "ts": _iso(last + timedelta(days=1))},
    ]
    assert compute_due_followups(events, _enabled(), now=NOW) == []
    assert is_followup_due(events, "p1", _enabled(), now=NOW) is None


def test_terminator_before_last_touch_does_not_cancel():
    # A reply that predates the last touch belongs to a prior round; it must not
    # cancel the current sequence's next follow-up.
    early = NOW - timedelta(days=40)
    last = NOW - timedelta(days=14)
    events = [
        {"type": "reply_received", "person_id": "p1", "ts": _iso(early)},
        _confirmed("p1", ts=last),
    ]
    assert len(compute_due_followups(events, _enabled(), now=NOW)) == 1


def test_manual_stop_cancels_even_when_not_in_stop_on():
    last = NOW - timedelta(days=14)
    events = [
        _confirmed("p1", ts=last),
        {"type": "followup_stopped", "person_id": "p1",
         "ts": _iso(last + timedelta(days=1))},
    ]
    cadence = _enabled(stop_on=frozenset())  # empty stop_on
    assert compute_due_followups(events, cadence, now=NOW) == []


def test_stop_on_subset_lets_excluded_signal_through():
    # An operator who removes 'bounce' from stop_on: a bounce no longer cancels.
    last = NOW - timedelta(days=14)
    events = [
        _confirmed("p1", ts=last),
        {"type": "bounce_detected", "person_id": "p1",
         "ts": _iso(last + timedelta(days=1))},
    ]
    cadence = _enabled(stop_on=frozenset({"reply", "unsubscribe"}))
    assert len(compute_due_followups(events, cadence, now=NOW)) == 1


# ---------------------------------------------------------------------------
# Multiple persons + ordering
# ---------------------------------------------------------------------------


def test_multiple_persons_sorted_by_last_touch_then_id():
    events = [
        _confirmed("p_late", ts=NOW - timedelta(days=10), intent_id="a"),
        _confirmed("p_early", ts=NOW - timedelta(days=20), intent_id="b"),
    ]
    actions = compute_due_followups(events, _enabled(), now=NOW)
    assert [a.person_id for a in actions] == ["p_early", "p_late"]


# ---------------------------------------------------------------------------
# derive_followup_steps (vault denormalization source)
# ---------------------------------------------------------------------------


def test_derive_followup_steps():
    events = [
        _confirmed("cold_only", ts=NOW - timedelta(days=5)),
        _confirmed("one_followup", ts=NOW - timedelta(days=10), intent_id="c"),
        _confirmed("one_followup", ts=NOW - timedelta(days=5), intent_id="d"),
        {"type": "send_intent", "person_id": "no_touch", "intent_id": "e",
         "channel": "email", "ts": _iso(NOW)},
    ]
    steps = derive_followup_steps(events)
    assert steps == {"cold_only": 0, "one_followup": 1}
    assert "no_touch" not in steps  # no confirmed touch -> absent


# ---------------------------------------------------------------------------
# is_followup_due (send-gate authorization surface)
# ---------------------------------------------------------------------------


def test_is_followup_due_returns_action_for_due_person():
    events = [_confirmed("p1", ts=NOW - timedelta(days=14))]
    action = is_followup_due(events, "p1", _enabled(), now=NOW)
    assert action is not None and action.next_step == 1


def test_is_followup_due_none_for_unknown_person():
    events = [_confirmed("p1", ts=NOW - timedelta(days=14))]
    assert is_followup_due(events, "ghost", _enabled(), now=NOW) is None


# ---------------------------------------------------------------------------
# Config parser
# ---------------------------------------------------------------------------


def test_cadence_config_from_dict_none_is_default_off():
    c = cadence_config_from_dict(None)
    assert c.enabled is False
    assert c.max_touches == 3
    assert [s.after_business_days for s in c.steps] == [3, 5]
    assert c.auto_send is False


def test_cadence_config_from_dict_full_block():
    c = cadence_config_from_dict({
        "enabled": True,
        "max_touches": 3,
        "steps": [{"after_business_days": 3}, {"after_business_days": 5}],
        "stop_on": ["reply", "unsubscribe", "bounce"],
        "auto_send": False,
    })
    assert c.enabled is True
    assert c.max_touches == 3
    assert [s.after_business_days for s in c.steps] == [3, 5]
    assert c.stop_on == frozenset({"reply", "unsubscribe", "bounce"})


@pytest.mark.parametrize("block", [
    [],                                              # not a mapping
    {"max_touches": "three"},                        # bad int
    {"max_touches": 0},                              # < 1
    {"steps": "nope"},                               # steps not a list
    {"steps": [{"after_business_days": 0}]},         # delay < 1
    {"steps": [{"days": 3}]},                        # missing key
    {"steps": [{"after_business_days": "soon"}]},    # delay not int
    {"stop_on": ["reply", "snooze"]},                # unknown token
])
def test_cadence_config_from_dict_refuses_malformed(block):
    with pytest.raises(ValueError):
        cadence_config_from_dict(block)


def test_stop_event_types_includes_manual_stop():
    c = cadence_config_from_dict({"stop_on": ["reply"]})
    types = c.stop_event_types()
    assert "reply_received" in types
    assert "followup_stopped" in types       # always on
    assert "bounce_detected" not in types     # not in stop_on
