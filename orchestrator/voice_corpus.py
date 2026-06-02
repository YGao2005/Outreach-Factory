"""Pillar F Week 2 — embedding-retrieval primitive.

Per ADR-0038 D178 + D179 + D181 (Pillar F foundation) + ADR-0039
(this week's design). The primitive REPLACES the heuristic in
:mod:`voice_retrieve` with a structured per-call entry point that
surfaces voice-corpus exemplars filtered by ``register`` +
``channel`` + ``is_substantive_reply``, scored by cosine
similarity * recency multiplier, deterministic-clock-controllable
for test reproducibility, and validated against a canonical
per-sample schema. Per-register thin adapters land in subsequent
weeks per ADR-0038 D181's per-register-symmetry pattern; the
shared primitive ships in this Week 2 commit.

Module shape (mirrors :mod:`discovery_dedup` + :mod:`email_verification_cache`
+ :mod:`tier_assignment` + :mod:`discovery_lineage` per the
per-primitive flat-module convention per ADR-0036 D166):

* :class:`VoiceExemplar` — frozen dataclass; per-sample record.
  Construction-time invariants per ADR-0038 D178 (refuse-loud on
  missing/empty/enum-violation). Mirrors
  :class:`discovery_lineage.DiscoveryLineage`'s ``__post_init__``
  pattern.
* :class:`ValidationResult` — frozen dataclass returned by
  :func:`validate_corpus_sample`. Aggregates ``ok`` + ``errors``
  so operators see all schema violations in one validator pass.
* :class:`VoiceCorpusMetadataMismatch` — raised when the corpus
  ``metadata.json`` diverges from the runtime (model name,
  schema version, or corpus_count). R026 mitigation per D179.
* :func:`validate_corpus_sample` — strict schema gate per ADR-0038
  D178. Required fields + enum membership for ``register`` /
  ``channel`` + ISO 8601 UTC ``date``.
* :func:`retrieve_voice_exemplars` — per-call entry point per
  ADR-0038 D179. Loads the corpus + metadata + verifies
  metadata-on-load + applies filters + computes cosine *
  recency-multiplier + returns top-K :class:`VoiceExemplar`
  instances.
* :func:`build_voice_exemplar_retrieved_payload` — event-shape
  factory per ADR-0038 D182. ``voice_exemplar_retrieved`` event
  carries ``person_id`` + ``query_hash`` (NOT raw query — privacy)
  + per-exemplar ``(exemplar_id, score)`` + ``channel`` (per
  channel-on-every-event invariant per ADR-0014 D33) + ``register``
  + ``_emitted_by``.
* :func:`rebuild_corpus` — re-embed-and-write per ADR-0038 D179
  R026 mitigation. Operators invoke via CLI ``rebuild`` subcommand
  OR via the ``rebuild_on_mismatch=True`` retrieve kwarg.

Pillar F Week 3 per-register adapters (per ADR-0040 D192-D198 —
five thin free-function adapters at the module level matching the
``/draft-outreach`` SKILL.md register table):

* :func:`retrieve_cold_pitch_exemplars` — cold-pitch register; defaults
  ``channel="email"``; biases ``is_substantive_reply=True``.
* :func:`retrieve_congrats_exemplars` — congrats register; defaults
  ``channel="linkedin-dm"``.
* :func:`retrieve_re_engagement_exemplars` — re-engagement register;
  defaults ``channel="email"``.
* :func:`retrieve_reply_exemplars` — reply register; channel REQUIRED
  (no default) per the SKILL.md's "match inbound channel" rule.
* :func:`retrieve_public_comment_exemplars` — public-comment register;
  defaults ``channel="linkedin-comment"``.

Each per-register adapter is a thin wrapper over
:func:`retrieve_voice_exemplars`; the per-register channel default
constants live at the module level (:data:`DEFAULT_CHANNEL_FOR_COLD_PITCH`
+ :data:`DEFAULT_CHANNEL_FOR_CONGRATS` +
:data:`DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT` +
:data:`DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT`).

Per ADR-0038 D178 §Existing-operator seed: Week 2 does NOT enforce
the new ``register`` + ``channel`` schema fields on legacy corpora.
The retrieval primitive's filter treats missing values as
"all-register" / "all-channel" (the legacy sample passes through
any filter). New corpora MUST validate-clean via
:func:`validate_corpus_sample`; the gate is operator-deliberate.

CLI surface (mirrors :mod:`discovery_dedup` + :mod:`email_verification_cache`):

::

    python orchestrator/voice_corpus.py retrieve --query <text> \\
                                                 [--k N] \\
                                                 [--register <reg>] \\
                                                 [--channel <ch>] \\
                                                 [--is-substantive-reply] \\
                                                 [--apply] [--json]
    python orchestrator/voice_corpus.py validate --corpus-dir <path> \\
                                                 [--json]
    python orchestrator/voice_corpus.py rebuild  --corpus-dir <path> \\
                                                 [--embed-model <model>]

The ``--apply`` flag controls whether the
``voice_exemplar_retrieved`` event is appended to the ledger
(live mode) or just reported (dry-run mode — the default). The
dry-run default mirrors :mod:`policy`'s ``simulate`` posture:
read-only by default; explicit opt-in for state-mutation.

Backwards-compat: :mod:`voice_retrieve` is preserved through
Week 8+ per ADR-0038 §Existing-operator seed. Operators opt in to
the new primitive via ``voice.use_embedding_primitive: true`` in
``~/.outreach-factory/config.yml`` (default ``false`` at Week 2;
default ``true`` at Week 8+ when the per-register adapters ship).
The ``/draft-outreach`` SKILL.md's Phase 4 invocation reads the
flag + dispatches accordingly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import yaml


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Per ADR-0038 D178 — frozen enum of voice-corpus registers. Closed-set
# matches the ``/draft-outreach`` SKILL.md register table; future
# additions require an ADR amendment + a vault migration to retag
# historical samples.
REGISTERS: frozenset[str] = frozenset({
    "cold-pitch",
    "congrats",
    "re-engagement",
    "reply",
    "public-comment",
})


# Per ADR-0038 D178 + ADR-0014 D33 — the four-channel closed enum.
# Inherits the Pillar C channel set; future channels extend per the
# ADR-0014 D34 extension trajectory.
CHANNELS: frozenset[str] = frozenset({
    "email",
    "linkedin-dm",
    "linkedin-comment",
    "twitter-dm",
})


# Per ADR-0010 D17 — every Pillar event carries an ``_emitted_by``
# marker for operator-facing filterability. Pillar F's voice-corpus
# primitive marker (consumed by
# :func:`build_voice_exemplar_retrieved_payload` + the cross-pillar
# surface audit's literal-string predicate).
EMITTED_BY: str = "voice_corpus"


# Per ADR-0038 D179 — default sentence-transformers model. Local-CPU
# + zero-per-call-cost. Operators override via
# ``voice.embed_model`` in ``~/.outreach-factory/config.yml``.
DEFAULT_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"


# Per ADR-0038 D179 — top-K default matches the pre-existing
# :mod:`voice_retrieve` heuristic + the ``/draft-outreach`` SKILL.md
# Phase 4 contract.
DEFAULT_TOP_K: int = 5


# Per ADR-0038 D178 + D179 — the corpus schema version. Incremented
# when the per-sample shape changes in a backwards-incompatible way
# (e.g., a required field is renamed; an enum's domain narrows).
SCHEMA_VERSION: int = 1


# Per :mod:`voice_retrieve` precedent — the per-year recency
# multiplier. Pinned here so the cross-pillar audit + the test
# corpus reference a single source of truth.
RECENT_BIAS_PER_YEAR: float = 0.03


# Default operator-private corpus location per ADR-0038 D178 (b).
DEFAULT_CORPUS_DIR: Path = (
    Path.home() / ".outreach-factory" / "voice-corpus"
)


# Per ADR-0040 D195 — per-register channel defaults pinned at module
# level so the cross-pillar audit + the SKILL.md register table
# (lines 339-345) + the per-register adapter docstrings reference a
# single source of truth. Values match the SKILL.md register table's
# "Channel default" column at Week 3 ship time; future operator-
# tunable per-register overrides land at Pillar F Week 6+ via
# ``~/.outreach-factory/voice_thresholds.yml`` IF demand
# materializes (operator-deferred at Week 3).
#
# Note: there is no ``DEFAULT_CHANNEL_FOR_REPLY`` — the reply
# register's channel is operator-supplied per the SKILL.md's "match
# inbound channel" rule. The :func:`retrieve_reply_exemplars`
# adapter raises ``ValueError`` when ``channel=None`` per ADR-0040
# D194 + D195.
DEFAULT_CHANNEL_FOR_COLD_PITCH: str = "email"
DEFAULT_CHANNEL_FOR_CONGRATS: str = "linkedin-dm"
DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT: str = "email"
DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT: str = "linkedin-comment"


# Per ADR-0041 D199 + ADR-0038 D184(a) — the operator-tunable
# per-register voice-fidelity threshold YAML path. Operators copy
# from ``config-template/voice_thresholds.example.yml`` (see
# :func:`_default_thresholds_template_path`) + tune as their corpus
# grows. The framework treats the file as an opaque dict; YAML-load
# errors fail loud at primitive-invocation time. Mirrors
# :data:`tier_assignment.DEFAULT_TIER_WEIGHTS_PATH` per ADR-0035 D163.
DEFAULT_VOICE_THRESHOLDS_PATH: Path = (
    Path.home() / ".outreach-factory" / "voice_thresholds.yml"
)


# Per ADR-0041 D200 + ADR-0038 D184(a) — default per-register
# voice-fidelity thresholds calibrated against the reference operator's curated corpus
# at Pillar F Week 4 ship time. The framework ships sensible defaults;
# operators tune at their cadence via the YAML template.
#
# Each threshold is a per-draft float in [0.0, 1.0] representing the
# minimum voice-fidelity score (cosine similarity × per-year recency
# multiplier, weighted-average over top-K corpus exemplars per the
# fidelity-scoring primitive landing at Pillar F Week 8+) for a
# draft in the named register to advance to ``ready``. Drafts below
# the threshold get re-drafted (Layer 1 fidelity-scoring gate per
# the Week 8+ trajectory).
#
# Per-register calibration trajectory: the defaults at Week 4 are
# the binding text from ADR-0038 D184(a). At Week 8+ when the
# fidelity-scoring primitive lands + the per-corpus per-register
# distribution becomes measurable, operators MAY recalibrate against
# their corpus' fidelity-score distribution. The default values
# reflect the reference operator's curated corpus's per-register fidelity at Pillar F
# Week 4 ship; operators with different corpora tune at their cadence.
#
# Asymmetric-failure-cost calculus per ADR-0038 D184(a): a
# false-positive (the gate blocks a true-voice draft) costs the
# operator one re-draft; a false-negative (the gate accepts an
# AI-flavored draft) costs the operator brand fidelity. The default
# thresholds bias toward false-positive at the framework default;
# operators with deep curated corpora tune upward.
DEFAULT_VOICE_THRESHOLD_PER_REGISTER: dict[str, float] = {
    "cold-pitch":     0.70,
    "congrats":       0.65,
    "re-engagement":  0.72,
    "reply":          0.70,
    "public-comment": 0.60,
}


# ISO 8601 UTC timestamp shape per ADR-0036 D167 (re-used). Accepted:
# ``YYYY-MM-DDTHH:MM:SSZ`` + fractional seconds + ``+00:00`` explicit
# UTC offset. Rejected: naive timestamps + non-UTC offsets.
_ISO_8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$",
)


# Process-cached sentence-transformers model — loaded lazily on first
# call (~1-2s); subsequent calls reuse. Per ADR-0038 D179 §Design
# decisions trade-off (process-cache vs per-call) — the process
# cache amortizes the load cost across the agent's per-draft loop.
_MODEL_CACHE: dict = {}


# Per ADR-0041 D203 — process-cached per-register threshold dict
# keyed by resolved-path string. The YAML parse is amortized across
# per-process invocations (matches the :data:`_MODEL_CACHE` pattern).
# Cache invalidation semantics: operator edits to
# ``~/.outreach-factory/voice_thresholds.yml`` mid-process are NOT
# picked up until the next process start — same posture as the
# existing :func:`_load_config` loader.
_VOICE_THRESHOLDS_CACHE: dict[str, dict[str, float]] = {}


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _is_iso8601_utc(value: object) -> bool:
    """True if ``value`` is a non-empty string matching ISO 8601 UTC.

    Naive timestamps + non-UTC offsets are rejected (mirrors
    :func:`discovery_lineage._is_iso8601_utc`).
    """
    return isinstance(value, str) and bool(_ISO_8601_UTC_RE.match(value))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VoiceCorpusMetadataMismatch(RuntimeError):
    """Raised when the corpus' ``metadata.json`` diverges from runtime.

    Per ADR-0038 D179 R026 (operator-corpus split across multi-machine)
    mitigation. The cache sidecar carries ``embed_model`` +
    ``embed_version`` + ``schema_version`` + ``corpus_count``; load
    refuses-loud when any field diverges from the runtime expectation.
    Operators resolve via the ``rebuild`` CLI subcommand OR by
    passing ``rebuild_on_mismatch=True`` to
    :func:`retrieve_voice_exemplars`.
    """


# ---------------------------------------------------------------------------
# VoiceExemplar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoiceExemplar:
    """Per-sample voice-corpus record per ADR-0038 D178.

    Construction-time invariants (mirrors
    :class:`discovery_lineage.DiscoveryLineage.__post_init__`):

    * :attr:`id`: non-empty string (whitespace-stripped).
    * :attr:`date`: ISO 8601 UTC.
    * :attr:`body`: non-empty string (whitespace-stripped).
    * :attr:`register`: ``None`` (legacy) OR member of
      :data:`REGISTERS` (validated).
    * :attr:`channel`: ``None`` (legacy) OR member of
      :data:`CHANNELS` (validated).
    * :attr:`year`: integer (for the ``RECENT_BIAS`` multiplier).
    * :attr:`voice_score_baseline`: ``None`` OR float in
      ``[0.0, 1.0]``.
    * :attr:`score`: ``None`` (corpus load) OR float (retrieval
      result).

    Legacy ``register`` / ``channel`` ``None`` posture per ADR-0038
    D178 §Existing-operator seed — pre-Pillar-F samples lacking
    the fields are tolerated by the retrieval primitive; the per-
    register filter treats ``None`` as "any register" (passes
    through any filter). New corpora MUST pass
    :func:`validate_corpus_sample`'s strict gate; the construction-
    time tolerance is for backwards-compat ONLY.
    """

    id: str
    date: str
    body: str
    register: str | None
    channel: str | None
    year: int
    subject: str | None = None
    to: list | None = None
    tags: list | None = None
    is_substantive_reply: bool | None = None
    voice_score_baseline: float | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.id, str) and self.id.strip()):
            raise ValueError(
                f"id must be a non-empty string per ADR-0038 D178; "
                f"got {self.id!r}"
            )
        if not _is_iso8601_utc(self.date):
            raise ValueError(
                f"date must be ISO 8601 UTC "
                f"(YYYY-MM-DDTHH:MM:SSZ or fractional / +00:00) per "
                f"ADR-0038 D178; got {self.date!r}"
            )
        if not (isinstance(self.body, str) and self.body.strip()):
            raise ValueError(
                f"body must be a non-empty string per ADR-0038 D178; "
                f"got {self.body!r}"
            )
        if self.register is not None and self.register not in REGISTERS:
            raise ValueError(
                f"register {self.register!r} not in REGISTERS "
                f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum is "
                f"closed-set + construction-time-validated"
            )
        if self.channel is not None and self.channel not in CHANNELS:
            raise ValueError(
                f"channel {self.channel!r} not in CHANNELS "
                f"{sorted(CHANNELS)!r}; per ADR-0038 D178 + ADR-0014 D33 "
                f"the enum is closed-set"
            )
        if not isinstance(self.year, int) or isinstance(self.year, bool):
            raise ValueError(
                f"year must be int per ADR-0038 D178; got "
                f"{type(self.year).__name__}={self.year!r}"
            )
        if self.voice_score_baseline is not None:
            v = self.voice_score_baseline
            # ``bool`` is a subclass of ``int``; reject explicitly so
            # ``voice_score_baseline=True`` does not silently pass as
            # a valid float score (mirrors the ``year`` bool-rejection
            # invariant + the ADR-0039 D186 "float in [0.0, 1.0]"
            # text). Per Pillar F Week 2 follow-up P3-2.
            if isinstance(v, bool):
                raise ValueError(
                    f"voice_score_baseline must be float in [0.0, 1.0] "
                    f"per ADR-0038 D178; got bool={v!r} (bool is a "
                    f"Python int subclass but not a valid score)"
                )
            if not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
                raise ValueError(
                    f"voice_score_baseline must be float in [0.0, 1.0] "
                    f"per ADR-0038 D178; got {v!r}"
                )


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of :func:`validate_corpus_sample`.

    Aggregates ``ok`` (overall verdict) + ``errors`` (per-violation
    operator-readable messages). Multiple violations surface in a
    single pass so operators fix all together rather than per-call.
    """

    ok: bool
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# validate_corpus_sample
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS: tuple[str, ...] = (
    "id", "date", "body", "register", "channel", "year",
)


def validate_corpus_sample(sample: dict) -> ValidationResult:
    """Strict schema gate per ADR-0038 D178.

    Validates the canonical per-sample shape. Required fields:
    ``id`` + ``date`` + ``body`` + ``register`` + ``channel`` +
    ``year``. Optional fields (``subject`` / ``to`` / ``tags`` /
    ``is_substantive_reply`` / ``voice_score_baseline``) are
    silently accepted; unknown extra keys are tolerated for
    forward-compat with future Pillar F schema extensions.

    Refuse-loud aggregation: every violation surfaces in
    :attr:`ValidationResult.errors`; operators see all schema
    drift in one validator pass.

    Note (Pillar F Week 2 follow-up P3-3): ``register`` and
    ``channel`` MUST be members of :data:`REGISTERS` /
    :data:`CHANNELS`. **JSON ``null`` is rejected** even though
    the :class:`VoiceExemplar` dataclass tolerates ``None`` for
    legacy-corpora backwards-compat — the strict validator is the
    gate for NEW corpora being tagged per ADR-0038 D178; operators
    partially migrating a corpus should set valid register +
    channel values before running the validator. The asymmetry is
    intentional per ADR-0038 §Existing-operator seed.

    Args:
        sample: The per-sample dict (typically one entry from the
            ``index.json`` array).

    Returns:
        :class:`ValidationResult` with ``ok=True`` + empty
        ``errors`` on a clean sample, OR ``ok=False`` + one error
        message per violation.

    Raises:
        TypeError: if ``sample`` is not a dict. The validator's
            contract is per-sample-dict; callers iterating an
            ``index.json`` array dispatch on the type.
    """
    if not isinstance(sample, dict):
        raise TypeError(
            f"validate_corpus_sample expects a dict; got "
            f"{type(sample).__name__}={sample!r}"
        )

    errors: list[str] = []

    for fname in _REQUIRED_FIELDS:
        if fname not in sample:
            errors.append(f"required field {fname!r} is missing")

    if "id" in sample:
        v = sample["id"]
        if not (isinstance(v, str) and v.strip()):
            errors.append(
                f"field id must be a non-empty string; got {v!r}"
            )

    if "date" in sample:
        if not _is_iso8601_utc(sample["date"]):
            errors.append(
                f"field date must be ISO 8601 UTC "
                f"(YYYY-MM-DDTHH:MM:SSZ or fractional / +00:00); got "
                f"{sample['date']!r}"
            )

    if "body" in sample:
        v = sample["body"]
        if not (isinstance(v, str) and v.strip()):
            errors.append(
                f"field body must be a non-empty string; got {v!r}"
            )

    if "register" in sample:
        v = sample["register"]
        if v not in REGISTERS:
            errors.append(
                f"field register {v!r} not in REGISTERS "
                f"{sorted(REGISTERS)!r}"
            )

    if "channel" in sample:
        v = sample["channel"]
        if v not in CHANNELS:
            errors.append(
                f"field channel {v!r} not in CHANNELS "
                f"{sorted(CHANNELS)!r}"
            )

    if "year" in sample:
        v = sample["year"]
        if not isinstance(v, int) or isinstance(v, bool):
            errors.append(
                f"field year must be int; got "
                f"{type(v).__name__}={v!r}"
            )

    if "voice_score_baseline" in sample:
        v = sample["voice_score_baseline"]
        if v is not None:
            # ``bool`` is a subclass of ``int`` — symmetric with the
            # ``year`` rejection. Per Pillar F Week 2 follow-up P3-2.
            if isinstance(v, bool):
                errors.append(
                    f"field voice_score_baseline must be float in "
                    f"[0.0, 1.0]; got bool={v!r}"
                )
            elif not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
                errors.append(
                    f"field voice_score_baseline must be float in "
                    f"[0.0, 1.0]; got {v!r}"
                )

    return ValidationResult(ok=(not errors), errors=errors)


# ---------------------------------------------------------------------------
# Internal — corpus + metadata loading
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    """Load ``~/.outreach-factory/config.yml`` (or via
    ``$OUTREACH_FACTORY_CONFIG``). Returns empty dict on absence —
    operators may supply ``corpus_dir`` + ``embed_model`` directly
    to :func:`retrieve_voice_exemplars`.
    """
    p = Path(os.environ.get(
        "OUTREACH_FACTORY_CONFIG",
        "~/.outreach-factory/config.yml",
    )).expanduser()
    if not p.exists():
        return {}
    try:
        with p.open() as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _resolve_corpus_dir(
    corpus_dir: Path | None,
    cfg: dict | None,
) -> Path:
    if corpus_dir is not None:
        return Path(corpus_dir).expanduser()
    if cfg is None:
        cfg = _load_config()
    voice_cfg = cfg.get("voice") or {}
    cfg_dir = voice_cfg.get("corpus_dir")
    if cfg_dir:
        return Path(cfg_dir).expanduser()
    return DEFAULT_CORPUS_DIR


def _resolve_embed_model(
    embed_model: str | None,
    cfg: dict | None,
) -> str:
    if embed_model is not None:
        return embed_model
    if cfg is None:
        cfg = _load_config()
    voice_cfg = cfg.get("voice") or {}
    return voice_cfg.get("embed_model") or DEFAULT_EMBED_MODEL


def _default_embed_fn(embed_model: str) -> Callable[[str], np.ndarray]:
    """Return the process-cached sentence-transformers encoder.

    Lazy-loads on first call (~1-2s); subsequent calls reuse the
    cached model. Per ADR-0038 D179 §Design decisions — the
    process-cache amortizes the load cost across the agent's
    per-draft loop. Tests inject their own ``embed_fn`` to bypass
    this entirely.
    """
    cached = _MODEL_CACHE.get(embed_model)
    if cached is None:
        from sentence_transformers import SentenceTransformer
        cached = SentenceTransformer(embed_model)
        _MODEL_CACHE[embed_model] = cached
    model = cached

    def _encode(query: str) -> np.ndarray:
        return model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[0].astype(np.float32)

    return _encode


def _check_metadata(
    metadata: dict,
    *,
    expected_embed_model: str,
    expected_schema_version: int,
    expected_corpus_count: int,
) -> list[str]:
    """Compare cache metadata against the runtime expectation.

    Returns a list of mismatch descriptions (empty on a clean
    match). The caller raises :class:`VoiceCorpusMetadataMismatch`
    OR triggers rebuild based on the operator-controlled flag.
    """
    mismatches: list[str] = []
    cache_model = metadata.get("embed_model")
    if cache_model != expected_embed_model:
        mismatches.append(
            f"embed_model mismatch: cache={cache_model!r} "
            f"runtime={expected_embed_model!r}"
        )
    cache_schema = metadata.get("schema_version")
    if cache_schema != expected_schema_version:
        mismatches.append(
            f"schema_version mismatch: cache={cache_schema!r} "
            f"runtime={expected_schema_version!r}"
        )
    cache_count = metadata.get("corpus_count")
    if cache_count != expected_corpus_count:
        mismatches.append(
            f"corpus_count mismatch: cache={cache_count!r} "
            f"actual={expected_corpus_count!r}"
        )
    return mismatches


def _load_corpus(
    corpus_dir: Path,
) -> tuple[np.ndarray, list[dict], dict]:
    """Load ``embeddings.npy`` + ``index.json`` + ``metadata.json``.

    Raises :exc:`FileNotFoundError` per-file on absence with an
    operator-readable message; the cross-pillar audit's category 6
    pre-Pillar-F-corpora gate is the upstream check.
    """
    if not corpus_dir.exists():
        raise FileNotFoundError(
            f"voice-corpus directory not found: {corpus_dir} "
            f"(per ADR-0038 D178 the canonical location is "
            f"~/.outreach-factory/voice-corpus/; set voice.corpus_dir "
            f"in ~/.outreach-factory/config.yml to override)"
        )
    emb_path = corpus_dir / "embeddings.npy"
    if not emb_path.exists():
        raise FileNotFoundError(
            f"embeddings file not found: {emb_path} "
            f"(build via the existing voice/README.md path OR run "
            f"`python orchestrator/voice_corpus.py rebuild "
            f"--corpus-dir {corpus_dir}`)"
        )
    idx_path = corpus_dir / "index.json"
    if not idx_path.exists():
        raise FileNotFoundError(
            f"index.json not found: {idx_path} "
            f"(per ADR-0038 D178 the corpus directory carries "
            f"embeddings.npy + index.json + metadata.json)"
        )
    meta_path = corpus_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"metadata.json not found: {meta_path} "
            f"(per ADR-0038 D179 R026 mitigation; the sidecar pins "
            f"embed_model + schema_version + corpus_count; rebuild "
            f"with `python orchestrator/voice_corpus.py rebuild "
            f"--corpus-dir {corpus_dir}`)"
        )

    embeddings = np.load(emb_path)
    index = json.loads(idx_path.read_text())
    metadata = json.loads(meta_path.read_text())
    return embeddings, index, metadata


def _coerce_to_exemplar(sample: dict, *, score: float | None = None) -> VoiceExemplar:
    """Lenient construction of a :class:`VoiceExemplar` from a
    corpus sample dict.

    Per ADR-0038 D178 §Existing-operator seed — pre-Pillar-F samples
    lacking ``register`` / ``channel`` are tolerated (default to
    ``None`` so the per-register filter treats them as "any
    register"). The strict gate is :func:`validate_corpus_sample`.

    Tolerant of:
      * Missing optional fields → ``None``
      * Missing ``register`` / ``channel`` → ``None``
      * Unknown register / channel → ``None`` (legacy operator's
        free-form tags); strict mode catches via the validator
    """
    raw_register = sample.get("register")
    register = raw_register if raw_register in REGISTERS else None

    raw_channel = sample.get("channel")
    channel = raw_channel if raw_channel in CHANNELS else None

    raw_year = sample.get("year")
    if not isinstance(raw_year, int) or isinstance(raw_year, bool):
        # Best-effort derive from date if year missing/malformed.
        date_val = sample.get("date")
        try:
            raw_year = int(date_val[:4]) if isinstance(date_val, str) else 1970
        except (TypeError, ValueError):
            raw_year = 1970

    return VoiceExemplar(
        id=sample.get("id", ""),
        date=sample.get("date", ""),
        body=sample.get("body", ""),
        register=register,
        channel=channel,
        year=raw_year,
        subject=sample.get("subject"),
        to=sample.get("to"),
        tags=sample.get("tags"),
        is_substantive_reply=sample.get("is_substantive_reply"),
        voice_score_baseline=sample.get("voice_score_baseline"),
        score=score,
    )


# ---------------------------------------------------------------------------
# retrieve_voice_exemplars — the per-call entry point
# ---------------------------------------------------------------------------


def retrieve_voice_exemplars(
    query: str,
    *,
    k: int = DEFAULT_TOP_K,
    register: str | None = None,
    channel: str | None = None,
    is_substantive_reply: bool | None = None,
    now: datetime | None = None,
    corpus_dir: Path | None = None,
    embed_model: str | None = None,
    rebuild_on_mismatch: bool = False,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
) -> list[VoiceExemplar]:
    """Retrieve top-K voice-corpus exemplars per ADR-0038 D179.

    The shared retrieval primitive backed by per-register thin
    adapters (Week 4-8 per D181). Filters surface per-register /
    per-channel / per-substantive-reply slices; cosine similarity
    × per-year recency multiplier scores the result.

    Args:
        query: The draft text (or any text) to retrieve against.
            Embedded via ``embed_fn``; cosine-compared against the
            corpus.
        k: Number of exemplars to return (top-K post-filter). The
            returned list may be shorter than K when fewer
            samples match the filters.
        register: Optional filter. ``None`` returns all registers;
            non-``None`` MUST be in :data:`REGISTERS`. Legacy
            samples lacking ``register`` pass through (per D178
            §Existing-operator seed).
        channel: Optional filter. ``None`` returns all channels;
            non-``None`` MUST be in :data:`CHANNELS`. Legacy
            samples lacking ``channel`` pass through.
        is_substantive_reply: Optional filter. ``None`` returns
            both; ``True`` returns only samples flagged as having
            received a substantive reply (operator-stamped at
            corpus-build time per D178 — used by cold-pitch
            adapter to bias toward proven-effective exemplars).
        now: Deterministic-clock anchor per ADR-0031 D140 +
            ADR-0034 D156 + ADR-0035 D162 precedent. When supplied,
            the ``RECENT_BIAS`` multiplier uses ``now.year``
            instead of ``datetime.now(UTC).year``; per-test
            reproducibility is preserved.
        corpus_dir: Override the corpus location (defaults to
            ``cfg.voice.corpus_dir`` or :data:`DEFAULT_CORPUS_DIR`).
        embed_model: Override the model name used to encode the
            query + validate against the cache metadata. Defaults
            to ``cfg.voice.embed_model`` or :data:`DEFAULT_EMBED_MODEL`.
        rebuild_on_mismatch: When ``True`` and the cache metadata
            diverges from the runtime, rebuild the corpus
            (re-encode every sample + write new metadata) BEFORE
            proceeding with the lookup. Default ``False`` —
            refuse-loud per R026 mitigation; operators opt in
            deliberately via ``voice.rebuild_on_metadata_mismatch``
            in ``~/.outreach-factory/config.yml`` OR the
            ``--rebuild-on-mismatch`` CLI flag.
        cfg: Pre-loaded config dict; ``None`` triggers the standard
            ``~/.outreach-factory/config.yml`` load.
        embed_fn: Optional injected encoder. Tests pass a
            deterministic function to bypass the
            sentence-transformers load. Defaults to the
            process-cached :func:`_default_embed_fn`.

    Returns:
        List of :class:`VoiceExemplar` (length ``min(k, n_matches)``),
        ordered by descending score. Each carries a populated
        :attr:`VoiceExemplar.score`.

    Raises:
        ValueError: when ``register`` is non-``None`` but not in
            :data:`REGISTERS`, or ``channel`` is non-``None`` but
            not in :data:`CHANNELS`.
        FileNotFoundError: when the corpus directory or any of
            its files (``embeddings.npy`` / ``index.json`` /
            ``metadata.json``) is missing.
        :class:`VoiceCorpusMetadataMismatch`: when the cache's
            metadata diverges from the runtime AND
            ``rebuild_on_mismatch=False``.

    Side effects: NONE on the read path. The optional rebuild path
    writes ``embeddings.npy`` + ``metadata.json``.
    """
    if register is not None and register not in REGISTERS:
        raise ValueError(
            f"register filter {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r} per ADR-0038 D178"
        )
    if channel is not None and channel not in CHANNELS:
        raise ValueError(
            f"channel filter {channel!r} not in CHANNELS "
            f"{sorted(CHANNELS)!r} per ADR-0038 D178 + ADR-0014 D33"
        )

    resolved_dir = _resolve_corpus_dir(corpus_dir, cfg)
    resolved_model = _resolve_embed_model(embed_model, cfg)

    embeddings, index, metadata = _load_corpus(resolved_dir)

    mismatches = _check_metadata(
        metadata,
        expected_embed_model=resolved_model,
        expected_schema_version=SCHEMA_VERSION,
        expected_corpus_count=embeddings.shape[0],
    )
    if mismatches:
        if rebuild_on_mismatch:
            # Rebuild + reload using the supplied embed_fn (or
            # default). Per ADR-0038 D179 §R026 mitigation
            # `--rebuild-on-mismatch` operator-controlled path.
            rebuild_corpus(
                resolved_dir,
                embed_model=resolved_model,
                embed_fn=embed_fn,
            )
            embeddings, index, metadata = _load_corpus(resolved_dir)
        else:
            raise VoiceCorpusMetadataMismatch(
                "voice-corpus metadata.json diverges from runtime "
                "expectation: " + "; ".join(mismatches)
                + ". Either run `python orchestrator/voice_corpus.py "
                "rebuild --corpus-dir " + str(resolved_dir) + "` to "
                "re-embed the corpus, or set "
                "voice.rebuild_on_metadata_mismatch: true in "
                "~/.outreach-factory/config.yml + pass "
                "rebuild_on_mismatch=True (R026 mitigation per "
                "ADR-0038 D179)."
            )

    # Empty-corpus guard — the matmul `embeddings @ q_emb` requires
    # the embeddings array to have matching inner dimensions. An empty
    # corpus (post-rebuild of an empty `index.json`, or operator-side
    # corpus init before any samples land) ships `shape[0] == 0`; the
    # matmul against an arbitrary-dim query embedding raises ValueError
    # at runtime. Short-circuit to empty result — symmetric with the
    # filter-yields-nothing path below.
    if embeddings.shape[0] == 0:
        return []

    if embed_fn is None:
        embed_fn = _default_embed_fn(resolved_model)

    # Encode query + compute cosine. Embeddings are pre-normalized at
    # build time (the sentence-transformers `normalize_embeddings=True`
    # convention from voice_retrieve.py:110 — preserved at rebuild).
    q_emb = embed_fn(query).astype(np.float32)
    sims = embeddings @ q_emb

    # Recency multiplier per D179: anchored to `now.year`.
    if now is None:
        now = datetime.now(timezone.utc)
    anchor_year = now.year

    # Apply filters BEFORE scoring — operator-deliberate: the per-
    # register / per-channel filter is a precondition, not a
    # tiebreaker.
    filtered_indices: list[int] = []
    for i, sample in enumerate(index):
        if register is not None:
            sample_reg = sample.get("register")
            # Legacy samples (register missing/None) pass through any
            # filter per D178 §Existing-operator seed; non-None
            # mismatches filter out.
            if sample_reg is not None and sample_reg != register:
                continue
        if channel is not None:
            sample_ch = sample.get("channel")
            if sample_ch is not None and sample_ch != channel:
                continue
        if is_substantive_reply is not None:
            if bool(sample.get("is_substantive_reply")) != is_substantive_reply:
                continue
        filtered_indices.append(i)

    if not filtered_indices:
        return []

    # Compute per-sample year + recency multiplier for the surviving set.
    scored: list[tuple[int, float]] = []
    for i in filtered_indices:
        sample = index[i]
        sample_year = sample.get("year")
        if not isinstance(sample_year, int) or isinstance(sample_year, bool):
            # Best-effort derive from date (same fallback as
            # _coerce_to_exemplar) so legacy samples score.
            d = sample.get("date")
            try:
                sample_year = int(d[:4]) if isinstance(d, str) else 1970
            except (TypeError, ValueError):
                sample_year = 1970
        recency = 1.0 - (anchor_year - sample_year) * RECENT_BIAS_PER_YEAR
        cos = float(sims[i])
        scored.append((i, cos * recency))

    # Sort by descending score (stable to preserve insertion order on
    # ties — matches numpy argsort's stable behavior for equal keys).
    scored.sort(key=lambda pair: pair[1], reverse=True)

    if k <= 0:
        return []
    top = scored[:k]
    return [
        _coerce_to_exemplar(index[i], score=score)
        for i, score in top
    ]


# ---------------------------------------------------------------------------
# Per-register adapters — Pillar F Week 3 (ADR-0040 D192-D198)
# ---------------------------------------------------------------------------
#
# Five thin free-function adapters at the module level, one per register
# from the closed-set :data:`REGISTERS` (per ADR-0038 D178 + the
# ``/draft-outreach`` SKILL.md register table at lines 339-345). Each
# adapter delegates to :func:`retrieve_voice_exemplars` with the
# per-register ``register=`` value frozen + per-register ``channel=``
# default (per :data:`DEFAULT_CHANNEL_FOR_<REGISTER>`) + per-register
# ``is_substantive_reply=`` bias per the table at ADR-0040 D196.
#
# Symmetric signature across all five adapters per ADR-0040 D194 —
# adopters at Week 8+ (the SKILL.md Phase 4 per-register routing
# extension + the hallucination-detection primitive's per-register
# dispatch + the fidelity-scoring primitive's per-register
# calibration) consume the adapter set with one uniform call shape.
#
# The reply register is the lone asymmetry per ADR-0040 D194 + D195
# — its channel is operator-supplied per the SKILL.md's "match
# inbound channel" rule. The :func:`retrieve_reply_exemplars`
# adapter accepts ``channel: str | None = None`` (signature
# symmetry preserved) but raises ``ValueError`` when ``channel=None``
# at runtime (operator-deliberateness enforced).
#
# TEST-ONLY ``embed_fn`` injection seam per ADR-0040 D197 — each
# adapter's docstring labels the kwarg as TEST-ONLY (mirrors
# :func:`retrieve_voice_exemplars`'s docstring per ADR-0039 D188).
# The CLI does NOT surface a per-register subcommand at Week 3 —
# operators continue to invoke the shared primitive's CLI per
# ADR-0039 D191 with ``--register <reg> --channel <ch>``.


def retrieve_cold_pitch_exemplars(
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
) -> list[VoiceExemplar]:
    """Cold-pitch register adapter — biases toward proven-effective exemplars.

    Per ADR-0040 D192-D198 (the per-register adapter pattern). Thin
    wrapper over :func:`retrieve_voice_exemplars` that freezes
    ``register="cold-pitch"`` + defaults ``channel=`` to
    :data:`DEFAULT_CHANNEL_FOR_COLD_PITCH` (``"email"``) + biases
    ``is_substantive_reply=True`` per the SKILL.md's 5-touch
    sampling discipline (ADR-0038 D178).

    Cold-pitch is the highest-stakes register; biasing toward
    proven-effective exemplars (drafts that GOT a substantive reply)
    compounds voice fidelity for new cold-pitch drafts. Operators
    wanting an unbiased exemplar set call the shared primitive
    directly: ``retrieve_voice_exemplars(query, register="cold-pitch",
    is_substantive_reply=None, ...)``.

    Args:
        query: The draft text to retrieve against.
        k: Number of exemplars to return (top-K post-filter).
        channel: Override the per-register channel default. ``None``
            (the default) resolves to
            :data:`DEFAULT_CHANNEL_FOR_COLD_PITCH` (``"email"``).
            Operators may override (e.g., cold-pitch via LinkedIn
            DM for a prospect publishing LinkedIn DM as their
            preferred channel); the override path is this kwarg.
        now: Deterministic-clock anchor per ADR-0031 D140 +
            ADR-0034 D156 + ADR-0035 D162 precedent.
        corpus_dir: Override corpus location.
        embed_model: Override embedding model name.
        rebuild_on_mismatch: Operator-controlled R026 auto-rebuild
            per ADR-0038 D179.
        cfg: Pre-loaded config dict.
        embed_fn: TEST-ONLY injected encoder per ADR-0040 D197 +
            ADR-0039 D188. Tests pass a deterministic function to
            bypass the sentence-transformers load; the kwarg has
            no operator-facing CLI surface.

    Returns:
        List of :class:`VoiceExemplar` (length ``min(k, n_matches)``),
        ordered by descending score.

    Raises:
        ValueError: when ``channel`` is non-``None`` but not in
            :data:`CHANNELS` (per the shared primitive's filter
            validation).
    """
    return retrieve_voice_exemplars(
        query,
        k=k,
        register="cold-pitch",
        channel=(channel if channel is not None
                 else DEFAULT_CHANNEL_FOR_COLD_PITCH),
        is_substantive_reply=True,
        now=now,
        corpus_dir=corpus_dir,
        embed_model=embed_model,
        rebuild_on_mismatch=rebuild_on_mismatch,
        cfg=cfg,
        embed_fn=embed_fn,
    )


def retrieve_congrats_exemplars(
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
) -> list[VoiceExemplar]:
    """Congrats register adapter — short, no substantive-reply bias.

    Per ADR-0040 D192-D198. Thin wrapper over
    :func:`retrieve_voice_exemplars` that freezes
    ``register="congrats"`` + defaults ``channel=`` to
    :data:`DEFAULT_CHANNEL_FOR_CONGRATS` (``"linkedin-dm"``).

    Congrats often DON'T get replies (the prospect reads the
    message + moves on); requiring ``is_substantive_reply=True``
    would surface zero exemplars for many operators. The
    ``is_substantive_reply`` filter defaults to ``None`` per
    ADR-0040 D196.

    Args:
        query: The draft text to retrieve against.
        k: Number of exemplars to return.
        channel: Override the per-register channel default. ``None``
            resolves to :data:`DEFAULT_CHANNEL_FOR_CONGRATS`
            (``"linkedin-dm"``). Operators may override (e.g.,
            email-based congrats); the override path is this kwarg.
        now: Deterministic-clock anchor.
        corpus_dir: Override corpus location.
        embed_model: Override embedding model name.
        rebuild_on_mismatch: Operator-controlled R026 auto-rebuild.
        cfg: Pre-loaded config dict.
        embed_fn: TEST-ONLY injected encoder per ADR-0040 D197.

    Returns:
        List of :class:`VoiceExemplar` (length ``min(k, n_matches)``).

    Raises:
        ValueError: when ``channel`` is non-``None`` but not in
            :data:`CHANNELS`.
    """
    return retrieve_voice_exemplars(
        query,
        k=k,
        register="congrats",
        channel=(channel if channel is not None
                 else DEFAULT_CHANNEL_FOR_CONGRATS),
        is_substantive_reply=None,
        now=now,
        corpus_dir=corpus_dir,
        embed_model=embed_model,
        rebuild_on_mismatch=rebuild_on_mismatch,
        cfg=cfg,
        embed_fn=embed_fn,
    )


def retrieve_re_engagement_exemplars(
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
) -> list[VoiceExemplar]:
    """Re-engagement register adapter — email default, no reply bias.

    Per ADR-0040 D192-D198. Thin wrapper over
    :func:`retrieve_voice_exemplars` that freezes
    ``register="re-engagement"`` + defaults ``channel=`` to
    :data:`DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT` (``"email"``).

    Re-engagement reply patterns are varied; the framework does
    NOT bias ``is_substantive_reply`` at Week 3. Future per-corpus
    tuning may surface a bias signal at Pillar F Week 8+ (the
    per-register threshold loader's per-register bias kwarg).

    Args:
        query: The draft text to retrieve against.
        k: Number of exemplars to return.
        channel: Override the per-register channel default. ``None``
            resolves to :data:`DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT`
            (``"email"``).
        now: Deterministic-clock anchor.
        corpus_dir: Override corpus location.
        embed_model: Override embedding model name.
        rebuild_on_mismatch: Operator-controlled R026 auto-rebuild.
        cfg: Pre-loaded config dict.
        embed_fn: TEST-ONLY injected encoder per ADR-0040 D197.

    Returns:
        List of :class:`VoiceExemplar` (length ``min(k, n_matches)``).

    Raises:
        ValueError: when ``channel`` is non-``None`` but not in
            :data:`CHANNELS`.
    """
    return retrieve_voice_exemplars(
        query,
        k=k,
        register="re-engagement",
        channel=(channel if channel is not None
                 else DEFAULT_CHANNEL_FOR_RE_ENGAGEMENT),
        is_substantive_reply=None,
        now=now,
        corpus_dir=corpus_dir,
        embed_model=embed_model,
        rebuild_on_mismatch=rebuild_on_mismatch,
        cfg=cfg,
        embed_fn=embed_fn,
    )


def retrieve_reply_exemplars(
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
) -> list[VoiceExemplar]:
    """Reply register adapter — channel REQUIRED (no default).

    Per ADR-0040 D192-D198. Thin wrapper over
    :func:`retrieve_voice_exemplars` that freezes
    ``register="reply"``. The reply register is the lone
    asymmetry in the per-register adapter set per ADR-0040 D194 +
    D195 — its channel is operator-supplied per the SKILL.md
    register table's "match inbound channel" rule (line 344).
    The operator MUST supply ``channel=`` at call time; ``channel=None``
    raises :exc:`ValueError`.

    The signature shape stays symmetric with the other four
    adapters (``channel: str | None = None``) per ADR-0040 D194 —
    the asymmetry is enforced at runtime, not in the type
    signature. This preserves uniform per-register documentation +
    templated per-register routing code at Week 8+ (the SKILL.md
    Phase 4 per-register dispatch extension) at the cost of a
    runtime check vs a static type-check.

    Args:
        query: The draft text to retrieve against.
        k: Number of exemplars to return.
        channel: REQUIRED — the inbound channel the operator is
            replying to (per the SKILL.md register table's "match
            inbound channel" rule). ``None`` raises ValueError
            because the reply register has no framework default
            channel (the per-call channel is operator-deliberate).
        now: Deterministic-clock anchor.
        corpus_dir: Override corpus location.
        embed_model: Override embedding model name.
        rebuild_on_mismatch: Operator-controlled R026 auto-rebuild.
        cfg: Pre-loaded config dict.
        embed_fn: TEST-ONLY injected encoder per ADR-0040 D197.

    Returns:
        List of :class:`VoiceExemplar` (length ``min(k, n_matches)``).

    Raises:
        ValueError: when ``channel`` is ``None`` (reply register
            requires operator-supplied channel per ADR-0040 D194 +
            D195) OR when ``channel`` is non-``None`` but not in
            :data:`CHANNELS`.
    """
    if channel is None:
        raise ValueError(
            "retrieve_reply_exemplars requires an explicit channel= "
            "kwarg per ADR-0040 D194 + D195 + the /draft-outreach "
            "SKILL.md register table's 'match inbound channel' rule "
            "(line 344). The reply register has no framework default "
            "channel — pass channel=<email|linkedin-dm|linkedin-comment|"
            "twitter-dm> matching the inbound the operator is replying "
            "to."
        )
    return retrieve_voice_exemplars(
        query,
        k=k,
        register="reply",
        channel=channel,
        is_substantive_reply=None,
        now=now,
        corpus_dir=corpus_dir,
        embed_model=embed_model,
        rebuild_on_mismatch=rebuild_on_mismatch,
        cfg=cfg,
        embed_fn=embed_fn,
    )


def retrieve_public_comment_exemplars(
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
) -> list[VoiceExemplar]:
    """Public-comment register adapter — LinkedIn comment default.

    Per ADR-0040 D192-D198. Thin wrapper over
    :func:`retrieve_voice_exemplars` that freezes
    ``register="public-comment"`` + defaults ``channel=`` to
    :data:`DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT` (``"linkedin-comment"``).

    Public-comment exemplars don't have a "reply" semantics in the
    same sense as DM-based registers (the comment may receive
    reactions / replies on the thread but the framework's
    ``is_substantive_reply`` field is per-DM not per-thread). No
    per-register bias at Week 3 per ADR-0040 D196.

    Args:
        query: The draft text to retrieve against.
        k: Number of exemplars to return.
        channel: Override the per-register channel default. ``None``
            resolves to :data:`DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT`
            (``"linkedin-comment"``).
        now: Deterministic-clock anchor.
        corpus_dir: Override corpus location.
        embed_model: Override embedding model name.
        rebuild_on_mismatch: Operator-controlled R026 auto-rebuild.
        cfg: Pre-loaded config dict.
        embed_fn: TEST-ONLY injected encoder per ADR-0040 D197.

    Returns:
        List of :class:`VoiceExemplar` (length ``min(k, n_matches)``).

    Raises:
        ValueError: when ``channel`` is non-``None`` but not in
            :data:`CHANNELS`.
    """
    return retrieve_voice_exemplars(
        query,
        k=k,
        register="public-comment",
        channel=(channel if channel is not None
                 else DEFAULT_CHANNEL_FOR_PUBLIC_COMMENT),
        is_substantive_reply=None,
        now=now,
        corpus_dir=corpus_dir,
        embed_model=embed_model,
        rebuild_on_mismatch=rebuild_on_mismatch,
        cfg=cfg,
        embed_fn=embed_fn,
    )


# ---------------------------------------------------------------------------
# Per-register voice-fidelity threshold loader — Pillar F Week 4
# (ADR-0041 D199-D205 + ADR-0038 D184(a))
# ---------------------------------------------------------------------------
#
# Operator-tunable per-register voice-fidelity thresholds live at
# ``~/.outreach-factory/voice_thresholds.yml`` (the
# :data:`DEFAULT_VOICE_THRESHOLDS_PATH`). The framework ships a
# default-shipped template at ``config-template/voice_thresholds.example.yml``
# carrying the per-register default thresholds per
# :data:`DEFAULT_VOICE_THRESHOLD_PER_REGISTER`. Operators copy the
# template to their config path + tune as their corpus grows.
#
# The threshold infrastructure is the LOAD-BEARING substrate for:
#
# * Pillar F Week 6+ hallucination-detection primitive — per-claim
#   trace consults the per-register threshold for the operator-supplied
#   register (Layer 2-3 per ADR-0038 D180).
# * Pillar F Week 8+ fidelity-scoring primitive — per-draft fidelity
#   score gets compared against the per-register threshold per
#   ADR-0038 D184(a).
#
# Strict per-register key requirement per ADR-0041 D202 — the loader
# requires all five register keys to be present in the YAML; missing
# keys raise ValueError. Mirrors :func:`validate_corpus_sample`'s
# strict-gate posture per ADR-0039 D187 (the legal-and-brand-liability
# invariant per ADR-0038 D184 is downstream-load-bearing; partial
# config is operator misconfiguration that must surface loudly).
#
# Out-of-range threshold values per ADR-0041 D201 — each threshold
# MUST be a float in [0.0, 1.0]. Values outside the range raise
# ValueError at load time (refuse-loud at the boundary check).


def _default_thresholds_template_path() -> Path:
    """Return the path to the default-shipped voice-thresholds template.

    Resolved relative to this module's location (mirrors
    :func:`tier_assignment._default_template_path` per ADR-0035 D163)
    so the path works whether the framework is installed via clone
    or via a future PyPI distribution.
    """
    return (
        Path(__file__).resolve().parent.parent
        / "config-template" / "voice_thresholds.example.yml"
    )


def _resolve_thresholds_path(
    thresholds_path: Path | None,
    cfg: dict | None,
) -> Path:
    """Resolve the per-register threshold YAML path.

    Precedence: explicit ``thresholds_path`` kwarg > ``cfg.voice.thresholds_path`` >
    :data:`DEFAULT_VOICE_THRESHOLDS_PATH`. Mirrors
    :func:`_resolve_corpus_dir` + :func:`_resolve_embed_model` per
    ADR-0039 D188.

    Externalized as a private helper (vs the inline
    ``if weights_path is None: weights_path = DEFAULT_...`` pattern at
    :func:`tier_assignment.load_weights`) because the precedence chain
    has THREE levels here (kwarg → cfg → default) vs that loader's TWO
    (kwarg → default); the cfg passthrough is the third level
    introduced by D199 per ADR-0041 — operators configure
    ``voice.thresholds_path`` in ``~/.outreach-factory/config.yml``
    alongside the other ``voice.*`` fields.
    """
    if thresholds_path is not None:
        return Path(thresholds_path).expanduser()
    if cfg is None:
        cfg = _load_config()
    voice_cfg = cfg.get("voice") or {}
    cfg_path = voice_cfg.get("thresholds_path")
    if cfg_path:
        return Path(cfg_path).expanduser()
    return DEFAULT_VOICE_THRESHOLDS_PATH


def load_voice_thresholds(
    thresholds_path: Path | None = None,
    *,
    cfg: dict | None = None,
) -> dict[str, float]:
    """Load the per-register voice-fidelity threshold YAML config per ADR-0041 D199.

    The operator's config lives at :data:`DEFAULT_VOICE_THRESHOLDS_PATH`
    (``~/.outreach-factory/voice_thresholds.yml``). When the operator's
    config is absent, falls back to the default-shipped template at
    ``config-template/voice_thresholds.example.yml`` (with stderr
    warning per ADR-0035 D164's operator-readable diagnostic
    discipline mirrored from :func:`tier_assignment.load_weights`).

    The returned dict is per-process cached per ADR-0041 D203 —
    the YAML parse cost is amortized across per-process invocations
    keyed by the resolved-path string. Operator edits mid-process
    are NOT picked up until the next process start (same posture as
    :func:`_load_config`).

    Strict per-register key requirement per ADR-0041 D202 — the
    loaded YAML MUST carry all five register keys from
    :data:`REGISTERS`. Missing keys raise :exc:`ValueError`. Mirrors
    :func:`validate_corpus_sample`'s strict-gate posture per
    ADR-0039 D187.

    Out-of-range thresholds per ADR-0041 D201 — each threshold MUST
    be a float in ``[0.0, 1.0]``. Out-of-range values raise
    :exc:`ValueError` at the boundary check.

    Args:
        thresholds_path: Override the default config path. ``None``
            resolves via ``cfg.voice.thresholds_path`` (if set) then
            :data:`DEFAULT_VOICE_THRESHOLDS_PATH`. The override
            surface is for test injection + Pillar I doctor.
        cfg: Pre-loaded config dict; ``None`` triggers the standard
            ``~/.outreach-factory/config.yml`` load via
            :func:`_load_config`.

    Returns:
        The parsed per-register threshold dict. Shape per
        ``config-template/voice_thresholds.example.yml``:
        a top-level ``thresholds:`` dict mapping each register
        (one of :data:`REGISTERS`) to a per-draft fidelity-score
        threshold in ``[0.0, 1.0]``.

    Raises:
        FileNotFoundError: if neither the operator's config NOR the
            default template exists (the framework is broken — the
            default template is required to ship with every clone).
        yaml.YAMLError: if either config is malformed (fail-loud per
            the operator-readable diagnostic discipline).
        ValueError: if the loaded config (a) is not a top-level
            dict, (b) lacks the ``thresholds:`` top-level key, (c)
            is missing a required register key, (d) carries an
            unknown register key not in :data:`REGISTERS`, or (e)
            carries an out-of-range threshold value.
    """
    resolved_path = _resolve_thresholds_path(thresholds_path, cfg)

    # Resolve the path-actually-read FIRST (apply fallback if needed),
    # THEN compute the cache key. Per Week 4 follow-up P2-1: caching
    # under the operator's path before the fallback rebind silently
    # served stale template data to a long-lived process where the
    # operator later created their config mid-run (the first call
    # cached template-derived data under the absent operator path;
    # subsequent calls returned that cache hit without re-checking
    # the path). Cache key follows the path actually read so fallback
    # results are correctly tagged to the template path; a fresh
    # process re-evaluates the operator's path naturally.
    if not resolved_path.exists():
        template_path = _default_thresholds_template_path()
        if not template_path.exists():
            raise FileNotFoundError(
                f"Neither the operator's voice-thresholds config at "
                f"{resolved_path} NOR the default-shipped template at "
                f"{template_path} exists. The framework is broken — "
                "the default template should ship with every clone. "
                "Check that the repository is intact + "
                "``config-template/voice_thresholds.example.yml`` exists."
            )
        sys.stderr.write(
            f"WARNING: operator-tuned voice thresholds not found at "
            f"{resolved_path}; falling back to default template at "
            f"{template_path}. Copy the template to {resolved_path} "
            "and tune per-register as your corpus grows.\n"
        )
        resolved_path = template_path

    cache_key = str(resolved_path)
    cached = _VOICE_THRESHOLDS_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    with resolved_path.open() as f:
        loaded = yaml.safe_load(f) or {}

    if not isinstance(loaded, dict):
        raise ValueError(
            f"Voice thresholds config at {resolved_path} must be a "
            f"top-level dict; got {type(loaded).__name__}. Check the "
            "YAML structure against "
            "config-template/voice_thresholds.example.yml."
        )

    if "thresholds" not in loaded or not isinstance(loaded["thresholds"], dict):
        raise ValueError(
            f"Voice thresholds config at {resolved_path} must have a "
            "top-level ``thresholds:`` dict. Check the YAML structure "
            "against config-template/voice_thresholds.example.yml."
        )

    thresholds = loaded["thresholds"]

    unknown_keys = set(thresholds.keys()) - REGISTERS
    if unknown_keys:
        raise ValueError(
            f"Voice thresholds config at {resolved_path}: unknown "
            f"register key(s) {sorted(unknown_keys)!r}; per ADR-0041 "
            f"D202 + ADR-0038 D178 the per-register key set is "
            f"closed-set at {sorted(REGISTERS)!r}. Adding a new "
            "register requires a coordinated ADR amendment per "
            "ADR-0038 D178 §Closed enum."
        )

    missing_keys = REGISTERS - set(thresholds.keys())
    if missing_keys:
        raise ValueError(
            f"Voice thresholds config at {resolved_path}: missing "
            f"required register key(s) {sorted(missing_keys)!r}; per "
            f"ADR-0041 D202 every register in REGISTERS "
            f"{sorted(REGISTERS)!r} MUST have a threshold (strict "
            "gate — partial config is operator misconfiguration that "
            "would otherwise surface as a downstream KeyError at "
            "draft-time)."
        )

    coerced: dict[str, float] = {}
    for register, threshold in thresholds.items():
        if isinstance(threshold, bool):
            # Avoid the Python bool-is-an-int footgun: ``True`` would
            # coerce to 1.0 + pass the [0.0, 1.0] range check.
            raise ValueError(
                f"Voice thresholds config at {resolved_path}: "
                f"thresholds[{register!r}] = {threshold!r} is a "
                "bool; per ADR-0041 D201 thresholds must be floats "
                "in [0.0, 1.0]."
            )
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            raise ValueError(
                f"Voice thresholds config at {resolved_path}: "
                f"thresholds[{register!r}] = {threshold!r} is not "
                "a valid float. Check the YAML structure against "
                "config-template/voice_thresholds.example.yml."
            )
        if not (0.0 <= value <= 1.0):
            raise ValueError(
                f"Voice thresholds config at {resolved_path}: "
                f"thresholds[{register!r}] = {value!r} is out of "
                "range; per ADR-0041 D201 + ADR-0038 D184(a) "
                "thresholds must be floats in [0.0, 1.0]."
            )
        coerced[register] = value

    _VOICE_THRESHOLDS_CACHE[cache_key] = dict(coerced)
    return coerced


def get_voice_threshold_for_register(
    register: str,
    *,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
) -> float:
    """Look up the per-register voice-fidelity threshold per ADR-0041 D204.

    Convenience helper for downstream Pillar F Week 6+
    hallucination-detection + Week 8+ fidelity-scoring consumers.
    Delegates to :func:`load_voice_thresholds` + extracts the
    per-register value.

    Args:
        register: The register name; MUST be in :data:`REGISTERS`.
        thresholds_path: Override the default config path; passed
            through to :func:`load_voice_thresholds`.
        cfg: Pre-loaded config dict; passed through.

    Returns:
        The per-draft fidelity-score threshold for the named
        register (float in ``[0.0, 1.0]``).

    Raises:
        ValueError: if ``register`` is not in :data:`REGISTERS`
            (closed-set per ADR-0038 D178). The underlying loader's
            errors (missing required register key; out-of-range
            value; malformed YAML) propagate unchanged.
    """
    if register not in REGISTERS:
        raise ValueError(
            f"register {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum is "
            "closed-set + construction-time-validated"
        )
    thresholds = load_voice_thresholds(thresholds_path, cfg=cfg)
    return thresholds[register]


# ---------------------------------------------------------------------------
# rebuild_corpus
# ---------------------------------------------------------------------------


def rebuild_corpus(
    corpus_dir: Path,
    *,
    embed_model: str | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    cfg: dict | None = None,
) -> None:
    """Re-embed every sample in ``index.json`` + write new
    ``embeddings.npy`` + ``metadata.json``.

    Per ADR-0038 D179 R026 mitigation. Operator-invoked via the
    ``rebuild`` CLI subcommand OR the
    ``retrieve_voice_exemplars(rebuild_on_mismatch=True)`` opt-in.

    Args:
        corpus_dir: The corpus directory. Must contain a valid
            ``index.json``; ``embeddings.npy`` + ``metadata.json``
            are overwritten.
        embed_model: The model name to record in the new metadata.
            Defaults to ``cfg.voice.embed_model`` or
            :data:`DEFAULT_EMBED_MODEL`.
        embed_fn: Optional injected encoder for tests; defaults to
            the process-cached :func:`_default_embed_fn`.
        cfg: Pre-loaded config dict; ``None`` triggers the standard
            ``~/.outreach-factory/config.yml`` load.

    Raises:
        FileNotFoundError: when ``corpus_dir`` or its ``index.json``
            does not exist.
    """
    corpus_dir = Path(corpus_dir).expanduser()
    if not corpus_dir.exists():
        raise FileNotFoundError(
            f"voice-corpus directory not found: {corpus_dir}"
        )
    idx_path = corpus_dir / "index.json"
    if not idx_path.exists():
        raise FileNotFoundError(
            f"index.json not found: {idx_path} (corpus rebuild needs "
            f"the per-sample index to re-encode)"
        )

    resolved_model = _resolve_embed_model(embed_model, cfg)
    if embed_fn is None:
        embed_fn = _default_embed_fn(resolved_model)

    samples = json.loads(idx_path.read_text())
    if not isinstance(samples, list):
        raise ValueError(
            f"index.json must be a list of per-sample dicts; got "
            f"{type(samples).__name__}"
        )

    vectors: list[np.ndarray] = []
    for s in samples:
        body = s.get("body") or ""
        vec = embed_fn(body).astype(np.float32)
        vectors.append(vec)

    if vectors:
        new_emb = np.stack(vectors, axis=0).astype(np.float32)
    else:
        # Empty corpus → write a zero-shape embeddings array so the
        # downstream loader's shape[0] == 0 reads stay consistent.
        new_emb = np.zeros((0, 1), dtype=np.float32)
    np.save(corpus_dir / "embeddings.npy", new_emb)

    # Best-effort sentence-transformers version capture; tests
    # injecting their own embed_fn don't need it but the metadata
    # still records what's installed in the rebuild process.
    try:
        from importlib.metadata import version as _pkg_version
        st_version = _pkg_version("sentence-transformers")
    except Exception:  # noqa: BLE001 — best-effort metadata
        st_version = "unknown"

    metadata = {
        "embed_model": resolved_model,
        "embed_version": st_version,
        "sentence_transformers_version": st_version,
        "schema_version": SCHEMA_VERSION,
        "corpus_count": len(samples),
        "built_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ",
        ),
    }
    (corpus_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))


# ---------------------------------------------------------------------------
# voice_exemplar_retrieved event-payload factory
# ---------------------------------------------------------------------------


def _hash_query(query: str) -> str:
    """SHA256-prefixed hex of the query string — privacy per I8.

    The raw query MUST NOT land in the ledger event stream. The
    hash is operator-visible (operators can deterministically
    re-hash a draft + grep the ledger for matches) without
    exposing the draft body.
    """
    return "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()


def build_voice_exemplar_retrieved_payload(
    *,
    person_id: str | None,
    query: str,
    exemplars: list[VoiceExemplar],
    channel: str,
    register: str | None,
) -> dict:
    """Construct the ``voice_exemplar_retrieved`` event payload (no
    ledger append).

    Per ADR-0038 D182 + ADR-0010 D17 + ADR-0014 D33's
    channel-on-every-event invariant + I8 privacy invariant
    extension (the raw query + the per-exemplar body are
    operator-private; the ledger event carries only the query
    hash + per-exemplar id + per-exemplar score).

    Event shape:

    .. code-block:: text

        type:        voice_exemplar_retrieved
        person_id    (the prospect the draft targets — may be None
                      for ad-hoc retrieval outside the per-Person flow)
        query_hash   (sha256:<hex> of the query — NOT the raw query)
        exemplars    (list of {exemplar_id, score} dicts — bodies NOT
                      included)
        channel      (closed-enum per ADR-0014 D33; required)
        register     (closed-enum per D178; may be None for unscoped
                      retrieval)
        _emitted_by  ("voice_corpus" per D17)

    Args:
        person_id: The prospect the draft targets. ``None`` is
            accepted for ad-hoc operator retrieval outside the
            per-Person flow.
        query: The raw query text. Hashed BEFORE inclusion; the
            raw text does NOT appear in the payload.
        exemplars: The retrieved :class:`VoiceExemplar` list.
            Their :attr:`VoiceExemplar.score` values land in the
            payload; bodies are NOT included.
        channel: The draft's intended channel (per
            channel-on-every-event invariant). MUST be in
            :data:`CHANNELS`; raises :exc:`ValueError` on unknown.
        register: The draft's register (or ``None`` for unscoped).
            When non-``None`` MUST be in :data:`REGISTERS`.

    Returns:
        The event payload dict (no ``ts`` — that's set by
        :meth:`Ledger.append`).

    Raises:
        ValueError: when ``channel`` is not in :data:`CHANNELS`
            or ``register`` (if non-None) is not in
            :data:`REGISTERS`.
    """
    if channel not in CHANNELS:
        raise ValueError(
            f"channel {channel!r} not in CHANNELS "
            f"{sorted(CHANNELS)!r} per ADR-0014 D33 + ADR-0038 D182"
        )
    if register is not None and register not in REGISTERS:
        raise ValueError(
            f"register {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r} per ADR-0038 D178"
        )

    exemplars_payload = [
        {"exemplar_id": ex.id, "score": ex.score}
        for ex in exemplars
    ]
    return {
        "type": "voice_exemplar_retrieved",
        "person_id": person_id,
        "query_hash": _hash_query(query),
        "exemplars": exemplars_payload,
        "channel": channel,
        "register": register,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_retrieve(args) -> int:
    # Per follow-up P2-2 — refuse-loud on --apply without --channel
    # BEFORE the retrieve runs (avoids loading SentenceTransformer +
    # the corpus for an invocation that's going to fail anyway).
    if args.apply and not args.channel:
        print(
            "ERROR: --channel is required when --apply is set "
            "(channel-on-every-event invariant per ADR-0014 D33; the "
            "emitted voice_exemplar_retrieved event MUST carry an "
            "operator-deliberate channel). Either pass "
            "--channel <email|linkedin-dm|linkedin-comment|twitter-dm> "
            "or drop --apply for dry-run inspection.",
            file=sys.stderr,
        )
        return 2

    cfg = _load_config()
    embed_model = args.embed_model or None
    query = args.query
    if not query and args.file:
        query = Path(args.file).expanduser().read_text()
    if not query:
        query = sys.stdin.read()
    if not query.strip():
        print("ERROR: query is empty", file=sys.stderr)
        return 2

    try:
        result = retrieve_voice_exemplars(
            query,
            k=args.k,
            register=args.register,
            channel=args.channel,
            is_substantive_reply=(
                True if args.is_substantive_reply else None
            ),
            corpus_dir=(
                Path(args.corpus_dir).expanduser()
                if args.corpus_dir else None
            ),
            embed_model=embed_model,
            rebuild_on_mismatch=args.rebuild_on_mismatch,
            cfg=cfg,
        )
    except (FileNotFoundError, ValueError,
            VoiceCorpusMetadataMismatch) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Per follow-up P2-2 — channel-on-every-event invariant (ADR-0014
    # D33) requires the operator's deliberate channel selection at
    # emit time. The dry-run `--json` mode omits the payload when
    # channel is unspecified (operators inspecting the corpus see the
    # exemplar list without a synthetic emit shape). The `--apply +
    # no --channel` refusal landed at the top of this function before
    # retrieve to fail fast.
    payload: dict | None = None
    if (args.apply or args.json) and args.channel:
        payload = build_voice_exemplar_retrieved_payload(
            person_id=args.person_id,
            query=query,
            exemplars=result,
            channel=args.channel,
            register=args.register,
        )

    if args.json:
        report = {
            "ok": True,
            "k": args.k,
            "register": args.register,
            "channel": args.channel,
            "exemplars": [
                {
                    "id": ex.id,
                    "date": ex.date,
                    "subject": ex.subject,
                    "to": ex.to,
                    "register": ex.register,
                    "channel": ex.channel,
                    "score": ex.score,
                    "is_substantive_reply": ex.is_substantive_reply,
                    "body": ex.body,
                }
                for ex in result
            ],
            "embed_model": _resolve_embed_model(embed_model, cfg),
        }
        if payload is not None:
            report["payload"] = payload
        print(json.dumps(report, indent=2))
    else:
        print(f"retrieved: {len(result)} exemplars")
        for i, ex in enumerate(result, 1):
            print(f"  [{i}] id={ex.id} score={ex.score:.4f} "
                  f"register={ex.register} channel={ex.channel}")

    if args.apply and payload is not None:
        # Lazy import to avoid forcing ledger init for read-only
        # retrieve invocations (CLI ledger init touches disk).
        import ledger as _ledger
        led = _ledger.Ledger(_ledger.DEFAULT_LEDGER_DIR)
        try:
            led.append(payload)
        except (OSError, ValueError) as exc:
            print(
                f"WARNING: ledger append failed for "
                f"voice_exemplar_retrieved: {exc}",
                file=sys.stderr,
            )
    return 0


def _cmd_validate(args) -> int:
    corpus_dir = Path(args.corpus_dir).expanduser()
    idx_path = corpus_dir / "index.json"
    if not idx_path.exists():
        msg = f"ERROR: index.json not found: {idx_path}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(msg, file=sys.stderr)
        return 2
    samples = json.loads(idx_path.read_text())
    if not isinstance(samples, list):
        msg = "ERROR: index.json must be a list of per-sample dicts"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(msg, file=sys.stderr)
        return 2

    per_sample: list[dict] = []
    overall_ok = True
    for i, s in enumerate(samples):
        try:
            r = validate_corpus_sample(s)
        except TypeError as exc:
            r = ValidationResult(ok=False, errors=[str(exc)])
        if not r.ok:
            overall_ok = False
        per_sample.append({
            "index": i,
            "id": s.get("id") if isinstance(s, dict) else None,
            "ok": r.ok,
            "errors": r.errors,
        })

    if args.json:
        print(json.dumps({
            "ok": overall_ok,
            "corpus_dir": str(corpus_dir),
            "sample_count": len(samples),
            "samples": per_sample,
        }, indent=2))
    else:
        for entry in per_sample:
            status = "OK" if entry["ok"] else "FAIL"
            print(f"  [{entry['index']}] {status} id={entry['id']!r}")
            for err in entry["errors"]:
                print(f"      - {err}")
        print(f"overall: {'OK' if overall_ok else 'FAIL'} "
              f"({sum(1 for e in per_sample if e['ok'])}/{len(per_sample)} pass)")
    return 0 if overall_ok else 2


def _cmd_rebuild(args) -> int:
    cfg = _load_config()
    corpus_dir = Path(args.corpus_dir).expanduser()
    try:
        rebuild_corpus(
            corpus_dir,
            embed_model=args.embed_model,
            cfg=cfg,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"rebuild complete: {corpus_dir}")
    return 0


def _resolve_thresholds_cli_paths(
    args, cfg: dict,
) -> tuple[Path, bool]:
    """Resolve the per-call thresholds path provenance for CLI output.

    Returns ``(source_path, is_fallback)`` where ``source_path`` is the
    ABSOLUTE path to the YAML file the loader will actually read AFTER
    any fallback rebind, and ``is_fallback`` is True when the
    operator-supplied (or cfg- / default-resolved) path was absent + the
    loader fell back to the default-shipped template per ADR-0041 D199.

    Per Week 5 follow-up P2-1: the operator-supplied path is normalized
    via ``Path.resolve()`` so the emitted ``_meta.source_path`` is
    always absolute regardless of whether the operator passed a
    relative ``--thresholds-path``. The fallback branch already returns
    an absolute path via :func:`_default_thresholds_template_path`'s
    ``Path(__file__).resolve()``. Pre-fix the non-fallback branch
    returned the unresolved (potentially relative) path, breaking the
    D207 contract ("source_path is the absolute path...") + creating
    silent cross-tenant audit-tooling drift where the same config file
    surfaced as different provenance strings depending on the caller's
    working directory.

    Used by the three ``thresholds`` CLI subcommands per ADR-0042 D207
    to populate ``_meta.source_path`` + ``_meta.is_fallback``. The
    helper re-runs the loader's path-resolution logic; it does NOT
    re-parse the YAML (the loader's process-cache amortizes that per
    D203). Private helper (not exported) — the structured surface is
    the CLI's JSON ``_meta`` output.
    """
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )
    resolved = _resolve_thresholds_path(thresholds_path, cfg)
    if not resolved.exists():
        return (_default_thresholds_template_path(), True)
    return (resolved.resolve(), False)


def _cmd_thresholds_list(args) -> int:
    """``thresholds list`` — emit the per-register threshold table
    with provenance metadata per ADR-0042 D207."""
    cfg = _load_config()
    source_path, is_fallback = _resolve_thresholds_cli_paths(args, cfg)
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )
    try:
        thresholds = load_voice_thresholds(thresholds_path, cfg=cfg)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = {
            "thresholds": thresholds,
            "_meta": {
                "source_path": str(source_path),
                "is_fallback": is_fallback,
            },
        }
        print(json.dumps(out, indent=2))
    else:
        # Per Week 5 follow-up P3-3: ``list`` text-table iteration uses
        # ALPHABETICAL order (sorted(REGISTERS)) — easier-to-scan
        # presentation for operator inspection. The asymmetric ``dump``
        # subcommand uses SKILL.md CANONICAL order (per ADR-0040 D193 +
        # ADR-0042 D208 round-trip contract) so the YAML re-emit
        # preserves the documentation-referenced order operators see in
        # the framework's per-register registry. Both orders are
        # operator-deliberate; the asymmetry is by design + pinned by
        # ``test_thresholds_list_text_registers_in_alphabetical_order``
        # + ``test_thresholds_dump_yaml_preserves_canonical_order``.
        print(f"{'register':<18} threshold")
        print(f"{'-' * 18} {'-' * 9}")
        for register in sorted(REGISTERS):
            print(f"{register:<18} {thresholds[register]:.2f}")
        print()
        if is_fallback:
            print(f"source: {source_path} "
                  "(default template; operator config not found)")
        else:
            print(f"source: {source_path}")
    return 0


def _cmd_thresholds_get(args) -> int:
    """``thresholds get <register>`` — single-register lookup with
    provenance metadata per ADR-0042 D207. Argparse-choices enforces
    the closed-enum per D210 BEFORE this handler runs."""
    cfg = _load_config()
    source_path, is_fallback = _resolve_thresholds_cli_paths(args, cfg)
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )
    try:
        threshold = get_voice_threshold_for_register(
            args.register,
            thresholds_path=thresholds_path,
            cfg=cfg,
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = {
            "register": args.register,
            "threshold": threshold,
            "_meta": {
                "source_path": str(source_path),
                "is_fallback": is_fallback,
            },
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"register:   {args.register}")
        print(f"threshold:  {threshold:.2f}")
        if is_fallback:
            print(f"source:     {source_path} "
                  "(default template; operator config not found)")
        else:
            print(f"source:     {source_path}")
    return 0


def _cmd_thresholds_dump(args) -> int:
    """``thresholds dump`` — literal YAML re-emit (or JSON) suitable
    for piping to ``~/.outreach-factory/voice_thresholds.yml`` per
    ADR-0042 D208. The ``_meta`` provenance field is OMITTED so the
    output round-trips cleanly through the loader (operators bootstrap
    via ``thresholds dump > voice_thresholds.yml``).
    """
    cfg = _load_config()
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )
    try:
        thresholds = load_voice_thresholds(thresholds_path, cfg=cfg)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {"thresholds": thresholds}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        # Pin per-key sort order to REGISTERS' canonical order via the
        # default-shipped template's ordering (cold-pitch, congrats,
        # re-engagement, reply, public-comment) so the YAML re-emit is
        # operator-readable + stable across runs. yaml.safe_dump's
        # default sort would alphabetize and lose the SKILL.md table
        # order — explicit dict ordering preserves the convention.
        ordered = {
            register: thresholds[register]
            for register in DEFAULT_VOICE_THRESHOLD_PER_REGISTER
            if register in thresholds
        }
        print(yaml.safe_dump(
            {"thresholds": ordered},
            sort_keys=False,
        ), end="")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Pillar F embedding-retrieval primitive (ADR-0038 D178 + "
            "D179 + ADR-0039 + ADR-0041 + ADR-0042)"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser(
        "retrieve",
        help="Retrieve top-K voice-corpus exemplars for a draft.",
    )
    r.add_argument("--query", default=None,
                   help="Draft text (or use --file or stdin)")
    r.add_argument("--file", default=None,
                   help="Read draft from file path")
    r.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    r.add_argument("--register", default=None,
                   choices=sorted(REGISTERS),
                   help=f"Filter by register (one of {sorted(REGISTERS)}); "
                        f"omit for unscoped retrieval")
    r.add_argument("--channel", default=None,
                   choices=sorted(CHANNELS),
                   help=f"Filter by channel (one of {sorted(CHANNELS)}); "
                        f"omit for unscoped retrieval")
    r.add_argument("--is-substantive-reply", action="store_true",
                   help="Filter to samples flagged as having received "
                        "a substantive reply")
    r.add_argument("--corpus-dir", default=None,
                   help="Override corpus directory location")
    r.add_argument("--embed-model", default=None,
                   help="Override embedding model name")
    r.add_argument("--rebuild-on-mismatch", action="store_true",
                   help="Auto-rebuild corpus if metadata diverges from "
                        "runtime (R026 mitigation)")
    r.add_argument("--person-id", default=None,
                   help="Optional: stamp on the emitted "
                        "voice_exemplar_retrieved event")
    r.add_argument("--apply", action="store_true",
                   help="Append voice_exemplar_retrieved event to the "
                        "ledger. Default is dry-run (report only).")
    r.add_argument("--json", action="store_true")

    v = sub.add_parser(
        "validate",
        help="Validate the per-sample schema of a corpus' index.json.",
    )
    v.add_argument("--corpus-dir", required=True)
    v.add_argument("--json", action="store_true")

    b = sub.add_parser(
        "rebuild",
        help="Re-embed all samples + write new metadata.json (R026 "
             "mitigation).",
    )
    b.add_argument("--corpus-dir", required=True)
    b.add_argument("--embed-model", default=None,
                   help="Override the embedding model used for "
                        "rebuild (recorded in metadata).")

    # Per ADR-0042 D206 — nested subparser group for per-register
    # voice-fidelity threshold inspection. Three actions surface the
    # Week 4 threshold loader (ADR-0041 D199-D205) to operators
    # without requiring custom Python scripts. READ-only by design;
    # the mutate subcommand is operator-deferred to Pillar I per D209.
    t = sub.add_parser(
        "thresholds",
        help="Inspect the per-register voice-fidelity thresholds "
             "(list / get / dump).",
    )
    t_sub = t.add_subparsers(dest="thresholds_cmd", required=True)

    tl = t_sub.add_parser(
        "list",
        help="Print the per-register threshold table + source path.",
    )
    tl.add_argument("--thresholds-path", default=None,
                    help=f"Override the threshold YAML path "
                         f"(default: {DEFAULT_VOICE_THRESHOLDS_PATH})")
    tl.add_argument("--json", action="store_true",
                    help="Emit JSON {thresholds, _meta} instead of "
                         "the operator-readable table.")

    tg = t_sub.add_parser(
        "get",
        help="Print the threshold for a single register.",
    )
    tg.add_argument("register", choices=sorted(REGISTERS),
                    help=f"The register to look up (one of "
                         f"{sorted(REGISTERS)} per ADR-0038 D178)")
    tg.add_argument("--thresholds-path", default=None,
                    help=f"Override the threshold YAML path "
                         f"(default: {DEFAULT_VOICE_THRESHOLDS_PATH})")
    tg.add_argument("--json", action="store_true",
                    help="Emit JSON {register, threshold, _meta} "
                         "instead of the operator-readable form.")

    td = t_sub.add_parser(
        "dump",
        help="Re-emit the per-register threshold YAML (suitable for "
             "piping to ~/.outreach-factory/voice_thresholds.yml).",
    )
    td.add_argument("--thresholds-path", default=None,
                    help=f"Override the threshold YAML path "
                         f"(default: {DEFAULT_VOICE_THRESHOLDS_PATH})")
    td.add_argument("--json", action="store_true",
                    help="Emit JSON {thresholds} instead of YAML.")

    args = p.parse_args()

    if args.cmd == "retrieve":
        return _cmd_retrieve(args)
    if args.cmd == "validate":
        return _cmd_validate(args)
    if args.cmd == "rebuild":
        return _cmd_rebuild(args)
    if args.cmd == "thresholds":
        if args.thresholds_cmd == "list":
            return _cmd_thresholds_list(args)
        if args.thresholds_cmd == "get":
            return _cmd_thresholds_get(args)
        if args.thresholds_cmd == "dump":
            return _cmd_thresholds_dump(args)
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
