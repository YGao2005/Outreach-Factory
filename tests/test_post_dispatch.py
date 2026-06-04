"""Tests for orchestrator/post_dispatch.py (the draft-and-manual dispatcher).

Operations-tier (a new advanced-channel surface, off the core send path).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator import content as c
from orchestrator import content_scheduler as cs
from orchestrator import ledger as L
from orchestrator import post_dispatch as pd
from orchestrator.policy import content_rules as cr
from orchestrator.policy.types import Allow, Block


NOW = datetime(2026, 6, 4, 17, 0, 0, tzinfo=timezone.utc)
SCHED = "2026-06-04T09:00:00.000Z"


@pytest.fixture
def led(tmp_path: Path) -> L.Ledger:
    return L.Ledger(tmp_path / "ledger")


def _cal(auto_publish=False, **channels):
    if not channels:
        channels = {"linkedin_post": {"enabled": True, "daily_cap": 1},
                    "x_post": {"enabled": True, "daily_cap": 3},
                    "reddit": {"enabled": True, "daily_cap": 1}}
    return cs.calendar_config_from_dict(
        {"enabled": True, "auto_publish": auto_publish, "channels": channels})


def _seed_approved(led, cid, channel, *, body_hash="sha256:h"):
    led.append({**c.build_content_drafted_payload(content_id=cid, source_ref="r", topic="t"),
                "type": "content_drafted"})
    led.append({**c.build_content_review_approved_payload(
        content_id=cid, channel=channel, scheduled_at=SCHED, body_hash=body_hash,
        register="post"), "type": "content_review_approved"})


class FakeClient:
    def __init__(self, postable):
        self.postable = set(postable)
        self.posted = []

    def can_post(self, channel):
        return channel in self.postable

    def post(self, channel, body, *, intent_id):
        self.posted.append((channel, body, intent_id))
        return f"post_{channel}"


class FailClient:
    def can_post(self, channel):
        return True

    def post(self, channel, body, *, intent_id):
        raise RuntimeError("boom")


def _bodies(**kv):
    # kv keyed "cid|channel" -> body
    table = {tuple(k.split("|")): v for k, v in kv.items()}
    return lambda cid, ch: table.get((cid, ch))


class TestDraftAndManual:
    def test_due_post_becomes_a_reminder_and_writes_nothing(self, led):
        _seed_approved(led, "cpc_1", "linkedin_post")
        before = len(led.all_events())
        out = pd.dispatch_due_posts(
            led, _cal(), now=NOW,
            resolve_body=_bodies(**{"cpc_1|linkedin_post": "the linkedin body"}))
        assert len(out.reminders) == 1
        r = out.reminders[0]
        assert r.channel == "linkedin_post" and r.body == "the linkedin body"
        assert "LinkedIn" in r.target_hint
        # No ledger write on the draft-and-manual path (no orphan intent).
        assert len(led.all_events()) == before
        assert c.derived_content_stage(led.all_events(), "cpc_1") == "approved"

    def test_missing_body_is_blocked_not_dropped(self, led):
        _seed_approved(led, "cpc_1", "x_post")
        out = pd.dispatch_due_posts(led, _cal(), now=NOW, resolve_body=lambda *_: None)
        assert out.reminders == []
        assert out.blocked == [{"content_id": "cpc_1", "channel": "x_post",
                                "reason": "missing_body"}]

    def test_community_reminder_flagged_manual(self, led):
        _seed_approved(led, "cpc_1", "reddit")
        out = pd.dispatch_due_posts(
            led, _cal(), now=NOW, resolve_body=_bodies(**{"cpc_1|reddit": "body"}))
        assert len(out.reminders) == 1 and out.reminders[0].requires_manual_post is True

    def test_placeholder_client_never_auto_posts_even_if_auto_publish_on(self, led):
        # auto_publish on, but the placeholder cannot post -> still a reminder.
        _seed_approved(led, "cpc_1", "x_post")
        out = pd.dispatch_due_posts(
            led, _cal(auto_publish=True), now=NOW,
            resolve_body=_bodies(**{"cpc_1|x_post": "body"}))
        assert len(out.reminders) == 1 and out.auto_posted == []


class TestPolicyGate:
    def test_gate_block_emits_policy_blocked(self, led):
        _seed_approved(led, "cpc_1", "x_post")

        def gate(action, events, now):
            return {"content_id": action.content_id, "channel": action.channel,
                    "rule": "no-double-post", "reason": "dup"}

        out = pd.dispatch_due_posts(
            led, _cal(), now=NOW, resolve_body=_bodies(**{"cpc_1|x_post": "b"}), gate=gate)
        assert out.reminders == []
        assert out.blocked[0]["rule"] == "no-double-post"
        blocked_events = [e for e in led.all_events()
                          if e.get("type") == "policy_blocked"]
        assert len(blocked_events) == 1
        assert blocked_events[0]["channel"] == "x_post"


class TestAutoPublishPath:
    def test_real_client_two_phase_commit(self, led):
        _seed_approved(led, "cpc_1", "x_post", body_hash="sha256:xx")
        client = FakeClient(postable={"x_post"})
        out = pd.dispatch_due_posts(
            led, _cal(auto_publish=True), now=NOW,
            resolve_body=_bodies(**{"cpc_1|x_post": "body"}), posting_client=client)
        assert out.auto_posted and out.auto_posted[0]["post_id"] == "post_x_post"
        assert client.posted  # the client was actually called
        assert c.derived_content_stage(led.all_events(), "cpc_1") == "posted"
        # the confirmed event carries the body_hash + post_id index works
        e = led.query_by_post_id("post_x_post", channel="x_post")
        assert e is not None and e["body_hash"] == "sha256:xx"

    def test_community_never_auto_posts_even_with_a_capable_client(self, led):
        # Structural guarantee (ADR-0082 D411(2)/D414): even auto_publish on + a
        # client that claims it can post reddit -> still a draft-and-remind.
        _seed_approved(led, "cpc_1", "reddit")
        client = FakeClient(postable={"reddit"})
        out = pd.dispatch_due_posts(
            led, _cal(auto_publish=True), now=NOW,
            resolve_body=_bodies(**{"cpc_1|reddit": "body"}), posting_client=client)
        assert out.auto_posted == []
        assert len(out.reminders) == 1 and out.reminders[0].requires_manual_post is True
        assert client.posted == []  # the client was never asked to post

    def test_client_failure_writes_distribution_failed(self, led):
        _seed_approved(led, "cpc_1", "x_post")
        out = pd.dispatch_due_posts(
            led, _cal(auto_publish=True), now=NOW,
            resolve_body=_bodies(**{"cpc_1|x_post": "body"}), posting_client=FailClient())
        assert out.auto_posted == []
        assert out.blocked[0]["reason"] == "post_failed"
        types = {e.get("type") for e in led.all_events()}
        assert "distribution_intent" in types and "distribution_failed" in types
        # a failed post is NOT posted -> still due next run (not confirmed)
        assert c.derived_content_stage(led.all_events(), "cpc_1") == "approved"


class TestConfirmManualPost:
    def test_confirm_writes_two_phase_and_marks_posted(self, led):
        _seed_approved(led, "cpc_1", "linkedin_post", body_hash="sha256:bh")
        # operator pasted it, now confirms
        iid = pd.confirm_manual_post(
            led, content_id="cpc_1", channel="linkedin_post",
            post_id="urn:li:7", body_hash="sha256:bh")
        assert iid.startswith("cont_")
        assert c.derived_content_stage(led.all_events(), "cpc_1") == "posted"
        e = led.query_by_post_id("urn:li:7", channel="linkedin_post")
        assert e is not None and e["intent_id"] == iid
        # and it drops out of the due list
        due = cs.compute_due_posts(led.all_events(), _cal(), now=NOW)
        assert not any(a.content_id == "cpc_1" and a.channel == "linkedin_post" for a in due)


# ---------------------------------------------------------------------------
# Content-post guardrails (ADR-0082 D417)
# ---------------------------------------------------------------------------


def _ctx(channel, body_hash="sha256:b", events=(), now=NOW):
    return cr.ContentRuleContext(content_id="cpc_1", channel=channel,
                                 body_hash=body_hash, register="post",
                                 now=now, events=tuple(events))


def _confirmed(channel, body_hash, ts="2026-06-04T11:00:00Z"):
    return {"type": "distribution_confirmed", "channel": channel,
            "body_hash": body_hash, "ts": ts}


class TestContentRules:
    def test_cap_blocks_at_cap_allows_under(self):
        rule = cr.PerChannelPostingCapRule({"x_post": 2})
        assert isinstance(rule.evaluate(_ctx("x_post", events=[
            _confirmed("x_post", "a")])), Allow)
        assert isinstance(rule.evaluate(_ctx("x_post", events=[
            _confirmed("x_post", "a"), _confirmed("x_post", "b")])), Block)

    def test_cap_ignores_other_channel_and_old(self):
        rule = cr.PerChannelPostingCapRule({"x_post": 1})
        # other channel + a post outside the 24h window don't count
        assert isinstance(rule.evaluate(_ctx("x_post", events=[
            _confirmed("linkedin_post", "a"),
            _confirmed("x_post", "b", ts="2026-06-01T00:00:00Z")])), Allow)

    def test_cap_unknown_channel_allows(self):
        assert isinstance(cr.PerChannelPostingCapRule({}).evaluate(_ctx("x_post")), Allow)

    def test_no_double_post(self):
        rule = cr.NoDoublePostRule()
        # same body already on this channel -> block
        assert isinstance(rule.evaluate(_ctx("x_post", body_hash="sha256:dup", events=[
            _confirmed("x_post", "sha256:dup")])), Block)
        # same body on a DIFFERENT channel -> allow (each channel is its own)
        assert isinstance(rule.evaluate(_ctx("x_post", body_hash="sha256:dup", events=[
            _confirmed("linkedin_post", "sha256:dup")])), Allow)

    def test_promo_weekly_ceiling(self):
        rule = cr.PromotionalRatioRule({"reddit": 1})
        assert isinstance(rule.evaluate(_ctx("reddit", events=[
            _confirmed("reddit", "a", ts="2026-06-03T00:00:00Z")])), Block)

    def test_load_content_rules_communities_strict(self):
        cal = cs.calendar_config_from_dict({"enabled": True, "channels": {
            "x_post": {"enabled": True, "daily_cap": 3},
            "reddit": {"enabled": True, "daily_cap": 1}}})
        rules = cr.load_content_rules(cal)
        promo = [r for r in rules if isinstance(r, cr.PromotionalRatioRule)][0]
        assert promo.weekly_caps["reddit"] == 1
        assert promo.weekly_caps["x_post"] == 15


class TestGuardrailsInDispatcher:
    def test_gate_blocks_a_cross_piece_duplicate(self, led):
        # cpc_2 is approved + due on x_post; a DIFFERENT piece (cpc_1) already
        # posted the same body to x_post. The scheduler can't see this (it dedups
        # by content_id, not body); the no-double-post GATE catches it.
        bh = c.variant_body_hash("x_post", "identical body text")
        led.append({**c.build_distribution_confirmed_payload(
            content_id="cpc_1", channel="x_post", intent_id="cont_a",
            post_id="p1", body_hash=bh), "type": "distribution_confirmed",
            "ts": "2026-06-04T08:00:00.000Z"})
        _seed_approved(led, "cpc_2", "x_post", body_hash=bh)
        cal = _cal()
        gate = cr.content_gate(cr.load_content_rules(cal))
        out = pd.dispatch_due_posts(
            led, cal, now=NOW,
            resolve_body=_bodies(**{"cpc_2|x_post": "identical body text"}), gate=gate)
        assert out.reminders == []
        assert out.blocked[0]["rule"] == "content.no-double-post"
        assert any(e.get("type") == "policy_blocked" and e.get("channel") == "x_post"
                   for e in led.all_events())
