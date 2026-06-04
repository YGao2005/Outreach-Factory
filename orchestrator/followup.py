"""Follow-up cadence engine - deterministic, read-only ledger walk.

The pipeline's first touch is a single cold email; then it stops. Cold outreach
is mostly follow-ups. This module decides WHO is due for WHICH follow-up touch
NOW, by READING the ledger (the source of truth), deterministically. It is the
timing/eligibility brain only.

The spine invariant (do not violate)
------------------------------------
The ledger is the source of truth; the vault is a denormalized view. Eligibility
is computed by READING the ledger (confirmed sends with timestamps + replies +
unsubscribes + bounces). This engine is a PURE READ that produces a worklist; it
does NOT send, does NOT mutate the vault, and absolutely does NOT bypass the send
gates. Every follow-up send still passes suppression + cooldown + daily cap +
warming ceiling at send time, exactly like a first touch (see
``skills/send-outreach/scripts/send_queued.py``). The engine decides ELIGIBILITY
and TIMING only.

This mirrors the read-only, ledger-walking shape of ``orchestrator/funnel.py`` and
the reconcile passes: a pure function over events + a config + a clock.

Cadence model (v1, email only)
------------------------------
A "touch" is a confirmed outbound email (a ``send_confirmed`` on the email
channel). Touch 1 is the initial cold email; the configured ``steps`` are the
follow-ups after it (touch 2, touch 3, ...). A person is DUE for their next
follow-up when:

  * they have at least one confirmed touch, and
  * the count of touches is below ``max_touches`` and there is still a
    configured step for the next follow-up, and
  * NO terminating event (reply / unsubscribe / bounce / manual stop) has landed
    AFTER the last touch, and
  * the configured number of business days for the next step has elapsed since
    the last touch (weekends skipped).

A reply, unsubscribe, or bounce after the last touch CANCELS all pending
follow-ups; this is re-derived from the ledger on every run, so there is no
stale "scheduled" state that can survive a reply.

The ``followup_step`` field
---------------------------
Each send event is tagged with ``followup_step`` = the number of confirmed
touches that preceded it (0 for the cold email, 1 for the first follow-up, 2 for
the second). The same value is denormalized onto the Person note by vault
migration 0006 so ``status`` + the dispatch skill can report per-step. The
ledger stays the source of truth; the tag is for reporting and is cross-checked,
never trusted, by the eligibility math.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# Bare import per the orchestrator/ scripts' import convention (added to
# sys.path by conftest.py + the send path's bootstrap). The engine imports
# ONLY the ledger + stdlib so the lean send path can consult it without
# re-welding to the heavy operations tier (see tests/test_import_graph_lean.py).
import ledger as _ledger  # noqa: E402


# ---------------------------------------------------------------------------
# Defaults (mirror config-template/config.example.yml `followup:` block)
# ---------------------------------------------------------------------------

#: Opt-in: off by default. A greenfield install never sends follow-ups until
#: the operator sets ``followup.enabled: true``.
DEFAULT_ENABLED: bool = False

#: Touch 1 (the cold email) + 2 follow-ups.
DEFAULT_MAX_TOUCHES: int = 3

#: The default cadence: touch 2 at +3 business days, touch 3 at +5 business days.
DEFAULT_STEP_BUSINESS_DAYS: tuple[int, ...] = (3, 5)

#: The terminating signals that cancel pending follow-ups. Operator-tunable via
#: ``followup.stop_on``. The tokens map to ledger event types in
#: :data:`_STOP_TOKEN_EVENT_TYPES`.
DEFAULT_STOP_ON: frozenset[str] = frozenset({"reply", "unsubscribe", "bounce"})

#: Keep the human review gate by default (drafted -> ready stays manual).
DEFAULT_AUTO_SEND: bool = False

#: A confirmed email touch. Email-only in v1 (cross-channel sequencing is a
#: later step). A ``send_confirmed`` carries ``channel: email`` per the send
#: path's emit + the reconcile Pass A synthesis, so counting these is the
#: ledger-derived touch count.
_CONFIRMED_TOUCH_TYPE: str = "send_confirmed"
_TOUCH_CHANNEL: str = "email"

#: Map each ``stop_on`` token to the ledger event type(s) that realize it.
#:
#:   * ``reply``       -> ``reply_received`` (an inbound email reply).
#:   * ``unsubscribe`` -> ``suppression_added`` (the CAN-SPAM suppression write;
#:     the load-bearing legal action, per the conversation state machine's
#:     ``classified -> unsubscribed`` driver).
#:   * ``bounce``      -> ``bounce_detected``.
#:
#: A ``followup_stopped`` event (operator-initiated manual stop) ALWAYS cancels,
#: independent of ``stop_on`` - see :data:`_MANUAL_STOP_TYPE`.
_STOP_TOKEN_EVENT_TYPES: dict[str, frozenset[str]] = {
    "reply": frozenset({"reply_received"}),
    "unsubscribe": frozenset({"suppression_added"}),
    "bounce": frozenset({"bounce_detected"}),
}

#: Operator-initiated manual stop. Honored regardless of ``stop_on`` so an
#: operator can always halt a sequence by appending one event.
_MANUAL_STOP_TYPE: str = "followup_stopped"

#: The draft register a follow-up reuses (the existing re-engagement register in
#: skills/draft-outreach: a short bump for touch 2, a brief breakup for touch 3).
FOLLOWUP_REGISTER: str = "re-engagement"


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FollowupStep:
    """One configured follow-up step.

    ``after_business_days`` is the delay measured from the PRIOR touch (skipping
    weekends) before this follow-up becomes due.
    """

    after_business_days: int


@dataclass(frozen=True)
class CadenceConfig:
    """The operator-tunable follow-up cadence (the ``followup:`` config block).

    The cadence schedule lives in ``config.yml`` (operator-tunable), NOT the
    policy engine. The policy engine keeps owning HARD caps + cooldowns; the
    cadence is a softer per-operator schedule. The follow-up send still hits the
    policy gates.
    """

    enabled: bool = DEFAULT_ENABLED
    max_touches: int = DEFAULT_MAX_TOUCHES
    steps: tuple[FollowupStep, ...] = field(
        default_factory=lambda: tuple(
            FollowupStep(n) for n in DEFAULT_STEP_BUSINESS_DAYS
        )
    )
    stop_on: frozenset[str] = DEFAULT_STOP_ON
    auto_send: bool = DEFAULT_AUTO_SEND

    def stop_event_types(self) -> frozenset[str]:
        """The concrete ledger event types that cancel a sequence for this
        config: the union of every configured ``stop_on`` token's types, plus
        the always-on manual-stop type."""
        types: set[str] = {_MANUAL_STOP_TYPE}
        for token in self.stop_on:
            types |= _STOP_TOKEN_EVENT_TYPES.get(token, frozenset())
        return frozenset(types)


@dataclass(frozen=True)
class FollowupAction:
    """One due follow-up: who, which step, and the prior-touch context.

    Returned by :func:`compute_due_followups`. Carries no body / no email /
    nothing the privacy invariant forbids in an aggregate surface - just the
    ``person_id`` worklist key + the step bookkeeping. The dispatch skill turns
    each action into a re-engagement draft that still passes every send gate.
    """

    #: The Person.id this follow-up is for.
    person_id: str
    #: 1-indexed follow-up number (1 = first follow-up = touch 2).
    next_step: int
    #: The absolute touch number this send will be (= prior touches + 1).
    touch_no: int
    #: The configured business-day delay for this step (the one that elapsed).
    after_business_days: int
    #: How many business days have actually elapsed since the last touch.
    business_days_waited: int
    #: ISO ts of the last confirmed touch (the delay anchor).
    last_touch_ts: str
    #: The intent_id of the last confirmed touch (prior-touch context for the
    #: draft + attribution); ``None`` if the confirmed event lacked one.
    last_touch_intent_id: str | None
    #: The draft register the follow-up reuses.
    register: str = FOLLOWUP_REGISTER


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

#: Module-level default, ready to use when no config block is present.
DEFAULT_CADENCE: CadenceConfig = CadenceConfig()


def cadence_config_from_dict(block: object) -> CadenceConfig:
    """Parse the ``followup:`` config block into a :class:`CadenceConfig`.

    Refuse-loud on malformed input (the project's refuse-don't-guess
    discipline): a typo in a delay or a negative ``max_touches`` raises
    :class:`ValueError` rather than silently sending on a wrong schedule.

    ``block`` is the value of the top-level ``followup:`` key in ``config.yml``
    (a dict), or ``None`` when the key is absent. ``None`` / an empty dict
    yields :data:`DEFAULT_CADENCE` (opt-in off).
    """
    if block is None:
        return DEFAULT_CADENCE
    if not isinstance(block, dict):
        raise ValueError(
            f"followup: config block must be a mapping, got {type(block).__name__}"
        )

    enabled = bool(block.get("enabled", DEFAULT_ENABLED))

    raw_max = block.get("max_touches", DEFAULT_MAX_TOUCHES)
    try:
        max_touches = int(raw_max)
    except (TypeError, ValueError):
        raise ValueError(f"followup.max_touches must be an int, got {raw_max!r}")
    if max_touches < 1:
        raise ValueError(
            f"followup.max_touches must be >= 1 (touch 1 is the cold email), "
            f"got {max_touches}"
        )

    raw_steps = block.get("steps")
    if raw_steps is None:
        steps = tuple(FollowupStep(n) for n in DEFAULT_STEP_BUSINESS_DAYS)
    else:
        if not isinstance(raw_steps, (list, tuple)):
            raise ValueError(
                f"followup.steps must be a list, got {type(raw_steps).__name__}"
            )
        steps_list: list[FollowupStep] = []
        for i, step in enumerate(raw_steps):
            if not isinstance(step, dict) or "after_business_days" not in step:
                raise ValueError(
                    f"followup.steps[{i}] must be a mapping with "
                    f"after_business_days, got {step!r}"
                )
            try:
                n = int(step["after_business_days"])
            except (TypeError, ValueError):
                raise ValueError(
                    f"followup.steps[{i}].after_business_days must be an int, "
                    f"got {step['after_business_days']!r}"
                )
            if n < 1:
                raise ValueError(
                    f"followup.steps[{i}].after_business_days must be >= 1, "
                    f"got {n}"
                )
            steps_list.append(FollowupStep(n))
        steps = tuple(steps_list)

    raw_stop = block.get("stop_on")
    if raw_stop is None:
        stop_on = DEFAULT_STOP_ON
    else:
        if not isinstance(raw_stop, (list, tuple)):
            raise ValueError(
                f"followup.stop_on must be a list, got {type(raw_stop).__name__}"
            )
        unknown = [t for t in raw_stop if t not in _STOP_TOKEN_EVENT_TYPES]
        if unknown:
            raise ValueError(
                f"followup.stop_on has unknown token(s) {unknown!r}; "
                f"allowed: {sorted(_STOP_TOKEN_EVENT_TYPES)!r}"
            )
        stop_on = frozenset(raw_stop)

    auto_send = bool(block.get("auto_send", DEFAULT_AUTO_SEND))

    return CadenceConfig(
        enabled=enabled,
        max_touches=max_touches,
        steps=steps,
        stop_on=stop_on,
        auto_send=auto_send,
    )


# ---------------------------------------------------------------------------
# Business-day arithmetic (no new dependency)
# ---------------------------------------------------------------------------


def _count_weekdays(a: date, b: date) -> int:
    """Number of weekdays (Mon-Fri) in the inclusive range ``[a, b]``.

    Returns 0 when ``b < a``. Uses a closed-form full-weeks + remainder count
    so it stays O(1) regardless of how far apart the dates are.
    """
    if b < a:
        return 0
    days = (b - a).days + 1
    full_weeks, rem = divmod(days, 7)
    count = full_weeks * 5
    start = a.weekday()  # Mon=0 .. Sun=6
    for i in range(rem):
        if (start + i) % 7 < 5:
            count += 1
    return count


def business_days_between(start: datetime, end: datetime) -> int:
    """Business days elapsed strictly AFTER ``start``'s date, through ``end``'s
    date (inclusive of ``end``'s date). Weekends are skipped.

    Examples (Mon=0):

      * send Monday, now Thursday  -> Tue, Wed, Thu = 3 business days.
      * send Friday, now next Wed  -> Mon, Tue, Wed = 3 (Sat/Sun skipped).

    Returns 0 when ``end`` is on or before ``start``'s date. Both inputs are
    treated as UTC dates (the ledger ts shape is trailing-``Z`` UTC).
    """
    sd = start.astimezone(timezone.utc).date()
    ed = end.astimezone(timezone.utc).date()
    if ed <= sd:
        return 0
    return _count_weekdays(sd + timedelta(days=1), ed)


def _parse_iso(s: str | None) -> datetime | None:
    """Parse an ISO-8601 UTC ts; return ``None`` on missing/malformed input.

    Mirrors :func:`funnel._parse_iso`: naive timestamps are promoted to UTC so
    the business-day arithmetic never compares mixed-awareness datetimes.
    """
    if not isinstance(s, str) or not s:
        return None
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Ledger walk
# ---------------------------------------------------------------------------


def _coerce_event(ev: object) -> dict:
    """Accept either a raw event dict or a :class:`ledger.Event`."""
    if hasattr(ev, "to_dict"):
        return ev.to_dict()  # type: ignore[attr-defined]
    return dict(ev)  # type: ignore[arg-type]


@dataclass
class _PersonSequence:
    """The per-person follow-up state derived from one ledger walk."""

    touches: list[dict] = field(default_factory=list)        # confirmed sends
    terminators: list[str] = field(default_factory=list)     # terminator ts list


def _walk(events: Iterable[object], cadence: CadenceConfig) -> dict[str, _PersonSequence]:
    """Single pass over the events: per person, gather confirmed email touches +
    the timestamps of any terminating events.

    Read-only: no ``led.append``. Mirrors funnel's aggregation walk.
    """
    stop_types = cadence.stop_event_types()
    by_person: dict[str, _PersonSequence] = defaultdict(_PersonSequence)
    for raw in events:
        ev = _coerce_event(raw)
        pid = ev.get("person_id")
        if not pid:
            continue
        t = ev.get("type")
        if t == _CONFIRMED_TOUCH_TYPE and (ev.get("channel") or _TOUCH_CHANNEL) == _TOUCH_CHANNEL:
            by_person[pid].touches.append(ev)
        elif t in stop_types:
            ts = ev.get("ts") or ""
            if ts:
                by_person[pid].terminators.append(ts)
    return by_person


def _due_action_for_sequence(
    pid: str, seq: _PersonSequence, cadence: CadenceConfig, *, now: datetime,
) -> FollowupAction | None:
    """Compute the single due :class:`FollowupAction` for one person's sequence,
    or ``None`` if not due (no touch yet / cancelled / capped / delay not
    elapsed). The whole eligibility decision lives here so the send-gate
    authorization and the worklist share ONE source of truth.
    """
    touches = seq.touches
    if not touches:
        return None
    touches_sorted = sorted(touches, key=lambda e: e.get("ts") or "")
    total_touches = len(touches_sorted)
    last = touches_sorted[-1]
    last_ts = last.get("ts") or ""

    # Cancel: any terminating event AFTER the last touch re-derives "they
    # responded / opted out / bounced" from the ledger every run. No stale
    # scheduled state can survive a reply.
    if any(t_ts > last_ts for t_ts in seq.terminators):
        return None

    # Never exceed max_touches, and only if a step is configured for the next
    # follow-up. ``next_step_index`` is 0-indexed into ``steps``.
    if total_touches >= cadence.max_touches:
        return None
    next_step_index = total_touches - 1
    if next_step_index >= len(cadence.steps):
        return None

    delay = cadence.steps[next_step_index].after_business_days
    last_dt = _parse_iso(last_ts)
    if last_dt is None:
        return None
    waited = business_days_between(last_dt, now)
    if waited < delay:
        return None

    return FollowupAction(
        person_id=pid,
        next_step=next_step_index + 1,
        touch_no=total_touches + 1,
        after_business_days=delay,
        business_days_waited=waited,
        last_touch_ts=last_ts,
        last_touch_intent_id=last.get("intent_id"),
    )


def compute_due_followups(
    events: Iterable[object],
    cadence: CadenceConfig = DEFAULT_CADENCE,
    *,
    now: datetime,
) -> list[FollowupAction]:
    """Return the deterministic worklist of follow-ups due as of ``now``.

    PURE read over ``events`` (dicts or :class:`ledger.Event`) - the signature
    the spec names: ``compute_due_followups(events, cadence_config, now)``. For
    each person whose last confirmed email touch is at least the step delay old,
    with NO terminating event since, and under ``max_touches``, the result holds
    exactly one due action.

    Returns ``[]`` when ``cadence.enabled`` is False (opt-in off). The result is
    sorted by ``(last_touch_ts, person_id)`` for a stable operator-facing order.
    """
    if not cadence.enabled:
        return []
    by_person = _walk(events, cadence)
    actions: list[FollowupAction] = []
    for pid, seq in by_person.items():
        action = _due_action_for_sequence(pid, seq, cadence, now=now)
        if action is not None:
            actions.append(action)
    actions.sort(key=lambda a: (a.last_touch_ts, a.person_id))
    return actions


def compute_due_followups_from_ledger(
    led: _ledger.Ledger,
    cadence: CadenceConfig = DEFAULT_CADENCE,
    *,
    now: datetime,
) -> list[FollowupAction]:
    """Convenience wrapper: walk a :class:`ledger.Ledger`'s events."""
    return compute_due_followups(led.all_events(), cadence, now=now)


def is_followup_due(
    events: Iterable[object],
    person_id: str,
    cadence: CadenceConfig = DEFAULT_CADENCE,
    *,
    now: datetime,
) -> FollowupAction | None:
    """The send-gate authorization: is THIS person genuinely due for their next
    follow-up touch right now, per the ledger?

    Returns the :class:`FollowupAction` if due, else ``None``. The send path
    consults this to refine its duplicate-send guardrail (``already_sent``): a
    second send is permitted only when the deterministic engine, re-derived from
    the ledger at send time, says the person is due. This is NOT a bypass - the
    follow-up still passes suppression + cooldown + daily cap + warming below the
    dedup check, exactly like a first touch.

    Returns ``None`` when ``cadence.enabled`` is False (the dedup stays strict).
    """
    if not cadence.enabled:
        return None
    by_person = _walk(events, cadence)
    seq = by_person.get(person_id)
    if seq is None:
        return None
    return _due_action_for_sequence(person_id, seq, cadence, now=now)


def derive_followup_steps(events: Iterable[object]) -> dict[str, int]:
    """Per-person ``followup_step`` = number of follow-up touches already sent
    (= confirmed email touches - 1), for the vault-0006 denormalization.

    A person with only the cold touch maps to 0 (cold sent, 0 follow-ups); after
    the first follow-up, 1; after the second, 2. Persons with no confirmed touch
    are absent from the result (absent field = "no sequence yet"). The ledger is
    the source of truth; the vault field mirrors this value.
    """
    by_person: dict[str, int] = defaultdict(int)
    for raw in events:
        ev = _coerce_event(raw)
        pid = ev.get("person_id")
        if not pid:
            continue
        if ev.get("type") == _CONFIRMED_TOUCH_TYPE and (
            ev.get("channel") or _TOUCH_CHANNEL
        ) == _TOUCH_CHANNEL:
            by_person[pid] += 1
    return {pid: count - 1 for pid, count in by_person.items() if count >= 1}


# ---------------------------------------------------------------------------
# CLI (mirrors orchestrator/funnel.py: bare-name imports, run from repo root)
# ---------------------------------------------------------------------------


def _parse_now(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_cadence_from_config() -> CadenceConfig:
    """Read the ``followup:`` block from ``~/.outreach-factory/config.yml``
    (honoring ``OUTREACH_FACTORY_CONFIG``). Missing config / missing block /
    missing PyYAML -> :data:`DEFAULT_CADENCE` (opt-in off)."""
    override = os.environ.get("OUTREACH_FACTORY_CONFIG", "").strip()
    cfg_path = (
        Path(os.path.expanduser(override))
        if override
        else Path.home() / ".outreach-factory" / "config.yml"
    )
    if not cfg_path.exists():
        return DEFAULT_CADENCE
    try:
        import yaml  # local import: the CLI is the only YAML consumer here
    except ImportError:
        return DEFAULT_CADENCE
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return DEFAULT_CADENCE
    return cadence_config_from_dict(cfg.get("followup"))


def action_to_dict(action: FollowupAction) -> dict:
    """Serialize a :class:`FollowupAction` for the ``--json`` surface."""
    return {
        "person_id": action.person_id,
        "next_step": action.next_step,
        "touch_no": action.touch_no,
        "after_business_days": action.after_business_days,
        "business_days_waited": action.business_days_waited,
        "last_touch_ts": action.last_touch_ts,
        "last_touch_intent_id": action.last_touch_intent_id,
        "register": action.register,
    }


def _ledger_dir_from_env(arg: str | None) -> Path:
    if arg:
        return Path(os.path.expanduser(arg)).resolve()
    return Path(
        os.environ.get(
            "OUTREACH_FACTORY_LEDGER_DIR",
            str(Path.home() / ".outreach-factory" / "ledger"),
        )
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Prints the due-follow-ups worklist.

    The dispatch skill consumes ``--json`` to build its per-person plan; the
    plain output is for operators eyeballing "who is due today".
    """
    parser = argparse.ArgumentParser(
        prog="python orchestrator/followup.py",
        description=(
            "Deterministic follow-up cadence engine. Reads the ledger and "
            "prints who is due for which follow-up touch now. Read-only: it "
            "never sends and never mutates the vault."
        ),
    )
    parser.add_argument("--ledger-dir", help="Override the ledger directory.")
    parser.add_argument(
        "--now",
        help="Pin the clock to an ISO ts (tests/reproducibility); else wall clock.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)

    try:
        now = _parse_now(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as exc:
        sys.stderr.write(f"followup: bad --now: {exc}\n")
        return 2

    cadence = load_cadence_from_config()
    led = _ledger.Ledger(_ledger_dir_from_env(args.ledger_dir))
    actions = compute_due_followups_from_ledger(led, cadence, now=now)

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "enabled": cadence.enabled,
                    "max_touches": cadence.max_touches,
                    "now": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "due": [action_to_dict(a) for a in actions],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return 0

    if not cadence.enabled:
        print("Follow-ups are off (set followup.enabled: true in config.yml).")
        return 0
    if not actions:
        print("No follow-ups due right now.")
        return 0
    print(f"Follow-ups due ({len(actions)}):")
    for a in actions:
        print(
            f"  {a.person_id:30s}  touch {a.touch_no} "
            f"(follow-up {a.next_step}/{len(cadence.steps)})  "
            f"last touch {a.last_touch_ts}  "
            f"waited {a.business_days_waited}/{a.after_business_days} business days"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    raise SystemExit(main())


__all__ = [
    "CadenceConfig",
    "DEFAULT_CADENCE",
    "FOLLOWUP_REGISTER",
    "FollowupAction",
    "FollowupStep",
    "action_to_dict",
    "business_days_between",
    "cadence_config_from_dict",
    "compute_due_followups",
    "compute_due_followups_from_ledger",
    "derive_followup_steps",
    "is_followup_due",
    "load_cadence_from_config",
    "main",
]
