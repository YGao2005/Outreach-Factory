"""Orchestrator: scan vault → preview → batch-confirm → two-phase send → writeback.

Phase 5.5 Week 3: the email send path is now ledger-gated and two-phase.

  Pre-flight gates (hard refusals — NO override flag):
    1. identity.read_person_keys: missing or `-tmp` id  → identity_incomplete
    2. ledger.last_send_for(person_id, "email"):
       a confirmed prior send  → already_sent
    3. policy.evaluate(cooldown_rules, ctx):  (Pillar A Week 1)
       first Block wins, ledger emits `policy_blocked` with rule + detail
    4. orchestrator.locks.acquire: another agent holds the lock  → locked

  Two-phase commit (per surviving draft):
    a. intent_id = ledger.new_intent_id()
    b. ledger.append(send_intent, intent_id, person_id, channel, email,
                      subject_hash)
    c. gmail_client.send_email(...,
            extra_headers={"X-Outreach-Intent-Id": intent_id},
            body_footer="\\u200boutreach-intent:<intent_id>\\u200b")
    d. on success: ledger.append(send_confirmed, intent_id, person_id,
                                  gmail_message_id, gmail_thread_id)
       on failure: ledger.append(send_failed, intent_id, error_class,
                                  error_message)
    e. vault writeback (touch.sent / Person.status / file move)

  Crash semantics: if the process dies between (b) and (d), reconcile Pass A
  recovers via the X-Outreach-Intent-Id header / body footer. Vault is the
  denormalized view; ledger is the authoritative record.

  Run termination: send_run_complete event with counts.

LinkedIn invites/DMs are still emitted as a manifest for Claude to handle
via the LinkedIn MCP (not two-phase yet; tracked for Phase 6).

Pillar G Week 6 (ADR-0055 D300-D306) adds per-stage OTel span
instrumentation at every send-gate call site via
:func:`observability.traced_stage` — the policy evaluation, the
two-phase send, the dispatcher histogram per-channel
:func:`observability.record_send_latency` integration at the four
channels (email / li_invite / li_dm / tw_dm), and the vault writeback
each surface as named spans. Operators tracing the send loop see
the per-gate decision narrative + per-channel latency distribution.
Privacy invariant per ADR-0054 D297 holds across spans.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional


# --- sys.path bootstrap: pull in orchestrator/* without packaging the repo ---
_THIS = Path(__file__).resolve()
_ORCHESTRATOR = _THIS.parent.parent.parent.parent / "orchestrator"
if _ORCHESTRATOR.exists() and str(_ORCHESTRATOR) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR))

import identity                       # noqa: E402
import ledger as _ledger              # noqa: E402
import policy as _policy              # noqa: E402
import security as _security          # noqa: E402  Pillar J J7 — CAN-SPAM footer + List-Unsubscribe (ADR-0079)
# reconcile is imported LAZILY inside _maybe_run_quick_reconcile (not at module
# scope): the pre-send freshness gate is best-effort + opt-out, and reconcile
# pulls the heavy operations tier (conversation state, reply classifier, OTel).
# Keeping the import lazy is what lets the core send path stay import-lean (see
# tests/test_import_graph_lean.py).
from obs import (                      # noqa: E402  no-op span shim; real OTel is opt-in via OUTREACH_FACTORY_OTEL
    get_send_latency_histogram,
    traced_stage,
)

import config as _config              # noqa: E402
from config import (                  # noqa: E402
    LINKEDIN_MANIFEST_PATH,
    LINKEDIN_WEEKLY_INVITE_LIMIT,
    SENDER_NAME,
)

# J7 security/compliance config. Read defensively via getattr so a partial
# config (a minimal config that predates the `security:` block) or a test's
# stubbed `config` module that omits these names does NOT break the import.
# Absent -> None -> main() skips the CAN-SPAM footer.
SECURITY_PHYSICAL_MAILING_ADDRESS = getattr(_config, "SECURITY_PHYSICAL_MAILING_ADDRESS", None)
SECURITY_UNSUBSCRIBE_BASE_URL = getattr(_config, "SECURITY_UNSUBSCRIBE_BASE_URL", None)
SECURITY_UNSUBSCRIBE_MAILTO = getattr(_config, "SECURITY_UNSUBSCRIBE_MAILTO", None)
SECURITY_SUPPRESSION_CHECK_URL = getattr(_config, "SECURITY_SUPPRESSION_CHECK_URL", None)
SECURITY_SUPPRESSION_CHECK_SECRET_ENV = getattr(_config, "SECURITY_SUPPRESSION_CHECK_SECRET_ENV", None)
SECURITY_SUPPRESSION_CHECK_SECRET_PATH = getattr(_config, "SECURITY_SUPPRESSION_CHECK_SECRET_PATH", None)
from gmail_client import GmailClient  # noqa: E402
from vault import (                   # noqa: E402
    TouchDraft,
    _email_pending,
    _linkedin_pending,
    count_linkedin_invites_last_n_days,
    find_pending_touches,
    split_frontmatter,
    tick_outcome_checkbox,
    update_frontmatter,
)


LINKEDIN_WEEKLY_SOFT_LIMIT = LINKEDIN_WEEKLY_INVITE_LIMIT
INTENT_HEADER = "X-Outreach-Intent-Id"
INTENT_FOOTER_TEMPLATE = "\n\n​outreach-intent:{intent_id}​\n"
# LinkedIn intent-id marker — embedded in the connection note text per
# ADR-0015 D39. Mirrors the email INTENT_FOOTER_TEMPLATE shape (same
# zero-width-space surround for invisibility); ~30 chars of the 300-char
# LinkedIn connection-note limit. The note text is the ONLY round-trip
# surface mcp__linkedin__connect_with_person exposes; embedding the
# intent_id here is what reconcile Pass D (Pillar C Week 4) reads back
# via mcp__linkedin__get_sent_invitations or equivalent.
LI_INVITE_INTENT_MARKER_TEMPLATE = "\n​outreach-intent:{intent_id}​"
# LinkedIn personal-account connection-note hard limit. The dispatcher
# refuses-loud when a draft note + the intent-id marker would push the
# total over this — silent send failure at the boundary is the failure
# mode the Week 2 per-week review's P2-1 flagged.
LINKEDIN_INVITE_NOTE_MAX_CHARS = 300
# LinkedIn DM intent-id marker — embedded in the DM body per ADR-0016
# D43 (event-type prefix `li_dm_*`). Same zero-width-space shape as
# the invite marker; DM bodies have an 8000-char limit (vs the 300-
# char invite-note limit), so the ~30-char marker eats <1% of the
# budget. The marker text is invisible to the recipient in LinkedIn's
# UI; reconcile Pass E (Pillar C Week 4) reads it back via the
# LinkedIn MCP's conversation-history surface.
LI_DM_INTENT_MARKER_TEMPLATE = "\n​outreach-intent:{intent_id}​"
# LinkedIn DM hard limit per the platform (8000 chars). Mirrors the
# invite-note refuse-loud posture though headroom is wide; pinning
# the limit forecloses surprise overflow if an operator pastes a long
# document body into a DM register's body field.
LINKEDIN_DM_BODY_MAX_CHARS = 8000
# Twitter DM intent-id marker — embedded in the DM body per ADR-0018
# D58 (event-type prefix `tw_dm_*`). Same zero-width-space shape as
# the LinkedIn invite + DM markers (ADR-0015 D39 + ADR-0016 D43); DM
# bodies have a 10000-char limit (vs LinkedIn DM's 8000) so the
# ~30-char marker eats <0.5% of the budget. The marker text is
# invisible to the recipient in Twitter's UI; reconcile Pass F
# (Pillar C Week 5) reads it back via the cookie-scrape MCP's
# recent-DMs surface.
TW_DM_INTENT_MARKER_TEMPLATE = "\n​outreach-intent:{intent_id}​"
# Twitter DM hard limit per the platform (10000 chars; Twitter Premium
# accounts get even more room — the framework pins the conservative
# default). Refuse-loud at the boundary forecloses surprise overflow
# the same way the LinkedIn-invite + DM gates do (per ADR-0015 D39
# / ADR-0016 D43 + the Week 2 per-week review P2-1 rationale).
TWITTER_DM_BODY_MAX_CHARS = 10000

# Pillar C Week 6 (ADR-0019 D65) — Calendar booking intent-id marker.
# DISTINCT shape from Weeks 2-5's zero-width-Unicode markers: Cal.com
# URLs are structured artifacts with their own query-param semantics, so
# the marker lives as a ``?intent_id=<value>`` query param on the
# booking URL. Cal.com's webhook payload preserves the originating URL
# (custom inputs / responses block per their schema versions), so the
# orchestrator-side correlation is "extract intent_id from the booking
# URL's query string" — same one-line shape as the LinkedIn / Twitter
# regex-extraction, different transport. The dispatcher mints
# ``cb_<ULID>`` IDs via ``new_intent_id(prefix="cb_")`` so the URL is
# self-evidently a calendar booking link (operators scanning their
# outbound email/DM bodies see the cb_ prefix + know the artifact's
# semantic class without parsing the rest of the URL).
CALENDAR_BOOKING_INTENT_ID_PREFIX = "cb_"
# Cal.com booking URL templates a base operator-configurable URL.
# Operators set either a per-Person ``calendar_booking_url_base:``
# (PersonInfo field) or rely on the dispatcher's ``cal_com_base_url``
# kwarg (operator-default). The URL ceiling is the conservative
# RFC-3986 web-form maximum (~2048 chars); the dispatcher refuses-loud
# when base URL + ``?intent_id=cb_<ULID>`` query param exceed.
CALENDAR_BOOKING_URL_MAX_CHARS = 2048

RECONCILE_FRESH_MAX_AGE = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Preview (unchanged from Phase 4 — printing/grouping only)
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _classify(d: TouchDraft) -> str:
    email_p = _email_pending(d)
    li_p = _linkedin_pending(d)
    if email_p and li_p:
        return "ready_email_li"
    if email_p and not li_p:
        return "ready_email"
    if li_p and not email_p:
        if d.frontmatter.get("sent") is True:
            return "ready_li_email_done"
        return "ready_li"
    if d.has_email_block and not (d.person and d.person.email):
        return "skip_no_email"
    return "skip_no_channel"


def _print_preview(drafts: list[TouchDraft]) -> dict:
    buckets: dict[str, list[TouchDraft]] = {}
    for d in drafts:
        buckets.setdefault(_classify(d), []).append(d)

    n_email_ready = len(buckets.get("ready_email", [])) + len(buckets.get("ready_email_li", []))
    n_li_new = len(buckets.get("ready_email_li", [])) + len(buckets.get("ready_li", []))
    n_li_followup = len(buckets.get("ready_li_email_done", []))
    n_li_total = n_li_new + n_li_followup

    li_count, _ = count_linkedin_invites_last_n_days(7)
    li_budget = LINKEDIN_WEEKLY_SOFT_LIMIT - li_count

    print(f"\n=== PENDING COLD TOUCHES ({len(drafts)} total) ===\n")
    print(f"LinkedIn invite tally (last 7 days): {li_count} / {LINKEDIN_WEEKLY_SOFT_LIMIT} soft limit  →  budget remaining: {li_budget}")
    if n_li_total > li_budget:
        print(f"  ⚠ Planned LinkedIn invites ({n_li_total}) would EXCEED weekly budget by {n_li_total - li_budget}")
    print()

    if n_email_ready:
        print(f"--- EMAILS READY ({n_email_ready}) ---")
        i = 1
        n_catch_all = 0
        for cls in ("ready_email_li", "ready_email"):
            for d in buckets.get(cls, []):
                tag = "E+L" if cls == "ready_email_li" else "E"
                risk = ""
                if d.person and d.person.email_risk == "catch_all":
                    risk = " ⚠ catch_all"
                    n_catch_all += 1
                print(
                    f"  {i:>2}. [{tag:>3}] "
                    f"{_truncate(d.person_name, 26):<26}  "
                    f"{_truncate(d.person.email, 30):<30}  "
                    f"{_truncate(d.email_subject or '', 42)}{risk}"
                )
                i += 1
        if n_catch_all:
            print(
                f"  ⚠ {n_catch_all} recipient(s) flagged catch_all by Reoon — bounce risk; "
                f"tier S/A allow-with-warning, tier B should be re-routed."
            )
        print()

    if buckets.get("ready_li_email_done"):
        print(f"--- LINKEDIN INVITES PENDING (email already sent) — {len(buckets['ready_li_email_done'])} ---")
        for d in buckets["ready_li_email_done"]:
            sent_at = d.frontmatter.get("sent_at", "?")
            print(f"   • {_truncate(d.person_name, 26):<26}  email sent {sent_at}   {d.person.linkedin}")
        print()

    if buckets.get("ready_li"):
        print(f"--- LINKEDIN-ONLY READY ({len(buckets['ready_li'])}) ---")
        for d in buckets["ready_li"]:
            print(f"   • {_truncate(d.person_name, 30):<30}  {d.person.linkedin}")
        print()

    skip_no_email = buckets.get("skip_no_email", [])
    if skip_no_email:
        print(f"--- SKIPPED: no email recipient ({len(skip_no_email)}) ---")
        for d in skip_no_email:
            note = "but has LinkedIn" if d.has_linkedin_block else "no channel"
            print(f"   • {_truncate(d.person_name, 30):<30}  {note}")
        print()

    if buckets.get("skip_no_channel"):
        print(f"--- SKIPPED: unparseable ({len(buckets['skip_no_channel'])}) ---")
        for d in buckets["skip_no_channel"]:
            print(f"   • {_truncate(d.person_name, 30):<30}  issues: {d.issues}")
        print()

    return {
        "email_ready": n_email_ready,
        "linkedin_ready": n_li_total,
        "linkedin_new": n_li_new,
        "linkedin_followup": n_li_followup,
        "linkedin_budget": li_budget,
        "skipped": len(skip_no_email) + len(buckets.get("skip_no_channel", [])),
    }


# ---------------------------------------------------------------------------
# Vault writeback (denormalized view of ledger state)
# ---------------------------------------------------------------------------


def _vault_writeback(draft: TouchDraft, gmail_message_id: str | None = None) -> str | None:
    """Apply the Phase-4 vault writes (touch.sent / Person.status / file move).

    Returns an error message if writeback partially failed, None on success.
    Ledger remains authoritative; vault is denormalized state.
    """
    today = date.today().isoformat()
    try:
        touch_updates: dict = {"sent": True, "sent_at": today}
        if gmail_message_id:
            touch_updates["gmail_message_id"] = gmail_message_id
        update_frontmatter(draft.note_path, touch_updates)
        tick_outcome_checkbox(draft.note_path, "Email sent")
    except Exception as e:
        return f"touch writeback failed: {e}"

    try:
        person_fm_updates: dict[str, Any] = {"last_touch": today}
        text = draft.person.note_path.read_text()
        fm, _ = split_frontmatter(text)
        flipped_to_contacted = False
        if fm.get("status") == "queued":
            person_fm_updates["status"] = "contacted"
            flipped_to_contacted = True
        if not fm.get("first_touch"):
            person_fm_updates["first_touch"] = today
        update_frontmatter(draft.person.note_path, person_fm_updates)

        if flipped_to_contacted:
            current_path = draft.person.note_path
            if "🟦 Queue" in str(current_path):
                new_path = Path(str(current_path).replace("🟦 Queue", "🟧 Active"))
                if not new_path.exists():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    current_path.rename(new_path)
                    draft.person.note_path = new_path
    except Exception as e:
        return f"person writeback failed: {e}"
    return None


# ---------------------------------------------------------------------------
# Gated two-phase send (the load-bearing function)
# ---------------------------------------------------------------------------


def _ledger_handle() -> _ledger.Ledger:
    import os
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    ldir = Path(os.path.expanduser(env)).resolve() if env else _ledger.DEFAULT_LEDGER_DIR
    return _ledger.Ledger(ldir)


def _build_security_cfg() -> Optional["_security.SecurityConfig"]:
    """Construct the J7 SecurityConfig from the operator's config, or None.

    The CAN-SPAM footer + one-click List-Unsubscribe headers are stamped onto
    every outbound email when this returns a SecurityConfig (per ADR-0079 D394).

    Returns None when the config has no ``security:`` block at all (the Aiyara
    default config) so the legacy footer-less path is preserved untouched. When
    the block IS present, SecurityConfig's ``__post_init__`` refuses-loud on an
    empty physical address / malformed URL, so a half-configured section fails
    fast at construction rather than silently shipping a non-compliant email.

    A clearly-marked placeholder address (``REPLACE_ME...``) is allowed through
    here so plumbing + self-tests work, but it is NOT legally compliant; the
    caller warns loudly when it detects the placeholder so a real stranger send
    can't go out unnoticed with a fake address.
    """
    if not SECURITY_PHYSICAL_MAILING_ADDRESS and not SECURITY_UNSUBSCRIBE_BASE_URL:
        return None
    return _security.SecurityConfig(
        physical_mailing_address=SECURITY_PHYSICAL_MAILING_ADDRESS or "",
        unsubscribe_base_url=SECURITY_UNSUBSCRIBE_BASE_URL or "",
        unsubscribe_mailto=SECURITY_UNSUBSCRIBE_MAILTO,
    )


def _unsub_token_for(person_id: str) -> str:
    """The opaque per-recipient suppression token.

    sha256(person_id)[:16], byte-identical to the token the J7 footer +
    List-Unsubscribe URL stamp (see _gated_send_one_inner). The ScholarFeed
    suppressions table is keyed on this token, so both ends agree without ever
    exchanging the cleartext person_id (I8 privacy invariant).
    """
    return hashlib.sha256(person_id.encode("utf-8")).hexdigest()[:16]


def _resolve_suppression_secret() -> str | None:
    """Resolve the suppression-API secret (sent as the X-Admin-Secret header).

    Generic resolution with no tenant-specific naming in core: the env var
    named in `security.suppression_check_secret_env` wins, else the file at
    `security.suppression_check_secret_path`. Both go through
    env_loader.get_secret (which also loads ~/.outreach-factory/.env)."""
    import env_loader
    return env_loader.get_secret(
        SECURITY_SUPPRESSION_CHECK_SECRET_ENV,
        file_path=SECURITY_SUPPRESSION_CHECK_SECRET_PATH,
    )


def _suppression_checker() -> Optional[Callable[[str], tuple[bool, str | None]]]:
    """Build a per-recipient suppression check, or None if not configured.

    When ``security.suppression_check_url`` is set, returns a callable taking a
    person_id and returning ``(blocked, detail)``:

      * ``(False, None)``       : not suppressed; OK to send.
      * ``(True, None)``        : recipient unsubscribed; DO NOT send.
      * ``(True, "<error>")``   : the suppression API could not be consulted;
        FAIL-CLOSED (block) because mailing a possible opt-out is the costlier
        error (asymmetric-failure-cost; mirrors the policy_engine_error refusal
        posture). The block is per-recipient, so a transient API outage marks
        those recipients blocked for this run rather than crashing the batch;
        re-run once the API is healthy.

    URL unset -> None -> main() runs without a suppression gate (the pre-deploy
    state). Uses urllib (no extra dependency), matching provision_trial_key.py.
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = SECURITY_SUPPRESSION_CHECK_URL
    if not url:
        return None
    base = url.rstrip("/")
    secret = _resolve_suppression_secret()

    def _check(person_id: str) -> tuple[bool, str | None]:
        token = _unsub_token_for(person_id)
        req = urllib.request.Request(
            f"{base}/{token}",
            headers={"X-Admin-Secret": secret or ""},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return (bool(data.get("suppressed")), None)
        except urllib.error.HTTPError as exc:
            return (True, f"suppression API HTTP {exc.code}")
        except Exception as exc:  # network / timeout / parse, fail closed
            return (True, f"suppression API error: {type(exc).__name__}: {exc}")

    return _check


def _policies_dir() -> Path:
    """Where to find policy YAML files.

    Override with ``OUTREACH_FACTORY_POLICIES_DIR`` (tests use this);
    default is ``~/.outreach-factory/policies/``.
    """
    import os
    env = os.environ.get("OUTREACH_FACTORY_POLICIES_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return Path.home() / ".outreach-factory" / "policies"


def _load_cooldown_rules() -> list:
    """Load cooldown rules from ``<policies_dir>/cooldowns.yml``.

    Missing file → empty list → ``policy.evaluate`` returns ``Allow()``
    on every call (per ADR-0001: greenfield install must not block).
    Doctor preflight (Phase 5 / Pillar I) is responsible for warning
    when the file is absent on a system with ledger history.

    No caching at this stage: dispatcher runs are short and the load
    cost is negligible. The Pillar H daemon will switch to mtime-cached
    loading + SIGHUP-driven live reload.
    """
    return _policy.load_rules_from_yaml(_policies_dir() / "cooldowns.yml")


def _build_rule_context(
    draft: TouchDraft, *,
    person_id: str,
    register: str,
    led: _ledger.Ledger,
    keys: identity.IdentityKeys,
    run_id: str | None = None,
) -> _policy.RuleContext:
    """Construct a ``RuleContext`` for the policy engine.

    Fields wired:
      person_id     ← from identity.read_person_keys (caller)
      channel       ← "email" (this is the email send path)
      register      ← caller-supplied (defaults to "cold-pitch")
      email         ← draft.person.email
      email_domain  ← lowercased portion after "@" (None if no email)
      now           ← datetime.now(UTC)
      timezone      ← tz_inference.infer_timezone(keys.country)
                       (ADR-0005; recipient-country signal lives on
                       Person.identity_keys.country with fallback to
                       Person.location, both parsed in
                       identity.read_person_keys). When inference fails
                       the helper returns the documented default
                       (America/Los_Angeles per ADR-0002 §5 resolution).
      person_status ← draft.person.status (from Person frontmatter)
      run_id        ← caller-supplied dispatcher run id (ADR-0006;
                       consumed by BudgetPerRunCapRule)
      tier          ← draft.person.research_tier (ADR-0007; consumed by
                       TierRequiresTierInRule + cross-cutting
                       block_when: {tier|tier_in} filters). v1 hardcodes
                       the source to `Person.research_tier`; a future
                       `policy.tier_field` config knob lets operators
                       point at a different frontmatter field. ``None``
                       is preserved — the tier rule treats it as
                       restrictive (BLOCK), the block_when filters
                       treat it as "filter does not match."
      ledger        ← the supplied Ledger instance (LedgerLike-compatible)
    """
    email = draft.person.email if draft.person else None
    email_domain: str | None = None
    if email and "@" in email:
        email_domain = email.split("@", 1)[1].lower()
    person_status = draft.person.status if draft.person else None
    tier = draft.person.research_tier if draft.person else None
    recipient_tz = _policy.tz_inference.infer_timezone(keys.country)
    return _policy.RuleContext(
        person_id=person_id,
        channel="email",
        register=register,
        email=email,
        email_domain=email_domain,
        now=datetime.now(timezone.utc),
        timezone=recipient_tz,
        ledger=led,
        person_status=person_status,
        run_id=run_id,
        tier=tier,
    )


def gated_send_one(
    draft: TouchDraft,
    *,
    gmail_client,
    led: _ledger.Ledger,
    sender_name: str = "",
    register: str = "cold-pitch",
    run_id: str | None = None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]] = None,
    release_lock: Optional[Callable[[str], None]] = None,
    writeback: Optional[Callable[[TouchDraft, str | None], str | None]] = _vault_writeback,
    security_cfg: Optional["_security.SecurityConfig"] = None,
) -> dict:
    """One draft through gate → two-phase send → writeback.

    Pure-ish: every external dependency is parameterized. Tests pass a fake
    gmail_client + an in-memory Ledger + dummy lock callables and assert on
    the returned outcome dict + the ledger contents.

    Returns a dict shaped like:
        {"ok": True/False, "reason": "<keyword>", "person_id": "...",
         "intent_id": "..." | None, "gmail_message_id": "..." | None,
         "detail": "...", "writeback_warning": "..." | None}
    """
    # Per ADR-0055 D303 — wrap the body in a send-stage span so the
    # per-channel dispatcher's two-phase commit timing is operator-
    # visible via the OTel tracing backend. The channel attribute
    # carries the channel-on-every-event invariant per ADR-0014 D33;
    # person_id is stamped via set_attribute once known (post-
    # identity.read_person_keys parse).
    with traced_stage(
        "send", "email",
        attributes={"channel": "email", "register": register},
    ) as _span:
        return _gated_send_one_inner(
            draft, gmail_client=gmail_client, led=led,
            sender_name=sender_name, register=register, run_id=run_id,
            acquire_lock=acquire_lock, release_lock=release_lock,
            writeback=writeback, security_cfg=security_cfg, _span=_span,
        )


def _gated_send_one_inner(
    draft: TouchDraft,
    *,
    gmail_client,
    led: _ledger.Ledger,
    sender_name: str,
    register: str,
    run_id: str | None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]],
    release_lock: Optional[Callable[[str], None]],
    writeback: Optional[Callable[[TouchDraft, str | None], str | None]],
    security_cfg: Optional["_security.SecurityConfig"],
    _span,
) -> dict:
    """Internal body of :func:`gated_send_one` — wrapped by the
    public function with a ``traced_stage`` context per ADR-0055
    D303. Splitting the body keeps the span wrapping cleanly
    delimited."""
    person_path = draft.person.note_path if draft.person else None
    if person_path is None:
        return _blocked(led, draft, person_id=None, reason="no_person_note")
    parsed = identity.read_person_keys(person_path)
    if parsed is None:
        return _blocked(led, draft, person_id=None, reason="not_a_person_note")
    person_id, keys = parsed
    # Stamp person_id on the span once known (per ADR-0055 D303 +
    # ADR-0054 D297; person_id is in _SPAN_ATTRIBUTES_ALLOWED).
    if person_id:
        try:
            _span.set_attribute("person_id", person_id)
        except Exception:
            pass
    if person_id is None or identity.id_is_temporary(person_id):
        return _blocked(led, draft, person_id=person_id, reason="identity_incomplete")

    prior = led.last_send_for(person_id, channel="email")
    if prior is not None:
        return _blocked(
            led, draft, person_id=person_id, reason="already_sent",
            detail=f"prior intent={prior.intent_id} at {prior.ts}",
        )

    # Policy gate (Pillar A Week 1 — replaces the Phase 5.5 Week 4 hook).
    # Loads cooldown rules from ~/.outreach-factory/policies/cooldowns.yml
    # (missing file → empty rules → Allow; greenfield safe by ADR-0001).
    # First Block wins; we emit a `policy_blocked` ledger event carrying
    # the firing rule name + reason + structured detail.
    try:
        cooldown_rules = _load_cooldown_rules()
        policy_ctx = _build_rule_context(
            draft, person_id=person_id, register=register, led=led,
            keys=keys, run_id=run_id,
        )
        policy_verdict = _policy.evaluate(cooldown_rules, policy_ctx)
    except Exception as exc:
        # Per ADR-0001 the engine does NOT swallow rule exceptions —
        # they propagate to here. We treat a policy outage as a refusal
        # (refuse-log-ask principle): emit a structured event, halt
        # this draft. Run-level escalation is the caller's job.
        print(f"WARNING: policy.evaluate raised for "
              f"{person_id} register={register}: {exc}", file=sys.stderr)
        return _blocked(
            led, draft, person_id=person_id,
            reason="policy_engine_error",
            detail=f"{type(exc).__name__}: {exc}",
            event_type="policy_blocked",
        )
    if isinstance(policy_verdict, _policy.Block):
        return _blocked(
            led, draft, person_id=person_id,
            reason=policy_verdict.rule,
            detail=policy_verdict.reason,
            event_type="policy_blocked",
            block_detail=policy_verdict.detail,
        )

    lock_held = False
    if acquire_lock is not None:
        ok, msg = acquire_lock(draft.person_name)
        if not ok:
            return _blocked(
                led, draft, person_id=person_id, reason="locked", detail=msg,
            )
        lock_held = True

    try:
        intent_id = _ledger.new_intent_id()
        subject_hash = hashlib.sha256(
            (draft.email_subject or "").encode("utf-8"),
        ).hexdigest()
        led.append({
            "type": "send_intent",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "email",
            "email": draft.person.email,
            "subject_hash": f"sha256:{subject_hash}",
            "register": register,
        })

        footer = INTENT_FOOTER_TEMPLATE.format(intent_id=intent_id)
        extra_headers = {INTENT_HEADER: intent_id}
        # J7 (ADR-0079 D394) — the every-send invariant: stamp the CAN-SPAM
        # physical-address footer + the RFC-8058 one-click List-Unsubscribe
        # headers onto every outbound email, merged into the existing intent
        # body_footer + extra_headers seams. The operator's SecurityConfig
        # supplies the address + base URL (refuse-loud at construction if the
        # address is empty); the per-recipient token is an opaque person hash
        # so the unsubscribe URL carries no cleartext person_id (I8).
        if security_cfg is not None:
            _unsub_token = hashlib.sha256(person_id.encode("utf-8")).hexdigest()[:16]
            _unsub_url = f"{security_cfg.unsubscribe_base_url}?u={_unsub_token}"
            footer += _security.build_canspam_footer(
                physical_mailing_address=security_cfg.physical_mailing_address,
                unsubscribe_url=_unsub_url,
            )
            extra_headers.update(_security.build_list_unsubscribe_headers(
                unsubscribe_url=_unsub_url,
                mailto=security_cfg.unsubscribe_mailto,
            ))
        # Per ADR-0055 D305 + ADR-0053 D289 — record the per-channel
        # external-API elapsed time into outreach_factory_send_
        # latency_seconds histogram for the Pillar G send-latency p99
        # SLO dashboard. Best-effort: histogram emit failure MUST NOT
        # break the dispatch (mirrors cost_incurred's try/except-
        # best-effort posture below).
        _send_start = time.monotonic()
        try:
            msg_id, thread_id = gmail_client.send_email(
                to=draft.person.email,
                subject=draft.email_subject,
                body=draft.email_body,
                from_name=sender_name or None,
                extra_headers=extra_headers,
                body_footer=footer,
            )
        except Exception as exc:
            led.append({
                "type": "send_failed",
                "intent_id": intent_id,
                "person_id": person_id,
                "channel": "email",
                "error_class": type(exc).__name__,
                "error_message": str(exc),
            })
            return {
                "ok": False,
                "reason": "send_failed",
                "person_id": person_id,
                "intent_id": intent_id,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        finally:
            try:
                get_send_latency_histogram().record(
                    time.monotonic() - _send_start,
                    {"channel": "email"},
                )
            except Exception:
                pass

        led.append({
            "type": "send_confirmed",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "email",
            "gmail_message_id": msg_id,
            "gmail_thread_id": thread_id,
            "email": draft.person.email,
        })

        # I7 cost-event emission (ADR-0006): Gmail is quota-only; the
        # binding cost is the per-day send quota, not USD. We emit
        # ``amount_usd: 0.0`` and ``units: 1`` so per-day window-cap
        # rules can scope on units (e.g. budget.window-cap on
        # source=gmail, max_units=400 to stay under Gmail's daily
        # limit). Emit at the success path only — a send_failed does
        # not consume the quota in a recoverable way and is already
        # observable via the send_failed event itself.
        try:
            led.append({
                "type": "cost_incurred",
                "source": "gmail",
                "amount_usd": 0.0,
                "units": 1,
                "model_or_endpoint": "messages.send",
                "person_id": person_id,
                "run_id": run_id,
                "intent_id": intent_id,
            })
        except Exception as exc:
            # The send itself succeeded — failing to record the cost
            # event must not roll the send back. Log + continue; the
            # missing event slightly under-reports usage in the
            # budget rule, biasing toward Allow (the safer side of
            # the I7 cap is "spent a bit more than reported" rather
            # than "blocked the send").
            print(
                f"WARNING: cost_incurred append failed for gmail send "
                f"{intent_id}: {exc}", file=sys.stderr,
            )

        wb_warning: str | None = None
        if writeback is not None:
            try:
                wb_warning = writeback(draft, msg_id)
            except Exception as e:
                wb_warning = f"writeback raised: {e}"

        return {
            "ok": True,
            "reason": "sent",
            "person_id": person_id,
            "intent_id": intent_id,
            "gmail_message_id": msg_id,
            "gmail_thread_id": thread_id,
            "writeback_warning": wb_warning,
        }
    finally:
        if lock_held and release_lock is not None:
            try:
                release_lock(draft.person_name)
            except Exception as exc:
                print(f"WARNING: release_lock({draft.person_name!r}) "
                      f"failed: {exc}", file=sys.stderr)


def _blocked(
    led: _ledger.Ledger,
    draft: TouchDraft,
    *,
    person_id: str | None,
    reason: str,
    detail: str | None = None,
    event_type: str = "dedup_blocked",
    block_detail: dict | None = None,
    channel: str = "email",
    result_extras: dict | None = None,
) -> dict:
    """Emit a dedup_blocked / policy_blocked / cooldown_blocked event +
    return the gate outcome.

    All gate refusals go through this function so the audit trail is
    uniform — the funnel diagnostic groups by these reasons.

    For policy_blocked events, ``block_detail`` carries the structured
    dict from ``policy.Block.detail`` (rule-specific evidence such as
    blocking event ts, threshold breached, age at check). Stored under
    the event's ``policy_detail`` key so future readers / reconcile can
    audit *why* the rule fired without re-running it.

    The ``channel`` parameter (default ``"email"`` for the existing
    email dispatcher) lets the LinkedIn dispatcher reuse this function
    while emitting ``channel: "linkedin"`` per ADR-0014 D33. Future
    per-channel dispatchers (Twitter DM, calendar booking) thread their
    channel value through the same parameter.

    The ``result_extras`` parameter lets per-channel callers thread
    channel-specific keys into the returned dict so the blocked-path
    shape matches each channel's documented success-path shape (e.g.
    the email dispatcher's success shape has ``gmail_message_id``;
    the LinkedIn DM dispatcher's has ``linkedin_thread_id``; the
    LinkedIn invite dispatcher's has ``linkedin_invitation_id``).
    Pillar H + Pillar I CLI callers that destructure the returned
    dict by key see a consistent shape across success + blocked paths
    per channel. Per Week 3 per-week review P2-2.
    """
    event: dict = {
        "type": event_type,
        "person_id": person_id,
        "channel": channel,
        "reason": reason,
        "touch_note": str(draft.note_path),
        "person_name": draft.person_name,
    }
    if draft.person and draft.person.email:
        event["email"] = draft.person.email
    if detail:
        event["detail"] = detail
    if block_detail:
        event["policy_detail"] = block_detail
    try:
        led.append(event)
    except Exception as exc:
        print(f"WARNING: gate ledger-append failed for "
              f"{person_id} reason={reason}: {exc}", file=sys.stderr)
    out: dict = {
        "ok": False,
        "reason": reason,
        "person_id": person_id,
        "intent_id": None,
        "detail": detail,
    }
    if channel == "email":
        # Email dispatcher's documented success shape includes
        # gmail_message_id. Default behavior — backwards compatible
        # with pre-Week-3 callers (gated_send_one's success return
        # carries gmail_message_id + gmail_thread_id; the blocked
        # shape leaves the latter implicit-None per long-standing
        # caller convention).
        out["gmail_message_id"] = None
    if result_extras:
        out.update(result_extras)
    return out


# Channel + action → result-extras mapping for ``_blocked``. Keyed by
# the per-channel dispatcher's documented success-path keys; the
# blocked-path matches via explicit-None entries so callers
# destructuring the dict see one shape across success + refusal. Per
# Week 3 per-week review P2-2 — the leak surfaced when the LinkedIn
# DM dispatcher's blocked paths inherited the email shape (with
# gmail_message_id) instead of the documented linkedin_thread_id.
LI_INVITE_BLOCK_EXTRAS = {"linkedin_invitation_id": None}
LI_DM_BLOCK_EXTRAS = {"linkedin_thread_id": None}
# Twitter DM dispatcher's documented success-path key per ADR-0018
# D58 — the cookie-scrape MCP returns a per-conversation ``thread_id``
# on send; the dispatcher stamps it on the confirmed event for Pillar D
# reply-correlation (per ADR-0018 D64). Blocked paths leave the key as
# explicit-None so callers destructuring the dict see one shape across
# success + refusal — same Week 3 per-week review P2-2 discipline.
TW_DM_BLOCK_EXTRAS = {"twitter_thread_id": None}
# Calendar booking dispatcher's documented success-path keys per
# ADR-0019 D65 — the dispatcher returns the booking URL it synthesized
# (``cal.com/yourhandle/intro?intent_id=cb_<ULID>``) so operators can embed it
# directly in their outbound message; the Cal.com webhook later returns
# a ``booking_id`` that the webhook handler stamps on the
# ``calendar_booking_confirmed`` event. Blocked paths leave both as
# explicit-None.
CALENDAR_BOOKING_BLOCK_EXTRAS = {
    "calendar_booking_url": None,
    "calendar_booking_id": None,
}


# ---------------------------------------------------------------------------
# LinkedIn invite two-phase send (Pillar C Week 2 — ADR-0015)
# ---------------------------------------------------------------------------


def _build_linkedin_rule_context(
    draft: TouchDraft, *,
    person_id: str,
    register: str,
    led: _ledger.Ledger,
    keys: identity.IdentityKeys,
    run_id: str | None = None,
) -> _policy.RuleContext:
    """Construct a ``RuleContext`` for the LinkedIn invite policy gate.

    Mirrors :func:`_build_rule_context` but sets ``channel="linkedin"``
    so the cross-channel rule (ADR-0003) + LinkedIn-weekly-invite-cap
    rule (ADR-0008) evaluate against the LinkedIn channel. Every other
    field is identical to the email path — register, run_id, tier all
    carry through unchanged because they're channel-agnostic.

    The ``email`` / ``email_domain`` fields stay populated even on the
    LinkedIn path because some cross-channel rules
    (``cross-channel-email-suppresses-linkedin``) reference the
    operator's prior email touch by domain; the policy engine's
    ``block_when:`` filters resolve at evaluation time and silently
    skip when the field is irrelevant.
    """
    email = draft.person.email if draft.person else None
    email_domain: str | None = None
    if email and "@" in email:
        email_domain = email.split("@", 1)[1].lower()
    person_status = draft.person.status if draft.person else None
    tier = draft.person.research_tier if draft.person else None
    recipient_tz = _policy.tz_inference.infer_timezone(keys.country)
    return _policy.RuleContext(
        person_id=person_id,
        channel="linkedin",
        register=register,
        email=email,
        email_domain=email_domain,
        now=datetime.now(timezone.utc),
        timezone=recipient_tz,
        ledger=led,
        person_status=person_status,
        run_id=run_id,
        tier=tier,
    )


def _li_invite_vault_writeback(
    draft: TouchDraft,
    *,
    intent_id: str,
    confirmed_at: str | None = None,
) -> str | None:
    """Apply the LinkedIn invite vault writes (touch.sent / intent_id /
    confirmed_at / Person.status / file move).

    Returns an error message if writeback partially failed, ``None`` on
    success. Mirrors :func:`_vault_writeback` (the email path) modulo
    the LinkedIn-specific frontmatter fields:

    * ``sent: true`` + ``sent_at: <today>``
    * ``linkedin_state: invited`` + ``linkedin_invited_at: <today>``
    * ``li_invite_intent_id: <intent_id>`` (round-trippable; reconcile
      Pass D Week 4 uses this to correlate ledger intent with vault
      touch state)
    * ``li_invite_confirmed_at: <ISO>`` (only when confirmed_at is
      passed — the dispatcher calls this once with intent_id only on
      the intent-write step, then again with confirmed_at on success).

    Person.status flip (queued → contacted) + the 🟦 Queue → 🟧 Active
    file move are common with the email path — the writeback function
    forwards both for symmetry. Ledger remains authoritative; vault
    is the denormalized view.
    """
    today = date.today().isoformat()
    try:
        touch_updates: dict = {
            "sent": True,
            "sent_at": today,
            "linkedin_state": "invited",
            "linkedin_invited_at": today,
            "li_invite_intent_id": intent_id,
        }
        if confirmed_at is not None:
            touch_updates["li_invite_confirmed_at"] = confirmed_at
        update_frontmatter(draft.note_path, touch_updates)
        tick_outcome_checkbox(draft.note_path, "LinkedIn sent")
    except Exception as e:
        return f"touch writeback failed: {e}"

    try:
        person_fm_updates: dict[str, Any] = {"last_touch": today}
        text = draft.person.note_path.read_text()
        fm, _ = split_frontmatter(text)
        flipped_to_contacted = False
        if fm.get("status") == "queued":
            person_fm_updates["status"] = "contacted"
            flipped_to_contacted = True
        if not fm.get("first_touch"):
            person_fm_updates["first_touch"] = today
        update_frontmatter(draft.person.note_path, person_fm_updates)

        if flipped_to_contacted:
            current_path = draft.person.note_path
            if "🟦 Queue" in str(current_path):
                new_path = Path(
                    str(current_path).replace("🟦 Queue", "🟧 Active"),
                )
                if not new_path.exists():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    current_path.rename(new_path)
                    draft.person.note_path = new_path
    except Exception as e:
        return f"person writeback failed: {e}"
    return None


def gated_li_invite_one(
    draft: TouchDraft,
    *,
    linkedin_client,
    led: _ledger.Ledger,
    register: str = "cold-pitch",
    run_id: str | None = None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]] = None,
    release_lock: Optional[Callable[[str], None]] = None,
    writeback: Optional[Callable[..., str | None]] = _li_invite_vault_writeback,
) -> dict:
    """One LinkedIn invite through gate → two-phase send → writeback.
    """
    # Per ADR-0055 D303 — wrap the body in a send-stage span (li_
    # invite operation) for per-channel two-phase commit visibility
    # in the OTel tracing backend.
    with traced_stage(
        "send", "li_invite",
        attributes={"channel": "linkedin", "register": register},
    ) as _span:
        return _gated_li_invite_one_inner(
            draft, linkedin_client=linkedin_client, led=led,
            register=register, run_id=run_id,
            acquire_lock=acquire_lock, release_lock=release_lock,
            writeback=writeback, _span=_span,
        )


def _gated_li_invite_one_inner(
    draft: TouchDraft,
    *,
    linkedin_client,
    led: _ledger.Ledger,
    register: str,
    run_id: str | None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]],
    release_lock: Optional[Callable[[str], None]],
    writeback: Optional[Callable[..., str | None]],
    _span,
) -> dict:
    """Internal body of :func:`gated_li_invite_one`.

    The Pillar C Week 2 LinkedIn invite dispatcher (per ADR-0015).
    Mirrors :func:`gated_send_one` (the email shape) modulo:

    * LinkedIn API call is ``linkedin_client.connect_with_person(...)``
      not ``gmail_client.send_email(...)``.
    * Event types are ``li_invite_intent`` / ``li_invite_confirmed`` /
      ``li_invite_failed`` per ADR-0014 D33.
    * ``channel="linkedin"`` on every two-phase event per D33.
    * ``cost_incurred`` event carries ``source="linkedin_invite"``
      matching the budget.window-cap rule in cooldowns.example.yml
      (per ADR-0008 — the rule activates the moment this dispatcher
      starts emitting cost_incurred events).
    * Vault writeback stamps ``linkedin_state: invited``,
      ``linkedin_invited_at:``, ``li_invite_intent_id:``,
      ``li_invite_confirmed_at:`` per ADR-0015.

    Intent-id correlation through the MCP call (ADR-0015 D39):
    embedded as a zero-width-Unicode marker in the connection note
    text (same shape as email's ``INTENT_FOOTER_TEMPLATE`` body
    footer). Reconcile Pass D (Week 4) reads it back via the LinkedIn
    MCP's sent-invitations surface to recover crashes between intent
    and confirmed writes.

    Returns a dict shaped like:
        {"ok": True/False, "reason": "<keyword>", "person_id": "...",
         "intent_id": "..." | None, "linkedin_invitation_id": "..." | None,
         "detail": "...", "writeback_warning": "..." | None}
    """
    person_path = draft.person.note_path if draft.person else None
    if person_path is None:
        return _blocked(
            led, draft, person_id=None,
            reason="no_person_note", channel="linkedin",
            result_extras=LI_INVITE_BLOCK_EXTRAS,
        )
    parsed = identity.read_person_keys(person_path)
    if parsed is None:
        return _blocked(
            led, draft, person_id=None,
            reason="not_a_person_note", channel="linkedin",
            result_extras=LI_INVITE_BLOCK_EXTRAS,
        )
    person_id, keys = parsed
    # Stamp person_id on the span once known (per ADR-0055 D303).
    if person_id:
        try:
            _span.set_attribute("person_id", person_id)
        except Exception:
            pass
    if person_id is None or identity.id_is_temporary(person_id):
        return _blocked(
            led, draft, person_id=person_id,
            reason="identity_incomplete", channel="linkedin",
            result_extras=LI_INVITE_BLOCK_EXTRAS,
        )
    if not draft.person or not draft.person.linkedin:
        return _blocked(
            led, draft, person_id=person_id,
            reason="no_linkedin_url", channel="linkedin",
            detail="person record has no linkedin: field",
            result_extras=LI_INVITE_BLOCK_EXTRAS,
        )

    # Ledger-prior-send dedup (uses the generalized last_send_for from
    # ADR-0014 D33 — the indexer now recognizes li_invite_confirmed as
    # a confirmed-outcome type matching channel=linkedin).
    prior = led.last_send_for(person_id, channel="linkedin")
    if prior is not None:
        return _blocked(
            led, draft, person_id=person_id, reason="already_sent",
            channel="linkedin",
            detail=f"prior intent={prior.intent_id} at {prior.ts}",
            result_extras=LI_INVITE_BLOCK_EXTRAS,
        )

    # Policy gate — cross-channel rule + budget.window-cap fire here.
    # The LinkedIn-weekly-invite-cap rule (ADR-0008) activates once
    # this dispatcher emits its first cost_incurred event with
    # source=linkedin_invite, since the rule was factory-shipped
    # commented in cooldowns.example.yml waiting for the dispatcher.
    try:
        cooldown_rules = _load_cooldown_rules()
        policy_ctx = _build_linkedin_rule_context(
            draft, person_id=person_id, register=register, led=led,
            keys=keys, run_id=run_id,
        )
        policy_verdict = _policy.evaluate(cooldown_rules, policy_ctx)
    except Exception as exc:
        print(f"WARNING: policy.evaluate raised for LinkedIn "
              f"{person_id} register={register}: {exc}", file=sys.stderr)
        return _blocked(
            led, draft, person_id=person_id,
            reason="policy_engine_error",
            detail=f"{type(exc).__name__}: {exc}",
            event_type="policy_blocked",
            channel="linkedin",
            result_extras=LI_INVITE_BLOCK_EXTRAS,
        )
    if isinstance(policy_verdict, _policy.Block):
        return _blocked(
            led, draft, person_id=person_id,
            reason=policy_verdict.rule,
            detail=policy_verdict.reason,
            event_type="policy_blocked",
            block_detail=policy_verdict.detail,
            channel="linkedin",
            result_extras=LI_INVITE_BLOCK_EXTRAS,
        )

    lock_held = False
    if acquire_lock is not None:
        ok, msg = acquire_lock(draft.person_name)
        if not ok:
            return _blocked(
                led, draft, person_id=person_id,
                reason="locked", detail=msg, channel="linkedin",
                result_extras=LI_INVITE_BLOCK_EXTRAS,
            )
        lock_held = True

    try:
        intent_id = _ledger.new_intent_id()

        # Compose the connection note text with the intent-id marker
        # PRE-FLIGHT (before writing intent to the ledger). If the
        # combined length would exceed LinkedIn's 300-char hard limit,
        # the MCP call would fail with an opaque error and a stale
        # li_invite_intent would be stranded in the ledger — silent
        # data loss from the operator's perspective. Refuse-loud
        # instead. Per Week 2 per-week review P2-1.
        note_text = (draft.linkedin_dm or "").strip()
        marker = LI_INVITE_INTENT_MARKER_TEMPLATE.format(intent_id=intent_id)
        note_with_marker = (note_text + marker) if note_text else marker.lstrip("\n")
        if len(note_with_marker) > LINKEDIN_INVITE_NOTE_MAX_CHARS:
            # Lock + intent_id are local-only at this point — no ledger
            # mutation has happened yet, so a refusal here is clean.
            # Release the lock + emit a dedup_blocked-shape event so
            # operator funnel diagnostics catch it.
            return _blocked(
                led, draft, person_id=person_id,
                reason="note_too_long",
                detail=(
                    f"connection note ({len(note_text)} chars) + "
                    f"intent-id marker ({len(marker)} chars) = "
                    f"{len(note_with_marker)} chars, exceeds the "
                    f"LinkedIn {LINKEDIN_INVITE_NOTE_MAX_CHARS}-char "
                    f"limit. ADR-0015 D39 recommends keeping notes "
                    f"≤270 chars to leave budget for the marker."
                ),
                channel="linkedin",
                result_extras=LI_INVITE_BLOCK_EXTRAS,
            )

        led.append({
            "type": "li_invite_intent",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "linkedin",
            "linkedin_url": draft.person.linkedin,
            "register": register,
        })

        # Per ADR-0055 D305 — record LinkedIn invite latency to the
        # per-channel send-latency Histogram.
        _send_start = time.monotonic()
        try:
            invitation_id = linkedin_client.connect_with_person(
                linkedin_url=draft.person.linkedin,
                note=note_with_marker,
                intent_id=intent_id,
            )
        except Exception as exc:
            led.append({
                "type": "li_invite_failed",
                "intent_id": intent_id,
                "person_id": person_id,
                "channel": "linkedin",
                "error_class": type(exc).__name__,
                "error_message": str(exc),
            })
            return {
                "ok": False,
                "reason": "send_failed",
                "person_id": person_id,
                "intent_id": intent_id,
                "linkedin_invitation_id": None,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        finally:
            try:
                get_send_latency_histogram().record(
                    time.monotonic() - _send_start,
                    {"channel": "linkedin"},
                )
            except Exception:
                pass

        confirmed_event = {
            "type": "li_invite_confirmed",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "linkedin",
            "linkedin_url": draft.person.linkedin,
        }
        # ``invitation_id`` is optional — the MCP's response shape
        # varies; some implementations return an opaque invitation
        # id, others return only success/failure. Stamp the field when
        # present so reconcile Pass D can correlate without re-querying.
        if invitation_id:
            confirmed_event["linkedin_invitation_id"] = invitation_id
        confirm_ack = led.append(confirmed_event)
        confirmed_ts = confirm_ack.get("ts") if isinstance(confirm_ack, dict) else None

        # I7 cost-event emission (ADR-0006 + ADR-0008): activates the
        # linkedin-weekly-invite-cap rule the moment this dispatcher
        # starts shipping. amount_usd=0.0 because LinkedIn invites are
        # quota-only (100/wk personal-account terms); units=1 ticks
        # the per-week cap. Emit at the success path only — a
        # li_invite_failed does not consume the LinkedIn quota in a
        # recoverable way and is observable via the failed event itself.
        try:
            led.append({
                "type": "cost_incurred",
                "source": "linkedin_invite",
                "amount_usd": 0.0,
                "units": 1,
                "model_or_endpoint": "mcp__linkedin__connect_with_person",
                "person_id": person_id,
                "run_id": run_id,
                "intent_id": intent_id,
            })
        except Exception as exc:
            print(
                f"WARNING: cost_incurred append failed for LinkedIn "
                f"invite {intent_id}: {exc}", file=sys.stderr,
            )

        wb_warning: str | None = None
        if writeback is not None:
            try:
                wb_warning = writeback(
                    draft,
                    intent_id=intent_id,
                    confirmed_at=confirmed_ts,
                )
            except Exception as e:
                wb_warning = f"writeback raised: {e}"

        return {
            "ok": True,
            "reason": "sent",
            "person_id": person_id,
            "intent_id": intent_id,
            "linkedin_invitation_id": invitation_id,
            # Per Week 2 per-week review P2-2: the success return shape
            # documented in the docstring includes "detail". The email
            # path's gated_send_one omits it on success (the existing
            # contract is "detail" only populated on failure paths);
            # match that — keep the key for shape-uniform parsing but
            # leave the value None on success.
            "detail": None,
            "writeback_warning": wb_warning,
        }
    finally:
        if lock_held and release_lock is not None:
            try:
                release_lock(draft.person_name)
            except Exception as exc:
                print(f"WARNING: release_lock({draft.person_name!r}) "
                      f"failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# LinkedIn DM two-phase send (Pillar C Week 3 — ADR-0016)
# ---------------------------------------------------------------------------


def _read_person_linkedin_connected(person_path: Path) -> bool | None:
    """Read the ``linkedin_connected:`` field from a Person note.

    Returns:
      * ``True`` — explicit ``linkedin_connected: true``.
      * ``False`` — explicit ``linkedin_connected: false``.
      * ``None`` — field absent or unparseable. The dispatcher reads
        ``None`` as "unknown" and per ADR-0016 D44 refuses-loud
        (rather than proceeding with a send that may silently land in
        the recipient's message-request inbox).

    The reader is deliberately tolerant of YAML quirks: ``true`` /
    ``True`` / ``TRUE`` / string ``"true"`` all parse as ``True``;
    everything else with a non-``None`` value parses by Python truth
    semantics. The exact same parsing posture as the touch frontmatter
    update path (vault.update_frontmatter writes ``true`` / ``false``
    consistently).
    """
    try:
        text = person_path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, _ = split_frontmatter(text)
    val = fm.get("linkedin_connected")
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "yes", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
        return None
    return bool(val)


def _stamp_person_linkedin_connected(
    person_path: Path, *, connected: bool,
) -> str | None:
    """Stamp ``linkedin_connected: <bool>`` on a Person note.

    Per ADR-0016 D45 (lazy stamping convention) the helper exists as
    the **future** hook for the auto-stamping path Pillar I CLI's
    ``python -m orchestrator.linkedin mark-connected <person>``
    command will wrap (per ADR-0016 §"Downstream pillar impact").
    The Week 3 dispatcher itself does NOT call this function on first
    DM attempt — D44 + D45 ship the operator-manual flow (operator
    stamps the field after verifying via LinkedIn's UI; dispatcher
    reads but does not auto-write). The helper is defined here so
    Pillar I doesn't have to re-derive it + so a future
    week's operator-batch tooling can import + reuse without a
    refactor. Per Week 3 per-week review P3-2 — the documented
    intentional-unused state.

    Returns an error string on failure, ``None`` on success. The
    writeback uses ``update_frontmatter`` (the same primitive
    ``_li_invite_vault_writeback`` uses for ``linkedin_state:``) so
    the field appears in the operator-visible frontmatter block in
    standard ordering.
    """
    try:
        update_frontmatter(person_path, {"linkedin_connected": connected})
    except Exception as e:
        return f"linkedin_connected stamp failed: {e}"
    return None


def _li_dm_vault_writeback(
    draft: TouchDraft,
    *,
    intent_id: str,
    confirmed_at: str | None = None,
    thread_id: str | None = None,
) -> str | None:
    """Apply the LinkedIn DM vault writes (touch.sent / intent_id /
    confirmed_at / thread_id / Person.status / file move).

    Returns an error message if writeback partially failed, ``None``
    on success. Mirrors :func:`_li_invite_vault_writeback` modulo the
    DM-specific frontmatter fields:

    * ``sent: true`` + ``sent_at: <today>``
    * ``linkedin_state: messaged`` + ``linkedin_messaged_at: <today>``
    * ``li_dm_intent_id: <intent_id>`` (round-trippable; reconcile
      Pass E Week 4 uses this to correlate ledger intent with vault
      touch state)
    * ``li_dm_thread_id: <thread_id>`` (when the MCP returns one;
      Pillar D's reply-classifier reads this to correlate inbound
      LinkedIn replies to their originating DM thread).
    * ``li_dm_confirmed_at: <ISO>`` (only when ``confirmed_at`` is
      passed — the dispatcher writes it on the confirm path).

    Person.status flip (queued → contacted) + the 🟦 Queue → 🟧 Active
    file move are common with the invite + email paths — the
    writeback function forwards both for symmetry. Ledger remains
    authoritative; vault is the denormalized view.
    """
    today = date.today().isoformat()
    try:
        touch_updates: dict = {
            "sent": True,
            "sent_at": today,
            "linkedin_state": "messaged",
            "linkedin_messaged_at": today,
            "li_dm_intent_id": intent_id,
        }
        if thread_id:
            touch_updates["li_dm_thread_id"] = thread_id
        if confirmed_at is not None:
            touch_updates["li_dm_confirmed_at"] = confirmed_at
        update_frontmatter(draft.note_path, touch_updates)
        tick_outcome_checkbox(draft.note_path, "LinkedIn DM sent")
    except Exception as e:
        return f"touch writeback failed: {e}"

    try:
        person_fm_updates: dict[str, Any] = {"last_touch": today}
        text = draft.person.note_path.read_text()
        fm, _ = split_frontmatter(text)
        flipped_to_contacted = False
        if fm.get("status") == "queued":
            person_fm_updates["status"] = "contacted"
            flipped_to_contacted = True
        if not fm.get("first_touch"):
            person_fm_updates["first_touch"] = today
        update_frontmatter(draft.person.note_path, person_fm_updates)

        if flipped_to_contacted:
            current_path = draft.person.note_path
            if "🟦 Queue" in str(current_path):
                new_path = Path(
                    str(current_path).replace("🟦 Queue", "🟧 Active"),
                )
                if not new_path.exists():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    current_path.rename(new_path)
                    draft.person.note_path = new_path
    except Exception as e:
        return f"person writeback failed: {e}"
    return None


def gated_li_dm_one(
    draft: TouchDraft,
    *,
    linkedin_client,
    led: _ledger.Ledger,
    register: str = "cold-pitch",
    run_id: str | None = None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]] = None,
    release_lock: Optional[Callable[[str], None]] = None,
    writeback: Optional[Callable[..., str | None]] = _li_dm_vault_writeback,
    allow_unconnected: bool = False,
) -> dict:
    """One LinkedIn DM through gate → two-phase send → writeback.
    """
    # Per ADR-0055 D303 — wrap the body in a send-stage span (li_dm
    # operation) for per-channel two-phase commit visibility in the
    # OTel tracing backend.
    with traced_stage(
        "send", "li_dm",
        attributes={"channel": "linkedin", "register": register},
    ) as _span:
        return _gated_li_dm_one_inner(
            draft, linkedin_client=linkedin_client, led=led,
            register=register, run_id=run_id,
            acquire_lock=acquire_lock, release_lock=release_lock,
            writeback=writeback, allow_unconnected=allow_unconnected,
            _span=_span,
        )


def _gated_li_dm_one_inner(
    draft: TouchDraft,
    *,
    linkedin_client,
    led: _ledger.Ledger,
    register: str,
    run_id: str | None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]],
    release_lock: Optional[Callable[[str], None]],
    writeback: Optional[Callable[..., str | None]],
    allow_unconnected: bool,
    _span,
) -> dict:
    """Internal body of :func:`gated_li_dm_one`.

    The Pillar C Week 3 LinkedIn DM dispatcher (per ADR-0016).
    Mirrors :func:`gated_li_invite_one` modulo:

    * LinkedIn API call is ``linkedin_client.send_message(...)`` not
      ``connect_with_person(...)``.
    * Event types are ``li_dm_intent`` / ``li_dm_confirmed`` /
      ``li_dm_failed`` per ADR-0014 D33.
    * ``channel="linkedin"`` on every two-phase event per D33 (same
      channel value as invites — the cross-channel rule's
      consider_channels matches both event-type prefixes).
    * ``cost_incurred`` event carries ``source="linkedin_dm"`` per
      ADR-0015 D40's split-source convention (so operators can
      configure separate per-action caps for invites vs DMs).
    * **Pre-flight gate adds an "is the recipient an existing
      LinkedIn connection?" check.** Per ADR-0016 D44, DMs to
      non-connections silently land in the recipient's message-
      request inbox (LinkedIn's behavior), which the dispatcher
      cannot track. Refuse-loud on unknown connection state is the
      asymmetric-failure-cost-correct posture: better to refuse a
      send than to send-with-uncertainty into a message-request
      void. Operators who want to send to non-connections invoke
      with ``allow_unconnected=True`` (Pillar I CLI exposes the
      flag explicitly).
    * Vault writeback stamps ``linkedin_state: messaged``,
      ``linkedin_messaged_at:``, ``li_dm_intent_id:``,
      ``li_dm_thread_id:`` (when the MCP returns one),
      ``li_dm_confirmed_at:``.

    Intent-id correlation through the MCP call (ADR-0016 D43): the
    intent_id is embedded as a zero-width-Unicode marker in the DM
    body (same shape as the invite path's connection-note marker;
    DM bodies have an 8000-char limit so the ~30-char marker is
    near-zero overhead). Reconcile Pass E (Week 4) reads it back via
    the LinkedIn MCP's conversation-history surface.

    Returns a dict shaped like:
        {"ok": True/False, "reason": "<keyword>", "person_id": "...",
         "intent_id": "..." | None, "linkedin_thread_id": "..." | None,
         "detail": "...", "writeback_warning": "..." | None}
    """
    person_path = draft.person.note_path if draft.person else None
    if person_path is None:
        return _blocked(
            led, draft, person_id=None,
            reason="no_person_note", channel="linkedin",
            result_extras=LI_DM_BLOCK_EXTRAS,
        )
    parsed = identity.read_person_keys(person_path)
    if parsed is None:
        return _blocked(
            led, draft, person_id=None,
            reason="not_a_person_note", channel="linkedin",
            result_extras=LI_DM_BLOCK_EXTRAS,
        )
    person_id, keys = parsed
    # Stamp person_id on the span once known (per ADR-0055 D303).
    if person_id:
        try:
            _span.set_attribute("person_id", person_id)
        except Exception:
            pass
    if person_id is None or identity.id_is_temporary(person_id):
        return _blocked(
            led, draft, person_id=person_id,
            reason="identity_incomplete", channel="linkedin",
            result_extras=LI_DM_BLOCK_EXTRAS,
        )
    if not draft.person or not draft.person.linkedin:
        return _blocked(
            led, draft, person_id=person_id,
            reason="no_linkedin_url", channel="linkedin",
            detail="person record has no linkedin: field",
            result_extras=LI_DM_BLOCK_EXTRAS,
        )

    # Per ADR-0016 D44: requires-existing-connection gate.
    # Refuse-loud on unknown connection state — DMs to non-
    # connections silently land in message-request inbox; the
    # dispatcher cannot track delivery so a "success" return would
    # mis-report. Operator who wants to bypass passes
    # allow_unconnected=True (Pillar I CLI surface).
    if not allow_unconnected:
        connected = _read_person_linkedin_connected(person_path)
        if connected is None:
            return _blocked(
                led, draft, person_id=person_id,
                reason="connection_state_unknown",
                channel="linkedin",
                detail=(
                    f"Person {draft.person_name!r} has no "
                    f"linkedin_connected: field. ADR-0016 D44 refuses "
                    f"this send because a DM to a non-connection "
                    f"silently lands in the message-request inbox. "
                    f"Stamp linkedin_connected: true on the Person "
                    f"note (after verifying via the LinkedIn UI), or "
                    f"invoke with allow_unconnected=True."
                ),
                result_extras=LI_DM_BLOCK_EXTRAS,
            )
        if connected is False:
            return _blocked(
                led, draft, person_id=person_id,
                reason="not_a_connection",
                channel="linkedin",
                detail=(
                    f"Person {draft.person_name!r} is marked "
                    f"linkedin_connected: false. ADR-0016 D44 refuses "
                    f"the send. Send a connection request first "
                    f"(via gated_li_invite_one), wait for acceptance, "
                    f"flip the field to true, then retry; or invoke "
                    f"with allow_unconnected=True."
                ),
                result_extras=LI_DM_BLOCK_EXTRAS,
            )

    # Ledger-prior-send dedup (uses the generalized last_send_for from
    # ADR-0014 D33 — the indexer recognizes li_dm_confirmed as a
    # confirmed-outcome type matching channel=linkedin).
    prior = led.last_send_for(person_id, channel="linkedin")
    if prior is not None:
        return _blocked(
            led, draft, person_id=person_id, reason="already_sent",
            channel="linkedin",
            detail=f"prior intent={prior.intent_id} at {prior.ts}",
            result_extras=LI_DM_BLOCK_EXTRAS,
        )

    # Policy gate — cross-channel rule + per-channel budget rules fire
    # here. ADR-0016 D43 names ``source="linkedin_dm"`` per ADR-0015
    # D40's split-source convention; the rule activates when the
    # operator uncomments a ``budget.window-cap`` rule with
    # source=linkedin_dm in their cooldowns.yml.
    try:
        cooldown_rules = _load_cooldown_rules()
        policy_ctx = _build_linkedin_rule_context(
            draft, person_id=person_id, register=register, led=led,
            keys=keys, run_id=run_id,
        )
        policy_verdict = _policy.evaluate(cooldown_rules, policy_ctx)
    except Exception as exc:
        print(f"WARNING: policy.evaluate raised for LinkedIn DM "
              f"{person_id} register={register}: {exc}", file=sys.stderr)
        return _blocked(
            led, draft, person_id=person_id,
            reason="policy_engine_error",
            detail=f"{type(exc).__name__}: {exc}",
            event_type="policy_blocked",
            channel="linkedin",
            result_extras=LI_DM_BLOCK_EXTRAS,
        )
    if isinstance(policy_verdict, _policy.Block):
        return _blocked(
            led, draft, person_id=person_id,
            reason=policy_verdict.rule,
            detail=policy_verdict.reason,
            event_type="policy_blocked",
            block_detail=policy_verdict.detail,
            channel="linkedin",
            result_extras=LI_DM_BLOCK_EXTRAS,
        )

    lock_held = False
    if acquire_lock is not None:
        ok, msg = acquire_lock(draft.person_name)
        if not ok:
            return _blocked(
                led, draft, person_id=person_id,
                reason="locked", detail=msg, channel="linkedin",
                result_extras=LI_DM_BLOCK_EXTRAS,
            )
        lock_held = True

    try:
        intent_id = _ledger.new_intent_id()

        # Compose the DM body with the intent-id marker PRE-FLIGHT
        # (before writing intent to the ledger). LinkedIn DM bodies
        # have an 8000-char limit; the marker eats ~30 chars. Refuse-
        # loud at the boundary forecloses the surprise-overflow failure
        # mode the Week 2 per-week review's P2-1 named for the invite
        # path. Mirror of the invite gate's length check; same
        # asymmetric-failure-cost reasoning.
        body_text = (draft.linkedin_dm or "").strip()
        if not body_text:
            return _blocked(
                led, draft, person_id=person_id,
                reason="no_dm_body",
                channel="linkedin",
                detail=(
                    "touch note has no LinkedIn DM body; the dispatch-"
                    "outreach skill's voice-li-dm register populates "
                    "the body via the ## LinkedIn DM block."
                ),
                result_extras=LI_DM_BLOCK_EXTRAS,
            )
        marker = LI_DM_INTENT_MARKER_TEMPLATE.format(intent_id=intent_id)
        body_with_marker = body_text + marker
        if len(body_with_marker) > LINKEDIN_DM_BODY_MAX_CHARS:
            return _blocked(
                led, draft, person_id=person_id,
                reason="dm_body_too_long",
                detail=(
                    f"DM body ({len(body_text)} chars) + intent-id "
                    f"marker ({len(marker)} chars) = "
                    f"{len(body_with_marker)} chars, exceeds the "
                    f"LinkedIn {LINKEDIN_DM_BODY_MAX_CHARS}-char "
                    f"limit. Shorten the DM body to leave budget for "
                    f"the marker."
                ),
                channel="linkedin",
                result_extras=LI_DM_BLOCK_EXTRAS,
            )

        led.append({
            "type": "li_dm_intent",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "linkedin",
            "linkedin_url": draft.person.linkedin,
            "register": register,
        })

        # Per ADR-0055 D305 — record LinkedIn DM latency to the
        # per-channel send-latency Histogram.
        _send_start = time.monotonic()
        try:
            thread_id = linkedin_client.send_message(
                linkedin_url=draft.person.linkedin,
                message=body_with_marker,
                intent_id=intent_id,
            )
        except Exception as exc:
            led.append({
                "type": "li_dm_failed",
                "intent_id": intent_id,
                "person_id": person_id,
                "channel": "linkedin",
                "error_class": type(exc).__name__,
                "error_message": str(exc),
            })
            return {
                "ok": False,
                "reason": "send_failed",
                "person_id": person_id,
                "intent_id": intent_id,
                "linkedin_thread_id": None,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        finally:
            try:
                get_send_latency_histogram().record(
                    time.monotonic() - _send_start,
                    {"channel": "linkedin"},
                )
            except Exception:
                pass

        confirmed_event = {
            "type": "li_dm_confirmed",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "linkedin",
            "linkedin_url": draft.person.linkedin,
        }
        # ``thread_id`` is optional — the MCP's response shape varies;
        # when present, stamp it so Pillar D's reply-classifier can
        # correlate without re-querying.
        if thread_id:
            confirmed_event["linkedin_thread_id"] = thread_id
        confirm_ack = led.append(confirmed_event)
        confirmed_ts = confirm_ack.get("ts") if isinstance(confirm_ack, dict) else None

        # I7 cost-event emission (ADR-0006 + ADR-0015 D40's split-
        # source convention). ``source="linkedin_dm"`` distinct from
        # ``"linkedin_invite"`` so operators can configure separate
        # per-action budget rules. amount_usd=0.0 because LinkedIn
        # DMs are quota-only on personal accounts (LinkedIn's enforced
        # spam-protection limits, not USD-billed); units=1 ticks the
        # per-window cap.
        try:
            led.append({
                "type": "cost_incurred",
                "source": "linkedin_dm",
                "amount_usd": 0.0,
                "units": 1,
                "model_or_endpoint": "mcp__linkedin__send_message",
                "person_id": person_id,
                "run_id": run_id,
                "intent_id": intent_id,
            })
        except Exception as exc:
            print(
                f"WARNING: cost_incurred append failed for LinkedIn "
                f"DM {intent_id}: {exc}", file=sys.stderr,
            )

        wb_warning: str | None = None
        if writeback is not None:
            try:
                wb_warning = writeback(
                    draft,
                    intent_id=intent_id,
                    confirmed_at=confirmed_ts,
                    thread_id=thread_id,
                )
            except Exception as e:
                wb_warning = f"writeback raised: {e}"

        return {
            "ok": True,
            "reason": "sent",
            "person_id": person_id,
            "intent_id": intent_id,
            "linkedin_thread_id": thread_id,
            # Match the invite path's shape: keep "detail" in the
            # success return shape but leave None on success.
            "detail": None,
            "writeback_warning": wb_warning,
        }
    finally:
        if lock_held and release_lock is not None:
            try:
                release_lock(draft.person_name)
            except Exception as exc:
                print(f"WARNING: release_lock({draft.person_name!r}) "
                      f"failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Twitter DM two-phase send (Pillar C Week 5 — ADR-0018)
# ---------------------------------------------------------------------------


def _build_twitter_rule_context(
    draft: TouchDraft, *,
    person_id: str,
    register: str,
    led: _ledger.Ledger,
    keys: identity.IdentityKeys,
    run_id: str | None = None,
) -> _policy.RuleContext:
    """Construct a ``RuleContext`` for the Twitter DM policy gate.

    Mirrors :func:`_build_linkedin_rule_context` modulo
    ``channel="twitter"`` so the cross-channel rule (ADR-0003) +
    per-channel budget rules (ADR-0008) evaluate against the Twitter
    channel. The ``email`` / ``email_domain`` fields stay populated even
    on the Twitter path because some cross-channel rules
    (``cross-channel-email-suppresses-twitter``, when shipped) reference
    the operator's prior email touch by domain; the policy engine's
    ``block_when:`` filters resolve at evaluation time and silently skip
    when the field is irrelevant.
    """
    email = draft.person.email if draft.person else None
    email_domain: str | None = None
    if email and "@" in email:
        email_domain = email.split("@", 1)[1].lower()
    person_status = draft.person.status if draft.person else None
    tier = draft.person.research_tier if draft.person else None
    recipient_tz = _policy.tz_inference.infer_timezone(keys.country)
    return _policy.RuleContext(
        person_id=person_id,
        channel="twitter",
        register=register,
        email=email,
        email_domain=email_domain,
        now=datetime.now(timezone.utc),
        timezone=recipient_tz,
        ledger=led,
        person_status=person_status,
        run_id=run_id,
        tier=tier,
    )


def _tw_dm_vault_writeback(
    draft: TouchDraft,
    *,
    intent_id: str,
    confirmed_at: str | None = None,
    thread_id: str | None = None,
) -> str | None:
    """Apply the Twitter DM vault writes (touch.sent / intent_id /
    confirmed_at / thread_id / Person.status / file move).

    Returns an error message if writeback partially failed, ``None``
    on success. Mirrors :func:`_li_dm_vault_writeback` modulo the
    Twitter-specific frontmatter fields per ADR-0018 D58 + D64:

    * ``sent: true`` + ``sent_at: <today>``
    * ``twitter_state: messaged`` + ``twitter_messaged_at: <today>``
    * ``tw_dm_intent_id: <intent_id>`` (round-trippable; reconcile
      Pass F uses this to correlate ledger intent with vault touch state)
    * ``tw_dm_thread_id: <thread_id>`` (when the MCP returns one;
      Pillar D's reply-classifier reads this to correlate inbound
      Twitter replies to their originating DM thread).
    * ``tw_dm_confirmed_at: <ISO>`` (only when ``confirmed_at`` is
      passed — the dispatcher writes it on the confirm path).

    Person.status flip (queued → contacted) + the 🟦 Queue → 🟧 Active
    file move are common with the LinkedIn invite + LinkedIn DM + email
    paths — the writeback function forwards both for symmetry. Ledger
    remains authoritative; vault is the denormalized view.
    """
    today = date.today().isoformat()
    try:
        touch_updates: dict = {
            "sent": True,
            "sent_at": today,
            "twitter_state": "messaged",
            "twitter_messaged_at": today,
            "tw_dm_intent_id": intent_id,
        }
        if thread_id:
            touch_updates["tw_dm_thread_id"] = thread_id
        if confirmed_at is not None:
            touch_updates["tw_dm_confirmed_at"] = confirmed_at
        update_frontmatter(draft.note_path, touch_updates)
        tick_outcome_checkbox(draft.note_path, "Twitter DM sent")
    except Exception as e:
        return f"touch writeback failed: {e}"

    try:
        person_fm_updates: dict[str, Any] = {"last_touch": today}
        text = draft.person.note_path.read_text()
        fm, _ = split_frontmatter(text)
        flipped_to_contacted = False
        if fm.get("status") == "queued":
            person_fm_updates["status"] = "contacted"
            flipped_to_contacted = True
        if not fm.get("first_touch"):
            person_fm_updates["first_touch"] = today
        update_frontmatter(draft.person.note_path, person_fm_updates)

        if flipped_to_contacted:
            current_path = draft.person.note_path
            if "🟦 Queue" in str(current_path):
                new_path = Path(
                    str(current_path).replace("🟦 Queue", "🟧 Active"),
                )
                if not new_path.exists():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    current_path.rename(new_path)
                    draft.person.note_path = new_path
    except Exception as e:
        return f"person writeback failed: {e}"
    return None


def gated_tw_dm_one(
    draft: TouchDraft,
    *,
    twitter_client,
    led: _ledger.Ledger,
    register: str = "cold-pitch",
    run_id: str | None = None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]] = None,
    release_lock: Optional[Callable[[str], None]] = None,
    writeback: Optional[Callable[..., str | None]] = _tw_dm_vault_writeback,
) -> dict:
    """One Twitter DM through gate → two-phase send → writeback.
    """
    # Per ADR-0055 D303 — wrap the body in a send-stage span (tw_dm
    # operation) for per-channel two-phase commit visibility.
    with traced_stage(
        "send", "tw_dm",
        attributes={"channel": "twitter", "register": register},
    ) as _span:
        return _gated_tw_dm_one_inner(
            draft, twitter_client=twitter_client, led=led,
            register=register, run_id=run_id,
            acquire_lock=acquire_lock, release_lock=release_lock,
            writeback=writeback, _span=_span,
        )


def _gated_tw_dm_one_inner(
    draft: TouchDraft,
    *,
    twitter_client,
    led: _ledger.Ledger,
    register: str,
    run_id: str | None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]],
    release_lock: Optional[Callable[[str], None]],
    writeback: Optional[Callable[..., str | None]],
    _span,
) -> dict:
    """Internal body of :func:`gated_tw_dm_one`.

    The Pillar C Week 5 Twitter DM dispatcher (per ADR-0018). Mirrors
    :func:`gated_li_dm_one` modulo:

    * Twitter API call is ``twitter_client.send_dm(...)``, wrapping the
      operator's cookie-scrape MCP surface per ADR-0018 D59.
    * Event types are ``tw_dm_intent`` / ``tw_dm_confirmed`` /
      ``tw_dm_failed`` per ADR-0014 D33 + ADR-0018 D58.
    * ``channel="twitter"`` on every two-phase event per D33.
    * ``cost_incurred`` event carries ``source="twitter_dm"`` per
      ADR-0015 D40's split-source convention + ADR-0018 D58 (operators
      configure separate per-channel budget caps).
    * **No requires-existing-connection / follow-state gate** per
      ADR-0018 D60. Twitter DMs to non-follows land in the recipient's
      filtered Message Requests tab — recipient-recoverable + visible
      via a notification badge, so the asymmetric-failure-cost calculus
      inverts from LinkedIn DM's refuse-loud posture (per ADR-0016
      D44). Operators who want per-Person follow-state enforcement
      configure a cooldown YAML rule against ``follow_state:
      not_follow``; the dispatcher's gate stays clean.
    * Vault writeback stamps ``twitter_state: messaged``,
      ``twitter_messaged_at:``, ``tw_dm_intent_id:``,
      ``tw_dm_thread_id:`` (when the MCP returns one),
      ``tw_dm_confirmed_at:``.

    Intent-id correlation through the MCP call (ADR-0018 D58): the
    intent_id is embedded as a zero-width-Unicode marker in the DM
    body (same shape as the LinkedIn invite + DM markers per ADR-0015
    D39 + ADR-0016 D43). Twitter DM bodies have a 10,000-char limit
    so the ~30-char marker is <0.5% overhead. Reconcile Pass F
    (Week 5) reads it back via the Twitter MCP's recent-DMs surface.

    Returns a dict shaped like:
        {"ok": True/False, "reason": "<keyword>", "person_id": "...",
         "intent_id": "..." | None, "twitter_thread_id": "..." | None,
         "detail": "...", "writeback_warning": "..." | None}
    """
    person_path = draft.person.note_path if draft.person else None
    if person_path is None:
        return _blocked(
            led, draft, person_id=None,
            reason="no_person_note", channel="twitter",
            result_extras=TW_DM_BLOCK_EXTRAS,
        )
    parsed = identity.read_person_keys(person_path)
    if parsed is None:
        return _blocked(
            led, draft, person_id=None,
            reason="not_a_person_note", channel="twitter",
            result_extras=TW_DM_BLOCK_EXTRAS,
        )
    person_id, keys = parsed
    # Stamp person_id on the span once known (per ADR-0055 D303).
    if person_id:
        try:
            _span.set_attribute("person_id", person_id)
        except Exception:
            pass
    if person_id is None or identity.id_is_temporary(person_id):
        return _blocked(
            led, draft, person_id=person_id,
            reason="identity_incomplete", channel="twitter",
            result_extras=TW_DM_BLOCK_EXTRAS,
        )
    if not draft.person or not draft.person.twitter_handle:
        return _blocked(
            led, draft, person_id=person_id,
            reason="no_twitter_handle", channel="twitter",
            detail="person record has no twitter_handle: field",
            result_extras=TW_DM_BLOCK_EXTRAS,
        )

    # Ledger-prior-send dedup (uses the generalized last_send_for —
    # the indexer recognizes tw_dm_confirmed as a confirmed-outcome type
    # matching channel=twitter per ADR-0014 D33 + Week 1's
    # generalization).
    prior = led.last_send_for(person_id, channel="twitter")
    if prior is not None:
        return _blocked(
            led, draft, person_id=person_id, reason="already_sent",
            channel="twitter",
            detail=f"prior intent={prior.intent_id} at {prior.ts}",
            result_extras=TW_DM_BLOCK_EXTRAS,
        )

    # Policy gate — cross-channel rule + per-channel budget rules fire
    # here. ADR-0018 D58 names ``source="twitter_dm"`` per ADR-0015
    # D40's split-source convention; the rule activates when the
    # operator uncomments a ``budget.window-cap`` rule with
    # source=twitter_dm in their cooldowns.yml.
    try:
        cooldown_rules = _load_cooldown_rules()
        policy_ctx = _build_twitter_rule_context(
            draft, person_id=person_id, register=register, led=led,
            keys=keys, run_id=run_id,
        )
        policy_verdict = _policy.evaluate(cooldown_rules, policy_ctx)
    except Exception as exc:
        print(f"WARNING: policy.evaluate raised for Twitter DM "
              f"{person_id} register={register}: {exc}", file=sys.stderr)
        return _blocked(
            led, draft, person_id=person_id,
            reason="policy_engine_error",
            detail=f"{type(exc).__name__}: {exc}",
            event_type="policy_blocked",
            channel="twitter",
            result_extras=TW_DM_BLOCK_EXTRAS,
        )
    if isinstance(policy_verdict, _policy.Block):
        return _blocked(
            led, draft, person_id=person_id,
            reason=policy_verdict.rule,
            detail=policy_verdict.reason,
            event_type="policy_blocked",
            block_detail=policy_verdict.detail,
            channel="twitter",
            result_extras=TW_DM_BLOCK_EXTRAS,
        )

    lock_held = False
    if acquire_lock is not None:
        ok, msg = acquire_lock(draft.person_name)
        if not ok:
            return _blocked(
                led, draft, person_id=person_id,
                reason="locked", detail=msg, channel="twitter",
                result_extras=TW_DM_BLOCK_EXTRAS,
            )
        lock_held = True

    try:
        intent_id = _ledger.new_intent_id()

        # Compose the DM body with the intent-id marker PRE-FLIGHT
        # (before writing intent to the ledger). Twitter DM bodies
        # have a 10,000-char limit; the marker eats ~30 chars. Refuse-
        # loud at the boundary forecloses the surprise-overflow failure
        # mode (per ADR-0018 D58; mirror of the LinkedIn DM gate's
        # length check per ADR-0016 D43).
        body_text = (draft.twitter_dm or "").strip()
        if not body_text:
            return _blocked(
                led, draft, person_id=person_id,
                reason="no_dm_body",
                channel="twitter",
                detail=(
                    "touch note has no Twitter DM body; the dispatch-"
                    "outreach skill's voice-tw-dm register populates "
                    "the body via the ## Twitter DM block."
                ),
                result_extras=TW_DM_BLOCK_EXTRAS,
            )
        marker = TW_DM_INTENT_MARKER_TEMPLATE.format(intent_id=intent_id)
        body_with_marker = body_text + marker
        if len(body_with_marker) > TWITTER_DM_BODY_MAX_CHARS:
            return _blocked(
                led, draft, person_id=person_id,
                reason="dm_body_too_long",
                detail=(
                    f"DM body ({len(body_text)} chars) + intent-id "
                    f"marker ({len(marker)} chars) = "
                    f"{len(body_with_marker)} chars, exceeds the "
                    f"Twitter {TWITTER_DM_BODY_MAX_CHARS}-char limit. "
                    f"Shorten the DM body to leave budget for the "
                    f"marker."
                ),
                channel="twitter",
                result_extras=TW_DM_BLOCK_EXTRAS,
            )

        led.append({
            "type": "tw_dm_intent",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "twitter",
            "twitter_handle": draft.person.twitter_handle,
            "register": register,
        })

        # Per ADR-0055 D305 — record Twitter DM latency to the
        # per-channel send-latency Histogram.
        _send_start = time.monotonic()
        try:
            thread_id = twitter_client.send_dm(
                twitter_handle=draft.person.twitter_handle,
                message=body_with_marker,
                intent_id=intent_id,
            )
        except Exception as exc:
            led.append({
                "type": "tw_dm_failed",
                "intent_id": intent_id,
                "person_id": person_id,
                "channel": "twitter",
                "error_class": type(exc).__name__,
                "error_message": str(exc),
            })
            return {
                "ok": False,
                "reason": "send_failed",
                "person_id": person_id,
                "intent_id": intent_id,
                "twitter_thread_id": None,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        finally:
            try:
                get_send_latency_histogram().record(
                    time.monotonic() - _send_start,
                    {"channel": "twitter"},
                )
            except Exception:
                pass

        confirmed_event = {
            "type": "tw_dm_confirmed",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "twitter",
            "twitter_handle": draft.person.twitter_handle,
        }
        # ``thread_id`` is optional — the MCP's response shape varies;
        # when present, stamp it so Pillar D's reply-classifier can
        # correlate inbound Twitter DMs to the originating thread
        # without re-querying.
        if thread_id:
            confirmed_event["twitter_thread_id"] = thread_id
        confirm_ack = led.append(confirmed_event)
        confirmed_ts = confirm_ack.get("ts") if isinstance(confirm_ack, dict) else None

        # I7 cost-event emission (ADR-0006 + ADR-0015 D40's split-source
        # convention + ADR-0018 D58). ``source="twitter_dm"`` distinct
        # from ``"linkedin_dm"`` + ``"linkedin_invite"`` so operators
        # can configure separate per-channel budget rules. amount_usd
        # =0.0 because Twitter cookie-scrape is quota-bounded by the
        # MCP's rate-limit (~10 calls/minute per Twitter anti-abuse),
        # not USD-billed; units=1 ticks the per-window cap.
        try:
            led.append({
                "type": "cost_incurred",
                "source": "twitter_dm",
                "amount_usd": 0.0,
                "units": 1,
                "model_or_endpoint": "twitter_client.send_dm",
                "person_id": person_id,
                "run_id": run_id,
                "intent_id": intent_id,
            })
        except Exception as exc:
            print(
                f"WARNING: cost_incurred append failed for Twitter "
                f"DM {intent_id}: {exc}", file=sys.stderr,
            )

        wb_warning: str | None = None
        if writeback is not None:
            try:
                wb_warning = writeback(
                    draft,
                    intent_id=intent_id,
                    confirmed_at=confirmed_ts,
                    thread_id=thread_id,
                )
            except Exception as e:
                wb_warning = f"writeback raised: {e}"

        return {
            "ok": True,
            "reason": "sent",
            "person_id": person_id,
            "intent_id": intent_id,
            "twitter_thread_id": thread_id,
            "detail": None,
            "writeback_warning": wb_warning,
        }
    finally:
        if lock_held and release_lock is not None:
            try:
                release_lock(draft.person_name)
            except Exception as exc:
                print(f"WARNING: release_lock({draft.person_name!r}) "
                      f"failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Calendar booking two-phase send (Pillar C Week 6 — ADR-0019)
# ---------------------------------------------------------------------------


def _build_calendar_rule_context(
    draft: TouchDraft, *,
    person_id: str,
    register: str,
    led: _ledger.Ledger,
    keys: identity.IdentityKeys,
    run_id: str | None = None,
) -> _policy.RuleContext:
    """Construct a ``RuleContext`` for the Calendar booking policy gate.

    Mirrors :func:`_build_twitter_rule_context` modulo
    ``channel="calendar"`` so the cross-channel rule (ADR-0003) +
    per-channel budget rules (ADR-0008) evaluate against the calendar
    channel. The ``email`` / ``email_domain`` fields stay populated
    even on the Calendar path because cross-channel rules
    (``cross-channel-email-suppresses-calendar``, when shipped) may
    reference the operator's prior email touch by domain.
    """
    email = draft.person.email if draft.person else None
    email_domain: str | None = None
    if email and "@" in email:
        email_domain = email.split("@", 1)[1].lower()
    person_status = draft.person.status if draft.person else None
    tier = draft.person.research_tier if draft.person else None
    recipient_tz = _policy.tz_inference.infer_timezone(keys.country)
    return _policy.RuleContext(
        person_id=person_id,
        channel="calendar",
        register=register,
        email=email,
        email_domain=email_domain,
        now=datetime.now(timezone.utc),
        timezone=recipient_tz,
        ledger=led,
        person_status=person_status,
        run_id=run_id,
        tier=tier,
    )


def _calendar_booking_vault_writeback(
    draft: TouchDraft,
    *,
    intent_id: str,
    booking_url: str,
    invited_at: str | None = None,
) -> str | None:
    """Apply the Calendar booking vault writes (touch.sent /
    calendar_booking_intent_id / calendar_booking_invited_at /
    calendar_booking_url / Person.status / file move).

    Returns an error message if writeback partially failed, ``None`` on
    success. Mirrors :func:`_tw_dm_vault_writeback` modulo the
    Calendar-booking-specific frontmatter fields per ADR-0019 D65 + D70:

    * ``sent: true`` + ``sent_at: <today>``
    * ``calendar_booking_intent_id: <intent_id>`` (round-trippable;
      the Cal.com webhook handler stamps ``calendar_booking_confirmed_at``
      + ``calendar_booking_id`` on the touch note when the booking
      actually happens — separate write path per ADR-0019 D66's
      FastAPI route + CLI replay surface).
    * ``calendar_booking_url: <synthesized url>`` (the URL the operator
      can paste into their email/DM body to share with the recipient;
      contains the ``?intent_id=cb_<ULID>`` query param the webhook
      handler keys on for correlation).
    * ``calendar_booking_invited_at: <today>`` (timestamp of the send-
      side step; distinct from ``calendar_booking_confirmed_at`` which
      the webhook handler stamps when the recipient actually books).

    Person.status flip (queued → contacted) + the 🟦 Queue → 🟧 Active
    file move are common with the email + LinkedIn + Twitter paths.
    Ledger remains authoritative; vault is the denormalized view.
    """
    today = date.today().isoformat()
    invited_at_value = invited_at or today
    try:
        touch_updates: dict = {
            "sent": True,
            "sent_at": today,
            "calendar_booking_intent_id": intent_id,
            "calendar_booking_url": booking_url,
            "calendar_booking_invited_at": invited_at_value,
        }
        update_frontmatter(draft.note_path, touch_updates)
        tick_outcome_checkbox(draft.note_path, "Calendar booking link sent")
    except Exception as e:
        return f"touch writeback failed: {e}"

    try:
        person_fm_updates: dict[str, Any] = {"last_touch": today}
        text = draft.person.note_path.read_text()
        fm, _ = split_frontmatter(text)
        flipped_to_contacted = False
        if fm.get("status") == "queued":
            person_fm_updates["status"] = "contacted"
            flipped_to_contacted = True
        if not fm.get("first_touch"):
            person_fm_updates["first_touch"] = today
        update_frontmatter(draft.person.note_path, person_fm_updates)

        if flipped_to_contacted:
            current_path = draft.person.note_path
            if "🟦 Queue" in str(current_path):
                new_path = Path(
                    str(current_path).replace("🟦 Queue", "🟧 Active"),
                )
                if not new_path.exists():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    current_path.rename(new_path)
                    draft.person.note_path = new_path
    except Exception as e:
        return f"person writeback failed: {e}"
    return None


def _build_calendar_booking_url(base_url: str, intent_id: str) -> str:
    """Compose ``<base>?intent_id=cb_<ULID>`` (per ADR-0019 D65).

    Appends ``intent_id`` as a query parameter. Handles base URLs that
    already carry query string (``?event=intro`` etc.) by appending with
    ``&`` instead of ``?``. The intent_id value is round-tripped through
    Cal.com's webhook payload — Cal.com preserves the originating URL's
    query params in the booking response (custom-inputs / responses
    block per their schema versions per D71).

    Refuses-loud (returns empty string) when:

    * The synthesized URL would exceed ``CALENDAR_BOOKING_URL_MAX_CHARS``.
    * The base URL contains a fragment (``#`` segment) — per RFC 3986
      the fragment must be the last component of a URI; appending a
      query string after a fragment yields a URL browsers treat as
      having a fragment of ``<fragment>?intent_id=cb_<ULID>``, the
      query param never reaches Cal.com's server, and the webhook
      handler can never extract the intent_id — silently corrupting
      the correlation surface (Week 6 per-week review dispatcher P2-2).

    The dispatcher refuses-loud with ``booking_url_too_long`` for both
    cases per the asymmetric-failure-cost calculus (better to refuse
    than to ship a permanently-unlinkable URL).
    """
    if "#" in base_url:
        # Fragment in base URL would silently corrupt the correlation.
        return ""
    if "?" in base_url:
        url = f"{base_url}&intent_id={intent_id}"
    else:
        url = f"{base_url}?intent_id={intent_id}"
    if len(url) > CALENDAR_BOOKING_URL_MAX_CHARS:
        return ""
    return url


def gated_calendar_booking_one(
    draft: TouchDraft,
    *,
    cal_com_base_url: str,
    led: _ledger.Ledger,
    register: str = "cold-pitch",
    run_id: str | None = None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]] = None,
    release_lock: Optional[Callable[[str], None]] = None,
    writeback: Optional[Callable[..., str | None]] = _calendar_booking_vault_writeback,
) -> dict:
    """One Calendar booking-link share through gate → emit intent →
    writeback.
    """
    # Per ADR-0055 D303 — wrap the body in a send-stage span
    # (calendar_booking operation). NOTE: NO send-latency histogram
    # record fires here because the calendar dispatcher's send
    # action is URL-synthesis (no external API call per ADR-0019
    # D66); operators consume webhook-driven calendar_booking_
    # confirmed events separately at orchestrator/cal_com_webhook.
    with traced_stage(
        "send", "calendar_booking",
        attributes={"channel": "calendar", "register": register},
    ) as _span:
        return _gated_calendar_booking_one_inner(
            draft, cal_com_base_url=cal_com_base_url, led=led,
            register=register, run_id=run_id,
            acquire_lock=acquire_lock, release_lock=release_lock,
            writeback=writeback, _span=_span,
        )


def _gated_calendar_booking_one_inner(
    draft: TouchDraft,
    *,
    cal_com_base_url: str,
    led: _ledger.Ledger,
    register: str,
    run_id: str | None,
    acquire_lock: Optional[Callable[[str], tuple[bool, str]]],
    release_lock: Optional[Callable[[str], None]],
    writeback: Optional[Callable[..., str | None]],
    _span,
) -> dict:
    """Internal body of :func:`gated_calendar_booking_one`.

    The Pillar C Week 6 Calendar booking dispatcher (per ADR-0019).
    STRUCTURALLY DIFFERENT from Weeks 2-5's synchronous dispatchers:

    * **Send action is URL synthesis, not API call.** The dispatcher
      generates ``<base>?intent_id=cb_<ULID>`` and stamps it on the
      touch note (for the operator to paste into their email / DM
      body). No external API is called at send time — Cal.com is a
      webhook-driven surface per ADR-0019 D66.

    * **Asymmetric two-phase shape.** The dispatcher emits
      ``calendar_booking_intent`` at send time; the matching
      ``calendar_booking_confirmed`` arrives LATER via the Cal.com
      webhook (when the recipient actually books a slot). The vault
      writeback at send time stamps ``calendar_booking_intent_id`` +
      ``calendar_booking_invited_at`` + ``calendar_booking_url``; the
      webhook handler (separate write path; see
      :mod:`orchestrator.cal_com_webhook`) later stamps
      ``calendar_booking_confirmed_at`` + ``calendar_booking_id``.

    * **No ``calendar_booking_failed`` from this dispatcher.** Failure
      modes are: gate refuses (pre-flight) OR URL-synthesis refuses
      (the booking_url_too_long path). The dispatcher does NOT emit
      ``calendar_booking_failed`` because there's no API call to fail;
      future webhook-handler failures (Cal.com signature mismatch /
      payload schema violation / etc.) are observability concerns
      handled by :mod:`orchestrator.cal_com_webhook`.

    * **No reconcile pass (Pass G deferred per ADR-0019 D68).** The
      Cal.com webhook is the canonical recovery surface (Cal.com
      retries failed webhooks up to 5 times per their docs); a periodic
      reconcile pass would duplicate effort. Operators with
      late/missing webhooks use the CLI replay path per ADR-0019 D66.

    Event types are ``calendar_booking_intent`` /
    ``calendar_booking_confirmed`` / ``calendar_booking_failed`` per
    ADR-0014 D33 (NO ``_aborted`` type — abort case is
    ``calendar_booking_cancelled``, a separate Pillar D
    conversation-state concern).

    ``channel="calendar"`` on every two-phase event per D33.

    ``cost_incurred`` event carries ``source="calendar_booking"`` per
    ADR-0015 D40's split-source convention + ADR-0019 D65.
    ``amount_usd=0.0`` because Cal.com is free for individual operators
    on the personal plan; ``units=1`` ticks the per-window cap.

    Pre-flight gate sequence (mirrors gated_tw_dm_one modulo the no-
    calendar-handle equivalent — every Person can in principle receive
    a calendar link if the operator has a ``cal_com_base_url``
    configured; no per-Person required identifier):

    1. ``no_person_note`` — draft.person is None.
    2. ``not_a_person_note`` — person path doesn't parse identity.
    3. ``identity_incomplete`` — person_id missing or -tmp.
    4. ``no_cal_com_base_url`` — operator didn't supply a base URL
       (the dispatcher needs SOMEWHERE to send the recipient).
    5. ``already_sent`` — prior ``calendar_booking_confirmed`` for
       this person (cross-channel rule's same-channel cooldown via
       ``led.last_send_for``).
    6. ``policy_blocked`` — engine returns Block.
    7. ``locked`` — concurrent agent holds the per-person lock.
    8. ``no_cover_message`` — touch has no Calendar block body (the
       operator-authored cover message that surrounds the URL).
    9. ``booking_url_too_long`` — synthesized URL exceeds
       :data:`CALENDAR_BOOKING_URL_MAX_CHARS`.

    Returns a dict shaped like:
        {"ok": True/False, "reason": "<keyword>", "person_id": "...",
         "intent_id": "..." | None,
         "calendar_booking_url": "..." | None,
         "calendar_booking_id": None  (always None at send time;
                                       webhook stamps it later),
         "detail": "...", "writeback_warning": "..." | None}
    """
    person_path = draft.person.note_path if draft.person else None
    if person_path is None:
        return _blocked(
            led, draft, person_id=None,
            reason="no_person_note", channel="calendar",
            result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
        )
    parsed = identity.read_person_keys(person_path)
    if parsed is None:
        return _blocked(
            led, draft, person_id=None,
            reason="not_a_person_note", channel="calendar",
            result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
        )
    person_id, keys = parsed
    # Stamp person_id on the span once known (per ADR-0055 D303).
    if person_id:
        try:
            _span.set_attribute("person_id", person_id)
        except Exception:
            pass
    if person_id is None or identity.id_is_temporary(person_id):
        return _blocked(
            led, draft, person_id=person_id,
            reason="identity_incomplete", channel="calendar",
            result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
        )

    # Per-Person calendar_booking_url_base overrides operator-default.
    base_url = (
        (draft.person.calendar_booking_url_base if draft.person else None)
        or cal_com_base_url
        or ""
    ).strip()
    if not base_url:
        return _blocked(
            led, draft, person_id=person_id,
            reason="no_cal_com_base_url", channel="calendar",
            detail=(
                "no per-Person calendar_booking_url_base AND no "
                "operator-default cal_com_base_url; the dispatcher "
                "needs a Cal.com link to share."
            ),
            result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
        )

    # Ledger-prior-send dedup (uses the generalized last_send_for —
    # the indexer recognizes calendar_booking_confirmed as a confirmed-
    # outcome type matching channel=calendar per ADR-0014 D33 + Week 1's
    # generalization). The per-channel cooldown holds.
    prior = led.last_send_for(person_id, channel="calendar")
    if prior is not None:
        return _blocked(
            led, draft, person_id=person_id, reason="already_sent",
            channel="calendar",
            detail=f"prior intent={prior.intent_id} at {prior.ts}",
            result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
        )

    # Policy gate — cross-channel rule + per-channel budget rules fire
    # here. ADR-0019 D65 names ``source="calendar_booking"`` per
    # ADR-0015 D40's split-source convention; operators activate per-
    # channel caps by uncommenting a ``budget.window-cap`` rule with
    # source=calendar_booking in cooldowns.yml.
    try:
        cooldown_rules = _load_cooldown_rules()
        policy_ctx = _build_calendar_rule_context(
            draft, person_id=person_id, register=register, led=led,
            keys=keys, run_id=run_id,
        )
        policy_verdict = _policy.evaluate(cooldown_rules, policy_ctx)
    except Exception as exc:
        print(f"WARNING: policy.evaluate raised for Calendar booking "
              f"{person_id} register={register}: {exc}", file=sys.stderr)
        return _blocked(
            led, draft, person_id=person_id,
            reason="policy_engine_error",
            detail=f"{type(exc).__name__}: {exc}",
            event_type="policy_blocked",
            channel="calendar",
            result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
        )
    if isinstance(policy_verdict, _policy.Block):
        return _blocked(
            led, draft, person_id=person_id,
            reason=policy_verdict.rule,
            detail=policy_verdict.reason,
            event_type="policy_blocked",
            block_detail=policy_verdict.detail,
            channel="calendar",
            result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
        )

    lock_held = False
    if acquire_lock is not None:
        ok, msg = acquire_lock(draft.person_name)
        if not ok:
            return _blocked(
                led, draft, person_id=person_id,
                reason="locked", detail=msg, channel="calendar",
                result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
            )
        lock_held = True

    try:
        # Body presence check — the touch note must contain an
        # operator-authored cover message (the prose that surrounds the
        # booking URL in the outbound email/DM). Without it the
        # dispatcher refuses-loud because a bare URL is a brittle
        # outreach artifact (no context, no callable).
        cover_text = (draft.calendar_cover_message or "").strip()
        if not cover_text:
            return _blocked(
                led, draft, person_id=person_id,
                reason="no_cover_message",
                channel="calendar",
                detail=(
                    "touch note has no Calendar block body; the "
                    "dispatch-outreach skill's calendar-pitch register "
                    "populates the body via the ## Calendar block."
                ),
                result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
            )

        intent_id = _ledger.new_intent_id(
            prefix=CALENDAR_BOOKING_INTENT_ID_PREFIX,
        )
        booking_url = _build_calendar_booking_url(base_url, intent_id)
        if not booking_url:
            return _blocked(
                led, draft, person_id=person_id,
                reason="booking_url_too_long",
                detail=(
                    f"base URL ({len(base_url)} chars) + intent-id "
                    f"query param would exceed the "
                    f"{CALENDAR_BOOKING_URL_MAX_CHARS}-char URL limit. "
                    f"Shorten the operator-default cal_com_base_url or "
                    f"the per-Person calendar_booking_url_base."
                ),
                channel="calendar",
                result_extras=CALENDAR_BOOKING_BLOCK_EXTRAS,
            )

        # Two-phase commit — intent only. The matching confirmed event
        # is emitted by orchestrator.cal_com_webhook when Cal.com posts
        # the booking webhook (per ADR-0019 D66). Pillar C Week 6's
        # asymmetric shape: dispatcher writes intent + URL; webhook
        # writes confirmed. The cross-channel rule (ADR-0003) only
        # fires on _confirmed events, so an intent without a webhook-
        # delivered confirmed never blocks downstream sends.
        led.append({
            "type": "calendar_booking_intent",
            "intent_id": intent_id,
            "person_id": person_id,
            "channel": "calendar",
            "booking_url": booking_url,
            "register": register,
        })

        # I7 cost-event emission (ADR-0006 + ADR-0015 D40 + ADR-0019
        # D65). source="calendar_booking" distinct from "linkedin_dm" /
        # "linkedin_invite" / "twitter_dm" so operators can configure
        # separate per-channel budget rules. amount_usd=0.0 because
        # Cal.com is free for individual users on the personal plan;
        # units=1 ticks the per-window cap.
        try:
            led.append({
                "type": "cost_incurred",
                "source": "calendar_booking",
                "amount_usd": 0.0,
                "units": 1,
                "model_or_endpoint": "calendar_booking_url_synthesis",
                "person_id": person_id,
                "run_id": run_id,
                "intent_id": intent_id,
            })
        except Exception as exc:
            print(
                f"WARNING: cost_incurred append failed for Calendar "
                f"booking {intent_id}: {exc}", file=sys.stderr,
            )

        wb_warning: str | None = None
        if writeback is not None:
            try:
                wb_warning = writeback(
                    draft,
                    intent_id=intent_id,
                    booking_url=booking_url,
                )
            except Exception as e:
                wb_warning = f"writeback raised: {e}"

        return {
            "ok": True,
            "reason": "sent",
            "person_id": person_id,
            "intent_id": intent_id,
            "calendar_booking_url": booking_url,
            "calendar_booking_id": None,  # webhook stamps later
            "detail": None,
            "writeback_warning": wb_warning,
        }
    finally:
        if lock_held and release_lock is not None:
            try:
                release_lock(draft.person_name)
            except Exception as exc:
                print(f"WARNING: release_lock({draft.person_name!r}) "
                      f"failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Lock adapter (orchestrator/locks.py needs an agent_id + stage)
# ---------------------------------------------------------------------------


def _make_lock_callbacks(agent_id: str | None = None
                         ) -> tuple[Callable[[str], tuple[bool, str]],
                                    Callable[[str], None]]:
    """Wrap orchestrator/locks.py into the (acquire, release) shape.

    Returned functions take just the prospect name — they close over the
    agent_id + a fixed stage="sending" so the call sites stay uncluttered.
    Failures to import locks (e.g., config missing) fall back to noop
    callbacks; the ledger gate is still the primary protection.
    """
    try:
        import locks
    except (ImportError, SystemExit):
        return (lambda _name: (True, "no-op (locks unavailable)"), lambda _name: None)
    aid = agent_id or f"send-{uuid.uuid4().hex[:8]}"

    def _acquire(name: str) -> tuple[bool, str]:
        return locks.acquire(name, aid, stage="sending")

    def _release(name: str) -> None:
        locks.release(name)

    return _acquire, _release


# ---------------------------------------------------------------------------
# LinkedIn manifest (unchanged from Phase 4)
# ---------------------------------------------------------------------------


def _emit_linkedin_manifest(drafts: list[TouchDraft], out_path: Path) -> None:
    manifest = []
    for d in drafts:
        if _classify(d) not in ("ready_email_li", "ready_li", "ready_li_email_done"):
            continue
        sent_at = d.frontmatter.get("sent_at")
        manifest.append({
            "note_path": str(d.note_path),
            "person": d.person_name,
            "linkedin_url": d.person.linkedin,
            "dm_text": d.linkedin_dm,
            "email_sent_at": str(sent_at) if sent_at else None,
            "current_li_state": d.frontmatter.get("linkedin_state", "not_invited"),
        })
    out_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote LinkedIn manifest: {out_path}  ({len(manifest)} entries)")
    print("Claude: read this file, then for each entry with current_li_state == 'not_invited':")
    print("  1. Call mcp__linkedin__connect_with_person (no note, per free-tier constraint)")
    print("  2. Update touch note frontmatter: linkedin_state: invited, linkedin_invited_at: today")
    print("  3. Tick the 'LinkedIn sent' outcome checkbox")
    print("  4. Append a cost_incurred ledger event (ADR-0008 transitional emit):")
    print("     python -m orchestrator.ledger append '{")
    print('       "type":"cost_incurred","source":"linkedin","units":1,')
    print('       "amount_usd":0.0,"model_or_endpoint":"connect_with_person",')
    print('       "person_id":"<person.id>"')
    print("     }'")
    print("     The policy engine's linkedin-weekly-invite-cap rule (cooldowns.yml)")
    print("     reads these to enforce the 100/wk soft limit. Pillar C will")
    print("     replace this manual step with two-phase li_invite_intent /")
    print("     li_invite_confirmed events; until then, every successful")
    print("     invite MUST be followed by this append or the cap rule")
    print("     under-reports and silently allows over-quota sends.")
    print("  Stop and warn the user when the weekly invite tally approaches 100.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _maybe_run_quick_reconcile(led: _ledger.Ledger, gmail_client) -> None:
    """Run Pass A in-process when the freshness gate trips.

    Conservative: errors here log to stderr and continue. Skipping a stale
    reconcile is worse than crashing the send batch over a Gmail blip; the
    individual sends still gate-check on their own.
    """
    try:
        # Lazy import: keeps the core send path import-lean. reconcile pulls the
        # heavy operations tier; an adopter without it (or running --skip-
        # reconcile-gate) still sends, gated by the per-draft checks. An
        # ImportError here is caught below and degrades to a stderr warning.
        import reconcile as _reconcile_mod  # noqa: PLC0415
        if not _reconcile_mod.needs_quick_reconcile(led=led):
            return
        print("Reconcile freshness gate tripped — running --quick first...")
        adapter = _reconcile_mod._GmailAdapter(gmail_client)
        result = _reconcile_mod.reconcile(
            passes="A",
            since=datetime.now(timezone.utc) - _reconcile_mod.QUICK_WINDOW,
            gmail=adapter, led=led, apply=True,
        )
        for pr in result.passes:
            print(f"  Pass {pr.pass_name}: {pr.summary()}")
    except Exception as exc:
        print(f"WARNING: pre-send reconcile failed: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Send queued cold-touch emails")
    ap.add_argument("--dry-run", action="store_true", help="Show preview, don't send")
    ap.add_argument("--yes", action="store_true", help="Skip confirmation prompt (use with care)")
    ap.add_argument("--only", help="Only process touches whose person name contains this substring")
    ap.add_argument(
        "--linkedin-manifest", type=Path, default=LINKEDIN_MANIFEST_PATH,
        help="Where to write the LinkedIn manifest for Claude to consume",
    )
    ap.add_argument(
        "--skip-reconcile-gate", action="store_true",
        help="Disable the pre-send 'last quick reconcile within 1h' freshness check",
    )
    args = ap.parse_args()

    drafts = find_pending_touches()
    if args.only:
        needle = args.only.lower()
        drafts = [d for d in drafts if needle in d.person_name.lower()]
    if not drafts:
        print("No unsent cold-touch notes found.")
        return 0

    counts = _print_preview(drafts)
    if counts["email_ready"] == 0 and counts["linkedin_ready"] == 0:
        print("Nothing ready to send.")
        return 0

    if args.dry_run:
        print("(dry-run) — exiting without sending")
        return 0

    args.linkedin_manifest.parent.mkdir(parents=True, exist_ok=True)
    _emit_linkedin_manifest(drafts, args.linkedin_manifest)

    if counts["email_ready"] == 0:
        print("\nNo emails to send (LinkedIn-only batch). Hand off to Claude via the manifest above.")
        return 0

    if not args.yes:
        print(f"\nReady to send {counts['email_ready']} emails. Continue? [y/N] ", end="", flush=True)
        ans = sys.stdin.readline().strip().lower()
        if ans != "y":
            print("Aborted.")
            return 1

    led = _ledger_handle()
    client = GmailClient.authenticate()
    print(f"\nAuthenticated as: {client.sender_email}\n")

    if not args.skip_reconcile_gate:
        _maybe_run_quick_reconcile(led, client)

    acquire_lock, release_lock = _make_lock_callbacks()
    run_id = f"run-{uuid.uuid4().hex[:10]}"

    # J7 (ADR-0079 D394): build the CAN-SPAM SecurityConfig once per run and
    # thread it into every send so the footer + List-Unsubscribe headers are
    # stamped on every outbound email. None when no `security:` block exists
    # (legacy footer-less path). Warn loudly if the address is still the
    # placeholder so a non-compliant cold send can't slip out unnoticed.
    security_cfg = _build_security_cfg()
    if security_cfg is not None:
        addr = security_cfg.physical_mailing_address
        if addr.startswith("REPLACE_ME") or "<real postal address>" in addr:
            print(
                "\n  ⚠ CAN-SPAM physical address is still the PLACEHOLDER "
                f"({addr!r}).\n    The footer will ship a FAKE address, which is "
                "a CAN-SPAM violation for real recipients.\n    Replace "
                "`security.physical_mailing_address` in the config before "
                "emailing strangers.\n", file=sys.stderr,
            )
        print(f"CAN-SPAM footer: ON (unsubscribe base {security_cfg.unsubscribe_base_url})")
    else:
        print("CAN-SPAM footer: OFF (no `security:` config block)")

    # Pre-send suppression gate (honors recipients who used the J7 one-click
    # unsubscribe). OFF until the suppressions API URL is configured (post-deploy).
    suppression_check = _suppression_checker()
    if suppression_check is not None:
        print(f"Suppression check: ON ({SECURITY_SUPPRESSION_CHECK_URL})")
    else:
        print("Suppression check: OFF (set security.suppression_check_url once "
              "your /unsubscribe endpoint is deployed)")

    sent = blocked = failed = 0
    for d in drafts:
        if _classify(d) not in ("ready_email", "ready_email_li"):
            continue
        # Honor unsubscribes before doing anything else. Resolve person_id the
        # same way gated_send_one does so the suppression token matches the one
        # stamped in the unsubscribe URL. On a check failure we fail-closed
        # (skip); mailing a possible opt-out is the costlier error.
        if suppression_check is not None and d.person is not None:
            _parsed = identity.read_person_keys(d.person.note_path)
            _pid = _parsed[0] if _parsed else None
            if _pid:
                _suppressed, _why = suppression_check(_pid)
                if _suppressed:
                    blocked += 1
                    _reason = "unsubscribed" if _why is None else "suppression_check_failed"
                    print(f"  ⏭ {d.person_name:<30}  blocked: {_reason}  "
                          f"{_why or 'recipient opted out (suppressed)'}")
                    continue
        outcome = gated_send_one(
            d, gmail_client=client, led=led,
            sender_name=SENDER_NAME,
            run_id=run_id,
            acquire_lock=acquire_lock, release_lock=release_lock,
            security_cfg=security_cfg,
        )
        if outcome["ok"]:
            sent += 1
            extra = f"  ⚠ {outcome['writeback_warning']}" if outcome.get("writeback_warning") else ""
            print(f"  ✓ {d.person_name:<30}  sent (gmail={outcome['gmail_message_id']}){extra}")
        elif outcome["reason"] == "send_failed":
            failed += 1
            print(f"  ✗ {d.person_name:<30}  {outcome['reason']}  {outcome.get('detail') or ''}")
        else:
            blocked += 1
            print(f"  ⏭ {d.person_name:<30}  blocked: {outcome['reason']}  "
                  f"{outcome.get('detail') or ''}")

    try:
        led.append({
            "type": "send_run_complete",
            "run_id": run_id,
            "sent_count": sent,
            "blocked_count": blocked,
            "failed_count": failed,
            "total_candidates": counts["email_ready"],
        })
    except Exception as exc:
        print(f"WARNING: send_run_complete append failed: {exc}", file=sys.stderr)

    print(f"\n=== DONE: {sent} sent, {blocked} blocked, {failed} failed ===")
    if counts["linkedin_ready"]:
        print(f"\nNext: handle {counts['linkedin_ready']} LinkedIn touches via Claude (manifest at {args.linkedin_manifest})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
