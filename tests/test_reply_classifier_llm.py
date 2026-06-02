"""Pillar D Week 6-8 — LLM fallback reply classifier unit tests.

Per ADR-0029 D122-D128. Covers:

* The :class:`LLMResponse` dataclass construction-time invariants.
* :func:`build_llm_prompt` renders the load-bearing prompt template
  with the reply text + the unsubscribe-exclusion language verbatim
  per ADR-0029 D123.
* :func:`compute_llm_cost_usd` returns the right per-call cost from
  the existing :data:`COST_RATES_USD["anthropic"]` pricing table.
* :func:`build_cost_incurred_payload` matches ADR-0006's contract.
* :func:`_parse_llm_response_text` accepts the LLM's JSON response in
  every shape the prompt may produce (with + without markdown fences;
  with int + float confidence; with out-of-range confidence clamped).
* Refuses :class:`LLMResponseParseError` on malformed input (not JSON,
  missing category, category not in allowed set, non-numeric
  confidence).
* CRITICAL: refuses on ``category="unsubscribe"`` per ADR-0029 D123
  (the load-bearing legal-liability invariant — second parse layer).
* :class:`LLMFallbackClassifier` dispatch ordering — rule first;
  short-circuits on ``unsubscribe`` BEFORE the LLM is consulted; only
  consults LLM on ``category=uncategorized`` per ADR-0029 D124.
* CRITICAL: :class:`LLMFallbackClassifier` raises :class:`LLMRefusalError`
  if the LLM somehow returns ``unsubscribe`` (third defense-in-depth
  layer per ADR-0029 D123).
* Cost emit shape — the classifier appends one ``cost_incurred`` event
  per successful LLM call with the right source + amount + units per
  ADR-0029 D126.
* Confidence preservation in :class:`ClassifierResult` per ADR-0029
  D125 (the LLM's self-reported value flows through; clamping happens
  in the parser).
* Channel preservation — Pass G's caller can pass any per-channel
  reply event; the classifier doesn't filter on channel.
* Failed LLM calls (SDK exceptions) propagate to the caller; NO cost
  event lands (matches ADR-0006's "we don't pay for failures"
  per-vendor convention).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ledger as _ledger
import reply_classifier as _classifier
import reply_classifier_llm as _llm
from reply_classifier import ClassifierResult, RuleBasedClassifier
from reply_classifier_llm import (
    COST_SOURCE,
    DEFAULT_LLM_MODEL,
    LLMClient,
    LLMFallbackClassifier,
    LLMRefusalError,
    LLMResponse,
    LLMResponseParseError,
    build_cost_incurred_payload,
    build_llm_prompt,
    compute_llm_cost_usd,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(d))
    return _ledger.Ledger(d)


@pytest.fixture
def basic_rule_classifier() -> RuleBasedClassifier:
    """Minimal rule classifier with one unsubscribe pattern + one OOO
    pattern + an empty interest list. Lets tests fall to uncategorized
    on anything not matching the unsubscribe + ooo patterns.
    """
    return RuleBasedClassifier(
        unsubscribe_patterns=[r"\bunsubscribe\b"],
        ooo_patterns=[r"\bout of office\b"],
    )


def _reply_event(
    text: str, *, channel: str = "email",
    person_id: str = "p1-test", reply_message_id: str = "msg_1",
) -> dict:
    """Build a synthetic reply event with the canonical shape."""
    return {
        "type": "reply_received",
        "person_id": person_id,
        "channel": channel,
        "reply_message_id": reply_message_id,
        "subject": "Re: test",
        "body": text,
    }


class _FakeLLMClient:
    """Test double — returns canned responses by reply-text-substring.

    Adapter for the :class:`LLMClient` Protocol. Tests construct with
    a list of (substring, LLMResponse) pairs; the first matching
    substring wins. A no-match returns a default uncategorized
    response (low confidence) so tests don't have to specify every
    expected text.

    Use the ``raise_on_substring`` kwarg to inject SDK-level failures
    (e.g., network errors). When the reply text contains the
    configured substring, the client raises the configured exception
    INSTEAD of returning a response — verifies the classifier's
    failure-mode handling.
    """

    def __init__(
        self,
        responses: list[tuple[str, LLMResponse]] | None = None,
        *,
        raise_on_substring: tuple[str, BaseException] | None = None,
        default_response: LLMResponse | None = None,
    ) -> None:
        self._responses = responses or []
        self._raise_on = raise_on_substring
        self._default = default_response or LLMResponse(
            category="uncategorized",
            confidence=0.3,
            rationale="default test fallback",
            input_tokens=100,
            output_tokens=20,
            model=DEFAULT_LLM_MODEL,
        )
        self.calls: list[tuple[str, str]] = []  # (text, model)

    def classify_text(
        self, reply_text: str, *, model: str = DEFAULT_LLM_MODEL,
    ) -> LLMResponse:
        self.calls.append((reply_text, model))
        if self._raise_on is not None:
            sub, exc = self._raise_on
            if sub in reply_text:
                raise exc
        for sub, resp in self._responses:
            if sub in reply_text:
                return resp
        return self._default


# ===========================================================================
# LLMResponse construction-time invariants
# ===========================================================================


class TestLLMResponseConstruction:

    def test_valid_long_tail_category_construct(self):
        r = LLMResponse(
            category="ooo",
            confidence=0.85,
            rationale="auto-reply phrasing",
            input_tokens=200,
            output_tokens=30,
            model="claude-haiku-4-5",
        )
        assert r.category == "ooo"
        assert r.confidence == pytest.approx(0.85)
        assert r.input_tokens == 200

    def test_unsubscribe_category_is_constructable(self):
        """LLMResponse allows ``unsubscribe`` at construction time —
        the dispatcher's refuse-loud guard catches at classify() time.
        This separates the two concerns (response shape vs dispatcher
        invariant) cleanly.
        """
        r = LLMResponse(
            category="unsubscribe",
            confidence=1.0,
            rationale="test — should be rejected by dispatcher guard",
            input_tokens=100,
            output_tokens=10,
            model=DEFAULT_LLM_MODEL,
        )
        assert r.category == "unsubscribe"  # the dispatcher will refuse

    def test_invalid_category_raises(self):
        with pytest.raises(ValueError, match="category must be one of"):
            LLMResponse(
                category="bogus_category",
                confidence=0.5,
                rationale="x",
                input_tokens=10,
                output_tokens=5,
                model=DEFAULT_LLM_MODEL,
            )

    def test_confidence_out_of_range_low_raises(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            LLMResponse(
                category="ooo",
                confidence=-0.1,
                rationale="x",
                input_tokens=10,
                output_tokens=5,
                model=DEFAULT_LLM_MODEL,
            )

    def test_confidence_out_of_range_high_raises(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            LLMResponse(
                category="ooo",
                confidence=1.1,
                rationale="x",
                input_tokens=10,
                output_tokens=5,
                model=DEFAULT_LLM_MODEL,
            )

    def test_negative_token_counts_raise(self):
        with pytest.raises(ValueError, match="input_tokens"):
            LLMResponse(
                category="ooo", confidence=0.5, rationale="x",
                input_tokens=-1, output_tokens=5,
                model=DEFAULT_LLM_MODEL,
            )
        with pytest.raises(ValueError, match="output_tokens"):
            LLMResponse(
                category="ooo", confidence=0.5, rationale="x",
                input_tokens=10, output_tokens=-1,
                model=DEFAULT_LLM_MODEL,
            )


# ===========================================================================
# build_llm_prompt — load-bearing template rendering
# ===========================================================================


class TestBuildLLMPrompt:

    def test_prompt_includes_reply_text(self):
        out = build_llm_prompt("hello world")
        assert "hello world" in out

    def test_prompt_explicit_unsubscribe_exclusion(self):
        """ADR-0029 D123 — the prompt MUST instruct the LLM not to
        return ``unsubscribe``. Defense-in-depth at the prompt layer
        (layer 2 of the three-layer carry-forward).
        """
        out = build_llm_prompt("any text")
        assert "DO NOT classify as \"unsubscribe\"" in out
        assert "legal-liability" in out.lower()

    def test_prompt_enumerates_all_long_tail_categories(self):
        """ADR-0029 D123 — every long-tail category MUST appear in the
        prompt's allowed-response list. A future contributor removing
        a category must update the prompt + the test.
        """
        out = build_llm_prompt("any text")
        for category in ("ooo", "wrong_person", "interest", "rejection",
                         "uncategorized"):
            assert category in out, (
                f"prompt missing long-tail category {category!r}"
            )

    def test_prompt_describes_json_output_shape(self):
        out = build_llm_prompt("any text")
        assert '"category"' in out
        assert '"confidence"' in out
        assert '"rationale"' in out

    def test_prompt_empty_reply_is_accepted(self):
        """Edge case: empty reply text doesn't crash the renderer."""
        out = build_llm_prompt("")
        # Still contains the prompt scaffolding.
        assert "uncategorized" in out

    def test_prompt_with_curly_braces_in_reply_text(self):
        """The template uses {reply_text} as a placeholder + the JSON
        example uses literal {{}} doubled escapes. A reply with raw
        ``{`` characters MUST not crash the formatter — str.format
        with format specifier injection.

        Our implementation uses str.format with only a {reply_text}
        named placeholder, and the JSON example uses escaped {{}}.
        Replies with curly braces are inserted verbatim AT the
        {reply_text} position; the format call resolves all literal
        {{}} pairs to {}. No injection vulnerability.
        """
        out = build_llm_prompt("I don't have a {valid} JSON {response} pattern")
        assert "I don't have a {valid} JSON {response} pattern" in out


# ===========================================================================
# compute_llm_cost_usd — uses the existing pricing table
# ===========================================================================


class TestComputeLLMCostUSD:

    def test_haiku_default_model_cost(self):
        """ADR-0029 D126 + COST_RATES_USD['anthropic']['claude-haiku-4-5'].
        500 input + 50 output tokens at Haiku 4.5 rates:
        500/1M × $0.80 + 50/1M × $4.00 = $0.0004 + $0.0002 = $0.0006.
        """
        cost = compute_llm_cost_usd(
            model="claude-haiku-4-5",
            input_tokens=500,
            output_tokens=50,
        )
        assert cost == pytest.approx(0.0006, abs=1e-9)

    def test_sonnet_cost_calculation(self):
        """Different model picks different rates from the table."""
        cost = compute_llm_cost_usd(
            model="claude-sonnet-4-6",
            input_tokens=500,
            output_tokens=50,
        )
        # 500/1M × $3.00 + 50/1M × $15.00 = $0.0015 + $0.00075 = $0.00225
        assert cost == pytest.approx(0.00225, abs=1e-9)

    def test_unknown_model_returns_zero_cost(self):
        """ADR-0029 D126 — missing pricing entry → 0.0 USD; classification
        proceeds, the cost event lands with amount_usd=0.0 + units=1.
        Operators see the missing-rates gap via Pillar G dashboards
        (zero-USD events for the unknown model).
        """
        cost = compute_llm_cost_usd(
            model="claude-future-9-0-not-yet-in-table",
            input_tokens=500,
            output_tokens=50,
        )
        assert cost == 0.0

    def test_zero_tokens_zero_cost(self):
        cost = compute_llm_cost_usd(
            model="claude-haiku-4-5",
            input_tokens=0,
            output_tokens=0,
        )
        assert cost == 0.0

    def test_large_token_counts_no_overflow(self):
        """Sanity: 1M tokens at Haiku rates = $0.80 input + $4.0 output."""
        cost = compute_llm_cost_usd(
            model="claude-haiku-4-5",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert cost == pytest.approx(4.8, abs=1e-6)


# ===========================================================================
# build_cost_incurred_payload — matches ADR-0006's contract
# ===========================================================================


class TestBuildCostIncurredPayload:

    def test_payload_shape_matches_adr_0006(self):
        reply = _reply_event("test", person_id="p1-test")
        response = LLMResponse(
            category="ooo",
            confidence=0.9,
            rationale="auto-reply",
            input_tokens=400,
            output_tokens=40,
            model="claude-haiku-4-5",
        )
        payload = build_cost_incurred_payload(
            reply_event=reply, response=response,
        )
        assert payload["type"] == "cost_incurred"
        assert payload["source"] == "reply_classifier_llm"
        assert payload["units"] == 1  # one call = one unit
        assert payload["model_or_endpoint"] == "claude-haiku-4-5"
        assert payload["person_id"] == "p1-test"
        assert payload["run_id"] is None  # not surfaced in v1

    def test_payload_amount_usd_computed(self):
        reply = _reply_event("test")
        response = LLMResponse(
            category="interest",
            confidence=0.8,
            rationale="positive signal",
            input_tokens=500,
            output_tokens=50,
            model="claude-haiku-4-5",
        )
        payload = build_cost_incurred_payload(
            reply_event=reply, response=response,
        )
        assert payload["amount_usd"] == pytest.approx(0.0006, abs=1e-9)

    def test_payload_handles_missing_person_id(self):
        """Pre-Pillar-D-Week-1 reply events may lack person_id; the
        cost emit gracefully sets it to None.
        """
        reply = {"type": "reply_received", "channel": "email",
                 "subject": "Re: test", "body": "hi"}
        response = LLMResponse(
            category="uncategorized", confidence=0.5, rationale="x",
            input_tokens=100, output_tokens=20,
            model="claude-haiku-4-5",
        )
        payload = build_cost_incurred_payload(
            reply_event=reply, response=response,
        )
        assert payload["person_id"] is None


# ===========================================================================
# _parse_llm_response_text — every shape the prompt may produce
# ===========================================================================


class TestParseLLMResponseText:

    def _parse(self, text: str, model: str = DEFAULT_LLM_MODEL) -> LLMResponse:
        return _llm._parse_llm_response_text(text, model=model)

    def test_clean_json_response(self):
        text = '{"category": "ooo", "confidence": 0.85, "rationale": "auto-reply"}'
        r = self._parse(text)
        assert r.category == "ooo"
        assert r.confidence == pytest.approx(0.85)
        assert r.rationale == "auto-reply"

    def test_json_with_markdown_fence(self):
        """Some models wrap JSON in ```json fences despite the prompt."""
        text = '```json\n{"category": "interest", "confidence": 0.7, "rationale": "x"}\n```'
        r = self._parse(text)
        assert r.category == "interest"
        assert r.confidence == pytest.approx(0.7)

    def test_json_with_bare_markdown_fence(self):
        """The bare ``` fence (no language tag) is also tolerated."""
        text = '```\n{"category": "rejection", "confidence": 0.6, "rationale": "x"}\n```'
        r = self._parse(text)
        assert r.category == "rejection"

    def test_json_with_surrounding_whitespace(self):
        text = '  \n  {"category": "wrong_person", "confidence": 0.9, "rationale": "x"}  \n  '
        r = self._parse(text)
        assert r.category == "wrong_person"

    def test_confidence_clamped_above_1(self):
        """ADR-0029 D125 — out-of-range confidence is clamped to [0, 1]."""
        text = '{"category": "ooo", "confidence": 1.5, "rationale": "x"}'
        r = self._parse(text)
        assert r.confidence == 1.0

    def test_confidence_clamped_below_0(self):
        text = '{"category": "ooo", "confidence": -0.5, "rationale": "x"}'
        r = self._parse(text)
        assert r.confidence == 0.0

    def test_confidence_as_integer(self):
        text = '{"category": "ooo", "confidence": 1, "rationale": "x"}'
        r = self._parse(text)
        assert r.confidence == 1.0

    def test_empty_response_raises(self):
        with pytest.raises(LLMResponseParseError, match="empty"):
            self._parse("")
        with pytest.raises(LLMResponseParseError, match="empty"):
            self._parse("   \n  ")

    def test_invalid_json_raises(self):
        with pytest.raises(LLMResponseParseError, match="not valid JSON"):
            self._parse("{not valid json")

    def test_non_object_top_level_raises(self):
        with pytest.raises(LLMResponseParseError, match="must be a JSON object"):
            self._parse('["a", "b"]')
        with pytest.raises(LLMResponseParseError, match="must be a JSON object"):
            self._parse('"just a string"')

    def test_missing_category_raises(self):
        with pytest.raises(LLMResponseParseError, match="missing 'category'"):
            self._parse('{"confidence": 0.5, "rationale": "x"}')

    def test_category_not_a_string_raises(self):
        with pytest.raises(LLMResponseParseError, match="must be a string"):
            self._parse('{"category": 42, "confidence": 0.5, "rationale": "x"}')

    def test_category_not_in_allowed_set_raises(self):
        with pytest.raises(LLMResponseParseError, match="must be one of"):
            self._parse(
                '{"category": "bogus", "confidence": 0.5, "rationale": "x"}'
            )

    def test_unsubscribe_category_rejected_at_parse(self):
        """CRITICAL — ADR-0029 D123 third defense-in-depth layer (parse
        layer). The LLM may not return ``unsubscribe`` per the prompt
        contract; if it does, the parse refuses BEFORE the dispatcher
        sees the response.
        """
        with pytest.raises(LLMResponseParseError, match="rule-only per ADR-0025 D97"):
            self._parse(
                '{"category": "unsubscribe", "confidence": 0.9, "rationale": "x"}'
            )

    def test_non_numeric_confidence_raises(self):
        with pytest.raises(LLMResponseParseError, match="confidence' must be numeric"):
            self._parse(
                '{"category": "ooo", "confidence": "high", "rationale": "x"}'
            )

    def test_missing_confidence_defaults_to_zero(self):
        """Missing confidence is tolerated; defaults to 0.0 (the
        asymmetric-failure-cost calculus per ADR-0029 D125 biases
        toward emit-with-low-confidence vs crash).
        """
        text = '{"category": "ooo", "rationale": "x"}'
        r = self._parse(text)
        assert r.confidence == 0.0

    def test_missing_rationale_defaults_to_empty_string(self):
        text = '{"category": "ooo", "confidence": 0.5}'
        r = self._parse(text)
        assert r.rationale == ""

    def test_response_model_field_preserves_input(self):
        """The ``model`` arg flows through to the returned LLMResponse."""
        text = '{"category": "ooo", "confidence": 0.5, "rationale": "x"}'
        r = self._parse(text, model="claude-sonnet-4-6")
        assert r.model == "claude-sonnet-4-6"


# ===========================================================================
# LLMFallbackClassifier dispatch ordering — ADR-0029 D124
# ===========================================================================


class TestDispatchOrdering:

    def test_unsubscribe_short_circuits_before_llm(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0029 D124 first-layer carry-forward of ADR-0025 D97.
        The LLM is NEVER consulted for unsubscribe — not as tiebreaker,
        not as second opinion, not at all.
        """
        # Configure the fake LLM with a marker — if it's called, the
        # ``calls`` list will be non-empty.
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        # The rule classifier matches "unsubscribe" pattern.
        result = classifier.classify(_reply_event("Please unsubscribe me now"))
        assert result.category == "unsubscribe"
        assert result.classification_method == "rule"
        assert result.confidence == 1.0
        # The LLM was NEVER called.
        assert fake_llm.calls == []

    def test_long_tail_rule_match_returns_as_is_no_llm(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0029 D124 — long-tail rule matches stay as-is. LLM doesn't
        re-classify rule decisions.
        """
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        # OOO rule matches.
        result = classifier.classify(_reply_event("I am out of office until Monday"))
        assert result.category == "ooo"
        assert result.classification_method == "rule"
        assert result.confidence == 1.0
        # The LLM was NEVER called.
        assert fake_llm.calls == []

    def test_uncategorized_rule_result_falls_to_llm(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0029 D124 — the narrow trigger. When rule returns
        ``uncategorized``, the LLM is consulted.
        """
        # The LLM returns ``interest`` for any reply containing "sounds".
        fake_response = LLMResponse(
            category="interest", confidence=0.75,
            rationale="positive signal",
            input_tokens=200, output_tokens=30,
            model="claude-haiku-4-5",
        )
        fake_llm = _FakeLLMClient([("sounds", fake_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        result = classifier.classify(_reply_event(
            "That sounds great, let's chat!"
        ))
        # The rule classifier returns uncategorized; the LLM upgrades
        # to interest.
        assert result.category == "interest"
        assert result.classification_method == "llm"
        assert result.confidence == pytest.approx(0.75)
        assert result.matched_pattern is None  # LLM has no regex
        # The LLM was called once.
        assert len(fake_llm.calls) == 1


# ===========================================================================
# LLMFallbackClassifier — refuse-loud guard (THIRD defense-in-depth layer)
# ===========================================================================


class TestRefuseLoudOnUnsubscribe:

    def test_llm_returning_unsubscribe_raises(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """CRITICAL — ADR-0029 D123 third layer. Even if the LLM
        somehow returns ``unsubscribe`` (prompt injection, model
        regression, parse error defaulting to bad category), the
        classifier dispatcher refuses with :class:`LLMRefusalError`.

        The :class:`LLMResponse` itself allows ``unsubscribe`` at
        construction time (testable separately above); this test pins
        the dispatcher-layer refusal.
        """
        # Craft a malicious LLMResponse with unsubscribe (in production
        # this couldn't happen — the parse layer also refuses — but
        # we test the third layer in isolation).
        malicious_response = LLMResponse(
            category="unsubscribe", confidence=1.0,
            rationale="prompt injection attempt",
            input_tokens=200, output_tokens=30,
            model=DEFAULT_LLM_MODEL,
        )
        fake_llm = _FakeLLMClient([("test", malicious_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        with pytest.raises(LLMRefusalError, match="ADR-0025 D97"):
            classifier.classify(_reply_event("test reply needing classification"))


# ===========================================================================
# Cost event emit — ADR-0029 D126
# ===========================================================================


class TestCostEventEmit:

    def test_cost_event_emitted_on_successful_llm_call(
        self, tmp_ledger, basic_rule_classifier,
    ):
        fake_response = LLMResponse(
            category="rejection", confidence=0.8,
            rationale="closing signal",
            input_tokens=400, output_tokens=40,
            model="claude-haiku-4-5",
        )
        fake_llm = _FakeLLMClient([("not interested", fake_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        classifier.classify(_reply_event(
            "We're not interested right now, thanks.",
            person_id="p2-test",
        ))
        # Walk the ledger; verify the cost event landed.
        all_events = list(tmp_ledger.all_events())
        cost_events = [e for e in all_events if e.get("type") == "cost_incurred"]
        assert len(cost_events) == 1
        ev = cost_events[0]
        assert ev["source"] == COST_SOURCE
        assert ev["model_or_endpoint"] == "claude-haiku-4-5"
        assert ev["units"] == 1
        # 400/1M × $0.80 + 40/1M × $4.00 = $0.000320 + $0.000160 = $0.000480
        assert ev["amount_usd"] == pytest.approx(0.000480, abs=1e-9)
        assert ev["person_id"] == "p2-test"

    def test_no_cost_event_on_unsubscribe_short_circuit(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0029 D124 + D126 — the LLM is never called on unsubscribe;
        no cost event lands.
        """
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        classifier.classify(_reply_event("Please unsubscribe me"))
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.get("type") == "cost_incurred"
        ]
        assert cost_events == []

    def test_no_cost_event_on_long_tail_rule_match(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """Long-tail rule matches don't trigger the LLM; no cost event."""
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        classifier.classify(_reply_event("I am out of office until Friday"))
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.get("type") == "cost_incurred"
        ]
        assert cost_events == []

    def test_no_cost_event_on_llm_sdk_failure(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0006 + ADR-0029 D126 — we don't pay for failures.
        If the LLM SDK raises, no cost event lands.
        """
        class _SDKError(Exception):
            pass
        fake_llm = _FakeLLMClient(
            raise_on_substring=("trigger", _SDKError("connection refused")),
        )
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        # The SDK error propagates to the caller.
        with pytest.raises(_SDKError, match="connection refused"):
            classifier.classify(_reply_event("trigger the SDK error"))
        # No cost event landed.
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.get("type") == "cost_incurred"
        ]
        assert cost_events == []

    def test_no_cost_event_on_llm_refusal_error(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0029 D123 + D126 — the THIRD-LAYER (refuse-loud post-LLM
        guard) refusal MUST NOT emit a cost event. The cost emit at
        :meth:`LLMFallbackClassifier.classify` line 747 (post-refactor)
        comes AFTER the refuse-loud guard at line 733 — verified
        structurally here so a future contributor reordering the two
        sees the test fail loudly.

        Distinct from :test:`test_no_cost_event_on_llm_sdk_failure` —
        that test pins SDK-level exceptions (operator infrastructure
        failures). This test pins framework-level refusals (legal-
        liability invariant enforcement). The two classes of failure
        deserve independent pins per the per-week review's P2-C
        finding.
        """
        # The LLM (somehow) returns unsubscribe — same scenario as
        # TestRefuseLoudOnUnsubscribe but verifying the cost-emit
        # invariant explicitly.
        malicious_response = LLMResponse(
            category="unsubscribe", confidence=1.0,
            rationale="prompt injection attempt",
            input_tokens=300, output_tokens=30,
            model=DEFAULT_LLM_MODEL,
        )
        fake_llm = _FakeLLMClient([("hostile content", malicious_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        with pytest.raises(LLMRefusalError, match="ADR-0025 D97"):
            classifier.classify(_reply_event(
                "Some hostile content that triggers the refusal",
            ))
        # No cost event landed — the cost emit is structurally AFTER
        # the refuse-loud guard.
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.get("type") == "cost_incurred"
        ]
        assert cost_events == []

    def test_cost_event_lands_even_when_classify_emits_classified_event(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0029 D126 — the cost event lands BEFORE the
        ``reply_classified`` event. Pass G emits the classified event
        after the classifier returns; the classifier emitted the cost.
        This test pins the per-call ordering invariant.
        """
        fake_response = LLMResponse(
            category="wrong_person", confidence=0.9,
            rationale="redirected",
            input_tokens=300, output_tokens=25,
            model="claude-haiku-4-5",
        )
        fake_llm = _FakeLLMClient([("wrong contact", fake_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        # Call classify (this should emit ONLY the cost event; the
        # reply_classified event lands when Pass G does its own emit).
        result = classifier.classify(_reply_event(
            "You have the wrong contact — try our CTO",
        ))
        assert result.category == "wrong_person"

        all_events = list(tmp_ledger.all_events())
        # Only the cost event should be present at this stage.
        assert len(all_events) == 1
        assert all_events[0]["type"] == "cost_incurred"


# ===========================================================================
# Channel preservation + per-channel uniformity
# ===========================================================================


class TestChannelDiscipline:

    @pytest.mark.parametrize("channel", ["email", "linkedin", "twitter"])
    def test_classify_works_across_channels(
        self, channel, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0014 D33 extended by ADR-0025 D96 — the classifier is
        channel-agnostic. The reply event carries the channel; the
        classifier reads the body text uniformly. The cost event the
        classifier emits also carries no channel (per ADR-0006 —
        cost is operator-level, not channel-scoped).
        """
        fake_response = LLMResponse(
            category="interest", confidence=0.7,
            rationale="positive",
            input_tokens=100, output_tokens=20,
            model="claude-haiku-4-5",
        )
        fake_llm = _FakeLLMClient([("yes", fake_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        result = classifier.classify(_reply_event(
            "yes please tell me more", channel=channel,
        ))
        assert result.category == "interest"
        assert result.classification_method == "llm"


# ===========================================================================
# Configuration knobs — model override + accessor properties
# ===========================================================================


class TestConfiguration:

    def test_default_model_is_haiku(
        self, tmp_ledger, basic_rule_classifier,
    ):
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        assert classifier.model == "claude-haiku-4-5"
        assert DEFAULT_LLM_MODEL == "claude-haiku-4-5"

    def test_model_override_at_construction(
        self, tmp_ledger, basic_rule_classifier,
    ):
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
            model="claude-sonnet-4-6",
        )
        assert classifier.model == "claude-sonnet-4-6"

    def test_model_passed_through_to_llm_client(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """The configured model name flows to the LLM client per call."""
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
            model="claude-sonnet-4-6",
        )
        classifier.classify(_reply_event("some uncategorized text"))
        # The fake records (text, model) per call.
        assert len(fake_llm.calls) == 1
        _text, model_used = fake_llm.calls[0]
        assert model_used == "claude-sonnet-4-6"

    def test_rule_classifier_accessor(
        self, tmp_ledger, basic_rule_classifier,
    ):
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        # Pillar I CLI introspection surface — exposes the wrapped
        # rule classifier for "show me the loaded patterns" queries.
        assert classifier.rule_classifier is basic_rule_classifier


# ===========================================================================
# Drop-in compatibility with Pass G — same .classify(reply) -> ClassifierResult
# ===========================================================================


class TestPassGCompatibility:

    def test_classify_signature_matches_rule_classifier(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """ADR-0029 D124 — the LLMFallbackClassifier.classify signature
        matches the rule classifier's signature exactly so it's
        drop-in compatible with Pass G's caller. The
        :class:`ClassifierResult` shape is unchanged.
        """
        fake_response = LLMResponse(
            category="interest", confidence=0.7, rationale="x",
            input_tokens=100, output_tokens=20,
            model="claude-haiku-4-5",
        )
        fake_llm = _FakeLLMClient([("hello", fake_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        result = classifier.classify(_reply_event(
            "hello, that sounds interesting"
        ))
        assert isinstance(result, ClassifierResult)
        assert result.category == "interest"
        # The matched_pattern is None for LLM classifications — the
        # rule classifier's pattern surface is preserved separately.
        assert result.matched_pattern is None


# ===========================================================================
# End-to-end via reconcile.run_pass_g — the integration surface
# ===========================================================================


class TestReconcileIntegration:
    """ADR-0029 D124 — the LLMFallbackClassifier is drop-in compatible
    with :func:`orchestrator.reconcile.run_pass_g`. Pass G receives
    the wrapped classifier via ``classifier=`` kwarg + invokes
    ``classifier.classify(reply_event)`` per reply; the LLM dispatch
    happens transparently inside the classifier wrapper.
    """

    def _ts(self, minutes_ago: int = 5) -> str:
        return (
            datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def test_pass_g_with_llm_fallback_emits_classified_event(
        self, tmp_ledger, basic_rule_classifier,
    ):
        import reconcile as _reconcile
        # Seed a reply event the rule classifier returns uncategorized
        # for (no matching pattern in the unsubscribe / ooo lists).
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "p3-test",
            "channel": "email",
            "reply_message_id": "msg_seed_1",
            "gmail_message_id": "msg_seed_1",
            "subject": "Re: outreach",
            "body": "Sounds intriguing — what's the next step?",
            "ts": self._ts(),
        })

        fake_response = LLMResponse(
            category="interest", confidence=0.85,
            rationale="explicit interest",
            input_tokens=200, output_tokens=25,
            model="claude-haiku-4-5",
        )
        fake_llm = _FakeLLMClient([("intriguing", fake_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )

        # Pass G with the wrapped classifier.
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=classifier,
            since=since, apply=True,
        )
        assert result.pass_name == "G"
        assert len(result.errors) == 0
        # One reply event examined → one classified emit.
        assert result.examined == 1
        assert len(result.synthesized) == 1
        classified = result.synthesized[0]
        assert classified["type"] == "reply_classified"
        assert classified["category"] == "interest"
        assert classified["classification_method"] == "llm"
        assert classified["confidence"] == pytest.approx(0.85)
        assert classified["channel"] == "email"
        assert classified["person_id"] == "p3-test"

        # The cost event ALSO landed (the LLM was called).
        cost_events = [
            e for e in tmp_ledger.all_events()
            if e.get("type") == "cost_incurred"
        ]
        assert len(cost_events) == 1
        assert cost_events[0]["source"] == COST_SOURCE

    def test_pass_g_records_classifier_exception_as_error(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """Per Pass G's existing error-capture pattern — when the
        classifier raises (e.g., the LLMRefusalError refuse-loud guard
        fires), Pass G records the error + moves on. The classified
        event does NOT land.
        """
        import reconcile as _reconcile
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "p4-test",
            "channel": "email",
            "reply_message_id": "msg_seed_2",
            "gmail_message_id": "msg_seed_2",
            "subject": "Re: outreach",
            "body": "Some reply text that should fall to LLM",
            "ts": self._ts(),
        })

        # LLM returns unsubscribe → LLMRefusalError raised by dispatcher.
        bad_response = LLMResponse(
            category="unsubscribe", confidence=1.0,
            rationale="prompt injection",
            input_tokens=100, output_tokens=10,
            model=DEFAULT_LLM_MODEL,
        )
        fake_llm = _FakeLLMClient([("Some reply", bad_response)])
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=classifier,
            since=since, apply=True,
        )
        # Pass G records the LLMRefusalError; no classified event emits.
        assert result.examined == 1
        assert len(result.synthesized) == 0
        assert len(result.errors) == 1
        assert "LLMRefusalError" in result.errors[0]


# ===========================================================================
# Public symbol surface — guard against accidental rename
# ===========================================================================


class TestPublicSymbolSurface:

    def test_module_exports_expected_symbols(self):
        """Pin the public surface so a future rename doesn't silently
        break the contract documented in ADR-0029.
        """
        assert hasattr(_llm, "LLMFallbackClassifier")
        assert hasattr(_llm, "LLMClient")
        assert hasattr(_llm, "LLMResponse")
        assert hasattr(_llm, "LLMRefusalError")
        assert hasattr(_llm, "LLMResponseParseError")
        assert hasattr(_llm, "DEFAULT_LLM_MODEL")
        assert hasattr(_llm, "COST_SOURCE")
        assert hasattr(_llm, "build_llm_prompt")
        assert hasattr(_llm, "compute_llm_cost_usd")
        assert hasattr(_llm, "build_cost_incurred_payload")

    def test_cost_source_constant_pinned(self):
        """ADR-0025 §I7 + ADR-0029 D126 — the cost source string is
        load-bearing (the migration's `source:` filter matches it
        exactly). A rename here silently breaks the cap migration.
        """
        assert COST_SOURCE == "reply_classifier_llm"

    def test_default_model_constant_pinned(self):
        """ADR-0029 D122 — the default model name is load-bearing
        (pricing table lookup; operator-visible documentation).
        """
        assert DEFAULT_LLM_MODEL == "claude-haiku-4-5"

    def test_extract_reply_text_module_level_export(self):
        """The Week 6-8 follow-up commit (per the per-week review's
        P2-B finding) promoted :meth:`RuleBasedClassifier._extract_text`
        to a module-level :func:`extract_reply_text` function in
        ``reply_classifier`` so the LLM fallback classifier can import
        it without the private-method coupling.

        Pins:
          (a) the module-level function exists + is callable.
          (b) the rule classifier's static method delegates to it.
          (c) both produce the same output for the same input.
        """
        from reply_classifier import (
            RuleBasedClassifier as _RC,
            extract_reply_text as _extract,
        )
        # (a) Module-level function exists + extracts uniformly.
        ev = {"subject": "Re: x", "body": "hello", "snippet": "world"}
        out = _extract(ev)
        assert "Re: x" in out and "hello" in out and "world" in out
        # (b) + (c) Static method delegates → same output.
        assert _RC._extract_text(ev) == out


# ===========================================================================
# Text-extraction coupling — single source of truth across rule + LLM paths
# ===========================================================================


class TestTextExtractionCoupling:
    """ADR-0029 D124 — the LLM fallback MUST read the same text the
    rule classifier inspected so the LLM is asked to classify the SAME
    content that fell to uncategorized. A divergence here would let
    the LLM see different content than the rule — operator-confusing +
    breaks the "LLM extends rule coverage" model.

    Per the Week 6-8 follow-up commit's P2-B fix — the `extract_reply_text`
    function is the module-level single source of truth shared by both
    classifiers. These tests pin the coupling so a future contributor
    refactoring one side without the other fails loudly.
    """

    def test_llm_fallback_uses_same_text_as_rule_classifier(
        self, tmp_ledger, basic_rule_classifier,
    ):
        """Pin: the LLM is called with text extracted via the SAME
        helper the rule classifier uses. Verified by inspecting the
        fake LLM's recorded call text — it must match what
        :func:`extract_reply_text` returns for the same reply event.
        """
        from reply_classifier import extract_reply_text
        fake_llm = _FakeLLMClient()
        classifier = LLMFallbackClassifier(
            rule_classifier=basic_rule_classifier,
            llm_client=fake_llm,
            led=tmp_ledger,
        )
        ev = _reply_event(
            "This is some text the rule classifier didn't match",
        )
        classifier.classify(ev)
        # The fake recorded one call.
        assert len(fake_llm.calls) == 1
        text_sent_to_llm, _model = fake_llm.calls[0]
        # The text the LLM saw matches extract_reply_text exactly.
        assert text_sent_to_llm == extract_reply_text(ev)
