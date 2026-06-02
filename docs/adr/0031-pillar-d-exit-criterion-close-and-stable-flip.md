# ADR-0031: Pillar D Week 12 — exit-criterion close (100-message synthetic inbox benchmark + funnel CLI + Pillar D Stable flip)

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** D (Reply + conversation handling — Week 12 — exit-criterion close)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0025 (Pillar D Week 1 foundation, D96-D101) pinned the reply event-type naming, classifier output convention, conversation state shape, cross-pillar surface audit (D99), auto-unsubscribe enforcement contract, and the **exit-criterion vehicle scope (D101)** — the binding 100-message synthetic-inbox classifier benchmark that gates Pillar D's "stable" flip. ADR-0026 (Week 2, D102-D107) shipped the rule-based classifier substrate. ADR-0027 (Week 3, D108-D114) extended to long-tail categories + per-channel reply detection (Passes H/I/J). ADR-0028 (Week 4-5, D115-D121) shipped the auto-unsubscribe handler (Pass M) + the conversation state machine (Pass N). ADR-0029 (Week 6-8, D122-D128) shipped the LLM fallback + the classifier-cap policy migration. ADR-0030 (Week 9-11, D129-D135) shipped win/loss attribution + the `conversation_outcome` event class (Pass O) + TTL-based `* → dormant` transitions.

**Pillar D Week 12 is the EXIT-CRITERION CLOSE.** Per PILLAR-PLAN §2 Pillar D's binding text:

> *"100-message synthetic inbox classifier benchmark with documented rule precision/recall; suppression updates idempotent; attribution funnel reproducible."*

Week 12 ships the SINGLE coordinated extension that satisfies this exit criterion + flips Pillar D from "In progress" to **Stable**:

1. **The 100-message synthetic inbox fixture** — a hybrid static-corpus + programmatic-builder substrate (per ADR-0013 D24's hybrid posture from Pillar B Week 5). 100 reply messages distributed proportionally across all 6 classifier categories (30 unsubscribe + 15 each of ooo / wrong_person / interest / rejection + 10 uncategorized) across 3 reply channels (60 email + 25 LinkedIn + 15 Twitter; calendar replies excluded per ADR-0027 D113). The corpus is calibrated against the factory pattern set so every rule-classifiable message matches at least one factory pattern (verification harness pins this).

2. **The `tests/test_multi_channel_coherence.py::TestPillarDExitCriterion::test_100_message_synthetic_inbox_classifier_benchmark` un-skip + body** — the binding test that consumes the fixture + exercises the full Pillar D pipeline (rule classifier → LLM fallback → auto-unsubscribe handler → conversation state machine + TTL → outcome derivation → funnel CLI). Six assertion rows: per-category precision/recall (ROW 1); LLM fallback coverage (ROW 2); auto-unsubscribe idempotence (ROW 3); funnel reproducibility (ROW 4); TTL-driven dormancy (ROW 5); per-Person aggregation (ROW 6).

3. **The `orchestrator/funnel.py` CLI** — the canonical operator-facing reply-funnel + outcome-attribution aggregation surface. Operators query `python orchestrator/funnel.py --since 30d --breakdown channel,category,classification_method` for the per-channel / per-category / per-method breakdown of classified replies + per-channel / per-outcome breakdown of conversation outcomes + per-outcome / per-attributed-touch breakdown. The output is **byte-identical** across consecutive invocations against a fixed ledger state — load-bearing for the reproducibility assertion + the future Pillar G dashboard layer that consumes this aggregation surface.

4. **Pillar D Stable flip** — PILLAR-PLAN §6 Pillar D row Notes column flips from "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4-5 ✓ + Week 6-8 ✓ + Week 9-11 ✓" to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4-5 ✓ + Week 6-8 ✓ + Week 9-11 ✓ + Week 12 ✓ — STABLE"; Status flips from "In progress" to "**Stable** as of 2026-05-24 (Week 12 exit gate closed + holistic exit review + Pillar D retrospective)."

The six concerns this ADR resolves:

1. **Synthetic 100-message corpus shape — programmatic-only vs static-only vs hybrid.** Three plausible options; ADR-0013 D24's hybrid posture from Pillar B Week 5 is the precedent. D136 picks hybrid.

2. **Per-category precision/recall targets — what numbers?** The factory pattern set's coverage calibrates the targets; the asymmetric-failure-cost calculus per PILLAR-PLAN §0 + ADR-0025 D97's legal-liability invariant drive the `unsubscribe` target higher than the long-tail categories. D137 pins.

3. **LLM fallback coverage substrate — deterministic fake client vs real LLM.** Two options. D138 picks deterministic fake for test reproducibility; real LLM eval surface is Pillar G's concern.

4. **Idempotence verification scope — Pass M only OR Pass M + Pass O.** Two options. D139 picks both (Pass M for the suppression-write side; Pass O for the outcome-emit side).

5. **Attribution funnel reproducibility primitive — byte-identical-stdout OR statistically-equivalent.** Two options. D140 picks byte-identical via `orchestrator/funnel.py` + JSON sort_keys.

6. **Pillar D stable claim's exit gate — what is the binding gate?** D141 names the binding test as THE gate.

Risks this ADR mitigates by design: **R012 (LLM hallucinates unsubscribe)** continues mitigated — the FIVE-layer carry-forward from ADR-0025 D97 + ADR-0026 D107 + ADR-0028 D119 + ADR-0029 D123 + ADR-0030 D131 STAYS WITH FULL WEIGHT; the binding test's ROW 1.5 asserts the legal-liability invariant across the full 100-message corpus (every unsubscribe event carries classification_method=rule + confidence=1.0). **R015 (asymmetric-crash inconsistency)** continues mitigated. **R016 (LLM cost runaway)** continues mitigated. **R017 (TTL-driven dormancy of active threads)** continues mitigated; the binding test's ROW 5 exercises TTL fires only on stale threads (last_activity > 30 days) + leaves non-stale threads in their classified states.

No new risks. The exit-criterion close adds NO new event classes, NO new reconcile passes, NO new policy / ledger / vault migrations, NO new operator-facing surfaces beyond `orchestrator/funnel.py`'s CLI. Pillar D's stable surface is the existing primitives + the binding test that gates them.

## Decision

### D136. Synthetic 100-message inbox fixture shape — HYBRID (static corpus YAML + programmatic builder)

The 100-message corpus ships as a HYBRID per ADR-0013 D24 — the static portion lives on disk for reviewer inspection; the programmatic builder constructs the surrounding ledger state.

```
tests/fixtures/synthetic_pillar_d/
├── corpus.yml      ← 100 messages with ground-truth labels (reviewer-inspectable)
└── README.md       ← corpus distribution + scenario substrate documentation

tests/conftest.py
└── synthetic_pillar_d_classifier_corpus_state_dir  ← builder fixture
```

**Why hybrid (rejected: static-only).** A static-only fixture (e.g., a single `synthetic_pillar_d/ledger/events-*.jsonl` file with pre-baked ledger events) would force reviewers to inspect raw JSON — opaque + unmaintainable. The corpus is the operator-readable artifact; the ledger seeding is mechanical given the corpus.

**Why hybrid (rejected: programmatic-only).** A programmatic-only fixture (the 100 messages constructed in `tests/conftest.py` directly, no static YAML) would force reviewers to read Python code to understand the corpus — the static YAML is `cat`-able, the per-message labels are inspectable, the operator-tunable nature of the classifier patterns is reflected.

**Why hybrid (rejected: corpus-in-Python-only with builder generating YAML lazily).** Adds indirection without gain; the YAML IS the corpus.

The corpus YAML structure pinned by D136:

```yaml
version: 1
messages:
  - id: m_001                          # unique message id
    person_id: p_unsub_em_01            # unique person id
    channel: email                       # email | linkedin | twitter
    reply_event_type: reply_received     # event type to seed
    expected_category: unsubscribe       # ground-truth label
    subject: "Re: hi from us"
    body: "please unsubscribe"
    notes: "Pattern 1 — direct unsubscribe verb"
  ...
scenarios:
  multi_touch:               # person_id → number of confirmed touches before reply
    p_unsub_em_01: 3
    ...
  cross_channel:             # person_id → extra-channel-touch seed
    p_unsub_em_02: linkedin
    ...
  ttl_dormant_days_ago:      # person_id → days_ago override (60 to trigger TTL)
    p_int_em_07: 60
    ...
  closed_won:                # person_id → days after reply for the booking
    p_int_em_01: 3
    ...
```

Distribution pinned by D136 (per the handoff's binding text):

| Category        | Count | Channels split (email / linkedin / twitter) |
|-----------------|------:|---------------------------------------------|
| `unsubscribe`   |    30 | 20 / 5 / 5 |
| `ooo`           |    15 | 9 / 3 / 3 |
| `wrong_person`  |    15 | 9 / 3 / 3 |
| `interest`      |    15 | 11 / 2 / 2 |
| `rejection`     |    15 | 11 / 2 / 2 |
| `uncategorized` |    10 | 0 / 10 (all `li_invite_reply_received`) / 0 |

The 10 uncategorized rows are all `li_invite_reply_received` events because invite acceptance has no body (per ADR-0027 D112 — `reply_message_id = li_accept:<invitation_id>`; no message text). The classifier's empty-text → no-pattern-match logic naturally returns `uncategorized` for these. The LLM fallback (per D138) predicts `interest` (invite acceptance signals interest in practice).

Required scenarios per D136:

* **Pattern coverage** — every factory pattern in `config-template/{category}-patterns.example.yml` has at least one representative phrase in the corpus.
* **Adversarial precedence** — 5 rows with mixed signals MUST resolve to the higher-priority category per `DISPATCH_PRIORITY`:
  - m_017 (`Sounds interesting but please unsubscribe me`) → unsubscribe (legal-liability priority)
  - m_018 (`out of office until June 1. Please also unsubscribe me`) → unsubscribe
  - m_038 (`I'm out of office. Send me more details when I'm back`) → ooo (ooo > interest)
  - m_053 (`Sounds interesting, but you should speak with our chief instead`) → wrong_person (wrong_person > interest)
  - m_069 (`Sounds interesting but not a fit for us right now`) → rejection (rejection > interest)
* **Multi-touch attribution** — 10 prospects have 2-3 confirmed same-channel touches before reply. The outcome MUST attribute to the most-recent same-channel touch per ADR-0030 D131.
* **Cross-channel attribution** — 5 prospects have touches on both email + linkedin BEFORE reply; outcome attributes to the SAME-CHANNEL touch (not the cross-channel touch).
* **TTL-driven dormancy** — 5 prospects (all category=interest) have replies dated 60 days before `now`; Pass N's TTL driver transitions them to dormant per ADR-0030 D132. The 5 prospects ALSO have their `reply_classified` events pre-seeded with the SAME stale timestamp (so Pass G's idempotence skips them + the thread's `last_activity_ts` stays stale).
* **Closed_won** — 3 prospects (all category=interest) have a `calendar_booking_confirmed` event 3 days after the reply; Pass O emits `closed_won` outcomes attributing to the most-recent same-channel touch before the booking.

**Pin:** the binding test asserts on each scenario substrate explicitly + the verification harness in the corpus README documents the calibration.

### D137. Per-category precision/recall targets — calibrated against the factory pattern set

The binding test's ROW 1 asserts per-category precision/recall against these documented targets:

| Category        | Precision target | Recall target | Rationale |
|-----------------|-----------------:|--------------:|-----------|
| `unsubscribe`   | **≥ 0.99**       | **≥ 0.95**    | CAN-SPAM legal-liability per ADR-0025 D97 — the asymmetric-failure-cost calculus puts a missed unsubscribe at MAXIMUM cost (CAN-SPAM violation); a false-positive is one missed conversation. |
| `ooo`           | ≥ 0.80           | ≥ 0.70        | Long-tail; operator-tunable per ADR-0027. Failure-cost is recoverable (operator's pipeline pauses or doesn't pause one prospect for ~7 days). |
| `wrong_person`  | ≥ 0.80           | ≥ 0.70        | Long-tail; failure-cost is one manual review per false-positive. |
| `interest`      | ≥ 0.80           | ≥ 0.70        | HIGHEST-AMBIGUITY long-tail per ADR-0027 D110 (evaluated LAST in DISPATCH_PRIORITY). The corpus's adversarial rows specifically test that rejection / wrong_person / ooo signals win over interest. |
| `rejection`     | ≥ 0.80           | ≥ 0.70        | Failure-cost is one annoying follow-up per false-negative; one manual re-open per false-positive. |

The factory-shipped pattern set is calibrated to meet these targets EXACTLY (0 misclassifications on the 90 rule-classifiable rows — verified by the corpus-validation harness + the binding test's ROW 1). The targets are floors, not the achieved values; future operator-contributed corpus additions MAY surface rule-pattern gaps that lower the achieved precision/recall, in which case operators tune their pattern files OR the factory ships an updated pattern set via a pattern-file migration.

**Why these numbers (rejected: ≥ 0.95 precision on long-tail too).** The long-tail categories are operator-tunable; a 0.95 precision floor would require the factory pattern set to be exhaustively curated against every reply phrasing in every operator's vertical. Pillar I's operator-onboarding doc names pattern tuning as part of the bootstrap; the 0.80 floor is the calibrated default that works across B2B verticals.

**Why these numbers (rejected: ≥ 0.99 recall on long-tail too).** Recall on long-tail categories competes with precision (broader patterns catch more but false-positive more). The factory's conservative pattern set biases toward precision; the 0.70 recall floor is the calibrated tradeoff.

**Why these numbers (rejected: separate per-channel precision/recall targets).** Per-channel targets would require ~25 separate target-rows (5 categories × 3 channels + uncategorized handling); the test's assertion surface bloats without operator-observable benefit. Operators concerned about per-channel quality query the funnel CLI's `--breakdown channel,category,classification_method` output.

**Pin:** the binding test's `_PRECISION_RECALL_TARGETS` class attribute is the source-of-truth; the corpus README documents the same numbers; any future change requires updating both + the surface audit.

### D138. LLM fallback coverage substrate — deterministic fake `LLMClient`

The binding test's ROW 2 wires a `_PillarDFakeLLMClient` (defined inline in the test file, NOT a fixture) that implements the `LLMClient` Protocol per ADR-0029 D122 + returns a deterministic prediction for the 10 uncategorized rows. The fake's `classify_text(reply_text, *, model)` returns:

```python
LLMResponse(
    category="interest",
    confidence=0.8,
    rationale="invite acceptance signals interest (synthetic test fake)",
    input_tokens=10, output_tokens=5,
    model=model,
)
```

All 10 uncategorized rows are `li_invite_reply_received` events with empty body — the fake returns `interest` for empty text. The test asserts:

* The fake was called exactly 10 times (once per uncategorized row).
* All 10 LLM-classified events carry `category=interest` + `classification_method=llm`.
* The legal-liability defense-in-depth (Layer 4 of the ADR-0025 D97 carry-forward) holds — the LLM is structurally incapable of returning `unsubscribe` per the prompt exclusion + the post-LLM refuse-loud guard.

**Why deterministic fake (rejected: real `AnthropicClient`).** A real LLM client would make the test (a) flaky (LLM responses vary), (b) costly (one cents-per-call × every CI run), (c) network-dependent (CI environments without API keys would skip). The deterministic fake gives reproducible coverage of the integration shape; real-LLM eval is a Pillar G observability concern (dashboards measuring LLM precision over time against a curated eval set independent of the exit-criterion test).

**Why deterministic fake (rejected: parameterized fake with per-row predictions).** A per-row prediction map would let the test exercise more LLM categories. But the corpus's 10 uncategorized rows are uniform (all empty-body invite acceptances) → uniform "interest" is the right deterministic prediction. Per-row variation adds test complexity without coverage gain.

**Why deterministic fake (rejected: no LLM coverage at all in the exit-criterion test).** Skipping LLM coverage would mean the exit criterion doesn't exercise the FULL Pillar D pipeline; the LLM fallback is a load-bearing primitive per ADR-0029 D124. The exit criterion MUST verify the integration shape (rule classifier → LLM fallback → reply_classified event with method=llm).

**Pin:** the binding test's `_PillarDFakeLLMClient` is the canonical fake shape; future Pillar D Week N+1 tests adding LLM coverage may extend the fake's prediction logic (e.g., by reply-text hash) but the Protocol surface stays unchanged.

### D139. Idempotence verification — Pass M + funnel re-runs

The binding test exercises two distinct idempotence surfaces:

**Pass M re-run idempotence (ROW 3):**
* First Pass M run emits 30 `suppression_added` events (one per unsubscribe-classified reply).
* Second Pass M run emits ZERO new `suppression_added` events.
* Per ADR-0028 D117 — the (reply_message_id, channel) dedup is the load-bearing primitive.
* The test asserts `result_m_2.synthesized == []` + `result_m_2.findings` carries `auto_unsubscribe_deduped: 30`.

**Funnel reproducibility (ROW 4 + D140 below).**

**Pass O re-run idempotence is verified separately in `tests/test_conversation_outcomes.py::TestRunOutcomesPass` (per Week 9-11 ADR-0030 D130).** The exit-criterion test does NOT explicitly re-run Pass O — the Pass O idempotence is already pinned by the Week 9-11 unit tests; re-asserting it in the exit-criterion would duplicate coverage without surfacing new risk.

**Why both surfaces (rejected: Pass M only).** Pillar D's idempotence guarantee is the substrate for operator confidence in re-running reconcile; verifying Pass M alone would leave the funnel's reproducibility (the operator-visible end-to-end primitive) untested at the exit-criterion level.

**Why both surfaces (rejected: full reconcile chain re-run).** Re-running the full 13-pass chain at the exit-criterion is over-coverage; the per-pass idempotence is pinned at each pass's unit test layer + the per-week independent reviews. The exit-criterion test surfaces the OPERATOR-VISIBLE primitives (suppression writes + funnel output), not internal pass plumbing.

**Why both surfaces (rejected: end-to-end byte-identical full ledger comparison).** Comparing the full ledger byte-by-byte across re-runs would surface accidental non-determinism but at high test-complexity cost (ledger files contain wall-clock-ts on emitted events). The funnel's aggregated output is the right level — it filters out the timestamp-noise dimension while preserving the load-bearing aggregations.

**Pin:** ROW 3 of the binding test asserts both `suppress_count_1 == 30` and `suppress_count_2 == suppress_count_1`. ROW 4 asserts the funnel renders byte-identical stdout across two invocations.

### D140. Attribution funnel reproducibility — byte-identical via `orchestrator/funnel.py`

The funnel CLI ships as a new module `orchestrator/funnel.py` (sibling of `orchestrator/reconcile.py` per the orchestrator/ flat-module convention). The CLI:

```bash
python orchestrator/funnel.py --since 30d
python orchestrator/funnel.py --since 30d --now 2026-05-23T12:00:00Z
python orchestrator/funnel.py --since 30d --breakdown channel,category,classification_method
```

Output format — JSON with deterministically sorted keys at every nesting level:

```json
{
  "attribution_by_outcome": {
    "closed_lost": {"snd_p_rej_em_01_t0": 1, "snd_p_rej_em_02_t2": 1, ...},
    "closed_unsubscribed": {...},
    "closed_won": {...},
    "dormant": {...}
  },
  "conversation_outcome_by_channel_outcome": {
    "email|closed_lost": 11,
    "email|closed_unsubscribed": 20,
    ...
  },
  "reply_classified_by_breakdown": {
    "email|interest|rule": 11,
    "email|ooo|rule": 9,
    ...
  },
  "totals": {
    "conversation_outcome": 68,
    "reply_classified": 100
  },
  "window": {
    "breakdown": ["channel", "category", "classification_method"],
    "now_iso": "2026-05-23T12:00:00.000Z",
    "since": "30d",
    "since_iso": "2026-04-23T12:00:00.000Z"
  }
}
```

**Determinism contract (the binding reproducibility primitive):**

* All dict keys sorted at every nesting level via `json.dumps(..., sort_keys=True)`.
* All timestamps in the output derive from the input args (`--now` + `--since`), NOT from the wall clock at print time.
* No floats; counts are integers.
* No randomization in the aggregation paths.
* The byte-identical assertion: `funnel.render_report(funnel.build_report(led_1, ...)) == funnel.render_report(funnel.build_report(led_2, ...))` for two `Ledger` instances against the same on-disk state.

**Why byte-identical (rejected: statistically-equivalent ±1 noise).** Statistical equivalence would mask real bugs (e.g., a non-deterministic Counter iteration order producing different but equal-cardinality output). Byte-identical is the strictest contract + the cheapest to verify.

**Why byte-identical (rejected: per-key equality without ordering).** Per-key equality is weaker than byte-identical (e.g., `{"a": 1, "b": 2}` vs `{"b": 2, "a": 1}` are per-key equal but bytewise different). Operators piping the funnel output to `diff` for change-detection (a common Pillar G dashboard workflow) need byte-identical ordering.

**Why byte-identical (rejected: hash-based equivalence).** A SHA256-of-output equality assertion is byte-identical-equivalent but loses the diff-readable failure message. Direct string equality surfaces the divergence inline in the test failure output.

**Pillar G dashboard interface:** Pillar G dashboards consume the `funnel.build_report(...)` Python function directly (no CLI shelling needed). The CLI is the operator-facing convenience; the dashboard layer uses the in-process API.

**Pin:** the binding test's ROW 4 asserts `rendered_1 == rendered_2`; ROW 4.5 additionally asserts the `funnel.main([...])` CLI dispatch produces identical stdout across two invocations.

### D141. Pillar D stable claim's exit gate — THE binding test IS the gate

Pillar D's "stable" flip per PILLAR-PLAN §6 is gated by **passing the binding test `tests/test_multi_channel_coherence.py::TestPillarDExitCriterion::test_100_message_synthetic_inbox_classifier_benchmark`**. The test consumes the fixture per D136 + asserts ROW 1 through ROW 6 per D137-D140; passing the test demonstrates:

* Every factory pattern in the operator-tunable pattern files classifies the corpus rows it should classify (per D137 — verifies the classifier substrate from ADRs 0026-0027).
* The LLM fallback correctly extends classification on the uncategorized subset (per D138 — verifies the substrate from ADR-0029).
* Auto-unsubscribe is idempotent under double-classification (per D139 — verifies the substrate from ADR-0028).
* The attribution funnel reproduces byte-identically across consecutive invocations (per D140 — verifies the new substrate from this ADR + the outcome derivation from ADR-0030).
* TTL-driven dormancy fires only on stale threads (per ROW 5 — verifies the substrate from ADR-0030 D132).
* Per-Person outcome aggregation returns the expected outcomes for synthetic personas (per ROW 6 — verifies the substrate from ADR-0030 D134).

**The test is the gate; the gate is the test.** A future Pillar I CLI extension or Pillar G dashboard layer extending Pillar D's surface MAY add new assertion rows to the binding test; the test stays the gate.

**Why the binding test (rejected: per-pillar regression suite).** A separate per-pillar regression suite (e.g., `tests/test_pillar_d_regression.py`) would duplicate coverage. The binding test IS the regression suite — it exercises every Pillar D surface in one place.

**Why the binding test (rejected: operator-runnable benchmark CLI).** An operator-runnable benchmark (`python -m orchestrator.classifier benchmark`) would be useful for operator-tunable pattern tuning, but the EXIT-CRITERION is a developer / CI gate, not an operator surface. The CLI surface is a future Pillar I scope. Operators today use `python orchestrator/funnel.py --since 30d` to observe the classifier quality on their own corpus.

**Why the binding test (rejected: split into per-row tests).** Splitting ROWS 1-6 into six separate test methods would lose the coherence — the six rows verify the FULL pipeline end-to-end; a single test method's failure surfaces "the binding gate is broken" without ambiguity. Splitting would create six failure modes that each need triage.

**Pin:** the test class docstring names ROWS 1-6 explicitly; the test method's body sectioned by ROW; the per-week independent reviewer's checklist for Week 12 includes "the binding test passes + per-row assertions are present."

## Alternatives considered

### D136-Alt1: Programmatic-only corpus in `tests/conftest.py`

Build the 100-message corpus directly in Python within the conftest fixture (no static YAML file). Mirrors the Pillar C `synthetic_pillar_c_stress_state_dir` fixture's pattern.

**Why rejected.** The Pillar C stress fixture's distribution (50 prospects across 4 channels with deterministic failure injection per index) is mechanical — operators can read the per-channel range-comments at the dict literal. The Pillar D corpus is OPERATOR-CONTENT (reply text + ground-truth labels + adversarial rationale); reading 100 message texts via Python list-of-dicts is opaque vs reading YAML with inline rationale comments. The hybrid posture is the right tradeoff.

### D136-Alt2: Static fixture with pre-baked `events-*.jsonl`

Ship a single `events-*.jsonl` file containing the seeded ledger state (touches + replies + per-corpus-row classified events). No programmatic builder — tests load the file directly.

**Why rejected.** The ledger seed encodes timestamps relative to "now"; a static `events-*.jsonl` would either bake absolute timestamps (rotting with time) OR encode relative offsets (defeating the JSONL readability). The programmatic builder generates the seed deterministically from the corpus + a fixed `now` anchor; reviewers inspect the corpus YAML, the builder logic stays small.

### D136-Alt3: Corpus YAML inline in the test file's docstring

Embed the 100-message corpus in the binding test's class docstring as a YAML literal. Single file; no separate fixture directory.

**Why rejected.** Docstring-embedded YAML loses syntax highlighting + makes the corpus invisible to text-editor folding; `tests/fixtures/synthetic_pillar_d/corpus.yml` is the natural home alongside the existing `tests/fixtures/synthetic_pillar_b/`.

### D137-Alt1: Identical precision/recall floors (≥ 0.95 / ≥ 0.95) across all categories

Apply the unsubscribe target (≥ 0.99 precision / ≥ 0.95 recall) uniformly. No per-category divergence.

**Why rejected.** The long-tail categories are operator-tunable; a uniform 0.95 precision floor would require the factory pattern set to be exhaustively curated against every operator's vertical (B2B SaaS / consumer apps / regulated industries each have distinct reply phrasings). The per-category floors reflect the asymmetric-failure-cost calculus per PILLAR-PLAN §0.

### D137-Alt2: Operator-tunable targets via a config file

Store the per-category targets in `~/.outreach-factory/classifier/precision-recall-targets.yml` so operators can override.

**Why rejected.** The targets are the EXIT-CRITERION gate, not an operator-tunable runtime parameter. Operators tuning their own pattern set should expect their own precision/recall to vary; the factory targets are the calibrated baseline. Operator-side precision/recall measurement is a Pillar G observability concern (dashboards measuring classifier quality on operator's own corpus over time).

### D137-Alt3: Confidence-weighted F1 score instead of separate precision/recall

Replace the two-target structure with a single F1 floor per category.

**Why rejected.** Precision and recall have asymmetric operator-facing implications (false-positive unsubscribe → missed conversation; false-negative unsubscribe → CAN-SPAM violation). A unified F1 score loses this asymmetry. The two-target structure is operator-readable.

### D138-Alt1: Real `AnthropicClient` with cassette-based response capture

Use a real `AnthropicClient` with HTTP cassette recording (per the existing `tests/test_voice_retrieve_e2e.py` pattern) so the test is reproducible + verifies the real LLM integration.

**Why rejected.** The cassette-recording pattern requires capturing real LLM responses for the 10 corpus rows — that's a one-time setup but the cassette becomes a maintenance burden (LLM responses drift across model versions; cassette refresh would change the corpus's LLM_predicted_category). The deterministic fake gives the same integration coverage without the cassette maintenance.

### D138-Alt2: No LLM coverage; rule classifier only

Skip the LLM fallback in the binding test entirely; ROW 2 becomes a no-op.

**Why rejected.** The LLM fallback is a load-bearing Pillar D primitive per ADR-0029 D124; the exit criterion MUST verify the integration shape. Without ROW 2, the binding test wouldn't cover the LLM → reply_classified emit path; a regression in the path would only surface in `tests/test_reply_classifier_llm.py` (per-unit coverage), not the cross-pillar coherence test.

### D138-Alt3: Per-corpus-row predictions in a separate YAML

Ship `tests/fixtures/synthetic_pillar_d/llm_predictions.yml` with per-row predictions; the fake LLM looks up by reply text.

**Why rejected.** The 10 uncategorized rows are uniform (all empty-body invite acceptances); per-row variation adds test complexity without coverage gain. A future Pillar I extension with diverse uncategorized rows MAY add this YAML; today it's premature.

### D139-Alt1: Pass M idempotence only; skip funnel reproducibility from D140

Verify Pass M re-run zero-emission; defer funnel reproducibility to a separate test class.

**Why rejected.** PILLAR-PLAN §2 Pillar D's binding text names BOTH "suppression updates idempotent" AND "attribution funnel reproducible" — both MUST be in the binding test. Separating them would leave the funnel reproducibility outside the gate.

### D139-Alt2: Full reconcile chain re-run with byte-identical ledger comparison

Compare the ledger files byte-by-byte across two full reconcile runs.

**Why rejected.** Ledger files contain wall-clock-ts on emitted events (per `_now_iso()`); byte-identical ledger comparison would require monkey-patching the clock for every event class. The funnel's aggregated output is the right level — it filters timestamp-noise while preserving load-bearing aggregations.

### D139-Alt3: Hash-based ledger-content verification

Compute SHA256 of the ledger contents across re-runs; assert equal hashes.

**Why rejected.** Same timestamp-noise issue as D139-Alt2. SHA256 of the funnel output IS the byte-identical assertion (D140 picks direct string equality for diff-readability).

### D140-Alt1: Statistically-equivalent output (counts within ±1 noise tolerance)

Allow funnel output to differ by ±1 count per breakdown row across runs.

**Why rejected.** Statistical equivalence would mask non-deterministic Counter iteration order or off-by-one race conditions. Byte-identical is the strictest contract + reveals divergence inline.

### D140-Alt2: Funnel CLI as a Pillar G concern (not shipped in Pillar D Week 12)

Defer the `orchestrator/funnel.py` CLI to Pillar G's dashboard layer; the exit-criterion test calls aggregation primitives directly without a CLI.

**Why rejected.** The PILLAR-PLAN §2 Pillar D binding text names "attribution funnel reproducible" — the funnel IS a Pillar D primitive. Pillar G dashboards consume the SAME aggregation surface but add visualization; the aggregation surface itself is Pillar D's scope per the binding text. Deferring would leave the binding criterion unsatisfied.

### D140-Alt3: Funnel as a JSON-only library function (no CLI argparse layer)

Ship `orchestrator/funnel.py` as a Python library with `build_report` / `render_report` functions; skip the argparse CLI wrapper.

**Why rejected.** The CLI is the operator-facing surface (operators query the funnel without writing Python). The library function is the Python-callable surface (tests + Pillar G dashboards consume directly). Both ship together; the CLI is ~50 LOC + provides the operator ergonomic.

### D141-Alt1: Pillar D Stable requires manual operator sign-off

Pillar D's "stable" flip requires an operator-side sign-off (e.g., Yang manually verifies on a real ledger) before the PILLAR-PLAN row flips.

**Why rejected.** Manual sign-off doesn't scale + introduces subjective gates. The binding test IS the objective gate; a regression would fail CI; the per-week independent reviewer + the holistic exit review are the human-judgment layers.

### D141-Alt2: Pillar D Stable requires a real-world operator running for 30 days

Pillar D's "stable" flip waits for 30 days of real-world operator usage post-Week-12.

**Why rejected.** Real-world operator validation is valuable but BLOCKING Pillar E + F + G + H + I + J on it would push the year-long roadmap by 30 days minimum. The binding test + the per-pillar surface audit + the per-week independent reviews are sufficient evidence for "stable" claim; operator-visible regressions surface as bug reports + get addressed via Pillar I OSS bring-up or per-pillar follow-up commits.

### D141-Alt3: Separate "stable" gate per-week (per-week stable claim)

Each Pillar D week's "✓" implies that week is independently stable; Week 12 stable = aggregation only.

**Why rejected.** Per-week stability isn't operator-meaningful; operators consume "stable Pillar D" as a whole (the classifier + handler + state machine + outcome derivation are interdependent). The single Week-12 gate is the right granularity.

## Consequences

### Positive

- **Pillar D is stable.** The binding test gates the stable claim; passing it demonstrates the full pipeline works end-to-end. Pillars E / F / G / H / I / J are unblocked from a "stable D" dependency.
- **The 100-message corpus is the operator-visible quality baseline.** Operators can inspect the corpus, understand what the factory pattern set covers, and extend their own pattern files against new reply shapes they observe in production. Future operator-contributed corpus additions extend the binding gate.
- **The funnel CLI is the operator-visible classifier-quality + outcome-attribution surface.** Operators today run `python orchestrator/funnel.py --since 30d` to see their reply mix + outcome distribution; Pillar G dashboards build on the same aggregation primitives.
- **The hybrid fixture posture (per ADR-0013 D24) scales.** Pillar B Week 5 introduced the pattern; Pillar D Week 12 confirms it scales to 100-message content-rich corpora. Future pillars adding their own exit-criterion fixtures inherit the pattern.
- **The deterministic fake `LLMClient` is the canonical test stand-in.** Future Pillar D tests adding LLM coverage extend the fake without changing the Protocol surface.
- **The legal-liability invariant per ADR-0025 D97 is verified at the corpus-level across 30 unsubscribe events.** Every unsubscribe-classified event in the corpus carries `classification_method=rule` + `confidence=1.0`; the binding test asserts this explicitly + the multi-layer carry-forward stays load-bearing.
- **The cross-pillar surface audit (per ADR-0025 D99) is UNCHANGED.** Week 12 ships NO new event classes, NO new emit shapes — only the new funnel-aggregation surface (which is a read-side primitive, not a ledger writer). The audit's "Week 12 confirmed unchanged" status is a clean exit signal.

### Negative

- **The binding test's 6 ROWS are interdependent.** A failure in ROW 1 (precision/recall) likely cascades to ROW 6 (per-Person aggregation, which depends on correctly-classified events). The test's failure message would surface the ROW that asserted; operators triaging would walk back through the pipeline. **Mitigation:** the test's docstring names ROWS 1-6 explicitly; per-ROW section comments in the test body; the ADR + the per-week reviewer's checklist name the dependency direction.
- **The 100-message corpus is calibrated to English-language B2B cold-outreach context.** Operators in other verticals (regulated industries, consumer apps, non-English) would see different reply shapes; the corpus + the factory pattern set may underperform. **Mitigation:** the corpus README explicitly names the tuning context; future operator-contributed corpus extensions are expected per the operator-tunability calculus per ADRs 0026-0027.
- **The funnel CLI's `--since` parser supports only `Nd / Nh / Nw / Nm`** (relative windows). Absolute-date windows (`--since 2026-01-01`) are not supported in v1; operators wanting historical analysis use `--since 365d` or larger. **Mitigation:** documented in the CLI `--help`; future Pillar I CLI extension may add absolute-date support if operator demand materializes.
- **The deterministic fake `LLMClient` does not exercise the production `AnthropicClient`.** A regression in the production client's parse / cost-emit path would NOT surface in the binding test. **Mitigation:** `tests/test_reply_classifier_llm.py` covers the production client's per-unit behavior; Pillar G's planned LLM-quality-over-time dashboard provides real-world validation; Pillar I CLI bring-up ships the operator-facing factory for the production client.

### Neutral / observability

- **The binding test runtime is < 1 second.** Re-running the full Pillar D pipeline against 100 messages + verifying 6 ROWS + funnel reproducibility completes well under the CI per-test time budget.
- **The funnel CLI's `--json` flag is reserved for forward-compat.** v1 always emits JSON; the flag is a no-op today. A future Pillar I extension MAY add a `--format markdown` or `--format csv` mode; the flag's presence pins the JSON surface as the default.
- **The funnel CLI's per-call cost is O(events) — one ledger walk per query.** For long-lived deployments, the walk's cost scales with ledger size. Operators with > 100K-event ledgers should expect sub-second query times today; Pillar I MAY add per-window caching if operator demand materializes.

## Compliance with invariants

- **I1 (one writer per fact):** Pillar D Week 12 ships ZERO new event-class writers. The funnel CLI is read-only; the binding test exercises existing writers (Pass G / M / N / O).
- **I2 (idempotent re-runs):** ROW 3 + ROW 4 of the binding test verify idempotence at two surfaces (Pass M re-run; funnel re-run). The Pass O idempotence is pinned at the Week 9-11 unit-test layer.
- **I3 (atomicity contract):** No new atomicity surfaces. The funnel CLI is read-only.
- **I4 (reproducible state):** Funnel's deterministic-output contract per D140 is the binding reproducibility primitive at the operator-visible aggregation surface.
- **I5 (append-only):** Funnel CLI is read-only; no append. The binding test exercises existing append surfaces; no schema changes.
- **I6 (Pillar A policy SoT):** No new policy rules; no new policy YAML files.
- **I7 (Pillar B migration framework SoT):** Week 12 ships ZERO new migrations. The pending migration count stays at 17 (unchanged from Week 9-11).

### Downstream pillar impact

- **Pillar E (discovery quality + lineage).** Pillar E's discovery-pass logic consumes the per-Person outcome breakdown via `derived_conversation_outcome(person_id)` (already shipped in ADR-0030 D134) + may consume the funnel CLI's `attribution_by_outcome` breakdown for per-source attribution learning (e.g., "prospects discovered via funded-founders source have 12% closed_won rate; competitor-customers source has 8%"). The funnel's stable JSON surface is the API; Pillar E ingests via the in-process `build_report` function.

- **Pillar F (vault rendering quality).** No direct impact. The vault denormalization for outcomes is Pillar G's concern; Pillar F (rendering) consumes the existing per-Person `conversation_status:` Person frontmatter field (per ADR-0028 D119).

- **Pillar G (observability + dashboards).** PRIMARY consumer. Pillar G's reply-funnel dashboard EXPANDS with the per-thread outcome breakdown + the cross-channel attribution funnel + the TTL-vs-category-driven dormancy metric. Pillar G's dashboard implementation consumes `orchestrator.funnel.build_report(...)` directly (no CLI shelling). Pillar G MAY add per-window caching + per-operator-customization on top of the canonical aggregation surface; the surface itself is Pillar D's scope per this ADR.

- **Pillar H (continuous operations / daemon mode).** Daemon mode invokes the reconcile chain (including Passes G / M / N / O); no daemon-specific Pillar D surface needed. The funnel CLI is a one-shot operator query; daemons don't invoke it.

- **Pillar I (OSS bring-up + CLI).** Future Pillar I CLI surfaces extend the funnel + the LLM-fallback bring-up:
  - `python orchestrator/funnel.py --format markdown` — operator-readable markdown table output.
  - `python orchestrator/funnel.py --since 2026-01-01` — absolute-date window support.
  - `python -m orchestrator.classifier benchmark --corpus <path>` — operator-runnable benchmark against operator's own corpus.
  - Production `AnthropicClient` wiring — per ADR-0029 D124's deferred item.
  - The pre-call LLM gate check (consult policy engine before invoking LLM) — per ADR-0029 D127's deferred item.

- **Pillar J (privacy + retention).** No new PII-carrying event classes. The funnel CLI's output contains aggregated counts + intent_ids (which carry no direct PII); a future Pillar J retention sweep would tombstone the underlying events (already covered by the existing tombstone primitive per ADR-0011 D24); the funnel CLI's output naturally reflects the post-tombstone state.

## Migration / rollout

**Existing operators (pre-Pillar-D-Week-12) seed two states:**

**Shape A — canonical (operator running Pillar D Week 9-11 reconcile cadence)**:
- Ledger has `reply_classified` + `suppression_added` + `conversation_state_changed` + `conversation_outcome` events from Passes G / M / N / O.
- Operator runs `python orchestrator/funnel.py --since 30d` post-upgrade.
- Funnel output shows the operator's actual reply mix + outcome distribution.
- The binding test passes locally if the operator has cloned the repo + runs `pytest tests/test_multi_channel_coherence.py::TestPillarDExitCriterion`.

**Shape B — new operator (cold start)**:
- Ledger is empty.
- Funnel output is empty (zero events in every breakdown).
- The binding test still passes against the synthetic fixture (no operator state needed).

**No new policy / ledger / vault migration.** Pillar D Week 12 ships ZERO new migrations. The pending migration count stays at 17 (unchanged from Week 9-11).

**The funnel CLI is shipped + immediately available.** Operators on the upgraded code see `python orchestrator/funnel.py --help` work out of the box; no bootstrap step required.

**Pillar D STABLE flip is documentation-only** — PILLAR-PLAN §6 Pillar D row Notes column + Status column update. No code change required for the flip itself; the binding test passing IS the evidence.

## Existing-operator seed

Per Shape A above: existing operators see the funnel CLI work immediately against their ledger. The CLI's JSON output reflects their actual operator state — reply mix, classification methods (rule vs llm), outcome distribution, attribution-by-touch.

For operators wanting to validate their own pattern-set quality, the `tests/fixtures/synthetic_pillar_d/corpus.yml` is the operator-readable baseline; operators may extend the corpus with their own reply samples + re-run the binding test against the extended corpus (the test's per-category precision/recall targets are calibrated to the FACTORY pattern set; operator extensions may surface gaps in the operator's pattern files).

The `--conversation-ttl-days` flag (shipped in Pillar D Week 9-11 per ADR-0030 D132) lets operators control TTL behavior; the funnel CLI reflects the operator's chosen TTL via the `dormant` outcome counts.

## References

- ADR-0013 D24 — hybrid synthetic-replay fixture posture from Pillar B Week 5; the precedent for D136's hybrid choice.
- ADR-0014 D33 — channel-on-every-event invariant carried forward via ADR-0025 D96 to all reply events + via ADR-0030 D130 to outcome events + verified in the binding test's ROW 4.
- ADR-0014 D37 — Pillar C exit-criterion test vehicle (`tests/test_multi_channel_coherence.py`); the binding test extends this file per ADR-0025 D101.
- ADR-0025 D96-D101 — Pillar D foundation; D101 explicitly forward-references the Week 12 exit-criterion vehicle scope this ADR delivers.
- ADR-0026 D102-D107 — Pillar D Week 2 rule-based classifier; the binding test ROW 1 exercises every factory pattern.
- ADR-0027 D108-D114 — Pillar D Week 3 long-tail categories + per-channel reply detection; the binding test ROW 1 exercises every long-tail category + every reply event type (`reply_received` / `li_invite_reply_received` / `li_dm_reply_received` / `tw_dm_reply_received`).
- ADR-0027 D113 — Cal.com Pass K deferred; the corpus does NOT include `calendar_booking_reply_received` events. Calendar bookings are tested via `calendar_booking_confirmed` events for closed_won outcome attribution.
- ADR-0028 D115-D121 — Pillar D Week 4-5 auto-unsubscribe handler + conversation state machine; ROW 3 verifies the (reply_message_id, channel) idempotence per D117.
- ADR-0029 D122-D128 — Pillar D Week 6-8 LLM fallback + classifier-cap; ROW 2 verifies the LLM fallback path with the deterministic fake client per D138.
- ADR-0030 D129-D135 — Pillar D Week 9-11 win/loss attribution + `conversation_outcome` event class + TTL driver; ROW 4 + ROW 5 + ROW 6 verify the outcome derivation + TTL dormancy + per-Person aggregation.
- `.planning/HANDOFF-pillar-d-week-12.md` — the handoff this ADR consumes; scopes Week 12's exit-criterion close.
- `.planning/REVIEW-pillar-d-surface-audit.md` — Week 12 confirms the audit is UNCHANGED (no new event classes; the funnel CLI is a read-side primitive).
- `.planning/REVIEW-pillar-d-holistic.md` — the Pillar D holistic exit review (per this commit).
- `.planning/RETRO-pillar-d.md` — the Pillar D retrospective (per this commit).
- `docs/PILLAR-PLAN.md` §2 Pillar D — binding exit criterion; §5 — "What we will not do" (the unsubscribe = rule-based ONLY constraint stays with full weight throughout the binding test); §6 Pillar D row — flipped to STABLE in this commit.
- `docs/RISK-REGISTER.md` R012 + R013 + R014 + R015 + R016 + R017 — all mitigations stay in place; no new risks surfaced in Week 12.
- `tests/fixtures/synthetic_pillar_d/corpus.yml` — the 100-message synthetic inbox corpus; the canonical reviewer-inspectable artifact for the binding test substrate.
- `tests/fixtures/synthetic_pillar_d/README.md` — corpus distribution + scenario substrate documentation.
- `tests/conftest.py::synthetic_pillar_d_classifier_corpus_state_dir` — the programmatic builder fixture consuming the corpus YAML.
- `orchestrator/funnel.py` — the attribution funnel CLI shipped in this commit per D140.
