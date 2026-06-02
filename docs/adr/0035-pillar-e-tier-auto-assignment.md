# ADR-0035: Pillar E Week 6-8 — tier auto-assignment primitive

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** E (Discovery quality + lineage — Week 6-8 tier auto-assignment primitive)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0032 (Pillar E Week 1 foundation) pinned the discovery-lineage shape (D142), the pre-enrichment dedup contract (D143), the email-verification cache shape (D144), the tier auto-assignment substrate (D145), the cross-pillar surface audit (D146), the exit-criterion vehicle scope (D147), and the privacy-respecting invariant (D148). ADR-0033 (Pillar E Week 2) shipped the dedup primitive module (`orchestrator/discovery_dedup.py`) + the per-skill integration in `find-leads` + Amendment 2026-05-24 extending integration to `find-funded-founders` (Phase 4f) + `competitor-customers` (Phase 3e). ADR-0034 (Pillar E Week 4-5) shipped the email-verification cache primitive module (`orchestrator/email_verification_cache.py`) + the wrap inside `orchestrator/enrich_emails.py::verify_with_reoon` + the content-additive cost-event schema extension (`email` + `verification_response` fields per D156). Both Week 2-3 + Week 4-5's primitives carry the same structural shape: per-call primitive + event-emit-shape factory + ledger substrate + CLI surface + per-week cross-pillar audit row extension.

**Pillar E Week 6-8 is the tier auto-assignment primitive.** The handoff (`.planning/HANDOFF-pillar-e-week-6.md` — committed in the Week 4-5 main commit) scopes Week 6-8 to: (a) the tier-assignment primitive's foundation module + emit-shape factory + per-signal weights config substrate; (b) per-Person-invocation integration via an operator-invoked CLI (NOT auto-invocation on every `enroll_person` write per ADR-0032 D145's operator-control posture); (c) the cross-pillar audit row extension naming the new event class's consumer surface; (d) the un-skip of all 3 `TestTierAutoAssignment` coherence rows. The split — dedup in Week 2-3 + cache in Week 4-5 + tier-suggestion in Week 6-8 + per-skill lineage stamping deferred to Week 9-11 — bounds each week's failure radius: a tier-primitive bug in Week 6-8 is one Python module + its tests + one YAML config template; a multi-pillar rework at Week 9-11 would compound risk.

The six concerns this ADR resolves:

1. **The tier-assignment primitive module's PLACEMENT must be pinned before the implementation lands.** Four plausible homes: (a) `orchestrator/tier_assignment.py` (top-level, sibling of `discovery_dedup.py` + `email_verification_cache.py` + `enrollment.py` + `identity.py`); (b) inside `orchestrator/policy/tier.py` (conflates rule-consumer with substrate-supplier — the existing `TierRequiresTierInRule` reads operator-stamped `Person.research_tier` via `ctx.tier`; the auto-assignment SUPPLIES the suggestion; merging the supplier into the consumer collapses the three-step decoupling D145 explicitly pins); (c) inside `orchestrator/enrollment.py` (conflates substrate-supplier with Person-note loader); (d) a new `orchestrator/tier/` subpackage (over-organization for one module in Week 6-8). D160 picks (a). The placement mirrors ADR-0033 D149's + ADR-0034 D154's sibling-of-existing-primitives shape — the tier primitive IS a Pillar E primitive in its own right.

2. **The `tier_suggested` event class's EMIT-SHAPE must be pinned per the channel-on-every-event invariant + the observational-only contract.** Per ADR-0032 D145 + D146 the event carries `channel: "none"` (tier is channel-agnostic — mirrors the dedup primitive's stamp; contrasts with the cache primitive's `channel: "email"`); per D145 the event REPLACES nothing — it is purely observational; the operator-stamped `Person.research_tier` field remains the SoT. The Pillar G dashboard filtering by tier-suggestion-rate must aggregate `tier_suggested` events independently of `manual_override` events (the latter is the operator's explicit override per ADR-0007's existing event class). D161 pins the field shape + the operator-readable `_emitted_by: "tier_assignment"` marker.

3. **The SIGNAL SOURCES the primitive consumes must be pinned + the partial-signal graceful-degradation contract must be explicit.** Per ADR-0032 D145 the firmographic signals are Apollo `organization_size` / `industry` / `funding_stage`; the intent signal is `discovery_lineage.source_skill`. Today's reality: (a) Apollo enrichment is NOT auto-populated into Person notes (the Apollo MCP is available but discovery skills don't currently consume it — forward-reference to Pillar I or beyond when Apollo enrichment lands in `find-funded-founders` etc.); (b) `discovery_lineage.source_skill` is reserved per ADR-0032 D142 BUT not stamped on existing Persons (the per-skill stamping refactor lands Week 9-11); the existing `source_channel` legacy field IS populated by discovery skills and serves as the fallback; (c) `find-funded-founders` specifically populates `round_stage` + `round_size_usd` + `funding_date` per its SKILL.md template — these are firmographic-adjacent signals available today. D162 pins the signal sources + the partial-signal degradation rule (default-low tier B + rationale naming missing signals when the Apollo firmographic signals are absent).

4. **The PER-SIGNAL WEIGHTS CONFIG SHAPE must be pinned at an operator-tunable substrate.** Per the HANDOFF-pillar-e-week-6.md §Design-decisions: three plausible homes for the weights — (a) hardcoded in `tier_assignment.py` (over-rigid; operator changes require code edit); (b) YAML config at `~/.outreach-factory/tier_weights.yml` (operator-tunable; consistent with other policy weights); (c) ML-trained weights file (over-engineered for v1 ~500 Person corpus + requires ML stack). D163 picks (b) — a YAML config with a default-shipped template at `config-template/tier_weights.example.yml`; the operator copies + tunes as their corpus grows. The default weights are calibrated against Yang's available operator-tagged corpus at Week 6-8 ship time (~500 Persons); the §Existing-operator seed names the confidence-interval limitation + the future re-calibration trajectory.

5. **The PER-PERSON-INVOCATION INTEGRATION must be pinned at the operator-invoked CLI grain.** Per ADR-0032 D145 the auto-assignment SUPPLIES the suggestion; the operator decides whether to act on it. D164 pins the integration site (the new CLI subcommand `python orchestrator/tier_assignment.py suggest --person <id> [--apply] [--json]`) + the operator-invocation discipline (no auto-invocation on every `enroll_person` write at v1; the auto-invocation surface preserves the OPERATOR-CONTROL property — the operator decides which Persons to retier). Auto-invocation is a future Pillar E (or Pillar I) week's concern IF operator demand materializes.

6. **The cross-pillar surface audit (per ADR-0032 D146) MUST be extended row-by-row each Pillar E week.** Week 6-8 ships the `tier_suggested` event class — it lands in `_idx_person` when the suggestion carries `person_id` (broadens the per-Person index for every consumer). The audit must verify each consumer is either closed-set-protected or by-design-broadening. D165 names the audit extension.

Risks this ADR mitigates by design: **R001 (identity-graph false-merge cascade)** is not regressed — the tier primitive operates on Person-frontmatter firmographic + intent signals (not identity keys); no identity-resolution semantics change. **R020 (email-verification cache staleness)** is unchanged — the tier primitive does not depend on the cache primitive's substrate (the tier primitive consults Person-frontmatter signals; the cache primitive consults `cost_incurred` events; orthogonal substrates). The asymmetric-failure-cost calculus per PILLAR-PLAN §0 carries: a false-positive tier suggestion (suggested S; operator overrides to B) is one extra event in the ledger (cheap; operator-visible via the `manual_override` event); a false-negative tier suggestion (suggested B; operator stamps S after manual review) is one missed automation benefit (the operator's manual stamping is the existing baseline — Week 6-8 ADDS the suggestion surface; the legacy operator-manual path is preserved). Both failure costs are bounded + asymmetric in the operator-friendly direction.

One new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`:
- **R021 (tier-weights config drift)** — the default-shipped weights are calibrated against Yang's corpus at Week 6-8 ship time (~500 Persons). Future operator changes to the weights file are operator-private (not version-controlled in the framework); an operator-tuned config that diverges from the default may surface tier suggestions that conflict with the SoT corpus. Mitigation by design: the per-signal weights are operator-tunable per a YAML config (the framework treats the config as opaque); the default template ships with explanatory comments naming each weight's rationale + the operator-readable rationale string on every `tier_suggested` event surfaces the decision tree for operator audit; the per-week reviewer's category #5 (per §D165) pins this as a category. Future Pillar I doctor preflight extension MAY check (a) the weights config's shape against the default template + (b) the per-tier distribution against the operator's corpus for drift detection — TBD.

R001 + R018 + R019 + R020 (all named in ADR-0032 §Context) carry the design-time mitigation forward; the Week 6-8 implementation does not regress these.

## Decision

### D160. Tier primitive module placement — `orchestrator/tier_assignment.py`

The tier-assignment primitive ships as a single top-level module under `orchestrator/`, sibling of `email_verification_cache.py` + `discovery_dedup.py` + `enrollment.py` + `identity.py` + `enrich_emails.py`:

```
orchestrator/
├── tier_assignment.py               ← NEW (Pillar E Week 6-8)
├── email_verification_cache.py      ← Pillar E Week 4-5 (the SIBLING primitive)
├── discovery_dedup.py               ← Pillar E Week 2 (the OTHER sibling primitive)
├── enrich_emails.py                 ← Pillar A Week 4 (Reoon call site)
├── enrollment.py                    ← Pillar 5.5 Week 1b
├── identity.py                      ← Pillar 5.5 Week 1b
├── reply_classifier.py              ← Pillar D Week 2 (sibling-primitive precedent)
├── ledger.py
├── reconcile.py
├── policy/
│   └── tier.py                      ← Pillar A's existing tier RULE (consumer of operator-stamped value)
└── ...
```

**The tier primitive is a Pillar E primitive, not a sub-helper of `policy/tier.py`.** Like the dedup primitive (per ADR-0033 D149) + the cache primitive (per ADR-0034 D154), the tier primitive PRODUCES events (it emits `tier_suggested` per the CLI's `--apply` flag) + DERIVES a suggestion (from per-Person firmographic + intent signals). The existing `policy/tier.py::TierRequiresTierInRule` is the CONSUMER of operator-stamped `Person.research_tier` via `ctx.tier`; the tier primitive's auto-assignment is the SUPPLIER of the suggestion. The three-step decoupling per ADR-0032 D145:

1. **Auto-assignment SUPPLIES** the suggestion via `tier_suggested` events (Week 6-8 ships).
2. **Operator STAMPS** the tier via `Person.research_tier` frontmatter (existing per-Person workflow) OR via `manual_override` event per ADR-0007 (existing event class).
3. **Policy rule READS** the stamped value via `ctx.tier` (Pillar A `TierRequiresTierInRule` unchanged).

Putting the auto-assignment SUPPLIER inside the rule CONSUMER would collapse the three-step decoupling — operators reading `policy/tier.py` would conflate the rule's "block when not in allowed_tiers" behavior with the primitive's "suggest a tier from signals" behavior. The sibling-of-existing-primitives placement (D160's choice) preserves the separation.

**Top-level placement matches the existing per-primitive convention.** `orchestrator/discovery_dedup.py` + `orchestrator/email_verification_cache.py` are each Pillar E primitives at this level; `orchestrator/identity.py` + `orchestrator/enrollment.py` + `orchestrator/reply_classifier.py` are sibling primitives at the same level for Pillars 5.5 + D. The tier primitive follows the same shape. An `orchestrator/tier/` subpackage would be over-organization for Week 6-8's ~400 LOC; the subpackage rationale resurfaces in a future Pillar E (or Pillar I) week IF a second tier primitive lands (e.g., a per-tenant tier scheme; an industry-vertical-specific tier — TBD).

**Why NOT inside `orchestrator/policy/tier.py`?** Conflates rule-consumer with substrate-supplier. `policy/tier.py` is the existing `TierRequiresTierInRule` — its load-bearing export is the rule class that filters on operator-stamped `ctx.tier`. Adding a `compute_tier_from_signals` function alongside the rule class would either (i) blur the module's single-purpose ("rule" vs "primitive"); or (ii) require operators reading the rule to also reason about the auto-assignment surface — exactly the cognitive coupling the three-step decoupling per ADR-0032 D145 prevents.

**Why NOT inside `orchestrator/enrollment.py`?** Conflates substrate-supplier with Person-note loader. `enrollment.py` is the post-enrichment enrollment site — it writes Person notes, stamps `identity_keys`, emits `enrolled` events. The tier primitive operates on EXISTING Person notes (read-only — it reads the firmographic + intent signals and emits a suggestion event). Putting the read-only suggestion inside the write-side enrollment module would (i) bloat the enrollment surface; (ii) tempt a future contributor to auto-invoke the suggestion on every enrollment (the rejected D164-Alt1 path).

**Why NOT inside `orchestrator/identity.py`?** Conflates tier-as-firmographic-signal with identity-as-key-resolution. `identity.py` is the strict-policy resolver — it intersects identity keys + refuses ambiguous matches. The tier primitive operates on firmographic signals (organization_size, industry, funding_stage), not identity keys. The shared `IdentityKeys` dataclass is the closest type adjacency, but the tier primitive does NOT consult identity keys at all — it consults Person frontmatter for signals + emits a tier suggestion event.

**Why NOT an `orchestrator/tier/` subpackage?** Over-organization for Week 6-8's scope (~400 LOC of tier primitive + tests). The single-file convention used by every other Pillar primitive is the precedent for new primitives. The subpackage rationale resurfaces IF a future week adds a sibling tier-related primitive (e.g., per-tenant tier overrides; industry-vertical-specific tier schemes).

### D161. `tier_suggested` event class — emit-shape contract

Per ADR-0032 D145 + D146 + ADR-0014 D33 (channel-on-every-event invariant). The `tier_suggested` event class carries the following fields:

```python
{
    "type": "tier_suggested",
    "person_id": "<person-id>",                # the Person whose tier was suggested
    "suggested_tier": "S",                     # one of S | A | B per the closed enum
    "signals_consulted": {                     # dict of EXACTLY the five signals the
                                                # primitive checks; each value or None
                                                # if the signal was absent
        "organization_size": "mid",             # may be None if the signal was absent
        "industry": "ai_ml",
        "funding_stage": "series_a",            # populated from canonical funding_stage
                                                # OR normalized from legacy round_stage
                                                # (e.g., "Series A" → "series_a")
        "source_skill": "find-funded-founders",
        "funding_recency_days": 53,             # integer days since funding_date; None
                                                # if funding_date absent / future / unparseable
    },
    "rationale": "Mid-sized org (50-500) + AI/ML industry + Series A funding + find-funded-founders source (high-intent) + Recent funding (within 53 days) → score 8 → high-intent S tier",
    "channel": "none",                         # tier is channel-agnostic per D146 invariant
    "_emitted_by": "tier_assignment",          # per ADR-0010 D17 convention
}
```

**Field rationale:**

* **`person_id`** — the Person whose tier was suggested. Always populated (the CLI's `--person <id>` is required; the primitive does not support cross-Person suggestions). Lands in `_idx_person` per the ledger index's single-purpose semantics.

* **`suggested_tier`** — one of `S | A | B` per the closed enum (`SUGGESTED_TIERS: frozenset[str] = frozenset({"S", "A", "B"})` — operator-pinned in the module). The values match Yang's existing `Person.research_tier` operator-stamping convention (per the Outreach Tier Playbook); future schemes (e.g., `P1 | P2 | P3`) would extend the enum + require a coordinated ADR amendment. The closed enum refuses-loud on weights-config values that produce non-enum suggestions (a safety net against a typo'd `tier_weights.yml` that emits `"AA"` instead of `"A"`).

* **`signals_consulted`** — dict of the signals the primitive READ (whether or not it found a value). Operator-deliberate denormalization: the dict carries `None` values for signals the primitive checked but didn't find on the Person frontmatter (e.g., `organization_size: None` when Apollo enrichment hasn't run yet). Operators auditing "why did the primitive suggest tier B?" via `python -m orchestrator.ledger grep --type tier_suggested` see the signal coverage directly. Pillar G future dashboards aggregate per-signal coverage rate: "how many tier suggestions are limited by missing organization_size?" — useful for prioritizing future Apollo enrichment integration.

* **`rationale`** — operator-readable explanation string (e.g., `"Recent Series A + AI/ML industry + funded-founders source → high-intent S tier"`). The string is composed from the signals + their weight contributions; the format is human-readable, not machine-parseable. Future Pillar I or G consumers may pattern-match (e.g., "rationale mentions `high-intent`") for category-level aggregation; the v1 contract is "operator-readable per row." Each rationale string carries an arrow (`→`) separator between the signals-list and the conclusion — operator-deliberate so a `grep -P '→ high-intent'` filter surfaces all high-intent suggestions in a corpus.

* **`channel: "none"`** — per ADR-0032 D146's channel-on-every-event invariant extension. The tier primitive is channel-agnostic (tier applies across all channels — email, LinkedIn, Twitter, calendar booking — the operator decides per-channel routing separately). MIRRORS the dedup primitive's `channel: "none"` stamp per ADR-0033 D150; CONTRASTS with the cache primitive's `channel: "email"` stamp per ADR-0034 D155. The asymmetry IS by design — Pillar G dashboards aggregate per-channel for cache hits (email-specific cost avoidance) + channel-agnostic for dedup hits + tier suggestions (cross-channel signals).

* **`_emitted_by: "tier_assignment"`** — per ADR-0010 D17 the operator-facing filter marker. Tests + the cross-pillar audit + the eventual Pillar G dashboard consume this literal string predicate.

**The event REPLACES nothing — it is purely observational.** Per ADR-0032 D145 the auto-assignment SUPPLIES the suggestion; the operator-stamped `Person.research_tier` field remains the SoT. The tier primitive does NOT modify Person frontmatter; the tier primitive does NOT emit `manual_override` events (that's the operator-facing path per ADR-0007). A discovery skill flow MAY:
1. `compute_tier_from_signals(person)` → `TierSuggestion(suggested_tier="S", ...)`
2. The operator reads the suggestion via the CLI's `--json` output OR via the ledger event log.
3. The operator stamps `research_tier: A` on the Person frontmatter (disagreeing with the suggestion).
4. Pillar A's `TierRequiresTierInRule` reads `ctx.tier = "A"` (the operator-stamped value) — UNCHANGED.

The three-step decoupling is preserved; the suggestion event is observational; the operator-stamped field is the SoT.

**Why `channel: "none"` (rejected: `channel: "all"`; rejected: omit the field; rejected: `channel: "email"` mirroring cache).** Four plausible postures:

* **(a) `channel: "none"`** (D161's choice — inherits ADR-0033 D150's dedup primitive convention). Tier is channel-agnostic (tier applies across all channels equally); the explicit `"none"` value is operator-visible to Pillar G dashboards filtering by channel (the absence makes the channel-agnostic semantics explicit).
* **(b) `channel: "all"`** — REJECTED. Semantic mismatch — `"all"` implies "every channel triggered" which is operator-confusing for a tier suggestion (which doesn't trigger anything on any channel). Pillar G dashboards filtering "show me email-channel events" would surface tier suggestions in the email funnel — wrong attribution. The `"none"` value is the precedent established by the dedup primitive; consistency with prior primitives.
* **(c) Omit the `channel` field entirely** — REJECTED. Violates ADR-0014 D33 + ADR-0032 D146's channel-on-every-event invariant. Pillar G dashboards filtering by channel must see every event class with the field (per the invariant's "every event carries the field" rule).
* **(d) `channel: "email"` mirroring the cache primitive** — REJECTED. The tier suggestion is NOT email-channel-specific — it informs the decision to engage on ANY channel (email, LinkedIn, Twitter, calendar booking). Stamping `"email"` would orphan tier suggestions from non-email-channel dashboards.

**Pin:** `tests/test_multi_channel_coherence.py::TestTierAutoAssignment::test_tier_suggested_event_carries_signals_consulted` un-skipped + passing in this Week 6-8 commit. `tests/test_tier_assignment.py::TestBuildTierSuggestedPayload::*` cover every field's contract individually.

### D162. Signal sources — firmographic + intent signals with partial-signal graceful degradation

Per ADR-0032 D145 the firmographic signals are Apollo `organization_size` / `industry` / `funding_stage`; the intent signal is `discovery_lineage.source_skill`. D162 pins the signal sources AS-READ-FROM-PERSON-FRONTMATTER + the graceful-degradation contract:

**Firmographic signals (read from Person frontmatter):**
- `organization_size: small | mid | large | None` — Apollo enrichment's company employee count bucket. Today: typically `None` (Apollo enrichment is not auto-populated into Person notes by any discovery skill). Future: `find-funded-founders` + `research-prospect` may stamp this when Apollo enrichment lands (Pillar I or beyond).
- `industry: ai_ml | saas | dev_tools | None` — Apollo enrichment's industry bucket. Today: typically `None`. Future: same forward-reference.
- `funding_stage: pre_seed | seed | series_a | series_b | series_c_plus | None` — Apollo enrichment's funding stage. Today: typically `None`. The `find-funded-founders` skill DOES populate `round_stage` (e.g., `"Series A"` or `"seed"`) per its SKILL.md template — D162 reads this legacy field as a fallback when `funding_stage` is absent + normalizes (`"Series A"` → `series_a`).

**Intent signals (read from Person frontmatter):**
- `discovery_lineage.source_skill: find-leads | find-funded-founders | competitor-customers | research-prospect | manual` — the canonical enum per ADR-0032 D142. Today: NOT stamped on existing Persons (the per-skill stamping refactor lands Week 9-11 per ADR-0036+). D162 reads the EXISTING `source_channel` legacy field as a fallback (per `enrolled` event's existing `source` field name; per `find-leads/SKILL.md` Phase 4.5 enrollment template). The fallback normalizes `source_channel: "funded-founders"` → `source_skill: "find-funded-founders"` (the prefix differs because the legacy field omits the `find-` prefix on `find-funded-founders`).

**Find-funded-founders-specific signals (read from Person frontmatter):**
- `round_stage: pre-seed | seed | Series A | unknown` — populated per `find-funded-founders/SKILL.md`. Folds into `funding_stage` when the canonical field is absent.
- `round_size_usd: <number>` — populated per the same skill. Today: not consulted by the v1 weights config (the weights aggregate by `funding_stage` bucket, not by raw size); future weights MAY add a per-size weight surface if operator demand crystallizes.
- `funding_date: <YYYY-MM-DD>` — populated per the same skill. The "recent funding" intent signal — D162's v1 weights treat any `funding_date` within the last 90 days as a recency boost (operator-tunable per the weights config); future weeks MAY refine the recency window.

**Partial-signal graceful degradation (the load-bearing contract):**

If a Person's frontmatter lacks Apollo firmographic signals (`organization_size`, `industry`, `funding_stage`) — the common case today — the primitive computes the tier suggestion from the available signals (intent + find-funded-founders-specific) + emits the `tier_suggested` event with:
- `suggested_tier: B` (the default-low tier — operator-tunable per the weights config's `thresholds:`)
- `signals_consulted: { ... with None values for missing signals ... }` — operator-visible coverage
- `rationale: "Limited firmographic signals (organization_size/industry/funding_stage absent); intent signals only → low-confidence B tier"` — operator-readable

The primitive MUST NOT raise on missing signals; the primitive MUST NOT default to `"S"` when signals are absent (the asymmetric-failure-cost calculus per PILLAR-PLAN §0 favors "low-default when uncertain" — a false-positive S tier wastes operator review time on a tier-B prospect; a false-negative B tier surfaces the suggestion for operator manual review where the operator can stamp the actual tier).

**The partial-signal degradation IS the operator-visible signal for Pillar I doctor preflight:** a future Pillar I doctor extension may aggregate `tier_suggested` events by `signals_consulted` coverage and surface "your tier suggestions are 80% limited by absent organization_size — prioritize Apollo enrichment integration." The structural defense is built-in from v1.

**Why frontmatter-direct read (rejected: shell to Apollo MCP per call; rejected: require ALL signals before computing; rejected: LLM-based signal extraction).** Four plausible signal-source postures:

* **(a) Read directly from Person frontmatter** (D162's choice). Deterministic + zero per-call cost + works with existing pre-Pillar-E Person notes + gracefully degrades when signals are absent. The signal coverage is operator-visible via `signals_consulted` on every event.
* **(b) Shell to Apollo MCP per `compute_tier_from_signals` call** — REJECTED. Per-call cost ($0.005-0.01/Apollo enrichment) compounds at suggestion volume (~500 Persons today; ~10K Persons at scale = $50-100 per full-corpus retier). The cost-avoidance invariant per ADR-0032 D143 + D144 forbids this (the tier primitive is a Pillar E "reduce credit burn" primitive — adding per-call enrichment cost contradicts the pillar's purpose). The deferred path: when discovery skills auto-stamp Apollo enrichment into Person notes (Pillar I or beyond), the tier primitive reads those stamped values directly — zero per-call cost.
* **(c) Require ALL signals before computing** — REJECTED. Refuses-loud when partial; operator-hostile (most Persons today have partial enrichment; the primitive would default-refuse for ~95% of the corpus). The graceful-degradation contract (D162) makes the primitive useful from day one with whatever signals the operator's corpus has accumulated.
* **(d) LLM-based signal extraction from Person note body text** — REJECTED. Per ADR-0032 D145-Alt2 already rejected at the foundation level: LLM-based tier assignment is non-deterministic + unbounded cost. Extending the LLM rejection to signal extraction inherits the same rationale. The deterministic per-signal weight computation is the v1 contract; future weeks MAY add an LLM-explainer for the `rationale` field (TBD) but the SUGGESTION must remain deterministic for operator audit + binding-test reproducibility.

**Pin:** `tests/test_tier_assignment.py::TestComputeTierFromSignals::*` cover the signal-source contract per signal (per-firmographic-signal happy paths × 6; partial-signal degradation × 4; find-funded-founders-specific fallback × 3; legacy `source_channel` fallback × 2).

### D163. Per-signal weights config shape — YAML-tunable per `config-template/tier_weights.example.yml`

The per-signal weights are configured via a YAML file. The default template ships at `config-template/tier_weights.example.yml`; operators copy to `~/.outreach-factory/tier_weights.yml` and tune as their corpus grows. The default weights are calibrated against Yang's available operator-tagged corpus at Week 6-8 ship time (~500 Persons); the §Existing-operator seed names the confidence-interval limitation + the future re-calibration trajectory.

**The weights config shape:**

```yaml
# Tier auto-assignment weights — Pillar E Week 6-8 per ADR-0035.
# Operator tunes weights as their corpus grows; defaults are
# calibrated against Yang's ~500 Person operator-tagged corpus
# at Week 6-8 ship time. See ADR-0035 D163 for the rationale.
#
# Tier suggestion algorithm:
#   1. For each signal present on the Person frontmatter, add the
#      corresponding weight to a running score.
#   2. Compare the score against the thresholds (highest match wins).
#   3. Emit a tier_suggested event with the matched tier + the
#      operator-readable rationale.
#
# Signals absent from the Person frontmatter contribute ZERO to the
# score (NOT a negative weight — absence is observed, not penalized).
# The default-low tier B is the floor when signals are insufficient.

signals:
  organization_size:
    small: 0      # <50 employees — neutral
    mid: 1        # 50-500 — slight boost (typical decision-maker org)
    large: -1     # >500 — slight penalty (lower acquisition velocity)

  industry:
    ai_ml: 2      # high-fit (Aiyara's wedge — AI agent monitoring)
    saas: 1       # adjacent-fit
    dev_tools: 1  # adjacent-fit
    fintech: 0    # neutral
    other: 0      # default

  funding_stage:
    pre_seed: 1   # early-stage; budget-constrained but high-intent
    seed: 2       # high-fit (post-seed agents have agent-failure pain)
    series_a: 2   # peak-fit (Series A AI startups are buying agent infra)
    series_b: 1   # slightly past peak; some agent maturity
    series_c_plus: 0  # later-stage; agent-failure pain is less acute

  source_skill:
    find-funded-founders: 2  # high-intent (recent funding signal)
    competitor-customers: 2  # high-precision (proven agent operators)
    find-leads: 0            # neutral (ICP-fit but no intent signal beyond)
    research-prospect: 0     # neutral (deepens an existing prospect)
    manual: 0                # neutral (operator-curated)

  funding_recency_days:
    # If funding_date is within N days, add the corresponding weight.
    # Operator-tunable per market velocity.
    90: 1         # within last 90 days = boost

thresholds:
  # Tier emitted = highest threshold the score >=
  # The thresholds are operator-tunable; the default biases toward
  # the operator-friendly "low-default when uncertain" posture.
  S: 4          # score >= 4 → tier S
  A: 2          # score >= 2 → tier A
  # else → tier B (the default-low when signals are insufficient)
```

**Why YAML config (rejected: hardcoded; rejected: ML-trained file; rejected: per-tenant override at v1).** Four plausible weight-storage postures:

* **(a) YAML config at `~/.outreach-factory/tier_weights.yml`** (D163's choice). Operator-tunable per Yang's growing corpus. Default template ships under version control at `config-template/tier_weights.example.yml`; the operator's actual config is operator-private (not version-controlled — same posture as `cooldowns.yml` + other operator-tunable policy YAML). Mirrors the existing operator-tunable config conventions per ADR-0001 + ADR-0002 + ADR-0005 + ADR-0006 + ADR-0007.
* **(b) Hardcoded in `tier_assignment.py`** — REJECTED. Operator changes require code edit; the operator-tuning surface is the whole point of D163 (weights are calibrated against the operator's specific corpus + ICP; future re-calibration as the corpus grows). A hardcoded surface would freeze the weights at the framework author's choice; an operator with a different ICP (e.g., enterprise SaaS instead of AI startups) would need to fork the framework.
* **(c) ML-trained weights file** — REJECTED. Over-engineered for v1 ~500 Person corpus + requires ML stack (sklearn / scikit / torch); the operator-tunable rule-based approach IS the v1 ground truth. The default weights ARE calibrated against Yang's hand-tagged corpus (which IS the ground truth at Week 6-8 ship time); future Pillar I or G weeks may add an ML-trained version IF the operator's corpus crosses 10K+ Persons with sufficient class balance — TBD.
* **(d) Per-tenant override at v1** — REJECTED. Multi-tenant configuration is a Pillar I concern (per PILLAR-PLAN §6 Pillar I — OSS hardening + multi-tenant); ADR-0001's per-operator config posture is single-tenant at v1. The per-tenant override surface resurfaces when Pillar I lands.

**The weights config is operator-private per ADR-0001 + ADR-0032 D148 posture.** The YAML file lives in the operator's home directory (`~/.outreach-factory/tier_weights.yml`); the framework treats the file as an opaque string-keyed dict. The default template ships in version control; the operator's actual config is operator-private (not surfaced in Pillar G dashboards; not committed to the framework repo).

**Pin:** `tests/test_tier_assignment.py::TestWeightsConfig::*` cover the weights-loading contract (default-template load × 1; operator-override-via-kwarg × 1; weights-config-malformed → fail-loud × 1; threshold-tie-breaking × 1).

### D164. Per-Person-invocation integration — operator-invoked CLI for v1

The tier primitive's integration is OPERATOR-INVOKED via a new CLI subcommand. The primitive is NOT auto-invoked on every `enroll_person` write at v1 — the auto-invocation surface preserves the OPERATOR-CONTROL property per ADR-0032 D145 ("the operator decides which Persons to retier").

**CLI surface:**

```bash
python orchestrator/tier_assignment.py suggest \
  --person <person-id> \
  [--weights-path <path>] \
  [--apply] \
  [--json]
```

**Behavior:**

* `--person <id>` — required; the Person's `person_id` (the LinkedIn-derived slug or the operator-stamped identifier).
* `--weights-path <path>` — optional; defaults to `~/.outreach-factory/tier_weights.yml`. When the path doesn't exist, the primitive loads the default-shipped template + emits a stderr warning ("operator-tuned weights not found at <path>; falling back to default template at config-template/tier_weights.example.yml").
* `--apply` — emits the `tier_suggested` event to the ledger. Default is dry-run (report only). Mirrors `discovery_dedup.py` + `email_verification_cache.py` CLI conventions.
* `--json` — JSON output. Default is human-readable.

**Operator-invocation discipline (the load-bearing contract):**

The primitive is OPERATOR-INVOKED per CLI. Operators iterating on the queue + retiering a specific cohort invoke per-Person:

```bash
# Operator retiers a cohort of newly-discovered prospects:
for pid in $(python -m orchestrator.ledger grep --type enrolled --since 2026-05-20 \
              | jq -r '.[].person_id'); do
  python orchestrator/tier_assignment.py suggest --person "$pid" --apply --json
done
```

Auto-invocation on every `enroll_person` write is DEFERRED to Pillar I OR a future Pillar E week IF operator demand materializes. The deferral rationale:

* **Auto-invocation would compound event volume.** Every enrollment emits one `tier_suggested` event; operators iterating on a 100-prospect cohort see 100 suggestions; operators reviewing the cohort via the Person notes see N suggestion events per N enrollments. The operator-invoked surface gives operators control over the event volume.
* **Auto-invocation would couple the tier-suggestion behavior to the enrollment site.** Pillar E's design principle (per ADR-0032 D145) is "the operator decides which Persons to retier"; auto-invocation would shift the decision to the framework. The future auto-invocation surface (if ever shipped) MUST be opt-in (a `--auto-tier` flag on `enroll_person` OR a daemon config flag).
* **The operator-invocation surface IS the per-Person retier path.** Operators wanting to retier a specific cohort (e.g., after updating the weights config) shell to the CLI per-Person; the per-Person grain is the right operator surface (not "retier every Person in the vault" — that would emit thousands of events).

**Why operator-invoked CLI (rejected: auto-invoke on every enrollment; rejected: wrap inside `enrollment.py::enroll_person`; rejected: new reconcile pass).** Four plausible integration shapes:

* **(a) Operator-invoked CLI** (D164's choice — inherits ADR-0032 D145's operator-control posture). Operator decides which Persons to retier; the per-Person invocation grain matches the operator's mental model.
* **(b) Auto-invocation on every `enroll_person` write** — REJECTED. Event volume compounds; couples observational primitive to enrollment-as-state-mutation; loses operator-control. The deferred surface (if ever shipped) MUST be opt-in.
* **(c) Wrap inside `enrollment.py::enroll_person` (cache-like wrap)** — REJECTED. The cache primitive's wrap-at-call-site (per ADR-0034 D158) is appropriate for cache-as-prevention (the cache short-circuits the Reoon call; the wrap is the natural integration point). The tier primitive is OBSERVATIONAL (it emits a suggestion event; it does NOT short-circuit any downstream call); the wrap-at-call-site shape would couple the tier surface to enrollment lifecycle — the rejected D164-Alt1 rationale applies.
* **(d) New reconcile pass (e.g., `Pass T` for tier-suggestion)** — REJECTED. Wrong cadence. Reconcile passes are POSTHOC state-healing operations (run periodically; catch drift); tier suggestion is per-Person + operator-invoked. A reconcile pass for tier-suggestion would run on every reconcile invocation + emit suggestions for every Person — exactly the event-volume compounding the rejected D164-Alt1 path warns against.

**Pin:** `tests/test_tier_assignment.py::TestCLI::*` cover the CLI's behavior (dry-run default × 1; `--apply` emits event × 1; `--weights-path` operator override × 1; `--json` shape × 1; missing weights file fallback × 1).

### D165. Cross-pillar audit row extension — `.planning/REVIEW-pillar-e-surface-audit.md`

Per ADR-0032 D146 the cross-pillar surface audit is the load-bearing anti-regression artifact. The Week 6-8 commit extends `.planning/REVIEW-pillar-e-surface-audit.md` with a new section walking the `tier_suggested` event class's consumer surface. Per consumer:

1. **`_idx_person`** — `tier_suggested` events carry `person_id` (always populated per D161); tier-suggestion events DO land in the per-Person index. Every existing consumer (the Pillar A/B/C/D + Pillar E Week 2 + Week 4-5 enumeration from prior audits) is closed-set-protected or by-design-broadening:
   * `derived_stage` — closed dispatch table `_STAGE_BY_EVENT_TYPE`; the new event type is absent → **closed-set-protected, by-design**.
   * `reachable_pipeline_stages` — same dispatch table → **closed-set-protected**.
   * `derived_conversation_status` — literal-string filter on REPLY_EVENT_TYPES + suppression + state-change events → **closed-set-protected**.
   * `derived_conversation_outcome` — `type == "conversation_outcome"` filter → **closed-set-protected**.
   * `CrossChannelTouchRule.evaluate` — `endswith("_confirmed")` predicate → the new type does NOT match → **literal-string-filtered, by-design**.
   * `BudgetWindowCapRule.evaluate` — `type == "cost_incurred"` filter → tier_suggested events are NOT cost_incurred → **literal-string-filtered**.
   * `CooldownRule._confirmed_send_intent_pairs` — `type in {"send_intent", "send_confirmed"}` → **literal-string-filtered**.
   * `DomainThrottleRule.evaluate` — `type != "send_confirmed"` → tier_suggested events don't match the loop guard → **literal-string-filtered**.
   * `Ledger.last_send_for` — `_INTENT_TYPES + _OUTCOME_TYPES` → tier_suggested events absent → **closed-set-protected**.
   * Pass G's reply classifier idempotence index — `REPLY_EVENT_TYPES` filter → tier_suggested events absent → **closed-set-protected**.
   * Pass M's auto-unsubscribe — `category=unsubscribe` filter → tier_suggested events absent → **closed-set-protected**.
   * Pass N's conversation state machine — reply + classified + suppression + state-change filter → tier_suggested events absent → **closed-set-protected**.
   * Pass O's conversation outcome — `*_confirmed` filter → tier_suggested events absent → **closed-set-protected**.
   * Pillar D funnel CLI (`orchestrator/funnel.py::build_report`) — `reply_classified` + `conversation_outcome` filter → tier_suggested events absent → **closed-set-protected**.

2. **The existing `policy/tier.py::TierRequiresTierInRule` is UNCHANGED.** The rule reads operator-stamped `Person.research_tier` via `ctx.tier` (per `policy/__main__.py:404` + `vault.py:197`). The tier-suggestion primitive emits events; the rule consumes the operator-stamped field. The three-step decoupling per ADR-0032 D145 IS the contract: SUPPLY (auto-assignment) → STAMP (operator) → READ (rule). Verdict: **rule behavior UNCHANGED; the auto-assignment is observational only**.

3. **The `manual_override` event class (ADR-0007) is UNCHANGED.** Operators disagreeing with the auto-assignment continue to emit `manual_override` events per the existing path (`policy/__main__.py:639`). The tier primitive does NOT emit `manual_override` events; the two event classes are independent surfaces. A future operator workflow: (a) auto-assignment emits `tier_suggested: S` for Person X; (b) operator disagrees, stamps `research_tier: A` on Person X's frontmatter (the SoT); (c) IF the operator wants to record the disagreement for audit, the existing `python -m orchestrator.policy override` CLI emits a `manual_override` event. The disagreement is operator-deliberate; the framework does NOT auto-emit overrides.

4. **`tier_suggested` SIBLING of `discovery_dedup_hit` + `email_verification_cache_hit`** — all three event classes are Pillar E primitives' observational signals. The three are structurally analogous:

   | Field | `discovery_dedup_hit` (Week 2) | `email_verification_cache_hit` (Week 4-5) | `tier_suggested` (Week 6-8) |
   |---|---|---|---|
   | `type` | `"discovery_dedup_hit"` | `"email_verification_cache_hit"` | `"tier_suggested"` |
   | `person_id` | YES (existing match's id) | YES (cached event's person_id, defaulting) | YES (the suggested Person's id) |
   | `channel` | `"none"` (channel-agnostic) | `"email"` (email-specific) | `"none"` (channel-agnostic) |
   | `_emitted_by` | `"discovery_dedup"` | `"email_verification_cache"` | `"tier_assignment"` |
   | source attribution | `source_skill` + `source_list` | NONE (cache is operator-invocation-agnostic) | NONE (suggestion is operator-invocation-agnostic) |
   | content-payload | `candidate_partial` + `matched_classes` | `cached_result` + `cached_at` + `cache_age_days` | `suggested_tier` + `signals_consulted` + `rationale` |
   | purpose | pre-action cost-avoidance | pre-action cost-avoidance | observational tier-suggestion |
   | replaces what | enrichment call (skipped) | Reoon HTTP call (skipped) | NOTHING (purely observational) |

   **Audit verdict: structural symmetry — by-design.** The three event classes share the `_idx_person` + `channel` + `_emitted_by` shape per the Pillar E primitive convention; they differ in scope (dedup is identity-keyed; cache is email-keyed; tier is Person-id-keyed) + in purpose (cost-avoidance vs observational). The `tier_suggested` event's "replaces NOTHING" posture is operator-deliberate per ADR-0032 D145 — the auto-assignment SUPPLIES; the operator STAMPS.

**Categories the Pillar E Week N+ per-week reviewer must verify (extending the Week 1 + 2 + 3 + 4-5 baseline):**

* **Does Week 6-8 broaden `_idx_person`?** YES — `tier_suggested` carries `person_id` (always populated). Every consumer verified closed-set-protected or by-design-broadening in §1 above.
* **Does Week 6-8 add a new `*_confirmed`-suffixed event?** NO. `CrossChannelTouchRule` unaffected.
* **Does Week 6-8 add to `_STAGE_BY_EVENT_TYPE`?** NO. The tier suggestion is observational, not a pipeline-stage advancement.
* **Does Week 6-8 add a new per-prospect dedup-index pattern analogous to `_idx_gmail_msg`?** NO. The tier primitive uses Person frontmatter + the weights config; no new index pattern.
* **Does Week 6-8 modify `enrollment.py` or any pre-existing reconcile pass?** NO. The tier primitive lives in its own module (`orchestrator/tier_assignment.py`); no enrollment-site changes; no reconcile-pass changes.
* **Does Week 6-8 extend the `identity_keys:` schema?** NO. The tier primitive reads firmographic + intent signals from Person frontmatter; the `identity_keys:` block is unchanged.
* **Does Week 6-8 modify the existing `policy/tier.py::TierRequiresTierInRule`?** NO. The rule is unchanged; the auto-assignment SUPPLIES via events; the operator STAMPS via frontmatter; the rule READS via `ctx.tier` (unchanged). The three-step decoupling is preserved.
* **Does Week 6-8 surface `source_list` in any operator-facing dashboard, CLI, or aggregation surface?** NO. The tier primitive does not carry `source_list` (the tier signals are firmographic + intent — `source_skill` only, NEVER `source_list`). The Layer 1 D148 defense continues to pass.
* **Does Week 6-8 add a new operator-tunable YAML config?** YES — `tier_weights.yml` per D163. The default template ships at `config-template/tier_weights.example.yml`; the operator's actual config is operator-private (per ADR-0001 posture + per the existing `cooldowns.yml` precedent).
* **Does Week 6-8 introduce a weights-config-drift risk?** YES — R021 per §Context above. Mitigation by design: the per-signal weights are operator-tunable per a YAML config; the default template ships with explanatory comments; the rationale field on every event surfaces the decision tree for operator audit. Future Pillar I doctor preflight extension MAY add config-shape validation + drift detection.

**Pin:** `.planning/REVIEW-pillar-e-surface-audit.md` extended in this commit with the Week 6-8 section (§32+). Future Pillar E weeks consult the audit + extend it per the per-week-review-with-follow-up-commit discipline.

## Alternatives considered

### D160-Alt1: Place the tier primitive inside `orchestrator/policy/tier.py`

A new `compute_tier_from_signals` function alongside the existing `TierRequiresTierInRule` class. **Rejected** because:

* Conflates rule-consumer with substrate-supplier. `policy/tier.py` is the existing rule — its load-bearing export is the rule class that filters on operator-stamped `ctx.tier`. The auto-assignment SUPPLIES the suggestion; the rule CONSUMES the operator-stamped value; the three-step decoupling per ADR-0032 D145 (SUPPLY → STAMP → READ) is the contract.
* The Pillar E Week 2 + 4-5 precedent (D149 + D154) — sibling-of-existing-primitives placement preserves single-purpose modules. The dedup primitive is SIBLING of `enrollment.py` (the wrapped call site); the cache primitive is SIBLING of `enrich_emails.py` (the wrapped call site); the tier primitive should be SIBLING of `policy/tier.py` (the existing rule the SUPPLY/STAMP/READ decoupling preserves).
* Operators reading `policy/tier.py` see the rule's "block when not in allowed_tiers" behavior; introducing a `compute_tier_from_signals` function would force operators to reason about both surfaces in the same module — exactly the cognitive coupling the three-step decoupling prevents.

### D160-Alt2: Place the tier primitive inside `orchestrator/enrollment.py`

A new function `enrollment.compute_tier_from_signals` alongside `enroll_person`. **Rejected** because:

* Conflates substrate-supplier with Person-note loader. `enrollment.py` is the post-enrichment enrollment site — it writes Person notes + emits `enrolled` events. The tier primitive is READ-ONLY (it reads frontmatter signals + emits a suggestion event); merging the read-only suggestion into the write-side enrollment would bloat the module + tempt a future contributor to auto-invoke the suggestion on every enrollment (the rejected D164-Alt1 path).
* The cache primitive's wrap-at-call-site pattern (per ADR-0034 D154) places the primitive in its OWN module + wraps the existing call site via opt-in kwargs. The tier primitive follows the same shape — sibling module + opt-in CLI invocation (per D164).
* The Pillar D Week 2 D102 precedent — the classifier is a SIBLING of `reconcile.py`, not inside it. The same rationale applies here: the tier primitive is SIBLING of `enrollment.py`, not inside it.

### D160-Alt3: Spin up an `orchestrator/tier/` subpackage

`orchestrator/tier/__init__.py` + `orchestrator/tier/assignment.py` + future siblings (per-tenant overrides, industry-vertical schemes, etc.). **Rejected** as over-organization for Week 6-8's scope (~400 LOC of tier primitive + tests). The single-file convention used by `discovery_dedup.py` + `email_verification_cache.py` + `reply_classifier.py` + `enrollment.py` + `identity.py` is the precedent for Pillar primitives. The subpackage rationale resurfaces in a future Pillar E (or Pillar I) week IF a second tier primitive lands; until then, the top-level placement is the right grain.

### D160-Alt4: Place the tier primitive inside `orchestrator/identity.py`

A new function alongside `find_matches` + `resolve_strict`. **Rejected** because:

* Conflates tier-as-firmographic-signal with identity-as-key-resolution. `identity.py` is the strict-policy resolver — it intersects identity keys + refuses ambiguous matches. The tier primitive operates on firmographic signals (organization_size, industry, funding_stage), not identity keys.
* The two primitives have orthogonal substrates (identity-keys index vs Person frontmatter) + orthogonal purposes (key resolution vs tier suggestion). Co-location would dilute the single-purpose semantics of `identity.py`.
* `IdentityKeys` is the closest type adjacency, but the tier primitive does NOT consult identity keys at all — it consults Person frontmatter for signals.

### D161-Alt1: Stamp `channel: "all"` instead of `"none"`

Mark the tier suggestion as applicable to all channels. **Rejected** because:

* Semantic mismatch — `"all"` implies "every channel triggered" which is operator-confusing for a tier suggestion (which doesn't trigger anything on any channel). Pillar G dashboards filtering "show me email-channel events" would surface tier suggestions in the email funnel — wrong attribution.
* The `"none"` value is the precedent established by the dedup primitive per ADR-0033 D150. Consistency with prior primitives.
* The "tier is channel-agnostic" semantics is operator-deliberate — operators reading per-channel dashboards see the absence of tier suggestions in the channel funnels as a signal that tier is a cross-channel concern.

### D161-Alt2: Omit the `channel` field entirely on tier_suggested events

The tier suggestion is channel-agnostic by definition; the field is superfluous. **Rejected** because:

* Violates ADR-0014 D33 + ADR-0032 D146's channel-on-every-event invariant. Pillar G dashboards filtering by channel must see every event class with the field (per the invariant's "every event carries the field" rule).
* The dedup primitive (per ADR-0033 D150) explicitly stamps `channel: "none"` to preserve the invariant; the cache primitive (per ADR-0034 D155) stamps `channel: "email"`; the tier primitive (per D161) stamps `channel: "none"` — omission would be a regression of the discipline.
* Per-event-class special cases in the dashboard layer (handle tier suggestions separately from other events) is exactly what the channel-on-every-event invariant prevents.

### D161-Alt3: Stamp the operator-readable rationale as a structured dict (not a string)

Instead of `rationale: "Recent Series A + AI/ML industry → S tier"`, ship `rationale: {signals_matched: ["funding_stage=series_a", "industry=ai_ml"], conclusion: "high-intent S tier"}`. **Rejected** because:

* The dict shape duplicates information already in `signals_consulted` (the structured field). The string IS the operator-readable summary; the dict would force operators to reconstruct the summary themselves.
* Pillar G dashboards aggregating by tier suggestion category can pattern-match the string (e.g., `rationale ~ /high-intent/`) for category-level aggregation; a structured dict would require dashboard authors to traverse the dict for the same query.
* The single-string rationale matches the `discovery_dedup_conflict` event's `report_path` field shape (per ADR-0033 D151) — a single operator-readable identifier + the structured fields adjacent to it. Consistency with prior event-shape conventions.

### D161-Alt4: Co-emit `manual_override` whenever the auto-assignment runs

Always emit both `tier_suggested` + a corresponding `manual_override` event so the operator's "I accept the suggestion" is implicit. **Rejected with high prejudice** because:

* Conflates suggestion with override. Per ADR-0007 the `manual_override` event is the OPERATOR's explicit action ("I am overriding the framework's default"); the auto-assignment is OBSERVATIONAL ("the framework suggests X"). Co-emission would falsely surface every suggestion as an "operator approved" event.
* Pillar G dashboards consume `manual_override` events to compute operator-deliberate intervention rates; co-emission would inflate the operator-override count to ~100% (every auto-assignment = one fake override) — operator-confusing.
* The three-step decoupling per ADR-0032 D145 IS the contract: SUPPLY (auto-assignment via `tier_suggested`) → STAMP (operator via frontmatter) → READ (rule via `ctx.tier`). The operator's explicit override path (via `python -m orchestrator.policy override`) is independent of the suggestion path.

### D162-Alt1: Shell to Apollo MCP per `compute_tier_from_signals` call

The primitive calls the Apollo MCP for each Person to fetch fresh firmographic data. **Rejected** because:

* Per-call cost ($0.005-0.01/Apollo enrichment) compounds at suggestion volume (~500 Persons today; ~10K Persons at scale = $50-100 per full-corpus retier). The cost-avoidance invariant per ADR-0032 D143 + D144 forbids this — the tier primitive is a Pillar E "reduce credit burn" primitive; adding per-call enrichment cost contradicts the pillar's purpose.
* Non-deterministic — the Apollo MCP's response may change over time (firmographic data updates); the binding-test reproducibility per ADR-0013 D24 requires deterministic computation. The frontmatter-direct read produces the same suggestion every call against the same Person; Apollo-per-call would not.
* The deferred path: when discovery skills auto-stamp Apollo enrichment into Person notes (Pillar I or beyond), the tier primitive reads those stamped values directly — zero per-call cost + deterministic.

### D162-Alt2: Require ALL firmographic signals before computing

The primitive refuses to compute when any of `organization_size`/`industry`/`funding_stage` is absent. **Rejected** because:

* Refuses-loud when partial; operator-hostile. Most Persons today have partial enrichment (Apollo is not auto-populated); the primitive would default-refuse for ~95% of the corpus. The graceful-degradation contract (D162) makes the primitive useful from day one with whatever signals the operator's corpus has accumulated.
* The asymmetric-failure-cost calculus per PILLAR-PLAN §0 favors "low-default when uncertain" over "refuse-loud when uncertain" — a default-low B tier surfaces the suggestion for operator review where the operator can stamp the actual tier; a refusal yields no signal at all + no operator-visible diagnostic.
* The `signals_consulted` field's `None` values for missing signals IS the operator-visible diagnostic — operators see which signals are absent + can prioritize future enrichment integration.

### D162-Alt3: LLM-based signal extraction from Person note body text

Use an LLM to extract firmographic signals from the Person note's body (e.g., "Series A funded in 2024" → `funding_stage: series_a`). **Rejected** because:

* Per ADR-0032 D145-Alt2 already rejected at the foundation level: LLM-based tier assignment is non-deterministic + unbounded cost. The same rejection rationale extends to LLM-based signal extraction.
* The deterministic per-signal weight computation is the v1 contract; future weeks MAY add an LLM-explainer for the `rationale` field (TBD) but the SUGGESTION must remain deterministic for operator audit + binding-test reproducibility.
* The forward-reference for Apollo enrichment integration (Pillar I or beyond) provides the deterministic firmographic signals; an LLM-based extraction would be a stop-gap that compounds technical debt.

### D162-Alt4: Default to tier S when signals are missing (operator-friendly default)

The primitive defaults to `suggested_tier: S` when signals are absent — "if we don't know, assume high-priority." **Rejected** because:

* The asymmetric-failure-cost calculus per PILLAR-PLAN §0 inverts: a false-positive S tier wastes operator review time on a tier-B prospect (operator spends 30 minutes researching a low-fit prospect); a false-negative B tier surfaces the suggestion for operator review where the operator can stamp the actual tier (operator spends 5 minutes confirming).
* Defaulting to S would surface ALL prospects with absent signals as high-priority — exactly the "operator drowning in low-tier prospects" failure mode the tier-rule per ADR-0007 was designed to prevent.
* The default-low B tier per D162 is operator-deliberate — surfaces the suggestion as "needs review" for operator follow-up.

### D163-Alt1: Hardcode the weights in `tier_assignment.py`

Pin the weights as constants in the Python module; operators wanting to tune must fork the framework. **Rejected** because:

* Operator changes require code edit; the operator-tuning surface is the whole point of D163 (weights are calibrated against the operator's specific corpus + ICP).
* An operator with a different ICP (e.g., enterprise SaaS instead of AI startups) would need to fork the framework to retune; the OSS sustainability per PILLAR-PLAN §6 Pillar I requires per-operator weight tuning at the config layer.
* The existing operator-tunable YAML conventions (per ADR-0001 + ADR-0002 + ADR-0005 + ADR-0006 + ADR-0007) all live in `~/.outreach-factory/`; the tier weights follow the same shape.

### D163-Alt2: ML-trained weights file (sklearn-shaped per-signal coefficients)

Replace the YAML config with an ML-trained model (sklearn / scikit / torch). **Rejected** because:

* Over-engineered for v1 ~500 Person corpus + requires ML stack. The operator-tunable rule-based approach IS the v1 ground truth.
* The default weights ARE calibrated against Yang's hand-tagged corpus (which IS the ground truth at Week 6-8 ship time); future Pillar I or G weeks may add an ML-trained version IF the operator's corpus crosses 10K+ Persons with sufficient class balance — TBD.
* The ML-trained surface would non-determinize the suggestion (model outputs depend on training-set order, random initialization, etc.) — incompatible with the binding-test reproducibility requirement per ADR-0013 D24.

### D163-Alt3: Per-tenant override at v1

Multi-tenant configuration — each tenant gets their own `tier_weights.yml` at `~/.outreach-factory/<tenant>/tier_weights.yml`. **Rejected** because:

* Multi-tenant configuration is a Pillar I concern (per PILLAR-PLAN §6 Pillar I — OSS hardening + multi-tenant); ADR-0001's per-operator config posture is single-tenant at v1.
* The per-tenant override surface resurfaces when Pillar I lands; v1 ships single-tenant.
* The existing per-operator YAML conventions (cooldowns.yml, etc.) are single-tenant; the tier weights follow the same shape.

### D163-Alt4: Inline weights in `tier_weights.example.yml` (no separate `~/.outreach-factory/tier_weights.yml`)

Ship the template directly; operators edit the in-repo file. **Rejected** because:

* The in-repo edits would conflict with framework updates (every `git pull` would prompt a merge conflict for operators who tuned the weights).
* The operator-private config posture (per ADR-0001) keeps operator-specific values out of the framework repo; the tier weights inherit this posture.
* The default template + operator copy + operator-tune workflow matches every other operator-tunable YAML config in the framework (cooldowns.yml, suppressions.yml, etc.).

### D164-Alt1: Auto-invoke `compute_tier_from_signals` on every `enroll_person` write

Wrap the call inside `enrollment.enroll_person`; every enrollment emits a `tier_suggested` event. **Rejected** because:

* Event volume compounds — every enrollment emits one `tier_suggested` event; operators iterating on a 100-prospect cohort see 100 suggestions; operators reviewing the cohort via the Person notes see N suggestion events per N enrollments. The operator-invoked surface gives operators control over the event volume.
* Couples observational primitive to enrollment-as-state-mutation; loses operator-control per ADR-0032 D145.
* The future auto-invocation surface (if ever shipped) MUST be opt-in (a `--auto-tier` flag on `enroll_person` OR a daemon config flag) — Week 6-8 ships the operator-invoked CLI; auto-invocation is a Pillar I or future Pillar E concern.

### D164-Alt2: New reconcile pass (`Pass T` for tier-suggestion)

Add a reconcile pass that runs periodically + emits `tier_suggested` for every Person whose suggestion has drifted from the operator-stamped value. **Rejected** because:

* Wrong cadence. Reconcile passes are POSTHOC state-healing operations (run periodically; catch drift); tier suggestion is per-Person + operator-invoked.
* A reconcile pass for tier-suggestion would run on every reconcile invocation + emit suggestions for every Person — exactly the event-volume compounding the rejected D164-Alt1 path warns against.
* Operators wanting to retier a specific cohort have the CLI per-Person; a reconcile pass would scatter the operator's intent across thousands of suggestions.

### D164-Alt3: Wrap inside the existing `policy/__main__.py override` CLI

Extend the override CLI with a `--suggest` flag that runs the auto-assignment + writes the suggestion as a `manual_override` event. **Rejected** because:

* Conflates suggestion with override. Per D161-Alt4's same rationale — the auto-assignment is OBSERVATIONAL ("the framework suggests X"); the `manual_override` event is the OPERATOR's explicit action ("I am overriding the framework's default"). Co-located on the same CLI would tempt operators to confuse the two.
* The tier-suggestion primitive's CLI follows the per-primitive convention (`discovery_dedup.py check`, `email_verification_cache.py lookup`, `tier_assignment.py suggest`) — sibling CLIs for sibling primitives.
* The existing override CLI is the operator-deliberate disagreement path; the tier-suggestion CLI is the framework-supplied baseline. Keeping them separate preserves the three-step decoupling.

### D165-Alt1: Spawn a code-reviewer agent for the audit extension

Use the `code-reviewer` agent type for a fresh-context audit. **Rejected for Week 6-8** mirroring ADR-0032 D146-Alt1 + ADR-0033 D153-Alt1 + ADR-0034 D159-Alt1's reasoning: the audit IS the load-bearing artifact + benefits from sharing context with the ADR's author. Pillar E Week 6-8's per-week independent reviewer (spawned post-commit per the standing convention) WILL re-audit the surfaces from a fresh-context perspective; the inline audit + the per-week-review audit are complementary.

### D165-Alt2: Skip the audit extension; rely on per-week reviews to catch broadening surfaces

Pillars A + B all relied on per-week reviews. **Rejected** mirroring ADR-0032 D146-Alt2 + ADR-0033 D153-Alt2 + ADR-0034 D159-Alt2's reasoning: the per-week reviewer's threshold for "ship-stopping" is biased toward "defer to holistic" for pre-existing surfaces. The audit IS the structural intervention against the Pass-A-class pattern; future Pillar E weeks' per-week reviewers consult the audit as the surface map + extend it; the discipline compounds.

### D165-Alt3: Defer the audit extension to a Week 6-8 follow-up commit

Ship the tier primitive + integration in the main commit; ship the audit extension in a follow-up. **Rejected** mirroring ADR-0033 D153-Alt3 + ADR-0034 D159-Alt3's reasoning: the audit extension IS part of the Week 6-8 deliverable per HANDOFF-pillar-e-week-6.md §"Validation gate". Splitting the commit risks the audit landing days/weeks after the code change it documents — exactly the gap the audit discipline is designed to prevent.

## Consequences

### Positive

- **The tier primitive MODULE is a clean Pillar E primitive.** Future Pillar E weeks (Week 9-11 per-skill `discovery_lineage:` stamping refactor) extend the discovery-primitive surface without churning the tier module. The three Pillar E primitives (dedup, cache, tier) are sibling modules with consistent shape — operator cognitive load stays low.
- **The `tier_suggested` event class makes the auto-assignment operator-visible.** Pillar G's per-tier-suggestion-rate dashboard reads these directly: "this week the framework suggested S for 12 prospects (you stamped A for 3 of them; the framework's recall on S vs your stamping is 75%)" — useful for tuning the weights.
- **The cross-pillar surface audit (D165) continues the ADR-0032 D146 + ADR-0033 D153 + ADR-0034 D159 discipline.** Every new event class extends the audit; the audit grows with the pillar; the Pass-A-class latent-bug pattern is foreclosed by construction.
- **The three-step decoupling per ADR-0032 D145 is preserved.** SUPPLY (auto-assignment) → STAMP (operator) → READ (rule) is the contract; the tier primitive supplies events; the operator stamps frontmatter; Pillar A's existing rule reads `ctx.tier` (unchanged).
- **The graceful-degradation contract per D162 makes the primitive useful from day one.** Operators with pre-existing Person notes (with partial enrichment) get tier suggestions immediately; the `signals_consulted` field surfaces signal coverage for future enrichment prioritization.
- **The exit-criterion vehicle's Week 6-8 rows un-skip + pin the contract.** All 3 `TestTierAutoAssignment` rows pass; the cross-pillar coherence is locked in.
- **The Pillar A I1 invariant (single source of truth) is preserved.** The ledger remains the SoT for events; the operator-stamped `Person.research_tier` field remains the SoT for the actual tier value; the tier primitive supplies observational events; no new SoT introduced.
- **The operator-tunable weights config (D163) lets operators calibrate against their specific corpus + ICP.** The default-shipped template is Yang-tuned; future operators with different ICPs (enterprise SaaS, fintech, etc.) tune the YAML for their use case without forking the framework.

### Negative

- **The default-shipped weights are calibrated against Yang's ~500 Person corpus.** Confidence intervals are limited at this corpus size. **Mitigation:** the §Existing-operator seed names the limitation explicitly; operators with their own corpora tune the weights as their data grows; the operator-tunable surface IS the path to operator-specific accuracy.
- **The tier primitive depends on Person frontmatter signals that are typically absent today (Apollo `organization_size`, `industry`, `funding_stage`).** Most Week 6-8 suggestions will be the default-low B tier with "limited firmographic signals" rationale. **Mitigation:** the graceful-degradation contract per D162 makes the primitive functional with whatever signals exist; the `signals_consulted` field surfaces coverage for operator audit; future Apollo enrichment integration (Pillar I or beyond) expands the signal coverage organically.
- **The operator-invoked CLI requires operator action per Person.** Operators retiering a large cohort must script the per-Person invocation. **Mitigation:** the operator-invoked surface is the v1 contract per ADR-0032 D145 (the operator decides which Persons to retier); future auto-invocation (if shipped) MUST be opt-in. The CLI surface mirrors `discovery_dedup.py` + `email_verification_cache.py` conventions — operator-readable + scriptable.
- **The weights config drift risk (R021) is operator-private.** An operator-tuned config that diverges from the default may surface tier suggestions that conflict with the operator's actual SoT corpus. **Mitigation:** the rationale field on every event surfaces the decision tree for operator audit; the per-week reviewer's category #5 pins this as a category; future Pillar I doctor preflight extension MAY add config-shape validation + drift detection.
- **The `tier_suggested` event is emit-only in Week 6-8 — no downstream consumer yet.** Pillar G dashboards land Weeks 31-42; until then, operators query via `python -m orchestrator.ledger grep --type tier_suggested`. **Mitigation:** the operator-visible surface is the ledger grep + the CLI's `--json` output. Operators can shell to `jq` for ad-hoc aggregation.
- **The tier primitive does NOT consume the cache primitive's per-email metadata (e.g., `is_role_account` from cached Reoon responses).** ADR-0034 §References forward-referenced this as a possible signal source; D162 does NOT include it at v1 (the cache primitive's response shape varies by Reoon version; coupling tier suggestion to cache hit shape would create a brittle dependency). **Mitigation:** future weeks MAY extend the weights config with cache-derived signals IF operator demand crystallizes; the current shape's signal sources are deliberately frontmatter-direct.

### Neutral / observability

- The `tier_suggested` events are queryable via the existing `query_by_person` + filter-by-type pattern. Pillar G's per-tier-suggestion-rate dashboard reads these directly.
- The `_emitted_by: "tier_assignment"` marker (per ADR-0010 D17 convention) lets operators filter tier-primitive output from other event sources in funnel queries.
- The `signals_consulted` field's `None` values for missing signals surfaces "what's the framework not seeing?" — useful for operator audit + future enrichment prioritization.
- The `rationale` field's operator-readable string composition surfaces "why did the framework pick this tier?" — useful for operator audit + weights calibration.
- No new SoT introduced (per I1 invariant). The tier primitive emits events; the operator-stamped `Person.research_tier` field remains the SoT for the actual tier value; the ledger remains the SoT for events. No new files, no new vault state, no auxiliary cache.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT row added. The tier primitive emits events to the ledger (existing SoT for events); the operator-stamped `Person.research_tier` field remains the SoT for the actual tier value (per ADR-0007's existing convention). The `~/.outreach-factory/tier_weights.yml` config is operator-private + tunable (per the existing operator-config convention — `cooldowns.yml` precedent). I1 holds.
- **I2 (two-phase commit on every external side effect):** The tier primitive is a pure FRAMEWORK operation (Person-frontmatter read + ledger append). No external side effects; no I2 contract change.
- **I3 (schema versioning):** The `tier_suggested` event carries `v: 1` stamped by `Ledger.append` per the existing event-versioning convention. No schema migration needed; the event class is new (content-additive at the event-class level).
- **I4 (reproducible state):** `compute_tier_from_signals` is deterministic — the same Person frontmatter + the same weights config produce the same suggestion on every call. The wall-clock dependency is limited to the `funding_recency_days` check (today's date vs `funding_date`); the primitive accepts an optional `now` kwarg for test reproducibility per ADR-0031 D140 + ADR-0034 D156 deterministic-clock precedent.
- **I5 (observable by default):** `tier_suggested` events carry `person_id` + `suggested_tier` + `signals_consulted` + `rationale` + `channel` + `_emitted_by`. Pillar G dashboards have scalar-field queries for every dimension. The `signals_consulted` dict surfaces per-signal coverage for operator audit.
- **I6 (tests prove invariants):** `tests/test_tier_assignment.py` ships per-method unit tests covering TierSuggestion invariants + compute_tier_from_signals happy paths + partial-signal degradation + weights override + CLI behavior. `tests/test_multi_channel_coherence.py::TestTierAutoAssignment` un-skipped 3 rows pin the integration-level contract. The load-bearing legal-liability + privacy invariants (D148) inherit the Layer 1 defense unchanged (the tier primitive does NOT introduce `source_list` aggregation; only `source_skill`).
- **I7 (cost is a first-class concern):** The tier primitive does NOT emit `cost_incurred` events (the primitive is rule-based + framework-local; zero per-call cost). The primitive's existence does NOT regress cost-avoidance — the dedup primitive (Week 2-3) + cache primitive (Week 4-5) continue to provide their cost-avoidance signals; the tier primitive adds observational tier-suggestion as an orthogonal surface.
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0035 row. The per-week trajectory in HANDOFF-pillar-e-week-9.md (TBD this commit) names planned ADRs 0036+.

Does not weaken any invariant. The three-step decoupling per ADR-0032 D145 IS the contract; the tier primitive preserves it by construction.

### Downstream pillar impact

Per the Pillar A / B / C / D / E Week 1 + 2 + 3 + 4-5 convention (every ADR explicitly names cross-pillar impact):

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring is per-touch (not per-tier); the tier primitive doesn't change Pillar F's contracts. The `tier_suggested` events surface "this Person was suggested as tier S" — Pillar F MAY consume this to surface tier-stamped voice exemplars (e.g., "your tier-S touches average 0.85 voice fidelity; your tier-A touches average 0.78") — TBD per Pillar F's ADR.

* **Pillar G (observability).** Pillar G's cost-per-quality-prospect dashboard consumes `tier_suggested` events to compute the auto-assignment hit-rate: `auto_assignment_accuracy = sum(operator_stamped == suggested) / total_suggestions`. The Pillar G per-source-funnel dashboard adds a `--breakdown tier_suggestion` dimension (Pillar G future ADR) — aggregates by `suggested_tier` to compute per-tier funnel conversion rates. Per the tier event's `channel: "none"` stamp, Pillar G's per-channel dashboards surface tier suggestions in the channel-agnostic funnel (not in any specific per-channel funnel — operator-deliberate; tier is cross-channel).

* **Pillar H (daemon + dispatcher).** Pillar H's daemon dispatches the channel sends; the tier primitive is operator-invoked (not auto-invoked by the daemon at v1). Pillar H's per-stage parallelism limits MAY become per-tier (a future Pillar H tuning: "tier S prospects get parallelism 4; tier A prospects get parallelism 2; tier B prospects get parallelism 1 — concentrate operator attention on high-tier") — TBD per Pillar H's ADR.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant tier weights. The Pillar I doctor preflight extends to check (a) the tier weights config's shape against the default template (drift detection); (b) the per-tier distribution against the operator's corpus (anomaly detection on a tier mix that suddenly skews — a sign of weights-config misalignment); (c) the auto-assignment accuracy over a rolling window (anomaly detection on a sudden accuracy drop — a sign of operator-stamping drift or weights-config drift). The Pillar I CLI ships `python -m orchestrator.tier_assignment retier --since <date> [--dry-run]` (batch re-suggestion for a cohort; operator-deliberate replay) — deferred from Week 6-8 scope. The Pillar I CLI also ships `python -m orchestrator.tier_assignment calibrate --corpus <vault>` (re-calibrate the default weights against the operator's actual corpus + emit a tuned weights config) — deferred.

* **Pillar J (security + compliance).** Pillar J's GDPR-forget transaction inherits the existing `forget_append` primitive (ADR-0004 §Decision step 2) + adds steps that purge tier-suggestion events for a deleted subject. The tier event carries `person_id`; the existing `person_id`-keyed purge predicate covers them. Pillar J's CAN-SPAM compliance gate is unchanged by Pillar E Week 6-8 — the tier primitive doesn't write to suppression YAML (that's Pillar D's auto-unsubscribe path); the tier primitive doesn't affect send authorization (the existing `TierRequiresTierInRule` reads operator-stamped `ctx.tier` unchanged).

## Migration / rollout

The Week 6-8 deliverable is the tier primitive module + the operator-tunable weights config template + the un-skipped coherence test rows + the cross-pillar audit row extension + the unit-test file.

**Operator-facing changes (Week 6-8):**

1. **No new pending migrations.** `runner.pending()` still returns 17 (the Pillar D + Pillar E Week 1-5 final state). The tier primitive is content-additive (NEW event class + NEW operator-tunable config; no schema changes to the ledger or vault that require a Pillar B migration).

2. **New module — `orchestrator/tier_assignment.py`** — importable via `from orchestrator import tier_assignment`. The public surface: `compute_tier_from_signals`, `build_tier_suggested_payload`, `TierSuggestion`, `DEFAULT_TIER_WEIGHTS_PATH`, `SUGGESTED_TIERS`, `EMITTED_BY`, `CHANNEL_VALUE`. The CLI surface: `python orchestrator/tier_assignment.py suggest --person <id> [--weights-path <path>] [--apply] [--json]`.

3. **New operator-tunable config template — `config-template/tier_weights.example.yml`** — operators copy to `~/.outreach-factory/tier_weights.yml` and tune as their corpus grows. The default template carries explanatory comments naming each weight's rationale + the operator-readable threshold semantics.

4. **No changes to existing modules** — `orchestrator/policy/tier.py` (the `TierRequiresTierInRule`) is UNCHANGED. The three-step decoupling per ADR-0032 D145 is preserved by construction.

5. **No changes to existing event classes** — the `tier_suggested` event class is NEW; the `manual_override` event class (ADR-0007) is unchanged; the `enrolled` event class is unchanged.

6. **New CLI subcommand — `python orchestrator/tier_assignment.py suggest`** — the tier primitive's command-line surface. `--apply` flag controls whether the `tier_suggested` event is appended to the ledger (live mode) or just reported (dry-run, the default).

7. **Existing operators with pre-Pillar-E-Week-6-8 Person notes** see no change. The tier primitive is content-additive; the operator-stamped `Person.research_tier` field remains the SoT (existing values preserved); the new suggestion event is operator-invoked (no auto-invocation surfacing unsolicited suggestions).

**Operator-facing changes (Pillar E Weeks 9-11+, planned):**

8. **Week 9-11 ships the per-skill `discovery_lineage:` stamping refactor + the coordinating vault migration** (per ADR-0032 D142 + D146). The `research-prospect` integration coincides. ADR-0036+ — TBD. The tier primitive's signal-source path will read `discovery_lineage.source_skill` directly (Week 9-11) — Week 6-8's legacy-fallback to `source_channel` becomes a back-compat path that the Week 9-11 commit may simplify.

9. **Week 12's binding exit-criterion test (`TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`) un-skips.** With the dedup primitive (Week 2-3) + the cache primitive (Week 4-5) + the tier-suggestion primitive (this commit) + the per-skill lineage stamping (Week 9-11) shipped, the cross-cutting three-skills-one-day-one-credit-each scenario is testable end-to-end. The tier primitive's contribution to the exit-criterion test is the verification that tier suggestions co-exist with the dedup + cache primitives without cross-event-class interference.

10. **Pillar I CLI extensions (Weeks 43-48)** — `python -m orchestrator.tier_assignment retier --since <date> [--dry-run]` (batch re-suggestion) + `python -m orchestrator.tier_assignment calibrate --corpus <vault>` (re-calibrate weights against operator corpus) + doctor-preflight extension for weights-config-drift detection. Deferred from Week 6-8 scope.

**The Week 6-8 commit's verification surface:**

```python
# 1. The tier primitive module exists + is importable.
$ python -c "from orchestrator.tier_assignment import compute_tier_from_signals, TierSuggestion, build_tier_suggested_payload, DEFAULT_TIER_WEIGHTS_PATH, SUGGESTED_TIERS, EMITTED_BY, CHANNEL_VALUE"

# 2. The default-shipped weights template exists + is loadable.
$ ls config-template/tier_weights.example.yml
$ python -c "import yaml; yaml.safe_load(open('config-template/tier_weights.example.yml'))"

# 3. The tier primitive unit tests pass.
$ python -m pytest tests/test_tier_assignment.py -v
# Expected: all per-method tests pass.

# 4. The coherence test vehicle's Week 6-8 rows un-skip + pass.
$ python -m pytest tests/test_multi_channel_coherence.py::TestTierAutoAssignment -v
# Expected: ALL 3 rows passing (no skips).

# 5. The tier CLI runs.
$ python orchestrator/tier_assignment.py suggest --person <some-pid> --json
# Expected: JSON output reporting the suggested tier + signals_consulted + rationale.

# 6. The full suite is green at +N tests.
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 2466+N passed (the +N comes from: NEW tier primitive unit tests + 3 un-skipped coherence rows).

# 7. ADR-0035 exists; README index gains the row; PILLAR-PLAN §6 Pillar E row updated.
$ ls docs/adr/0035-pillar-e-tier-auto-assignment.md
$ grep "0035" docs/adr/README.md
$ grep "Week 6-8 ✓" docs/PILLAR-PLAN.md
```

### Existing-operator seed

Pillar E Week 6-8 ships NO new migrations + NO new ledger-state primitives that require an existing-operator seed action.

**Bootstrap-step seed for existing operators (Yang):**

The Week 6-8 commit is content-additive — no operator action required. The tier primitive is callable via the new CLI; the operator-tunable weights template ships at `config-template/tier_weights.example.yml` for operators who want to tune.

For Yang specifically (the current sole operator), the default-shipped weights are calibrated against Yang's ~500 Person operator-tagged corpus at Week 6-8 ship time. Yang's first invocation of the tier primitive (e.g., `python orchestrator/tier_assignment.py suggest --person <pid>`) returns a tier suggestion derived from the default weights. The operator-readable `rationale` field surfaces the decision tree; if Yang disagrees with the suggestion, Yang stamps `research_tier:` on the Person's frontmatter (the existing operator-stamping workflow; unchanged). The `manual_override` event class (ADR-0007) remains available for operator-deliberate disagreement audit.

**Confidence-interval limitation of the default weights:**

The default weights are calibrated against ~500 Person corpus — sufficient for a starting point but limited for high-confidence accuracy claims. As Yang's corpus grows (toward 1000+ Persons with operator-stamped tiers), the operator may re-calibrate via:

```bash
# Future Pillar I CLI (deferred from Week 6-8):
python -m orchestrator.tier_assignment calibrate --corpus ~/Documents/Obsidian\ Vault/10\ People \
  --output ~/.outreach-factory/tier_weights.yml
```

The Pillar I calibrate command (deferred) walks the operator's actual corpus + computes the per-signal regression coefficients + emits a tuned weights file. Until then, operators tune the weights file by hand based on operator-readable rationale strings + per-tier distribution analysis.

**For operators with weights config divergent from the default (R021 mitigation):**

The default-shipped weights are operator-tunable per D163. An operator who tunes the weights file to extreme values (e.g., zero weights on every signal → every suggestion is tier B; or saturated weights → every suggestion is tier S) will see operator-visible accuracy drift on Pillar G dashboards. The structural defense is the rationale field on every event + the per-tier distribution surfacing on Pillar G; the per-week reviewer's category #5 pins config-shape validation as a future Pillar I doctor preflight extension.

The first Pillar E week that ships a vault migration requiring an existing-operator seed action (TBD — likely Pillar E Week 9-11's vault migration adding per-Person `discovery_lineage:` block) WILL include the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface the tier primitive integrates with (no engine change required); the operator-tunable YAML config convention the weights file inherits.
- ADR-0002 (cooldown rules) — the operator-tunable YAML config precedent (the weights config follows the same shape).
- ADR-0003 (channel as first-class policy predicate) — the cross-channel rule whose behavior the tier events do NOT trigger (events don't end in `_confirmed`).
- ADR-0004 (suppression rules + GDPR-forget) — the `forget_append` primitive Pillar J's purge transaction extends to tier-suggestion events.
- ADR-0005 (DayOfWeekRule) — the operator-tunable YAML config precedent the weights file inherits.
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention the tier primitive does NOT touch (the tier primitive emits no `cost_incurred` events; rule-based + framework-local).
- ADR-0007 (tier rules + `manual_override` event class) — **THE LOAD-BEARING PRECEDENT.** The existing `TierRequiresTierInRule` (per `policy/tier.py`) reads operator-stamped `ctx.tier` (unchanged by Week 6-8); the `manual_override` event class (per `policy/__main__.py:639`) is the operator-deliberate override surface (independent of the tier-suggestion primitive). The three-step decoupling per ADR-0032 D145 (SUPPLY → STAMP → READ) preserves this contract.
- ADR-0009 (migration framework) — Pillar E vault/ledger migrations (Week 9-11+) will register into the existing framework; Week 6-8 ships ZERO migrations.
- ADR-0010 (ledger migrations) — the D17 `_emitted_by` convention the tier primitive's events inherit.
- ADR-0011 (vault migrations) — Pillar E Person note migrations (Week 9-11+) consume the existing `add_frontmatter_block_text` + `iter_person_notes` primitives.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — the D24 hybrid synthetic fixture pattern Pillar E Week 12 extends.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-event invariant the tier events inherit (with `channel: "none"` per D161); the D36 existing-operator-seed pattern Pillar E inherits; the D37 exit-criterion vehicle Pillar E extends.
- ADR-0025 (Pillar D foundation) — the D99 cross-pillar surface audit Pillar E mirrors per ADR-0032 D146 + extends per D165.
- ADR-0026 (Pillar D Week 2 — rule-based classifier) — **THE PRECEDENT FOR PILLAR E SIBLING PRIMITIVES.** D102 (classifier module placement — `orchestrator/reply_classifier.py`) → D160 (tier module placement — `orchestrator/tier_assignment.py`). The sibling-of-existing-primitives placement pattern continues from ADR-0033 D149 + ADR-0034 D154.
- ADR-0031 (Pillar D exit-criterion close) — the D136 deterministic-clock pattern the tier primitive's `now` kwarg (for funding-recency window computation) inherits.
- ADR-0032 (Pillar E foundation) — D145 (tier auto-assignment substrate — D160-D162 implement); D146 (cross-pillar surface audit D165 extends); D147 (exit-criterion vehicle scope; Week 6-8 un-skips 3 of 3 `TestTierAutoAssignment` rows).
- ADR-0033 (Pillar E Week 2 — pre-enrichment dedup primitive) — **THE FIRST SIBLING PRIMITIVE PRECEDENT.** D149 (dedup module placement) → D160 (tier module placement — same shape). D150 (dedup event emit-shape with `channel: "none"`) → D161 (tier event emit-shape with `channel: "none"` — same channel-agnostic posture). D152 (per-skill integration discipline — four skill sites) → D164 (per-Person CLI invocation — one site per operator invocation). D153 (cross-pillar audit extension) → D165 (same pattern).
- ADR-0034 (Pillar E Week 4-5 — email-verification cache primitive) — **THE SECOND SIBLING PRIMITIVE PRECEDENT.** D154 (cache module placement) → D160 (tier module placement — same shape). D155 (cache event emit-shape with `channel: "email"`) → D161 (tier event emit-shape with `channel: "none"` — asymmetric per the tier's channel-agnostic scope vs the cache's email-specific scope). D158 (per-call-site integration — one site) → D164 (per-Person CLI invocation — one site per operator invocation). D159 (cross-pillar audit extension) → D165 (same pattern).
- `docs/PILLAR-PLAN.md` §2 Pillar E — exit criterion (binding text); §5 "What we will not do" — Pillar E adjacent constraints; §6 Pillar E row Notes column extended to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4-5 ✓ + Week 6-8 ✓" in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D162's default-low-tier-B-when-uncertain choice (false-positive S tier wastes operator review time; false-negative B tier surfaces for operator review where they can stamp the actual tier).
- `docs/RISK-REGISTER.md` R001 (identity-graph false-merge cascade) — risk the tier primitive does NOT regress (the tier operates on firmographic + intent signals, not identity keys). R018 + R019 + R020 + R021 (R021 NEW in this ADR — tier-weights config drift) — the Week 6-8 implementation does not introduce new identity-related risks; R021 names the operator-tuning surface's drift risk.
- `docs/SOURCES-OF-TRUTH.md` — no new row added (the tier primitive emits events; the ledger remains the SoT for events; the operator-stamped `Person.research_tier` field remains the SoT for the actual tier value; the operator-tunable weights config is operator-private per the existing operator-config convention).
- `.planning/REVIEW-pillar-e-surface-audit.md` — extended in this commit with the Week 6-8 section per D165.
- `.planning/HANDOFF-pillar-e-week-6.md` — the per-week handoff that scoped Week 6-8.
- `.planning/HANDOFF-pillar-e-week-9.md` — written in this commit; scopes Week 9-11 (the per-skill `discovery_lineage:` stamping refactor + the `research-prospect` integration per ADR-0032 D142).
- `orchestrator/tier_assignment.py` — the primitive module D160 names.
- `orchestrator/policy/tier.py` — the existing rule (the consumer of operator-stamped `ctx.tier`) the auto-assignment SUPPLIES via events (D161's three-step decoupling).
- `orchestrator/discovery_dedup.py` — the FIRST SIBLING primitive (per ADR-0033) whose shape this primitive mirrors.
- `orchestrator/email_verification_cache.py` — the SECOND SIBLING primitive (per ADR-0034) whose shape this primitive mirrors.
- `orchestrator/enrichment.py` (TBD — `enrollment.py`) — the existing Person enrollment site (UNCHANGED by Week 6-8; the tier primitive does NOT wrap enrollment per D164).
- `orchestrator/ledger.py` — the substrate the tier primitive emits to (`Ledger.append`).
- `config-template/tier_weights.example.yml` — the default-shipped weights template D163 names.
- `tests/test_tier_assignment.py` — the primitive's unit tests.
- `tests/test_multi_channel_coherence.py::TestTierAutoAssignment` — the un-skipped 3 of 3 rows that pin the integration-level contract.
- Forward-references (planned):
  - **ADR-0036+** (Pillar E Week 9-11): per-skill `discovery_lineage:` stamping refactor + the `research-prospect` integration + the coordinating vault migration (`vault/0005_add_discovery_lineage_to_identity_keys` — TBD shape). The tier primitive's signal-source path will read `discovery_lineage.source_skill` directly (Week 9-11) — Week 6-8's legacy-fallback to `source_channel` becomes a back-compat path.
  - **ADR-00NN** (Pillar E Week 12): exit-gate close — the binding three-skills-one-day exit-criterion test un-skips.
  - **Pillar G dashboards** (Weeks 31-42): cost-per-quality-prospect dashboard consuming `cost_incurred` + `discovery_dedup_hit` + `email_verification_cache_hit` + `tier_suggested` events; per-tier funnel conversion rates; auto-assignment accuracy aggregation.
  - **Pillar I CLI** (Weeks 43-48): aggregation of per-ADR seed blocks + the tier primitive's `retier --since` + `calibrate --corpus` extensions + the doctor-preflight extension for weights-config-drift detection + the per-tenant override surface.
  - **Pillar J GDPR-forget** (Weeks 49-52): the per-Person tier-suggestion event purge step added to the existing `forget_append` flow.
