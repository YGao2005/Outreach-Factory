# ADR-0045: Pillar F Week 8 — per-draft voice-fidelity scoring primitive + `draft_quality_scored` event class + `voice.use_embedding_primitive` default flip

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** F (Voice corpus + draft quality — Week 8 fidelity-scoring primitive)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation; Week 2 (ADR-0039 D185-D191) shipped the embedding-retrieval primitive; Week 3 (ADR-0040 D192-D198) shipped the per-register adapters; Week 4 (ADR-0041 D199-D205) shipped the per-register threshold loader; Week 5 (ADR-0042 D206-D211) shipped the operator-facing thresholds CLI; Week 6 (ADR-0043 D212-D219) shipped the hallucination-detection Layer 2-3 primitive; **Week 7** (ADR-0044 D220-D227) shipped the per-claim-type test corpora + measurement primitive (R027 mitigation — per-claim false-positive rate baseline). Week 7 closed at `06c3a8a` + follow-up `8e15fef` (0 P1 + 1 P2 + 3 P3 addressed); 3083 tests passing.

**Pillar F Week 8 ships THE per-draft voice-fidelity scoring primitive** per ADR-0045. The primitive is THE binding substrate the Pillar F D184(a) invariant promises since Week 1: *"the voice-fidelity score is a per-draft float in `[0.0, 1.0]` — the cosine similarity between the draft embedding and the top-K voice-corpus exemplar embeddings (weighted average)."*

The Week 8 commit lands FOUR concrete artifacts:

1. **`DraftFidelityResult` Layer 2 dataclass** — per-draft fidelity result with construction-time invariants per D229. Symmetric with the Week 6 `DraftQualityResult` (refuses-loud at construction when `state="ready"` AND `meets_threshold=False`).
2. **`compute_draft_fidelity_score` primitive** per D230 — consumes the Week 2 retrieval primitive + the Week 4 threshold loader; computes the per-draft fidelity score as the mean of top-K voice-corpus exemplars' (cosine × recency) scores; clamps to `[0.0, 1.0]`.
3. **`build_draft_quality_scored_payload` event factory** per D231 — the THIRD Pillar F event class (per ADR-0038 D182). **Emit-always** posture (vs Week 6's emit-only-on-uncited for `hallucination_detected` per ADR-0043 D219) — Pillar G observability needs accept-case events for per-register score distribution rendering.
4. **`voice.use_embedding_primitive` config default flip** per D232 — flips from `false` → `true`. The Week 2-7 transition window closes: the embedding-retrieval primitive is the framework default; operators with legacy corpora opt OUT explicitly.

The eight concerns this ADR resolves:

1. **Module placement** for the new primitive surface — extend `orchestrator/draft_quality.py` (per the Week 7 D220 co-location precedent) OR ship a new sibling at `orchestrator/fidelity_scoring.py`. **D228** pins.

2. **`DraftFidelityResult` dataclass shape + construction-time invariants** — the LOAD-BEARING refuse-loud surface for the per-register voice-fidelity gate per ADR-0038 D184(a). **D229** pins.

3. **`compute_draft_fidelity_score` primitive's per-call shape + the per-draft fidelity-score formula** (mean of top-K exemplar scores; clamp to `[0.0, 1.0]`; per-register threshold consumption). **D230** pins.

4. **`draft_quality_scored` event class emit-shape + emit posture** — the third Pillar F event class per ADR-0038 D182. Emit-always (NOT emit-only-on-X) per the Pillar G observability use case. **D231** pins.

5. **`voice.use_embedding_primitive` config default flip from `false` → `true`** per ADR-0039 §Existing-operator seed's Week 8+ trajectory. **D232** pins.

6. **SKILL.md Phase 4 + Phase 5 extension** — operators consuming the `/draft-outreach` skill see the new fidelity-scoring step as part of the per-draft gate. **D233** pins.

7. **CLI `score` subcommand** — operator-facing surface for per-draft fidelity scoring; mirrors the Week 6 `parse` subcommand's shape per ADR-0043 D212. **D234** pins.

8. **TEST-ONLY `embed_fn` + `retrieve_fn` injection seam preservation** — the Week 8 fidelity-scoring primitive ships TWO injection seams: `embed_fn` (passes through to the retrieval primitive per ADR-0043 D218's seam) + `retrieve_fn` (NEW Week 8 seam — full retrieval bypass for unit tests). **D235** pins.

Risks this ADR mitigates by design: **R023 (Hallucination-detection false-negative)** continues mitigated — Week 8 is voice-fidelity-scoring (orthogonal to hallucination-detection); the FIVE-layer defense per ADR-0038 D180 stays at Layer 3 (Week 6); Layer 4 ships Week 10; Layer 5 ships Week 12. **R024 (voice-corpus drift)** continues mitigated by the per-register fidelity-scoring's threshold consumption — operators see per-register score distributions via the `draft_quality_scored` event stream + Pillar G dashboards. **R025 (embedding-cost runaway)** continues mitigated — the Week 8 primitive consumes the Week 2 retrieval primitive's existing per-process model cache; no NEW per-call encoder calls beyond the Week 2 baseline. **R026 (operator-corpus split)** continues mitigated by the Week 2 metadata-mismatch refuse-loud + rebuild path; the Week 8 primitive inherits.

One new risk surfaces in this Week 8 commit + named in `docs/RISK-REGISTER.md`:

- **R028 (per-register threshold mis-calibration)** — the per-register thresholds shipped at Week 4 (cold-pitch ≥0.70; congrats ≥0.65; re-engagement ≥0.72; reply ≥0.70; public-comment ≥0.60 — calibrated against Yang's curated corpus per ADR-0041 D200) MAY be mis-calibrated for operators with materially different corpora (different voice; different register conventions; different recipient mix). The Week 4 ADR pinned the recalibration trajectory at Week 8+ — Week 8 lands the SCORING primitive; operators now have the substrate to MEASURE per-register score distributions against THEIR corpus. **Mitigated by** the per-register threshold operator-tunability per ADR-0041 D199-D204; operators with thoroughly-tuned corpora consult the `draft_quality_scored` event stream + tune `~/.outreach-factory/voice_thresholds.yml` per their distribution. **Bounded by** the Pillar I per-tenant audit-tooling trajectory + the per-corpus baseline measurement extension (operator-deferred).

## Decision

### D228. Module placement — extend `orchestrator/draft_quality.py` (NOT a new sibling module)

The Week 8 fidelity-scoring primitive lives at `orchestrator/draft_quality.py` (the Week 6 + Week 7 primitives' existing module). The new public surfaces:

* **`DraftFidelityResult`** dataclass (Layer 2 invariant per D229).
* **`compute_draft_fidelity_score`** primitive function (per-call dispatch per D230).
* **`build_draft_quality_scored_payload`** event factory (emit-always per D231).
* **`_cmd_score`** CLI handler + main() extension (per D234).

The module's growth: ~1700 LOC (post-Week-7) → ~2400 LOC (post-Week-8; +700 LOC for the Week 8 primitive + CLI + docstrings).

**Why extend the existing module (rejected: NEW sibling module at `orchestrator/fidelity_scoring.py`; rejected: subpackage at `orchestrator/draft_quality/`; rejected: per-Layer modules).**

* **Extend the existing module** matches the per-primitive flat-module convention per ADR-0036 D166 + ADR-0043 D212 + ADR-0044 D220. Both Week 6's `score_draft` (hallucination-detection composite) and Week 8's `compute_draft_fidelity_score` (voice-fidelity composite) consume the same Week 4 threshold loader (`get_voice_threshold_for_register`); both consume the same shared substrate (REGISTERS + CHANNELS closed-enums); both feed into the same downstream consumers (Week 10 Layer 4 emit guard + Week 12 Layer 5 reconcile heal-pass). Co-locating in one module preserves the per-primitive scoping + the operator-readable import shape (`from orchestrator.draft_quality import score_draft, compute_draft_fidelity_score`).
* **NEW sibling module at `orchestrator/fidelity_scoring.py`** is rejected because the fidelity-scoring primitive is the symmetric per-draft gate alongside the hallucination-detection primitive — splitting them across two modules creates the "look in two places" mental model the per-week convention rejects (per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0044 D220 — same shape rationale). Operators understanding "the per-draft gate" SHOULD find both surfaces at one import path.
* **Subpackage at `orchestrator/draft_quality/`** is rejected per the same rationale as ADR-0043 D212-Alt2 + ADR-0044 D220-Alt2 — over-organization for the Week 8 commit's ~700 LOC scope; one module is sufficient + future Pillar F weeks' extensions land at the existing module.
* **Per-Layer modules** (e.g., `orchestrator/draft_quality/layer2.py` + `layer3.py` + `layer4.py` + `layer5.py`) is rejected — per-Layer semantics are LABELS on the gate's defense-in-depth (per ADR-0038 D180), not module-split signals. The FIVE-layer defense ships across Weeks 6 + 10 + 12 at the same module's increasing surface area.

### D229. `DraftFidelityResult` dataclass + Layer 2 construction-time invariants

```python
@dataclass(frozen=True)
class DraftFidelityResult:
    draft_hash: str
    register: str
    channel: str
    voice_fidelity_score: float
    voice_fidelity_threshold: float
    meets_threshold: bool
    exemplar_ids: tuple[str, ...]
    k: int
    state: str
```

Construction-time invariants in `__post_init__`:

* `draft_hash` starts with `"sha256:"` (privacy per I8).
* `register` in `REGISTERS` (closed-enum per ADR-0038 D178).
* `channel` in `CHANNELS` (closed-enum per ADR-0014 D33).
* `state` in `{"ready", "refused"}` (closed-set).
* `voice_fidelity_score` is a float in `[0.0, 1.0]` (bool catch per ADR-0041 D201).
* `voice_fidelity_threshold` is a float in `[0.0, 1.0]` (bool catch).
* `meets_threshold` is a bool consistent with `voice_fidelity_score >= voice_fidelity_threshold` (the stamped boolean MUST match the comparison).
* `exemplar_ids` is a tuple of strs (per-item type check mirrors Week 6 follow-up P2-1 per ADR-0043 D213).
* `k` is a non-negative int (bool catch).
* `len(exemplar_ids) <= k` (subset invariant — the framework's retrieval primitive may return fewer than K when filters narrow the corpus per ADR-0039 D188).
* **`state="ready"` AND `meets_threshold=False` is REFUSED** — THE Layer 2 invariant per ADR-0038 D184(a) (structural commitment).

The dataclass is the LOAD-BEARING refuse-loud surface for the per-register voice-fidelity gate; symmetric with the Week 6 `DraftQualityResult` per ADR-0043 D213's "state='ready' AND uncited_claims non-empty is REFUSED" invariant.

**Why a typed frozen dataclass with construction-time invariants (rejected: dict-only result; rejected: TypedDict; rejected: separate flat field returns).**

* **Typed frozen dataclass with construction-time invariants** matches the framework's discipline per ADR-0036 D167 + ADR-0039 D186 + ADR-0043 D213 + ADR-0044 D222. Construction-time validation refuses-loud at the primitive's construction site; downstream consumers (Pillar G dashboard; Week 10 emit guard; Week 12 reconcile) read against the typed shape — no schema drift risk. The frozen dataclass also documents the per-result shape via type annotations (operators reading `DraftFidelityResult.__doc__` see the contract).
* **Dict-only** is rejected because per-field validation would have to live in the primitive function — adding scope creep + losing the IDE-assisted authoring of downstream consumers.
* **TypedDict** is rejected because the per-field construction-time validation can't run on a TypedDict (the type system doesn't enforce runtime invariants); the bool-catch + the consistency check between `meets_threshold` + the score/threshold pair need explicit runtime validation.
* **Separate flat field returns** (the primitive returns `(score, threshold, meets, ...)` tuple) is rejected — the tuple shape is positional + breaks operator-readability + loses the structural commitment to the Layer 2 invariant.

### D230. `compute_draft_fidelity_score` primitive — per-call shape + formula

```python
def compute_draft_fidelity_score(
    draft: str,
    *,
    register: str,
    channel: str,
    k: int = DEFAULT_TOP_K,
    is_substantive_reply: bool | None = None,
    now: datetime | None = None,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    retrieve_fn: Callable[..., list[VoiceExemplar]] | None = None,
) -> DraftFidelityResult: ...
```

Per-call dispatch:

1. Validate closed-enums (`register` + `channel`) BEFORE retrieval — fail-fast at the closed-enum boundary saves a SentenceTransformer load on operator misconfiguration.
2. Resolve the per-register threshold via `voice_corpus.get_voice_threshold_for_register` (the Week 4 loader per ADR-0041 D204).
3. Retrieve top-K voice-corpus exemplars via `voice_corpus.retrieve_voice_exemplars` (the Week 2 primitive per ADR-0039 D188). The TEST-ONLY `retrieve_fn` injection seam per D235 bypasses for unit tests.
4. Compute per-draft fidelity score = mean of per-exemplar scores (cosine × recency multiplier per ADR-0038 D184(a)). Each `VoiceExemplar.score` is already cosine × recency from the retrieval primitive per ADR-0039 D188; the Week 8 composite is the simple mean over top-K.
5. Clamp to `[0.0, 1.0]` to satisfy the `DraftFidelityResult` construction-time invariant — out-of-range scores are theoretically possible with non-normalized embeddings or low-recency samples (recency < 0 when `sample.year > anchor.year`).
6. Construct `DraftFidelityResult` (Layer 2 invariant runs at construction).

**Empty exemplar list (empty corpus OR filter-yields-nothing) yields `voice_fidelity_score=0.0` + `state="refused"`** — the framework refuses-loud per ADR-0038 D184's asymmetric-failure-cost calculus. Silently accepting drafts against an empty corpus is the brand-risk path; refuse-loud is the operator-friction path.

**Why mean-of-top-K scores (rejected: rank-weighted mean; rejected: max of top-K; rejected: median).**

* **Mean of top-K scores** matches ADR-0038 D184(a)'s "weighted average over top-K corpus exemplars" — each exemplar's score IS cosine × recency (the recency weighting is per-exemplar at the retrieval primitive per ADR-0039 D188); the composite mean treats each top-K exemplar equally + lets the per-exemplar score's already-weighted shape carry through. The interpretation: cosine × recency is the per-exemplar weighted contribution; mean is the composite aggregation grain. Pillar I per-tenant calibration MAY surface rank-weighted variants IF operator demand materializes.
* **Rank-weighted mean** (e.g., `[1.0, 0.9, 0.8, 0.7, 0.6]` rank weights times per-exemplar score, normalized) is rejected at Week 8 — operators tuning per-corpus distributions need a baseline to calibrate against; the simple-mean baseline is operator-readable + ADR-amendable to rank-weighted IF the per-week reviewer's call surfaces demand.
* **Max of top-K** is rejected because a single high-cosine outlier inflates the score artificially; operators want the AGGREGATE voice-fidelity, not the best-match singular exemplar.
* **Median** is rejected because the top-K is already filtered to high-cosine matches; median is approximately the same as mean for K=5; the mean is mathematically simpler + the Pillar G dashboard's per-register distribution rendering reads against per-event scalar (vs per-event distribution).

### D231. `build_draft_quality_scored_payload` event factory — emit-always posture

```python
def build_draft_quality_scored_payload(
    *,
    person_id: str | None,
    result: DraftFidelityResult,
    channel: str,
    register: str,
) -> dict: ...
```

Event shape:

```text
type:                       draft_quality_scored
person_id                   (the prospect the draft targets; None for ad-hoc)
draft_hash                  (sha256:<hex> of the draft body — NOT raw draft per I8)
register                    (closed-enum per ADR-0038 D178)
channel                     (closed-enum per ADR-0014 D33)
voice_fidelity_score        (float in [0.0, 1.0] per ADR-0038 D184(a))
voice_fidelity_threshold    (per-register threshold consulted per ADR-0041 D204)
meets_threshold             (bool; stamped per D229)
state                       ({"ready", "refused"})
exemplar_ids                (list of str — per-exemplar bodies NOT included per I8)
k                           (the requested top-K)
_emitted_by                 ("draft_quality" per ADR-0010 D17 + ADR-0043 D216)
```

**Emit-always posture** — BOTH `ready` and `refused` states emit through this factory. **Diverges from Week 6's `hallucination_detected` emit-only-on-uncited posture** per ADR-0043 D219:

| Event | Posture | Rationale |
|---|---|---|
| `hallucination_detected` (Week 6) | Emit-only-on-uncited | The event SIGNALS a problem (uncited claim caught); accept-case is the silent default per ADR-0043 D219. |
| `draft_quality_scored` (Week 8) | Emit-always | The event CARRIES per-draft fidelity score for Pillar G observability; accept-case events ARE structurally load-bearing for per-register score distribution rendering. |

Refuse-loud at the factory boundary:

* `channel` not in `CHANNELS` raises `ValueError`.
* `register` not in `REGISTERS` raises `ValueError`.
* `channel != result.channel` OR `register != result.register` raises `ValueError` (mirrors Week 6 follow-up P2-2 per ADR-0043 D216) — silent kwarg/result mismatch would surface phantom Pillar G dashboard signals.

Privacy-respecting per I8 + ADR-0038 §Compliance with invariants:

* **Raw draft body MUST NOT appear in the payload.** The draft is sha256-hashed at the result construction site.
* **Per-exemplar bodies MUST NOT appear in the payload.** Only the exemplar IDs surface (operators look up bodies via the corpus directly per ADR-0039 D189 precedent).

**Why emit-always (rejected: emit-only-on-refused; rejected: emit-only-on-state-change; rejected: skip the factory).**

* **Emit-always** matches the Pillar G observability use case (per-register score distribution rendering) + the dashboard's per-event aggregation needs accept-case events to render the "ready" baseline. Without accept-case emit, the dashboard sees only refusals + can't compute per-register acceptance rates.
* **Emit-only-on-refused** is rejected because it imitates Week 6's `hallucination_detected` posture without the matching rationale — `draft_quality_scored` is the operator-readable per-draft score signal, not the "we caught a problem" signal.
* **Emit-only-on-state-change** (e.g., when a re-scored draft's state changes from refused → ready) is rejected — the per-state-change semantics are downstream consumer concerns (Pillar G dashboard's per-Person per-register tracking) + complicating the factory inverts the read/write separation per ADR-0039 D189-Alt1.
* **Skip the factory** (operators construct payloads manually) is rejected per ADR-0039 D189-Alt3 — schema drift across callers is the framework convention's anti-pattern.

### D232. `voice.use_embedding_primitive` config default flip from `false` → `true`

The `config-template/config.example.yml`'s `voice.use_embedding_primitive` field default flips from `false` to `true` at Week 8 per ADR-0039 §Existing-operator seed's Week 8+ transition.

Operators with corpora tagged with `register` + `channel` schema fields per ADR-0038 D178 inherit the new behavior automatically (the framework default consumes the new primitive). Operators with legacy corpora set `voice.use_embedding_primitive: false` explicitly to keep the legacy heuristic active.

The deprecation timing for `voice_retrieve.py` remains operator-deferred — the file stays through Pillar F Week 12 exit gate (per ADR-0038 §Existing-operator seed); Pillar F Week 12+ may surface a stderr deprecation notice on import IF operator transition demand materializes.

**Why flip at Week 8 (rejected: flip at Week 12 exit gate; rejected: don't flip until Pillar G; rejected: flip earlier at Week 6).**

* **Flip at Week 8** matches ADR-0039 §Existing-operator seed's Week 8+ transition pin — the per-register adapters shipped at Week 3 (ADR-0040); the per-register thresholds shipped at Week 4 (ADR-0041); the hallucination-detection primitive shipped at Week 6 (ADR-0043); the per-claim-type measurement primitive shipped at Week 7 (ADR-0044); Week 8 ships the per-draft fidelity-scoring primitive — the substrate is complete. The framework default flips when the framework's NEW substrate is the more-capable surface.
* **Flip at Week 12 exit gate** is rejected because operators adopting the Week 8+ fidelity-scoring primitive need the new primitive to be the framework default at Week 8 ship; deferring to Week 12 means operators ship Week 8 with the legacy heuristic for 4 more weeks.
* **Don't flip until Pillar G** is rejected because the Pillar F Week 8 commit IS the operator-visible transition point (per ADR-0039 §Existing-operator seed); Pillar G is a separate pillar's concern.
* **Flip earlier at Week 6** is rejected because Week 6 ships the hallucination-detection primitive (orthogonal to retrieval); the retrieval primitive's flip belongs at the week that completes the per-register substrate (Week 8).

### D233. SKILL.md Phase 4 + Phase 5 extension

The `skills/draft-outreach/SKILL.md` Phase 4 + Phase 5 sections extend per ADR-0040 §Existing-operator seed's deferred Week 8+ extension. The narrative changes:

* **Phase 4 (voice retrieval + inline rewrite):** the dispatch narrative flips so Path A (`voice.use_embedding_primitive: true` via `orchestrator/voice_corpus.py retrieve --register R --channel C`) is the framework default; Path B (`voice_retrieve.py` legacy) is the opt-out posture. Operators reading the SKILL.md see the new primitive as the default + the legacy heuristic as the explicit opt-out (the §Existing-operator seed migration trajectory pin).
* **Phase 5 (humanizer-checklist pass):** AFTER the per-register anti-tell checklist + the hallucination-detection gate, the NEW per-register voice-fidelity gate runs. The gate invokes the Week 8 CLI:
  ```bash
  python orchestrator/draft_quality.py score \\
      --draft-path /tmp/draft.txt \\
      --register {register-key} --channel {channel-key} \\
      --json 2>/dev/null > /tmp/voice_fidelity.json
  ```
  Operators inspect the JSON output's `state` field; `refused` blocks the draft from advancing to `pipeline_stage: ready` (mirrors the Week 6 hallucination-detection gate's behavior per ADR-0043 D217).

**Why extend at Phase 5 (rejected: extend at Phase 4; rejected: extend at Phase 3.5; rejected: defer to Pillar G).**

* **Extend at Phase 5** matches the per-draft gate's structural placement — the humanizer-checklist pass is the LAST per-draft validation before the Touch note save + the optional send chain. The voice-fidelity gate joins the hallucination-detection gate at this phase as the SYMMETRIC per-draft quality check.
* **Extend at Phase 4** is rejected because Phase 4 is the rewrite step (operator's voice grounding); the gate VALIDATES the rewrite's output — placement at Phase 4 would couple the rewrite to the gate's verdict + complicate the per-phase isolation.
* **Extend at Phase 3.5** is rejected because Phase 3.5 is the scaffold assembly (pre-rewrite); the gate operates on the rewritten draft.
* **Defer to Pillar G** is rejected because Pillar G is observability (per-pillar concern); the per-draft gate IS Pillar F's Week 8 deliverable — operator-side behavior changes at Week 8, not at Pillar G ship.

### D234. CLI `score` subcommand — operator-facing surface

```
python orchestrator/draft_quality.py score \
    --draft-path <path> \
    --register {cold-pitch|congrats|re-engagement|reply|public-comment} \
    --channel {email|linkedin-dm|linkedin-comment|twitter-dm} \
    [--k 5] [--thresholds-path PATH] [--person-id ID] \
    [--apply] [--json]
```

Mirrors the Week 6 `parse` subcommand's shape per ADR-0043 D212 + the Week 7 `measure` subcommand's shape per ADR-0044 D224. Argparse-choices enforces the closed-enum on `--register` + `--channel` BEFORE handler dispatch (per ADR-0042 D210 precedent).

The `--apply` flag controls whether the `draft_quality_scored` event is appended to the ledger. Per D231's emit-always posture, the event emits for BOTH `ready` and `refused` states when `--apply` is set; default is dry-run (report only).

**Why a CLI subcommand at Week 8 (rejected: library-only; rejected: per-register subcommands; rejected: chain into the `parse` subcommand).**

* **CLI subcommand at Week 8** matches the framework's operator-facing CLI convention + the per-week-extension pattern (Pillar E `discovery_dedup check`, Pillar E `email_verification_cache lookup`, Pillar F Week 2 `voice_corpus retrieve`, Pillar F Week 5 `voice_corpus thresholds list/get/dump`, Pillar F Week 6 `draft_quality parse`, Pillar F Week 7 `draft_quality measure`).
* **Library-only at Week 8** is rejected because the per-week-extension convention ships the operator-readable surface with the library primitive.
* **Per-register subcommands** (`score-cold-pitch`, `score-congrats`, etc.) is rejected per ADR-0044 D224-Alt2 — argparse-choices is the framework convention for per-enum-value dispatch.
* **Chain into the `parse` subcommand** (extend `parse` to ALSO emit `draft_quality_scored`) is rejected because the two primitives have ORTHOGONAL gate verdicts (hallucination-detection vs voice-fidelity); operators may want one without the other; the two CLIs let operators inspect independently.

### D235. TEST-ONLY `embed_fn` + `retrieve_fn` seam preservation

The Week 8 fidelity-scoring primitive ships TWO injection seams labeled TEST-ONLY in the docstring:

1. **`embed_fn`** — passes through to `voice_corpus.retrieve_voice_exemplars`'s `embed_fn` kwarg per ADR-0043 D218. Reserved for the test suite + the Week 8+ encoding extension; operators do NOT inject custom encoders at production callsites.
2. **`retrieve_fn`** (NEW Week 8 seam) — full retrieval bypass for unit tests. When supplied, replaces `retrieve_voice_exemplars` for the per-call retrieval; receives the same kwargs (`query`, `k`, `register`, `channel`, `is_substantive_reply`, `now`, `cfg`, `embed_fn`). The seam exists because the Week 8 primitive's per-call dispatch tests need to substitute fake exemplars without building a real corpus on disk (the existing `voice_corpus`-level tests do build temp corpora; the `draft_quality`-level tests pass deterministic stubs).

Both kwargs are reserved for the test suite + the Week 8+ encoding extension. **CLI does NOT surface `--embed-fn` or `--retrieve-fn`** (security + audit per ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1).

The seam-preservation continues at the Week 8 commit:

* `parse_draft_for_claims` `embed_fn` kwarg — UNCHANGED at Week 8 (Week 6 ADR-0043 D218 + Week 7 ADR-0044 D227's verification status preserved).
* `score_draft` `embed_fn` kwarg — UNCHANGED at Week 8.
* `measure_per_claim_type_false_positive_rate` `embed_fn` kwarg — UNCHANGED at Week 8.
* `compute_draft_fidelity_score` `embed_fn` kwarg — NEW (Week 8). Passes through to the retrieval primitive.
* `compute_draft_fidelity_score` `retrieve_fn` kwarg — NEW (Week 8). Full retrieval bypass for unit tests.

**Why TWO seams at the fidelity-scoring surface (rejected: only `embed_fn`; rejected: only `retrieve_fn`; rejected: a single composite seam).**

* **Two seams** address two distinct test isolation concerns: the `embed_fn` seam (encoding cost) + the `retrieve_fn` seam (corpus I/O cost + per-exemplar deterministic substitution). Unit tests of compute_draft_fidelity_score's per-call dispatch (mean computation, clamping, threshold comparison, construction-time invariants) benefit from `retrieve_fn` substitution (skip the corpus load entirely); end-to-end tests benefit from `embed_fn` (substitute the encoder while exercising the full retrieve_voice_exemplars path).
* **Only `embed_fn`** is rejected because the per-call dispatch tests would still need to build a temp corpus on disk (the corpus load is the per-test cost the `retrieve_fn` seam amortizes).
* **Only `retrieve_fn`** is rejected because the `embed_fn` seam continues the ADR-0043 D218 + ADR-0044 D227 + ADR-0040 D197 + ADR-0039 D188 lineage at the fidelity-scoring surface — without it, the seam-preservation discipline breaks for callers consuming `retrieve_voice_exemplars` directly through the fidelity-scoring primitive.
* **Single composite seam** (e.g., `compute_fn: Callable[..., DraftFidelityResult]`) is rejected because operators substituting at the result level would bypass the construction-time invariants — the seams substitute at the COMPONENT level (encoding; retrieval), not at the COMPOSITE level (the result).

## Alternatives considered

### D228-Alt1: NEW sibling module at `orchestrator/fidelity_scoring.py`

Per the per-primitive-flat-module convention, the fidelity-scoring primitive lives at a NEW sibling module. **Rejected** per D228's rationale — the fidelity-scoring primitive is the symmetric per-draft gate alongside the hallucination-detection primitive; co-location preserves the per-primitive scoping.

### D228-Alt2: Subpackage at `orchestrator/draft_quality/`

Per-Layer subpackage modules. **Rejected** per ADR-0043 D212-Alt2 + ADR-0044 D220-Alt2 — over-organization for the per-week commit scope.

### D228-Alt3: Per-Layer modules

Per-Layer files at `orchestrator/draft_quality/layer2.py` etc. **Rejected** — per-Layer semantics are labels, not module-split signals.

### D229-Alt1: Dict-only result

The primitive returns a `dict[str, Any]` instead of a typed dataclass. **Rejected** per D229's rationale — typed dataclass with construction-time invariants is the framework convention per ADR-0036 D167 + ADR-0039 D186 + ADR-0043 D213 + ADR-0044 D222.

### D229-Alt2: TypedDict

The result is a `TypedDict` with structural type hints. **Rejected** — TypedDict doesn't enforce runtime invariants; the bool-catch + consistency checks need explicit runtime validation.

### D229-Alt3: Separate flat field returns

The primitive returns a tuple `(score, threshold, meets, ...)`. **Rejected** — positional tuples are operator-hostile + lose the Layer 2 structural commitment.

### D230-Alt1: Rank-weighted mean

The fidelity score is `sum(rank_weight[i] * exemplar[i].score) / sum(rank_weight)`. **Rejected** at Week 8 per D230's rationale — the simple-mean baseline is operator-readable + ADR-amendable to rank-weighted IF demand materializes.

### D230-Alt2: Max of top-K

The fidelity score is `max(exemplar.score for exemplar in top_k)`. **Rejected** — a single high-cosine outlier inflates the score artificially.

### D230-Alt3: Median

The fidelity score is the median of top-K. **Rejected** — mathematically similar to mean for K=5; the simpler mean is the operator-readable baseline.

### D231-Alt1: Emit-only-on-refused

The factory refuses construction when `state="ready"`. **Rejected** per D231's rationale — Pillar G observability needs accept-case events for per-register score distribution rendering.

### D231-Alt2: Emit-only-on-state-change

The factory emits only when the re-scored draft's state changes from refused → ready (or vice versa). **Rejected** — per-state-change semantics are downstream consumer concerns; complicating the factory inverts the read/write separation per ADR-0039 D189-Alt1.

### D231-Alt3: Skip the factory

Operators construct payloads manually. **Rejected** per ADR-0039 D189-Alt3 — schema drift across callers is the anti-pattern.

### D232-Alt1: Flip at Pillar F Week 12 exit gate

Defer the flip until the binding exit-criterion test passes. **Rejected** per D232's rationale — operators adopting the Week 8+ fidelity-scoring primitive need the new primitive to be the framework default at Week 8 ship.

### D232-Alt2: Don't flip until Pillar G

Defer the flip to a separate pillar's commit. **Rejected** — Pillar G is a separate pillar's concern; the Pillar F Week 8 commit IS the operator-visible transition point per ADR-0039 §Existing-operator seed.

### D232-Alt3: Flip earlier at Week 6

Flip at Week 6 alongside the hallucination-detection primitive. **Rejected** — Week 6 ships the hallucination-detection primitive (orthogonal to retrieval); the retrieval primitive's flip belongs at the week that completes the per-register substrate (Week 8).

### D233-Alt1: Extend at Phase 4

Place the voice-fidelity gate inside Phase 4 (alongside the rewrite). **Rejected** per D233's rationale — Phase 5 is the per-draft validation phase; placement at Phase 4 couples the rewrite to the gate's verdict.

### D233-Alt2: Extend at Phase 3.5

Place the gate before the rewrite (validate the scaffold). **Rejected** — the gate operates on the rewritten draft, not the pre-rewrite scaffold.

### D233-Alt3: Defer SKILL.md extension to Pillar G

Defer the Phase 5 extension to a Pillar G commit. **Rejected** — operator-side behavior changes at Week 8 ship; deferring breaks the per-week-extension convention.

### D234-Alt1: Library-only at Week 8

CLI deferred to Pillar I. **Rejected** — the per-week-extension convention ships the operator-readable surface with the library primitive.

### D234-Alt2: Per-register subcommand pattern

`score-cold-pitch` + `score-congrats` + etc. **Rejected** per ADR-0044 D224-Alt2 — argparse-choices is the framework convention.

### D234-Alt3: Chain into the `parse` subcommand

Extend `parse` to also emit `draft_quality_scored`. **Rejected** per D234's rationale — orthogonal gate verdicts; operators may want one without the other.

### D235-Alt1: Only `embed_fn`

Skip the new `retrieve_fn` seam. **Rejected** per D235's rationale — per-call dispatch tests need full retrieval bypass for cost amortization.

### D235-Alt2: Only `retrieve_fn`

Skip the inherited `embed_fn` seam. **Rejected** — breaks the ADR-0043 D218 + ADR-0044 D227 + ADR-0040 D197 + ADR-0039 D188 lineage.

### D235-Alt3: Single composite seam

A single `compute_fn` seam that substitutes at the result level. **Rejected** — operators substituting at the result level would bypass the construction-time invariants; the seams substitute at the COMPONENT level.

## Consequences

### Positive consequences

* **Pillar F Week 10 Layer 4 emit guard + Week 12 Layer 5 reconcile heal-pass gain the substrate.** Both downstream Layers consult `DraftFidelityResult.meets_threshold` + `state` alongside `DraftQualityResult.uncited_claims` + `state`; the per-draft gate becomes the SYMMETRIC two-dimensional verdict (hallucination-detection × voice-fidelity).
* **The third Pillar F event class ships.** `draft_quality_scored` joins `voice_exemplar_retrieved` (Week 2) + `hallucination_detected` (Week 6) at the cross-pillar audit's category 8 — Pillar G observability dashboards consume all three for per-register / per-channel / per-event-class aggregation.
* **The `voice.use_embedding_primitive` default flip closes the Week 2-7 transition window.** Operators with corpora ready inherit the new substrate; operators with legacy corpora keep the heuristic via explicit opt-out. The framework's NEW default IS the more-capable surface.
* **The TEST-ONLY `retrieve_fn` seam unblocks fast unit testing.** Per-call dispatch tests substitute fake exemplars without building temp corpora; the test suite's per-test cost stays bounded.
* **The Week 8 baseline rates motivate Pillar F Week 10+/12 calibration.** The `draft_quality_scored` event stream surfaces per-register score distributions; operators tune `~/.outreach-factory/voice_thresholds.yml` per their corpus's distribution (R024 + R028 mitigation).

### Negative consequences

* **Test count grows by ~71 tests post-follow-up** (TestDraftFidelityResult × 24 + TestComputeDraftFidelityScore × 20 + TestBuildDraftQualityScoredPayload × 11 + TestSeamPreservationWeek8 × 6 + TestCLIScore × 5 + TestWeek8ModuleSurface × 5). Cumulative: 3083 (post-Week-7-follow-up) → 3154 (post-Week-8-follow-up). The growth is bounded; per-test coverage is targeted at refuse-loud + per-register threshold consumption + the Layer 2 invariant + the event factory + the CLI. (Foundation commit shipped 68 tests; follow-up commit added 3 regression-barrier tests for the reviewer's P2-1 cell-coverage gap + P2-2 embed_fn behavioral passthrough + P3-1 all-None exemplar scores branch.)
* **`orchestrator/draft_quality.py` grows by ~700 LOC** (DraftFidelityResult dataclass + compute_draft_fidelity_score primitive + build_draft_quality_scored_payload event factory + _cmd_score CLI handler + main() extension + ~200 LOC of docstrings). The growth is intentional — the Week 8 primitive deserves co-location with the Week 6 + Week 7 primitives per D228.
* **A new event class lands at the ledger.** `draft_quality_scored` joins the per-event grep + jq operator workflow. Pillar G dashboard authors (per ADR-0038 §Downstream pillar impact's Pillar G note) consume the new event class for per-register score distribution rendering.
* **The `voice.use_embedding_primitive` default flip is operator-visible.** Operators reading the SKILL.md Phase 4 narrative see Path A as the new default + Path B as the legacy opt-out. The doc-sweep at Week 8 ensures the SKILL.md narrative matches the framework's new default.

### Risks

The asymmetric-failure-cost calculus carries:

* **R028 (per-register threshold mis-calibration) — new at Week 8.** Operators with materially different corpora may see the Week 4 defaults mis-calibrated; the `draft_quality_scored` event stream + Pillar G dashboards (deferred) surface the per-register score distributions for operator-side tuning. **Bounded by** the per-register threshold operator-tunability per ADR-0041 D199-D204 + the operator-deferred Pillar I per-tenant baseline measurement extension.

* **The empty-corpus refuse-loud's operator-friction surface (P3):** Operators flipping `voice.use_embedding_primitive: true` with an empty corpus see EVERY draft refused at `state="refused"` with `voice_fidelity_score=0.0`. **Bounded by** the operator-readable diagnostic in the CLI's `score` output ("the draft's voice-fidelity score is below the per-register threshold") + the SKILL.md Phase 4 narrative naming the empty-corpus opt-out posture + the §Existing-operator seed naming the operator-tagging trajectory.

* **The retrieve_fn seam's misuse (P3):** A future Pillar F contributor might tempt-pass `retrieve_fn=` in production to swap retrieval logic. **Bounded by** the docstring naming the seam as TEST-ONLY + the absence of a CLI surface for the kwarg + the Pillar I CLI tooling extension as the structured surface for advanced retrieval injection.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The Week 8 primitive emits `draft_quality_scored` events to the ledger; the per-draft fidelity score IS the per-event payload (not a separate denormalized store).
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The Week 8 primitive is upstream of the dispatcher.
* **I3 — Atomic per-Person enrollment.** Preserved. Week 8 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The `channel` field stamps every `draft_quality_scored` event.
* **I5 — Migration framework discipline.** Preserved. Week 8 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved + EXTENDED. The `draft_quality_scored` event class stamps `channel` per ADR-0014 D33's extension; the factory raises on unknown channel.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. The Week 8 primitive adds NEW refuse-loud surfaces: (a) `DraftFidelityResult.__post_init__` per-field validation (10+ checks: draft_hash prefix + register/channel/state closed-enum + score/threshold range + meets_threshold consistency + exemplar_ids tuple + per-item str + k int + non-negative + len<=k + ready+!meets refusal); (b) `compute_draft_fidelity_score` closed-enum on register + channel; (c) `build_draft_quality_scored_payload` closed-enum + channel/register mismatch with result; (d) CLI argparse-choices on `--register` + `--channel`; (e) CLI missing-draft-file refuse-loud. Mirrors the Week 6 `DraftQualityResult` strict-gate posture per ADR-0043 D213.
* **I8 — Privacy-respecting.** Preserved + EXTENDED. The `draft_quality_scored` event carries `draft_hash` (sha256:<hex>) NOT the raw draft body; the `exemplar_ids` list carries per-exemplar IDs only — per-exemplar bodies are NOT in the payload. Operators inspect bodies via the corpus directory directly; the ledger event is hash-and-ID only.

## Downstream pillar impact

* **Pillar F Week 10 (Layer 4 post-engine guard).** The Week 10 Layer 4 emit-refusal extension consults BOTH `DraftQualityResult` (hallucination-detection) AND `DraftFidelityResult` (voice-fidelity); the per-draft gate becomes the symmetric two-dimensional verdict. The Week 8 `compute_draft_fidelity_score` primitive's `state` field stays the Layer 2 substrate Week 10's Layer 4 emit guard consumes.

* **Pillar F Week 12 (Layer 5 reconcile heal-pass refusal).** The Week 12 Layer 5 reconcile Pass C refusal extension consults BOTH primitives' `state` fields via the linked `draft_quality_scored` + `hallucination_detected` events on the ledger. The Week 8 `voice_fidelity_score` + `meets_threshold` stamps are the per-event substrate Pass C reads against.

* **Pillar G (Observability).** Dashboards consume the `draft_quality_scored` event stream for per-register / per-channel / per-event-class aggregation. The per-register score distribution rendering (boxplot or histogram per register) reads against the stamped `voice_fidelity_score` field. Per-register threshold tuning (Pillar G "alert if per-register mean score drops X pp below baseline") consumes the per-event stream.

* **Pillar H (Real-time + scale).** The Week 8 primitive's per-call cost is bounded by the Week 2 retrieval primitive's per-call cost (~5-15ms for ~5K corpus). Pillar H optimizations (sparse indexing; pre-filter-aware partition; per-corpus shard) extend the retrieval primitive; the Week 8 fidelity-scoring primitive is content-additive against the Pillar H optimizations.

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions MAY extend with `draft_quality fidelity-baseline --corpus-dir <path>` (per-tenant per-register baseline measurement) IF operator demand materializes. The Week 8 CLI's `score` subcommand accepts per-tenant `--thresholds-path` for per-tenant threshold consultation.

* **Pillar J (Compliance + audit).** Per-tenant GDPR-purge does not touch the `draft_quality_scored` event class beyond the existing per-Person purge path (the event carries `person_id` for the per-Person filter). The per-event `draft_hash` is operator-deliberate sha256 hash (NOT PII); per-event `exemplar_ids` are corpus-internal IDs (NOT PII).

## Migration / rollout

**Week 8 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 7 to Pillar F Week 8:

1. **Operator updates the framework** to Pillar F Week 8's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 8 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_draft_quality.py -v`** to verify the new fidelity-scoring tests pass. Optional but recommended.
4. **Operator decides whether to opt OUT of the new primitive's default-on posture.** Two paths:
   * **Path A (recommended for tagged corpora):** Keep `voice.use_embedding_primitive: true` (the new framework default). The SKILL.md Phase 4 dispatches to the new primitive; Phase 5 runs both the hallucination-detection gate (Week 6) + the voice-fidelity gate (Week 8).
   * **Path B (operator-deferred for legacy corpora):** Set `voice.use_embedding_primitive: false` in `~/.outreach-factory/config.yml`. The SKILL.md Phase 4 dispatches to `voice_retrieve.py` (legacy heuristic); the Week 8 voice-fidelity gate stays inactive (the gate consumes the new primitive's substrate).
5. **Operator MAY measure per-register baselines against THEIR corpus.** Two paths:
   * **Path A (framework default):** Use the Week 4 default thresholds + score per-draft via `python orchestrator/draft_quality.py score --draft-path <path> --register R --channel C --json`.
   * **Path B (operator-curated):** Tune `~/.outreach-factory/voice_thresholds.yml` per per-register score distributions observed via the `draft_quality_scored` event stream.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 9 is open scope per the per-week author's call. Week 10 ships Layer 4 emit-refusal; may extend `ledger/0008_draft_quality_scored_index` for per-event indexing (TBD per the per-week design). Week 12 ships Layer 5 reconcile heal-pass refusal + the binding exit-criterion test un-skips.

## Existing-operator seed

**Pillar F Week 8's operator-side disposition is the load-bearing transition** per ADR-0039 §Existing-operator seed's Week 8+ trajectory. The framework default flips; operators with tagged corpora inherit the new primitive automatically.

The operator-side trajectory (per-week ships across Pillar F Weeks 8-12):

* **Week 8 (this commit):** The fidelity-scoring primitive lands + the `voice.use_embedding_primitive` config default flips to `true`. SKILL.md Phase 4 narrative updates so Path A (new primitive) is the default + Path B (legacy heuristic) is the explicit opt-out. SKILL.md Phase 5 extends with the per-register voice-fidelity gate.
* **Week 9 (operator-deferred scope):** Open per the per-week author's call. May extend with operator-deferred surfaces (per-corpus baseline measurement; Pillar I CLI tooling; per-event observability dashboards).
* **Week 10:** Layer 4 post-engine guard ships per ADR-0038 D180. The `draft_ready` event emit refuses-loud when EITHER `uncited_claims` non-empty OR `meets_threshold=False`. SKILL.md Phase 6 extends.
* **Week 12:** Layer 5 reconcile Pass C heal-pass refusal ships; the binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 8:** review `~/.outreach-factory/config.yml`. Operators with corpora not yet tagged with `register` + `channel` per ADR-0038 D178 set `voice.use_embedding_primitive: false` explicitly (else the new primitive's per-call retrieval refuses-loud on missing tags per ADR-0039 D188's refuse-loud-on-unknown-register surface).

**Operator action recommended at Week 8:** tag the corpus + flip to Path A. The §Migration/rollout Path A is the recommended posture — operators benefit from per-register threshold consumption + the per-draft voice-fidelity gate immediately.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D184(a) (voice-fidelity score is per-register operator-tunable; per-draft float in `[0.0, 1.0]` = cosine similarity weighted average over top-K corpus exemplars) is THE binding text Week 8 implements. D182 (`draft_quality_scored` event class) is THE third Pillar F event class the Week 8 factory builds.
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive. D188 (`retrieve_voice_exemplars` per-call entry point with TEST-ONLY embed_fn seam) is THE substrate Week 8's `compute_draft_fidelity_score` consumes. §Existing-operator seed's Week 8+ transition pin (default flip from `false` → `true`) is the operator-side trajectory Week 8's D232 lands.
- **ADR-0040 (D192-D198)** — Pillar F Week 3 per-register adapters. D196 (per-register `is_substantive_reply` bias) is the per-register-symmetry pattern the Week 8 primitive consumes via the `is_substantive_reply` kwarg passthrough.
- **ADR-0041 (D199-D205)** — Pillar F Week 4 per-register threshold infrastructure. D204 (`get_voice_threshold_for_register`) is THE substrate Week 8's `compute_draft_fidelity_score` consumes for the per-register threshold comparison. D201 (range validation + bool catch) is the STRUCTURAL reference for `DraftFidelityResult.__post_init__`'s bool-catch per D229.
- **ADR-0042 (D206-D211)** — Pillar F Week 5 voice-thresholds CLI extension. D210 (argparse-choices closed-enum at CLI) is the STRUCTURAL reference for the CLI's `--register` + `--channel` argparse-choices per D234.
- **ADR-0043 (D212-D219)** — Pillar F Week 6 hallucination-detection Layer 2-3 primitive. D213 (`DraftQualityResult` Layer 2 invariants) is the SYMMETRIC reference for the Week 8 `DraftFidelityResult` Layer 2 invariants per D229. D216 (event factory's channel/register-mismatch refuse-loud per Week 6 follow-up P2-2) is the STRUCTURAL reference for D231's factory mismatch refuse. D218 (TEST-ONLY embed_fn seam) is the LINEAGE the Week 8 D235's two-seam preservation continues. D219 (emit-only-on-uncited posture for `hallucination_detected`) is the CONTRAST against D231's emit-always posture for `draft_quality_scored`.
- **ADR-0044 (D220-D227)** — Pillar F Week 7 per-claim-type corpora + measurement primitive. D220 (extend `orchestrator/draft_quality.py` rather than new sibling) is the PRECEDENT for D228's module placement decision. D227 (TEST-ONLY embed_fn seam preservation at measurement primitive surface) is the LINEAGE D235 continues.
- **ADR-0014 (D33)** — Pillar C foundation. The channel-on-every-event invariant extends to the `draft_quality_scored` event class per D231.
- **ADR-0010 (D17)** — Per-event `_emitted_by` marker. The Week 8 event factory stamps `_emitted_by="draft_quality"` (same module emits both `hallucination_detected` + `draft_quality_scored`).
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §45+ extends with the Week 8 commit's audit verdict (the fidelity-scoring primitive's public surface + the event factory + the CLI extension + the SKILL.md Phase 4 + Phase 5 narrative changes + the `voice.use_embedding_primitive` default flip + the SOURCES-OF-TRUTH row update if any).
- **`.planning/HANDOFF-pillar-f-week-8.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 9 trajectory.
- **`orchestrator/draft_quality.py`** — extended with `DraftFidelityResult` + `compute_draft_fidelity_score` + `build_draft_quality_scored_payload` + `_cmd_score` per D228-D234.
- **`config-template/config.example.yml`** — `voice.use_embedding_primitive` default flipped to `true` per D232.
- **`skills/draft-outreach/SKILL.md`** — Phase 4 + Phase 5 extended per D233.
- **`tests/test_draft_quality.py`** — extended with `TestDraftFidelityResult` × 24 + `TestComputeDraftFidelityScore` × 20 + `TestBuildDraftQualityScoredPayload` × 11 + `TestSeamPreservationWeek8` × 6 + `TestCLIScore` × 5 + `TestWeek8ModuleSurface` × 5 = ~71 new tests covering D228-D235 (post-follow-up).
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 8 close summary.
- **`docs/adr/README.md`** — ADR-0045 row appended.
- **`docs/RISK-REGISTER.md`** — R028 (per-register threshold mis-calibration) row appended.
