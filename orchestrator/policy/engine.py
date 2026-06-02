"""Pillar A policy engine — registry, evaluator, YAML loader.

Four responsibilities:

1. ``RULE_REGISTRY`` — module-level discriminator → rule-class mapping.
   Rule sub-modules call ``register_rule_class`` at import time.

2. ``evaluate(rules, ctx)`` — ordered short-circuit evaluator. First
   ``Block`` wins; empty input returns ``Allow()``.

3. ``evaluate_all(rules, ctx)`` — non-short-circuit variant returning
   one verdict per rule. Used by the simulation CLI to answer "every
   rule's verdict on this context" instead of the production "first
   Block wins." See ADR-0007 §Decision item "Simulation surface."

4. ``load_rules_from_yaml(path)`` — parse a policy YAML file and
   construct concrete ``Rule`` instances via each class's ``from_yaml``.

See ``docs/adr/0001-policy-engine-architecture.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from .types import Allow, Rule, RuleContext, RuleResult


# Self-declared version of the policy engine code itself. Distinct
# from the migration framework's :data:`RUNNER_VERSION` (which versions
# the migration-execution surface) — this constant versions the policy
# engine's rule-loading + rule-evaluation surface.
#
# Currently both are ``"0.1.0"`` because the project is at v0.1.0
# overall. The two are expected to diverge over time: the runner bumps
# rarely (only when migration framework behavior changes); the engine
# bumps more often (when rule classes are added, removed, or semantically
# changed — Pillar C / D / E / F all advance it).
#
# Consumed by ``orchestrator.migrations.policy.migration_0001`` as the
# value stamped into each policy file's ``engine_compat.min_engine_version``
# field. Future engine releases that drop legacy schema support consult
# this stamp to refuse files known to be too old.
POLICY_ENGINE_VERSION = "0.1.0"


# Schema versions of the policy YAML format the engine knows how to
# load. The set is forward-compatible by design — operators between
# git-pull and migration-apply have v1 files that the new engine must
# still load (per ADR-0011 D12's warn-on-pending posture; doctor
# warns but the dispatcher keeps running). Without range acceptance,
# bumping a single supported version would brick every operator's
# send loop the moment they pull a code change that ships a policy
# migration.
#
# Per ADR-0012 the migration framework's contract:
#   * The engine accepts a contiguous version range.
#   * A new migration ships alongside an engine update that ADDS the
#     new version to this set.
#   * A future migration that drops legacy support REMOVES the old
#     version from this set (Pillar I OSS hardening is the natural
#     home for that step — by then operators have had multiple cycles
#     to apply the intermediate bumps).
#
# ``SUPPORTED_POLICY_SCHEMA_VERSION`` (singular) is preserved as the
# "latest" sentinel for backwards-compat with code that imports the
# constant. Bumping this requires a migration entry under
# orchestrator/migrations/policy/ AND adding the new version to
# ``SUPPORTED_POLICY_SCHEMA_VERSIONS`` (the set the loader actually
# checks). See ADR-0012.
SUPPORTED_POLICY_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})
SUPPORTED_POLICY_SCHEMA_VERSION = max(SUPPORTED_POLICY_SCHEMA_VERSIONS)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


RULE_REGISTRY: dict[str, type[Rule]] = {}


def register_rule_class(type_name: str, cls: type[Rule]) -> None:
    """Register a concrete Rule class under a YAML discriminator.

    Called once per rule class at module import time. The discriminator
    is the value users write under ``type:`` in their YAML file (e.g.
    ``"cooldown.register-cooldown"``, ``"suppression.email"``).

    Raises
    ------
    ValueError:
        If ``type_name`` is already registered. Silent shadowing would
        be a bug, not a feature — two classes claiming the same
        discriminator is a typo or a name collision that must be fixed
        in source, not papered over at runtime.
    """
    existing = RULE_REGISTRY.get(type_name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"rule type {type_name!r} already registered to {existing!r}; "
            f"cannot re-register to {cls!r}",
        )
    RULE_REGISTRY[type_name] = cls


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def evaluate(rules: Iterable[Rule], ctx: RuleContext) -> RuleResult:
    """Ordered short-circuit evaluation. First Block wins.

    Empty ``rules`` → ``Allow()`` (greenfield install with no policies
    must not block sends; doctor preflight is responsible for warning
    the user that no policies are configured).

    Exception handling: an exception raised by any rule propagates
    out uncaught. This is by design — a policy outage must not be
    silently swallowed (see ADR-0001). The send-loop is expected to
    log + halt the run; do not add a try/except here.
    """
    for rule in rules:
        result = rule.evaluate(ctx)
        if not isinstance(result, Allow):
            # Any non-Allow is a Block (RuleResult is Allow | Block).
            # Returning eagerly is the short-circuit — later rules in
            # the chain are not consulted, which is the contract the
            # send-gate relies on for "exactly one policy_blocked
            # event per gate decision."
            return result
    return Allow()


def evaluate_all(
    rules: Iterable[Rule], ctx: RuleContext,
) -> list[RuleResult]:
    """Non-short-circuit evaluation. Every rule's verdict, in order.

    Returns a list parallel to ``rules`` — ``result[i]`` is the verdict
    rule ``i`` produced for ``ctx``. Used by the simulation CLI
    (``python -m orchestrator.policy simulate ...``) to answer "what
    would EVERY rule say about this send?" rather than the production
    "would ANY rule block?" question.

    Where this differs from :func:`evaluate`:

    * **No short-circuit.** Every rule's ``evaluate`` is called even
      if an earlier rule returned ``Block``. The simulation use case
      is "show me every reason this send could fail," so seeing the
      second and third blockers is the whole point.
    * **Return shape.** ``list[RuleResult]`` not ``RuleResult``. An
      empty rule list returns ``[]`` (not ``[Allow()]`` — the empty
      list contains zero verdicts, which is the truthful shape).

    What stays identical to ``evaluate``:

    * **Exception propagation.** A rule raising still bubbles up
      uncaught (ADR-0001 §Decision item 2). No try/except wrapper:
      a policy outage during simulation is still a policy outage and
      the caller is expected to see the stack trace. The CLI in
      ``__main__.py`` catches at the outer surface so a single bad
      rule doesn't prevent the operator from seeing the verdicts of
      every other rule — but the engine itself stays clean.
    * **Rule order.** Same iteration order; the parallelism between
      ``rules`` and the returned list is load-bearing for the CLI's
      "rule N produced verdict M" presentation.

    See ADR-0001 §Alternative 4 for the original anticipation of this
    function (the "evaluate_all for simulation mode" plan); ADR-0007
    §Decision item "Simulation surface" locks the v1 contract.
    """
    out: list[RuleResult] = []
    for rule in rules:
        out.append(rule.evaluate(ctx))
    return out


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def load_rules_from_yaml(path: Path) -> list[Rule]:
    """Parse a policy YAML file and construct ``Rule`` instances.

    A missing file returns ``[]`` (greenfield OSS install); structural
    errors raise ``ValueError``.

    The file shape:

        version: 1
        rules:
          - name: <human identifier>
            type: <registry discriminator>
            # ...rule-specific fields...

    The ``name`` field becomes the rule instance's ``name`` attribute
    (used in ``Block.rule``). The ``type`` field selects the class from
    ``RULE_REGISTRY``. Everything else is passed through to the class's
    ``from_yaml`` classmethod as-is.

    Raises
    ------
    ValueError:
        - ``version:`` missing or not in ``SUPPORTED_POLICY_SCHEMA_VERSIONS``.
        - A rule entry missing ``name:`` or ``type:``.
        - A rule entry's ``type:`` not in ``RULE_REGISTRY``.
        - The file isn't a mapping at the top level.
    """
    p = Path(path)
    if not p.exists():
        return []

    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        # An empty file (or one containing only `---`) — treat as no rules.
        return []
    if not isinstance(data, dict):
        raise ValueError(
            f"policy file {p}: top-level must be a mapping, got {type(data).__name__}",
        )

    if "version" not in data:
        raise ValueError(
            f"policy file {p}: missing required 'version' key",
        )
    # Normalize to int — YAML quotes (`version: "1"` / `version: '1'`)
    # parse as ``str``, but ``SUPPORTED_POLICY_SCHEMA_VERSIONS`` is a
    # frozenset of Python ``int``. Without the coercion, a quoted
    # version field — which ``orchestrator.migrations.policy._policy_io.
    # bump_version_text`` deliberately preserves on rewrite — would
    # produce a string that's not in the int frozenset, and the engine
    # would refuse to load the file post-migration. Pillar B Week 6
    # parallel-review P1 fix per `.planning/REVIEW-pillar-a-b-coherence.md`
    # §P1-1. ``int()`` on an already-int is a no-op; ``int()`` on a
    # well-formed string raises ``ValueError`` which surfaces as the
    # same "unsupported version" message below.
    raw_version = data["version"]
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        version = raw_version  # let the membership check refuse loud
    if version not in SUPPORTED_POLICY_SCHEMA_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(SUPPORTED_POLICY_SCHEMA_VERSIONS))
        raise ValueError(
            f"policy file {p}: unsupported version {raw_version!r} "
            f"(this build supports versions {{{supported}}})",
        )

    rules_spec = data.get("rules", [])
    if not isinstance(rules_spec, list):
        raise ValueError(
            f"policy file {p}: 'rules' must be a list, got {type(rules_spec).__name__}",
        )

    out: list[Rule] = []
    for idx, spec in enumerate(rules_spec):
        if not isinstance(spec, dict):
            raise ValueError(
                f"policy file {p}: rules[{idx}] must be a mapping, "
                f"got {type(spec).__name__}",
            )
        if "name" not in spec:
            raise ValueError(
                f"policy file {p}: rules[{idx}] missing required 'name' key",
            )
        if "type" not in spec:
            raise ValueError(
                f"policy file {p}: rule {spec['name']!r} missing required 'type' key",
            )
        type_name = spec["type"]
        cls = RULE_REGISTRY.get(type_name)
        if cls is None:
            known = ", ".join(sorted(RULE_REGISTRY)) or "(none registered)"
            raise ValueError(
                f"policy file {p}: rule {spec['name']!r} has unknown type "
                f"{type_name!r}; known types: {known}",
            )
        out.append(cls.from_yaml(spec))
    return out
