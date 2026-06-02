"""Pillar D Week 2 — rule-based reply classifier unit tests.

Covers:

* Pattern YAML loading (refuse-loud per ADR-0026 D103).
* RuleBasedClassifier construction + pattern compilation.
* Rule-based unsubscribe detection (every default pattern matches a
  real-world example reply text).
* Per-channel discrimination (the classifier consumes the channel
  field from the reply event).
* Output event shape per ADR-0025 D97 (every emitted ``reply_classified``
  event carries the contract fields).
* The load-bearing legal-liability invariant per ADR-0025 D97 +
  PILLAR-PLAN §5 — every ``category=unsubscribe`` ClassifierResult
  carries ``classification_method='rule'`` AND ``confidence=1.0`` at
  construction time (defense-in-depth source-level check).
* Pillar D Week 2 uncategorized fallback per ADR-0026 D107 (non-
  matching replies emit ``category=uncategorized``).
* Pattern-list-as-input (operator-tunable YAML loads cleanly via
  ``from_yaml``).
* Run-pass-g integration via reconcile.run_pass_g (idempotence,
  per-channel discrimination, bounce-not-classified, error path).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import ledger as _ledger
import reconcile as _reconcile
import reply_classifier as _classifier
from reply_classifier import (
    CATEGORIES,
    DEFAULT_PATTERN_DIR,
    DEFAULT_PATTERN_PATH,
    DISPATCH_PRIORITY,
    PATTERN_FILE_BY_CATEGORY,
    SUPPORTED_PATTERN_SCHEMA_VERSION,
    WEEK_2_DELIVERED_CATEGORIES,
    WEEK_3_DELIVERED_CATEGORIES,
    ClassifierResult,
    PatternLoadError,
    RuleBasedClassifier,
    build_classified_payload,
    emit_classified_event,
    load_pattern_file,
    load_unsubscribe_patterns,
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
def factory_patterns_path() -> Path:
    """Returns the path to the factory example unsubscribe pattern file
    shipped in config-template/. Anchors against the repo root for
    reliability. Week 2 fixture; Week 3 callers also use
    :func:`factory_pattern_dir` for the full-long-tail load.
    """
    repo_root = Path(__file__).resolve().parent.parent
    p = repo_root / "config-template" / "unsubscribe-patterns.example.yml"
    assert p.exists(), f"factory pattern example missing: {p}"
    return p


@pytest.fixture
def factory_pattern_dir(tmp_path) -> Path:
    """Returns a tmp directory populated with every category's factory
    example file copied from config-template/ — each renamed to drop
    the ``.example.`` infix so RuleBasedClassifier.from_yaml_dir picks
    them up under the production-name convention. Per ADR-0027 D109's
    naming: ``{category}-patterns.yml``.
    """
    import shutil
    repo_root = Path(__file__).resolve().parent.parent
    dest = tmp_path / "classifier"
    dest.mkdir()
    for category, prod_name in PATTERN_FILE_BY_CATEGORY.items():
        example_name = prod_name.replace(".yml", ".example.yml")
        src = repo_root / "config-template" / example_name
        assert src.exists(), f"factory example missing for {category}: {src}"
        shutil.copy(src, dest / prod_name)
    return dest


@pytest.fixture
def factory_classifier(factory_patterns_path) -> RuleBasedClassifier:
    """Week 2 fixture — single-category (unsubscribe-only) classifier
    via from_yaml(path). Preserved unchanged for backwards-compat with
    the Week 2 test corpus.
    """
    return RuleBasedClassifier.from_yaml(factory_patterns_path)


@pytest.fixture
def full_factory_classifier(factory_pattern_dir) -> RuleBasedClassifier:
    """Week 3 fixture — full long-tail-aware classifier via
    from_yaml_dir(dir). Loads every category's factory file from a
    tmp directory.
    """
    return RuleBasedClassifier.from_yaml_dir(factory_pattern_dir)


def _write_patterns(path: Path, patterns: list[str], *, version=1) -> Path:
    """Write a pattern YAML file for tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": version, "patterns": patterns}
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _old_ts(minutes: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)) \
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ===========================================================================
# Pattern YAML loading (ADR-0026 D103 — refuse-loud)
# ===========================================================================


class TestPatternLoading:

    def test_load_factory_example_succeeds(self, factory_patterns_path):
        patterns = load_unsubscribe_patterns(factory_patterns_path)
        assert len(patterns) >= 10, (
            "factory example should ship ≥10 conservative defaults"
        )
        # Every entry compiles (the loader verifies but pin here too).
        for p in patterns:
            re.compile(p)

    def test_load_missing_file_raises_with_bootstrap_message(self, tmp_path):
        missing = tmp_path / "nonexistent" / "unsubscribe-patterns.yml"
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(missing)
        # The error message MUST guide bootstrap per ADR-0026 D103.
        assert "Bootstrap:" in str(exc.value)
        assert str(missing.parent) in str(exc.value)
        assert "config-template/unsubscribe-patterns.example.yml" in str(exc.value)

    def test_load_unparseable_yaml_raises(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text("{{{ this is not valid yaml", encoding="utf-8")
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(bad)
        assert "unparseable" in str(exc.value)

    def test_load_non_mapping_raises(self, tmp_path):
        bad = tmp_path / "list_at_top.yml"
        bad.write_text("- not a mapping\n- but a list\n", encoding="utf-8")
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(bad)
        assert "must be a YAML mapping" in str(exc.value)

    def test_load_wrong_version_raises(self, tmp_path):
        p = _write_patterns(tmp_path / "v99.yml", ["\\bunsubscribe\\b"], version=99)
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(p)
        assert "only version=1 supported" in str(exc.value)
        assert "got version=99" in str(exc.value)

    def test_load_missing_patterns_key_raises(self, tmp_path):
        bad = tmp_path / "no_patterns.yml"
        bad.write_text("version: 1\n", encoding="utf-8")
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(bad)
        assert "missing required 'patterns' key" in str(exc.value)

    def test_load_patterns_not_list_raises(self, tmp_path):
        bad = tmp_path / "patterns_dict.yml"
        bad.write_text("version: 1\npatterns: not a list\n", encoding="utf-8")
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(bad)
        assert "'patterns' must be a YAML list" in str(exc.value)

    def test_load_non_string_pattern_raises(self, tmp_path):
        bad = tmp_path / "bad_pattern.yml"
        bad.write_text(
            "version: 1\npatterns:\n  - \\bunsubscribe\\b\n  - 42\n",
            encoding="utf-8",
        )
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(bad)
        assert "pattern at index 1 is not a string" in str(exc.value)

    def test_load_invalid_regex_raises(self, tmp_path):
        # Unbalanced bracket — re.compile rejects.
        bad = tmp_path / "bad_regex.yml"
        bad.write_text(
            "version: 1\npatterns:\n  - \"[unbalanced\"\n",
            encoding="utf-8",
        )
        with pytest.raises(PatternLoadError) as exc:
            load_unsubscribe_patterns(bad)
        assert "pattern at index 0" in str(exc.value)
        assert "failed to compile" in str(exc.value)

    def test_load_empty_patterns_list_succeeds(self, tmp_path):
        """A defensible operator choice — an empty pattern list means
        the classifier classifies every reply as uncategorized (a
        useful posture for an operator who only wants the classifier's
        VISIBILITY without any rule firing). The loader should NOT
        refuse empty lists; the operator's deliberate choice is honored.
        """
        p = _write_patterns(tmp_path / "empty.yml", [])
        patterns = load_unsubscribe_patterns(p)
        assert patterns == []

    def test_from_yaml_classmethod_uses_loader(self, factory_patterns_path):
        c = RuleBasedClassifier.from_yaml(factory_patterns_path)
        # Constructed; classify against a known unsubscribe phrase.
        result = c.classify({"subject": "Re: hi", "body": "please unsubscribe"})
        assert result.category == "unsubscribe"

    def test_supported_pattern_schema_version_is_one(self):
        # Pin per ADR-0026 D103 — future schema bumps land via a
        # Pillar B policy/000N migration.
        assert SUPPORTED_PATTERN_SCHEMA_VERSION == 1


# ===========================================================================
# ClassifierResult construction-time invariants (ADR-0025 D97)
# ===========================================================================


class TestClassifierResultInvariants:
    """The construction-time enforcement of the legal-liability invariant
    per ADR-0025 D97 is the source-level defense-in-depth alongside the
    event-shape test in test_multi_channel_coherence.py."""

    def test_unsubscribe_with_rule_method_constructs(self):
        r = ClassifierResult(
            category="unsubscribe",
            classification_method="rule",
            confidence=1.0,
            matched_pattern="\\bunsubscribe\\b",
        )
        assert r.category == "unsubscribe"

    def test_unsubscribe_with_llm_method_refused(self):
        # The load-bearing legal-liability invariant per ADR-0025 D97.
        with pytest.raises(ValueError) as exc:
            ClassifierResult(
                category="unsubscribe",
                classification_method="llm",
                confidence=0.99,
                matched_pattern=None,
            )
        assert "ADR-0025 D97 invariant" in str(exc.value)
        assert "category=unsubscribe MUST carry classification_method='rule'" \
            in str(exc.value)
        # The error message names the rationale so future contributors
        # don't have to chase the ADR to understand the refusal.
        assert "PILLAR-PLAN §5" in str(exc.value)

    def test_unsubscribe_with_sub_unit_confidence_refused(self):
        with pytest.raises(ValueError) as exc:
            ClassifierResult(
                category="unsubscribe",
                classification_method="rule",
                confidence=0.95,
                matched_pattern="\\bunsubscribe\\b",
            )
        assert "ADR-0025 D97 invariant" in str(exc.value)
        assert "confidence=1.0" in str(exc.value)

    def test_unknown_category_refused(self):
        with pytest.raises(ValueError) as exc:
            ClassifierResult(
                category="something_else",
                classification_method="rule",
                confidence=1.0,
                matched_pattern=None,
            )
        assert "category must be one of" in str(exc.value)

    def test_unknown_classification_method_refused(self):
        with pytest.raises(ValueError) as exc:
            ClassifierResult(
                category="uncategorized",
                classification_method="hand_coded",
                confidence=1.0,
                matched_pattern=None,
            )
        assert "classification_method must be 'rule' or 'llm'" in str(exc.value)

    def test_non_unsubscribe_with_llm_method_allowed(self):
        # Week 6-8's LLM fallback constructs these for the long-tail
        # categories. The invariant only constrains UNSUBSCRIBE.
        r = ClassifierResult(
            category="ooo",
            classification_method="llm",
            confidence=0.85,
            matched_pattern=None,
        )
        assert r.classification_method == "llm"

    def test_categories_constant_is_complete(self):
        # Pin per ADR-0025 D97 — exactly six categories.
        assert CATEGORIES == frozenset({
            "unsubscribe", "ooo", "wrong_person",
            "interest", "rejection", "uncategorized",
        })

    def test_week_2_delivered_categories_subset(self):
        # Pin per ADR-0026 D107 — Week 2 ships unsubscribe +
        # uncategorized only.
        assert WEEK_2_DELIVERED_CATEGORIES == frozenset({
            "unsubscribe", "uncategorized",
        })
        assert WEEK_2_DELIVERED_CATEGORIES.issubset(CATEGORIES)


# ===========================================================================
# Rule-based unsubscribe detection
# ===========================================================================


class TestRuleBasedClassification:
    """Every default pattern must match a real-world example reply text.

    The 12 patterns in config-template/unsubscribe-patterns.example.yml
    each get a corresponding test case below pinning the expected match
    behavior. If a contributor changes a pattern, the test must be
    updated alongside — the test corpus IS the regression surface for
    the factory pattern set.
    """

    @pytest.mark.parametrize("body,expected_fragment", [
        # Pattern 1: bare "unsubscribe"
        ("please unsubscribe me", "unsubscribe"),
        ("UNSUBSCRIBE", "unsubscribe"),
        # Pattern 2: "unsub" shorthand
        ("reply unsub to stop", "unsub"),
        # Pattern 3: "remove me from your list" / "take me off"
        ("please remove me from your list", "remove me from your"),
        ("Could you take me off your list?", "take me off"),
        ("remove me from your email list", "remove me from your"),
        # Pattern 4: "please stop emailing"
        ("Please stop emailing me", "please stop"),
        ("please stop contacting me", "please stop"),
        # Pattern 5: "do not contact me"
        ("Do not contact me again", "do not"),
        ("do not email me again", "do not"),
        # Pattern 6: "opt out" / "opt-out" / "opt me out" (the imperative-
        # with-pronoun form was a Week 2 follow-up addition — the
        # original `\bopt[- ]?out\b` missed it; tightened to
        # `\bopt(?:\s+me)?\s*[- ]?out\b`).
        ("I want to opt-out", "opt"),
        ("please opt out", "opt"),
        ("opt me out", "opt"),
        ("please opt me out from this list", "opt"),
        # Pattern 7: line-start "stop emails"
        ("Stop emailing me please.", "(?:stop|cease)"),
        # Pattern 8: "no more emails"
        ("Please send no more emails", "no more"),
        ("no more messages please", "no more"),
        # Pattern 9: SMS-style STOP standalone
        ("STOP", "stop"),
        ("STOP.", "stop"),
        # Pattern 10: "leave me alone"
        ("please leave me alone", "leave me alone"),
        # Pattern 11: "remove from mailing list" / distribution / email
        ("Remove me from the mailing list", "remove"),
        ("remove me from this distribution list", "remove"),
        # Pattern 12: "unsubscribe me"
        ("please unsubscribe me from this", "unsubscribe"),
    ])
    def test_unsubscribe_pattern_matches(
        self, factory_classifier, body, expected_fragment,
    ):
        reply = {"subject": "Re: outreach", "body": body}
        result = factory_classifier.classify(reply)
        assert result.category == "unsubscribe", (
            f"body={body!r} expected unsubscribe match; got {result}"
        )
        assert result.classification_method == "rule"
        assert result.confidence == 1.0
        # The matched_pattern field is the audit surface — the regex
        # source string that fired. The fragment (a substring of the
        # pattern source) confirms the EXPECTED pattern won. Using
        # literal substring check (not re.search) because the regex
        # source contains anchors like `^` that would mis-interpret.
        assert result.matched_pattern is not None
        assert expected_fragment in result.matched_pattern, (
            f"matched_pattern={result.matched_pattern!r} does not "
            f"contain expected fragment {expected_fragment!r}"
        )

    @pytest.mark.parametrize("body", [
        # Conservative defaults SHOULD NOT match these legitimate replies.
        "Thanks for reaching out — would love to chat next week.",
        "Sounds interesting — can you send pricing?",
        "I'm out of office until next Monday.",
        "You have the wrong person — try our CTO.",
        "Not now but maybe Q3.",
        "We just signed with a competitor.",
        # Tricky no-match cases:
        # "stop by my office for coffee" — "stop" alone shouldn't fire.
        "Could you stop by my office for coffee?",
        # past-tense unsubscribed — discussing a prior action, not
        # requesting one.
        "We unsubscribed from that newsletter yesterday.",
        # "unsubsidized" doesn't trigger "\\bunsub\\b".
        "Unsubsidized loans are off the table.",
    ])
    def test_legitimate_replies_classified_as_uncategorized(
        self, factory_classifier, body,
    ):
        reply = {"subject": "Re: outreach", "body": body}
        result = factory_classifier.classify(reply)
        assert result.category == "uncategorized", (
            f"body={body!r} expected uncategorized; got {result}"
        )
        assert result.classification_method == "rule"
        assert result.confidence == 1.0
        assert result.matched_pattern is None

    def test_classifier_reads_subject_field(self, factory_classifier):
        # Subject-only match — the classifier reads subject + body.
        reply = {"subject": "unsubscribe please", "body": ""}
        result = factory_classifier.classify(reply)
        assert result.category == "unsubscribe"

    def test_classifier_reads_snippet_field(self, factory_classifier):
        # Snippet-only match (Pillar D Week 3+ per-channel reply
        # passes may populate `snippet` instead of `body`).
        reply = {"subject": "Re: hi", "snippet": "please stop emailing me"}
        result = factory_classifier.classify(reply)
        assert result.category == "unsubscribe"

    def test_first_matching_pattern_wins(self, tmp_path):
        # Per ADR-0026 D102's _extract_text + classify: the FIRST
        # pattern that matches wins (regex short-circuits). Operator
        # ordering controls which pattern's name surfaces in the
        # matched_pattern field for the audit trail.
        patterns = [
            r"\bspecific_phrase\b",     # would match first
            r"\bunsubscribe\b",         # would match second
        ]
        p = _write_patterns(tmp_path / "ordered.yml", patterns)
        c = RuleBasedClassifier.from_yaml(p)
        result = c.classify({
            "subject": "",
            "body": "please unsubscribe me from this specific_phrase list",
        })
        # First pattern wins in source order.
        assert result.matched_pattern == r"\bspecific_phrase\b"

    def test_case_insensitive_matching_default(self, tmp_path):
        # The classifier defaults to re.IGNORECASE — the factory
        # patterns include (?i) for operator clarity but the loader
        # doesn't require it.
        patterns = [r"\bunsubscribe\b"]  # no (?i) inline
        p = _write_patterns(tmp_path / "no_inline_flag.yml", patterns)
        c = RuleBasedClassifier.from_yaml(p)
        result = c.classify({"subject": "", "body": "UNSUBSCRIBE NOW"})
        assert result.category == "unsubscribe"

    def test_empty_pattern_list_classifies_everything_as_uncategorized(
        self, tmp_path,
    ):
        # Operator chose to ship NO patterns — every reply gets the
        # uncategorized fallback. A defensible posture (Week 2 ledger
        # visibility without rule firing).
        p = _write_patterns(tmp_path / "empty.yml", [])
        c = RuleBasedClassifier.from_yaml(p)
        result = c.classify({"subject": "", "body": "please unsubscribe me"})
        assert result.category == "uncategorized"

    def test_classifier_handles_missing_text_fields(self, factory_classifier):
        # Defensive: a reply event with no subject/body/snippet should
        # not crash; the classifier sees empty text + classifies as
        # uncategorized.
        result = factory_classifier.classify({})
        assert result.category == "uncategorized"

    def test_classifier_handles_non_string_text_fields(self, factory_classifier):
        # Defensive: a reply with a non-string `body` (e.g., None or a
        # dict — shouldn't happen but) should not crash.
        result = factory_classifier.classify({
            "subject": None, "body": None, "snippet": 42,
        })
        assert result.category == "uncategorized"


# ===========================================================================
# emit_classified_event (ADR-0025 D97 event shape)
# ===========================================================================


class TestEmitClassifiedEvent:

    def test_emit_creates_reply_classified_event(
        self, tmp_ledger, factory_classifier,
    ):
        reply_event = {
            "type": "reply_received",
            "person_id": "person-a",
            "channel": "email",
            "gmail_message_id": "gid_001",
            "gmail_thread_id": "tid_001",
            "subject": "Re: outreach",
            "body": "please unsubscribe me",
        }
        result = factory_classifier.classify(reply_event)
        written = emit_classified_event(tmp_ledger, reply_event, result)
        assert written["type"] == "reply_classified"
        assert written["person_id"] == "person-a"
        assert written["channel"] == "email"
        assert written["reply_message_id"] == "gid_001"
        assert written["gmail_thread_id"] == "tid_001"
        assert written["category"] == "unsubscribe"
        assert written["classification_method"] == "rule"
        assert written["confidence"] == 1.0
        assert written["matched_pattern"] is not None
        assert written["_emitted_by"] == "reply_classifier"
        # The event landed in the ledger.
        assert tmp_ledger.query_by_gmail_message_id("gid_001") is None, (
            "reply_classified doesn't carry gmail_message_id at the "
            "top level (it carries reply_message_id) — the gmail_msg "
            "index shouldn't see it."
        )

    def test_emit_preserves_reply_to_intent_id_when_present(
        self, tmp_ledger, factory_classifier,
    ):
        # Week 3+ per-channel reply passes populate reply_to_intent_id;
        # Pass B's pre-Pillar-D emits do NOT (it's None for email).
        reply_event = {
            "type": "li_dm_reply_received",
            "person_id": "person-b",
            "channel": "linkedin",
            "reply_message_id": "lin_msg_001",
            "reply_to_intent_id": "snd_INTENT_LI_DM_001",
            "subject": "",
            "body": "please stop messaging me",
        }
        result = factory_classifier.classify(reply_event)
        written = emit_classified_event(tmp_ledger, reply_event, result)
        assert written["channel"] == "linkedin"
        assert written["reply_message_id"] == "lin_msg_001"
        assert written["reply_to_intent_id"] == "snd_INTENT_LI_DM_001"

    def test_emit_defaults_channel_to_email_when_absent(
        self, tmp_ledger, factory_classifier,
    ):
        # Per ADR-0025 §Migration/rollout item 3 + ADR-0026 D104 —
        # pre-Pillar-D-Week-1 Pass B emits lack the channel field;
        # treat absent channel as email per the historical default.
        reply_event = {
            "type": "reply_received",
            "person_id": "person-c",
            "gmail_message_id": "gid_002",
            # no channel field — pre-Week-1 emit shape
            "subject": "Re: hi",
            "body": "please unsubscribe",
        }
        result = factory_classifier.classify(reply_event)
        written = emit_classified_event(tmp_ledger, reply_event, result)
        assert written["channel"] == "email"

    def test_emit_omits_gmail_thread_id_when_reply_lacks_one(
        self, tmp_ledger, factory_classifier,
    ):
        # LinkedIn / Twitter / calendar replies (Week 3+) carry
        # platform-specific thread identifiers, NOT gmail_thread_id.
        reply_event = {
            "type": "li_dm_reply_received",
            "person_id": "person-d",
            "channel": "linkedin",
            "reply_message_id": "lin_msg_002",
            "subject": "",
            "body": "stop messaging me",
        }
        result = factory_classifier.classify(reply_event)
        written = emit_classified_event(tmp_ledger, reply_event, result)
        assert "gmail_thread_id" not in written

    def test_emit_uncategorized_fallback_lands_in_ledger(
        self, tmp_ledger, factory_classifier,
    ):
        # Per ADR-0026 D107 — the uncategorized fallback IS an emit
        # (not a no-op) so the operator's ledger has full visibility
        # into "the classifier saw this reply but had no match."
        reply_event = {
            "type": "reply_received",
            "person_id": "person-e",
            "channel": "email",
            "gmail_message_id": "gid_uncat",
            "subject": "Re: outreach",
            "body": "Sounds great, let's chat next week.",
        }
        result = factory_classifier.classify(reply_event)
        assert result.category == "uncategorized"
        written = emit_classified_event(tmp_ledger, reply_event, result)
        assert written["category"] == "uncategorized"
        assert written["matched_pattern"] is None
        assert written["classification_method"] == "rule"

    def test_build_classified_payload_matches_emit_shape(
        self, factory_classifier,
    ):
        """Per Week 2 follow-up P3-C — the dry-run path + the live emit
        path BOTH call build_classified_payload, so the shape is one
        source of truth. A future field addition lands in both branches
        without manual synchronization.
        """
        reply_event = {
            "type": "reply_received",
            "person_id": "p_helper",
            "channel": "email",
            "gmail_message_id": "gid_helper",
            "gmail_thread_id": "tid_helper",
            "subject": "Re: hi",
            "body": "please unsubscribe",
        }
        result = factory_classifier.classify(reply_event)
        payload = build_classified_payload(reply_event, result)
        # Same fields as emit_classified_event minus the ledger-stamped
        # ts + v defaults.
        assert payload["type"] == "reply_classified"
        assert payload["person_id"] == "p_helper"
        assert payload["channel"] == "email"
        assert payload["reply_message_id"] == "gid_helper"
        assert payload["gmail_thread_id"] == "tid_helper"
        assert payload["category"] == "unsubscribe"
        assert payload["classification_method"] == "rule"
        assert payload["confidence"] == 1.0
        assert payload["matched_pattern"] is not None
        assert payload["_emitted_by"] == "reply_classifier"
        # Payload does NOT carry _dry_run (the caller stamps that field
        # in the dry-run branch per reconcile.run_pass_g).
        assert "_dry_run" not in payload
        # Payload does NOT carry v or ts (ledger.append stamps those
        # on persistence; payload is the pre-persistence shape).
        assert "v" not in payload
        assert "ts" not in payload

    def test_event_carries_v_and_ts_via_ledger_defaults(
        self, tmp_ledger, factory_classifier,
    ):
        reply_event = {
            "type": "reply_received",
            "person_id": "p",
            "channel": "email",
            "gmail_message_id": "gid_v_ts",
            "subject": "",
            "body": "unsubscribe",
        }
        written = emit_classified_event(
            tmp_ledger, reply_event, factory_classifier.classify(reply_event),
        )
        # Ledger's append() stamps v + ts defaults.
        assert written["v"] == 1
        assert "ts" in written


# ===========================================================================
# Pass G — reconcile.run_pass_g integration
# ===========================================================================


class TestPassG:

    def _make_classifier(self, tmp_path) -> RuleBasedClassifier:
        patterns = [r"\bunsubscribe\b", r"\bplease stop\b"]
        p = _write_patterns(tmp_path / "patterns.yml", patterns)
        return RuleBasedClassifier.from_yaml(p)

    def _seed_reply(
        self, ledger, *, person_id, mid, tid="thr_x",
        channel="email", body="please unsubscribe me",
        subject="Re: outreach",
    ) -> None:
        ledger.append({
            "type": "reply_received",
            "person_id": person_id,
            "channel": channel,
            "gmail_message_id": mid,
            "gmail_thread_id": tid,
            "from": f"{person_id}@x.test",
            "subject": subject,
            "body": body,
            "ts": _old_ts(60),
        })

    def test_classifies_one_reply(self, tmp_ledger, tmp_path):
        c = self._make_classifier(tmp_path)
        self._seed_reply(
            tmp_ledger, person_id="p1", mid="gid_p1",
        )
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert result.examined == 1
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["type"] == "reply_classified"
        assert ev["person_id"] == "p1"
        assert ev["channel"] == "email"
        assert ev["reply_message_id"] == "gid_p1"
        assert ev["category"] == "unsubscribe"
        assert ev["classification_method"] == "rule"
        assert ev["confidence"] == 1.0

    def test_idempotent_across_runs(self, tmp_ledger, tmp_path):
        """Per ADR-0026 D104 — running Pass G twice produces no new
        events the second time."""
        c = self._make_classifier(tmp_path)
        self._seed_reply(tmp_ledger, person_id="p2", mid="gid_p2")
        # First run — one event.
        r1 = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert len(r1.synthesized) == 1
        # Second run — examined again but skipped because already classified.
        r2 = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert r2.examined == 1
        assert r2.synthesized == []

    def test_idempotence_keyed_by_message_id_and_channel(
        self, tmp_ledger, tmp_path,
    ):
        """Per ADR-0026 D104 — the (mid, channel) pair is discriminative.
        A reply on the SAME message id but DIFFERENT channel produces
        a SEPARATE classification (defensive against per-channel
        message-id namespace collisions)."""
        c = self._make_classifier(tmp_path)
        # Seed an email reply with mid="msg_X".
        self._seed_reply(
            tmp_ledger, person_id="p3", mid="msg_X", channel="email",
        )
        # Seed a LinkedIn reply with the SAME mid="msg_X" but channel=linkedin.
        # This is a contrived collision scenario but the test pins the
        # discriminator's correctness.
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "p3",
            "channel": "linkedin",
            "reply_message_id": "msg_X",  # SAME mid, different channel
            "from": "p3-li",
            "subject": "",
            "body": "please stop messaging me",
            "ts": _old_ts(30),
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        # BOTH replies classified — the pair (msg_X, email) is distinct
        # from (msg_X, linkedin).
        assert result.examined == 2
        assert len(result.synthesized) == 2
        channels = {ev["channel"] for ev in result.synthesized}
        assert channels == {"email", "linkedin"}

    def test_skips_replies_outside_window(self, tmp_ledger, tmp_path):
        c = self._make_classifier(tmp_path)
        # Reply outside the window — should be skipped.
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "p4",
            "channel": "email",
            "gmail_message_id": "gid_old",
            "from": "old@x.test",
            "subject": "Re: hi",
            "body": "unsubscribe",
            "ts": "2020-01-01T00:00:00.000Z",  # ancient
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert result.examined == 0
        assert result.synthesized == []

    def test_does_not_classify_bounce_events(self, tmp_ledger, tmp_path):
        """Per ADR-0025 D96 — bounces are a SEPARATE category in the
        conversation-state machine; the classifier reads bounce events
        but does NOT emit reply_classified for them. Pass G filters."""
        c = self._make_classifier(tmp_path)
        # Bounce event with unsubscribe-flavored body.
        tmp_ledger.append({
            "type": "bounce_detected",  # NOT reply_received
            "person_id": "p5",
            "channel": "email",
            "gmail_message_id": "gid_bounce",
            "from": "mailer-daemon@x.test",
            "subject": "Delivery Status Notification (Failure)",
            "body": "please unsubscribe",  # would match if classified
            "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        # Bounce event NOT examined (Pass G filters to reply_received).
        assert result.examined == 0
        assert result.synthesized == []

    def test_dry_run_does_not_persist_events(self, tmp_ledger, tmp_path):
        c = self._make_classifier(tmp_path)
        self._seed_reply(tmp_ledger, person_id="p6", mid="gid_p6")
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=False,
        )
        # Synthesized but marked _dry_run.
        assert len(result.synthesized) == 1
        assert result.synthesized[0].get("_dry_run") is True
        # Nothing landed in the ledger — re-running confirms idempotence
        # didn't kick in (no reply_classified exists).
        events = [e for e in tmp_ledger.all_events()
                  if e.get("type") == "reply_classified"]
        assert events == []

    def test_classifies_uncategorized_for_non_matches(
        self, tmp_ledger, tmp_path,
    ):
        # Per ADR-0026 D107 — non-matching replies emit
        # category=uncategorized (NOT no-op).
        c = self._make_classifier(tmp_path)
        self._seed_reply(
            tmp_ledger, person_id="p7", mid="gid_p7",
            body="Sounds great, let me know more.",
        )
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert len(result.synthesized) == 1
        ev = result.synthesized[0]
        assert ev["category"] == "uncategorized"
        assert ev["matched_pattern"] is None

    def test_handles_reply_without_message_id_via_error(
        self, tmp_ledger, tmp_path,
    ):
        # Defensive — a reply event without a message id can't be
        # idempotently keyed. Pass G records the observation in errors
        # + skips. Shouldn't happen with Pass B's emit shape but defense.
        c = self._make_classifier(tmp_path)
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "p8",
            "channel": "email",
            # no gmail_message_id / reply_message_id
            "from": "p8@x.test",
            "subject": "Re: hi",
            "body": "unsubscribe",
            "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert result.synthesized == []
        assert len(result.errors) == 1
        assert "reply_received event without reply_message_id" in result.errors[0]

    def test_handles_classifier_exception_via_error_capture(
        self, tmp_ledger, tmp_path,
    ):
        # If the classifier raises (e.g., catastrophic regex
        # backtracking — pathological pattern), Pass G records the
        # error + moves to the next reply. The reply event itself is
        # unchanged; the operator can re-run after fixing the pattern.
        class _BrokenClassifier:
            def classify(self, _reply):
                raise RuntimeError("simulated classifier crash")
        self._seed_reply(tmp_ledger, person_id="p9", mid="gid_p9")
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=_BrokenClassifier(),
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert result.synthesized == []
        assert any("classifier exception" in e for e in result.errors)

    def test_pre_pillar_d_reply_without_channel_treated_as_email(
        self, tmp_ledger, tmp_path,
    ):
        # Per ADR-0025 §Migration/rollout item 3 — pre-Pillar-D-Week-1
        # Pass B emits lack the channel field. Pass G defaults to
        # "email" so the classifier handles them retroactively.
        c = self._make_classifier(tmp_path)
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "p_legacy",
            # no channel field — pre-Pillar-D-Week-1 emit shape
            "gmail_message_id": "gid_legacy",
            "gmail_thread_id": "tid_legacy",
            "from": "legacy@x.test",
            "subject": "Re: hi",
            "body": "please unsubscribe",
            "ts": _old_ts(60),
        })
        result = _reconcile.run_pass_g(
            led=tmp_ledger, classifier=c,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            apply=True,
        )
        assert len(result.synthesized) == 1
        assert result.synthesized[0]["channel"] == "email"


# ===========================================================================
# Reconcile integration — Pass G in the chain
# ===========================================================================


class TestReconcileIntegration:

    def test_pass_g_in_all_passes(self):
        # Per ADR-0026 D105 — Pass G is in the ALL_PASSES tuple.
        assert "G" in _reconcile.ALL_PASSES
        # Pass G runs AFTER the per-channel reply detection passes
        # (H/I/J — Week 3 per ADR-0027 D111) + BEFORE Pass M (auto-
        # unsubscribe handler — Week 4-5 per ADR-0028) which consumes
        # G's reply_classified emit. The "G is LAST" invariant from
        # Week 2 (ADR-0026 D105) no longer holds — M + N consume G's
        # output.
        passes = _reconcile.ALL_PASSES
        g_idx = passes.index("G")
        for upstream in ("H", "I", "J"):
            assert passes.index(upstream) < g_idx, (
                f"Pass {upstream} (producer) must run BEFORE Pass G "
                f"(consumer); got order {passes!r}."
            )
        if "M" in passes:
            assert passes.index("M") > g_idx, (
                "Pass M (auto-unsubscribe — consumer of Pass G's "
                "reply_classified emit per ADR-0028 D116) must run "
                "AFTER Pass G."
            )

    def test_reconcile_g_missing_classifier_records_clear_error(
        self, tmp_ledger,
    ):
        # If Pass G is requested but no classifier is provided, the
        # dispatcher records a clear error with bootstrap remediation
        # (no Python traceback to confuse operators).
        result = _reconcile.reconcile(
            passes="G",
            since=datetime.now(timezone.utc) - timedelta(days=7),
            led=tmp_ledger,
            classifier=None,
            apply=False,
            persist_status=False,
        )
        assert len(result.passes) == 1
        pr = result.passes[0]
        assert pr.pass_name == "G"
        assert any("Pass G requires a classifier" in e for e in pr.errors)
        assert any("ADR-0026 D103" in e for e in pr.errors)
        assert any("config-template/unsubscribe-patterns.example.yml"
                   in e for e in pr.errors)

    def test_reconcile_g_with_classifier_passes_cleanly(
        self, tmp_ledger, tmp_path,
    ):
        # End-to-end: reconcile(passes="G") with a real classifier runs
        # cleanly + emits classified events.
        patterns = [r"\bunsubscribe\b"]
        p = _write_patterns(tmp_path / "patterns.yml", patterns)
        c = RuleBasedClassifier.from_yaml(p)
        tmp_ledger.append({
            "type": "reply_received",
            "person_id": "p_e2e",
            "channel": "email",
            "gmail_message_id": "gid_e2e",
            "from": "e2e@x.test",
            "subject": "Re: hi",
            "body": "please unsubscribe",
            "ts": _old_ts(60),
        })
        result = _reconcile.reconcile(
            passes="G",
            since=datetime.now(timezone.utc) - timedelta(days=7),
            led=tmp_ledger,
            classifier=c,
            apply=True,
            persist_status=False,
        )
        assert len(result.passes) == 1
        pr = result.passes[0]
        assert pr.pass_name == "G"
        assert pr.errors == []
        assert len(pr.synthesized) == 1
        assert pr.synthesized[0]["type"] == "reply_classified"


# ===========================================================================
# Pillar D Week 3 — per-category long-tail classification (ADR-0027 D108-D110)
# ===========================================================================


class TestOOOClassification:
    """Every factory OOO pattern matches at least one real-world reply.

    The 10 patterns in config-template/ooo-patterns.example.yml each
    correspond to a common OOO-template family; the test corpus
    exercises each.
    """

    @pytest.mark.parametrize("body", [
        # Pattern 1: "out of office" (canonical)
        "I am currently out of office until June 5",
        "out-of-office reply: please hold",
        # Pattern 2: "OOO" / "OOTO" shorthand
        "OOO this week — back Monday",
        "OOTO until next Friday",
        # Pattern 3: "on vacation" / "on PTO" / "on holiday" / "on leave"
        "I'm on vacation until July 1",
        "currently on PTO",
        "on annual leave through end of June",
        "on sabbatical until September",
        # Pattern 4: "currently away" / "currently out"
        "I am currently away from my desk this week",
        "currently unavailable",
        "currently on parental leave",
        # Pattern 5: "I will be (out|away|back) until|on|from DATE"
        "I'll be out of the office until June 12",
        "I will be away from June 1 through June 8",
        "I am out of office starting tomorrow",
        # Pattern 6: "limited (access|email)"
        "I have limited email access this week",
        "limited connectivity through Friday",
        # Pattern 7: "automatic reply" / "auto-reply"
        "This is an automatic reply — I am out of office",
        "Auto-reply: out until next week",
        # Pattern 8: "be back on/by/after DATE"
        "I will be back on Monday morning",
        "Will be back by next Tuesday",
        # Pattern 9: parental / maternity / paternity leave
        "I am on maternity leave until August",
        "currently on paternity leave",
        # Pattern 10: "in a conference until"
        "I'm in a conference until Wednesday",
    ])
    def test_ooo_pattern_matches(self, full_factory_classifier, body):
        result = full_factory_classifier.classify(
            {"subject": "Re: outreach", "body": body},
        )
        assert result.category == "ooo", (
            f"body={body!r} expected ooo match; got {result.category}; "
            f"pattern={result.matched_pattern!r}"
        )
        assert result.classification_method == "rule"
        assert result.confidence == 1.0


class TestWrongPersonClassification:
    """Every factory wrong-person pattern matches at least one real-world reply."""

    @pytest.mark.parametrize("body", [
        # Pattern 1: "wrong person/contact"
        "You have the wrong person — try our CTO",
        "I'm the wrong contact for this",
        "Wrong recipient — please redirect",
        # Pattern 2: "not the right person/contact"
        "I'm not the right person for this question",
        "I am not the right contact for sales",
        # Pattern 3: "not my department"
        "This is not my department — try procurement",
        "Not my purview — please redirect to legal",
        "Not in my area of responsibility",
        # Pattern 4: "you should/would/might want to speak/talk/reach out to"
        "You should speak with our head of partnerships",
        "You'd want to reach out to our VP of Engineering",
        "I'd recommend you contact our procurement team",
        # Pattern 5: "(please )?reach out to <ROLE>"
        "Please reach out to our CTO",
        "Contact our Head of Sales for this",
        "Email our CFO directly",
        # Pattern 6: "try our <ROLE>"
        "Try our CTO Jane Doe",
        "Try our head of engineering",
        "Try our procurement team",
        # Pattern 7: "redirected/forwarded to"
        "I've forwarded this to our partnerships team",
        "Redirecting this to my colleague",
        "Passed this along to our CTO",
        # Pattern 8: "no longer with us / left the company"
        "Jane no longer works at the company",
        "She left the company last quarter",
        # Pattern 9: "wrong department / team"
        "This is the wrong department for that",
        "Wrong team — try platform engineering",
        # Pattern 10: "I don't handle" / "we don't handle"
        "I don't handle vendor relationships",
        "We don't handle partnerships at this level",
    ])
    def test_wrong_person_pattern_matches(self, full_factory_classifier, body):
        result = full_factory_classifier.classify(
            {"subject": "Re: outreach", "body": body},
        )
        assert result.category == "wrong_person", (
            f"body={body!r} expected wrong_person match; "
            f"got {result.category}; pattern={result.matched_pattern!r}"
        )
        assert result.classification_method == "rule"
        assert result.confidence == 1.0


class TestInterestClassification:
    """Every factory interest pattern matches at least one real-world reply."""

    @pytest.mark.parametrize("body", [
        # Pattern 1: "send me more info/details/pricing"
        "Please send me more info",
        "Could you send me the pricing?",
        "Send us more details on this",
        # Pattern 2: "(can|could) we (book|schedule) a (call|meeting|demo)"
        "Can we book a call next week?",
        "Could we schedule a demo?",
        "Let's set up a quick chat",
        "Happy to hop on a 15-minute call",
        # Pattern 3: "would love to chat/talk/discuss"
        "Would love to chat about this",
        "Would love to discuss further",
        "Would love to hear more about it",
        # Pattern 4: "sounds/looks (interesting|great|good|promising)"
        "Sounds interesting!",
        "Looks promising",
        "This is great timing for us",
        # Pattern 5: "interested in learning/hearing/seeing more"
        "Interested in learning more",
        "Interested in exploring this further",
        # Pattern 6: "tell me more"
        "Tell me more about your pricing",
        "Tell me more",
        # Pattern 7: "do you have a (deck|case studies|demo)"
        "Do you have a deck I can review?",
        "Can you send any case studies?",
        # Pattern 8: "when's a good time" / "what's your availability"
        "When's a good time to chat?",
        "What's your availability next week?",
        # Pattern 9: "I'd be (interested|happy|keen) to"
        "I'd be interested to learn more",
        "I'd be happy to set up a quick call",
        # Pattern 10: "open to a (chat|call|discussion)"
        "Open to a chat next week",
        "We'd be open to a brief call",
    ])
    def test_interest_pattern_matches(self, full_factory_classifier, body):
        result = full_factory_classifier.classify(
            {"subject": "Re: outreach", "body": body},
        )
        assert result.category == "interest", (
            f"body={body!r} expected interest match; "
            f"got {result.category}; pattern={result.matched_pattern!r}"
        )
        assert result.classification_method == "rule"
        assert result.confidence == 1.0


class TestRejectionClassification:
    """Every factory rejection pattern matches at least one real-world reply."""

    @pytest.mark.parametrize("body", [
        # Pattern 1: "not interested" / "no thanks"
        "Not interested at this time",
        "No thanks",
        "No, thank you",
        "We'll pass on this one",
        # Pattern 2: "not (now|at this time|in market|a fit|a priority)"
        "Not now — maybe next quarter",
        "Not at this time",
        "Not in market right now",
        "Not a fit for us",
        "Not a priority this year",
        # Pattern 3: "(we|i) just (signed|chose|went) with"
        "We just signed with a competitor",
        "I recently went with another vendor",
        "We already picked another solution",
        # Pattern 4: "we have/already have/use an existing"
        "We already have a solution for this",
        "We are happy with our current vendor",
        "We have an existing partnership in this area",
        # Pattern 5: "we don't/won't/aren't (need|buying|purchasing|looking)"
        "We don't need this right now",
        "We aren't buying in this category",
        "We won't be purchasing this quarter",
        "We aren't in the market",
        # Pattern 6: "maybe later / next year / Q3"
        "Maybe later this year",
        "Perhaps next quarter",
        "Possibly in Q3",
        # Pattern 7: "circle back / reach back"
        "Please circle back in six months",
        "Reach back when we're ready",
        "Touch back next year",
        # Pattern 8: "no budget" / "out of budget"
        "No budget for this right now",
        "Budget is frozen until Q1",
        "Out of budget this year",
        # Pattern 9: "isn't a priority / on our roadmap"
        "This isn't a priority for us",
        "Not on our roadmap this year",
        # Pattern 10: "please do not follow up" (borderline-unsubscribe)
        "Please do not follow up",
        "Please don't message me again",
    ])
    def test_rejection_pattern_matches(self, full_factory_classifier, body):
        result = full_factory_classifier.classify(
            {"subject": "Re: outreach", "body": body},
        )
        assert result.category == "rejection", (
            f"body={body!r} expected rejection match; "
            f"got {result.category}; pattern={result.matched_pattern!r}"
        )
        assert result.classification_method == "rule"
        assert result.confidence == 1.0


class TestCategoryPriorityOrder:
    """Per ADR-0027 D110 — the dispatch priority order is fixed.

    Unsubscribe ALWAYS FIRST (legal-liability path). Then ooo /
    wrong_person / rejection / interest in that priority. The
    interest category is evaluated LAST among the long-tail because
    "sounds interesting but ..." is a common rejection pattern; the
    more-specific category MUST win on competing matches.
    """

    def test_dispatch_priority_constant_pinned(self):
        # Pin per ADR-0027 D110 — exact order. Future contributors
        # MUST NOT reorder without a corresponding ADR amendment +
        # update to this test's expected tuple.
        assert DISPATCH_PRIORITY == (
            "unsubscribe", "ooo", "wrong_person",
            "rejection", "interest",
        )

    def test_unsubscribe_is_first(self):
        # The load-bearing legal-liability invariant — unsubscribe
        # FIRST. A future contributor reordering would break this row.
        assert DISPATCH_PRIORITY[0] == "unsubscribe"

    def test_interest_is_last_long_tail(self):
        # Interest is evaluated LAST among the long-tail categories so
        # ambiguous polite-positive language doesn't override
        # more-specific signals (rejection / ooo / wrong_person).
        # If a future tuning surfaces a reason to reorder, the
        # priority comment in reply_classifier.py + ADR-0027 D110 must
        # be amended alongside this test.
        assert DISPATCH_PRIORITY[-1] == "interest"

    def test_unsubscribe_wins_over_long_tail(self, full_factory_classifier):
        # Body has BOTH unsubscribe and interest signals; unsubscribe
        # must win per the legal-liability priority.
        reply = {
            "subject": "Re: outreach",
            "body": "sounds interesting but please unsubscribe me",
        }
        result = full_factory_classifier.classify(reply)
        assert result.category == "unsubscribe"

    def test_rejection_wins_over_interest(self, full_factory_classifier):
        # The competing-signal scenario: "sounds interesting but we're
        # not in market" is the canonical polite-rejection. Rejection
        # MUST win over interest.
        reply = {
            "subject": "Re: outreach",
            "body": "sounds interesting but we're not in market right now",
        }
        result = full_factory_classifier.classify(reply)
        assert result.category == "rejection"

    def test_wrong_person_wins_over_interest(self, full_factory_classifier):
        # Wrong-person redirect is more specific than positive interest
        # language. Operator-routing wins.
        reply = {
            "subject": "Re: outreach",
            "body": "sounds interesting — but you have the wrong person, try our CTO",
        }
        result = full_factory_classifier.classify(reply)
        assert result.category == "wrong_person"

    def test_ooo_wins_over_interest(self, full_factory_classifier):
        # Temporal-deferral signal is more specific than positive
        # interest language.
        reply = {
            "subject": "Re: outreach",
            "body": "sounds interesting — I'm currently out of office until June 12, will reply then",
        }
        result = full_factory_classifier.classify(reply)
        assert result.category == "ooo"

    def test_unsubscribe_wins_over_rejection(self, full_factory_classifier):
        # Unsubscribe + rejection signals both present — unsubscribe
        # wins per legal-liability priority.
        reply = {
            "subject": "Re: outreach",
            "body": "not interested at this time — please unsubscribe me",
        }
        result = full_factory_classifier.classify(reply)
        assert result.category == "unsubscribe"

    def test_ooo_wins_over_wrong_person(self, full_factory_classifier):
        # OOO is evaluated BEFORE wrong_person per DISPATCH_PRIORITY.
        # A reply containing both should classify as OOO.
        reply = {
            "subject": "Re: outreach",
            "body": "I'm out of office until next week — also try our CTO",
        }
        result = full_factory_classifier.classify(reply)
        assert result.category == "ooo"


class TestLongTailPatternLoading:
    """Per ADR-0027 D109 — per-category factory files load cleanly +
    follow the same refuse-loud schema-validation contract as the
    Week 2 unsubscribe file (ADR-0026 D103).
    """

    @pytest.mark.parametrize("category", [
        "ooo", "wrong_person", "interest", "rejection",
    ])
    def test_factory_example_loads(self, category):
        # Each long-tail factory example file loads cleanly.
        repo_root = Path(__file__).resolve().parent.parent
        example_name = PATTERN_FILE_BY_CATEGORY[category].replace(
            ".yml", ".example.yml",
        )
        p = repo_root / "config-template" / example_name
        assert p.exists(), f"factory example missing for {category}: {p}"
        patterns = load_pattern_file(p, category=category)
        assert len(patterns) >= 5, (
            f"{category} factory file must ship ≥5 patterns; "
            f"got {len(patterns)}"
        )
        # Every entry compiles.
        for pat in patterns:
            re.compile(pat)

    def test_load_pattern_file_missing_includes_category_in_bootstrap_message(
        self, tmp_path,
    ):
        # The bootstrap-failure error message names the per-category
        # factory example file (ADR-0027 D109).
        missing = tmp_path / "nonexistent" / "ooo-patterns.yml"
        with pytest.raises(PatternLoadError) as exc:
            load_pattern_file(missing, category="ooo")
        assert "Bootstrap:" in str(exc.value)
        assert "ooo-patterns.example.yml" in str(exc.value)

    def test_load_pattern_file_wrong_person_message(self, tmp_path):
        # wrong_person → wrong-person-patterns.example.yml (hyphenated
        # naming convention).
        missing = tmp_path / "nonexistent" / "wrong-person-patterns.yml"
        with pytest.raises(PatternLoadError) as exc:
            load_pattern_file(missing, category="wrong_person")
        assert "wrong-person-patterns.example.yml" in str(exc.value)

    def test_load_pattern_file_unknown_category_defaults_to_kebab(self, tmp_path):
        # An unknown category name (not in PATTERN_FILE_BY_CATEGORY)
        # defaults to "<category>-patterns.example.yml" in the
        # bootstrap message. This is defensive — operators shouldn't
        # hit this path; the constant is the SoT.
        missing = tmp_path / "nonexistent" / "made_up-patterns.yml"
        with pytest.raises(PatternLoadError) as exc:
            load_pattern_file(missing, category="made_up")
        assert "made_up-patterns.example.yml" in str(exc.value)

    def test_load_pattern_file_uses_same_validation_as_unsubscribe(self, tmp_path):
        # Same refuse-loud schema as Week 2 — wrong version raises.
        bad = _write_patterns(
            tmp_path / "rejection.yml", ["\\bnot interested\\b"], version=99,
        )
        with pytest.raises(PatternLoadError) as exc:
            load_pattern_file(bad, category="rejection")
        assert "only version=1 supported" in str(exc.value)


class TestFromYamlDir:
    """Per ADR-0027 D109 — from_yaml_dir loads every category's pattern
    file from one directory. The unsubscribe file is REQUIRED; the
    four long-tail files are OPTIONAL (absent → empty pattern list →
    category never fires).
    """

    def test_from_yaml_dir_loads_factory_examples(self, factory_pattern_dir):
        # With every factory file copied + renamed in the dir,
        # from_yaml_dir constructs a classifier with patterns for all
        # five categories.
        classifier = RuleBasedClassifier.from_yaml_dir(factory_pattern_dir)
        # Verify each category has patterns loaded.
        for category in CATEGORIES - {"uncategorized"}:
            patterns = classifier._raw_by_category[category]
            assert len(patterns) >= 5, (
                f"{category} expected ≥5 patterns from factory; "
                f"got {len(patterns)}"
            )

    def test_from_yaml_dir_missing_unsubscribe_refuses_loud(self, tmp_path):
        # The unsubscribe file is REQUIRED per ADR-0027 D109; absence
        # is a misconfiguration the framework surfaces loudly.
        d = tmp_path / "classifier"
        d.mkdir()
        # Drop only one long-tail file; no unsubscribe.
        _write_patterns(d / "ooo-patterns.yml", ["\\bout of office\\b"])
        with pytest.raises(PatternLoadError) as exc:
            RuleBasedClassifier.from_yaml_dir(d)
        # Bootstrap message points at the unsubscribe factory file.
        assert "unsubscribe-patterns.example.yml" in str(exc.value)

    def test_from_yaml_dir_optional_long_tail_files_default_empty(self, tmp_path):
        # With only the unsubscribe file present, the long-tail
        # categories default to empty lists. Replies matching no
        # unsubscribe pattern + nothing else fall to uncategorized.
        d = tmp_path / "classifier"
        d.mkdir()
        _write_patterns(
            d / "unsubscribe-patterns.yml", [r"\bunsubscribe\b"],
        )
        classifier = RuleBasedClassifier.from_yaml_dir(d)
        # Long-tail empty.
        for category in ("ooo", "wrong_person", "interest", "rejection"):
            assert classifier._raw_by_category[category] == []
        # Pre-existing unsubscribe still fires.
        result = classifier.classify({"body": "please unsubscribe"})
        assert result.category == "unsubscribe"
        # A long-tail-flavored reply falls to uncategorized (no patterns).
        result = classifier.classify({"body": "sounds interesting"})
        assert result.category == "uncategorized"

    def test_from_yaml_dir_partial_long_tail_loads_present_only(self, tmp_path):
        # Operators may opt into long-tail categories at their own
        # cadence (e.g., ship ooo + rejection first; defer interest +
        # wrong_person tuning). The classifier should load every
        # category file present + skip absent ones.
        d = tmp_path / "classifier"
        d.mkdir()
        _write_patterns(
            d / "unsubscribe-patterns.yml", [r"\bunsubscribe\b"],
        )
        _write_patterns(
            d / "ooo-patterns.yml", [r"\bout of office\b"],
        )
        _write_patterns(
            d / "rejection-patterns.yml", [r"\bnot interested\b"],
        )
        classifier = RuleBasedClassifier.from_yaml_dir(d)
        # Present categories loaded.
        assert classifier._raw_by_category["unsubscribe"] != []
        assert classifier._raw_by_category["ooo"] != []
        assert classifier._raw_by_category["rejection"] != []
        # Absent categories defaulted to empty.
        assert classifier._raw_by_category["wrong_person"] == []
        assert classifier._raw_by_category["interest"] == []
        # Verify the loaded categories dispatch.
        assert classifier.classify(
            {"body": "I am out of office until June 5"},
        ).category == "ooo"
        assert classifier.classify(
            {"body": "not interested at this time"},
        ).category == "rejection"

    def test_week_3_delivered_categories_constant(self):
        # Pin per ADR-0027 D108 — all 6 categories shipped Week 3
        # with rule-based detection. Week 2's subset (unsubscribe +
        # uncategorized) is preserved as a documentation pin.
        assert WEEK_3_DELIVERED_CATEGORIES == CATEGORIES
        assert WEEK_2_DELIVERED_CATEGORIES.issubset(WEEK_3_DELIVERED_CATEGORIES)

    def test_default_pattern_dir_matches_default_path(self):
        # The single-file legacy default is the unsubscribe file in
        # the default directory.
        assert DEFAULT_PATTERN_PATH == DEFAULT_PATTERN_DIR / "unsubscribe-patterns.yml"


class TestPerCategoryConstructorBackwardsCompat:
    """Per ADR-0027 D108 — the per-category-kwargs constructor shape
    keeps Week 2 callers (RuleBasedClassifier(unsubscribe_patterns=...))
    working. The long-tail kwargs default to empty sequences.
    """

    def test_unsubscribe_only_construction_works(self):
        # Week 2's signature — unchanged behavior.
        c = RuleBasedClassifier(unsubscribe_patterns=[r"\bunsubscribe\b"])
        result = c.classify({"body": "please unsubscribe me"})
        assert result.category == "unsubscribe"
        # Long-tail categories empty.
        assert c._raw_by_category["ooo"] == []

    def test_all_categories_construction(self):
        # Week 3 callers may pass every category at once.
        c = RuleBasedClassifier(
            unsubscribe_patterns=[r"\bunsubscribe\b"],
            ooo_patterns=[r"\bout of office\b"],
            wrong_person_patterns=[r"\bwrong person\b"],
            interest_patterns=[r"\bsounds great\b"],
            rejection_patterns=[r"\bnot interested\b"],
        )
        # Each category fires on its own pattern.
        cases = [
            ("please unsubscribe", "unsubscribe"),
            ("out of office until tomorrow", "ooo"),
            ("you have the wrong person", "wrong_person"),
            ("sounds great", "interest"),
            ("not interested", "rejection"),
        ]
        for body, expected in cases:
            result = c.classify({"body": body})
            assert result.category == expected, f"body={body!r}"

    def test_mixed_long_tail_construction(self):
        # Partial long-tail (only ooo + rejection) — the unspecified
        # categories default to empty.
        c = RuleBasedClassifier(
            unsubscribe_patterns=[r"\bunsubscribe\b"],
            ooo_patterns=[r"\bout of office\b"],
            rejection_patterns=[r"\bnot interested\b"],
        )
        # wrong_person + interest fall through to uncategorized.
        result = c.classify({"body": "sounds interesting"})
        assert result.category == "uncategorized"
        result = c.classify({"body": "wrong person — try our CTO"})
        assert result.category == "uncategorized"
        # ooo + rejection still fire.
        assert c.classify(
            {"body": "out of office today"},
        ).category == "ooo"
        assert c.classify(
            {"body": "not interested"},
        ).category == "rejection"


class TestUncategorizedFallback:
    """Per ADR-0026 D107 + ADR-0027 D108 — non-matching replies emit
    category=uncategorized (visibility-without-action). The fallback
    survives Week 3's long-tail extensions.
    """

    @pytest.mark.parametrize("body", [
        # Replies with no category signal.
        "Thanks for reaching out, I'll get back to you tomorrow",
        "Got it",
        "Will review and revert",
        "OK",
        "Acknowledged",
        # Tricky cases that DON'T match any factory pattern:
        # - "stop by my office" (innocuous; no unsubscribe-flavored stop).
        "Could you stop by my office for coffee?",
        # - past-tense unsubscribed (discussing prior action).
        "We unsubscribed from that newsletter yesterday.",
    ])
    def test_unmatched_replies_classified_as_uncategorized(
        self, full_factory_classifier, body,
    ):
        result = full_factory_classifier.classify(
            {"subject": "Re: outreach", "body": body},
        )
        assert result.category == "uncategorized", (
            f"body={body!r} expected uncategorized; got {result.category}"
        )
        assert result.matched_pattern is None
        assert result.classification_method == "rule"
        assert result.confidence == 1.0


# ===========================================================================
# Pillar D Week 3 — Pass H / I / J integration sanity (light pass-level tests;
# the per-pass test files in tests/test_reconcile_pass_h_i_j.py carry the
# detail.) Here we pin the public-symbol surface from reconcile.py.
# ===========================================================================


class TestPassHIJSymbolSurface:
    """Per ADR-0027 D111 — Pass H/I/J + the new per-channel reply event
    types are exposed from reconcile.py."""

    def test_all_passes_includes_h_i_j(self):
        # Per ADR-0027 D111 — Passes H, I, J added to the chain.
        for p in ("H", "I", "J"):
            assert p in _reconcile.ALL_PASSES, f"Pass {p} not in ALL_PASSES"
        # Pass G runs AFTER H/I/J (data-flow: producers before
        # consumer per ADR-0027 D111). Pillar D Week 4-5 (ADR-0028)
        # added Pass M + N after G; the "G is last" Week 2 invariant
        # no longer applies. The current invariant: G > {H, I, J}.
        passes = _reconcile.ALL_PASSES
        g_idx = passes.index("G")
        for upstream in ("H", "I", "J"):
            assert passes.index(upstream) < g_idx, (
                f"data-flow order violated: Pass {upstream} (producer "
                f"of *_reply_received) must run before Pass G "
                f"(consumer). ALL_PASSES = {passes!r}."
            )

    def test_reply_event_types_constant(self):
        # Per ADR-0027 D112 — Pass G's input set is the closed
        # REPLY_EVENT_TYPES frozenset.
        assert _reconcile.REPLY_EVENT_TYPES == frozenset({
            "reply_received",
            "li_invite_reply_received",
            "li_dm_reply_received",
            "tw_dm_reply_received",
        })

    def test_pass_h_i_j_callable(self):
        # The pass functions exist + are callable. The detailed
        # behavior tests live in test_reconcile_pass_h_i_j.py.
        for fname in ("run_pass_h", "run_pass_i", "run_pass_j"):
            fn = getattr(_reconcile, fname, None)
            assert callable(fn), f"reconcile.{fname} not callable"
