"""Pillar D Week 4-5 — conversation state machine unit tests.

Per ADR-0025 D98 + ADR-0028 D118-D119. Covers:

* Per-thread state-machine transitions (replied → classified →
  unsubscribed | active | dormant).
* Per-thread (not per-person) — a Person with multiple threads has
  multiple state machines.
* Per-Person aggregation (``derived_conversation_status``) — highest-
  priority state across threads wins.
* Pass N idempotence — re-runs emit no duplicate transitions.
* Event-shape contract per ADR-0025 D98.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import conversation_state as cs
import ledger as _ledger


def _ledger_with(events, ledger_dir):
    led = _ledger.Ledger(ledger_dir)
    for e in events:
        led.append(e)
    return led


def _email_reply(*, person_id, mid, thread_id, ts):
    return {
        "type": "reply_received",
        "person_id": person_id,
        "channel": "email",
        "gmail_message_id": mid,
        "gmail_thread_id": thread_id,
        "from": "someone@x.test",
        "subject": "Re: outreach",
        "body": "reply body",
        "ts": ts,
    }


def _classified(*, person_id, channel, reply_mid, category, ts,
                method="rule", confidence=1.0, gmail_thread_id=None):
    payload = {
        "type": "reply_classified",
        "person_id": person_id,
        "channel": channel,
        "reply_message_id": reply_mid,
        "category": category,
        "classification_method": method,
        "confidence": confidence,
        "matched_pattern": (
            "<rule>" if method == "rule" else None
        ),
        "ts": ts,
    }
    if gmail_thread_id:
        payload["gmail_thread_id"] = gmail_thread_id
    return payload


def _suppression_added(*, person_id, channel, reply_mid, value, ts):
    return {
        "type": "suppression_added",
        "person_id": person_id,
        "channel": channel,
        "suppressed_dimension": (
            "email" if channel == "email" else "identity_key"
        ),
        "suppressed_value": value,
        "source_reply_classified_event": {
            "reply_message_id": reply_mid,
            "channel": channel,
            "ts": ts,
        },
        "yaml_file": "/tmp/auto-unsubscribe.yml",
        "_emitted_by": "auto_unsubscribe_handler",
        "ts": ts,
    }


class TestComputeThreadStates:
    """ADR-0028 D119 — per-thread state computation from ledger."""

    def test_first_reply_yields_replied_state(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_1", mid="g1", thread_id="t1",
                    ts="2026-05-22T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk = cs.ThreadKey(person_id="p_1", channel="email", thread_key="t1")
        assert tk in states
        assert states[tk].state == "replied"

    def test_classified_event_progresses_state(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_1", mid="g1", thread_id="t1",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_1", channel="email", reply_mid="g1",
                    category="uncategorized",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t1",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk = cs.ThreadKey(person_id="p_1", channel="email", thread_key="t1")
        assert states[tk].state == "classified"

    def test_interest_classification_yields_active(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_2", mid="g2", thread_id="t2",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_2", channel="email", reply_mid="g2",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t2",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk = cs.ThreadKey(person_id="p_2", channel="email", thread_key="t2")
        assert states[tk].state == "active"

    def test_rejection_classification_yields_dormant(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_3", mid="g3", thread_id="t3",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_3", channel="email", reply_mid="g3",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t3",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk = cs.ThreadKey(person_id="p_3", channel="email", thread_key="t3")
        assert states[tk].state == "dormant"

    def test_ooo_classification_yields_dormant(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_4", mid="g4", thread_id="t4",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_4", channel="email", reply_mid="g4",
                    category="ooo",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t4",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk = cs.ThreadKey(person_id="p_4", channel="email", thread_key="t4")
        assert states[tk].state == "dormant"

    def test_suppression_added_yields_unsubscribed(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_5", mid="g5", thread_id="t5",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_5", channel="email", reply_mid="g5",
                    category="unsubscribe",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t5",
                ),
                _suppression_added(
                    person_id="p_5", channel="email", reply_mid="g5",
                    value="p_5@x.test",
                    ts="2026-05-22T10:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk = cs.ThreadKey(person_id="p_5", channel="email", thread_key="t5")
        assert states[tk].state == "unsubscribed"

    def test_priority_unsubscribed_beats_active(self, tmp_path):
        """ADR-0028 D119 — when multiple transition drivers fire, the
        higher-priority state wins. unsubscribed > active."""
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_6", mid="g6", thread_id="t6",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_6", channel="email", reply_mid="g6",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t6",
                ),
                _email_reply(
                    person_id="p_6", mid="g7", thread_id="t6",
                    ts="2026-05-22T11:00:00.000Z",
                ),
                _classified(
                    person_id="p_6", channel="email", reply_mid="g7",
                    category="unsubscribe",
                    ts="2026-05-22T11:00:01.000Z",
                    gmail_thread_id="t6",
                ),
                _suppression_added(
                    person_id="p_6", channel="email", reply_mid="g7",
                    value="p_6@x.test",
                    ts="2026-05-22T11:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk = cs.ThreadKey(person_id="p_6", channel="email", thread_key="t6")
        # Interest THEN unsubscribe on the same thread → unsubscribed wins.
        assert states[tk].state == "unsubscribed"

    def test_per_thread_not_per_person(self, tmp_path):
        """ADR-0025 D98 — per-thread state, NOT per-person. A Person
        with two threads has TWO state machines."""
        led = _ledger_with(
            [
                # Thread 1 — interest.
                _email_reply(
                    person_id="p_multi", mid="g_a", thread_id="t_a",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_multi", channel="email", reply_mid="g_a",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_a",
                ),
                # Thread 2 — rejection.
                _email_reply(
                    person_id="p_multi", mid="g_b", thread_id="t_b",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_multi", channel="email", reply_mid="g_b",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_b",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        tk_a = cs.ThreadKey(person_id="p_multi", channel="email", thread_key="t_a")
        tk_b = cs.ThreadKey(person_id="p_multi", channel="email", thread_key="t_b")
        assert states[tk_a].state == "active"
        assert states[tk_b].state == "dormant"

    def test_cross_channel_threads_distinct(self, tmp_path):
        """Email thread + LinkedIn DM thread → two separate state
        machines, even for the same person."""
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_cc", mid="g_e", thread_id="t_e",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                {
                    "type": "li_dm_reply_received",
                    "person_id": "p_cc",
                    "channel": "linkedin",
                    "reply_message_id": "li_msg",
                    "linkedin_thread_id": "li_t",
                    "snippet": "hi",
                    "ts": "2026-05-22T10:00:00.000Z",
                },
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        assert len(states) == 2
        tk_e = cs.ThreadKey(
            person_id="p_cc", channel="email", thread_key="t_e",
        )
        tk_li = cs.ThreadKey(
            person_id="p_cc", channel="linkedin", thread_key="li_t",
        )
        assert states[tk_e].state == "replied"
        assert states[tk_li].state == "replied"


class TestDerivedConversationStatus:
    """ADR-0028 D119 — per-Person aggregation."""

    def test_max_priority_wins(self, tmp_path):
        led = _ledger_with(
            [
                # Thread 1 — interest (active).
                _email_reply(
                    person_id="p_agg", mid="g_a", thread_id="t_a",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_agg", channel="email", reply_mid="g_a",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_a",
                ),
                # Thread 2 — rejection (dormant).
                _email_reply(
                    person_id="p_agg", mid="g_b", thread_id="t_b",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_agg", channel="email", reply_mid="g_b",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_b",
                ),
            ],
            tmp_path / "ledger",
        )
        # active > dormant per STATE_PRIORITY.
        status = cs.derived_conversation_status(led, "p_agg")
        assert status == "active"

    def test_unsubscribed_dominates(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_us", mid="g_a", thread_id="t_a",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_us", channel="email", reply_mid="g_a",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_a",
                ),
                _email_reply(
                    person_id="p_us", mid="g_b", thread_id="t_b",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_us", channel="email", reply_mid="g_b",
                    category="unsubscribe",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_b",
                ),
                _suppression_added(
                    person_id="p_us", channel="email", reply_mid="g_b",
                    value="p_us@x.test",
                    ts="2026-05-22T10:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        # unsubscribed > active.
        assert cs.derived_conversation_status(led, "p_us") == "unsubscribed"

    def test_no_conversation_returns_none(self, tmp_path):
        led = _ledger_with([], tmp_path / "ledger")
        assert cs.derived_conversation_status(led, "p_nothing") is None

    def test_precomputed_thread_states_accepted(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_pre", mid="g_a", thread_id="t_a",
                    ts="2026-05-22T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)
        # Passing precomputed states should give same result.
        assert (
            cs.derived_conversation_status(led, "p_pre")
            == cs.derived_conversation_status(led, "p_pre", thread_states=states)
            == "replied"
        )


class TestRunPass:
    """ADR-0028 D118 — Pass N emit + idempotence."""

    def test_apply_emits_state_change_events(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_n1", mid="g_n1", thread_id="t_n1",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_n1", channel="email", reply_mid="g_n1",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_n1",
                ),
            ],
            tmp_path / "ledger",
        )
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)
        result = cs.run_conversation_state_pass(
            led=led, since=since, apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        event = result.synthesized[0]
        assert event["type"] == "conversation_state_changed"
        assert event["person_id"] == "p_n1"
        assert event["channel"] == "email"
        assert event["thread_key"] == "t_n1"
        assert event["to_state"] == "active"

    def test_idempotent_under_rerun(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_n2", mid="g_n2", thread_id="t_n2",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_n2", channel="email", reply_mid="g_n2",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_n2",
                ),
            ],
            tmp_path / "ledger",
        )
        since = datetime(2026, 5, 1, tzinfo=timezone.utc)
        first = cs.run_conversation_state_pass(
            led=led, since=since, apply=True,
        )
        assert len(first.synthesized) == 1

        second = cs.run_conversation_state_pass(
            led=led, since=since, apply=True,
        )
        # Re-running emits NO new events — the (pid, ch, tk, to_state)
        # pair is already in the ledger per ADR-0028 D119 idempotence.
        assert second.synthesized == []

    def test_dry_run_does_not_append(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_n3", mid="g_n3", thread_id="t_n3",
                    ts="2026-05-22T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        result = cs.run_conversation_state_pass(
            led=led, since=datetime(2026, 5, 1, tzinfo=timezone.utc),
            apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0].get("_dry_run") is True
        # No conversation_state_changed in ledger.
        assert not [
            e for e in led.all_events()
            if e.get("type") == "conversation_state_changed"
        ]


class TestEventShape:
    """ADR-0025 D98 event-shape contract."""

    def test_event_carries_all_required_fields(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_e", mid="g_e", thread_id="t_e",
                    ts="2026-05-22T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        result = cs.run_conversation_state_pass(
            led=led, since=datetime(2026, 5, 1, tzinfo=timezone.utc),
            apply=True,
        )
        ev = result.synthesized[0]
        for required in (
            "type", "person_id", "channel", "thread_key",
            "from_state", "to_state", "trigger_event_id", "_emitted_by",
        ):
            assert required in ev, f"event missing required field {required!r}"
        assert ev["_emitted_by"] == "conversation_state_machine"
        assert isinstance(ev["trigger_event_id"], dict)
        assert ev["trigger_event_id"]["reply_message_id"] == "g_e"
        assert ev["trigger_event_id"]["channel"] == "email"

    def test_channel_field_invariant(self, tmp_path):
        """ADR-0014 D33 extended by ADR-0025 D96 — every event MUST
        carry a top-level ``channel:`` field."""
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_ch", mid="g_ch", thread_id="t_ch",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                {
                    "type": "li_dm_reply_received",
                    "person_id": "p_ch", "channel": "linkedin",
                    "reply_message_id": "li_m", "linkedin_thread_id": "li_t",
                    "snippet": "hi", "ts": "2026-05-22T10:00:00.000Z",
                },
            ],
            tmp_path / "ledger",
        )
        result = cs.run_conversation_state_pass(
            led=led, since=datetime(2026, 5, 1, tzinfo=timezone.utc),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev.get("channel") in {"email", "linkedin", "twitter", "calendar"}, (
                f"channel-on-every-event invariant VIOLATED: event "
                f"{ev!r} missing or invalid channel field."
            )
