# ADR-0029: Pillar D Week 6-8 — LLM fallback for long-tail categories + classifier-cap policy migration

- **Status:** Accepted
- **Date:** 2026-05-23
- **Pillar:** D (Reply + conversation handling — Week 6-8)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0025 (Pillar D Week 1) pinned the per-channel reply event-type naming (D96), the classifier output convention as a separate `reply_classified` event class (D97 — including the load-bearing legal-liability invariant `unsubscribe = classification_method == "rule"` ALWAYS), the conversation state shape (D98), the cross-pillar surface audit (D99), the auto-unsubscribe enforcement contract (D100), the exit-criterion vehicle scope (D101), AND reserved `source: "reply_classifier_llm"` for Pillar D Week 6-8's LLM fallback under I7 (cost is a first-class concern). ADR-0026 (Pillar D Week 2) shipped the rule-based classifier; D107 deferred the auto-unsubscribe handler to Week 4-5 + named Week 6-8's LLM fallback as the precision-improvement path for the long-tail categories. ADR-0027 (Pillar D Week 3) extended the classifier to all six categories via per-category pattern lists + per-channel reply detection passes. ADR-0028 (Pillar D Week 4-5) shipped the auto-unsubscribe handler (Pass M) + the conversation state machine (Pass N).

**Pillar D Week 6-8 is the LLM-fallback-for-long-tail-categories commit.** The handoff (`.planning/HANDOFF-pillar-d-week-6.md` — committed in the Week 4-5 follow-up) scopes Week 6-8 to TWO independent (but coordinated) extensions of Pillar D's substrate:

1. **The LLM fallback classifier** — a new `LLMFallbackClassifier` that wraps the existing `RuleBasedClassifier`. Dispatches the rule classifier FIRST; consults the LLM ONLY when the rule returns `category=uncategorized`. The LLM is restricted to the long-tail categories by prompt contract AND by a post-LLM refuse-loud guard (refuses if the LLM somehow returns `unsubscribe`). The fallback emits `reply_classified` events with `classification_method="llm"` + a calibrated 0.0-1.0 `confidence` from the model + emits `cost_incurred` events with `source: "reply_classifier_llm"` per ADR-0006's contract.

2. **The classifier-cap policy migration** — `policy/0007_add_reply_classifier_llm_cap`. Extends the operator's `cooldowns.yml` with a new `BudgetWindowCapRule` instance bounding the monthly LLM classifier call count. Follows the per-channel cap migration shape from Pillar C Weeks 7-11 (ADRs 0020-0024).

The seven concerns this ADR resolves:

1. **LLM provider choice + default model.** Three plausible providers — Anthropic Claude, OpenAI, open-source local. D122 picks Anthropic Claude Haiku 4.5 as the default — fast + cheap + the project's existing surface area + the rates table in `orchestrator/policy/budget.py:COST_RATES_USD` already lists it. Operators may override at construction time + a future Pillar I CLI flag.

2. **Prompt structure — one shared call vs per-category calls.** D123 picks one shared prompt that asks the LLM to classify the reply text into one of `{ooo, wrong_person, interest, rejection, uncategorized}` — SINGLE round-trip per reply. The prompt's allowed-response-set EXPLICITLY excludes `unsubscribe` per the D97 invariant carry-forward.

3. **Dispatch ordering — rule first, LLM second, but WHEN is the LLM consulted?** D124 picks the most conservative trigger: the LLM is consulted ONLY when `rule_result.category == "uncategorized"` (the rule found no match). Long-tail categories the rule MATCHED with a deterministic pattern are NOT re-classified by the LLM (the rule's `matched_pattern` is auditable; LLM-replacing-rule decisions are not). The narrow trigger is the v1 posture; the always-refine variant is reserved for a future operator-deliberate config knob.

4. **Confidence calibration — logprob vs self-reported vs benchmark.** D125 picks the LLM's self-reported `confidence` field (in the JSON response) for v1 — calibrated against the synthetic corpus + audited via Pillar G's classifier-precision/recall dashboard. The logprob-based calibration is a Pillar G observability extension (TBD); a future revision may swap in `top_logprobs`-derived calibration when Pillar G surfaces the precision-vs-self-reported-confidence curve.

5. **Cost emit-site + source name.** D126 pins `source: "reply_classifier_llm"` per ADR-0025 §I7's reservation. The emit shape matches ADR-0006's contract (`amount_usd` calculated from `COST_RATES_USD["anthropic"]` × tokens; `units = 1` per call; `model_or_endpoint = "<the model name>"`; `person_id` from the reply event; `run_id` is run-level overhead — None for v1).

6. **Classifier-cap migration shape.** D127 ships `policy/0007_add_reply_classifier_llm_cap` per the Pillar C Weeks 7-11 precedent (ADRs 0020-0024). ONE rule per migration: `reply-classifier-llm-monthly-cap` with `source: reply_classifier_llm`, `window_days: 30`, `max_units: 50` (one unit = one LLM call). The factory ships the rule as COMMENTED (matching Weeks 7-10's pattern; operators uncomment to enable).

7. **Cross-pillar audit row extension (per ADR-0025 D99).** D128 names the new emit shapes Week 6-8 introduces:
   * `reply_classified` events with `classification_method: "llm"` — new shape in the existing event class; consumers that filter on `classification_method == "rule"` (per ADR-0025 D97's invariant pin) continue to work because Pass M (auto-unsubscribe handler) reads ONLY `category=unsubscribe` events (which are STILL rule-only per D97).
   * `cost_incurred` events with `source: "reply_classifier_llm"` — new source value in the existing event class; consumers' source-filter is literal-string-protected.

Risks this ADR mitigates by design: **R012 (LLM hallucinates unsubscribe)** is reinforced — the LLM's allowed-response-set excludes `unsubscribe` by prompt contract; a post-LLM refuse-loud guard raises if the LLM somehow returns `unsubscribe`. **R013 (operator pattern-list misconfiguration)** is partially mitigated — operators whose rule list misses real long-tail signals now get LLM-classified coverage (without compromising the legal-liability path). **R014 (per-channel reply false-emit)** continues mitigated; Week 6-8's LLM fallback DOES improve precision on the long-tail (an `uncategorized` rule outcome on a benign auto-reply may be re-classified `ooo` by the LLM — improving Pillar G dashboards' signal-to-noise).

A new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`: **R016 (LLM cost runaway from inbox flood)**. A spam wave or a malformed reply pattern that surfaces hundreds of `uncategorized` rule outcomes in a single reconcile run would consume LLM budget faster than expected. Mitigations: (i) the classifier-cap migration's monthly window-cap bounds spend; (ii) operators can ship `BudgetPerRunCapRule` for per-batch defense-in-depth using the existing rule class (no new code); (iii) the LLM fallback is OPT-IN per the operator wiring path (Pass G accepts a `RuleBasedClassifier` by default; the `LLMFallbackClassifier` is constructed at the wiring site).

## Decision

### D122. LLM provider choice — Anthropic Claude Haiku 4.5 default

The LLM fallback's default model is `claude-haiku-4-5`. Pricing per `orchestrator/policy/budget.py:COST_RATES_USD["anthropic"]["claude-haiku-4-5:input_per_mtok"]` ($0.80/M input) + `claude-haiku-4-5:output_per_mtok` ($4.00/M output) — both rates as of the table's 2026-05-18 review.

**Why Haiku 4.5 (not Sonnet 4.6 or Opus 4.7 or a different provider):**

* **Classification is a Haiku-class task.** The long-tail categories (`ooo`, `wrong_person`, `interest`, `rejection`, `uncategorized`) are short-text classification with clear semantic boundaries. Haiku's accuracy on this kind of task is well-documented as sufficient. The rule-based classifier already handles the high-precision subset (deterministic patterns); the LLM extends coverage on the more-ambiguous text patterns the rule misses. Sonnet's marginal precision improvement is not worth ~10× the cost for v1.
* **Cost is bounded by the per-call shape.** Each call is ~500 input tokens (reply body + classification prompt) + ~50 output tokens (a JSON response with `category` + `confidence` + brief `rationale`). At Haiku pricing, one call costs ~$0.0006 (less than a tenth of a cent). At Yang's expected ~30 long-tail uncategorized replies/month, the monthly cost is ~$0.02 — essentially free. Sonnet would push this to ~$0.20/month (still cheap but 10× more); Opus to ~$1.50/month.
* **Latency matters for the dispatcher.** The auto-unsubscribe handler (Pass M) ships with a 60-second SLA per PILLAR-PLAN §2 — but Pass G is the prerequisite. Haiku's ~1-2s per-call latency vs Sonnet's ~3-5s vs Opus's ~10s makes Pass G's total runtime acceptable even under inbox flood (~30 calls × 2s = 1 minute additional Pass G runtime; Pass M follows + writes within the SLA).
* **The provider surface is already in the project's pricing table.** `COST_RATES_USD["anthropic"]` lists Haiku/Sonnet/Opus rates for input + output tokens; no new pricing constant required. Adding OpenAI would mean extending the rates table + the cost-event source-name set + the operator-readable provider-choice surface. Project scope per ADR-0006 is "Anthropic-first for now"; Pillar I OSS bring-up is the right venue to revisit if the operator surface demands provider flexibility.

**Operator override path.** The `LLMFallbackClassifier` constructor accepts a `LLMClient` Protocol implementation; production callers (the future Pillar I CLI) construct an `AnthropicClient(model="claude-haiku-4-5")` instance + pass it. Operators wanting Sonnet override at construction time. A future Pillar I CLI flag (`--llm-model <name>`) is the natural surface; v1 has no CLI flag because Pass G's wiring constructs the classifier server-side.

**Rejected D122 alternatives:**

* **Default to Sonnet 4.6 for higher precision.** **Rejected** because:
  - Cost is ~10× Haiku at this scale (still cheap but unnecessary for classification).
  - Latency is ~3× Haiku — Pass G runtime under inbox flood gets uncomfortable (~5 minutes for 30 calls).
  - Operators wanting Sonnet override at construction; the default-to-cheap-fast posture matches Pillar A's asymmetric-failure-cost calculus (cheap-and-fast-and-good-enough beats expensive-and-slow-and-marginally-better for operations that run on every reply).

* **Default to Opus 4.7 (the project's primary model surface).** **Rejected** because:
  - Cost is ~100× Haiku — at scale (a future operator with thousands of replies/month) this becomes prohibitive.
  - Latency is ~10× Haiku — Pass G runtime is unacceptable.
  - Opus's marginal accuracy improvement on classification doesn't justify the cost/latency penalty. The asymmetric-failure-cost calculus inverts: a false-positive Opus classification of `interest` is no better than a false-positive Haiku classification (both bypass to the same human-in-the-loop disposition).

* **Default to a local open-source model (e.g., Llama 3.1 8B Instruct).** **Rejected** because:
  - Zero per-call cost is appealing but requires operator-deliberate infrastructure (a local inference server, GPU resources, model file management). The framework's "works out of the box" posture inherits Pillar C's CLI ergonomics — operators get value without infra setup.
  - The project's existing surface area is Anthropic-first; introducing a local-model path duplicates the inference surface for unclear v1 benefit.
  - Pillar I OSS bring-up is the right venue to add provider flexibility (operators with privacy / cost / latency constraints may want local inference). Until then, the Anthropic default keeps the surface uniform with the project's other LLM call sites.

* **No default — REQUIRE operators to choose a provider at construction.** **Rejected** because:
  - The framework's default-with-override posture (per ADR-0026 D103's factory-template-with-operator-tunable convention) is the load-bearing operator-onboarding shape. Requiring a choice at construction breaks the "drop in the LLM client and it just works" experience.
  - The choice is reversible — operators can swap providers without re-running migrations or re-classifying historical events (the `reply_classified` events Week 6-8 emits carry `_emitted_by` + `model_or_endpoint` for forward attribution).

### D123. Prompt structure — one shared call classifying into the long-tail set

The LLM fallback uses ONE shared prompt per call. The prompt instructs the LLM to classify the reply text into one of `{ooo, wrong_person, interest, rejection, uncategorized}` and respond with a JSON object: `{"category": "<one of the allowed>", "confidence": <0.0-1.0>, "rationale": "<one short sentence>"}`. The prompt's allowed-response-set EXPLICITLY excludes `unsubscribe` — D97's invariant carry-forward.

**The prompt template (load-bearing — pinned in `orchestrator/reply_classifier_llm.py`):**

```text
You are a reply-classification assistant. Classify the following reply
text into EXACTLY ONE of these categories:

* ooo — auto-reply indicating the recipient is out of office
* wrong_person — recipient says you have the wrong contact + redirects
* interest — recipient expresses interest in continuing the conversation
* rejection — recipient declines (not interested / no thanks / already-with-competitor)
* uncategorized — none of the above; the reply doesn't fit a known category

DO NOT classify as "unsubscribe" — that category is handled by a
separate rule-based path and the LLM is never consulted for it
(legal-liability invariant per the framework's PILLAR-PLAN §5).

Reply text:
---
{reply_text}
---

Respond with ONLY a JSON object on a single line, no markdown fences:
{"category": "<one of: ooo, wrong_person, interest, rejection, uncategorized>",
 "confidence": <a float between 0.0 and 1.0>,
 "rationale": "<one short sentence explaining the choice>"}
```

The single-prompt shape bounds the per-call cost (one round-trip per reply) + matches the rule-based classifier's "single decision per call" shape (Pass G dispatches one rule classification per reply; the LLM fallback inherits the same dispatch granularity).

**Five-layer defense-in-depth carry-forward of the D97 invariant.** The "unsubscribe path is rule-only" rule is enforced at FIVE INDEPENDENT layers (the per-week review's P2-D finding reconciled the count across the module docstring + this ADR; the canonical enumeration is now used consistently):

1. **Dispatch short-circuit.** `LLMFallbackClassifier.classify` returns the rule result unchanged when `rule_result.category == "unsubscribe"` — the LLM is never called for the unsubscribe path. Per D124's dispatch ordering.
2. **Prompt exclusion.** The prompt's allowed-response-set excludes `unsubscribe`; the prompt body names the legal-liability justification inline.
3. **Parse-layer check.** `_parse_llm_response_text` rejects any response whose `category` is not in `_ALLOWED_LLM_CATEGORIES` (which excludes `unsubscribe`) by raising `LLMResponseParseError` BEFORE the `LLMResponse` dataclass is constructed.
4. **Post-LLM refuse-loud guard.** A guard in `LLMFallbackClassifier.classify` raises `LLMRefusalError` if the LLM somehow returns `unsubscribe` — defense against a future adapter that bypasses `_parse_llm_response_text` by constructing `LLMResponse` directly (e.g., via an SDK-native structured-output surface).
5. **Construction-time backstop.** `ClassifierResult.__post_init__` (shipped in Week 2 per ADR-0026) rejects `(category="unsubscribe", classification_method="llm")` at construction time. Inherited; defense against a hypothetical reflexive construction-without-parse code path.

The original rule-classifier `uncategorized` result is preserved in the audit trail when any of layers 3 / 4 / 5 fire (Pass G records the error + skips the event without emitting a misclassified `reply_classified` event). Layer 1 + 2 prevent the LLM from being called at all for unsubscribe; layers 3-5 catch the case where the LLM was called but returned a category that violates the invariant.

**Rejected D123 alternatives:**

* **Per-category prompts: five separate LLM calls per reply, one per long-tail category.** Each call asks "is this reply an `ooo` reply?" (yes/no with confidence); the dispatcher picks the highest-confidence yes. **Rejected** because:
  - Five round-trips per reply ≈ 5× the cost + 5× the latency. Even at Haiku's low rates, scale-up to 100+ replies/month makes the cost/latency comparison painful.
  - Per-category prompts could theoretically increase precision via specialization, but the empirical data on this kind of LLM-classification task suggests one-shot multi-class is comparable or better (the model's attention budget is the same; per-category prompts duplicate the reply text without adding semantic context).
  - The framework's `DISPATCH_PRIORITY` already pins the priority order across categories; per-category prompts would either: (a) need a dispatcher to resolve competing yes responses (adds complexity matching D110's priority order); or (b) introduce a different priority resolution that diverges from the rule classifier's behavior (operator-confusing — same reply gets a different category under rule-only vs LLM-fallback).

* **Multi-stage: one prompt to detect category presence, second to refine.** A first prompt asks "does this reply fit any of the long-tail categories?" (yes/no); a second prompt (only on yes) does the multi-class classification. **Rejected** because:
  - Two round-trips per reply when the answer is "yes" ≈ 2× cost + 2× latency. The first-stage "no" path is the same as the rule-classifier's `uncategorized` fallback — no benefit over the single-stage shape that already returns `uncategorized` directly.
  - The single-stage prompt's `uncategorized` option ALREADY covers the "doesn't fit any long-tail" case. The multi-stage shape is over-engineered for the same outcome.

* **JSON-schema-strict response via Anthropic's `tools` API.** Use Claude's tool-use surface to force the response into a typed schema. **Rejected for v1** because:
  - Tool-use adds tokens (the schema definition is part of the prompt context) + adds complexity (the SDK call pattern differs from text generation).
  - JSON-parsing the text response is a 5-line operation; the structured-output benefit is marginal at this scale.
  - A future Pillar I revision MAY swap to tool-use if the parse error rate is non-trivial in production (Pillar G observability surfaces this — the `LLMResponseParseError` emit is already shaped as a recorded error in Pass G).

* **Free-form prompt + post-LLM keyword extraction.** Let the LLM respond in natural language; parse the category from keywords in the response. **Rejected** because:
  - Brittle (the LLM's phrasing varies; keyword-extraction reintroduces the rule-classification problem inside the parser).
  - Defeats the structured-confidence-field shape D125 needs.
  - The framework's existing rule-classifier pattern (deterministic parse) + LLM-extending-coverage shape is the right grain; mixing free-form natural language back into the parse path loses the audit-trail clarity the structured response provides.

### D124. Rule-then-LLM dispatch ordering — LLM only on `uncategorized`

The LLM is consulted ONLY when `rule_classifier.classify(reply) == ClassifierResult(category="uncategorized", ...)`. Long-tail categories the rule already matched (`ooo`/`wrong_person`/`interest`/`rejection`) are returned as-is — the LLM does NOT re-classify them.

**The dispatch logic (pinned in `orchestrator/reply_classifier_llm.py:LLMFallbackClassifier.classify`):**

```python
def classify(self, reply_event: dict) -> ClassifierResult:
    rule_result = self._rule_classifier.classify(reply_event)
    if rule_result.category == "unsubscribe":
        # D97 invariant — the LLM is NEVER consulted for unsubscribe.
        return rule_result
    if rule_result.category != "uncategorized":
        # The rule matched a long-tail pattern with confidence 1.0;
        # the LLM has no audit-trail advantage over the deterministic
        # match. Return as-is.
        return rule_result
    # Rule returned uncategorized → consult the LLM.
    return self._llm_classify(reply_event)
```

**Why "only on uncategorized" (not "always re-classify long-tail with LLM"):**

* **Auditability.** The rule classifier's `matched_pattern` field on every long-tail result is an operator-inspectable trail ("the rule fired on `\bout of office\b`"). An LLM re-classification replaces this with a self-reported `rationale` field — less precise audit surface. Operators tuning the rule list need the rule's deterministic match to surface; LLM-replacing-rule decisions obscure the tuning signal.
* **The asymmetric-failure-cost calculus.** A rule false-positive (e.g., `ooo` rule fires on a reply that isn't actually OOO) is operator-fixable (tune the rule). An LLM false-positive is harder to remediate (the operator has no equivalent of "tune the regex" for an LLM). Starting narrow (LLM extends coverage; doesn't replace rule decisions) preserves operator agency.
* **Cost.** The "uncategorized only" trigger limits LLM calls to the subset of replies the rule didn't match. At Yang's expected ~30 uncategorized replies/month, the cost is ~$0.02 (~30 calls × $0.0006). The "always re-classify long-tail" variant would push call count to all ~100 replies/month — 3× the cost for marginal benefit on patterns the rule already correctly handles.
* **Backward compatibility.** Operators currently using the rule-only classifier (Pillar D Weeks 2-5 deployment) get drop-in compatibility — wrapping their `RuleBasedClassifier` in `LLMFallbackClassifier` extends coverage without changing existing classifications.

**The always-refine alternative is deferred.** A future operator-deliberate config knob (`LLMFallbackClassifier(rule_classifier, llm_client, also_refine=True)`) could opt into LLM refinement of long-tail rule matches. Reserved for a future Pillar D week if operator feedback surfaces a need; not shipped Week 6-8.

**Rejected D124 alternatives:**

* **Always consult the LLM for every reply (rule classifier is the "before" check, LLM is the "after" decision).** **Rejected** because:
  - Violates the operator-tunability rationale above (LLM-replacing-rule decisions obscure tuning).
  - 3-5× the cost without proportional precision benefit on patterns the rule already handles.
  - The rule classifier's deterministic `confidence: 1.0` ALREADY signals high precision; the LLM's self-reported confidence is at best comparable + at worst confusing (which is the source of truth when rule says 1.0 and LLM says 0.7?).

* **Consult the LLM when the rule's `matched_pattern` is in an operator-tunable "low-confidence patterns" list.** Operators tag certain patterns (e.g., "the OOO regex `\bout\b`" — possibly false-positive heavy) as low-confidence; the LLM re-classifies those rule hits. **Rejected for v1** because:
  - Adds operator-facing complexity (a new YAML field `low_confidence: true` per pattern) without clear evidence of need.
  - The operator's natural escape valve is already "edit the rule list" — if a pattern is low-confidence, tune it OR remove it. The LLM second-opinion shape is a less direct fix.
  - Pillar G observability surfaces per-pattern precision/recall after deployment; THAT data informs operator decisions on which patterns to tune. Shipping low-confidence tagging before the observability data exists is premature.

* **Consult the LLM only on a probability-weighted sample of long-tail hits (e.g., 10% sampling).** Random-sample some rule hits for LLM re-classification; use the sample as a precision check on the rule. **Rejected** because:
  - The sampling shape is a TESTING/OBSERVABILITY pattern, not a classification dispatch shape. Pillar G's classifier-precision/recall dashboard is the natural home (run an offline replay against historical events; compare rule vs LLM outcomes; surface precision drift).
  - Random LLM re-classification of rule hits introduces non-determinism — the same reply gets a different category on different reconcile runs (which sample bucket it landed in). The framework's idempotence contract (per ADR-0026 D104) is incompatible.

### D125. Confidence calibration — self-reported from the LLM (Pillar G observability validates)

The LLM's response includes a `confidence` field — a self-reported 0.0-1.0 score. The `ClassifierResult.confidence` for LLM-emitted events carries this value directly.

**Why self-reported (not logprob, not benchmark-derived):**

* **Logprob-based calibration requires `top_logprobs` access.** Anthropic's Messages API doesn't expose token-level logprobs (as of the 2026-05-23 SDK shape Yang has access to). A future SDK feature MAY ship this; v1 ships against what's available today.
* **Benchmark-derived calibration requires a labeled corpus.** The Pillar D Week 12 exit-criterion test ships a 100-message synthetic inbox benchmark. That benchmark IS the future calibration substrate, but it's not landing until Week 12. Building a calibration table from synthetic data this Week 6-8 would prejudge the benchmark.
* **Self-reported confidence is the simplest shape that works.** Claude has been trained to estimate confidence; the response field provides one. For v1 the field surfaces in `reply_classified` events; Pillar G dashboards aggregate it; operators tuning the LLM dispatch decisions (e.g., "always treat LLM results <0.5 as uncategorized regardless of the model's answer") consume the field via their dashboards.
* **The exit-criterion test will measure precision/recall by self-reported confidence bucket.** Per ADR-0025 D101 — the binding `test_100_message_synthetic_inbox_classifier_benchmark` (un-skips Week 12) measures classifier precision/recall across categories. The Pillar G classifier dashboard surfaces the same per-bucket data continuously. Calibration adjustments land at the dashboard layer (operator-tunable thresholds) rather than at the LLM-call layer.

**The Pillar G observability extension (TBD, forward-reference).** When Pillar G ships its classifier-precision/recall dashboard, the per-bucket precision data informs a calibration adjustment. A future ADR may ship a calibration table mapping self-reported confidence to empirical precision (e.g., "the LLM's 0.9 self-reported confidence empirically corresponds to 0.85 precision; reweight accordingly").

**Rejected D125 alternatives:**

* **Use Anthropic's `top_logprobs` field for token-level confidence.** **Rejected for v1** because the field is not available on the Messages API as of the SDK shape. Pillar I revisit if the SDK feature ships.

* **Calibrate against a benchmark BEFORE shipping.** Build a labeled set of 50-100 replies; tune the LLM's prompt to optimize precision/recall on that set; ship calibration constants alongside the classifier. **Rejected** because:
  - The Pillar D Week 12 exit-criterion benchmark IS the right venue for benchmark-based calibration; building a separate Week-6-8 benchmark would prejudge the exit-gate work.
  - Calibration constants tend to drift (a future model version's confidence distribution differs from today's); a fixed table becomes stale faster than the framework can re-tune.

* **Ignore the confidence field entirely; treat every LLM result as confidence 1.0.** **Rejected** because:
  - The classifier output's `confidence` field is the operator-visible signal for "should I trust this classification?" Treating LLM 1.0 as equivalent to rule 1.0 collapses an important distinction (rule = deterministic match; LLM = probabilistic estimate).
  - Pillar G's dashboards depend on the field for per-bucket precision/recall analysis.

* **Map the self-reported confidence to discrete buckets (high/medium/low) instead of a continuous value.** **Rejected** because:
  - The continuous value preserves more information for downstream consumers + matches the rule classifier's 1.0 / 0.0 discrete-but-extreme shape (a continuous LLM confidence aggregates naturally alongside rule 1.0).
  - Bucketing is an operator-side concern (a dashboard may render buckets); the framework emits the raw signal.

### D126. Cost emit-site + source name — `reply_classifier_llm`

Every successful LLM call emits one `cost_incurred` event:

```python
{
    "type": "cost_incurred",
    "source": "reply_classifier_llm",  # per ADR-0025 §I7 reservation
    "amount_usd": <calculated from input_tokens + output_tokens × COST_RATES_USD["anthropic"][<model>:input_per_mtok | :output_per_mtok]>,
    "units": 1,  # one call = one unit (matches Reoon/Gmail convention)
    "model_or_endpoint": <the model name, e.g. "claude-haiku-4-5">,
    "person_id": <from the reply event; per-prospect attribution>,
    "run_id": None,  # not surfaced through the classifier call path in v1
}
```

**Emit-site location — the `LLMFallbackClassifier` itself, not Pass G.** The classifier holds a reference to the ledger (injected at construction time); after a successful LLM call, the classifier emits the cost event via `led.append(...)`. The cost event lands in the ledger BEFORE the `reply_classified` event Pass G emits (the classifier's `classify()` returns to Pass G after the cost emit; Pass G then writes the classified event). Failed LLM calls do NOT emit cost — matches ADR-0006's per-vendor pricing-convention ("we don't pay for failures" for Anthropic per the COST_RATES_USD docstring).

**Per-prospect attribution.** The reply event Pass G dispatches carries `person_id`; the classifier propagates it to the cost event. The `BudgetPerPersonCapRule` (ADR-0006) can consume `reply_classifier_llm` source events with per-person scope — an operator wanting to bound LLM spend per prospect (defense against pattern-rich inbox flood from one sender) configures the rule directly without engine change.

**Run-level attribution deferred.** Pass G's call path doesn't currently surface `run_id` through to the classifier. Pillar I CLI may extend (operator-deliberate per-run cost reporting); v1 emits `run_id: None` matching the historical pattern for non-batched classifier calls.

**Why the ledger emit is non-atomic with the LLM call.** A crash between the LLM SDK call and the ledger append leaves the framework with an unrecorded cost (operator under-reports their spend). The asymmetric-failure-cost calculus per PILLAR-PLAN §0 biases toward under-report-spend > miss-classification-result: the classification result is the value Pass G needs to emit; the cost event is observability. Wrapping the two in a transaction journal would over-engineer for the v1 scope. Pillar G observability surfaces missing-cost events post-hoc (`reply_classified` events with `classification_method="llm"` outnumber `cost_incurred` events with `source="reply_classifier_llm"` → operator sees the drift in their dashboard).

**Rejected D126 alternatives:**

* **Emit the cost event from Pass G (not from the classifier).** Pass G calls the classifier; after the classifier returns the result, Pass G emits the cost event in addition to the `reply_classified` event. **Rejected** because:
  - Pass G doesn't know the LLM's token usage (the classifier holds the API response). Surfacing the token counts through `ClassifierResult` requires extending the dataclass + the wire shape across rule + LLM paths (rule has no tokens).
  - The classifier IS the call site that incurred the cost; the emit-site should match the cost site per ADR-0006 §"Emit at the API-call SUCCESS path only" convention.

* **Emit the cost event from the LLM client implementation (one level deeper than the classifier).** The `LLMClient` Protocol implementer (e.g., `AnthropicClient`) emits the cost; the classifier just calls + returns the response. **Rejected** because:
  - The classifier coordinates the prompt structure + the per-prospect attribution; the LLM client is a thin SDK wrapper. Pushing the cost emit into the client requires the client to know about ledger + reply context (cross-concern coupling).
  - The Protocol surface stays simple (just `classify_text(text) -> LLMResponse`); the classifier handles the framework-side attribution + ledger.

* **Don't emit cost events at all; rely on operator-side Anthropic billing dashboard.** **Rejected** because:
  - The `BudgetWindowCapRule` consumes `cost_incurred` events from the ledger; without the emit, the cap can't enforce.
  - ADR-0006's first-class-cost convention is the framework's operator-facing answer to "what did we spend on what?". Skipping the LLM cost emits violates I7.

* **Emit cost events but skip `amount_usd` (units-only mode).** Set `amount_usd: 0.0` per event + count via `units`. **Rejected** because:
  - The `BudgetWindowCapRule.max_usd` mode needs the amount field. Operators wanting a $5/month LLM cap would have to do the math (calls × per-call rate) instead of typing `max_usd: 5.0`.
  - The pricing table already exists per ADR-0006; using it at the emit-site is one math operation.

### D127. Classifier-cap migration shape — `policy/0007_add_reply_classifier_llm_cap`

The migration ships ONE rule per the Pillar C Weeks 7-11 precedent (ADRs 0020-0024). Mirrors Week 7's `policy/0002_add_li_invite_weekly_cap` shape MOST CLOSELY (single-rule per migration; commented factory rule; same rule class `budget.window-cap`); diverges from Week 11's `policy/0006` (TWO rules; different rule class).

**The rule block (pinned in `orchestrator/migrations/policy/migration_0007_add_reply_classifier_llm_cap.py:RULE_BLOCK_TEXT`):**

```yaml
- name: reply-classifier-llm-monthly-cap
  type: budget.window-cap
  source: reply_classifier_llm
  window_days: 30
  max_units: 50
  reason: "Reply-classifier LLM monthly call cap (≈$0.03/month at Haiku 4.5 rates; operator-tunable in cooldowns.yml)"
```

**Why `max_units: 50` (calibrated against expected reply volume):**

* Yang's current cadence: ~100 replies/month inbound. Roughly 20-30% miss the rule-based classifier's pattern set → fall to `uncategorized` → trigger the LLM fallback. That's ~20-30 LLM calls/month under normal operation.
* `max_units: 50` is a 1.5-2.5× safety margin over normal cadence; catches a runaway-loop or inbox-flood scenario before it exhausts the budget.
* At Haiku 4.5 rates (~$0.0006 per call), 50 calls/month ≈ $0.03/month — the cap's enforcement surfaces operator visibility into LLM spend, not budget protection per se.
* Operators with higher reply volume tune up (e.g., `max_units: 500` for ~1000 replies/month → ~$0.30/month). Operators in the warm-up phase tune down.

**Why monthly window (`window_days: 30`) — not daily, not weekly, not per-run:**

* The LLM cost is operator-budget-aggregated (operators budget in monthly terms, not daily). Monthly window matches the operator's mental model.
* Daily-window (`window_hours: 24`) would over-fire during high-traffic days (an inbox flood concentrated in one day shouldn't trip the cap if monthly total is fine).
* Weekly-window (`window_days: 7`) is operator-OK but less natural than monthly for spend tracking. The Pillar C per-channel caps used weekly because LinkedIn / Twitter / Calendar enforce weekly platform-side limits; the LLM has no platform-side limit, so the cap's role is operator-side spend bounding.
* Per-run cap (`BudgetPerRunCapRule`) is a defense-in-depth shape operators can add ALONGSIDE this monthly cap; this migration ships the monthly cap as the primary; operators wanting per-run defense ship the rule separately (no new code needed — the `BudgetPerRunCapRule` class already exists).

**Why `units` not `usd` mode:**

* Operators reading the cap field see "50 calls/month" — easier mental model than "$0.03/month" (small dollar amounts are hard to reason about; call counts are tangible).
* Operators wanting $-based caps configure with `max_usd: <amount>` mode by overriding the rule field; the rule class supports both modes per ADR-0006.
* The factory's commented-rule convention (per Pillar C Weeks 7-10) puts the units-mode shape as the default; operators uncomment + customize.

**Why commented factory rule (not active):**

* Matches Pillar C Weeks 7-10's pattern (Rules 12b/12c/12d/12e are all commented in `config-template/cooldowns.example.yml`). Operators uncomment when they want the cap active.
* The LLM fallback is opt-in at the wiring layer too (Pass G accepts a `RuleBasedClassifier` by default; the `LLMFallbackClassifier` is constructed at the wiring site). The cap's commented-by-default posture matches the LLM fallback's opt-in posture — operators who don't enable the LLM fallback don't see the cap fire.
* The migration backfills the rule shape into operator `cooldowns.yml` files so an operator who later opts into the LLM fallback has the cap shape ready to uncomment.

**Existing-operator seed (operators with pre-Pillar-D-Week-6-8 `cooldowns.yml`):**

* **Shape A — rule already canonical-named.** Some operator with a hand-tuned `cooldowns.yml` already has a `reply-classifier-llm-monthly-cap` rule (unlikely but possible — they could have read the handoff + added it manually). Migration skips per name-match idempotence.
* **Shape B — rule renamed (e.g., `my-llm-budget`).** Operator's tuned version stays; migration adds the canonical-named rule alongside. Operator dedupes if they want.
* **Shape new-operator — no rule present.** Migration appends the canonical rule.

The seed shapes are simpler than Week 11's four-shape catalog because this migration ships ONE rule (Week 11 ships two with bidirectional symmetry concerns).

**Rejected D127 alternatives:**

* **Ship the cap as ACTIVE (uncommented) in the factory + migration.** **Rejected** because:
  - The LLM fallback is opt-in at the wiring layer; the cap should match the opt-in posture. An active cap that never fires (because no LLM emits cost events) is dead policy that confuses operators reading their cooldowns.yml.
  - Mirrors Pillar C Weeks 7-10's commented-factory pattern; consistency favors the precedent.

* **Ship TWO rules: monthly cap + per-run cap (defense-in-depth).** **Rejected** because:
  - The per-run cap is operator-deliberate; defense-in-depth is a posture some operators want + others don't. Ship ONE primary cap; operators add per-run cap manually via `BudgetPerRunCapRule` (no migration needed — the rule class already exists).
  - Two-rule migrations (per ADR-0024 D-N1) are appropriate for bidirectional structural pairs; LLM caps are not structurally paired.

* **Per-source pricing emit (units = tokens, not calls).** Track tokens directly + cap on `max_units: 500000` (~50 calls × 10K tokens). **Rejected** because:
  - Token counts vary per call (some replies are longer; some prompts are tuned); the per-call shape gives operators a more stable mental model.
  - Per-call counting matches Reoon / Gmail / LinkedIn conventions in the existing rates table (`units: 1` per operation).
  - Operators wanting dollar caps configure `max_usd: <amount>` mode; the units mode is for "I want to cap calls".

* **No migration — operators configure the cap manually in their cooldowns.yml.** **Rejected** because:
  - The migration framework's role is to ensure operator policy files converge to the framework's expected shape. Operators who pull the Week 6-8 commit + enable the LLM fallback shouldn't have to know about a separate "go edit your cooldowns.yml" step — the migration handles it.
  - The Pillar C Weeks 7-11 precedent is per-week policy migrations for per-channel caps; Pillar D Week 6-8 inherits the pattern.

### D128. Cross-pillar audit row extension

`.planning/REVIEW-pillar-d-surface-audit.md` is extended with a Week 6-8 audit extension section covering:

* **`reply_classified` events with `classification_method: "llm"` — new shape.** Existing consumers:
  - **Pass M (auto-unsubscribe handler):** reads ONLY `category=unsubscribe` events. The LLM NEVER classifies as `unsubscribe` (D97 + D123 prompt contract + D124 dispatch guard). Pass M's filter is `category == "unsubscribe"` — literal-string-protected; the new `classification_method: "llm"` shape never matches because no LLM-emitted event carries `category=unsubscribe`. **Verdict: closed by construction.**
  - **Pass N (conversation state machine):** consumes the category to drive state transitions. The long-tail categories the LLM emits (`interest`, `ooo`, `wrong_person`, `rejection`, `uncategorized`) already have transition mappings per ADR-0028 D119; the LLM-emitted events drive the same transitions. **Verdict: closed by design — the state machine doesn't read `classification_method`.**
  - **Pass C `conversation_status:` heal:** consumes Pass N's derived state. Same as Pass N — `classification_method` is not read. **Verdict: closed by design.**
  - **Pass G's idempotence index:** keyed on `(reply_message_id, channel)` per ADR-0026 D104. Index population walks `reply_classified` events of any classification_method. **Verdict: closed by design — index treats rule + LLM events equivalently for idempotence.**
  - **Pillar G dashboards (planned):** consume `classification_method` to break down precision/recall by method. The Week 6-8 extension EXPANDS the dashboard surface; this is BY-DESIGN broadening, not regression. **Verdict: by-design.**

* **`cost_incurred` events with `source: "reply_classifier_llm"` — new source value.** Existing consumers:
  - **`BudgetWindowCapRule` / `BudgetPerPersonCapRule` / `BudgetPerRunCapRule`:** all filter by `source` field. Operators with no rule for `reply_classifier_llm` source see the events but no rule fires — same shape as Reoon/Gmail/Apollo source events before per-source caps existed. **Verdict: closed by design — operator-tunable rule activation.**
  - **The pricing table (`COST_RATES_USD`):** has anthropic entries; the LLM cost computation uses them. No new entry needed. **Verdict: pre-existing surface, no broadening.**
  - **The classifier-cap migration (D127):** the migration ships the operator-tunable rule shape that consumes the new source. **Verdict: by-design coupling.**

**Verdict per the D99 audit pattern: zero new P1 latent-bug patterns; zero new P2; zero new P3.** The new event shapes are either:
* closed-by-construction (Pass M's `category=unsubscribe` filter; the LLM never emits this);
* closed-by-design (Pass N + Pass C + Pass G index treat method-agnostic);
* by-design broadening (Pillar G dashboards EXPAND by intent; the classifier-cap migration's consumption is operator-tunable).

R016 (LLM cost runaway from inbox flood) is the audit's surfaced risk; mitigations land at the migration + the operator's manual `BudgetPerRunCapRule` opt-in.

**The audit document gains a new section `§Week 6-8 audit extension (ADR-0029 D128)` walking every consumer + the verdict per consumer.** Per ADR-0025 D99's row-by-row discipline.

## Alternatives considered

Above, per-decision §"Rejected DXXX-AltN" subsections enumerate the rejected alternatives per decision. The cross-cutting alternatives:

### D-Alt1: Defer LLM fallback to Pillar I OSS bring-up — Week 6-8 ships nothing

Skip Week 6-8 entirely; Pillar D's "stable" flip waits for Pillar I to ship the LLM fallback. **Rejected** because:
* Per PILLAR-PLAN §2 Pillar D's binding text — the exit criterion is "100-message synthetic inbox classifier benchmark with documented rule precision/recall." The benchmark is Week 12; the LLM fallback IS the precision-improvement substrate that the benchmark measures. Deferring the LLM fallback to Pillar I would gut the benchmark.
* The classifier-cap policy migration is the natural Week 6-8 deliverable (Pillar C Weeks 7-11's per-channel cap migration arc inherited the per-week cadence; Pillar D Week 6-8 continues the pattern with the classifier cap).
* The per-week-handoff trajectory in `.planning/HANDOFF-pillar-d-week-6.md` explicitly scopes Week 6-8 to LLM fallback + cap migration; deferring means rewriting the trajectory.

### D-Alt2: Ship the LLM fallback but skip the cap migration (one Week 6-8 ADR per artifact)

Two ADRs land Week 6-8: ADR-0029 for the LLM fallback + ADR-0030 for the cap migration. **Rejected** because:
* The two artifacts are inherently coordinated (the cap consumes the LLM's cost events; the LLM exists to be capped). Splitting into two ADRs would force a forward-reference dance.
* The Pillar C precedent (ADRs 0020-0024 — five per-channel cap migrations in five weeks; one ADR per migration) split BY-WEEK, not by artifact-within-a-week. Week 6-8 is one week; one ADR.
* The single-ADR shape matches Pillar D's Week-N convention (ADR-0025/0026/0027/0028 each cover their week's full scope).

### D-Alt3: Replace the rule classifier entirely with the LLM (single classification path)

Skip the rule classifier; every reply goes through the LLM. **Rejected with high prejudice** because:
* Violates D97's load-bearing legal-liability invariant (unsubscribe stays rule-based ONLY). Removing the rule classifier would force the LLM into the unsubscribe path — non-starter.
* Cost would 5× (every reply ≈ 100/month vs ~30 long-tail/month).
* Auditability regresses (every classification is LLM-self-reported rationale instead of deterministic `matched_pattern`).
* Backward compatibility breaks (Pillar D Weeks 2-5 deployments rely on the rule classifier).

## Consequences

### Positive

- **The LLM fallback extends classifier coverage for long-tail categories without compromising the legal-liability path.** The unsubscribe path stays rule-based per D97; the long-tail categories gain precision via the LLM. Pillar G's classifier-precision/recall dashboard surfaces the improvement.
- **The post-LLM refuse-loud guard is defense-in-depth.** Even if the prompt's allowed-response-set constraint fails (model regression, prompt injection, malformed parse), the guard catches a hypothetical LLM-classified unsubscribe + refuses. The LOAD-BEARING D97 invariant is enforced at THREE layers: (i) the prompt's allowed-response-set; (ii) the `LLMFallbackClassifier.classify()` post-LLM guard; (iii) the `ClassifierResult.__post_init__` source-level check from ADR-0026.
- **The classifier-cap migration bounds LLM spend.** Operators have an operator-tunable monthly cap; budget runaway is structurally prevented.
- **The cost-emit + Pillar G observability shape is uniform with existing sources.** Reoon / Gmail / Apollo / LinkedIn / Twitter / Calendar emit `cost_incurred` events with `source: <vendor>`; `reply_classifier_llm` joins as a new source value without engine change. The factory dashboard surface inherits.
- **The narrow dispatch trigger (LLM only on `uncategorized`) preserves rule-classifier audit signal.** Operators tuning the rule list continue to see deterministic pattern matches in the audit trail; LLM extends coverage without obscuring rule decisions.
- **Operator opt-in posture matches Pillar C Weeks 7-10's pattern.** The cap migration ships commented factory; the LLM fallback is wired at construction. Operators upgrading from Week 4-5 see ZERO behavior change until they explicitly opt in.

### Negative

- **The LLM call adds latency to Pass G.** Each long-tail uncategorized reply now incurs ~1-2s of LLM round-trip (Haiku) on top of the rule classification (~1ms). For ~30 long-tail replies in a Pass G run, that's ~1 minute additional runtime. **Mitigation:** Pass G is not on the dispatch critical path (it runs in reconcile, not on send-gate). Operators with high uncategorized rates can ship `LLMFallbackClassifier(also_refine=False)` (the v1 default) or skip the wrapper entirely.
- **The LLM call introduces a new failure mode (the LLM SDK could fail).** A network glitch, an API outage, a malformed response — all surface as `LLMRefusalError` or `LLMResponseParseError` in Pass G's recorded errors. **Mitigation:** the rule classifier's `uncategorized` result is preserved when the LLM fails (the dispatch ordering is rule-first); operators see the error in the reconcile output + can re-run; the failure does not regress to LLM-emitting-unsubscribe (the refuse-loud guard catches).
- **Per-prospect cost attribution depends on `person_id` propagation.** The reply event carries `person_id`; the classifier propagates it to the cost event. Pre-Pillar-D-Week-1 reply events that lack `channel: email` (per ADR-0025 D96's P2-A fix) MAY also lack `person_id` (TBD if any in production). **Mitigation:** the cost event handles `person_id: None` gracefully (the `BudgetPerPersonCapRule` skips Allow when `ctx.person_id is None`; the cost-aggregation rules' window-cap mode counts events regardless of attribution).
- **The classifier-cap migration ships a commented factory rule; operators must opt in.** A future operator who doesn't read the cap's commented documentation may run the LLM fallback unbounded for a long time. **Mitigation:** the cap's commented form is in the operator-readable factory file (Pillar C Weeks 7-10 convention); Pillar G observability surfaces LLM cost in the operator dashboard; Pillar I doctor preflight (TBD) may warn on "LLM fallback configured + no cap rule active."
- **The `reply_classifier_llm.py` module is the first project Python that depends on a real LLM SDK at runtime (when wired).** Today's tests inject fakes; tomorrow's wiring needs `anthropic.Anthropic` (or equivalent). The Pillar I CLI is the natural wiring surface; v1 ships the primitive + the Protocol interface; the production client is operator-configurable. **Mitigation:** the Protocol shape decouples the classifier from any specific SDK; the test surface uses fakes; the production wiring is a small adapter (Pillar I).

### Neutral / observability

- The `reply_classified` events Week 6-8 emits with `classification_method: "llm"` are queryable via the existing `query_by_person` + filter-by-method pattern. Pillar G's classifier-precision/recall dashboard breaks down by method.
- The `cost_incurred` events with `source: "reply_classifier_llm"` join the existing per-source cost-aggregation surface. Operators with `BudgetWindowCapRule(source=None)` (sum-all-sources) include LLM cost in their global cap automatically.
- The classifier-cap rule's `policy_blocked` event surfaces the cap firing — operators see `rule: reply-classifier-llm-monthly-cap` in their reconcile output. The standard cap-fire UX from Pillar C Weeks 7-11 inherits.
- No new SoT introduced. The LLM fallback's output IS a `reply_classified` event (existing SoT); the cost emit IS a `cost_incurred` event (existing SoT); the classifier-cap policy rule IS a `BudgetWindowCapRule` instance (existing rule class). The `docs/SOURCES-OF-TRUTH.md` registry gains NO new row.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. LLM output denormalizes into the existing `reply_classified` event class; cost output denormalizes into the existing `cost_incurred` event class; cap rule instances denormalize into the existing `cooldowns.yml` policy file. The classifier pattern lists SoT (per ADR-0026 D103) is unchanged.
- **I2 (two-phase commit on every external side effect):** The LLM call IS an external side effect (network call to Anthropic). The two-phase analog: phase 1 is the LLM call (READ — the model returns a response); phase 2 is the ledger append of `reply_classified` + `cost_incurred` (WRITE — the framework's local commitment). A crash between the two leaves the LLM cost unrecorded (operator under-reports) but does NOT leave the framework in an inconsistent state — the next Pass G run re-dispatches the same reply, the LLM is called again, the new cost lands. The asymmetric-failure-cost calculus per PILLAR-PLAN §0 biases toward double-call > skip-classification.
- **I3 (schema versioning):** `reply_classified` events carry `v: 1` (existing ledger event versioning — unchanged). `cost_incurred` events carry `v: 1` (existing — unchanged). The policy file's `version: 1` is unchanged by D127's content-additive migration (per ADR-0020 D75).
- **I4 (reproducible state):** The LLM classifier IS non-deterministic at the per-call layer (the model's response varies across calls with the same input; LLM temperature). The framework's reproducibility property is the EVENT TRAIL — the `reply_classified` event records the LLM's response + the rationale + the cost. Replaying the ledger reconstructs the operator-facing state regardless of the LLM's per-call variation. Pillar G observability surfaces per-classification-method variance for operator inspection.
- **I5 (observable by default):** Every LLM call emits `reply_classified` with the model + the rationale + the confidence; every successful call also emits `cost_incurred` with the token counts + the calculated cost. Pillar G dashboards query all the structured fields without bespoke parsing.
- **I6 (tests prove invariants):** `tests/test_reply_classifier_llm.py` (new file) pins: (a) the dispatch ordering (rule first / LLM only on uncategorized); (b) the post-LLM refuse-loud guard (LLM returning `unsubscribe` raises `LLMRefusalError`); (c) the cost-emit shape (matches ADR-0006's contract); (d) the channel-on-every-event invariant preservation (per ADR-0014 D33 + ADR-0025 D96); (e) the prompt construction (the allowed-response-set excludes `unsubscribe`).
- **I7 (cost is a first-class concern):** D126's emit-site contract + D127's cap migration close the loop. Operators have a tunable monthly cap; per-prospect attribution + per-run attribution (when wired) both work via the existing rule classes; the pricing table already includes anthropic rates.
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0029 row. The per-week trajectory in `.planning/HANDOFF-pillar-d-week-9.md` (this commit's sibling) names planned ADRs 0030+.

Does not weaken any invariant. I7's enforcement extends to the LLM source. I2's two-phase analog covers the LLM call. I5's enforcement extends to the per-call cost + the per-call rationale.

### Downstream pillar impact

Per the Pillar A / B / C / D convention (every ADR explicitly names cross-pillar impact):

* **Pillar E (discovery quality + lineage).** Pillar E's discovery-lineage tracking is unaffected by the LLM fallback (discovery doesn't classify replies). If a future Pillar E touch-quality scoring wants to consume `classification_method` (e.g., "weight rule classifications higher than LLM classifications when computing reply-rate per ICP segment"), the field is already in the event class — no API change.

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring is per-touch; classification method doesn't directly inform voice scoring. A future Pillar F revision MAY use the classification distribution (e.g., "operators with high LLM-classification rates are reaching outside the rule classifier's coverage — possibly because their ICP triggers unusual reply patterns; tune voice toward more conventional patterns") but this is observability, not Pillar F primitive change.

* **Pillar G (observability).** Pillar G's classifier-precision/recall dashboard EXPANDS to break down by `classification_method`. The per-method precision/recall + per-confidence-bucket precision are the natural observability extensions; Pillar G's dashboard surface inherits the field structure.

* **Pillar H (daemon + dispatcher).** Pillar H's SIGHUP-on-classifier-update hook (TBD) closes the policy-bundle reload race. Pillar H's daemon-mode Pass G dispatcher pre-loads the `LLMFallbackClassifier` once + invokes per reply; no per-call construction overhead.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant LLM provider isolation is the Pillar I responsibility — different tenants may want different providers (Anthropic, OpenAI, local) + different cost caps. The Pillar I CLI ships the `--llm-provider` + `--llm-model` flags + a tenant-scoped configuration surface. The classifier-cap migration's per-tenant policy file already separates tenants per the existing `~/.outreach-factory/policies/` per-tenant convention.

* **Pillar J (security + compliance).** Pillar J's CAN-SPAM compliance gate consumes Pillar D's auto-unsubscribe contract — the LLM fallback does NOT touch the auto-unsubscribe path (D97 invariant); Pillar J's compliance posture is unchanged. Pillar J's GDPR-forget transaction may also extend to "purge per-person LLM-classified events" (same pattern as `gdpr_purged` tombstoning for other event types — TBD per Pillar J's ADR).

## Migration / rollout

The Week 6-8 deliverable is the LLM fallback module + the classifier-cap policy migration + the cross-pillar audit extension + the per-week trajectory document.

**Operator-facing changes (Week 6-8):**

1. **One new pending migration.** `runner.pending()` returns 17 (up from 16). The new migration is `policy/0007_add_reply_classifier_llm_cap`; per-category breakdown: vault: 4, ledger: 6, policy: 7.

2. **Operators upgrading from Week 4-5 see NO behavior change unless they opt into the LLM fallback.** Pass G accepts a `RuleBasedClassifier` by default (the existing Week 2-5 wiring); the `LLMFallbackClassifier` is constructed at the wiring site. The classifier-cap migration ships a COMMENTED factory rule; operators uncomment to enable the cap when they opt into the LLM fallback.

3. **Operators opting into the LLM fallback need:**
   * An LLM client implementation (e.g., `AnthropicClient(model="claude-haiku-4-5")`) — the Pillar I CLI will ship a factory wrapper; v1 operators can implement the Protocol manually.
   * The classifier-cap rule uncommented in their `cooldowns.yml` (the migration installed it; operators uncomment).
   * No code change in their Pass G invocation — just wrap the `RuleBasedClassifier` in `LLMFallbackClassifier` before passing to `reconcile(classifier=...)`.

4. **The cap rule's `policy_blocked` event surface.** When the cap fires, operators see `rule: reply-classifier-llm-monthly-cap` in their reconcile output + the per-Pillar-G dashboards. The standard cap-fire UX inherits from Pillar C Weeks 7-11.

5. **Existing operators with pre-Pillar-D-Week-6-8 `reply_classified` events** retain `classification_method: "rule"` (their existing events are unchanged). The Pillar G dashboards' per-method breakdown shows 100% rule pre-Week-6-8; the LLM-method percentage grows as operators opt in.

**Operator-facing changes (Pillar D Week 9-11+, planned):**

6. **Win/loss attribution + `conversation_outcome` event class.** Week 9-11 per ADR-0030+ (TBD numbering). Consumes both `reply_classified` (any method) + `conversation_state_changed` events to derive per-prospect win/loss.

7. **TTL-based `* → dormant` transitions for conversation state machine.** Week 9-11 per ADR-0028 §Negative consequences forward-reference.

8. **Pillar D Week 12 exit-criterion close.** The binding `test_100_message_synthetic_inbox_classifier_benchmark` un-skips when Week 12 lands. The LLM fallback is a precursor; the benchmark measures the precision improvement.

**The Week 6-8 commit's verification surface:**

```bash
# 1. The new LLM fallback module exists + the Protocol is importable.
$ python -c "from orchestrator.reply_classifier_llm import LLMFallbackClassifier, LLMClient, LLMResponse, LLMRefusalError; print('ok')"

# 2. The new policy migration is registered.
$ python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print('pending:', len(r.pending()))"
# Expected: 17.

# 3. The new tests pass.
$ python -m pytest tests/test_reply_classifier_llm.py tests/test_migrations_policy_0007.py -v
# Expected: all passing.

# 4. The full suite is green.
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 2162 + N passing (N = LLM tests + migration tests).

# 5. ADR-0029 exists; README index gains the row; PILLAR-PLAN §6 Pillar D row flipped.
$ ls docs/adr/0029-pillar-d-llm-fallback-and-classifier-cap.md
$ grep "0029" docs/adr/README.md
$ grep "Week 6-8 ✓" docs/PILLAR-PLAN.md
```

### Existing-operator seed

The Week 6-8 commit ships ONE new policy migration. The seed taxonomy per ADR-0024 D-N7 inherits with shape simplification (one rule, not two):

* **Shape A — rule already canonical-named.** Operator with a hand-tuned `cooldowns.yml` carrying `reply-classifier-llm-monthly-cap` (unlikely but possible). Migration skips per name-match idempotence. **Action: none.**
* **Shape B — rule renamed (e.g., `my-llm-budget`).** Operator's tuned version stays; migration adds the canonical-named rule alongside. **Action: operator dedupes if they want.**
* **Shape new-operator — no rule present.** Migration appends the canonical rule (commented form per D127). **Action: operator uncomments when they enable the LLM fallback.**

The migration is content-additive (no version bump per ADR-0020 D75-D76). Operators on engine version `1` (the only supported version) get the rule shape backfilled; the LLM cost events that consume the rule land when operators wire the LLM fallback.

**No vault migration in Week 6-8.** The classifier-cap is policy-only; the `reply_classified` events' per-person aggregation (`derived_conversation_status`) and `conversation_status:` frontmatter field (Week 4-5's vault/0004) handle the LLM-method events transparently — both Pass N and Pass C heal operate on the category not the method.

**No ledger migration in Week 6-8.** The append-only ledger absorbs the new `reply_classified` (with `classification_method: "llm"`) + `cost_incurred` (with `source: "reply_classifier_llm"`) events without schema change.

## References

- ADR-0001 (policy engine architecture) — the engine surface the classifier-cap rule registers with (no engine change required).
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention the LLM fallback emits against. D126's `source: reply_classifier_llm` joins the existing per-source pricing-table surface. The `BudgetWindowCapRule` class shipped Week 6-8's migration writes instances of is the existing rule class.
- ADR-0009 (migration framework) — Pillar D Week 6-8's classifier-cap migration registers into the existing framework.
- ADR-0011 (vault migrations) — unchanged; Week 6-8 ships no vault migration.
- ADR-0012 (policy migrations) — Week 6-8's classifier-cap migration follows the engine-version-range-acceptance contract.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-event invariant Week 6-8 preserves on every emitted `reply_classified` event; the D36 existing-operator-seed pattern Week 6-8 inherits (simpler shape).
- ADR-0020 (Pillar C Week 7 per-channel policy migrations) — the D72-D78 per-channel-cap migration shape Week 6-8's classifier-cap migration MOST CLOSELY mirrors (single-rule per migration; commented factory; `budget.window-cap` rule class; `source:` field for per-source filter).
- ADR-0021 / 0022 / 0023 (Pillar C Weeks 8-10 per-channel caps) — the per-week single-rule migration arc Week 6-8 continues.
- ADR-0024 (Pillar C Week 11 cross-channel cooldown) — the structural divergence pattern Week 6-8 does NOT inherit (one rule, not two; same rule class as Weeks 7-10, not divergent).
- ADR-0025 (Pillar D foundation) — D96 (channel-on-every-event), D97 (load-bearing legal-liability invariant — unsubscribe = rule-based ONLY; the LLM is NEVER consulted for unsubscribe even as a tiebreaker; Week 6-8's dispatch ordering + prompt contract + post-LLM guard all enforce this carry-forward), D99 (cross-pillar audit), D101 (exit-criterion vehicle; Week 12 un-skips the benchmark the LLM fallback is a precursor for), §I7 (cost is first-class; reserves `source: "reply_classifier_llm"`).
- ADR-0026 (Pillar D Week 2 rule-based classifier) — D102 (module placement convention Week 6-8 inherits for `reply_classifier_llm.py`), D104 (idempotence-by-(reply_message_id, channel) Week 6-8's `LLMFallbackClassifier.classify` propagates unchanged), D107 (uncategorized fallback — Week 6-8's dispatch trigger).
- ADR-0027 (Pillar D Week 3 long-tail + per-channel reply detection) — D108 (per-category-kwargs constructor), D110 (dispatch priority order — unchanged; the LLM fallback consults on `uncategorized` AFTER the priority-ordered rule dispatch).
- ADR-0028 (Pillar D Week 4-5 auto-unsubscribe + conversation state) — D116 (YAML-first write order; Week 6-8 does NOT touch the handler), D117 (LOAD-BEARING (reply_message_id, channel) dedup; Week 6-8 preserves), D119 (per-thread state transitions; Week 6-8 emits the same long-tail categories the state machine consumes), D120 (Pass M + Pass N placement; Week 6-8 does NOT add a new pass).
- `docs/PILLAR-PLAN.md` §2 Pillar D — exit criterion + the LLM fallback's role as the precision-improvement substrate. §5 — "What we will not do" — the unsubscribe = rule-based ONLY constraint Week 6-8 enforces at THREE layers. §6 Pillar D row — flipped to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4-5 ✓ + Week 6-8 ✓" in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D124's narrow dispatch trigger (LLM extends coverage; doesn't replace rule decisions — operator-tunability bias).
- `docs/RISK-REGISTER.md` R012 (LLM hallucinates unsubscribe — risk D97 + D123 + D124 + the post-LLM refuse-loud guard mitigate by construction at THREE layers). R013 (operator pattern-list misconfiguration — partially mitigated by Week 6-8's LLM extending coverage on patterns the rule misses). R014 (per-channel reply false-emit — partially mitigated by Week 6-8's LLM improving long-tail precision). R016 (LLM cost runaway from inbox flood — NEW, added in this commit; mitigated by the classifier-cap migration + per-run cap defense-in-depth + opt-in posture).
- `docs/SOURCES-OF-TRUTH.md` — no new SoT row in Week 6-8 (the LLM output denormalizes into existing event classes; the cap rule instance denormalizes into the existing policy file SoT).
- `.planning/REVIEW-pillar-d-surface-audit.md` — extended with §"Week 6-8 audit extension (ADR-0029 D128)" per the row-by-row discipline.
- `.planning/HANDOFF-pillar-d-week-6.md` — the per-week handoff that scoped Week 6-8.
- `.planning/HANDOFF-pillar-d-week-9.md` (this commit's sibling) — the per-week trajectory document for Week 9-11.
- `orchestrator/reply_classifier.py` — the Week 2-3 rule-based classifier Week 6-8's LLM fallback wraps. Unchanged in this commit (the LLM fallback is a wrapper, not a modification).
- `orchestrator/reply_classifier_llm.py` (NEW) — the Week 6-8 module shipping `LLMFallbackClassifier` + the `LLMClient` Protocol + `LLMResponse` dataclass + `LLMRefusalError` + `LLMResponseParseError`.
- `orchestrator/policy/budget.py` — the existing `BudgetWindowCapRule` class Week 6-8's migration writes instances of. `COST_RATES_USD["anthropic"]` already lists the Haiku 4.5 rates Week 6-8's cost calculation uses.
- `orchestrator/migrations/policy/migration_0007_add_reply_classifier_llm_cap.py` (NEW) — the Week 6-8 migration.
- `config-template/cooldowns.example.yml` — extended with Rule 12f (commented form per D127).
- `tests/test_reply_classifier_llm.py` (NEW) — Week 6-8 LLM fallback unit tests.
- `tests/test_migrations_policy_0007.py` (NEW) — Week 6-8 classifier-cap migration unit tests.
- `tests/test_multi_channel_coherence.py::TestReplyClassification` — un-skipped a subset of LLM-fallback-dependent rows (TBD per Week 6-8 review).
- Forward-references (planned):
  - **ADR-0030+** (Pillar D Week 9-11): win/loss attribution + `conversation_outcome` event class + TTL-based dormant transitions.
  - **ADR-00NN** (Pillar D Week 12): exit-gate close — the binding 100-message benchmark un-skips.
  - **Pillar H SIGHUP** (Weeks 37-48): live-reload of classifier-cap rule changes; daemon-mode classifier pre-loading.
  - **Pillar I CLI** (Weeks 43-48): `--llm-provider` + `--llm-model` flags; production `AnthropicClient` wiring; per-tenant LLM provider isolation; doctor preflight extension warning "LLM fallback configured + no cap rule active."
