"""Golden-path liveness for the content-distribution surface (Phase 1, ADR-0082).

The cold side has L0 spine liveness for enroll -> draft -> send -> reconcile.
This is the broadcast spine's Phase 1 liveness: a source candidate's salience ->
a hub-and-spoke piece that passes the adaptation refusal -> ledger drafted +
approved -> the deterministic scheduler surfaces it as DUE -> a (mocked)
distribution_confirmed -> the derived stage is ``posted`` and it drops out of the
due list -> the report counts it. Phase 1 has a MOCKED dispatcher, so this proves
everything up to and including the two-phase confirm without a live channel call.

The FULL Phase 5 binding criterion (the guardrail BLOCKS an over-cap + duplicate
post; an engagement ingest flows into the optimization report from a real
reconcile pass; a community channel NEVER auto-posts via a structurally-absent
code path) lands at Phase 5 per ADR-0082 D412. The pieces that EXIST at Phase 1
are pinned here: the scheduler's cap math, the rejection cancel, the
community-flagged-manual marker, and the adaptation refusal.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from orchestrator import content as c
from orchestrator import content_scheduler as cs


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _enabled_calendar():
    return cs.calendar_config_from_dict({
        "enabled": True,
        "channels": {
            "linkedin_post": {"enabled": True, "daily_cap": 1},
            "x_post": {"enabled": True, "daily_cap": 3},
            "reddit": {"enabled": True, "daily_cap": 1},
        },
    })


class TestGoldenPathContentDistribution:
    def test_source_to_due_to_posted_spine(self, tmp_ledger, golden_now):
        """The Phase 1 broadcast spine is live end to end (mocked dispatcher)."""
        # 1. A codebase source surfaces an announce-worthy ship via salience.
        kept = c.select_shipped_features(
            [{"sha": "abc123", "subject": "feat: lineage tracking"},
             {"sha": "def456", "subject": "chore: deps"}]
        )
        assert [k.sha for k in kept] == ["abc123"]

        # 2. The generation step produces ONE canonical + distinct projections;
        #    the hub-and-spoke adaptation refusal passes (re-expressions, not clips).
        cid = c.new_content_id()
        canonical = (
            "We shipped lineage tracking. Every prospect now carries the discovery "
            "source it came from, so duplicate outreach dies at the root and "
            "attribution stops being a guess."
        )
        piece = c.ContentPiece(
            content_id=cid, source_ref="abc123", topic="lineage", canonical=canonical,
            variants=(
                c.ContentVariant("linkedin_post", "post",
                                 "Shipped lineage tracking today. Each prospect now points "
                                 "back to where we found it, which quietly kills duplicate "
                                 "outreach and makes attribution honest."),
                c.ContentVariant("x_post", "post",
                                 "new: lineage tracking. every prospect points to its "
                                 "discovery source. dedup gets trivial, attribution stops "
                                 "lying."),
            ),
        )
        c.validate_adaptation(piece)

        # 3. Ledger: drafted -> humanized -> per-channel approved (scheduled in the past).
        sched = _iso(golden_now - timedelta(hours=2))
        tmp_ledger.append(
            {**c.build_content_drafted_payload(content_id=cid, source_ref="abc123",
                                               topic="lineage"), "type": "content_drafted"})
        tmp_ledger.append(
            {**c.build_content_humanized_payload(content_id=cid), "type": "content_humanized"})
        for v in piece.variants:
            tmp_ledger.append({
                **c.build_content_review_approved_payload(
                    content_id=cid, channel=v.channel, scheduled_at=sched,
                    body_hash=v.body_hash, register=v.register),
                "type": "content_review_approved"})

        assert c.derived_content_stage(tmp_ledger.all_events(), cid) == "approved"

        # 4. The deterministic scheduler surfaces both channels as DUE.
        cal = _enabled_calendar()
        due = cs.compute_due_posts_from_ledger(tmp_ledger, cal, now=golden_now)
        assert {a.channel for a in due} == {"linkedin_post", "x_post"}
        assert all(a.source_ref == "abc123" for a in due)
        assert all(a.requires_manual_post is False for a in due)

        # 5. Mock the dispatcher confirming the linkedin post (the two-phase confirm).
        tmp_ledger.append({
            **c.build_distribution_confirmed_payload(
                content_id=cid, channel="linkedin_post",
                intent_id=c.new_distribution_intent_id(), post_id="li_urn_998",
                body_hash=piece.variant_for("linkedin_post").body_hash),
            "type": "distribution_confirmed"})

        # 6. The posted channel drops out; the piece's stage is now terminal.
        due2 = cs.compute_due_posts_from_ledger(tmp_ledger, cal, now=golden_now)
        assert {a.channel for a in due2} == {"x_post"}
        assert c.derived_content_stage(tmp_ledger.all_events(), cid) == "posted"

        # 7. The report counts the confirmed post; no engagement yet -> honest "none".
        report = cs.build_content_report(tmp_ledger.all_events(), now=golden_now)
        assert report["posts"]["by_channel"]["linkedin_post"] == 1
        assert report["engagement"]["signal"] == "none"

    def test_community_post_is_flagged_manual_never_auto(self, tmp_ledger, golden_now):
        """A due community post is surfaced but flagged requires_manual_post.

        The dispatcher (Phase 2) has no auto-post path for communities; the
        scheduler marks the worklist so that guarantee is legible from Phase 1.
        """
        cid = c.new_content_id()
        sched = _iso(golden_now - timedelta(hours=1))
        tmp_ledger.append(
            {**c.build_content_drafted_payload(content_id=cid, source_ref="abc",
                                               topic="t"), "type": "content_drafted"})
        tmp_ledger.append({
            **c.build_content_review_approved_payload(
                content_id=cid, channel="reddit", scheduled_at=sched,
                body_hash="sha256:rd", register="post"),
            "type": "content_review_approved"})
        due = cs.compute_due_posts_from_ledger(tmp_ledger, _enabled_calendar(), now=golden_now)
        reddit = [a for a in due if a.channel == "reddit"]
        assert len(reddit) == 1 and reddit[0].requires_manual_post is True

    def test_scheduler_is_read_only(self, tmp_ledger, golden_now):
        """The scheduler walk appends nothing to the ledger (read-only contract)."""
        cid = c.new_content_id()
        tmp_ledger.append({
            **c.build_content_review_approved_payload(
                content_id=cid, channel="x_post",
                scheduled_at=_iso(golden_now - timedelta(hours=1)),
                body_hash="sha256:h", register="post"),
            "type": "content_review_approved"})
        before = len(tmp_ledger.all_events())
        cs.compute_due_posts_from_ledger(tmp_ledger, _enabled_calendar(), now=golden_now)
        cs.build_content_report(tmp_ledger.all_events(), now=golden_now)
        assert len(tmp_ledger.all_events()) == before


# ---------------------------------------------------------------------------
# Phase 2 binding criterion (ADR-0082 D413-D417): the draft-and-manual loop
# ---------------------------------------------------------------------------

from orchestrator import post_dispatch as pd  # noqa: E402
from orchestrator import content_reconcile as crx  # noqa: E402
from orchestrator.policy import content_rules as cr  # noqa: E402


class TestGoldenPathContentPhase2:
    """The full draft-and-manual broadcast loop, end to end against the real
    dispatcher + guardrails + reconcile + report. Pins ADR-0082 D413-D417:
    no auto-post (human-gated), the guardrail blocks a duplicate, the manual
    confirm posts, engagement flows into the report, communities never auto-post.
    """

    def _approve(self, led, cid, channel, sched, *, body_hash):
        led.append({**c.build_content_drafted_payload(content_id=cid, source_ref="abc",
                                                       topic="t"), "type": "content_drafted"})
        led.append({**c.build_content_review_approved_payload(
            content_id=cid, channel=channel, scheduled_at=sched, body_hash=body_hash,
            register="post"), "type": "content_review_approved"})

    def test_draft_and_manual_loop(self, tmp_ledger, golden_now):
        cal = cs.calendar_config_from_dict({"enabled": True, "auto_publish": False,
            "channels": {"linkedin_post": {"enabled": True, "daily_cap": 1},
                         "reddit": {"enabled": True, "daily_cap": 1}}})
        sched = _iso(golden_now - timedelta(hours=1))
        li_body = "Shipped lineage tracking. Every prospect now carries its source."
        li_hash = c.variant_body_hash("linkedin_post", li_body)
        self._approve(tmp_ledger, "cpc_1", "linkedin_post", sched, body_hash=li_hash)
        self._approve(tmp_ledger, "cpc_1", "reddit", sched,
                      body_hash=c.variant_body_hash("reddit", "r/ML: we shipped lineage"))

        gate = cr.content_gate(cr.load_content_rules(cal))
        bodies = {("cpc_1", "linkedin_post"): li_body,
                  ("cpc_1", "reddit"): "r/ML: we shipped lineage"}

        # 1. Dispatch: draft-and-manual for BOTH channels, NO ledger writes, no auto-post.
        before = len(tmp_ledger.all_events())
        out = pd.dispatch_due_posts(tmp_ledger, cal, now=golden_now,
                                    resolve_body=lambda cid, ch: bodies.get((cid, ch)),
                                    gate=gate)
        assert {r.channel for r in out.reminders} == {"linkedin_post", "reddit"}
        assert out.auto_posted == []
        # community reminder is flagged manual (structural never-auto-post)
        assert any(r.channel == "reddit" and r.requires_manual_post for r in out.reminders)
        assert len(tmp_ledger.all_events()) == before  # no orphan intents written

        # 2. The operator posts the LinkedIn one and confirms it.
        pd.confirm_manual_post(tmp_ledger, content_id="cpc_1", channel="linkedin_post",
                               post_id="urn:li:7", body_hash=li_hash)
        assert c.derived_content_stage(tmp_ledger.all_events(), "cpc_1") == "posted"
        # it drops out of the due list
        due = cs.compute_due_posts(tmp_ledger.all_events(), cal, now=golden_now)
        assert not any(a.channel == "linkedin_post" for a in due)

        # 3. The guardrail BLOCKS a different piece reusing the same body on the
        #    same channel (the scheduler dedups by content_id, not body).
        self._approve(tmp_ledger, "cpc_2", "linkedin_post",
                      _iso(golden_now - timedelta(hours=1)), body_hash=li_hash)
        cal2 = cs.calendar_config_from_dict({"enabled": True, "auto_publish": False,
            "channels": {"linkedin_post": {"enabled": True, "daily_cap": 5}}})  # cap won't block
        out2 = pd.dispatch_due_posts(tmp_ledger, cal2, now=golden_now,
                                     resolve_body=lambda cid, ch: li_body,
                                     gate=cr.content_gate(cr.load_content_rules(cal2)))
        assert not any(r.content_id == "cpc_2" for r in out2.reminders)
        assert any(b["rule"] == "content.no-double-post" for b in out2.blocked)
        assert any(e.get("type") == "policy_blocked" for e in tmp_ledger.all_events())

        # 4. Engagement ingest (delta) flows into the report.
        crx.ingest_engagement(tmp_ledger, content_id="cpc_1", channel="linkedin_post",
                              scraped_metrics={"likes": 30, "comments": 4},
                              observed_at=_iso(golden_now))
        report = cs.build_content_report(tmp_ledger.all_events(), now=golden_now)
        assert report["engagement"]["signal"] == "present"
        assert report["engagement"]["by_channel"]["linkedin_post"]["likes"] == 30
        assert report["posts"]["by_channel"]["linkedin_post"] == 1
