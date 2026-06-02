#!/usr/bin/env python3
"""Entry point for send-outreach skill. Bootstraps venv on first run, then dispatches to scripts."""

import os
import subprocess
import sys
from pathlib import Path


def venv_python() -> Path:
    skill_dir = Path(__file__).parent.parent
    venv_dir = skill_dir / ".venv"
    return venv_dir / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def ensure_venv() -> Path:
    py = venv_python()
    if py.exists():
        return py
    setup = Path(__file__).parent / "setup_environment.py"
    print("First-run setup: creating venv + installing deps")
    result = subprocess.run([sys.executable, str(setup)])
    if result.returncode != 0:
        print("Setup failed", file=sys.stderr)
        sys.exit(result.returncode)
    return py


SCRIPTS = {
    "send": "send_queued.py",
    "reconcile": "reconcile.py",
    "auth": "gmail_auth.py",
    "check-bounces": "check_bounces.py",
}


def usage() -> None:
    print("Usage: python run.py <command> [args...]")
    print()
    print("Commands:")
    print("  send           — scan vault for queued cold-touches, preview, send (Gmail) + writeback")
    print("  reconcile      — Gmail Sent folder lookup to flip stale sent:false on already-sent notes")
    print("  check-bounces  — scan inbox for mailer-daemon DSNs, mark bounced person notes")
    print("  auth           — bootstrap Gmail OAuth (one-time browser consent)")


def main() -> int:
    if len(sys.argv) < 2:
        usage()
        return 1
    cmd = sys.argv[1]
    if cmd not in SCRIPTS:
        usage()
        return 1
    py = ensure_venv()
    script = Path(__file__).parent / SCRIPTS[cmd]
    return subprocess.run([str(py), str(script), *sys.argv[2:]]).returncode


if __name__ == "__main__":
    sys.exit(main())
