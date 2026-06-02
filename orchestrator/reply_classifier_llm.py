"""Pillar D Week 6-8 — LLM fallback for long-tail classifier categories.

Per ADR-0029 D122-D128. The :class:`LLMFallbackClassifier` wraps a
Week 2-3 :class:`orchestrator.reply_classifier.RuleBasedClassifier` +
delegates rule-first. When the rule returns ``category=uncategorized``
(per ADR-0026 D107's fallback posture), the LLM is consulted to extend
classification coverage on the long-tail categories
(``ooo`` / ``wrong_person`` / ``interest`` / ``rejection``).

The unsubscribe path stays rule-based per ADR-0025 D97's load-bearing
legal-liability invariant. The LLM is NEVER consulted for unsubscribe,
not as a tiebreaker, not as a high-confidence fallback. The invariant
is enforced at FIVE independent defense-in-depth layers (numbered
consistently across this module + ADR-0029 D123 + the Week 6-8
follow-up commit's reconciliation per the per-week review's P2-D
finding):

  1. **Dispatch short-circuit.** :meth:`LLMFallbackClassifier.classify`
     returns the rule result unchanged when ``rule_result.category ==
     "unsubscribe"`` — the LLM is never called for the unsubscribe path.
  2. **Prompt exclusion.** The LLM prompt (per ADR-0029 D123 — pinned
     in :data:`_PROMPT_TEMPLATE`) explicitly excludes ``unsubscribe``
     from the allowed response set with a legal-liability justification
     in the prompt body.
  3. **Parse-layer check.** :func:`_parse_llm_response_text` rejects
     any response whose ``category`` is not in
     :data:`_ALLOWED_LLM_CATEGORIES` (which excludes ``unsubscribe``)
     by raising :class:`LLMResponseParseError` BEFORE the LLMResponse
     dataclass is constructed.
  4. **Post-LLM refuse-loud guard.** A guard in
     :meth:`LLMFallbackClassifier.classify` raises
     :class:`LLMRefusalError` if the LLM somehow returns
     ``unsubscribe`` (e.g., if a future adapter implementation bypasses
     :func:`_parse_llm_response_text` and constructs an
     :class:`LLMResponse` directly).
  5. **Construction-time backstop.**
     :meth:`orchestrator.reply_classifier.ClassifierResult.__post_init__`
     (shipped in Week 2 per ADR-0026) rejects construction of a
     ``ClassifierResult(category="unsubscribe", classification_method=
     "llm", ...)`` — the source-level enforcement from ADR-0025 D97 that
     catches even a hypothetical reflexive construction-without-parse
     code path.

Defense-in-depth against prompt injection from inside the reply body,
model regression, malformed parse, adapter misconfig, or future
contributor reflex.

Module shape (ADR-0029 D122-D128):

* :class:`LLMResponse` — frozen dataclass; the parsed LLM response per
  one classify call. Carries ``category``, ``confidence``,
  ``rationale``, plus token-count fields the cost emitter uses.
* :class:`LLMClient` — :class:`typing.Protocol`; the implementer-facing
  surface. Production wiring (Pillar I CLI) ships an
  ``AnthropicClient`` implementing this Protocol; tests inject
  fakes. The Protocol is deliberately small (one method,
  :meth:`LLMClient.classify_text`) so adapter authors don't need to
  understand the framework's classifier wiring.
* :class:`LLMFallbackClassifier` — the Pillar D Week 6-8 primitive.
  Constructor takes a wrapped rule classifier + an LLM client + the
  ledger (for the cost-event emit). The ``classify()`` method returns
  a :class:`orchestrator.reply_classifier.ClassifierResult` matching
  the wrapped rule classifier's signature — DROP-IN compatible with
  :func:`orchestrator.reconcile.run_pass_g`.
* :class:`LLMRefusalError` — raised when the LLM's response would
  violate ADR-0025 D97 (returns ``unsubscribe``). Pass G records the
  error + skips the event without emitting a misclassified
  ``reply_classified`` event.
* :class:`LLMResponseParseError` — raised when the LLM's text response
  cannot be parsed as the expected JSON shape. Pass G records the
  error + falls back to the rule classifier's ``uncategorized``
  result.
* :func:`build_llm_prompt` — pure helper rendering the prompt template
  with one reply text. Exposed for the test surface + future
  Pillar G observability ("show me the exact prompt sent for this
  classification").
* :func:`compute_llm_cost_usd` — pure helper computing the per-call
  USD cost from token counts + model name. Uses the existing
  :data:`orchestrator.policy.budget.COST_RATES_USD["anthropic"]`
  pricing table (no new constants).
* :func:`build_cost_incurred_payload` — pure helper constructing the
  ``cost_incurred`` event per ADR-0006's contract. Single source of
  truth for the event shape (shared with the test fixtures).

Pass G integration:

Pass G's caller (the reconcile module's CLI main + the operator's
script-level wiring) constructs the classifier:

.. code-block:: python

    from orchestrator import reply_classifier, reply_classifier_llm

    rule = reply_classifier.RuleBasedClassifier.from_yaml_dir(directory)
    llm_client = AnthropicClient(model="claude-haiku-4-5")  # Pillar I
    classifier = reply_classifier_llm.LLMFallbackClassifier(
        rule_classifier=rule,
        llm_client=llm_client,
        led=led,
    )
    # Pass G accepts the wrapped classifier unchanged.
    reconcile(passes="G", classifier=classifier, led=led, since=...)

Operators NOT opting into the LLM fallback continue to pass the bare
``RuleBasedClassifier`` — Pass G is signature-compatible with both
(both expose ``.classify(reply_event) -> ClassifierResult``).

Cost emit (ADR-0029 D126):

After every successful LLM call, the classifier appends one
``cost_incurred`` event with ``source: "reply_classifier_llm"`` per
ADR-0025 §I7's reservation. Failed LLM calls do NOT emit cost (matches
ADR-0006's per-vendor convention — "we don't pay for failures" for
Anthropic). The cost event lands BEFORE the ``reply_classified`` event
Pass G emits (the classifier returns after the cost emit; Pass G then
writes the classified event via
:func:`orchestrator.reply_classifier.emit_classified_event`).

See ADR-0029 for the full design rationale.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Protocol

import ledger as _ledger
import reply_classifier as _reply_classifier
from policy import budget as _budget
from reply_classifier import extract_reply_text


# ---------------------------------------------------------------------------
# Constants — the prompt template + the allowed response set
# ---------------------------------------------------------------------------


# Per ADR-0029 D123 — the allowed response set EXCLUDES unsubscribe by
# prompt contract. The dispatch path in :meth:`LLMFallbackClassifier.
# classify` enforces by short-circuit; the prompt-level exclusion is
# the second layer (the post-LLM refuse-loud guard is the third).
_ALLOWED_LLM_CATEGORIES: tuple[str, ...] = (
    "ooo",
    "wrong_person",
    "interest",
    "rejection",
    "uncategorized",
)


# Per ADR-0029 D123 — the load-bearing prompt template. Pinned in
# module-level constant + exposed via :func:`build_llm_prompt` for the
# test surface + future Pillar G observability.
#
# Design notes (per ADR-0029 D123):
#   * SINGLE round-trip per reply (one call per classify); bounds cost.
#   * The allowed-response-set is enumerated explicitly + the exclusion
#     of "unsubscribe" is justified inline (load-bearing legal-liability
#     invariant per PILLAR-PLAN §5 + ADR-0025 D97).
#   * The JSON output shape is constrained: ``category`` (string),
#     ``confidence`` (float 0.0-1.0), ``rationale`` (one-sentence
#     string). The parser tolerates whitespace + optional markdown
#     fences but expects the JSON object on a single line per the
#     instruction.
#
# The template is plain text (NOT an f-string at module-load time)
# because the ``{reply_text}`` placeholder is filled by
# :func:`build_llm_prompt` at call time. Pre-filling would require
# escaping every ``{`` / ``}`` in the JSON example.
_PROMPT_TEMPLATE: str = """You are a reply-classification assistant. Classify the following reply
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
{{"category": "<one of: ooo, wrong_person, interest, rejection, uncategorized>",
 "confidence": <a float between 0.0 and 1.0>,
 "rationale": "<one short sentence explaining the choice>"}}"""


# Per ADR-0029 D122 — the default model name. Operators override via
# constructor kwarg + a future Pillar I CLI flag.
DEFAULT_LLM_MODEL: str = "claude-haiku-4-5"


# Per ADR-0029 §I7 + ADR-0025 §I7's reservation — the cost-event source
# name. Pinned in module-level constant + exposed for the test surface
# + downstream consumers (the classifier-cap migration consumes by
# this exact string).
COST_SOURCE: str = "reply_classifier_llm"


# Per ADR-0029 §I7 — the "units" convention. One unit = one LLM call
# (matches Reoon's verify-per-call convention + Gmail's send-per-call
# convention). Operators wanting token-based caps configure with the
# ``BudgetWindowCapRule.max_usd`` mode instead.
_UNITS_PER_CALL: int = 1


# Per ADR-0029 D125 — the LLM's self-reported confidence is clamped to
# [0.0, 1.0] before being placed in the :class:`ClassifierResult`. A
# malformed response that sets confidence to NaN / inf / negative gets
# normalized to 0.0 (the asymmetric-failure-cost calculus — a low-
# confidence classification is no worse than a high-confidence one
# from the downstream consumer's perspective; both surface in Pillar
# G's dashboards with the actual value).
_MIN_CONFIDENCE: float = 0.0
_MAX_CONFIDENCE: float = 1.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMRefusalError(Exception):
    """The LLM's response would violate ADR-0025 D97.

    Raised when the LLM returns ``category: "unsubscribe"`` despite
    the prompt contract excluding it. Defense-in-depth against:

    * Prompt injection from inside the reply body
      (recipient-attacker tries to manipulate the model).
    * Model regression (a future model release responds differently
      to the prompt instructions).
    * Malformed JSON parse defaulting the category field.

    Pass G catches this + records the error + skips the
    ``reply_classified`` emit for the event. The reply event remains
    available for re-classification on a future Pass G run; operators
    investigate via the recorded error + the LLM client's logs.

    Per ADR-0029 D123 — the THIRD layer of the load-bearing legal-
    liability invariant carry-forward (layer 1: dispatch short-circuit;
    layer 2: prompt allowed-response-set; layer 3: this guard).
    """


class LLMResponseParseError(Exception):
    """The LLM's text response cannot be parsed as the expected JSON shape.

    Raised when:

    * The response is not valid JSON.
    * The JSON object lacks a ``category`` field.
    * The ``category`` field is not in :data:`_ALLOWED_LLM_CATEGORIES`.
    * The ``confidence`` field is non-numeric (the value is normalized
      to [0.0, 1.0] if numeric — bare-numeric clamping is NOT a parse
      error; only fundamentally-non-numeric values are).

    Pass G catches this + records the error + falls back to the
    rule classifier's ``uncategorized`` result. The rule result was
    already computed BEFORE the LLM call (per the dispatch ordering);
    the framework preserves visibility-without-action posture.

    Per ADR-0029 D125 — the parse-error path is recorded in Pillar G
    observability (operators see the per-LLM-call error rate; high
    rates trigger investigation).
    """


# ---------------------------------------------------------------------------
# LLM client surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMResponse:
    """One LLM call's parsed response.

    Carries the LLM's classification decision (``category`` +
    ``confidence`` + ``rationale``) + the token counts the cost
    emitter needs. Returned by :meth:`LLMClient.classify_text`;
    consumed by :meth:`LLMFallbackClassifier.classify`.

    Per ADR-0029 D125 — the ``confidence`` field is the LLM's self-
    reported value, clamped to [0.0, 1.0]. Calibration vs empirical
    precision is a Pillar G observability extension.

    Per ADR-0029 D126 — the ``input_tokens`` + ``output_tokens`` fields
    drive the cost calculation via :func:`compute_llm_cost_usd`. The
    ``model`` field is surfaced in the ``cost_incurred`` event's
    ``model_or_endpoint`` field per ADR-0006's contract.
    """

    category: str
    confidence: float
    rationale: str
    input_tokens: int
    output_tokens: int
    model: str

    def __post_init__(self) -> None:
        # The category field validation is the LAST line of defense
        # before the response reaches the dispatcher. The dispatcher
        # ALSO checks (refuse-loud guard) but this construction-time
        # check catches malformed parses that build an LLMResponse
        # with a bad category.
        if self.category not in _reply_classifier.CATEGORIES:
            raise ValueError(
                f"LLMResponse.category must be one of "
                f"{sorted(_reply_classifier.CATEGORIES)}; "
                f"got {self.category!r}"
            )
        if not (_MIN_CONFIDENCE <= self.confidence <= _MAX_CONFIDENCE):
            raise ValueError(
                f"LLMResponse.confidence must be in "
                f"[{_MIN_CONFIDENCE}, {_MAX_CONFIDENCE}]; "
                f"got {self.confidence!r}"
            )
        if self.input_tokens < 0:
            raise ValueError(
                f"LLMResponse.input_tokens must be >= 0; "
                f"got {self.input_tokens!r}"
            )
        if self.output_tokens < 0:
            raise ValueError(
                f"LLMResponse.output_tokens must be >= 0; "
                f"got {self.output_tokens!r}"
            )


class LLMClient(Protocol):
    """The implementer-facing LLM-client Protocol.

    Production wiring (Pillar I CLI) ships an ``AnthropicClient``
    implementing this Protocol; tests inject fakes. Decoupling the
    classifier from any specific SDK keeps the test surface clean +
    lets operators swap providers without changing the classifier
    code.

    Per ADR-0029 D122 — the default production implementation uses
    Anthropic's SDK with the ``claude-haiku-4-5`` model. The Protocol
    is provider-agnostic — adapter implementations for OpenAI / local
    inference are operator-deliberate (Pillar I scope).

    The Protocol is deliberately small:

    * ONE method (:meth:`classify_text`) — the adapter author doesn't
      need to understand the framework's classifier wiring.
    * Synchronous — matches the Pillar D Week 2-3 rule classifier's
      synchronous interface. Pass G is a synchronous reconcile pass;
      async-via-asyncio is a Pillar H daemon concern.

    Adapter implementers MUST:

    * Return a parsed :class:`LLMResponse` (the SDK response → JSON
      parse → dataclass — the adapter owns the parse).
    * Raise :class:`LLMResponseParseError` on parse failure (NOT
      return a malformed :class:`LLMResponse`).
    * Pass through token usage (input + output) so the framework can
      compute the cost. The SDK exposes these fields; the adapter
      surfaces them on the response dataclass.
    * Declare a default value for ``model`` matching
      :data:`DEFAULT_LLM_MODEL`. Python :class:`typing.Protocol`
      structural compatibility does NOT inherit default values from
      the Protocol's method signature into the implementer — an
      implementer that writes ``def classify_text(self, reply_text:
      str, *, model: str)`` (no default) satisfies the Protocol
      structurally but breaks call sites that rely on the default.
      :class:`LLMFallbackClassifier`'s ``classify`` always passes
      ``model`` explicitly so it's resilient, but other future
      callers may rely on the Protocol's documented default.

    Adapters SHOULD NOT:

    * Catch + swallow LLM API exceptions — propagate as the SDK's
      native exception class. The classifier records the failure +
      Pass G falls back to the rule result.
    * Emit ``cost_incurred`` events themselves — the classifier owns
      the emit per ADR-0029 D126.

    Canonical adapter construction pattern (the Pillar I CLI's
    ``AnthropicClient`` follows this shape):

    .. code-block:: python

        class AnthropicClient:
            def __init__(self, *, api_key=None, model=DEFAULT_LLM_MODEL):
                self._client = anthropic.Anthropic(api_key=api_key)
                self._default_model = model

            def classify_text(
                self, reply_text, *, model=DEFAULT_LLM_MODEL,
            ) -> LLMResponse:
                # 1. Build the prompt + send to the SDK.
                prompt = build_llm_prompt(reply_text)
                sdk_response = self._client.messages.create(
                    model=model,
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                # 2. Extract text + token counts from the SDK response.
                text = sdk_response.content[0].text
                input_tokens = sdk_response.usage.input_tokens
                output_tokens = sdk_response.usage.output_tokens
                # 3. Parse the text into a partially-constructed
                #    response (token counts default to 0 in the parse
                #    helper); then build the final LLMResponse with the
                #    SDK-surfaced counts.
                parsed = _parse_llm_response_text(text, model=model)
                return LLMResponse(
                    category=parsed.category,
                    confidence=parsed.confidence,
                    rationale=parsed.rationale,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=model,
                )

    The three-step parse-extract-build pattern is the load-bearing
    contract: adapters MUST call :func:`_parse_llm_response_text` for
    the text-level parse (so the parse-layer legal-liability check
    fires uniformly across providers per Layer 3) AND construct the
    final :class:`LLMResponse` with the SDK-surfaced token counts (so
    cost emit is accurate per ADR-0029 D126).
    """

    def classify_text(
        self, reply_text: str, *, model: str = DEFAULT_LLM_MODEL,
    ) -> LLMResponse:
        """Classify one reply text. Returns a :class:`LLMResponse`.

        The implementation sends the prompt (via :func:`build_llm_prompt`)
        to the LLM provider, parses the response JSON, and returns the
        dataclass. The framework expects:

        * The :class:`LLMResponse` is constructable (the response's
          ``category`` is in :data:`_reply_classifier.CATEGORIES`; the
          ``confidence`` is in [0.0, 1.0]; the token counts are >= 0).
        * A malformed response raises :class:`LLMResponseParseError`
          (per the implementer contract above).
        * The ``model`` argument is passed through to the LLM call;
          the response's ``model`` field reflects what was used.

        Operators wanting per-call retry / backoff implement at the
        adapter layer (the classifier does not retry — that's an SDK-
        adapter concern, not a framework concern).
        """
        ...


# ---------------------------------------------------------------------------
# Pure helpers — prompt construction + cost calculation + event payload
# ---------------------------------------------------------------------------


def build_llm_prompt(reply_text: str) -> str:
    """Render the LLM prompt for one reply text.

    Per ADR-0029 D123 — the prompt template is module-level constant
    :data:`_PROMPT_TEMPLATE`. This helper fills the ``{reply_text}``
    placeholder.

    Empty reply text is acceptable (the framework's tests + edge cases
    cover this); the LLM is expected to return ``category="uncategorized"``
    with low confidence.

    Reply text containing literal ``{`` / ``}`` characters is safe —
    the :func:`str.format` call has only the ``{reply_text}`` named
    placeholder; curly braces in the substituted value are inserted
    verbatim as part of the formatted string, not re-parsed as format
    specifiers. (Verified by ``tests/test_reply_classifier_llm.py::
    TestBuildLLMPrompt::test_prompt_with_curly_braces_in_reply_text``.)
    No format-string injection vulnerability from recipient-supplied
    text.

    Exposed for the test surface + future Pillar G observability
    ("show me the exact prompt sent for this classification" is a
    natural operator query when investigating a per-prospect
    classification).
    """
    # The template uses Python's str.format placeholder ``{reply_text}``;
    # any literal `{` / `}` characters in the template (e.g., the JSON
    # example shape) are escaped as `{{` / `}}` per str.format's
    # contract. The substituted ``reply_text`` value's curly braces are
    # NOT re-parsed (the format spec only looks at the template, not
    # the substituted values).
    return _PROMPT_TEMPLATE.format(reply_text=reply_text)


def compute_llm_cost_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Compute the per-call USD cost from token counts.

    Per ADR-0029 D126 — uses the existing
    :data:`orchestrator.policy.budget.COST_RATES_USD["anthropic"]`
    pricing table. The rate keys follow the
    ``<model>:input_per_mtok`` / ``<model>:output_per_mtok`` convention
    pinned in ADR-0006 §"Pricing table snapshot".

    Returns ``0.0`` if the model is not in the rates table — operators
    using a model the rates table doesn't list (e.g., an unreleased
    future model) see the cost event emit with ``amount_usd=0.0`` +
    the model name + units=1; the units-mode budget cap still
    enforces. The asymmetric-failure-cost calculus per PILLAR-PLAN §0
    biases toward under-report > crash-the-classifier (a missing rates
    entry should not block classification).
    """
    rates = _budget.COST_RATES_USD.get("anthropic") or {}
    input_rate = float(rates.get(f"{model}:input_per_mtok") or 0.0)
    output_rate = float(rates.get(f"{model}:output_per_mtok") or 0.0)
    # Per-million-token rates → multiply by tokens / 1_000_000.
    input_cost = (float(input_tokens) / 1_000_000.0) * input_rate
    output_cost = (float(output_tokens) / 1_000_000.0) * output_rate
    return input_cost + output_cost


def build_cost_incurred_payload(
    *,
    reply_event: dict,
    response: LLMResponse,
) -> dict:
    """Construct the ``cost_incurred`` event payload (no ledger append).

    Per ADR-0006 §"Cost ledger contract" + ADR-0029 D126. Single
    source of truth for the cost-event shape; both
    :meth:`LLMFallbackClassifier.classify` (live persistence) and the
    test fixtures use this helper.

    Per-prospect attribution: ``person_id`` is taken from the reply
    event. Reply events without ``person_id`` (rare — pre-Pillar-D-Week-1
    Pass B emits sometimes lack the field per the historical default;
    see ADR-0025 D96) emit ``person_id: None`` per ADR-0006's
    convention.

    Run-level attribution deferred: ``run_id`` is None in v1 (the
    classifier call path doesn't surface run_id; Pillar I CLI may
    extend).
    """
    amount_usd = compute_llm_cost_usd(
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    return {
        "type": "cost_incurred",
        "source": COST_SOURCE,
        "amount_usd": float(amount_usd),
        "units": _UNITS_PER_CALL,
        "model_or_endpoint": response.model,
        "person_id": reply_event.get("person_id"),
        "run_id": None,
    }


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


# Regex matching a JSON object on a single line. The prompt instructs
# the LLM to respond with ONLY a single-line JSON object; the parser
# tolerates surrounding whitespace + optional markdown fences (some
# models reflexively wrap JSON in ```json fences despite the
# instruction).
_MARKDOWN_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)


def _parse_llm_response_text(
    text: str, *, model: str,
) -> LLMResponse:
    """Parse the LLM's text response into an :class:`LLMResponse`.

    Tolerates:

    * Surrounding whitespace.
    * Optional markdown fences (``` or ```json) — strip them.
    * The ``confidence`` field as int or float; clamp to [0.0, 1.0]
      if out of range (NOT a parse error — the asymmetric-failure-
      cost calculus per ADR-0029 D125 biases toward emit-with-clamped
      vs crash-the-classifier).

    Raises :class:`LLMResponseParseError` on:

    * Not-valid-JSON text.
    * Top-level not an object.
    * Missing ``category`` field.
    * ``category`` not in :data:`_ALLOWED_LLM_CATEGORIES`.
    * ``confidence`` non-numeric.

    The token-count fields (``input_tokens`` / ``output_tokens``) are
    NOT in the LLM's text response (the SDK surfaces them separately).
    This helper defaults BOTH to ``0`` on the returned LLMResponse;
    the adapter is responsible for constructing the FINAL LLMResponse
    with the SDK-surfaced token counts via the canonical three-step
    adapter pattern documented in :class:`LLMClient`'s docstring:

      1. Call the SDK; extract text from the response object.
      2. Call this function to parse the text into a partially-
         constructed LLMResponse (token counts default to 0).
      3. Construct the FINAL LLMResponse with the SDK-surfaced
         token counts replacing the defaults.

    Adapters MUST NOT skip step 2 — the parse-layer Layer 3 of the
    legal-liability invariant (per ADR-0029 D123 + the module-level
    docstring's five-layer enumeration) refuses any response whose
    ``category`` is ``unsubscribe``; bypassing this helper would
    bypass Layer 3.

    The ``model`` argument is the SDK-known model name (the adapter
    passes it through); embedded in the response for downstream
    cost-emit consumers.

    Per ADR-0029 D125 — the text-parse is exposed as a helper rather
    than inlined in adapters so the parse contract is uniform across
    SDKs + the test surface can test the parse without an LLM call.
    """
    raw = text.strip()
    if not raw:
        raise LLMResponseParseError(
            "LLM response is empty"
        )
    # Strip markdown fences if present.
    m = _MARKDOWN_FENCE_RE.match(raw)
    if m is not None:
        raw = m.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMResponseParseError(
            f"LLM response is not valid JSON: {exc}; "
            f"first 200 chars: {raw[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise LLMResponseParseError(
            f"LLM response top-level must be a JSON object; "
            f"got {type(parsed).__name__}"
        )
    category = parsed.get("category")
    if category is None:
        raise LLMResponseParseError(
            f"LLM response missing 'category' field; "
            f"got keys {sorted(parsed.keys())}"
        )
    if not isinstance(category, str):
        raise LLMResponseParseError(
            f"LLM response 'category' must be a string; "
            f"got {type(category).__name__}"
        )
    if category not in _ALLOWED_LLM_CATEGORIES:
        # Note: this catches the case where the LLM returns
        # "unsubscribe" — :class:`LLMResponseParseError` is the right
        # error class because the value is out of the allowed set.
        # The dispatcher's refuse-loud guard ALSO catches this (defense
        # in depth) by checking the category on the constructed
        # LLMResponse — but LLMResponse construction itself would
        # accept "unsubscribe" (it's in _reply_classifier.CATEGORIES).
        # The parse-error path here catches early.
        raise LLMResponseParseError(
            f"LLM response 'category' must be one of "
            f"{list(_ALLOWED_LLM_CATEGORIES)}; got {category!r}. "
            f"The unsubscribe category is rule-only per ADR-0025 D97."
        )
    raw_confidence = parsed.get("confidence", 0.0)
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError) as exc:
        raise LLMResponseParseError(
            f"LLM response 'confidence' must be numeric; "
            f"got {raw_confidence!r}"
        ) from exc
    # Clamp NaN / inf / out-of-range to [0.0, 1.0]. NaN comparison is
    # always False so the explicit check catches it.
    if confidence != confidence:  # NaN check
        confidence = _MIN_CONFIDENCE
    elif confidence < _MIN_CONFIDENCE:
        confidence = _MIN_CONFIDENCE
    elif confidence > _MAX_CONFIDENCE:
        confidence = _MAX_CONFIDENCE
    raw_rationale = parsed.get("rationale", "")
    rationale = str(raw_rationale) if raw_rationale is not None else ""
    # Token counts come from the adapter (SDK-known); not from the
    # text response. Default to 0 here; the adapter constructs the
    # LLMResponse with the SDK-surfaced counts after parsing.
    return LLMResponse(
        category=category,
        confidence=confidence,
        rationale=rationale,
        input_tokens=0,
        output_tokens=0,
        model=model,
    )


class LLMFallbackClassifier:
    """Pillar D Week 6-8 — LLM fallback classifier for long-tail categories.

    Wraps a Week 2-3 :class:`RuleBasedClassifier`; delegates rule-first.
    When the rule returns ``category=uncategorized`` (per ADR-0026 D107),
    consults the LLM to extend classification coverage on the long-
    tail categories.

    Per ADR-0029 D124's dispatch ordering:

    1. Rule classifier runs first → returns a :class:`ClassifierResult`.
    2. If ``rule_result.category == "unsubscribe"`` — return as-is.
       The LLM is NEVER consulted for unsubscribe per ADR-0025 D97.
    3. If ``rule_result.category != "uncategorized"`` (the rule matched
       a long-tail pattern with confidence 1.0) — return as-is. The
       LLM doesn't re-classify rule matches per the operator-tunability
       calculus.
    4. Else (the rule returned uncategorized) — consult the LLM.

    Per ADR-0029 D123's prompt + D124's guard:

    * The LLM prompt EXCLUDES ``unsubscribe`` from the allowed
      response set (prompt-layer enforcement).
    * The post-LLM refuse-loud guard raises :class:`LLMRefusalError`
      if the LLM somehow returns ``unsubscribe`` (third layer of the
      D97 carry-forward defense-in-depth).

    Per ADR-0029 D126's cost emit:

    * Every successful LLM call emits one ``cost_incurred`` event with
      ``source: "reply_classifier_llm"``.
    * The cost event lands BEFORE :meth:`classify` returns; Pass G's
      ``reply_classified`` emit follows.
    * Failed LLM calls do NOT emit cost (matches ADR-0006's per-
      vendor convention).

    Constructor signature:

    * ``rule_classifier`` — the wrapped Week 2-3 classifier. Required.
    * ``llm_client`` — an :class:`LLMClient` Protocol implementer.
      Required.
    * ``led`` — the ledger for the ``cost_incurred`` event emit.
      Required.
    * ``model`` — the LLM model name (default
      :data:`DEFAULT_LLM_MODEL` = ``"claude-haiku-4-5"``). Passed
      through to the LLM client per call.

    The ``classify(reply_event) -> ClassifierResult`` method matches
    the wrapped classifier's signature — DROP-IN compatible with
    :func:`orchestrator.reconcile.run_pass_g`.

    Per-channel discipline (carry-forward from Week 2-3): the result
    carries the same ``classification_method`` field shape as the
    rule classifier; rule results carry ``"rule"``, LLM results carry
    ``"llm"``. Pass G's ``reply_classified`` event emit preserves the
    field via :func:`reply_classifier.build_classified_payload`.
    """

    def __init__(
        self,
        *,
        rule_classifier: _reply_classifier.RuleBasedClassifier,
        llm_client: LLMClient,
        led: _ledger.Ledger,
        model: str = DEFAULT_LLM_MODEL,
    ) -> None:
        self._rule_classifier = rule_classifier
        self._llm_client = llm_client
        self._led = led
        self._model = model

    @property
    def rule_classifier(self) -> _reply_classifier.RuleBasedClassifier:
        """Expose the wrapped rule classifier for the test surface +
        Pillar I CLI introspection (e.g., "show me the loaded patterns").
        """
        return self._rule_classifier

    @property
    def model(self) -> str:
        """The configured LLM model name; surfaced for the test
        surface + future Pillar I CLI introspection.
        """
        return self._model

    def classify(
        self, reply_event: dict,
    ) -> _reply_classifier.ClassifierResult:
        """Classify one reply event. Returns a ClassifierResult.

        Per ADR-0029 D124's dispatch ordering — rule-first, LLM only
        on uncategorized. The unsubscribe path short-circuits BEFORE
        the LLM is consulted per ADR-0025 D97.

        Raises :class:`LLMRefusalError` if the LLM somehow returns
        ``category="unsubscribe"`` (third-layer defense-in-depth per
        ADR-0029 D123). Pass G catches + records the error + skips
        the event.

        Other LLM exceptions (SDK failures, network errors,
        :class:`LLMResponseParseError`) propagate to Pass G; Pass G
        catches + records + falls back to the rule result's
        ``uncategorized`` (the rule was already computed before the
        LLM call).
        """
        rule_result = self._rule_classifier.classify(reply_event)

        # ADR-0025 D97 — short-circuit on unsubscribe BEFORE the LLM
        # is consulted. The legal-liability invariant's first layer.
        if rule_result.category == "unsubscribe":
            return rule_result

        # ADR-0029 D124 — the narrow dispatch trigger. Only fall to
        # the LLM when the rule returned uncategorized (no pattern
        # matched). Long-tail rule matches stay as-is.
        if rule_result.category != "uncategorized":
            return rule_result

        # Rule returned uncategorized → consult the LLM. The text-extract
        # helper is the module-level :func:`extract_reply_text` shared
        # with :meth:`RuleBasedClassifier._extract_text` — single source
        # of truth per ADR-0029 D124 (both paths read the same fields
        # from the reply event so the LLM sees the same content the
        # rule inspected).
        text = extract_reply_text(reply_event)

        response = self._llm_client.classify_text(text, model=self._model)

        # Layer 4 of the legal-liability invariant carry-forward per
        # ADR-0029 D123 — the post-LLM refuse-loud guard. Catches a
        # hypothetical response that bypassed :func:`_parse_llm_response_text`
        # (Layer 3) by constructing :class:`LLMResponse` directly — e.g.,
        # a future adapter that uses a SDK-native structured-output
        # surface skipping the text parse path. Layer 5
        # (:meth:`ClassifierResult.__post_init__`) would also catch
        # `(category=unsubscribe, classification_method=llm)`, but
        # raising here is the operator-facing surface that names the
        # ADR-0025 D97 invariant explicitly.
        if response.category == "unsubscribe":
            raise LLMRefusalError(
                "LLM returned category='unsubscribe' despite prompt "
                "exclusion; refuse-loud per ADR-0025 D97 + ADR-0029 "
                "D123. The unsubscribe path is rule-based ONLY. "
                "Investigate: possible prompt injection from inside the "
                "reply body, model regression, or adapter misconfig."
            )

        # ADR-0029 D126 — emit the cost event BEFORE returning. The
        # cost event lands in the ledger; Pass G then emits the
        # reply_classified event (via reply_classifier.emit_classified_
        # event). A crash between the two leaves an unrecorded
        # classification; the next Pass G run re-emits both.
        cost_payload = build_cost_incurred_payload(
            reply_event=reply_event, response=response,
        )
        try:
            self._led.append(cost_payload)
        except (OSError, ValueError) as exc:
            # Per ADR-0006 §"Cost ledger contract" — the cost emit is
            # observability, not load-bearing for the classification.
            # A ledger append failure on the cost event is recorded
            # to stderr but does NOT roll back the LLM call (the LLM
            # already returned + the cost is real). The classifier
            # returns the classification result; Pillar G dashboards
            # surface the missing-cost discrepancy post-hoc.
            sys.stderr.write(
                f"WARNING: cost_incurred append failed for "
                f"reply_classifier_llm (model={self._model}): {exc}\n"
            )

        # Build the ClassifierResult per ADR-0025 D97's shape. The
        # `matched_pattern` field is None for LLM results (the LLM
        # doesn't produce a regex; the audit-trail surface is the
        # LLM response's rationale, recorded in the cost event +
        # surfaced via Pillar G dashboards).
        return _reply_classifier.ClassifierResult(
            category=response.category,
            classification_method="llm",
            confidence=response.confidence,
            matched_pattern=None,
        )
