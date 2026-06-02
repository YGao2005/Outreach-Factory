#!/usr/bin/env python3
"""Create the skill's local venv and install deps. Idempotent."""

import os
import subprocess
import sys
import venv
from pathlib import Path


def main() -> int:
    skill_dir = Path(__file__).parent.parent
    venv_dir = skill_dir / ".venv"
    requirements = skill_dir / "requirements.txt"

    if os.name == "nt":
        venv_python = venv_dir / "Scripts" / "python.exe"
        venv_pip = venv_dir / "Scripts" / "pip.exe"
    else:
        venv_python = venv_dir / "bin" / "python"
        venv_pip = venv_dir / "bin" / "pip"

    if not venv_dir.exists():
        print(f"Creating venv at {venv_dir}")
        venv.create(venv_dir, with_pip=True)

    if not requirements.exists():
        print("No requirements.txt — skipping pip install")
        return 0

    print("Installing dependencies (this can take ~30s on first run)")
    subprocess.run([str(venv_pip), "install", "--upgrade", "pip"], check=True, capture_output=True)
    result = subprocess.run([str(venv_pip), "install", "-r", str(requirements)], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return result.returncode

    print(f"venv ready: {venv_python}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
