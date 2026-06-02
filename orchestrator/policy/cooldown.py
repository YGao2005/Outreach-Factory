"""Pillar A — cooldown rule classes.

Four concrete rule classes covering every cooldown pattern named in
``docs/PILLAR-PLAN.md`` §2 Pillar A and ``.planning/HANDOFF-phase-5.5.md``
§5.5.D:

* ``NoDuplicateRegisterRule`` (``cooldown.no-duplicate-register``)
* ``RequiresPriorSendRule`` (``cooldown.requires-prior-send``)
* ``RequiresPersonStatusRule`` (``cooldown.requires-person-status``)
* ``DomainThrottleRule`` (``cooldown.domain-throttle``)

Each class:

* Implements the ``Rule`` Protocol from :mod:`orchestrator.policy.types`.
* Registers itself into ``RULE_REGISTRY`` at import time so YAML
  files can name it via the ``type:`` discriminator.
* Reads its YAML spec via ``from_yaml`` classmethod.
* Returns ``Allow()`` when the rule's ``block_when:`` filter doesn't
  match the current context, so a single YAML rule list can mix rules
  scoped to different registers / channels without conflict.

Age math is computed in UTC — see ``docs/adr/0002-cooldown-rules-and-timezone.md``
for why. ``RuleContext.timezone`` is not consulted here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Any

from ._helpers import _block_when_matches, _parse_iso_utc
from .engine import register_rule_class
from .types import Allow, Block, RuleContext, RuleResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ``_block_when_matches`` and ``_parse_iso_utc`` are shared with
# ``cross_channel.py`` and live in ``_helpers.py``. They are imported here
# (and re-exported via the module namespace) so existing callers that did
# ``from orchestrator.policy.cooldown import _parse_iso_utc`` keep working.


def _confirmed_send_intent_pairs(
    ctx: RuleContext, *, channel: str | None = None,
) -> list[tuple[dict, dict]]:
    """Return chronological [(send_intent, send_confirmed)] pairs for this
    person, optionally filtered by channel.

    Cooldown rules join on intent_id rather than walking events naively
    because the ledger stores intent + outcome as two separate events.
    A ``send_failed`` or ``send_aborted`` is not a confirmation and
    cannot block a subsequent send (cooldown only counts what reached
    the human, per ADR-0001 + ADR-0002 + the asymmetric-failure-cost
    principle).
    """
    events = ctx.ledger.query_by_person(ctx.person_id)
    intents: dict[str, dict] = {}
    confirms: dict[str, dict] = {}
    for e in events:
        # Tolerate both raw dicts (test fakes) and Event objects (production
        # ledger). Both expose .get() and __getitem__.
        t = e.get("type") if hasattr(e, "get") else None
        if t == "send_intent":
            if channel is None or e.get("channel") == channel:
                iid = e.get("intent_id")
                if iid:
                    intents[iid] = e
        elif t == "send_confirmed":
            iid = e.get("intent_id")
            if iid:
                confirms[iid] = e

    pairs: list[tuple[dict, dict]] = []
    for iid, intent in intents.items():
        confirm = confirms.get(iid)
        if confirm is None:
            continue
        pairs.append((intent, confirm))
    pairs.sort(key=lambda p: p[0].get("ts") or "")
    return pairs


# ---------------------------------------------------------------------------
# NoDuplicateRegisterRule
# ---------------------------------------------------------------------------


@dataclass
class NoDuplicateRegisterRule:
    """Block when a prior confirmed send with the same register exists.

    Factory rule: ``no-double-cold-pitch`` (``block_when: {register: cold-pitch}``).
    Equivalent rules for other registers (``no-double-follow-up`` etc.) are
    just additional YAML entries — no new code required.

    Looks at every prior ``send_intent`` for this person whose paired
    ``send_confirmed`` exists. If any such pair carries the same register
    as ``ctx.register``, blocks.
    """

    name: str
    block_when: dict[str, Any] = field(default_factory=dict)
    reason: str = "Already sent with this register"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()

        # Optional channel scoping in block_when applies here too —
        # if block_when says channel:email, we only join on email pairs.
        channel_filter = self.block_when.get("channel")
        for intent, confirm in _confirmed_send_intent_pairs(
            ctx, channel=channel_filter,
        ):
            if intent.get("register") == ctx.register:
                return Block(
                    rule=self.name,
                    reason=self.reason,
                    detail={
                        "prior_intent_id": intent.get("intent_id"),
                        "prior_send_ts": confirm.get("ts"),
                        "prior_register": intent.get("register"),
                    },
                )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "NoDuplicateRegisterRule":
        return cls(
            name=spec["name"],
            block_when=dict(spec.get("block_when", {})),
            reason=spec.get("reason", "Already sent with this register"),
        )


register_rule_class("cooldown.no-duplicate-register", NoDuplicateRegisterRule)


# ---------------------------------------------------------------------------
# RequiresPriorSendRule
# ---------------------------------------------------------------------------


@dataclass
class RequiresPriorSendRule:
    """Block unless a confirmed prior send with the required register
    exists and is at least ``min_age_days`` old.

    Factory rule: ``follow-up-requires-prior-cold-pitch``
    (``requires_register: cold-pitch``, ``min_age_days: 7``).

    Age math is UTC; ``ctx.timezone`` is not consulted (ADR-0002).

    Two distinct block reasons are surfaced in ``detail``:

    * ``missing_prior: true`` — no prior send with the required register
      exists at all.
    * ``age_days: <float>`` — a prior exists but is younger than
      ``min_age_days``. The actual age in days is included for audit.
    """

    name: str
    block_when: dict[str, Any] = field(default_factory=dict)
    requires_register: str = ""
    min_age_days: int = 0
    reason: str = "Required prior send not found or too recent"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()

        channel_filter = self.block_when.get("channel")
        candidates = [
            (intent, confirm)
            for intent, confirm in _confirmed_send_intent_pairs(
                ctx, channel=channel_filter,
            )
            if intent.get("register") == self.requires_register
        ]
        if not candidates:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "missing_prior": True,
                    "requires_register": self.requires_register,
                    "min_age_days": self.min_age_days,
                },
            )

        # Most-recent prior is the binding one for age check.
        candidates.sort(key=lambda p: p[0].get("ts") or "")
        intent, confirm = candidates[-1]
        intent_ts = _parse_iso_utc(intent.get("ts"))
        if intent_ts is None:
            # Malformed ts — be conservative: treat as missing prior.
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "missing_prior": True,
                    "requires_register": self.requires_register,
                    "min_age_days": self.min_age_days,
                    "warning": "prior intent had unparseable ts",
                },
            )

        age = ctx.now.astimezone(timezone.utc) - intent_ts
        age_days = age.total_seconds() / 86400.0
        if age_days < self.min_age_days:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "prior_intent_id": intent.get("intent_id"),
                    "prior_send_ts": confirm.get("ts"),
                    "age_days": age_days,
                    "min_age_days": self.min_age_days,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "RequiresPriorSendRule":
        if "requires_register" not in spec:
            raise ValueError(
                f"RequiresPriorSendRule {spec.get('name')!r}: "
                "'requires_register' is required",
            )
        if "min_age_days" not in spec:
            raise ValueError(
                f"RequiresPriorSendRule {spec.get('name')!r}: "
                "'min_age_days' is required",
            )
        return cls(
            name=spec["name"],
            block_when=dict(spec.get("block_when", {})),
            requires_register=spec["requires_register"],
            min_age_days=int(spec["min_age_days"]),
            reason=spec.get("reason", "Required prior send not found or too recent"),
        )


register_rule_class("cooldown.requires-prior-send", RequiresPriorSendRule)


# ---------------------------------------------------------------------------
# RequiresPersonStatusRule
# ---------------------------------------------------------------------------


@dataclass
class RequiresPersonStatusRule:
    """Block unless ``ctx.person_status`` matches ``required_status``.

    Factory rule: ``re-engage-requires-dormancy``
    (``required_status: dormant``).

    Restrictive interpretation of ``None``: a person whose status the
    send-gate couldn't determine is treated as "not the required status"
    (per ADR-0002). For re-engage, that means: if we don't *know* they're
    dormant, we don't send. The asymmetric-failure-cost principle wins.
    """

    name: str
    block_when: dict[str, Any] = field(default_factory=dict)
    required_status: str = ""
    reason: str = "Required person status not met"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()
        if ctx.person_status == self.required_status:
            return Allow()
        return Block(
            rule=self.name,
            reason=self.reason,
            detail={
                "required_status": self.required_status,
                "actual_status": ctx.person_status,
            },
        )

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "RequiresPersonStatusRule":
        if "required_status" not in spec:
            raise ValueError(
                f"RequiresPersonStatusRule {spec.get('name')!r}: "
                "'required_status' is required",
            )
        return cls(
            name=spec["name"],
            block_when=dict(spec.get("block_when", {})),
            required_status=spec["required_status"],
            reason=spec.get("reason", "Required person status not met"),
        )


register_rule_class(
    "cooldown.requires-person-status", RequiresPersonStatusRule,
)


# ---------------------------------------------------------------------------
# DomainThrottleRule
# ---------------------------------------------------------------------------


@dataclass
class DomainThrottleRule:
    """Block when ``ctx.email_domain`` has received ≥``max_count`` confirmed
    sends in the last ``window_days`` days.

    Factory rule: ``domain-cooldown`` (``max_count: 1, window_days: 14``).
    This is the per-domain deliverability throttle — sending repeatedly
    to one company's domain in a short window is a spam signal regardless
    of how distinct the recipients are.

    Counts only ``send_confirmed`` events (not ``send_failed`` or
    ``send_aborted``); only events whose recorded ``email`` ends with
    ``@<email_domain>`` (case-insensitive).
    """

    name: str
    block_when: dict[str, Any] = field(default_factory=dict)
    max_count: int = 1
    window_days: int = 14
    reason: str = "Domain throttle: too many recent sends to this domain"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()
        # No email / no domain → rule cannot apply.
        if not ctx.email or not ctx.email_domain:
            return Allow()

        domain = ctx.email_domain.lower()
        window_cutoff = ctx.now.astimezone(timezone.utc) - \
            timedelta(days=self.window_days)
        count = 0
        latest_ts: str | None = None
        for e in ctx.ledger.all_events():
            if e.get("type") != "send_confirmed":
                continue
            ev_email = (e.get("email") or "").lower()
            if "@" not in ev_email or not ev_email.endswith("@" + domain):
                continue
            ev_ts = _parse_iso_utc(e.get("ts"))
            if ev_ts is None or ev_ts < window_cutoff:
                continue
            count += 1
            if latest_ts is None or (e.get("ts") or "") > latest_ts:
                latest_ts = e.get("ts")

        if count >= self.max_count:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "domain": domain,
                    "count_in_window": count,
                    "threshold": self.max_count,
                    "window_days": self.window_days,
                    "latest_send_ts": latest_ts,
                },
            )
        return Allow()

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "DomainThrottleRule":
        return cls(
            name=spec["name"],
            block_when=dict(spec.get("block_when", {})),
            max_count=int(spec.get("max_count", 1)),
            window_days=int(spec.get("window_days", 14)),
            reason=spec.get(
                "reason",
                "Domain throttle: too many recent sends to this domain",
            ),
        )


register_rule_class("cooldown.domain-throttle", DomainThrottleRule)
