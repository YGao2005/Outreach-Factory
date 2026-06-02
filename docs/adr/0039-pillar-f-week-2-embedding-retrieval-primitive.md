# ADR-0039: Pillar F Week 2 — embedding-retrieval primitive (`orchestrator/voice_corpus.py`)

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** F (Voice corpus + draft quality — Week 2 embedding-retrieval primitive)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation: voice-corpus schema + canonical location, embedding-retrieval contract, hallucination-detection FIVE-layer defense, per-register-symmetry pattern, cross-pillar audit, exit-criterion vehicle scope, voice-fidelity + hallucination-detection invariants. The Week 1 commit + follow-up shipped at 68aa00e + 45007f2 with 0 P1 + 2 P2 + 2 P3s; 2685 tests passing. The Pillar F Week 1 audit named ONE LOAD-BEARING carry-forward for Week 2: **P2-A**, the `/draft-outreach` SKILL.md Phase 4 invocation update to call the new primitive instead of `voice_retrieve.py`.

Pillar F Week 2 ships **the embedding-retrieval primitive itself** per ADR-0038 D179 — `orchestrator/voice_corpus.py` (the module that replaces the heuristic in `orchestrator/voice_retrieve.py`). Per ADR-0038 D181's per-register-symmetry pattern, this Week 2 commit ships the SHARED retrieval primitive; per-register thin adapters land in Weeks 4-8 per the rollout.

The seven concerns this ADR resolves:

1. **The primitive's module placement + module surface must be pinned at Week 2** so subsequent Pillar F weeks (Week 4-8 per-register adapters; Week 6+ hallucination-detection primitive; Week 8+ fidelity scoring primitive) build against a stable target. The Pillar E precedent is the four primitives at the top level of `orchestrator/` (per ADR-0036 D166's per-primitive-flat-module convention); Pillar F follows. **D185** pins.

2. **The `VoiceExemplar` dataclass shape + construction-time invariants must be designed at Week 2** so per-register adapters at Week 4-8 consume a single closed-set shape rather than diverging per-adapter. The Pillar E `DiscoveryLineage.__post_init__` precedent per ADR-0036 D167 applies: construction-time validation is the load-bearing refuse-loud surface. **D186** pins.

3. **The `validate_corpus_sample` strict gate must ship at Week 2** so operators tagging corpora with `register` + `channel` see schema violations BEFORE the per-register retrieval ships in Weeks 4-8. Without the gate, the Week 4-8 commits' per-register adapters would surface unvalidated corpora as runtime errors. The Pillar E `enrollment.validate_identity_keys` precedent applies: validators ship the SAME week as the schema. **D187** pins.

4. **The `retrieve_voice_exemplars` per-call entry point must implement the D179 contract at Week 2** — per-register filter + per-channel filter + `is_substantive_reply` filter + `now` deterministic-clock kwarg + metadata-mismatch refuse-loud. This is THE substrate every downstream consumer (the `/draft-outreach` SKILL.md Phase 4 invocation; the Week 4-8 per-register adapters; the Week 6+ hallucination-detection primitive's retrieve-then-cross-reference path) reads against. **D188** pins.

5. **The `voice_exemplar_retrieved` event-payload factory must ship at Week 2** so the CLI's `--apply` path lands the event in the ledger AT Week 2 — the cross-pillar audit's category 8 surface (per ADR-0038 D182) gains its first concrete consumer. Without the factory, the audit category is theoretical until Week 4-8. **D189** pins.

6. **The metadata-mismatch refuse-loud + the operator-controlled rebuild path must ship at Week 2** so the R026 mitigation (operator-corpus split across multi-machine) is concrete, not theoretical. The `rebuild_on_mismatch` kwarg + the `rebuild` CLI subcommand together close R026's defense surface. **D190** pins.

7. **The `/draft-outreach` SKILL.md Phase 4 update must ship at Week 2** per the Pillar F Week 1 audit's P2-A carry-forward (the LOAD-BEARING item). Without the update, the SKILL.md drifts from the framework's new substrate + operators using the skill continue to invoke the heuristic indefinitely. The Pillar E precedent (Week 2's `discovery_dedup` ALSO updated `skills/find-leads/SKILL.md` Phase 3e simultaneously per ADR-0033 D152) applies. **D191** pins.

Risks this ADR mitigates by design: **R024 (voice-corpus drift)** is mitigated by the `register` + `channel` filters surfacing per-register fidelity slices for future drift-detection (Pillar I doctor extension deferred per ADR-0038 §Downstream pillar impact). **R025 (embedding-cost runaway)** stays mitigated by the default `BAAI/bge-small-en-v1.5` local-CPU model + the operator-tunable `voice.embed_model` config field with NO auto-switch to paid models. **R026 (operator-corpus split)** is mitigated by D190's metadata sidecar refuse-loud + rebuild path.

No new risks surface in this Week 2 commit. The Week 1-pinned R023-R026 cover the Pillar F design surface; Week 2's implementation is content-additive against those mitigations.

## Decision

### D185. Module placement — `orchestrator/voice_corpus.py` (top-level sibling)

The new primitive lives at `orchestrator/voice_corpus.py`, a top-level sibling of `discovery_dedup.py` + `email_verification_cache.py` + `tier_assignment.py` + `discovery_lineage.py` + the existing `voice_retrieve.py`. The flat-module convention per ADR-0036 D166 carries forward — each primitive's public surface is one module, importable via `from orchestrator.voice_corpus import retrieve_voice_exemplars, ...`. The Week 1 conftest pre-registration at `tests/conftest.py:39-55` already names `voice_corpus` in the aliasing loop (per the Pillar F Week 1 follow-up's dual-module-identity-hazard mitigation); this Week 2 commit lands the actual module file.

**Why a top-level sibling (rejected: subpackage; rejected: extension of `voice_retrieve.py`; rejected: per-register-module subpackage).** Three reasonable shapes:

* **(a) Top-level sibling at `orchestrator/voice_corpus.py`** — D185's choice. Continues the per-primitive-flat-module convention; one import path per primitive.
* **(b) Subpackage at `orchestrator/voice_corpus/`** with per-register modules — rejected per ADR-0038 D181-Alt1: over-organization for ~10 LOC per per-register adapter; future contributors navigate two-segment import paths for no proportional benefit.
* **(c) Extension of `orchestrator/voice_retrieve.py`** (rename + grow) — rejected: the legacy heuristic stays UNCHANGED for backwards-compat per ADR-0038 §Existing-operator seed; growing it in place mixes the legacy + new contracts in one file + makes the eventual Week 8+ deprecation cut harder.

### D186. `VoiceExemplar` dataclass + construction-time invariants

The per-sample dataclass:

```python
@dataclass(frozen=True)
class VoiceExemplar:
    id: str
    date: str          # ISO 8601 UTC per D178
    body: str
    register: str | None   # None tolerated for legacy corpora
    channel: str | None    # None tolerated for legacy corpora
    year: int
    subject: str | None = None
    to: list | None = None
    tags: list | None = None
    is_substantive_reply: bool | None = None
    voice_score_baseline: float | None = None
    score: float | None = None     # populated by retrieval
```

Construction-time invariants in `__post_init__`:

* `id` non-empty (whitespace-stripped) — ValueError.
* `date` matches the ISO 8601 UTC regex from `discovery_lineage._is_iso8601_utc` — ValueError on naive / non-UTC offsets.
* `body` non-empty (whitespace-stripped) — ValueError.
* `register` is `None` OR member of `REGISTERS` — ValueError on unknown non-None.
* `channel` is `None` OR member of `CHANNELS` — ValueError on unknown non-None.
* `year` is `int` (rejecting `bool` per Python `isinstance(True, int) == True` gotcha).
* `voice_score_baseline` is `None` OR float in `[0.0, 1.0]` — ValueError on out-of-range.

The `None` posture for `register` + `channel` per ADR-0038 D178 §Existing-operator seed — pre-Pillar-F samples lacking the new schema fields are TOLERATED by the dataclass (the retrieval primitive's per-register filter treats them as "any register"). The STRICT gate is `validate_corpus_sample` (D187) — new corpora must validate clean; old corpora are usable but unfiltered. Mirrors the Pillar E precedent for legacy `source_channel` rows per ADR-0036 §Existing-operator seed.

**Why frozen + construction-time-validated (rejected: mutable dataclass; rejected: pydantic; rejected: dict-only).**

* **Frozen mirrors Pillar E's four primitives' dataclass discipline** per ADR-0036 D167 — operators can safely pass a single instance across the retrieve → factory → ledger-emit boundary without copying.
* **Construction-time validation refuses-loud at the construction site** — the caller sees the schema violation immediately, not in a downstream consumer. Pydantic adds a dependency for the same effect; the framework today has no pydantic surface. Dict-only loses the typing surface for IDE-assisted authoring of per-register adapters.

### D187. `validate_corpus_sample(sample: dict) -> ValidationResult` strict gate

The strict schema validator per ADR-0038 D178. Required fields: `id` + `date` + `body` + `register` + `channel` + `year`. Optional fields (`subject` / `to` / `tags` / `is_substantive_reply` / `voice_score_baseline`) are silently accepted; unknown extra keys are tolerated for forward-compat with future Pillar F schema extensions.

The function returns a `ValidationResult` carrying `ok: bool` + `errors: list[str]`. **All schema violations surface in a single validator pass** — operators fix all errors at once rather than per-call. Mirrors the Pillar A doctor preflight's aggregation pattern per ADR-0008 §Doctor's verbose-mode + Pillar E's `parse_discovery_lineage_dict` error message shape.

```python
@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def validate_corpus_sample(sample: dict) -> ValidationResult: ...
```

The function ships at this Week 2 commit. The CLI's `validate --corpus-dir <path>` subcommand wraps it for operator-side per-corpus audits. Future Pillar I `doctor` extension consumes the same validator for the framework-side preflight.

**Why a separate strict validator (rejected: only construction-time; rejected: only CLI; rejected: pydantic).**

* **Separate strict validator catches schema drift before construction** — operators tagging corpora see the gate's verdict before they invoke retrieval; without the validator, the FIRST per-register filter call surfaces the error confusingly far from the corpus-tagging step.
* **Construction-time validation is the BACK-STOP** (`VoiceExemplar.__post_init__` catches anything that bypassed the validator); the two surfaces compose. The Pillar E `identity.resolve_strict` + `enrollment._safe_append` two-layer defense precedent applies.

### D188. `retrieve_voice_exemplars` — the per-call entry point

The contract per ADR-0038 D179 implemented:

```python
def retrieve_voice_exemplars(
    query: str,
    *,
    k: int = DEFAULT_TOP_K,
    register: str | None = None,
    channel: str | None = None,
    is_substantive_reply: bool | None = None,
    now: datetime | None = None,
    corpus_dir: Path | None = None,
    embed_model: str | None = None,
    rebuild_on_mismatch: bool = False,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
) -> list[VoiceExemplar]: ...
```

**Per-call behavior:**

1. **Validate filters** — `register` (if non-None) must be in `REGISTERS`; `channel` (if non-None) must be in `CHANNELS`. Raises `ValueError` per ADR-0038 D179 refuse-loud-on-unknown.
2. **Resolve corpus_dir + embed_model** from kwargs → `cfg` → `~/.outreach-factory/config.yml` → `DEFAULT_CORPUS_DIR` / `DEFAULT_EMBED_MODEL`.
3. **Load `embeddings.npy` + `index.json` + `metadata.json`** from `corpus_dir`. Each file-not-found raises `FileNotFoundError` with an operator-readable message naming the rebuild CLI invocation.
4. **Verify metadata** — `embed_model` + `schema_version` + `corpus_count` (computed from `embeddings.shape[0]`). On mismatch: `VoiceCorpusMetadataMismatch` (R026 refuse-loud) — UNLESS `rebuild_on_mismatch=True`, in which case `rebuild_corpus` runs in-place + the load retries.
5. **Encode query** via `embed_fn` (defaults to process-cached `SentenceTransformer(embed_model).encode`).
6. **Filter the index** by `register` (legacy-None passes through any filter) + `channel` (same) + `is_substantive_reply` (strict bool comparison).
7. **Compute cosine × recency** — cosine via `embeddings @ q_emb` (embeddings are pre-normalized at build time per the `voice_retrieve.py:110` precedent); recency multiplier `1.0 - (anchor_year - sample.year) * RECENT_BIAS_PER_YEAR` where `anchor_year = (now or datetime.now(UTC)).year`. Per ADR-0038 D179 deterministic-clock contract.
8. **Top-K by descending score** — Python's sort is stable; equal-score ties preserve insertion order (filesystem order in `index.json`).
9. **Coerce to `VoiceExemplar`** — lenient construction (legacy fields default to None) + populated `score`.

**Process-cached `SentenceTransformer`** — the `_MODEL_CACHE: dict` module-level dict memoizes per-`embed_model` loads. First call ~1-2s (load); subsequent ~5-15ms (encode + cosine + argsort). Per ADR-0038 D179 §Design decisions trade-off; the cache amortizes across the agent's per-draft loop. **Test isolation** — tests inject `embed_fn=` to bypass the cache + load.

**Operator-supplied `embed_fn` is the test-injection seam, NOT the operator-tuning seam.** Operators choose models via `embed_model` (string identifier); the framework provides the encoder. The `embed_fn` kwarg is reserved for tests + future Pillar I CLI tooling (e.g., `voice_corpus benchmark --embed-fn <module:fn>`). Documented in the docstring; not surfaced in the CLI.

**Why filters BEFORE scoring (rejected: filter after score; rejected: filter during scoring; rejected: per-register top-K then merge).**

* **Filter-before-score honors the operator-deliberate intent** — the per-register filter is a precondition for the per-register-symmetry pattern (D181). Scoring all-then-filtering would surface the top-K by global cosine THEN narrow; a cold-pitch retrieve with `register="cold-pitch"` would return fewer than K results if global ranking pulled congrats above the cold-pitch top-K. Filter-first guarantees the K returned ARE the top-K within the filter.
* **Filter-during-scoring (sparse-encode-then-rank) is over-engineering for v1 scale** — the framework's v1 corpus is ~5K samples; per-call full-matrix cosine is <5ms. Per-filter-aware sparse indexing optimizes for the Pillar H (~100K samples) scale; premature for Pillar F.
* **Per-register top-K-then-merge inverts the contract** — operators asking for K cold-pitch exemplars want K of them, not a mix. The per-register filter's load-bearing property is exclusivity within the filter.

### D189. `build_voice_exemplar_retrieved_payload` event-payload factory

The factory per ADR-0038 D182 — emit-shape for the first of Pillar F's three new event classes:

```python
def build_voice_exemplar_retrieved_payload(
    *,
    person_id: str | None,
    query: str,
    exemplars: list[VoiceExemplar],
    channel: str,                    # required, in CHANNELS
    register: str | None,            # may be None for unscoped
) -> dict: ...
```

Event shape:

```text
type:        voice_exemplar_retrieved
person_id    (the prospect the draft targets; None for ad-hoc retrieval)
query_hash   (sha256:<hex> of query — NOT the raw query)
exemplars    (list of {exemplar_id, score} — bodies NOT included)
channel      (closed-enum per ADR-0014 D33; required)
register     (closed-enum per D178; may be None for unscoped retrieval)
_emitted_by  ("voice_corpus" per ADR-0010 D17)
```

**Privacy-respecting per I8 extension (ADR-0038 §Compliance with invariants):**

* **Raw query MUST NOT appear in the payload.** The query is sha256-hashed; operators can deterministically re-hash a draft text + grep the ledger for matches without exposing the draft body. Mirrors the Pillar E `discovery_lineage`'s operator-private posture per ADR-0032 D148 — Pillar G dashboards aggregate by `channel` + `register` + per-event count, NEVER by `query_hash` (an aggregation by hash is operator-deliberate, not Pillar G default).
* **Per-exemplar body MUST NOT appear in the payload.** The payload carries `{exemplar_id, score}` per exemplar; operators look up bodies via `python orchestrator/voice_corpus.py retrieve --query "..." --json` against the corpus directly. The cross-pillar audit's category 8 enforces this.

**Refuse-loud-on-unknown** — `channel` not in `CHANNELS` raises `ValueError`; `register` (if non-None) not in `REGISTERS` raises `ValueError`. Construction-site refuse-loud is symmetric to `VoiceExemplar.__post_init__`.

**Empty exemplars accepted** — when filters yield zero matches, the retrieve returns `[]` + the factory accepts the empty list. The emitted event signals operator-visibly that the retrieval ran but returned nothing (per-event-count Pillar G dashboard catches the case).

**Why build-then-append separation (rejected: emit-inside-retrieve; rejected: factory-returns-Event; rejected: skip-factory-altogether).**

* **Build-then-append separation matches the Pillar E precedent** per ADR-0033 D150 + ADR-0034 D155 + ADR-0035 D161 — the factory builds the dict; the caller appends to the ledger; the dry-run path skips the append. The CLI's `--apply` flag controls the live-emit; the same factory is reused for the dry-run JSON output.
* **Emit-inside-retrieve couples the read path to a write side effect** — operators calling `retrieve_voice_exemplars` for a sanity check would un-intendedly write to the ledger; the read/write separation is the I1 invariant's structural commitment.

### D190. Metadata sidecar + operator-controlled rebuild path

The cache sidecar at `<corpus_dir>/metadata.json` carries:

```json
{
  "embed_model": "BAAI/bge-small-en-v1.5",
  "embed_version": "5.1.2",
  "sentence_transformers_version": "5.1.2",
  "schema_version": 1,
  "corpus_count": 5234,
  "built_at": "2026-05-24T18:32:00Z"
}
```

**On every retrieve, the primitive verifies:**

* `metadata.embed_model == runtime.embed_model` — operator-tunable model choice; mismatch means the cached embeddings were built with a different model + the per-query cosine is invalid against them.
* `metadata.schema_version == SCHEMA_VERSION` — module-pinned; mismatch means the per-sample shape has drifted across a framework upgrade boundary.
* `metadata.corpus_count == embeddings.shape[0]` — sanity check (the index.json's length should also match but we don't enforce that — operators editing the index manually may not rebuild; the count-vs-embeddings check is the load-bearing dimension).

**On mismatch:** `VoiceCorpusMetadataMismatch` raised with the per-field diff in the message. R026 mitigation: refuse-loud rather than silently scoring against stale embeddings.

**Operator override:** `rebuild_on_mismatch=True` (passed via kwarg OR set via `voice.rebuild_on_metadata_mismatch: true` in `~/.outreach-factory/config.yml` — though the config-driven path is operator-deferred to Pillar I CLI). Triggers `rebuild_corpus(corpus_dir, embed_model=runtime_model, embed_fn=...)`: re-encodes every sample's body + writes new `embeddings.npy` + `metadata.json`, then retries the load.

**Manual rebuild CLI:** `python orchestrator/voice_corpus.py rebuild --corpus-dir <path> [--embed-model <model>]`. Operators run after upgrading the framework OR after changing models. The CLI calls the same `rebuild_corpus` function.

**Why three-fields verification (rejected: model-only; rejected: schema-only; rejected: all-fields-incl-built_at-staleness-check).**

* **Three-fields is the minimum sufficient set** — `embed_model` catches model-switch mismatches; `schema_version` catches framework-upgrade drift; `corpus_count` catches operator-side manual-edit drift. Each catches a distinct R026 sub-failure mode.
* **`built_at` staleness check is rejected** — operators don't rebuild on a schedule; "built more than 30 days ago" is not a structural mismatch (the model + schema + count haven't drifted). A staleness signal IS useful for drift detection (Pillar I doctor extension) but not for the retrieve refuse-loud gate.

### D191. `/draft-outreach` SKILL.md Phase 4 update — P2-A carry-forward

The skill's Phase 4 invocation gets a config-driven dispatch:

* **`voice.use_embedding_primitive: true`** → invoke `python orchestrator/voice_corpus.py retrieve --file /tmp/draft.txt --k 5 [--register R] [--channel C] --json`. The new primitive surfaces per-register + per-channel filtered exemplars with the deterministic-clock-controlled recency multiplier.
* **`voice.use_embedding_primitive: false`** (default at Week 2) OR missing → invoke `python orchestrator/voice_retrieve.py --file /tmp/draft.txt` (the legacy heuristic). Operators with corpora not yet tagged with `register` + `channel` keep the legacy path until they opt in.

The SKILL.md's Step 1 names BOTH paths + the operator-chooses-via-config disposition. Step 2's voice-rewrite prompt is content-additive against both schemas (the exemplar shape is the same — `{id, date, subject, body, score, ...}` — Path A adds `register` + `channel` per-exemplar but the prompt doesn't consume them).

The deprecation note: `voice_retrieve.py` stays through Pillar F Week 8+ per ADR-0038 §Existing-operator seed. After Week 8, operators are expected to migrate; `voice_retrieve.py` becomes operator-deprecated (NOT removed — the file ships but emits a stderr deprecation notice on import; Pillar F Week 8+ ADR pins the actual removal).

**Why dual-path config-driven dispatch (rejected: strict-cutover; rejected: hard-cutover; rejected: skill auto-detects).**

* **Dual-path lets operators opt in at their own cadence** per ADR-0038 §Existing-operator seed. Operators with corpora ready (tagged with `register` + `channel`) flip the flag; operators with legacy corpora keep working. Mirrors the Pillar E `voice.use_embedding_primitive`-equivalent opt-in posture (Pillar E shipped `email_verification_cache` alongside the existing Reoon HTTP path per ADR-0034 §Existing-operator seed).
* **Strict-cutover at Week 2 breaks operators with legacy corpora** — they'd need to rebuild + re-tag in one weekend; the Pillar A retro precedent (refuse-loud-on-missing-config) is operator-friendly but the schema migration is heavier.
* **Skill auto-detects via index.json scan** — over-engineering: parsing the corpus index inside the skill prose is fragile + couples the SKILL.md to the primitive's internals. The config flag is the operator-deliberate explicit signal.

## Alternatives considered

### D185-Alt1: Subpackage `orchestrator/voice_corpus/`

A package directory with per-register modules + a shared `__init__.py`. **Rejected** because:

* Inflates import-path surface — `from orchestrator.voice_corpus.cold_pitch import retrieve_cold_pitch_exemplars` vs `from orchestrator.voice_corpus import retrieve_cold_pitch_exemplars`.
* ~10 LOC per per-register adapter doesn't justify per-register module isolation.
* The four Pillar E primitives all ship as flat modules; the convention compounds.

### D185-Alt2: Extension of `orchestrator/voice_retrieve.py` (rename + grow)

Rename `voice_retrieve.py` to `voice_corpus.py` + extend in place. **Rejected** because:

* The legacy heuristic stays UNCHANGED for backwards-compat per ADR-0038 §Existing-operator seed; growing in place mixes contracts.
* The Week 8+ deprecation cut becomes harder (more code to remove cleanly).
* Operators with shell scripts referencing `voice_retrieve.py` would silently break.

### D185-Alt3: Subpackage under `voice_corpus/` with `__init__.py` re-exports

Same as Alt1 but with a flat import-path via `__init__.py`. **Rejected** because:

* Adds a `__init__.py` indirection layer for no behavioral benefit.
* Future Pillar F contributors discovering the module trace through two files instead of one.

### D186-Alt1: Mutable dataclass

A non-frozen `VoiceExemplar`. **Rejected** because:

* Mutability across the retrieve → factory → ledger boundary creates aliasing hazards — a caller mutating the `score` on a returned exemplar would affect the next caller in the same process.
* Pillar E's four primitives all ship frozen; the framework convention is operator-readable.

### D186-Alt2: Pydantic-validated dataclass

`pydantic.BaseModel`-based schema. **Rejected** because:

* Adds pydantic as a fifth framework dependency; current orchestrator has zero pydantic surface.
* The construction-time invariants are ~30 LOC of explicit checks; pydantic's auto-generation is no clearer.
* The Pillar E `DiscoveryLineage` precedent uses explicit checks + a clear ValueError message; consistency.

### D186-Alt3: Dict-only — skip the dataclass

Pass `dict` everywhere; no typed surface. **Rejected** because:

* Loses IDE-assisted authoring for per-register adapters at Week 4-8.
* The `score` field's per-call population becomes implicit (every consumer must remember to populate it).
* Schema drift across consumers would surface only at runtime; the dataclass's frozen-ness is the static gate.

### D187-Alt1: Only construction-time validation (no separate validator)

Skip `validate_corpus_sample`; rely on `VoiceExemplar.__post_init__`. **Rejected** because:

* Operators tagging corpora can't validate-without-loading-the-corpus (the per-sample construction would chain through the whole index before catching the first error).
* Multi-violation aggregation is lost — `__post_init__` raises on the first violation; the validator aggregates.
* The CLI's `validate --corpus-dir <path>` subcommand has no entry point.

### D187-Alt2: Only CLI validation (no library function)

Wrap the schema check in a CLI command; no Python-callable function. **Rejected** because:

* Future Pillar I `doctor` extension needs a library-callable validator; without one, the CLI is the only path + the framework's internal callers shell out (Pillar A doctor's shell-out precedent is operator-tunable but inefficient for batch).
* Tests can't drive the validator without subprocess overhead.

### D187-Alt3: Pydantic schema

A `pydantic.BaseModel` for the per-sample schema with `model_validate` returning a `ValidationError`. **Rejected** because:

* Adds the pydantic dependency for one validator.
* The per-violation aggregation needs explicit handling either way; pydantic's default raises on first.

### D188-Alt1: No `embed_fn` injection seam

The retrieval primitive always loads `SentenceTransformer(embed_model)` directly; tests can't bypass. **Rejected** because:

* Per-test SentenceTransformer load is ~1-2s × N tests = unacceptable test-suite cost.
* The test isolation surface is load-bearing for the per-week-reviewer's checklist row (per-week reviewers verify retrieval behavior; per-test SentenceTransformer load multiplies their iteration cycle).
* The injection seam is a TEST-ONLY concern not surfaced in the CLI.

### D188-Alt2: Per-call SentenceTransformer load (no process cache)

Load the model fresh on every retrieve call. **Rejected** because:

* Per-draft retrieve cost balloons from ~5-15ms to ~1-2s + ~5-15ms; an operator drafting 10 emails/day pays ~10-20s of CPU per session vs ~50-150ms.
* The model is stateless across calls (no per-call mutation hazard); cache is safe.
* Mirrors `voice_retrieve.py:109` per-call load — but the new primitive REPLACES the heuristic + can do better.

### D188-Alt3: `embed_fn` as the operator-tuning seam (not test-only)

Operators configure `voice.embed_fn = "module:fn"` for arbitrary encoder injection. **Rejected** because:

* The operator-tuning surface is `voice.embed_model` (string name); the encoder is framework-controlled.
* Arbitrary `embed_fn` injection is a security concern (operators import user-supplied code at retrieve time).
* The Pillar I CLI tooling extension is the structured surface for advanced encoder injection; not the per-call retrieve kwarg.

### D189-Alt1: Emit-inside-retrieve

The `retrieve_voice_exemplars` function appends the event to the ledger before returning. **Rejected** because:

* Couples the read path to a write side effect; operators inspecting via CLI dry-run accidentally write.
* Pillar E's four primitives all separate build + append; consistency.
* The I1 invariant (ledger is SoT) is structurally weakest when read paths emit silently.

### D189-Alt2: Factory returns `Event` instance, not dict

Return a `Ledger.Event` (per ledger.py:203) instead of a plain dict. **Rejected** because:

* Pillar E factories return dicts; the convention is consistent.
* The `Ledger.append(dict)` path adds the `ts` + `event_id` fields at append time; passing an Event would duplicate the construction.

### D189-Alt3: Skip the factory — operators construct payloads manually

Document the event shape; let callers build the dict. **Rejected** because:

* Schema drift across callers — Pillar E's four primitives have a single factory each; adding callers without a factory invites copy-paste drift in field names.
* The Pillar D `reply_classifier.build_classified_payload` precedent is the convention; consistency.

### D190-Alt1: No metadata sidecar (assume cache valid)

Read `embeddings.npy` + `index.json`; don't check anything. **Rejected** because:

* R026 (operator-corpus split) becomes unmitigated — multi-machine operators silently score against stale embeddings.
* The R026 mitigation is the load-bearing safety property per ADR-0038 D179 §R026 mitigation.

### D190-Alt2: Sidecar but warn-only (don't raise)

Detect mismatch, print stderr warning, proceed. **Rejected** because:

* Refuse-loud is the framework convention per I7 (refuse-loud on operator misconfiguration).
* Warning-only invites operators to ignore drift; the retrieve proceeds with invalid scores.

### D190-Alt3: Auto-rebuild by default

`rebuild_on_mismatch=True` as the default behavior. **Rejected** because:

* Auto-rebuild has operator-visible cost (~5-10s for 10K samples on local CPU); operators expect retrieve to be ~5-15ms.
* The implicit rebuild surface hides the model-mismatch event from operator-side audit.
* Operator-controlled opt-in (default False) matches the Pillar A "simulate-first" precedent.

### D191-Alt1: Strict-cutover at Week 2

Phase 4 only invokes the new primitive; remove the `voice_retrieve.py` path from the SKILL.md. **Rejected** because:

* Operators with legacy corpora break immediately on framework upgrade.
* The §Existing-operator seed step (per ADR-0038) names a multi-week migration trajectory; strict-cutover compresses it to one weekend.

### D191-Alt2: Skill auto-detects via index.json scan

The skill parses index.json's first row + dispatches based on whether `register` is present. **Rejected** because:

* Couples the SKILL.md to the primitive's internals — schema drift in `index.json` breaks the skill's dispatch logic.
* The config flag is the operator-deliberate explicit signal; auto-detect is operator-invisible.

### D191-Alt3: Defer SKILL.md update to Week 4-8 (when per-register adapters land)

Wait to update Phase 4 until the per-register adapters are ready. **Rejected** because:

* The Week 1 audit's P2-A is LOAD-BEARING for Week 2 — without the update, the SKILL.md drifts from the framework's new substrate.
* The Pillar E precedent (Week 2's discovery_dedup ALSO updated find-leads SKILL.md per ADR-0033 D152) applies; the per-week atomicity is "primitive + per-skill integration".

## Consequences

### Positive consequences

* **The substrate Pillar F Week 4-12 builds on lands at Week 2.** Per-register adapters (Weeks 4-8) call into the shared primitive with `register=` set; hallucination-detection (Weeks 6+) consults the corpus directly via `retrieve_voice_exemplars(query=research_dossier_text, ...)`; fidelity-scoring (Weeks 8+) re-encodes drafts and compares against the corpus exemplars. The contract is stable.
* **Existing operators keep working** — `voice_retrieve.py` is preserved; the SKILL.md dispatches via config. The §Existing-operator seed migration is bounded.
* **R026 mitigation is concrete** — the metadata sidecar + the rebuild path together close the operator-corpus-split refusal surface.
* **The cross-pillar audit's category 8 gains its first concrete consumer** — the `voice_exemplar_retrieved` event class is now emit-able; future Pillar F weeks' commits inspect operator-facing ledger surfaces against the channel-on-every-event invariant.

### Negative consequences

* **Test count grows by ~89 (test_voice_corpus.py) + 6 un-skipped coherence rows = ~95.** Cumulative: 2685 (post-Pillar-F-Week-1) → ~2780 (post-Pillar-F-Week-2). The growth is bounded; no per-test SentenceTransformer load via the `embed_fn` injection.
* **The two-path Phase 4 dispatch is operator-visible complexity.** Operators reading the SKILL.md see TWO retrieval invocations; the config flag chooses. The complexity is bounded to the Week 2-8 transition window.
* **The `voice_corpus.py` module is ~900 LOC** (vs `voice_retrieve.py`'s 155 LOC). The expansion is intentional — the per-call entry point ships filter + clock + metadata + factory + CLI + lenient-coercion contracts the heuristic didn't have. Each is load-bearing for Weeks 4-12.

### Risks

The asymmetric-failure-cost calculus carries:

* **The metadata-mismatch refuse-loud catches every operator-side mismatch (P2):** the `corpus_count` check is strict — `metadata.corpus_count != embeddings.shape[0]` raises. Operators rebuilding via a non-canonical path (e.g., a custom rebuild script that doesn't update metadata) trip the gate. **Bounded by** the `rebuild` CLI subcommand documented as the canonical rebuild path + the deprecation note in `voice/README.md` (operator-deferred to Pillar F Week 4+).

* **The `embed_fn` injection seam's misuse (P3):** A future Pillar F contributor might tempt-pass `embed_fn=` in production to swap encoders without going through `embed_model`. **Bounded by** the docstring naming the seam as TEST-ONLY + the absence of a CLI surface for the kwarg + the Pillar I CLI tooling extension as the structured surface for advanced encoder injection.

* **The Phase 4 dual-path's bit-rot risk (P3):** Operators not flipping `voice.use_embedding_primitive: true` indefinitely keep the legacy path. **Bounded by** the §Existing-operator seed step naming Pillar F Week 8+ as the default-flip date + the per-week-reviewer's checklist row at Week 8 confirming the flip.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The voice-corpus is the SoT for corpus content per ADR-0038 D178; the embedding cache is a derived view per D190's metadata sidecar. The `voice_exemplar_retrieved` event lands in the ledger with `query_hash` + per-exemplar `id` + `score`; the corpus content is NOT in the event.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The voice-corpus primitive is upstream of the dispatcher.
* **I3 — Atomic per-Person enrollment.** Preserved. Pillar F Week 2 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The `channel` filter is per-channel; the emitted `voice_exemplar_retrieved` event stamps `channel: <value>`.
* **I5 — Migration framework discipline.** Preserved. Week 2 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The `voice_exemplar_retrieved` event class stamps `channel` per ADR-0014 D33's extension; the factory raises on unknown channel.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. Three new refuse-loud surfaces: (a) per-filter validation in `retrieve_voice_exemplars`; (b) metadata-mismatch in `_check_metadata` → `VoiceCorpusMetadataMismatch`; (c) per-sample validation in `validate_corpus_sample` + `VoiceExemplar.__post_init__`.
* **I8 — Privacy-respecting.** Preserved + EXTENDED. The `voice_exemplar_retrieved` event carries `query_hash` (NOT raw query) + per-exemplar `id` (NOT body) + `score` (operator-deliberate aggregation grain). Operators inspect corpus content via the corpus directory directly; the ledger event is hash-only.

## Downstream pillar impact

* **Pillar F Week 4-8 (per-register adapters).** The shared `retrieve_voice_exemplars` is the substrate. Per-register thin adapters (e.g., `retrieve_cold_pitch_exemplars`) call into the shared primitive with `register=` + `channel=` + `is_substantive_reply=` set per the D181 register table. The contract is stable; per-register adapter additions are content-additive.

* **Pillar F Week 6+ (hallucination-detection primitive).** The hallucination-detection primitive (Week 6+ per ADR-0038 D180 Layer 3) parses the draft + cross-references against the research dossier's citation set. It does NOT consume the voice-corpus directly — but operators MAY use voice-corpus retrieval to compare paraphrastic patterns (Pillar F Week 8+ fidelity scoring extension).

* **Pillar F Week 8+ (fidelity-scoring primitive).** The per-draft voice-fidelity score is the embedding distance between draft and top-K corpus exemplars (weighted average). The primitive consumes `retrieve_voice_exemplars` to surface the K exemplars + encodes the draft itself + computes the weighted average. The contract Week 2 ships is the prerequisite.

* **Pillar G (Observability).** Dashboards consume `voice_exemplar_retrieved` events for per-register retrieval-coverage analysis (per-day count by register; per-register score distribution). The cross-pillar audit's category 8 gates this: dashboards aggregate by `register` + `channel` + per-event count, NEVER by `query_hash` or per-exemplar body.

* **Pillar H (Real-time + scale).** The per-call O(N) cosine + O(N log N) sort is read-path performance. The contract D188 names; Pillar H optimizations (sparse indexing; pre-filter-aware partition; per-corpus shard) are content-additive against the contract. At v1 scale (~5K samples) the per-call cost is ~5-15ms; Pillar H scale (~100K samples) needs amortized indexing.

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions per the ADR-0038 §Downstream pillar impact list:
  * `voice_corpus rebuild --since <date>` for incremental re-embedding (operator-friendly version of the Week 2 full-corpus rebuild).
  * `voice_corpus migrate --from <old-path> --to <new-path>` for operator-side corpus migration to canonical location.
  * `voice_corpus benchmark --query <text>` for per-corpus retrieval-latency measurement (consumes the same primitive).
  * `voice_corpus doctor --corpus-dir <path>` for the operator-side preflight (validates schema + metadata + cosine-sanity-check; surfaces drift signals).

* **Pillar J (Compliance + audit).** GDPR-purge extends to remove voice-corpus samples mentioning a Person. The per-Person purge path inspects `index.json` + filters by recipient `to` + rewrites the corpus. The audit's category 8 enforces that purge is per-Person not per-exemplar (operator-aggregate fidelity metrics survive; per-sample body content is purged).

## Migration / rollout

**Week 2 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 1 to Pillar F Week 2:

1. **Operator updates the framework** to Pillar F Week 2's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 2 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_voice_corpus.py tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity -v`** to verify the new primitive's tests + the un-skipped coherence rows pass. Optional but recommended.
4. **Operator decides whether to opt in to the new primitive.** Two paths:
   * **Stay on legacy heuristic (default):** No action required. `voice.use_embedding_primitive: false` (default); the SKILL.md's Phase 4 continues to invoke `voice_retrieve.py`.
   * **Opt in to new primitive:** Tag the corpus' `index.json` samples with `register` + `channel` per the D178 schema (operator-side work; consult `voice/README.md` for the per-sample fields). Rebuild via `python orchestrator/voice_corpus.py rebuild --corpus-dir <path>` (writes new `metadata.json`). Flip `voice.use_embedding_primitive: true` in `~/.outreach-factory/config.yml`. Run `/draft-outreach` — Phase 4 now uses the new primitive.

**Subsequent Pillar F weeks' migrations** (forward-reference): Weeks 4-8 may ship `vault/0006_add_voice_corpus_metadata` for per-Touch-note voice-score annotations (TBD per the per-week design). Week 6+ ships the hallucination-detection primitive (no migration; content-additive). Week 8+ ships the fidelity-scoring primitive (may ship `ledger/0008_voice_fidelity_score_index` for per-event indexing; TBD).

## Existing-operator seed

**Pillar F Week 2's operator-side disposition mirrors Pillar E Week 4-5's email_verification_cache rollout posture:** the new primitive ships alongside the legacy heuristic; operators opt in via config; no automatic state changes.

The operator-side migration trajectory (per-week ships across Pillar F Weeks 2-12):

* **Week 2 (this commit):** The primitive ships at `orchestrator/voice_corpus.py`. The SKILL.md's Phase 4 dispatches via `voice.use_embedding_primitive` (default false at Week 2). Operators keep their `voice.corpus_dir` value pointed at scattered locations; NO automatic move. Operators may opt in by tagging the corpus + flipping the flag.
* **Weeks 4-8:** Per-register thin adapters ship; the `voice_thresholds.example.yml` default-shipped template lands; operators tune per-register thresholds.
* **Week 6+:** Hallucination-detection primitive Layers 2-3 ship per ADR-0038 D180. SKILL.md Phase 5/5.5 extended.
* **Week 8+:** `voice.use_embedding_primitive` default flips to `true`. Operators who haven't migrated their corpus see refuse-loud (unknown register / channel → validator fails) on first retrieval; operators with legacy corpora keep the heuristic path active via explicit `voice.use_embedding_primitive: false`. `voice_retrieve.py` enters operator-deprecated state (file ships; stderr deprecation notice on import).
* **Week 10:** Layer 4 (post-engine guard) ships per D180.
* **Week 12:** Layer 5 (reconcile heal-pass refusal) ships; binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 2:** none. The framework upgrade is read-only with respect to operator state.

**Operator action recommended at Week 2:** review the Phase 4 dispatch; tag corpora with `register` + `channel` ahead of Week 8's default flip; rebuild via `python orchestrator/voice_corpus.py rebuild --corpus-dir <path>` after re-tagging.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D178 (schema + canonical location) + D179 (embedding-retrieval contract) + D181 (per-register-symmetry pattern) + D182 (cross-pillar audit + new event class names) are the load-bearing Week 2 inputs.
- **ADR-0036 (D166-D171)** — Pillar E Week 9-11 discovery_lineage primitive. The per-primitive-flat-module convention per D166 + the construction-time validation precedent per D167 + the per-skill stamping shape per D169-D170 are the structural references.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier_assignment primitive. The operator-tunable YAML config precedent per D163 + the graceful-degradation contract per D162 are the design references for the `voice.embed_model` operator-tunable field.
- **ADR-0034 (D154-D159)** — Pillar E Week 4-5 email_verification_cache primitive. The "ship alongside legacy + config-driven opt-in" §Existing-operator seed precedent + the deterministic-clock `now` kwarg pattern per D156 carry forward.
- **ADR-0033 (D149-D153)** — Pillar E Week 2 discovery_dedup primitive. The per-skill SKILL.md integration discipline per D152 is the structural reference for D191's `/draft-outreach` SKILL.md Phase 4 update.
- **ADR-0014 (D33 + D37)** — Pillar C foundation. D33's channel-on-every-event invariant extends to the `voice_exemplar_retrieved` event class per D189.
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §17+ extends with the Week 2 commit's audit verdict (UNCHANGED for the existing surfaces; the new primitive's consumer surface is named here per D182's "audit lands against concrete event-type names").
- **`.planning/HANDOFF-pillar-f-week-2.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 3 trajectory.
- **`orchestrator/voice_corpus.py`** — the new primitive (this commit).
- **`tests/test_voice_corpus.py`** — the per-primitive unit tests (~89 tests covering invariants + validator + retrieve + payload factory + rebuild + CLI smoke).
- **`tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity`** — 6 of 7 stub rows un-skipped at this Week 2 commit; the `test_per_register_adapter_filters_to_correct_register` row stays SKIPPED for Weeks 4-8 per ADR-0038 D181 trajectory.
- **`skills/draft-outreach/SKILL.md` §Phase 4** — updated per D191 (P2-A from Week 1 audit closed).
- **`config-template/config.example.yml`** — extended with `voice.use_embedding_primitive` + `voice.embed_model` + `voice.rebuild_on_metadata_mismatch` per D188 + D190.
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 2 close summary.
- **`docs/adr/README.md`** — ADR-0039 row appended.
- **`docs/SOURCES-OF-TRUTH.md` Voice corpus row** — Notes column updated to reference ADR-0039 + name the new primitive's substrate shape.
