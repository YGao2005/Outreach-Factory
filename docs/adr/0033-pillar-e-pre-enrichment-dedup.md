# ADR-0033: Pillar E Week 2 — pre-enrichment dedup primitive

- **Status:** Accepted; Amended 2026-05-24 (Pillar E Week 3 — per-skill integration extension to find-funded-founders + competitor-customers; see §Amendment 2026-05-24 — Pillar E Week 3 at end of document)
- **Date:** 2026-05-24
- **Pillar:** E (Discovery quality + lineage — Week 2 dedup primitive)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0032 (Pillar E Week 1 foundation) pinned the discovery-lineage shape (D142 — `identity_keys.discovery_lineage:` sub-block), the pre-enrichment dedup contract (D143 — the load-bearing exit-criterion primitive), the email-verification cache shape (D144), the tier auto-assignment substrate (D145), the cross-pillar surface audit (D146 — `.planning/REVIEW-pillar-e-surface-audit.md`), the exit-criterion vehicle scope (D147), and the privacy-respecting invariant for `source_list` (D148). The Week 1 commit shipped the foundation ADR + the load-bearing surface audit + the Week 1 P2-A fix (`needs_identity_upgrade` event now stamps `source` + `source_list`) + the test-vehicle stubs in `tests/test_multi_channel_coherence.py`.

**Pillar E Week 2 is the pre-enrichment dedup primitive.** The handoff (`.planning/HANDOFF-pillar-e-week-2.md` — committed in the Week 1 follow-up) scopes Week 2 to: (a) the dedup primitive's foundation module + emit-shape factories + concurrent-race fallback semantics; (b) the per-skill integration discipline + the Week 2 integration in `find-leads` (the most active discovery skill); (c) the cross-pillar audit row extension naming the new event classes' consumer surface. Weeks 3+ extend per-skill integration to the other three discovery skills (`find-funded-founders`, `competitor-customers`, `research-prospect`); the per-skill `discovery_lineage:` stamping refactor + the coordinating vault migration land Week 9-11. The split — primitive in Week 2 + per-skill integration phased Week 3+ + canonical lineage stamping deferred to Week 9-11 — bounds each week's failure radius: a primitive bug in Week 2 is one Python module + its tests; a per-skill-stamping mistake at Week 9-11 is a coordinated vault migration + four skill refactors against an already-shipped primitive.

The five concerns this ADR resolves:

1. **The dedup primitive module's PLACEMENT must be pinned before the implementation lands.** Three plausible homes: (a) `orchestrator/discovery_dedup.py` (top-level, sibling of `enrollment.py` + `identity.py`); (b) inside `orchestrator/enrollment.py` (conflates the dedup-as-prevention with the enrollment-as-creation); (c) inside `orchestrator/identity.py` (conflates dedup-as-prevention with identity-as-resolution); (d) a new `orchestrator/discovery/` subpackage (over-organization for one module in Week 2). D149 picks (a).

2. **The `discovery_dedup_hit` event class's EMIT-SHAPE must be pinned per the channel-on-every-event invariant.** Per ADR-0032 D146 the event carries channel-agnostic `channel: "none"` (dedup operates over identity keys, not per-channel intents). The Pillar G dashboard filtering by channel must not silently exclude dedup-hits; D150 pins the field shape + the operator-readable `_emitted_by: "discovery_dedup"` marker.

3. **The `discovery_dedup_conflict` event class must exist for the ambiguous-multi-match + concurrent-race paths.** Per ADR-0032 D143 the strict-policy resolver (`identity.resolve_strict`) refuses 2+ matches as Conflict; the dedup primitive's emit path for that case mirrors the existing `enrollment_conflict` event shape so operators see the same diagnostic surface pre- and post-enrichment. D151 pins the event class.

4. **The per-skill INTEGRATION DISCIPLINE must be pinned so all four discovery skills consume the primitive uniformly.** Two plausible shapes: (a) explicit `check_dedup` call at each skill's pre-enrichment site (the canonical caller pattern); (b) transparent wrapping inside `enroll_person` (would put the dedup AFTER enrichment — defeats the exit-criterion). D152 picks (a) + Week 2 ships the integration in `find-leads`; subsequent weeks extend to the other three.

5. **The cross-pillar surface audit (per ADR-0032 D146) MUST be extended row-by-row each Pillar E week.** Week 2 ships the `discovery_dedup_hit` + `discovery_dedup_conflict` event classes — both land in `_idx_person` (broadens the per-Person index for every consumer); the audit must verify each consumer is either closed-set-protected or by-design-broadening. D153 names the audit extension.

Risks this ADR mitigates by design: **R001 (identity-graph false-merge cascade)** continues mitigated by `identity.resolve_strict`'s strict policy reused inside `check_dedup`; the dedup primitive does NOT introduce new identity-resolution semantics — it consults the existing resolver at an earlier point in the pipeline. **R019 (pre-enrichment dedup false-positive)** named in ADR-0032 §Context is mitigated structurally: the strict-policy refusal of 2+ matches (the same back-stop that handles `enrollment_conflict`) surfaces ambiguous-shared-email scenarios as `discovery_dedup_conflict` instead of silently collapsing distinct people. The asymmetric-failure-cost calculus per PILLAR-PLAN §0 carries: false-positive dedup is one missed enrollment we re-discover next surfacing (cheap); false-negative dedup is one Apollo + Reoon credit we burned (expensive at scale).

No new risk surfaces in this ADR's authoring. R001 + R018 + R019 + R020 (all named in ADR-0032 §Context) carry the design-time mitigation forward; the Week 2 implementation does not introduce new risk classes.

## Decision

### D149. Dedup primitive module placement — `orchestrator/discovery_dedup.py`

The dedup primitive ships as a single top-level module under `orchestrator/`, sibling of `enrollment.py` + `identity.py`:

```
orchestrator/
├── discovery_dedup.py       ← NEW (Pillar E Week 2)
├── enrollment.py            ← Pillar 5.5 Week 1b (the BACK-STOP consumer)
├── identity.py              ← Pillar 5.5 Week 1b (reused by check_dedup)
├── reply_classifier.py      ← Pillar D Week 2 (the precedent placement)
├── ledger.py
├── reconcile.py
└── ...
```

**The dedup primitive is a pillar primitive, not a policy rule.** Policy rules (`orchestrator/policy/*.py`) implement `evaluate(ctx) → RuleResult` — they CONSUME events to make gate decisions. The dedup primitive PRODUCES events (it walks the people_dir index + emits `discovery_dedup_hit` or `discovery_dedup_conflict` events on the caller's behalf). The placement-as-pillar-primitive matches `orchestrator/reply_classifier.py`'s precedent (Pillar D Week 2 ADR-0026 D102 picked the same shape for the same reason).

**Top-level placement matches the existing per-primitive convention.** `orchestrator/ledger.py` + `orchestrator/reconcile.py` + `orchestrator/identity.py` + `orchestrator/enrollment.py` + `orchestrator/reply_classifier.py` are each single-file pillar primitives. The dedup primitive follows the same shape. An `orchestrator/discovery/` subpackage would be over-organization for Week 2's ~450 LOC; the subpackage rationale resurfaces in Pillar E Week 4-5 IF the email-verification cache (a sibling primitive per ADR-0032 D144) lands in the same conceptual surface — TBD per Week 4-5's ADR.

**Why NOT inside `enrollment.py`?** Conflates dedup-as-prevention with enrollment-as-creation. The dedup primitive runs BEFORE enrichment (per ADR-0032 D143's exit-criterion contract); `enroll_person` runs AFTER enrichment is complete (the post-enrichment Person note write). Combining them would either (i) reorder enrollment into "check + enrich + create" — but the dedup primitive's job is to PREVENT the enrich step, not to gate the create step; or (ii) duplicate the dedup logic at both points — violating I1.

**Why NOT inside `identity.py`?** Conflates dedup-as-prevention with identity-as-resolution. `identity.resolve_strict` is the identity-resolver primitive — it makes the 0/1/2+ policy decision against existing data. `check_dedup` is the cost-attribution wrapper around the resolver — it's a thin call-site that adds operator-visible event emission. Putting the wrapper inside the resolver module would dilute the resolver's single-purpose shape + would create a circular-import hazard (a future per-skill integration importing identity for the resolver would also pull in the dedup-as-wrapper, which itself imports the resolver — fragile coupling).

### D150. `discovery_dedup_hit` event class — emit-shape contract

Per ADR-0032 D146 + ADR-0014 D33 (channel-on-every-event invariant). The `discovery_dedup_hit` event class carries the following fields:

```python
{
    "type": "discovery_dedup_hit",
    "person_id": "<existing-person-id>",          # the EXISTING Person whose keys matched
    "candidate_partial": {                        # IdentityKeys.to_serializable() of the pre-enrichment input
        "linkedin": "in/dylan-txa",
        "emails": ["dylan@example.com"],
        "github": None,
        "twitter": None,
        "alt_names": ["Dylan Teixeira"],
        "country": None,
    },
    "matched_classes": ["email", "linkedin"],     # subset of {linkedin, email, github, twitter}; sorted
    "source_skill": "find-leads",                 # one of SOURCE_SKILLS (D142 enum)
    "source_list": "[[2026-05-24-test]]",         # operator-supplied; OPERATOR-PRIVATE per D148
    "channel": "none",                            # dedup is channel-agnostic per D146 channel-on-every-event extension
    "_emitted_by": "discovery_dedup",             # per ADR-0010 D17 convention
}
```

**Field rationale:**

* **`person_id`** — the EXISTING Person's id. The dedup primitive's purpose is the join key from this event to the existing Person note + every other event on that Person (`_idx_person` consumer convergence).
* **`candidate_partial`** — the pre-enrichment input as `IdentityKeys.to_serializable()`. Pillar G dashboards aggregate "which key class triggered the dedup hit?" via the `matched_classes` field; the full partial is preserved for operator audit + Pillar I CLI replay.
* **`matched_classes`** — sorted list of identity-key classes that intersected. Deterministic for replay + Pillar G dashboard aggregation. Computed from `identity.find_matches`'s matched-class set.
* **`source_skill`** — the discovery skill that surfaced the duplicate. Operator-facing per Pillar G's per-source-funnel dashboard (the "find-funded-founders has 73% dedup-hit-rate" insight that ADR-0032 §"Pillar G observability has a clear discovery-source data shape" names).
* **`source_list`** — operator-PRIVATE per D148. Stamped on the event for direct ledger query (`python -m orchestrator.ledger grep --type discovery_dedup_hit | jq '.[] | select(.source_list == "...")'`) but NEVER aggregated by Pillar G dashboards. The Layer 1 defense per D148 (the test corpus pin in `test_source_list_is_operator_private`) covers the funnel CLI; future Pillar G dashboards inherit the invariant.
* **`channel: "none"`** — per ADR-0032 D146's channel-on-every-event invariant extension. Dedup is channel-agnostic (it operates over identity keys, not per-channel intents). The explicit `"none"` makes the absence operator-visible to Pillar G dashboards filtered by channel; a future operator filtering "show me email-channel events" would see dedup-hits excluded — by design.
* **`_emitted_by: "discovery_dedup"`** — per ADR-0010 D17 the operator-facing filter marker. Tests + the cross-pillar audit consume this literal string predicate.

**Why `channel: "none"` (rejected: omit the field entirely; rejected: stamp `channel: "all"`).** Three plausible postures: (a) `channel: "none"` (D150's choice); (b) omit the field; (c) `channel: "all"`. The rationale:

* **Per ADR-0014 D33 + ADR-0032 D146 the channel-on-every-event invariant** — every event carries the field, even when channel is not applicable. Omitting the field for dedup events would create a per-event-class special case that Pillar G dashboards must handle (silently exclude or default-to-some-value). The explicit `"none"` makes the absence loud.
* **`channel: "all"`** would suggest the event applies to every channel uniformly — but the dedup hit is OUTSIDE the per-channel send flow entirely. The semantic mismatch invites misinterpretation by Pillar G dashboard authors.
* **The Pillar D Week 1 precedent (ADR-0025 D96 + ADR-0032 D146)** — channel-on-every-event has uniform `channel: <value>` shape across reply / classified / send / bounce / suppression events. The dedup primitive extends the same shape with `"none"` rather than departing from the convention.

**Pin:** `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup::test_dedup_hit_emits_discovery_dedup_hit_event` un-skipped + passing in this Week 2 commit. `tests/test_discovery_dedup.py::TestBuildDiscoveryDedupHitPayload::*` cover every field's contract individually.

### D151. `discovery_dedup_conflict` event class — ambiguous-multi-match emit-shape

Per ADR-0032 D143 the dedup primitive's concurrent-race + ambiguous-multi-match path. When `identity.resolve_strict` returns Conflict from inside `check_dedup`, the primitive emits a `discovery_dedup_conflict` event (mirroring the existing `enrollment_conflict` event from `enrollment.py:308-317`):

```python
{
    "type": "discovery_dedup_conflict",
    "candidate_partial": {...},                   # IdentityKeys.to_serializable() of the pre-enrichment input
    "report_path": "/path/to/conflict-2026...yml",  # YAML report identity.resolve_strict wrote
    "match_count": 2,                              # number of existing Persons matching
    "matched_note_paths": [                        # list of Person note paths matched
        "/vault/.../Alice.md",
        "/vault/.../Bob.md",
    ],
    "matched_classes": ["email"],                  # union of matched classes across all matches; sorted
    "source_skill": "find-leads",
    "source_list": "[[2026-05-24-test]]",
    "channel": "none",
    "_emitted_by": "discovery_dedup",
}
```

**Mirrors `enrollment_conflict`'s shape** (per `enrollment.py:308-317`). The two event classes differ only in:
- `type` (`discovery_dedup_conflict` vs `enrollment_conflict`),
- `_emitted_by` (`discovery_dedup` vs unset on the existing `enrollment_conflict`; Pillar I's CLI doctor preflight MAY backfill the marker on the enrollment-conflict path in a future commit — TBD),
- the dedup variant carries `candidate_partial` (the pre-enrichment input as IdentityKeys) where the enrollment variant carries `candidate_keys` (the same shape; the field name difference reflects the pre- vs post-enrichment distinction in the event-flow timeline).

**The strict-policy report file is written ONCE.** The YAML conflict report at `report_path` is the operator-visible merge/split decision tree per `identity.py:588-637`. The dedup primitive does NOT write a second report; it reuses the report that `identity.resolve_strict` already wrote inside `check_dedup`. Two event classes (`discovery_dedup_conflict` + `enrollment_conflict`) MAY both point to the same `report_path` if the concurrent-race scenario fires (the SECOND skill's dedup primitive catches the race; if the dedup primitive is bypassed, the enrollment back-stop catches it). Operators see one report file + two events — the audit trail is full.

**Per D146 the channel-on-every-event invariant.** Dedup conflicts carry `channel: "none"` same as dedup hits. Pillar G dashboards filtering by channel see both event classes consistently.

**Pin:** `tests/test_discovery_dedup.py::TestBuildDiscoveryDedupConflictPayload::*` covers every field's contract. The coherence vehicle's `test_dedup_concurrent_race_falls_back_to_resolver_strict_policy` (un-skipped Week 2) exercises the end-to-end race-window-with-back-stop flow.

### D152. Per-skill integration discipline — explicit `check_dedup` call at each skill's pre-enrichment site

Each of the four discovery skills (`find-leads`, `find-funded-founders`, `competitor-customers`, `research-prospect`) wraps its pre-enrichment partial in an explicit `check_dedup` call BEFORE the Apollo / PDL / Reoon spend. The canonical caller pattern (per ADR-0032 D143's contract code-block):

```python
from orchestrator.discovery_dedup import (
    check_dedup,
    build_discovery_dedup_hit_payload,
    build_discovery_dedup_conflict_payload,
)
from orchestrator.identity import compute_keys

# Inside the discovery skill's per-candidate loop:
keys = compute_keys(
    name=candidate_name,
    linkedin_url=candidate_linkedin,
    email=candidate_email_if_known,
)
result = check_dedup(
    candidate_partial=keys,
    source_skill="find-leads",                  # or one of the other four enum values
    source_list="[[2026-05-24-find-leads-q2]]",
    people_dir=people_dir,                       # from config
)

if result.should_skip_enrichment:
    # Cost-avoidance pin per D143 — DO NOT call Apollo / PDL / Reoon.
    if result.is_duplicate:
        payload = build_discovery_dedup_hit_payload(
            result, "find-leads", "[[2026-05-24-find-leads-q2]]",
        )
    else:  # is_conflict
        payload = build_discovery_dedup_conflict_payload(
            result, "find-leads", "[[2026-05-24-find-leads-q2]]",
        )
    led.append(payload)
    continue  # next candidate

# Else: proceed with enrichment + enrollment as before.
apollo_result = apollo.enrich(...)
...
enrollment.enroll_person(...)
```

**Week 2 ships the integration in `find-leads`.** The most active discovery skill (Yang's primary surface for new-prospect discovery; the highest-cost-avoidance opportunity at v1 scale). The skill's SKILL.md gains a new sub-phase ("Phase 3e: Pre-enrichment dedup check") between the existing state-aware dedup (Phase 3b — the in-memory dedup against the cohort folders + lead lists) and the auto-enrollment (Phase 4.5). The Phase 3e sub-phase shells to `python orchestrator/discovery_dedup.py check --linkedin ... --source-skill find-leads --source-list <list> --apply` for each NEW candidate row.

**Subsequent weeks extend the integration to the other three skills.** Week 3 ships `find-funded-founders` + `competitor-customers` integration (both are recently-funded-founder + competitor-customer-list discovery patterns — high overlap with the find-leads pattern, low integration churn). Week 9-11 ships the per-skill `discovery_lineage:` stamping refactor (per ADR-0032 D142) + the coordinating vault migration; the stamping refactor coincides with the `research-prospect` integration (which is per-prospect rather than per-list, so its integration is structurally different from the other three).

**Why explicit `check_dedup` at the skill site (rejected: transparent wrap via `enroll_person`; rejected: a new reconcile pass).** Three plausible shapes: (a) explicit call at the skill site (D152's choice); (b) transparent wrap inside `enroll_person` (the dedup check happens at enrollment time, AFTER enrichment); (c) a new reconcile pass (the dedup runs periodically, not per-discovery). The rationale:

* **(a) honors the cost-avoidance pin.** The dedup primitive's purpose per ADR-0032 D143 is to PREVENT the Apollo / PDL / Reoon spend. Wrapping inside `enroll_person` runs the dedup AFTER enrichment is complete — defeats the exit-criterion's "one Apollo credit" bullet.
* **(b) creates an enrollment-flow surface change.** `enroll_person` today is the single-purpose post-enrichment vault-write + ledger-append primitive. Adding pre-enrichment-call semantics expands its surface + invites confusion ("does enroll_person call Apollo? does check_dedup call enroll_person?").
* **(c) is too cadence-detached.** Discovery skills surface candidates in batches (find-leads runs surface 10-20 candidates per invocation; find-funded-founders runs on weekly VC-post cadence). A reconcile pass running periodically would dedup batches AFTER they've already spent the Apollo / PDL / Reoon credits — the timing is wrong.

The (a)-shaped integration is the only one that honors D143's exit-criterion contract.

**Per-skill SKILL.md changes (Week 2):**

| Skill | Week | Change |
|---|---|---|
| `find-leads` | **Week 2 (this commit)** | New Phase 3e: pre-enrichment dedup check; shell to `discovery_dedup.py check --apply` for each NEW candidate row. |
| `find-funded-founders` | **Week 3 (amendment 2026-05-24 — this commit)** | New Phase 4f: pre-enrichment dedup check; shell to `discovery_dedup.py check --apply` for each NEW candidate row. Phase numbering reflects find-funded-founders' phase structure (Phase 4 = priority scoring 4a-4e + Phase 4f dedup); semantic equivalent of find-leads' Phase 3e (last per-candidate computation before lead-list save). See §Amendment 2026-05-24 — Pillar E Week 3. |
| `competitor-customers` | **Week 3 (amendment 2026-05-24 — this commit)** | New Phase 3e: pre-enrichment dedup check; shell to `discovery_dedup.py check --apply` for each NEW candidate row. Direct mirror of find-leads' Phase 3e (same phase numbering since Phase 3 = per-candidate workflow in both skills). See §Amendment 2026-05-24 — Pillar E Week 3. |
| `research-prospect` | Week 9-11 | Per-prospect dedup check; coordinated with the `discovery_lineage:` stamping refactor. |

**Pin:** `skills/find-leads/SKILL.md` updated in this commit. The other three skills carry their existing flow unchanged in Week 2; subsequent weeks extend per the trajectory above.

### D153. Cross-pillar audit row extension — `.planning/REVIEW-pillar-e-surface-audit.md`

Per ADR-0032 D146 the cross-pillar surface audit is the load-bearing anti-regression artifact. The Week 2 commit extends `.planning/REVIEW-pillar-e-surface-audit.md` with a new section walking the new event classes' consumer surfaces. Per consumer:

1. **`_idx_person`** — `discovery_dedup_hit` events carry `person_id` (the EXISTING matched Person's id) and DO land in the per-Person index. `discovery_dedup_conflict` events do NOT carry `person_id` (a multi-match conflict has 2+ matching Persons with no single attributable id; mirrors the existing `enrollment_conflict` shape which also omits `person_id` for the same reason). Operators querying conflicts must use `matched_note_paths` rather than `person_id` (Pillar J's GDPR-purge inherits this). Every existing consumer (the Pillar A/B/C/D enumeration from the Week 1 audit) is closed-set-protected or by-design-broadening; the audit's Week 2 verdict per consumer:
   * `derived_stage` — closed dispatch table `_STAGE_BY_EVENT_TYPE`; the new event types are absent → **closed-set-protected, by-design**.
   * `reachable_pipeline_stages` — same dispatch table → **closed-set-protected**.
   * `derived_conversation_status` — literal-string filter on REPLY_EVENT_TYPES + suppression + state-change events → **closed-set-protected**.
   * `derived_conversation_outcome` — `type == "conversation_outcome"` filter → **closed-set-protected**.
   * `CrossChannelTouchRule.evaluate` — `endswith("_confirmed")` predicate → the new types do NOT match → **literal-string-filtered, by-design**.
   * `BudgetWindowCapRule.evaluate` — `type == "cost_incurred"` filter → dedup events are NOT cost_incurred → **literal-string-filtered**.
   * `CooldownRule._confirmed_send_intent_pairs` — `type in {"send_intent", "send_confirmed"}` → **literal-string-filtered**.
   * `DomainThrottleRule.evaluate` — `type != "send_confirmed"` → dedup events don't match the loop guard → **literal-string-filtered**.
   * `Ledger.last_send_for` — `_INTENT_TYPES + _OUTCOME_TYPES` → dedup events absent → **closed-set-protected**.
   * Pass G's reply classifier idempotence index — `REPLY_EVENT_TYPES` filter → dedup events absent → **closed-set-protected**.
   * Pass M's auto-unsubscribe — `category=unsubscribe` filter on `reply_classified` events → dedup events absent → **closed-set-protected**.
   * Pass N's conversation state machine — reply + classified + suppression + state-change events filter → dedup events absent → **closed-set-protected**.
   * Pass O's conversation outcome — `*_confirmed` filter → dedup events absent → **closed-set-protected**.
   * Pillar D funnel CLI (`orchestrator/funnel.py::build_report`) — `reply_classified` + `conversation_outcome` filter → dedup events absent → **closed-set-protected**. (Future Pillar G `--breakdown source_skill` extension is a deliberate broadening per D148 the privacy invariant.)

2. **`enrollment_conflict` SIBLING SHAPE — `discovery_dedup_conflict`.** The new event class mirrors the existing `enrollment_conflict` shape (per `enrollment.py:308-317`). Audit verdict: **structural symmetry — by-design.** Any future consumer that processes `enrollment_conflict` (Pillar I CLI's conflict-report viewer; Pillar J's GDPR-purge transaction) MAY extend to process `discovery_dedup_conflict` uniformly; per `_emitted_by` filtering the consumer distinguishes pre- vs post-enrichment conflicts.

3. **`_idx_gmail_thread` — UNCHANGED.** Dedup events do not carry `gmail_thread_id` (dedup is channel-agnostic per D146; threads are email-specific). No broadening.

4. **`_idx_gmail_msg` + `_idx_li_invite_msg` + `_idx_li_dm_msg` + `_idx_tw_dm_msg` — UNCHANGED.** Per-channel message-id indices. Dedup events have no `*_message_id` field; absent → no broadening.

5. **The classifier-output idempotence index pattern (per ADR-0026 D106) — UNCHANGED.** Pass G's `(reply_message_id, channel)` idempotence index is filtered on `type == "reply_classified"` — dedup events do not match. No broadening.

**Verdict for Week 2's audit extension:** Zero new P1 latent-bug patterns introduced by Week 2's new event classes; both event classes' consumer surfaces are fully covered by the Week 1 audit's existing-consumer enumeration + the new ledger-walk patterns are closed-set-protected.

**Pin:** `.planning/REVIEW-pillar-e-surface-audit.md` extended in this commit with the Week 2 section. Future Pillar E weeks consult the audit + extend it per the per-week-review-with-follow-up-commit discipline (Pillar A + B + C + D + E pattern).

## Alternatives considered

### D149-Alt1: Place the dedup primitive inside `orchestrator/enrollment.py`

A new function `enrollment.check_dedup` that wraps the existing `enroll_person` flow's pre-enrichment check. **Rejected** because:

* Conflates dedup-as-prevention with enrollment-as-creation. The dedup primitive's job is to PREVENT the Apollo / PDL / Reoon spend (running BEFORE enrichment); `enroll_person`'s job is to write the Person note + emit the enrolled event (running AFTER enrichment). Combining them either reorders enrollment into "check + enrich + create" — but `enroll_person` doesn't call enrichment today — or duplicates the dedup logic at both points.
* `enrollment.py` already imports `identity.find_matches` + `identity.resolve_strict` for its post-enrichment back-stop; a sibling primitive importing the same surface from a different module is cleaner than overloading `enroll_person`'s call site.
* The single-purpose Pillar D Week 2 precedent (ADR-0026 D102 placed the classifier in its own module rather than inside `reconcile.py`) is the structural model.

### D149-Alt2: Place the dedup primitive inside `orchestrator/identity.py`

A new `identity.check_dedup` that wraps `identity.find_matches` + `identity.resolve_strict`. **Rejected** because:

* `identity.py` is the identity-resolver primitive — its load-bearing exports are `IdentityKeys`, `find_matches`, `resolve_strict`, `mint_id`. Adding a cost-attribution wrapper inside the same module dilutes the single-purpose shape.
* The dedup primitive emits ledger events (`discovery_dedup_hit` + `discovery_dedup_conflict`); `identity.py` today has ZERO ledger imports. Adding `_ledger` as an import to identity.py would create a circular-import hazard (`ledger.py` may eventually depend on identity primitives — TBD per Pillar G's per-person query surface).
* The Pillar D Week 2 precedent — the rule-based classifier is a sibling of `reconcile.py` (the reconcile primitive), not inside it. Pillar E mirrors.

### D149-Alt3: Spin up an `orchestrator/discovery/` subpackage

`orchestrator/discovery/__init__.py` + `orchestrator/discovery/dedup.py` + `orchestrator/discovery/lineage.py` (Week 9-11). **Rejected for Week 2** (deferred to a future Pillar E week's ADR amendment IF the surface area justifies the split):

* Over-organization for Week 2's scope (~450 LOC of dedup primitive + tests). The single-file convention used by `ledger.py` + `identity.py` + `enrollment.py` + `reply_classifier.py` is the precedent for Pillar primitives.
* The subpackage rationale resurfaces Pillar E Week 9-11 IF `discovery_lineage.py` + the per-skill stamping refactor adds enough surface that a coordinated subpackage clarifies. Premature subpackaging in Week 2 invites refactoring debt + would land code in module boundaries that don't yet have proven coherence.

### D150-Alt1: Omit the `channel` field on dedup events

Dedup is channel-agnostic; the field is superfluous. **Rejected** because:

* Violates ADR-0014 D33 + ADR-0032 D146's channel-on-every-event invariant. Pillar G dashboards filtering by channel would silently exclude (or default) dedup events. The explicit `"none"` makes the absence loud.
* The Pillar D Week 1 D96 precedent — every Pass B event stamps `channel: "email"` even though Pass B's emit context is unambiguously email. The "stamp the channel verbatim, no inference" discipline is the invariant.
* A future per-channel dedup-rate dashboard (e.g., "what fraction of LinkedIn-discovered candidates are already in the vault?") would lose the discrimination key. Stamping `"none"` preserves the option to extend per-channel discrimination later via the `candidate_partial.linkedin/emails/etc.` sub-fields without re-emitting historical events.

### D150-Alt2: Stamp `channel: "all"` instead of `"none"`

Dedup events apply to every channel uniformly. **Rejected** because:

* Semantic mismatch — the dedup event is OUTSIDE the per-channel send flow entirely. `"all"` would suggest the event applies to every channel's send tally; in reality, it applies to zero channel's send tally (dedup happens BEFORE any send is queued).
* Pillar G dashboard authors filtering by channel — e.g., "show me email-related events" — would see `"all"` events surface in EVERY channel's filter, inflating per-channel counts. The `"none"` value cleanly excludes dedup events from every per-channel filter; operator-deliberate per-source-skill aggregation (D142) is the right grain for dedup analytics.
* The Pillar D Week 1 precedent — Pass B doesn't stamp `channel: "all"` on `reply_received` events; it stamps `channel: "email"` because the event IS email-specific. Dedup events are NOT all-channels-specific; they're NO-channel-specific. `"none"` matches the semantic.

### D150-Alt3: Stamp `channel` to the source-skill's IMPLIED channel (e.g., `"linkedin"` for find-leads-via-LinkedIn-scrapes)

Surface the implicit channel based on which key class triggered the dedup. **Rejected** because:

* The implicit-channel-inference depends on the candidate's keys, NOT the event's emit context. The same `discovery_dedup_hit` event could match on linkedin + email simultaneously; the inferred channel would be ambiguous.
* The Pillar G dashboard's per-channel funnel reads `channel:` as the event's emit context (which channel did this event come from?), NOT as a derived field of the candidate's keys. The Pillar G query is fundamentally different.
* The dedup primitive's value to Pillar G is per-source-skill aggregation (D142), not per-channel aggregation. Stamping `channel: "none"` preserves the option to extend per-source-skill dashboards (the right grain) without orphaning Pillar G's per-channel filter (the wrong grain).

### D151-Alt1: Reuse `enrollment_conflict` for the dedup conflict path

The existing event class already exists; reusing it avoids a new event class for a similar-shaped scenario. **Rejected** because:

* The audit trail distinction is load-bearing. An operator inspecting "did the dedup primitive catch the race or did the enrollment back-stop catch it?" needs to distinguish the two emit points. Single event class collapses the distinction.
* The `_emitted_by` marker (`discovery_dedup` vs the enrollment path's absent marker — Pillar I CLI's doctor preflight MAY backfill the enrollment marker, but the dedup marker is set today) is the operator-readable provenance. Two event classes with the same shape make the marker more discoverable than one event class with two `_emitted_by` values.
* Future Pillar G dashboards aggregate per event class — the dedup-conflict-rate vs enrollment-conflict-rate split surfaces "is the fast-path catching races, or is the back-stop?" The split would be invisible under a single event class.

### D151-Alt2: Omit the conflict event entirely; rely on the YAML report file alone

The YAML conflict report at `identity.resolve_strict`'s `report_path` is operator-visible; an additional event class is redundant. **Rejected** because:

* The ledger is the single source of truth for Pillar G observability. A conflict that fires WITHOUT a paired ledger event is invisible to dashboards — the Pillar G per-source-conflict-rate query has no data.
* Operators interacting with the funnel via `python -m orchestrator.ledger grep --type discovery_dedup_conflict` get the per-event context (source_skill + source_list + matched_classes + match_count) at query time; the YAML report is the deep-dive surface for manual resolution.
* The Pillar D Week 1 + Pillar E Week 1 precedent — every operator-facing decision surface emits a ledger event AND any deeper artifact (conflict reports, suppression YAML writes). The two-surface pattern is the convention.

### D151-Alt3: Carry the full `identity.Conflict` object as a nested field

Serialize the full `Conflict` dataclass into the event for replay completeness. **Rejected** because:

* The full `Conflict` includes the candidate IdentityKeys + every match's `matched_values` dict + `note_path` + `person_id` + `report_path`. The serialized form would be large (a 2+ match conflict balloons to ~2KB JSON per event). The ledger's append-only growth scales with operator activity; carrying redundant data per event compounds.
* The audit trail is complete via the report file at `report_path` + the per-match `note_path` list — replay reconstructs the full Conflict by reading the report file. Serializing the same data into the event duplicates without adding fidelity.
* The Pillar D Week 1 precedent — `enrollment_conflict` carries `matched_note_paths` (paths) + `report_path` (path) + `candidate_keys` (IdentityKeys.to_serializable()) but NOT the full Match objects. The dedup variant mirrors.

### D152-Alt1: Transparent wrap inside `enroll_person` (the dedup primitive is invisible to discovery skills)

Each discovery skill keeps its existing flow; `enroll_person` gains a pre-enrichment check that fires automatically. **Rejected** because:

* The dedup runs AFTER enrichment in this scheme — defeats the exit-criterion's "one Apollo credit" bullet. Per ADR-0032 D143 the cost-avoidance is the load-bearing primitive; transparent wrap is structurally incompatible.
* Discovery skills today don't call `enroll_person` directly — they shell to `python orchestrator/enrollment.py enroll --json` per the existing per-skill CLI shape. A transparent wrap would need to intercept the CLI, not the function. The intercept layer doesn't exist today.
* Per-skill visibility of the dedup primitive's behavior (the skill's SKILL.md describes the Phase 3e step explicitly) is operator-readable. Transparent wrap hides the cost-attribution surface — operators reading the skill don't see "this skill avoids Apollo spend by checking dedup first" without spelunking into `enroll_person`'s source.

### D152-Alt2: A new reconcile pass that dedups discovery-source events periodically

A `Pass P` (TBD letter) walks recent discovery events + emits `discovery_dedup_hit` events retroactively. **Rejected** because:

* The dedup must run BEFORE enrichment per D143's exit-criterion contract. A periodic reconcile pass runs AFTER discovery batches have already spent the Apollo / PDL / Reoon credits — wrong cadence.
* Reconcile passes are about bringing inferred state into agreement with reality (Pass A heals send_intent → send_confirmed; Pass G classifies replies; Pass M handles unsubscribe). Dedup is about PREVENTING redundant work, not healing inconsistent state. The conceptual model doesn't fit.
* The Pillar D Week 2 D105 precedent — Pass G's classifier fits in reconcile because classification is a posthoc operation on already-emitted reply events. Dedup is a pre-emission gate; the reconcile chain is wrong.

### D152-Alt3: Defer per-skill integration to Week 9-11 (alongside the lineage stamping refactor)

Ship the primitive in Week 2 + integrate all four skills together in Week 9-11. **Rejected** because:

* The Week 2 → Week 9-11 gap is 7 weeks. Without an integrated skill, the primitive is unused — operators see no cost-avoidance benefit until Week 9-11. The asymmetric-failure-cost calculus (PILLAR-PLAN §0): one week of integration + 7 weeks of cost-avoidance benefit beats 7 weeks of deferral + one week of all-at-once integration. The Pillar D Week 2 precedent — the classifier shipped + Pass G integrated together; operators got the visibility benefit Week 2.
* Per-skill integration in Week 2 (find-leads only) is bounded scope — one skill, one SKILL.md update, one test. Subsequent weeks extend incrementally. Bundling all four into Week 9-11 increases blast radius.
* The exit-criterion test (`TestPillarEExitCriterion`) needs all three+ skills wired before it un-skips. Phased per-skill integration aligns with the per-week exit-criterion adjacency.

### D153-Alt1: Spawn a code-reviewer agent for the audit extension

Use the `code-reviewer` agent type for a fresh-context audit. **Rejected for Week 2** mirroring ADR-0032 D146-Alt1's reasoning: the audit IS the load-bearing artifact + benefits from sharing context with the ADR's author. Pillar E Week 2's per-week independent reviewer (spawned post-commit per the standing convention) WILL re-audit the surfaces from a fresh-context perspective; the inline audit + the per-week-review audit are complementary.

### D153-Alt2: Skip the audit extension; rely on per-week reviews to catch broadening surfaces

Pillars A + B all relied on per-week reviews. **Rejected** mirroring ADR-0032 D146-Alt2's reasoning: the per-week reviewer's threshold for "ship-stopping" is biased toward "defer to holistic" for pre-existing surfaces. The audit IS the structural intervention against the Pass-A-class pattern; future Pillar E weeks' per-week reviewers consult the audit as the surface map + extend it; the discipline compounds.

### D153-Alt3: Defer the audit extension to a Week 2 follow-up commit

Ship the dedup primitive + integration in the main commit; ship the audit extension in a follow-up. **Rejected** mirroring ADR-0026 D106-Alt2's reasoning: the audit extension IS part of the Week 2 deliverable per HANDOFF-pillar-e-week-2.md §"Validation gate". Splitting the commit risks the audit landing days/weeks after the code change it documents — exactly the gap the audit discipline is designed to prevent.

## Consequences

### Positive

- **The dedup primitive MODULE is a clean pillar primitive.** Future Pillar E weeks (Week 4-5 email-verification cache, Week 6-8 tier auto-assignment) extend the discovery-primitive surface without churning the dedup module.
- **The `discovery_dedup_hit` event class makes cost-avoidance operator-visible.** Pillar G's per-source-funnel dashboard reads these directly: "find-funded-founders has a 73% dedup-hit-rate" = "73% of its candidates are already in the vault" = "find-funded-founders is best deployed on weekly cadence rather than daily."
- **The `discovery_dedup_conflict` event class makes ambiguous-multi-match operator-visible.** The same operator-visible report shape as `enrollment_conflict` ensures the pre- and post-enrichment paths have parity diagnostic context.
- **The cross-pillar surface audit (D153) continues the ADR-0032 D146 discipline.** Every new event class extends the audit; the audit grows with the pillar; the Pass-A-class latent-bug pattern is foreclosed by construction.
- **The per-skill integration discipline (D152) is the operator-readable contract.** Discovery skill SKILL.md files name the dedup check at Phase 3e; operators reading the skill see the cost-attribution surface explicitly.
- **The exit-criterion vehicle's Week 2 rows un-skip + pin the contract.** `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup` 4-of-5 rows pass; the 5th (the cross-skill three-credit subset) un-skips at Week 3 when find-funded-founders + competitor-customers integrate.

### Negative

- **Discovery skills with no integration get no cost-avoidance benefit.** Week 2 integrates find-leads ONLY; find-funded-founders + competitor-customers + research-prospect carry their existing pre-Pillar-E flow until Week 3+. Operators using the un-integrated skills see no `discovery_dedup_hit` events for those candidates. **Mitigation:** the per-week integration trajectory closes the gap by Week 9-11; until then, the per-skill flow falls back to the post-enrichment `identity.resolve_strict` back-stop (the existing `enrollment_skipped_exists` event) — operator-visible but not pre-enrichment-cost-avoiding.
- **The `check_dedup` primitive rebuilds the people_dir index per call (O(N) per call).** For batch discovery (find-leads surfacing 50 candidates), the cost is N*M = 50*500 = 25K operations at v1 scale (~500 Persons). **Mitigation:** the naive implementation is fine at v1; if/when per-skill batch benchmarks show the rebuild as a bottleneck, a future Pillar E week adds a per-call index parameter (`check_dedup(..., index=preloaded_index)`) without changing the function's contract. The Week 2 reviewer's P2 watch-list item (per HANDOFF-pillar-e-week-2.md §"P2 candidates") tracks this.
- **The dedup primitive's `check_dedup` writes a YAML conflict report on conflict paths.** The filesystem side effect happens INSIDE `check_dedup` (via `identity.resolve_strict`'s existing behavior); a pre-enrichment dedup conflict produces a YAML file in `~/.outreach-factory/conflicts/` same as the post-enrichment enrollment conflict. Operators see two events (one pre-, one post-) + ONE report file (the dedup primitive reuses the report `identity.resolve_strict` writes). **Mitigation:** the audit trail is preserved; the two events differ in `_emitted_by` so Pillar I CLI's conflict-report viewer can dispatch.
- **The CLI's `--apply` flag is the live-mode opt-in.** Without `--apply` the primitive is dry-run; the dedup-hit event is NOT appended to the ledger. Operators forgetting `--apply` see the per-candidate report but no ledger entry — Pillar G dashboards aggregated over the ledger miss those candidates. **Mitigation:** the per-skill SKILL.md's Phase 3e step documents `--apply` explicitly; the dry-run-default-with-explicit-opt-in is the same posture as `python -m orchestrator.policy simulate` (read-only by default).
- **The `discovery_dedup_hit` event is emit-only in Week 2 — no downstream consumer yet.** Pillar G dashboards land Weeks 31-42; until then, operators query via `python -m orchestrator.ledger grep --type discovery_dedup_hit`. **Mitigation:** the operator-visible surface is the ledger grep + the Pillar I CLI's eventual doctor preflight extension.

### Neutral / observability

- The `discovery_dedup_hit` + `discovery_dedup_conflict` events are queryable via the existing `query_by_person` + filter-by-type pattern. Pillar G's per-source-funnel dashboard reads these directly.
- The `_emitted_by: "discovery_dedup"` marker (per ADR-0010 D17 convention) lets operators filter dedup-primitive output from other event sources in funnel queries.
- The `matched_classes` field surfaces "which identity-key class caught the dedup" for operator audit — "linkedin matches dominate" vs "email matches dominate" inform per-source curation tuning.
- No new SoT introduced (per I1 invariant). The dedup primitive emits events; the ledger remains the single SoT for the dedup-hit-rate aggregation. No new files, no new YAML config, no new vault state.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT row added. The dedup primitive emits events; the ledger remains the SoT for per-Person discovery history. The conflict-report YAML files inherit `identity.resolve_strict`'s existing SoT (per the pre-existing `~/.outreach-factory/conflicts/` location pinned by `identity._default_conflicts_dir`). I1 holds.
- **I2 (two-phase commit on every external side effect):** The dedup primitive is a pure FRAMEWORK operation (index walk + ledger append + optional conflict-report write). The conflict-report write is filesystem-side-effect (existing semantics from `identity.resolve_strict`); the ledger append is the durable side effect. The order is: resolve_strict writes the report (or returns Match if no conflict) THEN the caller appends the event. A crash between the two writes leaves the report on disk + no ledger event — the operator sees the report at `~/.outreach-factory/conflicts/` + manually resolves; the ledger gap is operator-visible via the audit trail. The Pillar A I2 contract for new external side effects is satisfied (no new external surface; the dedup primitive is FRAMEWORK-local).
- **I3 (schema versioning):** The `discovery_dedup_hit` + `discovery_dedup_conflict` events carry `v: 1` stamped by `Ledger.append` per the existing event-versioning convention. The `candidate_partial` sub-field is serialized via `IdentityKeys.to_serializable()` which returns `{linkedin, emails, github, twitter, alt_names, country}` (the existing six fields — no `identity_version` sub-field on the serialized form). Schema versioning is at the LEDGER-EVENT level (the `v:` field stamped by the Ledger class), not at the IdentityKeys-payload sub-level. I3 holds (the event-level version field is the load-bearing discriminator; per-ADR schema bumps land via Pillar B ledger migrations).
- **I4 (reproducible state):** `check_dedup` is deterministic — the same people_dir state + the same candidate_partial input produce the same DedupResult on every call. The dedup primitive emits events deterministically; replaying the ledger reconstructs the dedup-hit history as a function of the people_dir's state at each emit time. The concurrent-race path is non-deterministic (which skill checks first depends on real-time scheduling), but the back-stop (`identity.resolve_strict`) is deterministic — the post-enrichment outcome is reproducible.
- **I5 (observable by default):** `discovery_dedup_hit` events carry `person_id` (the EXISTING matched Person) + `candidate_partial` + `matched_classes` + `source_skill` + `source_list` + `channel` + `_emitted_by`. `discovery_dedup_conflict` events carry `candidate_partial` + `matched_classes` + `match_count` + `matched_note_paths` + `report_path` + `source_skill` + `source_list` + `channel` + `_emitted_by` — but NO `person_id` (a multi-match conflict has no single attributable Person; the operator-visible audit trail is `matched_note_paths` + the YAML conflict report at `report_path`). Pillar G dashboards have scalar-field queries for every dimension on the hit event; conflict events are operator-deliberate-attention-required artifacts queried via type filter rather than per-person aggregation.
- **I6 (tests prove invariants):** `tests/test_discovery_dedup.py` ships per-method unit tests (DedupResult invariants, check_dedup happy paths + conflict paths, event-payload contracts, per-skill integration smoke test). `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup` un-skipped 4 rows pin the integration-level contract. The load-bearing legal-liability + privacy invariants (D148) inherit the Layer 1 defense unchanged.
- **I7 (cost is a first-class concern):** The dedup primitive IS the cost-avoidance signal. `discovery_dedup_hit` events are the operator-visible "we saved an Apollo + Reoon call" signal. Pillar G dashboards compute cost-avoidance hit-rate as `discovery_dedup_hit_count / (discovery_dedup_hit_count + cost_incurred.source=apollo count)`. The dedup primitive itself does NOT emit `cost_incurred` (rule-based + framework-local; zero per-call cost).
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0033 row. The per-week trajectory in HANDOFF-pillar-e-week-3.md (TBD this commit) names planned ADRs 0034+.

Does not weaken any invariant. I5's enforcement extends to the dedup events' diagnostic-context fields. I7's enforcement extends to the cost-avoidance signal (the `discovery_dedup_hit` event makes cost-avoidance operator-visible alongside the existing `cost_incurred` events).

### Downstream pillar impact

Per the Pillar A / B / C / D / E Week 1 convention (every ADR explicitly names cross-pillar impact):

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring is per-touch (not per-discovery-source); the dedup primitive doesn't change Pillar F's contracts. The `discovery_dedup_hit` events surface "this prospect was rediscovered" — Pillar F MAY consume this to suppress drafting for already-drafted prospects (TBD per Pillar F's ADR).

* **Pillar G (observability).** Pillar G's cost-per-quality-prospect dashboard consumes `discovery_dedup_hit` events to compute the per-source cost-avoidance hit-rate. Per ADR-0032 D148 the privacy invariant — Pillar G aggregates by `source_skill` (operator-deliberate level — five enum values) but NEVER by `source_list` (would surface operator-internal segmentation). The funnel CLI (`orchestrator/funnel.py`) MAY extend with `--breakdown source_skill` (Pillar I CLI extension; Week 2 doesn't extend).

* **Pillar H (daemon + dispatcher).** Pillar H's daemon doesn't dispatch discovery skills (those are operator-invoked via `/find-leads` etc.); the dedup primitive is operator-side. Pillar H's per-stage parallelism limits (per the Pillar H eventual design) become per-source — `source_skill` is the discriminator the dispatcher routes on.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-source dedup index. The Pillar I doctor preflight extends to check (a) the dedup primitive's conflict-report directory health (no orphan reports from manual operator inspection); (b) the per-skill SKILL.md's Phase 3e step existence (sanity-check that the integration discipline hasn't drifted); (c) the dedup-hit-rate per source over a rolling window (anomaly detection on a source that suddenly stops hitting dedup — a sign of upstream scraper drift). The Pillar I CLI ships `python -m orchestrator.discovery_dedup replay --since <date>` for the one-time backfill of pre-Pillar-E enrollments where applicable.

* **Pillar J (security + compliance).** Pillar J's GDPR-forget transaction inherits the existing `forget_append` primitive (ADR-0004 §Decision step 2) + adds steps that purge dedup events for a deleted subject. The two event classes require DIFFERENT predicates: `discovery_dedup_hit` events carry `person_id` directly → the existing `person_id`-keyed purge predicate covers them; `discovery_dedup_conflict` events do NOT carry `person_id` (multi-match has no single attributable id) → Pillar J's purge must match the conflict event via `matched_note_paths` element-equality against the deleted person's note path. Pillar J's purge logic MUST handle both predicates. Field-name asymmetry note: `enrollment_conflict` carries `source` (legacy D142 P3-A field name); `discovery_dedup_conflict` carries `source_skill` (canonical D142 name) — Pillar J's purge code processes both event classes via the same `matched_note_paths` predicate, so the field-name divergence is observable but not load-bearing for the purge logic. Pillar J's CAN-SPAM compliance gate is unchanged by Pillar E Week 2 — the dedup primitive doesn't write to suppression YAML (that's Pillar D's auto-unsubscribe path).

## Migration / rollout

The Week 2 deliverable is the dedup primitive module + the per-skill integration in find-leads + the un-skipped coherence test rows + the cross-pillar audit row extension + the unit-test file.

**Operator-facing changes (Week 2):**

1. **No new pending migrations.** `runner.pending()` still returns 17 (the Pillar D + Pillar E Week 1 final state). The dedup primitive is content-additive (NEW event classes; no schema changes to the ledger or vault). Pillar E Week 9-11 ships the vault migration adding `discovery_lineage:` to existing Person notes; Week 2 leaves the migration count unchanged.

2. **New module — `orchestrator/discovery_dedup.py`** — importable via `from orchestrator import discovery_dedup`. The public surface: `check_dedup`, `build_discovery_dedup_hit_payload`, `build_discovery_dedup_conflict_payload`, `DedupResult`, `SOURCE_SKILLS`, `EMITTED_BY`, `CHANNEL_VALUE`. The CLI surface: `python orchestrator/discovery_dedup.py check --linkedin ... --source-skill ... [--source-list ...] [--apply] [--json]`.

3. **`skills/find-leads/SKILL.md` extended** with a new Phase 3e (pre-enrichment dedup check). Operators using `/find-leads` automatically benefit from the dedup primitive's cost-attribution event emission. Existing flows (Phase 3b dedup, Phase 4 lead-list save, Phase 4.5 auto-enrollment) are unchanged.

4. **New CLI subcommand — `python orchestrator/discovery_dedup.py check`** — the dedup primitive's command-line surface. `--apply` flag controls whether the dedup event is appended to the ledger (live mode) or just reported (dry-run, the default).

5. **Existing operators with pre-Pillar-E-Week-2 enrollment events** see no change. The dedup primitive is content-additive; pre-existing `enrolled` + `enrollment_skipped_exists` + `enrollment_conflict` events stay unchanged. The Week 2 commit's only modification to `orchestrator/enrollment.py` was the Week 1 P2-A fix to `needs_identity_upgrade` (per the Week 1 commit, not Week 2). The find-leads SKILL.md change is documentation-only — existing operators rerunning `/find-leads` simply get Phase 3e as an additive step.

**Operator-facing changes (Pillar E Weeks 3+, planned):**

6. **Week 3 ships per-skill integration in `find-funded-founders` + `competitor-customers`.** The two skills gain analogous Phase 3e-equivalent steps in their SKILL.md files. The Week 2 dedup primitive's CLI is reused.

7. **Week 3 un-skips `TestPreEnrichmentDedup::test_three_skills_one_day_consume_one_apollo_credit`.** With three skills wired (find-leads from Week 2 + find-funded-founders + competitor-customers from Week 3), the cross-skill subset of the binding exit-criterion is testable.

8. **Week 4-5 ships the email-verification cache primitive + the `email_verification_cache_hit` event class** (per ADR-0032 D144). Separate cache primitive; sibling-of-the-dedup-primitive surface. ADR-0034 — TBD.

9. **Week 6-8 ships the tier auto-assignment primitive + the `tier_suggested` event class** (per ADR-0032 D145). Separate primitive; consumes Apollo organization_size + industry + funding_stage signals. ADR-0035+ — TBD.

10. **Week 9-11 ships the per-skill `discovery_lineage:` stamping refactor + the coordinating vault migration** (per ADR-0032 D142 + D146). The `research-prospect` integration coincides. ADR-0036+ — TBD.

11. **Week 12's binding exit-criterion test (`TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`) un-skips.** With all the primitives + per-skill integration shipped, the cross-cutting three-skills-one-day-one-credit-each scenario is testable end-to-end.

**The Week 2 commit's verification surface:**

```python
# 1. The dedup primitive module exists + is importable.
$ python -c "from orchestrator.discovery_dedup import check_dedup, DedupResult, build_discovery_dedup_hit_payload, build_discovery_dedup_conflict_payload, SOURCE_SKILLS"

# 2. The dedup primitive unit tests pass.
$ python -m pytest tests/test_discovery_dedup.py -v
# Expected: every per-method test passes (DedupResult invariants, check_dedup happy paths + conflict paths, event-payload contracts, per-skill integration smoke test).

# 3. The coherence test vehicle's Week 2 rows un-skip + pass.
$ python -m pytest tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup -v
# Expected: 4 rows passing + 1 row SKIPPED (the cross-skill subset; un-skips Week 3).

# 4. The dedup CLI runs.
$ python orchestrator/discovery_dedup.py check --linkedin https://linkedin.com/in/test --source-skill find-leads --json
# Expected: JSON output reporting not_duplicate against a real vault (or duplicate if a Person note already exists for `in/test`).

# 5. The full suite is green at +N tests.
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 2374+N passed (the +N comes from: 35 new discovery_dedup unit tests + 4 un-skipped coherence rows).

# 6. ADR-0033 exists; README index gains the row; PILLAR-PLAN §6 Pillar E row updated.
$ ls docs/adr/0033-pillar-e-pre-enrichment-dedup.md
$ grep "0033" docs/adr/README.md
$ grep "Week 2 ✓" docs/PILLAR-PLAN.md
```

### Existing-operator seed

Pillar E Week 2 ships NO new migrations + NO new ledger-state primitives that require an existing-operator seed.

**Bootstrap-step seed for existing operators (Yang):**

The Week 2 commit is content-additive — no operator action required. The dedup primitive is callable via the new CLI; the find-leads skill auto-integrates the Phase 3e step on the next `/find-leads` invocation.

For Yang specifically (the current sole operator), the pre-existing Person notes (~500 today) inherit the dedup primitive's coverage automatically. The next `/find-leads` run with a candidate that intersects an existing Person's `identity_keys` will emit a `discovery_dedup_hit` event; operators verify via:

```bash
python -m orchestrator.ledger grep --type discovery_dedup_hit | head
```

If the operator wishes to backfill historical discovery-source data with `discovery_dedup_hit` events for pre-Pillar-E-Week-2 enrollments, the Pillar I CLI's `python -m orchestrator.discovery_dedup replay --since <date>` ships the one-time backfill ergonomic. Until Pillar I, the audit trail starts at Week 2's commit forward.

The first Pillar E week that ships a vault migration requiring an existing-operator seed (TBD — likely Pillar E Week 9-11's vault migration adding per-Person `discovery_lineage:` block) WILL include the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface the dedup primitive integrates with (no engine change required).
- ADR-0003 (channel as first-class policy predicate) — the cross-channel rule whose behavior the dedup events do NOT trigger (events don't end in `_confirmed`).
- ADR-0004 (suppression rules + GDPR-forget) — the `forget_append` primitive Pillar J's purge transaction extends to dedup events.
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention; the dedup primitive's events are EXPLICITLY distinct from `cost_incurred` (dedup IS the cost-avoidance signal).
- ADR-0009 (migration framework) — Pillar E vault/ledger migrations (Week 9-11+) will register into the existing framework; Week 2 ships ZERO migrations.
- ADR-0010 (ledger migrations) — the D17 `_emitted_by` convention the dedup primitive's events inherit.
- ADR-0011 (vault migrations) — Pillar E Person note migrations (Week 9-11+) consume the existing `add_frontmatter_block_text` + `iter_person_notes` primitives.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — the D24 hybrid synthetic fixture pattern Pillar E Week 12 extends.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-event invariant the dedup events inherit (with `channel: "none"` per D150); the D36 existing-operator-seed pattern Pillar E inherits; the D37 exit-criterion vehicle Pillar E extends.
- ADR-0025 (Pillar D foundation) — the D99 cross-pillar surface audit Pillar E mirrors per ADR-0032 D146 + extends per D153.
- ADR-0026 (Pillar D Week 2 — rule-based classifier) — **THE PRECEDENT FOR PILLAR E WEEK 2.** D102 (classifier module placement — `orchestrator/reply_classifier.py`) → D149 (dedup module placement — `orchestrator/discovery_dedup.py`). D104 (idempotence-by-pair) → no direct parallel (dedup is per-candidate, not per-event). D106 (cross-pillar audit row extension) → D153 (same pattern).
- ADR-0028 (Pillar D auto-unsubscribe + conversation state) — the D117 LOAD-BEARING dedup-by-(reply_message_id, channel) pattern Pillar E's dedup primitive extends to (candidate_partial, source_skill).
- ADR-0030 (Pillar D win/loss attribution) — the D134 `derived_conversation_outcome(person_id)` per-Person aggregation surface Pillar E's discovery-source-to-outcome learning consumes (the per-skill "what fraction of `find-funded-founders` enrollments became `closed_won`?" query).
- ADR-0031 (Pillar D exit-criterion close) — the D140 funnel CLI Pillar E's per-source breakdown extends (Pillar I CLI extension; Week 2 doesn't extend).
- ADR-0032 (Pillar E foundation) — D142 (discovery_lineage shape — the SOURCE_SKILLS enum reserved here for the per-skill stamping refactor in Week 9-11) + D143 (the pre-enrichment dedup contract D149-D153 implements) + D146 (cross-pillar surface audit D153 extends) + D147 (exit-criterion vehicle scope; Week 2 un-skips 4 of the 5 TestPreEnrichmentDedup rows) + D148 (privacy invariant `source_list` inherits — stamped on events but NEVER aggregated by Pillar G dashboards).
- `docs/PILLAR-PLAN.md` §2 Pillar E — exit criterion (binding text); §5 "What we will not do" — Pillar E adjacent constraints; §6 Pillar E row Notes column extended to "Week 1 ✓ + Week 2 ✓" in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D143's dedup contract (false-negative dedup is expensive at scale; false-positive dedup is cheap).
- `docs/RISK-REGISTER.md` R001 (identity-graph false-merge cascade) — risk the dedup primitive does NOT regress (REUSES `identity.find_matches` + `identity.resolve_strict` unchanged). R018 (discovery-source poisoning), R019 (pre-enrichment dedup false-positive), R020 (email-verification cache staleness) — all named in ADR-0032 §Context; the Week 2 implementation does not introduce new risks.
- `docs/SOURCES-OF-TRUTH.md` — no new row added (the dedup primitive emits events; the ledger remains the SoT).
- `.planning/REVIEW-pillar-e-surface-audit.md` — extended in this commit with the Week 2 section per D153.
- `.planning/HANDOFF-pillar-e-week-2.md` — the per-week handoff that scoped Week 2.
- `.planning/HANDOFF-pillar-e-week-3.md` — written in this commit; scopes Week 3 (per-skill integration in find-funded-founders + competitor-customers).
- `orchestrator/discovery_dedup.py` — the primitive module D149 names.
- `orchestrator/identity.py` — the `IdentityKeys` + `find_matches` + `resolve_strict` primitives the dedup primitive REUSES unchanged.
- `orchestrator/enrollment.py` — the BACK-STOP consumer (`enrollment.enroll_person`'s post-enrichment resolve_strict call) the dedup primitive's atomicity contract relies on for the concurrent-race fallback.
- `skills/find-leads/SKILL.md` — the per-skill integration site (Phase 3e added in this commit).
- `tests/test_discovery_dedup.py` — the primitive's unit tests.
- `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup` — the un-skipped 4 of 5 rows that pin the integration-level contract.
- Forward-references (planned):
  - **ADR-0034** (Pillar E Week 4-5): email-verification cache — `orchestrator/email_verification_cache.py` + `email_verification_cache_hit` event class + cache-aware wrapping of `enrich_emails.verify_with_reoon`.
  - **ADR-0035+** (Pillar E Week 6-8): tier auto-assignment — `orchestrator/tier_assignment.py` + `tier_suggested` event + per-signal weights against Yang's operator-tagged corpus.
  - **ADR-0036+** (Pillar E Week 9-11): per-skill `discovery_lineage:` stamping refactor + the `research-prospect` integration + the coordinating vault migration (`vault/0005_add_discovery_lineage_to_identity_keys` — TBD shape).
  - **ADR-00NN** (Pillar E Week 12): exit-gate close — the binding three-skills-one-day exit-criterion test un-skips.
  - **Pillar G dashboards** (Weeks 31-42): cost-per-quality-prospect dashboard consuming `cost_incurred` + `discovery_dedup_hit` + `email_verification_cache_hit` events; per-source funnel breakdown via `source_skill` (NEVER `source_list` per D148).
  - **Pillar I CLI** (Weeks 43-48): aggregation of per-ADR seed blocks + the dedup primitive's replay command + the doctor-preflight extension for dedup-hit-rate anomaly detection + the per-skill stamping refactor's CLI surface.

---

## Amendment 2026-05-24 — Pillar E Week 3 per-skill integration

- **Status:** Accepted (amendment to ADR-0033 D152; D149-D153 contracts unchanged)
- **Date:** 2026-05-24
- **Pillar:** E (Discovery quality + lineage — Week 3 per-skill integration extension)
- **Deciders:** Yang, Claude (architect)
- **Scope:** Wires the dedup primitive into `find-funded-founders` (Phase 4f) + `competitor-customers` (Phase 3e); un-skips `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup::test_three_skills_one_day_consume_one_apollo_credit`; confirms the cross-pillar audit's Week 2 verdict UNCHANGED.

### Context

Pillar E Week 2 (the main body of this ADR — D149-D153) shipped the dedup primitive module + the per-skill integration in `find-leads` (the most active discovery skill). D152 pinned the per-skill integration discipline as the canonical caller pattern — explicit `check_dedup` call at each skill's pre-enrichment site — and reserved the trajectory for the three remaining skills:

- `find-funded-founders` → **Week 3 (this amendment)**
- `competitor-customers` → **Week 3 (this amendment)**
- `research-prospect` → Week 9-11 (per-prospect shape coordinates with the `discovery_lineage:` stamping refactor)

Per `.planning/HANDOFF-pillar-e-week-3.md`'s Design-decisions section: an ADR-0033 amendment vs a new ADR-0034 is determined by whether the per-skill integration surfaces new design decisions. Week 3's integration is **structurally analogous** to find-leads' (canonical caller pattern unchanged; D149-D153 contracts unchanged; only the per-skill phase-numbering placement differs). **A minor ADR-0033 amendment suffices.** A full new ADR-0034 is deferred to Week 4-5 (the email-verification cache primitive — a sibling pillar primitive with its own emit-shape decisions).

### What Week 3 ships (amendment to D152)

#### A1. `find-funded-founders` Phase 4f — the new per-skill integration site

`skills/find-funded-founders/SKILL.md` gains a new sub-phase **4f** (placed at the end of Phase 4, the priority-scoring per-candidate loop):

- Phase 4 = priority scoring (4a Fit / 4b Intent / 4c Engagement / 4d compute priority + tier / 4e research tier / **4f pre-enrichment dedup check**)
- The dedup check runs INSIDE the per-candidate loop, after 4e assigns research tier + before the row aggregates into Phase 5's lead-list save
- Shells to `python orchestrator/discovery_dedup.py check --linkedin <...> --source-skill find-funded-founders --source-list "[[{YYYY-MM-DD}-funded-founders]]" --apply --json`
- The three-status dispatch (`not_duplicate` / `duplicate` / `conflict`) mirrors find-leads' Phase 3e behavior exactly
- The SKIP collapsed-callout bucket list gains `dedup-hit` + `dedup-conflict` rows
- The methodology footer is extended with a "Pre-enrichment dedup (Phase 4f, Pillar E)" line

**Why Phase 4f rather than Phase 3e or Phase 5.5?**

- **Not Phase 3e:** find-funded-founders' Phase 3 ends with buyer-shape search (3c — `search_people` against the URN); the row at end-of-Phase-3 lacks priority + research tier (assigned in Phase 4). The find-leads Phase 3e shape (after per-candidate fit + ICP + tier) maps semantically to AFTER find-funded-founders Phase 4e, not Phase 3c. Inserting at Phase 3.5 would split the per-candidate workflow across the priority-scoring loop boundary; the operator-readable per-candidate flow becomes harder to follow.
- **Not Phase 5.5:** Phase 5.5 is auto-enrollment (OPT-IN per `--enroll`). The dedup check is ALWAYS-ON for any NEW row (the cost-avoidance pin is unconditional per ADR-0032 D143). Conflating ALWAYS-ON dedup with OPT-IN enrollment would mis-signal the dedup primitive's purpose.
- **Phase 4f is the natural continuation of per-candidate computation.** The lowercase letter sub-phase convention (4a/4b/4c/4d/4e) extends to 4f cleanly. The dedup check is the LAST per-candidate computation before the list-aggregation hand-off to Phase 5.

#### A2. `competitor-customers` Phase 3e — direct mirror of find-leads

`skills/competitor-customers/SKILL.md` gains a new sub-phase **3e** (placed at the end of Phase 3, the per-candidate ICP + buyer-shape + score + tier loop):

- Phase 3 = ICP filter + buyer-shape search (3a sanity / 3b ICP / 3c buyer-shape / 3d score + tier / **3e pre-enrichment dedup check**)
- Shells to `python orchestrator/discovery_dedup.py check --linkedin <...> --source-skill competitor-customers --source-list "[[{YYYY-MM-DD}-competitor-customers]]" --apply --json`
- Direct mirror of find-leads' Phase 3e (same phase numbering since Phase 3 = per-candidate workflow in both skills)
- The SKIP collapsed-callout bucket list gains `dedup-hit` + `dedup-conflict` rows
- The methodology footer is extended with a "Pre-enrichment dedup (Phase 3e, Pillar E)" line

**Why Phase 3e (not 3.5 or a new Phase 3.6)?**

competitor-customers' Phase 3 structure is identical to find-leads' Phase 3 (3a-3d sub-phases of the per-candidate loop). Phase 3e fits as the natural next letter. Naming consistency across the two analogous skills aids operator readability — operators reading both SKILL.md files see the same Phase 3e pattern.

#### A3. Un-skip `TestPreEnrichmentDedup::test_three_skills_one_day_consume_one_apollo_credit`

The 5th coherence-test row was reserved at Week 2 specifically for Week 3 un-skip (per ADR-0033 D152's per-skill integration trajectory). The test exercises the COHERENCE-LEVEL subset of the binding exit-criterion (`TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`):

- Three skills (find-leads, find-funded-founders, competitor-customers — all three wired at Week 3) surface the same person in one day
- Each skill's flow uses the canonical caller pattern (per D152's code block) in pure Python (no shell-outs to the CLI; the unit-test smoke test `TestPerSkillIntegrationSmoke::test_three_skills_one_day_same_person_consumes_one_check` is the precedent shape)
- The first skill enrolls (consuming the simulated Apollo + PDL + Reoon credits); the second + third skills' dedup-check returns `duplicate` + emits `discovery_dedup_hit` events + SKIPS enrichment
- The binding assertion: ONE Apollo + ONE Reoon + ONE PDL + ONE enrollment + TWO dedup_hit events (each carrying its own `source_skill` attribution per D150)

**Why coherence-level rather than full exit-criterion-level?**

The full exit-criterion test (`TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`) un-skips at **Pillar E Week 12** with the email-verification cache (Week 4-5) + tier-suggestion (Week 6-8) + per-skill lineage stamping (Week 9-11) composed. Week 3's un-skip is the COHERENCE subset — the dedup-primitive-only portion of the binding scenario.

The phased un-skip trajectory mirrors the Pillar D Week 1-12 precedent (per ADR-0025 D101 → ADR-0026 D107 → ... → ADR-0031 D141): each Pillar E week's un-skip pins the contract that week ships; the final week un-skips the binding exit-criterion row.

#### A4. Cross-pillar surface audit — Week 3 confirmation (UNCHANGED verdict)

`.planning/REVIEW-pillar-e-surface-audit.md` gains a short **Week 3 section** (§18+) confirming the Week 2 verdict UNCHANGED:

- **Zero new event classes.** Week 3 reuses the Week 2 dedup primitive's `discovery_dedup_hit` + `discovery_dedup_conflict` event classes without modification.
- **Zero new ledger-walk patterns.** The cross-skill subset test exercises the SAME ledger-walk shape Week 2's smoke test exercises.
- **Zero new consumer surfaces.** The audit's Week 2 enumeration of `_idx_person` consumers (derived_stage, reachable_pipeline_stages, conversation_status, conversation_outcome, CrossChannelTouchRule, BudgetWindowCapRule, CooldownRule, DomainThrottleRule, Suppress*, last_send_for, Pass G classifier, Pass M auto-unsubscribe, Pass N conversation state, Pass O outcome derivation, funnel CLI) carries forward without amendment.
- **Two new integration call-sites only.** find-funded-founders Phase 4f + competitor-customers Phase 3e. Both call sites use the SAME `check_dedup` + `build_*_payload` surface that find-leads Phase 3e uses; no new public-surface broadening.

The audit's per-week-reviewer-checklist categories (per the audit's §Categories the Pillar E Week N per-week reviewer must keep auditing) all confirm UNCHANGED for Week 3:

1. `_idx_person` broadening: NO (Week 3 reuses Week 2's two new event classes; no new class introduced)
2. New `*_confirmed`-suffixed events: NO
3. Additions to `_STAGE_BY_EVENT_TYPE`: NO
4. New per-prospect dedup-index pattern: NO (Week 3 reuses the per-call O(N) index walk from Week 2)
5. Modifications to `enrollment.py` or pre-existing reconcile passes: NO
6. `identity_keys:` schema extension: NO (the `discovery_lineage:` sub-block is Week 9-11)
7. New `cost_incurred` source name: NO
8. `source_list` surfaced in any operator-facing dashboard / CLI / aggregation: NO (the Layer 1 D148 defense continues to pass)

### What Week 3 does NOT ship

Per the HANDOFF's §"Pillar E Week 3 will NOT ship" guard rails:

- **The email-verification cache.** Week 4-5 (ADR-0034 — TBD).
- **The tier auto-assignment computation.** Week 6-8 (ADR-0035+ — TBD).
- **The per-skill `discovery_lineage:` stamping refactor.** Week 9-11.
- **The `research-prospect` integration.** Week 9-11 (per-prospect shape coordinates with the lineage refactor).
- **The cost-per-quality-prospect dashboard.** Pillar G (forward-reference only).
- **The FULL exit-criterion test** (`TestPillarEExitCriterion::test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates`). Pillar E Week 12.
- **A CLI for any Pillar E operation beyond the dedup primitive's `check` subcommand.** Pillar I.
- **The renaming of `enrolled.source` to `enrolled.source_skill`** (P3-A from the Week 1 audit). Week 9-11.

### Alternatives considered (Week 3 amendment)

#### Alt-A: Ship Week 3 as a new ADR-0034 instead of amending ADR-0033

**Rejected** because the per-skill integration is structurally analogous to find-leads' (no new design decisions; D149-D153 contracts unchanged; only per-skill phase-numbering placement differs). A new ADR-0034 for two additional integration sites would inflate the ADR sequence without adding decision content. The amendment pattern preserves the structural unity of "D152 = per-skill integration discipline" — find-funded-founders + competitor-customers are extensions of D152's existing per-skill trajectory, not new decisions. ADR-0034 is reserved for the next Pillar E primitive (the email-verification cache — Week 4-5) where genuinely new design decisions land (cache substrate choice, event-shape contract, TTL semantics, ledger-as-substrate-derivation per ADR-0032 D144).

#### Alt-B: Wire only one skill in Week 3; defer the other to Week 4

**Rejected** because the binding cross-skill coherence test (`test_three_skills_one_day_consume_one_apollo_credit`) requires THREE wired skills (find-leads from Week 2 + two more from Week 3). Shipping only one skill in Week 3 would defer the un-skip to Week 4 — increasing the gap between dedup-primitive ship (Week 2) and dedup-coherence-test-un-skip (would be Week 4 not Week 3). The asymmetric-failure-cost calculus per PILLAR-PLAN §0 favors closing the per-week un-skip trajectory at the earliest week where it's structurally feasible — Week 3.

#### Alt-C: Insert find-funded-founders' dedup at Phase 3.5 (after buyer-shape, before priority scoring)

**Rejected** because the row at end-of-Phase-3 lacks priority + research tier (assigned in Phase 4). The find-leads Phase 3e semantic shape — pre-enrichment dedup check AFTER all per-candidate metadata is computed AND BEFORE the lead-list save — maps to AFTER find-funded-founders Phase 4e, not Phase 3c. Inserting at Phase 3.5 would mean the dedup-skipped rows still consume priority-scoring computation; Phase 4f correctly short-circuits the entire row (no priority score is computed for a dedup-skipped row in a future refinement — TBD; today the priority score is still computed but the row is re-bucketed to SKIP).

A minor wrinkle: today the priority score IS computed for dedup-skipped rows because Phase 4 runs before Phase 4f. Future refinement (post-Week 3) MAY move the dedup check earlier OR add a guard to skip priority scoring on early-dedup-hit detection. The current Phase 4f placement matches the "after all per-candidate computation, before list aggregation" shape that find-leads Phase 3e established; the trade-off of redundant priority computation for already-dedup-hit rows is small (priority scoring is pure-Python; no LinkedIn / Apollo / Reoon API calls in Phase 4).

### Consequences (Week 3 amendment)

**Positive:**

- **Three of four discovery skills are now Pillar E pre-enrichment-dedup integrated** (find-leads + find-funded-founders + competitor-customers). The cost-avoidance contract per ADR-0032 D143 covers ~95% of operator-driven discovery volume (research-prospect is per-prospect, lower-volume).
- **The cross-skill subset of the binding exit-criterion is testable + passing.** Week 12's full exit-criterion test composes additional primitives but the dedup-only subset is locked in.
- **The per-skill SKILL.md changes are operator-readable.** Each skill's Phase 3e / 4f section names the dedup check at the same operator-visible level as the existing Phase 0 dedup-index build + the existing Phase 3b/2c state-aware dedup.
- **No ADR-0034 sprawl.** The amendment pattern preserves ADR-0033 as the single source of truth for the dedup primitive — the per-skill integration discipline + its three (now-five — research-prospect deferred to Week 9-11; manual is invocation-shape so not a SKILL.md surface).

**Negative:**

- **`research-prospect` remains unintegrated until Week 9-11.** Operators using `/research-prospect` on a per-prospect dossier today don't see the dedup-hit cost-attribution event for that surface. Mitigation: `research-prospect` is per-prospect (lower volume than the list-based discovery skills); operators who care about per-prospect dedup can shell to `python orchestrator/discovery_dedup.py check --apply` manually before invoking `/research-prospect`.
- **find-funded-founders' priority-scoring computation runs even for dedup-skipped rows.** Phase 4 runs before Phase 4f; dedup-skipped rows have their priority score computed before being re-bucketed to SKIP. Mitigation: priority scoring is pure-Python (no external API calls); the wasted computation is on the order of milliseconds per row. A future refinement MAY move the dedup check earlier OR add an early-exit guard.
- **The `--apply` flag is operator-visibility-dependent.** If an operator (or a future SKILL.md author) forgets `--apply`, the dedup-hit events don't land in the ledger. Mitigation: every SKILL.md (find-leads + find-funded-founders + competitor-customers) explicitly names `--apply` in the canonical code block + the §"Why `--apply`" callout names the consequence loudly.

**Neutral / observability:**

- **Two new `discovery_dedup_hit.source_skill` values populate the ledger** (`find-funded-founders` + `competitor-customers`). Pillar G's per-source dedup-hit-rate dashboard (Weeks 31-42) gains two more aggregation buckets.

### Compliance with invariants (Week 3 amendment)

- **I1 (single source of truth):** UNCHANGED. Week 3 does not add a new SoT row. The dedup primitive emits events; the ledger remains the SoT.
- **I2 (two-phase commit):** UNCHANGED. Week 3 does not add new external side effects. The find-funded-founders + competitor-customers SKILL.md changes shell to the existing dedup CLI; no new write surfaces.
- **I3 (schema versioning):** UNCHANGED. Week 3 does not introduce new event types or fields.
- **I4 (reproducible state):** UNCHANGED. The dedup primitive's determinism contract is unchanged.
- **I5 (observable by default):** UNCHANGED. Week 3 does not add new fields; the existing `source_skill` enum values (`find-funded-founders` + `competitor-customers`) populate the existing `discovery_dedup_hit` event class.
- **I6 (tests prove invariants):** Week 3 un-skips one new coherence row (`test_three_skills_one_day_consume_one_apollo_credit`); the row pins the cross-skill subset of the binding exit-criterion. Pre-existing tests pass unchanged.
- **I7 (cost is a first-class concern):** STRENGTHENED. Week 3 wires two more skills into the cost-avoidance signal; operators gain per-source visibility into "which discovery skill is rediscovering already-known prospects" at the Pillar G dashboard layer.
- **I8 (documented decisions):** This amendment. `docs/adr/README.md` ADR-0033 row note is extended with "+ Week 3 amendment 2026-05-24"; the per-skill SKILL.md files reference the amendment via the §Why-Pillar-E callout.

### Pin (Week 3 amendment)

- `skills/find-funded-founders/SKILL.md` Phase 4f added; pipeline-summary updated; SKIP-bucket list extended; methodology footer extended.
- `skills/competitor-customers/SKILL.md` Phase 3e added; pipeline-summary updated; SKIP-bucket list extended; methodology footer extended.
- `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup::test_three_skills_one_day_consume_one_apollo_credit` un-skipped + passing.
- `.planning/REVIEW-pillar-e-surface-audit.md` Week 3 section appended (§18+, UNCHANGED verdict).
- `docs/PILLAR-PLAN.md` §6 Pillar E row Notes column updated to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓".
- `docs/adr/README.md` ADR-0033 row note extended with the Week 3 amendment date.

### References (Week 3 amendment)

- `.planning/HANDOFF-pillar-e-week-3.md` — the per-week handoff that scoped Week 3.
- `.planning/HANDOFF-pillar-e-week-4.md` — written in this commit; scopes Week 4-5 (the email-verification cache primitive).
- `skills/find-funded-founders/SKILL.md` — Phase 4f added in this commit.
- `skills/competitor-customers/SKILL.md` — Phase 3e added in this commit.
- `tests/test_multi_channel_coherence.py::TestPreEnrichmentDedup::test_three_skills_one_day_consume_one_apollo_credit` — un-skipped in this commit.
- `tests/test_discovery_dedup.py::TestPerSkillIntegrationSmoke::test_three_skills_one_day_same_person_consumes_one_check` — the Week 2 smoke-test precedent the Week 3 coherence test extends.
- `.planning/REVIEW-pillar-e-surface-audit.md` — §18+ Week 3 section appended (UNCHANGED verdict).
