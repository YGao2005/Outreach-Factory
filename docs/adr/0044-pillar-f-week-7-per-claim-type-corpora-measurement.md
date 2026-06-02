# ADR-0044: Pillar F Week 7 — per-claim-type test corpora + measurement primitive

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** F (Voice corpus + draft quality — Week 7 per-claim-type corpora + measurement primitive)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation; Week 2 (ADR-0039 D185-D191) shipped the embedding-retrieval primitive; Week 3 (ADR-0040 D192-D198) shipped the per-register adapters; Week 4 (ADR-0041 D199-D205) shipped the per-register threshold loader; Week 5 (ADR-0042 D206-D211) shipped the operator-facing thresholds CLI; **Week 6 (ADR-0043 D212-D219)** shipped the hallucination-detection Layer 2-3 primitive at `orchestrator/draft_quality.py` — the FIRST behavioral layers of the ADR-0038 D180 FIVE-layer defense. Week 6 ships at `f9d9e4b` + follow-up `7e6596e` (0 P1 + 4 P2 + 3 P3 addressed); 2973 tests passing.

The Week 6 commit's follow-up surfaced **R027 (per-claim false-positive rate)** as a Week 6-NEW risk per ADR-0043 §Risks: a deterministic regex-based parser will sometimes flag claims as uncited that ARE supported by the dossier (e.g., paraphrased citation, synonymous named entity). The framework biases toward false-positive (refuse-loud at the boundary) per the asymmetric-failure-cost calculus per ADR-0038 D180 + D184 — false-positive costs operator one stamp-override; false-negative ships an uncited claim. The Week 6 ADR pinned the per-claim-type calibration trajectory: "Pillar F Week 7+ MAY extend with per-claim-type test corpora + false-positive rate measurement against per-corpus baselines."

**Pillar F Week 7 ships THE per-claim-type measurement infrastructure** per ADR-0044. The infrastructure is the SUBSTRATE for two downstream concerns:

1. **R027 mitigation** — measurement-before-extension matches the framework's R024 mitigation discipline (the Week 4 threshold defaults are calibrated against Yang's curated corpus; Week 7's per-claim-type measurement is the analogous calibration for the Layer 3 parser). The Week 7 baseline rates surface where the deterministic parser has gaps; Week 8+/10+/12 refinements consume the baseline.
2. **Regression barriers for Weeks 8+/10/12** — every parser bug surfaces at the per-claim-type level before regressing Layer 4/5. The Week 8+ fidelity-scoring primitive's encoding behavior + Week 10 Layer 4 post-engine guard + Week 12 Layer 5 reconcile heal-pass refusal all consume the Layer 3 parser; the per-claim-type benchmark catches per-week regressions early.

Week 7 ships ONLY the corpus + the measurement primitive + the CLI surface + the benchmark tests. No new event classes; no new SKILL.md extensions (operator-deferred per the per-week-extension convention); no new migrations; no parser refinements (the deterministic Layer 3 baseline stays UNCHANGED at Week 7 — the corpus measures it).

The eight concerns this ADR resolves:

1. **The corpus file placement + structure must be pinned at Week 7** so subsequent Pillar F weeks (Week 8+ fidelity-scoring + Week 10 Layer 4 + Week 12 Layer 5) extend against a stable target. The corpus lives at `tests/fixtures/draft_quality_corpus/` sibling of `tests/fixtures/synthetic_pillar_b/` + `tests/fixtures/synthetic_pillar_d/` per the per-pillar fixture convention. **D220** pins.

2. **The per-claim-type partition strategy must be pinned at Week 7** — one YAML file per claim type in `CLAIM_TYPES` (per ADR-0043 D214's closed-enum), ~30+ pairs per file, ~50/50 ready/refused partition. **D221** pins.

3. **The per-pair schema + `CorpusPair` dataclass must be pinned at Week 7** so corpus drift surfaces via construction-time refuse-loud + the corpus is operator-readable. Mirrors Pillar D Week 12's corpus schema per ADR-0031 D136. **D222** pins.

4. **The measurement primitive + `CorpusMeasurement` dataclass must be pinned at Week 7** as THE per-claim-type measurement surface downstream Week 8+ + Week 10+/12 consumers compare baselines against. The dataclass carries TP/TN/FP/FN tallies + per-claim-type accuracy + FP_rate + FN_rate (the asymmetric-failure-cost rates per ADR-0038 D180 + D184). **D223** pins.

5. **The CLI `measure` subcommand must be pinned at Week 7** as operator-facing audit + tuning surface — operators MAY substitute `--corpus-dir <their-corpus>` to measure the parser against their own per-claim-type corpus. Pillar I per-tenant audit-tooling consumes via the CLI. **D224** pins.

6. **The per-claim-type regression-barrier rate bounds must be pinned at Week 7** as the Week 7 baseline + headroom for noise + minor parser refinements. The bounds tighten in subsequent Pillar F weeks per ADR-0038 D180's FIVE-layer trajectory. **D225** pins.

7. **The closed-enum protection on `claim_type` MUST extend to the corpus filename + the YAML's `claim_type` field + the CLI `--claim-type` argparse choices** per ADR-0043 D214's closed-enum discipline. Refuse-loud at every boundary. **D226** pins.

8. **The TEST-ONLY `embed_fn` seam preservation discipline EXTENDS to the Week 7 measurement primitive** per ADR-0043 D218 — the primitive passes the seam through to `score_draft`. The Week 7 corpus is DETERMINISTIC (no encoding at the measurement primitive's surface); the seam is reserved for the Week 8+ fidelity-scoring extension. **D227** pins.

Risks this ADR mitigates by design: **R027 (per-claim false-positive rate)** — the Week 7 corpus + measurement primitive ARE the addressing path. The Week 7 baseline rates surface where the deterministic parser has gaps; Week 8+/10+/12 refinements consume the baseline. **R024 (voice-corpus drift)** continues mitigated — the per-claim-type corpus is orthogonal to the voice corpus; the measurement primitive is read-only against the dossier + draft. **R025 (embedding-cost runaway)** continues mitigated — the measurement primitive is deterministic; no encoder calls. **R026 (operator-corpus split)** continues mitigated — the per-claim-type corpus is per-tenant tunable via `--corpus-dir`.

No new risks surface in this Week 7 commit. The Week 1-pinned R023-R026 + Week 6-NEW R027 cover the Pillar F design surface; Week 7's measurement primitive is content-additive against R027's mitigation.

## Decision

### D220. Module placement — extend `orchestrator/draft_quality.py` (NOT a new sibling module)

The Week 7 measurement primitive lives at `orchestrator/draft_quality.py` (the Week 6 primitive's existing module) — `CorpusPair` + `CorpusMeasurement` + `_load_corpus_file` + `measure_per_claim_type_false_positive_rate` + `_cmd_measure` + main() extension. The public surface grows from the Week 6 surfaces (CLAIM_TYPES, EMITTED_BY, ParsedClaim, DraftQualityResult, parse_draft_for_claims, score_draft, build_hallucination_detected_payload) with three new public surfaces (CorpusPair, CorpusMeasurement, measure_per_claim_type_false_positive_rate).

The module's growth: ~1260 LOC (post-Week-6) → ~1700 LOC (post-Week-7; +440 LOC for the measurement primitive + ~CLI + docstrings).

The corpus fixtures live at `tests/fixtures/draft_quality_corpus/` sibling of `tests/fixtures/synthetic_pillar_b/` + `tests/fixtures/synthetic_pillar_d/` per the per-pillar fixture convention.

The test surface lives at `tests/test_draft_quality_corpus.py` (NEW) sibling of `tests/test_draft_quality.py` (the Week 6 unit tests).

**Why extend the existing module (rejected: NEW sibling module at `orchestrator/draft_quality_corpus.py`; rejected: subpackage at `orchestrator/draft_quality/`; rejected: per-claim-type modules).**

* **Extend the existing module** matches the per-primitive flat-module convention per ADR-0036 D166 + ADR-0043 D212. The Week 7 measurement primitive's substrate is the Week 6 primitive's `score_draft` function; both are CLOSELY related (the measurement primitive's body invokes `score_draft` per pair). Co-locating in one module preserves the per-primitive scoping + the operator-readable import shape (`from orchestrator.draft_quality import score_draft, measure_per_claim_type_false_positive_rate`).
* **NEW sibling module at `orchestrator/draft_quality_corpus.py`** is rejected because the measurement primitive isn't a SEPARATE primitive — it's a per-claim-type AUDIT surface over the Week 6 primitive. Splitting into a sibling module creates the "look in two places" mental model the Pillar F per-week convention rejects (per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 — same shape rationale).
* **Subpackage at `orchestrator/draft_quality/`** is rejected per the same rationale as ADR-0043 D212-Alt2 — over-organization for the Week 7 commit's ~440 LOC scope; one module is sufficient + future Pillar F weeks' extensions land at the existing module.
* **Per-claim-type modules** is rejected — five modules vs one is operator-hostile; per-claim-type semantics are LABELS on the data, not module-split signals.

### D221. Per-claim-type partition — one YAML file per claim_type at `tests/fixtures/draft_quality_corpus/`

The corpus directory ships:

```
tests/fixtures/draft_quality_corpus/
├── README.md                  # corpus structure + maintenance discipline
├── date_reference.yml         # ~30 pairs exercising date_reference extraction
├── named_entity.yml           # ~30 pairs exercising named_entity extraction
├── you_phrase.yml             # ~30 pairs exercising you_phrase extraction
├── quoted_text.yml            # ~30 pairs exercising quoted_text extraction
└── dated_event.yml            # ~30 pairs exercising dated_event extraction
```

Per-claim-type partition (one file per claim_type in `CLAIM_TYPES`):

* **~30 pairs per file** at Week 7 ship time (~150 pairs total). Future Pillar F weeks (Week 8+ extension; operator-deferred extension) may grow to ~50 per file. The Week 7 floor (~30) is enough to surface meaningful per-claim-type FP/FN rates; the corpus is operator-extensible.
* **~50/50 ready/refused partition** per file — ~15 pairs labeled `ready` (operator-judgment: every claim cited) + ~15 pairs labeled `refused` (operator-judgment: at least one uncited claim). The partition lets the measurement primitive surface both FP rates (denominator = ready labels) + FN rates (denominator = refused labels).
* **Per-claim-type pairs are DOMINANT-CLAIM-TYPE-PRIMARY** — the date_reference corpus's pairs primarily exercise date_reference extraction patterns; pairs MAY surface secondary claim types from other categories (e.g., a date_reference draft may also surface a dated_event claim per the multi-claim-type extraction at Layer 3). The state-level measurement aggregates extraction + cross-reference for the combined gate verdict.

**Why one file per claim_type (rejected: one giant file with all 150 pairs; rejected: one file per ready/refused split; rejected: per-claim-type subdirectories with multiple files).**

* **One file per claim_type** mirrors the Pillar D Week 12 fixture's per-category partition (per ADR-0031 D136 — though Pillar D ships a single file with per-category sections; the per-claim-type file split matches the closed-enum boundary at `CLAIM_TYPES`). Operators auditing per-claim-type rates can `cat tests/fixtures/draft_quality_corpus/<claim_type>.yml` for a focused inspection.
* **One giant file with all 150 pairs** is rejected because the per-claim-type filter at the measurement primitive's signature becomes load-bearing — operators would need to grep + filter the giant file. The per-file split makes the per-claim-type measurement an O(1) file-load operation.
* **One file per ready/refused split** is rejected because the ready/refused dimension is orthogonal to the claim_type dimension — operators measure per-claim-type rates, not per-state rates.
* **Per-claim-type subdirectories with multiple files** is rejected per the same rationale as ADR-0041 D199-Alt3 — operator-hostile + the per-corpus editing workflow scales poorly.

### D222. Per-pair schema + `CorpusPair` dataclass

Each per-claim-type YAML file's structure:

```yaml
version: 1
claim_type: date_reference          # MUST match the filename + be in CLAIM_TYPES
register: cold-pitch                 # which register's threshold to consult
channel: email                       # the per-channel stamp

pairs:
  - id: dref-r-001                   # corpus-unique
    draft: |
      Following up on your April 2026 launch.
    dossier: |
      [Your launch](https://blog.example.com/april-2026) — April 2026.
    expected_state: ready            # operator-judgment ground truth
    notes: "Markdown link with year-bearing month reference"
```

The `CorpusPair` dataclass:

```python
@dataclass(frozen=True)
class CorpusPair:
    id: str
    draft: str
    dossier: str
    expected_state: str       # "ready" | "refused"
    notes: str | None = None
```

Construction-time invariants in `__post_init__`:

* `id`, `draft`, `dossier` are non-empty strings (whitespace-stripped).
* `expected_state` is in `{"ready", "refused"}` (closed-enum per `_VALID_EXPECTED_STATES`).

**Why a typed `CorpusPair` (rejected: dict-only pair representation; rejected: per-claim-level labels instead of state-level labels; rejected: additional expected fields like `expected_claim_count_min`).**

* **Typed `CorpusPair`** matches the framework's frozen-dataclass discipline per ADR-0036 D167 + ADR-0039 D186 + ADR-0043 D213/D214. Construction-time validation refuses-loud at the loader's per-pair instantiation site; corpus drift (missing field; unknown expected_state) surfaces at load time, not at measurement-result time. The frozen dataclass also documents the per-pair shape via type annotations — operators reading `CorpusPair.__doc__` see the contract.
* **Dict-only** is rejected because per-pair validation would have to live in the loader function — adding scope creep + losing the IDE-assisted authoring of new pairs.
* **Per-claim-level labels** (e.g., a `expected_claims: [{type, text, expected_cited}]` field) is rejected because (a) operators label what they CARE about (state-level: would I send this draft?) — not per-claim citation status; (b) the per-claim-level labeling explodes corpus size + maintenance cost; (c) per-claim-level measurement is a Pillar F Week 8+ refinement IF demand materializes.
* **Additional expected fields** (`expected_claim_count_min` etc.) is rejected per the YAGNI convention — the state-level measurement is sufficient at Week 7; per-claim-level details ship at Week 8+ if demand materializes.

### D223. `CorpusMeasurement` dataclass + measurement primitive shape

```python
@dataclass(frozen=True)
class CorpusMeasurement:
    claim_type: str           # closed-enum per CLAIM_TYPES
    register: str             # closed-enum per REGISTERS
    channel: str              # closed-enum per CHANNELS
    pair_count: int
    true_positive: int        # parser=refused + corpus=refused  (correct catch)
    true_negative: int        # parser=ready   + corpus=ready    (correct accept)
    false_positive: int       # parser=refused + corpus=ready    (over-eager catch)
    false_negative: int       # parser=ready   + corpus=refused  (missed catch — BRAND RISK)
    accuracy: float           # (TP+TN) / pair_count
    false_positive_rate: float  # FP / (FP+TN)
    false_negative_rate: float  # FN / (FN+TP)


def measure_per_claim_type_false_positive_rate(
    corpus_dir: Path,
    claim_type: str,
    *,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
) -> CorpusMeasurement: ...
```

Construction-time invariants on `CorpusMeasurement`:

* `claim_type` in `CLAIM_TYPES` (closed-enum per ADR-0043 D214).
* `register` in `REGISTERS` (closed-enum per ADR-0038 D178).
* `channel` in `CHANNELS` (closed-enum per ADR-0014 D33).
* All count fields are non-negative ints (bool catch per the Pillar F Week 4 footgun pattern at ADR-0041 D201).
* **`true_positive + true_negative + false_positive + false_negative == pair_count`** (the subset invariant — per-pair outcomes partition the corpus).
* All rate fields are floats in `[0.0, 1.0]`.

The measurement primitive's per-call dispatch:

1. Resolve corpus file path: `corpus_dir/<claim_type>.yml`.
2. Load + validate (closed-enum on `claim_type` + `register` + `channel`; per-pair refuse-loud on missing required fields + duplicate ids + unknown `expected_state`).
3. For each pair: run `score_draft(draft, dossier, register=…, channel=…, …)`.
4. Tally per-pair outcomes: TP/TN/FP/FN.
5. Compute rates: accuracy = `(TP+TN)/pair_count`; FP_rate = `FP/(FP+TN)` (0.0 if denominator 0); FN_rate = `FN/(FN+TP)` (0.0 if denominator 0).
6. Construct `CorpusMeasurement` (construction-time invariant runs).

**Asymmetric-failure-cost discipline** per ADR-0038 D180 + D184:

* **FN_rate (brand-risk path)** — the parser said "ready" but the corpus says "refused" (uncited claim ships). HIGH-cost. The Week 7 baseline + the regression-barrier bound on FN_rate are LOAD-BEARING.
* **FP_rate (operator-friction path)** — the parser said "refused" but the corpus says "ready" (operator stamps an override). LOW-cost. The bound is permissive at Week 7 baseline; future Pillar F weeks may tighten.

**Why the TP/TN/FP/FN tally + composite rates (rejected: per-pair detail list as result; rejected: aggregate accuracy-only; rejected: per-state confusion-matrix dict).**

* **TP/TN/FP/FN tally + composite rates** matches the framework's classification-measurement convention (Pillar D Week 12 per-category precision/recall per ADR-0031 D137). Operators reading the measurement see the per-state confusion at a glance + the load-bearing rates surfaced for the asymmetric-failure-cost analysis.
* **Per-pair detail list as result** is rejected because (a) operators care about per-claim-type rates, not per-pair outcomes (per-pair details are surfaced via the `--json` CLI flag); (b) the per-claim-type measurement is the operator-deliberate aggregation grain — surface the per-pair outcomes at the measurement-data-loading layer, not at the result layer.
* **Aggregate accuracy-only** is rejected because the asymmetric-failure-cost discipline requires the FP_rate + FN_rate split; aggregate accuracy obscures the per-state imbalance.
* **Per-state confusion-matrix dict** (e.g., `{"refused": {"refused": 10, "ready": 2}, ...}`) is rejected because the per-claim-type rates are the load-bearing surface; the dict shape forces operators to compute rates from the dict on every call.

### D224. CLI `measure` subcommand

The new CLI subcommand at `orchestrator/draft_quality.py`:

```
python orchestrator/draft_quality.py measure \
    --corpus-dir <path-to-corpus-directory> \
    --claim-type {date_reference|named_entity|you_phrase|quoted_text|dated_event} \
    [--thresholds-path PATH] [--json]
```

The subcommand surfaces the per-claim-type measurement for the operator. Argparse-choices enforces the closed-enum on `--claim-type` BEFORE handler dispatch (per ADR-0042 D210 precedent + ADR-0043 D212).

**Why a CLI subcommand at Week 7 (rejected: library-only at Week 7 + CLI deferred to Pillar I; rejected: per-claim-type CLI invocation pattern `measure-date_reference`; rejected: a single `measure-all` subcommand that walks all claim types).**

* **CLI subcommand at Week 7** matches the framework's operator-facing CLI convention (Pillar E `discovery_dedup check`, Pillar E `email_verification_cache lookup`, Pillar F Week 2 `voice_corpus retrieve`, Pillar F Week 5 `voice_corpus thresholds list/get/dump`, Pillar F Week 6 `draft_quality parse`). Operator-deferred Pillar I audit-tooling consumes the JSON output for per-tenant per-register dashboards.
* **Library-only at Week 7 + CLI deferred to Pillar I** is rejected because the measurement primitive's operator-facing utility ships at Week 7 — operators measuring their own corpora benefit from the CLI surface immediately.
* **Per-claim-type subcommand pattern** (`measure-date_reference`) is rejected because (a) the argparse-choices pattern at `--claim-type` is the framework's convention for per-enum-value dispatch; (b) per-claim-type subcommands would inflate the subparser surface 5x.
* **`measure-all` walking every claim type** is rejected because (a) the per-claim-type measurement is the load-bearing aggregation grain — operators interpret rates per-claim-type, not per-corpus-aggregate; (b) operators MAY shell-loop `for ct in date_reference named_entity ...; do measure --claim-type $ct; done` if they need bulk measurement.

### D225. Per-claim-type regression-barrier rate bounds

The Week 7 baseline regression-barrier targets at `tests/test_draft_quality_corpus.py::TestCorpusBenchmark::_CLAIM_TYPE_BENCHMARK_TARGETS`:

| Claim type        | FP_rate_max | FN_rate_max | Accuracy_min |
|-------------------|-------------|-------------|--------------|
| `date_reference`  |       0.40  |       0.40  |        0.60  |
| `named_entity`    |       0.20  |       0.65  |        0.55  |
| `you_phrase`      |       0.20  |       0.20  |        0.85  |
| `quoted_text`     |       0.20  |       0.20  |        0.85  |
| `dated_event`     |       0.20  |       0.55  |        0.65  |

Bounds derived from the empirically-measured Week 7 baseline rates against the shipped corpus with 5-15pp headroom for noise + minor parser refinements. The FN_rate bound is the LOAD-BEARING regression barrier per ADR-0038 D184's asymmetric-failure-cost discipline (brand-risk path).

Notes on the bounds:

* `named_entity` + `dated_event` carry HIGHER FN_rate bounds because the deterministic parser's regex-based extraction has known gaps on possessive constructions ("Anthropic Inc's research") + paraphrased dossiers. Week 8+ fidelity-scoring's fuzzy-match extension will close these gaps.
* `you_phrase` + `quoted_text` carry TIGHT FN_rate bounds because the substring-based cross-reference is calibrated to match the parser's exact-match behavior (corpus pairs author dossiers with verbatim quotes).
* `date_reference` carries balanced bounds because the date-extraction has moderate FN_rate (the parser surfaces relative-time + bare-month patterns the dossier may not literally contain).

Future Pillar F weeks' bound trajectory:

* **Week 8+** ships per-claim fuzzy-match scoring + per-claim severity weighting. The FP_rate + FN_rate bounds may TIGHTEN by 5-10pp per claim type as the fuzzy-match extension addresses the parser's substring-only gap.
* **Week 10+** ships Layer 4 post-engine guard. The per-claim-type benchmark surface gains additional rows for Layer 4 emit-refusal regressions.
* **Week 12** ships Layer 5 reconcile heal-pass refusal. The per-claim-type benchmark surface stays at the Layer 3 measurement; Layer 5 ships its own benchmark via the existing TestPillarFExitCriterion vehicle.

**Why empirical bounds with 5-15pp headroom (rejected: tight bounds at the current rates; rejected: vacuous bounds at 1.0; rejected: percentile-based bounds from operator-corpus measurement).**

* **Empirical bounds with 5-15pp headroom** balance the regression-barrier discipline (catch meaningful regressions) against bound flakiness (noise + minor parser refinements). The headroom matches the framework's per-week reviewer convention — a Week 7 follow-up commit MAY tighten the bounds based on the per-week reviewer's call.
* **Tight bounds at the current rates** is rejected because the corpus is a SAMPLE of operator-judgment ground truth; minor parser refinements may shift rates by 1-3pp without indicating quality regression.
* **Vacuous bounds at 1.0** is rejected because the regression-barrier surface needs to fail when rates regress significantly; vacuous bounds turn the test into a documentation-only artifact.
* **Percentile-based bounds from operator-corpus measurement** is rejected because (a) Week 7 ships the synthetic-corpus baseline; operator-corpus measurement is a Pillar I per-tenant concern; (b) percentile bounds add complexity without proportional benefit at Week 7.

### D226. Closed-enum protection — corpus filename + YAML field + CLI choices

Three closed-enum protection surfaces for `claim_type`:

1. **Function-argument membership** — the loader at `_load_corpus_file(corpus_dir, claim_type)` validates the function argument `claim_type` against `CLAIM_TYPES` BEFORE any file I/O; library callers passing an unknown claim_type refuse-loud at this surface.
2. **YAML field matches function argument** — the per-claim-type YAML's top-level `claim_type` field MUST equal the function argument (which is already validated against `CLAIM_TYPES` at surface 1). The mismatch check is the protection vehicle: any YAML field that is not a valid `CLAIM_TYPES` member necessarily differs from the (valid) function argument and is caught here; any YAML field that IS in `CLAIM_TYPES` but disagrees with the function argument is operator misconfiguration (e.g., the file was renamed without updating the field) and is caught here. The effective protection: the YAML field is always in `CLAIM_TYPES` post-check. **Note per Week 7 follow-up P3-3:** the implementation is the mismatch check, not an independent `CLAIM_TYPES` membership check on the YAML field. The combined behavior is identical, but contributors reading this ADR should not expect a redundant `file_claim_type not in CLAIM_TYPES` check.
3. **CLI argparse choices** — the CLI's `--claim-type` flag uses `choices=sorted(CLAIM_TYPES)` (per ADR-0042 D210 precedent + ADR-0043 D212) — closed-enum enforced BEFORE handler dispatch.

Plus the `register` + `channel` closed-enum protection at the YAML's top-level fields (per ADR-0038 D178 + ADR-0014 D33).

Plus the `expected_state` closed-enum protection at the per-pair `CorpusPair.__post_init__` (per the `_VALID_EXPECTED_STATES = {"ready", "refused"}` constant).

**Why three closed-enum surfaces for `claim_type` (rejected: only argparse-level enforcement; rejected: only YAML-field enforcement; rejected: defer enum check to score_draft).**

* **Three closed-enum surfaces** mirror the framework's defense-in-depth discipline per ADR-0042 D210 + ADR-0041 D202 — each layer catches a different misconfiguration pattern: filename match catches the operator copying the wrong file; YAML field catches the operator editing the wrong field; CLI argparse catches the operator typing the wrong value.
* **Only argparse-level enforcement** is rejected because operators using the library directly (e.g., `measure_per_claim_type_false_positive_rate(corpus_dir, "not-a-type")` in a custom audit script) would bypass the argparse check.
* **Only YAML-field enforcement** is rejected because the per-corpus drift surface (filename vs YAML field) needs explicit naming.
* **Defer enum check to score_draft** is rejected because the closed-enum check at the loader's boundary is the earlier surface — fail fast.

### D227. TEST-ONLY `embed_fn` seam preservation — VERIFIED at Week 7

The TEST-ONLY `embed_fn` injection seam preservation (Week 2 audit's P3-B carry-forward, reaffirmed at Weeks 3+4+5, FIRST non-N/A verified at Week 6 per ADR-0043 D218) carries forward to Week 7's measurement primitive surface.

The Week 7 verification:

* `measure_per_claim_type_false_positive_rate` carries `embed_fn` kwarg labeled TEST-ONLY in its docstring; the kwarg is a PASSTHROUGH to `score_draft` (Week 7's measurement primitive does NOT encode anything itself — it consumes the deterministic Layer 3 parser via `score_draft`).
* The CLI `measure` subcommand does NOT surface `--embed-fn` (security + audit per ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1).
* Verified via `test_embed_fn_seam_in_signature` + `test_embed_fn_docstring_test_only` + `test_measure_cli_has_no_embed_fn_flag` in `TestMeasurePerClaimTypeFalsePositiveRate` + `TestCLIMeasure`.

The corpus is DETERMINISTIC — every pair's `expected_state` is a static ground-truth label; the measurement primitive's output is reproducible from `(corpus_dir, claim_type, thresholds)`.

**Why passthrough preservation at Week 7 (rejected: surface `embed_fn` defensively even though the measurement primitive doesn't encode; rejected: skip the verification; rejected: remove the seam from `score_draft` to simplify the measurement primitive's signature).**

* **Passthrough preservation** carries the seam through the Week 7 measurement primitive's surface so Week 8+ fidelity-scoring's encoding behavior is reachable through the measurement primitive's API (operators measuring per-claim-type rates against fuzzy-match extensions can inject a test encoder).
* **Surface defensively** is rejected — same rationale as ADR-0041 D205-Alt1 (the kwarg's presence without behavior is operator-confusing).
* **Skip the verification** is rejected because the Week 2 P3-B carry-forward is a per-week-reviewer checklist row; explicitly verifying at Week 7 closes the row for Week 7 + carries forward to Week 8+.
* **Remove the seam from score_draft** is rejected because the seam IS the Week 8+ fidelity-scoring substrate per ADR-0043 D218.

## Alternatives considered

### D220-Alt1: NEW sibling module at `orchestrator/draft_quality_corpus.py`

Per the per-primitive-flat-module convention, the measurement primitive lives at a NEW sibling module. **Rejected** per D220's rationale — the measurement primitive is an AUDIT surface over the Week 6 primitive, not a separate primitive. Co-locating in one module preserves the per-primitive scoping.

### D220-Alt2: Subpackage at `orchestrator/draft_quality/`

The Week 6 primitive's surfaces + Week 7's measurement primitive surfaces partition into per-Layer subpackage modules. **Rejected** per ADR-0043 D212-Alt2 — over-organization for the per-week commit scope.

### D220-Alt3: Per-claim-type modules

Five modules at `orchestrator/draft_quality_<claim_type>.py`. **Rejected** — per-claim-type semantics are LABELS on the data, not module-split signals. The deterministic parser at `parse_draft_for_claims` ships ONE function handling all claim types; the per-claim-type modules would inflate the surface area for no behavioral benefit.

### D221-Alt1: One giant file with all 150 pairs

`tests/fixtures/draft_quality_corpus.yml` carrying all 150 pairs across five claim types. **Rejected** per D221's rationale — operators auditing per-claim-type rates need a focused file.

### D221-Alt2: One file per ready/refused split

`ready.yml` + `refused.yml` at the corpus dir. **Rejected** — the ready/refused dimension is orthogonal to claim_type; operators measure per-claim-type, not per-state.

### D221-Alt3: Per-claim-type subdirectories

`corpus/<claim_type>/pair-001.yml` + `corpus/<claim_type>/pair-002.yml` etc. **Rejected** per ADR-0041 D199-Alt3 — per-pair-per-file scaling is operator-hostile.

### D222-Alt1: Dict-only pair representation

`pairs: [{id, draft, dossier, expected_state, notes}]` as plain dicts; no `CorpusPair` dataclass. **Rejected** — frozen-dataclass discipline per the framework convention catches corpus drift at load-time refuse-loud.

### D222-Alt2: Per-claim-level labels

Per-pair `expected_claims: [{type, text, expected_cited}]` instead of state-level. **Rejected** per D222's rationale — per-claim-level labels explode corpus size + maintenance cost; per-claim-level measurement is a Pillar F Week 8+ refinement.

### D222-Alt3: Additional expected fields (`expected_claim_count_min` etc.)

Per-pair fields documenting the expected parser output for regression-barrier richness. **Rejected** per the YAGNI convention — the state-level measurement is sufficient at Week 7.

### D223-Alt1: Per-pair detail list as result

The measurement primitive returns `list[tuple[CorpusPair, DraftQualityResult]]` instead of `CorpusMeasurement`. **Rejected** — operators interpret per-claim-type rates, not per-pair outcomes. Per-pair detail is surfaced via the `--json` CLI flag IF operators need it.

### D223-Alt2: Aggregate accuracy-only

Result is `float` (the accuracy only). **Rejected** — the asymmetric-failure-cost discipline requires FP_rate + FN_rate split.

### D223-Alt3: Per-state confusion-matrix dict

Result is `dict[str, dict[str, int]]`. **Rejected** — forces operators to compute rates on every consumer call; the typed dataclass is the operator-readable surface.

### D224-Alt1: Library-only at Week 7

CLI deferred to Pillar I. **Rejected** — the CLI is operator-deliberate at Week 7 per the framework's CLI convention.

### D224-Alt2: Per-claim-type subcommand pattern

`measure-date_reference` + `measure-named_entity` + etc. **Rejected** — argparse-choices is the framework convention for per-enum-value dispatch.

### D224-Alt3: `measure-all` walking every claim type

A single subcommand that walks all five claim types + emits per-claim-type rates. **Rejected** — operators interpret per-claim-type, not per-corpus-aggregate.

### D225-Alt1: Tight bounds at the current rates

Set bounds at the exact Week 7 baseline (no headroom). **Rejected** per D225's rationale — bounds flakiness from corpus sampling.

### D225-Alt2: Vacuous bounds at 1.0

Set all bounds at 1.0 (the test is documentation-only). **Rejected** — the regression-barrier surface needs to fail on meaningful regressions.

### D225-Alt3: Percentile-based bounds from operator-corpus measurement

Bounds computed from operator-corpus distribution. **Rejected** — Pillar I per-tenant concern.

### D226-Alt1: Only argparse-level enforcement

Closed-enum check at the CLI only. **Rejected** — library callers bypass.

### D226-Alt2: Only YAML-field enforcement

Closed-enum check at the per-corpus YAML only. **Rejected** — operators using the library directly (e.g., `measure_per_claim_type_false_positive_rate(corpus_dir, "not-a-type")`) would bypass.

### D226-Alt3: Defer enum check to score_draft

The corpus loader skips the closed-enum check; `score_draft` per-pair invocation enforces. **Rejected** — fail fast at the loader's boundary.

### D227-Alt1: Surface `embed_fn` defensively even though measurement primitive doesn't encode

Add `embed_fn` to the measurement primitive's signature with no behavior. **Rejected** — the kwarg's purpose IS the passthrough to `score_draft`; it has a clear behavior (passthrough), not "defensive".

### D227-Alt2: Skip the verification

Don't explicitly name Week 7's status. **Rejected** — the per-week reviewer's checklist row at Week 7 requires explicit naming.

### D227-Alt3: Remove the seam from `score_draft`

Simplify the measurement primitive's signature by removing the seam. **Rejected** — the seam IS the Week 8+ fidelity-scoring substrate.

## Consequences

### Positive consequences

* **R027 mitigation lands at Week 7.** The per-claim-type baseline rates are measured + the regression-barrier surface is operator-readable; the parser's per-claim-type gaps are documented + measurable.
* **Week 8+/10+/12 refinements gain a regression-barrier substrate.** Every parser bug surfaces at the per-claim-type benchmark before regressing Layer 4/5; the asymmetric-failure-cost discipline's FN_rate bound is LOAD-BEARING.
* **Operators MAY benchmark their own corpora.** The CLI's `--corpus-dir` flag accepts per-tenant per-claim-type corpora; Pillar I per-tenant audit-tooling consumes via the CLI.
* **The corpus is the calibration signal for Week 8+ fidelity-scoring.** The Week 7 baseline rates motivate the per-claim-type encoding extension; the per-claim-type FN_rate gap is the empirical evidence for the Week 8+ work.
* **The TEST-ONLY embed_fn seam preservation continues.** Week 7's measurement primitive's passthrough preserves the seam for Week 8+ encoding behavior.

### Negative consequences

* **Test count grows by ~106 tests** (TestCorpusFiles + TestCorpusPair + TestCorpusMeasurement + TestLoadCorpusFile + TestMeasurePerClaimTypeFalsePositiveRate + TestCorpusBenchmark + TestCLIMeasure + TestWeek7ModuleSurface). Cumulative: 2973 (post-Week-6-follow-up) → 3079 (post-Week-7). The growth is bounded; per-test coverage is targeted at refuse-loud + per-claim-type measurement + the regression-barrier surface.
* **`orchestrator/draft_quality.py` grows by ~440 LOC** (`CorpusPair` + `CorpusMeasurement` + `_load_corpus_file` + `measure_per_claim_type_false_positive_rate` + `_cmd_measure` + main() extension + ~150 LOC of docstrings). The growth is intentional — the per-claim-type measurement primitive deserves co-location with the Week 6 primitive.
* **A ~150-pair corpus lands at `tests/fixtures/draft_quality_corpus/`.** The per-corpus authoring cost is real; the corpus is the operator-judgment ground-truth surface + the regression-barrier substrate. Future Pillar F weeks' operator-deferred extensions may grow to ~250 pairs (~50 per claim type per the original handoff target).
* **The Week 7 baseline rates surface PARSER GAPS.** The `named_entity` corpus's high FN_rate (~53%) + the `dated_event` corpus's FN_rate (~40%) are not bugs — they're the measurement signal motivating the Week 8+ fidelity-scoring extension. Operators reading the rates without context may interpret high FN_rates as quality regressions; the ADR + the corpus README explicitly name the Week 7 baseline + the Week 8+ trajectory.

### Risks

The asymmetric-failure-cost calculus carries:

* **The corpus drift risk (P2):** A future Pillar F contributor might revise the parser without updating the corpus or vice versa, causing benchmark targets to flake. **Bounded by** the per-week reviewer convention + the benchmark target table at `_CLAIM_TYPE_BENCHMARK_TARGETS` (operator-readable; per-claim-type rate bounds documented inline with rationale) + the corpus README's maintenance discipline section.

* **The synthetic-corpus calibration risk (P3):** The Week 7 corpus is OPERATOR-AUTHORED (Yang's judgment) — operator judgment is one signal among many; the corpus may not generalize to all operator workflows. **Bounded by** the per-corpus extensibility (operators MAY substitute `--corpus-dir <their-corpus>` for per-tenant measurement) + the Pillar I per-tenant trajectory + the corpus README's "ground truth — operator judgment" section explicitly naming the calibration discipline.

* **The benchmark target drift risk (P3):** Future Pillar F weeks may tighten the bounds without updating the ADR's bound table. **Bounded by** the per-week reviewer's checklist row + the ADR amendment convention.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The measurement primitive is upstream of the ledger (it reads a static corpus + invokes `score_draft` which is read-only against the ledger).
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The measurement primitive is read-only.
* **I3 — Atomic per-Person enrollment.** Preserved. Week 7 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The measurement primitive is per-claim-type (orthogonal to per-channel state).
* **I5 — Migration framework discipline.** Preserved. Week 7 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The measurement primitive is READ-only — it doesn't emit events.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. The Week 7 primitive adds NINE new refuse-loud surfaces: (a) `CorpusPair.__post_init__` per-field validation (id + draft + dossier + expected_state); (b) `CorpusMeasurement.__post_init__` per-field validation (claim_type + register + channel + counts + rates + subset invariant); (c) `_load_corpus_file` closed-enum + per-pair + duplicate-id; (d) `measure_per_claim_type_false_positive_rate` claim_type closed-enum; (e) CLI argparse-choices on `--claim-type`; (f) CLI missing-corpus-dir refuse-loud; (g) CLI missing-corpus-file refuse-loud (propagated from loader); (h) CLI malformed-YAML refuse-loud (propagated); (i) CLI per-pair refuse-loud (propagated). Mirrors `_load_corpus_file`'s strict-gate posture per ADR-0041 D202 + ADR-0043 D213.
* **I8 — Privacy-respecting.** Preserved. The measurement primitive is read-only against the corpus + the dossier; no per-Person data; no event emit.

## Downstream pillar impact

* **Pillar F Week 8+ (fidelity-scoring primitive).** The Week 8+ fidelity-scoring primitive's encoding behavior (per-claim fuzzy-match scoring against the dossier's citation set per ADR-0043 D218's seam) consumes the Week 7 measurement primitive's passthrough. The Week 7 baseline rates motivate the per-claim-type encoding extension; the per-week-7 FN_rate gap on `named_entity` + `dated_event` claims is the empirical evidence for the Week 8+ work. The Week 7 corpus serves as the regression barrier — Week 8+ extensions MUST not regress the Week 7 baseline FN_rate.

* **Pillar F Week 10 (Layer 4 post-engine guard).** The Week 10 Layer 4 emit-refusal extension consumes the Week 6 primitive's `parse_draft_for_claims` + `score_draft`. The Week 7 corpus + benchmark catches Layer 4 emit-guard regressions; the per-claim-type rate bounds extend to Layer 4 by the same surface.

* **Pillar F Week 12 (Layer 5 reconcile heal-pass refusal).** The Week 12 Layer 5 reconcile Pass C refusal extension consumes the same primitive. The Week 7 corpus + benchmark catches Pass C refusal regressions.

* **Pillar G (Observability).** Dashboards consume `hallucination_detected` events with per-register + per-channel + per-claim-type aggregation. The Week 7 corpus's per-claim-type rates inform dashboard threshold tuning (e.g., "alert if hallucination_detected per-claim-type rate exceeds Week 7 baseline + X pp").

* **Pillar H (Real-time + scale).** The measurement primitive's per-call cost is bounded by the corpus size (~30 pairs * ~5-10ms per score_draft = ~150-300ms per measurement). Pillar H's scaling concerns target the per-draft scoring primitive at Week 8+; the measurement primitive is operator-deferred (per-claim-type audit cadence is per-month or per-quarter, not per-draft).

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions per ADR-0038 §Downstream pillar impact list MAY extend with per-tenant per-claim-type corpus tooling IF operator demand materializes. The Week 7 CLI's `--corpus-dir` flag accepts per-tenant paths; Pillar I's per-tenant config separation extends to `<tenant>/draft_quality_corpus/` directories.

* **Pillar J (Compliance + audit).** Per-tenant GDPR-purge does not touch the corpus (it's operator-curated calibration data, not per-Person data). The corpus's `draft` + `dossier` fields are SYNTHETIC operator-authored examples — no personal data.

## Migration / rollout

**Week 7 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 6 to Pillar F Week 7:

1. **Operator updates the framework** to Pillar F Week 7's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 7 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_draft_quality_corpus.py -v`** to verify the new corpus + measurement primitive tests pass. Optional but recommended.
4. **Operator MAY benchmark their own corpus.** Two paths:
   * **Path A (framework default):** Use the shipped corpus at `tests/fixtures/draft_quality_corpus/` to validate the parser's Week 7 baseline.
   * **Path B (operator-curated):** Author per-tenant corpus directories with the same schema + invoke `python orchestrator/draft_quality.py measure --corpus-dir <path> --claim-type <type>`.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 8+ may extend the corpus with per-claim-level labels IF demand materializes (the corpus schema is extensible). Week 10 + Week 12 ship Layer 4/5 binding behavioral commits; corpus extensions land per the per-week design.

## Existing-operator seed

**Pillar F Week 7's operator-side disposition is content-additive — no operator action required at Week 7.** The corpus + measurement primitive land at the test-fixture surface + the operator-facing CLI; the existing `parse` subcommand + the SKILL.md Phase 5/6 extensions per ADR-0043 D217 stay UNCHANGED.

The operator-side trajectory (per-week ships across Pillar F Weeks 7-12):

* **Week 7 (this commit):** The per-claim-type corpus + measurement primitive land. Operators MAY use the CLI to benchmark their own corpora; the shipped corpus is the framework baseline. SKILL.md is UNCHANGED at Week 7.
* **Week 8+:** Fidelity-scoring primitive lands; the per-draft fidelity score consumes the per-register threshold. The `voice.use_embedding_primitive` default flips. The per-claim-type measurement primitive may extend with per-claim severity weighting. SKILL.md Phase 4 extends with per-register routing.
* **Week 10:** Layer 4 post-engine guard refusal lands; the `draft_ready` event emit refuses-loud on `uncited_claims` non-empty.
* **Week 12:** Layer 5 reconcile Pass C heal-pass refusal lands; the binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 7:** none. The framework upgrade is read-only with respect to operator state.

**Operator action recommended at Week 7:** none beyond the per-week pytest verification. Operators MAY copy the shipped corpus to their config directory + author per-tenant pairs; the framework's CLI continues to point at the shipped corpus by default.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D180 (hallucination-detection FIVE-layer defense) is THE structural context Week 7's corpus + measurement primitive ship under. D184's asymmetric-failure-cost discipline motivates the FN_rate-as-load-bearing-bound discipline per D225.
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive. D188 (TEST-ONLY `embed_fn` seam at retrieval surface docstring) is the STRUCTURAL reference for ADR-0044 D227's passthrough preservation.
- **ADR-0040 (D192-D198)** — Pillar F Week 3 per-register adapters. D197 (TEST-ONLY `embed_fn` seam preservation) carries forward per D227.
- **ADR-0041 (D199-D205)** — Pillar F Week 4 per-register threshold infrastructure. D201 (range validation + bool catch) is the STRUCTURAL reference for `CorpusMeasurement.__post_init__`'s bool-catch per D223. D204 (`get_voice_threshold_for_register`) is the substrate the measurement primitive consumes (via `score_draft`).
- **ADR-0042 (D206-D211)** — Pillar F Week 5 voice-thresholds CLI extension. D210 (argparse-choices closed-enum at CLI) is the STRUCTURAL reference for the CLI's `--claim-type` argparse-choices per D226.
- **ADR-0043 (D212-D219)** — Pillar F Week 6 hallucination-detection Layer 2-3 primitive. D213 (DraftQualityResult Layer 2 invariants) + D214 (parse_draft_for_claims Layer 3 parser) + D215 (per-register threshold consumption) + D218 (TEST-ONLY embed_fn seam FIRST non-N/A verification) are THE substrate Week 7's measurement primitive consumes.
- **ADR-0031 (D136-D141)** — Pillar D Week 12 100-message synthetic inbox corpus. D136 (per-category fixture YAML at `tests/fixtures/synthetic_pillar_d/corpus.yml`) is THE structural reference for ADR-0044's per-claim-type corpus shape per D221 + D222.
- **ADR-0036 (D166)** — Pillar E Week 9-11 per-primitive-flat-module convention. Week 7's extension of `orchestrator/draft_quality.py` (sibling of `voice_corpus.py`) preserves the convention per D220.
- **ADR-0014 (D33)** — Pillar C foundation. The channel-on-every-event invariant continues; the measurement primitive is READ-only.
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §41+ extends with the Week 7 commit's audit verdict (the measurement primitive's public surface + the corpus fixtures + the CLI extension + the per-claim-type benchmark + the SKILL.md UNCHANGED status + the SOURCES-OF-TRUTH row UNCHANGED status).
- **`.planning/HANDOFF-pillar-f-week-7.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 8 trajectory.
- **`orchestrator/draft_quality.py`** — extended with `CorpusPair` + `CorpusMeasurement` + `_load_corpus_file` + `measure_per_claim_type_false_positive_rate` + `_cmd_measure` per D220-D224.
- **`tests/fixtures/draft_quality_corpus/`** (NEW) — per-claim-type synthetic corpora per D221 + D222 + README.md.
- **`tests/test_draft_quality_corpus.py`** (NEW) — `TestCorpusFiles` + `TestCorpusPair` + `TestCorpusMeasurement` + `TestLoadCorpusFile` + `TestMeasurePerClaimTypeFalsePositiveRate` + `TestCorpusBenchmark` + `TestCLIMeasure` + `TestWeek7ModuleSurface` (~106 tests covering loader + measurement + benchmark + CLI per D220-D227).
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 7 close summary.
- **`docs/adr/README.md`** — ADR-0044 row appended.
