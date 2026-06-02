# ADR-0038: Pillar F foundation — voice-corpus schema + canonical location, embedding-retrieval contract, hallucination-detection contract, per-register-symmetry-with-shared-retrieval pattern, cross-pillar integration audit, exit-criterion vehicle scope, voice-fidelity-and-hallucination-detection invariants

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** F (Voice corpus + draft quality — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0008 shipped Pillar A (declarative policy engine). ADRs 0009-0013 shipped Pillar B (migration framework + synthetic-replay exit-criterion vehicle). ADRs 0014-0024 shipped Pillar C (multi-channel coherence — four channels, six reconcile passes, five per-channel policy migrations). ADRs 0025-0031 shipped Pillar D (reply + conversation handling — rule + LLM classifier, auto-unsubscribe, conversation state machine, win/loss attribution, funnel CLI). ADRs 0032-0037 shipped Pillar E (discovery quality + lineage — dedup + email-verification cache + tier auto-assignment + discovery_lineage stamping + three-skills-one-day binding exit-criterion). Pillar F — voice corpus + draft quality (`docs/PILLAR-PLAN.md` §2 Pillar F, Weeks 25-36) — extends the substrate at the OTHER end of the funnel from Pillar E: every draft that reaches `ready` carries a voice-fidelity score (the embedding distance between draft and corpus exemplars per the operator's curated email corpus) and a hallucination-detection verdict (every claim in the draft must trace to a citation in the research doc; un-cited claims block the draft from reaching `ready`). The substrate is in place; what Pillar F Week 1 needs is the **convention-setting decisions** the next eleven weeks build on.

Pillar E's Week 12 retrospective (`.planning/RETRO-pillar-e.md` §"What to do differently in Pillar F") named EIGHT carry-forward recommendations: (1) land the Pillar F voice-corpus coherence test in Week 1, not Week N (Pillar E Week 1 + Pillar D Week 1 + Pillar C Week 12 each surfaced the value of early-week stubbing); (2) audit pre-existing surfaces for symmetric assumptions whenever extending a Pillar A/B/C/D/E primitive (Pillar A through E each surfaced a pre-existing surface P2 at Week 1 — Pillar F's audit will likely surface ≥1 P2); (3) continue the per-week-handoff + per-week-review-with-follow-up-commit + per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact + holistic-exit-review discipline; (4) design Pillar F's hallucination-detection + voice-fidelity invariants at Week 1 (the legal-and-brand-liability-shaped CAN-SPAM precedent applies); (5) design the per-register-symmetry-with-shared-retrieval pattern at Week 1 (Pillar D's per-channel reply detection + Pillar E's per-skill integration both shipped per the shared-helper-with-thin-adapters convention); (6) bake the doc-sweep before commit (PILLAR-PLAN §6 + ADR README + SOURCES-OF-TRUTH + RISK-REGISTER are touched per commit); (7) anticipate the deterministic-clock requirement (Pillar D Week 12 + Pillar E Week 12 binding tests both required clock-control for reproducibility); (8) consider extracting `tests/_test_helpers/deterministic_clock.py` if Pillar F adds 2+ more deterministic-clock consumers.

The seven concerns this ADR resolves:

1. **Voice-corpus schema + canonical location must be pinned before per-register retrieval ships.** The current shape is `~/.outreach-factory/config.yml`'s `voice.corpus_dir` pointing to an operator-private directory carrying `embeddings.npy` + `index.json` (per `orchestrator/voice_retrieve.py:90-99`). The schema is inferred not pinned — `index.json` is a list of dicts with `date` / `subject` / `to` / `body` / `year` per the current heuristic's consumption (see `voice_retrieve.py:114-120`). D178 pins the canonical schema + the canonical location convention before per-register stamping refactors ship. **The `voice-corpus/` row in `docs/SOURCES-OF-TRUTH.md` already pre-declares the SoT** — *"Voice corpus | `voice-corpus/` directory (Pillar F locks the canonical path) | Embedding index (rebuildable) | Corpus → index | Currently scattered; Pillar F consolidates."* D178 formalizes.

2. **Embedding-retrieval is the load-bearing Week 1-2 substrate.** Per PILLAR-PLAN §2 Pillar F: *"Embedding-based retrieval replaces the current heuristic in `voice_retrieve.py`."* The current heuristic uses `BAAI/bge-small-en-v1.5` + cosine + recency bias (per `voice_retrieve.py:53-55`); the rewrite REPLACES this with a structured `retrieve_voice_exemplars(query, k, register, channel)` entry point that adds per-register filtering + per-channel filtering + per-corpus deterministic-clock-controlled retrieval. D179 pins the contract; Week 2 ships the primitive.

3. **Hallucination-detection is the load-bearing legal-and-brand-liability invariant.** Per PILLAR-PLAN §2 Pillar F binding text: *"every claim in the draft must trace to a citation in the research doc; un-cited claims block the draft from reaching `ready`."* The failure mode is asymmetric: a hallucinated claim in a cold-pitch email to a CEO ("you posted last week that X") that's NOT in the prospect's actual research dossier degrades the operator's brand + risks the relationship + may surface as a public callout. Per RETRO-pillar-d.md item-5 + ADR-0025 D97's CAN-SPAM precedent, asymmetric-failure-cost invariants get FIVE-layer defense-in-depth. D180 pins the contract; Week 1 ships Layer 1 (test corpus pin); subsequent weeks ship Layers 2-5.

4. **Per-register-symmetry-with-shared-retrieval pattern must be pinned at Week 1.** The `/draft-outreach` skill ships FIVE registers (cold-pitch / congrats / re-engagement / reply / public-comment per `skills/draft-outreach/SKILL.md:71+`). The shared retrieval primitive at Week 2 + per-register thin adapters in subsequent weeks mirrors Pillar D's per-channel reply detection (Passes H/I/J shipped three passes in ONE week via the shared `_run_channel_dm_reply_pass` helper) + Pillar E's per-skill integration (Week 9-11 shipped four skills in ONE commit via the shared `enroll_person` `lineage` kwarg). D181 pins the pattern.

5. **Cross-pillar integration audit — THE load-bearing anti-regression decision.** Per Pillar A/B/C/D/E Week 1 precedents (each pillar's Week 1 audit caught ≥1 pre-existing P2 — Pillar A surfaced policy-engine version concerns; Pillar B surfaced `ledger/0002`'s channel-field gap; Pillar C surfaced Pass A's channel-filter gap; Pillar D surfaced Pass B's channel-on-every-event gap; Pillar E surfaced `needs_identity_upgrade`'s source-attribution gap), every Pillar F week's per-week review MUST audit existing Pillar A/B/C/D/E surfaces for symmetric assumptions when Pillar F's commit silently expands the input space. D182 pins the audit + names the new event classes Pillar F adds (`voice_exemplar_retrieved` / `hallucination_detected` / `draft_quality_scored`) so the audit lands against concrete event-type names; `.planning/REVIEW-pillar-f-surface-audit.md` is the load-bearing artifact future Pillar F weeks extend.

6. **The Pillar F exit-criterion verification vehicle must exist in Week 1.** Per PILLAR-PLAN §2 Pillar F binding text: *"mean voice-fidelity score per register meets baseline; hallucination false-negative rate on a 200-draft eval set < 1%."* Without the vehicle landing in Week 1, the cross-cutting properties (per-register voice-fidelity score; per-register hallucination false-negative rate; per-register retrieval coverage; cross-primitive plumbing — voice-exemplar feeds the draft engine + the hallucination detector reads the citation set) would only surface end-of-pillar, repeating Pillar B Week 5 + Pillar C Week 12's pattern. D183 names the vehicle scope: `tests/test_multi_channel_coherence.py` is EXTENDED with `TestVoiceCorpusFidelity` + `TestHallucinationDetection` + `TestPillarFExitCriterion` test classes (Option A per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 single-file rationale inherited).

7. **Voice-fidelity-and-hallucination-detection invariants.** Per RETRO-pillar-d.md item-4 + ADR-0032 D148's precedent — load-bearing invariants get designed at Week 1. D184 names the two invariants: (a) **the voice-fidelity score is per-register operator-tunable** (Pillar F default thresholds calibrated against Yang's curated corpus; operators with different audiences tune per-register); (b) **the hallucination-detection invariant is FIVE-layer defense-in-depth** (Layer 1 ships Week 1 — test corpus pin; Layers 2-5 ship across subsequent weeks). The legal-and-brand-liability shape matches ADR-0025 D97's CAN-SPAM defense.

Risks this ADR mitigates by design: **R006 (Anthropic API churn)** continues mitigated by the embedding-model-choice operator-configurable per D179 (operators can switch from `BAAI/bge-small-en-v1.5` to any other sentence-transformer; the framework is provider-neutral). **R016 (LLM cost runaway)** continues mitigated by the retrieval primitive's LOCAL-ONLY contract (no LLM call inside `retrieve_voice_exemplars`; the rewrite happens in the agent's own LLM call per the existing `voice_retrieve.py` discipline).

Four new risks surface in this ADR's authoring + named in `docs/RISK-REGISTER.md`:

- **R023 (Hallucination-detection false-negative — un-cited claim slips past the gate)** — the Layer 1-5 defense bounds the false-negative rate; the 200-draft eval-set < 1% target per PILLAR-PLAN §2 Pillar F binding text is the structural bound. The asymmetric-failure-cost calculus: a single false-negative hallucination in a cold-pitch to a CEO that's publicly callable-out is high-cost; the operator's brand + the relationship is at stake. Mitigation by design: FIVE-layer defense per D180; Layer 1 test corpus pin Week 1; Layers 2-5 ship Weeks 6-12; the 200-draft eval set's `<1%` false-negative bound is the binding exit-criterion gate per Week 12.

- **R024 (Voice-corpus drift — operator's voice changes over time, corpus stays static, retrieval surfaces stale exemplars)** — the operator's voice evolves (new vocabulary; changed register conventions; updated company context per `~/.outreach-factory/config.yml` rewrites); the static corpus may surface exemplars from a year ago that no longer reflect the current voice. The current `voice_retrieve.py:113-117` mitigates partially via `RECENT_BIAS` (per-year recency multiplier); D179 extends with per-register fidelity-score tracking + operator-visible drift signals.

- **R025 (Embedding-cost runaway from corpus rebuild)** — operators with growing corpora (10K+ emails) re-building embeddings via `BAAI/bge-small-en-v1.5` (local CPU) consume ~1-5 minutes of CPU per rebuild. The risk surfaces when operators use a CLOUD embedding model (e.g., OpenAI's `text-embedding-3-small`) — per-rebuild cost compounds to ~$0.50-$2.00 for 10K emails at $0.00002/1K tokens. Mitigation by design: the framework defaults to LOCAL `BAAI/bge-small-en-v1.5` (zero per-rebuild cost); operators choosing cloud embeddings opt in deliberately + see the cost in Pillar G dashboards.

- **R026 (Operator-corpus split — multi-machine operator has divergent indices)** — operators running the framework on multiple machines (laptop + desktop + cloud daemon) each build local indices from synced corpus directories; if the corpus files are synced via Obsidian Sync / Dropbox / Syncthing, the per-machine `embeddings.npy` + `index.json` may diverge silently (different sentence-transformers version; different model weights; different sample order). Mitigation by design: D179 names the embedding-model + sentence-transformers version in the cache file's metadata; the retrieval primitive refuses-loud on metadata mismatch + auto-rebuilds.

## Decision

### D178. Voice-corpus schema + canonical location

Pillar F pins the voice-corpus location at TWO operator-facing paths + ONE per-sample schema:

**(a) Default-shipped templates** at `config-template/voice-corpus/` in the repo. Operators bootstrapping a new install copy the templates to their operator-private corpus directory. **Week 1 ships ZERO default templates** (the existing operators have curated their corpora over months; the templates are a Week 4+ concern for new-operator bring-up). The PATH is reserved at Week 1; the content lands in subsequent weeks.

**(b) Operator-private corpus** at `~/.outreach-factory/voice-corpus/` per the `~/.outreach-factory/config.yml`'s `voice.corpus_dir` field. Existing operators today point `voice.corpus_dir` at a scattered location (Yang's setup uses `/Users/yang/code/aiyara/voice/corpus/`); the operator-side migration is documented in §Existing-operator seed below. **Week 1 ships the location CONVENTION + the documented migration path; NO automatic move.** Operators apply the §Existing-operator seed step at their own cadence.

**(c) Per-sample schema** at `~/.outreach-factory/voice-corpus/index.json`. The shape:

```json
[
  {
    "id": "2025-04-15-dylan-tx-cold-pitch",
    "date": "2025-04-15T14:32:00Z",
    "to": ["dylan@example.com"],
    "subject": "wondering about your tau2-bench post",
    "body": "Hey Dylan,\n\nSaw your tau2-bench post last week...\n\n— Yang",
    "register": "cold-pitch",
    "channel": "email",
    "year": 2025,
    "tags": ["fintech-agents", "cold-pitch", "tier-S"],
    "is_substantive_reply": true,
    "voice_score_baseline": 0.78
  },
  ...
]
```

Required fields: `id` (auto-generated from date + slug; uniqueness pin); `date` (ISO 8601 UTC); `body` (the full email text); `register` (closed enum per the draft-outreach skill's five registers per §D181); `channel` (closed enum per ADR-0014 D33's `{email, linkedin-dm, linkedin-comment, twitter-dm}`); `year` (int, used by `RECENT_BIAS` per `voice_retrieve.py:113`).

Optional fields: `to` (list — may be redacted per operator preference for privacy); `subject` (string — null for `linkedin-comment` register; required for `cold-pitch` register's `email` channel default per the draft-outreach skill's register table); `tags` (list — operator-supplied free-form classification); `is_substantive_reply` (bool — operator-stamped marker for "this email got a real reply"; used by the per-register retrieval to bias toward proven-effective exemplars per the existing `voice_retrieve.py`'s 5-touch sampling discipline); `voice_score_baseline` (float — per-sample baseline-voice-fidelity score; populated by Pillar F Week 8+ when the fidelity-scoring primitive ships).

**Closed enum for `register`:** Frozen at five values in Week 1 — `{cold-pitch, congrats, re-engagement, reply, public-comment}` matching `/draft-outreach`'s register table. Future registers (operator-deliberate addition for a new conversational shape) extend the enum with a coordinated ADR amendment + a vault migration to retag historical samples.

**Closed enum for `channel`:** Frozen at four values per ADR-0014 D33 + Pillar C's four channels — `{email, linkedin-dm, linkedin-comment, twitter-dm}`. Future channels (per the existing ADR-0014 D34 extension trajectory) extend the enum with a coordinated ADR amendment.

**Why an `index.json` plus `embeddings.npy` pair (rejected: SQLite-backed corpus; rejected: per-sample-per-file markdown corpus; rejected: in-vault corpus).** Three reasonable storage shapes: (a) `index.json` + `embeddings.npy` pair (D178's choice — extension of the current heuristic's shape); (b) SQLite-backed corpus at `~/.outreach-factory/voice-corpus/corpus.db`; (c) per-sample-per-file markdown at `~/.outreach-factory/voice-corpus/samples/*.md` with embeddings rebuilt per-call. Pillar F Week 1 picks (a). The rationale:

* **Continuity with the existing heuristic.** The current `voice_retrieve.py:105-120` consumes `embeddings.npy` + `index.json`; D178 extends the schema (adding `register` / `channel` / `tags` / etc.) without changing the storage shape. Operators with existing corpora upgrade incrementally per §Existing-operator seed.
* **SQLite (option b) creates a fourth SoT in the framework's storage stack.** The framework today has ledger (JSONL) + vault (markdown) + policy YAML + suppression YAML; adding SQLite for the voice corpus is an extra dependency + an extra backup/sync/restore concern. The `index.json` + `embeddings.npy` pair is filesystem-native + sync-friendly (operators' Obsidian Sync / Dropbox / Syncthing handle the directory naturally).
* **Per-sample-per-file markdown (option c) requires per-call full corpus walk.** The retrieval primitive's per-call cost balloons from O(K) (existing `np.argsort(-sims)[:k]`) to O(N) markdown parsing + per-sample embed; for 10K-sample corpora this is ~5-10 seconds per draft. The `index.json` + `embeddings.npy` pair amortizes embedding cost at corpus-build time, not per-draft.

**Operator-tunable location per `~/.outreach-factory/config.yml`.** The `voice.corpus_dir` field already exists; D178 names `~/.outreach-factory/voice-corpus/` as the CONVENTION (not a hard requirement). Operators who insist on a different location keep their existing `voice.corpus_dir` value; the framework's primitive reads the config-driven path.

**Pin:** `tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity::test_voice_corpus_canonical_schema_validates` asserts the per-sample schema's required-field shape. **Stub lands in this Week 1 commit + un-skips when the canonical schema validator ships in Week 2.**

### D179. Embedding-retrieval contract

Pillar F ships `orchestrator/voice_corpus.py` (NEW module Week 2 ships) carrying the embedding-retrieval primitive. The contract:

```python
from orchestrator.voice_corpus import retrieve_voice_exemplars, VoiceExemplar  # Pillar F Week 2 ships

result: list[VoiceExemplar] = retrieve_voice_exemplars(
    query="Hey Dylan, saw your tau2-bench post last week...",
    k=5,
    register="cold-pitch",         # optional filter — defaults to no filter
    channel="email",               # optional filter — defaults to no filter
    is_substantive_reply=True,     # optional filter — defaults to no filter
    now=None,                      # optional deterministic-clock anchor (defaults to wall-clock)
)
# Each VoiceExemplar carries: id, date, body, subject, register, channel,
# score (cosine similarity * recency multiplier), tags, is_substantive_reply.
```

**The contract is LOAD-BEARING per the per-register-symmetry-with-shared-retrieval pattern per D181** — the per-register draft assemblers (Week 4+ per-register adapters) call into THIS primitive with `register=<value>` set; the shared retrieval handles per-register filtering uniformly.

**Embedding-cache substrate.** The cache lives at `~/.outreach-factory/voice-corpus/embeddings.npy` (numpy uncompressed) + `~/.outreach-factory/voice-corpus/index.json` (per D178). The retrieval primitive reads BOTH files at first call + memoizes the loaded model + the loaded embeddings for the process lifetime (existing `voice_retrieve.py:106-109` precedent). Per-call cost: O(N) cosine + O(N log N) argsort + O(K) result construction.

**Why a separate cache file pair (NOT the ledger-as-substrate per Pillar E's cache precedent per ADR-0034 D156).** Two reasonable substrate shapes: (a) separate file pair `embeddings.npy` + `index.json` per D179 (Pillar F Week 1's choice); (b) ledger-as-substrate per Pillar E's `email_verification_cache_hit` precedent. Pillar F Week 1 picks (a). The rationale:

* **Embedding-cache payload size is ~KB per sample (vs ~bytes-per-response for Reoon cache).** A `BAAI/bge-small-en-v1.5` embedding is 384 floats × 4 bytes ≈ 1.5KB per sample; the per-sample index metadata adds ~500 bytes; the total per-sample cost is ~2KB. A 10K-sample corpus produces ~20MB. Storing 20MB IN the ledger event stream (alongside event types whose typical payload is ~200 bytes) inflates ledger size by ~100x + slows down EVERY ledger walk for EVERY consumer (per-call O(N) walks per Pillar A's rule engine + Pillar B's reconcile + Pillar D's funnel + Pillar E's primitives). The ledger-as-substrate worked for ~bytes-per-response cost events (Reoon responses); it doesn't scale to ~KB-per-embedding samples.
* **Embedding payload is OPAQUE BINARY (numpy serialization).** The ledger's JSONL shape is operator-readable text; a Base64-encoded numpy blob inside a JSONL event is opaque + breaks the per-event grep + jq workflow operators rely on per `python -m orchestrator.ledger grep --type X | jq ...`.
* **Reproducibility from corpus rebuild.** The embedding cache IS rebuildable from the corpus directory (the operator's email source + the index.json schema). The cache is a DERIVED VIEW; the corpus directory IS the source of truth. Storing the derived view in the ledger would create a fourth SoT split (ledger + corpus dir + cache + index) — strictly worse than D179's two-file pair.
* **Existing-operator continuity.** Yang's current corpus already lives in `embeddings.npy` + `index.json` per `voice_retrieve.py:90-99`; D179 EXTENDS the schema in-place without forcing operators to re-ingest. Migration to a ledger-substrate would force every operator to rebuild from scratch — high operator-side cost + zero behavior gain.

**Re-evaluate at Pillar H scale analysis.** The two-file pair is filesystem-native; if Pillar H (real-time + scale) surfaces per-machine corpus divergence (per R026) as a sharper concern, the substrate may move to a SQLite-backed cache. The decision is bounded to the current corpus scale (~5K samples at v1).

**Deterministic-clock contract.** The retrieval primitive accepts an optional `now: datetime | None = None` kwarg per ADR-0031 D140 + ADR-0034 D156 + ADR-0035 D162 deterministic-clock precedent. When `now` is provided, the `RECENT_BIAS` per-year multiplier computation uses `now.year` instead of `datetime.now(UTC).year`; per-test reproducibility is preserved. Pillar F Week 1 names the kwarg — the implementation lands at Week 2.

**Model + sentence-transformers version metadata.** The cache file's first line (a sidecar `metadata.json` in the same dir) records: `embed_model` (the sentence-transformers model name); `embed_version` (the sentence-transformers package version); `built_at` (ISO 8601 UTC); `corpus_count` (the sample count); `schema_version` (the D178 schema version — `1` at Week 1). The retrieval primitive verifies metadata-on-load matches the runtime + refuses-loud on mismatch + auto-rebuilds when allowed (operator-controlled via `--rebuild-on-mismatch` flag). R026 mitigation.

**Pin:** `tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity::test_retrieval_per_register_filtering` asserts the per-register filter contract. **Stub lands in this Week 1 commit + un-skips when the primitive ships in Week 2.**

### D180. Hallucination-detection contract — FIVE-layer defense-in-depth

Per PILLAR-PLAN §2 Pillar F binding text: *"every claim in the draft must trace to a citation in the research doc; un-cited claims block the draft from reaching `ready`."* The legal-and-brand-liability asymmetric-failure-cost calculus matches ADR-0025 D97's CAN-SPAM defense — the cost of a false-negative (un-cited claim ships) is high (operator brand damage; relationship destruction; public callout risk); the cost of a false-positive (the gate blocks a true claim) is low (operator stamps a one-time override). The DEFENSE per D180 is FIVE layers:

| Layer | Surface | Ship week | Defense |
|---|---|---|---|
| **1** | Test corpus pin | Week 1 (this commit) | `tests/test_multi_channel_coherence.py::TestHallucinationDetection::test_draft_with_uncited_claim_fails_gate` — adversarial draft (a synthetic cold-pitch citing "you posted last week that X" where X is NOT in the research dossier) MUST fail the hallucination-detection gate. Stub at Week 1; un-skip at Week 6 when Layer 3 ships (the gate's first behavior). |
| **2** | Source-level construction refusal | Week 6+ | `DraftQualityResult` dataclass with construction-time invariants — refuses to construct a `ready`-state result when `uncited_claims` is non-empty. Mirrors Pillar E's `DiscoveryLineage.__post_init__` construction-time validation per ADR-0036 D167. |
| **3** | Parse-level guard | Week 6+ | The draft engine's output parser (`orchestrator/draft_quality.py::parse_draft_for_claims`) extracts every claim from the draft (every "you" + "your" sentence; every dated reference; every named-entity reference) + cross-references against the research dossier's citation set. Un-cited claims surface as `uncited_claims` on the result. |
| **4** | Post-engine guard | Week 10+ | The `draft_ready` event emission walks the `uncited_claims` field + refuses to emit when non-empty. Mirrors the Pillar D Week 4-5 `suppression_added` event's YAML-first-then-ledger discipline per ADR-0028 D116 — the event is the LAST WRITE in the per-draft pipeline; refusing emit prevents the downstream consumer from acting on a stale-state draft. |
| **5** | Reconcile heal-pass refusal | Week 12 | The `pipeline_stage: ready` heal in `reconcile.py` Pass C refuses to advance a Person to `ready` when the linked draft's `draft_quality_scored` event carries `uncited_claims` non-empty. The final structural backstop — a draft that bypassed Layers 1-4 still cannot advance the pipeline. |

**Why FIVE layers (rejected: ONE layer at the test-corpus pin only — Pillar E's privacy invariant precedent; rejected: THREE layers — source + parse + post-engine — Pillar D's suppression-write precedent).** Three reasonable defense postures: (a) ONE layer (Pillar E privacy invariant per ADR-0032 D148); (b) THREE layers; (c) FIVE layers (Pillar D CAN-SPAM legal-liability per ADR-0025 D97). Pillar F Week 1 picks (c). The rationale:

* **Asymmetric-failure-cost matches CAN-SPAM, not source_list privacy.** The hallucination-detection failure mode has EXTERNAL consequences (brand damage; public callout risk; relationship destruction) whereas source_list privacy is operator-DISCRETIONARY (operators may choose to surface). The CAN-SPAM precedent at FIVE layers fits.
* **Each layer catches a different bug class.** Layer 1 catches contributor regression (a future Pillar F author who weakens the parser would fail the test); Layer 2 catches in-process construction bugs (the dataclass can't be constructed in a bad state); Layer 3 catches parser bugs (the gate's first behavioral check); Layer 4 catches event-emission bugs (a draft that somehow has `uncited_claims` empty per the parse but non-empty per a later in-process mutation is caught at emit time); Layer 5 catches state-machine bugs (a draft that bypassed Layers 1-4 still cannot advance to `ready`).
* **Per-week ship trajectory amortizes the engineering cost.** Layer 1 at Week 1 is ~30 LOC of test fixture + the SKIPPED stub. Layer 2 at Week 6 is ~50 LOC of dataclass + invariants. Layer 3 at Week 6 is ~200-400 LOC of parser. Layer 4 at Week 10 is ~30 LOC of event-emit guard. Layer 5 at Week 12 is ~30 LOC of reconcile-pass extension. Total ~~700 LOC across 5 weeks ≈ Pillar D Week 12's classifier benchmark (~600 LOC) — comparable scope at comparable cost.

**Per-claim trace shape.** Each claim is a `(claim_type, claim_text, citation_anchor | None)` triple. `claim_type` ∈ `{date_reference, named_entity, you_phrase, quoted_text, dated_event}`. `citation_anchor` is the research-dossier line number + the source-URL string that supports the claim; None means uncited. The hallucination-detection primitive at Week 6 ships the per-claim parser; the per-claim trace ships as the `uncited_claims` field on the `DraftQualityResult`.

**Pin (Week 1):** `tests/test_multi_channel_coherence.py::TestHallucinationDetection::test_draft_with_uncited_claim_fails_gate` asserts the binding behavior. **Stub lands in this Week 1 commit + un-skips when Layer 3 ships in Week 6+.** The Week 1 stub names the binding text + the per-week un-skip trajectory.

### D181. Per-register-symmetry-with-shared-retrieval pattern

Pillar F ships the SHARED retrieval primitive at Week 2 (per D179); per-register thin adapters land in subsequent weeks (Weeks 4-8 per the per-register-per-week pattern from Pillar E Week 9-11's single-commit four-skill stamping). The five registers per `/draft-outreach` SKILL.md's register table:

| Register | Channel default | Word ceiling | Voice rule |
|---|---|---|---|
| `cold-pitch` | email | 75-200 | vulnerability-signal-required; vertical-specific Q1; no marketing hedges |
| `congrats` | LinkedIn DM | 35-50 | exclamation-marks-required; short; no embedded pitch |
| `re-engagement` | email | 50-75 | honest-prior-reference; no fake-forgetting |
| `reply` | inbound channel | match inbound | mirror inbound register |
| `public-comment` | LinkedIn comment | 15-25 | short; no asks; not self-promoting |

**Per-register adapter shape:**

```python
# Pillar F Week 4+ — orchestrator/voice_corpus.py
from orchestrator.voice_corpus import retrieve_voice_exemplars

def retrieve_cold_pitch_exemplars(query: str, k: int = 5) -> list[VoiceExemplar]:
    """Cold-pitch register adapter — biases toward substantive-reply exemplars."""
    return retrieve_voice_exemplars(
        query=query, k=k,
        register="cold-pitch", channel="email",
        is_substantive_reply=True,  # cold-pitch BIASES TOWARD proven-effective exemplars
    )

def retrieve_congrats_exemplars(query: str, k: int = 5) -> list[VoiceExemplar]:
    """Congrats register adapter — biases toward short LinkedIn DMs."""
    return retrieve_voice_exemplars(
        query=query, k=k,
        register="congrats", channel="linkedin-dm",
        # No is_substantive_reply filter (congrats often don't get replies)
    )

# Three more thin adapters for re-engagement / reply / public-comment.
```

**Why thin per-register adapters over a single retrieval primitive (rejected: per-register modules; rejected: per-register classes inheriting a shared base; rejected: one giant adapter).** Three reasonable shapes: (a) thin per-register free functions sharing one primitive (D181's choice); (b) per-register modules at `orchestrator/voice_corpus/cold_pitch.py` / `congrats.py` / etc.; (c) per-register classes inheriting `BaseVoiceRetriever`. Pillar F Week 1 picks (a). The rationale:

* **The per-register differences are small.** Looking at the per-register table above, the differences are: filter values (`register=` + `channel=` + `is_substantive_reply=`) + scoring biases (some registers weight recency higher; some bias toward proven exemplars). Per-register modules (option b) inflate the surface area for ~10 LOC per register — over-organization for the actual variation.
* **Per-register classes (option c) impose inheritance hierarchy that obscures the simple shape.** The shared retrieval IS a single function call; wrapping it in a class hierarchy with `BaseVoiceRetriever.retrieve` + per-register overrides creates indirection without proportional reuse benefit.
* **Thin per-register free functions match the existing draft-outreach SKILL.md's per-register section structure.** The SKILL.md ships ONE per-register table; the implementation mirrors with ONE per-register section in `voice_corpus.py`. The structural unity is operator-readable + future-Pillar-F-contributor-readable.
* **One giant adapter (rejected — fourth option emerging from the audit) collapses the per-register semantics into a parameter explosion.** A `retrieve_for_register(register: str, query: str, k: int)` with hardcoded per-register filter dispatching inside is harder to extend (a new register requires editing the switch) + harder to test (one function with five per-register test cases vs five per-register functions with isolated tests).

**Pin:** `tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity::test_per_register_adapter_filters_to_correct_register` asserts the per-register filter contract for cold-pitch (the largest-coverage register). **Stub lands in this Week 1 commit + un-skips when the per-register adapters ship in Week 4-8.**

### D182. Cross-pillar integration audit — load-bearing surface map

`.planning/REVIEW-pillar-f-surface-audit.md` (this commit) is the surface map. The audit walks every existing Pillar A / B / C / D / E surface that touches Person frontmatter / draft engine / voice retrieval / `send_intent` payload; verifies each is either closed-set protected or literal-string filtered against Pillar F's new event classes + the new voice-corpus-related surfaces. The audit's verdict: **see `.planning/REVIEW-pillar-f-surface-audit.md` for the per-surface walk + the verdict for Week 1**.

**The audit IS the contract.** Future Pillar F weeks' per-week reviewers consult the audit as the surface map; new code added in Week N+ that touches a ledger index or a query method extends the audit with a new row. The discipline mirrors Pillar A/B/C/D/E's per-week-review pattern + carries forward the RETRO-pillar-e.md item-2 "Audit pre-existing surfaces for symmetric assumptions" recommendation.

**New event classes Pillar F adds** (named here so the audit lands against concrete event-type names):

| Event class | Pillar F week that emits | Purpose |
|---|---|---|
| `voice_exemplar_retrieved` | Week 2 | Per-draft retrieval result — operator-visible signal that the voice-corpus primitive surfaced K exemplars for a given query. Channel: derived from the query's intended channel (email / linkedin-dm / etc.); register: the draft's register. |
| `hallucination_detected` | Week 6 | Per-draft hallucination-detection finding — operator-visible signal that the gate caught an un-cited claim. Carries the un-cited-claim trace per D180. |
| `draft_quality_scored` | Week 8 | Per-draft fidelity score + hallucination verdict — operator-visible scoring event. Channel: the draft's channel; register: the draft's register. |

**Pin:** the audit document is referenced from this ADR + every subsequent Pillar F ADR's §References. Pillar F Week N's per-week reviewer's checklist (per HANDOFF-pillar-f-week-N.md §"Validation gate") includes "the surface audit was extended (or confirmed unchanged) by this week's commit."

**Categories the audit pins for future Pillar F week reviewers** (extracted from `.planning/REVIEW-pillar-f-surface-audit.md` §"Categories the Pillar F Week N per-week reviewer must keep auditing"):

1. Does the week's commit broaden `_idx_person` (any event with `person_id`) in a way pre-Week-N consumers don't expect?
2. Does the week's commit add a new `*_confirmed`-suffixed event (would silently activate `CrossChannelTouchRule`)?
3. Does the week's commit add to `_STAGE_BY_EVENT_TYPE` (extends `derived_stage`)?
4. Does the week's commit add a new per-prospect cache-index pattern analogous to `_idx_gmail_msg` or `_idx_email_verification`?
5. Does the week's commit modify the `/draft-outreach` SKILL.md's Phase 4 (voice retrieval) or Phase 5 (humanizer-check) surfaces?
6. Does the week's commit extend the `voice-corpus/index.json` schema in a way that breaks pre-Pillar-F operator corpora?
7. Does the week's commit add a new `cost_incurred` source name (e.g., `cost_incurred.source=voice_embedding`)? IF YES, the per-source pricing-table in `orchestrator/policy/budget.py::COST_RATES_USD` MUST be updated per ADR-0006's discipline.
8. Does the week's commit surface a `hallucination_detected` or `voice_fidelity_score` in any operator-facing dashboard, CLI, or aggregation surface? IF YES, the per-event privacy invariant (research-dossier content + draft body content) MUST be reviewed (the dossier may contain operator-confidential research; the draft body may contain personally-identifying recipient context).

### D183. Pillar F exit-criterion vehicle scope

`tests/test_multi_channel_coherence.py` is the Pillar F exit-criterion verification vehicle (extended from the Pillar C + D + E vehicles per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147). The file gains THREE new test classes in this Week 1 commit:

* **`TestVoiceCorpusFidelity`** — voice-corpus schema coherence + per-register retrieval contract (per D178 + D179 + D181; per-register filter pins; canonical schema validator pins; embedding-cache metadata pins; pre-Pillar-F operator backfill compatibility). All test rows skip in Week 1 with `Pillar F Week N delivers` messages.

* **`TestHallucinationDetection`** — hallucination-detection contract (per D180; the FIVE-layer defense pins; Layer 1 test corpus pin un-skipped Week 1 via the ADVERSARIAL DRAFT IS REJECTED pin against the existing draft engine — the test passes against a synthetic adversarial draft today because there's no gate; the test stub asserts the gate's EVENTUAL behavior). Layer 1 ships as the stub; Layers 2-5 un-skip Weeks 6-12.

* **`TestPillarFExitCriterion`** — the binding exit-criterion test. One method: `test_voice_fidelity_per_register_meets_baseline_and_hallucination_false_negative_rate_under_one_percent` per PILLAR-PLAN §2 Pillar F's binding text. Skipped in Week 1; un-skips at the final Pillar F week (Week 12 of the Pillar F body — Week 36 of the program).

**The Option-A choice (extend the existing file) over Option B (new file).** Pillar C's exit-criterion vehicle (ADR-0014 D37) explicitly chose the single-file shape; Pillar D inherited per ADR-0025 D101; Pillar E inherited per ADR-0032 D147; Pillar F inherits the same rationale:

* The vehicle's load-bearing property is cross-pillar coherence visible from Week 1 in ONE place per-week reviewers consult.
* Splitting Pillar F into a separate `tests/test_pillar_f_voice_coherence.py` would create the "look in two places" mental model ADR-0014 D37 §Decision rejected.
* File growth (the test file is ~6833 lines post-Pillar-E-Week-12) is a real concern; Pillar F Week 1's extension adds ~200-350 lines of stubs. If the file crosses ~7500 lines the split argument resurfaces — TBD per the per-week reviewer's call in a future Pillar F week.

### D184. Voice-fidelity-and-hallucination-detection invariants

Per RETRO-pillar-e.md item-4 (continuing Pillar D Week 1's CAN-SPAM precedent per ADR-0025 D97) — Pillar F ships TWO load-bearing invariants designed at Week 1:

**(a) Voice-fidelity score is per-register operator-tunable.** Pillar F Week 1 names the convention:

* The fidelity score is a per-draft float in `[0.0, 1.0]` — the cosine similarity between the draft embedding and the top-K voice-corpus exemplar embeddings (weighted average).
* Per-register baseline thresholds live at `~/.outreach-factory/voice_thresholds.yml` with a default-shipped template at `config-template/voice_thresholds.example.yml` (Week 4+ ships; precedent: `tier_weights.example.yml` per ADR-0035 D163).
* Default per-register thresholds at Week 4 ship time (calibrated against Yang's curated corpus): cold-pitch ≥0.70; congrats ≥0.65; re-engagement ≥0.72; reply ≥0.70; public-comment ≥0.60.
* Operators tune per their corpus; the framework ships sensible defaults. Asymmetric-failure-cost calculus: a false-positive (the gate blocks a true-voice draft) costs operator one re-draft; a false-negative (the gate accepts an AI-flavored draft) costs operator brand fidelity. The per-register threshold biases toward false-positive at the framework default; operators with deep curated corpora tune upward.

**(b) Hallucination-detection invariant is FIVE-layer defense-in-depth per D180.** Already pinned in D180; here the invariant gets the explicit naming as the load-bearing legal-and-brand-liability gate analogous to CAN-SPAM. The invariant's status across the Pillar F weeks:

* **Layer 1 (this Week 1 commit):** test corpus pin per D180 layer 1 — the adversarial-draft-fails-gate stub.
* **Layer 2 (Week 6):** `DraftQualityResult` construction-time invariant.
* **Layer 3 (Week 6):** parse-level guard.
* **Layer 4 (Week 10):** post-engine guard on event emission.
* **Layer 5 (Week 12):** reconcile heal-pass refusal.

The FIVE-layer defense is the structural commitment of Pillar F to the brand-and-legal-liability surface. Future contributors who weaken any layer MUST amend D180 + name the new failure surface.

**Why ONLY the voice-fidelity-tunable invariant + the hallucination-detection FIVE-layer invariant at Week 1 (rejected: ship the voice-fidelity threshold default values; rejected: defer both invariants to later weeks; rejected: ship only the hallucination-detection invariant).** Three reasonable invariant postures: (a) ship both invariants at Week 1 (the NAMING — what the thresholds + the defense layers ARE, not the values yet); (b) ship the voice-fidelity threshold default values at Week 1 (premature — the thresholds depend on Yang's curated corpus's fidelity-score distribution which the Week 6+ scoring primitive surfaces); (c) ship only the hallucination-detection invariant at Week 1 (incomplete — the voice-fidelity invariant is symmetric load-bearing per the exit-criterion text). Pillar F Week 1 picks (a). The rationale:

* The invariants are CONVENTIONS that Pillar F's Week 2-12 implementations consume; naming them at Week 1 lands the convention before the implementations diverge.
* The threshold values depend on per-corpus measurement; the values land in Week 4 (when the threshold loader ships) + are operator-tunable thereafter.
* The hallucination-detection FIVE-layer defense is the structural commitment; per-layer details get shipped per-week per the Layer table above.

## Alternatives considered

### D178-Alt1: Single-file YAML corpus at `~/.outreach-factory/voice-corpus.yml`

A single YAML file carrying the per-sample list as a top-level array. **Rejected** because:

* Embedding storage in YAML is opaque text representation (base64-encoded floats) — inflates file size + breaks the deterministic numpy load path.
* Per-sample edits require parsing the entire YAML on every save — slow for 10K-sample corpora.
* Loses the existing `embeddings.npy` + `index.json` shape continuity; forces every operator to re-ingest.

### D178-Alt2: SQLite-backed corpus at `~/.outreach-factory/voice-corpus.db`

A SQLite database carrying per-sample rows + per-sample embedding BLOBs. **Rejected** because:

* Adds SQLite as a fourth framework dependency (alongside JSONL ledger + markdown vault + YAML policy/suppression). The dependency surface grows for one feature.
* SQLite-backed corpora are harder to backup / sync / restore via standard filesystem tooling (Obsidian Sync / Dropbox / Syncthing handle directories better than database files).
* The query patterns are simple (per-call cosine + argsort + filter); SQLite's query engine adds no value over numpy's vectorized operations.
* Pillar G observability dashboards expect filesystem-native surfaces; SQLite would create an additional adapter layer.

### D178-Alt3: Per-sample-per-file markdown at `~/.outreach-factory/voice-corpus/samples/*.md`

Per-sample markdown files with YAML frontmatter carrying the schema fields. **Rejected** because:

* Per-call full corpus walk for 10K samples ≈ 5-10 seconds; the retrieval primitive's per-call cost balloons.
* Embedding cost moves from build-time (one-shot CPU cost) to per-call (every draft re-embeds the corpus); for an operator drafting 10 emails/day this is 10x the CPU work.
* No clear win over the `embeddings.npy` + `index.json` pair — the markdown shape's only advantage is "operator-readable per-sample" which the `index.json` array also provides (operators inspect via `cat index.json | jq '.[] | select(.id == "X")'`).

### D179-Alt1: Ledger-as-substrate per Pillar E's `email_verification_cache_hit` precedent

Cache the embeddings IN the ledger event stream (each sample's embedding is the payload of a `voice_corpus_sample_indexed` event). **Rejected** because:

* Per-sample embedding payload is ~1.5KB (vs Pillar E's Reoon response ~200 bytes); 10K samples inflate the ledger by ~15MB.
* EVERY ledger walk by EVERY consumer (Pillar A's rule engine, Pillar B's reconcile, Pillar D's funnel, Pillar E's primitives) becomes slower; the per-call O(N) walk for the dedup primitive's index rebuild already noted in RETRO-pillar-e.md as a deferred Pillar H concern would be exacerbated.
* Base64-encoded numpy blobs inside JSONL break the per-event grep + jq operator workflow.
* The cache is DERIVED from the corpus directory; storing in the ledger creates a fourth SoT split.

### D179-Alt2: SQLite-backed embedding cache at `~/.outreach-factory/cache/voice_embeddings.db`

A SQLite database carrying per-sample rows + embedding BLOBs (rejected for the same reasons as D178-Alt2 — adds SQLite dependency + harder to sync/backup + no query-pattern advantage for the simple cosine-argsort-filter shape).

### D179-Alt3: Keep the current heuristic per `voice_retrieve.py` unchanged

Defer the embedding-retrieval primitive's redesign; Pillar F focuses only on hallucination detection + voice-fidelity scoring. **Rejected** because:

* PILLAR-PLAN §2 Pillar F explicitly names "Embedding-based retrieval REPLACES the current heuristic in `voice_retrieve.py`." Deferring contradicts the binding text.
* The current heuristic lacks per-register + per-channel filtering — the per-register-symmetry pattern per D181 has no foundation without the new primitive.
* The current heuristic lacks the deterministic-clock contract; Pillar F's binding exit-criterion test (Week 12) cannot be reproducible without the clock-control.

### D180-Alt1: ONE-layer defense (test corpus pin only) per Pillar E privacy invariant precedent

Ship only Layer 1 at Week 1 + treat Layers 2-5 as deferred. **Rejected** because:

* The hallucination-detection failure mode is asymmetric with EXTERNAL consequences (brand damage; public callout risk; relationship destruction) — matches Pillar D's CAN-SPAM legal-liability shape, NOT Pillar E's source_list operator-discretionary shape.
* A single-layer defense is bypassable by any contributor weakening the parser (the parse-level guard is the load-bearing behavior); ONE layer is insufficient for the asymmetric-failure-cost calculus.

### D180-Alt2: THREE-layer defense (source + parse + post-engine) per Pillar D's suppression-write precedent

Ship Layers 1 + 2 + 3 + 4 at Weeks 1 + 6 + 6 + 10; skip Layer 5 (the reconcile heal-pass refusal). **Rejected** because:

* The reconcile heal-pass is the FINAL structural backstop — a draft that bypassed Layers 1-4 (in-process or via a corrupted ledger event) still cannot advance the pipeline. Skipping Layer 5 leaves a one-bug-away failure mode where a single in-process bypass propagates downstream.
* The Pillar D CAN-SPAM defense includes the suppression-rule refuse-on-list mechanic (Layer 5 equivalent — the reconcile pass refuses to advance a Person on the suppression list); D180 mirrors with the reconcile heal-pass refusal.

### D180-Alt3: TEN-layer defense (per-claim-type per-layer dispatch)

Ship one defense layer per claim type per layer (e.g., date_reference at parse + named_entity at construction + you_phrase at post-engine + quoted_text at reconcile + dated_event at heal). **Rejected** because:

* Over-engineering for the v1 corpus. The five claim types share the same `(claim_text, citation_anchor)` shape; per-claim-type layering inflates surface area without proportional defense gain.
* The per-claim-type catch IS already in Layer 3 (parse-level guard) — every claim type lands in the same `uncited_claims` field; the per-layer dispatch is redundant.

### D181-Alt1: Per-register modules at `orchestrator/voice_corpus/cold_pitch.py` / `congrats.py` / etc.

A subpackage with per-register modules. **Rejected** because:

* Over-organization for ~10 LOC per register adapter. The per-register differences are small (filter values + scoring biases); module-level isolation is a heavyweight encapsulation.
* Creates an import-path surface that future Pillar F contributors must navigate (`from orchestrator.voice_corpus.cold_pitch import retrieve_cold_pitch_exemplars`) vs the simpler free-function shape (`from orchestrator.voice_corpus import retrieve_cold_pitch_exemplars`).

### D181-Alt2: Per-register classes inheriting `BaseVoiceRetriever`

A class hierarchy with `BaseVoiceRetriever.retrieve` + per-register overrides. **Rejected** because:

* Imposes inheritance hierarchy that obscures the simple shape. The shared retrieval IS a single function call; wrapping in a class hierarchy creates indirection without proportional reuse benefit.
* Testing surface inflates (per-register class instantiation + per-register subclass behavior verification) vs the simpler per-register-function shape (per-register function call + assertion on result).

### D181-Alt3: One giant adapter `retrieve_for_register(register: str, ...)` with internal dispatch

A single function with hardcoded per-register filter dispatching inside. **Rejected** because:

* A new register requires editing the internal switch (vs adding a new free function); the per-register surface is closed.
* Testing inflates (one function with five per-register test cases inside; isolating per-register failures requires conditional breakpoints) vs per-register-function isolation.

### D182-Alt1: Skip the audit since Pillar F doesn't extend the ledger

The Week 1 commit ships only test stubs + ADR + handoff; no new event classes. **Rejected** because:

* The PILLAR-PLAN §2 Pillar F NAMES three new event classes (per D182's table); the audit must walk every existing consumer for whether the new classes silently broaden the input space.
* The Pillar A/B/C/D/E precedent at Week 1 is the audit lands AT WEEK 1 against the EVENTUAL event-class set — every prior pillar's Week 1 audit caught ≥1 pre-existing P2 (the "Pillar X Week 1 catches a pre-existing surface bug" pattern is the load-bearing prediction from RETRO-pillar-e.md).
* Without the audit at Week 1, the Week 2-12 commits' P1/P2 catch rate drops (the audit's load-bearing role is the per-week reviewer's checklist row).

### D182-Alt2: Defer the audit to Week 2 (when the first primitive ships)

The Week 1 commit ships only test stubs; the audit lands at Week 2 alongside the embedding-retrieval primitive. **Rejected** because:

* The Pillar A/B/C/D/E precedent at Week 1 is unambiguous: the audit lands AT WEEK 1.
* Deferring creates a structural gap (the per-week-reviewer's Week 1 checklist row "the surface audit was extended" has nothing to check); the discipline degrades.

### D182-Alt3: Defer the audit to Pillar I OSS bring-up

Treat the audit as a Pillar I deliverable. **Rejected** because:

* The audit's role is per-pillar load-bearing anti-regression; deferring to Pillar I (six pillars later) creates a 6-pillar-wide gap where Pillar F's Week 1-12 commits are not audit-protected.
* The Pillar A/B/C/D/E precedent is unambiguous.

### D183-Alt1: Separate `tests/test_pillar_f_voice_coherence.py` file

A new file dedicated to Pillar F's exit-criterion vehicle. **Rejected** because:

* Fragments the coherence vehicle; the `tests/test_multi_channel_coherence.py` file's load-bearing property is single-file cross-pillar coherence per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147.
* Splits the per-Pillar-F test classes from the per-Pillar-C/D/E test classes that share the same coherence-vehicle imports + fixtures.
* Creates the "look in two places" mental model rejected at every Pillar A/B/C/D/E foundational ADR.

### D183-Alt2: Defer Pillar F test class additions to Week 2 (when the primitive ships)

The Week 1 commit lands the ADR + the audit; the test classes land at Week 2. **Rejected** because:

* The Pillar A/B/C/D/E precedent at Week 1 is the test classes land AT WEEK 1 as stubs; the per-week deliverables un-skip rows incrementally per the Pillar C → Pillar D → Pillar E carry-forward item 1.
* Deferring creates a structural gap (the per-week-reviewer's Week 1 checklist row "the test stubs name the per-week un-skip trajectory" has nothing to check).

### D183-Alt3: One Pillar F class instead of three

Combine all three test classes into one `TestPillarF` class. **Rejected** because:

* The three concerns (voice-corpus + hallucination-detection + exit-criterion) are structurally distinct — voice-corpus is the substrate primitive; hallucination-detection is the gate primitive; exit-criterion is the composition test.
* Per-class test organization mirrors the per-primitive shape (Pillar E's four primitives have four per-primitive test classes + one exit-criterion class); Pillar F follows the same convention.

### D184-Alt1: Ship voice-fidelity threshold default values at Week 1

Pre-decide the per-register threshold defaults at Week 1. **Rejected** because:

* The threshold values depend on per-corpus measurement (the embedding-distance distribution across Yang's curated corpus); the values land at Week 4+ when the threshold loader + the fidelity-scoring primitive ship.
* Premature default values lock in calibration that may be wrong against the actual corpus distribution; the operator-tunable design per D184 accommodates per-corpus drift.

### D184-Alt2: Defer both invariants to later weeks

Treat invariants as Week 6+ concerns. **Rejected** because:

* Per RETRO-pillar-e.md item-4 + RETRO-pillar-d.md item-5: invariants are DESIGNED at Week 1 even when the implementation lands later. The Week 1 design pins the convention; the implementation consumes the convention.
* Deferring contradicts the eight Pillar A/B/C/D/E carry-forward conventions.

### D184-Alt3: Ship only the hallucination-detection invariant at Week 1

Defer the voice-fidelity invariant. **Rejected** because:

* The voice-fidelity invariant is symmetric load-bearing per the exit-criterion text ("mean voice-fidelity score per register meets baseline"); shipping only one invariant leaves the binding text's first clause unverified.
* Pillar D shipped TWO invariants at Week 1 (CAN-SPAM legal-liability + suppression-as-kill-switch); Pillar F mirrors with TWO invariants at Week 1.

## Consequences

### Positive consequences

* **The Pillar F substrate is named at Week 1.** Future Pillar F Week 2-12 commits land against an established target (the voice-corpus schema + the retrieval contract + the hallucination-detection contract + the per-register-symmetry pattern + the audit + the test classes + the invariants). The per-week reviewer's fresh-context catch rate (per RETRO-pillar-e.md §"What worked") amortizes.
* **The hallucination-detection FIVE-layer defense is the structural commitment.** Pillar F's brand-and-legal-liability surface is operator-deliberate; the defense layers compose across Weeks 6-12.
* **The voice-corpus location convention preserves operator continuity.** Existing operators (Yang) keep their `voice.corpus_dir` value; the §Existing-operator seed step is documented + bounded (move corpus to `~/.outreach-factory/voice-corpus/` at operator's cadence).
* **The cross-pillar audit per D182 is the per-week reviewer's load-bearing artifact.** Every Pillar F week's commit either extends the audit OR confirms unchanged; the per-week reviewer's checklist row is concrete.
* **The exit-criterion test vehicle per D183 is the binding gate.** The 200-draft eval set's `<1%` false-negative bound is the structural verification; Pillar F's Stable flip at Week 12 is gated by the binding test passing.

### Negative consequences

* **Test count grows by 3 (three test class stubs).** The cumulative test count: 2685 (post-Pillar-E-Week-12) + 1 (Layer 1 stub un-skipped) ≈ 2686 (most rows stay SKIPPED at Week 1; the un-skipped Layer 1 stub is the privacy-equivalent test corpus pin, but here the gate doesn't exist yet so Week 1 ships only the STUB — the Layer 1 stub un-skips when the gate ships in Week 6). The growth is bounded.
* **Skip count rises by ~12-15 (per-class stub additions).** Pillar F adds three test classes with ~4-5 stubs each per the per-primitive coherence pattern. Most stays SKIPPED through Week 1; un-skips happen incrementally per the Layer table above + the per-week trajectory.
* **The `tests/test_multi_channel_coherence.py` file's size grows.** Currently ~6833 lines; this commit adds ~200-350 lines (the stub classes). Approaching the ~7000 LOC threshold; if a future Pillar F / G / H / I / J week's extension crosses ~7500 LOC the split argument resurfaces.
* **The per-week-reviewer's load grows.** The audit's per-week extensions + the per-week handoff doc + the per-week test-class extensions + the per-week-review-with-follow-up-commit discipline create per-week artifact volume. The Pillar A/B/C/D/E precedent shows the load amortizes per the per-week pattern.

### Risks

The asymmetric-failure-cost calculus (PILLAR-PLAN §0) carries:

* **The Week 1 ADR's design decisions get challenged at Week 2-12 (P2):** the voice-corpus schema's required-field shape proves inadequate for a Week 6+ adapter need. **Bounded by** the per-week amendment pattern per ADR-0033's §Amendment 2026-05-24 — the foundation ADR receives an amendment without re-opening the per-week shipping.
* **The hallucination-detection FIVE-layer defense's Layer 1 test corpus pin doesn't catch a real-world hallucination (P2):** the adversarial draft fixture doesn't represent the full hallucination space. **Bounded by** the per-week 200-draft eval set's incremental growth — Week 1 ships ~5 adversarial drafts; subsequent weeks grow the corpus to 200 per the Week 12 binding test.
* **The voice-corpus location migration breaks an operator's existing workflow (P3):** an operator with hard-coded paths in shell scripts that reference the old `voice.corpus_dir` value fails when the location convention changes. **Bounded by** the operator-tunable per-`config.yml` design + the §Existing-operator seed step's NO-AUTOMATIC-MOVE clause — operators apply the migration at their own cadence.

The framework's existing safeguards bound the regression failure modes by design.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The voice-corpus is the SoT for the corpus content (per the existing `docs/SOURCES-OF-TRUTH.md` row); the embedding cache is a derived view + rebuildable. The per-draft `draft_quality_scored` event's score + verdict land in the ledger; the per-draft body content does NOT (the draft is in the vault per the existing Touch note convention).
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. Pillar F is upstream of the dispatcher's two-phase commit (the voice-corpus + hallucination-detection happens at draft time, before `send_intent`); no changes to send-path semantics.
* **I3 — Atomic per-Person enrollment.** Preserved. Pillar F doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. Pillar F's event classes carry the channel-on-every-event invariant per ADR-0014 D33 (`voice_exemplar_retrieved.channel: <draft-channel>` + `hallucination_detected.channel: <draft-channel>` + `draft_quality_scored.channel: <draft-channel>`).
* **I5 — Migration framework discipline.** Preserved. Week 1 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The three new Pillar F event classes carry `channel: <draft-channel>` per the channel-stamping convention.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved. The voice-corpus primitive's metadata-mismatch refuse-loud per D179; the hallucination-detection primitive's construction-time refuse-loud per D180 Layer 2; the per-register adapter's enum-validation refuse-loud per D181.
* **I8 — Privacy-respecting (`source_list` operator-private + recipient research-dossier content operator-private).** Preserved + EXTENDED. Pillar F's `voice_exemplar_retrieved` event carries the exemplar's `id` field (the deterministic auto-generated slug) but NOT the exemplar's full body (privacy + storage); operators inspecting the ledger see WHICH exemplar was retrieved but must consult the voice-corpus directly for content. The `hallucination_detected` event carries the un-cited-claim trace (claim text + claim type) but NOT the full draft body (privacy + storage); operators inspecting see the offending claim but consult the Touch note for full context.

## Downstream pillar impact

* **Pillar G (Observability, begins Week 31).** Pillar G dashboards consume the three Pillar F event classes directly (`voice_exemplar_retrieved` / `hallucination_detected` / `draft_quality_scored`). The per-register fidelity-score distribution dashboard per PILLAR-PLAN §2 Pillar F is a Pillar G deliverable; the per-week reviewer's audit at each Pillar F week's commit verifies the surfaces stay stable for Pillar G consumption. Pillar G also extends the funnel CLI per ADR-0031 D140 with new breakdown dimensions: `--breakdown register` (operator-deliberate per-register aggregation per the D181 enum) — NEVER `--breakdown exemplar_id` (would surface per-sample voice-corpus content + violate the privacy-respecting invariant per I8).

* **Pillar H (Real-time + scale, begins Week 37).** The voice-corpus retrieval primitive's per-call O(N) cosine + O(N log N) argsort + per-call cache load — these are read-path performance concerns Pillar H may optimize. Week 1's contract per D179 names the substrate; Pillar H's optimizations are content-additive (the primitive's contract stays; the implementation gets caching/indexing). At v1 scale (~5K samples) the per-call cost is ~5-15ms; Pillar H scale (~100K samples) needs amortized indexing.

* **Pillar I (Multi-tenant + OSS hardening, begins Week 43).** Pillar I CLI extensions per the deferred-items list (deferred from Pillar F's per-week handoffs): `voice_corpus rebuild --since <date>` for incremental re-embedding; `voice_corpus migrate --from <old-path> --to <new-path>` for operator-side corpus migration; `hallucination_detection retest --draft-id <id>` for re-scoring after operator-side corpus update; doctor preflight extension for voice-corpus schema validation + per-sample required-field check. Pillar I also ships per-tenant voice-corpus namespaces.

* **Pillar J (Compliance + audit, begins Week 49).** GDPR-purge transaction extends to purge the voice-corpus samples mentioning a Person from the operator's corpus when the Person requests forget. The Pillar J commit extends the cross-pillar audit with the per-Person voice-corpus purge path's verdict. The per-draft `draft_quality_scored` event's score + verdict survive the purge (operator-aggregate metrics); the per-sample body content is purged.

## Migration / rollout

**Week 1 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar E Week 12 to Pillar F Week 1:

1. **Operator updates the framework** to Pillar F Week 1's commit (the standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Pillar F Week 1 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity tests/test_multi_channel_coherence.py::TestHallucinationDetection tests/test_multi_channel_coherence.py::TestPillarFExitCriterion -v`** to verify the Week 1 test stubs are collectable + the few un-skipped rows pass. Optional but recommended.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 2 ships zero migrations (the embedding-retrieval primitive is content-additive); Weeks 4-8 may ship `vault/0006_add_voice_corpus_metadata` for per-Touch-note voice-score annotations (TBD per the per-week design); Week 12 ships the binding test un-skip (zero migrations).

No operator-facing surface changes at Week 1. The Week 1 commit is foundation + test stubs + audit + ADR + handoff + retro-applied invariants; operators benefit from the structural stability the foundation pins.

## Existing-operator seed

**Pillar F Week 1 ships no operator-side state changes.** The voice-corpus location convention is documented but NOT applied automatically.

The operator-side migration trajectory (per-week ships across Pillar F Weeks 1-12):

* **Week 1 (this commit):** The voice-corpus location CONVENTION is named: `~/.outreach-factory/voice-corpus/`. Existing operators (Yang) keep their `voice.corpus_dir` value pointed at scattered locations. NO automatic move. The `index.json` schema's NEW required fields (`register`, `channel`) are NOT enforced at Week 1; existing operators' corpora with the legacy shape continue to work via the retrieval heuristic's existing path.
* **Week 2:** The embedding-retrieval primitive (`orchestrator/voice_corpus.py`) ships ALONGSIDE the existing `voice_retrieve.py` heuristic. Operators opt in to the new primitive by setting `voice.use_embedding_primitive: true` in their `~/.outreach-factory/config.yml` (default false at Week 2; default true at Week 8+ when the per-register adapters ship).
* **Weeks 4-8:** Per-register adapters ship; the `voice_thresholds.example.yml` default-shipped template lands; operators tune per their corpus.
* **Weeks 6-10:** The hallucination-detection primitive ships per the D180 Layer table; the per-week-handoff doc documents the per-week trajectory.
* **Week 12:** The binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 1:** none. The foundation is read-only.

**Operator action recommended at Week 1:** review `docs/PILLAR-PLAN.md` §6 Pillar F row's updated trajectory. Operators with curated voice corpora may begin tagging samples with `register` + `channel` ahead of the Week 2 primitive ship (the tags become consumable by the new primitive without re-ingestion).

## References

- **ADR-0032 (D142 + D146 + D147 + D148)** — Pillar E foundation (the discovery_lineage shape + the cross-pillar audit + the exit-criterion vehicle scope + the privacy invariant). Pillar F mirrors at D178 + D182 + D183 + D184.
- **ADR-0037 (D172-D177)** — Pillar E Week 12 exit-criterion close (the binding-test-as-gate + per-pillar stable-flip checklist + per-pillar retrospective discipline precedent). Pillar F's Week 12 will mirror.
- **ADR-0025 (D97)** — Pillar D foundation (the CAN-SPAM legal-liability invariant + the FIVE-layer defense precedent). Pillar F's D180 mirrors with the hallucination-detection FIVE-layer defense.
- **ADR-0014 (D33 + D37)** — Pillar C foundation (channel-on-every-event invariant + the cross-pillar coherence test vehicle's single-file rationale). Pillar F's D183 inherits the single-file rationale.
- **ADR-0033 (D149-D153)** — Pillar E Week 2 dedup primitive (the per-skill caller discipline precedent + the new event class emit-shape conventions). Pillar F's D182 mirrors with three new event classes.
- **ADR-0034 (D154-D159)** — Pillar E Week 4-5 cache primitive (the cost-event substrate extension precedent + the deterministic-clock per-call kwarg pattern). Pillar F's D179 inherits the deterministic-clock pattern.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier auto-assignment (the operator-tunable per-signal weights config precedent + the graceful-degradation contract). Pillar F's D184 mirrors with operator-tunable per-register thresholds.
- **ADR-0036 (D166-D171)** — Pillar E Week 9-11 discovery_lineage stamping (the symmetric per-skill stamping precedent + the construction-time validation precedent). Pillar F's D181 mirrors with per-register thin adapters.
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the load-bearing cross-pillar audit; Week 1 establishes baseline + per-Pillar-A/B/C/D/E surface walk.
- **`.planning/HANDOFF-pillar-f-week-1.md`** — this week's handoff document (per the per-week handoff convention).
- **`.planning/RETRO-pillar-e.md` §"What to do differently in Pillar F"** — the eight carry-forward recommendations Pillar F Week 1 honors.
- **`docs/PILLAR-PLAN.md` §2 Pillar F + §6 Pillar F row** — the binding exit-criterion text + the per-week trajectory ticker that flips to **In progress** at this commit.
- **`docs/SOURCES-OF-TRUTH.md` Voice corpus row** — the SoT registry's pre-declared row (Pillar F formalizes at Week 1 per D178).
- **`docs/RISK-REGISTER.md` R023 + R024 + R025 + R026** — the four new Pillar F risks named at design time per Week 1's risk surfacing discipline.
- **`skills/draft-outreach/SKILL.md` §Phase 4 — Voice retrieval + inline rewrite** — the existing draft-engine surface Pillar F extends per D180 + D181.
- **`orchestrator/voice_retrieve.py`** — the existing heuristic Pillar F's D179 REPLACES.
