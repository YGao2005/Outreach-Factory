# Pillar F Weeks 7+11 — Per-claim-type test corpora

Per-claim-type synthetic `(draft, dossier, expected_state)` pairs for measuring the Pillar F Week 6 Layer 3 deterministic parser's per-claim-type false-positive + false-negative rates against operator-judgment ground truth. Per ADR-0044 (Pillar F Week 7) + ADR-0048 (Pillar F Week 11 — corpus revision: paraphrased-ready pairs + bound tightening).

Loaded by `orchestrator.draft_quality.measure_per_claim_type_false_positive_rate(corpus_dir, claim_type)`; consumed by `tests/test_draft_quality_corpus.py::TestCorpusBenchmark::test_<claim_type>_corpus_rates_within_bounds`.

## Purpose

The Week 6 Layer 3 parser (`parse_draft_for_claims` in `orchestrator/draft_quality.py`) is **deterministic** — regex-based per-claim-type extraction + substring/regex citation cross-reference against the dossier. The framework's R027 risk (per-claim false-positive rate) ships unmeasured at Week 6; Week 7's corpus + measurement primitive close the measurement gap.

The corpus is the **regression barrier** for Weeks 8+/10/12:

* Week 8+ ships per-claim fuzzy-match scoring against the dossier's citation set (the `embed_fn` seam encodes draft + dossier per-claim spans). The per-claim-type rate measurements from Week 7's deterministic baseline are the reference; Week 8+ MUST not regress.
* Week 10 ships Layer 4 (post-engine guard on `draft_ready` emit refusal). The corpus pairs feed regression-barrier tests for the Layer 4 emit guard.
* Week 12 ships Layer 5 (reconcile heal-pass refusal). The corpus pairs feed regression-barrier tests for the Pass C refusal.

## Distribution (per ADR-0044 D221 + ADR-0048 D253)

| Claim type        | W7 baseline | W11 paraphrased-ready (`-p-` ids) | W11 total | Notes                                                                                |
|-------------------|------------:|----------------------------------:|----------:|--------------------------------------------------------------------------------------|
| `date_reference`  |          30 |                                 0 |        30 | ISO 8601 + month-year + quarter + relative-time + bare-month patterns; W11 extension excluded per ADR-0048 D254 (empirical encoder calibration) |
| `named_entity`    |          30 |                                 7 |        37 | Multi-word title-case entities (companies, people); W11 paraphrased pairs use comma-break inside 3+ token entities  |
| `you_phrase`      |          30 |                                 0 |        30 | "you VERB" patterns; W11 extension excluded per ADR-0048 D257 + ADR-0046 D240 (attribution-claim exclusion)         |
| `quoted_text`     |          30 |                                 0 |        30 | Straight-quote spans; W11 extension excluded per ADR-0048 D257 + ADR-0043 D214 (verbatim-only invariant)            |
| `dated_event`     |          30 |                                 5 |        35 | Direct `<date> <event-noun>` shapes + date-near-entity patterns; W11 paraphrased pairs use word-order shift + abbreviation expansion |
| **Total**         |     **150** |                            **12** |   **162** |                                                                                      |

Each W7 baseline file ships ~15 `ready`-labeled pairs (every claim has a matching dossier anchor) + ~15 `refused`-labeled pairs (at least one claim has no matching anchor). Per ADR-0044 D222 + the per-corpus calibration discipline.

The W11 paraphrased-ready pairs (per ADR-0048 D255) extend the `named_entity` + `dated_event` corpora; each pair's draft contains a fact claim + dossier paraphrases the claim with all claim tokens preserved (substring match broken via comma-break / punctuation / word-order shift), AND each pair was empirically verified at Week 11 commit time to hit cosine ≥ 0.85 against the framework default encoder (BAAI/bge-small-en-v1.5 per ADR-0039 D188 + ADR-0046 D239's threshold calibration).

## Per-file schema (per ADR-0044 D222)

```yaml
version: 1
claim_type: date_reference          # MUST match the filename + be in CLAIM_TYPES
register: cold-pitch                 # the per-register threshold the measurement consults
channel: email                       # the per-channel stamp

pairs:
  - id: dref-001                     # unique pair id (corpus-scope)
    draft: |
      Following up on your April 2026 launch — exciting stuff.
    dossier: |
      [Your launch](https://blog.example.com/april-2026) was announced in April 2026.
    expected_state: ready            # ground-truth: a human says "every claim has a dossier basis"
    notes: "Markdown link with year-bearing month reference"
```

Required fields: `id` (corpus-unique), `draft`, `dossier`, `expected_state` (one of `ready` | `refused`). Optional: `notes` (operator-readable rationale; documentation-only, NOT validated).

## Determinism

The corpus is **deterministic** — every pair's expected_state is a static ground-truth label authored by the corpus author. The measurement primitive runs `score_draft(draft, dossier, register=…, channel=…)` per pair + compares `result.state` against `expected_state` + aggregates per-claim-type tallies. No random number generation; no stochastic comparison.

The TEST-ONLY `embed_fn` seam preservation (per ADR-0043 D218) carries forward: the corpus is parsed against the deterministic Layer 3 baseline; Week 8+ fidelity-scoring extension will SHIP encoding behavior consuming the seam at the measurement primitive's pass-through.

## Ground truth — operator judgment

The corpus author's `expected_state` is OPERATOR JUDGMENT, NOT calibrated to the parser. The corpus measures how well the parser approximates a thoughtful human's "is every claim cited?" verdict.

* **`expected_state: ready`** — every claim a thoughtful operator would extract from the draft has a matching anchor in the dossier (URL, markdown link, footnote, verbatim substring near a citation).
* **`expected_state: refused`** — at least one claim has no matching anchor; the operator would re-draft the touch or stamp a `hallucination_check_override` on the Touch note per ADR-0043 D217.

The corpus pairs span both EASY cases (parser agrees with operator) + HARD cases (parser may diverge from operator); the measurement primitive's per-claim-type rates surface the parser's per-claim-type calibration.

## Week 11 paraphrased-ready pairs (per ADR-0048 D252-D255)

The W11 extension adds paraphrased-ready pairs to the `named_entity` + `dated_event` corpora. The pairs exercise the Week 9 fuzzy match's WIN cell per ADR-0046 D242 — the deterministic substring path returns `None` (the claim text is NOT a substring of the dossier), then the fuzzy fallback activates + correctly cites at threshold 0.85.

**Why the W11 extension matters**: The W7 baseline's structural design uses verbatim-substring ready pairs + negation-prose refused pairs. The deterministic Layer 3 parser handles the verbatim cases at 100%; fuzzy match was structurally untested at WIN cells per ADR-0046 D242's finding. The W11 paraphrased-ready pairs are the first empirical exercise of fuzzy match's WIN cell on the corpus surface; the post-extension bounds tighten per ADR-0048 D256.

**Per-claim-type extension scope** (per ADR-0048 D253):

* **`named_entity`** — +7 paraphrased-ready pairs (`nent-r-p-001` through `nent-r-p-007`). Each pair uses a 3+ token entity (e.g., "Acme Robotics Inc", "Meta AI Research Inc") with a comma-break paraphrase in the dossier (e.g., "Acme Robotics, Inc."). The comma breaks substring match while preserving all entity tokens for cosine similarity. Empirically-verified cosines at Week 11 commit time: 0.852-0.879.
* **`dated_event`** — +5 paraphrased-ready pairs (`devt-r-p-001` through `devt-r-p-005`). Each pair uses a date-event combination paraphrased via word-order shift (e.g., "March launch" vs "launch in early March") or abbreviation expansion (e.g., "Q3 2026 announcement" vs "Third quarter 2026 announcement"). Empirically-verified cosines: 0.851-0.876.
* **`date_reference`** — NO W11 extension per ADR-0048 D254. Empirical finding: the framework default encoder does NOT reliably reach cosine ≥ 0.85 on date paraphrases ("April 2026" vs "April of 2026" cosine ≈ 0.698 at Week 11 commit time). Future Pillar F weeks MAY extend when the calibration story matures (per-tenant encoder swap; threshold lowering with compensating attribution-claim exclusion expansion).
* **`you_phrase` + `quoted_text`** — NO W11 extension per ADR-0048 D257 + ADR-0046 D240's attribution-claim exclusion. Both claim types skip the fuzzy fallback per the parser's `_find_citation_anchor`'s attribution-preserving behavior; paraphrased-ready pairs in these corpora would VIOLATE the structural exclusion (the fuzzy path would NOT fire even if the chunk's cosine reached 0.85).

**Pair ID convention**: paraphrased-ready pairs use the `<prefix>-r-p-NNN` ID (e.g., `nent-r-p-001`). The `-p-` segment distinguishes them from W7 baseline `<prefix>-r-NNN` / `<prefix>-u-NNN` pairs.

**Per-pair invariants** (per ADR-0048 D255):

1. The dossier MUST NOT contain the claim text as a case-insensitive substring (otherwise deterministic catches → fuzzy is not exercised).
2. The dossier MUST include a URL within ±200 chars of the paraphrased chunk (operator-readable anchor for the fuzzy `citation_anchor` return per `_find_citation_anchor_fuzzy`).
3. The pair MUST empirically verify cosine ≥ 0.85 at Week 11 commit time against the framework default encoder. The pair's `notes` field records the empirical cosine for the per-week reviewer's audit.

## Maintenance

* When the Layer 3 parser's regex patterns change (e.g., new patterns added to `_DATED_EVENT_PATTERN_RE` via ADR amendment), audit this corpus for matching pairs + extend with regression-barrier rows.
* When `CLAIM_TYPES` extends (per ADR-0038 D180 + ADR-0043 D214 — closed-enum ADR-amended), add a new per-claim-type YAML file at this directory + a matching benchmark test row.
* When per-claim severity weighting lands at Week 12+ (per ADR-0044 §Downstream pillar impact), extend each pair's schema with per-claim labels if needed (TBD per the per-week design).
* When the framework default encoder changes (e.g., upgrade from `BAAI/bge-small-en-v1.5` to a newer model), re-run the per-claim-type benchmark + audit the W11 paraphrased-ready pairs' cosines + amend ADR-0048 D254-D256's calibration table.
* The per-claim-type rate bounds in `tests/test_draft_quality_corpus.py::TestCorpusBenchmark` are the regression-barrier surface; W11 tightened the bounds for `named_entity` + `dated_event` per ADR-0048 D256. Future Pillar F weeks MAY further tighten as the corpus + parser evolve.

## References

* ADR-0048 (Pillar F Week 11) — corpus revision: paraphrased-ready pairs for fuzzy-active claim types + per-claim-type bound tightening.
* ADR-0046 (Pillar F Week 9) D237-D243 — the Week 9 per-claim fuzzy-match citation extension at the Layer 3 parser; D239 (default threshold 0.85) + D240 (attribution-claim exclusion: quoted_text + you_phrase) + D242 (W7 corpus's structural limitation + Week 10+ corpus revision trajectory).
* ADR-0044 (Pillar F Week 7) — corpus shape + partition + measurement primitive + CLI. D225 (per-claim-type regression-barrier bounds + headroom discipline + bound-tightening trajectory).
* ADR-0043 (Pillar F Week 6) D212-D219 — the Layer 2 + Layer 3 primitive the corpus measures. D214 (verbatim-only invariant for quoted_text).
* ADR-0041 (Pillar F Week 4) D204 — the per-register threshold loader consumed via `score_draft`.
* ADR-0039 (Pillar F Week 2) D188 — the BAAI/bge-small-en-v1.5 framework default encoder; the per-process model cache the fuzzy match path consumes via lazy-load per ADR-0046 D241.
* ADR-0038 (Pillar F foundation) D180 — the FIVE-layer hallucination-detection defense the corpus benchmarks Layer 3 of. D184 (asymmetric-failure-cost discipline motivating tighter FN_rate bounds over FP_rate).
* `orchestrator/draft_quality.py` — the Week 6 primitive + Week 7 measurement primitive + Week 9 fuzzy-match extension + Week 10 Layer 4 emit-guard.
* `tests/test_draft_quality_corpus.py` — the per-claim-type benchmark test surface + Week 11 test classes (`TestCorpusBenchmarkFuzzyWin` + `TestCorpusBenchmarkExclusion` + `TestWeek11CorpusExtension` + `TestWeek11ModuleSurface`).
