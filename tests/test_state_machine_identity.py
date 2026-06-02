"""Tests for the identity-aware Person-note lookup added to state_machine.py.

Covers:
  - find_person_note_by_keys: returns Path on single match, None on no match,
    Conflict on 2+ matches.
  - find_person_note_identity: identity-first, name-fallback.
  - Legacy find_person_note still works (with deprecation warning to stderr).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from orchestrator import identity, ledger as ledger_mod, state_machine


@pytest.fixture
def vault(tmp_path: Path) -> dict:
    vault_path = tmp_path / "vault"
    people_dir = vault_path / "10 People"
    queue_dir = people_dir / "🟦 Queue"
    active_dir = people_dir / "🟧 Active"
    for d in (queue_dir, active_dir):
        d.mkdir(parents=True)
    return {
        "vault": {
            "path": str(vault_path),
            "people_dir": "10 People",
            "queue_subdir": "🟦 Queue",
            "active_subdir": "🟧 Active",
        },
        "_test_people_dir": people_dir,
    }


def _write_person(people_dir: Path, subdir: str, filename: str, **fm):
    fm_out = {"type": "person"}
    fm_out.update(fm)
    fm_yaml = yaml.safe_dump(fm_out, sort_keys=False, allow_unicode=True).strip()
    path = people_dir / subdir / f"{filename}.md"
    path.write_text(f"---\n{fm_yaml}\n---\n\n# {filename}\n", encoding="utf-8")
    return path


class TestFindByKeys:
    def test_single_match_by_linkedin(self, vault, tmp_path, monkeypatch):
        monkeypatch.setattr(state_machine, "_load_config", lambda: vault)
        target = _write_person(
            vault["_test_people_dir"], "🟧 Active", "Dylan",
            name="Dylan T", id="dylan-li",
            identity_keys={"linkedin": "in/dylan"},
        )
        keys = identity.compute_keys(linkedin_url="https://linkedin.com/in/dylan")
        result = state_machine.find_person_note_by_keys(keys, cfg=vault)
        assert isinstance(result, Path)
        assert result == target

    def test_no_match_returns_none(self, vault):
        keys = identity.compute_keys(linkedin_url="https://linkedin.com/in/nobody")
        assert state_machine.find_person_note_by_keys(keys, cfg=vault) is None

    def test_empty_keys_returns_none(self, vault):
        keys = identity.compute_keys()
        assert state_machine.find_person_note_by_keys(keys, cfg=vault) is None

    def test_two_matches_returns_conflict(self, vault, tmp_path, monkeypatch):
        # Avoid writing real conflict reports to ~/.outreach-factory/.
        monkeypatch.setenv("HOME", str(tmp_path))
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Alice",
            name="Alice", id="alice-li",
            identity_keys={"linkedin": "in/alice",
                           "emails": ["family@home.com"]},
        )
        _write_person(
            vault["_test_people_dir"], "🟧 Active", "Bob",
            name="Bob", id="bob-li",
            identity_keys={"linkedin": "in/bob",
                           "emails": ["family@home.com"]},
        )
        keys = identity.compute_keys(emails=["family@home.com"])
        result = state_machine.find_person_note_by_keys(keys, cfg=vault)
        assert isinstance(result, identity.Conflict)
        assert len(result.matches) == 2

    def test_legacy_frontmatter_match(self, vault):
        """Pre-backfill notes have top-level linkedin: — match still works."""
        target = _write_person(
            vault["_test_people_dir"], "🟦 Queue", "Legacy",
            name="Legacy", linkedin="https://linkedin.com/in/legacy-slug",
        )
        keys = identity.compute_keys(linkedin_url="https://linkedin.com/in/legacy-slug")
        assert state_machine.find_person_note_by_keys(keys, cfg=vault) == target


class TestFindIdentity:
    def test_identity_first(self, vault):
        target = _write_person(
            vault["_test_people_dir"], "🟧 Active", "Mismatched Name",
            name="Real Name", id="real-li",
            identity_keys={"linkedin": "in/real"},
        )
        keys = identity.compute_keys(linkedin_url="https://linkedin.com/in/real")
        # Name "Wrong Name" wouldn't match by name; LinkedIn would.
        result = state_machine.find_person_note_identity(
            name="Wrong Name", keys=keys, cfg=vault,
        )
        assert result == target

    def test_name_fallback_when_keys_empty(self, vault):
        target = _write_person(
            vault["_test_people_dir"], "🟦 Queue", "Name Only",
            name="Name Only",
        )
        keys = identity.compute_keys()  # empty
        result = state_machine.find_person_note_identity(
            name="Name Only", keys=keys, cfg=vault,
        )
        assert result == target

    def test_name_fallback_when_keys_no_match(self, vault):
        """Keys non-empty but no record matches — fall through to name lookup."""
        target = _write_person(
            vault["_test_people_dir"], "🟦 Queue", "Name Match",
            name="Name Match", linkedin="https://linkedin.com/in/old-slug",
        )
        keys = identity.compute_keys(linkedin_url="https://linkedin.com/in/nope")
        result = state_machine.find_person_note_identity(
            name="Name Match", keys=keys, cfg=vault,
        )
        assert result == target

    def test_returns_none_when_no_match_and_no_name(self, vault):
        keys = identity.compute_keys()
        assert state_machine.find_person_note_identity(
            name=None, keys=keys, cfg=vault,
        ) is None


class TestLegacyFindPersonNote:
    def test_legacy_still_works(self, vault, capsys):
        target = _write_person(
            vault["_test_people_dir"], "🟦 Queue", "Pranjali Awasthi",
            name="Pranjali Awasthi",
        )
        result = state_machine.find_person_note("Pranjali Awasthi", cfg=vault)
        assert result == target
        # Should emit a deprecation hint to stderr.
        captured = capsys.readouterr()
        assert "legacy" in captured.err.lower()

    def test_legacy_silent_when_called_internally(self, vault, capsys):
        """find_person_note_identity invokes the legacy path with
        _emit_warning=False so callers that explicitly went through the
        integrated entry point don't trigger the deprecation noise."""
        _write_person(
            vault["_test_people_dir"], "🟦 Queue", "Quiet Person",
            name="Quiet Person",
        )
        state_machine.find_person_note_identity(
            name="Quiet Person", keys=identity.compute_keys(), cfg=vault,
        )
        captured = capsys.readouterr()
        assert "legacy" not in captured.err.lower()


class TestRecordTransition:
    """Phase 5.5 Week 2 — state_machine.record_transition appends a
    state_transition event to the ledger so the dispatcher (and any other
    code that flips pipeline_stage) leaves a trace future reconcile can
    replay."""

    def test_emits_state_transition_event(self, tmp_path, monkeypatch):
        led_dir = tmp_path / "ledger"
        led_dir.mkdir()
        monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(led_dir))
        out = state_machine.record_transition(
            "dylan-txa-li", "queued", "researched",
            skill="research-prospect",
            note_path="/vault/10 People/Dylan.md",
        )
        assert out is not None
        led = ledger_mod.Ledger(led_dir)
        events = [e.to_dict() for e in led.all_events()]
        assert len(events) == 1
        assert events[0]["type"] == "state_transition"
        assert events[0]["from"] == "queued"
        assert events[0]["to"] == "researched"
        assert events[0]["person_id"] == "dylan-txa-li"
        assert events[0]["skill"] == "research-prospect"

    def test_derived_stage_picks_up_transition(self, tmp_path, monkeypatch):
        led_dir = tmp_path / "ledger"
        led_dir.mkdir()
        monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(led_dir))
        state_machine.record_transition("p1", None, "queued")
        state_machine.record_transition("p1", "queued", "researched")
        state_machine.record_transition("p1", "researched", "drafted")
        led = ledger_mod.Ledger(led_dir)
        assert led.derived_stage("p1") == "drafted"

    def test_ledger_failure_does_not_raise(self, tmp_path, monkeypatch, capsys):
        # Point at a path that can't be created (a regular file in the way).
        bad = tmp_path / "blocker"
        bad.write_text("not a directory")
        monkeypatch.setenv("OUTREACH_FACTORY_LEDGER_DIR", str(bad / "sub"))
        out = state_machine.record_transition("p1", "queued", "researched")
        # Returns None on failure but does not propagate.
        assert out is None
        captured = capsys.readouterr()
        assert "WARNING" in captured.err or "warning" in captured.err.lower()
