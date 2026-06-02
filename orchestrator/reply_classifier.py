"""Pillar D — rule-based reply classifier.

Per ADR-0025 D97 + ADR-0026 D102 the classifier emits a SEPARATE
``reply_classified`` event class linking back to the originating reply
via ``reply_message_id`` + ``channel``. The unsubscribe path is rule-
based ONLY — D97's load-bearing legal-liability invariant + PILLAR-PLAN
§5's "no LLM in the legal-liability path" constraint.

Module shape (ADR-0026 + ADR-0027):
  * ``ClassifierResult`` — frozen dataclass; the per-reply output. The
    construction-time invariant (D97) refuses ``category=unsubscribe``
    with any ``classification_method`` other than ``"rule"`` (or any
    ``confidence`` other than ``1.0``) as the source-level enforcement
    of the legal-liability rule.
  * ``RuleBasedClassifier`` — the rule-based classifier. ``classify
    (reply)`` returns a ``ClassifierResult``. Week 2 shipped
    unsubscribe ONLY. Week 3 (ADR-0027 D108-D110) extends to the
    other four categories (``ooo`` / ``wrong_person`` / ``interest``
    / ``rejection``) via per-category pattern lists + a fixed-priority
    dispatch order (unsubscribe FIRST — legal liability — then ooo,
    wrong_person, rejection, interest, uncategorized fallback).
  * ``load_unsubscribe_patterns(path)`` /
    ``load_pattern_file(path, category)`` — refuse-loud YAML loaders
    per ADR-0026 D103. Raises ``PatternLoadError`` with bootstrap
    instructions on every malformed input. Week 3 adds the generic
    ``load_pattern_file`` helper for the long-tail categories;
    ``load_unsubscribe_patterns`` is preserved as a thin wrapper for
    backwards-compat with Week 2 callers.
  * ``RuleBasedClassifier.from_yaml_dir(directory)`` — Week 3
    classmethod (ADR-0027 D109) that loads ALL per-category pattern
    files from one directory (``{category}-patterns.yml`` naming
    convention; absent files default to empty pattern lists per the
    "no patterns = uncategorized fallback" defensible posture).
    ``from_yaml(path)`` remains the single-file (unsubscribe-only)
    classmethod for backwards-compat with Week 2 callers + tests.
  * ``emit_classified_event(led, reply_event, result)`` — appends a
    ``reply_classified`` event to the ledger correlating back to the
    originating reply per ADR-0025 D97's event shape.

Pass G integration (``orchestrator/reconcile.py:run_pass_g``):
  Per ADR-0026 D105, the classifier pass joins the reconcile chain
  after Pass B (Week 2) + after the per-channel reply detection
  passes H / I / J (Week 3 — ADR-0027 D111). Pass G walks
  ``reply_received`` / ``li_invite_reply_received`` /
  ``li_dm_reply_received`` / ``tw_dm_reply_received`` events in the
  window, skips events whose ``(reply_message_id, channel)`` pair
  already has a paired ``reply_classified`` event (D104 idempotence),
  and emits ``reply_classified`` events for the rest.

Pillar D Week 4-5 (ADR-0028 D115-D121): auto-unsubscribe handler in
``orchestrator/auto_unsubscribe.py`` + conversation state machine in
``orchestrator/conversation_state.py``. The handler reads
``reply_classified`` events filtered to ``category=unsubscribe`` and
writes to the suppression YAML per ADR-0025 D100's YAML-first +
ledger-second atomic write contract.

Pillar D Week 6-8 (ADR-0029 D122-D128): LLM fallback for the long-tail
non-unsubscribe categories in ``orchestrator/reply_classifier_llm.py``.
``LLMFallbackClassifier`` wraps this rule classifier + delegates rule-
first; consults the LLM ONLY when the rule returns
``category=uncategorized`` per ADR-0029 D124. LLM-emitted events carry
``classification_method="llm"`` + calibrated 0.0-1.0 ``confidence`` from
the model. The unsubscribe path stays rule-based by D97's invariant
(THREE layers of carry-forward: dispatch short-circuit + prompt
allowed-response-set exclusion + post-LLM refuse-loud guard).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

import ledger as _ledger
from observability import traced_stage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Per ADR-0026 D103 — the default operator-tunable pattern DIRECTORY.
# Operators bootstrap with the factory templates in ``config-template/``;
# Week 3 (ADR-0027 D109) ships per-category factory files for each of
# the long-tail categories. The single-file constant
# ``DEFAULT_PATTERN_PATH`` is preserved for backwards-compat with Week 2
# callers + the ``from_yaml`` classmethod; ``DEFAULT_PATTERN_DIR`` is
# the directory-union convention Week 3 introduces.
DEFAULT_PATTERN_DIR: Path = (
    Path.home() / ".outreach-factory" / "classifier"
)


# Per ADR-0026 D103 — the legacy single-file default path. Preserved
# for Week 2 callers + the ``from_yaml(path)`` classmethod. Week 3's
# directory-shape consumers use ``DEFAULT_PATTERN_DIR`` instead.
DEFAULT_PATTERN_PATH: Path = DEFAULT_PATTERN_DIR / "unsubscribe-patterns.yml"


# Per ADR-0025 D97 — the six classifier categories. Week 2 shipped
# unsubscribe + the uncategorized fallback ONLY. Week 3 (ADR-0027
# D108) extends to the other four (ooo / wrong_person / interest /
# rejection); uncategorized remains the final fallback.
CATEGORIES: frozenset[str] = frozenset({
    "unsubscribe",
    "ooo",
    "wrong_person",
    "interest",
    "rejection",
    "uncategorized",
})


# Per ADR-0026 D107 — Week 2's scope was unsubscribe + uncategorized.
# Preserved as a documentation pin; the Week 3 expanded set is the
# load-bearing reference today.
WEEK_2_DELIVERED_CATEGORIES: frozenset[str] = frozenset({
    "unsubscribe", "uncategorized",
})


# Per ADR-0027 D108 — Week 3 narrows the uncategorized fallback by
# extending to the other four long-tail categories. All six categories
# of ``CATEGORIES`` are delivered with rule-based detection as of
# Pillar D Week 3; the LLM fallback for the non-unsubscribe categories
# remains a Week 6-8 deferral (ADR-0029 — TBD).
WEEK_3_DELIVERED_CATEGORIES: frozenset[str] = frozenset({
    "unsubscribe", "ooo", "wrong_person",
    "interest", "rejection", "uncategorized",
})


# Per ADR-0027 D110 — the dispatch priority order. Unsubscribe FIRST
# (legal-liability path per ADR-0025 D97 + PILLAR-PLAN §5). The
# remaining four long-tail categories follow in fixed order; the
# ``classify`` method short-circuits on the first match. The priority
# rationale (ADR-0027 D110):
#   1. unsubscribe — legal liability; CAN-SPAM violation if missed.
#   2. ooo — temporal-explicit ("out of office until ..."); low
#      ambiguity (specific phrasing patterns).
#   3. wrong_person — operator-routing ("you have the wrong person";
#      "try our CTO"); low ambiguity, explicit redirect.
#   4. rejection — closing-signal ("not now"; "we just signed with a
#      competitor"); moderate ambiguity; explicit closing posture.
#   5. interest — positive-signal ("sounds interesting"; "send me
#      more"); HIGHEST ambiguity (polite "thanks, sounds great" often
#      non-committal). Evaluated last among the long-tail categories
#      so the more-specific patterns (rejection / wrong_person) win
#      when they could compete with positive-but-non-committal text.
#   6. uncategorized — fallback (no pattern matched; the classifier's
#      visibility-without-action posture per ADR-0026 D107).
#
# The order is the load-bearing reviewer-facing reference; an operator
# whose tuning surfaces a different priority can re-order via a fork
# of the constant, but the unsubscribe-FIRST ordering MUST NOT be
# changed (a guard at ``_LONG_TAIL_CATEGORIES`` enforces).
DISPATCH_PRIORITY: tuple[str, ...] = (
    "unsubscribe",
    "ooo",
    "wrong_person",
    "rejection",
    "interest",
)


# The long-tail categories — every category in ``DISPATCH_PRIORITY``
# except unsubscribe. Used for asserts + the from_yaml_dir helper.
_LONG_TAIL_CATEGORIES: tuple[str, ...] = tuple(
    c for c in DISPATCH_PRIORITY if c != "unsubscribe"
)


# Per ADR-0026 D103 — the version field on the pattern YAML. Future
# schema bumps (per-pattern weights, per-language pattern sets) land
# through Pillar B ``policy/000N_add_classifier_pattern_*`` migrations.
SUPPORTED_PATTERN_SCHEMA_VERSION: int = 1


# Per ADR-0027 D109 — the per-category factory file naming convention.
# Each long-tail category gets a ``{category}-patterns.yml`` file in
# ``~/.outreach-factory/classifier/`` (matching the Week 2 unsubscribe
# file's path). The ``from_yaml_dir`` classmethod uses this mapping
# to discover + load each category's patterns.
PATTERN_FILE_BY_CATEGORY: dict[str, str] = {
    "unsubscribe": "unsubscribe-patterns.yml",
    "ooo": "ooo-patterns.yml",
    "wrong_person": "wrong-person-patterns.yml",
    "interest": "interest-patterns.yml",
    "rejection": "rejection-patterns.yml",
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PatternLoadError(Exception):
    """Pattern YAML failed to load, parse, or validate.

    Per ADR-0026 D103 the classifier refuses-loud rather than silently
    falling back to the factory defaults — silent fallback would mean
    the operator's classifier is the FACTORY's, not the operator's.
    The error message guides the bootstrap step.
    """


# ---------------------------------------------------------------------------
# Classifier output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifierResult:
    """Per ADR-0025 D97 — the per-reply classifier output.

    The :func:`emit_classified_event` helper serializes this into a
    ``reply_classified`` ledger event correlating back to the
    originating reply via ``(reply_message_id, channel)``.

    The ``__post_init__`` validation is the source-level enforcement
    of the load-bearing legal-liability invariant: a future contributor
    constructing ``ClassifierResult(category="unsubscribe",
    classification_method="llm", ...)`` fails at construction time
    rather than landing a bad event in the ledger. The test
    ``tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement
    ::test_unsubscribe_classification_method_is_always_rule`` pins the
    EVENT-level contract; this construction-time check is the
    defense-in-depth at the source.
    """

    category: str
    classification_method: str  # "rule" | "llm" — Week 2 is rule-only.
    confidence: float  # 1.0 for rule matches; LLM fallback (Week 6-8) varies.
    matched_pattern: str | None  # the regex source that matched, or None.

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(
                f"category must be one of {sorted(CATEGORIES)}; "
                f"got {self.category!r}"
            )
        if self.classification_method not in ("rule", "llm"):
            raise ValueError(
                f"classification_method must be 'rule' or 'llm'; "
                f"got {self.classification_method!r}"
            )
        # Per ADR-0025 D97 — the load-bearing legal-liability invariant.
        # Unsubscribe is rule-based ONLY. The LLM is NEVER consulted for
        # unsubscribe classification even as a tiebreaker. PILLAR-PLAN
        # §5: "no LLM in the legal-liability path."
        if self.category == "unsubscribe":
            if self.classification_method != "rule":
                raise ValueError(
                    "ADR-0025 D97 invariant: category=unsubscribe MUST "
                    "carry classification_method='rule'. The LLM is NEVER "
                    "consulted for unsubscribe classification even as a "
                    "tiebreaker. PILLAR-PLAN §5 + ADR-0026 D107. Got "
                    f"classification_method={self.classification_method!r}."
                )
            if self.confidence != 1.0:
                raise ValueError(
                    "ADR-0025 D97 invariant: category=unsubscribe MUST "
                    "carry confidence=1.0 (rule matches are deterministic; "
                    "the regex matched or it didn't). Got "
                    f"confidence={self.confidence!r}."
                )


# ---------------------------------------------------------------------------
# Pattern loading
# ---------------------------------------------------------------------------


def load_pattern_file(
    path: Path, category: str = "unsubscribe",
) -> list[str]:
    """Load + validate one category's pattern list from a YAML file.

    Per ADR-0026 D103 (Week 2 unsubscribe loader) + ADR-0027 D109
    (Week 3 generalization to the long-tail categories). The
    ``category`` argument names the per-category factory example file
    in the bootstrap-failure error message; the YAML schema is uniform
    across categories (the same ``version: 1`` + ``patterns: [...]``
    shape).

    Returns a list of regex source strings (the caller compiles via
    :class:`RuleBasedClassifier`'s constructor).

    Raises :class:`PatternLoadError` on every malformed input:

    * file not found (with bootstrap instructions naming the per-
      category factory example)
    * file unreadable
    * unparseable YAML
    * top-level not a mapping
    * ``version`` != :data:`SUPPORTED_PATTERN_SCHEMA_VERSION`
    * missing ``patterns`` key
    * ``patterns`` not a list
    * any pattern not a string
    * any pattern that fails :func:`re.compile`

    The refuse-loud posture is intentional per ADR-0026 D103 — silent
    fallback to defaults would mean the operator's classifier is the
    FACTORY's, not the operator's. The error message guides bootstrap.
    """
    p = Path(path)
    # Per ADR-0027 D109 — the per-category factory example file name
    # follows the ``{category}-patterns.example.yml`` convention.
    # ``wrong_person`` → ``wrong-person-patterns.example.yml`` (the
    # hyphenated form matches PATTERN_FILE_BY_CATEGORY).
    factory_name = PATTERN_FILE_BY_CATEGORY.get(
        category, f"{category}-patterns.yml",
    ).replace(".yml", ".example.yml")
    if not p.exists():
        raise PatternLoadError(
            f"classifier pattern file not found at {p}.\n"
            f"  Bootstrap: mkdir -p {p.parent} && \\\n"
            f"             cp config-template/{factory_name} \\\n"
            f"                {p}\n"
            f"  Then re-run."
        )
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise PatternLoadError(
            f"classifier pattern file unreadable at {p}: {exc}"
        ) from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise PatternLoadError(
            f"classifier pattern file unparseable at {p}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise PatternLoadError(
            f"classifier pattern file {p}: top-level must be a YAML mapping; "
            f"got {type(data).__name__}"
        )
    version = data.get("version")
    if version != SUPPORTED_PATTERN_SCHEMA_VERSION:
        raise PatternLoadError(
            f"classifier pattern file {p}: only version="
            f"{SUPPORTED_PATTERN_SCHEMA_VERSION} supported; got version="
            f"{version!r}. Future schema bumps land via a Pillar B "
            f"policy/000N_add_classifier_pattern_* migration."
        )
    raw_patterns = data.get("patterns")
    if raw_patterns is None:
        raise PatternLoadError(
            f"classifier pattern file {p}: missing required 'patterns' key"
        )
    if not isinstance(raw_patterns, list):
        raise PatternLoadError(
            f"classifier pattern file {p}: 'patterns' must be a YAML list; "
            f"got {type(raw_patterns).__name__}"
        )
    out: list[str] = []
    for i, raw in enumerate(raw_patterns):
        if not isinstance(raw, str):
            raise PatternLoadError(
                f"classifier pattern file {p}: pattern at index {i} is not a "
                f"string (got {type(raw).__name__})"
            )
        try:
            re.compile(raw)
        except re.error as exc:
            raise PatternLoadError(
                f"classifier pattern file {p}: pattern at index {i} "
                f"({raw!r}) failed to compile: {exc}"
            ) from exc
        out.append(raw)
    return out


# Per the Week 3 per-week reviewer's P3-B finding — patterns with nested
# alternations + optional groups can exhibit super-linear (catastrophic)
# backtracking on adversarial input. Python's `re` module has no built-in
# timeout guard + holds the GIL during search, so an in-process load-time
# probe CAN'T reliably catch a hanging pattern (the probe itself would
# hang). The P3-B fix in this commit is the pattern-simplification (see
# `config-template/interest-patterns.example.yml` pattern 2's split into
# 2a + 2b — removed the nested optional group's backtracking risk by
# splitting one pattern into two linear alternatives).
#
# Operator-facing remediation for future bad patterns:
#   1. Test new patterns interactively against representative reply
#      bodies before committing.
#   2. Avoid nested quantifiers like `(a+)+`, `(a|b)*c`, or nested
#      optional groups followed by alternations.
#   3. Pillar D Week 6-8's LLM fallback (ADR-0029 — TBD) provides an
#      alternative classification path for operators whose pattern set
#      becomes too complex; the rule list can stay simple while the
#      LLM handles edge cases.
#
# Future Pillar I work may add subprocess-based pattern probes (with
# hard timeouts via `signal.alarm` or `multiprocessing`) — the
# subprocess approach can kill a hanging regex; the in-process timing
# approach cannot.


def load_unsubscribe_patterns(path: Path) -> list[str]:
    """Load + validate the unsubscribe-pattern list from a YAML file.

    Per ADR-0026 D103 (Week 2 entry point). Thin wrapper around
    :func:`load_pattern_file` with ``category="unsubscribe"`` preserved
    for Week 2 callers + the ``from_yaml(path)`` classmethod. Week 3
    consumers use :func:`load_pattern_file` directly to load the
    long-tail categories.
    """
    return load_pattern_file(path, category="unsubscribe")


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class RuleBasedClassifier:
    """Pillar D — rule-based reply classifier (Week 2 unsubscribe +
    Week 3 long-tail categories).

    Per ADR-0025 D97 + ADR-0026 + ADR-0027:

    * Week 2 shipped the UNSUBSCRIBE path. Week 3 (ADR-0027 D108)
      extends to ``ooo`` / ``wrong_person`` / ``interest`` /
      ``rejection`` via per-category pattern lists. The
      ``uncategorized`` fallback (per ADR-0026 D107) catches any reply
      no pattern in any category matches — the classifier's
      visibility-without-action posture is preserved.
    * The unsubscribe path is rule-based ONLY — the LLM is NEVER
      consulted for unsubscribe classification even as a tiebreaker.
      Pinned by ``tests/test_multi_channel_coherence.py::
      TestUnsubscribeEnforcement
      ::test_unsubscribe_classification_method_is_always_rule`` AND by
      :meth:`ClassifierResult.__post_init__` source-level invariant.
    * Every rule match carries ``confidence = 1.0`` (deterministic
      regex — either it matched or it didn't); the LLM fallback (Week
      6-8) WILL carry calibrated 0.0-1.0 confidence from the model for
      the LONG-TAIL categories only.

    Dispatch priority (per ADR-0027 D110 — pinned by
    :data:`DISPATCH_PRIORITY`):

      1. ``unsubscribe`` (legal liability — FIRST always)
      2. ``ooo`` (temporal-explicit — low ambiguity)
      3. ``wrong_person`` (operator-routing — explicit redirect)
      4. ``rejection`` (closing-signal — moderate ambiguity)
      5. ``interest`` (positive-signal — highest ambiguity; evaluated
         LAST among the long-tail categories so more-specific patterns
         win on competing matches)
      6. ``uncategorized`` (fallback when no pattern in any category
         fires)

    Bounces are NEVER passed to the classifier — bounces are a separate
    category in the conversation-state machine per ADR-0025 D96. The
    caller (Pass G) filters to reply-received event types before
    dispatching to :meth:`classify`.
    """

    def __init__(
        self, *,
        unsubscribe_patterns: Sequence[str],
        ooo_patterns: Sequence[str] = (),
        wrong_person_patterns: Sequence[str] = (),
        interest_patterns: Sequence[str] = (),
        rejection_patterns: Sequence[str] = (),
    ) -> None:
        """Per ADR-0027 D108 — per-category-kwargs constructor shape.

        Backwards-compatible with Week 2 callers: every long-tail
        category defaults to an empty sequence (no patterns → that
        category never fires → falls through to the next priority OR
        ultimately ``uncategorized``).

        Operators bootstrap the long-tail categories at their own
        cadence — copy each ``config-template/{category}-patterns.
        example.yml`` to ``~/.outreach-factory/classifier/{category}-
        patterns.yml`` then re-run; the classifier picks up the new
        patterns on next construction (Pass G's next invocation).
        """
        # Per-category pattern lists. The raw form is preserved so the
        # ``matched_pattern`` field in the output reflects the
        # operator-readable regex source (audit surface — "which
        # pattern fired?"). Storing in a dict keyed by category name
        # lets ``classify()`` iterate :data:`DISPATCH_PRIORITY` once
        # without explicit per-category branching.
        raw: dict[str, list[str]] = {
            "unsubscribe": list(unsubscribe_patterns),
            "ooo": list(ooo_patterns),
            "wrong_person": list(wrong_person_patterns),
            "interest": list(interest_patterns),
            "rejection": list(rejection_patterns),
        }
        # Compile each pattern with IGNORECASE so the operator's pattern
        # doesn't need an inline (?i) flag. The factory defaults include
        # the flag for operator clarity (a reader sees case-
        # insensitivity is intended); the redundancy is harmless.
        compiled: dict[str, list[re.Pattern[str]]] = {
            category: [re.compile(p, re.IGNORECASE) for p in patterns]
            for category, patterns in raw.items()
        }
        self._raw_by_category: dict[str, list[str]] = raw
        self._compiled_by_category: dict[str, list[re.Pattern[str]]] = compiled

    # Backwards-compat property: Week 2 tests + introspection consumers
    # read ``_raw_unsubscribe`` directly. Preserving the name (as a
    # delegated view) keeps the Week 2 surface stable.
    @property
    def _raw_unsubscribe(self) -> list[str]:
        return self._raw_by_category["unsubscribe"]

    @classmethod
    def from_yaml(
        cls, path: Path = DEFAULT_PATTERN_PATH,
    ) -> "RuleBasedClassifier":
        """Load unsubscribe patterns from a single YAML file (Week 2 entry).

        Per ADR-0026 D103 — refuse-loud on missing/invalid file (raises
        :class:`PatternLoadError` with bootstrap instructions). The
        default path is the operator-bootstrap convention; tests +
        per-environment overrides pass an explicit path.

        This classmethod loads ONLY the unsubscribe pattern file (Week
        2's posture). Week 3 callers wanting the full long-tail
        coverage use :meth:`from_yaml_dir` instead.
        """
        patterns = load_unsubscribe_patterns(path)
        return cls(unsubscribe_patterns=patterns)

    @classmethod
    def from_yaml_dir(
        cls, directory: Path = DEFAULT_PATTERN_DIR,
    ) -> "RuleBasedClassifier":
        """Load every category's pattern file from a directory (Week 3).

        Per ADR-0027 D109 — the per-category factory file naming
        convention (``{category}-patterns.yml`` per
        :data:`PATTERN_FILE_BY_CATEGORY`). The unsubscribe file MUST
        exist (refuse-loud per ADR-0026 D103); the four long-tail
        category files are OPTIONAL (absent → empty pattern list →
        category never fires → falls through). Each file that DOES
        exist is loaded with the same refuse-loud schema-validation
        contract as :func:`load_pattern_file`.

        The rationale for the asymmetric refuse-loud posture:
        unsubscribe is the legal-liability path per ADR-0025 D97; an
        operator running the classifier with NO unsubscribe patterns
        is a misconfiguration the framework should surface loudly. The
        long-tail categories are visibility-only in Week 3 (Week 6-8's
        LLM fallback extends them; Week 4-5's auto-unsubscribe handler
        only reads ``category=unsubscribe`` per ADR-0025 D100 + ADR-
        0026 D107); operators may opt into them at their own cadence.

        ``directory`` defaults to :data:`DEFAULT_PATTERN_DIR`
        (``~/.outreach-factory/classifier/``).
        """
        d = Path(directory)
        # Per ADR-0027 D109's strict-loud-on-unsubscribe rationale —
        # the unsubscribe file MUST exist. The dispatcher's clear-
        # error path (in reconcile.run_pass_g + the helper
        # _build_classifier_or_record_error) translates the
        # PatternLoadError into a per-pass result error.
        unsubscribe_path = d / PATTERN_FILE_BY_CATEGORY["unsubscribe"]
        unsubscribe = load_pattern_file(unsubscribe_path, category="unsubscribe")
        # The four long-tail categories — load if file exists; else
        # default to empty list.
        long_tail: dict[str, list[str]] = {}
        for category in _LONG_TAIL_CATEGORIES:
            path = d / PATTERN_FILE_BY_CATEGORY[category]
            if path.exists():
                long_tail[category] = load_pattern_file(path, category=category)
            else:
                long_tail[category] = []
        return cls(
            unsubscribe_patterns=unsubscribe,
            ooo_patterns=long_tail.get("ooo", []),
            wrong_person_patterns=long_tail.get("wrong_person", []),
            interest_patterns=long_tail.get("interest", []),
            rejection_patterns=long_tail.get("rejection", []),
        )

    def classify(self, reply_event: dict) -> ClassifierResult:
        """Classify one reply event. Returns a ClassifierResult.

        Per ADR-0025 D97 + ADR-0026 D107 + ADR-0027 D110 — dispatches
        per-category in :data:`DISPATCH_PRIORITY` order. The FIRST
        category whose pattern list contains a match wins (regex
        short-circuits on first match within the category; categories
        short-circuit on first hit across the priority order).
        Non-matching replies emit ``category="uncategorized"`` per
        ADR-0026 D107 (the visibility-without-action fallback).

        The classifier reads the reply text from ``subject`` + ``body``
        + ``snippet`` fields (whichever are populated on the event).
        Pass B's pre-existing email-reply emits carry ``subject`` only
        (the body lives in the Gmail thread); Week 3+ per-channel
        reply detection passes (H / I / J — ADR-0027 D111) will
        populate ``body`` directly.

        Pattern ORDER within one category's YAML matters for the audit
        trail (the ``matched_pattern`` field on the output reflects the
        winning pattern); the operator's ordering can put more-specific
        patterns first to surface the most-precise audit reason.
        Pattern ORDER ACROSS categories is the fixed
        :data:`DISPATCH_PRIORITY` — operators tune within a category,
        not the priority order. The unsubscribe-FIRST guarantee MUST
        NOT be reordered (legal-liability path).
        """
        text = self._extract_text(reply_event)
        for category in DISPATCH_PRIORITY:
            for raw, compiled in zip(
                self._raw_by_category[category],
                self._compiled_by_category[category],
            ):
                if compiled.search(text):
                    return ClassifierResult(
                        category=category,
                        classification_method="rule",
                        confidence=1.0,
                        matched_pattern=raw,
                    )
        # No category fired — fall back to uncategorized per ADR-0026
        # D107 (emit-not-noop posture for visibility into "the
        # classifier saw this reply but had no match").
        return ClassifierResult(
            category="uncategorized",
            classification_method="rule",
            confidence=1.0,
            matched_pattern=None,
        )

    @staticmethod
    def _extract_text(reply_event: dict) -> str:
        # Thin wrapper preserving the Week 2 caller surface; the
        # implementation lives in the module-level :func:`extract_reply_text`
        # function so the Pillar D Week 6-8 LLM fallback classifier
        # (`orchestrator/reply_classifier_llm.py`) can import + call it
        # directly without the private-method coupling that the Week 6-8
        # per-week review's P2-B flagged.
        return extract_reply_text(reply_event)


def extract_reply_text(reply_event: dict) -> str:
    """Extract the classification-relevant text from a reply event.

    Single source of truth for "which fields on a reply event does the
    classifier read?" — used by both the Week 2-3 rule classifier
    (:meth:`RuleBasedClassifier.classify` → :meth:`_extract_text`) AND
    the Week 6-8 LLM fallback classifier
    (:class:`orchestrator.reply_classifier_llm.LLMFallbackClassifier`).

    The two classifiers MUST read the same fields so the LLM is asked
    to classify the SAME text the rule classifier inspected. A divergence
    here would let the LLM see different content than the rule —
    operator-confusing + breaks the "LLM extends rule coverage" model
    per ADR-0029 D124.

    Reads ``subject``, ``body``, and ``snippet`` in that order; joins
    with newlines. Skips any field that is not a non-empty string.

    Promoted from a private :meth:`RuleBasedClassifier._extract_text`
    static method to a module-level function in the Pillar D Week 6-8
    follow-up commit (per the per-week review's P2-B finding — the
    private-method import coupling from the LLM fallback classifier was
    a forward-maintenance hazard). The static method is preserved as a
    thin wrapper for Week 2 caller backwards-compat.
    """
    parts: list[str] = []
    for key in ("subject", "body", "snippet"):
        v = reply_event.get(key)
        if isinstance(v, str) and v:
            parts.append(v)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


def build_classified_payload(
    reply_event: dict, result: ClassifierResult,
) -> dict:
    """Construct the ``reply_classified`` event payload (no ledger append).

    Single source of truth for the event shape — both
    :func:`emit_classified_event` (live persistence) and
    :func:`reconcile.run_pass_g`'s dry-run path call this helper to
    avoid drift. The Pillar D Week 2 follow-up extracted this from
    :func:`emit_classified_event` after the per-week reviewer flagged
    that the dry-run path's manual payload reconstruction was a
    forward-maintenance hazard (a future field addition could be
    forgotten in the dry-run branch). Per the P3-C finding in the
    Week 2 review.

    Event shape (per ADR-0025 D97):

    .. code-block:: text

        type: reply_classified
        person_id
        channel (mandatory per D33-extended-by-D96)
        reply_message_id (the originating reply's gmail_message_id /
            linkedin_message_id / etc.)
        reply_to_intent_id (optional — None for Pass B's pre-Pillar-D
            email-reply emits; Week 3+ per-channel reply passes
            populate directly)
        category, classification_method, confidence, matched_pattern
        gmail_thread_id (preserved when the reply is on an email
            thread — Pillar G's per-thread timeline dashboard
            depends on this)
        _emitted_by: "reply_classifier"  (per ADR-0010 D17 convention)
    """
    # Per ADR-0025 §Migration/rollout item 3 — pre-Pillar-D-Week-1 Pass
    # B emits lack the channel field; treat absent channel as email per
    # the historical default.
    channel = reply_event.get("channel") or "email"
    # Per ADR-0026 D104 — the originating reply's message id is the
    # idempotence-pair component (with channel). Pass B's emit shape
    # carries this as ``gmail_message_id``; future per-channel reply
    # passes (Week 3+) name the field ``reply_message_id`` directly.
    # The classifier handles both shapes for cross-channel uniformity.
    reply_msg_id = (
        reply_event.get("reply_message_id")
        or reply_event.get("gmail_message_id")
    )
    payload: dict = {
        "type": "reply_classified",
        "person_id": reply_event.get("person_id"),
        "channel": channel,
        "reply_message_id": reply_msg_id,
        "reply_to_intent_id": reply_event.get("reply_to_intent_id"),
        "category": result.category,
        "classification_method": result.classification_method,
        "confidence": result.confidence,
        "matched_pattern": result.matched_pattern,
        "_emitted_by": "reply_classifier",
    }
    # Preserve the thread id for thread-aware queries (Pillar G
    # dashboards render the conversation timeline via
    # query_by_gmail_thread_id). Only stamp when the original reply
    # carried one — LinkedIn / Twitter / calendar replies (Week 3+)
    # won't have gmail_thread_id.
    tid = reply_event.get("gmail_thread_id")
    if tid:
        payload["gmail_thread_id"] = tid
    return payload


def emit_classified_event(
    led: "_ledger.Ledger",
    reply_event: dict,
    result: ClassifierResult,
) -> dict:
    """Append a ``reply_classified`` event correlating back to the reply.

    Per ADR-0025 D97 + ADR-0026 D104. Constructs the payload via
    :func:`build_classified_payload` (single source of truth for the
    event shape — shared with :func:`reconcile.run_pass_g`'s dry-run
    path).

    Returns the persisted event dict (with ``ts`` + ``v`` filled in per
    the ledger's standard ``append`` contract).
    """
    # Per ADR-0055 D302 — wrap the emit in a reply-stage span so
    # operators see per-reply classification metadata in the OTel
    # tracing backend. Per-attribute filtering on channel + person_id
    # + category + classification_method matches the per-event-class
    # MetricSnapshot breakdown surface per ADR-0014 D33 + ADR-0050
    # D276(c) + ADR-0051 D281.
    channel = reply_event.get("channel") or "email"
    span_attrs: dict[str, str] = {
        "channel": channel,
        "category": result.category,
        "classification_method": result.classification_method,
    }
    person_id = reply_event.get("person_id")
    if person_id:
        span_attrs["person_id"] = person_id
    with traced_stage(
        "reply", "classify", attributes=span_attrs,
    ):
        return led.append(build_classified_payload(reply_event, result))
