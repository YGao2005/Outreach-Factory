"""Integration: the follow-up cadence does NOT bypass the send guardrails.

The cadence engine decides timing/eligibility only. A follow-up is still a send:
it must pass the SAME gates as a first touch. This module drives the REAL send
path (``send_queued.gated_send_one``) and proves:

  * a genuinely-due follow-up is permitted past the duplicate-send dedup
    (the dedup is REFINED, not removed), and tags each send with followup_step;
  * WITHOUT the cadence (or with it disabled) a second send is still blocked as
    ``already_sent`` (the dedup is intact);
  * a not-yet-due follow-up (delay not elapsed) is blocked;
  * an unsubscribe / reply / bounce terminator after the last touch cancels the
    follow-up, so it can never re-mail someone who opted out (no bypass);
  * ``max_touches`` is enforced at the send path;
  * a due follow-up still flows THROUGH the policy/cooldown gate (no bypass).

Mirrors tests/test_send_gate.py's bootstrap (stub config before importing the
send path so it runs on a bare clone / CI).
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "skills" / "send-outreach" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

if "google_auth_oauthlib" not in sys.modules:
    _gao = types.ModuleType("google_auth_oauthlib")
    _gao_flow = types.ModuleType("google_auth_oauthlib.flow")
    _gao_flow.InstalledAppFlow = object
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
    _cfg.GMAIL_SCOPES = []
    sys.modules["config"] = _cfg

import send_queued  # noqa: E402
import vault as _vault  # noqa: E402
import ledger as _ledger  # noqa: E402

from orchestrator.followup import CadenceConfig  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures + helpers (slim copies of tests/test_send_gate.py's surface)
# --------------------------------------------------------------------------


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(d))
    # Default: no policy rules (empty dir -> Allow), so the dedup/engine are the
    # only gates unless a test writes its own cooldowns.yml.
    pol = tmp_path / "policies"
    pol.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_POLICIES_DIR", str(pol))
    return _ledger.Ledger(d)


def _policies_dir() -> Path:
    import os
    return Path(os.environ["OUTREACH_FACTORY_POLICIES_DIR"])


def _write_person_note(people_dir: Path, *, name, person_id, email) -> Path:
    people_dir.mkdir(parents=True, exist_ok=True)
    note = people_dir / f"{name}.md"
    note.write_text(
        "---\n"
        "type: person\n"
        f"id: {person_id}\n"
        "identity_keys:\n"
        "  emails:\n"
        f"    - {email}\n"
        f"name: {name}\n"
        f"email: {email}\n"
        "status: contacted\n"
        "pipeline_stage: followup_1_ready\n"
        "---\n"
        "# body\n",
        encoding="utf-8",
    )
    return note


def _make_draft(touch_path, person_path, name, email,
                subject="Quick follow-up", body="Bumping this.\n"):
    person_info = _vault.PersonInfo(
        name=name, note_path=person_path, email=email,
        linkedin=None, status="contacted", research_tier=None,
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
    def __init__(self, sender_email="me@example.test"):
        self.sender_email = sender_email
        self.sent: list[dict] = []

    def send_email(self, *, to, subject, body, from_name=None,
                   extra_headers=None, body_footer=None):
        mid = f"mid-{len(self.sent) + 1:03d}"
        tid = f"tid-{len(self.sent) + 1:03d}"
        self.sent.append({"id": mid, "threadId": tid, "to": to,
                          "subject": subject})
        return mid, tid


UTC = timezone.utc


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _seed_cold(led, pid, *, days_ago: int, intent_id="snd_cold"):
    """Seed a confirmed cold touch `days_ago` calendar days back."""
    ts = _iso(datetime.now(UTC) - timedelta(days=days_ago))
    led.append({"type": "send_intent", "intent_id": intent_id, "person_id": pid,
                "channel": "email", "register": "cold-pitch", "ts": ts})
    led.append({"type": "send_confirmed", "intent_id": intent_id, "person_id": pid,
                "channel": "email", "followup_step": 0, "ts": ts})


def _enabled() -> CadenceConfig:
    return CadenceConfig(enabled=True)


def _send(draft, gmail, led, **kw):
    return send_queued.gated_send_one(
        draft, gmail_client=gmail, led=led, writeback=None,
        register="re-engagement", **kw,
    )


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_due_followup_passes_dedup_and_tags_step(tmp_path, tmp_ledger):
    pid = "p-due-li"
    note = _write_person_note(tmp_path / "people", name="Due Person",
                              person_id=pid, email="due@example.com")
    _seed_cold(tmp_ledger, pid, days_ago=14)  # well past 3 business days
    draft = _make_draft(tmp_path / "t.md", note, "Due Person", "due@example.com")

    out = _send(draft, FakeGmail(), tmp_ledger, cadence=_enabled())

    assert out["ok"] is True and out["reason"] == "sent", out
    # The new send is tagged as the first follow-up (touch 2).
    confirmed = [e.to_dict() for e in tmp_ledger.all_events()
                 if e.to_dict()["type"] == "send_confirmed"]
    steps = sorted(e.get("followup_step") for e in confirmed)
    assert steps == [0, 1], f"expected cold(0)+followup(1), got {steps}"


def test_second_send_blocked_without_cadence(tmp_path, tmp_ledger):
    pid = "p-nocad-li"
    note = _write_person_note(tmp_path / "people", name="No Cadence",
                              person_id=pid, email="nc@example.com")
    _seed_cold(tmp_ledger, pid, days_ago=14)
    draft = _make_draft(tmp_path / "t.md", note, "No Cadence", "nc@example.com")

    out = _send(draft, FakeGmail(), tmp_ledger, cadence=None)
    assert out["ok"] is False and out["reason"] == "already_sent", out

    # Disabled cadence is identical to no cadence: the dedup stays strict.
    out2 = _send(draft, FakeGmail(), tmp_ledger, cadence=CadenceConfig(enabled=False))
    assert out2["ok"] is False and out2["reason"] == "already_sent", out2


def test_followup_blocked_when_delay_not_elapsed(tmp_path, tmp_ledger):
    pid = "p-early-li"
    note = _write_person_note(tmp_path / "people", name="Too Early",
                              person_id=pid, email="early@example.com")
    _seed_cold(tmp_ledger, pid, days_ago=0)  # 0 business days elapsed
    draft = _make_draft(tmp_path / "t.md", note, "Too Early", "early@example.com")

    out = _send(draft, FakeGmail(), tmp_ledger, cadence=_enabled())
    assert out["ok"] is False and out["reason"] == "already_sent", out


@pytest.mark.parametrize("term_type", ["suppression_added", "reply_received",
                                       "bounce_detected"])
def test_terminator_blocks_followup_no_bypass(tmp_path, tmp_ledger, term_type):
    pid = "p-term-li"
    note = _write_person_note(tmp_path / "people", name="Opted Out",
                              person_id=pid, email="opt@example.com")
    _seed_cold(tmp_ledger, pid, days_ago=14)
    # A terminator one day AFTER the cold touch cancels the sequence.
    tmp_ledger.append({"type": term_type, "person_id": pid,
                       "ts": _iso(datetime.now(UTC) - timedelta(days=13))})
    draft = _make_draft(tmp_path / "t.md", note, "Opted Out", "opt@example.com")

    out = _send(draft, FakeGmail(), tmp_ledger, cadence=_enabled())
    assert out["ok"] is False and out["reason"] == "already_sent", out


def test_max_touches_blocks_fourth_send(tmp_path, tmp_ledger):
    pid = "p-max-li"
    note = _write_person_note(tmp_path / "people", name="Maxed Out",
                              person_id=pid, email="max@example.com")
    # cold + 2 follow-ups already confirmed = 3 touches = max_touches.
    for i, days in enumerate((40, 30, 20)):
        ts = _iso(datetime.now(UTC) - timedelta(days=days))
        iid = f"snd_{i}"
        tmp_ledger.append({"type": "send_intent", "intent_id": iid, "person_id": pid,
                           "channel": "email", "register": "cold-pitch", "ts": ts})
        tmp_ledger.append({"type": "send_confirmed", "intent_id": iid, "person_id": pid,
                           "channel": "email", "followup_step": i, "ts": ts})
    draft = _make_draft(tmp_path / "t.md", note, "Maxed Out", "max@example.com")

    out = _send(draft, FakeGmail(), tmp_ledger, cadence=_enabled())
    assert out["ok"] is False and out["reason"] == "already_sent", out


def test_due_followup_still_hits_policy_gate(tmp_path, tmp_ledger):
    """A due follow-up is NOT exempt from the cooldown/policy gate: a
    requires-prior-send rule that the re-engagement send violates still blocks
    it (proving the send path runs the policy gate on the follow-up)."""
    (_policies_dir() / "cooldowns.yml").write_text(
        "version: 1\n"
        "rules:\n"
        "  - name: reengagement-requires-old-coldpitch\n"
        "    type: cooldown.requires-prior-send\n"
        "    block_when:\n"
        "      register: re-engagement\n"
        "    requires_register: cold-pitch\n"
        "    min_age_days: 999\n"
        "    reason: re-engagement requires a very old cold-pitch\n",
        encoding="utf-8",
    )
    pid = "p-policy-li"
    note = _write_person_note(tmp_path / "people", name="Policy Gated",
                              person_id=pid, email="pol@example.com")
    _seed_cold(tmp_ledger, pid, days_ago=14)  # due, but only 14d < 999d
    draft = _make_draft(tmp_path / "t.md", note, "Policy Gated", "pol@example.com")

    out = _send(draft, FakeGmail(), tmp_ledger, cadence=_enabled())

    # The dedup let the due follow-up through; the policy gate then refused it.
    assert out["ok"] is False, out
    assert out["reason"] == "reengagement-requires-old-coldpitch", out
    types_seen = [e.to_dict()["type"] for e in tmp_ledger.all_events()]
    assert "policy_blocked" in types_seen, types_seen
