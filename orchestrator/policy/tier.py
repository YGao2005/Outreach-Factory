"""Pillar A — tier rules (research/priority tier gating).

One concrete rule class covering the "don't send tier-B cold-pitches at
all" failure mode named in the Outreach Tier Playbook + PILLAR-PLAN §1
I5 (the funnel CLI's ``--breakdown source,tier,gate_reason`` SLO):

* :class:`TierRequiresTierInRule` (``tier.requires-tier-in``) — block
  when ``ctx.tier`` is not in ``allowed_tiers``. Factory pattern:
  ``cold-pitch-tier-gate`` (``block_when: {register: cold-pitch},
  allowed_tiers: [S, A]``) — refuse cold-pitches to prospects whose
  research tier is anything other than S or A.

Tier semantics (ADR-0007 §Decision item "Tier field source")
-----------------------------------------------------------
``ctx.tier`` is a free-form string sourced from Person frontmatter.
The OSS v1 ships hardcoded to ``Person.research_tier`` (``S | A | B``
per the Outreach Tier Playbook); a future ``policy.tier_field:`` config
knob lets operators point at e.g. ``priority`` (``P1 | P2 | P3``)
without recompiling. The rule itself never knows which frontmatter
field it's reading — it just compares ``ctx.tier`` (whatever string
the send-gate populated) against ``allowed_tiers``.

Set-membership only (ADR-0007 §Decision item "No tier ordering")
---------------------------------------------------------------
The rule does NOT know that S > A > B. Operators write the allowed set
explicitly. Rationale: tier ordering depends on the scheme — ``P1 >
P2 > P3`` inverts the ``S > A > B`` intuition (numerics ascending =
worse). A config-driven ordering would be brittle, and the cost of
getting it wrong is asymmetric: false-Allow on a low-tier prospect is
exactly the failure mode tier rules exist to prevent. Set-membership
refuses-on-typo; min-tier silently extends.

The shared ``_block_when_matches`` helper now accepts ``tier:`` (exact
match) and ``tier_in:`` (set-membership) keys, so every existing rule
class (cooldown / suppression / sending-window / budget / cross-channel)
can scope by tier without per-class code changes (ADR-0007 §Cross-cutting
``block_when:`` extension). This rule class adds the ``tier.requires-
tier-in`` discriminator for the standalone "deny on tier" pattern that
operators reach for first.

Edge cases
----------
* **``ctx.tier is None``** — the Person note lacks the configured tier
  field. The rule treats this as "unknown tier" and BLOCKs (restrictive
  interpretation, mirroring the ``RequiresPersonStatusRule`` None-
  handling precedent in ADR-0002 §Decision item "person_status joins
  RuleContext"). The detail field carries ``tier_unknown: true`` so
  audit can distinguish "wrong tier" from "no tier at all."
* **Empty ``allowed_tiers``** — degenerate window (mirrors ADR-0005
  ``DayOfWeekRule``). A typo'd YAML that produced an empty allowed
  set would Block every send the rule scopes to — refuse-loud rather
  than open-the-floodgates.

Case-sensitivity (ADR-0007 §Decision item "Case-sensitive set membership")
--------------------------------------------------------------------------
``ctx.tier in allowed_tiers`` is exact match, case-sensitive. Operators
write the values the way they appear in frontmatter; an "s" vs "S"
mismatch is a typo we want to surface as a Block, not silently fix.
The send-gate populates ``ctx.tier`` straight from the parsed Person
frontmatter without normalization, so the operator's source-of-truth
casing is what propagates.

Risk this rule mitigates by design: R012 (sending low-tier cold-pitches
that damage reply-rate signal). The risk register row is updated to
"Mitigated by design — ``tier.requires-tier-in`` ships in v1 factory
ruleset, activate by uncommenting in cooldowns.yml" when ADR-0007 lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._helpers import _block_when_matches
from .engine import register_rule_class
from .types import Allow, Block, RuleContext, RuleResult


@dataclass
class TierRequiresTierInRule:
    """Block when ``ctx.tier`` is not in ``allowed_tiers``.

    Factory rule: ``cold-pitch-tier-gate`` (``block_when: {register:
    cold-pitch}``, ``allowed_tiers: [S, A]``). Variations (per-channel
    tier gates, per-register tier gates, exclusion-set inversion) are
    additional YAML entries — no new code required.

    Threshold semantics
    -------------------
    The rule blocks when ``ctx.tier not in allowed_tiers``. The set is
    canonical — duplicates in the YAML list collapse on parse, ordering
    is irrelevant, and comparison is exact-match case-sensitive (see
    module docstring rationale).

    None-tier handling
    ------------------
    ``ctx.tier is None`` → BLOCK. Mirrors the ``RequiresPersonStatusRule``
    restrictive interpretation (ADR-0002). The send-gate populates
    ``ctx.tier`` from ``Person.research_tier`` (which is itself
    ``Optional[str]`` — see ``vault.PersonInfo.research_tier``). A
    Person note that omits ``research_tier:`` produces ``ctx.tier =
    None``; this rule refuses the send rather than silently allowing
    it on the theory that an un-tiered prospect should not be in the
    cold-pitch funnel at all.

    The block's ``detail`` carries ``tier_unknown: true`` (when
    ``ctx.tier is None``) or ``tier_value: <value>`` (when the tier is
    set but not in the allowed set) so the funnel CLI's
    ``--breakdown gate_reason`` view can distinguish "no tier" from
    "wrong tier."

    Empty-allowed-set degenerate case
    ---------------------------------
    ``allowed_tiers == []`` → always-Block (mirrors the
    ``DayOfWeekRule`` ``allowed_days: []`` convention from ADR-0005).
    A typo'd YAML producing an empty allow-list should refuse, not
    silently open the floodgates. ``detail.degenerate: true`` surfaces
    this in the audit trail.
    """

    name: str
    allowed_tiers: list[str]
    block_when: dict[str, Any] = field(default_factory=dict)
    reason: str = "Prospect tier not in the allowed set for this send"

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        if not _block_when_matches(self.block_when, ctx):
            return Allow()

        # Empty allowed-set degenerate case — block (typo'd YAML
        # should refuse, not allow).
        if not self.allowed_tiers:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "degenerate": True,
                    "allowed_tiers": list(self.allowed_tiers),
                    "tier_value": ctx.tier,
                },
            )

        # None-tier → BLOCK. Restrictive interpretation, per ADR-0007
        # §Decision item "None-tier handling" — an un-tiered prospect
        # in a tier-gated register is exactly the failure mode the
        # rule exists to catch.
        if ctx.tier is None:
            return Block(
                rule=self.name,
                reason=self.reason,
                detail={
                    "tier_unknown": True,
                    "allowed_tiers": list(self.allowed_tiers),
                },
            )

        if ctx.tier in self.allowed_tiers:
            return Allow()

        return Block(
            rule=self.name,
            reason=self.reason,
            detail={
                "tier_value": ctx.tier,
                "allowed_tiers": list(self.allowed_tiers),
            },
        )

    @classmethod
    def from_yaml(cls, spec: dict[str, Any]) -> "TierRequiresTierInRule":
        name = spec.get("name")
        if "allowed_tiers" not in spec:
            raise ValueError(
                f"TierRequiresTierInRule {name!r}: "
                "'allowed_tiers' is required (use [] to express "
                "degenerate always-block, though typo-as-empty is "
                "the more common case this rule's empty-set "
                "convention is designed to refuse)",
            )
        raw = spec["allowed_tiers"]
        if not isinstance(raw, list):
            raise ValueError(
                f"TierRequiresTierInRule {name!r}: 'allowed_tiers' "
                f"must be a list, got {type(raw).__name__}",
            )
        # Each entry must be a string — defending against
        # `allowed_tiers: [1, 2, 3]` (an integer-priority scheme written
        # without the surrounding YAML quoting; the rule does
        # str-comparison, so numeric entries would never match a
        # ctx.tier="P1" string).
        for i, entry in enumerate(raw):
            if not isinstance(entry, str):
                raise ValueError(
                    f"TierRequiresTierInRule {name!r}: "
                    f"allowed_tiers[{i}]={entry!r} is "
                    f"{type(entry).__name__}, not str. Quote the "
                    f"value in YAML (e.g. `\"P1\"` not `P1` if the "
                    f"YAML parser would coerce it).",
                )
        return cls(
            name=spec["name"],
            allowed_tiers=list(raw),
            block_when=dict(spec.get("block_when", {})),
            reason=spec.get(
                "reason",
                "Prospect tier not in the allowed set for this send",
            ),
        )


register_rule_class("tier.requires-tier-in", TierRequiresTierInRule)
