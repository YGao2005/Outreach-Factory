"""Pillar A — cross-channel touch rule (``cooldown.cross-channel-touch``).

One rule class — :class:`CrossChannelTouchRule` — that blocks a send on
channel X when a confirmed touch on channel Y exists in the ledger within
``window_days``. Decouples fire scope (``block_when: {channel: X}``) from
query scope (``consider_channels: [Y]``).

See ``docs/adr/0003-channel-as-first-class-policy-predicate.md`` for the
binding spec, including the CC-01..CC-12 test matrix that
``tests/test_policy_cross_channel.py`` enforces.

Risk this rule mitigates by design: R011 (cross-channel double-engagement).

Activation
----------
The v1 factory rules in ``config-template/cooldowns.example.yml`` ship
*before* the Pillar C LinkedIn integration. Until ``li_*_confirmed``
events first appear in the ledger, the rules return ``Allow()`` — there
is nothing to match against — and consume one ``query_by_person`` call
per evaluation. They begin enforcing automatically the moment Pillar C
writes the first matching event; no engine or YAML change required.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Any

from ._helpers import _block_when_matches, _parse_iso_utc
from .engine import register_rule_class
from .types import Allow, Block, RuleContext, RuleResult


@dataclass
class CrossChannelTouchRule:
    """Block when a confirmed touch on a *different* channel landed within
    ``window_days``.

    Fire scope is set by ``block_when:`` (typically
    ``block_when: {channel: <fire_channel>}``); query scope is set by
    ``consider_channels: [<other_channel>, ...]``. These are deliberately
    distinct YAML keys — see ADR-0003 §Alternative 3 for the rationale
    against overloading ``block_when:``.

    Event recognition
    -----------------
    The rule consumes any ledger event whose ``type`` ends with
    ``"_confirmed"`` and whose event-level ``channel`` field is in
    ``consider_channels``. The predicate is wider than ADR-0003 §Decision's
    literal ``type == "send_confirmed"`` text — see ADR-0003 §Decision
    "Event-type predicate" for the authorization. The widening matters
    because Pillar C lands ``li_invite_confirmed`` and ``li_dm_confirmed``
    as distinct types; without the suffix match the rule class would
    need editing the moment Pillar C ships. The channel filter is the
    load-bearing safety check — an event whose channel is NOT in
    ``consider_channels`` is skipped regardless of type, so the suffix
    rule cannot accidentally match an unrelated future event type that
    happens to end ``_confirmed`` (verified absent from
    ``ledger.py:EVENT_TYPES`` as of this commit; ``send_confirmed_orphan``
    ends ``_orphan`` and is correctly excluded).

    ``send_intent`` is intentionally **excluded** — an intent that never
    confirms may not have reached the human. Blocking on intent is a
    false-positive risk we explicitly accept missing one prior touch to
    avoid. See ADR-0003 §Compliance I2 + ADR-0001 §0 asymmetric-failure-cost.

    Window math (UTC, per ADR-0002)
    -------------------------------
    Cutoff = ``ctx.now - timedelta(days=window_days)``. An event with
    ``ev_ts < cutoff`` is considered **outside** the window. The boundary
    instant itself (``ev_ts == cutoff``) is **inside** the window — i.e.
    a touch exactly ``window_days`` ago still blocks. This is inclusive
    on the lower end, matching :class:`DomainThrottleRule`'s convention
    (``cooldown.py:DomainThrottleRule.evaluate``) and the natural reading
    of "within N days". See ADR-0003 §Decision row CC-06 for the bound
    contract and the boundary-pinning tests in
    ``tests/test_policy_cross_channel.py``.
    """

    name: str
    consider_channels: list[str]
    window_days: int
    block_when: dict[str, Any] = field(default_factory=dict)
    reason: str = "Cross-channel touch within window"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()

        cutoff = ctx.now.astimezone(timezone.utc) - \
            timedelta(days=self.window_days)
        considered = set(self.consider_channels)

        # Walk this person's events; cheapest possible filter on each.
        # No new LedgerLike method is required (ADR-0003 §Decision).
        for e in ctx.ledger.query_by_person(ctx.person_id):
            etype = e.get("type") if hasattr(e, "get") else None
            if not isinstance(etype, str) or not etype.endswith("_confirmed"):
                continue
            ev_channel = e.get("channel")
            if ev_channel not in considered:
                continue
            ev_ts = _parse_iso_utc(e.get("ts"))
            if ev_ts is None or ev_ts < cutoff:
                # Strictly older than the cutoff → outside the window.
                # The boundary instant (ev_ts == cutoff) IS inside the
                # window — inclusive lower-end, matching DomainThrottleRule.
                # See ADR-0003 §Decision CC-06.
                continue
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "fires_on": ctx.channel,
                    "considers": list(self.consider_channels),
                    "prior_touch_channel": ev_channel,
                    "prior_touch_type": etype,
                    "prior_touch_ts": e.get("ts"),
                    "prior_touch_intent_id": e.get("intent_id"),
                    "window_days": self.window_days,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "CrossChannelTouchRule":
        name = spec.get("name")
        if "consider_channels" not in spec:
            raise ValueError(
                f"CrossChannelTouchRule {name!r}: "
                "'consider_channels' is required",
            )
        considered = spec["consider_channels"]
        if not isinstance(considered, list) or len(considered) == 0:
            raise ValueError(
                f"CrossChannelTouchRule {name!r}: "
                "'consider_channels' must be a non-empty list",
            )
        if "window_days" not in spec:
            raise ValueError(
                f"CrossChannelTouchRule {name!r}: "
                "'window_days' is required",
            )

        block_when = dict(spec.get("block_when", {}))
        fire_channel = block_when.get("channel")
        if fire_channel is not None and fire_channel in considered:
            # CC-09: the rule queries the same channel it fires on. The
            # user may want this for non-touch-recency reasons, so we do
            # not raise — but we warn, because the common case is a typo
            # (forgot to swap the channel) that would silently mask
            # same-channel rule coverage.
            print(
                f"CrossChannelTouchRule {name!r}: consider_channels "
                f"contains the firing channel {fire_channel!r}; the rule "
                f"will also query same-channel events. This is unusual — "
                f"prefer a same-channel cooldown rule unless you intend "
                f"cross-channel + self semantics.",
                file=sys.stderr,
            )

        return cls(
            name=spec["name"],
            consider_channels=list(considered),
            window_days=int(spec["window_days"]),
            block_when=block_when,
            reason=spec.get(
                "reason", "Cross-channel touch within window",
            ),
        )


register_rule_class("cooldown.cross-channel-touch", CrossChannelTouchRule)
