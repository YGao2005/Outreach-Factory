"""Tests for policy migration 0006 — add cross-channel email↔LinkedIn cooldown.

Pillar C Week 11's per-channel policy migration. Mirrors Week 10's
``policy/0005_add_calendar_booking_daily_cap`` shape per ADR-0020 D72's
per-week trajectory + ADRs 0021's D79-D83 + 0022's D84-D88 + 0023's
D89-D95 + 0024's D-N1-N8.

**The structural shape diverges from Weeks 7-10 on a DIFFERENT axis from
Week 10's** — Week 10 diverged on window-unit + failure-mode-framing;
Week 11 diverges on FOUR axes per ADR-0024:

1. **TWO rules per migration (not one).** Bidirectional cross-channel
   pair per ADR-0003 §Decision "Two factory rules ship". The migration's
   upgrade() calls ``add_rule_block_text`` TWICE per file (once per
   direction); downgrade() calls ``remove_rule_block_text`` TWICE.
2. **Different rule class: ``cooldown.cross-channel-touch``.** Not
   ``budget.window-cap`` like Weeks 7-10. ``CrossChannelTouchRule``
   instances (per ADR-0003), not ``BudgetWindowCapRule``.
3. **Different field semantics: ``consider_channels:`` not ``source:``.**
   Cross-channel rules query ledger events by ``channel:`` field, not
   ``cost_incurred`` events by ``source:`` field. Per ADR-0003.
4. **Factory rules ALREADY ACTIVE.** Rules 5 + 6 in
   ``config-template/cooldowns.example.yml`` ship uncommented since
   Pillar A Week 2; the migration's job is operator-backfill, not
   factory-rule-activation. Per ADR-0024 D-N3.

The per-week-review-driven hardening of Week 7 (the
``_policy_io.add_rule_block_text`` primitive's inline-comment +
tab-indent handling; the rules-not-list refuse-loud path) is inherited
verbatim through Weeks 8 + 9 + 10 + 11.

Specifically tests:

* Every policy file gets BOTH canonical rules (Rule A + Rule B)
  appended via ``_policy_io.add_rule_block_text`` (called TWICE per
  file).
* Re-apply is idempotent — files already carrying BOTH canonical rule
  names are skipped (Shape A per ADR-0024 §"Existing-operator seed").
* Files with ONE direction installed (Shape B — transitional) get
  ONLY the missing direction inserted.
* Files with both rules renamed (Shape C) get the canonical pair
  added alongside the operator's renamed pair.
* Files with canonical-named rules carrying stale ``consider_channels:``
  values (Shape D) are skipped per name-match idempotence.
* Dry-run reports affected_count without mutation.
* Refuse-loud on ``ctx.policy_dir`` doesn't exist on disk.
* Refuse-loud on unparseable / non-mapping / missing-rules /
  rules-not-a-list policy files.
* Empty policy dir is NOT a refusal — applies cleanly with
  affected_count=0.
* Downgrade removes BOTH canonical-named rules.
* Round-trip (upgrade → downgrade) on the real factory cooldowns.example.yml
  is byte-identical — even though the factory ALREADY has the rules
  (Shape A); apply is a no-op + downgrade removes both + factory's
  active rules are removed by downgrade.
* Per-file failure leaves earlier files intact + migration NOT marked
  applied (framework atomicity contract).
* The migration is registered in ``policy.MIGRATIONS`` after policy/0005.
* No file ``version:`` bump (D75/D76 inherited).
* No ``migration_event`` ledger emission (policy migrations are ledger-
  silent per ADR-0012 I5).
* **NO stale-considered-channels warning path** per ADR-0024 D-N6.
  Same posture as Weeks 8 + 9 + 10's ADRs 0021 D81 + 0022 D86 +
  0023 D93 (no historical factory shape for stale considered_channels
  values; ``TestNoStaleConsiderChannelsWarning`` extends the
  ``TestNoStaleSourceWarning`` pattern to the cross-channel field).

**Rule-class divergence pins (NEW in Week 11):**

* ``test_rule_class_is_cross_channel_touch_not_budget_window_cap`` —
  the engine loads the rules as ``CrossChannelTouchRule`` instances.
* ``test_uses_consider_channels_not_source`` — RULE_A/B_BLOCK_TEXT
  contains ``consider_channels:`` and NOT ``source:``.
* ``test_no_max_units_field`` — RULE_A/B_BLOCK_TEXT contains NO
  ``max_units:`` field (cross-channel-touch rule doesn't take a
  max-units parameter).
* ``test_no_window_hours_field`` — RULE_A/B_BLOCK_TEXT uses
  ``window_days:`` (NOT ``window_hours:``; matching the factory's
  Pillar-A shape per ADR-0024 D-N5).

**Two-rule structure pins (NEW in Week 11):**

* ``test_inserts_both_rules_in_single_apply`` — apply against a
  baseline policy without either rule; both rules appear in result.
* ``test_removes_both_rules_in_single_downgrade`` — downgrade after
  apply removes both.
* ``test_idempotent_when_only_one_direction_present`` — Shape B
  scenario: operator has Rule A but not Rule B; migration inserts
  only Rule B. AND the inverse: operator has Rule B but not Rule A.
* ``test_idempotent_when_both_directions_already_present`` — Shape A
  scenario: both rules already canonical; migration skips both.
* ``test_idempotent_when_both_renamed`` — Shape C scenario.
* ``TestSequentialAddRuleBlockTextComposition`` — verifies the
  ``add_rule_block_text`` primitive is composition-safe when called
  twice in sequence per ADR-0024 D-N2.

**Coexistence with ALL prior per-channel cap rules (FIVE-WAY
cross-migration QUINTET)**: the new cross-channel pair composes
correctly alongside Week 7's invite cap AND Week 8's LinkedIn DM cap
AND Week 9's Twitter DM cap AND Week 10's Calendar booking daily cap.
The six rules (4 per-channel caps + 2 cross-channel rules)
independently throttle six distinct event-stream concerns per the
split-source convention (ADR-0015 D40 + ADR-0016 D43 + ADR-0018 D58 +
ADR-0019 D65) + cross-channel field semantics per ADR-0003.

See ``docs/adr/0024-pillar-c-cross-channel-email-linkedin-cooldown.md``
for the design rationale.
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
    MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP,
    MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN,
)
from orchestrator.migrations.policy._policy_io import (
    PolicyFileError,
    add_rule_block_text,
)
from orchestrator.migrations.policy.migration_0006_add_cross_channel_email_linkedin_cooldown import (
    MIGRATION,
    MIGRATION_ID,
    RULE_A_BLOCK_TEXT,
    RULE_A_BLOCK_WHEN_CHANNEL,
    RULE_A_CONSIDER_CHANNELS,
    RULE_A_NAME,
    RULE_A_REASON,
    RULE_A_TYPE,
    RULE_A_WINDOW_DAYS,
    RULE_B_BLOCK_TEXT,
    RULE_B_BLOCK_WHEN_CHANNEL,
    RULE_B_CONSIDER_CHANNELS,
    RULE_B_NAME,
    RULE_B_REASON,
    RULE_B_TYPE,
    RULE_B_WINDOW_DAYS,
    AddCrossChannelEmailLinkedinCooldown,
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
        logger=logging.getLogger("test.migrations.policy.0006"),
    )


# Minimal v2 policy WITHOUT cross-channel rules — exercises the
# insertion path. The real factory template ALREADY has both rules per
# ADR-0024 D-N3; for the test fixture we explicitly omit them so the
# upgrade path is exercised. The TestRealFactoryTemplateRoundTrip class
# below exercises the alternative path (factory already has both rules
# → migration skips → byte-identical).
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
        assert MIGRATION.id == "0006_add_cross_channel_email_linkedin_cooldown"

    def test_migration_category(self):
        assert MIGRATION.category == MigrationCategory.POLICY

    def test_migration_is_reversible(self):
        """Adding rules is reversible — downgrade removes by name."""
        assert MIGRATION.is_reversible is True

    def test_migration_satisfies_protocol(self):
        from orchestrator.migrations.types import Migration as MigrationProto
        assert isinstance(MIGRATION, MigrationProto)

    def test_module_constants(self):
        """The TWO rule constant sets are exported for tests +
        downstream consumers per ADR-0024 D-N1."""
        # Rule A — email touch suppresses LinkedIn send.
        assert RULE_A_NAME == "cross-channel-email-suppresses-linkedin"
        assert RULE_A_TYPE == "cooldown.cross-channel-touch"
        assert RULE_A_BLOCK_WHEN_CHANNEL == "linkedin"
        assert RULE_A_CONSIDER_CHANNELS == ["email"]
        assert RULE_A_WINDOW_DAYS == 14
        # Rule B — LinkedIn touch suppresses email send (mirror).
        assert RULE_B_NAME == "cross-channel-linkedin-suppresses-email"
        assert RULE_B_TYPE == "cooldown.cross-channel-touch"
        assert RULE_B_BLOCK_WHEN_CHANNEL == "email"
        assert RULE_B_CONSIDER_CHANNELS == ["linkedin"]
        assert RULE_B_WINDOW_DAYS == 14

    def test_two_rules_are_named_distinctly(self):
        """The bidirectional pair MUST have distinct names — the
        migration's idempotence is name-based; identical names would
        make one rule overwrite the other on apply."""
        assert RULE_A_NAME != RULE_B_NAME

    def test_two_rules_are_mirror_symmetric(self):
        """Per ADR-0024 D-N4: the two rules' block_when.channel + the
        consider_channels values are intentionally MIRROR-SWAPPED.
        Rule A fires on channel X, considers channel Y; Rule B fires on
        channel Y, considers channel X. The diagonal-swap is the
        bidirectional shape per ADR-0003."""
        # Rule A's block channel matches Rule B's considered channel.
        assert RULE_A_BLOCK_WHEN_CHANNEL == RULE_B_CONSIDER_CHANNELS[0]
        # Rule B's block channel matches Rule A's considered channel.
        assert RULE_B_BLOCK_WHEN_CHANNEL == RULE_A_CONSIDER_CHANNELS[0]
        # Sanity: not collapsed (the two channels are distinct).
        assert RULE_A_BLOCK_WHEN_CHANNEL != RULE_B_BLOCK_WHEN_CHANNEL

    def test_description_mentions_cross_channel(self):
        """The operator-facing description names what the migration
        does — the runner surfaces this string in pending / dry-run
        reports."""
        d = MIGRATION.description
        assert "cross-channel" in d.lower()
        assert "email" in d.lower()
        assert "linkedin" in d.lower()

    def test_migration_registered_in_policy_init(self):
        """The policy sub-package's MIGRATIONS list must include the
        Week 11 migration AFTER policy/0005."""
        from orchestrator.migrations.policy import MIGRATIONS
        assert MIGRATION_0001_ADD_ENGINE_COMPAT in MIGRATIONS
        assert MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP in MIGRATIONS
        assert MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN in MIGRATIONS
        # Ordering: 0001 < 0002 < 0003 < 0004 < 0005 < 0006.
        idx_0001 = MIGRATIONS.index(MIGRATION_0001_ADD_ENGINE_COMPAT)
        idx_0002 = MIGRATIONS.index(MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP)
        idx_0003 = MIGRATIONS.index(MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP)
        idx_0004 = MIGRATIONS.index(MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP)
        idx_0005 = MIGRATIONS.index(MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP)
        idx_0006 = MIGRATIONS.index(MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN)
        assert idx_0001 < idx_0002 < idx_0003 < idx_0004 < idx_0005 < idx_0006

    def test_policy_migration_does_not_emit_migration_event(
        self, policy_dir: Path, state_dir: Path, tmp_path: Path,
    ):
        """Per ADR-0012 I5: policy migrations write to YAML files, not
        to the ledger, and must NOT emit ``migration_event`` events.
        Same posture as policy/0001 + policy/0002 + policy/0003 +
        policy/0004 + policy/0005."""
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
            logger=logging.getLogger("test.policy.0006.no_ledger_emit"),
        )
        MIGRATION.upgrade(ctx)
        from orchestrator.migrations.ledger._ledger_io import iter_events
        events = list(iter_events(ledger_dir))
        assert events == []


# ---------------------------------------------------------------------------
# Rule-class divergence pins (NEW in Week 11) — ADR-0024 D-N2 + D-N4
# ---------------------------------------------------------------------------


class TestRuleClassDivergence:
    """ADR-0024 D-N2: Week 11 is the first per-channel cap migration to
    write ``cooldown.cross-channel-touch`` rules (Weeks 7-10 all wrote
    ``budget.window-cap``). These tests pin the divergence so a future
    contributor reflexively copying Week 10's RULE_BLOCK_TEXT format
    would fail them, surfacing the structural difference."""

    def test_uses_consider_channels_not_source(self):
        """RULE_A/B_BLOCK_TEXT contains ``consider_channels:`` and NOT
        ``source:``. Per ADR-0024 D-N4 — cross-channel rules query
        ledger events by channel:, NOT cost_incurred events by source:.
        Weeks 7-10 used ``source:`` (the per-channel cap pattern); Week
        11 is the first migration to use ``consider_channels:``."""
        for block_text in (RULE_A_BLOCK_TEXT, RULE_B_BLOCK_TEXT):
            assert "consider_channels:" in block_text
            assert "source:" not in block_text

    def test_no_max_units_field(self):
        """RULE_A/B_BLOCK_TEXT contains NO ``max_units:`` field. The
        cross-channel-touch rule doesn't take a max-units parameter —
        ANY confirmed touch on a considered channel within the window
        blocks (not a counted-threshold semantic like
        ``budget.window-cap`` uses). Per ADR-0003."""
        for block_text in (RULE_A_BLOCK_TEXT, RULE_B_BLOCK_TEXT):
            assert "max_units:" not in block_text
            assert "max_usd:" not in block_text

    def test_no_window_hours_field(self):
        """RULE_A/B_BLOCK_TEXT uses ``window_days:`` (matching the
        factory's Pillar-A shape per ADR-0024 D-N5); NOT
        ``window_hours:`` like Week 10's Calendar booking cap. The
        14-day coordination-perception horizon is multi-day; days is
        the natural unit."""
        for block_text in (RULE_A_BLOCK_TEXT, RULE_B_BLOCK_TEXT):
            assert "window_days: 14" in block_text
            assert "window_hours:" not in block_text

    def test_rule_class_is_cross_channel_touch_not_budget_window_cap(
        self, policy_dir: Path, state_dir: Path,
    ):
        """ADR-0024 D-N2: the engine MUST load the migrated rules as
        ``CrossChannelTouchRule`` instances (NOT ``BudgetWindowCapRule``
        like Weeks 7-10). This is the canonical engine-integration pin
        for the rule-class divergence."""
        from orchestrator.policy import budget as _budget  # register
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy import cross_channel as _cc  # register
        from orchestrator.policy.budget import BudgetWindowCapRule
        from orchestrator.policy.cross_channel import CrossChannelTouchRule
        from orchestrator.policy.engine import load_rules_from_yaml

        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        rules = load_rules_from_yaml(f)
        rule_a = next(r for r in rules if getattr(r, "name", None) == RULE_A_NAME)
        rule_b = next(r for r in rules if getattr(r, "name", None) == RULE_B_NAME)
        # Both rules instantiate as CrossChannelTouchRule.
        assert isinstance(rule_a, CrossChannelTouchRule)
        assert isinstance(rule_b, CrossChannelTouchRule)
        # NEITHER is a BudgetWindowCapRule (the divergence pin).
        assert not isinstance(rule_a, BudgetWindowCapRule)
        assert not isinstance(rule_b, BudgetWindowCapRule)
        # Field values match the migration's constants.
        assert rule_a.consider_channels == RULE_A_CONSIDER_CHANNELS
        assert rule_a.window_days == RULE_A_WINDOW_DAYS
        assert rule_a.block_when == {"channel": RULE_A_BLOCK_WHEN_CHANNEL}
        assert rule_b.consider_channels == RULE_B_CONSIDER_CHANNELS
        assert rule_b.window_days == RULE_B_WINDOW_DAYS
        assert rule_b.block_when == {"channel": RULE_B_BLOCK_WHEN_CHANNEL}


# ---------------------------------------------------------------------------
# Two-rule structure pins (NEW in Week 11) — ADR-0024 D-N1
# ---------------------------------------------------------------------------


class TestTwoRuleStructure:
    """ADR-0024 D-N1: Week 11 ships TWO rules in one migration per the
    bidirectional shape. These tests pin the two-rule-structure
    invariants — apply inserts both rules, downgrade removes both, and
    the various Shape A/B/C scenarios produce the correct file state."""

    def test_inserts_both_rules_in_single_apply(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Per ADR-0024 D-N1: the migration writes BOTH canonical rules
        in one upgrade() call. Operators applying once get the full
        bidirectional pair; no transitional R011-regression state."""
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        # One FILE affected (NOT two rules — the count is file-level).
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rules_by_name = {r["name"]: r for r in data["rules"]}
        # BOTH canonical names present after one apply.
        assert RULE_A_NAME in rules_by_name
        assert RULE_B_NAME in rules_by_name
        # Field values match the migration's constants.
        assert rules_by_name[RULE_A_NAME]["consider_channels"] == RULE_A_CONSIDER_CHANNELS
        assert rules_by_name[RULE_A_NAME]["block_when"]["channel"] == RULE_A_BLOCK_WHEN_CHANNEL
        assert rules_by_name[RULE_B_NAME]["consider_channels"] == RULE_B_CONSIDER_CHANNELS
        assert rules_by_name[RULE_B_NAME]["block_when"]["channel"] == RULE_B_BLOCK_WHEN_CHANNEL

    def test_apply_appends_in_canonical_order_a_then_b(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Deterministic insertion order: Rule A (email-suppresses-
        linkedin) first; Rule B (linkedin-suppresses-email) second.
        APPEND semantics (ADR-0020 D73 inherited)."""
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names_in_order = [r["name"] for r in data["rules"]]
        idx_a = names_in_order.index(RULE_A_NAME)
        idx_b = names_in_order.index(RULE_B_NAME)
        assert idx_a < idx_b, (
            "Rule A (email-suppresses-linkedin) must appear before "
            "Rule B (linkedin-suppresses-email) per the canonical "
            "insertion order"
        )
        # Both go AFTER the pre-existing rule (operator-installed first
        # per D73).
        idx_pre = names_in_order.index("no-double-cold-pitch")
        assert idx_pre < idx_a

    def test_removes_both_rules_in_single_downgrade(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Per ADR-0024 D-N1: downgrade removes BOTH canonical rules in
        one call. Operators rolling back get the full pre-migration
        state restored; no unidirectional-cooldown lingering after
        downgrade."""
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # Sanity: both rules present after upgrade.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
        # Downgrade.
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        # Both canonical names removed.
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
        # Pre-existing rule preserved.
        assert "no-double-cold-pitch" in names

    def test_idempotent_when_both_directions_already_present(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape A scenario (ADR-0024 §"Existing-operator seed"): both
        canonical rules are already present (the MAJORITY case for
        operators who copied the factory post-Pillar-A-Week-2). The
        migration skips both; affected_count = 0; the file is byte-
        identical."""
        policy_with_both_canonical = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
            f"  - name: {RULE_B_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_B_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_both_canonical)
        original = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        # Shape A: both rules present → no file affected.
        assert result.affected_count == 0
        # File byte-identical (no rewrite).
        assert f.read_text(encoding="utf-8") == original

    def test_idempotent_when_only_rule_a_present(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape B scenario (transitional / one-direction-installed —
        Rule A present, Rule B absent): the migration inserts ONLY the
        missing Rule B; the present Rule A stays."""
        policy_with_only_a = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_only_a)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        # File affected (one rule inserted).
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        # Both rules now present.
        assert RULE_A_NAME in names
        # Rule A appears exactly ONCE — no duplicate from the
        # idempotence skip.
        assert names.count(RULE_A_NAME) == 1
        assert RULE_B_NAME in names

    def test_idempotent_when_only_rule_b_present(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape B scenario inverse (Rule B present, Rule A absent):
        the migration inserts ONLY the missing Rule A; the present Rule
        B stays. This is the mirror of the previous test pinning
        symmetric behavior across the two directions."""
        policy_with_only_b = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_B_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_B_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_only_b)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_B_NAME in names
        assert names.count(RULE_B_NAME) == 1
        assert RULE_A_NAME in names

    def test_idempotent_when_both_renamed(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape C scenario (ADR-0024 §"Existing-operator seed"): both
        rules are renamed by the operator (different names; same filter
        shape). The migration adds the canonical-named pair alongside;
        operator ends up with FOUR rules. Operator remediation: delete
        one of the two pairs."""
        policy_with_renamed = _V2_POLICY_BASELINE + (
            "  - name: my-custom-email-blocks-linkedin\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            "    reason: 'My custom email→LinkedIn cooldown'\n"
            "  - name: my-custom-linkedin-blocks-email\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin]\n"
            "    window_days: 14\n"
            "    reason: 'My custom LinkedIn→email cooldown'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_renamed)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        # The migration adds the canonical pair (one file affected).
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        # All FOUR rules present — operator's renamed pair + canonical pair.
        assert "my-custom-email-blocks-linkedin" in names
        assert "my-custom-linkedin-blocks-email" in names
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names


# ---------------------------------------------------------------------------
# Sequential composition pin — ADR-0024 D-N2
# ---------------------------------------------------------------------------


class TestSequentialAddRuleBlockTextComposition:
    """ADR-0024 D-N2: the migration calls ``add_rule_block_text`` TWICE
    in sequence within one upgrade() call. The second call's ``text``
    argument is the result of the first call. The primitive must be
    composition-safe: calling it twice in sequence produces the same
    output as a single insertion of the concatenated two-block string.

    This invariant pins the primitive's behavior for the bundled-
    bidirectional pattern. Future per-channel-pair migrations
    (Pillar D+) rely on the same composition guarantee.
    """

    def test_two_sequential_calls_compose(self):
        """Two sequential ``add_rule_block_text`` calls produce the
        bidirectional pair in the canonical Rule A → Rule B order."""
        base = (
            "version: 2\n"
            "rules:\n"
            "  - name: pre-existing\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
        )
        # Sequential composition: feed result of first call into second.
        intermediate = add_rule_block_text(base, RULE_A_BLOCK_TEXT)
        final = add_rule_block_text(intermediate, RULE_B_BLOCK_TEXT)
        # Parsing confirms BOTH rules are present + in the canonical order.
        data = yaml.safe_load(final)
        names = [r["name"] for r in data["rules"]]
        assert names == ["pre-existing", RULE_A_NAME, RULE_B_NAME]

    def test_sequential_call_equivalent_to_concatenated_block(self):
        """Two sequential calls produce identical output to a single
        call with the concatenated block. Pins the primitive's
        composition-safety as a structural property."""
        base = (
            "version: 2\n"
            "rules:\n"
            "  - name: pre-existing\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
        )
        # Sequential.
        intermediate = add_rule_block_text(base, RULE_A_BLOCK_TEXT)
        sequential = add_rule_block_text(intermediate, RULE_B_BLOCK_TEXT)
        # Single call with concatenated block.
        combined_block = RULE_A_BLOCK_TEXT + RULE_B_BLOCK_TEXT
        single_call = add_rule_block_text(base, combined_block)
        # Outputs are identical.
        assert sequential == single_call

    def test_sequential_calls_idempotent_when_first_block_present(self):
        """When the first block is already present in the input text,
        the second sequential call still inserts the second block
        cleanly. The primitive doesn't enforce idempotence (the
        migration's name-match guards do); but sequential application
        composes regardless of starting state."""
        # The migration guards by name-match BEFORE calling the
        # primitive — so this test verifies the primitive's text-level
        # behavior under a hypothetical "second call without first"
        # composition. The primitive is text-level so it inserts
        # blindly; the migration's name-match wrapper prevents
        # duplication.
        base = (
            "version: 2\n"
            "rules:\n"
            "  - name: pre-existing\n"
            "    type: cooldown.no-duplicate-register\n"
            "    block_when:\n"
            "      register: cold-pitch\n"
        ) + RULE_A_BLOCK_TEXT
        # Add Rule B only (mirrors what the migration does when Shape B
        # — Rule A present, Rule B absent).
        result = add_rule_block_text(base, RULE_B_BLOCK_TEXT)
        data = yaml.safe_load(result)
        names = [r["name"] for r in data["rules"]]
        # All three rules present in order.
        assert names == ["pre-existing", RULE_A_NAME, RULE_B_NAME]


# ---------------------------------------------------------------------------
# Apply path — direct invocation
# ---------------------------------------------------------------------------


class TestApplyDirect:
    def test_adds_rules_to_v2_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cooldowns.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rules_by_name = {r["name"]: r for r in data["rules"]}
        # Rule A.
        assert RULE_A_NAME in rules_by_name
        rule_a = rules_by_name[RULE_A_NAME]
        assert rule_a["type"] == RULE_A_TYPE
        assert rule_a["consider_channels"] == RULE_A_CONSIDER_CHANNELS
        assert rule_a["block_when"]["channel"] == RULE_A_BLOCK_WHEN_CHANNEL
        assert rule_a["window_days"] == RULE_A_WINDOW_DAYS
        assert "source" not in rule_a  # Cross-channel rules don't have source.
        # Rule B.
        assert RULE_B_NAME in rules_by_name
        rule_b = rules_by_name[RULE_B_NAME]
        assert rule_b["type"] == RULE_B_TYPE
        assert rule_b["consider_channels"] == RULE_B_CONSIDER_CHANNELS
        assert rule_b["block_when"]["channel"] == RULE_B_BLOCK_WHEN_CHANNEL
        assert rule_b["window_days"] == RULE_B_WINDOW_DAYS
        assert "source" not in rule_b
        # Pre-existing rule preserved.
        assert "no-double-cold-pitch" in rules_by_name

    def test_adds_rules_to_v1_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Operators who haven't run policy/0001 (file still at v1) MUST
        still receive the rules — the migration is version-tolerant
        across the SUPPORTED set."""
        f = _write_policy(policy_dir, "cd.yml", _V1_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
        # Version not bumped — D76: no schema change.
        assert data["version"] == 1

    def test_does_not_bump_version_v2(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Per D75/D76 inherited: per-channel rule additions do NOT
        bump the file version. The engine continues to accept the
        unchanged version."""
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["version"] == 2

    def test_adds_rules_to_every_file(
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
            names = [r["name"] for r in data["rules"]]
            assert RULE_A_NAME in names
            assert RULE_B_NAME in names

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
        # The two cross-channel rules are last (Rule A then Rule B).
        assert data["rules"][-2]["name"] == RULE_A_NAME
        assert data["rules"][-1]["name"] == RULE_B_NAME

    def test_preserves_comments_in_real_factory_template(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The factory cooldowns.example.yml has 200+ comment lines;
        the migration must preserve all of them. Note: the factory
        ALREADY has Rules 5 + 6 per D-N3 so this is the Shape A path
        (migration skips); comment preservation is therefore trivial
        (file is byte-identical) but the test stays as an invariant
        check."""
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
        assert new_comment_count >= original_comment_count

    def test_idempotent_direct_reinvocation(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Re-applying the migration finds both rules already present +
        skips."""
        _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        first = MIGRATION.upgrade(ctx)
        assert first.affected_count == 1
        second = MIGRATION.upgrade(ctx)
        assert second.affected_count == 0
        assert second.applied is True
        # The file's rules list has BOTH rules exactly once (no duplicates).
        data = yaml.safe_load(
            (policy_dir / "cd.yml").read_text(encoding="utf-8"),
        )
        count_a = sum(1 for r in data["rules"] if r.get("name") == RULE_A_NAME)
        count_b = sum(1 for r in data["rules"] if r.get("name") == RULE_B_NAME)
        assert count_a == 1
        assert count_b == 1

    def test_partial_apply_then_finish(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Mixed state: file1 has both rules (Shape A); file2 has
        neither (new-operator shape). Re-running picks up file2 without
        double-migrating file1."""
        policy_with_both = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
            f"  - name: {RULE_B_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_B_REASON}"\n'
        )
        _write_policy(policy_dir, "alpha.yml", policy_with_both)
        _write_policy(policy_dir, "beta.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        # alpha already had the rules.
        assert "1 already at target" in result.notes

    def test_coexists_with_invite_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the LinkedIn INVITE cap rule (from Week 7's
        policy/0002) has the cross-channel pair added without conflict
        — different rule classes (budget.window-cap vs
        cooldown.cross-channel-touch) coexist legibly in one file."""
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
        names = [r["name"] for r in data["rules"]]
        # Cross-channel pair + invite cap all present.
        assert "linkedin-weekly-invite-cap" in names
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
        # Sanity: the cross-channel rules don't have a `source:` field
        # (per ADR-0024 D-N4); the invite cap does.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert "source" in rules_by_name["linkedin-weekly-invite-cap"]
        assert "source" not in rules_by_name[RULE_A_NAME]
        assert "source" not in rules_by_name[RULE_B_NAME]
        # Cross-channel rules have consider_channels; the invite cap
        # doesn't.
        assert "consider_channels" in rules_by_name[RULE_A_NAME]
        assert "consider_channels" not in rules_by_name["linkedin-weekly-invite-cap"]

    def test_coexists_with_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the LinkedIn DM cap rule (from Week 8's
        policy/0003) has the cross-channel pair added without conflict."""
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
        names = [r["name"] for r in data["rules"]]
        assert "linkedin-weekly-dm-cap" in names
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names

    def test_coexists_with_tw_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the Twitter DM cap rule (from Week 9's
        policy/0004) has the cross-channel pair added without conflict
        — the cross-channel rules are scoped to email + linkedin
        channels; the Twitter DM cap is scoped to twitter channel; no
        overlap."""
        policy_with_tw_dm = _V2_POLICY_BASELINE + (
            "  - name: twitter-weekly-dm-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'Twitter weekly DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_tw_dm)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert "twitter-weekly-dm-cap" in names
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names

    def test_coexists_with_calendar_booking_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the Calendar booking cap rule (from Week 10's
        policy/0005) has the cross-channel pair added without conflict
        — the cross-channel rules use ``window_days: 14``; Calendar
        booking uses ``window_hours: 24``; both forms coexist legibly."""
        policy_with_cal = _V2_POLICY_BASELINE + (
            "  - name: calendar-booking-daily-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking\n"
            "    window_hours: 24\n"
            "    max_units: 10\n"
            "    reason: 'Calendar booking daily cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_cal)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert "calendar-booking-daily-cap" in names
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
        # Cross-window-unit + cross-rule-class coexistence:
        # cross-channel uses window_days; calendar uses window_hours.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert rules_by_name["calendar-booking-daily-cap"]["window_hours"] == 24
        assert rules_by_name[RULE_A_NAME]["window_days"] == 14
        assert rules_by_name[RULE_B_NAME]["window_days"] == 14

    def test_coexists_with_all_prior_per_channel_caps(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: when ALL FOUR prior per-channel caps are
        present (the normal post-Week-10 operator state), Week 11's
        cross-channel pair lands as FIFTH + SIXTH independent rules.
        All six rules carry distinct enforcement concerns: four per-
        channel caps (budget.window-cap with distinct (source, channel)
        tuples) + two cross-channel rules (cooldown.cross-channel-touch
        with mirror-symmetric (block_when.channel, consider_channels)
        tuples). The per-channel-cap pattern + the cross-channel pattern
        coexist without overlap."""
        policy_with_all = _V2_POLICY_BASELINE + (
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
            "  - name: twitter-weekly-dm-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'Twitter weekly DM cap'\n"
            "  - name: calendar-booking-daily-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking\n"
            "    window_hours: 24\n"
            "    max_units: 10\n"
            "    reason: 'Calendar booking daily cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_all)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        # All four prior per-channel caps + the two cross-channel rules.
        assert "linkedin-weekly-invite-cap" in names
        assert "linkedin-weekly-dm-cap" in names
        assert "twitter-weekly-dm-cap" in names
        assert "calendar-booking-daily-cap" in names
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
        rules_by_name = {r["name"]: r for r in data["rules"]}
        # Per-channel caps: distinct (source, channel) tuples.
        per_channel_tuples = {
            (rules_by_name[n]["source"], rules_by_name[n]["block_when"]["channel"])
            for n in (
                "linkedin-weekly-invite-cap",
                "linkedin-weekly-dm-cap",
                "twitter-weekly-dm-cap",
                "calendar-booking-daily-cap",
            )
        }
        assert per_channel_tuples == {
            ("linkedin_invite", "linkedin"),
            ("linkedin_dm", "linkedin"),
            ("twitter_dm", "twitter"),
            ("calendar_booking", "calendar"),
        }
        # Cross-channel rules: mirror-symmetric (block_when.channel,
        # consider_channels) tuples.
        cross_channel_tuples = {
            (
                rules_by_name[n]["block_when"]["channel"],
                tuple(rules_by_name[n]["consider_channels"]),
            )
            for n in (RULE_A_NAME, RULE_B_NAME)
        }
        assert cross_channel_tuples == {
            ("linkedin", ("email",)),
            ("email", ("linkedin",)),
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
            names = {r["name"] for r in data["rules"]}
            assert RULE_A_NAME not in names
            assert RULE_B_NAME not in names

    def test_dry_run_shape_b_counts_one_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape B (one direction present, other absent) is counted as
        ONE file affected — the file IS changed (one rule inserted) but
        only counted at the file level, not at the rule level."""
        policy_with_only_a = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_only_a)
        original = f.read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        # File untouched (dry-run).
        assert f.read_text(encoding="utf-8") == original


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
        null` (vs `rules: []`) is operator-corrupted state."""
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
# NO stale-considered-channels warning path — D-N6 (ADR-0024)
# ---------------------------------------------------------------------------


class TestNoStaleConsiderChannelsWarning:
    """ADR-0024 D-N6: Unlike Week 7's policy/0002 (which warns when
    operators have the canonical-named ``linkedin-weekly-invite-cap``
    rule with the pre-Pillar-C-Week-2 ``source: linkedin`` shape from
    ADR-0008's factory comment), Week 11 has NO analogous staleness path.

    Reason: the factory's Rules 5 + 6 have always shipped
    ``consider_channels: [email]`` and ``[linkedin]`` since Pillar A
    Week 2 per ADR-0003. There has never been a factory-shipped variant
    with a different ``consider_channels:`` value. No operator could
    have copied a stale factory shape; no warning is needed.

    Same posture as Weeks 8 + 9 + 10's ADRs 0021 D81 + 0022 D86 +
    0023 D93 (NO stale-source detection for those weeks). The
    ``TestNoStaleConsiderChannelsWarning`` pattern extends the
    ``TestNoStaleSourceWarning`` carry-forward pattern from Weeks 8-10
    to the cross-channel field.

    These tests pin the absence of the warning path; a future
    contributor who reflexively adds a "stale considered_channels
    detection" branch by mirroring policy/0002 would fail these —
    surfacing the structural difference between Week 11 (no historical
    factory shape) and Week 7 (the original pre-Pillar-C-Week-2 stale
    shape).
    """

    def test_no_warning_when_canonical_rule_a_has_fully_substituted_consider_channels(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """ADR-0024 D-N6 sub-case 1: If an operator hand-wrote the
        ``cross-channel-email-suppresses-linkedin`` rule with
        ``consider_channels: [twitter]`` (fully replacing ``email`` with
        ``twitter``), the migration MUST skip without warning.

        This is the most dangerous substitution variant: the rule has
        the canonical name so the migration considers it present, but it
        will never fire — no ledger events carry ``channel: twitter``
        for the email→LinkedIn coordination purpose. The migration
        respects the operator's choice; staleness detection is
        deliberately absent per ADR-0024 D-N6."""
        policy_with_twitter = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [twitter]\n"  # fully-substituted — silently inert
            "    window_days: 14\n"
            "    reason: 'Operator substituted twitter for email'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_twitter)
        ctx = _make_ctx(policy_dir, state_dir)
        with caplog.at_level(logging.WARNING):
            MIGRATION.upgrade(ctx)
        warning_messages = [
            r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        # No staleness or inertness warning emitted.
        assert not any("stale" in m.lower() for m in warning_messages)
        assert not any("inert" in m.lower() for m in warning_messages)

    def test_no_warning_when_canonical_rule_a_has_stale_consider_channels(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """ADR-0024 D-N6 sub-case 2: If an operator hand-wrote a
        ``cross-channel-email-suppresses-linkedin`` rule with
        ``consider_channels: [email, twitter]`` (a plausible hand-
        edited multi-channel cooldown variant), the migration MUST skip
        without emitting a stale-considered-channels warning. The
        operator's deliberate choice is respected; no doctor-like
        nagging."""
        policy_with_unusual = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email, twitter]\n"  # hand-edited multi-channel variant
            "    window_days: 14\n"
            "    reason: 'Operator hand-wrote with extra channel'\n"
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

    def test_no_warning_when_canonical_rule_b_has_stale_consider_channels(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """Mirror of the previous test — pins the symmetric absence of
        warning for Rule B's hand-edited considered_channels."""
        policy_with_unusual = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_B_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin, twitter]\n"
            "    window_days: 14\n"
            "    reason: 'Operator hand-wrote with extra channel'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_unusual)
        ctx = _make_ctx(policy_dir, state_dir)
        with caplog.at_level(logging.WARNING):
            MIGRATION.upgrade(ctx)
        warning_messages = [
            r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert not any("stale" in m.lower() for m in warning_messages)

    def test_no_warning_when_cross_direction_confusion(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """Cross-direction confusion: operator's Rule A has
        ``consider_channels: [linkedin]`` (confused which direction is
        which). The migration still skips without warning. The
        operator's choice is their own — copy-paste confusions are
        detected via the natural feedback loop (rule fires on the wrong
        events; Pillar G dashboard shows the pattern)."""
        policy_with_confusion = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [linkedin]\n"  # cross-direction confused
            "    window_days: 14\n"
            "    reason: 'Operator confused which direction is which'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_confusion)
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
        """Operators with the Pillar-A-correct shape (consider_channels:
        [email] for Rule A) get NO warning — their rule is healthy.
        This is the negative-control case."""
        policy_with_correct = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"  # canonical
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
            f"  - name: {RULE_B_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin]\n"  # canonical
            "    window_days: 14\n"
            f'    reason: "{RULE_B_REASON}"\n'
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
        through Weeks 8 + 9 + 10): downgrade also refuses when `rules:`
        is not a list."""
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
    def test_removes_both_rules_appended_by_upgrade(
        self, policy_dir: Path, state_dir: Path,
    ):
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # Both rules added.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
        # Downgrade removes both.
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        assert result.applied is False
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
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

    def test_downgrade_does_not_remove_renamed_rules(
        self, policy_dir: Path, state_dir: Path,
    ):
        """If the operator has renamed versions (different names, same
        filter shape), downgrade must NOT remove them — only the
        canonical-named rules the migration added."""
        policy_with_renamed_only = _V2_POLICY_BASELINE + (
            "  - name: my-custom-email-blocks-linkedin\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            "    reason: 'My custom cooldown'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_renamed_only)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # Migration added BOTH canonical rules.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
        assert "my-custom-email-blocks-linkedin" in names
        # Downgrade: removes only canonical-named versions.
        MIGRATION.downgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
        assert "my-custom-email-blocks-linkedin" in names

    def test_downgrade_removes_only_one_direction_if_only_one_present(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape B downgrade: if a file has only Rule A present (not
        Rule B), downgrade removes Rule A. The Rule B removal is a
        no-op (it wasn't present)."""
        policy_with_only_a = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_only_a)
        ctx = _make_ctx(policy_dir, state_dir)
        # Direct downgrade (no upgrade first).
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names

    def test_downgrade_does_not_remove_invite_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: downgrading Week 11's cross-channel pair
        must NOT touch Week 7's LinkedIn invite cap rule. Different
        rule classes; downgrade is name-match scoped."""
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
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
        assert "linkedin-weekly-invite-cap" in names

    def test_downgrade_does_not_remove_linkedin_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: cross-channel downgrade preserves Week 8's
        LinkedIn DM cap."""
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
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
        assert "linkedin-weekly-dm-cap" in names

    def test_downgrade_does_not_remove_twitter_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: cross-channel downgrade preserves Week 9's
        Twitter DM cap."""
        policy_with_tw_dm = _V2_POLICY_BASELINE + (
            "  - name: twitter-weekly-dm-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: twitter\n"
            "    source: twitter_dm\n"
            "    window_days: 7\n"
            "    max_units: 50\n"
            "    reason: 'Twitter weekly DM cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_tw_dm)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
        assert "twitter-weekly-dm-cap" in names

    def test_downgrade_does_not_remove_calendar_booking_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: cross-channel downgrade preserves Week 10's
        Calendar booking cap. Five-way cross-migration carry-forward."""
        policy_with_cal = _V2_POLICY_BASELINE + (
            "  - name: calendar-booking-daily-cap\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking\n"
            "    window_hours: 24\n"
            "    max_units: 10\n"
            "    reason: 'Calendar booking daily cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_cal)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        MIGRATION.downgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
        assert "calendar-booking-daily-cap" in names

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
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names
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
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME in names
        assert RULE_B_NAME in names
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
        # Re-run: alpha already has the rules; broken gets them now.
        results = runner.apply(MigrationCategory.POLICY)
        assert results[0].affected_count == 1
        state = load_state(state_dir)
        assert is_applied(state, MigrationCategory.POLICY, MIGRATION_ID)


# ---------------------------------------------------------------------------
# Engine integration — the rules load cleanly post-migration
# ---------------------------------------------------------------------------
#
# Per the Week 7 per-week-review P2-C documentation note carried
# forward through Weeks 8 + 9 + 10 + 11: the engine's
# `load_rules_from_yaml` consults `RULE_REGISTRY`, which is populated
# at import-time by each rule-class module. Engine-integration tests
# in this file explicitly import `cross_channel` (and `cooldown` for
# files referencing cooldown rules) inside the test body so the
# registry side-effect happens reliably regardless of test-collection
# order. Future per-channel policy migration tests follow the same
# pattern; do NOT skip the imports.


class TestEngineIntegration:
    def test_engine_loads_migrated_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """After applying the migration, the engine must successfully
        load the policy file and parse the two new rules into
        CrossChannelTouchRule instances."""
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy import cross_channel as _cc  # register
        from orchestrator.policy.engine import load_rules_from_yaml

        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)

        rules = load_rules_from_yaml(f)
        rule_names = [getattr(r, "name", None) for r in rules]
        assert RULE_A_NAME in rule_names
        assert RULE_B_NAME in rule_names

    def test_engine_loads_both_rules_independently_evaluable(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The two rules' `evaluate()` methods must be independently
        callable. This is the cross-channel-rule-class engine-
        integration pin — verifies both rules instantiate + can run
        evaluate() without raising."""
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy import cross_channel as _cc  # register
        from orchestrator.policy.engine import load_rules_from_yaml
        from orchestrator.policy.types import RuleContext, Allow

        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)

        rules = load_rules_from_yaml(f)
        rule_a = next(r for r in rules if getattr(r, "name", None) == RULE_A_NAME)
        rule_b = next(r for r in rules if getattr(r, "name", None) == RULE_B_NAME)

        # Build a minimal RuleContext with an empty ledger; both rules
        # should return Allow() (no prior touches).
        class _EmptyLedger:
            def query_by_person(self, person_id):
                return []

            def all_events(self):
                return []

        from datetime import datetime as _dt, timezone as _tz
        eval_ctx = RuleContext(
            person_id="pers_test",
            channel="linkedin",
            register="cold-pitch",
            email=None,
            email_domain=None,
            now=_dt(2026, 5, 22, 12, 0, 0, tzinfo=_tz.utc),
            timezone="America/Los_Angeles",
            ledger=_EmptyLedger(),
        )
        # Rule A fires on linkedin; with no prior touches, returns Allow.
        result_a = rule_a.evaluate(eval_ctx)
        assert isinstance(result_a, Allow)
        # Rule B fires on email; with the linkedin context, the block_when
        # filter doesn't match, returns Allow (per ADR-0001's filter-
        # semantic).
        result_b = rule_b.evaluate(eval_ctx)
        assert isinstance(result_b, Allow)


# ---------------------------------------------------------------------------
# Real factory cooldowns.example.yml end-to-end
# ---------------------------------------------------------------------------


class TestRealFactoryTemplateRoundTrip:
    """The factory template already has Rules 5 + 6 ACTIVE per ADR-0024
    D-N3. The migration's behavior against the factory is Shape A —
    apply is a no-op (both rules already present); downgrade removes
    both rules; round-trip restores the factory's byte-identical
    content (apply is the no-op, downgrade is the removal that needs
    to be inverse-able by manually re-adding the rules via a future
    factory pull)."""

    def test_apply_against_factory_is_noop(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Apply against the factory template (Shape A — both rules
        already present) is a no-op; affected_count = 0; file is
        byte-identical."""
        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        original = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0
        # File byte-identical post-apply (no rewrite per Shape A skip).
        assert (policy_dir / "cooldowns.yml").read_text(encoding="utf-8") == original

    def test_apply_to_factory_template_yields_loadable_file(
        self, policy_dir: Path, state_dir: Path,
    ):
        """After applying to the factory template, the engine must still
        load the file — the schema is still valid (no change made +
        the factory was loadable before)."""
        from orchestrator.policy import budget as _budget  # register
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy import cross_channel as _cc  # register
        from orchestrator.policy.engine import load_rules_from_yaml

        shutil.copy(FACTORY_TEMPLATE, policy_dir / "cooldowns.yml")
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        rules = load_rules_from_yaml(policy_dir / "cooldowns.yml")
        # Factory has 6 active rules; migration is a no-op; still 6.
        rule_names = [getattr(r, "name", None) for r in rules]
        assert RULE_A_NAME in rule_names
        assert RULE_B_NAME in rule_names
        assert len(rules) == 6

    def test_factory_template_has_active_rules_5_and_6(
        self,
    ):
        """ADR-0024 D-N3: the factory template ships Rules 5 + 6 ACTIVE
        (uncommented) since Pillar A Week 2. This is the load-bearing
        invariant for D-N3's no-factory-change posture."""
        text = FACTORY_TEMPLATE.read_text(encoding="utf-8")
        # Both canonical names appear in the factory.
        assert RULE_A_NAME in text
        assert RULE_B_NAME in text
        # The rules are ACTIVE (uncommented). Look for the canonical
        # `- name: <name>` line at column 2 (the active rule shape).
        # Compare with `# - name: <name>` (commented form).
        active_rule_a = f"  - name: {RULE_A_NAME}"
        active_rule_b = f"  - name: {RULE_B_NAME}"
        commented_rule_a = f"  # - name: {RULE_A_NAME}"
        commented_rule_b = f"  # - name: {RULE_B_NAME}"
        assert active_rule_a in text
        assert active_rule_b in text
        # The rules are NOT in commented form anywhere in the factory.
        assert commented_rule_a not in text
        assert commented_rule_b not in text


# ---------------------------------------------------------------------------
# Cross-direction Shape B downgrade scenarios
# ---------------------------------------------------------------------------


class TestShapeBDowngrade:
    """Downgrade behavior across the four shapes (A / B / C / D). Per
    ADR-0024 §"Existing-operator seed" + the downgrade contract."""

    def test_downgrade_shape_a_removes_both(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape A (both rules present): downgrade removes both,
        producing a Shape-without-cross-channel file."""
        policy_with_both = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
            f"  - name: {RULE_B_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_B_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_both)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names
        assert RULE_B_NAME not in names

    def test_downgrade_shape_b_rule_a_only(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape B (only Rule A): downgrade removes Rule A; Rule B was
        already absent."""
        policy_only_a = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_A_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: linkedin\n"
            "    consider_channels: [email]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_A_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_only_a)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_A_NAME not in names

    def test_downgrade_shape_b_rule_b_only(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape B (only Rule B): downgrade removes Rule B; Rule A was
        already absent."""
        policy_only_b = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_B_NAME}\n"
            "    type: cooldown.cross-channel-touch\n"
            "    block_when:\n"
            "      channel: email\n"
            "    consider_channels: [linkedin]\n"
            "    window_days: 14\n"
            f'    reason: "{RULE_B_REASON}"\n'
        )
        f = _write_policy(policy_dir, "cd.yml", policy_only_b)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_B_NAME not in names

    def test_downgrade_no_rules_skips(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Shape no-rules: downgrade is a no-op."""
        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.downgrade(ctx)
        assert result.affected_count == 0
