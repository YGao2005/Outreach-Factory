"""Tests for orchestrator/content_reconcile.py (read-back recovery + engagement).

Operations-tier. The Scrapling reads happen in the skill; these test the pure
correlation + delta + ledger-write logic the skill calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator import content as c
from orchestrator import content_scheduler as cs
from orchestrator import content_reconcile as crx
from orchestrator import ledger as L


NOW = datetime(2026, 6, 4, 17, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def led(tmp_path: Path) -> L.Ledger:
    return L.Ledger(tmp_path / "ledger")


def _intent(cid, channel, iid, ts, *, body_hash="sha256:b"):
    return {**c.build_distribution_intent_payload(
        content_id=cid, channel=channel, intent_id=iid, body_hash=body_hash),
        "type": "distribution_intent", "ts": ts}


class TestReadBackRecovery:
    def test_old_orphan_is_found(self, led):
        old = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        led.append(_intent("cpc_1", "x_post", "cont_a", old))
        orphans = crx.find_orphaned_distribution_intents(led.all_events(), now=NOW)
        assert [o["intent_id"] for o in orphans] == ["cont_a"]

    def test_closed_intent_is_not_orphan(self, led):
        old = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        led.append(_intent("cpc_1", "x_post", "cont_a", old))
        led.append({**c.build_distribution_confirmed_payload(
            content_id="cpc_1", channel="x_post", intent_id="cont_a",
            post_id="p", body_hash="sha256:b"), "type": "distribution_confirmed"})
        assert crx.find_orphaned_distribution_intents(led.all_events(), now=NOW) == []

    def test_fresh_intent_inside_grace_window_skipped(self, led):
        fresh = (NOW - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        led.append(_intent("cpc_1", "x_post", "cont_a", fresh))
        assert crx.find_orphaned_distribution_intents(
            led.all_events(), now=NOW, min_age=timedelta(minutes=5)) == []

    def test_synthesize_confirmed_marks_recovered_and_posted(self, led):
        old = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        led.append(_intent("cpc_1", "linkedin_post", "cont_a", old, body_hash="sha256:bh"))
        orphan = crx.find_orphaned_distribution_intents(led.all_events(), now=NOW)[0]
        crx.synthesize_confirmed_from_readback(led, intent_event=orphan, post_id="urn:li:9")
        e = led.query_by_post_id("urn:li:9", channel="linkedin_post")
        assert e is not None
        assert e["_recovered_by"] == "reconcile"
        assert e["body_hash"] == "sha256:bh"
        assert c.derived_content_stage(led.all_events(), "cpc_1") == "posted"


class TestEngagementIngest:
    def _confirm(self, led, cid, channel, post_id):
        led.append({**c.build_distribution_confirmed_payload(
            content_id=cid, channel=channel, intent_id="i",
            post_id=post_id, body_hash="sha256:b"), "type": "distribution_confirmed"})

    def test_posts_to_poll_dedupes(self, led):
        self._confirm(led, "cpc_1", "x_post", "p1")
        self._confirm(led, "cpc_2", "linkedin_post", "p2")
        polls = crx.posts_to_poll(led.all_events())
        assert {(p["content_id"], p["channel"]) for p in polls} == \
            {("cpc_1", "x_post"), ("cpc_2", "linkedin_post")}

    def test_first_scrape_emits_full_then_delta(self, led):
        self._confirm(led, "cpc_1", "x_post", "p1")
        d1 = crx.ingest_engagement(led, content_id="cpc_1", channel="x_post",
                                   scraped_metrics={"likes": 10}, observed_at="t1")
        assert d1 == {"likes": 10}
        d2 = crx.ingest_engagement(led, content_id="cpc_1", channel="x_post",
                                   scraped_metrics={"likes": 25}, observed_at="t2")
        assert d2 == {"likes": 15}
        # the report sums the deltas back to the cumulative scrape
        rep = cs.build_content_report(led.all_events(), now=NOW)
        assert rep["engagement"]["by_channel"]["x_post"]["likes"] == 25
        assert rep["engagement"]["signal"] == "present"

    def test_no_change_is_noop(self, led):
        self._confirm(led, "cpc_1", "x_post", "p1")
        crx.ingest_engagement(led, content_id="cpc_1", channel="x_post",
                              scraped_metrics={"likes": 10}, observed_at="t1")
        before = len(led.all_events())
        # same cumulative count -> nothing new
        assert crx.ingest_engagement(led, content_id="cpc_1", channel="x_post",
                                     scraped_metrics={"likes": 10}, observed_at="t2") is None
        assert len(led.all_events()) == before

    def test_empty_scrape_is_no_signal(self, led):
        self._confirm(led, "cpc_1", "x_post", "p1")
        before = len(led.all_events())
        # a failed/empty scrape produces no event (honest "no signal")
        assert crx.ingest_engagement(led, content_id="cpc_1", channel="x_post",
                                     scraped_metrics={}, observed_at="t") is None
        assert len(led.all_events()) == before
