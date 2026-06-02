"""Reconcile shim (Phase 5.5 Week 3).

Thin wrapper that delegates to orchestrator/reconcile.py. The send-outreach
SKILL.md still references `scripts/reconcile.py`; keeping this file present
avoids breaking the documented entry point during the migration. New code
should call `python orchestrator/reconcile.py` directly.

Passes any/all CLI flags through to orchestrator.reconcile.main(); also
default-injects `--send-outreach-scope` so the orchestrator can log that
the invocation came from the legacy entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
_ORCHESTRATOR = _THIS.parent.parent.parent.parent / "orchestrator"
if _ORCHESTRATOR.exists() and str(_ORCHESTRATOR) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR))


import reconcile as _reconcile  # noqa: E402


def main() -> int:
    argv = sys.argv[1:]
    if not any(a in argv for a in ("--quick", "--full", "--status", "--passes", "--since")):
        # Legacy invocation with no Phase-5.5 flags. Default to --quick so the
        # SKILL.md's "always reconcile on first use" guidance keeps working.
        argv = ["--quick", *argv]
    if "--send-outreach-scope" not in argv:
        argv = [*argv, "--send-outreach-scope"]
    sys.argv = [sys.argv[0], *argv]
    return _reconcile.main()


if __name__ == "__main__":
    sys.exit(main())
