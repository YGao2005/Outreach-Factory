"""Tests for orchestrator/backfill_ledger.py.

Validates the retroactive event emission for Phase 5.5 Week 2 migration:
  - enrolled events emit one per Person note
  - send_intent + send_confirmed pair emit per touch with sent: true
  - orphan touches (Person.last_touch without matching touch note) surface
  - rerunning is idempotent (deterministic synthetic intent_ids)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from orchestrator import backfill_ledger, ledger as ledger_mod


@pytest.fixture
def synthetic_vault(tmp_path: Path) -> dict:
    """Build a synthetic vault with 3 persons + 2 touches.

    Person A — has identity + a corresponding sent touch.
    Person B — has identity, no touch, but a last_touch frontmatter field
               that should surface as an orphan.
    Person C — has identity, no touches, no last_touch — not in any event.
    """
    vault = tmp_path / "vault"
    people = vault / "10 People" / "🟧 Active"
    conv = vault / "40 Conversations" / "2026" / "05"
    people.mkdir(parents=True)
    conv.mkdir(parents=True)
    ledger_dir = tmp_path / "outreach-factory" / "ledger"
    ledger_dir.mkdir(parents=True)

    def write_person(name, **fm):
        out = {"type": "person", "name": name}
        out.update(fm)
        path = people / f"{name}.md"
        path.write_text(
            "---\n"
            + yaml.safe_dump(out, sort_keys=False, allow_unicode=True).strip()
            + f"\n---\n\n# {name}\n",
            encoding="utf-8",
        )
        return path

    def write_touch(date_str, person_name, channel="email", sent=True, **extra):
        fm = {
            "type": "touch",
            "date": date_str,
            "channel": channel,
            "direction": "outbound",
            "person": f"[[{person_name}]]",
            "sent": sent,
            "sent_at": date_str,
        }
        fm.update(extra)
        fname = f"{date_str} {person_name} cold touch ({channel.title()}).md"
        path = conv / fname
        path.write_text(
            "---\n"
            + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
            + "\n---\n\n# touch\n",
            encoding="utf-8",
        )
        return path

    write_person("Alice", id="alice-li", identity_keys={"linkedin": "in/alice"},
                 identity_version=1, status="contacted",
                 created="2026-05-01", first_touch="2026-05-02",
                 last_touch="2026-05-02")
    write_person("Bob", id="bob-li", identity_keys={"linkedin": "in/bob"},
                 identity_version=1, status="contacted",
                 created="2026-04-15", last_touch="2026-04-20")
    write_person("Charlie", id="charlie-li",
                 identity_keys={"linkedin": "in/charlie"},
                 identity_version=1, status="queued",
                 created="2026-05-10")

    write_touch("2026-05-02", "Alice", channel="email")

    return {
        "vault_path": vault,
        "people_dir": people.parent,
        "conv_dir": conv.parent.parent,
        "ledger_dir": ledger_dir,
    }


class TestPlanAndApply:
    def test_dry_run_emits_nothing_to_disk(self, synthetic_vault):
        result = backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=True,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        # The plan reports what *would* be emitted.
        assert len(result.enrolled_emitted) == 3
        assert len(result.sends_emitted) == 1
        # No files written.
        files = list(synthetic_vault["ledger_dir"].glob("events-*.jsonl"))
        assert files == []

    def test_apply_writes_expected_events(self, synthetic_vault):
        result = backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=False,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        assert len(result.enrolled_emitted) == 3
        assert len(result.sends_emitted) == 1
        # Bob has last_touch but no matching touch → orphan.
        assert "bob-li" in result.orphans_emitted

        led = ledger_mod.Ledger(synthetic_vault["ledger_dir"])
        events = [e.to_dict() for e in led.all_events()]
        types = [e["type"] for e in events]
        # 3 enrolled + 1 send_intent + 1 send_confirmed + 1 orphan = 6
        assert types.count("enrolled") == 3
        assert types.count("send_intent") == 1
        assert types.count("send_confirmed") == 1
        assert types.count("send_confirmed_orphan") == 1

    def test_idempotent_rerun(self, synthetic_vault):
        backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=False,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        # Second run should skip everything.
        result2 = backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=False,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        assert result2.enrolled_emitted == []
        assert result2.enrolled_skipped == ["alice-li", "bob-li", "charlie-li"]
        assert result2.sends_emitted == []
        assert len(result2.sends_skipped) == 1
        assert result2.orphans_emitted == []

    def test_synth_intent_id_is_deterministic(self):
        a = backfill_ledger.synth_intent_id(
            "alice-li", "2026-05-02T00:00:00.000Z", "email")
        b = backfill_ledger.synth_intent_id(
            "alice-li", "2026-05-02T00:00:00.000Z", "email")
        assert a == b
        assert a.startswith("bf_")
        # Different inputs → different id.
        c = backfill_ledger.synth_intent_id(
            "alice-li", "2026-05-02T00:00:00.000Z", "linkedin")
        assert a != c

    def test_persons_without_id_flagged_not_enrolled(self, tmp_path):
        # A vault with one Person note missing `id:` (pre-identity-backfill).
        vault = tmp_path / "vault"
        people = vault / "10 People"
        conv = vault / "40 Conversations"
        people.mkdir(parents=True)
        conv.mkdir(parents=True)
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()

        path = people / "Legacy.md"
        path.write_text(
            "---\ntype: person\nname: Legacy\ncreated: 2026-01-01\n---\n\n# x\n",
            encoding="utf-8",
        )

        result = backfill_ledger.plan_and_apply(
            people, conv, dry_run=False, ledger_dir=ledger_dir,
        )
        assert result.enrolled_emitted == []
        assert len(result.persons_without_id) == 1

    def test_touches_without_person_match_flagged(self, synthetic_vault):
        # Add a touch that points at a nonexistent Person.
        conv = synthetic_vault["conv_dir"] / "2026" / "05"
        fm = {
            "type": "touch", "date": "2026-05-05", "channel": "email",
            "person": "[[Nobody Here]]", "sent": True,
            "sent_at": "2026-05-05",
        }
        (conv / "2026-05-05 Nobody Here cold touch.md").write_text(
            "---\n" + yaml.safe_dump(fm, sort_keys=False).strip()
            + "\n---\n\nbody\n",
            encoding="utf-8",
        )
        result = backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=False,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        assert len(result.touches_without_person_match) == 1

    def test_enrolled_ts_matches_created_date(self, synthetic_vault):
        backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=False,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        led = ledger_mod.Ledger(synthetic_vault["ledger_dir"])
        events = [e for e in led.all_events() if e.type == "enrolled"]
        alice = next(e for e in events if e["person_id"] == "alice-li")
        assert alice["ts"].startswith("2026-05-01T")
        bob = next(e for e in events if e["person_id"] == "bob-li")
        assert bob["ts"].startswith("2026-04-15T")

    def test_send_pair_has_matching_intent_id(self, synthetic_vault):
        backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=False,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        led = ledger_mod.Ledger(synthetic_vault["ledger_dir"])
        intent = next(e for e in led.all_events() if e.type == "send_intent")
        confirm = next(e for e in led.all_events()
                       if e.type == "send_confirmed")
        assert intent["intent_id"] == confirm["intent_id"]
        assert intent["intent_id"].startswith("bf_")
        # last_send_for should pick this up.
        last = led.last_send_for("alice-li", "email")
        assert last is not None
        assert last["intent_id"] == intent["intent_id"]


class TestValidate:
    def test_validate_clean(self, synthetic_vault):
        backfill_ledger.plan_and_apply(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            dry_run=False,
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        result = backfill_ledger.validate_ledger(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        assert result["ok"] is True
        assert result["person_count"] == 3
        assert result["touch_count"] == 1
        assert result["missing_enrolled"] == []
        assert result["missing_intents"] == []

    def test_validate_pre_apply_reports_gaps(self, synthetic_vault):
        result = backfill_ledger.validate_ledger(
            synthetic_vault["people_dir"],
            synthetic_vault["conv_dir"],
            ledger_dir=synthetic_vault["ledger_dir"],
        )
        assert result["ok"] is False
        assert len(result["missing_enrolled"]) == 3
        assert len(result["missing_intents"]) == 1


class TestDateCoercion:
    def test_iso_date_string(self):
        out = backfill_ledger._date_to_iso("2026-05-15")
        assert out == "2026-05-15T00:00:00.000Z"

    def test_datetime_value(self):
        dt = datetime(2026, 5, 15, 12, 30, tzinfo=timezone.utc)
        out = backfill_ledger._date_to_iso(dt)
        assert out.startswith("2026-05-15T12:30:")

    def test_none_falls_back_to_mtime(self, tmp_path):
        out = backfill_ledger._date_to_iso(None, fallback_mtime=1700000000)
        # Just verify it parses as a valid ISO timestamp.
        datetime.fromisoformat(out.replace("Z", "+00:00"))

    def test_person_link_parsing(self):
        assert backfill_ledger._person_link_to_name("[[Dylan Teixeira]]") \
            == "Dylan Teixeira"
        assert backfill_ledger._person_link_to_name(
            "[[Dylan Teixeira|alias]]") == "Dylan Teixeira"
        assert backfill_ledger._person_link_to_name("plain string") \
            == "plain string"
        assert backfill_ledger._person_link_to_name(None) is None
