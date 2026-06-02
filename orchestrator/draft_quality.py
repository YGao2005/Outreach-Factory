"""Pillar F Week 6 + Week 7 + Week 8 + Week 9 + Week 10 (+ Week 11 corpus revision) — hallucination-detection primitive + per-claim-type corpus measurement + per-draft voice-fidelity scoring primitive + per-claim fuzzy-match citation extension at the Layer 3 parser + Layer 4 post-engine guard + ``draft_ready`` event class.

Per ADR-0043 (D212-D219) — Week 6 hallucination-detection Layer 2-3.
Per ADR-0044 (D220-D227) — Week 7 per-claim-type corpora + measurement primitive.
Per ADR-0045 (D228-D235) — Week 8 per-draft voice-fidelity scoring primitive.
Per ADR-0046 (D236-D243) — Week 9 per-claim fuzzy-match citation extension at the Layer 3 parser.
Per ADR-0047 (D244-D251) — Week 10 Layer 4 post-engine guard + ``draft_ready`` event class + per-dimension operator-override path.
Per ADR-0048 (D252-D261) — Week 11 Layer 3 parser corpus revision: paraphrased-ready pairs for fuzzy-active claim types + per-claim-type bound tightening (corpus-revision scope; ZERO new module surfaces in this file per D261; the per-claim-type benchmark bounds at ``tests/test_draft_quality_corpus.py:_CLAIM_TYPE_BENCHMARK_TARGETS`` tightened for ``named_entity`` + ``dated_event``).

**Week 6** lands the FIRST behavioral layers of the ADR-0038 D180
FIVE-layer hallucination-detection defense:

* **Layer 2** — :class:`DraftQualityResult` dataclass with
  construction-time invariants. Refuses-loud at construction when
  ``state="ready"`` AND ``uncited_claims`` is non-empty. Mirrors
  Pillar E :class:`discovery_lineage.DiscoveryLineage`'s
  ``__post_init__`` per ADR-0036 D167 + Pillar F Week 2
  :class:`voice_corpus.VoiceExemplar`'s pattern per ADR-0039 D186.
* **Layer 3** — :func:`parse_draft_for_claims` deterministic
  per-claim extractor + per-claim citation cross-reference against
  the research dossier. Five claim types per ADR-0038 D180 +
  ADR-0043 D214: ``date_reference`` / ``named_entity`` /
  ``you_phrase`` / ``quoted_text`` / ``dated_event``.

**Week 7** lands the per-claim-type corpus + measurement primitive
per ADR-0044 (R027 mitigation — per-claim false-positive rate
measurement):

* :class:`CorpusPair` — per-pair dataclass for the operator-
  judgment ground-truth labels in
  ``tests/fixtures/draft_quality_corpus/<claim_type>.yml``.
* :class:`CorpusMeasurement` — per-claim-type measurement result
  dataclass with TP/TN/FP/FN tallies + accuracy +
  false_positive_rate + false_negative_rate.
* :func:`measure_per_claim_type_false_positive_rate` — walks the
  per-claim-type corpus, runs :func:`score_draft` per pair,
  aggregates outcomes against the ``expected_state`` ground truth.

**Week 8** lands the per-draft voice-fidelity scoring primitive
per ADR-0045 (ADR-0038 D184(a) — the LOAD-BEARING per-register
fidelity gate; ADR-0038 D182 — the third Pillar F event class
``draft_quality_scored``):

* :class:`DraftFidelityResult` — per-draft Layer 2 fidelity-
  scoring result dataclass with construction-time invariants per
  ADR-0045 D229. Refuses-loud at construction when
  ``state="ready"`` AND ``meets_threshold=False`` (symmetric with
  the Week 6 :class:`DraftQualityResult` uncited-with-ready
  refusal). The ``voice_fidelity_score`` field is the mean of the
  top-K voice-corpus exemplars' per-exemplar scores (cosine ×
  recency multiplier per ADR-0038 D184(a)).
* :func:`compute_draft_fidelity_score` — per-draft fidelity
  scoring primitive per ADR-0045 D230. Consumes the Week 2
  retrieval primitive (:func:`voice_corpus.retrieve_voice_exemplars`)
  + the Week 4 threshold loader
  (:func:`voice_corpus.get_voice_threshold_for_register`). The
  per-register threshold gates whether the draft advances to
  ``state="ready"``.
* :func:`build_draft_quality_scored_payload` — ``draft_quality_scored``
  event factory per ADR-0045 D231. **Emit-always** posture
  (vs Week 6's emit-only-on-uncited for ``hallucination_detected``
  per ADR-0043 D219) — Pillar G observability needs accept-case
  events for per-register score distribution rendering. Privacy-
  respecting per I8: ``draft_hash`` (sha256), per-exemplar IDs
  only, NO raw draft body, NO per-exemplar bodies.

Week 8 also flips the ``voice.use_embedding_primitive`` config
default from ``false`` → ``true`` per ADR-0039 §Existing-operator
seed (the Week 8+ transition: operators with corpora tagged with
``register`` + ``channel`` schema fields adopt the new primitive;
operators without tags opt OUT explicitly).

The Week 6 primitive consumes the Pillar F Week 4 threshold loader
(:func:`voice_corpus.get_voice_threshold_for_register`) at draft-
time per ADR-0041 D204; the per-register threshold is STAMPED on
the :class:`DraftQualityResult` for downstream consumers (Week 8+
fidelity-scoring; Week 10 Layer 4 emit guard; Week 12 Layer 5
reconcile heal-pass).

Module shape (per-primitive flat-module convention per ADR-0036
D166 + ADR-0043 D212):

* :data:`CLAIM_TYPES` — frozen enum of the five claim types.
* :data:`EMITTED_BY` — per-event ``_emitted_by`` marker per
  ADR-0010 D17 + ADR-0043 D216.
* :class:`ParsedClaim` — per-claim trace dataclass per ADR-0043
  D214.
* :class:`DraftQualityResult` — per-draft Layer 2 result dataclass
  per ADR-0043 D213.
* :func:`parse_draft_for_claims` — Layer 3 deterministic parser
  per ADR-0043 D214.
* :func:`score_draft` — composite Layer 2 + Layer 3 entry point
  per ADR-0043 D215.
* :func:`build_hallucination_detected_payload` — event-shape
  factory per ADR-0043 D216 (privacy-respecting; emit-only-on-
  uncited per ADR-0043 D219).
* :class:`CorpusPair` — per-pair labeled corpus dataclass per
  ADR-0044 D222.
* :class:`CorpusMeasurement` — per-claim-type measurement
  dataclass per ADR-0044 D223.
* :func:`measure_per_claim_type_false_positive_rate` —
  measurement primitive per ADR-0044 D223.
* :class:`DraftFidelityResult` — per-draft Layer 2 fidelity-
  scoring result dataclass per ADR-0045 D229.
* :func:`compute_draft_fidelity_score` — per-draft fidelity-
  scoring primitive per ADR-0045 D230.
* :func:`build_draft_quality_scored_payload` — Week 8 event-
  shape factory per ADR-0045 D231 (emit-always posture).
* :data:`DEFAULT_FUZZY_CITATION_THRESHOLD` — Week 9 module
  constant per ADR-0046 D239 (the cosine cutoff for the
  per-claim fuzzy-match citation extension, calibrated
  against the Week 7 corpus at ``0.85``).
* :func:`_chunk_dossier_for_fuzzy_match` — Week 9 private
  sentence-level chunker per ADR-0046 D238.
* :func:`_find_citation_anchor_fuzzy` — Week 9 private
  cosine-against-chunks helper per ADR-0046 D238.
* :class:`Layer4GuardRefusal` — Week 10 typed exception per
  ADR-0047 D245 (subclasses :exc:`ValueError`; carries the
  per-dimension trace + the per-Layer-2 result objects for
  operator-readable diagnostic surfacing at the CLI / SKILL.md
  Phase 6).
* :func:`build_draft_ready_payload` — Week 10 Layer 4 emit-
  guard factory per ADR-0047 D245 + D246. Consumes BOTH
  :class:`DraftQualityResult` (Week 6 substrate) AND
  :class:`DraftFidelityResult` (Week 8 substrate); refuses-
  loud (raises :exc:`Layer4GuardRefusal`) when EITHER state
  is ``"refused"`` AND the per-dimension override is absent;
  emits the ``draft_ready`` event when both pass (or per-
  dimension overrides bypass). Emit-only-on-both-pass posture
  per ADR-0047 D246 — distinct from Week 6's emit-only-on-
  uncited per ADR-0043 D219 + Week 8's emit-always per
  ADR-0045 D231. THE FOURTH Pillar F event class per
  ADR-0038 D182.

CLI surface (per ADR-0043 D212 + ADR-0044 D224 + ADR-0045 D234):

::

    python orchestrator/draft_quality.py parse \\
        --draft-path <path> \\
        --research-dossier-path <path> \\
        --register <cold-pitch|congrats|re-engagement|reply|public-comment> \\
        --channel <email|linkedin-dm|linkedin-comment|twitter-dm> \\
        [--thresholds-path PATH] \\
        [--apply] [--json]

    python orchestrator/draft_quality.py measure \\
        --corpus-dir <path-to-tests/fixtures/draft_quality_corpus> \\
        --claim-type <date_reference|named_entity|you_phrase|quoted_text|dated_event> \\
        [--thresholds-path PATH] [--json]

    python orchestrator/draft_quality.py score \\
        --draft-path <path> \\
        --register <cold-pitch|congrats|re-engagement|reply|public-comment> \\
        --channel <email|linkedin-dm|linkedin-comment|twitter-dm> \\
        [--k 5] [--thresholds-path PATH] [--person-id ID] \\
        [--apply] [--json]

    python orchestrator/draft_quality.py emit-ready \\
        --draft-path <path> \\
        --research-dossier-path <path> \\
        --register <cold-pitch|congrats|re-engagement|reply|public-comment> \\
        --channel <email|linkedin-dm|linkedin-comment|twitter-dm> \\
        [--k 5] [--thresholds-path PATH] [--person-id ID] \\
        [--hallucination-check-override --hallucination-check-override-reason REASON] \\
        [--voice-fidelity-check-override --voice-fidelity-check-override-reason REASON] \\
        [--skip-fidelity-check] \\
        [--apply] [--json]

The ``--apply`` flag controls ledger emit behavior:

* For the ``parse`` subcommand (Week 6 per ADR-0043 D219), the
  ``hallucination_detected`` event is appended ONLY when
  ``uncited_claims`` is non-empty AND ``--apply`` is set (emit-
  only-on-uncited posture). Dry-run is default — mirrors
  :mod:`voice_corpus`'s ``--apply`` semantics per ADR-0039 D188.
* For the ``score`` subcommand (Week 8 per ADR-0045 D231), the
  ``draft_quality_scored`` event is appended for BOTH ``ready``
  and ``refused`` states when ``--apply`` is set (emit-always
  posture). Pillar G observability needs accept-case events for
  per-register score distribution rendering; the emit-always
  posture diverges from the Week 6 ``hallucination_detected``
  emit-only-on-uncited posture deliberately.
* For the ``emit-ready`` subcommand (Week 10 per ADR-0047 D246),
  the ``draft_ready`` event is appended ONLY when BOTH per-Layer
  2 verdicts pass (natively OR via the per-dimension override)
  AND ``--apply`` is set (emit-only-on-both-pass posture). The
  subcommand ALSO emits the upstream ``hallucination_detected``
  (emit-only-on-uncited per ADR-0043 D219) + ``draft_quality_scored``
  (emit-always per ADR-0045 D231 unless ``--skip-fidelity-check``)
  events per their existing cardinalities when ``--apply`` is set
  — the per-Layer events emit at their existing cardinality
  regardless of the Layer 4 verdict.

**Privacy invariant per I8 + ADR-0038 §Compliance with
invariants**: the ``hallucination_detected`` event carries
``draft_hash`` (sha256:<hex>) NOT the raw draft body; the per-
claim trace carries the draft's literal claim span (operator-
visible diagnostic) NOT the dossier content.

**TEST-ONLY ``embed_fn`` seam preservation per ADR-0043 D218 +
ADR-0044 D227 + ADR-0045 D235 + ADR-0046 D243 + ADR-0047 D250**:
the TEST-ONLY ``embed_fn`` seam is LIVE at FIVE encoding surfaces
in this module:

* :func:`parse_draft_for_claims` (Week 6 — Layer 3 parser; per
  ADR-0043 D218; Week 9 lands FIRST behavioral consumption via
  the fuzzy-fallback path per ADR-0046 D243).
* :func:`score_draft` (Week 6 — composite Layer 2 + Layer 3
  entry point; per ADR-0043 D218).
* :func:`measure_per_claim_type_false_positive_rate` (Week 7 —
  passthrough to ``score_draft``; per ADR-0044 D227).
* :func:`compute_draft_fidelity_score` (Week 8 — per-draft
  fidelity-scoring primitive; per ADR-0045 D235).
* The fuzzy-fallback inside :func:`parse_draft_for_claims`
  (Week 9 — FIRST behavioral consumption at the parser surface
  per ADR-0046 D243).

Week 8 ALSO ships a NEW TEST-ONLY ``retrieve_fn`` seam at
:func:`compute_draft_fidelity_score` (full retrieval bypass for
unit tests; substitutes :func:`voice_corpus.retrieve_voice_exemplars`
at the COMPONENT level; per ADR-0045 D235).

**Week 10 lands the Layer 4 emit-guard factory
:func:`build_draft_ready_payload` as a STRUCTURAL COMPOSITION
surface** — the factory consumes already-constructed Layer 2
results from the per-Layer primitives; the per-Layer encoding
work has already amortized at the per-Layer per-call sites. The
factory's signature has NO ``embed_fn`` or ``retrieve_fn`` kwarg
per ADR-0047 D250 (rejected: pass-through ``embed_fn`` for
re-running per-Layer primitives — would invert the per-Layer
dispatch + compound per-call cost). The seam stays at the FIVE
upstream surfaces named above.

Week 6's default code path does NOT encode (parser is
deterministic + cross-reference is substring/regex); Week 8's
default code path DOES encode (the retrieval primitive's
``embed_fn`` runs unless ``retrieve_fn`` is supplied); Week 9
lands the FIRST behavioral consumption at the parser surface
via the fuzzy-fallback path (the lazy-load default per ADR-0046
D241 runs ``voice_corpus._default_embed_fn`` when
``embed_fn=None``). The CLI does NOT surface ``--embed-fn`` or
``--retrieve-fn`` (security + audit concern per ADR-0039
D188-Alt3 + ADR-0040 D197-Alt1). Verified by
``test_cli_has_no_embed_fn_flag`` (Week 6) +
``test_cli_score_has_no_embed_fn_flag`` (Week 8) +
``test_cli_score_has_no_retrieve_fn_flag`` (Week 8) +
``test_cli_emit_ready_has_no_embed_fn_flag`` (Week 10) +
``test_cli_emit_ready_has_no_retrieve_fn_flag`` (Week 10) + the
per-week reviewer's checklist row.

The Week 6 primitive was the FIRST non-N/A verification of the
TEST-ONLY ``embed_fn`` seam at a new encoding surface (Weeks 4+5
were N/A — config-loader + read-only-CLI surfaces); Weeks 7 + 8
+ 9 extended the seam to per-claim-type measurement + per-draft
fidelity-scoring + per-claim fuzzy-match surfaces; Week 10's
Layer 4 emit-guard factory is structural-composition (no new
seam — the factory consumes the upstream per-Layer results).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import yaml

# Pillar F Week 6 substrate — the per-register threshold loader from
# Week 4 (ADR-0041 D204) is the LOAD-BEARING substrate the Week 6
# primitive consumes at draft-time per ADR-0043 D215. The closed-enum
# REGISTERS + CHANNELS sets per ADR-0038 D178 + ADR-0014 D33 are the
# shared closed enums.
from voice_corpus import (
    CHANNELS,
    DEFAULT_TOP_K,
    REGISTERS,
    VoiceExemplar,
    get_voice_threshold_for_register,
    retrieve_voice_exemplars,
)

# Pillar G Week 6 — per-stage span emit at the review-stage call site
# per ADR-0055 D301. The helper is no-op-safe when the OTel
# TracerProvider is uninitialized (NoOpTracer); operators wiring
# `init_otel_tracer_provider` at startup see spans flow through to
# the OTel backend.
from observability import traced_stage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Per ADR-0038 D180 + ADR-0043 D214 — the five claim types extracted
# from drafts. Closed-set; future extensions land via ADR amendment
# per the closed-enum convention.
CLAIM_TYPES: frozenset[str] = frozenset({
    "date_reference",
    "named_entity",
    "you_phrase",
    "quoted_text",
    "dated_event",
})


# Per ADR-0010 D17 + ADR-0043 D216 — per-event ``_emitted_by`` marker
# for ledger filterability (operators grep events by primitive of
# origin via ``jq 'select(._emitted_by == "draft_quality")'``).
EMITTED_BY: str = "draft_quality"


# Per ADR-0046 D239 — default fuzzy-match cosine threshold for the
# Layer 3 parser's per-claim citation cross-reference. Calibrated
# against the Week 7 corpus to balance the asymmetric-failure-cost
# discipline per ADR-0038 D180 + D184:
#
# * FN_rate reduction (brand-risk path): the threshold must be LOW
#   enough to close the Week 7 ``named_entity`` 53% + ``dated_event``
#   40% FN gaps. Paraphrased entities cosine ≈ 0.85-0.95; possessive
#   constructions cosine ≈ 0.80-0.90.
# * FP_rate bound (operator-friction path): the threshold must be
#   HIGH enough that semantically-unrelated chunks don't false-
#   positively match. Unrelated chunks cosine ≈ 0.30-0.65.
#
# Empirically calibrated against the Week 7 corpus measurement at
# Week 9 commit time (per ADR-0046 D239's calibration discipline).
# Note on the negation-prose limitation: the Week 7 corpus's refused-
# pair dossiers use negation phrasing ("no Q1 2025 mention"; "August
# 2026 is absent") that LITERALLY contains the claim text;
# embedding-based similarity cannot detect negation, so chunks with
# negation prose surface cosines in the 0.75-0.90 range against the
# claim text. 0.85 keeps these below the threshold while remaining
# low enough to close the named_entity (paraphrased entity cosine
# ~0.85-0.95) + dated_event (multi-word event reference cosine
# ~0.80-0.92) FN_rate gap. Per-call override via the
# ``fuzzy_threshold`` kwarg at :func:`parse_draft_for_claims` +
# :func:`score_draft`.
DEFAULT_FUZZY_CITATION_THRESHOLD: float = 0.85


# Per ADR-0046 D238 — chunker bounds. Short chunks (<10 chars) drop
# (cosine noise at the BAAI/bge-small-en-v1.5 model's 384-dim
# embedding resolution); long chunks (>500 chars) re-split on the
# next sentence boundary (embedding dilution on long texts degrades
# cosine discrimination).
_FUZZY_CHUNK_MIN_CHARS: int = 10
_FUZZY_CHUNK_MAX_CHARS: int = 500


# ---------------------------------------------------------------------------
# Per-claim trace dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedClaim:
    """Per-claim trace per ADR-0043 D214.

    The Layer 3 parser surfaces every extractable claim from the
    draft as a ``ParsedClaim`` tuple; the cross-reference step
    against the dossier populates ``citation_anchor`` (the URL OR
    line ref supporting the claim) or leaves it ``None`` to
    signal the uncited case.

    Attributes:
        claim_type: One of :data:`CLAIM_TYPES`. Closed-enum per
            ADR-0038 D180 + ADR-0043 D214.
        claim_text: The draft's literal claim span (operator-
            visible diagnostic per ADR-0043 D216). The dossier
            content is NOT in this field (privacy per I8).
        citation_anchor: The matching dossier anchor (URL or line
            ref) when cited; ``None`` when uncited. Operators
            inspect the dossier directly via the anchor; the
            anchor is the per-event ledger payload's citation
            field (NOT the dossier body).

    Construction-time invariants per ADR-0043 D214:

    * ``claim_type`` in :data:`CLAIM_TYPES` (closed-enum).
    * ``claim_text`` non-empty (whitespace-stripped).
    """

    claim_type: str
    claim_text: str
    citation_anchor: str | None

    def __post_init__(self) -> None:
        if self.claim_type not in CLAIM_TYPES:
            raise ValueError(
                f"claim_type {self.claim_type!r} not in CLAIM_TYPES "
                f"{sorted(CLAIM_TYPES)!r}; per ADR-0043 D214 the set is "
                "closed + construction-time-validated"
            )
        if not self.claim_text or not self.claim_text.strip():
            raise ValueError(
                "claim_text must be non-empty (whitespace-stripped); "
                f"got {self.claim_text!r}"
            )


# ---------------------------------------------------------------------------
# DraftQualityResult — Layer 2 dataclass
# ---------------------------------------------------------------------------


_VALID_STATES: frozenset[str] = frozenset({"ready", "refused"})


@dataclass(frozen=True)
class DraftQualityResult:
    """Per-draft Layer 2 result dataclass per ADR-0043 D213.

    The LOAD-BEARING refuse-loud surface for the
    hallucination-detection FIVE-layer defense per ADR-0038 D180
    Layer 2 — a ``state="ready"`` result with ``uncited_claims``
    non-empty MUST be refused at construction time.

    Attributes:
        draft_hash: ``sha256:<hex>`` of the draft body (privacy
            per I8 + ADR-0038 §Compliance with invariants — the
            raw draft text is NOT carried).
        register: Closed-enum per ADR-0038 D178 (one of
            :data:`voice_corpus.REGISTERS`).
        channel: Closed-enum per ADR-0014 D33 (one of
            :data:`voice_corpus.CHANNELS`).
        parsed_claims: Tuple of ALL claims extracted from the
            draft (both cited + uncited). The Layer 3 parser
            populates this field.
        uncited_claims: Tuple of the parsed_claims subset where
            ``citation_anchor is None``. The Layer 2 invariant
            consumes this field to decide the gate verdict.
        threshold: The per-register threshold consulted from the
            Week 4 loader per ADR-0041 D204 + ADR-0043 D215.
            Stamped at construction for downstream consumers
            (Week 8+ fidelity-scoring; Week 10 emit guard; Week
            12 reconcile heal-pass). Float in ``[0.0, 1.0]``.
        state: One of ``{"ready", "refused"}``. The Layer 2
            invariant gates: ``state="ready"`` AND
            ``uncited_claims`` non-empty is REFUSED at
            construction.

    Construction-time invariants (Layer 2 per ADR-0038 D180 +
    ADR-0043 D213):

    * ``draft_hash`` starts with ``"sha256:"``.
    * ``register`` in :data:`voice_corpus.REGISTERS`.
    * ``channel`` in :data:`voice_corpus.CHANNELS`.
    * ``parsed_claims`` is a tuple of :class:`ParsedClaim`.
    * ``uncited_claims`` is a tuple of :class:`ParsedClaim`.
    * Every member of ``uncited_claims`` IS a member of
      ``parsed_claims`` (subset invariant).
    * Every member of ``uncited_claims`` has
      ``citation_anchor is None``.
    * ``threshold`` is a float in ``[0.0, 1.0]``.
    * ``state`` in ``{"ready", "refused"}``.
    * **``state="ready"`` AND ``uncited_claims`` non-empty is
      REFUSED** — raises :exc:`ValueError` naming the per-claim
      trace + the operator-readable remediation. **This is THE
      Layer 2 invariant.**
    """

    draft_hash: str
    register: str
    channel: str
    parsed_claims: tuple[ParsedClaim, ...]
    uncited_claims: tuple[ParsedClaim, ...]
    threshold: float
    state: str

    def __post_init__(self) -> None:
        if not isinstance(self.draft_hash, str) or not self.draft_hash.startswith("sha256:"):
            raise ValueError(
                f"draft_hash must start with 'sha256:' prefix (privacy "
                f"invariant per I8 + ADR-0043 D213); got "
                f"{self.draft_hash!r}"
            )
        if self.register not in REGISTERS:
            raise ValueError(
                f"register {self.register!r} not in REGISTERS "
                f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum is "
                "closed + construction-time-validated"
            )
        if self.channel not in CHANNELS:
            raise ValueError(
                f"channel {self.channel!r} not in CHANNELS "
                f"{sorted(CHANNELS)!r}; per ADR-0014 D33 the enum is "
                "closed + construction-time-validated"
            )
        if self.state not in _VALID_STATES:
            raise ValueError(
                f"state {self.state!r} not in {sorted(_VALID_STATES)!r}; "
                "per ADR-0043 D213 the state is closed-set"
            )
        # bool catches before float coercion per the Pillar F Week 4
        # bool-is-an-int footgun pattern at ADR-0041 D201.
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)):
            raise ValueError(
                f"threshold must be a float in [0.0, 1.0]; got "
                f"{self.threshold!r} (type {type(self.threshold).__name__})"
            )
        if not (0.0 <= float(self.threshold) <= 1.0):
            raise ValueError(
                f"threshold {self.threshold!r} out of range [0.0, 1.0] "
                "per ADR-0041 D201 + ADR-0043 D213"
            )
        if not isinstance(self.parsed_claims, tuple):
            raise ValueError(
                "parsed_claims must be a tuple of ParsedClaim instances "
                "(tuple-typed for immutability per ADR-0043 D213)"
            )
        if not isinstance(self.uncited_claims, tuple):
            raise ValueError(
                "uncited_claims must be a tuple of ParsedClaim instances"
            )
        # Per Week 6 follow-up P2-1: per-item type validation so a
        # contributor passing dicts (or any non-ParsedClaim) sees the
        # refusal at construction site rather than at downstream
        # attribute access time. Without this guard, Week 8+/10/12
        # consumers iterating ``.claim_type`` / ``.claim_text`` /
        # ``.citation_anchor`` would see AttributeError at consumption
        # — bypassing the Layer 2 gate's structural commitment.
        for idx, item in enumerate(self.parsed_claims):
            if not isinstance(item, ParsedClaim):
                raise ValueError(
                    f"parsed_claims[{idx}] must be a ParsedClaim "
                    f"instance; got {type(item).__name__!r} per ADR-0043 "
                    "D213. The Layer 2 invariant requires every claim to "
                    "construction-time-validate so downstream consumers "
                    "(Week 8+ fidelity-scoring; Week 10 emit guard; "
                    "Week 12 reconcile heal-pass) read against the "
                    "typed shape."
                )
        for idx, item in enumerate(self.uncited_claims):
            if not isinstance(item, ParsedClaim):
                raise ValueError(
                    f"uncited_claims[{idx}] must be a ParsedClaim "
                    f"instance; got {type(item).__name__!r} per ADR-0043 "
                    "D213."
                )
        # Subset invariant — every uncited claim MUST appear in
        # parsed_claims. Operators can't surface uncited claims that
        # don't exist in the parse (per ADR-0043 D213).
        for uc in self.uncited_claims:
            if uc not in self.parsed_claims:
                raise ValueError(
                    f"uncited_claims member {uc!r} not in parsed_claims; "
                    "uncited_claims MUST be a subset per ADR-0043 D213"
                )
            if uc.citation_anchor is not None:
                raise ValueError(
                    f"uncited_claims member {uc!r} has non-None "
                    "citation_anchor; cited claims belong in "
                    "parsed_claims only per ADR-0043 D213"
                )
        # THE Layer 2 invariant per ADR-0038 D180 + ADR-0043 D213.
        # state="ready" + uncited non-empty is the structural refuse-
        # loud case.
        if self.state == "ready" and self.uncited_claims:
            raise ValueError(
                f"Refusing to construct a state='ready' "
                f"DraftQualityResult with non-empty uncited_claims "
                f"(count={len(self.uncited_claims)}); per ADR-0038 D180 "
                "Layer 2 + ADR-0043 D213 THE construction-time "
                "invariant catches the structurally invalid "
                "combination. Either set state='refused' (the "
                "operator-deliberate refuse-case) OR ensure every "
                "claim has a citation_anchor (the accept-case)."
            )


# ---------------------------------------------------------------------------
# Layer 3 — deterministic per-claim parser
# ---------------------------------------------------------------------------


# Date-reference regexes per ADR-0043 D214. ISO 8601 + month-year +
# quarter + relative-time phrases (the LLM-flavored draft patterns
# from cold-pitch / congrats / re-engagement registers).
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTH_YEAR_RE = re.compile(
    r"\b("
    r"January|February|March|April|May|June|"
    r"July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    r")\s+\d{4}\b",
    re.IGNORECASE,
)
_QUARTER_RE = re.compile(r"\bQ[1-4]\s*20\d{2}\b", re.IGNORECASE)
_RELATIVE_TIME_RE = re.compile(
    r"\b("
    r"last\s+(?:week|month|year|quarter)|"
    r"this\s+(?:week|month|year|quarter)|"
    r"yesterday|tomorrow|today|"
    r"a\s+few\s+(?:days|weeks|months)\s+ago|"
    r"recently|earlier\s+this\s+(?:week|month|year)"
    r")\b",
    re.IGNORECASE,
)


# Per ADR-0043 D214 — bare month names (no year) are date_reference
# claims when followed by an event noun OR appear alone. The pattern
# is bounded to standalone month names NOT immediately followed by a
# 4-digit year (those are caught by _MONTH_YEAR_RE).
_BARE_MONTH_RE = re.compile(
    r"\b("
    r"January|February|March|April|May|June|"
    r"July|August|September|October|November|December"
    r")\b(?!\s+\d{4})",
    re.IGNORECASE,
)


# Per ADR-0043 D214 — dated_event patterns directly catch the common
# "(<date>) (<event-noun>)" shape (e.g., "March launch", "Q1
# announcement", "last week's raise"). The event-noun vocabulary
# comes from the SKILL.md's register guidance + the cold-pitch /
# congrats vertical's typical event-mention patterns.
_EVENT_NOUN_PATTERN = (
    r"(?:launch|release|announcement|raise|funding|round|post|tweet|"
    r"blog|article|update|hire|departure|acquisition|deal|merger|"
    r"IPO|exit|pivot|product|feature|news|drop|push|unveiling|"
    r"reveal|appearance|talk|keynote|interview|podcast|episode|"
    r"essay|paper|writeup|memo|thread)"
)
_DATED_EVENT_PATTERN_RE = re.compile(
    r"\b(?:"
    # Bare month + event noun
    r"(?:January|February|March|April|May|June|"
    r"July|August|September|October|November|December)\s+"
    + _EVENT_NOUN_PATTERN +
    r"|"
    # Quarter + event noun (Q1 announcement; Q1 2026 raise)
    r"Q[1-4](?:\s*20\d{2})?\s+" + _EVENT_NOUN_PATTERN +
    r"|"
    # Relative time + event noun (last week's raise; this month's launch)
    r"(?:last|this)\s+(?:week|month|year|quarter)(?:'s|\s*)\s*"
    + _EVENT_NOUN_PATTERN +
    r"|"
    # Month + Year + event noun (March 2026 raise)
    r"(?:January|February|March|April|May|June|"
    r"July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{4}\s+"
    + _EVENT_NOUN_PATTERN +
    r")\b",
    re.IGNORECASE,
)


# Named-entity heuristic per ADR-0043 D214 — multi-word title-case
# span; stopwords filter false-positives. Single-word entities
# deferred (false-positive rate too high for v1).
_NAMED_ENTITY_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9]{2,}(?:\s+[A-Z][a-zA-Z0-9]+){1,4})\b"
)
_STOPWORD_ENTITY_FIRSTWORDS: frozenset[str] = frozenset({
    "I", "My", "Your", "We", "Our", "Us", "The", "An", "A", "Hi",
    "Hey", "Dear", "Yours", "Thanks", "Following", "Saw", "Loved",
    "Hello", "Goodbye", "But", "And", "Or", "So", "Also", "Then",
    "Now", "Today", "Yesterday", "Tomorrow", "When", "Where", "How",
    "Why", "What", "Who", "If", "Of", "On", "In", "At", "To",
    "From", "By", "With", "Without", "About", "Just", "Saw",
})


# You-phrase regex per ADR-0043 D214 — the LLM-flavored "you posted"
# / "you launched" / etc. patterns that need dossier citation. Verb
# list comes from the SKILL.md's register guidance.
_YOU_PHRASE_RE = re.compile(
    r"\byou\s+"
    r"(?:posted|mentioned|launched|wrote|said|shared|tweeted|"
    r"announced|raised|hired|fired|joined|left|built|shipped|"
    r"released|published|noted|claimed|argued)\b"
    r"[^.!?\n]*[.!?\n]?",
    re.IGNORECASE,
)


# Quoted-text regex per ADR-0043 D214 — straight-quote spans. The
# Markdown-bold pattern (`**...**`) is NOT a claim (emphasis only).
_QUOTED_TEXT_RE = re.compile(r'"([^"\n]+)"')


def _extract_date_references(draft: str) -> list[tuple[str, int, int]]:
    """Extract `(text, start, end)` tuples for date-reference claims.

    Helper for :func:`parse_draft_for_claims`; private. Returns the
    deduplicated per-span list (first-occurrence wins for overlapping
    matches). Per ADR-0043 D214: ISO dates + month-year + quarter +
    relative-time + bare-month phrases.
    """
    found: list[tuple[str, int, int]] = []
    # Order matters: _MONTH_YEAR_RE before _BARE_MONTH_RE so the
    # year-bearing match (e.g., "March 2026") wins over the bare
    # month overlap (the bare-month regex's negative-lookahead
    # `(?!\s+\d{4})` also blocks the overlap; the ordering is
    # defensive).
    for regex in (
        _ISO_DATE_RE,
        _MONTH_YEAR_RE,
        _QUARTER_RE,
        _RELATIVE_TIME_RE,
        _BARE_MONTH_RE,
    ):
        for m in regex.finditer(draft):
            found.append((m.group(0), m.start(), m.end()))
    found.sort(key=lambda x: x[1])
    return found


def _extract_named_entities(draft: str) -> list[tuple[str, int, int]]:
    """Extract `(text, start, end)` for named-entity claims.

    Filters sentence-starter stopwords + drops spans that overlap
    earlier-found entities. Single-word entities deferred (false-
    positive rate too high for v1; per ADR-0043 D214).
    """
    found: list[tuple[str, int, int]] = []
    for m in _NAMED_ENTITY_RE.finditer(draft):
        text = m.group(0)
        first_word = text.split()[0]
        if first_word in _STOPWORD_ENTITY_FIRSTWORDS:
            continue
        found.append((text, m.start(), m.end()))
    return found


def _extract_you_phrases(draft: str) -> list[tuple[str, int, int]]:
    """Extract `(text, start, end)` for you-phrase claims."""
    found: list[tuple[str, int, int]] = []
    for m in _YOU_PHRASE_RE.finditer(draft):
        text = m.group(0).strip().rstrip(".!?")
        found.append((text, m.start(), m.end()))
    return found


def _extract_quoted_text(draft: str) -> list[tuple[str, int, int]]:
    """Extract `(text, start, end)` for quoted-text claims.

    Returns the QUOTED CONTENT (no surrounding quote marks).
    """
    found: list[tuple[str, int, int]] = []
    for m in _QUOTED_TEXT_RE.finditer(draft):
        content = m.group(1)
        # Span the quoted content (inside the quotes) — operators
        # see the literal claim span without quote ceremony.
        found.append((content, m.start(1), m.end(1)))
    return found


def _extract_dated_events(
    draft: str,
    date_spans: list[tuple[str, int, int]],
    entity_spans: list[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    """Extract `(text, start, end)` for dated_event claims.

    Two extraction paths per ADR-0043 D214:

    1. **Direct pattern** — `<date> <event-noun>` shapes (the "March
       launch" / "Q1 announcement" / "last week's raise" / "March
       2026 raise" patterns). Matches via :data:`_DATED_EVENT_PATTERN_RE`.
    2. **Date-near-entity** — a named entity within 5 tokens of a
       date reference. Spans from earlier-start to later-end so
       operators see the full event reference.
    """
    found: list[tuple[str, int, int]] = []

    # Path 1: direct date + event-noun patterns.
    for m in _DATED_EVENT_PATTERN_RE.finditer(draft):
        found.append((m.group(0), m.start(), m.end()))

    # Path 2: named entity within 5 tokens of a date reference.
    for d_text, d_start, d_end in date_spans:
        for e_text, e_start, e_end in entity_spans:
            if d_start < e_start:
                gap_text = draft[d_end:e_start]
            else:
                gap_text = draft[e_end:d_start]
            gap_tokens = len(gap_text.split())
            if gap_tokens > 5:
                continue
            start = min(d_start, e_start)
            end = max(d_end, e_end)
            found.append((draft[start:end], start, end))
    return found


# Citation cross-reference helpers per ADR-0043 D214.
_URL_RE = re.compile(r"https?://[^\s\)\]]+", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")
_FOOTNOTE_REF_RE = re.compile(r"\[(\d+)\](?!\()")
_FOOTNOTE_DEF_RE = re.compile(r"^\[(\d+)\]:\s*(\S+)", re.MULTILINE)


def _build_dossier_anchors(dossier: str) -> dict[str, str]:
    """Build a per-dossier anchor map for citation cross-reference.

    Returns ``{anchor_label: anchor_value}`` where the keys are
    indexable strings (footnote numbers, URL substrings, named
    section headers) and values are the operator-visible anchor
    (URL or line ref).

    Per ADR-0043 D214 the deterministic-first cross-reference is
    substring + regex (no encoding); per ADR-0046 D237 + D241 the
    fuzzy-match fallback ships at Week 9 via the ``embed_fn`` seam
    activated at :func:`_find_citation_anchor`.
    """
    anchors: dict[str, str] = {}
    # Footnote-style anchors: `[1]: https://...`
    for m in _FOOTNOTE_DEF_RE.finditer(dossier):
        num, url = m.group(1), m.group(2)
        anchors[f"[{num}]"] = url
    # Markdown links: `[text](https://...)`
    for m in _MARKDOWN_LINK_RE.finditer(dossier):
        text, url = m.group(1), m.group(2)
        anchors[text.lower()] = url
        anchors[url] = url
    # Bare URLs.
    for m in _URL_RE.finditer(dossier):
        url = m.group(0)
        anchors[url] = url
    return anchors


# Per ADR-0046 D238 — sentence-boundary regex for the dossier chunker.
# Matches `.!?` followed by whitespace OR end-of-paragraph. The
# negative lookbehind on `\d` avoids splitting numeric decimals
# (e.g., ``2.5 million``); the negative lookahead on `\w` avoids
# splitting ellipses + abbreviations. Per-paragraph boundaries
# (double-newline) ALSO split chunks.
_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<!\d)[.!?]+\s+(?=[A-Z\"'\(\[]|$)|\n\s*\n",
)


def _chunk_dossier_for_fuzzy_match(
    dossier: str,
) -> list[tuple[str, str | None]]:
    """Chunk the dossier into sentence-level units per ADR-0046 D238.

    Returns a list of ``(chunk_text, nearby_url | None)`` tuples.
    The chunker:

    1. Splits the dossier on sentence boundaries (``.!?`` followed
       by whitespace) AND paragraph boundaries (double-newline).
    2. Filters out chunks shorter than
       :data:`_FUZZY_CHUNK_MIN_CHARS` (10) — too noisy at the
       BAAI/bge-small-en-v1.5 model's 384-dim embedding resolution.
    3. Re-splits chunks longer than :data:`_FUZZY_CHUNK_MAX_CHARS`
       (500) on the next sentence boundary — embedding dilution on
       long texts degrades cosine discrimination.
    4. For each chunk, finds a URL within the chunk OR within ±200
       chars of the chunk's offset in the original dossier (the
       operator-visible anchor surfaced via
       :func:`_find_citation_anchor_fuzzy`).

    Per-parse amortization: :func:`parse_draft_for_claims` invokes
    this ONCE per parse + reuses the chunk list across all claims.
    """
    if not dossier or not dossier.strip():
        return []

    chunks_raw: list[tuple[str, int]] = []
    # Walk sentence boundaries; collect (chunk_text, start_offset).
    last_start = 0
    for m in _SENTENCE_BOUNDARY_RE.finditer(dossier):
        chunk = dossier[last_start:m.start()].strip()
        if chunk:
            chunks_raw.append((chunk, last_start))
        last_start = m.end()
    # Trailing chunk (after the last boundary).
    if last_start < len(dossier):
        chunk = dossier[last_start:].strip()
        if chunk:
            chunks_raw.append((chunk, last_start))

    # Filter short + re-split long.
    chunks: list[tuple[str, int]] = []
    for chunk_text, offset in chunks_raw:
        if len(chunk_text) < _FUZZY_CHUNK_MIN_CHARS:
            continue
        if len(chunk_text) <= _FUZZY_CHUNK_MAX_CHARS:
            chunks.append((chunk_text, offset))
            continue
        # Re-split long chunk on next sentence boundary or hard cap.
        sub_start = 0
        while sub_start < len(chunk_text):
            window_end = sub_start + _FUZZY_CHUNK_MAX_CHARS
            if window_end >= len(chunk_text):
                sub = chunk_text[sub_start:].strip()
                if len(sub) >= _FUZZY_CHUNK_MIN_CHARS:
                    chunks.append((sub, offset + sub_start))
                break
            # Find next sentence boundary within the window; else
            # hard-cap at the window end.
            sub_m = _SENTENCE_BOUNDARY_RE.search(chunk_text, sub_start, window_end)
            if sub_m:
                sub_end = sub_m.start()
                sub = chunk_text[sub_start:sub_end].strip()
                if len(sub) >= _FUZZY_CHUNK_MIN_CHARS:
                    chunks.append((sub, offset + sub_start))
                sub_start = sub_m.end()
            else:
                sub = chunk_text[sub_start:window_end].strip()
                if len(sub) >= _FUZZY_CHUNK_MIN_CHARS:
                    chunks.append((sub, offset + sub_start))
                sub_start = window_end

    # Attach nearby URLs (per-chunk).
    out: list[tuple[str, str | None]] = []
    for chunk_text, offset in chunks:
        window_start = max(0, offset - 200)
        window_end = min(len(dossier), offset + len(chunk_text) + 200)
        window = dossier[window_start:window_end]
        url_m = _URL_RE.search(window)
        nearby_url = url_m.group(0) if url_m else None
        out.append((chunk_text, nearby_url))
    return out


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute the cosine similarity between two vectors.

    Assumes inputs may or may not be unit-normalized; computes the
    normalized cosine explicitly to avoid downstream surprises.
    Returns ``0.0`` when either vector is the zero vector (avoids
    division-by-zero; semantically "no signal").
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def _find_citation_anchor_fuzzy(
    claim_text: str,
    chunks: list[tuple[str, str | None]],
    *,
    embed_fn: Callable[[str], np.ndarray],
    threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> str | None:
    """Fuzzy-match a claim against pre-chunked dossier text per ADR-0046 D238.

    Returns the operator-visible anchor of the best-matching chunk
    if its cosine similarity to the claim meets ``threshold``; else
    ``None``. The anchor is the chunk's nearby URL when available
    (per :func:`_chunk_dossier_for_fuzzy_match`); else
    ``"dossier:fuzzy-match@chunk-{index}"`` (the chunk index in the
    chunk list — operator-readable diagnostic surface per ADR-0046
    §Compliance with invariants — privacy I8 preserved: the chunk's
    BODY is NEVER in the anchor string).

    Args:
        claim_text: The draft's literal claim span. Encoded once via
            ``embed_fn``.
        chunks: The pre-computed dossier chunks per
            :func:`_chunk_dossier_for_fuzzy_match`. Empty list → return
            ``None`` (no fuzzy match possible).
        embed_fn: The encoder. **MUST be supplied** (no lazy-load at
            this level; lazy-load happens at
            :func:`parse_draft_for_claims` per ADR-0046 D241). Tests
            substitute via deterministic stub.
        threshold: The cosine-similarity cutoff. Defaults to
            :data:`DEFAULT_FUZZY_CITATION_THRESHOLD` (``0.85``) per
            ADR-0046 D239. Validated in
            :func:`parse_draft_for_claims` (range
            ``[0.0, 1.0]``).

    Returns:
        The anchor string on match; ``None`` on no match.

    Raises:
        ValueError: if ``embed_fn`` is ``None`` (the caller MUST
            supply per ADR-0046 D238's invariant — lazy-load happens
            upstream at the parser surface).
    """
    if embed_fn is None:
        raise ValueError(
            "embed_fn must be supplied to _find_citation_anchor_fuzzy; "
            "lazy-load happens at parse_draft_for_claims per ADR-0046 "
            "D241"
        )
    if not chunks:
        return None
    if not claim_text or not claim_text.strip():
        return None

    claim_emb = embed_fn(claim_text)
    best_idx = -1
    best_score = -1.0
    best_anchor: str | None = None
    for idx, (chunk_text, nearby_url) in enumerate(chunks):
        chunk_emb = embed_fn(chunk_text)
        score = _cosine_similarity(claim_emb, chunk_emb)
        if score > best_score:
            best_score = score
            best_idx = idx
            best_anchor = nearby_url
    if best_score < threshold:
        return None
    # Operator-readable: prefer the chunk's nearby URL; else surface
    # the chunk index in a privacy-respecting diagnostic string.
    if best_anchor is not None:
        return best_anchor
    return f"dossier:fuzzy-match@chunk-{best_idx}"


def _find_citation_anchor(
    claim_text: str,
    dossier: str,
    anchors: dict[str, str],
    claim_type: str,
    *,
    dossier_chunks: list[tuple[str, str | None]] | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> str | None:
    """Find the matching dossier anchor for a claim per ADR-0043 D214 + ADR-0046 D237 + D240.

    Cross-reference strategy (deterministic-first, fuzzy-fallback):

    * ``quoted_text`` claims require VERBATIM (token-for-token)
      match in the dossier per ADR-0043 D214 + ADR-0046 D240. Fuzzy
      match SKIPS quoted_text unconditionally — operators citing a
      literal quote MUST trace the quote to the verbatim source;
      paraphrased quotes are a misattribution semantic the fuzzy
      path does not paper over.
    * Other claim types match if the claim_text appears as a
      substring in the dossier OR overlaps with a markdown-link's
      anchor text OR appears near a footnote reference. When the
      deterministic-first path returns ``None`` AND
      ``dossier_chunks`` + ``embed_fn`` are supplied (per ADR-0046
      D241 — lazy-loaded at :func:`parse_draft_for_claims` when
      caller doesn't supply), the fuzzy fallback runs.

    Per ADR-0046 D237 the always-on fuzzy fallback (when the seam
    is wired) is the addressing path for the Week 7 baseline FN_rate
    gap on ``named_entity`` (53%) + ``dated_event`` (40%) corpora;
    the W7 corpus's negation-prose refused pairs structurally limit
    the demonstrable WIN per ADR-0046 D242, and the fuzzy match's
    value lands when operators run against real (non-synthetic)
    dossiers + at the Week 10+ corpus revision per the operator-
    deferred trajectory. The FP_rate is bounded by the 0.85 cosine
    threshold calibration per ADR-0046 D239.

    Returns the operator-visible anchor (URL or line-ref) on
    match; ``None`` on no match (the uncited case).
    """
    if claim_type == "quoted_text":
        if claim_text in dossier:
            # Find a URL near the verbatim quote, if available.
            idx = dossier.find(claim_text)
            window = dossier[max(0, idx - 200):idx + len(claim_text) + 200]
            url_m = _URL_RE.search(window)
            if url_m:
                return url_m.group(0)
            return f"dossier:verbatim-match@offset-{idx}"
        # Per ADR-0046 D240 — quoted_text SKIPS fuzzy fallback. The
        # verbatim invariant per ADR-0043 D214 is preserved.
        return None

    # Other claim types: substring search in the dossier (case-
    # insensitive). For named_entity + dated_event, anchor mapping
    # via the markdown-link text key works when the operator wrote
    # the entity name verbatim in a dossier link.
    cl_lower = claim_text.lower()
    if cl_lower in dossier.lower():
        # Find any URL nearby (within ±200 chars of the match) for the
        # anchor surfacing.
        idx = dossier.lower().find(cl_lower)
        window = dossier[max(0, idx - 200):idx + len(claim_text) + 200]
        url_m = _URL_RE.search(window)
        if url_m:
            return url_m.group(0)
        # Footnote ref nearby?
        fn_m = _FOOTNOTE_REF_RE.search(window)
        if fn_m and f"[{fn_m.group(1)}]" in anchors:
            return anchors[f"[{fn_m.group(1)}]"]
        return f"dossier:match@offset-{idx}"

    # Markdown link key match: the entity name IS the link text.
    if cl_lower in anchors:
        return anchors[cl_lower]

    # Per ADR-0046 D240 — ``you_phrase`` ALSO SKIPS the fuzzy fallback
    # (the attribution semantic — "YOU posted X" — is corrupted by
    # paraphrase tolerance; a dossier with "X was posted" passive-
    # voiced does NOT support the operator's direct attribution to
    # the prospect). The you_phrase exclusion mirrors quoted_text's
    # verbatim-only invariant per ADR-0043 D214 + ADR-0046 D240.
    if claim_type == "you_phrase":
        return None

    # Fuzzy fallback (Week 9 — ADR-0046 D237) — runs only when the
    # caller wired the embed_fn + chunks (lazy-loaded by
    # parse_draft_for_claims per ADR-0046 D241; tests can disable
    # by passing embed_fn=None at the parser surface). Applies only
    # to ``date_reference`` + ``named_entity`` + ``dated_event`` per
    # ADR-0046 D240's attribution-claim exclusion list.
    if embed_fn is not None and dossier_chunks is not None:
        return _find_citation_anchor_fuzzy(
            claim_text,
            dossier_chunks,
            embed_fn=embed_fn,
            threshold=fuzzy_threshold,
        )
    return None


def parse_draft_for_claims(
    draft: str,
    dossier: str,
    *,
    register: str,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> list[ParsedClaim]:
    """Layer 3 per-claim extractor per ADR-0043 D214 + ADR-0046 D237.

    Walks the draft + extracts every claim per the five
    :data:`CLAIM_TYPES`. For each extracted claim, cross-references
    against the research dossier to populate ``citation_anchor``;
    uncited claims have ``citation_anchor is None``.

    **Deterministic-first cross-reference** (Week 6 per ADR-0043
    D214): substring + markdown-link-key + footnote-ref against the
    dossier. **Fuzzy-fallback** (Week 9 per ADR-0046 D237 + D238):
    when the deterministic path returns ``None`` AND
    ``claim_type != "quoted_text"`` (per ADR-0046 D240's verbatim-
    only invariant for quoted_text), the parser encodes the claim +
    each dossier chunk + returns the best-matching chunk's anchor
    if cosine ≥ ``fuzzy_threshold`` (default ``0.85`` per ADR-0046
    D239's empirical calibration against the Week 7 corpus). Per
    ADR-0046 D240, ``you_phrase`` ALSO skips the fuzzy fallback (the
    YOU attribution semantic is corrupted by passive-voice
    paraphrase).

    The deterministic per-claim extraction stays deterministic
    (regex-based); the fuzzy fallback's encoding is reproducible
    from ``(draft, dossier, register, embed_fn)`` per ADR-0013 D24.

    Args:
        draft: The draft text to parse (e.g., the Phase 3.5 prose
            assembly output).
        dossier: The research dossier (e.g., the Phase 1
            ``/research-prospect`` output). Carries citation
            anchors (URLs, markdown links, footnote refs) the
            parser cross-references against; ALSO the source for
            the fuzzy-fallback's sentence-level chunks per ADR-0046
            D238.
        register: The draft's register (closed-enum per ADR-0038
            D178). Validated BEFORE extraction; unknown register
            raises :exc:`ValueError`.
        cfg: Pre-loaded config dict (passed to
            :func:`voice_corpus._resolve_embed_model` when
            lazy-resolving the encoder per ADR-0046 D241). Defaults
            to ``None`` (loader resolves from the framework config).
        embed_fn: **TEST-ONLY** per ADR-0043 D218 + ADR-0046 D243.
            At Week 9 this seam ACTIVATES the fuzzy-fallback path
            at :func:`_find_citation_anchor`; the FIRST behavioral
            consumption at the parser surface (Week 6 + 7 + 8 were
            passthrough-only at this surface). When supplied,
            replaces the lazy-loaded framework default (per
            ADR-0046 D241). **Operators MUST NOT inject custom
            encoders at production callsites** — the framework's
            encoder is the operator-deliberate selection per
            ADR-0039 D188. The CLI does NOT surface a corresponding
            ``--embed-fn`` flag (security + audit per ADR-0039
            D188-Alt3 + ADR-0046 D237). To DISABLE the fuzzy
            fallback in tests, pass
            ``embed_fn=lambda _: numpy.zeros(384, dtype=numpy.float32)``
            — a stub that returns zero vectors yields cosine 0
            against every chunk, never crossing the threshold.
        fuzzy_threshold: The cosine cutoff for the fuzzy fallback
            per ADR-0046 D239. Defaults to
            :data:`DEFAULT_FUZZY_CITATION_THRESHOLD` (``0.85``).
            Validated as a float in ``[0.0, 1.0]`` (bool catch per
            ADR-0041 D201).

    Returns:
        The per-claim trace list. Every extracted claim appears
        (both cited + uncited); the caller filters by
        ``citation_anchor is None`` to get the uncited subset
        for the :class:`DraftQualityResult` Layer 2 gate.

    Raises:
        ValueError: if ``register`` is not in
            :data:`voice_corpus.REGISTERS` (closed-enum per
            ADR-0038 D178); if ``fuzzy_threshold`` is not a float
            in ``[0.0, 1.0]`` per ADR-0046 D239.
    """
    if register not in REGISTERS:
        raise ValueError(
            f"register {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum is "
            "closed-set"
        )
    # Per ADR-0041 D201's bool-catch footgun + ADR-0046 D239's
    # threshold range validation.
    if isinstance(fuzzy_threshold, bool) or not isinstance(
        fuzzy_threshold, (int, float)
    ):
        raise ValueError(
            f"fuzzy_threshold must be a float in [0.0, 1.0]; got "
            f"{fuzzy_threshold!r} (type={type(fuzzy_threshold).__name__})"
        )
    if not (0.0 <= float(fuzzy_threshold) <= 1.0):
        raise ValueError(
            f"fuzzy_threshold must be in [0.0, 1.0]; got "
            f"{fuzzy_threshold!r}"
        )

    if not draft:
        return []

    date_spans = _extract_date_references(draft)
    entity_spans = _extract_named_entities(draft)
    you_spans = _extract_you_phrases(draft)
    quote_spans = _extract_quoted_text(draft)
    dated_event_spans = _extract_dated_events(draft, date_spans, entity_spans)

    # Deduplicate within-type by exact text + start offset to avoid
    # double-counting overlapping regex matches.
    def _dedupe(spans: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
        seen: set[tuple[str, int]] = set()
        out: list[tuple[str, int, int]] = []
        for s in spans:
            key = (s[0], s[1])
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    anchors = _build_dossier_anchors(dossier)

    # Per ADR-0046 D238 + D241 — compute dossier chunks ONCE per
    # parse + lazy-resolve the encoder when the caller doesn't
    # supply ``embed_fn``. The chunk computation is cheap (string
    # ops); the encoder lazy-load amortizes across the per-process
    # cache from ADR-0039 D188.
    dossier_chunks = _chunk_dossier_for_fuzzy_match(dossier)
    resolved_embed_fn = embed_fn
    if resolved_embed_fn is None and dossier_chunks:
        # Lazy-load the framework default per ADR-0046 D241. The
        # local import avoids importing the heavyweight model at
        # module load time + lets the test suite stub embed_fn
        # without triggering the lazy-load.
        from voice_corpus import _default_embed_fn, _resolve_embed_model
        embed_model = _resolve_embed_model(None, cfg)
        resolved_embed_fn = _default_embed_fn(embed_model)

    claims: list[ParsedClaim] = []
    for claim_type, spans in (
        ("date_reference", _dedupe(date_spans)),
        ("named_entity", _dedupe(entity_spans)),
        ("you_phrase", _dedupe(you_spans)),
        ("quoted_text", _dedupe(quote_spans)),
        ("dated_event", _dedupe(dated_event_spans)),
    ):
        for text, _, _ in spans:
            anchor = _find_citation_anchor(
                text,
                dossier,
                anchors,
                claim_type,
                dossier_chunks=dossier_chunks,
                embed_fn=resolved_embed_fn,
                fuzzy_threshold=float(fuzzy_threshold),
            )
            claims.append(ParsedClaim(
                claim_type=claim_type,
                claim_text=text,
                citation_anchor=anchor,
            ))
    return claims


# ---------------------------------------------------------------------------
# score_draft — composite Layer 2 + Layer 3 entry point
# ---------------------------------------------------------------------------


def _hash_draft(draft: str) -> str:
    """SHA256-prefixed hex of the draft string — privacy per I8."""
    return "sha256:" + hashlib.sha256(draft.encode("utf-8")).hexdigest()


def score_draft(
    draft: str,
    dossier: str,
    *,
    register: str,
    channel: str,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> DraftQualityResult:
    """Composite Layer 2 + Layer 3 entry point per ADR-0043 D215.

    Per-call dispatch:

    1. Validate ``register`` + ``channel`` BEFORE parser load
       (closed-enum per ADR-0038 D178 + ADR-0014 D33).
    2. Resolve the per-register threshold via the Pillar F Week 4
       loader (:func:`voice_corpus.get_voice_threshold_for_register`
       per ADR-0041 D204).
    3. Parse draft + cross-reference against dossier (Layer 3 per
       :func:`parse_draft_for_claims`). Per ADR-0046 D237 the
       parser's per-claim cross-reference is deterministic-first
       with fuzzy-fallback (the fuzzy path activates when the
       deterministic path returns ``None`` AND the claim isn't
       quoted_text).
    4. Decide state: ``"ready"`` when ``uncited_claims`` is empty;
       ``"refused"`` when non-empty.
    5. Construct :class:`DraftQualityResult` (Layer 2 invariant
       runs at construction site).

    Per ADR-0043 D215 the per-register threshold is STAMPED on the
    result for downstream consumers (Week 8+ fidelity-scoring +
    Week 10 Layer 4 emit guard + Week 12 Layer 5 reconcile heal-
    pass); the Week 6 gate decision is binary (uncited non-empty
    → refused, REGARDLESS of the threshold value at Week 6). Per-
    claim severity weighting against the threshold lands at Week
    8+.

    Args:
        draft: The draft text (Phase 3.5 prose assembly output).
        dossier: The research dossier (Phase 1
            ``/research-prospect`` output).
        register: The draft's register (closed-enum per ADR-0038
            D178).
        channel: The draft's channel (closed-enum per ADR-0014 D33).
        thresholds_path: Override the per-register threshold
            config path; passed through to
            :func:`voice_corpus.get_voice_threshold_for_register`.
        cfg: Pre-loaded config dict; passed through (to the
            threshold loader AND to :func:`parse_draft_for_claims`
            for the fuzzy-fallback's encoder lazy-load per ADR-0046
            D241).
        embed_fn: **TEST-ONLY** per ADR-0043 D218 + ADR-0046 D243.
            At Week 9 this seam ACTIVATES the fuzzy-fallback path
            at :func:`parse_draft_for_claims`; the kwarg is reserved
            for the test suite (operators DO NOT inject custom
            encoders at production callsites — the framework's
            encoder is the operator-deliberate selection per
            ADR-0039 D188). The CLI does NOT surface a
            corresponding ``--embed-fn`` flag (security + audit
            per ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1).
        fuzzy_threshold: The cosine cutoff for the fuzzy fallback
            per ADR-0046 D239. Defaults to
            :data:`DEFAULT_FUZZY_CITATION_THRESHOLD` (``0.85``).
            Validated in :func:`parse_draft_for_claims`.

    Returns:
        The :class:`DraftQualityResult` carrying:

        * ``draft_hash`` = sha256 of the draft body.
        * ``register`` + ``channel`` as supplied.
        * ``parsed_claims`` = all extracted claims (cited + uncited).
        * ``uncited_claims`` = the parsed_claims subset where
          ``citation_anchor is None``.
        * ``threshold`` = the per-register threshold from the Week
          4 loader (stamped for downstream consumers).
        * ``state`` = ``"ready"`` (uncited empty) | ``"refused"``
          (uncited non-empty).

    Raises:
        ValueError: if ``register`` not in
            :data:`voice_corpus.REGISTERS` OR ``channel`` not in
            :data:`voice_corpus.CHANNELS`. The Week 4 loader's
            errors (missing required register key; out-of-range
            value; malformed YAML) propagate unchanged. If
            ``fuzzy_threshold`` is out of range per ADR-0046 D239,
            :func:`parse_draft_for_claims` raises.
    """
    # Per ADR-0055 D301 — wrap the body in a review-stage span so
    # operators see per-draft Layer 2-3 timing in the OTel tracing
    # backend. Privacy invariant per I8 + ADR-0054 D297 + ADR-0055
    # D304 — neither ``draft_body`` nor ``dossier_body`` enters the
    # span attributes; only the closed-enum register + channel +
    # resulting state surfaces.
    with traced_stage(
        "review", "score_draft",
        attributes={"register": register, "channel": channel},
    ) as _span:
        # Validate closed-enums BEFORE parser load (faster failure
        # surface for operator misconfiguration).
        if register not in REGISTERS:
            raise ValueError(
                f"register {register!r} not in REGISTERS "
                f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum "
                "is closed-set"
            )
        if channel not in CHANNELS:
            raise ValueError(
                f"channel {channel!r} not in CHANNELS "
                f"{sorted(CHANNELS)!r}; per ADR-0014 D33 the enum is "
                "closed-set"
            )

        # Resolve threshold via Week 4 loader.
        threshold = get_voice_threshold_for_register(
            register,
            thresholds_path=thresholds_path,
            cfg=cfg,
        )

        # Parse + cross-reference (Layer 3 per ADR-0043 D214 +
        # ADR-0046 D237's deterministic-first + fuzzy-fallback
        # pipeline).
        claims = parse_draft_for_claims(
            draft, dossier,
            register=register,
            cfg=cfg,
            embed_fn=embed_fn,
            fuzzy_threshold=fuzzy_threshold,
        )

        uncited = tuple(c for c in claims if c.citation_anchor is None)
        state = "refused" if uncited else "ready"

        # Stamp the resulting state on the span so operators querying
        # the tracing backend can filter per result_state per
        # ADR-0055 D301 (the result_state attribute is in the
        # _SPAN_ATTRIBUTES_ALLOWED closed-set per ADR-0054 D297).
        _span.set_attribute("result_state", state)

        # Construct (Layer 2 invariant runs at construction).
        return DraftQualityResult(
            draft_hash=_hash_draft(draft),
            register=register,
            channel=channel,
            parsed_claims=tuple(claims),
            uncited_claims=uncited,
            threshold=threshold,
            state=state,
        )


# ---------------------------------------------------------------------------
# build_hallucination_detected_payload — event-shape factory
# ---------------------------------------------------------------------------


def build_hallucination_detected_payload(
    *,
    person_id: str | None,
    result: DraftQualityResult,
    channel: str,
    register: str,
) -> dict:
    """Build the ``hallucination_detected`` event payload per
    ADR-0043 D216.

    The factory is the structured surface for the Layer 2 + Layer
    3 refusal event. **Emit-only-on-uncited per ADR-0043 D219** —
    the factory refuses construction when ``result.uncited_claims``
    is empty (the accept-case should not flow through the factory).

    Event shape:

    .. code-block:: text

        type:           hallucination_detected
        person_id       (the prospect the draft targets; None for
                         ad-hoc validation)
        draft_hash      (sha256:<hex> of the draft body — NOT the
                         raw draft per I8)
        register        (closed-enum per ADR-0038 D178)
        channel         (closed-enum per ADR-0014 D33)
        threshold       (per-register threshold consulted per D215)
        uncited_claims  (list of {claim_type, claim_text,
                         citation_anchor: None} tuples)
        _emitted_by     ("draft_quality" per ADR-0010 D17)

    Privacy-respecting per I8 + ADR-0038 §Compliance with
    invariants:

    * **Raw draft body MUST NOT appear in the payload.** The draft
      is sha256-hashed at the result construction site.
    * **Per-claim trace IS in the payload** — ``claim_text`` is
      the draft's literal claim span (operator-visible diagnostic
      for "which claim did the gate catch"); the dossier content
      is NOT in the payload (the ``citation_anchor`` for cited
      claims is URL OR line-ref).

    Args:
        person_id: The prospect the draft targets. ``None`` is
            accepted for ad-hoc operator validation outside the
            per-Person flow.
        result: The :class:`DraftQualityResult`. Must carry
            non-empty ``uncited_claims`` per D219.
        channel: The draft's channel (per channel-on-every-event
            invariant per ADR-0014 D33). MUST be in
            :data:`voice_corpus.CHANNELS`; raises
            :exc:`ValueError` on unknown.
        register: The draft's register. MUST be in
            :data:`voice_corpus.REGISTERS`; raises
            :exc:`ValueError` on unknown.

    Returns:
        The event payload dict (no ``ts`` — that's set by
        :meth:`Ledger.append`).

    Raises:
        ValueError: when ``channel`` is not in
            :data:`voice_corpus.CHANNELS`, ``register`` is not in
            :data:`voice_corpus.REGISTERS`, OR
            ``result.uncited_claims`` is empty (accept-case is
            silent default per D219).
    """
    if channel not in CHANNELS:
        raise ValueError(
            f"channel {channel!r} not in CHANNELS "
            f"{sorted(CHANNELS)!r} per ADR-0014 D33 + ADR-0043 D216"
        )
    if register not in REGISTERS:
        raise ValueError(
            f"register {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r} per ADR-0038 D178 + ADR-0043 D216"
        )
    # Per Week 6 follow-up P2-2: the factory's channel + register
    # kwargs must match the result's stamped values (the result was
    # constructed against a specific channel + register; the factory
    # MUST surface the same values in the event payload). Without this
    # check, a caller passing mismatched values silently emits an
    # event claiming a different channel/register than the draft was
    # scored against — the per-Pillar-G dashboard's per-register
    # aggregation would surface phantom signals + Pillar I per-tenant
    # audit-tooling would surface phantom refusal-rate divergence.
    if channel != result.channel:
        raise ValueError(
            f"channel {channel!r} does not match result.channel "
            f"{result.channel!r}; per ADR-0043 D216 the factory MUST "
            "stamp the same channel the draft was scored against. The "
            "caller passed inconsistent values — fix the call site."
        )
    if register != result.register:
        raise ValueError(
            f"register {register!r} does not match result.register "
            f"{result.register!r}; per ADR-0043 D216 the factory MUST "
            "stamp the same register the draft was scored against."
        )
    if not result.uncited_claims:
        raise ValueError(
            "Refusing to build hallucination_detected payload with "
            "empty uncited_claims; per ADR-0043 D219 the event is "
            "emit-only-on-uncited (the accept-case is the silent "
            "default). Caller bug — the accept-case should NOT flow "
            "through the factory."
        )

    uncited_payload = [
        {
            "claim_type": c.claim_type,
            "claim_text": c.claim_text,
            "citation_anchor": c.citation_anchor,
        }
        for c in result.uncited_claims
    ]
    return {
        "type": "hallucination_detected",
        "person_id": person_id,
        "draft_hash": result.draft_hash,
        "register": register,
        "channel": channel,
        "threshold": result.threshold,
        "uncited_claims": uncited_payload,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# Pillar F Week 7 — per-claim-type corpus + measurement primitive
# ---------------------------------------------------------------------------


# Per ADR-0044 D222 — closed-set of valid ``expected_state`` values
# in per-pair corpus YAML files; mirrors :data:`_VALID_STATES` for the
# :class:`DraftQualityResult` state-level enum. Construction-time
# validation on :class:`CorpusPair` refuses-loud on unknown values.
_VALID_EXPECTED_STATES: frozenset[str] = frozenset({"ready", "refused"})


@dataclass(frozen=True)
class CorpusPair:
    """One labeled corpus pair per ADR-0044 D222.

    The per-pair structure in
    ``tests/fixtures/draft_quality_corpus/<claim_type>.yml`` — a
    synthetic ``(draft, dossier, expected_state)`` triple labeled
    with operator judgment.

    Attributes:
        id: Corpus-unique pair identifier. Non-empty string.
        draft: The synthetic draft text. Non-empty string.
        dossier: The synthetic research dossier text. Non-empty
            string.
        expected_state: Operator-judgment ground truth — one of
            ``{"ready", "refused"}`` per ADR-0044 D222.

            * ``ready`` — every claim a thoughtful operator
              extracts from the draft has a matching dossier
              anchor.
            * ``refused`` — at least one claim has no matching
              anchor; the operator would re-draft OR stamp
              ``hallucination_check_override`` per ADR-0043 D217.
        notes: Optional operator-readable rationale. Documentation-
            only; NOT validated.

    Construction-time invariants (per ADR-0044 D222):

    * ``id``, ``draft``, ``dossier`` are non-empty strings.
    * ``expected_state`` is in :data:`_VALID_EXPECTED_STATES`.
    """

    id: str
    draft: str
    dossier: str
    expected_state: str
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError(
                f"id must be a non-empty string; got {self.id!r}"
            )
        if not isinstance(self.draft, str) or not self.draft.strip():
            raise ValueError(
                f"draft must be a non-empty string; got {self.draft!r}"
            )
        if not isinstance(self.dossier, str) or not self.dossier.strip():
            raise ValueError(
                f"dossier must be a non-empty string; got {self.dossier!r}"
            )
        if self.expected_state not in _VALID_EXPECTED_STATES:
            raise ValueError(
                f"expected_state {self.expected_state!r} not in "
                f"{sorted(_VALID_EXPECTED_STATES)!r}; per ADR-0044 D222 "
                "the corpus's ground truth is a closed-enum."
            )


@dataclass(frozen=True)
class CorpusMeasurement:
    """Per-claim-type corpus measurement result per ADR-0044 D223.

    Aggregates the per-pair :func:`score_draft` outcomes against
    the corpus's ``expected_state`` ground truth + computes the
    per-claim-type accuracy + false-positive rate + false-negative
    rate.

    Cell definitions per ADR-0044 D223:

    * **TP (true positive)** — parser said ``refused`` AND corpus
      says ``refused`` (correct catch).
    * **TN (true negative)** — parser said ``ready`` AND corpus
      says ``ready`` (correct accept).
    * **FP (false positive)** — parser said ``refused`` AND
      corpus says ``ready`` (over-eager catch; operator-friction
      cost).
    * **FN (false negative)** — parser said ``ready`` AND corpus
      says ``refused`` (missed catch; brand-risk cost per
      ADR-0038 D184's asymmetric-failure-cost calculus).

    The framework's asymmetric-failure-cost discipline per
    ADR-0038 D180 + D184 biases the gate toward false-positive
    (operator stamps an override) over false-negative (uncited
    claim ships). Per-claim-type rate bounds at
    ``tests/test_draft_quality_corpus.py::TestCorpusBenchmark``
    encode the Week 7 baseline regression-barrier targets.

    Attributes:
        claim_type: One of :data:`CLAIM_TYPES` (closed-enum per
            ADR-0038 D180 + ADR-0043 D214).
        register: The corpus's register (closed-enum per ADR-0038
            D178).
        channel: The corpus's channel (closed-enum per ADR-0014
            D33).
        pair_count: Total pairs in the corpus.
        true_positive: TP count.
        true_negative: TN count.
        false_positive: FP count.
        false_negative: FN count.
        accuracy: ``(TP + TN) / pair_count`` (float in
            ``[0.0, 1.0]``).
        false_positive_rate: ``FP / (FP + TN)`` (float in
            ``[0.0, 1.0]``; 0.0 when ``FP + TN == 0``).
        false_negative_rate: ``FN / (FN + TP)`` (float in
            ``[0.0, 1.0]``; 0.0 when ``FN + TP == 0``).

    Construction-time invariants (per ADR-0044 D223):

    * ``claim_type`` in :data:`CLAIM_TYPES`.
    * ``register`` in :data:`voice_corpus.REGISTERS`.
    * ``channel`` in :data:`voice_corpus.CHANNELS`.
    * All count fields are non-negative ints.
    * ``true_positive + true_negative + false_positive +
      false_negative == pair_count`` (the subset invariant).
    * All rate fields are floats in ``[0.0, 1.0]``.
    """

    claim_type: str
    register: str
    channel: str
    pair_count: int
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    accuracy: float
    false_positive_rate: float
    false_negative_rate: float

    def __post_init__(self) -> None:
        if self.claim_type not in CLAIM_TYPES:
            raise ValueError(
                f"claim_type {self.claim_type!r} not in CLAIM_TYPES "
                f"{sorted(CLAIM_TYPES)!r}; per ADR-0038 D180 + ADR-0043 "
                "D214 the enum is closed-set"
            )
        if self.register not in REGISTERS:
            raise ValueError(
                f"register {self.register!r} not in REGISTERS "
                f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum "
                "is closed-set"
            )
        if self.channel not in CHANNELS:
            raise ValueError(
                f"channel {self.channel!r} not in CHANNELS "
                f"{sorted(CHANNELS)!r}; per ADR-0014 D33 the enum is "
                "closed-set"
            )
        for field_name in (
            "pair_count", "true_positive", "true_negative",
            "false_positive", "false_negative",
        ):
            v = getattr(self, field_name)
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(
                    f"{field_name} must be a non-negative int; got "
                    f"{v!r} (type {type(v).__name__})"
                )
            if v < 0:
                raise ValueError(
                    f"{field_name} must be non-negative; got {v}"
                )
        # The subset invariant: TP + TN + FP + FN MUST == pair_count.
        # Without this, downstream consumers reading rates against
        # the pair_count would see inconsistent denominators.
        tally = (
            self.true_positive + self.true_negative
            + self.false_positive + self.false_negative
        )
        if tally != self.pair_count:
            raise ValueError(
                f"tally invariant violated: TP+TN+FP+FN={tally} != "
                f"pair_count={self.pair_count}. Per ADR-0044 D223 "
                "the per-pair outcomes partition the corpus."
            )
        for rate_name in (
            "accuracy", "false_positive_rate", "false_negative_rate",
        ):
            v = getattr(self, rate_name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(
                    f"{rate_name} must be a float in [0.0, 1.0]; got "
                    f"{v!r} (type {type(v).__name__})"
                )
            if not (0.0 <= float(v) <= 1.0):
                raise ValueError(
                    f"{rate_name} {v!r} out of range [0.0, 1.0] per "
                    "ADR-0044 D223"
                )


def _load_corpus_file(corpus_dir: Path, claim_type: str) -> dict:
    """Load + validate a per-claim-type corpus YAML file.

    Per ADR-0044 D222 + D226 — refuses-loud on unknown claim_type
    + missing corpus file + malformed YAML + mismatched
    claim_type field + unknown register/channel + per-pair
    missing-required-field.

    Args:
        corpus_dir: Path to the corpus directory (e.g.,
            ``tests/fixtures/draft_quality_corpus/``).
        claim_type: One of :data:`CLAIM_TYPES`.

    Returns:
        The parsed YAML dict with validated top-level fields +
        a ``pairs`` list of :class:`CorpusPair` instances under
        key ``"pairs_typed"`` (the raw YAML's ``pairs`` list is
        preserved under ``"pairs"`` for operator-readable
        access).

    Raises:
        ValueError: on closed-enum violations, missing fields,
            or invariant violations.
        FileNotFoundError: when the corpus file does not exist.
        yaml.YAMLError: on malformed YAML (propagates unchanged).
    """
    if claim_type not in CLAIM_TYPES:
        raise ValueError(
            f"claim_type {claim_type!r} not in CLAIM_TYPES "
            f"{sorted(CLAIM_TYPES)!r}; per ADR-0038 D180 + ADR-0043 "
            "D214 the enum is closed-set"
        )
    corpus_path = Path(corpus_dir).expanduser() / f"{claim_type}.yml"
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"corpus file not found: {corpus_path}. Per ADR-0044 "
            "D221 the corpus directory MUST carry one YAML file per "
            f"claim type in CLAIM_TYPES ({sorted(CLAIM_TYPES)!r})."
        )
    with corpus_path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"corpus file {corpus_path} must parse as a dict (got "
            f"{type(data).__name__}); per ADR-0044 D222 the top-level "
            "shape is `{version, claim_type, register, channel, pairs}`."
        )
    file_claim_type = data.get("claim_type")
    if file_claim_type != claim_type:
        raise ValueError(
            f"corpus file {corpus_path}: claim_type field "
            f"{file_claim_type!r} does not match filename "
            f"{claim_type!r}. Per ADR-0044 D222 + D226 the YAML's "
            "claim_type MUST match the filename."
        )
    register = data.get("register")
    if register not in REGISTERS:
        raise ValueError(
            f"corpus file {corpus_path}: register {register!r} not in "
            f"REGISTERS {sorted(REGISTERS)!r}; per ADR-0038 D178 the "
            "enum is closed-set."
        )
    channel = data.get("channel")
    if channel not in CHANNELS:
        raise ValueError(
            f"corpus file {corpus_path}: channel {channel!r} not in "
            f"CHANNELS {sorted(CHANNELS)!r}; per ADR-0014 D33 the "
            "enum is closed-set."
        )
    pairs_raw = data.get("pairs")
    if not isinstance(pairs_raw, list) or not pairs_raw:
        raise ValueError(
            f"corpus file {corpus_path}: pairs must be a non-empty "
            f"list; got {type(pairs_raw).__name__}. Per ADR-0044 "
            "D221 each corpus file ships at least one labeled pair."
        )
    seen_ids: set[str] = set()
    typed_pairs: list[CorpusPair] = []
    for idx, raw in enumerate(pairs_raw):
        if not isinstance(raw, dict):
            raise ValueError(
                f"corpus file {corpus_path}: pairs[{idx}] must be a "
                f"dict; got {type(raw).__name__}."
            )
        for required in ("id", "draft", "dossier", "expected_state"):
            if required not in raw:
                raise ValueError(
                    f"corpus file {corpus_path}: pairs[{idx}] missing "
                    f"required field {required!r}; per ADR-0044 D222."
                )
        pair = CorpusPair(
            id=raw["id"],
            draft=raw["draft"],
            dossier=raw["dossier"],
            expected_state=raw["expected_state"],
            notes=raw.get("notes"),
        )
        if pair.id in seen_ids:
            raise ValueError(
                f"corpus file {corpus_path}: duplicate pair id "
                f"{pair.id!r}; per ADR-0044 D222 pair ids are "
                "corpus-unique."
            )
        seen_ids.add(pair.id)
        typed_pairs.append(pair)
    data["pairs_typed"] = tuple(typed_pairs)
    return data


def measure_per_claim_type_false_positive_rate(
    corpus_dir: Path,
    claim_type: str,
    *,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_CITATION_THRESHOLD,
) -> CorpusMeasurement:
    """Measurement primitive per ADR-0044 D223.

    Walks the per-claim-type corpus at
    ``corpus_dir/<claim_type>.yml``, runs :func:`score_draft` per
    pair, aggregates outcomes against the ``expected_state`` ground
    truth + returns a :class:`CorpusMeasurement` with per-claim-
    type accuracy + false-positive rate + false-negative rate.

    The corpus is the operator-judgment ground-truth surface; the
    parser is the system under test. Per ADR-0044 R027 mitigation
    + the asymmetric-failure-cost discipline per ADR-0038 D180 +
    D184, the false-negative rate is the BRAND-RISK path (uncited
    claim ships) + the false-positive rate is the OPERATOR-FRICTION
    path (stamp an override). The Week 7 baseline measurement
    surfaces the per-claim-type calibration that Week 8+ fidelity-
    scoring + Week 10+ Layer 4/5 will tighten.

    Args:
        corpus_dir: Path to the corpus directory (e.g.,
            ``tests/fixtures/draft_quality_corpus/``).
        claim_type: One of :data:`CLAIM_TYPES`. Closed-enum per
            ADR-0038 D180 + ADR-0043 D214; refuses-loud on
            unknown.
        thresholds_path: Override the per-register threshold YAML
            path; passed through to :func:`score_draft` per ADR-
            0041 D204.
        cfg: Pre-loaded config dict; passed through to
            :func:`score_draft`.
        embed_fn: **TEST-ONLY** per ADR-0043 D218 + ADR-0044 D227 +
            ADR-0046 D243. Passthrough to :func:`score_draft` →
            :func:`parse_draft_for_claims`. At Week 9 this seam
            ACTIVATES the fuzzy-fallback path at the parser surface
            (the default code path lazy-loads the framework's
            encoder when ``embed_fn=None``); the measurement
            primitive's per-pair behavior reflects the fuzzy-match
            extension's verdict (`citation_anchor` populated from
            chunk's nearby URL OR `dossier:fuzzy-match@chunk-N`
            diagnostic). To DISABLE the fuzzy fallback in tests,
            pass ``embed_fn=lambda _: numpy.zeros(384,
            dtype=numpy.float32)``. The CLI does NOT surface a
            corresponding ``--embed-fn`` flag (security + audit per
            ADR-0039 D188-Alt3).
        fuzzy_threshold: The cosine cutoff for the fuzzy fallback
            per ADR-0046 D239. Defaults to
            :data:`DEFAULT_FUZZY_CITATION_THRESHOLD` (``0.85``).
            Passthrough to :func:`score_draft` → :func:`parse_draft_for_claims`
            where the range validation runs (float in ``[0.0, 1.0]``
            with bool catch per ADR-0041 D201).

    Returns:
        The :class:`CorpusMeasurement` with per-pair TP/TN/FP/FN
        tallies + per-claim-type accuracy + FP_rate + FN_rate.

    Raises:
        ValueError: on closed-enum violations, missing required
            fields, or any per-pair :func:`score_draft` failure
            (the underlying :func:`score_draft`'s closed-enum
            errors propagate).
        FileNotFoundError: when the per-claim-type corpus file
            does not exist at ``corpus_dir/<claim_type>.yml``.
        yaml.YAMLError: on malformed YAML (propagates unchanged).
    """
    data = _load_corpus_file(corpus_dir, claim_type)
    register: str = data["register"]
    channel: str = data["channel"]
    pairs: tuple[CorpusPair, ...] = data["pairs_typed"]

    tp = tn = fp = fn = 0
    for pair in pairs:
        result = score_draft(
            pair.draft,
            pair.dossier,
            register=register,
            channel=channel,
            thresholds_path=thresholds_path,
            cfg=cfg,
            embed_fn=embed_fn,
            fuzzy_threshold=fuzzy_threshold,
        )
        if pair.expected_state == "refused" and result.state == "refused":
            tp += 1
        elif pair.expected_state == "ready" and result.state == "ready":
            tn += 1
        elif pair.expected_state == "ready" and result.state == "refused":
            fp += 1
        elif pair.expected_state == "refused" and result.state == "ready":
            fn += 1
        # CorpusPair's __post_init__ guarantees expected_state is
        # in _VALID_EXPECTED_STATES; score_draft's Layer 2 invariant
        # guarantees result.state is in _VALID_STATES. The above four
        # branches partition the (expected_state, result.state)
        # product; no else clause needed.

    pair_count = len(pairs)
    accuracy = (tp + tn) / pair_count if pair_count > 0 else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fn_rate = fn / (fn + tp) if (fn + tp) > 0 else 0.0

    return CorpusMeasurement(
        claim_type=claim_type,
        register=register,
        channel=channel,
        pair_count=pair_count,
        true_positive=tp,
        true_negative=tn,
        false_positive=fp,
        false_negative=fn,
        accuracy=accuracy,
        false_positive_rate=fp_rate,
        false_negative_rate=fn_rate,
    )


# ===========================================================================
# Pillar F Week 8 — per-draft voice-fidelity scoring primitive (ADR-0045)
# ===========================================================================
#
# Per ADR-0038 D184(a) — voice-fidelity score is per-register operator-tunable;
# per-draft float in [0.0, 1.0] = cosine similarity between draft embedding and
# top-K voice-corpus exemplar embeddings (mean per ADR-0045 D230).
#
# Per ADR-0038 D182 — the third Pillar F event class:
# `draft_quality_scored` carries per-draft fidelity score + Pillar G dashboard
# substrate. **Emit-always** posture (vs Week 6's emit-only-on-uncited for
# `hallucination_detected`) — accept-case events are LOAD-BEARING for the
# per-register score distribution rendering.


# ---------------------------------------------------------------------------
# DraftFidelityResult — Layer 2 fidelity-scoring result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftFidelityResult:
    """Per-draft Layer 2 fidelity-scoring result per ADR-0045 D229.

    Symmetric with the Week 6 :class:`DraftQualityResult` per
    ADR-0043 D213. The LOAD-BEARING refuse-loud surface:
    ``state="ready"`` AND ``meets_threshold=False`` MUST be
    refused at construction (the per-register voice-fidelity
    threshold per ADR-0038 D184(a) gates the ``ready`` advance).

    Attributes:
        draft_hash: ``sha256:<hex>`` of the draft body (privacy
            per I8 + ADR-0038 §Compliance with invariants — the
            raw draft text is NOT carried).
        register: Closed-enum per ADR-0038 D178.
        channel: Closed-enum per ADR-0014 D33.
        voice_fidelity_score: The per-draft float in ``[0.0, 1.0]``
            per ADR-0038 D184(a). Computed as the mean of the
            top-K voice-corpus exemplars' per-exemplar scores
            (cosine × recency multiplier). Clamped to range by
            :func:`compute_draft_fidelity_score`.
        voice_fidelity_threshold: The per-register threshold
            consulted from the Week 4 loader
            (:func:`voice_corpus.get_voice_threshold_for_register`
            per ADR-0041 D204). Float in ``[0.0, 1.0]``.
        meets_threshold: Boolean stamp of
            ``voice_fidelity_score >= voice_fidelity_threshold``.
            Stored explicitly so downstream consumers (Pillar G
            dashboard; Week 10 Layer 4 emit guard; Week 12 Layer
            5 reconcile heal-pass) read against a stamped boolean
            (the invariant-check at construction guarantees
            consistency with the score/threshold pair).
        exemplar_ids: Tuple of the top-K voice-corpus exemplar
            IDs. Per-exemplar bodies are NOT stored (privacy per
            I8 — operators look up bodies via the corpus directly
            per ADR-0039 D189 precedent).
        k: The requested top-K (``len(exemplar_ids) <= k``).
        state: One of ``{"ready", "refused"}``. The Layer 2
            invariant gates: ``state="ready"`` AND
            ``meets_threshold=False`` is REFUSED.

    Construction-time invariants (Layer 2 per ADR-0045 D229):

    * ``draft_hash`` starts with ``"sha256:"``.
    * ``register`` in :data:`voice_corpus.REGISTERS`.
    * ``channel`` in :data:`voice_corpus.CHANNELS`.
    * ``voice_fidelity_score`` is a float in ``[0.0, 1.0]`` (bool
      catch per ADR-0041 D201).
    * ``voice_fidelity_threshold`` is a float in ``[0.0, 1.0]``
      (bool catch).
    * ``meets_threshold`` is a bool consistent with the
      score/threshold pair.
    * ``exemplar_ids`` is a tuple of strs (per-item type check
      mirrors Week 6 follow-up P2-1 per ADR-0043 D213).
    * ``k`` is a non-negative int (bool catch).
    * ``len(exemplar_ids) <= k`` (subset invariant — the
      framework's retrieval primitive may return fewer than K
      when filters narrow the corpus per ADR-0039 D188).
    * ``state`` in ``{"ready", "refused"}``.
    * **``state="ready"`` AND ``meets_threshold=False`` is
      REFUSED** per ADR-0038 D184(a) — the structural
      commitment of the Layer 2 invariant.
    """

    draft_hash: str
    register: str
    channel: str
    voice_fidelity_score: float
    voice_fidelity_threshold: float
    meets_threshold: bool
    exemplar_ids: tuple[str, ...]
    k: int
    state: str

    def __post_init__(self) -> None:
        if not isinstance(self.draft_hash, str) or not self.draft_hash.startswith("sha256:"):
            raise ValueError(
                f"draft_hash must start with 'sha256:' prefix (privacy "
                f"invariant per I8 + ADR-0045 D229); got "
                f"{self.draft_hash!r}"
            )
        if self.register not in REGISTERS:
            raise ValueError(
                f"register {self.register!r} not in REGISTERS "
                f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum is "
                "closed + construction-time-validated"
            )
        if self.channel not in CHANNELS:
            raise ValueError(
                f"channel {self.channel!r} not in CHANNELS "
                f"{sorted(CHANNELS)!r}; per ADR-0014 D33 the enum is "
                "closed + construction-time-validated"
            )
        if self.state not in _VALID_STATES:
            raise ValueError(
                f"state {self.state!r} not in {sorted(_VALID_STATES)!r}; "
                "per ADR-0045 D229 the state is closed-set"
            )
        # bool catch per ADR-0041 D201 footgun — `True` is an int
        # subclass; without the explicit catch, YAML `true` → 1.0
        # silently coerces past the range check.
        for name, value in (
            ("voice_fidelity_score", self.voice_fidelity_score),
            ("voice_fidelity_threshold", self.voice_fidelity_threshold),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"{name} must be a float in [0.0, 1.0]; got "
                    f"{value!r} (type {type(value).__name__}) per "
                    "ADR-0045 D229 + ADR-0041 D201 bool catch"
                )
            if not (0.0 <= float(value) <= 1.0):
                raise ValueError(
                    f"{name} {value!r} out of range [0.0, 1.0] per "
                    "ADR-0045 D229 + ADR-0038 D184(a)"
                )
        if isinstance(self.k, bool) or not isinstance(self.k, int):
            raise ValueError(
                f"k must be an int (bool catch per ADR-0041 D201); "
                f"got {self.k!r} (type {type(self.k).__name__})"
            )
        if self.k < 0:
            raise ValueError(
                f"k must be non-negative; got {self.k!r}"
            )
        if not isinstance(self.exemplar_ids, tuple):
            raise ValueError(
                "exemplar_ids must be a tuple of strs (tuple-typed for "
                "immutability per ADR-0045 D229 + the Week 6 "
                "DraftQualityResult pattern at ADR-0043 D213); got "
                f"{type(self.exemplar_ids).__name__}"
            )
        for idx, eid in enumerate(self.exemplar_ids):
            if not isinstance(eid, str):
                raise ValueError(
                    f"exemplar_ids[{idx}] must be a str instance; got "
                    f"{type(eid).__name__!r} per ADR-0045 D229. Per-item "
                    "type validation mirrors Week 6 follow-up P2-1 at "
                    "DraftQualityResult per ADR-0043 D213."
                )
        if len(self.exemplar_ids) > self.k:
            raise ValueError(
                f"len(exemplar_ids)={len(self.exemplar_ids)} exceeds "
                f"k={self.k}; per ADR-0045 D229 the subset invariant "
                "requires len(exemplar_ids) <= k. The framework's "
                "retrieval primitive may return fewer than K when "
                "filters narrow the corpus per ADR-0039 D188; "
                "operators stamping more than K signals a per-call "
                "config drift."
            )
        # Consistency check: meets_threshold MUST equal
        # (score >= threshold). Without this guard, downstream
        # consumers (Pillar G dashboard) couldn't trust the stamped
        # boolean independently of the score/threshold pair.
        if not isinstance(self.meets_threshold, bool):
            raise ValueError(
                "meets_threshold must be a bool; got "
                f"{type(self.meets_threshold).__name__}"
            )
        expected_meets = float(self.voice_fidelity_score) >= float(self.voice_fidelity_threshold)
        if self.meets_threshold != expected_meets:
            raise ValueError(
                f"meets_threshold={self.meets_threshold!r} inconsistent "
                f"with voice_fidelity_score={self.voice_fidelity_score!r} "
                f">= voice_fidelity_threshold={self.voice_fidelity_threshold!r} "
                f"(expected {expected_meets!r}); per ADR-0045 D229 the "
                "stamped boolean MUST match the score/threshold "
                "comparison. Caller bug — fix the construction site."
            )
        # THE Layer 2 invariant per ADR-0045 D229 + ADR-0038 D184(a).
        # state="ready" + meets_threshold=False is the structural
        # refuse-loud case (symmetric with Week 6's ready + uncited
        # non-empty refusal at DraftQualityResult per ADR-0043 D213).
        if self.state == "ready" and not self.meets_threshold:
            raise ValueError(
                f"Refusing to construct a state='ready' "
                f"DraftFidelityResult with meets_threshold=False "
                f"(score={self.voice_fidelity_score:.3f} < "
                f"threshold={self.voice_fidelity_threshold:.3f}); per "
                "ADR-0038 D184(a) + ADR-0045 D229 THE construction-time "
                "invariant catches the structurally invalid combination. "
                "Either set state='refused' (the operator-deliberate "
                "refuse-case) OR ensure the score meets the per-register "
                "threshold (the accept-case)."
            )


# ---------------------------------------------------------------------------
# compute_draft_fidelity_score — per-draft fidelity-scoring primitive
# ---------------------------------------------------------------------------


def compute_draft_fidelity_score(
    draft: str,
    *,
    register: str,
    channel: str,
    k: int = DEFAULT_TOP_K,
    is_substantive_reply: bool | None = None,
    now: datetime | None = None,
    thresholds_path: Path | None = None,
    cfg: dict | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    retrieve_fn: Callable[..., list[VoiceExemplar]] | None = None,
) -> DraftFidelityResult:
    """Per-draft voice-fidelity scoring primitive per ADR-0045 D230.

    Consumes the Week 2 retrieval primitive
    (:func:`voice_corpus.retrieve_voice_exemplars`) + the Week 4
    threshold loader
    (:func:`voice_corpus.get_voice_threshold_for_register` per
    ADR-0041 D204).

    Per-call dispatch:

    1. Validate ``register`` + ``channel`` BEFORE retrieval
       (closed-enum per ADR-0038 D178 + ADR-0014 D33; fail-fast).
    2. Resolve the per-register threshold via the Week 4 loader.
    3. Retrieve top-K voice-corpus exemplars (filtered per
       ``register`` + ``channel`` + ``is_substantive_reply``). The
       TEST-ONLY ``retrieve_fn`` injection seam (per ADR-0045
       D235) bypasses :func:`voice_corpus.retrieve_voice_exemplars`
       when supplied.
    4. Compute the per-draft fidelity score as the mean of the
       per-exemplar scores (cosine × recency per ADR-0038
       D184(a)). Clamp to ``[0.0, 1.0]``.
    5. Construct :class:`DraftFidelityResult` (Layer 2 invariant
       runs at construction site per ADR-0045 D229).

    Empty exemplar list (empty corpus OR no filter matches) yields
    ``voice_fidelity_score=0.0`` + ``state="refused"`` — the
    framework refuses-loud per ADR-0038 D184's asymmetric-failure-
    cost calculus (the brand-risk path is the high-cost side).
    Operators with empty corpora opt OUT of fidelity-scoring via
    the SKILL.md Phase 4 dispatch (`voice.use_embedding_primitive`
    flag).

    Args:
        draft: The draft text (Phase 3.5 prose assembly output).
            Passed as the query to the retrieval primitive.
        register: The draft's register (closed-enum per ADR-0038
            D178). Validated BEFORE retrieval.
        channel: The draft's channel (closed-enum per ADR-0014
            D33). Validated BEFORE retrieval.
        k: Number of top-K exemplars to consider. Defaults to
            :data:`voice_corpus.DEFAULT_TOP_K` (5).
        is_substantive_reply: Optional filter — biases toward
            proven-effective exemplars per ADR-0040 D196 for
            the cold-pitch register's calibration.
        now: Deterministic-clock anchor per ADR-0031 D140 +
            ADR-0034 D156 + ADR-0035 D162 precedent. Passed
            through to the retrieval primitive for per-test
            reproducibility.
        thresholds_path: Override the per-register threshold
            config path; passed through to
            :func:`voice_corpus.get_voice_threshold_for_register`.
        cfg: Pre-loaded config dict; passed through.
        embed_fn: **TEST-ONLY** per ADR-0045 D235. Passes through
            to the retrieval primitive's
            :func:`voice_corpus.retrieve_voice_exemplars`
            ``embed_fn`` kwarg per ADR-0043 D218. Reserved for
            the test suite + the Week 8+ encoding extension;
            operators do NOT inject custom encoders at production
            callsites. The CLI does NOT surface a corresponding
            ``--embed-fn`` flag (security + audit per ADR-0039
            D188-Alt3 + ADR-0040 D197-Alt1).
        retrieve_fn: **TEST-ONLY** per ADR-0045 D235. The Week 8
            NEW injection seam — full retrieval bypass for unit
            tests. When supplied, this callable replaces
            :func:`voice_corpus.retrieve_voice_exemplars` for the
            per-call retrieval; receives the same kwargs
            (``query``, ``k``, ``register``, ``channel``,
            ``is_substantive_reply``, ``now``, ``cfg``,
            ``embed_fn``). Reserved for the test suite; the CLI
            does NOT surface a corresponding ``--retrieve-fn``
            flag.

    Returns:
        :class:`DraftFidelityResult` carrying the per-draft
        score + threshold + meets_threshold stamp + exemplar IDs
        + state verdict.

    Raises:
        ValueError: if ``register`` not in
            :data:`voice_corpus.REGISTERS` OR ``channel`` not in
            :data:`voice_corpus.CHANNELS`. The Week 4 loader's
            errors (missing required register key; out-of-range
            value; malformed YAML) propagate unchanged. The
            Week 2 retrieval primitive's errors (corpus file
            not found; metadata mismatch; embedding cache
            invalid) propagate unchanged when ``retrieve_fn`` is
            not supplied.
    """
    # Validate closed-enums BEFORE retrieval (fail-fast surface for
    # operator misconfiguration; saves a SentenceTransformer load).
    if register not in REGISTERS:
        raise ValueError(
            f"register {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r}; per ADR-0038 D178 the enum is "
            "closed-set"
        )
    if channel not in CHANNELS:
        raise ValueError(
            f"channel {channel!r} not in CHANNELS "
            f"{sorted(CHANNELS)!r}; per ADR-0014 D33 the enum is "
            "closed-set"
        )

    # Resolve per-register threshold via Week 4 loader.
    threshold = get_voice_threshold_for_register(
        register,
        thresholds_path=thresholds_path,
        cfg=cfg,
    )

    # Retrieve top-K exemplars. The TEST-ONLY retrieve_fn seam per
    # ADR-0045 D235 bypasses the Week 2 retrieval primitive for unit
    # tests (full retrieval substitution); default behavior calls
    # retrieve_voice_exemplars per ADR-0039 D188.
    retriever = retrieve_fn if retrieve_fn is not None else retrieve_voice_exemplars
    exemplars = retriever(
        draft,
        k=k,
        register=register,
        channel=channel,
        is_substantive_reply=is_substantive_reply,
        now=now,
        cfg=cfg,
        embed_fn=embed_fn,
    )

    # Compute fidelity score as the mean of per-exemplar scores. Each
    # exemplar's score is cosine × recency from the retrieval
    # primitive per ADR-0038 D179 + ADR-0038 D184(a). Empty exemplar
    # list yields 0.0 (the framework refuses-loud per ADR-0038 D184's
    # asymmetric-failure-cost calculus — silently accepting drafts
    # against an empty corpus is the brand-risk path).
    if not exemplars:
        fidelity_score = 0.0
    else:
        # Defensive against None scores (legacy corpus samples or
        # retrieve_fn stubs without scores).
        scored_values = [
            float(ex.score) for ex in exemplars
            if ex.score is not None
        ]
        if not scored_values:
            fidelity_score = 0.0
        else:
            fidelity_score = sum(scored_values) / len(scored_values)
    # Clamp to [0.0, 1.0] per ADR-0038 D184(a) range. Out-of-range
    # values are theoretically possible with non-normalized embeddings
    # or low-recency samples (recency < 0 when sample.year > anchor.year);
    # the clamp satisfies the DraftFidelityResult construction-time
    # invariant.
    fidelity_score = max(0.0, min(1.0, fidelity_score))

    meets_threshold = fidelity_score >= threshold
    state = "ready" if meets_threshold else "refused"

    exemplar_ids = tuple(ex.id for ex in exemplars)

    return DraftFidelityResult(
        draft_hash=_hash_draft(draft),
        register=register,
        channel=channel,
        voice_fidelity_score=fidelity_score,
        voice_fidelity_threshold=threshold,
        meets_threshold=meets_threshold,
        exemplar_ids=exemplar_ids,
        k=k,
        state=state,
    )


# ---------------------------------------------------------------------------
# build_draft_quality_scored_payload — event-shape factory (emit-always)
# ---------------------------------------------------------------------------


def build_draft_quality_scored_payload(
    *,
    person_id: str | None,
    result: DraftFidelityResult,
    channel: str,
    register: str,
) -> dict:
    """Build the ``draft_quality_scored`` event payload per
    ADR-0045 D231 + ADR-0038 D182.

    The third Pillar F event class. **Emit-always** posture (vs
    Week 6's emit-only-on-uncited for ``hallucination_detected``
    per ADR-0043 D219) — Pillar G observability per ADR-0038
    §Downstream pillar impact needs accept-case events for
    per-register score distribution rendering. Both ``ready`` +
    ``refused`` states emit through this factory.

    Event shape:

    .. code-block:: text

        type:                       draft_quality_scored
        person_id                   (the prospect the draft targets;
                                     None for ad-hoc validation)
        draft_hash                  (sha256:<hex> of the draft body —
                                     NOT the raw draft per I8)
        register                    (closed-enum per ADR-0038 D178)
        channel                     (closed-enum per ADR-0014 D33)
        voice_fidelity_score        (float in [0.0, 1.0] per
                                     ADR-0038 D184(a))
        voice_fidelity_threshold    (per-register threshold consulted
                                     per ADR-0041 D204)
        meets_threshold             (bool; stamped per ADR-0045 D229)
        state                       ({"ready", "refused"})
        exemplar_ids                (list of str — per-exemplar bodies
                                     NOT included per I8)
        k                           (the requested top-K)
        _emitted_by                 ("draft_quality" per ADR-0010 D17 +
                                     ADR-0043 D216 — same primitive
                                     emits both hallucination_detected
                                     + draft_quality_scored)

    Privacy-respecting per I8 + ADR-0038 §Compliance with
    invariants:

    * **Raw draft body MUST NOT appear in the payload.** The
      draft is sha256-hashed at the result construction site.
    * **Per-exemplar bodies MUST NOT appear in the payload.**
      Only the exemplar IDs surface (operators look up bodies
      via the corpus directly per ADR-0039 D189 precedent).

    Args:
        person_id: The prospect the draft targets. ``None`` is
            accepted for ad-hoc operator validation outside the
            per-Person flow (mirrors ADR-0039 D189 + ADR-0043
            D216).
        result: The :class:`DraftFidelityResult`. Both ``ready``
            + ``refused`` states are accepted (emit-always per
            ADR-0045 D231).
        channel: The draft's channel (per channel-on-every-event
            invariant per ADR-0014 D33). MUST be in
            :data:`voice_corpus.CHANNELS`; raises
            :exc:`ValueError` on unknown. MUST match
            ``result.channel`` (mirrors Week 6 follow-up P2-2
            per ADR-0043 D216).
        register: The draft's register. MUST be in
            :data:`voice_corpus.REGISTERS`; raises
            :exc:`ValueError` on unknown. MUST match
            ``result.register``.

    Returns:
        The event payload dict (no ``ts`` — that's set by
        :meth:`Ledger.append`).

    Raises:
        ValueError: when ``channel`` is not in
            :data:`voice_corpus.CHANNELS`, ``register`` is not in
            :data:`voice_corpus.REGISTERS`, OR the kwarg values
            do not match the result's stamped values.
    """
    if channel not in CHANNELS:
        raise ValueError(
            f"channel {channel!r} not in CHANNELS "
            f"{sorted(CHANNELS)!r} per ADR-0014 D33 + ADR-0045 D231"
        )
    if register not in REGISTERS:
        raise ValueError(
            f"register {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r} per ADR-0038 D178 + ADR-0045 D231"
        )
    # Per Week 6 follow-up P2-2 precedent — the factory's channel +
    # register kwargs MUST match the result's stamped values. Without
    # this check, a caller passing mismatched values silently emits
    # an event claiming a different channel/register than the draft
    # was scored against — the Pillar G dashboard's per-register
    # aggregation would surface phantom signals.
    if channel != result.channel:
        raise ValueError(
            f"channel {channel!r} does not match result.channel "
            f"{result.channel!r}; per ADR-0045 D231 the factory MUST "
            "stamp the same channel the draft was scored against. The "
            "caller passed inconsistent values — fix the call site."
        )
    if register != result.register:
        raise ValueError(
            f"register {register!r} does not match result.register "
            f"{result.register!r}; per ADR-0045 D231 the factory MUST "
            "stamp the same register the draft was scored against."
        )
    return {
        "type": "draft_quality_scored",
        "person_id": person_id,
        "draft_hash": result.draft_hash,
        "register": register,
        "channel": channel,
        "voice_fidelity_score": result.voice_fidelity_score,
        "voice_fidelity_threshold": result.voice_fidelity_threshold,
        "meets_threshold": result.meets_threshold,
        "state": result.state,
        "exemplar_ids": list(result.exemplar_ids),
        "k": result.k,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# Pillar F Week 10 — Layer 4 post-engine guard + ``draft_ready`` event
# class per ADR-0047 (D244-D251)
# ---------------------------------------------------------------------------


class Layer4GuardRefusal(ValueError):
    """Raised when :func:`build_draft_ready_payload` refuses per ADR-0047
    D245 + ADR-0038 D180 Layer 4.

    The exception is the structured surface for the Layer 4 emit-guard's
    per-dimension refuse-loud verdict. Subclasses :exc:`ValueError` so
    existing exception-handling (CLI try/except blocks; downstream
    callers) continues to work without code changes — operators wanting
    to distinguish the Layer 4 refusal from generic invariant violations
    use :func:`isinstance` against this class.

    The two per-dimension refuse paths per ADR-0047 D245:

    * **Hallucination-detection dimension** —
      ``quality_result.state == "refused"`` (Week 6 substrate per
      ADR-0043 D213) AND ``hallucination_check_override`` is False.
    * **Voice-fidelity dimension** — ``fidelity_result.state == "refused"``
      (Week 8 substrate per ADR-0045 D229) AND
      ``voice_fidelity_check_override`` is False.

    When BOTH dimensions refused, the exception's ``refused_dimensions``
    field carries the full tuple ``("hallucination", "fidelity")``;
    operators see both refusals in one error per the SYMMETRIC
    two-dimensional verdict structural commitment.

    Attributes:
        refused_dimensions: Tuple naming the refused dimension(s); a
            subset of ``("hallucination", "fidelity")``. Always non-
            empty when the exception is raised.
        quality_result: The :class:`DraftQualityResult` instance passed
            to the factory. Operators inspect ``quality_result.uncited_claims``
            for the per-claim diagnostic per ADR-0043 D213.
        fidelity_result: The :class:`DraftFidelityResult` instance
            passed to the factory (may be ``None`` when the caller
            passed ``fidelity_result=None`` for the ``voice_fidelity_check
            == "skipped"`` path per ADR-0047 D246).
    """

    def __init__(
        self,
        message: str,
        *,
        refused_dimensions: tuple[str, ...],
        quality_result: "DraftQualityResult",
        fidelity_result: "DraftFidelityResult | None",
    ) -> None:
        super().__init__(message)
        self.refused_dimensions = refused_dimensions
        self.quality_result = quality_result
        self.fidelity_result = fidelity_result


# Per ADR-0047 D247 — the two per-dimension verdict-name values stamped
# on the ``draft_ready`` event payload's ``hallucination_check`` +
# ``voice_fidelity_check`` fields. Pillar I per-tenant audit-tooling
# distinguishes native-pass from override-pass via these markers.
_DRAFT_READY_PASS_NATIVE: str = "passed"
_DRAFT_READY_PASS_VIA_OVERRIDE: str = "passed_via_override"
_DRAFT_READY_SKIPPED: str = "skipped"


# Per ADR-0047 D247 — closed-set of per-dimension verdict-name values
# the ``draft_ready`` event class accepts. The construction-time
# refuse-loud per D245 enforces this implicitly via the dispatch.
_VALID_DRAFT_READY_HALLUCINATION_VERDICTS: frozenset[str] = frozenset({
    _DRAFT_READY_PASS_NATIVE,
    _DRAFT_READY_PASS_VIA_OVERRIDE,
})
_VALID_DRAFT_READY_FIDELITY_VERDICTS: frozenset[str] = frozenset({
    _DRAFT_READY_PASS_NATIVE,
    _DRAFT_READY_PASS_VIA_OVERRIDE,
    _DRAFT_READY_SKIPPED,
})


def build_draft_ready_payload(
    *,
    person_id: str | None,
    quality_result: DraftQualityResult,
    fidelity_result: DraftFidelityResult | None,
    channel: str,
    register: str,
    hallucination_check_override: bool = False,
    hallucination_check_override_reason: str | None = None,
    voice_fidelity_check_override: bool = False,
    voice_fidelity_check_override_reason: str | None = None,
) -> dict:
    """Build the ``draft_ready`` event payload per ADR-0047 D245 + D246.

    The FOURTH Pillar F event class per ADR-0038 D182. **Emit-only-on-
    both-pass** posture (vs Week 6's emit-only-on-uncited for
    ``hallucination_detected`` per ADR-0043 D219 + Week 8's emit-always
    for ``draft_quality_scored`` per ADR-0045 D231) — the event SIGNALS
    dispatch-eligibility per ADR-0038 D180 Layer 4; the refuse-case is
    the loud :exc:`Layer4GuardRefusal`.

    The factory consumes BOTH per-Layer 2 substrates:

    * :class:`DraftQualityResult` (Week 6 — hallucination-detection per
      ADR-0043 D213).
    * :class:`DraftFidelityResult` (Week 8 — voice-fidelity per ADR-0045
      D229). May be ``None`` to surface the ``voice_fidelity_check ==
      "skipped"`` path per ADR-0047 D246 (operators with
      ``voice.use_embedding_primitive: false`` legacy posture per
      ADR-0045 §Migration/rollout Path B).

    Per-call dispatch per ADR-0047 D245:

    1. Validate closed-enums (``channel`` in :data:`voice_corpus.CHANNELS`;
       ``register`` in :data:`voice_corpus.REGISTERS`).
    2. Validate kwarg mismatch with both results (``channel`` /
       ``register`` MUST match ``quality_result.channel`` /
       ``quality_result.register`` AND ``fidelity_result.channel`` /
       ``fidelity_result.register`` when ``fidelity_result is not None``).
    3. Validate the override bool kwargs (bool catch per ADR-0041 D201;
       reason MUST be a non-empty stripped string when the matching
       override is True).
    4. Validate cross-dimension consistency: ``quality_result.draft_hash``
       MUST equal ``fidelity_result.draft_hash`` when ``fidelity_result
       is not None`` (both results MUST refer to the same draft body —
       mismatch is a caller bug per ADR-0047 D245).
    5. Per-dimension refuse-loud per D245:

       * IF ``quality_result.state == "refused"`` AND NOT
         ``hallucination_check_override``: raise :exc:`Layer4GuardRefusal`
         with the per-claim trace.
       * IF ``fidelity_result is not None`` AND
         ``fidelity_result.state == "refused"`` AND NOT
         ``voice_fidelity_check_override``: raise :exc:`Layer4GuardRefusal`
         with the per-register score + threshold.
       * IF BOTH refused AND BOTH overrides absent: raise
         :exc:`Layer4GuardRefusal` naming BOTH dimensions.

    6. Construct the ``draft_ready`` payload + return.

    Event shape per ADR-0047 D246:

    .. code-block:: text

        type:                                  draft_ready
        person_id                              (the prospect; None for ad-hoc)
        draft_hash                             (sha256:<hex> per I8)
        register                               (closed-enum per ADR-0038 D178)
        channel                                (closed-enum per ADR-0014 D33)
        hallucination_check                    ("passed" | "passed_via_override")
        hallucination_check_override_reason    (str | None)
        voice_fidelity_check                   ("passed" | "passed_via_override"
                                                | "skipped")
        voice_fidelity_check_override_reason   (str | None)
        voice_fidelity_score                   (float | None — None when skipped)
        voice_fidelity_threshold               (float | None — None when skipped)
        parsed_claims_count                    (int)
        uncited_claims_count                   (int — > 0 only when override stamped)
        _emitted_by                            ("draft_quality" per ADR-0010 D17)

    Privacy-respecting per I8 + ADR-0038 §Compliance with invariants:

    * **Raw draft body MUST NOT appear in the payload.** The draft is
      sha256-hashed at the upstream result construction sites per
      ADR-0043 D213 + ADR-0045 D229.
    * **Per-claim trace MUST NOT appear in the payload.** Only counts
      (``parsed_claims_count`` + ``uncited_claims_count``) surface;
      operators inspect the per-claim trace via the upstream
      ``hallucination_detected`` event per ADR-0043 D219.
    * **Per-exemplar bodies MUST NOT appear in the payload.** Only
      ``voice_fidelity_score`` + ``voice_fidelity_threshold`` surface;
      operators inspect the per-exemplar IDs via the upstream
      ``draft_quality_scored`` event per ADR-0045 D231.
    * **Override reasons ARE in the payload** — operators stamping
      ``*_override_reason`` deliberately exposes the rationale for the
      Pillar I per-tenant audit-tooling. Reasons are caller-controlled
      prose (operator-readable; not auto-extracted from per-claim trace).

    Args:
        person_id: The prospect the draft targets. ``None`` is accepted
            for ad-hoc operator validation outside the per-Person flow
            (mirrors ADR-0039 D189 + ADR-0043 D216 + ADR-0045 D231).
        quality_result: The :class:`DraftQualityResult` from
            :func:`score_draft` per ADR-0043 D215. Required (the Layer 3
            parser + Layer 2 hallucination-detection gate ALWAYS runs
            per the Week 10 emit-guard's structural commitment).
        fidelity_result: The :class:`DraftFidelityResult` from
            :func:`compute_draft_fidelity_score` per ADR-0045 D230. Pass
            ``None`` to surface the ``voice_fidelity_check == "skipped"``
            path per ADR-0047 D246 (operators with
            ``voice.use_embedding_primitive: false`` legacy posture).
        channel: The draft's channel (per channel-on-every-event
            invariant per ADR-0014 D33). MUST be in
            :data:`voice_corpus.CHANNELS`. MUST match both results'
            stamped ``channel`` fields.
        register: The draft's register. MUST be in
            :data:`voice_corpus.REGISTERS`. MUST match both results'
            stamped ``register`` fields.
        hallucination_check_override: Operator-stamped override per
            ADR-0047 D247. When True, the factory bypasses the
            ``quality_result.state == "refused"`` refuse-loud + stamps
            ``hallucination_check == "passed_via_override"`` on the
            event payload. Operators MUST also supply
            ``hallucination_check_override_reason``.
        hallucination_check_override_reason: Operator's rationale for
            stamping the hallucination-check override. MUST be a non-
            empty stripped string when ``hallucination_check_override``
            is True (refuse-loud per D247).
        voice_fidelity_check_override: Operator-stamped override per
            ADR-0047 D247. When True, the factory bypasses the
            ``fidelity_result.state == "refused"`` refuse-loud + stamps
            ``voice_fidelity_check == "passed_via_override"``. Ignored
            when ``fidelity_result is None`` (the skipped path).
        voice_fidelity_check_override_reason: Operator's rationale for
            stamping the voice-fidelity-check override. MUST be a non-
            empty stripped string when ``voice_fidelity_check_override``
            is True AND ``fidelity_result is not None``.

    Returns:
        The event payload dict (no ``ts`` — that's set by
        :meth:`Ledger.append`).

    Raises:
        ValueError: when ``channel`` is not in
            :data:`voice_corpus.CHANNELS`, ``register`` is not in
            :data:`voice_corpus.REGISTERS`, the kwarg values do not
            match either result's stamped values, the cross-dimension
            ``draft_hash`` consistency check fails, an override kwarg
            is not a bool (per ADR-0041 D201 bool catch), or an
            override reason is missing when the matching override is
            True.
        Layer4GuardRefusal: when EITHER dimension's state is
            ``"refused"`` AND the per-dimension override is absent.
            Subclasses :exc:`ValueError`; carries ``refused_dimensions``
            + the per-Layer 2 result objects for operator-readable
            diagnostic surfacing.
    """
    # ---- (1) closed-enum validation per ADR-0047 D245 step 1 ----
    if channel not in CHANNELS:
        raise ValueError(
            f"channel {channel!r} not in CHANNELS "
            f"{sorted(CHANNELS)!r} per ADR-0014 D33 + ADR-0047 D245"
        )
    if register not in REGISTERS:
        raise ValueError(
            f"register {register!r} not in REGISTERS "
            f"{sorted(REGISTERS)!r} per ADR-0038 D178 + ADR-0047 D245"
        )

    # ---- (2) channel/register mismatch with both results per D245 step 2 ----
    # Mirrors Week 6 follow-up P2-2 per ADR-0043 D216 + Week 8 per
    # ADR-0045 D231 — silent kwarg/result mismatch would surface phantom
    # Pillar G dashboard signals.
    if channel != quality_result.channel:
        raise ValueError(
            f"channel {channel!r} does not match quality_result.channel "
            f"{quality_result.channel!r}; per ADR-0047 D245 the factory "
            "MUST stamp the same channel the per-Layer 2 hallucination "
            "result was constructed against. The caller passed "
            "inconsistent values — fix the call site."
        )
    if register != quality_result.register:
        raise ValueError(
            f"register {register!r} does not match quality_result.register "
            f"{quality_result.register!r}; per ADR-0047 D245 the factory "
            "MUST stamp the same register the per-Layer 2 hallucination "
            "result was constructed against."
        )
    if fidelity_result is not None:
        if channel != fidelity_result.channel:
            raise ValueError(
                f"channel {channel!r} does not match "
                f"fidelity_result.channel {fidelity_result.channel!r}; "
                "per ADR-0047 D245 the factory MUST stamp the same "
                "channel the per-Layer 2 fidelity result was constructed "
                "against. The caller passed inconsistent values — fix "
                "the call site."
            )
        if register != fidelity_result.register:
            raise ValueError(
                f"register {register!r} does not match "
                f"fidelity_result.register {fidelity_result.register!r}; "
                "per ADR-0047 D245 the factory MUST stamp the same "
                "register the per-Layer 2 fidelity result was constructed "
                "against."
            )

    # ---- (3) override bool catch + reason-required-when-override-true ----
    # Per ADR-0041 D201's bool-is-an-int discipline (bool IS a subclass
    # of int — ``isinstance(True, int) == True`` — so type() identity is
    # the only way to reject int while accepting bool) + ADR-0047 D247's
    # operator-stamping discipline (override rationale is the per-event
    # audit substrate for Pillar I per-tenant audit-tooling).
    if type(hallucination_check_override) is not bool:
        raise ValueError(
            f"hallucination_check_override must be bool, not "
            f"{type(hallucination_check_override).__name__} per ADR-0041 "
            "D201's bool-is-an-int discipline + ADR-0047 D247. Pass True "
            "or False explicitly; integer 0/1 will refuse-loud."
        )
    if type(voice_fidelity_check_override) is not bool:
        raise ValueError(
            f"voice_fidelity_check_override must be bool, not "
            f"{type(voice_fidelity_check_override).__name__} per ADR-0041 "
            "D201's bool-is-an-int discipline + ADR-0047 D247. Pass True "
            "or False explicitly; integer 0/1 will refuse-loud."
        )

    if hallucination_check_override:
        if (
            hallucination_check_override_reason is None
            or not isinstance(hallucination_check_override_reason, str)
            or not hallucination_check_override_reason.strip()
        ):
            raise ValueError(
                "hallucination_check_override=True requires a non-empty "
                "stripped string in hallucination_check_override_reason "
                "per ADR-0047 D247 + ADR-0043 D217's operator-stamping "
                "discipline. Operators stamping an override MUST surface "
                "the rationale for the Pillar I per-tenant audit-"
                "tooling."
            )
    if voice_fidelity_check_override and fidelity_result is not None:
        if (
            voice_fidelity_check_override_reason is None
            or not isinstance(voice_fidelity_check_override_reason, str)
            or not voice_fidelity_check_override_reason.strip()
        ):
            raise ValueError(
                "voice_fidelity_check_override=True requires a non-empty "
                "stripped string in voice_fidelity_check_override_reason "
                "per ADR-0047 D247 + ADR-0043 D217's operator-stamping "
                "discipline. Operators stamping an override MUST surface "
                "the rationale for the Pillar I per-tenant audit-"
                "tooling."
            )

    # ---- (4) cross-dimension draft_hash consistency per D245 step 4 ----
    # Both per-Layer 2 results MUST refer to the same draft body — the
    # asymmetric-failure-cost calculus per ADR-0038 D184 demands BOTH
    # gates fire on the SAME draft. Mismatch is a caller bug that would
    # silently emit a ``draft_ready`` claiming two-dimension verdict on
    # two different drafts.
    if fidelity_result is not None:
        if quality_result.draft_hash != fidelity_result.draft_hash:
            raise ValueError(
                f"quality_result.draft_hash "
                f"{quality_result.draft_hash!r} does not match "
                f"fidelity_result.draft_hash "
                f"{fidelity_result.draft_hash!r}; per ADR-0047 D245 the "
                "two per-Layer 2 results MUST refer to the same draft "
                "body. The caller passed two results from different "
                "drafts — fix the call site (BOTH score_draft AND "
                "compute_draft_fidelity_score must run on the same "
                "draft text)."
            )

    # ---- (5) per-dimension refuse-loud per D245 step 5 ----
    refused: list[str] = []
    if (
        quality_result.state == "refused"
        and not hallucination_check_override
    ):
        refused.append("hallucination")
    if (
        fidelity_result is not None
        and fidelity_result.state == "refused"
        and not voice_fidelity_check_override
    ):
        refused.append("fidelity")

    if refused:
        # Build the per-dimension diagnostic message — operators see
        # WHICH dimension(s) refused + the per-dimension data in one
        # error message (per the SYMMETRIC two-dimensional verdict
        # structural commitment per D245).
        parts: list[str] = []
        if "hallucination" in refused:
            parts.append(
                f"hallucination-detection refused: "
                f"{len(quality_result.uncited_claims)} uncited claim(s) "
                f"per ADR-0043 D213 (state={quality_result.state!r}). "
                "Operator remediation: stamp "
                "hallucination_check_override=True + "
                "hallucination_check_override_reason='...' to bypass, "
                "OR remediate the draft + re-run score_draft."
            )
        if "fidelity" in refused:
            # ``fidelity_result is not None`` is implied by the
            # append condition above; the type checker doesn't infer
            # this so the local rebinding makes it explicit.
            fr = fidelity_result
            assert fr is not None
            parts.append(
                f"voice-fidelity refused: score={fr.voice_fidelity_score:.3f} "
                f"< threshold={fr.voice_fidelity_threshold:.3f} per "
                f"ADR-0045 D229 (state={fr.state!r}). Operator "
                "remediation: stamp voice_fidelity_check_override=True + "
                "voice_fidelity_check_override_reason='...' to bypass, "
                "OR remediate the draft + re-run "
                "compute_draft_fidelity_score, OR tune the per-register "
                "threshold in ~/.outreach-factory/voice_thresholds.yml."
            )
        message = (
            "Layer 4 post-engine guard refused per ADR-0038 D180 + "
            "ADR-0047 D245. Refused dimension(s): "
            f"{', '.join(refused)}. {' | '.join(parts)}"
        )
        raise Layer4GuardRefusal(
            message,
            refused_dimensions=tuple(refused),
            quality_result=quality_result,
            fidelity_result=fidelity_result,
        )

    # ---- (6) construct the draft_ready payload per D246 ----
    # Per-dimension verdict-name dispatch — the override-pass marker
    # distinguishes native-pass from override-pass for Pillar I per-
    # tenant audit-tooling per ADR-0047 D247.
    hallucination_verdict = (
        _DRAFT_READY_PASS_VIA_OVERRIDE
        if hallucination_check_override
        else _DRAFT_READY_PASS_NATIVE
    )
    if fidelity_result is None:
        fidelity_verdict = _DRAFT_READY_SKIPPED
        fidelity_score: float | None = None
        fidelity_threshold: float | None = None
    elif voice_fidelity_check_override:
        fidelity_verdict = _DRAFT_READY_PASS_VIA_OVERRIDE
        fidelity_score = fidelity_result.voice_fidelity_score
        fidelity_threshold = fidelity_result.voice_fidelity_threshold
    else:
        fidelity_verdict = _DRAFT_READY_PASS_NATIVE
        fidelity_score = fidelity_result.voice_fidelity_score
        fidelity_threshold = fidelity_result.voice_fidelity_threshold

    return {
        "type": "draft_ready",
        "person_id": person_id,
        "draft_hash": quality_result.draft_hash,
        "register": register,
        "channel": channel,
        "hallucination_check": hallucination_verdict,
        "hallucination_check_override_reason": (
            hallucination_check_override_reason
            if hallucination_check_override
            else None
        ),
        "voice_fidelity_check": fidelity_verdict,
        "voice_fidelity_check_override_reason": (
            voice_fidelity_check_override_reason
            if voice_fidelity_check_override and fidelity_result is not None
            else None
        ),
        "voice_fidelity_score": fidelity_score,
        "voice_fidelity_threshold": fidelity_threshold,
        "parsed_claims_count": len(quality_result.parsed_claims),
        "uncited_claims_count": len(quality_result.uncited_claims),
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    """Load the operator's config; returns ``{}`` if not present.

    Test isolation: tests set ``OUTREACH_FACTORY_CONFIG`` env to a
    nonexistent path so this returns ``{}`` instead of pulling the
    operator's real ``~/.outreach-factory/config.yml``.
    """
    env_path = os.environ.get("OUTREACH_FACTORY_CONFIG")
    if env_path:
        p = Path(env_path).expanduser()
    else:
        p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        return {}
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _ledger_dir() -> Path:
    """Resolve the ledger directory (env override > default)."""
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    import ledger as _ledger
    return _ledger.DEFAULT_LEDGER_DIR


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_parse(args) -> int:
    """``parse`` — Layer 2 + Layer 3 entry point per ADR-0043 D212."""
    draft_path = Path(args.draft_path).expanduser()
    dossier_path = Path(args.research_dossier_path).expanduser()
    if not draft_path.exists():
        print(f"ERROR: draft file not found: {draft_path}", file=sys.stderr)
        return 2
    if not dossier_path.exists():
        print(
            f"ERROR: research dossier not found: {dossier_path}",
            file=sys.stderr,
        )
        return 2

    draft = draft_path.read_text()
    dossier = dossier_path.read_text()
    cfg = _load_config()
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )

    try:
        result = score_draft(
            draft, dossier,
            register=args.register,
            channel=args.channel,
            thresholds_path=thresholds_path,
            cfg=cfg,
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Per ADR-0043 D219 — emit-only-on-uncited. The accept-case never
    # emits regardless of --apply; the refuse-case emits only when
    # --apply is set.
    payload: dict | None = None
    if result.state == "refused":
        payload = build_hallucination_detected_payload(
            person_id=args.person_id,
            result=result,
            channel=args.channel,
            register=args.register,
        )

    if args.json:
        out = {
            "state": result.state,
            "register": result.register,
            "channel": result.channel,
            "draft_hash": result.draft_hash,
            "threshold": result.threshold,
            "parsed_claims": [
                {
                    "claim_type": c.claim_type,
                    "claim_text": c.claim_text,
                    "citation_anchor": c.citation_anchor,
                }
                for c in result.parsed_claims
            ],
            "uncited_claims": [
                {
                    "claim_type": c.claim_type,
                    "claim_text": c.claim_text,
                    "citation_anchor": c.citation_anchor,
                }
                for c in result.uncited_claims
            ],
        }
        if payload is not None:
            out["payload"] = payload
        print(json.dumps(out, indent=2))
    else:
        print(f"state:      {result.state}")
        print(f"register:   {result.register}")
        print(f"channel:    {result.channel}")
        print(f"threshold:  {result.threshold:.2f}")
        print(f"parsed:     {len(result.parsed_claims)} claims")
        print(f"uncited:    {len(result.uncited_claims)} claims")
        if result.uncited_claims:
            print()
            print("Uncited claim trace (the gate caught these):")
            for c in result.uncited_claims:
                print(f"  [{c.claim_type}] {c.claim_text!r}")
            print()
            print("Operator remediation per ADR-0043 D217:")
            print("  - Add a dossier citation for each uncited claim, OR")
            print(
                "  - Stamp ``hallucination_check_override: true`` on the "
                "Touch note + a rationale."
            )

    if args.apply and payload is not None:
        import ledger as _ledger
        led = _ledger.Ledger(_ledger_dir())
        try:
            led.append(payload)
        except (OSError, ValueError) as exc:
            print(
                f"WARNING: ledger append failed for "
                f"hallucination_detected: {exc}",
                file=sys.stderr,
            )
    return 0


def _cmd_measure(args) -> int:
    """``measure`` — Per-claim-type corpus measurement per ADR-0044 D224."""
    corpus_dir = Path(args.corpus_dir).expanduser()
    if not corpus_dir.exists() or not corpus_dir.is_dir():
        print(
            f"ERROR: corpus directory not found: {corpus_dir}",
            file=sys.stderr,
        )
        return 2

    cfg = _load_config()
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )

    try:
        measurement = measure_per_claim_type_false_positive_rate(
            corpus_dir,
            args.claim_type,
            thresholds_path=thresholds_path,
            cfg=cfg,
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "claim_type": measurement.claim_type,
            "register": measurement.register,
            "channel": measurement.channel,
            "pair_count": measurement.pair_count,
            "true_positive": measurement.true_positive,
            "true_negative": measurement.true_negative,
            "false_positive": measurement.false_positive,
            "false_negative": measurement.false_negative,
            "accuracy": measurement.accuracy,
            "false_positive_rate": measurement.false_positive_rate,
            "false_negative_rate": measurement.false_negative_rate,
        }, indent=2))
    else:
        print(f"claim_type:           {measurement.claim_type}")
        print(f"register:             {measurement.register}")
        print(f"channel:              {measurement.channel}")
        print(f"pair_count:           {measurement.pair_count}")
        print(f"true_positive:        {measurement.true_positive}")
        print(f"true_negative:        {measurement.true_negative}")
        print(f"false_positive:       {measurement.false_positive}")
        print(f"false_negative:       {measurement.false_negative}")
        print(f"accuracy:             {measurement.accuracy:.3f}")
        print(f"false_positive_rate:  {measurement.false_positive_rate:.3f}")
        print(f"false_negative_rate:  {measurement.false_negative_rate:.3f}")
    return 0


def _cmd_score(args) -> int:
    """``score`` — Per-draft voice-fidelity scoring per ADR-0045 D234.

    The subcommand surfaces the Week 8 fidelity-scoring primitive to
    operators. Mirrors the ``parse`` subcommand's shape (per ADR-0043
    D212) — read the draft from disk, invoke the primitive, optionally
    emit the ``draft_quality_scored`` event to the ledger via
    ``--apply`` (emit-always per ADR-0045 D231).
    """
    draft_path = Path(args.draft_path).expanduser()
    if not draft_path.exists():
        print(f"ERROR: draft file not found: {draft_path}", file=sys.stderr)
        return 2

    draft = draft_path.read_text()
    cfg = _load_config()
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )

    try:
        result = compute_draft_fidelity_score(
            draft,
            register=args.register,
            channel=args.channel,
            k=args.k,
            thresholds_path=thresholds_path,
            cfg=cfg,
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Per ADR-0045 D231 — emit-always (both ready + refused). The
    # factory constructs the payload for either state; only --apply
    # gates the ledger append.
    payload = build_draft_quality_scored_payload(
        person_id=args.person_id,
        result=result,
        channel=args.channel,
        register=args.register,
    )

    if args.json:
        out = {
            "state": result.state,
            "register": result.register,
            "channel": result.channel,
            "draft_hash": result.draft_hash,
            "voice_fidelity_score": result.voice_fidelity_score,
            "voice_fidelity_threshold": result.voice_fidelity_threshold,
            "meets_threshold": result.meets_threshold,
            "exemplar_ids": list(result.exemplar_ids),
            "k": result.k,
            "payload": payload,
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"state:                    {result.state}")
        print(f"register:                 {result.register}")
        print(f"channel:                  {result.channel}")
        print(f"voice_fidelity_score:     {result.voice_fidelity_score:.3f}")
        print(f"voice_fidelity_threshold: {result.voice_fidelity_threshold:.3f}")
        print(f"meets_threshold:          {result.meets_threshold}")
        print(f"k:                        {result.k}")
        print(f"exemplars:                {len(result.exemplar_ids)} ids")
        if result.exemplar_ids:
            print()
            print("Top-K exemplar IDs (consult corpus directly for bodies):")
            for eid in result.exemplar_ids:
                print(f"  - {eid}")
        if result.state == "refused":
            print()
            print("Operator remediation per ADR-0045 D231:")
            print(
                "  - The draft's voice-fidelity score is below the per-"
                "register threshold."
            )
            print(
                "  - Either revise the draft (re-run /draft-outreach Phase 4 "
                "to re-anchor the voice) OR lower the threshold in "
                "~/.outreach-factory/voice_thresholds.yml (operator-"
                "deliberate calibration)."
            )

    if args.apply:
        import ledger as _ledger
        led = _ledger.Ledger(_ledger_dir())
        try:
            led.append(payload)
        except (OSError, ValueError) as exc:
            print(
                f"WARNING: ledger append failed for "
                f"draft_quality_scored: {exc}",
                file=sys.stderr,
            )
    return 0


def _cmd_emit_ready(args) -> int:
    """``emit-ready`` — Layer 4 post-engine guard per ADR-0047 D248.

    Composite per-draft entry point. Runs BOTH per-Layer 2 gates (Layer
    3 parser + Layer 2 hallucination-detection via :func:`score_draft`;
    Layer 2 voice-fidelity scorer via :func:`compute_draft_fidelity_score`)
    + invokes the Layer 4 emit-guard via :func:`build_draft_ready_payload`
    + emits the per-Layer events per the existing cardinality (ADR-0043
    D219 + ADR-0045 D231) AND the NEW ``draft_ready`` event per
    ADR-0047 D246.

    Per-call emit cardinality (per ADR-0047 D248):

    * ``hallucination_detected`` (Week 6): appended ONLY when
      ``uncited_claims`` is non-empty AND ``--apply`` per ADR-0043 D219
      (the per-Layer event's existing emit-only-on-uncited posture is
      preserved).
    * ``draft_quality_scored`` (Week 8): appended for BOTH ``ready`` +
      ``refused`` states when ``--apply`` per ADR-0045 D231 (emit-
      always). SKIPPED when ``--skip-fidelity-check`` is set.
    * ``draft_ready`` (Week 10): appended ONLY when BOTH per-Layer 2
      verdicts pass (natively OR via the per-dimension override) AND
      ``--apply`` per ADR-0047 D246 (emit-only-on-both-pass posture).

    Exit code is always 0 on successful CLI execution — the Layer 4
    refusal is a framework structural commitment NOT a CLI error. Exit
    code 2 is reserved for unrecoverable CLI errors (missing files,
    invalid args, etc.).
    """
    draft_path = Path(args.draft_path).expanduser()
    dossier_path = Path(args.research_dossier_path).expanduser()
    if not draft_path.exists():
        print(f"ERROR: draft file not found: {draft_path}", file=sys.stderr)
        return 2
    if not dossier_path.exists():
        print(
            f"ERROR: research dossier not found: {dossier_path}",
            file=sys.stderr,
        )
        return 2

    draft = draft_path.read_text()
    dossier = dossier_path.read_text()
    cfg = _load_config()
    thresholds_path = (
        Path(args.thresholds_path).expanduser()
        if args.thresholds_path else None
    )

    # ---- Step 1: Layer 3 parser + Layer 2 hallucination-detection
    # gate per ADR-0043 D215 (score_draft is the composite Layer 2 +
    # Layer 3 entry point — runs the parser, cross-references claims
    # against the dossier, constructs the DraftQualityResult with the
    # Layer 2 invariant). ----
    try:
        quality_result = score_draft(
            draft, dossier,
            register=args.register,
            channel=args.channel,
            thresholds_path=thresholds_path,
            cfg=cfg,
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # ---- Step 2: Layer 2 voice-fidelity gate per ADR-0045 D230
    # (compute_draft_fidelity_score consumes the Week 2 retrieval
    # primitive + Week 4 threshold loader; skipped when
    # --skip-fidelity-check). ----
    fidelity_result: DraftFidelityResult | None
    if args.skip_fidelity_check:
        fidelity_result = None
    else:
        try:
            fidelity_result = compute_draft_fidelity_score(
                draft,
                register=args.register,
                channel=args.channel,
                k=args.k,
                thresholds_path=thresholds_path,
                cfg=cfg,
            )
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    # ---- Step 3: Emit per-Layer events at their existing cardinality
    # (per ADR-0047 D248 — the per-Layer events emit at their existing
    # cardinality regardless of the Layer 4 verdict). ----
    hallucination_payload: dict | None = None
    if quality_result.state == "refused":
        hallucination_payload = build_hallucination_detected_payload(
            person_id=args.person_id,
            result=quality_result,
            channel=args.channel,
            register=args.register,
        )
    fidelity_payload: dict | None = None
    if fidelity_result is not None:
        fidelity_payload = build_draft_quality_scored_payload(
            person_id=args.person_id,
            result=fidelity_result,
            channel=args.channel,
            register=args.register,
        )

    # ---- Step 4: Invoke the Layer 4 emit-guard per ADR-0047 D245. ----
    # The factory raises Layer4GuardRefusal on per-dimension refusal;
    # the CLI surfaces the per-dimension trace in the JSON output's
    # ``refused_dimensions`` field + does NOT emit ``draft_ready``.
    draft_ready_payload: dict | None = None
    refusal: Layer4GuardRefusal | None = None
    try:
        draft_ready_payload = build_draft_ready_payload(
            person_id=args.person_id,
            quality_result=quality_result,
            fidelity_result=fidelity_result,
            channel=args.channel,
            register=args.register,
            hallucination_check_override=args.hallucination_check_override,
            hallucination_check_override_reason=(
                args.hallucination_check_override_reason
            ),
            voice_fidelity_check_override=args.voice_fidelity_check_override,
            voice_fidelity_check_override_reason=(
                args.voice_fidelity_check_override_reason
            ),
        )
    except Layer4GuardRefusal as exc:
        refusal = exc
    except ValueError as exc:
        # ValueError (not Layer4GuardRefusal) means caller bug — e.g.,
        # channel/register/draft_hash mismatch, missing override reason,
        # bool catch. Surface to stderr + return 2 (CLI error).
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # ---- Step 5: Report verdicts (JSON or human-readable). ----
    # Per Week 10 follow-up P2-2 — when ANY per-dimension override fired
    # AND Layer 4 passed, the layer_4_check field surfaces
    # ``passed_via_override`` so operators can stamp the matching value
    # on the Touch note frontmatter per SKILL.md D249 without inspecting
    # the nested draft_ready_payload's per-dimension verdict markers.
    # The voice_fidelity_check_override is moot when --skip-fidelity-check
    # is set (the factory ignores it per the skipped path); only count
    # the override toward the top-level marker when fidelity actually ran.
    any_override_fired = bool(args.hallucination_check_override) or (
        bool(args.voice_fidelity_check_override)
        and not args.skip_fidelity_check
    )
    if refusal is not None:
        layer_4_check_value = "refused"
    elif any_override_fired:
        layer_4_check_value = "passed_via_override"
    else:
        layer_4_check_value = "passed"
    if args.json:
        out: dict = {
            "layer_4_check": layer_4_check_value,
            "register": quality_result.register,
            "channel": quality_result.channel,
            "draft_hash": quality_result.draft_hash,
            "hallucination_state": quality_result.state,
            "parsed_claims_count": len(quality_result.parsed_claims),
            "uncited_claims_count": len(quality_result.uncited_claims),
        }
        if fidelity_result is not None:
            out["fidelity_state"] = fidelity_result.state
            out["voice_fidelity_score"] = (
                fidelity_result.voice_fidelity_score
            )
            out["voice_fidelity_threshold"] = (
                fidelity_result.voice_fidelity_threshold
            )
        else:
            out["fidelity_state"] = "skipped"
            out["voice_fidelity_score"] = None
            out["voice_fidelity_threshold"] = None
        if hallucination_payload is not None:
            out["hallucination_detected_payload"] = hallucination_payload
        if fidelity_payload is not None:
            out["draft_quality_scored_payload"] = fidelity_payload
        if refusal is not None:
            out["refused_dimensions"] = list(refusal.refused_dimensions)
            out["refusal_message"] = str(refusal)
            # Surface per-dimension diagnostic data (operators consume
            # this for remediation OR override-stamping decisions).
            if "hallucination" in refusal.refused_dimensions:
                out["uncited_claims"] = [
                    {
                        "claim_type": c.claim_type,
                        "claim_text": c.claim_text,
                        "citation_anchor": c.citation_anchor,
                    }
                    for c in quality_result.uncited_claims
                ]
        if draft_ready_payload is not None:
            out["draft_ready_payload"] = draft_ready_payload
        print(json.dumps(out, indent=2))
    else:
        if refusal is not None:
            print(f"layer_4_check:    refused")
            print(
                f"refused_dimensions: "
                f"{', '.join(refusal.refused_dimensions)}"
            )
        else:
            # Per Week 10 follow-up P2-2 — surface the same value the
            # JSON output emits so operators get a consistent signal.
            print(f"layer_4_check:    {layer_4_check_value}")
        print(f"register:         {quality_result.register}")
        print(f"channel:          {quality_result.channel}")
        print(f"hallucination:    {quality_result.state} "
              f"({len(quality_result.uncited_claims)} uncited claims)")
        if fidelity_result is not None:
            print(
                f"fidelity:         {fidelity_result.state} "
                f"(score={fidelity_result.voice_fidelity_score:.3f}, "
                f"threshold={fidelity_result.voice_fidelity_threshold:.3f})"
            )
        else:
            print("fidelity:         skipped (--skip-fidelity-check)")
        if refusal is not None:
            print()
            print("Layer 4 refusal trace:")
            print(f"  {refusal}")
            print()
            print("Operator remediation per ADR-0047 D247:")
            if "hallucination" in refusal.refused_dimensions:
                print(
                    "  - Remediate uncited claims (add dossier "
                    "citations) + re-run, OR"
                )
                print(
                    "  - Stamp --hallucination-check-override + "
                    "--hallucination-check-override-reason '<rationale>'"
                )
            if "fidelity" in refusal.refused_dimensions:
                print(
                    "  - Remediate the draft (re-run /draft-outreach "
                    "Phase 4) + re-run, OR"
                )
                print(
                    "  - Stamp --voice-fidelity-check-override + "
                    "--voice-fidelity-check-override-reason '<rationale>'"
                )
                print(
                    "  - OR tune ~/.outreach-factory/voice_thresholds.yml "
                    "for the per-register threshold."
                )

    # ---- Step 6: Apply (ledger append) per --apply flag. ----
    # Per ADR-0047 D248 — the per-Layer events emit at their existing
    # cardinality regardless of the Layer 4 verdict; the draft_ready
    # event emits ONLY when both gates pass.
    if args.apply:
        import ledger as _ledger
        led = _ledger.Ledger(_ledger_dir())
        # Per-Layer event 1: hallucination_detected (emit-only-on-uncited
        # per ADR-0043 D219).
        if hallucination_payload is not None:
            try:
                led.append(hallucination_payload)
            except (OSError, ValueError) as exc:
                print(
                    f"WARNING: ledger append failed for "
                    f"hallucination_detected: {exc}",
                    file=sys.stderr,
                )
        # Per-Layer event 2: draft_quality_scored (emit-always per
        # ADR-0045 D231; skipped when --skip-fidelity-check).
        if fidelity_payload is not None:
            try:
                led.append(fidelity_payload)
            except (OSError, ValueError) as exc:
                print(
                    f"WARNING: ledger append failed for "
                    f"draft_quality_scored: {exc}",
                    file=sys.stderr,
                )
        # Layer 4 event: draft_ready (emit-only-on-both-pass per
        # ADR-0047 D246).
        if draft_ready_payload is not None:
            try:
                led.append(draft_ready_payload)
            except (OSError, ValueError) as exc:
                print(
                    f"WARNING: ledger append failed for "
                    f"draft_ready: {exc}",
                    file=sys.stderr,
                )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Pillar F Week 6 + Week 7 + Week 8 + Week 9 + Week 10 "
            "hallucination-detection primitive + per-claim-type corpus "
            "measurement + per-draft voice-fidelity scoring + per-claim "
            "fuzzy-match citation extension + Layer 4 post-engine guard "
            "(ADR-0038 D180 + D184(a) + ADR-0043 D212-D219 + ADR-0044 "
            "D220-D227 + ADR-0045 D228-D235 + ADR-0046 D236-D243 + "
            "ADR-0047 D244-D251). Week 6 ships Layer 2 + Layer 3 "
            "defense. Week 7 adds the `measure` subcommand. Week 8 adds "
            "the `score` subcommand. Week 9 extends the parser with "
            "per-claim fuzzy-match cross-reference. Week 10 adds the "
            "`emit-ready` subcommand — the Layer 4 post-engine guard's "
            "composite per-draft entry point that runs BOTH per-Layer 2 "
            "gates + the Layer 4 emit-guard + emits the `draft_ready` "
            "event when both per-Layer 2 verdicts pass (natively OR via "
            "the per-dimension operator override)."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser(
        "parse",
        help=(
            "Parse a draft + cross-reference claims against a research "
            "dossier; emit per-claim trace + gate verdict. Refuses-loud "
            "on uncited claims per ADR-0038 D180 Layer 2 + Layer 3."
        ),
    )
    ps.add_argument(
        "--draft-path", required=True,
        help="Path to the draft text file (e.g., /tmp/draft.txt).",
    )
    ps.add_argument(
        "--research-dossier-path", required=True,
        help=(
            "Path to the research dossier (e.g., the Phase 1 "
            "/research-prospect output Markdown file). The parser "
            "cross-references claims against this dossier's citation "
            "anchors."
        ),
    )
    ps.add_argument(
        "--register", required=True,
        choices=sorted(REGISTERS),
        help=(
            f"The draft's register (one of {sorted(REGISTERS)} per "
            "ADR-0038 D178). The per-register threshold is consulted "
            "via the Pillar F Week 4 loader per ADR-0041 D204."
        ),
    )
    ps.add_argument(
        "--channel", required=True,
        choices=sorted(CHANNELS),
        help=(
            f"The draft's channel (one of {sorted(CHANNELS)} per "
            "ADR-0014 D33). The channel-on-every-event invariant "
            "requires per-event channel stamping per ADR-0043 D216."
        ),
    )
    ps.add_argument(
        "--thresholds-path", default=None,
        help=(
            "Override the per-register threshold YAML path; passed "
            "through to voice_corpus.get_voice_threshold_for_register "
            "per ADR-0041 D204."
        ),
    )
    ps.add_argument(
        "--person-id", default=None,
        help=(
            "Optional: stamp on the emitted hallucination_detected "
            "event per ADR-0043 D216 (person_id field)."
        ),
    )
    ps.add_argument(
        "--apply", action="store_true",
        help=(
            "Append hallucination_detected event to the ledger (only "
            "when uncited_claims is non-empty per ADR-0043 D219 "
            "emit-only-on-uncited posture). Default is dry-run "
            "(report only)."
        ),
    )
    ps.add_argument("--json", action="store_true")

    # Pillar F Week 7 — measure subcommand per ADR-0044 D224.
    ms = sub.add_parser(
        "measure",
        help=(
            "Measure the per-claim-type false-positive rate of the "
            "Layer 3 parser against a per-claim-type corpus. Per "
            "ADR-0044 D223 + D224: walks `corpus_dir/<claim_type>.yml`, "
            "runs score_draft per pair, aggregates outcomes against "
            "expected_state ground truth + reports TP/TN/FP/FN tallies "
            "+ accuracy + FP_rate + FN_rate."
        ),
    )
    ms.add_argument(
        "--corpus-dir", required=True,
        help=(
            "Path to the per-claim-type corpus directory (e.g., "
            "tests/fixtures/draft_quality_corpus/). Per ADR-0044 D221 "
            "the directory ships one YAML file per claim type."
        ),
    )
    ms.add_argument(
        "--claim-type", required=True,
        choices=sorted(CLAIM_TYPES),
        help=(
            f"The claim type to measure (one of {sorted(CLAIM_TYPES)} "
            "per ADR-0038 D180 + ADR-0043 D214). The closed-enum is "
            "enforced at argparse choices BEFORE handler dispatch."
        ),
    )
    ms.add_argument(
        "--thresholds-path", default=None,
        help=(
            "Override the per-register threshold YAML path; passed "
            "through to score_draft per ADR-0041 D204."
        ),
    )
    ms.add_argument("--json", action="store_true")

    # Pillar F Week 8 — score subcommand per ADR-0045 D234.
    ss = sub.add_parser(
        "score",
        help=(
            "Per-draft voice-fidelity scoring against the per-register "
            "threshold. Per ADR-0045 D230 + D231: consumes the Week 2 "
            "retrieval primitive + the Week 4 threshold loader; computes "
            "the per-draft fidelity score = mean of top-K corpus "
            "exemplars' (cosine × recency) scores; emits "
            "draft_quality_scored event when --apply is set (emit-always "
            "per ADR-0045 D231)."
        ),
    )
    ss.add_argument(
        "--draft-path", required=True,
        help="Path to the draft text file (e.g., /tmp/draft.txt).",
    )
    ss.add_argument(
        "--register", required=True,
        choices=sorted(REGISTERS),
        help=(
            f"The draft's register (one of {sorted(REGISTERS)} per "
            "ADR-0038 D178). The per-register threshold is consulted "
            "via the Pillar F Week 4 loader per ADR-0041 D204."
        ),
    )
    ss.add_argument(
        "--channel", required=True,
        choices=sorted(CHANNELS),
        help=(
            f"The draft's channel (one of {sorted(CHANNELS)} per "
            "ADR-0014 D33). The channel-on-every-event invariant "
            "requires per-event channel stamping per ADR-0045 D231."
        ),
    )
    ss.add_argument(
        "--k", type=int, default=DEFAULT_TOP_K,
        help=(
            f"Top-K voice-corpus exemplars to score against (default "
            f"{DEFAULT_TOP_K} per voice_corpus.DEFAULT_TOP_K)."
        ),
    )
    ss.add_argument(
        "--thresholds-path", default=None,
        help=(
            "Override the per-register threshold YAML path; passed "
            "through to voice_corpus.get_voice_threshold_for_register "
            "per ADR-0041 D204."
        ),
    )
    ss.add_argument(
        "--person-id", default=None,
        help=(
            "Optional: stamp on the emitted draft_quality_scored event "
            "per ADR-0045 D231 (person_id field)."
        ),
    )
    ss.add_argument(
        "--apply", action="store_true",
        help=(
            "Append draft_quality_scored event to the ledger (emit-"
            "always per ADR-0045 D231 — both ready + refused states "
            "emit; Pillar G observability needs accept-case events for "
            "per-register score distribution rendering). Default is "
            "dry-run (report only)."
        ),
    )
    ss.add_argument("--json", action="store_true")

    # Pillar F Week 10 — emit-ready subcommand per ADR-0047 D248.
    es = sub.add_parser(
        "emit-ready",
        help=(
            "Layer 4 post-engine guard — composite per-draft entry "
            "point. Per ADR-0047 D245 + D246 + D248: runs BOTH per-"
            "Layer 2 gates (Layer 3 parser via score_draft; Layer 2 "
            "voice-fidelity scorer via compute_draft_fidelity_score) "
            "+ invokes the Layer 4 emit-guard "
            "(build_draft_ready_payload) + emits the per-Layer events "
            "at their existing cardinality + emits the NEW draft_ready "
            "event ONLY when both per-Layer 2 verdicts pass (natively "
            "OR via the per-dimension override) AND --apply is set "
            "(emit-only-on-both-pass posture per ADR-0047 D246)."
        ),
    )
    es.add_argument(
        "--draft-path", required=True,
        help="Path to the draft text file (e.g., /tmp/draft.txt).",
    )
    es.add_argument(
        "--research-dossier-path", required=True,
        help=(
            "Path to the research dossier (e.g., the Phase 1 "
            "/research-prospect output Markdown file). The Layer 3 "
            "parser cross-references claims against this dossier's "
            "citation anchors per ADR-0043 D214."
        ),
    )
    es.add_argument(
        "--register", required=True,
        choices=sorted(REGISTERS),
        help=(
            f"The draft's register (one of {sorted(REGISTERS)} per "
            "ADR-0038 D178). The per-register threshold is consulted "
            "via the Pillar F Week 4 loader per ADR-0041 D204."
        ),
    )
    es.add_argument(
        "--channel", required=True,
        choices=sorted(CHANNELS),
        help=(
            f"The draft's channel (one of {sorted(CHANNELS)} per "
            "ADR-0014 D33). The channel-on-every-event invariant "
            "requires per-event channel stamping per ADR-0047 D246."
        ),
    )
    es.add_argument(
        "--k", type=int, default=DEFAULT_TOP_K,
        help=(
            f"Top-K voice-corpus exemplars to score against (default "
            f"{DEFAULT_TOP_K} per voice_corpus.DEFAULT_TOP_K). Ignored "
            "when --skip-fidelity-check is set."
        ),
    )
    es.add_argument(
        "--thresholds-path", default=None,
        help=(
            "Override the per-register threshold YAML path; passed "
            "through to BOTH score_draft (Layer 3 parser threshold "
            "stamping) AND compute_draft_fidelity_score (Layer 2 "
            "fidelity threshold consumption) per ADR-0041 D204."
        ),
    )
    es.add_argument(
        "--person-id", default=None,
        help=(
            "Optional: stamp on ALL emitted events (hallucination_"
            "detected per ADR-0043 D216 + draft_quality_scored per "
            "ADR-0045 D231 + draft_ready per ADR-0047 D246) (person_id "
            "field)."
        ),
    )
    es.add_argument(
        "--hallucination-check-override", action="store_true",
        help=(
            "Per ADR-0047 D247 — bypass the hallucination-detection "
            "dimension's refuse-loud. The emitted draft_ready event's "
            "hallucination_check field stamps 'passed_via_override'; "
            "requires --hallucination-check-override-reason."
        ),
    )
    es.add_argument(
        "--hallucination-check-override-reason", default=None,
        help=(
            "Operator's rationale for stamping the hallucination-"
            "check override. Required when --hallucination-check-"
            "override is set; stamped on the draft_ready event for "
            "Pillar I per-tenant audit-tooling."
        ),
    )
    es.add_argument(
        "--voice-fidelity-check-override", action="store_true",
        help=(
            "Per ADR-0047 D247 — bypass the voice-fidelity dimension's "
            "refuse-loud. The emitted draft_ready event's voice_"
            "fidelity_check field stamps 'passed_via_override'; "
            "requires --voice-fidelity-check-override-reason. Ignored "
            "when --skip-fidelity-check is set."
        ),
    )
    es.add_argument(
        "--voice-fidelity-check-override-reason", default=None,
        help=(
            "Operator's rationale for stamping the voice-fidelity-"
            "check override. Required when --voice-fidelity-check-"
            "override is set AND --skip-fidelity-check is NOT set; "
            "stamped on the draft_ready event for Pillar I per-tenant "
            "audit-tooling."
        ),
    )
    es.add_argument(
        "--skip-fidelity-check", action="store_true",
        help=(
            "Per ADR-0047 D246 — skip the Layer 2 voice-fidelity "
            "scorer. Operators with voice.use_embedding_primitive: "
            "false (legacy posture per ADR-0045 §Migration/rollout "
            "Path B) use this; the emitted draft_ready event carries "
            "voice_fidelity_check: 'skipped'."
        ),
    )
    es.add_argument(
        "--apply", action="store_true",
        help=(
            "Append the per-Layer events at their existing cardinality "
            "(hallucination_detected emit-only-on-uncited per ADR-0043 "
            "D219; draft_quality_scored emit-always per ADR-0045 D231 "
            "unless --skip-fidelity-check) + draft_ready event (emit-"
            "only-on-both-pass per ADR-0047 D246) to the ledger. "
            "Default is dry-run (report only)."
        ),
    )
    es.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "parse":
        return _cmd_parse(args)
    if args.cmd == "measure":
        return _cmd_measure(args)
    if args.cmd == "score":
        return _cmd_score(args)
    if args.cmd == "emit-ready":
        return _cmd_emit_ready(args)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
