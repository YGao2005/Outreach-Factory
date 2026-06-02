"""Pillar A policy engine — value types.

These types are the contract every rule class consumes and every caller
of ``evaluate()`` interacts with. They are frozen dataclasses (immutable)
so a rule cannot accidentally mutate context shared with other rules.

See ``docs/adr/0001-policy-engine-architecture.md`` for the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Union, runtime_checkable


@dataclass(frozen=True)
class Allow:
    """Verdict marker: this rule did not block the send.

    Returned both by individual rules and by ``engine.evaluate`` when
    every rule in the chain returned Allow (or the rule list was empty).
    """


@dataclass(frozen=True)
class Block:
    """Verdict marker: this rule refused the send.

    Attributes
    ----------
    rule:
        The firing rule's ``name``. Goes into the ``policy_blocked``
        ledger event so funnel breakdowns can attribute refusals.
    reason:
        Human-readable explanation. Surfaced in CLI output + ledger.
    detail:
        Rule-specific evidence (blocking event ts, threshold breached,
        cooldown-window-remaining, etc.). The send-gate serializes this
        into the ledger event so future audits can reconstruct *why*
        the rule fired, not just *that* it did.
    """

    rule: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


RuleResult = Union[Allow, Block]


@runtime_checkable
class LedgerLike(Protocol):
    """Subset of ``orchestrator.ledger.Ledger`` that rules may consult.

    Defined as a ``Protocol`` so test fakes don't have to subclass
    anything — they just need to implement these four methods. Real
    code passes ``orchestrator.ledger.Ledger`` directly.

    Note: methods deliberately return the same shapes as the concrete
    Ledger so a Protocol mismatch surfaces at type-check time, not
    at runtime.
    """

    def query_by_person(self, person_id: str, since: datetime | None = None) -> list[Any]: ...

    def last_send_for(self, person_id: str, channel: str) -> Any | None: ...

    def query_by_email(self, email: str) -> set[str]: ...

    def all_events(self) -> list[Any]: ...


@dataclass(frozen=True)
class RuleContext:
    """The per-evaluation context passed to every rule.

    Fields
    ------
    person_id:
        The Person.id this send concerns. Rules use this to query the
        ledger for prior events.
    channel:
        ``"email"`` / ``"linkedin"`` / ``"twitter"``. Rules may scope
        themselves to a single channel via YAML config.
    register:
        The outreach register (``"cold-pitch"``, ``"follow-up"``,
        ``"re-engage"``, etc.). Cooldown rules typically condition on it.
    email:
        The recipient email address (if ``channel == "email"``). ``None``
        for non-email channels.
    email_domain:
        Lowercased domain portion of ``email``, pre-extracted for
        per-domain throttle rules. ``None`` when ``email`` is ``None``.
    now:
        The evaluation timestamp, injected so tests can time-travel
        without monkeypatching ``datetime.now``. Must be timezone-aware.
    timezone:
        Recipient's IANA timezone (e.g. ``"America/Los_Angeles"``).
        Cooldown rules do NOT consult this field (cooldown math is UTC;
        see ADR-0002). Reserved for sending-window rules (Week 3 task).
    person_status:
        The Person.status frontmatter value
        (``"queued" | "contacted" | "reached-out" | "dormant" | ...``)
        or ``None`` if not known. The send-gate caller reads this
        from ``vault.Person.status``. Consumed by
        ``RequiresPersonStatusRule`` (the re-engage-requires-dormancy
        factory rule). ``None`` is treated as "not the required
        status" — restrictive interpretation, per ADR-0002.
    run_id:
        The current dispatcher / send-batch identifier (e.g.
        ``"run-3f8b2a91cd"``) or ``None`` if the send is happening
        outside a batched run. Consumed by
        ``BudgetPerRunCapRule`` (the per-run budget cap rule,
        ADR-0006) to bound the cost spent within a single dispatcher
        invocation — a defense against the "dispatcher in a bad loop"
        failure mode named in I7. ``None`` causes the per-run rule
        to ``Allow`` (it has nothing to scope against); the
        window-cap and per-person-cap rules ignore the field.
    tier:
        Per-deployment tier label sourced from Person frontmatter.
        Free-form ``str`` so the engine is not coupled to any single
        tier taxonomy — the OSS deployment ships hardcoded to
        ``Person.research_tier`` (``S | A | B`` per the Outreach Tier
        Playbook); operators with a different scheme will eventually
        flip a ``policy.tier_field`` config knob to point at e.g.
        ``priority`` (``P1 | P2 | P3``) without recompiling. See
        ADR-0007 §Decision item "Tier field source."
        Consumed by ``TierRequiresTierInRule`` (ADR-0007) and by the
        cross-cutting ``block_when: {tier|tier_in}`` filter (every
        existing rule class scopes by tier without per-class code).
        ``None`` represents "tier not on the Person note" — the
        ``TierRequiresTierInRule`` treats this as restrictive (BLOCK)
        when the rule fires, mirroring the ``RequiresPersonStatusRule``
        None-handling precedent (ADR-0002). When NO tier rule is
        configured, a ``None`` tier never causes a Block on its own —
        the ``block_when:`` filter on existing rules treats a
        ``tier:`` filter as "does not apply" when ``ctx.tier is None``,
        consistent with how channel/register filters treat absent
        context fields.
    ledger:
        A ``LedgerLike`` implementation. Rules call its methods to
        learn about prior events.
    """

    person_id: str
    channel: str
    register: str
    email: str | None
    email_domain: str | None
    now: datetime
    timezone: str
    ledger: LedgerLike
    person_status: str | None = None
    run_id: str | None = None
    tier: str | None = None


@runtime_checkable
class Rule(Protocol):
    """Structural type for a policy rule.

    Implementations live in sub-modules: ``policy.cooldown``,
    ``policy.suppression``, etc. They register themselves into the
    engine's ``RULE_REGISTRY`` at import time so YAML files can name
    them via the ``type:`` discriminator.

    Required surface
    ----------------
    ``name`` (instance attribute):
        The rule's identifier. Goes into ``Block.rule`` when this rule
        fires. Typically set from the YAML ``name:`` field.
    ``evaluate(ctx)``:
        Return ``Allow()`` or ``Block(rule=self.name, reason=..., detail=...)``.
        May raise — the engine intentionally does not catch (silent
        swallow would hide policy outages from the gate; see ADR-0001).
    ``from_yaml(spec)`` (classmethod):
        Construct an instance from a single rule's YAML dict (the spec
        already has ``name:`` and ``type:`` separated out by the engine,
        but they're left in the dict for convenience).
    """

    name: str

    def evaluate(self, ctx: RuleContext) -> RuleResult: ...

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "Rule": ...
