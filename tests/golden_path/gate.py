#!/usr/bin/env python3
"""Golden-path self-verification gate — the autonomous-loop exit-signal primitive.

This is what makes an unsupervised loop (Ralph) SAFE: a unit of work is "done"
only when its golden-path assertion is GENUINELY green, not when a commit body
claims it. The loop keys its EXIT_SIGNAL to this script's exit code.

Modes (exit code IS the signal):

  python3 tests/golden_path/gate.py
      Regression check. Exit 0 iff no committed-green golden-path assertion
      regressed. xfail punch-list items are ALLOWED (they stay red on purpose).

  python3 tests/golden_path/gate.py --require <substr>
      "Is my target genuinely fixed?" Runs matching tests with --runxfail, so an
      xfail that now passes counts as GREEN and an xfail that still fails counts
      as RED. Exit 0 iff the matching test(s) genuinely pass. Use the test name
      (e.g. test_pillar_C_reconcile_pass_a_synthesizes_confirmed).

  python3 tests/golden_path/gate.py --status
      Human/machine-readable per-test outcome table. No gating.

  python3 tests/golden_path/gate.py --full
      Also run the WHOLE test suite (cross-pillar regression). Slow (~160s).
      Exit 0 iff golden path AND full suite are green.

Discipline: when --require flips an xfail green, REMOVE the xfail marker in the
test so it becomes a permanent regression barrier (per the spec §7 / §9).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent
REPO_ROOT = GOLDEN_DIR.parent.parent


def _pytest(*args: str) -> int:
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args]
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Golden-path self-verification gate")
    ap.add_argument("--require", metavar="SUBSTR",
                    help="exit 0 iff matching test(s) GENUINELY pass (xfail flipped via --runxfail)")
    ap.add_argument("--status", action="store_true", help="print per-test outcome table")
    ap.add_argument("--full", action="store_true", help="also run the whole suite (cross-pillar regression)")
    ns = ap.parse_args(argv)

    gp = str(GOLDEN_DIR)

    if ns.status:
        return _pytest(gp, "-rA", "--tb=no", "-q")

    if ns.require:
        # --runxfail: ignore xfail markers so a fixed punch-list item reads GREEN
        # and an unfixed one reads RED. -k filters to the target.
        rc = _pytest(gp, "-k", ns.require, "--runxfail", "--tb=short", "-q")
        if rc == 5:  # pytest: no tests collected → target name didn't match
            print(f"GATE: no golden-path test matched --require '{ns.require}'", file=sys.stderr)
        print(f"GATE require '{ns.require}': {'GREEN' if rc == 0 else 'RED'} (exit {rc})")
        return rc

    # Default: regression check. xfails allowed (punch-list stays red on purpose).
    rc = _pytest(gp, "--tb=short", "-q")
    if ns.full and rc == 0:
        print("GATE: golden path green — running full suite for cross-pillar regression…")
        rc = _pytest("-q", "--tb=short")
    print(f"GATE regression check: {'GREEN' if rc == 0 else 'RED'} (exit {rc})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
