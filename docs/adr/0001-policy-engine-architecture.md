# ADR-0001: Policy engine architecture

- **Status:** Accepted
- **Date:** 2026-05-16
- **Pillar:** A (Policy engine)
- **Deciders:** Yang, Claude (architect)

## Context

Phase 5.5 Week 3 shipped the two-phase send commit with a hardcoded gate in `skills/send-outreach/scripts/send_queued.py:gated_send_one` covering three rules: `not_a_person_note`, `identity_incomplete`, `already_sent`. A fourth — `cooldown` — was left as a stub comment at `send_queued.py:286–291` waiting for a backing implementation:

```python
# Cooldown check hook (Phase 5.5 Week 4):
#   policy = cooldown.check(person_id, "email", register, led)
#   if isinstance(policy, cooldown.Block):
#       return _blocked(...)
```

Pillar A of the 10-pillar plan (see `docs/PILLAR-PLAN.md` §2) widens that hook to five policy classes — cooldown, suppression, budget, sending-window, tier — and adds a sixth concern (simulation mode: "which rule would block X tomorrow?"). A linear chain of hardcoded `if` branches in `gated_send_one` does not scale to that surface, and would push policy changes onto code deploys instead of config edits.

This decision sets the engine architecture that all five rule classes consume.

## Decision

Build `orchestrator/policy/` as a declarative, ordered short-circuit rule engine:

1. **`types.py`** defines:
   - `Allow` — frozen dataclass with no fields; marker for "rule passed."
   - `Block` — frozen dataclass with `rule: str`, `reason: str`, `detail: dict`. `rule` names the firing rule; `reason` is human-readable; `detail` carries rule-specific evidence (blocking event ts, threshold breached, etc.) that the caller serializes into the `policy_blocked` ledger event.
   - `RuleResult = Allow | Block` — the verdict type.
   - `RuleContext` — frozen dataclass passed to every rule. Fields: `person_id`, `channel`, `register`, `email`, `email_domain`, `now: datetime`, `timezone: str`, `ledger: LedgerLike`. `now` is injectable for testability; `timezone` is the recipient's IANA tz (Pillar A Week 1 task #5 fills the inference logic).
   - `LedgerLike` — `typing.Protocol` exposing the subset of `Ledger` methods rules call (`query_by_person`, `last_send_for`, `query_by_email`, `all_events`). Tests pass fakes; production passes the real `Ledger`.
   - `Rule` — `typing.Protocol` with `name: str`, `evaluate(self, ctx: RuleContext) -> RuleResult`, and `from_yaml(cls, spec: dict) -> Rule` classmethod for YAML instantiation.

2. **`engine.py`** defines:
   - `RULE_REGISTRY: dict[str, type[Rule]]` — a module-level registry keyed by rule discriminator (e.g. `"cooldown.register-cooldown"`, `"suppression.email"`).
   - `register_rule_class(type_name: str, cls: type[Rule]) -> None` — called by rule modules at import time. Double-registration raises `ValueError` (silent shadow is the bug).
   - `evaluate(rules: Iterable[Rule], ctx: RuleContext) -> RuleResult` — ordered short-circuit. First `Block` wins; empty input returns `Allow()`. Exceptions raised by rules propagate uncaught — a bug in a rule is a policy outage, and silent swallowing would hide it from the gate. Caller is responsible for surfacing the outage (Pillar G observability).
   - `load_rules_from_yaml(path: Path) -> list[Rule]` — parses the YAML file, validates `version:`, walks `rules:`, dispatches each spec by `type:` to its registered class's `from_yaml`. Missing file → empty list (greenfield OSS install must not block; doctor preflight in Phase 5 reports the absence). Wrong version → raises. Unknown rule type → raises.

3. **Sub-modules per rule class** (`cooldown.py`, `suppression.py`, `budget.py`, `sending_window.py`, `tier.py`) define their concrete `Rule` classes and call `register_rule_class` at module bottom.

4. **`__init__.py`** re-exports the public surface (`Allow`, `Block`, `RuleContext`, `evaluate`, `load_rules_from_yaml`) and imports the sub-modules for their registration side effect.

## Alternatives considered

### Alternative 1: Hard-coded `if` ladders in `gated_send_one`
Keep extending the existing gate with one `if` block per rule class. **Rejected because:** doesn't scale past 5–7 rules without becoming unreviewable; policy changes require code deploys and PR review for every cooldown tweak; no path to simulation mode or live reload (Pillar H); rule ordering is implicit and easy to break in refactors.

### Alternative 2: Open Policy Agent (OPA) / Rego
A purpose-built policy DSL with a battle-tested engine and tooling. **Rejected because:** adds a Go runtime as a hard dependency for a Python-only project; introduces a DSL (Rego) that Yang and future contributors have to learn before they can edit a cooldown rule; the entire Pillar A rule surface totals <100 LoC of logic — overshooting by importing OPA is a worse tradeoff than maintaining a hand-rolled evaluator.

### Alternative 3: Python rule functions (no class hierarchy)
Each rule is a bare `Callable[[RuleContext], RuleResult]`. Engine just iterates. **Rejected because:** loses the natural home for YAML-spec instantiation (`from_yaml` classmethod), forcing a parallel parsing-function registry. Single class-with-classmethod is the cleanest place to put both `evaluate` and `from_yaml`.

### Alternative 4: Aggregate-all-then-decide
Collect every rule's verdict, return all `Block`s, let the caller pick. **Rejected because:** ordered short-circuit gives a clear audit ("which rule blocked this") and lets rule ordering deterministically encode priority. Aggregation buys nothing for the gate path; if a simulation mode wants the full block-set, we add a separate `evaluate_all` later — the load-bearing path stays simple.

### Alternative 5: One YAML file per rule class
Five files instead of one. **Rejected because:** users edit cooldown rules and budget rules together when they're tuning a campaign; splitting forces multi-file edits for a single conceptual change. A future option could let `load_rules_from_yaml` accept a list of files for users who do want segregation; we don't pre-build that.

## Consequences

### Positive
- Policy changes are config edits, not code edits.
- One uniform `policy_blocked` ledger event shape across all rule classes — feeds observability (Pillar G).
- Simulation mode is a `evaluate(rules, ctx_at_future_time)` call away — no separate code path.
- Live reload (Pillar H daemon SIGHUP) becomes a re-call to `load_rules_from_yaml`.
- Test fakes implement `LedgerLike` Protocol without any inheritance plumbing.
- `channel` is first-class on `RuleContext` (decision item 1), enabling both same-channel scoping (ADR-0002 `block_when:`) and cross-channel join rules (ADR-0003 `consider_channels:`) without engine or `LedgerLike` changes.

### Negative
- Rule ordering in `cooldowns.yml` is load-bearing — a misordered file can mask higher-priority blocks (a `domain-throttle` rule placed after `no-double-cold-pitch` would still fire correctly, but a future rule that *depends* on running before another could break silently if reordered). Mitigation: rule-coverage analyzer in Pillar A Week 5 reports rule-fire frequency; misordering surfaces as "this rule never fires" anomalies.
- A bug in one rule short-circuits the whole gate (exception propagates uncaught). This is by design — silent swallow is worse — but it means a single bad YAML can halt sends. Mitigation: load-time validation in `load_rules_from_yaml` catches structural errors before any send is attempted; doctor preflight runs `evaluate` with synthetic contexts as a smoke test.

### Neutral / observability
- Every `Block` returned by `evaluate` is logged to the ledger as a `policy_blocked` event with `rule`, `reason`, and `detail` fields. The funnel CLI (`ledger.py funnel`) already counts events by type, so policy refusals appear in the funnel breakdown without any new code.

## Compliance with invariants

- **I1 (single source of truth):** Policy files in `~/.outreach-factory/policies/*.yml` are the SoT for "what blocks a send?". `docs/SOURCES-OF-TRUTH.md` row already covers this. No denormalized view exists yet; if simulation results get cached, that cache is the view.
- **I5 (observable by default):** Every Block emits a `policy_blocked` ledger event with full diagnostic context.
- **I7 (cost is first-class):** Budget rules (Week 2 task) consume `cost_incurred` events from the ledger; this ADR establishes the seat for them.
- **I8 (documented decisions):** This ADR is the seat for the architectural decision.
- Does not weaken any other invariant.

## Migration / rollout

Greenfield package; no migration needed for Week 1. The cooldown hook stub at `send_queued.py:286–291` becomes the integration point in Pillar A Week 1 task #6 (`policy.evaluate` replaces the comment). Existing 260 tests must still pass after that integration — the engine returning `Allow()` on an empty rules list preserves current behavior for users who haven't authored a `cooldowns.yml` yet.

## References

- `docs/PILLAR-PLAN.md` §2 Pillar A
- `.planning/HANDOFF-phase-5.5.md` §5.5.D (original cooldown design — superseded by this ADR)
- `skills/send-outreach/scripts/send_queued.py:286–291` (the cooldown hook stub being filled)
- `orchestrator/ledger.py:Event`, `Ledger.last_send_for`, `Ledger.query_by_person` (the surface rules consume)
- Subsequent ADRs in this series:
  - ADR-0002 (Cooldown rules + per-recipient timezone)
  - ADR-0003 (Channel as first-class policy predicate)
