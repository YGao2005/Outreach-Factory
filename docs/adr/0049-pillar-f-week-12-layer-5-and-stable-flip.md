# ADR-0049: Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** F (Voice corpus + draft quality — Week 12 — exit-criterion close)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation; Week 2 (ADR-0039 D185-D191) shipped the embedding-retrieval primitive; Week 3 (ADR-0040 D192-D198) shipped the per-register adapters; Week 4 (ADR-0041 D199-D205) shipped the per-register threshold loader; Week 5 (ADR-0042 D206-D211) shipped the operator-facing thresholds CLI; Week 6 (ADR-0043 D212-D219) shipped the hallucination-detection Layer 2-3 primitive; Week 7 (ADR-0044 D220-D227) shipped the per-claim-type test corpora + measurement primitive; Week 8 (ADR-0045 D228-D235) shipped the per-draft voice-fidelity scoring primitive + the `draft_quality_scored` event class; Week 9 (ADR-0046 D236-D243) shipped the per-claim fuzzy-match citation extension at the Layer 3 parser; Week 10 (ADR-0047 D244-D251) shipped the Layer 4 post-engine guard + the `draft_ready` event class + the per-dimension operator-override path; **Week 11** (ADR-0048 D252-D261) shipped the Layer 3 parser corpus revision (paraphrased-ready pairs + per-claim-type bound tightening). Week 11 closed at `17a6004` + follow-up `6c8a1fe` (0 P1 + 2 P2 + 3 P3 addressed); 3325 tests passing post-follow-up; 15 skipped (the Layer 5 row + the binding exit-criterion row stay SKIPPED through Week 11).

**Pillar F Week 12 is the EXIT-CRITERION CLOSE.** Per PILLAR-PLAN §2 Pillar F binding text:

> *"mean voice-fidelity score per register meets baseline; hallucination false-negative rate on a 200-draft eval set < 1%."*

Plus ADR-0038 D180's FIVE-layer defense-in-depth contract — Layers 1+2+3 SHIPPED at Week 6 + 8 + 9; Layer 4 SHIPPED at Week 10; **Layer 5 SHIPS at this commit.**

Week 12 ships the THREE bundled deliverables that satisfy the exit criterion + flip Pillar F from "In progress" to **Stable**, per the Pillar E Week 12 precedent (ADR-0037 D172-D177):

1. **Layer 5 reconcile Pass C heal-pass refusal extension** at `orchestrator/reconcile.py` — walks per-Person `draft_ready` events via the existing `_idx_person` index (per ADR-0047 D251 + ADR-0038 D182 audit category 1); refuses to ratify any post-Pass-C vault stage of `ready` when no corresponding `draft_ready` event exists in the ledger. The FINAL structural backstop per ADR-0038 D180 Layer 5 — a draft that bypassed Layers 1-4 still cannot advance the pipeline.

2. **Two binding tests un-skip** at `tests/test_multi_channel_coherence.py`:
   - **`TestHallucinationDetection::test_reconcile_pass_c_refuses_advance_to_ready_on_uncited`** — THE Week 1 binding behavioral commitment per ADR-0038 D180 Layer 5 + ADR-0049 D262/D263.
   - **`TestPillarFExitCriterion::test_voice_fidelity_per_register_meets_baseline_and_hallucination_false_negative_rate_under_one_percent`** — THE binding 200-draft eval set's `<1%` FN bound per PILLAR-PLAN §2 Pillar F + ADR-0049 D265/D266.

3. **Pillar F Stable flip** — per the Pillar E Week 12 precedent (ADR-0037 D175): binding tests as THE gate + per-pillar stable-flip checklist + Pillar F retrospective at `.planning/RETRO-pillar-f.md`. `docs/PILLAR-PLAN.md` §6 Pillar F row Status column flips from "In progress" to "**Stable** as of 2026-05-25".

The ten concerns this ADR resolves:

1. **Module placement for the Layer 5 extension** — extend `orchestrator/reconcile.py` (per ADR-0010 D17's per-Person heal-pass scope + ADR-0047 D244-Alt5's per-Layer-module rejection) OR ship a new sibling at `orchestrator/layer_5_guard.py`. **D262** pins.

2. **Pass C refusal semantics + heal-pass write surface** — surface `reconcile_drift` finding with a NEW `reason` value `"ready_without_draft_ready_event"`; emit drift event when `apply=True`; do NOT rewrite vault (mirrors the existing `vault_ahead_of_ledger` precedent at `reconcile.py` Pass C). **D263** pins.

3. **ZERO new migrations** at Week 12 — the existing `_idx_person` index already covers the `draft_ready` event class per ADR-0047 D251; Pass C's per-Person query consumes the index without schema changes. **D264** pins.

4. **200-draft eval set fixture shape** — programmatic builder inline in the test body (NOT a separate `tests/fixtures/pillar_f_eval/`) mirroring Pillar E Week 12's inline construction precedent per ADR-0037 D173 + per ADR-0038 D183's verification-only scope. **D265** pins.

5. **Exit-criterion test vehicle scope** — extend `tests/test_multi_channel_coherence.py::TestPillarFExitCriterion` (the Week 1 stub per ADR-0038 D183) with the binding test body. **D266** pins.

6. **Pillar F Stable-flip discipline** — binding tests as THE gate + per-pillar stable-flip checklist per the Pillar E Week 12 precedent (ADR-0037 D175). **D267** pins.

7. **Pillar F retrospective** — `.planning/RETRO-pillar-f.md` per ADR-0037 D176's Pillar D / Pillar E Week 12 precedent. **D268** pins.

8. **`voice_retrieve.py` deprecation decision** — P3-A carry-forward from Pillar F Week 1 (deprecation gate at Week 12 per ADR-0045 §Migration/rollout). Preserve as documentation-only backwards-compat (NOT remove). **D269** pins.

9. **Cross-pillar audit row extension** — UNCHANGED verdict per ADR-0037 D177's precedent (the Week 12 deliverables introduce ZERO new event classes, ZERO new ledger-walk patterns, ZERO new operator-facing surfaces beyond the Pass C extension's existing `reconcile_drift` shape). **D270** pins.

10. **SKILL.md Phase 6 extension naming the Pass C heal-pass behavior** — operators reading the skill's Phase 6 narrative see a one-line note about the Layer 5 backstop. **D271** pins.

Risks this ADR mitigates by design:

* **R023 (Hallucination-detection false-negative)** — FINAL mitigation. The FIVE-layer defense closes at Week 12 with Layer 5; the 200-draft eval set's `<1%` FN bound is now a passing test per the structural commitment of ADR-0038 D180 + D184.
* **R024 (voice-corpus drift)** continues mitigated — orthogonal to Pass C.
* **R025 (embedding-cost runaway)** continues mitigated — Pass C's per-Person `draft_ready` query consumes the existing `_idx_person` index; ZERO new encoder calls.
* **R026 (operator-corpus split)** continues mitigated — orthogonal.
* **R027 (per-claim false-positive rate)** continues mitigated — orthogonal.
* **R028 (per-register threshold mis-calibration)** continues mitigated — Pass C consults per-Person `draft_ready` events; the per-register threshold's per-event payload (via the upstream `draft_quality_scored` per ADR-0045 D231) is the audit substrate.
* **R029 (per-claim fuzzy-match false-positive)** continues mitigated + BOUNDED at FINAL — Week 11 added per-pair behavioral coverage; Week 12 ships the binding 200-draft eval set's `<1%` FN bound as THE final structural commitment.
* **R030 (Layer 4 emit-guard bypass via direct payload construction)** — FINAL mitigation. Week 10 surfaced R030 + named the Week 12 Pass C extension as THE final structural backstop. Week 12 ships the backstop; the risk is now mitigated end-to-end.

No new risks. Week 12 ships the closing deliverables for the FIVE-layer defense + the binding exit criterion; no Week 12 commit introduces a new failure surface that isn't bounded by existing mitigations.

## Decision

### D262. Module placement — extend `orchestrator/reconcile.py` (the Pass C extension)

The Layer 5 backstop lives at `orchestrator/reconcile.py` (Pass C — the existing per-Person heal-pass orchestrator per ADR-0011 + ADR-0028 D119). New surfaces:

* **`_LAYER_5_DRIFT_REASON: str = "ready_without_draft_ready_event"`** — module-level constant naming the new `reconcile_drift` reason for Layer 5 refusals.
* **`_person_has_draft_ready_event(led, person_id) -> bool`** — private predicate walking the per-Person index (`led.all_events_for_person(person_id)`) for `draft_ready` events.
* **`run_pass_c` extension** — Layer 5 pre-check before the existing pipeline_stage heal dispatch. When the EFFECTIVE post-Pass-C vault stage would be `ready` (either vault already claims it OR ledger would heal vault forward to it via `l_rank >= v_rank`), require a `draft_ready` event; absence surfaces `reconcile_drift` with `reason=_LAYER_5_DRIFT_REASON` + `continue`s the per-Person iteration.

The module's growth: ~3254 LOC (post-Week-11) → ~3300 LOC (post-Week-12; +~46 LOC for the predicate + module constant + Pass C pre-check + docstrings).

**Why extend `orchestrator/reconcile.py` (rejected: NEW sibling at `orchestrator/layer_5_guard.py`; rejected: extend `orchestrator/draft_quality.py`; rejected: per-Layer modules).**

* **Extend `orchestrator/reconcile.py`** matches the per-Pillar-F per-Layer module convention per ADR-0047 D244 (Layers 2-4 at `orchestrator/draft_quality.py`; **Layer 5 at `orchestrator/reconcile.py`** — the per-pass orchestrator). The Layer 5 backstop IS a heal-pass refusal at the per-Person reconcile surface; co-locating with the existing Pass C dispatch preserves the per-pass scoping + the operator-readable module shape.
* **NEW sibling module at `orchestrator/layer_5_guard.py`** is rejected because Layer 5 IS a Pass C extension — splitting into a sibling module creates the "look in two places" mental model the Pillar A/B/C/D/E foundational ADRs reject (per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0044 D220 + ADR-0045 D228 + ADR-0046 D236 + ADR-0047 D244). The per-pass orchestrator's existing Pass C extension precedent (ADR-0028 D119 added the `conversation_status:` heal alongside the `pipeline_stage:` heal in a single Pass C iteration) is the model for Week 12's Layer 5 addition.
* **Extend `orchestrator/draft_quality.py`** is rejected because the Week 6-10 primitives at that module are per-DRAFT (per-call construction + per-draft-emit factory + per-draft-gate scorer); Layer 5 is per-PERSON (heal-pass on the per-Person ledger walk). The per-call scope mismatch is structural — Layer 5 BELONGS at the per-Person orchestrator.
* **Per-Layer modules** (e.g., `orchestrator/layers/5_reconcile_guard.py`) is rejected per ADR-0047 D244-Alt4 — per-Layer semantics are LABELS on the defense-in-depth (per ADR-0038 D180), not module-split signals. The FIVE-layer defense ships across Weeks 6 + 8 + 9 + 10 + 12 at TWO modules' increasing surface area (`draft_quality.py` for Layers 2-4; `reconcile.py` for Layer 5).

### D263. Pass C refusal semantics + heal-pass write surface

The Layer 5 check inside `run_pass_c`:

```python
v_rank = STAGE_RANK.get(vault_stage or "", -1)
l_rank = STAGE_RANK.get(ledger_stage or "", -1)
ratifies_ready = (
    vault_stage == "ready"
    or (ledger_stage == "ready" and l_rank >= v_rank)
)
if ratifies_ready and not _person_has_draft_ready_event(led, person_id):
    finding = {
        "kind": "reconcile_drift",
        "person_id": person_id,
        "note_path": str(note),
        "vault_stage": vault_stage,
        "ledger_stage": ledger_stage,
        "conflict": True,
        "reason": _LAYER_5_DRIFT_REASON,
    }
    result.findings.append(finding)
    if apply:
        _safe_append(led, {
            "type": "reconcile_drift",
            "person_id": person_id,
            "note_path": str(note),
            "vault_stage": vault_stage,
            "ledger_stage": ledger_stage,
            "conflict": True,
            "reason": _LAYER_5_DRIFT_REASON,
        }, result.errors)
    continue
```

**The Layer 5 trigger condition: `ratifies_ready and not _person_has_draft_ready_event(led, person_id)`.** The `ratifies_ready` predicate captures two cases — (a) vault already claims `ready` (operator-deliberate SKILL.md Phase 6 stamp per ADR-0047 D249); (b) ledger derives stage `ready` AND heal would advance vault forward (the legacy `review_approved`-event path per `_STAGE_BY_EVENT_TYPE`). Both cases require a `draft_ready` event evidence in the ledger.

**The refusal action: surface `reconcile_drift` + skip the per-Person iteration.** Mirrors the existing `vault_ahead_of_ledger` precedent at `reconcile.py` Pass C — Pass C does NOT rewrite the vault on a Layer 5 refusal; the drift is the operator's signal for review. The `continue` skips the remaining per-Person dispatch (pipeline_stage heal + conflict surfacing) — Layer 5 is decision-final at the per-Person grain.

**The `reason` value: `"ready_without_draft_ready_event"`.** The NEW string disambiguates Layer 5 refusals from the existing `"vault_has_stage_but_ledger_empty"` + `"vault_ahead_of_ledger"` reasons. Pillar I per-tenant audit-tooling reads `reconcile_drift` events filtered by `reason` for per-operator override-rate dashboards; the new value is structurally distinct.

**Why this refusal semantic (rejected: surface a NEW finding kind `layer_5_drift`; rejected: rewrite vault to `drafted` on refusal; rejected: emit a NEW event class `draft_ready_missing`; rejected: silent-skip without surfacing).**

* **Surface `reconcile_drift` with NEW reason** preserves the existing Pass C consumer surface — Pillar I per-tenant audit-tooling reads `reconcile_drift` events for operator-visible drift findings (per ADR-0028 D119's `reconcile_drift` shape). The NEW `reason` value extends the closed-set predicate without breaking existing readers. Operators reading the per-Person drift surface see the Layer 5 refusal in the same dashboard as other drift cases.
* **NEW finding kind `layer_5_drift`** is rejected because (a) the per-Pass-C finding shape is `reconcile_drift` per the existing convention; introducing a kind variant fragments the consumer surface; (b) the audit-tooling readers' closed-set predicate over `kind` would need extension at every consumer site (per ADR-0028's category 2 rejected pattern).
* **Rewrite vault to `drafted` on Layer 5 refusal** is rejected per the existing Pass C precedent — Pass C does NOT downgrade vault stage when conflict arises (`vault_ahead_of_ledger` surfaces drift but leaves vault unchanged). Downgrading would (a) silently lose operator state; (b) create a write-on-refuse pattern unseen elsewhere in reconcile; (c) require a more elaborate ledger event (`reconcile_downgraded`) that doesn't fit the Pillar F Week 12 minimal-surface trajectory.
* **NEW event class `draft_ready_missing`** is rejected because the EXISTING `reconcile_drift` event class covers Pass C drift findings; introducing a per-Layer event class fragments the consumer surface (Pillar I audit-tooling would need TWO ledger walks instead of one) + ZERO new event classes at Week 12 matches the Pillar E Week 12 precedent (ADR-0037 D177 — UNCHANGED verdict on the cross-pillar audit).
* **Silent-skip without surfacing** is rejected per the framework's I7 invariant + the Pillar D Week 4-5 `suppression_added` precedent per ADR-0028 D116 — refuse-loud at the structural backstop is the framework convention; silent-skip would hide the Layer 4 bypass case from the operator-visible audit trail.

### D264. ZERO new migrations at Week 12 — `_idx_person` covers `draft_ready`

The `draft_ready` event class carries `person_id` (per ADR-0047 D246); the existing per-Person index `Ledger._idx_person` (per ADR-0010 D17) covers the event without schema changes. Pass C's per-Person query consumes the index via `led.all_events_for_person(person_id)` + filters by `event.type == "draft_ready"` — a closed-set predicate per ADR-0011 D24's pattern. Pending count stays at 19.

**Migration-free trajectory rationale (rejected: ONE new ledger migration backfilling synthetic `draft_ready` events for pre-Week-10 `review_approved` events; rejected: ONE new vault migration clearing stale `pipeline_stage: ready` stamps; rejected: NEW dedicated index `_idx_draft_ready_by_person`).**

* **ZERO new migrations** matches the Pillar E Week 12 precedent (ADR-0037 §Migration/rollout — ZERO new migrations at the Week 12 close commit). The Pass C extension is content-additive at the consumer surface; the existing `_idx_person` index is sufficient. Operators upgrading from Week 11 to Week 12 with stale `pipeline_stage: ready` notes (from BEFORE Week 10's Layer 4 ship) MAY see Layer 5 drift findings until they re-emit `draft_ready` events via the Week 10 emit-ready CLI (per ADR-0047 D248); the operator-side action is one-time + bounded per the §Existing-operator seed section below.
* **ONE ledger migration backfilling `draft_ready`** is rejected because (a) the per-Person backfill heuristic would synthesize `draft_ready` events without consulting the upstream `DraftQualityResult` + `DraftFidelityResult` (the Layer 4 emit-guard's structural commitment per ADR-0047 D245 is REFUSE-LOUD on `state="refused"`; synthesizing `draft_ready` on legacy `review_approved` would falsely certify drafts that may have been low-fidelity OR uncited); (b) the per-Person backfill would write to the append-only ledger creating audit-trail pollution; (c) the operator-side burden is bounded — operators with legacy `pipeline_stage: ready` notes (≤ a few hundred Persons in Yang's vault per the existing scale) re-emit via the CLI in minutes.
* **ONE vault migration clearing stale stamps** is rejected per the same I1 invariant + ADR-0011 D24 (the ledger is SoT; vault drift heals to ledger). The Pass C extension's Layer 5 refusal IS the operator-side signal that the stamp lacks ledger evidence; operators decide per-Person whether to re-emit (Week 10 CLI) or accept the drift (the draft is unsendable until re-emitted).
* **NEW dedicated index `_idx_draft_ready_by_person`** is rejected per ADR-0010 D17's per-call cost analysis — the per-Person `_idx_person` query is O(E_p) where E_p is the per-Person event count (~1-100 events per Person in operational use); the per-call cost is bounded at sub-millisecond. A dedicated index would save the per-Person event-class filter but the index-rebuild cost is O(N) where N is total event count; for a single Pass C query the trade-off is unfavorable. Future Pillar H (real-time + scale) may revisit if per-call cost becomes a bottleneck.

### D265. 200-draft eval set fixture shape — programmatic builder inline in the test body

The 200-draft eval set is constructed inline in `test_voice_fidelity_per_register_meets_baseline_and_hallucination_false_negative_rate_under_one_percent` via per-register draft templates + per-entity dossier construction. The composition:

* **5 registers × 40 drafts each = 200 drafts.**
* **Per register: 36 valid drafts (claim cited) + 4 adversarial drafts (claim NOT cited) = 200 total** (180 valid + 20 adversarial).
* **Each draft contains a 2-word named-entity claim** matching the per-register SKILL.md template (cold-pitch / congrats / re-engagement / reply / public-comment per ADR-0038 D181).
* **Per-entity dossiers** include a markdown link to the entity (valid) OR an unrelated company mention (adversarial).
* **Stub `embed_fn`** (zero vector) disables fuzzy match — the parser's deterministic substring path catches valid drafts; adversarial drafts return None (uncited).
* **Stub `retrieve_fn`** returns 5 high-score exemplars (score=0.95) — fidelity-dimension composition verification per ADR-0049 D266.

**Why inline programmatic builder (rejected: static YAML fixture at `tests/fixtures/pillar_f_eval/200_drafts.yml`; rejected: shared conftest fixture; rejected: per-register sub-tests).**

* **Inline programmatic builder** matches the Pillar E Week 12 precedent (ADR-0037 D174 — the binding test's fixture wiring is inline + per-test). The 200-draft composition is structural (deterministic per-register + per-entity loop); externalizing to YAML adds file-format coupling without behavior gain. The test's load-bearing property IS the composition logic; readers see the construction in one place adjacent to the assertions.
* **Static YAML fixture at `tests/fixtures/pillar_f_eval/`** is rejected because (a) the 200-draft composition is loop-generated (the per-register × per-entity expansion is structural, not data-driven); a YAML enumeration would duplicate the loop's outputs verbatim with no maintainability gain; (b) any change to the per-register template OR per-entity firsts list would require regenerating the YAML; (c) the Pillar E Week 12 + Pillar D Week 12 + Pillar C Week 12 precedents all chose inline construction for the binding test fixture.
* **Shared conftest fixture** (`tests/conftest.py::pillar_f_eval_set_200_drafts`) is rejected because the eval set is binding-test-specific (the test's structural commitment + the test's assertions are co-located); externalizing the fixture inverts the per-test scope without proportional reuse benefit. Future Pillar F tests that need a similar eval set MAY extract a fixture at that time per YAGNI.
* **Per-register sub-tests** (5 separate test methods, one per register, each scoring 40 drafts) is rejected per the binding-test-as-one-scenario convention per ADR-0037 D173 + ADR-0031 D141 (Pillar D Week 12 precedent) — the binding text per PILLAR-PLAN §2 Pillar F names ONE composite assertion (mean fidelity per register + FN_rate < 1% over the 200-draft set); decomposing into per-register methods loses the cross-register aggregation.

### D266. Exit-criterion test vehicle scope — extend `tests/test_multi_channel_coherence.py::TestPillarFExitCriterion`

The binding test un-skips inside the existing `TestPillarFExitCriterion` class in `tests/test_multi_channel_coherence.py` (the stub landed at Week 1 per ADR-0038 D183). The class's single method `test_voice_fidelity_per_register_meets_baseline_and_hallucination_false_negative_rate_under_one_percent` un-skips + the body lands in this Week 12 commit. Per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 the cross-pillar coherence file is the single canonical exit-criterion vehicle.

The Week 12 commit adds ~200 LOC to the existing file (the binding test body + the per-register template dict + the per-entity loop + the assertions); the file's cumulative size approaches ~7800 LOC. The Pillar E Week 12 ADR (ADR-0037 D172) flagged ~7500 LOC as the file-split threshold; Pillar F Week 12 crosses this threshold at ~7800 LOC. The split argument is now LIVE — Pillar G + Pillar H + Pillar I + Pillar J authors MAY split the file per their per-week trajectory at their cadence. Pillar F Week 12 does NOT split (the binding test belongs adjacent to the per-class stubs that compose it per ADR-0014 D37's single-file rationale).

**Why extend the existing file (rejected: separate `tests/test_pillar_f_exit_criterion.py`; rejected: inline as multiple shorter tests; rejected: split the file at Week 12).**

* **Extend the existing file** matches the per-pillar precedent (Pillar A + B + C + D + E all chose single-file coherence per the foundational ADRs). Splitting at Week 12 (the LAST Pillar F week's commit) would create a per-pillar fragment without a structural reason — the test composes the per-pillar surfaces; the surfaces' coherence verification IS the file's purpose.
* **Separate `tests/test_pillar_f_exit_criterion.py`** is rejected per the same rationale as ADR-0037 D172-Alt1 + Pillar D Week 12 ADR-0031 D136 precedent — the single-file coherence vehicle's load-bearing property is cross-pillar visibility from one file.
* **Inline as multiple shorter tests** is rejected per the binding-test-as-one-scenario convention (D265-Alt4 above + ADR-0037 D173-Alt1).
* **Split the file at Week 12** is rejected because Week 12 IS the close commit; the per-week trajectory does not introduce new test rows requiring extension space. Future pillars MAY split if the per-pillar extension trajectory demands it.

### D267. Pillar F Stable-flip discipline — binding tests as the gate + per-pillar stable-flip checklist

Per ADR-0014 D37 + ADR-0025 D101 + ADR-0031 D141 + ADR-0037 D175's per-pillar stable-flip precedent. The Pillar F Stable flip's gate is BOTH binding tests passing in this Week 12 commit:

* `TestHallucinationDetection::test_reconcile_pass_c_refuses_advance_to_ready_on_uncited` — Layer 5 binding behavioral commitment.
* `TestPillarFExitCriterion::test_voice_fidelity_per_register_meets_baseline_and_hallucination_false_negative_rate_under_one_percent` — 200-draft eval set's `<1%` FN bound + per-register fidelity baseline.

The PILLAR-PLAN §6 Pillar F row's Status column flips from "In progress" to "**Stable** as of 2026-05-25"; the Notes column appends "+ Week 12 ✓ — Pillar F Stable (binding exit-criterion tests passing; the FIVE-layer defense closes at Layer 5)."

The per-pillar stable-flip checklist (inherited from ADR-0037 D175's Pillar E Week 12 precedent):

1. **Every exit-criterion bullet from PILLAR-PLAN §2 verified.** Pillar F's two exit-criterion sub-bullets: (a) every claim in the draft traces to a citation in the research dossier — verified by Layers 1-5 (Week 1 + Week 6 + Week 9 + Week 10 + Week 12 un-skipped); (b) mean voice-fidelity score per register meets baseline + hallucination FN_rate < 1% on the 200-draft eval set — verified by THIS binding test (Week 12 un-skipped).

2. **Every per-week handoff doc closed.** `.planning/HANDOFF-pillar-f-week-{1,2,3,4,5,6,7,8,9,10,11,12}.md` (twelve handoff documents — Week 12 is this commit's authoring).

3. **Cross-pillar audit's verdict at "no P1 outstanding."** `.planning/REVIEW-pillar-f-surface-audit.md` §65+ (this commit's extension) confirms UNCHANGED verdict — the Week 12 deliverables introduce ZERO new event classes + ZERO new ledger-walk patterns + ZERO new operator-facing surfaces beyond the Pass C extension's existing `reconcile_drift` shape.

4. **The binding tests passing in CI for ≥1 day.** Observational, not gating. The Week 12 main commit ships both tests passing; the per-week reviewer's verification confirms the pass before the follow-up commit (per the Pillar E Week 12 precedent).

**Why the binding tests gate the Stable flip (rejected: per-week-reviewer sign-off as the gate; rejected: full Pillar G dashboard validation; rejected: holistic exit review as the gate).**

* **Binding tests gate the Stable flip** per the Pillar A/B/C/D/E precedent — the binding test IS the exit-criterion vehicle's structural verification. Pillar F has TWO binding tests (Layer 5 + 200-draft eval); BOTH must pass.
* **Per-week-reviewer sign-off** is rejected per ADR-0037 D175-Alt2 — per-week reviewers' findings are scope-bounded to the per-week commit; the binding tests verify cross-week composition.
* **Full Pillar G dashboard validation** is rejected per ADR-0037 D175-Alt3 — Pillar G is downstream; coupling Pillar F's stable flip to Pillar G's timeline indefinitely defers.
* **Holistic exit review** is rejected per ADR-0037 D175-Alt1 — holistic reviews are optional addenda; the binding tests are the structural gate.

### D268. Pillar F retrospective — `.planning/RETRO-pillar-f.md`

Per ADR-0037 D176's Pillar E Week 12 precedent. The retrospective document captures:

* **§Calibration headline** — the per-pillar week-budget vs calendar-day-cost calibration (twelve pillar-weeks budgeted; one calendar day's worth of compressed execution per the Pillar D + Pillar E precedent).
* **§What worked** — the patterns Pillar F confirmed (per-Layer-per-week defense-in-depth + per-week-handoff + per-week-review-with-follow-up-commit + per-ADR ≥3-rejected-alternatives + cell-level-matrix-coverage discipline + behavioral-passthrough-not-signature-only discipline).
* **§What surprised** — the structural discoveries (the cross-claim-type extraction cascade NEW pattern at Week 11; the empirical encoder calibration finding for date_reference at Week 11 D254; the TEST-ONLY embed_fn + retrieve_fn seam preservation across FIVE surfaces).
* **§What to do differently in Pillar G** — the carry-forward recommendations for the next pillar (Observability begins Week 31 per PILLAR-PLAN §6).
* **§The pattern's known blind spot** — cross-pillar coherence at dependency edges (the back-audit gap; the legacy-state-vs-new-defense-layer tension surfaced at Week 12 by the legacy Pass C tests requiring `draft_ready` event additions).
* **§Carry-overs into Pillar G** — what stays deferred + what new carryovers Pillar F adds.
* **§Twelve-week trace** — the per-week commit table.

**Why ship the retrospective in the Week 12 main commit (rejected: separate post-pillar reflection commit; rejected: 1-week stabilization period; rejected: defer to Pillar I).** Same rationale as ADR-0037 D176-Alt1/Alt2/Alt3.

### D269. `voice_retrieve.py` deprecation decision — preserve as documentation-only backwards-compat

The `voice_retrieve.py` heuristic shim from Pillar F Week 1 (per ADR-0038 D179's pre-Pillar-F substrate) was superseded at Week 2 by `voice_corpus.py::retrieve_voice_exemplars`. The Week 1 P3-A carry-forward (per `.planning/HANDOFF-pillar-f-week-1.md` §"Carry-overs deferred") named Week 12 as THE decision point for the deprecation.

**Decision: preserve `voice_retrieve.py` as documentation-only backwards-compat.** The module:

* **Remains in the codebase** at `orchestrator/voice_retrieve.py` (NOT removed) so operators with stale import paths see a deprecation warning + the migration shim's import-time alias points at `voice_corpus.retrieve_voice_exemplars`.
* **Carries the existing deprecation warning** per ADR-0045 §Migration/rollout Path A's Week 8 default flip — the module already emits a `DeprecationWarning` at import time.
* **Documentation-only updates** — the module docstring names ADR-0049 D269 as the Week 12 deprecation-gate decision; future operators see "deprecation accepted; backwards-compat shim preserved indefinitely" per the framework's content-additive convention.

**Why preserve (rejected: remove the deprecated module entirely; rejected: re-export from `voice_corpus.py` only; rejected: extend the deprecation runway to Pillar I OSS bring-up).**

* **Preserve as documentation-only backwards-compat** matches the per-pillar deprecation discipline — operators' import paths stay stable across pillar boundaries; removing the module would break any operator script with `from voice_retrieve import ...` imports. The cost of preservation is bounded (the module is ~50 LOC; it doesn't grow); the cost of removal is operator-script breakage with no offsetting benefit.
* **Remove the deprecated module entirely** is rejected because (a) backwards-compat is the framework's default per the Pillar D + Pillar E precedents (no removed primitives); (b) any operator who has imported the bare module name in a custom script (per the conftest's bare-import aliasing convention per ADR-0038 D182 audit category 4) would see ImportError on upgrade — a breaking change without justification; (c) the module's footprint is trivial.
* **Re-export from `voice_corpus.py` only** is rejected because the deprecated module's import-time warning IS the operator-side signal to migrate; removing the warning surface would silently hide the deprecation from operator-script readers.
* **Extend the deprecation runway to Pillar I OSS bring-up** is rejected because the deprecation runway is THIS framework's internal deprecation, not an OSS API contract — extending the runway is content-additive but unnecessary at Week 12. Pillar I MAY revisit if multi-tenant operator backbones surface a removal need.

### D270. Cross-pillar audit row extension — `.planning/REVIEW-pillar-f-surface-audit.md` §65+ — UNCHANGED verdict

Per ADR-0032 D146 + ADR-0033 D153 + ADR-0034 D158 + ADR-0035 D165 + ADR-0036 D171 + ADR-0037 D177 conventions, the Week 12 commit extends the cross-pillar surface audit with a new section walking the Week 12 deliverables' consumer surface.

**The Week 12 deliverables are verification-only + content-additive at the audit surface.** They introduce:

* **ZERO new event classes** — the Layer 5 refusal uses the EXISTING `reconcile_drift` event class with a NEW `reason` value (`"ready_without_draft_ready_event"`). The binding 200-draft eval test consumes the existing `draft_ready` + `draft_quality_scored` + `hallucination_detected` event classes from Week 10 / 8 / 6.

* **ZERO new ledger-walk patterns** — Pass C's Layer 5 query consumes `Ledger.all_events_for_person(person_id)` (existing per ADR-0010 D17). No new index access; no new consumer pattern.

* **ZERO new operator-facing surfaces** — the Pass C extension is internal to reconcile; the new `reason` value is the operator-readable signal in the existing `reconcile_drift` event's payload. The SKILL.md Phase 6 extension per D271 names the Layer 5 backstop in one operator-readable line.

* **ZERO new primitives** — the Week 6-10 + Week 11 primitives stay at their existing ship shape. The Layer 5 backstop is a CONSUMER, not a producer.

**The Week 12 audit section's verdict: UNCHANGED.** The audit document's §65+ Week 12 section confirms that the Week 12 deliverables' consumer surface is closed-set-protected against every Pillar A/B/C/D/E/F (Weeks 1-11) consumer; zero new latent-bug patterns surfaced.

**Why extend the audit even with UNCHANGED verdict (rejected: skip; rejected: combine with Week 11 section; rejected: defer to follow-up).** Same rationale as ADR-0037 D177-Alt1/Alt2/Alt3.

### D271. SKILL.md Phase 6 extension naming the Pass C heal-pass behavior

Per ADR-0047 D249's Phase 6 narrative extension precedent. The Week 12 SKILL.md Phase 6 update adds a one-line note in the Phase 6 §Don't list naming the Layer 5 backstop:

> *"**Don't bypass the Layer 4 `emit-ready` CLI when stamping `pipeline_stage: ready`.** The Pillar F Week 12 Layer 5 backstop (per ADR-0049 D262 + ADR-0038 D180) refuses Pass C heal-to-ready when no `draft_ready` event exists in the ledger; bypassed stamps surface as `reconcile_drift` findings with `reason: ready_without_draft_ready_event` + the Person stays at the prior pipeline_stage until the operator re-emits the `draft_ready` event via `python orchestrator/draft_quality.py emit-ready --apply ...`."*

**Why a one-line extension (rejected: a full Phase 6 sub-section; rejected: NO update; rejected: extend Phase 5 instead).**

* **One-line extension** matches the per-deliverable SKILL.md extension grain per ADR-0036 D169 + ADR-0046 D243 + ADR-0047 D249 — operators reading Phase 6 see the new constraint in one place; the full Layer 5 rationale lives in this ADR.
* **A full Phase 6 sub-section** is rejected because the Layer 5 backstop is operator-INVISIBLE in the happy path (operators who follow the SKILL.md Phase 6 narrative correctly never hit the refusal); the constraint is the framework's structural commitment, not a per-Phase action item.
* **NO update** is rejected because operators reading Phase 6 MAY hit the Layer 5 refusal in edge cases (manual stamp without running the CLI; scripted automation that stamps directly); the one-line note surfaces the constraint without inflating the narrative.
* **Extend Phase 5 instead** is rejected because Phase 5 is the humanizer-checklist phase; the Layer 5 backstop is a Phase 6 (send mechanics) concern.

## Alternatives considered

### D262-Alt1: Ship the Layer 5 backstop at `orchestrator/draft_quality.py`

The Week 6-10 + Week 11 primitives all live at `orchestrator/draft_quality.py`; D262-Alt1 would extend the module with a per-Person `verify_layer_5_for_person(led, person_id)` helper + invoke it from Pass C. **Rejected** because:

* The Layer 5 surface IS per-Person (heal-pass scope); the Week 6-10 primitives are per-DRAFT (per-call construction + per-emit factory + per-gate scorer). The per-call scope mismatch is structural.
* Pass C is the per-Person orchestrator; co-locating Layer 5 at the per-pass orchestrator matches the existing Pillar F per-Layer module convention (Layers 2-4 at draft_quality.py; Layer 5 at reconcile.py).
* The module's growth at draft_quality.py (~3928 LOC post-Week-10) is already at the per-module size guidance; adding the per-Person heal-pass surface inflates without proportional gain.

### D262-Alt2: NEW sibling module at `orchestrator/layer_5_guard.py`

Ship a dedicated module for Layer 5 surfaces (the predicate + the Pass C invocation glue). **Rejected** because:

* Splitting Layer 5 into a sibling creates the "look in three places" mental model the Pillar A/B/C/D/E foundational ADRs reject.
* The Layer 5 backstop is a per-Pass-C-iteration check (~50 LOC); a dedicated module is over-organization.
* The existing per-Pass-C extension precedent (ADR-0028 D119 added conversation_status: heal alongside pipeline_stage: heal in a single Pass C iteration) is the model for Week 12's Layer 5 addition.

### D262-Alt3: Per-Layer modules (`orchestrator/layers/`)

Ship a subpackage at `orchestrator/layers/` with `2_*.py`, `3_*.py`, `4_*.py`, `5_*.py` modules. **Rejected** because:

* Per-Layer semantics are LABELS on the defense-in-depth (per ADR-0038 D180), not module-split signals.
* Reorganizing the Week 6-10 + Week 11 primitives into a subpackage at Week 12 is a major refactor with no behavior gain.
* The two-module split (draft_quality.py for per-Draft surfaces; reconcile.py for per-Person Pass C extension) is operator-readable + matches the existing per-pass scoping.

### D263-Alt1: NEW finding kind `layer_5_drift`

Surface a NEW `kind` value distinct from `reconcile_drift`. **Rejected** because:

* The per-Pass-C finding shape is `reconcile_drift` per the existing convention; introducing a kind variant fragments the consumer surface.
* Pillar I per-tenant audit-tooling reads `reconcile_drift` events for operator-visible drift findings; the NEW `reason` value extends the closed-set predicate without breaking existing readers.
* Closed-set predicates over `kind` would need extension at every consumer site (per ADR-0028's category 2 rejected pattern).

### D263-Alt2: Rewrite vault to `drafted` on Layer 5 refusal

Pass C downgrades vault stage to `drafted` when Layer 5 fires. **Rejected** because:

* Pass C does NOT downgrade vault stage when conflict arises (`vault_ahead_of_ledger` surfaces drift but leaves vault unchanged). Downgrading would silently lose operator state.
* Creates a write-on-refuse pattern unseen elsewhere in reconcile; structural inconsistency.
* Operators reading the drift finding MAY want to keep the vault stamp (they're in the middle of re-emitting `draft_ready` and Pass C ran mid-flow); downgrading races operator workflows.

### D263-Alt3: NEW event class `draft_ready_missing`

Emit a NEW event class instead of using `reconcile_drift`. **Rejected** because:

* The EXISTING `reconcile_drift` event class covers Pass C drift findings; introducing a per-Layer event class fragments the consumer surface.
* Pillar I audit-tooling would need TWO ledger walks instead of one.
* ZERO new event classes at Week 12 matches the Pillar E Week 12 precedent (ADR-0037 D177 — UNCHANGED verdict).

### D263-Alt4: Silent-skip without surfacing

Layer 5 silently skips the heal without surfacing drift. **Rejected** because:

* Refuse-loud at the structural backstop is the framework convention per I7.
* Silent-skip would hide the Layer 4 bypass case from the operator-visible audit trail; operators auditing per-Person drift dashboards would NOT see the Layer 5 refusal.
* The Pillar D Week 4-5 `suppression_added` precedent (per ADR-0028 D116) is refuse-loud; Pillar F Week 12 mirrors.

### D264-Alt1: ONE ledger migration backfilling synthetic `draft_ready` events

Pre-populate `draft_ready` events for pre-Week-10 `review_approved` events. **Rejected** because:

* The per-Person backfill heuristic would synthesize `draft_ready` events without consulting the upstream substrates (DraftQualityResult + DraftFidelityResult); the Layer 4 emit-guard's structural commitment per ADR-0047 D245 is REFUSE-LOUD on `state="refused"`. Synthesizing would falsely certify drafts.
* The per-Person backfill would pollute the append-only ledger.
* Operator-side burden is bounded — operators with legacy `pipeline_stage: ready` notes re-emit via the Week 10 CLI in minutes.

### D264-Alt2: ONE vault migration clearing stale stamps

Sweep the vault + clear `pipeline_stage: ready` notes that lack `draft_ready` events. **Rejected** because:

* The ledger is SoT per I1; vault migrations heal vault to ledger.
* The Pass C extension's Layer 5 refusal IS the operator-side signal — clearing vault stamps preemptively would conflate framework upgrade with operator-deliberate state.
* Operators decide per-Person whether to re-emit OR accept the drift; the per-Person operator-action grain is the right scope.

### D264-Alt3: NEW dedicated index `_idx_draft_ready_by_person`

Add a Pillar F-specific index for `draft_ready` events. **Rejected** because:

* The per-Person `_idx_person` query is O(E_p) at sub-millisecond per call; a dedicated index would save the event-class filter but the index-rebuild cost is O(N).
* Future Pillar H (real-time + scale) may revisit if per-call cost becomes a bottleneck.

### D265-Alt1: Static YAML fixture at `tests/fixtures/pillar_f_eval/200_drafts.yml`

Externalize the 200-draft composition to a YAML file. **Rejected** because:

* The 200-draft composition is loop-generated; a YAML enumeration duplicates the loop's outputs verbatim.
* Any change to the per-register template OR per-entity firsts list would require regenerating the YAML.
* Pillar C + D + E Week 12 precedents all chose inline construction.

### D265-Alt2: Shared conftest fixture

Extract the eval-set builder to `tests/conftest.py::pillar_f_eval_set_200_drafts`. **Rejected** because:

* The eval set is binding-test-specific; externalizing inverts per-test scope without reuse benefit.
* Future Pillar F tests that need a similar set MAY extract a fixture at that time per YAGNI.

### D265-Alt3: Per-register sub-tests

Split the binding test into 5 per-register methods. **Rejected** because:

* Binding text per PILLAR-PLAN §2 Pillar F is ONE composite assertion; decomposition loses cross-register aggregation.
* Pillar D + E Week 12 precedent: one binding test per pillar's exit criterion.

### D266-Alt1: Separate `tests/test_pillar_f_exit_criterion.py` file

Ship the binding test in a dedicated file. **Rejected** per ADR-0037 D172-Alt1's single-file rationale + Pillar A/B/C/D/E precedent.

### D266-Alt2: Inline as multiple shorter tests

Decompose the binding test into ~5 shorter per-assertion methods. **Rejected** per ADR-0037 D173-Alt2 + the binding-test-as-one-scenario convention.

### D266-Alt3: Split the file at Week 12

Pre-emptively split tests/test_multi_channel_coherence.py at the LAST Pillar F week. **Rejected** because Week 12 IS the close commit; the per-week trajectory does not require split space.

### D267-Alt1: Per-week-reviewer sign-off as the Stable-flip gate

The per-week-reviewer's verdict gates Stable. **Rejected** per ADR-0037 D175-Alt2 — per-week reviews are scope-bounded.

### D267-Alt2: Full Pillar G dashboard validation as the gate

Wait for Pillar G dashboards. **Rejected** per ADR-0037 D175-Alt3 — coupling defers indefinitely.

### D267-Alt3: Holistic exit review as the gate

Treat the holistic review as gating. **Rejected** per ADR-0037 D175-Alt1 — addenda, not gating.

### D268-Alt1: Ship retrospective in separate post-pillar commit

Defer the retrospective. **Rejected** per ADR-0037 D176-Alt1 — atomic with Stable flip.

### D268-Alt2: 1-week stabilization period

Wait 7 days before retrospective. **Rejected** per ADR-0037 D176-Alt2 — no precedent.

### D268-Alt3: Defer retrospective to Pillar I

Defer indefinitely. **Rejected** per ADR-0037 D176-Alt3 — per-pillar discipline.

### D269-Alt1: Remove `voice_retrieve.py` entirely

Delete the deprecated module. **Rejected** because backwards-compat is the framework default + breaking change without justification.

### D269-Alt2: Re-export from `voice_corpus.py` only

Move re-exports + delete `voice_retrieve.py`. **Rejected** because the import-time deprecation warning IS the operator signal.

### D269-Alt3: Extend deprecation runway to Pillar I

Hold the decision longer. **Rejected** because the deprecation is internal + Pillar I revisits if multi-tenant needs surface.

### D270-Alt1: Skip the audit extension

UNCHANGED verdict; skip the section. **Rejected** per ADR-0037 D177-Alt1 — per-week audit discipline.

### D270-Alt2: Combine with Week 11 section

Combine Week 12 verdict with prior section. **Rejected** per ADR-0037 D177-Alt2 — per-week traceability.

### D270-Alt3: Defer audit extension to follow-up commit

Ship audit in follow-up. **Rejected** per ADR-0037 D177-Alt3 — atomic with main commit.

### D271-Alt1: A full Phase 6 sub-section

Inflate the SKILL.md narrative. **Rejected** because operators in happy path never hit Layer 5; the constraint is structural.

### D271-Alt2: NO SKILL.md update

Skip the extension. **Rejected** because edge-case operators MAY hit the refusal; the one-line note surfaces the constraint.

### D271-Alt3: Extend Phase 5 instead

Wrong phase — Phase 5 is humanizer; Phase 6 is send mechanics. **Rejected** because the Layer 5 backstop is a Phase 6 concern.

## Consequences

### Positive consequences

* **The Pillar F exit criterion is structurally verified.** The two binding tests compose all Pillar F primitives in the integrated scenarios matching PILLAR-PLAN §2 Pillar F's binding text. The "hallucination false-negative rate on a 200-draft eval set < 1%" + "mean voice-fidelity score per register meets baseline" claims are now passing tests.
* **The FIVE-layer hallucination-detection defense closes.** Layer 1 (Week 1 test corpus pin) + Layer 2 (Week 6 construction-time invariant + Week 8 fidelity invariant) + Layer 3 (Week 6 parser + Week 9 fuzzy extension + Week 11 corpus revision) + Layer 4 (Week 10 emit-guard) + Layer 5 (Week 12 reconcile heal-pass refusal) — the defense-in-depth contract per ADR-0038 D180 is operationally complete.
* **Pillar F flips to Stable.** Future Pillar G / H / I / J week-1 commits depend on "Pillar F Stable" per the PILLAR-PLAN §6 dependency graph; Week 12's flip unblocks the dependents.
* **The four Pillar F event classes' composition is verified.** `voice_exemplar_retrieved` + `hallucination_detected` + `draft_quality_scored` + `draft_ready` — Week 12's binding tests exercise the cross-event-class plumbing.
* **The retrospective + the audit + the handoff + this ADR + the SKILL.md update land in the same commit.** The atomicity contract per Pillar F's discipline is preserved; future Pillar G's author has the complete Pillar F close in one git revision.
* **The per-week-reviewer pattern's track record across SIX consecutive weeks (W6-W11) compounds at Week 12.** The cell-level matrix coverage discipline + behavioral-passthrough-not-signature-only discipline + cross-claim-type extraction cascade pattern (NEW at W11) all carry forward to the Week 12 per-week reviewer's checklist.

### Negative consequences

* **Test count grows by 2 (the two binding tests un-skip).** The cumulative test count: 3325 (post-Week-11-follow-up) + 2 unskipped + ~0 net new = ~3327. The two binding tests are inline; no external fixtures shipped.
* **Skip count drops by 2 (both binding tests un-skip).** From 15 skips down to 13. The remaining 13 skips are all live skips for live-network or environment-dependent tests.
* **The `tests/test_multi_channel_coherence.py` file's size grows.** Currently ~7599 lines pre-Week-12; this commit adds ~200 lines (the binding test body + Layer 5 test body). Crosses the ~7500 LOC threshold flagged by ADR-0037 D172; the split argument is now LIVE for future Pillar G / H / I / J authors.
* **TWO legacy Pass C tests required updates** (`test_heal_under_apply` + `test_dry_run_only_reports` at `tests/test_reconcile.py`). The Layer 5 backstop refuses heal-to-ready without `draft_ready` event evidence; the legacy tests' synthetic ledgers (review_approved only) needed `draft_ready` event additions to exercise the post-Week-12 heal flow.
* **No new primitives ship at Week 12.** The Pillar F close is verification-only + a per-Person heal-pass refusal extension. Operators expecting a Week 12 surface find that voice-fidelity + hallucination-detection are now fully bounded structurally; future calibration is operator-tunable per the per-register thresholds + the per-tenant Pillar I audit-tooling trajectory.
* **The retrospective + the handoff + the audit + this ADR + the SKILL.md update + the legacy test fixes all land in one commit.** The Week 12 main commit's diff is larger than typical Pillar F weeks (~7 documents touched + 2 tests un-skipped + 1 module extended + 1 ADR + 1 retrospective + 1 handoff + 1 audit extension + 1 SKILL.md update + 2 legacy test updates). Operators reviewing the commit need to read all surfaces; the per-week-reviewer protocol handles the volume per the Pillar A + B + C + D + E + F pattern.

### Risks

The asymmetric-failure-cost calculus (PILLAR-PLAN §0) carries:

* **Layer 5 false-positive — operator's legitimate `pipeline_stage: ready` stamp without `draft_ready` event (P2):** real-world legacy state (pre-Week-10 Persons with `pipeline_stage: ready` notes from before the Layer 4 CLI shipped). **Bounded by** the §Existing-operator seed migration narrative (operators re-emit `draft_ready` events via the Week 10 CLI) + the operator-side action's bounded cost (~minutes per Person; <100 Persons in Yang's vault).
* **Layer 5 false-negative — a draft with `draft_ready` event but downstream-corrupted quality (P3):** the Layer 5 backstop verifies `draft_ready` EVENT PRESENCE, not the event's payload semantics. A future operator who manually appends synthetic `draft_ready` events to the ledger (bypassing the Layer 4 emit-guard factory) would defeat Layer 5. **Bounded by** the `_emitted_by: "draft_quality"` audit marker per ADR-0010 D17 + ADR-0043 D216 (Pillar I audit-tooling can grep for `_emitted_by != "draft_quality"` `draft_ready` events to surface non-factory emissions) + the framework's no-direct-ledger-mutation convention (operators interact via the CLI per the operator-readable narrative).
* **Binding 200-draft eval test passes Week 12 but regresses on a future Pillar G / H / I / J week's primitive extension (P2):** a downstream pillar's commit silently broadens the input space + breaks the Layer 3 parser. **Bounded by** the cross-pillar surface audit's per-week-extension discipline + the binding tests' continuous CI runs.
* **The "Pillar F Stable" claim's future re-validation (P3):** a future Pillar I OSS bring-up week's commit extends the Pillar F primitives (e.g., the legacy `voice_retrieve.py` removal per D269's deferred decision; per-tenant fuzzy_threshold extension per ADR-0048 D254's trajectory). **Bounded by** the per-pillar stable-flip checklist's re-runnability (the binding tests stay in CI; any regression surfaces at the per-week reviewer of the modifying commit).

The framework's existing safeguards bound the regression failure modes by design.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The Layer 5 backstop CONSUMES the ledger (queries `_idx_person` for `draft_ready` event presence); no new SoT. The Pass C refusal surfaces `reconcile_drift` events to the ledger via the existing emit path.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The Layer 5 check is upstream of the dispatch (Pass C runs before send); no changes to send-path semantics.
* **I3 — Atomic per-Person enrollment.** Preserved. The Layer 5 check is per-Person heal-pass; no enrollment changes.
* **I4 — Per-channel state isolation.** Preserved. The Layer 5 check is channel-agnostic at the per-Person grain; the per-event channel field is carried verbatim through the `reconcile_drift` event.
* **I5 — Migration framework discipline.** Preserved. Week 12 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The Layer 5 refusal emits `reconcile_drift` per the existing event shape (channel inherited from the Person's most-recent channel-bearing event per the existing reconcile pattern).
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. Layer 5 IS the refuse-loud at the per-Person heal-pass surface; the FIVE-layer defense closes the refuse-loud chain.
* **I8 — Privacy-respecting.** Preserved. The Layer 5 refusal's `reconcile_drift` event carries ONLY per-Person fields (`person_id` + `note_path` + `vault_stage` + `ledger_stage` + `reason`); NO draft body content, NO dossier content, NO embedding content.

## Downstream pillar impact

* **Pillar F (Voice corpus + draft quality) — Week 12 (this commit).** Pillar F flips to Stable at Week 12 close. The FIVE-layer hallucination-detection defense is operationally complete. The voice-fidelity per-register threshold loader + the per-claim parser + the fuzzy-match extension + the Layer 4 emit-guard + the Layer 5 reconcile backstop compose end-to-end. Future Pillar F maintenance ships under the Pillar I OSS bring-up scope (per-tenant fuzzy_threshold + per-tenant bound tables).

* **Pillar G (Observability, begins Week 31).** Pillar G dashboards consume the four Pillar F event classes directly (`voice_exemplar_retrieved` + `hallucination_detected` + `draft_quality_scored` + `draft_ready`) + the NEW `reconcile_drift` reason value (`"ready_without_draft_ready_event"`). Pillar G's per-Person drift dashboard MAY filter by reason for operator-visible Layer 5 audit. The hallucination FN_rate dashboard per Pillar G's exit-criterion's cost-per-quality-prospect bullet is unblocked by Pillar F's stable surface.

* **Pillar H (Real-time + scale, begins Week 37).** Pass C's Layer 5 query is O(E_p) per Person; Pillar H MAY optimize the per-Person index with a dedicated `_idx_draft_ready_by_person` if per-call cost surfaces as a bottleneck (per D264-Alt3). Future Pillar H optimizations are content-additive (the predicate's contract stays).

* **Pillar I (Multi-tenant + OSS hardening, begins Week 43).** Pillar I extensions per the deferred-items list: per-tenant `fuzzy_threshold` extension per ADR-0048 D254's trajectory + per-tenant `voice_thresholds.yml` overrides per ADR-0041 D204 + per-tenant audit-tooling for Layer 5 refusals (per-tenant operator-override-rate dashboards). The `voice_retrieve.py` deprecation decision per D269 stays at documentation-only backwards-compat through Pillar I.

* **Pillar J (Compliance + audit, begins Week 49).** GDPR-purge transaction extends to purge the per-Person `draft_ready` event sequence when the Person requests forget — the event class carries `person_id` + `draft_hash` (sha256-hashed per I8); the GDPR-purge implementation walks the per-Person index + appends the per-Person forget tombstones. The Layer 5 backstop's refusal trail (`reconcile_drift` events) ALSO purges per the same per-Person walk. The binding test does NOT exercise GDPR-purge; Pillar J's commit extends the cross-pillar audit with the per-Person purge path's verdict for the Pillar F event classes.

## Migration / rollout

**Week 12 ships ZERO new migrations.** Pending count stays at 19. Operators upgrading from Week 11 to Week 12:

1. **Operator updates the framework** to Week 12's commit (the standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since the pending migrations are already applied at prior weeks' ship times.
3. **Operator runs `python -m pytest tests/test_multi_channel_coherence.py::TestPillarFExitCriterion -v` + `... TestHallucinationDetection::test_reconcile_pass_c_refuses_advance_to_ready_on_uncited -v`** to verify the binding tests pass locally. Optional but recommended for operators wanting end-to-end Pillar F verification.
4. **Operator's first Pass C run post-upgrade** MAY surface Layer 5 drift findings for Persons with pre-Week-10 `pipeline_stage: ready` stamps lacking `draft_ready` event evidence. The drift findings are operator-readable signals; operators re-emit `draft_ready` events via `python orchestrator/draft_quality.py emit-ready --person-id <pid> --apply ...` per the Week 10 CLI (per ADR-0047 D248).

The operator-side action is bounded (~minutes per Person; small population in Yang's vault).

## Existing-operator seed

**Pillar F Week 12 ships no operator-side state migrations.** The Layer 5 backstop is verification-only at the Pass C extension; no operator data migration; no operator CLI changes (the new `--apply` flag values already exist).

**Operator action recommended at Week 12 (NOT required):**

* **Re-emit `draft_ready` events for legacy `pipeline_stage: ready` Persons.** Operators with Person notes stamped `pipeline_stage: ready` from BEFORE Week 10 (when the Layer 4 emit-guard CLI shipped) see Layer 5 drift findings on the first Pass C run post-upgrade. The remediation is per-Person + bounded:
  1. Operator runs `python orchestrator/reconcile.py --apply` → sees `reconcile_drift` findings with `reason: ready_without_draft_ready_event`.
  2. For each per-Person drift, operator inspects the Touch note's `draft_hash` + the latest `draft_complete` event's payload.
  3. Operator re-emits `draft_ready` via the Week 10 CLI (`python orchestrator/draft_quality.py emit-ready --person-id <pid> --draft-file <touch.md> --register <r> --channel <c> --apply ...`).
  4. The next Pass C run finds the `draft_ready` event + Layer 5 passes.

The §Existing-operator seed convention from prior Pillar F weeks does NOT apply at Week 12 — there is no operator data migration. The Layer 5 backstop is content-additive at the structural commitment.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation (the FIVE-layer hallucination-detection defense per D180 + the four event classes per D182 + the exit-criterion vehicle scope per D183 + the asymmetric-failure-cost calculus per D184).
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive.
- **ADR-0040 (D192-D198)** — Pillar F Week 3 per-register adapters.
- **ADR-0041 (D199-D205)** — Pillar F Week 4 per-register threshold loader.
- **ADR-0042 (D206-D211)** — Pillar F Week 5 operator-facing thresholds CLI.
- **ADR-0043 (D212-D219)** — Pillar F Week 6 hallucination-detection Layer 2-3 primitive.
- **ADR-0044 (D220-D227)** — Pillar F Week 7 per-claim-type test corpora + measurement primitive.
- **ADR-0045 (D228-D235)** — Pillar F Week 8 per-draft voice-fidelity scoring primitive + `draft_quality_scored` event class.
- **ADR-0046 (D236-D243)** — Pillar F Week 9 per-claim fuzzy-match citation extension.
- **ADR-0047 (D244-D251)** — Pillar F Week 10 Layer 4 post-engine guard + `draft_ready` event class + per-dimension operator-override path.
- **ADR-0048 (D252-D261)** — Pillar F Week 11 Layer 3 parser corpus revision + per-claim-type bound tightening.
- **ADR-0037 (D172-D177)** — Pillar E Week 12 exit-criterion close + Stable flip precedent (the binding-test-as-gate + per-pillar stable-flip checklist + per-pillar retrospective + cross-pillar audit UNCHANGED verdict).
- **ADR-0031 (D136 + D141)** — Pillar D Week 12 (the binding-test-as-gate + per-pillar stable-flip checklist + per-pillar retrospective discipline foundation).
- **ADR-0014 (D33 + D37)** — Pillar C foundation (channel-on-every-event invariant + the cross-pillar coherence test vehicle's single-file rationale).
- **ADR-0025 (D101)** — Pillar D foundation (the exit-criterion vehicle's single-file rationale extended).
- **ADR-0011 + ADR-0028 (D119)** — reconcile Pass C foundation + the `conversation_status:` heal extension precedent (Layer 5 follows the same per-Pass-C extension pattern).
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the load-bearing cross-pillar audit; Week 12 extends with §65+ (UNCHANGED verdict).
- **`.planning/RETRO-pillar-f.md`** — this Week 12 commit's Pillar F retrospective.
- **`.planning/RETRO-pillar-e.md`** — the Pillar E Week 12 retrospective; informs Pillar F's per-pillar carry-forward.
- **`.planning/HANDOFF-pillar-f-week-12.md`** — this week's handoff document.
- **`.planning/HANDOFF-pillar-g-week-1.md`** — the breadcrumb for Pillar G (Observability begins Week 31).
- **`docs/PILLAR-PLAN.md` §2 Pillar F + §6 Pillar F row** — the binding exit-criterion text + the per-week trajectory ticker that flips to **Stable** at this commit.
- **`docs/SOURCES-OF-TRUTH.md`** — Pillar F's stable surface (the four event classes + the FIVE-layer defense's per-Layer write sites).
