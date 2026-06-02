# ADR-0043: Pillar F Week 6 — hallucination-detection primitive (Layer 2-3)

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** F (Voice corpus + draft quality — Week 6 hallucination-detection Layer 2-3 primitive)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation — D180 named the hallucination-detection FIVE-layer defense-in-depth (Layer 1 test-corpus pin shipped Week 1; Layers 2-3 land Week 6; Layer 4 lands Week 10; Layer 5 lands Week 12). Pillar F Week 2 (ADR-0039 D185-D191) shipped the shared embedding-retrieval primitive. Pillar F Week 3 (ADR-0040 D192-D198) shipped the five per-register adapters in one commit. Pillar F Week 4 (ADR-0041 D199-D205) shipped the per-register voice-fidelity threshold infrastructure (`load_voice_thresholds` + `get_voice_threshold_for_register` + `DEFAULT_VOICE_THRESHOLD_PER_REGISTER`). Pillar F Week 5 (ADR-0042 D206-D211) shipped the operator-facing CLI extension (`thresholds list/get/dump`). The Week 5 commit + follow-up shipped at 24f51ef + 171fddc with 0 P1 + 1 P2 + 3 P3s addressed; 2884 tests passing post-follow-up.

Pillar F Week 6 ships **the first behavioral layers of the hallucination-detection FIVE-layer defense** per ADR-0038 D180 Layer table — Layer 2 (`DraftQualityResult` construction-time invariants) + Layer 3 (`parse_draft_for_claims` parse-level guard). Both layers land in a NEW per-primitive flat module at `orchestrator/draft_quality.py` per ADR-0036 D166's per-primitive-flat-module convention; the Week 2 voice-corpus primitive's public surface stays verbatim, and the Week 4 threshold loader's library surface is the LOAD-BEARING substrate the new primitive consumes (via `get_voice_threshold_for_register(register=<draft-register>)` per ADR-0041 D204).

The Week 1 stub at `tests/test_multi_channel_coherence.py::TestHallucinationDetection::test_draft_with_uncited_claim_fails_gate` has been waiting since Week 1 for the gate's first behavior. Week 6 un-skips this row PLUS the three other rows that gate on Layer 2 / Layer 3 / event-shape per the D180 Layer table: `test_draft_with_cited_claims_passes_gate` (Layer 3 happy-path complement), `test_draft_quality_result_refuses_construction_on_uncited_with_ready` (Layer 2), `test_hallucination_detected_event_carries_uncited_claim_trace` (D182 event-shape pin). Per the existing TestHallucinationDetection docstring at lines 7204-7214, Week 6 un-skips FOUR rows total; Week 10 un-skips ONE (Layer 4); Week 12 un-skips ONE (Layer 5).

The eight concerns this ADR resolves:

1. **The module placement + module shape must be pinned at Week 6** so subsequent Pillar F weeks (Week 8+ fidelity-scoring primitive; Week 10 Layer 4 post-engine guard; Week 12 Layer 5 reconcile heal-pass) build against a stable target. The per-primitive flat-module convention per ADR-0036 D166 is the structural reference. **D212** pins.

2. **The `DraftQualityResult` dataclass + Layer 2 construction-time invariants must be designed at Week 6** so downstream consumers (Week 10 `draft_ready` event emitter; Week 12 reconcile Pass C heal) read against a single closed-set shape with refuse-loud-at-construction discipline. The Pillar E `DiscoveryLineage.__post_init__` precedent per ADR-0036 D167 + the Pillar F Week 2 `VoiceExemplar.__post_init__` precedent per ADR-0039 D186 are the structural references. **D213** pins.

3. **The `parse_draft_for_claims` primitive + per-claim trace shape must be pinned at Week 6** per ADR-0038 D180's "(claim_type, claim_text, citation_anchor | None) triple" naming + the five claim types `{date_reference, named_entity, you_phrase, quoted_text, dated_event}`. The parser is the Layer 3 gate; per-claim threshold dispatch + per-claim citation cross-reference both consume the trace. **D214** pins.

4. **The per-claim threshold consumption surface must be pinned at Week 6** per ADR-0041 D204 substrate. The per-claim Layer 2-3 gate consults `get_voice_threshold_for_register(register=<draft-register>)`; the Week 4 threshold loader's public surface is unchanged at Week 6 (consumer-side adoption, not surface mutation). **D215** pins.

5. **The `hallucination_detected` event-payload factory must ship at Week 6** per ADR-0038 D182's new-event-class naming. The factory builds the per-draft refusal payload (privacy-respecting per ADR-0038 §Compliance with invariants — sha256 `draft_hash` NOT raw draft body; per-claim `{claim_type, claim_text, citation_anchor}` tuples). The event class carries `channel: <draft-channel>` per ADR-0014 D33's channel-on-every-event invariant + `register: <draft-register>` per ADR-0038 D178's closed enum + `_emitted_by: "draft_quality"` per ADR-0010 D17. **D216** pins.

6. **The `/draft-outreach` SKILL.md Phase 5 extension must ship at Week 6** per the Pillar F Week 1 audit's P2-B carry-forward (LOAD-BEARING for Week 6). The humanizer-check phase extends with the hallucination-detection gate dispatch; refuses to advance the draft to `pipeline_stage: ready` when `uncited_claims` is non-empty. The Pillar F Week 2 precedent at D191 (the SKILL.md Phase 4 update at the primitive's ship week) applies — the SKILL.md integration lands AT the primitive's ship week, not deferred. **D217** pins.

7. **The TEST-ONLY `embed_fn` seam preservation discipline EXTENDS to the Week 6 primitive** per ADR-0040 D197 + ADR-0041 D205 + ADR-0042 D211. **Week 6 is the FIRST non-N/A verification of the seam at a new encoding surface** — the parser CAN optionally encode the draft + each claim against the research dossier's citation set for fuzzy-match scoring (a Week 8+ extension). At Week 6 the deterministic parser ships first; the encoding-extension seam ships PRE-INSTALLED in the public signature as TEST-ONLY in the docstring, NOT surfaced via CLI. **D218** pins.

8. **The `hallucination_detected` event emit-cardinality must be pinned at Week 6.** Emit-only-on-uncited (one event per uncited-claims-non-empty parse) rather than emit-on-every-parse (one event per parse, accept-case included). The accept-case is the silent default; the refuse-case is the loud event. The asymmetric-failure-cost calculus mirrors the Pillar D Week 4-5 `suppression_added` event's emit-only-on-add per ADR-0028 D116. **D219** pins.

Risks this ADR mitigates by design: **R024 (voice-corpus drift)** continues mitigated — the Week 6 primitive is a consumer of the corpus-side metadata; no new corpus mutation. **R025 (embedding-cost runaway)** continues mitigated — the Week 6 parser is DETERMINISTIC (regex-based per-claim extraction); the optional encoding seam ships pre-installed but the default code path does NOT encode (Week 8+ ships the fuzzy-match scoring extension). **R026 (operator-corpus split)** continues mitigated — orthogonal to the corpus directory.

**One new risk surfaces in this Week 6 commit:** **R027 (per-claim false-positive rate)** — a deterministic regex-based parser will sometimes flag claims as uncited that ARE supported by the dossier (e.g., a paraphrased citation, a synonymous named entity). The asymmetric-failure-cost calculus: false-positive costs operator one stamp-override; false-negative ships an uncited claim. The framework defaults toward false-positive (refuse-loud at the boundary). Recalibration trajectory: Pillar F Week 8+ ships per-claim fuzzy-match scoring against the dossier's citation set; Week 10+ ships per-claim-type calibration corpora to measure false-positive rates per-register. Week 6 surfaces the structural commitment; Weeks 8-12 surface the per-claim-type calibration.

## Decision

### D212. Module placement — `orchestrator/draft_quality.py` (NEW top-level sibling)

A new module at `orchestrator/draft_quality.py`, a top-level sibling of `voice_corpus.py` + `discovery_dedup.py` + `email_verification_cache.py` + `tier_assignment.py` + `discovery_lineage.py`. The flat-module convention per ADR-0036 D166 carries forward — each primitive's public surface is one module, importable via `from orchestrator.draft_quality import DraftQualityResult, parse_draft_for_claims, score_draft, build_hallucination_detected_payload`.

The module's public surface:

* `DraftQualityResult` (dataclass) — Layer 2 construction-time-validated per-draft result. Refuses construction when `uncited_claims` non-empty AND `state == "ready"`.
* `ParsedClaim` (dataclass) — per-claim trace shape per D214; carries `claim_type` + `claim_text` + `citation_anchor`.
* `CLAIM_TYPES` (frozenset[str]) — closed-set of the five claim types per ADR-0038 D180. Module-level constant (mirrors `REGISTERS` + `CHANNELS` convention per ADR-0038 D178 + ADR-0014 D33).
* `parse_draft_for_claims(draft, *, ...) -> list[ParsedClaim]` — Layer 3 deterministic per-claim extractor.
* `score_draft(draft, dossier, *, register, channel, ...) -> DraftQualityResult` — composite Layer 2 + Layer 3 entry point; the per-draft refusal gate.
* `build_hallucination_detected_payload(*, person_id, result, channel, register) -> dict` — Layer 2-3 event-payload factory per D216.
* `EMITTED_BY: str = "draft_quality"` — the per-event `_emitted_by` marker per ADR-0010 D17.

The CLI subcommands:

```
python orchestrator/draft_quality.py parse --draft-path <path> --research-dossier-path <path> \
                                            [--register <reg>] [--channel <ch>] \
                                            [--apply] [--json]
```

`parse` runs Layer 3 + Layer 2 + returns the per-claim trace + the gate verdict. `--apply` controls whether the `hallucination_detected` event lands in the ledger when `uncited_claims` is non-empty per D219's emit-only-on-uncited posture. Dry-run is default (mirrors `voice_corpus.py retrieve`'s `--apply` semantics per ADR-0039 D188).

**Why a NEW top-level sibling module (rejected: extension of `voice_corpus.py`; rejected: subpackage at `orchestrator/draft_quality/`; rejected: per-Layer files at `orchestrator/draft_quality/layer2.py` + `layer3.py`).**

* **NEW top-level sibling** preserves the per-primitive-flat-module convention per ADR-0036 D166. The Week 6 primitive's substrate is the Week 4 threshold loader at `voice_corpus.py` (consumed via `get_voice_threshold_for_register`); the primitives are sibling at the same `orchestrator/` directory. Future Pillar F weeks (Week 8+ fidelity-scoring) likely land at `orchestrator/fidelity_scoring.py` as a third sibling.
* **Extension of `voice_corpus.py`** is rejected because the module is already ~2170 LOC post-Week-5; adding ~400-600 LOC for the Week 6 hallucination-detection primitive would push the file past ~2600 LOC at one module. The framework convention is per-primitive separation (Pillar E shipped FOUR sibling modules; Pillar F Week 2's voice corpus is one; the hallucination-detection primitive deserves its own).
* **Subpackage at `orchestrator/draft_quality/`** is rejected per the same rationale as ADR-0038 D181-Alt1 + ADR-0039 D185-Alt1 — over-organization for the Week 6 commit's ~400-600 LOC scope; one module is sufficient + future Pillar F weeks' extensions land at the existing module.
* **Per-Layer files at `orchestrator/draft_quality/layer2.py` + `layer3.py`** is rejected because Layers 2 + 3 are structurally bound — Layer 3's parser produces the `uncited_claims` field; Layer 2's construction-time invariant consumes that field. Splitting them across files inflates the import surface for no behavioral benefit; the per-Layer naming is a documentation convention, not a module-split signal.

### D213. `DraftQualityResult` dataclass + Layer 2 construction-time invariants

The per-draft result dataclass:

```python
@dataclass(frozen=True)
class DraftQualityResult:
    draft_hash: str                  # sha256:<hex> of the draft body (privacy)
    register: str                    # closed-set per REGISTERS per ADR-0038 D178
    channel: str                     # closed-set per CHANNELS per ADR-0014 D33
    parsed_claims: tuple[ParsedClaim, ...]   # all claims extracted (cited + uncited)
    uncited_claims: tuple[ParsedClaim, ...]  # subset where citation_anchor is None
    threshold: float                 # the per-register threshold consulted (D215)
    state: str                       # "ready" | "refused"
```

Construction-time invariants in `__post_init__` (Layer 2 per ADR-0038 D180):

* `draft_hash` starts with `"sha256:"` (privacy invariant — raw drafts MUST NOT land in the result).
* `register` in `REGISTERS` (closed-enum per ADR-0038 D178).
* `channel` in `CHANNELS` (closed-enum per ADR-0014 D33).
* `parsed_claims` is a `tuple` of `ParsedClaim` instances (immutability — operator-passed lists would alias the constructor's input).
* `uncited_claims` is a subset of `parsed_claims` (every member of `uncited_claims` MUST appear in `parsed_claims`).
* Every member of `uncited_claims` has `citation_anchor is None`.
* `threshold` is a float in `[0.0, 1.0]` (matches ADR-0041 D201's loader's range).
* **`state == "ready"` AND `uncited_claims` non-empty is REFUSED** — `__post_init__` raises `ValueError` naming the per-claim trace + the `state="refused"` operator-readable remediation. This is the THE Layer 2 invariant per ADR-0038 D180.
* `state` in `{"ready", "refused"}`; unknown state raises `ValueError`.

The `state="refused"` path is the construction-time accept of the uncited-non-empty case — operators (or callers) construct a `DraftQualityResult(state="refused", uncited_claims=(...))` to surface the refusal to downstream consumers. The Layer 2 invariant ONLY catches the structurally invalid combination (`state="ready"` AND `uncited_claims` non-empty) — the refused state IS the correct shape for the uncited case.

**Why frozen + tuple-typed + construction-time-validated (rejected: mutable dataclass with list fields; rejected: pydantic; rejected: skip the construction-time invariant + rely on the parse-level guard only; rejected: dict-only).**

* **Frozen + tuple-typed** mirrors Pillar E's four primitives' + Pillar F Week 2's `VoiceExemplar` dataclass discipline per ADR-0036 D167 + ADR-0039 D186. Immutability across the parse → factory → ledger-emit boundary prevents aliasing hazards; tuple fields prevent caller mutations that would silently invalidate the construction-time invariant.
* **Construction-time validation refuses-loud at the construction site** per the framework's I7 invariant. The Layer 2 gate is the structural commitment — even if a future contributor's parser bug produced a `state="ready"` result with `uncited_claims` non-empty, the dataclass refuses to construct it; the bug surfaces at the construction site, not in a downstream consumer.
* **Mutable dataclass with list fields** is rejected because operator-side mutations across the parse → factory → emit boundary could silently invalidate the construction-time invariant (an operator stamping `result.state = "ready"` after construction would bypass the gate); tuples + frozen prevent the bypass at the language level.
* **Pydantic** is rejected per ADR-0039 D186-Alt2 — adds a dependency for one validator; the explicit `__post_init__` is ~30 LOC + matches the framework convention.
* **Skip the construction-time invariant + rely on parse-level guard only** is rejected because the parse-level guard is one of FIVE layers per ADR-0038 D180; landing only Layer 3 weakens the structural commitment. The construction-time invariant is the lower-level defense — even a contributor bypassing the parser (e.g., constructing a `DraftQualityResult` directly in a test or a future operator-side script) hits the gate.
* **Dict-only** is rejected because the per-call boundary loses the typed surface for IDE-assisted authoring of downstream consumers (Week 10 Layer 4 event-emitter; Week 12 Layer 5 reconcile pass).

### D214. `parse_draft_for_claims` primitive + per-claim trace shape

The deterministic Layer 3 parser:

```python
@dataclass(frozen=True)
class ParsedClaim:
    claim_type: str       # one of CLAIM_TYPES
    claim_text: str       # the literal claim span from the draft (operator-visible)
    citation_anchor: str | None   # the matching dossier anchor (URL OR line ref); None = uncited


CLAIM_TYPES: frozenset[str] = frozenset({
    "date_reference",   # "last week", "April 2026", "in Q1", "2026-03-15"
    "named_entity",     # proper-noun spans (capitalized phrases; "$Company")
    "you_phrase",       # "you posted...", "you mentioned...", "you launched..."
    "quoted_text",      # spans inside straight quotes
    "dated_event",      # date-anchored event references ("the March launch")
})


def parse_draft_for_claims(
    draft: str,
    dossier: str,
    *,
    register: str,
    embed_fn: Callable[[str], np.ndarray] | None = None,
) -> list[ParsedClaim]: ...
```

**Per-claim extraction** (Layer 3):

1. **`date_reference`** — regex matches ISO 8601 dates (`\d{4}-\d{2}-\d{2}`), month-year phrases (`April 2026`), quarter phrases (`Q[1-4] 20\d{2}`), and relative-time phrases (`last week`, `last month`, `this week`, `yesterday`, `last quarter`, etc.).
2. **`named_entity`** — heuristic: a multi-word title-case span (≥2 capitalized words in sequence; ≥1 word ≥3 chars) where the first word is not a sentence-starter. Stopwords (`I`, `My`, `Your`, `We`, `The`, `An`, `A`, `Hi`, `Hey`, `Dear`) filter false-positives. Single-word entities are deferred (false-positive rate too high for v1).
3. **`you_phrase`** — regex matches `you (posted|mentioned|launched|wrote|said|shared|tweeted|announced|raised|hired|fired|joined|left|built|shipped|released|published|noted|claimed|argued)\b[^.!?]*[.!?]` (the verb list comes from the SKILL.md's "vulnerability-signal-required; vertical-specific Q1" register guidance — the LLM-flavored you-phrases that need citation).
4. **`quoted_text`** — straight-quote spans (`"..."` or `'...'`); markdown-bold (`**...**`) is NOT a claim (it's emphasis).
5. **`dated_event`** — the intersection: a named entity within 5 tokens of a date reference (`the March launch`, `their Q1 announcement`, `Apr 2026 raise`).

**Per-claim citation cross-reference** (Layer 3):

For each extracted claim, the parser searches the dossier for a matching anchor:

* **Markdown footnote-style anchors** — `[1]`, `[N]` numeric references; `[link](url)` markdown links; bare URLs (`http://...`).
* **Per-section headers** — the dossier's `## Recent posts` / `## Funding history` / etc. headers; a claim's `claim_text` matching a phrase in a section's body counts as cited (the section's header URL is the `citation_anchor`).
* **Verbatim quote match** — for `quoted_text` claims, the dossier MUST contain the exact quote (token-for-token); fuzzy match defers to Week 8+.

The cross-reference is deterministic (substring + regex; no encoding at Week 6). The `embed_fn` kwarg is PRE-INSTALLED in the signature as TEST-ONLY per D218 — Week 6's body does NOT call it; Week 8+ extension uses it for fuzzy-match scoring against the dossier's per-anchor body.

**Cited vs uncited decision:**

* `citation_anchor is not None` → cited (the dossier supports the claim).
* `citation_anchor is None` → uncited (the parser found NO matching anchor in the dossier).

**Why deterministic regex-based per-claim-type extraction at Week 6 (rejected: LLM-based per-claim classification; rejected: per-claim NER via spaCy; rejected: defer Layer 3 to Week 8+; rejected: ship Layer 3 with fuzzy-match-encoding default-on).**

* **Deterministic regex-based extraction** matches the framework's reproducibility invariant per ADR-0013 D24 — the parser's per-call output is deterministic from `(draft, dossier, register)`; no LLM call introduces stochasticity. The Pillar D `reply_classifier`'s per-rule regex extraction precedent applies — the per-pattern surface IS the operator-readable contract.
* **LLM-based per-claim classification** is rejected because (a) per-call cost is non-zero (~$0.002/draft via Sonnet); for an operator drafting 10/day this is ~$0.02/day or ~$7/year of per-draft LLM cost; (b) reproducibility violation — the same `(draft, dossier)` would surface different `uncited_claims` across calls; (c) the gate's load-bearing property is BEHAVIORAL CONSISTENCY (the operator should be able to know in advance which claims the gate will catch). Pillar F Week 8+ MAY surface a per-claim LLM-classification override as an opt-in extension IF false-positive rates from the regex baseline are too high; Week 6 ships the deterministic baseline.
* **Per-claim NER via spaCy** is rejected because (a) spaCy is a new framework dependency (the orchestrator today has zero NLP-library surface); (b) per-call load cost (~200-500ms first call); (c) the per-NER precision is not better than the regex heuristic for cold-pitch / congrats register prose (LLM-flavored drafts have predictable patterns).
* **Defer Layer 3 to Week 8+** is rejected because the Week 1 test stub at `test_draft_with_uncited_claim_fails_gate` was scheduled to un-skip at Week 6 per ADR-0038 D180 Layer 1 description + the per-week handoff convention; deferring would slip the stub's behavioral commitment by ≥2 weeks + delay the FIVE-layer defense's first behavioral surface.
* **Ship Layer 3 with fuzzy-match-encoding default-on** is rejected because (a) encoding cost (~5-15ms per claim × N claims × 2 sides per cross-reference = ~50-300ms per parse); (b) the deterministic baseline's false-positive rate is unmeasured at Week 6 — shipping the encoding default-on commits to a stochastic-comparison baseline before the deterministic baseline's measurement; (c) the encoding seam ships pre-installed per D218 — Week 8+ flips the default after per-corpus measurement.

### D215. Per-claim threshold consumption — Week 4 substrate

The Week 4 threshold loader's `get_voice_threshold_for_register(register=<draft-register>)` per ADR-0041 D204 is THE per-claim threshold source. `score_draft(draft, dossier, *, register, channel)` consults the loader ONCE per call + stamps the per-register threshold on the `DraftQualityResult.threshold` field. The Week 4 loader's signature is UNCHANGED at Week 6 — Week 6 is a consumer, not a surface-mutator.

**Per-call dispatch:**

```python
def score_draft(
    draft: str,
    dossier: str,
    *,
    register: str,
    channel: str,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
) -> DraftQualityResult:
    # 1. Validate register + channel BEFORE parser load (closed-enum).
    # 2. Resolve threshold via Week 4 loader.
    # 3. Parse + cross-reference (Layer 3).
    # 4. Decide state ("ready" if uncited empty; "refused" if non-empty).
    # 5. Construct DraftQualityResult (Layer 2 invariant runs).
    ...
```

**Per-register threshold semantics (Week 6 simple gate):**

At Week 6 the threshold is a binary gate — the per-register threshold IS the refusal cutoff (uncited_claims non-empty → refused, REGARDLESS of the per-register threshold value at Week 6). The threshold field is STAMPED on the result for operator-visible audit AND for the Week 8+ fidelity-scoring extension's per-claim severity weighting. At Week 6 the per-register threshold's role is operator-visible (the field appears in the `hallucination_detected` event); the per-claim severity weighting against the threshold lands at Week 8+.

The decision to STAMP-but-not-CONSUME the per-register threshold at Week 6 is the per-Layer ship trajectory pinned by ADR-0038 D180: Week 6 ships Layers 2 + 3 (construction-time + parse-level); Week 8+ ships the fidelity-scoring primitive that consumes the per-register threshold for per-draft severity weighting; Week 10 ships Layer 4 (post-engine guard) that consumes the per-register threshold as a per-event emit decision; Week 12 ships Layer 5 (reconcile heal-pass) that consumes the per-register threshold as a per-Person advancement decision.

**Why stamp-but-not-consume at Week 6 (rejected: consume the per-register threshold for per-claim severity weighting at Week 6; rejected: omit the threshold field from the result; rejected: split per-claim thresholds from per-draft thresholds).**

* **Stamp-but-not-consume** lands the threshold-field surface at Week 6 so downstream consumers (Week 8+ scoring; Week 10 emit guard) read against a stable shape; the consumption logic ships per-Layer per the D180 trajectory. The asymmetric ship pattern matches the framework's Pillar E `tier_assignment` precedent — the `suggested_tier` field landed at Week 6-8 with the tier-stamping behavior; the per-tier downstream consumers (Pillar A `tier` rule per ADR-0007) consumed at Week 1+.
* **Consume for per-claim severity weighting at Week 6** is rejected because per-claim severity weighting requires a per-claim fidelity score (the encoding-based comparison against the dossier's anchor body) — the fidelity-scoring primitive ships at Week 8+ per ADR-0038 §Existing-operator seed. Bringing the per-claim severity weighting into Week 6 would require either (a) shipping the fidelity-scoring primitive's substrate at Week 6 (scope creep — Week 6 ships hallucination-detection Layers 2-3 per D180, not fidelity-scoring) or (b) faking per-claim scores via the deterministic parser's output (a heuristic that compounds with the parser's false-positive rate — operator-confusing).
* **Omit the threshold field from the result** is rejected because future consumers (Week 8+ fidelity-scoring; Week 10 Layer 4 emit guard; Week 12 Layer 5 reconcile pass) need the per-register threshold at result-inspection time without a second loader call. Stamping at construction amortizes the loader call to ONCE per per-draft pipeline; downstream consumers read the field directly.
* **Split per-claim thresholds from per-draft thresholds** is rejected because the per-register threshold IS per-draft per ADR-0038 D184(a)'s "per-draft float in `[0.0, 1.0]`" naming. Per-claim sub-thresholds (e.g., a date_reference claim weights X vs a named_entity claim weights Y) are operator-deferred to Pillar F Week 8+ per the per-week design; Week 6 stays per-draft.

### D216. `hallucination_detected` event-payload factory

The factory per ADR-0038 D182:

```python
def build_hallucination_detected_payload(
    *,
    person_id: str | None,
    result: DraftQualityResult,
    channel: str,                    # required, in CHANNELS
    register: str,                   # required, in REGISTERS
) -> dict: ...
```

Event shape:

```text
type:           hallucination_detected
person_id       (the prospect the draft targets; None for ad-hoc validation)
draft_hash      (sha256:<hex> of the draft body — NOT the raw draft)
register        (closed-enum per ADR-0038 D178)
channel         (closed-enum per ADR-0014 D33)
threshold       (the per-register threshold consulted per D215)
uncited_claims  (list of {claim_type, claim_text, citation_anchor: None} tuples)
_emitted_by     ("draft_quality" per ADR-0010 D17)
```

**Privacy-respecting per I8 + ADR-0038 §Compliance with invariants:**

* **Raw draft body MUST NOT appear in the payload.** The draft is sha256-hashed; operators can deterministically re-hash a draft text + grep the ledger for matches without exposing the draft body. Mirrors `voice_exemplar_retrieved`'s query-hash posture per ADR-0039 D189.
* **Per-claim trace IS in the payload** — `claim_text` is the draft's literal claim span (operator-visible diagnostic for "which claim did the gate catch"). This is NOT a privacy violation: the claim_text is the draft's content that the operator wrote; the operator needs to see WHICH span the gate caught to remediate. The dossier content is NOT in the payload (the `citation_anchor` for cited claims is the URL OR line-ref, not the dossier body).
* **`uncited_claims` IS the payload's payload** — emit-only-on-uncited per D219 means the per-claim trace is the load-bearing diagnostic. An empty `uncited_claims` would never surface in the event (the accept-case doesn't emit).

**Refuse-loud-on-unknown** — `channel` not in `CHANNELS` raises `ValueError`; `register` not in `REGISTERS` raises `ValueError`. Construction-site refuse-loud is symmetric to `DraftQualityResult.__post_init__`.

**`uncited_claims` non-empty REQUIRED** — the factory refuses construction when `result.uncited_claims` is empty (the accept-case should not flow through the factory; per D219 the accept-case is the silent default). Construction-site refuse-loud catches caller bugs where the accept-case incorrectly invokes the factory.

**Why build-then-append separation (rejected: emit-inside-score_draft; rejected: factory-returns-Event; rejected: skip-factory-altogether; rejected: factory accepts the event AND the dossier content for full provenance).**

* **Build-then-append separation matches the Pillar E + Pillar F Week 2 precedent** per ADR-0033 D150 + ADR-0034 D155 + ADR-0035 D161 + ADR-0039 D189 — the factory builds the dict; the caller appends to the ledger; the dry-run path skips the append. The CLI's `--apply` flag controls the live-emit per D219; the same factory is reused for the dry-run JSON output.
* **Emit-inside-score_draft** couples the read path to a write side effect — operators calling `score_draft` for a sanity check (or for a Week 8+ fidelity-scoring extension that calls `score_draft` upstream) would un-intendedly write to the ledger; the read/write separation is the I1 invariant's structural commitment.
* **Factory returns `Event` instance, not dict** is rejected per ADR-0039 D189-Alt2 — Pillar E + Pillar F Week 2 factories return dicts; the convention is consistent.
* **Skip the factory** is rejected per ADR-0039 D189-Alt3 — schema drift across callers; the Pillar E + Pillar F precedent is a single factory per event class.
* **Factory accepts the dossier content for full provenance** is rejected because the dossier may contain operator-confidential research (per ADR-0038 D182 §category 8) + the per-event ledger size grows linearly with dossier size; the per-anchor URL OR line-ref is sufficient for operator-side audit (operators look up the dossier directly when inspecting an event).

### D217. `/draft-outreach` SKILL.md Phase 5 extension — P2-B carry-forward

The SKILL.md Phase 5 (humanizer-checklist pass) extends with the hallucination-detection gate dispatch. The integration shape:

* Phase 5 currently runs the per-register anti-tell checklist + reports green/yellow/red per check.
* Phase 5 EXTENDS with a new step at the END of Phase 5 (after the existing humanizer-check completes): invoke `python orchestrator/draft_quality.py parse --draft-path /tmp/draft.txt --research-dossier-path <dossier-path> --register <reg> --channel <ch> --json [--apply]` + read the result.
* **The gate's verdict drives Phase 6's `pipeline_stage:` advancement:**
  * `state == "ready"` (uncited empty) → Phase 6 proceeds; Touch note's `voice_rules_check: passed` continues; `pipeline_stage: ready` advances.
  * `state == "refused"` (uncited non-empty) → Phase 6 REFUSES to advance to `pipeline_stage: ready`. The Touch note's frontmatter gets `pipeline_stage: drafted` (NOT `ready`) + `hallucination_check: failed` + an operator-readable per-claim trace dropped into the Touch note's body under a new "Hallucination gate findings" section. The operator decides whether to fix the draft or stamp an override.

The dossier path is resolved per the existing `/research-prospect` skill's dossier-emission convention: the Phase 1 dossier lands at the Person note's body OR at a separate brief file when `--call-prep` is set. Phase 5's gate invocation reads the same dossier the draft was scaffolded against (Phase 3's input).

**The operator-override surface:** an operator who disagrees with the gate's verdict (e.g., a paraphrased citation the deterministic parser didn't match) can stamp `hallucination_check_override: true` + a `hallucination_check_override_reason: "<rationale>"` field on the Touch note's frontmatter. The override surfaces in the ledger via a future Pillar F Week 8+ event class extension (TBD per the per-week design); at Week 6 the override is operator-stamped at the Touch note + does NOT auto-clear the gate's refusal (operators MUST also manually advance `pipeline_stage: ready` after stamping the override).

**Why land the SKILL.md Phase 5 extension at Week 6 (rejected: defer the SKILL.md extension to Week 10 when Layer 4 lands; rejected: ship the gate as a Phase 5.5 NEW phase; rejected: bypass the SKILL.md + ship gate-as-Touch-note-template-only).**

* **Land at Week 6** matches the Pillar F Week 2 precedent at D191 — the SKILL.md Phase 4 integration landed AT the primitive's ship week. The Week 1 audit's P2-B carry-forward is explicitly LOAD-BEARING for Week 6 per the handoff convention; deferring would create the SKILL.md drift the per-week reviewer flagged at Week 1.
* **Defer the SKILL.md extension to Week 10** is rejected because the Week 1 audit's P2-B item names Week 6 as the ship week; deferring would push operators using the skill to draft with NO hallucination-detection gate for FIVE additional weeks. The framework's I7 invariant (refuse-loud on operator misconfiguration) extends to the operator-side workflow — the SKILL.md is the operator's primary interface; landing the gate at the primitive's ship week is the consistent posture.
* **Ship the gate as a Phase 5.5 NEW phase** is rejected because Phase 5 is the existing "anti-tell + gate-checks" phase by convention; adding a Phase 5.5 (between humanizer-check + Phase 6 send-mechanics) creates a new phase boundary that operators learning the skill would parse as a structural change. Extending Phase 5 with a new step preserves the per-phase convention + matches the per-existing-phase per-step extension pattern (Phase 4 currently has Step 1 / Step 2 / Step 3; Phase 5 can extend with a new step after the existing checklist).
* **Bypass SKILL.md + ship gate-as-Touch-note-template-only** is rejected because the Touch note template is operator-modifiable; relying on the template alone leaves the gate invocation operator-discretionary. The SKILL.md is the operator-deliberate flow; the gate is the framework's structural commitment.

### D218. TEST-ONLY `embed_fn` seam preservation — FIRST non-N/A verification at a new encoding surface

The TEST-ONLY `embed_fn` injection seam (Week 2 audit's P3-B carry-forward; reaffirmed at Week 3 per ADR-0040 D197; verified N/A at Week 4 per ADR-0041 D205; verified N/A at Week 5 per ADR-0042 D211) **LANDS its first non-N/A verification at Week 6**.

The Week 6 primitive's `parse_draft_for_claims` + `score_draft` accept `embed_fn: Callable[[str], np.ndarray] | None = None` per D214's signature. **The Week 6 default code path does NOT encode** — the parser is deterministic (regex-based per-claim extraction; substring + regex cross-reference against the dossier). The `embed_fn` kwarg is PRE-INSTALLED in the signature with the seam labeled TEST-ONLY in the docstring; Week 8+ ships the fuzzy-match scoring extension that actually consumes the encoder.

**The seam preservation discipline at Week 6:**

* `embed_fn` is in BOTH `parse_draft_for_claims` AND `score_draft` signatures.
* Each docstring labels the kwarg as TEST-ONLY with explicit naming of the Week 8+ consumer.
* The CLI does NOT surface `--embed-fn` per the security + audit-confusion rationale at ADR-0040 D197 + ADR-0041 D205 + ADR-0042 D211 (arbitrary `embed_fn = "module:fn"` imports user-supplied code; per-event audit can't recover which encoder ran).
* The seam is verified by `test_draft_quality_primitive_preserves_test_only_embed_fn_seam` (inspects both public signatures' parameter list for `embed_fn`).
* The CLI is verified by `test_draft_quality_cli_has_no_embed_fn_flag` (inspects the subcommand's `--help` output + asserts `--embed-fn` is absent).

**This is the FIRST non-N/A verification of the seam at a new encoding surface.** Weeks 4 + 5 were N/A (config-loader + read-only-CLI). Week 6 ships the encoding-extension seam pre-installed; Week 8+ ships the encoding behavior; the per-week reviewer's checklist row at every subsequent Pillar F week verifies the seam stays TEST-ONLY + CLI-absent.

**Why pre-install the seam at Week 6 even though Week 6's parser doesn't encode (rejected: omit the kwarg from the Week 6 signature + add it at Week 8+; rejected: surface the kwarg via CLI; rejected: remove the seam entirely + monkey-patch in tests).**

* **Pre-install at Week 6** lands the signature shape for Week 8+ consumers; future per-claim fuzzy-match scoring tests at Week 8+ can inject deterministic encoders without rewriting the test suite's per-call construction. The seam's per-test cost amortization is the load-bearing property — Week 8+ tests will hit the seam at scale (per-claim × per-corpus × per-test).
* **Add the kwarg at Week 8+** is rejected because the signature would change between Week 6 + Week 8+ (a kwarg addition is a soft backwards-compat shift but every consumer testing the Week 6 parser would need to add the kwarg-pass at Week 8+ adoption time). The framework convention is to ship the test-injection seam AT the primitive's ship time (Pillar F Week 2's `retrieve_voice_exemplars` shipped the seam at its first ship per ADR-0039 D188; Week 6 mirrors).
* **Surface the kwarg via CLI** is rejected per ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1 — security concern (arbitrary `embed_fn` injection at parse time runs user-supplied code) + audit confusion (the per-event ledger surface couldn't recover which encoder ran for a given parse).
* **Remove the seam entirely + monkey-patch in tests** is rejected per ADR-0040 D197-Alt2 — test isolation via monkey-patching is fragile + harder to reason about than the explicit kwarg passthrough. The seam is TEST-ONLY (per the docstring); the kwarg's presence is bounded by the docstring's label.

### D219. `hallucination_detected` event emit-cardinality — emit-only-on-uncited

The `hallucination_detected` event class is emitted ONLY when `uncited_claims` is non-empty (the accept-case is the silent default; the refuse-case is the loud event). The CLI's `--apply` flag controls whether the event lands in the ledger when the refuse-case fires; the accept-case never emits regardless of `--apply`.

**Per-call emit-decision matrix:**

| `uncited_claims` | `--apply` flag | Event emitted? |
|---|---|---|
| empty | False (dry-run) | No (accept-case silent) |
| empty | True | No (accept-case silent regardless of `--apply`) |
| non-empty | False (dry-run) | No (dry-run reports verdict; doesn't write) |
| non-empty | True | YES (refuse-case loud) |

**The asymmetric-failure-cost calculus mirrors the Pillar D Week 4-5 `suppression_added` event's emit-only-on-add per ADR-0028 D116:**

* Emit-on-every-parse would inflate per-event volume + ledger growth for the typical accept-case (most drafts cleanly cite their claims). The per-Person Pillar G dashboard's per-event count would surface noise (the per-day `hallucination_detected` count would be dominated by accept-cases that don't surface a refusal signal).
* Emit-only-on-uncited preserves the per-event Pillar G dashboard's "every emitted event signals a refusal" property; operators inspecting the dashboard see refusals only.
* The dry-run path (`--apply` not set) prints the verdict to stdout/JSON without writing — operators inspect via CLI without polluting the ledger.

**Why emit-only-on-uncited (rejected: emit-on-every-parse; rejected: emit-only-on-uncited-AND-apply-true [trivially symmetric — that's D219's choice]; rejected: emit the accept-case as a separate `draft_quality_validated` event class).**

* **Emit-only-on-uncited** matches the asymmetric-failure-cost calculus + the Pillar D `suppression_added` precedent per ADR-0028 D116 — refuse-loud events are the load-bearing diagnostic; accept-case events inflate volume without surfacing actionable signal.
* **Emit-on-every-parse** is rejected per the asymmetric-failure-cost above — the per-event Pillar G dashboard's signal-to-noise ratio degrades when accept-cases dominate.
* **Emit the accept-case as a separate `draft_quality_validated` event class** is rejected as Week 6 scope creep — adding a second event class at Week 6 would extend the cross-pillar audit's category 8 surface AND require a per-event privacy invariant for the validated payload AND need the Pillar G dashboard to consume two event classes. The framework convention is to ship ONE event class per primitive at the primitive's first ship week (Pillar E Week 9-11 shipped ONE event class per primitive; Pillar F Week 2 shipped ONE `voice_exemplar_retrieved` event). Week 6 mirrors with one `hallucination_detected` event.

The Week 8+ fidelity-scoring primitive may ship a `draft_quality_scored` event per ADR-0038 D182 (already named at Week 1) — that event covers the per-draft fidelity score IN THE ACCEPT-CASE (when fidelity is measured). The two events are complementary: `hallucination_detected` covers the per-draft refusal at Layer 2-3 (Week 6); `draft_quality_scored` covers the per-draft accept-case scoring at Week 8+.

## Alternatives considered

### D212-Alt1: Extension of `orchestrator/voice_corpus.py`

Land the Week 6 hallucination-detection primitive in the existing `voice_corpus.py` module (alongside the retrieval primitive + per-register adapters + threshold loader). **Rejected** per D212 — `voice_corpus.py` is already ~2170 LOC post-Week-5; ~400-600 LOC growth would push past ~2600 LOC. The framework convention is per-primitive separation; Pillar E shipped four sibling modules.

### D212-Alt2: Subpackage `orchestrator/draft_quality/`

A package directory with per-Layer modules + shared `__init__.py`. **Rejected** per D212 + ADR-0038 D181-Alt1 + ADR-0039 D185-Alt1 — over-organization; Week 6 ships one module; future Pillar F weeks' extensions land at the existing module.

### D212-Alt3: Per-Layer files at `orchestrator/draft_quality/layer2.py` + `layer3.py`

Split Layer 2 invariants + Layer 3 parser into separate files. **Rejected** per D212 — Layers 2 + 3 are structurally bound (Layer 3 produces the `uncited_claims` field; Layer 2 consumes it); splitting inflates the import surface for no behavioral benefit.

### D213-Alt1: Mutable dataclass with list fields

A non-frozen `DraftQualityResult` with `list[ParsedClaim]` fields. **Rejected** per D213 — operator-side mutations across the parse → factory → emit boundary could silently invalidate the construction-time invariant; tuples + frozen prevent the bypass at the language level.

### D213-Alt2: Pydantic-validated dataclass

`pydantic.BaseModel`-based schema. **Rejected** per ADR-0039 D186-Alt2 — adds pydantic as a fifth framework dependency; the explicit `__post_init__` is ~30 LOC + matches Pillar E + Pillar F Week 2 convention.

### D213-Alt3: Skip the construction-time invariant + rely on parse-level guard only

Drop Layer 2 entirely; ship only Layer 3. **Rejected** per D213 — the FIVE-layer defense per ADR-0038 D180 is the structural commitment; landing only Layer 3 weakens the construction-time refuse-loud surface. Construction-time defense catches the contributor who bypasses the parser entirely.

### D213-Alt4: Dict-only — skip the dataclass

Pass `dict` everywhere; no typed surface. **Rejected** per ADR-0039 D186-Alt3 — loses IDE-assisted authoring for downstream consumers (Week 10 event-emitter; Week 12 reconcile pass).

### D214-Alt1: LLM-based per-claim classification

Each claim's `claim_type` + cited/uncited decision comes from a per-claim LLM call (e.g., Sonnet via the Anthropic SDK). **Rejected** per D214 — per-call cost (~$0.002/draft), reproducibility violation (same `(draft, dossier)` surfaces different `uncited_claims` across calls), gate's load-bearing property is BEHAVIORAL CONSISTENCY.

### D214-Alt2: Per-claim NER via spaCy

Named-entity recognition via spaCy. **Rejected** per D214 — adds spaCy as a new framework dependency; per-call load cost; per-NER precision not better than regex heuristic for cold-pitch / congrats register prose.

### D214-Alt3: Defer Layer 3 to Week 8+

Ship the Layer 2 dataclass at Week 6; defer the parser to Week 8+. **Rejected** per D214 — the Week 1 test stub at `test_draft_with_uncited_claim_fails_gate` was scheduled to un-skip at Week 6 per ADR-0038 D180 Layer 1 description; deferring slips the stub's behavioral commitment + delays the FIVE-layer defense's first behavioral surface.

### D214-Alt4: Ship Layer 3 with fuzzy-match-encoding default-on

Layer 3's per-claim cross-reference uses `embed_fn`-based fuzzy matching by default at Week 6. **Rejected** per D214 — encoding cost; the deterministic baseline's false-positive rate is unmeasured; the encoding seam ships pre-installed per D218 + Week 8+ flips the default.

### D215-Alt1: Consume the per-register threshold for per-claim severity weighting at Week 6

Layer 3 uses the per-register threshold to weight per-claim severity scores; the result's gate decision depends on the per-claim weighted sum vs the threshold. **Rejected** per D215 — per-claim severity weighting requires a per-claim fidelity score (encoding-based comparison); the fidelity-scoring primitive ships at Week 8+ per ADR-0038 §Existing-operator seed.

### D215-Alt2: Omit the threshold field from the result

The `DraftQualityResult` does NOT carry the per-register threshold. **Rejected** per D215 — future consumers (Week 8+ scoring; Week 10 emit guard; Week 12 reconcile pass) need the per-register threshold at result-inspection time without a second loader call.

### D215-Alt3: Split per-claim thresholds from per-draft thresholds

Per-claim sub-thresholds (per-claim-type) vs per-draft thresholds. **Rejected** per D215 — per ADR-0038 D184(a) the threshold is per-draft; per-claim sub-thresholds are Pillar F Week 8+ scope.

### D216-Alt1: Emit-inside-score_draft

`score_draft` writes the event to the ledger before returning. **Rejected** per D216 — couples read path to write side effect; violates I1.

### D216-Alt2: Factory returns `Event` instance

Return `Ledger.Event` instead of a dict. **Rejected** per ADR-0039 D189-Alt2 — Pillar E + Pillar F Week 2 factories return dicts; convention is consistent.

### D216-Alt3: Skip the factory

Document the event shape; let callers build the dict. **Rejected** per ADR-0039 D189-Alt3 — schema drift across callers.

### D216-Alt4: Factory accepts the dossier content for full provenance

Payload includes the dossier body. **Rejected** per D216 — privacy concern (dossier may contain operator-confidential research per ADR-0038 D182 §category 8); per-event ledger size grows linearly with dossier size.

### D217-Alt1: Defer the SKILL.md extension to Week 10

Wait to extend SKILL.md Phase 5 until Layer 4 (post-engine guard) lands. **Rejected** per D217 — the Week 1 audit's P2-B item explicitly names Week 6 as the ship week.

### D217-Alt2: Ship the gate as a Phase 5.5 NEW phase

Add Phase 5.5 between humanizer-check + Phase 6. **Rejected** per D217 — extending Phase 5 preserves the per-phase convention; adding Phase 5.5 creates structural-change confusion for operators.

### D217-Alt3: Bypass SKILL.md + ship gate-as-Touch-note-template-only

The Touch note template carries the gate-invocation prose; the SKILL.md is unchanged. **Rejected** per D217 — the Touch note template is operator-modifiable; relying on the template leaves the gate invocation operator-discretionary.

### D218-Alt1: Omit the `embed_fn` kwarg from the Week 6 signature

Wait to add the kwarg at Week 8+ when the encoding behavior ships. **Rejected** per D218 — signature would change between Week 6 + Week 8+; every consumer testing the Week 6 parser would need to add the kwarg-pass at Week 8+ adoption time.

### D218-Alt2: Surface the kwarg via CLI

Add `--embed-fn module:fn` to `python orchestrator/draft_quality.py parse`. **Rejected** per ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1 — security concern + audit confusion.

### D218-Alt3: Remove the seam entirely + monkey-patch in tests

The Week 6 parser does not accept `embed_fn`; tests monkey-patch the encoder. **Rejected** per ADR-0040 D197-Alt2 — test isolation via monkey-patching is fragile + harder to reason about than the explicit kwarg passthrough.

### D219-Alt1: Emit-on-every-parse

Emit a `hallucination_detected` event for EVERY parse (accept-case included). **Rejected** per D219 — per-event volume inflation; Pillar G dashboard signal-to-noise degrades.

### D219-Alt2: Emit the accept-case as a separate `draft_quality_validated` event class

Two event classes — one for refuse-case, one for accept-case. **Rejected** per D219 — Week 6 scope creep; the Week 8+ `draft_quality_scored` event per ADR-0038 D182 covers the accept-case scoring.

### D219-Alt3: Always-emit + flag accept vs refuse via a field on the event

One event class; payload carries `verdict: "accept"|"refuse"`. **Rejected** per D219 — same per-event volume inflation problem as Alt1; the per-Pillar-G dashboard's per-event count loses meaning.

## Consequences

### Positive consequences

* **The hallucination-detection FIVE-layer defense's first behavioral surface ships at Week 6.** Layers 2 + 3 land in one commit; the Week 1 test stub un-skips; the per-week reviewer's audit pass walks the new primitive against the existing categories.
* **The Week 4 threshold infrastructure's first consumer ships.** `get_voice_threshold_for_register` per ADR-0041 D204 is consumed by the Week 6 primitive's `score_draft`; the per-register threshold field surfaces on `DraftQualityResult` + the `hallucination_detected` event.
* **The Week 1 audit's P2-B carry-forward closes.** The `/draft-outreach` SKILL.md Phase 5 extension lands at Week 6 per D217; the operator-side flow's hallucination-detection gate is the structural surface.
* **The TEST-ONLY `embed_fn` seam's first non-N/A verification lands.** The Week 6 primitive's encoding extension seam ships pre-installed per D218; the per-week reviewer's checklist row's compounding verification continues.
* **The `hallucination_detected` event class's emit-only-on-uncited posture preserves the Pillar G dashboard's signal-to-noise ratio.** Refuse-loud events are the load-bearing diagnostic; accept-case silence preserves the per-event count's meaning.
* **The per-primitive flat-module convention extends to a fifth orchestrator/ sibling.** `orchestrator/draft_quality.py` joins the four Pillar E primitives' modules + the Pillar F Week 2 voice corpus primitive's module; the convention compounds.

### Negative consequences

* **Test count grows by ~50-80 tests** (TestDraftQualityResult + TestParseDraftForClaims + TestScoreDraft + TestBuildHallucinationDetectedPayload + TestCLIParse + TestSeamPreservation classes). Cumulative: 2884 (post-Week-5-follow-up) → ~2934-2964 (post-Week-6). The growth is bounded; per-test coverage targets the per-claim-type extraction × per-claim cross-reference × per-Layer invariants.
* **`orchestrator/draft_quality.py` ships at ~400-600 LOC.** The growth is intentional — the Week 6 primitive lands all-at-once with Layer 2 dataclass + Layer 3 parser + cross-reference logic + event factory + CLI.
* **A NEW orchestrator/ sibling module ships at Week 6.** Operators learning the framework via `ls orchestrator/` see one more file; the per-primitive separation is operator-readable + matches the framework convention.
* **The `/draft-outreach` SKILL.md's Phase 5 gains a new step + a new operator-side workflow.** Operators using the skill experience the gate's refuse-loud at the FIRST parse where their draft has an uncited claim. The remediation surface is operator-deliberate (stamp override OR fix the draft); the framework defaults to false-positive.

### Risks

The asymmetric-failure-cost calculus carries:

* **The deterministic parser's per-claim false-positive rate is unmeasured at Week 6 (P2):** Operators may experience the gate flagging cited claims (e.g., paraphrased dossier content; synonymous named entities). **Bounded by** (a) the operator-override surface per D217 (stamp `hallucination_check_override: true` on the Touch note + manually advance pipeline_stage); (b) the per-week reviewer's checklist row at Week 8+ to measure per-corpus false-positive rates BEFORE Week 8+ ships the fuzzy-match scoring extension; (c) the framework convention to default toward false-positive at the legal-and-brand-liability boundary per ADR-0038 D184(b).

* **The `parse_draft_for_claims` regex set is incomplete (P3):** Operators may surface claim shapes the Week 6 regex doesn't cover (e.g., new you-phrase verbs; unusual date formats; non-English entities). **Bounded by** (a) the closed-set `CLAIM_TYPES` enum naming the supported types; (b) the per-claim regex extensions land at subsequent Pillar F weeks via ADR amendments; (c) the operator-override surface per D217 is the per-call escape hatch.

* **The `embed_fn` seam's misuse at Week 8+ (P3):** A future Pillar F contributor might surface the seam via CLI at Week 8+ when the encoding behavior ships. **Bounded by** (a) the per-week reviewer's checklist row at every subsequent Pillar F week verifying the CLI-absence; (b) the documented Pillar I CLI tooling extension as the structured surface for advanced encoder injection per ADR-0038 §Downstream pillar impact.

* **The `hallucination_detected` event's per-Touch-note operator-visibility (P3):** Operators inspecting the ledger via `grep | jq` see the refusal event but may not know how to remediate. **Bounded by** the SKILL.md Phase 5 extension per D217 surfacing the per-claim trace + the override surface in the Touch note + the per-event payload carrying `claim_text` (the literal claim span) so operators identify the failing claim immediately.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The `hallucination_detected` event lands in the ledger per D216 + D219; the per-Touch-note `hallucination_check_override` is a denormalized view (the operator-visible remediation signal). The ledger remains the SoT for per-event data; the override Touch note field surfaces the override decision for downstream consumers.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The hallucination-detection gate is upstream of the send (gate fires at Phase 5; send fires at Phase 6); the gate's refusal blocks the send before two-phase commit fires.
* **I3 — Atomic per-Person enrollment.** Preserved. Week 6 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The gate is per-register + per-channel (the `DraftQualityResult` carries both); the per-event `channel` field stamps per ADR-0014 D33.
* **I5 — Migration framework discipline.** Preserved. Week 6 ships ZERO new migrations; pending count stays at 19. (Future Pillar F weeks MAY ship migrations for per-Touch-note hallucination-check annotation TBD per the per-week design; Week 6 ships the gate behavior + the operator-stamped Touch note convention without a vault migration.)
* **I6 — Channel-on-every-event invariant.** Preserved + EXTENDED. The new `hallucination_detected` event class stamps `channel: <draft-channel>` per ADR-0014 D33; the factory raises on unknown channel.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. Three new refuse-loud surfaces: (a) per-construction validation in `DraftQualityResult.__post_init__` (state=ready + uncited non-empty); (b) per-construction validation in `build_hallucination_detected_payload` (unknown channel/register; empty uncited_claims); (c) per-call validation in `score_draft` (unknown channel/register before parser load).
* **I8 — Privacy-respecting.** Preserved + EXTENDED. The `hallucination_detected` event carries `draft_hash` (NOT raw draft body) + per-claim `{claim_type, claim_text, citation_anchor}` triples (claim_text is the draft's literal claim — operator-visible diagnostic; the dossier content is NOT in the payload). Operators inspect draft content via the Touch note directly; the ledger event is hash-only for the draft body.

## Downstream pillar impact

* **Pillar F Week 7+ (hallucination-detection refinement).** Per-claim-type test corpora expansion + false-positive rate measurement against a per-corpus baseline. Week 6's parser ships the closed-set claim types; Week 7+ ships per-claim-type test corpora (synthetic adversarial drafts + dossier pairs per claim type) for false-positive rate measurement. The per-week author MAY extend `CLAIM_TYPES` IF the per-corpus measurement surfaces additional patterns; the extension lands via ADR amendment per the closed-enum convention.

* **Pillar F Week 8+ (fidelity-scoring primitive).** The fidelity-scoring primitive consumes `parse_draft_for_claims` for per-claim severity weighting + the `embed_fn` seam for per-claim fuzzy-match scoring against the dossier's per-anchor body. The Week 6 primitive's seam is the substrate; Week 8+ ships the consumer.

* **Pillar F Week 10 (Layer 4 post-engine guard).** The `draft_ready` event emit walks the per-Person `DraftQualityResult` (looked up via the Touch note's `hallucination_check` field or the per-Person `hallucination_detected` event in the ledger); refuses-loud when `uncited_claims` non-empty AND `hallucination_check_override` is NOT stamped. The Week 6 primitive's `DraftQualityResult` shape + the `hallucination_detected` event class are the consumer-side substrate.

* **Pillar F Week 12 (Layer 5 reconcile heal-pass).** The reconcile Pass C heal walks the per-Person `pipeline_stage: ready` advancement candidates + refuses when the linked draft's `draft_quality_scored` event carries `uncited_claims` non-empty AND `hallucination_check_override` is NOT stamped. The Week 6 primitive's event class is the consumer-side substrate.

* **Pillar G (Observability).** Dashboards consume `hallucination_detected` events for per-register refusal-rate analysis (per-day count by register; per-register per-claim-type breakdown). The cross-pillar audit's category 8 gates: dashboards aggregate by `register` + `channel` + per-claim-type + per-event count, NEVER by raw `draft_hash` or per-claim `claim_text` content (the dashboard's aggregation grain is operator-deliberate; the per-claim content is for per-Person inspection only).

* **Pillar H (Real-time + scale).** The per-call parse cost is O(N) over claim count × O(M) over dossier size for substring search. At v1 draft scale (~200-500 word drafts; ~5-10 claims per draft; ~5000-word dossiers) the cost is ~5-20ms per call. Pillar H optimizations (per-claim sparse indexing; pre-built dossier inverted index) are content-additive against the contract.

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions per ADR-0038 §Downstream pillar impact list MAY extend with `draft_quality benchmark --corpus-dir <path>` for per-corpus false-positive rate measurement IF operator demand materializes; `draft_quality doctor --person <id>` for per-Person hallucination-check audit IF operator demand materializes. Week 6 ships the per-call CLI only.

* **Pillar J (Compliance + audit).** Per-Person GDPR-purge extends to remove `hallucination_detected` events from the ledger (per-Person aggregate refusal-rate metrics survive; per-Person raw `draft_hash` + per-claim `claim_text` are purged). The per-Person purge path inspects the ledger's `_idx_person` index + filters by per-Person `person_id` + redacts.

## Migration / rollout

**Week 6 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 5 to Pillar F Week 6:

1. **Operator updates the framework** to Pillar F Week 6's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 6 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_draft_quality.py tests/test_multi_channel_coherence.py::TestHallucinationDetection -v`** to verify the new primitive's tests + the un-skipped coherence rows pass. Optional but recommended.
4. **Operator decides whether to opt in to the new SKILL.md Phase 5 extension.** Two paths:
   * **Path A (default at Week 6 — recommended):** Run `/draft-outreach` per the updated SKILL.md Phase 5 — the gate fires automatically; refusals surface in the Touch note. Operators stamp `hallucination_check_override: true` to override.
   * **Path B (opt-out via per-call):** Skip the gate by NOT invoking the `draft_quality parse` step at Phase 5. The gate is operator-discretionary at Week 6 (the SKILL.md describes the step; operators may bypass for legacy workflows). The bypass surface is operator-deferred to Pillar I per ADR-0038 §Downstream pillar impact — Pillar I MAY ship a `voice.hallucination_check_enabled: false` config flag IF operator demand materializes; Week 6 leaves the bypass operator-discretionary.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 7+ ships per-claim-type test corpora (no migration). Week 8+ ships fidelity-scoring + flips `voice.use_embedding_primitive` default + MAY ship `vault/0006_add_voice_fidelity_score` for per-Touch-note fidelity annotations (TBD per the per-week design). Week 10 ships Layer 4 (no migration; consumes the Week 6 event class). Week 12 ships Layer 5 + the binding exit-criterion test.

## Existing-operator seed

**Pillar F Week 6's operator-side disposition is content-additive at the library level + operator-recommended at the SKILL.md level.** The framework ships the primitive + the SKILL.md extension at one commit per D217; existing operators using `/draft-outreach` see the gate's behavior at the next invocation.

The operator-side trajectory (per-week ships across Pillar F Weeks 6-12):

* **Week 6 (this commit):** The Layer 2 + Layer 3 primitive ships at `orchestrator/draft_quality.py`. The SKILL.md's Phase 5 extends with the gate invocation per D217. Operators see the gate's refuse-loud at the FIRST parse where their draft has an uncited claim. The remediation surface is the operator-override stamp per D217.
* **Week 7+:** Per-claim-type test corpora expansion + false-positive rate measurement. The per-week author MAY extend `CLAIM_TYPES` via ADR amendment.
* **Week 8+:** Fidelity-scoring primitive ships at `orchestrator/fidelity_scoring.py` (or extension of `voice_corpus.py` per the per-week design). The `voice.use_embedding_primitive` default flips. The SKILL.md Phase 4 extends with per-register routing per ADR-0040 §Existing-operator seed.
* **Week 10:** Layer 4 (post-engine guard) ships per ADR-0038 D180. The `draft_ready` event emit walks the per-Person `hallucination_detected` events + refuses on uncited+no-override.
* **Week 12:** Layer 5 (reconcile heal-pass refusal) ships. Binding exit-criterion test un-skips. Pillar F flips to Stable.

**Operator action required at Week 6:** none. The framework upgrade is read-only with respect to operator state; the SKILL.md extension takes effect at next `/draft-outreach` invocation.

**Operator action recommended at Week 6:** run a sample `/draft-outreach` against a known cold-pitch draft to see the gate's behavior; inspect the per-claim trace in the Touch note's "Hallucination gate findings" section. Operators with established workflows continue unchanged (the gate is operator-discretionary at Week 6 per the Path B bypass surface).

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. **D180 (hallucination-detection FIVE-layer defense-in-depth) is THE binding text Week 6 implements** — Layers 2 + 3 land in this commit. **D184(b) (hallucination-detection invariant is FIVE-layer defense-in-depth per D180)** names the load-bearing legal-and-brand-liability gate analogous to CAN-SPAM per ADR-0025 D97. **D182 (cross-pillar integration audit + new event class names)** names `hallucination_detected` as the Week 6 event class.
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive. **D188 (`retrieve_voice_exemplars` per-call entry point with TEST-ONLY `embed_fn` seam in docstring)** is the structural reference for D218's seam preservation at the Week 6 encoding surface. **D189 (`build_voice_exemplar_retrieved_payload` factory)** is the structural reference for D216's `build_hallucination_detected_payload` factory + privacy-respecting payload posture.
- **ADR-0040 (D192-D198)** — Pillar F Week 3 per-register adapters. **D197 (TEST-ONLY `embed_fn` seam preservation reaffirmed at per-register adapter surfaces)** is the structural reference for D218's preservation at the Week 6 primitive's encoding surface (FIRST non-N/A verification at a new encoding surface).
- **ADR-0041 (D199-D205)** — Pillar F Week 4 per-register threshold infrastructure. **D204 (`get_voice_threshold_for_register` helper)** is THE LOAD-BEARING substrate Week 6 consumes via D215. **D205 (TEST-ONLY `embed_fn` N/A at threshold loader)** is the structural reference for D218's per-Pillar-F-week seam verification.
- **ADR-0042 (D206-D211)** — Pillar F Week 5 voice-thresholds CLI extension. **D211 (TEST-ONLY `embed_fn` N/A at CLI surface; carries forward to Week 6+)** names Week 6 as the FIRST non-N/A verification target — D218 lands the verification.
- **ADR-0036 (D166-D171)** — Pillar E Week 9-11 discovery_lineage stamping. **D166 (per-primitive flat-module convention)** is the structural reference for D212's `orchestrator/draft_quality.py` module placement. **D167 (per-field construction-time validation refuse-loud at construction site)** is the structural reference for D213's `DraftQualityResult.__post_init__` Layer 2 invariants.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier_assignment primitive. **D162 (graceful-degradation contract + the per-Person convenience surface)** is the structural reference for D215's per-call dispatch shape.
- **ADR-0033 (D149-D153)** — Pillar E Week 2 discovery_dedup primitive. **D150 (per-event factory + privacy-respecting payload)** is the structural reference for D216's event factory.
- **ADR-0028 (D116)** — Pillar D Week 4-5 suppression-write event class. **The emit-only-on-add posture** is the structural reference for D219's emit-only-on-uncited posture.
- **ADR-0014 (D33)** — Pillar C foundation. **The channel-on-every-event invariant** extends to the new `hallucination_detected` event class per D216.
- **ADR-0010 (D17)** — `_emitted_by` field convention. The `hallucination_detected` event stamps `_emitted_by: "draft_quality"` per D216.
- **ADR-0025 (D97)** — Pillar D Week 1 CAN-SPAM legal-liability gate. **The asymmetric-failure-cost calculus matches** — the hallucination-detection FIVE-layer defense per ADR-0038 D180 mirrors the CAN-SPAM defense's structural commitment per ADR-0025 D97.
- **ADR-0013 (D24)** — Reproducibility invariant. D214's deterministic regex-based parser preserves the invariant (the per-call output is deterministic from `(draft, dossier, register)`).
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §36+ extends with the Week 6 commit's audit verdict (the new primitive + the new event class + the SKILL.md Phase 5 extension + the closed-enum protection on `hallucination_detected.register` per ADR-0038 D178 + the TEST-ONLY `embed_fn` FIRST non-N/A verification at a new encoding surface).
- **`.planning/HANDOFF-pillar-f-week-6.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 7 trajectory.
- **`orchestrator/draft_quality.py`** (NEW) — the Week 6 primitive per D212-D219.
- **`tests/test_draft_quality.py`** (NEW) — the per-primitive unit tests (~50-80 tests covering Layer 2 invariants + Layer 3 parser + per-claim cross-reference + per-register threshold consumption + event factory + CLI smoke + TEST-ONLY embed_fn seam preservation).
- **`tests/test_multi_channel_coherence.py::TestHallucinationDetection`** — FOUR rows un-skipped at this Week 6 commit per ADR-0038 D180 Layer 1 description + the TestHallucinationDetection class docstring at lines 7204-7214: `test_draft_with_uncited_claim_fails_gate` (Layer 1 + Layer 3), `test_draft_with_cited_claims_passes_gate` (Layer 3 happy-path), `test_draft_quality_result_refuses_construction_on_uncited_with_ready` (Layer 2), `test_hallucination_detected_event_carries_uncited_claim_trace` (D182 event-shape pin).
- **`skills/draft-outreach/SKILL.md` §Phase 5** — extended with the hallucination-detection gate dispatch per D217 (closes Week 1 audit P2-B).
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 6 close summary.
- **`docs/adr/README.md`** — ADR-0043 row appended.
