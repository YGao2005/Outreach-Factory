"""Tests for policy migration 0001 — add engine_compat block + bump version.

Exercises the migration directly (calling ``upgrade`` / ``downgrade``
against a synthetic ``MigrationContext``) AND through the
``MigrationRunner`` (``apply`` + ``rollback`` paths). Covers:

* Every policy file gets the ``engine_compat`` block + version bumped 1→2.
* Re-apply is idempotent (already-migrated files skipped).
* Dry-run reports affected_count without mutation.
* Refuse-loud on inconsistent state (version: 2 without block;
  version: 1 with block; unexpected version values).
* Refuse-loud on ``ctx.policy_dir`` doesn't exist on disk.
* Refuse-loud on unparseable / non-mapping policy files.
* Empty policy dir (zero ``.yml`` files) is NOT a refusal — applies
  cleanly with affected_count=0.
* Downgrade removes block + reverts version 2→1 idempotently.
* Per-file failure leaves earlier files intact + migration NOT marked
  applied (framework atomicity contract).
* Engine accepts both v1 and v2 files after the version-range update
  in :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.
* Real cooldowns.example.yml round-trip preserves comments + rules.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest
import yaml

from orchestrator.migrations import (
    MigrationCategory,
    MigrationNotReversibleError,
    MigrationRunner,
)
from orchestrator.migrations.policy._policy_io import PolicyFileError
from orchestrator.migrations.policy.migration_0001 import (
    COMPAT_BLOCK_KEY,
    FROM_VERSION,
    MIGRATION,
    MIGRATION_ID,
    MIN_ENGINE_VERSION_VALUE,
    TO_VERSION,
    AddEngineCompatField,
)
from orchestrator.migrations.state import is_applied, load_state
from orchestrator.migrations.types import (
    Migration,
    MigrationContext,
    MigrationResult,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
FACTORY_TEMPLATE = REPO_ROOT / "config-template" / "cooldowns.example.yml"


@pytest.fixture
def policy_dir(tmp_path: Path) -> Path:
    """Synthetic policy directory per test."""
    p = tmp_path / "policies"
    p.mkdir()
    return p


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Isolated state directory per test."""
    d = tmp_path / "state"
    d.mkdir()
    return d


def _make_runner(
    state_dir: Path,
    policy_dir: Path,
    registries: dict[MigrationCategory, Sequence[Migration]] | None = None,
) -> MigrationRunner:
    return MigrationRunner(
        state_dir=state_dir,
        ledger_dir=state_dir / "ledger",
        vault_dir=None,
        policy_dir=policy_dir,
        registries=registries or {MigrationCategory.POLICY: [MIGRATION]},
    )


def _make_ctx(
    policy_dir: Path,
    state_dir: Path,
    *,
    dry_run: bool = False,
) -> MigrationContext:
    """Build a MigrationContext for direct upgrade()/downgrade() tests."""
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=state_dir / "ledger",
        vault_dir=None,
        policy_dir=policy_dir,
        now=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        logger=logging.getLogger("test.migrations.policy.0001"),
    )


def _write_v1_policy(
    policy_dir: Path, name: str, rules_block: str = "rules: []",
) -> Path:
    """Write a synthetic v1 policy file."""
    f = policy_dir / name
    f.write_text(f"version: 1\n{rules_block}\n", encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Migration shape — declared attributes
# ---------------------------------------------------------------------------


class TestMigrationShape:
    def test_migration_id(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0001_add_engine_compat_field"

    def test_migration_category(self):
        assert MIGRATION.category == MigrationCategory.POLICY

    def test_migration_is_reversible(self):
        """Policy migrations are usually reversible (per ADR-0012)."""
        assert MIGRATION.is_reversible is True

    def test_migration_satisfies_protocol(self):
        from orchestrator.migrations.types import Migration as MigrationProto
        assert isinstance(MIGRATION, MigrationProto)

    def test_module_constants(self):
        """The from/to versions + block key are exposed for tests +
        downstream consumers."""
        assert FROM_VERSION == 1
        assert TO_VERSION == 2
        assert COMPAT_BLOCK_KEY == "engine_compat"
        assert MIN_ENGINE_VERSION_VALUE  # non-empty string

    def test_min_engine_version_comes_from_policy_engine_constant(self):
        """The stamped value MUST be ``POLICY_ENGINE_VERSION`` (from
        ``orchestrator.policy.engine``), NOT ``RUNNER_VERSION`` (from
        the migration framework). The field name ``min_engine_version``
        is semantically about the POLICY ENGINE — the two constants
        share ``"0.1.0"`` at Week 4 but are expected to diverge as
        Pillar C / D / E / F land. Per ADR-0012 D18 + Week 4
        follow-up P2-2."""
        from orchestrator.policy.engine import POLICY_ENGINE_VERSION
        assert MIN_ENGINE_VERSION_VALUE == POLICY_ENGINE_VERSION

    def test_description_mentions_engine_compat_and_version(self):
        """The operator-facing description names what the migration
        does — the runner surfaces this string in pending / dry-run
        reports."""
        d = MIGRATION.description
        assert "engine_compat" in d
        assert "version" in d

    def test_policy_migration_does_not_emit_migration_event(
        self, policy_dir: Path, state_dir: Path, tmp_path: Path,
    ):
        """Per ADR-0012 I5 compliance + Week 4 follow-up P2-1: the
        ``migration_event`` audit-trail emission contract is
        ledger-specific (ADR-0010 D17). Policy migrations write to
        YAML files, not to the ledger, and must NOT emit
        ``migration_event`` events. Pillar G is the future home for
        per-migration metrics on non-ledger categories."""
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        _write_v1_policy(policy_dir, "cd.yml")
        ctx = MigrationContext(
            dry_run=False,
            state_dir=state_dir,
            ledger_dir=ledger_dir,
            vault_dir=None,
            policy_dir=policy_dir,
            now=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
            logger=logging.getLogger("test.policy_no_ledger_emit"),
        )
        MIGRATION.upgrade(ctx)
        # Verify NO events were written to the ledger.
        from orchestrator.migrations.ledger._ledger_io import iter_events
        events = list(iter_events(ledger_dir))
        assert events == []


# ---------------------------------------------------------------------------
# Apply path — direct invocation
# ---------------------------------------------------------------------------


class TestApplyDirect:
    def test_adds_block_and_bumps_version_on_single_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_v1_policy(policy_dir, "cooldowns.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["version"] == 2
        assert data[COMPAT_BLOCK_KEY] == {
            "min_engine_version": MIN_ENGINE_VERSION_VALUE,
        }

    def test_adds_block_to_every_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_v1_policy(policy_dir, "cooldowns.yml")
        _write_v1_policy(policy_dir, "extras.yml")
        _write_v1_policy(policy_dir, "alpha.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 3
        for f in policy_dir.glob("*.yml"):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            assert data["version"] == 2
            assert COMPAT_BLOCK_KEY in data

    def test_empty_policy_dir_is_legitimate(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A fresh OSS install with no policy customization. The
        migration should succeed with affected_count=0 — NOT refuse."""
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        assert result.applied is True

    def test_preserves_rule_block_contents(
        self, policy_dir: Path, state_dir: Path,
    ):
        rules = (
            "rules:\n"
            "  - name: rule1\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
            "    reason: 'test reason'\n"
        )
        f = _write_v1_policy(policy_dir, "cd.yml", rules)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["rules"][0]["name"] == "rule1"
        assert data["rules"][0]["type"] == "cooldown.no-duplicate-register"
        assert data["rules"][0]["block_when"]["register"] == "cold-pitch"

    def test_preserves_comments_in_real_factory_template(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The factory cooldowns.example.yml has 200+ comment lines;
        the migration must preserve all of them."""
        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        original_text = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
        original_comment_count = sum(
            1 for line in original_text.split("\n") if line.lstrip().startswith("#")
        )
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        new_text = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
        new_comment_count = sum(
            1 for line in new_text.split("\n") if line.lstrip().startswith("#")
        )
        # Every comment line preserved.
        assert new_comment_count == original_comment_count

    def test_idempotent_direct_reinvocation(
        self, policy_dir: Path, state_dir: Path,
    ):
        """After a successful apply, calling upgrade again finds
        zero files to migrate (per-file idempotence)."""
        _write_v1_policy(policy_dir, "cooldowns.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        first = MIGRATION.upgrade(ctx)
        assert first.affected_count == 1
        second = MIGRATION.upgrade(ctx)
        assert second.affected_count == 0
        assert second.applied is True  # still "would apply"

    def test_partial_apply_then_finish(
        self, policy_dir: Path, state_dir: Path,
    ):
        """If a previous apply migrated some files but failed on others
        (e.g. the runner crashed mid-batch), re-running picks up the
        unfinished files without double-migrating the finished ones."""
        # Simulate partial state: file1 already migrated, file2 fresh.
        (policy_dir / "alpha.yml").write_text(
            "version: 2\n"
            "engine_compat:\n"
            f"  min_engine_version: '{MIN_ENGINE_VERSION_VALUE}'\n"
            "rules: []\n",
            encoding="utf-8",
        )
        _write_v1_policy(policy_dir, "beta.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        # Only beta.yml gets migrated.
        assert result.affected_count == 1
        assert "1 already at target" in result.notes


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_reports_count_without_writing(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_v1_policy(policy_dir, "cooldowns.yml")
        original_text = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        assert result.dry_run is True
        # File untouched.
        assert f.read_text(encoding="utf-8") == original_text

    def test_dry_run_handles_multiple_files(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_v1_policy(policy_dir, "alpha.yml")
        _write_v1_policy(policy_dir, "beta.yml")
        _write_v1_policy(policy_dir, "gamma.yml")
        ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 3
        # None of them written.
        for f in policy_dir.glob("*.yml"):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            assert data["version"] == 1
            assert COMPAT_BLOCK_KEY not in data


# ---------------------------------------------------------------------------
# Refuse-loud paths
# ---------------------------------------------------------------------------


class TestRefuseLoud:
    def test_refuses_when_policy_dir_missing(
        self, state_dir: Path,
    ):
        ghost = state_dir / "nonexistent_policy_dir"
        ctx = _make_ctx(ghost, state_dir)
        with pytest.raises(FileNotFoundError, match="policy_dir"):
            MIGRATION.upgrade(ctx)

    def test_refuses_unparseable_yaml(
        self, policy_dir: Path, state_dir: Path,
    ):
        (policy_dir / "broken.yml").write_text(
            "version: 1\nrules:\n  - bad: [unbalanced\n",
            encoding="utf-8",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="unparseable"):
            MIGRATION.upgrade(ctx)

    def test_refuses_non_mapping_top_level(
        self, policy_dir: Path, state_dir: Path,
    ):
        (policy_dir / "list.yml").write_text(
            "- this is a list\n- not a mapping\n",
            encoding="utf-8",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="top-level"):
            MIGRATION.upgrade(ctx)

    def test_refuses_inconsistent_state_v2_no_block(
        self, policy_dir: Path, state_dir: Path,
    ):
        """version: 2 + no engine_compat block — operator-corrupted or
        partial-failure state. Refuse loud."""
        (policy_dir / "weird.yml").write_text(
            "version: 2\nrules: []\n", encoding="utf-8",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="lacks the .*engine_compat"):
            MIGRATION.upgrade(ctx)

    def test_refuses_inconsistent_state_v1_with_block(
        self, policy_dir: Path, state_dir: Path,
    ):
        """version: 1 + engine_compat block present — half-migrated.
        Refuse loud."""
        (policy_dir / "weird.yml").write_text(
            "version: 1\n"
            "engine_compat:\n"
            f"  min_engine_version: '{MIN_ENGINE_VERSION_VALUE}'\n"
            "rules: []\n",
            encoding="utf-8",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="version: 1 but already"):
            MIGRATION.upgrade(ctx)

    def test_refuses_unexpected_version_value(
        self, policy_dir: Path, state_dir: Path,
    ):
        """version: 5 (or any non-1, non-2) — not a shape this
        migration knows how to handle."""
        (policy_dir / "future.yml").write_text(
            "version: 5\nrules: []\n", encoding="utf-8",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="version: 5"):
            MIGRATION.upgrade(ctx)


# ---------------------------------------------------------------------------
# Downgrade path
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_removes_block_and_reverts_version(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_v1_policy(policy_dir, "cd.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        # Upgrade first.
        MIGRATION.upgrade(ctx)
        assert yaml.safe_load(f.read_text())["version"] == 2
        # Then downgrade.
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        assert result.applied is False  # downgrade result convention
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert COMPAT_BLOCK_KEY not in data

    def test_downgrade_round_trip_byte_identical(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Upgrade then downgrade should restore byte-identical content
        (the surgical-edit promise)."""
        original = (
            "# Header comment.\n"
            "version: 1\n"
            "\n"
            "rules:\n"
            "  - name: foo\n"
            "    type: bar\n"
            "    reason: 'because'  # trailing comment\n"
        )
        f = policy_dir / "cd.yml"
        f.write_text(original, encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        assert f.read_text(encoding="utf-8") == original

    def test_downgrade_idempotent(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Re-running downgrade after success finds nothing to do."""
        f = _write_v1_policy(policy_dir, "cd.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        first = MIGRATION.downgrade(ctx)
        assert first.affected_count == 1
        second = MIGRATION.downgrade(ctx)
        assert second.affected_count == 0

    def test_downgrade_dry_run_reports_without_writing(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_v1_policy(policy_dir, "cd.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        post_upgrade_text = f.read_text(encoding="utf-8")
        dry_ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.downgrade(dry_ctx)
        assert result.affected_count == 1
        assert result.dry_run is True
        assert f.read_text(encoding="utf-8") == post_upgrade_text

    def test_downgrade_refuses_missing_policy_dir(self, state_dir: Path):
        ghost = state_dir / "nonexistent"
        ctx = _make_ctx(ghost, state_dir)
        with pytest.raises(FileNotFoundError, match="policy_dir"):
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# Runner integration — apply + rollback through MigrationRunner
# ---------------------------------------------------------------------------


class TestRunnerIntegration:
    def test_apply_through_runner_marks_applied(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_v1_policy(policy_dir, "cd.yml")
        runner = _make_runner(state_dir, policy_dir)
        results = runner.apply(MigrationCategory.POLICY)
        assert len(results) == 1
        assert results[0].affected_count == 1
        state = load_state(state_dir)
        assert is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)

    def test_runner_pending_drops_migration_after_apply(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_v1_policy(policy_dir, "cd.yml")
        runner = _make_runner(state_dir, policy_dir)
        assert runner.pending(MigrationCategory.POLICY) == [MIGRATION]
        runner.apply(MigrationCategory.POLICY)
        assert runner.pending(MigrationCategory.POLICY) == []

    def test_runner_dry_run_does_not_mark_applied(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_v1_policy(policy_dir, "cd.yml")
        runner = _make_runner(state_dir, policy_dir)
        runner.dry_run(MigrationCategory.POLICY)
        state = load_state(state_dir)
        assert not is_applied(
            state, MigrationCategory.POLICY, MIGRATION_ID,
        )

    def test_runner_rollback(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_v1_policy(policy_dir, "cd.yml")
        runner = _make_runner(state_dir, policy_dir)
        runner.apply(MigrationCategory.POLICY)
        # Roll back.
        result = runner.rollback(
            MigrationCategory.POLICY, MIGRATION_ID, allow_rollback=True,
        )
        assert result.applied is False
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert COMPAT_BLOCK_KEY not in data
        # State file no longer shows the migration applied.
        state = load_state(state_dir)
        assert not is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)

    def test_runner_rollback_refused_without_explicit_flag(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_v1_policy(policy_dir, "cd.yml")
        runner = _make_runner(state_dir, policy_dir)
        runner.apply(MigrationCategory.POLICY)
        with pytest.raises(ValueError, match="allow_rollback=True"):
            runner.rollback(MigrationCategory.POLICY, MIGRATION_ID)

    def test_per_file_failure_leaves_earlier_intact_and_not_marked(
        self, policy_dir: Path, state_dir: Path,
    ):
        """If file N+1 raises mid-batch, file N's earlier rewrite stays
        on disk (per-file atomicity) BUT the runner does NOT mark the
        migration applied (framework atomicity)."""
        # alpha.yml is valid v1; broken.yml has malformed YAML so the
        # iteration over alpha (which is sorted first) succeeds and
        # writes the bumped file, then broken fails.
        f_alpha = _write_v1_policy(policy_dir, "alpha.yml")
        (policy_dir / "broken.yml").write_text(
            "version: 1\nrules:\n  - bad: [unbalanced\n",
            encoding="utf-8",
        )
        runner = _make_runner(state_dir, policy_dir)
        with pytest.raises(PolicyFileError):
            runner.apply(MigrationCategory.POLICY)
        # alpha.yml was rewritten before broken.yml failed.
        data = yaml.safe_load(f_alpha.read_text(encoding="utf-8"))
        assert data["version"] == 2
        assert COMPAT_BLOCK_KEY in data
        # Migration NOT marked applied.
        state = load_state(state_dir)
        assert not is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)

    def test_resume_after_partial_failure(
        self, policy_dir: Path, state_dir: Path,
    ):
        """After fixing the broken file, re-running apply picks up
        from where the previous run left off."""
        f_alpha = _write_v1_policy(policy_dir, "alpha.yml")
        broken = policy_dir / "broken.yml"
        broken.write_text(
            "version: 1\nrules:\n  - bad: [unbalanced\n",
            encoding="utf-8",
        )
        runner = _make_runner(state_dir, policy_dir)
        with pytest.raises(PolicyFileError):
            runner.apply(MigrationCategory.POLICY)
        # Operator fixes broken.yml.
        broken.write_text("version: 1\nrules: []\n", encoding="utf-8")
        # Re-run apply: alpha is already at v2, broken applies cleanly.
        results = runner.apply(MigrationCategory.POLICY)
        assert results[0].affected_count == 1  # only broken (alpha already done)
        state = load_state(state_dir)
        assert is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)


# ---------------------------------------------------------------------------
# Engine forward-compat — the version-range contract
# ---------------------------------------------------------------------------


class TestEngineForwardCompat:
    """The migration's version bump requires the engine to accept both
    v1 (pre-migration) and v2 (post-migration) so the operator's
    dispatcher never sees a "wrong version" error during the transition
    window between git-pull and migration-apply.
    """

    def test_engine_accepts_v1_files(self, policy_dir: Path):
        """Pre-migration state: file at v1, engine must load."""
        from orchestrator.policy.engine import load_rules_from_yaml
        f = policy_dir / "cd.yml"
        f.write_text("version: 1\nrules: []\n", encoding="utf-8")
        # Should not raise.
        rules = load_rules_from_yaml(f)
        assert rules == []

    def test_engine_accepts_v2_files(self, policy_dir: Path):
        """Post-migration state: file at v2, engine must load."""
        from orchestrator.policy.engine import load_rules_from_yaml
        f = policy_dir / "cd.yml"
        f.write_text(
            "version: 2\n"
            "engine_compat:\n"
            f"  min_engine_version: '{MIN_ENGINE_VERSION_VALUE}'\n"
            "rules: []\n",
            encoding="utf-8",
        )
        rules = load_rules_from_yaml(f)
        assert rules == []

    def test_engine_still_rejects_unsupported_version(
        self, policy_dir: Path,
    ):
        """Range acceptance is bounded — version 999 is still
        rejected. The "wrong version raises" contract from
        ``test_policy_engine.py`` is preserved."""
        from orchestrator.policy.engine import load_rules_from_yaml
        f = policy_dir / "cd.yml"
        f.write_text("version: 999\nrules: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unsupported version"):
            load_rules_from_yaml(f)

    def test_supported_versions_set_contains_both(self):
        """The forward-compat range is declared explicitly so the
        migration framework can audit it."""
        from orchestrator.policy.engine import SUPPORTED_POLICY_SCHEMA_VERSIONS
        assert FROM_VERSION in SUPPORTED_POLICY_SCHEMA_VERSIONS
        assert TO_VERSION in SUPPORTED_POLICY_SCHEMA_VERSIONS


# ---------------------------------------------------------------------------
# Real factory cooldowns.example.yml end-to-end
# ---------------------------------------------------------------------------


class TestRealFactoryTemplateRoundTrip:
    def test_apply_then_downgrade_preserves_bytes(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The migration applied to + reversed off the 275-line factory
        template must produce byte-identical content."""
        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        original = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # Verify the upgraded file loads via the engine (real test of
        # the version-range coordination).
        from orchestrator.policy.engine import load_rules_from_yaml
        from orchestrator.policy import cooldown as _cd  # register rules
        rules = load_rules_from_yaml(policy_dir / "cooldowns.yml")
        # The factory template has 6 active rules (the rest are
        # commented-out templates) — verify they all loaded.
        assert len(rules) == 6
        # Downgrade restores byte-identical original.
        MIGRATION.downgrade(ctx)
        assert (policy_dir / "cooldowns.yml").read_text(encoding="utf-8") == original
