"""Pillar C Week 5 — Twitter DM two-phase send + gate behavior.

Verifies:
  - Pre-flight gate blocks: already_sent, identity_incomplete, locked,
    no_twitter_handle, no_dm_body.
  - **NO requires-follow gate** (ADR-0018 D60 ALLOW posture — opposite
    of LinkedIn DM's D44 refuse-loud; Twitter's filtered-DM inbox is
    recipient-recoverable).
  - Two-phase commit: tw_dm_intent + tw_dm_confirmed pair on success
    per ADR-0014 D33 (every event carries channel: twitter).
  - MCP failure path: tw_dm_failed event written; no confirm;
    returns ok=False.
  - Vault writeback: touch frontmatter gets twitter_state: messaged
    + twitter_messaged_at + tw_dm_intent_id + tw_dm_thread_id (when
    the MCP returns one) + tw_dm_confirmed_at.
  - Intent-id marker (ADR-0018 D58): the DM body the dispatcher
    passes to the MCP contains the zero-width-space-surrounded
    intent_id marker.
  - cost_incurred emission (ADR-0015 D40 split-source convention +
    ADR-0018 D58): source="twitter_dm" on every successful DM send.
  - Body-length pre-flight: dispatcher refuses-loud when DM body +
    intent-id marker would exceed Twitter's 10000-char limit.
  - Blocked-return-dict shape contract: ``twitter_thread_id`` key
    present (None on blocked); no ``gmail_message_id`` /
    ``linkedin_thread_id`` keys leaked.

Mirrors tests/test_send_gate_linkedin_dm.py shape — fakes + per-test
isolation, no live MCP calls.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# --- bootstrap (mirror test_send_gate_linkedin_dm.py) ----------------------

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
    linkedin: str | None = "in/test-person",
    twitter_handle: str | None = "test_person",
    email: str | None = None,
) -> Path:
    """Write a Twitter-channel Person note. ``twitter_handle`` is the
    channel-surface field the Week 5 dispatcher reads (per ADR-0018
    D60). ``linkedin`` is present for identity-strength mint (gives a
    ``-li`` provenance suffix via Phase 5.5 mint_id logic); operators
    with a Twitter-only Person and no LinkedIn URL fail
    identity_incomplete per the existing identity gate."""
    fm_lines = [
        "---",
        "type: person",
        f"id: {person_id}",
        "identity_keys:",
    ]
    if linkedin:
        fm_lines.append(f"  linkedin: {linkedin}")
    if twitter_handle:
        fm_lines.append(f"  twitter: {twitter_handle}")
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
    if twitter_handle:
        fm_lines.append(f"twitter_handle: {twitter_handle}")
    fm_lines += [
        "status: contacted",
        "pipeline_stage: ready",
        "---",
        "# body",
    ]
    note = people_dir / f"{name}.md"
    note.write_text("\n".join(fm_lines) + "\n", encoding="utf-8")
    return note


def _make_tw_dm_draft(
    touch_path: Path,
    person_path: Path,
    name: str,
    *,
    linkedin: str | None = "in/test-person",
    twitter_handle: str | None = "test_person",
    email: str | None = None,
    dm_text: str = "Hey, sharing some notes on agent infra.",
) -> _vault.TouchDraft:
    """Construct a Twitter DM TouchDraft for unit testing."""
    touch_path.write_text(
        "---\n"
        "type: touch\n"
        f"person: '[[{name}]]'\n"
        "channel: twitter\n"
        "sent: false\n"
        "---\n"
        "## Twitter DM\n"
        f"{dm_text}\n",
        encoding="utf-8",
    )
    person_info = _vault.PersonInfo(
        name=name, note_path=person_path, email=email,
        linkedin=linkedin, status="contacted",
        research_tier=None,
        twitter_handle=twitter_handle,
    )
    return _vault.TouchDraft(
        note_path=touch_path,
        frontmatter={
            "type": "touch", "person": f"[[{name}]]",
            "channel": "twitter", "sent": False,
        },
        body="",
        person_name=name,
        person=person_info,
        channel_declared="twitter",
        has_email_block=False,
        has_linkedin_block=False,
        email_subject=None,
        email_body=None,
        linkedin_dm=None,
        has_twitter_block=True,
        twitter_dm=dm_text,
        issues=[],
    )


class FakeTwitter:
    """Bare-minimum stand-in for a Twitter cookie-scrape MCP client (DM
    mode).

    Accepts ``send_dm`` calls; records each call; can be configured to
    raise via ``fail_with``. The dispatcher tests inspect ``self.sent``
    to verify what was sent (in particular the intent-id marker per
    ADR-0018 D58).

    Also exposes ``list_recent_dms`` for reconcile Pass F tests that
    share this fake — the Pillar C Week 5 fake is one client with two
    surfaces, mirroring how a cookie-scrape MCP adapter would wrap
    both send + read endpoints.
    """

    def __init__(self):
        self.sent: list[dict] = []
        self.recent_dms: list[dict] = []
        self.fail_with: Exception | None = None
        self.fail_list_dms: Exception | None = None
        self._next_id = 1
        self.list_dms_calls: list[int] = []

    def send_dm(
        self, *, twitter_handle: str, message: str,
        intent_id: str | None = None,
    ) -> str | None:
        if self.fail_with is not None:
            raise self.fail_with
        thread_id = f"tw-thread-{self._next_id:03d}"
        self._next_id += 1
        self.sent.append({
            "thread_id": thread_id,
            "twitter_handle": twitter_handle,
            "message": message,
            "intent_id": intent_id,
        })
        return thread_id

    def list_recent_dms(self, limit: int = 100) -> list[dict]:
        self.list_dms_calls.append(limit)
        if self.fail_list_dms is not None:
            raise self.fail_list_dms
        return list(self.recent_dms[:limit])


# ---------------------------------------------------------------------------
# Gate behavior — base path + no-follow-state-gate posture (D60)
# ---------------------------------------------------------------------------


class TestTwitterDMGate:
    def test_allows_clean_dm_to_any_handle(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0018 D60: a Twitter Person with id + twitter_handle
        succeeds — NO follow-state check (opposite of LinkedIn DM's D44)."""
        note = _write_person_note(
            people_dir, name="Evan Clean", person_id="evan-clean-li",
            twitter_handle="evan_clean",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Evan Clean",
            twitter_handle="evan_clean",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger,
            writeback=None,
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        assert out["intent_id"]
        assert out["twitter_thread_id"]
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "tw_dm_intent" in types_seen
        assert "tw_dm_confirmed" in types_seen

    def test_blocks_already_sent(self, tmp_path, tmp_ledger, people_dir):
        """Prior tw_dm_confirmed for the same person triggers
        already_sent dedup. Generalized last_send_for path filtered to
        channel=twitter."""
        note = _write_person_note(
            people_dir, name="Fay Done", person_id="fay-done-li",
        )
        tmp_ledger.append({
            "type": "tw_dm_intent", "intent_id": "twdm_prior",
            "person_id": "fay-done-li", "channel": "twitter",
        })
        tmp_ledger.append({
            "type": "tw_dm_confirmed", "intent_id": "twdm_prior",
            "person_id": "fay-done-li", "channel": "twitter",
        })
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Fay Done",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "already_sent"
        assert tw.sent == []
        blocked = [e for e in tmp_ledger.all_events()
                   if e.type == "dedup_blocked"]
        assert len(blocked) == 1
        assert blocked[0].get("channel") == "twitter"

    def test_blocks_no_twitter_handle(self, tmp_path, tmp_ledger, people_dir):
        """A Person without a twitter_handle field cannot receive a DM."""
        note = _write_person_note(
            people_dir, name="Gus NoTW", person_id="gus-notw-li",
            twitter_handle=None,
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Gus NoTW",
            twitter_handle=None,
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_twitter_handle"
        assert tw.sent == []

    def test_blocks_tmp_identity(self, tmp_path, tmp_ledger, people_dir):
        """A Person with a -tmp id (identity_incomplete) cannot send."""
        note = people_dir / "Hera Tmp.md"
        note.write_text(
            "---\n"
            "type: person\n"
            "id: hera-tmp-2026-tmp\n"
            "identity_keys: {}\n"
            "name: Hera Tmp\n"
            "twitter_handle: hera_tmp\n"
            "---\n",
            encoding="utf-8",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Hera Tmp",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "identity_incomplete"
        assert tw.sent == []

    def test_lock_blocks(self, tmp_path, tmp_ledger, people_dir):
        """A held lock blocks the send."""
        note = _write_person_note(
            people_dir, name="Ivy Locked", person_id="ivy-locked-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Ivy Locked",
        )

        def _no_lock(name):
            return (False, "held by other agent")

        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
            acquire_lock=_no_lock,
        )
        assert out["ok"] is False
        assert out["reason"] == "locked"
        assert tw.sent == []

    def test_empty_dm_body_blocks(self, tmp_path, tmp_ledger, people_dir):
        """A draft with no Twitter DM body is refused — operators
        shouldn't send empty messages."""
        note = _write_person_note(
            people_dir, name="Joe Empty", person_id="joe-empty-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Joe Empty",
            dm_text="",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_dm_body"
        assert tw.sent == []


# ---------------------------------------------------------------------------
# No requires-follow-state gate (ADR-0018 D60 ALLOW)
# ---------------------------------------------------------------------------


class TestNoFollowStateGate:
    """Per ADR-0018 D60: DMs to non-follows route to the recipient's
    filtered Message Requests tab (recipient-recoverable + visible via
    notification badge), so the asymmetric-failure-cost calculus inverts
    from LinkedIn DM's refuse-loud posture (per ADR-0016 D44). The
    Twitter dispatcher does NOT check follow state; no
    ``allow_unconnected``-style override exists because no gate exists
    to override.
    """

    def test_sends_without_follow_state_field(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The dispatcher does NOT read any follow-state field on the
        Person note — absent / true / false all produce identical
        behavior (gate passes if twitter_handle present)."""
        note = _write_person_note(
            people_dir, name="Kira NoFollow", person_id="kira-nofollow-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Kira NoFollow",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert len(tw.sent) == 1

    def test_sends_even_with_explicit_unfollow_field(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """An operator who stamps ``twitter_followed: false`` on their
        Person note does NOT see the dispatcher refuse — the field is
        not read by the dispatcher per ADR-0018 D60. Per-Person
        follow-state enforcement is the operator's policy YAML
        responsibility (cooldown rule against tier.match-rule), not the
        dispatcher's gate."""
        note_path = people_dir / "Lia Unfollowed.md"
        note_path.write_text(
            "---\n"
            "type: person\n"
            "id: lia-unfollowed-li\n"
            "identity_keys:\n"
            "  linkedin: in/lia-unfollowed\n"
            "  twitter: lia_unfollowed\n"
            "name: Lia Unfollowed\n"
            "linkedin: in/lia-unfollowed\n"
            "twitter_handle: lia_unfollowed\n"
            "twitter_followed: false\n"
            "---\n",
            encoding="utf-8",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note_path, "Lia Unfollowed",
            twitter_handle="lia_unfollowed",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert len(tw.sent) == 1


# ---------------------------------------------------------------------------
# Two-phase commit
# ---------------------------------------------------------------------------


class TestTwoPhase:
    def test_intent_then_confirm_pair(self, tmp_path, tmp_ledger, people_dir):
        """One tw_dm_intent + one tw_dm_confirmed, same intent_id."""
        note = _write_person_note(
            people_dir, name="Maya Pair", person_id="maya-pair-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Maya Pair",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        intent_id = out["intent_id"]
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "tw_dm_intent"
        ]
        confirms = [
            e for e in tmp_ledger.all_events() if e.type == "tw_dm_confirmed"
        ]
        assert len(intents) == 1
        assert len(confirms) == 1
        assert intents[0].intent_id == intent_id
        assert confirms[0].intent_id == intent_id

    def test_every_event_carries_channel_twitter(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """ADR-0014 D33 invariant — every two-phase event carries
        channel=twitter."""
        note = _write_person_note(
            people_dir, name="Nina Chan", person_id="nina-chan-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Nina Chan",
        )
        tw = FakeTwitter()
        send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        for e in tmp_ledger.all_events():
            if e.type in ("tw_dm_intent", "tw_dm_confirmed"):
                assert e.get("channel") == "twitter"

    def test_mcp_failure_writes_tw_dm_failed(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """When the cookie-scrape MCP raises, dispatcher writes
        tw_dm_failed (NOT tw_dm_confirmed) and returns ok=False."""
        note = _write_person_note(
            people_dir, name="Omi Fail", person_id="omi-fail-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Omi Fail",
        )
        tw = FakeTwitter()
        tw.fail_with = RuntimeError("MCP transient error")
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "send_failed"
        failed = [
            e for e in tmp_ledger.all_events() if e.type == "tw_dm_failed"
        ]
        confirmed = [
            e for e in tmp_ledger.all_events() if e.type == "tw_dm_confirmed"
        ]
        assert len(failed) == 1
        assert failed[0].get("channel") == "twitter"
        assert failed[0].get("error_class") == "RuntimeError"
        assert len(confirmed) == 0


# ---------------------------------------------------------------------------
# Intent-id marker (ADR-0018 D58)
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
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Pia Mark",
            dm_text="Hey! Quick thought on Estefan Labs infra.",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        intent_id = out["intent_id"]
        # The MCP received a single call.
        assert len(tw.sent) == 1
        sent_msg = tw.sent[0]["message"]
        # The intent_id is embedded in the message text.
        assert intent_id in sent_msg
        # The intent_id marker is wrapped in zero-width-spaces (U+200B).
        assert "​outreach-intent:" in sent_msg
        # The intent_id parameter is also passed explicitly to the MCP
        # (so a future MCP that exposes a tracking-token surface can
        # correlate without parsing the message text).
        assert tw.sent[0]["intent_id"] == intent_id


# ---------------------------------------------------------------------------
# cost_incurred emission (ADR-0015 D40 split-source convention + D58)
# ---------------------------------------------------------------------------


class TestCostEmission:
    def test_success_emits_cost_incurred_with_twitter_dm_source(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006 + ADR-0015 D40 + ADR-0018 D58: every successful
        Twitter DM emits cost_incurred with source="twitter_dm".
        Distinct from ``"linkedin_dm"`` + ``"linkedin_invite"`` so
        operators can configure separate per-channel budget rules."""
        note = _write_person_note(
            people_dir, name="Quin Cost", person_id="quin-cost-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Quin Cost",
        )
        tw = FakeTwitter()
        send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert len(cost_events) == 1
        e = cost_events[0]
        assert e.get("source") == "twitter_dm"
        assert e.get("amount_usd") == 0.0  # quota-only.
        assert e.get("units") == 1
        assert e.get("person_id") == "quin-cost-li"
        assert e.get("model_or_endpoint") == "twitter_client.send_dm"

    def test_failure_does_not_emit_cost_incurred(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006: failed sends do NOT emit cost_incurred (we
        don't pay for failures; biasing the budget would defeat its
        purpose)."""
        note = _write_person_note(
            people_dir, name="Rio Fail", person_id="rio-fail-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Rio Fail",
        )
        tw = FakeTwitter()
        tw.fail_with = RuntimeError("MCP error")
        send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert cost_events == []


# ---------------------------------------------------------------------------
# DM body-length pre-flight (mirrors LinkedIn paths' P2-1 discipline)
# ---------------------------------------------------------------------------


class TestDMBodyLengthPreflight:
    """Mirrors the LinkedIn DM path's body-length refuse-loud. Twitter
    DM bodies have a 10000-char limit (vs LinkedIn's 8000); the marker
    eats ~30 chars. Refuse-loud at the boundary forecloses the surprise-
    overflow failure mode (per ADR-0018 D58)."""

    def test_long_body_blocks_before_intent_write(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A DM body that pushes the total over 10000 chars is refused;
        no tw_dm_intent is written; no MCP call is made."""
        note = _write_person_note(
            people_dir, name="Sue Long", person_id="sue-long-li",
        )
        # 10000+ chars of body content.
        long_dm = "Hi! " + ("padding text " * 900)  # ~11700 chars
        assert len(long_dm) > send_queued.TWITTER_DM_BODY_MAX_CHARS
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Sue Long",
            dm_text=long_dm,
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "dm_body_too_long"
        assert tw.sent == []
        intents = [
            e for e in tmp_ledger.all_events() if e.type == "tw_dm_intent"
        ]
        assert intents == []

    def test_short_body_within_limit_passes(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A short DM body (well under the limit) passes pre-flight."""
        note = _write_person_note(
            people_dir, name="Tia Mid", person_id="tia-mid-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Tia Mid",
            dm_text="Hi, sharing notes on agent infra.",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert len(tw.sent) == 1

    def test_twitter_limit_is_higher_than_linkedin(self):
        """Sanity check on the constant: Twitter's body limit per
        ADR-0018 D58 is 10000 (vs LinkedIn's 8000 per ADR-0016 D43)."""
        assert send_queued.TWITTER_DM_BODY_MAX_CHARS == 10000
        assert (
            send_queued.TWITTER_DM_BODY_MAX_CHARS
            > send_queued.LINKEDIN_DM_BODY_MAX_CHARS
        )


# ---------------------------------------------------------------------------
# Success return-dict shape contract
# ---------------------------------------------------------------------------


class TestSuccessReturnDictShape:
    """Mirrors the LinkedIn DM path's discipline: the documented
    success return shape includes ``detail``. Callers reading
    ``outcome["detail"]`` via direct subscript should not get a
    KeyError."""

    def test_success_return_dict_contains_detail_key(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        note = _write_person_note(
            people_dir, name="Una Shape", person_id="una-shape-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Una Shape",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert "detail" in out
        assert out["detail"] is None

    def test_success_return_dict_includes_twitter_thread_id(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The dispatcher returns the MCP's thread_id when present.
        Pillar D's reply-classifier reads ``twitter_thread_id`` from
        the confirmed event + the dispatcher's return dict."""
        note = _write_person_note(
            people_dir, name="Vic Thread", person_id="vic-thread-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Vic Thread",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["twitter_thread_id"] is not None
        # And the same thread_id is stamped on the confirmed event.
        confirmed = [
            e for e in tmp_ledger.all_events() if e.type == "tw_dm_confirmed"
        ]
        assert len(confirmed) == 1
        assert confirmed[0].get("twitter_thread_id") == out["twitter_thread_id"]


# ---------------------------------------------------------------------------
# Blocked return-dict shape contract (per Week 3 P2-2 discipline)
# ---------------------------------------------------------------------------


class TestBlockedReturnDictShape:
    """Per Week 3 per-week review P2-2 (carried to Week 5): the
    dispatcher's blocked-path return shape must match the documented
    success-path shape per channel. The Twitter dispatcher's blocked
    paths thread ``result_extras=TW_DM_BLOCK_EXTRAS`` which stamps
    ``twitter_thread_id: None`` on every refusal.
    """

    def test_blocked_path_includes_twitter_thread_id_key(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The blocked path return dict contains ``twitter_thread_id``
        (set to ``None``) but does NOT contain ``gmail_message_id`` or
        ``linkedin_thread_id`` — the per-channel result_extras override
        applies."""
        note = _write_person_note(
            people_dir, name="Wes Refused", person_id="wes-refused-li",
            twitter_handle=None,  # triggers no_twitter_handle
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Wes Refused",
            twitter_handle=None,
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_twitter_handle"
        # The Twitter DM-shape key is present (None on the blocked path).
        assert "twitter_thread_id" in out
        assert out["twitter_thread_id"] is None
        # Other channel keys are NOT in the dict.
        assert "gmail_message_id" not in out
        assert "linkedin_thread_id" not in out
        assert "linkedin_invitation_id" not in out

    def test_blocked_path_consistent_across_refusal_reasons(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Every refusal path in gated_tw_dm_one threads
        result_extras=TW_DM_BLOCK_EXTRAS — the blocked shape is uniform
        regardless of which gate fired."""
        # no_twitter_handle + already_sent are the two reasons easiest to
        # induce without crossing into MCP-call territory.

        # Case 1: no_twitter_handle
        note1 = _write_person_note(
            people_dir, name="Xeno NoTW", person_id="xeno-notw-li",
            twitter_handle=None,
        )
        draft1 = _make_tw_dm_draft(
            tmp_path / "touch1.md", note1, "Xeno NoTW",
            twitter_handle=None,
        )
        tw = FakeTwitter()
        out1 = send_queued.gated_tw_dm_one(
            draft1, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out1["reason"] == "no_twitter_handle"
        assert "twitter_thread_id" in out1
        assert out1["twitter_thread_id"] is None

        # Case 2: already_sent
        note2 = _write_person_note(
            people_dir, name="Yara Sent", person_id="yara-sent-li",
        )
        tmp_ledger.append({
            "type": "tw_dm_intent", "intent_id": "twdm_prior_ys",
            "person_id": "yara-sent-li", "channel": "twitter",
        })
        tmp_ledger.append({
            "type": "tw_dm_confirmed", "intent_id": "twdm_prior_ys",
            "person_id": "yara-sent-li", "channel": "twitter",
        })
        draft2 = _make_tw_dm_draft(
            tmp_path / "touch2.md", note2, "Yara Sent",
        )
        out2 = send_queued.gated_tw_dm_one(
            draft2, twitter_client=tw, led=tmp_ledger, writeback=None,
        )
        assert out2["reason"] == "already_sent"
        assert "twitter_thread_id" in out2
        assert out2["twitter_thread_id"] is None


# ---------------------------------------------------------------------------
# Vault writeback contract (ADR-0018 D58 + D64)
# ---------------------------------------------------------------------------


class TestVaultWriteback:
    """The default writeback path stamps Twitter-specific fields on the
    touch note + Person note. Tests run the live writeback (no
    ``writeback=None``) against a tmp_path vault structure."""

    def test_writeback_stamps_twitter_state_messaged(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """``twitter_state: messaged`` + ``twitter_messaged_at:`` land
        on the touch note frontmatter; ``tw_dm_intent_id:`` +
        ``tw_dm_thread_id:`` + ``tw_dm_confirmed_at:`` correlate the
        touch to the ledger event."""
        note = _write_person_note(
            people_dir, name="Zane WB", person_id="zane-wb-li",
        )
        touch_path = tmp_path / "touch.md"
        draft = _make_tw_dm_draft(
            touch_path, note, "Zane WB",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger,
        )
        assert out["ok"] is True
        # Reload the touch note frontmatter to verify the writeback.
        touch_fm, _ = _vault.split_frontmatter(touch_path.read_text())
        assert touch_fm.get("sent") is True
        assert touch_fm.get("twitter_state") == "messaged"
        assert touch_fm.get("twitter_messaged_at") is not None
        assert touch_fm.get("tw_dm_intent_id") == out["intent_id"]
        assert touch_fm.get("tw_dm_thread_id") == out["twitter_thread_id"]
        assert touch_fm.get("tw_dm_confirmed_at") is not None

    def test_writeback_updates_person_last_touch(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Person.last_touch updates to today after a successful send."""
        note = _write_person_note(
            people_dir, name="Ana Last", person_id="ana-last-li",
        )
        draft = _make_tw_dm_draft(
            tmp_path / "touch.md", note, "Ana Last",
        )
        tw = FakeTwitter()
        out = send_queued.gated_tw_dm_one(
            draft, twitter_client=tw, led=tmp_ledger,
        )
        assert out["ok"] is True
        person_fm, _ = _vault.split_frontmatter(note.read_text())
        assert person_fm.get("last_touch") is not None
