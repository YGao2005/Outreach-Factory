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
