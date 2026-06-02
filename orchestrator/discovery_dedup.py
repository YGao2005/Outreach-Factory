"""Pillar E Week 2 — pre-enrichment dedup primitive.

Per ADR-0032 D143 (Pillar E foundation) + ADR-0033 D149-D153 (Pillar E
Week 2). Before any discovery skill calls Apollo / PDL / Reoon, it
consults this primitive: *"does any existing Person carry an
identity-key (email / linkedin / twitter / github) that matches THIS
candidate's pre-enrichment partial?"* If yes, the discovery skill
emits a ``discovery_dedup_hit`` event referencing the existing Person
and SKIPS the Apollo + PDL + Reoon call entirely. The cost-avoidance
IS the binding exit-criterion behavior per PILLAR-PLAN §2 Pillar E:
*"discovering the same person via three skills in one day consumes
one Apollo credit, one Reoon credit, zero duplicate enrollments."*

Pillar G Week 6 (ADR-0055 D300-D306) adds the per-stage OTel span
instrumentation at the :func:`check_dedup` call site via
:func:`observability.traced_stage` — operators tracing the discovery
flow see the dedup primitive as a named span in the per-stage trace.
The privacy invariant per ADR-0054 D297 holds — span attributes
EXCLUDE ``source_list`` / ``draft_body`` / body-shaped fields.

Module shape (ADR-0033 D149):
  * :class:`DedupResult` — frozen dataclass; the outcome of a per-
    candidate check. Three statuses: ``"not_duplicate"`` (proceed to
    enrichment), ``"duplicate"`` (skip enrichment; emit
    ``discovery_dedup_hit``), ``"conflict"`` (skip enrichment; emit
    ``discovery_dedup_conflict`` — the ambiguous-multi-match or
    distinct-LinkedIn-same-email path that ``identity.resolve_strict``
    refuses).
  * :func:`check_dedup` — the per-skill entry point. Reuses
    :func:`identity.find_matches` + :func:`identity.resolve_strict`
    unchanged (the dedup primitive is the FAST-PATH for the common
    pre-enrichment case; the resolver is the BACK-STOP for the
    post-enrichment concurrent-race case per D143's atomicity
    contract).
  * :func:`build_discovery_dedup_hit_payload` — emit-shape factory
    for ``discovery_dedup_hit`` events per ADR-0033 D150 + ADR-0032
    D146's channel-on-every-event invariant extension
    (``channel: "none"`` since dedup is channel-agnostic).
  * :func:`build_discovery_dedup_conflict_payload` — emit-shape
    factory for ``discovery_dedup_conflict`` events per ADR-0033
    D151. Mirrors the existing ``enrollment_conflict`` event shape
    (per :mod:`enrollment`) so operators encountering a dedup
    conflict + an enrollment conflict on the same candidate see
    matching diagnostic context.

Per-skill integration (ADR-0033 D152):
  Each discovery skill wraps its pre-enrichment partial in a
  :func:`check_dedup` call BEFORE the Apollo / PDL / Reoon spend.
  Week 2 ships the primitive + the integration in ``find-leads``
  (the most active skill); subsequent weeks integrate the other
  three (``find-funded-founders``, ``competitor-customers``,
  ``research-prospect``). The per-skill ``discovery_lineage:``
  stamping refactor (per ADR-0032 D142) lands Week 9-11; the dedup
  primitive does NOT depend on that refactor — it consults the
  EXISTING ``identity_keys:`` partial via :func:`identity.find_matches`.

CLI (mirrors :mod:`identity` + :mod:`enrollment`):

    python discovery_dedup.py check --linkedin <url> \\
                                    [--email <addr> ...] \\
                                    [--github <h>] [--twitter <h>] \\
                                    --source-skill <enum> \\
                                    [--source-list <str>] \\
                                    [--apply] [--json]

The ``--apply`` flag controls whether the ``discovery_dedup_hit`` /
``discovery_dedup_conflict`` event is appended to the ledger (live
mode) or just reported (dry-run mode — the default). The dry-run
default mirrors :mod:`policy`'s ``simulate`` posture: read-only by
default; explicit opt-in for state-mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import identity
import ledger as _ledger
from observability import traced_stage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Per ADR-0032 D142 + ADR-0036 D167 — the canonical closed-set enum of
# discovery skills. The canonical home moved from this module to
# ``orchestrator/discovery_lineage.py`` in Week 9-11; this module
# imports the name + re-exports it for back-compat with any consumer
# that references the dedup module's ``SOURCE_SKILLS`` name. Future
# additions to the enum coordinate via ``discovery_lineage.py`` per
# ADR-0036 D167.
from discovery_lineage import SOURCE_SKILLS  # noqa: E402


# Per ADR-0010 D17 — every Pillar E event carries an ``_emitted_by``
# marker for operator-facing filterability. The dedup primitive's
# marker is reserved here as the single source of truth (consumed by
# :func:`build_discovery_dedup_hit_payload` +
# :func:`build_discovery_dedup_conflict_payload` + the cross-pillar
# surface audit's literal-string predicate).
EMITTED_BY: str = "discovery_dedup"


# Per ADR-0032 D146 + ADR-0014 D33 — the dedup primitive's events
# carry ``channel: "none"`` because dedup is channel-agnostic (it
# operates over identity keys, not per-channel intents). A future
# Pillar G dashboard filtering by channel would silently exclude
# dedup-hits if the field were absent; the explicit ``"none"`` value
# makes the absence operator-visible.
CHANNEL_VALUE: str = "none"


# ---------------------------------------------------------------------------
# DedupResult
# ---------------------------------------------------------------------------


_RESULT_STATUSES: frozenset[str] = frozenset({
    "not_duplicate",
    "duplicate",
    "conflict",
})


@dataclass(frozen=True)
class DedupResult:
    """Outcome of a pre-enrichment dedup check per ADR-0033 D149.

    Three statuses + the data each carries:

    * ``"not_duplicate"`` — no existing Person intersects the
      candidate's identity keys. The caller proceeds with the Apollo
      / PDL / Reoon enrichment call as today. ``existing_person_id``
      / ``matched_classes`` / ``existing_match`` / ``conflict`` are
      all empty.

    * ``"duplicate"`` — exactly one existing Person matches per
      :func:`identity.resolve_strict` (the strict-policy "1
      confident match" path). The caller emits
      ``discovery_dedup_hit`` referencing :attr:`existing_person_id`
      + :attr:`matched_classes` + SKIPS the Apollo / PDL / Reoon
      call. :attr:`existing_match` carries the full
      :class:`identity.Match` for operator-readable diagnostic
      context (note path; matched values per class).

    * ``"conflict"`` — 2+ existing Persons match OR a sole
      single-class email match where the candidate's LinkedIn
      differs from the existing record's LinkedIn (the
      ``_is_ambiguous_single_class_email_match`` refinement per
      :mod:`identity`). The caller emits
      ``discovery_dedup_conflict`` + SKIPS the enrichment call.
      :attr:`conflict` carries the :class:`identity.Conflict` whose
      ``report_path`` points at the operator-visible YAML report
      that :func:`identity.resolve_strict` already wrote
      (filesystem side effect happens INSIDE the dedup call — same
      as the post-enrichment :mod:`enrollment` path).

    The dataclass is frozen + has no internal mutability so a single
    :class:`DedupResult` can be passed across the discovery-skill +
    event-payload-factory boundary without copying.
    """

    status: str
    candidate_partial: identity.IdentityKeys
    existing_person_id: str | None = None
    matched_classes: frozenset[str] = frozenset()
    existing_match: identity.Match | None = None
    conflict: identity.Conflict | None = None

    def __post_init__(self) -> None:
        if self.status not in _RESULT_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_RESULT_STATUSES)}; "
                f"got {self.status!r}"
            )
        if self.status == "duplicate" and self.existing_match is None:
            raise ValueError(
                "DedupResult(status='duplicate') requires existing_match "
                "(the identity.Match returned by resolve_strict)"
            )
        if self.status == "conflict" and self.conflict is None:
            raise ValueError(
                "DedupResult(status='conflict') requires conflict "
                "(the identity.Conflict returned by resolve_strict)"
            )

    @property
    def is_duplicate(self) -> bool:
        return self.status == "duplicate"

    @property
    def is_conflict(self) -> bool:
        return self.status == "conflict"

    @property
    def is_not_duplicate(self) -> bool:
        return self.status == "not_duplicate"

    @property
    def should_skip_enrichment(self) -> bool:
        """True when the caller MUST skip the Apollo / PDL / Reoon call.

        The cost-avoidance pin per ADR-0032 D143. ``True`` for both
        ``duplicate`` (a known existing Person — re-enriching wastes
        the credit) AND ``conflict`` (manual resolution required —
        enriching would mint a third record on the same identity
        key + compound the conflict).
        """
        return self.status in ("duplicate", "conflict")


# ---------------------------------------------------------------------------
# Config + people-dir resolution
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


def _default_conflicts_dir() -> Path:
    """Mirrors :func:`identity._default_conflicts_dir` + the enrollment
    side's conflicts directory choice. Kept out of the Obsidian-synced
    vault tree so report files don't trigger Obsidian Sync conflict-
    suffix duplication."""
    return Path.home() / ".outreach-factory" / "conflicts"


def _ledger_dir() -> Path:
    env = os.environ.get("OUTREACH_FACTORY_LEDGER_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return _ledger.DEFAULT_LEDGER_DIR


# ---------------------------------------------------------------------------
# The dedup primitive
# ---------------------------------------------------------------------------


def check_dedup(
    candidate_partial: identity.IdentityKeys,
    source_skill: str,
    source_list: str | None = None,
    *,
    people_dir: Path | None = None,
    conflicts_dir: Path | None = None,
    cfg: dict | None = None,
) -> DedupResult:
    """Consult the existing identity-keys index for a pre-enrichment match.

    Per ADR-0033 D149-D152. The per-skill entry point: each discovery
    skill (Week 2 ships find-leads; subsequent weeks ship the other
    three) wraps its pre-enrichment partial in a call to this
    function BEFORE the Apollo / PDL / Reoon spend.

    Args:
        candidate_partial: The pre-enrichment identity keys (whatever
            the discovery skill scraped — typically a LinkedIn slug
            OR an email OR both; rarely github/twitter at the
            pre-enrichment stage). An empty partial returns
            ``status="not_duplicate"`` immediately (nothing to
            intersect against — the caller proceeds to enrichment
            and the post-enrichment resolver handles the eventual
            identity-key population).
        source_skill: The discovery skill that surfaced the candidate.
            One of ``SOURCE_SKILLS`` (enum-validation deferred to
            Week 9-11's per-skill stamping refactor; this primitive
            accepts the string transparently). Stamped on the emitted
            ``discovery_dedup_hit`` / ``discovery_dedup_conflict``
            event for Pillar G dashboard aggregation.
        source_list: The operator-supplied list filename or tag (e.g.,
            ``[[2026-05-24-funded-founders]]``). Operator-PRIVATE per
            ADR-0032 D148 — stamped on the event for direct ledger
            query but NEVER aggregated by Pillar G dashboards.
        people_dir: Override of the vault's Person notes directory.
            ``None`` resolves via ``cfg`` (then via the standard config
            file). Test fixtures pass an explicit ``tmp_path / "people"``
            to avoid pinging the operator's real vault.
        conflicts_dir: Override of the conflicts-report directory.
            ``None`` resolves to ``~/.outreach-factory/conflicts/``.
        cfg: Pre-loaded config dict; ``None`` triggers the standard
            ``~/.outreach-factory/config.yml`` load.

    Returns:
        :class:`DedupResult` carrying the status + the diagnostic
        context. The caller inspects ``result.should_skip_enrichment``
        + dispatches to the appropriate event-payload factory.

    Behavior:
        * Empty candidate partial → ``not_duplicate`` (no keys to
          intersect; caller proceeds to enrichment).
        * Vault unreadable (no ``people_dir``) → ``not_duplicate`` —
          the dedup primitive is the FAST-PATH; the BACK-STOP is the
          post-enrichment :func:`identity.resolve_strict` call inside
          :func:`enrollment.enroll_person`. A vault-side failure does
          not block enrichment; it merely loses the cost-avoidance
          benefit for this candidate.
        * 0 matches → ``not_duplicate``.
        * 1 confident match → ``duplicate``.
        * 1 match BUT ambiguous single-class email (candidate's
          LinkedIn differs from existing record's LinkedIn) →
          ``conflict`` (per :func:`identity._is_ambiguous_single_class_email_match`).
        * 2+ matches → ``conflict``.

    The dedup primitive REUSES :func:`identity.find_matches` +
    :func:`identity.resolve_strict` unchanged. The exit-criterion
    binding (D147 vehicle's
    ``test_three_skills_one_day_consume_one_apollo_one_reoon_zero_duplicates``)
    rests on this reuse — the same strict policy that protects
    post-enrichment enrollment now also protects pre-enrichment
    discovery.

    Side effects:
        On conflict, :func:`identity.resolve_strict` writes a YAML
        report to ``conflicts_dir`` so the operator has the merge /
        split decision tree on disk (same path as the
        :func:`enrollment.enroll_person` conflict). The dedup primitive
        does NOT append to the ledger (the caller dispatches to
        :func:`build_discovery_dedup_hit_payload` or
        :func:`build_discovery_dedup_conflict_payload` + appends via
        the caller's ledger handle).
    """
    # Per ADR-0055 D300 — wrap the body in a discovery-stage span so
    # the per-Person discovery surface is operator-visible via the
    # OTel tracing backend. The source_skill attribute matches the
    # per-Person discovery surface per ADR-0050 D277; source_list is
    # PRIVACY-DISALLOWED at the span attribute surface per ADR-0054
    # D297 + ADR-0055 D304.
    span_attrs: dict[str, str] = {"source_skill": source_skill}
    with traced_stage(
        "discovery", "check_dedup", attributes=span_attrs,
    ):
        if candidate_partial.is_empty():
            return DedupResult(
                status="not_duplicate",
                candidate_partial=candidate_partial,
            )

        if people_dir is None:
            cfg = cfg if cfg is not None else _load_config()
            people_dir = _vault_people_dir(cfg)
            if people_dir is None:
                return DedupResult(
                    status="not_duplicate",
                    candidate_partial=candidate_partial,
                )

        if conflicts_dir is None:
            conflicts_dir = _default_conflicts_dir()

        matches = identity.find_matches(candidate_partial, people_dir)
        resolution = identity.resolve_strict(
            candidate_partial, matches, conflicts_dir,
        )

        if resolution is None:
            return DedupResult(
                status="not_duplicate",
                candidate_partial=candidate_partial,
            )

        if isinstance(resolution, identity.Match):
            return DedupResult(
                status="duplicate",
                candidate_partial=candidate_partial,
                existing_person_id=resolution.person_id or None,
                matched_classes=resolution.matched_classes,
                existing_match=resolution,
            )

        # resolution is identity.Conflict
        # Compute the union of matched_classes across all conflicting
        # matches for operator-readable "which keys overlapped?" context
        # on the conflict event. Mirrors the matched_classes set on the
        # existing enrollment_conflict emit (per enrollment.py:309-317
        # uses matched_note_paths but the per-match classes are useful
        # for the dedup case too).
        union_classes: set[str] = set()
        for m in resolution.matches:
            union_classes |= set(m.matched_classes)
        return DedupResult(
            status="conflict",
            candidate_partial=candidate_partial,
            matched_classes=frozenset(union_classes),
            conflict=resolution,
        )


# ---------------------------------------------------------------------------
# Event payload factories
# ---------------------------------------------------------------------------


def build_discovery_dedup_hit_payload(
    result: DedupResult,
    source_skill: str,
    source_list: str | None,
) -> dict:
    """Construct the ``discovery_dedup_hit`` event payload (no ledger append).

    Per ADR-0033 D150 + ADR-0032 D146. Single source of truth for the
    event shape — both the live-emit path (caller appends to ledger)
    and the dry-run / CLI path call this helper to avoid drift. The
    Pillar D Week 2 follow-up's
    :func:`reply_classifier.build_classified_payload` is the precedent
    for the build-then-append separation.

    Caller-consistency note (Week 2 follow-up P3-E): ``source_skill`` +
    ``source_list`` are passed twice in the canonical caller pattern —
    once to :func:`check_dedup` (for the audit-trail / future enrichment-
    skip dispatch context) and again here (for the event payload).
    :class:`DedupResult` does NOT store these values; callers MUST pass
    the same values to both functions or the emitted event's attribution
    will diverge from the dedup-check provenance. The explicit-caller
    shape is the deliberate D152 design (the dedup primitive is the
    FAST-PATH wrapper; per-skill callers own the source attribution).

    Event shape (per ADR-0033 D150):

    .. code-block:: text

        type: discovery_dedup_hit
        person_id                  (the EXISTING Person whose keys matched)
        candidate_partial          (the pre-enrichment input — IdentityKeys.to_serializable())
        matched_classes            (subset of {linkedin, email, github, twitter} that overlapped)
        source_skill               (which discovery skill surfaced the duplicate)
        source_list                (which operator-supplied list — OPERATOR-PRIVATE per D148)
        channel                    ("none" per D146 channel-on-every-event invariant)
        _emitted_by                ("discovery_dedup" per D17 convention)

    Raises:
        ValueError: if ``result.status != "duplicate"`` — the
            discovery_dedup_hit shape only applies to the
            single-match path. The caller is expected to dispatch
            on ``result.is_duplicate`` / ``result.is_conflict``
            before calling either factory; a misdispatch should fail
            loud at construction time per the Pillar D
            :class:`ClassifierResult` precedent.
    """
    if not result.is_duplicate:
        raise ValueError(
            "build_discovery_dedup_hit_payload requires "
            f"status='duplicate'; got status={result.status!r}. The "
            "caller likely meant build_discovery_dedup_conflict_payload "
            "(for status='conflict') or should not be emitting at all "
            "(for status='not_duplicate')."
        )
    return {
        "type": "discovery_dedup_hit",
        "person_id": result.existing_person_id,
        "candidate_partial": result.candidate_partial.to_serializable(),
        "matched_classes": sorted(result.matched_classes),
        "source_skill": source_skill,
        "source_list": source_list,
        "channel": CHANNEL_VALUE,
        "_emitted_by": EMITTED_BY,
    }


def build_discovery_dedup_conflict_payload(
    result: DedupResult,
    source_skill: str,
    source_list: str | None,
) -> dict:
    """Construct the ``discovery_dedup_conflict`` event payload.

    Per ADR-0033 D151. Mirrors the existing ``enrollment_conflict``
    event shape (per :mod:`enrollment`) so operators encountering a
    dedup conflict + an enrollment conflict on the same candidate
    see matching diagnostic context. The two event classes differ
    only in (a) ``type``, (b) ``_emitted_by``, (c) the dedup variant
    carries ``candidate_partial`` (the pre-enrichment input as
    IdentityKeys) where the enrollment variant carries
    ``candidate_keys`` (the same IdentityKeys but stamped at the
    post-enrichment enrollment site).

    No ``person_id`` field (Week 2 follow-up P2-A clarification): the
    conflict event references 2+ existing Persons (or one ambiguous-
    shared-email match); there is no single attributable person_id.
    Operators consuming this event for per-person aggregation MUST
    use ``matched_note_paths`` (filesystem path equality) rather than
    a ``person_id`` predicate. The Pillar J GDPR-purge implementation
    inherits the same per-path predicate.

    Caller-consistency note (Week 2 follow-up P3-E): same as
    :func:`build_discovery_dedup_hit_payload` — ``source_skill`` +
    ``source_list`` must match the values passed to :func:`check_dedup`.

    Event shape (per ADR-0033 D151):

    .. code-block:: text

        type: discovery_dedup_conflict
        candidate_partial          (the pre-enrichment input — IdentityKeys.to_serializable())
        report_path                (path to the YAML conflict report that resolve_strict wrote)
        match_count                (number of existing Persons matching)
        matched_note_paths         (list of Person note paths matched)
        matched_classes            (union of matched classes across all matches)
        source_skill
        source_list
        channel                    ("none" per D146 channel-on-every-event invariant)
        _emitted_by                ("discovery_dedup" per D17 convention)

    Raises:
        ValueError: if ``result.status != "conflict"`` — symmetric to
            :func:`build_discovery_dedup_hit_payload`'s validation.
    """
    if not result.is_conflict or result.conflict is None:
        raise ValueError(
            "build_discovery_dedup_conflict_payload requires "
            f"status='conflict' + result.conflict set; got "
            f"status={result.status!r}. The caller likely meant "
            "build_discovery_dedup_hit_payload (for status='duplicate') "
            "or should not be emitting at all (for status='not_duplicate')."
        )
    conflict = result.conflict
    return {
        "type": "discovery_dedup_conflict",
        "candidate_partial": result.candidate_partial.to_serializable(),
        "report_path": str(conflict.report_path),
        "match_count": len(conflict.matches),
        "matched_note_paths": [str(m.note_path) for m in conflict.matches],
        "matched_classes": sorted(result.matched_classes),
        "source_skill": source_skill,
        "source_list": source_list,
        "channel": CHANNEL_VALUE,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_keys_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--linkedin", dest="linkedin_url", default=None)
    p.add_argument("--email", action="append", default=None,
                   help="repeat for multiple emails")
    p.add_argument("--github", default=None)
    p.add_argument("--twitter", default=None)
    p.add_argument("--name", default=None,
                   help="optional; used for alt_names in conflict report")


def _keys_from_args(args) -> identity.IdentityKeys:
    return identity.compute_keys(
        name=args.name,
        emails=args.email,
        linkedin_url=args.linkedin_url,
        github=args.github,
        twitter=args.twitter,
    )


def _safe_append(led: "_ledger.Ledger", event: dict) -> None:
    """Best-effort ledger append — mirrors :func:`enrollment._safe_append`.

    A ledger I/O failure must not block the discovery skill (the
    dedup-hit event is the cost-attribution signal; losing it loses
    one row of Pillar G observability, not the dedup behavior
    itself). Print stderr warning + continue.
    """
    try:
        led.append(event)
    except (OSError, ValueError) as exc:
        print(
            f"WARNING: ledger append failed for {event.get('type')}: {exc}",
            file=sys.stderr,
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Pillar E pre-enrichment dedup primitive (ADR-0033)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ck = sub.add_parser(
        "check", help="Check whether a candidate's identity-keys partial "
                      "matches any existing Person — emit dedup events.",
    )
    _add_keys_args(ck)
    ck.add_argument(
        "--source-skill", required=True,
        help=f"One of {sorted(SOURCE_SKILLS)}",
    )
    ck.add_argument(
        "--source-list", default=None,
        help="Operator-supplied list filename or tag (OPERATOR-PRIVATE per "
             "ADR-0032 D148 — never aggregated by Pillar G dashboards)",
    )
    ck.add_argument(
        "--apply", action="store_true",
        help="Append the discovery_dedup_hit / discovery_dedup_conflict "
             "event to the ledger. Default is dry-run (report only).",
    )
    ck.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "check":
        cfg = _load_config()
        people_dir = _vault_people_dir(cfg)
        if people_dir is None:
            out = {
                "ok": False,
                "reason": "vault.people_dir not resolvable",
            }
            print(json.dumps(out) if args.json else
                  f"ERROR: {out['reason']}")
            sys.exit(2)

        keys = _keys_from_args(args)
        if keys.is_empty():
            out = {
                "ok": False,
                "reason": "no identity keys provided",
            }
            print(json.dumps(out) if args.json else
                  f"ERROR: {out['reason']}")
            sys.exit(2)

        result = check_dedup(
            keys,
            source_skill=args.source_skill,
            source_list=args.source_list,
            people_dir=people_dir,
        )

        report: dict = {
            "ok": True,
            "status": result.status,
            "should_skip_enrichment": result.should_skip_enrichment,
            "candidate_partial": result.candidate_partial.to_serializable(),
            "source_skill": args.source_skill,
            "source_list": args.source_list,
        }

        if result.is_duplicate:
            payload = build_discovery_dedup_hit_payload(
                result, args.source_skill, args.source_list,
            )
            report["payload"] = payload
            report["existing_person_id"] = result.existing_person_id
            report["matched_classes"] = sorted(result.matched_classes)
            if args.apply:
                led = _ledger.Ledger(_ledger_dir())
                _safe_append(led, payload)
                report["applied"] = True
        elif result.is_conflict:
            payload = build_discovery_dedup_conflict_payload(
                result, args.source_skill, args.source_list,
            )
            report["payload"] = payload
            # result.conflict is guaranteed non-None by DedupResult.__post_init__
            # when status=='conflict' + by is_conflict above; no bare assert
            # (per Week 2 follow-up P3-A: bare asserts are unsafe under `-O`).
            conflict = result.conflict
            report["report_path"] = str(conflict.report_path) if conflict else None
            report["match_count"] = len(conflict.matches) if conflict else 0
            if args.apply:
                led = _ledger.Ledger(_ledger_dir())
                _safe_append(led, payload)
                report["applied"] = True

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"status: {report['status']}")
            print(f"should_skip_enrichment: {report['should_skip_enrichment']}")
            if result.is_duplicate:
                print(f"  existing person_id: {report['existing_person_id']}")
                print(f"  matched_classes:    {report['matched_classes']}")
                if result.existing_match is not None:
                    print(f"  note_path:          {result.existing_match.note_path}")
            elif result.is_conflict:
                print(f"  match_count:        {report['match_count']}")
                print(f"  report_path:        {report['report_path']}")
            if report.get("applied"):
                print("  ledger event appended.")
            elif result.should_skip_enrichment:
                print("  (dry-run; pass --apply to emit the event to the ledger.)")
        sys.exit(0)


if __name__ == "__main__":
    main()
