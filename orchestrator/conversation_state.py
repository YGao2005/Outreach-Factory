"""Pillar D Week 4-5 — conversation state machine.

Per ADR-0025 D98 + ADR-0028 D118-D119, the conversation state machine
is **per-thread** (one state machine per ``(person_id, channel,
thread_key)`` triple). The send-state machine (``derived_stage`` per
``orchestrator/ledger.py``) is per-person; the two are independent.
A Person with three email threads + one LinkedIn DM thread has FOUR
conversation state machines + one send-state machine.

States (per ADR-0025 D98 + ADR-0028 D119):

  * ``replied`` — first ``*_reply_received`` event lands on the
    thread. The recipient has communicated; the framework is now
    aware of the conversation.
  * ``classified`` — a ``reply_classified`` event has been emitted
    for the reply (any category). The framework has interpreted the
    reply; downstream consumers (handler / dashboards) read the
    category.
  * ``unsubscribed`` — a ``suppression_added`` event correlating
    back to a classified ``unsubscribe`` on this thread has landed.
    Terminal state — no further outreach permitted (CAN-SPAM
    compliance per ADR-0025 D97 + D100).
  * ``active`` — the classifier categorized the reply as
    ``interest``. The conversation is in an active phase; operators
    typically progress to draft / book / etc. via the normal
    pipeline. Pillar D Week 9-11 (ADR-0029 — TBD) MAY refine this
    state's transitions further.
  * ``dormant`` — the classifier categorized the reply as
    ``rejection`` OR ``ooo``, OR (per ADR-0030 D132) the thread has
    had no activity in ``ttl_days`` and the TTL driver advances it.
    The thread is paused; the operator's pipeline may auto-snooze +
    re-engage at a future cadence.

State transitions (Week 4-5 — ADR-0028 D119):

  * ``(none) → replied`` on the FIRST ``*_reply_received`` event for
    the thread.
  * ``replied → classified`` on the FIRST ``reply_classified`` event
    for a reply on the thread.
  * ``classified → unsubscribed`` on the FIRST ``suppression_added``
    event whose ``source_reply_classified_event`` references a
    classified event on this thread. Terminal.
  * ``classified → active`` on the FIRST ``reply_classified`` with
    ``category=interest`` on the thread (operator-deliberate per
    ADR-0028 D119; the state pinning serves Pillar G dashboards +
    win/loss attribution).
  * ``classified → dormant`` on the FIRST ``reply_classified`` with
    ``category=rejection`` OR ``category=ooo`` on the thread.
  * (Pillar D Week 9-11 — ADR-0030 D132) ``* → dormant`` (TTL driver)
    when the thread's last-activity timestamp is older than
    ``ttl_days`` and the current state is non-terminal (replied /
    classified / active). Terminal states (unsubscribed) are NOT
    affected by TTL because their priority dominates per
    :data:`STATE_PRIORITY`.

Higher-priority transitions win when multiple signals fire on the
same thread:

  unsubscribed > active > dormant > classified > replied > (none)

The priority captures the asymmetric-failure-cost calculus per
PILLAR-PLAN §0: a missed unsubscribe (CAN-SPAM violation) >
misclassified-dormant (operator-tunable). The priority is operator-
visible via the ``conversation_status:`` Person frontmatter field
(per ADR-0028 D119's denormalization).

Per-Person aggregation
----------------------

The conversation state is per-thread, but the operator-facing surface
(Person frontmatter + Pillar G dashboards) often needs a per-Person
roll-up. The aggregation: take the highest-priority state across all
threads belonging to the Person. The ``derived_conversation_status``
helper computes the aggregated status; Pass C extension heals the
``conversation_status:`` Person frontmatter from this derived value.

Event shape
-----------

Per ADR-0025 D98:

.. code-block:: python

    {
        "type": "conversation_state_changed",
        "person_id": "<pid>",
        "channel": "email | linkedin | twitter | calendar",
        "thread_key": "<gmail_thread_id | linkedin_thread_id |
                       linkedin_invitation_id | twitter_thread_id |
                       calendar_booking_intent_id>",
        "from_state": "replied",  # or None on the initial transition
        "to_state": "classified",
        "trigger_event_id": {
            "reply_message_id": "<the originating reply's id>",
            "channel": "<channel>",
            "ts": "<the trigger event's ts>",
        },
        "_emitted_by": "conversation_state_machine",
    }

The ``trigger_event_id`` correlation key is a dict shape (mirrors the
``source_reply_classified_event`` field on ``suppression_added``
events per ADR-0028 D116) keyed by ``(reply_message_id, channel)``
per ADR-0026 D104. Future Pillar G dashboards join across the chain
``*_reply_received → reply_classified → conversation_state_changed →
suppression_added`` via this key.

Per-thread idempotence
----------------------

The pass walks the ledger + computes the canonical per-thread state
deterministically from the events present. The emit-side idempotence
key is ``(person_id, channel, thread_key, to_state)`` — the pass
skips emission when the canonical from→to transition already has a
matching ``conversation_state_changed`` event in the ledger.

The deterministic-walk-from-events shape means a re-run never
emits duplicate transitions; if a new event lands between runs the
pass detects + emits the additional transitions on the next run.

Pillar D Week 9-11 (ADR-0030) — TTL transitions
-----------------------------------------------

Per ADR-0030 D132, the state machine gains a TIME-DRIVEN transition
to ``dormant`` for threads that have been quiet for ``ttl_days``
days. The default is :data:`DEFAULT_CONVERSATION_TTL_DAYS` (30) —
operator-tunable via the reconcile CLI flag
``--conversation-ttl-days`` (per the standard --quick / --full
operator-facing convention; Pillar I CLI may extend further).

The TTL driver is a NEW driver in :func:`compute_thread_states`,
which now accepts ``now`` + ``ttl_days`` optional kwargs:

  * ``now=None`` (default) — TTL evaluation disabled. Matches
    Week 4-5 callsites that don't care about TTL.
  * ``now=<utc dt>`` + ``ttl_days=N`` — TTL evaluation enabled. The
    walk computes the per-thread ``last_activity_ts``; if
    ``now - last_activity_ts > ttl_days days`` AND the current state
    is non-terminal (replied / classified / active), the TTL driver
    emits a ``dormant`` transition.

The TTL driver respects ``STATE_PRIORITY`` — it cannot demote a
thread from ``unsubscribed`` (priority 4) to ``dormant``
(priority 2). The priority is the load-bearing legal-liability
discipline per ADR-0025 D97 + ADR-0028 D119; the TTL is a UX
convenience that operates ONLY in the non-terminal range.

Pass O (Pillar D Week 9-11 — ADR-0030 D133) builds on this surface
+ emits per-thread ``conversation_outcome`` events for terminal
states. See ``orchestrator/conversation_outcomes.py``.

Non-deliverables — deferred beyond Pillar D Week 9-11
-----------------------------------------------------

* ``unsubscribed → re-engaged`` for GDPR-pause-then-resume flows
  (Pillar J).
* Calendar-channel state transitions beyond the booking-state events
  (Pass K deferred per ADR-0027 D113).
* Per-channel TTL overrides (one global TTL today; per-channel
  refinement is a Pillar I CLI extension if operator demand
  materializes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

import ledger as _ledger


# Per ADR-0028 D119 — the per-thread state machine's canonical states.
# Ordering reflects priority: higher index = higher priority. The
# aggregation logic (``derived_conversation_status``) selects the
# highest-priority state across a Person's threads.
STATES: tuple[str, ...] = (
    "replied", "classified", "dormant", "active", "unsubscribed",
)


# Per ADR-0030 D132 — default TTL window for the
# ``* → dormant`` transition driver. Threads in non-terminal state
# (replied / classified / active) past this window auto-transition to
# dormant. Operator-tunable via the reconcile CLI flag
# ``--conversation-ttl-days``. 30 days matches the conservative B2B
# sales-cycle horizon; operators with longer cycles tune up. Pass 0
# to disable TTL entirely (manual pipeline operators).
DEFAULT_CONVERSATION_TTL_DAYS: int = 30


# Per ADR-0030 D132 — the TTL driver's transition trigger field.
# When a TTL transition fires, the ``trigger_event_id`` field carries
# ``driver: "ttl"`` so downstream consumers (Pass O outcome derivation,
# Pillar G dashboards) can distinguish TTL-driven dormancy from
# category-driven dormancy.
TTL_TRIGGER_DRIVER: str = "ttl"


# Per ADR-0028 D119 — priority index for cross-thread aggregation +
# transition-conflict resolution. The unsubscribed state is TERMINAL
# (top priority); active > dormant > classified > replied is the
# operator-visibility ordering (an "active" thread is more interesting
# than a "dormant" thread; a "classified" thread is more interesting
# than a still-"replied" thread).
STATE_PRIORITY: dict[str, int] = {s: i for i, s in enumerate(STATES)}


# Per ADR-0027 D108 — the categories that drive long-tail state
# transitions. The unsubscribe category transitions via the
# ``suppression_added`` event (a SEPARATE driver), NOT via the
# classified event itself (because the unsubscribe state needs the
# YAML write to have happened — that's the load-bearing posture per
# ADR-0025 D100 + ADR-0028 D116).
_CLASSIFIED_TO_ACTIVE_CATEGORIES: frozenset[str] = frozenset({"interest"})
_CLASSIFIED_TO_DORMANT_CATEGORIES: frozenset[str] = frozenset({
    "rejection", "ooo",
})


def _extract_thread_key(event: dict) -> str | None:
    """Pull the per-channel thread key out of a ledger event.

    Mirrors the helper in ``orchestrator/auto_unsubscribe.py`` — the
    two modules SHARE the per-channel thread-field convention. Per
    ADR-0025 D98 each channel uses a distinct field:

    * email → ``gmail_thread_id``
    * linkedin (invite) → ``linkedin_invitation_id``
    * linkedin (DM) → ``linkedin_thread_id``
    * twitter → ``twitter_thread_id``
    * calendar → ``calendar_booking_intent_id`` (deferred per ADR-
      0027 D113 — Pass K not shipped; calendar threads don't reach
      this helper today)

    Returns the thread-key string or ``None`` when no field matches.
    """
    for field_name in (
        "gmail_thread_id",
        "linkedin_thread_id",
        "linkedin_invitation_id",
        "twitter_thread_id",
        "calendar_booking_intent_id",
    ):
        v = event.get(field_name)
        if isinstance(v, str) and v:
            return v
    return None


@dataclass(frozen=True)
class ThreadKey:
    """The identity of one conversation-state machine.

    Per ADR-0025 D98 + ADR-0028 D119 — a thread is identified by the
    triple ``(person_id, channel, thread_key)``. Two threads with the
    same ``thread_key`` field across different channels (e.g., a
    LinkedIn invite + a LinkedIn DM that happen to share a stringly
    identifier) are DISTINCT state machines because the channel
    discriminates.
    """

    person_id: str
    channel: str
    thread_key: str


@dataclass
class ThreadState:
    """The accumulated state of one thread + the per-state trigger.

    The ``trigger`` map records the (reply_message_id, ts) pair that
    drove each transition; the conversation-state pass uses this to
    construct the ``trigger_event_id`` field on the emitted
    ``conversation_state_changed`` event.

    ``last_activity_ts`` (Pillar D Week 9-11 — ADR-0030 D132) tracks
    the timestamp of the most-recent driver event for the thread.
    Used by the TTL driver to determine when ``* → dormant`` should
    fire.
    """

    state: str | None = None
    # Maps "from_state" → ("reply_message_id", "ts") for the most-
    # recent transition. Used to build emitted-event trigger fields.
    trigger: dict[str, dict[str, str | None]] = field(default_factory=dict)
    # The ts of the most-recent driver event for the thread (any
    # reply / classified / suppression event). Per ADR-0030 D132.
    last_activity_ts: str | None = None


def _classified_thread_index(
    led: "_ledger.Ledger",
) -> dict[tuple[str, str], tuple[str, str | None]]:
    """Build the (reply_message_id, channel) → (thread_key, ts) index
    for ``reply_classified`` events.

    Used by the conversation-state walk to resolve the THREAD a
    classified-event belongs to (the classified event itself carries
    the originating reply's ``gmail_thread_id`` when on email, but
    NOT the LinkedIn / Twitter thread keys — those live on the
    ORIGINATING reply event).

    Returns a dict mapping the discriminator pair to (thread_key, ts);
    classified events without a resolvable thread key map to None.
    """
    # First pass — collect the originating reply events keyed by
    # (reply_message_id, channel) so we can resolve thread keys.
    reply_thread_by_pair: dict[tuple[str, str], str | None] = {}
    for e in led.all_events():
        t = e.get("type")
        # Per Pass B (Phase 5.5) + ADR-0027 D112 — the four reply
        # event classes whose message_id+channel pair Pass G consumes.
        if t not in (
            "reply_received",
            "li_invite_reply_received",
            "li_dm_reply_received",
            "tw_dm_reply_received",
        ):
            continue
        mid = e.get("reply_message_id") or e.get("gmail_message_id")
        ch = e.get("channel") or "email"
        if not mid:
            continue
        reply_thread_by_pair[(str(mid), str(ch))] = _extract_thread_key(
            e.to_dict() if hasattr(e, "to_dict") else dict(e),
        )

    out: dict[tuple[str, str], tuple[str, str | None]] = {}
    for e in led.all_events():
        if e.get("type") != "reply_classified":
            continue
        mid = e.get("reply_message_id")
        ch = e.get("channel")
        if not mid or not ch:
            continue
        # The classifier preserves ``gmail_thread_id`` on email-channel
        # classified events (per ``build_classified_payload`` in
        # ``orchestrator/reply_classifier.py``); for non-email channels
        # we look up the originating reply event's thread key.
        tk = _extract_thread_key(
            e.to_dict() if hasattr(e, "to_dict") else dict(e),
        )
        if tk is None:
            tk = reply_thread_by_pair.get((str(mid), str(ch)))
        out[(str(mid), str(ch))] = (
            tk if tk is not None else "",
            e.get("ts"),
        )
    return out


@dataclass
class ConversationStatePassResult:
    """Mirrors ``PassResult`` so Pass N integrates with reconcile.

    Lives here as a distinct class because the conversation-state
    pass may be invoked standalone (Pillar I CLI surface) + the field
    set is conversation-state-specific.
    """

    examined: int = 0
    synthesized: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "examined": self.examined,
            "synthesized": len(self.synthesized),
            "errors": len(self.errors),
        }


def compute_thread_states(
    led: "_ledger.Ledger",
    *,
    since: datetime | None = None,
    now: datetime | None = None,
    ttl_days: int = DEFAULT_CONVERSATION_TTL_DAYS,
) -> dict[ThreadKey, ThreadState]:
    """Walk the ledger; compute the canonical per-thread state.

    Per ADR-0028 D119 — the state machine is event-driven (each event
    class drives a specific transition). The walk is deterministic
    + idempotent; running it twice over the same ledger produces the
    same result.

    The ``since`` parameter is OPTIONAL — when provided, only events
    at or after the cutoff drive transitions. When omitted, the full
    ledger is walked (used by the per-Person aggregation surface,
    which needs the canonical lifetime state).

    Pillar D Week 9-11 (ADR-0030 D132) extends with the TTL driver:

      * ``now=None`` (default) → TTL evaluation DISABLED. Matches the
        Week 4-5 behavior; existing callsites unchanged.
      * ``now=<utc dt>`` → TTL evaluation ENABLED. After the
        event-driven walk completes, threads whose current state is
        in the TTL-ELIGIBLE set (replied / classified / active) AND
        whose ``last_activity_ts < now - ttl_days days`` transition
        to ``dormant`` via the TTL driver. ``dormant`` threads are
        SKIPPED (overwriting category-driven dormant triggers would
        silently reclassify rejection-driven closed_lost outcomes as
        TTL-driven dormant in Pass O downstream).
        ``unsubscribed`` threads are SKIPPED (legal-liability
        invariant per ADR-0025 D97 + ADR-0028 D119 STAYS WITH FULL
        WEIGHT). The trigger field carries ``driver: "ttl"`` so
        downstream consumers can distinguish.

        **``now`` MUST be a UTC-aware datetime** (i.e.,
        ``tzinfo=timezone.utc``). Naive datetimes or non-UTC
        timezone-aware datetimes produce incorrect lexical
        comparisons against ledger timestamps (which always use the
        trailing-``Z`` UTC shape per the ledger's emit convention).
        The production callsite in :func:`reconcile.reconcile` uses
        ``datetime.now(timezone.utc)``; tests inject UTC-aware
        datetimes via :func:`datetime.datetime` with explicit
        ``tzinfo=timezone.utc``.
      * ``ttl_days=0`` → TTL evaluation skipped even when ``now`` is
        provided (operator-explicit disable for manual pipelines).

    Returns a dict mapping each ``ThreadKey`` (where one exists in
    the ledger) to the computed ``ThreadState``. Threads with no
    ``*_reply_received`` event are NOT in the result (the state
    machine starts at ``(none)``; absence is the implicit baseline).
    """
    states: dict[ThreadKey, ThreadState] = {}
    classified_index = _classified_thread_index(led)

    # Index: classified-event pair → suppression_added events
    # correlating back. ADR-0028 D119's
    # classified → unsubscribed transition driver.
    suppressed_pairs: set[tuple[str, str]] = set()
    for e in led.all_events():
        if e.get("type") != "suppression_added":
            continue
        src = e.get("source_reply_classified_event")
        if not isinstance(src, dict):
            continue
        mid = src.get("reply_message_id")
        ch = src.get("channel")
        if mid and ch:
            suppressed_pairs.add((str(mid), str(ch)))

    since_iso: str | None = None
    if since is not None:
        since_iso = (
            since.isoformat() if since.tzinfo
            else since.replace(tzinfo=timezone.utc).isoformat()
        )

    # Walk events chronologically (already sorted by ts in
    # ``Ledger._load_events``). For each driver event, compute the
    # would-be transition + commit it only if the new state has
    # higher priority than the current state for the thread.
    for e in led.all_events():
        t = e.get("type")
        ts = e.get("ts") or ""
        if since_iso is not None and ts < since_iso:
            continue
        person_id = e.get("person_id")
        if not person_id:
            continue

        # ``(none) → replied`` — first reply on the thread.
        if t in (
            "reply_received",
            "li_invite_reply_received",
            "li_dm_reply_received",
            "tw_dm_reply_received",
        ):
            channel = e.get("channel") or "email"
            thread_key = _extract_thread_key(
                e.to_dict() if hasattr(e, "to_dict") else dict(e),
            )
            if thread_key is None:
                continue
            tk = ThreadKey(person_id=person_id, channel=channel, thread_key=thread_key)
            cur = states.setdefault(tk, ThreadState())
            # Per ADR-0030 D132 — track per-thread last-activity for
            # TTL evaluation. Updated on EVERY driver event (not just
            # transitions that win priority), so a subsequent reply on
            # an already-classified thread resets the TTL window.
            if cur.last_activity_ts is None or ts > cur.last_activity_ts:
                cur.last_activity_ts = ts
            new_state = "replied"
            if cur.state is None or STATE_PRIORITY[new_state] > STATE_PRIORITY.get(
                cur.state, -1,
            ):
                prev = cur.state
                cur.state = new_state
                cur.trigger[new_state] = {
                    "reply_message_id": e.get("reply_message_id")
                    or e.get("gmail_message_id"),
                    "channel": channel,
                    "ts": ts,
                    "from_state": prev,
                }

        # ``replied → classified`` AND ``classified → active|dormant``
        # — every classified event drives a transition.
        elif t == "reply_classified":
            channel = e.get("channel") or "email"
            mid = e.get("reply_message_id")
            if not mid:
                continue
            pair_thread_ts = classified_index.get((str(mid), str(channel)))
            if pair_thread_ts is None or not pair_thread_ts[0]:
                # Can't resolve thread → can't drive a per-thread
                # transition. Skip silently (defensive — the resolve
                # path covers all live classifier emit shapes; a
                # malformed historical event lacks the correlation).
                continue
            thread_key = pair_thread_ts[0]
            tk = ThreadKey(person_id=person_id, channel=channel, thread_key=thread_key)
            cur = states.setdefault(tk, ThreadState())
            if cur.last_activity_ts is None or ts > cur.last_activity_ts:
                cur.last_activity_ts = ts
            category = e.get("category")

            # First — every classified event drives at least the
            # base ``replied → classified`` transition.
            new_state = "classified"
            if category in _CLASSIFIED_TO_ACTIVE_CATEGORIES:
                new_state = "active"
            elif category in _CLASSIFIED_TO_DORMANT_CATEGORIES:
                new_state = "dormant"

            if cur.state is None or STATE_PRIORITY[new_state] > STATE_PRIORITY.get(
                cur.state, -1,
            ):
                prev = cur.state
                cur.state = new_state
                cur.trigger[new_state] = {
                    "reply_message_id": mid,
                    "channel": channel,
                    "ts": ts,
                    "from_state": prev,
                }

        # ``classified → unsubscribed`` — suppression_added drives.
        elif t == "suppression_added":
            src = e.get("source_reply_classified_event")
            if not isinstance(src, dict):
                continue
            mid = src.get("reply_message_id")
            ch = src.get("channel")
            if not mid or not ch:
                continue
            pair_thread_ts = classified_index.get((str(mid), str(ch)))
            if pair_thread_ts is None or not pair_thread_ts[0]:
                continue
            thread_key = pair_thread_ts[0]
            tk = ThreadKey(
                person_id=person_id, channel=str(ch), thread_key=thread_key,
            )
            cur = states.setdefault(tk, ThreadState())
            if cur.last_activity_ts is None or ts > cur.last_activity_ts:
                cur.last_activity_ts = ts
            new_state = "unsubscribed"
            if cur.state is None or STATE_PRIORITY[new_state] > STATE_PRIORITY.get(
                cur.state, -1,
            ):
                prev = cur.state
                cur.state = new_state
                cur.trigger[new_state] = {
                    "reply_message_id": mid,
                    "channel": ch,
                    "ts": ts,
                    "from_state": prev,
                }

    # Per ADR-0030 D132 — apply the TTL driver AFTER the event-driven
    # walk. Threads whose current state is in the TTL-ELIGIBLE set
    # (replied / classified / active) AND whose last_activity_ts is
    # older than `now - ttl_days days` transition to dormant. The TTL
    # driver respects STATE_PRIORITY — `unsubscribed` (terminal-for-
    # legal-liability per ADR-0025 D97 + ADR-0028 D119) is NEVER
    # demoted. `dormant` threads (either category-driven via rejection
    # / ooo OR TTL-driven on a prior run) are SKIPPED — overwriting a
    # category-driven dormant trigger with TTL semantics would silently
    # reclassify rejection-driven `closed_lost` outcomes as TTL-driven
    # `dormant` outcomes downstream in Pass O (per the per-week review
    # P1 finding on the original Week 9-11 commit `bb6fcae` — the
    # original two-priority-guard form had dead-code in the first guard
    # and only protected `unsubscribed` in the second, leaving
    # `dormant` threads vulnerable to trigger overwrite).
    if now is not None and ttl_days > 0:
        ttl_cutoff_iso = (now - timedelta(days=ttl_days)).isoformat()
        # The state machine's last_activity_ts uses the ledger's
        # zulu-shape (e.g. `2026-05-22T10:00:00.000Z`). Normalise the
        # cutoff to the same shape for lexical comparison; ISO 8601
        # timestamps with consistent timezone suffixes sort lexically.
        # The ledger's shape is always trailing-`Z` (UTC); the cutoff
        # comes from a tz-aware datetime — `.isoformat()` yields
        # `+00:00` for UTC. Both sort lexically against each other
        # (the suffix difference doesn't affect the date portion's
        # ordering when both are UTC), but for safety we normalise to
        # the trailing-`Z` shape.
        if ttl_cutoff_iso.endswith("+00:00"):
            ttl_cutoff_iso = ttl_cutoff_iso[: -len("+00:00")] + "Z"
        for tk, cur in states.items():
            if cur.state is None or cur.last_activity_ts is None:
                continue
            # TTL-eligible set per ADR-0030 D132 — explicit allow-list
            # forecloses both the `dormant`-overwrite bug AND the
            # `unsubscribed`-demote bug by construction. A future state
            # added to the canonical STATES tuple MUST explicitly opt-in
            # here OR stay TTL-ineligible by default. This is the
            # priority-respecting design at the code layer — not a
            # discipline that depends on STATE_PRIORITY value lookups
            # staying correct as states are added.
            if cur.state not in ("replied", "classified", "active"):
                continue
            if cur.last_activity_ts < ttl_cutoff_iso:
                # TTL transition fires. The trigger carries
                # ``driver: "ttl"`` so downstream consumers (Pass O
                # outcome derivation, audit doc) can distinguish.
                prev = cur.state
                cur.state = "dormant"
                cur.trigger["dormant"] = {
                    "reply_message_id": None,
                    "channel": tk.channel,
                    "ts": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "from_state": prev,
                    "driver": TTL_TRIGGER_DRIVER,
                }

    return states


def _emitted_transitions(
    led: "_ledger.Ledger",
) -> set[tuple[str, str, str, str]]:
    """Build the idempotence key set for ``conversation_state_changed``.

    Per ADR-0028 D119 the emit-side idempotence key is
    ``(person_id, channel, thread_key, to_state)``. Re-running the pass
    over the same ledger produces no duplicate transitions.
    """
    out: set[tuple[str, str, str, str]] = set()
    for e in led.all_events():
        if e.get("type") != "conversation_state_changed":
            continue
        pid = e.get("person_id") or ""
        ch = e.get("channel") or ""
        tk = e.get("thread_key") or ""
        to_state = e.get("to_state") or ""
        if pid and ch and tk and to_state:
            out.add((str(pid), str(ch), str(tk), str(to_state)))
    return out


def build_state_change_payload(
    tk: ThreadKey,
    from_state: str | None,
    to_state: str,
    trigger: dict,
) -> dict:
    """Construct the ``conversation_state_changed`` event payload.

    Per ADR-0025 D98's event shape. Single source of truth across
    live + dry-run paths (mirrors the
    ``build_suppression_added_payload`` shape from
    ``orchestrator/auto_unsubscribe.py``).

    Pillar D Week 9-11 (ADR-0030 D132) extends the
    ``trigger_event_id`` dict with an optional ``driver:`` field
    when the transition was TTL-driven. The audit-doc consumers
    (Pillar G dashboards + Pass O outcome derivation) read the
    field to distinguish category-driven dormancy from
    TTL-driven dormancy.
    """
    trigger_id: dict = {
        "reply_message_id": trigger.get("reply_message_id"),
        "channel": trigger.get("channel"),
        "ts": trigger.get("ts"),
    }
    driver = trigger.get("driver")
    if driver:
        trigger_id["driver"] = driver
    payload: dict = {
        "type": "conversation_state_changed",
        "person_id": tk.person_id,
        "channel": tk.channel,
        "thread_key": tk.thread_key,
        "from_state": from_state,
        "to_state": to_state,
        "trigger_event_id": trigger_id,
        "_emitted_by": "conversation_state_machine",
    }
    return payload


def run_conversation_state_pass(
    *,
    led: "_ledger.Ledger",
    since: datetime,
    apply: bool,
    now: datetime | None = None,
    ttl_days: int = DEFAULT_CONVERSATION_TTL_DAYS,
) -> ConversationStatePassResult:
    """Walk the ledger; emit ``conversation_state_changed`` events.

    Per ADR-0028 D118 the pass:

    1. Computes the canonical per-thread state via
       :func:`compute_thread_states` (deterministic event-driven
       state computation).
    2. Builds the idempotence index from existing
       ``conversation_state_changed`` events.
    3. For each thread whose current state isn't yet pinned by a
       matching ledger event, emits one
       ``conversation_state_changed`` event per ADR-0025 D98's
       event shape.

    The pass is run-window-bounded by ``since`` (mirrors Pass G's
    cadence per ADR-0026 D105) — only threads whose driver event is
    in window contribute transitions. The full-ledger walk inside
    :func:`compute_thread_states` is the canonical source; ``since``
    bounds the emit-side so an operator running on a per-day cadence
    doesn't re-process arbitrarily-old threads on every run.

    Per ADR-0030 D132 + D133: when ``now`` is provided, the pass
    ALSO evaluates the TTL-driven ``* → dormant`` driver for threads
    whose last-activity is past ``ttl_days``. The TTL driver respects
    STATE_PRIORITY — terminal states (unsubscribed) are NOT demoted.

    Dry-run path: synthesizes the payloads + stamps ``_dry_run:
    True``; no ledger append. Same pattern as
    ``auto_unsubscribe.run_auto_unsubscribe``.
    """
    result = ConversationStatePassResult()

    states = compute_thread_states(
        led, since=since, now=now, ttl_days=ttl_days,
    )
    emitted = _emitted_transitions(led)

    for tk, ts in states.items():
        if ts.state is None:
            continue
        result.examined += 1
        # The pass emits the CURRENT canonical state. If the ledger
        # already has the matching ``(pid, ch, tk, to_state)`` event,
        # no-op. Per-state idempotence (NOT per-thread-history) — the
        # state machine's intermediate states are not all preserved
        # in the emit chain (the walk computes the highest-priority
        # transition driver; the pass emits ONE event per state-
        # destination, not the full historical chain).
        key = (tk.person_id, tk.channel, tk.thread_key, ts.state)
        if key in emitted:
            continue
        trigger = ts.trigger.get(ts.state) or {}
        from_state = trigger.get("from_state")
        payload = build_state_change_payload(
            tk, from_state, ts.state, trigger,
        )
        if apply:
            try:
                written = led.append(payload)
                result.synthesized.append(written)
            except (OSError, ValueError) as exc:
                result.errors.append(
                    f"ledger append failed for "
                    f"conversation_state_changed "
                    f"(person={tk.person_id}, channel={tk.channel}, "
                    f"thread_key={tk.thread_key}, to_state={ts.state}): "
                    f"{exc}"
                )
        else:
            payload["_dry_run"] = True
            result.synthesized.append(payload)

    return result


def derived_conversation_status(
    led: "_ledger.Ledger",
    person_id: str,
    *,
    thread_states: "dict[ThreadKey, ThreadState] | None" = None,
) -> str | None:
    """Per-Person aggregation of per-thread states per ADR-0028 D119.

    The aggregation: across all threads belonging to the Person, take
    the highest-priority state (per :data:`STATE_PRIORITY`). Used by
    Pass C extension to heal the ``conversation_status:`` Person
    frontmatter field.

    Returns the aggregated status string or ``None`` if the Person
    has no conversation threads (no ``*_reply_received`` event for
    the person_id).

    Mirrors the existing ``Ledger.derived_stage(person_id)`` shape
    from ``orchestrator/ledger.py`` so Pass C's extension to heal
    ``conversation_status:`` follows the same pattern as the existing
    ``pipeline_stage:`` heal.

    The optional ``thread_states`` parameter accepts a precomputed
    state map (the output of :func:`compute_thread_states`). Callers
    iterating over many Persons (e.g. Pass C's vault heal) should
    compute the map ONCE + pass it in to avoid O(N persons * full-
    ledger-walk) re-computation. When omitted, the full ledger is
    walked per call (the simple-callsite shape Pillar G dashboards
    use).
    """
    states = (
        thread_states if thread_states is not None
        else compute_thread_states(led)
    )
    best: str | None = None
    best_prio = -1
    for tk, ts in states.items():
        if tk.person_id != person_id:
            continue
        if ts.state is None:
            continue
        prio = STATE_PRIORITY.get(ts.state, -1)
        if prio > best_prio:
            best = ts.state
            best_prio = prio
    return best


__all__ = [
    "ConversationStatePassResult",
    "DEFAULT_CONVERSATION_TTL_DAYS",
    "STATES",
    "STATE_PRIORITY",
    "TTL_TRIGGER_DRIVER",
    "ThreadKey",
    "ThreadState",
    "build_state_change_payload",
    "compute_thread_states",
    "derived_conversation_status",
    "run_conversation_state_pass",
]
