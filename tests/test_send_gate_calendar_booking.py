"""Pillar C Week 6 — Calendar booking dispatcher + gate behavior.

Verifies:
  - Pre-flight gate blocks: already_sent, identity_incomplete, locked,
    no_cal_com_base_url, no_cover_message, booking_url_too_long.
  - **No external API call at send time** (ADR-0019 D66 — Cal.com is
    webhook-driven; the dispatcher only synthesizes the URL).
  - Asymmetric two-phase commit: ``calendar_booking_intent`` written at
    send time per ADR-0014 D33 (channel: calendar); the matching
    ``calendar_booking_confirmed`` is webhook-emitted (NOT this
    dispatcher's concern).
  - URL synthesis (ADR-0019 D65): the dispatcher returns
    ``<base>?intent_id=cb_<ULID>`` for the operator to embed.
  - Vault writeback: ``calendar_booking_intent_id`` +
    ``calendar_booking_url`` + ``calendar_booking_invited_at`` on the
    touch note frontmatter.
  - ``cost_incurred`` emission (ADR-0015 D40 split-source + ADR-0019
    D65): source="calendar_booking" on every successful synthesis.
  - Per-Person ``calendar_booking_url_base:`` override behavior.
  - Blocked-return-dict shape: ``calendar_booking_url`` /
    ``calendar_booking_id`` keys present (None on blocked).

Mirrors tests/test_send_gate_twitter_dm.py shape — fakes + per-test
isolation, no live Cal.com calls.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# --- bootstrap (mirror test_send_gate_twitter_dm.py) ----------------------

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


DEFAULT_CAL_COM_URL = "https://cal.com/acme/intro"


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
    email: str | None = "test@example.com",
    calendar_booking_url_base: str | None = None,
) -> Path:
    """Write a Person note for calendar-booking testing. Per-Person
    ``calendar_booking_url_base:`` is optional (operators with multiple
    booking link types stamp it per-Person)."""
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
    if calendar_booking_url_base:
        fm_lines.append(f"calendar_booking_url_base: {calendar_booking_url_base}")
    fm_lines += [
        "status: contacted",
        "pipeline_stage: ready",
        "---",
        "# body",
    ]
    note = people_dir / f"{name}.md"
    note.write_text("\n".join(fm_lines) + "\n", encoding="utf-8")
    return note


def _make_calendar_draft(
    touch_path: Path,
    person_path: Path,
    name: str,
    *,
    linkedin: str | None = "in/test-person",
    email: str | None = "test@example.com",
    calendar_booking_url_base: str | None = None,
    cover_text: str = "Grab any 30 minutes here:",
) -> _vault.TouchDraft:
    """Construct a Calendar booking TouchDraft for unit testing."""
    touch_path.write_text(
        "---\n"
        "type: touch\n"
        f"person: '[[{name}]]'\n"
        "channel: calendar\n"
        "sent: false\n"
        "---\n"
        "## Calendar\n"
        "```\n"
        f"{cover_text}\n"
        "```\n",
        encoding="utf-8",
    )
    person_info = _vault.PersonInfo(
        name=name, note_path=person_path, email=email,
        linkedin=linkedin, status="contacted",
        research_tier=None,
        calendar_booking_url_base=calendar_booking_url_base,
    )
    return _vault.TouchDraft(
        note_path=touch_path,
        frontmatter={
            "type": "touch", "person": f"[[{name}]]",
            "channel": "calendar", "sent": False,
        },
        body="",
        person_name=name,
        person=person_info,
        channel_declared="calendar",
        has_email_block=False,
        has_linkedin_block=False,
        email_subject=None,
        email_body=None,
        linkedin_dm=None,
        has_twitter_block=False,
        twitter_dm=None,
        has_calendar_block=True,
        calendar_cover_message=cover_text,
        issues=[],
    )


# ---------------------------------------------------------------------------
# Gate behavior — base path + no Cal.com URL
# ---------------------------------------------------------------------------


class TestCalendarBookingGate:
    def test_allows_clean_booking(self, tmp_path, tmp_ledger, people_dir):
        """Per ADR-0019: a Person with id + operator cal_com_base_url
        succeeds; emits intent + cost; returns URL."""
        note = _write_person_note(
            people_dir, name="Alice Clean", person_id="alice-clean-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Alice Clean",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        assert out["reason"] == "sent"
        assert out["intent_id"]
        assert out["intent_id"].startswith("cb_")
        assert out["calendar_booking_url"]
        assert "intent_id=" in out["calendar_booking_url"]
        # Pre-webhook, calendar_booking_id is None.
        assert out["calendar_booking_id"] is None
        types_seen = {e.type for e in tmp_ledger.all_events()}
        assert "calendar_booking_intent" in types_seen
        # No confirmed at send time — webhook ships that later.
        assert "calendar_booking_confirmed" not in types_seen

    def test_allows_redispatch_when_intent_only_no_confirmed(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per Week 6 per-week review dispatcher P2-1: pin the
        intent-only re-dispatch contract as a deliberate behavior, not
        a silent gap.

        ``ledger.last_send_for`` filters on confirmed-outcome events
        (per ADR-0010 + ledger.py docstring "most-recent CONFIRMED
        outreach"). A calendar booking intent that has NOT yet received
        its webhook-driven confirmed event therefore does NOT block a
        second dispatch. This is operator-deliberate per the asymmetric
        two-phase shape (ADR-0019 D66) — the recipient may have
        ignored the first link; the operator may legitimately want to
        share a refreshed link.

        Re-dispatch protection for "I shared the link very recently"
        cases lives at the policy-engine layer (a future
        ``budget.window-cap`` rule against ``source=calendar_booking``
        with a 24h window blocks rapid re-dispatch). The dispatcher's
        gate is intentionally permissive on this axis; the policy
        layer is the operator-deliberate refinement.
        """
        note = _write_person_note(
            people_dir, name="Adam Redispatch", person_id="adam-redispatch-li",
        )
        # Seed an intent (no confirmed) — simulating a prior dispatch
        # whose Cal.com webhook never arrived (or the recipient never
        # booked).
        tmp_ledger.append({
            "type": "calendar_booking_intent",
            "intent_id": "cb_PRIORINTENT12345678ABCDEFG",
            "person_id": "adam-redispatch-li", "channel": "calendar",
            "booking_url": "https://cal.com/acme/intro?intent_id=cb_PRIORINTENT12345678ABCDEFG",
        })
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Adam Redispatch",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        # Re-dispatch is allowed — the new intent gets a distinct id.
        assert out["ok"] is True
        assert out["intent_id"] != "cb_PRIORINTENT12345678ABCDEFG"
        intents = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_intent"
        ]
        assert len(intents) == 2

    def test_blocks_already_sent(self, tmp_path, tmp_ledger, people_dir):
        """Prior calendar_booking_confirmed for the same person triggers
        already_sent dedup. Generalized last_send_for path filtered to
        channel=calendar."""
        note = _write_person_note(
            people_dir, name="Brent Done", person_id="brent-done-li",
        )
        tmp_ledger.append({
            "type": "calendar_booking_intent",
            "intent_id": "cb_prior_test_001",
            "person_id": "brent-done-li", "channel": "calendar",
        })
        tmp_ledger.append({
            "type": "calendar_booking_confirmed",
            "intent_id": "cb_prior_test_001",
            "person_id": "brent-done-li", "channel": "calendar",
        })
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Brent Done",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "already_sent"
        blocked = [
            e for e in tmp_ledger.all_events()
            if e.type == "dedup_blocked"
        ]
        assert len(blocked) == 1
        assert blocked[0].get("channel") == "calendar"

    def test_blocks_no_cal_com_base_url(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Without an operator-default URL AND no per-Person override,
        the dispatcher refuses-loud (no URL to share = no booking)."""
        note = _write_person_note(
            people_dir, name="Cory NoBase", person_id="cory-nobase-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Cory NoBase",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url="", led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_cal_com_base_url"

    def test_blocks_tmp_identity(self, tmp_path, tmp_ledger, people_dir):
        """A Person with a -tmp id cannot send."""
        note = people_dir / "Dora Tmp.md"
        note.write_text(
            "---\n"
            "type: person\n"
            "id: dora-tmp-2026-tmp\n"
            "identity_keys: {}\n"
            "name: Dora Tmp\n"
            "---\n",
            encoding="utf-8",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Dora Tmp",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "identity_incomplete"

    def test_lock_blocks(self, tmp_path, tmp_ledger, people_dir):
        """A held lock blocks the send."""
        note = _write_person_note(
            people_dir, name="Erin Locked", person_id="erin-locked-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Erin Locked",
        )

        def _no_lock(name):
            return (False, "held by other agent")

        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
            acquire_lock=_no_lock,
        )
        assert out["ok"] is False
        assert out["reason"] == "locked"

    def test_empty_cover_message_blocks(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A touch with no Calendar block body is refused — operators
        shouldn't share bare booking URLs without context."""
        note = _write_person_note(
            people_dir, name="Finn Empty", person_id="finn-empty-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Finn Empty",
            cover_text="",
        )
        # Patch the draft to actually drop the cover_message (the fixture
        # builder writes it; we override here to model the empty case).
        draft.calendar_cover_message = ""
        draft.has_calendar_block = False
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "no_cover_message"


# ---------------------------------------------------------------------------
# URL synthesis (ADR-0019 D65)
# ---------------------------------------------------------------------------


class TestURLSynthesis:
    def test_url_has_intent_id_query_param(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The dispatcher returns ``<base>?intent_id=cb_<ULID>``."""
        note = _write_person_note(
            people_dir, name="Gail URL", person_id="gail-url-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Gail URL",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url="https://cal.com/acme/intro",
            led=tmp_ledger, writeback=None,
        )
        url = out["calendar_booking_url"]
        assert url.startswith("https://cal.com/acme/intro?intent_id=cb_")
        # The intent_id in the URL matches the ledger event's intent_id.
        intent_id = out["intent_id"]
        assert f"intent_id={intent_id}" in url

    def test_url_appends_with_ampersand_when_base_has_query(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A base URL with existing query string gets ``&intent_id=``
        instead of ``?``."""
        note = _write_person_note(
            people_dir, name="Hank Amp", person_id="hank-amp-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Hank Amp",
        )
        out = send_queued.gated_calendar_booking_one(
            draft,
            cal_com_base_url="https://cal.com/acme/intro?event=intro30",
            led=tmp_ledger, writeback=None,
        )
        url = out["calendar_booking_url"]
        assert "?event=intro30&intent_id=cb_" in url

    def test_per_person_url_base_overrides_default(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """A Person's ``calendar_booking_url_base:`` overrides the
        operator-default cal_com_base_url kwarg."""
        note = _write_person_note(
            people_dir, name="Iris Per", person_id="iris-per-li",
            calendar_booking_url_base="https://cal.com/acme/coffee-15",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Iris Per",
            calendar_booking_url_base="https://cal.com/acme/coffee-15",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url="https://cal.com/acme/intro",
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is True
        url = out["calendar_booking_url"]
        # Per-Person override wins; the operator-default URL is absent.
        assert "coffee-15" in url
        assert "intro" not in url

    def test_long_base_url_blocks(self, tmp_path, tmp_ledger, people_dir):
        """A base URL that would overflow CALENDAR_BOOKING_URL_MAX_CHARS
        when combined with the intent_id query param refuses-loud."""
        note = _write_person_note(
            people_dir, name="Jack Long", person_id="jack-long-li",
        )
        # Construct a base URL pushing us past the limit (~2048 chars).
        long_path = "/long" + ("padding" * 300)
        long_base = f"https://cal.com{long_path}"
        assert len(long_base) > 2000
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Jack Long",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=long_base,
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "booking_url_too_long"

    def test_base_url_with_fragment_refuses(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per Week 6 per-week review dispatcher P2-2: a base URL with
        a ``#`` fragment would silently corrupt the booking link (RFC
        3986: fragment must be last; appending ?intent_id= after #
        produces a URL the query param never reaches Cal.com from).
        The dispatcher refuses-loud at the URL-synthesis layer with
        ``booking_url_too_long`` (the URL is structurally too broken
        to ship, not literally too long; the refusal reason
        consolidates the two structural-validation cases per the
        asymmetric-failure-cost calculus)."""
        note = _write_person_note(
            people_dir, name="Zoe Frag", person_id="zoe-frag-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Zoe Frag",
        )
        out = send_queued.gated_calendar_booking_one(
            draft,
            cal_com_base_url="https://cal.com/acme/intro#timeslots",
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert out["reason"] == "booking_url_too_long"
        # No tw_dm_intent / no cost_incurred / no writeback was attempted.
        intents = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_intent"
        ]
        assert intents == []


# ---------------------------------------------------------------------------
# Asymmetric two-phase commit (intent only at send time; confirmed later
# from webhook)
# ---------------------------------------------------------------------------


class TestAsymmetricTwoPhase:
    def test_only_intent_emitted_at_send_time(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """ADR-0019 D66 inverts Weeks 2-5's synchronous shape: the
        dispatcher emits ONLY calendar_booking_intent. The webhook
        emits the confirmed event later when the recipient books."""
        note = _write_person_note(
            people_dir, name="Kira Intent", person_id="kira-intent-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Kira Intent",
        )
        send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        intents = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_intent"
        ]
        confirms = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_confirmed"
        ]
        assert len(intents) == 1
        assert len(confirms) == 0

    def test_intent_carries_channel_calendar(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """ADR-0014 D33 invariant — every event carries channel=calendar."""
        note = _write_person_note(
            people_dir, name="Liam Chan", person_id="liam-chan-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Liam Chan",
        )
        send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        for e in tmp_ledger.all_events():
            if e.type == "calendar_booking_intent":
                assert e.get("channel") == "calendar"

    def test_intent_carries_booking_url(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The emitted intent event carries the synthesized URL so
        downstream consumers (Pillar D win-attribution) can verify
        which URL was shared without reading the touch note."""
        note = _write_person_note(
            people_dir, name="Mia URL", person_id="mia-url-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Mia URL",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        intent_evs = [
            e for e in tmp_ledger.all_events()
            if e.type == "calendar_booking_intent"
        ]
        assert len(intent_evs) == 1
        assert intent_evs[0].get("booking_url") == out["calendar_booking_url"]


# ---------------------------------------------------------------------------
# cost_incurred emission (ADR-0015 D40 split-source + D65)
# ---------------------------------------------------------------------------


class TestCostEmission:
    def test_success_emits_cost_incurred_with_calendar_booking_source(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006 + ADR-0015 D40 + ADR-0019 D65: every successful
        synthesis emits cost_incurred with source="calendar_booking"."""
        note = _write_person_note(
            people_dir, name="Nina Cost", person_id="nina-cost-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Nina Cost",
        )
        send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert len(cost_events) == 1
        e = cost_events[0]
        assert e.get("source") == "calendar_booking"
        assert e.get("amount_usd") == 0.0
        assert e.get("units") == 1
        assert e.get("person_id") == "nina-cost-li"

    def test_cost_emitted_after_intent(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per Week 6 per-week review dispatcher P2-3: pin the
        calendar_booking_intent → cost_incurred append ordering.
        Downstream observability queries that read events by ts order
        depend on the intent landing before the cost; a regression
        that flipped the order would silently bias Pillar G dashboards.
        """
        note = _write_person_note(
            people_dir, name="Order Test", person_id="order-test-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Order Test",
        )
        send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        events = list(tmp_ledger.all_events())
        types = [e.type for e in events]
        intent_idx = types.index("calendar_booking_intent")
        cost_idx = types.index("cost_incurred")
        assert intent_idx < cost_idx

    def test_blocked_does_not_emit_cost_incurred(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Per ADR-0006: blocked paths do NOT emit cost_incurred (we
        don't pay for refusals)."""
        # already_sent blocks (cheapest induction).
        note = _write_person_note(
            people_dir, name="Owen Skip", person_id="owen-skip-li",
        )
        tmp_ledger.append({
            "type": "calendar_booking_intent",
            "intent_id": "cb_prior_owen",
            "person_id": "owen-skip-li", "channel": "calendar",
        })
        tmp_ledger.append({
            "type": "calendar_booking_confirmed",
            "intent_id": "cb_prior_owen",
            "person_id": "owen-skip-li", "channel": "calendar",
        })
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Owen Skip",
        )
        send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        cost_events = [
            e for e in tmp_ledger.all_events() if e.type == "cost_incurred"
        ]
        assert cost_events == []


# ---------------------------------------------------------------------------
# Blocked return-dict shape contract (per Week 3 P2-2 discipline)
# ---------------------------------------------------------------------------


class TestBlockedReturnDictShape:
    """The dispatcher's blocked-path return shape must match the
    documented success-path shape — calendar booking dispatcher carries
    ``calendar_booking_url`` + ``calendar_booking_id`` (both None on
    blocked).
    """

    def test_blocked_path_includes_calendar_keys(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """The blocked path return dict contains
        ``calendar_booking_url`` + ``calendar_booking_id`` (both None)
        and does NOT leak other channels' keys."""
        note = _write_person_note(
            people_dir, name="Pia NoBase", person_id="pia-nobase-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Pia NoBase",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url="",  # → no_cal_com_base_url
            led=tmp_ledger, writeback=None,
        )
        assert out["ok"] is False
        assert "calendar_booking_url" in out
        assert out["calendar_booking_url"] is None
        assert "calendar_booking_id" in out
        assert out["calendar_booking_id"] is None
        # Other channel keys leak-checks.
        assert "gmail_message_id" not in out
        assert "linkedin_thread_id" not in out
        assert "twitter_thread_id" not in out

    def test_blocked_path_consistent_across_refusal_reasons(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Every refusal path threads result_extras="
        CALENDAR_BOOKING_BLOCK_EXTRAS — the blocked shape is uniform."""
        # Case 1: no_cal_com_base_url
        note1 = _write_person_note(
            people_dir, name="Quinn None", person_id="quinn-none-li",
        )
        draft1 = _make_calendar_draft(
            tmp_path / "touch1.md", note1, "Quinn None",
        )
        out1 = send_queued.gated_calendar_booking_one(
            draft1, cal_com_base_url="", led=tmp_ledger, writeback=None,
        )
        assert out1["reason"] == "no_cal_com_base_url"
        assert out1["calendar_booking_url"] is None
        assert out1["calendar_booking_id"] is None

        # Case 2: already_sent
        note2 = _write_person_note(
            people_dir, name="Reed Sent", person_id="reed-sent-li",
        )
        tmp_ledger.append({
            "type": "calendar_booking_intent", "intent_id": "cb_prior_reed",
            "person_id": "reed-sent-li", "channel": "calendar",
        })
        tmp_ledger.append({
            "type": "calendar_booking_confirmed",
            "intent_id": "cb_prior_reed",
            "person_id": "reed-sent-li", "channel": "calendar",
        })
        draft2 = _make_calendar_draft(
            tmp_path / "touch2.md", note2, "Reed Sent",
        )
        out2 = send_queued.gated_calendar_booking_one(
            draft2, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        assert out2["reason"] == "already_sent"
        assert out2["calendar_booking_url"] is None
        assert out2["calendar_booking_id"] is None


# ---------------------------------------------------------------------------
# Vault writeback contract (ADR-0019 D65)
# ---------------------------------------------------------------------------


class TestVaultWriteback:
    """The default writeback path stamps calendar-specific fields on
    the touch note + Person note."""

    def test_writeback_stamps_calendar_fields(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """``sent: true`` + ``calendar_booking_intent_id`` +
        ``calendar_booking_url`` + ``calendar_booking_invited_at`` land
        on the touch note frontmatter."""
        note = _write_person_note(
            people_dir, name="Saul WB", person_id="saul-wb-li",
        )
        touch_path = tmp_path / "touch.md"
        draft = _make_calendar_draft(
            touch_path, note, "Saul WB",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger,
        )
        assert out["ok"] is True
        touch_fm, _ = _vault.split_frontmatter(touch_path.read_text())
        assert touch_fm.get("sent") is True
        assert touch_fm.get("calendar_booking_intent_id") == out["intent_id"]
        assert touch_fm.get("calendar_booking_url") == out["calendar_booking_url"]
        assert touch_fm.get("calendar_booking_invited_at") is not None
        # confirmed_at is NOT stamped at send time — webhook stamps it later.
        assert touch_fm.get("calendar_booking_confirmed_at") is None

    def test_writeback_updates_person_last_touch(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Person.last_touch updates after a successful send."""
        note = _write_person_note(
            people_dir, name="Tara Last", person_id="tara-last-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Tara Last",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger,
        )
        assert out["ok"] is True
        person_fm, _ = _vault.split_frontmatter(note.read_text())
        assert person_fm.get("last_touch") is not None


# ---------------------------------------------------------------------------
# Intent-id prefix discipline (ADR-0019 D65)
# ---------------------------------------------------------------------------


class TestIntentIdPrefix:
    def test_intent_id_uses_cb_prefix(self, tmp_path, tmp_ledger, people_dir):
        """The dispatcher mints ``cb_<26-char ULID>`` IDs per ADR-0019
        D65 — distinct from email's ``snd_`` / Twitter's runtime
        ``snd_`` / LinkedIn's ``snd_`` prefixes so URL inspection +
        webhook routing can short-circuit on the prefix."""
        note = _write_person_note(
            people_dir, name="Una Pre", person_id="una-pre-li",
        )
        draft = _make_calendar_draft(
            tmp_path / "touch.md", note, "Una Pre",
        )
        out = send_queued.gated_calendar_booking_one(
            draft, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        intent_id = out["intent_id"]
        assert intent_id.startswith("cb_")
        # 26-char ULID body after the prefix.
        assert len(intent_id) == 3 + 26

    def test_intent_id_is_unique_across_calls(
        self, tmp_path, tmp_ledger, people_dir,
    ):
        """Two successive calls mint distinct intent IDs."""
        note_a = _write_person_note(
            people_dir, name="Val A", person_id="val-a-li",
        )
        note_b = _write_person_note(
            people_dir, name="Val B", person_id="val-b-li",
        )
        draft_a = _make_calendar_draft(
            tmp_path / "touch_a.md", note_a, "Val A",
        )
        draft_b = _make_calendar_draft(
            tmp_path / "touch_b.md", note_b, "Val B",
        )
        out_a = send_queued.gated_calendar_booking_one(
            draft_a, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        out_b = send_queued.gated_calendar_booking_one(
            draft_b, cal_com_base_url=DEFAULT_CAL_COM_URL,
            led=tmp_ledger, writeback=None,
        )
        assert out_a["intent_id"] != out_b["intent_id"]


# ---------------------------------------------------------------------------
# Module-level constants pinning (per Week 5 source-level discipline)
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_constants_exist(self):
        """Pillar C Week 6 must expose the named constants in
        send_queued.py per ADR-0019."""
        assert hasattr(send_queued, "CALENDAR_BOOKING_INTENT_ID_PREFIX")
        assert send_queued.CALENDAR_BOOKING_INTENT_ID_PREFIX == "cb_"
        assert hasattr(send_queued, "CALENDAR_BOOKING_URL_MAX_CHARS")
        assert send_queued.CALENDAR_BOOKING_URL_MAX_CHARS == 2048
        assert hasattr(send_queued, "CALENDAR_BOOKING_BLOCK_EXTRAS")

    def test_block_extras_contain_calendar_keys(self):
        """The calendar BLOCK_EXTRAS map carries calendar_booking_url
        + calendar_booking_id (both None defaults)."""
        extras = send_queued.CALENDAR_BOOKING_BLOCK_EXTRAS
        assert "calendar_booking_url" in extras
        assert extras["calendar_booking_url"] is None
        assert "calendar_booking_id" in extras
        assert extras["calendar_booking_id"] is None

    def test_dispatcher_function_signature(self):
        """gated_calendar_booking_one accepts the expected kwargs."""
        import inspect
        sig = inspect.signature(send_queued.gated_calendar_booking_one)
        params = sig.parameters
        # Required draft (positional).
        assert "draft" in params
        # Keyword-only kwargs.
        assert "cal_com_base_url" in params
        assert "led" in params
        assert "register" in params
        assert "run_id" in params
        assert "acquire_lock" in params
        assert "release_lock" in params
        assert "writeback" in params
