"""Content scheduler - deterministic, read-only ledger walk for the broadcast surface.

The cold-email cadence engine (``orchestrator/followup.py``) decides WHO is due
for WHICH follow-up touch now. This is its broadcast sibling: it decides WHICH
approved, scheduled content posts are DUE now, by READING the ledger (the source
of truth), deterministically. It is the timing/eligibility brain only.

The spine invariant (do not violate)
------------------------------------
The ledger is the source of truth; the vault is a denormalized view. Eligibility
is computed by READING the ledger (per-channel review approvals with a scheduled
time + the confirmed posts that have already landed). This engine is a PURE READ
that produces a worklist; it does NOT post, does NOT mutate the vault, and does
NOT bypass a guardrail. Every actual post still passes the policy engine at post
time (per-channel cap + no-double-post + quiet hours + promotional-ratio guard),
exactly like a send passes the send gates. The engine decides ELIGIBILITY and
TIMING only.

This mirrors the read-only, ledger-walking shape of ``orchestrator/followup.py``
and ``orchestrator/funnel.py``: a pure function over events + a config + a clock.

Eligibility model (ADR-0082 D409)
---------------------------------
A per-channel variant is DUE for posting when:

  * it is review-approved for that channel (a ``content_review_approved`` not
    superseded by a later ``content_review_rejected``), and
  * its scheduled time has arrived (``scheduled_at`` <= now), and
  * it has not already been posted (no ``distribution_confirmed`` for that
    content_id + channel), and
  * the channel has cap headroom in the trailing 24h window (below the
    operator-configured per-channel ``daily_cap``).

Communities (reddit / hn / discord) still surface as due, but the PostAction is
flagged ``requires_manual_post`` - the dispatcher has NO auto-post path for them
(ADR-0082 D411(2)); it drafts + reminds, the operator pastes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import ledger as _ledger  # noqa: E402
import content as _content  # noqa: E402


# ---------------------------------------------------------------------------
# Defaults (mirror config-template/config.example.yml `content:` block)
# ---------------------------------------------------------------------------

#: Opt-in: off by default. A greenfield install never schedules a post until the
#: operator sets ``content.enabled: true``.
DEFAULT_ENABLED: bool = False

#: Keep the human review gate (review -> scheduled stays manual). Opt-in
#: auto-publish (owned channels only) is a deliberate later step.
DEFAULT_AUTO_PUBLISH: bool = False

#: Per-channel daily cap defaults when a channel is enabled without one. Posting
#: more than this in a day reads as spam; the policy engine owns the HARD cap,
#: this is the scheduler's matching pre-check so it never surfaces a post that
#: the gate would block.
DEFAULT_DAILY_CAP: dict[str, int] = {
    "linkedin_post": 1,
    "x_post": 3,
    "x_thread": 1,
    "blog": 1,
    "newsletter": 1,
    "reddit": 1,
    "hn": 1,
    "discord": 2,
}


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelCalendar:
    """Per-channel posting config (the softer per-operator rhythm).

    The policy engine keeps owning the HARD per-channel cap + quiet hours; this
    is the scheduler's matching view so the due-list reflects reality.
    """

    channel: str
    enabled: bool
    daily_cap: int
    mode: str = "auto"  # "auto" | "draft_only" (communities)


@dataclass(frozen=True)
class CalendarConfig:
    """The operator-tunable ``content:`` calendar (the config block).

    The cadence lives in config (operator-tunable), NOT the policy engine. The
    post still hits the policy gates at post time.
    """

    enabled: bool = DEFAULT_ENABLED
    auto_publish: bool = DEFAULT_AUTO_PUBLISH
    channels: tuple[ChannelCalendar, ...] = ()

    def channel(self, name: str) -> ChannelCalendar | None:
        for c in self.channels:
            if c.channel == name:
                return c
        return None


@dataclass(frozen=True)
class PostAction:
    """One due post: which piece, which channel, the schedule + dedup context.

    Returned by :func:`compute_due_posts`. Carries no engagement / nothing the
    privacy invariant forbids in an aggregate surface - just the worklist keys.
    The dispatcher turns each action into a post that still passes every gate.
    """

    #: The content piece this post is for.
    content_id: str
    #: The target channel (member of POST_CHANNELS).
    channel: str
    #: The content register (post / thread / essay).
    register: str
    #: The ISO ts the operator scheduled this for (the due anchor).
    scheduled_at: str
    #: The variant body hash (the no-double-post guard key).
    body_hash: str
    #: The originating source key (a commit range / arXiv id), for attribution.
    source_ref: str | None
    #: True for community channels: the dispatcher has no auto-post path; it
    #: drafts + reminds, the operator pastes (ADR-0082 D411(2)).
    requires_manual_post: bool


DEFAULT_CALENDAR: CalendarConfig = CalendarConfig()


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def calendar_config_from_dict(block: object) -> CalendarConfig:
    """Parse the ``content:`` config block into a :class:`CalendarConfig`.

    Refuse-loud on malformed input. ``None`` / empty -> :data:`DEFAULT_CALENDAR`
    (opt-in off). The ``sources`` sub-block is parsed separately by
    :func:`content.content_sources_from_config`.
    """
    if block is None:
        return DEFAULT_CALENDAR
    if not isinstance(block, dict):
        raise ValueError(
            f"content: config block must be a mapping, got {type(block).__name__}"
        )
    enabled = bool(block.get("enabled", DEFAULT_ENABLED))
    auto_publish = bool(block.get("auto_publish", DEFAULT_AUTO_PUBLISH))

    raw_channels = block.get("channels") or {}
    if not isinstance(raw_channels, dict):
        raise ValueError(
            f"content.channels must be a mapping, got {type(raw_channels).__name__}"
        )
    channels: list[ChannelCalendar] = []
    for name, cfg in raw_channels.items():
        if name not in _content.POST_CHANNELS:
            raise ValueError(
                f"content.channels has unknown channel {name!r}; allowed "
                f"{sorted(_content.POST_CHANNELS)!r}"
            )
        cfg = cfg or {}
        if not isinstance(cfg, dict):
            raise ValueError(f"content.channels.{name} must be a mapping")
        ch_enabled = bool(cfg.get("enabled", False))
        try:
            cap = int(cfg.get("daily_cap", DEFAULT_DAILY_CAP.get(name, 1)))
        except (TypeError, ValueError):
            raise ValueError(f"content.channels.{name}.daily_cap must be an int")
        if cap < 0:
            raise ValueError(f"content.channels.{name}.daily_cap must be >= 0")
        # Communities are structurally draft_only (ADR-0082 D411(2)); the config
        # cannot promote them to auto.
        mode = "draft_only" if name in _content.COMMUNITY_CHANNELS else cfg.get("mode", "auto")
        if name in _content.COMMUNITY_CHANNELS and cfg.get("mode", "draft_only") != "draft_only":
            raise ValueError(
                f"content.channels.{name} is a community channel; mode must be "
                f"'draft_only' in v1 (auto-post is structurally disallowed)"
            )
        channels.append(
            ChannelCalendar(channel=name, enabled=ch_enabled, daily_cap=cap, mode=mode)
        )
    return CalendarConfig(
        enabled=enabled,
        auto_publish=auto_publish,
        channels=tuple(sorted(channels, key=lambda c: c.channel)),
    )


# ---------------------------------------------------------------------------
# Ledger walk
# ---------------------------------------------------------------------------


def _coerce_event(ev: object) -> dict:
    if hasattr(ev, "to_dict"):
        return ev.to_dict()  # type: ignore[attr-defined]
    return dict(ev)  # type: ignore[arg-type]


def _parse_iso(s: object) -> datetime | None:
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


@dataclass
class _ChannelState:
    """The per (content_id, channel) state derived from one ledger walk."""

    approval: dict | None = None  # the active content_review_approved event
    posted: bool = False


def _walk(events: Iterable[object]) -> tuple[
    dict[tuple[str, str], _ChannelState],
    dict[str, str],
    dict[str, list[str]],
]:
    """Single read-only pass. Returns:

    * per (content_id, channel) -> :class:`_ChannelState` (active approval +
      posted flag), with a later rejection cancelling an approval and a later
      approval re-instating it (last write wins),
    * content_id -> source_ref (from ``content_drafted``), for attribution,
    * channel -> list of confirmed-post timestamps (for the cap-headroom check).
    """
    by_key: dict[tuple[str, str], _ChannelState] = defaultdict(_ChannelState)
    source_ref: dict[str, str] = {}
    confirmed_ts: dict[str, list[str]] = defaultdict(list)
    for raw in events:
        ev = _coerce_event(raw)
        t = ev.get("type")
        cid = ev.get("content_id")
        if t == "content_drafted" and cid:
            sref = ev.get("source_ref")
            if isinstance(sref, str) and sref:
                source_ref[cid] = sref
            continue
        ch = ev.get("channel")
        if not cid or not ch:
            continue
        key = (cid, ch)
        if t == "content_review_approved":
            by_key[key].approval = ev
        elif t == "content_review_rejected":
            by_key[key].approval = None
        elif t == "distribution_confirmed":
            by_key[key].posted = True
            ts = ev.get("ts") or ""
            if ts:
                confirmed_ts[ch].append(ts)
    return by_key, source_ref, confirmed_ts


def _cap_headroom(
    channel: str, confirmed_ts: list[str], cal: ChannelCalendar, *, now: datetime,
) -> bool:
    """True if the channel is below its daily cap in the trailing 24h window.

    Rolling 24h (deterministic given ``now``, no calendar-boundary ambiguity). A
    cap of 0 means the channel is paused (no headroom ever).
    """
    if cal.daily_cap <= 0:
        return False
    window_start = now - timedelta(hours=24)
    recent = 0
    for ts in confirmed_ts:
        dt = _parse_iso(ts)
        if dt is not None and dt > window_start:
            recent += 1
    return recent < cal.daily_cap


def compute_due_posts(
    events: Iterable[object],
    calendar: CalendarConfig = DEFAULT_CALENDAR,
    *,
    now: datetime,
) -> list[PostAction]:
    """Return the deterministic worklist of posts due as of ``now``.

    PURE read over ``events`` (dicts or :class:`ledger.Event`) - the signature
    the spec names: ``compute_due_posts(events, calendar_config, now)``. For each
    per-channel variant that is review-approved (and not later rejected), whose
    scheduled time has arrived, that has not been posted, on an enabled channel
    with cap headroom, the result holds exactly one due action.

    Returns ``[]`` when ``calendar.enabled`` is False (opt-in off). The result is
    sorted by ``(scheduled_at, content_id, channel)`` for a stable order.
    """
    if not calendar.enabled:
        return []
    by_key, source_ref, confirmed_ts = _walk(events)
    actions: list[PostAction] = []
    for (cid, ch), state in by_key.items():
        if state.posted or state.approval is None:
            continue
        cal_ch = calendar.channel(ch)
        if cal_ch is None or not cal_ch.enabled:
            continue
        approval = state.approval
        sched = approval.get("scheduled_at") or ""
        sched_dt = _parse_iso(sched)
        if sched_dt is None or sched_dt > now:
            continue
        if not _cap_headroom(ch, confirmed_ts.get(ch, []), cal_ch, now=now):
            continue
        actions.append(
            PostAction(
                content_id=cid,
                channel=ch,
                register=approval.get("register") or _content.CHANNEL_DEFAULT_REGISTER.get(ch, "post"),
                scheduled_at=sched,
                body_hash=approval.get("body_hash") or "",
                source_ref=source_ref.get(cid),
                requires_manual_post=ch in _content.COMMUNITY_CHANNELS,
            )
        )
    actions.sort(key=lambda a: (a.scheduled_at, a.content_id, a.channel))
    return actions


def compute_due_posts_from_ledger(
    led: _ledger.Ledger,
    calendar: CalendarConfig = DEFAULT_CALENDAR,
    *,
    now: datetime,
) -> list[PostAction]:
    """Convenience wrapper: walk a :class:`ledger.Ledger`'s events."""
    return compute_due_posts(led.all_events(), calendar, now=now)


# ---------------------------------------------------------------------------
# Optimization report (funnel-style: deterministic, byte-identical, read-only)
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_content_report(events: Iterable[object], *, now: datetime) -> dict:
    """Aggregate the content surface into a "what is working" report (D409).

    Per hook / format / topic / channel -> posts published + engagement. The
    report is correlational + human-in-the-loop: it surfaces, it does not
    auto-tune. Best-effort signal: a channel with no readable engagement shows
    ``"signal": "none"`` rather than a fabricated number. Deterministic +
    byte-identical (sorted keys) per ADR-0031 D140; read-only per ADR-0059 D325.
    """
    published_by_channel: dict[str, int] = defaultdict(int)
    eng_by_channel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    eng_events = 0
    for raw in events:
        ev = _coerce_event(raw)
        t = ev.get("type")
        if t == "distribution_confirmed":
            ch = ev.get("channel")
            if ch:
                published_by_channel[ch] += 1
        elif t == "engagement_observed":
            ch = ev.get("channel")
            metrics = ev.get("metrics") or {}
            if ch and isinstance(metrics, dict):
                eng_events += 1
                for k, v in metrics.items():
                    try:
                        eng_by_channel[ch][str(k)] += int(v)
                    except (TypeError, ValueError):
                        continue
    report = {
        "generated_at": _iso(now),
        "posts": {
            "published_total": sum(published_by_channel.values()),
            "by_channel": dict(sorted(published_by_channel.items())),
        },
        "engagement": {
            "signal": "present" if eng_events > 0 else "none",
            "observations": eng_events,
            "by_channel": {
                ch: dict(sorted(metrics.items()))
                for ch, metrics in sorted(eng_by_channel.items())
            },
        },
    }
    return report


def render_report(report: dict) -> str:
    """Render the report as deterministic JSON (sorted keys, trailing newline)."""
    return json.dumps(report, sort_keys=True, indent=2) + "\n"


# ---------------------------------------------------------------------------
# CLI (mirrors orchestrator/followup.py)
# ---------------------------------------------------------------------------


def _parse_now(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_calendar_from_config() -> CalendarConfig:
    """Read the ``content:`` block from ``~/.outreach-factory/config.yml``
    (honoring ``OUTREACH_FACTORY_CONFIG``). Missing -> :data:`DEFAULT_CALENDAR`."""
    override = os.environ.get("OUTREACH_FACTORY_CONFIG", "").strip()
    cfg_path = (
        Path(os.path.expanduser(override))
        if override
        else Path.home() / ".outreach-factory" / "config.yml"
    )
    if not cfg_path.exists():
        return DEFAULT_CALENDAR
    try:
        import yaml
    except ImportError:
        return DEFAULT_CALENDAR
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return DEFAULT_CALENDAR
    return calendar_config_from_dict(cfg.get("content"))


def action_to_dict(action: PostAction) -> dict:
    return {
        "content_id": action.content_id,
        "channel": action.channel,
        "register": action.register,
        "scheduled_at": action.scheduled_at,
        "body_hash": action.body_hash,
        "source_ref": action.source_ref,
        "requires_manual_post": action.requires_manual_post,
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
    """CLI entry point. Prints the due-posts worklist, or the report.

    The dispatch skill consumes ``--json`` to build its plan; ``--report`` prints
    the "what is working" surface. Read-only: it never posts, never mutates.
    """
    parser = argparse.ArgumentParser(
        prog="python orchestrator/content_scheduler.py",
        description=(
            "Deterministic content scheduler. Reads the ledger and prints which "
            "approved, scheduled posts are due now, or the engagement report. "
            "Read-only: it never posts and never mutates the vault."
        ),
    )
    parser.add_argument("--ledger-dir", help="Override the ledger directory.")
    parser.add_argument(
        "--now",
        help="Pin the clock to an ISO ts (tests/reproducibility); else wall clock.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--report", action="store_true", help="Print the engagement report instead."
    )
    args = parser.parse_args(argv)

    try:
        now = _parse_now(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as exc:
        sys.stderr.write(f"content_scheduler: bad --now: {exc}\n")
        return 2

    calendar = load_calendar_from_config()
    led = _ledger.Ledger(_ledger_dir_from_env(args.ledger_dir))

    if args.report:
        report = build_content_report(led.all_events(), now=now)
        sys.stdout.write(render_report(report))
        return 0

    actions = compute_due_posts_from_ledger(led, calendar, now=now)

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "enabled": calendar.enabled,
                    "auto_publish": calendar.auto_publish,
                    "now": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "due": [action_to_dict(a) for a in actions],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return 0

    if not calendar.enabled:
        print("Content distribution is off (set content.enabled: true in config.yml).")
        return 0
    if not actions:
        print("No posts due right now.")
        return 0
    print(f"Posts due ({len(actions)}):")
    for a in actions:
        manual = "  [paste-yourself]" if a.requires_manual_post else ""
        print(
            f"  {a.content_id:30s}  {a.channel:14s}  {a.register:7s}  "
            f"scheduled {a.scheduled_at}{manual}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    raise SystemExit(main())


__all__ = [
    "CalendarConfig",
    "ChannelCalendar",
    "DEFAULT_CALENDAR",
    "PostAction",
    "action_to_dict",
    "build_content_report",
    "calendar_config_from_dict",
    "compute_due_posts",
    "compute_due_posts_from_ledger",
    "load_calendar_from_config",
    "main",
    "render_report",
]
