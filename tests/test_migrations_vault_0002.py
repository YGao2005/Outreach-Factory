"""Tests for ``vault/0002_backfill_identity_lineage``.

Direct unit tests against the synthetic fixture. The replay-test in
``tests/test_migrations_replay.py`` covers the runner-mediated path;
this module exercises the migration's contract end-to-end without
going through the runner.

The synthetic fixture (``tests/fixtures/synthetic_pillar_b/``)
contains three Person notes — Alice (linkedin + email), Bob (email
only), Carol (linkedin only) — and one touch note + one ledger event
+ one policy file. None of the three Person notes share an identity
key class, so the migration runs cleanly against the baseline.

See ADR-0013 for the synthetic-replay vehicle design.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext, MigrationResult,
)
from orchestrator.migrations.vault.migration_0002 import (
    BackfillIdentityLineage,
    IDENTITY_VERSION_VALUE,
    IdentityBackfillConflictError,
    MIGRATION,
    MIGRATION_ID,
    PEOPLE_SUBDIR,
)
from orchestrator.migrations.vault._vault_io import FrontmatterError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    state_dir: Path,
    vault_dir: Path | None,
    dry_run: bool = False,
) -> MigrationContext:
    """Construct a MigrationContext for direct migration invocation.

    Mirrors the runner's ``_build_context`` shape so direct-call tests
    exercise the same surface the framework would hand the migration.
    """
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.vault.0002"),
    )


def _parse_fm(path: Path) -> dict:
    """Read a note's frontmatter dict (assumes well-formed input)."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.find("\n---", 4)
    assert end != -1
    return yaml.safe_load(text[4:end])


# ---------------------------------------------------------------------------
# Migration surface — Protocol compliance
# ---------------------------------------------------------------------------


class TestMigrationSurface:
    def test_singleton_implements_protocol(self):
        """``MIGRATION`` exports the right id / category / reversibility."""
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0002_backfill_identity_lineage"
        assert MIGRATION.category == MigrationCategory.VAULT
        assert MIGRATION.is_reversible is False

    def test_description_is_one_line(self):
        """Description fits the runner's pending-report shape."""
        assert "\n" not in MIGRATION.description
        assert "Person note" in MIGRATION.description


# ---------------------------------------------------------------------------
# upgrade() — happy path against the synthetic fixture
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:
    def test_stamps_id_and_identity_keys_on_all_three(self, synthetic_state_dir):
        """Each Person note gains id + identity_keys + identity_version.

        Test name says "all three" for historical reasons; the fixture
        now has six Persons (Alice/Bob/Carol/Dana/Evan/Fiona) per
        Pillar C Week 6 extension."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        assert isinstance(result, MigrationResult)
        assert result.applied is True
        assert result.dry_run is False
        assert result.affected_count == 6

        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        for name in (
            "Alice Anderson.md", "Bob Brown.md",
            "Carol Cole.md", "Dana Davis.md", "Evan Estefan.md",
            "Fiona Forrest.md",
        ):
            fm = _parse_fm(people_dir / name)
            assert isinstance(fm.get("id"), str) and fm["id"]
            assert isinstance(fm.get("identity_keys"), dict)
            assert fm["identity_version"] == IDENTITY_VERSION_VALUE

    def test_id_provenance_suffix_reflects_strong_keys(
        self, synthetic_state_dir,
    ):
        """Alice (linkedin+email) + Carol (linkedin) + Dana (linkedin) →
        ``-li`` suffix; Bob (email only) → ``-em`` suffix. Verifies the
        mint_id contract carries through the migration wrapper."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        fm_alice = _parse_fm(people_dir / "Alice Anderson.md")
        fm_bob = _parse_fm(people_dir / "Bob Brown.md")
        fm_carol = _parse_fm(people_dir / "Carol Cole.md")
        fm_dana = _parse_fm(people_dir / "Dana Davis.md")
        assert fm_alice["id"].endswith("-li"), fm_alice["id"]
        assert fm_bob["id"].endswith("-em"), fm_bob["id"]
        assert fm_carol["id"].endswith("-li"), fm_carol["id"]
        assert fm_dana["id"].endswith("-li"), fm_dana["id"]

    def test_identity_keys_block_contains_strong_keys(
        self, synthetic_state_dir,
    ):
        """Bob's identity_keys carries his email; Carol's carries her linkedin."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        fm_bob = _parse_fm(people_dir / "Bob Brown.md")
        assert fm_bob["identity_keys"]["emails"] == ["bob@brown.example"]
        assert "linkedin" not in fm_bob["identity_keys"]

        fm_carol = _parse_fm(people_dir / "Carol Cole.md")
        assert fm_carol["identity_keys"]["linkedin"] == "in/carolcole"
        assert "emails" not in fm_carol["identity_keys"]

    def test_body_text_preserved_byte_identical(self, synthetic_state_dir):
        """The markdown body below the frontmatter is unchanged."""
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        # Snapshot Alice's body before.
        before = (people_dir / "Alice Anderson.md").read_text(encoding="utf-8")
        body_before = before.split("\n---\n", 1)[1]

        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)

        after = (people_dir / "Alice Anderson.md").read_text(encoding="utf-8")
        body_after = after.split("\n---\n", 1)[1]
        assert body_before == body_after

    def test_returns_migration_result_with_proper_fields(
        self, synthetic_state_dir,
    ):
        """The MigrationResult carries the contract fields."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.migration_id == MIGRATION_ID
        assert result.category == MigrationCategory.VAULT
        assert result.applied is True
        assert result.affected_count == 6
        assert "backfilled" in result.notes
        assert "6" in result.notes


# ---------------------------------------------------------------------------
# upgrade() — dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_write_to_disk(self, synthetic_state_dir):
        """Dry-run produces counts without mutating Person notes."""
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        before = {
            n.name: n.read_text(encoding="utf-8")
            for n in people_dir.glob("*.md")
        }

        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.applied is True
        assert result.affected_count == 6

        after = {
            n.name: n.read_text(encoding="utf-8")
            for n in people_dir.glob("*.md")
        }
        assert before == after

    def test_dry_run_then_real_apply_produces_same_counts(
        self, synthetic_state_dir,
    ):
        """Real apply after dry-run produces the same affected_count."""
        ctx_dry = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        ctx_real = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        r_dry = MIGRATION.upgrade(ctx_dry)
        r_real = MIGRATION.upgrade(ctx_real)
        assert r_dry.affected_count == r_real.affected_count == 6


# ---------------------------------------------------------------------------
# upgrade() — idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_re_apply_is_no_op(self, synthetic_state_dir):
        """Second apply finds zero work."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        r2 = MIGRATION.upgrade(ctx)
        assert r2.affected_count == 0
        assert "already complete" in r2.notes

    def test_re_apply_preserves_bytes(self, synthetic_state_dir):
        """A second apply against the already-migrated vault leaves
        files byte-identical."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        snapshot = {
            n.name: n.read_text(encoding="utf-8")
            for n in people_dir.glob("*.md")
        }
        MIGRATION.upgrade(ctx)
        after = {
            n.name: n.read_text(encoding="utf-8")
            for n in people_dir.glob("*.md")
        }
        assert snapshot == after

    def test_partial_state_with_id_and_keys_but_no_version_is_rewritten(
        self, synthetic_state_dir,
    ):
        """A Person with ``id`` + ``identity_keys`` but no
        ``identity_version`` is NOT considered complete — the
        migration stamps ``identity_version: 1``.

        Per the Week 5 review P2-4 fix: the idempotence check enforces
        ALL THREE fields the migration stamps (``id`` + ``identity_keys``
        + ``identity_version``). A future Pillar D / E / F migration
        that gates on ``identity_version: 1`` finds counterexamples
        in any vault where the operator hand-stamped two of the three
        and would either re-apply or refuse silently. The strict
        idempotence check closes the SoT-marker gap.
        """
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        alice = people_dir / "Alice Anderson.md"
        original = alice.read_text(encoding="utf-8")
        # Manually stamp id + identity_keys (multi-line block) but NOT
        # identity_version.
        partial = original.replace(
            "type: person\n",
            "type: person\n"
            "id: alice-manual-li\n"
            "identity_keys:\n"
            "  linkedin: in/aliceanderson\n",
        )
        alice.write_text(partial, encoding="utf-8")

        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        result = MIGRATION.upgrade(ctx)
        fm = _parse_fm(alice)
        # identity_version is now stamped.
        assert fm["identity_version"] == IDENTITY_VERSION_VALUE
        # Operator-installed id is preserved (SoT — never silently
        # re-minted).
        assert fm["id"] == "alice-manual-li"
        # identity_keys block is present (operator-installed shape
        # preserved; migration just adds the version marker).
        assert isinstance(fm.get("identity_keys"), dict)
        # Alice was rewritten; Bob + Carol + Dana + Evan + Fiona also
        # rewritten (they have neither field). affected_count = 6.
        assert result.affected_count == 6

    def test_partial_state_resumes_cleanly(self, synthetic_state_dir):
        """A note that gained ``id:`` without ``identity_keys:``
        (partial-failure resume scenario) is rewritten on next apply.

        The pre-existing ``id`` is preserved (operator-installed ids
        are the SoT — backfill_identity matches this), but the
        missing ``identity_keys:`` block is added. Re-running apply
        from this partial state converges cleanly.
        """
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        # Manually stamp `id:` on Alice but leave identity_keys absent.
        alice = people_dir / "Alice Anderson.md"
        original = alice.read_text(encoding="utf-8")
        partial = original.replace(
            "type: person\n",
            "type: person\nid: alice-anderson-partial-li\n",
        )
        alice.write_text(partial, encoding="utf-8")

        result = MIGRATION.upgrade(ctx)
        # Alice's pre-existing id is preserved (operator-installed
        # ids are the SoT; never silently re-minted); identity_keys
        # block is added.
        fm = _parse_fm(alice)
        assert fm["id"] == "alice-anderson-partial-li"
        assert isinstance(fm.get("identity_keys"), dict)
        # All six Person notes affected (Alice was rewritten because
        # her identity_keys was still missing; Bob/Carol/Dana/Evan/Fiona
        # also).
        assert result.affected_count == 6


# ---------------------------------------------------------------------------
# upgrade() — refuse-loud paths
# ---------------------------------------------------------------------------


class TestRefuseLoud:
    def test_refuses_on_missing_vault_dir(self, synthetic_state_dir):
        """ctx.vault_dir=None → ValueError."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=None,
        )
        with pytest.raises(ValueError, match="vault_dir"):
            MIGRATION.upgrade(ctx)

    def test_no_op_on_missing_people_subdir(self, tmp_path):
        """Vault without 10 People/ is a legitimate empty state.

        The migration succeeds with affected_count=0 — same posture as
        ``iter_person_notes`` (which yields nothing).
        """
        # Build a vault dir with NO People subdir.
        vault = tmp_path / "empty_vault"
        vault.mkdir()
        state = tmp_path / "state"
        state.mkdir()
        ctx = _make_ctx(state_dir=state, vault_dir=vault)
        result = MIGRATION.upgrade(ctx)
        assert result.applied is True
        assert result.affected_count == 0
        assert "does not exist" in result.notes

    def test_refuses_on_identity_conflict(
        self, synthetic_state_dir, tmp_path,
    ):
        """Two Person notes sharing a linkedin → IdentityBackfillConflictError."""
        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        # Create a fourth Person note that shares Alice's linkedin.
        dup = people_dir / "Alice Duplicate.md"
        dup.write_text(
            "---\n"
            "type: person\n"
            "name: Alice Duplicate\n"
            "linkedin: https://linkedin.com/in/aliceanderson\n"  # collides!
            "email: dup@example.com\n"
            "---\n"
            "# Alice Duplicate\n",
            encoding="utf-8",
        )
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        with pytest.raises(IdentityBackfillConflictError) as exc:
            MIGRATION.upgrade(ctx)
        msg = str(exc.value)
        assert "1 identity-graph conflict cluster" in msg
        assert "linkedin" in msg
        assert "in/aliceanderson" in msg
        assert "Alice Anderson.md" in msg
        assert "Alice Duplicate.md" in msg

    def test_conflict_error_is_subclass_of_frontmatter_error(self):
        """IdentityBackfillConflictError extends FrontmatterError so
        callers catching FrontmatterError (the broader frontmatter
        category) also catch identity conflicts."""
        assert issubclass(IdentityBackfillConflictError, FrontmatterError)


# ---------------------------------------------------------------------------
# upgrade() — atomicity contract
# ---------------------------------------------------------------------------


class TestAtomicity:
    def test_failure_before_write_leaves_vault_unchanged(
        self, synthetic_state_dir, monkeypatch,
    ):
        """A simulated mid-apply crash leaves un-rewritten notes intact.

        Patches ``write_person_frontmatter_atomic`` to raise on the
        second call; verifies the first note IS rewritten + the rest
        are unchanged + the migration raises (so the runner's atomicity
        contract leaves the migration unmarked).
        """
        from orchestrator.migrations.vault import migration_0002 as mod

        people_dir = synthetic_state_dir.vault_dir / PEOPLE_SUBDIR
        before = {
            n.name: n.read_text(encoding="utf-8")
            for n in sorted(people_dir.glob("*.md"))
        }

        call_count = {"n": 0}

        def raising_write(path: Path, text: str) -> None:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("simulated crash")
            # First call: do the real atomic write.
            from orchestrator.migrations.vault._vault_io import (
                write_person_frontmatter_atomic as real_write,
            )
            real_write(path, text)

        monkeypatch.setattr(
            mod, "write_person_frontmatter_atomic", raising_write,
        )
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        with pytest.raises(OSError, match="simulated crash"):
            MIGRATION.upgrade(ctx)

        # First Person note (alphabetically Alice) was rewritten.
        after = {
            n.name: n.read_text(encoding="utf-8")
            for n in sorted(people_dir.glob("*.md"))
        }
        # At least one note rewritten (the one before the crash).
        differs = [n for n in before if before[n] != after[n]]
        assert len(differs) == 1, f"expected 1 changed, got {differs}"
        # The other two are byte-identical to pre-migration state.
        for name in before:
            if name not in differs:
                assert before[name] == after[name]


# ---------------------------------------------------------------------------
# downgrade() — refusal
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_downgrade_raises_not_implemented(self, synthetic_state_dir):
        """The migration is structurally irreversible per D23."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        with pytest.raises(NotImplementedError, match="irreversible"):
            MIGRATION.downgrade(ctx)
