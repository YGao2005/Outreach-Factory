"""Phase 5.5 Week 3 — reconcile passes.

Covers all three passes + status persistence + needs_quick_reconcile gate
logic. The Gmail surface is a small in-test fake (see FakeGmail) — same
shape as the one in test_send_gate.py; duplicated here so each test file
remains self-contained.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import identity  # noqa: F401
import ledger as _ledger
import reconcile as _reconcile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(d))
    return _ledger.Ledger(d)


@pytest.fixture
def tmp_status_dir(tmp_path, monkeypatch):
    d = tmp_path / "reconcile"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_RECONCILE_DIR", str(d))
    return d


@pytest.fixture
def people_dir(tmp_path):
    d = tmp_path / "people"
    d.mkdir()
    return d


def _old_ts(minutes: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)) \
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _write_person(people_dir: Path, *, name: str, person_id: str,
                  email: str, linkedin: str | None = None,
                  pipeline_stage: str | None = None) -> Path:
    note = people_dir / f"{name}.md"
    li_line = f"  linkedin: {linkedin}\n" if linkedin else ""
    stage_line = f"pipeline_stage: {pipeline_stage}\n" if pipeline_stage else ""
    note.write_text(
        "---\n"
        "type: person\n"
        f"id: {person_id}\n"
        "identity_keys:\n"
        f"{li_line}"
        "  emails:\n"
        f"    - {email}\n"
        f"name: {name}\n"
        + stage_line +
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    return note


class FakeGmail:
    """Drop-in for tests; same shape as the test_send_gate FakeGmail.

    Holds a list of `sent` messages (used for Pass A search) and an
    `extra_thread_messages` dict for injecting inbound messages on threads
    (used for Pass B's DSN/reply scenarios).
    """

    def __init__(self, sender_email: str = "me@example.test"):
        self.sender_email = sender_email
        self.sent: list[dict] = []
        self.extra_thread_messages: dict[str, list[dict]] = {}

    def search_messages(self, query: str, max_results: int = 100) -> list[dict]:
        q = query.strip('"').strip("'")
        hits = []
        for m in self.sent:
            if q in (m.get("body") or "") or \
                    q in m.get("headers", {}).get("X-Outreach-Intent-Id", ""):
                hits.append({"id": m["id"], "threadId": m["threadId"]})
                if len(hits) >= max_results:
                    break
        return hits

    def get_message(self, msg_id: str) -> dict | None:
        for m in self.sent:
            if m["id"] == msg_id:
                return self._wrap(m)
        for msgs in self.extra_thread_messages.values():
            for m in msgs:
                if m.get("id") == msg_id:
                    return self._wrap(m)
        return None

    def get_thread(self, thread_id: str) -> dict | None:
        msgs = [self._wrap(m) for m in self.sent if m["threadId"] == thread_id]
        msgs.extend(self._wrap(m)
                    for m in self.extra_thread_messages.get(thread_id, []))
        if not msgs:
            return None
        return {"id": thread_id, "messages": msgs}

    @staticmethod
    def _wrap(m: dict) -> dict:
        hdrs = [{"name": k, "value": v}
                for k, v in (m.get("headers") or {}).items()]
        for k in ("to", "subject", "from"):
            if k in m and k.lower() not in {h["name"].lower() for h in hdrs}:
                hdrs.append({"name": k.title(), "value": m[k]})
        return {
            "id": m["id"], "threadId": m.get("threadId", ""),
            "payload": {"headers": hdrs},
            "body": m.get("body", ""),
        }


# ---------------------------------------------------------------------------
# Pass A — Ledger ↔ Gmail
# ---------------------------------------------------------------------------


class TestPassA:

    def test_five_match_five_missing(self, tmp_ledger):
        gmail = FakeGmail()
        matched_intents = []
        missing_intents = []
        for i in range(5):
            iid = f"snd_MATCH{i:02d}TEST{i:02d}TEST{i:02d}T"
            matched_intents.append(iid)
            tmp_ledger.append({
                "type": "send_intent", "intent_id": iid,
                "person_id": f"matched-{i}-li", "channel": "email",
                "email": f"m{i}@x.test", "ts": _old_ts(),
            })
            gmail.sent.append({
                "id": f"gid-match-{i}", "threadId": f"tid-match-{i}",
                "to": f"m{i}@x.test", "subject": "Hi",
                "body": f"body\n\noutreach-intent:{iid}\n",
                "headers": {"X-Outreach-Intent-Id": iid},
            })
        for i in range(5):
            iid = f"snd_MISS{i:02d}TEST{i:02d}TEST{i:02d}TST"
            missing_intents.append(iid)
            tmp_ledger.append({
                "type": "send_intent", "intent_id": iid,
                "person_id": f"missing-{i}-li", "channel": "email",
                "email": f"x{i}@x.test", "ts": _old_ts(),
            })

        result = _reconcile.run_pass_a(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        assert result.examined == 10
        confirms = [e for e in result.synthesized if e["type"] == "send_confirmed"]
        aborts = [e for e in result.synthesized if e["type"] == "send_aborted"]
        assert len(confirms) == 5
        assert len(aborts) == 5
        # All confirmed intents map back to ledger outcome.
        for iid in matched_intents:
            outcome = tmp_ledger.outcome_for_intent(iid)
            assert outcome is not None and outcome.type == "send_confirmed"
        # All missing intents marked aborted.
        for iid in missing_intents:
            outcome = tmp_ledger.outcome_for_intent(iid)
            assert outcome is not None and outcome.type == "send_aborted"

    def test_dry_run_no_writes(self, tmp_ledger):
        iid = "snd_DRYRUNDRYRUNDRYRUNDRYRUN0"
        tmp_ledger.append({
            "type": "send_intent", "intent_id": iid,
            "person_id": "dry-li", "channel": "email", "ts": _old_ts(),
        })
        gmail = FakeGmail()
        result = _reconcile.run_pass_a(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=False,
        )
        assert result.synthesized   # reported
        # No outcome written.
        assert tmp_ledger.outcome_for_intent(iid) is None
        # Outcome shapes carry the _dry_run marker
        assert all(e.get("_dry_run") for e in result.synthesized)

    def test_min_age_filter(self, tmp_ledger):
        iid_young = "snd_YOUNGYOUNGYOUNGYOUNG12345"
        iid_old = "snd_OLDOLDOLDOLDOLDOLDOLD11111"
        tmp_ledger.append({
            "type": "send_intent", "intent_id": iid_young,
            "person_id": "y-li", "channel": "email",
            "ts": _old_ts(1),
        })
        tmp_ledger.append({
            "type": "send_intent", "intent_id": iid_old,
            "person_id": "o-li", "channel": "email",
            "ts": _old_ts(10),
        })
        gmail = FakeGmail()
        result = _reconcile.run_pass_a(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True, min_intent_age=timedelta(minutes=5),
        )
        # Only old intent examined.
        seen = [e.get("intent_id") for e in result.synthesized]
        assert iid_old in seen
        assert iid_young not in seen

    def test_only_email_channel_intents_examined(self, tmp_ledger):
        """Pass A must filter ``open_intents`` to ``channel='email'``.

        Pillar C Week 12 fix: pre-fix, Pass A walked every channel's
        intent type (the index includes ``li_invite_intent`` /
        ``li_dm_intent`` / ``tw_dm_intent`` / ``calendar_booking_intent``
        per ADR-0014 D33) and synthesized wrong-typed ``send_aborted``
        events for non-email orphans. Surfaced by the 50-prospect
        exit-criterion stress test
        (``test_multi_channel_coherence.py::TestExitCriterion``). The
        fix: ``run_pass_a`` now passes ``channel='email'`` to
        ``led.open_intents``, mirroring Pass D/E/F's discipline.
        """
        # One email orphan (Pass A should pick this up).
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_EMAILONLY01EMAILONLY01EM",
            "person_id": "email-li", "channel": "email",
            "ts": _old_ts(10),
        })
        # One LinkedIn invite orphan (Pass A must NOT touch — that's
        # Pass D's job).
        tmp_ledger.append({
            "type": "li_invite_intent",
            "intent_id": "li_LINKEDINORPHAN01LINKEDINOR",
            "person_id": "li-li", "channel": "linkedin",
            "ts": _old_ts(10),
        })
        # One Twitter DM orphan (Pass A must NOT touch — Pass F).
        tmp_ledger.append({
            "type": "tw_dm_intent",
            "intent_id": "tw_TWITTERORPHAN01TWITTERORPH",
            "person_id": "tw-li", "channel": "twitter",
            "ts": _old_ts(10),
        })
        gmail = FakeGmail()
        result = _reconcile.run_pass_a(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            apply=True,
        )
        # Exactly ONE intent examined — the email orphan. Pre-fix the
        # count was 3 (all channels' intents). The per-channel intents
        # must remain untouched in the ledger so Pass D / F can recover
        # them via their own per-channel logic.
        assert result.examined == 1
        seen_intent_ids = {e.get("intent_id") for e in result.synthesized}
        assert "snd_EMAILONLY01EMAILONLY01EM" in seen_intent_ids
        assert "li_LINKEDINORPHAN01LINKEDINOR" not in seen_intent_ids
        assert "tw_TWITTERORPHAN01TWITTERORPH" not in seen_intent_ids
        # No wrong-typed send_aborted landed for the non-email orphans.
        assert tmp_ledger.outcome_for_intent(
            "li_LINKEDINORPHAN01LINKEDINOR",
        ) is None
        assert tmp_ledger.outcome_for_intent(
            "tw_TWITTERORPHAN01TWITTERORPH",
        ) is None


# ---------------------------------------------------------------------------
# Pass B — Inbox ↔ Ledger
# ---------------------------------------------------------------------------


class TestPassB:

    def _seed_send(self, tmp_ledger, gmail, *, person_id="p-li",
                   thread_id="tid-1", message_id="gid-1",
                   email="p@x.test"):
        iid = "snd_SENTSENTSENTSENTSENTSENT1"
        tmp_ledger.append({
            "type": "send_intent", "intent_id": iid,
            "person_id": person_id, "channel": "email", "email": email,
            "ts": _old_ts(60),
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": iid,
            "person_id": person_id, "channel": "email",
            "gmail_message_id": message_id, "gmail_thread_id": thread_id,
            "email": email,
        })
        gmail.sent.append({
            "id": message_id, "threadId": thread_id,
            "to": email, "from": gmail.sender_email,
            "subject": "Hi",
            "body": "hello\n", "headers": {},
        })

    def test_dsn_detected(self, tmp_ledger):
        gmail = FakeGmail()
        self._seed_send(tmp_ledger, gmail, person_id="bounced-li",
                        thread_id="tid-bounce", message_id="gid-bounce",
                        email="bounced@x.test")
        gmail.extra_thread_messages["tid-bounce"] = [{
            "id": "inbound-bounce-1", "threadId": "tid-bounce",
            "from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
            "to": gmail.sender_email,
            "subject": "Delivery Status Notification (Failure)",
            "body": "could not deliver",
            "headers": {},
        }]
        result = _reconcile.run_pass_b(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        bounces = [e for e in result.synthesized if e["type"] == "bounce_detected"]
        assert len(bounces) == 1
        assert bounces[0]["person_id"] == "bounced-li"
        assert bounces[0]["gmail_thread_id"] == "tid-bounce"
        # ADR-0025 D96 + Pillar D Week 1 P2-A fix: Pass B's emitted
        # bounce events stamp channel=email so the Pillar D classifier
        # can discriminate per-channel without special-casing absent
        # channel. Mirrors ADR-0014 D33's channel-on-every-event
        # invariant extended to reply / bounce events.
        assert bounces[0]["channel"] == "email"

    def test_reply_detected(self, tmp_ledger):
        gmail = FakeGmail()
        self._seed_send(tmp_ledger, gmail, person_id="replied-li",
                        thread_id="tid-reply", message_id="gid-reply",
                        email="replied@x.test")
        gmail.extra_thread_messages["tid-reply"] = [{
            "id": "inbound-reply-1", "threadId": "tid-reply",
            "from": "Replied <replied@x.test>",
            "to": gmail.sender_email,
            "subject": "Re: Hi",
            "body": "Hey thanks!", "headers": {},
        }]
        result = _reconcile.run_pass_b(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        replies = [e for e in result.synthesized if e["type"] == "reply_received"]
        assert len(replies) == 1
        assert replies[0]["person_id"] == "replied-li"
        # ADR-0025 D96 + Pillar D Week 1 P2-A fix.
        assert replies[0]["channel"] == "email"

    def test_reply_received_carries_channel_email(self, tmp_ledger):
        """ADR-0025 D96 + Pillar D Week 1 P2-A regression pin.

        Pillar D's classifier (Week 2-3) consumes ``*_reply_received``
        events with a ``channel`` discriminator. Without ``channel:
        "email"`` on Pass B's pre-Pillar-D-Week-1 reply emits, the
        classifier would either silently skip email replies or have
        to special-case "absent = email" everywhere. The Week 1 fix
        stamps the field; this test pins the contract — a future
        contributor reverting the stamp would fail loudly.

        Mirrors ``test_backfilled_send_confirmed_carries_channel_
        from_paired_intent`` in ``tests/test_migrations_ledger_0002.
        py`` (Pillar C Week 1 ADR-0014 D33 §"Backfill send_confirmed
        carries channel" regression).
        """
        gmail = FakeGmail()
        self._seed_send(tmp_ledger, gmail, person_id="ch-pin-li",
                        thread_id="tid-ch-pin",
                        message_id="gid-ch-pin",
                        email="ch-pin@x.test")
        gmail.extra_thread_messages["tid-ch-pin"] = [{
            "id": "inbound-ch-pin-1", "threadId": "tid-ch-pin",
            "from": "Reply <ch-pin@x.test>", "to": gmail.sender_email,
            "subject": "Re: Hi", "body": "ok", "headers": {},
        }]
        result = _reconcile.run_pass_b(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        replies = [e for e in result.synthesized
                   if e["type"] == "reply_received"]
        assert len(replies) == 1
        # The load-bearing assertion — Pillar D's classifier depends
        # on this field for per-channel discrimination.
        assert replies[0].get("channel") == "email", (
            f"reply_received must stamp channel=email per ADR-0025 D96; "
            f"got channel={replies[0].get('channel')!r}"
        )
        # Sanity: every reply_received in the synthesized batch carries
        # the field — not just the first one.
        for ev in replies:
            assert ev.get("channel") == "email"

    def test_bounce_detected_carries_channel_email(self, tmp_ledger):
        """ADR-0025 D96 + Pillar D Week 1 P2-A regression pin (bounce).

        Symmetric to ``test_reply_received_carries_channel_email`` —
        the bounce path also requires ``channel: "email"`` so the
        Pillar D classifier's bounce-as-dormant treatment can
        discriminate per-channel.
        """
        gmail = FakeGmail()
        self._seed_send(tmp_ledger, gmail, person_id="ch-bounce-li",
                        thread_id="tid-ch-bounce",
                        message_id="gid-ch-bounce",
                        email="ch-bounce@x.test")
        gmail.extra_thread_messages["tid-ch-bounce"] = [{
            "id": "inbound-ch-bounce-1", "threadId": "tid-ch-bounce",
            "from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
            "to": gmail.sender_email,
            "subject": "Delivery Status Notification (Failure)",
            "body": "delivery failed", "headers": {},
        }]
        result = _reconcile.run_pass_b(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        bounces = [e for e in result.synthesized
                   if e["type"] == "bounce_detected"]
        assert len(bounces) == 1
        assert bounces[0].get("channel") == "email", (
            f"bounce_detected must stamp channel=email per ADR-0025 D96; "
            f"got channel={bounces[0].get('channel')!r}"
        )

    def test_idempotent_skips_known_message_ids(self, tmp_ledger):
        gmail = FakeGmail()
        self._seed_send(tmp_ledger, gmail, person_id="idem-li",
                        thread_id="tid-idem", message_id="gid-idem",
                        email="idem@x.test")
        gmail.extra_thread_messages["tid-idem"] = [{
            "id": "inbound-idem-1", "threadId": "tid-idem",
            "from": "Reply <idem@x.test>", "to": gmail.sender_email,
            "subject": "Re: Hi", "body": "ok", "headers": {},
        }]
        # Run once → emits reply_received
        _reconcile.run_pass_b(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        # Run again → no new events (idempotent on gmail_message_id)
        result_again = _reconcile.run_pass_b(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert result_again.synthesized == []

    def test_skips_our_outbound(self, tmp_ledger):
        gmail = FakeGmail()
        self._seed_send(tmp_ledger, gmail, person_id="self-li",
                        thread_id="tid-self", message_id="gid-self",
                        email="someone@x.test")
        result = _reconcile.run_pass_b(
            led=tmp_ledger, gmail=gmail,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        # Only our outbound on the thread, no inbound → nothing emitted
        assert result.synthesized == []


# ---------------------------------------------------------------------------
# Pass C — Vault ↔ Ledger
# ---------------------------------------------------------------------------


class TestPassC:

    def test_heal_under_apply(self, tmp_ledger, people_dir):
        note = _write_person(
            people_dir, name="Alex Drift", person_id="alex-drift-li",
            email="alex@x.test", pipeline_stage="drafted",
        )
        # Ledger says: review_approved (stage=ready)
        tmp_ledger.append({
            "type": "review_approved", "person_id": "alex-drift-li",
            "ts": _old_ts(60),
        })
        # Pillar F Week 12 Layer 5 per ADR-0049 D262 — heal-to-ready
        # requires a `draft_ready` event (the Layer 4 emit-guard's per-
        # Person audit trail per ADR-0047 D246). The post-Week-12 heal
        # flow: review_approved + draft_ready BOTH present in ledger.
        tmp_ledger.append({
            "type": "draft_ready", "person_id": "alex-drift-li",
            "channel": "email", "register": "cold-pitch",
            "draft_hash": "sha256:" + ("0" * 64),
            "hallucination_check": "passed",
            "voice_fidelity_check": "passed",
            "_emitted_by": "draft_quality",
            "ts": _old_ts(59),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        synth = [e for e in result.synthesized if e["type"] == "reconcile_healed"]
        assert len(synth) == 1
        assert synth[0]["from"] == "drafted"
        assert synth[0]["to"] == "ready"
        # Vault written.
        text = note.read_text(encoding="utf-8")
        assert "pipeline_stage: ready" in text

    def test_dry_run_only_reports(self, tmp_ledger, people_dir):
        note = _write_person(
            people_dir, name="Bea Dry", person_id="bea-dry-li",
            email="bea@x.test", pipeline_stage="drafted",
        )
        tmp_ledger.append({
            "type": "review_approved", "person_id": "bea-dry-li",
            "ts": _old_ts(60),
        })
        # Pillar F Week 12 Layer 5 per ADR-0049 D262 — `would_heal`
        # surface requires the `draft_ready` event evidence (same
        # rationale as test_heal_under_apply above).
        tmp_ledger.append({
            "type": "draft_ready", "person_id": "bea-dry-li",
            "channel": "email", "register": "cold-pitch",
            "draft_hash": "sha256:" + ("1" * 64),
            "hallucination_check": "passed",
            "voice_fidelity_check": "passed",
            "_emitted_by": "draft_quality",
            "ts": _old_ts(59),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=False,
        )
        # Reports drift but doesn't heal.
        would = [f for f in result.findings if f["kind"] == "would_heal"]
        assert len(would) == 1
        assert "pipeline_stage: drafted" in note.read_text(encoding="utf-8")
        assert result.synthesized == []

    def test_conflict_vault_ahead_refuses_heal(self, tmp_ledger, people_dir):
        # Vault says "sent" but ledger has nothing supporting that.
        note = _write_person(
            people_dir, name="Conf Ahead", person_id="conf-ahead-li",
            email="conf@x.test", pipeline_stage="sent",
        )
        # Ledger has only an enrolled event → derived_stage = queued
        tmp_ledger.append({
            "type": "enrolled", "person_id": "conf-ahead-li",
            "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        # NOT healed: file still says sent.
        assert "pipeline_stage: sent" in note.read_text(encoding="utf-8")
        conflicts = [f for f in result.findings
                     if f["kind"] == "reconcile_drift" and f.get("conflict")]
        assert len(conflicts) == 1
        assert conflicts[0]["vault_stage"] == "sent"
        assert conflicts[0]["ledger_stage"] == "queued"

    def test_ok_when_aligned(self, tmp_ledger, people_dir):
        note = _write_person(
            people_dir, name="Aligned", person_id="aligned-li",
            email="al@x.test", pipeline_stage="queued",
        )
        tmp_ledger.append({
            "type": "enrolled", "person_id": "aligned-li", "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        assert result.synthesized == []
        assert result.findings == []

    def test_skips_conflict_suffix_files(self, tmp_ledger, people_dir):
        _write_person(
            people_dir, name="Real Person", person_id="real-li",
            email="real@x.test", pipeline_stage="queued",
        )
        # Sync conflict file alongside it
        (people_dir / "Real Person.conflicted.md").write_text(
            "---\ntype: person\nid: bogus-li\n---\n", encoding="utf-8",
        )
        tmp_ledger.append({
            "type": "enrolled", "person_id": "real-li", "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        # examined should be 1, not 2.
        assert result.examined == 1

    def test_conversation_status_heal_under_apply(
        self, tmp_ledger, people_dir,
    ):
        """ADR-0028 D119 — Pass C heals the conversation_status: field.

        Per the per-week reviewer's P2-A finding: the existing TestPassC
        class covers the pipeline_stage: heal path; this test pins the
        Week 4-5 extension's conversation_status: heal path. The heal
        runs alongside the pipeline_stage: heal in the same per-Person
        walk + uses a precomputed thread_states map.
        """
        note = _write_person(
            people_dir, name="Conv Drift", person_id="conv-drift-li",
            email="conv@x.test", pipeline_stage="ready",
        )
        # Seed reply + classification → thread state = active.
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "conv-drift-li", "channel": "email",
            "gmail_message_id": "gid_cd", "gmail_thread_id": "thr_cd",
            "from": "conv@x.test", "subject": "Re: outreach",
            "body": "sounds interesting", "ts": _old_ts(60),
        })
        tmp_ledger.append({
            "type": "reply_classified",
            "person_id": "conv-drift-li", "channel": "email",
            "reply_message_id": "gid_cd",
            "category": "interest",
            "classification_method": "rule", "confidence": 1.0,
            "matched_pattern": r"\binterested\b",
            "gmail_thread_id": "thr_cd",
            "ts": _old_ts(59),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        # Pass C should have written conversation_status: active to the
        # Person note (the field was absent — derived value lands).
        text = note.read_text(encoding="utf-8")
        assert "conversation_status: active" in text, (
            "Pass C heal extension did NOT stamp conversation_status: "
            "active on the Person note. The ledger-derived value should "
            "land per ADR-0028 D119."
        )
        # The reconcile_healed event carries the field discriminator.
        synth = [
            e for e in result.synthesized
            if e.get("type") == "reconcile_healed"
            and e.get("field") == "conversation_status"
        ]
        assert len(synth) == 1
        assert synth[0]["from"] is None  # field was absent
        assert synth[0]["to"] == "active"

    def test_conversation_status_heal_under_drift(
        self, tmp_ledger, people_dir,
    ):
        """Vault drift (operator hand-edit) → ledger overwrites.

        Per ADR-0028 D119 — the conversation state machine is fully
        ledger-derived. Vault drift heals to the ledger-derived
        canonical regardless of direction (no conflict-detection
        surface; the ledger is SoT per I1).
        """
        # Vault stamped to "active" but ledger says "unsubscribed".
        note = people_dir / "Drift.md"
        note.write_text(
            "---\n"
            "type: person\n"
            "id: drift-li\n"
            "identity_keys:\n  emails:\n    - d@x.test\n"
            "name: Drift\n"
            "pipeline_stage: ready\n"
            "conversation_status: active\n"  # stale
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "drift-li", "channel": "email",
            "gmail_message_id": "gid_d", "gmail_thread_id": "thr_d",
            "from": "d@x.test", "body": "please unsubscribe",
            "ts": _old_ts(60),
        })
        tmp_ledger.append({
            "type": "reply_classified",
            "person_id": "drift-li", "channel": "email",
            "reply_message_id": "gid_d",
            "category": "unsubscribe",
            "classification_method": "rule", "confidence": 1.0,
            "matched_pattern": r"\bunsubscribe\b",
            "gmail_thread_id": "thr_d",
            "ts": _old_ts(59),
        })
        tmp_ledger.append({
            "type": "suppression_added",
            "person_id": "drift-li", "channel": "email",
            "suppressed_dimension": "email",
            "suppressed_value": "d@x.test",
            "source_reply_classified_event": {
                "reply_message_id": "gid_d",
                "channel": "email",
                "ts": _old_ts(59),
            },
            "yaml_file": "/tmp/auto-unsubscribe.yml",
            "_emitted_by": "auto_unsubscribe_handler",
            "ts": _old_ts(58),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        # The ledger-derived unsubscribed > vault's stale active.
        text = note.read_text(encoding="utf-8")
        assert "conversation_status: unsubscribed" in text
        assert "conversation_status: active" not in text
        synth = [
            e for e in result.synthesized
            if e.get("type") == "reconcile_healed"
            and e.get("field") == "conversation_status"
        ]
        assert len(synth) == 1
        assert synth[0]["from"] == "active"
        assert synth[0]["to"] == "unsubscribed"

    def test_conversation_status_heal_skips_when_no_conversation(
        self, tmp_ledger, people_dir,
    ):
        """No `*_reply_received` events for the person → no field stamp.

        Per ADR-0028 D119 — absent field is the canonical "no
        conversation yet" state. Pass C does NOT stamp the field on
        Person notes with no derivable status.
        """
        note = _write_person(
            people_dir, name="No Conv", person_id="no-conv-li",
            email="nc@x.test", pipeline_stage="queued",
        )
        tmp_ledger.append({
            "type": "enrolled", "person_id": "no-conv-li",
            "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        text = note.read_text(encoding="utf-8")
        assert "conversation_status:" not in text, (
            "Pass C stamped conversation_status: on a Person with no "
            "conversation events — should leave absent per ADR-0028 D119."
        )
        # No conversation-status reconcile_healed event for this person.
        assert not [
            e for e in result.synthesized
            if e.get("type") == "reconcile_healed"
            and e.get("field") == "conversation_status"
            and e.get("person_id") == "no-conv-li"
        ]


# ---------------------------------------------------------------------------
# Pillar F Week 12 follow-up — Layer 5 reconcile heal-pass refusal
# regression-barrier tests per ADR-0049 D262 + Week 12 follow-up findings
# (P2-1 cell-level matrix coverage gap + P2-2 reason-precedence drift +
# P3-1 module docstring drift + P3-2 _emitted_by-permissive predicate +
# P3-4 closed-set drift-reason enum).
# ---------------------------------------------------------------------------


class TestPassCLayer5:
    """Regression-barrier tests for the Layer 5 backstop per ADR-0049
    D262-D263 (Pillar F Week 12).

    The Pillar F Week 12 follow-up per-week-reviewer surfaced cell-level
    matrix coverage gaps on the Layer 5 binding test at
    ``tests/test_multi_channel_coherence.py::TestHallucinationDetection
    ::test_reconcile_pass_c_refuses_advance_to_ready_on_uncited`` (which
    covered ONLY two cells of the ``ratifies_ready`` predicate at
    ``orchestrator/reconcile.py``). This class extends per-cell coverage
    AND pins the precedence + the closed-enum + the permissive-on-
    ``_emitted_by`` behavior per the follow-up findings.
    """

    def _draft_ready_event(self, person_id: str) -> dict:
        return {
            "type": "draft_ready",
            "person_id": person_id,
            "channel": "email",
            "register": "cold-pitch",
            "draft_hash": "sha256:" + ("0" * 64),
            "hallucination_check": "passed",
            "voice_fidelity_check": "passed",
            "_emitted_by": "draft_quality",
            "ts": _old_ts(60),
        }

    def test_layer_5_fires_on_heal_forward_to_ready_no_draft_ready_event(
        self, tmp_ledger, people_dir,
    ):
        """P2-1 cell — vault=drafted + ledger derives ready (l_rank=3 >=
        v_rank=2) WITHOUT a draft_ready event. The canonical heal-
        forward case. Layer 5 fires + Pass C does NOT heal vault.
        """
        note = _write_person(
            people_dir, name="HealForward", person_id="heal-forward",
            email="hf@x.test", pipeline_stage="drafted",
        )
        tmp_ledger.append({
            "type": "review_approved", "person_id": "heal-forward",
            "ts": _old_ts(60),
        })
        # NO draft_ready event — Layer 4 bypass.
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        layer5 = [
            f for f in result.findings
            if f.get("reason") == "ready_without_draft_ready_event"
        ]
        assert len(layer5) == 1, (
            f"Layer 5 MUST fire on heal-forward-to-ready without "
            f"draft_ready event; got findings={result.findings!r}."
        )
        # Pass C does NOT advance vault — operator-readable signal.
        assert "pipeline_stage: drafted" in note.read_text(encoding="utf-8")
        # NO reconcile_healed event (heal refused).
        healed = [e for e in result.synthesized if e["type"] == "reconcile_healed"]
        assert healed == []

    def test_layer_5_fires_on_vault_ready_ledger_none_no_draft_ready_event(
        self, tmp_ledger, people_dir,
    ):
        """P2-1 cell — vault=ready + ledger=None (no ledger evidence).
        The ``ratifies_ready`` predicate fires (vault claims ready);
        absence of draft_ready surfaces the Layer 5 drift.
        """
        _write_person(
            people_dir, name="VaultReady", person_id="vault-ready-no-led",
            email="vr@x.test", pipeline_stage="ready",
        )
        # Empty ledger — no events for this Person.
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        layer5 = [
            f for f in result.findings
            if f.get("reason") == "ready_without_draft_ready_event"
        ]
        assert len(layer5) == 1
        assert layer5[0]["vault_stage"] == "ready"
        assert layer5[0]["ledger_stage"] is None

    def test_layer_5_dry_run_surfaces_finding_no_ledger_emit(
        self, tmp_ledger, people_dir,
    ):
        """P2-1 cell — apply=False (dry-run) surfaces the drift finding
        but does NOT emit the drift event to the ledger. The surface
        vs emit decomposition is the per-Pass-C convention (mirrors
        ``test_dry_run_only_reports``).
        """
        _write_person(
            people_dir, name="DryRun", person_id="dry-run-li",
            email="dr@x.test", pipeline_stage="ready",
        )
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=False,
        )
        layer5 = [
            f for f in result.findings
            if f.get("reason") == "ready_without_draft_ready_event"
        ]
        assert len(layer5) == 1, "Dry-run MUST surface the drift finding."
        # apply=False — no drift event in ledger.
        drift_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "reconcile_drift"
        ]
        assert drift_events == [], (
            "Dry-run MUST NOT emit reconcile_drift to the ledger; the "
            "surface (findings) vs emit (ledger event) decomposition is "
            "the per-Pass-C convention."
        )

    def test_layer_5_reason_preempts_vault_ahead_of_ledger(
        self, tmp_ledger, people_dir,
    ):
        """P2-2 — when vault=ready + ledger=drafted + NO draft_ready
        event, Layer 5's reason value PRE-EMPTS the existing
        ``vault_ahead_of_ledger`` reason (because Layer 5's
        ``ratifies_ready`` predicate fires on ``vault_stage == "ready"``
        unconditionally, ahead of the ``v_rank > l_rank`` branch).

        This pins the operator-visible reason transition: Pillar I
        per-tenant audit-tooling filtering on
        ``vault_ahead_of_ledger`` MUST also subscribe to
        ``ready_without_draft_ready_event`` to preserve prior
        operational visibility. The behavior change is documented in
        the audit at ``.planning/REVIEW-pillar-f-surface-audit.md``
        §65 + the ``_LAYER_5_DRIFT_REASON`` module docstring.
        """
        _write_person(
            people_dir, name="Preempt", person_id="preempt-li",
            email="pe@x.test", pipeline_stage="ready",
        )
        # Ledger only has draft_complete → derived_stage = "drafted".
        # v_rank=3 > l_rank=2 — the legacy vault_ahead_of_ledger branch.
        tmp_ledger.append({
            "type": "draft_complete", "person_id": "preempt-li",
            "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        reasons = [f.get("reason") for f in result.findings]
        assert "ready_without_draft_ready_event" in reasons, (
            "Layer 5 MUST fire when vault=ready + ledger=drafted + no "
            "draft_ready event."
        )
        assert "vault_ahead_of_ledger" not in reasons, (
            "Layer 5 PRE-EMPTS the vault_ahead_of_ledger reason; the "
            "drift surface is the Layer 5 reason (post-Week-12 "
            "behavior). Operators filtering vault_ahead_of_ledger MUST "
            "extend their filter per ADR-0049 D263 + the audit's §65 "
            "consumer-filter migration note."
        )

    def test_person_has_draft_ready_event_permissive_on_emitted_by(
        self, tmp_ledger, people_dir,
    ):
        """P3-2 — the ``_person_has_draft_ready_event`` predicate
        accepts ANY draft_ready event regardless of ``_emitted_by``.

        The Layer 5 false-negative bound (per ADR-0049 §Risks) is
        REACTIVE not structural — Pillar I per-tenant audit-tooling
        greps ``_emitted_by != "draft_quality"`` for non-factory
        emissions; the predicate itself is permissive. This test
        pins the current behavior so any future tightening (e.g.,
        requiring ``_emitted_by == "draft_quality"``) lands at the
        Pillar I commit that adds the structural enforcement.
        """
        _write_person(
            people_dir, name="EmitBy", person_id="emit-by-test",
            email="eb@x.test", pipeline_stage="ready",
        )
        # Append a draft_ready event with a different _emitted_by.
        tmp_ledger.append({
            "type": "draft_ready",
            "person_id": "emit-by-test",
            "channel": "email", "register": "cold-pitch",
            "draft_hash": "sha256:" + ("a" * 64),
            "hallucination_check": "passed",
            "voice_fidelity_check": "passed",
            "_emitted_by": "some_other_module",  # NOT "draft_quality"
            "ts": _old_ts(60),
        })
        # Currently — Layer 5 passes (predicate is permissive).
        assert _reconcile._person_has_draft_ready_event(
            tmp_ledger, "emit-by-test",
        ) is True, (
            "Per ADR-0049 §Risks the Layer 5 predicate is permissive on "
            "_emitted_by; future Pillar I MAY tighten to require "
            "_emitted_by == \"draft_quality\"."
        )
        # And Pass C does not surface a Layer 5 drift.
        result = _reconcile.run_pass_c(
            led=tmp_ledger, people_dir=people_dir, apply=True,
        )
        layer5 = [
            f for f in result.findings
            if f.get("reason") == "ready_without_draft_ready_event"
        ]
        assert layer5 == [], (
            "Permissive predicate accepts non-draft_quality emissions; "
            "test documents this behavior for the Pillar I structural "
            "tightening decision."
        )

    def test_drift_reasons_closed_set_pinned(self):
        """P3-4 — the ``reconcile_drift.reason`` values form a closed
        set at ``_DRIFT_REASONS``. Any future addition MUST update this
        frozenset + the consumer-surface migration note.
        """
        assert _reconcile._DRIFT_REASONS == frozenset({
            "vault_has_stage_but_ledger_empty",
            "vault_ahead_of_ledger",
            "ready_without_draft_ready_event",
        }), (
            "_DRIFT_REASONS frozenset is the closed-set pin for Pillar G "
            "observability + Pillar I per-tenant audit-tooling "
            "consumers; any future addition MUST update this pin + "
            "document the consumer-surface migration in an ADR."
        )
        # Layer 5 reason MUST be in the set.
        assert _reconcile._LAYER_5_DRIFT_REASON in _reconcile._DRIFT_REASONS

    def test_reconcile_module_docstring_mentions_week_12_layer_5(self):
        """P3-1 — the module-level docstring at ``orchestrator/reconcile.
        py`` MUST name the Pillar F Week 12 Layer 5 extension. The
        pre-follow-up docstring was frozen at Pillar D Week 4-5 (Pass
        N/M extension); future operators reading the module header MUST
        see the Layer 5 backstop pinned (same doc-drift class as W8
        P3-3 + W9 P3-1 + W10 P3-1 + W11 P3-1 module-docstring-frozen-
        at-prior-week pattern — FIFTH consecutive week of this finding).
        """
        doc = _reconcile.__doc__ or ""
        assert "Layer 5" in doc, (
            "Module docstring MUST name Layer 5 (the Pillar F Week 12 "
            "hallucination-detection backstop extension)."
        )
        assert "ADR-0049" in doc, (
            "Module docstring MUST cite ADR-0049 (Pillar F Week 12)."
        )
        assert "ready_without_draft_ready_event" in doc, (
            "Module docstring MUST name the NEW reason value for "
            "operator-readable per-week-reviewer audit trail."
        )


# ---------------------------------------------------------------------------
# Orchestration / status persistence / freshness gate
# ---------------------------------------------------------------------------


class TestOrchestration:

    def test_unknown_pass_raises(self, tmp_ledger):
        with pytest.raises(ValueError):
            _reconcile.reconcile(
                passes="Z", since=datetime.now(timezone.utc),
                led=tmp_ledger, persist_status=False,
            )

    def test_missing_gmail_for_pass_a_recorded_as_error(self, tmp_ledger):
        result = _reconcile.reconcile(
            passes="A", since=datetime.now(timezone.utc),
            led=tmp_ledger, gmail=None, persist_status=False,
        )
        assert result.passes[0].errors

    def test_missing_people_dir_for_pass_c_recorded(self, tmp_ledger):
        result = _reconcile.reconcile(
            passes="C", since=datetime.now(timezone.utc),
            led=tmp_ledger, people_dir=None, persist_status=False,
        )
        assert result.passes[0].errors

    def test_status_persistence_round_trip(
        self, tmp_ledger, tmp_status_dir,
    ):
        gmail = FakeGmail()
        # No intents — pass should run cleanly with no work.
        result = _reconcile.reconcile(
            passes="A",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            gmail=gmail, led=tmp_ledger, apply=True,
            status_dir=tmp_status_dir,
        )
        assert result.passes[0].errors == []
        status_file = tmp_status_dir / "status.yml"
        assert status_file.exists()
        # And we can read it back via the public helper.
        ts = _reconcile.last_quick_run(tmp_status_dir)
        assert ts is not None
        assert (datetime.now(timezone.utc) - ts) < timedelta(minutes=1)

    def test_pass_with_errors_does_not_update_status(
        self, tmp_ledger, tmp_status_dir,
    ):
        # Pass A with no Gmail → records error, must NOT update status.
        _reconcile.reconcile(
            passes="A", since=datetime.now(timezone.utc),
            led=tmp_ledger, gmail=None, status_dir=tmp_status_dir,
        )
        assert _reconcile.last_quick_run(tmp_status_dir) is None

    def test_needs_quick_reconcile_no_open_intents(
        self, tmp_ledger, tmp_status_dir,
    ):
        assert _reconcile.needs_quick_reconcile(
            led=tmp_ledger, status_dir=tmp_status_dir,
        ) is False

    def test_needs_quick_reconcile_with_open_old_intent(
        self, tmp_ledger, tmp_status_dir,
    ):
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_NEEDSNEEDSNEEDSNEEDSNEEDSN1",
            "person_id": "needs-li", "channel": "email", "ts": _old_ts(60),
        })
        # No prior quick-run → needs reconcile.
        assert _reconcile.needs_quick_reconcile(
            led=tmp_ledger, status_dir=tmp_status_dir,
        ) is True
        # After a clean run, ledger.open_intents reflects the synthesized
        # send_aborted; needs_quick_reconcile returns False.
        gmail = FakeGmail()
        _reconcile.reconcile(
            passes="A",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            gmail=gmail, led=tmp_ledger, apply=True,
            status_dir=tmp_status_dir,
        )
        assert _reconcile.needs_quick_reconcile(
            led=tmp_ledger, status_dir=tmp_status_dir,
        ) is False

    def test_abc_passes_invoked_in_order(
        self, tmp_ledger, tmp_status_dir, people_dir,
    ):
        """The email-only run (Pass A,B,C) invokes the three email/vault
        passes in the requested order. Pillar C Week 4 added LinkedIn
        Passes D + E; this test is the pre-Week-4 baseline scope."""
        gmail = FakeGmail()
        result = _reconcile.reconcile(
            passes="A,B,C",
            since=datetime.now(timezone.utc) - timedelta(days=30),
            gmail=gmail, led=tmp_ledger, people_dir=people_dir,
            apply=False, status_dir=tmp_status_dir,
        )
        assert [p.pass_name for p in result.passes] == ["A", "B", "C"]

    def test_full_run_invokes_all_five_passes(
        self, tmp_ledger, tmp_status_dir, people_dir,
    ):
        """Per Pillar C Week 4: the full 5-pass run (A,B,C,D,E) invokes
        every pass in the requested order. A regression that dropped D
        or E from the default ``--full`` set would be caught here.

        Coverage-gap fix per the Week 4 per-week review C-3 finding —
        before this test, the suite had no assertion that ``--full``
        actually executes Pass D + Pass E. Without injected clients,
        each LinkedIn pass records the "requires a LinkedIn client"
        error per the documented degradation path — but the per-pass
        invocation order is still observable."""
        gmail = FakeGmail()
        result = _reconcile.reconcile(
            passes="A,B,C,D,E",
            since=datetime.now(timezone.utc) - timedelta(days=30),
            gmail=gmail, led=tmp_ledger, people_dir=people_dir,
            linkedin=None, apply=False, status_dir=tmp_status_dir,
        )
        assert [p.pass_name for p in result.passes] == \
            ["A", "B", "C", "D", "E"]
        # Pass D / E record the missing-LinkedIn-client error explicitly
        # (the degradation path per ADR-0017 §Migration/rollout item 5).
        d_pass = next(p for p in result.passes if p.pass_name == "D")
        e_pass = next(p for p in result.passes if p.pass_name == "E")
        assert any("LinkedIn" in err for err in d_pass.errors)
        assert any("LinkedIn" in err for err in e_pass.errors)


class TestCLI:

    def test_status_subcommand_outputs_json(
        self, tmp_status_dir, capsys, monkeypatch,
    ):
        monkeypatch.setattr(
            "sys.argv",
            ["reconcile.py", "--status", "--json",
             "--reconcile-dir", str(tmp_status_dir)],
        )
        rc = _reconcile.main()
        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert "last_run" in data
