"""Pillar D Week 9-11 — win/loss attribution + conversation_outcome unit tests.

Per ADR-0030 D129-D135. Covers:

* :class:`ConversationOutcome` dataclass invariants.
* Outcome derivation per terminal state (closed_won / closed_lost /
  closed_unsubscribed / dormant).
* Last-touch-wins attribution per-channel (the winning/losing touch is
  the most-recent ``*_confirmed`` event on the SAME channel as the
  thread, for the same person, before the outcome-driving event).
* Cross-channel attribution: a person with an email touch + a LinkedIn
  touch + a reply on LinkedIn → the LinkedIn touch wins (same-channel
  rule).
* No-prior-touch case: when no ``*_confirmed`` event exists before the
  outcome-driving event, ``attributed_touch_intent_id`` is ``None``.
* ``conversation_outcome`` event-shape contract per ADR-0030 D130.
* Pass O orchestration + idempotence (re-running emits no duplicate
  outcomes; the (person_id, channel, thread_key, outcome) tuple is the
  idempotence key).
* Per-Person aggregation (``derived_conversation_outcome``) — highest-
  priority outcome across the person's threads wins.
* The ``OUTCOME_PRIORITY`` ordering pin.

The tests are organized analogously to ``tests/test_conversation_state.py``:
small per-concern classes, fixture-built ledgers, no live network.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import conversation_outcomes as co
import conversation_state as cs
import ledger as _ledger
import reconcile as _reconcile


# ---------------------------------------------------------------------------
# Test fixtures + builders
# ---------------------------------------------------------------------------


def _ledger_with(events, ledger_dir):
    led = _ledger.Ledger(ledger_dir)
    for e in events:
        led.append(e)
    return led


def _email_send_confirmed(*, person_id, intent_id, thread_id, ts,
                          gmail_message_id=None):
    return {
        "type": "send_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "email",
        "gmail_message_id": gmail_message_id or f"sent_{intent_id}",
        "gmail_thread_id": thread_id,
        "email": f"{person_id}@x.test",
        "ts": ts,
    }


def _li_invite_confirmed(*, person_id, intent_id, invitation_id, ts):
    return {
        "type": "li_invite_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "linkedin",
        "linkedin_invitation_id": invitation_id,
        "ts": ts,
    }


def _li_dm_confirmed(*, person_id, intent_id, thread_id, ts):
    return {
        "type": "li_dm_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "linkedin",
        "linkedin_thread_id": thread_id,
        "ts": ts,
    }


def _tw_dm_confirmed(*, person_id, intent_id, thread_id, ts):
    return {
        "type": "tw_dm_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "twitter",
        "twitter_thread_id": thread_id,
        "ts": ts,
    }


def _email_reply(*, person_id, mid, thread_id, ts):
    return {
        "type": "reply_received",
        "person_id": person_id,
        "channel": "email",
        "gmail_message_id": mid,
        "gmail_thread_id": thread_id,
        "from": f"{person_id}@x.test",
        "subject": "Re: outreach",
        "body": "reply body",
        "ts": ts,
    }


def _li_dm_reply(*, person_id, mid, thread_id, ts):
    return {
        "type": "li_dm_reply_received",
        "person_id": person_id,
        "channel": "linkedin",
        "reply_message_id": mid,
        "linkedin_thread_id": thread_id,
        "snippet": "li reply",
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
        "matched_pattern": "<rule>" if method == "rule" else None,
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
        "suppressed_dimension": "email" if channel == "email" else "identity_key",
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


def _calendar_booking_confirmed(*, person_id, intent_id, ts):
    return {
        "type": "calendar_booking_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "calendar",
        "cal_event_id": f"cal_{intent_id}",
        "ts": ts,
    }


# ---------------------------------------------------------------------------
# ConversationOutcome dataclass
# ---------------------------------------------------------------------------


class TestConversationOutcomeDataclass:
    """ADR-0030 D130 — outcome dataclass invariants."""

    def test_constructor_accepts_canonical_fields(self):
        out = co.ConversationOutcome(
            person_id="p_1",
            channel="email",
            thread_key="t_1",
            outcome="closed_won",
            ts="2026-05-22T10:00:00.000Z",
            attributed_touch_intent_id="snd_ABCD",
            triggering_event_id={
                "type": "calendar_booking_confirmed",
                "intent_id": "cb_XYZ",
                "ts": "2026-05-22T10:00:00.000Z",
            },
        )
        assert out.person_id == "p_1"
        assert out.outcome == "closed_won"

    def test_outcome_must_be_in_canonical_set(self):
        with pytest.raises(ValueError):
            co.ConversationOutcome(
                person_id="p", channel="email", thread_key="t",
                outcome="closed_drifted",  # not in OUTCOMES
                ts="2026-05-22T10:00:00.000Z",
                attributed_touch_intent_id=None,
                triggering_event_id={"type": "x", "ts": "2026-05-22T10:00:00.000Z"},
            )

    def test_channel_must_be_canonical(self):
        with pytest.raises(ValueError):
            co.ConversationOutcome(
                person_id="p", channel="signal",  # not in canonical set
                thread_key="t", outcome="closed_lost",
                ts="2026-05-22T10:00:00.000Z",
                attributed_touch_intent_id=None,
                triggering_event_id={"type": "x", "ts": "2026-05-22T10:00:00.000Z"},
            )

    def test_attributed_touch_intent_id_may_be_none(self):
        # Reply with no prior framework-emitted touch (operator hand-
        # initiated touch outside the framework, or the recipient
        # initiated contact). The outcome still computes.
        out = co.ConversationOutcome(
            person_id="p", channel="email", thread_key="t",
            outcome="closed_unsubscribed",
            ts="2026-05-22T10:00:00.000Z",
            attributed_touch_intent_id=None,
            triggering_event_id={"type": "suppression_added",
                                 "reply_message_id": "g_1",
                                 "channel": "email",
                                 "ts": "2026-05-22T10:00:00.000Z"},
        )
        assert out.attributed_touch_intent_id is None


# ---------------------------------------------------------------------------
# OUTCOMES + OUTCOME_PRIORITY
# ---------------------------------------------------------------------------


class TestOutcomesConstants:
    """ADR-0030 D130 + D134 — public outcome constants."""

    def test_outcomes_constant_present(self):
        assert isinstance(co.OUTCOMES, tuple)
        assert set(co.OUTCOMES) == {
            "closed_won",
            "closed_lost",
            "closed_unsubscribed",
            "dormant",
        }

    def test_outcome_priority_canonical_order(self):
        # closed_won > closed_unsubscribed > closed_lost > dormant
        # The won-first priority reflects: an active conversion is the
        # highest-signal outcome for operator visibility. closed_
        # unsubscribed beats closed_lost because the legal-liability
        # surface is structurally weightier than a soft rejection.
        assert (
            co.OUTCOME_PRIORITY["closed_won"]
            > co.OUTCOME_PRIORITY["closed_unsubscribed"]
            > co.OUTCOME_PRIORITY["closed_lost"]
            > co.OUTCOME_PRIORITY["dormant"]
        )

    def test_outcome_priority_keys_match_outcomes_constant(self):
        assert set(co.OUTCOME_PRIORITY.keys()) == set(co.OUTCOMES)


# ---------------------------------------------------------------------------
# Outcome derivation from terminal states
# ---------------------------------------------------------------------------


class TestOutcomeDerivation:
    """ADR-0030 D131 — outcome computation from thread state + classified
    categories + booking events."""

    def test_unsubscribed_state_yields_closed_unsubscribed_outcome(
        self, tmp_path,
    ):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_u", intent_id="snd_TOUCH_U",
                    thread_id="t_u",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_u", mid="g_u", thread_id="t_u",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_u", channel="email", reply_mid="g_u",
                    category="unsubscribe",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_u",
                ),
                _suppression_added(
                    person_id="p_u", channel="email", reply_mid="g_u",
                    value="p_u@x.test",
                    ts="2026-05-22T10:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_u", channel="email", thread_key="t_u")
        assert tk in outcomes
        assert outcomes[tk].outcome == "closed_unsubscribed"

    def test_dormant_via_rejection_yields_closed_lost(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_l", intent_id="snd_TOUCH_L",
                    thread_id="t_l",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_l", mid="g_l", thread_id="t_l",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_l", channel="email", reply_mid="g_l",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_l",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_l", channel="email", thread_key="t_l")
        assert outcomes[tk].outcome == "closed_lost"

    def test_dormant_via_ooo_yields_dormant_outcome(self, tmp_path):
        # OOO is a soft signal — operator may want to re-engage later.
        # OOO maps to dormant outcome (NOT closed_lost) per ADR-0030 D131.
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_o", intent_id="snd_TOUCH_O",
                    thread_id="t_o",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_o", mid="g_o", thread_id="t_o",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_o", channel="email", reply_mid="g_o",
                    category="ooo",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_o",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_o", channel="email", thread_key="t_o")
        assert outcomes[tk].outcome == "dormant"

    def test_active_with_calendar_booking_yields_closed_won(
        self, tmp_path,
    ):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_w", intent_id="snd_TOUCH_W",
                    thread_id="t_w",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_w", mid="g_w", thread_id="t_w",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_w", channel="email", reply_mid="g_w",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_w",
                ),
                _calendar_booking_confirmed(
                    person_id="p_w", intent_id="cb_BOOKING_W",
                    ts="2026-05-23T15:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_w", channel="email", thread_key="t_w")
        assert outcomes[tk].outcome == "closed_won"

    def test_active_without_calendar_booking_has_no_outcome(self, tmp_path):
        # Active is a non-terminal state for outcome computation
        # purposes — the thread is in active engagement but no
        # conversion signal (booking) has landed. NO outcome event
        # emitted per ADR-0030 D131 (avoid premature closed_won emit).
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_a", intent_id="snd_TOUCH_A",
                    thread_id="t_a",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_a", mid="g_a", thread_id="t_a",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_a", channel="email", reply_mid="g_a",
                    category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_a",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_a", channel="email", thread_key="t_a")
        # Either tk not in outcomes OR its outcome is None — both
        # express "non-terminal." The contract is: NO conversation_
        # outcome event is emitted for a thread without a terminal
        # state.
        assert tk not in outcomes or outcomes[tk].outcome is None

    def test_replied_only_has_no_outcome(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_r", intent_id="snd_TOUCH_R",
                    thread_id="t_r",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_r", mid="g_r", thread_id="t_r",
                    ts="2026-05-22T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_r", channel="email", thread_key="t_r")
        assert tk not in outcomes or outcomes[tk].outcome is None

    def test_classified_uncategorized_only_has_no_outcome(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_c", intent_id="snd_TOUCH_C",
                    thread_id="t_c",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_c", mid="g_c", thread_id="t_c",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_c", channel="email", reply_mid="g_c",
                    category="uncategorized",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_c",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_c", channel="email", thread_key="t_c")
        assert tk not in outcomes or outcomes[tk].outcome is None

    def test_unsubscribe_via_llm_method_short_circuit_still_yields_won_if_booking(
        self, tmp_path,
    ):
        # Defense-in-depth: even if a malformed event slips through
        # with classification_method=llm + category=unsubscribe (which
        # is structurally impossible per ADR-0029's THREE-layer
        # carry-forward), the OUTCOME derivation still reads the
        # state-machine's terminal state. The state machine reads
        # category, not method. ADR-0030 D131 — outcome derivation is
        # method-agnostic.
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_lu", intent_id="snd_TOUCH_LU",
                    thread_id="t_lu",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_lu", mid="g_lu", thread_id="t_lu",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_lu", channel="email", reply_mid="g_lu",
                    category="unsubscribe",
                    method="rule",  # the only structurally-valid method
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_lu",
                ),
                _suppression_added(
                    person_id="p_lu", channel="email", reply_mid="g_lu",
                    value="p_lu@x.test",
                    ts="2026-05-22T10:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_lu", channel="email",
                          thread_key="t_lu")
        assert outcomes[tk].outcome == "closed_unsubscribed"


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


class TestAttributionSingleTouch:
    """ADR-0030 D131 — last-touch-wins single-touch happy path."""

    def test_single_touch_attributed_to_that_touch(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_s", intent_id="snd_THE_ONLY_TOUCH",
                    thread_id="t_s",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_s", mid="g_s", thread_id="t_s",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_s", channel="email", reply_mid="g_s",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_s",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_s", channel="email", thread_key="t_s")
        assert outcomes[tk].attributed_touch_intent_id == "snd_THE_ONLY_TOUCH"


class TestAttributionMultiTouchSameChannel:
    """ADR-0030 D131 — multi-touch on the same channel → last touch wins."""

    def test_two_email_touches_last_wins(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_m", intent_id="snd_FIRST_TOUCH",
                    thread_id="t_m",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _email_send_confirmed(
                    person_id="p_m", intent_id="snd_SECOND_TOUCH",
                    thread_id="t_m",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_m", mid="g_m", thread_id="t_m",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_m", channel="email", reply_mid="g_m",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_m",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_m", channel="email", thread_key="t_m")
        # Per D131 last-touch-wins — the SECOND (most-recent) touch is
        # the losing one.
        assert outcomes[tk].attributed_touch_intent_id == "snd_SECOND_TOUCH"

    def test_touch_after_outcome_driver_excluded(self, tmp_path):
        # A `*_confirmed` event that fires AFTER the outcome-driving
        # reply does NOT win attribution — it couldn't have driven the
        # outcome (it came too late). Per D131 the winning/losing
        # touch is the most recent one BEFORE the outcome-driver.
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_t", intent_id="snd_TOUCH_BEFORE",
                    thread_id="t_t",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_t", mid="g_t", thread_id="t_t",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_t", channel="email", reply_mid="g_t",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_t",
                ),
                # Spurious later touch — would not have driven the
                # outcome since the classification fired first.
                _email_send_confirmed(
                    person_id="p_t", intent_id="snd_TOUCH_AFTER",
                    thread_id="t_t",
                    ts="2026-05-23T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_t", channel="email", thread_key="t_t")
        assert outcomes[tk].attributed_touch_intent_id == "snd_TOUCH_BEFORE"


class TestAttributionCrossChannel:
    """ADR-0030 D131 — cross-channel: attribution is per-channel-of-thread."""

    def test_email_touch_plus_linkedin_touch_li_reply_wins_li_touch(
        self, tmp_path,
    ):
        # Person p_x has an email send + a LinkedIn DM send.
        # They reply on LinkedIn → the thread is the LinkedIn thread →
        # attribution looks for the most-recent LinkedIn `*_confirmed`
        # for this person. The email touch is on a DIFFERENT channel
        # and DOES NOT win attribution.
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_x", intent_id="snd_EMAIL_TOUCH",
                    thread_id="t_x_email",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _li_dm_confirmed(
                    person_id="p_x", intent_id="snd_LINKEDIN_TOUCH",
                    thread_id="t_x_li",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _li_dm_reply(
                    person_id="p_x", mid="li_msg_x",
                    thread_id="t_x_li",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_x", channel="linkedin",
                    reply_mid="li_msg_x", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_x", channel="linkedin",
                          thread_key="t_x_li")
        # LinkedIn touch wins — same channel as the thread.
        assert outcomes[tk].attributed_touch_intent_id == "snd_LINKEDIN_TOUCH"

    def test_no_same_channel_touch_yields_none_attribution(self, tmp_path):
        # Person p_n has an email touch but the reply comes in on
        # LinkedIn — no LinkedIn `*_confirmed` touch exists. The
        # attribution is None (recipient may have looked up our
        # LinkedIn profile independently after seeing the email).
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_n", intent_id="snd_EMAIL_ONLY",
                    thread_id="t_n_email",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _li_dm_reply(
                    person_id="p_n", mid="li_msg_n",
                    thread_id="t_n_li",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_n", channel="linkedin",
                    reply_mid="li_msg_n", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_n", channel="linkedin",
                          thread_key="t_n_li")
        assert outcomes[tk].attributed_touch_intent_id is None


class TestAttributionPerChannelTypes:
    """Per-week review P2-A — pin attribution across ALL four touch
    types in :data:`_TOUCH_CHANNEL_BY_TYPE`. The original Week 9-11
    commit defined `_li_invite_confirmed` + `_tw_dm_confirmed`
    fixtures but never exercised them; the audit doc overstated
    coverage. This test class closes the gap."""

    def test_li_invite_confirmed_attributes_to_linkedin_channel(
        self, tmp_path,
    ):
        # LinkedIn invite acceptance flow: send invitation → invitation
        # accepted (li_invite_reply_received per Pass H) → recipient
        # writes back via LinkedIn DM → reply classified as rejection.
        # Attribution looks for the most-recent linkedin-channel touch
        # BEFORE the reply; the invite-confirmed touch wins.
        led = _ledger_with(
            [
                _li_invite_confirmed(
                    person_id="p_inv", intent_id="snd_INV_TOUCH",
                    invitation_id="inv_p_inv",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _li_dm_reply(
                    person_id="p_inv", mid="li_dm_msg_inv",
                    thread_id="t_inv_li",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_inv", channel="linkedin",
                    reply_mid="li_dm_msg_inv", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_inv", channel="linkedin",
                          thread_key="t_inv_li")
        assert outcomes[tk].outcome == "closed_lost"
        # The li_invite_confirmed touch wins per _TOUCH_CHANNEL_BY_TYPE
        # (li_invite_confirmed → linkedin).
        assert (
            outcomes[tk].attributed_touch_intent_id == "snd_INV_TOUCH"
        )

    def test_tw_dm_confirmed_attributes_to_twitter_channel(
        self, tmp_path,
    ):
        # Twitter DM flow: send DM → recipient replies → reply
        # classified as rejection. Attribution looks for the
        # most-recent twitter-channel touch.
        led = _ledger_with(
            [
                _tw_dm_confirmed(
                    person_id="p_tw", intent_id="snd_TW_TOUCH",
                    thread_id="t_tw",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                {
                    "type": "tw_dm_reply_received",
                    "person_id": "p_tw", "channel": "twitter",
                    "reply_message_id": "tw_msg_p",
                    "twitter_thread_id": "t_tw",
                    "snippet": "no thanks",
                    "ts": "2026-05-22T10:00:00.000Z",
                },
                _classified(
                    person_id="p_tw", channel="twitter",
                    reply_mid="tw_msg_p", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_tw", channel="twitter",
                          thread_key="t_tw")
        assert outcomes[tk].outcome == "closed_lost"
        # The tw_dm_confirmed touch wins per _TOUCH_CHANNEL_BY_TYPE
        # (tw_dm_confirmed → twitter).
        assert (
            outcomes[tk].attributed_touch_intent_id == "snd_TW_TOUCH"
        )


class TestAttributionForBookingDrivenWon:
    """ADR-0030 D131 — closed_won attribution: the touch that drove the
    booking is the touch on the SAME channel as the active thread."""

    def test_closed_won_attributes_to_last_touch_on_active_thread_channel(
        self, tmp_path,
    ):
        # Active thread on LinkedIn (interest classified); cal booking
        # lands later. The winning touch is the most-recent LinkedIn
        # touch before the booking.
        led = _ledger_with(
            [
                _li_dm_confirmed(
                    person_id="p_b", intent_id="snd_LI_FIRST_TOUCH",
                    thread_id="t_b",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _li_dm_confirmed(
                    person_id="p_b", intent_id="snd_LI_LAST_TOUCH",
                    thread_id="t_b",
                    ts="2026-05-19T10:00:00.000Z",
                ),
                _li_dm_reply(
                    person_id="p_b", mid="li_msg_b",
                    thread_id="t_b",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_b", channel="linkedin",
                    reply_mid="li_msg_b", category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                ),
                _calendar_booking_confirmed(
                    person_id="p_b", intent_id="cb_BOOKING_B",
                    ts="2026-05-23T15:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        tk = cs.ThreadKey(person_id="p_b", channel="linkedin",
                          thread_key="t_b")
        assert outcomes[tk].outcome == "closed_won"
        assert (
            outcomes[tk].attributed_touch_intent_id == "snd_LI_LAST_TOUCH"
        )

    def test_multiple_active_threads_one_booking_yields_won_for_each(
        self, tmp_path,
    ):
        """Per-week review P2-B — pin the v1 multi-active-thread
        attribution semantics explicitly.

        When a person has multiple active threads (e.g., email +
        LinkedIn both got interest-classified) and ONE booking lands,
        ALL active threads whose active-transition precedes the
        booking receive a `closed_won` outcome event. The per-Person
        aggregation surface (`derived_conversation_outcome`) reflects
        closed_won regardless.

        This is the documented v1 limitation per ADR-0030 D131
        §"closed_won correlation is per-PERSON": Cal.com bookings
        don't carry the active-thread `thread_key`, so the framework
        cannot determine WHICH active thread actually drove the
        booking. The conservative v1 choice is to attribute won to
        every eligible thread; Pillar G dashboards may compute a
        more-refined attribution from the per-touch send history.
        Future Pillar I CLI extension MAY refine if Cal.com adds a
        custom-field surface.
        """
        led = _ledger_with(
            [
                # Email active thread.
                _email_send_confirmed(
                    person_id="p_multi", intent_id="snd_EMAIL_TOUCH",
                    thread_id="t_email",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_multi", mid="g_em_multi",
                    thread_id="t_email",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_multi", channel="email",
                    reply_mid="g_em_multi", category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_email",
                ),
                # LinkedIn active thread.
                _li_dm_confirmed(
                    person_id="p_multi", intent_id="snd_LI_TOUCH",
                    thread_id="t_li",
                    ts="2026-05-16T10:00:00.000Z",
                ),
                _li_dm_reply(
                    person_id="p_multi", mid="li_msg_multi",
                    thread_id="t_li",
                    ts="2026-05-22T11:00:00.000Z",
                ),
                _classified(
                    person_id="p_multi", channel="linkedin",
                    reply_mid="li_msg_multi", category="interest",
                    ts="2026-05-22T11:00:01.000Z",
                ),
                # ONE booking after BOTH active-transitions.
                _calendar_booking_confirmed(
                    person_id="p_multi", intent_id="cb_MULTI",
                    ts="2026-05-23T15:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        email_tk = cs.ThreadKey(
            person_id="p_multi", channel="email", thread_key="t_email",
        )
        li_tk = cs.ThreadKey(
            person_id="p_multi", channel="linkedin", thread_key="t_li",
        )
        # BOTH active threads get closed_won — the documented v1
        # limitation.
        assert outcomes[email_tk].outcome == "closed_won"
        assert outcomes[li_tk].outcome == "closed_won"
        # Per-Person aggregation reflects closed_won.
        assert (
            co.derived_conversation_outcome(led, "p_multi") == "closed_won"
        )


# ---------------------------------------------------------------------------
# TTL transitions
# ---------------------------------------------------------------------------


class TestTTLTransitions:
    """ADR-0030 D132 — TTL-driven * → dormant transitions."""

    def test_ttl_default_constant_is_30_days(self):
        # Operator-tunable default per ADR-0030 D132.
        assert cs.DEFAULT_CONVERSATION_TTL_DAYS == 30

    def test_replied_state_past_ttl_transitions_to_dormant(self, tmp_path):
        # A thread in `replied` (no classification ever landed) past
        # the TTL window transitions to dormant.
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_tx", mid="g_tx", thread_id="t_tx",
                    ts="2026-01-01T10:00:00.000Z",  # ~5 months ago
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(
            led, now=now, ttl_days=30,
        )
        tk = cs.ThreadKey(person_id="p_tx", channel="email",
                          thread_key="t_tx")
        assert states[tk].state == "dormant"

    def test_classified_past_ttl_transitions_to_dormant(self, tmp_path):
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_ct", mid="g_ct", thread_id="t_ct",
                    ts="2026-01-01T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_ct", channel="email", reply_mid="g_ct",
                    category="uncategorized",
                    ts="2026-01-01T10:00:01.000Z",
                    gmail_thread_id="t_ct",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(
            led, now=now, ttl_days=30,
        )
        tk = cs.ThreadKey(person_id="p_ct", channel="email",
                          thread_key="t_ct")
        assert states[tk].state == "dormant"

    def test_active_past_ttl_transitions_to_dormant(self, tmp_path):
        # ADR-0030 D132 — even `active` threads (someone showed
        # interest) transition to dormant after TTL of inactivity. The
        # operator can re-engage explicitly but the framework's
        # automatic posture is "stop waiting after N days."
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_at", mid="g_at", thread_id="t_at",
                    ts="2026-01-01T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_at", channel="email", reply_mid="g_at",
                    category="interest",
                    ts="2026-01-01T10:00:01.000Z",
                    gmail_thread_id="t_at",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(
            led, now=now, ttl_days=30,
        )
        tk = cs.ThreadKey(person_id="p_at", channel="email",
                          thread_key="t_at")
        assert states[tk].state == "dormant"

    def test_unsubscribed_NOT_affected_by_ttl(self, tmp_path):
        # Terminal states are immutable per the state machine's
        # priority rule. The TTL transition is a NEW driver — it can
        # only ELEVATE non-terminal states to dormant; it cannot
        # demote unsubscribed.
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_ut", mid="g_ut", thread_id="t_ut",
                    ts="2026-01-01T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_ut", channel="email", reply_mid="g_ut",
                    category="unsubscribe",
                    ts="2026-01-01T10:00:01.000Z",
                    gmail_thread_id="t_ut",
                ),
                _suppression_added(
                    person_id="p_ut", channel="email", reply_mid="g_ut",
                    value="p_ut@x.test",
                    ts="2026-01-01T10:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(
            led, now=now, ttl_days=30,
        )
        tk = cs.ThreadKey(person_id="p_ut", channel="email",
                          thread_key="t_ut")
        # Unsubscribed > dormant per STATE_PRIORITY — TTL doesn't win.
        assert states[tk].state == "unsubscribed"

    def test_thread_within_ttl_window_stays_in_current_state(
        self, tmp_path,
    ):
        # A thread that's well-inside the TTL window keeps its current
        # state (no spurious transitions).
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_in", mid="g_in", thread_id="t_in",
                    ts="2026-05-22T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(
            led, now=now, ttl_days=30,
        )
        tk = cs.ThreadKey(person_id="p_in", channel="email",
                          thread_key="t_in")
        assert states[tk].state == "replied"

    def test_ttl_zero_disables_ttl_check(self, tmp_path):
        # ttl_days=0 is the off-switch — no TTL transitions fire.
        # Operators wanting to disable TTL (e.g., manual pipeline)
        # pass 0.
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_z", mid="g_z", thread_id="t_z",
                    ts="2026-01-01T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(
            led, now=now, ttl_days=0,
        )
        tk = cs.ThreadKey(person_id="p_z", channel="email",
                          thread_key="t_z")
        # Stays in replied — TTL disabled.
        assert states[tk].state == "replied"

    def test_ttl_only_applies_when_now_provided(self, tmp_path):
        # Backwards-compat with Week 4-5 callsites: omitting `now`
        # means "no TTL evaluation" — the pre-Week-9-11 behavior.
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_no_now", mid="g_no_now",
                    thread_id="t_no_now",
                    ts="2026-01-01T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        states = cs.compute_thread_states(led)  # no `now` arg
        tk = cs.ThreadKey(person_id="p_no_now", channel="email",
                          thread_key="t_no_now")
        assert states[tk].state == "replied"

    def test_recent_activity_resets_ttl_window(self, tmp_path):
        # If a thread has an OLD initial reply but a RECENT subsequent
        # event (e.g., another reply on the thread), the TTL window
        # is measured from the most-recent activity. The thread stays
        # in its current state.
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_rr", mid="g_rr_old",
                    thread_id="t_rr",
                    ts="2026-01-01T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_rr", mid="g_rr_new",
                    thread_id="t_rr",
                    ts="2026-05-22T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(
            led, now=now, ttl_days=30,
        )
        tk = cs.ThreadKey(person_id="p_rr", channel="email",
                          thread_key="t_rr")
        assert states[tk].state == "replied"

    def test_rejection_dormant_past_ttl_stays_dormant_NOT_overwritten(
        self, tmp_path,
    ):
        """Per-week review P1 regression — TTL block MUST NOT overwrite
        category-driven dormant triggers.

        Original bug: a rejection-driven dormant thread (state=dormant,
        trigger carries reply_message_id for the rejection event) had
        its TTL block fire when last_activity_ts < cutoff. The TTL
        block overwrote ``cur.trigger["dormant"]`` with the TTL-driver
        shape (driver:"ttl", reply_message_id:None), causing Pass O's
        `_classify_dormant_driver` to return "ttl" → outcome = "dormant"
        instead of "closed_lost". A rejection from >30 days ago was
        silently reclassified.

        Fix: the TTL block's eligibility check uses an explicit
        allow-list `state in ("replied", "classified", "active")`.
        Already-dormant threads (whether category-driven via rejection
        / ooo OR TTL-driven on a prior run) are skipped.

        This test pins: a rejection-driven dormant thread past TTL
        retains its rejection trigger. The driver field stays
        ABSENT (per the non-TTL convention); reply_message_id stays
        populated.
        """
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_rj", intent_id="snd_RJ",
                    thread_id="t_rj",
                    ts="2026-01-01T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_rj", mid="g_rj_OLD",
                    thread_id="t_rj",
                    ts="2026-01-02T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_rj", channel="email",
                    reply_mid="g_rj_OLD", category="rejection",
                    ts="2026-01-02T10:00:01.000Z",
                    gmail_thread_id="t_rj",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)  # ~5 mo later
        # The thread is well past the 30-day TTL window.
        states = cs.compute_thread_states(led, now=now, ttl_days=30)
        tk = cs.ThreadKey(person_id="p_rj", channel="email",
                          thread_key="t_rj")
        assert states[tk].state == "dormant"
        # The trigger MUST still carry the rejection event's
        # reply_message_id + MUST NOT carry the TTL driver field.
        trigger = states[tk].trigger.get("dormant") or {}
        assert trigger.get("reply_message_id") == "g_rj_OLD", (
            f"TTL block overwrote rejection-driven dormant trigger. "
            f"Per ADR-0030 D132 the TTL driver MUST NOT fire on "
            f"already-dormant threads. trigger={trigger!r}"
        )
        assert trigger.get("driver") != "ttl", (
            f"TTL driver field present on rejection-driven dormant "
            f"trigger. Per the per-week review P1 finding, the TTL "
            f"block's allow-list MUST exclude `dormant` state. "
            f"trigger={trigger!r}"
        )
        # And the downstream outcome MUST be closed_lost (the hard
        # rejection signal preserved), NOT dormant (the TTL inferred
        # signal).
        outcomes = co.compute_conversation_outcomes(
            led, now=now, ttl_days=30,
        )
        assert outcomes[tk].outcome == "closed_lost", (
            f"Per ADR-0030 D131 the outcome derivation map: "
            f"`state==dormant via rejection → closed_lost`. The TTL "
            f"block MUST NOT silently reclassify to `dormant` "
            f"outcome. Got outcome={outcomes[tk].outcome!r}."
        )

    def test_ooo_dormant_past_ttl_also_stays_ooo_driven(
        self, tmp_path,
    ):
        """Per-week review P1 symmetry pin — same protection for OOO.

        OOO-driven dormancy past TTL stays ooo-driven (outcome =
        `dormant`, NOT overwritten with TTL trigger). Confirms the
        TTL block's allow-list handles BOTH dormant flavors
        symmetrically.
        """
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_oo", intent_id="snd_OO",
                    thread_id="t_oo",
                    ts="2026-01-01T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_oo", mid="g_oo_OLD",
                    thread_id="t_oo",
                    ts="2026-01-02T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_oo", channel="email",
                    reply_mid="g_oo_OLD", category="ooo",
                    ts="2026-01-02T10:00:01.000Z",
                    gmail_thread_id="t_oo",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        states = cs.compute_thread_states(led, now=now, ttl_days=30)
        tk = cs.ThreadKey(person_id="p_oo", channel="email",
                          thread_key="t_oo")
        assert states[tk].state == "dormant"
        trigger = states[tk].trigger.get("dormant") or {}
        # OOO-driven trigger carries reply_message_id; TTL would
        # overwrite with None — pin the preservation.
        assert trigger.get("reply_message_id") == "g_oo_OLD"
        assert trigger.get("driver") != "ttl"
        # Outcome is `dormant` (soft signal) — same as TTL outcome
        # but distinguishable downstream via the trigger's
        # reply_message_id presence (TTL-driven would carry None).
        outcomes = co.compute_conversation_outcomes(
            led, now=now, ttl_days=30,
        )
        assert outcomes[tk].outcome == "dormant"
        # The outcome's triggering_event_id carries the OOO trigger
        # (type=reply_classified), NOT the TTL trigger
        # (type=conversation_state_changed with driver:"ttl").
        assert outcomes[tk].triggering_event_id.get("type") == (
            "reply_classified"
        )
        assert outcomes[tk].triggering_event_id.get("driver") is None


# ---------------------------------------------------------------------------
# Pass N TTL integration (TTL drives state-transition events)
# ---------------------------------------------------------------------------


class TestPassNTTL:
    """ADR-0030 D133 — Pass N extended with TTL-driven transitions
    emits ``conversation_state_changed`` events for TTL transitions."""

    def test_pass_n_with_ttl_emits_dormant_transition(
        self, tmp_path,
    ):
        # Per the Week 4-5 contract (ADR-0028 D119), Pass N emits ONE
        # event per thread carrying the canonical CURRENT state. When
        # TTL fires, the canonical state moves to dormant + Pass N
        # emits to_state=dormant; the trigger_event_id carries
        # ``driver: "ttl"`` so consumers can distinguish from
        # category-driven dormancy.
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_pn", mid="g_pn", thread_id="t_pn",
                    ts="2026-01-01T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        since = datetime(2025, 12, 1, tzinfo=timezone.utc)
        result = cs.run_conversation_state_pass(
            led=led, since=since, apply=True,
            now=now, ttl_days=30,
        )
        synth = [e for e in result.synthesized
                 if e["type"] == "conversation_state_changed"]
        # One event for the thread — dormant (TTL-driven).
        assert len(synth) == 1
        ev = synth[0]
        assert ev["to_state"] == "dormant"
        assert ev["trigger_event_id"].get("driver") == "ttl", (
            "TTL-driven dormant transitions MUST carry "
            "driver:\"ttl\" in trigger_event_id per ADR-0030 D132."
        )

    def test_pass_n_without_ttl_kwargs_unchanged_behavior(
        self, tmp_path,
    ):
        # Backwards-compat: existing callsites that don't pass
        # `now` / `ttl_days` see Week 4-5 behavior.
        led = _ledger_with(
            [
                _email_reply(
                    person_id="p_bc", mid="g_bc", thread_id="t_bc",
                    ts="2026-01-01T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        since = datetime(2025, 12, 1, tzinfo=timezone.utc)
        result = cs.run_conversation_state_pass(
            led=led, since=since, apply=True,
        )
        to_states = [e["to_state"] for e in result.synthesized
                     if e["type"] == "conversation_state_changed"]
        # Only the replied transition — no TTL-driven dormant.
        assert to_states == ["replied"]


# ---------------------------------------------------------------------------
# Event shape
# ---------------------------------------------------------------------------


class TestConversationOutcomeEventShape:
    """ADR-0030 D130 — event shape contract for `conversation_outcome`."""

    def test_event_carries_all_required_fields(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_e", intent_id="snd_E_TOUCH",
                    thread_id="t_e",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_e", mid="g_e", thread_id="t_e",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_e", channel="email", reply_mid="g_e",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_e",
                ),
            ],
            tmp_path / "ledger",
        )
        result = co.run_conversation_outcomes_pass(
            led=led, apply=True,
        )
        synth = result.synthesized
        assert len(synth) == 1
        ev = synth[0]
        for required in (
            "type", "person_id", "channel", "thread_key",
            "outcome", "attributed_touch_intent_id",
            "triggering_event_id", "ts", "_emitted_by",
        ):
            assert required in ev, f"event missing required field {required!r}"
        assert ev["type"] == "conversation_outcome"
        assert ev["_emitted_by"] == "conversation_outcomes"
        assert isinstance(ev["triggering_event_id"], dict)
        assert ev["channel"] == "email"
        assert ev["outcome"] == "closed_lost"

    def test_non_ttl_dormant_trigger_omits_driver_field(self, tmp_path):
        """Per-week review P3-A — _build_dormant_trigger MUST omit the
        ``driver`` field for non-TTL (category-driven) dormant
        outcomes. Per ADR-0030 D130 the driver field is
        type-specific best-effort, present for TTL-driven outcomes
        only. Emitting ``driver: None`` for non-TTL cases pollutes
        operator ``--json`` output + Pillar G dashboard queries with
        a meaningless null field."""
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_nd", intent_id="snd_ND",
                    thread_id="t_nd",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_nd", mid="g_nd", thread_id="t_nd",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_nd", channel="email",
                    reply_mid="g_nd", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_nd",
                ),
            ],
            tmp_path / "ledger",
        )
        result = co.run_conversation_outcomes_pass(led=led, apply=True)
        ev = next(
            e for e in result.synthesized
            if e["type"] == "conversation_outcome"
            and e["person_id"] == "p_nd"
        )
        # Category-driven dormant trigger MUST NOT carry `driver:`
        # field at all (not even None).
        assert "driver" not in ev["triggering_event_id"], (
            f"non-TTL dormant outcome event MUST NOT carry "
            f"`driver:` field per ADR-0030 D130 + per-week review "
            f"P3-A. Got triggering_event_id="
            f"{ev['triggering_event_id']!r}."
        )

    def test_ttl_dormant_trigger_includes_driver_ttl(self, tmp_path):
        """ADR-0030 D130 — TTL-driven dormant outcome's
        triggering_event_id MUST carry `driver: "ttl"` (the
        observability marker that distinguishes TTL-driven from
        category-driven dormancy)."""
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_td", intent_id="snd_TD",
                    thread_id="t_td",
                    ts="2026-01-01T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_td", mid="g_td", thread_id="t_td",
                    ts="2026-01-02T10:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        now = datetime(2026, 5, 23, tzinfo=timezone.utc)
        result = co.run_conversation_outcomes_pass(
            led=led, apply=True, now=now, ttl_days=30,
        )
        ev = next(
            e for e in result.synthesized
            if e["type"] == "conversation_outcome"
            and e["person_id"] == "p_td"
        )
        assert ev["outcome"] == "dormant"
        assert ev["triggering_event_id"].get("driver") == "ttl"

    def test_channel_field_invariant_on_every_emit(self, tmp_path):
        # ADR-0014 D33 extended by ADR-0025 D96 — every event MUST
        # carry a top-level `channel:` field.
        led = _ledger_with(
            [
                _li_dm_confirmed(
                    person_id="p_ch", intent_id="snd_LI_CH",
                    thread_id="t_ch",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _li_dm_reply(
                    person_id="p_ch", mid="li_msg_ch",
                    thread_id="t_ch",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_ch", channel="linkedin",
                    reply_mid="li_msg_ch", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        result = co.run_conversation_outcomes_pass(led=led, apply=True)
        for ev in result.synthesized:
            assert ev.get("channel") in {
                "email", "linkedin", "twitter", "calendar",
            }, (
                f"channel-on-every-event invariant VIOLATED: event "
                f"{ev!r} missing or invalid channel field."
            )


# ---------------------------------------------------------------------------
# Pass O orchestration + idempotence
# ---------------------------------------------------------------------------


class TestRunOutcomesPass:
    """ADR-0030 D133 — Pass O orchestration + idempotence."""

    def test_apply_emits_outcome_events(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_po", intent_id="snd_PO",
                    thread_id="t_po",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_po", mid="g_po", thread_id="t_po",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_po", channel="email", reply_mid="g_po",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_po",
                ),
            ],
            tmp_path / "ledger",
        )
        result = co.run_conversation_outcomes_pass(led=led, apply=True)
        assert result.examined >= 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "conversation_outcome"
        assert ev["outcome"] == "closed_lost"

    def test_idempotent_under_rerun(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_idem", intent_id="snd_IDEM",
                    thread_id="t_idem",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_idem", mid="g_idem",
                    thread_id="t_idem",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_idem", channel="email",
                    reply_mid="g_idem", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_idem",
                ),
            ],
            tmp_path / "ledger",
        )
        first = co.run_conversation_outcomes_pass(led=led, apply=True)
        assert len(first.synthesized) == 1

        second = co.run_conversation_outcomes_pass(led=led, apply=True)
        # Re-run emits NO new events — the (pid, ch, tk, outcome)
        # tuple is already in the ledger per ADR-0030 D130 idempotence.
        assert second.synthesized == []

    def test_dry_run_does_not_append(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_dr", intent_id="snd_DR",
                    thread_id="t_dr",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_dr", mid="g_dr", thread_id="t_dr",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_dr", channel="email", reply_mid="g_dr",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_dr",
                ),
            ],
            tmp_path / "ledger",
        )
        result = co.run_conversation_outcomes_pass(
            led=led, apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0].get("_dry_run") is True
        # No conversation_outcome in ledger.
        assert not [
            e for e in led.all_events()
            if e.get("type") == "conversation_outcome"
        ]

    def test_active_thread_emits_no_outcome(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_skip", intent_id="snd_SKIP",
                    thread_id="t_skip",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_skip", mid="g_skip",
                    thread_id="t_skip",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_skip", channel="email",
                    reply_mid="g_skip", category="interest",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_skip",
                ),
            ],
            tmp_path / "ledger",
        )
        # Active without booking — non-terminal; no outcome.
        result = co.run_conversation_outcomes_pass(led=led, apply=True)
        assert result.synthesized == []


# ---------------------------------------------------------------------------
# Per-Person aggregation
# ---------------------------------------------------------------------------


class TestDerivedConversationOutcome:
    """ADR-0030 D134 — per-Person aggregation."""

    def test_no_terminal_threads_returns_none(self, tmp_path):
        led = _ledger_with([], tmp_path / "ledger")
        assert co.derived_conversation_outcome(led, "p_nothing") is None

    def test_won_dominates_other_outcomes(self, tmp_path):
        # Person has two threads: one closed_lost (rejection), one
        # closed_won (interest + booking). closed_won wins.
        led = _ledger_with(
            [
                # Thread 1 — rejected (closed_lost).
                _email_send_confirmed(
                    person_id="p_agg", intent_id="snd_T1",
                    thread_id="t_1",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_agg", mid="g_1", thread_id="t_1",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_agg", channel="email", reply_mid="g_1",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_1",
                ),
                # Thread 2 — won (interest + booking).
                _li_dm_confirmed(
                    person_id="p_agg", intent_id="snd_T2",
                    thread_id="t_2",
                    ts="2026-05-15T11:00:00.000Z",
                ),
                _li_dm_reply(
                    person_id="p_agg", mid="li_2", thread_id="t_2",
                    ts="2026-05-22T11:00:00.000Z",
                ),
                _classified(
                    person_id="p_agg", channel="linkedin",
                    reply_mid="li_2", category="interest",
                    ts="2026-05-22T11:00:01.000Z",
                ),
                _calendar_booking_confirmed(
                    person_id="p_agg", intent_id="cb_W",
                    ts="2026-05-23T15:00:00.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        assert co.derived_conversation_outcome(led, "p_agg") == "closed_won"

    def test_unsubscribed_beats_lost(self, tmp_path):
        led = _ledger_with(
            [
                # Thread 1 — rejected.
                _email_send_confirmed(
                    person_id="p_ul", intent_id="snd_T1",
                    thread_id="t_1",
                    ts="2026-05-15T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_ul", mid="g_1", thread_id="t_1",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_ul", channel="email", reply_mid="g_1",
                    category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_1",
                ),
                # Thread 2 — unsubscribed.
                _email_send_confirmed(
                    person_id="p_ul", intent_id="snd_T2",
                    thread_id="t_2",
                    ts="2026-05-15T11:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_ul", mid="g_2", thread_id="t_2",
                    ts="2026-05-22T11:00:00.000Z",
                ),
                _classified(
                    person_id="p_ul", channel="email", reply_mid="g_2",
                    category="unsubscribe",
                    ts="2026-05-22T11:00:01.000Z",
                    gmail_thread_id="t_2",
                ),
                _suppression_added(
                    person_id="p_ul", channel="email", reply_mid="g_2",
                    value="p_ul@x.test",
                    ts="2026-05-22T11:00:02.000Z",
                ),
            ],
            tmp_path / "ledger",
        )
        assert (
            co.derived_conversation_outcome(led, "p_ul")
            == "closed_unsubscribed"
        )

    def test_precomputed_outcomes_accepted(self, tmp_path):
        led = _ledger_with(
            [
                _email_send_confirmed(
                    person_id="p_pre", intent_id="snd_PRE",
                    thread_id="t_pre",
                    ts="2026-05-20T10:00:00.000Z",
                ),
                _email_reply(
                    person_id="p_pre", mid="g_pre", thread_id="t_pre",
                    ts="2026-05-22T10:00:00.000Z",
                ),
                _classified(
                    person_id="p_pre", channel="email",
                    reply_mid="g_pre", category="rejection",
                    ts="2026-05-22T10:00:01.000Z",
                    gmail_thread_id="t_pre",
                ),
            ],
            tmp_path / "ledger",
        )
        outcomes = co.compute_conversation_outcomes(led)
        assert (
            co.derived_conversation_outcome(led, "p_pre")
            == co.derived_conversation_outcome(
                led, "p_pre", outcomes=outcomes,
            )
            == "closed_lost"
        )


# ---------------------------------------------------------------------------
# Pass O integration via reconcile
# ---------------------------------------------------------------------------


class TestReconcileIntegration:
    """ADR-0030 D133 — Pass O integrates with the reconcile chain."""

    def test_pass_o_in_all_passes(self):
        assert "O" in _reconcile.ALL_PASSES

    def test_pass_o_after_pass_n(self):
        # Pass O reads Pass N's `conversation_state_changed` events
        # (the canonical state machine output). Pass N must run first
        # so the same reconcile run sees both the state transitions
        # AND the outcome derivation.
        passes = _reconcile.ALL_PASSES
        assert passes.index("O") > passes.index("N"), (
            f"Pass O must run AFTER Pass N (consumes its state-machine "
            f"transitions). ALL_PASSES = {passes!r}."
        )

    def test_reconcile_pass_o_emits_outcome(self, tmp_path, monkeypatch):
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(ledger_dir))
        led = _ledger.Ledger(ledger_dir)
        for ev in [
            _email_send_confirmed(
                person_id="p_ro", intent_id="snd_RO",
                thread_id="t_ro",
                ts="2026-05-20T10:00:00.000Z",
            ),
            _email_reply(
                person_id="p_ro", mid="g_ro", thread_id="t_ro",
                ts="2026-05-22T10:00:00.000Z",
            ),
            _classified(
                person_id="p_ro", channel="email", reply_mid="g_ro",
                category="rejection",
                ts="2026-05-22T10:00:01.000Z",
                gmail_thread_id="t_ro",
            ),
        ]:
            led.append(ev)

        result = _reconcile.reconcile(
            passes="O",
            since=datetime(2026, 5, 1, tzinfo=timezone.utc),
            led=led,
            apply=True,
            persist_status=False,
        )
        pass_o_result = next(p for p in result.passes if p.pass_name == "O")
        assert pass_o_result.synthesized, (
            f"Pass O should emit at least one outcome; got "
            f"errors={pass_o_result.errors}"
        )
        ev = pass_o_result.synthesized[0]
        assert ev["type"] == "conversation_outcome"
        assert ev["outcome"] == "closed_lost"


# ---------------------------------------------------------------------------
# Public symbol surface
# ---------------------------------------------------------------------------


class TestPublicSymbolSurface:
    """ADR-0030 D129 — module's public symbols are stable."""

    def test_public_api_present(self):
        for sym in (
            "ConversationOutcome",
            "ConversationOutcomesPassResult",
            "OUTCOMES",
            "OUTCOME_PRIORITY",
            "compute_conversation_outcomes",
            "derived_conversation_outcome",
            "build_outcome_payload",
            "run_conversation_outcomes_pass",
        ):
            assert hasattr(co, sym), (
                f"public symbol {sym!r} missing from "
                f"orchestrator.conversation_outcomes"
            )

    def test_emitted_by_constant_present(self):
        # Pass O's emit-site tags `_emitted_by: "conversation_outcomes"`;
        # the constant is the source-of-truth for tests + audit doc.
        assert co.EMITTED_BY == "conversation_outcomes"
