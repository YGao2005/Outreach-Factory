# ADR-0047: Pillar F Week 10 — Layer 4 post-engine guard + `draft_ready` event class + per-dimension operator-override path

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** F (Voice corpus + draft quality — Week 10 Layer 4 post-engine guard)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation; Week 2 (ADR-0039 D185-D191) shipped the embedding-retrieval primitive; Week 3 (ADR-0040 D192-D198) shipped the per-register adapters; Week 4 (ADR-0041 D199-D205) shipped the per-register threshold loader; Week 5 (ADR-0042 D206-D211) shipped the operator-facing thresholds CLI; Week 6 (ADR-0043 D212-D219) shipped the hallucination-detection Layer 2-3 primitive; Week 7 (ADR-0044 D220-D227) shipped the per-claim-type test corpora + measurement primitive; Week 8 (ADR-0045 D228-D235) shipped the per-draft voice-fidelity scoring primitive + the `draft_quality_scored` event class + the `voice.use_embedding_primitive` default flip; **Week 9** (ADR-0046 D236-D243) shipped the per-claim fuzzy-match citation extension at the Layer 3 parser. Week 9 closed at `a6b66a9` + follow-up `c6b3d58` (0 P1 + 2 P2 + 3 P3 addressed); 3222 tests passing post-follow-up.

**Pillar F Week 10 ships the Layer 4 post-engine guard** per ADR-0038 D180's FIVE-layer hallucination-detection defense. Layer 4 is the LAST WRITE in the per-draft pipeline — the `draft_ready` event emission. The guard refuses-loud when EITHER of the two per-draft Layer 2 gates refused: `DraftQualityResult.state == "refused"` (Week 6 hallucination-detection per ADR-0043 D213) OR `DraftFidelityResult.state == "refused"` (Week 8 voice-fidelity per ADR-0045 D229). The guard is the **SYMMETRIC two-dimensional verdict** — hallucination-detection × voice-fidelity — at the per-draft pipeline's emit boundary.

The Week 1 stub at `tests/test_multi_channel_coherence.py::TestHallucinationDetection::test_draft_ready_event_refuses_emit_on_uncited` has been SKIPPED since Week 1 with "Pillar F Week 10 delivers — draft_ready event emit guard per ADR-0038 D180 Layer 4." Week 10 un-skips this row + lands the binding behavioral commitment. The remaining `test_reconcile_pass_c_refuses_advance_to_ready_on_uncited` row stays SKIPPED through Week 11 + un-skips at Week 12 (the Layer 5 reconcile heal-pass refusal).

The eight concerns this ADR resolves:

1. **Module placement** for the new Layer 4 emit-guard surface — extend `orchestrator/draft_quality.py` (per the Week 6 D212 + Week 7 D220 + Week 8 D228 co-location precedent) OR ship a new sibling at `orchestrator/draft_ready_guard.py`. **D244** pins.

2. **`build_draft_ready_payload` factory shape + Layer 4 emit-guard refuse-loud semantics** — the factory consumes BOTH `DraftQualityResult` (Week 6 substrate) AND `DraftFidelityResult` (Week 8 substrate); refuses-loud when EITHER state is `"refused"` AND the per-dimension override is absent; emits the `draft_ready` event when both pass (or the per-dimension overrides bypass). **D245** pins.

3. **`draft_ready` event class — NEW + emit-only-on-both-pass posture** per ADR-0038 D180's Layer 4 surface. The class joins the three existing Pillar F event classes (`voice_exemplar_retrieved` Week 2 + `hallucination_detected` Week 6 + `draft_quality_scored` Week 8). The posture DIFFERS from the three existing classes:

   | Event | Posture | Rationale |
   |---|---|---|
   | `voice_exemplar_retrieved` (Week 2) | Emit-always (when `--apply`) | Pillar G observability needs accept-case retrieval events for per-query coverage rendering. |
   | `hallucination_detected` (Week 6) | Emit-only-on-uncited | The event SIGNALS a problem (uncited claim caught); accept-case is the silent default per ADR-0043 D219. |
   | `draft_quality_scored` (Week 8) | Emit-always (when `--apply`) | Pillar G observability needs accept-case events for per-register score distribution rendering. |
   | `draft_ready` (Week 10 — NEW) | Emit-only-on-both-gates-pass | The event SIGNALS dispatch-eligibility (both per-draft gates passed); per ADR-0038 D180 Layer 4's "refuses-loud when uncited_claims is non-empty OR meets_threshold=False" — the refuse-case is loud, the accept-case is the structured emit. |

   **D246** pins.

4. **Per-dimension operator-override path** — `hallucination_check_override: bool = False` + `voice_fidelity_check_override: bool = False` kwargs (with optional `*_override_reason: str | None`). When True, the guard bypasses the per-dimension refuse-loud + stamps the override on the emitted `draft_ready` event. The overrides MIRROR the SKILL.md Phase 5 operator-override surface per ADR-0043 D217. **D247** pins.

5. **CLI `emit-ready` subcommand** — operator-facing composite per-draft entry point. Mirrors the Week 6 `parse` subcommand's shape per ADR-0043 D212 + the Week 7 `measure` subcommand's shape per ADR-0044 D224 + the Week 8 `score` subcommand's shape per ADR-0045 D234. Runs BOTH per-draft gates (Layer 3 parser + Layer 2 fidelity scorer) + invokes the Layer 4 emit-guard per D245 + emits the per-Layer events per the existing cardinality (D219 + D231) AND the NEW `draft_ready` per D246. **D248** pins.

6. **SKILL.md Phase 6 frontmatter extension** — the Phase 6 Touch note frontmatter gets `layer_4_check: passed | failed | skipped` + `voice_fidelity_check_override: bool` (the missing per-dimension override symmetric with the existing `hallucination_check_override` per ADR-0043 D217) + `voice_fidelity_check_override_reason: str | null`. Operators stamping the Touch note's frontmatter surface the Layer 4 verdict + the per-dimension overrides for the Pillar I per-tenant audit-tooling. **D249** pins.

7. **TEST-ONLY `embed_fn` + `retrieve_fn` seam preservation discipline EXTENDS to the Week 10 Layer 4 emit-guard surface.** The seam is LIVE at FIVE surfaces post-Week-9 (`parse_draft_for_claims` + `score_draft` + `measure_per_claim_type_false_positive_rate` + `compute_draft_fidelity_score` + the fuzzy-fallback inside `parse_draft_for_claims`). Week 10's `build_draft_ready_payload` is a STRUCTURAL COMPOSITION (consumes already-constructed `DraftQualityResult` + `DraftFidelityResult`); the seam is NOT in the factory's signature — the seam stays at the per-Layer surfaces upstream of the factory. The CLI's `emit-ready` subcommand passes through the existing seam discipline at score_draft + compute_draft_fidelity_score (which already carry the seam). **D250** pins.

8. **Migration / ledger indexing — ZERO new migrations at Week 10.** The `draft_ready` event class carries `person_id` → indexed via the existing `_idx_person` per ADR-0010 D17 + ADR-0038 D182's category 1. Per-Person lookup for Week 12 reconcile Pass C's downstream consumer is satisfied by `_idx_person` + per-type filtering. **D251** pins.

Risks this ADR mitigates by design: **R023 (Hallucination-detection false-negative)** continues mitigated — Week 10 ships Layer 4 of the FIVE-layer defense per ADR-0038 D180; the structural backstop catches drafts that bypassed Layers 1-3. **R024 (voice-corpus drift)** continues mitigated — the Layer 4 guard consults `DraftFidelityResult.state` which carries the per-register threshold verdict per Week 8's substrate. **R025 (embedding-cost runaway)** continues mitigated — Week 10's guard is a STRUCTURAL COMPOSITION (no new encoder calls); per-call cost is dominated by the upstream Layer 3 parser + Layer 2 fidelity scorer that already ran. **R026 (operator-corpus split)** continues mitigated — orthogonal. **R027 (per-claim false-positive rate)** continues mitigated — the per-dimension `hallucination_check_override` operator-override path bypasses per-Week 6 D217 + the Week 6 fuzzy-match parser path. **R028 (per-register threshold mis-calibration)** continues mitigated — the per-dimension `voice_fidelity_check_override` operator-override path bypasses per-Week 8 D229 + the Pillar I per-tenant audit-tooling trajectory. **R029 (per-claim fuzzy-match false-positive)** continues mitigated — the Layer 4 emit-guard is the structural backstop at the emit boundary; fuzzy-match false-positives at the parser surface are caught by Layer 4 BEFORE the `draft_ready` event lands.

**One new risk surfaces in this Week 10 commit + named in `docs/RISK-REGISTER.md`:**

- **R030 (Layer 4 emit-guard bypass via direct payload construction)** — a future contributor (or operator script) that constructs the `draft_ready` event payload directly (bypassing the `build_draft_ready_payload` factory) would emit a `draft_ready` event without consulting the per-Layer verdicts. **Mitigated by** (a) the factory's refuse-loud at the construction boundary per D245 — the factory IS the only sanctioned construction surface; (b) the per-event `_emitted_by: "draft_quality"` marker per ADR-0010 D17 + ADR-0043 D216 — Pillar I audit-tooling can grep for `_emitted_by != "draft_quality"` `draft_ready` events to surface non-factory emissions; (c) the SKILL.md Phase 6 narrative per D249 names the factory as the LOAD-BEARING surface (operators reading the skill see the factory invocation, not a direct payload construction); (d) the Week 12 Layer 5 reconcile Pass C will WALK the per-Person `draft_ready` events + the linked `hallucination_detected` + `draft_quality_scored` events as the final structural backstop — a Layer 4 bypass that emitted a `draft_ready` WITHOUT a passing `draft_quality_scored` would surface at the Pass C heal as a `pipeline_stage: ready` advancement refusal. **Bounded by** the Pillar I per-tenant audit-tooling extension (operator-deferred).

## Decision

### D244. Module placement — extend `orchestrator/draft_quality.py` (NOT a new sibling module)

The Week 10 Layer 4 emit-guard primitive lives at `orchestrator/draft_quality.py` (the Week 6 + Week 7 + Week 8 + Week 9 primitives' existing module). The new public surfaces:

* **`build_draft_ready_payload`** factory function (Layer 4 emit-guard per D245 + D246).
* **`Layer4GuardRefusal`** typed exception (raised by the factory when the per-dimension refuse-loud fires; consumers catch this specific class to distinguish the Layer 4 refusal from generic `ValueError` raised by the per-dimension factories' invariants). **Subclasses `ValueError`** so existing exception-handling that catches `ValueError` (CLI try/except blocks; downstream callers) continues to work without code changes.
* **`_cmd_emit_ready`** CLI handler + main() extension (per D248).

The module's growth: ~2966 LOC (post-Week-9-follow-up) → ~3450-3500 LOC (post-Week-10; +~480-550 LOC for the Week 10 factory + the typed exception + CLI handler + main() extension + docstrings).

**Why extend the existing module (rejected: NEW sibling module at `orchestrator/draft_ready_guard.py`; rejected: subpackage at `orchestrator/draft_quality/`; rejected: per-Layer modules; rejected: extend `orchestrator/reconcile.py`).**

* **Extend the existing module** matches the per-primitive flat-module convention per ADR-0036 D166 + ADR-0043 D212 + ADR-0044 D220 + ADR-0045 D228 + ADR-0046 D236. The Layer 4 emit-guard IS the SYMMETRIC two-dimensional verdict surface — it consumes BOTH `DraftQualityResult` (Week 6) AND `DraftFidelityResult` (Week 8); BOTH dataclasses live at this module; co-locating the guard preserves the per-primitive scoping + the operator-readable import shape (`from orchestrator.draft_quality import build_draft_ready_payload, Layer4GuardRefusal`). The Week 10 ADR's structural commitment: "the per-draft gate is the SYMMETRIC two-dimensional verdict" (per the Week 9 handoff §"Phase 2 Recommended decisions" + ADR-0045 §Downstream pillar impact); the guard lives where the gate lives.
* **NEW sibling module at `orchestrator/draft_ready_guard.py`** is rejected because the Layer 4 emit-guard is the COMPOSITE consumer of two co-located Layer 2 primitives — splitting it across a sibling module creates the "look in three places" mental model per ADR-0045 D228-Alt1 + ADR-0046 D236-Alt1. Operators understanding "the per-draft gate" SHOULD find all four surfaces at one import path (Layer 2 hallucination + Layer 2 fidelity + Layer 3 parser + Layer 4 emit-guard).
* **Subpackage at `orchestrator/draft_quality/`** is rejected per the same rationale as ADR-0043 D212-Alt2 + ADR-0044 D220-Alt2 + ADR-0045 D228-Alt2 + ADR-0046 D236-Alt2 — over-organization for the Week 10 commit's ~500 LOC scope; one module is sufficient + future Pillar F weeks' extensions land at the existing module.
* **Per-Layer modules** (e.g., `orchestrator/draft_quality/layer4.py`) is rejected per ADR-0045 D228-Alt4 — per-Layer semantics are LABELS on the gate's defense-in-depth (per ADR-0038 D180), not module-split signals. The FIVE-layer defense ships across Weeks 6 + 8 + 9 + 10 + 12 at the same module's increasing surface area.
* **Extend `orchestrator/reconcile.py`** is rejected because reconcile is the per-Person heal-pass orchestrator (Pillar B + C substrate) — the Layer 4 emit-guard is the per-DRAFT emit-side guard, NOT the per-Person reconcile-side heal. Week 12's Layer 5 reconcile Pass C extension lives at `orchestrator/reconcile.py`; Week 10's Layer 4 emit-guard lives at the draft-quality module. The per-Pillar-F per-Layer module convention: Layers 2-4 at `orchestrator/draft_quality.py`; Layer 5 at `orchestrator/reconcile.py` per the per-pass orchestrator's existing surface.

### D245. `build_draft_ready_payload` factory shape + Layer 4 emit-guard refuse-loud semantics

```python
def build_draft_ready_payload(
    *,
    person_id: str | None,
    quality_result: DraftQualityResult,
    fidelity_result: DraftFidelityResult,
    channel: str,
    register: str,
    hallucination_check_override: bool = False,
    hallucination_check_override_reason: str | None = None,
    voice_fidelity_check_override: bool = False,
    voice_fidelity_check_override_reason: str | None = None,
) -> dict: ...
```

**Per-call dispatch:**

1. Validate closed-enums (`channel` in `CHANNELS`; `register` in `REGISTERS`) — raises `ValueError` (Layer 4 caller bug).
2. Validate mismatch with both results (`channel != quality_result.channel`; `register != quality_result.register`; same for `fidelity_result`) — raises `ValueError` mirrors Week 6 follow-up P2-2 per ADR-0043 D216 + Week 8 P2-2 per ADR-0045 D231.
3. Validate the override bool kwargs (bool catch on the four kwargs per ADR-0041 D201; reason MUST be a non-empty stripped string when the matching override is True).
4. Validate the cross-dimension consistency: the `quality_result.draft_hash` MUST equal the `fidelity_result.draft_hash` (both results MUST refer to the same draft body — the asymmetric-failure-cost calculus per ADR-0038 D184 demands BOTH gates fire on the SAME draft). Mismatch is a caller bug that would silently emit a `draft_ready` claiming two-dimension verdict on two different drafts.
5. Per-dimension refuse-loud:
   - IF `quality_result.state == "refused"` AND NOT `hallucination_check_override`: raise `Layer4GuardRefusal` with the per-claim trace.
   - IF `fidelity_result.state == "refused"` AND NOT `voice_fidelity_check_override`: raise `Layer4GuardRefusal` with the per-register score + threshold.
   - IF BOTH refused AND BOTH overrides absent: raise `Layer4GuardRefusal` naming BOTH dimensions (the refusal message names which dimension(s) refused + the per-dimension diagnostic; operators see both refusals in one error).
6. Construct the `draft_ready` payload per D246 + return.

**The `Layer4GuardRefusal` exception** carries operator-readable structured data:

```python
class Layer4GuardRefusal(ValueError):
    """Raised when build_draft_ready_payload refuses per Layer 4 per ADR-0038 D180."""

    def __init__(
        self,
        message: str,
        *,
        refused_dimensions: tuple[str, ...],     # subset of ("hallucination", "fidelity")
        quality_result: DraftQualityResult,
        fidelity_result: DraftFidelityResult,
    ) -> None:
        super().__init__(message)
        self.refused_dimensions = refused_dimensions
        self.quality_result = quality_result
        self.fidelity_result = fidelity_result
```

Operators catching the exception have BOTH per-dimension result objects available for diagnostic surfacing. The CLI's `_cmd_emit_ready` handler uses this to render the per-dimension trace in the JSON output's `refused_dimensions` field.

**Why a single composite factory consuming BOTH results (rejected: separate per-dimension factories; rejected: factory returns Optional[dict]; rejected: factory takes the per-Layer override as a single tuple kwarg; rejected: factory takes a `cfg` dict carrying overrides).**

* **Single composite factory** matches the SYMMETRIC two-dimensional verdict structural commitment per ADR-0038 D180 Layer 4 — Layer 4 is ONE guard surface, not two; consolidating to one factory keeps the per-call refuse-loud LOCAL to one decision site. Operators inspecting the per-call site see ONE factory invocation that consults BOTH dimensions; the per-dimension overrides + reasons are kwargs at the same surface.
* **Separate per-dimension factories** (`build_draft_ready_payload_hallucination_check(...)` + `build_draft_ready_payload_fidelity_check(...)` + a top-level combinator) is rejected because the per-dimension separation moves the SYMMETRIC two-dimensional verdict semantics OUT of the factory + INTO the caller; callers risk emitting two separate `draft_ready` events (one per dimension) when the structural commitment is ONE event per draft per the channel-on-every-event invariant per ADR-0014 D33.
* **Factory returns Optional[dict]** (returns `None` instead of raising on refused) is rejected per the framework's I7 invariant + the Pillar D Week 4-5 `suppression_added` precedent per ADR-0028 D116 — refuse-loud at the construction site is the framework convention; silent-None returns hide caller bugs (operators forgetting to check the return). Raising preserves the structural commitment that the accept-case IS the structured emit + the refuse-case IS the loud failure.
* **Factory takes the per-Layer override as a single tuple kwarg** (`override: tuple[bool, bool]` for hallucination + fidelity) is rejected per operator-readability — positional tuples are operator-hostile + lose the per-dimension naming. The four discrete kwargs (`hallucination_check_override` + `hallucination_check_override_reason` + `voice_fidelity_check_override` + `voice_fidelity_check_override_reason`) MIRROR the SKILL.md Phase 6 frontmatter fields per D249; the per-dimension symmetry is the operator-reading mental model.
* **Factory takes a `cfg` dict carrying overrides** (`cfg: dict` with `hallucination_check_override` key etc.) is rejected because it inverts the discipline of explicit kwargs into a dict-of-strings — the bool catch per ADR-0041 D201 is harder to apply on dict values; the type checker can't surface missing required-when-override-true reasons; the per-dimension naming is hidden behind dict keys.

### D246. `draft_ready` event class — NEW + emit-only-on-both-pass posture

The Week 10 `draft_ready` event class is the FOURTH Pillar F event class per ADR-0038 D182. Event shape:

```text
type:                                      draft_ready
person_id                                  (the prospect the draft targets; None for ad-hoc validation)
draft_hash                                 (sha256:<hex> of the draft body — NOT the raw draft per I8)
register                                   (closed-enum per ADR-0038 D178)
channel                                    (closed-enum per ADR-0014 D33)
hallucination_check                        ("passed" | "passed_via_override")
hallucination_check_override_reason        (str | None — non-empty when hallucination_check == "passed_via_override")
voice_fidelity_check                       ("passed" | "passed_via_override" | "skipped")
voice_fidelity_check_override_reason       (str | None — non-empty when voice_fidelity_check == "passed_via_override")
voice_fidelity_score                       (float in [0.0, 1.0] | None — None when voice_fidelity_check == "skipped")
voice_fidelity_threshold                   (float in [0.0, 1.0] | None — None when voice_fidelity_check == "skipped")
parsed_claims_count                        (int — count of all extracted claims for operator audit)
uncited_claims_count                       (int — count of uncited claims at parse time; 0 when not overridden; >0 only when hallucination_check == "passed_via_override")
_emitted_by                                ("draft_quality" per ADR-0010 D17 + ADR-0043 D216)
```

**Emit-only-on-both-pass posture** — the factory emits when BOTH per-dimension verdicts pass (either natively `state="ready"` OR via the per-dimension override). The factory refuses construction (raises `Layer4GuardRefusal`) when EITHER dimension is `state="refused"` AND the override is absent.

**Compared with the three existing Pillar F event classes:**

| Event | Week | Posture | Emit cardinality |
|---|---|---|---|
| `voice_exemplar_retrieved` (Week 2) | Emit-always (when `--apply`) | One event per `retrieve_voice_exemplars` call. |
| `hallucination_detected` (Week 6) | Emit-only-on-uncited | One event per draft with `uncited_claims` non-empty. |
| `draft_quality_scored` (Week 8) | Emit-always (when `--apply`) | One event per `compute_draft_fidelity_score` call. |
| `draft_ready` (Week 10 — NEW) | Emit-only-on-both-pass | One event per draft when BOTH Layer 2 gates passed (natively OR via override). |

**The `voice_fidelity_check == "skipped"` path** — operators with `voice.use_embedding_primitive: false` (legacy path per ADR-0045 §Migration/rollout Path B) do NOT run the Week 8 fidelity-scoring primitive; the SKILL.md Phase 5 voice-fidelity gate stamps `voice_fidelity_check: skipped` on the Touch note per the existing surface. The CLI's `emit-ready` subcommand per D248 accepts `--skip-fidelity-check` to surface this path operator-readably; the factory is invoked with `fidelity_result=None` AND the `voice_fidelity_check_override` is implicit (the per-dimension dispatch treats `fidelity_result=None` as "no fidelity check ran; voice_fidelity_check=skipped"). The emitted event's `voice_fidelity_score` + `voice_fidelity_threshold` fields are `None` in this path.

**Privacy-respecting per I8 + ADR-0038 §Compliance with invariants:**

* **Raw draft body MUST NOT appear in the payload.** The draft is sha256-hashed at the upstream result construction sites per ADR-0043 D213 + ADR-0045 D229.
* **Per-claim trace MUST NOT appear in the payload.** Only counts (`parsed_claims_count` + `uncited_claims_count`) surface — operators inspect the per-claim trace via the upstream `hallucination_detected` event (emitted at parse-time per ADR-0043 D219 — the per-claim diagnostic IS that event's load-bearing payload; the Layer 4 emit-guard's event is the dispatch-eligibility signal, NOT the per-claim diagnostic surface). The per-dimension override stamps the operator's deliberate decision; the per-claim trace stays at the upstream event.
* **Per-exemplar bodies MUST NOT appear in the payload.** Only `voice_fidelity_score` + `voice_fidelity_threshold` surface — operators inspect the per-exemplar IDs via the upstream `draft_quality_scored` event per ADR-0045 D231.
* **Override reasons ARE in the payload** — operators stamping `*_override_reason` deliberately exposes the rationale for the Pillar I per-tenant audit-tooling. Reasons are caller-controlled prose (operator-readable; not auto-extracted from per-claim trace).

**Refuse-loud surfaces at the factory boundary** (mirror Week 6 D216 + Week 8 D231 + Week 7 D223 disciplines):

* `channel` not in `CHANNELS` raises `ValueError`.
* `register` not in `REGISTERS` raises `ValueError`.
* `channel != quality_result.channel` OR `register != quality_result.register` raises `ValueError` (mirrors ADR-0043 D216 + ADR-0045 D231).
* `channel != fidelity_result.channel` OR `register != fidelity_result.register` raises `ValueError` (only when `fidelity_result is not None`).
* `quality_result.draft_hash != fidelity_result.draft_hash` raises `ValueError` (cross-dimension consistency — both results MUST refer to the same draft body; mismatch is a caller bug).
* Per-dimension override is True AND reason is None / empty / whitespace-only raises `ValueError` (operators stamping an override MUST surface the rationale per ADR-0043 D217's discipline).
* Override bool kwargs that are `int` (bool-is-an-int per ADR-0041 D201) raise `ValueError`.

**Why a NEW event class with emit-only-on-both-pass posture (rejected: extend `draft_quality_scored` with a new field; rejected: emit-always for `draft_ready`; rejected: emit-on-state-change; rejected: emit-when-either-passes).**

* **NEW event class with emit-only-on-both-pass** matches the FOURTH-event-class pattern per ADR-0038 D182's category 8 audit + the per-Layer ship trajectory per ADR-0038 D180 — Layer 4 is the post-engine guard; the guard's verdict IS the new event class's emit-trigger. The posture's asymmetric-failure-cost calculus: false-negative (a `draft_ready` event lands when the gate should refuse) is BRAND-RISK PATH (downstream consumers act on a stale-state draft); false-positive (the gate refuses a true-ready draft) is OPERATOR-FRICTION PATH (operator stamps a one-time override + re-emits). The framework defaults to false-positive per ADR-0038 D184.
* **Extend `draft_quality_scored` with a new field** (e.g., add `layer_4_check: "passed" | "refused"` to the existing Week 8 event class) is rejected because the existing event class's emit-always posture per ADR-0045 D231 doesn't match the Layer 4 emit-only-on-pass posture; extending the field would force one of TWO unacceptable choices: (a) keep emit-always + the `layer_4_check: refused` value lands on the ledger → downstream consumers (Week 12 Pass C) would need to filter by the field to distinguish dispatch-eligible from refused events (vs filtering by event class — operator-cleaner); (b) flip the emit posture to emit-only-on-both-pass → breaks the Pillar G observability use case the Week 8 ADR D231 explicitly addresses. The per-event-class separation preserves the per-class posture's structural commitment.
* **Emit-always for `draft_ready`** is rejected because the event class SIGNALS dispatch-eligibility per ADR-0038 D180 Layer 4; the refused case is NOT the `draft_ready` event (that's the `hallucination_detected` + `draft_quality_scored` events' diagnostic payload). Emit-always would create a per-event field `draft_ready_state: ("ready" | "refused")` that operators filter on — same problem as extending `draft_quality_scored`.
* **Emit-on-state-change** (e.g., emit when the per-draft's gate verdict changes from refused → ready across re-scoring) is rejected per ADR-0045 D231-Alt2 — per-state-change semantics are downstream consumer concerns; the framework convention is per-call emit, not per-state-change emit.
* **Emit-when-either-passes** (emit `draft_ready` when EITHER dimension passes, regardless of the other) is rejected because it inverts the SYMMETRIC two-dimensional verdict structural commitment — the `draft_ready` signal IS "both per-draft gates passed"; weakening to either-passes ships drafts that failed one gate to downstream consumers as dispatch-eligible.

### D247. Per-dimension operator-override path

The two per-dimension override kwarg pairs:

* **`hallucination_check_override: bool = False`** + **`hallucination_check_override_reason: str | None = None`** — when True, the Layer 4 guard bypasses the `quality_result.state == "refused"` refuse-loud. The emitted event's `hallucination_check` field stamps `"passed_via_override"` (NOT `"passed"` — Pillar I audit-tooling distinguishes native-pass from override-pass); the `hallucination_check_override_reason` field carries the operator's rationale.
* **`voice_fidelity_check_override: bool = False`** + **`voice_fidelity_check_override_reason: str | None = None`** — when True, the Layer 4 guard bypasses the `fidelity_result.state == "refused"` refuse-loud. The emitted event's `voice_fidelity_check` field stamps `"passed_via_override"`; the `voice_fidelity_check_override_reason` field carries the rationale.

**Reason field MUST be non-empty (stripped) when the matching override is True.** The factory's refuse-loud surface per D245 covers this — operators stamping an override MUST surface the rationale per ADR-0043 D217's existing operator-side discipline.

**The override path's structural commitment:**

* The override is a per-DRAFT deliberate operator decision, NOT a per-corpus / per-register / per-Person config flag. Each override stamps the rationale at the per-draft scope; operators who repeatedly override across drafts MUST be visible in the per-event audit stream for Pillar I per-tenant audit-tooling to surface "this operator has stamped X overrides this week" signals.
* The override does NOT auto-clear the per-dimension `*_check: failed` Touch note frontmatter field (per ADR-0043 D217's discipline: the SKILL.md Phase 6 narrative names the operator's manual frontmatter rewrite when stamping an override). The Week 10 commit does NOT auto-rewrite the frontmatter; the SKILL.md Phase 6 narrative per D249 names the operator-stamping convention.
* Per ADR-0038 D182's category 8 audit, the override fields ARE surfaced in the `draft_ready` event payload — Pillar I per-tenant audit-tooling reads against the event stream for per-operator override-rate signals.

**Why two per-dimension override pairs (rejected: single composite override kwarg; rejected: override-bypass-without-reason; rejected: defer overrides to a separate downstream consumer).**

* **Two per-dimension override pairs** preserve the SYMMETRIC two-dimensional verdict structural commitment per D245 + D246 — each dimension's override is independent; operators stamping ONLY the hallucination override (e.g., a paraphrased citation the parser missed) should NOT implicitly stamp the fidelity override.
* **Single composite override kwarg** (`override_both_gates: bool = False`) is rejected because it conflates the per-dimension semantics — operators stamping a hallucination override (a known per-claim false-positive) shouldn't be forced to also stamp the fidelity override (a separate per-register threshold concern). The per-dimension separation preserves the operator's per-dimension authoritative judgment.
* **Override-bypass-without-reason** (e.g., `override: bool` without a paired `reason`) is rejected per ADR-0043 D217's discipline — the override IS the operator's deliberate decision; without the rationale field, the per-event audit stream loses the operator's intent + Pillar I per-tenant audit-tooling can't distinguish thoughtful overrides from blanket-bypass operators.
* **Defer overrides to a separate downstream consumer** (e.g., the SKILL.md Phase 6 frontmatter stamp's override path bypasses the Layer 4 guard ENTIRELY at a higher layer; the factory only runs the hard-refusal path) is rejected because the override path IS the structural commitment of ADR-0043 D217 + ADR-0045 §Migration/rollout — the override SURFACES at the per-event audit stream; deferring to a separate consumer hides the operator-stamped override from the per-event audit. The factory IS the per-Layer-4 surface; the override IS surfaced AT the factory boundary; the per-event audit stream carries the override stamp.

### D248. CLI `emit-ready` subcommand — operator-facing composite per-draft entry point

```
python orchestrator/draft_quality.py emit-ready \
    --draft-path <path> \
    --research-dossier-path <path> \
    --register {cold-pitch|congrats|re-engagement|reply|public-comment} \
    --channel {email|linkedin-dm|linkedin-comment|twitter-dm} \
    [--k 5] [--thresholds-path PATH] [--person-id ID] \
    [--hallucination-check-override --hallucination-check-override-reason REASON] \
    [--voice-fidelity-check-override --voice-fidelity-check-override-reason REASON] \
    [--skip-fidelity-check] \
    [--apply] [--json]
```

Per-call dispatch:

1. Read draft + dossier from disk (refuse-loud on missing files).
2. Run Layer 3 parser + Layer 2 hallucination-detection invariant per `score_draft` per ADR-0043 D215 → `quality_result: DraftQualityResult`.
3. Run Layer 2 voice-fidelity scorer per `compute_draft_fidelity_score` per ADR-0045 D230 → `fidelity_result: DraftFidelityResult`. **Skipped if `--skip-fidelity-check`** (the `voice_fidelity_check: skipped` path per D246).
4. **Per existing emit cardinality** (the per-Layer events emit at their existing cardinality regardless of the Layer 4 verdict):
   - IF `quality_result.uncited_claims` non-empty AND `--apply`: emit `hallucination_detected` per ADR-0043 D219.
   - IF NOT `--skip-fidelity-check` AND `--apply`: emit `draft_quality_scored` per ADR-0045 D231 (emit-always for this event class).
5. Invoke `build_draft_ready_payload(...)` per D245:
   - On `Layer4GuardRefusal`: the CLI surfaces the per-dimension trace in JSON / human-readable output + does NOT emit `draft_ready`. Exit code is 0 (the CLI ran to completion; the Layer 4 verdict is "refused" which is the framework's structural commitment, NOT a CLI error).
   - On accept: build the `draft_ready` payload; emit when `--apply` per the emit-only-on-both-pass posture per D246.
6. Report per-dimension verdicts + the Layer 4 verdict in CLI output.

**The `--skip-fidelity-check` flag** — operators with `voice.use_embedding_primitive: false` (legacy path) use this to skip the Layer 2 fidelity scorer + emit the `draft_ready` event with `voice_fidelity_check: skipped`. The flag exists for parity with the SKILL.md Phase 5 narrative per the existing `voice_fidelity_check: skipped` operator-stamping surface.

**Argparse-choices enforce closed-enums** on `--register` + `--channel` BEFORE handler dispatch per ADR-0042 D210 precedent.

**CLI does NOT surface `--embed-fn` or `--retrieve-fn`** per the security + audit rationale at ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1 + ADR-0045 D235 + ADR-0046 D243.

**`--apply` controls ledger appends** for ALL THREE event classes (the per-Layer events at the existing cardinality + the new `draft_ready` event at emit-only-on-both-pass). The dry-run path (no `--apply`) reports verdicts without ledger writes.

**Why `emit-ready` as a NEW CLI subcommand (rejected: extend the `parse` subcommand; rejected: extend the `score` subcommand; rejected: a single composite subcommand replacing `parse` + `score`; rejected: library-only at Week 10).**

* **NEW subcommand at Week 10** matches the framework's operator-facing CLI convention + the per-week-extension pattern (Pillar E `discovery_dedup check`, Pillar E `email_verification_cache lookup`, Pillar F Week 2 `voice_corpus retrieve`, Pillar F Week 5 `voice_corpus thresholds list/get/dump`, Pillar F Week 6 `draft_quality parse`, Pillar F Week 7 `draft_quality measure`, Pillar F Week 8 `draft_quality score`).
* **Extend the `parse` subcommand** is rejected because `parse` is the Layer 3 parser + Layer 2 hallucination-detection invariant — the per-call entry point per ADR-0043 D212. Extending it to ALSO run Layer 2 fidelity-scoring + Layer 4 emit-guard would couple the per-call dispatch to the composite verdict + collapse the per-week-extension pattern.
* **Extend the `score` subcommand** is rejected per the same rationale — `score` is the Layer 2 fidelity-scoring per ADR-0045 D234; extending it to ALSO run Layer 3 + Layer 4 conflates per-Layer per-call boundaries.
* **A single composite subcommand replacing `parse` + `score`** (e.g., remove `parse` + `score` + only ship `emit-ready`) is rejected per the per-week-handoff invariant — the Pillar F Week 6 + Week 8 surfaces are preserved verbatim per the per-week handoff convention. The per-Layer CLI surfaces stay; the Week 10 commit ADDS the composite without REMOVING the per-Layer ones.
* **Library-only at Week 10** is rejected per ADR-0045 D234-Alt1 — the per-week-extension convention ships the operator-readable surface with the library primitive.

### D249. SKILL.md Phase 6 frontmatter extension — `layer_4_check` + per-dimension override symmetry

The `skills/draft-outreach/SKILL.md` Phase 6 (Save + send mechanics) extends with TWO new frontmatter fields + ONE rewritten field-set:

1. **NEW: `layer_4_check: passed | passed_via_override | failed | skipped`** — the Layer 4 emit-guard verdict per ADR-0047 D245. Operators stamp this field AFTER invoking the CLI's `emit-ready` subcommand (or after manually running the per-Layer gates + the Layer 4 emit-guard).
2. **NEW: `voice_fidelity_check_override: bool`** + `voice_fidelity_check_override_reason: string | null` — the per-dimension operator-override fields for the voice-fidelity gate per D247 (symmetric with the existing `hallucination_check_override` + `hallucination_check_override_reason` fields per ADR-0043 D217).
3. **REWRITTEN: `pipeline_stage: ready`** — the gate condition extends per the Week 10 SYMMETRIC two-dimensional verdict:
   * `pipeline_stage: ready` ONLY when ALL of:
     * `voice_rules_check: passed`, AND
     * `hallucination_check: passed` OR `hallucination_check_override: true`, AND
     * `voice_fidelity_check: passed` OR `voice_fidelity_check_override: true` OR `voice_fidelity_check: skipped` (legacy path), AND
     * **`layer_4_check: passed` OR `layer_4_check: passed_via_override`** (the NEW Week 10 condition).

**The SKILL.md Phase 6 narrative changes** name the operator-stamping convention:

* AFTER the Phase 5 humanizer-checklist pass + the Phase 5 hallucination-detection gate + the Phase 5 voice-fidelity gate, the operator invokes the Layer 4 emit-guard via `python orchestrator/draft_quality.py emit-ready --draft-path /tmp/draft.txt --research-dossier-path <dossier-path> --register R --channel C [--hallucination-check-override --hallucination-check-override-reason REASON] [--voice-fidelity-check-override --voice-fidelity-check-override-reason REASON] [--skip-fidelity-check] --json`.
* The operator inspects the JSON output:
  * `layer_4_check: passed` → Phase 6 stamps `layer_4_check: passed` + `pipeline_stage: ready` advances (assuming the upstream gates ALSO passed).
  * `layer_4_check: refused` (from the JSON's `refused_dimensions` field) → Phase 6 REFUSES to advance to `pipeline_stage: ready`. The operator either remediates the draft (loops back to Phase 4) OR stamps the per-dimension override on the Touch note's frontmatter + re-invokes the CLI with the matching `--*-check-override` flag.

**Why land the SKILL.md Phase 6 extension at Week 10 (rejected: defer to Pillar I; rejected: ship as a new Phase 6.5; rejected: bypass the SKILL.md + ship guard-as-CLI-only).**

* **Land at Week 10** matches the Week 6 D217 + Week 8 D233 precedent — the SKILL.md Phase 6 extension lands AT the primitive's ship week. The operator's per-draft workflow needs the Layer 4 verdict at the per-draft scope; deferring to Pillar I leaves operators with no operator-side Layer 4 surface at Week 10 ship.
* **Defer to Pillar I** is rejected per the Week 6 + Week 8 precedents — operator-side behavior changes at Week 10 ship.
* **Ship as a new Phase 6.5** (between Phase 6 save-and-send + a future phase) is rejected per ADR-0043 D217-Alt3 — Phase 6 is the existing save-and-send phase by convention; the Layer 4 verdict IS part of the save (the `pipeline_stage: ready` advancement decision) per the structural commitment.
* **Bypass SKILL.md + ship guard-as-CLI-only** is rejected per ADR-0043 D217-Alt4 — the SKILL.md is the operator-deliberate flow + the framework's structural commitment surface; the CLI is the operator-readable per-call interface, but the SKILL.md is the per-skill workflow narrative.

### D250. TEST-ONLY `embed_fn` + `retrieve_fn` seam preservation — Week 10 emit-guard surface

The Week 10 Layer 4 emit-guard factory `build_draft_ready_payload` is a STRUCTURAL COMPOSITION — it consumes already-constructed `DraftQualityResult` + `DraftFidelityResult` instances; the per-Layer encoding work has ALREADY run at the upstream `score_draft` + `compute_draft_fidelity_score` per-call sites. The Week 10 factory's signature has NO `embed_fn` or `retrieve_fn` kwarg.

The TEST-ONLY seam discipline continues at the FIVE existing surfaces:

* `parse_draft_for_claims` `embed_fn` kwarg (per ADR-0046 D243) — UNCHANGED at Week 10.
* `score_draft` `embed_fn` kwarg (per ADR-0043 D218) — UNCHANGED at Week 10.
* `measure_per_claim_type_false_positive_rate` `embed_fn` kwarg (per ADR-0044 D227) — UNCHANGED at Week 10.
* `compute_draft_fidelity_score` `embed_fn` kwarg + `retrieve_fn` kwarg (per ADR-0045 D235) — UNCHANGED at Week 10.
* The fuzzy-fallback inside `parse_draft_for_claims` (per ADR-0046 D243's FIRST behavioral consumption) — UNCHANGED at Week 10.

The CLI's `emit-ready` subcommand per D248 does NOT surface `--embed-fn` or `--retrieve-fn` per the security + audit rationale at ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1 + ADR-0045 D235 + ADR-0046 D243.

The seam-preservation verification at Week 10:

* `test_build_draft_ready_payload_has_no_embed_fn_seam` (inspects the factory's signature; asserts `embed_fn` + `retrieve_fn` are absent).
* `test_cli_emit_ready_has_no_embed_fn_flag` (inspects the subcommand's `--help` output; asserts `--embed-fn` is absent).
* `test_cli_emit_ready_has_no_retrieve_fn_flag` (inspects the subcommand's `--help` output; asserts `--retrieve-fn` is absent).
* The existing FIVE-surface seam-preservation tests STAY GREEN at Week 10.

**Why the factory has NO seam (rejected: pass-through `embed_fn` for callers that want to re-run the per-Layer primitives inside the factory; rejected: a third seam `gate_fn` for the per-Layer dispatch).**

* **NO seam at the factory** matches the structural-composition rationale — the factory consumes already-constructed Layer 2 results; per-Layer encoding work has already amortized at the per-Layer per-call sites. Adding a seam to the factory would invert the per-Layer dispatch (the factory would be re-running the Layer 2/3 work it's supposed to be reading from); the per-call cost would compound.
* **Pass-through `embed_fn` for callers re-running per-Layer primitives** is rejected because the factory's API surface should NOT promise to re-run the per-Layer work — callers re-running need to invoke `score_draft` + `compute_draft_fidelity_score` themselves + pass the results to the factory. The clean separation preserves the per-Layer per-call boundaries.
* **A third seam `gate_fn` for the per-Layer dispatch** (e.g., `gate_fn: Callable[[DraftQualityResult, DraftFidelityResult], bool]`) is rejected because the per-Layer dispatch logic IS the per-dimension refuse-loud per D245; substituting it via a seam would bypass the structural commitment of the Layer 4 emit-guard.

### D251. Migration / ledger indexing — ZERO new migrations at Week 10

The Week 10 `draft_ready` event class carries `person_id` → indexed automatically by `_idx_person` per ADR-0010 D17 + ADR-0038 D182's category 1. The Week 12 reconcile Pass C downstream consumer (the Layer 5 reconcile heal-pass refusal) walks per-Person events via `Ledger.query_by_person(person_id)` + filters by event type — both surfaces already exist + don't need new migrations.

**Why ZERO new migrations (rejected: ship `ledger/0008_draft_quality_scored_index` for per-event indexing; rejected: ship a per-draft-hash index for cross-event consistency).**

* **ZERO new migrations** preserves the framework's pending-migration count at 19; the `_idx_person` substrate is sufficient for Week 12's per-Person Pass C heal. The framework convention per ADR-0010 D17 + ADR-0038 D182 is: new event classes inherit the per-Person index for free; per-event-class indexes are added ONLY when query patterns demand them.
* **Ship `ledger/0008_draft_quality_scored_index` for per-event indexing** is rejected because the Week 12 Pass C query pattern is per-Person (not per-event-class); the existing `_idx_person` + per-type filter is O(N_per_person_events) per call which is bounded at ~10-100 events per Person (per the Pillar D Week 12 funnel CLI's existing per-Person aggregation cost) — no new index needed.
* **Ship a per-draft-hash index for cross-event consistency** (e.g., `_idx_draft_hash` for cross-event payload-hash consistency lookup) is rejected because Week 12 Pass C's query pattern is "for this Person, find the latest `draft_quality_scored` + `hallucination_detected` + `draft_ready` events + verify the dispatch-eligibility decision" — the cross-event consistency check is a Pass-C-side responsibility, not an index-side concern. Future Pillar H scale optimizations MAY surface a per-draft-hash index if per-Person event counts grow past a threshold (operator-deferred).

## Alternatives considered

### D244-Alt1: NEW sibling module at `orchestrator/draft_ready_guard.py`

A sibling module for the Layer 4 emit-guard. **Rejected** per D244's rationale — the guard IS the SYMMETRIC two-dimensional verdict surface; co-location with the per-Layer 2 primitives preserves the per-primitive scoping.

### D244-Alt2: Subpackage at `orchestrator/draft_quality/`

Per-Layer subpackage modules. **Rejected** per ADR-0043 D212-Alt2 + ADR-0044 D220-Alt2 + ADR-0045 D228-Alt2 + ADR-0046 D236-Alt2.

### D244-Alt3: Per-Layer modules

Per-Layer files at `orchestrator/draft_quality/layer4.py`. **Rejected** per ADR-0045 D228-Alt3 — per-Layer semantics are labels.

### D244-Alt4: Extend `orchestrator/reconcile.py`

Layer 4 emit-guard at the reconcile module. **Rejected** per D244's rationale — reconcile is the per-Person heal-pass orchestrator; the Layer 4 emit-guard is per-DRAFT emit-side. Week 12 Layer 5 lands at reconcile; Week 10 Layer 4 lands at draft-quality.

### D245-Alt1: Separate per-dimension factories

Per-dimension factories with a top-level combinator. **Rejected** per D245's rationale — moves the SYMMETRIC two-dimensional verdict semantics out of the factory + into the caller.

### D245-Alt2: Factory returns Optional[dict]

`None` return instead of raising on refused. **Rejected** per D245's rationale — silent-None returns hide caller bugs; refuse-loud at the construction site is the framework convention.

### D245-Alt3: Factory takes per-Layer override as single tuple kwarg

`override: tuple[bool, bool]`. **Rejected** per D245's rationale — positional tuples are operator-hostile + lose per-dimension naming.

### D245-Alt4: Factory takes `cfg` dict carrying overrides

Dict-of-strings override. **Rejected** per D245's rationale — the type checker can't surface missing required-when-override-true reasons.

### D246-Alt1: Extend `draft_quality_scored` with a new field

Add `layer_4_check: "passed" | "refused"` to the Week 8 event class. **Rejected** per D246's rationale — the existing event class's emit-always posture doesn't match the Layer 4 emit-only-on-pass posture.

### D246-Alt2: Emit-always for `draft_ready`

Emit both ready + refused states. **Rejected** per D246's rationale — the event class SIGNALS dispatch-eligibility; refused case is the per-Layer events' diagnostic payload.

### D246-Alt3: Emit-on-state-change

Emit when the per-draft's gate verdict changes across re-scoring. **Rejected** per ADR-0045 D231-Alt2 — per-state-change semantics are downstream consumer concerns.

### D246-Alt4: Emit-when-either-passes

Emit `draft_ready` when EITHER dimension passes. **Rejected** per D246's rationale — inverts the SYMMETRIC two-dimensional verdict structural commitment.

### D247-Alt1: Single composite override kwarg

`override_both_gates: bool = False`. **Rejected** per D247's rationale — conflates per-dimension semantics.

### D247-Alt2: Override-bypass-without-reason

`override: bool` without a paired `reason`. **Rejected** per ADR-0043 D217's discipline.

### D247-Alt3: Defer overrides to a separate downstream consumer

Bypass the Layer 4 guard at a higher layer. **Rejected** per D247's rationale — hides operator-stamped override from per-event audit.

### D248-Alt1: Extend the `parse` subcommand

Run Layer 4 emit-guard from `parse`. **Rejected** per D248's rationale — couples per-call dispatch to composite verdict.

### D248-Alt2: Extend the `score` subcommand

Run Layer 4 emit-guard from `score`. **Rejected** per the same rationale.

### D248-Alt3: A single composite subcommand replacing `parse` + `score`

Remove `parse` + `score`. **Rejected** per the per-week-handoff invariant — surfaces preserved verbatim.

### D248-Alt4: Library-only at Week 10

CLI deferred to Pillar I. **Rejected** per ADR-0045 D234-Alt1 + the per-week-extension convention.

### D249-Alt1: Defer SKILL.md extension to Pillar I

Defer Phase 6 extension to a Pillar I commit. **Rejected** per the Week 6 + Week 8 precedents — operator-side behavior changes at Week 10 ship.

### D249-Alt2: Ship as a new Phase 6.5

A separate phase between Phase 6 + the next phase. **Rejected** per ADR-0043 D217-Alt3 — Phase 6 IS the save-and-send phase.

### D249-Alt3: Bypass SKILL.md + ship guard-as-CLI-only

Skip the SKILL.md narrative. **Rejected** per ADR-0043 D217-Alt4 — the SKILL.md is the operator-deliberate flow.

### D250-Alt1: Pass-through `embed_fn` for re-running per-Layer primitives

Factory accepts seam to re-run Layers 2/3. **Rejected** per D250's rationale — would invert the per-Layer dispatch.

### D250-Alt2: Third seam `gate_fn` for per-Layer dispatch

Substitute the per-dimension refuse-loud via a seam. **Rejected** per D250's rationale — would bypass the structural commitment.

### D251-Alt1: Ship `ledger/0008_draft_quality_scored_index` for per-event indexing

A new per-event-class index. **Rejected** per D251's rationale — `_idx_person` is sufficient for Week 12's Pass C query pattern.

### D251-Alt2: Ship a per-draft-hash index for cross-event consistency

`_idx_draft_hash` for cross-event payload-hash lookup. **Rejected** per D251's rationale — cross-event consistency is Pass C's responsibility, not an index concern.

## Consequences

### Positive consequences

* **The Layer 4 post-engine guard ships per ADR-0038 D180.** The FIVE-layer defense-in-depth gains its FOURTH layer; the Week 12 Layer 5 reconcile heal-pass refusal is the only remaining layer.
* **The fourth Pillar F event class ships.** `draft_ready` joins `voice_exemplar_retrieved` (Week 2) + `hallucination_detected` (Week 6) + `draft_quality_scored` (Week 8) at the cross-pillar audit's category 8 — Pillar G observability dashboards consume all four for per-register / per-channel / per-event-class aggregation.
* **The SYMMETRIC two-dimensional verdict structural commitment lands.** The Layer 4 emit-guard IS the per-draft gate's emit boundary; the per-dimension hallucination × fidelity verdict is enforced at ONE structured factory site; downstream consumers (Week 12 Pass C; Pillar G dashboards; Pillar I per-tenant audit-tooling) read against a single closed-shape `draft_ready` event class.
* **The Week 1 stub un-skips.** `test_draft_ready_event_refuses_emit_on_uncited` lands its binding behavioral commitment at Week 10 per the Week 1 ADR-0038 D180 Layer 4 ship trajectory.
* **The per-dimension operator-override path is per-event auditable.** Operators stamping overrides surface the rationale at the per-event audit stream; Pillar I per-tenant audit-tooling reads against per-operator override-rate signals for the operator-deferred per-tenant calibration trajectory.
* **The SKILL.md Phase 6 narrative gains the symmetric two-dimensional verdict.** Operators reading the skill see the Layer 4 verdict as the LAST gate before `pipeline_stage: ready` advancement; the per-dimension override symmetric (hallucination + fidelity) is the operator-side discipline.

### Negative consequences

* **Test count grows by ~60-100 tests** (TestBuildDraftReadyPayload + TestLayer4GuardRefusal + TestCLIEmitReady + TestWeek10ModuleSurface + TestSeamPreservationWeek10 + the un-skipped coherence row). Cumulative: 3222 (post-Week-9-follow-up) → ~3290-3320 (post-Week-10). The growth is bounded; per-test coverage is targeted at refuse-loud + per-dimension override + the Layer 4 invariant + the event factory + the CLI + the seam preservation.
* **`orchestrator/draft_quality.py` grows by ~480-550 LOC** (build_draft_ready_payload factory + Layer4GuardRefusal typed exception + _cmd_emit_ready CLI handler + main() extension + ~200 LOC of docstrings). The growth is intentional — the Week 10 Layer 4 emit-guard deserves co-location with the Week 6 + Week 7 + Week 8 + Week 9 primitives per D244.
* **A new event class lands at the ledger.** `draft_ready` joins the per-event grep + jq operator workflow. Pillar G dashboard authors consume the new event class for per-Layer-4 verdict signal rendering.
* **The SKILL.md Phase 6 narrative is operator-visible.** Operators reading the skill see the Layer 4 verdict as the NEW gate. The doc-sweep at Week 10 ensures the SKILL.md narrative matches the framework's new structural commitment.
* **The operator's per-draft workflow has ONE additional CLI invocation per draft.** Operators who previously stopped after the Phase 5 humanizer-check + Phase 5 gates now run the `emit-ready` subcommand at the end of Phase 5 / start of Phase 6. The per-draft operator-time cost is ~2-5 seconds (the per-Layer primitives have already run at Phase 5).

### Risks

The asymmetric-failure-cost calculus carries:

* **R030 (Layer 4 emit-guard bypass via direct payload construction) — new at Week 10.** Mitigated by design — the factory IS the only sanctioned construction surface; the `_emitted_by: "draft_quality"` marker enables Pillar I audit grep; the Week 12 Layer 5 reconcile Pass C is the final structural backstop. **Bounded by** the Pillar I per-tenant audit-tooling extension.

* **The per-dimension override surface's misuse (P3):** A future operator MAY stamp overrides as a blanket-bypass posture (every draft gets both overrides). **Bounded by** (a) the per-event audit surface naming the override-rate; (b) the Pillar I per-tenant audit-tooling's per-operator override-rate dashboard (operator-deferred); (c) the SKILL.md Phase 6 narrative naming the override as the OPERATOR'S DELIBERATE DECISION per ADR-0043 D217's existing discipline.

* **The Layer4GuardRefusal subclass-of-ValueError choice (P3):** Operators writing generic `except ValueError:` blocks WILL catch the Layer 4 refusal alongside per-field invariant violations. **Bounded by** (a) the typed exception's `refused_dimensions` attribute (operators inspect with `isinstance` to distinguish); (b) the CLI's structured JSON output (the refusal surfaces in the JSON's `refused_dimensions` field, NOT in the exception's string). The structural choice (subclass of ValueError) preserves the framework's existing exception-handling discipline (the CLI's per-Layer try/except per ADR-0043 D212 + ADR-0045 D234 catches ValueError uniformly).

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The Week 10 emit-guard appends `draft_ready` events to the ledger; the per-Layer 2 verdicts ARE the per-event payload's structural commitment (not a separate denormalized store).
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The Week 10 emit-guard is UPSTREAM of the dispatcher; the `draft_ready` event is the dispatch-eligibility signal, NOT the send intent (the send intent IS the existing `email_intent_recorded` per Pillar C precedent).
* **I3 — Atomic per-Person enrollment.** Preserved. Week 10 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The `channel` field stamps every `draft_ready` event per the channel-on-every-event invariant per ADR-0014 D33.
* **I5 — Migration framework discipline.** Preserved. Week 10 ships ZERO new migrations per D251; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved + EXTENDED. The `draft_ready` event class stamps `channel` per ADR-0014 D33's extension; the factory raises on unknown channel.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. The Week 10 emit-guard adds NEW refuse-loud surfaces: (a) `build_draft_ready_payload` closed-enum on register + channel; (b) factory channel/register mismatch with both results; (c) cross-dimension draft_hash consistency check; (d) per-dimension override bool catch + reason-required-when-override-true; (e) per-dimension `Layer4GuardRefusal` when EITHER state is "refused" AND the matching override is absent; (f) CLI argparse-choices on `--register` + `--channel`; (g) CLI missing-draft-file + missing-dossier-file refuse-loud.
* **I8 — Privacy-respecting.** Preserved + EXTENDED. The `draft_ready` event carries `draft_hash` (sha256:<hex>) NOT the raw draft body; the per-claim trace + per-exemplar bodies are NOT in the payload (only counts + per-Layer pass/refuse markers + per-dimension override reasons surface). Operators inspect per-claim diagnostics via the upstream `hallucination_detected` event + per-exemplar IDs via the upstream `draft_quality_scored` event per the per-Layer events' existing payload shapes.

## Downstream pillar impact

* **Pillar F Week 11 (open-scope per the per-week author's call).** Week 11 may extend with Layer 4 refinements (per-dimension threshold tuning; per-tenant audit-tooling; corpus revision per ADR-0046 D242's trajectory); the Week 11 commit's scope is the per-week author's call per the per-week-handoff convention.

* **Pillar F Week 12 (Layer 5 reconcile heal-pass refusal).** The Week 12 Layer 5 reconcile Pass C extension consults the per-Person `draft_ready` events via the existing `_idx_person` (the structural backstop per ADR-0038 D180 Layer 5). Per the Layer 5 design: a draft that bypassed Layers 1-4 (e.g., a stale-state Touch note with `pipeline_stage: ready` AND a corresponding linked `hallucination_detected` event AND NO `draft_ready` event) cannot advance the pipeline. The Week 10 `draft_ready` event class IS the per-Pass-C consumption surface.

* **Pillar G (Observability).** Dashboards consume the `draft_ready` event stream for per-register / per-channel / per-Layer-4-verdict aggregation. The per-register "Layer 4 acceptance rate" metric (% of `draft_ready` events with `hallucination_check: passed` AND `voice_fidelity_check: passed` — i.e., the native-pass rate vs the override-pass rate) reads against the per-event stream. Per-operator "override-rate" dashboards (per Week 8 R028 mitigation trajectory) consume the per-event `*_override` fields.

* **Pillar H (Real-time + scale).** The Week 10 emit-guard's per-call cost is bounded by the upstream per-Layer primitives' per-call cost (already-amortized at the per-Layer per-call sites); the factory's own work is O(structural validation) — negligible.

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions MAY extend with `draft_quality layer-4-baseline --corpus-dir <path>` (per-tenant per-dimension override-rate measurement) IF operator demand materializes. The Week 10 CLI's `emit-ready` subcommand accepts per-tenant `--thresholds-path` for per-tenant threshold consultation upstream of the Layer 4 emit-guard. Pillar I per-tenant audit-tooling reads against the per-event `*_override` fields for per-operator override-rate signals.

* **Pillar J (Compliance + audit).** Per-tenant GDPR-purge does not touch the `draft_ready` event class beyond the existing per-Person purge path (the event carries `person_id` for the per-Person filter). The per-event `draft_hash` is operator-deliberate sha256 hash (NOT PII); per-event override reasons are operator-stamped prose (operator-readable; not PII).

## Migration / rollout

**Week 10 ships ZERO new migrations** per D251. Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 9 to Pillar F Week 10:

1. **Operator updates the framework** to Pillar F Week 10's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 10 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_draft_quality.py -v`** to verify the new Layer 4 emit-guard tests pass. Optional but recommended.
4. **Operator's per-draft workflow extends with ONE additional CLI invocation per draft.** The new `emit-ready` subcommand runs at the end of Phase 5 / start of Phase 6:
   * **Path A (recommended):** Operator runs `python orchestrator/draft_quality.py emit-ready --draft-path /tmp/draft.txt --research-dossier-path <dossier-path> --register R --channel C --apply --json`. The CLI runs BOTH per-Layer gates + the Layer 4 emit-guard + emits ALL THREE event classes (`hallucination_detected` if uncited; `draft_quality_scored` always; `draft_ready` only if both gates pass).
   * **Path B (legacy operators with `voice.use_embedding_primitive: false`):** Operator runs `python orchestrator/draft_quality.py emit-ready ... --skip-fidelity-check --apply --json`. The Layer 2 fidelity scorer is skipped; the `draft_ready` event carries `voice_fidelity_check: skipped`.
   * **Path C (operator-deliberate override on a per-draft basis):** Operator stamps the per-dimension override on the Touch note's frontmatter + re-invokes the CLI with `--hallucination-check-override --hallucination-check-override-reason "<rationale>"` OR `--voice-fidelity-check-override --voice-fidelity-check-override-reason "<rationale>"`.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 11 is open scope per the per-week author's call. Week 12 ships Layer 5 reconcile heal-pass refusal + the binding exit-criterion test un-skips; may ship migrations IF the Layer 5 reconcile pass needs per-Person heal state.

## Existing-operator seed

**Pillar F Week 10's operator-side disposition is the Layer 4 emit-guard adoption.** The framework default behavior:

* Operators continue to set `pipeline_stage: ready` on the Touch note's frontmatter per the SKILL.md Phase 6 narrative. The Week 10 commit ADDS the Layer 4 emit-guard CLI invocation as the OPERATOR-RUNNABLE structural commitment; operators who do NOT yet adopt the CLI continue to set `pipeline_stage: ready` manually per the existing operator-stamping convention.
* The `draft_ready` event is OPTIONAL at Week 10 — operators who do NOT run the `emit-ready` CLI subcommand do NOT emit the event; the per-Person pipeline-stage continues to advance per the existing surface. The Week 12 Layer 5 reconcile Pass C will SURFACE Touch notes with `pipeline_stage: ready` + NO linked `draft_ready` event as the Pass-C heal target (the operator's adoption gate); operators inheriting the framework default at Week 12 see the Pass-C heal as the operator-stamping prompt to adopt the CLI.

**Operator action required at Week 10:** NONE. The Week 10 commit is content-additive (new event class + new CLI subcommand + new SKILL.md frontmatter fields). Operators continue their existing per-draft workflow; the Layer 4 emit-guard is the framework's NEW structural commitment surface that operators MAY adopt at their cadence.

**Operator action recommended at Week 10:** adopt the `emit-ready` CLI subcommand for the per-draft workflow. The Layer 4 emit-guard's value is the SYMMETRIC two-dimensional verdict at the emit boundary; operators adopting the CLI gain (a) per-event audit trail for the per-Layer-4 verdict; (b) the per-dimension override surface for operator-deliberate per-draft overrides; (c) the Pillar G observability dashboard's per-Layer-4 acceptance-rate signal.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D180 Layer 4's "post-engine guard on `draft_ready` event emission refuses-loud when uncited_claims non-empty" is THE binding text Week 10 implements. D182's category 8 audit ("operator-facing dashboard / CLI / aggregation surface for new event class") is THE structural reference for the `draft_ready` event class's surface audit.
- **ADR-0043 (D212-D219)** — Pillar F Week 6 hallucination-detection Layer 2-3 primitive. D213 (`DraftQualityResult` Layer 2 invariants) is THE substrate Week 10's `build_draft_ready_payload` consumes for the hallucination dimension's verdict. D216 (event factory's channel/register-mismatch refuse-loud) is THE STRUCTURAL REFERENCE for D245's factory mismatch refuse. D217 (operator-override path via `hallucination_check_override`) is THE LINEAGE D247's per-dimension override path continues. D219 (emit-only-on-uncited posture for `hallucination_detected`) is THE CONTRAST against D246's emit-only-on-both-pass posture for `draft_ready`.
- **ADR-0044 (D220-D227)** — Pillar F Week 7 per-claim-type corpora + measurement primitive. D220 (extend `orchestrator/draft_quality.py` rather than new sibling) is THE PRECEDENT for D244's module placement decision.
- **ADR-0045 (D228-D235)** — Pillar F Week 8 per-draft voice-fidelity scoring primitive. D229 (`DraftFidelityResult` Layer 2 invariants) is THE substrate Week 10's `build_draft_ready_payload` consumes for the fidelity dimension's verdict. D231 (event factory's emit-always posture for `draft_quality_scored`) is THE CONTRAST against D246's emit-only-on-both-pass posture for `draft_ready`. D235 (TEST-ONLY embed_fn + retrieve_fn seam preservation) is THE LINEAGE D250's NO-seam-at-the-factory decision preserves.
- **ADR-0046 (D236-D243)** — Pillar F Week 9 per-claim fuzzy-match citation extension. D243 (TEST-ONLY embed_fn seam's FIRST behavioral consumption at parser surface) is THE LINEAGE D250 continues.
- **ADR-0028 (D116)** — Pillar D Week 4-5 auto-unsubscribe handler's YAML-first-then-ledger discipline. The Week 10 emit-guard's refuse-loud semantics MIRROR D116's "the YAML write IS the structural commitment; the ledger append IS the audit trail" — the Week 10 emit-guard's `draft_ready` event IS the audit trail; the per-Layer 2 + Layer 3 verdicts ARE the structural commitments.
- **ADR-0014 (D33)** — Pillar C foundation. The channel-on-every-event invariant extends to the `draft_ready` event class per D246.
- **ADR-0010 (D17)** — Per-event `_emitted_by` marker. The Week 10 event factory stamps `_emitted_by="draft_quality"` (same module emits all FOUR Pillar F event classes — `voice_exemplar_retrieved` + `hallucination_detected` + `draft_quality_scored` + `draft_ready`).
- **ADR-0041 (D199-D205)** — Pillar F Week 4 per-register threshold infrastructure. D201 (range validation + bool catch) is THE STRUCTURAL REFERENCE for the bool catches on the per-dimension override kwargs per D247.
- **ADR-0042 (D206-D211)** — Pillar F Week 5 voice-thresholds CLI extension. D210 (argparse-choices closed-enum at CLI) is THE STRUCTURAL REFERENCE for the CLI's `--register` + `--channel` argparse-choices per D248.
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §55+ extends with the Week 10 commit's audit verdict (the Layer 4 emit-guard's public surface + the NEW event class + the CLI extension + the SKILL.md Phase 6 narrative changes).
- **`.planning/HANDOFF-pillar-f-week-10.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 11+ trajectory.
- **`orchestrator/draft_quality.py`** — extended with `build_draft_ready_payload` + `Layer4GuardRefusal` + `_cmd_emit_ready` per D244-D248.
- **`skills/draft-outreach/SKILL.md`** — Phase 6 extended per D249.
- **`tests/test_draft_quality.py`** — extended with `TestBuildDraftReadyPayload` + `TestLayer4GuardRefusal` + `TestCLIEmitReady` + `TestWeek10ModuleSurface` + `TestSeamPreservationWeek10` (~60-100 new tests covering D244-D251).
- **`tests/test_multi_channel_coherence.py::TestHallucinationDetection::test_draft_ready_event_refuses_emit_on_uncited`** — un-skipped at Week 10 per the Week 1 stub trajectory.
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 10 close summary.
- **`docs/adr/README.md`** — ADR-0047 row appended.
- **`docs/RISK-REGISTER.md`** — R030 (Layer 4 emit-guard bypass) row appended.
