"""Pillar C Week 5 — reconcile Pass F (Twitter DMs) direct unit tests.

Mirrors ``tests/test_reconcile_li_dm.py::TestPassE*`` shape modulo:

* Intent type ``tw_dm_intent``; outcome types ``tw_dm_confirmed`` /
  ``tw_dm_aborted``.
* Twitter cookie-scrape surface is recent DMs (`list_recent_dms` per
  ADR-0018 D58 + the D62 helper generalization).
* Marker-scan against Twitter DM body text (same marker shape as
  LinkedIn DM per ADR-0018 D58 = ADR-0016 D43 = ADR-0015 D39).
* Correlation field stamped is ``twitter_thread_id``.
* Channel value is ``"twitter"`` (distinct from LinkedIn's).
* Intent-side carry field is ``twitter_handle`` (vs LinkedIn's
  ``linkedin_url``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import ledger as _ledger
import reconcile as _reconcile


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(d))
    return _ledger.Ledger(d)


def _old_ts(minutes: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)) \
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _seed_tw_dm_intent(
    led, *, intent_id, person_id="evan-estefan-li",
    twitter_handle="evan_estefan",
    register="cold-pitch",
    ts_minutes_ago: int = 10,
):
    led.append({
        "type": "tw_dm_intent",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "twitter",
        "twitter_handle": twitter_handle,
        "register": register,
        "ts": _old_ts(ts_minutes_ago),
    })


# Zero-width-space character (U+200B) per ADR-0015 D39 + ADR-0016 D43 +
# ADR-0018 D58.
ZWS = "​"


def _tw_marker(intent_id: str) -> str:
    """The on-the-wire marker shape per ADR-0018 D58 (verbatim mirror
    of ADR-0015 D39's LinkedIn marker)."""
    return f"{ZWS}outreach-intent:{intent_id}{ZWS}"


def _conv_with_dm(
    *, thread_id: str, body: str, sent_at: str | None = None,
    from_self: bool = True,
) -> dict:
    """Build a fake Twitter DM conversation dict shaped for the
    TwitterClientLike Protocol's ``list_recent_dms()`` return shape."""
    return {
        "thread_id": thread_id,
        "messages": [
            {
                "body": body,
                "from_self": from_self,
                "sent_at": sent_at or _old_ts(8),
            },
        ],
    }


class FakeTwitter:
    """Drop-in for tests.

    ``recent_dms`` is the list returned by ``list_recent_dms``;
    ``fail_list_dms`` injects failures into the surface to exercise
    Pass F's error-handling posture per ADR-0017 D50 (inherited by
    Pass F via D62's generalized helper).
    """

    def __init__(self):
        self.recent_dms: list[dict] = []
        self.fail_list_dms: Exception | None = None
        self.list_dms_calls: list[int] = []

    def list_recent_dms(
        self, limit: int = _reconcile.TWITTER_DEFAULT_SCAN_LIMIT,
    ) -> list[dict]:
        self.list_dms_calls.append(limit)
        if self.fail_list_dms is not None:
            raise self.fail_list_dms
        return list(self.recent_dms[:limit])


# ---------------------------------------------------------------------------
# Pass F — happy paths
# ---------------------------------------------------------------------------


class TestPassFHappyPath:

    def test_empty_ledger_no_emissions(self, tmp_ledger):
        """No open Twitter DM intents → no emissions."""
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []
        assert result.errors == []
        # ADR-0017 D49 (generalized to Pass F via D62) forecloses the
        # wasted MCP fetch when no orphans exist.
        assert tw.list_dms_calls == []

    def test_single_intent_marker_match_emits_confirmed(self, tmp_ledger):
        """A matching DM body in a Twitter conversation → emit
        tw_dm_confirmed with channel=twitter + _recovered_by=reconcile +
        twitter_thread_id."""
        iid = "snd_TWDMMATCH00000000000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        tw.recent_dms.append(_conv_with_dm(
            thread_id="tw-thread-A",
            body=f"hey, thoughts on agent infra.{_tw_marker(iid)}",
        ))
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "tw_dm_confirmed"
        assert ev["intent_id"] == iid
        assert ev["channel"] == "twitter"
        assert ev["_recovered_by"] == "reconcile"
        assert ev["twitter_thread_id"] == "tw-thread-A"
        # Per the D62 generalized helper's carry-field parameter, the
        # twitter_handle from the intent denormalizes onto the
        # confirmed event so Pillar D's reply joiner can correlate
        # without re-querying the origin.
        assert ev["twitter_handle"] == "evan_estefan"
        outcome = tmp_ledger.outcome_for_intent(iid)
        assert outcome is not None
        assert outcome.type == "tw_dm_confirmed"

    def test_intent_no_match_old_enough_emits_aborted(self, tmp_ledger):
        """Per ADR-0017 D50 (generalized via D62): no matching DM marker
        AND intent older than min_intent_age → emit tw_dm_aborted."""
        iid = "snd_TWDMNOMATCH00000000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid, ts_minutes_ago=10)
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "tw_dm_aborted"
        assert ev["intent_id"] == iid
        assert ev["channel"] == "twitter"
        assert ev["_recovered_by"] == "reconcile"
        assert "no_twitter_dm_match" in ev["reason"]

    def test_intent_no_match_too_young_skipped(self, tmp_ledger):
        """Intent younger than min_intent_age → no emission yet."""
        iid = "snd_TWDMYOUNG0000000000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid, ts_minutes_ago=1)
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        assert result.examined == 1
        assert result.synthesized == []
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_multi_message_conversation_scans_all_self_sent(self, tmp_ledger):
        """A conversation with several self-sent messages: marker may be
        in any of them. Pass F scans every self-message body."""
        iid = "snd_TWDMMULTIBODY00000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        # Marker is in the 3rd self message.
        tw.recent_dms.append({
            "thread_id": "tw-thread-multi",
            "messages": [
                {"body": "hey", "from_self": True, "sent_at": _old_ts(15)},
                {"body": "thanks!", "from_self": False, "sent_at": _old_ts(14)},
                {"body": f"follow-up{_tw_marker(iid)}",
                 "from_self": True, "sent_at": _old_ts(13)},
            ],
        })
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "tw_dm_confirmed"]
        assert len(confirms) == 1
        assert confirms[0]["twitter_thread_id"] == "tw-thread-multi"

    def test_mixed_match_and_no_match(self, tmp_ledger):
        """A mix of matched + missing intents: matched → confirmed,
        missing-and-old → aborted, missing-and-young → skipped."""
        tw = FakeTwitter()
        # 2 matched
        matched_ids = []
        for i in range(2):
            iid = f"snd_TWDMMIX{i:02d}MATCH000000000001"
            matched_ids.append(iid)
            _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
            tw.recent_dms.append(_conv_with_dm(
                thread_id=f"tw-thread-mix-{i}",
                body=f"msg {i}{_tw_marker(iid)}",
            ))
        # 2 missing-and-old
        missing_old_ids = []
        for i in range(2):
            iid = f"snd_TWDMMIX{i:02d}MISSINGOLD0001"
            missing_old_ids.append(iid)
            _seed_tw_dm_intent(
                tmp_ledger, intent_id=iid, ts_minutes_ago=20,
            )
        # 1 missing-and-young
        young_iid = "snd_TWDMMIX01MISSINGYOUNG0001"
        _seed_tw_dm_intent(
            tmp_ledger, intent_id=young_iid, ts_minutes_ago=1,
        )
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        confirms = [e for e in result.synthesized if e["type"] == "tw_dm_confirmed"]
        aborts = [e for e in result.synthesized if e["type"] == "tw_dm_aborted"]
        assert {e["intent_id"] for e in confirms} == set(matched_ids)
        assert {e["intent_id"] for e in aborts} == set(missing_old_ids)
        assert tmp_ledger.outcome_for_intent(young_iid) is None

    def test_confirmed_omits_thread_id_when_surface_omits_it(self, tmp_ledger):
        """When the conversation dict has no thread_id, the confirmed
        event must still emit (without twitter_thread_id stamping)."""
        iid = "snd_TWDMNOTHREADID00000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        # No thread_id on the conversation dict.
        tw.recent_dms.append({
            "messages": [
                {"body": _tw_marker(iid), "from_self": True},
            ],
        })
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "tw_dm_confirmed"]
        assert len(confirms) == 1
        assert "twitter_thread_id" not in confirms[0]


# ---------------------------------------------------------------------------
# Pass F — execution + dry-run + idempotence + boundary
# ---------------------------------------------------------------------------


class TestPassFExecution:

    def test_dry_run_no_ledger_writes(self, tmp_ledger):
        """Dry-run reports findings; ledger is unchanged."""
        iid = "snd_TWDMDRYRUN0000000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0]["_dry_run"] is True
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_idempotent_under_re_run(self, tmp_ledger):
        """A second Pass F doesn't re-emit an outcome the first committed."""
        iid = "snd_TWDMIDEMPOTENT0000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        result_1 = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(result_1.synthesized) == 1
        result_2 = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result_2.examined == 0
        assert result_2.synthesized == []

    def test_min_age_filter_uses_intent_ts(self, tmp_ledger):
        """min_intent_age controls the abort-vs-skip decision per D50."""
        iid_young = "snd_TWDMYOUNGAGE0000000001"
        iid_old = "snd_TWDMOLDAGE000000000001"
        _seed_tw_dm_intent(
            tmp_ledger, intent_id=iid_young, ts_minutes_ago=2,
        )
        _seed_tw_dm_intent(
            tmp_ledger, intent_id=iid_old, ts_minutes_ago=30,
        )
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=10),
        )
        seen = [e.get("intent_id") for e in result.synthesized]
        assert iid_old in seen
        assert iid_young not in seen

    def test_scan_limit_propagated_to_twitter_call(self, tmp_ledger):
        """ADR-0018 D58 — scan_limit kwarg propagated to
        list_recent_dms."""
        iid = "snd_TWDMSCANLIMIT000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, scan_limit=25,
        )
        assert tw.list_dms_calls == [25]

    def test_default_scan_limit_is_100(self, tmp_ledger):
        """ADR-0018 D58 — default TWITTER_DEFAULT_SCAN_LIMIT is 100."""
        iid = "snd_TWDMDEFAULTLIMIT00000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert tw.list_dms_calls == [100]


# ---------------------------------------------------------------------------
# Pass F — channel discipline + cross-channel isolation
# ---------------------------------------------------------------------------


class TestPassFChannelDiscipline:

    def test_does_not_examine_email_intents(self, tmp_ledger):
        """Email intents are out of scope for Pass F."""
        email_iid = "snd_EMAILINTENTPASSF0000001"
        tmp_ledger.append({
            "type": "send_intent", "intent_id": email_iid,
            "person_id": "alice-anderson-li", "channel": "email",
            "ts": _old_ts(10),
        })
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert tmp_ledger.outcome_for_intent(email_iid) is None

    def test_does_not_examine_li_invite_intents(self, tmp_ledger):
        """LinkedIn-invite intents go through Pass D, not Pass F.
        Per ADR-0014 D33's per-action prefix discrimination AND
        per-channel filtering via led.open_intents."""
        inv_iid = "snd_LIINVITEINTENTPASSF0001"
        tmp_ledger.append({
            "type": "li_invite_intent", "intent_id": inv_iid,
            "person_id": "carol-cole-li", "channel": "linkedin",
            "ts": _old_ts(10),
        })
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert tmp_ledger.outcome_for_intent(inv_iid) is None

    def test_does_not_examine_li_dm_intents(self, tmp_ledger):
        """LinkedIn-DM intents go through Pass E, not Pass F.
        Per-channel filtering via led.open_intents(channel='twitter')
        excludes LinkedIn even though both are DM-shaped events."""
        lidm_iid = "snd_LIDMINTENTPASSF0000001"
        tmp_ledger.append({
            "type": "li_dm_intent", "intent_id": lidm_iid,
            "person_id": "dana-davis-li", "channel": "linkedin",
            "ts": _old_ts(10),
        })
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert tmp_ledger.outcome_for_intent(lidm_iid) is None

    def test_emitted_confirmed_always_carries_channel_twitter(
        self, tmp_ledger,
    ):
        """ADR-0014 D33 invariant for the confirmed path."""
        iid = "snd_TWDMCHANINVARCONF000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        tw.recent_dms.append(_conv_with_dm(
            thread_id="tw-thread-chan",
            body=_tw_marker(iid),
        ))
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "twitter"

    def test_emitted_aborted_always_carries_channel_twitter(
        self, tmp_ledger,
    ):
        """ADR-0014 D33 invariant for the abort path."""
        iid = "snd_TWDMCHANINVARABORT000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "twitter"
            assert ev["_recovered_by"] == "reconcile"


# ---------------------------------------------------------------------------
# Pass F — failure modes
# ---------------------------------------------------------------------------


class TestPassFFailureModes:

    def test_twitter_fetch_exception_recorded_no_emission(self, tmp_ledger):
        """A Twitter MCP fetch exception is recorded + the pass emits
        nothing (per ADR-0017 D49's defensive shape — generalized via
        D62)."""
        iid = "snd_TWDMFETCHFAIL00000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        tw.fail_list_dms = RuntimeError("Twitter MCP rate-limited")
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert len(result.errors) == 1
        assert "rate-limited" in result.errors[0]
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_skips_from_self_false_message(self, tmp_ledger):
        """A message marked from_self=False (recipient-sent) does NOT
        match the marker scan — recipient messages can't contain
        operator-side intent_ids."""
        iid = "snd_TWDMRECIPIENTSENT00000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        # Marker is in a recipient-sent message — should be skipped.
        tw.recent_dms.append({
            "thread_id": "tw-thread-recip",
            "messages": [
                {"body": _tw_marker(iid), "from_self": False},
            ],
        })
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # Falls through to abort.
        aborts = [e for e in result.synthesized if e["type"] == "tw_dm_aborted"]
        assert len(aborts) == 1

    def test_marker_match_when_from_self_field_missing(self, tmp_ledger):
        """Some MCP backends don't tag from_self at all. The scan should
        still match (the marker is collision-resistant; defaulting to
        'consider every message' is the safe shape per the LinkedIn
        precedent)."""
        iid = "snd_TWDMNOFROMSELF0000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        tw.recent_dms.append({
            "thread_id": "tw-thread-nfs",
            "messages": [
                # No from_self key at all.
                {"body": _tw_marker(iid)},
            ],
        })
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "tw_dm_confirmed"]
        assert len(confirms) == 1

    def test_marker_for_different_intent_does_not_match(self, tmp_ledger):
        """Cross-intent isolation — a marker for a different intent_id
        in a DM body does NOT confirm the orphan."""
        iid = "snd_TWDMMINE0000000000000001"
        other_iid = "snd_TWDMOTHER000000000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        tw.recent_dms.append(_conv_with_dm(
            thread_id="tw-thread-other",
            body=f"DM for someone else: {_tw_marker(other_iid)}",
        ))
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        aborts = [e for e in result.synthesized if e["type"] == "tw_dm_aborted"]
        assert len(aborts) == 1
        assert aborts[0]["intent_id"] == iid

    def test_empty_messages_array_does_not_false_positive(self, tmp_ledger):
        """A conversation with no messages (cookie-scrape quirk)
        shouldn't crash or false-positive."""
        iid = "snd_TWDMEMPTYMSGS000000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        tw.recent_dms.append({"thread_id": "tw-thread-empty", "messages": []})
        tw.recent_dms.append({"thread_id": "tw-thread-nokey"})  # no messages key
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # Falls through to abort (no marker matched).
        aborts = [e for e in result.synthesized if e["type"] == "tw_dm_aborted"]
        assert len(aborts) == 1

    def test_non_list_batch_recorded_as_error(self, tmp_ledger):
        """A misbehaving MCP that returns non-list is recorded as an
        error + the pass emits nothing. Per ADR-0017 D49's defensive
        shape — the generalized helper preserves the discipline."""
        iid = "snd_TWDMNONLIST00000000000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)

        class BadTwitter:
            def list_recent_dms(self, limit=100):
                return {"not": "a list"}  # type: ignore[return-value]

        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=BadTwitter(),
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert len(result.errors) == 1
        assert "non-list" in result.errors[0]


# ---------------------------------------------------------------------------
# Pass F — orchestration integration (the reconcile() wrapper)
# ---------------------------------------------------------------------------


class TestPassFOrchestration:

    def test_reconcile_f_without_twitter_records_error(self, tmp_ledger):
        """A request for Pass F without a Twitter client → recorded
        as error; pass shape returns with the explicit message."""
        result = _reconcile.reconcile(
            passes="F",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, twitter=None, persist_status=False,
        )
        assert result.passes[0].pass_name == "F"
        assert len(result.passes[0].errors) == 1
        assert "Twitter" in result.passes[0].errors[0]

    def test_reconcile_d_e_f_serial_per_d58(self, tmp_ledger):
        """Per ADR-0017 D48 + ADR-0018 D58: D + E run serially (shared
        LinkedIn rate-limit pool); F joins after E by-convention
        (Twitter's MCP pool is distinct, but uniform serial ordering
        is operator-friendly). Each pass makes exactly one batch
        fetch."""
        from tests.test_reconcile_li_invite import FakeLinkedIn
        # Seed one open intent of each type.
        d_iid = "snd_TWDM_SERIAL_D_ORPHAN0001"
        e_iid = "snd_TWDM_SERIAL_E_ORPHAN0001"
        f_iid = "snd_TWDM_SERIAL_F_ORPHAN0001"
        tmp_ledger.append({
            "type": "li_invite_intent", "intent_id": d_iid,
            "person_id": "carol-cole-li", "channel": "linkedin",
            "ts": _old_ts(10),
        })
        tmp_ledger.append({
            "type": "li_dm_intent", "intent_id": e_iid,
            "person_id": "dana-davis-li", "channel": "linkedin",
            "ts": _old_ts(10),
        })
        tmp_ledger.append({
            "type": "tw_dm_intent", "intent_id": f_iid,
            "person_id": "evan-estefan-li", "channel": "twitter",
            "twitter_handle": "evan_estefan",
            "ts": _old_ts(10),
        })
        li = FakeLinkedIn()
        tw = FakeTwitter()
        result = _reconcile.reconcile(
            passes="D,E,F",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, linkedin=li, twitter=tw, apply=True,
            persist_status=False,
        )
        # Per D48 + D58: D, E, F in that order.
        assert [p.pass_name for p in result.passes] == ["D", "E", "F"]
        # Each pass made exactly one batch-fetch call.
        assert li.list_invitations_calls == [100]
        assert li.list_conversations_calls == [100]
        assert tw.list_dms_calls == [100]
        # All three orphans aborted.
        assert tmp_ledger.outcome_for_intent(d_iid).type == "li_invite_aborted"
        assert tmp_ledger.outcome_for_intent(e_iid).type == "li_dm_aborted"
        assert tmp_ledger.outcome_for_intent(f_iid).type == "tw_dm_aborted"

    def test_pass_f_in_all_passes_set(self):
        """F is a recognized pass name."""
        assert "F" in _reconcile.ALL_PASSES

    def test_reconcile_f_updates_status_per_pass(
        self, tmp_ledger, tmp_path,
    ):
        """Per ADR-0017 D51 + ADR-0018 D64 §Pillar G: per-pass
        last-run-clean timestamps in ``status.yml`` are the
        operator-facing health indicator. A clean Pass F run writes
        its timestamp."""
        import yaml
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        tw = FakeTwitter()  # No orphans → clean (no errors) Pass F.
        _reconcile.reconcile(
            passes="F",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, twitter=tw, apply=True,
            status_dir=status_dir,
        )
        status_file = status_dir / "status.yml"
        assert status_file.exists()
        data = yaml.safe_load(status_file.read_text(encoding="utf-8"))
        assert "F" in data["last_run"], (
            f"Pass F's last-run timestamp missing from status; "
            f"data={data!r}"
        )
        assert "F" in data["last_results"]

    def test_full_run_invokes_all_six_passes(self, tmp_ledger):
        """``--full`` runs all 6 passes (A,B,C,D,E,F) per ADR-0018
        §Migration/rollout item 2. The orchestrator dispatches each
        pass in turn; missing clients are recorded as per-pass errors
        rather than raising."""
        result = _reconcile.reconcile(
            passes="A,B,C,D,E,F",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger,
            gmail=None, linkedin=None, twitter=None,
            people_dir=None,
            persist_status=False,
        )
        # Six passes present in order; each records its missing-client
        # error.
        assert [p.pass_name for p in result.passes] == [
            "A", "B", "C", "D", "E", "F",
        ]


# ---------------------------------------------------------------------------
# Pass F — generalized helper symmetry with D + E
# ---------------------------------------------------------------------------


class TestGeneralizedHelper:
    """Per ADR-0018 D62, the shared core is ``_run_channel_intent_pass``
    (renamed from Week 4's ``_run_linkedin_intent_pass``). These tests
    pin the helper's per-channel parameter discipline — a regression
    that re-hardcoded ``channel='linkedin'`` would break Pass F."""

    def test_helper_emits_passed_channel_value(self, tmp_ledger):
        """The helper stamps whatever ``channel`` value the caller
        passes — not a hardcoded constant."""
        iid = "snd_HELPER_CHAN_PARAM0000001"
        _seed_tw_dm_intent(tmp_ledger, intent_id=iid)
        tw = FakeTwitter()
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "twitter"
            assert ev["channel"] != "linkedin"

    def test_helper_uses_passed_carry_intent_field(self, tmp_ledger):
        """The helper's ``carry_intent_field`` parameter (per D62)
        controls which intent-side field denormalizes onto the
        confirmed event. Pass F carries ``twitter_handle``; Pass D + E
        carry ``linkedin_url``."""
        iid = "snd_HELPER_CARRY_FIELD0001"
        _seed_tw_dm_intent(
            tmp_ledger, intent_id=iid, twitter_handle="distinct_handle",
        )
        tw = FakeTwitter()
        tw.recent_dms.append(_conv_with_dm(
            thread_id="tw-thread-carry",
            body=_tw_marker(iid),
        ))
        result = _reconcile.run_pass_f(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [
            e for e in result.synthesized if e["type"] == "tw_dm_confirmed"
        ]
        assert len(confirms) == 1
        # twitter_handle carries forward; linkedin_url does NOT appear.
        assert confirms[0]["twitter_handle"] == "distinct_handle"
        assert "linkedin_url" not in confirms[0]

    def test_helper_unchanged_behavior_for_pass_d_and_e(self, tmp_ledger):
        """A regression sanity check: Pass D + Pass E still work
        identically after the helper rename (per D62 the rename is
        non-behavioral)."""
        from tests.test_reconcile_li_invite import (
            FakeLinkedIn as _FakeLi, _li_marker as _li_marker_fn,
        )

        d_iid = "snd_HELPER_REGRESSION_D0001"
        e_iid = "snd_HELPER_REGRESSION_E0001"
        tmp_ledger.append({
            "type": "li_invite_intent", "intent_id": d_iid,
            "person_id": "carol-cole-li", "channel": "linkedin",
            "linkedin_url": "https://www.linkedin.com/in/carol/",
            "ts": _old_ts(10),
        })
        tmp_ledger.append({
            "type": "li_dm_intent", "intent_id": e_iid,
            "person_id": "dana-davis-li", "channel": "linkedin",
            "linkedin_url": "https://www.linkedin.com/in/dana/",
            "ts": _old_ts(10),
        })
        li = _FakeLi()
        li.invitations.append({
            "invitation_id": "inv-001",
            "note": f"hello{_li_marker_fn(d_iid)}",
        })
        li.conversations.append({
            "thread_id": "li-thread-dm",
            "messages": [
                {"body": _li_marker_fn(e_iid), "from_self": True},
            ],
        })
        result_d = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        result_e = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # Pass D emits confirmed with linkedin_invitation_id stamped.
        d_confirms = [
            e for e in result_d.synthesized
            if e["type"] == "li_invite_confirmed"
        ]
        assert len(d_confirms) == 1
        assert d_confirms[0]["linkedin_invitation_id"] == "inv-001"
        # The carry-field still works — linkedin_url stamps on the
        # confirmed event.
        assert d_confirms[0]["linkedin_url"] == "https://www.linkedin.com/in/carol/"

        # Pass E emits confirmed with linkedin_thread_id stamped.
        e_confirms = [
            e for e in result_e.synthesized
            if e["type"] == "li_dm_confirmed"
        ]
        assert len(e_confirms) == 1
        assert e_confirms[0]["linkedin_thread_id"] == "li-thread-dm"
        assert e_confirms[0]["linkedin_url"] == "https://www.linkedin.com/in/dana/"
