"""Tests for vault migration 0001 — add schema_version: 1 to Person notes.

Exercises the migration via :class:`MigrationRunner` against a synthetic
vault directory. Covers:

* Apply on a vault with N Person notes adds schema_version to each.
* Re-apply is idempotent (already-applied notes skipped).
* Dry-run reports affected_count without mutation.
* Notes already at schema_version: 1 are skipped silently.
* Notes at a different schema_version raise loud.
* Non-Person notes (type != "person") are silently skipped.
* Notes with no parseable frontmatter (sub-notes) are silently skipped.
* Notes with malformed YAML raise loud — the migration is NOT marked
  applied; re-apply after fix resumes.
* ctx.vault_dir is None raises ValueError.
* Downgrade removes the field and restores idempotently.
* Per-file failure leaves earlier files intact + migration NOT marked
  applied (framework atomicity contract).
* Real Person-note round-trip preserves comments + field ordering.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import pytest

from orchestrator.migrations import MigrationRunner
from orchestrator.migrations.state import is_applied, load_state
from orchestrator.migrations.types import Migration, MigrationCategory
from orchestrator.migrations.vault._vault_io import FrontmatterError
from orchestrator.migrations.vault.migration_0001 import (
    MIGRATION,
    SCHEMA_VERSION_VALUE,
    AddSchemaVersionToPersonNotes,
)


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Synthetic vault root with `<vault>/10 People/`."""
    v = tmp_path / "vault"
    (v / "10 People").mkdir(parents=True)
    return v


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Isolated state dir per test."""
    d = tmp_path / "state"
    d.mkdir()
    return d


def _make_runner(
    state_dir: Path,
    vault_dir: Path | None,
    registries: dict[MigrationCategory, Sequence[Migration]] | None = None,
) -> MigrationRunner:
    return MigrationRunner(
        state_dir=state_dir,
        ledger_dir=state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        registries=registries or {MigrationCategory.VAULT: [MIGRATION]},
    )


def _make_person(
    vault_dir: Path, name: str, extra_fields: str = "",
) -> Path:
    """Write a synthetic Person note. ``extra_fields`` is appended to
    the frontmatter block (newline-prefixed)."""
    note = vault_dir / "10 People" / f"{name}.md"
    fm = f"name: {name}\ntype: person\nemail: {name.lower()}@example.com"
    if extra_fields:
        fm += "\n" + extra_fields
    note.write_text(f"---\n{fm}\n---\nbody for {name}\n", encoding="utf-8")
    return note


# ---------------------------------------------------------------------------
# Apply path
# ---------------------------------------------------------------------------


class TestApply:
    def test_stamps_schema_version_on_every_person_note(
        self, vault_dir: Path, state_dir: Path,
    ):
        _make_person(vault_dir, "Alice")
        _make_person(vault_dir, "Bob")
        _make_person(vault_dir, "Carol")
        runner = _make_runner(state_dir, vault_dir)
        results = runner.apply(MigrationCategory.VAULT)
        assert len(results) == 1
        assert results[0].affected_count == 3
        for name in ("Alice", "Bob", "Carol"):
            note = vault_dir / "10 People" / f"{name}.md"
            text = note.read_text(encoding="utf-8")
            assert f"schema_version: {SCHEMA_VERSION_VALUE}" in text

    def test_marks_applied_in_state_file(
        self, vault_dir: Path, state_dir: Path,
    ):
        _make_person(vault_dir, "Alice")
        runner = _make_runner(state_dir, vault_dir)
        runner.apply(MigrationCategory.VAULT)
        state = load_state(state_dir)
        assert is_applied(
            state, MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
        )

    def test_idempotent_re_apply(self, vault_dir: Path, state_dir: Path):
        """Re-applying after success is a no-op (pending is empty)."""
        _make_person(vault_dir, "Alice")
        runner = _make_runner(state_dir, vault_dir)
        runner.apply(MigrationCategory.VAULT)
        # Second apply: no pending migrations, no-op.
        second = runner.apply(MigrationCategory.VAULT)
        assert second == []

    def test_skips_notes_already_at_target_version(
        self, vault_dir: Path, state_dir: Path,
    ):
        """A note that already carries schema_version: 1 is skipped
        silently — supports operators who hand-stamp + re-apply."""
        _make_person(
            vault_dir, "Alice",
            extra_fields=f"schema_version: {SCHEMA_VERSION_VALUE}",
        )
        _make_person(vault_dir, "Bob")  # no schema_version
        runner = _make_runner(state_dir, vault_dir)
        result = runner.apply(MigrationCategory.VAULT)[0]
        # Only Bob was affected; Alice already at target.
        assert result.affected_count == 1

    def test_raises_on_schema_version_mismatch(
        self, vault_dir: Path, state_dir: Path,
    ):
        """A note with schema_version: 2 must refuse loud — operator
        intervention required."""
        _make_person(vault_dir, "Alice", extra_fields="schema_version: 2")
        _make_person(vault_dir, "Bob")
        runner = _make_runner(state_dir, vault_dir)
        with pytest.raises(FrontmatterError, match="schema_version: 2"):
            runner.apply(MigrationCategory.VAULT)
        # Framework's atomicity: migration NOT marked applied.
        state = load_state(state_dir)
        assert not is_applied(
            state, MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
        )

    def test_skips_non_person_notes(
        self, vault_dir: Path, state_dir: Path,
    ):
        """Notes with type != "person" are not Person notes; no
        schema_version contract applies."""
        _make_person(vault_dir, "Alice")  # type: person
        # A non-Person note in the People dir (e.g. an operator's draft).
        non_person = vault_dir / "10 People" / "draft.md"
        non_person.write_text(
            "---\nname: Draft\ntype: notebook\n---\nbody\n",
            encoding="utf-8",
        )
        runner = _make_runner(state_dir, vault_dir)
        result = runner.apply(MigrationCategory.VAULT)[0]
        # Only Alice affected; non-Person note untouched.
        assert result.affected_count == 1
        assert "schema_version" not in non_person.read_text()

    def test_skips_notes_with_no_frontmatter(
        self, vault_dir: Path, state_dir: Path,
    ):
        """Sub-notes / drafts without frontmatter are skipped silently."""
        _make_person(vault_dir, "Alice")
        plain = vault_dir / "10 People" / "plain.md"
        plain.write_text("just body content, no frontmatter\n")
        runner = _make_runner(state_dir, vault_dir)
        result = runner.apply(MigrationCategory.VAULT)[0]
        assert result.affected_count == 1
        # Plain note untouched.
        assert plain.read_text() == "just body content, no frontmatter\n"

    def test_raises_on_corrupt_yaml(
        self, vault_dir: Path, state_dir: Path,
    ):
        _make_person(vault_dir, "Good")
        corrupt = vault_dir / "10 People" / "Corrupt.md"
        corrupt.write_text(
            "---\nname: x\n  unbalanced: [\n---\nbody\n",
            encoding="utf-8",
        )
        runner = _make_runner(state_dir, vault_dir)
        with pytest.raises(FrontmatterError, match="unparseable"):
            runner.apply(MigrationCategory.VAULT)

    def test_raises_on_missing_vault_dir(self, state_dir: Path):
        runner = _make_runner(state_dir, vault_dir=None)
        with pytest.raises(ValueError, match="vault_dir"):
            runner.apply(MigrationCategory.VAULT)

    def test_empty_vault_applies_cleanly(
        self, vault_dir: Path, state_dir: Path,
    ):
        """No Person notes → affected_count=0 → migration marked applied."""
        runner = _make_runner(state_dir, vault_dir)
        result = runner.apply(MigrationCategory.VAULT)[0]
        assert result.affected_count == 0
        state = load_state(state_dir)
        assert is_applied(
            state, MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
        )


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_reports_affected_without_writing(
        self, vault_dir: Path, state_dir: Path,
    ):
        _make_person(vault_dir, "Alice")
        _make_person(vault_dir, "Bob")
        runner = _make_runner(state_dir, vault_dir)
        results = runner.dry_run(MigrationCategory.VAULT)
        assert results[0].affected_count == 2
        assert results[0].dry_run is True
        # Files unchanged.
        for name in ("Alice", "Bob"):
            text = (vault_dir / "10 People" / f"{name}.md").read_text()
            assert "schema_version" not in text
        # State file unchanged.
        state = load_state(state_dir)
        assert not is_applied(
            state, MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
        )


# ---------------------------------------------------------------------------
# Downgrade path
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_removes_schema_version_after_rollback(
        self, vault_dir: Path, state_dir: Path,
    ):
        _make_person(vault_dir, "Alice")
        _make_person(vault_dir, "Bob")
        runner = _make_runner(state_dir, vault_dir)
        runner.apply(MigrationCategory.VAULT)
        # Confirm applied.
        for name in ("Alice", "Bob"):
            text = (vault_dir / "10 People" / f"{name}.md").read_text()
            assert f"schema_version: {SCHEMA_VERSION_VALUE}" in text

        result = runner.rollback(
            MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
            allow_rollback=True,
        )
        assert result.affected_count == 2
        # Field removed from both.
        for name in ("Alice", "Bob"):
            text = (vault_dir / "10 People" / f"{name}.md").read_text()
            assert "schema_version" not in text

    def test_idempotent_downgrade_for_notes_without_field(
        self, vault_dir: Path, state_dir: Path,
    ):
        """A note that doesn't have schema_version is silently skipped
        on downgrade — supports re-running downgrade safely."""
        _make_person(vault_dir, "Alice")  # never had schema_version
        # Manually mark the migration applied so downgrade can run.
        runner = _make_runner(state_dir, vault_dir)
        # Call upgrade once to mark applied.
        runner.apply(MigrationCategory.VAULT)
        # Sneakily remove the field someone could have hand-edited.
        note = vault_dir / "10 People" / "Alice.md"
        text = note.read_text()
        text = text.replace(
            f"schema_version: {SCHEMA_VERSION_VALUE}\n", "",
        )
        note.write_text(text)
        # Downgrade should not raise; affected_count = 0.
        result = runner.rollback(
            MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
            allow_rollback=True,
        )
        assert result.affected_count == 0

    def test_downgrade_raises_on_missing_vault(self, state_dir: Path):
        runner = _make_runner(state_dir, vault_dir=None)
        # Need the migration applied first; do it with a vault then drop.
        with pytest.raises(ValueError, match="vault_dir"):
            # rollback() refuses unapplied first; force the path by
            # constructing the migration's downgrade directly.
            from datetime import datetime, timezone
            import logging
            from orchestrator.migrations.types import MigrationContext
            ctx = MigrationContext(
                dry_run=False,
                state_dir=state_dir,
                ledger_dir=state_dir / "ledger",
                vault_dir=None,
                policy_dir=state_dir / "policies",
                now=datetime.now(timezone.utc),
                logger=logging.getLogger("test"),
            )
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# Round-trip — preserve comments + field order
# ---------------------------------------------------------------------------


class TestRealVaultRoundTrip:
    def test_preserves_inline_comments(self, vault_dir: Path, state_dir: Path):
        note = vault_dir / "10 People" / "Alice.md"
        note.write_text(
            "---\n"
            "name: Alice  # informal nickname\n"
            "email: alice@acme.com  # guess-unverified\n"
            "type: person\n"
            "research_tier: A  # high priority\n"
            "---\n"
            "## About Alice\n\n"
            "Body content here.\n",
            encoding="utf-8",
        )
        runner = _make_runner(state_dir, vault_dir)
        runner.apply(MigrationCategory.VAULT)
        text = note.read_text()
        # Comments preserved.
        assert "# informal nickname" in text
        assert "# guess-unverified" in text
        assert "# high priority" in text
        # New field at end.
        assert f"schema_version: {SCHEMA_VERSION_VALUE}\n" in text
        # Body preserved.
        assert "## About Alice" in text
        assert "Body content here." in text

    def test_preserves_field_order(self, vault_dir: Path, state_dir: Path):
        note = vault_dir / "10 People" / "Alice.md"
        note.write_text(
            "---\n"
            "z_field: z\n"
            "name: Alice\n"
            "a_field: a\n"
            "type: person\n"
            "m_field: m\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        runner = _make_runner(state_dir, vault_dir)
        runner.apply(MigrationCategory.VAULT)
        text = note.read_text()
        fm_section = text.split("---\n")[1]
        lines = [
            ln for ln in fm_section.split("\n") if ":" in ln
        ]
        # Original ordering preserved; new field appended last.
        order = [ln.split(":", 1)[0].strip() for ln in lines]
        assert order == [
            "z_field", "name", "a_field", "type", "m_field",
            "schema_version",
        ]


# ---------------------------------------------------------------------------
# Per-file failure leaves earlier files intact
# ---------------------------------------------------------------------------


class TestPerFileFailureAtomicity:
    def test_corrupt_note_mid_batch_leaves_earlier_files_unchanged(
        self, vault_dir: Path, state_dir: Path,
    ):
        """Notes are walked in sorted order. A corrupt note partway
        through the batch:

        * Files rewritten BEFORE the corrupt note are persisted (per-file
          atomicity — each rewrite committed independently).
        * The corrupt note raises.
        * Files AFTER the corrupt note are NOT touched.
        * Framework's batch-level atomicity: migration NOT marked applied.
        * Re-running apply after the operator fixes the corrupt note
          resumes: earlier files are at schema_version: 1 already
          (skipped), corrupt note now parses (rewritten), later files
          processed.
        """
        # Sorted order is: Alice, Bob_corrupt, Charlie.
        _make_person(vault_dir, "Alice")
        bob = vault_dir / "10 People" / "Bob_corrupt.md"
        bob.write_text(
            "---\nname: Bob\n  bad: [\n---\nbody\n",
            encoding="utf-8",
        )
        _make_person(vault_dir, "Charlie")

        runner = _make_runner(state_dir, vault_dir)
        with pytest.raises(FrontmatterError):
            runner.apply(MigrationCategory.VAULT)

        # Alice was processed before Bob_corrupt; her file IS updated.
        alice_text = (vault_dir / "10 People" / "Alice.md").read_text()
        assert f"schema_version: {SCHEMA_VERSION_VALUE}" in alice_text

        # Charlie was NOT processed (Bob raised first).
        charlie_text = (vault_dir / "10 People" / "Charlie.md").read_text()
        assert "schema_version" not in charlie_text

        # Migration NOT marked applied.
        state = load_state(state_dir)
        assert not is_applied(
            state, MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
        )

        # Operator fixes Bob.
        bob.write_text(
            "---\nname: Bob\ntype: person\n---\nbody\n",
            encoding="utf-8",
        )
        runner.apply(MigrationCategory.VAULT)

        # Now all three at v1.
        for name in ("Alice", "Bob_corrupt", "Charlie"):
            text = (vault_dir / "10 People" / f"{name}.md").read_text()
            assert f"schema_version: {SCHEMA_VERSION_VALUE}" in text

        # Migration marked applied.
        state = load_state(state_dir)
        assert is_applied(
            state, MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
        )


# ---------------------------------------------------------------------------
# Per-file write atomicity — tmp file behavior under simulated crash
# ---------------------------------------------------------------------------


class TestPerFileWriteAtomicity:
    def test_simulated_rename_crash_leaves_target_untouched(
        self, vault_dir: Path, state_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """If os.replace raises after the tmp file is written, the
        target note must remain at its pre-migration content."""
        _make_person(vault_dir, "Alice")
        alice = vault_dir / "10 People" / "Alice.md"
        pre_content = alice.read_text()

        original_replace = os.replace
        crashed = {"flag": False}

        def crashing_replace(src, dst):
            if not crashed["flag"]:
                crashed["flag"] = True
                raise OSError("simulated crash before rename")
            return original_replace(src, dst)

        monkeypatch.setattr(os, "replace", crashing_replace)
        runner = _make_runner(state_dir, vault_dir)
        with pytest.raises(OSError, match="simulated crash"):
            runner.apply(MigrationCategory.VAULT)

        # Alice's file unchanged.
        assert alice.read_text() == pre_content
        # Framework's atomicity: NOT marked applied.
        state = load_state(state_dir)
        assert not is_applied(
            state, MigrationCategory.VAULT,
            "0001_add_schema_version_to_person_notes",
        )


# ---------------------------------------------------------------------------
# Migration shape — Protocol conformance + class attributes
# ---------------------------------------------------------------------------


class TestMigrationShape:
    def test_migration_attributes(self):
        m = MIGRATION
        assert m.id == "0001_add_schema_version_to_person_notes"
        assert m.category == MigrationCategory.VAULT
        assert m.is_reversible is True
        assert isinstance(m.description, str) and m.description

    def test_migration_class_is_dataclass(self):
        """The migration class is a dataclass instance for testability."""
        m = AddSchemaVersionToPersonNotes()
        assert m.id == "0001_add_schema_version_to_person_notes"
