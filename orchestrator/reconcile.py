"""Reconcile — heal the five sources of truth (ledger, Gmail, LinkedIn,
Twitter, vault).

Phase 5.5 shipped Passes A/B/C against the email + vault path. Pillar C
Week 4 (ADR-0017) extends to per-channel LinkedIn recovery — Pass D
(invites) + Pass E (DMs) — the LinkedIn-side analogs of email's Pass A.
Pillar C Week 5 (ADR-0018) extends to Twitter DM recovery — Pass F —
via the same generalized helper (`_run_channel_intent_pass`) per
ADR-0018 D62. Pillar D Week 2 (ADR-0026) adds Pass G — the rule-based
reply classifier — extending the chain from "send-state recovery" to
"reply-state classification." Pillar D Week 3 (ADR-0027) adds the per-
channel reply detection passes: Pass H (LinkedIn invite acceptances),
Pass I (LinkedIn DM replies), Pass J (Twitter DM replies); these
PRODUCE reply events that Pass G CONSUMES. Pillar D Week 4-5 (ADR-
0028) adds Pass M (auto-unsubscribe handler — writes the suppression
YAML for `category=unsubscribe` classifications) + Pass N
(conversation state machine — emits `conversation_state_changed`
events per thread); Pass C also gains a `conversation_status:` heal
extension. Pass K is the deferred Cal.com slot
per ADR-0027 D113; Pass L is intentionally skipped (letter-sequence
preserves the deferred Pass K's operator-readability).

Pillar G Week 6 (ADR-0055 D300-D306) adds per-stage OTel span
instrumentation at every reconcile pass call site via
:func:`observability.traced_stage` — operators tracing the reconcile
loop see each pass (A/B/C/D/E/F/G/H/I/J/M/N/O) as a named span +
the per-pass latency/error attributes. Privacy invariant per ADR-0054
D297 holds across spans.

The send path is two-phase (`<channel>_intent` → external API →
`<channel>_confirmed`) and any moving part (vault frontmatter, ledger,
the external surface — Gmail Sent / Gmail inbox / LinkedIn invitations /
LinkedIn conversations / Twitter DMs) can drift on a crash, network
hiccup, sync conflict, or manual edit. Reconcile is the periodic healer
that brings them back into agreement.

Twelve modular passes (Pass K deferred; Pass L unused):

  Pass A — Ledger ↔ Gmail (email intent recovery)
    For every `send_intent` older than --min-intent-age (default 5min) in the
    window with no matching outcome event, search Gmail for the message
    stamped with that intent_id. Found → synthesize `send_confirmed` with the
    live message + thread ids. Not found → `send_aborted` with reason.

  Pass B — Inbox ↔ Ledger (replies + bounces)
    For each `send_confirmed` in window with a known gmail_thread_id, fetch
    the thread and classify any inbound messages as bounce (DSN), reply, or
    unknown. Emit `bounce_detected` / `reply_received` events linked to the
    person_id. Idempotent — events already in the ledger (by
    gmail_message_id) are skipped.

  Pass C — Vault ↔ Ledger (denormalized-view heal)
    For each Person note, compare frontmatter `pipeline_stage` against the
    ledger's `derived_stage(person_id)`. Drift in the safe direction
    (ledger > vault) under --apply: write the canonical stage to the
    Person note + emit `reconcile_healed`. Drift in the unsafe direction
    (vault claims stage X but ledger has no support) → `reconcile_drift`
    with `conflict: true`; never auto-heal (the user wrote that vault state
    for a reason; surface for manual review).

  Pass D — Ledger ↔ LinkedIn invitations (LinkedIn-invite intent recovery)
    For every `li_invite_intent` older than --min-intent-age (default 5min)
    in the window with no matching outcome event, query the LinkedIn
    client's sent-invitations surface for an invitation whose connection-
    note text contains the operator's intent-id marker (the zero-width-
    Unicode-wrapped token per ADR-0015 D39). Found → synthesize
    `li_invite_confirmed`. Not found → `li_invite_aborted` (per ADR-0017
    D50's asymmetric-failure-cost calculus). Per ADR-0017 D48, runs
    SERIALLY after Pass A/B and before Pass E.

  Pass E — Ledger ↔ LinkedIn conversations (LinkedIn-DM intent recovery)
    For every `li_dm_intent` older than --min-intent-age in the window
    with no matching outcome event, query the LinkedIn client's recent-
    conversations surface for a DM whose body contains the marker (same
    marker shape per ADR-0016 D43). Found → synthesize `li_dm_confirmed`.
    Not found → `li_dm_aborted`. Per ADR-0017 D48, runs SERIALLY after
    Pass D.

  Pass F — Ledger ↔ Twitter DMs (Twitter-DM intent recovery)
    For every `tw_dm_intent` older than --min-intent-age in the window
    with no matching outcome event, query the Twitter client's recent-
    DMs surface for a DM whose body contains the marker (same marker
    shape per ADR-0018 D58 = ADR-0015 D39 = ADR-0016 D43). Found →
    synthesize `tw_dm_confirmed`. Not found → `tw_dm_aborted`. Per
    ADR-0018 D62 reuses the generalized `_run_channel_intent_pass`
    helper (renamed from Week 4's `_run_linkedin_intent_pass`). Per
    ADR-0018 D58, runs SERIALLY after Pass E by-convention; Twitter's
    cookie-scrape MCP rate-limit pool is distinct from LinkedIn's, so
    the serialization is observability-oriented (uniform per-pass
    logging) rather than rate-limit-required.

  Pass G — Reply classification (Pillar D Week 2, ADR-0026; Week 3
           extended per ADR-0027)
    For every reply event (per :data:`REPLY_EVENT_TYPES`) in the
    window that does not yet have a paired `reply_classified` event
    (idempotence-by-`(reply_message_id, channel)` per ADR-0026 D104),
    dispatch to the rule-based classifier
    (`orchestrator.reply_classifier`) + emit a `reply_classified`
    event per ADR-0025 D97. Week 2 shipped the unsubscribe path ONLY;
    Week 3 (ADR-0027 D108-D110) extends to the long-tail categories
    (ooo / wrong_person / interest / rejection) — the unsubscribe
    path remains rule-based ONLY (the LLM is NEVER consulted for
    unsubscribe per PILLAR-PLAN §5 + the load-bearing legal-liability
    invariant pinned by `tests/test_multi_channel_coherence.py::
    TestUnsubscribeEnforcement
    ::test_unsubscribe_classification_method_is_always_rule`). Non-
    matching replies are classified as `uncategorized` per ADR-0026
    D107 (the visibility-without-action fallback). Pass G has NO
    external client dependency — it's a pure framework operation
    (regex match against ledger events). The operator's pattern
    files live at `~/.outreach-factory/classifier/{category}-
    patterns.yml` per ADR-0026 D103 + ADR-0027 D109 (factory shapes
    at `config-template/{category}-patterns.example.yml`). Auto-
    unsubscribe enforcement (YAML write + suppression-rule
    integration) lands Pillar D Week 4-5 (ADR-0028 — TBD) per ADR-0026
    D107's two-week split rationale.

  Pass H — LinkedIn invite acceptance detection (Pillar D Week 3,
           ADR-0027 D111)
    For every `li_invite_confirmed` event in the window that does
    not yet have a paired `li_invite_reply_received` event, query
    the LinkedIn surface for the invitation's acceptance status. If
    `status == "accepted"`, emit `li_invite_reply_received` with
    `channel: "linkedin"` + `reply_message_id: <synthesized
    li_accept:invitation_id token>` + `reply_to_intent_id: <the
    intent_id of the originating li_invite_intent>` per ADR-0025 D96.
    The synthesized reply_message_id is necessary because LinkedIn
    invitation-acceptance is a connection-state change, not a
    message-with-id; the token guarantees the (mid, channel)
    idempotence pair per ADR-0026 D104 stays well-defined. Pass H
    PRODUCES events Pass G CONSUMES.

  Pass I — LinkedIn DM reply detection (Pillar D Week 3, ADR-0027 D111)
    For every inbound message (`from_self: False`) on a LinkedIn
    conversation whose `thread_id` matches a known
    `li_dm_confirmed.linkedin_thread_id` in the window, emit
    `li_dm_reply_received` with `channel: "linkedin"` +
    `reply_message_id: <per-message id>` + `reply_to_intent_id: <the
    intent_id of the originating li_dm_intent>` per ADR-0025 D96.
    Idempotent per ADR-0026 D104 — re-running Pass I against the
    same conversation does NOT re-emit. Pass I PRODUCES events Pass
    G CONSUMES.

  Pass J — Twitter DM reply detection (Pillar D Week 3, ADR-0027 D111)
    Structurally identical to Pass I against Twitter's cookie-scrape
    MCP surface. For every inbound message on a Twitter DM thread
    whose `thread_id` matches a known
    `tw_dm_confirmed.twitter_thread_id` in the window, emit
    `tw_dm_reply_received` with `channel: "twitter"`. Pass J PRODUCES
    events Pass G CONSUMES. Pass I + Pass J share the generalized
    helper :func:`_run_channel_dm_reply_pass` (analogous to ADR-0018
    D62's `_run_channel_intent_pass` generalization).

  Pass K (Cal.com booking reply detection) is DEFERRED to Pillar I OSS
  bring-up per ADR-0027 D113 — Cal.com's public webhook API does not
  expose a per-booking comment surface. The booking-state events
  (`calendar_booking_confirmed` / `calendar_booking_rescheduled` /
  `calendar_booking_cancelled`) emitted by the Cal.com webhook handler
  (ADR-0019) ARE the calendar-channel reply signals today; they're
  classified through the dispatcher/webhook path, not via Pass G's
  classifier.

  Pass L is intentionally unused — the letter sequence skips L so the
  deferred Pass K slot stays operator-readable.

  Pass M — Auto-unsubscribe handler (Pillar D Week 4-5, ADR-0028 D115-
           D117)
    Walks `reply_classified` events filtered to `category=unsubscribe`
    + dedups by `(reply_message_id, channel)` + writes the suppression
    YAML via `policy.suppression.forget_append` (ADR-0004 primitive)
    + emits `suppression_added` ledger events. Per ADR-0025 D100 the
    write order is YAML-first + ledger-second: a crash between the two
    leaves the suppression LIVE (CAN-SPAM compliance posture preserved
    even when the audit trail is incomplete). The handler reads ONLY
    `category=unsubscribe` events — the long-tail categories don't
    trigger auto-suppression (rule-based-ONLY legal-liability path
    per ADR-0025 D97). The "M = mutation" naming reflects M's
    distinction from Passes A-L: M is the first pass that writes
    OUTSIDE the ledger (to the suppression YAML).

  Pass N — Conversation state machine (Pillar D Week 4-5, ADR-0028
           D118-D119; ADR-0030 D132 — TTL extension)
    Walks the ledger; computes the canonical per-thread conversation
    state (`replied → classified → unsubscribed | active | dormant`)
    per ADR-0025 D98; emits `conversation_state_changed` events for
    transitions not yet recorded. Per-thread state, NOT per-person —
    a Person with multiple email threads + a LinkedIn DM thread has
    independent state machines per thread. Pass C's vault heal
    extension (per ADR-0028 D119) denormalizes the per-thread states
    into the Person-level `conversation_status:` frontmatter field via
    `conversation_state.derived_conversation_status(person_id)` —
    aggregation logic: highest-priority state across all threads wins
    (unsubscribed > active > dormant > classified > replied). Per
    ADR-0030 D132 Pass N also emits TTL-driven `* → dormant`
    transitions for non-terminal threads with no activity past
    `--conversation-ttl-days` (default 30); the trigger_event_id
    carries `driver: "ttl"` so consumers distinguish.

  Pass O — Conversation outcomes (Pillar D Week 9-11, ADR-0030
           D130-D133)
    Walks the canonical thread state (via conversation_state
    primitive — same source as Pass N); emits per-thread
    `conversation_outcome` events for terminal states (closed_won /
    closed_lost / closed_unsubscribed / dormant). Last-touch-wins
    attribution per-channel: the winning/losing touch is the most-
    recent `*_confirmed` event on the SAME channel as the thread
    for the same person before the outcome-driving event. closed_won
    requires a `calendar_booking_confirmed` for the person AFTER
    the thread's active-transition timestamp. Pass O is NOT
    run-window-bounded by `--since` (outcome attribution walks
    back through historical touches); idempotence by
    (person_id, channel, thread_key, outcome) tuple keeps re-runs
    cheap.

CLI:

    python reconcile.py --quick           # last 24h, Pass A only, applies
    python reconcile.py --full            # last 30d, all 13 passes, applies
    python reconcile.py --since 7d --passes A,B,C,D,H,E,I,F,J,G,M,N,O
    python reconcile.py --dry-run         # report; no ledger or vault writes
    python reconcile.py --apply           # write events + vault changes
    python reconcile.py --status          # show last-clean-run timestamps
    python reconcile.py --classifier-rule-list <path>  # override Pass G's pattern file
    python reconcile.py --suppressions-dir <path>      # override Pass M's YAML dir
    python reconcile.py --conversation-ttl-days N      # override Pass N's TTL (default 30)

Apply semantics: `--quick` and `--full` imply --apply by default. Bare
`--passes <list>` defaults to dry-run unless --apply is passed. Explicit
--dry-run always wins.

Status persistence: `~/.outreach-factory/reconcile/status.yml` records the
ts of the last clean run per pass + the counts surfaced. send_queued.py
reads this file to enforce the "last --quick within 1h" freshness gate.

Gmail client: passed in. The send-outreach skill wires its own GmailClient
through a thin adapter; tests inject a fake. See GmailClientLike below for
the duck-typed surface.

LinkedIn client: passed in. The Week 4 LinkedIn adapter wraps the MCP-
backed client for the sent-invitations + recent-conversations surfaces.
Tests inject a fake. See LinkedInClientLike below for the duck-typed
surface. The protocol intentionally accepts whatever MCP surface the
operator's environment exposes — production deployment may wrap
`mcp__linkedin__get_sent_invitations` + `mcp__linkedin__get_inbox` +
`mcp__linkedin__get_conversation`, while OSS bring-up (Pillar I) ships
a reference adapter that does the same.

Twitter client: passed in. The Week 5 Twitter adapter wraps a cookie-
scrape MCP-backed client for the recent-DMs surface per ADR-0018 D59.
Tests inject a fake. See TwitterClientLike below for the duck-typed
surface — single method (`list_recent_dms`) covers Pass F. The
dispatcher's wider surface (`send_dm`) is not part of the Protocol
(Pass F is read-only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

import yaml

import auto_unsubscribe as _auto_unsubscribe
import conversation_outcomes as _conversation_outcomes
import conversation_state as _conversation_state
import identity
import ledger as _ledger
import reply_classifier as _reply_classifier
from observability import traced_stage


DEFAULT_RECONCILE_DIR = Path.home() / ".outreach-factory" / "reconcile"
# Pillar C Week 5 (ADR-0018) — Pass F joins the serial sequence after
# Pass E. Per ADR-0017 D48 the LinkedIn-MCP-rate-limit-pool serializes
# D + E; Pass F uses a distinct Twitter cookie-scrape MCP whose rate-
# limit pool is independent, so the serialization is by-convention
# (uniform operator-facing ordering) rather than by-rate-limit-pool.
# Pillar D Week 2 (ADR-0026) — Pass G is the rule-based reply
# classifier; it consumes reply events emitted by Pass B (email
# replies) + the per-channel reply detection passes added in Pillar D
# Week 3 + emits ``reply_classified`` events per ADR-0025 D97. Pass G
# has NO external client dependency (pure framework operation — regex
# match against ledger events); the serialization after Pass F is by
# data-flow (producers before consumers).
# Pillar D Week 3 (ADR-0027) — Passes H + I + J ADD per-channel reply
# detection (LinkedIn invite acceptance / LinkedIn DM reply / Twitter
# DM reply respectively). Per ADR-0027 D111 the new passes run BEFORE
# Pass G in the chain so the events they emit are consumed in the same
# reconcile run — the (mid, channel) idempotence in Pass G handles
# the same-run sequencing (events produced in Pass H/I/J land in the
# ledger; Pass G's all-events walk picks them up). Pass H joins the
# chain after Pass D (LinkedIn invite intent recovery → invite reply
# detection); Pass I after Pass E (LinkedIn DM intent recovery → DM
# reply detection); Pass J after Pass F (Twitter DM intent recovery
# → DM reply detection); Pass G runs after H/I/J.
# Pillar D Week 4-5 (ADR-0028) — Pass M (auto-unsubscribe handler)
# and Pass N (conversation state machine) join the chain after Pass
# G. Pass M reads ``reply_classified`` events filtered to
# ``category=unsubscribe`` + writes the suppression YAML (per ADR-
# 0025 D100's YAML-first contract) + emits ``suppression_added``
# events. Pass N walks the ledger + emits ``conversation_state_
# changed`` events per ADR-0025 D98. The naming "M = mutation" is
# operator-clarity: M is the first pass that WRITES outside the
# ledger to an external file (the suppression YAML). N is the next
# alphabetical letter; the conversation state machine consumes M's
# ``suppression_added`` emissions to drive the ``classified →
# unsubscribed`` transition. Pass K (Cal.com booking-reply
# detection) remains the deferred slot per ADR-0027 D113 — a future
# Pillar I OSS bring-up may ship it if Cal.com gains a comment API.
# Pass L is intentionally unused (skipped in the letter sequence so
# the deferred Pass K slot stays operator-readable).
# Pillar D Week 9-11 (ADR-0030) — Pass O (conversation outcomes
# derivation) joins after Pass N. Pass O reads the canonical thread
# state (computed by `conversation_state.compute_thread_states` —
# the SAME source Pass N emits from) + emits per-thread
# `conversation_outcome` events for terminal outcomes (closed_won /
# closed_lost / closed_unsubscribed / dormant). Pass N is also
# extended with the TTL-driven `* → dormant` transition (per ADR-
# 0030 D132); the `--conversation-ttl-days` CLI flag controls the
# TTL window (default 30 days per `conversation_state.DEFAULT_
# CONVERSATION_TTL_DAYS`).
ALL_PASSES = ("A", "B", "C", "D", "H", "E", "I", "F", "J", "G", "M", "N", "O")
QUICK_WINDOW = timedelta(hours=24)
FULL_WINDOW = timedelta(days=30)
DEFAULT_MIN_INTENT_AGE = timedelta(minutes=5)


# Per ADR-0027 D112 — the closed set of reply event types Pass G
# consumes. Week 2 shipped ``reply_received`` (email) only; Week 3
# adds the per-channel reply event classes Pass H / I / J emit. Cal.
# com booking-reply detection is deferred per ADR-0027 D113 (no
# per-booking comment surface in Cal.com's public API); the calendar-
# channel reply signal is the booking-state event itself
# (``calendar_booking_confirmed`` / ``_rescheduled`` / ``_cancelled``),
# classified through the dispatcher/webhook path, NOT via Pass G.
#
# The closed-set discipline mirrors ``_INTENT_TYPES`` / ``_OUTCOME_TYPES``
# / ``_CONFIRMED_TYPES`` per the ADR-0025 D99 cross-pillar audit's
# pattern: literal-string filters prevent Pass-A-class broadening
# when future contributors add new event types (a new reply event
# class doesn't accidentally land in Pass G unless explicitly added
# to this constant + the audit row in REVIEW-pillar-d-surface-audit.md).
REPLY_EVENT_TYPES: frozenset[str] = frozenset({
    "reply_received",                  # Phase 5.5 Pass B (email)
    "li_invite_reply_received",        # Pillar D Week 3 Pass H
    "li_dm_reply_received",            # Pillar D Week 3 Pass I
    "tw_dm_reply_received",            # Pillar D Week 3 Pass J
    # "calendar_booking_reply_received" deferred to Pillar I per
    #   ADR-0027 D113 — Cal.com has no per-booking comment API.
})

# Stage ordering for Pass C drift classification.
STAGE_RANK = {"queued": 0, "researched": 1, "drafted": 2, "ready": 3, "sent": 4}

# Footer marker stamped into outbound emails so Gmail's body-text search can
# recover the intent_id even when custom-header search misbehaves. Keep this
# in sync with skills/send-outreach/scripts/send_queued.py.
INTENT_FOOTER_RE = re.compile(r"outreach-intent:(snd_[0-9A-HJKMNP-TV-Z]{26})")

# Per ADR-0017 D49: Pass D + Pass E walk the most-recent N items returned
# by the LinkedIn client (default 100, matching LinkedIn's UI page size +
# covering the worst-case operator scenario of ~50 orphans across both
# action types within a 24h crash window).
LINKEDIN_DEFAULT_SCAN_LIMIT = 100

# Pillar C Week 5 (ADR-0018 D58 + the D62 helper generalization) — Pass F
# walks the most-recent N Twitter DMs returned by the Twitter client. The
# default mirrors LINKEDIN_DEFAULT_SCAN_LIMIT for cross-channel uniformity;
# Twitter's cookie-scrape rate-limit (~10 calls/minute) is the binding
# operational constraint, not the per-call return-size budget.
TWITTER_DEFAULT_SCAN_LIMIT = 100

# Marker regex for LinkedIn invite notes + DM bodies + Twitter DM bodies.
# The marker scheme (per ADR-0015 D39 + ADR-0016 D43 + ADR-0018 D58) is
# `<ZWS>outreach-intent:<intent_id><ZWS>` — same `outreach-intent:` prefix
# as the email body footer + the same ULID intent_id shape. Reuses
# INTENT_FOOTER_RE because the on-the-wire token is identical; the
# difference is only the surrounding zero-width-space wrapping, which
# doesn't affect the regex match. Per ADR-0018 D58 the regex carries
# unchanged from LinkedIn to Twitter. The original Week 4 name
# (``LINKEDIN_INTENT_MARKER_RE``) was renamed per ADR-0018 D62's
# generalization discipline; the channel-agnostic name is the canonical
# reference going forward.
CHANNEL_INTENT_MARKER_RE = INTENT_FOOTER_RE

DSN_FROM_RE = re.compile(
    r"(mailer-daemon|postmaster|mail delivery|delivery subsystem)",
    re.IGNORECASE,
)
DSN_SUBJECT_RE = re.compile(
    r"(delivery status|undelivered|undeliverable|returned mail|"
    r"failure notice|mail delivery failed)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Gmail client protocol
# ---------------------------------------------------------------------------


class GmailClientLike(Protocol):
    """Duck-typed subset of GmailClient that reconcile needs.

    The real adapter lives in skills/send-outreach/scripts (it wraps the
    googleapiclient resource). Tests pass a fake implementation.
    """

    sender_email: str

    def search_messages(self, query: str, max_results: int = 100) -> list[dict]:
        """Return list of {id, threadId} matching Gmail search query."""

    def get_message(self, msg_id: str) -> dict | None:
        """Full message dict with headers + (optionally) body. None if missing."""

    def get_thread(self, thread_id: str) -> dict | None:
        """Full thread dict including messages list. None if missing."""


class LinkedInClientLike(Protocol):
    """Duck-typed subset of a LinkedIn client that reconcile Pass D / E / H / I need.

    Per ADR-0017 (Pass D + E intent recovery) + ADR-0027 D111 (Pass H +
    Pass I reply detection), the real adapter wraps the MCP-backed
    LinkedIn surfaces (`mcp__linkedin__get_sent_invitations`-shaped +
    `mcp__linkedin__get_inbox` + `mcp__linkedin__get_conversation`).
    Tests inject fakes. The methods cover the four distinct passes:

    * ``list_sent_invitations(limit)`` → list of dicts shaped
      ``{"invitation_id": str, "note": str, "created_at": str,
      "status": str, "accepted_at": str, ...}``. Pass D (intent
      recovery) scans for the intent-id marker in the ``note`` text.
      Pass H (Pillar D Week 3 reply detection per ADR-0027 D111) reads
      the ``status`` field (one of ``"pending"`` / ``"accepted"`` /
      ``"declined"`` / ``"withdrawn"``; absent treated as ``"pending"``
      for backwards-compat) + the optional ``accepted_at`` timestamp.
      Accepted invites that have not yet been classified emit
      ``li_invite_reply_received`` per ADR-0025 D96.

    * ``list_recent_conversations(limit)`` → list of dicts shaped
      ``{"thread_id": str, "messages": [{"body": str, "from_self": bool,
      "sent_at": str, "message_id": str, ...}, ...], ...}``. Pass E
      (intent recovery) scans for the intent-id marker in any
      ``from_self=True`` message body. Pass I (Pillar D Week 3 reply
      detection per ADR-0027 D111) iterates ``from_self=False``
      (inbound) messages on conversations whose ``thread_id`` matches
      a known ``li_dm_confirmed.linkedin_thread_id`` from the ledger;
      each inbound message emits ``li_dm_reply_received`` once
      (idempotence keyed by the per-message ``message_id``).

    All methods accept a ``limit`` argument bounding the number of
    items the LinkedIn surface returns (default LINKEDIN_DEFAULT_SCAN_LIMIT
    per ADR-0017 D49). All methods may raise any Exception — the pass
    catches + records in result.errors rather than propagating, so a
    LinkedIn outage doesn't break the broader reconcile run.

    Unknown / extra fields on returned dicts are forward-compatible —
    the passes only read the fields named above. Per-message
    ``message_id`` may be absent on older MCP backends; Pass I falls
    back to a deterministic synthesized id (``thread_id:sent_at:idx``)
    for idempotence keying when absent.
    """

    def list_sent_invitations(
        self, limit: int = LINKEDIN_DEFAULT_SCAN_LIMIT,
    ) -> list[dict]:
        """Return recent sent connection invitations (note text + id + status)."""

    def list_recent_conversations(
        self, limit: int = LINKEDIN_DEFAULT_SCAN_LIMIT,
    ) -> list[dict]:
        """Return recent conversations (thread_id + messages array)."""


class TwitterClientLike(Protocol):
    """Duck-typed subset of a Twitter client that reconcile Pass F / J need.

    Per ADR-0018 D59 (Pass F intent recovery) + ADR-0027 D111 (Pass J
    DM reply detection), the real adapter wraps a cookie-scrape MCP
    surface (`mcp__scraplingserver__*` shape — or any equivalent the
    operator's environment exposes). Tests inject fakes. The single
    method covers both passes:

    * ``list_recent_dms(limit)`` → list of dicts shaped
      ``{"thread_id": str, "messages": [{"body": str, "from_self": bool,
      "sent_at": str, "message_id": str, ...}, ...], ...}``. Pass F
      (intent recovery) scans for the intent-id marker in any
      ``from_self=True`` message body in the conversation. Pass J
      (Pillar D Week 3 reply detection per ADR-0027 D111) iterates
      ``from_self=False`` (inbound) messages on conversations whose
      ``thread_id`` matches a known ``tw_dm_confirmed.
      twitter_thread_id`` from the ledger; each inbound message emits
      ``tw_dm_reply_received`` once (idempotence keyed by the per-
      message ``message_id``).

    The method accepts a ``limit`` argument bounding the number of items
    the Twitter surface returns (default TWITTER_DEFAULT_SCAN_LIMIT per
    ADR-0018 D58). The method may raise any Exception — the pass catches
    + records in result.errors rather than propagating, so a Twitter
    outage doesn't break the broader reconcile run.

    Unknown / extra fields on returned dicts are forward-compatible —
    the passes only read the fields named above. Per-message
    ``message_id`` may be absent on older MCP backends; Pass J falls
    back to a deterministic synthesized id (``thread_id:sent_at:idx``)
    for idempotence keying when absent.

    The dispatcher (``gated_tw_dm_one`` in
    ``send_queued.py``) uses a different method on the same adapter:
    ``send_dm(twitter_handle: str, message: str, intent_id: str) ->
    str | None`` which returns an optional thread_id on success. The
    dispatcher's signature is NOT part of this Protocol because Pass F
    + Pass J are read-only; the live dispatcher's wider-surface
    adapter satisfies both via duck typing.
    """

    def list_recent_dms(
        self, limit: int = TWITTER_DEFAULT_SCAN_LIMIT,
    ) -> list[dict]:
        """Return recent DM conversations (thread_id + messages array)."""


# ---------------------------------------------------------------------------
# Pass result types
# ---------------------------------------------------------------------------


@dataclass
class PassResult:
    """What one pass observed and what it wrote (or would write)."""

    pass_name: str
    examined: int = 0
    synthesized: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for e in self.synthesized:
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        for f in self.findings:
            tag = f.get("kind", "finding")
            counts[tag] = counts.get(tag, 0) + 1
        return {
            "pass": self.pass_name,
            "examined": self.examined,
            "by_type": counts,
            "errors": len(self.errors),
        }


@dataclass
class ReconcileResult:
    """Aggregate output across all passes invoked in one run."""

    ran_at: str
    apply: bool
    passes: list[PassResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ran_at": self.ran_at,
            "apply": self.apply,
            "passes": [p.summary() for p in self.passes],
            "synthesized": [s for p in self.passes for s in p.synthesized],
            "findings": [f for p in self.passes for f in p.findings],
            "errors": [e for p in self.passes for e in p.errors],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _headers_dict(msg: dict | None) -> dict[str, str]:
    """Flatten Gmail payload.headers list-of-{name,value} into a lowercased dict."""
    if not msg:
        return {}
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or msg.get("headers") or []
    out: dict[str, str] = {}
    for h in headers:
        name = (h.get("name") or "").lower()
        if name and name not in out:
            out[name] = h.get("value") or ""
    return out


def _message_body_text(msg: dict | None) -> str:
    """Best-effort plain-text body extraction for footer-marker search.

    Tests pass `body` directly; real Gmail responses have a nested
    payload.parts structure with base64url bodies. Tolerant: returns "" on
    anything weird.
    """
    if not msg:
        return ""
    if isinstance(msg.get("body"), str):
        return msg["body"]
    payload = msg.get("payload") or {}
    snippet = msg.get("snippet") or ""
    parts: list[str] = []
    if snippet:
        parts.append(snippet)
    for part in (payload.get("parts") or []):
        body = part.get("body") or {}
        data = body.get("data")
        if isinstance(data, str):
            parts.append(data)  # not base64-decoded; ULIDs are ASCII so search still works
    body = (payload.get("body") or {}).get("data")
    if isinstance(body, str):
        parts.append(body)
    return "\n".join(parts)


def _ledger_dir_default() -> Path:
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _ledger.DEFAULT_LEDGER_DIR


def _reconcile_dir_default() -> Path:
    env = os.environ.get("OUTREACH_FACTORY_RECONCILE_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return DEFAULT_RECONCILE_DIR


def _safe_append(led: _ledger.Ledger, event: dict, errors: list[str]) -> dict | None:
    try:
        return led.append(event)
    except (OSError, ValueError) as exc:
        msg = f"ledger append failed for {event.get('type')}: {exc}"
        print(f"WARNING: reconcile: {msg}", file=sys.stderr)
        errors.append(msg)
        return None


# ---------------------------------------------------------------------------
# Pass A — Ledger ↔ Gmail (intent recovery)
# ---------------------------------------------------------------------------


def _search_intent(gmail: GmailClientLike, intent_id: str) -> dict | None:
    """Locate the Gmail message stamped with this intent_id.

    Strategy: query Gmail for the bare ULID. The ULID is intentionally
    unique enough to disambiguate without false positives, and it lives in
    both the custom header AND the body footer (defense in depth — Gmail's
    custom-header search has known quirks per Phase 5.5 risk list).

    Tiebreak: if multiple hits come back (shouldn't happen, but be safe),
    prefer the one whose body OR headers actually contain the intent_id.
    """
    try:
        hits = gmail.search_messages(f'"{intent_id}"', max_results=5)
    except Exception as exc:
        print(f"WARNING: Gmail search failed for {intent_id}: {exc}",
              file=sys.stderr)
        return None
    if not hits:
        return None
    for hit in hits:
        msg_id = hit.get("id")
        if not msg_id:
            continue
        msg = gmail.get_message(msg_id)
        if not msg:
            continue
        headers = _headers_dict(msg)
        body = _message_body_text(msg)
        if intent_id in headers.get("x-outreach-intent-id", ""):
            return msg
        if intent_id in body:
            return msg
    # Fall back to the first hit even if we couldn't reverify — better to
    # confirm with caveat than to abort the recovery.
    first = hits[0]
    msg_id = first.get("id")
    return gmail.get_message(msg_id) if msg_id else None


def run_pass_a(
    *,
    led: _ledger.Ledger,
    gmail: GmailClientLike,
    since: datetime,
    apply: bool,
    min_intent_age: timedelta = DEFAULT_MIN_INTENT_AGE,
    now: datetime | None = None,
) -> PassResult:
    """Recover orphaned send_intents by querying Gmail.

    Per ADR-0014 D33 the ledger's ``open_intents`` index now contains
    every channel's intent types (``send_intent`` /
    ``li_invite_intent`` / ``li_dm_intent`` / ``tw_dm_intent`` /
    ``calendar_booking_intent``). Pass A is the email-channel recovery
    surface — it must filter to ``channel="email"`` or it would
    synthesize wrong-typed ``send_aborted`` events for LinkedIn /
    Twitter / Calendar orphans (the cross-channel rule would then see
    a ``send_aborted`` with ``channel: linkedin`` — meaningless, but
    a real bug). The filter matches Pass D / E / F's discipline (each
    pass scopes ``open_intents`` to its own channel + intent type
    per ADR-0018 D62's helper generalization). Pillar C Week 12
    exit-criterion test surfaced the missing filter.
    """
    result = PassResult(pass_name="A")
    now = now or datetime.now(timezone.utc)
    open_intents = led.open_intents(
        since=since, channel="email", min_age=min_intent_age,
    )
    result.examined = len(open_intents)

    for intent in open_intents:
        iid = intent.intent_id
        if not iid:
            continue
        try:
            msg = _search_intent(gmail, iid)
        except Exception as exc:
            result.errors.append(f"{iid}: search exception: {exc}")
            continue

        if msg is not None:
            headers = _headers_dict(msg)
            event = {
                "type": "send_confirmed",
                "intent_id": iid,
                "person_id": intent.person_id,
                "channel": intent.get("channel") or "email",
                "gmail_message_id": msg.get("id"),
                "gmail_thread_id": msg.get("threadId") or msg.get("thread_id"),
                "_recovered_by": "reconcile",
            }
            # Carry recipient back for cross-reference.
            to_header = headers.get("to")
            if to_header:
                event["recipient_header"] = to_header
        else:
            # Decide: send_aborted (never made it) vs leave-open (still in grace).
            try:
                intent_ts = datetime.fromisoformat(
                    (intent.ts or "").replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                intent_ts = None
            if intent_ts and (now - intent_ts) < min_intent_age:
                continue  # too young; reconcile again later
            event = {
                "type": "send_aborted",
                "intent_id": iid,
                "person_id": intent.person_id,
                "channel": intent.get("channel") or "email",
                "reason": "no_gmail_match_after_5min",
                "_recovered_by": "reconcile",
            }

        if apply:
            written = _safe_append(led, event, result.errors)
            if written is not None:
                result.synthesized.append(written)
        else:
            event["_dry_run"] = True
            result.synthesized.append(event)
    return result


# ---------------------------------------------------------------------------
# Pass B — Inbox ↔ Ledger (replies + bounces)
# ---------------------------------------------------------------------------


def _classify_inbound(msg: dict, our_email: str | None) -> str | None:
    """Return 'bounce', 'reply', or None if the message is our own outbound."""
    headers = _headers_dict(msg)
    from_h = headers.get("from", "")
    if our_email and our_email.lower() in from_h.lower():
        return None
    subject = headers.get("subject", "")
    if DSN_FROM_RE.search(from_h):
        return "bounce"
    if DSN_SUBJECT_RE.search(subject) and "Re:" not in subject:
        # Bounces sometimes come from domain MTAs, not just mailer-daemon.
        return "bounce"
    return "reply"


def run_pass_b(
    *,
    led: _ledger.Ledger,
    gmail: GmailClientLike,
    since: datetime,
    apply: bool,
) -> PassResult:
    """Walk confirmed sends in the window, classify any inbound thread traffic.

    Emits ``reply_received`` and ``bounce_detected`` events with
    ``channel: "email"`` per ADR-0025 D96 (Pillar D Week 1 extension of
    ADR-0014 D33's channel-on-every-event invariant to reply / bounce
    events). The classifier (Pillar D Week 2+) consumes ``channel`` to
    discriminate per-channel reply detection — without it on email
    replies the classifier would have to special-case "absent = email".
    Mirrors the ADR-0014 D33 §"Backfill send_confirmed carries channel"
    foundation-week fix pattern. Pre-Pillar-D-Week-1 reply events lack
    the field; Pillar D's classifier treats absent-channel as ``email``
    per the historical default (ADR-0025 §Migration/rollout item 3).
    """
    result = PassResult(pass_name="B")
    since_iso = (
        since.isoformat() if since.tzinfo
        else since.replace(tzinfo=timezone.utc).isoformat()
    )

    # Collect (thread_id, originating send_confirmed) for the window. Dedup
    # by thread so a thread with multiple sends only fetches once.
    confirmed_by_thread: dict[str, dict] = {}
    for e in led.all_events():
        if e.type != "send_confirmed":
            continue
        if (e.ts or "") < since_iso:
            continue
        tid = e.get("gmail_thread_id")
        if not tid:
            continue
        # If multiple sends on same thread, keep the earliest — that's the
        # one whose person_id originally owned the conversation.
        prior = confirmed_by_thread.get(tid)
        if prior is None or (e.ts or "") < (prior.get("ts") or ""):
            confirmed_by_thread[tid] = e.to_dict()
    result.examined = len(confirmed_by_thread)

    our_email = getattr(gmail, "sender_email", None)

    for tid, send_ev in confirmed_by_thread.items():
        try:
            thread = gmail.get_thread(tid)
        except Exception as exc:
            result.errors.append(f"thread {tid}: get exception: {exc}")
            continue
        if not thread:
            continue
        person_id = send_ev.get("person_id")
        our_msg_id = send_ev.get("gmail_message_id")

        for msg in thread.get("messages", []) or []:
            mid = msg.get("id")
            if not mid or mid == our_msg_id:
                continue
            # Idempotency: skip messages already in the ledger.
            if led.query_by_gmail_message_id(mid) is not None:
                continue
            kind = _classify_inbound(msg, our_email)
            if kind is None:
                continue
            headers = _headers_dict(msg)
            event_type = "bounce_detected" if kind == "bounce" else "reply_received"
            event = {
                "type": event_type,
                "person_id": person_id,
                # Pillar D Week 1 ADR-0025 D96 extends ADR-0014 D33's
                # channel-on-every-event invariant to reply / bounce events.
                # The pre-Pillar-D-Week-1 emit shape omitted this field;
                # Pillar D Week 2+ classifier consumes ``channel`` to
                # discriminate per-channel reply detection — without the
                # field on email replies the classifier would either
                # silently skip email replies or have to special-case
                # "absent = email" everywhere. Mirrors Pillar C Week 1's
                # ADR-0014 D33 §"Backfill send_confirmed carries channel"
                # foundation-week fix pattern. Pinned by
                # ``tests/test_reconcile.py::TestPassB`` regression rows.
                "channel": "email",
                "gmail_message_id": mid,
                "gmail_thread_id": tid,
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "_recovered_by": "reconcile",
            }
            if apply:
                written = _safe_append(led, event, result.errors)
                if written is not None:
                    result.synthesized.append(written)
            else:
                event["_dry_run"] = True
                result.synthesized.append(event)
    return result


# ---------------------------------------------------------------------------
# Pass C — Vault ↔ Ledger (denormalized-view heal)
# ---------------------------------------------------------------------------


def _read_pipeline_stage(note_path: Path) -> tuple[str | None, str]:
    """Return (pipeline_stage_or_None, full_text). full_text returned so the
    caller can do a surgical writeback without a second read."""
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return None, ""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    try:
        fm = yaml.safe_load(text[3:end].lstrip("\n"))
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    val = fm.get("pipeline_stage")
    return (str(val).strip() if val else None), text


def _read_conversation_status(note_path: Path) -> str | None:
    """Return the ``conversation_status:`` value from a Person note,
    or None if absent / unparseable.

    Per ADR-0028 D119 — the per-Person denormalized view of the
    conversation state machine's per-thread states. Pass C heals this
    field analogous to the existing ``pipeline_stage:`` heal.
    """
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end].lstrip("\n"))
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    val = fm.get("conversation_status")
    return str(val).strip() if val else None


def _write_pipeline_stage(note_path: Path, new_stage: str) -> None:
    """Surgical writeback of pipeline_stage in YAML frontmatter.

    Preserves comments + ordering of every other field. If the field is
    absent, appends it at the end of the frontmatter block.
    """
    text = note_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"no YAML frontmatter in {note_path}")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"unterminated frontmatter in {note_path}")
    fm_text = text[4:end]
    pattern = re.compile(r"^pipeline_stage:\s*.*$", re.MULTILINE)
    if pattern.search(fm_text):
        fm_text = pattern.sub(f"pipeline_stage: {new_stage}", fm_text)
    else:
        fm_text = fm_text.rstrip("\n") + f"\npipeline_stage: {new_stage}"
    note_path.write_text(text[:4] + fm_text + text[end:], encoding="utf-8")


def _write_conversation_status(note_path: Path, new_status: str) -> None:
    """Surgical writeback of ``conversation_status:`` in YAML frontmatter.

    Per ADR-0028 D119 — the per-Person denormalized conversation-state
    field. Same surgical-edit pattern as :func:`_write_pipeline_stage`;
    preserves comments + ordering of every other field. If the field
    is absent, appends it at the end of the frontmatter block.
    """
    text = note_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"no YAML frontmatter in {note_path}")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"unterminated frontmatter in {note_path}")
    fm_text = text[4:end]
    pattern = re.compile(r"^conversation_status:\s*.*$", re.MULTILINE)
    if pattern.search(fm_text):
        fm_text = pattern.sub(
            f"conversation_status: {new_status}", fm_text,
        )
    else:
        fm_text = fm_text.rstrip("\n") + f"\nconversation_status: {new_status}"
    note_path.write_text(text[:4] + fm_text + text[end:], encoding="utf-8")


def _walk_people_dir(people_dir: Path) -> Iterable[Path]:
    for note in sorted(people_dir.rglob("*.md")):
        rel = note.relative_to(people_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ".conflicted" in note.name or note.name.endswith(".conflict.md"):
            continue
        yield note


# Closed-set of ``reconcile_drift`` ``reason`` values for the per-Pass-C
# drift surfaces. Pillar G observability dashboards + Pillar I per-tenant
# audit-tooling consume ``reconcile_drift`` events filtered by ``reason``
# per ADR-0049 D263; this frozenset is the regression-barrier against
# future contributors adding a NEW ``reason`` value without ADR
# coordination. A new value MUST extend this frozenset + the consumer
# surface migration MUST document at the ADR that adds it.
_DRIFT_REASONS: frozenset[str] = frozenset({
    # Pass C pipeline_stage heal — vault has a stage, ledger has none.
    "vault_has_stage_but_ledger_empty",
    # Pass C pipeline_stage heal — vault claims a more-advanced stage
    # than ledger can justify (v_rank > l_rank).
    "vault_ahead_of_ledger",
})


def run_pass_c(
    *,
    led: _ledger.Ledger,
    people_dir: Path,
    apply: bool,
) -> PassResult:
    """Heal vault frontmatter from ledger; flag unsafe drift.

    Per ADR-0011 + ADR-0028 D119 — Pass C now heals TWO denormalized
    frontmatter fields:

    * ``pipeline_stage:`` per ``Ledger.derived_stage(person_id)``
      (Phase 5.5 surface). Drift in safe direction → heal; drift in
      unsafe direction → ``reconcile_drift`` finding.

    * ``conversation_status:`` per
      ``conversation_state.derived_conversation_status(person_id)``
      (Pillar D Week 4-5 — ADR-0028 D119). Drift heals to the ledger-
      derived value; absent field → stamp; field already matching →
      no-op. The conversation state machine's per-thread emit chain
      is fully ledger-derived; vault drift in either direction heals
      to the ledger's canonical aggregate (the operator may have
      hand-edited but the ledger is the SoT per I1).

    The two heals share one per-Person walk so vault rewrites are
    batched (one write per Person with both fields changed, not two
    writes).
    """
    # Per ADR-0055 D301 — wrap Pass C in a review-stage span so the
    # heal-pass is operator-visible via the OTel tracing backend.
    # Pass C is per-Person heal-pass; the per-Person attributes flow
    # through the inner
    # per-Person operations via the standard Pillar A-F event
    # emission surfaces (the per-Person ``reconcile_drift`` /
    # ``reconcile_healed`` events carry the ``person_id`` field).
    with traced_stage("review", "reconcile_pass_c"):
        return _run_pass_c_inner(
            led=led, people_dir=people_dir, apply=apply,
        )


def _run_pass_c_inner(
    *,
    led: _ledger.Ledger,
    people_dir: Path,
    apply: bool,
) -> PassResult:
    """Internal body of :func:`run_pass_c` — wrapped by the public
    function with a ``traced_stage`` context per ADR-0055 D301.
    Splitting the body keeps the span wrapping cleanly delimited
    without indenting ~250 lines of existing logic."""
    result = PassResult(pass_name="C")
    if not people_dir.exists():
        result.errors.append(f"people_dir does not exist: {people_dir}")
        return result

    # Per ADR-0028 D119 — precompute the conversation-state map ONCE
    # for this Pass C run, then query per-Person. Saves O(N persons *
    # full-ledger-walk) re-computation that ``derived_conversation_
    # status`` would otherwise do (the function walks the full ledger
    # per call when called without a precomputed map).
    thread_states = _conversation_state.compute_thread_states(led)

    for note in _walk_people_dir(people_dir):
        parsed = identity.read_person_keys(note)
        if parsed is None:
            continue
        person_id, _keys = parsed
        if not person_id:
            continue
        result.examined += 1

        # Per ADR-0028 D119 — conversation_status heal. Runs alongside
        # the pipeline_stage heal so vault-write batching is per-
        # Person (one read + one write for both fields when both
        # drift).
        ledger_conv_status = _conversation_state.derived_conversation_status(
            led, person_id, thread_states=thread_states,
        )
        vault_conv_status = _read_conversation_status(note)
        if ledger_conv_status is not None and vault_conv_status != ledger_conv_status:
            if apply:
                try:
                    _write_conversation_status(note, ledger_conv_status)
                except (OSError, ValueError) as exc:
                    result.errors.append(
                        f"vault conversation_status write failed for "
                        f"{note}: {exc}"
                    )
                else:
                    _safe_append(led, {
                        "type": "reconcile_healed",
                        "person_id": person_id,
                        "note_path": str(note),
                        "field": "conversation_status",
                        "from": vault_conv_status,
                        "to": ledger_conv_status,
                    }, result.errors)
                    result.synthesized.append({
                        "type": "reconcile_healed",
                        "person_id": person_id,
                        "field": "conversation_status",
                        "from": vault_conv_status,
                        "to": ledger_conv_status,
                    })
            else:
                result.findings.append({
                    "kind": "would_heal_conversation_status",
                    "person_id": person_id,
                    "note_path": str(note),
                    "from": vault_conv_status,
                    "to": ledger_conv_status,
                })

        vault_stage, _ = _read_pipeline_stage(note)
        ledger_stage = led.derived_stage(person_id)

        v_rank = STAGE_RANK.get(vault_stage or "", -1)
        l_rank = STAGE_RANK.get(ledger_stage or "", -1)

        if ledger_stage is None and vault_stage is None:
            continue
        if vault_stage == ledger_stage:
            continue

        if ledger_stage is None:
            # Vault has a stage; ledger has nothing. Don't heal — the user
            # may have set this manually and the ledger lacks history.
            _reason = "vault_has_stage_but_ledger_empty"
            assert _reason in _DRIFT_REASONS  # per Week 12 follow-up P3-4
            finding = {
                "kind": "reconcile_drift",
                "person_id": person_id,
                "note_path": str(note),
                "vault_stage": vault_stage,
                "ledger_stage": None,
                "conflict": True,
                "reason": _reason,
            }
            result.findings.append(finding)
            if apply:
                _safe_append(led, {
                    "type": "reconcile_drift",
                    "person_id": person_id,
                    "note_path": str(note),
                    "vault_stage": vault_stage,
                    "ledger_stage": None,
                    "conflict": True,
                    "reason": _reason,
                }, result.errors)
            continue

        if l_rank >= v_rank:
            # Safe direction — ledger ahead of or equal-rank-but-different
            # from vault. Heal.
            if apply:
                try:
                    _write_pipeline_stage(note, ledger_stage)
                except (OSError, ValueError) as exc:
                    result.errors.append(
                        f"vault write failed for {note}: {exc}"
                    )
                    continue
                _safe_append(led, {
                    "type": "reconcile_healed",
                    "person_id": person_id,
                    "note_path": str(note),
                    "from": vault_stage,
                    "to": ledger_stage,
                }, result.errors)
                result.synthesized.append({
                    "type": "reconcile_healed",
                    "person_id": person_id,
                    "from": vault_stage, "to": ledger_stage,
                })
            else:
                result.findings.append({
                    "kind": "would_heal",
                    "person_id": person_id,
                    "note_path": str(note),
                    "from": vault_stage,
                    "to": ledger_stage,
                })
        else:
            # Vault claims a more-advanced stage than the ledger can justify.
            # Conflict: do NOT auto-heal. Surface for manual review.
            _reason = "vault_ahead_of_ledger"
            assert _reason in _DRIFT_REASONS  # per Week 12 follow-up P3-4
            finding = {
                "kind": "reconcile_drift",
                "person_id": person_id,
                "note_path": str(note),
                "vault_stage": vault_stage,
                "ledger_stage": ledger_stage,
                "conflict": True,
                "reason": _reason,
            }
            result.findings.append(finding)
            if apply:
                _safe_append(led, {
                    "type": "reconcile_drift",
                    "person_id": person_id,
                    "note_path": str(note),
                    "vault_stage": vault_stage,
                    "ledger_stage": ledger_stage,
                    "conflict": True,
                    "reason": _reason,
                }, result.errors)
    return result


# ---------------------------------------------------------------------------
# Pass D — Ledger ↔ LinkedIn invitations (per ADR-0017)
# ---------------------------------------------------------------------------


def _scan_li_invitations_for_marker(
    invitations: list[dict], intent_id: str,
) -> dict | None:
    """Return the first invitation whose note text contains the marker.

    The marker shape (ADR-0015 D39) is the ULID intent_id wrapped in
    zero-width spaces inside the connection note text. We don't compare
    against the zero-width spaces directly; the substring check on the
    bare intent_id is sufficient because the ULID's collision-resistance
    makes false-positives effectively impossible. Falls back to
    CHANNEL_INTENT_MARKER_RE if the operator pasted the marker token
    without surrounding ZWS (e.g. note was hand-edited post-send).
    """
    for inv in invitations:
        note = inv.get("note") or ""
        if not isinstance(note, str):
            continue
        if intent_id in note:
            return inv
        # Defense in depth: extract any intent-id markers from the note
        # via the regex and compare. Catches edge cases like manually
        # truncated notes where the ZWS got stripped.
        for match in CHANNEL_INTENT_MARKER_RE.finditer(note):
            if match.group(1) == intent_id:
                return inv
    return None


def _intent_age_or_none(
    intent: _ledger.Event, now: datetime,
) -> timedelta | None:
    """Return age of intent or None if its ts is unparseable."""
    try:
        intent_ts = datetime.fromisoformat(
            (intent.ts or "").replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None
    return now - intent_ts


def run_pass_d(
    *,
    led: _ledger.Ledger,
    linkedin: LinkedInClientLike,
    since: datetime,
    apply: bool,
    min_intent_age: timedelta = DEFAULT_MIN_INTENT_AGE,
    scan_limit: int = LINKEDIN_DEFAULT_SCAN_LIMIT,
    now: datetime | None = None,
) -> PassResult:
    """Recover orphaned ``li_invite_intent`` events by querying LinkedIn.

    Per ADR-0017 (Pillar C Week 4):

    * Walks ``li_invite_intent`` events within the window that lack a
      matching outcome event (``_confirmed | _failed | _aborted``).
    * Pre-fetches one batch of sent invitations from the LinkedIn client
      (per D49's marker-scan window — default 100).
    * For each orphan intent, scans the batch for an invitation whose
      ``note`` contains the intent-id marker (ADR-0015 D39 zero-width-
      Unicode shape; per ``_scan_li_invitations_for_marker``).
    * Marker match → emit ``li_invite_confirmed`` with
      ``_recovered_by: "reconcile"`` + ``channel: "linkedin"`` per
      ADR-0014 D33. Stamp the invitation's ``invitation_id`` field as
      ``linkedin_invitation_id`` when present, so Pillar D's reply-
      correlator doesn't have to re-query.
    * No marker match AND intent older than ``min_intent_age`` (per D50's
      asymmetric-failure-cost calculus — better to abort and let the
      operator retry than to leave the orphan stale) → emit
      ``li_invite_aborted`` with ``_recovered_by: "reconcile"`` +
      ``reason``. The cross-channel rule (ADR-0003) doesn't fire on
      ``_aborted`` events (only on ``_confirmed``), so an over-aborted
      intent doesn't double-engage the recipient.
    * No marker match AND intent younger than ``min_intent_age`` → skip
      (still in the normal send-completion grace window; reconcile again
      later).

    The LinkedIn batch is pre-fetched ONCE per Pass D invocation (not
    per-intent) to amortize the rate-limit cost across the orphan set.
    The fetch error (LinkedIn down, MCP rate-limit hit) is recorded in
    ``result.errors`` and the pass returns early with no emissions —
    a failed Pass D is safer than a partial Pass D that left some
    intents wrongly aborted.

    Parameters mirror ``run_pass_a`` for symmetry; the LinkedIn-specific
    ``scan_limit`` corresponds to D49's ``LINKEDIN_DEFAULT_SCAN_LIMIT``.
    """
    return _run_channel_intent_pass(
        pass_name="D",
        channel="linkedin",
        intent_type="li_invite_intent",
        confirmed_type="li_invite_confirmed",
        aborted_type="li_invite_aborted",
        led=led,
        fetch_batch=lambda: linkedin.list_sent_invitations(limit=scan_limit),
        extract_marker_match=_scan_li_invitations_for_marker,
        result_correlate_field="linkedin_invitation_id",
        result_source_field="invitation_id",
        carry_intent_field=("linkedin_url", "linkedin_url"),
        since=since,
        apply=apply,
        min_intent_age=min_intent_age,
        now=now,
        aborted_reason_prefix="no_linkedin_invitation_match",
    )


# ---------------------------------------------------------------------------
# Pass E — Ledger ↔ LinkedIn conversations (per ADR-0017)
# ---------------------------------------------------------------------------


def _scan_li_conversations_for_marker(
    conversations: list[dict], intent_id: str,
) -> dict | None:
    """Return the first conversation whose self-sent message body contains
    the marker.

    Walks each conversation's ``messages`` array; for each message marked
    ``from_self: True`` (i.e. sent by the operator, not by the recipient),
    checks for the intent-id substring + regex fallback. Returns a dict
    shaped like ``{"thread_id": ..., "message": <matched msg>}`` so the
    caller can stamp both the LinkedIn thread id AND any per-message
    correlation field.
    """
    for conv in conversations:
        tid = conv.get("thread_id")
        for msg in (conv.get("messages") or []):
            if not isinstance(msg, dict):
                continue
            # If the conversation surface doesn't tag from_self,
            # default to considering every message (the marker is
            # collision-resistant; cross-side false positives are
            # vanishingly unlikely because the ULID was generated
            # by the operator's intent).
            if "from_self" in msg and msg.get("from_self") is False:
                continue
            body = msg.get("body") or ""
            if not isinstance(body, str):
                continue
            if intent_id in body:
                return {"thread_id": tid, "message": msg}
            for match in CHANNEL_INTENT_MARKER_RE.finditer(body):
                if match.group(1) == intent_id:
                    return {"thread_id": tid, "message": msg}
    return None


def run_pass_e(
    *,
    led: _ledger.Ledger,
    linkedin: LinkedInClientLike,
    since: datetime,
    apply: bool,
    min_intent_age: timedelta = DEFAULT_MIN_INTENT_AGE,
    scan_limit: int = LINKEDIN_DEFAULT_SCAN_LIMIT,
    now: datetime | None = None,
) -> PassResult:
    """Recover orphaned ``li_dm_intent`` events by querying LinkedIn.

    Per ADR-0017, structurally near-identical to ``run_pass_d`` modulo:

    * Intent / outcome types: ``li_dm_intent`` / ``li_dm_confirmed`` /
      ``li_dm_aborted`` (per ADR-0014 D33 + ADR-0016 D43).
    * Fetched surface: recent conversations (not sent invitations).
    * Marker location: DM body text (not connection-note text); same
      marker shape per ADR-0016 D43 = ADR-0015 D39.
    * Correlation field stamped on the confirmed event: the conversation's
      ``thread_id`` becomes ``linkedin_thread_id`` (matching the live
      dispatcher's stamping per ADR-0016 D43; Pillar D's reply joiner
      reads it for cross-correlation).
    """
    return _run_channel_intent_pass(
        pass_name="E",
        channel="linkedin",
        intent_type="li_dm_intent",
        confirmed_type="li_dm_confirmed",
        aborted_type="li_dm_aborted",
        led=led,
        fetch_batch=lambda: linkedin.list_recent_conversations(limit=scan_limit),
        extract_marker_match=_scan_li_conversations_for_marker,
        result_correlate_field="linkedin_thread_id",
        result_source_field="thread_id",
        carry_intent_field=("linkedin_url", "linkedin_url"),
        since=since,
        apply=apply,
        min_intent_age=min_intent_age,
        now=now,
        aborted_reason_prefix="no_linkedin_dm_match",
    )


# ---------------------------------------------------------------------------
# Pass F — Ledger ↔ Twitter recent DMs (per ADR-0018)
# ---------------------------------------------------------------------------


def _scan_tw_conversations_for_marker(
    conversations: list[dict], intent_id: str,
) -> dict | None:
    """Return the first Twitter conversation whose self-sent message body
    contains the marker.

    Structurally identical to :func:`_scan_li_conversations_for_marker`
    modulo: the marker scheme is the SAME zero-width-Unicode marker per
    ADR-0018 D58 (which reaffirms ADR-0015 D39 + ADR-0016 D43). The
    Twitter cookie-scrape surface exposes a similar
    ``messages: [{body, from_self, sent_at}, ...]`` shape on each
    conversation; the function reuses :data:`CHANNEL_INTENT_MARKER_RE`
    (= INTENT_FOOTER_RE) for the regex fallback.

    Cloning the LinkedIn helper rather than calling it directly preserves
    the per-channel-MCP surface boundary (the Twitter shape may diverge
    from LinkedIn's in future MCP versions; the scan helpers are the
    structural surface boundary). The cloned body is trivially small —
    eight lines of iteration logic. Per ADR-0018 D62, the shared
    ``_run_channel_intent_pass`` core uses BOTH scan helpers via the
    parameterized ``extract_marker_match`` callable.
    """
    for conv in conversations:
        tid = conv.get("thread_id")
        for msg in (conv.get("messages") or []):
            if not isinstance(msg, dict):
                continue
            if "from_self" in msg and msg.get("from_self") is False:
                continue
            body = msg.get("body") or ""
            if not isinstance(body, str):
                continue
            if intent_id in body:
                return {"thread_id": tid, "message": msg}
            for match in CHANNEL_INTENT_MARKER_RE.finditer(body):
                if match.group(1) == intent_id:
                    return {"thread_id": tid, "message": msg}
    return None


def run_pass_f(
    *,
    led: _ledger.Ledger,
    twitter: TwitterClientLike,
    since: datetime,
    apply: bool,
    min_intent_age: timedelta = DEFAULT_MIN_INTENT_AGE,
    scan_limit: int = TWITTER_DEFAULT_SCAN_LIMIT,
    now: datetime | None = None,
) -> PassResult:
    """Recover orphaned ``tw_dm_intent`` events by querying Twitter.

    Per ADR-0018 (Pillar C Week 5):

    * Walks ``tw_dm_intent`` events within the window that lack a
      matching outcome event (``_confirmed | _failed | _aborted``).
    * Pre-fetches one batch of recent DMs from the Twitter client
      (per D58's marker-scan window — default
      :data:`TWITTER_DEFAULT_SCAN_LIMIT`).
    * For each orphan intent, scans the batch for a DM whose body
      contains the intent-id marker (ADR-0018 D58's zero-width-
      Unicode shape; per :func:`_scan_tw_conversations_for_marker`).
    * Marker match → emit ``tw_dm_confirmed`` with
      ``_recovered_by: "reconcile"`` + ``channel: "twitter"`` per
      ADR-0014 D33 + ADR-0018 D58. Stamp the conversation's
      ``thread_id`` as ``twitter_thread_id`` when present, so Pillar D's
      reply-correlator doesn't have to re-query.
    * No marker match AND intent older than ``min_intent_age`` (per
      ADR-0017 D50's asymmetric-failure-cost calculus — inherited by
      Pass F via the D62 helper generalization) → emit
      ``tw_dm_aborted`` with ``_recovered_by: "reconcile"`` +
      ``reason``. The cross-channel rule (ADR-0003) doesn't fire on
      ``_aborted`` events (only on ``_confirmed``), so an over-aborted
      intent doesn't double-engage the recipient.
    * No marker match AND intent younger than ``min_intent_age`` → skip
      (still in the normal send-completion grace window; reconcile
      again later).

    Per ADR-0018 D62, structurally identical to Pass D + Pass E via the
    generalized ``_run_channel_intent_pass`` helper. The only per-channel
    differences are the intent / outcome types, the fetch callable
    (Twitter's ``list_recent_dms`` instead of LinkedIn's
    ``list_recent_conversations``), the marker-scan callable, the
    intent-side field carry name (``twitter_handle`` instead of
    ``linkedin_url``), and the abort reason prefix.

    Per ADR-0018 D58 + D62 the Twitter MCP's rate-limit pool is distinct
    from LinkedIn's (cookie-scrape vs LinkedIn MCP — independent
    backends), so Pass F's serial execution after Pass E is by-convention
    (uniform operator-facing ordering) rather than by-rate-limit-pool.
    The daemon (Pillar H) is the right place to lift the serial
    convention to per-channel parallelism if it's needed later.
    """
    return _run_channel_intent_pass(
        pass_name="F",
        channel="twitter",
        intent_type="tw_dm_intent",
        confirmed_type="tw_dm_confirmed",
        aborted_type="tw_dm_aborted",
        led=led,
        fetch_batch=lambda: twitter.list_recent_dms(limit=scan_limit),
        extract_marker_match=_scan_tw_conversations_for_marker,
        result_correlate_field="twitter_thread_id",
        result_source_field="thread_id",
        carry_intent_field=("twitter_handle", "twitter_handle"),
        since=since,
        apply=apply,
        min_intent_age=min_intent_age,
        now=now,
        aborted_reason_prefix="no_twitter_dm_match",
    )


def _run_channel_intent_pass(
    *,
    pass_name: str,
    channel: str,
    intent_type: str,
    confirmed_type: str,
    aborted_type: str,
    led: _ledger.Ledger,
    fetch_batch: Callable[[], list[dict]],
    extract_marker_match: Callable[[list[dict], str], dict | None],
    result_correlate_field: str,
    result_source_field: str,
    carry_intent_field: tuple[str, str],
    since: datetime,
    apply: bool,
    min_intent_age: timedelta,
    now: datetime | None,
    aborted_reason_prefix: str,
) -> PassResult:
    """Shared core for Pass D + Pass E + Pass F (per ADR-0018 D62).

    Generalized from the prior ``_run_linkedin_intent_pass`` helper
    (ADR-0017 D48) to accommodate Twitter's distinct MCP surface +
    channel value. The seven parameterized dimensions cover every
    per-channel divergence point:

    * ``channel`` — the value stamped on every emitted event per
      ADR-0014 D33's channel-on-every-event invariant.
    * ``intent_type`` / ``confirmed_type`` / ``aborted_type`` — the
      event-type prefixes per channel.
    * ``fetch_batch`` — the per-channel MCP query (LinkedIn invites /
      conversations / Twitter DMs).
    * ``extract_marker_match`` — the per-channel surface scan helper.
    * ``result_correlate_field`` / ``result_source_field`` — the
      per-channel correlation-id field name + source key.
    * ``carry_intent_field`` — ``(intent_field_name,
      emitted_field_name)`` tuple naming a field on the intent event
      that carries forward to the confirmed event (LinkedIn URL,
      Twitter handle, etc.). Centralizes the "denormalize intent-side
      identifier" pattern that Pass D + Pass E both did inline.

    Per ADR-0017 D48 (now generalized): D + E execute serially because
    they share the LinkedIn MCP rate-limit pool. Pass F's serial
    execution after E is by-convention (Twitter's cookie-scrape pool is
    independent); the helper itself is concurrency-agnostic — the
    serial discipline lives at the orchestration layer (the for-loop in
    :func:`reconcile`).

    Per ADR-0017 D49: pre-fetch the batch ONCE per pass. A backend
    outage / rate-limit-hit at this step records the error and returns
    early — better to skip the pass than to abort intents that the
    backend simply didn't surface because of a transient outage.

    Per ADR-0017 D50 (now generalized): no marker match AND intent
    older than ``min_intent_age`` → emit ``aborted``; otherwise skip
    (still in grace window).
    """
    result = PassResult(pass_name=pass_name)
    now = now or datetime.now(timezone.utc)

    # Filter open intents to the per-channel type. led.open_intents
    # already filters by channel; we filter further by intent type
    # because each channel may have multiple two-phase types
    # (LinkedIn has both li_invite_* and li_dm_*; Twitter has only
    # tw_dm_* today but the per-type filter is forward-compatible
    # with a future tw_thread_mention_* per ADR-0018 D61's deferral).
    open_intents = [
        i for i in led.open_intents(
            since=since, channel=channel, min_age=timedelta(0),
        )
        if i.type == intent_type
    ]
    result.examined = len(open_intents)
    if not open_intents:
        return result

    # Per ADR-0017 D49: pre-fetch the most-recent N items ONCE per
    # pass. A backend outage / rate-limit-hit at this step records
    # the error and returns early.
    try:
        batch = fetch_batch()
    except Exception as exc:
        msg = (
            f"{channel} batch fetch failed for Pass {pass_name}: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"WARNING: reconcile: {msg}", file=sys.stderr)
        result.errors.append(msg)
        return result

    if not isinstance(batch, list):
        msg = (
            f"{channel} batch for Pass {pass_name} returned "
            f"non-list ({type(batch).__name__}); skipping pass."
        )
        print(f"WARNING: reconcile: {msg}", file=sys.stderr)
        result.errors.append(msg)
        return result

    intent_field_src, intent_field_emit = carry_intent_field

    for intent in open_intents:
        iid = intent.intent_id
        if not iid:
            continue

        try:
            matched = extract_marker_match(batch, iid)
        except Exception as exc:
            result.errors.append(
                f"{iid}: marker-scan exception in Pass {pass_name}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        if matched is not None:
            event = {
                "type": confirmed_type,
                "intent_id": iid,
                "person_id": intent.person_id,
                "channel": channel,
                "_recovered_by": "reconcile",
            }
            # Carry forward the intent-side identifier the dispatcher
            # stamped (LinkedIn URL / Twitter handle / etc.) so
            # downstream consumers (Pillar D / G) can correlate
            # without re-querying the origin.
            carry_val = intent.get(intent_field_src)
            if carry_val:
                event[intent_field_emit] = carry_val
            # Stamp the optional correlation id (invitation_id /
            # thread_id) when the source surface returned one. The
            # dispatcher's live success path uses the same field name
            # per ADR-0015 D39 / ADR-0016 D43 / ADR-0018 D58.
            source_value = matched.get(result_source_field)
            if source_value:
                event[result_correlate_field] = source_value
        else:
            # No marker match — decide abort-now vs leave-open by age.
            # Bad-ts intents are filtered upstream by led.open_intents
            # (its fromisoformat check skips them); the `age is None`
            # branch here is unreachable in practice but the original
            # `if age is not None and age < min_intent_age` shape kept
            # for symmetry with Pass A's defensive parse.
            age = _intent_age_or_none(intent, now)
            if age is not None and age < min_intent_age:
                continue  # too young; reconcile again later
            event = {
                "type": aborted_type,
                "intent_id": iid,
                "person_id": intent.person_id,
                "channel": channel,
                "reason": (
                    f"{aborted_reason_prefix}_after_"
                    f"{int(min_intent_age.total_seconds())}s"
                ),
                "_recovered_by": "reconcile",
            }

        if apply:
            written = _safe_append(led, event, result.errors)
            if written is not None:
                result.synthesized.append(written)
        else:
            event["_dry_run"] = True
            result.synthesized.append(event)
    return result


# ---------------------------------------------------------------------------
# Pass H — LinkedIn invite acceptance detection (Pillar D Week 3, ADR-0027)
# ---------------------------------------------------------------------------


def _li_invite_accept_reply_message_id(invitation_id: str) -> str:
    """Per ADR-0027 D112 — synthesize a stable reply_message_id for an
    accepted LinkedIn invite.

    LinkedIn invitation-acceptance is a connection-state change, NOT a
    message-with-id. The (reply_message_id, channel) idempotence pair
    per ADR-0026 D104 requires a deterministic discriminator per
    accepted invite. The synthesized token ``li_accept:<invitation_id>``
    satisfies the contract: the same invitation produces the same
    token across reruns (idempotence holds); distinct invitations
    produce distinct tokens (cross-prospect discrimination); the
    ``li_accept:`` prefix surface-reads as "this isn't a real message
    id" so future debuggers don't grep the LinkedIn API for a
    matching message.
    """
    return f"li_accept:{invitation_id}"


def run_pass_h(
    *,
    led: _ledger.Ledger,
    linkedin: LinkedInClientLike,
    since: datetime,
    apply: bool,
    scan_limit: int = LINKEDIN_DEFAULT_SCAN_LIMIT,
) -> PassResult:
    """Detect LinkedIn invitation acceptances; emit li_invite_reply_received.

    Per ADR-0027 D111 + ADR-0025 D96:

    * Walks ``li_invite_confirmed`` events in the window — these are
      the invites the operator has SENT (per Pass D / the dispatcher).
    * Pre-fetches ONE batch of sent invitations from the LinkedIn
      client (per ADR-0017 D49's marker-scan window — default
      :data:`LINKEDIN_DEFAULT_SCAN_LIMIT`).
    * For each ``li_invite_confirmed`` event, looks up the invitation
      in the batch by ``linkedin_invitation_id`` (stamped by Pass D
      or the live dispatcher per ADR-0017). If the invitation's
      ``status`` field is ``"accepted"`` AND no
      ``li_invite_reply_received`` for the (synthesized reply_message_id,
      "linkedin") pair exists in the ledger yet, emit
      ``li_invite_reply_received`` with:

        - ``channel: "linkedin"`` per ADR-0014 D33 + ADR-0025 D96
        - ``reply_message_id: li_accept:<invitation_id>``
        - ``reply_to_intent_id: <intent_id of the originating
          li_invite_intent>`` per ADR-0025 D96's reply-to-intent
          correlation contract
        - ``linkedin_invitation_id: <invitation_id>`` for cross-
          correlation with the originating event
        - ``person_id: <pid from the originating intent>``
        - ``_recovered_by: "reconcile"``
        - optional ``accepted_at`` from the LinkedIn surface

    Idempotence per ADR-0026 D104: Pass H walks the ledger for
    existing ``li_invite_reply_received`` events + builds a
    ``set[str]`` of synthesized message ids; reruns are no-ops.

    Defensive postures:
    * Fetch failure (LinkedIn down, MCP rate-limit hit) → record in
      ``result.errors`` + return early (better to skip the pass than
      to wrongly emit acceptances).
    * Invitation status absent or non-string → defaults to
      ``"pending"`` (no acceptance emit).
    * Invitation absent from the batch (operator's invitation older
      than ``scan_limit`` items) → no emit; the operator's manual
      re-check via a wider scan is the recovery surface.
    """
    result = PassResult(pass_name="H")
    since_iso = (
        since.isoformat() if since.tzinfo
        else since.replace(tzinfo=timezone.utc).isoformat()
    )

    # Build the candidate set: every li_invite_confirmed in the window
    # with a known linkedin_invitation_id.
    confirmed_by_invitation: dict[str, dict] = {}
    for e in led.all_events():
        if e.get("type") != "li_invite_confirmed":
            continue
        if (e.get("ts") or "") < since_iso:
            continue
        inv_id = e.get("linkedin_invitation_id")
        if not inv_id:
            continue
        # If duplicate (shouldn't happen — invitation_id is unique),
        # keep the EARLIEST (the original confirmation).
        prior = confirmed_by_invitation.get(inv_id)
        if prior is None or (e.get("ts") or "") < (prior.get("ts") or ""):
            confirmed_by_invitation[inv_id] = e.to_dict()
    result.examined = len(confirmed_by_invitation)

    if not confirmed_by_invitation:
        return result

    # Build the idempotence index per ADR-0026 D104 — the (reply_message_id,
    # channel) PAIR is the discriminator. Channel is always "linkedin"
    # within this pass's emit scope, but keying by the pair (not bare mid)
    # makes the pattern uniform with Pass G's index AND defends against a
    # future contributor adding a second LinkedIn invite-reply event type
    # (e.g., li_invite_withdrawn_reply_received) that would share the
    # invitation-id namespace if keyed by bare mid. Per the Week 3 per-week
    # reviewer's P2-A finding.
    already_emitted: set[tuple[str, str]] = set()
    for e in led.all_events():
        if e.get("type") != "li_invite_reply_received":
            continue
        mid = e.get("reply_message_id")
        ch = e.get("channel")
        if mid and ch:
            already_emitted.add((mid, ch))

    # Pre-fetch sent invitations ONCE per pass per ADR-0017 D49.
    try:
        batch = linkedin.list_sent_invitations(limit=scan_limit)
    except Exception as exc:
        msg = (
            f"linkedin batch fetch failed for Pass H: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"WARNING: reconcile: {msg}", file=sys.stderr)
        result.errors.append(msg)
        return result

    if not isinstance(batch, list):
        msg = (
            f"linkedin batch for Pass H returned non-list "
            f"({type(batch).__name__}); skipping pass."
        )
        print(f"WARNING: reconcile: {msg}", file=sys.stderr)
        result.errors.append(msg)
        return result

    # Index the batch by invitation_id for O(1) lookup per confirmed
    # event.
    batch_by_id: dict[str, dict] = {}
    for inv in batch:
        if not isinstance(inv, dict):
            continue
        inv_id = inv.get("invitation_id")
        if isinstance(inv_id, str) and inv_id:
            batch_by_id[inv_id] = inv

    for invitation_id, confirmed in confirmed_by_invitation.items():
        # The synthesized reply_message_id per ADR-0027 D112 — stable
        # per (invitation_id) so reruns idempotently skip.
        reply_mid = _li_invite_accept_reply_message_id(invitation_id)
        if (reply_mid, "linkedin") in already_emitted:
            continue

        live = batch_by_id.get(invitation_id)
        if live is None:
            # Invitation older than the scan window OR LinkedIn surface
            # doesn't return the record. No emit; the next Pass H run
            # (operator may widen --linkedin-scan-limit) retries.
            continue

        status = live.get("status")
        if not isinstance(status, str) or status.lower() != "accepted":
            continue

        event = {
            "type": "li_invite_reply_received",
            "person_id": confirmed.get("person_id"),
            "channel": "linkedin",
            "reply_message_id": reply_mid,
            "reply_to_intent_id": confirmed.get("intent_id"),
            "linkedin_invitation_id": invitation_id,
            "_recovered_by": "reconcile",
        }
        # Carry the optional accepted_at from the LinkedIn surface for
        # operator observability + Pillar G timeline rendering. Use the
        # full live record's accepted_at field; some MCP backends may
        # name the field differently (accepted_ts / acceptedAt / etc.).
        for key in ("accepted_at", "accepted_ts", "acceptedAt"):
            v = live.get(key)
            if isinstance(v, str) and v:
                event["accepted_at"] = v
                break

        if apply:
            written = _safe_append(led, event, result.errors)
            if written is not None:
                result.synthesized.append(written)
        else:
            event["_dry_run"] = True
            result.synthesized.append(event)
        # Defense-in-depth: mark seen in case the same invitation_id
        # appears twice in confirmed_by_invitation (shouldn't happen
        # but the defense holds).
        already_emitted.add((reply_mid, "linkedin"))
    return result


# ---------------------------------------------------------------------------
# Pass I — LinkedIn DM reply detection (Pillar D Week 3, ADR-0027)
# Pass J — Twitter DM reply detection (Pillar D Week 3, ADR-0027)
# ---------------------------------------------------------------------------


def _synthesize_dm_reply_message_id(
    thread_id: str, msg: dict, idx: int,
) -> str:
    """Per ADR-0027 D112 — fall-back deterministic id when the per-
    message MCP surface omits ``message_id``.

    Some MCP backends expose only ``{body, from_self, sent_at}`` on
    each conversation message. The (mid, channel) idempotence pair
    per ADR-0026 D104 requires a stable per-message discriminator;
    the synthesized form ``<thread_id>:<sent_at>:<idx>`` satisfies
    the contract:

    * ``thread_id`` — distinct across conversations.
    * ``sent_at`` — distinct across same-thread messages under normal
      operation (LinkedIn / Twitter clock resolution is per-second).
    * ``idx`` — a per-conversation positional index defends against
      same-second messages (rare; both within one second AND in the
      same conversation).

    The synthesized id is stable across Pass I / J reruns IFF the
    LinkedIn / Twitter surface returns messages in the same order
    + with the same sent_at (the MCP backend's invariant; the
    cookie-scrape adapter sorts by sent_at ascending).
    """
    sent_at = msg.get("sent_at") or ""
    return f"{thread_id}:{sent_at}:{idx}"


def run_pass_i(
    *,
    led: _ledger.Ledger,
    linkedin: LinkedInClientLike,
    since: datetime,
    apply: bool,
    scan_limit: int = LINKEDIN_DEFAULT_SCAN_LIMIT,
) -> PassResult:
    """Detect LinkedIn DM replies; emit li_dm_reply_received.

    Per ADR-0027 D111 + ADR-0025 D96. Walks ``li_dm_confirmed``
    events in the window to discover known LinkedIn thread ids;
    fetches recent conversations from the LinkedIn surface; for each
    conversation whose ``thread_id`` matches a known confirmed-DM
    thread, iterates inbound (``from_self: False``) messages + emits
    ``li_dm_reply_received`` per inbound message not already emitted.

    Idempotence per ADR-0026 D104 + ADR-0027 D112:
    The (reply_message_id, channel) pair is the discriminator. Pass I
    builds a ``set[str]`` of known reply_message_ids from existing
    ``li_dm_reply_received`` events (channel is always "linkedin"
    here so filtering by mid is sufficient). Reruns are no-ops.

    Defensive postures:
    * Fetch failure → record in errors + return early.
    * Conversation without ``thread_id`` or without ``messages`` →
      skipped (not malformed-enough to error; the missing data is
      informational).
    * Inbound message without per-message ``message_id`` → synthesized
      via :func:`_synthesize_dm_reply_message_id`.

    Per ADR-0027 D111, structurally identical to Pass J modulo the
    per-channel MCP surface — both share :func:`_run_channel_dm_reply_pass`.
    """
    return _run_channel_dm_reply_pass(
        pass_name="I",
        channel="linkedin",
        confirmed_type="li_dm_confirmed",
        confirmed_thread_field="linkedin_thread_id",
        reply_type="li_dm_reply_received",
        led=led,
        fetch_batch=lambda: linkedin.list_recent_conversations(limit=scan_limit),
        since=since,
        apply=apply,
    )


def run_pass_j(
    *,
    led: _ledger.Ledger,
    twitter: TwitterClientLike,
    since: datetime,
    apply: bool,
    scan_limit: int = TWITTER_DEFAULT_SCAN_LIMIT,
) -> PassResult:
    """Detect Twitter DM replies; emit tw_dm_reply_received.

    Per ADR-0027 D111. Structurally identical to Pass I via
    :func:`_run_channel_dm_reply_pass` modulo the per-channel MCP
    surface (Twitter's ``list_recent_dms`` instead of LinkedIn's
    ``list_recent_conversations``) + the confirmed-event type
    (``tw_dm_confirmed`` not ``li_dm_confirmed``) + the thread-id
    field name (``twitter_thread_id`` not ``linkedin_thread_id``).

    Per ADR-0018 D58 + ADR-0027 D111 the Twitter MCP's rate-limit
    pool is distinct from LinkedIn's (cookie-scrape vs LinkedIn MCP
    — independent backends), so Pass J's serial execution after Pass
    F is by-convention (uniform operator-facing ordering) rather
    than by-rate-limit-pool. The daemon (Pillar H) is the right
    place to lift the serial convention to per-channel parallelism
    if it's needed later.
    """
    return _run_channel_dm_reply_pass(
        pass_name="J",
        channel="twitter",
        confirmed_type="tw_dm_confirmed",
        confirmed_thread_field="twitter_thread_id",
        reply_type="tw_dm_reply_received",
        led=led,
        fetch_batch=lambda: twitter.list_recent_dms(limit=scan_limit),
        since=since,
        apply=apply,
    )


def _run_channel_dm_reply_pass(
    *,
    pass_name: str,
    channel: str,
    confirmed_type: str,
    confirmed_thread_field: str,
    reply_type: str,
    led: _ledger.Ledger,
    fetch_batch: Callable[[], list[dict]],
    since: datetime,
    apply: bool,
) -> PassResult:
    """Shared core for Pass I + Pass J (per ADR-0027 D111).

    Generalized analogue of :func:`_run_channel_intent_pass` for the
    reply-detection family (Pillar D Week 3). The five parameterized
    dimensions cover every per-channel divergence:

    * ``channel`` — the value stamped on every emitted reply event per
      ADR-0014 D33's channel-on-every-event invariant.
    * ``confirmed_type`` — ``li_dm_confirmed`` for Pass I,
      ``tw_dm_confirmed`` for Pass J. Walked to discover the set of
      thread_ids the operator has sent into.
    * ``confirmed_thread_field`` — the per-channel thread-id field
      name on the confirmed event (``linkedin_thread_id`` for Pass I,
      ``twitter_thread_id`` for Pass J — stamped by Pass E / F or
      the live dispatcher per ADR-0016 D43 / ADR-0018 D58).
    * ``reply_type`` — ``li_dm_reply_received`` for Pass I,
      ``tw_dm_reply_received`` for Pass J. The emit-event type.
    * ``fetch_batch`` — the per-channel MCP query
      (LinkedIn's ``list_recent_conversations`` vs Twitter's
      ``list_recent_dms``).

    Implementation contract:

    * Walks confirmed events in window → builds set of known
      thread_ids. Empty set → skip the MCP fetch (operator may run
      with no relevant conversations; no need to consume rate-limit
      budget on an empty set per ADR-0017 D49).
    * Fetches one batch from the MCP surface; failure recorded in
      result.errors + early return per ADR-0017 D50's asymmetric-
      failure-cost calculus.
    * Walks each conversation; for each in our known-threads set,
      iterates inbound messages + emits one reply event per inbound
      message not already in the ledger's idempotence set.
    * The reply event carries:
        - ``type: <reply_type>``
        - ``person_id`` from the originating confirmed event
        - ``channel: <channel>``
        - ``reply_message_id``: the per-message ``message_id`` from
          the MCP if present, else the synthesized
          ``<thread_id>:<sent_at>:<idx>`` per
          :func:`_synthesize_dm_reply_message_id`
        - ``reply_to_intent_id`` from the originating confirmed
          event's ``intent_id``
        - the per-channel thread-id field
          (``linkedin_thread_id`` or ``twitter_thread_id``)
        - ``from`` and ``snippet`` carry forward for downstream
          classifier consumption (the message body lives on the
          MCP; we denormalize a short snippet so the classifier can
          pattern-match without re-fetching)
        - ``_recovered_by: "reconcile"``
    """
    result = PassResult(pass_name=pass_name)
    since_iso = (
        since.isoformat() if since.tzinfo
        else since.replace(tzinfo=timezone.utc).isoformat()
    )

    # Build the known-threads map: thread_id → confirmed event dict
    # (so we can carry forward person_id + intent_id on emit).
    threads_to_confirmed: dict[str, dict] = {}
    for e in led.all_events():
        if e.get("type") != confirmed_type:
            continue
        if (e.get("ts") or "") < since_iso:
            continue
        tid = e.get(confirmed_thread_field)
        if not tid:
            continue
        prior = threads_to_confirmed.get(tid)
        if prior is None or (e.get("ts") or "") < (prior.get("ts") or ""):
            threads_to_confirmed[tid] = e.to_dict()

    result.examined = len(threads_to_confirmed)
    if not threads_to_confirmed:
        return result

    # Build the idempotence set per ADR-0026 D104 — the (reply_message_id,
    # channel) PAIR is the discriminator. Channel is uniform per pass (the
    # passed-in `channel` argument), but keying by the pair (not bare mid)
    # makes the pattern uniform with Pass G's index AND defends against a
    # future contributor adding a second reply event type on the same
    # channel that would share the message-id namespace. Per the Week 3
    # per-week reviewer's P2-A finding.
    already_emitted: set[tuple[str, str]] = set()
    for e in led.all_events():
        if e.get("type") != reply_type:
            continue
        mid = e.get("reply_message_id")
        ch = e.get("channel")
        if mid and ch:
            already_emitted.add((mid, ch))

    try:
        batch = fetch_batch()
    except Exception as exc:
        msg = (
            f"{channel} batch fetch failed for Pass {pass_name}: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"WARNING: reconcile: {msg}", file=sys.stderr)
        result.errors.append(msg)
        return result

    if not isinstance(batch, list):
        msg = (
            f"{channel} batch for Pass {pass_name} returned non-list "
            f"({type(batch).__name__}); skipping pass."
        )
        print(f"WARNING: reconcile: {msg}", file=sys.stderr)
        result.errors.append(msg)
        return result

    for conv in batch:
        if not isinstance(conv, dict):
            continue
        tid = conv.get("thread_id")
        if not tid or tid not in threads_to_confirmed:
            continue
        confirmed = threads_to_confirmed[tid]
        messages = conv.get("messages") or []
        if not isinstance(messages, list):
            continue
        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            # Inbound = NOT from_self. If the MCP backend doesn't
            # tag from_self, default to skipping (we can't tell who
            # sent the message; better to under-emit than to
            # incorrectly classify a self-message as a reply). This
            # is the inverse of Pass E/F's defensive default (which
            # was "treat absent from_self as candidate" for marker
            # scanning — different failure mode there).
            from_self = msg.get("from_self")
            if from_self is None or from_self is True:
                continue
            body = msg.get("body") or ""
            if not isinstance(body, str):
                body = ""

            mid_raw = msg.get("message_id")
            if isinstance(mid_raw, str) and mid_raw:
                reply_mid = mid_raw
            else:
                reply_mid = _synthesize_dm_reply_message_id(tid, msg, idx)

            if (reply_mid, channel) in already_emitted:
                continue

            event: dict = {
                "type": reply_type,
                "person_id": confirmed.get("person_id"),
                "channel": channel,
                "reply_message_id": reply_mid,
                "reply_to_intent_id": confirmed.get("intent_id"),
                confirmed_thread_field: tid,
                # The reply body (truncated to a snippet for the
                # classifier's pattern-match input + downstream
                # observability). Full body lives on the MCP; the
                # 500-char ceiling matches the cookie-scrape MCP's
                # typical per-message snippet length.
                "snippet": body[:500],
                "_recovered_by": "reconcile",
            }
            # Optional carry-forward from the MCP record.
            sender = msg.get("from") or msg.get("sender")
            if isinstance(sender, str) and sender:
                event["from"] = sender
            sent_at = msg.get("sent_at")
            if isinstance(sent_at, str) and sent_at:
                event["sent_at"] = sent_at

            if apply:
                written = _safe_append(led, event, result.errors)
                if written is not None:
                    result.synthesized.append(written)
            else:
                event["_dry_run"] = True
                result.synthesized.append(event)
            # Defense-in-depth: mark seen so a duplicate inbound
            # message within the same batch doesn't double-emit.
            already_emitted.add((reply_mid, channel))
    return result


# ---------------------------------------------------------------------------
# Pass G — Reply classification (Pillar D Week 2, ADR-0026; extended ADR-0027)
# ---------------------------------------------------------------------------


def _classifier_pattern_path_default() -> Path:
    """Per ADR-0026 D103 — the operator-tunable pattern file location.

    Operators bootstrap with ``cp config-template/unsubscribe-patterns.
    example.yml ~/.outreach-factory/classifier/unsubscribe-patterns.yml``.
    The classifier refuses-loud (PatternLoadError) when the file doesn't
    exist; the error message guides the bootstrap step.

    The ``OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH`` env var overrides
    for test injection + per-environment overrides (analogous to
    ``OUTREACH_FACTORY_LEDGER_DIR``).
    """
    env = os.environ.get("OUTREACH_FACTORY_CLASSIFIER_PATTERN_PATH")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _reply_classifier.DEFAULT_PATTERN_PATH


def run_pass_g(
    *,
    led: _ledger.Ledger,
    classifier: "_reply_classifier.RuleBasedClassifier",
    since: datetime,
    apply: bool,
) -> PassResult:
    """Classify reply events; emit reply_classified events.

    Per ADR-0025 D97 + ADR-0026 D104 + ADR-0027 D112 — walks every
    event whose type is in :data:`REPLY_EVENT_TYPES` (Week 2's
    ``reply_received`` + Week 3's ``li_invite_reply_received`` /
    ``li_dm_reply_received`` / ``tw_dm_reply_received``) in the
    window; for each event whose ``(reply_message_id, channel)`` pair
    does NOT yet have a paired ``reply_classified`` event, dispatches
    to the classifier + emits a ``reply_classified`` event
    correlating back to the originating reply.

    The classifier is rule-based per ADR-0026 D102; Week 2 shipped
    unsubscribe ONLY. Week 3 (ADR-0027 D108-D110) extends to the
    long-tail categories (ooo / wrong_person / interest / rejection)
    via per-category pattern lists. Non-matching replies emit
    ``category=uncategorized`` per ADR-0026 D107 (the visibility-
    without-action fallback).

    Idempotence-by-(reply_message_id, channel) per ADR-0026 D104:
    Pass G builds a ``set[tuple[str, str]]`` of pairs from existing
    ``reply_classified`` events + skips replies whose pair is in the
    set. Reruns are no-ops. The pair (not bare reply_message_id) is
    discriminative against per-channel message-id namespace collisions
    that could land if a future LinkedIn / Twitter / calendar API
    swapped to gmail-shaped opaque tokens.

    Bounce events are NEVER passed to the classifier per ADR-0025 D96
    — bounces are a separate category in the conversation-state
    machine. Pass G filters to reply event types upstream of the
    classifier dispatch via :data:`REPLY_EVENT_TYPES`.

    The pass has NO external client dependency — the classifier is a
    pure framework operation (regex match against ledger events).
    Operators with no pattern file get a refuse-loud error at
    classifier construction time, NOT here (Pass G assumes the caller
    has constructed a valid classifier).
    """
    result = PassResult(pass_name="G")
    since_iso = (
        since.isoformat() if since.tzinfo
        else since.replace(tzinfo=timezone.utc).isoformat()
    )

    # Build the idempotence index per ADR-0026 D104. One pass over the
    # ledger; O(events) — acceptable today (ADR-0026 §Negative consequences
    # names this as a known cost; Pillar G observability may surface
    # ledger-size growth as a pre-Pillar-H concern).
    classified_keys: set[tuple[str, str]] = set()
    for e in led.all_events():
        if e.get("type") != "reply_classified":
            continue
        mid = e.get("reply_message_id")
        ch = e.get("channel")
        if mid and ch:
            classified_keys.add((mid, ch))

    # Second ledger walk — the reply-event candidates. The mtime-based
    # cache in ``Ledger._build_indexes`` returns the same snapshot as
    # the first walk above under normal single-process operation (no
    # writes between the two calls). Per the Week 2 follow-up's P3-D
    # finding — the double-walk is documented here so a future reader
    # doesn't assume a single-snapshot semantic.
    for e in led.all_events():
        # Per ADR-0027 D112 — Pass G consumes every reply event type
        # in REPLY_EVENT_TYPES. Week 2 shipped reply_received only;
        # Week 3 extends to the per-channel reply event classes
        # emitted by Pass H / I / J.
        if e.get("type") not in REPLY_EVENT_TYPES:
            continue
        if (e.get("ts") or "") < since_iso:
            continue
        # Per ADR-0026 D104 + ADR-0025 §Migration/rollout item 3 —
        # discriminator is (reply_message_id, channel). Pass B's email
        # emit shape carries the message id as gmail_message_id; the
        # per-channel reply passes (Pass H / I / J — ADR-0027 D112)
        # name the field reply_message_id directly. Treat absent
        # channel as email per the historical default.
        mid = e.get("reply_message_id") or e.get("gmail_message_id")
        if not mid:
            # Defensive: a reply event without a message id can't be
            # idempotently identified; skip it and surface the
            # observation so operators see the unusual shape.
            result.errors.append(
                f"{e.get('type')} event without reply_message_id / "
                f"gmail_message_id; skipped (ts={e.get('ts')!r}, "
                f"person={e.get('person_id')!r})"
            )
            continue
        ch = e.get("channel") or "email"
        result.examined += 1

        if (mid, ch) in classified_keys:
            continue

        # Defensive: cast ledger.Event to plain dict so the classifier
        # doesn't need to know about Event vs dict. ``all_events()``
        # returns ``list[Event]`` (per ledger.py:756); the classifier
        # API consumes dicts.
        ev_dict = e.to_dict() if hasattr(e, "to_dict") else dict(e)

        try:
            cls_result = classifier.classify(ev_dict)
        except Exception as exc:
            # Classifier exceptions (e.g., catastrophic regex backtracking)
            # MUST NOT roll back Pass G — we record the error and move
            # on to the next event. The reply event itself is unchanged
            # (Pass G doesn't write to it); the operator can re-run
            # after tuning the pattern set.
            result.errors.append(
                f"{mid}: classifier exception: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        # Defense-in-depth per ADR-0026 D104 — mark seen so a duplicate
        # reply event in the same window (shouldn't happen — message id
        # is unique — but defense in depth) doesn't double-classify.
        classified_keys.add((mid, ch))

        if apply:
            try:
                written = _reply_classifier.emit_classified_event(
                    led, ev_dict, cls_result,
                )
                result.synthesized.append(written)
            except (OSError, ValueError) as exc:
                msg = (
                    f"ledger append failed for reply_classified "
                    f"({mid=}, {ch=}): {exc}"
                )
                print(f"WARNING: reconcile: {msg}", file=sys.stderr)
                result.errors.append(msg)
        else:
            # Dry run — synthesize the event payload without persisting.
            # Per the Week 2 follow-up's P3-C finding the payload
            # construction lives in ``reply_classifier.build_classified_
            # payload`` so the live path + the dry-run path share one
            # source of truth (a future field addition in the payload
            # shape lands automatically in both branches without manual
            # synchronization).
            dry = _reply_classifier.build_classified_payload(
                ev_dict, cls_result,
            )
            dry["_dry_run"] = True
            result.synthesized.append(dry)
    return result


# ---------------------------------------------------------------------------
# Pass M — auto-unsubscribe handler (Pillar D Week 4-5, ADR-0028 D115-D117)
# ---------------------------------------------------------------------------


def run_pass_m(
    *,
    led: _ledger.Ledger,
    suppressions_dir: Path,
    since: datetime,
    apply: bool,
) -> PassResult:
    """Auto-unsubscribe handler — reads ``reply_classified`` events
    filtered to ``category=unsubscribe`` + writes the suppression YAML.

    Per ADR-0028 D115-D117 + ADR-0025 D100's atomic write contract.
    Thin wrapper around
    :func:`orchestrator.auto_unsubscribe.run_auto_unsubscribe`; lives
    here so the pass integrates cleanly into the reconcile chain
    surface (per-pass `PassResult` + status persistence + CLI flag
    surface). The standalone handler primitive in
    ``orchestrator/auto_unsubscribe.py`` may be invoked directly by
    the future Pillar I CLI surface.

    The wrapping translates :class:`AutoUnsubscribeResult` →
    :class:`PassResult` so the reconcile machinery (status persistence,
    `--json` output, the operator-facing summary printer) sees a
    uniform shape across all 12 passes.
    """
    inner = _auto_unsubscribe.run_auto_unsubscribe(
        led=led,
        suppressions_dir=suppressions_dir,
        since=since,
        apply=apply,
    )
    result = PassResult(pass_name="M")
    result.examined = inner.examined
    result.synthesized = list(inner.synthesized)
    result.errors = list(inner.errors)
    # YAML writes + dedup counts surfaced as findings so operators see
    # the per-pass detail without expanding the PassResult dataclass.
    if inner.deduped:
        result.findings.append({
            "kind": "auto_unsubscribe_deduped",
            "count": inner.deduped,
        })
    for path in inner.yaml_writes:
        result.findings.append({
            "kind": "auto_unsubscribe_yaml_write",
            "path": str(path),
        })
    return result


# ---------------------------------------------------------------------------
# Pass N — conversation state machine (Pillar D Week 4-5, ADR-0028 D118-D119)
# ---------------------------------------------------------------------------


def run_pass_n(
    *,
    led: _ledger.Ledger,
    since: datetime,
    apply: bool,
    now: datetime | None = None,
    ttl_days: int = _conversation_state.DEFAULT_CONVERSATION_TTL_DAYS,
) -> PassResult:
    """Conversation state machine — emits ``conversation_state_changed``
    events per ADR-0025 D98 + ADR-0028 D118-D119.

    Thin wrapper around
    :func:`orchestrator.conversation_state.run_conversation_state_pass`
    — see that function's docstring for the per-thread state machine
    contract. Lives here so the pass integrates cleanly with the
    reconcile chain (per-pass `PassResult` + status persistence + CLI).

    Pass N runs AFTER Pass M in the chain so the
    ``suppression_added`` events Pass M emits drive the ``classified
    → unsubscribed`` transition within the same reconcile run.

    Per ADR-0030 D132 — the ``now`` + ``ttl_days`` parameters
    propagate the TTL-driven ``* → dormant`` transition. When
    ``now`` is ``None`` the TTL evaluation is DISABLED (matches the
    Week 4-5 behavior for callsites that don't supply the kwarg).
    """
    inner = _conversation_state.run_conversation_state_pass(
        led=led, since=since, apply=apply,
        now=now, ttl_days=ttl_days,
    )
    result = PassResult(pass_name="N")
    result.examined = inner.examined
    result.synthesized = list(inner.synthesized)
    result.errors = list(inner.errors)
    return result


# ---------------------------------------------------------------------------
# Pass O — conversation outcomes (Pillar D Week 9-11, ADR-0030 D133)
# ---------------------------------------------------------------------------


def run_pass_o(
    *,
    led: _ledger.Ledger,
    apply: bool,
    now: datetime | None = None,
    ttl_days: int = _conversation_state.DEFAULT_CONVERSATION_TTL_DAYS,
) -> PassResult:
    """Conversation outcomes — emits ``conversation_outcome`` events
    per ADR-0030 D130-D133.

    Thin wrapper around
    :func:`orchestrator.conversation_outcomes.run_conversation_outcomes_pass`
    — see that function's docstring for the per-thread outcome
    derivation contract. Lives here so the pass integrates cleanly
    with the reconcile chain (per-pass `PassResult` + status
    persistence + CLI).

    Pass O runs AFTER Pass N in the chain so the latest canonical
    thread state is the source for outcome derivation. The
    ``now`` + ``ttl_days`` kwargs propagate to
    :func:`orchestrator.conversation_outcomes.compute_conversation_outcomes`
    so TTL-driven dormant outcomes are visible in the same reconcile
    run that Pass N emits the TTL transition.

    Pass O is NOT run-window-bounded by ``since`` (unlike Pass N).
    Outcome derivation needs the full historical context (attribution
    walks back through pre-window touches); the idempotence index
    ensures re-runs are cheap.
    """
    inner = _conversation_outcomes.run_conversation_outcomes_pass(
        led=led, apply=apply, now=now, ttl_days=ttl_days,
    )
    result = PassResult(pass_name="O")
    result.examined = inner.examined
    result.synthesized = list(inner.synthesized)
    result.errors = list(inner.errors)
    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def reconcile(
    *,
    passes: str | Iterable[str] = "A",
    since: datetime,
    gmail: GmailClientLike | None = None,
    linkedin: LinkedInClientLike | None = None,
    twitter: TwitterClientLike | None = None,
    classifier: "_reply_classifier.RuleBasedClassifier | None" = None,
    led: _ledger.Ledger | None = None,
    people_dir: Path | None = None,
    suppressions_dir: Path | None = None,
    apply: bool = False,
    min_intent_age: timedelta = DEFAULT_MIN_INTENT_AGE,
    linkedin_scan_limit: int = LINKEDIN_DEFAULT_SCAN_LIMIT,
    twitter_scan_limit: int = TWITTER_DEFAULT_SCAN_LIMIT,
    conversation_ttl_days: int = (
        _conversation_state.DEFAULT_CONVERSATION_TTL_DAYS
    ),
    status_dir: Path | None = None,
    persist_status: bool = True,
) -> ReconcileResult:
    """Run the requested passes. Returns the aggregate ReconcileResult.

    `passes` accepts "A", "A,B,C,D,E,F", or an iterable. Order is
    preserved.
    `gmail` is required for Pass A and Pass B; Pass C is purely
    vault+ledger; `linkedin` is required for Pass D and Pass E;
    `twitter` is required for Pass F.
    `people_dir` is required for Pass C.

    Per ADR-0017 D48, when both Pass D and Pass E are requested in the
    same call, they execute SERIALLY (Pass D first, then Pass E) — both
    share the LinkedIn MCP rate-limit pool. Per ADR-0018 D58 + D62,
    Pass F executes serially after E by-convention (uniform operator-
    facing ordering); Twitter's cookie-scrape MCP rate-limit pool is
    distinct from LinkedIn's, so the serialization is observability-
    oriented (one-pass-at-a-time logs) rather than rate-limit-required.
    Pillar H's daemon is the right home for cross-pass parallelism if
    it's needed later.
    """
    if isinstance(passes, str):
        passes_list = [p.strip().upper() for p in passes.split(",") if p.strip()]
    else:
        passes_list = [p.strip().upper() for p in passes if p and p.strip()]
    for p in passes_list:
        if p not in ALL_PASSES:
            raise ValueError(f"unknown pass {p!r}; expected one of {ALL_PASSES}")

    if led is None:
        led = _ledger.Ledger(_ledger_dir_default())

    ran_at = _now_iso()
    agg = ReconcileResult(ran_at=ran_at, apply=apply)

    # Per ADR-0030 D132 + per-week review P3-D — capture `now` ONCE
    # for the entire reconcile run + pass to both Pass N (TTL driver)
    # + Pass O (outcome derivation). The single-`now` discipline keeps
    # the two passes consistent under fixed-now test injection +
    # eliminates the millisecond-gap surface area that a future test
    # injecting `now` via mocking would have to coordinate across.
    run_now = datetime.now(timezone.utc)

    for p in passes_list:
        if p == "A":
            if gmail is None:
                agg.passes.append(PassResult(
                    pass_name="A",
                    errors=["Pass A requires a Gmail client"],
                ))
                continue
            agg.passes.append(run_pass_a(
                led=led, gmail=gmail, since=since, apply=apply,
                min_intent_age=min_intent_age,
            ))
        elif p == "B":
            if gmail is None:
                agg.passes.append(PassResult(
                    pass_name="B",
                    errors=["Pass B requires a Gmail client"],
                ))
                continue
            agg.passes.append(run_pass_b(
                led=led, gmail=gmail, since=since, apply=apply,
            ))
        elif p == "C":
            if people_dir is None:
                agg.passes.append(PassResult(
                    pass_name="C",
                    errors=["Pass C requires a people_dir"],
                ))
                continue
            agg.passes.append(run_pass_c(
                led=led, people_dir=people_dir, apply=apply,
            ))
        elif p == "D":
            if linkedin is None:
                agg.passes.append(PassResult(
                    pass_name="D",
                    errors=["Pass D requires a LinkedIn client"],
                ))
                continue
            agg.passes.append(run_pass_d(
                led=led, linkedin=linkedin, since=since, apply=apply,
                min_intent_age=min_intent_age,
                scan_limit=linkedin_scan_limit,
            ))
        elif p == "E":
            if linkedin is None:
                agg.passes.append(PassResult(
                    pass_name="E",
                    errors=["Pass E requires a LinkedIn client"],
                ))
                continue
            agg.passes.append(run_pass_e(
                led=led, linkedin=linkedin, since=since, apply=apply,
                min_intent_age=min_intent_age,
                scan_limit=linkedin_scan_limit,
            ))
        elif p == "F":
            if twitter is None:
                agg.passes.append(PassResult(
                    pass_name="F",
                    errors=["Pass F requires a Twitter client"],
                ))
                continue
            agg.passes.append(run_pass_f(
                led=led, twitter=twitter, since=since, apply=apply,
                min_intent_age=min_intent_age,
                scan_limit=twitter_scan_limit,
            ))
        elif p == "H":
            if linkedin is None:
                agg.passes.append(PassResult(
                    pass_name="H",
                    errors=["Pass H requires a LinkedIn client"],
                ))
                continue
            agg.passes.append(run_pass_h(
                led=led, linkedin=linkedin, since=since, apply=apply,
                scan_limit=linkedin_scan_limit,
            ))
        elif p == "I":
            if linkedin is None:
                agg.passes.append(PassResult(
                    pass_name="I",
                    errors=["Pass I requires a LinkedIn client"],
                ))
                continue
            agg.passes.append(run_pass_i(
                led=led, linkedin=linkedin, since=since, apply=apply,
                scan_limit=linkedin_scan_limit,
            ))
        elif p == "J":
            if twitter is None:
                agg.passes.append(PassResult(
                    pass_name="J",
                    errors=["Pass J requires a Twitter client"],
                ))
                continue
            agg.passes.append(run_pass_j(
                led=led, twitter=twitter, since=since, apply=apply,
                scan_limit=twitter_scan_limit,
            ))
        elif p == "G":
            if classifier is None:
                agg.passes.append(PassResult(
                    pass_name="G",
                    errors=[
                        "Pass G requires a classifier — bootstrap with "
                        "`mkdir -p ~/.outreach-factory/classifier && "
                        "cp config-template/unsubscribe-patterns.example.yml "
                        "~/.outreach-factory/classifier/unsubscribe-"
                        "patterns.yml` (per ADR-0026 D103), or pass an "
                        "explicit `classifier=` to reconcile()."
                    ],
                ))
                continue
            agg.passes.append(run_pass_g(
                led=led, classifier=classifier, since=since, apply=apply,
            ))
        elif p == "M":
            sup_dir = (
                suppressions_dir
                if suppressions_dir is not None
                else _auto_unsubscribe.suppressions_dir_default()
            )
            agg.passes.append(run_pass_m(
                led=led, suppressions_dir=sup_dir,
                since=since, apply=apply,
            ))
        elif p == "N":
            # Per ADR-0030 D132 — propagate TTL kwargs so Pass N's
            # TTL-driven `* → dormant` transitions land in this run.
            # `run_now` captured once at reconcile() entry per the
            # single-`now` discipline above.
            agg.passes.append(run_pass_n(
                led=led, since=since, apply=apply,
                now=run_now,
                ttl_days=conversation_ttl_days,
            ))
        elif p == "O":
            # Per ADR-0030 D133 — Pass O propagates the same TTL
            # kwargs so the outcome derivation sees the canonical
            # state (including TTL-driven dormant) consistently.
            agg.passes.append(run_pass_o(
                led=led, apply=apply,
                now=run_now,
                ttl_days=conversation_ttl_days,
            ))

    if persist_status:
        try:
            _record_status(agg, status_dir or _reconcile_dir_default())
        except OSError as exc:
            print(f"WARNING: reconcile status persistence failed: {exc}",
                  file=sys.stderr)

    return agg


# ---------------------------------------------------------------------------
# Status persistence
# ---------------------------------------------------------------------------


def _status_path(status_dir: Path) -> Path:
    status_dir.mkdir(parents=True, exist_ok=True)
    return status_dir / "status.yml"


def _load_status(status_dir: Path) -> dict:
    p = _status_path(status_dir)
    if not p.exists():
        return {"last_run": {}, "last_results": {}}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"last_run": {}, "last_results": {}}
    if not isinstance(data, dict):
        return {"last_run": {}, "last_results": {}}
    data.setdefault("last_run", {})
    data.setdefault("last_results", {})
    return data


def _record_status(agg: ReconcileResult, status_dir: Path) -> None:
    """Update per-pass last-run timestamp + summary in status.yml.

    Only records passes that produced no errors — a half-broken run shouldn't
    satisfy the send-gate freshness check.
    """
    data = _load_status(status_dir)
    for pr in agg.passes:
        if pr.errors:
            continue
        data["last_run"][pr.pass_name] = agg.ran_at
        data["last_results"][pr.pass_name] = pr.summary()
    data["last_run_apply"] = agg.apply
    _status_path(status_dir).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def last_quick_run(status_dir: Path | None = None) -> datetime | None:
    """Return the ts of the last clean Pass A run, or None."""
    sd = status_dir or _reconcile_dir_default()
    data = _load_status(sd)
    ts = (data.get("last_run") or {}).get("A")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def needs_quick_reconcile(
    *,
    led: _ledger.Ledger | None = None,
    status_dir: Path | None = None,
    max_age: timedelta = timedelta(hours=1),
    now: datetime | None = None,
) -> bool:
    """Decision used by send_queued.py before dispatching a send batch.

    Returns True if (a) the last quick run is older than max_age AND
    (b) there are at least one open intent (older than min_intent_age).
    Both conditions must hold — fast when nothing's wrong, thorough when
    something might be.

    Caveat — LinkedIn intents (Pillar C Week 4): this function returns
    True when ANY channel has an open intent (the underlying
    ``open_intents`` call is not channel-filtered). Pass D + Pass E
    (LinkedIn) are only invoked by ``--full``, not ``--quick``;
    callers using this gate to trigger ``--quick`` should be aware
    that LinkedIn orphans will NOT be resolved by the resulting
    Pass-A-only run. The ``--quick`` reconcile will write its own
    last-run-clean timestamp + the next invocation may continue to
    return True until a ``--full`` run heals the LinkedIn orphans
    (or up to 24h pass, the typical daemon ``--full`` cadence).
    Pillar H's daemon addresses this operationally by running
    ``--full`` daily on its own schedule. Per the Week 4 per-week
    review A-3 finding; a follow-up Pillar I CLI ergonomic may add
    per-channel needs-quick-reconcile sub-queries.
    """
    led = led or _ledger.Ledger(_ledger_dir_default())
    now = now or datetime.now(timezone.utc)
    last = last_quick_run(status_dir)
    if last is not None and (now - last) <= max_age:
        return False
    open_intents = led.open_intents(
        since=now - timedelta(days=7),
        min_age=DEFAULT_MIN_INTENT_AGE,
    )
    return len(open_intents) > 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_SINCE_RE = re.compile(r"^(\d+)([dhm])$")


def _parse_since(text: str) -> datetime:
    m = _SINCE_RE.match(text.strip())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n),
                 "m": timedelta(minutes=n)}[unit]
        return datetime.now(timezone.utc) - delta
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"--since: {text!r} not a duration or ISO date: {exc}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_people_dir() -> Path | None:
    cfg_path = Path.home() / ".outreach-factory" / "config.yml"
    if not cfg_path.exists():
        return None
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(v.get("path") or ""))
    if not vault_path.exists():
        return None
    pd = vault_path / (v.get("people_dir") or "10 People")
    return pd if pd.exists() else None


def _build_gmail_adapter() -> GmailClientLike | None:
    """Lazily import the send-outreach GmailClient + wrap it for the
    GmailClientLike protocol. Returns None on import failure (e.g., google
    libs not installed) so --status / Pass-C-only runs still work."""
    skill_scripts = Path(__file__).resolve().parent.parent / \
        "skills" / "send-outreach" / "scripts"
    if str(skill_scripts) not in sys.path:
        sys.path.insert(0, str(skill_scripts))
    try:
        from gmail_client import GmailClient  # type: ignore
    except Exception as exc:
        print(f"reconcile: cannot import GmailClient ({exc})",
              file=sys.stderr)
        return None
    try:
        client = GmailClient.authenticate()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"reconcile: Gmail authenticate failed: {exc}", file=sys.stderr)
        return None
    return _GmailAdapter(client)


def _build_linkedin_adapter() -> LinkedInClientLike | None:
    """Lazily import a LinkedIn client + wrap it for the LinkedInClientLike
    protocol. Returns None when no adapter is available.

    Per ADR-0017 §Migration/rollout, the operator-facing LinkedIn surface
    for reconcile is wired via the same shim mechanism Pillar I OSS bring-up
    uses for `dispatch-outreach`. The exact MCP wiring is environment-
    specific — the operator's `~/.outreach-factory/config.yml` may name an
    importable adapter via `reconcile.linkedin_adapter`; until that hook
    lands (Pillar I), CLI invocation with Pass D / E without an injected
    adapter records the "Pass D requires a LinkedIn client" error per the
    same shape as Pass A's missing-Gmail error.

    Tests inject fakes directly via the `linkedin=` kwarg to `reconcile()`.
    """
    skill_scripts = Path(__file__).resolve().parent.parent / \
        "skills" / "send-outreach" / "scripts"
    if str(skill_scripts) not in sys.path:
        sys.path.insert(0, str(skill_scripts))
    try:
        from linkedin_client import build_reconcile_adapter  # type: ignore
    except Exception as exc:
        print(
            f"reconcile: cannot import linkedin_client ({exc}); "
            f"Pass D / E will record 'requires a LinkedIn client'.",
            file=sys.stderr,
        )
        return None
    try:
        return build_reconcile_adapter()
    except SystemExit:
        raise
    except Exception as exc:
        print(
            f"reconcile: LinkedIn adapter build failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None


def _build_classifier_or_record_error(
    pattern_path: Path,
) -> "tuple[_reply_classifier.RuleBasedClassifier | None, str | None]":
    """Per ADR-0026 D103 — lazy classifier construction with refuse-loud.

    Returns ``(classifier, error_msg)`` — at most one is non-None.
    Pass G's dispatcher (in ``reconcile()``) lifts the error into a
    PassResult.errors entry so operators see one clear remediation
    message rather than a Python traceback.

    Tests inject classifiers directly via the ``classifier=`` kwarg
    to ``reconcile()``.
    """
    try:
        return (
            _reply_classifier.RuleBasedClassifier.from_yaml(pattern_path),
            None,
        )
    except _reply_classifier.PatternLoadError as exc:
        return None, str(exc)


def _build_twitter_adapter() -> TwitterClientLike | None:
    """Lazily import a Twitter client + wrap it for the TwitterClientLike
    protocol. Returns None when no adapter is available.

    Per ADR-0018 §Migration/rollout, the operator-facing Twitter surface
    for reconcile is wired via the same shim mechanism Pillar I OSS bring-up
    uses for `dispatch-outreach`. The cookie-scrape MCP wiring is
    environment-specific — the operator's `~/.outreach-factory/config.yml`
    may name an importable adapter via `reconcile.twitter_adapter`; until
    that hook lands (Pillar I), CLI invocation with Pass F without an
    injected adapter records the "Pass F requires a Twitter client" error
    per the same shape as Pass A's missing-Gmail + Pass D's missing-
    LinkedIn errors.

    Tests inject fakes directly via the `twitter=` kwarg to `reconcile()`.
    """
    skill_scripts = Path(__file__).resolve().parent.parent / \
        "skills" / "send-outreach" / "scripts"
    if str(skill_scripts) not in sys.path:
        sys.path.insert(0, str(skill_scripts))
    try:
        from twitter_client import build_reconcile_adapter  # type: ignore
    except Exception as exc:
        print(
            f"reconcile: cannot import twitter_client ({exc}); "
            f"Pass F will record 'requires a Twitter client'.",
            file=sys.stderr,
        )
        return None
    try:
        return build_reconcile_adapter()
    except SystemExit:
        raise
    except Exception as exc:
        print(
            f"reconcile: Twitter adapter build failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None


class _GmailAdapter:
    """Wraps the googleapiclient-backed GmailClient for the protocol."""

    def __init__(self, client):
        self._client = client
        self.sender_email = getattr(client, "sender_email", None)

    def search_messages(self, query: str, max_results: int = 100) -> list[dict]:
        svc = self._client.service.users().messages()
        resp = svc.list(userId="me", q=query, maxResults=max_results).execute()
        return resp.get("messages", []) or []

    def get_message(self, msg_id: str) -> dict | None:
        try:
            return self._client.service.users().messages().get(
                userId="me", id=msg_id, format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date",
                                 "X-Outreach-Intent-Id", "Message-Id",
                                 "In-Reply-To"],
            ).execute()
        except Exception:
            return None

    def get_thread(self, thread_id: str) -> dict | None:
        try:
            return self._client.service.users().threads().get(
                userId="me", id=thread_id, format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date",
                                 "X-Outreach-Intent-Id", "Message-Id",
                                 "In-Reply-To"],
            ).execute()
        except Exception:
            return None


def main() -> int:
    p = argparse.ArgumentParser(
        description="Reconcile ledger ↔ Gmail ↔ LinkedIn ↔ Twitter ↔ vault",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true",
                   help="Last 24h, Pass A only; applies by default")
    g.add_argument("--full", action="store_true",
                   help="Last 30d, all 12 passes "
                        "(A,B,C,D,H,E,I,F,J,G,M,N); applies by default")
    g.add_argument("--status", action="store_true",
                   help="Show last clean-run timestamps and exit")
    p.add_argument("--since", default=None,
                   help="Custom window (e.g. 7d, 12h, ISO date)")
    p.add_argument("--passes", default=None,
                   help="Comma-separated subset of A,B,C,D,H,E,I,F,J,G,M,N "
                        "(default: A for --quick, "
                        "A,B,C,D,H,E,I,F,J,G,M,N for --full)")
    apply_group = p.add_mutually_exclusive_group()
    apply_group.add_argument("--dry-run", action="store_true",
                             help="Report only; no ledger or vault writes")
    apply_group.add_argument("--apply", action="store_true",
                             help="Write events + heal vault frontmatter")
    p.add_argument("--ledger-dir", default=None)
    p.add_argument("--reconcile-dir", default=None)
    p.add_argument("--people-dir", default=None)
    p.add_argument("--min-intent-age-min", type=int, default=5)
    p.add_argument("--linkedin-scan-limit", type=int,
                   default=LINKEDIN_DEFAULT_SCAN_LIMIT,
                   help=f"Per ADR-0017 D49 — number of most-recent invitations "
                        f"(Pass D) / conversations (Pass E) the LinkedIn "
                        f"adapter returns. Default "
                        f"{LINKEDIN_DEFAULT_SCAN_LIMIT}.")
    p.add_argument("--twitter-scan-limit", type=int,
                   default=TWITTER_DEFAULT_SCAN_LIMIT,
                   help=f"Per ADR-0018 D58 — number of most-recent DM "
                        f"conversations (Pass F) the Twitter adapter "
                        f"returns. Default {TWITTER_DEFAULT_SCAN_LIMIT}.")
    p.add_argument(
        "--classifier-rule-list", default=None,
        help="Per ADR-0026 D103 — path to the unsubscribe-pattern YAML "
             "for Pass G. Default: "
             "~/.outreach-factory/classifier/unsubscribe-patterns.yml. "
             "Override for test injection or per-environment tuning.",
    )
    p.add_argument(
        "--suppressions-dir", default=None,
        help="Per ADR-0028 D115 — directory for the auto-unsubscribe "
             "YAML Pass M writes to. Default: "
             "~/.outreach-factory/suppressions/. "
             "Override for test injection or per-environment tuning.",
    )
    p.add_argument(
        "--conversation-ttl-days", type=int,
        default=_conversation_state.DEFAULT_CONVERSATION_TTL_DAYS,
        help=f"Per ADR-0030 D132 — TTL window (days) for the Pass N "
             f"`* → dormant` transition driver. Threads with no "
             f"activity past this window auto-transition to dormant; "
             f"Pass O then emits the `conversation_outcome` event. "
             f"Default {_conversation_state.DEFAULT_CONVERSATION_TTL_DAYS} "
             f"days; 0 disables the TTL driver entirely (manual "
             f"pipeline operators).",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument("--send-outreach-scope", action="store_true",
                   help="Compat flag for the send-outreach skill shim")

    args = p.parse_args()

    status_dir = (
        Path(os.path.expanduser(args.reconcile_dir)).resolve()
        if args.reconcile_dir else _reconcile_dir_default()
    )

    if args.status:
        data = _load_status(status_dir)
        if args.json:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(f"Reconcile status ({status_dir}):")
            for pn in ALL_PASSES:
                ts = (data.get("last_run") or {}).get(pn) or "(never)"
                res = (data.get("last_results") or {}).get(pn) or {}
                print(f"  Pass {pn}: last clean run = {ts}")
                if res:
                    print(f"           {json.dumps(res.get('by_type', {}))}")
        return 0

    # Resolve window + passes. Per ADR-0017 D48 + ADR-0018 D58 + ADR-0026
    # D105 + ADR-0027 D111, --full requests A,B,C,D,H,E,I,F,J,G:
    # D + E + F run serially per the LinkedIn MCP rate-limit pool +
    # the per-channel-uniformity convention; H follows D (LinkedIn
    # invite intent recovery → invite acceptance detection); I
    # follows E (LinkedIn DM intent recovery → DM reply detection);
    # J follows F (Twitter DM intent recovery → DM reply detection);
    # G runs LAST and consumes the reply events H + I + J emit + the
    # email reply events B emits.
    if args.quick:
        since = datetime.now(timezone.utc) - QUICK_WINDOW
        passes = args.passes or "A"
        apply_default = True
    elif args.full:
        since = datetime.now(timezone.utc) - FULL_WINDOW
        passes = args.passes or "A,B,C,D,H,E,I,F,J,G,M,N,O"
        apply_default = True
    else:
        if not args.since and not args.passes:
            p.error("specify one of --quick / --full / --status, "
                    "or provide --since with --passes")
        since = _parse_since(args.since) if args.since else \
            datetime.now(timezone.utc) - timedelta(days=7)
        passes = args.passes or "A"
        apply_default = False

    if args.apply:
        apply = True
    elif args.dry_run:
        apply = False
    else:
        apply = apply_default

    ledger_dir = (
        Path(os.path.expanduser(args.ledger_dir)).resolve()
        if args.ledger_dir else _ledger_dir_default()
    )
    led = _ledger.Ledger(ledger_dir)

    needs_gmail = any(pn in passes.upper() for pn in ("A", "B"))
    gmail = _build_gmail_adapter() if needs_gmail else None

    needs_linkedin = any(pn in passes.upper() for pn in ("D", "E", "H", "I"))
    linkedin = _build_linkedin_adapter() if needs_linkedin else None

    needs_twitter = any(pn in passes.upper() for pn in ("F", "J"))
    twitter = _build_twitter_adapter() if needs_twitter else None

    # Per ADR-0026 D105 — Pass G's classifier construction. The flag
    # --classifier-rule-list overrides the default per-operator path.
    # On bootstrap-missing (PatternLoadError), the classifier is None;
    # Pass G's dispatcher in reconcile() records a PassResult.errors
    # entry with the bootstrap remediation message.
    needs_classifier = "G" in passes.upper()
    classifier = None
    if needs_classifier:
        pattern_path = (
            Path(os.path.expanduser(args.classifier_rule_list)).resolve()
            if args.classifier_rule_list else _classifier_pattern_path_default()
        )
        classifier, classifier_err = _build_classifier_or_record_error(pattern_path)
        if classifier_err:
            print(f"reconcile: Pass G classifier not loaded: "
                  f"{classifier_err}", file=sys.stderr)

    people_dir = None
    if "C" in passes.upper():
        people_dir = (
            Path(os.path.expanduser(args.people_dir)).resolve()
            if args.people_dir else _resolve_people_dir()
        )

    # Per ADR-0028 D115 — Pass M writes the auto-unsubscribe YAML to
    # ``--suppressions-dir`` (default: ``~/.outreach-factory/
    # suppressions/``). Pass N has no external resource dependency.
    suppressions_dir = None
    if "M" in passes.upper():
        suppressions_dir = (
            Path(os.path.expanduser(args.suppressions_dir)).resolve()
            if args.suppressions_dir
            else _auto_unsubscribe.suppressions_dir_default()
        )

    result = reconcile(
        passes=passes,
        since=since,
        gmail=gmail,
        linkedin=linkedin,
        twitter=twitter,
        classifier=classifier,
        led=led,
        people_dir=people_dir,
        suppressions_dir=suppressions_dir,
        apply=apply,
        min_intent_age=timedelta(minutes=args.min_intent_age_min),
        linkedin_scan_limit=args.linkedin_scan_limit,
        twitter_scan_limit=args.twitter_scan_limit,
        conversation_ttl_days=args.conversation_ttl_days,
        status_dir=status_dir,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"Reconcile {mode}  ran_at={result.ran_at}  since={since.isoformat()}")
    for pr in result.passes:
        s = pr.summary()
        line = f"  Pass {pr.pass_name}: examined={s['examined']}"
        if s["by_type"]:
            line += "  " + ", ".join(f"{k}={v}" for k, v in s["by_type"].items())
        if s["errors"]:
            line += f"  errors={s['errors']}"
        print(line)
        for f in pr.findings[:10]:
            kind = f.get("kind", "?")
            extra = ""
            if "person_id" in f:
                extra = f"  {f['person_id']}"
            if "from" in f and "to" in f:
                extra += f"  {f['from']}→{f['to']}"
            elif "vault_stage" in f and "ledger_stage" in f:
                extra += f"  vault={f['vault_stage']} ledger={f['ledger_stage']}"
            print(f"      • {kind}{extra}")
        if len(pr.findings) > 10:
            print(f"      ... +{len(pr.findings) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
