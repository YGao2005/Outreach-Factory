"""Content-post policy guardrails (ADR-0082 D417).

The broadcast post-time gate. These run on the SAME refuse-loud + first-Block-wins
discipline as the cold-side rules, but through a SEPARATE ``ContentRuleContext``,
because a post has ``content_id`` + ``channel`` + ``body_hash`` and NO
``person_id`` (the person-centric ``RuleContext`` + ``_block_when_matches`` would
AttributeError on it). They read the ledger (the source of truth) read-only.

Three guards:

* ``PerChannelPostingCapRule`` - the HARD per-channel daily cap. Its window
  matches the scheduler's ``_cap_headroom`` rolling 24h so the soft pre-check and
  the hard gate never disagree (no surprise block after the scheduler said DUE).
* ``NoDoublePostRule`` - block re-posting the same variant body to the same
  channel (hash of the normalized body + channel).
* ``PromotionalRatioRule`` - a conservative weekly self-promo ceiling per channel
  (strict for communities). HONEST LIMITATION: a true "ratio of promo to organic
  activity" is unmeasurable from the ledger (the system never sees your organic
  posts), so this is a frequency ceiling, not a real ratio. It still keeps a
  channel from being flooded with self-promo over a week.

Under the v2 human-gated posture these gate whether the dispatcher SURFACES a post
for the operator to paste; they become the hard send-time gate unchanged when a
real posting client is dropped into the seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Protocol, runtime_checkable

from .types import Allow, Block, RuleResult

import content as _content  # bare import (orchestrator/ on sys.path), as content_scheduler


_DISTRIBUTION_CONFIRMED = "distribution_confirmed"


def _parse_iso(s: object) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ContentRuleContext:
    """The post-time gate context (the content-post analog of RuleContext)."""

    content_id: str
    channel: str
    body_hash: str
    register: str
    now: datetime
    events: tuple


@runtime_checkable
class ContentRule(Protocol):
    name: str

    def evaluate(self, ctx: ContentRuleContext) -> RuleResult: ...


def _confirmed_on_channel(events: Iterable, channel: str):
    for e in events:
        d = e.to_dict() if hasattr(e, "to_dict") else e
        if d.get("type") == _DISTRIBUTION_CONFIRMED and d.get("channel") == channel:
            yield d


def _count_in_window(ctx: ContentRuleContext, *, hours: int) -> int:
    start = ctx.now - timedelta(hours=hours)
    n = 0
    for d in _confirmed_on_channel(ctx.events, ctx.channel):
        ts = _parse_iso(d.get("ts"))
        if ts is None or ts > start:
            n += 1
    return n


@dataclass
class PerChannelPostingCapRule:
    """The hard per-channel daily cap (rolling 24h, matching the scheduler)."""

    caps: dict[str, int]
    window_hours: int = 24
    name: str = "content.per-channel-cap"

    def evaluate(self, ctx: ContentRuleContext) -> RuleResult:
        cap = self.caps.get(ctx.channel)
        if cap is None:
            return Allow()
        n = _count_in_window(ctx, hours=self.window_hours)
        if n >= cap:
            return Block(
                rule=self.name,
                reason=f"{ctx.channel} at the daily cap ({cap} per {self.window_hours}h)",
                detail={"count": n, "cap": cap, "window_hours": self.window_hours},
            )
        return Allow()


@dataclass
class NoDoublePostRule:
    """Block re-posting the same variant body to the same channel."""

    name: str = "content.no-double-post"

    def evaluate(self, ctx: ContentRuleContext) -> RuleResult:
        for d in _confirmed_on_channel(ctx.events, ctx.channel):
            if d.get("body_hash") and d.get("body_hash") == ctx.body_hash:
                return Block(
                    rule=self.name,
                    reason=f"this exact body was already posted to {ctx.channel}",
                    detail={"body_hash": ctx.body_hash},
                )
        return Allow()


@dataclass
class PromotionalRatioRule:
    """A conservative weekly self-promo ceiling per channel (see module docstring)."""

    weekly_caps: dict[str, int]
    window_hours: int = 168
    name: str = "content.promotional-ratio"

    def evaluate(self, ctx: ContentRuleContext) -> RuleResult:
        cap = self.weekly_caps.get(ctx.channel)
        if cap is None:
            return Allow()
        n = _count_in_window(ctx, hours=self.window_hours)
        if n >= cap:
            return Block(
                rule=self.name,
                reason=f"weekly self-promo ceiling ({cap}) reached on {ctx.channel}",
                detail={"count": n, "weekly_cap": cap},
            )
        return Allow()


def load_content_rules(calendar) -> list[ContentRule]:
    """Build the default content guardrails from a CalendarConfig.

    The daily caps come straight from the calendar (so the hard gate and the
    scheduler's pre-check agree). The weekly self-promo ceiling is derived:
    communities get 1 per week (self-promo there is a reputation landmine); other
    channels get five dailies' worth.
    """
    caps = {ch.channel: ch.daily_cap for ch in calendar.channels}
    weekly: dict[str, int] = {}
    for ch in calendar.channels:
        if ch.channel in _content.COMMUNITY_CHANNELS:
            weekly[ch.channel] = 1
        else:
            weekly[ch.channel] = max(ch.daily_cap * 5, 5)
    return [
        PerChannelPostingCapRule(caps),
        NoDoublePostRule(),
        PromotionalRatioRule(weekly),
    ]


def content_gate(rules: list[ContentRule]):
    """Adapt the content rules into the dispatcher's ``GateFn`` seam.

    Returns ``gate(action, events, now)`` that builds a :class:`ContentRuleContext`
    and runs the rules first-Block-wins, returning the block-info dict the
    dispatcher serializes into ``policy_blocked``, or None to allow.
    """

    def gate(action, events, now) -> "dict | None":
        ctx = ContentRuleContext(
            content_id=action.content_id,
            channel=action.channel,
            body_hash=action.body_hash,
            register=action.register,
            now=now,
            events=tuple(events),
        )
        for rule in rules:
            res = rule.evaluate(ctx)
            if not isinstance(res, Allow):
                return {
                    "content_id": ctx.content_id,
                    "channel": ctx.channel,
                    "rule": res.rule,
                    "reason": res.reason,
                    "detail": res.detail,
                }
        return None

    return gate


__all__ = [
    "ContentRule",
    "ContentRuleContext",
    "NoDoublePostRule",
    "PerChannelPostingCapRule",
    "PromotionalRatioRule",
    "content_gate",
    "load_content_rules",
]
