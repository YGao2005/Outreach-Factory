"""Phase 1 tests for the content-distribution surface (ADR-0082).

Covers the entity + typed source registry + the codebase salience selector (the
one net-new primitive) + the hub-and-spoke adaptation refusal + the refuse-loud
event builders + the derived-stage walk (content.py), and the read-only
scheduler's eligibility math + the optimization report (content_scheduler.py).

Operations-tier (a new advanced-channel surface, off the core send path) per the
conftest auto-marker.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orchestrator import content as c
from orchestrator import content_scheduler as cs
from orchestrator.observability import EVENT_CLASS_CATALOG


NOW = datetime(2026, 6, 4, 17, 0, 0, tzinfo=timezone.utc)


def _ev(payload: dict, *, type: str, ts: str) -> dict:
    return {**payload, "type": type, "ts": ts}


# ---------------------------------------------------------------------------
# The codebase salience selector (the one net-new primitive, ADR-0082 D410)
# ---------------------------------------------------------------------------


class TestSalienceSelector:
    def test_keeps_feat_and_release_drops_the_rest(self):
        commits = [
            {"sha": "a1", "subject": "feat: add lineage primitive"},
            {"sha": "a2", "subject": "feat(api): citation endpoint"},
            {"sha": "b1", "subject": "chore: bump deps"},
            {"sha": "b2", "subject": "docs: tidy readme"},
            {"sha": "b3", "subject": "fix(api): null guard"},
            {"sha": "b4", "subject": "refactor: split module"},
            {"sha": "b5", "subject": "just some words no type"},
            {"sha": "c1", "subject": "cut release", "tags": ["v1.2.0"]},
        ]
        kept = c.select_shipped_features(commits)
        assert {k.sha for k in kept} == {"a1", "a2", "c1"}

    def test_release_tag_reason_and_feat_reason(self):
        kept = c.select_shipped_features(
            [
                {"sha": "a1", "subject": "feat: x"},
                {"sha": "c1", "subject": "rel", "tags": ["v2.0.0"]},
            ]
        )
        by_sha = {k.sha: k.salience_reason for k in kept}
        assert "feat" in by_sha["a1"]
        assert "v2.0.0" in by_sha["c1"]

    def test_breaking_change_bang_still_kept_when_feat(self):
        kept = c.select_shipped_features([{"sha": "a1", "subject": "feat(core)!: rework"}])
        assert [k.sha for k in kept] == ["a1"]

    def test_missing_sha_or_subject_skipped(self):
        kept = c.select_shipped_features(
            [{"sha": "", "subject": "feat: x"}, {"sha": "a", "subject": ""}]
        )
        assert kept == []

    def test_custom_feature_types(self):
        kept = c.select_shipped_features(
            [{"sha": "a1", "subject": "ship: new thing"}],
            feature_types=frozenset({"ship"}),
        )
        assert [k.sha for k in kept] == ["a1"]


class TestPaperFilter:
    def test_rank_age_topic_filter(self):
        papers = [
            {"arxiv_id": "1", "title": "A survey of agents", "rank": 0.9,
             "published": "2026-06-02T00:00:00Z", "categories": ["cs.AI"]},
            {"arxiv_id": "2", "title": "Low rank", "rank": 0.5,
             "published": "2026-06-02T00:00:00Z"},
            {"arxiv_id": "3", "title": "Stale high rank", "rank": 0.95,
             "published": "2026-01-02T00:00:00Z"},
            {"arxiv_id": "4", "title": "High rank off topic", "rank": 0.95,
             "published": "2026-06-03T00:00:00Z", "categories": ["q-bio"]},
        ]
        got = c.filter_papers(papers, min_rank=0.85, max_age_days=7,
                              topics=("agents",), now=NOW)
        assert [g.ref for g in got] == ["1"]

    def test_no_topics_keeps_all_fresh_high_rank(self):
        papers = [
            {"arxiv_id": "1", "title": "x", "rank": 0.9, "published": "2026-06-03T00:00:00Z"},
            {"arxiv_id": "2", "title": "y", "rank": 0.9, "published": "2026-06-03T00:00:00Z"},
        ]
        got = c.filter_papers(papers, min_rank=0.85, max_age_days=7, now=NOW)
        assert {g.ref for g in got} == {"1", "2"}

    def test_missing_date_is_kept_age_unknown(self):
        # No readable date -> not aged out (the filter does not fabricate a date).
        got = c.filter_papers(
            [{"arxiv_id": "1", "title": "x", "rank": 0.9}],
            min_rank=0.85, max_age_days=7, now=NOW,
        )
        assert [g.ref for g in got] == ["1"]


# ---------------------------------------------------------------------------
# The typed source registry (ADR-0082 D410)
# ---------------------------------------------------------------------------


class TestSourceRegistry:
    def test_parses_codebase_and_paper_feed(self):
        srcs = c.content_sources_from_config([
            {"id": "ships", "type": "codebase", "repo": "../scholarfeed",
             "salience": "shipped_feature", "since": "last_post",
             "registers": ["linkedin_post", "x_thread"]},
            {"id": "papers", "type": "paper_feed", "provider": "scholarfeed_mcp",
             "filter": {"min_rank": 0.85, "max_age_days": 7, "topics": ["agents"]},
             "registers": ["x_post"]},
        ])
        assert isinstance(srcs[0], c.CodebaseSource)
        assert srcs[0].salience == "shipped_feature"
        assert isinstance(srcs[1], c.PaperFeedSource)
        assert srcs[1].min_rank == 0.85 and srcs[1].max_age_days == 7

    def test_none_and_empty(self):
        assert c.content_sources_from_config(None) == []
        assert c.content_sources_from_config([]) == []

    @pytest.mark.parametrize("bad", [
        [{"id": "x", "type": "nope"}],
        [{"type": "codebase", "repo": "r"}],                       # missing id
        [{"id": "x", "type": "codebase"}],                          # missing repo
        [{"id": "x", "type": "codebase", "repo": "r", "salience": "magic"}],
        [{"id": "a", "type": "codebase", "repo": "r"},
         {"id": "a", "type": "codebase", "repo": "r"}],             # dup id
        [{"id": "x", "type": "paper_feed", "filter": {"min_rank": 2.0}}],
        [{"id": "x", "type": "paper_feed", "filter": {"max_age_days": 0}}],
        [{"id": "x", "type": "codebase", "repo": "r", "registers": ["bogus"]}],
    ])
    def test_refuse_loud(self, bad):
        with pytest.raises(ValueError):
            c.content_sources_from_config(bad)


# ---------------------------------------------------------------------------
# Hub-and-spoke adaptation refusal (ADR-0082 D407 + D411(3))
# ---------------------------------------------------------------------------


CANON = (
    "We shipped lineage tracking so every prospect traces back to its discovery "
    "source. That kills duplicate outreach at the root and makes attribution honest."
)


def _piece(*variants):
    return c.ContentPiece(content_id="cpc_x", source_ref="a1", topic="t",
                          canonical=CANON, variants=tuple(variants))


class TestAdaptationRefusal:
    def test_distinct_variants_pass(self):
        c.validate_adaptation(_piece(
            c.ContentVariant("linkedin_post", "post",
                             "Shipped lineage today. Every prospect now points back to "
                             "where it came from, so duplicate outreach just dies."),
            c.ContentVariant("x_post", "post",
                             "new: lineage. each prospect points to its discovery source. "
                             "dedup gets trivial and attribution stops lying."),
        ))

    def test_identical_bodies_rejected(self):
        with pytest.raises(ValueError, match="identical cross-post"):
            c.validate_adaptation(_piece(
                c.ContentVariant("linkedin_post", "post", "Same words here."),
                c.ContentVariant("x_post", "post", "same words here."),
            ))

    def test_mechanical_truncation_rejected(self):
        with pytest.raises(ValueError, match="truncation"):
            c.validate_adaptation(_piece(
                c.ContentVariant("x_post", "post",
                                 "We shipped lineage tracking so every prospect traces back"),
            ))

    def test_empty_body_rejected(self):
        with pytest.raises(ValueError, match="empty body"):
            c.validate_adaptation(_piece(c.ContentVariant("x_post", "post", "   ")))

    def test_bad_channel_and_register_rejected(self):
        with pytest.raises(ValueError, match="POST_CHANNELS"):
            c.validate_adaptation(_piece(c.ContentVariant("myspace", "post", "hi there")))
        with pytest.raises(ValueError, match="CONTENT_REGISTERS"):
            c.validate_adaptation(_piece(c.ContentVariant("x_post", "tiktok", "hi there")))

    def test_truncation_predicate_direct(self):
        assert c.is_mechanical_truncation(CANON, "We shipped lineage tracking so every")
        assert c.is_mechanical_truncation(CANON, CANON)
        assert not c.is_mechanical_truncation(CANON, "a totally re-worded shorter take")

    def test_body_hash_is_channel_scoped_and_stable(self):
        h1 = c.variant_body_hash("x_post", "hello world")
        h2 = c.variant_body_hash("x_post", "hello   world")  # whitespace-normalized
        h3 = c.variant_body_hash("linkedin_post", "hello world")
        assert h1 == h2
        assert h1 != h3
        assert h1.startswith("sha256:")


# ---------------------------------------------------------------------------
# Refuse-loud event builders + catalog parity
# ---------------------------------------------------------------------------


class TestEventBuilders:
    def test_drafted_is_piece_level_null_channel(self):
        p = c.build_content_drafted_payload(content_id="cpc_1", source_ref="a1", topic="t")
        assert p["channel"] is None and p["_emitted_by"] == "content"

    def test_approved_carries_schedule_hash_register(self):
        p = c.build_content_review_approved_payload(
            content_id="cpc_1", channel="linkedin_post",
            scheduled_at="2026-06-05T09:00:00Z", body_hash="sha256:abc", register="post")
        assert p["scheduled_at"] and p["body_hash"] and p["register"] == "post"
        assert p["channel"] == "linkedin_post"

    @pytest.mark.parametrize("call", [
        lambda: c.build_content_drafted_payload(content_id="", source_ref="a", topic="t"),
        lambda: c.build_content_review_approved_payload(
            content_id="c", channel="bogus", scheduled_at="t", body_hash="h", register="post"),
        lambda: c.build_content_review_approved_payload(
            content_id="c", channel="x_post", scheduled_at="t", body_hash="h", register="tiktok"),
        lambda: c.build_distribution_confirmed_payload(
            content_id="c", channel="x_post", intent_id="i", post_id=""),
        lambda: c.build_engagement_observed_payload(
            content_id="c", channel="x_post", metrics="notadict", observed_at="t"),
    ])
    def test_refuse_loud(self, call):
        with pytest.raises(ValueError):
            call()

    def test_catalog_parity(self):
        # The per-pillar mirror-constant parity discipline (ADR-0050 D272).
        assert c.CONTENT_NEW_EVENT_CLASSES <= EVENT_CLASS_CATALOG, (
            "CONTENT_NEW_EVENT_CLASSES must be a subset of EVENT_CLASS_CATALOG; "
            f"missing: {sorted(c.CONTENT_NEW_EVENT_CLASSES - EVENT_CLASS_CATALOG)!r}"
        )
        assert len(c.CONTENT_NEW_EVENT_CLASSES) == 8


class TestDerivedStage:
    def test_unseen_is_none(self):
        assert c.derived_content_stage([], "cpc_x") is None

    def test_progression(self):
        ev = [
            _ev(c.build_content_drafted_payload(content_id="cpc_1", source_ref="a", topic="t"),
                type="content_drafted", ts="2026-06-01T10:00:00Z"),
        ]
        assert c.derived_content_stage(ev, "cpc_1") == "drafted"
        ev.append(_ev(c.build_content_humanized_payload(content_id="cpc_1"),
                      type="content_humanized", ts="2026-06-01T11:00:00Z"))
        assert c.derived_content_stage(ev, "cpc_1") == "humanized"
        ev.append(_ev(c.build_content_review_approved_payload(
            content_id="cpc_1", channel="x_post", scheduled_at="2026-06-02T09:00:00Z",
            body_hash="sha256:h", register="post"),
            type="content_review_approved", ts="2026-06-01T12:00:00Z"))
        assert c.derived_content_stage(ev, "cpc_1") == "approved"
        ev.append(_ev(c.build_distribution_confirmed_payload(
            content_id="cpc_1", channel="x_post", intent_id="i", post_id="p"),
            type="distribution_confirmed", ts="2026-06-02T09:05:00Z"))
        assert c.derived_content_stage(ev, "cpc_1") == "posted"

    def test_rejection_without_approval_drops_to_drafted(self):
        ev = [
            _ev(c.build_content_drafted_payload(content_id="cpc_1", source_ref="a", topic="t"),
                type="content_drafted", ts="2026-06-01T10:00:00Z"),
            _ev(c.build_content_review_rejected_payload(
                content_id="cpc_1", channel="x_post", reason="off-tone"),
                type="content_review_rejected", ts="2026-06-01T11:00:00Z"),
        ]
        assert c.derived_content_stage(ev, "cpc_1") == "drafted"


# ---------------------------------------------------------------------------
# The scheduler (content_scheduler.py)
# ---------------------------------------------------------------------------


def _cal(**channels):
    return cs.calendar_config_from_dict({"enabled": True, "channels": channels})


def _approve(cid, channel, sched, *, bh="sha256:h", reg="post", ts="2026-06-03T11:00:00Z"):
    return _ev(c.build_content_review_approved_payload(
        content_id=cid, channel=channel, scheduled_at=sched, body_hash=bh, register=reg),
        type="content_review_approved", ts=ts)


def _drafted(cid, sref="feat-abc", ts="2026-06-03T10:00:00Z"):
    return _ev(c.build_content_drafted_payload(content_id=cid, source_ref=sref, topic="t"),
               type="content_drafted", ts=ts)


def _confirm(cid, channel, ts, *, post_id="p"):
    return _ev(c.build_distribution_confirmed_payload(
        content_id=cid, channel=channel, intent_id="i", post_id=post_id),
        type="distribution_confirmed", ts=ts)


class TestScheduler:
    def test_off_by_default(self):
        assert cs.compute_due_posts([_approve("cpc_1", "x_post", "2026-06-01T00:00:00Z")],
                                    cs.DEFAULT_CALENDAR, now=NOW) == []

    def test_approved_and_due_surfaces(self):
        ev = [_drafted("cpc_1"),
              _approve("cpc_1", "linkedin_post", "2026-06-04T09:00:00Z")]
        due = cs.compute_due_posts(ev, _cal(linkedin_post={"enabled": True, "daily_cap": 1}),
                                   now=NOW)
        assert len(due) == 1
        assert due[0].channel == "linkedin_post"
        assert due[0].source_ref == "feat-abc"
        assert due[0].requires_manual_post is False

    def test_future_schedule_not_due(self):
        ev = [_approve("cpc_1", "x_post", "2026-06-05T09:00:00Z")]
        assert cs.compute_due_posts(ev, _cal(x_post={"enabled": True, "daily_cap": 3}),
                                    now=NOW) == []

    def test_posted_drops_out(self):
        ev = [_approve("cpc_1", "x_post", "2026-06-04T09:00:00Z"),
              _confirm("cpc_1", "x_post", "2026-06-04T09:05:00Z")]
        assert cs.compute_due_posts(ev, _cal(x_post={"enabled": True, "daily_cap": 3}),
                                    now=NOW) == []

    def test_cap_holds_second_post(self):
        ev = [_approve("cpc_1", "linkedin_post", "2026-06-04T08:00:00Z"),
              _confirm("cpc_1", "linkedin_post", "2026-06-04T08:05:00Z"),
              _approve("cpc_2", "linkedin_post", "2026-06-04T10:00:00Z")]
        # cap 1/day already used by the confirmed post -> cpc_2 held.
        assert cs.compute_due_posts(ev, _cal(linkedin_post={"enabled": True, "daily_cap": 1}),
                                    now=NOW) == []

    def test_disabled_channel_not_due(self):
        ev = [_approve("cpc_1", "blog", "2026-06-04T09:00:00Z")]
        assert cs.compute_due_posts(ev, _cal(blog={"enabled": False}), now=NOW) == []

    def test_rejection_cancels_approval(self):
        ev = [_approve("cpc_1", "x_post", "2026-06-04T08:00:00Z", ts="2026-06-03T11:00:00Z"),
              _ev(c.build_content_review_rejected_payload(
                  content_id="cpc_1", channel="x_post", reason="no"),
                  type="content_review_rejected", ts="2026-06-03T12:00:00Z")]
        assert cs.compute_due_posts(ev, _cal(x_post={"enabled": True, "daily_cap": 3}),
                                    now=NOW) == []

    def test_reapproval_after_rejection_restores(self):
        ev = [_approve("cpc_1", "x_post", "2026-06-04T08:00:00Z", ts="2026-06-03T11:00:00Z"),
              _ev(c.build_content_review_rejected_payload(
                  content_id="cpc_1", channel="x_post", reason="no"),
                  type="content_review_rejected", ts="2026-06-03T12:00:00Z"),
              _approve("cpc_1", "x_post", "2026-06-04T08:00:00Z", ts="2026-06-03T13:00:00Z")]
        due = cs.compute_due_posts(ev, _cal(x_post={"enabled": True, "daily_cap": 3}), now=NOW)
        assert [a.channel for a in due] == ["x_post"]

    def test_community_flagged_manual(self):
        ev = [_approve("cpc_1", "reddit", "2026-06-04T08:00:00Z")]
        due = cs.compute_due_posts(
            ev, cs.calendar_config_from_dict(
                {"enabled": True, "channels": {"reddit": {"enabled": True, "daily_cap": 1}}}),
            now=NOW)
        assert len(due) == 1 and due[0].requires_manual_post is True

    def test_sorted_stable_order(self):
        ev = [_approve("cpc_2", "x_post", "2026-06-04T08:00:00Z"),
              _approve("cpc_1", "x_post", "2026-06-04T07:00:00Z")]
        due = cs.compute_due_posts(ev, _cal(x_post={"enabled": True, "daily_cap": 3}), now=NOW)
        assert [a.content_id for a in due] == ["cpc_1", "cpc_2"]


class TestCalendarParsing:
    def test_community_auto_mode_refused(self):
        with pytest.raises(ValueError, match="draft_only"):
            cs.calendar_config_from_dict(
                {"enabled": True, "channels": {"reddit": {"enabled": True, "mode": "auto"}}})

    def test_unknown_channel_refused(self):
        with pytest.raises(ValueError, match="unknown channel"):
            cs.calendar_config_from_dict(
                {"enabled": True, "channels": {"myspace": {"enabled": True}}})

    def test_negative_cap_refused(self):
        with pytest.raises(ValueError, match="daily_cap"):
            cs.calendar_config_from_dict(
                {"enabled": True, "channels": {"x_post": {"enabled": True, "daily_cap": -1}}})


class TestReport:
    def test_empty_engagement_signal_none(self):
        ev = [_confirm("cpc_1", "linkedin_post", "2026-06-04T09:00:00Z")]
        rep = cs.build_content_report(ev, now=NOW)
        assert rep["engagement"]["signal"] == "none"
        assert rep["posts"]["published_total"] == 1
        assert rep["posts"]["by_channel"] == {"linkedin_post": 1}

    def test_engagement_aggregated_when_present(self):
        ev = [
            _confirm("cpc_1", "x_post", "2026-06-04T09:00:00Z"),
            _ev(c.build_engagement_observed_payload(
                content_id="cpc_1", channel="x_post",
                metrics={"likes": 10, "reshares": 2}, observed_at="2026-06-04T12:00:00Z"),
                type="engagement_observed", ts="2026-06-04T12:00:00Z"),
            _ev(c.build_engagement_observed_payload(
                content_id="cpc_1", channel="x_post",
                metrics={"likes": 5}, observed_at="2026-06-04T15:00:00Z"),
                type="engagement_observed", ts="2026-06-04T15:00:00Z"),
        ]
        rep = cs.build_content_report(ev, now=NOW)
        assert rep["engagement"]["signal"] == "present"
        assert rep["engagement"]["by_channel"]["x_post"]["likes"] == 15
        assert rep["engagement"]["by_channel"]["x_post"]["reshares"] == 2

    def test_report_is_byte_identical(self):
        ev = [_confirm("cpc_1", "x_post", "2026-06-04T09:00:00Z")]
        a = cs.render_report(cs.build_content_report(ev, now=NOW))
        b = cs.render_report(cs.build_content_report(ev, now=NOW))
        assert a == b
