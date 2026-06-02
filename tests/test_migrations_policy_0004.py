"""Tests for policy migration 0004 — add ``twitter-weekly-dm-cap`` rule.

Pillar C Week 9's per-channel policy migration. Mirrors Week 8's
``policy/0003_add_li_dm_weekly_cap`` shape per ADR-0020 D72's per-week
trajectory + ADR-0021's D79-D83 inheritance + ADR-0022's D84-D88. The
structural shape is identical modulo three rule-shape parameters
(channel filter ``twitter``; source filter ``twitter_dm``; canonical
name ``twitter-weekly-dm-cap``); the per-week-review-driven hardening
of Week 7 (the ``_policy_io.add_rule_block_text`` primitive's inline-
comment + tab-indent handling; the rules-not-list refuse-loud path) is
inherited verbatim through both Week 8 + Week 9.

Specifically tests:

* Every policy file with an existing ``rules:`` list gets the canonical
  ``twitter-weekly-dm-cap`` rule appended via ``_policy_io.add_rule_block_text``.
* Re-apply is idempotent — files already carrying the canonical rule
  name are skipped (D74 rule-name-lookup convention inherited from
  ADR-0020 + ADR-0021).
* Operators who renamed the rule (e.g. ``twitter-dm-cap-50``) keep
  their version; the migration adds the canonical-named rule alongside
  per D74.
* Dry-run reports affected_count without mutation.
* Refuse-loud on ``ctx.policy_dir`` doesn't exist on disk.
* Refuse-loud on unparseable / non-mapping / missing-rules /
  rules-not-a-list policy files.
* Empty policy dir is NOT a refusal — applies cleanly with
  affected_count=0.
* Downgrade removes the appended rule by canonical name.
* Round-trip (upgrade → downgrade) on the real factory cooldowns.example.yml
  preserves byte-identical content.
* Per-file failure leaves earlier files intact + migration NOT marked
  applied (framework atomicity contract).
* The migration is registered in ``policy.MIGRATIONS`` after policy/0003.
* No file ``version:`` bump (D75/D76 inherited from ADR-0020 through
  ADR-0021 to ADR-0022 — content-additive migration, no engine SUPPORTED
  set extension).
* No ``migration_event`` ledger emission (policy migrations are ledger-
  silent per ADR-0012 I5).
* Source filter matches Pillar C Week 5 dispatcher emit
  (``source="twitter_dm"`` per ADR-0018 D58).
* **NO stale-source warning path** per ADR-0022 D86. Same posture as
  Week 8's ADR-0021 D81 (the Twitter DM dispatcher shipped AFTER
  ADR-0015 D40's split-source convention; no historical factory shape
  exists for a stale source). This invariant is pinned by
  ``TestNoStaleSourceWarning`` — the migration MUST NOT emit a WARNING
  when the canonical rule has any other ``source:`` value, because no
  such pre-existing factory shape ever shipped.
* **Coexistence with both prior per-channel caps**: the new Twitter DM
  cap composes correctly alongside Week 7's invite cap AND Week 8's
  LinkedIn DM cap. The three rules independently throttle three distinct
  per-action event streams per the split-source convention (ADR-0015
  D40 + ADR-0016 D43 + ADR-0018 D58).

See ``docs/adr/0022-pillar-c-twitter-dm-weekly-cap.md`` for the design
rationale.
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
    MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP,
    MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP,
    MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP,
)
from orchestrator.migrations.policy._policy_io import PolicyFileError
from orchestrator.migrations.policy.migration_0004_add_tw_dm_weekly_cap import (
    MIGRATION,
    MIGRATION_ID,
    RULE_BLOCK_WHEN_CHANNEL,
    RULE_MAX_UNITS,
    RULE_NAME,
    RULE_SOURCE,
    RULE_TYPE,
    RULE_WINDOW_DAYS,
    AddTwitterDMWeeklyCap,
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
        now=datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc),
        logger=logging.getLogger("test.migrations.policy.0004"),
    )


# Minimal v2 policy: structurally what an operator has POST-policy/0001.
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
# Migration shape — declared attributes
# ---------------------------------------------------------------------------


class TestMigrationShape:
    def test_migration_id(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0004_add_tw_dm_weekly_cap"

    def test_migration_category(self):
        assert MIGRATION.category == MigrationCategory.POLICY

    def test_migration_is_reversible(self):
        """Adding a rule is reversible — downgrade removes by name."""
        assert MIGRATION.is_reversible is True

    def test_migration_satisfies_protocol(self):
        from orchestrator.migrations.types import Migration as MigrationProto
        assert isinstance(MIGRATION, MigrationProto)

    def test_module_constants(self):
        """The rule's identifying constants are exported for tests +
        downstream consumers."""
        assert RULE_NAME == "twitter-weekly-dm-cap"
        assert RULE_TYPE == "budget.window-cap"
        assert RULE_SOURCE == "twitter_dm"
        assert RULE_BLOCK_WHEN_CHANNEL == "twitter"
        assert RULE_WINDOW_DAYS == 7
        # ADR-0022 D84: matches Week 8's LinkedIn DM default of 50 for
        # cross-channel consistency. Twitter's recoverable failure mode
        # (cookie-scrape MCP rate-limit + filtered-DM inbox) supports the
        # same default as LinkedIn DM despite differing enforcement
        # surfaces; both channels' cold-outreach intensity profiles +
        # recipient-friction characteristics are similar enough that one
        # default covers the median operator.
        assert RULE_MAX_UNITS == 50

    def test_description_mentions_twitter_dm_and_cap(self):
        """The operator-facing description names what the migration
        does — the runner surfaces this string in pending / dry-run
        reports."""
        d = MIGRATION.description
        assert "twitter" in d.lower()
        assert "dm" in d.lower()
        assert "cap" in d.lower() or "weekly" in d.lower()

    def test_migration_registered_in_policy_init(self):
        """The policy sub-package's MIGRATIONS list must include the
        Week 9 migration AFTER policy/0003."""
        from orchestrator.migrations.policy import MIGRATIONS
        assert MIGRATION_0001_ADD_ENGINE_COMPAT in MIGRATIONS
        assert MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP in MIGRATIONS
        # Ordering: 0001 < 0002 < 0003 < 0004.
        idx_0001 = MIGRATIONS.index(MIGRATION_0001_ADD_ENGINE_COMPAT)
        idx_0002 = MIGRATIONS.index(MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP)
        idx_0003 = MIGRATIONS.index(MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP)
        idx_0004 = MIGRATIONS.index(MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP)
        assert idx_0001 < idx_0002 < idx_0003 < idx_0004

    def test_source_matches_pillar_c_week_5_dispatcher_emit(self):
        """Per ADR-0018 D58, Pillar C Week 5's Twitter-DM dispatcher
        emits cost_incurred events with source="twitter_dm". The
        migration's rule MUST match the dispatcher's actual emit value —
        otherwise the rule activates but never fires."""
        # The constant is the load-bearing assertion: any future change
        # to the dispatcher's source value forces this test to be updated
        # alongside, which is the coordination contract.
        assert RULE_SOURCE == "twitter_dm"

    def test_source_distinct_from_linkedin_sources(self):
        """ADR-0015 D40's split-source convention: twitter_dm is a
        distinct source from linkedin_invite + linkedin_dm. The rule's
        cap applies to Twitter DMs ONLY; the two LinkedIn caps gate
        their own per-action streams via Weeks 7 + 8 rules."""
        from orchestrator.migrations.policy.migration_0002_add_li_invite_weekly_cap import (
            RULE_SOURCE as LI_INVITE_SOURCE,
        )
        from orchestrator.migrations.policy.migration_0003_add_li_dm_weekly_cap import (
            RULE_SOURCE as LI_DM_SOURCE,
        )
        assert RULE_SOURCE != LI_INVITE_SOURCE
        assert RULE_SOURCE != LI_DM_SOURCE

    def test_channel_distinct_from_linkedin(self):
        """Per ADR-0018 D58: Twitter's `channel:` value is `twitter`,
        distinct from LinkedIn's `linkedin`. The cross-channel rule's
        `consider_channels:` matches the string exactly, so the two
        channels are independent join targets."""
        from orchestrator.migrations.policy.migration_0003_add_li_dm_weekly_cap import (
            RULE_BLOCK_WHEN_CHANNEL as LI_DM_CHANNEL,
        )
        assert RULE_BLOCK_WHEN_CHANNEL != LI_DM_CHANNEL
        assert RULE_BLOCK_WHEN_CHANNEL == "twitter"

    def test_policy_migration_does_not_emit_migration_event(
        self, policy_dir: Path, state_dir: Path, tmp_path: Path,
    ):
        """Per ADR-0012 I5: policy migrations write to YAML files, not
        to the ledger, and must NOT emit ``migration_event`` events.
        Same posture as policy/0001 + policy/0002 + policy/0003."""
        ledger_dir = tmp_path / "ledger"
        ledger_dir.mkdir()
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = MigrationContext(
            dry_run=False,
            state_dir=state_dir,
            ledger_dir=ledger_dir,
            vault_dir=None,
            policy_dir=policy_dir,
            now=datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc),
            logger=logging.getLogger("test.policy.0004.no_ledger_emit"),
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
        # Find the migration's appended rule.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert RULE_NAME in rules_by_name
        rule = rules_by_name[RULE_NAME]
        assert rule["type"] == RULE_TYPE
        assert rule["source"] == RULE_SOURCE
        assert rule["block_when"]["channel"] == RULE_BLOCK_WHEN_CHANNEL
        assert rule["window_days"] == RULE_WINDOW_DAYS
        assert rule["max_units"] == RULE_MAX_UNITS
        # Pre-existing rule preserved.
        assert "no-double-cold-pitch" in rules_by_name

    def test_adds_rule_to_v1_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Operators who haven't run policy/0001 (file still at v1) MUST
        still receive the rule — the migration is version-tolerant
        across the SUPPORTED set."""
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
        """Per D75/D76 inherited from ADR-0020 → ADR-0021 → ADR-0022:
        per-channel rule additions do NOT bump the file version. The
        engine continues to accept the unchanged version."""
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
        with affected_count=0."""
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        assert result.applied is True

    def test_preserves_existing_rules(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The pre-existing rule must be byte-equivalent (in semantic
        terms) after the migration — operator-installed rules go first."""
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        # The pre-existing rule must be FIRST in the list (D73 APPEND
        # semantics — operator-installed-first ordering).
        assert data["rules"][0]["name"] == "no-double-cold-pitch"
        assert data["rules"][-1]["name"] == RULE_NAME

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
        # Every comment line preserved (the new rule may add its own
        # explanatory comment header — that's allowed; equality OR the
        # new file has MORE comments than the original).
        assert new_comment_count >= original_comment_count

    def test_idempotent_direct_reinvocation(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Re-applying the migration finds the rule already present +
        skips."""
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        first = MIGRATION.upgrade(ctx)
        assert first.affected_count == 1
        second = MIGRATION.upgrade(ctx)
        assert second.affected_count == 0
        assert second.applied is True
        # The file's rules list has the rule exactly once (no
        # duplicate).
        data = yaml.safe_load(
            (policy_dir / "cd.yml").read_text(encoding="utf-8"),
        )
        count = sum(1 for r in data["rules"] if r.get("name") == RULE_NAME)
        assert count == 1

    def test_idempotent_when_operator_renamed_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Per D74 (inherited from ADR-0020 → ADR-0021 → ADR-0022):
        operators who renamed the rule (different name, canonical filter
        shape) — the migration recognizes their version + adds the
        canonical-named rule alongside. The operator's explicit choice
        to rename is respected; the canonical name becomes available for
        downstream tooling that filters on it."""
        policy_with_renamed = _V2_POLICY_BASELINE + (
            "  - name: twitter-dm-cap-50\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'My Twitter DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_renamed)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        # The migration adds the canonical-named rule, so affected_count=1.
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rule_names = [r.get("name") for r in data["rules"]]
        # Both rules now present — operator's renamed version stays;
        # canonical-named version added.
        assert "twitter-dm-cap-50" in rule_names
        assert RULE_NAME in rule_names

    def test_idempotent_when_exact_canonical_name_already_present(
        self, policy_dir: Path, state_dir: Path,
    ):
        """When the canonical-named rule is already present (manually
        hand-written by the operator), the migration skips entirely.
        The operator's version stays as-is (potentially with different
        max_units / source — operator-deliberate)."""
        policy_with_canonical = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"
            "    window_days: 7\n"
            "    max_units: 30\n"  # operator tuned tighter
            "    reason: 'My conservative Twitter DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_canonical)
        original = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        # File byte-identical (no rewrite).
        assert f.read_text(encoding="utf-8") == original
        # Operator's tuning preserved.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rule = next(r for r in data["rules"] if r["name"] == RULE_NAME)
        assert rule["max_units"] == 30

    def test_partial_apply_then_finish(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Mixed state: file1 already has the rule; file2 doesn't.
        Re-running picks up file2 without double-migrating file1."""
        policy_with_canonical = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'Already manually added'\n"
        )
        _write_policy(policy_dir, "alpha.yml", policy_with_canonical)
        _write_policy(policy_dir, "beta.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        # alpha already had the rule.
        assert "1 already at target" in result.notes or "1 already present" in result.notes

    def test_coexists_with_invite_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the LinkedIn INVITE cap rule (from Week 7's
        policy/0002) has the Twitter DM cap rule added without conflict —
        per-channel split-source convention (ADR-0015 D40 + ADR-0018
        D58) means both rules coexist + independently throttle their
        respective per-action streams."""
        policy_with_invite = _V2_POLICY_BASELINE + (
            "  - name: linkedin-weekly-invite-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    source: linkedin_invite\n"
            "    window_days: 7\n"
            "    max_units: 100\n"
            "    reason: 'LinkedIn weekly invite cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_invite)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rule_names = [r["name"] for r in data["rules"]]
        assert "linkedin-weekly-invite-cap" in rule_names
        assert RULE_NAME in rule_names
        # Sources + channels are distinct per ADR-0015 D40 + ADR-0018 D58.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert rules_by_name["linkedin-weekly-invite-cap"]["source"] == "linkedin_invite"
        assert rules_by_name[RULE_NAME]["source"] == "twitter_dm"
        assert (
            rules_by_name["linkedin-weekly-invite-cap"]["block_when"]["channel"]
            == "linkedin"
        )
        assert rules_by_name[RULE_NAME]["block_when"]["channel"] == "twitter"

    def test_coexists_with_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the LinkedIn DM cap rule (from Week 8's
        policy/0003) has the Twitter DM cap rule added without conflict —
        both DM caps share the rule SHAPE (``budget.window-cap`` + 50
        units / 7 days) but differ on `source:` + `channel:` per the
        split-source convention. Each fires only against its own
        dispatcher's cost emissions."""
        policy_with_li_dm = _V2_POLICY_BASELINE + (
            "  - name: linkedin-weekly-dm-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    source: linkedin_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'LinkedIn weekly DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_li_dm)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rule_names = [r["name"] for r in data["rules"]]
        assert "linkedin-weekly-dm-cap" in rule_names
        assert RULE_NAME in rule_names
        # Both rules carry the same budget.window-cap type + same units
        # + same window — the split is on source + channel.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert rules_by_name["linkedin-weekly-dm-cap"]["type"] == "budget.window-cap"
        assert rules_by_name[RULE_NAME]["type"] == "budget.window-cap"
        assert rules_by_name["linkedin-weekly-dm-cap"]["max_units"] == 50
        assert rules_by_name[RULE_NAME]["max_units"] == 50
        assert rules_by_name["linkedin-weekly-dm-cap"]["source"] == "linkedin_dm"
        assert rules_by_name[RULE_NAME]["source"] == "twitter_dm"
        assert (
            rules_by_name["linkedin-weekly-dm-cap"]["block_when"]["channel"]
            == "linkedin"
        )
        assert rules_by_name[RULE_NAME]["block_when"]["channel"] == "twitter"

    def test_coexists_with_both_prior_per_channel_caps(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: when BOTH Week 7's invite cap AND Week 8's
        LinkedIn DM cap are present (the normal post-Week-8 operator
        state), Week 9's Twitter DM cap lands as a third independent
        rule. All three rules carry distinct (source, channel) tuples
        and coexist without overlap."""
        policy_with_both = _V2_POLICY_BASELINE + (
            "  - name: linkedin-weekly-invite-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    source: linkedin_invite\n"
            "    window_days: 7\n"
            "    max_units: 100\n"
            "    reason: 'LinkedIn weekly invite cap'\n"
            "  - name: linkedin-weekly-dm-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    source: linkedin_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'LinkedIn weekly DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_both)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rule_names = [r["name"] for r in data["rules"]]
        # All three per-channel caps coexist.
        assert "linkedin-weekly-invite-cap" in rule_names
        assert "linkedin-weekly-dm-cap" in rule_names
        assert RULE_NAME in rule_names
        # Per-rule (source, channel) tuples are pairwise distinct.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        tuples = {
            (rules_by_name[n]["source"], rules_by_name[n]["block_when"]["channel"])
            for n in (
                "linkedin-weekly-invite-cap",
                "linkedin-weekly-dm-cap",
                RULE_NAME,
            )
        }
        assert tuples == {
            ("linkedin_invite", "linkedin"),
            ("linkedin_dm", "linkedin"),
            ("twitter_dm", "twitter"),
        }


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_reports_count_without_writing(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        original = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        assert result.dry_run is True
        # File untouched.
        assert f.read_text(encoding="utf-8") == original

    def test_dry_run_handles_multiple_files(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(policy_dir, "alpha.yml", _V2_POLICY_BASELINE)
        _write_policy(policy_dir, "beta.yml", _V2_POLICY_BASELINE)
        _write_policy(policy_dir, "gamma.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 3
        # None of them changed.
        for f in policy_dir.glob("*.yml"):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            rule_names = {r["name"] for r in data["rules"]}
            assert RULE_NAME not in rule_names


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
        _write_policy(
            policy_dir, "broken.yml",
            "version: 2\nrules:\n  - bad: [unbalanced\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="unparseable"):
            MIGRATION.upgrade(ctx)

    def test_refuses_non_mapping_top_level(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(
            policy_dir, "list.yml",
            "- this is a list\n- not a mapping\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="top-level"):
            MIGRATION.upgrade(ctx)

    def test_refuses_unsupported_version(
        self, policy_dir: Path, state_dir: Path,
    ):
        """version: 999 (or any value outside SUPPORTED_POLICY_SCHEMA_VERSIONS)
        is operator-corrupted state — refuse loud."""
        _write_policy(
            policy_dir, "future.yml",
            "version: 999\nrules:\n  - name: r1\n    type: foo\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="version"):
            MIGRATION.upgrade(ctx)

    def test_refuses_missing_rules_key(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A policy file with no `rules:` key at all is an unexpected
        shape — refuse loud rather than silently creating one."""
        _write_policy(
            policy_dir, "weird.yml",
            "version: 2\nengine_compat:\n  min_engine_version: '0.1.0'\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="rules"):
            MIGRATION.upgrade(ctx)

    def test_refuses_rules_null(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Inherited from Week 7's per-week-review P2-A guard: `rules:
        null` (vs `rules: []`) is operator-corrupted state. The text-
        level append helper would otherwise corrupt the file by
        inserting a list-entry after a scalar value."""
        _write_policy(
            policy_dir, "bad.yml",
            "version: 2\nrules: null\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="not a YAML list"):
            MIGRATION.upgrade(ctx)

    def test_refuses_rules_string(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Inherited guard: `rules: some-string` is invalid + refuses
        loud."""
        _write_policy(
            policy_dir, "bad.yml",
            "version: 2\nrules: a-string\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="not a YAML list"):
            MIGRATION.upgrade(ctx)

    def test_refuses_rules_mapping(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Inherited guard: `rules: {}` (map, not list) is invalid +
        refuses loud."""
        _write_policy(
            policy_dir, "bad.yml",
            "version: 2\nrules: {}\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="not a YAML list"):
            MIGRATION.upgrade(ctx)


# ---------------------------------------------------------------------------
# NO stale-source warning path — D86 (ADR-0022)
# ---------------------------------------------------------------------------


class TestNoStaleSourceWarning:
    """ADR-0022 D86: Unlike Week 7's policy/0002 (which warns when
    operators have the canonical-named ``linkedin-weekly-invite-cap``
    rule with the pre-Pillar-C-Week-2 ``source: linkedin`` shape from
    ADR-0008's factory comment), Week 9 has NO analogous staleness path.

    Reason: the Twitter DM dispatcher (ADR-0018) shipped AFTER ADR-0015
    D40's split-source convention established. There has never been a
    factory-shipped ``twitter-weekly-dm-cap`` rule with any non-canonical
    ``source:`` field — the canonical source from day one is
    ``twitter_dm``. No operator could have copied a stale factory shape,
    so no warning is needed.

    Same posture as Week 8's ADR-0021 D81 (the LinkedIn DM dispatcher
    similarly post-dated the split-source convention). The Week 8
    ``TestNoStaleSourceWarning`` pattern carries forward verbatim per
    the Week 8 per-week-review "what looks good" item.

    These tests pin the absence of the warning path; a future
    contributor who reflexively adds a "stale source detection" branch
    by mirroring policy/0002 would fail these — surfacing the
    structural difference between Week 9 (no historical factory shape)
    and Week 7 (the original pre-Pillar-C-Week-2 stale shape).
    """

    def test_no_warning_when_canonical_rule_has_source_twitter(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """If an operator hand-wrote a ``twitter-weekly-dm-cap`` rule
        with ``source: twitter`` (a plausible un-suffixed shape — never
        a factory shape; the dispatcher emits ``twitter_dm``), the
        migration MUST skip without emitting a stale-source warning.
        The operator's deliberate choice of source is respected; no
        doctor-like nagging.

        Contrast with policy/0002 which warns on this exact shape per
        ADR-0020 §D77 Shape 1 (for the LinkedIn-invite case)."""
        policy_with_unusual = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter\n"  # Not the canonical "twitter_dm"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'Operator hand-wrote with non-canonical source'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_unusual)
        ctx = _make_ctx(policy_dir, state_dir)
        with caplog.at_level(logging.WARNING):
            MIGRATION.upgrade(ctx)
        warning_messages = [
            r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        # No staleness warning emitted.
        assert not any("stale" in m.lower() for m in warning_messages)
        assert not any("inert" in m.lower() for m in warning_messages)

    def test_no_warning_when_canonical_rule_has_source_linkedin_dm(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """If an operator's ``twitter-weekly-dm-cap`` rule has
        ``source: linkedin_dm`` (a likely copy-paste mistake from
        Week 8's LinkedIn DM cap rule), the migration still skips
        without warning. The operator's source choice is their own —
        the migration's name-match idempotence is intentionally non-
        invasive. Pillar I doctor preflight is the future home for
        misconfig detection."""
        policy_with_swapped = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: linkedin_dm\n"  # likely copy-paste mistake
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'Copy-paste mistake'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_swapped)
        ctx = _make_ctx(policy_dir, state_dir)
        with caplog.at_level(logging.WARNING):
            MIGRATION.upgrade(ctx)
        warning_messages = [
            r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert not any("stale" in m.lower() for m in warning_messages)

    def test_no_warning_when_canonical_rule_is_correct(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """Operators with the Pillar-C-correct shape (source:
        twitter_dm) get NO warning — their rule is healthy."""
        policy_with_correct = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"  # canonical
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'Correct shape'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_correct)
        ctx = _make_ctx(policy_dir, state_dir)
        with caplog.at_level(logging.WARNING):
            MIGRATION.upgrade(ctx)
        warning_messages = [
            r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert not any("stale" in m.lower() for m in warning_messages)


# ---------------------------------------------------------------------------
# Per-week-review P2-A inheritance: rules-not-list refuse on downgrade too.
# ---------------------------------------------------------------------------


class TestDowngradeRefusesNonListRules:
    def test_downgrade_refuses_rules_null(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth (inherited from Week 7 per-week-review P2-A
        through Week 8): downgrade also refuses when `rules:` is not a
        list (mirrors upgrade's guard)."""
        _write_policy(
            policy_dir, "bad.yml",
            "version: 2\nrules: null\n",
        )
        ctx = _make_ctx(policy_dir, state_dir)
        with pytest.raises(PolicyFileError, match="not a YAML list"):
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# Downgrade path
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_removes_rule_appended_by_upgrade(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # The rule was added.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert any(r["name"] == RULE_NAME for r in data["rules"])
        # Downgrade removes it.
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        assert result.applied is False
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert not any(r["name"] == RULE_NAME for r in data["rules"])
        # Pre-existing rule preserved.
        assert any(r["name"] == "no-double-cold-pitch" for r in data["rules"])

    def test_downgrade_round_trip_byte_identical(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Upgrade then downgrade should restore byte-identical content
        on a synthetic baseline (the surgical-edit promise)."""
        original = _V2_POLICY_BASELINE
        f = _write_policy(policy_dir, "cd.yml", original)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        assert f.read_text(encoding="utf-8") == original

    def test_downgrade_idempotent(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Re-running downgrade after success finds nothing to do."""
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        first = MIGRATION.downgrade(ctx)
        assert first.affected_count == 1
        second = MIGRATION.downgrade(ctx)
        assert second.affected_count == 0

    def test_downgrade_dry_run_reports_without_writing(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        post_upgrade_text = f.read_text(encoding="utf-8")
        dry_ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.downgrade(dry_ctx)
        assert result.affected_count == 1
        assert result.dry_run is True
        assert f.read_text(encoding="utf-8") == post_upgrade_text

    def test_downgrade_does_not_remove_renamed_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """If the operator has a renamed version (different name, same
        filter), downgrade must NOT remove it — only the
        canonical-named rule the migration added."""
        policy_with_both = _V2_POLICY_BASELINE + (
            "  - name: twitter-dm-cap-50\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'My Twitter DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_both)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # Migration added canonical-named version.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_NAME in names
        assert "twitter-dm-cap-50" in names
        # Downgrade: removes only canonical-named version.
        MIGRATION.downgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_NAME not in names
        assert "twitter-dm-cap-50" in names

    def test_downgrade_does_not_remove_invite_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: downgrading Week 9's Twitter DM cap must
        NOT touch Week 7's LinkedIn invite cap rule. The two are
        name-distinct + the per-channel split-source convention
        (ADR-0015 D40) means each rule's downgrade is independent."""
        policy_with_invite = _V2_POLICY_BASELINE + (
            "  - name: linkedin-weekly-invite-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    source: linkedin_invite\n"
            "    window_days: 7\n"
            "    max_units: 100\n"
            "    reason: 'LinkedIn weekly invite cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_invite)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        # Twitter DM cap removed; LinkedIn invite cap preserved.
        assert RULE_NAME not in names
        assert "linkedin-weekly-invite-cap" in names

    def test_downgrade_does_not_remove_linkedin_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: downgrading Week 9's Twitter DM cap must
        NOT touch Week 8's LinkedIn DM cap rule. The two are
        name-distinct + channel-distinct + source-distinct; each rule's
        downgrade is independent of the other's. Cross-migration
        coexistence per the Week 8 review carry-forward."""
        policy_with_li_dm = _V2_POLICY_BASELINE + (
            "  - name: linkedin-weekly-dm-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    source: linkedin_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'LinkedIn weekly DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_li_dm)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        # Twitter DM cap removed; LinkedIn DM cap preserved.
        assert RULE_NAME not in names
        assert "linkedin-weekly-dm-cap" in names

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
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        runner = _make_runner(state_dir, policy_dir)
        results = runner.apply(MigrationCategory.POLICY)
        assert len(results) == 1
        assert results[0].affected_count == 1
        state = load_state(state_dir)
        assert is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)

    def test_runner_pending_drops_migration_after_apply(
        self, policy_dir: Path, state_dir: Path,
    ):
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        runner = _make_runner(state_dir, policy_dir)
        assert runner.pending(MigrationCategory.POLICY) == [MIGRATION]
        runner.apply(MigrationCategory.POLICY)
        assert runner.pending(MigrationCategory.POLICY) == []

    def test_runner_rollback(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        runner = _make_runner(state_dir, policy_dir)
        runner.apply(MigrationCategory.POLICY)
        result = runner.rollback(
            MigrationCategory.POLICY, MIGRATION_ID, allow_rollback=True,
        )
        assert result.applied is False
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert not any(r["name"] == RULE_NAME for r in data["rules"])
        state = load_state(state_dir)
        assert not is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)

    def test_per_file_failure_leaves_earlier_intact_and_not_marked(
        self, policy_dir: Path, state_dir: Path,
    ):
        """If file N+1 raises, file N's earlier rewrite stays on disk
        (per-file atomicity) BUT the runner does NOT mark applied
        (framework atomicity)."""
        f_alpha = _write_policy(policy_dir, "alpha.yml", _V2_POLICY_BASELINE)
        _write_policy(
            policy_dir, "broken.yml",
            "version: 2\nrules:\n  - bad: [unbalanced\n",
        )
        runner = _make_runner(state_dir, policy_dir)
        with pytest.raises(PolicyFileError):
            runner.apply(MigrationCategory.POLICY)
        # alpha was migrated.
        data = yaml.safe_load(f_alpha.read_text(encoding="utf-8"))
        assert any(r["name"] == RULE_NAME for r in data["rules"])
        # But migration NOT marked applied.
        state = load_state(state_dir)
        assert not is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)

    def test_resume_after_partial_failure(
        self, policy_dir: Path, state_dir: Path,
    ):
        """After fixing broken file, re-running picks up unfinished."""
        _write_policy(policy_dir, "alpha.yml", _V2_POLICY_BASELINE)
        broken = policy_dir / "broken.yml"
        broken.write_text(
            "version: 2\nrules:\n  - bad: [unbalanced\n",
            encoding="utf-8",
        )
        runner = _make_runner(state_dir, policy_dir)
        with pytest.raises(PolicyFileError):
            runner.apply(MigrationCategory.POLICY)
        # Fix broken.yml.
        broken.write_text(_V2_POLICY_BASELINE, encoding="utf-8")
        # Re-run: alpha already has the rule; broken gets it now.
        results = runner.apply(MigrationCategory.POLICY)
        assert results[0].affected_count == 1
        state = load_state(state_dir)
        assert is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)


# ---------------------------------------------------------------------------
# Engine integration — the rule loads cleanly post-migration
# ---------------------------------------------------------------------------
#
# Per the Week 7 per-week-review P2-C documentation note carried
# forward through Weeks 8 + 9: the engine's `load_rules_from_yaml`
# consults `RULE_REGISTRY`, which is populated at import-time by each
# rule-class module. Engine-integration tests in this file explicitly
# import `budget` (and `cooldown` for files referencing cooldown
# rules) inside the test body so the registry side-effect happens
# reliably regardless of test-collection order. Weeks 10-11 per-channel
# policy migration tests follow the same pattern; do NOT skip the
# imports.


class TestEngineIntegration:
    def test_engine_loads_migrated_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """After applying the migration, the engine must successfully
        load the policy file and parse the new rule into a
        BudgetWindowCapRule instance."""
        from orchestrator.policy import budget as _budget  # register rule
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy.engine import load_rules_from_yaml

        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)

        rules = load_rules_from_yaml(f)
        rule_names = [getattr(r, "name", None) for r in rules]
        assert RULE_NAME in rule_names

    def test_rule_class_is_budget_window_cap(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The appended rule is a BudgetWindowCapRule instance — the
        canonical class for window-scoped quota caps."""
        from orchestrator.policy.budget import BudgetWindowCapRule
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy.engine import load_rules_from_yaml

        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)

        rules = load_rules_from_yaml(f)
        rule = next(r for r in rules if getattr(r, "name", None) == RULE_NAME)
        assert isinstance(rule, BudgetWindowCapRule)
        assert rule.source == RULE_SOURCE
        assert rule.window_days == RULE_WINDOW_DAYS
        assert rule.max_units == RULE_MAX_UNITS


# ---------------------------------------------------------------------------
# Real factory cooldowns.example.yml end-to-end
# ---------------------------------------------------------------------------


class TestRealFactoryTemplateRoundTrip:
    def test_apply_then_downgrade_preserves_bytes(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The migration applied to + reversed off the real factory
        template must produce byte-identical content."""
        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        original = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        assert (policy_dir / "cooldowns.yml").read_text(encoding="utf-8") == original

    def test_apply_to_factory_template_yields_loadable_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """After applying to the factory template, the engine must still
        load the file — the schema is still valid."""
        from orchestrator.policy import budget as _budget  # register
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy.engine import load_rules_from_yaml

        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        rules = load_rules_from_yaml(policy_dir / "cooldowns.yml")
        # Factory has 6 active rules; migration adds 1 → 7 total.
        rule_names = [getattr(r, "name", None) for r in rules]
        assert RULE_NAME in rule_names
        assert len(rules) == 7

    def test_factory_template_has_commented_rule_12d(
        self,
    ):
        """ADR-0022 D85: the factory template ships a commented Rule 12d
        documenting the Twitter DM cap shape for new operators. The
        rule mirrors Rule 12c's structure modulo channel-source /
        max_units / reason — Pillar C's per-channel symmetry."""
        text = FACTORY_TEMPLATE.read_text(encoding="utf-8")
        # The Rule 12d block-comment header is present.
        assert "Rule 12d" in text
        # The commented rule references the canonical name.
        assert "twitter-weekly-dm-cap" in text
        # The commented source value matches the canonical Pillar C
        # Week 5 dispatcher emit (per ADR-0018 D58).
        assert "source: twitter_dm" in text
        # The commented default is 50 per ADR-0022 D84.
        assert "max_units: 50" in text
        # The commented channel value is twitter (distinct from
        # linkedin per ADR-0018 D58).
        assert "channel: twitter" in text
