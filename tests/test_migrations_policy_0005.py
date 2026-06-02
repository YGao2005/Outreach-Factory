"""Tests for policy migration 0005 — add ``calendar-booking-daily-cap`` rule.

Pillar C Week 10's per-channel policy migration. Mirrors Week 9's
``policy/0004_add_tw_dm_weekly_cap`` shape per ADR-0020 D72's per-week
trajectory + ADRs 0021's D79-D83 + 0022's D84-D88 + 0023's D89-D95.

**The structural shape is identical modulo FIVE rule-shape parameters
unique to the Calendar booking channel**: channel filter ``calendar``;
source filter ``calendar_booking``; canonical name
``calendar-booking-daily-cap``; **window unit ``window_hours`` (NOT
``window_days``)**; **max_units default ``10`` (NOT 50)** reflecting the
operator-side-runaway-loop failure-mode framing per ADR-0023 D89.

The per-week-review-driven hardening of Week 7 (the
``_policy_io.add_rule_block_text`` primitive's inline-comment +
tab-indent handling; the rules-not-list refuse-loud path) is inherited
verbatim through Weeks 8 + 9 + 10.

Specifically tests:

* Every policy file with an existing ``rules:`` list gets the canonical
  ``calendar-booking-daily-cap`` rule appended via
  ``_policy_io.add_rule_block_text``.
* Re-apply is idempotent — files already carrying the canonical rule
  name are skipped (D74 rule-name-lookup convention inherited from
  ADR-0020 through ADRs 0021 + 0022 + 0023).
* Operators who renamed the rule (e.g. ``calendar-cap-10``) keep
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
* The migration is registered in ``policy.MIGRATIONS`` after policy/0004.
* No file ``version:`` bump (D75/D76 inherited from ADR-0020 through
  ADRs 0021 + 0022 + 0023 — content-additive migration, no engine
  SUPPORTED set extension).
* No ``migration_event`` ledger emission (policy migrations are ledger-
  silent per ADR-0012 I5).
* Source filter matches Pillar C Week 6 dispatcher emit
  (``source="calendar_booking"`` per ADR-0019 D65).
* **NO stale-source warning path** per ADR-0023 D93. Same posture as
  Weeks 8 + 9's ADRs 0021 D81 + 0022 D86 (the Calendar booking
  dispatcher shipped AFTER ADR-0015 D40's split-source convention; no
  historical factory shape exists for a stale source). This invariant
  is pinned by ``TestNoStaleSourceWarning`` — the migration MUST NOT
  emit a WARNING when the canonical rule has any other ``source:``
  value, because no such pre-existing factory shape ever shipped.

**Window-unit divergence pins (NEW in Week 10):**

* ``test_uses_window_hours_not_window_days`` — the RULE_BLOCK_TEXT
  contains ``window_hours: 24`` and NOT ``window_days: 1``.
* ``test_engine_loads_rule_with_window_hours`` — the engine parses the
  rule's window as 24 hours.
* ``test_rule_uses_units_mode_not_usd_mode`` — the rule has
  ``max_units:`` (not ``max_usd:``). The factory's Rule 9 (commented
  Apollo daily cap) uses ``max_usd:``; Rule 12e uses ``max_units:``.

**Coexistence with ALL prior per-channel cap rules (FOUR cross-migration
tests this week)**: the new Calendar booking cap composes correctly
alongside Week 7's invite cap AND Week 8's LinkedIn DM cap AND Week 9's
Twitter DM cap. The four rules independently throttle four distinct
per-action event streams per the split-source convention (ADR-0015 D40
+ ADR-0016 D43 + ADR-0018 D58 + ADR-0019 D65) AND demonstrate that the
daily-window form composes with the weekly-window form in the same
policy file.

See ``docs/adr/0023-pillar-c-calendar-booking-daily-cap.md`` for the
design rationale.
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
)
from orchestrator.migrations.policy._policy_io import PolicyFileError
from orchestrator.migrations.policy.migration_0005_add_calendar_booking_daily_cap import (
    MIGRATION,
    MIGRATION_ID,
    RULE_BLOCK_TEXT,
    RULE_BLOCK_WHEN_CHANNEL,
    RULE_MAX_UNITS,
    RULE_NAME,
    RULE_SOURCE,
    RULE_TYPE,
    RULE_WINDOW_HOURS,
    AddCalendarBookingDailyCap,
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
        logger=logging.getLogger("test.migrations.policy.0005"),
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
        assert MIGRATION.id == "0005_add_calendar_booking_daily_cap"

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
        assert RULE_NAME == "calendar-booking-daily-cap"
        assert RULE_TYPE == "budget.window-cap"
        assert RULE_SOURCE == "calendar_booking"
        assert RULE_BLOCK_WHEN_CHANNEL == "calendar"
        # Week 10 STRUCTURAL DIVERGENCE: window is hours-based, not days.
        assert RULE_WINDOW_HOURS == 24
        # ADR-0023 D89: 10 link-shares/day, calibrated against the
        # operator-side runaway-loop failure mode (NOT cross-channel
        # consistency with Weeks 7-9's 50). Yang's normal ~3-5/day
        # cadence + 2-3x headroom; catches runaway loops at ~10x normal.
        assert RULE_MAX_UNITS == 10

    def test_description_mentions_calendar_and_cap(self):
        """The operator-facing description names what the migration
        does — the runner surfaces this string in pending / dry-run
        reports."""
        d = MIGRATION.description
        assert "calendar" in d.lower()
        assert "cap" in d.lower() or "daily" in d.lower()

    def test_migration_registered_in_policy_init(self):
        """The policy sub-package's MIGRATIONS list must include the
        Week 10 migration AFTER policy/0004."""
        from orchestrator.migrations.policy import MIGRATIONS
        assert MIGRATION_0001_ADD_ENGINE_COMPAT in MIGRATIONS
        assert MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP in MIGRATIONS
        assert MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP in MIGRATIONS
        # Ordering: 0001 < 0002 < 0003 < 0004 < 0005.
        idx_0001 = MIGRATIONS.index(MIGRATION_0001_ADD_ENGINE_COMPAT)
        idx_0002 = MIGRATIONS.index(MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP)
        idx_0003 = MIGRATIONS.index(MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP)
        idx_0004 = MIGRATIONS.index(MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP)
        idx_0005 = MIGRATIONS.index(MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP)
        assert idx_0001 < idx_0002 < idx_0003 < idx_0004 < idx_0005

    def test_source_matches_pillar_c_week_6_dispatcher_emit(self):
        """Per ADR-0019 D65, Pillar C Week 6's Calendar-booking
        dispatcher emits cost_incurred events with
        source="calendar_booking". The migration's rule MUST match the
        dispatcher's actual emit value — otherwise the rule activates
        but never fires."""
        # The constant is the load-bearing assertion: any future change
        # to the dispatcher's source value forces this test to be
        # updated alongside, which is the coordination contract.
        assert RULE_SOURCE == "calendar_booking"

    def test_source_distinct_from_all_prior_per_channel_sources(self):
        """ADR-0015 D40's split-source convention: calendar_booking is
        a distinct source from linkedin_invite + linkedin_dm +
        twitter_dm. The rule's cap applies to Calendar booking link-
        shares ONLY; the three prior caps gate their own per-action
        streams via Weeks 7 + 8 + 9 rules."""
        from orchestrator.migrations.policy.migration_0002_add_li_invite_weekly_cap import (
            RULE_SOURCE as LI_INVITE_SOURCE,
        )
        from orchestrator.migrations.policy.migration_0003_add_li_dm_weekly_cap import (
            RULE_SOURCE as LI_DM_SOURCE,
        )
        from orchestrator.migrations.policy.migration_0004_add_tw_dm_weekly_cap import (
            RULE_SOURCE as TW_DM_SOURCE,
        )
        assert RULE_SOURCE != LI_INVITE_SOURCE
        assert RULE_SOURCE != LI_DM_SOURCE
        assert RULE_SOURCE != TW_DM_SOURCE

    def test_channel_distinct_from_linkedin_and_twitter(self):
        """Per ADR-0019 D65: Calendar's `channel:` value is `calendar`,
        distinct from LinkedIn's `linkedin` AND Twitter's `twitter`.
        The cross-channel rule's `consider_channels:` matches the
        string exactly, so calendar is an independent join target."""
        from orchestrator.migrations.policy.migration_0003_add_li_dm_weekly_cap import (
            RULE_BLOCK_WHEN_CHANNEL as LI_DM_CHANNEL,
        )
        from orchestrator.migrations.policy.migration_0004_add_tw_dm_weekly_cap import (
            RULE_BLOCK_WHEN_CHANNEL as TW_DM_CHANNEL,
        )
        assert RULE_BLOCK_WHEN_CHANNEL != LI_DM_CHANNEL
        assert RULE_BLOCK_WHEN_CHANNEL != TW_DM_CHANNEL
        assert RULE_BLOCK_WHEN_CHANNEL == "calendar"

    def test_policy_migration_does_not_emit_migration_event(
        self, policy_dir: Path, state_dir: Path, tmp_path: Path,
    ):
        """Per ADR-0012 I5: policy migrations write to YAML files, not
        to the ledger, and must NOT emit ``migration_event`` events.
        Same posture as policy/0001 + policy/0002 + policy/0003 +
        policy/0004."""
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
            logger=logging.getLogger("test.policy.0005.no_ledger_emit"),
        )
        MIGRATION.upgrade(ctx)
        from orchestrator.migrations.ledger._ledger_io import iter_events
        events = list(iter_events(ledger_dir))
        assert events == []


# ---------------------------------------------------------------------------
# Window-unit divergence pins (NEW in Week 10) — ADR-0023 D90
# ---------------------------------------------------------------------------


class TestWindowUnitDivergence:
    """ADR-0023 D90: Week 10 is the first per-channel cap migration to
    use ``window_hours:`` instead of ``window_days:``. The engine
    accepts both forms equivalently per ADR-0006 §"Three concrete rule
    classes"; the cosmetic choice favors operator-facing semantic
    clarity (the hours form makes the daily nature explicit at the
    rule-entry level). These tests pin the divergence so a future
    contributor reflexively copying Week 9's RULE_BLOCK_TEXT format
    (with ``window_days:``) would fail them, surfacing the structural
    difference."""

    def test_uses_window_hours_not_window_days(self):
        """RULE_BLOCK_TEXT contains ``window_hours: 24`` and NOT
        ``window_days:``. The factory file's Rule 9 (commented Apollo
        daily cap) is the precedent for this convention."""
        assert "window_hours: 24" in RULE_BLOCK_TEXT
        assert "window_days:" not in RULE_BLOCK_TEXT

    def test_engine_loads_rule_with_window_hours(
        self, policy_dir: Path, state_dir: Path,
    ):
        """The engine MUST parse the rule's window as 24 hours, with
        ``window_hours`` populated and ``window_days`` left as ``None``.
        Per :class:`BudgetWindowCapRule`'s ``__post_init__`` exactly one
        of the two attributes must be set; Week 10's RULE_BLOCK_TEXT
        uses ``window_hours: 24`` so the constructed rule exposes
        ``window_hours=24`` and ``window_days=None``."""
        from orchestrator.policy import budget as _budget  # register
        from orchestrator.policy import cooldown as _cooldown  # register
        from orchestrator.policy.engine import load_rules_from_yaml

        f = _write_policy(policy_dir, "cd.yml", _V2_POLICY_BASELINE)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        rules = load_rules_from_yaml(f)
        rule = next(r for r in rules if getattr(r, "name", None) == RULE_NAME)
        # Strict assertion: hours form populated; days form is None.
        # The prior conditional-guard shape (`if X is not None: assert
        # X == 24`) silently passed when both attributes were None;
        # the strict assertion catches a future regression that drops
        # one or the other form. Per ADR-0023 D90's window-unit
        # divergence pin.
        assert rule.window_hours == 24
        assert rule.window_days is None

    def test_rule_uses_units_mode_not_usd_mode(self):
        """The factory's Rule 9 (commented Apollo daily cap) uses
        ``max_usd:`` (dollar-budget for Apollo); Rule 12e uses
        ``max_units:`` (count of link-shares). The unit-mode choice
        tracks the cost-event's nature — Cal.com booking-link shares
        emit ``amount_usd=0.0 + units=1`` per ADR-0019 D65, so units
        is the load-bearing field."""
        assert "max_units: 10" in RULE_BLOCK_TEXT
        assert "max_usd:" not in RULE_BLOCK_TEXT


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
        # WEEK 10 DIVERGENCE: window_hours (NOT window_days).
        assert rule["window_hours"] == RULE_WINDOW_HOURS
        assert "window_days" not in rule
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
        """Per D75/D76 inherited from ADR-0020 → ADRs 0021 + 0022 +
        0023: per-channel rule additions do NOT bump the file version.
        The engine continues to accept the unchanged version."""
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
        """Per D74 (inherited from ADR-0020 → ADRs 0021 + 0022 + 0023):
        operators who renamed the rule (different name, canonical filter
        shape) — the migration recognizes their version + adds the
        canonical-named rule alongside. The operator's explicit choice
        to rename is respected; the canonical name becomes available
        for downstream tooling that filters on it."""
        policy_with_renamed = _V2_POLICY_BASELINE + (
            "  - name: calendar-cap-10\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking\n"
            "    window_hours: 24\n"
            "    max_units: 10\n"
            "    reason: 'My calendar booking cap'\n"
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
        assert "calendar-cap-10" in rule_names
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
            "      channel: calendar\n"
            "    source: calendar_booking\n"
            "    window_hours: 24\n"
            "    max_units: 5\n"  # operator tuned tighter for warm-up
            "    reason: 'My conservative calendar cap'\n"
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
        assert rule["max_units"] == 5

    def test_partial_apply_then_finish(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Mixed state: file1 already has the rule; file2 doesn't.
        Re-running picks up file2 without double-migrating file1."""
        policy_with_canonical = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking\n"
            "    window_hours: 24\n"
            "    max_units: 10\n"
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
        policy/0002) has the Calendar booking cap rule added without
        conflict — per-channel split-source convention (ADR-0015 D40 +
        ADR-0019 D65) means both rules coexist + independently throttle
        their respective per-action streams."""
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
        # Sources + channels are distinct per ADR-0015 D40 + ADR-0019 D65.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert rules_by_name["linkedin-weekly-invite-cap"]["source"] == "linkedin_invite"
        assert rules_by_name[RULE_NAME]["source"] == "calendar_booking"
        assert (
            rules_by_name["linkedin-weekly-invite-cap"]["block_when"]["channel"]
            == "linkedin"
        )
        assert rules_by_name[RULE_NAME]["block_when"]["channel"] == "calendar"
        # The cross-window-unit coexistence: LinkedIn invite uses
        # window_days, Calendar uses window_hours — both forms coexist
        # in the same file.
        assert rules_by_name["linkedin-weekly-invite-cap"]["window_days"] == 7
        assert rules_by_name[RULE_NAME]["window_hours"] == 24

    def test_coexists_with_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the LinkedIn DM cap rule (from Week 8's
        policy/0003) has the Calendar booking cap rule added without
        conflict — different rule per channel; window-unit divergence
        (days vs hours) coexists legibly."""
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
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert rules_by_name["linkedin-weekly-dm-cap"]["source"] == "linkedin_dm"
        assert rules_by_name[RULE_NAME]["source"] == "calendar_booking"
        assert rules_by_name["linkedin-weekly-dm-cap"]["block_when"]["channel"] == "linkedin"
        assert rules_by_name[RULE_NAME]["block_when"]["channel"] == "calendar"
        # Cross-window-unit coexistence.
        assert rules_by_name["linkedin-weekly-dm-cap"]["window_days"] == 7
        assert rules_by_name[RULE_NAME]["window_hours"] == 24
        # Max-units divergence reflects different failure-mode
        # framings: 50 platform-side enforcement vs 10 operator-side
        # runaway-loop guardrail.
        assert rules_by_name["linkedin-weekly-dm-cap"]["max_units"] == 50
        assert rules_by_name[RULE_NAME]["max_units"] == 10

    def test_coexists_with_tw_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """A file with the Twitter DM cap rule (from Week 9's
        policy/0004) has the Calendar booking cap rule added without
        conflict — distinct (source, channel) tuples; the per-channel
        split-source convention (ADR-0018 D58 + ADR-0019 D65) means
        each rule fires only against its own dispatcher's cost
        emissions."""
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
        rule_names = [r["name"] for r in data["rules"]]
        assert "twitter-weekly-dm-cap" in rule_names
        assert RULE_NAME in rule_names
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert rules_by_name["twitter-weekly-dm-cap"]["source"] == "twitter_dm"
        assert rules_by_name[RULE_NAME]["source"] == "calendar_booking"
        assert rules_by_name["twitter-weekly-dm-cap"]["block_when"]["channel"] == "twitter"
        assert rules_by_name[RULE_NAME]["block_when"]["channel"] == "calendar"
        # Cross-window-unit + cross-failure-mode divergence.
        assert rules_by_name["twitter-weekly-dm-cap"]["window_days"] == 7
        assert rules_by_name[RULE_NAME]["window_hours"] == 24
        assert rules_by_name["twitter-weekly-dm-cap"]["max_units"] == 50
        assert rules_by_name[RULE_NAME]["max_units"] == 10

    def test_coexists_with_all_prior_per_channel_caps(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: when ALL THREE prior per-channel caps are
        present (the normal post-Week-9 operator state), Week 10's
        Calendar booking cap lands as a FOURTH independent rule. All
        four rules carry distinct (source, channel) tuples and coexist
        without overlap. The daily-window form (calendar) coexists with
        the weekly-window form (linkedin invite/dm + twitter dm) in
        the same policy file."""
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
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_all)
        ctx = _make_ctx(policy_dir, state_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 1
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        rule_names = [r["name"] for r in data["rules"]]
        # All four per-channel caps coexist.
        assert "linkedin-weekly-invite-cap" in rule_names
        assert "linkedin-weekly-dm-cap" in rule_names
        assert "twitter-weekly-dm-cap" in rule_names
        assert RULE_NAME in rule_names
        # Per-rule (source, channel) tuples are pairwise distinct.
        rules_by_name = {r["name"]: r for r in data["rules"]}
        tuples = {
            (rules_by_name[n]["source"], rules_by_name[n]["block_when"]["channel"])
            for n in (
                "linkedin-weekly-invite-cap",
                "linkedin-weekly-dm-cap",
                "twitter-weekly-dm-cap",
                RULE_NAME,
            )
        }
        assert tuples == {
            ("linkedin_invite", "linkedin"),
            ("linkedin_dm", "linkedin"),
            ("twitter_dm", "twitter"),
            ("calendar_booking", "calendar"),
        }
        # Cross-window-unit coexistence: three weekly windows + one
        # daily window in the same file.
        assert rules_by_name["linkedin-weekly-invite-cap"]["window_days"] == 7
        assert rules_by_name["linkedin-weekly-dm-cap"]["window_days"] == 7
        assert rules_by_name["twitter-weekly-dm-cap"]["window_days"] == 7
        assert rules_by_name[RULE_NAME]["window_hours"] == 24


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
# NO stale-source warning path — D93 (ADR-0023)
# ---------------------------------------------------------------------------


class TestNoStaleSourceWarning:
    """ADR-0023 D93: Unlike Week 7's policy/0002 (which warns when
    operators have the canonical-named ``linkedin-weekly-invite-cap``
    rule with the pre-Pillar-C-Week-2 ``source: linkedin`` shape from
    ADR-0008's factory comment), Week 10 has NO analogous staleness path.

    Reason: the Calendar booking dispatcher (ADR-0019) shipped AFTER
    ADR-0015 D40's split-source convention established. There has never
    been a factory-shipped ``calendar-booking-daily-cap`` rule with any
    non-canonical ``source:`` field — the canonical source from day one
    is ``calendar_booking``. No operator could have copied a stale
    factory shape, so no warning is needed.

    Same posture as Weeks 8 + 9's ADRs 0021 D81 + 0022 D86 (the
    LinkedIn DM + Twitter DM dispatchers similarly post-dated the
    split-source convention). The ``TestNoStaleSourceWarning`` pattern
    carries forward verbatim per the Weeks 8 + 9 per-week-review "what
    looks good" item.

    These tests pin the absence of the warning path; a future
    contributor who reflexively adds a "stale source detection" branch
    by mirroring policy/0002 would fail these — surfacing the
    structural difference between Week 10 (no historical factory shape)
    and Week 7 (the original pre-Pillar-C-Week-2 stale shape).
    """

    def test_no_warning_when_canonical_rule_has_source_calendar(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """If an operator hand-wrote a ``calendar-booking-daily-cap``
        rule with ``source: calendar`` (a plausible un-suffixed shape —
        never a factory shape; the dispatcher emits ``calendar_booking``),
        the migration MUST skip without emitting a stale-source
        warning. The operator's deliberate choice of source is
        respected; no doctor-like nagging.

        Contrast with policy/0002 which warns on this exact shape per
        ADR-0020 §D77 Shape 1 (for the LinkedIn-invite case)."""
        policy_with_unusual = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar\n"  # Not the canonical "calendar_booking"
            "    window_hours: 24\n"
            "    max_units: 10\n"
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

    def test_no_warning_when_canonical_rule_has_source_calendar_booking_intent(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """If an operator's ``calendar-booking-daily-cap`` rule has
        ``source: calendar_booking_intent`` (a plausible mis-conflation
        with the event-type prefix per ADR-0019 D65 — the event type
        IS ``calendar_booking_intent`` but the cost-event source is
        just ``calendar_booking``), the migration still skips without
        warning. The operator's source choice is their own — the
        migration's name-match idempotence is intentionally non-
        invasive. Pillar I doctor preflight is the future home for
        misconfig detection."""
        policy_with_event_type_source = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking_intent\n"  # event-type-mis-conflation
            "    window_hours: 24\n"
            "    max_units: 10\n"
            "    reason: 'Event-type-name mis-conflation'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_event_type_source)
        ctx = _make_ctx(policy_dir, state_dir)
        with caplog.at_level(logging.WARNING):
            MIGRATION.upgrade(ctx)
        warning_messages = [
            r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert not any("stale" in m.lower() for m in warning_messages)

    def test_no_warning_when_canonical_rule_has_source_linkedin_invite(
        self, policy_dir: Path, state_dir: Path, caplog,
    ):
        """If an operator's ``calendar-booking-daily-cap`` rule has
        ``source: linkedin_invite`` (a likely copy-paste mistake from
        Week 7's rule), the migration still skips without warning. The
        operator's source choice is their own; copy-paste mistakes are
        detected via the natural feedback loop (dispatcher-not-firing
        observation; the rule activates but reports zero usage)."""
        policy_with_copy_paste = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: linkedin_invite\n"  # likely copy-paste mistake
            "    window_hours: 24\n"
            "    max_units: 10\n"
            "    reason: 'Copy-paste mistake from Week 7 rule'\n"
        )
        _write_policy(policy_dir, "cd.yml", policy_with_copy_paste)
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
        calendar_booking) get NO warning — their rule is healthy."""
        policy_with_correct = _V2_POLICY_BASELINE + (
            f"  - name: {RULE_NAME}\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking\n"  # canonical
            "    window_hours: 24\n"
            "    max_units: 10\n"
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
        through Weeks 8 + 9): downgrade also refuses when `rules:` is
        not a list (mirrors upgrade's guard)."""
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
            "  - name: calendar-cap-10\n"
            "    type: budget.window-cap\n"
            "    block_when:\n"
            "      channel: calendar\n"
            "    source: calendar_booking\n"
            "    window_hours: 24\n"
            "    max_units: 10\n"
            "    reason: 'My calendar booking cap'\n"
        )
        f = _write_policy(policy_dir, "cd.yml", policy_with_both)
        ctx = _make_ctx(policy_dir, state_dir)
        MIGRATION.upgrade(ctx)
        # Migration added canonical-named version.
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_NAME in names
        assert "calendar-cap-10" in names
        # Downgrade: removes only canonical-named version.
        MIGRATION.downgrade(ctx)
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        names = [r["name"] for r in data["rules"]]
        assert RULE_NAME not in names
        assert "calendar-cap-10" in names

    def test_downgrade_does_not_remove_invite_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: downgrading Week 10's Calendar booking cap
        must NOT touch Week 7's LinkedIn invite cap rule. The two are
        name-distinct + the per-channel split-source convention
        (ADR-0015 D40 + ADR-0019 D65) means each rule's downgrade is
        independent."""
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
        # Calendar booking cap removed; LinkedIn invite cap preserved.
        assert RULE_NAME not in names
        assert "linkedin-weekly-invite-cap" in names

    def test_downgrade_does_not_remove_linkedin_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: downgrading Week 10's Calendar booking cap
        must NOT touch Week 8's LinkedIn DM cap rule. Cross-migration
        coexistence per the Weeks 8 + 9 review carry-forward."""
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
        # Calendar booking cap removed; LinkedIn DM cap preserved.
        assert RULE_NAME not in names
        assert "linkedin-weekly-dm-cap" in names

    def test_downgrade_does_not_remove_twitter_dm_cap_rule(
        self, policy_dir: Path, state_dir: Path,
    ):
        """Defense-in-depth: downgrading Week 10's Calendar booking cap
        must NOT touch Week 9's Twitter DM cap rule. Cross-migration
        coexistence per the Weeks 8 + 9 review carry-forward extended
        to Week 10."""
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
        # Calendar booking cap removed; Twitter DM cap preserved.
        assert RULE_NAME not in names
        assert "twitter-weekly-dm-cap" in names

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
# forward through Weeks 8 + 9 + 10: the engine's `load_rules_from_yaml`
# consults `RULE_REGISTRY`, which is populated at import-time by each
# rule-class module. Engine-integration tests in this file explicitly
# import `budget` (and `cooldown` for files referencing cooldown
# rules) inside the test body so the registry side-effect happens
# reliably regardless of test-collection order. Week 11's per-channel
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
        canonical class for window-scoped quota caps. The Week 10 rule
        uses the hours form of the window parameter; the engine MUST
        construct the rule successfully + the constructed rule exposes
        ``window_hours == RULE_WINDOW_HOURS`` (with the sibling
        ``window_days`` field left as ``None`` — see
        :class:`BudgetWindowCapRule`'s ``__post_init__``'s exactly-one
        validation)."""
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
        # Restored from Week 9's mirror (substituted hours-form for
        # days-form; the prior commit dropped the assertion without
        # replacing it; the substitution is the correct mirror).
        assert rule.window_hours == RULE_WINDOW_HOURS
        assert rule.window_days is None
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

    def test_factory_template_has_commented_rule_12e(
        self,
    ):
        """ADR-0023 D92: the factory template ships a commented Rule 12e
        documenting the Calendar booking cap shape for new operators.
        The rule mirrors Rule 12d's structure modulo channel-source /
        window unit / max_units / reason — Pillar C's per-channel
        symmetry."""
        text = FACTORY_TEMPLATE.read_text(encoding="utf-8")
        # The Rule 12e block-comment header is present.
        assert "Rule 12e" in text
        # The commented rule references the canonical name.
        assert "calendar-booking-daily-cap" in text
        # The commented source value matches the canonical Pillar C
        # Week 6 dispatcher emit (per ADR-0019 D65).
        assert "source: calendar_booking" in text
        # The commented default is 10 per ADR-0023 D89 (NOT 50 like
        # Weeks 7-9).
        assert "max_units: 10" in text
        # The commented channel value is calendar (distinct from
        # linkedin + twitter per ADR-0019 D65).
        assert "channel: calendar" in text
        # WEEK 10 DIVERGENCE: window_hours (NOT window_days).
        assert "window_hours: 24" in text

    def test_factory_template_rule_12e_names_operator_side_runaway_framing(
        self,
    ):
        """ADR-0023 D92: Rule 12e's comment is meaningfully longer than
        Rules 12b / 12c / 12d because the operator-side-runaway-loop
        failure-mode framing requires explicit explanation. Operators
        reading the factory file should NOT confuse the cap with a
        platform-published limit; the comment names the framing
        explicitly."""
        text = FACTORY_TEMPLATE.read_text(encoding="utf-8")
        # Locate the Rule 12e block by anchor.
        assert "Rule 12e" in text
        # Extract a window of text around Rule 12e for substring checks.
        idx = text.find("Rule 12e")
        # Take ~100 lines worth of context after the anchor.
        rule_12e_section = text[idx:idx + 5000]
        # The operator-side-runaway-loop framing is explicit.
        assert "runaway" in rule_12e_section.lower() or "loop" in rule_12e_section.lower()
        # The "Cal.com has NO platform-side daily cap" context is
        # explicit (operators reading should understand the cap is
        # operator-deliberate, NOT platform-published).
        assert "Cal.com" in rule_12e_section
        assert "platform-side" in rule_12e_section.lower() or "platform" in rule_12e_section.lower()
