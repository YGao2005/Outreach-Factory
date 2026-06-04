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
