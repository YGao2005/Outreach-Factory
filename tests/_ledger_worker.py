"""Subprocess worker for the ledger concurrency test.

Spawned by tests/test_ledger.py via multiprocessing. Lives at module level
(not nested in a test) so multiprocessing can import + pickle the entry point
on platforms where 'spawn' is the default start method (macOS, Windows).

Each invocation appends `count` events tagged with this worker's id to the
shared ledger directory. The test asserts that across N workers no events
are lost and the JSONL stays parseable.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCH = REPO_ROOT / "orchestrator"
for p in (str(REPO_ROOT), str(ORCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ledger  # noqa: E402


def write_n(args: tuple[str, int, int]) -> int:
    """Append `count` events to ledger_dir tagged with worker_id."""
    ledger_dir, worker_id, count = args
    led = ledger.Ledger(Path(ledger_dir))
    for i in range(count):
        led.append({
            "type": "send_intent",
            "person_id": f"worker-{worker_id}",
            "intent_id": f"snd_w{worker_id:02d}_e{i:04d}",
            "channel": "email",
            "seq": i,
        })
    return count
