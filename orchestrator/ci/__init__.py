"""Pillar I Week 5 — CI bring-up surface (ADR-0070 D375 invariant 5 + ADR-0074;
closes the Pillar A Week 6 §D3 deferral per ADR-0006 §"CI enforcement of the
price-update == ADR-amendment discipline").

This package is the **first CI artifact in the repo** (per ADR-0006 §D3: "the
repo has no CI surface today … that decision belongs in Pillar I where the
OSS-hardening week range owns the CI bring-up"). The CI workflow lands at
``.github/workflows/ci.yml``; the load-bearing logic is the deterministic,
harness-gated Python primitive :func:`check_cochange_discipline` so the rule is
unit-testable without spawning git — the ``.github/workflows`` step and the
``python -m orchestrator.ci`` CLI are thin wrappers that feed it the
``git diff --name-only`` set.

**The discipline** (ADR-0006 §Pricing table contract): *a vendor price change is
a new ADR amendment + commit, not a silent edit.* Concretely — a commit that
changes ``orchestrator/policy/budget.py``'s ``COST_RATES_USD`` block MUST also
amend ``docs/adr/0006-budget-rules-and-cost-events.md`` (its pricing-table-as-of
date row). The check generalizes to **any** "constant + governing ADR" co-change
pair via the :data:`COCHANGE_PAIRS` closed-set (per ADR-0006 §D3: "generalizes to
the same shape for any future 'constant + ADR' pair").

**Refuse-loud** per ADR-0001 D2 + the Pillar H W10-11 follow-up P1-1 closure
(operator-readable message; NO Python traceback at the operator-facing surface):
:func:`check_cochange_discipline` returns structured :class:`DisciplineViolation`
values; :func:`run_cochange_check_cli` renders them as operator-readable lines and
returns a non-zero exit code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class CoChangePair:
    """A (constant-bearing source file, governing ADR) pair that MUST co-change.

    Per ADR-0006 §D3 + the generalization to any future "constant + ADR" pair.
    All paths are **repo-relative** with forward slashes (matching
    ``git diff --name-only`` output).

    Fields:

    * ``source`` — repo-relative path of the source file bearing the governed
      constant (e.g. ``orchestrator/policy/budget.py``).
    * ``adr`` — repo-relative path of the governing ADR that MUST be amended in
      the same commit (e.g. ``docs/adr/0006-budget-rules-and-cost-events.md``).
    * ``constant`` — the governed constant's name (e.g. ``COST_RATES_USD``). Used
      by the content-aware refinement: when a unified diff is available, a source
      change is only flagged if this name appears in the file's diff, so an
      unrelated edit to the source file (a comment, a bug-fix in a sibling rule)
      does not false-positive-refuse.
    * ``reason`` — operator-readable explanation of why the pair must co-change;
      surfaced verbatim in the refuse-loud message.
    """

    source: str
    adr: str
    constant: str
    reason: str


#: Closed-set (R031-shape) of the co-change pairs the CI surface enforces.
#:
#: ADR-0006 §D3 names the seed pair (``COST_RATES_USD`` ↔ ADR-0006) and the
#: generalization target (e.g. ``LINKEDIN_WEEKLY_INVITE_LIMIT`` ↔ ADR-0008 "if it
#: ever moves from cosmetic display to load-bearing"). Only load-bearing pairs
#: ship here; adding a pair is itself a reviewable code change. The closed-set IS
#: the regression-barrier — a test pins its membership so a silent removal of the
#: pricing-table guard reads red.
COCHANGE_PAIRS: tuple[CoChangePair, ...] = (
    CoChangePair(
        source="orchestrator/policy/budget.py",
        adr="docs/adr/0006-budget-rules-and-cost-events.md",
        constant="COST_RATES_USD",
        reason=(
            "a vendor price change is a new ADR-0006 amendment + commit, not a "
            "silent edit (ADR-0006 §Pricing table contract + §D3 deferral)"
        ),
    ),
)


@dataclass(frozen=True)
class DisciplineViolation:
    """A single co-change discipline violation — refuse-loud value object.

    Carries the offending :class:`CoChangePair` + an operator-readable
    ``message`` naming the source, the ADR, and how to resolve. NO Python
    traceback is surfaced at the operator-facing CI step (ADR-0001 D2 + the
    Pillar H W10-11 follow-up P1-1 closure's operator-readable-error discipline).
    """

    pair: CoChangePair
    message: str


def check_cochange_discipline(
    changed_paths: Iterable[str],
    *,
    diffs: Mapping[str, str] | None = None,
    pairs: Sequence[CoChangePair] = COCHANGE_PAIRS,
) -> tuple[DisciplineViolation, ...]:
    """Return one :class:`DisciplineViolation` per pair whose source changed
    WITHOUT its governing ADR also changing.

    Args:
        changed_paths: the ``git diff --name-only`` set — repo-relative paths
            with forward slashes. Order-insensitive; deduplicated internally.
        diffs: optional ``{path: unified-diff-text}`` map. When supplied, a
            source change is only flagged if the pair's ``constant`` name appears
            in that file's diff text — the ADR-0006 §D3 "change to the
            ``COST_RATES_USD`` block" refinement that keeps an unrelated
            ``budget.py`` edit (a comment, a sibling-rule fix) from
            false-positive-refusing. When ``None``, the strict file-level
            ``--name-only`` contract per D375 invariant 5 applies (ANY change to
            the source file requires the governing ADR).
        pairs: the co-change pairs to enforce; defaults to :data:`COCHANGE_PAIRS`.

    Returns:
        A tuple of violations (empty == discipline satisfied). The return value
        is the structural commitment the ``.github/workflows/ci.yml`` step + the
        :func:`run_cochange_check_cli` consume.
    """

    changed = set(changed_paths)
    violations: list[DisciplineViolation] = []
    for pair in pairs:
        if pair.source not in changed:
            continue
        # Content-aware refinement (ADR-0006 §D3): if we have the diff text and
        # the governed constant is NOT in it, the source changed for an
        # unrelated reason — do not refuse.
        if diffs is not None and pair.constant not in diffs.get(pair.source, ""):
            continue
        if pair.adr in changed:
            continue  # co-changed in the same commit — discipline satisfied.
        violations.append(
            DisciplineViolation(
                pair=pair,
                message=(
                    f"CI discipline violation: {pair.source} changed without "
                    f"{pair.adr}. {pair.reason}. Resolve by amending {pair.adr} "
                    f"(its pricing-table-as-of-date row) in the SAME commit, or "
                    f"revert the {pair.constant} edit."
                ),
            )
        )
    return tuple(violations)


def run_cochange_check_cli(
    changed_paths: Iterable[str],
    *,
    diffs: Mapping[str, str] | None = None,
) -> int:
    """Render :func:`check_cochange_discipline` results for the CI step.

    Prints an operator-readable line per violation (NO traceback) and returns a
    process exit code: ``0`` when the discipline holds, ``1`` when any pair is
    violated. The ``.github/workflows/ci.yml`` step + ``python -m orchestrator.ci``
    invoke this with the commit's ``git diff --name-only`` set.
    """

    violations = check_cochange_discipline(changed_paths, diffs=diffs)
    if not violations:
        print("CI cochange-discipline: OK (no unaccompanied constant change).")
        return 0
    print(f"CI cochange-discipline: {len(violations)} violation(s):")
    for v in violations:
        print(f"  - {v.message}")
    return 1


__all__ = [
    "CoChangePair",
    "COCHANGE_PAIRS",
    "DisciplineViolation",
    "check_cochange_discipline",
    "run_cochange_check_cli",
]
