"""Tests for policy migration 0007 — add reply-classifier LLM monthly cap.

Pillar D Week 6-8's per-channel-cap-analog policy migration. SIXTH
policy migration overall; FIRST policy migration of Pillar D. Mirrors
Week 7's ``policy/0002_add_li_invite_weekly_cap`` shape MOST CLOSELY:

* Single rule per migration (one `add_rule_block_text` call per file).
* Same rule class `budget.window-cap`.
* Commented factory rule (operator uncomments to activate).

Structural divergences from Weeks 7-10 (per ADR-0029 D127):

* `source: reply_classifier_llm` — framework-internal source, NOT
  vendor identifier (Weeks 7-10's `linkedin_invite` / `linkedin_dm` /
  `twitter_dm` / `calendar_booking` are dispatcher emitters).
* `window_days: 30` (monthly) — distinct from Weeks 7-9's
  `window_days: 7` weekly AND Week 10's `window_hours: 24` daily.
  Operator budgets LLM spend in monthly terms.
* `max_units: 50` — calibrated against expected ~30 LLM calls/month
  with 1.5-2.5× safety margin (per ADR-0029 D127).

The per-week-review-driven hardening of Week 7 (the
``_policy_io.add_rule_block_text`` primitive's inline-comment +
tab-indent handling; the rules-not-list refuse-loud path) is
inherited verbatim through Weeks 8-11 + Pillar D Week 6-8.

Specifically tests:

* Every policy file gets the canonical rule appended via
  ``_policy_io.add_rule_block_text``.
* Re-apply is idempotent — files already carrying the canonical rule
  name are skipped.
* Files with renamed rules (operator-tuned name) get the canonical
  rule alongside.
* Dry-run reports affected_count without mutation.
* Refuse-loud on ``ctx.policy_dir`` doesn't exist on disk.
* Refuse-loud on unparseable / non-mapping / missing-rules /
  rules-not-a-list policy files.
* Empty policy dir is NOT a refusal — applies cleanly with
  affected_count=0.
* Downgrade removes the canonical-named rule.
* Round-trip (upgrade → downgrade) on the real factory cooldowns.example.yml
  preserves byte-identical content.
* The migration is registered in ``policy.MIGRATIONS`` after policy/0006.
* No file ``version:`` bump (D75/D76 inherited).
* No ``migration_event`` ledger emission (ADR-0012 I5).
* The engine loads the migrated rule as a
  ``BudgetWindowCapRule`` instance.
* The rule's ``source:`` value matches the LLM classifier's
  ``COST_SOURCE`` constant (cross-coupling pin — the rule activates
  the moment the LLM classifier's cost events land in the ledger).

See ``docs/adr/0029-pillar-d-llm-fallback-and-classifier-cap.md`` for
the design rationale.
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
    MigrationRunner,
)
from orchestrator.migrations.policy import (
    MIGRATION_0001_ADD_ENGINE_COMPAT,
    MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN,
    MIGRATION_0007_ADD_REPLY_CLASSIFIER_LLM_CAP,
)
from orchestrator.migrations.policy._policy_io import PolicyFileError
from orchestrator.migrations.policy.migration_0007_add_reply_classifier_llm_cap import (
    MIGRATION,
    MIGRATION_ID,
    RULE_BLOCK_TEXT,
    RULE_MAX_UNITS,
    RULE_NAME,
    RULE_REASON,
    RULE_SOURCE,
    RULE_TYPE,
    RULE_WINDOW_DAYS,
    AddReplyClassifierLlmCap,
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
        registries=registries or {
            MigrationCategory.POLICY: [MIGRATION],
        },
    )


def _make_ctx(
    policy_dir: Path,
    state_dir: Path,
    *,
    dry_run: bool = False,
) -> MigrationContext:
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=state_dir / "ledger",
        vault_dir=None,
        policy_dir=policy_dir,
        now=datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc),
        logger=logging.getLogger("test.migrations.policy.0007"),
    )


# Minimal v2 policy — what an operator has POST-policy/0001.
_V2_POLICY_BASELINE = (
    "version: 2\n"
    "engine_compat:\n"
    "  min_engine_version: '0.1.0'\n"
    "\n"
    "rules:\n"
    "  - name: no-double-cold-pitch\n"
    "    type: cooldown.no-duplicate-register\n"
    "    block_when:\n"
    "      register: cold-pitch\n"
    "    reason: 'Already cold-pitched this person'\n"
)

# Pre-policy/0001 shape (engine still accepts v1).
_V1_POLICY_BASELINE = (
    "version: 1\n"
    "\n"
    "rules:\n"
    "  - name: no-double-cold-pitch\n"
    "    type: cooldown.no-duplicate-register\n"
    "    block_when:\n"
    "      register: cold-pitch\n"
    "    reason: 'Already cold-pitched this person'\n"
)


def _write_policy(policy_dir: Path, name: str, content: str) -> Path:
    f = policy_dir / name
    f.write_text(content, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Migration shape — declared attributes + constants
# ---------------------------------------------------------------------------


class TestMigrationShape:
    def test_migration_id(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0007_add_reply_classifier_llm_cap"

    def test_migration_category(self):
        assert MIGRATION.category == MigrationCategory.POLICY

    def test_migration_is_reversible(self):
        """Adding a rule is reversible — downgrade removes by name."""
        assert MIGRATION.is_reversible is True

    def test_migration_satisfies_protocol(self):
        from orchestrator.migrations.types import Migration as MigrationProto
        assert isinstance(MIGRATION, MigrationProto)

    def test_module_constants_pinned(self):
        """The rule's identifying constants are exported for tests +
        downstream consumers (the LLM classifier's COST_SOURCE +
        Pillar G dashboards consume the source name; the cap migration
        writes it).
        """
        assert RULE_NAME == "reply-classifier-llm-monthly-cap"
        assert RULE_TYPE == "budget.window-cap"
        assert RULE_SOURCE == "reply_classifier_llm"
        assert RULE_WINDOW_DAYS == 30
        assert RULE_MAX_UNITS == 50

    def test_source_matches_llm_classifier_cost_source(self):
        """ADR-0029 D126 — the rule's `source:` value MUST match the
        LLM classifier's `COST_SOURCE` constant. A future divergence
        means the cap activates but never fires (the cost events
        carry the LLM classifier's source; the rule's filter doesn't
        match → no aggregation).

        Cross-coupling pin: this test will fail loudly if either side
        renames without coordinating.
        """
        from orchestrator.reply_classifier_llm import COST_SOURCE
        assert RULE_SOURCE == COST_SOURCE
        assert RULE_SOURCE == "reply_classifier_llm"

    def test_description_mentions_llm_and_cap(self):
        """The operator-facing description names what the migration
        does — the runner surfaces this string in pending / dry-run
        reports."""
        d = MIGRATION.description
        assert "llm" in d.lower()
        assert "cap" in d.lower() or "monthly" in d.lower()
        # The framework-internal naming distinction from vendor sources.
        assert "reply" in d.lower() or "classifier" in d.lower()

    def test_migration_registered_in_policy_init(self):
        """The policy sub-package's MIGRATIONS list must include
        Week 6-8's migration AFTER policy/0006.
        """
        from orchestrator.migrations.policy import MIGRATIONS
        assert MIGRATION_0001_ADD_ENGINE_COMPAT in MIGRATIONS
        assert MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN in MIGRATIONS
        assert MIGRATION_0007_ADD_REPLY_CLASSIFIER_LLM_CAP in MIGRATIONS
        # Ordering: 0006 before 0007.
        idx_0006 = MIGRATIONS.index(
            MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN
        )
        idx_0007 = MIGRATIONS.index(
            MIGRATION_0007_ADD_REPLY_CLASSIFIER_LLM_CAP
        )
        assert idx_0006 < idx_0007

    def test_rule_block_text_shape(self):
        """ADR-0029 D127 — RULE_BLOCK_TEXT contains the canonical fields
        in the right order + the right values. Pinning the byte shape
        catches accidental field reorders or value drifts.
        """
        assert RULE_NAME in RULE_BLOCK_TEXT
        assert RULE_TYPE in RULE_BLOCK_TEXT
        assert f"source: {RULE_SOURCE}" in RULE_BLOCK_TEXT
        assert f"window_days: {RULE_WINDOW_DAYS}" in RULE_BLOCK_TEXT
        assert f"max_units: {RULE_MAX_UNITS}" in RULE_BLOCK_TEXT
        # The reason is quoted per the factory's convention.
        assert f'reason: "{RULE_REASON}"' in RULE_BLOCK_TEXT
        # Leading 2-space indent matches Weeks 7-11's shape.
        assert RULE_BLOCK_TEXT.startswith("  - name:")

    def test_rule_block_text_has_no_block_when_channel(self):
        """ADR-0029 D127 — the LLM cap has NO `block_when.channel:`
        scope. LLM calls are channel-agnostic (Pass G dispatches
        across all REPLY_EVENT_TYPES; the classifier reads body text
        uniformly). Adding a channel scope would mis-fire (the LLM
        cost event isn't channel-scoped per ADR-0006).
        """
        assert "block_when:" not in RULE_BLOCK_TEXT
        assert "channel:" not in RULE_BLOCK_TEXT

    def test_rule_block_text_uses_window_days_not_window_hours(self):
        """ADR-0029 D127 — monthly window. Distinct from Week 10's
        daily cap (`window_hours: 24`).
        """
        assert "window_days: 30" in RULE_BLOCK_TEXT
        assert "window_hours" not in RULE_BLOCK_TEXT

    def test_rule_block_text_uses_max_units_not_max_usd(self):
        """ADR-0029 D127 — units mode (one unit = one LLM call).
        Operators wanting USD mode override at the operator's
        cooldowns.yml.
        """
        assert "max_units: 50" in RULE_BLOCK_TEXT
        assert "max_usd:" not in RULE_BLOCK_TEXT

    def test_policy_migration_does_not_emit_migration_event(
        self, policy_dir: Path, state_dir: Path, tmp_path: Path,
    ):
        """Per ADR-0012 I5: policy migrations write to YAML files, not
        to the ledger, and must NOT emit ``migration_event`` events.
        Same posture as policy/0001-0006.
        """
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = MigrationContext(
            dry_run=False,
            state_dir=state_dir,
            ledger_dir=ledger_dir,
            vault_dir=None,
            policy_dir=policy_dir,
            now=datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc),
            logger=logging.getLogger("test.policy.0007.no_ledger_emit"),
        )
        MIGRATION.upgrade(ctx)
        from orchestrator.migrations.ledger._ledger_io import iter_events
        events = list(iter_events(ledger_dir))
        assert events == []


# ---------------------------------------------------------------------------
# Apply path — direct invocation
# ---------------------------------------------------------------------------


class TestApplyDirect:
    def test_adds_rule_to_v2_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cooldowns.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert RULE_NAME in rules_by_name
        rule = rules_by_name[RULE_NAME]
        assert rule["type"] == RULE_TYPE
        assert rule["source"] == RULE_SOURCE
        assert rule["window_days"] == RULE_WINDOW_DAYS
        assert rule["max_units"] == RULE_MAX_UNITS
        # No block_when.channel — LLM is channel-agnostic.
        assert "block_when" not in rule
        # Pre-existing rule preserved.
        assert "no-double-cold-pitch" in rules_by_name

    def test_adds_rule_to_v1_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Operators who haven't run policy/0001 (file still at v1)
        MUST still receive the rule — the migration is version-tolerant
        across the SUPPORTED set.
        """
        f = _write_policy(policy_dir, "cd.yml", _V1_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert any(r["name"] == RULE_NAME for r in data["rules"])
        # Version not bumped — D76: no schema change.
        assert data["version"] == 1

    def test_does_not_bump_version_v2(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["version"] == 2

    def test_adds_rule_to_every_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(policy_dir, "alpha.yml", _V2_POLICY_BASELINE)
        _write_policy(policy_dir, "beta.yml", _V2_POLICY_BASELINE)
        _write_policy(policy_dir, "cooldowns.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 3
        for f in policy_dir.glob("*.yml"):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            assert any(r["name"] == RULE_NAME for r in data["rules"])

    def test_empty_policy_dir_is_legitimate(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A fresh OSS install with no policy customization — succeed
        with affected_count=0.
        """
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        assert result.applied is True

    def test_preserves_existing_rules_append_semantics(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The pre-existing rule must be FIRST in the list (D73 APPEND
        semantics — operator-installed-first ordering).
        """
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["rules"][0]["name"] == "no-double-cold-pitch"
        assert data["rules"][-1]["name"] == RULE_NAME

    def test_preserves_comments_in_real_factory_template(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The factory cooldowns.example.yml has 200+ comment lines;
        the migration must preserve all of them.
        """
        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        original_text = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
        original_comment_count = sum(
            1 for line in original_text.split("\n") if line.lstrip().startswith("#")
        )
        ctx = _make_ctx(policy_dir, state_dir)
        # The factory already ships the rule in commented form — but
        # commented lines don't count as a rule entry per
        # `_rule_present_by_name`. The migration adds the ACTIVE form.
        MIGRATION.upgrade(ctx)
        new_text = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
        new_comment_count = sum(
            1 for line in new_text.split("\n") if line.lstrip().startswith("#")
        )
        # Every comment line preserved.
        assert new_comment_count == original_comment_count


# ---------------------------------------------------------------------------
# Idempotence — name-match short-circuit
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_re_apply_is_noop(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        # First apply.
        first = MIGRATION.upgrade(ctx)
        assert first.affected_count == 1
        text_after_first = f.read_text(encoding="utf-8")
        # Second apply — idempotent.
        second = MIGRATION.upgrade(ctx)
        assert second.affected_count == 0
        text_after_second = f.read_text(encoding="utf-8")
        assert text_after_first == text_after_second

    def test_renamed_rule_does_not_dedupe(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Operator who renamed the rule (e.g., `my-llm-budget`) keeps
        their version; the migration adds the canonical-named rule
        alongside. The operator dedupes if they want.
        """
        baseline_plus_rename = (
            "version: 2\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "\n"
            "rules:\n"
            "  - name: no-double-cold-pitch\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
            "    reason: 'Already cold-pitched this person'\n"
            "  - name: my-llm-budget\n"
            "    type: budget.window-cap\n"
            "    source: reply_classifier_llm\n"
            "    window_days: 30\n"
            "    max_units: 25\n"
            "    reason: 'Operator-tuned LLM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", baseline_plus_rename)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rule_names = [r["name"] for r in data["rules"]]
        # Both rules present — operator's tuned + canonical.
        assert "my-llm-budget" in rule_names
        assert RULE_NAME in rule_names


# ---------------------------------------------------------------------------
# Dry-run — preview without mutation
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_reports_count_without_mutation(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        original = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.affected_count == 1
        # File unchanged.
        assert f.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Refuse-loud — operator-corrupted state surfaces clearly
# ---------------------------------------------------------------------------


class TestRefuseLoud:
    def test_missing_policy_dir_raises(
        self, tmp_path: Path, state_dir: Path,
    ):
        missing = tmp_path / "does_not_exist"
        ctx = _make_ctx(missing, state_dir)
        with pytest.raises(FileNotFoundError, match="policy migration"):
            MIGRATION.upgrade(ctx)

    def test_unparseable_yaml_raises(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(policy_dir, "broken.yml", "{{{ not valid yaml")
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="unparseable"):
            MIGRATION.upgrade(ctx)

    def test_non_mapping_yaml_raises(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(policy_dir, "list.yml", "- not\n- a\n- mapping\n")
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="must be a mapping"):
            MIGRATION.upgrade(ctx)

    def test_missing_rules_key_raises(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(
            policy_dir, "no_rules.yml",
            "version: 2\nengine_compat:\n  min_engine_version: '0.1.0'\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="missing top-level `rules:`"):
            MIGRATION.upgrade(ctx)

    def test_rules_not_a_list_raises(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Inherited Week 7 P2-A guard."""
        _write_policy(
            policy_dir, "bad_rules.yml",
            "version: 2\nengine_compat:\n"
            "  min_engine_version: '0.1.0'\nrules: some_string\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="not a YAML list"):
            MIGRATION.upgrade(ctx)

    def test_unsupported_version_raises(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(
            policy_dir, "v99.yml",
            "version: 99\nrules: []\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="SUPPORTED_POLICY_SCHEMA_VERSIONS"):
            MIGRATION.upgrade(ctx)


# ---------------------------------------------------------------------------
# Downgrade — removes by canonical name
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_downgrade_removes_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # Verify the rule landed.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert any(r["name"] == RULE_NAME for r in data["rules"])

        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert not any(r["name"] == RULE_NAME for r in data["rules"])
        # Pre-existing rule preserved.
        assert any(r["name"] == "no-double-cold-pitch" for r in data["rules"])

    def test_downgrade_leaves_renamed_rule_alone(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Operator who renamed the canonical rule keeps it through
        downgrade — downgrade matches on canonical name.
        """
        baseline_plus_rename = (
            "version: 2\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "\n"
            "rules:\n"
            "  - name: my-llm-budget\n"
            "    type: budget.window-cap\n"
            "    source: reply_classifier_llm\n"
            "    window_days: 30\n"
            "    max_units: 25\n"
            "    reason: 'Operator-tuned LLM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", baseline_plus_rename)
        ctx = _make_ctx(policy_dir, state_dir)
        # Canonical rule was never installed → downgrade is a no-op.
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 0
        # Renamed rule still there.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert any(r["name"] == "my-llm-budget" for r in data["rules"])

    def test_downgrade_idempotent(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Re-running downgrade after success is a no-op (Pillar A
        ADR-0009 D7 — reversibility means inverse is idempotent).
        """
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        first_down = MIGRATION.downgrade(ctx)
        assert first_down.affected_count == 1
        second_down = MIGRATION.downgrade(ctx)
        assert second_down.affected_count == 0


# ---------------------------------------------------------------------------
# Round-trip — upgrade then downgrade preserves byte-identical content
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_round_trip_on_v2_baseline(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        original = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        assert f.read_text(encoding="utf-8") == original

    def test_round_trip_on_real_factory_template(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The factory template ships the cap as COMMENTED (per
        ADR-0029 D127). Apply ADDS the active rule (commented form is
        a comment, not a rule entry). Downgrade removes only the
        active rule; the commented form stays. Round-trip preserves
        every comment + every uncommented rule.
        """
        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        f = policy_dir / "cooldowns.yml"
        original = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        assert f.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Engine integration — the migrated rule loads as BudgetWindowCapRule
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    def test_engine_loads_migrated_file_as_budget_window_cap(
        self, policy_dir: Path, state_dir: Path,
    ):
        """ADR-0006 + ADR-0029 D127 — the rule's `type:` discriminator
        is `budget.window-cap`. The engine's RULE_REGISTRY constructs
        a `BudgetWindowCapRule` instance from the YAML.

        Verifies the migration writes parseable YAML matching the
        engine's expectations.
        """
        from orchestrator.policy.budget import BudgetWindowCapRule
        from orchestrator.policy.engine import load_rules_from_yaml
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        rules = load_rules_from_yaml(policy_dir / "cd.yml")
        # Find the rule by name.
        matching = [r for r in rules if getattr(r, "name", None) == RULE_NAME]
        assert len(matching) == 1
        rule = matching[0]
        assert isinstance(rule, BudgetWindowCapRule)
        # Verify the configured fields.
        assert rule.source == RULE_SOURCE
        assert rule.window_days == RULE_WINDOW_DAYS
        assert rule.max_units == RULE_MAX_UNITS
        # max_usd is None — units mode.
        assert rule.max_usd is None


# ---------------------------------------------------------------------------
# Runner integration — apply through MigrationRunner
# ---------------------------------------------------------------------------


class TestRunnerIntegration:
    def test_apply_via_runner_marks_applied(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        runner = _make_runner(state_dir, policy_dir)
        results = runner.apply()
        assert len(results) == 1
        assert results[0].applied is True
        state = load_state(state_dir)
        assert is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)

    def test_dry_run_via_runner_does_not_mutate_state(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        runner = _make_runner(state_dir, policy_dir)
        runner.dry_run()
        state = load_state(state_dir)
        assert not is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)


# ---------------------------------------------------------------------------
# No-stale-source-warning invariant — ADR-0029 D127 carries the posture
# ---------------------------------------------------------------------------


class TestNoStaleSourceWarning:
    """ADR-0029 D127 inherits ADRs 0021 D81 + 0022 D86 + 0023 D93 +
    0024 D-N6 — there is NO stale-source detection path. Unlike
    policy/0002 (where ADR-0020 §D77 Shape 1 has a stale-source
    warning for the `source: linkedin` legacy value), the LLM
    classifier-cap source `reply_classifier_llm` is a NEW source name
    introduced in Pillar D Week 6-8; there is no legacy value to warn
    about.

    The negative test pins the absence of the warning path. A future
    contributor reflexively adding a heuristic by mirroring policy/0002
    fails this test.
    """

    def test_no_stale_source_warning_in_migration(self):
        """The migration module does NOT define a `STALE_SOURCE_VALUES`
        constant (Week 7's policy/0002 does, for the legacy
        `source: linkedin` warning).
        """
        from orchestrator.migrations.policy import (
            migration_0007_add_reply_classifier_llm_cap as m,
        )
        # Defensive — no stale-source constant exists.
        assert not hasattr(m, "STALE_SOURCE_VALUES")

    def test_no_warning_logged_for_unrelated_rules(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """A policy file with unrelated rules + the migration runs
        cleanly with no warnings — the per-file walk is non-noisy
        when there's nothing to flag.
        """
        # File with various other source rules; none should warn.
        baseline_with_other_sources = (
            "version: 2\n"
            "engine_compat:\n"
            "  min_engine_version: '0.1.0'\n"
            "rules:\n"
            "  - name: existing-li-cap\n"
            "    type: budget.window-cap\n"
            "    source: linkedin_invite\n"
            "    window_days: 7\n"
            "    max_units: 100\n"
            "    reason: 'LinkedIn invite cap'\n"
        )
        _write_policy(policy_dir, "cd.yml", baseline_with_other_sources)
        ctx = _make_ctx(policy_dir, state_dir)
        with caplog.at_level(logging.WARNING):
            MIGRATION.upgrade(ctx)
        # Verify no WARN-level "stale source" mention in the logs.
        for record in caplog.records:
            assert "stale" not in record.message.lower()
