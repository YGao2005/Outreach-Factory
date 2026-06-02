"""Pillar C Week 4 — reconcile Pass E (LinkedIn DMs) direct unit tests.

Mirrors ``tests/test_reconcile_li_invite.py::TestPassD*`` shape modulo:

* Intent type ``li_dm_intent``; outcome types ``li_dm_confirmed`` /
  ``li_dm_aborted``.
* LinkedIn surface is conversations (not invitations).
* Marker-scan against message body text (not connection-note text).
* Correlation field stamped is ``linkedin_thread_id`` (not invitation_id).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import ledger as _ledger
import reconcile as _reconcile

from tests.test_reconcile_li_invite import (
    FakeLinkedIn,
    ZWS,
    _li_marker,
    _old_ts,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(d))
    return _ledger.Ledger(d)


def _seed_li_dm_intent(
    led, *, intent_id, person_id="dana-davis-li",
    linkedin_url="https://www.linkedin.com/in/test/",
    register="cold-pitch",
    ts_minutes_ago: int = 10,
):
    led.append({
        "type": "li_dm_intent",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "linkedin",
        "linkedin_url": linkedin_url,
        "register": register,
        "ts": _old_ts(ts_minutes_ago),
    })


def _conv_with_dm(
    *, thread_id: str, body: str, sent_at: str | None = None,
    from_self: bool = True,
) -> dict:
    """Build a fake conversation dict shaped for the LinkedInClientLike
    Protocol's list_recent_conversations() return shape."""
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


# ---------------------------------------------------------------------------
# Pass E — happy paths
# ---------------------------------------------------------------------------


class TestPassEHappyPath:

    def test_empty_ledger_no_emissions(self, tmp_ledger):
        """No open LinkedIn DM intents → no emissions."""
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []
        assert result.errors == []
        # ADR-0017 D49 forecloses the wasted MCP fetch when no orphans
        # exist — list_recent_conversations is NOT called.
        assert li.list_conversations_calls == []

    def test_single_intent_marker_match_emits_confirmed(self, tmp_ledger):
        """A matching DM body in a conversation → emit li_dm_confirmed
        with channel=linkedin + _recovered_by=reconcile + linkedin_thread_id."""
        iid = "snd_LIDMMATCH00000000000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.conversations.append(_conv_with_dm(
            thread_id="li-thread-A",
            body=f"hey, wanted to share this with you.{_li_marker(iid)}",
        ))
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "li_dm_confirmed"
        assert ev["intent_id"] == iid
        assert ev["channel"] == "linkedin"
        assert ev["_recovered_by"] == "reconcile"
        assert ev["linkedin_thread_id"] == "li-thread-A"
        assert ev["linkedin_url"] == "https://www.linkedin.com/in/test/"
        outcome = tmp_ledger.outcome_for_intent(iid)
        assert outcome is not None
        assert outcome.type == "li_dm_confirmed"

    def test_intent_no_match_old_enough_emits_aborted(self, tmp_ledger):
        """Per ADR-0017 D50: no matching DM marker AND intent older
        than min_intent_age → emit li_dm_aborted."""
        iid = "snd_LIDMNOMATCH00000000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid, ts_minutes_ago=10)
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "li_dm_aborted"
        assert ev["intent_id"] == iid
        assert ev["channel"] == "linkedin"
        assert ev["_recovered_by"] == "reconcile"
        assert "no_linkedin_dm_match" in ev["reason"]

    def test_intent_no_match_too_young_skipped(self, tmp_ledger):
        """Intent younger than min_intent_age → no emission yet."""
        iid = "snd_LIDMYOUNG0000000000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid, ts_minutes_ago=1)
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        assert result.examined == 1
        assert result.synthesized == []
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_multi_message_conversation_scans_all_self_sent(self, tmp_ledger):
        """A conversation with several self-sent messages: marker may
        be in any of them. Pass E scans every self-message body."""
        iid = "snd_LIDMMULTIBODY00000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        # Marker is in the 3rd self message.
        li.conversations.append({
            "thread_id": "li-thread-multi",
            "messages": [
                {"body": "hey", "from_self": True, "sent_at": _old_ts(15)},
                {"body": "thanks!", "from_self": False, "sent_at": _old_ts(14)},
                {"body": f"follow-up{_li_marker(iid)}",
                 "from_self": True, "sent_at": _old_ts(13)},
            ],
        })
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "li_dm_confirmed"]
        assert len(confirms) == 1
        assert confirms[0]["linkedin_thread_id"] == "li-thread-multi"

    def test_mixed_match_and_no_match(self, tmp_ledger):
        """A mix of matched + missing intents: matched → confirmed,
        missing-and-old → aborted, missing-and-young → skipped."""
        li = FakeLinkedIn()
        # 2 matched
        matched_ids = []
        for i in range(2):
            iid = f"snd_LIDMMIX{i:02d}MATCH000000000001"
            matched_ids.append(iid)
            _seed_li_dm_intent(tmp_ledger, intent_id=iid)
            li.conversations.append(_conv_with_dm(
                thread_id=f"li-thread-mix-{i}",
                body=f"msg {i}{_li_marker(iid)}",
            ))
        # 2 missing-and-old
        missing_old_ids = []
        for i in range(2):
            iid = f"snd_LIDMMIX{i:02d}MISSINGOLD0001"
            missing_old_ids.append(iid)
            _seed_li_dm_intent(
                tmp_ledger, intent_id=iid, ts_minutes_ago=20,
            )
        # 1 missing-and-young
        young_iid = "snd_LIDMMIX01MISSINGYOUNG0001"
        _seed_li_dm_intent(
            tmp_ledger, intent_id=young_iid, ts_minutes_ago=1,
        )
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        confirms = [e for e in result.synthesized if e["type"] == "li_dm_confirmed"]
        aborts = [e for e in result.synthesized if e["type"] == "li_dm_aborted"]
        assert {e["intent_id"] for e in confirms} == set(matched_ids)
        assert {e["intent_id"] for e in aborts} == set(missing_old_ids)
        assert tmp_ledger.outcome_for_intent(young_iid) is None

    def test_confirmed_omits_thread_id_when_surface_omits_it(self, tmp_ledger):
        """When the conversation dict has no thread_id, the confirmed
        event must still emit (without linkedin_thread_id stamping)."""
        iid = "snd_LIDMNOTHREADID00000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        # No thread_id on the conversation dict.
        li.conversations.append({
            "messages": [
                {"body": _li_marker(iid), "from_self": True},
            ],
        })
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "li_dm_confirmed"]
        assert len(confirms) == 1
        assert "linkedin_thread_id" not in confirms[0]


# ---------------------------------------------------------------------------
# Pass E — execution + dry-run + idempotence + boundary
# ---------------------------------------------------------------------------


class TestPassEExecution:

    def test_dry_run_no_ledger_writes(self, tmp_ledger):
        """Dry-run reports findings; ledger is unchanged."""
        iid = "snd_LIDMDRYRUN0000000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0]["_dry_run"] is True
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_idempotent_under_re_run(self, tmp_ledger):
        """A second Pass E doesn't re-emit an outcome the first run committed."""
        iid = "snd_LIDMIDEMPOTENT0000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        result_1 = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(result_1.synthesized) == 1
        result_2 = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result_2.examined == 0
        assert result_2.synthesized == []

    def test_min_age_filter_uses_intent_ts(self, tmp_ledger):
        """min_intent_age controls the abort-vs-skip decision per D50."""
        iid_young = "snd_LIDMYOUNGAGE0000000001"
        iid_old = "snd_LIDMOLDAGE000000000001"
        _seed_li_dm_intent(
            tmp_ledger, intent_id=iid_young, ts_minutes_ago=2,
        )
        _seed_li_dm_intent(
            tmp_ledger, intent_id=iid_old, ts_minutes_ago=30,
        )
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=10),
        )
        seen = [e.get("intent_id") for e in result.synthesized]
        assert iid_old in seen
        assert iid_young not in seen

    def test_scan_limit_propagated_to_linkedin_call(self, tmp_ledger):
        """D49 — scan_limit kwarg propagated to list_recent_conversations."""
        iid = "snd_LIDMSCANLIMIT000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, scan_limit=25,
        )
        assert li.list_conversations_calls == [25]

    def test_default_scan_limit_is_100(self, tmp_ledger):
        """ADR-0017 D49 — default LINKEDIN_DEFAULT_SCAN_LIMIT is 100."""
        iid = "snd_LIDMDEFAULTLIMIT00000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert li.list_conversations_calls == [100]


# ---------------------------------------------------------------------------
# Pass E — channel discipline + cross-channel isolation
# ---------------------------------------------------------------------------


class TestPassEChannelDiscipline:

    def test_does_not_examine_email_intents(self, tmp_ledger):
        """Email intents are out of scope for Pass E."""
        email_iid = "snd_EMAILINTENTPASSE0000001"
        tmp_ledger.append({
            "type": "send_intent", "intent_id": email_iid,
            "person_id": "alice-anderson-li", "channel": "email",
            "ts": _old_ts(10),
        })
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert tmp_ledger.outcome_for_intent(email_iid) is None

    def test_does_not_examine_li_invite_intents(self, tmp_ledger):
        """LinkedIn-invite intents go through Pass D, not Pass E.
        Per ADR-0014 D33's per-action prefix discrimination."""
        inv_iid = "snd_LIINVITEINTENTPASSE0001"
        tmp_ledger.append({
            "type": "li_invite_intent", "intent_id": inv_iid,
            "person_id": "carol-cole-li", "channel": "linkedin",
            "ts": _old_ts(10),
        })
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert tmp_ledger.outcome_for_intent(inv_iid) is None

    def test_emitted_confirmed_always_carries_channel_linkedin(
        self, tmp_ledger,
    ):
        """ADR-0014 D33 invariant for the confirmed path."""
        iid = "snd_LIDMCHANINVARCONF000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.conversations.append(_conv_with_dm(
            thread_id="li-thread-chan",
            body=_li_marker(iid),
        ))
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "linkedin"

    def test_emitted_aborted_always_carries_channel_linkedin(
        self, tmp_ledger,
    ):
        """ADR-0014 D33 invariant for the abort path."""
        iid = "snd_LIDMCHANINVARABORT000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "linkedin"
            assert ev["_recovered_by"] == "reconcile"


# ---------------------------------------------------------------------------
# Pass E — failure modes
# ---------------------------------------------------------------------------


class TestPassEFailureModes:

    def test_linkedin_fetch_exception_recorded_no_emission(self, tmp_ledger):
        """A LinkedIn fetch exception is recorded + the pass emits nothing."""
        iid = "snd_LIDMFETCHFAIL00000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.fail_list_conversations = RuntimeError("LinkedIn MCP rate-limited")
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
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
        iid = "snd_LIDMRECIPIENTSENT00000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        # Marker is in a recipient-sent message — should be skipped.
        li.conversations.append({
            "thread_id": "li-thread-recip",
            "messages": [
                {"body": _li_marker(iid), "from_self": False},
            ],
        })
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # Falls through to abort.
        aborts = [e for e in result.synthesized if e["type"] == "li_dm_aborted"]
        assert len(aborts) == 1

    def test_marker_match_when_from_self_field_missing(self, tmp_ledger):
        """Some MCP backends don't tag from_self at all. The scan should
        still match (the marker is collision-resistant; defaulting to
        'consider every message' is the safe shape)."""
        iid = "snd_LIDMNOFROMSELF0000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-nfs",
            "messages": [
                # No from_self key at all.
                {"body": _li_marker(iid)},
            ],
        })
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "li_dm_confirmed"]
        assert len(confirms) == 1

    def test_marker_for_different_intent_does_not_match(self, tmp_ledger):
        """Cross-intent isolation — a marker for a different intent_id
        in a DM body does NOT confirm the orphan."""
        iid = "snd_LIDMMINE0000000000000001"
        other_iid = "snd_LIDMOTHER000000000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.conversations.append(_conv_with_dm(
            thread_id="li-thread-other",
            body=f"DM for someone else: {_li_marker(other_iid)}",
        ))
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        aborts = [e for e in result.synthesized if e["type"] == "li_dm_aborted"]
        assert len(aborts) == 1
        assert aborts[0]["intent_id"] == iid

    def test_empty_messages_array_does_not_false_positive(self, tmp_ledger):
        """A conversation with no messages (LinkedIn quirk) shouldn't crash
        or false-positive."""
        iid = "snd_LIDMEMPTYMSGS000000000001"
        _seed_li_dm_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.conversations.append({"thread_id": "li-thread-empty", "messages": []})
        li.conversations.append({"thread_id": "li-thread-nokey"})  # no messages key
        result = _reconcile.run_pass_e(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # Falls through to abort (no marker matched).
        aborts = [e for e in result.synthesized if e["type"] == "li_dm_aborted"]
        assert len(aborts) == 1


# ---------------------------------------------------------------------------
# Pass E — orchestration integration (the reconcile() wrapper)
# ---------------------------------------------------------------------------


class TestPassEOrchestration:

    def test_reconcile_e_without_linkedin_records_error(self, tmp_ledger):
        """A request for Pass E without a LinkedIn client → recorded
        as error; pass shape returns with the explicit message."""
        result = _reconcile.reconcile(
            passes="E",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, linkedin=None, persist_status=False,
        )
        assert result.passes[0].pass_name == "E"
        assert len(result.passes[0].errors) == 1
        assert "LinkedIn" in result.passes[0].errors[0]

    def test_reconcile_d_and_e_serial_per_d48(self, tmp_ledger):
        """Per ADR-0017 D48: D and E run serially in a single call.
        Both share the LinkedIn MCP rate-limit pool — Pass D fetches
        invitations once, then Pass E fetches conversations once,
        each emitting independent outcomes."""
        # Seed one open intent of each type.
        d_iid = "snd_LIDM_SERIAL_D_ORPHAN0001"
        e_iid = "snd_LIDM_SERIAL_E_ORPHAN0001"
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
        li = FakeLinkedIn()  # No matching invitations or conversations.
        result = _reconcile.reconcile(
            passes="D,E",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, linkedin=li, apply=True,
            persist_status=False,
        )
        # Per D48: D first, then E.
        assert [p.pass_name for p in result.passes] == ["D", "E"]
        # Each pass made exactly one batch-fetch call (the marker scan
        # is amortized across orphans per D49).
        assert li.list_invitations_calls == [100]
        assert li.list_conversations_calls == [100]
        # Both orphans aborted.
        assert tmp_ledger.outcome_for_intent(d_iid).type == "li_invite_aborted"
        assert tmp_ledger.outcome_for_intent(e_iid).type == "li_dm_aborted"

    def test_pass_e_in_all_passes_set(self):
        """E is a recognized pass name."""
        assert "E" in _reconcile.ALL_PASSES

    def test_reconcile_d_and_e_update_status_per_pass(
        self, tmp_ledger, tmp_path,
    ):
        """Per ADR-0017 D51 + D52 §Pillar G: per-pass last-run-clean
        timestamps in ``status.yml`` are the operator-facing health
        indicator. A clean Pass D + Pass E run writes both timestamps.

        Coverage-gap fix per the Week 4 per-week review C-2 finding —
        before this test, neither test file exercised the per-pass
        persistence path for D / E, so a regression in ``_record_status``
        that silently dropped LinkedIn-pass timestamps wouldn't catch.
        """
        import yaml
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        li = FakeLinkedIn()  # No orphans → clean (no errors) Pass D + E.
        _reconcile.reconcile(
            passes="D,E",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, linkedin=li, apply=True,
            status_dir=status_dir,
        )
        status_file = status_dir / "status.yml"
        assert status_file.exists()
        data = yaml.safe_load(status_file.read_text(encoding="utf-8"))
        assert "D" in data["last_run"], (
            f"Pass D's last-run timestamp missing from status; "
            f"data={data!r}"
        )
        assert "E" in data["last_run"], (
            f"Pass E's last-run timestamp missing from status; "
            f"data={data!r}"
        )
        # Per-pass result summaries are also persisted.
        assert "D" in data["last_results"]
        assert "E" in data["last_results"]
