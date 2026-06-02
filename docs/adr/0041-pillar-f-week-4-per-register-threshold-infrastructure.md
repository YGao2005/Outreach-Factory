# ADR-0041: Pillar F Week 4 — per-register voice-fidelity threshold infrastructure

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** F (Voice corpus + draft quality — Week 4 per-register threshold infrastructure)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation: voice-corpus schema + canonical location, embedding-retrieval contract, hallucination-detection FIVE-layer defense, per-register-symmetry pattern, cross-pillar audit, exit-criterion vehicle scope, voice-fidelity-and-hallucination-detection invariants. Pillar F Week 2 (ADR-0039 D185-D191) shipped the shared embedding-retrieval primitive at `orchestrator/voice_corpus.py` — `retrieve_voice_exemplars(query, *, k, register, channel, is_substantive_reply, now, ...)` as THE per-call substrate. Pillar F Week 3 (ADR-0040 D192-D198) shipped the per-register thin adapter pattern + ALL FIVE adapters in one commit + the four `DEFAULT_CHANNEL_FOR_<REGISTER>` module constants. The Week 3 commit + follow-up shipped at aefc1c8 + 46a58fc with 0 P1 + 0 P2 + 3 P3s addressed; 2827 tests passing.

Pillar F Week 4 ships **the per-register voice-fidelity threshold infrastructure** per ADR-0038 D184(a). The infrastructure is the LOAD-BEARING substrate for two downstream Pillar F primitives:

1. **Pillar F Week 6+ hallucination-detection primitive** per ADR-0038 D180 — the per-claim trace consults the per-register threshold for the operator-supplied register at Layer 2-3 (the parse-level + construction-time gates compare the per-Layer score against the per-register threshold).
2. **Pillar F Week 8+ fidelity-scoring primitive** per ADR-0038 D184(a) — the per-draft voice-fidelity score (cosine similarity × per-year recency multiplier, weighted-average over top-K corpus exemplars) gets compared against the per-register threshold to decide whether the draft advances to `ready`.

Week 4 ships ONLY the threshold loader + the operator-tunable YAML template + the default-shipped per-register threshold values + the threshold lookup helper. No new consumer surfaces (the hallucination-detection + fidelity-scoring primitives land at Weeks 6-12). The library surface is consumed by the per-week author at Weeks 6+ and operator-facing custom scripts at Week 4+.

The seven concerns this ADR resolves:

1. **The threshold YAML schema must be pinned at Week 4** so the Week 6+ hallucination-detection primitive's per-claim trace + the Week 8+ fidelity-scoring primitive's per-draft comparison build against a stable schema. The Pillar E Week 6-8 precedent at ADR-0035 D163 (`tier_weights.example.yml` template + `load_weights` loader at `orchestrator/tier_assignment.py`) is the structural reference. **D199** pins.

2. **The default-shipped threshold values must be pinned at Week 4** per ADR-0038 D184(a)'s binding text — cold-pitch ≥0.70, congrats ≥0.65, re-engagement ≥0.72, reply ≥0.70, public-comment ≥0.60. Operators MAY recalibrate against their corpus's per-register distribution at Pillar F Week 8+ (when the fidelity-scoring primitive's distribution becomes measurable). The Week 4 defaults reflect Yang's curated corpus at ship time; operators with different corpora tune at their cadence. **D200** pins.

3. **The threshold value range must be pinned at Week 4** at `[0.0, 1.0]` per ADR-0038 D184(a)'s "per-draft float in `[0.0, 1.0]`" naming. Out-of-range values raise `ValueError` at load time (refuse-loud at the boundary check). The Python-bool-is-an-int footgun (`True` → `1.0`; `False` → `0.0` would silently pass the range check) gets caught explicitly. **D201** pins.

4. **The strict per-register key requirement must be pinned at Week 4.** The loader requires all five register keys (matching `REGISTERS` per ADR-0038 D178) to be present; missing keys raise `ValueError`. The lenient alternative (missing register falls back to framework default) is rejected because the legal-and-brand-liability invariant per ADR-0038 D184 is downstream-load-bearing — partial config is operator misconfiguration that must surface loudly. Mirrors `validate_corpus_sample`'s strict-gate posture per ADR-0039 D187. **D202** pins.

5. **The process-cache posture must be pinned at Week 4.** The loader memoizes the per-process YAML parse keyed by resolved-path string (matches the `_MODEL_CACHE` per-process amortization pattern at the shared retrieval primitive per ADR-0038 D179). Cache-invalidation semantics: operator edits mid-process are NOT picked up until the next process start (same posture as the existing `_load_config` loader). **D203** pins.

6. **The threshold lookup helper must be pinned at Week 4** as the per-register convenience surface downstream Week 6+ + Week 8+ consumers call into. The helper delegates to the loader + extracts the per-register value (refuses-loud on unknown register per ADR-0038 D178's closed enum). Mirrors the Pillar E Week 6-8 `compute_tier_from_signals` per-Person convenience surface over `load_weights` per ADR-0035 D162. **D204** pins.

7. **The TEST-ONLY `embed_fn` seam preservation must be reaffirmed at Week 4** per the Week 2 audit's P3-B carry-forward — but the threshold loader DOES NOT have an `embed_fn` kwarg (the loader doesn't encode anything; the TEST-ONLY seam belongs to retrieval surfaces, not config-loader surfaces). The carry-forward is VERIFIED for Week 4's new public surfaces + carried forward to the Week 6+ hallucination-detection primitive (which WILL encode). **D205** pins.

Risks this ADR mitigates by design: **R024 (voice-corpus drift)** continues mitigated by the per-register threshold loader's per-register surfacing — future Pillar I doctor extensions consume per-register thresholds for per-register drift alerts. **R025 (embedding-cost runaway)** continues mitigated — the threshold infrastructure is read-only against the corpus; no encoder calls. **R026 (operator-corpus split)** continues mitigated by the corpus-level metadata-mismatch refuse-loud (the threshold loader is orthogonal to the corpus directory; it reads a separate YAML at a separate path).

No new risks surface in this Week 4 commit. The Week 1-pinned R023-R026 cover the Pillar F design surface; Week 4's threshold loader is content-additive against those mitigations.

## Decision

### D199. Threshold YAML schema — top-level `thresholds:` dict + per-register key set + per-register float value

The operator-tunable YAML config at `~/.outreach-factory/voice_thresholds.yml` carries a top-level `thresholds:` dict mapping each of the five registers (`REGISTERS` per ADR-0038 D178) to a per-draft voice-fidelity threshold:

```yaml
thresholds:
  cold-pitch:     0.70
  congrats:       0.65
  re-engagement:  0.72
  reply:          0.70
  public-comment: 0.60
```

The framework ships a default template at `config-template/voice_thresholds.example.yml` (sibling of `tier_weights.example.yml` per ADR-0035 D163 + `cooldowns.example.yml` per ADR-0007 + other operator-tunable YAML templates).

The loader signature: `load_voice_thresholds(thresholds_path: Path | None = None, *, cfg: dict | None = None) -> dict[str, float]`. Precedence: explicit `thresholds_path` kwarg > `cfg.voice.thresholds_path` > `DEFAULT_VOICE_THRESHOLDS_PATH`. Missing-operator-config fallback: when the operator's path is absent, the loader falls back to the default-shipped template + emits a stderr warning naming both paths (mirrors `load_weights` per ADR-0035 D164's operator-readable diagnostic discipline).

**Why a top-level `thresholds:` key wrapping the per-register dict (rejected: flat dict at top level; rejected: nested per-register `cold-pitch.threshold:` shape; rejected: per-register file at `~/.outreach-factory/voice_thresholds/<register>.yml`).**

* **Top-level `thresholds:` key** preserves room for future top-level extension (e.g., `hallucination_thresholds:` at Week 6+; `fidelity_score_window_days:` at Week 8+) without breaking the existing schema. Mirrors `tier_weights.example.yml`'s `signals:` + `thresholds:` two-key shape per ADR-0035 D163.
* **Flat dict at top level** (each register a top-level key) is rejected because it forecloses on future per-Pillar-F-week extensions to the same file — any new top-level key would conflict with a hypothetical "introduction" register added via ADR amendment.
* **Nested per-register `cold-pitch.threshold:` shape** (`cold-pitch: { threshold: 0.70, bias: True }`) is rejected because Week 4 ships only the threshold value; the nested shape inflates the schema for forward-compat that may never land + makes the operator-readability worse.
* **Per-register file at `~/.outreach-factory/voice_thresholds/<register>.yml`** is rejected because five files vs one is operator-hostile + the per-register editing workflow for "raise all thresholds by 0.05" would touch five files.

### D200. Default-shipped per-register threshold values per ADR-0038 D184(a)

Default per-register thresholds at Week 4 ship time:

| Register | Default threshold | Rationale |
|---|---|---|
| `cold-pitch` | 0.70 | Highest-stakes register; first-touch sends to prospects with no prior relationship. The per-register adapter at `retrieve_cold_pitch_exemplars` already biases toward proven-effective exemplars (`is_substantive_reply=True` per ADR-0040 D196). High-quality exemplars + high threshold compound voice fidelity. |
| `congrats` | 0.65 | Short, register-specific. Brief messages have less surface for voice signal; threshold relaxed to accommodate brevity. |
| `re-engagement` | 0.72 | Highest threshold of any register. Voice mismatch between prior touch + re-engage signals "automated outreach"; consistency-across-touches matters more than for first-touch. |
| `reply` | 0.70 | Matches cold-pitch; relationship is established but voice consistency still matters. |
| `public-comment` | 0.60 | Most relaxed. Public-comment context has loose voice norms (operators use different register in public than DMs); corpus exemplars for public-comment tend to be more varied. |

The defaults are exported as the `DEFAULT_VOICE_THRESHOLD_PER_REGISTER` module-level dict at `orchestrator/voice_corpus.py` (mirrors the `DEFAULT_CHANNEL_FOR_<REGISTER>` module-level constants per ADR-0040 D195). The default-shipped template at `config-template/voice_thresholds.example.yml` ships the same values + inline comments naming each register's rationale.

Recalibration trajectory: at Pillar F Week 8+ when the fidelity-scoring primitive lands + per-corpus per-register distributions become measurable, operators recalibrate against their corpus's distribution. The Week 4 defaults reflect Yang's curated corpus at ship time; per-corpus distributions WILL differ.

**Why ship default values at Week 4 (rejected: defer values to Week 6+ when hallucination-detection lands; rejected: ship per-register thresholds at Week 1 with the foundation ADR; rejected: derive defaults from a corpus measurement step at install time).**

* **Ship at Week 4** matches ADR-0038 D184(a)'s "Week 4+ ships" trajectory. The values are operator-tunable; framework defaults serve as the starting point.
* **Defer to Week 6+** is rejected because the threshold infrastructure is the SUBSTRATE for hallucination-detection (Week 6+) + fidelity-scoring (Week 8+); landing the infrastructure at Week 4 unblocks both downstream primitives to consume against a stable API.
* **Ship at Week 1** is rejected per ADR-0038 D184-Alt1 — premature, the thresholds depend on per-corpus measurement that the Week 6+ scoring primitive surfaces.
* **Derive defaults from install-time corpus measurement** is rejected because (a) operators may not have a corpus at install time; (b) the install-time path adds complexity for marginal benefit (operators recalibrate at Week 8+ regardless); (c) the framework should ship reasonable defaults that work without an existing corpus.

### D201. Threshold value range `[0.0, 1.0]` with refuse-loud out-of-range + explicit bool catch

Each threshold MUST be a float in `[0.0, 1.0]`. The loader validates at load time:

* `float(threshold)` coercion attempts; non-numeric values raise `ValueError` with operator-readable diagnostic ("not a valid float").
* Out-of-range values (negative, > 1.0) raise `ValueError` with the offending key + value + range.
* `bool` values caught explicitly BEFORE the `float()` coercion (Python's `bool` is an `int` subclass; `True` → `1.0` would silently pass the range check + `False` → `0.0` would too). The explicit catch surfaces operator intent (a YAML `true` literal is operator misconfiguration; the loader names the issue rather than silently coercing).
* Boundary values `0.0` and `1.0` are valid (operator-deliberate extremes — `0.0` accepts every draft; `1.0` only perfect-match drafts).

**Why `[0.0, 1.0]` with explicit bool catch (rejected: `[0.0, 1.0)` open right-side; rejected: silent bool coercion; rejected: no range validation at load time).**

* **Closed `[0.0, 1.0]`** matches ADR-0038 D184(a)'s "per-draft float in `[0.0, 1.0]`" + provides escape hatches at both ends. Boundary `1.0` lets operators set a "perfect-match only" gate for an experimental register tune-up; boundary `0.0` is the disabled-gate posture.
* **Open right-side `[0.0, 1.0)`** is rejected because operators tuning toward stricter gates need the `1.0` boundary; arbitrary cutoff at `0.999` is operator-hostile.
* **Silent bool coercion** is rejected because YAML `true` is operator misconfiguration that surfaces as a downstream draft-time accept-everything (`True` → `1.0`) or reject-everything (`False` → `0.0`); silent coercion masks the typo.
* **No range validation at load time** is rejected because the failure surfaces as a downstream comparison ambiguity (`fidelity_score >= 1.5` is always false; `fidelity_score >= -0.5` is always true) hours/days after the operator edited the YAML; load-time validation provides immediate operator feedback.

### D202. Strict per-register key requirement per ADR-0039 D187 precedent

The loader REQUIRES all five register keys (`REGISTERS` per ADR-0038 D178) to be present in the YAML's `thresholds:` dict. Missing keys raise `ValueError` naming the missing register(s); unknown keys raise `ValueError` naming the unknown key + the closed enum.

**Why strict (rejected: lenient with framework-default fallback for missing keys; rejected: strict only at Pillar F Week 12 exit gate; rejected: optional via per-register `enforce_per_register_threshold:` flag).**

* **Strict** mirrors `validate_corpus_sample`'s strict-gate posture per ADR-0039 D187. The legal-and-brand-liability invariant per ADR-0038 D184 is downstream-load-bearing; partial config is operator misconfiguration. The asymmetric-failure-cost: a partial config silently applying framework defaults for missing registers is operator-invisible drift (the operator thinks they tuned every register; the framework silently overrides for the missing keys). Strict surfaces immediately.
* **Lenient with framework-default fallback** is rejected per the asymmetric-failure-cost above. The convenience of "operator only configures the registers they care about" is paid for in invisible drift; the explicit-listing requirement is a one-time copy of the template + per-register tune.
* **Strict only at Week 12 exit gate** is rejected because the threshold loader's downstream consumers (hallucination-detection at Week 6+; fidelity-scoring at Week 8+) need the strict gate at their ship time, not at the Pillar F exit gate at Week 12.
* **Optional via flag** is rejected because the flag itself is operator configuration that may drift; the strict gate is the framework convention.

### D203. Process-cache posture per ADR-0038 D179 `_MODEL_CACHE` precedent

The loader memoizes the per-process YAML parse keyed by resolved-path string in `_VOICE_THRESHOLDS_CACHE: dict[str, dict[str, float]]`. The cache amortizes the per-process YAML parse cost (~5-10ms) across per-process invocations (the agent's per-draft loop calls the loader once per register per draft).

Cache invalidation semantics: operator edits to `~/.outreach-factory/voice_thresholds.yml` mid-process are NOT picked up until the next process start. Matches the `_load_config` posture (per the existing helper's behavior).

The loader returns a defensive copy via `dict(cached)`: caller mutations to the returned dict do NOT contaminate the cache. The defensive-copy pattern mirrors `_load_config`'s yaml.safe_load fresh-parse pattern.

**Why process-cache with defensive-copy (rejected: no cache + per-call YAML parse; rejected: TTL-based cache invalidation; rejected: file-mtime-based cache invalidation; rejected: return the cached dict directly without copying).**

* **Process-cache + defensive-copy** matches the `_MODEL_CACHE` per-process amortization pattern per ADR-0038 D179. The per-call YAML parse cost is negligible (~5-10ms) but agent-loop callers invoke per-register per-draft; caching is the consistent shape.
* **No cache** is rejected because the per-process invocation pattern (per-draft per-register) doesn't reward per-call YAML re-parse; the cache is the agent-loop optimization.
* **TTL-based cache invalidation** is rejected because (a) operators editing the YAML expect immediate effect, but the TTL window adds unpredictability; (b) the consistent posture across `_load_config` + `_MODEL_CACHE` is "fresh-load at process start, cache thereafter" — TTL diverges.
* **File-mtime-based cache invalidation** is rejected because the file-mtime check on every loader call inflates the per-call cost back toward the per-call YAML parse cost it's trying to amortize; the consistent posture is process-lifetime stale-tolerance.
* **Return cached dict directly** is rejected because caller mutations would contaminate the cache (the loader's return type is `dict[str, float]`, not `MappingProxyType` — operators may iterate + transform).

### D204. Threshold lookup helper `get_voice_threshold_for_register(register, *, thresholds_path, cfg) -> float`

Convenience helper for downstream Week 6+ hallucination-detection + Week 8+ fidelity-scoring consumers. Signature:

```python
def get_voice_threshold_for_register(
    register: str,
    *,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
) -> float: ...
```

Delegates to `load_voice_thresholds` + extracts the per-register value. Refuses-loud on unknown register (per ADR-0038 D178's closed enum) BEFORE invoking the loader (so an unknown register doesn't trigger a misleading "missing required register key" error). The underlying loader's errors (missing required register key; out-of-range value; malformed YAML) propagate unchanged.

Mirrors the Pillar E Week 6-8 `compute_tier_from_signals` per-Person convenience surface over `load_weights` per ADR-0035 D162.

**Why a per-register helper (rejected: leave downstream consumers to call the loader + index; rejected: expose only the helper with no loader; rejected: helper signature accepts `Iterable[str]` for batch lookup).**

* **Per-register helper** is the operator-readable surface for "what's the threshold for register X?". Downstream consumers (`hallucination_detection.score_per_claim(claim, register=X)` at Week 6+; `fidelity_scoring.compute_per_draft(draft, register=X)` at Week 8+) read more naturally with `get_voice_threshold_for_register(X)` than `load_voice_thresholds()[X]`.
* **Leave to consumers** is rejected because the closed-enum validation needs to happen somewhere; the helper centralizes the validation + provides a per-register operator-readable error surface.
* **Expose only helper** is rejected because batch operations (e.g., dashboard rendering ALL per-register thresholds; CLI listing) need the loader directly. Both surfaces serve different cardinalities.
* **Helper accepts `Iterable[str]`** is rejected because the per-call-per-register shape matches the per-draft consumer pattern; batch lookup can call the loader directly.

### D205. TEST-ONLY `embed_fn` seam preservation — NOT APPLICABLE to threshold loader; VERIFIED

The TEST-ONLY `embed_fn` injection seam preservation (Week 2 audit's P3-B carry-forward, reaffirmed at Week 3 per ADR-0040 D197) does NOT apply to Week 4's threshold loader. The loader does not encode anything — it parses YAML + validates per-register float values + returns a dict. There is no encoder to inject; there is no SentenceTransformer load to amortize.

The Week 4 verification: `load_voice_thresholds` + `get_voice_threshold_for_register` signatures do NOT include `embed_fn`. The P3-B carry-forward is verified UNCHANGED for Week 4's new surfaces + flagged for the Week 6+ hallucination-detection primitive (which WILL encode + WILL need the seam) + the Week 8+ fidelity-scoring primitive (which WILL encode the draft + WILL need the seam).

The per-week reviewer's checklist row at Week 4 + every subsequent Pillar F week that adds new public surfaces: "if the new public surface encodes anything (corpus, draft, claim text), it MUST expose a TEST-ONLY `embed_fn` kwarg labeled in its docstring + MUST NOT surface the kwarg via CLI."

**Why verify-only for Week 4 (rejected: surface `embed_fn` defensively even though loader doesn't encode; rejected: redesign the loader to use embeddings; rejected: skip the verification).**

* **Verify-only** is the correct posture per the seam's purpose — the seam exists to amortize per-test SentenceTransformer load cost. Surfaces that don't encode don't need the seam.
* **Surface defensively** is rejected because the kwarg's presence in the signature without a corresponding behavior is operator-confusing + creates a documentation surface (the docstring would need to explain "this kwarg does nothing for the threshold loader, it's here for future-proofing") for no benefit.
* **Redesign loader to use embeddings** is rejected because the threshold loader's job is YAML parse + range validation; no embedding cost is appropriate.
* **Skip the verification** is rejected because the Week 2 P3-B carry-forward is a per-week-reviewer checklist row; explicitly naming the Week 4 status (N/A + verified) closes the row for Week 4 + carries it forward to Weeks 6+ with explicit naming.

## Alternatives considered

### D199-Alt1: Flat dict at top level (each register a top-level key)

```yaml
cold-pitch: 0.70
congrats: 0.65
re-engagement: 0.72
reply: 0.70
public-comment: 0.60
```

**Rejected** per D199's rationale — forecloses on future top-level extensions (hallucination-detection thresholds at Week 6+; per-register bias overrides at Week 8+) + conflicts with hypothetical ADR-amended new registers.

### D199-Alt2: Nested per-register shape (`cold-pitch: { threshold: 0.70, bias: True }`)

```yaml
thresholds:
  cold-pitch:
    threshold: 0.70
    bias: true  # is_substantive_reply bias (future extension)
```

**Rejected** because Week 4 ships only the threshold value; the nested shape inflates the schema for forward-compat that may never materialize (operators may never want per-register bias overrides). YAGNI per the framework convention.

### D199-Alt3: Per-register file at `~/.outreach-factory/voice_thresholds/<register>.yml`

Each register gets its own file. **Rejected** because:

* Five files vs one is operator-hostile (per-register editing workflow scales poorly).
* The "raise all thresholds by 0.05" workflow touches five files.
* Operators auditing their tuning via `cat ~/.outreach-factory/voice_thresholds.yml` becomes `cat ~/.outreach-factory/voice_thresholds/*.yml` — extra ceremony.

### D200-Alt1: Defer default values to Week 6+ when hallucination-detection lands

Ship the loader + the YAML schema at Week 4 with NO default-shipped template values; operators MUST configure all five values before the Week 6+ hallucination-detection primitive consumes the threshold. **Rejected** because:

* The framework convention is "ship sensible defaults; allow operator override" (every cap rule per ADR-0007 D11; every tier auto-assignment per ADR-0035 D162; every per-register channel default per ADR-0040 D195).
* Operators adopting the Week 6+ primitive without per-register tuning would hit a runtime error; the framework should ship reasonable defaults.

### D200-Alt2: Ship per-register thresholds at Week 1 with the foundation ADR

Land the threshold values + the loader at the Week 1 foundation commit. **Rejected** per ADR-0038 D184-Alt1 — premature, the threshold values depend on per-corpus measurement that the Week 6+ scoring primitive surfaces (Week 1 didn't have the measurement primitive; landing the values would be guesses).

### D200-Alt3: Derive defaults from a corpus measurement step at install time

The framework's install path scans the operator's corpus + computes per-register percentile thresholds. **Rejected** because:

* Operators may not have a corpus at install time (the threshold infrastructure ships before the per-corpus measurement primitive at Week 8+).
* Install-time path adds complexity for marginal benefit (operators recalibrate at Week 8+ when the scoring primitive lands regardless).
* The framework should ship reasonable defaults that work without an existing corpus.

### D201-Alt1: Open right-side range `[0.0, 1.0)`

Reject `1.0`. **Rejected** because operators tuning toward stricter gates need the `1.0` boundary; arbitrary cutoff at `0.999` is operator-hostile.

### D201-Alt2: Silent bool coercion

Allow YAML `true` → `1.0`; `false` → `0.0`. **Rejected** because:

* YAML `true` is operator misconfiguration (the YAML literal type is wrong); silent coercion masks the typo.
* Surfacing as a comparison ambiguity hours/days after the edit (`fidelity_score >= 1.0` is sometimes true; `fidelity_score >= 0.0` is always true) is operator-hostile.

### D201-Alt3: No range validation at load time

Defer range validation to the downstream consumer (the fidelity-scoring primitive at Week 8+). **Rejected** because:

* The load-time validation provides immediate operator feedback (edit YAML → run validate → see error).
* Deferring loses the operator-readable diagnostic at the layer that knows the schema; the downstream consumer would surface a comparison ambiguity, not a "threshold out of range" message.

### D202-Alt1: Lenient with framework-default fallback for missing keys

Missing register keys fall back to the framework default per `DEFAULT_VOICE_THRESHOLD_PER_REGISTER`. **Rejected** per D202's rationale — asymmetric-failure-cost: partial config silently applying framework defaults is operator-invisible drift; the explicit-listing requirement is a one-time copy of the template + per-register tune.

### D202-Alt2: Strict only at Pillar F Week 12 exit gate

Land lenient at Week 4; flip to strict at Week 12. **Rejected** because the downstream consumers (Week 6+ hallucination-detection; Week 8+ fidelity-scoring) need the strict gate at their ship time. Deferring weakens the contract.

### D202-Alt3: Optional via per-register `enforce_per_register_threshold:` flag

Operators opt out of the strict gate via a YAML flag. **Rejected** because the flag itself is operator configuration that may drift; the strict gate is the framework convention.

### D203-Alt1: No cache + per-call YAML parse

Each loader call re-parses YAML. **Rejected** because the per-process invocation pattern (per-draft per-register × 5 registers × N drafts/session) rewards caching. ~5-10ms × 5 registers × 10 drafts = 250-500ms per session of redundant YAML parse.

### D203-Alt2: TTL-based cache invalidation

Cache TTL of N seconds; re-parse after TTL expires. **Rejected** because:

* Operators editing YAML expect immediate effect at next process start (consistent posture).
* TTL window adds unpredictability (when does my edit land? After N seconds? After N seconds + the next loader call?).
* Diverges from `_load_config` + `_MODEL_CACHE` posture.

### D203-Alt3: File-mtime-based cache invalidation

Cache hit checks file mtime; re-parse on change. **Rejected** because the per-call mtime check inflates per-call cost back toward per-call YAML parse cost.

### D203-Alt4: Return cached dict directly without copying

Return `_VOICE_THRESHOLDS_CACHE[key]` directly. **Rejected** because caller mutations would contaminate the cache; downstream consumers iterating + transforming the dict would silently mutate the per-process source of truth.

### D204-Alt1: Leave downstream consumers to call the loader + index

Consumers write `load_voice_thresholds()["cold-pitch"]`. **Rejected** because the closed-enum validation needs centralization + the per-register helper is more readable at the call site.

### D204-Alt2: Expose only the helper with no loader

Drop `load_voice_thresholds` as a public surface; expose only `get_voice_threshold_for_register`. **Rejected** because batch operations (CLI listing; Pillar G dashboard rendering all per-register thresholds) need the loader directly.

### D204-Alt3: Helper accepts `Iterable[str]` for batch lookup

Signature: `get_voice_thresholds_for_registers(registers: Iterable[str]) -> dict[str, float]`. **Rejected** because the per-call-per-register shape matches the per-draft consumer pattern; batch lookup can call the loader directly.

### D205-Alt1: Surface `embed_fn` defensively even though loader doesn't encode

Add `embed_fn: Callable | None = None` to the loader signature for "future-proofing" (in case future weeks add embedding-based threshold computation). **Rejected** because:

* The kwarg's presence without corresponding behavior is operator-confusing.
* Future-proofing for hypothetical functionality is the YAGNI anti-pattern.
* If future weeks add embedding-based threshold computation, the seam can be added with an ADR amendment + the same TEST-ONLY discipline.

### D205-Alt2: Redesign the loader to use embeddings

Make the threshold loader compute thresholds from corpus embeddings (e.g., per-register percentile cutoff). **Rejected** per D200-Alt3 + Week 4 scope — the threshold loader's job is YAML parse + range validation; embedding-based threshold derivation is Pillar F Week 8+ scope (the fidelity-scoring primitive's per-corpus distribution measurement).

### D205-Alt3: Skip the verification

Don't explicitly name Week 4's P3-B status. **Rejected** because the Week 2 P3-B carry-forward is a per-week-reviewer checklist row; explicitly naming the Week 4 status (N/A + verified) closes the row for Week 4 + carries it forward to Weeks 6+.

## Consequences

### Positive consequences

* **Downstream Week 6+ hallucination-detection + Week 8+ fidelity-scoring primitives can ship against a stable threshold infrastructure.** The per-claim threshold lookup + per-draft threshold comparison surfaces are designed; the Week 6+ + Week 8+ primitives are content-additive against the threshold loader.
* **Operators get sensible defaults at Week 4** per ADR-0038 D184(a)'s binding text. Operators MAY tune per-register at their cadence; the framework defaults work without an existing corpus.
* **The strict per-register key requirement surfaces operator misconfiguration loudly.** Partial config raises `ValueError` with operator-readable diagnostic naming the missing register(s); operator-invisible drift via framework-default fallback is foreclosed.
* **The process-cache amortizes per-process YAML parse cost.** Per-draft per-register loader invocations hit the cache; YAML parse is paid once per process per resolved path.
* **The Pillar E Week 6-8 `load_weights` precedent is mirrored.** The framework's per-pillar-per-week operator-tunable YAML loader convention carries forward; future contributors see the precedent + apply at their pillar's analogous week.

### Negative consequences

* **Test count grows by ~35 tests** (TestVoiceThresholds + TestGetVoiceThresholdForRegister + TestModuleConstants extensions). Cumulative: 2827 (post-Pillar-F-Week-3-follow-up) → ~2862 (post-Pillar-F-Week-4). The growth is bounded; per-test coverage is targeted at refuse-loud + per-register strict-gate + process-cache posture.
* **`orchestrator/voice_corpus.py` grows from ~1742 LOC to ~1990 LOC** (adding ~250 LOC for the loader + helper + module constants + docstrings). The growth is intentional — the threshold infrastructure lands all-at-once.
* **A second operator-tunable YAML at `~/.outreach-factory/voice_thresholds.yml` joins the existing `~/.outreach-factory/tier_weights.yml`.** Operators with thoroughly-tuned setups now have two YAMLs in the config directory. The trade-off is intentional — the per-register threshold deserves a dedicated file (vs cramming into the generic `config.yml`) for the same operator-readability reasons `tier_weights.yml` deserves a dedicated file per ADR-0035 D163.

### Risks

The asymmetric-failure-cost calculus carries:

* **The per-register default's drift risk (P2):** A future Pillar F contributor might change `DEFAULT_VOICE_THRESHOLD_PER_REGISTER["cold-pitch"]` to a different value without updating the default-shipped template at `config-template/voice_thresholds.example.yml`. **Bounded by** the test `test_default_shipped_template_loads_cleanly` (verifies the template matches the constant) + the cross-pillar audit's §27+ naming the per-register defaults as a single source of truth + the per-week reviewer's checklist row at every Pillar F week verifying the defaults match.

* **The strict gate's operator friction (P3):** Operators adopting partial-config patterns from other YAMLs (e.g., `tier_weights.yml`'s lenient missing-key posture) may be surprised by the strict gate. **Bounded by** the loader's operator-readable error message (names the missing register(s) + the closed-enum + the path to fix) + the template's inline comment explaining the strict requirement + the §Migration/rollout naming the strict gate.

* **The process-cache's mid-process-edit invisibility (P3):** Operators editing `~/.outreach-factory/voice_thresholds.yml` mid-process won't see the edit until process restart. **Bounded by** the docstring naming the semantics + the existing precedent (`_load_config` has the same posture) + Pillar I CLI tooling at Week 8+ may surface a cache-invalidation subcommand IF operator demand materializes.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The threshold loader is upstream of the ledger (it parses YAML + returns a dict; it does NOT write to the ledger). Downstream consumers (Week 6+ hallucination-detection; Week 8+ fidelity-scoring) emit events that land in the ledger; the threshold values flow through but the LEDGER is the SoT for per-event data.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The threshold loader is read-only.
* **I3 — Atomic per-Person enrollment.** Preserved. Week 4 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The threshold loader is per-register (orthogonal to per-channel state).
* **I5 — Migration framework discipline.** Preserved. Week 4 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The threshold loader is READ-only — it doesn't emit events. Downstream consumers (hallucination-detection; fidelity-scoring) WILL emit events that stamp `channel:` per ADR-0014 D33.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. The loader's strict per-register key requirement per D202 + the out-of-range threshold refuse-loud per D201 + the unknown register key refuse-loud per D202 + the bool catch per D201 + the malformed YAML propagation per D199 are five new refuse-loud surfaces. Mirrors `validate_corpus_sample`'s multi-violation aggregation per ADR-0039 D187.
* **I8 — Privacy-respecting.** Preserved. The threshold loader is read-only against a static YAML; no per-Person data.

## Downstream pillar impact

* **Pillar F Week 5 (operator-deferred per-week scope).** Week 5's scope is open per the per-week author's call. The Week 4 threshold infrastructure is stable; Week 5 may extend with additional operator-tunable per-register surfaces (e.g., per-register top-K override; per-register `is_substantive_reply` bias override at the loader level per D196's deferred-to-Week-8+ trajectory) IF demand materializes.

* **Pillar F Week 6+ (hallucination-detection primitive).** The Week 6+ hallucination-detection primitive's per-claim trace consults `get_voice_threshold_for_register(register=<draft-register>)` at Layer 2 (construction-time invariant) + Layer 3 (parse-level guard). The per-register threshold is the load-bearing comparison target.

* **Pillar F Week 8+ (fidelity-scoring primitive).** The Week 8+ fidelity-scoring primitive's per-draft entry point computes the fidelity score + compares against `get_voice_threshold_for_register(register=<draft-register>)` to decide whether the draft advances to `ready`. The per-register threshold is the binding gate.

* **Pillar F Week 8+ (`voice.use_embedding_primitive` default flip).** The Week 8+ flip of `voice.use_embedding_primitive` from `false` to `true` depends on per-register threshold availability — operators flipping the flag need per-register operator-tunable thresholds in place to tune their voice fidelity gates. The Week 4 infrastructure unblocks the Week 8+ flip.

* **Pillar G (Observability).** Dashboards consume `voice_fidelity_score` events with per-register threshold annotation — the per-register threshold infrastructure's stable identity makes the dashboard's per-register comparison meaningful (operators see "draft scored 0.58; cold-pitch threshold is 0.70 — gate refused").

* **Pillar H (Real-time + scale).** The threshold loader's per-call cost is negligible (~5-10ms one-time YAML parse; ~0.1ms cache hit). Pillar H's scaling concerns target the per-draft scoring primitive at Week 8+; the threshold loader is content-additive against the optimization.

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions per ADR-0038 §Downstream pillar impact list MAY extend with `voice_corpus thresholds list / set / dump` subcommands IF operator demand materializes. Week 4 ships library-only; the CLI extension is operator-deferred to Pillar I. Pillar I's per-tenant config separation also extends to `voice_thresholds.yml` (per-tenant override at `<tenant>/voice_thresholds.yml`).

* **Pillar J (Compliance + audit).** Per-tenant GDPR-purge does not touch the threshold YAML (it's per-tenant config, not per-Person data). The threshold values themselves are NOT subject to purge (operator config, not personal data).

## Migration / rollout

**Week 4 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 3 to Pillar F Week 4:

1. **Operator updates the framework** to Pillar F Week 4's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 4 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_voice_corpus.py -v`** to verify the new threshold loader tests pass. Optional but recommended.
4. **Operator decides whether to copy the default-shipped template to their config directory.** Two paths:
   * **Path A (recommended for first-time adoption):** `cp config-template/voice_thresholds.example.yml ~/.outreach-factory/voice_thresholds.yml` + tune per-register as needed.
   * **Path B (defer-to-default):** Skip the copy step; the framework falls back to the default-shipped template + emits a stderr warning per loader call. Operators see the warning + decide whether to opt in.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 5 may ship operator-deferred per-register surfaces (no migration; content-additive). Week 6+ ships hallucination-detection's Layer 2 + Layer 3 (no migration; consumes the threshold loader). Week 8+ ships fidelity-scoring + flips `voice.use_embedding_primitive` default + may ship `vault/0006_add_voice_fidelity_score` for per-Touch-note fidelity annotations (TBD per the per-week design). Week 12 ships the binding exit-criterion test.

## Existing-operator seed

**Pillar F Week 4's operator-side disposition is content-additive — no operator action required at Week 4.** The threshold infrastructure is library-only at this commit. The downstream consumers (Week 6+ hallucination-detection; Week 8+ fidelity-scoring) haven't shipped yet; operators have no behavioral change at Week 4.

The operator-side trajectory (per-week ships across Pillar F Weeks 4-12):

* **Week 4 (this commit):** The threshold loader + the operator-tunable YAML template land at `~/.outreach-factory/voice_thresholds.yml` (default fallback to the shipped template). Operators copy + tune at their cadence. SKILL.md is UNCHANGED at Week 4.
* **Week 5:** Per-week author's call — open scope.
* **Weeks 6-10:** Hallucination-detection primitive's Layers 2-4 ship per ADR-0038 D180; the per-register threshold loader is consumed for the per-Layer per-register threshold comparison. SKILL.md Phase 5 / 5.5 extensions land at Weeks 6+ per the P2-B carry-forward.
* **Week 8+:** Fidelity-scoring primitive lands; the per-draft fidelity score is compared against `get_voice_threshold_for_register(register)`. The `voice.use_embedding_primitive` default flips from `false` to `true`. SKILL.md Phase 4 extends with per-register routing.
* **Week 12:** Binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 4:** none. The framework upgrade is read-only with respect to operator state.

**Operator action recommended at Week 4:** none beyond the per-week pytest verification. Operators MAY copy the template to their config directory + tune per-register thresholds; the framework continues to fall back to defaults if the operator opts to defer.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D184(a) (voice-fidelity score is per-register operator-tunable at `~/.outreach-factory/voice_thresholds.yml` with default-shipped template at `config-template/voice_thresholds.example.yml` Week 4+; default per-register thresholds calibrated against Yang's curated corpus at Week 4 ship time) is THE binding text Week 4 implements.
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive. D187 (`validate_corpus_sample` strict-gate posture) is the STRUCTURAL reference for Week 4's strict per-register key requirement per D202.
- **ADR-0040 (D192-D198)** — Pillar F Week 3 per-register adapters. D195 (per-register channel default module-level constants) is the STRUCTURAL reference for Week 4's `DEFAULT_VOICE_THRESHOLD_PER_REGISTER` module-level dict per D200. D197 (TEST-ONLY `embed_fn` seam preservation) is VERIFIED unchanged for Week 4's new surfaces per D205.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier_assignment primitive. D163 (operator-tunable YAML config loader at `~/.outreach-factory/tier_weights.yml` with default-shipped template at `config-template/tier_weights.example.yml`) is THE structural reference for Week 4's threshold loader. D164 (operator-readable diagnostic discipline — stderr warning on fallback to default) carries over.
- **ADR-0036 (D166)** — Pillar E Week 9-11 per-primitive-flat-module convention. Week 4's threshold loader at `orchestrator/voice_corpus.py` (sibling of `retrieve_voice_exemplars` per D188) preserves the convention.
- **ADR-0014 (D33)** — Pillar C foundation. The channel-on-every-event invariant continues through the per-register adapters' downstream callers at Week 6+ + Week 8+; the threshold loader is upstream + does NOT touch the invariant.
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §27+ extends with the Week 4 commit's audit verdict (the threshold loader's public surface + the YAML schema + the per-register threshold defaults table + the SKILL.md UNCHANGED status + the SOURCES-OF-TRUTH row UNCHANGED status).
- **`.planning/HANDOFF-pillar-f-week-4.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 5 trajectory.
- **`orchestrator/voice_corpus.py`** — extended with the threshold loader + helper + the `DEFAULT_VOICE_THRESHOLDS_PATH` + `DEFAULT_VOICE_THRESHOLD_PER_REGISTER` module constants per D199-D204.
- **`config-template/voice_thresholds.example.yml`** (NEW) — default-shipped per-register threshold template per D200.
- **`config-template/config.example.yml`** — extended with `voice.thresholds_path` field per D199.
- **`tests/test_voice_corpus.py`** — extended with `TestVoiceThresholds` class + `TestGetVoiceThresholdForRegister` class (~35 tests covering loader happy path + per-register override + refuse-loud on unknown register / out-of-range value / missing required register / non-existent file / malformed YAML / bool catch + `get_voice_threshold_for_register` happy path + refuse-loud + process-cache posture).
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 4 close summary.
- **`docs/adr/README.md`** — ADR-0041 row appended.
