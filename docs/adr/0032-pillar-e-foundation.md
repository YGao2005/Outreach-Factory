# ADR-0032: Pillar E foundation — discovery lineage shape, pre-enrichment dedup contract, email-verification cache, tier auto-assignment substrate, cross-pillar integration audit, exit-criterion vehicle scope, privacy-respecting invariant

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** E (Discovery quality + lineage — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0008 shipped Pillar A (declarative policy engine). ADRs 0009-0013 shipped Pillar B (migration framework + synthetic-replay exit-criterion vehicle). ADRs 0014-0024 shipped Pillar C (multi-channel coherence — four channels, six reconcile passes, five per-channel policy migrations). ADRs 0025-0031 shipped Pillar D (reply + conversation handling — rule + LLM classifier, auto-unsubscribe, conversation state machine, win/loss attribution, funnel CLI). Pillar E — discovery quality + lineage (`docs/PILLAR-PLAN.md` §2 Pillar E, Weeks 19–30) — extends the substrate at the OTHER end of the funnel: every prospect carries durable provenance from the moment a discovery skill surfaces them, the pipeline refuses to spend Apollo / PDL / Reoon credits on duplicates the system already knows about, the email-verification result is cached so a 30-day round-trip cycle doesn't burn Reoon dollars repeatedly, and tier assignment derives from firmographic + intent signals rather than operator manual stamping. The substrate is in place; what Pillar E Week 1 needs is the **convention-setting decisions** the next eleven weeks build on.

Pillar D's Week 12 retrospective (`.planning/RETRO-pillar-d.md` §"What to do differently in Pillar E") named EIGHT carry-forward recommendations: (1) land the Pillar E discovery-source coherence test in Week 1, not Week N (Pillar C Week 12's exit-criterion stress test caught a Pass A latent bug 8 weeks after introduction; Pillar D's Week 1 audit caught Pass B's pre-existing channel-on-every-event gap); (2) audit pre-existing surfaces for symmetric assumptions whenever extending a Pillar A/B/C/D primitive; (3) continue the per-week-handoff + per-week-review-with-follow-up-commit + per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact + holistic-exit-review discipline; (4) continue the per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact convention; (5) design the legal-liability + privacy-respecting invariants at Week 1; (6) design the per-source-symmetry-with-shared-classifier pattern at Week 1; (7) bake the doc-sweep before commit; (8) anticipate the deterministic-clock requirement.

The seven concerns this ADR resolves:

1. **Discovery lineage shape must be pinned across all four discovery skills before per-skill stamping refactors ship.** The four existing skills (`find-leads`, `find-funded-founders`, `competitor-customers`, `research-prospect`) all stamp varying provenance shapes today (`source_channel` + `source_list` on some events; nothing on others). The `docs/SOURCES-OF-TRUTH.md` Discovery-lineage row already pre-declares the contract — *"Person note `identity_keys.discovery_lineage:` (source skill, source list, scraped-at, raw-input hash) | Ledger `enrolled` event carries the same fields denormalized | Pillar E formalizes"*. D142 pins the canonical shape so the per-week refactors (Week 9-11) land against an established target.

2. **Pre-enrichment dedup is the load-bearing exit-criterion primitive.** The Pillar E exit criterion (PILLAR-PLAN §2 Pillar E binding text): *"discovering the same person via three skills in one day consumes one Apollo credit, one Reoon credit, zero duplicate enrollments."* Today, three skills discovering the same person produce three enrichment calls (Apollo credit per call) + three Reoon verifications (Reoon credit per call) + three identity-keys reconciliations (the strict-policy refusal-or-merge surface). The exit-criterion requires that the SECOND and THIRD discovery skills consult a dedup primitive BEFORE the enrichment call lands. D143 pins the contract; Week 2-3 ships the primitive.

3. **Email-verification cache shape.** Reoon verification today is per-call (every dispatcher-side `verify_with_reoon` invocation re-spends ~$0.001/email). Operators iterating on the queue + repeatedly verifying the same prospect see cumulative Reoon spend that the exit criterion (one Reoon credit per discovery-source coalition) requires bounded. D144 pins the cache shape: per-email TTL-30-day cache; cache hit emits a NEW `email_verification_cache_hit` event class instead of `cost_incurred`; cache miss falls through to the existing Reoon path + emits `cost_incurred` per ADR-0006 unchanged.

4. **Tier auto-assignment substrate.** Today `Person.research_tier` is operator-manual per ADR-0007's "v1 hardcoded to `Person.research_tier`" note. Pillar E's "tier auto-assignment from signals" exit-criterion bullet (PILLAR-PLAN §2 Pillar E) means firmographic signals (Apollo `organization_size` / `industry` / `funding_stage`) + intent signals (discovery_lineage.source_skill — `find-funded-founders` implies high-intent per the recent-funding signal) compute a SUGGESTED tier that operators can override per ADR-0007's existing `manual_override` event class. D145 pins the substrate; Week 6-8 implements per-signal weights.

5. **Cross-pillar integration audit — THE load-bearing anti-regression decision.** Per Pillar D Week 1's D99 + Pillar C Week 12's surfaced Pass A bug + Pillar B Week 5's late-discovered cross-category-dependency surprise, every Pillar E week's per-week review MUST audit existing Pillar A/B/C/D surfaces for symmetric assumptions when Pillar E's commit silently expands the input space. D146 pins the audit + names the new event classes Pillar E adds (`discovery_dedup_hit`, `email_verification_cache_hit`, optionally `tier_suggested`) so the audit lands against concrete event-type names; `.planning/REVIEW-pillar-e-surface-audit.md` is the load-bearing artifact future Pillar E weeks extend.

6. **The Pillar E exit-criterion verification vehicle must exist in Week 1.** Per PILLAR-PLAN §2 Pillar E binding text: *"discovering the same person via three skills in one day consumes one Apollo credit, one Reoon credit, zero duplicate enrollments."* Without the vehicle landing in Week 1, the cross-cutting properties (dedup hit-rate; cache hit-rate; tier-suggestion accuracy; per-Person discovery-source funnel reproducibility) would only surface end-of-pillar, repeating Pillar B Week 5 + Pillar C Week 12's pattern. D147 names the vehicle scope: `tests/test_multi_channel_coherence.py` is EXTENDED with `TestDiscoveryLineage` + `TestPreEnrichmentDedup` + `TestEmailVerificationCache` + `TestTierAutoAssignment` + `TestPillarEExitCriterion` test classes (Option A per ADR-0025 D101's single-file rationale).

7. **Discovery-source privacy invariant.** The `discovery_lineage.source_list` field reveals WHICH curated list a prospect was found on (`[[2026-05-24-funded-founders]]`, `[[2026-05-24-competitor-customers-acme]]`, etc.). If exposed via dashboards, this surfaces operator-internal segmentation strategies (which competitors the operator is mining; which VCs the operator is tracking; which curated lists the operator considers high-value). D148 names the privacy invariant: `source_list` is operator-private (not surfaced in any Pillar G dashboard's operator-facing view; only available via direct ledger query). Per the RETRO-pillar-d.md item-5 recommendation, the invariant is named in Week 1; a FIVE-layer defense (analogous to ADR-0025 D97's CAN-SPAM defense) is design-deferred unless a specific privacy concern crystallizes — Week 1 ships the structural defense at Layer 1 (test-corpus pin) only.

Risks this ADR mitigates by design: **R001 (identity-graph false-merge cascade)** continues mitigated by `identity.resolve_strict`'s strict policy; Pillar E's pre-enrichment dedup is the COMPLEMENT (the resolver runs AFTER enrichment populates the keys; the dedup primitive runs BEFORE the enrichment call lands), with the asymmetric-failure-cost calculus biased toward "false-positive dedup is one missed enrollment we re-discover next surfacing; false-negative dedup is one Apollo credit + Reoon credit we burned that the exit criterion forbids."

Three new risks surface in this ADR's authoring + named in `docs/RISK-REGISTER.md`:
- **R018 (discovery-source poisoning)** — an operator scrapes an inaccurate list (a competitor's customer-list page that lists prospects not actually using the competitor; a VC's portfolio page that lists deals that never closed); the downstream `closed_won` attribution incorrectly credits the misattributed source. Mitigation by design: the `source_list` field's value is operator-provided (no framework-side trust); operator audit of dashboards is the recovery surface; Pillar I CLI doctor extension verifies source-list shape.
- **R019 (pre-enrichment dedup false-positive)** — two distinct people share an identity-key partial (shared family email; cofounder mailbox; shared LinkedIn slug after a profile takeover); the dedup primitive collapses them. Mitigation by design: the dedup primitive REUSES `identity.find_matches` + `identity.resolve_strict` (the same strict-policy refusal that already handles 2+ ambiguous matches surfaces a `discovery_dedup_conflict` instead of silently collapsing); the conflict path emits the same operator-visible report shape as today's `enrollment_conflict`.
- **R020 (email-verification cache staleness)** — a 30-day-old verified email becomes invalid (mailbox change, domain change, employee left); the cache returns the stale result; the dispatcher sends to the now-invalid address. Mitigation by design: 30-day TTL + cache-hit emits a `email_verification_cache_hit` event (operator-visible); operators flagging unexpected bounces can `python -m orchestrator.email_verification_cache evict --email <addr>` (Pillar I CLI extension); the existing `bounce_detected` Pass B event flow naturally surfaces stale-cache failures.

## Decision

### D142. Discovery lineage shape — `identity_keys.discovery_lineage:` sub-block

Pillar E ships a new `discovery_lineage:` sub-block inside the existing `identity_keys:` Person frontmatter block. The shape:

```yaml
identity_keys:
  linkedin: in/dylan-txa
  emails:
    - dylan@example.com
  github: dylan
  twitter: dylantx
  country: US
  discovery_lineage:
    source_skill: find-funded-founders     # one of {find-leads, find-funded-founders, competitor-customers, research-prospect, manual}
    source_list: "[[2026-05-24-funded-founders]]"   # operator-supplied list filename / tag (operator-private per D148)
    scraped_at: "2026-05-24T14:32:18Z"      # ISO timestamp at scraping time
    raw_input_hash: "sha256:9f86d081884c..."  # SHA256 of the canonical raw input (per-skill canonicalization at the skill level)
```

**Why an `identity_keys` sub-block (rejected: top-level Person frontmatter field; rejected: standalone `provenance:` block).** Three reasonable shapes: (a) sub-block of `identity_keys:` (D142's choice); (b) top-level Person frontmatter field (parallel to `research_tier:` / `pipeline_stage:` / `conversation_status:`); (c) standalone `provenance:` block at the top of Person frontmatter. Pillar E Week 1 picks (a). The rationale:

* **The lineage IS the provenance of the identity_keys themselves.** The `linkedin` / `emails` / `github` / `twitter` fields are scraped from a specific source at a specific time; the lineage's `scraped_at` + `raw_input_hash` answer "where did THESE keys come from?" — the structural home is alongside the keys.
* **Top-level placement (option b) would suggest per-Person mutable state.** Pipeline-state fields (`pipeline_stage`, `conversation_status`) change over the prospect's lifecycle; the discovery_lineage is set ONCE at enrollment + immutable thereafter. Top-level placement creates a misleading mental model.
* **Standalone `provenance:` block (option c) splits the keys-and-their-provenance question across two YAML blocks.** Operators reading a Person note must jump between blocks to answer "where did this prospect come from?" — the cognitive cost is higher than the structural gain.

**Schema:**

| Field | Type | Required | Semantics |
|---|---|---|---|
| `source_skill` | enum string | YES on NEW enrollments | One of `{find-leads, find-funded-founders, competitor-customers, research-prospect, manual}`. The discovery skill that surfaced the prospect. Operator-tunable enum frozen in `orchestrator/discovery_lineage.py::SOURCE_SKILLS` (Week 2 ships); enum-validated at construction time. |
| `source_list` | string | YES on NEW enrollments | The list filename or operator-supplied tag (e.g., `[[2026-05-24-funded-founders]]`). Operator-PRIVATE per D148 — not surfaced in operator-facing dashboards. Free-form (operator's convention; the framework treats as opaque string). |
| `scraped_at` | ISO 8601 timestamp | YES on NEW enrollments | UTC timestamp at scraping time. The skill-side timestamp; downstream consumers use this to compute "how stale is this scrape?" |
| `raw_input_hash` | SHA256-prefixed hex string | YES on NEW enrollments | `sha256:<hex>` — the SHA256 of the canonical raw input (per-skill canonicalization). Used for de-duplication of scrapes (operator scraping the same list twice produces the same hash). |

**Each field MUST be present on every NEW Person enrollment.** Pre-Pillar-E operators see absence (Week 1 ships NO migration; Week 9-11's vault migration backfills from existing `_source.md` files where parseable, else stamps `source_skill: manual` per the existing-operator seed).

**Closed enum for `source_skill`.** Frozen at five values in Week 1; future skills (Pillar I OSS bring-up may add `import-from-csv`, etc.) extend the enum with a coordinated ADR amendment. The enum-validation at construction time refuses unknown values loudly — a future skill author who omits the enum extension fails Pass G's stamping check.

**Operator-private posture for `source_list`.** Per D148 the field is operator-private. The framework treats the field as an opaque string; Pillar G dashboards filter on `source_skill` (operator-deliberate aggregation level — "how many of my funded-founder discoveries became `closed_won`") but NEVER on `source_list` (which would surface "the operator's `[[2026-05-24-acme-customers]]` list yielded N customers" to anyone with dashboard access).

**Pin:** `tests/test_multi_channel_coherence.py::TestDiscoveryLineage::test_discovery_lineage_is_identity_keys_sub_block` asserts the structural placement. **Stub lands in this Week 1 commit + un-skips when the canonical block lands in Week 2.**

### D143. Pre-enrichment dedup contract — load-bearing exit-criterion primitive

Before any discovery skill calls Apollo / PDL / Reoon, it MUST query the dedup primitive: *"does any existing Person carry an identity_key (email / linkedin / twitter / github) that matches THIS candidate's pre-enrichment partial?"* If yes, increment a `discovery_dedup_hit` ledger event (NEW event class per D146) on the existing Person + skip the enrichment.

The contract:

```python
from orchestrator.discovery_dedup import check_dedup  # Pillar E Week 2 ships

result = check_dedup(
    candidate_partial=IdentityKeys(emails=frozenset({"dylan@example.com"})),
    source_skill="find-leads",
    source_list="[[2026-05-24-find-leads-q2]]",
)

if result.is_duplicate:
    # Emit discovery_dedup_hit event referencing result.existing_person_id;
    # skip the Apollo + PDL + Reoon call entirely.
    led.append({
        "type": "discovery_dedup_hit",
        "person_id": result.existing_person_id,
        "candidate_partial": result.candidate_partial.to_serializable(),
        "matched_classes": sorted(result.matched_classes),
        "source_skill": "find-leads",
        "source_list": "[[2026-05-24-find-leads-q2]]",
        "channel": "none",  # dedup is channel-agnostic per ADR-0014 D33 channel-on-every-event invariant
        "_emitted_by": "discovery_dedup",
    })
    continue  # next candidate; no enrichment call
else:
    # Proceed with the enrichment call as today.
    apollo_result = apollo.enrich(...)
    ...
```

**The contract is LOAD-BEARING per the exit criterion** — three skills discovering the same person in one day MUST consume one Apollo credit + one Reoon credit + zero duplicate enrollments. Without the contract, the THIRD skill's Apollo + Reoon spend is unmitigated.

**Atomicity contract.** The check + the enrichment-call decision is NOT an atomic primitive (the framework cannot prevent two concurrent skills from BOTH checking, BOTH receiving "no duplicate", BOTH proceeding to Apollo). The atomicity contract per Pillar A's `identity.resolve_strict` covers the post-enrichment phase (the SECOND skill's enrichment lands + the resolver refuses-as-conflict because the FIRST skill's enrollment populated the keys). Pillar E's dedup is the FAST-PATH for the common case (sequential discovery surfaces hitting the dedup primitive's index before paying for enrichment); the concurrent-race case falls back to the existing identity-resolver's strict policy. The exit-criterion test (D147 vehicle) verifies the sequential case binds the cost.

**Dedup primitive scope:**

| Pre-enrichment input | Dedup check | Behavior on hit |
|---|---|---|
| `email` only | `find_matches` index intersection on `emails` | Skip enrichment; emit `discovery_dedup_hit` referencing existing person |
| `linkedin` only | `find_matches` index intersection on `linkedin` | Skip enrichment; emit `discovery_dedup_hit` referencing existing person |
| `name + company` only | NO dedup (name is not a match key per `identity.py` policy) | Proceed with enrichment; post-enrichment resolver handles |
| `email + linkedin` | `find_matches` index intersection on EITHER key | Skip enrichment if EITHER matches; conflict-pathway if BOTH match different people |

**Failure modes the contract defends against:**

| Failure mode | Defense |
|---|---|
| Concurrent enrollments from two skills | Existing `identity.resolve_strict` strict policy refuses post-enrichment merge of 2+ matches; emits `enrollment_conflict`. |
| Dedup-index staleness across multi-day scrapes | Index is rebuilt per-call from `build_index(people_dir)` — always fresh. |
| Identity-key partial-match ambiguity (shared family email + distinct LinkedIn) | Per `identity._is_ambiguous_single_class_email_match`'s existing refinement — escalates to `discovery_dedup_conflict` (mirroring `enrollment_conflict`). |
| Operator scraping an outdated/inaccurate list | The lineage's `raw_input_hash` field surfaces the operator's scrape provenance for audit. R018 (discovery-source poisoning) names this risk explicitly. |

**Pin:** `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup::test_three_skills_one_day_consume_one_apollo_credit` is the binding exit-criterion-adjacent test for the dedup primitive. **Stub lands in this Week 1 commit + un-skips when the primitive ships in Week 2-3.**

### D144. Email-verification cache shape

The Reoon (or alternative provider) verification result is cached per-email for 30 days. The cache primitive lives in `orchestrator/email_verification_cache.py` (NEW module Week 4-5 ships); reads + writes are atomic per ADR-0011 D24's append-only ledger discipline.

**Cache shape:**

```python
{
    "type": "email_verification_cache_hit",
    "person_id": "<pid>",                         # the Person whose email was verified
    "email": "dylan@example.com",                 # the email looked up
    "channel": "email",                           # email-specific per ADR-0014 D33
    "cached_at": "2026-05-01T10:00:00Z",          # when the original Reoon call landed
    "ttl_days": 30,                               # cache TTL
    "cache_age_seconds": 1956123,                 # cached_at_now - cached_at
    "cached_result": {                            # the Reoon response shape (preserved verbatim)
        "status": "valid",
        "score": 95,
        "is_disposable": false,
        ...
    },
    "_emitted_by": "email_verification_cache",
}
```

**Cache hit emits `email_verification_cache_hit` event (NEW per D146) INSTEAD of `cost_incurred`.** The cache hit IS the cost-avoidance signal; the Pillar G dashboard aggregates `email_verification_cache_hit` against `cost_incurred.source=reoon` to compute the operator's cache hit-rate + the operator's Reoon spend avoidance.

**Cache miss falls through to the existing Reoon call + emits `cost_incurred` per Pillar A unchanged.** The existing `enrich_emails.emit_reoon_cost_event` path stays as-is; the cache wraps the Reoon call site.

**Cache storage:** the cache is a derived view of the ledger event stream — specifically, the most-recent `cost_incurred.source=reoon` event per email's `payload` field carries the Reoon response. The cache primitive `lookup(email)` queries the ledger for the most-recent matching event; if `ts < now - ttl_days`, treats as cache miss. NO separate cache-storage file; the ledger IS the cache substrate. This preserves Pillar A's I1 invariant (single source of truth — the ledger; the cache is a derived index).

**Why the ledger-as-cache substrate (rejected: separate cache file; rejected: in-memory cache; rejected: SQLite-backed cache).** Three reasonable storage shapes: (a) ledger-as-cache (D144's choice); (b) separate cache file at `~/.outreach-factory/cache/email_verification.yml`; (c) SQLite-backed cache. Pillar E Week 1 picks (a). The rationale:

* **No new SoT.** Adding a cache file would create a row in `docs/SOURCES-OF-TRUTH.md` — but the source-of-truth is Reoon (the external service) + the ledger's `cost_incurred` event already records the most-recent response. A separate cache file would be a duplicate denormalization that must be kept in sync.
* **Reproducibility from ledger replay (I4).** Replaying the ledger reconstructs the cache state. A separate cache file would need its own replay machinery.
* **Simplicity at v1.** Ledger queries scale to ~1M events per ADR-0011's R003 mitigation plan; the per-email lookup is O(len(events)) today + amortizes via the existing `_idx_*` machinery once Week 4-5 adds the `_idx_email_verification` index.

**Pin:** `tests/test_multi_channel_coherence.py::TestEmailVerificationCache::test_cache_hit_emits_cache_hit_event_not_cost_incurred` is the binding contract test. **Stub lands in this Week 1 commit + un-skips when the primitive ships in Week 4-5.**

### D145. Tier auto-assignment substrate

The `Person.research_tier` field today is operator-manual per ADR-0007's note. Pillar E ships a `compute_tier_from_signals(person)` primitive that derives tier from firmographic signals (Apollo `organization_size` / `industry` / `funding_stage`) + intent signals (per-prospect `discovery_lineage.source_skill` — e.g., `find-funded-founders` implies high-intent per the recent-funding signal).

**The primitive's output is operator-overridable per ADR-0007's existing `manual_override` event class.** Operators inspecting the suggested tier + disagreeing emit `manual_override` events that override the suggestion. The framework respects the override: `compute_tier_from_signals(person)` returns the suggestion; the actual `Person.research_tier` field is whichever the operator stamps (suggestion or override).

**Week 1 substrate contract:**

```python
from orchestrator.tier_assignment import compute_tier_from_signals  # Pillar E Week 6-8 ships

suggestion = compute_tier_from_signals(person)
# suggestion.tier ∈ {"S", "A", "B"}
# suggestion.signals: dict[str, str|int] — the firmographic + intent signals consulted
# suggestion.rationale: str — operator-readable explanation
```

**Per-signal weights deferred to Week 6-8.** Week 1 pins the substrate + the contract; Week 6-8 implements the weights against Yang's actual operator-tagged corpus (operators with months of historical `research_tier:` stampings provide ground truth; the primitive trains-by-inspection against this corpus). Week 1 doesn't ship the weights because the calibration depends on an operator-corpus that Yang will assemble by hand-tagging recent discoveries.

**Tier-suggestion event class (Week 6-8 ships):**

```python
{
    "type": "tier_suggested",
    "person_id": "<pid>",
    "channel": "none",  # tier is channel-agnostic per ADR-0014 D33's channel-on-every-event invariant
    "suggested_tier": "S | A | B",
    "signals_consulted": {
        "organization_size": "...",
        "industry": "...",
        "funding_stage": "...",
        "source_skill": "find-funded-founders",
        ...
    },
    "rationale": "Recent Series A + AI/ML industry + founder role → high-intent S tier",
    "_emitted_by": "tier_assignment",
}
```

**Pin:** `tests/test_multi_channel_coherence.py::TestTierAutoAssignment::test_suggestion_respects_operator_manual_override` is the binding contract test. **Stub lands in this Week 1 commit + un-skips when the primitive ships in Week 6-8.**

### D146. Cross-pillar integration audit — load-bearing surface map

`.planning/REVIEW-pillar-e-surface-audit.md` (this commit) is the surface map. The audit walks every existing Pillar A / B / C / D surface that touches `identity_keys:` or `cost_incurred:` or Person enrollment; verifies each is either closed-set protected or literal-string filtered against Pillar E's new event classes + the new `discovery_lineage:` sub-block. The audit's verdict: **see `.planning/REVIEW-pillar-e-surface-audit.md` for the per-surface walk + the verdict for Week 1**.

**The audit IS the contract.** Future Pillar E weeks' per-week reviewers consult the audit as the surface map; new code added in Week N+ that touches a ledger index or a query method extends the audit with a new row. The discipline mirrors Pillar D's per-week-review pattern + carries forward the RETRO-pillar-d.md "Audit pre-existing surfaces for symmetric assumptions" recommendation.

**New event classes Pillar E adds** (named here so the audit lands against concrete event-type names):

| Event class | Pillar E week that emits | Purpose |
|---|---|---|
| `discovery_dedup_hit` | Week 2-3 | Pre-enrichment dedup hit — operator-visible signal that the dedup primitive saved an Apollo + Reoon call. |
| `email_verification_cache_hit` | Week 4-5 | Email-verification cache hit — operator-visible signal that the cache saved a Reoon call. |
| `tier_suggested` | Week 6-8 | Tier auto-assignment suggestion — operator-visible reason for the suggestion. |

**Pin:** the audit document is referenced from this ADR + every subsequent Pillar E ADR's §References. Pillar E Week N's per-week reviewer's checklist (per HANDOFF-pillar-e-week-N.md §"Validation gate") includes "the surface audit was extended (or confirmed unchanged) by this week's commit."

**Categories the audit pins for future Pillar E week reviewers** (extracted from `.planning/REVIEW-pillar-e-surface-audit.md` §"Categories the Pillar E Week N per-week reviewer must keep auditing"):

1. Does the week's commit broaden `_idx_person` (any event with `person_id`) in a way pre-Week-N consumers don't expect?
2. Does the week's commit add a new `*_confirmed`-suffixed event (would silently activate `CrossChannelTouchRule`)?
3. Does the week's commit add to `_STAGE_BY_EVENT_TYPE` (extends `derived_stage`)?
4. Does the week's commit add a new per-prospect dedup-index pattern analogous to `_idx_gmail_msg`?
5. Does the week's commit modify enrollment.py (the existing `source` / `source_list` source-attribution surface) or any pre-existing reconcile pass?
6. Does the week's commit extend the `identity_keys:` schema in a way that breaks pre-Pillar-E Person notes?

### D147. Pillar E exit-criterion vehicle scope

`tests/test_multi_channel_coherence.py` is the Pillar E exit-criterion verification vehicle (extended from the Pillar C + D vehicles per ADR-0014 D37 + ADR-0025 D101). The file gains FIVE new test classes in this Week 1 commit:

* **`TestDiscoveryLineage`** — discovery-lineage shape coherence (the `identity_keys.discovery_lineage` sub-block per D142; per-skill stamping uniformity; pre-Pillar-E operator backfill compatibility). All test rows skip in Week 1 with `Pillar E Week N delivers` messages.

* **`TestPreEnrichmentDedup`** — pre-enrichment dedup contract (the dedup primitive per D143; concurrent-race fallback to identity-resolver; per-skill dedup-hit emit shape). All test rows skip in Week 1 with `Pillar E Week 2-3 delivers` messages.

* **`TestEmailVerificationCache`** — email-verification cache contract (per D144; cache-hit-emits-cache-hit-event-not-cost-incurred invariant; 30-day TTL; operator eviction surface). All test rows skip in Week 1 with `Pillar E Week 4-5 delivers` messages.

* **`TestTierAutoAssignment`** — tier auto-assignment substrate (per D145; suggestion respects operator manual override; firmographic + intent signal consumption). All test rows skip in Week 1 with `Pillar E Week 6-8 delivers` messages.

* **`TestPillarEExitCriterion`** — the binding exit-criterion test. One method: `test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates` per PILLAR-PLAN §2 Pillar E's binding text. Skipped in Week 1; un-skips at the final Pillar E week (Week 12 of the Pillar E body — Week 30 of the program).

**The Option-A choice (extend the existing file) over Option B (new file).** Pillar C's exit-criterion vehicle (ADR-0014 D37) explicitly chose the single-file shape; Pillar D inherited per ADR-0025 D101; Pillar E inherits the same rationale:

* The vehicle's load-bearing property is cross-pillar coherence visible from Week 1 in ONE place per-week reviewers consult.
* Splitting Pillar E into a separate `tests/test_pillar_e_discovery_coherence.py` would create the "look in two places" mental model ADR-0014 D37 §Decision rejected.
* File growth (the test file is ~4742 lines post-Pillar-D-Week-12) is a real concern; Pillar E Week 1's extension adds ~250-450 lines of stubs. If the file crosses ~6000 lines the split argument resurfaces — TBD per the per-week reviewer's call in a future Pillar E week.

### D148. Privacy-respecting invariant — `source_list` is operator-private

Per RETRO-pillar-d.md item 5 — Pillar E's discovery-source attribution carries operator-side privacy implications. The `discovery_lineage.source_list` field reveals WHICH list a prospect was found on; if exposed via dashboards, this surfaces operator-internal segmentation strategies. D148 pins the invariant:

* **`source_list` is operator-private.** Not surfaced in any Pillar G dashboard's operator-facing view; only available via direct ledger query (`python -m orchestrator.ledger grep --type enrolled | jq '.[] | select(.identity_keys.discovery_lineage.source_list)'`).
* **`source_skill` is operator-facing.** Pillar G dashboards aggregate by `source_skill` (the enum is intentionally coarse — five values today) to compute per-skill funnels.
* **Layer 1 defense (Week 1 ships):** test corpus pin. `tests/test_multi_channel_coherence.py::TestDiscoveryLineage::test_source_list_is_operator_private` asserts that the existing Pillar D Week 12 funnel CLI's `--help` text (which lists the allowed `--breakdown` dimensions) does NOT include `source_list`. **Test PASSES Week 1** against the current funnel CLI shape (which surfaces only `channel` / `category` / `classification_method` per ADR-0031 D140); a future Pillar G contributor adding `--breakdown source_list` to the funnel CLI's allowed dimensions would fail the test loudly + would have to amend D148 + add the breakdown deliberately. The intervention is structural — the test forces the contributor to confront the privacy invariant at parser-definition time, not at dashboard-deploy time.

**Why ONLY Layer 1 in Week 1 (rejected: defense-in-depth at five layers; rejected: hard YAML-level field redaction).** Three reasonable defense postures: (a) test-corpus pin only (D148's choice); (b) FIVE-layer defense analogous to ADR-0025 D97's CAN-SPAM legal-liability defense; (c) hard YAML-level field redaction (`source_list` written to a separate operator-only file). Pillar E Week 1 picks (a). The rationale:

* **The privacy concern is operator-side, not legal-liability.** CAN-SPAM legal-liability has external legal consequences (regulator fines, lawsuits); operator-side privacy is operator-discretionary (the operator may CHOOSE to surface source_list in their own dashboards). A FIVE-layer defense would over-engineer a discretionary concern.
* **Hard YAML-level redaction (option c) creates a SoT split.** The source_list field would live in two places (the operator-only file + the regular `identity_keys` block) — a duplication that violates I1.
* **Test-corpus pin (option a) is the right grain for v1.** A future contributor adding `--breakdown source_list` to Pillar G's funnel CLI would fail the test loudly + need to amend D148 + add the breakdown deliberately.

**Future weeks may add layers IF a specific privacy concern crystallizes.** Per the RETRO-pillar-d.md item-5 recommendation — design the invariant upfront; add defense layers as concerns surface. The Layer 1 pin is the structural intervention; Layers 2-5 (source-level construction refusal in a `DiscoveryLineage` dataclass; parse-level redaction; downstream-consumer guard; per-Pillar-G dashboard filter) are design-deferred.

## Alternatives considered

### D142-Alt1: Top-level Person frontmatter field — `discovery_lineage:` at the same level as `pipeline_stage:` / `conversation_status:`

A standalone top-level field carrying the four sub-fields. **Rejected** because:

* Top-level placement suggests per-Person mutable state (Pipeline-state fields change over the lifecycle; conversation_status changes per the state machine; tier may change per operator override). Discovery lineage is set ONCE at enrollment + immutable thereafter; top-level placement creates a misleading mental model.
* The lineage is structurally part of the identity (it's the provenance of the identity_keys themselves). The `country` field is already an `identity_keys` sub-block per ADR-0005's precedent; `discovery_lineage` follows the same pattern.
* Top-level placement would require a separate vault migration (`vault/000N_add_discovery_lineage_to_person_notes` — TBD week); identity_keys sub-block placement is content-additive within the existing `identity_keys:` block (the existing `add_frontmatter_block_text` primitive Pillar B Week 6 third follow-up handles).

### D142-Alt2: Standalone `provenance:` block at top of Person frontmatter

A separate `provenance:` YAML block adjacent to `identity_keys:`. **Rejected** because:

* Splits the keys-and-their-provenance question across two YAML blocks. Operators reading a Person note must jump between blocks to answer "where did this prospect come from?" — cognitive cost higher than the structural gain.
* The keys' provenance is a property OF the keys, not a sibling concept. The structural sibling-of-keys placement loses the parent-child relationship.
* `provenance:` as a generic name invites scope creep — future authors may want to add `enrichment_provenance:` (when did Apollo run?), `verification_provenance:` (when did Reoon run?), etc. — eventually `provenance:` is a catch-all bag that's hard to navigate. Per-concern blocks (discovery_lineage inside identity_keys; verification cache inside the ledger) keep the surface focused.

### D142-Alt3: Defer the shape decision to Pillar E Week 2 (when the dedup primitive ships)

The shape can land at the implementation site rather than in the foundation ADR. **Rejected** explicitly per the Pillar D Week 1 + Pillar C Week 1 precedent — the cross-pillar surface audit (D146) requires concrete schema to verify which existing surfaces broaden; deferring the schema defers the audit. Pillar D Week 1 ADR-0025 D97 set the precedent — schemas land in the foundation week so the audit can run.

### D143-Alt1: Defer dedup entirely; rely on `identity.resolve_strict` post-enrichment

The existing strict-policy resolver refuses 2+ matches; the only cost of deferring dedup is the second + third skill's Apollo + Reoon spend. **Rejected with high prejudice** because:

* PILLAR-PLAN §2 Pillar E exit criterion EXPLICITLY names the cost-bounded outcome: *"one Apollo credit, one Reoon credit, zero duplicate enrollments."* Deferring dedup violates the binding text.
* The asymmetric-failure-cost calculus per PILLAR-PLAN §0: false-positive dedup is one missed enrollment we re-discover next surfacing (cheap); false-negative dedup is one Apollo + Reoon credit we burned (expensive at scale — 100 duplicate discoveries × $0.10/discovery = $10 per operator per month).
* The existing resolver runs AFTER enrichment; by then the cost is already incurred.

### D143-Alt2: Bloom-filter based dedup (probabilistic, false-positive-acceptable)

A bloom filter over the identity-keys index would dedup with constant-time lookup. **Rejected** because:

* Bloom filters tolerate false-positives (a non-duplicate may register as a duplicate) but not false-negatives. The exit-criterion requires zero false-negatives (no duplicate enrollments) — bloom filters cannot guarantee this.
* The dedup index size is small (Yang's ~500 Persons today; ~10K Persons at 5-year scale) — direct index lookup is microseconds without the bloom-filter machinery.
* The existing `identity.find_matches` primitive already provides the exact behavior at the right grain (no need for a bloom filter).

### D143-Alt3: Per-skill dedup (each skill maintains its own dedup index)

Each discovery skill maintains its own per-call cache of "did we surface this person before in this batch?" **Rejected** because:

* The exit-criterion is CROSS-SKILL (three skills discovering the same person → one credit). Per-skill dedup only covers the within-skill case.
* Per-skill caches diverge across skills; an enrollment from skill X is not visible to skill Y's cache. The cross-skill dedup is the load-bearing primitive.
* Centralized dedup primitive (D143's choice) is one code path; per-skill is four code paths (four discovery skills) that must be kept in sync.

### D144-Alt1: Separate cache file at `~/.outreach-factory/cache/email_verification.yml`

A dedicated cache file with its own schema + read/write primitive. **Rejected** because:

* Creates a new row in `docs/SOURCES-OF-TRUTH.md` — but the source-of-truth is Reoon (the external service) + the ledger's `cost_incurred` event already records the most-recent response. A separate cache file duplicates information that must be kept in sync (drift risk).
* Reproducibility from ledger replay (I4) suffers — replaying the ledger reconstructs the cache state if the cache lives in the ledger; a separate cache file requires its own replay machinery.
* Operator-visible state grows by one file; per-pillar SoT registry growth is operator-visible cost.

### D144-Alt2: SQLite-backed cache (Pillar G's analytics-storage precedent)

SQLite mirror of the cache for fast lookup. **Rejected** as premature. SQLite mirror is the Pillar G analytics-storage primitive per PILLAR-PLAN §5 ("SQLite mirror of ledger, rebuilt nightly"); the cache primitive lives at the Pillar E layer (per-call lookup, not analytics). The existing ledger query primitive (`_idx_*` machinery) handles cache lookup at v1 scale; SQLite is a future scaling primitive.

### D144-Alt3: Cache via dedicated `email_verification_cache.yml` ledger event class (cache events as a sibling to cost_incurred)

A new event class `email_verification_cache_state` carries the cache index + is appended on every Reoon call. **Rejected** because:

* Adds a new event class for a state-derivation that's already implicit in the existing `cost_incurred.source=reoon` events. The cache primitive `lookup(email)` queries the ledger for the most-recent matching `cost_incurred` event; no new event class needed for the READ side.
* The cache HIT side (when the cache returns instead of calling Reoon) DOES emit a new `email_verification_cache_hit` event per D144 — that's the operator-visible signal. The two-event-class shape (cache miss → existing cost_incurred; cache hit → new event) is the right grain.

### D145-Alt1: Operator-manual tier only (no auto-assignment)

Skip the auto-assignment primitive; the operator stamps `research_tier:` manually as today. **Rejected** because:

* PILLAR-PLAN §2 Pillar E EXPLICITLY names tier auto-assignment as a binding bullet. Skipping violates the pillar's scope.
* Manual stamping scales poorly — Yang's current ~500 Persons are stamped; the next 10K Persons are not. Auto-assignment is the scaling primitive.
* The existing `manual_override` event class (ADR-0007) ALREADY provides the operator-override path; the auto-assignment is the BASELINE, the operator override is the EXCEPTION.

### D145-Alt2: LLM-based tier assignment (Anthropic-classifies-tier-from-Person-note)

Send the Person note to an LLM that returns a tier assignment. **Rejected** because:

* The cost is unbounded — every new prospect triggers an LLM call (vs deterministic firmographic-signal lookup which is free).
* LLM calls are non-deterministic; the same Person note classified twice may yield different tiers. The auto-assignment must be deterministic for operator audit + the binding exit-criterion test's reproducibility.
* The firmographic signals (Apollo organization_size / industry / funding_stage) + intent signals (discovery_lineage.source_skill) are deterministic + scale to operator-tunable thresholds. LLM is the wrong tool for a scalar-arithmetic problem.

### D145-Alt3: Defer auto-assignment to Pillar I (manual-only at v1)

Pillar I's OSS bring-up may ship the auto-assignment as a CLI command. **Rejected** because:

* PILLAR-PLAN §2 Pillar E binding text names tier auto-assignment in-scope. Deferring violates the pillar's scope + creates a Pillar E↔Pillar I dependency.
* The substrate (D145's `compute_tier_from_signals` primitive) is the right grain for Pillar E; Pillar I's CLI wraps the primitive operator-facing.

### D146-Alt1: Spawn a separate code-reviewer agent for the audit

Use the `code-reviewer` agent type instead of inline author audit. **Rejected for Week 1**; the audit IS the load-bearing artifact + benefits from sharing context with the ADR's author. Pillar E Week 1's per-week independent reviewer (spawned post-commit per the standing convention) WILL re-audit the surfaces from a fresh-context perspective; the inline audit + the per-week-review audit are complementary (per the Pillar D Week 1 + Pillar C Week 12 per-week review's §"Categories to watch" pattern lesson).

### D146-Alt2: Skip the audit entirely; rely on per-week reviews to catch broadening surfaces

Pillar A + B all relied on per-week reviews; Pillars C + D added structural audit. **Rejected explicitly** per Pillar D Week 12's retrospective lesson + the Pillar C Week 12 retrospective's "audit existing surfaces" recommendation: the per-week reviewer's threshold for "ship-stopping" is biased toward "defer to holistic" for pre-existing surfaces. The audit IS the structural intervention against the Pass-A-class pattern. Future Pillar E weeks' per-week reviewers consult the audit as the surface map + extend it; the discipline is the surface-symmetry-check + the per-week-review-with-follow-up-commit pattern compounding.

### D146-Alt3: Defer the audit to Pillar E Week 12 (the exit-gate close)

A holistic-review-style audit at the end of the pillar. **Rejected** because the audit's value is forward-looking (preventing broadening in Weeks 2-N). A Week-12 audit catches what's been broken by then; a Week-1 audit prevents the breakage. Per the Pillar B → C → D lesson: cross-cutting tests + cross-pillar audits land Week 1.

### D147-Alt1: New file `tests/test_pillar_e_discovery_coherence.py` (Option B from HANDOFF-pillar-e-week-1.md)

Per-pillar test file split. **Rejected** per the Option-A rationale above. Pillar C's ADR-0014 D37 explicitly chose Option A; Pillar D inherited per ADR-0025 D101; Pillar E inherits the same rationale.

### D147-Alt2: Defer the test vehicle stub to Pillar E Week 4-5 (when the dedup primitive ships)

Skip the test stubs in Week 1; land them with the implementation. **Rejected** per the same Week-1-vehicle lesson that Pillar C + D inherited. The stubs ARE the surface contract; per-week reviewers consult them.

### D147-Alt3: Skip `TestPreEnrichmentDedup` stubs and rely on the existing `tests/test_identity.py` + `tests/test_enrollment.py` tests

Defer the dedup regression tests to the existing identity / enrollment test files. **Rejected** because:

* The dedup contract (D143) is cross-cutting — it spans Pillar A (identity-resolver), Pillar B (ledger event shape), Pillar E (dedup primitive). The test file's home should be the cross-cutting coherence vehicle, not the per-primitive unit test file.
* `tests/test_identity.py` covers the strict-policy resolver's behavior; it doesn't (and shouldn't) cover the pre-enrichment dedup contract or the discovery_dedup_hit event shape.

### D148-Alt1: Five-layer defense analogous to ADR-0025 D97's CAN-SPAM defense

Defense layers: (1) source-level construction refusal in a `DiscoveryLineage` dataclass; (2) test-corpus pin; (3) parse-level redaction; (4) downstream-consumer guard; (5) per-Pillar-G dashboard filter. **Rejected** as over-engineered for a discretionary concern. CAN-SPAM has external legal consequences (regulator fines); operator-side privacy is operator-discretionary. A five-layer defense would over-engineer a single-concern problem. The Week 1 Layer 1 pin is the structural intervention; layers 2-5 are design-deferred unless a specific privacy concern crystallizes.

### D148-Alt2: Hard YAML-level field redaction — `source_list` written to a separate operator-only file

Operators may export their Person notes (for sync, backup, sharing); a separate operator-only file prevents accidental disclosure. **Rejected** because:

* Creates a SoT split. The source_list field would live in two places (the operator-only file + the regular `identity_keys` block) — a duplication that violates I1 + creates drift risk.
* The operator export use case is operator-discretionary (operators choose what to export); the framework enforcing redaction at the storage layer over-engineers the discretionary concern.
* The Layer 1 test-corpus pin (D148's choice) prevents the dashboard-side accidental disclosure (the most common surface); the operator-export concern is the operator's responsibility.

### D148-Alt3: Skip the privacy invariant entirely

`source_list` is operator-provided + operator-visible by definition; no need to defend its placement in dashboards. **Rejected** because:

* Pillar G dashboards are shared (operators with team members; future multi-tenant OSS deployment per Pillar I). A dashboard surfacing `source_list` would expose operator-internal segmentation to every dashboard viewer.
* The RETRO-pillar-d.md item-5 recommendation EXPLICITLY names the privacy-respecting invariant as a Week 1 deliverable. Skipping violates the carry-forward recommendation.

## Consequences

### Positive

- **Discovery-lineage shape is pinned across all four discovery skills before per-skill stamping refactors ship.** Pillar E Week 9-11's per-skill refactor lands against the convention; no retroactive rename.
- **The cross-pillar surface audit (D146) closes the Pass-A-class latent-bug pattern by construction.** Every existing surface is verified; the new event classes either don't broaden the surface or broaden expected-by-design with a literal-string or closed-set filter.
- **The pre-enrichment dedup contract (D143) is the exit-criterion-binding primitive.** The exit criterion (three skills, one Apollo, one Reoon, zero duplicates) becomes a tractable test target — Week 12's binding test exercises the primitive against a three-skill synthetic discovery scenario.
- **The email-verification cache (D144) preserves I1 (single source of truth).** The cache is a derived view of the ledger; no new SoT row; reproducibility-from-replay (I4) preserved.
- **The tier auto-assignment substrate (D145) is operator-overridable by construction.** The existing ADR-0007 `manual_override` event class is the override surface; Pillar E adds the BASELINE, the operator override is the EXCEPTION.
- **The privacy invariant (D148) is named in Week 1 + has a Layer 1 defense.** Future Pillar G dashboard authors who add `--breakdown source_list` fail the test loudly + must amend D148 + add the breakdown deliberately.
- **Pillar G observability has a clear discovery-source data shape.** D142's `discovery_lineage:` sub-block + D143's `discovery_dedup_hit` event + D144's `email_verification_cache_hit` event + D145's `tier_suggested` event compose into a per-source funnel that Pillar G dashboards consume.

### Negative

- **Three new event classes (`discovery_dedup_hit`, `email_verification_cache_hit`, `tier_suggested`) are reserved in Week 1 but emitted only in Week 2-8.** A casual reader of the codebase sees the names in this ADR + the test stubs but no production emit-site until Pillar E Week 2-8 ships. **Mitigation:** the stubs name the week that delivers; per-week reviewers consult the ADR as the contract.
- **The `discovery_lineage:` sub-block's exact migration path for pre-Pillar-E operators is TBD per Week 9-11 implementation.** D142 names the shape (`source_skill` enum + `source_list` + `scraped_at` + `raw_input_hash`) but the migration script that backfills from existing `_source.md` files lands Week 9-11. **Mitigation:** the existing `source_channel` / `source_list` fields on enrollment events (per `enrollment.py:279-280`) already record the partial information; the migration extends with `scraped_at` (timestamp of original enrollment) + `raw_input_hash` (rebuilt from the existing identity_keys via canonical serialization).
- **D143's dedup contract requires the discovery skills to consume the primitive — a refactor across four skills.** The per-skill refactor lands Week 9-11. Until then, the dedup primitive (Week 2-3 ships) is unused by the production skills; only the test corpus exercises it. **Mitigation:** the per-skill refactor is the planned coordinated Week 9-11 change with a vault migration that backfills missing fields on existing Person notes; Week 1 pins the contract + adds the regression test verifying NEW enrollments fail-loud if the canonical block is missing.
- **D144's email-verification cache requires the dispatcher to consult the cache before the Reoon call.** The cache primitive lands Week 4-5; until then, the dispatcher's existing `enrich_emails.verify_with_reoon` path is unwrapped. **Mitigation:** the cache is a wrapping primitive — the existing call site stays; the cache wraps. The Pillar E Week 4-5 commit changes the call-site to consult the cache first.
- **D145's tier auto-assignment requires per-signal weights that depend on Yang's operator-tagged corpus.** The weights land Week 6-8 against Yang's hand-tagged historical corpus. Until then, the primitive returns operator-tunable defaults. **Mitigation:** the substrate (D145) is the right grain for Week 1; the weight-calibration is the Week 6-8 deliverable.
- **The audit (D146) is a one-time snapshot.** Future Pillar E weeks must extend the audit row-by-row; a lazy week could ship without updating the audit. **Mitigation:** the per-week-reviewer's checklist (HANDOFF-pillar-e-week-N.md §"Validation gate") includes "the surface audit was extended (or confirmed unchanged)"; the discipline is the safeguard.
- **The exit-criterion stub test class adds ~250-450 LOC of skipped stubs to `tests/test_multi_channel_coherence.py`.** The file is already ~4742 lines post-Pillar-D-Week-12. **Mitigation:** Pillar E Week 12+'s split-file argument may resurface; until then the file-per-pillar discipline carries forward from ADR-0014 D37.

### Neutral / observability

- The `discovery_dedup_hit` events Pillar E Week 2-3 emits are queryable via the existing `query_by_person` + filter-by-type pattern. Pillar G's discovery-funnel dashboard reads these directly.
- The `email_verification_cache_hit` events Pillar E Week 4-5 emits feed Pillar G's Reoon-spend dashboard (cache hit-rate = `email_verification_cache_hit` count / (`email_verification_cache_hit` + `cost_incurred.source=reoon`) count).
- The `tier_suggested` events Pillar E Week 6-8 emits power Pillar G's tier-assignment audit dashboard (per-Person suggestion + operator override + the divergence rate).
- No new SoT introduced. The `discovery_lineage:` block adds a row to `docs/SOURCES-OF-TRUTH.md` per the existing pre-declared entry; the email-verification cache adds no row (it's a derived view of the ledger); the tier-assignment primitive adds no row (the SoT is the existing `Person.research_tier` field).

## Compliance with invariants

- **I1 (single source of truth):** The `discovery_lineage:` block is a NEW SoT (Person note frontmatter; pre-declared in `docs/SOURCES-OF-TRUTH.md` per the existing row "Discovery lineage"). The `enrolled` ledger event carries the same fields denormalized; the heal direction is Person note → ledger (at enroll time only — the lineage is immutable post-enrollment). The email-verification cache is a derived view of the ledger's `cost_incurred.source=reoon` events; no new SoT. The tier-assignment primitive's output is operator-overridable per ADR-0007 — the SoT for `Person.research_tier` is the Person note (per the existing row); the primitive's `tier_suggested` event is a sibling observation, not a write to the SoT.
- **I2 (two-phase commit on every external side effect):** The pre-enrichment dedup primitive is FRAMEWORK-only (no external side effect; the primitive avoids the external Apollo + Reoon call); the email-verification cache is FRAMEWORK-only (cache hit avoids the external Reoon call; cache miss falls through to the existing two-phase Reoon call); the tier-assignment primitive is FRAMEWORK-only (no external side effect). No I2 change required.
- **I3 (schema versioning):** Reply events carry `v: 1` (existing ledger event versioning). The new event classes (`discovery_dedup_hit`, `email_verification_cache_hit`, `tier_suggested`) carry `v: 1`. The `discovery_lineage:` sub-block within `identity_keys:` carries the existing `identity_version: 1` per `enrollment.py:354-355`. No I3 change required in Week 1; future Pillar E weeks may bump schemas if the lineage shape evolves.
- **I4 (reproducible state):** Every Pillar E event class is durable in the append-only ledger; the pre-enrichment dedup primitive is idempotent (consulting the index returns the same result for the same input); the cache primitive is deterministic (cache hit returns the same response for the same email + same cache window). Replaying the ledger reconstructs the dedup index + the cache state.
- **I5 (observable by default):** D143's `discovery_dedup_hit`, D144's `email_verification_cache_hit`, D145's `tier_suggested` all emit structured events with full diagnostic context (matched classes, source skill, source list, signals consulted, rationale). Pillar G observability has scalar-field queries.
- **I6 (tests prove invariants):** D147's test vehicle (extended in this Week 1 commit) is the integrative test surface. The dedup contract is pinned by `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup`; the cache contract by `TestEmailVerificationCache`; the tier-assignment contract by `TestTierAutoAssignment`; the binding exit criterion by `TestPillarEExitCriterion`.
- **I7 (cost is a first-class concern):** Pillar E's pre-enrichment dedup is the COST-AVOIDANCE primitive — `discovery_dedup_hit` IS the operator-visible "we saved an Apollo + Reoon call" signal. The cache is the parallel for Reoon-only avoidance. Pillar E Week 1 doesn't ship NEW cost-event classes for cost — it consumes the existing `cost_incurred` event class + adds per-Person attribution via the `person_id` field already present on every event.
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0032 row. The per-week trajectory in HANDOFF-pillar-e-week-2.md (TBD this commit) names planned ADRs 0033+.

Does not weaken any invariant. I7's enforcement extends to the cost-avoidance signal (the `discovery_dedup_hit` + `email_verification_cache_hit` events make cost-avoidance operator-visible alongside the existing `cost_incurred` events).

### Downstream pillar impact

Per the Pillar A / B / C / D convention (every ADR explicitly names cross-pillar impact):

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring is per-touch (not per-discovery-source); Pillar F migrations operate on touch notes regardless of discovery lineage. Pillar F may add a `voice_fidelity_by_discovery_source` aggregation surface (per-source quality breakdown) — TBD per Pillar F's ADR. The `discovery_lineage.source_skill` field is the join key.

* **Pillar G (observability).** Pillar G's cost-per-quality-prospect dashboard consumes the cost aggregation. Per ADR-0006 the `cost_incurred` event class is the cost SoT; Pillar E's per-Person attribution (the dedup + cache hits) feeds the dashboard's per-prospect cost breakdown. Pillar G dashboards aggregate by `source_skill` (operator-deliberate level) but NEVER by `source_list` per D148. The funnel CLI from Pillar D Week 12 (`orchestrator/funnel.py`) extends with `--breakdown source_skill` (Pillar I CLI extension if/when operator demand materializes; Week 1 doesn't extend the existing CLI).

* **Pillar H (daemon + dispatcher).** Pillar H's per-stage parallelism limits become per-source (e.g., "no more than N concurrent find-funded-founders enrichment calls"); the D142 `source_skill` field is the dispatch-router's discriminator. Pillar H inherits Pillar E's per-source primitives unchanged.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-source state isolation. The Pillar I doctor preflight extends to check (a) `discovery_lineage:` block existence on every Person note, (b) `source_skill` enum-conformance, (c) the dedup primitive's index health. The Pillar I CLI ships the per-skill stamping refactor (Week 9-11) as a coordinated change.

* **Pillar J (security + compliance).** Pillar J's GDPR-forget transaction inherits the existing `forget_append` primitive (ADR-0004 §Decision step 2) + adds a new step "purge per-person discovery_lineage from the Person note frontmatter" (the lineage is operator-private + may contain PII-like operator segmentation data per D148). Pillar J's CAN-SPAM compliance gate consumes Pillar E's email-verification cache state (a stale cache entry should not be a basis for sending; the cache TTL bounds the risk).

## Migration / rollout

The Week 1 deliverable is convention-setting + the test vehicle stub + the cross-pillar surface audit. No new framework primitive ships; no new migration ships; no new module ships.

**Operator-facing changes (Week 1):**

1. **No new pending migrations.** `runner.pending()` still returns 17 (the Pillar D final state). Pillar E Week 4-5+ MAY ship a vault migration to add `discovery_lineage:` to existing Person notes — TBD per the Week 2+ ADRs. Likely shape: `vault/0005_add_discovery_lineage_to_identity_keys`.

2. **Existing operators with pre-Pillar-E-Week-1 enrollment events** carry a small known limitation: their `enrolled` events stamp `source` + `source_list` (per `enrollment.py:279-280`) but lack `scraped_at` + `raw_input_hash` + the canonical `source_skill` enum value. Pillar E Week 9-11's per-skill refactor + the coordinating vault migration backfills from existing fields where parseable, else stamps `source_skill: manual` per the existing-operator seed.

**Operator-facing changes (Pillar E Weeks 2+, planned):**

3. **Week 2-3 ships the pre-enrichment dedup primitive + the `discovery_dedup_hit` event class.** Per HANDOFF-pillar-e-week-2.md (this commit's sibling). Per the D36 convention inherited from Pillar C, each Pillar E ADR ships its own §Existing-operator-seed subsection.

4. **Week 4-5 ships the email-verification cache primitive + the `email_verification_cache_hit` event class.**

5. **Week 6-8 ships the tier auto-assignment primitive + the `tier_suggested` event class + the per-signal weights against Yang's operator-tagged corpus.**

6. **Week 9-11 ships the per-skill `discovery_lineage:` stamping refactor + the coordinating vault migration.**

7. **The exit-criterion test (`TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`) un-skips at the final Pillar E week.** The test is the operator-visible signal that Pillar E is "stable" — when it passes, the per-week trajectory has completed.

**The Week 1 commit's verification surface:**

```python
# 1. The coherence test vehicle extension exists and runs the email-baseline.
$ python -m pytest tests/test_multi_channel_coherence.py::TestDiscoveryLineage \
                   tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup \
                   tests/test_multi_channel_coherence.py::TestEmailVerificationCache \
                   tests/test_multi_channel_coherence.py::TestTierAutoAssignment \
                   tests/test_multi_channel_coherence.py::TestPillarEExitCriterion -v
# Expected: every row SKIPPED with "Pillar E Week N delivers" message.

# 2. The full suite is green at +N tests (2371 + N — new test class stubs).
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 2371+N passed, ~similar skipped count.

# 3. ADR-0032 exists; README index gains the row; PILLAR-PLAN §6 Pillar E row flipped.
$ ls docs/adr/0032-pillar-e-foundation.md
$ grep "0032" docs/adr/README.md
$ grep "Pillar E" docs/PILLAR-PLAN.md
```

### Existing-operator seed

Pillar E Week 1 ships NO new migrations + NO new ledger-state primitives that require an existing-operator seed. The convention-setting ADR + the test-vehicle stubs + the audit document are documentation-only; existing operators see no change.

The first Pillar E week that ships a migration requiring an existing-operator seed (TBD — likely Pillar E Week 9-11's vault migration adding per-Person `discovery_lineage:` block) WILL include the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface Pillar E's pre-enrichment dedup + tier auto-assignment integrate with (no engine change required).
- ADR-0004 (suppression rules + GDPR-forget) — the `forget_append` primitive Pillar E's discovery-lineage tombstoning may reuse (Pillar J consumer per the §Downstream pillar impact).
- ADR-0005 (sending-window + tz inference) — the `country` field's placement in `identity_keys` as a sub-block; the structural precedent for D142's `discovery_lineage:` sub-block placement.
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention Pillar E's cache + dedup primitives consume (cache hit = NO cost_incurred emit; cache miss = existing cost_incurred path).
- ADR-0007 (tier rules + block_when.tier) — the `manual_override` event class Pillar E's tier auto-assignment is overridable through.
- ADR-0009 (migration framework) — Pillar E vault migrations (Week 9-11+) register into the existing framework.
- ADR-0010 (ledger migrations) — Pillar E `migration_event` audit-trail emissions follow the D35 `channel=` kwarg convention (inherited from Pillar C); Pillar E's dedup + cache events carry `channel: none` (dedup is channel-agnostic; cache is email-specific).
- ADR-0011 (vault migrations) — Pillar E Person note migrations consume the existing `add_frontmatter_block_text` + `iter_person_notes` primitives.
- ADR-0012 (policy migrations) — Pillar E's tier-assignment threshold weights may surface as policy rules (TBD Week 6-8); the engine-version-range-acceptance contract holds.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — the D24 hybrid synthetic fixture pattern Pillar E Week 12 extends.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-event invariant D146 extends to Pillar E's new event classes (`discovery_dedup_hit` carries `channel: none`; `email_verification_cache_hit` carries `channel: email`); the D37 exit-criterion vehicle Pillar E extends per D147; the D36 existing-operator-seed pattern Pillar E inherits.
- ADR-0025 (Pillar D foundation) — the D99 cross-pillar surface audit D146 mirrors; the D100 YAML-first + ledger-second pattern Pillar E's cache may reference for crash semantics; the D101 exit-criterion vehicle D147 extends.
- ADR-0026 (Pillar D rule-based classifier) — the D103 refuse-loud bootstrap pattern Pillar E's dedup primitive may inherit (refuse-loud if the people_dir is unreadable).
- ADR-0028 (Pillar D auto-unsubscribe + conversation state) — the D117 LOAD-BEARING dedup-by-(reply_message_id, channel) pattern Pillar E's dedup primitive extends to (candidate_partial, source_skill).
- ADR-0030 (Pillar D win/loss attribution) — the D134 `derived_conversation_outcome(person_id)` per-Person aggregation surface Pillar E's discovery-source-to-outcome learning consumes (e.g., "what fraction of `find-funded-founders` enrollments became `closed_won`?").
- ADR-0031 (Pillar D exit-criterion close) — the D140 funnel CLI Pillar E's per-source breakdown extends (Pillar I CLI extension).
- `docs/PILLAR-PLAN.md` §2 Pillar E — exit criterion (binding text); §5 "What we will not do" — Pillar E adjacent constraints; §6 Pillar E row flipped to In progress in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D143's dedup contract (false-negative dedup is expensive at scale; false-positive dedup is cheap).
- `docs/RISK-REGISTER.md` R001 (identity-graph false-merge cascade) — risk Pillar E's dedup primitive does NOT regress (the dedup primitive REUSES `identity.find_matches` + `identity.resolve_strict`'s strict policy). R018 (discovery-source poisoning — NEW, added in this commit). R019 (pre-enrichment dedup false-positive — NEW, added in this commit). R020 (email-verification cache staleness — NEW, added in this commit).
- `docs/SOURCES-OF-TRUTH.md` — existing row for "Discovery lineage" (pre-declared; Pillar E formalizes); existing row for "Per-deployment tier" (Pillar E adds the suggestion path; the operator-stamped SoT is unchanged).
- `.planning/RETRO-pillar-d.md` §"What to do differently in Pillar E" items 1-8 — the eight carry-forward recommendations this ADR's structure implements.
- `.planning/REVIEW-pillar-d-holistic.md` §"Systemic Patterns Assessment" — the seven Pillar D patterns Pillar E inherits.
- `.planning/REVIEW-pillar-d-surface-audit.md` — the structural precedent Pillar E Week 1's `.planning/REVIEW-pillar-e-surface-audit.md` mirrors.
- `.planning/HANDOFF-pillar-e-week-1.md` — the per-week handoff that scoped Week 1.
- `.planning/REVIEW-pillar-e-surface-audit.md` — the D146 audit document; THE load-bearing anti-regression artifact for Pillar E Week 1.
- `orchestrator/identity.py` — the `IdentityKeys` dataclass D142 extends; `find_matches` + `resolve_strict` Pillar E's dedup primitive reuses.
- `orchestrator/enrollment.py` — the existing `source` + `source_list` source-attribution surface D142 extends; the `enroll_person` entry point Pillar E's dedup primitive integrates with.
- `orchestrator/enrich_emails.py` — the existing Reoon verification surface D144's cache wraps.
- `orchestrator/policy/tier.py` — the existing tier-rule consumer D145's auto-assignment SUPPLIES (the rule reads `Person.research_tier`; the auto-assignment suggests + the operator stamps).
- `skills/find-leads/SKILL.md` + `skills/find-funded-founders/SKILL.md` + `skills/competitor-customers/SKILL.md` + `skills/research-prospect/SKILL.md` — the four discovery skills Pillar E's per-skill refactor (Week 9-11) coordinates against.
- `tests/test_multi_channel_coherence.py` — the D147 vehicle Pillar E extends.
- Forward-references (planned):
  - **ADR-0033** (Pillar E Week 2-3): pre-enrichment dedup primitive — `orchestrator/discovery_dedup.py` module + `discovery_dedup_hit` event emit-site + Pass P (TBD letter; dedup pass) integration.
  - **ADR-0034** (Pillar E Week 4-5): email-verification cache — `orchestrator/email_verification_cache.py` module + `email_verification_cache_hit` event emit-site + cache-aware wrapping of `enrich_emails.verify_with_reoon`.
  - **ADR-0035+** (Pillar E Week 6-8): tier auto-assignment — `orchestrator/tier_assignment.py` module + `tier_suggested` event emit-site + per-signal weights against Yang's operator-tagged corpus.
  - **ADR-0036+** (Pillar E Week 9-11): per-skill `discovery_lineage:` stamping refactor + coordinating vault migration (`vault/0005_add_discovery_lineage_to_identity_keys` — TBD shape).
  - **ADR-00NN** (Pillar E Week 12): exit-gate close — the binding three-skills-one-day exit-criterion test un-skips.
  - **Pillar G dashboards** (Weeks 31-42): cost-per-quality-prospect dashboard consuming `cost_incurred` + `discovery_dedup_hit` + `email_verification_cache_hit` events; per-source funnel breakdown via `source_skill` (NEVER `source_list` per D148).
  - **Pillar I CLI** (Weeks 43-48): aggregation of per-ADR seed blocks + the dedup primitive's CLI surface + the doctor-preflight extension for discovery_lineage block validation + the per-skill stamping refactor's CLI surface.
  - **Pillar J GDPR-forget** (Weeks 49-52): the per-Person discovery_lineage tombstoning step added to the existing `forget_append` flow.
