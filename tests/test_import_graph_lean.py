"""Keystone regression barrier: the core send path stays import-lean.

Importing the cold-send path (``skills/send-outreach/scripts/send_queued.py``)
must NOT transitively import the heavy operations apparatus (the daemon, the
reconcile reply-ingestion engine, reply classification, conversation tracking,
discovery, enrichment, the funnel) or the OpenTelemetry SDK.

The send path's guardrails (dedup, cooldowns, compliance, two-phase commit) are
load-bearing and stay; the operations modules are opt-in and must not ride in on
a module-level import. If this test goes RED, a new import re-welded the lean
core to the heavy tier. Fix the import (make it lazy, or point it at the
``orchestrator/obs.py`` shim). Do NOT relax this test.

See ``.planning/PLAN-sever-and-partition.md`` (W0).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "send-outreach" / "scripts"

# Bare module names as they appear in ``sys.modules`` (the send path adds
# ``orchestrator/`` to ``sys.path`` and imports these by bare name).
BANNED = [
    "opentelemetry",
    "observability",
    "reconcile",
    "reply_classifier",
    "reply_classifier_llm",
    "conversation_state",
    "conversation_outcomes",
    "discovery_lineage",
    "discovery_dedup",
    "enrich_emails",
    "email_verification_cache",
    "cal_com_webhook",
    "tier_assignment",
    "funnel",
    "enrollment",
    "auto_unsubscribe",
    "daemon",
]


def test_core_send_path_import_is_lean():
    probe = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import send_queued  # noqa: F401\n"
        f"banned = {BANNED!r}\n"
        "leaked = sorted({m for m in sys.modules for b in banned "
        "if m == b or m.startswith(b + '.')})\n"
        "print('LEANRESULT:' + json.dumps(leaked))\n"
    )
    # The send path's config module loads ~/.outreach-factory/config.yml at
    # import time (config.py sys.exit(2) if absent). This probe only needs
    # send_queued to IMPORT so it can inspect sys.modules, so point it at the
    # committed template via OUTREACH_FACTORY_CONFIG. Without this the test is
    # non-hermetic: it passes only on a machine that already has a user config
    # and fails on a fresh clone / in CI (where there is no ~/.outreach-factory).
    env = dict(os.environ)
    env["OUTREACH_FACTORY_CONFIG"] = str(REPO_ROOT / "config-template" / "config.example.yml")
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert proc.returncode == 0, (
        "probe failed to import the core send path:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    markers = [ln for ln in proc.stdout.splitlines() if ln.startswith("LEANRESULT:")]
    assert markers, (
        "probe produced no result marker:\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    leaked = json.loads(markers[-1][len("LEANRESULT:"):])
    assert leaked == [], (
        "the core send path re-welded to the heavy operations tier. "
        f"Leaked module imports: {leaked}. Make the offending import lazy or "
        "route it through orchestrator/obs.py; do not relax this test."
    )
