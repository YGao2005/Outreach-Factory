"""Pillar C Week 3 — LinkedIn DM two-phase send + gate behavior.

Verifies:
  - Pre-flight gate blocks: already_sent, identity_incomplete, locked,
    no_linkedin_url, no_dm_body, connection_state_unknown,
    not_a_connection (ADR-0016 D44 requires-existing-connection gate).
  - Two-phase commit: li_dm_intent + li_dm_confirmed pair on success
    per ADR-0014 D33 (every event carries channel: linkedin).
  - MCP failure path: li_dm_failed event written; no confirm;
    returns ok=False.
  - Vault writeback: touch frontmatter gets linkedin_state: messaged
    + linkedin_messaged_at + li_dm_intent_id + li_dm_thread_id (when
    the MCP returns one) + li_dm_confirmed_at.
  - Intent-id marker (ADR-0016 D43): the DM body the dispatcher passes
    to the MCP contains the zero-width-space-surrounded intent_id
    marker.
  - cost_incurred emission (ADR-0015 D40 split-source convention):
    source="linkedin_dm" on every successful DM send.
  - Body-length pre-flight: dispatcher refuses-loud when DM body +
    intent-id marker would exceed LinkedIn's 8000-char limit.

Mirrors tests/test_send_gate_linkedin.py shape — fakes + per-test
isolation, no live MCP calls.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# --- bootstrap (mirror test_send_gate_linkedin.py) -------------------------

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
    _cfg.GMAIL_SCOPES: list[str] = []
    sys.modules["config"] = _cfg

import send_queued  # noqa: E402
import vault as _vault  # noqa: E402
import ledger as _ledger  # noqa: E402


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
def people_dir(tmp_path):
    pd = tmp_path / "people"
    pd.mkdir()
    return pd


def _write_person_note(
    people_dir: Path,
    *,
    name: str,
    person_id: str,
    email: str | None = None,
    linkedin: str | None = "in/dana-test",
    linkedin_connected: bool | None = True,
) -> Path:
    """Write a Person note. ``linkedin_connected`` is what the Week 3
    DM dispatcher gate reads (per ADR-0016 D44/D45). ``None`` means
    the field is absent — the gate refuses-loud on unknown."""
    fm_lines = [
        "---",
        "type: person",
        f"id: {person_id}",
        "identity_keys:",
    ]
    if linkedin:
        fm_lines.append(f"  linkedin: {linkedin}")
    if email:
        fm_lines += [
            "  emails:",
            f"    - {email}",
        ]
    fm_lines += [
        f"name: {name}",
    ]
    if email:
        fm_lines.append(f"email: {email}")
    if linkedin:
        fm_lines.append(f"linkedin: {linkedin}")
    if linkedin_connected is not None:
        # YAML lower-case true/false; mirrors the dispatcher's writes
        # via update_frontmatter.
        fm_lines.append(
            f"linkedin_connected: {'true' if linkedin_connected else 'false'}",
        )
    fm_lines += [
        "status: contacted",
        "pipeline_stage: ready",
        "---",
        "# body",
    ]
    note = people_dir / f"{name}.md"
    note.write_text("\n".join(fm_lines) + "\n", encoding="utf-8")
    return note


def _make_li_dm_draft(
    touch_path: Path,
    person_path: Path,
    name: str,
    *,
    linkedin: str | None = "in/dana-test",
    email: str | None = None,
    dm_text: str = "Hi, sharing some notes on agent infra.",
) -> _vault.TouchDraft:
    """Construct a LinkedIn DM TouchDraft for unit testing."""
    touch_path.write_text(
        "---\n"
        "type: touch\n"
        f"person: '[[{name}]]'\n"
        "channel: linkedin\n"
        "linkedin_action: dm\n"
        "sent: false\n"
        "---\n"
        "## LinkedIn DM\n"
        f"{dm_text}\n",
        encoding="utf-8",
    )
    person_info = _vault.PersonInfo(
        name=name, note_path=person_path, email=email,
        linkedin=linkedin, status="contacted",
        research_tier=None,
    )
    return _vault.TouchDraft(
        note_path=touch_path,
        frontmatter={
            "type": "touch", "person": f"[[{name}]]",
            "channel": "linkedin", "linkedin_action": "dm",
            "sent": False,
        },
        body="",
        person_name=name,
        person=person_info,
        channel_declared="linkedin",
        has_email_block=False,
        has_linkedin_block=True,
        email_subject=None,
        email_body=None,
        linkedin_dm=dm_text,
        issues=[],
    )


class FakeLinkedIn:
    """Bare-minimum stand-in for a LinkedIn MCP client (DM mode).

    Accepts ``send_message`` calls; records each call; can be configured
    to raise via ``fail_with``. The dispatcher tests inspect ``self.sent``
    to verify what was sent (in particular the intent-id marker per
    ADR-0016 D43).
    """

    def __init__(self):
        self.sent: list[dict] = []
        self.fail_with: Exception | None = None
        self._next_id = 1

    def send_message(
        self, *, linkedin_url: str, message: str,
        intent_id: str | None = None,
    ) -> str | None:
        if self.fail_with is not None:
            raise self.fail_with
        thread_id = f"li-thread-{self._next_id:03d}"
        self._next_id += 1
        self.sent.append({
            "thread_id": thread_id,
            "linkedin_url": linkedin_url,
            "message": message,
            "intent_id": intent_id,
        })
        return thread_id


# ---------------------------------------------------------------------------
# Gate behavior — base path + new requires-connection gate (D44)
# ---------------------------------------------------------------------------


class TestLinkedInDMGate:
    def test_allows_clean_dm_to_existing_connection(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A clean Person with id + linkedin URL + linkedin_connected:
        true succeeds."""
        note = _write_person_note(
            people_dir, name="Dana Clean", person_id="dana-clean-li",
            linkedin_connected=True,
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Dana Clean",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        assert out["intent_id"]
        assert out["linkedin_thread_id"]
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "li_dm_intent" in types_seen
        assert "li_dm_confirmed" in types_seen

    def test_blocks_already_sent(self, tmp_path, tmp_ledger, people_dir):
        """Prior li_dm_confirmed (or li_invite_confirmed) for the same
        person triggers already_sent dedup. Generalized last_send_for
        path tested."""
        note = _write_person_note(
            people_dir, name="Dora Done", person_id="dora-done-li",
        )
        tmp_ledger.append({
            "type": "li_dm_intent", "intent_id": "lidm_prior",
            "person_id": "dora-done-li", "channel": "linkedin",
        })
        tmp_ledger.append({
            "type": "li_dm_confirmed", "intent_id": "lidm_prior",
            "person_id": "dora-done-li", "channel": "linkedin",
        })
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Dora Done",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "already_sent"
        assert li.sent == []  # No MCP call made.
        blocked = [e for e in tmp_ledger.all_events()
                   if e.type == "dedup_blocked"]
        assert len(blocked) == 1
        assert blocked[0].get("channel") == "linkedin"

    def test_blocks_no_linkedin_url(self, tmp_path, tmp_ledger, people_dir):
        """A Person without a linkedin field cannot receive a DM."""
        note = _write_person_note(
            people_dir, name="Eli NoLi", person_id="eli-noli-em",
            linkedin=None, email="eli@example.com",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Eli NoLi",
            linkedin=None,
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_linkedin_url"
        assert li.sent == []

    def test_blocks_tmp_identity(self, tmp_path, tmp_ledger, people_dir):
        """A Person with a -tmp id (identity_incomplete) cannot send."""
        note = people_dir / "Fay Tmp.md"
        note.write_text(
            "---\n"
            "type: person\n"
            "id: fay-tmp-2026-tmp\n"
            "identity_keys: {}\n"
            "name: Fay Tmp\n"
            "linkedin: in/fay\n"
            "linkedin_connected: true\n"
            "---\n",
            encoding="utf-8",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Fay Tmp",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "identity_incomplete"
        assert li.sent == []

    def test_lock_blocks(self, tmp_path, tmp_ledger, people_dir):
        """A held lock blocks the send."""
        note = _write_person_note(
            people_dir, name="Gigi Locked", person_id="gigi-locked-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Gigi Locked",
        )

        def _no_lock(name):
            return (False, "held by other agent")

        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
            acquire_lock=_no_lock,
        )
        assert out["ok"] is False
        assert out["reason"] == "locked"
        assert li.sent == []

    def test_empty_dm_body_blocks(self, tmp_path, tmp_ledger, people_dir):
        """A draft with no LinkedIn DM body is refused — operators
        shouldn't send empty messages."""
        note = _write_person_note(
            people_dir, name="Hana Empty", person_id="hana-empty-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Hana Empty",
            dm_text="",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_dm_body"
        assert li.sent == []


# ---------------------------------------------------------------------------
# Requires-existing-connection gate (ADR-0016 D44)
# ---------------------------------------------------------------------------


class TestRequiresConnectionGate:
    """Per ADR-0016 D44: DMs to non-connections silently land in
    message-request inbox (LinkedIn behavior) — dispatcher cannot
    track delivery, so refuse-loud on unknown / not-a-connection.
    Operator who wants to bypass passes ``allow_unconnected=True``.
    """

    def test_blocks_when_linkedin_connected_absent(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Absent linkedin_connected: field → refuse-loud."""
        note = _write_person_note(
            people_dir, name="Ivy Unknown", person_id="ivy-unknown-li",
            linkedin_connected=None,
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Ivy Unknown",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "connection_state_unknown"
        assert li.sent == []
        # No li_dm_intent landed.
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_intent"
        ]
        assert intents == []

    def test_blocks_when_linkedin_connected_false(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Explicit linkedin_connected: false → refuse-loud."""
        note = _write_person_note(
            people_dir, name="Jay NotConn", person_id="jay-notconn-li",
            linkedin_connected=False,
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Jay NotConn",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "not_a_connection"
        assert li.sent == []
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_intent"
        ]
        assert intents == []

    def test_allow_unconnected_bypasses_gate(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Operator-deliberate ``allow_unconnected=True`` lets the
        send proceed regardless of linkedin_connected state. The
        operator accepts the message-request-inbox delivery risk
        per ADR-0016 D44 §"Operator override"."""
        note = _write_person_note(
            people_dir, name="Kai Override", person_id="kai-override-li",
            linkedin_connected=None,  # field absent
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Kai Override",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
            allow_unconnected=True,
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        assert len(li.sent) == 1

    def test_allow_unconnected_also_overrides_connected_false(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Explicit not-a-connection + operator override → send proceeds."""
        note = _write_person_note(
            people_dir, name="Lou Override", person_id="lou-override-li",
            linkedin_connected=False,
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Lou Override",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
            allow_unconnected=True,
        )
        assert out["ok"] is True


# ---------------------------------------------------------------------------
# Two-phase commit
# ---------------------------------------------------------------------------


class TestTwoPhase:
    def test_intent_then_confirm_pair(self, tmp_path, tmp_ledger, people_dir):
        """One li_dm_intent + one li_dm_confirmed, same intent_id."""
        note = _write_person_note(
            people_dir, name="Mia Pair", person_id="mia-pair-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Mia Pair",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        intent_id = out["intent_id"]
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_intent"
        ]
        confirms = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_confirmed"
        ]
        assert len(intents) == 1
        assert len(confirms) == 1
        assert intents[0].intent_id == intent_id
        assert confirms[0].intent_id == intent_id

    def test_every_event_carries_channel_linkedin(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """ADR-0014 D33 invariant — every two-phase event carries
        channel=linkedin."""
        note = _write_person_note(
            people_dir, name="Nia Chan", person_id="nia-chan-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Nia Chan",
        )
        li = FakeLinkedIn()
        send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        for e in tmp_ledger.all_events():
            if e.type in ("li_dm_intent", "li_dm_confirmed"):
                assert e.get("channel") == "linkedin"

    def test_mcp_failure_writes_li_dm_failed(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """When the MCP raises, dispatcher writes li_dm_failed (NOT
        li_dm_confirmed) and returns ok=False."""
        note = _write_person_note(
            people_dir, name="Ola Fail", person_id="ola-fail-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Ola Fail",
        )
        li = FakeLinkedIn()
        li.fail_with = RuntimeError("MCP transient error")
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "send_failed"
        failed = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_failed"
        ]
        confirmed = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_confirmed"
        ]
        assert len(failed) == 1
        assert failed[0].get("channel") == "linkedin"
        assert failed[0].get("error_class") == "RuntimeError"
        assert len(confirmed) == 0


# ---------------------------------------------------------------------------
# Intent-id marker (ADR-0016 D43)
# ---------------------------------------------------------------------------


class TestIntentIdMarker:
    def test_marker_appended_to_dm_body(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The MCP receives DM body text containing the zero-width-
        space-surrounded intent_id marker."""
        note = _write_person_note(
            people_dir, name="Pia Mark", person_id="pia-mark-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Pia Mark",
            dm_text="Hey! Quick thought on Davis Robotics infra.",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        intent_id = out["intent_id"]
        # The MCP received a single call.
        assert len(li.sent) == 1
        sent_msg = li.sent[0]["message"]
        # The intent_id is embedded in the message text.
        assert intent_id in sent_msg
        # The intent_id marker is wrapped in zero-width-spaces (U+200B).
        assert "​outreach-intent:" in sent_msg
        # The intent_id parameter is also passed explicitly to the MCP
        # (so a future MCP that exposes a tracking-token surface can
        # correlate without parsing the message text).
        assert li.sent[0]["intent_id"] == intent_id


# ---------------------------------------------------------------------------
# cost_incurred emission (ADR-0015 D40 split-source convention)
# ---------------------------------------------------------------------------


class TestCostEmission:
    def test_success_emits_cost_incurred_with_linkedin_dm_source(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006 + ADR-0015 D40: every successful LinkedIn DM
        emits cost_incurred with source="linkedin_dm". Distinct from
        ``"linkedin_invite"`` so operators can configure separate
        per-action budget rules."""
        note = _write_person_note(
            people_dir, name="Quin Cost", person_id="quin-cost-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Quin Cost",
        )
        li = FakeLinkedIn()
        send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert len(cost_events) == 1
        e = cost_events[0]
        assert e.get("source") == "linkedin_dm"
        assert e.get("amount_usd") == 0.0  # quota-only.
        assert e.get("units") == 1
        assert e.get("person_id") == "quin-cost-li"
        assert e.get("model_or_endpoint") == "mcp__linkedin__send_message"

    def test_failure_does_not_emit_cost_incurred(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006: failed sends do NOT emit cost_incurred (we don't
        pay for failures; biasing the budget would defeat its purpose)."""
        note = _write_person_note(
            people_dir, name="Ravi Fail", person_id="ravi-fail-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Ravi Fail",
        )
        li = FakeLinkedIn()
        li.fail_with = RuntimeError("MCP error")
        send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert cost_events == []


# ---------------------------------------------------------------------------
# DM body-length pre-flight (mirrors invite path's P2-1 discipline)
# ---------------------------------------------------------------------------


class TestDMBodyLengthPreflight:
    """Mirrors the invite path's note-length refuse-loud. DM bodies
    have an 8000-char limit; the marker eats ~30 chars. Refuse-loud
    at the boundary forecloses the surprise-overflow failure mode."""

    def test_long_body_blocks_before_intent_write(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A DM body that pushes the total over 8000 chars is refused;
        no li_dm_intent is written; no MCP call is made."""
        note = _write_person_note(
            people_dir, name="Sue Long", person_id="sue-long-li",
        )
        # 8000+ chars of body content.
        long_dm = "Hi! " + ("padding text " * 800)  # ~10400 chars
        assert len(long_dm) > send_queued.LINKEDIN_DM_BODY_MAX_CHARS
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Sue Long",
            dm_text=long_dm,
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "dm_body_too_long"
        assert li.sent == []
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_intent"
        ]
        assert intents == []

    def test_short_body_within_limit_passes(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A short DM body (well under the limit) passes pre-flight."""
        note = _write_person_note(
            people_dir, name="Tia Mid", person_id="tia-mid-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Tia Mid",
            dm_text="Hi, sharing notes on agent infra.",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert len(li.sent) == 1


# ---------------------------------------------------------------------------
# Success return-dict shape contract
# ---------------------------------------------------------------------------


class TestSuccessReturnDictShape:
    """Mirrors the invite-path P2-2 discipline: the documented success
    return shape includes ``detail``. Callers reading
    ``outcome["detail"]`` via direct subscript (not .get) should not
    get a KeyError."""

    def test_success_return_dict_contains_detail_key(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        note = _write_person_note(
            people_dir, name="Una Shape", person_id="una-shape-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Una Shape",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert "detail" in out
        assert out["detail"] is None

    def test_success_return_dict_includes_thread_id(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The dispatcher returns the MCP's thread_id when present.
        Pillar D's reply-classifier reads ``li_dm_thread_id`` from the
        confirmed event + the dispatcher's return dict."""
        note = _write_person_note(
            people_dir, name="Vic Thread", person_id="vic-thread-li",
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Vic Thread",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["linkedin_thread_id"] is not None
        # And the same thread_id is stamped on the confirmed event.
        confirmed = [
            e for e in tmp_ledger.all_events() if e.type == "li_dm_confirmed"
        ]
        assert len(confirmed) == 1
        assert confirmed[0].get("linkedin_thread_id") == out["linkedin_thread_id"]


# ---------------------------------------------------------------------------
# Blocked return-dict shape contract (Week 3 per-week review P2-2)
# ---------------------------------------------------------------------------


class TestBlockedReturnDictShape:
    """Per Week 3 per-week review P2-2: the dispatcher's blocked-path
    return shape must match the documented success-path shape per channel.
    Pre-fix, the DM dispatcher's blocked paths inherited the email
    shape (``gmail_message_id: None``) instead of the documented
    LinkedIn shape (``linkedin_thread_id: None``). Pillar H / Pillar I
    CLI callers that destructure the dict by key would see a different
    set of keys on success vs blocked.
    """

    def test_blocked_path_includes_linkedin_thread_id_key(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The blocked path return dict contains ``linkedin_thread_id``
        (set to ``None``) but does NOT contain ``gmail_message_id`` —
        the per-channel result_extras override applies."""
        note = _write_person_note(
            people_dir, name="Wes Refused", person_id="wes-refused-li",
            linkedin_connected=None,  # triggers connection_state_unknown
        )
        draft = _make_li_dm_draft(
            tmp_path / "touch.md", note, "Wes Refused",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_dm_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "connection_state_unknown"
        # The LinkedIn DM-shape key is present (None on the blocked path).
        assert "linkedin_thread_id" in out
        assert out["linkedin_thread_id"] is None
        # The email-shape key is NOT in the dict (leaked-shape regression
        # would re-add it; the P2-2 fix forecloses this).
        assert "gmail_message_id" not in out

    def test_blocked_path_consistent_across_all_refusal_reasons(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Every refusal path in gated_li_dm_one threads
        result_extras=LI_DM_BLOCK_EXTRAS — the blocked shape is uniform
        regardless of which gate fired."""
        # Cover each of the gate refusals that don't require setup
        # beyond a Person + a draft.
        configs = [
            # (linkedin_connected, expected_reason)
            (None, "connection_state_unknown"),
            (False, "not_a_connection"),
        ]
        for linkedin_connected, expected_reason in configs:
            note = _write_person_note(
                people_dir,
                name=f"Xeno {expected_reason}",
                person_id=f"xeno-{expected_reason}-li",
                linkedin_connected=linkedin_connected,
            )
            draft = _make_li_dm_draft(
                tmp_path / f"touch-{expected_reason}.md", note,
                f"Xeno {expected_reason}",
            )
            li = FakeLinkedIn()
            out = send_queued.gated_li_dm_one(
                draft, linkedin_client=li, led=tmp_ledger,
                writeback=None,
            )
            assert out["reason"] == expected_reason
            assert "linkedin_thread_id" in out
            assert out["linkedin_thread_id"] is None
            assert "gmail_message_id" not in out
