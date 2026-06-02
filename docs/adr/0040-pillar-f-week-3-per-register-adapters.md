# ADR-0040: Pillar F Week 3 — per-register adapters (`retrieve_<register>_exemplars`)

- **Status:** Accepted
- **Date:** 2026-05-24
- **Pillar:** F (Voice corpus + draft quality — Week 3 per-register adapters)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation: voice-corpus schema + canonical location, embedding-retrieval contract, hallucination-detection FIVE-layer defense, per-register-symmetry pattern, cross-pillar audit, exit-criterion vehicle scope, voice-fidelity-and-hallucination-detection invariants. Pillar F Week 2 (ADR-0039 D185-D191) shipped the shared embedding-retrieval primitive at `orchestrator/voice_corpus.py` — `retrieve_voice_exemplars(query, *, k, register, channel, is_substantive_reply, now, ...)` is THE substrate every downstream consumer reads against. The Week 2 commit + follow-up shipped at 0914273 + 8e864f0 with 0 P1 + 3 P2 + 3 P3s addressed; 2789 tests passing. The Pillar F Week 2 audit named ONE LOAD-BEARING carry-forward for Week 3+: **P3-B**, preserving the TEST-ONLY `embed_fn` injection seam at any new public surface (the per-register adapters).

Pillar F Week 3 ships **the per-register thin adapter pattern + all five adapters in a single commit** per ADR-0038 D181's per-register-symmetry pattern + the Pillar E Week 9-11 single-commit-four-skill-stamping precedent (ADR-0036 D169). The five registers — cold-pitch / congrats / re-engagement / reply / public-comment — each get a thin free-function adapter at `orchestrator/voice_corpus.py` (the same module as the shared primitive). The adapter shape is symmetric across all five; the per-register differences are: filter values (each adapter passes its own `register=` to the shared primitive), per-register channel defaults (frozen via module-level constants), and per-register `is_substantive_reply` biases (cold-pitch biases `True`; others stay `None`). The reply register is the lone exception to the channel-default convention — its channel is operator-supplied per the SKILL.md's "match inbound channel" rule.

The seven concerns this ADR resolves:

1. **The per-register adapter shape must be pinned at Week 3** so the Week 8+ `/draft-outreach` Phase 4 per-register routing extension + the Week 6+ hallucination-detection per-register dispatch + the Week 8+ fidelity-scoring per-register calibration build against a stable target. The Pillar E Week 9-11 precedent at ADR-0036 D166 (per-primitive-flat-module convention) + D169 (single-commit four-skill stamping via shared `enroll_person(lineage=)` kwarg) is the structural reference. **D192** pins.

2. **The per-register kwarg dispatch convention must be pinned at Week 3** so per-week reviewers can verify every adapter's per-register defaults match the `/draft-outreach` SKILL.md register table (lines 339-345) at a single source of truth. Without the convention, future Pillar F weeks' commits could quietly drift the per-register defaults; the SKILL.md's prose + the adapter's kwarg defaults could diverge. **D193** pins.

3. **The per-register signature shape must be symmetric** so adopters at Week 8+ (the SKILL.md Phase 4 per-register routing extension) consume FIVE adapters with the same signature (modulo the `reply` register's operator-deliberate channel-required asymmetry per ADR-0038 D181's "match inbound channel" rule). Symmetric signatures mean per-register documentation can be templated; mass refactors (e.g., adding a kwarg) touch all five adapters uniformly. **D194** pins.

4. **The per-register channel default constants must be pinned at module level** at Week 3 so the cross-pillar audit + the SKILL.md register table + the per-register adapter docstrings reference a single source of truth. Without the constants, the per-register defaults would live only inside each adapter's body — operators reading the adapter source would see five separate `"email"` / `"linkedin-dm"` / etc. literals rather than five constant references. The Pillar E precedent at `discovery_lineage.LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL` (D167) is module-level dispatch constants. **D195** pins.

5. **The per-register `is_substantive_reply` bias convention must be pinned at Week 3** so adopters at Week 8+ see WHY each register defaults the way it does. Cold-pitch biases `True` (per ADR-0038 D178 + the SKILL.md's 5-touch sampling discipline — proven-effective exemplars improve voice fidelity for the highest-stakes register). The other four registers default `None` (congrats often don't get replies; re-engagement / reply / public-comment have varied reply patterns). **D196** pins.

6. **The TEST-ONLY `embed_fn` seam preservation must be reaffirmed at Week 3** per the Week 2 audit's P3-B carry-forward. Each new per-register adapter MUST inherit the seam as TEST-ONLY in its docstring + MUST NOT surface the kwarg via CLI. The per-week reviewer's checklist row at Week 3 (and at every Pillar F week that adds new public retrieval surfaces) verifies. **D197** pins.

7. **The single-commit five-adapter ship (Option B per the Week 2 author's recommendation) is the Week 3 author's deliberate choice** per the Pillar E Week 9-11 single-commit-four-skill-stamping precedent (ADR-0036 D169). The five adapters are structurally identical (~30 LOC each including docstring); one ADR + one batch is feasible + amortizes the per-week-reviewer's audit pass + frees Weeks 4-5 for the per-register threshold infrastructure (`voice_thresholds.example.yml` + the per-register threshold loader per ADR-0038 D184). **D198** pins.

Risks this ADR mitigates by design: **R024 (voice-corpus drift)** continues mitigated by the per-register filter primitive's per-register fidelity surfacing — future Pillar I doctor extensions consume per-register adapters for per-register drift signals. **R025 (embedding-cost runaway)** continues mitigated by the per-register adapters' content-additive posture (no new model loads; no per-adapter encoder). **R026 (operator-corpus split)** continues mitigated by the per-register adapters' content-additive posture (the metadata-mismatch refuse-loud at the shared primitive's load path covers every adapter call).

No new risks surface in this Week 3 commit. The Week 1-pinned R023-R026 cover the Pillar F design surface; Week 3's per-register adapters are content-additive against those mitigations.

## Decision

### D192. Per-register adapter shape — thin free-function per register at `orchestrator/voice_corpus.py`

Five new module-level free functions land at `orchestrator/voice_corpus.py` (sibling of `retrieve_voice_exemplars` at the same module per ADR-0036 D166's per-primitive-flat-module convention):

* `retrieve_cold_pitch_exemplars(query, *, k=DEFAULT_TOP_K, channel=None, ...) -> list[VoiceExemplar]`
* `retrieve_congrats_exemplars(query, *, k=DEFAULT_TOP_K, channel=None, ...) -> list[VoiceExemplar]`
* `retrieve_re_engagement_exemplars(query, *, k=DEFAULT_TOP_K, channel=None, ...) -> list[VoiceExemplar]`
* `retrieve_reply_exemplars(query, *, k=DEFAULT_TOP_K, channel=None, ...) -> list[VoiceExemplar]`
* `retrieve_public_comment_exemplars(query, *, k=DEFAULT_TOP_K, channel=None, ...) -> list[VoiceExemplar]`

Each adapter is ~30 LOC including docstring. The adapter body delegates to `retrieve_voice_exemplars` with the per-register `register=` value frozen + per-register `channel=` default + per-register `is_substantive_reply=` bias per D196. The shared primitive's contract is preserved unchanged — Week 2's `retrieve_voice_exemplars` / `validate_corpus_sample` / `build_voice_exemplar_retrieved_payload` / `rebuild_corpus` public surfaces stay verbatim.

**Why thin free-function per register (rejected: per-register methods on a VoiceCorpus class; rejected: per-register modules at `orchestrator/voice_corpus/cold_pitch.py`; rejected: one giant adapter with internal dispatch).** Three reasonable shapes — all already rejected at ADR-0038 D181-Alt1/2/3:

* **(a) Thin per-register free functions sharing one primitive** — D192's choice. Mirrors the discovery_dedup `build_discovery_dedup_hit_payload` + discovery_lineage `build_discovery_lineage_dict` free-function convention from Pillar E (ADR-0033 D150 + ADR-0036 D168). The adapter is module-level + importable via `from orchestrator.voice_corpus import retrieve_cold_pitch_exemplars`.
* **(b) Per-register methods on a `VoiceCorpus` class** — rejected: imposes object-orientation hierarchy that obscures the simple shape; Pillar E's four primitives all ship free functions + dataclasses, not class methods. The class wrapper has zero state to carry between calls (the shared primitive is process-cached at the module level via `_MODEL_CACHE`).
* **(c) Per-register modules at `orchestrator/voice_corpus/cold_pitch.py` / `congrats.py` / etc.** — rejected per ADR-0038 D181-Alt1: over-organization for ~30 LOC per per-register adapter; future contributors navigate two-segment import paths for no proportional benefit.
* **(d) One giant adapter `retrieve_for_register(register: str, ...)` with internal dispatch** — rejected per ADR-0038 D181-Alt3: a new register requires editing the internal switch (vs adding a new free function); the per-register surface is closed and adding a sixth register is an operator-deliberate ADR amendment, not a routine extension.

### D193. Per-register kwarg dispatch convention

Each adapter calls `retrieve_voice_exemplars` with closed-set kwarg values matching the SKILL.md register table (lines 339-345):

| Adapter | `register=` | Default `channel=` | `is_substantive_reply=` |
|---|---|---|---|
| `retrieve_cold_pitch_exemplars` | `"cold-pitch"` | `"email"` (`DEFAULT_CHANNEL_FOR_COLD_PITCH`) | `True` |
| `retrieve_congrats_exemplars` | `"congrats"` | `"linkedin-dm"` (`DEFAULT_CHANNEL_FOR_CONGRATS`) | `None` |
| `retrieve_re_engagement_exemplars` | `"re-engagement"` | `"email"` (`DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT`) | `None` |
| `retrieve_reply_exemplars` | `"reply"` | **(operator-supplied; no module-level default)** | `None` |
| `retrieve_public_comment_exemplars` | `"public-comment"` | `"linkedin-comment"` (`DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT`) | `None` |

The shared primitive's contract is preserved unchanged. The adapters do NOT add new filters / new kwargs / new event types — they are kwarg-defaulted thin wrappers over the existing entry point.

**Operators MAY override the channel default** by passing `channel=` explicitly (e.g., cold-pitch via LinkedIn DM is a valid edge case when a prospect publishes a LinkedIn DM as their preferred channel). The default lands when the operator omits the kwarg; the override path is the per-adapter signature's `channel: str | None = None` parameter.

**Why kwarg dispatch over per-register method dispatch (rejected: per-register class methods; rejected: dispatch via a register → adapter dict; rejected: kwarg dispatch via a single function with internal switch).**

* **Kwarg dispatch is the simplest legible shape.** Each adapter is one function call; the per-register intent is in the function NAME (which any importer reads); the per-register defaults are in the kwarg defaults (which any IDE surfaces). No indirection.
* **Dispatch via `REGISTER_TO_ADAPTER = {"cold-pitch": retrieve_cold_pitch_exemplars, ...}` is rejected** because callers wanting cold-pitch should write `retrieve_cold_pitch_exemplars(...)` not `REGISTER_TO_ADAPTER["cold-pitch"](...)` — the per-call register intent is operator-deliberate at the call site. The dispatch dict re-introduces the "one giant adapter" failure mode (D192's option d) at a different layer.
* **Kwarg dispatch via a single function with internal switch is already rejected at D192-d** for the same reason — a new register requires editing the switch + per-register isolation is lost.

### D194. Per-register signature shape — symmetric across all five registers

All five adapters share the SAME keyword-only signature template (modulo the reply register's operator-deliberate channel-required asymmetry per D195):

```python
def retrieve_<register>_exemplars(
    query: str,
    *,
    k: int = DEFAULT_TOP_K,
    channel: str | None = None,
    now: datetime | None = None,
    corpus_dir: Path | None = None,
    embed_model: str | None = None,
    rebuild_on_mismatch: bool = False,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
) -> list[VoiceExemplar]: ...
```

The `channel` kwarg's `None` default resolves to the per-register `DEFAULT_CHANNEL_FOR_<REGISTER>` constant per D195 — EXCEPT for `retrieve_reply_exemplars`, where `channel=None` raises `ValueError` (the reply register's channel matches the inbound channel per the SKILL.md register table; the operator MUST supply it at adapter call time). The signature shape stays symmetric across all five registers; the runtime behavior diverges only for reply per D195.

The `register=` kwarg of the shared primitive is NOT surfaced in the adapter signature — each adapter has its register frozen in the body. The `is_substantive_reply=` kwarg is also NOT surfaced — each adapter freezes its bias per D196. Surfacing them at the adapter signature would re-introduce the dispatch-by-string failure mode (D192-d).

**Why symmetric signature with explicit reply asymmetry (rejected: separate signature per register; rejected: reply with `channel: str` required; rejected: all adapters require channel).**

* **Symmetric signature simplifies the Week 8+ SKILL.md Phase 4 per-register routing extension** — the routing code dispatches on the operator-supplied register, calls the corresponding adapter with one common set of kwargs, and inspects the result. No per-register kwarg conditionals.
* **Reply with `channel: str` required (no default)** is rejected because it BREAKS signature symmetry — the Python type checker + IDE would flag reply as structurally different. The runtime check (raise on None) preserves symmetry while enforcing operator-deliberateness. The cost is a runtime error vs a static error; we accept the runtime trade-off for symmetry + uniform per-register documentation.
* **All adapters require channel (no default for any)** is rejected because it forces operators to repeat the SKILL.md register table's channel defaults at every call site — the framework SHOULD encode the defaults so operators write the typical case briefly (`retrieve_cold_pitch_exemplars(query)`) and override only when atypical.

### D195. Per-register channel default constants pinned at module level

Four module-level constants (mirroring the discovery_lineage `LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL` per-primitive constant convention per ADR-0036 D167):

```python
DEFAULT_CHANNEL_FOR_COLD_PITCH: str = "email"
DEFAULT_CHANNEL_FOR_CONGRATS: str = "linkedin-dm"
DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT: str = "email"
DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT: str = "linkedin-comment"
```

The `retrieve_reply_exemplars` adapter has NO `DEFAULT_CHANNEL_FOR_REPLY` constant — the reply register's channel is operator-supplied per the SKILL.md's "match inbound channel" rule. Documented in the reply adapter's docstring + the cross-pillar audit's §22.

**Each constant is the single source of truth.** The SKILL.md register table (lines 339-345) MUST reference the same values; the per-week reviewer at Week 3 + future Pillar F weeks verifies the SKILL.md table matches the constants. Cross-pillar audit category 5 ("the SKILL.md Phase 4 surface stays unchanged at Week 3") is content-additive — Week 3 introduces NEW constants without changing the SKILL.md Phase 4 invocation.

**Why module-level constants (rejected: literal strings inside each adapter; rejected: a single REGISTER_DEFAULTS dict; rejected: per-register config-file values).**

* **Module-level constants are operator-readable + grep-able** — `grep DEFAULT_CHANNEL_FOR_ orchestrator/voice_corpus.py` surfaces all four defaults at once + their per-register identity.
* **Literal strings inside each adapter are rejected** — the cross-pillar audit + the SKILL.md register table + the per-week reviewer would inspect FIVE adapter bodies to verify the per-register channel; the module-level constants reduce the inspection to ONE block at the top of the module.
* **A single `REGISTER_DEFAULTS = {"cold-pitch": "email", ...}` dict is rejected** — operators expecting `DEFAULT_CHANNEL_FOR_COLD_PITCH` would search the module + miss the dict (the framework's convention is `DEFAULT_<THING>` per-primitive constants, not per-primitive dicts).
* **Per-register config-file values (`voice.cold_pitch_channel_default: email` in `~/.outreach-factory/config.yml`)** are rejected as Week 3 scope — the channel default is a framework convention (matching the SKILL.md register table), not an operator-tunable preference. Pillar F Week 6+ may surface a per-register operator override in `~/.outreach-factory/voice_thresholds.yml` IF demand materializes; Week 3 freezes the framework defaults.

### D196. Per-register `is_substantive_reply` bias convention

Each adapter freezes its `is_substantive_reply` bias at the call to `retrieve_voice_exemplars`:

| Adapter | `is_substantive_reply=` | Rationale |
|---|---|---|
| `retrieve_cold_pitch_exemplars` | `True` | Per ADR-0038 D178 + the SKILL.md's 5-touch sampling discipline — cold-pitch exemplars used for voice rewriting MUST come from PROVEN-EFFECTIVE drafts (got a substantive reply) rather than from drafts that didn't land. Cold-pitch is the highest-stakes register; biasing toward proven-effective exemplars compounds voice fidelity. |
| `retrieve_congrats_exemplars` | `None` | Congrats often DON'T get replies (the prospect read the message + moved on); requiring `is_substantive_reply=True` would surface zero exemplars for many operators. Congrats is short + register-specific; the bias relaxes. |
| `retrieve_re_engagement_exemplars` | `None` | Re-engagement reply patterns are varied; the framework doesn't bias. Future per-corpus tuning may surface a bias signal (Pillar F Week 8+ per-register threshold loader). |
| `retrieve_reply_exemplars` | `None` | Reply exemplars are by definition "got a reply" — the inbound triggered the outbound. The `is_substantive_reply` field captures something different (did the OUTBOUND get a substantive reply BACK?); no per-register bias at Week 3. |
| `retrieve_public_comment_exemplars` | `None` | Public-comment exemplars don't have a "reply" semantics in the same sense (the comment may get reactions / replies on the thread but the framework's `is_substantive_reply` field is per-DM not per-thread). No bias at Week 3. |

The bias is FROZEN at the adapter level per D192's thin-wrapper convention. Operators wanting a non-default bias call the shared primitive directly (`retrieve_voice_exemplars(query, register="cold-pitch", is_substantive_reply=None)`) — the override path is the shared primitive, not the adapter.

**Why per-register frozen biases (rejected: surface `is_substantive_reply=` on every adapter; rejected: per-register operator-tunable bias; rejected: no bias on any adapter).**

* **Per-register frozen biases encode the per-register WHY** — cold-pitch biases True because of the SKILL.md's 5-touch sampling discipline; the bias is operator-deliberate (the framework's design intent) not operator-tunable. Surfacing the kwarg on the adapter would invite per-call drift.
* **Per-register operator-tunable bias** (e.g., `voice.cold_pitch_is_substantive_reply_default: false`) is rejected as Week 3 scope — the bias is a framework convention. Pillar F Week 8+ may surface a per-register override in `~/.outreach-factory/voice_thresholds.yml` IF demand materializes.
* **No bias on any adapter** (every register defaults to `is_substantive_reply=None`) is rejected because it loses the cold-pitch SKILL.md discipline — operators using the cold-pitch adapter would silently get a mixed exemplar set; voice fidelity for the highest-stakes register would degrade.

### D197. TEST-ONLY `embed_fn` seam preservation at per-register adapters

Each per-register adapter accepts `embed_fn` per D194's symmetric signature; each adapter's docstring labels the kwarg as TEST-ONLY (mirrors `retrieve_voice_exemplars`'s docstring per ADR-0039 D188). The CLI does NOT surface a per-register subcommand at Week 3 per D198's Option-B-no-CLI-extension choice; the `embed_fn` kwarg has no operator-facing path.

**The per-week reviewer's checklist row at Week 3 + every subsequent Pillar F week:** "every new public retrieval surface (per-register adapter; future per-register CLI subcommand; future per-register convenience function) preserves the `embed_fn` kwarg as TEST-ONLY in its docstring + does NOT surface a CLI flag for it." This closes the Week 2 audit's P3-B carry-forward at the per-register adapter surface.

**Future Pillar F contributors adding new entry points MUST honor the same convention.** The `embed_fn` kwarg is reserved for tests (where the per-test `SentenceTransformer` load would otherwise cost ~1-2s × N tests). Operators tune via `embed_model` (string identifier); the framework supplies the encoder. The Pillar I CLI tooling extension per ADR-0038 §Downstream pillar impact is the structured surface for advanced encoder injection.

**Why preserve the seam as TEST-ONLY (rejected: surface `embed_fn` as a CLI flag; rejected: remove the kwarg entirely; rejected: add a per-register `embed_fn` override via `~/.outreach-factory/config.yml`).**

* **Preserving the seam as TEST-ONLY maintains the per-test cost amortization** — the test suite's per-test cost stays bounded at ~5-15ms (the deterministic embed_fn) rather than ballooning to ~1-2s per test on SentenceTransformer load.
* **Surfacing as a CLI flag** invites operators to swap encoders ad-hoc — security concern (arbitrary `embed_fn = "module:fn"` imports user-supplied code at retrieve time) + audit confusion (the per-event ledger surface couldn't recover which encoder ran for a given retrieve).
* **Removing the kwarg entirely** breaks the test suite's ~1-2s × N cost amortization.

### D198. Single-commit five-adapter ship (Option B per the Week 2 author's recommendation)

The Week 3 author ships ALL FIVE adapters in a single commit per the Pillar E Week 9-11 single-commit-four-skill-stamping precedent (ADR-0036 D169). The alternative (Option A — ship cold-pitch first; defer the other four to Weeks 4-5 per the per-week-per-adapter trajectory) is rejected for this Week 3 commit.

**Why Option B (rejected: Option A — design ADR + cold-pitch first ship; rejected: ship without the design ADR; rejected: defer all five adapters to Weeks 4-5).**

* **Option B amortizes the per-week reviewer's audit pass** — one ADR + one batch of five structurally-identical adapters + one test class with per-adapter rows + one un-skipped coherence row. The reviewer walks one commit covering the full per-register surface rather than five per-adapter commits each with the same audit pattern.
* **Option B frees Weeks 4-5 for the per-register threshold infrastructure** per ADR-0038 D184 (`voice_thresholds.example.yml` template + the per-register threshold loader at `orchestrator/voice_corpus.py` reading the threshold per-register). Without the per-register adapters landing at Week 3, Weeks 4-5 would be per-adapter ship cadence — the threshold infrastructure would slip to Weeks 6-8 + the hallucination-detection primitive's threshold dependency would shift.
* **Option B mirrors the Pillar E Week 9-11 precedent.** Pillar E shipped the discovery_lineage primitive + the four discovery skills' per-skill stamping in ONE commit via the shared `enroll_person(lineage=)` kwarg per ADR-0036 D169. Pillar F mirrors with five per-register adapters in one commit via the shared `retrieve_voice_exemplars(register=, channel=, is_substantive_reply=)` kwargs.
* **Option A (cold-pitch first; defer four)** is rejected because the five adapters are structurally identical (~30 LOC each); shipping cold-pitch in isolation creates a structural asymmetry (cold-pitch has an adapter; the other four don't) that the per-week reviewer must mentally bridge until Weeks 4-5. The asymmetry's load-bearing-cost is positive at Week 3 (the per-register coherence test row un-skips for cold-pitch only) and negative at Weeks 4-5 (the per-adapter commits each ship structural symmetry one register at a time).
* **Defer all five adapters to Weeks 4-5** is rejected because the Week 2 audit's P3-B carry-forward (the TEST-ONLY `embed_fn` preservation at future per-register adapters) needs the adapters to verify against. Deferring the adapters defers the verification.

The Option-B + Option-A trade-off matrix:

| Concern | Option A (cold-pitch first) | Option B (all five) |
|---|---|---|
| Week 3 LOC delta | ~30 LOC (one adapter) | ~150 LOC (five adapters) |
| Week 3 test delta | ~10-15 tests | ~25-35 tests |
| Week 3 audit pass | One adapter surface | Five adapter surfaces |
| Weeks 4-5 freed for | Per-adapter ship cadence (4 commits) | Threshold infrastructure |
| Coherence row un-skip | One register | All five registers |
| Per-week reviewer burden | Per-week per-adapter | One-pass full-surface |
| Symmetry at week boundary | Asymmetric (cold-pitch only) | Symmetric (all five) |

The trade-off favors Option B at Week 3 scale (five adapters ~150 LOC + one ADR ~250 LOC = ~400 LOC commit + one test class + one un-skip is within the Pillar E Week 9-11 single-commit ship norm of ~640 LOC for the lineage primitive). Future Pillar F weeks may diverge from Option B if the per-week scope ships a primitive larger than the per-register adapters (the hallucination-detection primitive at Week 6+ is ~200-400 LOC + per-Layer-trajectory; Option-B-equivalent compression there would compress too much).

## Alternatives considered

### D192-Alt1: Per-register methods on a `VoiceCorpus` class

A class wrapper carrying `retrieve_cold_pitch`, `retrieve_congrats`, etc. as methods. **Rejected** because:

* Pillar E's four primitives all ship free functions; the framework convention is consistent.
* No state to carry between calls (the shared primitive is process-cached at module level via `_MODEL_CACHE`).
* Importers would write `from orchestrator.voice_corpus import VoiceCorpus; vc = VoiceCorpus(); vc.retrieve_cold_pitch(...)` vs the simpler free-function path `from orchestrator.voice_corpus import retrieve_cold_pitch_exemplars`.
* Already rejected at ADR-0038 D181-Alt2.

### D192-Alt2: Per-register modules at `orchestrator/voice_corpus/<register>.py`

Each register gets its own module. **Rejected** because:

* Over-organization for ~30 LOC per register adapter.
* Inflates import-path surface — `from orchestrator.voice_corpus.cold_pitch import retrieve_cold_pitch_exemplars`.
* Already rejected at ADR-0038 D181-Alt1.

### D192-Alt3: One giant adapter `retrieve_for_register(register: str, ...)`

A single function with internal per-register dispatch. **Rejected** because:

* A new register requires editing the internal switch.
* Per-register testing inflates (one function with five per-register test cases vs five per-register functions with isolated tests).
* Already rejected at ADR-0038 D181-Alt3.

### D193-Alt1: Surface `register=` on the adapter signature

The adapter signature carries `register=` + the body's call to `retrieve_voice_exemplars` passes through. **Rejected** because:

* Re-introduces the per-call register selection at the wrong layer (the adapter's per-register identity should be IN THE FUNCTION NAME, not the kwarg).
* Operators wanting cold-pitch via `retrieve_cold_pitch_exemplars(query, register="cold-pitch")` is redundant + invites drift (what if `register="congrats"` is passed?).

### D193-Alt2: Dispatch via a register → adapter dict at the call site

Callers use `REGISTER_TO_ADAPTER["cold-pitch"](query, ...)` instead of `retrieve_cold_pitch_exemplars(query, ...)`. **Rejected** because:

* Reintroduces the dispatch-by-string failure mode (D192-d) at a different layer.
* The dispatch dict couples the per-register selection to a global registry — the per-call register intent should be operator-deliberate at the call site.

### D193-Alt3: Kwarg dispatch via a single function with internal switch

`retrieve_for_register(register: str, query: str, ...)` with the internal `if register == "cold-pitch": ...` switch. **Rejected** at D192-d (one giant adapter).

### D194-Alt1: Separate signature per register

Each adapter has a different signature tuned to per-register kwargs (e.g., cold-pitch's signature includes `is_substantive_reply: bool = True`; congrats's signature omits it). **Rejected** because:

* Breaks per-register signature symmetry — future per-register routing code (Week 8+ SKILL.md Phase 4 extension) would dispatch with conditional kwargs.
* Per-register documentation cannot be templated.
* Mass refactors (adding a kwarg) touch all five adapters with per-adapter conditionals.

### D194-Alt2: `retrieve_reply_exemplars(query, *, channel: str, ...)` — channel required (no default)

The reply adapter's signature differs from the others: `channel` is required (no default). **Rejected** because:

* Breaks Python type-checker uniformity — the type checker + IDE would flag reply as structurally different.
* The runtime check (raise on None) preserves symmetry while enforcing operator-deliberateness; we accept the runtime trade-off for symmetry + uniform per-register documentation.
* The reply asymmetry is documented at D194 + D195 + the adapter's docstring; the runtime check surfaces operator-readably.

### D194-Alt3: All adapters require channel (no default for any)

Every adapter's signature: `channel: str` (no default). **Rejected** because:

* Forces operators to repeat the SKILL.md register table's channel defaults at every call site.
* Breaks the framework's convention of "ship sensible defaults; allow operator override" (precedent: every cap rule's default per ADR-0007 D11; every tier auto-assignment per ADR-0035 D162).
* The per-register channel default is operator-deliberate (the SKILL.md's register table) — the framework should encode it.

### D195-Alt1: Literal strings inside each adapter

Each adapter's body carries `channel=channel if channel is not None else "email"` etc. **Rejected** because:

* The cross-pillar audit + the SKILL.md register table + the per-week reviewer would inspect FIVE adapter bodies to verify the per-register channel.
* Operators expecting to grep `DEFAULT_CHANNEL_FOR_` would miss the per-adapter literals.

### D195-Alt2: A single `REGISTER_DEFAULTS = {"cold-pitch": "email", ...}` dict

A module-level dict mapping register to default channel. **Rejected** because:

* Operators expecting `DEFAULT_CHANNEL_FOR_COLD_PITCH` would search the module + miss the dict.
* The framework's convention is per-primitive constants (e.g., `DEFAULT_EMBED_MODEL`, `DEFAULT_TOP_K`, `DEFAULT_CORPUS_DIR`), not per-primitive dicts.

### D195-Alt3: Per-register operator-tunable defaults via `~/.outreach-factory/config.yml`

`voice.cold_pitch_channel_default: email` etc. **Rejected** at Week 3 scope because:

* The channel default is a framework convention matching the SKILL.md register table, NOT an operator preference.
* Pillar F Week 6+ may surface a per-register operator override in `~/.outreach-factory/voice_thresholds.yml` IF demand materializes; Week 3 freezes the framework defaults.

### D196-Alt1: Surface `is_substantive_reply=` on every adapter

Each adapter signature includes `is_substantive_reply: bool | None = <register-default>`. **Rejected** because:

* Per-call drift hazard — operators passing `is_substantive_reply=False` to the cold-pitch adapter could silently degrade voice fidelity (the SKILL.md's 5-touch sampling discipline is operator-deliberate at the framework level).
* The override path is the shared primitive directly (`retrieve_voice_exemplars(query, register="cold-pitch", is_substantive_reply=None)`); operators wanting a non-default bias bypass the adapter intentionally.

### D196-Alt2: Per-register operator-tunable bias via `~/.outreach-factory/config.yml`

`voice.cold_pitch_is_substantive_reply_default: false` etc. **Rejected** at Week 3 scope. The bias is a framework convention. Pillar F Week 6+ may surface a per-register override if demand materializes.

### D196-Alt3: No bias on any adapter

Every register defaults to `is_substantive_reply=None`. **Rejected** because:

* Loses the cold-pitch SKILL.md discipline (the 5-touch sampling per ADR-0038 D178).
* Operators using the cold-pitch adapter would get a mixed exemplar set; voice fidelity for the highest-stakes register would degrade.

### D197-Alt1: Surface `embed_fn` as a CLI flag

Add `--embed-fn module:fn` to the (future) per-register CLI subcommand. **Rejected** because:

* Security concern — arbitrary `embed_fn` injection at retrieve time runs user-supplied code.
* Audit confusion — the per-event ledger surface couldn't recover which encoder ran for a given retrieve.
* Already rejected at ADR-0039 D188-Alt3 for the shared primitive's CLI.

### D197-Alt2: Remove the `embed_fn` kwarg from the per-register adapters

The adapters call `retrieve_voice_exemplars` WITHOUT passing `embed_fn=` through; tests using the adapters would need to monkey-patch `_MODEL_CACHE`. **Rejected** because:

* Test isolation via monkey-patching is fragile + harder to reason about than the explicit kwarg passthrough.
* The seam is TEST-ONLY (per the docstring); the kwarg's presence is bounded by the docstring's label.

### D197-Alt3: Per-register `embed_fn` config override via `~/.outreach-factory/config.yml`

`voice.cold_pitch_embed_fn: module:fn` etc. **Rejected** for the same security + audit reasons as D197-Alt1.

### D198-Alt1: Option A — design ADR + cold-pitch first ship

Ship the design ADR + the cold-pitch adapter only; defer the other four adapters to Weeks 4-5 per the per-week-per-adapter trajectory. **Rejected** at Week 3 for the reasons in D198 (asymmetry at week boundary; per-week reviewer burden; threshold infrastructure shifts to Weeks 6-8).

### D198-Alt2: Ship the adapters without the design ADR

Land the five adapters as a Week 3 commit without a separate ADR. **Rejected** because:

* The per-register adapter pattern is a load-bearing convention future Pillar F weeks build on; the ADR pins the design intent + the rejected alternatives + the §Downstream-pillar-impact + the §Existing-operator seed.
* The framework convention is one ADR per pillar-week (Pillar E Weeks 2 / 4-5 / 6-8 / 9-11 each shipped one ADR; Pillar F Weeks 1 / 2 each shipped one ADR); Week 3 mirrors with ADR-0040.

### D198-Alt3: Defer all five adapters to Weeks 4-5

Ship a design-only Week 3 commit (the ADR + the cross-pillar audit extension + zero new code); land the five adapters across Weeks 4-5. **Rejected** because:

* The Week 2 audit's P3-B carry-forward (the TEST-ONLY `embed_fn` preservation at future per-register adapters) needs the adapters to verify against. Deferring defers the verification.
* The still-skipped coherence row (`test_per_register_adapter_filters_to_correct_register`) is design-only across Weeks 1-2; un-skipping at Week 3 is the natural per-week trajectory.

## Consequences

### Positive consequences

* **The per-register surface ships in one commit, not five.** Future Pillar F weeks' commits build against the full per-register adapter surface from Week 3 onward.
* **Weeks 4-5 are freed for the per-register threshold infrastructure** per ADR-0038 D184 (`voice_thresholds.example.yml` template + the per-register threshold loader). The threshold loader's per-register surface depends on the adapter set being stable; Week 3's all-five-adapter ship enables the threshold infrastructure to land at Weeks 4-5 rather than slipping to Weeks 6-8.
* **The still-skipped coherence row un-skips with full coverage.** `tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity::test_per_register_adapter_filters_to_correct_register` un-skips at this Week 3 commit; the test verifies the cold-pitch adapter calls into the shared primitive with `register="cold-pitch"`. The four other adapters' per-register filter behavior is verified by per-adapter rows in `tests/test_voice_corpus.py::TestPerRegisterAdapters`.
* **The TEST-ONLY `embed_fn` seam preservation is reaffirmed at every per-register adapter** per the Week 2 audit's P3-B carry-forward. The per-week reviewer's checklist row at Week 3 + every subsequent Pillar F week verifies the seam stays library-only.
* **The Pillar E Week 9-11 single-commit-four-skill-stamping precedent is mirrored at Pillar F Week 3.** The framework's per-pillar-per-week ship cadence carries forward; future contributors see the precedent + apply at their pillar's analogous week.

### Negative consequences

* **Test count grows by ~25-35 (TestPerRegisterAdapters class) + 1 un-skipped coherence row = ~26-36.** Cumulative: 2789 (post-Pillar-F-Week-2) → ~2815-2825 (post-Pillar-F-Week-3). The growth is bounded; per-adapter tests are ~5 each (~25 total minimum) covering filter values + per-channel defaults + per-bias values + signature shape + TEST-ONLY embed_fn injection + cross-adapter independence.
* **`orchestrator/voice_corpus.py` grows from ~1330 LOC to ~1500-1600 LOC** (adding 5 × ~30 LOC adapter functions + 4 module-level constants + ~20 LOC of per-adapter `__all__` extension if applicable). The growth is intentional — the per-register adapter pattern lands all-at-once.
* **The reply adapter's runtime channel-required check is operator-runtime, not type-checker-static.** Operators calling `retrieve_reply_exemplars(query)` without `channel=` see a runtime ValueError. The trade-off (runtime vs static) is documented at D194 + bounded by the reply adapter's docstring naming the asymmetry.

### Risks

The asymmetric-failure-cost calculus carries:

* **The per-register default's drift risk (P2):** A future Pillar F contributor might change `DEFAULT_CHANNEL_FOR_COLD_PITCH = "email"` to a different value without updating the SKILL.md register table. **Bounded by** the cross-pillar audit's §22 extension naming the per-register defaults + the SKILL.md register table at lines 339-345 as the operator-readable source of truth + the per-week reviewer's checklist row at every Pillar F week verifying the defaults match.

* **The reply adapter's runtime check vs static signature trade-off (P3):** Operators calling `retrieve_reply_exemplars(query)` without channel see a runtime ValueError instead of a type-checker static error. **Bounded by** the adapter's docstring naming the asymmetry + the unit test `test_retrieve_reply_exemplars_requires_channel_kwarg` pinning the behavior + the SKILL.md register table's "same channel as inbound" guidance.

* **The single-commit five-adapter ship's review cost (P3):** The per-week reviewer audits five adapter surfaces in one pass; the per-week-reviewer's load grows linearly. **Bounded by** the structural identity of the adapters (~30 LOC each, same shape, same per-register defaults table) — the reviewer's audit is templated by the per-register table at D193 + the per-channel defaults at D195 + the per-bias at D196.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The per-register adapters are upstream of the ledger (they retrieve from the voice-corpus; they do NOT write to the ledger directly). The shared primitive's `voice_exemplar_retrieved` event factory at `build_voice_exemplar_retrieved_payload` continues to land in the ledger per ADR-0039 D189; the per-register adapters' callers (e.g., the SKILL.md Phase 4 at Week 8+) compose the adapter call + the factory call + the ledger append.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The per-register adapters are upstream of the dispatcher.
* **I3 — Atomic per-Person enrollment.** Preserved. Pillar F Week 3 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The per-register adapters' `channel=` kwarg defaults to the per-register channel default per D195; operators override per-call. The shared primitive's per-channel filter behavior carries over.
* **I5 — Migration framework discipline.** Preserved. Week 3 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The per-register adapters are READ-only — they do NOT emit events. The `voice_exemplar_retrieved` event class continues to stamp `channel` via the factory per ADR-0039 D189; the adapter callers pass the per-register default OR operator-supplied channel through.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. The reply adapter's runtime `channel=None` check is the per-register refuse-loud surface per D194. The shared primitive's existing refuse-loud surfaces (per-filter validation; metadata-mismatch; per-sample validation) carry over unchanged.
* **I8 — Privacy-respecting.** Preserved. The per-register adapters are read-only; they do NOT emit events. The privacy invariants on the `voice_exemplar_retrieved` event (sha256 query hash; per-exemplar id-only) continue per ADR-0039 D189 at the factory.

## Downstream pillar impact

* **Pillar F Weeks 4-5 (per-register threshold infrastructure).** The `voice_thresholds.example.yml` template + the per-register threshold loader at `orchestrator/voice_corpus.py` consume the per-register adapter surface — operators tune per-register fidelity thresholds against a stable per-register set. The Week 3 commit enables Weeks 4-5 to ship the threshold infrastructure directly rather than per-adapter ship cadence.

* **Pillar F Week 6+ (hallucination-detection primitive).** The hallucination-detection primitive's per-claim trace varies per-register (cold-pitch tolerates "you-phrase" claims more permissively than re-engagement). The per-register adapter pattern at Week 3 is the SUBSTRATE — the hallucination-detection primitive dispatches per-register via the adapter set.

* **Pillar F Week 8+ (`/draft-outreach` Phase 4 per-register routing extension).** The SKILL.md Phase 4 at Week 8+ extends with per-register routing — the per-operator register selection (via `--register`) dispatches to the corresponding adapter. The Week 3 adapter surface IS the dispatch target.

* **Pillar F Week 8+ (fidelity-scoring primitive).** The per-draft voice-fidelity score is computed per-register against the top-K corpus exemplars — the per-register adapter at the operator-supplied register surfaces the K exemplars + the fidelity-scoring primitive computes the weighted-average distance.

* **Pillar G (Observability).** Dashboards consume `voice_exemplar_retrieved` events with per-register breakdown — the per-register adapter set's stable identity makes the dashboard's per-register aggregation grain operator-deliberate. The cross-pillar audit's category 8 enforces aggregation by `register` + `channel` + per-event count; NEVER by `query_hash` or per-exemplar body.

* **Pillar H (Real-time + scale).** The per-register adapter's per-call cost is the shared primitive's per-call cost + ~negligible adapter overhead (~1-2µs per kwarg dispatch). Pillar H's scaling concerns target the shared primitive (per-corpus sparse indexing); the adapter set is content-additive against the optimization.

* **Pillar I (Multi-tenant + OSS hardening).** Pillar I CLI extensions per ADR-0038 §Downstream pillar impact list MAY extend with per-register CLI subcommands at `voice_corpus retrieve-cold-pitch --query <text>` etc. IF operator demand materializes; Week 3's `voice_corpus retrieve --register cold-pitch ...` continues to work via the existing CLI surface per ADR-0039 D188.

* **Pillar J (Compliance + audit).** Per-Person GDPR-purge of voice-corpus samples mentioning a Person continues per ADR-0038 §Downstream-pillar-impact — the per-register adapter pattern is read-only against the corpus; the purge path operates at the corpus level + does not need per-register dispatch.

## Migration / rollout

**Week 3 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 2 to Pillar F Week 3:

1. **Operator updates the framework** to Pillar F Week 3's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 3 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_voice_corpus.py tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity -v`** to verify the new per-register adapter tests + the un-skipped coherence row pass. Optional but recommended.
4. **Operator decides whether to adopt the per-register adapters.** The Week 3 adapters are LIBRARY-only at this commit — the SKILL.md Phase 4 invocation continues to use the shared primitive's CLI per ADR-0039 D191 (Path A: `python orchestrator/voice_corpus.py retrieve --register <reg> --channel <ch>`; Path B: legacy `voice_retrieve.py`). Operators writing custom scripts that consume the framework's voice-corpus surface MAY import the per-register adapters directly; the SKILL.md does NOT change at Week 3.

**Subsequent Pillar F weeks' migrations** (forward-reference): Weeks 4-5 ship the `voice_thresholds.example.yml` template + the per-register threshold loader (no migration; content-additive against the threshold yaml schema). Week 6+ ships the hallucination-detection primitive's Layer 2 + Layer 3 (no migration; content-additive). Week 8+ may ship `vault/0006_add_voice_corpus_metadata` for per-Touch-note voice-score annotations (TBD per the per-week design). Week 8+ also flips `voice.use_embedding_primitive` default from false to true + extends the SKILL.md Phase 4 with per-register routing.

## Existing-operator seed

**Pillar F Week 3's operator-side disposition is content-additive — no operator action required at Week 3.** The per-register adapters are LIBRARY-only at this commit. Operators consuming the framework via the SKILL.md continue to invoke the shared primitive's CLI per ADR-0039 D191 (the `--register <reg>` flag on `voice_corpus.py retrieve` already exists; the per-register adapter set is for FUTURE consumers — the Week 8+ SKILL.md Phase 4 per-register routing extension + the Week 6+ hallucination-detection primitive's per-register dispatch + per-operator custom scripts).

The operator-side trajectory (per-week ships across Pillar F Weeks 3-12):

* **Week 3 (this commit):** The per-register adapter set lands at `orchestrator/voice_corpus.py`. The SKILL.md Phase 4 invocation is UNCHANGED. Operators using custom scripts may import `from orchestrator.voice_corpus import retrieve_cold_pitch_exemplars` etc.; operators using the SKILL.md continue to invoke the shared primitive's CLI.
* **Weeks 4-5:** Per-register threshold infrastructure lands (`voice_thresholds.example.yml` + the per-register threshold loader). Operators tune per-register thresholds.
* **Weeks 6-10:** Hallucination-detection primitive's Layers 2-4 ship per ADR-0038 D180. SKILL.md Phase 5 / 5.5 extensions land at Weeks 6+ per the P2-B carry-forward.
* **Week 8+:** `voice.use_embedding_primitive` default flips to true + SKILL.md Phase 4 extends with per-register routing (per-operator `--register cold-pitch` etc. dispatches to the corresponding adapter via the existing CLI's `--register` flag — the per-register CLI subcommand surface (`voice_corpus retrieve-cold-pitch`) is operator-deferred to Pillar I IF demand materializes).
* **Week 12:** Binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 3:** none. The framework upgrade is read-only with respect to operator state.

**Operator action recommended at Week 3:** none beyond the per-week pytest verification. Operators MAY explore the per-register adapter set via custom scripts; the framework's SKILL.md continues to invoke the shared primitive's CLI.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D181 (per-register-symmetry-with-shared-retrieval pattern) is THE structural reference for Week 3's per-register adapters.
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive. D188 (`retrieve_voice_exemplars` per-call entry point) is the SUBSTRATE Week 3's per-register adapters call into; D186 (`VoiceExemplar` dataclass) + D189 (`build_voice_exemplar_retrieved_payload` factory) are the public surfaces adapters consume unchanged.
- **ADR-0036 (D166-D171)** — Pillar E Week 9-11 discovery_lineage stamping. D169 (single-commit four-skill stamping via shared `enroll_person(lineage=)` kwarg) is the STRUCTURAL reference for Week 3's all-five-adapter ship (Option B per D198). D170 (per-skill SKILL.md integration discipline) is the future-week reference for Week 8+ SKILL.md Phase 4 per-register routing extension.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier_assignment primitive. The operator-tunable YAML config precedent per D163 is the FUTURE-WEEK reference for the per-register threshold infrastructure landing at Weeks 4-5.
- **ADR-0033 (D149-D153)** — Pillar E Week 2 discovery_dedup primitive. The per-skill caller discipline precedent + the new event class emit-shape conventions carry forward.
- **ADR-0014 (D33)** — Pillar C foundation. The channel-on-every-event invariant extends through the per-register adapters' callers (the SKILL.md Phase 4 + the hallucination-detection primitive at Week 6+ + the fidelity-scoring primitive at Week 8+).
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §22+ extends with the Week 3 commit's audit verdict (the per-register adapter surface + the TEST-ONLY `embed_fn` seam preservation + the SKILL.md Phase 4 surface stays UNCHANGED at Week 3).
- **`.planning/HANDOFF-pillar-f-week-3.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 4 trajectory.
- **`orchestrator/voice_corpus.py`** — extended with the five per-register adapter free functions + the four `DEFAULT_CHANNEL_FOR_<REGISTER>` module constants per D195.
- **`tests/test_voice_corpus.py`** — extended with `TestPerRegisterAdapters` class (~25-35 tests covering per-register filter values + per-channel defaults + per-bias values + signature shape + TEST-ONLY embed_fn preservation + cross-adapter independence + reply adapter's channel-required runtime check).
- **`tests/test_multi_channel_coherence.py::TestVoiceCorpusFidelity::test_per_register_adapter_filters_to_correct_register`** — un-skipped at this Week 3 commit; verifies the cold-pitch adapter calls into the shared primitive with `register="cold-pitch"`.
- **`skills/draft-outreach/SKILL.md` §Phase 4** — UNCHANGED at Week 3. The shared primitive's CLI continues to serve the SKILL.md per ADR-0039 D191. The per-register routing extension is operator-deferred to Week 8+.
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 3 close summary.
- **`docs/adr/README.md`** — ADR-0040 row appended.
