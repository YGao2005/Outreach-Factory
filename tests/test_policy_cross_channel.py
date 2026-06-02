"""Pillar A Week 2 — cross-channel touch rule (CC-01..CC-12).

Mirrors the structure of ``tests/test_policy_cooldown.py``:

  TestCC01..TestCC10 — each row from ADR-0003 §Decision as a named class.
  TestCC11DSTSafetyProperty — Hypothesis property: cross-channel verdict
                              is independent of ``ctx.timezone``.
  TestCC12RuleOrdering — engine short-circuit holds when a cross-channel
                          rule precedes a same-channel rule.
  TestCrossChannelFromYaml — YAML round-trip and structural error rows.
  TestCC09SameChannelOverlap — load-time stderr warning when
                                ``consider_channels`` contains the firing
                                channel.

The fake ledger here adds ``add_confirmed_event`` to seed the LinkedIn-side
events the rule reads (``li_invite_confirmed`` / ``li_dm_confirmed``), in
addition to the standard ``add_send`` helper inherited in spirit from
``test_policy_cooldown.py`` for email sends.

ADR-0003 binds the rule shape; the rows below are its mandatory test rows
(CC-01..CC-12).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from orchestrator import policy as policy_pkg
from orchestrator.policy import cross_channel as cc
from orchestrator.policy import cooldown as cd
from orchestrator.policy import engine as policy_engine
from orchestrator.policy import types as policy_types


# ---------------------------------------------------------------------------
# Fake ledger — minimal LedgerLike for cross-channel tests
# ---------------------------------------------------------------------------


class _Evt(dict):
    """A dict that satisfies the duck-typed Event surface cross_channel reads."""

    @property
    def type(self):
        return self["type"]


class _FakeLedger:
    """Minimal ledger that seeds the email + LinkedIn event shapes the
    cross-channel rule joins on.

    Two seed methods:

    * ``add_send`` — email send_intent + send_confirmed pair (matches the
      shape ``cooldown.py`` already consumes; reused so test setup mirrors
      ``test_policy_cooldown.py``).
    * ``add_confirmed_event`` — a single raw ``*_confirmed`` event with an
      explicit ``type`` + ``channel``. Used to seed the LinkedIn-side
      events (``li_invite_confirmed`` / ``li_dm_confirmed``) that Pillar C
      will land — we synthesize them here so the v1 cross-channel rules
      exercise the path they'll take in production.
    """

    def __init__(self) -> None:
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
            conf_ts = (ts + timedelta(milliseconds=1)) \
                .astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            self._events.append(_Evt({
                "v": 1, "type": "send_confirmed", "ts": conf_ts,
                "intent_id": intent_id, "person_id": person_id,
                "channel": channel, "email": email,
                "gmail_message_id": f"gm_{intent_id}",
            }))
        return intent_id

    def add_confirmed_event(
        self,
        *,
        person_id: str,
        channel: str,
        event_type: str,
        ts: datetime,
        intent_id: str | None = None,
        register: str | None = None,
    ) -> str:
        """Append a raw ``*_confirmed`` event with explicit type + channel.

        Used to seed Pillar C-shaped events (``li_invite_confirmed``,
        ``li_dm_confirmed``) that the cross-channel rule queries against.
        """
        self._intent_counter += 1
        if intent_id is None:
            intent_id = f"evt_test_{self._intent_counter:06d}"
        ts_iso = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self._events.append(_Evt({
            "v": 1, "type": event_type, "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": channel,
            "register": register,
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
            ev_email = e.get("email")
            if ev_email and ev_email.lower() == email.lower():
                pid = e.get("person_id")
                if pid:
                    out.add(pid)
        return out

    def all_events(self):
        return list(self._events)


def _make_ctx(
    *,
    ledger=None,
    channel="linkedin",
    register="cold-pitch",
    person_id="alice-li",
    email=None,
    now=None,
    tz="UTC",
    person_status=None,
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


def _rule_linkedin_blocks_on_email_touch(window_days: int = 14):
    """Factory rule: fire on linkedin; consider email touches; 14d window."""
    return cc.CrossChannelTouchRule(
        name="cross-channel-email-suppresses-linkedin",
        consider_channels=["email"],
        window_days=window_days,
        block_when={"channel": "linkedin"},
        reason="Prior email touch within window; LinkedIn would look coordinated",
    )


def _rule_email_blocks_on_linkedin_touch(window_days: int = 14):
    """Factory rule: fire on email; consider linkedin touches; 14d window."""
    return cc.CrossChannelTouchRule(
        name="cross-channel-linkedin-suppresses-email",
        consider_channels=["linkedin"],
        window_days=window_days,
        block_when={"channel": "email"},
        reason="Prior LinkedIn touch within window; email would look coordinated",
    )


# ---------------------------------------------------------------------------
# CC-01 — linkedin send, empty ledger → Allow
# ---------------------------------------------------------------------------


class TestCC01EmptyLedger:
    def test_allow(self):
        rule = _rule_linkedin_blocks_on_email_touch()
        ctx = _make_ctx(channel="linkedin")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# CC-02 — linkedin send, email send_confirmed within window → Block
# ---------------------------------------------------------------------------


class TestCC02EmailTouchWithinWindowBlocksLinkedIn:
    def test_block(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3), email="alice@example.com",
        )
        rule = _rule_linkedin_blocks_on_email_touch(window_days=14)
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)

        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "cross-channel-email-suppresses-linkedin"
        # Detail carries cross-channel-specific fields (ADR-0003 §Neutral).
        assert result.detail.get("fires_on") == "linkedin"
        assert result.detail.get("considers") == ["email"]
        assert result.detail.get("prior_touch_channel") == "email"
        assert result.detail.get("window_days") == 14
        assert result.detail.get("prior_touch_ts") is not None


# ---------------------------------------------------------------------------
# CC-03 — linkedin send, email send_confirmed beyond window → Allow
# ---------------------------------------------------------------------------


class TestCC03EmailTouchBeyondWindowAllowsLinkedIn:
    def test_allow(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=30), email="alice@example.com",
        )
        rule = _rule_linkedin_blocks_on_email_touch(window_days=14)
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# CC-04 — email send, li_dm_confirmed within window → Block
# ---------------------------------------------------------------------------


class TestCC04LinkedInDmBlocksEmail:
    def test_block(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_confirmed_event(
            person_id="alice-li", channel="linkedin",
            event_type="li_dm_confirmed",
            ts=now - timedelta(days=5),
        )
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            email="alice@example.com", now=now,
        )

        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "cross-channel-linkedin-suppresses-email"
        assert result.detail.get("prior_touch_channel") == "linkedin"
        assert result.detail.get("fires_on") == "email"

    def test_li_invite_confirmed_also_blocks(self):
        """The rule must also recognize ``li_invite_confirmed`` — Pillar C
        will land both invite and DM event types and the cross-channel
        rule treats them uniformly (any ``*_confirmed`` on the considered
        channel within window blocks)."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_confirmed_event(
            person_id="alice-li", channel="linkedin",
            event_type="li_invite_confirmed",
            ts=now - timedelta(days=2),
        )
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            email="alice@example.com", now=now,
        )
        assert isinstance(rule.evaluate(ctx), policy_types.Block)


# ---------------------------------------------------------------------------
# CC-05 — linkedin send, email send_intent only (no confirmed) → Allow
# ---------------------------------------------------------------------------


class TestCC05IntentOnlyDoesNotBlock:
    """Asymmetric-failure-cost (ADR-0001 §0 / ADR-0003 I2 compliance): a
    bare ``send_intent`` may never have reached the human (it might have
    failed before delivery). Blocking on intent is a false-positive risk
    we explicitly accept missing one prior touch to avoid."""

    def test_allow(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3), email="alice@example.com",
            confirmed=False,  # send_intent only — no send_confirmed pair
        )
        rule = _rule_linkedin_blocks_on_email_touch()
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# CC-06 — boundary semantics: inclusive lower-end, matches DomainThrottle
# ---------------------------------------------------------------------------


class TestCC06BoundaryInclusiveOnLowerEnd:
    """Window is **inclusive** on the lower end — an event whose timestamp
    is exactly ``now - window_days`` is considered **inside** the window
    and blocks. An event strictly older than the cutoff is outside and
    allows. Matches ``DomainThrottleRule`` and the natural reading of
    "within N days". See ADR-0003 §Decision row CC-06.

    These tests bypass ``_FakeLedger.add_send`` (which would add a +1ms
    offset between intent and confirm timestamps) so the boundary instant
    is pinned to the exact microsecond — without this, the comparison
    operator (< vs <=) could not be distinguished by the test.
    """

    def test_at_exact_boundary_blocks(self):
        """An ``ev_ts == cutoff`` event is INSIDE the window → Block.

        Pinned directly via ``add_confirmed_event`` so the confirm ts is
        exactly ``now - 14d``, not ``now - 14d + 1ms``.
        """
        now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_confirmed_event(
            person_id="alice-li", channel="email",
            event_type="send_confirmed",
            ts=now - timedelta(days=14),
        )
        rule = _rule_linkedin_blocks_on_email_touch(window_days=14)
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        assert isinstance(rule.evaluate(ctx), policy_types.Block)

    def test_one_microsecond_past_boundary_allows(self):
        """An event strictly older than the cutoff is OUTSIDE the window
        → Allow. This is the negative half of the boundary contract."""
        now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_confirmed_event(
            person_id="alice-li", channel="email",
            event_type="send_confirmed",
            ts=now - timedelta(days=14, microseconds=1),
        )
        rule = _rule_linkedin_blocks_on_email_touch(window_days=14)
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# CC-07 — email send_confirmed at window_days - 1 second → Block
# ---------------------------------------------------------------------------


class TestCC07JustInsideWindowBlocks:
    def test_block(self):
        now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # 14d - 1s in the past: well inside window.
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=14, seconds=-1),
            email="alice@example.com",
        )
        rule = _rule_linkedin_blocks_on_email_touch(window_days=14)
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        assert isinstance(rule.evaluate(ctx), policy_types.Block)


# ---------------------------------------------------------------------------
# CC-08 — consider_channels: [] (empty) → from_yaml raises
# ---------------------------------------------------------------------------


class TestCC08EmptyConsiderChannelsRaises:
    def test_raises(self):
        spec = {
            "name": "x",
            "type": "cooldown.cross-channel-touch",
            "block_when": {"channel": "linkedin"},
            "consider_channels": [],
            "window_days": 14,
        }
        with pytest.raises(ValueError, match="consider_channels"):
            cc.CrossChannelTouchRule.from_yaml(spec)

    def test_missing_consider_channels_raises(self):
        spec = {
            "name": "x",
            "type": "cooldown.cross-channel-touch",
            "block_when": {"channel": "linkedin"},
            "window_days": 14,
        }
        with pytest.raises(ValueError, match="consider_channels"):
            cc.CrossChannelTouchRule.from_yaml(spec)

    def test_missing_window_days_raises(self):
        spec = {
            "name": "x",
            "type": "cooldown.cross-channel-touch",
            "block_when": {"channel": "linkedin"},
            "consider_channels": ["email"],
        }
        with pytest.raises(ValueError, match="window_days"):
            cc.CrossChannelTouchRule.from_yaml(spec)


# ---------------------------------------------------------------------------
# CC-09 — consider_channels contains firing channel → stderr warning, loads
# ---------------------------------------------------------------------------


class TestCC09SameChannelOverlap:
    """The user may want a rule that fires on email and queries email
    events too (e.g. for a custom semantic the same-channel cooldown
    rules don't cover). We do NOT block this — we warn so a typo
    (forgot to swap the channel) doesn't silently mask same-channel
    rule coverage."""

    def test_loads_with_stderr_warning(self, capsys):
        spec = {
            "name": "self-loop-allowed",
            "type": "cooldown.cross-channel-touch",
            "block_when": {"channel": "email"},
            "consider_channels": ["email"],
            "window_days": 7,
        }
        rule = cc.CrossChannelTouchRule.from_yaml(spec)
        captured = capsys.readouterr()
        # Rule loads — does not raise.
        assert rule.name == "self-loop-allowed"
        # And a warning is on stderr mentioning the overlap.
        assert "self-loop-allowed" in captured.err
        assert "email" in captured.err

    def test_distinct_channels_no_warning(self, capsys):
        spec = {
            "name": "distinct",
            "type": "cooldown.cross-channel-touch",
            "block_when": {"channel": "linkedin"},
            "consider_channels": ["email"],
            "window_days": 7,
        }
        cc.CrossChannelTouchRule.from_yaml(spec)
        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# CC-10 — consider_channels: [email, twitter] → block if either has touch
# ---------------------------------------------------------------------------


class TestCC10MultipleConsiderChannels:
    def test_block_via_email(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3), email="alice@example.com",
        )
        rule = cc.CrossChannelTouchRule(
            name="multi-channel-suppresses-linkedin",
            consider_channels=["email", "twitter"],
            window_days=14,
            block_when={"channel": "linkedin"},
        )
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("prior_touch_channel") == "email"

    def test_block_via_twitter(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_confirmed_event(
            person_id="alice-li", channel="twitter",
            event_type="tw_dm_confirmed",
            ts=now - timedelta(days=4),
        )
        rule = cc.CrossChannelTouchRule(
            name="multi-channel-suppresses-linkedin",
            consider_channels=["email", "twitter"],
            window_days=14,
            block_when={"channel": "linkedin"},
        )
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.detail.get("prior_touch_channel") == "twitter"

    def test_allow_when_neither_in_window(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=30), email="alice@example.com",
        )
        rule = cc.CrossChannelTouchRule(
            name="multi",
            consider_channels=["email", "twitter"],
            window_days=14,
            block_when={"channel": "linkedin"},
        )
        ctx = _make_ctx(ledger=led, channel="linkedin", now=now)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# CC-11 — Hypothesis property: verdict independent of ctx.timezone
# ---------------------------------------------------------------------------


_TZ_SAMPLES = [
    "UTC",
    "America/Los_Angeles",
    "Europe/London",
    "Australia/Sydney",
    "Asia/Tokyo",
    "Asia/Kolkata",
]


class TestCC11DSTSafetyProperty:
    """Inherits the ADR-0002 DST guarantee: cross-channel age math is UTC,
    so the verdict cannot depend on ``ctx.timezone``. If a refactor ever
    reaches for ``ctx.timezone``, this property test catches it."""

    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        prior_offset_hours=st.integers(min_value=0, max_value=24 * 365),
        now_extra_hours=st.integers(min_value=1, max_value=24 * 365),
        window_days=st.integers(min_value=1, max_value=60),
        tz1=st.sampled_from(_TZ_SAMPLES),
        tz2=st.sampled_from(_TZ_SAMPLES),
    )
    def test_cross_channel_tz_invariant(
        self, prior_offset_hours, now_extra_hours, window_days, tz1, tz2,
    ):
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        prior_ts = base + timedelta(hours=prior_offset_hours)
        now = prior_ts + timedelta(hours=now_extra_hours)

        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=prior_ts, email="alice@example.com",
        )
        rule = cc.CrossChannelTouchRule(
            name="cross-channel-email-suppresses-linkedin",
            consider_channels=["email"],
            window_days=window_days,
            block_when={"channel": "linkedin"},
        )

        v1 = rule.evaluate(_make_ctx(
            ledger=led, channel="linkedin", now=now, tz=tz1,
        ))
        v2 = rule.evaluate(_make_ctx(
            ledger=led, channel="linkedin", now=now, tz=tz2,
        ))
        assert type(v1) is type(v2), (
            f"DST drift: tz1={tz1} → {type(v1).__name__}, "
            f"tz2={tz2} → {type(v2).__name__}"
        )
        if isinstance(v1, policy_types.Block):
            assert v1.rule == v2.rule


# ---------------------------------------------------------------------------
# CC-12 — rule ordering: cross-channel before same-channel → first Block wins
# ---------------------------------------------------------------------------


class TestCC12RuleOrderingShortCircuit:
    """If both a cross-channel and a same-channel rule would block, the
    one listed first in the YAML wins. (Engine short-circuit per ADR-0001.)"""

    def test_cross_channel_first_wins(self):
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # An email touch 3d ago — cross-channel rule would block linkedin.
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3), email="alice@example.com",
        )
        # A prior linkedin cold-pitch — same-channel no-duplicate rule
        # would ALSO block this linkedin cold-pitch.
        led.add_send(
            person_id="alice-li", channel="linkedin", register="cold-pitch",
            ts=now - timedelta(days=30),
        )

        cross_rule = _rule_linkedin_blocks_on_email_touch(window_days=14)
        same_rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch", "channel": "linkedin"},
        )

        ctx = _make_ctx(
            ledger=led, channel="linkedin", register="cold-pitch", now=now,
        )
        result = policy_engine.evaluate([cross_rule, same_rule], ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "cross-channel-email-suppresses-linkedin"

    def test_same_channel_first_wins(self):
        """Reversed ordering — same-channel rule fires first."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3), email="alice@example.com",
        )
        led.add_send(
            person_id="alice-li", channel="linkedin", register="cold-pitch",
            ts=now - timedelta(days=30),
        )
        cross_rule = _rule_linkedin_blocks_on_email_touch(window_days=14)
        same_rule = cd.NoDuplicateRegisterRule(
            name="no-double-cold-pitch",
            block_when={"register": "cold-pitch", "channel": "linkedin"},
        )
        ctx = _make_ctx(
            ledger=led, channel="linkedin", register="cold-pitch", now=now,
        )
        result = policy_engine.evaluate([same_rule, cross_rule], ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "no-double-cold-pitch"


# ---------------------------------------------------------------------------
# YAML round-trip and registry integration
# ---------------------------------------------------------------------------


class TestCrossChannelFromYaml:
    def test_round_trip(self):
        spec = {
            "name": "cross-channel-email-suppresses-linkedin",
            "type": "cooldown.cross-channel-touch",
            "block_when": {"channel": "linkedin"},
            "consider_channels": ["email"],
            "window_days": 14,
            "reason": "...",
        }
        rule = cc.CrossChannelTouchRule.from_yaml(spec)
        assert rule.name == "cross-channel-email-suppresses-linkedin"
        assert rule.consider_channels == ["email"]
        assert rule.window_days == 14
        assert rule.block_when == {"channel": "linkedin"}

    def test_registered_under_discriminator(self):
        assert policy_engine.RULE_REGISTRY.get(
            "cooldown.cross-channel-touch"
        ) is cc.CrossChannelTouchRule

    def test_load_rules_from_yaml_integrates(self, tmp_path):
        p = tmp_path / "cooldowns.yml"
        p.write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: cross-channel-email-suppresses-linkedin\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when: {channel: linkedin}\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            "  - name: cross-channel-linkedin-suppresses-email\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when: {channel: email}\n"
            "    consider_channels: [linkedin]\n"
            "    window_days: 14\n",
            encoding="utf-8",
        )
        rules = policy_engine.load_rules_from_yaml(p)
        assert len(rules) == 2
        assert all(isinstance(r, cc.CrossChannelTouchRule) for r in rules)


# ---------------------------------------------------------------------------
# Sanity: empty ledger + cross-channel rules → no false blocks
# ---------------------------------------------------------------------------


class TestEmptyHistoryNoFalseBlocks:
    """Greenfield install: factory rules ship but no LinkedIn events
    have landed (pre-Pillar C). Cross-channel rules must return Allow
    in that state — same as fresh same-channel cooldown rules."""

    def test_linkedin_allows_with_no_email(self):
        rule = _rule_linkedin_blocks_on_email_touch()
        ctx = _make_ctx(channel="linkedin")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_email_allows_with_no_linkedin(self):
        rule = _rule_email_blocks_on_linkedin_touch()
        ctx = _make_ctx(channel="email", email="alice@example.com")
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_block_when_channel_filter_skips_other_channel(self):
        """Rule scoped to linkedin doesn't fire on an email send, even
        with prior email touches that would otherwise match its
        consider_channels."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        led.add_send(
            person_id="alice-li", channel="email", register="cold-pitch",
            ts=now - timedelta(days=3), email="alice@example.com",
        )
        rule = _rule_linkedin_blocks_on_email_touch()
        # ctx is for an email send — the rule fires on linkedin only.
        ctx = _make_ctx(ledger=led, channel="email",
                        email="alice@example.com", now=now)
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# Pillar C Week 2 — rule firing against the live `li_invite_*` event shape
# ---------------------------------------------------------------------------


class TestCrossChannelAgainstLiveLinkedInInviteShape:
    """The synthetic-event tests above (CC-01..CC-12) construct ad-hoc
    in-memory events. Pillar C Week 2 ships the dispatcher
    (``gated_li_invite_one``) that emits ``li_invite_intent`` +
    ``li_invite_confirmed`` events with the full Week-2 field set
    (``linkedin_url``, ``linkedin_invitation_id``, ``register``,
    etc.). These rows assert the cross-channel rule treats those
    live-shape events identically — the rule looks only at
    ``type``, ``channel``, ``ts`` per ADR-0003 §Decision; any
    additional dispatcher-emitted fields are ignored.

    The contract is forward-compatibility — future Week 2+ dispatcher
    changes that add fields to the live event shape must not change
    cross-channel rule semantics. These tests pin that contract.
    """

    def _seed_live_shape_confirmed(
        self,
        led: _FakeLedger,
        *,
        person_id: str,
        ts: datetime,
        intent_id: str = "li_live_001",
        linkedin_url: str = "in/alice-test",
        invitation_id: str | None = "li-inv-001",
    ) -> str:
        """Seed a li_invite_confirmed event with the full Week 2
        dispatcher-emitted field set. Used to verify the rule
        ignores fields it doesn't care about."""
        ts_iso = ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        evt = _Evt({
            "v": 1, "type": "li_invite_confirmed", "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": "linkedin",
            "linkedin_url": linkedin_url,
        })
        if invitation_id:
            evt["linkedin_invitation_id"] = invitation_id
        led._events.append(evt)
        return intent_id

    def test_live_shape_li_invite_confirmed_blocks_email_within_window(self):
        """An email send is blocked by a recent li_invite_confirmed
        carrying the Week 2 dispatcher's full field set."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        self._seed_live_shape_confirmed(
            led, person_id="alice-li",
            ts=now - timedelta(days=3),
            linkedin_url="in/alice-real",
            invitation_id="li-inv-xyz-789",
        )
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            email="alice@example.com", now=now,
        )
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "cross-channel-linkedin-suppresses-email"
        assert result.detail.get("prior_touch_channel") == "linkedin"
        # The rule's detail should expose the prior_touch_type so the
        # operator can debug which kind of LinkedIn event blocked.
        assert result.detail.get("prior_touch_type") == "li_invite_confirmed"

    def test_live_shape_li_invite_confirmed_outside_window_allows_email(self):
        """An email send is allowed when the only li_invite_confirmed
        is outside the window."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        self._seed_live_shape_confirmed(
            led, person_id="alice-li",
            ts=now - timedelta(days=30),  # beyond window.
        )
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            email="alice@example.com", now=now,
        )
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_live_shape_li_invite_intent_only_does_not_block(self):
        """A bare li_invite_intent (no confirmed) does NOT block — same
        asymmetric-cost rationale as email send_intent (ADR-0001 §0).

        The Pillar C Week 2 dispatcher writes intent BEFORE the MCP
        call; if the MCP fails or the process crashes, the intent is
        alone in the ledger. The cross-channel rule must treat this
        case as Allow — the operator hasn't actually engaged the
        recipient yet."""
        now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        # Seed only an intent, no confirmed.
        ts_iso = (now - timedelta(days=2)).isoformat() \
            .replace("+00:00", "Z")
        led._events.append(_Evt({
            "v": 1, "type": "li_invite_intent", "ts": ts_iso,
            "intent_id": "li_orphan_001", "person_id": "alice-li",
            "channel": "linkedin",
            "linkedin_url": "in/alice-test",
        }))
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            email="alice@example.com", now=now,
        )
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)


# ---------------------------------------------------------------------------
# Cross-channel rule against live LinkedIn DM event shape (Pillar C Week 3)
# ---------------------------------------------------------------------------


class TestCrossChannelAgainstLiveLinkedInDMShape:
    """Pillar C Week 3 ships the LinkedIn DM dispatcher
    (``gated_li_dm_one``) that emits ``li_dm_intent`` +
    ``li_dm_confirmed`` events with the full Week-3 field set
    (``linkedin_url``, ``linkedin_thread_id``, ``register``, etc.).
    These rows assert the cross-channel rule treats DM events
    identically to invite events — the rule looks only at ``type``,
    ``channel``, ``ts`` per ADR-0003 §Decision; the event-type prefix
    (``li_invite_`` vs ``li_dm_``) is opaque to the rule.

    The forward-compatibility contract: future Week 3+ dispatcher
    changes that add fields to the live event shape must not change
    cross-channel rule semantics. These tests pin that contract.
    """

    def _seed_live_shape_li_dm_confirmed(
        self,
        led: _FakeLedger,
        *,
        person_id: str,
        ts: datetime,
        intent_id: str = "lidm_live_001",
        linkedin_url: str = "in/dana-test",
        thread_id: str | None = "li-thread-001",
    ) -> str:
        """Seed a li_dm_confirmed event with the full Week 3
        dispatcher-emitted field set."""
        ts_iso = ts.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
        evt = _Evt({
            "v": 1, "type": "li_dm_confirmed", "ts": ts_iso,
            "intent_id": intent_id, "person_id": person_id,
            "channel": "linkedin",
            "linkedin_url": linkedin_url,
        })
        if thread_id:
            evt["linkedin_thread_id"] = thread_id
        led._events.append(evt)
        return intent_id

    def test_live_shape_li_dm_confirmed_blocks_email_within_window(self):
        """An email send is blocked by a recent li_dm_confirmed
        carrying the Week 3 dispatcher's full field set."""
        now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        self._seed_live_shape_li_dm_confirmed(
            led, person_id="dana-li",
            ts=now - timedelta(days=3),
            linkedin_url="in/dana-real",
            thread_id="li-thread-xyz-789",
        )
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            person_id="dana-li",
            email="dana@example.com", now=now,
        )
        result = rule.evaluate(ctx)
        assert isinstance(result, policy_types.Block)
        assert result.rule == "cross-channel-linkedin-suppresses-email"
        assert result.detail.get("prior_touch_channel") == "linkedin"
        # The rule's detail exposes prior_touch_type so the operator
        # can debug which kind of LinkedIn event blocked. li_dm_*
        # surfaces here distinctly from li_invite_*.
        assert result.detail.get("prior_touch_type") == "li_dm_confirmed"

    def test_live_shape_li_dm_confirmed_outside_window_allows_email(self):
        """An email send is allowed when the only li_dm_confirmed is
        outside the window."""
        now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        self._seed_live_shape_li_dm_confirmed(
            led, person_id="dana-li",
            ts=now - timedelta(days=30),  # beyond window.
        )
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            person_id="dana-li",
            email="dana@example.com", now=now,
        )
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)

    def test_live_shape_li_dm_intent_only_does_not_block(self):
        """A bare li_dm_intent (no confirmed) does NOT block — same
        asymmetric-cost rationale as email send_intent + LinkedIn
        invite intent (ADR-0001 §0).

        The Pillar C Week 3 dispatcher writes intent BEFORE the MCP
        call; if the MCP fails or the process crashes, the intent is
        alone in the ledger. The cross-channel rule must treat this
        case as Allow."""
        now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
        led = _FakeLedger()
        ts_iso = (now - timedelta(days=2)).isoformat() \
            .replace("+00:00", "Z")
        led._events.append(_Evt({
            "v": 1, "type": "li_dm_intent", "ts": ts_iso,
            "intent_id": "lidm_orphan_001", "person_id": "dana-li",
            "channel": "linkedin",
            "linkedin_url": "in/dana-test",
        }))
        rule = _rule_email_blocks_on_linkedin_touch(window_days=14)
        ctx = _make_ctx(
            ledger=led, channel="email",
            person_id="dana-li",
            email="dana@example.com", now=now,
        )
        assert isinstance(rule.evaluate(ctx), policy_types.Allow)
