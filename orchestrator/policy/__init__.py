"""Pillar A — declarative policy engine.

The pre-send gate consults this package to decide whether a send is
permitted. Rules live in YAML files under ``~/.outreach-factory/policies/``
and are evaluated in order; the first ``Block`` wins.

Sub-modules currently shipped:

* ``cooldown`` — same-channel cooldown rules (ADR-0002):
  ``no-duplicate-register``, ``requires-prior-send``,
  ``requires-person-status``, ``domain-throttle``.
* ``cross_channel`` — cross-channel touch rule (ADR-0003):
  ``cross-channel-touch``.
* ``suppression`` — list-based suppression rules + GDPR-forget atomic
  append (ADR-0004): ``suppression.email``, ``suppression.domain``,
  ``suppression.identity-key``.
* ``sending_window`` — recipient-local time-of-day + day-of-week rules
  (ADR-0005): ``sending-window.local-time-of-day``,
  ``sending-window.day-of-week``. Consumes ``ctx.timezone`` populated by
  ``tz_inference.infer_timezone`` from the recipient country signal.
* ``budget`` — cost-cap rules (ADR-0006): ``budget.window-cap``,
  ``budget.per-person-cap``, ``budget.per-run-cap``. Consumes
  ``cost_incurred`` ledger events emitted at every external API call
  success path. Locks the I7 invariant ("cost is a first-class
  concern") into the policy engine.
* ``tier`` — research/priority tier gating (ADR-0007):
  ``tier.requires-tier-in``. Consumes ``RuleContext.tier`` (free-form
  string sourced from Person frontmatter ``research_tier:`` in v1).
  Pairs with the cross-cutting ``block_when: {tier|tier_in}`` filter
  keys that ``_block_when_matches`` now accepts — every existing rule
  class scopes by tier without per-class code.
* ``tz_inference`` — country signal → IANA timezone lookup. The send-gate
  caller uses this to populate ``RuleContext.timezone``.

Public surface — import from here, not from sub-modules:

    from orchestrator import policy
    rules = policy.load_rules_from_yaml(path)
    result = policy.evaluate(rules, policy.RuleContext(...))
    if isinstance(result, policy.Block):
        ...

See ``docs/adr/0001-policy-engine-architecture.md`` for the architecture
and ``docs/PILLAR-PLAN.md`` §2 Pillar A for the wider scope (cooldown,
suppression, budget, sending-window, tier).
"""

from .types import (
    Allow,
    Block,
    LedgerLike,
    Rule,
    RuleContext,
    RuleResult,
)
from .engine import (
    RULE_REGISTRY,
    evaluate,
    evaluate_all,
    load_rules_from_yaml,
    register_rule_class,
)

# Sub-modules auto-register their rule classes at import time. Imported
# for side effect; symbols are not re-exported (use ``policy.<class>`` or
# import directly from the sub-module if a caller actually needs the class).
#
# Order is alphabetical, not semantic — registration is independent.
# Adding a new rule class? Drop its import here and add the discriminator
# to ``RULE_REGISTRY`` via ``register_rule_class`` inside the new module.
from . import budget  # noqa: F401
from . import cooldown  # noqa: F401
from . import cross_channel  # noqa: F401
from . import sending_window  # noqa: F401
from . import suppression  # noqa: F401
from . import tier  # noqa: F401

# tz_inference is utility-only (no rule classes); re-exported for callers
# that need to populate ``RuleContext.timezone`` from a country signal.
from . import tz_inference  # noqa: F401


__all__ = [
    "Allow",
    "Block",
    "LedgerLike",
    "Rule",
    "RuleContext",
    "RuleResult",
    "RULE_REGISTRY",
    "evaluate",
    "evaluate_all",
    "load_rules_from_yaml",
    "register_rule_class",
]
