# ADR-0002: Cooldown rules + recipient timezone semantics

- **Status:** Accepted
- **Date:** 2026-05-16
- **Pillar:** A (Policy engine — first concrete rule class)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0001 established the policy engine surface (`evaluate`, `Rule` Protocol, YAML registry). This ADR specifies the first concrete rule class — cooldown — and resolves two questions the engine left open:

1. **Which cooldown rules ship as factory defaults?** Yang's original Phase 5.5 §5.5.D HANDOFF named four: no-double-cold-pitch, follow-up-requires-prior-cold-pitch, re-engage-requires-dormancy, domain-cooldown. Pillar A inherits all four.

2. **What does "timezone-aware and DST-safe" mean for cooldown specifically?** PILLAR-PLAN §5 commits to "per-person tz inferred from `identity_keys.country`; fallback `America/Los_Angeles`," but the *use* of that timezone in cooldown rules isn't yet defined. The naive interpretation ("7-day cooldown is 7 calendar days in their local tz") would make DST transitions a 1-hour-off bug source. The correct interpretation needs to be written down before the rules read like idioms.

A third practical question — how the engine recognizes prior `cold-pitch` sends — surfaces here too: the ledger's `send_intent` event carries a `register:` field (added in Phase 5.5 Week 3 at `send_queued.py:315`), so cooldown rules can join `send_intent` → `send_confirmed` pairs and condition on the prior register.

## Decision

**Cooldown age math is computed in UTC.** The ledger's `ts` field is ISO-8601 UTC; `RuleContext.now` is timezone-aware UTC. `timedelta` subtraction is unambiguous and DST-irrelevant. The recipient's `timezone` field on `RuleContext` is *not consulted* by cooldown rules — it is reserved for sending-window rules (Pillar A Week 3 task) which need local-time-of-day evaluation.

"7 days" therefore means "168 hours of wall-clock UTC time." Documented in YAML comments and in `cooldown.py` docstrings so users editing the rules aren't surprised.

**Four factory rule classes** with one-class-per-yaml-discriminator:

| YAML discriminator | Class | Role |
|---|---|---|
| `cooldown.no-duplicate-register` | `NoDuplicateRegisterRule` | Block if a prior confirmed send to this person with the same register exists. Factory rule: `no-double-cold-pitch`. |
| `cooldown.requires-prior-send` | `RequiresPriorSendRule` | Block if no confirmed prior send to this person with the required register exists, or if it exists but is too recent. Factory rule: `follow-up-requires-prior-cold-pitch` (requires `register: cold-pitch`, `min_age_days: 7`). |
| `cooldown.requires-person-status` | `RequiresPersonStatusRule` | Block if `ctx.person_status` does not match the required value. Factory rule: `re-engage-requires-dormancy` (requires `person_status: dormant`). |
| `cooldown.domain-throttle` | `DomainThrottleRule` | Block if `ctx.email_domain` has had ≥`count` confirmed sends in the last `days` days. Factory rule: `domain-cooldown` (`count: 1, days: 14`). |

**`person_status` joins `RuleContext`.** The send-gate caller (Week 1 task #6) reads it from `Person.status` (already exposed via `vault.py:152`) and passes it in. `None` is treated as "status unknown — most restrictive interpretation" (refuse re-engage if we can't confirm dormancy; the "false-positive > false-negative" memory applies).

**Rule scoping (`block_when:`).** Every rule may declare a `block_when:` filter that determines whether the rule applies to this send at all. Supported keys: `register:`, `channel:`. If the filter doesn't match, the rule returns `Allow()` without further work. This keeps YAML readable — a domain-throttle rule with `block_when: {channel: email}` won't fire on LinkedIn sends.

**DST property test (Hypothesis).** The Pillar A exit criterion mandates DST-safety. Since cooldown is UTC-only by decision above, the property reduces to: *for any recipient timezone, the cooldown verdict is identical to the UTC verdict*. Property test asserts: `rule.evaluate(ctx_with_tz_X) == rule.evaluate(ctx_with_tz_UTC)` for X ∈ {a representative set including across-DST and never-DST zones}, across a wide range of `last_send_ts` and `now` values including DST-transition adjacent timestamps.

## Alternatives considered

### Alternative 1: Cooldown rules compute age in recipient's local timezone
"7 days" would mean "7 calendar days in their tz" — i.e., `now_in_local_tz - 7d_calendar_subtraction`. **Rejected because:** introduces a DST-bug class for marginal benefit (1h different verdict on rare days). The pattern "we want to wait at least a week" is rounded enough that ±1h doesn't change a human's expectation. UTC is simpler, more testable, and provably DST-safe.

### Alternative 2: One YAML-discriminator per rule (e.g. `cooldown.no-double-cold-pitch`)
Concrete rule names become the discriminator; YAML has no `block_when:`, just direct hardcoded behavior. **Rejected because:** four classes balloon into ~12 (every variant — `no-double-follow-up`, `no-double-re-engage`, `linkedin-no-double-cold-pitch`...). The "rule class is the mechanism; YAML names are the configuration" split keeps the surface small and gives users power to write `no-double-follow-up` themselves without code changes.

### Alternative 3: Defer Rule 3 (re-engage-requires-dormancy) to Week 2
The other three rules don't need `person_status` in the RuleContext. Adding it now is a minor type surface change. **Rejected because:** the `person_status` field costs nothing (default `None`), and shipping all four factory rules in one commit gives the test matrix natural coverage of rule-interaction patterns. Deferring would split the discipline artifact (one ADR per rule batch) for no real saving.

### Alternative 4: Encode rules as data-driven SQL-like predicates (e.g. JSON Logic)
A single generic `cooldown.predicate` rule class with a JSON Logic expression instead of named classes. **Rejected because:** users would write SQL-shaped rules in YAML; the four named classes capture every cooldown pattern the HANDOFF identified plus the patterns Pillar A specifies. Generic predicate engine is over-design for ~5 rules.

## Consequences

### Positive
- Cooldown rules are deterministic, DST-irrelevant, and unit-testable without time-zone fixtures.
- The four factory classes cover every pattern named in the HANDOFF and PILLAR-PLAN — users adding a new pattern often won't need new code, just a new YAML rule.
- `person_status` on `RuleContext` is a forward-compatible field other Pillar A rule classes (suppression, tier) may consume.

### Negative
- "7-day cooldown" in user mental model may be "7 calendar days local" but is technically "168 hours UTC." For most timezones the discrepancy is at most 1h and only on DST-transition days — documented in `cooldowns.example.yml` so users aren't surprised.
- `RequiresPersonStatusRule` depends on the caller passing a correct `person_status` — if the caller forgets and defaults `None`, re-engage sends get refused (safer side of the asymmetry, but a footgun if the caller integration regresses). Mitigated by integration test in task #6.

### Neutral / observability
- Cooldown blocks emit the standard `policy_blocked` ledger event (per ADR-0001). The `detail` field carries: `rule` discriminator (so we know which class), `prior_intent_id`, `prior_send_ts`, `age_at_check_seconds`. The funnel CLI surfaces these by-rule counts when reporting why sends were refused.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAMLs at `~/.outreach-factory/policies/cooldowns.yml` are the SoT for cooldown logic (registry row already present in `docs/SOURCES-OF-TRUTH.md`).
- **I3 (schema versioning):** YAML carries `version: 1` (enforced by `load_rules_from_yaml`). When rule semantics change, version bump + migration entry in `orchestrator/migrations/policy/` (Pillar B).
- **I5 (observable by default):** Every Block emits `policy_blocked` with full diagnostic.
- **I6 (tests prove invariants):** Hypothesis property test proves DST-safety; parameterized matrix covers each factory rule's allow/block branches; an "empty history → no false blocks" property is included.
- **I8 (decisions documented):** This ADR.

Does not weaken any invariant.

## Migration / rollout

Greenfield: no migration needed for the rule classes themselves. The factory YAML `config-template/cooldowns.example.yml` ships in the repo; doctor preflight (Phase 5) is extended in task #6 to copy it to `~/.outreach-factory/policies/cooldowns.yml` on first run if the user doesn't have a file. Until then the engine returns `Allow()` on a missing file (per ADR-0001), which preserves current behavior.

`RuleContext.person_status` is a new field with default `None` — all existing test contexts continue to construct without modification.

## References

- ADR-0001 (policy engine architecture)
- `docs/PILLAR-PLAN.md` §2 Pillar A; §5 (timezone resolution row)
- `.planning/HANDOFF-phase-5.5.md` §5.5.D (original cooldown.yml design — this ADR is the formal acceptance)
- `skills/send-outreach/scripts/send_queued.py:307–315` (the `send_intent` event with `register:` field that rules consume)
- `skills/send-outreach/scripts/vault.py:152` (where `Person.status` comes from)
- ADR-0003 (Channel as first-class policy predicate) — published 2026-05-16 before Pillar A Week 2 begins; pulls the cross-channel rule shape forward from Pillar C into Pillar A v1.
- ADR-0004 (Suppression rules + GDPR forget) — Week 2 sibling.
- ADR-0005 (Sending-window rules + recipient timezone inference) — Week 3 sibling; locks the semantics of `RuleContext.timezone` (this ADR reserved the field; ADR-0005 makes it operationally meaningful).
- ADR-0006 (Budget rules + `cost_incurred` event) — Week 4 sibling; landed 2026-05-18. The cooldown DST property test continues to hold after Week 4 (regression sentinel in `tests/test_policy_budget.py::TestCooldownDSTPropertyStillHolds`).
- Followups: ADR-0007 tier rules (Week 5). (Numbering shifted forward by one from this ADR's original "0005 budget" list to accommodate sending-window landing at 0005; see ADR-0005 §ADR numbering shift.)
