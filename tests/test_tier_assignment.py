"""Tests for orchestrator/tier_assignment.py — Pillar E Week 6-8.

Covers the tier auto-assignment primitive per ADR-0035 D160-D165:
:class:`TierSuggestion` dataclass invariants,
:func:`compute_tier_from_signals` happy paths + partial-signal graceful
degradation + legacy-fallback normalization, event-payload factory
contract per D161 channel-on-every-event invariant, the weights config
loader's default-template fallback per D163, the deterministic-clock
pin via the ``now`` parameter (per ADR-0031 D140 + ADR-0034 D156
precedent), the CLI's `--apply` flag behavior + Person-id lookup, and
the module-level constants the cross-pillar audit pins.

Run:
    cd /Users/yang/code/outreach-factory && pytest tests/test_tier_assignment.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from orchestrator import tier_assignment
from orchestrator import ledger as _ledger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def led(tmp_path: Path) -> _ledger.Ledger:
    """Per-test isolated ledger directory."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    return _ledger.Ledger(ledger_dir)


@pytest.fixture
def default_weights() -> dict:
    """Load the default-shipped weights template.

    Mirrors the operator's first-invocation experience (the
    operator's config is absent; the primitive falls back to the
    default template). Pin the default weights so the per-method
    happy paths assert against a known config.
    """
    template = Path(__file__).resolve().parent.parent / "config-template" / "tier_weights.example.yml"
    with template.open() as f:
        return yaml.safe_load(f)


@pytest.fixture
def fixed_now() -> datetime:
    """Deterministic wall-clock anchor — 2026-05-24T12:00:00Z.

    Anchors funding-recency computations against a fixed date so
    `funding_date: 2026-04-01` always reads as ~53 days ago.
    """
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# TierSuggestion invariants — ADR-0035 D161
# ---------------------------------------------------------------------------


class TestTierSuggestionInvariants:
    """Construction-time invariants on the :class:`TierSuggestion` dataclass."""

    def test_valid_construction(self):
        sug = tier_assignment.TierSuggestion(
            suggested_tier="S",
            person_id="dylan-li",
            signals_consulted={"industry": "ai_ml"},
            rationale="AI/ML industry → S tier",
            score=3,
        )
        assert sug.suggested_tier == "S"
        assert sug.person_id == "dylan-li"
        assert sug.signals_consulted == {"industry": "ai_ml"}
        assert sug.rationale == "AI/ML industry → S tier"
        assert sug.score == 3

    def test_rejects_non_enum_tier(self):
        with pytest.raises(ValueError, match="suggested_tier must be one of"):
            tier_assignment.TierSuggestion(
                suggested_tier="AA",  # invalid
                person_id="dylan-li",
                signals_consulted={},
                rationale="bad",
                score=0,
            )

    def test_rejects_empty_person_id(self):
        with pytest.raises(ValueError, match="non-empty person_id"):
            tier_assignment.TierSuggestion(
                suggested_tier="B",
                person_id="",
                signals_consulted={},
                rationale="",
                score=0,
            )

    def test_rejects_non_dict_signals_consulted(self):
        with pytest.raises(ValueError, match="signals_consulted must be a dict"):
            tier_assignment.TierSuggestion(
                suggested_tier="B",
                person_id="dylan-li",
                signals_consulted=["not a dict"],  # type: ignore[arg-type]
                rationale="",
                score=0,
            )

    def test_dataclass_is_frozen(self):
        sug = tier_assignment.TierSuggestion(
            suggested_tier="A",
            person_id="dylan-li",
            signals_consulted={},
            rationale="",
            score=2,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            sug.suggested_tier = "S"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# compute_tier_from_signals — happy paths + partial-signal degradation
# ---------------------------------------------------------------------------


class TestComputeTierFromSignalsHappyPaths:
    """Per-signal weight contribution + threshold matching per D161 + D162."""

    def test_high_intent_series_a_founder_lands_S_tier(
        self, default_weights, fixed_now,
    ):
        """ADR-0035 D161 happy path — every signal aligned for S tier.

        Series A AI/ML founder discovered via find-funded-founders +
        funding within 90 days → high-intent S tier. Score:
        funding_stage=series_a(2) + industry=ai_ml(2) +
        source_skill=find-funded-founders(2) + funding_recency(1) +
        organization_size=mid(1) = 8 ≥ 4 → S.
        """
        frontmatter = {
            "type": "person",
            "name": "Test Founder",
            "organization_size": "mid",
            "industry": "ai_ml",
            "funding_stage": "series_a",
            "funding_date": date(2026, 4, 1),  # ~53 days before fixed_now
            "identity_keys": {
                "discovery_lineage": {
                    "source_skill": "find-funded-founders",
                },
            },
        }
        sug = tier_assignment.compute_tier_from_signals(
            "test-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.suggested_tier == "S"
        assert sug.score == 8
        assert "Series A funding" in sug.rationale
        assert "AI/ML industry" in sug.rationale
        assert "find-funded-founders source" in sug.rationale
        assert "→ score 8 →" in sug.rationale
        assert sug.rationale.endswith("high-intent S tier")

    def test_mid_intent_lands_A_tier(self, default_weights, fixed_now):
        """ADR-0035 D162 — moderate signals → A tier.

        Seed-stage SaaS startup via find-funded-founders, no recent
        funding date, no organization_size. Score:
        funding_stage=seed(2) + industry=saas(1) +
        source_skill=find-funded-founders(2) = 5 ≥ 4 → S?
        Actually that's still S. Let me design for A: drop
        industry, drop find-funded-founders. Just funding_stage=seed
        + organization_size=mid + source_skill=find-leads(0) → 2+1+0=3 → A.
        """
        frontmatter = {
            "type": "person",
            "name": "Test Founder",
            "organization_size": "mid",
            "funding_stage": "seed",
            "source_channel": "find-leads",  # legacy field; weight 0
        }
        sug = tier_assignment.compute_tier_from_signals(
            "test-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.suggested_tier == "A"
        assert sug.score == 3  # mid(1) + seed(2) + find-leads(0)
        assert "→ score 3 →" in sug.rationale
        assert "mid-intent A tier" in sug.rationale

    def test_low_signal_lands_B_tier(self, default_weights, fixed_now):
        """ADR-0035 D162 default-low B floor — minimal signals.

        Manual entry, no firmographic, no funding.  Score: 0 → B.
        """
        frontmatter = {
            "type": "person",
            "name": "Test Person",
            "source_channel": "manual",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "test-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.suggested_tier == "B"
        assert sug.score == 0
        assert "→ score 0 →" in sug.rationale

    def test_competitor_customers_high_precision_lands_S(
        self, default_weights, fixed_now,
    ):
        """ADR-0035 D162 — competitor-customers as high-intent signal.

        Score: source_skill=competitor-customers(2) +
        funding_stage=series_a(2) = 4 ≥ 4 → S.
        """
        frontmatter = {
            "type": "person",
            "name": "Customer",
            "funding_stage": "series_a",
            "identity_keys": {
                "discovery_lineage": {
                    "source_skill": "competitor-customers",
                },
            },
        }
        sug = tier_assignment.compute_tier_from_signals(
            "customer-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.suggested_tier == "S"
        assert "competitor-customers source" in sug.rationale
        assert "high-precision" in sug.rationale


class TestComputeTierFromSignalsPartialDegradation:
    """ADR-0035 D162 graceful-degradation contract — missing signals OK."""

    def test_empty_frontmatter_lands_B_tier_with_named_missing_signals(
        self, default_weights, fixed_now,
    ):
        """ADR-0035 D162 — empty frontmatter doesn't crash; emits B."""
        sug = tier_assignment.compute_tier_from_signals(
            "empty-li", {}, weights=default_weights, now=fixed_now,
        )
        assert sug.suggested_tier == "B"
        assert sug.score == 0
        # Rationale names the absent firmographic signals.
        assert "Limited firmographic signals" in sug.rationale
        assert "organization_size/industry/funding_stage absent" in sug.rationale
        # signals_consulted carries the None values.
        assert sug.signals_consulted["organization_size"] is None
        assert sug.signals_consulted["industry"] is None
        assert sug.signals_consulted["funding_stage"] is None
        assert sug.signals_consulted["source_skill"] is None

    def test_intent_only_no_firmographic_lands_B_or_A(
        self, default_weights, fixed_now,
    ):
        """ADR-0035 D162 — intent signal alone is insufficient for S.

        find-funded-founders source alone → score 2 → A (the threshold
        for A is 2). Without firmographic + recency, the framework
        cannot confidently push to S.
        """
        frontmatter = {
            "type": "person",
            "source_channel": "funded-founders",  # legacy → find-funded-founders
        }
        sug = tier_assignment.compute_tier_from_signals(
            "intent-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.suggested_tier == "A"
        assert sug.score == 2

    def test_missing_signals_contribute_zero_not_penalty(
        self, default_weights, fixed_now,
    ):
        """ADR-0035 D162 — absence is observed, not penalized.

        Compare two Persons: one with `industry: ai_ml` (weight 2)
        + nothing else; one with ONLY industry absent. The first
        should score 2; the second should score 0 (NOT a negative
        weight for absence).
        """
        with_ai = {
            "type": "person",
            "industry": "ai_ml",
            "source_channel": "manual",
        }
        without_ai = {
            "type": "person",
            "source_channel": "manual",
        }
        sug_with = tier_assignment.compute_tier_from_signals(
            "with-li", with_ai, weights=default_weights, now=fixed_now,
        )
        sug_without = tier_assignment.compute_tier_from_signals(
            "without-li", without_ai, weights=default_weights, now=fixed_now,
        )
        assert sug_with.score == 2  # industry ai_ml = 2
        assert sug_without.score == 0  # no contribution; NOT -2

    def test_signals_consulted_dict_carries_None_for_missing(
        self, default_weights, fixed_now,
    ):
        """ADR-0035 D161 — signals_consulted operator-visible coverage.

        Operators auditing 'why did the primitive suggest B?' see
        the None values for missing signals + the populated values
        for present ones.
        """
        frontmatter = {
            "type": "person",
            "industry": "ai_ml",
            "source_channel": "find-funded-founders",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "partial-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["industry"] == "ai_ml"
        assert sug.signals_consulted["source_skill"] == "find-funded-founders"
        assert sug.signals_consulted["organization_size"] is None
        assert sug.signals_consulted["funding_stage"] is None
        assert sug.signals_consulted["funding_recency_days"] is None


class TestComputeTierFromSignalsLegacyFallbacks:
    """ADR-0035 D162 legacy field normalization (Week 6-8 back-compat)."""

    def test_legacy_source_channel_normalizes_to_canonical_source_skill(
        self, default_weights, fixed_now,
    ):
        """The find-funded-founders SKILL.md emits
        ``source_channel: funded-founders`` (legacy); D162 normalizes
        to ``source_skill: find-funded-founders``."""
        frontmatter = {
            "type": "person",
            "source_channel": "funded-founders",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "legacy-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["source_skill"] == "find-funded-founders"
        # The weight for find-funded-founders is 2 → score 2 → A tier.
        assert sug.score == 2
        assert sug.suggested_tier == "A"

    def test_legacy_round_stage_normalizes_to_canonical_funding_stage(
        self, default_weights, fixed_now,
    ):
        """find-funded-founders emits ``round_stage: Series A``
        (human-readable); D162 normalizes to ``funding_stage:
        series_a`` for the weights lookup."""
        frontmatter = {
            "type": "person",
            "round_stage": "Series A",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "legacy-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["funding_stage"] == "series_a"
        assert sug.score == 2  # series_a = 2 → A
        assert sug.suggested_tier == "A"

    def test_canonical_funding_stage_wins_over_legacy_round_stage(
        self, default_weights, fixed_now,
    ):
        """When both canonical + legacy are present, canonical wins."""
        frontmatter = {
            "type": "person",
            "funding_stage": "seed",      # canonical wins
            "round_stage": "Series A",    # legacy ignored
        }
        sug = tier_assignment.compute_tier_from_signals(
            "both-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["funding_stage"] == "seed"

    def test_canonical_discovery_lineage_wins_over_legacy_source_channel(
        self, default_weights, fixed_now,
    ):
        """When both canonical + legacy are present, canonical wins."""
        frontmatter = {
            "type": "person",
            "source_channel": "manual",  # legacy ignored
            "identity_keys": {
                "discovery_lineage": {
                    "source_skill": "find-funded-founders",  # canonical wins
                },
            },
        }
        sug = tier_assignment.compute_tier_from_signals(
            "both-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["source_skill"] == "find-funded-founders"


class TestComputeTierFromSignalsFundingRecency:
    """ADR-0035 D162 funding-recency window matching."""

    def test_recent_funding_within_90_days_contributes_weight(
        self, default_weights, fixed_now,
    ):
        """funding_date within 90 days → recency boost (+1 per default)."""
        frontmatter = {
            "type": "person",
            "funding_date": date(2026, 4, 1),  # 53 days before fixed_now
        }
        sug = tier_assignment.compute_tier_from_signals(
            "recent-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["funding_recency_days"] == 53
        assert sug.score == 1  # only the recency boost contributes

    def test_old_funding_outside_window_no_boost(
        self, default_weights, fixed_now,
    ):
        """funding_date older than 90 days → no recency boost."""
        frontmatter = {
            "type": "person",
            "funding_date": date(2025, 1, 1),  # >365 days before fixed_now
        }
        sug = tier_assignment.compute_tier_from_signals(
            "old-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["funding_recency_days"] is not None
        assert sug.signals_consulted["funding_recency_days"] > 90
        assert sug.score == 0  # no recency boost

    def test_funding_date_string_form_parses(
        self, default_weights, fixed_now,
    ):
        """funding_date may be a string (not YAML date literal)."""
        frontmatter = {
            "type": "person",
            "funding_date": "2026-04-01",  # string form
        }
        sug = tier_assignment.compute_tier_from_signals(
            "string-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["funding_recency_days"] == 53

    def test_unparseable_funding_date_treated_as_absent(
        self, default_weights, fixed_now,
    ):
        """Malformed funding_date → treated as absent (no crash)."""
        frontmatter = {
            "type": "person",
            "funding_date": "not a date",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "bad-date-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        assert sug.signals_consulted["funding_recency_days"] is None

    def test_future_funding_date_treated_as_absent_not_zero(
        self, default_weights, fixed_now,
    ):
        """Per Week 6-8 follow-up P2-A: future funding_date treated as absent.

        Operators stamping an announced-but-not-yet-closed funding round
        with a future date (e.g., announced today, closes next week)
        previously had ``max(0, delta.days)`` clamp the recency to 0,
        which then matched every recency bucket (smallest default is
        90 days) and produced ``"Recent funding (within 0 days)"`` —
        operator-confusing AND scored an incorrect recency boost.

        The fix: future dates are treated as ``None`` (absent signal);
        the operator's eventual stamping of the actual closing date
        triggers the boost at that point.
        """
        # funding_date 6 days in the future (post-fixed_now anchor).
        frontmatter = {
            "type": "person",
            "funding_date": date(2026, 5, 30),
        }
        sug = tier_assignment.compute_tier_from_signals(
            "future-li", frontmatter, weights=default_weights, now=fixed_now,
        )
        # Treated as absent — None, NOT 0.
        assert sug.signals_consulted["funding_recency_days"] is None
        # No recency boost contributes.
        assert sug.score == 0
        # No "Recent funding (within 0 days)" in the rationale.
        assert "Recent funding (within 0 days)" not in sug.rationale


class TestComputeTierFromSignalsWeightsOverride:
    """ADR-0035 D163 weights override via kwarg."""

    def test_weights_kwarg_overrides_default(self, fixed_now):
        """The weights= kwarg lets tests inject custom configs."""
        custom_weights = {
            "signals": {
                "industry": {
                    "ai_ml": 100,
                },
            },
            "thresholds": {
                "S": 99,
                "A": 50,
            },
        }
        frontmatter = {
            "type": "person",
            "industry": "ai_ml",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "custom-li", frontmatter,
            weights=custom_weights, now=fixed_now,
        )
        # ai_ml weight 100 → score 100 ≥ S threshold 99 → S
        assert sug.score == 100
        assert sug.suggested_tier == "S"

    def test_threshold_tie_breaking_picks_highest_match(self, fixed_now):
        """ADR-0035 D162 threshold-matching: highest matching threshold wins."""
        weights = {
            "signals": {"industry": {"ai_ml": 3}},
            "thresholds": {"S": 3, "A": 1},
        }
        frontmatter = {"type": "person", "industry": "ai_ml"}
        sug = tier_assignment.compute_tier_from_signals(
            "tie-li", frontmatter, weights=weights, now=fixed_now,
        )
        assert sug.suggested_tier == "S"  # NOT A (3 >= 3 picks S)


# ---------------------------------------------------------------------------
# Weights config loading — ADR-0035 D163
# ---------------------------------------------------------------------------


class TestLoadWeights:
    """ADR-0035 D163 weights config loader contract."""

    def test_loads_default_template_when_operator_path_absent(
        self, tmp_path, capsys,
    ):
        """Missing operator config → falls back to default template + warns."""
        absent_path = tmp_path / "absent.yml"
        assert not absent_path.exists()
        weights = tier_assignment.load_weights(absent_path)
        assert "signals" in weights
        assert "thresholds" in weights
        # Stderr warning was emitted.
        captured = capsys.readouterr()
        assert "operator-tuned weights not found" in captured.err
        assert str(absent_path) in captured.err

    def test_loads_operator_config_when_present(self, tmp_path):
        """Operator config takes precedence over default template."""
        op_path = tmp_path / "tier_weights.yml"
        op_path.write_text(yaml.safe_dump({
            "signals": {"industry": {"ai_ml": 99}},
            "thresholds": {"S": 50, "A": 25},
        }))
        weights = tier_assignment.load_weights(op_path)
        assert weights["signals"]["industry"]["ai_ml"] == 99

    def test_rejects_non_dict_top_level(self, tmp_path):
        bad_path = tmp_path / "bad.yml"
        bad_path.write_text("- just a list\n- not a dict\n")
        with pytest.raises(ValueError, match="must be a top-level dict"):
            tier_assignment.load_weights(bad_path)

    def test_rejects_missing_signals_key(self, tmp_path):
        bad_path = tmp_path / "bad.yml"
        bad_path.write_text(yaml.safe_dump({
            "thresholds": {"S": 4, "A": 2},
        }))
        with pytest.raises(ValueError, match="must have a top-level ``signals:`` dict"):
            tier_assignment.load_weights(bad_path)

    def test_rejects_missing_thresholds_key(self, tmp_path):
        bad_path = tmp_path / "bad.yml"
        bad_path.write_text(yaml.safe_dump({
            "signals": {},
        }))
        with pytest.raises(ValueError, match="must have a top-level ``thresholds:`` dict"):
            tier_assignment.load_weights(bad_path)

    def test_rejects_non_integer_threshold_value(self, tmp_path):
        """Per Week 6-8 follow-up P3-E: threshold values must coerce to int.

        A typo'd YAML like ``S: four`` would previously produce an
        unguarded ValueError deep inside _match_tier at primitive-
        invocation time, with a traceback that surfaces a Python
        internal rather than an operator-readable diagnostic.
        """
        bad_path = tmp_path / "bad.yml"
        bad_path.write_text(yaml.safe_dump({
            "signals": {},
            "thresholds": {"S": "four", "A": 2},
        }))
        with pytest.raises(ValueError, match="not a valid integer"):
            tier_assignment.load_weights(bad_path)


class TestComputeTierFromSignalsZeroWeightContributions:
    """Per Week 6-8 follow-up P2-B: zero-weight contributions don't
    inflate the rationale's tier-category label to "moderate"."""

    def test_zero_weight_only_contribution_labels_as_default_low(
        self, fixed_now,
    ):
        """A signal with weight 0 doesn't constitute "moderate" corroboration.

        Operators reading the rationale see "default-low B tier" when
        the only contributions are zero-weight (e.g., source_skill=manual
        with the default weight of 0); "moderate B tier" misleadingly
        implies some signal moved the score.
        """
        weights = {
            "signals": {"source_skill": {"manual": 0}},
            "thresholds": {"S": 4, "A": 2},
        }
        frontmatter = {
            "type": "person",
            "source_channel": "manual",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "manual-li", frontmatter, weights=weights, now=fixed_now,
        )
        assert sug.score == 0
        assert sug.suggested_tier == "B"
        # The category label is "default-low" (no signals moved the
        # score), NOT "moderate" (which would imply some signal
        # corroborated B tier).
        assert "default-low B tier" in sug.rationale
        assert "moderate B tier" not in sug.rationale

    def test_nonzero_weight_partial_contribution_labels_as_moderate(
        self, fixed_now,
    ):
        """A nonzero contribution at B tier still labels as "moderate".

        E.g., a +1 boost that didn't reach the A threshold of +2
        should still be labeled "moderate B tier" — the score moved
        but not enough to cross the threshold.
        """
        weights = {
            "signals": {
                "industry": {"saas": 1},
                "source_skill": {"manual": 0},
            },
            "thresholds": {"S": 4, "A": 2},
        }
        frontmatter = {
            "type": "person",
            "industry": "saas",
            "source_channel": "manual",
        }
        sug = tier_assignment.compute_tier_from_signals(
            "saas-manual-li", frontmatter,
            weights=weights, now=fixed_now,
        )
        assert sug.score == 1  # below A threshold of 2 → still B
        assert sug.suggested_tier == "B"
        # SaaS industry contributed +1 → "moderate", not "default-low".
        assert "moderate B tier" in sug.rationale
        assert "default-low B tier" not in sug.rationale


# ---------------------------------------------------------------------------
# build_tier_suggested_payload — ADR-0035 D161 emit-shape contract
# ---------------------------------------------------------------------------


class TestBuildTierSuggestedPayload:
    """Per-field contract checks for the event payload factory."""

    @pytest.fixture
    def suggestion(self):
        return tier_assignment.TierSuggestion(
            suggested_tier="S",
            person_id="dylan-li",
            signals_consulted={
                "organization_size": "mid",
                "industry": "ai_ml",
                "funding_stage": "series_a",
                "source_skill": "find-funded-founders",
                "funding_recency_days": 30,
            },
            rationale="Series A + AI/ML → S tier",
            score=8,
        )

    def test_payload_type_is_tier_suggested(self, suggestion):
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert payload["type"] == "tier_suggested"

    def test_payload_carries_person_id(self, suggestion):
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert payload["person_id"] == "dylan-li"

    def test_payload_carries_suggested_tier(self, suggestion):
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert payload["suggested_tier"] == "S"

    def test_payload_carries_signals_consulted_dict(self, suggestion):
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert payload["signals_consulted"] == {
            "organization_size": "mid",
            "industry": "ai_ml",
            "funding_stage": "series_a",
            "source_skill": "find-funded-founders",
            "funding_recency_days": 30,
        }

    def test_payload_carries_rationale_string(self, suggestion):
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert payload["rationale"] == "Series A + AI/ML → S tier"

    def test_payload_carries_channel_none_per_d161(self, suggestion):
        """Per ADR-0035 D161 — tier is channel-agnostic; mirrors dedup primitive."""
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert payload["channel"] == "none"

    def test_payload_carries_emitted_by_marker(self, suggestion):
        """Per ADR-0010 D17 — _emitted_by enables operator-facing filtering."""
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert payload["_emitted_by"] == "tier_assignment"

    def test_payload_signals_consulted_is_a_copy_not_alias(self, suggestion):
        """Mutating the payload's signals_consulted MUST NOT mutate the suggestion."""
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        payload["signals_consulted"]["industry"] = "MUTATED"
        assert suggestion.signals_consulted["industry"] == "ai_ml"

    def test_payload_field_set_is_exactly_pinned(self, suggestion):
        """Per ADR-0035 D161 — pin the field set exactly to prevent drift."""
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        assert set(payload.keys()) == {
            "type",
            "person_id",
            "suggested_tier",
            "signals_consulted",
            "rationale",
            "channel",
            "_emitted_by",
        }


# ---------------------------------------------------------------------------
# Module constants — ADR-0035 D161 + D163
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Per ADR-0035 D161 + D163 the constants must be the single source of truth."""

    def test_suggested_tiers_is_closed_enum(self):
        assert tier_assignment.SUGGESTED_TIERS == frozenset({"S", "A", "B"})

    def test_emitted_by_marker_reserved(self):
        assert tier_assignment.EMITTED_BY == "tier_assignment"

    def test_channel_value_is_none_per_d161(self):
        """Per ADR-0035 D161 — tier is channel-agnostic; mirrors dedup primitive."""
        assert tier_assignment.CHANNEL_VALUE == "none"

    def test_default_weights_path_is_in_operator_home(self):
        assert tier_assignment.DEFAULT_TIER_WEIGHTS_PATH == (
            Path.home() / ".outreach-factory" / "tier_weights.yml"
        )


# ---------------------------------------------------------------------------
# CLI integration smoke test
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    """ADR-0035 D164 operator-invoked CLI contract."""

    def _write_person_note(self, people_dir: Path, person_id: str, fm: dict):
        people_dir.mkdir(parents=True, exist_ok=True)
        body = "---\n"
        body += yaml.safe_dump({"type": "person", "id": person_id, **fm}, sort_keys=False)
        body += "---\n# Test Person\n"
        (people_dir / f"{person_id}.md").write_text(body)

    def test_find_person_note_by_id(self, tmp_path):
        """Per-Person lookup by frontmatter id."""
        people_dir = tmp_path / "10 People"
        self._write_person_note(people_dir, "dylan-li", {"industry": "ai_ml"})
        found = tier_assignment._find_person_note_by_id("dylan-li", people_dir)
        assert found is not None
        note_path, fm = found
        assert note_path.name == "dylan-li.md"
        assert fm["industry"] == "ai_ml"

    def test_find_person_returns_none_for_missing_id(self, tmp_path):
        people_dir = tmp_path / "10 People"
        people_dir.mkdir(parents=True)
        assert tier_assignment._find_person_note_by_id(
            "absent-li", people_dir,
        ) is None

    def test_apply_emits_event_to_ledger(self, led, default_weights, fixed_now):
        """ADR-0035 D164 --apply flag emits the event."""
        frontmatter = {
            "type": "person",
            "industry": "ai_ml",
            "funding_stage": "series_a",
        }
        suggestion = tier_assignment.compute_tier_from_signals(
            "applied-li", frontmatter,
            weights=default_weights, now=fixed_now,
        )
        payload = tier_assignment.build_tier_suggested_payload(suggestion)
        tier_assignment._safe_append(led, payload)

        events = list(led.all_events())
        tier_events = [e for e in events
                       if e.get("type") == "tier_suggested"]
        assert len(tier_events) == 1
        assert tier_events[0]["person_id"] == "applied-li"
        assert tier_events[0]["suggested_tier"] == "S"
        assert tier_events[0]["channel"] == "none"
        assert tier_events[0]["_emitted_by"] == "tier_assignment"


# ---------------------------------------------------------------------------
# Deterministic clock — ADR-0031 D140 + ADR-0034 D156 precedent
# ---------------------------------------------------------------------------


class TestDeterministicClock:
    """The now kwarg pins wall-clock for reproducibility."""

    def test_now_parameter_pins_funding_recency_calculation(
        self, default_weights,
    ):
        """Same Person + same now → same suggestion every call."""
        frontmatter = {
            "type": "person",
            "funding_date": date(2026, 4, 1),
        }
        anchor = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        sug1 = tier_assignment.compute_tier_from_signals(
            "det-li", frontmatter, weights=default_weights, now=anchor,
        )
        sug2 = tier_assignment.compute_tier_from_signals(
            "det-li", frontmatter, weights=default_weights, now=anchor,
        )
        assert sug1.suggested_tier == sug2.suggested_tier
        assert sug1.score == sug2.score
        assert sug1.signals_consulted == sug2.signals_consulted

    def test_different_now_can_yield_different_recency_bucket(
        self, default_weights,
    ):
        """now=today → recent; now=180-days-later → outside-window."""
        frontmatter = {
            "type": "person",
            "funding_date": date(2026, 4, 1),
        }
        early_anchor = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
        late_anchor = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
        sug_early = tier_assignment.compute_tier_from_signals(
            "early-li", frontmatter, weights=default_weights, now=early_anchor,
        )
        sug_late = tier_assignment.compute_tier_from_signals(
            "late-li", frontmatter, weights=default_weights, now=late_anchor,
        )
        # Within 90 days → recency boost; >90 days → no boost.
        assert sug_early.score == 1  # boost
        assert sug_late.score == 0   # no boost


# ---------------------------------------------------------------------------
# Default template loads + has expected shape
# ---------------------------------------------------------------------------


class TestDefaultTemplate:
    """The default-shipped template must have the expected shape."""

    def test_default_template_exists(self):
        template = (
            Path(__file__).resolve().parent.parent
            / "config-template" / "tier_weights.example.yml"
        )
        assert template.exists()

    def test_default_template_loads_via_load_weights(self):
        template = (
            Path(__file__).resolve().parent.parent
            / "config-template" / "tier_weights.example.yml"
        )
        weights = tier_assignment.load_weights(template)
        assert "signals" in weights
        assert "thresholds" in weights

    def test_default_template_has_all_signal_blocks(self, default_weights):
        """All five signal kinds appear in the default template."""
        assert "organization_size" in default_weights["signals"]
        assert "industry" in default_weights["signals"]
        assert "funding_stage" in default_weights["signals"]
        assert "source_skill" in default_weights["signals"]
        assert "funding_recency_days" in default_weights["signals"]

    def test_default_template_has_S_and_A_thresholds(self, default_weights):
        assert "S" in default_weights["thresholds"]
        assert "A" in default_weights["thresholds"]
        # S threshold should be strictly greater than A threshold
        # (operator-deliberate ordering).
        assert int(default_weights["thresholds"]["S"]) > int(
            default_weights["thresholds"]["A"]
        )
