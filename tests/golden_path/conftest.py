"""Golden-path harness fixtures (L0 spine-liveness).

See `.planning/GOLDEN-PATH-HARNESS.md`. The parent `tests/conftest.py` already
puts the repo root + `orchestrator/` on `sys.path` and aliases the bare module
names to the `orchestrator.*` package, so `from orchestrator import ledger`
works here.

Determinism: a fixed `GOLDEN_NOW` anchor (per ADR-0031 byte-identical-determinism).
Isolation: every ledger write is redirected to a `tmp_path` via the constructor
and the `OUTREACH_FACTORY_LEDGER_DIR` escape-hatch — the real
`~/.outreach-factory/ledger` is never touched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

PERSONA_DIR = Path(__file__).parent / "personas"

# Fixed clock anchor for the whole harness. Events are emitted relative to this
# so the funnel's default 30d window always covers them deterministically.
GOLDEN_NOW = datetime(2026, 5, 28, 17, 0, 0, tzinfo=timezone.utc)


def load_persona(name: str) -> dict:
    return yaml.safe_load((PERSONA_DIR / f"{name}.yml").read_text())


@pytest.fixture
def golden_now() -> datetime:
    return GOLDEN_NOW


@pytest.fixture
def aiyara_persona() -> dict:
    return load_persona("aiyara_yang")


@pytest.fixture
def scholarfeed_persona() -> dict:
    return load_persona("scholarfeed")


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    """An isolated Ledger at tmp_path; also exports OUTREACH_FACTORY_LEDGER_DIR
    so primitives that open their own handle (enrollment, state_machine,
    reconcile-with-led=None) write to the same isolated dir."""
    from orchestrator import ledger as _ledger

    led_dir = tmp_path / "ledger"
    monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(led_dir))
    return _ledger.Ledger(led_dir)
