"""Tests for ``vault/0006_add_followup_step_to_person_notes``.

Follow-up cadence vault migration. Coverage:

* TestMigrationSurface   - Migration Protocol shape pins.
* TestUpgradeStampsStep  - ledger-derived followup_step per Person.
* TestUpgradeIdempotence - re-running upgrade is a no-op.
* TestStaleHeal          - a drifted value is healed to the derived value.
* TestDryRun             - dry-run previews without writing.
* TestRefuseLoud         - missing vault / ledger posture.
* TestDowngradeRoundTrip - remove the field; round-trip exact.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from orchestrator import ledger as _ledger
from orchestrator.migrations.types import MigrationCategory, MigrationContext
from orchestrator.migrations.vault._vault_io import read_person_frontmatter
from orchestrator.migrations.vault.migration_0006_add_followup_step_to_person_notes import (
    MIGRATION,
    MIGRATION_ID,
    AddFollowupStepToPersonNotes,
)


def _make_ctx(*, state_dir, vault_dir, ledger_dir=None, dry_run=False):
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir if ledger_dir is not None else state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.vault.0006"),
    )


def _write_person_note(vault_dir: Path, name: str, *, person_id, extra=None) -> Path:
    fm = {"type": "person", "name": name, "id": person_id}
    if extra:
        fm.update(extra)
    note = vault_dir / "10 People" / f"{name}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n# {name}\n",
        encoding="utf-8",
    )
    return note


def _seed_confirmed(ledger_dir: Path, person_id: str, n_touches: int) -> None:
    """Append ``n_touches`` confirmed email sends for the person."""
    led = _ledger.Ledger(ledger_dir)
    for i in range(n_touches):
        iid = f"snd_{person_id}_{i}"
        led.append({"type": "send_intent", "intent_id": iid,
                    "person_id": person_id, "channel": "email"})
        led.append({"type": "send_confirmed", "intent_id": iid,
                    "person_id": person_id, "channel": "email",
                    "followup_step": i})


def _fm(note: Path) -> dict:
    fm, _ = read_person_frontmatter(note)
    assert fm is not None
    return fm


class TestMigrationSurface:
    def test_protocol_shape(self):
        assert MIGRATION.id == MIGRATION_ID == "0006_add_followup_step_to_person_notes"
        assert MIGRATION.category == MigrationCategory.VAULT
        assert MIGRATION.is_reversible is True
        assert isinstance(MIGRATION, AddFollowupStepToPersonNotes)


class TestUpgradeStampsStep:
    def test_stamps_derived_step_and_skips_no_touch(self, tmp_path):
        vault = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        cold = _write_person_note(vault, "Cold Only", person_id="p_cold")
        one = _write_person_note(vault, "One Followup", person_id="p_one")
        none = _write_person_note(vault, "No Touch", person_id="p_none")

        _seed_confirmed(ledger_dir, "p_cold", 1)   # cold only -> step 0
        _seed_confirmed(ledger_dir, "p_one", 2)    # cold + 1 follow-up -> step 1
        # p_none: no confirmed sends.

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)

        assert result.applied is True
        assert result.affected_count == 2
        assert _fm(cold)["followup_step"] == 0
        assert _fm(one)["followup_step"] == 1
        assert "followup_step" not in _fm(none)   # no sequence yet -> absent


class TestUpgradeIdempotence:
    def test_second_run_is_noop(self, tmp_path):
        vault = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        _write_person_note(vault, "Person A", person_id="p_a")
        _seed_confirmed(ledger_dir, "p_a", 2)

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, ledger_dir=ledger_dir)
        first = MIGRATION.upgrade(ctx)
        assert first.affected_count == 1
        second = MIGRATION.upgrade(ctx)
        assert second.affected_count == 0


class TestStaleHeal:
    def test_drifted_value_is_healed(self, tmp_path):
        vault = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        note = _write_person_note(vault, "Drifted", person_id="p_d",
                                  extra={"followup_step": 9})  # stale
        _seed_confirmed(ledger_dir, "p_d", 2)  # ledger says step 1

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        assert _fm(note)["followup_step"] == 1


class TestDryRun:
    def test_dry_run_does_not_write(self, tmp_path):
        vault = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        note = _write_person_note(vault, "Preview", person_id="p_p")
        _seed_confirmed(ledger_dir, "p_p", 1)

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, ledger_dir=ledger_dir,
                        dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True and result.affected_count == 1
        assert "followup_step" not in _fm(note)   # not written


class TestRefuseLoud:
    def test_missing_vault_raises(self, tmp_path):
        ctx = _make_ctx(state_dir=tmp_path, vault_dir=None,
                        ledger_dir=tmp_path / "ledger")
        with pytest.raises(ValueError):
            MIGRATION.upgrade(ctx)

    def test_missing_ledger_raises(self, tmp_path):
        # ledger_dir is typed non-optional, so construct the context directly to
        # exercise the migration's defensive missing-ledger branch.
        ctx = MigrationContext(
            dry_run=False, state_dir=tmp_path, ledger_dir=None,
            vault_dir=tmp_path / "vault", policy_dir=tmp_path / "policies",
            now=datetime.now(timezone.utc),
            logger=logging.getLogger("test.vault.0006"),
        )
        with pytest.raises(ValueError):
            MIGRATION.upgrade(ctx)


class TestDowngradeRoundTrip:
    def test_downgrade_removes_field(self, tmp_path):
        vault = tmp_path / "vault"
        ledger_dir = tmp_path / "ledger"
        note = _write_person_note(vault, "Round Trip", person_id="p_rt")
        _seed_confirmed(ledger_dir, "p_rt", 2)

        ctx = _make_ctx(state_dir=tmp_path, vault_dir=vault, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)
        assert _fm(note)["followup_step"] == 1

        down = MIGRATION.downgrade(ctx)
        assert down.affected_count == 1
        assert "followup_step" not in _fm(note)
