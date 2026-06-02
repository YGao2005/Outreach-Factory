"""Unit tests for the Pillar F Week 2 voice-corpus primitive.

Per ADR-0039 (D185+) — the embedding-retrieval primitive that
REPLACES the heuristic in :mod:`voice_retrieve`. Coverage:

* :class:`VoiceExemplar` construction-time invariants per ADR-0038
  D178.
* :func:`validate_corpus_sample` schema gate per ADR-0038 D178.
* :func:`retrieve_voice_exemplars` per-call entry point per
  ADR-0038 D179 (per-register filter + per-channel filter +
  is_substantive_reply filter + deterministic-clock kwarg +
  metadata-mismatch refuse-loud).
* :data:`REGISTERS` + :data:`CHANNELS` frozen enums per ADR-0038
  D178 + ADR-0014 D33.
* :func:`build_voice_exemplar_retrieved_payload` event-shape
  factory per ADR-0038 D182 (channel-on-every-event invariant
  extension + privacy: NO raw query text in payload).
* :func:`rebuild_corpus` re-embed-and-write per ADR-0038 D179's
  metadata-sidecar mitigation for R026.
* CLI smoke tests (retrieve / validate / rebuild subcommands).

Test isolation: tests inject ``embed_fn=`` to bypass the
process-cached :class:`sentence_transformers.SentenceTransformer`
load (~1-2s per call) and use a deterministic per-test embedder.
The corpus directory is built inside ``tmp_path`` so the
operator's real corpus is never touched.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pytest
import yaml

import voice_corpus
from voice_corpus import (
    CHANNELS,
    DEFAULT_CHANNEL_FOR_COLD_PITCH,
    DEFAULT_CHANNEL_FOR_CONGRATS,
    DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT,
    DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT,
    DEFAULT_EMBED_MODEL,
    DEFAULT_TOP_K,
    DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
    DEFAULT_VOICE_THRESHOLDS_PATH,
    EMITTED_BY,
    REGISTERS,
    SCHEMA_VERSION,
    ValidationResult,
    VoiceCorpusMetadataMismatch,
    VoiceExemplar,
    build_voice_exemplar_retrieved_payload,
    get_voice_threshold_for_register,
    load_voice_thresholds,
    rebuild_corpus,
    retrieve_cold_pitch_exemplars,
    retrieve_congrats_exemplars,
    retrieve_public_comment_exemplars,
    retrieve_re_engagement_exemplars,
    retrieve_reply_exemplars,
    retrieve_voice_exemplars,
    validate_corpus_sample,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
VOICE_CORPUS_SCRIPT = REPO_ROOT / "orchestrator" / "voice_corpus.py"


# ---------------------------------------------------------------------------
# Test fixtures + helpers
# ---------------------------------------------------------------------------


def _unit_vec(values: list[float]) -> np.ndarray:
    """Return a unit-norm float32 vector for cosine-similarity convenience."""
    v = np.asarray(values, dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm == 0:
        return v
    return v / norm


def _fixed_embed_fn(vec: np.ndarray) -> Callable[[str], np.ndarray]:
    """Return an ``embed_fn`` that always returns the same vector.

    Used to make cosine similarity per-sample deterministic across
    invocations regardless of the query text.
    """
    def _embed(query: str) -> np.ndarray:
        return vec
    return _embed


def _sample(
    *,
    sid: str = "s1",
    date: str = "2025-06-15T12:00:00Z",
    body: str = "Hey there, just wanted to drop a line.",
    register: str = "cold-pitch",
    channel: str = "email",
    year: int = 2025,
    subject: str | None = None,
    to: list | None = None,
    tags: list | None = None,
    is_substantive_reply: bool | None = None,
    voice_score_baseline: float | None = None,
) -> dict:
    """Build a corpus sample dict with the canonical D178 shape."""
    s: dict = {
        "id": sid,
        "date": date,
        "body": body,
        "register": register,
        "channel": channel,
        "year": year,
    }
    if subject is not None:
        s["subject"] = subject
    if to is not None:
        s["to"] = to
    if tags is not None:
        s["tags"] = tags
    if is_substantive_reply is not None:
        s["is_substantive_reply"] = is_substantive_reply
    if voice_score_baseline is not None:
        s["voice_score_baseline"] = voice_score_baseline
    return s


def _make_corpus(
    tmp_path: Path,
    samples: list[dict],
    embeddings: np.ndarray,
    *,
    embed_model: str = DEFAULT_EMBED_MODEL,
    embed_version: str = "5.1.2",
    schema_version: int = SCHEMA_VERSION,
    corpus_count: int | None = None,
    built_at: str = "2026-05-01T00:00:00Z",
    dirname: str = "voice-corpus",
) -> Path:
    """Build a tmp corpus directory carrying ``index.json`` +
    ``embeddings.npy`` + ``metadata.json`` (per ADR-0038 D178 +
    D179)."""
    corpus_dir = tmp_path / dirname
    corpus_dir.mkdir(parents=True, exist_ok=True)
    np.save(corpus_dir / "embeddings.npy", embeddings.astype(np.float32))
    (corpus_dir / "index.json").write_text(json.dumps(samples))
    metadata = {
        "embed_model": embed_model,
        "embed_version": embed_version,
        "sentence_transformers_version": embed_version,
        "schema_version": schema_version,
        "corpus_count": (corpus_count
                         if corpus_count is not None
                         else len(samples)),
        "built_at": built_at,
    }
    (corpus_dir / "metadata.json").write_text(json.dumps(metadata))
    return corpus_dir


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Module-level constants pinned at ADR-0038 D178 + D179 + D182."""

    def test_registers_is_frozenset(self):
        assert isinstance(REGISTERS, frozenset)

    def test_registers_has_five_values_per_d178(self):
        assert REGISTERS == frozenset({
            "cold-pitch",
            "congrats",
            "re-engagement",
            "reply",
            "public-comment",
        })

    def test_channels_is_frozenset(self):
        assert isinstance(CHANNELS, frozenset)

    def test_channels_has_four_values_per_adr_0014_d33(self):
        assert CHANNELS == frozenset({
            "email",
            "linkedin-dm",
            "linkedin-comment",
            "twitter-dm",
        })

    def test_emitted_by_constant_per_adr_0010_d17(self):
        assert EMITTED_BY == "voice_corpus"

    def test_default_embed_model_per_adr_0038_d179(self):
        assert DEFAULT_EMBED_MODEL == "BAAI/bge-small-en-v1.5"

    def test_default_top_k_matches_voice_retrieve_heuristic(self):
        assert DEFAULT_TOP_K == 5

    def test_schema_version_starts_at_one_per_d179(self):
        assert SCHEMA_VERSION == 1

    def test_default_channel_for_cold_pitch_per_adr_0040_d195(self):
        """ADR-0040 D195 — per-register channel defaults pinned at
        module level matching SKILL.md register table line 341."""
        assert DEFAULT_CHANNEL_FOR_COLD_PITCH == "email"
        assert DEFAULT_CHANNEL_FOR_COLD_PITCH in CHANNELS

    def test_default_channel_for_congrats_per_adr_0040_d195(self):
        """ADR-0040 D195 — SKILL.md register table line 342."""
        assert DEFAULT_CHANNEL_FOR_CONGRATS == "linkedin-dm"
        assert DEFAULT_CHANNEL_FOR_CONGRATS in CHANNELS

    def test_default_channel_for_re_engagement_per_adr_0040_d195(self):
        """ADR-0040 D195 — SKILL.md register table line 343."""
        assert DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT == "email"
        assert DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT in CHANNELS

    def test_default_channel_for_public_comment_per_adr_0040_d195(self):
        """ADR-0040 D195 — SKILL.md register table line 345."""
        assert DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT == "linkedin-comment"
        assert DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT in CHANNELS

    def test_no_default_channel_for_reply_per_adr_0040_d195(self):
        """ADR-0040 D195 — the reply register has NO module-level
        default; its channel is operator-supplied per the SKILL.md's
        'match inbound channel' rule (line 344). The
        :func:`retrieve_reply_exemplars` adapter raises ValueError
        when channel=None."""
        assert not hasattr(voice_corpus, "DEFAULT_CHANNEL_FOR_REPLY")

    def test_default_voice_thresholds_path_per_adr_0041_d199(self):
        """ADR-0041 D199 — per-register threshold YAML path mirrors
        ADR-0035 D163's DEFAULT_TIER_WEIGHTS_PATH convention."""
        assert DEFAULT_VOICE_THRESHOLDS_PATH == (
            Path.home() / ".outreach-factory" / "voice_thresholds.yml"
        )

    def test_default_voice_threshold_per_register_has_all_registers(self):
        """ADR-0041 D200 — defaults dict carries all five registers."""
        assert set(DEFAULT_VOICE_THRESHOLD_PER_REGISTER.keys()) == REGISTERS

    def test_default_voice_threshold_per_register_values_per_adr_0038_d184a(self):
        """ADR-0038 D184(a) — per-register defaults calibrated against
        Yang's curated corpus at Pillar F Week 4 ship time."""
        assert DEFAULT_VOICE_THRESHOLD_PER_REGISTER == {
            "cold-pitch":     0.70,
            "congrats":       0.65,
            "re-engagement":  0.72,
            "reply":          0.70,
            "public-comment": 0.60,
        }

    def test_default_voice_threshold_per_register_values_in_unit_range(self):
        """ADR-0041 D201 — each threshold MUST be a float in [0.0, 1.0]."""
        for register, value in DEFAULT_VOICE_THRESHOLD_PER_REGISTER.items():
            assert isinstance(value, float), (
                f"threshold for {register!r} is {type(value).__name__}; "
                "must be float per ADR-0041 D201"
            )
            assert 0.0 <= value <= 1.0, (
                f"threshold for {register!r} = {value!r} out of range "
                "per ADR-0041 D201"
            )


# ---------------------------------------------------------------------------
# VoiceExemplar dataclass invariants
# ---------------------------------------------------------------------------


class TestVoiceExemplar:
    """Construction-time invariants per ADR-0038 D178.

    Mirrors the :class:`DiscoveryLineage.__post_init__` precedent
    per ADR-0036 D167 — refuse-loud at construction time so
    downstream consumers never see a partially-validated instance.
    """

    def test_required_fields_construct(self):
        ex = VoiceExemplar(
            id="2025-06-15-cold-pitch-dylan",
            date="2025-06-15T12:00:00Z",
            body="Hey Dylan, saw your post last week.",
            register="cold-pitch",
            channel="email",
            year=2025,
        )
        assert ex.id == "2025-06-15-cold-pitch-dylan"
        assert ex.register == "cold-pitch"
        assert ex.channel == "email"
        assert ex.year == 2025

    def test_optional_fields_default_to_none(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register="cold-pitch", channel="email", year=2025,
        )
        assert ex.subject is None
        assert ex.to is None
        assert ex.tags is None
        assert ex.is_substantive_reply is None
        assert ex.voice_score_baseline is None
        assert ex.score is None

    def test_optional_to_accepted(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register="cold-pitch", channel="email", year=2025,
            to=["dylan@example.com"],
        )
        assert ex.to == ["dylan@example.com"]

    def test_optional_subject_accepted(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register="cold-pitch", channel="email", year=2025,
            subject="hello",
        )
        assert ex.subject == "hello"

    def test_optional_tags_accepted(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register="cold-pitch", channel="email", year=2025,
            tags=["fintech", "tier-S"],
        )
        assert ex.tags == ["fintech", "tier-S"]

    def test_optional_is_substantive_reply_accepted(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register="cold-pitch", channel="email", year=2025,
            is_substantive_reply=True,
        )
        assert ex.is_substantive_reply is True

    def test_optional_voice_score_baseline_in_range_accepted(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register="cold-pitch", channel="email", year=2025,
            voice_score_baseline=0.78,
        )
        assert ex.voice_score_baseline == pytest.approx(0.78)

    def test_voice_score_baseline_out_of_range_raises(self):
        with pytest.raises(ValueError, match="voice_score_baseline"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="email", year=2025,
                voice_score_baseline=1.5,
            )

    def test_voice_score_baseline_negative_raises(self):
        with pytest.raises(ValueError, match="voice_score_baseline"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="email", year=2025,
                voice_score_baseline=-0.1,
            )

    def test_voice_score_baseline_bool_true_raises(self):
        """Per Week 2 follow-up P3-2 — bool is a Python int subclass
        + True is in [0,1] arithmetically; the validator must reject
        symmetric with the ``year`` bool-rejection invariant per
        ADR-0039 D186."""
        with pytest.raises(ValueError, match="voice_score_baseline"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="email", year=2025,
                voice_score_baseline=True,
            )

    def test_voice_score_baseline_bool_false_raises(self):
        """Per Week 2 follow-up P3-2 — same as True; False == 0
        arithmetically but is still a bool not a float."""
        with pytest.raises(ValueError, match="voice_score_baseline"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="email", year=2025,
                voice_score_baseline=False,
            )

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id"):
            VoiceExemplar(
                id="", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="email", year=2025,
            )

    def test_whitespace_id_raises(self):
        with pytest.raises(ValueError, match="id"):
            VoiceExemplar(
                id="   ", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="email", year=2025,
            )

    def test_empty_body_raises(self):
        with pytest.raises(ValueError, match="body"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="",
                register="cold-pitch", channel="email", year=2025,
            )

    def test_whitespace_body_raises(self):
        with pytest.raises(ValueError, match="body"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="   \n  ",
                register="cold-pitch", channel="email", year=2025,
            )

    def test_naive_date_raises(self):
        with pytest.raises(ValueError, match="date"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00", body="b",
                register="cold-pitch", channel="email", year=2025,
            )

    def test_iso_with_fractional_accepted(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00.123Z", body="b",
            register="cold-pitch", channel="email", year=2025,
        )
        assert ex.date == "2025-06-15T12:00:00.123Z"

    def test_iso_with_plus_offset_accepted(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00+00:00", body="b",
            register="cold-pitch", channel="email", year=2025,
        )
        assert ex.date == "2025-06-15T12:00:00+00:00"

    def test_iso_with_non_utc_offset_raises(self):
        with pytest.raises(ValueError, match="date"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00-07:00", body="b",
                register="cold-pitch", channel="email", year=2025,
            )

    def test_unknown_register_raises(self):
        with pytest.raises(ValueError, match="register"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="b",
                register="follow-up", channel="email", year=2025,
            )

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError, match="channel"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="sms", year=2025,
            )

    def test_none_register_accepted_for_legacy_corpora(self):
        """Per ADR-0038 D178 §Existing-operator seed — pre-Pillar-F
        samples lacking ``register`` are tolerated by the parser
        (the per-register filter treats ``None`` as "any register").
        Strict enforcement is in :func:`validate_corpus_sample`."""
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register=None, channel=None, year=2025,
        )
        assert ex.register is None
        assert ex.channel is None

    def test_year_must_be_int(self):
        with pytest.raises(ValueError, match="year"):
            VoiceExemplar(
                id="x", date="2025-06-15T12:00:00Z", body="b",
                register="cold-pitch", channel="email", year="2025",
            )

    def test_frozen(self):
        ex = VoiceExemplar(
            id="x", date="2025-06-15T12:00:00Z", body="b",
            register="cold-pitch", channel="email", year=2025,
        )
        with pytest.raises(Exception):
            ex.id = "y"


# ---------------------------------------------------------------------------
# validate_corpus_sample — strict gate
# ---------------------------------------------------------------------------


class TestValidateCorpusSample:
    """The strict schema validator per ADR-0038 D178.

    Mirrors :func:`discovery_lineage.parse_discovery_lineage_dict`'s
    construction-time refuse-loud pattern. Validates the canonical
    per-sample shape; surfaces every error in one pass so operators
    fix all schema violations together rather than one-at-a-time.
    """

    def test_happy_path_all_required(self):
        result = validate_corpus_sample(_sample())
        assert isinstance(result, ValidationResult)
        assert result.ok is True
        assert result.errors == []

    def test_happy_path_with_all_optionals(self):
        s = _sample(
            subject="hey",
            to=["x@y.com"],
            tags=["a", "b"],
            is_substantive_reply=True,
            voice_score_baseline=0.75,
        )
        result = validate_corpus_sample(s)
        assert result.ok is True

    def test_missing_id_fails(self):
        s = _sample()
        del s["id"]
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("id" in e for e in result.errors)

    def test_missing_date_fails(self):
        s = _sample()
        del s["date"]
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("date" in e for e in result.errors)

    def test_missing_body_fails(self):
        s = _sample()
        del s["body"]
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("body" in e for e in result.errors)

    def test_missing_register_fails(self):
        s = _sample()
        del s["register"]
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("register" in e for e in result.errors)

    def test_missing_channel_fails(self):
        s = _sample()
        del s["channel"]
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("channel" in e for e in result.errors)

    def test_missing_year_fails(self):
        s = _sample()
        del s["year"]
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("year" in e for e in result.errors)

    def test_unknown_register_fails(self):
        s = _sample(register="follow-up")
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("register" in e for e in result.errors)

    def test_unknown_channel_fails(self):
        s = _sample(channel="sms")
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("channel" in e for e in result.errors)

    def test_naive_date_fails(self):
        s = _sample(date="2025-06-15T12:00:00")
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("date" in e for e in result.errors)

    def test_empty_body_fails(self):
        s = _sample(body="")
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("body" in e for e in result.errors)

    def test_non_string_id_fails(self):
        s = _sample()
        s["id"] = 42
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("id" in e for e in result.errors)

    def test_multiple_violations_all_reported(self):
        s = _sample(register="follow-up", channel="sms", body="")
        result = validate_corpus_sample(s)
        assert result.ok is False
        # All three should appear
        joined = " | ".join(result.errors)
        assert "register" in joined
        assert "channel" in joined
        assert "body" in joined

    def test_non_dict_input_raises(self):
        with pytest.raises(TypeError):
            validate_corpus_sample("not a dict")

    def test_extra_fields_tolerated(self):
        """Forward-compat — future Pillar F weeks may extend the
        schema. The validator MUST NOT reject unknown keys."""
        s = _sample()
        s["future_field"] = "value"
        result = validate_corpus_sample(s)
        assert result.ok is True

    def test_voice_score_baseline_bool_rejected(self):
        """Per Week 2 follow-up P3-2 — symmetric with the dataclass
        invariant; the strict gate must catch bools too."""
        s = _sample(voice_score_baseline=True)
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("voice_score_baseline" in e for e in result.errors)

    def test_register_explicit_null_rejected(self):
        """Per Week 2 follow-up P3-3 — JSON null for ``register`` is
        rejected by the strict validator even though the dataclass
        tolerates ``None`` for legacy corpora. The asymmetry is
        intentional per ADR-0038 §Existing-operator seed."""
        s = _sample()
        s["register"] = None
        result = validate_corpus_sample(s)
        assert result.ok is False
        assert any("register" in e for e in result.errors)


# ---------------------------------------------------------------------------
# retrieve_voice_exemplars — the per-call entry point
# ---------------------------------------------------------------------------


class TestRetrieveVoiceExemplars:
    """Per ADR-0038 D179. The shared retrieval primitive backs the
    per-register adapters at Week 4-8 per D181. Filters surface
    per-register / per-channel / per-substantive-reply slices of
    the corpus; the deterministic-clock ``now`` kwarg controls the
    recency multiplier per ADR-0031 D140 + ADR-0034 D156 + ADR-0035
    D162 precedent."""

    def _corpus_three_registers(self, tmp_path: Path) -> tuple[Path, np.ndarray]:
        # Three samples — one per register-channel combo. Each carries
        # a distinct embedding so cosine ordering is determinable.
        samples = [
            _sample(sid="s1", register="cold-pitch", channel="email",
                    date="2025-06-15T12:00:00Z", year=2025),
            _sample(sid="s2", register="congrats", channel="linkedin-dm",
                    date="2025-06-15T12:00:00Z", year=2025),
            _sample(sid="s3", register="cold-pitch", channel="email",
                    date="2025-06-15T12:00:00Z", year=2025,
                    is_substantive_reply=True),
        ]
        # Three identical unit vectors → cosine == 1.0 for each;
        # ordering then driven by recency multiplier (all 2025, so
        # equal scores — sort stable by index).
        embeddings = np.array([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([1.0, 0.0, 0.0]),
        ])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)
        return corpus_dir, embeddings

    def test_returns_voice_exemplar_instances(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft text",
            k=3,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(result) == 3
        for ex in result:
            assert isinstance(ex, VoiceExemplar)
            assert ex.score is not None

    def test_returns_top_k(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft",
            k=2,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(result) == 2

    def test_score_in_descending_order(self, tmp_path):
        # Distinct vectors → distinct cosine values
        samples = [
            _sample(sid="a", year=2025),
            _sample(sid="b", year=2025),
            _sample(sid="c", year=2025),
        ]
        embeddings = np.array([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([0.0, 1.0, 0.0]),
            _unit_vec([0.5, 0.5, 0.0]),
        ])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)
        # Query strongly aligns with first sample
        result = retrieve_voice_exemplars(
            "q",
            k=3,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert [e.id for e in result] == ["a", "c", "b"]
        for prev, curr in zip(result, result[1:]):
            assert prev.score >= curr.score

    def test_per_register_filter(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft",
            k=5,
            register="cold-pitch",
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        ids = {e.id for e in result}
        assert ids == {"s1", "s3"}

    def test_per_channel_filter(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft",
            k=5,
            channel="linkedin-dm",
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        ids = {e.id for e in result}
        assert ids == {"s2"}

    def test_is_substantive_reply_filter(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft",
            k=5,
            is_substantive_reply=True,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        ids = {e.id for e in result}
        assert ids == {"s3"}

    def test_combined_filters(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft",
            k=5,
            register="cold-pitch",
            channel="email",
            is_substantive_reply=True,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        ids = {e.id for e in result}
        assert ids == {"s3"}

    def test_filter_yields_empty_when_no_match(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft",
            k=5,
            register="reply",
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert result == []

    def test_k_larger_than_filtered_corpus_returns_all_matches(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        result = retrieve_voice_exemplars(
            "draft",
            k=100,
            register="cold-pitch",
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(result) == 2

    def test_unknown_register_filter_value_raises(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        with pytest.raises(ValueError, match="register"):
            retrieve_voice_exemplars(
                "draft",
                k=5,
                register="follow-up",
                corpus_dir=corpus_dir,
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
                now=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_unknown_channel_filter_value_raises(self, tmp_path):
        corpus_dir, _ = self._corpus_three_registers(tmp_path)
        with pytest.raises(ValueError, match="channel"):
            retrieve_voice_exemplars(
                "draft",
                k=5,
                channel="sms",
                corpus_dir=corpus_dir,
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
                now=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_deterministic_clock_now_kwarg_controls_recency(self, tmp_path):
        """Per ADR-0038 D179 deterministic-clock contract. Two
        different ``now`` values produce different recency
        multipliers — and thus different scores — for the same
        corpus + query."""
        samples = [_sample(sid="s1", year=2024)]
        embeddings = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)

        result_2026 = retrieve_voice_exemplars(
            "q",
            k=1,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        result_2030 = retrieve_voice_exemplars(
            "q",
            k=1,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )

        # Cosine = 1.0; recency = 1.0 - (now.year - 2024) * 0.03
        assert result_2026[0].score == pytest.approx(1.0 - 2 * 0.03)
        assert result_2030[0].score == pytest.approx(1.0 - 6 * 0.03)
        # Per-year monotone — newer "now" = smaller recency multiplier
        assert result_2026[0].score > result_2030[0].score

    def test_deterministic_clock_default_uses_wall_clock(self, tmp_path):
        samples = [_sample(sid="s1", year=datetime.now(timezone.utc).year)]
        embeddings = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)

        result = retrieve_voice_exemplars(
            "q",
            k=1,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
        )
        # Same-year recency = 1.0; cosine = 1.0
        assert result[0].score == pytest.approx(1.0)

    def test_missing_corpus_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            retrieve_voice_exemplars(
                "q",
                corpus_dir=tmp_path / "does-not-exist",
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            )

    def test_missing_embeddings_file_raises(self, tmp_path):
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        (corpus_dir / "index.json").write_text("[]")
        (corpus_dir / "metadata.json").write_text(json.dumps({
            "embed_model": DEFAULT_EMBED_MODEL,
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 0,
            "embed_version": "5.1.2",
            "built_at": "2026-05-01T00:00:00Z",
        }))
        with pytest.raises(FileNotFoundError, match="embeddings"):
            retrieve_voice_exemplars(
                "q",
                corpus_dir=corpus_dir,
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            )

    def test_missing_index_file_raises(self, tmp_path):
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        np.save(corpus_dir / "embeddings.npy", np.zeros((0, 3), dtype=np.float32))
        (corpus_dir / "metadata.json").write_text(json.dumps({
            "embed_model": DEFAULT_EMBED_MODEL,
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 0,
            "embed_version": "5.1.2",
            "built_at": "2026-05-01T00:00:00Z",
        }))
        with pytest.raises(FileNotFoundError, match="index"):
            retrieve_voice_exemplars(
                "q",
                corpus_dir=corpus_dir,
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            )

    def test_missing_metadata_file_raises(self, tmp_path):
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        np.save(corpus_dir / "embeddings.npy", np.zeros((0, 3), dtype=np.float32))
        (corpus_dir / "index.json").write_text("[]")
        with pytest.raises(FileNotFoundError, match="metadata"):
            retrieve_voice_exemplars(
                "q",
                corpus_dir=corpus_dir,
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            )

    def test_empty_corpus_returns_empty_without_matmul_crash(self, tmp_path):
        """Per Week 2 follow-up P2-1 — an empty corpus
        (shape[0] == 0, post-rebuild of an empty index.json) MUST
        short-circuit to an empty result rather than letting
        `embeddings @ q_emb` raise a dimension-mismatch ValueError.
        Symmetric with the filter-yields-nothing path that already
        returns []."""
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        # 384-dim shape so any q_emb shape would matmul-mismatch if
        # the guard is missing.
        np.save(corpus_dir / "embeddings.npy",
                np.zeros((0, 384), dtype=np.float32))
        (corpus_dir / "index.json").write_text("[]")
        (corpus_dir / "metadata.json").write_text(json.dumps({
            "embed_model": DEFAULT_EMBED_MODEL,
            "embed_version": "5.1.2",
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 0,
            "built_at": "2026-05-01T00:00:00Z",
        }))

        result = retrieve_voice_exemplars(
            "any query",
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(np.zeros(384, dtype=np.float32)),
        )
        assert result == []

    def test_legacy_sample_missing_register_treated_as_any_register(
        self, tmp_path,
    ):
        """Per ADR-0038 D178 §Existing-operator seed — pre-Pillar-F
        samples lacking ``register`` MUST be tolerated by the
        retrieval primitive. The per-register filter treats them as
        "all registers" (they pass through any filter)."""
        s = _sample(sid="legacy")
        del s["register"]
        del s["channel"]
        embeddings = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(tmp_path, [s], embeddings)

        result = retrieve_voice_exemplars(
            "q",
            k=5,
            register="cold-pitch",
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert len(result) == 1
        assert result[0].id == "legacy"


# ---------------------------------------------------------------------------
# Metadata mismatch — R026 refuse-loud
# ---------------------------------------------------------------------------


class TestMetadataMismatch:
    """Per ADR-0038 D179 R026 (operator-corpus split across
    multi-machine) mitigation. The cache sidecar carries
    ``embed_model`` + ``embed_version`` + ``schema_version``; load
    refuses-loud when the metadata diverges from the runtime."""

    def test_embed_model_mismatch_refuses_loud(self, tmp_path):
        samples = [_sample()]
        embeddings = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(
            tmp_path, samples, embeddings,
            embed_model="OLD-MODEL-v0",
        )
        with pytest.raises(VoiceCorpusMetadataMismatch, match="embed_model"):
            retrieve_voice_exemplars(
                "q",
                corpus_dir=corpus_dir,
                embed_model="NEW-MODEL-v1",
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            )

    def test_schema_version_mismatch_refuses_loud(self, tmp_path):
        samples = [_sample()]
        embeddings = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(
            tmp_path, samples, embeddings,
            schema_version=99,
        )
        with pytest.raises(VoiceCorpusMetadataMismatch, match="schema_version"):
            retrieve_voice_exemplars(
                "q",
                corpus_dir=corpus_dir,
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            )

    def test_corpus_count_mismatch_refuses_loud(self, tmp_path):
        samples = [_sample(sid="s1"), _sample(sid="s2")]
        embeddings = np.array([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([0.0, 1.0, 0.0]),
        ])
        corpus_dir = _make_corpus(
            tmp_path, samples, embeddings,
            corpus_count=99,  # diverges from len(samples)==2 and embeddings.shape[0]==2
        )
        with pytest.raises(VoiceCorpusMetadataMismatch, match="corpus_count"):
            retrieve_voice_exemplars(
                "q",
                corpus_dir=corpus_dir,
                embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            )

    def test_rebuild_on_mismatch_flag_triggers_rebuild(self, tmp_path):
        """Operator-controlled auto-rebuild per ADR-0038 D179
        §Embedding-cache substrate ``--rebuild-on-mismatch``
        flag. When ``rebuild_on_mismatch=True`` and the metadata
        diverges, the retrieve call re-embeds the corpus via the
        supplied ``embed_fn`` + writes new ``embeddings.npy`` +
        ``metadata.json`` BEFORE proceeding with the lookup."""
        samples = [_sample(sid="s1")]
        old_emb = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(
            tmp_path, samples, old_emb,
            embed_model="OLD-MODEL",
        )
        # New embed_fn returns a clearly different vector → if
        # rebuild ran, the new embeddings.npy carries the new
        # vector + the metadata says the new model name.
        new_vec = _unit_vec([0.0, 1.0, 0.0])
        result = retrieve_voice_exemplars(
            "q",
            corpus_dir=corpus_dir,
            embed_model="NEW-MODEL",
            embed_fn=_fixed_embed_fn(new_vec),
            rebuild_on_mismatch=True,
        )
        assert len(result) == 1
        rebuilt_emb = np.load(corpus_dir / "embeddings.npy")
        assert np.allclose(rebuilt_emb[0], new_vec)
        new_meta = json.loads((corpus_dir / "metadata.json").read_text())
        assert new_meta["embed_model"] == "NEW-MODEL"


# ---------------------------------------------------------------------------
# rebuild_corpus — re-embed-and-write
# ---------------------------------------------------------------------------


class TestRebuildCorpus:
    """Per ADR-0038 D179 + R026 mitigation. The CLI ``rebuild``
    subcommand wraps :func:`rebuild_corpus`; the
    ``rebuild_on_mismatch=True`` retrieve path also calls it."""

    def test_replaces_embeddings_with_fresh_encoding(self, tmp_path):
        samples = [
            _sample(sid="s1", body="first sample"),
            _sample(sid="s2", body="second sample"),
        ]
        old_emb = np.array([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([0.0, 1.0, 0.0]),
        ])
        corpus_dir = _make_corpus(
            tmp_path, samples, old_emb, embed_model="OLD",
        )

        # Per-sample distinct vectors so we can verify per-sample
        # rebuild.
        def per_sample_embed(text: str) -> np.ndarray:
            if "first" in text:
                return _unit_vec([0.0, 0.0, 1.0])
            return _unit_vec([0.5, 0.5, 0.0])

        rebuild_corpus(
            corpus_dir,
            embed_model="NEW",
            embed_fn=per_sample_embed,
        )

        rebuilt_emb = np.load(corpus_dir / "embeddings.npy")
        assert rebuilt_emb.shape == (2, 3)
        assert np.allclose(rebuilt_emb[0], _unit_vec([0.0, 0.0, 1.0]))
        assert np.allclose(rebuilt_emb[1], _unit_vec([0.5, 0.5, 0.0]))

    def test_writes_new_metadata_with_runtime_model(self, tmp_path):
        samples = [_sample()]
        old_emb = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(
            tmp_path, samples, old_emb, embed_model="OLD",
        )

        rebuild_corpus(
            corpus_dir,
            embed_model="NEW",
            embed_fn=_fixed_embed_fn(_unit_vec([0.0, 1.0, 0.0])),
        )

        new_meta = json.loads((corpus_dir / "metadata.json").read_text())
        assert new_meta["embed_model"] == "NEW"
        assert new_meta["schema_version"] == SCHEMA_VERSION
        assert new_meta["corpus_count"] == 1
        assert "built_at" in new_meta

    def test_preserves_index_json_unchanged(self, tmp_path):
        samples = [_sample(sid="keep-me", body="text")]
        old_emb = np.array([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(
            tmp_path, samples, old_emb, embed_model="OLD",
        )

        rebuild_corpus(
            corpus_dir,
            embed_model="NEW",
            embed_fn=_fixed_embed_fn(_unit_vec([0.0, 1.0, 0.0])),
        )

        rebuilt_idx = json.loads((corpus_dir / "index.json").read_text())
        assert len(rebuilt_idx) == 1
        assert rebuilt_idx[0]["id"] == "keep-me"
        assert rebuilt_idx[0]["body"] == "text"


# ---------------------------------------------------------------------------
# voice_exemplar_retrieved event-payload factory
# ---------------------------------------------------------------------------


class TestBuildVoiceExemplarRetrievedPayload:
    """Per ADR-0038 D182. The event class carries:

    * ``type``: ``voice_exemplar_retrieved``
    * ``person_id``: from the calling draft's recipient
    * ``query_hash``: sha256 of the query (NOT the raw query — I8
      privacy invariant)
    * ``exemplars``: list of ``{exemplar_id, score}`` dicts (NOT the
      exemplar bodies — operator-private corpus content stays in
      the corpus)
    * ``channel``: derived from the draft's intended channel
      (channel-on-every-event invariant per ADR-0014 D33)
    * ``register``: the draft's register (closed-enum per D178)
    * ``_emitted_by``: ``voice_corpus`` per ADR-0010 D17
    """

    def _exemplars(self) -> list[VoiceExemplar]:
        return [
            VoiceExemplar(
                id="ex1", date="2025-06-15T12:00:00Z",
                body="example body 1", register="cold-pitch",
                channel="email", year=2025, score=0.91,
            ),
            VoiceExemplar(
                id="ex2", date="2025-05-10T12:00:00Z",
                body="example body 2", register="cold-pitch",
                channel="email", year=2025, score=0.87,
            ),
        ]

    def test_type_field(self):
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p123", query="draft text",
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        assert payload["type"] == "voice_exemplar_retrieved"

    def test_person_id_field(self):
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p123", query="draft text",
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        assert payload["person_id"] == "p123"

    def test_person_id_none_accepted(self):
        payload = build_voice_exemplar_retrieved_payload(
            person_id=None, query="draft",
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        assert payload["person_id"] is None

    def test_query_hash_field_is_sha256(self):
        query = "draft text"
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query=query,
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        expected = "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()
        assert payload["query_hash"] == expected

    def test_raw_query_does_not_appear_in_payload(self):
        """Privacy — per ADR-0038 D182 + I8 + the event's
        operator-private posture, the raw query text MUST NOT
        appear in the payload (operators look up exemplar bodies
        via the corpus directly; the ledger event is hash-only)."""
        query = "very confidential research findings about Dylan"
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query=query,
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        flattened = json.dumps(payload)
        assert query not in flattened
        assert "confidential" not in flattened

    def test_exemplars_field_shape(self):
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query="q",
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        assert payload["exemplars"] == [
            {"exemplar_id": "ex1", "score": pytest.approx(0.91)},
            {"exemplar_id": "ex2", "score": pytest.approx(0.87)},
        ]

    def test_exemplars_field_omits_body(self):
        """Privacy + storage — per-exemplar body is NOT in the
        event. Operators inspect the corpus directly for body."""
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query="q",
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        for ex_payload in payload["exemplars"]:
            assert "body" not in ex_payload
            assert "subject" not in ex_payload
            assert "to" not in ex_payload

    def test_channel_field(self):
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query="q",
            exemplars=self._exemplars(),
            channel="linkedin-dm", register="congrats",
        )
        assert payload["channel"] == "linkedin-dm"

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError, match="channel"):
            build_voice_exemplar_retrieved_payload(
                person_id="p", query="q",
                exemplars=self._exemplars(),
                channel="sms", register="cold-pitch",
            )

    def test_register_field(self):
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query="q",
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        assert payload["register"] == "cold-pitch"

    def test_register_none_accepted(self):
        """The unscoped retrieval path (no per-register filter)
        emits ``register: None`` — operator-deliberate per the
        D182 emit-shape."""
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query="q",
            exemplars=self._exemplars(),
            channel="email", register=None,
        )
        assert payload["register"] is None

    def test_unknown_register_raises(self):
        with pytest.raises(ValueError, match="register"):
            build_voice_exemplar_retrieved_payload(
                person_id="p", query="q",
                exemplars=self._exemplars(),
                channel="email", register="follow-up",
            )

    def test_emitted_by_field(self):
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query="q",
            exemplars=self._exemplars(),
            channel="email", register="cold-pitch",
        )
        assert payload["_emitted_by"] == EMITTED_BY
        assert payload["_emitted_by"] == "voice_corpus"

    def test_empty_exemplars_accepted(self):
        """A retrieval that finds zero matches (filtered to nothing)
        emits the event with an empty list — operator-visible
        signal that the retrieval ran but returned nothing."""
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p", query="q",
            exemplars=[],
            channel="email", register="cold-pitch",
        )
        assert payload["exemplars"] == []


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------


class TestCLI:
    """Per ADR-0038 D179 + the per-primitive flat-CLI convention
    inherited from :mod:`discovery_dedup` + :mod:`email_verification_cache`
    + :mod:`tier_assignment`. Three subcommands: ``retrieve`` +
    ``validate`` + ``rebuild``."""

    def test_help_lists_three_subcommands(self):
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        for sub in ("retrieve", "validate", "rebuild"):
            assert sub in proc.stdout

    def test_validate_subcommand_reports_invalid_schema(self, tmp_path):
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        bad_samples = [
            {"id": "x", "date": "2025-06-15T12:00:00Z", "body": "b",
             "register": "follow-up", "channel": "sms", "year": 2025},
        ]
        (corpus_dir / "index.json").write_text(json.dumps(bad_samples))
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "validate",
             "--corpus-dir", str(corpus_dir), "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode != 0
        out = json.loads(proc.stdout)
        assert out["ok"] is False
        assert any("register" in e for s in out["samples"]
                   for e in s.get("errors", []))

    def test_validate_subcommand_happy_path(self, tmp_path):
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        good_samples = [_sample()]
        (corpus_dir / "index.json").write_text(json.dumps(good_samples))
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "validate",
             "--corpus-dir", str(corpus_dir), "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert out["sample_count"] == 1

    def test_retrieve_subcommand_refuses_apply_without_channel(self, tmp_path):
        """Per Week 2 follow-up P2-2 — channel-on-every-event
        invariant requires the operator's deliberate channel at emit
        time. ``--apply`` without ``--channel`` must refuse-loud
        rather than silently defaulting to ``"email"``."""
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        samples = [_sample()]
        # 384-dim matches the default BAAI/bge-small-en-v1.5 output
        # so the CLI's real SentenceTransformer encoder + matmul work.
        emb = np.zeros((1, 384), dtype=np.float32)
        emb[0, 0] = 1.0
        np.save(corpus_dir / "embeddings.npy", emb)
        (corpus_dir / "index.json").write_text(json.dumps(samples))
        (corpus_dir / "metadata.json").write_text(json.dumps({
            "embed_model": DEFAULT_EMBED_MODEL,
            "embed_version": "5.1.2",
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 1,
            "built_at": "2026-05-01T00:00:00Z",
        }))
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "retrieve",
             "--query", "test draft",
             "--corpus-dir", str(corpus_dir),
             "--apply"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode != 0
        assert "--channel is required when --apply" in proc.stderr


class TestCLIRetrieveOutput:
    """Per Week 2 follow-up P2-3 — Path A's CLI ``--json`` output
    must carry the ``to`` field per the SKILL.md Step 2 prompt
    template's ``to [...]`` placeholder.
    """

    def test_retrieve_json_output_includes_to_field(self, tmp_path):
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        samples = [
            _sample(sid="s1", to=["dylan@example.com"], subject="hello"),
        ]
        # 384-dim matches the default BAAI/bge-small-en-v1.5 output
        # so the CLI's real SentenceTransformer encoder + matmul work.
        emb = np.zeros((1, 384), dtype=np.float32)
        emb[0, 0] = 1.0
        np.save(corpus_dir / "embeddings.npy", emb)
        (corpus_dir / "index.json").write_text(json.dumps(samples))
        (corpus_dir / "metadata.json").write_text(json.dumps({
            "embed_model": DEFAULT_EMBED_MODEL,
            "embed_version": "5.1.2",
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 1,
            "built_at": "2026-05-01T00:00:00Z",
        }))
        # Override OUTREACH_FACTORY_CONFIG so the CLI doesn't try to
        # load the operator's real config; pass an empty config dir.
        env_config = tmp_path / "config.yml"
        env_config.write_text("voice: {}\n")
        import os as _os
        env = {**_os.environ, "OUTREACH_FACTORY_CONFIG": str(env_config)}
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "retrieve",
             "--query", "test draft",
             "--corpus-dir", str(corpus_dir),
             "--json"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["ok"] is True
        assert len(out["exemplars"]) == 1
        ex = out["exemplars"][0]
        # The to field MUST be present in the CLI JSON output to
        # match the SKILL.md Step 2 prompt template's `to [...]`.
        assert "to" in ex
        assert ex["to"] == ["dylan@example.com"]
        # Sanity-check the other fields the SKILL.md schema names.
        for required in ("id", "date", "subject", "register",
                         "channel", "score", "is_substantive_reply",
                         "body"):
            assert required in ex

    def test_retrieve_json_output_omits_payload_when_no_channel(self, tmp_path):
        """Per Week 2 follow-up P2-2 — the dry-run inspection path
        (``--json`` without ``--apply``) does NOT include a synthetic
        ``payload`` with a defaulted channel. Operators who want the
        emit-shape preview pass ``--channel`` explicitly."""
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        samples = [_sample()]
        # 384-dim matches the default BAAI/bge-small-en-v1.5 output
        # so the CLI's real SentenceTransformer encoder + matmul work.
        emb = np.zeros((1, 384), dtype=np.float32)
        emb[0, 0] = 1.0
        np.save(corpus_dir / "embeddings.npy", emb)
        (corpus_dir / "index.json").write_text(json.dumps(samples))
        (corpus_dir / "metadata.json").write_text(json.dumps({
            "embed_model": DEFAULT_EMBED_MODEL,
            "embed_version": "5.1.2",
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 1,
            "built_at": "2026-05-01T00:00:00Z",
        }))
        env_config = tmp_path / "config.yml"
        env_config.write_text("voice: {}\n")
        import os as _os
        env = {**_os.environ, "OUTREACH_FACTORY_CONFIG": str(env_config)}
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "retrieve",
             "--query", "test draft",
             "--corpus-dir", str(corpus_dir),
             "--json"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        # No --channel + no --apply → no payload preview in dry-run
        # output (avoids the silent channel default).
        assert "payload" not in out
        assert out["channel"] is None

    def test_retrieve_json_output_includes_payload_when_channel_given(
        self, tmp_path,
    ):
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir()
        samples = [_sample()]
        # 384-dim matches the default BAAI/bge-small-en-v1.5 output
        # so the CLI's real SentenceTransformer encoder + matmul work.
        emb = np.zeros((1, 384), dtype=np.float32)
        emb[0, 0] = 1.0
        np.save(corpus_dir / "embeddings.npy", emb)
        (corpus_dir / "index.json").write_text(json.dumps(samples))
        (corpus_dir / "metadata.json").write_text(json.dumps({
            "embed_model": DEFAULT_EMBED_MODEL,
            "embed_version": "5.1.2",
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 1,
            "built_at": "2026-05-01T00:00:00Z",
        }))
        env_config = tmp_path / "config.yml"
        env_config.write_text("voice: {}\n")
        import os as _os
        env = {**_os.environ, "OUTREACH_FACTORY_CONFIG": str(env_config)}
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "retrieve",
             "--query", "test draft",
             "--corpus-dir", str(corpus_dir),
             "--channel", "email",
             "--register", "cold-pitch",
             "--json"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert "payload" in out
        payload = out["payload"]
        assert payload["type"] == "voice_exemplar_retrieved"
        assert payload["channel"] == "email"
        assert payload["register"] == "cold-pitch"


# ---------------------------------------------------------------------------
# Cross-primitive plumbing — retrieval result → event payload
# ---------------------------------------------------------------------------


class TestRetrievalToEventPlumbing:
    """End-to-end shape check: a retrieve_voice_exemplars result
    feeds straight into build_voice_exemplar_retrieved_payload
    without translation. The two surfaces compose."""

    def test_retrieve_result_feeds_payload_factory(self, tmp_path):
        samples = [
            _sample(sid="s1", year=2025),
            _sample(sid="s2", year=2025),
        ]
        embeddings = np.array([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([0.5, 0.5, 0.0]),
        ])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)

        result = retrieve_voice_exemplars(
            "draft",
            k=2,
            corpus_dir=corpus_dir,
            embed_fn=_fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0])),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p999", query="draft",
            exemplars=result,
            channel="email", register="cold-pitch",
        )
        assert payload["type"] == "voice_exemplar_retrieved"
        assert len(payload["exemplars"]) == 2
        assert {e["exemplar_id"] for e in payload["exemplars"]} == {"s1", "s2"}


# ---------------------------------------------------------------------------
# Per-register adapters — Pillar F Week 3 (ADR-0040 D192-D198)
# ---------------------------------------------------------------------------


class TestPerRegisterAdapters:
    """Pillar F Week 3 — per-register adapter pattern per ADR-0040.

    Five thin free-function adapters at the module level matching the
    ``/draft-outreach`` SKILL.md register table:

    * :func:`retrieve_cold_pitch_exemplars` — biases
      ``is_substantive_reply=True`` per the SKILL.md's 5-touch
      sampling discipline. Default channel: email.
    * :func:`retrieve_congrats_exemplars` — no reply bias (congrats
      often don't get replies). Default channel: linkedin-dm.
    * :func:`retrieve_re_engagement_exemplars` — no reply bias.
      Default channel: email.
    * :func:`retrieve_reply_exemplars` — channel REQUIRED (no
      default per ADR-0040 D195; SKILL.md's "match inbound channel"
      rule). No reply bias.
    * :func:`retrieve_public_comment_exemplars` — no reply bias.
      Default channel: linkedin-comment.

    Each adapter delegates to :func:`retrieve_voice_exemplars` with
    the per-register kwargs frozen per ADR-0040 D193 + D196. The
    signature shape is symmetric across all five per ADR-0040 D194;
    operators override per-register channel defaults via the
    ``channel=`` kwarg.

    The TEST-ONLY ``embed_fn`` injection seam per ADR-0040 D197 is
    preserved at every per-register adapter — tests pass a
    deterministic embedder to bypass the ~1-2s SentenceTransformer
    load.
    """

    # -- Fixtures ----------------------------------------------------

    def _corpus_all_registers_and_channels(
        self, tmp_path: Path,
    ) -> Path:
        """Build a corpus with one sample per (register, channel) combo
        the adapter set would target by default, plus a few extra samples
        to verify filtering. Each sample's embedding is identical (cosine
        == 1.0) so filter behavior is the only differentiator."""
        samples = [
            # cold-pitch/email — substantive reply (matches cold-pitch
            # adapter's is_substantive_reply=True bias)
            _sample(sid="cp-email-sub", register="cold-pitch",
                    channel="email", is_substantive_reply=True),
            # cold-pitch/email — NOT substantive (cold-pitch adapter
            # filters this OUT via is_substantive_reply=True bias)
            _sample(sid="cp-email-nosub", register="cold-pitch",
                    channel="email", is_substantive_reply=False),
            # congrats/linkedin-dm
            _sample(sid="cg-ldm", register="congrats",
                    channel="linkedin-dm"),
            # re-engagement/email
            _sample(sid="re-email", register="re-engagement",
                    channel="email"),
            # reply/email — for reply adapter with explicit channel=email
            _sample(sid="rp-email", register="reply", channel="email"),
            # reply/linkedin-dm — for reply adapter with channel=linkedin-dm
            _sample(sid="rp-ldm", register="reply", channel="linkedin-dm"),
            # public-comment/linkedin-comment
            _sample(sid="pc-lcm", register="public-comment",
                    channel="linkedin-comment"),
            # cold-pitch/linkedin-dm — non-default channel for cold-pitch;
            # the cold-pitch adapter would filter this OUT by default
            _sample(sid="cp-ldm-sub", register="cold-pitch",
                    channel="linkedin-dm", is_substantive_reply=True),
        ]
        n = len(samples)
        # All identical unit vectors → cosine == 1.0 for each;
        # ordering is then filter-bound only.
        embeddings = np.stack([
            _unit_vec([1.0, 0.0, 0.0]) for _ in range(n)
        ])
        return _make_corpus(tmp_path, samples, embeddings)

    def _embed_fn(self) -> Callable[[str], np.ndarray]:
        return _fixed_embed_fn(_unit_vec([1.0, 0.0, 0.0]))

    def _now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)

    # -- cold-pitch adapter ------------------------------------------

    def test_cold_pitch_adapter_filters_register_to_cold_pitch(
        self, tmp_path,
    ):
        """ADR-0040 D193 — cold-pitch adapter freezes
        ``register="cold-pitch"``. Returned exemplars MUST only be
        from the cold-pitch register."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_cold_pitch_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.register == "cold-pitch", (
                f"cold-pitch adapter surfaced non-cold-pitch exemplar "
                f"{ex.id} register={ex.register!r}"
            )

    def test_cold_pitch_adapter_defaults_channel_to_email(
        self, tmp_path,
    ):
        """ADR-0040 D195 — cold-pitch adapter defaults
        ``channel=DEFAULT_CHANNEL_FOR_COLD_PITCH`` ("email") when
        the operator omits ``channel=``. The result must exclude
        cold-pitch samples in non-email channels."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_cold_pitch_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.channel == "email"
        ids = {ex.id for ex in result}
        # cp-ldm-sub is cold-pitch but linkedin-dm channel — must be
        # excluded by the per-register channel default
        assert "cp-ldm-sub" not in ids

    def test_cold_pitch_adapter_biases_is_substantive_reply_true(
        self, tmp_path,
    ):
        """ADR-0040 D196 — cold-pitch adapter freezes
        ``is_substantive_reply=True`` per the SKILL.md's 5-touch
        sampling discipline. The result must exclude cold-pitch
        samples flagged ``is_substantive_reply=False``."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_cold_pitch_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        ids = {ex.id for ex in result}
        # cp-email-sub has is_substantive_reply=True → IN
        assert "cp-email-sub" in ids
        # cp-email-nosub has is_substantive_reply=False → OUT
        assert "cp-email-nosub" not in ids

    def test_cold_pitch_adapter_channel_override_works(
        self, tmp_path,
    ):
        """ADR-0040 D194 — operators may override the per-register
        channel default via the adapter's ``channel=`` kwarg.
        Surfacing cp-ldm-sub (cold-pitch/linkedin-dm) requires the
        override."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_cold_pitch_exemplars(
            "draft",
            k=10,
            channel="linkedin-dm",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        ids = {ex.id for ex in result}
        assert "cp-ldm-sub" in ids
        # Default channel cp-email-sub is now excluded
        assert "cp-email-sub" not in ids

    def test_cold_pitch_adapter_returns_voice_exemplar_list(
        self, tmp_path,
    ):
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_cold_pitch_exemplars(
            "draft",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        assert isinstance(result, list)
        for ex in result:
            assert isinstance(ex, VoiceExemplar)
            assert ex.score is not None

    def test_cold_pitch_adapter_invalid_channel_raises(
        self, tmp_path,
    ):
        """ADR-0040 D194 — operator-supplied ``channel=`` non-None
        but not in :data:`CHANNELS` raises via the shared
        primitive's filter validation per ADR-0038 D179."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        with pytest.raises(ValueError, match="channel"):
            retrieve_cold_pitch_exemplars(
                "draft",
                channel="sms",
                corpus_dir=corpus_dir,
                embed_fn=self._embed_fn(),
            )

    # -- congrats adapter --------------------------------------------

    def test_congrats_adapter_filters_register_to_congrats(
        self, tmp_path,
    ):
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_congrats_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.register == "congrats"

    def test_congrats_adapter_defaults_channel_to_linkedin_dm(
        self, tmp_path,
    ):
        """ADR-0040 D195 — congrats adapter defaults
        ``channel=DEFAULT_CHANNEL_FOR_CONGRATS`` ("linkedin-dm")."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_congrats_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.channel == "linkedin-dm"

    def test_congrats_adapter_no_is_substantive_reply_bias(
        self, tmp_path,
    ):
        """ADR-0040 D196 — congrats adapter freezes
        ``is_substantive_reply=None`` (no bias; congrats often don't
        get replies).

        Per Week 3 follow-up P3-2 — the corpus contains BOTH
        is_substantive_reply=True AND is_substantive_reply=False
        samples; both MUST appear in the result. A regression to
        is_substantive_reply=True (cold-pitch's bias) would exclude
        the False sample; a regression to is_substantive_reply=False
        would exclude the True sample. None passes both."""
        samples = [
            _sample(sid="cg-true", register="congrats",
                    channel="linkedin-dm",
                    is_substantive_reply=True),
            _sample(sid="cg-false", register="congrats",
                    channel="linkedin-dm",
                    is_substantive_reply=False),
        ]
        embeddings = np.stack([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([1.0, 0.0, 0.0]),
        ])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)
        result = retrieve_congrats_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        ids = {ex.id for ex in result}
        assert ids == {"cg-true", "cg-false"}, (
            f"congrats adapter MUST NOT bias is_substantive_reply "
            f"per ADR-0040 D196; got ids={ids} (expected both True "
            f"and False samples)"
        )

    # -- re-engagement adapter ---------------------------------------

    def test_re_engagement_adapter_filters_register(self, tmp_path):
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_re_engagement_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.register == "re-engagement"

    def test_re_engagement_adapter_defaults_channel_to_email(
        self, tmp_path,
    ):
        """ADR-0040 D195 — re-engagement adapter defaults
        ``channel=DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT`` ("email")."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_re_engagement_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.channel == "email"

    def test_re_engagement_adapter_no_reply_bias(self, tmp_path):
        """ADR-0040 D196 — re-engagement adapter freezes
        ``is_substantive_reply=None`` (no bias; reply patterns vary).

        Per Week 3 follow-up P3-2 — discriminating fixture (both
        True and False samples) catches regressions to either
        bias direction."""
        samples = [
            _sample(sid="re-true", register="re-engagement",
                    channel="email",
                    is_substantive_reply=True),
            _sample(sid="re-false", register="re-engagement",
                    channel="email",
                    is_substantive_reply=False),
        ]
        embeddings = np.stack([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([1.0, 0.0, 0.0]),
        ])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)
        result = retrieve_re_engagement_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        ids = {ex.id for ex in result}
        assert ids == {"re-true", "re-false"}, (
            f"re-engagement adapter MUST NOT bias is_substantive_reply "
            f"per ADR-0040 D196; got ids={ids}"
        )

    # -- reply adapter (the asymmetric one) --------------------------

    def test_reply_adapter_requires_channel_kwarg(self, tmp_path):
        """ADR-0040 D194 + D195 — the reply register has NO
        framework channel default; the adapter raises ValueError
        when ``channel=None``."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        with pytest.raises(ValueError, match="requires an explicit channel"):
            retrieve_reply_exemplars(
                "draft",
                corpus_dir=corpus_dir,
                embed_fn=self._embed_fn(),
            )

    def test_reply_adapter_requires_channel_kwarg_message_names_skill_md(
        self, tmp_path,
    ):
        """The reply adapter's error message names the SKILL.md
        register table's 'match inbound channel' rule for operator
        readability."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        with pytest.raises(ValueError) as exc_info:
            retrieve_reply_exemplars(
                "draft",
                corpus_dir=corpus_dir,
                embed_fn=self._embed_fn(),
            )
        msg = str(exc_info.value)
        assert "match inbound channel" in msg
        assert "ADR-0040" in msg

    def test_reply_adapter_filters_register_with_email_channel(
        self, tmp_path,
    ):
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_reply_exemplars(
            "draft",
            channel="email",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.register == "reply"
            assert ex.channel == "email"
        ids = {ex.id for ex in result}
        assert "rp-email" in ids
        assert "rp-ldm" not in ids

    def test_reply_adapter_filters_register_with_linkedin_dm_channel(
        self, tmp_path,
    ):
        """The operator-supplied channel overrides; reply/linkedin-dm
        sample lands when ``channel="linkedin-dm"``."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_reply_exemplars(
            "draft",
            channel="linkedin-dm",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.register == "reply"
            assert ex.channel == "linkedin-dm"
        ids = {ex.id for ex in result}
        assert "rp-ldm" in ids
        assert "rp-email" not in ids

    def test_reply_adapter_invalid_channel_raises(self, tmp_path):
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        with pytest.raises(ValueError, match="channel"):
            retrieve_reply_exemplars(
                "draft",
                channel="sms",
                corpus_dir=corpus_dir,
                embed_fn=self._embed_fn(),
            )

    # -- public-comment adapter --------------------------------------

    def test_public_comment_adapter_filters_register(self, tmp_path):
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_public_comment_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.register == "public-comment"

    def test_public_comment_adapter_defaults_channel(self, tmp_path):
        """ADR-0040 D195 — defaults
        ``channel=DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT``
        ("linkedin-comment")."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        result = retrieve_public_comment_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        for ex in result:
            assert ex.channel == "linkedin-comment"

    def test_public_comment_adapter_no_reply_bias(self, tmp_path):
        """ADR-0040 D196 — public-comment adapter freezes
        ``is_substantive_reply=None`` (no bias; thread-level reply
        semantics are not in the per-DM field).

        Per Week 3 follow-up P3-2 — discriminating fixture (both
        True and False samples) catches regressions to either
        bias direction."""
        samples = [
            _sample(sid="pc-true", register="public-comment",
                    channel="linkedin-comment",
                    is_substantive_reply=True),
            _sample(sid="pc-false", register="public-comment",
                    channel="linkedin-comment",
                    is_substantive_reply=False),
        ]
        embeddings = np.stack([
            _unit_vec([1.0, 0.0, 0.0]),
            _unit_vec([1.0, 0.0, 0.0]),
        ])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)
        result = retrieve_public_comment_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        ids = {ex.id for ex in result}
        assert ids == {"pc-true", "pc-false"}, (
            f"public-comment adapter MUST NOT bias is_substantive_reply "
            f"per ADR-0040 D196; got ids={ids}"
        )

    # -- Symmetric signature shape -----------------------------------

    def test_all_adapters_share_keyword_only_signature_shape(self):
        """ADR-0040 D194 — STRICT symmetric keyword-only signature
        across all five adapters. Reply has the same signature shape
        but raises at runtime when channel is None (D194 + D195).

        Per Week 3 follow-up P3-1 — uses strict equality (==) rather
        than subset matching, so a future regression where one
        adapter sprouted an extra kwarg (e.g., cold-pitch silently
        re-surfacing ``is_substantive_reply`` per D196-Alt1's
        rejected path) would fail this test. The regression barrier
        must be strict to enforce the per-register-symmetry pattern
        D194 pins.
        """
        import inspect
        adapters = [
            retrieve_cold_pitch_exemplars,
            retrieve_congrats_exemplars,
            retrieve_re_engagement_exemplars,
            retrieve_reply_exemplars,
            retrieve_public_comment_exemplars,
        ]
        expected_kw_only = {
            "k", "channel", "now", "corpus_dir", "embed_model",
            "rebuild_on_mismatch", "cfg", "embed_fn",
        }
        # Each adapter's full parameter NAME tuple (positional-then-
        # keyword-only); used to pin signature shape symmetry across
        # all five adapters.
        per_adapter_param_names: list[tuple[str, ...]] = []
        for adapter in adapters:
            sig = inspect.signature(adapter)
            params = list(sig.parameters.items())
            # First param: query (positional or keyword)
            assert params[0][0] == "query", (
                f"{adapter.__name__}: first param must be query"
            )
            # All remaining params: keyword-only AND exactly
            # expected_kw_only — no extras (regression barrier
            # against per-register kwarg drift).
            kw_only_names = {
                name for name, p in params[1:]
                if p.kind == inspect.Parameter.KEYWORD_ONLY
            }
            assert kw_only_names == expected_kw_only, (
                f"{adapter.__name__}: keyword-only kwargs "
                f"{kw_only_names} != expected {expected_kw_only}; "
                f"the per-register-symmetry pattern per ADR-0040 "
                f"D194 requires EXACTLY these kwargs (no extras / "
                f"no missing)"
            )
            # Pin parameter order across adapters too (full tuple).
            per_adapter_param_names.append(
                tuple(name for name, _ in params)
            )
        # All five adapters MUST share the exact parameter order +
        # name tuple. Verifies per-register-symmetry beyond just the
        # kwarg set.
        first = per_adapter_param_names[0]
        for adapter, names in zip(adapters[1:], per_adapter_param_names[1:]):
            assert names == first, (
                f"{adapter.__name__}: parameter order {names} differs "
                f"from {adapters[0].__name__}'s {first}; per-register "
                f"signature symmetry per ADR-0040 D194 requires "
                f"identical signature shape across all five adapters"
            )

    def test_all_adapters_return_list_of_voice_exemplar(self, tmp_path):
        """ADR-0040 D194 — symmetric return type."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        for adapter, kwargs in [
            (retrieve_cold_pitch_exemplars, {}),
            (retrieve_congrats_exemplars, {}),
            (retrieve_re_engagement_exemplars, {}),
            (retrieve_reply_exemplars, {"channel": "email"}),
            (retrieve_public_comment_exemplars, {}),
        ]:
            result = adapter(
                "draft",
                corpus_dir=corpus_dir,
                embed_fn=self._embed_fn(),
                now=self._now(),
                **kwargs,
            )
            assert isinstance(result, list)
            for ex in result:
                assert isinstance(ex, VoiceExemplar)

    # -- TEST-ONLY embed_fn seam preservation ------------------------

    def test_all_adapters_accept_embed_fn_kwarg(self):
        """ADR-0040 D197 — TEST-ONLY ``embed_fn`` kwarg preserved
        at every per-register adapter per ADR-0038 D188 + the Week 2
        audit's P3-B carry-forward."""
        import inspect
        adapters = [
            retrieve_cold_pitch_exemplars,
            retrieve_congrats_exemplars,
            retrieve_re_engagement_exemplars,
            retrieve_reply_exemplars,
            retrieve_public_comment_exemplars,
        ]
        for adapter in adapters:
            sig = inspect.signature(adapter)
            assert "embed_fn" in sig.parameters, (
                f"{adapter.__name__}: missing TEST-ONLY embed_fn kwarg "
                f"(ADR-0040 D197 + Week 2 audit P3-B carry-forward)"
            )
            p = sig.parameters["embed_fn"]
            assert p.kind == inspect.Parameter.KEYWORD_ONLY
            assert p.default is None

    def test_all_adapter_docstrings_label_embed_fn_test_only(self):
        """ADR-0040 D197 — the TEST-ONLY label MUST appear in each
        adapter's docstring (mirrors retrieve_voice_exemplars per
        ADR-0039 D188 + Week 2 audit P3-B)."""
        adapters = [
            retrieve_cold_pitch_exemplars,
            retrieve_congrats_exemplars,
            retrieve_re_engagement_exemplars,
            retrieve_reply_exemplars,
            retrieve_public_comment_exemplars,
        ]
        for adapter in adapters:
            doc = adapter.__doc__ or ""
            assert "TEST-ONLY" in doc, (
                f"{adapter.__name__}: docstring missing TEST-ONLY label "
                f"on the embed_fn kwarg (ADR-0040 D197 + Week 2 audit "
                f"P3-B carry-forward)"
            )

    # -- now / corpus_dir / embed_model / rebuild_on_mismatch passthrough

    def test_all_adapters_now_kwarg_controls_recency(self, tmp_path):
        """ADR-0040 D194 — the ``now`` kwarg passes through to the
        shared primitive's deterministic-clock contract per ADR-0038
        D179 + ADR-0039 D188."""
        # Year 2020 sample → recency multiplier varies with now.year
        samples = [
            _sample(sid="cp", register="cold-pitch", channel="email",
                    year=2020, is_substantive_reply=True),
        ]
        embeddings = np.stack([_unit_vec([1.0, 0.0, 0.0])])
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)
        r2026 = retrieve_cold_pitch_exemplars(
            "draft",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        r2030 = retrieve_cold_pitch_exemplars(
            "draft",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        assert r2026[0].score > r2030[0].score

    def test_all_adapters_propagate_corpus_dir_override(self, tmp_path):
        """ADR-0040 D194 — ``corpus_dir=`` passes through. The
        adapters MUST NOT pin a hard-coded corpus location."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        # If the adapter ignored corpus_dir, it would fall back to the
        # default at ~/.outreach-factory/voice-corpus/ — almost
        # certainly missing on the CI machine + raising FileNotFoundError.
        result = retrieve_cold_pitch_exemplars(
            "draft",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        assert len(result) >= 1

    # -- Cross-adapter independence ----------------------------------

    def test_adapters_return_independent_filtered_views(
        self, tmp_path,
    ):
        """Adapter independence — calling cold-pitch then congrats
        produces filter-disjoint result sets (no state leakage)."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        cp = retrieve_cold_pitch_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        cg = retrieve_congrats_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        cp_regs = {ex.register for ex in cp}
        cg_regs = {ex.register for ex in cg}
        assert cp_regs == {"cold-pitch"}
        assert cg_regs == {"congrats"}
        # No overlap by register (the adapters' per-register filters
        # are exclusive)
        assert cp_regs.isdisjoint(cg_regs)

    def test_consecutive_adapter_calls_are_deterministic(
        self, tmp_path,
    ):
        """Two consecutive calls with identical kwargs MUST return
        the same result. Pins per-call determinism — adapter must
        not carry per-call state across invocations.

        Per Week 3 follow-up P3-3 — renamed from
        ``test_adapter_call_does_not_mutate_default_kwargs`` since
        the test verifies determinism, not mutable-default-kwarg
        absence. The companion test
        :func:`test_no_adapter_has_mutable_default_kwargs` covers the
        mutable-default-kwarg footgun statically via
        :mod:`inspect`."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        r1 = retrieve_cold_pitch_exemplars(
            "draft",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        r2 = retrieve_cold_pitch_exemplars(
            "draft",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        assert [e.id for e in r1] == [e.id for e in r2]

    def test_no_adapter_has_mutable_default_kwargs(self):
        """Per Week 3 follow-up P3-3 — static guard against the
        Python mutable-default-kwarg footgun
        (``def f(x: dict = {})``). The adapters' kwarg defaults
        MUST all be immutable (None / int / bool / DEFAULT_TOP_K /
        false). A future regression introducing a mutable default
        (`cfg: dict = {}`) would silently share state across calls.

        This static inspection catches the regression at test time
        without needing per-call observable mutation (which the
        determinism test alone cannot catch since both calls would
        observe the same mutated default)."""
        import inspect
        adapters = [
            retrieve_cold_pitch_exemplars,
            retrieve_congrats_exemplars,
            retrieve_re_engagement_exemplars,
            retrieve_reply_exemplars,
            retrieve_public_comment_exemplars,
        ]
        for adapter in adapters:
            sig = inspect.signature(adapter)
            for name, p in sig.parameters.items():
                if p.default is inspect.Parameter.empty:
                    continue
                assert not isinstance(p.default, (list, dict, set)), (
                    f"{adapter.__name__}: kwarg {name} has mutable "
                    f"default {p.default!r} (type {type(p.default).__name__}) "
                    f"— Python mutable-default-kwarg footgun. Use "
                    f"None default + body-time construction instead."
                )

    # -- Composition with the event-payload factory ------------------

    def test_adapter_result_feeds_payload_factory(self, tmp_path):
        """The adapters return :class:`VoiceExemplar` instances that
        feed directly into
        :func:`build_voice_exemplar_retrieved_payload` — the per-
        register dispatch composes with the event emit shape per
        ADR-0039 D189 (no per-adapter event shape divergence)."""
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        exemplars = retrieve_cold_pitch_exemplars(
            "draft",
            k=2,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        payload = build_voice_exemplar_retrieved_payload(
            person_id="p1",
            query="draft",
            exemplars=exemplars,
            channel=DEFAULT_CHANNEL_FOR_COLD_PITCH,
            register="cold-pitch",
        )
        assert payload["type"] == "voice_exemplar_retrieved"
        assert payload["register"] == "cold-pitch"
        assert payload["channel"] == "email"
        assert len(payload["exemplars"]) >= 1

    # -- k kwarg ------------------------------------------------------

    def test_all_adapters_k_kwarg_caps_result_size(self, tmp_path):
        """ADR-0040 D194 — the ``k`` kwarg passes through (mirrors
        the shared primitive's contract per ADR-0038 D179)."""
        # cold-pitch/email has 1 substantive sample by default →
        # k=10 should cap at 1; k=0 caps at 0
        corpus_dir = self._corpus_all_registers_and_channels(tmp_path)
        r10 = retrieve_cold_pitch_exemplars(
            "draft",
            k=10,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        r0 = retrieve_cold_pitch_exemplars(
            "draft",
            k=0,
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        assert len(r10) == 1
        assert len(r0) == 0

    # -- Empty filter result handling --------------------------------

    def test_adapter_returns_empty_when_no_register_match(self, tmp_path):
        """The adapter returns ``[]`` (not raises) when the per-
        register filter yields zero matches — mirrors the shared
        primitive's empty-filter behavior per ADR-0038 D179."""
        # Empty corpus
        samples = []
        embeddings = np.zeros((0, 3), dtype=np.float32)
        corpus_dir = _make_corpus(tmp_path, samples, embeddings)
        result = retrieve_cold_pitch_exemplars(
            "draft",
            corpus_dir=corpus_dir,
            embed_fn=self._embed_fn(),
            now=self._now(),
        )
        assert result == []


# ---------------------------------------------------------------------------
# Per-register voice-fidelity threshold loader — Pillar F Week 4
# (ADR-0041 D199-D205 + ADR-0038 D184(a))
# ---------------------------------------------------------------------------


class TestVoiceThresholds:
    """Per-register voice-fidelity threshold loader per ADR-0041 D199-D205.

    Mirrors :class:`TestLoadWeights` in ``tests/test_tier_assignment.py``
    per ADR-0035 D163's operator-tunable YAML loader precedent. Strict
    per-register key requirement per D202; out-of-range refuse-loud
    per D201; process-cache posture per D203.
    """

    def _write_thresholds(
        self,
        path: Path,
        thresholds: dict | None = None,
        *,
        wrap_in_top_level: bool = True,
    ) -> Path:
        """Build a per-test thresholds YAML at ``path``.

        ``thresholds=None`` writes the framework defaults; pass a dict
        to override per-test. ``wrap_in_top_level=False`` writes the
        thresholds dict directly without the required ``thresholds:``
        key (used to test the missing-top-level-key validator).
        """
        if thresholds is None:
            thresholds = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
        if wrap_in_top_level:
            payload = {"thresholds": thresholds}
        else:
            payload = thresholds
        path.write_text(yaml.safe_dump(payload))
        return path

    @pytest.fixture(autouse=True)
    def _clear_voice_threshold_cache(self):
        """Per ADR-0041 D203 — the process-cache amortizes per-process
        invocations. Tests inject their own paths; clear the cache
        before AND after each test to avoid cross-test pollution.
        """
        voice_corpus._VOICE_THRESHOLDS_CACHE.clear()
        yield
        voice_corpus._VOICE_THRESHOLDS_CACHE.clear()

    # -- Happy path ---------------------------------------------------

    def test_loads_operator_config_when_present(self, tmp_path):
        """ADR-0041 D199 — operator config at the supplied path is loaded."""
        op_path = self._write_thresholds(tmp_path / "voice_thresholds.yml")
        thresholds = load_voice_thresholds(op_path)
        assert thresholds == DEFAULT_VOICE_THRESHOLD_PER_REGISTER

    def test_operator_override_takes_precedence_over_defaults(self, tmp_path):
        """ADR-0041 D199 — the operator's YAML values override the
        framework defaults; the loader returns the operator's values."""
        op_path = self._write_thresholds(
            tmp_path / "voice_thresholds.yml",
            thresholds={
                "cold-pitch":     0.85,
                "congrats":       0.50,
                "re-engagement":  0.80,
                "reply":          0.75,
                "public-comment": 0.55,
            },
        )
        thresholds = load_voice_thresholds(op_path)
        assert thresholds["cold-pitch"] == 0.85
        assert thresholds["congrats"] == 0.50
        assert thresholds["re-engagement"] == 0.80
        assert thresholds["reply"] == 0.75
        assert thresholds["public-comment"] == 0.55

    def test_falls_back_to_default_template_when_operator_path_absent(
        self, tmp_path, capsys,
    ):
        """ADR-0041 D199 — missing operator config → falls back to the
        default-shipped template + emits stderr warning per ADR-0035 D164's
        operator-readable diagnostic discipline.
        """
        absent_path = tmp_path / "absent.yml"
        assert not absent_path.exists()
        thresholds = load_voice_thresholds(absent_path)
        # Default-shipped template carries the framework defaults.
        assert thresholds == DEFAULT_VOICE_THRESHOLD_PER_REGISTER
        # Stderr warning was emitted naming the missing path + the
        # fallback template path.
        captured = capsys.readouterr()
        assert "operator-tuned voice thresholds not found" in captured.err
        assert str(absent_path) in captured.err
        assert "voice_thresholds.example.yml" in captured.err

    def test_default_template_path_resolves_relative_to_module(self):
        """ADR-0041 D199 — the default-shipped template ships with
        every clone at ``config-template/voice_thresholds.example.yml``
        (sibling of ``tier_weights.example.yml`` per ADR-0035 D163)."""
        path = voice_corpus._default_thresholds_template_path()
        assert path.name == "voice_thresholds.example.yml"
        assert path.parent.name == "config-template"
        assert path.exists(), (
            "default-shipped template missing — Week 4 ship integrity broken"
        )

    # -- Refuse-loud on malformed config -----------------------------

    def test_rejects_non_dict_top_level(self, tmp_path):
        """ADR-0041 D199 — YAML must be a top-level dict."""
        bad_path = tmp_path / "bad.yml"
        bad_path.write_text("- just a list\n- not a dict\n")
        with pytest.raises(ValueError, match="must be a top-level dict"):
            load_voice_thresholds(bad_path)

    def test_rejects_missing_thresholds_top_level_key(self, tmp_path):
        """ADR-0041 D199 — YAML must have a ``thresholds:`` top-level key."""
        bad_path = self._write_thresholds(
            tmp_path / "bad.yml",
            thresholds=DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
            wrap_in_top_level=False,
        )
        with pytest.raises(
            ValueError, match="must have a top-level ``thresholds:`` dict"
        ):
            load_voice_thresholds(bad_path)

    def test_rejects_thresholds_when_not_a_dict(self, tmp_path):
        """ADR-0041 D199 — ``thresholds:`` value must be a dict."""
        bad_path = tmp_path / "bad.yml"
        bad_path.write_text("thresholds: not-a-dict\n")
        with pytest.raises(
            ValueError, match="must have a top-level ``thresholds:`` dict"
        ):
            load_voice_thresholds(bad_path)

    def test_rejects_malformed_yaml(self, tmp_path):
        """ADR-0041 D199 — malformed YAML surfaces as yaml.YAMLError."""
        bad_path = tmp_path / "bad.yml"
        bad_path.write_text("thresholds: {cold-pitch: 0.7\n")  # missing }
        with pytest.raises(yaml.YAMLError):
            load_voice_thresholds(bad_path)

    # -- Strict per-register key requirement (D202) ------------------

    def test_rejects_unknown_register_key(self, tmp_path):
        """ADR-0041 D202 — unknown register key (typo, deprecated value,
        or operator-invented register) surfaces loudly. The REGISTERS
        enum is closed-set per ADR-0038 D178."""
        bad_path = self._write_thresholds(
            tmp_path / "bad.yml",
            thresholds={
                **DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                "introduction": 0.65,  # not in REGISTERS
            },
        )
        with pytest.raises(
            ValueError, match="unknown register key"
        ) as exc:
            load_voice_thresholds(bad_path)
        assert "introduction" in str(exc.value)

    def test_rejects_missing_required_register_key(self, tmp_path):
        """ADR-0041 D202 — strict per-register key requirement; missing
        keys raise ValueError (partial config is operator misconfiguration
        that must surface loudly per the legal-and-brand-liability
        invariant per ADR-0038 D184)."""
        partial = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
        del partial["public-comment"]
        bad_path = self._write_thresholds(
            tmp_path / "bad.yml", thresholds=partial,
        )
        with pytest.raises(
            ValueError, match="missing required register key"
        ) as exc:
            load_voice_thresholds(bad_path)
        assert "public-comment" in str(exc.value)

    def test_rejects_when_all_register_keys_missing(self, tmp_path):
        """ADR-0041 D202 — empty ``thresholds:`` dict refuses-loud."""
        bad_path = self._write_thresholds(
            tmp_path / "bad.yml", thresholds={},
        )
        with pytest.raises(
            ValueError, match="missing required register key"
        ):
            load_voice_thresholds(bad_path)

    # -- Out-of-range threshold values (D201) ------------------------

    def test_rejects_threshold_above_one(self, tmp_path):
        """ADR-0041 D201 — thresholds MUST be in [0.0, 1.0]; values > 1.0
        raise ValueError."""
        bad_path = self._write_thresholds(
            tmp_path / "bad.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 1.5},
        )
        with pytest.raises(ValueError, match="out of range"):
            load_voice_thresholds(bad_path)

    def test_rejects_threshold_below_zero(self, tmp_path):
        """ADR-0041 D201 — thresholds MUST be in [0.0, 1.0]; values < 0.0
        raise ValueError."""
        bad_path = self._write_thresholds(
            tmp_path / "bad.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "congrats": -0.1},
        )
        with pytest.raises(ValueError, match="out of range"):
            load_voice_thresholds(bad_path)

    def test_accepts_threshold_at_zero(self, tmp_path):
        """ADR-0041 D201 — boundary 0.0 is valid (operator-deliberate
        choice — every draft passes the gate)."""
        op_path = self._write_thresholds(
            tmp_path / "voice_thresholds.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.0},
        )
        thresholds = load_voice_thresholds(op_path)
        assert thresholds["cold-pitch"] == 0.0

    def test_accepts_threshold_at_one(self, tmp_path):
        """ADR-0041 D201 — boundary 1.0 is valid (operator-deliberate
        choice — only perfect-match drafts pass the gate)."""
        op_path = self._write_thresholds(
            tmp_path / "voice_thresholds.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "reply": 1.0},
        )
        thresholds = load_voice_thresholds(op_path)
        assert thresholds["reply"] == 1.0

    def test_rejects_non_numeric_threshold(self, tmp_path):
        """ADR-0041 D201 — non-numeric threshold values raise ValueError
        with an operator-readable diagnostic (not a Python TypeError
        traceback deep inside the comparison code)."""
        bad_path = self._write_thresholds(
            tmp_path / "bad.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": "high"},
        )
        with pytest.raises(ValueError, match="not.*valid float"):
            load_voice_thresholds(bad_path)

    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_rejects_bool_threshold_value(self, tmp_path, bad_bool):
        """ADR-0041 D201 — bool values caught explicitly. Python's
        ``bool`` is an ``int`` subclass; ``True`` would coerce to 1.0
        + pass the [0.0, 1.0] range check silently; ``False`` would
        coerce to 0.0 + pass the inclusive lower-bound silently. Both
        directions of the footgun are pinned per Week 4 follow-up P3-1
        (the original test covered only True; False is the equally
        dangerous path — silently accepts EVERY draft for the
        register).
        """
        bad_path = self._write_thresholds(
            tmp_path / f"bad_{bad_bool}.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": bad_bool},
        )
        with pytest.raises(ValueError, match="is a bool"):
            load_voice_thresholds(bad_path)

    def test_coerces_int_threshold_to_float(self, tmp_path):
        """ADR-0041 D201 — integer values (e.g., ``0`` or ``1``) coerce
        to float; the loader's return type is ``dict[str, float]``."""
        op_path = self._write_thresholds(
            tmp_path / "voice_thresholds.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 1, "congrats": 0},
        )
        thresholds = load_voice_thresholds(op_path)
        assert thresholds["cold-pitch"] == 1.0
        assert isinstance(thresholds["cold-pitch"], float)
        assert thresholds["congrats"] == 0.0
        assert isinstance(thresholds["congrats"], float)

    # -- cfg= kwarg passthrough (D199 precedence) --------------------

    def test_cfg_voice_thresholds_path_takes_precedence_over_default(
        self, tmp_path,
    ):
        """ADR-0041 D199 — precedence: explicit kwarg > cfg.voice.thresholds_path
        > DEFAULT_VOICE_THRESHOLDS_PATH. With kwarg None, the cfg path
        wins."""
        op_path = self._write_thresholds(
            tmp_path / "cfg-driven.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.42},
        )
        thresholds = load_voice_thresholds(
            None, cfg={"voice": {"thresholds_path": str(op_path)}},
        )
        assert thresholds["cold-pitch"] == 0.42

    def test_explicit_kwarg_takes_precedence_over_cfg(self, tmp_path):
        """ADR-0041 D199 — explicit ``thresholds_path`` kwarg trumps
        ``cfg.voice.thresholds_path``."""
        kwarg_path = self._write_thresholds(
            tmp_path / "kwarg.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.11},
        )
        cfg_path = self._write_thresholds(
            tmp_path / "cfg.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.99},
        )
        thresholds = load_voice_thresholds(
            kwarg_path,
            cfg={"voice": {"thresholds_path": str(cfg_path)}},
        )
        assert thresholds["cold-pitch"] == 0.11

    # -- Process-cache posture (D203) --------------------------------

    def test_process_cache_amortizes_repeat_loads_for_same_path(self, tmp_path):
        """ADR-0041 D203 — repeat invocations against the same resolved
        path hit the cache; only the first call parses YAML.

        Verifies via mid-test mutation of the YAML file: cached result
        does NOT reflect the post-cache edit (matches the existing
        ``_load_config`` posture per the loader's docstring).
        """
        op_path = self._write_thresholds(
            tmp_path / "voice_thresholds.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.55},
        )
        first = load_voice_thresholds(op_path)
        assert first["cold-pitch"] == 0.55

        # Mutate the YAML; the cache should still return the original.
        self._write_thresholds(
            op_path,
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.99},
        )
        second = load_voice_thresholds(op_path)
        assert second["cold-pitch"] == 0.55, (
            "process-cache should mask mid-process file edits per D203"
        )

    def test_process_cache_is_per_resolved_path(self, tmp_path):
        """ADR-0041 D203 — cache key is the resolved-path string; loads
        against different paths are independent (do NOT collide).

        Per Week 4 follow-up P3-4: the test verifies per-path
        ISOLATION via mid-test mutation. The initial-load assertion
        (different paths return different values) would pass even
        with a single-slot cache that evicts on every new path; the
        mutation phase verifies a's cache slot is INTACT after b's
        load + a's file change. Combined with
        :meth:`test_process_cache_amortizes_repeat_loads_for_same_path`
        this pins the full per-path-slot semantics.
        """
        a_path = self._write_thresholds(
            tmp_path / "a.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.10},
        )
        b_path = self._write_thresholds(
            tmp_path / "b.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.90},
        )
        a = load_voice_thresholds(a_path)
        b = load_voice_thresholds(b_path)
        assert a["cold-pitch"] == 0.10
        assert b["cold-pitch"] == 0.90

        # Mutate a.yml + re-load via a_path; cache slot for a_path
        # is INTACT (not evicted by b's load) → still returns 0.10
        # despite the file now carrying 0.77. Proves the two paths
        # have independent cache slots, not a single-slot cache.
        self._write_thresholds(
            a_path,
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.77},
        )
        a_again = load_voice_thresholds(a_path)
        assert a_again["cold-pitch"] == 0.10, (
            "per-path cache slot eviction detected — a_path's slot "
            "was evicted by b_path's load (D203 requires per-path "
            "isolation, not a single-slot cache)"
        )
        # b_path's slot also intact across the a mutation.
        b_again = load_voice_thresholds(b_path)
        assert b_again["cold-pitch"] == 0.90

    def test_loader_returns_a_defensive_copy(self, tmp_path):
        """ADR-0041 D203 — caller mutations to the returned dict do NOT
        contaminate the process-cache. The cache + the returned dict
        are independent (defensive-copy pattern mirrors
        :func:`_load_config`'s yaml.safe_load fresh-parse pattern)."""
        op_path = self._write_thresholds(tmp_path / "voice_thresholds.yml")
        first = load_voice_thresholds(op_path)
        first["cold-pitch"] = 999.0  # caller mutation
        second = load_voice_thresholds(op_path)
        assert second["cold-pitch"] == 0.70

    def test_fallback_to_template_caches_under_template_path_not_operator_path(
        self, tmp_path, capsys,
    ):
        """Week 4 follow-up P2-1 — when the operator's path doesn't
        exist, the loader falls back to the template + caches the
        result under the TEMPLATE path (not the absent operator path).

        Regression barrier: the pre-fix behavior cached the template-
        derived data under the absent operator path, so a long-lived
        process where the operator later created the operator file
        mid-run would continue to get template data silently (the
        cache hit suppressed the re-check). Post-fix: a fresh process
        re-evaluates the operator path naturally (no stale-tagged
        cache entry).

        This test pins:
        * Per-call WARNING for the absent operator path (no cache hit
          suppressing it on the first call).
        * The cache key after a fallback IS the template path's
          string, NOT the absent operator path's string.
        """
        absent_path = tmp_path / "absent.yml"
        assert not absent_path.exists()
        result = load_voice_thresholds(absent_path)
        assert result == DEFAULT_VOICE_THRESHOLD_PER_REGISTER
        captured = capsys.readouterr()
        assert "operator-tuned voice thresholds not found" in captured.err

        # The cache key MUST be the template path, NOT the absent
        # operator path. Pre-fix this would have been
        # str(absent_path); post-fix it's str(template_path).
        template_path = voice_corpus._default_thresholds_template_path()
        assert str(template_path) in voice_corpus._VOICE_THRESHOLDS_CACHE
        assert str(absent_path) not in voice_corpus._VOICE_THRESHOLDS_CACHE

    # -- Default-shipped template loads cleanly ----------------------

    def test_default_shipped_template_loads_cleanly(self):
        """ADR-0041 D200 — the default-shipped template at
        ``config-template/voice_thresholds.example.yml`` MUST pass the
        loader's strict gate; framework ship integrity test."""
        template_path = voice_corpus._default_thresholds_template_path()
        thresholds = load_voice_thresholds(template_path)
        assert thresholds == DEFAULT_VOICE_THRESHOLD_PER_REGISTER


class TestGetVoiceThresholdForRegister:
    """Per-register threshold lookup helper per ADR-0041 D204."""

    @pytest.fixture(autouse=True)
    def _clear_voice_threshold_cache(self):
        voice_corpus._VOICE_THRESHOLDS_CACHE.clear()
        yield
        voice_corpus._VOICE_THRESHOLDS_CACHE.clear()

    def _write_defaults(self, tmp_path: Path) -> Path:
        op_path = tmp_path / "voice_thresholds.yml"
        op_path.write_text(yaml.safe_dump({
            "thresholds": dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER),
        }))
        return op_path

    def test_returns_per_register_value(self, tmp_path):
        """ADR-0041 D204 — happy path; reads the operator-supplied
        per-register threshold."""
        op_path = self._write_defaults(tmp_path)
        for register, expected in DEFAULT_VOICE_THRESHOLD_PER_REGISTER.items():
            actual = get_voice_threshold_for_register(
                register, thresholds_path=op_path,
            )
            assert actual == expected, (
                f"register {register!r}: expected {expected}, got {actual}"
            )

    def test_refuses_unknown_register(self, tmp_path):
        """ADR-0041 D204 — refuses-loud on unknown register name (closed
        enum per ADR-0038 D178); the error names the closed-set."""
        op_path = self._write_defaults(tmp_path)
        with pytest.raises(ValueError, match="not in REGISTERS"):
            get_voice_threshold_for_register(
                "introduction", thresholds_path=op_path,
            )

    def test_propagates_loader_errors(self, tmp_path):
        """ADR-0041 D204 — the underlying loader's ValueError (missing
        required register key) propagates unchanged."""
        partial = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
        del partial["cold-pitch"]
        op_path = tmp_path / "voice_thresholds.yml"
        op_path.write_text(yaml.safe_dump({"thresholds": partial}))
        with pytest.raises(ValueError, match="missing required register key"):
            get_voice_threshold_for_register(
                "congrats", thresholds_path=op_path,
            )

    def test_cfg_passthrough(self, tmp_path):
        """ADR-0041 D204 — ``cfg=`` kwarg passes through to the loader."""
        op_path = tmp_path / "cfg-driven.yml"
        op_path.write_text(yaml.safe_dump({
            "thresholds": {**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                           "cold-pitch": 0.33},
        }))
        value = get_voice_threshold_for_register(
            "cold-pitch",
            cfg={"voice": {"thresholds_path": str(op_path)}},
        )
        assert value == 0.33

    def test_accepts_all_five_registers(self, tmp_path):
        """ADR-0041 D204 — every register in REGISTERS is a valid lookup
        target; structural symmetry pins.

        Per Week 4 follow-up P3-3: the assertion pins the EXACT
        per-register value (not just type + range). The weaker
        assertion (``isinstance + 0.0 <= value <= 1.0``) would pass
        for a regression where the helper returned the wrong
        register's threshold for every input (e.g.,
        ``return thresholds["cold-pitch"]`` ignoring the ``register``
        kwarg) — every returned value is still a float in range, but
        the per-register lookup is broken.
        """
        op_path = self._write_defaults(tmp_path)
        for register in REGISTERS:
            value = get_voice_threshold_for_register(
                register, thresholds_path=op_path,
            )
            expected = DEFAULT_VOICE_THRESHOLD_PER_REGISTER[register]
            assert value == expected, (
                f"register {register!r}: got {value!r}, "
                f"expected {expected!r}"
            )
            assert isinstance(value, float)
            assert 0.0 <= value <= 1.0

    def test_no_embed_fn_kwarg_per_p3_b_carry_forward(self):
        """ADR-0041 D205 + Week 2 audit P3-B carry-forward — the
        threshold loader + helper do NOT expose an ``embed_fn`` kwarg.
        The loader doesn't encode anything; the TEST-ONLY ``embed_fn``
        seam belongs to retrieval surfaces (per ADR-0040 D197) only.
        """
        import inspect
        loader_sig = inspect.signature(load_voice_thresholds)
        helper_sig = inspect.signature(get_voice_threshold_for_register)
        assert "embed_fn" not in loader_sig.parameters
        assert "embed_fn" not in helper_sig.parameters


# ---------------------------------------------------------------------------
# Pillar F Week 5 — `thresholds` CLI subcommand (ADR-0042 D206-D211)
# ---------------------------------------------------------------------------


class TestCLIThresholds:
    """Per-register threshold inspection CLI per ADR-0042 D206-D211.

    Three nested subcommands under ``thresholds`` per D206:

    * ``thresholds list [--json] [--thresholds-path PATH]`` — operator
      readable per-register threshold table + JSON-form ``{"thresholds":
      {...}, "_meta": {"source_path", "is_fallback"}}`` per D207.
    * ``thresholds get <register> [--json] [--thresholds-path PATH]`` —
      single-register lookup; refuses-loud on unknown register at
      argparse-choices level (D210).
    * ``thresholds dump [--json] [--thresholds-path PATH]`` — literal
      YAML re-emit (default) or JSON form per D208; ``_meta`` is OMITTED
      so operators pipe to ``~/.outreach-factory/voice_thresholds.yml``
      without polluting the config.

    Test isolation: tests set ``OUTREACH_FACTORY_CONFIG`` env to a
    nonexistent path so :func:`_load_config` returns ``{}`` + doesn't
    pull the operator's real ``config.yml``. Each test passes
    ``--thresholds-path`` explicitly to control which YAML the loader
    reads. Subprocess invocations create new processes per test, so
    the per-process ``_VOICE_THRESHOLDS_CACHE`` is fresh per test
    naturally — no autouse fixture needed.
    """

    def _write_thresholds_yaml(
        self,
        path: Path,
        thresholds: dict | None = None,
    ) -> Path:
        if thresholds is None:
            thresholds = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
        path.write_text(yaml.safe_dump({"thresholds": thresholds}))
        return path

    def _env(self, tmp_path: Path) -> dict:
        """Build a subprocess env with OUTREACH_FACTORY_CONFIG pointing
        at a nonexistent path so the CLI's :func:`_load_config` returns
        ``{}`` instead of pulling the operator's real config.yml."""
        import os as _os
        absent_cfg = tmp_path / "nonexistent_config.yml"
        return {**_os.environ, "OUTREACH_FACTORY_CONFIG": str(absent_cfg)}

    # -- Help + discoverability --------------------------------------

    def test_help_lists_thresholds_subcommand(self):
        """D206 — top-level --help advertises the new ``thresholds``
        subcommand alongside the existing retrieve / validate / rebuild
        commands."""
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        assert "thresholds" in proc.stdout
        # Pre-existing subcommands continue to appear (no regression).
        for sub in ("retrieve", "validate", "rebuild"):
            assert sub in proc.stdout

    def test_thresholds_help_lists_three_actions(self):
        """D206 — ``thresholds --help`` advertises all three nested
        actions (list / get / dump)."""
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        for action in ("list", "get", "dump"):
            assert action in proc.stdout

    # -- `thresholds list` -------------------------------------------

    def test_thresholds_list_json_happy_path(self, tmp_path):
        """D207 — ``thresholds list --json`` returns the per-register
        dict + ``_meta.source_path`` + ``_meta.is_fallback=False`` when
        the operator-supplied YAML is present."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "list",
             "--thresholds-path", str(op_path),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["thresholds"] == DEFAULT_VOICE_THRESHOLD_PER_REGISTER
        assert out["_meta"]["source_path"] == str(op_path)
        assert out["_meta"]["is_fallback"] is False

    def test_thresholds_list_text_happy_path(self, tmp_path):
        """D207 — ``thresholds list`` (no --json) emits an
        operator-readable per-register table + the source path naming
        provenance. Pins: every register appears + its threshold value
        appears + the source path is named."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
            thresholds={
                "cold-pitch":     0.81,
                "congrats":       0.62,
                "re-engagement":  0.73,
                "reply":          0.71,
                "public-comment": 0.59,
            },
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "list",
             "--thresholds-path", str(op_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        for register in REGISTERS:
            assert register in proc.stdout
        for value in ("0.81", "0.62", "0.73", "0.71", "0.59"):
            assert value in proc.stdout
        assert str(op_path) in proc.stdout

    def test_thresholds_list_fallback_marks_is_fallback_true(
        self, tmp_path,
    ):
        """D207 — when the operator-supplied path is absent, the loader
        falls back to the default template + the CLI reports
        ``_meta.is_fallback=True`` + ``_meta.source_path`` = the template
        path. The library's stderr warning is preserved (operator
        actionable diagnostic per ADR-0035 D164)."""
        absent_path = tmp_path / "absent.yml"
        assert not absent_path.exists()
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "list",
             "--thresholds-path", str(absent_path),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["_meta"]["is_fallback"] is True
        assert "voice_thresholds.example.yml" in out["_meta"]["source_path"]
        # The library's stderr fallback warning surfaces through the
        # CLI per ADR-0035 D164's operator-readable diagnostic posture.
        assert "operator-tuned voice thresholds not found" in proc.stderr

    def test_thresholds_list_refuses_loud_on_missing_required_key(
        self, tmp_path,
    ):
        """D207 — loader's strict per-register key requirement per
        ADR-0041 D202 surfaces via non-zero exit code + ERROR message on
        stderr (not a traceback). The error names the missing register."""
        partial = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
        del partial["congrats"]
        bad_path = self._write_thresholds_yaml(
            tmp_path / "bad.yml", thresholds=partial,
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "list",
             "--thresholds-path", str(bad_path),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 2
        assert "ERROR" in proc.stderr
        assert "congrats" in proc.stderr

    def test_thresholds_list_refuses_loud_on_out_of_range(self, tmp_path):
        """D207 — out-of-range threshold value per ADR-0041 D201 surfaces
        via non-zero exit code + ERROR diagnostic on stderr."""
        bad_path = self._write_thresholds_yaml(
            tmp_path / "bad.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 1.5},
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "list",
             "--thresholds-path", str(bad_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 2
        assert "ERROR" in proc.stderr
        assert "out of range" in proc.stderr

    # -- `thresholds get` --------------------------------------------

    def test_thresholds_get_json_happy_path(self, tmp_path):
        """D207 — ``thresholds get <register> --json`` emits
        ``{"register", "threshold", "_meta"}`` with the per-register
        value + provenance metadata."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
            thresholds={**DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
                        "cold-pitch": 0.88},
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "get", "cold-pitch",
             "--thresholds-path", str(op_path),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["register"] == "cold-pitch"
        assert out["threshold"] == 0.88
        assert out["_meta"]["source_path"] == str(op_path)
        assert out["_meta"]["is_fallback"] is False

    def test_thresholds_get_text_happy_path(self, tmp_path):
        """D207 — ``thresholds get <register>`` (no --json) emits an
        operator-readable two-field text form naming the register + the
        threshold + the source path."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "get", "re-engagement",
             "--thresholds-path", str(op_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        assert "re-engagement" in proc.stdout
        assert "0.72" in proc.stdout
        assert str(op_path) in proc.stdout

    def test_thresholds_get_per_register_correct_value(self, tmp_path):
        """D207 — structural symmetry: ``thresholds get`` returns the
        EXACT per-register threshold for every register in REGISTERS
        (not just type + range). Mirrors the Week 4 follow-up P3-2 fix
        for the library-level helper test."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        for register, expected in DEFAULT_VOICE_THRESHOLD_PER_REGISTER.items():
            proc = subprocess.run(
                [sys.executable, str(VOICE_CORPUS_SCRIPT),
                 "thresholds", "get", register,
                 "--thresholds-path", str(op_path),
                 "--json"],
                capture_output=True, text=True, timeout=30,
                env=self._env(tmp_path),
            )
            assert proc.returncode == 0, (
                f"register {register!r} subcommand failed: {proc.stderr}"
            )
            out = json.loads(proc.stdout)
            assert out["register"] == register
            assert out["threshold"] == expected, (
                f"register {register!r}: got {out['threshold']!r}, "
                f"expected {expected!r}"
            )

    def test_thresholds_get_refuses_unknown_register(self, tmp_path):
        """D210 — unknown register at the argparse-choices level
        (closed enum per ADR-0038 D178). Surfaces via argparse's
        ``invalid choice`` error + non-zero exit code BEFORE the loader
        is invoked.

        The closed-enum protection prevents the misleading "missing
        required register key" diagnostic the loader would otherwise
        surface (the loader's error names ALL missing keys; the CLI's
        argparse error names the specific unknown register the operator
        typed)."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "get", "introduction",
             "--thresholds-path", str(op_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode != 0
        assert "invalid choice" in proc.stderr
        assert "introduction" in proc.stderr

    def test_thresholds_get_fallback_marks_is_fallback_true(
        self, tmp_path,
    ):
        """D207 — fallback to template propagates through ``get`` per the
        same provenance rule as ``list``.

        Per Week 5 follow-up P3-2: assert the FULL provenance shape
        (both ``is_fallback=True`` AND ``source_path`` resolves to the
        template). The pre-fix assertion only verified the boolean;
        a regression where ``is_fallback`` was correctly set but
        ``source_path`` was an arbitrary string (e.g., still pointing
        at the absent operator path) would pass the test while
        violating the D207 provenance contract. Mirrors the symmetric
        provenance assertion at
        :meth:`test_thresholds_list_fallback_marks_is_fallback_true`.
        """
        absent_path = tmp_path / "absent.yml"
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "get", "cold-pitch",
             "--thresholds-path", str(absent_path),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["register"] == "cold-pitch"
        assert out["threshold"] == 0.70
        assert out["_meta"]["is_fallback"] is True
        # Per Week 5 follow-up P3-2 — the pre-fix assertion stopped at
        # the boolean; the full provenance contract per D207 requires
        # the source_path to be the template path under fallback.
        assert "voice_thresholds.example.yml" in out["_meta"]["source_path"]

    # -- `thresholds dump` -------------------------------------------

    def test_thresholds_dump_yaml_default_loader_compatible(self, tmp_path):
        """D208 — ``thresholds dump`` (no --json) emits literal YAML
        re-emit. The output MUST round-trip through
        :func:`load_voice_thresholds` (operators pipe to file +
        re-read)."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
            thresholds={
                "cold-pitch":     0.81,
                "congrats":       0.62,
                "re-engagement":  0.73,
                "reply":          0.71,
                "public-comment": 0.59,
            },
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "dump",
             "--thresholds-path", str(op_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr

        # Round-trip: parse stdout as YAML; load via the library loader.
        parsed = yaml.safe_load(proc.stdout)
        assert "thresholds" in parsed
        assert set(parsed["thresholds"].keys()) == REGISTERS

        round_trip_path = tmp_path / "round_trip.yml"
        round_trip_path.write_text(proc.stdout)
        # Library loader accepts the dumped YAML cleanly.
        loaded = load_voice_thresholds(round_trip_path)
        assert loaded == {
            "cold-pitch":     0.81,
            "congrats":       0.62,
            "re-engagement":  0.73,
            "reply":          0.71,
            "public-comment": 0.59,
        }

    def test_thresholds_dump_yaml_omits_meta_field(self, tmp_path):
        """D208 — YAML re-emit MUST NOT carry a ``_meta`` top-level key
        (operators pipe ``thresholds dump > voice_thresholds.yml`` to
        bootstrap their config; a ``_meta`` key would pollute the
        loader's strict-gate). Validated by re-parsing the YAML output
        + verifying only ``thresholds`` is at top level."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "dump",
             "--thresholds-path", str(op_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        parsed = yaml.safe_load(proc.stdout)
        assert set(parsed.keys()) == {"thresholds"}, (
            f"dump YAML must carry ONLY the ``thresholds:`` top-level "
            f"key (operators pipe to file); got extra keys: "
            f"{set(parsed.keys()) - {'thresholds'}}"
        )

    def test_thresholds_dump_json_happy_path(self, tmp_path):
        """D208 — ``thresholds dump --json`` emits the per-register dict
        wrapped in the ``thresholds:`` top-level key (same shape as the
        YAML default, JSON-encoded)."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "dump",
             "--thresholds-path", str(op_path),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["thresholds"] == DEFAULT_VOICE_THRESHOLD_PER_REGISTER

    def test_thresholds_dump_json_omits_meta_field(self, tmp_path):
        """D208 — JSON form mirrors the YAML form's no-_meta posture so
        operators get a consistent shape across the two output modes."""
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "dump",
             "--thresholds-path", str(op_path),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert "_meta" not in out, (
            f"dump --json must NOT carry a ``_meta`` key (consistent "
            f"with YAML form's no-_meta posture per D208); got: "
            f"{set(out.keys())}"
        )

    def test_thresholds_dump_fallback_round_trip_to_template(
        self, tmp_path,
    ):
        """D208 — fallback path: ``dump`` of the template (when operator
        config absent) MUST round-trip cleanly. Operators bootstrapping
        a fresh config via ``thresholds dump > ~/.outreach-factory/
        voice_thresholds.yml`` get the template defaults."""
        absent_path = tmp_path / "absent.yml"
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "dump",
             "--thresholds-path", str(absent_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        round_trip_path = tmp_path / "bootstrapped.yml"
        round_trip_path.write_text(proc.stdout)
        loaded = load_voice_thresholds(round_trip_path)
        assert loaded == DEFAULT_VOICE_THRESHOLD_PER_REGISTER

    # -- Week 5 follow-up regression barriers ------------------------

    def test_thresholds_list_relative_path_returns_absolute_source_path(
        self, tmp_path,
    ):
        """Week 5 follow-up P2-1 — when ``--thresholds-path`` is a
        RELATIVE path (e.g., ``./voice_thresholds.yml``), the JSON
        ``_meta.source_path`` MUST be absolute per D207 ("source_path
        is the absolute path to the YAML file the loader actually
        read"). Pre-fix the helper returned the unresolved (relative)
        path; cross-tenant audit tooling concatenating two audit results
        where one run used a relative path + another used an absolute
        path got non-matching provenance for the same config file,
        silently breaking drift detection.

        Test isolation: subprocess runs with ``cwd=tmp_path`` so the
        relative path ``voice_thresholds.yml`` resolves to
        ``tmp_path / voice_thresholds.yml`` at the subprocess'
        working directory.
        """
        self._write_thresholds_yaml(tmp_path / "voice_thresholds.yml")
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "list",
             "--thresholds-path", "voice_thresholds.yml",  # RELATIVE
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
            cwd=str(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        import os
        assert os.path.isabs(out["_meta"]["source_path"]), (
            f"_meta.source_path MUST be absolute per D207; got "
            f"relative path: {out['_meta']['source_path']!r}. The "
            f"helper at _resolve_thresholds_cli_paths must call "
            f".resolve() on the non-fallback path so cross-tenant "
            f"audit tooling sees consistent provenance regardless of "
            f"the operator's working directory at CLI-invocation time."
        )

    def test_thresholds_dump_yaml_preserves_canonical_order(
        self, tmp_path,
    ):
        """Week 5 follow-up P3-1 — the ``dump`` YAML output's key order
        MUST match the SKILL.md register table's canonical order per
        ADR-0040 D193 + ADR-0042 D208. The round-trip-cleanly test
        (``test_thresholds_dump_yaml_default_loader_compatible``) only
        verifies the loader accepts the dumped YAML; YAML key order is
        semantically irrelevant to the loader, so a regression that
        switches ``sort_keys=False`` to ``sort_keys=True`` would still
        pass the round-trip test while silently breaking the
        operator-readable canonical-order contract per D208.

        Pins the canonical order via the YAML's raw key sequence (not
        the parsed dict — Python 3.7+ dict preserves insertion order
        but the test asserts the YAML emit's literal order). The
        canonical order: cold-pitch → congrats → re-engagement → reply
        → public-comment per the SKILL.md register table.
        """
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "dump",
             "--thresholds-path", str(op_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr

        # Extract per-register key order from raw YAML output by
        # scanning lines under the ``thresholds:`` top-level key for
        # ``<register>:`` patterns. Avoids relying on yaml.safe_load's
        # dict ordering (Python 3.7+ preserves insertion order but
        # this test should pin the YAML literal's order independent of
        # the parser's behavior).
        emitted_order: list[str] = []
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "thresholds:":
                continue
            # Indented per-register lines have shape "register: value".
            for register in REGISTERS:
                if stripped.startswith(f"{register}:"):
                    emitted_order.append(register)
                    break

        expected_order = list(DEFAULT_VOICE_THRESHOLD_PER_REGISTER.keys())
        assert emitted_order == expected_order, (
            f"dump YAML's per-register key order MUST match SKILL.md "
            f"canonical order per ADR-0040 D193 + ADR-0042 D208; got "
            f"{emitted_order!r}, expected {expected_order!r}. A "
            f"future contributor flipping sort_keys=False to True (or "
            f"reformatting DEFAULT_VOICE_THRESHOLD_PER_REGISTER to a "
            f"different declaration order) breaks the canonical-order "
            f"contract."
        )

    def test_thresholds_list_text_registers_in_alphabetical_order(
        self, tmp_path,
    ):
        """Week 5 follow-up P3-3 — pin the ``list`` text-table's
        ALPHABETICAL register order so the asymmetry with ``dump``'s
        canonical order is operator-deliberate + regression-protected.
        The text mode iterates ``sorted(REGISTERS)`` for easier
        operator-scan presentation; the YAML emit at ``dump`` iterates
        ``DEFAULT_VOICE_THRESHOLD_PER_REGISTER`` for SKILL.md-canonical
        round-trip preservation. Both orders are operator-deliberate;
        unifying them silently breaks one or the other contract.
        """
        op_path = self._write_thresholds_yaml(
            tmp_path / "voice_thresholds.yml",
        )
        proc = subprocess.run(
            [sys.executable, str(VOICE_CORPUS_SCRIPT),
             "thresholds", "list",
             "--thresholds-path", str(op_path)],
            capture_output=True, text=True, timeout=30,
            env=self._env(tmp_path),
        )
        assert proc.returncode == 0, proc.stderr

        # Extract per-register row order from text output by scanning
        # for lines beginning with each register name (each row's
        # first column carries the register name).
        emitted_order: list[str] = []
        for line in proc.stdout.splitlines():
            for register in REGISTERS:
                if line.startswith(register):
                    emitted_order.append(register)
                    break

        expected_order = sorted(REGISTERS)
        assert emitted_order == expected_order, (
            f"list text-mode row order MUST be alphabetical (operator "
            f"scan convenience); got {emitted_order!r}, expected "
            f"{expected_order!r}. The asymmetric ``dump`` YAML order "
            f"is intentionally canonical per ADR-0040 D193 + ADR-0042 "
            f"D208; both orders are operator-deliberate."
        )

    # -- TEST-ONLY embed_fn carry-forward verification ---------------

    def test_thresholds_cli_has_no_embed_fn_flag(self):
        """ADR-0042 D211 + ADR-0041 D205 + Week 2 audit P3-B
        carry-forward — the CLI MUST NOT surface an ``--embed-fn`` flag
        on any of the three ``thresholds`` subcommands. The CLI is
        read-only against YAML; no encoder runs; the seam is N/A at
        this surface per the per-week reviewer checklist row.

        Verified by inspecting per-subcommand --help output."""
        for action in ("list", "get", "dump"):
            argv = [sys.executable, str(VOICE_CORPUS_SCRIPT),
                    "thresholds", action, "--help"]
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=30,
            )
            assert proc.returncode == 0
            assert "--embed-fn" not in proc.stdout, (
                f"thresholds {action} --help advertises --embed-fn; "
                "the TEST-ONLY embed_fn seam MUST NOT surface on the "
                "CLI per ADR-0040 D197 + ADR-0042 D211"
            )
