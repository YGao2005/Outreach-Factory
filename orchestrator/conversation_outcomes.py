"""Pillar D Week 9-11 — win/loss attribution + conversation_outcome
event class.

Per ADR-0030 D129-D135. This module ships:

* :class:`ConversationOutcome` — the per-thread outcome dataclass.
* :data:`OUTCOMES` — the canonical outcome set.
* :data:`OUTCOME_PRIORITY` — priority used for per-Person aggregation.
* :func:`compute_conversation_outcomes` — walks the ledger + computes
  per-thread outcomes from the canonical conversation_state machine
  (per :mod:`orchestrator.conversation_state`) + send-side `*_confirmed`
  events (for attribution) + `calendar_booking_confirmed` events (for
  closed_won detection).
* :func:`derived_conversation_outcome` — per-Person aggregation.
* :func:`build_outcome_payload` — single source of truth for the
  emitted `conversation_outcome` event shape.
* :func:`run_conversation_outcomes_pass` — Pass O's inner primitive
  (wrapped by ``reconcile.run_pass_o``).

Why standalone (per ADR-0030 D129)
----------------------------------

The outcome derivation logic is non-trivial:

  * It depends on the conversation_state machine's terminal states
    (consumes :mod:`orchestrator.conversation_state`).
  * It depends on the dispatcher's send history (consumes
    ``*_confirmed`` events from Pillar B + C).
  * It optionally consumes ``calendar_booking_confirmed`` events for
    closed_won detection (per ADR-0030 D131).

A sibling module keeps :mod:`orchestrator.conversation_state` focused
on the state-transition primitive. Pillar G dashboards + Pillar I CLI
extensions import this module directly without dragging in the
classifier / handler / state-machine concerns.

Pillar G Week 6 (ADR-0055 D300-D306) adds the per-stage OTel span
instrumentation at the :func:`run_conversation_outcomes_pass` call
site via :func:`observability.traced_stage` — operators tracing the
Pass O run see the outcome-derivation pass as a named span with the
per-pass duration + emit count attributes. Privacy invariant per
ADR-0054 D297 holds — span attributes EXCLUDE the per-thread body
content + attribution body fields.

Per ADR-0030 D131 — attribution algorithm
-----------------------------------------

The winning/losing touch is the **most-recent ``*_confirmed`` event
on the SAME channel as the thread, for the same person, before the
outcome-driving event's timestamp**. If no such touch exists the
attribution is ``None`` (the recipient initiated contact OR an
operator-side hand-sent message landed outside the framework).

The same-channel rule reflects the per-channel state-machine
substrate: a reply on LinkedIn is correlated to LinkedIn touches; a
reply on email is correlated to email touches. Cross-channel
spillover (a person sees an email + replies on LinkedIn) is
attributed to the LinkedIn channel because the THREAD is on
LinkedIn. Cross-channel attribution (decay-weighted, multi-touch
shared-credit) is a Pillar G dashboard refinement, not a v1
ledger-event concern.

Per ADR-0030 D131 — outcome derivation map
------------------------------------------

  +----------------------------------+-------------------------+
  | Source state / signal            | Outcome                 |
  +==================================+=========================+
  | state == unsubscribed            | closed_unsubscribed     |
  +----------------------------------+-------------------------+
  | state == dormant via rejection   | closed_lost             |
  +----------------------------------+-------------------------+
  | state == dormant via ooo         | dormant                 |
  +----------------------------------+-------------------------+
  | state == dormant via TTL         | dormant                 |
  +----------------------------------+-------------------------+
  | state == active + cal booking    | closed_won              |
  | for person AFTER active transition                         |
  +----------------------------------+-------------------------+
  | state == active (no booking)     | (no outcome — pending)  |
  +----------------------------------+-------------------------+
  | state == classified              | (no outcome — pending)  |
  +----------------------------------+-------------------------+
  | state == replied                 | (no outcome — pending)  |
  +----------------------------------+-------------------------+

The asymmetric semantics for `dormant` (rejection → closed_lost;
ooo → dormant; TTL → dormant) capture the operator-meaningful
distinction: rejection is a HARD signal ("not interested"); ooo
is a SOFT signal ("temporarily unavailable; revisit"); TTL is an
INFERRED signal ("no response in N days"). Lumping all three to
closed_lost would over-state operator certainty about deal status.

Per ADR-0030 D130 — event shape
-------------------------------

.. code-block:: python

    {
        "type": "conversation_outcome",
        "person_id": "<pid>",
        "channel": "email | linkedin | twitter | calendar",
        "thread_key": "<thread identifier>",
        "outcome": "closed_won | closed_lost | closed_unsubscribed | dormant",
        "attributed_touch_intent_id": "<intent_id | None>",
        "triggering_event_id": {
            "type": "<event type that drove the outcome>",
            "channel": "<channel>",
            "ts": "<event ts>",
            # type-specific correlators (best-effort):
            # for reply_classified / suppression_added:
            #   "reply_message_id": ...
            # for calendar_booking_confirmed: "intent_id": ...
            # for ttl-driven dormancy: "driver": "ttl"
        },
        "ts": "<emit ts>",
        "_emitted_by": "conversation_outcomes",
    }

Per-thread idempotence
----------------------

Pass O's emit-side idempotence key is
``(person_id, channel, thread_key, outcome)``. The walk is
deterministic; running it twice over the same ledger produces no
duplicate outcomes. An outcome that subsequently UPGRADES (e.g., an
active thread transitions to closed_won when a booking lands) emits
a SECOND outcome event under the new key — the (pid, ch, tk, "closed_won")
tuple is distinct from (pid, ch, tk, "active"), and "active" never
emits today (active is non-terminal for outcome purposes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import conversation_state as _cs
import ledger as _ledger
from observability import traced_stage


# Per ADR-0030 D130 — canonical outcome set. Order reflects priority
# for per-Person aggregation (see OUTCOME_PRIORITY below).
OUTCOMES: tuple[str, ...] = (
    "dormant",
    "closed_lost",
    "closed_unsubscribed",
    "closed_won",
)


# Per ADR-0030 D134 — priority index for per-Person aggregation.
# `closed_won` (4) > `closed_unsubscribed` (3) > `closed_lost` (2)
# > `dormant` (1). The won-first priority reflects operator-facing
# signal: a person with one closed_won thread + one dormant thread
# is operationally "won." closed_unsubscribed beats closed_lost
# because the legal-liability surface is structurally weightier
# than a soft rejection.
OUTCOME_PRIORITY: dict[str, int] = {
    s: i + 1 for i, s in enumerate(OUTCOMES)
}


# Per ADR-0030 D130 — every emit carries this canonical
# `_emitted_by:` value. Tests + the cross-pillar audit consume the
# constant.
EMITTED_BY: str = "conversation_outcomes"


# Per ADR-0030 D131 — channels considered for attribution + outcome
# emission. Mirrors :data:`reconcile.REPLY_EVENT_TYPES`'s closed-set
# discipline + the conversation state machine's channel set.
_CHANNELS: frozenset[str] = frozenset({
    "email", "linkedin", "twitter", "calendar",
})


# Per ADR-0030 D131 — the closed set of `*_confirmed` event types
# the attribution walker reads to find the winning/losing touch.
# Mirrors `_OUTCOME_TYPES` in `orchestrator/ledger.py` filtered to
# successful confirmations; calendar_booking_confirmed is handled
# separately for closed_won attribution.
_TOUCH_CONFIRMED_TYPES: frozenset[str] = frozenset({
    "send_confirmed",                 # email
    "li_invite_confirmed",            # linkedin invite
    "li_dm_confirmed",                # linkedin DM
    "tw_dm_confirmed",                # twitter DM
})


# Per ADR-0030 D131 — the per-channel mapping from `*_confirmed`
# event type to the channel the conversation thread lives on. The
# attribution walker uses this to filter touches to same-channel
# touches only.
_TOUCH_CHANNEL_BY_TYPE: dict[str, str] = {
    "send_confirmed": "email",
    "li_invite_confirmed": "linkedin",
    "li_dm_confirmed": "linkedin",
    "tw_dm_confirmed": "twitter",
}


@dataclass(frozen=True)
class ConversationOutcome:
    """A per-thread outcome record per ADR-0030 D130.

    Constructed by :func:`compute_conversation_outcomes`. Emitted as
    a `conversation_outcome` ledger event by Pass O (see
    :func:`run_conversation_outcomes_pass`).

    The ``attributed_touch_intent_id`` is the intent_id of the
    winning/losing touch — the most-recent ``*_confirmed`` event on
    the SAME channel as the thread, for the same person, before the
    outcome-driving event. ``None`` when no prior framework-emitted
    touch exists.

    The ``triggering_event_id`` dict carries the correlator for the
    event that drove the outcome (reply_classified for closed_lost /
    dormant-via-ooo; suppression_added for closed_unsubscribed;
    calendar_booking_confirmed for closed_won;
    conversation_state_changed with driver:"ttl" for dormant-via-TTL).
    """

    person_id: str
    channel: str
    thread_key: str
    outcome: str
    ts: str
    attributed_touch_intent_id: str | None
    triggering_event_id: dict

    def __post_init__(self):
        if self.outcome not in OUTCOMES:
            raise ValueError(
                f"ConversationOutcome.outcome must be one of "
                f"{sorted(OUTCOMES)!r}; got {self.outcome!r}."
            )
        if self.channel not in _CHANNELS:
            raise ValueError(
                f"ConversationOutcome.channel must be one of "
                f"{sorted(_CHANNELS)!r}; got {self.channel!r}."
            )


@dataclass
class ConversationOutcomesPassResult:
    """Mirrors ``PassResult`` so Pass O integrates with reconcile.

    Lives here so the outcomes primitive may be invoked standalone
    (Pillar I CLI surface).
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


def _last_touch_by_thread(
    led: "_ledger.Ledger",
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Build the per-(person_id, channel) list of (ts, intent_id) touch
    pairs, sorted by ts ascending.

    Per ADR-0030 D131 — attribution looks up the most-recent
    `*_confirmed` event on the SAME channel as the thread, for the
    same person, before the outcome-driving event's timestamp. The
    walk runs once + builds a sorted list per (person, channel) for
    O(log N) lookup at attribution time.

    Calendar bookings are EXCLUDED from this index — they're the
    closed_won conversion SIGNAL, not the attributed touch. The
    attributed touch for a closed_won outcome is the most-recent
    same-channel touch BEFORE the booking (which is typically the
    LinkedIn / email touch that prompted the booking).
    """
    out: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for e in led.all_events():
        t = e.get("type")
        if t not in _TOUCH_CONFIRMED_TYPES:
            continue
        pid = e.get("person_id")
        ts = e.get("ts")
        iid = e.get("intent_id")
        if not pid or not ts or not iid:
            continue
        # `_TOUCH_CHANNEL_BY_TYPE` is the canonical mapping; the
        # event's `channel:` field SHOULD match per ADR-0014 D33 but
        # we use the closed-set mapping for safety (a malformed
        # historical event with the wrong channel field doesn't
        # confuse attribution).
        ch = _TOUCH_CHANNEL_BY_TYPE.get(t)
        if ch is None:
            continue
        out.setdefault((str(pid), ch), []).append((str(ts), str(iid)))
    # Sort each list by ts ascending.
    for k in out:
        out[k].sort()
    return out


def _attribute_touch(
    touches: dict[tuple[str, str], list[tuple[str, str]]],
    *,
    person_id: str,
    channel: str,
    before_ts: str,
) -> str | None:
    """Find the intent_id of the most-recent same-channel touch BEFORE
    the cutoff timestamp.

    Per ADR-0030 D131. Linear scan of the per-(person, channel) sorted
    list — bounded by the number of touches per person (typically <
    10 for B2B outreach). A future Pillar I optimization may switch
    to bisect_right when the per-person touch volume warrants.

    Returns the intent_id string or ``None`` when no qualifying touch
    exists.
    """
    bucket = touches.get((person_id, channel))
    if not bucket:
        return None
    last: str | None = None
    for ts, iid in bucket:
        if ts < before_ts:
            last = iid
        else:
            break
    return last


def _calendar_bookings_by_person(
    led: "_ledger.Ledger",
) -> dict[str, list[tuple[str, str]]]:
    """Build the per-person list of (ts, intent_id) calendar-booking
    pairs, sorted by ts ascending.

    Per ADR-0030 D131 — closed_won detection. A calendar_booking_
    confirmed event for the person AFTER a thread's active-transition
    timestamp drives the closed_won outcome.

    Calendar booking → person correlation today is per-person, NOT
    per-thread (Cal.com bookings don't carry the active thread_key).
    The closed_won attribution thus correlates BY PERSON — the
    earliest booking after the earliest active-transition wins.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for e in led.all_events():
        if e.get("type") != "calendar_booking_confirmed":
            continue
        pid = e.get("person_id")
        ts = e.get("ts")
        iid = e.get("intent_id") or ""
        if not pid or not ts:
            continue
        out.setdefault(str(pid), []).append((str(ts), str(iid)))
    for k in out:
        out[k].sort()
    return out


def _earliest_booking_after(
    bookings: dict[str, list[tuple[str, str]]],
    *, person_id: str, after_ts: str,
) -> tuple[str, str] | None:
    """Find the earliest (ts, intent_id) booking AFTER the cutoff.

    Returns the tuple or ``None`` when no qualifying booking exists.
    """
    bucket = bookings.get(person_id)
    if not bucket:
        return None
    for ts, iid in bucket:
        if ts > after_ts:
            return (ts, iid)
    return None


def _build_classified_category_index(
    led: "_ledger.Ledger",
) -> dict[tuple[str, str], str]:
    """Build the (reply_message_id, channel) → category index for
    rejection / ooo / interest discrimination.

    Per ADR-0030 D131 — the outcome derivation needs to distinguish:

      * dormant via rejection (category="rejection") → closed_lost
      * dormant via ooo (category="ooo") → dormant
      * active via interest (category="interest") → closed_won (if
        a booking lands)

    The walk reads the canonical `reply_classified` events directly
    — the SAME source as the state machine in
    :mod:`orchestrator.conversation_state`. Reading directly (rather
    than via emit-side `conversation_state_changed` events) means
    Pass O can run STANDALONE without requiring Pass N to have
    persisted state transitions first; the outcome derivation is
    method-agnostic AND emit-side-agnostic.
    """
    out: dict[tuple[str, str], str] = {}
    for e in led.all_events():
        if e.get("type") != "reply_classified":
            continue
        mid = e.get("reply_message_id")
        ch = e.get("channel")
        cat = e.get("category")
        if mid and ch and cat:
            out[(str(mid), str(ch))] = str(cat)
    return out


def _classify_dormant_driver(
    trigger: dict,
    *,
    classified_category: dict[tuple[str, str], str],
) -> str:
    """Determine the dormant driver from the state-machine trigger.

    Per ADR-0030 D131 — returns one of ``{"rejection", "ooo", "ttl"}``.

    The trigger dict comes from :class:`conversation_state.ThreadState`'s
    ``trigger["dormant"]`` slot. When the TTL driver fires (per
    :data:`conversation_state.TTL_TRIGGER_DRIVER`), the trigger
    carries ``driver: "ttl"``. Otherwise the dormant transition was
    category-driven (rejection or ooo); the trigger's
    `reply_message_id` + `channel` correlate to the classified event
    whose category resolves the distinction.
    """
    if trigger.get("driver") == _cs.TTL_TRIGGER_DRIVER:
        return "ttl"
    mid = trigger.get("reply_message_id")
    ch = trigger.get("channel")
    if mid and ch:
        cat = classified_category.get((str(mid), str(ch)))
        if cat == "rejection":
            return "rejection"
        if cat == "ooo":
            return "ooo"
    # Defensive: a dormant trigger without a known category cross-
    # reference. Treat as 'ooo' (soft dormancy) — avoids over-confident
    # closed_lost attribution.
    return "ooo"


def _build_unsubscribe_trigger(trigger: dict, channel: str) -> dict:
    """Build the triggering_event_id dict for the unsubscribed outcome.

    The state-machine's trigger field carries the suppression_added
    event's reply_message_id correlator (the source-classified event).
    Reshape into the canonical conversation_outcome triggering_event_id
    payload.
    """
    return {
        "type": "suppression_added",
        "channel": channel,
        "ts": trigger.get("ts"),
        "reply_message_id": trigger.get("reply_message_id"),
    }


def _build_dormant_trigger(trigger: dict, channel: str, driver: str) -> dict:
    """Build the triggering_event_id dict for the dormant outcome.

    Distinguishes TTL-driven dormancy (driver:"ttl") from category-
    driven (reply_classified is the trigger).

    The ``driver`` field is INCLUDED only when the driver is ``"ttl"``
    — matches ADR-0030 D130's event shape spec (the driver field is
    type-specific best-effort, present for TTL-driven outcomes only).
    Per the per-week review P3-A finding on the original Week 9-11
    commit `bb6fcae`: emitting ``driver: None`` for non-TTL cases
    pollutes operator ``--json`` output + Pillar G dashboard queries
    with a meaningless null field. The conditional spread form below
    preserves the dict-shape symmetry across TTL + non-TTL paths.
    """
    payload: dict = {
        "type": (
            "conversation_state_changed" if driver == "ttl"
            else "reply_classified"
        ),
        "channel": channel,
        "ts": trigger.get("ts"),
        "reply_message_id": trigger.get("reply_message_id"),
    }
    if driver == "ttl":
        payload["driver"] = "ttl"
    return payload


def _build_per_thread_active_transition_ts(
    states: dict["_cs.ThreadKey", "_cs.ThreadState"],
) -> dict["_cs.ThreadKey", str]:
    """For threads currently in `active` state, the ts of the
    active-state transition trigger.

    Used by closed_won detection — a calendar_booking_confirmed AFTER
    this ts drives the won outcome.
    """
    out: dict["_cs.ThreadKey", str] = {}
    for tk, ts in states.items():
        if ts.state != "active":
            continue
        trig = ts.trigger.get("active") or {}
        trig_ts = trig.get("ts")
        if trig_ts:
            out[tk] = str(trig_ts)
    return out


def compute_conversation_outcomes(
    led: "_ledger.Ledger",
    *,
    now: datetime | None = None,
    ttl_days: int = _cs.DEFAULT_CONVERSATION_TTL_DAYS,
) -> dict["_cs.ThreadKey", ConversationOutcome]:
    """Walk the ledger; compute per-thread outcomes per ADR-0030.

    Per ADR-0030 D131:

      1. Compute canonical thread states via
         :func:`orchestrator.conversation_state.compute_thread_states`
         (passes through `now` + `ttl_days` so TTL-driven dormant
         transitions are visible).
      2. For each terminal-state thread, determine the outcome
         (per the D131 derivation map).
      3. For each outcome, attribute to the winning/losing touch
         (most-recent same-channel `*_confirmed` event for the
         person, before the outcome-driving event).
      4. Build the triggering_event_id dict from the appropriate
         conversation_state_changed / suppression_added /
         calendar_booking_confirmed event.

    Returns a dict mapping each terminal-state ThreadKey to the
    computed :class:`ConversationOutcome`. Threads in non-terminal
    states (replied / classified / active without booking) are NOT
    in the result.

    Per ADR-0030 D131 — the outcome computation is deterministic +
    idempotent. Re-running over the same ledger produces the same
    outcomes.
    """
    states = _cs.compute_thread_states(
        led, now=now, ttl_days=ttl_days,
    )
    touches = _last_touch_by_thread(led)
    bookings = _calendar_bookings_by_person(led)
    classified_category = _build_classified_category_index(led)
    active_transitions = _build_per_thread_active_transition_ts(states)

    out: dict["_cs.ThreadKey", ConversationOutcome] = {}

    for tk, ts in states.items():
        if ts.state is None:
            continue

        outcome: str | None = None
        triggering: dict | None = None
        outcome_ts: str | None = None

        if ts.state == "unsubscribed":
            outcome = "closed_unsubscribed"
            unsub_trig = ts.trigger.get("unsubscribed") or {}
            triggering = _build_unsubscribe_trigger(unsub_trig, tk.channel)
            outcome_ts = unsub_trig.get("ts") or ts.last_activity_ts

        elif ts.state == "dormant":
            dormant_trig = ts.trigger.get("dormant") or {}
            driver = _classify_dormant_driver(
                dormant_trig, classified_category=classified_category,
            )
            outcome = "closed_lost" if driver == "rejection" else "dormant"
            triggering = _build_dormant_trigger(
                dormant_trig, tk.channel, driver,
            )
            outcome_ts = dormant_trig.get("ts") or ts.last_activity_ts

        elif ts.state == "active":
            # closed_won requires a calendar_booking_confirmed for
            # the person AFTER the active-transition ts.
            active_ts = active_transitions.get(tk)
            if active_ts:
                booking = _earliest_booking_after(
                    bookings, person_id=tk.person_id,
                    after_ts=active_ts,
                )
                if booking is not None:
                    booking_ts, booking_iid = booking
                    outcome = "closed_won"
                    triggering = {
                        "type": "calendar_booking_confirmed",
                        "channel": "calendar",
                        "ts": booking_ts,
                        "intent_id": booking_iid,
                    }
                    outcome_ts = booking_ts

        # Non-terminal states (replied / classified / active-without-
        # booking) → no outcome.
        if outcome is None:
            continue

        # Attribution — look up most-recent same-channel touch BEFORE
        # the outcome-driving event.
        attribution_cutoff = outcome_ts or ts.last_activity_ts or ""
        attributed_iid = _attribute_touch(
            touches,
            person_id=tk.person_id,
            channel=tk.channel,
            before_ts=attribution_cutoff,
        )

        out[tk] = ConversationOutcome(
            person_id=tk.person_id,
            channel=tk.channel,
            thread_key=tk.thread_key,
            outcome=outcome,
            ts=outcome_ts or ts.last_activity_ts or "",
            attributed_touch_intent_id=attributed_iid,
            triggering_event_id=dict(triggering) if triggering else {},
        )

    return out


def _emitted_outcomes(
    led: "_ledger.Ledger",
) -> set[tuple[str, str, str, str]]:
    """Build the idempotence key set for `conversation_outcome` events.

    Per ADR-0030 D130 the emit-side idempotence key is
    ``(person_id, channel, thread_key, outcome)``. Re-running the
    pass produces no duplicate outcome events.
    """
    out: set[tuple[str, str, str, str]] = set()
    for e in led.all_events():
        if e.get("type") != "conversation_outcome":
            continue
        pid = e.get("person_id") or ""
        ch = e.get("channel") or ""
        tk = e.get("thread_key") or ""
        outcome = e.get("outcome") or ""
        if pid and ch and tk and outcome:
            out.add((str(pid), str(ch), str(tk), str(outcome)))
    return out


def build_outcome_payload(outcome: ConversationOutcome) -> dict:
    """Construct the `conversation_outcome` event payload.

    Per ADR-0030 D130's event shape. Single source of truth across
    live + dry-run paths (mirrors :func:`conversation_state.
    build_state_change_payload`).
    """
    return {
        "type": "conversation_outcome",
        "person_id": outcome.person_id,
        "channel": outcome.channel,
        "thread_key": outcome.thread_key,
        "outcome": outcome.outcome,
        "attributed_touch_intent_id": outcome.attributed_touch_intent_id,
        "triggering_event_id": dict(outcome.triggering_event_id),
        "ts": outcome.ts,
        "_emitted_by": EMITTED_BY,
    }


def run_conversation_outcomes_pass(
    *,
    led: "_ledger.Ledger",
    apply: bool,
    now: datetime | None = None,
    ttl_days: int = _cs.DEFAULT_CONVERSATION_TTL_DAYS,
) -> ConversationOutcomesPassResult:
    """Walk the ledger; emit `conversation_outcome` events.

    Per ADR-0030 D133. The pass:

    1. Computes per-thread outcomes via
       :func:`compute_conversation_outcomes`.
    2. Builds the idempotence index from existing `conversation_
       outcome` events.
    3. For each terminal-state thread whose outcome isn't yet pinned
       by a matching ledger event, emits one `conversation_outcome`
       event per ADR-0030 D130's shape.

    Pass O is NOT run-window-bounded by `since` (unlike Pass N / Pass
    G). The outcome computation reads the canonical thread state +
    looks BACK to attribute the winning touch; a `since` window would
    arbitrarily exclude past touches from attribution. The
    idempotence index handles "did we already emit this outcome?" so
    re-runs are cheap.

    Dry-run path: synthesizes the payloads + stamps ``_dry_run:
    True``; no ledger append. Same pattern as Pass M / Pass N.
    """
    # Per ADR-0055 D302 — wrap the pass in a win_loss-stage span so
    # operators see per-Pass-O timing in the OTel tracing backend.
    # The per-Person outcome attributes flow through the inner per-
    # Person operations via the standard ``conversation_outcome``
    # event emission surface (the per-Person event carries
    # person_id + channel + outcome fields).
    with traced_stage("win_loss", "derive_outcomes"):
        result = ConversationOutcomesPassResult()

        outcomes = compute_conversation_outcomes(
            led, now=now, ttl_days=ttl_days,
        )
        emitted = _emitted_outcomes(led)

        for tk, oc in outcomes.items():
            result.examined += 1
            key = (tk.person_id, tk.channel, tk.thread_key, oc.outcome)
            if key in emitted:
                continue
            payload = build_outcome_payload(oc)
            if apply:
                try:
                    written = led.append(payload)
                    result.synthesized.append(written)
                except (OSError, ValueError) as exc:
                    result.errors.append(
                        f"ledger append failed for conversation_outcome "
                        f"(person={tk.person_id}, channel={tk.channel}, "
                        f"thread_key={tk.thread_key}, outcome={oc.outcome}): "
                        f"{exc}"
                    )
            else:
                payload["_dry_run"] = True
                result.synthesized.append(payload)

        return result


def derived_conversation_outcome(
    led: "_ledger.Ledger",
    person_id: str,
    *,
    outcomes: "dict[_cs.ThreadKey, ConversationOutcome] | None" = None,
) -> str | None:
    """Per-Person aggregation of per-thread outcomes per ADR-0030 D134.

    Across all threads belonging to the Person, take the highest-
    priority outcome (per :data:`OUTCOME_PRIORITY`). Used by Pillar G
    dashboards + future Pillar I CLI surfaces.

    Returns the aggregated outcome string or ``None`` if the Person
    has no terminal-state threads.

    Mirrors :func:`conversation_state.derived_conversation_status`'s
    interface so callers iterating over many Persons (Pillar G
    dashboards) can precompute the per-thread outcome map ONCE +
    pass it in via the ``outcomes`` kwarg, avoiding O(N persons *
    full-ledger-walk) re-computation.
    """
    oc_map = (
        outcomes if outcomes is not None
        else compute_conversation_outcomes(led)
    )
    best: str | None = None
    best_prio = -1
    for tk, oc in oc_map.items():
        if tk.person_id != person_id:
            continue
        prio = OUTCOME_PRIORITY.get(oc.outcome, -1)
        if prio > best_prio:
            best = oc.outcome
            best_prio = prio
    return best


__all__ = [
    "ConversationOutcome",
    "ConversationOutcomesPassResult",
    "EMITTED_BY",
    "OUTCOMES",
    "OUTCOME_PRIORITY",
    "build_outcome_payload",
    "compute_conversation_outcomes",
    "derived_conversation_outcome",
    "run_conversation_outcomes_pass",
]
