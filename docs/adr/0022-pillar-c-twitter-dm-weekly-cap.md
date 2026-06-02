# ADR-0022: Per-channel policy migrations — Twitter weekly DM cap (Pillar C Week 9)

- **Status:** Accepted
- **Date:** 2026-05-22
- **Pillar:** C (Multi-channel coherence — Week 9's per-channel policy migration; third of Weeks 7-11)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0020 (Week 7) shipped the first per-channel policy migration — `policy/0002_add_li_invite_weekly_cap` — and established the convention each subsequent per-channel cap migration follows. D72-D78 cover the structural decisions (ID convention, APPEND insertion, rule-name idempotence, content-additive-no-version-bump, existing-operator seed taxonomy, downstream pillar impact). ADR-0021 (Week 8) shipped the second per-channel policy migration — `policy/0003_add_li_dm_weekly_cap` — and decided five LinkedIn-DM-specific concerns (D79-D83). Both ADRs are read by Week 9 contributors; Weeks 8-11 inherit the structural decisions; D79-D83 are precedent for D84-D88 modulo the per-channel adaptations.

What Week 9 adds is the next concrete migration in the Week 7-11 trajectory: `policy/0004_add_tw_dm_weekly_cap`. The structural shape is identical to Week 8's modulo three rule-shape parameters — channel filter (`twitter` vs `linkedin`), source value (`twitter_dm` vs `linkedin_dm`), and canonical name (`twitter-weekly-dm-cap` vs `linkedin-weekly-dm-cap`). ADR-0022 records only the decisions that are Twitter-DM-specific (or are inheritances worth pinning explicitly so a future contributor reading just this ADR can ship correctly without first reading ADR-0020 + ADR-0021).

ADR-0018 (Pillar C Week 5) is the prerequisite ADR establishing the dispatcher whose emissions this rule consumes. ADR-0018 D58 names `source="twitter_dm"` as the Twitter DM dispatcher's `cost_incurred` emission shape — the canonical source-filter value from day one of Twitter DM dispatch. ADR-0018 D58 also establishes `channel="twitter"` (distinct from LinkedIn's `linkedin`), which makes Twitter an independent cross-channel join target. ADR-0015 D40's split-source convention separates `linkedin_invite`, `linkedin_dm`, and `twitter_dm` so operators can configure per-action caps; Week 7 activated the invite cap; Week 8 activated the LinkedIn DM cap; Week 9 activates the Twitter DM cap.

The five concerns Week 9 resolves:

1. **`max_units:` default — Twitter's enforcement surface differs from LinkedIn's.** Where LinkedIn DM (Week 8) bottlenecks on account-level enforcement (multi-week recovery; outreach surface lost), Twitter DM bottlenecks more often on the cookie-scrape MCP rate-limit (recoverable; re-capture cookies + resume). The asymmetric-failure-cost calculus on the false-allow side is LOWER for Twitter. But Twitter's filtered-DM inbox path means high-volume cold outreach without reciprocal engagement DOES trigger account-level penalties when the operator strays beyond the typical cold-outreach intensity. D84 pins the default at 50 (matching Week 8 for cross-channel consistency) + names the asymmetric-failure-cost calculus differences.
2. **Factory template Rule 12d — whether to ship a commented documentation example.** Week 7 + Week 8 both shipped factory Rule 12b + 12c respectively. Week 9 has the same choice: ship a commented Rule 12d mirroring Rule 12c's shape, OR skip the factory update because the migration writes operator-installed files regardless. D85 pins YES.
3. **Stale-source detection — whether to mirror Week 7's WARNING log path.** Week 7's policy/0002 detects `linkedin-weekly-invite-cap` rules with `source: linkedin` (the pre-Pillar-C-Week-2 factory shape) + warns at WARNING level per ADR-0020 §D77 Shape 1. Week 8's ADR-0021 D81 already rejected the analogous staleness path for LinkedIn DM. Week 9 asks whether an analogous staleness path applies for Twitter DM. D86 pins NO (same posture as ADR-0021 D81).
4. **Existing-operator seed — which of ADR-0020 §D77's three shapes apply.** The Twitter DM dispatcher shipped after the split-source convention; Shape 1 (canonical name with stale source) has no historical precedent. D87 pins the subset that applies (Shape 2 + Shape 3; not Shape 1).
5. **Downstream pillar impact — adapted from ADR-0020 D78 + ADR-0021 D83.** The Week 9 rule has the same shape Pillar D / E / F / G / H / I / J query/observe as Weeks 7 + 8. D88 names the Twitter-DM-specific adaptations (cookie-scrape MCP discoverability per ADR-0018 D59; `tw_dm_thread_id` correlator instead of `linkedin_thread_id`).

Risks this ADR mitigates by design: **R-account-throttle-on-Twitter-DM-volume** — operators with Twitter DM dispatchers can over-quota themselves silently (the cookie-scrape MCP's `send_dm` returns success even when Twitter's account-level enforcement starts deprioritizing recipient notifications or routing the operator's DMs to the recipient's filtered Message Requests tab regardless of follow status; the failure mode surfaces as a slow rate of replies, not an immediate refusal). The per-channel DM cap closes the gap by refusing further sends before the account-level enforcement kicks in. Additionally **R-cookie-scrape-rate-limit-exhaustion** — operators sending DMs above the cookie-scrape MCP's ~10-calls/minute threshold per ADR-0018 D59 see the MCP throttle them; a weekly cap at 50 keeps even bursty operators well under the rate-limit envelope (50/week ≈ 7/day ≈ <1/minute average).

## Decision

### D84. `max_units: 50` — matches Week 8's LinkedIn DM default for cross-channel consistency

The factory-shipped + migration-written `twitter-weekly-dm-cap` rule's `max_units:` is **50** (50 DMs per 7 days per Twitter account).

**Why 50:**

- **Cross-channel consistency with LinkedIn DM.** Week 8's ADR-0021 D79 pinned 50 for LinkedIn DM. Both DM channels share similar cold-outreach intensity profiles + recipient-friction characteristics. Operators don't reason about "LinkedIn DM cap" and "Twitter DM cap" as independent quantities; they reason about "DM cap" as one concept. A consistent default across the two channels avoids surprising the operator who tunes one but not the other.

- **Asymmetric failure modes.**
  - **False-block (cap too low + operator hits it before account-level enforcement would):** one-line YAML edit raises the cap. Operator-time cost ~30 seconds.
  - **False-allow (cap too high + Twitter account-level enforcement triggers):** Twitter routes the operator's cold DMs to the recipient's filtered Message Requests tab regardless of follow status (the recipient sees a notification badge but is more likely to ignore than respond), OR Twitter suspends the account for spam-like behavior (multi-week recovery; outreach surface lost). Operator-time cost: days-to-weeks + reputational damage with the recipients whose threads now dangle.
  - The cost ratio is asymmetric (though LESS than LinkedIn DM's — see "different failure mode profile" below). The default biases toward refuse.

- **Different failure mode profile from LinkedIn DM.** Where ADR-0021 D79 emphasizes LinkedIn's account-level enforcement (silent shadowbanning + multi-week account-recovery), Twitter's enforcement-shape differs in two structural ways:
  1. **The cookie-scrape MCP is the more-common bottleneck.** Per ADR-0018 D59, the `mcp__scraplingserver__*` surface rate-limits at ~10 calls/minute — the operator hits this far earlier than Twitter's account-level enforcement for typical cold-outreach cadences. The failure mode is recoverable (re-capture cookies; resume); the asymmetric-failure-cost on the false-allow side is structurally LOWER than LinkedIn DM's.
  2. **Twitter's account-level enforcement IS still real.** Twitter suspends accounts that send high-volume DMs to non-followers without reciprocal engagement (the spam classifier weighs sends-to-non-mutuals + low-reply-rate signals). The account-level enforcement is rarer than the cookie-scrape rate-limit but more severe when it triggers (multi-week recovery; account loss).
  - Net: the EXPECTED failure mode is recoverable (the operator hits the cookie-scrape limit before the account limit; they re-capture cookies and continue). The WORST-CASE failure mode is account-level loss (rarer but catastrophic). The 50/week default protects against the worst case while leaving headroom above the typical operator's cadence — operators sending ~7/day will rarely hit the cap.

- **Below the cookie-scrape rate-limit envelope.** 50 DMs/week ≈ 7/day ≈ <1/minute average over an 8-hour operator-active window. Well under the cookie-scrape MCP's ~10-calls/minute throttle per ADR-0018 D59 (even bursting all 50 in a single 5-minute window stays under the rate-limit). The cap is structurally compatible with the MCP's enforcement; an operator hitting the cap is also operating well within the MCP's surface limits.

- **Operator-tunability.** Operators with Twitter Premium accounts (higher rate-limits at Twitter's API tier; the cookie-scrape MCP may inherit higher per-account thresholds depending on the account's verification status) plausibly tune up (operators in the 80-100 range with reciprocal engagement history). Operators in the warm-up phase plausibly tune down (operators in the 10-25 range building reputation). The factory's 50 covers the median use case; the rule's `name:` is the load-bearing identifier (D74 idempotence) so operator tuning is preserved through subsequent re-applies.

- **Doctor preflight (Pillar I) is the natural future home for tuning advice.** A future Pillar I doctor preflight pass may inspect the operator's actual `cost_incurred.source=twitter_dm` history + observed cookie-scrape rate-limit-hit events + suggest a tuned cap based on observed volume. Until then, 50 is the safe-by-default starting point.

**Rejected D84 alternatives:**

- **`max_units: 30` — more conservative for Twitter's filtered-DM friction.** **Rejected** because:
  - The cross-channel inconsistency cost outweighs the marginal additional protection. Operators thinking about "DM cap" as one concept would be confused by 50/week for LinkedIn but 30/week for Twitter — surface asymmetry without semantic motivation.
  - The cookie-scrape MCP's ~10-calls/minute rate-limit is the practical bottleneck for most operators; 30 vs 50 weekly cap is irrelevant for operators who hit the per-minute limit first. The cap protects against the rarer account-level enforcement; 50 is below the typical account-level threshold for non-Premium operators.
  - The 30-vs-50 difference is plausibly within the noise band of "what's the actual threshold for account-level penalties"; both are conservative defaults; the cross-channel consistency tiebreaker is the principled choice.
  - Operators in the warm-up phase (the population this alternative would protect) get the recommendation in the migration's commit notes + Pillar I doctor's future tuning advice; the factory default's job is the median case.

- **`max_units: 100` — match Twitter's "high but not abusive" cold-outreach cadence.** **Rejected** because:
  - 100/week DMs is plausibly above the silent account-level enforcement threshold for non-Premium operators without established sender reputations. The asymmetric-failure-cost calculus on the false-allow side disfavors the higher default.
  - The cookie-scrape MCP's ~10-calls/minute rate-limit means 100/week ≈ 14/day is still below per-minute limits, BUT the daily bursting creates more friction with the cookie-scrape's anti-abuse heuristics. The MCP's rate-limit shape isn't well-documented; a higher default risks operators hitting MCP-side throttling unexpectedly.
  - The cross-channel inconsistency cost applies in the other direction: 100 for Twitter but 50 for LinkedIn DM would confuse operators who reason about "DM cap" as one concept.

- **No factory default — operator MUST set `max_units:` explicitly before the rule activates.** **Rejected** because:
  - Same rationale as ADR-0021 D79's rejection of this alternative. Defeats the purpose of the migration; the engine's policy YAML schema doesn't currently support "rule with no `max_units:` is no-op"; operators who want the behavior can comment-out the migrated rule + uncomment manually after setting their value.

- **`max_units: 75` — arithmetic mean of conservative (50) and aggressive (100).** **Rejected** because:
  - Arithmetic-mean shapes are unmotivated by the underlying failure mode. The relevant questions are "what number stays below the cookie-scrape rate-limit envelope?" and "what number stays below the account-level enforcement threshold?" — not "what number balances two arbitrary bounds?"
  - 75 is in the same noise band as 50 from the account-level enforcement perspective; the cross-channel consistency tiebreaker favors 50.

### D85. Ship factory-template Rule 12d — commented Twitter DM cap example mirroring Rule 12c

The Week 9 commit adds a commented `Rule 12d` block to `config-template/cooldowns.example.yml`. The block mirrors Rule 12c's shape (LinkedIn DM cap) modulo channel filter / source / reason; it ships BETWEEN Rule 12c (LinkedIn DM cap) and Rule 13 (the tier-scoped budget cap example) — the next slot in the file's existing ordering per ADR-0021 D80's precedent.

**Why ship Rule 12d:**

- **Per-channel symmetry.** Pillar C's structural identity is "every channel gets full primitive coverage." The factory template's documentation should reflect this — operators reading the file should see one example per channel-action combination Pillar C delivers. After Week 8 there are Rule 12b (LinkedIn invite) + Rule 12c (LinkedIn DM); Rule 12d (Twitter DM) completes the per-channel set for the three Weeks-2-5 channel dispatchers (LinkedIn invite + LinkedIn DM + Twitter DM). Skipping Rule 12d would leave operators reading "Rule 12c: LinkedIn DM cap" + wondering "is there a Twitter DM cap too? where is it documented?" The mirror closes the documentation gap.

- **New-operator onboarding.** Operators copying `cooldowns.example.yml` to `~/.outreach-factory/policies/cooldowns.yml` get the commented Rule 12d as documentation in their installed file. When they later run `runner.apply(MigrationCategory.POLICY)`, the migration's APPEND semantics (D73 inherited from ADR-0020 through ADR-0021) drops the active rule AFTER the existing rule list — the operator's commented Rule 12d remains as documentation alongside the migration-installed active rule. The two coexist legibly.

- **Operator-tuning template.** Operators who want to start with a different `max_units:` value (e.g. 25 for warm-up) can uncomment Rule 12d BEFORE running the migration + set their value. The migration's name-match idempotence (D74) then skips the file because the operator's rule shares the canonical name. The factory comment is the on-ramp for operator-deliberate tuning at install time.

- **Per-channel discoverability for the Twitter cookie-scrape MCP friction.** The factory's Rule 12d header comment names the cookie-scrape rate-limit per ADR-0018 D59 explicitly — operators inspecting the factory file see the per-channel context (LinkedIn invite caps reference LinkedIn's published 100/week soft limit; LinkedIn DM caps reference the opaque-account-level enforcement; Twitter DM caps reference the cookie-scrape rate-limit). Each per-channel example documents its channel's specific failure-mode rationale. This per-channel rationale-in-comments grows the operator's mental model of the cross-channel failure-mode landscape without requiring them to read the ADRs.

- **Identical maintenance cost to skipping.** Adding Rule 12d is ~35 lines of comment + YAML in the factory file (slightly more than Rule 12c because the Twitter-specific cookie-scrape context is worth documenting inline for operator-readability). Skipping has zero file-edit cost but creates an asymmetric file (every other channel-action gets a documented example; Twitter DM doesn't). The cost-benefit clearly favors shipping.

**Rejected D85 alternatives:**

- **Skip Rule 12d — let the migration's writeback be the operator's first exposure.** **Rejected** because:
  - Operators inspecting the factory file before running migrations see Rule 12b + 12c for LinkedIn but nothing for Twitter DM — surface asymmetry the per-channel migration sequence should not introduce. Same rationale as ADR-0021 D80's rejection of this alternative.
  - The Pillar I doctor preflight (future) will plausibly grep the factory file for canonical rule names; an absent canonical name forces a special-case "Pillar C Week 9's rule has no factory example" branch in the doctor. Shipping the example keeps the doctor's grep uniform.
  - The Twitter-specific cookie-scrape context (per ADR-0018 D59) is operator-relevant — operators who want to understand why the Twitter cap fires at a different observable boundary than LinkedIn caps benefit from the inline documentation.

- **Ship Rule 12d but reuse Rule 12c's comment verbatim (just swap `linkedin` → `twitter`).** **Rejected** because:
  - The per-channel failure-mode context is genuinely different. LinkedIn DM's primary failure mode is account-level enforcement (Week 8's emphasis); Twitter DM's primary failure mode is cookie-scrape MCP rate-limit (D84's emphasis). Verbatim reuse would misdirect operators about what the cap protects against.
  - The factory file's job is to document per-channel context; a uniform comment block defeats the per-channel documentation discipline.

- **Ship Rule 12d with `max_units: 100` to demonstrate operator-tunability.** **Rejected** because:
  - The factory documentation must match the migration's actual writeback. If Rule 12d shows `max_units: 100` but the migration writes `max_units: 50`, operators reading both surfaces see contradictory recommendations — confusing + a maintenance hazard. Same rationale as ADR-0021 D80's rejection of `max_units: 100` for Rule 12c.

### D86. NO stale-source detection — same posture as ADR-0021 D81

The Week 9 migration's `upgrade()` does NOT emit a WARNING log when the canonical `twitter-weekly-dm-cap` rule is already present with a non-canonical `source:` value. The migration's idempotence check (D74 inherited from ADR-0020) skips the file when the canonical name is present — it does NOT inspect the rule's other fields to surface staleness.

This is a deliberate inheritance from ADR-0021 D81's posture, which itself diverges from Week 7's policy/0002 WARNING path. The structural reason is identical: no historical factory shape exists for Twitter DM operators to have stale-copied.

**Why no stale-source path for Week 9:**

- **No historical precedent.** Twitter DM dispatcher (ADR-0018) shipped 2026-05-22 — AFTER ADR-0015 D40's split-source convention (Week 2 — 2026-05-20). There has never been a factory-shipped `twitter-weekly-dm-cap` rule with any non-canonical `source:` value for operators to have copied. ADR-0008's factory comment was invite-specific; ADR-0016 + ADR-0018 both shipped after the split-source convention; no equivalent staleness shape exists for the post-Week-2 channels.

- **Operator-hand-written rules are operator-deliberate.** If an operator hand-wrote a `twitter-weekly-dm-cap` rule with `source: twitter` (without the `_dm` suffix — a plausible un-suffixed naming choice) or `source: linkedin_dm` (a likely copy-paste mistake from Week 8's rule), the divergence is operator-deliberate — perhaps they're using a custom dispatcher emitting a different source, perhaps they made a copy-paste mistake they'll find on next inspection. The migration should not nag.

- **Asymmetric stale-source posture across the policy/0002-0006 range.** Per ADR-0020 §D77, Shape 1 (stale source) applies only to the invite rule (Week 7) because the factory file ships only the invite rule's commented form with the historical `source: linkedin` value. Shapes 2 + 3 (canonical correct, or renamed) apply to every per-channel migration uniformly. Per the Week 7 / Week 8 / Week 9 sequence: Shape 1 applies only to Week 7; Shapes 2 + 3 apply to Weeks 7-11.

- **Same pattern carries to Week 10's Calendar booking + Week 11's cross-channel.** Both subsequent weeks involve channels whose dispatchers shipped after the split-source convention; both inherit ADR-0021 D81 + ADR-0022 D86's "no stale-source" posture. The structural intervention against a future contributor reflexively adding a "stale source detection" branch by mirroring policy/0002 is the `TestNoStaleSourceWarning` test class introduced in Week 8 + extended in Week 9. Any future per-channel migration whose ADR-decision says NO stale-source detection gets a `TestNoStaleSourceWarning` class with sub-cases covering the values an operator might hand-write.

- **A future Pillar I doctor preflight is the home for misconfig detection.** The Pillar I OSS bring-up will ship a `python -m orchestrator.policy doctor` command that inspects every active policy rule for canonical-shape conformance + warns on per-rule deviations (wrong source value, wrong channel value, wrong scope, etc.). That command is the principled home for per-rule misconfig surfacing; the per-migration WARNING path in policy/0002 is a one-off accommodation for the specific Shape 1 case. Week 9 does not introduce a parallel one-off for a shape that does not exist.

**Rejected D86 alternatives:**

- **Mirror Week 7's WARNING path: warn on any non-canonical `source:` value when the canonical name is present.** **Rejected** because:
  - Same rationale as ADR-0021 D81's rejection of this alternative. Pillar I's doctor is the correct surface for general misconfig detection. A per-migration WARNING for every conceivable deviation pollutes the runner's apply logs + duplicates effort that Pillar I will land cleanly.
  - The Shape 1 case (a specific historical mistake from a specific factory shape) is fundamentally different from "operator's rule has the wrong source" — the former is a known-population state with a known operator base; the latter is an open-ended class. Treating them the same conflates remediation paths.

- **Add a "warn-on-linkedin-source-mistake" path specifically for Twitter (the most likely copy-paste mistake).** **Rejected** because:
  - The migration would be encoding heuristics about likely operator mistakes; the heuristic surface grows as more migrations land (a Calendar booking migration with a "warn-on-twitter-source" path? a cross-channel migration with "warn-on-single-channel-source" path?). Each per-migration heuristic is a maintenance burden + an audit-trail noise source.
  - The `TestNoStaleSourceWarning` invariant test pins the negative posture explicitly — future contributors who reflexively add the heuristic fail the test + are forced to re-think.
  - Operators who make copy-paste mistakes find them via dispatcher-not-firing observation (the rule activates but reports zero usage); the natural feedback loop is more reliable than a migration-time warning.

- **Emit an INFO log noting the operator's source value when skipping, without a WARNING.** **Rejected** because:
  - Same rationale as ADR-0021 D81's rejection of this alternative. INFO logs are noise in the runner's normal apply path; per-rule visibility belongs in the dry-run preview or Pillar I doctor.

### D87. Existing-operator seed — which ADR-0020 §D77 shapes apply to Week 9

ADR-0020 §D77 catalogs three pre-migration operator shapes for the LinkedIn invite cap (Week 7). For Twitter DM (Week 9), the operator shapes are:

1. **Shape 1 (canonical name, stale source) — DOES NOT APPLY.** Per D86's analysis: there is no historical factory-shipped Twitter DM cap rule; no operator could have copied a stale `source: twitter` (or any other non-canonical value) from a factory shape that never existed. Operators with hand-written non-canonical-source rules are operator-deliberate per D86; the migration is silent. Same posture as ADR-0021 §D82 for LinkedIn DM.

2. **Shape 2 (canonical name, correct source `twitter_dm`) — applies.** Operators who hand-wrote the rule before Week 9 (anticipating the migration, or installed it via copy-paste from the Week 7-8 commits' forward-references in ADR-0020 + ADR-0021) have the rule with the canonical source. The migration's name-match idempotence skips. **Operator remediation:** none needed.

3. **Shape 3 (renamed) — applies.** Operators who wrote their own Twitter DM cap rule with a different name (e.g. `twitter-dm-cap-50` or `my-tw-throttle`) have a rule that delivers the same enforcement under a different name. The migration's name-match (canonical-name only) treats it as "not present" + adds the canonical-named version alongside. The operator now has TWO rules with overlapping enforcement. **Operator remediation:** delete one of the two rules. (The canonical version is operator-acceptable to delete — it's the migration's default; the operator's renamed version preserves their tuning. Or vice versa — operator's choice.) Same posture as Week 7 + Week 8's Shape 3 + the same doctor preflight (Pillar I) is the natural future warning surface.

The factory file's `cooldowns.example.yml` ships the commented Rule 12d (per D85) — new operators copying the factory get the canonical shape with `source: twitter_dm` from day one. There is no pre-Week-9 factory shape they could have stale-copied (Shape 1's non-applicability).

**Rejected D87 alternatives:**

- **Catalog Shape 1 anyway with a hypothetical "what-if-Twitter-changes-API-emit-shape" path.** **Rejected** because:
  - ADR-0022 is recording the state of the world today, not speculating on future Twitter API changes. The migration's `source: twitter_dm` matches the Pillar C Week 5 dispatcher's emit value (ADR-0018 D58); if Twitter changes the underlying API shape (or the cookie-scrape MCP changes its surface), the dispatcher updates first + the rule's source value follows.
  - Hypothetical future-state Shape 1 would be confusing in the operator-facing rollout text (operators reading the ADR look for actionable advice; speculative scenarios dilute it).

- **Use a tag system (e.g. ADR-0022 references ADR-0021 §D82 by tag instead of restating).** **Rejected** because:
  - ADR-0022 is read independently of ADR-0021 — operators looking up "what does Week 9 do?" should get a self-contained answer. Cross-references force readers to chase a chain of ADRs that erodes the ADR-per-decision discipline.
  - The restatement is short (3 shapes × ~2 sentences each) — not a maintenance burden.

- **Defer existing-operator seed entirely to Pillar I doctor.** **Rejected** because:
  - Pillar I is 34+ weeks out (per PILLAR-PLAN §6 timing). The migration ships now; operator-facing rollout documentation must be in this ADR.
  - The Pillar I doctor is the future automated-detect surface; the ADR is the current operator-readable explanation. Both are needed; deferring one to the other creates documentation gaps.

### D88. Downstream pillar impact

Per the ADR-0009 convention (every Pillar B + C ADR explicitly names cross-pillar impact); identical structure to ADR-0021 D83 modulo the Twitter-DM-specific adaptations.

* **Pillar D (reply + conversation handling).** Reply classifiers may need Twitter-DM-specific per-channel policy rules (e.g. "if `twitter_dm` reply received in last 14d, suppress further DM sends in the same thread"). Pillar D authors follow the same `policy/000N_add_<channel>_<rule-class>_<scope>.py` pattern; the `_policy_io.add_rule_block_text` primitive (landed Week 7) composes. Pillar D's reply joiner correlates `tw_dm_reply_received` events (per ADR-0025 D96's per-channel-prefixed naming convention; supersedes the generic `reply_received` placeholder this paragraph used pre-ADR-0025) to their originating `tw_dm_confirmed` by `intent_id` + `tw_dm_thread_id` (Twitter's per-conversation correlator; the cookie-scrape MCP returns a thread_id on send + a matching thread_id on inbound per ADR-0018 D64). The cap rule's enforcement at send-time doesn't affect this surface.

* **Pillar E (discovery quality + lineage).** No direct interaction. Discovery doesn't emit `cost_incurred` with `source="twitter_dm"` — that source is reserved for the Twitter DM dispatcher's per-send cost emission. Pillar E may add its own `BudgetWindowCapRule` instances filtering by discovery-source values (`source: pdl`, `source: apollo`); the per-channel migration shape composes. Pillar E's `discovery_lineage:` blocks (per ADR-0018 D64) may include a `discovered_via_twitter:` field that ties to a Pillar C `tw_dm_confirmed` event — the cross-pillar query is one join, no Pillar C schema change.

* **Pillar F (voice corpus + draft quality).** Voice-fidelity-scoped policy rules (e.g. "block DM sends whose voice-fidelity score is below X") may need new rule classes. The Week 9 rule does not interact; voice rules are register-and-channel scoped via `block_when:`, not directly composed with the per-channel cap. Pillar F's voice-scorer must strip the intent-id marker (per ADR-0018 D58) from Twitter DM bodies before scoring — same logic as Week 2's invite marker per ADR-0015 D42 + Week 3's DM marker per ADR-0016 D47 + Week 5's Twitter DM marker per ADR-0018 D58.

* **Pillar G (observability).** OTel + Prometheus will emit per-rule metrics; the `twitter-weekly-dm-cap` rule produces `policy_blocked` events with `rule: "twitter-weekly-dm-cap"` + `channel: twitter` (per ADR-0014 D33's channel-on-every-event invariant). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=twitter-weekly-dm-cap` without new code (per ADR-0001). Pillar G's dashboards group by `rule:` field — the per-channel cap rules surface as distinct rows in the per-rule firing-rate dashboard. The cookie-scrape MCP's rate-limit-hit events (when the MCP throttles the dispatcher per ADR-0018 D59) are dispatcher-emitted; Pillar G's dashboard correlates dispatcher-side rate-limit hits with rule-side cap-firings to give operators per-channel "you're approaching the cookie-scrape ceiling" early warnings.

* **Pillar H (daemon + scheduled jobs).** Pre-API-call gating (per ADR-0006 §"Where budget rules fire") may consume the same per-channel rule at additional gates. The daemon's bulk-send workflow per-Person threading may want a per-channel BudgetWindowCapRule instance evaluated AT JOB-DISPATCH time (vs. AT SEND time) — Pillar H's job-dispatch layer composes with the existing rule via the same RULE_REGISTRY. No engine change. Pillar H's per-channel throttling layer should treat Twitter independently from LinkedIn — the cookie-scrape MCP rate-limit pool is distinct from LinkedIn MCP's per ADR-0018 D64; the daemon's per-channel worker budgets compose with the `source="twitter_dm"` cost emission's separate accounting.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant policy directories; each tenant's `cooldowns.yml` gets the Weeks 7-11 migrations independently. The doctor's refuse-on-pending applies uniformly. The CLI's `python -m orchestrator.migrations apply` lands here (deferred from ADR-0012 D20). Pillar I doctor preflight: the §"Existing-operator seed" Shape 3 (renamed + dual-rule transitional state) is the natural detect surface — the doctor scans operator policy files for rules with overlapping `source:` + `block_when.channel:` + `type:` and warns when more than one rule fires on the same event class. Pillar I's CLI may also surface the deferred `python -m orchestrator.twitter check-cookies` ergonomic per ADR-0018 D59 — operators discovering "my cookies expired; that's why my Twitter DM cap isn't firing despite my apparent volume" via the future ergonomic.

* **Pillar J (security + compliance).** GDPR-forget on a policy file doesn't typically apply (rules don't contain PII). A policy migration that removes a deprecated rule class is structurally reversible — `is_reversible=True` carries. Per-tenant rule deletion as part of an account-forget operation is a Pillar I + J intersection — neither week 7, 8, nor 9 ships it. Twitter-specific: the `twitter_handle:` field per ADR-0018 D60 is potentially-PII per Pillar J's classification; the cap rule does NOT consume the field (it filters on `source:` + `channel:`, not per-Person identifiers), so Pillar J's forget tooling operates orthogonally.

**Rejected D88 alternatives:**

- **Defer downstream pillar impact to the consolidated Pillar I doctor.** **Rejected** because:
  - Every ADR since 0014 has named cross-pillar impact explicitly (per the ADR-0009 convention). Skipping for Week 9 would break the precedent + force a future reader to reconstruct the impact from absent context.
  - Cross-pillar impact is structurally similar to ADR-0021 D83 — restating it explicitly with Twitter-specific adaptations forces the explicit per-channel-correctness check.

- **Mark cross-pillar impact identical to ADR-0021 D83 by reference, no restatement.** **Rejected** because:
  - The Twitter-specific adaptations (Pillar D's `tw_dm_thread_id` correlator vs LinkedIn's `linkedin_thread_id`; Pillar H's cookie-scrape MCP rate-limit pool distinct from LinkedIn MCP; Pillar I's `check-cookies` ergonomic deferral) are not identical to the LinkedIn DM version. Restating with adaptations forces the explicit per-channel-correctness check.
  - ADRs should be self-contained per the §D87 rationale.

- **Add a new Pillar K (compliance audit) row anticipating future regulatory needs.** **Rejected** because:
  - PILLAR-PLAN does not include a Pillar K; introducing one in a Week 9 ADR is scope creep beyond the migration. Future ADRs covering compliance shapes belong in their own ADR sequence.

## Alternatives considered

### Alternative 1: Skip Week 9 + bundle Twitter DM cap into Week 11's cross-channel migration

Defer the Twitter DM cap to Week 11 (the cross-channel cooldown week) — bundle the per-channel + cross-channel rules in one mega-migration. **Rejected** because:

- Per ADR-0020 Alternative 3 + ADR-0021 Alternative 1 (rejected): per-week shipping discipline is the project's load-bearing process. A bundled migration would be a single 3+-week commit that's hard to review per-section.
- The cross-channel cooldown rule (Week 11) has a DIFFERENT shape than per-channel caps (it uses `CrossChannelTouchRule` per ADR-0003, not `BudgetWindowCapRule`). Bundling them conflates rule classes — fixing one would force the other into the same commit's review window unnecessarily.
- Operators with Twitter DM dispatchers (Week 5) shipped 2026-05-22 — operators on the Week 5 commit + before Week 11 have weeks-to-months of unprotected Twitter DM sends. The per-week shipping discipline minimizes the unprotected window per channel.

### Alternative 2: Per-Person Twitter DM cap (`budget.per-person-cap` filter, not `budget.window-cap`)

Use the `BudgetPerPersonCapRule` shape (ADR-0006) — "max N DMs per Person per lifetime" — instead of the window-cap shape. **Rejected** because:

- Same rationale as ADR-0021 Alternative 2 (rejected for LinkedIn DM): the failure mode the rule mitigates is account-level throttling, which is aggregated across all recipients. A per-Person cap doesn't constrain account-level volume; an operator could be at 1 DM per Person but 200 DMs/week total + still trigger account-level enforcement.
- Per-Person caps belong in a separate rule (e.g. `twitter-dm-cooldown-per-person`) addressing a different failure mode (recipient-side spam-flag aggregation, which on Twitter manifests as the recipient blocking + the spam classifier seeing the block-rate signal). Conflating the two rule shapes muddies the policy file's per-rule purpose.
- The factory can ship BOTH a per-Person cooldown AND a window cap — they're complementary. Week 9 ships the window cap; the per-Person cooldown for Twitter DMs is a future ADR if the use case surfaces.

### Alternative 3: Reuse Week 8's policy/0003 — drop in `twitter_dm` rule into the same migration

Add the Twitter DM cap rule as a second `RULE_BLOCK_TEXT` inside Week 8's policy/0003 migration; rename to `0003_add_li_dm_and_tw_dm_caps`. **Rejected** because:

- Per ADR-0020 Alternative 3 (mega-migration alt) + ADR-0009 D2 (sequential ID convention): each migration is independently reversible at the migration level. An operator who wants to roll back just the Twitter DM cap while keeping the LinkedIn DM cap needs them as separate migrations.
- The migration was already shipped (commit `c5a4c70`); modifying it post-ship breaks the framework's append-only migration discipline (per ADR-0009 D4 + D7).
- Future per-channel migrations (Calendar booking, cross-channel cooldown) each ship as their own migration — bundling Week 9 with Week 8 would have to also bundle every future per-channel cap, defeating the per-week cadence.

### Alternative 4: Migration also emits a `migration_event` to record the per-channel-cap activation

Per ADR-0010 D17 / ADR-0020 Alternative 4 / ADR-0021 Alternative 4 (all rejected): migrations could emit a `migration_event` audit-trail event. **Rejected** by inheritance:

- Policy migrations are explicitly ledger-silent per ADR-0012 I5. Week 9 inherits the posture.
- Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories.

### Alternative 5: Migration writes a `twitter-weekly-dm-cap` rule with both `source: twitter_dm` AND a wildcard for future Twitter action classes

Construct a single rule that aggregates twitter_dm + any future twitter_* sources into one weekly cap. **Rejected** because:

- The `BudgetWindowCapRule` (ADR-0006) accepts a SINGLE `source:` value per instance; wildcard-source matching would require a new rule class (e.g. `BudgetWindowMultiSourceCap`). Schema change → bump version → coordinate engine update → scope creep against content-additive migration. Same rationale as ADR-0021 Alternative 5.
- Per ADR-0015 D40's split-source convention: operators want per-action visibility on caps. Aggregating sources hides the per-action breakdown in the `policy_blocked` event stream (Pillar G's per-rule dashboard would surface a single "twitter-combined-cap" row instead of two).
- The Twitter dispatcher currently has only one action class (DM per ADR-0018 D61 — Twitter has no invite-vs-DM ambiguity). A future Pillar F may add a Twitter thread-mention action class (per ADR-0018 D61's deferral case); that future ADR would ship its own per-action cap migration following the established pattern. Bundling now would be premature.

### Alternative 6: Ship the Twitter DM cap with a `cookie_scrape_aware: true` field that integrates with the MCP's rate-limit reporting

Add a Twitter-specific configuration field that lets the rule consult the cookie-scrape MCP's rate-limit telemetry + auto-tune. **Rejected** because:

- The MCP's rate-limit telemetry surface is not stable (per ADR-0018 D59 — the cookie-scrape MCP's surface is operator-environment-dependent; the Protocol covers the two methods the dispatcher consumes but not telemetry endpoints).
- Cross-cutting "MCP-aware rule fields" would be a fundamental rule-class extension; not within Week 9's scope.
- Operators who want MCP-telemetry-integrated caps can write a custom dispatcher that emits `cost_incurred` with adjusted units based on observed rate-limit headroom; the cap rule remains source-filter-based. The `cost_incurred` event's `units:` field is the right surface for per-call cost amplification (e.g. units=3 when the operator is near the rate-limit ceiling).
- Future Pillar G observability ships rate-limit-hit dashboards; Pillar H daemon ships pre-API-call rate-limit-aware backoff. Both are the principled extension paths for the underlying concern.

## Consequences

### Positive

- **Operators using Twitter DM dispatcher (Week 5 onward) get DM-volume protection automatically** when they run the next batch of pending migrations. The 50/week default is a safe starting point for the median operator; operators tune via the one-line YAML edit per D74's name-match idempotence preserves tuning.
- **The migration is content-additive, not schema-changing** (D75/D76 inherited from ADR-0020 through ADR-0021). Files stay at their pre-migration version; the engine's SUPPORTED set is unchanged; no flag-day risk.
- **Per-channel symmetry of the factory template** — Rule 12d documents the Twitter DM cap shape alongside Rule 12c (LinkedIn DM cap) + Rule 12b (LinkedIn invite cap). New operators reading the factory file see one example per channel-action combination Pillar C delivers.
- **Cross-channel consistency in defaults.** Both DM channels' factory defaults are 50/week — operators reasoning about "DM cap" as one concept don't have to maintain different mental models per platform.
- **Pillar C exit criterion progression.** Week 9 closes the Twitter DM cap gap; Weeks 10-11 deliver the Calendar booking daily cap + cross-channel cooldown. After Week 11 Pillar C's per-channel policy coverage is complete.
- **Future per-channel migrations (Weeks 10-11) inherit the pattern cleanly.** ADR-0022's D84-D88 are derivative of ADR-0020's D72-D78 + ADR-0021's D79-D83; Week 10's Calendar booking cap ADR-0023 will diverge meaningfully (daily window not weekly; operator-side-runaway failure mode not platform-side-enforcement). The structural divergence is documented prospectively in the Week 10 handoff.

### Negative

- **Operators with established Twitter sender reputations who actually need a higher cap (e.g. Premium accounts at 80-100/week) will hit the 50 default + need to tune up.** The tuning is a one-line YAML edit, but it's friction the operator only discovers when the cap fires for the first time. Documented in §D84 + the migration's notes; doctor preflight (Pillar I) could plausibly observe the operator's actual `cost_incurred.source=twitter_dm` volume + suggest a tuned value in a future iteration.
- **The Shape 3 (renamed) transitional state** requires operator action to deduplicate when the migration adds the canonical-named rule alongside the operator's renamed version. Same posture as Weeks 7 + 8; documented in §D87.
- **The factory `cooldowns.example.yml` grows by ~35 lines** for Rule 12d — small but real. Operators tracking the factory across versions via git see a new commented block. Acceptable cost for the per-channel-symmetry benefit.
- **The cookie-scrape MCP rate-limit context in Rule 12d's comment may be operator-confusing if the operator's environment uses a different Twitter surface adapter.** The `TwitterClientLike` Protocol per ADR-0018 D59 is surface-agnostic; an operator using the official v2 API (enterprise tier) wouldn't see cookie-scrape rate-limits. The comment names cookie-scrape as the typical case + the operator's environment may differ — same pattern as the LinkedIn MCP-specific notes in Rule 12c.

### Neutral / observability

- The migration logs at INFO with `affected_count` + `already_present` counts. The runner's pending / dry-run / apply reports surface the migration ID + description as expected.
- Policy migrations remain ledger-silent (no `migration_event` events) per ADR-0012 I5; Pillar G is the future home for per-migration metrics on non-ledger categories.
- The rule's `policy_blocked` event shape is unchanged from existing budget-window-cap rules (per ADR-0006 §"Budget blocks emit the standard `policy_blocked` event"). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=twitter-weekly-dm-cap` without new code.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAML remains the SoT for "what rules are active" (per `docs/SOURCES-OF-TRUTH.md`). The migration writes to that SoT — no competing source.
- **I2 (two-phase commit):** Not applicable — policy migrations are internal state evolution, not external side effects. Per-file atomicity (tmp-then-rename + fsync via `write_policy_file_atomic`) is the migration-framework analog. Same posture as ADR-0011 + ADR-0012 + ADR-0020 + ADR-0021.
- **I3 (schema versioning):** The migration does NOT bump the file's `version:` field (D75 inherited from ADR-0020 through ADR-0021 — content-additive migrations don't bump). The engine's `SUPPORTED_POLICY_SCHEMA_VERSIONS` remains `frozenset({1, 2})` — no extension required.
- **I5 (observable by default):** Every apply + downgrade logs at INFO with `affected_count` + already-present counts. Doctor's WARN-on-pending surfaces the migration ID. Per-channel cap firings emit standard `policy_blocked` events with `rule: "twitter-weekly-dm-cap"` + `channel: twitter`.
- **I6 (tests prove invariants):** `tests/test_migrations_policy_0004.py` (57 tests) covers surface compliance, apply / dry-run / downgrade paths, idempotence (canonical-name + operator-renamed + already-present), refuse-loud on every failure mode, runner integration, engine integration (the rule loads + instantiates as `BudgetWindowCapRule`), round-trip byte-identical on the real factory template, coexistence with Week 7's invite cap rule AND Week 8's LinkedIn DM cap rule (the cross-migration coexistence test pair per the Week 8 review carry-forward), three-way coexistence assertion (all three per-channel caps cohabit a single file with pairwise-distinct (source, channel) tuples), and the NO-stale-source-warning invariant per D86.
- **I7 (cost is a first-class concern):** Policy migrations do not emit `cost_incurred` events. The migration's rule, once active, consumes `cost_incurred` events with `source="twitter_dm"` per ADR-0006's existing contract + ADR-0018 D58.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains the ADR-0022 row. `docs/PILLAR-PLAN.md` §6 Pillar C row extends to "Week 9 ✓."

Does not weaken any invariant. The migration is structurally additive: a new rule entry under existing shapes, leveraging existing rule classes, with existing event schemas.

## Existing-operator seed

Per §D87 above, ADR-0020's three §D77 operator shapes reduce to two for Week 9 (same pattern as ADR-0021 §D82 for LinkedIn DM):

- **Shape 2 (canonical name, correct `source: twitter_dm`):** the migration skips. No operator action needed.
- **Shape 3 (renamed):** the migration adds the canonical-named rule. Operator should review + delete one of the two overlapping rules to clean up the dual-enforcement state.

Shape 1 (canonical name, stale source) does NOT apply — there has never been a pre-Week-9 factory-shipped Twitter DM cap rule, so no operator could have copied a stale shape. Per D86, the migration is silent on operator-hand-written rules with non-canonical source values (those are operator-deliberate; not stale-from-factory).

For operators who want to skip the migration entirely (e.g. "I never use Twitter DM dispatcher; don't add this rule to my files"), the existing-operator seed pattern per ADR-0014 D36 + ADR-0015 D41 + ADR-0020 §"Existing-operator seed" + ADR-0021 §"Existing-operator seed" applies:

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
    state, MigrationCategory.POLICY, "0004_add_tw_dm_weekly_cap",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `policy/0004` as applied; `apply()` skips it; the operator's `cooldowns.yml` files stay unmodified.

**Recommended posture per operator profile:**

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero Twitter DM history) | Run `apply()` normally. The migration writes the rule with the safe default; if you never send Twitter DMs the rule fires zero times. |
| Existing operator who uses Twitter DMs | Run `apply()` normally. Tune `max_units:` in your operator-installed `cooldowns.yml` if 50/week is too low (Premium accounts with reciprocal engagement history) or too high (warm-up operators ramping up — consider tuning down to 25 to stay safely under account-level enforcement). |
| Existing operator who uses Twitter via the official v2 API (enterprise tier) instead of cookie-scrape MCP | Run `apply()` normally. The cap is source-filter-based (matches `source: twitter_dm` regardless of underlying transport). Adjust `max_units:` based on your API tier's documented limits. |
| Existing operator who does NOT use Twitter DMs + does NOT want the rule in their files | Seed `policy/0004` per the snippet above. Your `cooldowns.yml` stays untouched. |
| Yang (current sole operator, as of 2026-05-22) | Recommended: run `apply()` normally. Yang's current Twitter DM cadence is well under 50/week; the default is conservative for the current operator. |

## Migration / rollout

The Week 9 migration is `policy/0004_add_tw_dm_weekly_cap`. Rollout shape:

1. Operator pulls Week 9 code. Engine code unchanged (D76 inherited: no SUPPORTED set extension). Pre-existing policy files (at v2 post-policy/0001) continue to load fine. Doctor preflight surfaces `policy/0004` as pending.

2. Operator runs `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             N pending: ..., policy/0004_add_tw_dm_weekly_cap
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
   Each policy file's `rules:` list gains one new entry at the end (after Week 7's invite cap + Week 8's LinkedIn DM cap, if present).

6. Operator inspects the migrated file:
   ```bash
   tail -10 ~/.outreach-factory/policies/cooldowns.yml
   #   - name: twitter-weekly-dm-cap
   #     type: budget.window-cap
   #     block_when:
   #       channel: twitter
   #     source: twitter_dm
   #     window_days: 7
   #     max_units: 50
   #     reason: "Twitter weekly DM cap (...)"
   ```

7. The engine reloads `cooldowns.yml` on next dispatcher invocation. The rule joins the active rule set. Twitter DM sends from this point forward are gated by the per-week cap.

The factory `cooldowns.example.yml`'s commented `Rule 12d` ships as part of Week 9's commit. Operators copying the factory template in the future see the documented Twitter-DM-cap shape with the cookie-scrape MCP context inline.

Doctor preflight does not need to change for this ADR — the rule is shape-identical to other `budget.window-cap` rules, which doctor already validates structurally.

A CLI (`python -m orchestrator.migrations apply`) remains deferred to Pillar I OSS bring-up.

The migration is reversible — `runner.rollback(MigrationCategory.POLICY, "0004_add_tw_dm_weekly_cap", allow_rollback=True)` removes the canonical-named rule. Operators rarely invoke; the defense-in-depth `allow_rollback=True` flag (ADR-0009 D4) makes accidental rollback a deliberate operator action.

## References

- ADR-0001 (policy engine architecture) — `policy_blocked` event shape; `RULE_REGISTRY` discriminator + `BudgetWindowCapRule` consumer.
- ADR-0003 (channel as first-class policy predicate) — `block_when.channel:` semantics consumed by the migrated rule.
- ADR-0006 (budget rules + cost_incurred event) — `BudgetWindowCapRule` units mode + `cost_incurred` schema. The rule the migration adds is an instance of this class.
- ADR-0008 (LinkedIn weekly invite cap migration from hardcoded constant to policy rule) — the original cap rule shape that established the per-channel-cap pattern; Week 7 + Week 8 + Week 9 are sequential applications.
- ADR-0009 (migration framework foundation) — D1-D7 + the per-category ADR-per-dispatcher convention.
- ADR-0010 (ledger migrations) — `migration_event` audit-trail emission is ledger-specific; policy migrations remain ledger-silent.
- ADR-0011 (vault migrations) — surgical-edit precedent for in-place YAML rewrites.
- ADR-0012 (policy migrations — surgical YAML rewrite) — the policy-migration architecture this ADR builds on.
- ADR-0014 (channel-as-event-field invariant) — D33's "every policy_blocked event MUST stamp channel" invariant.
- ADR-0015 (Pillar C LinkedIn-invite dispatcher) — D40's split-source convention. The migration's `source: twitter_dm` is the Twitter portion of the split.
- ADR-0016 (Pillar C LinkedIn-DM dispatcher) — D43's `source="linkedin_dm"` emit convention (precedent for ADR-0018 D58's `source="twitter_dm"`).
- ADR-0018 (Pillar C Twitter-DM dispatcher) — D58's `source="twitter_dm"` emit convention + `channel="twitter"` value (the rule's `source:` + `block_when.channel:` fields match exactly); D59's cookie-scrape MCP surface choice + the ~10-calls/minute rate-limit context (D84's "below the cookie-scrape rate-limit envelope" rationale); D60's ALLOW follow-state gate (orthogonal to the cap rule; the cap fires at the same rate-limit failure-mode boundary D60's allow-posture leaves uncovered); D64's `tw_dm_thread_id` correlator (Pillar D's reply joiner relevance).
- ADR-0020 (Pillar C Week 7 — per-channel policy migrations) — D72-D78. ADR-0022 inherits the structural decisions through ADR-0021.
- ADR-0021 (Pillar C Week 8 — LinkedIn weekly DM cap) — D79-D83. ADR-0022 inherits the LinkedIn-DM-specific decisions modulo the Twitter-DM-specific adaptations; D86's NO-stale-source posture is identical to D81's; D87's existing-operator seed reduces to Shape 2 + Shape 3 (same posture as D82).
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies the conservative D84 default).
- `docs/PILLAR-PLAN.md` §1 — I1 (single source of truth), I3 (schema versioning), I5 (observable by default), I6 (tests prove invariants).
- `docs/PILLAR-PLAN.md` §2 Pillar C — scope + exit criterion. Week 9 ✓.
- `docs/PILLAR-PLAN.md` §6 Pillar C row — updated to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4 ✓ + Week 5 ✓ + Week 6 ✓ + Week 7 ✓ + Week 8 ✓ + Week 9 ✓".
- `docs/SOURCES-OF-TRUTH.md` row "Cooldown / budget / window policy" — the SoT this migration writes to.
- `orchestrator/migrations/policy/_policy_io.py` — `add_rule_block_text`, `remove_rule_block_text` (landed Week 7; consumed unchanged by Weeks 8 + 9).
- `orchestrator/migrations/policy/migration_0004_add_tw_dm_weekly_cap.py` — the migration class + module-level constants (`RULE_NAME`, `RULE_TYPE`, `RULE_SOURCE`, `RULE_BLOCK_WHEN_CHANNEL`, `RULE_WINDOW_DAYS`, `RULE_MAX_UNITS`, `RULE_REASON`, `RULE_BLOCK_TEXT`).
- `orchestrator/migrations/policy/__init__.py` — `MIGRATIONS = [MIGRATION_0001_ADD_ENGINE_COMPAT, MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP, MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP, MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP]`.
- `config-template/cooldowns.example.yml` — Rule 12d (commented Twitter DM cap example) added as part of Week 9.
- `tests/test_migrations_policy_0004.py` — 57 direct migration tests including the three-way coexistence assertion (Weeks 7 + 8 + 9 caps cohabit a single file) + the `TestNoStaleSourceWarning` invariant per D86.
- `tests/test_migrations_replay.py::TestFullBatchApply::test_full_apply_writes_all_per_channel_cap_rules_to_policy_file` (renamed from `test_full_apply_writes_both_per_channel_cap_rules_to_policy_file`) — pins the production sequence end-to-end: runner applies the full migration set + the synthetic `cooldowns.yml` carries all three per-channel cap rules with pairwise-distinct (source, channel) tuples.
- Forward-references (planned):
  - **ADR-0023** (Pillar C Week 10) — Calendar booking daily cap migration. **Structurally divergent from Weeks 7-9** in two ways: (a) the window is DAILY not WEEKLY (`window_days: 1` or `window_hours: 24`); (b) the channel is `calendar` not `linkedin` / `twitter`. The cap value differs — calendar booking emails don't have account-level throttling the way LinkedIn / Twitter do; the cap mitigates "operator-side runaway loop" failure mode rather than "platform-side enforcement." ADR-0023 will diverge meaningfully from ADRs 0020-0022.
  - **ADR-0024** (Pillar C Week 11) — Cross-channel email/LinkedIn cooldown migration (bidirectional). The cross-channel shape adds TWO rules in one migration — slight variation on the single-rule pattern but same primitives.
  - Pillar I doctor preflight enhancement — warn on §D87 Shape 3 (dual-rule transitional state). Same detect surface as ADR-0020's Shape 3.
  - Pillar I OSS bring-up CLI (`python -m orchestrator.migrations apply`) — the operator-facing command-line surface for the per-category dispatcher. Inherits all of Pillar B + C's primitives.
  - Pillar I OSS bring-up CLI (`python -m orchestrator.twitter check-cookies`) — the cookie-scrape MCP capture-state validator deferred per ADR-0018 D59. Operators discovering "my cookies expired; that's why my Twitter DM cap isn't firing despite my apparent volume" via the future ergonomic.
