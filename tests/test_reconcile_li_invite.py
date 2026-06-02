"""Pillar C Week 4 — reconcile Pass D (LinkedIn invites) direct unit tests.

Mirrors ``tests/test_reconcile.py::TestPassA``'s shape modulo:

* LinkedIn client surface (not Gmail) — see ``FakeLinkedIn`` below.
* Intent type ``li_invite_intent``; outcome types ``li_invite_confirmed``
  / ``li_invite_aborted``.
* Marker-scan against connection-note text (not email body / header).
* Channel-on-every-event invariant (per ADR-0014 D33).

Covers the verification surface ADR-0017 D48-D52 names:

* D48 — serial execution semantics (cross-pass integration in
  ``tests/test_reconcile.py``).
* D49 — marker-scan window / scan_limit parameterization.
* D50 — marker-not-found semantics (abort after grace period).
* D51 — existing-operator-seed-shape persistence is via the integrating
  status file (covered in ``tests/test_reconcile.py::TestOrchestration``).
* D52 — downstream pillar impact is an ADR concern only.
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


def _seed_li_invite_intent(
    led, *, intent_id, person_id="alice-anderson-li",
    linkedin_url="https://www.linkedin.com/in/test/",
    register="cold-pitch",
    ts_minutes_ago: int = 10,
):
    led.append({
        "type": "li_invite_intent",
        "intent_id": intent_id,
        "person_id": person_id,
        "channel": "linkedin",
        "linkedin_url": linkedin_url,
        "register": register,
        "ts": _old_ts(ts_minutes_ago),
    })


# Zero-width-space character (U+200B) per ADR-0015 D39 + ADR-0016 D43.
ZWS = "​"


def _li_marker(intent_id: str) -> str:
    """The on-the-wire marker shape per ADR-0015 D39."""
    return f"{ZWS}outreach-intent:{intent_id}{ZWS}"


class FakeLinkedIn:
    """Drop-in for tests.

    ``invitations`` is the list returned by ``list_sent_invitations``;
    ``conversations`` is the list returned by ``list_recent_conversations``
    (covered by the Pass E test module).

    ``fail_list_invitations`` / ``fail_list_conversations`` inject
    failures into the LinkedIn surface to exercise the pass's error-
    handling posture per ADR-0017 D50.
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


# ---------------------------------------------------------------------------
# Pass D — happy paths
# ---------------------------------------------------------------------------


class TestPassDHappyPath:

    def test_empty_ledger_no_emissions(self, tmp_ledger):
        """No open LinkedIn invite intents → no emissions."""
        li = FakeLinkedIn()
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []
        assert result.errors == []
        # ADR-0017 D49 forecloses the wasted MCP fetch when no orphans
        # exist — list_sent_invitations is NOT called.
        assert li.list_invitations_calls == []

    def test_single_intent_marker_match_emits_confirmed(self, tmp_ledger):
        """A matching invitation's note text → emit li_invite_confirmed
        with channel=linkedin + _recovered_by=reconcile."""
        iid = "snd_LIINVITEMATCH00000000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-001",
            "note": f"hey there — wanted to connect.{_li_marker(iid)}",
            "created_at": _old_ts(8),
        })
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "li_invite_confirmed"
        assert ev["intent_id"] == iid
        assert ev["channel"] == "linkedin"
        assert ev["_recovered_by"] == "reconcile"
        assert ev["linkedin_invitation_id"] == "inv-001"
        assert ev["linkedin_url"] == "https://www.linkedin.com/in/test/"
        # Persisted in the ledger as the outcome for the intent.
        outcome = tmp_ledger.outcome_for_intent(iid)
        assert outcome is not None
        assert outcome.type == "li_invite_confirmed"

    def test_intent_no_match_old_enough_emits_aborted(self, tmp_ledger):
        """Per ADR-0017 D50: no matching invitation marker AND intent
        older than min_intent_age → emit li_invite_aborted."""
        iid = "snd_LIINVITENOMATCH0000000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid, ts_minutes_ago=10)
        li = FakeLinkedIn()
        # No invitations returned — simulate "not in the most-recent N".
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "li_invite_aborted"
        assert ev["intent_id"] == iid
        assert ev["channel"] == "linkedin"
        assert ev["_recovered_by"] == "reconcile"
        assert "no_linkedin_invitation_match" in ev["reason"]

    def test_intent_no_match_too_young_skipped(self, tmp_ledger):
        """Intent younger than min_intent_age → no emission yet
        (within the normal send-completion grace window)."""
        iid = "snd_LIINVITEYOUNG000000000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid, ts_minutes_ago=1)
        li = FakeLinkedIn()
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        # Examined but not synthesized.
        assert result.examined == 1
        assert result.synthesized == []
        # Outcome stays open.
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_mixed_match_and_no_match(self, tmp_ledger):
        """A mix of matched + missing intents: matched → confirmed,
        missing-and-old → aborted, missing-and-young → skipped."""
        li = FakeLinkedIn()
        # 2 matched (have invitations)
        matched_ids = []
        for i in range(2):
            iid = f"snd_LIINVITEMIX{i:02d}MATCH00000000"
            matched_ids.append(iid)
            _seed_li_invite_intent(tmp_ledger, intent_id=iid)
            li.invitations.append({
                "invitation_id": f"inv-mix-{i}",
                "note": f"note {i}{_li_marker(iid)}",
                "created_at": _old_ts(8),
            })
        # 2 missing-and-old
        missing_old_ids = []
        for i in range(2):
            iid = f"snd_LIINVITEMIX{i:02d}MISSINGOLD0"
            missing_old_ids.append(iid)
            _seed_li_invite_intent(
                tmp_ledger, intent_id=iid, ts_minutes_ago=20,
            )
        # 1 missing-and-young
        young_iid = "snd_LIINVITEMIX01MISSINGYOUNG"
        _seed_li_invite_intent(
            tmp_ledger, intent_id=young_iid, ts_minutes_ago=1,
        )

        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        confirms = [e for e in result.synthesized if e["type"] == "li_invite_confirmed"]
        aborts = [e for e in result.synthesized if e["type"] == "li_invite_aborted"]
        assert {e["intent_id"] for e in confirms} == set(matched_ids)
        assert {e["intent_id"] for e in aborts} == set(missing_old_ids)
        # Young not in outcomes at all.
        assert tmp_ledger.outcome_for_intent(young_iid) is None

    def test_confirmed_omits_invitation_id_when_surface_omits_it(
        self, tmp_ledger,
    ):
        """Some MCP backends return only note text on the invitation
        record; the confirmed event must still emit (with no invitation_id)."""
        iid = "snd_LIINVITENOINVID00000000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.invitations.append({
            # No invitation_id key.
            "note": f"hello.{_li_marker(iid)}",
            "created_at": _old_ts(8),
        })
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "li_invite_confirmed"]
        assert len(confirms) == 1
        assert "linkedin_invitation_id" not in confirms[0]
        assert confirms[0]["channel"] == "linkedin"


# ---------------------------------------------------------------------------
# Pass D — execution + dry-run + idempotence + boundary
# ---------------------------------------------------------------------------


class TestPassDExecution:

    def test_dry_run_no_ledger_writes(self, tmp_ledger):
        """Dry-run reports findings; ledger is unchanged."""
        iid = "snd_LIINVITEDRYRUN00000000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        # No invitations → would abort under apply.
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=False,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0]["_dry_run"] is True
        # Ledger has no outcome for the intent.
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_idempotent_under_re_run(self, tmp_ledger):
        """After Pass D commits an outcome, a second Pass D doesn't
        re-emit a duplicate (the indexer no longer surfaces the intent
        as 'open')."""
        iid = "snd_LIINVITEIDEMPOTENT00000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        # Run once → aborts (no matching invitation).
        result_1 = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert len(result_1.synthesized) == 1
        # Run again → nothing to do; intent now has an outcome.
        result_2 = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result_2.examined == 0
        assert result_2.synthesized == []

    def test_min_age_filter_uses_intent_ts(self, tmp_ledger):
        """min_intent_age controls the abort-vs-skip decision per D50;
        the intent's ts (not the LinkedIn timestamp) is the source."""
        iid_young = "snd_LIINVITEYOUNGAGE00000001"
        iid_old = "snd_LIINVITEOLDAGE0000000001"
        _seed_li_invite_intent(
            tmp_ledger, intent_id=iid_young, ts_minutes_ago=2,
        )
        _seed_li_invite_intent(
            tmp_ledger, intent_id=iid_old, ts_minutes_ago=30,
        )
        li = FakeLinkedIn()
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=10),
        )
        # Only the old one aborts.
        seen = [e.get("intent_id") for e in result.synthesized]
        assert iid_old in seen
        assert iid_young not in seen

    def test_scan_limit_propagated_to_linkedin_call(self, tmp_ledger):
        """D49 — scan_limit kwarg is what reaches list_sent_invitations."""
        iid = "snd_LIINVITESCANLIMIT00000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, scan_limit=50,
        )
        assert li.list_invitations_calls == [50]

    def test_default_scan_limit_is_100(self, tmp_ledger):
        """ADR-0017 D49 — the default LINKEDIN_DEFAULT_SCAN_LIMIT is 100."""
        iid = "snd_LIINVITEDEFAULTLIMIT0000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert li.list_invitations_calls == [100]


# ---------------------------------------------------------------------------
# Pass D — channel discipline + cross-channel isolation
# ---------------------------------------------------------------------------


class TestPassDChannelDiscipline:

    def test_does_not_examine_email_intents(self, tmp_ledger):
        """An open send_intent (channel=email) is NOT examined by Pass D
        — channel filter is load-bearing per ADR-0014 D33."""
        email_iid = "snd_EMAILINTENTPASSD00000001"
        tmp_ledger.append({
            "type": "send_intent", "intent_id": email_iid,
            "person_id": "alice-anderson-li", "channel": "email",
            "ts": _old_ts(10),
        })
        li = FakeLinkedIn()
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        # The email intent stays open.
        assert tmp_ledger.outcome_for_intent(email_iid) is None

    def test_does_not_examine_li_dm_intents(self, tmp_ledger):
        """An open li_dm_intent (channel=linkedin) is NOT examined by
        Pass D — Pass E handles DMs. Per ADR-0014 D33's per-action
        prefix discrimination."""
        dm_iid = "snd_LIDMINTENTPASSD000000001"
        tmp_ledger.append({
            "type": "li_dm_intent", "intent_id": dm_iid,
            "person_id": "dana-davis-li", "channel": "linkedin",
            "ts": _old_ts(10),
        })
        li = FakeLinkedIn()
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 0
        assert tmp_ledger.outcome_for_intent(dm_iid) is None

    def test_emitted_confirmed_always_carries_channel_linkedin(
        self, tmp_ledger,
    ):
        """ADR-0014 D33 invariant — every emission stamps channel=linkedin
        regardless of whether the LinkedIn surface returned an invitation_id."""
        iid = "snd_LIINVITECHANINVAR0000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-chan",
            "note": _li_marker(iid),
        })
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "linkedin"

    def test_emitted_aborted_always_carries_channel_linkedin(
        self, tmp_ledger,
    ):
        """Per ADR-0017 + ADR-0014 D33 invariant for the abort path."""
        iid = "snd_LIINVITECHANABORT0000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        for ev in result.synthesized:
            assert ev["channel"] == "linkedin"
            assert ev["_recovered_by"] == "reconcile"


# ---------------------------------------------------------------------------
# Pass D — failure modes
# ---------------------------------------------------------------------------


class TestPassDFailureModes:

    def test_linkedin_fetch_exception_recorded_no_emission(self, tmp_ledger):
        """A LinkedIn fetch exception is recorded in errors + the pass
        emits nothing (per ADR-0017 D50's posture — better to skip the
        pass than to wrongly abort intents because of an outage)."""
        iid = "snd_LIINVITEFETCHFAIL00000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.fail_list_invitations = RuntimeError("LinkedIn MCP rate-limited")
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert len(result.errors) == 1
        assert "rate-limited" in result.errors[0]
        # Intent stays open.
        assert tmp_ledger.outcome_for_intent(iid) is None

    def test_linkedin_returns_non_list_recorded_no_emission(self, tmp_ledger):
        """An MCP backend that returns a dict instead of a list shouldn't
        crash the pass — record the error + return early."""
        iid = "snd_LIINVITENONLIST00000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()

        class WeirdShape:
            def list_sent_invitations(self, limit=100):
                return {"oops": "not a list"}

            def list_recent_conversations(self, limit=100):
                return []

        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=WeirdShape(),
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.synthesized == []
        assert len(result.errors) == 1
        assert "non-list" in result.errors[0]

    def test_marker_scan_recovers_when_zws_stripped(self, tmp_ledger):
        """Defense in depth — if the operator (or LinkedIn UI) strips
        the surrounding ZWS chars from the marker, the regex fallback
        still recovers the intent_id."""
        iid = "snd_LIINVITESTRIPPEDZWS00001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        # Marker without surrounding ZWS — just the bare token.
        li.invitations.append({
            "invitation_id": "inv-stripped",
            "note": f"hey\nP.S. outreach-intent:{iid}",
        })
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        confirms = [e for e in result.synthesized if e["type"] == "li_invite_confirmed"]
        assert len(confirms) == 1
        assert confirms[0]["linkedin_invitation_id"] == "inv-stripped"

    def test_invitation_without_note_does_not_false_positive(self, tmp_ledger):
        """An invitation with no note text shouldn't match anything."""
        iid = "snd_LIINVITENONOTE0000000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        li.invitations.append({
            "invitation_id": "inv-empty",
            # No note key.
        })
        li.invitations.append({
            "invitation_id": "inv-nullnote",
            "note": None,
        })
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # Falls through to abort (intent stays unmatched).
        aborts = [e for e in result.synthesized if e["type"] == "li_invite_aborted"]
        assert len(aborts) == 1

    def test_marker_for_different_intent_does_not_match(self, tmp_ledger):
        """The marker scan compares the orphan intent_id against
        invitation-note text, NOT vice versa — a different intent_id
        in the note shouldn't false-positive."""
        iid = "snd_LIINVITEMINE000000000001"
        other_iid = "snd_LIINVITEOTHER00000000001"
        _seed_li_invite_intent(tmp_ledger, intent_id=iid)
        li = FakeLinkedIn()
        # Invitation contains a DIFFERENT intent_id's marker.
        li.invitations.append({
            "invitation_id": "inv-other",
            "note": f"different intent:{_li_marker(other_iid)}",
        })
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # No match for the orphan → abort.
        aborts = [e for e in result.synthesized if e["type"] == "li_invite_aborted"]
        assert len(aborts) == 1
        assert aborts[0]["intent_id"] == iid


# ---------------------------------------------------------------------------
# Pass D — orchestration integration (the reconcile() wrapper)
# ---------------------------------------------------------------------------


class TestPassDUnparseableTs:
    """Per the Week 4 per-week review A-1 finding — verify the chokepoint
    behavior: bad-ts intents are filtered by ``led.open_intents`` (its
    ``fromisoformat`` check skips them), so they never reach the pass's
    abort-after-grace branch. The intent stays open in the ledger;
    operator manual inspection (`python orchestrator/ledger.py
    healthcheck`) surfaces the unparseable-ts intent for repair."""

    def test_unparseable_ts_intent_filtered_by_open_intents(self, tmp_ledger):
        """An intent with a corrupt / unparseable ts is excluded from
        ``open_intents`` (per ledger.py's ``fromisoformat`` guard); the
        pass examines 0 intents and emits nothing. The bad-ts intent
        stays open in the ledger for operator-manual repair via the
        healthcheck CLI."""
        iid = "snd_LIINVITEBADTS00000000001"
        tmp_ledger.append({
            "type": "li_invite_intent",
            "intent_id": iid,
            "person_id": "alice-anderson-li",
            "channel": "linkedin",
            "linkedin_url": "https://www.linkedin.com/in/test/",
            "register": "cold-pitch",
            "ts": "not-a-timestamp",
        })
        li = FakeLinkedIn()
        result = _reconcile.run_pass_d(
            led=tmp_ledger, linkedin=li,
            since=datetime.now(timezone.utc) - timedelta(days=365),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        # open_intents filtered out the bad-ts intent BEFORE the pass
        # saw it; examined count is 0; no emission.
        assert result.examined == 0
        assert result.synthesized == []
        assert result.errors == []
        # The bad-ts intent stays open in the ledger.
        assert tmp_ledger.outcome_for_intent(iid) is None


class TestPassDOrchestration:

    def test_reconcile_d_without_linkedin_records_error(self, tmp_ledger):
        """A request for Pass D without a LinkedIn client → recorded
        as error; pass shape returns with the explicit message."""
        result = _reconcile.reconcile(
            passes="D",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, linkedin=None, persist_status=False,
        )
        assert result.passes[0].pass_name == "D"
        assert len(result.passes[0].errors) == 1
        assert "LinkedIn" in result.passes[0].errors[0]

    def test_reconcile_d_serial_with_a_and_e(self, tmp_ledger):
        """Per ADR-0017 D48 — order of execution matches passes
        argument; A→D→E sequence is the recommended full-LinkedIn
        run when both email + LinkedIn passes are wanted."""
        result = _reconcile.reconcile(
            passes="A,D,E",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            led=tmp_ledger, gmail=None, linkedin=None,
            persist_status=False,
        )
        # All three passes invoked (each records the missing-dep error).
        assert [p.pass_name for p in result.passes] == ["A", "D", "E"]

    def test_pass_d_in_all_passes_set(self):
        """D is a recognized pass name."""
        assert "D" in _reconcile.ALL_PASSES
