"""Unit tests for the Pillar F Week 7 per-claim-type corpora + measurement primitive.

Per ADR-0044 (D220-D227) — the per-claim-type test corpora at
``tests/fixtures/draft_quality_corpus/`` + the measurement primitive
``measure_per_claim_type_false_positive_rate`` at
``orchestrator/draft_quality.py``. The measurement primitive walks
the corpus, runs :func:`score_draft` per pair, aggregates outcomes
against ``expected_state`` ground truth + returns a
:class:`CorpusMeasurement` with TP/TN/FP/FN tallies + accuracy +
false-positive rate + false-negative rate.

Test class layout (mirrors the Pillar D Week 12 corpus benchmark
pattern at ``tests/test_multi_channel_coherence.py::TestPillarDExitCriterion``
+ the Pillar F Week 6 test layout at ``tests/test_draft_quality.py``):

* :class:`TestCorpusFiles` — pin the shipped corpus files' structure.
* :class:`TestCorpusPair` — :class:`CorpusPair` construction-time
  invariants per ADR-0044 D222.
* :class:`TestCorpusMeasurement` — :class:`CorpusMeasurement`
  construction-time invariants per ADR-0044 D223.
* :class:`TestLoadCorpusFile` — corpus loader behavior +
  refuse-loud surfaces.
* :class:`TestMeasurePerClaimTypeFalsePositiveRate` — measurement
  primitive behavior + the TEST-ONLY ``embed_fn`` seam preservation
  per ADR-0044 D227.
* :class:`TestCorpusBenchmark` — per-claim-type benchmark tests
  with regression-barrier rate bounds per ADR-0044 D225.
* :class:`TestCLIMeasure` — CLI ``measure`` subcommand per ADR-0044
  D224.

Test isolation: tests pass per-call ``thresholds_path`` to control
the per-register threshold loader; CLI tests pass
``--thresholds-path`` explicitly + ``OUTREACH_FACTORY_CONFIG`` env to
avoid pulling the operator's real ``config.yml``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
import yaml

import draft_quality
from draft_quality import (
    CLAIM_TYPES,
    CorpusMeasurement,
    CorpusPair,
    measure_per_claim_type_false_positive_rate,
)
from voice_corpus import (
    CHANNELS,
    DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
    REGISTERS,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DRAFT_QUALITY_SCRIPT = REPO_ROOT / "orchestrator" / "draft_quality.py"
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "draft_quality_corpus"

# Per ADR-0044 D225 — Week 7 baseline regression-barrier targets +
# Week 11 corpus revision per ADR-0048 D256. The asymmetric-failure-
# cost discipline per ADR-0038 D180 + D184 motivates tighter FN_rate
# bounds (brand-risk path) over FP_rate (operator-friction path) —
# the FN_rate bounds are the LOAD-BEARING regression barriers.
#
# Week 11 bound recalibration (per ADR-0048 D256):
#   * `named_entity`: FP_rate_max 0.20 → 0.10; accuracy_min 0.55 →
#     0.70. Corpus extended with +7 paraphrased-ready pairs per
#     ADR-0048 D253; empirical post-extension rates FP_rate 0.000
#     (~10pp headroom) + accuracy 0.784 (~8pp headroom).
#   * `dated_event`: FP_rate_max 0.20 → 0.10; accuracy_min 0.65 →
#     0.70. Corpus extended with +5 paraphrased-ready pairs;
#     empirical post-extension rates FP_rate 0.000 (~10pp headroom)
#     + accuracy 0.829 (~13pp headroom). Per Week 11 follow-up
#     P2-2 — the original devt-r-p-003 design ("Loved the Q3 2026
#     announcement.") generated a cross-claim `date_reference: "Q3
#     2026"` claim that fuzzy-missed at 0.85 per ADR-0048 D254's
#     empirical encoder calibration finding; redesigned to "Loved
#     the August launch." (bare month substring-matches dossier
#     verbatim + dated_event paraphrased via word-order shift)
#     which avoids cross-claim cascade. Post-redesign all 5
#     paraphrased dated_event pairs cite via fuzzy; symmetric
#     tightening with named_entity (both FP_rate_max=0.10).
#   * `date_reference`: UNCHANGED. Per ADR-0048 D254 the framework
#     default encoder (BAAI/bge-small-en-v1.5) does NOT reliably
#     reach cosine ≥ 0.85 on date paraphrases (empirical: 0 of 9
#     candidates at Week 11 commit time); no paraphrased-ready
#     pairs added.
#   * `you_phrase` + `quoted_text`: UNCHANGED per ADR-0048 D257 +
#     ADR-0046 D240's attribution-claim exclusion. The W7 baseline
#     bounds preserve verbatim — the 0.20 FN_rate_max remains the
#     structural placeholder regression barrier (corpus design
#     gives ~0.00 baseline; no extension at Week 11 to exercise FN
#     path).
#
# FN_rate_max bounds are UNCHANGED at Week 11 for all five claim
# types. Paraphrased-ready pairs grow the TN denominator only;
# the FN cells (corpus=refused) are not touched at Week 11.
_CLAIM_TYPE_BENCHMARK_TARGETS: dict[str, dict[str, float]] = {
    "date_reference":  {"fp_rate_max": 0.40, "fn_rate_max": 0.40, "accuracy_min": 0.60},
    "named_entity":    {"fp_rate_max": 0.10, "fn_rate_max": 0.65, "accuracy_min": 0.70},
    "you_phrase":      {"fp_rate_max": 0.20, "fn_rate_max": 0.20, "accuracy_min": 0.85},
    "quoted_text":     {"fp_rate_max": 0.20, "fn_rate_max": 0.20, "accuracy_min": 0.85},
    "dated_event":     {"fp_rate_max": 0.10, "fn_rate_max": 0.55, "accuracy_min": 0.70},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_thresholds(path: Path, thresholds: dict | None = None) -> Path:
    if thresholds is None:
        thresholds = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
    path.write_text(yaml.safe_dump({"thresholds": thresholds}))
    return path


def _build_synthetic_corpus(
    tmp_path: Path,
    *,
    claim_type: str = "named_entity",
    register: str = "cold-pitch",
    channel: str = "email",
    pairs: list[dict] | None = None,
) -> Path:
    """Build a synthetic per-claim-type corpus directory in tmp_path.

    Returns the path to the corpus dir; the per-claim-type YAML
    file lives at ``corpus_dir/<claim_type>.yml``.
    """
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    if pairs is None:
        # Build minimal ~2-pair corpus by default.
        pairs = [
            {
                "id": "syn-001",
                "draft": "Following work at Foo Bar Inc.",
                "dossier": "Foo Bar Inc is a leader: https://example.com/foobar.",
                "expected_state": "ready",
            },
            {
                "id": "syn-002",
                "draft": "Saw what Acme Corp shipped.",
                "dossier": "Generic content. No companies mentioned.",
                "expected_state": "refused",
            },
        ]
    data = {
        "version": 1,
        "claim_type": claim_type,
        "register": register,
        "channel": channel,
        "pairs": pairs,
    }
    (corpus_dir / f"{claim_type}.yml").write_text(yaml.safe_dump(data, sort_keys=False))
    return corpus_dir


def _env(tmp_path: Path) -> dict:
    """Build a subprocess env with OUTREACH_FACTORY_CONFIG absent."""
    import os as _os
    absent_cfg = tmp_path / "nonexistent_config.yml"
    return {**_os.environ, "OUTREACH_FACTORY_CONFIG": str(absent_cfg)}


# ---------------------------------------------------------------------------
# Corpus files (shipped at tests/fixtures/draft_quality_corpus/)
# ---------------------------------------------------------------------------


class TestCorpusFiles:
    """Pin the shipped corpus files' structure per ADR-0044 D221 + D222."""

    def test_corpus_dir_exists(self):
        assert CORPUS_DIR.exists(), (
            f"Corpus directory {CORPUS_DIR} MUST exist per ADR-0044 D221"
        )
        assert CORPUS_DIR.is_dir()

    def test_corpus_readme_exists(self):
        readme = CORPUS_DIR / "README.md"
        assert readme.exists(), (
            "README.md MUST document the corpus structure + maintenance "
            "discipline per ADR-0044 §References"
        )

    def test_all_five_claim_types_have_corpus_files(self):
        """Per ADR-0044 D221 — one YAML file per claim type in CLAIM_TYPES."""
        for ct in CLAIM_TYPES:
            f = CORPUS_DIR / f"{ct}.yml"
            assert f.exists(), (
                f"Missing corpus file: {f}. Per ADR-0044 D221 the corpus "
                f"directory ships one YAML file per claim_type in {sorted(CLAIM_TYPES)!r}."
            )

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_corpus_files_load_cleanly_as_yaml(self, claim_type):
        f = CORPUS_DIR / f"{claim_type}.yml"
        data = yaml.safe_load(f.read_text())
        assert isinstance(data, dict)

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_corpus_claim_type_matches_filename(self, claim_type):
        """Per ADR-0044 D222 + D226 — claim_type field MUST match filename."""
        data = yaml.safe_load((CORPUS_DIR / f"{claim_type}.yml").read_text())
        assert data["claim_type"] == claim_type

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_corpus_register_in_closed_enum(self, claim_type):
        data = yaml.safe_load((CORPUS_DIR / f"{claim_type}.yml").read_text())
        assert data["register"] in REGISTERS

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_corpus_channel_in_closed_enum(self, claim_type):
        data = yaml.safe_load((CORPUS_DIR / f"{claim_type}.yml").read_text())
        assert data["channel"] in CHANNELS

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_corpus_pair_count_at_least_20(self, claim_type):
        """Per ADR-0044 D221 — each corpus ships ~30+ pairs for measurement signal."""
        data = yaml.safe_load((CORPUS_DIR / f"{claim_type}.yml").read_text())
        assert len(data["pairs"]) >= 20, (
            f"corpus {claim_type}.yml has only {len(data['pairs'])} pairs; "
            "per ADR-0044 D221 the corpus targets ~30+ pairs per claim type "
            "for meaningful FP/FN rate measurement."
        )

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_corpus_has_both_ready_and_refused_examples(self, claim_type):
        """Per ADR-0044 D221 — corpus partitions ~50/50 across ready/refused."""
        data = yaml.safe_load((CORPUS_DIR / f"{claim_type}.yml").read_text())
        states = {p["expected_state"] for p in data["pairs"]}
        assert states == {"ready", "refused"}, (
            f"corpus {claim_type}.yml must contain BOTH ready + refused "
            f"examples; got {sorted(states)}"
        )

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_corpus_pair_ids_unique_within_file(self, claim_type):
        data = yaml.safe_load((CORPUS_DIR / f"{claim_type}.yml").read_text())
        ids = [p["id"] for p in data["pairs"]]
        assert len(ids) == len(set(ids)), (
            f"corpus {claim_type}.yml has duplicate pair ids; per "
            "ADR-0044 D222 pair ids MUST be corpus-unique"
        )


# ---------------------------------------------------------------------------
# CorpusPair
# ---------------------------------------------------------------------------


class TestCorpusPair:
    """:class:`CorpusPair` construction-time invariants per ADR-0044 D222."""

    def test_construction_minimal_fields(self):
        p = CorpusPair(
            id="test-001",
            draft="Some draft.",
            dossier="Some dossier.",
            expected_state="ready",
        )
        assert p.id == "test-001"
        assert p.notes is None

    def test_construction_with_notes(self):
        p = CorpusPair(
            id="test-001",
            draft="Some draft.",
            dossier="Some dossier.",
            expected_state="refused",
            notes="Pattern X — bare event",
        )
        assert p.notes == "Pattern X — bare event"

    def test_empty_id_refuses(self):
        with pytest.raises(ValueError, match="id must be a non-empty string"):
            CorpusPair(id="", draft="d", dossier="x", expected_state="ready")

    def test_whitespace_only_id_refuses(self):
        with pytest.raises(ValueError, match="id must be a non-empty string"):
            CorpusPair(id="   ", draft="d", dossier="x", expected_state="ready")

    def test_empty_draft_refuses(self):
        with pytest.raises(ValueError, match="draft must be a non-empty string"):
            CorpusPair(id="t", draft="", dossier="x", expected_state="ready")

    def test_empty_dossier_refuses(self):
        with pytest.raises(ValueError, match="dossier must be a non-empty string"):
            CorpusPair(id="t", draft="d", dossier="", expected_state="ready")

    def test_unknown_expected_state_refuses(self):
        with pytest.raises(ValueError, match="expected_state"):
            CorpusPair(
                id="t", draft="d", dossier="x",
                expected_state="not-a-state",
            )

    @pytest.mark.parametrize("state", ["ready", "refused"])
    def test_both_expected_states_accepted(self, state):
        p = CorpusPair(id="t", draft="d", dossier="x", expected_state=state)
        assert p.expected_state == state

    def test_frozen_dataclass(self):
        p = CorpusPair(id="t", draft="d", dossier="x", expected_state="ready")
        with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError
            p.id = "other"


# ---------------------------------------------------------------------------
# CorpusMeasurement
# ---------------------------------------------------------------------------


def _basic_measurement(**overrides) -> CorpusMeasurement:
    defaults: dict = {
        "claim_type": "named_entity",
        "register": "cold-pitch",
        "channel": "email",
        "pair_count": 10,
        "true_positive": 4,
        "true_negative": 4,
        "false_positive": 1,
        "false_negative": 1,
        "accuracy": 0.8,
        "false_positive_rate": 0.2,
        "false_negative_rate": 0.2,
    }
    defaults.update(overrides)
    return CorpusMeasurement(**defaults)


class TestCorpusMeasurement:
    """:class:`CorpusMeasurement` construction-time invariants per ADR-0044 D223."""

    def test_construction_minimal_fields(self):
        m = _basic_measurement()
        assert m.claim_type == "named_entity"
        assert m.pair_count == 10

    def test_unknown_claim_type_refuses(self):
        with pytest.raises(ValueError, match="claim_type"):
            _basic_measurement(claim_type="not-a-type")

    def test_unknown_register_refuses(self):
        with pytest.raises(ValueError, match="register"):
            _basic_measurement(register="not-a-register")

    def test_unknown_channel_refuses(self):
        with pytest.raises(ValueError, match="channel"):
            _basic_measurement(channel="not-a-channel")

    def test_negative_pair_count_refuses(self):
        with pytest.raises(ValueError, match="pair_count"):
            _basic_measurement(pair_count=-1)

    def test_negative_tp_refuses(self):
        with pytest.raises(ValueError, match="true_positive"):
            _basic_measurement(true_positive=-1)

    def test_negative_fn_refuses(self):
        with pytest.raises(ValueError, match="false_negative"):
            _basic_measurement(false_negative=-1)

    def test_subset_invariant_violation_refuses(self):
        """TP+TN+FP+FN MUST equal pair_count per ADR-0044 D223."""
        with pytest.raises(ValueError, match="tally invariant"):
            _basic_measurement(
                pair_count=10,
                true_positive=3, true_negative=3,
                false_positive=1, false_negative=1,  # sum=8 != 10
            )

    def test_subset_invariant_zero_pair_count_accepted(self):
        m = _basic_measurement(
            pair_count=0,
            true_positive=0, true_negative=0,
            false_positive=0, false_negative=0,
            accuracy=0.0,
            false_positive_rate=0.0, false_negative_rate=0.0,
        )
        assert m.pair_count == 0

    def test_accuracy_out_of_range_refuses(self):
        with pytest.raises(ValueError, match="accuracy"):
            _basic_measurement(accuracy=1.5)

    def test_fp_rate_out_of_range_refuses(self):
        with pytest.raises(ValueError, match="false_positive_rate"):
            _basic_measurement(false_positive_rate=-0.1)

    def test_fn_rate_out_of_range_refuses(self):
        with pytest.raises(ValueError, match="false_negative_rate"):
            _basic_measurement(false_negative_rate=2.0)

    def test_bool_threshold_caught_explicitly(self):
        """Python's bool-is-an-int footgun caught per ADR-0041 D201 precedent."""
        with pytest.raises(ValueError, match="accuracy"):
            _basic_measurement(accuracy=True)

    def test_bool_pair_count_refused(self):
        """Per Week 7 follow-up P3-1 — bool catch regression barrier for count fields.

        The ADR-0041 D201 bool-is-an-int footgun discipline applies to
        ALL count fields, not just rate fields. The existing
        ``test_bool_threshold_caught_explicitly`` covers the rate-field
        case (accuracy); this test closes the count-field gap. The
        implementation loops over five count fields with explicit
        ``isinstance(v, bool)`` checks; a future refactor that inlined
        the loop or removed the bool check from one field would be
        caught here.
        """
        # Construct a measurement where pair_count is True (= int 1)
        # and the tally satisfies the subset invariant; the bool catch
        # must fire BEFORE the subset invariant check.
        with pytest.raises(ValueError, match="pair_count"):
            _basic_measurement(
                pair_count=True,
                true_positive=1, true_negative=0,
                false_positive=0, false_negative=0,
                accuracy=1.0, false_positive_rate=0.0, false_negative_rate=0.0,
            )

    def test_bool_true_positive_refused(self):
        """Per Week 7 follow-up P3-1 — bool catch on true_positive count field."""
        with pytest.raises(ValueError, match="true_positive"):
            _basic_measurement(true_positive=True)

    def test_int_rates_coerced_via_float(self):
        # accuracy=1 should be accepted as 1.0
        m = _basic_measurement(
            pair_count=10,
            true_positive=5, true_negative=5,
            false_positive=0, false_negative=0,
            accuracy=1, false_positive_rate=0, false_negative_rate=0,
        )
        assert m.accuracy == 1

    def test_boundary_values_accepted(self):
        m = _basic_measurement(
            pair_count=10,
            true_positive=10, true_negative=0,
            false_positive=0, false_negative=0,
            accuracy=1.0, false_positive_rate=0.0, false_negative_rate=0.0,
        )
        assert m.accuracy == 1.0

    def test_frozen_dataclass(self):
        m = _basic_measurement()
        with pytest.raises(Exception):
            m.pair_count = 999


# ---------------------------------------------------------------------------
# _load_corpus_file
# ---------------------------------------------------------------------------


class TestLoadCorpusFile:
    """Pin the loader's refuse-loud surfaces per ADR-0044 D222 + D226."""

    def test_unknown_claim_type_refuses(self, tmp_path):
        with pytest.raises(ValueError, match="claim_type"):
            draft_quality._load_corpus_file(tmp_path, "not-a-type")

    def test_missing_corpus_file_refuses(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="corpus file not found"):
            draft_quality._load_corpus_file(tmp_path, "named_entity")

    def test_malformed_yaml_propagates(self, tmp_path):
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "named_entity.yml").write_text("not: a: valid: yaml: ::::")
        with pytest.raises(yaml.YAMLError):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_non_dict_top_level_refuses(self, tmp_path):
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "named_entity.yml").write_text("- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="parse as a dict"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_mismatched_claim_type_field_refuses(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path, claim_type="named_entity")
        # Rewrite with mismatched claim_type field.
        (corpus_dir / "named_entity.yml").write_text(yaml.safe_dump({
            "version": 1,
            "claim_type": "you_phrase",  # mismatch
            "register": "cold-pitch",
            "channel": "email",
            "pairs": [{"id": "x", "draft": "d", "dossier": "x", "expected_state": "ready"}],
        }))
        with pytest.raises(ValueError, match="claim_type field"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_unknown_register_refuses(self, tmp_path):
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "named_entity.yml").write_text(yaml.safe_dump({
            "version": 1,
            "claim_type": "named_entity",
            "register": "not-a-register",
            "channel": "email",
            "pairs": [{"id": "x", "draft": "d", "dossier": "x", "expected_state": "ready"}],
        }))
        with pytest.raises(ValueError, match="register"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_unknown_channel_refuses(self, tmp_path):
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "named_entity.yml").write_text(yaml.safe_dump({
            "version": 1,
            "claim_type": "named_entity",
            "register": "cold-pitch",
            "channel": "not-a-channel",
            "pairs": [{"id": "x", "draft": "d", "dossier": "x", "expected_state": "ready"}],
        }))
        with pytest.raises(ValueError, match="channel"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_empty_pairs_refuses(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=[])
        with pytest.raises(ValueError, match="pairs must be a non-empty list"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_pair_missing_required_field_refuses(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=[
            {"id": "x", "draft": "d", "dossier": "x"},  # missing expected_state
        ])
        with pytest.raises(ValueError, match="missing required field"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_duplicate_pair_ids_refuses(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=[
            {"id": "dup", "draft": "d1", "dossier": "x1", "expected_state": "ready"},
            {"id": "dup", "draft": "d2", "dossier": "x2", "expected_state": "refused"},
        ])
        with pytest.raises(ValueError, match="duplicate pair id"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_pair_with_unknown_expected_state_refuses(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=[
            {"id": "x", "draft": "d", "dossier": "x", "expected_state": "not-a-state"},
        ])
        with pytest.raises(ValueError, match="expected_state"):
            draft_quality._load_corpus_file(corpus_dir, "named_entity")

    def test_load_returns_typed_pairs(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        data = draft_quality._load_corpus_file(corpus_dir, "named_entity")
        assert "pairs_typed" in data
        assert isinstance(data["pairs_typed"], tuple)
        assert all(isinstance(p, CorpusPair) for p in data["pairs_typed"])


# ---------------------------------------------------------------------------
# measure_per_claim_type_false_positive_rate
# ---------------------------------------------------------------------------


class TestMeasurePerClaimTypeFalsePositiveRate:
    """Pin the measurement primitive's behavior per ADR-0044 D223."""

    def test_unknown_claim_type_refuses(self, tmp_path):
        with pytest.raises(ValueError, match="claim_type"):
            measure_per_claim_type_false_positive_rate(tmp_path, "not-a-type")

    def test_missing_corpus_dir_refuses(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            measure_per_claim_type_false_positive_rate(
                tmp_path, "named_entity",
            )

    def test_returns_corpus_measurement(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert isinstance(m, CorpusMeasurement)

    def test_measurement_carries_register_and_channel(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(
            tmp_path, register="congrats", channel="linkedin-dm",
        )
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert m.register == "congrats"
        assert m.channel == "linkedin-dm"

    def test_measurement_carries_claim_type(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path, claim_type="date_reference")
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "date_reference",
            thresholds_path=thresholds_path,
        )
        assert m.claim_type == "date_reference"

    def test_tallies_sum_to_pair_count(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert (
            m.true_positive + m.true_negative
            + m.false_positive + m.false_negative
        ) == m.pair_count

    def test_pair_count_matches_corpus_pair_count(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert m.pair_count == 2  # default synthetic corpus has 2 pairs

    def test_accuracy_in_range(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert 0.0 <= m.accuracy <= 1.0

    def test_rates_in_range(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert 0.0 <= m.false_positive_rate <= 1.0
        assert 0.0 <= m.false_negative_rate <= 1.0

    def test_all_refused_corpus_gives_only_tp_or_fn(self, tmp_path):
        """A corpus with only expected_state=refused pairs has TN=FP=0."""
        pairs = [
            {
                "id": f"r-{i:03d}",
                "draft": "Saw what Acme Corp shipped.",
                "dossier": "No company mentions.",
                "expected_state": "refused",
            } for i in range(5)
        ]
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=pairs)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert m.true_negative == 0
        assert m.false_positive == 0
        # All pairs are refused-labeled → fall in TP or FN buckets.
        assert m.true_positive + m.false_negative == m.pair_count

    def test_all_ready_corpus_gives_only_tn_or_fp(self, tmp_path):
        """A corpus with only expected_state=ready pairs has TP=FN=0."""
        pairs = [
            {
                "id": f"a-{i:03d}",
                # Empty-draft-ish: no claims extracted → state=ready
                "draft": "Hello.",
                "dossier": "Generic dossier.",
                "expected_state": "ready",
            } for i in range(5)
        ]
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=pairs)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert m.true_positive == 0
        assert m.false_negative == 0
        # All pairs are ready-labeled → fall in TN or FP buckets.
        assert m.true_negative + m.false_positive == m.pair_count

    def test_fp_cell_of_measurement_primitive(self, tmp_path):
        """Targeted unit test for the FP branch of the outcome partition.

        Per Week 7 follow-up P2-1 — the existing
        ``test_all_ready_corpus_gives_only_tn_or_fp`` test is
        structurally vacuous for the FP cell (uses ``draft="Hello."``
        which produces zero extracted claims → state=ready → TN cell
        only; FP=0 by corpus construction, not by primitive logic).
        This test exercises the FP branch directly: a draft where
        the parser flags an uncited claim (state="refused") paired
        with ``expected_state="ready"`` (operator judgment that the
        dossier substantively supports the claim though no verbatim
        match exists). FP cell: parser=refused, corpus=ready.
        """
        pairs = [
            {
                "id": "fp-001",
                "draft": "Excited by what Acme Corp is shipping.",
                "dossier": "Generic industry overview.",
                "expected_state": "ready",
            },
        ]
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=pairs)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert m.false_positive == 1, (
            "FP branch must increment when parser=refused + corpus=ready"
        )
        assert m.true_positive == 0
        assert m.true_negative == 0
        assert m.false_negative == 0
        assert m.pair_count == 1

    def test_fn_cell_of_measurement_primitive(self, tmp_path):
        """Targeted unit test for the FN branch of the outcome partition.

        Per Week 7 follow-up P2-1 — the existing
        ``test_all_refused_corpus_gives_only_tp_or_fn`` test is
        structurally vacuous for the FN cell (uses ``draft="Saw what
        Acme Corp shipped."`` which produces a named_entity claim →
        state=refused → TP cell only; FN=0 by corpus construction,
        not by primitive logic). This test exercises the FN branch
        directly: a draft where the parser surfaces no claim (state=
        "ready") paired with ``expected_state="refused"`` (operator
        judgment that an implicit claim exists). FN cell: parser=
        ready, corpus=refused. The FN cell is the LOAD-BEARING
        brand-risk path per ADR-0038 D184.
        """
        pairs = [
            {
                "id": "fn-001",
                "draft": "Hello.",
                "dossier": "Generic dossier.",
                "expected_state": "refused",
            },
        ]
        corpus_dir = _build_synthetic_corpus(tmp_path, pairs=pairs)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            corpus_dir, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert m.false_negative == 1, (
            "FN branch must increment when parser=ready + corpus=refused"
        )
        assert m.true_positive == 0
        assert m.true_negative == 0
        assert m.false_positive == 0
        assert m.pair_count == 1

    def test_embed_fn_seam_in_signature(self):
        """TEST-ONLY embed_fn seam per ADR-0043 D218 + ADR-0044 D227."""
        import inspect
        sig = inspect.signature(measure_per_claim_type_false_positive_rate)
        assert "embed_fn" in sig.parameters
        param = sig.parameters["embed_fn"]
        assert param.default is None

    def test_embed_fn_docstring_test_only(self):
        """Per ADR-0044 D227 — the embed_fn kwarg's docstring labels it TEST-ONLY."""
        doc = measure_per_claim_type_false_positive_rate.__doc__
        assert "TEST-ONLY" in doc
        assert "embed_fn" in doc

    def test_fuzzy_threshold_in_signature(self):
        """Per ADR-0046 D236 follow-up — the fuzzy_threshold kwarg is
        present at the measure primitive's signature + defaults to
        :data:`DEFAULT_FUZZY_CITATION_THRESHOLD`."""
        import inspect
        from draft_quality import DEFAULT_FUZZY_CITATION_THRESHOLD
        sig = inspect.signature(measure_per_claim_type_false_positive_rate)
        assert "fuzzy_threshold" in sig.parameters
        param = sig.parameters["fuzzy_threshold"]
        assert param.default == DEFAULT_FUZZY_CITATION_THRESHOLD

    def test_fuzzy_threshold_passes_through_to_score_draft(self, tmp_path):
        """Per ADR-0046 D236 follow-up — the fuzzy_threshold kwarg
        passthrough to score_draft is BEHAVIORALLY verified (mirrors
        the Week 8 P2-2 capturing-lambda discipline). A future
        refactor that drops fuzzy_threshold=fuzzy_threshold at the
        score_draft call would silently revert measure callers to
        the default threshold."""
        import numpy as np
        captured: dict = {}

        def _capture_embed(text):
            captured.setdefault("calls", 0)
            captured["calls"] += 1
            return np.zeros(384, dtype=np.float32)

        corpus_dir = _build_synthetic_corpus(
            tmp_path,
            claim_type="named_entity",
            pairs=[{
                "id": "syn-001",
                "draft": "Excited by Anthropic Inc work.",
                "dossier": "Unrelated content here.",
                "expected_state": "refused",
            }],
        )
        thresholds_path = _write_thresholds(tmp_path / "voice_thresholds.yml")
        # Pass a CUSTOM fuzzy_threshold (0.99) — must propagate.
        measure_per_claim_type_false_positive_rate(
            corpus_dir,
            "named_entity",
            thresholds_path=thresholds_path,
            embed_fn=_capture_embed,
            fuzzy_threshold=0.99,
        )
        # The embed_fn was invoked → fuzzy path activated → the
        # fuzzy_threshold kwarg propagated through score_draft + parse.
        assert captured.get("calls", 0) > 0, (
            "fuzzy_threshold passthrough through score_draft + parse "
            "did not exercise the fuzzy path; the seam may have "
            "regressed"
        )

    def test_bool_fuzzy_threshold_refuses_loud(self, tmp_path):
        """Per ADR-0046 D236 + ADR-0041 D201 follow-up — bool
        fuzzy_threshold at the measure primitive surface propagates
        the refuse-loud from parse_draft_for_claims (bool catch is
        per-call; the measure-level signature accepts the kwarg
        verbatim + lets parse_draft_for_claims's validator raise)."""
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "voice_thresholds.yml")
        with pytest.raises(ValueError, match="fuzzy_threshold"):
            measure_per_claim_type_false_positive_rate(
                corpus_dir,
                "named_entity",
                thresholds_path=thresholds_path,
                fuzzy_threshold=True,  # bool catch
            )


# ---------------------------------------------------------------------------
# Per-claim-type benchmark (the regression-barrier surface)
# ---------------------------------------------------------------------------


class TestCorpusBenchmark:
    """Per-claim-type benchmark tests per ADR-0044 D225.

    Rate bounds reflect the Week 7 empirical baseline + headroom for
    minor variations. Bounds tighten as future Pillar F weeks ship
    per-claim fuzzy-match scoring (Week 8+), per-claim severity
    weighting, + Layer 4/5 refusal extensions.

    Per ADR-0038 D180 + D184's asymmetric-failure-cost discipline,
    the FN_rate bound is the load-bearing regression-barrier (brand-
    risk path); the FP_rate bound is permissive (operator-friction
    path).
    """

    @pytest.fixture
    def thresholds_path(self, tmp_path) -> Path:
        return _write_thresholds(tmp_path / "thresholds.yml")

    @pytest.mark.parametrize("claim_type", sorted(CLAIM_TYPES))
    def test_per_claim_type_corpus_rates_within_bounds(
        self, claim_type, thresholds_path,
    ):
        """The per-claim-type regression-barrier surface."""
        m = measure_per_claim_type_false_positive_rate(
            CORPUS_DIR, claim_type,
            thresholds_path=thresholds_path,
        )
        targets = _CLAIM_TYPE_BENCHMARK_TARGETS[claim_type]
        assert m.accuracy >= targets["accuracy_min"], (
            f"{claim_type} accuracy {m.accuracy:.3f} below regression-"
            f"barrier {targets['accuracy_min']}. Per ADR-0044 D225 the "
            "Week 7 baseline targets are tightened in subsequent Pillar F "
            "weeks; a regression beyond this bound signals a parser quality "
            "loss against the operator-judgment corpus."
        )
        assert m.false_negative_rate <= targets["fn_rate_max"], (
            f"{claim_type} FN_rate {m.false_negative_rate:.3f} above "
            f"regression-barrier {targets['fn_rate_max']}. Per ADR-0038 D184 "
            "the FN path (uncited claim ships) is the brand-risk path; a "
            "FN_rate increase is the LOAD-BEARING regression to catch."
        )
        assert m.false_positive_rate <= targets["fp_rate_max"], (
            f"{claim_type} FP_rate {m.false_positive_rate:.3f} above "
            f"regression-barrier {targets['fp_rate_max']}. The FP path "
            "(operator stamps an override) is the operator-friction path."
        )

    def test_benchmark_targets_cover_all_claim_types(self):
        """The benchmark target table covers all CLAIM_TYPES (closed-set protection)."""
        assert set(_CLAIM_TYPE_BENCHMARK_TARGETS) == set(CLAIM_TYPES), (
            "_CLAIM_TYPE_BENCHMARK_TARGETS keys must match CLAIM_TYPES "
            "exactly per the closed-enum convention; missing keys would "
            "skip benchmark coverage for that claim type."
        )


# ---------------------------------------------------------------------------
# CLI measure subcommand
# ---------------------------------------------------------------------------


class TestCLIMeasure:
    """CLI ``measure`` subcommand per ADR-0044 D224."""

    def test_help_lists_measure_subcommand(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "measure", "--help"],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        assert "--corpus-dir" in proc.stdout
        assert "--claim-type" in proc.stdout

    def test_measure_emits_json(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "measure",
                "--corpus-dir", str(corpus_dir),
                "--claim-type", "named_entity",
                "--thresholds-path", str(thresholds_path),
                "--json",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0, f"stderr={proc.stderr}"
        out = json.loads(proc.stdout)
        assert out["claim_type"] == "named_entity"
        assert out["register"] == "cold-pitch"
        assert out["channel"] == "email"
        assert out["pair_count"] == 2
        for k in (
            "true_positive", "true_negative",
            "false_positive", "false_negative",
            "accuracy", "false_positive_rate", "false_negative_rate",
        ):
            assert k in out

    def test_measure_text_mode_human_readable(self, tmp_path):
        corpus_dir = _build_synthetic_corpus(tmp_path)
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "measure",
                "--corpus-dir", str(corpus_dir),
                "--claim-type", "named_entity",
                "--thresholds-path", str(thresholds_path),
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0, f"stderr={proc.stderr}"
        assert "claim_type:" in proc.stdout
        assert "accuracy:" in proc.stdout
        assert "false_positive_rate:" in proc.stdout
        assert "false_negative_rate:" in proc.stdout

    def test_measure_unknown_claim_type_refuses_loud(self, tmp_path):
        """argparse-choices enforces closed-enum BEFORE handler dispatch."""
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "measure",
                "--corpus-dir", str(tmp_path),
                "--claim-type", "not-a-type",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "invalid choice" in proc.stderr.lower()

    def test_measure_missing_corpus_dir_refuses_loud(self, tmp_path):
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "measure",
                "--corpus-dir", str(tmp_path / "nonexistent"),
                "--claim-type", "named_entity",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "corpus directory not found" in proc.stderr.lower()

    def test_measure_missing_corpus_file_refuses_loud(self, tmp_path):
        # corpus dir exists but the per-claim-type YAML is missing.
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "measure",
                "--corpus-dir", str(corpus_dir),
                "--claim-type", "named_entity",
                "--thresholds-path", str(thresholds_path),
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "corpus file not found" in proc.stderr.lower()

    def test_measure_cli_has_no_embed_fn_flag(self, tmp_path):
        """Per ADR-0044 D227 — the CLI does NOT surface --embed-fn."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "measure", "--help"],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert "--embed-fn" not in proc.stdout, (
            "Per ADR-0044 D227 the TEST-ONLY embed_fn seam MUST NOT surface "
            "via CLI (security + audit per ADR-0039 D188-Alt3)."
        )


# ---------------------------------------------------------------------------
# Cross-cutting — module-level pins for the new Week 7 surfaces
# ---------------------------------------------------------------------------


class TestWeek7ModuleSurface:
    """Pin the Week 7 module-level public surface per ADR-0044 D220."""

    def test_corpus_pair_exported(self):
        assert hasattr(draft_quality, "CorpusPair")

    def test_corpus_measurement_exported(self):
        assert hasattr(draft_quality, "CorpusMeasurement")

    def test_measure_function_exported(self):
        assert hasattr(draft_quality, "measure_per_claim_type_false_positive_rate")

    def test_module_docstring_mentions_week_7(self):
        assert "Week 7" in draft_quality.__doc__


# ---------------------------------------------------------------------------
# Week 11 — corpus revision (paraphrased-ready pairs + bound tightening)
# ---------------------------------------------------------------------------


class TestCorpusBenchmarkFuzzyWin:
    """Pin fuzzy match's WIN cell per ADR-0048 D258.

    These tests exercise the per-claim-type fuzzy-match WIN cell at
    the test level (separate from the corpus YAML). The WIN cell is
    when the deterministic-first path returns None (claim text is
    not a substring of the dossier) AND the fuzzy fallback correctly
    cites at the framework default threshold 0.85 per ADR-0046 D239.

    Per the cell-level matrix coverage discipline (carried forward
    from Weeks 6-10) — for every primitive's outcome partition,
    each cell has a targeted unit test. The WIN cell across the
    three fuzzy-active claim types per ADR-0046 D240
    (date_reference + named_entity + dated_event) is the
    Week 11-pinned regression-barrier surface.
    """

    @pytest.fixture
    def thresholds_path(self, tmp_path) -> Path:
        return _write_thresholds(tmp_path / "thresholds.yml")

    def test_named_entity_fuzzy_win_at_threshold(self, thresholds_path):
        """A paraphrased-ready named_entity pair: parser deterministic
        misses (claim text not substring) → fuzzy correctly cites at
        cosine >= 0.85. Pinned at the canonical pair nent-r-p-001
        per ADR-0048 D255 — comma-break paraphrase pattern (verified
        cosine 0.859 at Week 11 commit time)."""
        from draft_quality import score_draft
        draft = "Saw what Acme Robotics Inc is shipping."
        dossier = "Acme Robotics, Inc. is announcing their plans. https://acme.example.com"
        result = score_draft(
            draft, dossier,
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
        )
        # The fuzzy match correctly cites the paraphrased dossier.
        assert result.state == "ready", (
            f"Fuzzy match WIN regression on named_entity paraphrase: "
            f"state={result.state}, uncited={result.uncited_claims}. "
            "Per ADR-0046 D239 the cosine threshold 0.85 + the comma-"
            "break paraphrase 'Acme Robotics Inc' vs 'Acme Robotics, "
            "Inc.' should produce a fuzzy-citation."
        )

    def test_dated_event_fuzzy_win_at_threshold(self, thresholds_path):
        """A paraphrased-ready dated_event pair: bare-month + event +
        word-order shift → fuzzy correctly cites at cosine >= 0.85.
        Pinned at the canonical pair devt-r-p-001 per ADR-0048 D255
        (verified cosine 0.876 at Week 11 commit time)."""
        from draft_quality import score_draft
        draft = "Following up on the March launch."
        dossier = "The launch took place in early March. https://example.com/march-launch"
        result = score_draft(
            draft, dossier,
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
        )
        assert result.state == "ready", (
            f"Fuzzy match WIN regression on dated_event paraphrase: "
            f"state={result.state}, uncited={result.uncited_claims}. "
            "Per ADR-0046 D239 the cosine threshold 0.85 + the bare-"
            "month + event word-order shift 'March launch' vs 'launch "
            "in early March' should produce a fuzzy-citation."
        )

    def test_date_reference_empirical_no_fuzzy_win_at_threshold(
        self, thresholds_path,
    ):
        """Empirical finding at Week 11 commit time per ADR-0048 D254:
        the framework default encoder (BAAI/bge-small-en-v1.5) does
        NOT reliably reach cosine >= 0.85 on date paraphrases like
        'April 2026' vs 'April of 2026' (empirical 0.698 at Week 11
        commit time). This test documents the empirical calibration
        finding so a future encoder swap that DOES bridge this
        paraphrase pattern would surface as a test update + ADR
        amendment.
        """
        from draft_quality import score_draft
        draft = "Excited by your April 2026 launch."
        dossier = "April of 2026 launch details. https://example.com/april-launch"
        result = score_draft(
            draft, dossier,
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
        )
        # Per ADR-0048 D254: date paraphrases empirically do NOT
        # reach 0.85 with the framework default encoder. Parser
        # refuses (uncited). If this assertion fires (state=ready),
        # the encoder behavior has shifted + ADR-0048 D254 needs
        # amendment + bound table needs recalibration.
        assert result.state == "refused", (
            "Expected date paraphrase to NOT hit fuzzy at threshold "
            "0.85 per ADR-0048 D254's empirical calibration finding. "
            "If this fires (state=ready), the encoder behavior has "
            "improved: amend ADR-0048 D254 + recalibrate the "
            "date_reference bounds + add date_reference paraphrased-"
            "ready pairs to the corpus."
        )

    def test_fuzzy_win_pinned_at_threshold_85(self):
        """Per ADR-0046 D239 the framework default fuzzy threshold is
        0.85. This test pins the constant so a future change to the
        constant (e.g., dropping to 0.70 to catch date paraphrases at
        the cost of negation-prose FP regression per ADR-0046 D239's
        calibration history) surfaces explicitly."""
        from draft_quality import DEFAULT_FUZZY_CITATION_THRESHOLD
        assert DEFAULT_FUZZY_CITATION_THRESHOLD == 0.85, (
            "Per ADR-0046 D239 the framework default fuzzy threshold "
            "MUST stay at 0.85. The Week 11 corpus revision per "
            "ADR-0048 was calibrated against this threshold; a change "
            "requires re-running the per-claim-type benchmark + "
            "updating the bound table at _CLAIM_TYPE_BENCHMARK_TARGETS."
        )


class TestCorpusBenchmarkExclusion:
    """Pin the structural exclusion per ADR-0048 D257.

    The you_phrase + quoted_text corpora are UNCHANGED at Week 11
    per ADR-0046 D240's attribution-claim exclusion. Adding
    paraphrased-ready pairs to these corpora would VIOLATE D240's
    structural commitment (the fuzzy path skips you_phrase +
    quoted_text claims; paraphrased-ready pairs would generate FN
    cells against the parser's attribution-preserving behavior).
    """

    def test_you_phrase_corpus_unchanged_at_week_11(self):
        """Per ADR-0048 D257 — no paraphrased-ready pairs in you_phrase."""
        data = yaml.safe_load((CORPUS_DIR / "you_phrase.yml").read_text())
        pair_ids = [p["id"] for p in data["pairs"]]
        # Pin the W7 baseline pair count (30 = 15 ready + 15 refused).
        assert len(pair_ids) == 30, (
            f"you_phrase corpus pair count drifted from W7 baseline (30) "
            f"to {len(pair_ids)}. Per ADR-0048 D257 + ADR-0046 D240's "
            "attribution-claim exclusion, this corpus MUST NOT grow at "
            "Week 11. If a future Pillar F week extends, that is an ADR "
            "amendment of ADR-0046 D240."
        )
        # Pin that no paraphrased ids exist.
        p_ids = [pid for pid in pair_ids if "-p-" in pid]
        assert p_ids == [], (
            f"you_phrase corpus has paraphrased pair ids: {p_ids!r}. Per "
            "ADR-0046 D240, the you_phrase fuzzy path is excluded; "
            "paraphrased-ready pairs in this corpus would violate the "
            "attribution-claim exclusion's structural commitment."
        )

    def test_quoted_text_corpus_unchanged_at_week_11(self):
        """Per ADR-0048 D257 — no paraphrased-ready pairs in quoted_text."""
        data = yaml.safe_load((CORPUS_DIR / "quoted_text.yml").read_text())
        pair_ids = [p["id"] for p in data["pairs"]]
        assert len(pair_ids) == 30, (
            f"quoted_text corpus pair count drifted from W7 baseline (30) "
            f"to {len(pair_ids)}. Per ADR-0048 D257 + ADR-0046 D240's "
            "verbatim-only invariant for quoted_text (per ADR-0043 D214), "
            "this corpus MUST NOT grow at Week 11."
        )
        p_ids = [pid for pid in pair_ids if "-p-" in pid]
        assert p_ids == [], (
            f"quoted_text corpus has paraphrased pair ids: {p_ids!r}. Per "
            "ADR-0043 D214 + ADR-0046 D240, the quoted_text fuzzy path "
            "is excluded; paraphrased quotes are structurally a "
            "misattribution per the verbatim-only invariant."
        )

    def test_date_reference_corpus_unchanged_at_week_11(self):
        """Per ADR-0048 D254 — no paraphrased-ready pairs in date_reference.

        Empirical finding: the framework default encoder does NOT
        reliably reach cosine >= 0.85 on date paraphrases. The
        date_reference corpus stays at the W7 baseline at Week 11;
        future Pillar F weeks MAY extend when calibration story
        matures.
        """
        data = yaml.safe_load((CORPUS_DIR / "date_reference.yml").read_text())
        pair_ids = [p["id"] for p in data["pairs"]]
        assert len(pair_ids) == 30, (
            f"date_reference corpus pair count drifted from W7 baseline "
            f"(30) to {len(pair_ids)}. Per ADR-0048 D254 the W11 "
            "extension excludes date_reference (empirical encoder "
            "calibration finding); a future extension is an ADR amendment."
        )
        p_ids = [pid for pid in pair_ids if "-p-" in pid]
        assert p_ids == [], (
            f"date_reference corpus has paraphrased pair ids: {p_ids!r}. "
            "Per ADR-0048 D254 the W11 extension excludes date_reference "
            "(empirical calibration finding at Week 11 commit time)."
        )


class TestWeek11CorpusExtension:
    """Pin the Week 11 corpus extension invariants per ADR-0048 D259."""

    def test_named_entity_corpus_grew_at_week_11(self):
        """Per ADR-0048 D253 — named_entity corpus has +7 paraphrased-ready pairs."""
        data = yaml.safe_load((CORPUS_DIR / "named_entity.yml").read_text())
        pair_ids = [p["id"] for p in data["pairs"]]
        # W7 baseline 30 + W11 extension 7 = 37.
        assert len(pair_ids) == 37, (
            f"named_entity pair count {len(pair_ids)} != 37 (W7 baseline "
            "30 + W11 extension 7). If this changes, update ADR-0048 D253 "
            "+ the bound table at _CLAIM_TYPE_BENCHMARK_TARGETS."
        )
        # Verify paraphrased pair ids follow the -p- convention.
        paraphrased_ids = sorted(pid for pid in pair_ids if "-p-" in pid)
        assert paraphrased_ids == [
            "nent-r-p-001", "nent-r-p-002", "nent-r-p-003", "nent-r-p-004",
            "nent-r-p-005", "nent-r-p-006", "nent-r-p-007",
        ], (
            f"named_entity paraphrased pair ids drifted: {paraphrased_ids!r}. "
            "Per ADR-0048 D255 the convention is nent-r-p-NNN."
        )

    def test_dated_event_corpus_grew_at_week_11(self):
        """Per ADR-0048 D253 — dated_event corpus has +5 paraphrased-ready pairs."""
        data = yaml.safe_load((CORPUS_DIR / "dated_event.yml").read_text())
        pair_ids = [p["id"] for p in data["pairs"]]
        assert len(pair_ids) == 35, (
            f"dated_event pair count {len(pair_ids)} != 35 (W7 baseline 30 "
            "+ W11 extension 5)."
        )
        paraphrased_ids = sorted(pid for pid in pair_ids if "-p-" in pid)
        assert paraphrased_ids == [
            "devt-r-p-001", "devt-r-p-002", "devt-r-p-003",
            "devt-r-p-004", "devt-r-p-005",
        ], (
            f"dated_event paraphrased pair ids drifted: {paraphrased_ids!r}. "
            "Per ADR-0048 D255 the convention is devt-r-p-NNN."
        )

    def test_paraphrased_pairs_are_ready_labeled(self):
        """Per ADR-0048 D255 — all paraphrased pairs use expected_state=ready.

        The Week 11 extension's structural commitment is paraphrased-
        READY pairs (exercising fuzzy's WIN cell, growing the TN
        denominator of FP_rate). Paraphrased-refused pairs would
        grow the FN cell + be a separate Pillar F design decision.
        """
        for ct in ("named_entity", "dated_event"):
            data = yaml.safe_load((CORPUS_DIR / f"{ct}.yml").read_text())
            for p in data["pairs"]:
                if "-p-" in p["id"]:
                    assert p["expected_state"] == "ready", (
                        f"{ct} paraphrased pair {p['id']} has "
                        f"expected_state={p['expected_state']!r}; per "
                        "ADR-0048 D255 paraphrased pairs are ready-labeled."
                    )

    def test_paraphrased_pairs_have_nearby_url(self):
        """Per ADR-0048 D255 — each paraphrased pair's dossier has a URL
        within the chunk (operator-readable anchor for fuzzy citation).
        """
        url_re_str = "https?://"
        import re as _re
        url_re = _re.compile(url_re_str)
        for ct in ("named_entity", "dated_event"):
            data = yaml.safe_load((CORPUS_DIR / f"{ct}.yml").read_text())
            for p in data["pairs"]:
                if "-p-" in p["id"]:
                    assert url_re.search(p["dossier"]), (
                        f"{ct} paraphrased pair {p['id']} dossier has no URL: "
                        f"{p['dossier']!r}. Per ADR-0048 D255 each pair's "
                        "dossier MUST include a URL within the chunk for "
                        "the fuzzy citation_anchor surfacing."
                    )

    def test_named_entity_post_extension_meets_tightened_bounds(self, tmp_path):
        """Per ADR-0048 D256 — named_entity meets tightened bounds.

        Empirical at Week 11 commit time: accuracy 0.784, FP_rate
        0.000, FN_rate 0.533. Tightened bounds: accuracy_min 0.70
        (was 0.55), FP_rate_max 0.10 (was 0.20), FN_rate_max 0.65
        (unchanged). This test asserts the tightened bounds hold —
        a regression that drops below the bound surfaces here.
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            CORPUS_DIR, "named_entity",
            thresholds_path=thresholds_path,
        )
        assert m.pair_count == 37  # W7 30 + W11 7
        assert m.accuracy >= 0.70, (
            f"named_entity accuracy {m.accuracy:.3f} below tightened W11 "
            "bound 0.70 per ADR-0048 D256."
        )
        assert m.false_positive_rate <= 0.10, (
            f"named_entity FP_rate {m.false_positive_rate:.3f} above "
            "tightened W11 bound 0.10 per ADR-0048 D256."
        )

    def test_dated_event_post_extension_meets_tightened_bounds(self, tmp_path):
        """Per ADR-0048 D256 — dated_event meets tightened bounds.

        Per Week 11 follow-up P2-2 — devt-r-p-003 redesigned from
        the original "Loved the Q3 2026 announcement." (which
        generated a cross-claim `date_reference: "Q3 2026"` that
        fuzzy-missed at 0.85 per D254) to "Loved the August launch."
        (bare month substring-matches dossier; dated_event word-
        order shift fuzzy-hits). Empirical at Week 11 follow-up:
        accuracy 0.829, FP_rate 0.000, FN_rate 0.400. Tightened
        bounds: accuracy_min 0.70, FP_rate_max 0.10 (was 0.15 in
        foundation commit), FN_rate_max 0.55 (unchanged).
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            CORPUS_DIR, "dated_event",
            thresholds_path=thresholds_path,
        )
        assert m.pair_count == 35  # W7 30 + W11 5
        assert m.accuracy >= 0.70, (
            f"dated_event accuracy {m.accuracy:.3f} below tightened W11 "
            "bound 0.70 per ADR-0048 D256."
        )
        assert m.false_positive_rate <= 0.10, (
            f"dated_event FP_rate {m.false_positive_rate:.3f} above "
            "tightened W11 bound 0.10 per ADR-0048 D256 + Week 11 "
            "follow-up P2-2 (devt-r-p-003 redesigned to avoid cross-"
            "claim cascade)."
        )

    def test_excluded_corpora_baseline_preserved_at_week_11(self, tmp_path):
        """Per ADR-0048 D257 — you_phrase + quoted_text baseline preserved.

        These two corpora are UNCHANGED at Week 11; the W7 baseline
        rates (accuracy 1.0; FP_rate 0.0; FN_rate 0.0) preserve verbatim.
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        for ct in ("you_phrase", "quoted_text"):
            m = measure_per_claim_type_false_positive_rate(
                CORPUS_DIR, ct,
                thresholds_path=thresholds_path,
            )
            assert m.pair_count == 30, f"{ct} pair_count={m.pair_count} != 30"
            assert m.accuracy == 1.0, (
                f"{ct} accuracy {m.accuracy:.3f} != 1.0; W7 baseline "
                "must be preserved at Week 11 per ADR-0048 D257."
            )
            assert m.false_positive_rate == 0.0
            assert m.false_negative_rate == 0.0

    def test_date_reference_corpus_baseline_preserved_at_week_11(self, tmp_path):
        """Per ADR-0048 D254 — date_reference UNCHANGED at Week 11.

        Empirical at Week 11 commit time matches Week 7+9 baseline:
        accuracy 0.733, FP_rate 0.267, FN_rate 0.267. No paraphrased-
        ready pairs added per the empirical encoder calibration
        finding.
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        m = measure_per_claim_type_false_positive_rate(
            CORPUS_DIR, "date_reference",
            thresholds_path=thresholds_path,
        )
        assert m.pair_count == 30, f"date_reference pair_count={m.pair_count} != 30"


class TestWeek11ModuleSurface:
    """Pin the Week 11 corpus-revision invariants per ADR-0048."""

    def test_named_entity_bound_table_matches_adr_0048(self):
        """Per ADR-0048 D256 — named_entity bound tightening pinned."""
        assert _CLAIM_TYPE_BENCHMARK_TARGETS["named_entity"] == {
            "fp_rate_max": 0.10, "fn_rate_max": 0.65, "accuracy_min": 0.70,
        }, (
            "named_entity bound table drifted from ADR-0048 D256. The "
            "Week 11 commit's bound table must match the empirically-"
            "calibrated post-extension rates with 5-10pp headroom."
        )

    def test_dated_event_bound_table_matches_adr_0048(self):
        """Per ADR-0048 D256 + Week 11 follow-up P2-2 — dated_event bound
        tightening pinned at 0.10 (was 0.15 in foundation commit; tightened
        further after devt-r-p-003 redesign avoided cross-claim cascade)."""
        assert _CLAIM_TYPE_BENCHMARK_TARGETS["dated_event"] == {
            "fp_rate_max": 0.10, "fn_rate_max": 0.55, "accuracy_min": 0.70,
        }, (
            "dated_event bound table drifted from ADR-0048 D256 + Week 11 "
            "follow-up P2-2 calibration."
        )

    def test_excluded_bounds_preserved_at_week_11(self):
        """Per ADR-0048 D257 — you_phrase + quoted_text bounds UNCHANGED."""
        assert _CLAIM_TYPE_BENCHMARK_TARGETS["you_phrase"] == {
            "fp_rate_max": 0.20, "fn_rate_max": 0.20, "accuracy_min": 0.85,
        }
        assert _CLAIM_TYPE_BENCHMARK_TARGETS["quoted_text"] == {
            "fp_rate_max": 0.20, "fn_rate_max": 0.20, "accuracy_min": 0.85,
        }

    def test_date_reference_bound_unchanged_at_week_11(self):
        """Per ADR-0048 D254 — date_reference bounds UNCHANGED."""
        assert _CLAIM_TYPE_BENCHMARK_TARGETS["date_reference"] == {
            "fp_rate_max": 0.40, "fn_rate_max": 0.40, "accuracy_min": 0.60,
        }

    def test_fn_rate_max_unchanged_for_all_claim_types_at_week_11(self):
        """Per ADR-0048 D256 — FN_rate_max bounds preserved verbatim at W11.

        Paraphrased-ready pairs grow the TN denominator only; the FN
        cells (corpus=refused) are NOT touched at Week 11. The
        FN_rate denominator stays at the W7 baseline; the FN_rate_max
        bounds therefore stay UNCHANGED for all five claim types.
        """
        # W7 baseline FN_rate_max values per ADR-0044 D225.
        w7_fn_rate_max = {
            "date_reference":  0.40,
            "named_entity":    0.65,
            "you_phrase":      0.20,
            "quoted_text":     0.20,
            "dated_event":     0.55,
        }
        for ct, expected in w7_fn_rate_max.items():
            assert _CLAIM_TYPE_BENCHMARK_TARGETS[ct]["fn_rate_max"] == expected, (
                f"{ct} fn_rate_max drifted from W7 baseline at Week 11. "
                "Per ADR-0048 D256 the FN_rate_max bounds preserve verbatim."
            )

    def test_module_docstring_mentions_week_11(self):
        """Per Week 11 follow-up P3-1 — module-level docstring updated to
        name Week 11 corpus revision.

        The Week 11 ship is corpus-revision scope (ZERO new module
        surfaces per ADR-0048 D261), but the bound table at
        ``_CLAIM_TYPE_BENCHMARK_TARGETS`` tightened for ``named_entity``
        + ``dated_event``; the module docstring should mention Week 11
        + ADR-0048 even though no module surface changes. Same doc-
        drift pattern as Week 8 P3-3 (module-level TEST-ONLY embed_fn
        docstring frozen at Week 6) and Week 9 P3-1 (module docstring
        frozen at Week 8) — fixed at the follow-up commit.
        """
        assert "Week 11" in draft_quality.__doc__, (
            "Module docstring at orchestrator/draft_quality.py:1 MUST "
            "mention Week 11 per Week 11 follow-up P3-1 (corpus-revision "
            "scope; bound table tightened)."
        )
        assert "ADR-0048" in draft_quality.__doc__, (
            "Module docstring MUST reference ADR-0048 per Week 11 "
            "follow-up P3-1."
        )


# ---------------------------------------------------------------------------
# Week 11 follow-up — per-pair behavioral coverage (per Week 11 P2-1 + P2-2)
# ---------------------------------------------------------------------------


def _paraphrased_pairs_for(claim_type: str) -> list[dict]:
    """Load the paraphrased-ready pairs (`-p-` ids) for a claim type."""
    data = yaml.safe_load((CORPUS_DIR / f"{claim_type}.yml").read_text())
    return [p for p in data["pairs"] if "-p-" in p["id"]]


class TestParaphrasedPairsBehavioralPerPair:
    """Per Week 11 follow-up P2-1 + P2-2 — per-pair behavioral pin.

    The Week 11 commit's TestCorpusBenchmarkFuzzyWin pinned ONE
    canonical pair per claim type (nent-r-p-001 + devt-r-p-001) +
    used INLINE draft/dossier text. The OTHER 10 paraphrased pairs
    (nent-r-p-002 through -007, devt-r-p-002 through -005) had their
    behavioral-correctness asserted only via the corpus-aggregate
    FP_rate bound (which has 10pp headroom and masks 1-3 per-pair
    regressions).

    Per the "behavioral-passthrough-not-signature-only" discipline
    carried forward across THREE consecutive weeks (W8 P2-2 + W9
    P2-2 + W10 P2-1), the notes-field cosine declarations are
    documentation-only commitments; this test class converts each
    paraphrased pair into an INDIVIDUAL regression barrier so a
    YAML edit that drops one pair's cosine below 0.85 fires the
    pair's specific test row, not just the aggregate.

    Per Week 11 follow-up P2-1 — the ADR-0048 D255 per-pair
    invariant #3 ("dossier MUST NOT contain claim text as case-
    insensitive substring") is verified at the per-pair scope here.
    A future YAML edit that inlines the claim text verbatim
    (silently shifting the pair from fuzzy-WIN to deterministic-
    match) is caught at the per-pair test row.
    """

    @pytest.fixture
    def thresholds_path(self, tmp_path) -> Path:
        return _write_thresholds(tmp_path / "thresholds.yml")

    @pytest.mark.parametrize(
        "pair",
        _paraphrased_pairs_for("named_entity"),
        ids=lambda p: p["id"],
    )
    def test_named_entity_paraphrased_pair_hits_fuzzy(self, pair, thresholds_path):
        """Each named_entity paraphrased pair empirically cites via fuzzy
        per ADR-0048 D255 invariant #5 (cosine >= 0.85)."""
        from draft_quality import score_draft
        result = score_draft(
            pair["draft"], pair["dossier"],
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
        )
        assert result.state == "ready", (
            f"Paraphrased-ready pair {pair['id']!r} regressed: state="
            f"{result.state!r}, uncited={result.uncited_claims}. Per ADR-"
            "0048 D255 invariant #5 each pair empirically verified cosine "
            ">= 0.85 at Week 11 commit time; a regression on this pair "
            "drops below the threshold AND silently inflates corpus-"
            "aggregate FP_rate. Per-pair behavioral coverage per Week 11 "
            "follow-up P2-2."
        )

    @pytest.mark.parametrize(
        "pair",
        _paraphrased_pairs_for("dated_event"),
        ids=lambda p: p["id"],
    )
    def test_dated_event_paraphrased_pair_hits_fuzzy(self, pair, thresholds_path):
        """Each dated_event paraphrased pair empirically cites via fuzzy.

        Per Week 11 follow-up P2-2 — all 5 dated_event paraphrased
        pairs (post devt-r-p-003 redesign to avoid cross-claim
        cascade) reach state="ready" at Week 11 commit time. The
        original devt-r-p-003 ("Loved the Q3 2026 announcement.")
        generated a cross-claim `date_reference: "Q3 2026"` that
        fuzzy-missed at 0.85; the redesigned "Loved the August
        launch." uses bare-month date_reference (substring matches
        dossier verbatim) + dated_event word-order shift (fuzzy
        hits) so no cross-claim cascade.
        """
        from draft_quality import score_draft
        result = score_draft(
            pair["draft"], pair["dossier"],
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
        )
        assert result.state == "ready", (
            f"Paraphrased-ready pair {pair['id']!r} regressed: state="
            f"{result.state!r}, uncited={result.uncited_claims}. Per "
            "ADR-0048 D255 invariant #5 each pair empirically verified "
            "cosine >= 0.85 at Week 11 commit time; per Week 11 follow-"
            "up P2-2 all 5 dated_event paraphrased pairs reach state="
            "ready post devt-r-p-003 redesign."
        )

    def test_paraphrased_pairs_dossier_does_not_contain_claim_substring(self):
        """Per Week 11 follow-up P2-1 — invariant #3 enforcement.

        ADR-0048 D255 invariant #3: each paraphrased pair's dossier
        MUST NOT contain the parser-extracted claim text as a case-
        insensitive substring (otherwise deterministic-first path
        catches → fuzzy is NOT exercised → the pair is no longer a
        fuzzy-WIN regression-barrier). Without this test, a future
        YAML edit that inlines the claim text would silently shift
        the pair from fuzzy-WIN cell to deterministic-match cell;
        the corpus-aggregate FP_rate would still pass, but the
        paraphrased pair would no longer test what it claims to test.
        """
        from draft_quality import parse_draft_for_claims
        for claim_type in ("named_entity", "dated_event"):
            for pair in _paraphrased_pairs_for(claim_type):
                # Extract the parser's claim from the draft (no
                # dossier-side cross-reference; just the extraction).
                claims = parse_draft_for_claims(
                    pair["draft"], "irrelevant dossier",
                    register="cold-pitch",
                )
                matching = [c for c in claims if c.claim_type == claim_type]
                assert matching, (
                    f"Pair {pair['id']!r} draft does not extract a "
                    f"{claim_type} claim. Per ADR-0048 D255 invariant #1, "
                    "the draft MUST contain a claim of the appropriate "
                    "type."
                )
                claim_lower = matching[0].claim_text.lower()
                dossier_lower = pair["dossier"].lower()
                assert claim_lower not in dossier_lower, (
                    f"Pair {pair['id']!r} dossier contains claim text "
                    f"{matching[0].claim_text!r} as case-insensitive "
                    "substring. Per ADR-0048 D255 invariant #3, "
                    "paraphrased pairs MUST NOT contain the claim text "
                    "as substring (otherwise deterministic-first path "
                    "catches → fuzzy is NOT exercised → the pair is no "
                    "longer a fuzzy-WIN regression-barrier). A YAML edit "
                    "shifted this pair from fuzzy-WIN to deterministic-"
                    "match silently."
                )


class TestCorpusBenchmarkFuzzyWinTextDriftPin:
    """Per Week 11 follow-up P3-3 — pin the inline text drift gap.

    The Week 11 commit's TestCorpusBenchmarkFuzzyWin uses INLINE
    draft/dossier text matching nent-r-p-001 + devt-r-p-001 from the
    YAML corpus. The test docstring claims "Pinned at the canonical
    pair nent-r-p-001 design", but there's no assertion that the
    inline text MATCHES the YAML pair's text. A future YAML edit
    (e.g., adds trailing period, changes URL) would silently drift
    the canonical pair away from the test's inline text; the test
    would still pass (cosine still hits) but the "canonical" claim
    becomes false.
    """

    def test_named_entity_inline_text_matches_yaml_canonical_pair(self):
        """The TestCorpusBenchmarkFuzzyWin INLINE text matches the
        nent-r-p-001 YAML pair byte-for-byte."""
        data = yaml.safe_load((CORPUS_DIR / "named_entity.yml").read_text())
        canonical = next(p for p in data["pairs"] if p["id"] == "nent-r-p-001")
        # The inline text used in
        # TestCorpusBenchmarkFuzzyWin::test_named_entity_fuzzy_win_at_threshold.
        # If THAT test's inline text drifts from this YAML, update
        # both together (or refactor to load from YAML).
        expected_draft = "Saw what Acme Robotics Inc is shipping."
        expected_dossier = "Acme Robotics, Inc. is announcing their plans. https://acme.example.com\n"
        assert canonical["draft"] == expected_draft, (
            f"nent-r-p-001 YAML draft drifted from TestCorpusBenchmarkFuzzyWin "
            f"inline text. YAML: {canonical['draft']!r}. Inline: {expected_draft!r}. "
            "Per Week 11 follow-up P3-3, update both in sync."
        )
        assert canonical["dossier"] == expected_dossier, (
            f"nent-r-p-001 YAML dossier drifted from inline text. "
            f"YAML: {canonical['dossier']!r}. Inline: {expected_dossier!r}."
        )

    def test_dated_event_inline_text_matches_yaml_canonical_pair(self):
        """The TestCorpusBenchmarkFuzzyWin INLINE text matches the
        devt-r-p-001 YAML pair byte-for-byte."""
        data = yaml.safe_load((CORPUS_DIR / "dated_event.yml").read_text())
        canonical = next(p for p in data["pairs"] if p["id"] == "devt-r-p-001")
        expected_draft = "Following up on the March launch."
        expected_dossier = "The launch took place in early March. https://example.com/march-launch\n"
        assert canonical["draft"] == expected_draft
        assert canonical["dossier"] == expected_dossier
        assert "ADR-0044" in draft_quality.__doc__
