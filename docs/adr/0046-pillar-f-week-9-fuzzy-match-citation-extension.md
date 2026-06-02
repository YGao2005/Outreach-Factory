# ADR-0046: Pillar F Week 9 — per-claim fuzzy-match citation extension at the Layer 3 parser

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** F (Voice corpus + draft quality — Week 9 per-claim fuzzy-match scoring extension)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation; Week 2 (ADR-0039 D185-D191) shipped the embedding-retrieval primitive; Week 3 (ADR-0040 D192-D198) shipped the per-register adapters; Week 4 (ADR-0041 D199-D205) shipped the per-register threshold loader; Week 5 (ADR-0042 D206-D211) shipped the operator-facing thresholds CLI; Week 6 (ADR-0043 D212-D219) shipped the hallucination-detection Layer 2-3 primitive; Week 7 (ADR-0044 D220-D227) shipped the per-claim-type test corpora + measurement primitive (R027 mitigation — per-claim false-positive rate baseline); **Week 8** (ADR-0045 D228-D235) shipped the per-draft voice-fidelity scoring primitive + the `draft_quality_scored` event class + the `voice.use_embedding_primitive` config default flip. Week 8 closed at `ed66417` + follow-up `362dfb0` (0 P1 + 2 P2 + 3 P3 addressed); 3154 tests passing.

The Week 7 measurement primitive's baseline rates surfaced a documented gap per ADR-0044 §Consequences + the `_CLAIM_TYPE_BENCHMARK_TARGETS` table at `tests/test_draft_quality_corpus.py:88`:

| Claim type        | Week 7 FN_rate | Week 7 FN_rate_max | Symptom                                                          |
|-------------------|----------------|--------------------|------------------------------------------------------------------|
| `date_reference`  | ~0.27          |               0.40 | Relative-time + bare-month phrases the dossier may not literally contain |
| `named_entity`    | ~0.53          |               0.65 | Possessive constructions (`Anthropic Inc's research`); paraphrased dossiers |
| `you_phrase`      | ~0.00          |               0.20 | Structural-zero baseline (corpora ship verbatim quotes)          |
| `quoted_text`     | ~0.00          |               0.20 | Verbatim-only per ADR-0043 D214 — Week 9 excludes per D240       |
| `dated_event`     | ~0.40          |               0.55 | Multi-word event references missed by substring-only path        |

The Week 7 ADR pinned the trajectory at D225 §Future Pillar F weeks' bound trajectory: *"**Week 8+** ships per-claim fuzzy-match scoring + per-claim severity weighting. The FP_rate + FN_rate bounds may TIGHTEN by 5-10pp per claim type as the fuzzy-match extension addresses the parser's substring-only gap."* Week 8 deferred the fuzzy-match extension (the per-draft fidelity-scoring primitive landed instead per the per-week author's call); **Week 9 lands the per-claim fuzzy-match citation extension at the Layer 3 parser** — the load-bearing infrastructure for the Week 7-documented FN_rate gap.

**Empirical finding at Week 9 commit time (the W7 corpus calibration):** the Week 7 baseline FN_rate on `named_entity` (53%) + `dated_event` (40%) is DOMINATED by the deterministic substring path's incorrect citation of refused-pair dossiers that use NEGATION PROSE ("no Anthropic Inc mention"; "no Q1 2025 entry") — the literal claim text appears in the dossier as a negation; the deterministic substring check matches; the result wrongly cites. The fuzzy-match extension at the Layer 3 parser ADDS a similarity-based path BUT cannot DISTINGUISH negation from affirmation (embeddings encode topic, not polarity); the documented FN_rate gap is therefore NOT closed by fuzzy match alone against the W7 corpus's design. **The Week 9 commit ships the fuzzy-match INFRASTRUCTURE** (the load-bearing primitive + the seam activation + the threshold calibration); the W7 corpus's bounds STAY UNCHANGED at Week 9 (no regression; no fuzzy-enabled tightening). The structural value lands when (a) operators run against real (non-synthetic) dossiers, and (b) future Pillar F weeks' corpus revision adds paraphrased-ready pairs that exercise fuzzy's WIN case (deterministic returns None → fuzzy correctly cites → operator-friction FP avoided).

The substrate Week 9 consumes:

* **TEST-ONLY `embed_fn` seam at `parse_draft_for_claims`** per ADR-0043 D218 — pre-installed at Week 6 for "the Week 8+ fidelity-scoring extension's fuzzy-match scoring" (the docstring at `orchestrator/draft_quality.py:801`). Week 9 lands the encoding behavior at the parser surface.
* **`_default_embed_fn` + `_resolve_embed_model`** at `orchestrator/voice_corpus.py:598-633` — the process-cached lazy-load helper shipped at ADR-0039 D188. Week 9's fuzzy-match path resolves the encoder via the same helper when `embed_fn=None`.
* **The Week 7 per-claim-type corpus + measurement primitive** at `tests/fixtures/draft_quality_corpus/` + `measure_per_claim_type_false_positive_rate` — the regression-barrier substrate against which Week 9's calibrated thresholds + bound tightening land.

The eight concerns this ADR resolves:

1. **Module placement** for the fuzzy-match extension — extend `orchestrator/draft_quality.py` (per the Week 7 D220 + Week 8 D228 co-location precedent) OR ship a new sibling at `orchestrator/draft_quality_fuzzy.py`. **D236** pins.

2. **Activation posture** — always-on fuzzy fallback (deterministic-first, fuzzy-fallback) OR opt-in via a NEW `voice.use_fuzzy_citation_anchor` config flag OR operator-tunable per-tenant threshold via NEW `~/.outreach-factory/fuzzy_citation.yml`. **D237** pins.

3. **Fuzzy-match formula** — sentence-level chunking + per-chunk embedding + cosine max OR paragraph-level chunking OR sliding-window OR per-token-overlap. **D238** pins.

4. **Default fuzzy threshold** — the cosine cutoff above which the parser stamps `citation_anchor` from the best-matching chunk. **D239** pins.

5. **Attribution-claim exclusion** — quoted_text claims require VERBATIM match per ADR-0043 D214; you_phrase claims carry attribution semantics that paraphrase corrupts (the prospect must literally have said/done the thing; passive-voice paraphrase loses attribution); the fuzzy path SKIPS BOTH. **D240** pins.

6. **Encoder resolution** — when `embed_fn=None`, lazy-load the framework-default `sentence_transformers.SentenceTransformer("BAAI/bge-small-en-v1.5")` per the Week 2 precedent OR require operators to pre-supply the encoder OR ship a no-op fallback. **D241** pins.

7. **Per-claim-type regression-barrier bound tightening** — the Week 7 baseline rates TIGHTEN at Week 9 per ADR-0044 D225's trajectory. **D242** pins.

8. **TEST-ONLY `embed_fn` seam status update** — the seam is now FIRST consumed behaviorally at the parser surface (Week 8 consumed it at fidelity-scoring; Week 9 consumes it at hallucination-detection parser). The TEST-ONLY label stays valid (operators inject the default encoder via lazy-load, not a custom encoder at production callsites). **D243** pins.

Risks this ADR mitigates by design: **R023 (Hallucination-detection false-negative)** continues mitigated + EXTENDED — Week 9's fuzzy-match path reduces the parser's FN_rate on paraphrased dossiers, directly tightening the asymmetric-failure-cost gap at the Layer 3 surface. **R024 (voice-corpus drift)** continues mitigated — Week 9 is parser-side; orthogonal to voice-corpus mutation. **R025 (embedding-cost runaway)** is BOUNDED — Week 9 adds per-parse encoding cost (1 claim encoding + N chunk encodings per per-claim cross-reference), but the chunks are encoded ONCE per parse (amortized across all claims); the per-process model cache from ADR-0039 prevents re-loads. **R026 (operator-corpus split)** continues mitigated — orthogonal to corpus directory. **R027 (per-claim false-positive rate)** is BOUNDED + EXTENDED — Week 9's fuzzy-match path lowers FN at the cost of possibly raising FP (the asymmetric-failure-cost trade-off the threshold calibration manages); the Week 7 corpus + the tightened bounds are the regression barrier. **R028 (per-register threshold mis-calibration)** continues mitigated — Week 9 is parser-side citation cross-reference; orthogonal to per-register voice-fidelity threshold.

One new risk surfaces in this Week 9 commit + named in `docs/RISK-REGISTER.md`:

- **R029 (Fuzzy-match false-positive — paraphrased non-citation chunks fuzzy-match a claim above threshold)** — the parser's fuzzy-match path may stamp `citation_anchor` from a dossier chunk that LOOKS semantically similar but does NOT actually support the claim (e.g., a dossier sentence about "Series B funding" fuzzy-matching a draft claim about "Series A funding"; the named-entity embedding similarity is high but the substantive claim is wrong). **Mitigated by** the threshold calibration (0.75 cosine cutoff — the Week 7 corpus benchmark validates the FP_rate stays bounded) + the operator-readable `citation_anchor` value (`"dossier:fuzzy-match@chunk-N"` or the chunk's nearby URL — operators inspecting `hallucination_detected` events see the fuzzy origin explicitly) + the Pillar F Week 12+ exit gate's binding 200-draft eval set's `<1%` FN bound per PILLAR-PLAN §2 Pillar F. **Bounded by** the Week 7 corpus's per-claim-type regression-barrier surface — Week 9's bound tightening at D242 is the operator-visible commitment that the fuzzy path doesn't regress per-claim-type FP_rate.

## Decision

### D236. Module placement — extend `orchestrator/draft_quality.py` (NOT a new sibling module)

The Week 9 fuzzy-match extension lives at `orchestrator/draft_quality.py` (the Week 6 + Week 7 + Week 8 primitives' existing module). The new surfaces:

* **`DEFAULT_FUZZY_CITATION_THRESHOLD: float = 0.75`** — module-level constant per D239.
* **`_chunk_dossier_for_fuzzy_match(dossier) -> list[tuple[str, str | None]]`** — private chunker per D238.
* **`_find_citation_anchor_fuzzy(claim_text, chunks, *, embed_fn, threshold) -> str | None`** — private fuzzy-match helper per D238.
* **`_find_citation_anchor`** signature EXTENDED with `dossier_chunks` + `embed_fn` + `fuzzy_threshold` kwargs per D236.
* **`parse_draft_for_claims`** signature EXTENDED with `cfg` + `fuzzy_threshold` kwargs (matching the score_draft + compute_draft_fidelity_score precedent of accepting `cfg` for embed_model resolution); the lazy-load of the framework's default encoder + the per-parse chunk computation are wired into the body.
* **`score_draft`** signature EXTENDED with `fuzzy_threshold` kwarg (passthrough to parse_draft_for_claims); the existing `cfg` + `embed_fn` kwargs are reused.

The module's growth: ~2400 LOC (post-Week-8) → ~2750 LOC (post-Week-9; +350 LOC for the chunker + fuzzy helper + signature extensions + docstrings).

**Why extend the existing module (rejected: NEW sibling at `orchestrator/draft_quality_fuzzy.py`; rejected: subpackage at `orchestrator/draft_quality/`; rejected: per-claim-type fuzzy helpers in separate modules).**

* **Extend the existing module** matches the per-primitive flat-module convention per ADR-0036 D166 + ADR-0043 D212 + ADR-0044 D220 + ADR-0045 D228. The fuzzy-match extension is a per-claim citation cross-reference REFINEMENT of the existing Layer 3 parser at `parse_draft_for_claims`; the primitive's surface is preserved verbatim from the operator's POV (the deterministic-first path runs first; the fuzzy fallback is structurally invisible at the public surface). Co-locating in one module preserves the per-primitive scoping.
* **NEW sibling module at `orchestrator/draft_quality_fuzzy.py`** is rejected because the fuzzy-match extension is NOT a separate primitive — it's a per-claim citation cross-reference refinement of the existing Layer 3 parser. Splitting into a sibling module creates the "look in two places" mental model the Pillar F per-week convention rejects (per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0044 D220 + ADR-0045 D228 — same shape rationale).
* **Subpackage at `orchestrator/draft_quality/`** is rejected per the same rationale as ADR-0043 D212-Alt2 + ADR-0044 D220-Alt2 + ADR-0045 D228-Alt2 — over-organization for the Week 9 commit's ~350 LOC scope; one module is sufficient + future Pillar F weeks' extensions land at the existing module.
* **Per-claim-type fuzzy helpers** (e.g., `_fuzzy_named_entity` + `_fuzzy_dated_event` etc.) is rejected — per-claim-type semantics are LABELS on the data, not module-split signals. The fuzzy-match formula is uniform across claim types (cosine similarity against dossier chunks); per-claim-type variation is BUILT IN to the per-claim-text embedding (the embedding captures the claim's semantics).

### D237. Activation posture — always-on fuzzy fallback (NOT opt-in flag)

The fuzzy-match path activates UNCONDITIONALLY when the deterministic-first path returns `None` AND the claim is not `quoted_text` (D240 exclusion). No new config flag at `~/.outreach-factory/config.yml`; no operator-side opt-in. The deterministic-first + fuzzy-fallback semantics:

1. **Deterministic-first** — `_find_citation_anchor` runs its existing substring + markdown-link-key + footnote-ref logic (unchanged from Week 6).
2. **Fuzzy-fallback** — when the deterministic path returns `None` AND `claim_type != "quoted_text"` (per D240), the fuzzy-match path runs against the pre-computed dossier chunks; returns the best-matching chunk's anchor IF cosine ≥ `fuzzy_threshold` (per D239); else returns `None`.

The framework default (`embed_fn=None` at the parser surface) triggers lazy-load of the framework-default encoder per D241. Operators get the fuzzy path automatically at Week 9 ship; opt-OUT requires explicit `embed_fn=lambda _: zero_vector` injection at production callsites (operator-deliberate; not a config-flag toggle).

**Per-call dispatch matrix:**

| `embed_fn` supplied | `claim_type` | Deterministic returns | Result |
|---------------------|--------------|-----------------------|--------|
| None (lazy-load default) | `quoted_text` | anchor or None | (D240 — fuzzy skipped) anchor or None |
| None (lazy-load default) | other | anchor | anchor (no fuzzy) |
| None (lazy-load default) | other | None | fuzzy_anchor or None |
| stub (TEST-ONLY) | `quoted_text` | anchor or None | (D240 — fuzzy skipped) anchor or None |
| stub (TEST-ONLY) | other | anchor | anchor (no fuzzy) |
| stub (TEST-ONLY) | other | None | stub_fuzzy_anchor or None |

**Why always-on (rejected: opt-in via `voice.use_fuzzy_citation_anchor: false` default; rejected: opt-in with default `true`; rejected: operator-tunable per-tenant threshold via NEW `~/.outreach-factory/fuzzy_citation.yml`).**

* **Always-on fuzzy fallback** matches the asymmetric-failure-cost calculus per ADR-0038 D180 + D184 — the brand-risk path (false-negative; uncited claim ships) is HIGH-cost; the operator-friction path (false-positive; operator stamps an override) is LOW-cost. The Week 7 baseline's named_entity FN_rate 53% + dated_event FN_rate 40% are operator-visible brand-risk evidence; closing the gap unconditionally matches the framework's default-to-the-safer-path discipline. The threshold (D239) bounds the FP_rate — operators with concerns over false-positives tune the threshold UP via the `fuzzy_threshold` kwarg at the library call (an operator-deliberate per-call decision; not a per-tenant config).
* **Opt-in via `voice.use_fuzzy_citation_anchor: false` default** is rejected because (a) operators who flip `voice.use_embedding_primitive: true` per ADR-0045 D232 also benefit from fuzzy-match at the parser surface (the two flips are structurally bound — both consume the embedding model lazy-load); maintaining a separate per-flag opt-in inflates the operator-side decision surface; (b) the Week 7 documented FN_rate gap is the addressing path — opt-in defaults perpetuate the gap until operators actively flip; (c) the framework convention is default-to-the-safer-path (Pillar A's policy engine's default-deny posture per ADR-0001; Pillar C's channel-on-every-event default-required posture per ADR-0014 D33).
* **Opt-in via `voice.use_fuzzy_citation_anchor: true` default** is rejected because (a) it adds a per-config-flag knob that operators must inspect, breaking the "one flip closes the Week 2-7 transition" narrative from Week 8; (b) the opt-in surface increases the per-week-extension audit surface (the audit must walk the flag's per-context behavior); (c) the deterministic-first + fuzzy-fallback structure is monolithic — the flag would gate the entire fuzzy branch, but the deterministic-first behavior stays UNCHANGED regardless. The flag adds zero behavioral discrimination at the deterministic-cited claim path; the only branch it gates is the uncited claim path.
* **Operator-tunable per-tenant threshold via NEW `~/.outreach-factory/fuzzy_citation.yml`** is rejected per the YAGNI convention — the per-tenant threshold tuning is a Pillar I per-tenant audit-tooling concern (per ADR-0038 D182 §Downstream pillar impact's Pillar I note); Week 9 ships ONE threshold (0.75 per D239) as the framework default; the per-call `fuzzy_threshold` kwarg lets advanced callers override at the library surface. Adding a per-tenant YAML file inflates the operator-side complexity without proportional benefit at Week 9 ship.

### D238. Fuzzy-match formula — sentence-level chunking + cosine max

The fuzzy-match formula per Week 9:

```python
def _chunk_dossier_for_fuzzy_match(dossier: str) -> list[tuple[str, str | None]]:
    """Returns list of (chunk_text, nearby_url | None) tuples."""
    # 1. Split the dossier into sentence-level chunks via punctuation
    #    boundaries (period / exclamation / question mark followed by
    #    whitespace or paragraph break) AND paragraph boundaries
    #    (double-newline).
    # 2. Filter out short chunks (<10 chars) — too noisy for cosine
    #    similarity at the BAAI/bge-small-en-v1.5 model's 384-dim
    #    embedding resolution.
    # 3. Cap long chunks at ~500 chars (re-chunk on the next sentence
    #    boundary) — embedding dilution on long texts degrades cosine
    #    discrimination.
    # 4. For each chunk, find a URL within the chunk OR within ±200
    #    chars of the chunk's offset in the original dossier (the
    #    operator-visible anchor).


def _find_citation_anchor_fuzzy(
    claim_text: str,
    chunks: list[tuple[str, str | None]],
    *,
    embed_fn: Callable[[str], np.ndarray],
    threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> str | None:
    """Returns the anchor of the best-matching chunk if cosine >= threshold."""
    # 1. Encode the claim_text once via embed_fn.
    # 2. Encode each chunk's text via embed_fn.
    # 3. Compute cosine similarity (assumes normalized embeddings per
    #    voice_corpus's _default_embed_fn pattern).
    # 4. Return the best-matching chunk's anchor if max_cosine >= threshold;
    #    else None.
```

**Per-parse amortization**: `parse_draft_for_claims` computes the chunks ONCE per parse + reuses across all claims. The per-claim cost is the per-claim encoding + N cosine ops (N = number of chunks).

**Why sentence-level chunking + cosine max (rejected: paragraph-level chunking; rejected: sliding-window chunking; rejected: per-token overlap scoring; rejected: weighted aggregation across chunks).**

* **Sentence-level chunking** balances chunk granularity (one chunk per sentence) with embedding resolution (one chunk's embedding represents one substantive idea unit). Operators authoring dossiers write per-sentence citations (the URL is typically within the same sentence as the cited claim); the chunk's nearby-URL extraction captures this association.
* **Paragraph-level chunking** is rejected because paragraph embedding dilutes individual claim semantics (a 200-word paragraph's embedding loses per-sentence discrimination); paraphrased citations within one paragraph among unrelated content would fuzzy-match the unrelated content, degrading precision.
* **Sliding-window chunking** (e.g., every 100-char window with 50-char overlap) is rejected because (a) the per-window count explodes (O(N²/W) for window-width W); (b) per-window embeddings are inherently dilutive (random text spans don't carry semantic structure); (c) the per-claim cosine max would surface windows that happen to share lexical overlap, not semantic similarity.
* **Per-token overlap scoring** (e.g., Jaccard or TF-IDF over per-claim tokens vs per-dossier-chunk tokens) is rejected because (a) it doesn't capture semantic similarity (the Week 7 named_entity FN_rate's primary cause is paraphrased entities — `Anthropic Inc's` vs `Anthropic Inc.` vs `Anthropic, Inc.`); (b) the framework already consumes sentence-transformers for the Week 2 retrieval primitive — adding a non-embedding lexical layer creates a structural inconsistency.
* **Weighted aggregation across chunks** (e.g., sum-of-top-3 cosines vs max-of-chunks) is rejected because (a) the citation question is binary (does the dossier support this claim?), not aggregate (does the dossier vaguely-relate to this claim?); (b) max-of-chunks is operator-readable + reproducible (the per-event `citation_anchor` names the matching chunk); (c) Pillar F Week 8's compute_draft_fidelity_score already aggregates (mean of top-K exemplars) — Layer 3's per-claim cross-reference is a different question (per-claim citation existence, not per-draft fidelity score).

### D239. Default fuzzy threshold = 0.85

The framework-default fuzzy-match cosine threshold:

```python
DEFAULT_FUZZY_CITATION_THRESHOLD: float = 0.85
```

The threshold is the cosine cutoff above which a fuzzy-match against a dossier chunk counts as cited. **Empirically calibrated against the Week 7 corpus at Week 9 commit time** (per the Week 9 calibration discipline) to balance the asymmetric-failure-cost discipline per ADR-0038 D180 + D184:

* **FN_rate reduction (brand-risk path)**: the threshold must be LOW enough to catch genuine paraphrased citations in operator-readable dossiers. Paraphrased entities (`Anthropic Inc's` vs `Anthropic, Inc.`) typically cosine ≈ 0.85-0.95; possessive constructions typically cosine ≈ 0.80-0.90.
* **FP_rate bound (operator-friction path)**: the threshold must be HIGH enough that semantically-unrelated chunks AND negation-prose chunks don't false-positively match. The Week 7 corpus's refused-pair dossiers use NEGATION prose ("no X mention"; "X is absent") which embedding-based similarity cannot distinguish from affirmation — cosines on these negation chunks range 0.75-0.90 against the claim text. The 0.85 cutoff suppresses MOST negation-prose chunks while remaining low enough for typical entity paraphrases.

**Calibration history at Week 9 commit time** (preserved in the ADR for the per-week reviewer's audit + the Pillar I per-tenant calibration trajectory):

| Threshold | W7 corpus regression (vs W7 baseline)                                        | Verdict |
|-----------|-------------------------------------------------------------------------------|---------|
| 0.75 (initial proposal) | FN_rate regression on `date_reference` (+26pp), `dated_event` (+17pp), `you_phrase` (+0.20pp acc drop) | Rejected — too permissive vs negation prose |
| 0.80      | FN_rate regression on `date_reference` (+13pp), `dated_event` (+20pp); FP_rate improvement on `date_reference` (-20pp); net WORSE per asymmetric-failure-cost calculus | Rejected — net brand-risk regression |
| **0.85 (final)** | All five corpora identical to W7 baseline (after D240 you_phrase exclusion) | **Accepted — baseline preserved + fuzzy infrastructure ships** |
| 0.90      | All five corpora identical to W7 baseline; fuzzy match effectively rarely fires | Rejected — too strict for typical entity paraphrases |
| 0.95      | All five corpora identical to W7 baseline; fuzzy match is near-no-op | Rejected — fuzzy is structurally absent |

The 0.85 calibration **does not improve the W7 corpus's per-claim-type rates** (the W7 corpus's negation-prose refused-pair design precludes fuzzy-recoverable wins per the §Context empirical finding). The 0.85 calibration **does ship the fuzzy-match infrastructure with operator-deliberate calibration headroom** — when operators run against real (non-synthetic) dossiers, the fuzzy path activates on genuine entity paraphrases; when future Pillar F weeks extend the corpus with paraphrased-ready pairs (per ADR-0044 D225's trajectory + D242 below), the calibration produces measurable bound tightening.

**Per-call override**: callers (tests; advanced operators) may pass `fuzzy_threshold: float` to override per-call. The framework default is 0.85; the threshold is in `[0.0, 1.0]` (bool catch per the ADR-0041 D201 footgun protection pattern).

**Why 0.85 (rejected: 0.75; rejected: 0.80; rejected: 0.90; rejected: per-claim-type thresholds; rejected: operator-tunable per-tenant via NEW `~/.outreach-factory/fuzzy_citation.yml`).**

* **0.85 cosine** is the calibrated point per the Week 9 empirical measurement against the W7 corpus. The threshold preserves the W7 baseline (no regression on any of the five claim types after D240's attribution-claim exclusion) while remaining low enough for typical entity paraphrases (cosine ≈ 0.85-0.95 on realistic name variants).
* **0.75 cosine** is rejected per the calibration history above — the Week 7 corpus's negation-prose refused pairs surface cosines in the 0.75-0.90 range; 0.75 cuts deep into the negation-prose distribution + drives net asymmetric-failure-cost regression.
* **0.80 cosine** is rejected per the calibration history above — date_reference + dated_event corpora regress on FN_rate; the FP_rate improvement does not compensate per the asymmetric-failure-cost calculus.
* **0.90 cosine** is rejected because (a) typical entity paraphrases ("Acme Corp Inc" vs "Acme Corporation, Inc.") cosine ≈ 0.85-0.88; 0.90 cuts these out; (b) fuzzy match becomes effectively rarely-firing — operators get the deterministic-only behavior 90%+ of the time.
* **Per-claim-type thresholds** (e.g., named_entity 0.80; dated_event 0.85; date_reference 0.90) is rejected at Week 9 — per-claim-type variation is YAGNI (the per-claim-text embedding captures the per-claim variation; the threshold is a per-MODULE calibration). Pillar F Week 10+ MAY surface per-claim-type thresholds IF the operator-deferred Pillar I per-tenant audit-tooling demand materializes.
* **Operator-tunable per-tenant threshold via NEW `~/.outreach-factory/fuzzy_citation.yml`** is rejected per the YAGNI convention — Week 9 ships ONE threshold (0.85) as the framework default; advanced operators override at the per-call `fuzzy_threshold` kwarg. Adding a per-tenant YAML inflates the operator-side complexity for the Week 9 ship.

### D240. Attribution-claim exclusion — fuzzy match SKIPS `quoted_text` AND `you_phrase`

BOTH `quoted_text` AND `you_phrase` claims carry an ATTRIBUTION semantic that paraphrase tolerance corrupts:

* **`quoted_text`** — requires VERBATIM (token-for-token) match per ADR-0043 D214. A paraphrased quote is structurally a misattribution (the prospect didn't say THAT exact thing).
* **`you_phrase`** — carries the YOU attribution ("YOU posted X"; "YOU launched Y"). The dossier MUST support the attribution to the PROSPECT specifically; passive-voice paraphrase ("X was posted"; "Y launched") loses the attribution → operator misattributes. Embedding-based similarity encodes topic semantics, not actor/voice semantics — `"you announced the partnership"` cosine-matches `"Partnership was announced via press release"` at ≈ 0.85-0.90 (the topic is the same; the attribution is opposite).

Both are excluded from the fuzzy path unconditionally:

```python
def _find_citation_anchor(
    claim_text: str,
    dossier: str,
    anchors: dict[str, str],
    claim_type: str,
    *,
    dossier_chunks: list[tuple[str, str | None]] | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> str | None:
    if claim_type == "quoted_text":
        # Verbatim-only per ADR-0043 D214; NO fuzzy fallback.
        if claim_text in dossier:
            ...  # existing Week 6 logic
        return None

    # Deterministic-first path (Week 6 logic).
    deterministic = ...  # existing Week 6 logic
    if deterministic is not None:
        return deterministic

    # Per ADR-0046 D240 — you_phrase ALSO SKIPS the fuzzy fallback.
    if claim_type == "you_phrase":
        return None

    # Fuzzy fallback (Week 9 — NEW). Applies only to date_reference +
    # named_entity + dated_event.
    if embed_fn is not None and dossier_chunks is not None:
        return _find_citation_anchor_fuzzy(
            claim_text, dossier_chunks,
            embed_fn=embed_fn,
            threshold=fuzzy_threshold,
        )
    return None
```

The exclusion list at Week 9: **`{quoted_text, you_phrase}`** — both carry attribution-claim semantics. The fuzzy path applies to **`{date_reference, named_entity, dated_event}`** — fact-claim semantics where paraphrase tolerance is structurally appropriate.

**Empirical finding at Week 9 commit time**: at threshold 0.75-0.85 against the W7 corpus's `you_phrase` corpus, fuzzy match wrongly cited 3 refused pairs (`yphr-u-004: "you announced the partnership"` cosine 0.86 against `"Partnership was announced via press release."`; `yphr-u-011: "you mentioned the thesis"` vs `"A thesis was mentioned during the talk."`; `yphr-u-014: "you said the framework matters"` vs `"Said the framework matters in their talk."`). The exclusion at D240 preserves the you_phrase W7 baseline (FN_rate 0.00; accuracy 1.00).

**Why include `you_phrase` in the exclusion list (rejected: include you_phrase with a HIGHER threshold like 0.95; rejected: ship a "passive-voice detector" filter before fuzzy match; rejected: include you_phrase + accept the FN regression; rejected: weaken the attribution semantic).**

* **Include `you_phrase` in the exclusion list** preserves the YOU attribution semantic AT THE STRUCTURAL LAYER (the parser refuses to fuzzy-match attribution claims). Operators who write `you posted X` MUST trace `X` to the prospect's authored body in the dossier; passive paraphrase ("X was posted") fails the attribution and properly surfaces as uncited at the Layer 3 parser. Operators see the operator-readable diagnostic (the parser surfaces `you_phrase` as uncited; the operator either revises the draft to remove the YOU attribution or finds a dossier passage that EXPLICITLY attributes the action to the prospect).
* **Include `you_phrase` with higher threshold (0.95)** is rejected because (a) the attribution semantic isn't a cosine-threshold problem — `"you announced X"` vs `"X was announced"` cosine ≈ 0.85-0.90, but cosine 0.95+ would still cite when the dossier paraphrases the prospect's quoted attribution in same voice (`"Yang announced X"` vs `"You announced X"` cosine ≈ 0.95+); the structural problem is voice/actor, not similarity magnitude.
* **"Passive-voice detector" filter before fuzzy match** is rejected per the YAGNI convention — adds NLP complexity (passive-voice detection is a non-trivial ML problem); the structural exclusion at the claim_type level achieves the same result with simpler implementation.
* **Include `you_phrase` + accept the FN regression** is rejected because the asymmetric-failure-cost discipline per ADR-0038 D184 says brand-risk path (FN) > operator-friction path (FP); the W7 `you_phrase` baseline FN_rate 0.00 is a load-bearing regression barrier; the fuzzy-match-induced FN regression would degrade the parser's brand-risk gate.
* **Weaken the attribution semantic** is rejected — ADR-0043 D214's verbatim-only invariant for `quoted_text` is the parallel structural commitment for the attribution-claim category; `you_phrase` joins the category at Week 9 per the empirical evidence.

The `quoted_text` exclusion rationale is preserved (per ADR-0043 D214):

* **Quoted_text exclusion** preserves the ADR-0043 D214 invariant — operators who literally quote a prospect's claim (`You said "agents are eating SaaS"`) must trace the quote to the verbatim source in the dossier.
* **Include quoted_text with higher threshold (0.95)** is rejected — cosine 0.95 typically requires near-identical phrasing (barely more permissive than the existing verbatim check); the operator-side disposition is "this is a quote attribution" — fuzzy match weakens the attribution semantics regardless of threshold.
* **Separate fuzzy-quote-match primitive** is rejected — adds module surface for a use case operators explicitly opt out of (the literal-quote semantic).
* **Relax the verbatim-only invariant** is rejected — would amend ADR-0043 D214 (an out-of-scope amendment for Week 9).

### D241. Encoder resolution — lazy-load framework default when `embed_fn=None`

When `embed_fn=None` at `parse_draft_for_claims`, the body lazy-resolves the framework's default encoder via the Week 2 helper at `voice_corpus._default_embed_fn`:

```python
def parse_draft_for_claims(
    draft: str,
    dossier: str,
    *,
    register: str,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> list[ParsedClaim]:
    ...
    # Lazy-resolve the encoder for the fuzzy-match path.
    if embed_fn is None:
        from voice_corpus import _resolve_embed_model, _default_embed_fn
        embed_model = _resolve_embed_model(None, cfg)
        embed_fn = _default_embed_fn(embed_model)
    chunks = _chunk_dossier_for_fuzzy_match(dossier)
    ...
```

The lazy-load amortizes the encoder load cost — `_default_embed_fn` uses the process-cached `_MODEL_CACHE` at `voice_corpus.py:270` (the per-process singleton pattern from ADR-0039 D188).

**Why lazy-load (rejected: require operators to pre-supply the encoder explicitly; rejected: skip fuzzy when no encoder is supplied; rejected: ship a no-op fallback that returns None for all fuzzy matches).**

* **Lazy-load** matches the framework's operator-side ergonomics — operators invoking `parse_draft_for_claims(draft, dossier, register=...)` at the library surface get the fuzzy path automatically (no kwarg-pass required). The lazy-load is structurally identical to the Week 2 retrieval primitive's `embed_fn` resolution at `voice_corpus.py:910` (`if embed_fn is None: embed_fn = _default_embed_fn(resolved_model)`).
* **Require operators to pre-supply the encoder** is rejected — breaks the operator's library-call shape from Week 6 (the kwarg was TEST-ONLY at Week 6; suddenly making it operator-required at Week 9 would be a soft-breaking surface change). The TEST-ONLY label stays valid per D243 (operators DON'T inject custom encoders at production callsites; the framework's default loader runs).
* **Skip fuzzy when no encoder is supplied** is rejected — semantically equivalent to D237-Alt1 (opt-in default-off) since most operators don't pass embed_fn explicitly; defeats the always-on fuzzy fallback per D237.
* **No-op fallback returning None for all fuzzy matches** is rejected — would silently disable fuzzy in any caller that doesn't supply embed_fn, equivalent to the skip-fuzzy alternative.

### D242. Per-claim-type regression-barrier bounds — UNCHANGED at Week 9 (W7 corpus structural limitation)

The Week 7 baseline regression-barrier targets at `tests/test_draft_quality_corpus.py::TestCorpusBenchmark::_CLAIM_TYPE_BENCHMARK_TARGETS` **stay UNCHANGED at Week 9**:

| Claim type        | W7 FP_rate_max | W9 FP_rate_max | W7 FN_rate_max | W9 FN_rate_max | W7 Accuracy_min | W9 Accuracy_min |
|-------------------|----------------|----------------|----------------|----------------|-----------------|-----------------|
| `date_reference`  |          0.40  |          0.40  |          0.40  |          0.40  |           0.60  |           0.60  |
| `named_entity`    |          0.20  |          0.20  |          0.65  |          0.65  |           0.55  |           0.55  |
| `you_phrase`      |          0.20  |          0.20  |          0.20  |          0.20  |           0.85  |           0.85  |
| `quoted_text`     |          0.20  |          0.20  |          0.20  |          0.20  |           0.85  |           0.85  |
| `dated_event`     |          0.20  |          0.20  |          0.55  |          0.55  |           0.65  |           0.65  |

**The W7 baseline preserves at Week 9 commit time** — empirically measured at threshold 0.85 + D240 attribution-claim exclusion, all five corpora's TP/TN/FP/FN tallies + accuracy + FP_rate + FN_rate are IDENTICAL to the Week 7 baseline. No regression; no fuzzy-enabled tightening.

**Why bounds stay UNCHANGED at Week 9** (rejected at Week 9 commit time: tighten named_entity + dated_event per the original ADR-0044 D225 trajectory; rejected: ship NEW per-claim-type bounds against a separate fuzzy-test corpus; rejected: ship per-claim-type accuracy-only bounds; rejected: tighten more aggressively to the empirically-measured Week 9 rate).

**The W7 corpus's structural limitation against fuzzy match's WIN case** (the empirical finding at Week 9 commit time):

* The Week 7 baseline FN_rate on `named_entity` (53%) + `dated_event` (40%) is DOMINATED by the deterministic substring path's incorrect citation of refused-pair dossiers that use NEGATION PROSE. Example: `nent-u-003 "Following Anthropic Inc's research"` against dossier `"Generic research notes. No specific company mentioned."` — the substring `"anthropic inc"` is NOT in the dossier, but the named_entity claim is "Anthropic Inc" + the dossier's deterministic substring check on possessive forms etc. catches it incorrectly. Fuzzy match at threshold 0.85 against `"Generic research notes. No specific company mentioned."` cosines ~0.50-0.60 — well below threshold — so fuzzy correctly does NOT cite. **The W7 baseline FN cases are stable across W7 and W9 — they are NOT fuzzy-recoverable.**
* The Week 7 baseline ready pairs use VERBATIM dossier embedding (the dossier contains the exact claim text as a markdown link or substring). The deterministic substring path catches these at 100%; fuzzy match has nothing to add. **The W7 baseline TN cases are also stable across W7 and W9 — fuzzy match's WIN case (deterministic returns None → fuzzy correctly cites) is NOT exercised by the W7 corpus's ready-pair design.**
* The W7 corpus's structural design — negation-prose refused pairs + verbatim-substring ready pairs — does NOT exercise fuzzy match's win case. Bound tightening at Week 9 against the W7 corpus is therefore vacuous OR structurally invalid (tightening without behavioral coverage).

**The Week 9 commit ships the fuzzy match INFRASTRUCTURE** + the W7 baseline regression barrier holds verbatim. The fuzzy match's value lands when:

1. **Operators run against real (non-synthetic) dossiers** — operator-authored research dossiers don't use negation prose ("no X mention"); they simply DON'T MENTION X (substring matches return None → deterministic uncited). When the dossier paraphrases the prospect's affirmation (`"Acme Corporation announced..."` for a draft mentioning `"Acme Corp Inc"`), fuzzy match catches the citation that deterministic substring missed. The empirical measurement at Week 9 commit time validated 5 of 8 candidate paraphrase pairs cite correctly at threshold 0.85 (cosines 0.86-0.88).

2. **Future Pillar F weeks' corpus revision** (Week 10+ trajectory; OR operator-side corpus extension via `--corpus-dir <tenant-path>` per ADR-0044 D224): extend the per-claim-type corpora with paraphrased-ready pairs that exercise fuzzy match's WIN case. The bound table at Week 10+ MAY tighten based on the extended corpus's measurements.

3. **The R029 regression-barrier surface** (NEW at Week 9 per §Risks): the Week 9 ship's empirical evidence that fuzzy match at 0.85 does NOT regress the W7 baseline IS the regression barrier — a future Pillar F commit that weakens the fuzzy infrastructure (e.g., raising the threshold above 0.85 without recalibration; removing D240's attribution-claim exclusion) would surface against the W7 baseline's `you_phrase` corpus's FN_rate via the existing benchmark.

**Why bounds stay UNCHANGED** (the alternatives considered at Week 9 commit time):

* **Keep all W7 bounds verbatim** is the ACCEPTED Week 9 choice per the empirical finding above. The W7 corpus's structural limitation makes Week 9 bound tightening vacuous; the Week 9 ship IS the fuzzy infrastructure + the calibration discipline.
* **Tighten named_entity + dated_event per the original ADR-0044 D225 trajectory** is rejected per the empirical finding — the projected bound tightening assumed the W7 baseline FN cases would be fuzzy-recoverable; the Week 9 calibration revealed they are NOT (the FN cases are negation-prose-induced deterministic-substring matches, not fuzzy-recoverable paraphrases).
* **Ship NEW per-claim-type bounds against a separate fuzzy-test corpus** is rejected for the Week 9 ship — the corpus-extension work is operator-deferred per ADR-0044 §Existing-operator seed; landing a NEW corpus at Week 9 would inflate the commit scope beyond the per-week-extension convention. Pillar F Week 10+ MAY ship the extended corpus per the trajectory note above.
* **Ship per-claim-type accuracy-only bounds** is rejected per ADR-0044 D223 — asymmetric-failure-cost discipline requires the FP_rate + FN_rate split.
* **Tighten more aggressively to the empirically-measured Week 9 rate** is rejected per ADR-0044 D225-Alt1 + ADR-0044 D225's headroom discipline (5-15pp for noise + minor parser refinements).

### D243. TEST-ONLY `embed_fn` seam — Week 9 status update (FIRST behavioral consumption at parser surface)

The TEST-ONLY `embed_fn` seam shipped at Week 6 per ADR-0043 D218 was previously PASSTHROUGH-ONLY at the parser surface (Week 6's parser body never invoked it; the seam was pre-installed for "the Week 8+ fidelity-scoring extension's fuzzy-match scoring" per the Week 6 docstring at `orchestrator/draft_quality.py:801-812`). Week 9 ships the FIRST behavioral consumption at the parser surface — the `embed_fn` is invoked in the fuzzy-match path of `_find_citation_anchor` (when the deterministic-first path returns None AND the claim is not quoted_text).

**The TEST-ONLY label stays valid at Week 9** — the rationale is unchanged from ADR-0043 D218:

* **Operators DO NOT inject custom encoders at production callsites.** The lazy-load per D241 resolves the framework's default encoder; operators never pass `embed_fn=...` in production. The kwarg's purpose is the test substitution context (deterministic stub encoder for fast test loop).
* **CLI does NOT surface `--embed-fn`.** Security + audit per ADR-0039 D188-Alt3 — arbitrary embed_fn injection at the CLI runs user-supplied code; the per-event ledger surface couldn't recover which encoder ran for a given parse.
* **The seam is operator-discoverable via the test suite + the docstring.** The TEST-ONLY label in the docstring at `parse_draft_for_claims` updates at Week 9 to NAME the Week 9 behavioral consumption (the seam ACTIVATES the fuzzy-match path) WHILE preserving the TEST-ONLY warning (operators don't inject custom encoders at production callsites).

The seam-preservation continues at the Week 9 commit:

* `parse_draft_for_claims` `embed_fn` kwarg — UPDATED at Week 9 (Week 9 lands the FIRST behavioral consumption; docstring updates to NAME the fuzzy-match path).
* `score_draft` `embed_fn` kwarg — UPDATED at Week 9 (passes through to `parse_draft_for_claims`; the behavioral consumption is at the parser surface).
* `measure_per_claim_type_false_positive_rate` `embed_fn` kwarg — UNCHANGED at Week 9 (the measurement primitive's passthrough to `score_draft` carries the seam through; Week 7's verification status updates per the Week 9 fuzzy-match activation).
* `compute_draft_fidelity_score` `embed_fn` kwarg — UNCHANGED at Week 9 (the fidelity-scoring primitive's passthrough to `retrieve_voice_exemplars` is independent of the parser surface).
* `compute_draft_fidelity_score` `retrieve_fn` kwarg — UNCHANGED at Week 9 (the full-retrieval bypass seam is at the fidelity-scoring primitive only).

**Why update the seam's status without removing the TEST-ONLY label (rejected: rename to non-TEST-ONLY `embed_fn` kwarg; rejected: remove the kwarg from the public signature; rejected: ship a separate `production_embed_fn` kwarg).**

* **Update without removing the label** matches the operator-injection-context reading of "TEST-ONLY" — the label is about the INTENT of the kwarg (test substitution context), not the SHAPE of the body (whether the kwarg has behavior). At Week 9 the kwarg has behavior; the label stays because operators don't inject custom encoders.
* **Rename to non-TEST-ONLY `embed_fn`** is rejected because (a) it would soft-break the Week 6-8 callers' test-substitution patterns (the docstring's TEST-ONLY warning is the operator-discovery surface); (b) the kwarg's per-call cost (encoder invocation) at production is borne via the lazy-load default — operators don't perceive the kwarg as a configuration knob.
* **Remove the kwarg from the public signature** is rejected — breaks the Week 6-8 test-substitution pattern; loses the per-test cost amortization at the per-parse seam.
* **Ship a separate `production_embed_fn` kwarg** is rejected per the YAGNI convention — operators with custom production encoders use the framework's `voice.embed_model` config (per ADR-0039 D188); a parallel kwarg is redundant.

## Alternatives considered

### D236-Alt1: NEW sibling module at `orchestrator/draft_quality_fuzzy.py`

Per the per-primitive flat-module convention, the fuzzy-match extension lives at a NEW sibling module. **Rejected** per D236's rationale — the fuzzy-match extension is a per-claim citation cross-reference refinement of the existing Layer 3 parser; co-location preserves the per-primitive scoping.

### D236-Alt2: Subpackage at `orchestrator/draft_quality/`

Per-Layer subpackage modules. **Rejected** per ADR-0043 D212-Alt2 + ADR-0044 D220-Alt2 + ADR-0045 D228-Alt2 — over-organization for the per-week commit scope.

### D236-Alt3: Per-claim-type fuzzy helpers in separate modules

Five fuzzy helpers at `orchestrator/draft_quality_fuzzy_<claim_type>.py`. **Rejected** — per-claim-type semantics are LABELS on the data, not module-split signals; the fuzzy formula is uniform across claim types.

### D237-Alt1: Opt-in via `voice.use_fuzzy_citation_anchor: false` default

Default off; operators flip true to activate. **Rejected** per D237's rationale — the Week 7 documented FN_rate gap is the addressing path; opt-in defaults perpetuate the gap until operators actively flip.

### D237-Alt2: Opt-in via `voice.use_fuzzy_citation_anchor: true` default

Default on with an opt-out flag. **Rejected** per D237's rationale — adds a per-config-flag knob without per-context discrimination value.

### D237-Alt3: Operator-tunable per-tenant threshold via NEW `~/.outreach-factory/fuzzy_citation.yml`

A per-tenant YAML file with per-claim-type thresholds. **Rejected** per the YAGNI convention — Pillar I per-tenant audit-tooling concern.

### D238-Alt1: Paragraph-level chunking

One chunk per paragraph (double-newline boundaries). **Rejected** per D238's rationale — paragraph embedding dilutes individual claim semantics; FP_rate inflation on paragraphs that combine unrelated content.

### D238-Alt2: Sliding-window chunking

100-char windows with 50-char overlap. **Rejected** per D238's rationale — per-window count explodes (O(N²/W)); per-window embeddings inherently dilutive.

### D238-Alt3: Per-token overlap scoring

Jaccard or TF-IDF over per-claim tokens vs per-chunk tokens. **Rejected** per D238's rationale — doesn't capture semantic similarity; lexical overlap is what the Week 6 substring-only path already does.

### D238-Alt4: Weighted aggregation across chunks

Sum-of-top-3 cosines or similar. **Rejected** per D238's rationale — citation is binary (cited or not); aggregate is not the right question for Layer 3 per-claim cross-reference.

### D239-Alt1: 0.75 cosine threshold (initial proposal)

Per the original ADR-0046 proposal. **Rejected** per D239's calibration history — at threshold 0.75, the W7 corpus regressed (FN_rate spike on date_reference + dated_event + you_phrase) due to negation-prose chunks surfacing cosines in the 0.75-0.90 range.

### D239-Alt2: 0.80 cosine threshold

A slightly less strict threshold. **Rejected** per D239's calibration history — date_reference + dated_event corpora regress on FN_rate; the FP_rate improvement does not compensate per the asymmetric-failure-cost calculus.

### D239-Alt3: 0.90 cosine threshold

A stricter threshold. **Rejected** per D239's rationale — typical entity paraphrases ("Acme Corp Inc" vs "Acme Corporation, Inc.") cosine ≈ 0.85-0.88; 0.90 cuts these out; fuzzy match becomes effectively rarely-firing.

### D239-Alt4: Per-claim-type thresholds

Different thresholds per claim_type (e.g., named_entity 0.80; dated_event 0.85; date_reference 0.90). **Rejected** at Week 9 — YAGNI; per-claim-type variation is captured in the per-claim-text embedding.

### D239-Alt5: Operator-tunable per-tenant threshold via NEW `~/.outreach-factory/fuzzy_citation.yml`

Per-tenant YAML file. **Rejected** per the YAGNI convention — Pillar I per-tenant audit-tooling concern.

### D240-Alt1: Include quoted_text with higher threshold (0.95)

Fuzzy match quoted_text but require ≥ 0.95 cosine. **Rejected** per D240's rationale — ADR-0043 D214 invariant; quote attribution semantics require verbatim.

### D240-Alt2: Separate fuzzy-quote-match primitive

A new `_find_quote_paraphrase_anchor` for quoted_text. **Rejected** per D240's rationale — operators explicitly opt out of fuzzy quote attribution.

### D240-Alt3: Relax verbatim-only invariant

Amend ADR-0043 D214 to allow fuzzy quote matching. **Rejected** — out-of-scope amendment for Week 9; preserves prior ADRs.

### D241-Alt1: Require operators to pre-supply the encoder explicitly

`parse_draft_for_claims(..., embed_fn=YOUR_ENCODER)` operator-required. **Rejected** per D241's rationale — breaks the operator's library-call shape from Week 6.

### D241-Alt2: Skip fuzzy when no encoder is supplied

The fuzzy path activates only when caller passes embed_fn. **Rejected** per D241's rationale — semantically equivalent to opt-in default-off.

### D241-Alt3: No-op fallback returning None for all fuzzy matches

The fuzzy path silently returns None when no encoder. **Rejected** per D241's rationale — silently disables fuzzy in any caller that doesn't supply embed_fn.

### D242-Alt1: Tighten named_entity + dated_event per the original ADR-0044 D225 trajectory

Originally proposed at the Week 9 draft commit time per the ADR-0044 D225 trajectory note. **Rejected** per D242's rationale — the empirical Week 9 measurement revealed the W7 corpus's negation-prose structural limitation against fuzzy match's WIN case (the projected bound tightening assumed fuzzy-recoverable FN cases; the W7 baseline FN cases are deterministic-substring-on-negation-prose induced, NOT fuzzy-recoverable).

### D242-Alt2: Tighten more aggressively to the empirically-measured Week 9 rate

Tight bounds at the current Week 9 rate (no headroom). **Rejected** per ADR-0044 D225-Alt1 — bound flakiness from corpus sampling + minor parser refinements. Also: the W9 empirical rate matches the W7 baseline (no improvement); tightening from the same baseline is structurally vacuous.

### D242-Alt3: Ship NEW per-claim-type accuracy-only bounds

Drop the FP_rate + FN_rate split in favor of accuracy-only. **Rejected** per ADR-0044 D223 — asymmetric-failure-cost discipline requires the FP/FN split.

### D242-Alt4: Ship NEW per-claim-type bounds against a separate fuzzy-test corpus

A second corpus extension at Week 9. **Rejected** per D242's rationale — the corpus-extension work is operator-deferred per ADR-0044 §Existing-operator seed; landing a NEW corpus at Week 9 would inflate the commit scope. Pillar F Week 10+ MAY ship the extended corpus.

### D243-Alt1: Rename to non-TEST-ONLY `embed_fn` kwarg

Remove the TEST-ONLY label. **Rejected** per D243's rationale — operators DON'T inject custom encoders at production callsites; the label is about INTENT, not body.

### D243-Alt2: Remove the kwarg from the public signature

Drop `embed_fn` from `parse_draft_for_claims`. **Rejected** per D243's rationale — breaks Week 6-8 test-substitution pattern.

### D243-Alt3: Ship a separate `production_embed_fn` kwarg

Parallel kwarg for production-encoder injection. **Rejected** per the YAGNI convention — operators use `voice.embed_model` config.

## Consequences

### Positive consequences

* **The fuzzy-match infrastructure ships at the Layer 3 parser surface.** The TEST-ONLY `embed_fn` seam pre-installed at Week 6 per ADR-0043 D218 lands its FIRST behavioral consumption at the parser surface — the load-bearing primitive's amortized per-test cost property is realized. Operators with real (non-synthetic) dossiers benefit immediately when paraphrased entities + dated events appear; the operator-friction false-positive (refusing a draft that DOES cite the prospect's affirmation paraphrased in the dossier) is bounded by the 0.85 threshold calibration.
* **The asymmetric-failure-cost discipline tightens at the parser surface — within the calibration discipline.** The Week 9 commit's threshold calibration (0.85, with you_phrase + quoted_text excluded per D240) preserves the Week 7 baseline regression barrier; the Week 9 ship adds the fuzzy infrastructure WITHOUT regressing the W7 baseline FN_rate (the brand-risk path).
* **The W7 baseline's structural limitation against fuzzy match's WIN case is empirically documented + bounded.** The Week 9 commit's calibration history (preserved in D239) names the calibration trajectory + the W7 corpus's negation-prose structural limitation. Future Pillar F weeks' corpus revision (per ADR-0044 D225's trajectory note) MAY surface paraphrased-ready pairs that exercise fuzzy match's win case; the bound table MAY tighten at Week 10+ per the extended corpus's measurements.
* **The Week 9 ship is the operator-invisible behavioral upgrade.** Operators inheriting `voice.use_embedding_primitive: true` per ADR-0045 D232 at Week 8 also inherit the fuzzy-match parser at Week 9; no per-config-flag operator action required.
* **The you_phrase exclusion at D240 surfaces the attribution-claim semantic at the structural layer.** Operators writing `you posted X` MUST trace `X` to the prospect's authored body in the dossier; passive-voice paraphrase `X was posted` correctly fails the attribution AT THE STRUCTURAL LAYER (the parser refuses to fuzzy-match attribution claims). The exclusion mirrors the verbatim-only invariant for quoted_text per ADR-0043 D214's parallel structural commitment.

### Negative consequences

* **Per-parse encoding cost lands at Week 9.** Each parse incurs ~50-200ms for the encoder lazy-load (first call; amortized across the process lifetime per `_MODEL_CACHE`) + ~5-15ms per chunk encoding (N chunks per dossier; typically N = 10-30 for a 500-1500-char dossier) + ~5-15ms per uncited claim's claim_text encoding. Total per-parse: ~100-450ms first call; ~50-150ms steady-state. **Bounded by** the deterministic-first dispatch (fuzzy only runs for claims that don't substring-match); operators with verbatim-citation dossiers pay zero fuzzy cost.
* **`orchestrator/draft_quality.py` grows by ~350 LOC** (DEFAULT_FUZZY_CITATION_THRESHOLD + _chunk_dossier_for_fuzzy_match + _find_citation_anchor_fuzzy + parse_draft_for_claims signature extension + score_draft signature extension + ~100 LOC of docstrings + 2 module-level docstring updates).
* **Test count grows by ~60-80 tests.** TestChunkDossier + TestFindCitationAnchorFuzzy + TestParseDraftForClaimsFuzzy + TestScoreDraftFuzzy + TestWeek9ModuleSurface + supplementary regression-barrier tests against the Week 7 corpus.
* **The Week 7 corpus benchmark stays UNCHANGED at Week 9.** The empirical measurement at Week 9 commit time confirms the W7 baseline rates preserve (after D240 attribution-claim exclusion + the 0.85 threshold calibration); no bound updates. The per-week reviewer's checklist verifies the W7 corpus's per-claim-type rates stay within the existing bounds.
* **R029 (Fuzzy-match false-positive) surfaces.** Operators may see drafts cited via the fuzzy path that they would have refused under strict verbatim cross-reference. The `citation_anchor` field surfaces `"dossier:fuzzy-match@chunk-N"` (or the chunk's nearby URL) for operator-side inspection; the threshold calibration bounds the FP_rate.

### Risks

The asymmetric-failure-cost calculus carries:

* **R029 (Fuzzy-match false-positive — new at Week 9).** The fuzzy-match path may stamp `citation_anchor` from a dossier chunk that LOOKS semantically similar but does NOT actually support the claim. **Bounded by** the threshold calibration (0.75 cosine cutoff against the Week 7 corpus's FP characterization) + the operator-readable `citation_anchor` value (`"dossier:fuzzy-match@chunk-N"`) + the Pillar F Week 12 binding 200-draft eval set's `<1%` FN bound + the per-week reviewer's per-claim-type benchmark re-runs.

* **The chunk-boundary noise sensitivity (P3):** Operators authoring dossiers with unusual punctuation (no sentence-ending periods; markdown-heavy formatting) may see the chunker produce noisy chunks. **Bounded by** the chunker's short-chunk filter (<10 chars dropped) + the chunker's long-chunk re-split (>500 chars re-chunked) + the operator-readable chunker test surface.

* **The encoder lazy-load's first-call latency surface (P3):** The first parse in a process pays ~1-2s for the SentenceTransformer load. **Bounded by** the per-process `_MODEL_CACHE` singleton from ADR-0039 D188 — subsequent parses reuse the cached model; the operator's `/draft-outreach` per-prospect loop amortizes the load cost across the per-batch parses.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The Week 9 fuzzy-match extension is parser-side; no ledger mutation; the `citation_anchor` field is per-parse in-memory only; the `hallucination_detected` event payload (when refused) carries the per-claim trace including the (possibly fuzzy-matched) anchor for operator inspection.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The Week 9 extension is upstream of the dispatcher.
* **I3 — Atomic per-Person enrollment.** Preserved. Week 9 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The fuzzy-match path is per-claim; `channel` is per-draft.
* **I5 — Migration framework discipline.** Preserved. Week 9 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The `hallucination_detected` event's `channel` field is unchanged at Week 9.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. The Week 9 extension adds a NEW refuse-loud surface: (a) `fuzzy_threshold` validation in `parse_draft_for_claims` (out-of-range refuses-loud); (b) `_find_citation_anchor_fuzzy` per-arg validation (empty chunks list + None embed_fn refuses-loud at the test substitution context). Mirrors the Week 6 + Week 7 + Week 8 closed-enum + bool-catch discipline.
* **I8 — Privacy-respecting.** Preserved. The `citation_anchor` field is per-chunk; for fuzzy matches, the anchor is the chunk's nearby URL OR `"dossier:fuzzy-match@chunk-N"` — NEVER the chunk's body text. The `hallucination_detected` event's per-claim trace continues to carry the per-claim literal span + the anchor (URL or chunk reference); the dossier body NEVER lands in the event payload.

## Downstream pillar impact

* **Pillar F Week 10 (Layer 4 post-engine guard).** The Week 10 emit guard consults `DraftQualityResult.uncited_claims` + `state` (Week 6 + Week 8 substrate); the Week 9 fuzzy-match path lowers the `uncited_claims` count for paraphrased citations + drops the rate at which Layer 4 refuses. The Week 9 commit's per-claim-type benchmark stays GREEN at Week 10's ship; the Week 10 emit guard's per-event refusal cardinality re-measures.

* **Pillar F Week 12 (Layer 5 reconcile heal-pass refusal).** The Week 12 reconcile Pass C consults the linked `hallucination_detected` events on the ledger; the Week 9 fuzzy-match's lowered FN_rate at the Layer 3 surface translates to fewer per-Person `hallucination_detected` events → fewer Pass C refusals. The Week 12 binding exit-criterion's 200-draft eval set's `<1%` FN bound is the structural commitment Week 9's fuzzy match contributes to.

* **Pillar G (Observability).** Dashboards consume `hallucination_detected` events; the per-event `uncited_claims` count per Person + per register drops at Week 9. The per-claim-type FP_rate + FN_rate dashboards (per ADR-0044 §Pillar G) read against the updated baseline.

* **Pillar H (Real-time + scale).** The Week 9 extension adds per-parse encoding cost (~50-150ms steady-state per parse). Pillar H optimizations (per-process model cache from ADR-0039; pre-computed dossier chunks for high-volume operators) bound the per-parse cost.

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions MAY extend with `draft_quality fuzzy-baseline --corpus-dir <path>` (per-tenant per-claim-type fuzzy-match baseline measurement) IF operator demand materializes. The Week 9 CLI's `parse` subcommand does NOT surface `--fuzzy-threshold` (operator-deferred per the per-call kwarg's library-only access pattern).

* **Pillar J (Compliance + audit).** Per-tenant GDPR-purge does not touch the Week 9 extension beyond the existing `hallucination_detected` per-Person purge path. The fuzzy-match `citation_anchor` field surfaces `"dossier:fuzzy-match@chunk-N"` (NOT the chunk body); the per-event privacy invariant preserves.

## Migration / rollout

**Week 9 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 8 to Pillar F Week 9:

1. **Operator updates the framework** to Pillar F Week 9's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 9 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_draft_quality.py -v`** to verify the new fuzzy-match tests pass. Optional but recommended.
4. **Operator MAY verify the Week 7 baseline against the Week 9 bounds.** `python -m pytest tests/test_draft_quality_corpus.py::TestCorpusBenchmark -v` runs the per-claim-type benchmark; the TIGHTENED bounds (named_entity FN_rate_max 0.45; dated_event FN_rate_max 0.35) MUST be green.
5. **Operator MAY adjust the per-call `fuzzy_threshold` kwarg** at library callsites IF their corpus's per-claim-type characteristics differ materially from the Week 7 corpus baseline. The framework default 0.75 is the structural commitment; per-call overrides are operator-deliberate.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 10 ships Layer 4 emit-refusal; may extend `ledger/0008_draft_quality_scored_index` for per-event indexing (TBD per the per-week design). Week 12 ships Layer 5 reconcile heal-pass refusal + the binding exit-criterion test un-skips.

## Existing-operator seed

**Pillar F Week 9's operator-side disposition is content-additive — no operator action required at Week 9.** The fuzzy-match extension lands at the parser surface; operators inheriting `voice.use_embedding_primitive: true` per ADR-0045 D232 automatically inherit the fuzzy-match path; operators with `voice.use_embedding_primitive: false` still get the fuzzy-match path at the parser surface (the parser's fuzzy-match is independent of the voice-corpus retrieval primitive's flag).

The operator-side trajectory (per-week ships across Pillar F Weeks 9-12):

* **Week 9 (this commit):** The fuzzy-match parser extension lands. The Week 7 per-claim-type bounds TIGHTEN on `named_entity` + `dated_event`. SKILL.md is UNCHANGED at Week 9 (the per-draft narrative's Phase 5 hallucination-detection gate dispatch is unchanged; the gate is more precise but the operator-facing prose stays).
* **Week 10:** Layer 4 post-engine guard ships per ADR-0038 D180. The `draft_ready` event emit refuses-loud when EITHER `uncited_claims` non-empty OR `meets_threshold=False`. SKILL.md Phase 6 extends.
* **Week 12:** Layer 5 reconcile Pass C heal-pass refusal ships; the binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 9:** none. The framework upgrade is read-only with respect to operator state.

**Operator action recommended at Week 9:** none beyond the per-week pytest verification. Operators MAY pass `fuzzy_threshold=X` at library callsites if their corpus's distribution warrants. Pillar I per-tenant audit-tooling may surface per-corpus calibration if demand materializes.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D180 (FIVE-layer hallucination-detection defense; the Layer 3 parser is Week 6 + Week 9 substrate) is THE structural context Week 9's fuzzy extension consumes. D184's asymmetric-failure-cost discipline motivates the always-on fuzzy fallback per D237.
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive. D188 (TEST-ONLY `embed_fn` seam at retrieval surface) is the LINEAGE the Week 9 D243's parser-surface consumption continues. The `_default_embed_fn` + `_resolve_embed_model` helpers at `voice_corpus.py:598-633` are the substrate Week 9's D241 lazy-load consumes.
- **ADR-0040 (D192-D198)** — Pillar F Week 3 per-register adapters. D197 (TEST-ONLY embed_fn seam preservation) carries forward per D243.
- **ADR-0041 (D199-D205)** — Pillar F Week 4 per-register threshold infrastructure. D201 (range validation + bool catch) is the STRUCTURAL reference for the `fuzzy_threshold` kwarg's validation per D239.
- **ADR-0042 (D206-D211)** — Pillar F Week 5 voice-thresholds CLI extension. D210 (argparse-choices closed-enum at CLI) is the STRUCTURAL precedent the Week 9 commit does NOT extend — Week 9 does NOT surface `--fuzzy-threshold` at the CLI (operator-deferred per the per-call kwarg's library-only access pattern).
- **ADR-0043 (D212-D219)** — Pillar F Week 6 hallucination-detection Layer 2-3 primitive. D214 (`parse_draft_for_claims` Layer 3 parser) is THE substrate Week 9 extends. D218 (TEST-ONLY `embed_fn` seam pre-installed) is the LINEAGE Week 9's parser-surface activation continues. The Week 6 verbatim-only invariant for `quoted_text` is preserved at Week 9 per D240.
- **ADR-0044 (D220-D227)** — Pillar F Week 7 per-claim-type corpora + measurement primitive. D225 (per-claim-type regression-barrier rate bounds) is THE substrate Week 9 tightens per D242. The trajectory pinned at D225 §Future Pillar F weeks' bound trajectory ("Week 8+ ships per-claim fuzzy-match scoring") is the Week 9 commit's structural commitment. D227 (TEST-ONLY embed_fn seam preservation at measurement primitive) carries forward per D243.
- **ADR-0045 (D228-D235)** — Pillar F Week 8 fidelity-scoring primitive + draft_quality_scored event class. D228 (extend `orchestrator/draft_quality.py` rather than new sibling) is the PRECEDENT for D236's module placement decision. D235 (TEST-ONLY embed_fn + retrieve_fn seam preservation) is the LINEAGE Week 9's parser-surface activation continues at the parse_draft_for_claims surface.
- **ADR-0014 (D33)** — Pillar C foundation. The channel-on-every-event invariant continues at the `hallucination_detected` event class; Week 9's fuzzy-match path doesn't add new event classes.
- **ADR-0010 (D17)** — Per-event `_emitted_by` marker. The Week 9 extension does NOT add new event classes; `_emitted_by` stays UNCHANGED.
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §51+ extends with the Week 9 commit's audit verdict (the fuzzy-match parser extension's public surface + the seam's parser-surface activation + the per-claim-type bound tightening + the SKILL.md UNCHANGED status + the SOURCES-OF-TRUTH row UNCHANGED status).
- **`.planning/HANDOFF-pillar-f-week-9.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 10 Layer 4 trajectory.
- **`orchestrator/draft_quality.py`** — extended with `DEFAULT_FUZZY_CITATION_THRESHOLD` + `_chunk_dossier_for_fuzzy_match` + `_find_citation_anchor_fuzzy` + parser signature extension per D236-D243.
- **`tests/test_draft_quality.py`** — extended with `TestChunkDossier` × 10 + `TestFindCitationAnchorFuzzy` × 16 + `TestParseDraftForClaimsFuzzy` × 14 + `TestScoreDraftFuzzy` × 8 + `TestWeek9ModuleSurface` × 5 = ~53 new tests covering D236-D243.
- **`tests/test_draft_quality_corpus.py`** — `_CLAIM_TYPE_BENCHMARK_TARGETS` UNCHANGED at Week 9 per D242 (the W7 baseline preserves; future bound tightening at Week 10+ when corpus is extended).
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 9 close summary.
- **`docs/adr/README.md`** — ADR-0046 row appended.
- **`docs/RISK-REGISTER.md`** — R029 (fuzzy-match false-positive) row appended.
