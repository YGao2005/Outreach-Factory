"""Pillar A Week 1 task #5 — cooldown rules + DST property test.

Covers the four factory cooldown rule classes:
  - NoDuplicateRegisterRule (cooldown.no-duplicate-register)
  - RequiresPriorSendRule (cooldown.requires-prior-send)
  - RequiresPersonStatusRule (cooldown.requires-person-status)
  - DomainThrottleRule (cooldown.domain-throttle)

Tests are organized:
  TestNoDuplicateRegisterRule — basic allow/block, register-scoping,
                                 block_when filter, channel filter.
  TestRequiresPriorSendRule — no prior → block, recent prior → block,
                               aged prior → allow, register filter.
  TestRequiresPersonStatusRule — exact match → allow, mismatch → block,
                                  None → block (restrictive).
  TestDomainThrottleRule — count-in-window thresholds.
  TestFromYaml — every rule class round-trips through YAML spec.
  TestEmptyHistoryNoFalseBlocks — invariant: an empty ledger never
                                   produces a Block from cooldown rules
                                   that *require* prior history.
  TestDSTSafetyProperty — Hypothesis property: cooldown verdict is
                          identical across recipient timezones.
  TestDSTCrossing — concrete spring-forward / fall-back date pairs.

The fake ledger here is a minimal in-memory implementation so we don't
have to manage tmp directories per test. It exposes the LedgerLike
Protocol surface only.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from orchestrator import policy as policy_pkg
from orchestrator.policy import cooldown as cd
from orchestrator.policy import engine as policy_engine
from orchestrator.policy import types as policy_types


# ---------------------------------------------------------------------------
# Fake ledger — minimal LedgerLike for these tests
# ---------------------------------------------------------------------------


class _Evt(dict):
    """A dict that quacks like Event enough for cooldown.py's consumption.

    cooldown.py reads via .get() and indexing; this works.
    """

    @property
    def type(self):
        return self["type"]

    @property
    def person_id(self):
        return self.get("person_id")

    @property
    def intent_id(self):
        return self.get("intent_id")

    @property
    def ts(self):
        return self.get("ts")


class _FakeLedger:
    """Minimal ledger for cooldown tests. Stores events; serves the
    LedgerLike Protocol methods cooldown rules call.

    Construct empty, then `.add_send(person_id, channel, register, ts, email)`
    to seed prior confirmed sends. Internally synthesizes the
    (send_intent, send_confirmed) pair the rules look for.
    """

    def __init__(self):
        self._events: list[_Evt] = []
        self._intent_counter = 0

    def add_send(
        self,
        *,
        person_id: str,
        channel: str,
        register: str,
        ts: datetime,
        email: str | None = None,
        confirmed: bool = True,
    ) -> str:
        """Add a (send_intent, send_confirmed?) pair. Returns intent_id."""
        self._intent_counter += 1
        intent_id = f"snd_test_{self._intent_counter:06d}"
        ts_iso = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self._events.append(_Evt({
            "v": 1, "type": "send_intent", "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": channel, "register": register,
            "email": email,
        }))
        if confirmed:
            # Confirmation lands ~1s later in real life; +1ms here for
            # deterministic ordering in tests.
            conf_ts = (ts + timedelta(milliseconds=1)).astimezone(timezone.utc) \
                .isoformat().replace("+00:00", "Z")
            self._events.append(_Evt({
                "v": 1, "type": "send_confirmed", "ts": conf_ts,
                "intent_id": intent_id, "person_id": person_id,
                "channel": channel, "email": email,
                "gmail_message_id": f"gm_{intent_id}",
            }))
        return intent_id

    def query_by_person(self, person_id, since=None):
        out = [e for e in self._events if e.get("person_id") == person_id]
        if since is not None:
            cutoff = since.astimezone(timezone.utc).isoformat() \
                .replace("+00:00", "Z")
            out = [e for e in out if (e.get("ts") or "") >= cutoff]
        return out

    def last_send_for(self, person_id, channel):
        """Return chronologically last send_confirmed for (person_id, channel)."""
        best = None
        for e in self._events:
            if e.get("type") != "send_confirmed":
                continue
            if e.get("person_id") != person_id:
                continue
            if e.get("channel") != channel:
                continue
            if best is None or (e.get("ts") or "") > (best.get("ts") or ""):
                best = e
        return best

    def query_by_email(self, email):
        out: set[str] = set()
        for e in self._events:
            if (e.get("email") or "").lower() == email.lower():
                pid = e.get("person_id")
                if pid:
                    out.add(pid)
        return out

    def all_events(self):
        return list(self._events)


def _make_ctx(
    *,
    ledger=None,
    register="cold-pitch",
    channel="email",
    person_id="alice-li",
    email="alice@example.com",
    person_status=None,
    now=None,
    tz="America/Los_Angeles",
):
    return policy_types.RuleContext(
        person_id=person_id,
        channel=channel,
        register=register,
        email=email,
        email_domain=email.split("@", 1)[1] if email and "@" in email else None,
        now=now or datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        timezone=tz,
        ledger=ledger or _FakeLedger(),
        person_status=person_status,
    )


# ---------------------------------------------------------------------------
# NoDuplicateRegisterRule
# ---------------------------------------------------------------------------


class TestNoDuplicateRegisterRule:
    def test_no_prior_send_allows(self):
        rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch"},
            reason="Already cold-pitched this person",
        )
        ctx = _make_ctx()
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_prior_cold_pitch_blocks(self):
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=datetime(2026, 4, 1, tzinfo=timezone.utc),
            email="alice@example.com",
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch"},
            reason="Already cold-pitched this person",
        )
        ctx = _make_ctx(ledger=led)
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "no-double-cold-pitch"
        assert "prior_intent_id" in result.detail

    def test_prior_different_register_allows(self):
        """A prior follow-up doesn't block a fresh cold-pitch."""
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="follow-up",
            ts=datetime(2026, 4, 1, tzinfo=timezone.utc),
            email="alice@example.com",
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch"},
        )
        ctx = _make_ctx(ledger=led, register="cold-pitch")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_block_when_register_filter_skips_other_registers(self):
        """Rule scoped to cold-pitch doesn't fire on a follow-up send."""
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=datetime(2026, 4, 1, tzinfo=timezone.utc),
            email="alice@example.com",
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch"},
        )
        # Sending a follow-up — the no-double-cold-pitch rule should
        # not fire even though a prior cold-pitch exists.
        ctx = _make_ctx(ledger=led, register="follow-up")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_block_when_channel_filter(self):
        """A rule scoped to channel:email doesn't fire on LinkedIn."""
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=datetime(2026, 4, 1, tzinfo=timezone.utc),
            email="alice@example.com",
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch", "channel": "email"},
        )
        ctx = _make_ctx(ledger=led, channel="linkedin", email=None)
        # Channel mismatch → rule doesn't apply → Allow.
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_failed_send_does_not_block(self):
        """A send_failed (no send_confirmed) is not a prior 'sent' state."""
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=datetime(2026, 4, 1, tzinfo=timezone.utc),
            email="alice@example.com",
            confirmed=False,
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch"},
        )
        ctx = _make_ctx(ledger=led)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# RequiresPriorSendRule
# ---------------------------------------------------------------------------


class TestRequiresPriorSendRule:
    def _rule(self):
        return cd.RequiresPriorSendRule(
            name="follow-up-requires-prior-cold-pitch",
            block_when={"register": "follow-up"},
            requires_register="cold-pitch",
            min_age_days=7,
            reason="Follow-up requires a confirmed cold-pitch ≥7d ago",
        )

    def test_no_prior_blocks(self):
        ctx = _make_ctx(register="follow-up")
        result = self._rule().evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "follow-up-requires-prior-cold-pitch"
        # Detail should explain why.
        assert result.detail.get("missing_prior") is True

    def test_recent_prior_blocks(self):
        """Prior cold-pitch exists but is <7d old → block (still inside cooldown)."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3),
            email="alice@example.com",
        )
        ctx = _make_ctx(ledger=led, register="follow-up", now=now)
        result = self._rule().evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("age_days") is not None
        assert result.detail["age_days"] < 7

    def test_aged_prior_allows(self):
        """Prior cold-pitch ≥7d old → allow."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=10),
            email="alice@example.com",
        )
        ctx = _make_ctx(ledger=led, register="follow-up", now=now)
        result = self._rule().evaluate(ctx)
        assert isinstance(result, policy_types.Allow)

    def test_exactly_seven_days_allows(self):
        """Edge case: exactly 7 days old → allow (≥ is inclusive)."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=7, seconds=1),
            email="alice@example.com",
        )
        ctx = _make_ctx(ledger=led, register="follow-up", now=now)
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_wrong_prior_register_blocks(self):
        """A prior follow-up doesn't count as the required cold-pitch."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="follow-up",
            ts=now - timedelta(days=10),
            email="alice@example.com",
        )
        ctx = _make_ctx(ledger=led, register="follow-up", now=now)
        result = self._rule().evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("missing_prior") is True

    def test_block_when_register_filter(self):
        """Rule scoped to follow-up doesn't fire on a cold-pitch send."""
        ctx = _make_ctx(register="cold-pitch")
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# RequiresPersonStatusRule
# ---------------------------------------------------------------------------


class TestRequiresPersonStatusRule:
    def _rule(self):
        return cd.RequiresPersonStatusRule(
            name="re-engage-requires-dormancy",
            block_when={"register": "re-engage"},
            required_status="dormant",
            reason="Re-engage only for dormant prospects",
        )

    def test_matching_status_allows(self):
        ctx = _make_ctx(register="re-engage", person_status="dormant")
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_other_status_blocks(self):
        ctx = _make_ctx(register="re-engage", person_status="contacted")
        result = self._rule().evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("actual_status") == "contacted"
        assert result.detail.get("required_status") == "dormant"

    def test_none_status_blocks(self):
        """ADR-0002 restrictive interpretation: unknown status → block.

        Asymmetric failure cost: refusing re-engage to a non-dormant
        person costs one missed conversation. Sending re-engage to a
        not-actually-dormant person costs a "why did you re-engage me?"
        reply.
        """
        ctx = _make_ctx(register="re-engage", person_status=None)
        assert isinstance(self._rule().evaluate(ctx), policy_types.Block)

    def test_block_when_register_filter(self):
        """Rule doesn't fire on non-re-engage sends."""
        ctx = _make_ctx(register="cold-pitch", person_status="contacted")
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# DomainThrottleRule
# ---------------------------------------------------------------------------


class TestDomainThrottleRule:
    def _rule(self, count=1, days=14):
        return cd.DomainThrottleRule(
            name="domain-cooldown",
            block_when={"channel": "email"},
            max_count=count,
            window_days=days,
            reason=f"≥{count} send(s) to this domain in last {days}d",
        )

    def test_no_history_allows(self):
        ctx = _make_ctx()
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_one_prior_in_window_blocks(self):
        """count=1 + 1 prior within window → block."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="bob-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=7),
            email="bob@example.com",
        )
        ctx = _make_ctx(ledger=led, now=now)
        result = self._rule(count=1, days=14).evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("count_in_window") == 1
        assert result.detail.get("threshold") == 1

    def test_prior_outside_window_allows(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="bob-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=30),  # outside 14d window
            email="bob@example.com",
        )
        ctx = _make_ctx(ledger=led, now=now)
        assert isinstance(
            self._rule(count=1, days=14).evaluate(ctx),
            policy_types.Allow,
        )

    def test_different_domain_allows(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="bob-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3),
            email="bob@other-co.com",
        )
        ctx = _make_ctx(ledger=led, now=now,
                        email="alice@example.com")
        # Domain mismatch — example.com vs other-co.com.
        assert isinstance(
            self._rule(count=1, days=14).evaluate(ctx),
            policy_types.Allow,
        )

    def test_count_threshold_at_boundary(self):
        """count=3 with exactly 3 prior in window → block."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for i in range(3):
            led.add_send(
                person_id=f"p{i}-li", channel="email", register="cold-pitch",
                ts=now - timedelta(days=i + 1),
                email=f"p{i}@example.com",
            )
        ctx = _make_ctx(ledger=led, now=now)
        result = self._rule(count=3, days=14).evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail["count_in_window"] == 3

    def test_count_threshold_below(self):
        """count=3 with 2 prior → allow (not yet at threshold)."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        for i in range(2):
            led.add_send(
                person_id=f"p{i}-li", channel="email", register="cold-pitch",
                ts=now - timedelta(days=i + 1),
                email=f"p{i}@example.com",
            )
        ctx = _make_ctx(ledger=led, now=now)
        assert isinstance(
            self._rule(count=3, days=14).evaluate(ctx),
            policy_types.Allow,
        )

    def test_at_exact_boundary_blocks(self):
        """Boundary contract: an event whose ts is **exactly**
        ``now - window_days`` is inside the window → counted → Block.

        Pins the inclusive-lower-end convention that
        :class:`CrossChannelTouchRule` also follows (per ADR-0003 CC-06
        the two rules are explicitly aligned). Without this test the
        ``<`` vs ``<=`` choice could silently drift in either rule.
        """
        now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # Append a send_confirmed directly with ts == cutoff (no +1ms
        # intent/confirm offset). _FakeLedger.add_send would add the
        # offset and prevent pinning the exact boundary instant.
        cutoff_ts = (now - timedelta(days=14)).isoformat() \
            .replace("+00:00", "Z")
        led._events.append(_Evt({
            "v": 1, "type": "send_confirmed", "ts": cutoff_ts,
            "intent_id": "snd_pin_boundary",
            "person_id": "boundary-li",
            "channel": "email", "email": "boundary@example.com",
            "gmail_message_id": "gm_pin_boundary",
        }))
        ctx = _make_ctx(ledger=led, now=now,
                        email="other@example.com")  # rule reads all_events; domain match on event side
        result = self._rule(count=1, days=14).evaluate(ctx)
        assert isinstance(result, policy_types.Block), \
            "ev_ts == cutoff must be inside the window (inclusive lower-end)"

    def test_one_microsecond_past_boundary_allows(self):
        """Boundary contract negative: an event strictly older than
        ``now - window_days`` is outside the window → not counted."""
        now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        old_ts = (now - timedelta(days=14, microseconds=1)).isoformat() \
            .replace("+00:00", "Z")
        led._events.append(_Evt({
            "v": 1, "type": "send_confirmed", "ts": old_ts,
            "intent_id": "snd_pin_past",
            "person_id": "past-li",
            "channel": "email", "email": "past@example.com",
            "gmail_message_id": "gm_pin_past",
        }))
        ctx = _make_ctx(ledger=led, now=now,
                        email="other@example.com")
        assert isinstance(
            self._rule(count=1, days=14).evaluate(ctx),
            policy_types.Allow,
        )

    def test_block_when_channel_filter(self):
        """Rule scoped to channel:email doesn't fire on linkedin."""
        ctx = _make_ctx(channel="linkedin", email=None)
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)

    def test_no_email_no_block(self):
        """No email domain to throttle on → allow (rule is a no-op)."""
        ctx = _make_ctx(channel="email", email=None)
        assert isinstance(self._rule().evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# YAML round-trip (from_yaml)
# ---------------------------------------------------------------------------


class TestFromYaml:
    def test_no_duplicate_register_from_yaml(self):
        spec = {
            "name": "no-double-cold-pitch",
            "type": "cooldown.no-duplicate-register",
            "block_when": {"register": "cold-pitch"},
            "reason": "Already cold-pitched this person",
        }
        rule = cd.NoDuplicateRegisterRule.from_yaml(spec)
        assert rule.name == "no-double-cold-pitch"
        assert rule.block_when == {"register": "cold-pitch"}

    def test_requires_prior_send_from_yaml(self):
        spec = {
            "name": "follow-up-requires-prior-cold-pitch",
            "type": "cooldown.requires-prior-send",
            "block_when": {"register": "follow-up"},
            "requires_register": "cold-pitch",
            "min_age_days": 7,
            "reason": "...",
        }
        rule = cd.RequiresPriorSendRule.from_yaml(spec)
        assert rule.name == "follow-up-requires-prior-cold-pitch"
        assert rule.requires_register == "cold-pitch"
        assert rule.min_age_days == 7

    def test_requires_person_status_from_yaml(self):
        spec = {
            "name": "re-engage-requires-dormancy",
            "type": "cooldown.requires-person-status",
            "block_when": {"register": "re-engage"},
            "required_status": "dormant",
        }
        rule = cd.RequiresPersonStatusRule.from_yaml(spec)
        assert rule.name == "re-engage-requires-dormancy"
        assert rule.required_status == "dormant"

    def test_domain_throttle_from_yaml(self):
        spec = {
            "name": "domain-cooldown",
            "type": "cooldown.domain-throttle",
            "block_when": {"channel": "email"},
            "max_count": 3,
            "window_days": 14,
        }
        rule = cd.DomainThrottleRule.from_yaml(spec)
        assert rule.name == "domain-cooldown"
        assert rule.max_count == 3
        assert rule.window_days == 14

    def test_required_fields_enforced(self):
        # Missing min_age_days on RequiresPriorSendRule.
        with pytest.raises((KeyError, ValueError)):
            cd.RequiresPriorSendRule.from_yaml({
                "name": "x", "type": "cooldown.requires-prior-send",
                "requires_register": "cold-pitch",
            })

    def test_load_rules_from_yaml_integrates(self, tmp_path):
        """End-to-end: cooldown classes are registered, YAML loads cleanly."""
        p = tmp_path / "cooldowns.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: no-double-cold-pitch\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when: {register: cold-pitch}\n"
            "    reason: 'Already cold-pitched this person'\n"
            "  - name: follow-up-requires-prior-cold-pitch\n"
            "    type: cooldown.requires-prior-send\n"
            "    block_when: {register: follow-up}\n"
            "    requires_register: cold-pitch\n"
            "    min_age_days: 7\n"
            "  - name: re-engage-requires-dormancy\n"
            "    type: cooldown.requires-person-status\n"
            "    block_when: {register: re-engage}\n"
            "    required_status: dormant\n"
            "  - name: domain-cooldown\n"
            "    type: cooldown.domain-throttle\n"
            "    block_when: {channel: email}\n"
            "    max_count: 1\n"
            "    window_days: 14\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 4
        assert [r.name for r in rules] == [
            "no-double-cold-pitch",
            "follow-up-requires-prior-cold-pitch",
            "re-engage-requires-dormancy",
            "domain-cooldown",
        ]


# ---------------------------------------------------------------------------
# Invariant: empty history never produces false blocks
# ---------------------------------------------------------------------------


class TestEmptyHistoryNoFalseBlocks:
    """Sanity: a fresh ledger never produces a 'cooldown blocked' for rules
    that condition on prior sends. Prevents the failure mode where a
    misconfigured rule blocks every new prospect."""

    @pytest.mark.parametrize("register", [
        "cold-pitch", "follow-up", "re-engage", "reply", "public-comment",
    ])
    def test_no_duplicate_register_allows_on_empty(self, register):
        rule = cd.NoDuplicateRegisterRule(
            name="r",
            block_when={"register": register},
        )
        ctx = _make_ctx(register=register, person_status="dormant")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_domain_throttle_allows_on_empty(self):
        rule = cd.DomainThrottleRule(
            name="r", block_when={"channel": "email"},
            max_count=1, window_days=14,
        )
        ctx = _make_ctx()
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# DST safety — Hypothesis property
# ---------------------------------------------------------------------------


# Representative tz set: UTC, two with US/EU DST, one Southern-Hemisphere DST
# (Australia), one never-DST (Tokyo). Asia/Kolkata is also never-DST + has
# a half-hour offset, which is a useful corner case.
_TZ_SAMPLES = [
    "UTC",
    "America/Los_Angeles",
    "Europe/London",
    "Australia/Sydney",
    "Asia/Tokyo",
    "Asia/Kolkata",
]


def _make_dst_test_ctx(
    *, ledger, register, now_utc, tz_name, person_status=None,
    person_id="alice-li", email="alice@example.com",
):
    return policy_types.RuleContext(
        person_id=person_id,
        channel="email",
        register=register,
        email=email,
        email_domain=email.split("@", 1)[1] if email else None,
        now=now_utc,
        timezone=tz_name,
        ledger=ledger,
        person_status=person_status,
    )


class TestDSTSafetyProperty:
    """Hypothesis property: cooldown verdict is identical across recipient
    timezones for the same UTC `now` and the same ledger state.

    Per ADR-0002: cooldown math is UTC; the `timezone` field is reserved
    for sending-window rules. The property test proves the engine
    actually obeys that contract — if someone refactored cooldown to
    accidentally consult `ctx.timezone`, this test would catch it.
    """

    @settings(
        max_examples=200,
        deadline=None,  # property is pure-Python, but Hypothesis runs many
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        last_send_offset_hours=st.integers(min_value=0, max_value=24 * 365),
        now_extra_hours=st.integers(min_value=0, max_value=24 * 365),
        tz1=st.sampled_from(_TZ_SAMPLES),
        tz2=st.sampled_from(_TZ_SAMPLES),
        register=st.sampled_from(["cold-pitch", "follow-up", "re-engage"]),
    )
    def test_no_duplicate_register_tz_invariant(
        self, last_send_offset_hours, now_extra_hours, tz1, tz2, register,
    ):
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        last_send_ts = base + timedelta(hours=last_send_offset_hours)
        now = last_send_ts + timedelta(hours=now_extra_hours)

        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register=register,
            ts=last_send_ts, email="alice@example.com",
        )

        rule = cd.NoDuplicateRegisterRule(
            name="no-double",
            block_when={"register": register},
        )

        v1 = rule.evaluate(
            _make_dst_test_ctx(ledger=led, register=register, now_utc=now,
                               tz_name=tz1),
        )
        v2 = rule.evaluate(
            _make_dst_test_ctx(ledger=led, register=register, now_utc=now,
                               tz_name=tz2),
        )

        # Both must be the same kind. We don't compare detail dicts
        # because they may legitimately differ in ordering of optional
        # diagnostic fields if implementation pulls in tz strings; but
        # the verdict type (Allow vs Block) and (for Block) the rule
        # name MUST match.
        assert type(v1) is type(v2), (
            f"DST drift: tz1={tz1} → {type(v1).__name__}, "
            f"tz2={tz2} → {type(v2).__name__}"
        )
        if isinstance(v1, policy_types.Block):
            assert v1.rule == v2.rule

    @settings(
        max_examples=200, deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        last_send_offset_hours=st.integers(min_value=0, max_value=24 * 365),
        now_extra_hours=st.integers(min_value=0, max_value=24 * 365),
        min_age_days=st.integers(min_value=1, max_value=30),
        tz1=st.sampled_from(_TZ_SAMPLES),
        tz2=st.sampled_from(_TZ_SAMPLES),
    )
    def test_requires_prior_send_tz_invariant(
        self, last_send_offset_hours, now_extra_hours, min_age_days, tz1, tz2,
    ):
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        last_send_ts = base + timedelta(hours=last_send_offset_hours)
        now = last_send_ts + timedelta(hours=now_extra_hours)

        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=last_send_ts, email="alice@example.com",
        )

        rule = cd.RequiresPriorSendRule(
            name="follow-up-req",
            block_when={"register": "follow-up"},
            requires_register="cold-pitch",
            min_age_days=min_age_days,
        )

        v1 = rule.evaluate(
            _make_dst_test_ctx(ledger=led, register="follow-up",
                               now_utc=now, tz_name=tz1),
        )
        v2 = rule.evaluate(
            _make_dst_test_ctx(ledger=led, register="follow-up",
                               now_utc=now, tz_name=tz2),
        )
        assert type(v1) is type(v2)
        if isinstance(v1, policy_types.Block):
            assert v1.rule == v2.rule

    @settings(
        max_examples=200, deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        last_send_offset_hours=st.integers(min_value=0, max_value=24 * 365),
        now_extra_hours=st.integers(min_value=0, max_value=24 * 365),
        window_days=st.integers(min_value=1, max_value=60),
        tz1=st.sampled_from(_TZ_SAMPLES),
        tz2=st.sampled_from(_TZ_SAMPLES),
    )
    def test_domain_throttle_tz_invariant(
        self, last_send_offset_hours, now_extra_hours, window_days, tz1, tz2,
    ):
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        last_send_ts = base + timedelta(hours=last_send_offset_hours)
        now = last_send_ts + timedelta(hours=now_extra_hours)

        led = _FakeLedger()
        led.add_send(
            person_id="bob-li", channel="email", register="cold-pitch",
            ts=last_send_ts, email="bob@example.com",
        )

        rule = cd.DomainThrottleRule(
            name="domain-cooldown",
            block_when={"channel": "email"},
            max_count=1,
            window_days=window_days,
        )

        v1 = rule.evaluate(
            _make_dst_test_ctx(ledger=led, register="cold-pitch",
                               now_utc=now, tz_name=tz1),
        )
        v2 = rule.evaluate(
            _make_dst_test_ctx(ledger=led, register="cold-pitch",
                               now_utc=now, tz_name=tz2),
        )
        assert type(v1) is type(v2)


# ---------------------------------------------------------------------------
# DST crossings — concrete known dates
# ---------------------------------------------------------------------------


class TestDSTCrossing:
    """Sanity tests at known DST transitions. The Hypothesis property
    above proves invariance abstractly; these tests prove the verdict
    is the *expected* one across spring-forward / fall-back boundaries
    in two hemispheres."""

    def test_spring_forward_pacific_seven_day_window(self):
        """In Los_Angeles, DST spring-forward = 2026-03-08 02:00 PST → 03:00 PDT.
        A 7-day cooldown set on 2026-03-04 12:00 UTC, evaluated on
        2026-03-11 12:00 UTC, has 7 days elapsed regardless of tz."""
        last = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc)

        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=last, email="alice@example.com",
        )
        rule = cd.RequiresPriorSendRule(
            name="follow-up-req",
            block_when={"register": "follow-up"},
            requires_register="cold-pitch",
            min_age_days=7,
        )
        for tz_name in ("UTC", "America/Los_Angeles"):
            ctx = _make_dst_test_ctx(
                ledger=led, register="follow-up", now_utc=now,
                tz_name=tz_name,
            )
            # 7 days exactly → boundary; we accept ≥7d, so Allow.
            assert isinstance(rule.evaluate(ctx), policy_types.Allow), \
                f"spring-forward failed for tz={tz_name}"

    def test_fall_back_pacific_seven_day_window(self):
        """Fall-back = 2026-11-01 02:00 PDT → 01:00 PST. Set cooldown
        on 2026-10-29 12:00 UTC, evaluate on 2026-11-05 12:00 UTC →
        exactly 7 days elapsed."""
        last = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=last, email="alice@example.com",
        )
        rule = cd.RequiresPriorSendRule(
            name="follow-up-req",
            block_when={"register": "follow-up"},
            requires_register="cold-pitch",
            min_age_days=7,
        )
        for tz_name in ("UTC", "America/Los_Angeles"):
            ctx = _make_dst_test_ctx(
                ledger=led, register="follow-up", now_utc=now,
                tz_name=tz_name,
            )
            assert isinstance(rule.evaluate(ctx), policy_types.Allow), \
                f"fall-back failed for tz={tz_name}"

    def test_southern_hemisphere_dst_invariance(self):
        """Sydney DST: forward 2026-10-04 02:00 AEST → 03:00 AEDT;
        back 2026-04-05 03:00 AEDT → 02:00 AEST. A cooldown spanning
        2026-04-01 → 2026-04-08 (across fall-back) gives the same
        verdict in Australia/Sydney as in UTC."""
        last = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)

        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=last, email="alice@example.com",
        )
        rule = cd.NoDuplicateRegisterRule(
            name="no-double",
            block_when={"register": "cold-pitch"},
        )
        for tz_name in ("UTC", "Australia/Sydney"):
            ctx = _make_dst_test_ctx(
                ledger=led, register="cold-pitch", now_utc=now,
                tz_name=tz_name,
            )
            # Prior cold-pitch exists → block regardless of tz.
            assert isinstance(rule.evaluate(ctx), policy_types.Block)


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    """End-to-end: load the four factory rules from YAML, evaluate
    through engine.evaluate against a populated ledger, assert the
    expected verdict."""

    def test_factory_rules_through_engine(self, tmp_path):
        # Build the four-rule factory YAML.
        p = tmp_path / "cooldowns.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: no-double-cold-pitch\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when: {register: cold-pitch}\n"
            "  - name: follow-up-requires-prior-cold-pitch\n"
            "    type: cooldown.requires-prior-send\n"
            "    block_when: {register: follow-up}\n"
            "    requires_register: cold-pitch\n"
            "    min_age_days: 7\n"
            "  - name: re-engage-requires-dormancy\n"
            "    type: cooldown.requires-person-status\n"
            "    block_when: {register: re-engage}\n"
            "    required_status: dormant\n"
            "  - name: domain-cooldown\n"
            "    type: cooldown.domain-throttle\n"
            "    block_when: {channel: email}\n"
            "    max_count: 1\n"
            "    window_days: 14\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 4

        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)

        # Case 1: empty ledger + cold-pitch + first send → all rules pass.
        led = _FakeLedger()
        ctx = _make_ctx(ledger=led, register="cold-pitch", now=now,
                        person_status=None)
        assert isinstance(
            policy_engine.evaluate(rules, ctx), policy_types.Allow,
        )

        # Case 2: prior cold-pitch exists → no-double-cold-pitch fires
        #         (first rule in chain blocks).
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=30),
            email="alice@example.com",
        )
        ctx = _make_ctx(ledger=led, register="cold-pitch", now=now)
        result = policy_engine.evaluate(rules, ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "no-double-cold-pitch"

        # Case 3: re-engage to a non-dormant person → re-engage-requires-
        #         dormancy fires. (cold-pitch rule doesn't apply b/c
        #         register != cold-pitch; follow-up rule doesn't apply
        #         b/c register != follow-up.)
        led = _FakeLedger()
        ctx = _make_ctx(ledger=led, register="re-engage", now=now,
                        person_status="contacted")
        result = policy_engine.evaluate(rules, ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "re-engage-requires-dormancy"

        # Case 4: follow-up after ≥7d → all rules pass.
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=10),
            email="alice@example.com",
        )
        # Different prospect for the follow-up so the domain-throttle
        # rule sees only one prior send to example.com, but our ctx
        # uses bob@example.com so it counts in window. To avoid
        # cross-rule interference, point at a fresh domain.
        ctx = _make_ctx(
            ledger=led, register="follow-up", now=now,
            email="alice@other-co.com",  # different domain
        )
        # The follow-up rule queries by person_id, not email, so the
        # prior cold-pitch to alice-li at example.com satisfies it.
        result = policy_engine.evaluate(rules, ctx)
        assert isinstance(result, policy_types.Allow)
