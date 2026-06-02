# ADR-0021: Per-channel policy migrations — LinkedIn weekly DM cap (Pillar C Week 8)

- **Status:** Accepted
- **Date:** 2026-05-22
- **Pillar:** C (Multi-channel coherence — Week 8's per-channel policy migration; second of Weeks 7-11)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0020 (Week 7) shipped the first per-channel policy migration — `policy/0002_add_li_invite_weekly_cap` — and established the convention each subsequent per-channel cap migration follows. D72-D78 cover the structural decisions (ID convention, APPEND insertion, rule-name idempotence, content-additive-no-version-bump, existing-operator seed taxonomy, downstream pillar impact); Weeks 8-11 inherit them without re-deciding.

What Week 8 adds is the next concrete migration in the Week 7-11 trajectory: `policy/0003_add_li_dm_weekly_cap`. The structural shape is identical to Week 7's modulo three rule-shape parameters — channel filter, source value, max_units default. ADR-0021 records only the decisions that are LinkedIn-DM-specific (or are inheritances worth pinning explicitly so a future contributor reading just this ADR can ship correctly without first reading ADR-0020).

ADR-0016 (Pillar C Week 3) is the prerequisite ADR establishing the dispatcher whose emissions this rule consumes. ADR-0016 D43 names `source="linkedin_dm"` as the LinkedIn DM dispatcher's `cost_incurred` emission shape — the canonical source-filter value from day one of LinkedIn DM dispatch. ADR-0015 D40's split-source convention separates `linkedin_invite` from `linkedin_dm` so operators can configure per-action caps; Week 7 activated the invite cap; Week 8 activates the DM cap.

The five concerns Week 8 resolves:

1. **`max_units:` default — LinkedIn does NOT publish a DM-specific soft cap.** Where ADR-0008's 100/week is the well-known invite cap value (LinkedIn's own public guidance), there is no equivalent published number for DMs. The asymmetric-failure-cost calculus per PILLAR-PLAN §0 biases toward a conservative default; D79 pins 50.
2. **Factory template Rule 12c — whether to ship a commented documentation example.** Week 7 updated Rule 12b's `source:` field but did not add a NEW factory rule. Week 8 has the choice: ship a commented Rule 12c mirroring Rule 12b's shape, OR skip the factory update because the migration writes operator-installed files regardless. D80 pins YES.
3. **Stale-source detection — whether to mirror Week 7's WARNING log path.** Week 7's policy/0002 detects `linkedin-weekly-invite-cap` rules with `source: linkedin` (the pre-Pillar-C-Week-2 factory shape) + warns at WARNING level per ADR-0020 §D77 Shape 1. Week 8 asks whether an analogous staleness path applies. D81 pins NO.
4. **Existing-operator seed — which of ADR-0020 §D77's three shapes apply.** The DM dispatcher shipped after the split-source convention; Shape 1 (canonical name with stale source) has no historical precedent. D82 pins the subset that applies.
5. **Downstream pillar impact — adapted from ADR-0020 D78.** The Week 8 rule has the same shape Pillar D / E / F / G / H / I / J query/observe as Week 7's. D83 names the LinkedIn-DM-specific adaptations.

Risks this ADR mitigates by design: **R-account-throttle-on-DM-volume** — operators with LinkedIn DM dispatchers can over-quota themselves silently (the MCP's `send_message` returns success even when LinkedIn's account-level enforcement starts shadowbanning recipient notifications; the failure mode surfaces as a slow rate of replies, not an immediate refusal). The per-channel DM cap closes the gap by refusing further sends before the account-level enforcement kicks in.

## Decision

### D79. `max_units: 50` — conservative half-of-invite default

The factory-shipped + migration-written `linkedin-weekly-dm-cap` rule's `max_units:` is **50** (50 DMs per 7 days per LinkedIn account).

**Why 50:**

- **No published soft cap.** LinkedIn's documentation on DMs (`/help/linkedin/answer/a523218`, `/help/linkedin/answer/a531213`) names neither a numeric weekly cap NOR a daily cap on DMs to existing connections. The 100/week INVITE cap from ADR-0008 is the only published soft-cap value LinkedIn shares; DMs operate under "be reasonable" guidance that the account-level enforcement (shadowbanning, suspension) silently enforces. The asymmetric-failure-cost calculus per PILLAR-PLAN §0 biases toward a low default.

- **Asymmetric failure modes.**
  - **False-block (cap too low + operator hits it before account-level enforcement would):** one-line YAML edit raises the cap. Operator-time cost ~30 seconds.
  - **False-allow (cap too high + account-level enforcement triggers):** LinkedIn shadowbans recipient notifications (Pillar D's reply joiner observes a sudden rate-of-replies drop weeks later) OR LinkedIn suspends the account (multi-week recovery; outreach surface lost). Operator-time cost: days-to-weeks + reputational damage with the recipients whose threads now dangle.
  - The cost ratio is at least 1000x asymmetric; the default biases hard toward refuse.

- **Half-of-invite shape.** 50 is half of ADR-0008's 100/week invite cap. The relationship is not load-bearing (invite-to-DM ratio isn't fundamental), but it provides a defensible round number that operators understand vs. an arbitrary "75" or "63." The half-of-invite shape also tracks reported operator anecdote that DM throttling triggers tighter than invite throttling (DM recipients have higher friction-to-report-spam than invite recipients).

- **Operator-tunability.** Operators with established sender reputations + Sales Navigator accounts plausibly tune up (operators in the 80-100 range with prior history). Operators in the warm-up phase plausibly tune down (operators in the 10-25 range building reputation). The factory's 50 covers the median use case; the rule's `name:` is the load-bearing identifier (D74 idempotence) so operator tuning is preserved through subsequent re-applies.

- **Doctor preflight (Pillar I) is the natural future home for tuning advice.** A future Pillar I doctor preflight pass may inspect the operator's actual `cost_incurred.source=linkedin_dm` history + suggest a tuned cap based on observed volume. Until then, 50 is the safe-by-default starting point.

**Rejected D79 alternatives:**

- **`max_units: 100` — mirror the invite cap value.** **Rejected** because:
  - The relationship "DM ≈ invite" is not load-bearing for the cap value. LinkedIn enforces DM volume separately from invite volume (operators report being throttled on DMs while invites still flow, and vice versa); using the invite cap value as a default would assume an equivalence the platform doesn't observe.
  - 100/week DM volume in the absence of a published cap is plausibly above the silent enforcement threshold for operators without established sender reputations. The asymmetric-failure-cost calculus disfavors the higher default.
  - Operator anecdote (community-aggregated, not authoritative) consistently reports DM-driven throttling at lower volumes than invite-driven throttling. A factory default at 100 would surface the failure mode for typical operators; a factory default at 50 stays under the typical enforcement threshold.

- **`max_units: 25` — extremely conservative for warm-up operators.** **Rejected** because:
  - 25/week is plausibly below the operator's actual safe-quota — it forces every operator to tune up on first ramp-up, which is friction without protection (the operator runs into the cap on their second day of normal operation + has to edit YAML to proceed).
  - The factory default's job is to be safe for the median operator, not the most-conservative one. 25 is the right number for new operators with no LinkedIn history; the migration would surface the recommendation in commit notes / Pillar I doctor as "consider tuning down for warm-up." But the factory default for an established operator with normal DM cadence should not be the warm-up value.
  - A more-restrictive default would make operators less likely to keep the rule active (rather than disable / remove it), which is the opposite of the migration's purpose.

- **No factory default — operator MUST set `max_units:` explicitly before the rule activates.** **Rejected** because:
  - Defeats the purpose of the migration. The whole point of policy/0003 is to give operators a working cap without requiring them to research + decide a number; a "must-set-before-active" rule is what ADR-0008's pre-Week-7 factory-comment approach already provided.
  - The engine's policy YAML schema does not currently support "rule with no `max_units:` is no-op." Adding the semantics would require an engine code change (per ADR-0020 D75 — schema-changing — which would bump version + extend SUPPORTED set). Scope creep against the content-additive migration shape.
  - Operators who want this behavior can comment-out the migrated rule + uncomment manually after setting their value. Operator-deliberate; not a default-shape problem.

- **`max_units: 75` — arithmetic mean of conservative (25) and aggressive (100-150).** **Rejected** because:
  - Arithmetic-mean shapes are unmotivated by the underlying failure mode. The relevant question is "what number stays below LinkedIn's silent enforcement threshold for the median operator?" — not "what number balances two arbitrary bounds?"
  - 75/week DMs is plausibly above the silent enforcement threshold for warm-up operators (per the anecdotal DM-vs-invite ratio). The factory default's safety guarantee should hold for the lower-reputation operator, not the median.

### D80. Ship factory-template Rule 12c — commented LinkedIn DM cap example mirroring Rule 12b

The Week 8 commit adds a commented `Rule 12c` block to `config-template/cooldowns.example.yml`. The block mirrors Rule 12b's shape (LinkedIn invite cap) modulo channel filter / source / max_units / reason; it ships BETWEEN Rule 12b and Rule 13 (the tier-scoped budget cap example) — the next slot in the file's existing ordering.

**Why ship Rule 12c:**

- **Per-channel symmetry.** Pillar C's structural identity is "every channel gets full primitive coverage." The factory template's documentation should reflect this — operators reading the file should see one example per channel-action combination Pillar C delivers. Skipping Rule 12c would leave operators reading "Rule 12b: LinkedIn invite cap" + wondering "is there a LinkedIn DM cap too? where is it documented?" The mirror closes the documentation gap.

- **New-operator onboarding.** Operators copying `cooldowns.example.yml` to `~/.outreach-factory/policies/cooldowns.yml` get the commented Rule 12c as documentation in their installed file. When they later run `runner.apply(MigrationCategory.POLICY)`, the migration's APPEND semantics (D73 inherited from ADR-0020) drops the active rule AFTER the existing rule list — the operator's commented Rule 12c remains as documentation alongside the migration-installed active rule. The two coexist legibly.

- **Operator-tuning template.** Operators who want to start with a different `max_units:` value (e.g. 25 for warm-up) can uncomment Rule 12c BEFORE running the migration + set their value. The migration's name-match idempotence (D74) then skips the file because the operator's rule shares the canonical name. The factory comment is the on-ramp for operator-deliberate tuning at install time.

- **Identical maintenance cost to skipping.** Adding Rule 12c is ~25 lines of comment + YAML in the factory file. Skipping has zero file-edit cost but creates an asymmetric file (every other channel-action gets a documented example; DMs don't). The cost-benefit clearly favors shipping.

**Rejected D80 alternatives:**

- **Skip Rule 12c — let the migration's writeback be the operator's first exposure.** **Rejected** because:
  - Operators inspecting the factory file before running migrations see Rule 12b for invites but nothing for DMs — surface asymmetry the per-channel migration sequence should not introduce.
  - The Pillar I doctor preflight (future) will plausibly grep the factory file for canonical rule names; an absent canonical name forces a special-case "Pillar C Week 8's rule has no factory example" branch in the doctor. Shipping the example keeps the doctor's grep uniform.
  - Operators who run the migration without first reading the factory get no documentation of the rule they just installed — they have to consult ADR-0020 / 0021 to understand the shape, which is friction. The factory comment is the canonical operator-readable explanation.

- **Ship Rule 12c but with `max_units:` left as `<TUNE_ME>` placeholder.** **Rejected** because:
  - Placeholders break the YAML — a commented-out rule with `max_units: <TUNE_ME>` is not parseable if the operator uncomments without first replacing the placeholder. Operator-deliberate friction at the wrong layer (the operator has to know to replace the placeholder; YAML's parse error if they don't is opaque).
  - The factory's job is to ship a working default. Placeholders push the "what's the right value?" question to every operator individually, when the migration's actual purpose is to ship a safe default + let operators tune. D79's 50 is the safe default; Rule 12c documents it.

- **Ship Rule 12c using `max_units: 100` to mirror Rule 12b's invite cap.** **Rejected** because:
  - The factory documentation must match the migration's actual writeback. If Rule 12c shows `max_units: 100` but the migration writes `max_units: 50`, operators reading both surfaces see contradictory recommendations — confusing + a maintenance hazard.
  - Per D79's analysis, 100 is the wrong default for DMs; documenting it in Rule 12c would be a misdirection.

### D81. NO stale-source detection — unlike Week 7's policy/0002 WARNING path

The Week 8 migration's `upgrade()` does NOT emit a WARNING log when the canonical `linkedin-weekly-dm-cap` rule is already present with a non-canonical `source:` value. The migration's idempotence check (D74 inherited from ADR-0020) skips the file when the canonical name is present — it does NOT inspect the rule's other fields to surface staleness.

This is a deliberate divergence from Week 7's policy/0002, which DOES emit a WARNING when the canonical `linkedin-weekly-invite-cap` rule is present with `source: linkedin` (per ADR-0020 §D77 Shape 1 — the pre-Pillar-C-Week-2 ADR-0008 factory shape that pre-dates ADR-0015 D40's split-source convention).

**Why no stale-source path for Week 8:**

- **No historical precedent.** LinkedIn DM dispatcher (ADR-0016) shipped 2026-05-21 — AFTER ADR-0015 D40's split-source convention (Week 2). There has never been a factory-shipped `linkedin-weekly-dm-cap` rule with a stale `source: linkedin` value for operators to have copied. ADR-0008's factory comment was invite-specific; no DM equivalent ever existed in a stale shape.

- **Operator-hand-written rules are operator-deliberate.** If an operator hand-wrote a `linkedin-weekly-dm-cap` rule with `source: linkedin` (deviating from the canonical `source: linkedin_dm`), the divergence is operator-deliberate — perhaps they're testing pre-Pillar-C behavior, perhaps they're using a custom dispatcher emitting `source="linkedin"`. The migration should not nag.

- **Asymmetric stale-source posture across the policy/0002-0006 range.** Per ADR-0020 §D77, Shape 1 (stale source) applies only to the invite rule because the factory file ships only the invite rule's commented form with the historical `source: linkedin` value. Shapes 2 + 3 (canonical correct, or renamed) apply to every per-channel migration uniformly. ADR-0021 §D82 catalogs which shapes apply to Week 8 explicitly.

- **A future Pillar I doctor preflight is the home for misconfig detection.** The Pillar I OSS bring-up will ship a `python -m orchestrator.policy doctor` command that inspects every active policy rule for canonical-shape conformance + warns on per-rule deviations (wrong source value, wrong channel value, wrong scope, etc.). That command is the principled home for per-rule misconfig surfacing; the per-migration WARNING path in policy/0002 is a one-off accommodation for the specific Shape 1 case. Week 8 does not introduce a parallel one-off for a shape that does not exist.

**Rejected D81 alternatives:**

- **Mirror Week 7's WARNING path: warn on any non-canonical `source:` value when the canonical name is present.** **Rejected** because:
  - Pillar I's doctor is the correct surface for general misconfig detection. A per-migration WARNING for every conceivable deviation pollutes the runner's apply logs + duplicates effort that Pillar I will land cleanly.
  - The Shape 1 case (a specific historical mistake from a specific factory shape) is fundamentally different from "operator's rule has the wrong source" — the former is a known-population state with a known operator base; the latter is an open-ended class. Treating them the same conflates remediation paths.
  - The Week 7 WARNING path was a per-week-review finding (P2-B) addressing a specific known operator base. Week 8 has no known operator base for a stale shape; the conditions that motivated Week 7's accommodation don't apply.

- **Add a "any-source-warning" toggle to the migration's context.** **Rejected** because:
  - The toggle would be operator-configuration for a behavior nobody has asked for. Scope creep against the migration's content-additive shape.
  - Operators who want per-rule misconfig detection get Pillar I's doctor — building it twice (once per-migration, once Pillar-I-doctor) is the wrong layering.

- **Emit an INFO log noting the operator's source value when skipping, without a WARNING.** **Rejected** because:
  - INFO logs are noise in the runner's normal apply path. The migration logs at INFO level summarizing "added rule to N file(s) (M already present)" — adding per-file detail noise pollutes the operator-facing log.
  - Operators wanting per-rule visibility get the dry-run preview or Pillar I doctor; the apply path's logging should stay summary-level.

### D82. Existing-operator seed — which ADR-0020 §D77 shapes apply to Week 8

ADR-0020 §D77 catalogs three pre-migration operator shapes for the LinkedIn invite cap (Week 7). For LinkedIn DMs (Week 8), the operator shapes are:

1. **Shape 1 (canonical name, stale source) — DOES NOT APPLY.** Per D81's analysis: there is no historical factory-shipped LinkedIn DM cap rule; no operator could have copied a stale `source: linkedin` (or any other non-canonical value) from a factory shape that never existed. Operators with hand-written non-canonical-source rules are operator-deliberate per D81; the migration is silent.

2. **Shape 2 (canonical name, correct source `linkedin_dm`) — applies.** Operators who hand-wrote the rule before Week 8 (anticipating the migration, or installed it via copy-paste from the Week 7 commit's ADR-0020 forward-references) have the rule with the canonical source. The migration's name-match idempotence skips. **Operator remediation:** none needed.

3. **Shape 3 (renamed) — applies.** Operators who wrote their own LinkedIn DM cap rule with a different name (e.g. `linkedin-dm-cap-50` or `my-dm-throttle`) have a rule that delivers the same enforcement under a different name. The migration's name-match (canonical-name only) treats it as "not present" + adds the canonical-named version alongside. The operator now has TWO rules with overlapping enforcement. **Operator remediation:** delete one of the two rules. (The canonical version is operator-acceptable to delete — it's the migration's default; the operator's renamed version preserves their tuning. Or vice versa — operator's choice.) Same posture as Week 7's Shape 3 + the same doctor preflight (Pillar I) is the natural future warning surface.

The factory file's `cooldowns.example.yml` ships the commented Rule 12c (per D80) — new operators copying the factory get the canonical shape with `source: linkedin_dm` from day one. There is no pre-Week-8 factory shape they could have stale-copied (Shape 1's non-applicability).

**Rejected D82 alternatives:**

- **Catalog Shape 1 anyway with a hypothetical "what-if-LinkedIn-changes-DM-API-emit-shape" path.** **Rejected** because:
  - ADR-0021 is recording the state of the world today, not speculating on future LinkedIn API changes. The migration's `source: linkedin_dm` matches the Pillar C Week 3 dispatcher's emit value (ADR-0016 D43); if LinkedIn changes the underlying API shape, the dispatcher updates first + the rule's source value follows.
  - Hypothetical future-state Shape 1 would be confusing in the operator-facing rollout text (operators reading the ADR look for actionable advice; speculative scenarios dilute it).

- **Use a tag system (e.g. ADR-0021 references ADR-0020 §D77 by tag instead of restating).** **Rejected** because:
  - ADR-0021 is read independently of ADR-0020 — operators looking up "what does Week 8 do?" should get a self-contained answer. Cross-references force readers to chase a chain of ADRs that erodes the ADR-per-decision discipline.
  - The restatement is short (3 shapes × ~2 sentences each) — not a maintenance burden.

- **Defer existing-operator seed entirely to Pillar I doctor.** **Rejected** because:
  - Pillar I is 35+ weeks out (per PILLAR-PLAN §6 timing). The migration ships now; operator-facing rollout documentation must be in this ADR.
  - The Pillar I doctor is the future automated-detect surface; the ADR is the current operator-readable explanation. Both are needed; deferring one to the other creates documentation gaps.

### D83. Downstream pillar impact

Per the ADR-0009 convention (every Pillar B + C ADR explicitly names cross-pillar impact); identical posture to ADR-0020 D78 modulo the LinkedIn-DM-specific adaptations.

* **Pillar D (reply + conversation handling).** Reply classifiers may need DM-specific per-channel policy rules (e.g. "if `linkedin_dm` reply received in last 14d, suppress further DM sends in the same thread"). Pillar D authors follow the same `policy/000N_add_<channel>_<rule-class>_<scope>.py` pattern; the `_policy_io.add_rule_block_text` primitive (landed Week 7) composes. Pillar D's reply joiner correlates `li_dm_reply_received` events (per ADR-0025 D96's per-channel-prefixed naming convention; supersedes the generic `reply_received` placeholder this paragraph used pre-ADR-0025) to their originating `li_dm_confirmed` by `intent_id` + `linkedin_thread_id` per ADR-0016 D43; the cap rule's enforcement at send-time doesn't affect this surface.

* **Pillar E (discovery quality + lineage).** No direct interaction. Discovery doesn't emit `cost_incurred` with `source="linkedin_dm"` — that source is reserved for the LinkedIn DM dispatcher's per-send cost emission. Pillar E may add its own `BudgetWindowCapRule` instances filtering by discovery-source values (`source: pdl`, `source: apollo`); the per-channel migration shape composes.

* **Pillar F (voice corpus + draft quality).** Voice-fidelity-scoped policy rules (e.g. "block DM sends whose voice-fidelity score is below X") may need new rule classes. The Week 8 rule does not interact; voice rules are register-and-channel scoped via `block_when:`, not directly composed with the per-channel cap.

* **Pillar G (observability).** OTel + Prometheus will emit per-rule metrics; the `linkedin-weekly-dm-cap` rule produces `policy_blocked` events with `rule: "linkedin-weekly-dm-cap"` + `channel: linkedin` (per ADR-0014 D33's channel-on-every-event invariant). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=linkedin-weekly-dm-cap` without new code (per ADR-0001). Pillar G's dashboards group by `rule:` field — the per-channel cap rules surface as distinct rows in the per-rule firing-rate dashboard.

* **Pillar H (daemon + scheduled jobs).** Pre-API-call gating (per ADR-0006 §"Where budget rules fire") may consume the same per-channel rule at additional gates. The daemon's bulk-send workflow per-Person threading may want a per-channel BudgetWindowCapRule instance evaluated AT JOB-DISPATCH time (vs. AT SEND time) — Pillar H's job-dispatch layer composes with the existing rule via the same RULE_REGISTRY. No engine change.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant policy directories; each tenant's `cooldowns.yml` gets the Weeks 7-11 migrations independently. The doctor's refuse-on-pending applies uniformly. The CLI's `python -m orchestrator.migrations apply` lands here (deferred from ADR-0012 D20). Pillar I doctor preflight: the §"Existing-operator seed" Shape 3 (renamed + dual-rule transitional state) is the natural detect surface — the doctor scans operator policy files for rules with overlapping `source:` + `block_when.channel:` + `type:` and warns when more than one rule fires on the same event class.

* **Pillar J (security + compliance).** GDPR-forget on a policy file doesn't typically apply (rules don't contain PII). A policy migration that removes a deprecated rule class is structurally reversible — `is_reversible=True` carries. Per-tenant rule deletion as part of an account-forget operation is a Pillar I + J intersection — neither week 7 nor 8 ships it.

**Rejected D83 alternatives:**

- **Defer downstream pillar impact to the consolidated Pillar I doctor.** **Rejected** because:
  - Every ADR since 0014 has named cross-pillar impact explicitly (per the ADR-0009 convention). Skipping for Week 8 would break the precedent + force a future reader to reconstruct the impact from absent context.
  - Cross-pillar impact is structurally near-identical to ADR-0020 D78 — restating it explicitly takes minimal space; the value to readers exceeds the cost.

- **Mark cross-pillar impact identical to ADR-0020 D78 by reference, no restatement.** **Rejected** because:
  - The DM-specific adaptations (Pillar D's reply joiner correlator detail; Pillar H's job-dispatch layer composition) are not identical to the invite version. Restating with adaptations forces the explicit per-channel-correctness check.
  - ADRs should be self-contained per the §D82 rationale.

- **Add a new Pillar K (compliance audit) row anticipating future regulatory needs.** **Rejected** because:
  - PILLAR-PLAN does not include a Pillar K; introducing one in a Week 8 ADR is scope creep beyond the migration. Future ADRs covering compliance shapes belong in their own ADR sequence.

## Alternatives considered

### Alternative 1: Skip Week 8 + bundle DM cap into Week 11's cross-channel migration

Defer the LinkedIn DM cap to Week 11 (the cross-channel cooldown week) — bundle the per-channel + cross-channel rules in one mega-migration. **Rejected** because:

- Per ADR-0020 Alternative 3 (rejected): per-week shipping discipline is the project's load-bearing process. A bundled migration would be a single 5-week commit that's hard to review per-section.
- The cross-channel cooldown rule (Week 11) has a DIFFERENT shape than per-channel caps (it uses `CrossChannelTouchRule` per ADR-0003, not `BudgetWindowCapRule`). Bundling them conflates rule classes — fixing one would force the other into the same commit's review window unnecessarily.
- Operators with LinkedIn DM dispatchers (Week 3) shipped 2026-05-21 — operators on the Week 3 commit + before Week 11 have months of unprotected DM sends. The per-week shipping discipline minimizes the unprotected window per channel.

### Alternative 2: Per-Person DM cap (`budget.per-person-cap` filter, not `budget.window-cap`)

Use the `BudgetPerPersonCapRule` shape (ADR-0006) — "max N DMs per Person per lifetime" — instead of the window-cap shape. **Rejected** because:

- The failure mode the rule mitigates is account-level throttling, which is aggregated across all recipients. A per-Person cap doesn't constrain account-level volume; an operator could be at 1 DM per Person but 200 DMs/week total + still trigger account-level enforcement.
- Per-Person caps belong in a separate rule (e.g. `linkedin-dm-cooldown-per-person`) addressing a different failure mode (recipient-side spam-flag aggregation). Conflating the two rule shapes muddies the policy file's per-rule purpose.
- The factory can ship BOTH a per-Person cooldown AND a window cap — they're complementary. Week 8 ships the window cap; the per-Person cooldown for DMs is a future ADR if the use case surfaces.

### Alternative 3: Reuse Week 7's policy/0002 — drop in `linkedin_dm` rule into the same migration

Add the LinkedIn DM cap rule as a second `RULE_BLOCK_TEXT` inside Week 7's policy/0002 migration; rename to `0002_add_li_invite_and_dm_caps`. **Rejected** because:

- Per ADR-0020 Alternative 3 (mega-migration alt) + ADR-0009 D2 (sequential ID convention): each migration is independently reversible at the migration level. An operator who wants to roll back just the DM cap while keeping the invite cap needs them as separate migrations.
- The migration was already shipped (commit `65f817f`); modifying it post-ship breaks the framework's append-only migration discipline (per ADR-0009 D4 + D7).
- Future per-channel migrations (Twitter DM, calendar booking, cross-channel cooldown) each ship as their own migration — bundling Week 8 with Week 7 would have to also bundle every future per-channel cap, defeating the per-week cadence.

### Alternative 4: Migration also emits a `migration_event` to record the per-channel-cap activation

Per ADR-0010 D17 / ADR-0020 Alternative 4 (rejected): migrations could emit a `migration_event` audit-trail event. **Rejected** by inheritance from ADR-0020:

- Policy migrations are explicitly ledger-silent per ADR-0012 I5. Week 8 inherits the posture.
- Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories.

### Alternative 5: Migration writes a `linkedin-weekly-dm-cap` rule with both `source: linkedin_invite` AND `source: linkedin_dm` (a "linkedin-combined-cap" entry)

Construct a single rule that aggregates invites + DMs into one weekly cap (e.g. 150/week total). **Rejected** because:

- The `BudgetWindowCapRule` (ADR-0006) accepts a SINGLE `source:` value per instance; aggregating multiple sources would require a new rule class (e.g. `BudgetWindowMultiSourceCap`). Schema change → bump version → coordinate engine update → scope creep against content-additive migration.
- Per ADR-0015 D40's split-source convention: operators want per-action visibility on caps. Aggregating sources hides the per-action breakdown in the `policy_blocked` event stream (Pillar G's per-rule dashboard would surface a single "linkedin-combined-cap" row instead of two).
- Operators who want a combined cap can write a second rule with a future glob-source extension (e.g. `source: linkedin_*` — Pillar A's hypothetical future extension). Week 8 doesn't need to ship the combined shape; the per-action split is the canonical pattern.

## Consequences

### Positive

- **Operators using LinkedIn DM dispatcher (Week 3 onward) get DM-volume protection automatically** when they run the next batch of pending migrations. The 50/week default is a safe starting point for the median operator; operators tune via the one-line YAML edit per D74's name-match idempotence preserves tuning.
- **The migration is content-additive, not schema-changing** (D75/D76 inherited from ADR-0020). Files stay at their pre-migration version; the engine's SUPPORTED set is unchanged; no flag-day risk.
- **Per-channel symmetry of the factory template** — Rule 12c documents the LinkedIn DM cap shape alongside Rule 12b (invite cap). New operators reading the factory file see one example per channel-action combination.
- **Future per-channel migrations (Weeks 9-11) inherit the pattern cleanly.** ADR-0021's D79-D83 are derivative of ADR-0020's D72-D78; Week 9's Twitter DM cap ADR-0022 will be derivative of ADR-0021's D79-D83 modulo the Twitter-specific cap value + Twitter dispatcher's emit shape.

### Negative

- **Operators with established LinkedIn sender reputations who actually need a higher cap (e.g. 80-100/week) will hit the 50 default + need to tune up.** The tuning is a one-line YAML edit, but it's friction the operator only discovers when the cap fires for the first time. Documented in §D79 + the migration's notes; doctor preflight (Pillar I) could plausibly observe the operator's actual `cost_incurred.source=linkedin_dm` volume + suggest a tuned value in a future iteration.
- **The Shape 3 (renamed) transitional state** requires operator action to deduplicate when the migration adds the canonical-named rule alongside the operator's renamed version. Same posture as Week 7; documented in §D82.
- **The factory `cooldowns.example.yml` grows by ~25 lines** for Rule 12c — small but real. Operators tracking the factory across versions via git see a new commented block. Acceptable cost for the per-channel-symmetry benefit.

### Neutral / observability

- The migration logs at INFO with `affected_count` + `already_present` counts. The runner's pending / dry-run / apply reports surface the migration ID + description as expected.
- Policy migrations remain ledger-silent (no `migration_event` events) per ADR-0012 I5; Pillar G is the future home for per-migration metrics on non-ledger categories.
- The rule's `policy_blocked` event shape is unchanged from existing budget-window-cap rules (per ADR-0006 §"Budget blocks emit the standard `policy_blocked` event"). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=linkedin-weekly-dm-cap` without new code.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAML remains the SoT for "what rules are active" (per `docs/SOURCES-OF-TRUTH.md`). The migration writes to that SoT — no competing source.
- **I2 (two-phase commit):** Not applicable — policy migrations are internal state evolution, not external side effects. Per-file atomicity (tmp-then-rename + fsync via `write_policy_file_atomic`) is the migration-framework analog. Same posture as ADR-0011 + ADR-0012 + ADR-0020.
- **I3 (schema versioning):** The migration does NOT bump the file's `version:` field (D75 inherited from ADR-0020 — content-additive migrations don't bump). The engine's `SUPPORTED_POLICY_SCHEMA_VERSIONS` remains `frozenset({1, 2})` — no extension required.
- **I5 (observable by default):** Every apply + downgrade logs at INFO with `affected_count` + already-present counts. Doctor's WARN-on-pending surfaces the migration ID. Per-channel cap firings emit standard `policy_blocked` events with `rule: "linkedin-weekly-dm-cap"` + `channel: linkedin`.
- **I6 (tests prove invariants):** `tests/test_migrations_policy_0003.py` (53 tests) covers surface compliance, apply / dry-run / downgrade paths, idempotence (canonical-name + operator-renamed + already-present), refuse-loud on every failure mode, runner integration, engine integration (the rule loads + instantiates as `BudgetWindowCapRule`), round-trip byte-identical on the real factory template, coexistence with Week 7's invite cap rule, and the NO-stale-source-warning invariant per D81.
- **I7 (cost is a first-class concern):** Policy migrations do not emit `cost_incurred` events. The migration's rule, once active, consumes `cost_incurred` events with `source="linkedin_dm"` per ADR-0006's existing contract.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains the ADR-0021 row. `docs/PILLAR-PLAN.md` §6 Pillar C row extends to "Week 8 ✓."

Does not weaken any invariant. The migration is structurally additive: a new rule entry under existing shapes, leveraging existing rule classes, with existing event schemas.

## Existing-operator seed

Per §D82 above, ADR-0020's three §D77 operator shapes reduce to two for Week 8:

- **Shape 2 (canonical name, correct `source: linkedin_dm`):** the migration skips. No operator action needed.
- **Shape 3 (renamed):** the migration adds the canonical-named rule. Operator should review + delete one of the two overlapping rules to clean up the dual-enforcement state.

Shape 1 (canonical name, stale source) does NOT apply — there has never been a pre-Week-8 factory-shipped LinkedIn DM cap rule, so no operator could have copied a stale shape. Per D81, the migration is silent on operator-hand-written rules with non-canonical source values (those are operator-deliberate; not stale-from-factory).

For operators who want to skip the migration entirely (e.g. "I never use LinkedIn DM dispatcher; don't add this rule to my files"), the existing-operator seed pattern per ADR-0014 D36 + ADR-0015 D41 + ADR-0020 §"Existing-operator seed" applies:

```python
from datetime import datetime, timezone
from orchestrator.migrations.state import (
    MigrationState, mark_applied, save_state_atomic,
    load_state, DEFAULT_STATE_DIR,
)
from orchestrator.migrations.types import MigrationCategory

state = load_state(DEFAULT_STATE_DIR)
now = datetime.now(timezone.utc)
mark_applied(
    state, MigrationCategory.POLICY, "0003_add_li_dm_weekly_cap",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `policy/0003` as applied; `apply()` skips it; the operator's `cooldowns.yml` files stay unmodified.

**Recommended posture per operator profile:**

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero LinkedIn DM history) | Run `apply()` normally. The migration writes the rule with the safe default; if you never send DMs the rule fires zero times. |
| Existing operator who uses LinkedIn DMs | Run `apply()` normally. Tune `max_units:` in your operator-installed `cooldowns.yml` if 50/week is too low (operators with established sender reputations) or too high (warm-up operators ramping up). |
| Existing operator who does NOT use LinkedIn DMs + does NOT want the rule in their files | Seed `policy/0003` per the snippet above. Your `cooldowns.yml` stays untouched. |
| Yang (current sole operator, as of 2026-05-22) | Recommended: run `apply()` normally. The 50/week default is conservative for Yang's current DM cadence. |

## Migration / rollout

The Week 8 migration is `policy/0003_add_li_dm_weekly_cap`. Rollout shape:

1. Operator pulls Week 8 code. Engine code unchanged (D76 inherited: no SUPPORTED set extension). Pre-existing policy files (at v2 post-policy/0001) continue to load fine. Doctor preflight surfaces `policy/0003` as pending.

2. Operator runs `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             N pending: ..., policy/0003_add_li_dm_weekly_cap
   ```

3. **Quiesce concurrent writers if any** (per ADR-0012 D21):
   * Close editor sessions on policy YAML files.
   * Stop any daemon that reloads policy on SIGHUP (Pillar H future).

4. Operator runs dry-run preview:
   ```python
   from orchestrator.migrations import MigrationRunner, MigrationCategory
   runner = MigrationRunner()
   preview = runner.dry_run(MigrationCategory.POLICY)
   ```
   The preview reports affected_count = (number of operator policy files that don't yet have the canonical rule).

5. Operator applies for real:
   ```python
   runner.apply(MigrationCategory.POLICY)
   ```
   Each policy file's `rules:` list gains one new entry at the end (after Week 7's invite cap, if present).

6. Operator inspects the migrated file:
   ```bash
   tail -10 ~/.outreach-factory/policies/cooldowns.yml
   #   - name: linkedin-weekly-dm-cap
   #     type: budget.window-cap
   #     block_when:
   #       channel: linkedin
   #     source: linkedin_dm
   #     window_days: 7
   #     max_units: 50
   #     reason: "LinkedIn weekly DM cap (...)"
   ```

7. The engine reloads `cooldowns.yml` on next dispatcher invocation. The rule joins the active rule set. LinkedIn DM sends from this point forward are gated by the per-week cap.

The factory `cooldowns.example.yml`'s commented `Rule 12c` ships as part of Week 8's commit. Operators copying the factory template in the future see the documented DM-cap shape.

Doctor preflight does not need to change for this ADR — the rule is shape-identical to other `budget.window-cap` rules, which doctor already validates structurally.

A CLI (`python -m orchestrator.migrations apply`) remains deferred to Pillar I OSS bring-up.

The migration is reversible — `runner.rollback(MigrationCategory.POLICY, "0003_add_li_dm_weekly_cap", allow_rollback=True)` removes the canonical-named rule. Operators rarely invoke; the defense-in-depth `allow_rollback=True` flag (ADR-0009 D4) makes accidental rollback a deliberate operator action.

## References

- ADR-0001 (policy engine architecture) — `policy_blocked` event shape; `RULE_REGISTRY` discriminator + `BudgetWindowCapRule` consumer.
- ADR-0003 (channel as first-class policy predicate) — `block_when.channel:` semantics consumed by the migrated rule.
- ADR-0006 (budget rules + cost_incurred event) — `BudgetWindowCapRule` units mode + `cost_incurred` schema. The rule the migration adds is an instance of this class.
- ADR-0008 (LinkedIn weekly invite cap migration from hardcoded constant to policy rule) — the invite-specific predecessor; Week 8 is the DM analog.
- ADR-0009 (migration framework foundation) — D1-D7 + the per-category ADR-per-dispatcher convention.
- ADR-0010 (ledger migrations) — `migration_event` audit-trail emission is ledger-specific; policy migrations remain ledger-silent.
- ADR-0011 (vault migrations) — surgical-edit precedent for in-place YAML rewrites.
- ADR-0012 (policy migrations — surgical YAML rewrite) — the policy-migration architecture this ADR builds on.
- ADR-0014 (channel-as-event-field invariant) — D33's "every policy_blocked event MUST stamp channel" invariant.
- ADR-0015 (Pillar C LinkedIn-invite dispatcher) — D40's split-source convention. The migration's `source: linkedin_dm` is the DM half of the split.
- ADR-0016 (Pillar C LinkedIn-DM dispatcher) — D43's `source="linkedin_dm"` emit convention. The Week 8 rule's `source:` field matches exactly.
- ADR-0020 (Pillar C Week 7 — per-channel policy migrations) — D72-D78. ADR-0021 inherits the structural decisions; D79-D83 are the LinkedIn-DM-specific decisions.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies the conservative D79 default).
- `docs/PILLAR-PLAN.md` §1 — I1 (single source of truth), I3 (schema versioning), I5 (observable by default), I6 (tests prove invariants).
- `docs/PILLAR-PLAN.md` §2 Pillar C — scope + exit criterion. Week 8 ✓.
- `docs/PILLAR-PLAN.md` §6 Pillar C row — updated to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4 ✓ + Week 5 ✓ + Week 6 ✓ + Week 7 ✓ + Week 8 ✓".
- `docs/SOURCES-OF-TRUTH.md` row "Cooldown / budget / window policy" — the SoT this migration writes to.
- `orchestrator/migrations/policy/_policy_io.py` — `add_rule_block_text`, `remove_rule_block_text` (landed Week 7; consumed unchanged by Week 8).
- `orchestrator/migrations/policy/migration_0003_add_li_dm_weekly_cap.py` — the migration class + module-level constants (`RULE_NAME`, `RULE_TYPE`, `RULE_SOURCE`, `RULE_BLOCK_WHEN_CHANNEL`, `RULE_WINDOW_DAYS`, `RULE_MAX_UNITS`, `RULE_REASON`, `RULE_BLOCK_TEXT`).
- `orchestrator/migrations/policy/__init__.py` — `MIGRATIONS = [MIGRATION_0001_ADD_ENGINE_COMPAT, MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP, MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP]`.
- `config-template/cooldowns.example.yml` — Rule 12c (commented LinkedIn DM cap example) added as part of Week 8.
- `tests/test_migrations_policy_0003.py` — 53 direct migration tests.
- Forward-references (planned):
  - **ADR-0022** (Pillar C Week 9) — Twitter DM weekly cap migration. Same shape; D72-D74 directly inherited from ADR-0020; D75/D76 inherited (content-additive); ADR-0022's LinkedIn-DM-specific equivalents to D79-D83 will be Twitter-DM-specific (cookie-scrape MCP + ALLOW follow-state gate per ADR-0018; `source="twitter_dm"`).
  - **ADR-0023** (Pillar C Week 10) — Calendar booking daily cap migration. The window is daily (not weekly) — first per-week migration with a non-7-day scope; the rule class is still `budget.window-cap` per ADR-0006.
  - **ADR-0024** (Pillar C Week 11) — Cross-channel email/LinkedIn cooldown migration (bidirectional). The cross-channel shape adds TWO rules in one migration — slight variation on the single-rule pattern but same primitives.
  - Pillar I doctor preflight enhancement — warn on §D82 Shape 3 (dual-rule transitional state). Same detect surface as ADR-0020's Shape 3.
  - Pillar I OSS bring-up CLI (`python -m orchestrator.migrations apply`) — the operator-facing command-line surface for the per-category dispatcher. Inherits all of Pillar B + C's primitives.
