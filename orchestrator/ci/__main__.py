"""``python -m orchestrator.ci`` — the cochange-discipline CI entrypoint.

Thin git-plumbing wrapper around :func:`orchestrator.ci.check_cochange_discipline`
(the load-bearing, unit-tested logic lives there). Computes the commit's changed
file set + per-file diff text, feeds them to the primitive, prints any violation
as an operator-readable line, and exits non-zero on a violation so the CI job
fails the build.

Usage:

    python -m orchestrator.ci [BASE_REF] [HEAD_REF]

``BASE_REF``/``HEAD_REF`` default to ``HEAD^`` and ``HEAD`` (the D375 invariant 5
shape: ``git diff --name-only HEAD^ HEAD``). In GitHub Actions PR runs the
workflow passes the PR base + head SHAs.
"""

from __future__ import annotations

import subprocess
import sys

from orchestrator.ci import COCHANGE_PAIRS, run_cochange_check_cli


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    base = argv[0] if len(argv) >= 1 else "HEAD^"
    head = argv[1] if len(argv) >= 2 else "HEAD"

    changed = [p for p in _git("diff", "--name-only", base, head).splitlines() if p]

    # Per-file diff text for ONLY the governed source files — lets the primitive
    # apply the ADR-0006 §D3 "change to the COST_RATES_USD block" content
    # refinement, so an unrelated budget.py edit does not false-positive-refuse.
    governed = {pair.source for pair in COCHANGE_PAIRS}
    diffs = {
        path: _git("diff", base, head, "--", path)
        for path in changed
        if path in governed
    }

    return run_cochange_check_cli(changed, diffs=diffs)


if __name__ == "__main__":
    raise SystemExit(main())
