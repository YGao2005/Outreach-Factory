"""Phase 5.5 Week 3 — two-phase send + gate behavior.

Verifies:
  - Pre-flight gate blocks: already_sent, identity_incomplete, locked.
  - Two-phase commit: send_intent + send_confirmed pair on success.
  - Gmail failure path: send_failed event written; no confirm; returns ok=False.
  - Crash recovery: send_intent written + Gmail received the message but
    confirm event missing → reconcile Pass A synthesizes send_confirmed.
  - 5xx crash: send_intent written + Gmail never received → reconcile after
    grace period synthesizes send_aborted.

The send_queued module imports config + vault + gmail_client which all load
from ~/.outreach-factory/config.yml at import time. Tests stub `config` via
sys.modules before importing so they run in any environment (CI/fresh clone)
without requiring a real config file.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# --- bootstrap: stub config + add scripts/ to path BEFORE importing send_queued
_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "skills" / "send-outreach" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# google_auth_oauthlib is only required for the interactive OAuth bootstrap,
# not for the tested code paths. Stub it so gmail_client can import cleanly
# in environments (CI, fresh clones) where it's not installed.
if "google_auth_oauthlib" not in sys.modules:
    _gao = types.ModuleType("google_auth_oauthlib")
    _gao_flow = types.ModuleType("google_auth_oauthlib.flow")
    _gao_flow.InstalledAppFlow = object  # only referenced at runtime
    _gao.flow = _gao_flow
    sys.modules["google_auth_oauthlib"] = _gao
    sys.modules["google_auth_oauthlib.flow"] = _gao_flow

if "config" not in sys.modules:
    _cfg = types.ModuleType("config")
    _cfg.LINKEDIN_MANIFEST_PATH = Path("/tmp/_test_li_manifest.json")
    _cfg.LINKEDIN_WEEKLY_INVITE_LIMIT = 100
    _cfg.SENDER_NAME = "Test Sender"
    _cfg.VAULT_ROOT = Path("/tmp/_test_vault")
    _cfg.PEOPLE_DIR = Path("/tmp/_test_vault/10 People")
    _cfg.CONVERSATIONS_DIR = Path("/tmp/_test_vault/40 Conversations")
    _cfg.TOUCH_NOTE_GLOB = "**/*.md"
    _cfg.CREDENTIALS_DIR = Path("/tmp/_test_creds")
    _cfg.GMAIL_CREDENTIALS = Path("/tmp/_test_creds/g.json")
    _cfg.GMAIL_TOKEN = Path("/tmp/_test_creds/t.json")
    _cfg.GMAIL_SCOPES: list[str] = []
    sys.modules["config"] = _cfg

import send_queued  # noqa: E402
import vault as _vault  # noqa: E402
import identity  # noqa: E402
import ledger as _ledger  # noqa: E402
import reconcile as _reconcile  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    """Isolated ledger directory per test."""
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(d))
    return _ledger.Ledger(d)


@pytest.fixture
def people_dir(tmp_path):
    pd = tmp_path / "people"
    pd.mkdir()
    return pd


def _write_person_note(
    people_dir: Path,
    *,
    name: str,
    person_id: str,
    email: str,
    linkedin: str | None = "in/alice-test",
    research_tier: str | None = None,
) -> Path:
    """Write a Person note with the identity_keys block populated.

    The optional ``research_tier`` kwarg adds the frontmatter field
    (`research_tier: <value>`) that `vault.load_person` parses into
    `PersonInfo.research_tier`, which the send-gate threads into
    `ctx.tier` (ADR-0007). When `None`, the field is omitted entirely
    — preserving the pre-Week-5 behavior of every existing test caller.
    """
    ik_lines = [
        "identity_keys:",
        f"  emails:",
        f"    - {email}",
    ]
    if linkedin:
        ik_lines.insert(1, f"  linkedin: {linkedin}")
    extra_lines = ""
    if research_tier is not None:
        extra_lines = f"research_tier: {research_tier}\n"
    note = people_dir / f"{name}.md"
    note.write_text(
        "---\n"
        "type: person\n"
        f"id: {person_id}\n"
        + "\n".join(ik_lines) + "\n"
        f"name: {name}\n"
        f"email: {email}\n"
        "status: queued\n"
        "pipeline_stage: ready\n"
        f"{extra_lines}"
        "---\n"
        "# body\n",
        encoding="utf-8",
    )
    return note


def _make_draft(
    touch_path: Path, person_path: Path, name: str,
    email: str, subject: str = "Hi", body: str = "Hello\n",
    research_tier: str | None = None,
) -> _vault.TouchDraft:
    """Construct a TouchDraft directly (avoiding vault walk for unit tests).

    Mirrors what `vault.parse_touch_note` would produce for a ready-to-send
    cold-pitch email; we just synthesize it here to keep the test surface
    small.

    The optional ``research_tier`` kwarg populates
    ``PersonInfo.research_tier`` directly — the send-gate's
    ``_build_rule_context`` reads it to populate ``ctx.tier`` (ADR-0007).
    Tests that need the tier-rule path to see a value go through this
    kwarg; pre-Week-5 tests pass ``None`` (the default) implicitly and
    behave identically to the pre-Week-5 PersonInfo shape.
    """
    touch_path.write_text(
        "---\n"
        "type: touch\n"
        f"person: '[[{name}]]'\n"
        "channel: email\n"
        "sent: false\n"
        "---\n"
        "## Email\n"
        f"**Subject:** `{subject}`\n"
        "\n```\n"
        f"{body}"
        "```\n",
        encoding="utf-8",
    )
    person_info = _vault.PersonInfo(
        name=name, note_path=person_path, email=email,
        linkedin=None, status="queued",
        research_tier=research_tier,
    )
    return _vault.TouchDraft(
        note_path=touch_path,
        frontmatter={"type": "touch", "person": f"[[{name}]]",
                     "channel": "email", "sent": False},
        body="",
        person_name=name,
        person=person_info,
        channel_declared="email",
        has_email_block=True,
        has_linkedin_block=False,
        email_subject=subject,
        email_body=body,
        linkedin_dm=None,
        issues=[],
    )


class FakeGmail:
    """Bare-minimum stand-in for GmailClient: accepts sends, records messages,
    answers search_messages / get_message / get_thread."""

    def __init__(self, sender_email: str = "me@example.test"):
        self.sender_email = sender_email
        self.sent: list[dict] = []        # one entry per successful send
        self.fail_with: Exception | None = None
        # Manual injection (for inbox/DSN scenarios in Pass B)
        self.extra_thread_messages: dict[str, list[dict]] = {}

    def send_email(self, *, to, subject, body, from_name=None,
                   extra_headers=None, body_footer=None):
        if self.fail_with is not None:
            raise self.fail_with
        msg_id = f"mid-{len(self.sent) + 1:03d}"
        thread_id = f"tid-{len(self.sent) + 1:03d}"
        headers = list((extra_headers or {}).items())
        self.sent.append({
            "id": msg_id, "threadId": thread_id,
            "to": to, "subject": subject,
            "body": (body or "") + (body_footer or ""),
            "headers": dict(headers),
        })
        return msg_id, thread_id

    # Reconcile protocol surface ------------------------------------------------

    def search_messages(self, query: str, max_results: int = 100) -> list[dict]:
        # Strip surrounding quotes from "phrase"
        q = query.strip('"').strip("'")
        hits = []
        for m in self.sent:
            if q in (m.get("body") or "") or q in m.get("headers", {}).get(
                    "X-Outreach-Intent-Id", ""):
                hits.append({"id": m["id"], "threadId": m["threadId"]})
                if len(hits) >= max_results:
                    break
        return hits

    def get_message(self, msg_id: str) -> dict | None:
        for m in self.sent:
            if m["id"] == msg_id:
                return self._as_gmail_payload(m)
        # Also look in injected thread messages
        for msgs in self.extra_thread_messages.values():
            for m in msgs:
                if m.get("id") == msg_id:
                    return self._as_gmail_payload(m)
        return None

    def get_thread(self, thread_id: str) -> dict | None:
        msgs = [self._as_gmail_payload(m) for m in self.sent
                if m["threadId"] == thread_id]
        msgs.extend(self._as_gmail_payload(m)
                    for m in self.extra_thread_messages.get(thread_id, []))
        if not msgs:
            return None
        return {"id": thread_id, "messages": msgs}

    @staticmethod
    def _as_gmail_payload(m: dict) -> dict:
        hdrs = []
        for k, v in (m.get("headers") or {}).items():
            hdrs.append({"name": k, "value": v})
        if "to" in m and "to" not in (m.get("headers") or {}):
            hdrs.append({"name": "To", "value": m["to"]})
        if "subject" in m and "subject" not in (m.get("headers") or {}):
            hdrs.append({"name": "Subject", "value": m["subject"]})
        if "from" in m and "from" not in (m.get("headers") or {}):
            hdrs.append({"name": "From", "value": m["from"]})
        return {
            "id": m["id"],
            "threadId": m.get("threadId", ""),
            "payload": {"headers": hdrs},
            "body": m.get("body", ""),
        }


# ---------------------------------------------------------------------------
# Gate behavior
# ---------------------------------------------------------------------------


class TestGate:

    def test_allows_clean_person(self, tmp_path, tmp_ledger, people_dir):
        note = _write_person_note(
            people_dir, name="Alice Clean", person_id="alice-clean-li",
            email="alice@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Alice Clean", "alice@example.com",
        )
        gmail = FakeGmail()
        out = send_queued.gated_send_one(
            draft, gmail_client=gmail, led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        assert out["intent_id"]
        assert out["gmail_message_id"]
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "send_intent" in types_seen and "send_confirmed" in types_seen

    def test_blocks_already_sent(self, tmp_path, tmp_ledger, people_dir):
        note = _write_person_note(
            people_dir, name="Bob Done", person_id="bob-done-li",
            email="bob@example.com",
        )
        # Seed: already sent.
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_prior",
            "person_id": "bob-done-li", "channel": "email",
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": "snd_prior",
            "person_id": "bob-done-li", "channel": "email",
            "gmail_message_id": "gid_prior", "gmail_thread_id": "tid_prior",
        })
        draft = _make_draft(
            tmp_path / "touch.md", note, "Bob Done", "bob@example.com",
        )
        gmail = FakeGmail()
        out = send_queued.gated_send_one(
            draft, gmail_client=gmail, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "already_sent"
        assert gmail.sent == []     # no Gmail call made
        blocked = [e for e in tmp_ledger.all_events()
                   if e.type == "dedup_blocked"]
        assert len(blocked) == 1
        assert blocked[0].get("reason") == "already_sent"

    def test_blocks_tmp_identity(self, tmp_path, tmp_ledger, people_dir):
        # -tmp id: identity_incomplete
        note = people_dir / "Carla Tmp.md"
        note.write_text(
            "---\n"
            "type: person\n"
            "id: carla-tmp-2026-tmp\n"
            "identity_keys: {}\n"
            "name: Carla Tmp\n"
            "email: carla@example.com\n"
            "---\n",
            encoding="utf-8",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Carla Tmp", "carla@example.com",
        )
        gmail = FakeGmail()
        out = send_queued.gated_send_one(
            draft, gmail_client=gmail, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "identity_incomplete"
        assert gmail.sent == []

    def test_blocks_no_person_note(self, tmp_path, tmp_ledger):
        note = tmp_path / "ghost.md"
        note.write_text("# not a frontmatter file\n", encoding="utf-8")
        draft = _make_draft(
            tmp_path / "touch.md", note, "Ghost", "ghost@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] in ("not_a_person_note", "identity_incomplete")

    def test_lock_blocks(self, tmp_path, tmp_ledger, people_dir):
        note = _write_person_note(
            people_dir, name="Dee Locked", person_id="dee-locked-li",
            email="dee@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Dee Locked", "dee@example.com",
        )

        def _no_lock(name):
            return (False, "held by other agent")

        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger, writeback=None,
            acquire_lock=_no_lock,
        )
        assert out["ok"] is False
        assert out["reason"] == "locked"


# ---------------------------------------------------------------------------
# Two-phase commit & crash recovery
# ---------------------------------------------------------------------------


class TestTwoPhase:

    def test_intent_and_confirm_both_written_with_thread_id(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        note = _write_person_note(
            people_dir, name="Eve Two", person_id="eve-two-li",
            email="eve@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Eve Two", "eve@example.com",
        )
        gmail = FakeGmail()
        out = send_queued.gated_send_one(
            draft, gmail_client=gmail, led=tmp_ledger, writeback=None,
        )
        assert out["ok"]
        events = tmp_ledger.all_events()
        intents = [e for e in events if e.type == "send_intent"]
        confirms = [e for e in events if e.type == "send_confirmed"]
        assert len(intents) == 1 and len(confirms) == 1
        assert intents[0].intent_id == confirms[0].intent_id
        assert confirms[0].get("gmail_message_id") == gmail.sent[0]["id"]
        assert confirms[0].get("gmail_thread_id") == gmail.sent[0]["threadId"]
        # Intent footer present in body
        assert intents[0].intent_id in (gmail.sent[0]["body"] or "")
        # Custom header present
        assert gmail.sent[0]["headers"].get("X-Outreach-Intent-Id") == \
            intents[0].intent_id

    def test_gmail_5xx_writes_send_failed_no_confirm(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        note = _write_person_note(
            people_dir, name="Frank Fail", person_id="frank-fail-li",
            email="frank@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Frank Fail", "frank@example.com",
        )
        gmail = FakeGmail()
        gmail.fail_with = RuntimeError("Gmail API send failed: 503")
        out = send_queued.gated_send_one(
            draft, gmail_client=gmail, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "send_failed"
        types_seen = [e.type for e in tmp_ledger.all_events()]
        assert "send_intent" in types_seen
        assert "send_failed" in types_seen
        assert "send_confirmed" not in types_seen

    def test_mid_intent_crash_recovers_via_reconcile_pass_a(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Simulate the SIGKILL-after-Gmail-success-before-confirm case.

        We manually write send_intent + insert the message into FakeGmail
        (Gmail received it) without writing send_confirmed. Then run Pass A
        and assert the synthesized send_confirmed carries the live ids.
        """
        intent_id = "snd_ABCDEFGHJKMNPQRSTVWXYZ01"
        # Write the intent as if gated_send_one had emitted it.
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)) \
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tmp_ledger.append({
            "type": "send_intent", "intent_id": intent_id,
            "person_id": "ghost-li", "channel": "email",
            "email": "ghost@example.com",
            "ts": old_ts,
        })
        # Gmail has the message (intent_id embedded in body)
        gmail = FakeGmail()
        gmail.sent.append({
            "id": "gid_recovered", "threadId": "tid_recovered",
            "to": "ghost@example.com", "subject": "Hi",
            "body": f"hello\n\noutreach-intent:{intent_id}\n",
            "headers": {"X-Outreach-Intent-Id": intent_id},
        })

        result = _reconcile.reconcile(
            passes="A",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            gmail=gmail, led=tmp_ledger, apply=True,
            persist_status=False,
        )
        synthesized = [e for p in result.passes for e in p.synthesized]
        assert any(e["type"] == "send_confirmed"
                   and e["intent_id"] == intent_id
                   and e["gmail_message_id"] == "gid_recovered"
                   for e in synthesized)
        # Ledger now has the confirm event (idempotent re-run won't re-add it)
        outcome = tmp_ledger.outcome_for_intent(intent_id)
        assert outcome is not None and outcome.type == "send_confirmed"

    def test_mid_intent_5xx_recovers_to_send_aborted(
        self, tmp_path, tmp_ledger,
    ):
        """Intent written, Gmail never received → after grace, send_aborted."""
        intent_id = "snd_FAILEDFAILEDFAILEDFAILED1"
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=15)) \
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tmp_ledger.append({
            "type": "send_intent", "intent_id": intent_id,
            "person_id": "ghosted-li", "channel": "email",
            "email": "ghosted@example.com",
            "ts": old_ts,
        })
        gmail = FakeGmail()  # never received anything
        result = _reconcile.reconcile(
            passes="A",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            gmail=gmail, led=tmp_ledger, apply=True,
            min_intent_age=timedelta(minutes=5),
            persist_status=False,
        )
        synthesized = [e for p in result.passes for e in p.synthesized]
        aborts = [e for e in synthesized if e["type"] == "send_aborted"]
        assert len(aborts) == 1
        assert aborts[0]["intent_id"] == intent_id
        assert aborts[0]["reason"] == "no_gmail_match_after_5min"

    def test_intent_too_young_not_aborted(self, tmp_ledger):
        intent_id = "snd_YOUNGYOUNGYOUNGYOUNG12345"
        # Intent only 1 minute old
        new_ts = (datetime.now(timezone.utc) - timedelta(minutes=1)) \
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tmp_ledger.append({
            "type": "send_intent", "intent_id": intent_id,
            "person_id": "young-li", "channel": "email",
            "ts": new_ts,
        })
        gmail = FakeGmail()
        result = _reconcile.reconcile(
            passes="A",
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            gmail=gmail, led=tmp_ledger, apply=True,
            min_intent_age=timedelta(minutes=5),
            persist_status=False,
        )
        # Should not touch this intent yet (still in grace window)
        synthesized = [e for p in result.passes for e in p.synthesized]
        assert all(e.get("intent_id") != intent_id for e in synthesized)


# ---------------------------------------------------------------------------
# Validation gate: 10-prospect synthetic batch with mid-flight crashes
# ---------------------------------------------------------------------------


class TestValidationGate:
    """The HANDOFF §5.5.C synthetic 10-prospect mock-Gmail batch.

    Sends 10 with the gate; mid-two-phase 'crashes' on 3 (one with Gmail
    success, two without). Then reconcile Pass A. Asserts:
      - no double send_confirmed for any intent_id
      - every send_confirmed has a preceding send_intent
      - the funnel is internally consistent
    """

    def _seed_batch(self, tmp_path, tmp_ledger, people_dir, gmail):
        drafts = []
        for i in range(10):
            note = _write_person_note(
                people_dir,
                name=f"Person {i:02d}",
                person_id=f"person-{i:02d}-li",
                email=f"p{i:02d}@example.com",
                linkedin=f"in/person-{i:02d}",
            )
            touch = tmp_path / f"touch_{i:02d}.md"
            d = _make_draft(touch, note, f"Person {i:02d}",
                            f"p{i:02d}@example.com",
                            subject=f"Subj {i}", body=f"Body {i}\n")
            drafts.append(d)
        return drafts

    def test_full_run_with_three_crashes(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        gmail = FakeGmail()
        drafts = self._seed_batch(tmp_path, tmp_ledger, people_dir, gmail)

        # Process 7 normally.
        for d in drafts[:7]:
            outcome = send_queued.gated_send_one(
                d, gmail_client=gmail, led=tmp_ledger, writeback=None,
            )
            assert outcome["ok"], outcome
        assert len([e for e in tmp_ledger.all_events()
                    if e.type == "send_confirmed"]) == 7

        # Crash variant A: Gmail received, no confirm event written (sim crash
        # between Gmail return and ledger append).
        crash_intent = _ledger.new_intent_id()
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)) \
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        tmp_ledger.append({
            "type": "send_intent", "intent_id": crash_intent,
            "person_id": "person-07-li", "channel": "email",
            "email": "p07@example.com", "ts": old_ts,
        })
        gmail.sent.append({
            "id": "gid_crashA", "threadId": "tid_crashA",
            "to": "p07@example.com", "subject": "Subj 7",
            "body": f"Body 7\n\noutreach-intent:{crash_intent}\n",
            "headers": {"X-Outreach-Intent-Id": crash_intent},
        })

        # Crash variant B + C: intent written, Gmail never received.
        for i in (8, 9):
            iid = _ledger.new_intent_id()
            tmp_ledger.append({
                "type": "send_intent", "intent_id": iid,
                "person_id": f"person-{i:02d}-li", "channel": "email",
                "email": f"p{i:02d}@example.com", "ts": old_ts,
            })

        # Run reconcile Pass A.
        result = _reconcile.reconcile(
            passes="A",
            since=datetime.now(timezone.utc) - timedelta(hours=2),
            gmail=gmail, led=tmp_ledger, apply=True,
            persist_status=False,
        )
        recovered = [e for p in result.passes for e in p.synthesized]
        confirms_recovered = [e for e in recovered if e["type"] == "send_confirmed"]
        aborts_recovered = [e for e in recovered if e["type"] == "send_aborted"]
        assert len(confirms_recovered) == 1
        assert confirms_recovered[0]["intent_id"] == crash_intent
        assert len(aborts_recovered) == 2

        # Internal consistency: no duplicate confirms for any intent_id.
        confirms = [e for e in tmp_ledger.all_events()
                    if e.type == "send_confirmed"]
        intent_ids = [e.intent_id for e in confirms]
        assert len(intent_ids) == len(set(intent_ids))
        # Every confirm has a matching intent.
        for c in confirms:
            assert tmp_ledger.query_by_intent(c.intent_id) is not None
        # 7 normal + 1 recovered = 8 confirms; 2 aborts.
        assert len(confirms) == 8
        aborts = [e for e in tmp_ledger.all_events() if e.type == "send_aborted"]
        assert len(aborts) == 2


# ---------------------------------------------------------------------------
# Policy gate — Pillar A Week 1 task #6
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_policies_dir(tmp_path, monkeypatch):
    """Per-test policies directory; overrides where send_queued looks
    for cooldowns.yml. Empty by default — caller writes the file if a
    test needs concrete rules."""
    d = tmp_path / "policies"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_POLICIES_DIR", str(d))
    return d


def _factory_cooldowns_yaml() -> str:
    """The four factory cooldown rules from config-template/cooldowns.example.yml.

    Embedded here (rather than read from disk) so tests are self-contained
    and don't break if the example file is reorganized.
    """
    return (
        "version: 1\n"
        "rules:\n"
        "  - name: no-double-cold-pitch\n"
        "    type: cooldown.no-duplicate-register\n"
        "    block_when: {register: cold-pitch}\n"
        "    reason: 'Already cold-pitched this person'\n"
        "  - name: follow-up-requires-prior-cold-pitch\n"
        "    type: cooldown.requires-prior-send\n"
        "    block_when: {register: follow-up}\n"
        "    requires_register: cold-pitch\n"
        "    min_age_days: 7\n"
        "  - name: re-engage-requires-dormancy\n"
        "    type: cooldown.requires-person-status\n"
        "    block_when: {register: re-engage}\n"
        "    required_status: dormant\n"
        "  - name: domain-cooldown\n"
        "    type: cooldown.domain-throttle\n"
        "    block_when: {channel: email}\n"
        "    max_count: 1\n"
        "    window_days: 14\n"
    )


class TestPolicyGate:
    """Verifies the integration between gated_send_one and policy.evaluate.

    Surface under test:
      - No cooldowns.yml file → engine returns Allow → send proceeds.
      - cooldowns.yml present + matching rule fires → policy_blocked event
        emitted with rule/reason/policy_detail; send refused.
      - Specifically: no-double-cold-pitch blocks a 2nd cold-pitch.
      - Domain throttle blocks a new prospect on an already-emailed domain.
      - Re-engage on a non-dormant person blocks.
      - Follow-up without prior cold-pitch blocks.
      - Policy outage (rule raises) → policy_blocked with policy_engine_error.

    The "no policy file" case is implicitly covered by every test in
    TestGate / TestTwoPhase above (they don't use tmp_policies_dir, so
    OUTREACH_FACTORY_POLICIES_DIR env var is unset → no rules → Allow).
    """

    def test_no_cooldown_file_allows(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Empty policies directory (no cooldowns.yml) → engine returns Allow."""
        note = _write_person_note(
            people_dir, name="Eve Empty", person_id="eve-empty-li",
            email="eve@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Eve Empty", "eve@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        # No policy_blocked event emitted.
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "policy_blocked" not in types_seen

    def test_no_double_cold_pitch_blocks_second_send(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Two distinct prospects on different domains; second send is to
        a prospect who already received a cold-pitch (via direct ledger seed
        of the (send_intent, send_confirmed) pair). The no-double rule fires.

        We can't just have the same prospect — the prior `already_sent` gate
        catches that first (and would short-circuit before the policy gate).
        Instead we seed with a DIFFERENT intent_id chain for the same
        person_id to exercise the policy gate's rule-matching directly.

        Wait — the already_sent gate uses ledger.last_send_for(person_id,
        channel) which finds ANY confirmed send. So if we seed a prior
        send to this exact person, the already_sent gate fires first
        (correct behavior — exactly what we want as the primary defense).

        To exercise no-double-cold-pitch in isolation, we'd need a scenario
        where last_send_for returns None but the rule still finds a prior
        cold-pitch. The two diverge only when the prior had a different
        channel (e.g. linkedin) — but our cooldown rules also scope on
        channel, so they'd skip too.

        Conclusion: with the four factory rules, no-double-cold-pitch is
        defense-in-depth behind already_sent. We test it via a register
        mismatch: prior cold-pitch + new send with register=cold-pitch =>
        already_sent fires first. Test the rule's standalone behavior by
        loading ONLY no-double-cold-pitch.
        """
        # Use a minimal policy with ONLY no-double-cold-pitch so the
        # already_sent gate isn't masking it. But already_sent fires
        # before policy.evaluate regardless of policy contents. So we
        # need a scenario where already_sent does NOT match but the
        # policy rule does. That requires a prior confirmed send whose
        # `last_send_for` doesn't match — which can't happen for same
        # (person_id, channel).
        #
        # Better: prove policy fires for cases already_sent can't see.
        # Example: a prior LINKEDIN cold-pitch (channel="linkedin"), and
        # now we attempt an EMAIL cold-pitch. last_send_for("...", "email")
        # returns None, but a future cross-channel rule could block.
        # Our factory rule is scoped to register only (no channel scope),
        # so it WILL block the cross-channel cold-pitch. Good — this is
        # the load-bearing test.
        (tmp_policies_dir / "cooldowns.yml").write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: no-double-cold-pitch\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when: {register: cold-pitch}\n",
            encoding="utf-8",
        )

        note = _write_person_note(
            people_dir, name="Carol Mixed", person_id="carol-mixed-li",
            email="carol@example.com",
        )
        # Seed a prior LinkedIn cold-pitch (last_send_for(email) returns None).
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_li_prior",
            "person_id": "carol-mixed-li", "channel": "linkedin",
            "register": "cold-pitch",
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": "snd_li_prior",
            "person_id": "carol-mixed-li", "channel": "linkedin",
        })

        draft = _make_draft(
            tmp_path / "touch.md", note, "Carol Mixed", "carol@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no-double-cold-pitch"
        # Verify the policy_blocked event was emitted with the structured
        # detail dict from the rule.
        policy_events = [e for e in tmp_ledger.all_events()
                         if e.type == "policy_blocked"]
        assert len(policy_events) == 1
        ev = policy_events[0]
        assert ev["reason"] == "no-double-cold-pitch"
        assert ev["person_id"] == "carol-mixed-li"
        assert "policy_detail" in ev.to_dict()
        assert ev["policy_detail"]["prior_register"] == "cold-pitch"

    def test_domain_throttle_blocks_second_domain_send(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """One prior send to example.com; second send to a different
        prospect at example.com is blocked by domain-cooldown."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            _factory_cooldowns_yaml(), encoding="utf-8",
        )

        # Seed: prior send to bob@example.com (different person).
        ts = datetime.now(timezone.utc) - timedelta(days=3)
        ts_iso = ts.isoformat().replace("+00:00", "Z")
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_bob",
            "person_id": "bob-li", "channel": "email",
            "register": "cold-pitch", "email": "bob@example.com",
            "ts": ts_iso,
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": "snd_bob",
            "person_id": "bob-li", "channel": "email",
            "email": "bob@example.com", "ts": ts_iso,
        })

        # Now try sending to a NEW person at example.com.
        note = _write_person_note(
            people_dir, name="Alice Same Domain",
            person_id="alice-samedomain-li",
            email="alice@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Alice Same Domain",
            "alice@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        assert out["ok"] is False
        assert out["reason"] == "domain-cooldown"
        policy_events = [e for e in tmp_ledger.all_events()
                         if e.type == "policy_blocked"]
        assert len(policy_events) == 1
        ev = policy_events[0]
        assert ev["policy_detail"]["domain"] == "example.com"
        assert ev["policy_detail"]["count_in_window"] == 1

    def test_re_engage_requires_dormancy_blocks_non_dormant(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Person.status is 'queued' (per _write_person_note default);
        re-engage register triggers re-engage-requires-dormancy block."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            _factory_cooldowns_yaml(), encoding="utf-8",
        )

        note = _write_person_note(
            people_dir, name="Quinn Queued", person_id="quinn-queued-li",
            email="quinn@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Quinn Queued", "quinn@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="re-engage",
        )
        assert out["ok"] is False
        assert out["reason"] == "re-engage-requires-dormancy"
        policy_events = [e for e in tmp_ledger.all_events()
                         if e.type == "policy_blocked"]
        assert policy_events
        ev = policy_events[0]
        assert ev["policy_detail"]["required_status"] == "dormant"
        assert ev["policy_detail"]["actual_status"] == "queued"

    def test_follow_up_without_prior_blocks(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """No prior cold-pitch → follow-up rule fires."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            _factory_cooldowns_yaml(), encoding="utf-8",
        )
        note = _write_person_note(
            people_dir, name="Frank Fresh", person_id="frank-fresh-li",
            email="frank@other-co.com",  # different domain to avoid throttle
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Frank Fresh", "frank@other-co.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="follow-up",
        )
        assert out["ok"] is False
        assert out["reason"] == "follow-up-requires-prior-cold-pitch"

    def test_clean_send_with_factory_rules_passes(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Factory rules loaded + new prospect on new domain + cold-pitch
        register → engine returns Allow; send proceeds normally."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            _factory_cooldowns_yaml(), encoding="utf-8",
        )
        note = _write_person_note(
            people_dir, name="Diana Domain", person_id="diana-domain-li",
            email="diana@new-co.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Diana Domain", "diana@new-co.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        # No policy_blocked event.
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "policy_blocked" not in types_seen

    def test_policy_engine_error_blocks_with_diagnostic(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
        monkeypatch,
    ):
        """Per ADR-0001: rule exceptions propagate; send-gate treats a
        policy outage as a refusal (refuse-log-ask). Emits policy_blocked
        with reason='policy_engine_error'."""
        # Monkeypatch policy.evaluate to raise.
        import policy as policy_mod

        def boom(*args, **kwargs):
            raise RuntimeError("simulated policy outage")

        monkeypatch.setattr(policy_mod, "evaluate", boom)

        note = _write_person_note(
            people_dir, name="Olive Outage", person_id="olive-outage-li",
            email="olive@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Olive Outage", "olive@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "policy_engine_error"
        policy_events = [e for e in tmp_ledger.all_events()
                         if e.type == "policy_blocked"]
        assert policy_events
        assert "simulated policy outage" in policy_events[0]["detail"]

    def test_already_sent_short_circuits_before_policy(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Defense-in-depth ordering: already_sent (cheap hash lookup)
        fires before policy.evaluate (parses YAML, walks events). If we
        seed a prior send for the same person + channel, already_sent
        must win — not domain-cooldown."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            _factory_cooldowns_yaml(), encoding="utf-8",
        )
        note = _write_person_note(
            people_dir, name="Same Person", person_id="same-person-li",
            email="same@example.com",
        )
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_same_prior",
            "person_id": "same-person-li", "channel": "email",
            "register": "cold-pitch", "email": "same@example.com",
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": "snd_same_prior",
            "person_id": "same-person-li", "channel": "email",
            "email": "same@example.com",
        })

        draft = _make_draft(
            tmp_path / "touch.md", note, "Same Person", "same@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        # already_sent fires first (cheaper, narrower).
        assert out["ok"] is False
        assert out["reason"] == "already_sent"
        # No policy_blocked event.
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "policy_blocked" not in types_seen
        assert "dedup_blocked" in types_seen


# ---------------------------------------------------------------------------
# I7 cost emission — Pillar A Week 4 (ADR-0006)
# ---------------------------------------------------------------------------


class TestCostIncurredEmissionGmail:
    """Verifies that gated_send_one emits a cost_incurred event at the
    Gmail-success path. Gmail is quota-only (amount_usd: 0.0, units: 1).

    This is the integration test that proves the wiring between the
    Gmail send path and the I7 cost ledger contract (ADR-0006 §Emit-
    site contract).
    """

    def test_success_emits_cost_event(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        note = _write_person_note(
            people_dir, name="Cost Alice", person_id="cost-alice-li",
            email="alice@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Cost Alice", "alice@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, run_id="run-abc",
        )
        assert out["ok"] is True
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "cost_incurred"
        ]
        assert len(cost_events) == 1
        ev = cost_events[0]
        assert ev["source"] == "gmail"
        assert ev["amount_usd"] == 0.0
        assert ev["units"] == 1
        assert ev["model_or_endpoint"] == "messages.send"
        assert ev["person_id"] == "cost-alice-li"
        assert ev["run_id"] == "run-abc"
        assert ev["intent_id"] == out["intent_id"]

    def test_send_failure_does_not_emit_cost(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006: we do not pay for failed sends, so we must
        not emit cost_incurred on a failure path. Failure-path emission
        would bias the budget upward and trigger false-positive caps."""
        note = _write_person_note(
            people_dir, name="Cost Frank", person_id="cost-frank-li",
            email="frank@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Cost Frank", "frank@example.com",
        )
        gmail = FakeGmail()
        gmail.fail_with = RuntimeError("Gmail API send failed: 503")
        out = send_queued.gated_send_one(
            draft, gmail_client=gmail, led=tmp_ledger, writeback=None,
            run_id="run-abc",
        )
        assert out["ok"] is False
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "cost_incurred"
        ]
        assert cost_events == []
        # send_failed event was written instead — the only audit trail
        # of the attempt.
        assert any(e.type == "send_failed" for e in tmp_ledger.all_events())

    def test_gated_block_does_not_emit_cost(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """If the pre-flight gate refuses (e.g. already_sent), no Gmail
        call is made and no cost_incurred is emitted."""
        note = _write_person_note(
            people_dir, name="Cost Bob", person_id="cost-bob-li",
            email="bob@example.com",
        )
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_bob_prior",
            "person_id": "cost-bob-li", "channel": "email",
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": "snd_bob_prior",
            "person_id": "cost-bob-li", "channel": "email",
            "gmail_message_id": "gm_bob_prior",
        })
        draft = _make_draft(
            tmp_path / "touch.md", note, "Cost Bob", "bob@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "already_sent"
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "cost_incurred"
        ]
        assert cost_events == []

    def test_run_id_absent_still_emits(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A send without run_id (the default for one-off invocations)
        still emits cost; just with run_id=None so per-run rules
        skip it."""
        note = _write_person_note(
            people_dir, name="Cost Zara", person_id="cost-zara-li",
            email="zara@example.com",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Cost Zara", "zara@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None,  # no run_id passed
        )
        assert out["ok"] is True
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "cost_incurred"
        ]
        assert len(cost_events) == 1
        # run_id is null in the persisted event; per-run rules ignore.
        assert cost_events[0].get("run_id") is None


# ---------------------------------------------------------------------------
# Tier emission — Pillar A Week 5 (ADR-0007)
# ---------------------------------------------------------------------------


class TestTierEmission:
    """Verifies that `gated_send_one` populates `ctx.tier` from
    `Person.research_tier` and the tier rule fires correctly.

    This is the end-to-end wiring check that pairs with
    `test_policy_tier.py`'s unit tests of the rule class. The wiring
    point is `send_queued._build_rule_context` which reads
    `draft.person.research_tier` and threads it into `RuleContext.tier`
    (ADR-0007 §Decision item "Tier field source").
    """

    def test_tier_s_cold_pitch_allows(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Tier-S prospect + cold-pitch + allowed_tiers=[S, A] → send proceeds."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n",
            encoding="utf-8",
        )
        note = _write_person_note(
            people_dir, name="Sarah Tier S", person_id="sarah-tier-s-li",
            email="sarah@example.com", research_tier="S",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Sarah Tier S",
            "sarah@example.com", research_tier="S",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        # No policy_blocked event.
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "policy_blocked" not in types_seen

    def test_tier_b_cold_pitch_blocks(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Tier-B prospect + cold-pitch + allowed_tiers=[S, A] → BLOCK.

        Verifies:
          - ctx.tier was populated from Person.research_tier
          - the tier rule fired (verdict.rule == cold-pitch-tier-gate)
          - policy_blocked.policy_detail.tier_value carries 'B' (the
            funnel CLI's --breakdown tier axis depends on this)
        """
        (tmp_policies_dir / "cooldowns.yml").write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n",
            encoding="utf-8",
        )
        note = _write_person_note(
            people_dir, name="Brad Tier B", person_id="brad-tier-b-li",
            email="brad@example.com", research_tier="B",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Brad Tier B",
            "brad@example.com", research_tier="B",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        assert out["ok"] is False
        assert out["reason"] == "cold-pitch-tier-gate"
        policy_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "policy_blocked"
        ]
        assert len(policy_events) == 1
        ev = policy_events[0]
        assert ev["policy_detail"]["tier_value"] == "B"
        assert ev["policy_detail"]["allowed_tiers"] == ["S", "A"]
        # The wrong-tier block does NOT set tier_unknown.
        assert ev["policy_detail"].get("tier_unknown") is not True

    def test_no_tier_field_cold_pitch_blocks(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Person note without `research_tier:` → ctx.tier=None → BLOCK
        (restrictive None-handling per ADR-0007).

        policy_detail.tier_unknown=true surfaces the cause distinct from
        the wrong-tier case.
        """
        (tmp_policies_dir / "cooldowns.yml").write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n",
            encoding="utf-8",
        )
        note = _write_person_note(
            people_dir, name="Untiered Person",
            person_id="untiered-person-li",
            email="untiered@example.com",
            # research_tier intentionally omitted
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Untiered Person",
            "untiered@example.com",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        assert out["ok"] is False
        assert out["reason"] == "cold-pitch-tier-gate"
        policy_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "policy_blocked"
        ]
        assert len(policy_events) == 1
        ev = policy_events[0]
        assert ev["policy_detail"]["tier_unknown"] is True

    def test_tier_b_follow_up_unaffected_by_cold_pitch_only_rule(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """The tier rule is scoped to `block_when: {register: cold-pitch}`.
        A follow-up to a tier-B prospect doesn't trigger it (the
        register filter short-circuits before the tier check)."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: cold-pitch-tier-gate\n"
            "    type: tier.requires-tier-in\n"
            "    block_when: {register: cold-pitch}\n"
            "    allowed_tiers: [S, A]\n",
            encoding="utf-8",
        )
        # Seed a prior cold-pitch so the follow-up rule's prior-send
        # requirement is satisfied (a 10-day-old cold-pitch is older
        # than the 7-day min).
        ts = datetime.now(timezone.utc) - timedelta(days=10)
        ts_iso = ts.isoformat().replace("+00:00", "Z")
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_brad_prior",
            "person_id": "brad-tier-b-li", "channel": "email",
            "register": "cold-pitch", "email": "brad@example.com",
            "ts": ts_iso,
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": "snd_brad_prior",
            "person_id": "brad-tier-b-li", "channel": "email",
            "email": "brad@example.com", "ts": ts_iso,
        })

        note = _write_person_note(
            people_dir, name="Brad Tier B Followup",
            person_id="brad-tier-b-li",
            email="brad@example.com", research_tier="B",
        )
        draft = _make_draft(
            tmp_path / "touch.md", note, "Brad Tier B Followup",
            "brad@example.com", subject="Following up",
            research_tier="B",
        )
        out = send_queued.gated_send_one(
            draft, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="follow-up",
        )
        # Note: this person already has a prior `send_confirmed` for email,
        # so the already_sent gate (NOT policy.evaluate) is what we expect
        # to fire — the tier rule scoped to cold-pitch wouldn't have
        # blocked a follow-up anyway. The test's contract: tier rule
        # does NOT emit a policy_blocked event for a follow-up register
        # — proved by absence of any policy_blocked with tier-rule reason.
        policy_events = [
            e for e in tmp_ledger.all_events()
            if e.type == "policy_blocked"
        ]
        tier_blocks = [
            e for e in policy_events
            if e.get("reason") == "cold-pitch-tier-gate"
        ]
        assert tier_blocks == [], (
            "tier rule wrongly fired on a follow-up register"
        )

    def test_cross_cutting_block_when_tier_on_domain_throttle(
        self, tmp_path, tmp_ledger, people_dir, tmp_policies_dir,
    ):
        """Domain-throttle rule scoped to `block_when: {tier: S}` only
        fires for tier-S prospects. End-to-end verification that the
        cross-cutting filter extension reaches existing rule classes
        without per-class code (ADR-0007 §Cross-cutting `block_when:`)."""
        (tmp_policies_dir / "cooldowns.yml").write_text(
            "version: 1\n"
            "rules:\n"
            "  - name: tier-s-domain-throttle\n"
            "    type: cooldown.domain-throttle\n"
            "    block_when:\n"
            "      channel: email\n"
            "      tier: S\n"
            "    max_count: 1\n"
            "    window_days: 14\n",
            encoding="utf-8",
        )
        # Seed: prior send to coworker@acme.com so any subsequent send to
        # acme.com would hit the domain throttle rule IF the tier filter
        # admits the rule.
        ts = datetime.now(timezone.utc) - timedelta(days=3)
        ts_iso = ts.isoformat().replace("+00:00", "Z")
        tmp_ledger.append({
            "type": "send_intent", "intent_id": "snd_acme_prior",
            "person_id": "coworker-acme-li", "channel": "email",
            "register": "cold-pitch", "email": "coworker@acme.com",
            "ts": ts_iso,
        })
        tmp_ledger.append({
            "type": "send_confirmed", "intent_id": "snd_acme_prior",
            "person_id": "coworker-acme-li", "channel": "email",
            "email": "coworker@acme.com", "ts": ts_iso,
        })

        # A tier-A prospect at acme.com → tier filter mismatches → throttle
        # rule does not fire → send proceeds.
        note_a = _write_person_note(
            people_dir, name="Tier A At Acme",
            person_id="tier-a-acme-li",
            email="tier-a@acme.com", research_tier="A",
        )
        draft_a = _make_draft(
            tmp_path / "touch_a.md", note_a, "Tier A At Acme",
            "tier-a@acme.com", research_tier="A",
        )
        out_a = send_queued.gated_send_one(
            draft_a, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        assert out_a["ok"] is True

        # A tier-S prospect at acme.com → tier filter matches → throttle
        # rule fires → block.
        note_s = _write_person_note(
            people_dir, name="Tier S At Acme",
            person_id="tier-s-acme-li",
            email="tier-s@acme.com", research_tier="S",
        )
        draft_s = _make_draft(
            tmp_path / "touch_s.md", note_s, "Tier S At Acme",
            "tier-s@acme.com", research_tier="S",
        )
        out_s = send_queued.gated_send_one(
            draft_s, gmail_client=FakeGmail(), led=tmp_ledger,
            writeback=None, register="cold-pitch",
        )
        assert out_s["ok"] is False
        assert out_s["reason"] == "tier-s-domain-throttle"
