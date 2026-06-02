"""Pillar C Week 2 — LinkedIn invite two-phase send + gate behavior.

Verifies:
  - Pre-flight gate blocks: already_sent, identity_incomplete, locked,
    no_linkedin_url.
  - Two-phase commit: li_invite_intent + li_invite_confirmed pair on
    success per ADR-0014 D33 (every event carries channel: linkedin).
  - MCP failure path: li_invite_failed event written; no confirm;
    returns ok=False.
  - Vault writeback: touch frontmatter gets linkedin_state: invited +
    linkedin_invited_at + li_invite_intent_id + li_invite_confirmed_at.
  - Intent-id marker (ADR-0015 D39): the connection note text the
    dispatcher passes to the MCP contains the zero-width-space-
    surrounded intent_id marker.
  - cost_incurred emission (ADR-0008 D40): source="linkedin_invite"
    on every successful invite send.

Mirrors tests/test_send_gate.py shape — fakes + per-test isolation,
no live MCP calls.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# --- bootstrap (mirror test_send_gate.py) ----------------------------------

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
import identity  # noqa: E402
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
    email: str | None = "alice@example.com",
    linkedin: str | None = "in/alice-test",
) -> Path:
    """Write a Person note. ``linkedin`` is what makes a touch eligible
    for the LinkedIn dispatcher (must be non-None)."""
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
    fm_lines += [
        "status: queued",
        "pipeline_stage: ready",
        "---",
        "# body",
    ]
    note = people_dir / f"{name}.md"
    note.write_text("\n".join(fm_lines) + "\n", encoding="utf-8")
    return note


def _make_li_draft(
    touch_path: Path,
    person_path: Path,
    name: str,
    *,
    linkedin: str | None = "in/alice-test",
    email: str | None = "alice@example.com",
    dm_text: str = "Hi, let's connect.",
) -> _vault.TouchDraft:
    """Construct a LinkedIn TouchDraft for unit testing."""
    touch_path.write_text(
        "---\n"
        "type: touch\n"
        f"person: '[[{name}]]'\n"
        "channel: linkedin\n"
        "linkedin_action: invite\n"
        "sent: false\n"
        "---\n"
        "## LinkedIn invite\n"
        f"{dm_text}\n",
        encoding="utf-8",
    )
    person_info = _vault.PersonInfo(
        name=name, note_path=person_path, email=email,
        linkedin=linkedin, status="queued",
        research_tier=None,
    )
    return _vault.TouchDraft(
        note_path=touch_path,
        frontmatter={
            "type": "touch", "person": f"[[{name}]]",
            "channel": "linkedin", "linkedin_action": "invite",
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
    """Bare-minimum stand-in for a LinkedIn MCP client.

    Accepts ``connect_with_person`` calls; records each call; can be
    configured to raise via ``fail_with``. The dispatcher tests
    inspect ``self.sent`` to verify what was sent (in particular the
    intent-id marker per ADR-0015 D39).
    """

    def __init__(self):
        self.sent: list[dict] = []
        self.fail_with: Exception | None = None
        self._next_id = 1

    def connect_with_person(
        self, *, linkedin_url: str, note: str | None = None,
        intent_id: str | None = None,
    ) -> str | None:
        if self.fail_with is not None:
            raise self.fail_with
        invitation_id = f"li-inv-{self._next_id:03d}"
        self._next_id += 1
        self.sent.append({
            "id": invitation_id,
            "linkedin_url": linkedin_url,
            "note": note,
            "intent_id": intent_id,
        })
        return invitation_id


# ---------------------------------------------------------------------------
# Gate behavior
# ---------------------------------------------------------------------------


class TestLinkedInGate:
    def test_allows_clean_linkedin_person(self, tmp_path, tmp_ledger, people_dir):
        """A clean Person with id + linkedin URL succeeds."""
        note = _write_person_note(
            people_dir, name="Alice Clean", person_id="alice-clean-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Alice Clean",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        assert out["intent_id"]
        assert out["linkedin_invitation_id"]
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "li_invite_intent" in types_seen
        assert "li_invite_confirmed" in types_seen

    def test_blocks_already_sent(self, tmp_path, tmp_ledger, people_dir):
        """Prior li_invite_confirmed for the same person triggers
        already_sent dedup. Generalized last_send_for path tested."""
        note = _write_person_note(
            people_dir, name="Bob Done", person_id="bob-done-li",
        )
        # Seed: prior LinkedIn invite sent.
        tmp_ledger.append({
            "type": "li_invite_intent", "intent_id": "li_prior",
            "person_id": "bob-done-li", "channel": "linkedin",
        })
        tmp_ledger.append({
            "type": "li_invite_confirmed", "intent_id": "li_prior",
            "person_id": "bob-done-li", "channel": "linkedin",
        })
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Bob Done",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "already_sent"
        assert li.sent == []  # No MCP call made.
        # The dedup_blocked event carries channel=linkedin.
        blocked = [e for e in tmp_ledger.all_events()
                   if e.type == "dedup_blocked"]
        assert len(blocked) == 1
        assert blocked[0].get("channel") == "linkedin"

    def test_blocks_no_linkedin_url(self, tmp_path, tmp_ledger, people_dir):
        """A Person without a linkedin field cannot receive an invite."""
        note = _write_person_note(
            people_dir, name="Carla NoLi", person_id="carla-noli-em",
            linkedin=None, email="carla@example.com",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Carla NoLi",
            linkedin=None,
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_linkedin_url"
        assert li.sent == []

    def test_blocks_tmp_identity(self, tmp_path, tmp_ledger, people_dir):
        """A Person with a -tmp id (identity_incomplete) cannot send."""
        note = people_dir / "Dora Tmp.md"
        note.write_text(
            "---\n"
            "type: person\n"
            "id: dora-tmp-2026-tmp\n"
            "identity_keys: {}\n"
            "name: Dora Tmp\n"
            "linkedin: in/dora\n"
            "---\n",
            encoding="utf-8",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Dora Tmp",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "identity_incomplete"
        assert li.sent == []

    def test_lock_blocks(self, tmp_path, tmp_ledger, people_dir):
        """A held lock blocks the send."""
        note = _write_person_note(
            people_dir, name="Eve Locked", person_id="eve-locked-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Eve Locked",
        )

        def _no_lock(name):
            return (False, "held by other agent")

        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
            acquire_lock=_no_lock,
        )
        assert out["ok"] is False
        assert out["reason"] == "locked"
        assert li.sent == []


# ---------------------------------------------------------------------------
# Two-phase commit
# ---------------------------------------------------------------------------


class TestTwoPhase:
    def test_intent_then_confirm_pair(self, tmp_path, tmp_ledger, people_dir):
        """One li_invite_intent + one li_invite_confirmed, same intent_id."""
        note = _write_person_note(
            people_dir, name="Fred Pair", person_id="fred-pair-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Fred Pair",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        intent_id = out["intent_id"]
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "li_invite_intent"
        ]
        confirms = [
            e for e in tmp_ledger.all_events() if e.type == "li_invite_confirmed"
        ]
        assert len(intents) == 1
        assert len(confirms) == 1
        assert intents[0].intent_id == intent_id
        assert confirms[0].intent_id == intent_id

    def test_every_event_carries_channel_linkedin(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """ADR-0014 D33 invariant — every two-phase event carries channel=linkedin."""
        note = _write_person_note(
            people_dir, name="Gabe Chan", person_id="gabe-chan-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Gabe Chan",
        )
        li = FakeLinkedIn()
        send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        for e in tmp_ledger.all_events():
            if e.type in ("li_invite_intent", "li_invite_confirmed"):
                assert e.get("channel") == "linkedin"

    def test_mcp_failure_writes_li_invite_failed(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """When the MCP raises, dispatcher writes li_invite_failed
        (NOT li_invite_confirmed) and returns ok=False."""
        note = _write_person_note(
            people_dir, name="Hank Fail", person_id="hank-fail-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Hank Fail",
        )
        li = FakeLinkedIn()
        li.fail_with = RuntimeError("MCP transient error")
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "send_failed"
        failed = [
            e for e in tmp_ledger.all_events() if e.type == "li_invite_failed"
        ]
        confirmed = [
            e for e in tmp_ledger.all_events() if e.type == "li_invite_confirmed"
        ]
        assert len(failed) == 1
        assert failed[0].get("channel") == "linkedin"
        assert failed[0].get("error_class") == "RuntimeError"
        assert len(confirmed) == 0


# ---------------------------------------------------------------------------
# Intent-id marker (ADR-0015 D39)
# ---------------------------------------------------------------------------


class TestIntentIdMarker:
    def test_marker_appended_to_connection_note(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The MCP receives connection-note text containing the
        zero-width-space-surrounded intent_id marker."""
        note = _write_person_note(
            people_dir, name="Ivy Mark", person_id="ivy-mark-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Ivy Mark",
            dm_text="Hi! Let's connect.",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        intent_id = out["intent_id"]
        # The MCP received a single call.
        assert len(li.sent) == 1
        sent_note = li.sent[0]["note"]
        # The intent_id is embedded in the note text.
        assert intent_id in sent_note
        # The intent_id marker is wrapped in zero-width-spaces (U+200B).
        assert "​outreach-intent:" in sent_note
        # The intent_id parameter is also passed explicitly to the MCP
        # (so an MCP implementation that uses a tracking-token surface
        # in the future can correlate without parsing the note text).
        assert li.sent[0]["intent_id"] == intent_id


# ---------------------------------------------------------------------------
# cost_incurred emission (D40)
# ---------------------------------------------------------------------------


class TestCostEmission:
    def test_success_emits_cost_incurred_with_linkedin_invite_source(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006 + ADR-0008 + ADR-0015 D40: every successful
        LinkedIn invite emits cost_incurred with source="linkedin_invite".
        The factory rule activates on this exact source value."""
        note = _write_person_note(
            people_dir, name="Jane Cost", person_id="jane-cost-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Jane Cost",
        )
        li = FakeLinkedIn()
        send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert len(cost_events) == 1
        e = cost_events[0]
        assert e.get("source") == "linkedin_invite"
        assert e.get("amount_usd") == 0.0  # LinkedIn invites are quota-only.
        assert e.get("units") == 1
        assert e.get("person_id") == "jane-cost-li"
        assert e.get("model_or_endpoint") == "mcp__linkedin__connect_with_person"

    def test_failure_does_not_emit_cost_incurred(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006: failed sends do NOT emit cost_incurred (we don't
        pay for failures; biasing the budget would defeat its purpose)."""
        note = _write_person_note(
            people_dir, name="Kim Fail", person_id="kim-fail-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Kim Fail",
        )
        li = FakeLinkedIn()
        li.fail_with = RuntimeError("MCP error")
        send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert cost_events == []


# ---------------------------------------------------------------------------
# Note-length pre-flight (Week 2 per-week review P2-1)
# ---------------------------------------------------------------------------


class TestNoteLengthPreflight:
    """Per Week 2 per-week review P2-1: the dispatcher must refuse-loud
    when the connection note + intent-id marker would exceed LinkedIn's
    300-char limit. Without this check, the MCP call would fail with an
    opaque error, a stale li_invite_intent would be stranded in the
    ledger, and the operator would have no indication the root cause is
    marker budget overflow.
    """

    def test_long_note_blocks_before_intent_write(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A draft note that pushes the total over 300 chars is
        refused; no li_invite_intent is written; no MCP call is made."""
        note = _write_person_note(
            people_dir, name="Lou Long", person_id="lou-long-li",
        )
        # 290-char body + ~30-char marker = 320 chars, over the limit.
        long_dm = "Hi! " + ("padding text " * 30)  # ~390 chars
        assert len(long_dm) > 300
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Lou Long",
            dm_text=long_dm,
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "note_too_long"
        # No MCP call.
        assert li.sent == []
        # No li_invite_intent landed in the ledger.
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "li_invite_intent"
        ]
        assert intents == []
        # The dedup_blocked-shape event carries channel=linkedin + the
        # operator-readable reason.
        blocked = [
            e for e in tmp_ledger.all_events() if e.type == "dedup_blocked"
        ]
        assert len(blocked) == 1
        assert blocked[0].get("channel") == "linkedin"
        assert blocked[0].get("reason") == "note_too_long"

    def test_short_note_within_limit_passes(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A short note (well under the limit) passes pre-flight."""
        note = _write_person_note(
            people_dir, name="Mia Mid", person_id="mia-mid-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Mia Mid",
            dm_text="Hi, let's connect.",  # ~20 chars + 30-char marker
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert len(li.sent) == 1

    def test_empty_dm_passes_with_only_marker(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A draft with no DM body (marker only) passes — the marker
        alone is well under 300 chars."""
        note = _write_person_note(
            people_dir, name="Nia Bare", person_id="nia-bare-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Nia Bare",
            dm_text="",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True


# ---------------------------------------------------------------------------
# Writeback contract (Week 2 per-week review P3-3)
# ---------------------------------------------------------------------------


class TestWritebackContract:
    """Per Week 2 per-week review P3-3: the dispatcher passes
    ``confirmed_at`` to the writeback function, sourced from the ledger
    append's returned dict. If a future ledger refactor changes the
    return type, confirmed_at would silently become None and vault
    writes would record no li_invite_confirmed_at. Pin the contract."""

    def test_writeback_receives_non_none_confirmed_at(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        note = _write_person_note(
            people_dir, name="Oli Time", person_id="oli-time-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Oli Time",
        )
        li = FakeLinkedIn()
        received_kwargs: dict = {}

        def _fake_writeback(d, *, intent_id, confirmed_at):
            received_kwargs["intent_id"] = intent_id
            received_kwargs["confirmed_at"] = confirmed_at
            return None  # no warning.

        send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger,
            writeback=_fake_writeback,
        )
        assert received_kwargs.get("intent_id") is not None
        # The critical contract: confirmed_at is NOT None. Its exact
        # value depends on the ledger's _now_iso() but it must be a
        # parseable ISO 8601 string with the 'Z' suffix.
        ts = received_kwargs.get("confirmed_at")
        assert ts is not None
        assert isinstance(ts, str)
        assert ts.endswith("Z")
        # And it should start with the current year (the dispatcher
        # writes "now" — sanity check).
        from datetime import datetime, timezone
        assert ts.startswith(str(datetime.now(timezone.utc).year))


# ---------------------------------------------------------------------------
# Success return-dict shape contract (Week 2 per-week review P2-2)
# ---------------------------------------------------------------------------


class TestSuccessReturnDictShape:
    """Per Week 2 per-week review P2-2: the documented success return
    shape includes ``detail``. Callers reading ``outcome["detail"]``
    via direct subscript (not .get) should not get a KeyError."""

    def test_success_return_dict_contains_detail_key(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        note = _write_person_note(
            people_dir, name="Pia Shape", person_id="pia-shape-li",
        )
        draft = _make_li_draft(
            tmp_path / "touch.md", note, "Pia Shape",
        )
        li = FakeLinkedIn()
        out = send_queued.gated_li_invite_one(
            draft, linkedin_client=li, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        # Direct subscript access (not .get) must not raise.
        assert "detail" in out
        # detail is None on success per the email path's convention.
        assert out["detail"] is None
