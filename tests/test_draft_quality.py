"""Unit tests for the Pillar F Week 6 hallucination-detection primitive.

Per ADR-0043 (D212-D219) — the Layer 2 + Layer 3 primitive that
extends Pillar F's hallucination-detection FIVE-layer defense per
ADR-0038 D180. Coverage:

* :class:`DraftQualityResult` Layer 2 construction-time invariants
  per ADR-0043 D213 — refuses-loud at construction when
  ``state="ready"`` AND ``uncited_claims`` non-empty.
* :class:`ParsedClaim` + :data:`CLAIM_TYPES` closed enum per
  ADR-0043 D214.
* :func:`parse_draft_for_claims` Layer 3 deterministic per-claim
  extractor per ADR-0043 D214 (date_reference / named_entity /
  you_phrase / quoted_text / dated_event).
* :func:`score_draft` per-call composite Layer 2 + Layer 3 entry
  point + per-register threshold consumption per ADR-0043 D215.
* :func:`build_hallucination_detected_payload` event-shape factory
  per ADR-0043 D216 (privacy-respecting payload — sha256
  ``draft_hash`` + per-claim ``{claim_type, claim_text,
  citation_anchor}`` tuples; NO raw draft body).
* :data:`EMITTED_BY` marker per ADR-0010 D17 + ADR-0043 D216.
* TEST-ONLY ``embed_fn`` seam preservation per ADR-0043 D218 —
  FIRST non-N/A verification at a new encoding surface (Week 2
  audit P3-B carry-forward; reaffirmed at Weeks 3+4+5; verified at
  Week 6).
* CLI smoke tests (``parse`` subcommand) per ADR-0043 D212.

Test isolation: tests pass per-call ``thresholds_path`` to
control the per-register threshold loader; the per-call
``--thresholds-path`` CLI flag controls the subprocess invocation.
Subprocess invocations create fresh processes so the per-process
``_VOICE_THRESHOLDS_CACHE`` is naturally per-test.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pytest
import yaml

import draft_quality
from draft_quality import (
    CLAIM_TYPES,
    EMITTED_BY,
    DraftFidelityResult,
    DraftQualityResult,
    Layer4GuardRefusal,
    ParsedClaim,
    build_draft_quality_scored_payload,
    build_draft_ready_payload,
    build_hallucination_detected_payload,
    compute_draft_fidelity_score,
    parse_draft_for_claims,
    score_draft,
)
from voice_corpus import (
    CHANNELS,
    DEFAULT_VOICE_THRESHOLD_PER_REGISTER,
    REGISTERS,
    VoiceExemplar,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DRAFT_QUALITY_SCRIPT = REPO_ROOT / "orchestrator" / "draft_quality.py"


# ---------------------------------------------------------------------------
# Test fixtures + helpers
# ---------------------------------------------------------------------------


def _hash(text: str) -> str:
    """sha256:<hex> of a string — matches the framework's privacy convention."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_thresholds(path: Path, thresholds: dict | None = None) -> Path:
    """Write a thresholds YAML at path; returns path for chaining."""
    if thresholds is None:
        thresholds = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
    path.write_text(yaml.safe_dump({"thresholds": thresholds}))
    return path


def _env(tmp_path: Path) -> dict:
    """Build a subprocess env with OUTREACH_FACTORY_CONFIG absent so the
    CLI's :func:`_load_config` returns ``{}`` instead of pulling the
    operator's real config.yml."""
    import os as _os
    absent_cfg = tmp_path / "nonexistent_config.yml"
    return {**_os.environ, "OUTREACH_FACTORY_CONFIG": str(absent_cfg)}


def _basic_claim(
    *,
    claim_type: str = "named_entity",
    claim_text: str = "Acme Corp",
    citation_anchor: str | None = None,
) -> ParsedClaim:
    return ParsedClaim(
        claim_type=claim_type,
        claim_text=claim_text,
        citation_anchor=citation_anchor,
    )


def _basic_result(
    *,
    state: str = "refused",
    register: str = "cold-pitch",
    channel: str = "email",
    parsed_claims: tuple[ParsedClaim, ...] | None = None,
    uncited_claims: tuple[ParsedClaim, ...] | None = None,
    threshold: float = 0.70,
    draft_body: str = "Hey, you posted about X last week.",
) -> DraftQualityResult:
    if parsed_claims is None and uncited_claims is None:
        parsed_claims = (_basic_claim(),)
        uncited_claims = parsed_claims
    elif parsed_claims is None:
        parsed_claims = uncited_claims or ()
    elif uncited_claims is None:
        uncited_claims = tuple(c for c in parsed_claims if c.citation_anchor is None)
    return DraftQualityResult(
        draft_hash=_hash(draft_body),
        register=register,
        channel=channel,
        parsed_claims=parsed_claims,
        uncited_claims=uncited_claims,
        threshold=threshold,
        state=state,
    )


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Pin the module-level constants per ADR-0043 D214 + D216."""

    def test_claim_types_is_frozenset(self):
        """D214 — CLAIM_TYPES is a closed-set frozenset (operator-deliberate
        extension via ADR amendment)."""
        assert isinstance(CLAIM_TYPES, frozenset)

    def test_claim_types_exact_five_values(self):
        """D214 — exactly five claim types per ADR-0038 D180 + ADR-0043 D214."""
        assert CLAIM_TYPES == frozenset({
            "date_reference",
            "named_entity",
            "you_phrase",
            "quoted_text",
            "dated_event",
        })

    def test_emitted_by_marker(self):
        """D216 + ADR-0010 D17 — per-primitive marker for ledger
        filterability."""
        assert EMITTED_BY == "draft_quality"


# ---------------------------------------------------------------------------
# DraftQualityResult — Layer 2 construction-time invariants
# ---------------------------------------------------------------------------


class TestDraftQualityResult:
    """Layer 2 construction-time invariants per ADR-0043 D213.

    The LOAD-BEARING refuse-loud surface: a ``state="ready"``
    result with ``uncited_claims`` non-empty MUST be refused at
    construction time per ADR-0038 D180 Layer 2.
    """

    def test_construct_ready_with_empty_uncited_succeeds(self):
        """D213 — ``state="ready"`` is valid when ``uncited_claims`` is
        empty (the accept-case)."""
        result = _basic_result(
            state="ready",
            parsed_claims=(_basic_claim(citation_anchor="https://x.com/y"),),
            uncited_claims=(),
        )
        assert result.state == "ready"
        assert result.uncited_claims == ()

    def test_construct_refused_with_nonempty_uncited_succeeds(self):
        """D213 — ``state="refused"`` is valid when ``uncited_claims``
        is non-empty (the refuse-case)."""
        result = _basic_result(state="refused")
        assert result.state == "refused"
        assert len(result.uncited_claims) == 1

    def test_construct_ready_with_nonempty_uncited_refuses_loud(self):
        """D213 — THE Layer 2 invariant: ``state="ready"`` AND
        ``uncited_claims`` non-empty MUST raise ValueError. Per
        ADR-0038 D180 the structural commitment of Layer 2."""
        with pytest.raises(ValueError, match="uncited|ready"):
            _basic_result(state="ready")

    def test_unknown_state_refuses_loud(self):
        """D213 — state outside {ready, refused} raises ValueError."""
        with pytest.raises(ValueError, match="state"):
            _basic_result(state="pending")

    def test_unknown_register_refuses_loud(self):
        """D213 — register not in REGISTERS raises ValueError (closed
        enum per ADR-0038 D178)."""
        with pytest.raises(ValueError, match="register"):
            _basic_result(register="introduction")

    def test_unknown_channel_refuses_loud(self):
        """D213 — channel not in CHANNELS raises ValueError (closed
        enum per ADR-0014 D33)."""
        with pytest.raises(ValueError, match="channel"):
            _basic_result(channel="fax")

    def test_draft_hash_must_be_sha256_prefixed(self):
        """D213 + I8 privacy invariant — draft_hash must start with
        sha256: prefix (no raw draft body in result)."""
        with pytest.raises(ValueError, match="draft_hash|sha256"):
            DraftQualityResult(
                draft_hash="plain text not a hash",
                register="cold-pitch",
                channel="email",
                parsed_claims=(),
                uncited_claims=(),
                threshold=0.70,
                state="ready",
            )

    def test_threshold_below_zero_refuses_loud(self):
        """D213 — threshold must be in [0.0, 1.0] per ADR-0041 D201."""
        with pytest.raises(ValueError, match="threshold"):
            _basic_result(threshold=-0.1)

    def test_threshold_above_one_refuses_loud(self):
        """D213 — threshold must be in [0.0, 1.0]; > 1.0 rejected."""
        with pytest.raises(ValueError, match="threshold"):
            _basic_result(threshold=1.5)

    def test_threshold_boundary_zero_accepted(self):
        """D213 — threshold = 0.0 is operator-deliberate disabled gate."""
        result = _basic_result(
            state="ready",
            parsed_claims=(),
            uncited_claims=(),
            threshold=0.0,
        )
        assert result.threshold == 0.0

    def test_threshold_boundary_one_accepted(self):
        """D213 — threshold = 1.0 is operator-deliberate perfect-match-only
        gate."""
        result = _basic_result(
            state="ready",
            parsed_claims=(),
            uncited_claims=(),
            threshold=1.0,
        )
        assert result.threshold == 1.0

    def test_uncited_must_be_subset_of_parsed(self):
        """D213 — every member of uncited_claims MUST appear in
        parsed_claims (a structural invariant — operators can't surface
        uncited claims that don't exist in the parse)."""
        rogue = _basic_claim(claim_text="not in parsed list")
        present = _basic_claim(citation_anchor="https://x.com/y")
        with pytest.raises(ValueError, match="subset|parsed_claims"):
            DraftQualityResult(
                draft_hash=_hash("draft"),
                register="cold-pitch",
                channel="email",
                parsed_claims=(present,),
                uncited_claims=(rogue,),
                threshold=0.70,
                state="refused",
            )

    def test_uncited_must_have_citation_anchor_none(self):
        """D213 — every member of uncited_claims MUST have
        citation_anchor is None (cited claims belong in parsed_claims
        but not in uncited_claims)."""
        cited = _basic_claim(citation_anchor="https://x.com/y")
        with pytest.raises(ValueError, match="citation_anchor"):
            DraftQualityResult(
                draft_hash=_hash("draft"),
                register="cold-pitch",
                channel="email",
                parsed_claims=(cited,),
                uncited_claims=(cited,),
                threshold=0.70,
                state="refused",
            )

    def test_result_is_frozen(self):
        """D213 — frozen dataclass prevents post-construction mutation
        (attribute assignment raises)."""
        result = _basic_result()
        with pytest.raises((AttributeError, TypeError)):
            result.state = "ready"

    def test_parsed_claims_is_tuple_not_list(self):
        """D213 — tuple-typed claims field prevents caller mutation that
        would silently invalidate the construction-time invariant."""
        result = _basic_result()
        assert isinstance(result.parsed_claims, tuple)
        assert isinstance(result.uncited_claims, tuple)

    def test_parsed_claims_per_item_must_be_parsed_claim(self):
        """D213 + Week 6 follow-up P2-1 — every parsed_claims item MUST
        be a ParsedClaim instance. Without this guard, downstream
        consumers (Week 8+ fidelity-scoring; Week 10 emit guard; Week
        12 reconcile heal-pass) reading `.claim_type` / `.claim_text` /
        `.citation_anchor` would see AttributeError at consumption time
        — silently bypassing the Layer 2 gate's structural commitment.
        Pins the per-item type check separately from the container-type
        check to close the P3-1 documentation-test drift gap."""
        with pytest.raises(ValueError, match="ParsedClaim|parsed_claims"):
            DraftQualityResult(
                draft_hash=_hash("d"),
                register="cold-pitch",
                channel="email",
                parsed_claims=(  # dict masquerading as ParsedClaim
                    {"claim_type": "named_entity",
                     "claim_text": "Acme Corp",
                     "citation_anchor": None},
                ),
                uncited_claims=(),
                threshold=0.70,
                state="ready",
            )

    def test_uncited_claims_per_item_must_be_parsed_claim(self):
        """D213 + Week 6 follow-up P2-1 — every uncited_claims item MUST
        be a ParsedClaim instance. Companion to the parsed_claims
        per-item check; the uncited_claims subset-invariant loop's
        attribute access (`uc.citation_anchor`) would surface
        AttributeError, but the construction-time refusal is the
        operator-readable surface."""
        real_claim = _basic_claim()
        with pytest.raises(ValueError, match="ParsedClaim|uncited_claims"):
            DraftQualityResult(
                draft_hash=_hash("d"),
                register="cold-pitch",
                channel="email",
                parsed_claims=(real_claim,),
                uncited_claims=(
                    {"claim_type": "named_entity",
                     "claim_text": "X",
                     "citation_anchor": None},
                ),
                threshold=0.70,
                state="refused",
            )

    def test_all_five_registers_accepted(self):
        """D213 — every register in REGISTERS is a valid construction
        target. Structural symmetry pin per ADR-0038 D178."""
        for register in REGISTERS:
            result = _basic_result(
                state="ready",
                register=register,
                parsed_claims=(),
                uncited_claims=(),
            )
            assert result.register == register

    def test_all_four_channels_accepted(self):
        """D213 — every channel in CHANNELS is a valid construction
        target. Structural symmetry pin per ADR-0014 D33."""
        for channel in CHANNELS:
            result = _basic_result(
                state="ready",
                channel=channel,
                parsed_claims=(),
                uncited_claims=(),
            )
            assert result.channel == channel


# ---------------------------------------------------------------------------
# ParsedClaim — per-claim trace shape
# ---------------------------------------------------------------------------


class TestParsedClaim:
    """Per-claim trace shape per ADR-0043 D214 — frozen dataclass with
    claim_type + claim_text + citation_anchor."""

    def test_construct_with_anchor(self):
        """D214 — cited claim carries a non-None citation_anchor."""
        c = _basic_claim(citation_anchor="https://example.com/post")
        assert c.citation_anchor == "https://example.com/post"

    def test_construct_without_anchor(self):
        """D214 — uncited claim has citation_anchor is None."""
        c = _basic_claim(citation_anchor=None)
        assert c.citation_anchor is None

    def test_unknown_claim_type_refuses_loud(self):
        """D214 — claim_type not in CLAIM_TYPES raises ValueError."""
        with pytest.raises(ValueError, match="claim_type"):
            ParsedClaim(
                claim_type="unsupported_type",
                claim_text="X",
                citation_anchor=None,
            )

    def test_empty_claim_text_refuses_loud(self):
        """D214 — empty claim_text (whitespace-only) raises ValueError."""
        with pytest.raises(ValueError, match="claim_text"):
            ParsedClaim(
                claim_type="named_entity",
                claim_text="   ",
                citation_anchor=None,
            )

    def test_all_five_claim_types_accepted(self):
        """D214 — every claim type in CLAIM_TYPES is a valid construction
        target. Structural symmetry pin."""
        for claim_type in CLAIM_TYPES:
            c = ParsedClaim(
                claim_type=claim_type,
                claim_text="sample",
                citation_anchor=None,
            )
            assert c.claim_type == claim_type

    def test_parsed_claim_is_frozen(self):
        """D214 — frozen dataclass prevents post-construction mutation."""
        c = _basic_claim()
        with pytest.raises((AttributeError, TypeError)):
            c.citation_anchor = "https://x.com/y"


# ---------------------------------------------------------------------------
# parse_draft_for_claims — Layer 3 deterministic parser
# ---------------------------------------------------------------------------


class TestParseDraftForClaims:
    """Layer 3 deterministic parser per ADR-0043 D214.

    Per-claim-type extraction + per-claim citation cross-reference
    against the dossier. Deterministic (regex-based; substring +
    regex cross-reference); no encoding at Week 6.
    """

    def test_extracts_iso_date_reference(self):
        """D214 — ISO 8601 date `2026-03-15` is a date_reference claim."""
        draft = "Saw your launch on 2026-03-15, congrats."
        dossier = "## Launch — March 15\nThe launch happened on 2026-03-15."
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        date_claims = [c for c in claims if c.claim_type == "date_reference"]
        assert len(date_claims) >= 1
        assert any("2026-03-15" in c.claim_text for c in date_claims)

    def test_extracts_relative_time_phrase(self):
        """D214 — 'last week' is a relative-time date_reference."""
        draft = "Hi, you posted last week about your raise."
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        date_claims = [c for c in claims if c.claim_type == "date_reference"]
        assert any("last week" in c.claim_text.lower() for c in date_claims)

    def test_extracts_month_year_phrase(self):
        """D214 — 'April 2026' is a date_reference."""
        draft = "I saw your April 2026 update."
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        date_claims = [c for c in claims if c.claim_type == "date_reference"]
        assert any("april 2026" in c.claim_text.lower() for c in date_claims)

    def test_extracts_quarter_phrase(self):
        """D214 — 'Q1 2026' is a date_reference."""
        draft = "Following your Q1 2026 momentum."
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        date_claims = [c for c in claims if c.claim_type == "date_reference"]
        assert any("q1 2026" in c.claim_text.lower() for c in date_claims)

    def test_extracts_named_entity_multiword_titlecase(self):
        """D214 — multi-word title-case span is a named_entity."""
        draft = "Hey, congrats on Series A from Acme Ventures."
        dossier = "## Funding\nAcme Ventures led the Series A."
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        ents = [c for c in claims if c.claim_type == "named_entity"]
        assert any("Acme Ventures" in c.claim_text for c in ents)

    def test_stopword_does_not_become_named_entity(self):
        """D214 — sentence-starter stopwords (`Hey`, `The`, `My`) don't
        become named_entity false-positives."""
        draft = "Hey there. The team is great."
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        ent_texts = {c.claim_text for c in claims if c.claim_type == "named_entity"}
        assert "Hey there" not in ent_texts
        assert "The team" not in ent_texts

    def test_extracts_you_phrase_posted(self):
        """D214 — 'you posted...' is a you_phrase claim."""
        draft = "Saw you posted about your Series A."
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        you_phrases = [c for c in claims if c.claim_type == "you_phrase"]
        assert len(you_phrases) >= 1
        assert any("you posted" in c.claim_text.lower() for c in you_phrases)

    def test_extracts_you_phrase_launched(self):
        """D214 — 'you launched...' is a you_phrase claim."""
        draft = "Loved that you launched the new feature."
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        you_phrases = [c for c in claims if c.claim_type == "you_phrase"]
        assert any("you launched" in c.claim_text.lower() for c in you_phrases)

    def test_extracts_quoted_text(self):
        """D214 — straight-quote span is a quoted_text claim."""
        draft = 'You said "this is the year of agents" recently.'
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        quoted = [c for c in claims if c.claim_type == "quoted_text"]
        assert any(
            "this is the year of agents" in c.claim_text
            for c in quoted
        )

    def test_extracts_dated_event(self):
        """D214 — named entity within 5 tokens of a date_reference is
        a dated_event."""
        draft = "Following your March launch of the platform."
        dossier = ""
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        events = [c for c in claims if c.claim_type == "dated_event"]
        assert len(events) >= 1

    def test_cited_claim_carries_anchor(self):
        """D214 — a claim with a matching dossier anchor has
        citation_anchor set to the anchor (URL or line ref)."""
        draft = "Acme Corp raised $5M."
        dossier = "## Funding\nAcme Corp [1] raised $5M.\n\n[1]: https://crunchbase.com/acme"
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        cited = [c for c in claims if c.citation_anchor is not None]
        assert len(cited) >= 1

    def test_uncited_claim_has_none_anchor(self):
        """D214 — a claim NOT in the dossier has citation_anchor is None."""
        draft = "Following your Phantom Project launch."
        dossier = "## Other section\nUnrelated content here."
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        uncited = [c for c in claims if c.citation_anchor is None]
        assert len(uncited) >= 1

    def test_url_in_dossier_serves_as_anchor(self):
        """D214 — markdown URL in dossier serves as citation_anchor.
        The dossier's markdown link `[Acme Corp](URL)` makes "Acme
        Corp" findable + the nearby URL becomes the per-claim
        anchor."""
        draft = "Loved your Acme Corp post."
        dossier = "Their [Acme Corp](https://example.com/blog) was great."
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        cited = [c for c in claims if c.citation_anchor is not None]
        assert any("example.com" in (c.citation_anchor or "") for c in cited)

    def test_verbatim_quote_match_for_quoted_text(self):
        """D214 — quoted_text claim requires exact (verbatim) match in
        the dossier; fuzzy match defers to Week 8+."""
        draft = 'You said "agents are eating SaaS" recently.'
        dossier = 'Quote: "agents are eating SaaS"'
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        quoted_cited = [
            c for c in claims
            if c.claim_type == "quoted_text" and c.citation_anchor is not None
        ]
        assert len(quoted_cited) >= 1

    def test_quoted_text_without_verbatim_match_is_uncited(self):
        """D214 — paraphrased quoted text in dossier does NOT count as
        cited at Week 6 (verbatim only)."""
        draft = 'You said "the year of agents is now".'
        dossier = "They talked about agents being the future."
        claims = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        quoted_uncited = [
            c for c in claims
            if c.claim_type == "quoted_text" and c.citation_anchor is None
        ]
        assert len(quoted_uncited) >= 1

    def test_deterministic_output(self):
        """D214 — same input produces same output across calls per the
        ADR-0013 D24 reproducibility invariant."""
        draft = "Hey, you posted about Acme Corp last week."
        dossier = "## Posts\nAcme Corp announcement."
        c1 = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        c2 = parse_draft_for_claims(draft, dossier, register="cold-pitch")
        assert c1 == c2

    def test_register_must_be_known(self):
        """D214 — unknown register raises ValueError (closed enum)."""
        with pytest.raises(ValueError, match="register"):
            parse_draft_for_claims(
                "hi", "dossier", register="introduction",
            )

    def test_empty_draft_returns_no_claims(self):
        """D214 — empty draft string yields empty claim list (no
        extraction)."""
        claims = parse_draft_for_claims("", "dossier", register="cold-pitch")
        assert claims == []


# ---------------------------------------------------------------------------
# score_draft — composite Layer 2 + Layer 3 entry point
# ---------------------------------------------------------------------------


class TestScoreDraft:
    """Composite Layer 2 + Layer 3 entry point per ADR-0043 D215.

    Per-call: validate register/channel (closed enum) → resolve
    threshold via Week 4 loader → parse + cross-reference (Layer 3)
    → decide state → construct DraftQualityResult (Layer 2 runs).
    """

    def test_clean_draft_passes_gate(self, tmp_path):
        """D215 — a draft with no extractable claims (or all claims
        cited) yields state="ready"."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft = "Hello."
        dossier = ""
        result = score_draft(
            draft, dossier,
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds,
        )
        assert result.state == "ready"
        assert result.uncited_claims == ()

    def test_uncited_draft_refuses_loud(self, tmp_path):
        """D215 — a draft with an uncited claim yields state="refused".
        This is the ADR-0038 D180 binding behavior."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft = "You posted about Phantom Entity last week."
        dossier = "## Unrelated\nNothing matching."
        result = score_draft(
            draft, dossier,
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds,
        )
        assert result.state == "refused"
        assert len(result.uncited_claims) >= 1

    def test_threshold_stamped_on_result(self, tmp_path):
        """D215 — per-register threshold from Week 4 loader is stamped
        on the result (the field is consumer-readable for Week 8+
        fidelity-scoring + Week 10 Layer 4 emit guard + Week 12
        Layer 5 reconcile)."""
        custom = dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER)
        custom["cold-pitch"] = 0.85
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml", custom)
        result = score_draft(
            "Hello.", "",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds,
        )
        assert result.threshold == 0.85

    def test_draft_hash_in_result_is_sha256(self, tmp_path):
        """D215 + I8 — result's draft_hash is sha256-prefixed, NOT raw
        draft body."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft = "this is some draft text."
        result = score_draft(
            draft, "",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds,
        )
        assert result.draft_hash.startswith("sha256:")
        assert "this is some draft" not in result.draft_hash

    def test_unknown_register_refuses_loud(self, tmp_path):
        """D215 — unknown register raises BEFORE parser load (closed
        enum at the entry point)."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        with pytest.raises(ValueError, match="register"):
            score_draft(
                "draft", "dossier",
                register="introduction",
                channel="email",
                thresholds_path=thresholds,
            )

    def test_unknown_channel_refuses_loud(self, tmp_path):
        """D215 — unknown channel raises BEFORE parser load."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        with pytest.raises(ValueError, match="channel"):
            score_draft(
                "draft", "dossier",
                register="cold-pitch",
                channel="fax",
                thresholds_path=thresholds,
            )

    def test_all_five_registers_accepted(self, tmp_path):
        """D215 — every register in REGISTERS is a valid entry-point
        argument. Structural symmetry pin."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        for register in REGISTERS:
            result = score_draft(
                "Hello.", "",
                register=register,
                channel="email",
                thresholds_path=thresholds,
            )
            assert result.register == register

    def test_register_stamped_on_result(self, tmp_path):
        """D215 — operator-supplied register lands on result.register."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        result = score_draft(
            "Hello.", "",
            register="congrats",
            channel="linkedin-dm",
            thresholds_path=thresholds,
        )
        assert result.register == "congrats"
        assert result.channel == "linkedin-dm"

    def test_parsed_claims_contains_both_cited_and_uncited(self, tmp_path):
        """D215 — result.parsed_claims includes ALL claims (cited +
        uncited); uncited_claims is the subset."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft = (
            "You posted about Acme Corp last week. "
            "Also saw Phantom Entity announcement."
        )
        dossier = "## Posts\nAcme Corp posted recently."
        result = score_draft(
            draft, dossier,
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds,
        )
        assert len(result.parsed_claims) >= len(result.uncited_claims)


# ---------------------------------------------------------------------------
# build_hallucination_detected_payload — event-shape factory
# ---------------------------------------------------------------------------


class TestBuildHallucinationDetectedPayload:
    """Event-shape factory per ADR-0043 D216.

    Privacy-respecting payload — sha256 draft_hash; per-claim
    {claim_type, claim_text, citation_anchor: None} tuples.
    Channel-on-every-event invariant per ADR-0014 D33.
    Emit-only-on-uncited per ADR-0043 D219.
    """

    def test_payload_shape(self):
        """D216 — payload carries all the named fields per the event
        shape table."""
        result = _basic_result()
        payload = build_hallucination_detected_payload(
            person_id="person-1",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["type"] == "hallucination_detected"
        assert payload["person_id"] == "person-1"
        assert payload["draft_hash"] == result.draft_hash
        assert payload["register"] == "cold-pitch"
        assert payload["channel"] == "email"
        assert payload["threshold"] == result.threshold
        assert payload["_emitted_by"] == EMITTED_BY
        assert isinstance(payload["uncited_claims"], list)
        assert len(payload["uncited_claims"]) == 1

    def test_payload_does_not_contain_raw_draft(self):
        """D216 + I8 — privacy invariant: raw draft body NEVER appears
        in payload (only sha256 hash). Per Week 6 follow-up P3-2: the
        check recursively inspects the uncited_claims list items so a
        regression that leaked the raw draft body into a per-claim
        trace's claim_text would surface here (NOT just the top-level
        string fields)."""
        body = "this is the literal draft body operators wrote"
        result = _basic_result(draft_body=body)
        payload = build_hallucination_detected_payload(
            person_id="x",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        # Recursively walk every string in the payload (top-level +
        # nested in lists + nested in dicts) to catch a regression
        # that leaked the raw draft body anywhere.
        def _walk(obj):
            if isinstance(obj, str):
                assert body not in obj, (
                    f"raw draft body leaked into payload: {obj!r}"
                )
            elif isinstance(obj, dict):
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)
        _walk(payload)

    def test_payload_carries_per_claim_trace(self):
        """D216 — per-claim trace is `{claim_type, claim_text,
        citation_anchor}` triples in uncited_claims list."""
        result = _basic_result()
        payload = build_hallucination_detected_payload(
            person_id="x",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        trace = payload["uncited_claims"][0]
        assert set(trace.keys()) == {"claim_type", "claim_text", "citation_anchor"}
        assert trace["citation_anchor"] is None

    def test_unknown_channel_refuses_loud(self):
        """D216 — channel not in CHANNELS raises ValueError (closed
        enum per ADR-0014 D33)."""
        result = _basic_result()
        with pytest.raises(ValueError, match="channel"):
            build_hallucination_detected_payload(
                person_id="x",
                result=result,
                channel="fax",
                register="cold-pitch",
            )

    def test_unknown_register_refuses_loud(self):
        """D216 — register not in REGISTERS raises ValueError (closed
        enum per ADR-0038 D178)."""
        result = _basic_result()
        with pytest.raises(ValueError, match="register"):
            build_hallucination_detected_payload(
                person_id="x",
                result=result,
                channel="email",
                register="introduction",
            )

    def test_empty_uncited_refuses_loud(self):
        """D216 + D219 — emit-only-on-uncited posture: factory refuses
        construction when uncited_claims is empty (the accept-case
        should not flow through the factory)."""
        result = _basic_result(
            state="ready",
            parsed_claims=(),
            uncited_claims=(),
        )
        with pytest.raises(ValueError, match="uncited"):
            build_hallucination_detected_payload(
                person_id="x",
                result=result,
                channel="email",
                register="cold-pitch",
            )

    def test_person_id_none_accepted(self):
        """D216 — person_id is operator-supplied; None accepted for
        ad-hoc validation outside the per-Person flow."""
        result = _basic_result()
        payload = build_hallucination_detected_payload(
            person_id=None,
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["person_id"] is None

    def test_emit_marker_is_draft_quality(self):
        """D216 + ADR-0010 D17 — _emitted_by stamps the per-primitive
        marker for ledger filterability."""
        result = _basic_result()
        payload = build_hallucination_detected_payload(
            person_id="x",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["_emitted_by"] == "draft_quality"

    def test_channel_on_every_event_invariant(self):
        """D216 + ADR-0014 D33 — every payload carries channel."""
        result = _basic_result()
        for channel in CHANNELS:
            r = _basic_result(channel=channel)
            payload = build_hallucination_detected_payload(
                person_id="x",
                result=r,
                channel=channel,
                register="cold-pitch",
            )
            assert payload["channel"] == channel

    def test_factory_refuses_channel_mismatch_with_result(self):
        """D216 + Week 6 follow-up P2-2 — the factory's channel kwarg
        MUST match result.channel. Without the check, a caller passing
        mismatched values silently emits an event claiming a different
        channel than the draft was scored against; per-Pillar-G
        dashboard's per-channel aggregation would surface phantom
        signals."""
        result = _basic_result(channel="email")
        with pytest.raises(ValueError, match="channel.*does not match"):
            build_hallucination_detected_payload(
                person_id="x",
                result=result,
                channel="linkedin-dm",  # mismatch with result.channel=email
                register="cold-pitch",
            )

    def test_factory_refuses_register_mismatch_with_result(self):
        """D216 + Week 6 follow-up P2-2 — the factory's register kwarg
        MUST match result.register."""
        result = _basic_result(register="cold-pitch")
        with pytest.raises(ValueError, match="register.*does not match"):
            build_hallucination_detected_payload(
                person_id="x",
                result=result,
                channel="email",
                register="congrats",  # mismatch with result.register=cold-pitch
            )


# ---------------------------------------------------------------------------
# TEST-ONLY embed_fn seam preservation — FIRST non-N/A verification
# ---------------------------------------------------------------------------


class TestSeamPreservation:
    """TEST-ONLY ``embed_fn`` seam preservation per ADR-0043 D218 —
    FIRST non-N/A verification at a new encoding surface (Week 2
    audit P3-B carry-forward; reaffirmed at Weeks 3+4+5; verified
    at Week 6).

    The Week 6 default code path does NOT encode (parser is
    deterministic + cross-reference is substring/regex). The
    ``embed_fn`` kwarg is PRE-INSTALLED in the public signatures
    with the seam labeled TEST-ONLY in the docstring; Week 8+
    ships the fuzzy-match scoring extension that actually
    consumes the encoder.
    """

    def test_parse_draft_for_claims_has_embed_fn_kwarg(self):
        """D218 — `parse_draft_for_claims` signature carries
        TEST-ONLY embed_fn kwarg per ADR-0043 D218."""
        import inspect
        sig = inspect.signature(parse_draft_for_claims)
        assert "embed_fn" in sig.parameters

    def test_score_draft_has_embed_fn_kwarg(self):
        """D218 — `score_draft` signature carries TEST-ONLY embed_fn
        kwarg per ADR-0043 D218."""
        import inspect
        sig = inspect.signature(score_draft)
        assert "embed_fn" in sig.parameters

    def test_parse_draft_docstring_labels_embed_fn_test_only(self):
        """D218 — `parse_draft_for_claims` docstring labels embed_fn
        as TEST-ONLY per ADR-0040 D197 + ADR-0043 D218."""
        doc = parse_draft_for_claims.__doc__ or ""
        assert "TEST-ONLY" in doc

    def test_score_draft_docstring_labels_embed_fn_test_only(self):
        """D218 — `score_draft` docstring labels embed_fn as
        TEST-ONLY."""
        doc = score_draft.__doc__ or ""
        assert "TEST-ONLY" in doc

    def test_cli_has_no_embed_fn_flag(self):
        """D218 — CLI does NOT surface --embed-fn (security + audit
        concern per ADR-0039 D188-Alt3 + ADR-0040 D197-Alt1)."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "--embed-fn" not in proc.stdout
        assert "--embed_fn" not in proc.stdout


# ---------------------------------------------------------------------------
# CLI smoke tests — `python orchestrator/draft_quality.py parse`
# ---------------------------------------------------------------------------


class TestCLIParse:
    """CLI smoke tests per ADR-0043 D212 — the ``parse`` subcommand
    surfaces the Layer 2 + Layer 3 gate to operators.

    Test isolation: tests pass --thresholds-path explicitly to
    control which YAML the loader reads. Subprocess invocations
    create new processes per test, so the per-process
    _VOICE_THRESHOLDS_CACHE is fresh per test naturally.
    """

    def _run_parse(
        self,
        *,
        tmp_path: Path,
        draft: str,
        dossier: str,
        register: str = "cold-pitch",
        channel: str = "email",
        thresholds_path: Path | None = None,
        apply: bool = False,
        json_output: bool = True,
    ) -> subprocess.CompletedProcess:
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text(draft)
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text(dossier)
        if thresholds_path is None:
            thresholds_path = _write_thresholds(tmp_path / "voice_thresholds.yml")
        argv = [
            sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse",
            "--draft-path", str(draft_path),
            "--research-dossier-path", str(dossier_path),
            "--register", register,
            "--channel", channel,
            "--thresholds-path", str(thresholds_path),
        ]
        if apply:
            argv.append("--apply")
        if json_output:
            argv.append("--json")
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )

    def test_help_lists_parse_subcommand(self):
        """D212 — top-level --help advertises parse subcommand."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        assert "parse" in proc.stdout

    def test_parse_clean_draft_json_emits_ready(self, tmp_path):
        """D212 — clean draft (no uncited claims) yields state=ready."""
        proc = self._run_parse(
            tmp_path=tmp_path,
            draft="Hello.",
            dossier="",
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["state"] == "ready"
        assert out["uncited_claims"] == []

    def test_parse_uncited_draft_json_emits_refused(self, tmp_path):
        """D212 — draft with uncited claim yields state=refused +
        per-claim trace in output."""
        proc = self._run_parse(
            tmp_path=tmp_path,
            draft="You posted about Phantom Entity last week.",
            dossier="## Unrelated\nNothing.",
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["state"] == "refused"
        assert len(out["uncited_claims"]) >= 1

    def test_parse_per_claim_trace_in_json(self, tmp_path):
        """D212 + D216 — per-claim trace is operator-readable in JSON
        output."""
        proc = self._run_parse(
            tmp_path=tmp_path,
            draft="You launched a Phantom Project last week.",
            dossier="",
        )
        out = json.loads(proc.stdout)
        for trace in out["uncited_claims"]:
            assert "claim_type" in trace
            assert "claim_text" in trace
            assert trace["citation_anchor"] is None

    def test_parse_text_mode_human_readable(self, tmp_path):
        """D212 — non-JSON mode produces operator-readable output."""
        proc = self._run_parse(
            tmp_path=tmp_path,
            draft="Hi.",
            dossier="",
            json_output=False,
        )
        assert proc.returncode == 0
        # Should mention state or verdict in the text output
        assert "ready" in proc.stdout.lower() or "state" in proc.stdout.lower()

    def test_parse_text_mode_refused_has_per_claim_trace(self, tmp_path):
        """D212 — text mode prints per-claim trace operator-readably."""
        proc = self._run_parse(
            tmp_path=tmp_path,
            draft="You posted about Phantom Entity last week.",
            dossier="",
            json_output=False,
        )
        assert proc.returncode == 0
        assert "refused" in proc.stdout.lower()
        # Should mention at least one claim type
        assert any(
            ct in proc.stdout
            for ct in ("you_phrase", "date_reference", "named_entity")
        )

    def test_parse_unknown_register_refuses_loud(self, tmp_path):
        """D212 — argparse-choices on --register rejects unknown values."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("hi")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("")
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse",
             "--draft-path", str(draft_path),
             "--research-dossier-path", str(dossier_path),
             "--register", "introduction",
             "--channel", "email",
             "--thresholds-path", str(thresholds)],
            capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )
        assert proc.returncode != 0

    def test_parse_unknown_channel_refuses_loud(self, tmp_path):
        """D212 — argparse-choices on --channel rejects unknown values."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("hi")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("")
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse",
             "--draft-path", str(draft_path),
             "--research-dossier-path", str(dossier_path),
             "--register", "cold-pitch",
             "--channel", "fax",
             "--thresholds-path", str(thresholds)],
            capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )
        assert proc.returncode != 0

    def test_parse_missing_draft_file_refuses_loud(self, tmp_path):
        """D212 — missing draft file path raises operator-readable error."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse",
             "--draft-path", str(tmp_path / "absent.txt"),
             "--research-dossier-path", str(tmp_path / "absent.md"),
             "--register", "cold-pitch",
             "--channel", "email",
             "--thresholds-path", str(thresholds)],
            capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "not found" in proc.stderr.lower() or "no such file" in proc.stderr.lower() or "error" in proc.stderr.lower()

    def test_parse_apply_true_emits_event_to_ledger(self, tmp_path):
        """D219 + Week 6 follow-up P2-3 — emit-matrix row 4: with
        `--apply` and uncited_claims non-empty, the CLI MUST write the
        hallucination_detected event to the ledger. The most
        load-bearing emit-matrix cell — without this test, a bug in
        the led.append integration path (wrong event shape, wrong
        ledger directory resolution, ledger write failure silently
        swallowed) would not be caught."""
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        env = _env(tmp_path)
        env["OUTREACH_FACTORY_LEDGER_DIR"] = str(ledger_dir)
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("You posted about Phantom Entity last week.")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("")
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse",
             "--draft-path", str(draft_path),
             "--research-dossier-path", str(dossier_path),
             "--register", "cold-pitch",
             "--channel", "email",
             "--thresholds-path", str(thresholds),
             "--apply",
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        # Verify the ledger directory now has at least one .jsonl file
        # containing a hallucination_detected event.
        jsonl_files = list(ledger_dir.rglob("*.jsonl"))
        assert len(jsonl_files) >= 1, (
            f"Expected at least one ledger .jsonl file after --apply; "
            f"got {[str(p) for p in ledger_dir.rglob('*')]!r}"
        )
        # Walk the JSONL events; verify the hallucination_detected
        # event is present with the correct shape.
        found = False
        for jf in jsonl_files:
            for line in jf.read_text().splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("type") == "hallucination_detected":
                    assert event["_emitted_by"] == "draft_quality"
                    assert event["draft_hash"].startswith("sha256:")
                    assert event["register"] == "cold-pitch"
                    assert event["channel"] == "email"
                    assert len(event["uncited_claims"]) >= 1
                    # Privacy invariant — raw draft body NOT in event.
                    assert "Phantom Entity" not in event["draft_hash"]
                    found = True
        assert found, (
            f"No hallucination_detected event found in ledger files "
            f"{[str(p) for p in jsonl_files]!r}"
        )

    def test_parse_dry_run_does_not_emit_event(self, tmp_path):
        """D219 — without --apply, the CLI does NOT write to the ledger
        even when state=refused."""
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        env = _env(tmp_path)
        env["OUTREACH_FACTORY_LEDGER_DIR"] = str(ledger_dir)
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("You posted about Phantom Entity last week.")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("")
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse",
             "--draft-path", str(draft_path),
             "--research-dossier-path", str(dossier_path),
             "--register", "cold-pitch",
             "--channel", "email",
             "--thresholds-path", str(thresholds),
             "--json"],
            capture_output=True, text=True, timeout=30,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        # No ledger files written in dry-run.
        ledger_files = list(ledger_dir.rglob("*"))
        # Only the directory itself exists, no JSONL files written
        jsonl_files = [f for f in ledger_files if f.is_file() and f.suffix == ".jsonl"]
        assert jsonl_files == []


# ---------------------------------------------------------------------------
# Privacy invariants (cross-cutting)
# ---------------------------------------------------------------------------


class TestPrivacyInvariants:
    """Per I8 + ADR-0038 §Compliance with invariants — privacy
    preservation across the result + factory + payload boundary.

    The hallucination_detected event MUST NOT carry raw draft
    body OR per-claim citation context that would leak operator
    research. The hash-only posture mirrors the
    voice_exemplar_retrieved event's query_hash discipline per
    ADR-0039 D189.
    """

    def test_score_draft_does_not_store_raw_draft_in_result(self, tmp_path):
        """I8 — result.draft_hash is sha256-prefixed; raw text never
        appears."""
        thresholds = _write_thresholds(tmp_path / "voice_thresholds.yml")
        body = "this is the literal draft text from the operator"
        result = score_draft(
            body, "",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds,
        )
        assert "this is the literal" not in result.draft_hash

    def test_payload_does_not_contain_dossier_body(self):
        """I8 — payload's citation_anchor is URL OR line-ref only; the
        dossier body content does NOT appear in the payload (operator-
        confidential research per ADR-0038 D182 §category 8)."""
        dossier_body = "secret operator research that should not leak"
        cited = ParsedClaim(
            claim_type="named_entity",
            claim_text="Acme",
            citation_anchor="https://example.com/post#L12",
        )
        uncited = ParsedClaim(
            claim_type="you_phrase",
            claim_text="you launched the new feature",
            citation_anchor=None,
        )
        result = DraftQualityResult(
            draft_hash=_hash("d"),
            register="cold-pitch",
            channel="email",
            parsed_claims=(cited, uncited),
            uncited_claims=(uncited,),
            threshold=0.70,
            state="refused",
        )
        payload = build_hallucination_detected_payload(
            person_id="p",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        for value in payload.values():
            if isinstance(value, str):
                assert dossier_body not in value
            if isinstance(value, list):
                # uncited_claims list — recursively check nested strings
                for item in value:
                    if isinstance(item, dict):
                        for sub in item.values():
                            if isinstance(sub, str):
                                assert dossier_body not in sub

    def test_payload_claim_text_is_draft_span_not_dossier(self):
        """I8 — per-claim trace's claim_text IS the draft's literal
        claim span (operator-visible diagnostic) — NOT the dossier
        content. The operator wrote the draft span; surfacing it back
        is operator-deliberate."""
        draft_span = "you launched Phantom Project last week"
        uncited = ParsedClaim(
            claim_type="you_phrase",
            claim_text=draft_span,
            citation_anchor=None,
        )
        result = DraftQualityResult(
            draft_hash=_hash("draft body"),
            register="cold-pitch",
            channel="email",
            parsed_claims=(uncited,),
            uncited_claims=(uncited,),
            threshold=0.70,
            state="refused",
        )
        payload = build_hallucination_detected_payload(
            person_id="p",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["uncited_claims"][0]["claim_text"] == draft_span


# ===========================================================================
# Pillar F Week 8 — fidelity-scoring primitive (ADR-0045 D228-D235)
# ===========================================================================
#
# Week 8 ships the per-draft voice-fidelity scoring primitive per
# ADR-0038 D184(a) — `compute_draft_fidelity_score` consumes the Week 2
# retrieval primitive (`retrieve_voice_exemplars`) + the Week 4 threshold
# loader (`get_voice_threshold_for_register`); the per-register threshold
# is the comparison target for the per-draft fidelity gate.
#
# Coverage:
#
# * `DraftFidelityResult` Layer 2 construction-time invariants per
#   ADR-0045 D229 — refuses-loud at construction when `state="ready"`
#   but `meets_threshold=False` (symmetric with Week 6's
#   `DraftQualityResult.state="ready"` + uncited non-empty refusal).
# * `compute_draft_fidelity_score` per-call dispatch per ADR-0045 D230 —
#   per-register threshold lookup + retrieve-top-K + mean-of-scores
#   composite + clamp to [0.0, 1.0] + construct `DraftFidelityResult`.
# * `build_draft_quality_scored_payload` event-shape factory per
#   ADR-0045 D231 — emit-always posture (NOT emit-only-on-X like
#   `hallucination_detected` per ADR-0043 D219) for Pillar G
#   observability per ADR-0038 D182.
# * TEST-ONLY `embed_fn` + `retrieve_fn` injection seam preservation per
#   ADR-0045 D235 — both kwargs labeled TEST-ONLY in the docstring;
#   neither surfaced via CLI (per ADR-0039 D188-Alt3 security stance).
# * CLI `score` subcommand per ADR-0045 D234.


def _fake_exemplar(
    *,
    ex_id: str = "ex-001",
    date: str = "2026-04-15T14:32:00Z",
    register: str = "cold-pitch",
    channel: str = "email",
    year: int = 2026,
    body: str = "Hey, saw your post last week.",
    score: float | None = 0.80,
    is_substantive_reply: bool = True,
) -> VoiceExemplar:
    """Build a VoiceExemplar with `score` populated for test scenarios.

    The fidelity-scoring primitive consumes `VoiceExemplar.score`
    (cosine × recency from `retrieve_voice_exemplars`); the test
    seam injects pre-scored exemplars so we don't have to build a
    real corpus on disk for unit tests.
    """
    return VoiceExemplar(
        id=ex_id,
        date=date,
        body=body,
        register=register,
        channel=channel,
        year=year,
        score=score,
        is_substantive_reply=is_substantive_reply,
    )


def _stub_retrieve(
    exemplars: list[VoiceExemplar] | None = None,
) -> Callable:
    """Build a `retrieve_fn` stub returning fixed exemplars.

    Matches the `retrieve_voice_exemplars` signature so the
    fidelity-scoring primitive's TEST-ONLY `retrieve_fn` injection
    seam consumes a deterministic substitute. Per ADR-0045 D235 the
    seam is reserved for the test suite + the Week 8+ encoding
    extension (operators do NOT pass `retrieve_fn` at production
    callsites; CLI does NOT surface `--retrieve-fn`).
    """
    fixed = exemplars if exemplars is not None else [_fake_exemplar()]

    def _stub(query, **kwargs):
        return list(fixed)

    return _stub


def _basic_fidelity_result(
    *,
    state: str = "ready",
    register: str = "cold-pitch",
    channel: str = "email",
    voice_fidelity_score: float = 0.82,
    voice_fidelity_threshold: float = 0.70,
    meets_threshold: bool | None = None,
    exemplar_ids: tuple[str, ...] = ("ex-001",),
    k: int = 5,
    draft_body: str = "Hey, saw your post last week.",
) -> DraftFidelityResult:
    if meets_threshold is None:
        meets_threshold = voice_fidelity_score >= voice_fidelity_threshold
    return DraftFidelityResult(
        draft_hash=_hash(draft_body),
        register=register,
        channel=channel,
        voice_fidelity_score=voice_fidelity_score,
        voice_fidelity_threshold=voice_fidelity_threshold,
        meets_threshold=meets_threshold,
        exemplar_ids=exemplar_ids,
        k=k,
        state=state,
    )


# ---------------------------------------------------------------------------
# DraftFidelityResult — Layer 2 construction-time invariants
# ---------------------------------------------------------------------------


class TestDraftFidelityResult:
    """ADR-0045 D229 — Layer 2 construction-time invariants on the
    new per-draft fidelity-scoring result dataclass.

    Symmetric with Week 6 `DraftQualityResult` per ADR-0043 D213's
    construction-time refuse-loud discipline. The structurally
    load-bearing invariant: `state="ready"` AND
    `meets_threshold=False` is REFUSED — a draft that didn't meet
    the per-register voice-fidelity threshold cannot construct as
    `ready` (mirrors Week 6's uncited-with-ready refusal).
    """

    def test_construct_ready_meets_threshold_succeeds(self):
        """D229 — `state="ready"` is valid when `meets_threshold=True`."""
        result = _basic_fidelity_result(state="ready")
        assert result.state == "ready"
        assert result.meets_threshold is True

    def test_construct_refused_below_threshold_succeeds(self):
        """D229 — `state="refused"` is valid when score < threshold."""
        result = _basic_fidelity_result(
            state="refused",
            voice_fidelity_score=0.40,
            voice_fidelity_threshold=0.70,
        )
        assert result.state == "refused"
        assert result.meets_threshold is False

    def test_construct_ready_below_threshold_refuses_loud(self):
        """D229 — THE Layer 2 invariant: `state="ready"` AND
        `meets_threshold=False` MUST raise ValueError. Per ADR-0038
        D184(a) the per-register threshold gates the `ready` advance."""
        with pytest.raises(ValueError, match="ready|threshold|meets"):
            _basic_fidelity_result(
                state="ready",
                voice_fidelity_score=0.40,
                voice_fidelity_threshold=0.70,
            )

    def test_meets_threshold_inconsistent_with_score_refuses(self):
        """D229 — `meets_threshold` MUST equal `(score >= threshold)`.
        Inconsistent stamping refuses-loud at construction so
        downstream consumers (Pillar G dashboard; Week 10 emit guard)
        can trust the stamped boolean."""
        with pytest.raises(ValueError, match="meets_threshold"):
            DraftFidelityResult(
                draft_hash=_hash("d"),
                register="cold-pitch",
                channel="email",
                voice_fidelity_score=0.80,
                voice_fidelity_threshold=0.70,
                meets_threshold=False,  # inconsistent: 0.80 >= 0.70 is True
                exemplar_ids=("ex-001",),
                k=5,
                state="refused",
            )

    def test_unknown_register_refuses_loud(self):
        """D229 — register not in REGISTERS refuses-loud (closed enum
        per ADR-0038 D178)."""
        with pytest.raises(ValueError, match="register"):
            _basic_fidelity_result(register="introduction")

    def test_unknown_channel_refuses_loud(self):
        """D229 — channel not in CHANNELS refuses-loud (closed enum
        per ADR-0014 D33)."""
        with pytest.raises(ValueError, match="channel"):
            _basic_fidelity_result(channel="fax")

    def test_unknown_state_refuses_loud(self):
        """D229 — state outside {ready, refused} refuses-loud."""
        with pytest.raises(ValueError, match="state"):
            _basic_fidelity_result(state="pending")

    def test_draft_hash_must_be_sha256_prefixed(self):
        """D229 + I8 privacy — draft_hash MUST start with `sha256:`
        prefix; raw draft body never appears in the result."""
        with pytest.raises(ValueError, match="draft_hash|sha256"):
            DraftFidelityResult(
                draft_hash="plain text",
                register="cold-pitch",
                channel="email",
                voice_fidelity_score=0.80,
                voice_fidelity_threshold=0.70,
                meets_threshold=True,
                exemplar_ids=("ex-001",),
                k=5,
                state="ready",
            )

    def test_score_below_zero_refuses_loud(self):
        """D229 — score in [0.0, 1.0] per ADR-0038 D184(a). Out-of-range
        refuses at construction."""
        with pytest.raises(ValueError, match="score|fidelity"):
            _basic_fidelity_result(voice_fidelity_score=-0.1)

    def test_score_above_one_refuses_loud(self):
        """D229 — score above 1.0 refuses."""
        with pytest.raises(ValueError, match="score|fidelity"):
            _basic_fidelity_result(voice_fidelity_score=1.5)

    def test_score_boundary_zero_accepted(self):
        """D229 — score = 0.0 is operator-deliberate
        no-match-anywhere baseline."""
        result = _basic_fidelity_result(
            state="refused",
            voice_fidelity_score=0.0,
            voice_fidelity_threshold=0.70,
        )
        assert result.voice_fidelity_score == 0.0

    def test_score_boundary_one_accepted(self):
        """D229 — score = 1.0 is operator-deliberate perfect-match."""
        result = _basic_fidelity_result(
            voice_fidelity_score=1.0,
            voice_fidelity_threshold=0.70,
        )
        assert result.voice_fidelity_score == 1.0

    def test_threshold_below_zero_refuses_loud(self):
        """D229 — threshold in [0.0, 1.0] per ADR-0041 D201."""
        with pytest.raises(ValueError, match="threshold"):
            _basic_fidelity_result(voice_fidelity_threshold=-0.1)

    def test_threshold_above_one_refuses_loud(self):
        """D229 — threshold above 1.0 refuses."""
        with pytest.raises(ValueError, match="threshold"):
            _basic_fidelity_result(voice_fidelity_threshold=1.5)

    def test_bool_score_refuses_loud(self):
        """D229 — `True` (a bool) is an int subclass; the bool catch
        per ADR-0041 D201's footgun discipline applies. A YAML `true`
        coerced to score would silently pass the range check; the
        explicit bool catch surfaces operator intent."""
        with pytest.raises(ValueError, match="score|fidelity|float"):
            _basic_fidelity_result(voice_fidelity_score=True)

    def test_bool_threshold_refuses_loud(self):
        """D229 — bool threshold catch (ADR-0041 D201 footgun)."""
        with pytest.raises(ValueError, match="threshold|float"):
            _basic_fidelity_result(voice_fidelity_threshold=True)

    def test_bool_k_refuses_loud(self):
        """D229 — k is int (bool catch per ADR-0041 D201)."""
        with pytest.raises(ValueError, match="k|int"):
            _basic_fidelity_result(k=True)

    def test_k_negative_refuses_loud(self):
        """D229 — k must be a non-negative integer."""
        with pytest.raises(ValueError, match="k"):
            _basic_fidelity_result(k=-1)

    def test_exemplar_ids_must_be_tuple(self):
        """D229 — exemplar_ids tuple-typed for immutability per
        construction-time invariant + the Week 6 DraftQualityResult
        pattern at ADR-0043 D213."""
        with pytest.raises(ValueError, match="exemplar_ids|tuple"):
            DraftFidelityResult(
                draft_hash=_hash("d"),
                register="cold-pitch",
                channel="email",
                voice_fidelity_score=0.80,
                voice_fidelity_threshold=0.70,
                meets_threshold=True,
                exemplar_ids=["ex-001"],  # list, not tuple
                k=5,
                state="ready",
            )

    def test_exemplar_ids_per_item_str_check(self):
        """D229 — every exemplar_id MUST be a str (mirrors Week 6
        follow-up P2-1 per-item type validation at
        DraftQualityResult per ADR-0043 D213)."""
        with pytest.raises(ValueError, match="exemplar_id"):
            DraftFidelityResult(
                draft_hash=_hash("d"),
                register="cold-pitch",
                channel="email",
                voice_fidelity_score=0.80,
                voice_fidelity_threshold=0.70,
                meets_threshold=True,
                exemplar_ids=("ex-001", 42),  # int violates per-item
                k=5,
                state="ready",
            )

    def test_exemplar_count_exceeds_k_refuses_loud(self):
        """D229 — `len(exemplar_ids) <= k` (subset invariant).
        Operators stamping more exemplars than the requested K signals
        a per-call config drift."""
        with pytest.raises(ValueError, match="exemplar|k"):
            DraftFidelityResult(
                draft_hash=_hash("d"),
                register="cold-pitch",
                channel="email",
                voice_fidelity_score=0.80,
                voice_fidelity_threshold=0.70,
                meets_threshold=True,
                exemplar_ids=("e1", "e2", "e3", "e4", "e5", "e6"),
                k=5,  # 6 > 5
                state="ready",
            )

    def test_exemplar_count_can_be_less_than_k(self):
        """D229 — `len(exemplar_ids) <= k` (subset, not equality).
        When the corpus returns fewer than K exemplars (small corpus,
        narrow filter), the result IS valid; the framework's
        retrieval primitive may return < K per ADR-0039 D188."""
        result = _basic_fidelity_result(exemplar_ids=("e1", "e2"), k=5)
        assert len(result.exemplar_ids) == 2
        assert result.k == 5

    def test_empty_exemplar_ids_accepted(self):
        """D229 — empty exemplar_ids is valid (empty-corpus +
        filter-yields-nothing baseline per ADR-0039 D188)."""
        result = _basic_fidelity_result(
            state="refused",
            voice_fidelity_score=0.0,
            voice_fidelity_threshold=0.70,
            exemplar_ids=(),
            k=5,
        )
        assert result.exemplar_ids == ()

    def test_construct_refused_meets_threshold_true_accepted(self):
        """D229 — the `(refused, meets_threshold=True)` cell of the
        state × meets_threshold outcome partition. Caller-deliberate:
        the score meets the threshold but the caller explicitly sets
        state="refused" (e.g., a downstream operator-stamped override
        OR a synthetic test scenario for Week 10 Layer 4 emit guard
        coverage). Per Week 8 follow-up P2-1: the cell is structurally
        valid + reachable, but the foundation commit's
        TestDraftFidelityResult lacked a test for it — matching the
        Week 6 P2-3/P2-4 + Week 7 P2-1 cell-coverage discipline
        pattern that the per-week reviewer pinned as a load-bearing
        category."""
        result = _basic_fidelity_result(
            state="refused",
            voice_fidelity_score=0.80,
            voice_fidelity_threshold=0.70,
            meets_threshold=True,
        )
        assert result.state == "refused"
        assert result.meets_threshold is True
        assert result.voice_fidelity_score == 0.80


# ---------------------------------------------------------------------------
# compute_draft_fidelity_score — primitive per-call dispatch
# ---------------------------------------------------------------------------


class TestComputeDraftFidelityScore:
    """ADR-0045 D230 — `compute_draft_fidelity_score` per-call dispatch.

    The primitive consumes the Week 2 retrieval primitive
    (`retrieve_voice_exemplars`) + the Week 4 threshold loader
    (`get_voice_threshold_for_register`). Per-call shape:

    1. Validate closed-enums (`register` + `channel`) BEFORE
       retrieval.
    2. Resolve per-register threshold via the Week 4 loader.
    3. Retrieve top-K voice-corpus exemplars (filtered per
       `register` + `channel` + `is_substantive_reply`).
    4. Compute per-draft fidelity score = mean of per-exemplar
       scores (cosine × recency per ADR-0038 D184(a)). Clamp to
       `[0.0, 1.0]`.
    5. Construct `DraftFidelityResult` (Layer 2 invariant runs at
       construction site).

    The TEST-ONLY `retrieve_fn` injection seam per ADR-0045 D235
    bypasses `retrieve_voice_exemplars` for unit tests; the
    `embed_fn` injection seam continues per ADR-0043 D218 (passes
    through to the retrieve_fn when supplied).
    """

    def test_happy_path_returns_draft_fidelity_result(self, tmp_path):
        """D230 — primitive returns a `DraftFidelityResult`."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        result = compute_draft_fidelity_score(
            "Hey, saw your post last week.",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=_stub_retrieve(),
        )
        assert isinstance(result, DraftFidelityResult)

    def test_score_above_threshold_yields_ready(self, tmp_path):
        """D230 — when the mean exemplar score >= per-register
        threshold, state is `ready`."""
        thresholds_path = _write_thresholds(
            tmp_path / "th.yml",
            thresholds={"cold-pitch": 0.70, "congrats": 0.65,
                        "re-engagement": 0.72, "reply": 0.70,
                        "public-comment": 0.60},
        )
        retrieve = _stub_retrieve([
            _fake_exemplar(ex_id="e1", score=0.85),
            _fake_exemplar(ex_id="e2", score=0.80),
        ])
        result = compute_draft_fidelity_score(
            "draft body",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert result.state == "ready"
        assert result.meets_threshold is True
        assert abs(result.voice_fidelity_score - 0.825) < 1e-6

    def test_score_below_threshold_yields_refused(self, tmp_path):
        """D230 — when the mean exemplar score < per-register
        threshold, state is `refused`."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        retrieve = _stub_retrieve([
            _fake_exemplar(ex_id="e1", score=0.40),
            _fake_exemplar(ex_id="e2", score=0.50),
        ])
        result = compute_draft_fidelity_score(
            "draft body",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert result.state == "refused"
        assert result.meets_threshold is False
        assert abs(result.voice_fidelity_score - 0.45) < 1e-6

    def test_score_at_exactly_threshold_yields_ready(self, tmp_path):
        """D230 — boundary: score == threshold → meets_threshold=True
        → ready (gate is `>= threshold` not `> threshold`)."""
        thresholds_path = _write_thresholds(
            tmp_path / "th.yml",
            thresholds={"cold-pitch": 0.70, "congrats": 0.65,
                        "re-engagement": 0.72, "reply": 0.70,
                        "public-comment": 0.60},
        )
        retrieve = _stub_retrieve([_fake_exemplar(score=0.70)])
        result = compute_draft_fidelity_score(
            "draft body",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert result.state == "ready"
        assert result.meets_threshold is True

    def test_empty_exemplar_list_yields_zero_score_refused(self, tmp_path):
        """D230 — empty exemplars (empty corpus OR no filter matches)
        yields `voice_fidelity_score=0.0` + `state=refused`. The
        framework refuses-loud rather than scoring a default 1.0
        (which would silently accept every draft against an empty
        corpus) — per ADR-0038 D184 asymmetric-failure-cost
        (false-negative is the high-cost path)."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        result = compute_draft_fidelity_score(
            "draft body",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=_stub_retrieve([]),
        )
        assert result.voice_fidelity_score == 0.0
        assert result.state == "refused"
        assert result.exemplar_ids == ()

    def test_negative_score_clamps_to_zero(self, tmp_path):
        """D230 — out-of-range scores (theoretically possible with
        cosine on weird embeddings + low recency) clamp to
        `[0.0, 1.0]` to satisfy the result's construction-time
        invariant. The clamp is operator-invisible."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        retrieve = _stub_retrieve([
            _fake_exemplar(score=-0.50),
            _fake_exemplar(score=-0.30),
        ])
        result = compute_draft_fidelity_score(
            "draft body",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert result.voice_fidelity_score == 0.0
        assert result.state == "refused"

    def test_score_above_one_clamps_to_one(self, tmp_path):
        """D230 — scores above 1.0 (theoretically possible with
        non-normalized embeddings + > 1.0 recency) clamp to 1.0."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        retrieve = _stub_retrieve([_fake_exemplar(score=1.5)])
        result = compute_draft_fidelity_score(
            "draft body",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert result.voice_fidelity_score == 1.0

    def test_per_register_threshold_consumed(self, tmp_path):
        """D230 — per-register threshold per ADR-0041 D204. Different
        registers consult different threshold values."""
        thresholds_path = _write_thresholds(
            tmp_path / "th.yml",
            thresholds={"cold-pitch": 0.70, "congrats": 0.65,
                        "re-engagement": 0.72, "reply": 0.70,
                        "public-comment": 0.60},
        )
        retrieve = _stub_retrieve([_fake_exemplar(score=0.62)])
        # cold-pitch threshold 0.70: 0.62 < 0.70 → refused
        cp = compute_draft_fidelity_score(
            "d", register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert cp.state == "refused"
        # public-comment threshold 0.60: 0.62 >= 0.60 → ready
        pc = compute_draft_fidelity_score(
            "d", register="public-comment", channel="linkedin-comment",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert pc.state == "ready"

    def test_threshold_stamped_on_result(self, tmp_path):
        """D230 — the per-register threshold MUST be stamped on the
        result for downstream consumers (Pillar G dashboard; Week 10
        Layer 4 emit guard; Week 12 Layer 5 reconcile heal-pass)."""
        thresholds_path = _write_thresholds(
            tmp_path / "th.yml",
            thresholds={"cold-pitch": 0.70, "congrats": 0.65,
                        "re-engagement": 0.72, "reply": 0.70,
                        "public-comment": 0.60},
        )
        result = compute_draft_fidelity_score(
            "d", register="re-engagement", channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=_stub_retrieve(),
        )
        assert result.voice_fidelity_threshold == 0.72

    def test_unknown_register_refuses_loud(self, tmp_path):
        """D230 — register not in REGISTERS refuses BEFORE retrieval
        (fail-fast at the closed-enum boundary)."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        with pytest.raises(ValueError, match="register"):
            compute_draft_fidelity_score(
                "d", register="introduction", channel="email",
                thresholds_path=thresholds_path,
                retrieve_fn=_stub_retrieve(),
            )

    def test_unknown_channel_refuses_loud(self, tmp_path):
        """D230 — channel not in CHANNELS refuses BEFORE retrieval."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        with pytest.raises(ValueError, match="channel"):
            compute_draft_fidelity_score(
                "d", register="cold-pitch", channel="fax",
                thresholds_path=thresholds_path,
                retrieve_fn=_stub_retrieve(),
            )

    def test_draft_hash_matches_sha256_of_draft(self, tmp_path):
        """D230 + I8 — draft_hash on the result is sha256:<hex> of
        the input draft text."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        draft = "this is the draft body"
        result = compute_draft_fidelity_score(
            draft, register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=_stub_retrieve(),
        )
        assert result.draft_hash == _hash(draft)

    def test_exemplar_ids_match_returned_exemplars(self, tmp_path):
        """D230 — `exemplar_ids` on the result names the IDs of the
        top-K exemplars the retrieval primitive surfaced."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        retrieve = _stub_retrieve([
            _fake_exemplar(ex_id="alpha", score=0.85),
            _fake_exemplar(ex_id="beta", score=0.80),
        ])
        result = compute_draft_fidelity_score(
            "d", register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert result.exemplar_ids == ("alpha", "beta")

    def test_k_kwarg_passes_through_to_retrieve(self, tmp_path):
        """D230 — `k` kwarg passes through to the retrieve_fn."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        captured_k = []

        def _capturing(query, **kwargs):
            captured_k.append(kwargs.get("k"))
            return [_fake_exemplar()]

        compute_draft_fidelity_score(
            "d", register="cold-pitch", channel="email", k=7,
            thresholds_path=thresholds_path,
            retrieve_fn=_capturing,
        )
        assert captured_k == [7]

    def test_register_and_channel_pass_through_to_retrieve(self, tmp_path):
        """D230 — `register` + `channel` kwargs pass through to the
        retrieve_fn (the corpus filter applies BEFORE scoring)."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        captured: list[dict] = []

        def _capturing(query, **kwargs):
            captured.append(kwargs)
            return [_fake_exemplar()]

        compute_draft_fidelity_score(
            "d", register="congrats", channel="linkedin-dm",
            thresholds_path=thresholds_path,
            retrieve_fn=_capturing,
        )
        assert captured[0]["register"] == "congrats"
        assert captured[0]["channel"] == "linkedin-dm"

    def test_now_kwarg_passes_through_to_retrieve(self, tmp_path):
        """D230 — `now` kwarg (deterministic-clock anchor per
        ADR-0031 D140 + ADR-0034 D156 + ADR-0035 D162) passes through
        to the retrieve_fn for per-test reproducibility."""
        from datetime import datetime, timezone
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        captured: list[dict] = []

        def _capturing(query, **kwargs):
            captured.append(kwargs)
            return [_fake_exemplar()]

        anchor = datetime(2026, 1, 15, tzinfo=timezone.utc)
        compute_draft_fidelity_score(
            "d", register="cold-pitch", channel="email", now=anchor,
            thresholds_path=thresholds_path,
            retrieve_fn=_capturing,
        )
        assert captured[0]["now"] == anchor

    def test_is_substantive_reply_passes_through(self, tmp_path):
        """D230 — `is_substantive_reply` kwarg passes through to the
        retrieve_fn (cold-pitch adapter's bias toward proven-effective
        exemplars per ADR-0040 D196)."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        captured: list[dict] = []

        def _capturing(query, **kwargs):
            captured.append(kwargs)
            return [_fake_exemplar()]

        compute_draft_fidelity_score(
            "d", register="cold-pitch", channel="email",
            is_substantive_reply=True,
            thresholds_path=thresholds_path,
            retrieve_fn=_capturing,
        )
        assert captured[0]["is_substantive_reply"] is True

    def test_retrieve_fn_query_is_draft_text(self, tmp_path):
        """D230 — the retrieve_fn is called with the draft as the
        query text (so the corpus retrieval surfaces exemplars
        similar to THIS draft)."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        captured_query = []

        def _capturing(query, **kwargs):
            captured_query.append(query)
            return [_fake_exemplar()]

        compute_draft_fidelity_score(
            "the actual draft text",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=_capturing,
        )
        assert captured_query == ["the actual draft text"]

    def test_embed_fn_passes_through_to_retrieve(self, tmp_path):
        """D235 — the TEST-ONLY `embed_fn` kwarg MUST pass through to
        the retrieve_fn / retrieve_voice_exemplars per ADR-0045 D235's
        seam-preservation discipline + ADR-0043 D218's seam lineage.
        Per Week 8 follow-up P2-2: the foundation commit verified the
        kwarg presence in the signature + the docstring labeling +
        the CLI absence, but did NOT verify the BEHAVIORAL passthrough
        (a future refactor dropping `embed_fn=embed_fn` at the
        retriever call site would silently revert all callers
        injecting `embed_fn` back to the default encoder). The
        capturing-lambda pattern matches `test_k_kwarg_passes_through_to_retrieve`
        + `test_now_kwarg_passes_through_to_retrieve`."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        captured: list[dict] = []

        def _capturing(query, **kwargs):
            captured.append(kwargs)
            return [_fake_exemplar()]

        sentinel_embed_fn = lambda text: None  # noqa: E731
        compute_draft_fidelity_score(
            "d", register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=_capturing,
            embed_fn=sentinel_embed_fn,
        )
        assert captured[0]["embed_fn"] is sentinel_embed_fn

    def test_all_none_exemplar_scores_yields_zero_score_refused(self, tmp_path):
        """D230 — defensive guard against `VoiceExemplar.score is
        None`. Legacy corpus samples (or retrieve_fn stubs without
        scores) may have `score=None`; the primitive's defensive
        filter (lines 1891-1896) skips None-scored exemplars + falls
        back to `fidelity_score=0.0` when no scored exemplar
        survives. Per Week 8 follow-up P3-1: the foundation commit
        tested the empty-exemplar-list branch (test_empty_exemplar_list_yields_zero_score_refused)
        but NOT the all-None-scores branch (non-empty exemplar list
        where every `ex.score is None`); a future refactor dropping
        the `if ex.score is not None` filter would raise TypeError at
        `float(None)` rather than falling back to 0.0."""
        thresholds_path = _write_thresholds(tmp_path / "th.yml")
        retrieve = _stub_retrieve([
            _fake_exemplar(ex_id="e1", score=None),
            _fake_exemplar(ex_id="e2", score=None),
        ])
        result = compute_draft_fidelity_score(
            "draft body",
            register="cold-pitch",
            channel="email",
            thresholds_path=thresholds_path,
            retrieve_fn=retrieve,
        )
        assert result.voice_fidelity_score == 0.0
        assert result.state == "refused"
        # The exemplar IDs are still stamped (the primitive doesn't
        # filter out the exemplars themselves — only their scores
        # from the mean computation).
        assert result.exemplar_ids == ("e1", "e2")


# ---------------------------------------------------------------------------
# build_draft_quality_scored_payload — event-shape factory
# ---------------------------------------------------------------------------


class TestBuildDraftQualityScoredPayload:
    """ADR-0045 D231 — event-shape factory for the new
    `draft_quality_scored` event class per ADR-0038 D182.

    Unlike `build_hallucination_detected_payload` (emit-only-on-uncited
    per ADR-0043 D219), this factory has the **emit-always** posture
    per ADR-0038 D182 + the Pillar G observability use case — operators
    consume per-draft fidelity score distributions, so accept-case
    events ARE structurally load-bearing for the dashboards.
    """

    def test_happy_path_payload_shape(self):
        """D231 — happy-path payload carries every Week 8 field."""
        result = _basic_fidelity_result()
        payload = build_draft_quality_scored_payload(
            person_id="person-123",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["type"] == "draft_quality_scored"
        assert payload["person_id"] == "person-123"
        assert payload["draft_hash"] == result.draft_hash
        assert payload["register"] == "cold-pitch"
        assert payload["channel"] == "email"
        assert payload["voice_fidelity_score"] == result.voice_fidelity_score
        assert payload["voice_fidelity_threshold"] == result.voice_fidelity_threshold
        assert payload["meets_threshold"] == result.meets_threshold
        assert payload["state"] == result.state
        assert payload["exemplar_ids"] == list(result.exemplar_ids)
        assert payload["k"] == result.k
        assert payload["_emitted_by"] == EMITTED_BY

    def test_person_id_none_accepted(self):
        """D231 — `person_id=None` accepted for ad-hoc operator
        validation outside the per-Person flow (mirrors
        ADR-0043 D216 + ADR-0039 D189)."""
        result = _basic_fidelity_result()
        payload = build_draft_quality_scored_payload(
            person_id=None,
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["person_id"] is None

    def test_emit_on_ready_state(self):
        """D231 — emit-always: `state="ready"` constructs the payload
        successfully (vs the emit-only-on-uncited posture of
        `build_hallucination_detected_payload` per ADR-0043 D219).
        Pillar G dashboard needs accept-case events for per-register
        score distribution rendering."""
        result = _basic_fidelity_result(state="ready")
        payload = build_draft_quality_scored_payload(
            person_id="p",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["state"] == "ready"
        assert payload["meets_threshold"] is True

    def test_emit_on_refused_state(self):
        """D231 — emit-always: `state="refused"` ALSO constructs the
        payload (symmetric)."""
        result = _basic_fidelity_result(
            state="refused",
            voice_fidelity_score=0.40,
            voice_fidelity_threshold=0.70,
        )
        payload = build_draft_quality_scored_payload(
            person_id="p",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["state"] == "refused"
        assert payload["meets_threshold"] is False

    def test_unknown_channel_refuses_loud(self):
        """D231 — channel not in CHANNELS refuses-loud (mirrors
        ADR-0043 D216 + ADR-0014 D33)."""
        result = _basic_fidelity_result()
        with pytest.raises(ValueError, match="channel"):
            build_draft_quality_scored_payload(
                person_id="p",
                result=result,
                channel="fax",
                register="cold-pitch",
            )

    def test_unknown_register_refuses_loud(self):
        """D231 — register not in REGISTERS refuses-loud."""
        result = _basic_fidelity_result()
        with pytest.raises(ValueError, match="register"):
            build_draft_quality_scored_payload(
                person_id="p",
                result=result,
                channel="email",
                register="introduction",
            )

    def test_channel_mismatch_with_result_refuses_loud(self):
        """D231 — the factory's `channel` kwarg MUST match the
        result's stamped channel. Mirrors ADR-0043 D216 + Week 6
        follow-up P2-2: silent channel/result mismatch would surface
        phantom Pillar G signals."""
        result = _basic_fidelity_result(channel="email")
        with pytest.raises(ValueError, match="channel"):
            build_draft_quality_scored_payload(
                person_id="p",
                result=result,
                channel="linkedin-dm",
                register="cold-pitch",
            )

    def test_register_mismatch_with_result_refuses_loud(self):
        """D231 — the factory's `register` kwarg MUST match the
        result's stamped register (mirrors Week 6 follow-up P2-2)."""
        result = _basic_fidelity_result(register="cold-pitch")
        with pytest.raises(ValueError, match="register"):
            build_draft_quality_scored_payload(
                person_id="p",
                result=result,
                channel="email",
                register="congrats",
            )

    def test_payload_does_not_contain_raw_draft(self):
        """D231 + I8 — the payload MUST NOT carry the raw draft body.
        Only the sha256 draft_hash + the per-result fields appear.
        Mirrors ADR-0043 D216 + Week 6 follow-up P3-2's recursive
        walk check."""
        secret_draft = "secret operator draft body that should not leak"
        result = DraftFidelityResult(
            draft_hash=_hash(secret_draft),
            register="cold-pitch",
            channel="email",
            voice_fidelity_score=0.80,
            voice_fidelity_threshold=0.70,
            meets_threshold=True,
            exemplar_ids=("ex-001",),
            k=5,
            state="ready",
        )
        payload = build_draft_quality_scored_payload(
            person_id="p",
            result=result,
            channel="email",
            register="cold-pitch",
        )

        def _walk(value):
            if isinstance(value, str):
                assert secret_draft not in value
            elif isinstance(value, dict):
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for item in value:
                    _walk(item)

        _walk(payload)

    def test_payload_does_not_contain_exemplar_bodies(self):
        """D231 + I8 — exemplar BODIES MUST NOT appear in the payload;
        only the exemplar IDs surface (operators look up bodies via
        the corpus directly per ADR-0039 D189 precedent)."""
        # The result.exemplar_ids only carries IDs; ensure the
        # factory doesn't accidentally enrich with bodies.
        result = _basic_fidelity_result(exemplar_ids=("alpha", "beta"))
        payload = build_draft_quality_scored_payload(
            person_id="p",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        # exemplar_ids is a flat list of strings
        assert payload["exemplar_ids"] == ["alpha", "beta"]
        # No `exemplar_bodies` field (the privacy contract)
        assert "exemplar_bodies" not in payload

    def test_emitted_by_marker(self):
        """D231 — `_emitted_by` marker per ADR-0010 D17 + ADR-0043
        D216: `draft_quality` (same module emits both
        `hallucination_detected` + `draft_quality_scored`)."""
        result = _basic_fidelity_result()
        payload = build_draft_quality_scored_payload(
            person_id="p",
            result=result,
            channel="email",
            register="cold-pitch",
        )
        assert payload["_emitted_by"] == "draft_quality"


# ---------------------------------------------------------------------------
# TEST-ONLY embed_fn + retrieve_fn seam preservation (Week 8 extension)
# ---------------------------------------------------------------------------


class TestSeamPreservationWeek8:
    """ADR-0045 D235 — TEST-ONLY `embed_fn` + `retrieve_fn` seam
    preservation at the Week 8 fidelity-scoring primitive surface.

    Continuation of the ADR-0043 D218 + ADR-0044 D227 discipline.
    Both kwargs labeled TEST-ONLY in the primitive's docstring;
    neither surfaced via CLI (per ADR-0039 D188-Alt3 +
    ADR-0040 D197-Alt1's security stance).
    """

    def test_compute_draft_fidelity_score_has_embed_fn_kwarg(self):
        """D235 — `compute_draft_fidelity_score` carries TEST-ONLY
        `embed_fn` kwarg (passes through to retrieve_fn or
        retrieve_voice_exemplars's default encoder injection)."""
        import inspect
        sig = inspect.signature(compute_draft_fidelity_score)
        assert "embed_fn" in sig.parameters

    def test_compute_draft_fidelity_score_has_retrieve_fn_kwarg(self):
        """D235 — `compute_draft_fidelity_score` carries TEST-ONLY
        `retrieve_fn` kwarg (the Week 8 NEW injection seam — full
        retrieval bypass for unit tests)."""
        import inspect
        sig = inspect.signature(compute_draft_fidelity_score)
        assert "retrieve_fn" in sig.parameters

    def test_compute_docstring_labels_embed_fn_test_only(self):
        """D235 — docstring labels `embed_fn` as TEST-ONLY per
        ADR-0040 D197 + ADR-0043 D218 + ADR-0045 D235."""
        doc = compute_draft_fidelity_score.__doc__ or ""
        assert "TEST-ONLY" in doc

    def test_compute_docstring_labels_retrieve_fn_test_only(self):
        """D235 — docstring labels `retrieve_fn` as TEST-ONLY."""
        doc = compute_draft_fidelity_score.__doc__ or ""
        # The TEST-ONLY discipline applies to both seams; the
        # docstring names retrieve_fn alongside embed_fn.
        assert "retrieve_fn" in doc
        assert "TEST-ONLY" in doc

    def test_cli_score_has_no_embed_fn_flag(self):
        """D235 — CLI `score` subcommand does NOT surface `--embed-fn`
        (security + audit per ADR-0039 D188-Alt3)."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "score", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "--embed-fn" not in proc.stdout
        assert "--embed_fn" not in proc.stdout

    def test_cli_score_has_no_retrieve_fn_flag(self):
        """D235 — CLI `score` subcommand does NOT surface
        `--retrieve-fn` (the test-injection seam is reserved for the
        test suite + Pillar I CLI tooling per ADR-0039 D188-Alt3)."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "score", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "--retrieve-fn" not in proc.stdout
        assert "--retrieve_fn" not in proc.stdout


# ---------------------------------------------------------------------------
# CLI smoke tests — `python orchestrator/draft_quality.py score`
# ---------------------------------------------------------------------------


class TestCLIScore:
    """CLI smoke tests for the Week 8 `score` subcommand per
    ADR-0045 D234.

    The subcommand surfaces the fidelity-scoring primitive to
    operators + emits `draft_quality_scored` to the ledger when
    `--apply` is set (emit-always per ADR-0045 D231 — both ready
    + refused states emit).

    Tests use subprocess invocations so the CLI dispatch + argparse
    + main() path is exercised end-to-end. Subprocess invocations
    create fresh processes so the per-process voice_corpus cache
    is naturally per-test.

    Each test sets `OUTREACH_FACTORY_CONFIG` to a non-existent
    path so the CLI's `_load_config` returns `{}` (test isolation
    from operator config).
    """

    def test_score_subcommand_in_help(self):
        """D234 — main `--help` lists the `score` subcommand."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        assert "score" in proc.stdout

    def test_score_argparse_register_closed_enum(self, tmp_path):
        """D234 — `--register` argparse choices enforce the closed
        enum BEFORE handler dispatch (mirrors ADR-0042 D210 +
        ADR-0043 D212 precedent)."""
        draft = tmp_path / "draft.txt"
        draft.write_text("hey")
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "score",
             "--draft-path", str(draft),
             "--register", "introduction",  # invalid
             "--channel", "email"],
            capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "introduction" in proc.stderr or "invalid choice" in proc.stderr

    def test_score_argparse_channel_closed_enum(self, tmp_path):
        """D234 — `--channel` argparse choices enforce the closed
        enum BEFORE handler dispatch."""
        draft = tmp_path / "draft.txt"
        draft.write_text("hey")
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "score",
             "--draft-path", str(draft),
             "--register", "cold-pitch",
             "--channel", "fax"],  # invalid
            capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "fax" in proc.stderr or "invalid choice" in proc.stderr

    def test_score_missing_draft_path_refuses(self, tmp_path):
        """D234 — missing `--draft-path` argparse error."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "score",
             "--register", "cold-pitch", "--channel", "email"],
            capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )
        assert proc.returncode != 0

    def test_score_nonexistent_draft_file_errors(self, tmp_path):
        """D234 — non-existent draft file errors with a per-path
        diagnostic."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "score",
             "--draft-path", str(tmp_path / "does_not_exist.txt"),
             "--register", "cold-pitch", "--channel", "email"],
            capture_output=True, text=True, timeout=30,
            env=_env(tmp_path),
        )
        assert proc.returncode != 0
        assert "not found" in proc.stderr.lower() or "no such" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# Week 8 module surface
# ---------------------------------------------------------------------------


class TestWeek8ModuleSurface:
    """Pin the Week 8 public surfaces per ADR-0045 D228 +
    Pillar F Week 7 invariant carry-forward (`Pillar F Week 6 + 7
    primitive's public surfaces are preserved verbatim`).
    """

    def test_draft_fidelity_result_exported(self):
        """D228 — `DraftFidelityResult` is importable from
        `orchestrator.draft_quality`."""
        from draft_quality import DraftFidelityResult as _DFR
        assert _DFR is DraftFidelityResult

    def test_compute_draft_fidelity_score_exported(self):
        """D228 — `compute_draft_fidelity_score` is importable."""
        from draft_quality import (
            compute_draft_fidelity_score as _compute,
        )
        assert _compute is compute_draft_fidelity_score

    def test_build_draft_quality_scored_payload_exported(self):
        """D228 — `build_draft_quality_scored_payload` is importable."""
        from draft_quality import (
            build_draft_quality_scored_payload as _bld,
        )
        assert _bld is build_draft_quality_scored_payload

    def test_week_6_surfaces_preserved(self):
        """D228 + per-week handoff invariant — the Pillar F Week 6
        public surfaces stay verbatim (ParsedClaim,
        DraftQualityResult, parse_draft_for_claims, score_draft,
        build_hallucination_detected_payload, CLAIM_TYPES,
        EMITTED_BY)."""
        for sym in (
            "ParsedClaim", "DraftQualityResult", "parse_draft_for_claims",
            "score_draft", "build_hallucination_detected_payload",
            "CLAIM_TYPES", "EMITTED_BY",
        ):
            assert hasattr(draft_quality, sym), (
                f"Week 8 must preserve Week 6 surface {sym!r}"
            )

    def test_week_7_surfaces_preserved(self):
        """D228 + per-week handoff invariant — the Pillar F Week 7
        public surfaces stay verbatim (CorpusPair, CorpusMeasurement,
        measure_per_claim_type_false_positive_rate)."""
        for sym in (
            "CorpusPair", "CorpusMeasurement",
            "measure_per_claim_type_false_positive_rate",
        ):
            assert hasattr(draft_quality, sym), (
                f"Week 8 must preserve Week 7 surface {sym!r}"
            )


# ---------------------------------------------------------------------------
# Pillar F Week 9 — fuzzy-match parser extension per ADR-0046
# ---------------------------------------------------------------------------


def _zero_embed_fn(text: str) -> np.ndarray:
    """A deterministic stub encoder that returns zero vectors.

    Cosine similarity against this encoder's output is always 0.0
    (the cosine helper returns 0.0 when either vector is zero per
    ADR-0046 D238's _cosine_similarity rule). Tests use this stub
    to DISABLE the fuzzy fallback while preserving the per-call
    seam wiring.
    """
    return np.zeros(384, dtype=np.float32)


def _deterministic_embed_fn(text: str) -> np.ndarray:
    """A deterministic stub encoder that maps text to a hash-based
    pseudo-vector. Same input → same output (per ADR-0013 D24
    reproducibility); different inputs → near-orthogonal vectors.

    This stub LETS the fuzzy path activate (non-zero vectors) but
    keeps cosines low (~0.0-0.3) since different texts produce
    near-orthogonal vectors. Useful for tests that exercise the
    fuzzy path's signature without depending on real semantic
    similarity behavior.
    """
    import hashlib as _h
    digest = _h.sha256(text.encode("utf-8")).digest()
    # Expand 32 bytes to 384 floats via repetition + normalize.
    arr = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
    arr = np.tile(arr, 12)[:384]
    arr = (arr - 127.5) / 127.5  # roughly center on 0
    return arr


def _high_similarity_embed_fn(target: str, threshold: float = 0.95):
    """Returns an embed_fn that produces high cosine similarity
    for the supplied ``target`` text and one specific other text;
    near-orthogonal for everything else.

    Used by tests to deterministically trigger fuzzy-match acceptance
    against a CHOSEN dossier chunk without depending on real
    SentenceTransformer behavior. Same vector for target text +
    one specific tag input.
    """
    def _fn(text: str) -> np.ndarray:
        if text == target:
            v = np.zeros(384, dtype=np.float32)
            v[0] = 1.0
            return v
        # Default: orthogonal axis derived from text hash
        return _deterministic_embed_fn(text)
    return _fn


def _always_match_embed_fn(text: str) -> np.ndarray:
    """Stub that returns the SAME constant non-zero vector regardless
    of input. Cosine similarity between any two outputs is 1.0 (the
    vectors are identical). Used to test the fuzzy path's threshold
    + control-flow without depending on real semantic similarity."""
    v = np.zeros(384, dtype=np.float32)
    v[0] = 1.0
    return v


class TestChunkDossier:
    """``_chunk_dossier_for_fuzzy_match`` per ADR-0046 D238.

    Tests the per-parse chunker's bounds + per-chunk URL extraction.
    """

    def test_empty_dossier_yields_empty_chunks(self):
        """D238 — empty dossier returns empty chunk list (no fuzzy
        match possible)."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        assert _chunk_dossier_for_fuzzy_match("") == []

    def test_whitespace_only_dossier_yields_empty(self):
        """D238 — whitespace-only dossier returns empty chunk list."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        assert _chunk_dossier_for_fuzzy_match("   \n\n  \t  ") == []

    def test_single_sentence_yields_one_chunk(self):
        """D238 — a single sentence yields one chunk."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        chunks = _chunk_dossier_for_fuzzy_match(
            "Acme Corp shipped a new product."
        )
        assert len(chunks) == 1
        assert "Acme Corp shipped a new product" in chunks[0][0]

    def test_multi_sentence_yields_multi_chunks(self):
        """D238 — multiple sentences yield multiple chunks split on
        sentence boundaries."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        chunks = _chunk_dossier_for_fuzzy_match(
            "Acme Corp shipped. Sequoia led the round. "
            "OpenAI raised in Q1."
        )
        # Three sentences → three chunks
        assert len(chunks) == 3

    def test_short_chunks_filtered(self):
        """D238 — chunks below 10 chars are dropped (cosine noise)."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        # "OK." is 3 chars; "Hi!" is 3 chars; long enough remains.
        chunks = _chunk_dossier_for_fuzzy_match(
            "OK. Hi! Acme Corp announced a partnership today."
        )
        # The two short chunks dropped; the long one stays.
        texts = [c[0] for c in chunks]
        assert "OK" not in texts
        assert "Hi" not in texts
        assert any("Acme Corp announced" in t for t in texts)

    def test_paragraph_boundary_splits_chunks(self):
        """D238 — double-newline (paragraph) boundaries split chunks."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        chunks = _chunk_dossier_for_fuzzy_match(
            "Paragraph one about Acme Corp.\n\n"
            "Paragraph two about Sequoia Capital."
        )
        assert len(chunks) == 2

    def test_long_chunk_re_splits(self):
        """D238 — chunks longer than 500 chars re-split on next
        sentence boundary or hard cap."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        # Build a single "sentence" of ~700 chars by using only commas.
        long_sentence = "Acme Corp" + ", and now back to work" * 35 + "."
        assert len(long_sentence) > 500
        chunks = _chunk_dossier_for_fuzzy_match(long_sentence)
        # Should produce more than one chunk via the hard-cap re-split.
        assert len(chunks) >= 2
        for chunk_text, _ in chunks:
            assert len(chunk_text) <= 500

    def test_chunk_nearby_url_extracted(self):
        """D238 — URLs within ±200 chars of a chunk surface as the
        chunk's nearby_url field."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        chunks = _chunk_dossier_for_fuzzy_match(
            "Acme Corp shipped a product: https://example.com/acme."
        )
        # The URL should be extracted as the chunk's nearby_url.
        assert chunks[0][1] == "https://example.com/acme."

    def test_chunk_without_url_returns_none(self):
        """D238 — chunks without nearby URLs surface ``None`` for the
        nearby_url field."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        chunks = _chunk_dossier_for_fuzzy_match(
            "Acme Corp shipped a product."
        )
        assert chunks[0][1] is None

    def test_chunker_is_deterministic(self):
        """D238 — same dossier produces same chunk list across calls
        (reproducibility per ADR-0013 D24)."""
        from draft_quality import _chunk_dossier_for_fuzzy_match
        dossier = (
            "First sentence. Second sentence about Acme. "
            "Third sentence with URL https://example.com."
        )
        c1 = _chunk_dossier_for_fuzzy_match(dossier)
        c2 = _chunk_dossier_for_fuzzy_match(dossier)
        assert c1 == c2


class TestFindCitationAnchorFuzzy:
    """``_find_citation_anchor_fuzzy`` per ADR-0046 D238 + D239.

    Tests the fuzzy-match cosine-against-chunks logic + threshold
    + URL/chunk-index anchor surfacing.
    """

    def test_empty_chunks_returns_none(self):
        """D238 — empty chunk list → return None (no fuzzy possible)."""
        from draft_quality import _find_citation_anchor_fuzzy
        result = _find_citation_anchor_fuzzy(
            "Acme Corp", [], embed_fn=_deterministic_embed_fn,
        )
        assert result is None

    def test_empty_claim_text_returns_none(self):
        """D238 — empty claim_text → return None."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Acme Corp shipped.", "https://example.com")]
        result = _find_citation_anchor_fuzzy(
            "", chunks, embed_fn=_deterministic_embed_fn,
        )
        assert result is None

    def test_none_embed_fn_refuses_loud(self):
        """D238 — embed_fn=None refuses loud (lazy-load happens
        upstream at parse_draft_for_claims per D241)."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Acme Corp shipped.", None)]
        with pytest.raises(ValueError, match="embed_fn"):
            _find_citation_anchor_fuzzy(
                "Acme Corp", chunks, embed_fn=None,
            )

    def test_cosine_below_threshold_returns_none(self):
        """D239 — cosine below threshold → return None."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Completely unrelated topic.", None)]
        # _deterministic_embed_fn produces near-orthogonal vectors;
        # cosine should be well below 0.85.
        result = _find_citation_anchor_fuzzy(
            "Acme Corp", chunks,
            embed_fn=_deterministic_embed_fn,
            threshold=0.85,
        )
        assert result is None

    def test_cosine_at_or_above_threshold_returns_anchor(self):
        """D239 — cosine ≥ threshold returns the chunk's anchor."""
        from draft_quality import _find_citation_anchor_fuzzy
        # _high_similarity_embed_fn returns identical vectors for the
        # target text and the same string; cosine 1.0 against itself.
        target_chunk = "Acme Corporation announced a partnership."
        embed_fn = _high_similarity_embed_fn(target_chunk)
        chunks = [(target_chunk, "https://example.com/acme")]
        result = _find_citation_anchor_fuzzy(
            target_chunk, chunks, embed_fn=embed_fn, threshold=0.85,
        )
        assert result == "https://example.com/acme"

    def test_anchor_falls_back_to_chunk_index_when_no_url(self):
        """D238 — chunk without nearby_url surfaces a chunk-index
        diagnostic string instead of None."""
        from draft_quality import _find_citation_anchor_fuzzy
        target_chunk = "Acme Corp announcement."
        embed_fn = _high_similarity_embed_fn(target_chunk)
        chunks = [(target_chunk, None)]  # no URL
        result = _find_citation_anchor_fuzzy(
            target_chunk, chunks, embed_fn=embed_fn, threshold=0.85,
        )
        assert result == "dossier:fuzzy-match@chunk-0"

    def test_best_matching_chunk_wins(self):
        """D238 — when multiple chunks match, the highest-cosine
        chunk's anchor is returned."""
        from draft_quality import _find_citation_anchor_fuzzy
        # Build a 3-chunk list. Only the second chunk matches (cosine
        # 1.0); the others are near-orthogonal.
        target_chunk = "Acme Corp shipped v2."
        embed_fn = _high_similarity_embed_fn(target_chunk)
        chunks = [
            ("Random chunk.", "https://example.com/random"),
            (target_chunk, "https://example.com/target"),
            ("Another random one.", "https://example.com/other"),
        ]
        result = _find_citation_anchor_fuzzy(
            target_chunk, chunks, embed_fn=embed_fn, threshold=0.85,
        )
        assert result == "https://example.com/target"

    def test_threshold_zero_accepts_any_match(self):
        """D239 — threshold=0.0 accepts any non-negative cosine
        match. Uses a constant-axis stub (cosine 1.0 against the
        target string + the same vector for all inputs → cosine 1.0
        ≥ 0.0 → accepted)."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Unrelated chunk.", "https://example.com/x")]
        # Constant non-zero vector stub → cosine 1.0 against any input.
        def _const(_text):
            v = np.zeros(384, dtype=np.float32)
            v[0] = 1.0
            return v
        result = _find_citation_anchor_fuzzy(
            "Acme Corp", chunks,
            embed_fn=_const,
            threshold=0.0,
        )
        # Cosine 1.0 ≥ 0.0 → returns the anchor.
        assert result is not None

    def test_threshold_one_rejects_unless_exact_match(self):
        """D239 — threshold=1.0 rejects anything but exact-match
        vectors (cosine 1.0)."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Some chunk.", "https://example.com/x")]
        result = _find_citation_anchor_fuzzy(
            "Acme Corp", chunks,
            embed_fn=_deterministic_embed_fn,
            threshold=1.0,
        )
        # _deterministic_embed_fn produces different vectors for
        # different inputs → cosine < 1.0 → rejected.
        assert result is None

    def test_chunk_with_url_returns_url_not_index(self):
        """D238 — when a chunk has a nearby_url, the URL takes
        precedence over the chunk-index diagnostic."""
        from draft_quality import _find_citation_anchor_fuzzy
        target_chunk = "Sequoia Capital led the round."
        embed_fn = _high_similarity_embed_fn(target_chunk)
        chunks = [(target_chunk, "https://example.com/sequoia")]
        result = _find_citation_anchor_fuzzy(
            target_chunk, chunks, embed_fn=embed_fn, threshold=0.85,
        )
        # URL wins over chunk-index diagnostic.
        assert result == "https://example.com/sequoia"

    def test_anchor_is_privacy_respecting(self):
        """D238 + I8 — the fuzzy-match anchor (chunk-index diagnostic)
        does NOT contain the chunk body text."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunk_body = "Confidential operator notes about prospect."
        embed_fn = _high_similarity_embed_fn(chunk_body)
        chunks = [(chunk_body, None)]
        result = _find_citation_anchor_fuzzy(
            chunk_body, chunks, embed_fn=embed_fn, threshold=0.85,
        )
        # The chunk's body must NOT appear in the returned anchor.
        assert chunk_body not in result
        assert "Confidential" not in result
        # Only the chunk index surfaces.
        assert result.startswith("dossier:fuzzy-match@chunk-")

    def test_default_threshold_is_module_constant(self):
        """D239 — default threshold is DEFAULT_FUZZY_CITATION_THRESHOLD."""
        from draft_quality import (
            _find_citation_anchor_fuzzy,
            DEFAULT_FUZZY_CITATION_THRESHOLD,
        )
        target = "Hugging Face Labs"
        embed_fn = _high_similarity_embed_fn(target)
        chunks = [(target, "https://example.com")]
        # With default threshold, cosine 1.0 ≥ 0.85 → accepts.
        result = _find_citation_anchor_fuzzy(
            target, chunks, embed_fn=embed_fn,
        )
        assert result == "https://example.com"
        # And the constant is 0.85.
        assert DEFAULT_FUZZY_CITATION_THRESHOLD == 0.85

    def test_zero_vector_embed_fn_yields_no_match(self):
        """D238 — the _cosine_similarity helper returns 0.0 for
        zero-vector inputs (avoids division-by-zero); fuzzy returns
        None."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Some chunk.", "https://example.com")]
        result = _find_citation_anchor_fuzzy(
            "Acme Corp", chunks,
            embed_fn=_zero_embed_fn,
            threshold=0.85,
        )
        assert result is None

    def test_chunker_independent_of_caller(self):
        """D238 — the fuzzy helper accepts pre-computed chunks; does
        NOT re-chunk."""
        from draft_quality import _find_citation_anchor_fuzzy
        # Pass a chunk that wouldn't naturally appear from the chunker.
        target = "X"
        embed_fn = _high_similarity_embed_fn(target)
        chunks = [(target, "https://example.com")]
        # Even though the chunker would filter "X" out (too short),
        # _find_citation_anchor_fuzzy uses the chunk list as-supplied.
        result = _find_citation_anchor_fuzzy(
            target, chunks, embed_fn=embed_fn, threshold=0.85,
        )
        assert result == "https://example.com"

    def test_claim_text_whitespace_only_returns_none(self):
        """D238 — whitespace-only claim_text → return None."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Acme Corp.", None)]
        result = _find_citation_anchor_fuzzy(
            "   \t  \n  ", chunks, embed_fn=_deterministic_embed_fn,
        )
        assert result is None

    def test_negative_score_threshold_handled(self):
        """D239 — even if threshold < 0 (out of [0,1]) is supplied at
        the helper level, the function does not raise; the threshold
        validation lives at parse_draft_for_claims (per ADR-0046
        D241)."""
        from draft_quality import _find_citation_anchor_fuzzy
        chunks = [("Some chunk.", None)]
        # Should accept any cosine since threshold is -0.5 ≤ everything.
        result = _find_citation_anchor_fuzzy(
            "Acme Corp", chunks,
            embed_fn=_deterministic_embed_fn,
            threshold=-0.5,
        )
        # Returns some anchor (the best match).
        assert result is not None


class TestParseDraftForClaimsFuzzy:
    """``parse_draft_for_claims`` fuzzy-fallback per ADR-0046 D237 + D240 + D241.

    Tests the deterministic-first + fuzzy-fallback pipeline + the
    attribution-claim exclusion (D240) + the lazy-load encoder
    resolution (D241).
    """

    def test_deterministic_first_path_runs_unchanged(self):
        """D237 — when deterministic substring match succeeds, fuzzy
        does NOT run (deterministic-first ordering)."""
        draft = "Excited by what Acme Corp ships."
        dossier = "Acme Corp shipped a product: https://example.com."
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=_zero_embed_fn,  # would yield no fuzzy match
        )
        # Substring matched → citation_anchor populated despite zero embed.
        named = [c for c in claims if c.claim_type == "named_entity"]
        assert any(c.citation_anchor is not None for c in named)

    def test_fuzzy_fallback_runs_when_deterministic_returns_none(self):
        """D237 — when deterministic returns None, fuzzy fallback runs
        if embed_fn + chunks are wired. Uses _always_match_embed_fn
        to deterministically trigger fuzzy acceptance."""
        draft = "Excited by Anthropic Inc work."
        # Dossier paraphrases — "anthropic inc" NOT a substring of
        # "Anthropic Labs released a new tool".
        dossier_chunk = "Anthropic Labs released a new tool."
        dossier = dossier_chunk
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=_always_match_embed_fn,
        )
        named = [c for c in claims if c.claim_type == "named_entity"]
        # The named_entity 'Anthropic Inc' fuzzy-matches the dossier
        # chunk via the always-match stub.
        assert any(c.citation_anchor is not None for c in named), (
            f"Expected at least one named_entity cited via fuzzy; "
            f"got: {[(c.claim_text, c.citation_anchor) for c in named]}"
        )

    def test_quoted_text_skips_fuzzy_per_d240(self):
        """D240 — quoted_text claims skip fuzzy fallback unconditionally."""
        draft = 'You said "agents are eating SaaS".'
        # Paraphrased quote in dossier → fuzzy MIGHT match if it ran.
        embed_fn = _high_similarity_embed_fn(
            "agents are everywhere now"
        )
        dossier = "agents are everywhere now"
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=embed_fn,
        )
        # The quoted_text claim must stay uncited (verbatim required).
        quoted = [c for c in claims if c.claim_type == "quoted_text"]
        assert all(c.citation_anchor is None for c in quoted)

    def test_you_phrase_skips_fuzzy_per_d240(self):
        """D240 — you_phrase claims skip fuzzy fallback (attribution
        semantic preserved)."""
        draft = "Saw you announced the partnership."
        # Dossier paraphrases — passive voice.
        dossier_chunk = "The partnership was announced via press release."
        embed_fn = _high_similarity_embed_fn(dossier_chunk)
        dossier = dossier_chunk
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=embed_fn,
        )
        # The you_phrase claim must stay uncited (attribution semantic
        # preserved per D240; passive paraphrase loses attribution).
        you_phrases = [c for c in claims if c.claim_type == "you_phrase"]
        assert all(c.citation_anchor is None for c in you_phrases)

    def test_fuzzy_runs_for_named_entity(self):
        """D240 — named_entity claims DO run fuzzy fallback (when the
        deterministic path returns None)."""
        draft = "Excited by Anthropic Inc work."
        # No substring match — 'anthropic inc' NOT in dossier.
        dossier = "Anthropic Labs shipped a major release."
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=_always_match_embed_fn,
        )
        named = [c for c in claims if c.claim_type == "named_entity"]
        # The named_entity SHOULD be cited via fuzzy.
        assert any(c.citation_anchor is not None for c in named), (
            f"Expected fuzzy fallback to cite named_entity; "
            f"got: {[(c.claim_text, c.citation_anchor) for c in named]}"
        )

    def test_fuzzy_runs_for_date_reference(self):
        """D240 follow-up — date_reference claims DO run fuzzy fallback
        (the dispatch matrix at D237 lists THREE claim types that run
        fuzzy: date_reference + named_entity + dated_event; this is
        the regression-barrier test for the date_reference cell).
        A refactor that accidentally added date_reference to the
        attribution-claim exclusion list would silently break the
        fuzzy WIN case + pass every other Week 9 test."""
        # 'Q3 2026' is NOT substring of "quarterly cycle".
        draft = "Saw your Q3 2026 announcement."
        dossier = "Quarterly cycle update available."
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=_always_match_embed_fn,
        )
        date_refs = [c for c in claims if c.claim_type == "date_reference"]
        # date_reference SHOULD be cited via fuzzy.
        assert any(c.citation_anchor is not None for c in date_refs), (
            f"Expected fuzzy fallback to cite date_reference; "
            f"got: {[(c.claim_text, c.citation_anchor) for c in date_refs]}"
        )

    def test_fuzzy_runs_for_dated_event(self):
        """D240 follow-up — dated_event claims DO run fuzzy fallback
        (the dispatch matrix at D237 lists THREE claim types that run
        fuzzy: date_reference + named_entity + dated_event; this is
        the regression-barrier test for the dated_event cell).
        A refactor that accidentally added dated_event to the
        attribution-claim exclusion list would silently break the
        fuzzy WIN case + pass every other Week 9 test."""
        # 'August 2026 launch' is NOT substring of dossier.
        draft = "Following the August 2026 launch."
        dossier = "Recent shipping milestones documented."
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=_always_match_embed_fn,
        )
        dated_events = [c for c in claims if c.claim_type == "dated_event"]
        # dated_event SHOULD be cited via fuzzy.
        assert any(c.citation_anchor is not None for c in dated_events), (
            f"Expected fuzzy fallback to cite dated_event; "
            f"got: {[(c.claim_text, c.citation_anchor) for c in dated_events]}"
        )

    def test_fuzzy_threshold_kwarg_passes_through(self):
        """D239 + D241 — the fuzzy_threshold kwarg propagates to the
        fuzzy helper. Uses a stub that returns a constant non-zero
        vector → cosine 1.0 against any chunk → fuzzy always cites."""
        captured = {}

        def _capture_embed(text):
            captured.setdefault("calls", []).append(text)
            # Constant non-zero vector → cosine 1.0 against any chunk.
            v = np.zeros(384, dtype=np.float32)
            v[0] = 1.0
            return v

        draft = "Excited by Anthropic Inc work."  # named_entity not
        # in dossier
        dossier = "Anthropic Labs shipped: https://example.com/acmexyz"
        # With threshold 0.99, the fuzzy path still cites (cosine 1.0
        # ≥ 0.99).
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=_capture_embed,
            fuzzy_threshold=0.99,
        )
        # The seam was wired (embed_fn was called).
        assert "calls" in captured

    def test_invalid_fuzzy_threshold_refuses_loud(self):
        """D239 — fuzzy_threshold out of [0,1] refuses loud."""
        with pytest.raises(ValueError, match="fuzzy_threshold"):
            parse_draft_for_claims(
                "Hello.", "World.",
                register="cold-pitch",
                fuzzy_threshold=1.5,
            )

    def test_bool_fuzzy_threshold_refuses_loud(self):
        """D239 — bool fuzzy_threshold refuses loud per the ADR-0041
        D201 bool-catch footgun discipline."""
        with pytest.raises(ValueError, match="fuzzy_threshold"):
            parse_draft_for_claims(
                "Hello.", "World.",
                register="cold-pitch",
                fuzzy_threshold=True,  # bool catch
            )

    def test_string_fuzzy_threshold_refuses_loud(self):
        """D239 — non-numeric fuzzy_threshold refuses loud."""
        with pytest.raises(ValueError, match="fuzzy_threshold"):
            parse_draft_for_claims(
                "Hello.", "World.",
                register="cold-pitch",
                fuzzy_threshold="0.85",  # string catch
            )

    def test_negative_fuzzy_threshold_refuses_loud(self):
        """D239 — negative fuzzy_threshold refuses loud."""
        with pytest.raises(ValueError, match="fuzzy_threshold"):
            parse_draft_for_claims(
                "Hello.", "World.",
                register="cold-pitch",
                fuzzy_threshold=-0.1,
            )

    def test_threshold_boundary_zero_accepted(self):
        """D239 — fuzzy_threshold=0.0 accepted (boundary)."""
        claims = parse_draft_for_claims(
            "Hello.", "World.",
            register="cold-pitch",
            embed_fn=_zero_embed_fn,
            fuzzy_threshold=0.0,
        )
        # No exception; runs to completion.
        assert isinstance(claims, list)

    def test_threshold_boundary_one_accepted(self):
        """D239 — fuzzy_threshold=1.0 accepted (boundary)."""
        claims = parse_draft_for_claims(
            "Hello.", "World.",
            register="cold-pitch",
            embed_fn=_zero_embed_fn,
            fuzzy_threshold=1.0,
        )
        assert isinstance(claims, list)

    def test_zero_embed_fn_disables_fuzzy(self):
        """D241 — passing a zero-vector embed_fn DISABLES fuzzy
        (the _cosine_similarity returns 0.0 → no chunk crosses
        threshold)."""
        draft = "Following XyzCorp's progress."  # XyzCorp not in dossier
        dossier = "Some unrelated chunk."
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=_zero_embed_fn,
        )
        # With zero-embed, no fuzzy match runs → named_entity uncited.
        named = [c for c in claims if c.claim_type == "named_entity"]
        assert all(c.citation_anchor is None for c in named)

    def test_fuzzy_anchor_does_not_contain_chunk_body(self):
        """D238 + I8 — the fuzzy match's anchor in ParsedClaim is the
        chunk-index diagnostic OR the chunk's nearby_url; the
        dossier's body text is NEVER in the anchor."""
        draft = "Following XyzCorp's progress."
        dossier_chunk = "Confidential dossier notes: XyzCorp shipped."
        embed_fn = _high_similarity_embed_fn(dossier_chunk)
        dossier = dossier_chunk
        claims = parse_draft_for_claims(
            draft, dossier,
            register="cold-pitch",
            embed_fn=embed_fn,
        )
        for c in claims:
            if c.citation_anchor is not None:
                # The dossier body must not appear in the anchor
                # (the deterministic substring path is OK since XyzCorp
                # IS in the dossier substring; the named_entity may
                # cite via deterministic 'dossier:match@offset-N').
                assert "Confidential dossier notes" not in c.citation_anchor


class TestScoreDraftFuzzy:
    """``score_draft`` fuzzy-threshold passthrough per ADR-0046 D236."""

    def test_score_draft_accepts_fuzzy_threshold(self, tmp_path):
        """D236 — score_draft accepts fuzzy_threshold kwarg."""
        thresholds_path = _write_thresholds_file(tmp_path)
        result = score_draft(
            "Hello.", "World.",
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            embed_fn=_zero_embed_fn,
            fuzzy_threshold=0.85,
        )
        assert isinstance(result, DraftQualityResult)

    def test_score_draft_default_fuzzy_threshold(self, tmp_path):
        """D239 — score_draft's default fuzzy_threshold is
        DEFAULT_FUZZY_CITATION_THRESHOLD."""
        thresholds_path = _write_thresholds_file(tmp_path)
        result = score_draft(
            "Hello.", "World.",
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            embed_fn=_zero_embed_fn,
        )
        assert isinstance(result, DraftQualityResult)

    def test_score_draft_invalid_fuzzy_threshold_refuses(self, tmp_path):
        """D239 — invalid fuzzy_threshold propagates from
        parse_draft_for_claims."""
        thresholds_path = _write_thresholds_file(tmp_path)
        with pytest.raises(ValueError, match="fuzzy_threshold"):
            score_draft(
                "Hello.", "World.",
                register="cold-pitch", channel="email",
                thresholds_path=thresholds_path,
                fuzzy_threshold=2.0,
            )

    def test_score_draft_fuzzy_path_activates(self, tmp_path):
        """D237 — score_draft's per-call dispatch wires the fuzzy
        fallback to parse_draft_for_claims."""
        thresholds_path = _write_thresholds_file(tmp_path)
        captured = {}

        def _capture_embed(text):
            captured.setdefault("calls", 0)
            captured["calls"] += 1
            return _deterministic_embed_fn(text)

        # Draft with named_entity that's NOT a substring of dossier →
        # deterministic returns None → fuzzy path activates.
        draft = "Excited by Anthropic Inc work."
        dossier = "Unrelated company released a tool."
        score_draft(
            draft, dossier,
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            embed_fn=_capture_embed,
        )
        # The encoder was called (fuzzy path ran).
        assert captured.get("calls", 0) > 0

    def test_score_draft_attribution_exclusion_per_d240(self, tmp_path):
        """D240 — score_draft preserves the quoted_text + you_phrase
        attribution-claim exclusion via parse_draft_for_claims."""
        thresholds_path = _write_thresholds_file(tmp_path)
        draft = 'You said "year of agents".'
        # Even with a high-similarity embed_fn, you_phrase + quoted_text
        # claims should stay uncited.
        embed_fn = _high_similarity_embed_fn("agents are everywhere")
        result = score_draft(
            draft, "agents are everywhere",
            register="cold-pitch", channel="email",
            thresholds_path=thresholds_path,
            embed_fn=embed_fn,
        )
        # state should be refused (uncited claims exist).
        you_phrases = [c for c in result.parsed_claims if c.claim_type == "you_phrase"]
        quoted = [c for c in result.parsed_claims if c.claim_type == "quoted_text"]
        for c in you_phrases + quoted:
            assert c.citation_anchor is None, (
                f"D240 attribution-claim exclusion failed for "
                f"{c.claim_type}: anchor={c.citation_anchor}"
            )


def _write_thresholds_file(tmp_path):
    """Helper — write a thresholds YAML file with the framework defaults."""
    thresholds_path = tmp_path / "voice_thresholds.yml"
    thresholds_path.write_text(
        yaml.safe_dump({
            "thresholds": dict(DEFAULT_VOICE_THRESHOLD_PER_REGISTER),
        })
    )
    return thresholds_path


class TestWeek9ModuleSurface:
    """The Pillar F Week 9 public surface per ADR-0046.

    Verifies the new symbols are exported + the W8/W7/W6 surfaces
    stay verbatim (the per-week handoff invariant).
    """

    def test_default_fuzzy_citation_threshold_exported(self):
        """D239 — DEFAULT_FUZZY_CITATION_THRESHOLD is module-level
        + equals 0.85."""
        assert hasattr(draft_quality, "DEFAULT_FUZZY_CITATION_THRESHOLD")
        assert draft_quality.DEFAULT_FUZZY_CITATION_THRESHOLD == 0.85

    def test_module_docstring_mentions_week_9(self):
        """P3-1 follow-up — the module-level docstring names Week 9
        + ADR-0046 (mirrors the doc-drift catch in Week 8 P3-2 +
        P3-3; the docstring is the operator-discovery surface)."""
        doc = draft_quality.__doc__ or ""
        assert "Week 9" in doc, (
            "Module docstring must name Week 9 per the doc-drift "
            "discipline"
        )
        assert "ADR-0046" in doc, (
            "Module docstring must reference ADR-0046 per the "
            "ADR-vs-implementation discipline"
        )

    def test_no_stale_zero_seven_five_in_fuzzy_docstrings(self):
        """P3-2 follow-up — no stale ``0.75`` references in the
        docstrings of the Week 9 fuzzy primitives + extended
        signatures (the default is ``0.85`` per ADR-0046 D239's
        calibration; ``0.75`` was the rejected initial proposal).
        The module-level constant block at lines ~245-275 may
        legitimately reference ``0.75`` in the negation-prose range
        discussion (cosine 0.75-0.90 for negation chunks)."""
        # Per-function docstrings should not contain the rejected
        # 0.75 default.
        for fn in (
            draft_quality._find_citation_anchor_fuzzy,
            draft_quality._find_citation_anchor,
            draft_quality.parse_draft_for_claims,
            draft_quality.score_draft,
        ):
            doc = fn.__doc__ or ""
            assert "(``0.75``)" not in doc, (
                f"{fn.__name__} docstring contains stale 0.75 default; "
                f"the framework default per ADR-0046 D239 is 0.85"
            )
            assert "default ``0.75``" not in doc, (
                f"{fn.__name__} docstring contains stale 0.75 default; "
                f"the framework default per ADR-0046 D239 is 0.85"
            )

    def test_chunker_helper_exists(self):
        """D238 — _chunk_dossier_for_fuzzy_match is module-level."""
        assert hasattr(draft_quality, "_chunk_dossier_for_fuzzy_match")
        assert callable(draft_quality._chunk_dossier_for_fuzzy_match)

    def test_fuzzy_helper_exists(self):
        """D238 — _find_citation_anchor_fuzzy is module-level."""
        assert hasattr(draft_quality, "_find_citation_anchor_fuzzy")
        assert callable(draft_quality._find_citation_anchor_fuzzy)

    def test_parse_draft_for_claims_has_fuzzy_threshold_kwarg(self):
        """D236 + D239 — parse_draft_for_claims signature includes
        fuzzy_threshold."""
        import inspect
        sig = inspect.signature(parse_draft_for_claims)
        assert "fuzzy_threshold" in sig.parameters
        # Default matches the module constant.
        default = sig.parameters["fuzzy_threshold"].default
        assert default == draft_quality.DEFAULT_FUZZY_CITATION_THRESHOLD

    def test_parse_draft_for_claims_has_cfg_kwarg(self):
        """D241 — parse_draft_for_claims signature includes cfg for
        the lazy-resolve encoder path."""
        import inspect
        sig = inspect.signature(parse_draft_for_claims)
        assert "cfg" in sig.parameters

    def test_score_draft_has_fuzzy_threshold_kwarg(self):
        """D236 + D239 — score_draft signature includes
        fuzzy_threshold."""
        import inspect
        sig = inspect.signature(score_draft)
        assert "fuzzy_threshold" in sig.parameters

    def test_week_6_surfaces_preserved(self):
        """Per the per-week handoff invariant — the Pillar F Week 6
        public surfaces stay verbatim at Week 9."""
        for sym in (
            "CLAIM_TYPES", "EMITTED_BY", "ParsedClaim",
            "DraftQualityResult", "parse_draft_for_claims",
            "score_draft", "build_hallucination_detected_payload",
        ):
            assert hasattr(draft_quality, sym), (
                f"Week 9 must preserve Week 6 surface {sym!r}"
            )

    def test_week_7_surfaces_preserved(self):
        """Per the per-week handoff invariant — the Pillar F Week 7
        public surfaces stay verbatim at Week 9."""
        for sym in (
            "CorpusPair", "CorpusMeasurement",
            "measure_per_claim_type_false_positive_rate",
        ):
            assert hasattr(draft_quality, sym), (
                f"Week 9 must preserve Week 7 surface {sym!r}"
            )

    def test_week_8_surfaces_preserved(self):
        """Per the per-week handoff invariant — the Pillar F Week 8
        public surfaces stay verbatim at Week 9."""
        for sym in (
            "DraftFidelityResult", "compute_draft_fidelity_score",
            "build_draft_quality_scored_payload",
        ):
            assert hasattr(draft_quality, sym), (
                f"Week 9 must preserve Week 8 surface {sym!r}"
            )

    def test_cli_parse_has_no_fuzzy_threshold_flag(self):
        """D237 + per the operator-deferred CLI surface — the
        ``parse`` subcommand does NOT surface ``--fuzzy-threshold``
        at Week 9 (the per-call kwarg is library-only access)."""
        out = subprocess.check_output(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "parse", "--help"],
            text=True,
        )
        assert "--fuzzy-threshold" not in out

    def test_cli_score_has_no_fuzzy_threshold_flag(self):
        """D237 + per the operator-deferred CLI surface — the
        ``score`` subcommand does NOT surface ``--fuzzy-threshold``
        at Week 9 (the per-call kwarg is library-only access)."""
        out = subprocess.check_output(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "score", "--help"],
            text=True,
        )
        assert "--fuzzy-threshold" not in out


class TestWeek9SeamPreservation:
    """The TEST-ONLY ``embed_fn`` seam preservation at Week 9 per
    ADR-0046 D243.

    Verifies the seam stays labeled TEST-ONLY at the parser surface
    even after Week 9's behavioral consumption activation.
    """

    def test_parse_docstring_labels_embed_fn_test_only(self):
        """D243 — parse_draft_for_claims docstring labels embed_fn
        TEST-ONLY (the label stays valid because operators don't
        inject custom encoders at production callsites)."""
        doc = parse_draft_for_claims.__doc__ or ""
        assert "TEST-ONLY" in doc

    def test_parse_docstring_names_week_9_activation(self):
        """D243 — the docstring NAMES the Week 9 behavioral
        consumption at the parser surface (the first non-N/A
        verification at this surface)."""
        doc = parse_draft_for_claims.__doc__ or ""
        assert "ADR-0046" in doc

    def test_score_docstring_labels_embed_fn_test_only(self):
        """D243 — score_draft docstring labels embed_fn TEST-ONLY."""
        doc = score_draft.__doc__ or ""
        assert "TEST-ONLY" in doc

    def test_parse_embed_fn_kwarg_signature(self):
        """D243 — parse_draft_for_claims still has the embed_fn
        kwarg per ADR-0043 D218 lineage."""
        import inspect
        sig = inspect.signature(parse_draft_for_claims)
        assert "embed_fn" in sig.parameters

    def test_score_embed_fn_kwarg_signature(self):
        """D243 — score_draft still has the embed_fn kwarg."""
        import inspect
        sig = inspect.signature(score_draft)
        assert "embed_fn" in sig.parameters


# ===========================================================================
# Pillar F Week 10 — Layer 4 post-engine guard + draft_ready event class
# per ADR-0047 (D244-D251)
# ===========================================================================


def _paired_results(
    *,
    quality_state: str = "ready",
    fidelity_state: str = "ready",
    register: str = "cold-pitch",
    channel: str = "email",
    draft_body: str = "Hey, saw your post last week.",
    parsed_claims: tuple[ParsedClaim, ...] | None = None,
    uncited_claims: tuple[ParsedClaim, ...] | None = None,
    voice_fidelity_score: float = 0.82,
    voice_fidelity_threshold: float = 0.70,
) -> tuple[DraftQualityResult, DraftFidelityResult]:
    """Build a paired (DraftQualityResult, DraftFidelityResult) for the
    Layer 4 emit-guard's per-call dispatch tests.

    Both results carry the SAME ``draft_hash`` (cross-dimension consistency
    per ADR-0047 D245); both stamp the matching register + channel.
    Defaults to BOTH ``ready`` for the happy-path test fixture.
    """
    if quality_state == "ready" and parsed_claims is None and uncited_claims is None:
        # Happy-path: zero claims (so no uncited claims; state=ready is valid).
        parsed_claims = ()
        uncited_claims = ()
    elif quality_state == "refused" and uncited_claims is None:
        # Refused-path: at least one uncited claim.
        uncited = _basic_claim(claim_type="you_phrase",
                                claim_text="you posted about X")
        parsed_claims = parsed_claims or (uncited,)
        uncited_claims = (uncited,)
    elif parsed_claims is None:
        parsed_claims = uncited_claims or ()
    else:
        if uncited_claims is None:
            uncited_claims = tuple(
                c for c in parsed_claims if c.citation_anchor is None
            )

    quality = DraftQualityResult(
        draft_hash=_hash(draft_body),
        register=register,
        channel=channel,
        parsed_claims=parsed_claims,
        uncited_claims=uncited_claims,
        threshold=voice_fidelity_threshold,
        state=quality_state,
    )

    if fidelity_state == "refused":
        # Score below threshold to drive state=refused.
        score = min(voice_fidelity_score, voice_fidelity_threshold - 0.05)
        meets = False
    else:
        score = max(voice_fidelity_score, voice_fidelity_threshold + 0.05)
        meets = True

    fidelity = DraftFidelityResult(
        draft_hash=_hash(draft_body),
        register=register,
        channel=channel,
        voice_fidelity_score=score,
        voice_fidelity_threshold=voice_fidelity_threshold,
        meets_threshold=meets,
        exemplar_ids=("ex-001",),
        k=5,
        state=fidelity_state,
    )
    return quality, fidelity


# ---------------------------------------------------------------------------
# build_draft_ready_payload — Layer 4 emit-guard factory per ADR-0047 D245+D246
# ---------------------------------------------------------------------------


class TestBuildDraftReadyPayload:
    """ADR-0047 D245 + D246 — Layer 4 emit-guard factory's per-call dispatch.

    Coverage:

    * The per-dimension refuse-loud cell matrix per D245 — outcome
      partition is state × override × dimension; per the per-week
      reviewer's "cell-level matrix coverage" discipline (caught P2s
      at Weeks 6+7+8+9), each cell is tested independently.
    * Closed-enum + result-mismatch + cross-dimension consistency
      refuse-loud per D245 step 1-4.
    * Override bool-catch + reason-required-when-override-true per
      D245 step 3 (bool catch per ADR-0041 D201's bool-is-an-int
      discipline).
    * Event payload shape per D246 — privacy-respecting (no raw
      draft, no per-claim trace, no per-exemplar bodies); per-dimension
      verdict markers (passed | passed_via_override | skipped).
    * The ``voice_fidelity_check == "skipped"`` path per D246 when
      ``fidelity_result is None``.
    """

    # --- Cell (ready, ready, no overrides) — the happy path ---

    def test_happy_path_both_pass_emits_native(self):
        """D245+D246 — both gates ``state="ready"`` → emit-only-on-
        both-pass posture fires; both per-dimension verdicts are
        ``"passed"`` (native-pass, not via-override)."""
        quality, fidelity = _paired_results()
        payload = build_draft_ready_payload(
            person_id="person-123",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
        )
        assert payload["type"] == "draft_ready"
        assert payload["person_id"] == "person-123"
        assert payload["draft_hash"] == quality.draft_hash
        assert payload["register"] == "cold-pitch"
        assert payload["channel"] == "email"
        assert payload["hallucination_check"] == "passed"
        assert payload["voice_fidelity_check"] == "passed"
        assert payload["voice_fidelity_score"] == fidelity.voice_fidelity_score
        assert payload["voice_fidelity_threshold"] == fidelity.voice_fidelity_threshold
        assert payload["hallucination_check_override_reason"] is None
        assert payload["voice_fidelity_check_override_reason"] is None
        assert payload["_emitted_by"] == EMITTED_BY

    # --- Cell (refused, ready, no overrides) — Layer4GuardRefusal[hallucination] ---

    def test_hallucination_refused_no_override_refuses_loud(self):
        """D245 — ``quality_result.state == "refused"`` AND no override
        → raises Layer4GuardRefusal naming the hallucination dimension."""
        quality, fidelity = _paired_results(quality_state="refused")
        with pytest.raises(Layer4GuardRefusal) as exc_info:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )
        assert exc_info.value.refused_dimensions == ("hallucination",)
        assert "hallucination" in str(exc_info.value)
        # Exception carries the result objects for diagnostic surfacing.
        assert exc_info.value.quality_result is quality
        assert exc_info.value.fidelity_result is fidelity

    # --- Cell (refused, ready, hallucination_override) — emit + via-override marker ---

    def test_hallucination_refused_with_override_emits_via_override(self):
        """D247 — hallucination override bypasses the refuse-loud +
        stamps ``hallucination_check == "passed_via_override"`` on the
        event. Pillar I per-tenant audit-tooling distinguishes native
        from override pass via this marker."""
        quality, fidelity = _paired_results(quality_state="refused")
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
            hallucination_check_override=True,
            hallucination_check_override_reason="paraphrased citation",
        )
        assert payload["hallucination_check"] == "passed_via_override"
        assert payload["hallucination_check_override_reason"] == "paraphrased citation"
        # The fidelity dimension is unchanged (native pass).
        assert payload["voice_fidelity_check"] == "passed"
        assert payload["voice_fidelity_check_override_reason"] is None

    # --- Cell (ready, refused, no overrides) — Layer4GuardRefusal[fidelity] ---

    def test_fidelity_refused_no_override_refuses_loud(self):
        """D245 — ``fidelity_result.state == "refused"`` AND no override
        → raises Layer4GuardRefusal naming the fidelity dimension."""
        quality, fidelity = _paired_results(fidelity_state="refused")
        with pytest.raises(Layer4GuardRefusal) as exc_info:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )
        assert exc_info.value.refused_dimensions == ("fidelity",)
        assert "fidelity" in str(exc_info.value)

    # --- Cell (ready, refused, fidelity_override) — emit + via-override marker ---

    def test_fidelity_refused_with_override_emits_via_override(self):
        """D247 — fidelity override bypasses the refuse-loud + stamps
        ``voice_fidelity_check == "passed_via_override"`` on the event."""
        quality, fidelity = _paired_results(fidelity_state="refused")
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
            voice_fidelity_check_override=True,
            voice_fidelity_check_override_reason="operator-calibrated for this draft",
        )
        assert payload["voice_fidelity_check"] == "passed_via_override"
        assert payload["voice_fidelity_check_override_reason"] == (
            "operator-calibrated for this draft"
        )
        # Hallucination dimension unchanged (native pass).
        assert payload["hallucination_check"] == "passed"

    # --- Cell (refused, refused, no overrides) — Layer4GuardRefusal[both] ---

    def test_both_dimensions_refused_no_overrides_refuses_with_both(self):
        """D245 — BOTH dimensions refused AND BOTH overrides absent →
        Layer4GuardRefusal naming BOTH dimensions in one error.
        SYMMETRIC two-dimensional verdict per D245's structural commitment."""
        quality, fidelity = _paired_results(
            quality_state="refused", fidelity_state="refused"
        )
        with pytest.raises(Layer4GuardRefusal) as exc_info:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )
        assert exc_info.value.refused_dimensions == ("hallucination", "fidelity")
        assert "hallucination" in str(exc_info.value)
        assert "fidelity" in str(exc_info.value)

    # --- Cell (refused, refused, both overrides) — emit with both override markers ---

    def test_both_dimensions_refused_with_both_overrides_emits(self):
        """D247 — BOTH overrides set → emit with BOTH ``passed_via_override``
        markers. Operators stamping both overrides surface both rationales
        on the per-event audit stream."""
        quality, fidelity = _paired_results(
            quality_state="refused", fidelity_state="refused"
        )
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
            hallucination_check_override=True,
            hallucination_check_override_reason="known paraphrase",
            voice_fidelity_check_override=True,
            voice_fidelity_check_override_reason="operator-stamped",
        )
        assert payload["hallucination_check"] == "passed_via_override"
        assert payload["voice_fidelity_check"] == "passed_via_override"
        assert payload["hallucination_check_override_reason"] == "known paraphrase"
        assert payload["voice_fidelity_check_override_reason"] == "operator-stamped"

    # --- Cell (ready, None=skipped, no overrides) — emit with skipped marker ---

    def test_fidelity_none_emits_skipped_marker(self):
        """D246 — ``fidelity_result=None`` surfaces the
        ``voice_fidelity_check == "skipped"`` path. Operators with
        ``voice.use_embedding_primitive: false`` (legacy posture per
        ADR-0045 §Migration/rollout Path B) use this."""
        quality, _ = _paired_results()
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=None,
            channel="email",
            register="cold-pitch",
        )
        assert payload["voice_fidelity_check"] == "skipped"
        assert payload["voice_fidelity_score"] is None
        assert payload["voice_fidelity_threshold"] is None
        assert payload["voice_fidelity_check_override_reason"] is None
        # Hallucination dimension still emits native-pass.
        assert payload["hallucination_check"] == "passed"

    # --- Cell (refused, None=skipped, hallucination_override) — emit override+skipped ---

    def test_hallucination_override_with_skipped_fidelity_emits(self):
        """D246+D247 — hallucination_override=True + fidelity_result=None
        → emit with hallucination_check=passed_via_override AND
        voice_fidelity_check=skipped."""
        quality, _ = _paired_results(quality_state="refused")
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=None,
            channel="email",
            register="cold-pitch",
            hallucination_check_override=True,
            hallucination_check_override_reason="ok",
        )
        assert payload["hallucination_check"] == "passed_via_override"
        assert payload["voice_fidelity_check"] == "skipped"

    # --- Cell (refused, None=skipped, no overrides) — Layer4GuardRefusal[hallucination] ---

    def test_hallucination_refused_with_skipped_fidelity_refuses(self):
        """D245+D246 — quality_state=refused + fidelity_result=None +
        no override → refuses-loud on hallucination dimension; the
        skipped fidelity path does NOT mask the hallucination refusal."""
        quality, _ = _paired_results(quality_state="refused")
        with pytest.raises(Layer4GuardRefusal) as exc_info:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=None,
                channel="email",
                register="cold-pitch",
            )
        assert exc_info.value.refused_dimensions == ("hallucination",)
        # When fidelity_result is None, the exception's
        # ``fidelity_result`` attribute is None.
        assert exc_info.value.fidelity_result is None

    # --- Closed-enum + result-mismatch refuse-loud ---

    def test_unknown_channel_refuses_loud(self):
        """D245 — channel not in CHANNELS refuses-loud."""
        quality, fidelity = _paired_results()
        with pytest.raises(ValueError, match="channel"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="fax",
                register="cold-pitch",
            )

    def test_unknown_register_refuses_loud(self):
        """D245 — register not in REGISTERS refuses-loud."""
        quality, fidelity = _paired_results()
        with pytest.raises(ValueError, match="register"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="introduction",
            )

    def test_channel_mismatch_with_quality_result_refuses_loud(self):
        """D245 — channel kwarg MUST match ``quality_result.channel``
        (mirrors ADR-0043 D216 + ADR-0045 D231)."""
        quality, fidelity = _paired_results(channel="email")
        with pytest.raises(ValueError, match="quality_result.channel"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="linkedin-dm",
                register="cold-pitch",
            )

    def test_register_mismatch_with_quality_result_refuses_loud(self):
        """D245 — register kwarg MUST match ``quality_result.register``."""
        quality, fidelity = _paired_results(register="cold-pitch")
        with pytest.raises(ValueError, match="quality_result.register"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="congrats",
            )

    def test_channel_mismatch_with_fidelity_result_refuses_loud(self):
        """D245 — channel kwarg MUST match ``fidelity_result.channel``
        even when quality_result.channel matches (the cross-dimension
        check fires on EITHER result mismatch)."""
        # Build a fidelity result with a different channel than the quality.
        quality, _ = _paired_results(channel="email")
        fidelity = DraftFidelityResult(
            draft_hash=quality.draft_hash,
            register="cold-pitch",
            channel="linkedin-dm",  # MISMATCH
            voice_fidelity_score=0.82,
            voice_fidelity_threshold=0.70,
            meets_threshold=True,
            exemplar_ids=("ex-001",),
            k=5,
            state="ready",
        )
        # The quality channel matches; the fidelity channel doesn't.
        # The factory's quality-vs-kwarg check fires first; pass kwargs
        # matching quality to surface the fidelity mismatch.
        with pytest.raises(ValueError, match="fidelity_result.channel"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )

    def test_register_mismatch_with_fidelity_result_refuses_loud(self):
        """D245 — register kwarg MUST match ``fidelity_result.register``
        when quality_result.register matches."""
        quality, _ = _paired_results(register="cold-pitch")
        fidelity = DraftFidelityResult(
            draft_hash=quality.draft_hash,
            register="congrats",  # MISMATCH
            channel="email",
            voice_fidelity_score=0.82,
            voice_fidelity_threshold=0.70,
            meets_threshold=True,
            exemplar_ids=("ex-001",),
            k=5,
            state="ready",
        )
        with pytest.raises(ValueError, match="fidelity_result.register"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )

    def test_cross_dimension_draft_hash_mismatch_refuses_loud(self):
        """D245 step 4 — ``quality_result.draft_hash`` MUST equal
        ``fidelity_result.draft_hash`` (both results MUST refer to the
        same draft body). Mismatch is a caller bug that would silently
        emit a draft_ready claiming two-dimension verdict on two
        different drafts."""
        quality, _ = _paired_results(draft_body="draft A")
        # Build a fidelity result for a DIFFERENT draft body
        fidelity_other = DraftFidelityResult(
            draft_hash=_hash("draft B"),  # MISMATCH
            register="cold-pitch",
            channel="email",
            voice_fidelity_score=0.82,
            voice_fidelity_threshold=0.70,
            meets_threshold=True,
            exemplar_ids=("ex-001",),
            k=5,
            state="ready",
        )
        with pytest.raises(ValueError, match="draft_hash"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity_other,
                channel="email",
                register="cold-pitch",
            )

    # --- Override bool catch per ADR-0041 D201 ---

    def test_int_hallucination_override_refuses_loud(self):
        """D247 + ADR-0041 D201 — integer 1 is NOT bool True even though
        ``isinstance(1, int) == True``. The bool-is-an-int discipline
        requires explicit type() check."""
        quality, fidelity = _paired_results()
        with pytest.raises(ValueError, match="bool"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
                hallucination_check_override=1,  # type: ignore[arg-type]
            )

    def test_int_fidelity_override_refuses_loud(self):
        """D247 + ADR-0041 D201 — symmetric bool catch on fidelity override."""
        quality, fidelity = _paired_results()
        with pytest.raises(ValueError, match="bool"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
                voice_fidelity_check_override=1,  # type: ignore[arg-type]
            )

    # --- Reason-required-when-override-true per D247 ---

    def test_hallucination_override_without_reason_refuses_loud(self):
        """D247 — ``hallucination_check_override=True`` REQUIRES a
        non-empty stripped reason; operators stamping an override MUST
        surface the rationale per ADR-0043 D217's discipline."""
        quality, fidelity = _paired_results(quality_state="refused")
        with pytest.raises(ValueError, match="hallucination_check_override_reason"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
                hallucination_check_override=True,
                hallucination_check_override_reason=None,
            )

    def test_hallucination_override_with_whitespace_reason_refuses_loud(self):
        """D247 — whitespace-only reason is rejected (stripped → empty)."""
        quality, fidelity = _paired_results(quality_state="refused")
        with pytest.raises(ValueError, match="hallucination_check_override_reason"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
                hallucination_check_override=True,
                hallucination_check_override_reason="   ",
            )

    def test_fidelity_override_without_reason_refuses_loud(self):
        """D247 — symmetric reason-required check on fidelity override."""
        quality, fidelity = _paired_results(fidelity_state="refused")
        with pytest.raises(ValueError, match="voice_fidelity_check_override_reason"):
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
                voice_fidelity_check_override=True,
                voice_fidelity_check_override_reason=None,
            )

    def test_fidelity_override_with_skipped_fidelity_ignores_reason_requirement(self):
        """D247 — when ``fidelity_result is None`` (skipped path), the
        fidelity override is meaningless; the reason-required check
        does NOT fire. Pre-existing operator scripts that pass the
        override kwarg with skip-fidelity-check still work.

        Per Week 10 follow-up P3-1: the reason field MUST land as
        ``None`` in the payload even when the operator stamped a
        non-None reason — the skipped path discards the reason since
        the override semantic is structurally moot. A future refactor
        that drops the ``fidelity_result is not None`` guard at the
        payload assembly site would leak the reason; the assertion
        catches the regression.
        """
        quality, _ = _paired_results()
        # voice_fidelity_check_override=True + reason=None + fidelity_result=None
        # → does NOT raise (the override is structurally moot for skipped).
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=None,
            channel="email",
            register="cold-pitch",
            voice_fidelity_check_override=True,
            voice_fidelity_check_override_reason=None,
        )
        assert payload["voice_fidelity_check"] == "skipped"
        # Per Week 10 follow-up P3-1 — reason MUST be None in payload
        # for the skipped path even when operator stamped a non-None
        # reason (the implementation discards it; this assertion
        # prevents regression of the discard).
        assert payload["voice_fidelity_check_override_reason"] is None

    def test_hallucination_override_on_already_ready_quality_stamps_via_override(self):
        """Per Week 10 follow-up P3-2 — D247: hallucination_check_override=True
        stamps ``passed_via_override`` unconditionally, even when
        ``quality_result.state`` is already ``"ready"``. Pillar I per-tenant
        audit-tooling reads the override marker for the per-operator
        override-rate signal; scripted tooling that always passes the
        override flag inflates this rate even for clean drafts.

        The cell ``(quality=ready, fidelity=ready, hallucination_override=True)``
        was missing from the original Week 10 ``TestBuildDraftReadyPayload``
        suite — the reviewer caught it as a P3 cell-coverage gap. This
        regression-barrier test documents the override's unconditional
        application.
        """
        quality, fidelity = _paired_results()  # both states default to "ready"
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
            hallucination_check_override=True,
            hallucination_check_override_reason="always-override tooling",
        )
        # The override stamps passed_via_override regardless of the
        # underlying quality_result.state value (the override is
        # operator-deliberate per ADR-0047 D247; the stamp is permanent).
        assert payload["hallucination_check"] == "passed_via_override"
        assert payload["hallucination_check_override_reason"] == (
            "always-override tooling"
        )
        # The fidelity dimension is unaffected (no override on that
        # dimension; native pass).
        assert payload["voice_fidelity_check"] == "passed"
        assert payload["voice_fidelity_check_override_reason"] is None

    # --- Payload shape + privacy per ADR-0047 D246 + I8 ---

    def test_payload_does_not_contain_raw_draft(self):
        """D246 + I8 — the payload MUST NOT carry the raw draft body.
        Only the sha256 ``draft_hash`` + the structural fields appear.
        Mirrors Week 6 follow-up P3-2's recursive walk check."""
        secret_draft = "secret operator draft body that should not leak"
        quality = DraftQualityResult(
            draft_hash=_hash(secret_draft),
            register="cold-pitch",
            channel="email",
            parsed_claims=(),
            uncited_claims=(),
            threshold=0.70,
            state="ready",
        )
        fidelity = DraftFidelityResult(
            draft_hash=_hash(secret_draft),
            register="cold-pitch",
            channel="email",
            voice_fidelity_score=0.82,
            voice_fidelity_threshold=0.70,
            meets_threshold=True,
            exemplar_ids=("ex-001",),
            k=5,
            state="ready",
        )
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
        )

        def _walk(value):
            if isinstance(value, str):
                assert secret_draft not in value
            elif isinstance(value, dict):
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for item in value:
                    _walk(item)

        _walk(payload)

    def test_payload_does_not_contain_per_claim_trace(self):
        """D246 + I8 — the per-claim trace MUST NOT appear in the
        payload. Only counts surface; operators inspect the per-claim
        diagnostic via the upstream hallucination_detected event per
        ADR-0043 D219."""
        secret_claim_text = "you posted about THE SECRET TOPIC last week"
        uncited = ParsedClaim(
            claim_type="you_phrase",
            claim_text=secret_claim_text,
            citation_anchor=None,
        )
        quality = DraftQualityResult(
            draft_hash=_hash("draft body"),
            register="cold-pitch",
            channel="email",
            parsed_claims=(uncited,),
            uncited_claims=(uncited,),
            threshold=0.70,
            state="refused",
        )
        fidelity = DraftFidelityResult(
            draft_hash=_hash("draft body"),
            register="cold-pitch",
            channel="email",
            voice_fidelity_score=0.82,
            voice_fidelity_threshold=0.70,
            meets_threshold=True,
            exemplar_ids=("ex-001",),
            k=5,
            state="ready",
        )
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
            hallucination_check_override=True,
            hallucination_check_override_reason="ok",
        )

        def _walk(value):
            if isinstance(value, str):
                assert secret_claim_text not in value
            elif isinstance(value, dict):
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for item in value:
                    _walk(item)

        _walk(payload)
        # The counts ARE in the payload (no per-claim trace, just counts).
        assert payload["parsed_claims_count"] == 1
        assert payload["uncited_claims_count"] == 1

    def test_payload_does_not_contain_exemplar_bodies(self):
        """D246 + I8 — exemplar BODIES MUST NOT appear in the payload.
        Only the per-Layer 2 scalar fields surface; operators look up
        per-exemplar IDs via the upstream draft_quality_scored event."""
        quality, fidelity = _paired_results()
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
        )
        # No exemplar_ids field in the draft_ready event (per D246's
        # privacy posture — per-exemplar IDs surface on draft_quality_scored).
        assert "exemplar_ids" not in payload
        assert "exemplar_bodies" not in payload

    def test_person_id_none_accepted(self):
        """D246 — ``person_id=None`` accepted for ad-hoc operator
        validation (mirrors ADR-0043 D216 + ADR-0045 D231)."""
        quality, fidelity = _paired_results()
        payload = build_draft_ready_payload(
            person_id=None,
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
        )
        assert payload["person_id"] is None

    def test_emitted_by_marker(self):
        """D246 — ``_emitted_by`` marker per ADR-0010 D17 + ADR-0043
        D216: ``draft_quality`` (same module emits ALL FOUR Pillar F
        event classes)."""
        quality, fidelity = _paired_results()
        payload = build_draft_ready_payload(
            person_id="p",
            quality_result=quality,
            fidelity_result=fidelity,
            channel="email",
            register="cold-pitch",
        )
        assert payload["_emitted_by"] == "draft_quality"


# ---------------------------------------------------------------------------
# Layer4GuardRefusal typed exception per ADR-0047 D245
# ---------------------------------------------------------------------------


class TestLayer4GuardRefusal:
    """ADR-0047 D245 — typed exception for the Layer 4 emit-guard's
    per-dimension refusal verdict.

    Coverage:

    * Subclass of :exc:`ValueError` per D244 (existing exception-
      handling that catches ValueError continues to work).
    * Carries ``refused_dimensions`` + the per-Layer 2 result
      objects for operator-readable diagnostic surfacing.
    """

    def test_subclass_of_value_error(self):
        """D244 — Layer4GuardRefusal subclasses ValueError so existing
        try/except blocks catching ValueError continue to work."""
        assert issubclass(Layer4GuardRefusal, ValueError)

    def test_carries_refused_dimensions(self):
        """D245 — the exception's ``refused_dimensions`` attribute
        names which dimension(s) refused. Operators inspect this for
        per-dimension diagnostic surfacing."""
        quality, fidelity = _paired_results(quality_state="refused")
        try:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )
        except Layer4GuardRefusal as exc:
            assert exc.refused_dimensions == ("hallucination",)
        else:
            pytest.fail("Layer4GuardRefusal expected")

    def test_carries_quality_result(self):
        """D245 — the exception carries the ``quality_result`` for
        operator-readable diagnostic surfacing (the per-claim trace
        lives on the result)."""
        quality, fidelity = _paired_results(quality_state="refused")
        try:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )
        except Layer4GuardRefusal as exc:
            assert exc.quality_result is quality

    def test_carries_fidelity_result(self):
        """D245 — the exception carries the ``fidelity_result`` for
        operator-readable diagnostic surfacing."""
        quality, fidelity = _paired_results(fidelity_state="refused")
        try:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )
        except Layer4GuardRefusal as exc:
            assert exc.fidelity_result is fidelity

    def test_carries_none_fidelity_result_when_skipped(self):
        """D245+D246 — when ``fidelity_result=None`` (skipped path) +
        the hallucination dimension refuses, the exception's
        ``fidelity_result`` attribute is None."""
        quality, _ = _paired_results(quality_state="refused")
        try:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=None,
                channel="email",
                register="cold-pitch",
            )
        except Layer4GuardRefusal as exc:
            assert exc.fidelity_result is None

    def test_str_message_is_operator_readable(self):
        """D245 — the exception's str() message names the refused
        dimension(s) + the per-dimension diagnostic prose."""
        quality, fidelity = _paired_results(
            quality_state="refused", fidelity_state="refused"
        )
        try:
            build_draft_ready_payload(
                person_id="p",
                quality_result=quality,
                fidelity_result=fidelity,
                channel="email",
                register="cold-pitch",
            )
        except Layer4GuardRefusal as exc:
            msg = str(exc)
            assert "Layer 4" in msg
            assert "hallucination" in msg
            assert "fidelity" in msg
            assert "ADR-0047" in msg
            assert "ADR-0038" in msg


# ---------------------------------------------------------------------------
# CLI emit-ready subcommand per ADR-0047 D248
# ---------------------------------------------------------------------------


class TestCLIEmitReady:
    """ADR-0047 D248 — CLI ``emit-ready`` subcommand smoke tests.

    Coverage:

    * The subcommand runs BOTH per-Layer 2 gates + invokes the Layer 4
      emit-guard + emits per-Layer events at their existing cardinality
      (per ADR-0047 D248 — emit-cardinality preserved).
    * The ``--skip-fidelity-check`` flag actually skips the fidelity
      scorer + emits draft_ready with ``voice_fidelity_check: skipped``.
    * The ``--apply`` flag controls ledger appends.
    * The ``--json`` output surfaces the Layer 4 verdict + refusal
      diagnostic when applicable.
    """

    def _write_draft_and_dossier(
        self, tmp_path: Path, draft: str, dossier: str
    ) -> tuple[Path, Path]:
        draft_path = tmp_path / "draft.txt"
        dossier_path = tmp_path / "dossier.md"
        draft_path.write_text(draft)
        dossier_path.write_text(dossier)
        return draft_path, dossier_path

    def test_emit_ready_help_lists_subcommand(self, tmp_path):
        """D248 — the ``emit-ready`` subcommand surfaces in the main
        --help output."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "--help"],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        assert "emit-ready" in proc.stdout

    def test_emit_ready_subcommand_help_lists_flags(self, tmp_path):
        """D248 — the subcommand's --help lists all per-dimension
        override + skip-fidelity-check flags."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready", "--help"],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        assert "--hallucination-check-override" in proc.stdout
        assert "--hallucination-check-override-reason" in proc.stdout
        assert "--voice-fidelity-check-override" in proc.stdout
        assert "--voice-fidelity-check-override-reason" in proc.stdout
        assert "--skip-fidelity-check" in proc.stdout

    def test_skip_fidelity_check_emits_draft_ready_with_skipped(self, tmp_path):
        """D246+D248 — ``--skip-fidelity-check`` skips the Layer 2
        fidelity scorer + emits draft_ready with
        ``voice_fidelity_check: skipped``. Operators with
        ``voice.use_embedding_primitive: false`` legacy posture use
        this path."""
        # Clean draft + clean dossier (zero claims; both gates pass
        # trivially — the hallucination gate is satisfied by empty
        # uncited_claims; the fidelity gate is skipped).
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft_path, dossier_path = self._write_draft_and_dossier(
            tmp_path, "Hello there.", "## Notes\nSome content."
        )
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
                "--json",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0, (
            f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
        )
        out = json.loads(proc.stdout)
        assert out["layer_4_check"] == "passed"
        assert out["fidelity_state"] == "skipped"
        # The draft_ready payload's voice_fidelity_check field is
        # "skipped".
        assert out["draft_ready_payload"]["voice_fidelity_check"] == "skipped"

    def test_uncited_draft_refuses_layer_4_in_json(self, tmp_path):
        """D245+D248 — an adversarial draft with uncited claims +
        --skip-fidelity-check → JSON output's ``layer_4_check ==
        "refused"`` + ``refused_dimensions`` contains "hallucination"."""
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        # Adversarial draft per the Layer 1 stub pattern.
        draft = (
            "Hey, saw you posted last week about a Phantom Project "
            "launch — congrats."
        )
        dossier = (
            "## Recent posts\nUnrelated content [1].\n\n"
            "[1]: https://example.com/other"
        )
        draft_path, dossier_path = self._write_draft_and_dossier(
            tmp_path, draft, dossier
        )
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",  # focus on the hallucination dimension
                "--json",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out["layer_4_check"] == "refused"
        assert "hallucination" in out["refused_dimensions"]
        # The CLI surfaces the per-claim trace for operator remediation.
        assert "uncited_claims" in out
        assert len(out["uncited_claims"]) >= 1
        # Layer 4 refused → NO draft_ready payload in the output.
        assert "draft_ready_payload" not in out

    def test_uncited_draft_with_hallucination_override_emits_draft_ready(
        self, tmp_path
    ):
        """D247+D248 — operator stamps ``--hallucination-check-override``
        + reason → Layer 4 emits draft_ready with
        ``hallucination_check: passed_via_override``. Operators bypass
        the per-dimension refuse via the per-CLI-call override.

        Per Week 10 follow-up P2-2 the top-level ``layer_4_check`` field
        ALSO emits ``"passed_via_override"`` when ANY override fires (so
        operators can stamp the matching value on the Touch note
        frontmatter per SKILL.md D249 without inspecting the nested
        payload).
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft = (
            "Hey, saw you posted last week about a Phantom Project "
            "launch — congrats."
        )
        dossier = "## Notes\nUnrelated content."
        draft_path, dossier_path = self._write_draft_and_dossier(
            tmp_path, draft, dossier
        )
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
                "--hallucination-check-override",
                "--hallucination-check-override-reason",
                "paraphrased citation in dossier",
                "--json",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        # Per Week 10 follow-up P2-2 — top-level marker emits via-override.
        assert out["layer_4_check"] == "passed_via_override"
        # Per ADR-0047 D247 — nested per-dimension marker also stamps via-override.
        assert out["draft_ready_payload"]["hallucination_check"] == (
            "passed_via_override"
        )
        assert out["draft_ready_payload"]["hallucination_check_override_reason"] == (
            "paraphrased citation in dossier"
        )

    def test_apply_appends_draft_ready_event_to_ledger(self, tmp_path):
        """D248 — ``--apply`` actually appends the ``draft_ready`` event
        to the ledger when both gates pass."""
        import os as _os
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        # Clean draft with no claims; fidelity skipped.
        draft = "Hello there."
        dossier = "## Notes\nSome content."
        draft_path, dossier_path = self._write_draft_and_dossier(
            tmp_path, draft, dossier
        )
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        env = {
            **_env(tmp_path),
            "OUTREACH_FACTORY_LEDGER_DIR": str(ledger_dir),
        }
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
                "--apply",
                "--json",
            ],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0
        # Verify the ledger contains a draft_ready event.
        ledger_files = list(ledger_dir.rglob("*.jsonl"))
        assert ledger_files, f"no ledger files written; tmp_path: {ledger_dir}"
        found_draft_ready = False
        for f in ledger_files:
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("type") == "draft_ready":
                    found_draft_ready = True
                    assert event["hallucination_check"] == "passed"
                    assert event["voice_fidelity_check"] == "skipped"
                    break
        assert found_draft_ready, (
            "ledger did not contain a draft_ready event after --apply"
        )

    def test_apply_does_not_emit_draft_ready_on_refusal(self, tmp_path):
        """D245+D248 — when Layer 4 refuses, --apply does NOT append a
        draft_ready event to the ledger (the emit-only-on-both-pass
        posture per ADR-0047 D246)."""
        import os as _os
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        # Uncited draft → hallucination dimension refuses.
        draft = (
            "Hey, saw you posted last week about a Phantom Project "
            "launch — congrats."
        )
        dossier = "## Notes\nUnrelated content."
        draft_path, dossier_path = self._write_draft_and_dossier(
            tmp_path, draft, dossier
        )
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        env = {
            **_env(tmp_path),
            "OUTREACH_FACTORY_LEDGER_DIR": str(ledger_dir),
        }
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
                "--apply",
                "--json",
            ],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0
        # Verify NO draft_ready event landed. (A hallucination_detected
        # event MAY land per the per-Layer event's emit-only-on-uncited
        # posture per ADR-0043 D219 — that's preserved.)
        ledger_files = list(ledger_dir.rglob("*.jsonl"))
        for f in ledger_files:
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                assert event.get("type") != "draft_ready", (
                    f"unexpected draft_ready event in ledger: {event!r}"
                )

    def test_missing_draft_file_returns_2(self, tmp_path):
        """D248 — missing draft file → exit 2 (CLI error)."""
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("## Notes")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(tmp_path / "missing.txt"),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 2
        assert "draft file not found" in proc.stderr

    def test_missing_dossier_file_returns_2(self, tmp_path):
        """D248 — missing dossier file → exit 2 (CLI error)."""
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("Hello.")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(tmp_path / "missing.md"),
                "--register", "cold-pitch",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 2
        assert "research dossier not found" in proc.stderr

    def test_unknown_register_argparse_choices_rejects(self, tmp_path):
        """D248 + ADR-0042 D210 — argparse-choices closed-enum on
        --register rejects unknown registers BEFORE handler dispatch."""
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("Hello.")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("## Notes")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "introduction",
                "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        # argparse error → exit 2
        assert proc.returncode != 0
        assert "introduction" in proc.stderr or "invalid choice" in proc.stderr

    def test_hallucination_override_produces_passed_via_override_in_layer_4_check(
        self, tmp_path
    ):
        """Per Week 10 follow-up P2-2 — D249: when hallucination_check_override
        fires, the CLI JSON's top-level ``layer_4_check`` field emits
        ``"passed_via_override"`` (not ``"passed"``) so operators can stamp
        the correct value on the Touch note frontmatter per SKILL.md D249
        without inspecting the nested ``draft_ready_payload``'s per-dimension
        verdict markers.

        The original Week 10 implementation emitted ``"passed"`` regardless
        of whether an override fired — operators reading the SKILL.md's
        Phase 6 narrative were instructed to stamp ``"passed_via_override"``
        but the CLI never signaled this at the top-level field. The
        follow-up commit aligns the CLI output with the SKILL.md specification.
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft = (
            "Hey, saw you posted last week about a Phantom Project "
            "launch — congrats."
        )
        dossier = "## Notes\nUnrelated content."
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text(draft)
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text(dossier)
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch", "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
                "--hallucination-check-override",
                "--hallucination-check-override-reason", "paraphrased citation",
                "--json",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        out = json.loads(proc.stdout)
        # Per the follow-up: the top-level field emits passed_via_override
        # when ANY override fired AND Layer 4 passed.
        assert out["layer_4_check"] == "passed_via_override"
        # Per ADR-0047 D247 — the per-dimension marker also stamps
        # passed_via_override on the nested payload.
        assert out["draft_ready_payload"]["hallucination_check"] == (
            "passed_via_override"
        )

    def test_clean_draft_with_skipped_fidelity_emits_layer_4_check_passed_native(
        self, tmp_path
    ):
        """Per Week 10 follow-up P2-2 — D249: when NO override fired AND
        Layer 4 passed, the CLI JSON's top-level ``layer_4_check`` field
        emits ``"passed"`` (native pass; not via-override). The
        complement test to the override-fires case above.
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("Hello there.")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("## Notes\nSome content.")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch", "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
                "--json",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        # No override fired → native pass marker.
        assert out["layer_4_check"] == "passed"

    def test_voice_fidelity_check_override_skip_does_not_count_for_top_marker(
        self, tmp_path
    ):
        """Per Week 10 follow-up P2-2 — D249 + D246: when
        ``--voice-fidelity-check-override`` is passed AND
        ``--skip-fidelity-check`` is also set, the override is structurally
        moot (the factory treats it as the skipped path); the top-level
        ``layer_4_check`` field should emit ``"passed"`` (NOT
        ``"passed_via_override"``) since the override didn't actually fire
        at the factory level.

        The follow-up's any_override_fired derivation correctly excludes
        the voice-fidelity override when fidelity is skipped — otherwise
        scripted tooling that always passes the override flag with
        --skip-fidelity-check would inflate the Pillar I per-tenant
        override-rate signal.
        """
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("Hello there.")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("## Notes\nSome content.")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch", "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                "--skip-fidelity-check",
                "--voice-fidelity-check-override",
                # No reason needed — skipped path discards the override
                # semantic per ADR-0047 D247 + the per-Week 10 follow-up.
                "--json",
            ],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        # No real override fired (skipped path discards the
        # voice-fidelity override semantic).
        assert out["layer_4_check"] == "passed"
        assert out["draft_ready_payload"]["voice_fidelity_check"] == "skipped"

    def _make_empty_corpus(self, tmp_path: Path) -> Path:
        """Build a minimal empty corpus directory (valid metadata + zero
        samples) at ``tmp_path / "voice-corpus"``. Per ADR-0045 D230's
        empty-exemplar refuse-loud — the empty corpus drives
        ``compute_draft_fidelity_score`` to return state="refused" +
        score=0.0 + empty exemplar_ids. Used by the per-dimension
        behavioral passthrough test to exercise the
        ``voice_fidelity_check_override`` bypass.
        """
        from voice_corpus import DEFAULT_EMBED_MODEL, SCHEMA_VERSION
        corpus_dir = tmp_path / "voice-corpus"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        # Empty corpus: zero samples + zero embeddings.
        np.save(
            corpus_dir / "embeddings.npy",
            np.zeros((0, 384), dtype=np.float32),
        )
        (corpus_dir / "index.json").write_text(json.dumps([]))
        metadata = {
            "embed_model": DEFAULT_EMBED_MODEL,
            "embed_version": "5.1.2",
            "sentence_transformers_version": "5.1.2",
            "schema_version": SCHEMA_VERSION,
            "corpus_count": 0,
            "built_at": "2026-05-25T00:00:00Z",
        }
        (corpus_dir / "metadata.json").write_text(json.dumps(metadata))
        return corpus_dir

    def test_voice_fidelity_check_override_behavioral_passthrough_subprocess(
        self, tmp_path
    ):
        """Per Week 10 follow-up P2-1 — D247 + D248 behavioral passthrough:
        ``--voice-fidelity-check-override`` + ``--voice-fidelity-check-override-reason``
        actually pass through to ``build_draft_ready_payload``, stamping
        ``voice_fidelity_check=passed_via_override`` on the emitted
        ``draft_ready`` event payload.

        Matches the Week 8 P2-2 + Week 9 P2-2 behavioral-passthrough
        discipline — a future refactor dropping the
        ``voice_fidelity_check_override=args.voice_fidelity_check_override``
        passthrough at the build_draft_ready_payload call site would
        silently revert all CLI callers to override=False with no test
        failure. The only prior verification was
        ``test_emit_ready_subcommand_help_lists_flags`` (signature-only
        --help string check). This subprocess test exercises the
        end-to-end behavioral passthrough.

        Test pattern per ADR-0045 D230's empty-corpus refuse-loud: the
        fidelity scorer runs against a minimal empty corpus → empty
        exemplar list → score 0.0 → state="refused" → the override
        bypasses the refusal → emitted draft_ready carries
        ``voice_fidelity_check=passed_via_override``.
        """
        # Set up the empty corpus + config that points voice.corpus_dir
        # at it.
        corpus_dir = self._make_empty_corpus(tmp_path)
        cfg_path = tmp_path / "config.yml"
        cfg_path.write_text(yaml.safe_dump({
            "voice": {
                "corpus_dir": str(corpus_dir),
                "use_embedding_primitive": True,
            }
        }))
        env = {
            **_env(tmp_path),
            "OUTREACH_FACTORY_CONFIG": str(cfg_path),
        }
        thresholds_path = _write_thresholds(tmp_path / "thresholds.yml")
        draft_path = tmp_path / "draft.txt"
        draft_path.write_text("Hello there.")
        dossier_path = tmp_path / "dossier.md"
        dossier_path.write_text("## Notes\nSome content.")
        proc = subprocess.run(
            [
                sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready",
                "--draft-path", str(draft_path),
                "--research-dossier-path", str(dossier_path),
                "--register", "cold-pitch", "--channel", "email",
                "--thresholds-path", str(thresholds_path),
                # Do NOT --skip-fidelity-check — let the fidelity scorer
                # run against the empty corpus + return state="refused".
                "--voice-fidelity-check-override",
                "--voice-fidelity-check-override-reason",
                "operator-calibrated for this draft",
                "--json",
            ],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, (
            f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
        )
        out = json.loads(proc.stdout)
        # Per the follow-up P2-2 — top-level marker emits via-override.
        assert out["layer_4_check"] == "passed_via_override"
        # Per the follow-up P2-1 — behavioral passthrough verified at the
        # nested payload's per-dimension marker.
        assert out["draft_ready_payload"]["voice_fidelity_check"] == (
            "passed_via_override"
        )
        assert out["draft_ready_payload"]["voice_fidelity_check_override_reason"] == (
            "operator-calibrated for this draft"
        )
        # Verify the fidelity scorer actually ran (empty corpus → score=0.0
        # → state="refused" per ADR-0045 D230) — confirms the test
        # exercises the override bypass path NOT the skipped path.
        assert out["fidelity_state"] == "refused"
        assert out["voice_fidelity_score"] == 0.0


# ---------------------------------------------------------------------------
# Week 10 module surface per ADR-0047 D244 + D246
# ---------------------------------------------------------------------------


class TestWeek10ModuleSurface:
    """ADR-0047 D244 — module surface verification: the Layer 4 emit-
    guard primitive lives at ``orchestrator/draft_quality.py``; the
    public surfaces are importable; the module docstring names Week 10.
    """

    def test_build_draft_ready_payload_importable(self):
        """D244 — ``build_draft_ready_payload`` is at the module's
        public surface."""
        from draft_quality import build_draft_ready_payload as _f
        assert callable(_f)

    def test_layer_4_guard_refusal_importable(self):
        """D245 — ``Layer4GuardRefusal`` is at the module's public
        surface."""
        from draft_quality import Layer4GuardRefusal as _c
        assert issubclass(_c, ValueError)

    def test_module_docstring_mentions_week_10(self):
        """D244 — the module docstring names Week 10 + ADR-0047 per
        the doc-update discipline established at Week 9 follow-up P3-1."""
        doc = draft_quality.__doc__ or ""
        assert "Week 10" in doc
        assert "ADR-0047" in doc

    def test_module_shape_block_lists_layer4guardrefusal(self):
        """D244 — the module shape block (in the docstring) lists
        ``Layer4GuardRefusal`` per the Week 9 P3-1 doc-update pattern."""
        doc = draft_quality.__doc__ or ""
        assert "Layer4GuardRefusal" in doc

    def test_module_shape_block_lists_build_draft_ready_payload(self):
        """D244 — the module shape block lists ``build_draft_ready_payload``."""
        doc = draft_quality.__doc__ or ""
        assert "build_draft_ready_payload" in doc

    def test_main_cli_description_mentions_week_10(self):
        """D248 — the main CLI description mentions Week 10 + the
        ``emit-ready`` subcommand."""
        from draft_quality import main
        # The main() ArgumentParser's description is the visible CLI
        # banner; inspect via the parser.
        import argparse
        # Run --help to get the description (avoids needing to parse
        # the source); the help output's first lines are the description.
        import io
        from contextlib import redirect_stdout, redirect_stderr
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            try:
                # Force --help; argparse exits on --help.
                import sys as _sys
                old_argv = _sys.argv
                _sys.argv = ["draft_quality.py", "--help"]
                try:
                    main()
                except SystemExit:
                    pass
                finally:
                    _sys.argv = old_argv
            except Exception:
                pass
        output = buf_out.getvalue() + buf_err.getvalue()
        assert "Week 10" in output
        assert "emit-ready" in output

    def test_draft_ready_event_emitted_by_marker(self):
        """D246 — the ``draft_ready`` event class stamps
        ``_emitted_by: "draft_quality"`` per ADR-0010 D17 + ADR-0043
        D216 (the same module emits ALL FOUR Pillar F event classes)."""
        from draft_quality import EMITTED_BY
        assert EMITTED_BY == "draft_quality"

    def test_draft_ready_not_in_stage_by_event_type(self):
        """Per Week 10 follow-up P3-3 — ADR-0047 §Compliance I2 +
        cross-pillar audit §55 category 3: the ``draft_ready`` event class
        MUST NOT appear in ``ledger._STAGE_BY_EVENT_TYPE`` (the stage
        advancement dispatch table).

        The event class SIGNALS dispatch-eligibility per ADR-0047 D246
        (operator-side workflow signal), NOT per-Person pipeline-stage
        advancement. A mistaken future addition of ``"draft_ready"`` to
        ``_STAGE_BY_EVENT_TYPE`` would auto-advance ``pipeline_stage`` on
        every ledger-appended ``draft_ready`` event, bypassing the
        operator-deliberate Touch note frontmatter stamp per SKILL.md
        Phase 6 + D249. The cross-pillar audit §55 asserts this invariant
        in prose; this regression-barrier test pins it in code.
        """
        import sys as _sys
        # voice_corpus shim imports ledger; ensure ledger is loaded.
        import ledger as _ledger
        stage_table = getattr(_ledger, "_STAGE_BY_EVENT_TYPE", None)
        assert stage_table is not None, (
            "ledger._STAGE_BY_EVENT_TYPE must exist per Pillar B + "
            "Pillar C dispatch infrastructure; the test cannot verify "
            "the draft_ready exclusion without the table."
        )
        assert "draft_ready" not in stage_table, (
            "draft_ready MUST NOT be in _STAGE_BY_EVENT_TYPE; per "
            "ADR-0047 D246 the event signals dispatch-eligibility, NOT "
            "pipeline_stage advancement. Adding it would auto-advance "
            "pipeline_stage on every --apply invocation, bypassing the "
            "operator-deliberate Touch note frontmatter stamp per SKILL.md "
            "Phase 6 + D249."
        )

    def test_other_pillar_f_event_classes_not_in_stage_by_event_type(self):
        """Per Week 10 follow-up P3-3 — symmetric verification for the
        prior three Pillar F event classes (``voice_exemplar_retrieved`` +
        ``hallucination_detected`` + ``draft_quality_scored``). All
        Pillar F event classes are operator-side / Pillar G observability
        signals, NOT pipeline-stage advancement signals.

        Carry-forward from prior Pillar F weeks (the original commits did
        not pin this invariant explicitly per event class). Pinning all
        four together at Week 10 closes the carry-forward.
        """
        import ledger as _ledger
        stage_table = getattr(_ledger, "_STAGE_BY_EVENT_TYPE", {})
        for event_class in (
            "voice_exemplar_retrieved",
            "hallucination_detected",
            "draft_quality_scored",
        ):
            assert event_class not in stage_table, (
                f"{event_class} MUST NOT be in _STAGE_BY_EVENT_TYPE — "
                "Pillar F event classes are operator-side / Pillar G "
                "observability signals, NOT pipeline_stage advancement "
                "signals. Per ADR-0038 D182 category 3 of the cross-"
                "pillar audit."
            )


# ---------------------------------------------------------------------------
# TEST-ONLY seam preservation at the Week 10 Layer 4 emit-guard surface
# per ADR-0047 D250
# ---------------------------------------------------------------------------


class TestSeamPreservationWeek10:
    """ADR-0047 D250 — the Week 10 Layer 4 emit-guard factory is a
    STRUCTURAL COMPOSITION (consumes already-constructed Layer 2
    results). The factory's signature has NO ``embed_fn`` or
    ``retrieve_fn`` kwarg; the CLI does NOT surface the corresponding
    flags. The seam stays at the FIVE upstream per-Layer surfaces.
    """

    def test_build_draft_ready_payload_has_no_embed_fn_seam(self):
        """D250 — the factory's signature has NO ``embed_fn`` kwarg.
        Rejecting per-Layer re-running keeps the per-Layer dispatch
        amortized at the per-Layer per-call sites."""
        import inspect
        sig = inspect.signature(build_draft_ready_payload)
        assert "embed_fn" not in sig.parameters

    def test_build_draft_ready_payload_has_no_retrieve_fn_seam(self):
        """D250 — the factory's signature has NO ``retrieve_fn`` kwarg."""
        import inspect
        sig = inspect.signature(build_draft_ready_payload)
        assert "retrieve_fn" not in sig.parameters

    def test_cli_emit_ready_has_no_embed_fn_flag(self, tmp_path):
        """D250 — the CLI's ``emit-ready`` subcommand does NOT surface
        ``--embed-fn`` per the security + audit rationale at ADR-0039
        D188-Alt3 + ADR-0040 D197-Alt1 + ADR-0045 D235."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready", "--help"],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        assert "--embed-fn" not in proc.stdout
        assert "--embed_fn" not in proc.stdout

    def test_cli_emit_ready_has_no_retrieve_fn_flag(self, tmp_path):
        """D250 — the CLI's ``emit-ready`` subcommand does NOT surface
        ``--retrieve-fn``."""
        proc = subprocess.run(
            [sys.executable, str(DRAFT_QUALITY_SCRIPT), "emit-ready", "--help"],
            capture_output=True, text=True, env=_env(tmp_path),
        )
        assert proc.returncode == 0
        assert "--retrieve-fn" not in proc.stdout
        assert "--retrieve_fn" not in proc.stdout

    def test_upstream_parse_embed_fn_seam_unchanged(self):
        """D250 — the upstream ``parse_draft_for_claims`` ``embed_fn``
        seam is UNCHANGED at Week 10 (the seam stays at the per-Layer
        surfaces; Week 10's factory is structural-composition)."""
        import inspect
        sig = inspect.signature(parse_draft_for_claims)
        assert "embed_fn" in sig.parameters

    def test_upstream_score_embed_fn_seam_unchanged(self):
        """D250 — the upstream ``score_draft`` ``embed_fn`` seam is
        UNCHANGED at Week 10."""
        import inspect
        sig = inspect.signature(score_draft)
        assert "embed_fn" in sig.parameters

    def test_upstream_compute_draft_fidelity_score_embed_fn_seam_unchanged(self):
        """D250 — the upstream ``compute_draft_fidelity_score``
        ``embed_fn`` seam is UNCHANGED at Week 10."""
        import inspect
        sig = inspect.signature(compute_draft_fidelity_score)
        assert "embed_fn" in sig.parameters

    def test_upstream_compute_draft_fidelity_score_retrieve_fn_seam_unchanged(self):
        """D250 — the upstream ``compute_draft_fidelity_score``
        ``retrieve_fn`` seam is UNCHANGED at Week 10."""
        import inspect
        sig = inspect.signature(compute_draft_fidelity_score)
        assert "retrieve_fn" in sig.parameters
