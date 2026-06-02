"""Pillar A Week 4 — cost_incurred wiring for enrichment-side API calls.

Currently covers the Reoon emit site in
``orchestrator/enrich_emails.py``. The Reoon call is the only paid
API the orchestrator-side Python codebase makes; Anthropic / Apollo /
PDL / LinkedIn API calls happen via Claude Code skills (MCP-mediated)
and are covered separately in Pillar G (observability).

Tests use the documented ``emit_reoon_cost_event`` helper directly,
because the surrounding CLI path (``process_one``) does file IO on
vault paths the test wouldn't be exercising. The helper IS the
unit-testable contract.
"""

from __future__ import annotations

import pytest


# enrich_emails.py lazy-imports verify_email (and therefore dnspython),
# so importing the module here does not require dns to be installed.
# The cost-emission helpers under test never call the DNS path.
#
# conftest.py already aliases `orchestrator.policy` to the bare name
# `policy` in sys.modules. We use the orchestrator-prefixed import
# here so the orchestrator package's pre-aliased ledger/policy modules
# are reused (avoids the double-registration ValueError that would
# fire if we re-imported via the bare path).
from orchestrator import enrich_emails  # noqa: E402
from orchestrator import ledger as _ledger  # noqa: E402
from orchestrator.policy import budget as _budget  # noqa: E402


@pytest.fixture
def led(tmp_path: Path) -> _ledger.Ledger:
    d = tmp_path / "ledger"
    d.mkdir()
    return _ledger.Ledger(d)


class TestReoonCostEmission:
    def test_emit_writes_cost_event(self, led: _ledger.Ledger):
        enrich_emails.emit_reoon_cost_event(
            led, person_id="alice-stem", run_id="enrich-abc",
        )
        events = [e for e in led.all_events()
                  if e.type == "cost_incurred"]
        assert len(events) == 1
        ev = events[0]
        assert ev["source"] == "reoon"
        assert ev["units"] == 1
        assert ev["person_id"] == "alice-stem"
        assert ev["run_id"] == "enrich-abc"
        assert ev["model_or_endpoint"] == "verifier/power"

    def test_emit_uses_pricing_table_rate(self, led: _ledger.Ledger):
        """The helper pulls amount_usd from COST_RATES_USD, not a
        hardcoded literal — so a future price update via ADR-0006
        propagates without touching the emit site."""
        enrich_emails.emit_reoon_cost_event(led, person_id="alice-stem")
        events = [e for e in led.all_events()
                  if e.type == "cost_incurred"]
        expected_rate = _budget.COST_RATES_USD["reoon"]["verify"]
        assert events[0]["amount_usd"] == expected_rate

    def test_emit_with_none_ledger_is_noop(self):
        """The legacy CLI path (no ledger) must keep working."""
        # Should not raise.
        enrich_emails.emit_reoon_cost_event(None, person_id="alice-stem")

    def test_emit_run_id_optional(self, led: _ledger.Ledger):
        enrich_emails.emit_reoon_cost_event(led, person_id="alice-stem")
        events = [e for e in led.all_events()
                  if e.type == "cost_incurred"]
        assert len(events) == 1
        assert events[0].get("run_id") is None

    def test_emit_failure_is_swallowed(self, led: _ledger.Ledger, capsys):
        """Per the helper's contract: a failure to append must not
        propagate — the API call already succeeded, and a missing
        audit row is better than rolling back the (already-spent)
        spend."""
        class _BrokenLedger:
            def append(self, _event):
                raise RuntimeError("disk full")

        enrich_emails.emit_reoon_cost_event(
            _BrokenLedger(), person_id="alice-stem",
        )
        captured = capsys.readouterr()
        assert "cost_incurred append failed" in captured.err
