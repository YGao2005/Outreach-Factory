"""Health-gated warming-ramp policy for a cold sending mailbox.

A brand-new sending identity (a fresh domain or mailbox) has no reputation.
Mailbox providers treat a sudden burst from an unknown sender as spam, so the
only safe way to reach the daily send cap is to ramp into it: a handful of
sends in week 1, more each week, steady at the cap after a few weeks. This
module computes that ramp and gates it on deliverability health: if the
trailing bounce rate climbs above a threshold, the ramp HOLDS rather than
escalating, so a degrading mailbox is never asked to send more.

What this module owns:
  * the per-week scheduled ceiling (the RAMP), clamped to the daily send cap;
  * the HEALTH GATE that holds the ramp when the trailing bounce rate is high.

What this module does NOT do (be honest about scope):
  * it does not BUILD reputation. Reputation comes from weeks of real, engaged
    sends (opens, replies, low complaints) and is best handed to a dedicated
    warmup network (Mailwarm, Warmup Inbox, Instantly, and similar). In v1 that
    is a recommend-only step, not something the framework automates.
  * it does not ENFORCE the ceiling on the send path. `compute_ramp` returns
    the ceiling and the hold decision; wiring a hard pre-send gate into
    send_queued.py is a separate step. Today the ceiling is surfaced in
    `outreach-factory status` so the operator can see it and respect it.

Health is derived from the ledger events the rest of the factory already
emits (see orchestrator/ledger.py "Event types"): bounce_detected vs
send_confirmed over a trailing window gives the bounce rate. There is no
spam-complaint event in the ledger, so complaints are out of scope for v1.

Import-lean: this module stays off the heavy operations tier. It imports only
the standard library (and reads pre-loaded ledger event objects passed in by
the caller); it never imports the daemon, observability, reconcile, or any
other operations module, so the core send/onboarding path stays light.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

# Default per-week ramp, expressed as a fraction of the daily send cap. Week 1
# sends a small fixed floor; weeks 2-5 climb toward the cap; week 6+ is steady
# at the cap. The fractions are applied to ``daily_send_cap`` and then floored
# by ``_WEEK1_FLOOR`` so a small cap still starts at a sane handful, and clamped
# so the ceiling never exceeds the cap. This is the conservative "start low,
# ramp slow" posture cold-domain warming requires; operators can override the
# schedule via config (warming.weeks_to_full or warming.fractions).
DEFAULT_SCHEDULE: tuple[float, ...] = (0.20, 0.40, 0.60, 0.80, 1.00)

# The absolute minimum week-1 ceiling. Even when 20% of the cap rounds down to
# a tiny number, week 1 starts here (a handful of sends is fine on a fresh
# mailbox; zero sends warms nothing).
_WEEK1_FLOOR: int = 5

# Health-gate defaults.
_DEFAULT_HEALTH_WINDOW = timedelta(days=7)
_DEFAULT_BOUNCE_THRESHOLD: float = 0.05  # 5%

# Ledger event types this module reads (must match orchestrator/ledger.py).
_SEND_CONFIRMED = "send_confirmed"
_BOUNCE_DETECTED = "bounce_detected"


@dataclass(frozen=True)
class RampDecision:
    """The warming ramp decision for a single day.

    Fields:
      * ``week_index`` - 1-based week of the ramp (week 1 is the first week
        after ``start_date``). Days before ``start_date`` still report week 1.
      * ``base_ceiling`` - this week's scheduled ceiling from the ramp
        schedule, already clamped to ``daily_send_cap``, BEFORE the health
        gate is applied.
      * ``health`` - ``"ok"`` or ``"degraded"`` (degraded when the trailing
        bounce rate is over the threshold).
      * ``held`` - True when the ramp is held back by the health gate (the
        effective ceiling is not allowed to escalate beyond the prior/floor
        value while unhealthy).
      * ``effective_ceiling`` - the ceiling to actually respect today. Never
        exceeds ``daily_send_cap``. Equals ``base_ceiling`` when healthy; when
        held, it is the floor (the prior, lower week's ceiling) instead of
        escalating.
      * ``reasons`` - human-readable notes explaining the decision.
      * ``bounce_rate`` - bounce_detected / max(1, send_confirmed) over the
        health window.
      * ``sends_window`` - count of send_confirmed events in the health window.
    """

    week_index: int
    base_ceiling: int
    health: str
    held: bool
    effective_ceiling: int
    bounce_rate: float
    sends_window: int
    reasons: list[str] = field(default_factory=list)


def _as_aware(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC; pass an aware one through unchanged."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_ts(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 ledger timestamp (trailing 'Z' or offset) to an aware
    UTC datetime, or None if it is missing/unparseable. Mirrors how the rest of
    the factory reads ``event.ts``."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return _as_aware(dt)


def _event_type(e) -> str | None:
    """Read an event's type from either an Event-like object (``.get('type')``)
    or a plain dict. The status command reads ``e.get('type')``; we accept both
    so callers can pass ledger Event objects or fabricated dicts."""
    if hasattr(e, "get"):
        return e.get("type")
    return None


def _event_ts(e) -> str | None:
    """Read an event's ts. Ledger Event objects expose ``.ts``; plain dicts use
    ``["ts"]`` via ``.get``. Prefer the attribute, fall back to the mapping."""
    ts = getattr(e, "ts", None)
    if ts is not None:
        return ts
    if hasattr(e, "get"):
        return e.get("ts")
    return None


def normalize_schedule(
    schedule: object | None,
    *,
    daily_send_cap: int,
) -> tuple[int, ...]:
    """Resolve a schedule spec into a tuple of absolute per-week ceilings.

    Accepts, in order of preference:
      * ``None`` - use :data:`DEFAULT_SCHEDULE` (fractions of the cap).
      * a list/tuple of fractions (all <= 1.0) - multiplied by the cap.
      * a list/tuple of absolute steps (any value > 1) - used as-is.
      * an int ``weeks_to_full`` - a linear ramp from the week-1 floor up to
        the cap across that many weeks.

    Every resulting ceiling is floored at the week-1 floor for the first week
    and clamped to ``[1, daily_send_cap]`` so the ramp can never exceed the cap
    and never collapses to zero. The returned tuple is non-decreasing.
    """
    cap = max(1, int(daily_send_cap))

    if schedule is None:
        steps = _fractions_to_steps(DEFAULT_SCHEDULE, cap)
    elif isinstance(schedule, int) and not isinstance(schedule, bool):
        steps = _weeks_to_full_steps(schedule, cap)
    elif isinstance(schedule, (list, tuple)) and schedule:
        seq = list(schedule)
        # Fractions if every value is <= 1.0; absolute steps otherwise.
        if all(isinstance(v, (int, float)) and v <= 1.0 for v in seq):
            steps = _fractions_to_steps(seq, cap)
        else:
            steps = [max(1, min(cap, int(round(float(v))))) for v in seq]
    else:
        steps = _fractions_to_steps(DEFAULT_SCHEDULE, cap)

    # Week 1 floor + clamp + non-decreasing.
    out: list[int] = []
    for i, v in enumerate(steps):
        val = max(1, min(cap, int(v)))
        if i == 0:
            val = min(cap, max(val, _WEEK1_FLOOR))
        if out and val < out[-1]:
            val = out[-1]
        out.append(val)
    return tuple(out) if out else (min(cap, _WEEK1_FLOOR),)


def _fractions_to_steps(fractions, cap: int) -> list[int]:
    return [max(1, int(round(float(f) * cap))) for f in fractions]


def _weeks_to_full_steps(weeks_to_full: int, cap: int) -> list[int]:
    weeks = max(1, int(weeks_to_full))
    if weeks == 1:
        return [cap]
    floor = min(cap, _WEEK1_FLOOR)
    steps: list[int] = []
    for w in range(weeks):
        # Linear interpolation from the floor (week 1) to the cap (last week).
        frac = w / (weeks - 1)
        steps.append(int(round(floor + frac * (cap - floor))))
    return steps


def _infer_start_date(events) -> datetime | None:
    """Earliest send_confirmed timestamp in ``events``, or None if there are no
    confirmed sends yet. Used as the ramp anchor when no explicit start_date is
    configured: warming begins the day the mailbox first sent."""
    earliest: datetime | None = None
    for e in events or ():
        if _event_type(e) != _SEND_CONFIRMED:
            continue
        dt = _parse_ts(_event_ts(e))
        if dt is None:
            continue
        if earliest is None or dt < earliest:
            earliest = dt
    return earliest


def _week_index(now: datetime, start_date: datetime) -> int:
    """1-based week number of ``now`` relative to ``start_date``. The first
    seven days (days 0-6) are week 1; days before the start are also week 1."""
    delta_days = (now.date() - start_date.date()).days
    if delta_days < 0:
        return 1
    return delta_days // 7 + 1


def _ceiling_for_week(week_index: int, steps: tuple[int, ...]) -> int:
    """The scheduled ceiling for a 1-based week. Weeks past the schedule length
    hold steady at the last (cap) step."""
    if week_index < 1:
        week_index = 1
    idx = min(week_index, len(steps)) - 1
    return steps[idx]


def compute_health(
    events,
    *,
    now: datetime,
    window: timedelta = _DEFAULT_HEALTH_WINDOW,
    bounce_threshold: float = _DEFAULT_BOUNCE_THRESHOLD,
) -> tuple[str, bool, float, int]:
    """Derive deliverability health from the trailing window of ledger events.

    Returns ``(health, degraded, bounce_rate, sends_window)`` where:
      * ``bounce_rate`` = bounce_detected / max(1, send_confirmed) in the window
      * ``degraded`` is True when ``bounce_rate > bounce_threshold``
      * ``health`` is ``"degraded"`` when degraded else ``"ok"``

    The ``max(1, ...)`` floor means a window with bounces but zero confirmed
    sends still produces a finite rate (it reads as "all bounces"), which is the
    correct conservative signal.
    """
    now = _as_aware(now)
    cutoff = now - window
    sends = 0
    bounces = 0
    for e in events or ():
        t = _event_type(e)
        if t != _SEND_CONFIRMED and t != _BOUNCE_DETECTED:
            continue
        dt = _parse_ts(_event_ts(e))
        if dt is None or dt < cutoff or dt > now:
            continue
        if t == _SEND_CONFIRMED:
            sends += 1
        else:
            bounces += 1
    bounce_rate = bounces / max(1, sends)
    degraded = bounce_rate > bounce_threshold
    return ("degraded" if degraded else "ok", degraded, bounce_rate, sends)


def compute_ramp(
    *,
    now: datetime,
    start_date: datetime | None,
    daily_send_cap: int,
    events,
    schedule: object | None = None,
    health_window: timedelta = _DEFAULT_HEALTH_WINDOW,
    bounce_threshold: float = _DEFAULT_BOUNCE_THRESHOLD,
) -> RampDecision:
    """Compute today's warming-ramp decision.

    Args:
        now: the moment to evaluate (UTC; naive is treated as UTC).
        start_date: explicit ramp anchor. When None, inferred from the earliest
            ``send_confirmed`` in ``events``; when there are no sends yet, the
            ramp is week 1 anchored at ``now``.
        daily_send_cap: the operator's hard daily cap (email_send.daily_send_cap).
            The effective ceiling never exceeds this.
        events: ledger events (Event objects or plain dicts) to derive health
            from. Reused from whatever the caller already loaded.
        schedule: optional override (fractions, absolute steps, or an int
            weeks_to_full). See :func:`normalize_schedule`.
        health_window: trailing window for the bounce-rate health gate.
        bounce_threshold: bounce-rate above which the ramp holds (default 0.05).

    Returns:
        A :class:`RampDecision`. When healthy, ``effective_ceiling ==
        base_ceiling``. When the bounce rate is over the threshold,
        ``health == "degraded"``, ``held == True``, and the effective ceiling
        is the FLOOR (the prior, lower week's ceiling) rather than escalating to
        this week's higher number. This is the guardrail: degraded health must
        not escalate the ramp.
    """
    now = _as_aware(now)
    cap = max(1, int(daily_send_cap))
    steps = normalize_schedule(schedule, daily_send_cap=cap)

    inferred = False
    anchor = _as_aware(start_date) if start_date is not None else None
    if anchor is None:
        anchor = _infer_start_date(events)
        inferred = anchor is not None
    if anchor is None:
        # No explicit anchor and no sends yet: fresh mailbox, week 1 at now.
        anchor = now

    week_index = _week_index(now, anchor)
    base_ceiling = _ceiling_for_week(week_index, steps)

    health, degraded, bounce_rate, sends_window = compute_health(
        events, now=now, window=health_window, bounce_threshold=bounce_threshold,
    )

    reasons: list[str] = []
    if inferred:
        reasons.append(
            f"start_date inferred from earliest send_confirmed "
            f"({anchor.date().isoformat()})"
        )
    elif start_date is None:
        reasons.append("no sends yet; ramp at week 1")

    held = False
    effective_ceiling = base_ceiling
    if degraded:
        held = True
        # Hold the ramp: do not escalate beyond the prior (lower) week's
        # ceiling. The floor is the previous week's step (or week 1's ceiling
        # when already in week 1). This caps the mailbox at the level it was
        # safely sending before the bounce rate climbed.
        floor_week = max(1, week_index - 1)
        floor_ceiling = _ceiling_for_week(floor_week, steps)
        effective_ceiling = min(base_ceiling, floor_ceiling)
        pct = round(bounce_rate * 100)
        gate_pct = round(bounce_threshold * 100)
        reasons.append(
            f"HELD: bounce rate {pct}% over the {gate_pct}% gate "
            f"({sends_window} sends in the trailing "
            f"{int(health_window.total_seconds() // 86400)}d window)"
        )
    else:
        reasons.append(
            f"health ok (bounce rate {round(bounce_rate * 100)}% under the "
            f"{round(bounce_threshold * 100)}% gate)"
        )

    # Final clamp - effective_ceiling never exceeds the daily send cap.
    effective_ceiling = max(1, min(cap, effective_ceiling))

    return RampDecision(
        week_index=week_index,
        base_ceiling=base_ceiling,
        health=health,
        held=held,
        effective_ceiling=effective_ceiling,
        bounce_rate=bounce_rate,
        sends_window=sends_window,
        reasons=reasons,
    )


def total_weeks(schedule: object | None = None, *, daily_send_cap: int) -> int:
    """Number of weeks in the ramp before it steadies at the cap. Useful for
    the status line ('week 2 of 5')."""
    return len(normalize_schedule(schedule, daily_send_cap=daily_send_cap))


def status_line(decision: RampDecision, *, total: int | None = None) -> str:
    """One-line status summary for `outreach-factory status`.

    Examples:
        "warming ceiling  8/day  (week 2 of 5 ramp; health ok)"
        "warming ceiling  5/day  (week 3 of 5 ramp; HELD: bounce rate 7% over the 5% gate)"
    """
    if decision.held:
        note = next(
            (r for r in decision.reasons if r.startswith("HELD")),
            "HELD (degraded health)",
        )
    else:
        note = "health ok"
    weeks = f" of {total}" if total else ""
    return (
        f"warming ceiling  {decision.effective_ceiling}/day  "
        f"(week {decision.week_index}{weeks} ramp; {note})"
    )


__all__ = [
    "RampDecision",
    "DEFAULT_SCHEDULE",
    "compute_ramp",
    "compute_health",
    "normalize_schedule",
    "total_weeks",
    "status_line",
]
