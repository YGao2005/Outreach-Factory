"""Pillar A Week 4 — direct ledger-level tests for the cost_incurred event.

Verifies the load-bearing properties of the cost_incurred event shape
that ADR-0006 locks:

* Round-trips through the JSONL writer (read what we wrote).
* New fields (``source``, ``amount_usd``, ``units``,
  ``model_or_endpoint``, ``person_id``, ``run_id``) survive the
  serializer / parser.
* Backward compatibility: events written before Week 4 (without the
  cost_incurred type) parse identically — the new event type is
  additive, not a schema breaker.
* The ledger's all_events() surface returns cost_incurred events
  alongside everything else (this is the path budget rules consume).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.ledger import Event, Ledger


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ledger"
    d.mkdir()
    return d


@pytest.fixture
def led(ledger_dir: Path) -> Ledger:
    return Ledger(ledger_dir)


# ---------------------------------------------------------------------------
# Event-class round-trip
# ---------------------------------------------------------------------------


class TestEventRoundTrip:
    def test_cost_incurred_event_constructible(self):
        e = Event(
            type="cost_incurred",
            source="apollo",
            amount_usd=0.05,
            units=1,
            model_or_endpoint="people-search",
            person_id="alice-li",
            run_id="run-abc",
        )
        assert e.type == "cost_incurred"
        assert e["source"] == "apollo"
        assert e["amount_usd"] == 0.05
        assert e["units"] == 1
        assert e["model_or_endpoint"] == "people-search"
        assert e.person_id == "alice-li"
        assert e["run_id"] == "run-abc"

    def test_cost_incurred_event_round_trips_via_from_dict(self):
        d = {
            "v": 1,
            "ts": "2026-05-18T12:00:00.000Z",
            "type": "cost_incurred",
            "source": "anthropic",
            "amount_usd": 0.015,
            "units": 1500,
            "model_or_endpoint": "claude-opus-4-7:input",
            "person_id": "alice-li",
            "run_id": "run-xyz",
        }
        e = Event.from_dict(d)
        assert e.to_dict() == d

    def test_optional_fields_default_absent(self):
        """person_id + run_id are optional; not setting them keeps them
        out of the serialized form (no implicit None)."""
        e = Event(
            type="cost_incurred",
            source="anthropic",
            amount_usd=0.0,
            units=100,
            model_or_endpoint="overhead",
        )
        d = e.to_dict()
        assert "person_id" not in d
        assert "run_id" not in d


# ---------------------------------------------------------------------------
# Ledger append + read
# ---------------------------------------------------------------------------


class TestLedgerAppendReadCost:
    def test_append_then_all_events_returns_cost(self, led: Ledger):
        out = led.append({
            "type": "cost_incurred",
            "source": "apollo",
            "amount_usd": 0.05,
            "units": 1,
            "model_or_endpoint": "people-search",
            "person_id": "alice-li",
            "run_id": "run-abc",
        })
        # The append return shape carries ts + v auto-filled.
        assert out["source"] == "apollo"
        assert out["amount_usd"] == 0.05
        assert "ts" in out
        assert out["v"] == 1

        # all_events() surface returns it.
        events = led.all_events()
        cost_events = [e for e in events if e.type == "cost_incurred"]
        assert len(cost_events) == 1
        assert cost_events[0]["source"] == "apollo"
        assert cost_events[0]["amount_usd"] == 0.05

    def test_append_persists_to_disk(self, led: Ledger, ledger_dir: Path):
        led.append({
            "type": "cost_incurred",
            "source": "reoon", "amount_usd": 0.005, "units": 1,
            "model_or_endpoint": "verifier/power",
        })
        # File should exist with one line.
        files = list(ledger_dir.glob("events-*.jsonl"))
        assert len(files) == 1
        lines = [l for l in files[0].read_text().split("\n") if l.strip()]
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["type"] == "cost_incurred"
        assert parsed["source"] == "reoon"
        assert parsed["amount_usd"] == 0.005

    def test_multiple_cost_events_aggregated_on_read(self, led: Ledger):
        for source, amount in [
            ("apollo", 0.05),
            ("apollo", 0.05),
            ("reoon", 0.005),
            ("anthropic", 0.015),
        ]:
            led.append({
                "type": "cost_incurred",
                "source": source,
                "amount_usd": amount,
                "units": 1,
                "model_or_endpoint": f"{source}/x",
            })

        cost_events = [e for e in led.all_events()
                       if e.type == "cost_incurred"]
        assert len(cost_events) == 4
        by_source: dict[str, float] = {}
        for e in cost_events:
            s = e["source"]
            by_source[s] = by_source.get(s, 0.0) + e["amount_usd"]
        assert by_source["apollo"] == pytest.approx(0.10)
        assert by_source["reoon"] == pytest.approx(0.005)
        assert by_source["anthropic"] == pytest.approx(0.015)

    def test_quota_only_event_has_zero_usd(self, led: Ledger):
        """Gmail / LinkedIn emit ``amount_usd: 0.0`` per ADR-0006."""
        led.append({
            "type": "cost_incurred",
            "source": "gmail", "amount_usd": 0.0, "units": 1,
            "model_or_endpoint": "messages.send",
        })
        events = [e for e in led.all_events()
                  if e.type == "cost_incurred"]
        assert len(events) == 1
        assert events[0]["amount_usd"] == 0.0
        assert events[0]["units"] == 1

    def test_run_level_event_without_person_id(self, led: Ledger):
        led.append({
            "type": "cost_incurred",
            "source": "anthropic",
            "amount_usd": 0.001, "units": 100,
            "model_or_endpoint": "claude-opus-4-7:auth",
            "run_id": "run-abc",
            # person_id deliberately omitted — run-level overhead.
        })
        events = [e for e in led.all_events()
                  if e.type == "cost_incurred"]
        assert len(events) == 1
        # Confirm person_id is absent in the persisted shape.
        assert events[0].get("person_id") is None


# ---------------------------------------------------------------------------
# Backward compatibility: existing events ignore the new fields
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_existing_send_events_unchanged_by_new_type(self, led: Ledger):
        """Adding cost_incurred to the catalog must not break parsing
        of pre-Week-4 event shapes."""
        led.append({
            "type": "send_intent", "intent_id": "snd_x",
            "person_id": "alice-li", "channel": "email",
        })
        led.append({
            "type": "send_confirmed", "intent_id": "snd_x",
            "person_id": "alice-li", "channel": "email",
            "gmail_message_id": "gm_1",
        })
        led.append({
            "type": "cost_incurred", "source": "gmail",
            "amount_usd": 0.0, "units": 1,
            "model_or_endpoint": "messages.send",
            "person_id": "alice-li", "intent_id": "snd_x",
        })
        # All three event types coexist.
        events = led.all_events()
        types = {e.type for e in events}
        assert types == {"send_intent", "send_confirmed", "cost_incurred"}

        # Existing query paths (by person, by intent) still work.
        per_person = led.query_by_person("alice-li")
        assert len(per_person) == 3

    def test_intent_id_field_on_cost_event_indexed(self, led: Ledger):
        """A cost event with intent_id should be retrievable via the
        cross-reference path the ledger uses for send events.

        This pins the choice that intent_id is a generic cross-event
        correlation key, not a send-specific one — useful for
        attributing the per-send Gmail cost to its originating
        intent_id even if the send_confirmed gets purged later.
        """
        led.append({
            "type": "send_intent", "intent_id": "snd_corr",
            "person_id": "alice-li", "channel": "email",
        })
        led.append({
            "type": "cost_incurred",
            "intent_id": "snd_corr",
            "source": "gmail",
            "amount_usd": 0.0, "units": 1,
            "model_or_endpoint": "messages.send",
            "person_id": "alice-li",
        })
        # query_by_person returns both events; the intent_id correlator
        # lets a future analytics pass join cost back to the send.
        evs = led.query_by_person("alice-li")
        intent_correlated = [e for e in evs if e.intent_id == "snd_corr"]
        assert len(intent_correlated) == 2
        types = {e.type for e in intent_correlated}
        assert types == {"send_intent", "cost_incurred"}
