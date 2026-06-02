# ADR-0007: Tier rules + cross-cutting `block_when: {tier|tier_in}` + simulation surface

- **Status:** Accepted
- **Date:** 2026-05-19
- **Pillar:** A (Policy engine — fifth concrete rule batch + simulation foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0001 established the policy engine; ADR-0002 shipped four cooldown rule classes; ADR-0003 added the cross-channel rule; ADR-0004 added three suppression rule classes; ADR-0005 added two sending-window rule classes + the timezone-inference module; ADR-0006 added three budget rule classes + the `cost_incurred` event + the `manual_override` event schema. Pillar A Week 5 ships the **tier** rule class — the fifth concrete rule batch — closing out the "research/priority tier as gate predicate" failure mode the Outreach Tier Playbook + PILLAR-PLAN §1 I5 both name. The simulation surface (`evaluate_all` + `python -m orchestrator.policy simulate`) also lands here, fulfilling ADR-0001 §Alternative 4's anticipated "non-short-circuit variant for simulation mode."

Five concerns this ADR resolves:

1. **The Outreach Tier Playbook has no enforcement.** The Playbook (`research_tier: S | A | B`) is the operator's mental model for prioritization, but the send-gate has never refused a low-tier prospect on register-mismatch. Yang's reflex of "tier-B prospects don't get cold-pitches" has been hope-not-process: no rule fires, the operator catches it at draft review (or doesn't). Tier-as-policy-predicate fixes this — the rule refuses on the gate before any draft is composed.

2. **`RuleContext.tier` was an empty seat.** Like `RuleContext.timezone` before ADR-0005 (semantically inert until sending-window rules consumed it), `RuleContext.tier` has been a planned-not-shipped field. ADR-0005 §Decision item "Country signal" set the precedent: an additive context field lands in the same commit as its first consumer. This ADR ships both — the field on `types.py` + the `TierRequiresTierInRule` consumer + the cross-cutting `block_when:` filter that lets every existing rule class scope by tier without per-class code.

3. **PILLAR-PLAN §1 I5 names tier as a funnel breakdown dimension.** I5's SLO is `python orchestrator/funnel.py --since 30d --breakdown source,tier,gate_reason`. Until the gate populates `ctx.tier` from Person frontmatter AND tier rules emit it on `policy_blocked` events, the `tier` axis of that breakdown is structurally unavailable. This ADR completes the wiring.

4. **The simulation surface ADR-0001 reserved is empty.** ADR-0001 §Alternative 4 anticipated `evaluate_all` for simulation mode but didn't land it. Without simulation, an operator debugging "why did my YAML refuse this send?" has to construct a synthetic ledger + run the production gate. The simulation surface answers "every rule's verdict on this hypothetical context" in one shot.

5. **The Week 4 review surfaced `manual_override` as a 2am-incident footgun.** ADR-0006 §`manual_override` event schema is concrete, but the only operator path to producing one was hand-crafted JSON via `python orchestrator/ledger.py append @event.json`. The Week 4 review (W1) called this out as the "incident at 2am, operator types malformed JSON" failure mode. This ADR ships the operator surface (`python -m orchestrator.policy override ...`) that validates the args + writes a correct event.

The asymmetric-failure-cost principle (PILLAR-PLAN §0) applies to tier the way it does to suppression: an un-tiered prospect (the Person note has no `research_tier:` field at all) in a tier-gated register is the failure mode tier rules exist to catch. The rule refuses on `ctx.tier is None`. The opposite reading ("be lenient when we don't know") would silently route the un-tiered cold-pitch through and the rule would only fire on the operator's tier-B prospects — the failure mode they probably already knew about. Refuse-loud on unknown extends coverage to the cases the operator doesn't realize they have.

Risks this ADR mitigates by design: **R012** (low-tier cold-pitches damage reply-rate signal); inherits the "missing data → refuse" stance from ADR-0002 / ADR-0004 / ADR-0006.

## Decision

### One concrete rule class

| YAML discriminator | Class | Role |
|---|---|---|
| `tier.requires-tier-in` | `TierRequiresTierInRule` | Block when `ctx.tier` is not in `allowed_tiers`. Factory pattern: `cold-pitch-tier-gate` (block_when: `{register: cold-pitch}`, `allowed_tiers: [S, A]`). |

Lives in `orchestrator/policy/tier.py` and registers itself into `RULE_REGISTRY` at import time (the standard pattern set by ADR-0002).

### Cross-cutting `block_when:` extension

`_block_when_matches` (the shared filter helper used by cooldown / cross-channel / sending-window / budget) gains two new keys:

* **`tier`** *(exact match)* — equality on `ctx.tier`. A `None` `ctx.tier` does NOT match a non-None filter value; the filter never fires the rule on a Person note that lacks a tier.
* **`tier_in`** *(set membership)* — `ctx.tier in tier_in`. List form only; scalar raises `TypeError` at evaluation time so a typo like `tier_in: S` doesn't silently match (`"S" in "S"` is True; `"A" in "S"` is False — false-positive-on-typo is exactly what set-membership avoids). Empty list does NOT match anything. Case-sensitive exact match per entry.

The two keys compose with each other and with the existing `register:` / `channel:` keys via natural `AND` semantics (mirrors how cooldown rules already AND `register:` + `channel:`).

The behavioral contract: a rule whose `block_when:` filter doesn't match returns `Allow()` for that evaluation. Adding `tier` / `tier_in` here means EVERY existing rule class — cooldown, cross-channel, suppression, sending-window, budget — gains tier-scoped variants without any per-class code changes. The example YAML in `config-template/cooldowns.example.yml` (Rule 13) demonstrates "tier-S Apollo cap can be wider than the global cap" by combining `block_when: {register: cold-pitch, tier: S}` with `budget.window-cap`. The cooldown / cross-channel / sending-window / budget tests pass unchanged because none of them use the new keys.

### `RuleContext.tier` semantics

Free-form `str | None` field on `RuleContext`. Additive change with a `None` default — every existing test construction site continues to work without modification.

* **Source in v1: hardcoded to `Person.research_tier`** (already parsed by `vault.PersonInfo.research_tier`; the send-gate's `_build_rule_context` populates `tier=draft.person.research_tier`). The Outreach Tier Playbook's `S | A | B` taxonomy is the de facto OSS-default tier scheme.
* **Future config knob: `policy.tier_field`** — operators with a different tier scheme (e.g. `priority: P1 | P2 | P3` per `find-funded-founders/SKILL.md:541`) will eventually flip a config field to point `ctx.tier` at a different frontmatter source. Deliberately deferred to a future ADR — see §Alternative 2.

The rule and the cross-cutting filter both treat `ctx.tier` as an opaque string. They never know what taxonomy is in use. This is what lets `tier.requires-tier-in` work for both `[S, A, B]` and `[P1, P2, P3]` operators without code changes — the value comes from the Person note, the allowed set comes from the YAML rule, the engine compares strings.

### Tier rule decisions

**Set-membership, no ordering.** `tier.requires-tier-in` does not encode `S > A > B` (or `P1 > P2 > P3`). Operators write the allowed set explicitly. Rationale:

* Tier ordering depends on the scheme. `P1 > P2 > P3` inverts the `S > A > B` intuition (numerics ascending = worse; letters ascending = worse). A config-driven ordering ("which is the high end?") is brittle.
* The cost of getting ordering wrong is asymmetric. False-Allow on a low-tier prospect is exactly the failure mode tier rules exist to prevent. Set-membership refuses on typo (a missing letter from the allowed set means a prospect with that tier is refused — loud); min-tier silently extends (a typo in the ordering config lets unintended tiers through — quiet).
* The brevity gain from `min_tier: A` over `allowed_tiers: [S, A]` is one YAML line. Not worth the ordering footgun.

**`None`-tier → BLOCK (restrictive).** When the Person note lacks the configured tier field, `ctx.tier` is `None`. The rule treats this as "unknown tier" and BLOCKs (mirrors the `RequiresPersonStatusRule` None-handling precedent in ADR-0002). The `detail.tier_unknown: true` field surfaces the cause distinct from `detail.tier_value: <value>` for a wrong-tier block.

The cross-cutting `block_when: {tier|tier_in}` filter behaves differently: a `None` `ctx.tier` makes the filter NOT MATCH (the rule does not fire on this send). That's because the filter is a scoping mechanism ("this rule applies only to tier-S sends"), not the substantive gate ("this send must have a valid tier"). The substantive gate is the `tier.requires-tier-in` rule itself; the filter just scopes who else cares.

The two behaviors are consistent because the filter's purpose is "skip me when I don't apply" while the rule's purpose is "refuse the un-tiered case." An operator who wants "refuse un-tiered sends generally" writes the substantive rule; an operator who wants "tier-S Apollo cap is wider" writes a tier-scoped budget rule, and untiered sends fall back to the global cap rule (which is exactly what they want — the global cap still protects them).

**Empty `allowed_tiers: []` → degenerate BLOCK.** Mirrors `DayOfWeekRule`'s `allowed_days: []` convention from ADR-0005. A typo'd YAML that produced an empty list should refuse every send the rule scopes to (refuse-loud) rather than open the floodgates (silently allow). `detail.degenerate: true` surfaces this in audit.

**Case-sensitive exact match.** Operators write the values the way they appear in frontmatter. `"s"` does not match `"S"`. The send-gate populates `ctx.tier` from `Person.research_tier` without normalization — the source-of-truth casing propagates. Aliasing (`"s"` → `"S"`) would couple the rule to a single tier-scheme's conventions; staying exact-match keeps the rule scheme-agnostic.

**`block_when:` supported.** Tier rules accept `block_when:` (cooldown / cross-channel / sending-window / budget precedent). Tier is tunable policy — operators may want a per-channel tier gate ("LinkedIn DMs go out to A and B, email cold-pitch only to S and A") that differs from a per-register one. The suppression-style kill-switch posture (ADR-0004 §Alternative 8) does NOT apply.

### Simulation surface

**`engine.evaluate_all(rules, ctx) -> list[RuleResult]`.** Non-short-circuit variant of `evaluate`. Returns one verdict per rule, in iteration order. Exceptions still propagate uncaught (ADR-0001 §Decision item 2). Empty `rules` returns `[]` (not `[Allow()]` — the empty list contains zero verdicts, which is the truthful shape).

The CLI subcommand `python -m orchestrator.policy simulate` loads `~/.outreach-factory/policies/cooldowns.yml` (or an `--policies-dir` / `--rules-file` override), reads a named Person note for `id` + `country` + `research_tier` + `status` + `email`, builds a `RuleContext` (using `tz_inference.infer_timezone(country)`, the same source the production gate uses), and prints every rule's verdict. `--at <ISO datetime>` lets operators time-travel ("would a send tomorrow morning at 9am their tz be blocked by sending-window?"). `--json` emits a parseable shape for tooling.

**Where simulation lives.** `engine.py` for `evaluate_all`; `__main__.py` for the CLI. NOT a standalone `simulation.py` module yet — see §Alternative 4.

### Operator tooling — `manual_override` write surface

**`python -m orchestrator.policy override --rule <name> --until <ISO> --reason <text> --approved-by <user> [--person <id>] [--run <id>]`.** Validates the args + writes a `manual_override` ledger event per ADR-0006's schema. The CLI:

* Refuses `--until` values that are not strict ISO-8601.
* Refuses `--until` values that are already in the past (override would be a no-op; the budget rule's `_is_overridden` would immediately ignore it — block the write rather than silently accept a no-op).
* Requires `--rule`, `--until`, `--reason`, `--approved-by` (audit-trail completeness — Pillar J's CI gate will demand all four anyway).
* Omits `scope` from the event when neither `--person` nor `--run` is given (ADR-0006 §`manual_override` "scope absent = no scope constraint on this field").

Reduces the W1 "operator types malformed JSON at 2am" failure mode. ~80 LOC of CLI plumbing; no new event schema; no engine surface change.

### Pillar A Week 5 emit sites (initial wiring)

| Emit site | Field populated | Source |
|---|---|---|
| `skills/send-outreach/scripts/send_queued.py:_build_rule_context` | `RuleContext.tier` | `draft.person.research_tier` (already parsed by `vault.load_person`) |

Pillar G's funnel CLI (`--breakdown source,tier,gate_reason`) automatically gains the `tier` axis the moment this ADR's wiring lands — no new code in `funnel.py`, because `policy_blocked` events' `policy_detail.tier_value` field already serializes when the rule fires.

## Alternatives considered

### Alternative 1: Hardcode the tier field name (`research_tier`) with no future config knob

Cleaner; one fewer config dimension; matches what 100% of OSS users will use today (the Outreach Tier Playbook's S/A/B is the de-facto default). **Rejected because:** operators with non-`research_tier` schemes shouldn't have to fork the code. The current PILLAR-PLAN list of factory skills already contains BOTH `research_tier` (S/A/B) AND `priority` (P1/P2/P3) — they semantically overlap (both are tier-shaped predicates) but they have different cardinalities and different sources. Hardcoding `research_tier` would force operators using `priority` to either re-key every Person note or maintain a fork. The v1 ships hardcoded with the deferred-config-knob escape hatch; the rule class is already scheme-agnostic, so the knob is purely a `_build_rule_context` change when the time comes.

### Alternative 2: Ship the `policy.tier_field` config knob in v1

Read the config field at gate-construction time; let operators point at any frontmatter field. **Rejected for v1 — deferred** because YAGNI applies for the ~0 OSS users in the next quarter who'll need this. The deferred knob is a single-file change to `_build_rule_context` (replace `draft.person.research_tier` with a getattr-by-config-name lookup) plus a config-schema entry; no engine or rule changes. When an operator actually needs it, the change is < 30 LOC. Shipping the knob now would force `vault.PersonInfo` to grow a generic `extra_fields: dict` field (so the gate can read whatever the operator pointed at) — a bigger change than the actual demand justifies. Cited under ADR-0007 §Decision item "Tier field source" so the future contributor knows where to land it.

### Alternative 3: Min-tier ordering on `tier.requires-tier-in`

`min_tier: A` instead of `allowed_tiers: [S, A]` — operators get brevity, the rule encodes `S > A > B`. **Rejected because:** ordering depends on the scheme (S/A/B vs P1/P2/P3 invert), false-Allow is the cost-asymmetric direction, and the brevity savings (one YAML line per rule) are not worth the ordering footgun. Documented at length in the rule's module docstring. Sympathetic to the brevity argument; the cost of getting it wrong is what tips the balance.

### Alternative 4: Ship a separate `simulation.py` module now even if it's thin

PILLAR-PLAN's §2 Pillar A package list names `simulation.py` as a Week-5/6 deliverable. **Rejected — Week 5 ships `evaluate_all` + the CLI in `engine.py` + `__main__.py`; standalone `simulation.py` waits.** Rationale: the Week-5 simulation surface is two functions (`evaluate_all` + the CLI's `_cmd_simulate`). A standalone module would mostly contain re-exports and one helper. The PILLAR-PLAN's `simulation.py` is reserved for what-if simulation features that haven't been spec'd yet (alternative rule sets, batch what-if across many synthetic prospects, time-window simulation). Those features will need their own module when they land; pre-creating an empty shell now is premature abstraction. The module-name PILLAR-PLAN reserved is unblocked, not consumed.

### Alternative 5: Tier as a kill switch (no `block_when:`)

Force every tier rule to apply to every send unconditionally — mirroring suppression's posture (ADR-0004 §Alternative 8). **Rejected because:** tier is tunable policy, not a kill switch. An operator may legitimately want different tier requirements per register (cold-pitch refused for tier-B; follow-up allowed for tier-B because the prior touch validated them) or per channel (LinkedIn DMs go to A+B; email cold-pitch only to S+A). The suppression analog doesn't apply — a do-not-contact entry is a legal requirement that should fire regardless of channel/register; a tier gate is operator-tunable prioritization. The cooldown / cross-channel / sending-window / budget precedent applies.

### Alternative 6: `tier:` as a top-level RuleContext field separate from `block_when:` filter

Add the field on `RuleContext` but DON'T extend `_block_when_matches`. Operators who want a tier-scoped budget rule write a tier rule next to the budget rule and rely on rule ordering. **Rejected because:** the cross-cutting filter mechanism already exists; adding `tier:` / `tier_in:` there is ~10 LOC and unlocks tier-scoped variants for every rule class without per-class code changes. The alternative would force operators to write 2 rules where 1 sufficed (a budget cap rule + a tier rule that fires first to block-or-allow the send to even hit the budget cap). The asymmetric cost of NOT shipping the extension is more YAML for operators; the cost of shipping it is 10 LOC the existing cooldown/budget tests don't exercise (and which a new test class pins).

### Alternative 7: Tier inferred from signals, not read from frontmatter

A future Pillar E (discovery quality + lineage) deliverable. **Out of scope** for Week 5. Pillar E will compute `tier` from firmographic + intent signals (per PILLAR-PLAN §2 Pillar E "Tier auto-assignment from signals (firmographic + intent)"). When that lands, `Person.research_tier` is the SoT for what the inference layer computed; `ctx.tier` continues to read from there. This ADR's tier-as-policy-predicate is forward-compatible — the rule doesn't care whether `Person.research_tier` was hand-typed or computed.

### Alternative 8: Wildcard `block_when: {tier: any}` to mean "any non-null tier"

A YAML shortcut for "fire when ctx.tier is set, regardless of value." **Rejected because:** `tier_in:` with the actual set of tiers the operator uses ([S, A, B]) is more explicit and less footgun-prone. Wildcards in `block_when:` would be the second case (after `manual_override.rule` which ADR-0006 §Alternative 7 also rejected wildcards on) where a wildcard would silently expand scope; the principle is "be explicit at write time so the audit trail is unambiguous at refusal time."

### Alternative 9: Make `_block_when_matches` raise on unknown keys

Adding new keys (`tier`, `tier_in`) silently to an unknown-keys-ignored helper means a typo like `block_when: {teir: S}` would silently never match. **Rejected for this commit** — backward-compatibility with existing YAML (any unknown key in `block_when:` is silently ignored across cooldown / budget / sending-window). The cost of strict mode is a breaking change to every existing operator's YAML; the value is catching a single class of typo. A future ADR can land strict mode if the operator demand surfaces. Noted in `_block_when_matches`'s docstring as a known limitation.

### Alternative 10: Per-tier-per-register kill-switch on suppression

Override the suppression rule's no-`block_when:` stance for tier. **Rejected — out of scope.** Suppression's posture is legally and operationally correct: a do-not-contact entry must fire regardless of channel, register, OR tier. The same CAN-SPAM / GDPR reasoning that motivated ADR-0004 §Alternative 8 applies to tier — a tier-A prospect who unsubscribed must still be honored. Operators who want "tier-S overrides suppression" are asking for the wrong thing; they should manage the suppression list, not the policy.

## Consequences

### Positive

- R012 (low-tier cold-pitches) mitigated by design. The `cold-pitch-tier-gate` factory rule ships in `cooldowns.example.yml` (commented-out by default — operator opt-in).
- The `RuleContext.tier` field — anticipated but inert since ADR-0001's design — is now operationally meaningful. Every existing context construction site gains tier automatically because the send-gate populates `tier=draft.person.research_tier` and the field defaults to `None`.
- Cross-cutting `block_when: {tier|tier_in}` unlocks tier-scoped variants for every existing rule class. Per-tier budget caps, per-tier cooldown windows, per-tier sending-window scopes — all expressible without code.
- The simulation surface (`evaluate_all` + CLI) closes the operator's "why did my YAML refuse this?" investigation loop without requiring synthetic-ledger construction.
- The `python -m orchestrator.policy override` surface reduces the W1 incident-response footgun. Audit-trail completeness (rule, expires_ts, reason, approved_by) is enforced by argparse + parse-validation; no hand-crafted JSON.
- The funnel CLI's `--breakdown source,tier,gate_reason` SLO (PILLAR-PLAN §1 I5) is structurally available now that `ctx.tier` is populated and `policy_blocked.policy_detail.tier_value` is serialized.
- Cooldown's DST property test + sending-window's tz-dependence property test both continue to hold (regression sentinels in `tests/test_policy_tier.py`).
- The Pillar A exit criterion's 50-case test matrix gains its consolidation file in `tests/test_policy_matrix.py` — 25–30 representative rows shipped in Week 5; Week 6 finishes the consolidation.

### Negative

- The tier source is hardcoded to `Person.research_tier`. Operators with `priority` (P1/P2/P3) or custom schemes must fork until the deferred `policy.tier_field` config knob ships. **Mitigation:** documented in ADR-0007 §Decision item "Tier field source" + the rule's module docstring; the future enhancement is ~30 LOC.
- `None`-tier handling diverges between the substantive rule (`tier.requires-tier-in`: None → Block) and the cross-cutting filter (`block_when: {tier: S}`: None → filter does not match → rule does not fire). The asymmetry is intentional (§Decision item "None-tier handling") but a future contributor reading the codebase will need to understand it. **Mitigation:** documented in `RuleContext.tier`'s docstring + the rule's module docstring + this ADR's §Decision.
- The `block_when: {tier_in: ...}` filter raises `TypeError` at evaluation time on a scalar input (typo defense). This is a behavior change in `_block_when_matches` from "ignore unknown keys / tolerate any shape" toward strict typing. Existing rule tests pass because none use `tier_in:`; new tier-tier_in tests pin the strictness. **Mitigation:** the type error message tells the operator exactly how to fix (`write 'tier_in: [S, A]' not 'tier_in: S'`).
- The `manual_override` CLI write surface bypasses the doctor preflight check that validates the override schema. **Mitigation:** the CLI's own parse-validation is stricter than doctor's check anyway (doctor validates the on-disk shape; the CLI validates inputs BEFORE constructing the on-disk shape). A future doctor enhancement could surface "any overrides about to expire" as a warning.
- `evaluate_all` walks every rule unconditionally, costing N rule-evaluate calls instead of the production short-circuit's 1 (in the worst case). **Mitigation:** simulation is a one-off operator gesture, not a hot path. N is bounded by the rule list (~10s); each rule evaluate is O(ledger walk in the worst case) which is the same cost the production gate pays. Performance is not the concern here.

### Neutral / observability

- Tier blocks emit the standard `policy_blocked` event (per ADR-0001) with `detail` carrying: `tier_value` (the rejected value, when the tier is known), `tier_unknown: true` (when `ctx.tier is None`), `allowed_tiers` (the rule's configured set), `degenerate: true` (when `allowed_tiers == []`). The funnel CLI surfaces tier refusals as distinct rule categories without new code.
- The cross-cutting `block_when:` extension changes nothing in the verdict shape for rules that don't use the new keys — every existing test passes unchanged.
- The simulate CLI's text output is human-readable by default; `--json` produces a machine-parseable shape for tooling (CI hooks, dashboards). The JSON shape mirrors what `ledger.py funnel --json` already emits for `policy_blocked` events.
- The override CLI's text output names the rule + expiry + scope + reason + approved-by + ts on six lines. `--json` emits the raw event for piping into other tools.

## Compliance with invariants

- **I1 (single source of truth):** Per-deployment tier is `Person.research_tier:` in frontmatter. The new "Per-deployment tier" row in `docs/SOURCES-OF-TRUTH.md` records this — with the future-config-knob caveat that this row will gain a "consumer-configurable source" note when the deferred `policy.tier_field` knob lands.
- **I2 (two-phase commit):** Tier rules consume only `ctx.tier` — no ledger writes, no external side effects. The two-phase guarantee on send is unchanged. The `manual_override` CLI is a single-event append; the override-is-already-incurred-at-write-time semantics from ADR-0006 §I2 carry forward.
- **I3 (schema versioning):** `RuleContext.tier` is an additive optional field (default `None`). The `manual_override` event carries `v: 1` per ADR-0006. No on-disk migration needed; existing notes without `research_tier:` parse identically (the field defaults to `None` in `vault.PersonInfo`).
- **I5 (observable by default):** Every tier Block emits `policy_blocked` with the diagnostic shape above. Tier appears as a breakdown axis in the funnel CLI without per-skill changes.
- **I6 (tests prove invariants):** `tests/test_policy_tier.py` covers the rule class's allow/block branches, None-tier handling, empty-allowed-tiers degenerate case, `block_when:` scoping, case-sensitivity, and the cross-cutting filter (proving every existing rule class scopes by tier without per-class code). `tests/test_policy_matrix.py` ships with 25-30 rows from across the rule classes (ADR-0003 CC-01..CC-12 + cooldown / suppression / sending-window / budget / tier seeds). `tests/test_policy_engine.py::TestEvaluateAll` pins the non-short-circuit shape + exception propagation parity with `evaluate`. `TestCooldownDSTPropertyStillHolds` + `TestSendingWindowTzDependenceStillHolds` regression sentinels still pass after Week 5.
- **I7 (cost is first-class):** Tier rules do not emit cost events (they're pure-read gating). The budget rules' cost-event emission is unchanged. The `manual_override` CLI's write goes through `Ledger.append`, the same path the budget rule already consumes.
- **I8 (decisions documented):** This ADR. ADR-0006 §References is updated to point forward to ADR-0007. `docs/adr/README.md` gains the ADR-0007 row.

Does not weaken any invariant. The "Per-deployment tier" SoT row adds an explicit registry entry where one was missing.

## Migration / rollout

Greenfield: `orchestrator/policy/tier.py` is a new file; `orchestrator/policy/__main__.py` is a new file; `RuleContext.tier` is an additive optional field (default `None`); `_block_when_matches`'s new keys are silently ignored by rules that don't use them.

The factory `cooldowns.example.yml` is extended with one commented-out tier rule (`cold-pitch-tier-gate`) and one commented-out tier-scoped budget rule (demonstrating the cross-cutting filter). Operators opt in by uncommenting; until they do, the rules are not in the active rule list and never fire.

`docs/PILLAR-PLAN.md` §2 Pillar A's package list is updated in the same commit: `tier.py` is removed from the outstanding-modules list. `simulation.py` remains outstanding (Week 6, when standalone what-if features land).

Doctor preflight already validates `cooldowns.yml` structure at install time; once the example file gains tier rules (commented-out), preflight covers their structural validity automatically when an operator uncomments.

The `tier` field on `RuleContext` does NOT trigger a migration. Existing Person notes parse the same as before: `vault.load_person` returns `research_tier=None` when the field is absent; the gate populates `ctx.tier=None`; rules that don't scope on tier ignore it; the substantive `tier.requires-tier-in` rule (only active if uncommented) refuses on `None` with a structured detail.

`evaluate_all` is a new public symbol on `orchestrator.policy.engine` — additive, no migration. The CLI is invoked via `python -m orchestrator.policy`; the entry point lives at `orchestrator/policy/__main__.py` per the standard Python convention.

`python -m orchestrator.policy override ...` writes the same `manual_override` event shape ADR-0006 locked. Existing overrides written via `ledger.py append @event.json` continue to be honored; the CLI is a new producer for the same schema.

## References

- ADR-0001 (policy engine architecture) — engine surface; §Alternative 4 anticipated `evaluate_all` for simulation mode.
- ADR-0002 (cooldown rules + recipient timezone) — `block_when:` semantics; `RequiresPersonStatusRule` None-handling precedent (Block on unknown).
- ADR-0003 (channel as first-class policy predicate) — CC-01..CC-12 matrix that this ADR's `tests/test_policy_matrix.py` consolidates.
- ADR-0004 (suppression rules + GDPR forget) — the deliberate non-`block_when:` posture there contrasts with this ADR's deliberate-yes (§Alternative 5).
- ADR-0005 (sending-window rules + recipient timezone inference) — additive-context-field precedent (`country` on `IdentityKeys`); `_block_when_matches` shared helper.
- ADR-0006 (budget rules + `cost_incurred` event) — `manual_override` event schema; the override CLI in this ADR writes that schema. ADR-0007 §References-from-0006 should be updated in the same commit to link forward.
- `docs/PILLAR-PLAN.md` §1 I5 (funnel breakdown SLO) — the binding requirement that `ctx.tier` be populated. §2 Pillar A Week 5 — the package-list update.
- `docs/RISK-REGISTER.md` — risk this ADR mitigates: R012 (low-tier cold-pitches damage reply-rate signal). Adjacent: R009 (off-hours sends), R011 (cross-channel double-engagement).
- `docs/SOURCES-OF-TRUTH.md` — the new "Per-deployment tier" row.
- `orchestrator/policy/tier.py` — the `TierRequiresTierInRule` class.
- `orchestrator/policy/_helpers.py` — `_block_when_matches` extended with `tier:` and `tier_in:` keys.
- `orchestrator/policy/engine.py` — `evaluate_all` added.
- `orchestrator/policy/__main__.py` — simulate + override CLI surface.
- `orchestrator/policy/types.py` — `RuleContext.tier` field added.
- `skills/send-outreach/scripts/send_queued.py:_build_rule_context` — populates `ctx.tier=draft.person.research_tier`.
- `tests/test_policy_tier.py` — rule-class tests + cross-cutting filter tests + invariants.
- `tests/test_policy_engine.py::TestEvaluateAll` — non-short-circuit shape + exception propagation.
- `tests/test_policy_matrix.py` — 25–30-row consolidation; Pillar A exit-criterion vehicle.
- `tests/test_send_gate.py::TestTierEmission` — end-to-end `ctx.tier` population from Person frontmatter.
- Followups: Pillar E (auto-assignment of tier from signals); future ADR for `policy.tier_field` config knob if/when an operator needs a non-`research_tier` source; Week 6 finishes the matrix consolidation + lands standalone `simulation.py` if what-if features become real.
- Forward reference: **ADR-0008 (LinkedIn weekly invite cap migration)** — Week 6 closes the "zero hardcoded policy in skills" Pillar A exit criterion by migrating `LINKEDIN_WEEKLY_SOFT_LIMIT` from `send_queued.py` to a `budget.window-cap` factory rule; the cross-cutting `block_when: {channel: linkedin}` filter this ADR established is what scopes ADR-0008's new rule to LinkedIn sends.
