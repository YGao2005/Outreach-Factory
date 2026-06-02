# ADR-0037: Pillar E Week 12 — exit-criterion close (three-skills-one-day binding test) + Pillar E Stable flip

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** E (Discovery quality + lineage — Week 12 — exit-criterion close)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0032 (Pillar E Week 1 foundation, D142-D148) pinned the discovery-lineage shape as an `identity_keys:` sub-block, the pre-enrichment dedup contract, the email-verification cache shape, the tier auto-assignment substrate, the cross-pillar surface audit, the exit-criterion vehicle scope (D147), and the privacy-respecting invariant for `source_list`. ADR-0033 (Week 2, D149-D153 + the 2026-05-24 Amendment) shipped the dedup primitive (`orchestrator/discovery_dedup.py`) + per-skill integration in find-leads + find-funded-founders + competitor-customers. ADR-0034 (Week 4-5, D154-D159) shipped the email-verification cache primitive (`orchestrator/email_verification_cache.py`) + the wrap inside `enrich_emails.verify_with_reoon`. ADR-0035 (Week 6-8, D160-D165) shipped the tier auto-assignment primitive (`orchestrator/tier_assignment.py`) + the operator-tunable per-signal weights config. ADR-0036 (Week 9-11, D166-D171) shipped the discovery-lineage primitive (`orchestrator/discovery_lineage.py`) + the vault migration `vault/0005_add_discovery_lineage_to_identity_keys` + the ledger migration `ledger/0007_backfill_enrolled_source_skill` + per-skill stamping in all four discovery skills' SKILL.md files + the `enrollment.py` `lineage` kwarg surface.

**Pillar E Week 12 is the EXIT-CRITERION CLOSE.** Per PILLAR-PLAN §2 Pillar E's binding text:

> *"discovering the same person via three skills in one day consumes one Apollo credit, one Reoon credit, zero duplicate enrollments."*

Week 12 ships the SINGLE coordinated extension that satisfies this exit criterion + flips Pillar E from "In progress" to **Stable**:

1. **The `tests/test_multi_channel_coherence.py::TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates` un-skip + body** — the binding test that composes ALL FOUR Pillar E primitives (dedup + cache + tier-suggestion + lineage stamping) against a single synthetic scenario: three discovery skills (find-leads + find-funded-founders + competitor-customers) surface the same prospect on the same day. The first skill's enrollment + the second + third skills' dedup-skip cost-avoidance + the post-dispatch cache hit + the per-Person tier suggestion all land inside a single integrated test body.

2. **Pillar E Stable flip** — `docs/PILLAR-PLAN.md` §6 Pillar E row Status column flips from "In progress" to "**Stable** as of 2026-05-24"; Notes column appends "+ Week 12 ✓ — Pillar E Stable" + the close summary.

3. **`.planning/RETRO-pillar-e.md`** — the Pillar E retrospective per the Pillar D Week 12 ADR-0031 D141 precedent. Captures the eight Pillar D → Pillar E carry-forward outcomes + the Pillar E → Pillar F handoff recommendations + the structural pattern discoveries (per-week-reviewer fresh-context catches; dual-module-identity hazard; the per-primitive-per-week trajectory's compression).

4. **`.planning/REVIEW-pillar-e-surface-audit.md` Week 12 extension** (§45+) — the audit's UNCHANGED-verdict section walking the binding test's consumer surface. The binding test is verification-only; no new event classes; no new ledger-walk patterns; no new operator-facing surfaces.

5. **`.planning/HANDOFF-pillar-f-week-1.md`** (NEW) — the per-week trajectory breadcrumb for Pillar F (Voice corpus + draft quality begins Week 25 per PILLAR-PLAN §6). Carries forward the Pillar E pattern discoveries + the eight Pillar A/B/C/D/E conventions.

The six concerns this ADR resolves:

1. **Binding exit-criterion test vehicle scope — extend `test_multi_channel_coherence.py` vs new file.** Per ADR-0032 D147 + ADR-0014 D37 + ADR-0025 D101's single-file-per-vehicle rationale, the binding test extends the existing coherence vehicle. D172 confirms.

2. **Binding test assertion ROWS — which surfaces must the test exercise.** Per PILLAR-PLAN §2 Pillar E's binding text + the four primitives' contracts. D173 names the seven assertion rows (Apollo + Reoon + duplicate-count + dedup-hit-count + cache-hit-count + lineage-stamping + canonical-source-skill-field).

3. **Deterministic-clock contract for the binding test.** Per ADR-0031 D140 + ADR-0034 D156 + ADR-0035 D162 deterministic-clock precedent. D174 names the explicit `now`-argument discipline.

4. **Pillar E Stable flip discipline — what is the binding gate.** Per ADR-0014 D37 + ADR-0025 D101 + ADR-0031 D141's per-pillar stable-flip precedent. D175 names the binding test as THE gate + the per-pillar stable-flip checklist.

5. **Pillar E retrospective discipline.** Per ADR-0031 D141's Pillar D Week 12 precedent. D176 ships `.planning/RETRO-pillar-e.md`.

6. **Cross-pillar audit row extension — UNCHANGED verdict.** Per ADR-0032 D146 + ADR-0033 D153 + ADR-0034 D158 + ADR-0035 D165 + ADR-0036 D171 conventions. D177 names the Week 12 audit extension + the UNCHANGED verdict (the binding test is verification-only).

Risks this ADR mitigates by design: **R001 (identity-graph false-merge cascade)** continues mitigated by the dedup primitive's reuse of `identity.resolve_strict`. **R018 (discovery-source poisoning)** continues mitigated by the lineage primitive's `raw_input_hash` field. **R019 (pre-enrichment dedup false-positive)** continues mitigated by the dedup primitive's `should_skip_enrichment` semantics. **R020 (email-verification cache staleness)** continues mitigated by the 30-day TTL + the post-dispatch re-verify cache-hit path. **R021 (tier-weights config drift)** continues mitigated by the per-Person rationale field. **R022 (discovery_lineage backfill heuristic precision)** continues mitigated by the per-Person operator-resolution CLI.

No new risks. The exit-criterion close adds NO new event classes, NO new reconcile passes, NO new policy / ledger / vault migrations, NO new operator-facing surfaces — Pillar E's stable surface is the four primitives + the per-skill integration shipped through Week 9-11 + the binding test that gates them.

## Decision

### D172. Binding exit-criterion test vehicle scope — extend `tests/test_multi_channel_coherence.py`

The binding test un-skips inside the existing `TestPillarEExitCriterion` class in `tests/test_multi_channel_coherence.py` (the stub landed at Week 1 per ADR-0032 D147). The class's single method `test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates` un-skips + the body lands in this Week 12 commit.

Per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 the cross-pillar coherence file is the single canonical exit-criterion vehicle. The Week 12 commit adds ~250-350 LOC to the existing file (the binding test body + fixture wiring); the file's cumulative size approaches ~6500 LOC. If a future Pillar F / G / H / I / J week's extension crosses ~7500 LOC the split argument resurfaces — TBD per the per-week reviewer's call in that future week.

**Why extend the existing file (rejected: separate `tests/test_pillar_e_exit_criterion.py` file).** Fragments the coherence vehicle. The vehicle's load-bearing property is cross-pillar coherence visible from Week 1 in ONE place per-week reviewers consult — a separate file creates the "look in two places" mental model ADR-0014 D37 §Decision rejected.

**Why extend the existing file (rejected: separate `tests/test_pillar_e_three_skills_one_day.py` per-scenario file).** Splits the binding scenario from the per-primitive coherence rows that constitute it. The per-primitive rows (`TestDiscoveryLineage` / `TestPreEnrichmentDedup` / `TestEmailVerificationCache` / `TestTierAutoAssignment`) live in the same file; the binding test that composes them belongs adjacent.

**Why extend the existing file (rejected: inline as multiple shorter tests in `TestPillarEExitCriterion`).** The binding text per PILLAR-PLAN §2 is ONE scenario ("discovering the same person via three skills in one day"); decomposing into multiple shorter tests loses the end-to-end coherence the exit criterion explicitly pins. The COHERENCE-LEVEL subset that exercises ONLY the dedup primitive across three skills (`TestPreEnrichmentDedup::test_three_skills_one_day_consume_one_apollo_credit`) already un-skipped at Week 3 per ADR-0033 §Amendment 2026-05-24; the FULL exit-criterion test extends that subset to cover Apollo + Reoon + zero-duplicates + lineage stamping + tier suggestion + cache hit uniformly.

### D173. Binding test assertion ROWS — eight rows

The binding test (`test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`) asserts the following ROWS in this Week 12 commit:

| Row | Pin | Source primitive |
|---|---|---|
| **(a)** | **ONE Apollo credit** consumed across the three discovery skills' invocations of the same prospect | dedup (per ADR-0033) |
| **(b)** | **ONE Reoon credit** consumed across the three invocations (the post-dispatch re-verify hits the cache) | dedup + cache (per ADR-0033 + ADR-0034) |
| **(c)** | **ZERO duplicate enrollments** — exactly one Person note created; the dedup primitive's `should_skip_enrichment` guarantees skills 2 + 3 skip the enrichment + enrollment path entirely | dedup + identity-resolver (per ADR-0033 + Phase 5.5 Week 1b) |
| **(d)** | **TWO `discovery_dedup_hit` events** emitted (one per skill that hit the dedup primitive's duplicate path; skill 1's `not_duplicate` result emits no event) | dedup (per ADR-0033 D150) |
| **(e)** | **ONE `email_verification_cache_hit` event** emitted (the post-dispatch re-verify hits the cache substrate populated by skill 1's Reoon call); the substrate is the ledger's `cost_incurred.source=reoon` event extended with `email` + `verification_response` per ADR-0034 D156 | cache (per ADR-0034 D155) |
| **(f)** | The enrolled Person carries the canonical `identity_keys.discovery_lineage:` sub-block with the FIRST skill's `source_skill` (the dedup primitive's "skip enrichment" path means the second + third skills' stamping never happens — the first skill's lineage WINS by enrollment-time precedence) | lineage + enrollment (per ADR-0036 D169 + D170) |
| **(g)** | The `enrolled` ledger event carries the canonical `source_skill` field per ADR-0036 D170 (denormalized from the lineage's stamping); the field's value is one of `SOURCE_SKILLS` | lineage + enrollment (per ADR-0036 D170) |

Plus the integrated-scenario tier-suggestion row per the handoff's recommendation (a):

| Row | Pin | Source primitive |
|---|---|---|
| **(h)** | The enrolled Person carries a `tier_suggested` event emitted via `tier_assignment.compute_tier_from_signals` consuming the canonical `discovery_lineage.source_skill` per ADR-0035 D162 | tier (per ADR-0035 D161) |

The binding test composes all four Pillar E primitives in a SINGLE integrated scenario. The per-primitive coherence rows (TestDiscoveryLineage × 5 + TestPreEnrichmentDedup × 5 + TestEmailVerificationCache × 4 + TestTierAutoAssignment × 3 — all un-skipped through Week 9-11) exercise each primitive's contract in isolation; the binding test verifies the primitives COMPOSE per the exit-criterion text.

**Why include the tier-suggestion row (rejected: scope binding test to dedup + cache + lineage per ADR-0032 D147's original text).** The handoff's Design-decisions recommendation (a) names the integrated-scenario shape as the most-coverage choice. Excluding tier-suggestion would leave one of the four primitives unverified in the binding scenario. Per the asymmetric-failure-cost calculus, the integrated-scenario shape catches per-primitive integration bugs the per-primitive coherence rows miss (the per-Person tier-suggestion's signal source IS the lineage primitive's `source_skill`; the binding test verifies the cross-primitive plumbing works).

**Why include the cache-hit row via a synthetic post-dispatch re-verify step (rejected: assume skills 2 + 3 reach the cache primitive).** Skills 2 + 3 hit the dedup primitive's "skip enrichment" path → they DO NOT reach Reoon (the dedup primitive is upstream of the cache primitive per ADR-0033 D149 + ADR-0034 D154). The cache primitive's substrate IS populated by skill 1's Reoon call (the cost event's `email` + `verification_response` fields per ADR-0034 D156 land for future cache hits). A synthetic post-dispatch re-verify step (modeling the dispatcher's pre-send email re-check minutes later per Pillar A's standard flow) exercises the cache HIT path AGAINST the substrate the binding scenario populates. Without this step the cache primitive is only verified by its own per-primitive coherence rows; the binding scenario's composition verification is incomplete.

**Why exclude the `enrolled_source_skill_backfill` event class from the binding test (rejected: include a synthetic historical `enrolled` event + run the ledger migration).** The binding test is for NEW enrollments (post-Week-9-11 emit shape per ADR-0036 D170); the backfill event class is for historical pre-Week-9-11 enrollments. Per the handoff's Design-decisions recommendation (b), the backfill event class's coverage lives in `tests/test_migrations_ledger_0007.py` (Week 9-11's 28-test unit suite); the binding test stays scoped to the NEW-enrollment flow.

### D174. Deterministic-clock contract for the binding test

The binding test uses an explicit anchor `anchor = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)` for:

* The `DiscoveryLineage.scraped_at` value (ISO 8601 UTC formatted via `anchor.strftime("%Y-%m-%dT%H:%M:%SZ")`).
* The `tier_assignment.compute_tier_from_signals` call's `now` kwarg (per ADR-0035 D162's deterministic-clock precedent).
* The post-dispatch re-verify call's `email_verification_cache.datetime.now` patched return value (per ADR-0034 D156's deterministic-clock precedent — `anchor + timedelta(minutes=5)`).

The ledger emit timestamps (the `ts` field on each emitted event) DO NOT need explicit patching — the binding test's assertions are on event COUNTS + field VALUES (source_skill / email / cached_result), NOT on event ts values. The 30-day cache TTL window comfortably accommodates real-time skew between test runs; the cache primitive's behavior is deterministic for any (cost_event_ts, lookup_now) pair where the difference is within TTL.

**Why partial-deterministic-clock (rejected: full-deterministic-clock via `ledger._now_iso` monkey-patch).** Full-deterministic-clock would require patching `orchestrator.ledger._now_iso` (per the Pillar D Week 12 ADR-0031 D140 precedent) to anchor every ledger-emitted ts. Pillar E's binding test does not assert on ledger ts values — the deterministic-clock contract is bounded to the surfaces whose BEHAVIOR depends on the clock (the cache's TTL window + the tier primitive's funding-recency window). Patching `_now_iso` would add ~10 LOC of fixture scaffolding for no behavior gain.

**Why partial-deterministic-clock (rejected: no-clock-patching, accept real-time variance).** The cache primitive's `cache_age_days` calculation depends on the lookup's `now` MINUS the cost event's ts. Without patching `email_verification_cache.datetime.now`, the cache primitive would use wall-clock real-now (which may drift relative to the binding test's anchor). Patching `now` for the post-dispatch lookup ensures the cache HIT predictably fires + the event payload's `cache_age_days` value is deterministic (~0 days for the in-test millisecond window).

**Why partial-deterministic-clock (rejected: extract `tests/_test_helpers/deterministic_clock.py` per RETRO-pillar-d.md item 8 recommendation).** The Pillar D Week 12 retrospective named helper extraction as a future Pillar E or Pillar I concern; Pillar E shipped four primitives' coherence tests without the helper (each uses the per-test `now` kwarg pattern directly per the lineage primitive's compute_canonical_raw_input_hash + the cache primitive's lookup_cache + the tier primitive's compute_tier_from_signals signatures). The lineage primitive (Week 9-11) is the FOURTH deterministic-clock consumer after the funnel CLI + cache primitive + tier primitive; helper extraction MAY land in a future Pillar I OSS bring-up week IF the per-test boilerplate grows past ~6 consumers. At Week 12 the per-test pattern stays inline.

### D175. Pillar E Stable flip discipline — binding test as THE gate + per-pillar checklist

Per ADR-0014 D37 + ADR-0025 D101 + ADR-0031 D141's per-pillar stable-flip precedent. The Pillar E Stable flip's gate is the binding test PASSING in this Week 12 commit. The PILLAR-PLAN §6 Pillar E row's Status column flips from "In progress" to "**Stable** as of 2026-05-24"; the Notes column appends "+ Week 12 ✓ — Pillar E Stable (binding exit-criterion test passing; the four Pillar E primitives compose per the exit criterion's three-skills-one-day text)."

The per-pillar stable-flip checklist (inherited from ADR-0031 D141's Pillar D Week 12 precedent):

1. **Every exit-criterion bullet from PILLAR-PLAN §2 verified.** Pillar E's three exit-criterion sub-bullets: (a) discovery_lineage carried on every NEW enrollment — verified by `TestDiscoveryLineage::test_every_new_enrollment_carries_canonical_discovery_lineage` (Week 9-11 un-skipped); (b) one Apollo + one Reoon + zero-duplicates per the three-skills-one-day scenario — verified by THIS binding test (Week 12 un-skipped); (c) tier auto-assignment from signals — verified by `TestTierAutoAssignment::test_suggestion_respects_operator_manual_override` (Week 6-8 un-skipped). The fourth bullet (cost-per-quality-prospect dashboard) is a Pillar G forward-reference per ADR-0035 §Downstream pillar impact.

2. **Every per-week handoff doc closed.** `.planning/HANDOFF-pillar-e-week-{1,2,4,6,9,12}.md` (six handoff documents — Week 12 is this commit's authoring).

3. **Cross-pillar audit's verdict at "no P1 outstanding."** `.planning/REVIEW-pillar-e-surface-audit.md` §45+ (this commit's extension) confirms UNCHANGED verdict.

4. **The binding test passing in CI for ≥1 day.** Observational, not gating. The Week 12 main commit ships the test passing; the per-week reviewer's verification confirms the pass before the follow-up commit.

The "≥1 day CI" requirement is observational per the Pillar D Week 12 precedent — the binding test ships passing in the Week 12 main commit; future Pillar F authors verify via `python -m pytest tests/test_multi_channel_coherence.py::TestPillarEExitCriterion -v` against the same commit.

**Why the binding test gates the Stable flip (rejected: holistic exit review as the gate).** The holistic exit review (per Pillar D Week 12's `.planning/REVIEW-pillar-d-holistic.md`) surfaced 0 P1 + 2 P2 + 4 P3 findings — operator-visible but not gating. Per the Pillar D Week 12 precedent the BINDING TEST is the structural gate; the holistic review is an addendum surface. Pillar E Week 12 follows the same convention.

**Why the binding test gates the Stable flip (rejected: per-week-reviewer sign-off as the gate).** Per-week reviewers' findings are scope-bounded to the per-week commit's changes; the BINDING TEST is the exit-criterion vehicle's structural verification across all twelve Pillar E weeks. Per-week sign-off is a complement, not a substitute.

**Why the binding test gates the Stable flip (rejected: full Pillar G dashboard validation).** The Pillar G dashboards are downstream consumers of the Pillar E surfaces (per the §Downstream pillar impact sections of ADR-0032 + ADR-0033 + ADR-0034 + ADR-0035 + ADR-0036); waiting for Pillar G to validate would couple Pillar E's stable flip to a future pillar's timeline. The dashboards consume the surfaces Pillar E ships; Pillar E's surfaces are stable independent of dashboard consumption.

### D176. Pillar E retrospective discipline — `.planning/RETRO-pillar-e.md`

Per ADR-0031 D141's Pillar D Week 12 precedent. The retrospective document captures:

* **§Calibration headline** — the per-pillar week-budget vs calendar-day-cost calibration.
* **§What worked** — the patterns Pillar E confirmed (primitive-per-week + per-week-handoff + per-week-review-with-follow-up-commit + cross-pillar audit + per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact + holistic-exit-review).
* **§What surprised** — the structural discoveries (the dual-module-identity hazard between `discovery_lineage` bare and `orchestrator.discovery_lineage` package imports; the per-week-reviewer fresh-context advantage catching P2s the inline author missed; the per-week-reviewer P1 frequency dropping to ZERO across Weeks 4-5 + 6-8 + 9-11 vs Pillar D Week 9-11's P1).
* **§What to do differently in Pillar F** — the carry-forward recommendations (continue the per-week discipline; design Pillar F's voice-corpus invariants at Week 1; bake the doc-sweep step; anticipate the deterministic-clock requirement).
* **§The pattern's known blind spot** — cross-pillar coherence at the dependency edges (the back-audit gap).
* **§Carry-overs into Pillar F** — what stays deferred + what new carryovers Pillar E adds.
* **§Twelve-week trace** — the per-week commit table.

The eight Pillar D → Pillar E carry-forward outcomes named in ADR-0032 §Context bullet 1-8 + RETRO-pillar-d.md §"What to do differently in Pillar E" each get a verdict in the retrospective.

**Why ship the retrospective in the Week 12 main commit (rejected: ship as a separate post-pillar reflection commit).** Per ADR-0031 D141's discipline, the retrospective IS part of the stable-flip artifact. Splitting would create a temporal gap where Pillar E is Stable but the retrospective is missing; the per-pillar stable-flip discipline names the retrospective as a load-bearing surface for Pillar F's first ADR author to read.

**Why ship the retrospective in the Week 12 main commit (rejected: ship after a 1-week stabilization period).** The Pillar D precedent shipped the retrospective in the Week 12 main commit; stabilization-period reflection has no precedent. Pillar E follows the same convention — the per-week patterns are documented continuously through the twelve weeks; the retrospective synthesizes them at the stable-flip moment.

**Why ship the retrospective in the Week 12 main commit (rejected: defer retrospective to Pillar I OSS bring-up).** Defers the synthesis indefinitely; the per-pillar retrospective discipline is the operator-readable evidence of the per-week pattern continuity. Pillar F's author reads RETRO-pillar-e.md before authoring Pillar F's first ADR per the same convention Pillar E followed reading RETRO-pillar-d.md.

### D177. Cross-pillar audit row extension — `.planning/REVIEW-pillar-e-surface-audit.md` §45+ — UNCHANGED verdict

Per ADR-0032 D146 + ADR-0033 D153 + ADR-0034 D158 + ADR-0035 D165 + ADR-0036 D171 conventions, the Week 12 commit extends the cross-pillar surface audit with a new section walking the un-skipped binding test's consumer surface.

**The binding test is verification-only.** It introduces:

* **ZERO new event classes** — every event the binding test consumes (`discovery_dedup_hit` / `email_verification_cache_hit` / `tier_suggested` / `enrolled` / `cost_incurred`) is an existing class shipped through Weeks 2-11. No new audit row for "the test's new event surface" because the test introduces no new surface.

* **ZERO new ledger-walk patterns** — the binding test consumes `Ledger.all_events()` (existing per ADR-0011 D24) + filters by `event.get("type") == "..."` (existing closed-set predicate pattern per Weeks 2-11's audit sections). No new index access; no new consumer pattern.

* **ZERO new operator-facing surfaces** — the binding test does NOT add a new CLI command, a new SKILL.md phase, a new operator-tunable config, or a new ledger event class. It exercises the existing four-primitive surface integrated.

* **ZERO new primitives** — the four Pillar E primitives stay at their Week 9-11 ship shape. The binding test is a CONSUMER, not a producer.

**The Week 12 audit section's verdict: UNCHANGED.** The audit document's §45+ Week 12 section confirms that the binding test's consumer surface is closed-set-protected against every Pillar A/B/C/D/E (Weeks 1-11) consumer; zero new latent-bug patterns surfaced.

**Why extend the audit even with UNCHANGED verdict (rejected: skip the audit extension since no new surfaces).** The per-week audit discipline per ADR-0032 D146 is "every Pillar E week's commit extends the audit OR confirms unchanged." Skipping creates a structural gap (a future audit reader sees the Weeks 1-11 sections + the missing Week 12 entry; the audit's continuity is a load-bearing reading surface). The UNCHANGED verdict IS the audit's signal that Week 12 is verification-only; the explicit section also documents the four-primitive composition for future readers.

**Why extend the audit even with UNCHANGED verdict (rejected: combine Week 12 verdict with the Week 9-11 section).** Per the per-week-section convention, each Pillar E week's commit gets its own section. Combining would erase the per-week traceability the audit provides; future Pillar F / G / H / I / J authors trace per-week extensions to per-week commits.

**Why extend the audit even with UNCHANGED verdict (rejected: defer the audit extension to the per-week-reviewer follow-up commit).** Per ADR-0036 §"Why NOT split the audit into a follow-up commit" the atomicity contract is "primitive + audit + ADR + tests + handoff land together." Pillar E Week 12 ships the binding test + the audit extension + this ADR + the retrospective + the handoff together in the main commit; the per-week-reviewer follow-up handles per-review findings, not structural artifacts.

## Alternatives considered

### D172-Alt1: Ship the binding test in a separate `tests/test_pillar_e_exit_criterion.py` file

A new file dedicated to Pillar E's exit-criterion vehicle. **Rejected** because:

* Fragments the coherence vehicle; the `tests/test_multi_channel_coherence.py` file's load-bearing property is single-file cross-pillar coherence per ADR-0014 D37 + ADR-0025 D101.
* Splits the per-primitive coherence rows (in the existing file) from the binding scenario that composes them.
* Creates the "look in two places" mental model rejected at every Pillar A/B/C/D/E foundational ADR.

### D172-Alt2: Ship the binding test as multiple shorter scenario tests inside `TestPillarEExitCriterion`

Split the single binding scenario into ~6 shorter per-assertion-row tests. **Rejected** because:

* Loses the end-to-end scenario coherence the exit-criterion text explicitly pins ("discovering the same person via three skills in one day").
* The per-primitive coherence rows already exist (Week 2 through Week 9-11 un-skipped them); the binding test's purpose IS the composition.
* Per the Pillar D Week 12 precedent (ADR-0031 D141) the binding test is one scenario; Pillar E follows the same convention.

### D172-Alt3: Defer the binding test to Pillar I OSS bring-up

Treat the exit-criterion text as aspirational; ship Pillar E without the binding verification. **Rejected** because:

* The exit-criterion text per PILLAR-PLAN §2 Pillar E is the binding gate for the Stable flip; deferring would block the flip indefinitely.
* The four per-primitive coherence rows verify each primitive in isolation but do NOT verify composition; the binding test's purpose is composition verification.
* Pillar D Week 12 + Pillar C Week 12 + Pillar B Week 5 + Pillar A Week 6 each shipped their exit-criterion test in the same closing-week commit; Pillar E follows the same convention.

### D173-Alt1: Exclude the tier-suggestion row from the binding test

Scope the binding test to dedup + cache + lineage per ADR-0032 D147's original text. **Rejected** because:

* Leaves one of the four Pillar E primitives unverified in the binding scenario.
* The integrated-scenario shape catches per-primitive integration bugs the per-primitive coherence rows miss (the per-Person tier-suggestion's signal source IS the lineage primitive's `source_skill`; cross-primitive plumbing is what the binding test verifies).
* Per the handoff's Design-decisions recommendation (a), the integrated-scenario shape is the most-coverage choice.

### D173-Alt2: Include the `enrolled_source_skill_backfill` event class in the binding test

Add a synthetic historical `enrolled` event + run the ledger migration inside the binding test. **Rejected** because:

* The binding test is for NEW enrollments (post-Week-9-11 emit shape per ADR-0036 D170); the backfill event class is for historical enrollments.
* The backfill event class's coverage lives in `tests/test_migrations_ledger_0007.py` (Week 9-11's 28-test unit suite); duplicating in the binding test adds noise without coverage gain.
* Per the handoff's Design-decisions recommendation (b), the binding test stays scoped to the NEW-enrollment flow.

### D173-Alt3: Drop the cache-hit row from the binding test

Skip the post-dispatch re-verify step; assert only on the cache substrate's population (the `email` + `verification_response` fields on the cost event). **Rejected** because:

* The cache primitive's HIT path is the cost-avoidance signal per ADR-0034 D155; verifying only the substrate's shape (without verifying the hit fires) leaves the cache primitive only verified by its own per-primitive coherence rows.
* The post-dispatch re-verify step models a real operator workflow (the dispatcher pre-send email re-check per Pillar A's standard flow); exercising it in the binding scenario captures the cache primitive's role in the integrated cost-bound exit criterion.
* The binding text per PILLAR-PLAN §2 Pillar E says "ONE Reoon credit consumed" — the post-dispatch re-verify is the surface that DEMONSTRATES the one-credit bound holds even under re-verification load.

### D174-Alt1: Full-deterministic-clock via `ledger._now_iso` monkey-patch (per Pillar D Week 12 ADR-0031 D140 precedent)

Patch `orchestrator.ledger._now_iso` to anchor every ledger-emitted ts. **Rejected** because:

* Pillar E's binding test asserts on event counts + field values, NOT on ledger ts values. The Pillar D Week 12 precedent needed the full patch because the funnel CLI's reproducibility assertion required byte-identical JSON output (per ADR-0031 D140); Pillar E has no such reproducibility surface.
* Adds ~10 LOC of fixture scaffolding for no behavior gain.
* The 30-day cache TTL window comfortably accommodates real-time skew between cost-emit ts + cache-lookup now.

### D174-Alt2: No-clock-patching — accept real-time variance

Skip all `now` kwargs + `email_verification_cache.datetime` patching. **Rejected** because:

* The cache primitive's `cache_age_days` calculation depends on (now - cost_event_ts); without the post-dispatch lookup's patched `now`, the cache HIT could fail intermittently if real-time drift makes `now - cost_ts` exceed TTL (extreme edge case, but possible on slow CI).
* The tier primitive's funding-recency window calculation depends on the supplied `now`; without explicit `now`, the funding_recency_days signal computes against real-time, which could surface as a flaky test if the test corpus' funding_date drifts past a recency bucket.
* The deterministic-clock discipline per ADR-0031 D140 + ADR-0034 D156 + ADR-0035 D162 is the established convention; abandoning it for Week 12 contradicts the per-week pattern.

### D174-Alt3: Extract `tests/_test_helpers/deterministic_clock.py` per RETRO-pillar-d.md item 8

Centralize the per-test `now` patching scaffolding. **Rejected** because:

* Helper extraction was named as a future-Pillar concern per RETRO-pillar-d.md item 8 — deferred until ≥6 consumers materialize. At Week 12, the binding test is the FOURTH consumer (after the funnel CLI + cache primitive + tier primitive + lineage primitive's compute_canonical_raw_input_hash); helper extraction is premature.
* The per-test `now` pattern stays inline + readable; extraction would add indirection without proportional reuse benefit at Week 12.
* Pillar I OSS bring-up MAY extract the helper IF the per-test boilerplate grows past the threshold per the RETRO-pillar-d.md item-8 guidance.

### D175-Alt1: Holistic exit review as the Stable-flip gate (replacing the binding test)

Treat the holistic review (per `.planning/REVIEW-pillar-e-holistic.md` — TBD if shipped) as the gate; the binding test is observational. **Rejected** because:

* Pillar D Week 12's precedent (ADR-0031 D141) names the binding test as THE gate; holistic review is an addendum surface.
* Holistic reviews surface operator-visible findings (P1/P2/P3) but do NOT verify structural composition; the binding test is the structural verification.
* Pillar E's holistic review is OPTIONAL at the Week 12 close (Pillar D shipped one; Pillar A + B + C did not). Making it gating would impose a new artifact requirement without per-pillar precedent.

### D175-Alt2: Per-week-reviewer sign-off as the Stable-flip gate

Treat each per-week reviewer's "no P1 outstanding" verdict as the gate. **Rejected** because:

* Per-week reviewers' findings are scope-bounded to the per-week commit's changes; the BINDING TEST is the exit-criterion vehicle's structural verification across all twelve Pillar E weeks.
* Per-week sign-off is a complement, not a substitute; the binding test demonstrates the per-primitive surfaces compose per the exit-criterion text.
* Pillar D + C + B + A + E's stable-flip discipline names the binding test (or exit-criterion vehicle) as THE gate; per-week reviews are gates on per-week commits, not pillar stability.

### D175-Alt3: Full Pillar G dashboard validation as the Stable-flip gate

Defer the Stable flip until Pillar G ships the operator-facing dashboards consuming the Pillar E surfaces. **Rejected** because:

* Pillar G is a downstream consumer of the Pillar E surfaces (per the §Downstream pillar impact sections of ADR-0032 through ADR-0036); coupling Pillar E's stable flip to Pillar G's timeline indefinitely defers the flip.
* The Pillar A/B/C/D stable flips each landed independent of their respective downstream-pillar dashboards; Pillar E follows the same convention.
* The dashboards consume what Pillar E ships; Pillar E's surfaces are stable independent of dashboard consumption.

### D176-Alt1: Ship the retrospective in a separate post-pillar-stable-flip reflection commit

Stable-flip in Week 12 main commit; retrospective lands days/weeks later. **Rejected** because:

* Per ADR-0031 D141 the retrospective IS part of the stable-flip artifact; splitting creates a temporal gap where Pillar E is Stable but the operator-readable evidence is missing.
* Pillar D's Week 12 main commit shipped the retrospective inline; Pillar E follows the same convention.
* Future Pillar F's author reads RETRO-pillar-e.md before authoring Pillar F's first ADR; deferring breaks the per-pillar continuity.

### D176-Alt2: Ship the retrospective after a 1-week stabilization period

Wait for the binding test to run in CI for ≥7 days; then ship the retrospective. **Rejected** because:

* No precedent in Pillar A / B / C / D for stabilization-period reflection.
* The per-week patterns are documented continuously through the twelve weeks (in HANDOFFs + ADRs + audit sections); the retrospective synthesizes them at the stable-flip moment — no additional observation is needed.
* The "≥1 day CI" requirement per D175 is observational, not gating.

### D176-Alt3: Defer the retrospective to Pillar I OSS bring-up

Ship Pillar E Stable without the retrospective; the retrospective lands in a future Pillar I commit. **Rejected** because:

* Defers the synthesis indefinitely; the per-pillar retrospective discipline is the operator-readable evidence of the per-week pattern continuity.
* Pillar F's author reads RETRO-pillar-e.md before authoring Pillar F's first ADR per the same convention Pillar E followed reading RETRO-pillar-d.md.
* The retrospective's authoring cost (~30-45 minutes per Pillar D's precedent) is bounded; deferral has no benefit.

### D177-Alt1: Skip the audit extension since no new surfaces

The Week 12 commit has UNCHANGED verdict; skip the audit section. **Rejected** because:

* The per-week audit discipline per ADR-0032 D146 is "every Pillar E week's commit extends the audit OR confirms unchanged." Skipping creates a structural gap.
* A future audit reader sees the Weeks 1-11 sections + the missing Week 12 entry; the audit's continuity is a load-bearing reading surface.
* The UNCHANGED verdict IS the audit's signal that Week 12 is verification-only; the explicit section documents the four-primitive composition for future readers.

### D177-Alt2: Combine Week 12 verdict with the Week 9-11 section

Append the Week 12 UNCHANGED verdict as a footnote to Week 9-11's section. **Rejected** because:

* Per the per-week-section convention each Pillar E week's commit gets its own section; combining erases per-week traceability.
* Future Pillar F / G / H / I / J authors trace per-week extensions to per-week commits; the per-week section discipline supports the trace.

### D177-Alt3: Defer the audit extension to the Week 12 per-week-reviewer follow-up commit

Ship the binding test + this ADR + the retrospective in the main commit; the audit extension comes in the per-week-reviewer follow-up. **Rejected** because:

* Per ADR-0036 §"Why NOT split the audit into a follow-up commit" the atomicity contract is "primitive + audit + ADR + tests + handoff land together."
* The audit extension's content is determinable at main-commit-authoring time (the binding test's consumer surface is known); deferring would let a P1 latent-bug pattern slip through if the follow-up is delayed.
* The per-week-reviewer follow-up handles per-review findings, not structural artifacts.

## Consequences

### Positive consequences

* **The Pillar E exit criterion is structurally verified.** The binding test composes all four Pillar E primitives in a single integrated scenario matching the PILLAR-PLAN §2 binding text. The "discovering the same person via three skills in one day consumes one Apollo credit, one Reoon credit, zero duplicate enrollments" claim is now a passing test.
* **Pillar E flips to Stable.** Future Pillar F / G / H / I / J week-1 commits depend on "Pillar E Stable" per the PILLAR-PLAN §6 dependency graph; Week 12's flip unblocks the dependents.
* **The four Pillar E primitives' composition is verified.** The per-primitive coherence rows verify each primitive in isolation; the binding test verifies they compose per the exit-criterion text. Cross-primitive integration bugs (e.g., the tier primitive's `source_skill` read path's coupling to the lineage primitive's stamping site) are caught by the binding test.
* **The retrospective + the audit + the handoff land in the same commit.** The atomicity contract per Pillar E's discipline is preserved; future Pillar F's author has the complete Pillar E close in one git revision.
* **The per-week-reviewer pattern's compounding value is documented.** Per `.planning/RETRO-pillar-e.md` §"What worked" the per-week-reviewer fresh-context advantage caught 8+ P2 bugs across Weeks 4-5 / 6-8 / 9-11 that the inline author missed. The pattern's quantified evidence informs Pillar F's per-week trajectory.

### Negative consequences

* **Test count grows by 1 (the binding test row).** The cumulative test count: 2684 (post-Week-9-11) + 1 = 2685. The growth is bounded.
* **Skip count drops by 1 (the binding test un-skips).** From 14 skips down to 13. The remaining 13 skips are all live skips for live-network or environment-dependent tests (per Pillar B Week 1 stub conventions).
* **The `tests/test_multi_channel_coherence.py` file's size grows.** Currently ~6284 lines; this commit adds ~250-350 lines (the binding test body). Approaching the ~6500 LOC threshold; if a future Pillar F / G / H / I / J week's extension crosses ~7500 LOC the split argument resurfaces.
* **No new primitives ship at Week 12.** The Pillar E close is verification-only. Operators who expected a Week 12 surface (e.g., a cost-per-quality-prospect dashboard) find that surface is a Pillar G forward-reference. PILLAR-PLAN §6 Pillar E row's "deferred items" list names every deferred surface explicitly.
* **The retrospective + the handoff + the audit + this ADR all land in one commit.** The Week 12 main commit's diff is larger than typical Pillar E weeks (~5 documents touched + 1 test added + 1 ADR + 1 retrospective + 1 handoff + 1 audit extension). Operators reviewing the commit need to read all surfaces; the per-week-reviewer protocol handles the volume per the Pillar A + B + C + D + E pattern.

### Risks

The asymmetric-failure-cost calculus (PILLAR-PLAN §0) carries:

* **Binding test passes locally but fails on CI (P2):** real-time skew between cost-emit ts + cache-lookup now exceeds the post-dispatch lookup's 5-minute anchor. **Bounded by** the 30-day TTL (5-minute skew is well within 30-day window) + the partial-deterministic-clock contract per D174 (`email_verification_cache.datetime.now` patched for the post-dispatch lookup ensures the cache HIT predictably fires).
* **Binding test passes Week 12 but regresses on a future Pillar F / G / H / I / J week's primitive extension (P2):** a downstream pillar's commit silently broadens the input space + breaks one of the four Pillar E primitives' coherence. **Bounded by** the cross-pillar surface audit's per-week-extension discipline (every future pillar's week extends the audit + verifies UNCHANGED on the Pillar E surfaces) + the binding test's continuous CI runs.
* **The "Pillar E Stable" claim's future re-validation (P3):** a future Pillar I OSS bring-up week's commit extends the Pillar E primitives (e.g., the legacy `source_channel` fallback removal) + the stable claim needs re-verification. **Bounded by** the per-pillar stable-flip checklist's re-runnability (the binding test stays in CI; any regression surfaces at the per-week reviewer of the modifying commit).

The framework's existing safeguards bound the regression failure modes by design.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The binding test consumes the ledger as the canonical event surface; no new SoT.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The binding test exercises the discovery + enrollment phase (upstream of the dispatcher's two-phase commit); no changes to send-path semantics.
* **I3 — Atomic per-Person enrollment.** Preserved. The binding test's enrollment step exercises `enrollment.enroll_person` per its existing per-Person atomic contract (Phase 5.5 Week 1b).
* **I4 — Per-channel state isolation.** Preserved. The binding test's events carry the channel-on-every-event invariant per ADR-0014 D33 (`discovery_dedup_hit.channel: "none"` + `email_verification_cache_hit.channel: "email"` + `tier_suggested.channel: "none"` + `enrolled.channel`: as today).
* **I5 — Migration framework discipline.** Preserved. Week 12 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The binding test's emitted events carry the channel field per the per-primitive shape from Weeks 2 + 4-5 + 6-8 + 9-11.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved. The binding test exercises the four primitives' refuse-loud invariants (the lineage primitive's construction-time validation; the dedup primitive's enum validation on source_skill; the cache primitive's TTL boundary check; the tier primitive's threshold matching).
* **I8 — Privacy-respecting (`source_list` operator-private).** Preserved. The binding test's emitted events carry `source_list` per the existing convention; the Layer 1 defense per ADR-0032 D148 (the `test_source_list_is_operator_private` test corpus pin) continues to hold.

## Downstream pillar impact

* **Pillar F (Voice corpus + draft quality, begins Week 25).** Pillar F's first ADR (whoever writes it) reads RETRO-pillar-e.md before authoring + inherits the per-week pattern. The binding test's coherence-vehicle extension precedent is the model for Pillar F's exit-criterion-test landing — Pillar F should land a `TestPillarFExitCriterion` stub class at Week 1 + un-skip the binding test at Week 12 per the same trajectory.

* **Pillar G (Observability, begins Week 31).** Pillar G dashboards consume the four Pillar E event classes directly (`discovery_dedup_hit` / `email_verification_cache_hit` / `tier_suggested` / `enrolled` with the new `source_skill` field). The cost-per-quality-prospect dashboard per Pillar E's exit-criterion sub-bullet (d) is a Pillar G deliverable; the binding test's UNCHANGED verdict at Week 12 confirms the surfaces are stable for Pillar G consumption.

* **Pillar H (Real-time + scale, begins Week 37).** The dedup primitive's per-call O(N) index rebuild + the cache primitive's per-call O(N) ledger walk + the tier primitive's per-call config load are read-path performance concerns Pillar H may optimize. Week 12's binding test passes against the current O(N) implementations; Pillar H's optimizations are content-additive (the primitives' contracts stay; the implementations get caching/indexing).

* **Pillar I (Multi-tenant + OSS hardening, begins Week 43).** Pillar I CLI extensions per the deferred-items list (per `.planning/HANDOFF-pillar-e-week-12.md` §"Carry-overs deferred"): `discovery_dedup replay --since <date>` + `email_verification_cache replay --since <date>` + `email_verification_cache purge --email <addr>` + `tier_assignment retier --since <date>` + `tier_assignment calibrate --corpus <vault>` + `discovery_lineage backfill --bulk --csv <path>` + `discovery_lineage audit`. Pillar I also ships doctor preflight extensions for backfill-confidence + tier-weights drift + lineage-source-skill enum sync.

* **Pillar J (Compliance + audit, begins Week 49).** GDPR-purge transaction extends to purge the `discovery_lineage.raw_input_hash` field from a Person's identity_keys block when the Person requests forget (per ADR-0036 §Downstream pillar impact's Pillar J row). The binding test does NOT exercise GDPR-purge; Pillar J's commit extends the cross-pillar audit with the per-Person purge path's verdict.

## Migration / rollout

**Week 12 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Week 9-11). Operators upgrading from Week 9-11 to Week 12:

1. **Operator updates the framework** to Week 12's commit (the standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since the pending migrations are already applied at Week 9-11 ship time.
3. **Operator runs `python -m pytest tests/test_multi_channel_coherence.py::TestPillarEExitCriterion -v`** to verify the binding test passes locally. Optional but recommended for operators wanting end-to-end Pillar E verification.

No operator-facing surface changes. The binding test is internal verification; operators benefit from the structural stability the test pins.

## Existing-operator seed

**Pillar E Week 12 ships no operator-side state changes.** The binding test is verification-only; no operator data migration; no operator CLI changes; no operator-tunable config changes.

The §Existing-operator seed convention from prior Pillar E weeks does NOT apply at Week 12 — there is no operator action required beyond the standard framework upgrade.

## References

- **ADR-0032 (D142 + D146 + D147 + D148)** — Pillar E foundation (the discovery_lineage shape + the cross-pillar audit + the exit-criterion vehicle scope + the privacy invariant).
- **ADR-0033 (D149-D153 + §Amendment 2026-05-24)** — Pillar E Week 2-3 dedup primitive + the canonical caller pattern + the per-skill integration discipline.
- **ADR-0034 (D154-D159)** — Pillar E Week 4-5 email-verification cache primitive + the cost-event substrate extension.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier auto-assignment primitive + the operator-tunable weights config.
- **ADR-0036 (D166-D171)** — Pillar E Week 9-11 discovery-lineage stamping refactor + vault migration 0005 + ledger migration 0007 + research-prospect integration.
- **ADR-0014 (D33 + D37)** — Pillar C foundation (channel-on-every-event invariant + the cross-pillar coherence test vehicle's single-file rationale).
- **ADR-0025 (D101)** — Pillar D foundation (the exit-criterion vehicle's single-file rationale extended).
- **ADR-0031 (D136 + D141)** — Pillar D Week 12 (the binding-test-as-gate + per-pillar stable-flip checklist + per-pillar retrospective discipline precedent).
- **`.planning/REVIEW-pillar-e-surface-audit.md`** — the load-bearing cross-pillar audit; Week 12 extends with §45+ (UNCHANGED verdict).
- **`.planning/RETRO-pillar-e.md`** — this Week 12 commit's Pillar E retrospective.
- **`.planning/RETRO-pillar-d.md`** — the Pillar D Week 12 retrospective; informs Pillar E's eight carry-forward outcomes.
- **`.planning/HANDOFF-pillar-e-week-12.md`** — this week's handoff document.
- **`.planning/HANDOFF-pillar-f-week-1.md`** — the breadcrumb for Pillar F (Voice corpus + draft quality begins Week 25).
- **`docs/PILLAR-PLAN.md` §2 Pillar E + §6 Pillar E row** — the binding exit-criterion text + the per-week trajectory ticker that flips to **Stable** at this commit.
- **`docs/SOURCES-OF-TRUTH.md` Discovery-lineage row** — the SoT registry's pre-declared row (Pillar E formalized through Week 9-11; Week 12 confirms stable).
