"""Pillar D Week 3 — reconcile Pass H / I / J unit tests.

Per ADR-0027 D111 + D112. Mirrors ``tests/test_reconcile_li_invite.py`` /
``tests/test_reconcile_li_dm.py`` / ``tests/test_reconcile_tw_dm.py``
shapes modulo the per-channel reply-detection (not intent-recovery)
contract.

Covers the verification surface ADR-0027 D111 + D112 name:

* Pass H (LinkedIn invite acceptance detection):
  - Happy path: a ``li_invite_confirmed`` with a ``"accepted"``
    status on the LinkedIn surface → emit ``li_invite_reply_received``
    with channel=linkedin + reply_message_id=li_accept:<inv_id> +
    reply_to_intent_id=<intent_id>.
  - Pending / declined / withdrawn invitations → no emit.
  - Idempotence per ADR-0026 D104 + ADR-0027 D112 (rerun is no-op).
  - Per-channel discipline (channel=linkedin on every emit).
  - Dry-run safety (no ledger writes).
  - Failure modes (LinkedIn fetch error → recorded + early return).

* Pass I (LinkedIn DM reply detection):
  - Happy path: an inbound message on a known
    ``li_dm_confirmed.linkedin_thread_id`` → emit
    ``li_dm_reply_received`` with channel=linkedin +
    reply_message_id=<msg_id or synthesized fallback>.
  - Self-sent messages NEVER emit (from_self=True filtered).
  - Conversations on UNKNOWN thread_ids NEVER emit (filter is
    by-known-thread).
  - Idempotence per (mid, channel) pair.
  - Synthesized reply_message_id fallback when MCP omits message_id.
  - Dry-run + failure-mode coverage.

* Pass J (Twitter DM reply detection):
  - Structurally identical to Pass I via the
    `_run_channel_dm_reply_pass` helper (ADR-0027 D111). The shared-
    helper coverage tests one representative shape per channel.

* Pass G consumes the new event types per ADR-0027 D112 (Pillar G
  integration test confirms end-to-end H/I/J → Pass G chain).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ledger as _ledger
import reconcile as _reconcile
import reply_classifier as _classifier


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


def _seed_li_invite_confirmed(
    led, *, intent_id="snd_LIINVITE01CONFIRMED000000", invitation_id="inv-001",
    person_id="alice-anderson-li",
    linkedin_url="https://www.linkedin.com/in/test/",
    ts_minutes_ago: int = 5,
):
    led.append({
        "type": "li_invite_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "linkedin",
        "linkedin_url": linkedin_url,
        "linkedin_invitation_id": invitation_id,
        "_recovered_by": "reconcile",
        "ts": _old_ts(ts_minutes_ago),
    })


def _seed_li_dm_confirmed(
    led, *, intent_id="snd_LIDM01CONFIRMED00000000001",
    thread_id="li-thread-A",
    person_id="bob-baker-li",
    linkedin_url="https://www.linkedin.com/in/bob/",
    ts_minutes_ago: int = 5,
):
    led.append({
        "type": "li_dm_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "linkedin",
        "linkedin_url": linkedin_url,
        "linkedin_thread_id": thread_id,
        "_recovered_by": "reconcile",
        "ts": _old_ts(ts_minutes_ago),
    })


def _seed_tw_dm_confirmed(
    led, *, intent_id="snd_TWDM01CONFIRMED00000000001",
    thread_id="tw-thread-A",
    person_id="carol-cole-tw",
    twitter_handle="carol_cole",
    ts_minutes_ago: int = 5,
):
    led.append({
        "type": "tw_dm_confirmed",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "twitter",
        "twitter_handle": twitter_handle,
        "twitter_thread_id": thread_id,
        "_recovered_by": "reconcile",
        "ts": _old_ts(ts_minutes_ago),
    })


class FakeLinkedIn:
    """Drop-in for Pass H + Pass I tests.

    ``invitations`` is the list returned by ``list_sent_invitations``.
    ``conversations`` is the list returned by ``list_recent_conversations``.

    ``fail_list_invitations`` / ``fail_list_conversations`` inject
    exceptions for failure-mode tests.
    """

    def __init__(self):
        self.invitations: list[dict] = []
        self.conversations: list[dict] = []
        self.fail_list_invitations: Exception | None = None
        self.fail_list_conversations: Exception | None = None
        self.list_invitations_calls: list[int] = []
        self.list_conversations_calls: list[int] = []

    def list_sent_invitations(
        self, limit: int = _reconcile.LINKEDIN_DEFAULT_SCAN_LIMIT,
    ) -> list[dict]:
        self.list_invitations_calls.append(limit)
        if self.fail_list_invitations is not None:
            raise self.fail_list_invitations
        return list(self.invitations[:limit])

    def list_recent_conversations(
        self, limit: int = _reconcile.LINKEDIN_DEFAULT_SCAN_LIMIT,
    ) -> list[dict]:
        self.list_conversations_calls.append(limit)
        if self.fail_list_conversations is not None:
            raise self.fail_list_conversations
        return list(self.conversations[:limit])


class FakeTwitter:
    """Drop-in for Pass J tests."""

    def __init__(self):
        self.dms: list[dict] = []
        self.fail_list_dms: Exception | None = None
        self.list_dms_calls: list[int] = []

    def list_recent_dms(
        self, limit: int = _reconcile.TWITTER_DEFAULT_SCAN_LIMIT,
    ) -> list[dict]:
        self.list_dms_calls.append(limit)
        if self.fail_list_dms is not None:
            raise self.fail_list_dms
        return list(self.dms[:limit])


# ===========================================================================
# Pass H — LinkedIn invite acceptance detection (ADR-0027 D111)
# ===========================================================================


class TestPassHHappyPath:

    def test_empty_ledger_no_emit_no_fetch(self, tmp_ledger):
        """No li_invite_confirmed events → no fetch, no emit (per
        ADR-0017 D49's no-wasted-MCP-fetch posture inherited by Pass H)."""
        li = FakeLinkedIn()
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []
        assert li.list_invitations_calls == []

    def test_accepted_invitation_emits_reply_received(self, tmp_ledger):
        """Per ADR-0027 D111 — an accepted invitation in the LinkedIn
        batch produces a li_invite_reply_received event."""
        _seed_li_invite_confirmed(
            tmp_ledger,
            intent_id="snd_LIINV1ACCEPT0000000000000",
            invitation_id="inv-accept-1",
        )
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-accept-1",
            "note": "hey there",
            "status": "accepted",
            "accepted_at": "2026-05-23T12:34:56.000Z",
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "li_invite_reply_received"
        assert ev["channel"] == "linkedin"
        assert ev["reply_message_id"] == "li_accept:inv-accept-1"
        assert ev["reply_to_intent_id"] == "snd_LIINV1ACCEPT0000000000000"
        assert ev["linkedin_invitation_id"] == "inv-accept-1"
        assert ev["person_id"] == "alice-anderson-li"
        assert ev["_recovered_by"] == "reconcile"
        assert ev["accepted_at"] == "2026-05-23T12:34:56.000Z"

    def test_pending_invitation_does_not_emit(self, tmp_ledger):
        """Pending invitation → no emit (operator is still waiting)."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-pending-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-pending-1",
            "note": "hey",
            "status": "pending",
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_declined_invitation_does_not_emit(self, tmp_ledger):
        """Declined invitation → no emit (declining is not a reply)."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-decline-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-decline-1",
            "note": "hey",
            "status": "declined",
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_withdrawn_invitation_does_not_emit(self, tmp_ledger):
        """Withdrawn invitation → no emit (operator-side action)."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-w-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-w-1",
            "note": "hey",
            "status": "withdrawn",
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_invitation_missing_from_batch_does_not_emit(self, tmp_ledger):
        """If the LinkedIn surface doesn't return our invitation in the
        batch (e.g., older than scan_limit), Pass H emits nothing for
        that invite. Operator may widen --linkedin-scan-limit."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-missing-1")
        li = FakeLinkedIn()
        # Return a different invitation (operator's older invite not
        # in the batch).
        li.invitations.append({
            "invitation_id": "inv-other",
            "status": "accepted",
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_mixed_accepted_and_pending_emit_only_accepted(self, tmp_ledger):
        """A mix of accepted + pending invitations: only the accepted
        ones emit reply events."""
        _seed_li_invite_confirmed(
            tmp_ledger, intent_id="snd_LIINVMIXACPT01", invitation_id="inv-a",
        )
        _seed_li_invite_confirmed(
            tmp_ledger, intent_id="snd_LIINVMIXPND01", invitation_id="inv-p",
        )
        li = FakeLinkedIn()
        li.invitations.extend([
            {"invitation_id": "inv-a", "status": "accepted"},
            {"invitation_id": "inv-p", "status": "pending"},
        ])
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0]["linkedin_invitation_id"] == "inv-a"


class TestPassHIdempotence:

    def test_rerun_does_not_emit_duplicate(self, tmp_ledger):
        """Per ADR-0026 D104 — re-running Pass H against an already-
        emitted acceptance produces no new event."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-i-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-i-1",
            "status": "accepted",
        })
        # First run — emits.
        r1 = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(r1.synthesized) == 1
        # Second run — examined again but skipped.
        r2 = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert r2.synthesized == []

    def test_idempotence_pinned_by_synthesized_reply_message_id(
        self, tmp_ledger,
    ):
        """Per ADR-0027 D112 — the synthesized reply_message_id
        (li_accept:<invitation_id>) is the idempotence discriminator."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-syn-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-syn-1",
            "status": "accepted",
        })
        r1 = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        ev = r1.synthesized[0]
        assert ev["reply_message_id"] == "li_accept:inv-syn-1"
        # Confirm the synthesized form prevents re-emit.
        r2 = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert r2.synthesized == []


class TestPassHChannelDiscipline:

    def test_emit_always_carries_channel_linkedin(self, tmp_ledger):
        """Per ADR-0025 D96 — every emit stamps channel=linkedin."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-ch-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-ch-1",
            "status": "accepted",
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "linkedin"


class TestPassHFailureModes:

    def test_fetch_exception_recorded_no_emit(self, tmp_ledger):
        """A LinkedIn fetch exception → record error + emit nothing
        per the asymmetric-failure-cost calculus (better to skip than
        wrongly emit)."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-fail-1")
        li = FakeLinkedIn()
        li.fail_list_invitations = RuntimeError("LinkedIn rate-limited")
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert len(result.errors) == 1
        assert "rate-limited" in result.errors[0]

    def test_non_list_response_recorded(self, tmp_ledger):
        """A non-list response from the MCP backend → record error +
        emit nothing."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-bad-1")

        class WeirdShape:
            def list_sent_invitations(self, limit=100):
                return {"oops": "not a list"}

            def list_recent_conversations(self, limit=100):
                return []

        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=WeirdShape(),
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert len(result.errors) == 1
        assert "non-list" in result.errors[0]

    def test_invitation_without_status_does_not_emit(self, tmp_ledger):
        """Per the protocol's defensive default — absent status is
        treated as 'pending'; no emit."""
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-nostat-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-nostat-1",
            # no status field — pre-Pillar-D-Week-3 MCP backends.
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_confirmed_without_invitation_id_skipped(self, tmp_ledger):
        """A confirmed event without linkedin_invitation_id can't be
        looked up; Pass H skips it without erroring."""
        tmp_ledger.append({
            "type": "li_invite_confirmed",
            "intent_id": "snd_LINOIDC0000000000000000001",
            "person_id": "x",
            "channel": "linkedin",
            # no linkedin_invitation_id
            "ts": _old_ts(5),
        })
        li = FakeLinkedIn()
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []


class TestPassHDryRun:

    def test_dry_run_does_not_persist(self, tmp_ledger):
        _seed_li_invite_confirmed(tmp_ledger, invitation_id="inv-dry-1")
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-dry-1",
            "status": "accepted",
        })
        result = _reconcile.run_pass_h(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0].get("_dry_run") is True
        # Ledger has no li_invite_reply_received.
        events = [e for e in tmp_ledger.all_events()
                  if e.get("type") == "li_invite_reply_received"]
        assert events == []


# ===========================================================================
# Pass I — LinkedIn DM reply detection (ADR-0027 D111)
# ===========================================================================


class TestPassIHappyPath:

    def test_empty_ledger_no_emit_no_fetch(self, tmp_ledger):
        """No li_dm_confirmed events → no fetch, no emit."""
        li = FakeLinkedIn()
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []
        assert li.list_conversations_calls == []

    def test_inbound_message_emits_reply(self, tmp_ledger):
        """An inbound message on a known thread → emit
        li_dm_reply_received with channel=linkedin + correlation."""
        _seed_li_dm_confirmed(
            tmp_ledger,
            intent_id="snd_LIDM01HAPPYPATH0000000001",
            thread_id="li-thread-happy",
        )
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-happy",
            "messages": [
                {"body": "hello!", "from_self": True,
                 "sent_at": "2026-05-23T10:00:00.000Z",
                 "message_id": "li-msg-out-1"},
                {"body": "thanks for reaching out", "from_self": False,
                 "sent_at": "2026-05-23T11:00:00.000Z",
                 "message_id": "li-msg-in-1"},
            ],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "li_dm_reply_received"
        assert ev["channel"] == "linkedin"
        assert ev["reply_message_id"] == "li-msg-in-1"
        assert ev["reply_to_intent_id"] == "snd_LIDM01HAPPYPATH0000000001"
        assert ev["linkedin_thread_id"] == "li-thread-happy"
        assert ev["snippet"] == "thanks for reaching out"
        assert ev["person_id"] == "bob-baker-li"

    def test_self_sent_message_does_not_emit(self, tmp_ledger):
        """from_self=True messages NEVER produce reply events."""
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-self")
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-self",
            "messages": [
                {"body": "first msg", "from_self": True,
                 "message_id": "out-1"},
                {"body": "second msg", "from_self": True,
                 "message_id": "out-2"},
            ],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_conversation_on_unknown_thread_does_not_emit(self, tmp_ledger):
        """A conversation whose thread_id doesn't match a known
        li_dm_confirmed is IGNORED (we don't classify random LinkedIn
        DMs — only those that follow our outbound)."""
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-mine")
        li = FakeLinkedIn()
        # Conversation on a DIFFERENT thread.
        li.conversations.append({
            "thread_id": "li-thread-stranger",
            "messages": [
                {"body": "random LinkedIn DM", "from_self": False,
                 "message_id": "msg-stranger"},
            ],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_multiple_inbound_messages_each_emit(self, tmp_ledger):
        """A conversation with multiple inbound messages → one
        reply event per message."""
        _seed_li_dm_confirmed(
            tmp_ledger,
            intent_id="snd_LIDM01MULTIINB000000000001",
            thread_id="li-thread-multi-inb",
        )
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-multi-inb",
            "messages": [
                {"body": "outbound", "from_self": True, "message_id": "out-1"},
                {"body": "first reply", "from_self": False,
                 "message_id": "in-1"},
                {"body": "second reply", "from_self": False,
                 "message_id": "in-2"},
            ],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(result.synthesized) == 2
        mids = {ev["reply_message_id"] for ev in result.synthesized}
        assert mids == {"in-1", "in-2"}


class TestPassIIdempotence:

    def test_rerun_does_not_emit_duplicate(self, tmp_ledger):
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-idem")
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-idem",
            "messages": [
                {"body": "reply", "from_self": False,
                 "message_id": "in-idem-1"},
            ],
        })
        r1 = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(r1.synthesized) == 1
        r2 = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert r2.synthesized == []

    def test_message_without_id_uses_synthesized_fallback(self, tmp_ledger):
        """Per ADR-0027 D112 — when MCP omits per-message message_id,
        Pass I synthesizes via thread_id:sent_at:idx."""
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-nomid")
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-nomid",
            "messages": [
                # No message_id field.
                {"body": "reply text", "from_self": False,
                 "sent_at": "2026-05-23T12:00:00.000Z"},
            ],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(result.synthesized) == 1
        # Synthesized form: thread_id:sent_at:idx (idx=0 here — first
        # message in the conversation).
        mid = result.synthesized[0]["reply_message_id"]
        assert mid == "li-thread-nomid:2026-05-23T12:00:00.000Z:0"


class TestPassIChannelDiscipline:

    def test_emit_always_carries_channel_linkedin(self, tmp_ledger):
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-ch")
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-ch",
            "messages": [{"body": "r", "from_self": False, "message_id": "m"}],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "linkedin"


class TestPassIFailureModes:

    def test_fetch_exception_recorded_no_emit(self, tmp_ledger):
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-fail")
        li = FakeLinkedIn()
        li.fail_list_conversations = RuntimeError("LinkedIn rate-limited")
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert "rate-limited" in result.errors[0]

    def test_non_list_response_recorded(self, tmp_ledger):
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-bad")

        class WeirdShape:
            def list_sent_invitations(self, limit=100):
                return []

            def list_recent_conversations(self, limit=100):
                return {"not": "a list"}

        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=WeirdShape(),
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert "non-list" in result.errors[0]

    def test_message_without_from_self_treated_defensively_no_emit(
        self, tmp_ledger,
    ):
        """Defensive: a message without from_self tagging defaults to
        skip (we can't tell who sent it; better to under-emit than
        to incorrectly classify a self-message as a reply)."""
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-amb")
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-amb",
            "messages": [
                # No from_self field.
                {"body": "ambiguous", "message_id": "amb"},
            ],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []


class TestPassIDryRun:

    def test_dry_run_does_not_persist(self, tmp_ledger):
        _seed_li_dm_confirmed(tmp_ledger, thread_id="li-thread-dry")
        li = FakeLinkedIn()
        li.conversations.append({
            "thread_id": "li-thread-dry",
            "messages": [{"body": "r", "from_self": False, "message_id": "m"}],
        })
        result = _reconcile.run_pass_i(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0].get("_dry_run") is True
        events = [e for e in tmp_ledger.all_events()
                  if e.get("type") == "li_dm_reply_received"]
        assert events == []


# ===========================================================================
# Pass J — Twitter DM reply detection (ADR-0027 D111)
# ===========================================================================


class TestPassJHappyPath:

    def test_empty_ledger_no_emit_no_fetch(self, tmp_ledger):
        tw = FakeTwitter()
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []
        assert tw.list_dms_calls == []

    def test_inbound_dm_emits_reply(self, tmp_ledger):
        """An inbound Twitter DM on a known thread → emit
        tw_dm_reply_received with channel=twitter."""
        _seed_tw_dm_confirmed(
            tmp_ledger,
            intent_id="snd_TWDM01HAPPY00000000000001",
            thread_id="tw-thread-happy",
        )
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-happy",
            "messages": [
                {"body": "hi", "from_self": True,
                 "message_id": "tw-out-1"},
                {"body": "thanks for the message", "from_self": False,
                 "message_id": "tw-in-1"},
            ],
        })
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "tw_dm_reply_received"
        assert ev["channel"] == "twitter"
        assert ev["reply_message_id"] == "tw-in-1"
        assert ev["reply_to_intent_id"] == "snd_TWDM01HAPPY00000000000001"
        assert ev["twitter_thread_id"] == "tw-thread-happy"

    def test_self_sent_dm_does_not_emit(self, tmp_ledger):
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-self")
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-self",
            "messages": [
                {"body": "outbound", "from_self": True,
                 "message_id": "out"},
            ],
        })
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []

    def test_unknown_thread_does_not_emit(self, tmp_ledger):
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-mine")
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-stranger",
            "messages": [
                {"body": "random", "from_self": False, "message_id": "m"},
            ],
        })
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []


class TestPassJIdempotence:

    def test_rerun_does_not_emit_duplicate(self, tmp_ledger):
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-idem")
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-idem",
            "messages": [
                {"body": "r", "from_self": False, "message_id": "tw-idem-1"},
            ],
        })
        r1 = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(r1.synthesized) == 1
        r2 = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert r2.synthesized == []


class TestPassJChannelDiscipline:

    def test_emit_always_carries_channel_twitter(self, tmp_ledger):
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-ch")
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-ch",
            "messages": [{"body": "r", "from_self": False, "message_id": "m"}],
        })
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "twitter"


class TestPassJFailureModes:

    def test_fetch_exception_recorded_no_emit(self, tmp_ledger):
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-fail")
        tw = FakeTwitter()
        tw.fail_list_dms = RuntimeError("Twitter cookie-scrape rate-limit")
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert "rate-limit" in result.errors[0]

    def test_non_list_response_recorded(self, tmp_ledger):
        """Per the Week 3 per-week reviewer's P3-A finding — Pass J was
        missing the non-list-response defensive-branch test that Pass H
        + Pass I cover. The defensive code lives in
        ``_run_channel_dm_reply_pass`` so Pass I + Pass J share the same
        branch; this test pins the contract per-pass for the operator-
        facing failure-mode discipline (every failure mode tested per
        channel)."""
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-bad")

        class WeirdShape:
            def list_recent_dms(self, limit=100):
                return {"not": "a list"}

        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=WeirdShape(),
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert "non-list" in result.errors[0]

    def test_message_without_from_self_treated_defensively_no_emit(
        self, tmp_ledger,
    ):
        """Defensive: a Twitter DM without from_self tagging defaults to
        skip (matches Pass I's posture; the shared helper applies the
        same rule). Mirrors `TestPassIFailureModes::
        test_message_without_from_self_treated_defensively_no_emit`."""
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-amb")
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-amb",
            "messages": [
                # No from_self field.
                {"body": "ambiguous", "message_id": "tw-amb"},
            ],
        })
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []


class TestPassJDryRun:
    """Mirrors TestPassIDryRun for completeness per the per-channel
    discipline (every Pass H/I/J failure mode covered uniformly)."""

    def test_dry_run_does_not_persist(self, tmp_ledger):
        _seed_tw_dm_confirmed(tmp_ledger, thread_id="tw-thread-dry")
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-dry",
            "messages": [
                {"body": "r", "from_self": False, "message_id": "tw-dry-1"},
            ],
        })
        result = _reconcile.run_pass_j(
            led=tmp_ledger, twitter=tw,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0].get("_dry_run") is True
        events = [e for e in tmp_ledger.all_events()
                  if e.get("type") == "tw_dm_reply_received"]
        assert events == []


# ===========================================================================
# Pass G consumes Week 3's new reply event types (ADR-0027 D112)
# ===========================================================================


class TestPassGConsumesWeek3ReplyTypes:
    """Per ADR-0027 D112 — Pass G's filter widens from
    ``type == "reply_received"`` (Week 2) to the closed-set
    REPLY_EVENT_TYPES (Week 2 + Week 3). End-to-end pipeline test.
    """

    def _classifier(self, tmp_path) -> _classifier.RuleBasedClassifier:
        # Minimal classifier — unsubscribe + interest patterns.
        return _classifier.RuleBasedClassifier(
            unsubscribe_patterns=[r"\bunsubscribe\b"],
            interest_patterns=[r"\bsounds great\b"],
        )

    def test_pass_g_classifies_li_invite_reply_received(
        self, tmp_ledger, tmp_path,
    ):
        c = self._classifier(tmp_path)
        # Seed a Week 3 LinkedIn invite reply event (as Pass H would emit).
        tmp_ledger.append({
            "type": "li_invite_reply_received",
            "person_id": "p-li-inv",
            "channel": "linkedin",
            "reply_message_id": "li_accept:inv-w3-1",
            "reply_to_intent_id": "snd_LIINVITEW3_REPLY00000001",
            "linkedin_invitation_id": "inv-w3-1",
            "snippet": "sounds great, would love to connect",
            "ts": _old_ts(30),
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "reply_classified"
        assert ev["channel"] == "linkedin"
        assert ev["reply_message_id"] == "li_accept:inv-w3-1"

    def test_pass_g_classifies_li_dm_reply_received(
        self, tmp_ledger, tmp_path,
    ):
        c = self._classifier(tmp_path)
        tmp_ledger.append({
            "type": "li_dm_reply_received",
            "person_id": "p-li-dm",
            "channel": "linkedin",
            "reply_message_id": "li-msg-w3-1",
            "reply_to_intent_id": "snd_LIDMW3_REPLY000000000001",
            "linkedin_thread_id": "li-thread-w3",
            "snippet": "please unsubscribe",
            "ts": _old_ts(30),
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["channel"] == "linkedin"
        assert ev["category"] == "unsubscribe"
        assert ev["classification_method"] == "rule"

    def test_pass_g_classifies_tw_dm_reply_received(
        self, tmp_ledger, tmp_path,
    ):
        c = self._classifier(tmp_path)
        tmp_ledger.append({
            "type": "tw_dm_reply_received",
            "person_id": "p-tw-dm",
            "channel": "twitter",
            "reply_message_id": "tw-msg-w3-1",
            "reply_to_intent_id": "snd_TWDMW3_REPLY000000000001",
            "twitter_thread_id": "tw-thread-w3",
            "snippet": "sounds great",
            "ts": _old_ts(30),
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["channel"] == "twitter"
        assert ev["category"] == "interest"

    def test_idempotence_across_channels(self, tmp_ledger, tmp_path):
        """Per ADR-0026 D104 — the (mid, channel) pair is the
        discriminator across channels. Pass G is idempotent over
        Week 3's new reply event types."""
        c = self._classifier(tmp_path)
        tmp_ledger.append({
            "type": "li_dm_reply_received",
            "person_id": "p-idem",
            "channel": "linkedin",
            "reply_message_id": "msg-idem-1",
            "reply_to_intent_id": "snd_LIDMIDEM0000000000000001",
            "linkedin_thread_id": "li-thread-idem",
            "snippet": "please unsubscribe",
            "ts": _old_ts(30),
        })
        r1 = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert len(r1.synthesized) == 1
        r2 = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert r2.synthesized == []


# ===========================================================================
# Pass H/I/J orchestration via reconcile()
# ===========================================================================


class TestPassHIJOrchestration:

    def test_reconcile_h_without_linkedin_records_error(self, tmp_ledger):
        result = _reconcile.reconcile(
            passes="H",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, linkedin=None, persist_status=False,
        )
        assert result.passes[0].pass_name == "H"
        assert "LinkedIn" in result.passes[0].errors[0]

    def test_reconcile_i_without_linkedin_records_error(self, tmp_ledger):
        result = _reconcile.reconcile(
            passes="I",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, linkedin=None, persist_status=False,
        )
        assert result.passes[0].pass_name == "I"
        assert "LinkedIn" in result.passes[0].errors[0]

    def test_reconcile_j_without_twitter_records_error(self, tmp_ledger):
        result = _reconcile.reconcile(
            passes="J",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, twitter=None, persist_status=False,
        )
        assert result.passes[0].pass_name == "J"
        assert "Twitter" in result.passes[0].errors[0]

    def test_all_passes_chain_with_real_clients(self, tmp_ledger, tmp_path):
        """End-to-end full-chain test: D→H→E→I→F→J→G orchestrated via
        reconcile() with fake clients + a real classifier. The chain
        produces invite-acceptance + DM-reply events that Pass G
        classifies."""
        # Seed substrate.
        _seed_li_invite_confirmed(
            tmp_ledger,
            intent_id="snd_E2E_LIINV01CONFIRM0000000",
            invitation_id="inv-e2e-1",
        )
        _seed_li_dm_confirmed(
            tmp_ledger,
            intent_id="snd_E2E_LIDM01CONFIRM00000001",
            thread_id="li-thread-e2e",
        )
        _seed_tw_dm_confirmed(
            tmp_ledger,
            intent_id="snd_E2E_TWDM01CONFIRM00000001",
            thread_id="tw-thread-e2e",
        )

        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-e2e-1",
            "status": "accepted",
        })
        li.conversations.append({
            "thread_id": "li-thread-e2e",
            "messages": [
                {"body": "please unsubscribe", "from_self": False,
                 "message_id": "li-msg-e2e"},
            ],
        })
        tw = FakeTwitter()
        tw.dms.append({
            "thread_id": "tw-thread-e2e",
            "messages": [
                {"body": "sounds great", "from_self": False,
                 "message_id": "tw-msg-e2e"},
            ],
        })
        classifier = _classifier.RuleBasedClassifier(
            unsubscribe_patterns=[r"\bunsubscribe\b"],
            interest_patterns=[r"\bsounds great\b"],
        )

        # Run H + I + J + G in chain. (D/E/F not needed — the confirmed
        # events are already in the ledger.)
        result = _reconcile.reconcile(
            passes="H,I,J,G",
            since=datetime.now(timezone.utc) - timedelta(hours=2),
            led=tmp_ledger, linkedin=li, twitter=tw, classifier=classifier,
            apply=True, persist_status=False,
        )
        # 4 passes ran.
        assert len(result.passes) == 4
        # 3 reply events emitted (one per channel) + 3 classified
        # events (Pass G).
        types_by_pass = {pr.pass_name: pr for pr in result.passes}
        assert types_by_pass["H"].synthesized[0]["type"] == \
            "li_invite_reply_received"
        assert types_by_pass["I"].synthesized[0]["type"] == \
            "li_dm_reply_received"
        assert types_by_pass["J"].synthesized[0]["type"] == \
            "tw_dm_reply_received"
        g_synth = types_by_pass["G"].synthesized
        assert len(g_synth) == 3
        # Verify per-channel classification.
        by_channel = {ev["channel"]: ev for ev in g_synth}
        assert set(by_channel.keys()) == {"linkedin", "twitter"}
        # The two LinkedIn events (invite-accept + DM-reply) BOTH carry
        # channel=linkedin; gather by reply_message_id for distinction.
        li_classifications = [
            ev for ev in g_synth if ev["channel"] == "linkedin"
        ]
        assert len(li_classifications) == 2
        # The DM reply with "please unsubscribe" → category=unsubscribe.
        unsub_evs = [
            ev for ev in li_classifications
            if ev["category"] == "unsubscribe"
        ]
        assert len(unsub_evs) == 1
        # Twitter event with "sounds great" → category=interest.
        tw_ev = by_channel["twitter"]
        assert tw_ev["category"] == "interest"
