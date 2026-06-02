"""Pillar E Week 6-8 — tier auto-assignment primitive.

Per ADR-0032 D145 (Pillar E foundation) + ADR-0035 D160-D165 (Pillar E
Week 6-8). The tier-assignment primitive derives a SUGGESTED
``research_tier`` from per-Person firmographic + intent signals
(Apollo ``organization_size`` / ``industry`` / ``funding_stage`` +
``discovery_lineage.source_skill`` + ``find-funded-founders``-specific
``round_stage`` / ``funding_date``) per an operator-tunable YAML
weights config. The suggestion is OBSERVATIONAL — the operator-
stamped ``Person.research_tier`` field remains the SoT per
ADR-0007's existing convention + ADR-0032 D145's three-step
decoupling:

  1. **Auto-assignment SUPPLIES** the suggestion via the
     ``tier_suggested`` event (this module).
  2. **Operator STAMPS** the tier via ``Person.research_tier``
     frontmatter (existing per-Person workflow; unchanged) OR via
     ``manual_override`` per ADR-0007 (existing event class).
  3. **Policy rule READS** the stamped value via ``ctx.tier``
     (Pillar A's existing ``TierRequiresTierInRule``; unchanged).

The primitive REPLACES nothing — it ADDS the suggestion surface
without affecting the existing tier-stamping workflow. Operators
disagreeing with a suggestion stamp the tier they want; the rule
reads the operator-stamped value.

Module shape (ADR-0035 D160 — sibling-of-discovery_dedup.py +
sibling-of-email_verification_cache.py placement):
  * :class:`TierSuggestion` — frozen dataclass; the outcome of a
    per-Person tier computation. Carries
    ``suggested_tier`` ∈ ``SUGGESTED_TIERS`` + ``signals_consulted``
    dict (operator-visible coverage) + ``rationale`` string
    (operator-readable explanation) + ``person_id`` + derived
    ``score`` (the running sum of per-signal weights).
  * :func:`compute_tier_from_signals` — the per-Person entry point.
    Reads firmographic + intent signals from the supplied frontmatter
    dict; computes the score per the weights config; emits a
    :class:`TierSuggestion` with the threshold-matched tier.
    Graceful-degradation per ADR-0035 D162: missing signals
    contribute ZERO (NOT a penalty); the default-low B tier is the
    floor when signals are insufficient.
  * :func:`build_tier_suggested_payload` — emit-shape factory for
    ``tier_suggested`` events per ADR-0035 D161 + ADR-0032 D146's
    channel-on-every-event invariant extension
    (``channel: "none"`` since tier is channel-agnostic; mirrors
    the dedup primitive's stamp).
  * :func:`load_weights` — YAML config loader. Operator's
    config at ``~/.outreach-factory/tier_weights.yml`` (the
    DEFAULT_TIER_WEIGHTS_PATH); falls back to the default-shipped
    template at ``config-template/tier_weights.example.yml`` with
    stderr warning when the operator's config is absent.
  * :data:`DEFAULT_TIER_WEIGHTS_PATH` — the operator-tunable
    weights config path.
  * :data:`SUGGESTED_TIERS` — frozen set of valid tier values
    (``{"S", "A", "B"}``) per ADR-0035 D161's closed enum.

Per-Person-invocation integration (ADR-0035 D164 — operator-invoked
CLI):
  The primitive is OPERATOR-INVOKED via the CLI; auto-invocation on
  every ``enroll_person`` write is deferred to Pillar I OR a future
  Pillar E week IF operator demand materializes. The operator-
  invocation surface preserves the OPERATOR-CONTROL property per
  ADR-0032 D145.

CLI (mirrors :mod:`discovery_dedup` + :mod:`email_verification_cache`):

    python tier_assignment.py suggest --person <id> \\
                                      [--weights-path <path>] \\
                                      [--apply] [--json]

The ``--apply`` flag controls whether the ``tier_suggested`` event
is appended to the ledger (live mode) or just reported (dry-run
mode — the default). The dry-run default mirrors :mod:`policy`'s
``simulate`` posture: read-only by default; explicit opt-in for
state-mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

import ledger as _ledger
from observability import traced_stage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Per ADR-0035 D161 — the closed enum of valid suggested tier values.
# Matches the Outreach Tier Playbook convention + the existing
# operator-stamped ``Person.research_tier`` values (S | A | B). Future
# tier schemes (e.g., P1/P2/P3) would extend the enum + require a
# coordinated ADR amendment.
SUGGESTED_TIERS: frozenset[str] = frozenset({"S", "A", "B"})


# Per ADR-0035 D163 — the operator-tunable weights config path.
# Operators copy from ``config-template/tier_weights.example.yml`` +
# tune as their corpus grows. The framework treats the file as an
# opaque dict; YAML-load errors fail loud at primitive-invocation
# time.
DEFAULT_TIER_WEIGHTS_PATH: Path = (
    Path.home() / ".outreach-factory" / "tier_weights.yml"
)


# The default-shipped weights template path — the fallback when the
# operator's config is absent. Lives at the repo root's
# ``config-template/`` (sibling of other operator-tunable YAML
# templates like ``cooldowns.example.yml``).
def _default_template_path() -> Path:
    """Return the path to the default-shipped weights template.

    Resolved relative to this module's location so the path works
    whether the framework is installed via clone (the default for
    the reference operator's bootstrap) or via a future PyPI distribution.
    """
    # orchestrator/tier_assignment.py → orchestrator/ → repo root → config-template/
    return Path(__file__).resolve().parent.parent / "config-template" / "tier_weights.example.yml"


# Per ADR-0010 D17 — every Pillar E event carries an ``_emitted_by``
# marker for operator-facing filterability. The tier primitive's
# marker is reserved here as the single source of truth (consumed
# by :func:`build_tier_suggested_payload` + the cross-pillar surface
# audit's literal-string predicate).
EMITTED_BY: str = "tier_assignment"


# Per ADR-0032 D146 + ADR-0014 D33 — the tier primitive's events
# carry ``channel: "none"`` because tier is channel-agnostic (tier
# applies across all channels — email, LinkedIn, Twitter, calendar
# booking — the operator decides per-channel routing separately).
# MIRRORS the dedup primitive's stamp per ADR-0033 D150; CONTRASTS
# with the cache primitive's ``channel: "email"`` per ADR-0034 D155.
# The asymmetry IS by design per ADR-0035 D161.
CHANNEL_VALUE: str = "none"


# Internal — the canonical source-skill enum per ADR-0032 D142.
# Frozen at five values; the Week 9-11 per-skill stamping refactor
# enforces enum-validation at construction time per the
# ``orchestrator/discovery_lineage.py`` module that ADR-0036+ ships.
# Week 6-8 (this module) accepts whatever the operator's frontmatter
# carries + normalizes legacy ``source_channel`` values to the
# canonical enum.
_CANONICAL_SOURCE_SKILLS: frozenset[str] = frozenset({
    "find-leads",
    "find-funded-founders",
    "competitor-customers",
    "research-prospect",
    "manual",
})


# Legacy ``source_channel`` value normalization is owned by the
# discovery-lineage primitive's canonical mapping per ADR-0036 D167.
# Pre-Pillar-E-Week-9-11 Person notes stamp ``source_channel:`` from
# the discovery skill (per ``find-leads/SKILL.md`` Phase 4.5 + others);
# the canonical field is ``discovery_lineage.source_skill``. The tier
# primitive's legacy-fallback path consumes the same mapping the vault
# migration + the ledger migration use — preserves the single-source-
# of-truth contract per ADR-0036 D167. Week 9-11 review P2-C migrated
# the local copy out of this module; future legacy variants (operator
# typos surfacing in production) land via one ADR amendment to the
# canonical map + one wave of consumers updating at the same time.
from discovery_lineage import normalize_legacy_source_to_skill


# Legacy ``round_stage`` value normalization map. ``find-funded-founders``
# stamps human-readable round stages (per ``find-funded-founders/
# SKILL.md`` enrollment template: ``pre-seed | seed | Series A |
# unknown``); the canonical ``funding_stage`` field (per ADR-0032 D145)
# uses snake_case lower-case enum values. This map normalizes the
# legacy values to the canonical enum for the weights lookup.
_LEGACY_ROUND_STAGE_NORMALIZATION: dict[str, str] = {
    "pre-seed":     "pre_seed",
    "seed":         "seed",
    "series a":     "series_a",
    "series b":     "series_b",
    "series c":     "series_c_plus",
    "series c+":    "series_c_plus",
    "series d":     "series_c_plus",
    "series e":     "series_c_plus",
    "unknown":      None,
}


# Markdown frontmatter regex — matches the leading YAML frontmatter
# block in a Person note. Mirrors the convention used elsewhere in
# the orchestrator (e.g., ``identity._parse_frontmatter``).
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


# ---------------------------------------------------------------------------
# TierSuggestion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierSuggestion:
    """Outcome of a per-Person tier auto-assignment computation per ADR-0035 D161.

    The dataclass is frozen + has no internal mutability so a single
    :class:`TierSuggestion` can be passed across the
    :func:`compute_tier_from_signals` + :func:`build_tier_suggested_payload`
    boundary without copying.

    Fields:

    * :attr:`suggested_tier` — one of :data:`SUGGESTED_TIERS`
      (``"S" | "A" | "B"``) per the closed enum. Construction-time
      validation refuses unknown values loudly (a typo'd weights
      config that emits a non-enum tier surfaces as ValueError).

    * :attr:`person_id` — the Person whose tier was suggested.
      Always populated by :func:`compute_tier_from_signals`'s
      caller (the CLI's ``--person`` arg or a future per-skill
      auto-invocation site).

    * :attr:`signals_consulted` — dict of every signal the primitive
      READ from the Person frontmatter, with the value found (or
      ``None`` if absent). Operator-deliberate: surfaces "what's
      the framework not seeing?" via the ``None`` values for missing
      signals (useful for operator audit + future enrichment
      prioritization per ADR-0035 D161).

    * :attr:`rationale` — operator-readable explanation string
      composed from the signals + their weight contributions.
      Format: ``"<signals> → score <N> → <tier-category> <tier>
      tier"``. The arrow (``→``) separator is operator-deliberate
      so a ``grep -P '→ high-intent'`` filter surfaces all
      high-intent suggestions in a corpus.

    * :attr:`score` — the running sum of per-signal weight
      contributions. Useful for operator audit + future weights
      calibration. Operator-tunable: future weights configs may
      bias toward higher scores (e.g., to emit more S-tier
      suggestions) without changing the algorithm.
    """

    suggested_tier: str
    person_id: str
    signals_consulted: dict
    rationale: str
    score: int

    def __post_init__(self) -> None:
        if self.suggested_tier not in SUGGESTED_TIERS:
            raise ValueError(
                f"TierSuggestion.suggested_tier must be one of "
                f"{sorted(SUGGESTED_TIERS)}; got {self.suggested_tier!r}. "
                "A weights config that produces a non-enum tier value "
                "indicates a typo'd ``thresholds:`` block; check that "
                "the threshold names match the enum exactly "
                "(case-sensitive)."
            )
        if not self.person_id:
            raise ValueError(
                "TierSuggestion requires a non-empty person_id (the "
                "Person whose tier was suggested)."
            )
        if not isinstance(self.signals_consulted, dict):
            raise ValueError(
                "TierSuggestion.signals_consulted must be a dict; got "
                f"{type(self.signals_consulted).__name__}."
            )


# ---------------------------------------------------------------------------
# Weights config loading
# ---------------------------------------------------------------------------


def load_weights(weights_path: Path | None = None) -> dict:
    """Load the per-signal weights YAML config per ADR-0035 D163.

    The operator's config lives at :data:`DEFAULT_TIER_WEIGHTS_PATH`
    (``~/.outreach-factory/tier_weights.yml``). When the operator's
    config is absent, falls back to the default-shipped template at
    ``config-template/tier_weights.example.yml`` (with stderr
    warning per ADR-0035 D164's operator-readable diagnostic
    discipline).

    Args:
        weights_path: Override the default config path. ``None``
            resolves to :data:`DEFAULT_TIER_WEIGHTS_PATH`. The
            override surface is for test injection + the CLI's
            ``--weights-path`` flag.

    Returns:
        The parsed weights dict. Shape per
        ``config-template/tier_weights.example.yml``: a top-level
        dict with ``signals:`` (per-signal-name → per-value-name →
        weight) + ``thresholds:`` (tier-name → minimum score).

    Raises:
        FileNotFoundError: if neither the operator's config NOR the
            default template exists (the framework is broken — the
            default template is required to ship with every clone).
        yaml.YAMLError: if either config is malformed (fail-loud per
            the operator-readable diagnostic discipline).
        ValueError: if the loaded config lacks required top-level
            keys (``signals:`` + ``thresholds:``).
    """
    if weights_path is None:
        weights_path = DEFAULT_TIER_WEIGHTS_PATH

    if not weights_path.exists():
        template_path = _default_template_path()
        if not template_path.exists():
            raise FileNotFoundError(
                f"Neither the operator's weights config at "
                f"{weights_path} NOR the default-shipped template at "
                f"{template_path} exists. The framework is broken — "
                "the default template should ship with every clone. "
                "Check that the repository is intact + "
                "``config-template/tier_weights.example.yml`` exists."
            )
        sys.stderr.write(
            f"WARNING: operator-tuned weights not found at "
            f"{weights_path}; falling back to default template at "
            f"{template_path}. Copy the template to {weights_path} "
            "and tune as your corpus grows.\n"
        )
        weights_path = template_path

    with weights_path.open() as f:
        weights = yaml.safe_load(f) or {}

    if not isinstance(weights, dict):
        raise ValueError(
            f"Weights config at {weights_path} must be a top-level "
            f"dict; got {type(weights).__name__}. Check the YAML "
            "structure against config-template/tier_weights.example.yml."
        )
    if "signals" not in weights or not isinstance(weights["signals"], dict):
        raise ValueError(
            f"Weights config at {weights_path} must have a top-level "
            "``signals:`` dict. Check the YAML structure against "
            "config-template/tier_weights.example.yml."
        )
    if "thresholds" not in weights or not isinstance(weights["thresholds"], dict):
        raise ValueError(
            f"Weights config at {weights_path} must have a top-level "
            "``thresholds:`` dict. Check the YAML structure against "
            "config-template/tier_weights.example.yml."
        )

    # Per Week 6-8 follow-up P3-E: validate that each threshold value
    # is coercible to int. A non-numeric threshold (e.g., ``S: four``)
    # would otherwise produce an unguarded Python ValueError deep
    # inside _match_tier at primitive-invocation time, with a
    # traceback that surfaces a Python internal rather than an
    # operator-readable diagnostic naming the offending key + the
    # path to fix.
    for tier_name, threshold in weights["thresholds"].items():
        try:
            int(threshold)
        except (ValueError, TypeError):
            raise ValueError(
                f"Weights config at {weights_path}: thresholds[{tier_name!r}] "
                f"= {threshold!r} is not a valid integer. Check the YAML "
                "structure against config-template/tier_weights.example.yml."
            )

    return weights


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------


def _extract_signals(
    frontmatter: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Extract per-signal values from a Person frontmatter dict.

    Per ADR-0035 D162 — reads firmographic + intent signals from the
    Person frontmatter directly; gracefully degrades when signals are
    absent (returns ``None`` for missing signals).

    Signals extracted:

    * ``organization_size`` — Apollo enrichment's company size bucket.
      Today typically absent; future Apollo integration populates.
    * ``industry`` — Apollo enrichment's industry bucket. Today
      typically absent.
    * ``funding_stage`` — Apollo enrichment's funding stage. Today
      typically absent; falls back to normalizing ``round_stage:``
      from ``find-funded-founders``'s SKILL.md template.
    * ``source_skill`` — discovery skill enum. Read from
      ``discovery_lineage.source_skill`` (Week 9-11 canonical) OR
      ``source_channel`` (legacy fallback; normalized via
      :func:`discovery_lineage.normalize_legacy_source_to_skill`).
    * ``funding_recency_days`` — integer days since funding_date.
      ``None`` if ``funding_date`` is absent.

    Args:
        frontmatter: The Person's parsed YAML frontmatter (the dict
            returned by ``yaml.safe_load`` on the note's frontmatter
            block).
        now: Wall-clock anchor for the funding-recency calculation.
            ``None`` defaults to ``datetime.now(timezone.utc)``.
            Test fixtures pin ``now`` for reproducibility per ADR-0031
            D136 deterministic-clock precedent.

    Returns:
        Dict of signal-name → signal-value (or ``None`` if absent).
        The dict's keys cover every signal the primitive checks;
        ``None`` values surface "what's absent" for operator audit
        per the ``signals_consulted`` event field shape.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    signals: dict = {}

    # Apollo firmographic signals — typically absent on pre-Pillar-I
    # Person notes. The graceful-degradation contract per D162
    # returns ``None`` for absent signals (NOT a default value —
    # absence is observed, not invented).
    signals["organization_size"] = _normalize_str(
        frontmatter.get("organization_size")
    )
    signals["industry"] = _normalize_str(frontmatter.get("industry"))

    # Funding stage: canonical ``funding_stage:`` field first; fall
    # back to find-funded-founders' ``round_stage:`` (per its
    # SKILL.md template) with normalization to the canonical enum.
    funding_stage_raw = _normalize_str(frontmatter.get("funding_stage"))
    if funding_stage_raw is None:
        round_stage_raw = _normalize_str(frontmatter.get("round_stage"))
        if round_stage_raw is not None:
            funding_stage_raw = _LEGACY_ROUND_STAGE_NORMALIZATION.get(
                round_stage_raw.lower(), funding_stage_raw,
            )
    signals["funding_stage"] = funding_stage_raw

    # Source skill: canonical ``discovery_lineage.source_skill`` first
    # (Week 9-11 stamping); fall back to legacy ``source_channel:``
    # (per find-leads + find-funded-founders + competitor-customers
    # SKILL.md enrollment templates) with normalization.
    source_skill_raw: str | None = None
    ik_block = frontmatter.get("identity_keys") or {}
    if isinstance(ik_block, dict):
        lineage = ik_block.get("discovery_lineage") or {}
        if isinstance(lineage, dict):
            source_skill_raw = _normalize_str(lineage.get("source_skill"))
    if source_skill_raw is None:
        legacy = _normalize_str(frontmatter.get("source_channel"))
        if legacy is not None:
            # Per Week 9-11 review P2-C — consume the canonical
            # normalization helper (the single source of truth per
            # ADR-0036 D167) instead of a local copy. Unknown legacy
            # values normalize to "manual" via the helper's floor
            # (the previous local copy's `.get(legacy, legacy)`
            # fall-through returned the raw uncanonical value, which
            # was then absent from _CANONICAL_SOURCE_SKILLS and
            # contributed zero to the tier score — silently dropping
            # the intent signal instead of normalizing it).
            source_skill_raw = normalize_legacy_source_to_skill(legacy)
    signals["source_skill"] = source_skill_raw

    # Funding-recency days: today's date - funding_date (None if
    # funding_date is absent, unparseable, OR in the future). Future
    # dates are treated as absent rather than clamped to 0 — a
    # not-yet-closed funding round (operator stamping an announced-but-
    # pending round) does NOT semantically qualify as "recent funding"
    # for the recency boost; the operator's eventual stamping of the
    # actual closing date triggers the boost at that point. Per Week 6-8
    # follow-up P2-A: clamping future dates to 0 caused the
    # "within 0 days" rationale + an inflated recency boost.
    funding_date_raw = frontmatter.get("funding_date")
    funding_recency_days: int | None = None
    if funding_date_raw is not None:
        funding_date_parsed = _parse_iso_date(funding_date_raw)
        if funding_date_parsed is not None:
            delta = now.date() - funding_date_parsed
            if delta.days >= 0:
                funding_recency_days = delta.days
    signals["funding_recency_days"] = funding_recency_days

    return signals


def _normalize_str(value: object) -> str | None:
    """Normalize a frontmatter value to a non-empty str (or None).

    Tolerates: ``None`` → ``None``; empty string → ``None``; trim
    whitespace; numeric values coerced via str(). Mirrors the
    convention used elsewhere in the orchestrator (e.g.,
    ``vault.py``'s string-cleaning helpers).
    """
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _parse_iso_date(value: object) -> date | None:
    """Parse an ISO date string (or ``date``/``datetime``) to a ``date``.

    The find-funded-founders enrollment template emits
    ``funding_date: <YYYY-MM-DD>`` as a YAML date literal (which
    PyYAML parses to ``datetime.date``). Some operator-stamped
    variants may carry a string. Both are tolerated; unparseable
    values return ``None``.
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Tier computation
# ---------------------------------------------------------------------------


def compute_tier_from_signals(
    person_id: str,
    frontmatter: dict,
    *,
    weights: dict | None = None,
    now: datetime | None = None,
) -> TierSuggestion:
    """Compute a tier suggestion for one Person per ADR-0035 D161-D162.

    The primitive READS firmographic + intent signals from the
    supplied frontmatter dict + computes a score per the weights
    config + returns a :class:`TierSuggestion` with the
    threshold-matched tier + operator-readable rationale.

    Args:
        person_id: The Person's identifier (the LinkedIn-derived
            slug per Phase 5.5 Week 1b OR the operator-stamped
            ``id:`` frontmatter field).
        frontmatter: The Person's parsed YAML frontmatter (the dict
            returned by ``yaml.safe_load`` on the note's frontmatter
            block). The primitive reads firmographic + intent
            signals via :func:`_extract_signals`.
        weights: Override the loaded weights config. ``None``
            triggers a standard :func:`load_weights` call. The
            override surface is for test injection + the CLI's
            ``--weights-path`` flag.
        now: Wall-clock anchor for the funding-recency calculation.
            ``None`` defaults to ``datetime.now(timezone.utc)``.
            Test fixtures pin ``now`` for reproducibility per ADR-0031
            D136 deterministic-clock precedent.

    Returns:
        :class:`TierSuggestion` carrying the suggested tier +
        signals_consulted + rationale + score. The caller inspects
        the suggestion + dispatches to
        :func:`build_tier_suggested_payload` (for event emission)
        OR prints the rationale (for operator review).

    Behavior:
        * Empty frontmatter → default-low tier B + rationale naming
          "no signals available."
        * Partial signals (some absent) → degraded score from
          available signals only; missing signals contribute ZERO
          (NOT a penalty per D162).
        * All signals present → full score per the weights config.
        * Score ≥ threshold[S] → S tier.
        * Score ≥ threshold[A] (but < threshold[S]) → A tier.
        * Score < threshold[A] → B tier (default-low floor per D162).

    Side effects: NONE. The primitive is read-only; the caller
    appends the ``tier_suggested`` event via
    :func:`build_tier_suggested_payload` + the caller's own ledger
    handle (per the cache primitive's same emit pattern).
    """
    # Per ADR-0055 D300 — wrap the body in an enrichment-stage span
    # so the per-Person tier-derivation surface is operator-visible
    # via the OTel tracing backend. The person_id attribute matches
    # the per-Person observability surface per ADR-0050 D277.
    with traced_stage(
        "enrichment", "compute_tier",
        attributes={"person_id": person_id},
    ):
        return _compute_tier_from_signals_inner(
            person_id, frontmatter, weights=weights, now=now,
        )


def _compute_tier_from_signals_inner(
    person_id: str,
    frontmatter: dict,
    *,
    weights: dict | None,
    now: datetime | None,
) -> TierSuggestion:
    """Internal body of :func:`compute_tier_from_signals` — wrapped
    by the public function with a ``traced_stage`` context per
    ADR-0055 D300. Splitting the body keeps the span wrapping
    cleanly delimited without indenting the existing logic.
    """
    if weights is None:
        weights = load_weights()

    signals = _extract_signals(frontmatter, now=now)
    signal_weights = weights.get("signals") or {}
    thresholds = weights.get("thresholds") or {}

    # Score computation — walk every signal + add its per-value
    # weight contribution.
    score = 0
    contributions: list[tuple[str, str, int]] = []  # (signal, value, weight)
    for signal_name, signal_value in signals.items():
        if signal_value is None:
            continue
        signal_weight_block = signal_weights.get(signal_name) or {}
        if not isinstance(signal_weight_block, dict):
            continue

        weight: int | None = None
        if signal_name == "funding_recency_days":
            # Recency signals are time-windowed — pick the smallest
            # window that contains the funding age + use its weight.
            # Per ADR-0035 D162: if ``funding_recency_days: { 30: 2,
            # 90: 1 }`` and funding was 25 days ago, use weight 2
            # (the 30-day bucket); if 60 days ago, use weight 1 (the
            # 90-day bucket); if 100 days ago, no boost.
            try:
                bucket_thresholds = sorted(
                    (int(k), int(v))
                    for k, v in signal_weight_block.items()
                )
            except (ValueError, TypeError):
                bucket_thresholds = []
            for bucket_days, bucket_weight in bucket_thresholds:
                if signal_value <= bucket_days:
                    weight = bucket_weight
                    break
        else:
            # Scalar signals — direct dict lookup on the value.
            raw_weight = signal_weight_block.get(str(signal_value))
            if raw_weight is not None:
                try:
                    weight = int(raw_weight)
                except (ValueError, TypeError):
                    weight = None

        if weight is not None:
            score += weight
            contributions.append((signal_name, str(signal_value), weight))

    # Threshold matching — pick the HIGHEST threshold the score
    # >=. The thresholds dict is operator-tunable per D163; the
    # default ships S=4, A=2. Below the lowest threshold, the tier
    # is the default-low B (per D162's graceful-degradation floor).
    suggested_tier = _match_tier(score, thresholds)

    # Rationale composition — operator-readable string per D161.
    rationale = _compose_rationale(
        contributions, signals, score, suggested_tier,
    )

    return TierSuggestion(
        suggested_tier=suggested_tier,
        person_id=person_id,
        signals_consulted=signals,
        rationale=rationale,
        score=score,
    )


def _match_tier(score: int, thresholds: dict) -> str:
    """Match a score against the thresholds dict; return the tier.

    Per ADR-0035 D162's graceful-degradation contract. The thresholds
    dict shape per ``config-template/tier_weights.example.yml``:
    ``{ "S": 4, "A": 2 }`` — tier S requires score >= 4; tier A
    requires score >= 2; below 2 → tier B (default-low floor).

    The default-low B is implicit (no ``B:`` key in the thresholds
    dict). Operators tuning the weights can override the floor by
    adding ``B: <int>`` to the thresholds, BUT the enum requires
    the tier value to be one of :data:`SUGGESTED_TIERS`; the floor
    behavior is preserved regardless.

    Args:
        score: The aggregated weight contribution.
        thresholds: The operator-tunable thresholds dict from the
            weights config.

    Returns:
        One of :data:`SUGGESTED_TIERS` (``"S" | "A" | "B"``).

    Raises:
        ValueError: if the thresholds dict produces a non-enum tier
            value. Operator-readable so the operator can fix the
            weights config (e.g., a typo'd ``"AA": 5`` would surface
            here).
    """
    # Walk thresholds in descending order; pick the first match.
    # Only consider enum-valid tier names — others are ignored
    # (the TierSuggestion post-init validates the final value).
    candidate_tiers = [
        (tier_name, int(threshold))
        for tier_name, threshold in thresholds.items()
        if tier_name in SUGGESTED_TIERS
    ]
    candidate_tiers.sort(key=lambda x: x[1], reverse=True)
    for tier_name, threshold in candidate_tiers:
        if score >= threshold:
            return tier_name
    # Below every threshold → default-low B (graceful-degradation
    # floor per D162).
    return "B"


def _compose_rationale(
    contributions: list[tuple[str, str, int]],
    signals: dict,
    score: int,
    suggested_tier: str,
) -> str:
    """Compose the operator-readable rationale string per ADR-0035 D161.

    Format: ``"<signals> → score <N> → <tier-category> <tier> tier"``.

    Examples:
      * ``"Series A + AI/ML industry + funded-founders source + recent
        funding (within 90 days) → score 7 → high-intent S tier"``
      * ``"Limited firmographic signals (organization_size/industry/
        funding_stage absent); intent signals only → score 0 →
        low-confidence B tier"``

    The arrow (``→``) separator is operator-deliberate so a
    ``grep -P '→ high-intent'`` filter surfaces all high-intent
    suggestions in a corpus.
    """
    # Tier category labels — operator-readable mapping from tier to
    # the prose qualifier. Per Week 6-8 follow-up P2-B: zero-weight
    # contributions (e.g., source_skill=manual with weight 0 in the
    # default config) do not constitute "moderate" corroboration; the
    # "moderate" label only applies when there are nonzero-weight
    # contributions that landed at B tier (e.g., a single +1 boost
    # that didn't reach the A threshold). Filtering zero-weight rows
    # from the category decision preserves the operator-readable
    # accuracy: "default-low" means no signal moved the score;
    # "moderate" means signals moved the score but not enough to
    # cross the A threshold.
    nonzero_contributions = [c for c in contributions if c[2] != 0]
    tier_category = {
        "S": "high-intent",
        "A": "mid-intent",
        "B": "low-confidence" if score < 0 else (
            "default-low" if not nonzero_contributions else "moderate"
        ),
    }[suggested_tier]

    # Identify missing firmographic signals (the operator-audit
    # surface per D162's graceful-degradation contract).
    firmographic_signals = ("organization_size", "industry", "funding_stage")
    missing_firmographic = [
        s for s in firmographic_signals if signals.get(s) is None
    ]

    # Build the signals-list prefix. Contributions are ordered by
    # the iteration order of ``_extract_signals`` (deterministic).
    signal_descriptors: list[str] = []
    for signal_name, signal_value, weight in contributions:
        desc = _humanize_contribution(signal_name, signal_value, weight)
        signal_descriptors.append(desc)

    if not signal_descriptors and missing_firmographic:
        prefix = (
            f"Limited firmographic signals "
            f"({'/'.join(missing_firmographic)} absent); no other "
            "signals available"
        )
    elif not signal_descriptors:
        prefix = "No signals available"
    elif missing_firmographic and suggested_tier == "B":
        # Partial signals with a B-tier outcome — surface the
        # missing firmographic signals so the operator knows the
        # tier is constrained by absent enrichment.
        prefix = (
            f"Limited firmographic signals "
            f"({'/'.join(missing_firmographic)} absent); "
            + " + ".join(signal_descriptors)
        )
    else:
        prefix = " + ".join(signal_descriptors)

    return f"{prefix} → score {score} → {tier_category} {suggested_tier} tier"


def _humanize_contribution(
    signal_name: str, signal_value: str, weight: int,
) -> str:
    """Render one signal contribution as operator-readable prose.

    Mapping rationale: operators reading the rationale string in the
    ledger see the prose form (e.g., "Series A funding") rather than
    the dict-key form (e.g., "funding_stage=series_a"). The mapping
    is operator-deliberate; future weeks may refine the wording
    based on operator feedback.
    """
    if signal_name == "funding_stage":
        # Render snake_case → human-readable.
        readable = {
            "pre_seed":      "Pre-seed funding",
            "seed":          "Seed funding",
            "series_a":      "Series A funding",
            "series_b":      "Series B funding",
            "series_c_plus": "Series C+ funding",
        }.get(signal_value, f"{signal_value} funding")
        return readable
    if signal_name == "industry":
        readable = {
            "ai_ml":     "AI/ML industry",
            "saas":      "SaaS industry",
            "dev_tools": "Dev-tools industry",
            "fintech":   "Fintech industry",
        }.get(signal_value, f"{signal_value} industry")
        return readable
    if signal_name == "organization_size":
        readable = {
            "small": "Small org (<50)",
            "mid":   "Mid-sized org (50-500)",
            "large": "Large org (>500)",
        }.get(signal_value, f"{signal_value} organization size")
        return readable
    if signal_name == "source_skill":
        # Show the skill name + a parenthetical category.
        category = {
            "find-funded-founders": "high-intent",
            "competitor-customers": "high-precision",
            "find-leads":           "ICP-fit",
            "research-prospect":    "deepening",
            "manual":               "operator-curated",
        }.get(signal_value, "")
        if category:
            return f"{signal_value} source ({category})"
        return f"{signal_value} source"
    if signal_name == "funding_recency_days":
        return f"Recent funding (within {signal_value} days)"
    # Fallback for unknown signals (forward-compatibility — a
    # future weights config may introduce a new signal).
    return f"{signal_name}={signal_value}"


# ---------------------------------------------------------------------------
# Event payload factory
# ---------------------------------------------------------------------------


def build_tier_suggested_payload(suggestion: TierSuggestion) -> dict:
    """Construct the ``tier_suggested`` event payload (no ledger append).

    Per ADR-0035 D161 + ADR-0032 D146. Single source of truth for
    the event shape — both the live-emit path (caller appends to
    ledger) and the dry-run / CLI path call this helper to avoid
    drift. Mirrors :func:`discovery_dedup.build_discovery_dedup_hit_payload`
    + :func:`email_verification_cache.build_email_verification_cache_hit_payload`
    (the Pillar E sibling primitives' build-then-append separation).

    Event shape (per ADR-0035 D161):

    .. code-block:: text

        type: tier_suggested
        person_id              (the Person whose tier was suggested)
        suggested_tier         (one of SUGGESTED_TIERS: S | A | B)
        signals_consulted      (dict — every signal the primitive checked,
                                with None for absent signals)
        rationale              (operator-readable explanation string)
        channel                ("none" per D146 channel-on-every-event invariant +
                                the tier primitive's channel-agnostic scope)
        _emitted_by            ("tier_assignment" per ADR-0010 D17 convention)

    The event REPLACES nothing — it is purely observational per
    ADR-0032 D145. The operator-stamped ``Person.research_tier``
    field remains the SoT.

    Args:
        suggestion: The :class:`TierSuggestion` returned by
            :func:`compute_tier_from_signals`.

    Returns:
        The event payload dict. Caller appends to ledger via
        ``led.append(payload)`` per the standard Pillar E pattern.
    """
    return {
        "type": "tier_suggested",
        "person_id": suggestion.person_id,
        "suggested_tier": suggestion.suggested_tier,
        "signals_consulted": dict(suggestion.signals_consulted),
        "rationale": suggestion.rationale,
        "channel": CHANNEL_VALUE,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# Internal — safe-append helper (mirrors discovery_dedup._safe_append +
# email_verification_cache._safe_append)
# ---------------------------------------------------------------------------


def _safe_append(led: "_ledger.Ledger", event: dict) -> None:
    """Best-effort ledger append — mirrors :func:`discovery_dedup._safe_append`.

    A ledger I/O failure must not block the suggestion (the
    ``tier_suggested`` event is the operator-visible signal; losing
    it loses one row of Pillar G observability, not the suggestion
    behavior itself). Print stderr warning + continue.

    Per ADR-0035 D165: each Pillar primitive owns its own emit error
    handling per ADR-0033 D149's pillar-primitive-as-sibling shape
    (don't cross-import).
    """
    try:
        led.append(event)
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write(
            f"WARNING: ledger append failed for {event.get('type')}: "
            f"{exc}\n"
        )


# ---------------------------------------------------------------------------
# CLI helpers — config + people-dir resolution + Person lookup
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    p = Path.home() / ".outreach-factory" / "config.yml"
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _vault_people_dir(cfg: dict) -> Path | None:
    v = cfg.get("vault") or {}
    vault_path = Path(os.path.expanduser(v.get("path") or ""))
    if not vault_path.exists():
        return None
    people_dir = vault_path / (v.get("people_dir") or "10 People")
    return people_dir if people_dir.exists() else None


def _ledger_dir() -> Path:
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _ledger.DEFAULT_LEDGER_DIR


def _parse_person_frontmatter(note_path: Path) -> dict | None:
    """Parse a Person note's YAML frontmatter to a dict.

    Returns ``None`` if the note lacks frontmatter, has malformed
    YAML, or isn't a Person note (``type != "person"``).
    """
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    if (fm.get("type") or "").strip() != "person":
        return None
    return fm


def _find_person_note_by_id(
    person_id: str, people_dir: Path,
) -> tuple[Path, dict] | None:
    """Find the Person note whose frontmatter ``id:`` matches person_id.

    Returns ``(note_path, frontmatter_dict)`` on hit OR ``None`` on
    miss. The walk is O(N) over the people_dir tree; at v1 scale
    (~500 Persons) the cost is sub-second.

    Falls back to filename-stem matching when ``id:`` is absent
    (legacy pre-backfill Person notes); the stem fallback mirrors
    the convention used by :func:`vault.find_person_note`.
    """
    target = person_id.strip()
    if not target:
        return None
    for note in people_dir.rglob("*.md"):
        fm = _parse_person_frontmatter(note)
        if fm is None:
            continue
        stamped_id = (fm.get("id") or "").strip()
        if stamped_id == target:
            return (note, fm)
    # Fallback: filename stem match (legacy pre-backfill).
    for note in people_dir.rglob(f"{target}.md"):
        fm = _parse_person_frontmatter(note)
        if fm is not None:
            return (note, fm)
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(
        description="Pillar E tier auto-assignment primitive (ADR-0035)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sg = sub.add_parser(
        "suggest",
        help=(
            "Compute a tier suggestion for a Person from firmographic + "
            "intent signals; optionally emit the tier_suggested event."
        ),
    )
    sg.add_argument(
        "--person", required=True,
        help="Person ID (the frontmatter 'id:' value OR the note's "
             "filename stem for legacy pre-backfill notes)",
    )
    sg.add_argument(
        "--weights-path", default=None,
        help=f"Override the weights config path (default: "
             f"{DEFAULT_TIER_WEIGHTS_PATH})",
    )
    sg.add_argument(
        "--apply", action="store_true",
        help="Append the tier_suggested event to the ledger. "
             "Default is dry-run (report only).",
    )
    sg.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "suggest":
        cfg = _load_config()
        people_dir = _vault_people_dir(cfg)
        if people_dir is None:
            out = {
                "ok": False,
                "reason": "vault.people_dir not resolvable",
            }
            print(json.dumps(out) if args.json else
                  f"ERROR: {out['reason']}", file=sys.stderr)
            sys.exit(2)

        found = _find_person_note_by_id(args.person, people_dir)
        if found is None:
            out = {
                "ok": False,
                "reason": f"Person not found by id={args.person!r} in "
                          f"{people_dir}",
            }
            print(json.dumps(out) if args.json else
                  f"ERROR: {out['reason']}", file=sys.stderr)
            sys.exit(2)

        note_path, frontmatter = found

        weights_path = (
            Path(os.path.expanduser(args.weights_path))
            if args.weights_path is not None else None
        )
        try:
            weights = load_weights(weights_path)
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            out = {
                "ok": False,
                "reason": f"Failed to load weights: {exc}",
            }
            print(json.dumps(out) if args.json else
                  f"ERROR: {out['reason']}", file=sys.stderr)
            sys.exit(2)

        suggestion = compute_tier_from_signals(
            args.person, frontmatter, weights=weights,
        )
        payload = build_tier_suggested_payload(suggestion)

        report: dict = {
            "ok": True,
            "person_id": suggestion.person_id,
            "note_path": str(note_path),
            "suggested_tier": suggestion.suggested_tier,
            "score": suggestion.score,
            "signals_consulted": suggestion.signals_consulted,
            "rationale": suggestion.rationale,
            "payload": payload,
        }

        if args.apply:
            led = _ledger.Ledger(_ledger_dir())
            _safe_append(led, payload)
            report["applied"] = True

        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"person_id:       {report['person_id']}")
            print(f"note_path:       {report['note_path']}")
            print(f"suggested_tier:  {report['suggested_tier']}")
            print(f"score:           {report['score']}")
            print(f"rationale:       {report['rationale']}")
            print("signals_consulted:")
            for sig_name, sig_value in report["signals_consulted"].items():
                print(f"  {sig_name}: {sig_value}")
            if report.get("applied"):
                print("  ledger event appended.")
            else:
                print("  (dry-run; pass --apply to emit the event to "
                      "the ledger.)")
        sys.exit(0)


if __name__ == "__main__":
    main()
