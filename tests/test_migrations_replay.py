"""End-to-end synthetic-replay tests for the Pillar B migration framework.

This module is the Pillar B exit-criterion's verification vehicle
(PILLAR-PLAN §2: *"the Phase 5.5 backfills replayed cleanly through
the migration runner against a fresh synthetic vault"*).

The tests build a fresh copy of ``tests/fixtures/synthetic_pillar_b/``
in tmp, point a ``MigrationRunner`` at it, and exercise the full
five-migration sequence (vault/0001 → vault/0002 → ledger/0001 →
ledger/0002 → policy/0001 per ADR-0013 D27's apply order) through
the runner's public API.

Week 5 ships foundations: the wrapped backfills + the synthetic
fixture + single-migration + full-batch + dry-run + idempotence
replay tests. Week 6 closes the exit gate (doctor refuse-on-pending
feature flag; ADR-0013 finalization).

See ADR-0013 for the synthetic-replay vehicle design.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from orchestrator.migrations import MigrationRunner
from orchestrator.migrations.ledger._ledger_io import iter_events
from orchestrator.migrations.ledger.migration_0002 import (
    SYNTHETIC_INTENT_PREFIX,
)
from orchestrator.migrations.types import MigrationCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_runner(synthetic_state_dir) -> MigrationRunner:
    """Construct a runner pointed at the synthetic fixture."""
    return MigrationRunner(
        state_dir=synthetic_state_dir.state_dir,
        ledger_dir=synthetic_state_dir.ledger_dir,
        vault_dir=synthetic_state_dir.vault_dir,
        policy_dir=synthetic_state_dir.policy_dir,
        logger=logging.getLogger("test.replay"),
    )


def _events_by_type(ledger_dir: Path, type_name: str) -> list[dict]:
    return [e for e in iter_events(ledger_dir) if e.get("type") == type_name]


def _person_fm(vault_dir: Path, filename: str) -> dict:
    text = (vault_dir / "10 People" / filename).read_text(encoding="utf-8")
    end = text.find("\n---", 4)
    return yaml.safe_load(text[4:end])


def _policy_fm(policy_dir: Path) -> dict:
    text = (policy_dir / "cooldowns.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


# ---------------------------------------------------------------------------
# Synthetic before-state — sanity checks
# ---------------------------------------------------------------------------


class TestSyntheticBeforeState:
    def test_all_pending_migrations_listed(self, synthetic_state_dir):
        """A fresh runner against the synthetic state sees all real
        migrations pending. Pillar B set: 5 migrations. Pillar C Week 2
        adds 2 more (vault/0003 + ledger/0003). Pillar C Week 3 adds
        ledger/0004. Pillar C Week 5 adds ledger/0005. Pillar C Week 6
        adds ledger/0006. Pillar C Week 7 adds policy/0002 (per-channel
        LinkedIn invite cap). Pillar C Week 8 adds policy/0003 (per-
        channel LinkedIn DM cap). Pillar C Week 9 adds policy/0004
        (per-channel Twitter DM cap). Pillar C Week 10 adds policy/0005
        (per-channel Calendar booking daily cap). Pillar C Week 11 adds
        policy/0006 (cross-channel email↔LinkedIn cooldown — TWO rules
        per migration, bidirectional shape per ADR-0003 + ADR-0024).
        Pillar D Week 4-5 adds vault/0004 (conversation_status
        denormalization per ADR-0028 D119). Pillar D Week 6-8 adds
        policy/0007 (reply-classifier LLM monthly cap per
        ADR-0029 D127). Pillar E Week 9-11 adds vault/0005
        (discovery_lineage sub-block per ADR-0036 D168) + ledger/0007
        (backfill enrolled.source_skill per ADR-0036 D170)."""
        runner = _build_runner(synthetic_state_dir)
        pending = runner.pending()
        assert len(pending) == 19
        ids = [m.id for m in pending]
        assert ids == [
            "0001_add_schema_version_to_person_notes",              # vault
            "0002_backfill_identity_lineage",                        # vault
            "0003_add_linkedin_action_to_touch_notes",               # vault (Pillar C Week 2)
            "0004_add_conversation_status_to_person_notes",          # vault (Pillar D Week 4-5)
            "0005_add_discovery_lineage_to_identity_keys",           # vault (Pillar E Week 9-11)
            "0001_close_orphan_send_intents",                        # ledger
            "0002_backfill_send_history",                            # ledger
            "0003_baseline_li_invite_history",                       # ledger (Pillar C Week 2)
            "0004_baseline_li_dm_history",                           # ledger (Pillar C Week 3)
            "0005_baseline_tw_dm_history",                           # ledger (Pillar C Week 5)
            "0006_baseline_calendar_booking_history",                # ledger (Pillar C Week 6)
            "0007_backfill_enrolled_source_skill",                   # ledger (Pillar E Week 9-11)
            "0001_add_engine_compat_field",                          # policy
            "0002_add_li_invite_weekly_cap",                         # policy (Pillar C Week 7)
            "0003_add_li_dm_weekly_cap",                             # policy (Pillar C Week 8)
            "0004_add_tw_dm_weekly_cap",                             # policy (Pillar C Week 9)
            "0005_add_calendar_booking_daily_cap",                   # policy (Pillar C Week 10)
            "0006_add_cross_channel_email_linkedin_cooldown",        # policy (Pillar C Week 11)
            "0007_add_reply_classifier_llm_cap",                     # policy (Pillar D Week 6-8)
        ]

    def test_default_apply_order_is_vault_first(self, synthetic_state_dir):
        """Per ADR-0013 D27 + ADR-0014 D34 default apply order is
        VAULT → LEDGER → POLICY. Pillar C Week 2's vault/0003 +
        ledger/0003 + Week 3's ledger/0004 + Week 5's ledger/0005 +
        Week 6's ledger/0006 + Week 7's policy/0002 + Week 8's
        policy/0003 + Week 9's policy/0004 + Week 10's policy/0005 +
        Week 11's policy/0006 + Pillar D Week 4-5's vault/0004 +
        Pillar E Week 9-11's vault/0005 + ledger/0007 all slot into
        this order without amendment."""
        runner = _build_runner(synthetic_state_dir)
        pending = runner.pending()
        # 5 VAULT migrations (0001-0005), 7 LEDGER migrations
        # (0001-0007), 7 POLICY migrations (0001-0007) = 19 total.
        for i in range(5):
            assert pending[i].category == MigrationCategory.VAULT
        for i in range(5, 12):
            assert pending[i].category == MigrationCategory.LEDGER
        for i in range(12, 19):
            assert pending[i].category == MigrationCategory.POLICY

    def test_person_notes_lack_id_pre_migration(self, synthetic_state_dir):
        """The synthetic fixture is a fresh-Phase-5.5 before-state."""
        for name in ("Alice Anderson.md", "Bob Brown.md", "Carol Cole.md"):
            fm = _person_fm(synthetic_state_dir.vault_dir, name)
            assert "id" not in fm
            assert "identity_keys" not in fm
            assert "schema_version" not in fm

    def test_policy_at_version_1(self, synthetic_state_dir):
        """The synthetic policy is at version 1, no engine_compat."""
        fm = _policy_fm(synthetic_state_dir.policy_dir)
        assert fm["version"] == 1
        assert "engine_compat" not in fm

    def test_pre_existing_orphan_intent(self, synthetic_state_dir):
        """One pre-existing send_intent with no outcome (for ledger/0001)."""
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_intent",
        )
        outcomes = (
            _events_by_type(synthetic_state_dir.ledger_dir, "send_confirmed")
            + _events_by_type(
                synthetic_state_dir.ledger_dir, "send_failed",
            )
            + _events_by_type(
                synthetic_state_dir.ledger_dir, "send_aborted",
            )
        )
        # Exactly one orphan: the seeded snd_synthetic_orphan_01.
        assert len(intents) == 1
        assert len(outcomes) == 0


# ---------------------------------------------------------------------------
# (a) Single-migration apply
# ---------------------------------------------------------------------------


class TestSingleMigrationApply:
    def test_apply_vault_only(self, synthetic_state_dir):
        """Apply just the VAULT category. Ledger + policy stay pending.
        Pillar C Week 2 adds vault/0003; Pillar D Week 4-5 adds
        vault/0004; Pillar E Week 9-11 adds vault/0005; total VAULT
        migrations = 5."""
        runner = _build_runner(synthetic_state_dir)
        results = runner.apply(MigrationCategory.VAULT)
        # vault/0001 + vault/0002 + vault/0003 + vault/0004 + vault/0005
        assert len(results) == 5
        # All Person notes now have schema_version + id + identity_keys.
        for name in (
            "Alice Anderson.md", "Bob Brown.md",
            "Carol Cole.md", "Dana Davis.md", "Evan Estefan.md",
            "Fiona Forrest.md",
        ):
            fm = _person_fm(synthetic_state_dir.vault_dir, name)
            assert fm["schema_version"] == 1
            assert isinstance(fm.get("id"), str) and fm["id"]
            assert isinstance(fm.get("identity_keys"), dict)
        # Other categories still pending.
        # Pillar C Week 3 adds ledger/0004 + Week 5 adds ledger/0005 +
        # Week 6 adds ledger/0006 + Pillar E Week 9-11 adds ledger/0007
        # → ledger pending becomes 7. Week 7 adds policy/0002 + Week 8
        # adds policy/0003 + Week 9 adds policy/0004 + Week 10 adds
        # policy/0005 + Week 11 adds policy/0006 + Pillar D Week 6-8
        # adds policy/0007 → policy pending becomes 7.
        assert len(runner.pending(MigrationCategory.LEDGER)) == 7
        assert len(runner.pending(MigrationCategory.POLICY)) == 7
        # Global pending count = 14 (ledger × 7 + policy × 7).
        assert len(runner.pending()) == 14  # 7 ledger + 7 policy

    def test_apply_ledger_only_after_vault(self, synthetic_state_dir):
        """LEDGER apply after VAULT emits enrolled per Person + closes
        orphan + emits per-channel backfill pairs. Pillar C Week 2 added
        ledger/0003 (LinkedIn invite history); Week 3 added ledger/0004
        (LinkedIn DM history); Week 5 adds ledger/0005 (Twitter DM
        history); Week 6 adds ledger/0006 (Calendar booking history);
        Pillar E Week 9-11 adds ledger/0007 (backfill enrolled.source_skill);
        total LEDGER migrations = 7."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply(MigrationCategory.VAULT)
        results = runner.apply(MigrationCategory.LEDGER)
        # ledger/0001 + 0002 + 0003 + 0004 + 0005 + 0006 + 0007 = 7
        assert len(results) == 7
        # ledger/0001 closed the seeded orphan.
        aborted = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_aborted",
        )
        assert len(aborted) == 1
        assert aborted[0]["intent_id"] == "snd_synthetic_orphan_01"
        # ledger/0002 emitted enrolled per Person with id (6 after the
        # Pillar C Week 5 fixture extension added Evan and Week 6 added
        # Fiona).
        enrolled = _events_by_type(
            synthetic_state_dir.ledger_dir, "enrolled",
        )
        assert len(enrolled) == 6
        # ledger/0003 emitted one new li_invite_intent + li_invite_confirmed
        # for Alice's LinkedIn invite touch (2026-04-18). Carol's pre-
        # existing li_invite pair (li_synthetic_carol_01 from the
        # fixture) was NOT re-emitted because no touch note backs it;
        # the new pair is backfilled-only for Alice.
        li_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        # 3 total: 1 pre-existing (Carol's synthetic li_synthetic_carol_01)
        # + 1 backfilled (Alice's bf_li_*) + 1 Pillar C Week 4 orphan
        # (Carol's li_synthetic_orphan_invite_01 — substrate for
        # reconcile Pass D; no matching outcome by design).
        assert len(li_intents) == 3
        backfill_li_intents = [
            e for e in li_intents
            if str(e.get("intent_id", "")).startswith("bf_li_")
        ]
        assert len(backfill_li_intents) == 1
        assert backfill_li_intents[0].get("channel") == "linkedin"
        # ledger/0004 emitted one new li_dm_intent + li_dm_confirmed
        # for Dana's LinkedIn DM touch (2026-04-20). Plus the Pillar C
        # Week 4 orphan li_dm_intent (lidm_synthetic_orphan_dm_01 —
        # substrate for reconcile Pass E).
        li_dm_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_intent",
        )
        assert len(li_dm_intents) == 2
        backfill_li_dm_intents = [
            e for e in li_dm_intents
            if str(e.get("intent_id", "")).startswith("bf_lidm_")
        ]
        assert len(backfill_li_dm_intents) == 1
        assert backfill_li_dm_intents[0].get("channel") == "linkedin"
        # ledger/0005 emitted one new tw_dm_intent + tw_dm_confirmed
        # for Evan's Twitter DM touch (2026-04-22). Plus the Pillar C
        # Week 5 orphan tw_dm_intent (twdm_synthetic_orphan_dm_01 —
        # substrate for reconcile Pass F).
        tw_dm_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "tw_dm_intent",
        )
        assert len(tw_dm_intents) == 2
        backfill_tw_dm_intents = [
            e for e in tw_dm_intents
            if str(e.get("intent_id", "")).startswith("bf_twdm_")
        ]
        assert len(backfill_tw_dm_intents) == 1
        assert backfill_tw_dm_intents[0].get("channel") == "twitter"


# ---------------------------------------------------------------------------
# (b) Full-batch apply
# ---------------------------------------------------------------------------


class TestFullBatchApply:
    def test_apply_no_args_walks_default_order(self, synthetic_state_dir):
        """``runner.apply()`` applies all migrations in dependency order.

        Pillar B set: 5 migrations. Pillar C Week 2 adds vault/0003 +
        ledger/0003. Pillar C Week 3 adds ledger/0004. Pillar C Week 5
        adds ledger/0005. Pillar C Week 6 adds ledger/0006. Pillar C
        Week 7 adds policy/0002. Pillar C Week 8 adds policy/0003.
        Pillar C Week 9 adds policy/0004. Pillar C Week 10 adds
        policy/0005. Pillar C Week 11 adds policy/0006. Pillar D
        Week 4-5 adds vault/0004. Pillar D Week 6-8 adds policy/0007.
        Pillar E Week 9-11 adds vault/0005 + ledger/0007. Total = 19."""
        runner = _build_runner(synthetic_state_dir)
        results = runner.apply()
        assert len(results) == 19

        # Verify after-state across all surfaces.
        # Vault: every Person note has schema_version + id + identity_keys.
        # Every LinkedIn touch note has linkedin_action stamped.
        for name in (
            "Alice Anderson.md", "Bob Brown.md",
            "Carol Cole.md", "Dana Davis.md", "Evan Estefan.md",
            "Fiona Forrest.md",
        ):
            fm = _person_fm(synthetic_state_dir.vault_dir, name)
            assert fm["schema_version"] == 1
            assert isinstance(fm.get("id"), str)
            assert isinstance(fm.get("identity_keys"), dict)

        # Ledger after full apply:
        #   1 send_aborted (closed orphan from ledger/0001)
        #   6 enrolled (from ledger/0002, one per Person:
        #     Alice/Bob/Carol/Dana/Evan/Fiona)
        #   5 send_intent + 5 send_confirmed pairs (from ledger/0002,
        #     channel-agnostic walker: Alice's email + Alice's LinkedIn
        #     invite + Dana's LinkedIn DM + Evan's Twitter DM +
        #     Fiona's calendar booking)
        #   1 send_confirmed_orphan (Carol's last_touch-without-matching-
        #     touch; her orphan invariant is preserved by every fixture
        #     extension placing new touches on someone other than Carol)
        #   1 li_invite pair (ledger/0003 — Alice's LinkedIn invite).
        #   1 li_dm pair (ledger/0004 — Dana's LinkedIn DM).
        #   1 tw_dm pair (ledger/0005 — Evan's Twitter DM).
        #   1 calendar_booking_intent (ledger/0006 — Fiona's calendar
        #     booking; per ADR-0019 D69 NO paired _confirmed because
        #     the touch carries no calendar_booking_confirmed_at:).
        #   6 migration_events (ledger/0001 + 0002 + 0003 + 0004 +
        #     0005 + 0006).
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir, "send_aborted")) == 1
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir, "enrolled")) == 6
        backfill_intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "send_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 5
        # Channels reflect the cross-channel sequence: 1 email (Alice)
        # + 2 linkedin (Alice invite + Dana DM) + 1 twitter (Evan DM)
        # + 1 calendar (Fiona booking).
        bf_channels = sorted(e["channel"] for e in backfill_intents)
        assert bf_channels == [
            "calendar", "email", "linkedin", "linkedin", "twitter",
        ]
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed")) == 5
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir,
            "send_confirmed_orphan",
        )) == 1
        # ledger/0003 emitted one li_invite pair for Alice's LinkedIn
        # invite.
        bf_li_intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_invite_intent")
            if str(e.get("intent_id", "")).startswith("bf_li_")
        ]
        assert len(bf_li_intents) == 1
        assert bf_li_intents[0].get("channel") == "linkedin"
        # ledger/0004 emitted one li_dm pair for Dana's LinkedIn DM.
        bf_li_dm_intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_dm_intent")
            if str(e.get("intent_id", "")).startswith("bf_lidm_")
        ]
        assert len(bf_li_dm_intents) == 1
        assert bf_li_dm_intents[0].get("channel") == "linkedin"
        # ledger/0005 emitted one tw_dm pair for Evan's Twitter DM.
        bf_tw_dm_intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "tw_dm_intent")
            if str(e.get("intent_id", "")).startswith("bf_twdm_")
        ]
        assert len(bf_tw_dm_intents) == 1
        assert bf_tw_dm_intents[0].get("channel") == "twitter"
        # ledger/0006 emitted one calendar_booking_intent (no paired
        # _confirmed per ADR-0019 D69 — Fiona's touch has no
        # calendar_booking_confirmed_at:).
        bf_calendar_intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "calendar_booking_intent")
            if str(e.get("intent_id", "")).startswith("bf_cb_")
        ]
        assert len(bf_calendar_intents) == 1
        assert bf_calendar_intents[0].get("channel") == "calendar"
        # No paired _confirmed (asymmetric semantics per D69).
        bf_calendar_confirms = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "calendar_booking_confirmed")
            if str(e.get("intent_id", "")).startswith("bf_cb_")
        ]
        assert len(bf_calendar_confirms) == 0
        # 7 migration_events: ledger/0001 + 0002 + 0003 + 0004 + 0005 +
        # 0006 + 0007. Pillar E Week 9-11's ledger/0007 (backfill
        # enrolled.source_skill) emits its migration_event but appends
        # zero enrolled_source_skill_backfill events because the
        # synthetic fixture's enrolled events (emitted by ledger/0002)
        # lack the `source` field — the migration's contract is to skip
        # such events per the "no source attribution to normalize" path.
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event")) == 7

        # Policy: version bumped to 2 + engine_compat block present.
        fm_policy = _policy_fm(synthetic_state_dir.policy_dir)
        assert fm_policy["version"] == 2
        assert "engine_compat" in fm_policy
        assert "min_engine_version" in fm_policy["engine_compat"]

        # No pending remain.
        assert runner.pending() == []

    def test_state_file_records_all_applied(self, synthetic_state_dir):
        """After full apply, the state file lists every migration as applied."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        from orchestrator.migrations.state import load_state
        state = load_state(synthetic_state_dir.state_dir)
        assert state.applied[MigrationCategory.VAULT.value] == [
            "0001_add_schema_version_to_person_notes",
            "0002_backfill_identity_lineage",
            "0003_add_linkedin_action_to_touch_notes",
            "0004_add_conversation_status_to_person_notes",
            "0005_add_discovery_lineage_to_identity_keys",
        ]
        assert state.applied[MigrationCategory.LEDGER.value] == [
            "0001_close_orphan_send_intents",
            "0002_backfill_send_history",
            "0003_baseline_li_invite_history",
            "0004_baseline_li_dm_history",
            "0005_baseline_tw_dm_history",
            "0006_baseline_calendar_booking_history",
            "0007_backfill_enrolled_source_skill",
        ]
        assert state.applied[MigrationCategory.POLICY.value] == [
            "0001_add_engine_compat_field",
            "0002_add_li_invite_weekly_cap",
            "0003_add_li_dm_weekly_cap",
            "0004_add_tw_dm_weekly_cap",
            "0005_add_calendar_booking_daily_cap",
            "0006_add_cross_channel_email_linkedin_cooldown",
            "0007_add_reply_classifier_llm_cap",
        ]

    def test_full_apply_writes_all_per_channel_cap_rules_to_policy_file(
        self, synthetic_state_dir,
    ):
        """End-to-end sequential apply: after ``runner.apply()`` walks
        the full migration set, the synthetic ``cooldowns.yml`` carries
        ALL FOUR per-channel cap rules — ``linkedin-weekly-invite-cap``
        (Week 7's policy/0002), ``linkedin-weekly-dm-cap`` (Week 8's
        policy/0003), ``twitter-weekly-dm-cap`` (Week 9's policy/0004),
        AND ``calendar-booking-daily-cap`` (Week 10's policy/0005) —
        each with its canonical ``source:`` value matching the per-
        channel dispatcher's emit convention (ADR-0015 D40 split-source
        + ADR-0016 D43 + ADR-0018 D58 + ADR-0019 D65).

        Per-week-review P2-C closure (Week 8) extended in Weeks 9 + 10
        to cover the third + fourth per-channel caps. The individual
        migration tests pin the upgrade path on hand-constructed fixture
        YAML; this test pins the production sequence — runner applies
        0001 (schema-changing engine_compat field) → 0002 (content-
        additive invite cap) → 0003 (content-additive LinkedIn DM cap)
        → 0004 (content-additive Twitter DM cap) → 0005 (content-
        additive Calendar booking DAILY cap — first window_hours-form
        rule) to the same operator policy file via the standard
        ``apply()`` walk.

        Week 10 STRUCTURAL DIVERGENCE pin: the four caps cohabit a
        single file with THREE weekly-window rules (linkedin invite +
        linkedin dm + twitter dm) AND ONE daily-window rule (calendar
        booking). The engine accepts both forms equivalently per
        ADR-0006; the cross-window-unit coexistence is the load-bearing
        invariant Week 10 establishes."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        text = (synthetic_state_dir.policy_dir / "cooldowns.yml").read_text(
            encoding="utf-8",
        )
        # All four canonical rule names appear in the file.
        assert "linkedin-weekly-invite-cap" in text
        assert "linkedin-weekly-dm-cap" in text
        assert "twitter-weekly-dm-cap" in text
        assert "calendar-booking-daily-cap" in text
        # Parse + verify the rules' source filters match the per-
        # channel dispatcher emit conventions.
        import yaml as _yaml
        data = _yaml.safe_load(text)
        rules_by_name = {r["name"]: r for r in data["rules"]}
        assert rules_by_name["linkedin-weekly-invite-cap"]["source"] == "linkedin_invite"
        assert rules_by_name["linkedin-weekly-dm-cap"]["source"] == "linkedin_dm"
        assert rules_by_name["twitter-weekly-dm-cap"]["source"] == "twitter_dm"
        assert rules_by_name["calendar-booking-daily-cap"]["source"] == "calendar_booking"
        # Both LinkedIn rules block_when channel: linkedin (account-
        # level pool shared across invites + DMs; per-action
        # discrimination is via source: field per ADR-0015 D40).
        # Twitter cap blocks on channel: twitter (its own account-
        # level rate-limit pool per ADR-0018 D58). Calendar cap blocks
        # on channel: calendar (its own enforcement surface — the
        # operator's calendar, NOT a platform-side rate-limit pool —
        # per ADR-0019 D65 + ADR-0023 D89).
        assert rules_by_name["linkedin-weekly-invite-cap"]["block_when"]["channel"] == "linkedin"
        assert rules_by_name["linkedin-weekly-dm-cap"]["block_when"]["channel"] == "linkedin"
        assert rules_by_name["twitter-weekly-dm-cap"]["block_when"]["channel"] == "twitter"
        assert rules_by_name["calendar-booking-daily-cap"]["block_when"]["channel"] == "calendar"
        # Cross-window-unit coexistence: three weekly caps + one daily
        # cap in the same file. Week 10's structural divergence per
        # ADR-0023 D90.
        assert rules_by_name["linkedin-weekly-invite-cap"]["window_days"] == 7
        assert rules_by_name["linkedin-weekly-dm-cap"]["window_days"] == 7
        assert rules_by_name["twitter-weekly-dm-cap"]["window_days"] == 7
        assert rules_by_name["calendar-booking-daily-cap"]["window_hours"] == 24
        # APPEND semantics (ADR-0020 D73): the per-channel caps go
        # AFTER any pre-existing operator-installed rules. The synthetic
        # fixture's cooldowns.yml has 6 active rules before the
        # migrations; the four caps land at the end in apply order
        # (invite first per policy/0002, then LinkedIn DM per
        # policy/0003, then Twitter DM per policy/0004, then Calendar
        # booking per policy/0005).
        rule_names_in_order = [r["name"] for r in data["rules"]]
        invite_idx = rule_names_in_order.index("linkedin-weekly-invite-cap")
        li_dm_idx = rule_names_in_order.index("linkedin-weekly-dm-cap")
        tw_dm_idx = rule_names_in_order.index("twitter-weekly-dm-cap")
        cal_idx = rule_names_in_order.index("calendar-booking-daily-cap")
        assert invite_idx < li_dm_idx < tw_dm_idx < cal_idx, (
            "Per-channel caps must appear in apply order: Week 7's "
            "invite cap → Week 8's LinkedIn DM cap → Week 9's Twitter "
            "DM cap → Week 10's Calendar booking daily cap (runner "
            "applies in id order; 0002 < 0003 < 0004 < 0005)"
        )
        # All four caps appear after every pre-existing rule (synthetic
        # cooldowns.yml ships with no other rules named *-cap).
        # All standard rule names from the synthetic fixture must
        # precede the four caps.
        for r in data["rules"][:invite_idx]:
            assert r["name"] not in (
                "linkedin-weekly-invite-cap",
                "linkedin-weekly-dm-cap",
                "twitter-weekly-dm-cap",
                "calendar-booking-daily-cap",
            )
        # Pairwise distinct (source, channel) tuples — each per-channel
        # cap gates a distinct event stream (no overlap / no aliasing).
        tuples = {
            (rules_by_name[n]["source"], rules_by_name[n]["block_when"]["channel"])
            for n in (
                "linkedin-weekly-invite-cap",
                "linkedin-weekly-dm-cap",
                "twitter-weekly-dm-cap",
                "calendar-booking-daily-cap",
            )
        }
        assert tuples == {
            ("linkedin_invite", "linkedin"),
            ("linkedin_dm", "linkedin"),
            ("twitter_dm", "twitter"),
            ("calendar_booking", "calendar"),
        }

    def test_full_apply_writes_cross_channel_cooldown_rules_to_policy_file(
        self, synthetic_state_dir,
    ):
        """End-to-end sequential apply: after ``runner.apply()`` walks
        the full migration set, the synthetic ``cooldowns.yml`` carries
        BOTH cross-channel cooldown rules — ``cross-channel-email-
        suppresses-linkedin`` AND ``cross-channel-linkedin-suppresses-
        email`` — per Week 11's policy/0006 + the bundled-bidirectional
        shape per ADR-0024 D-N1.

        Parallel cross-channel sentinel — distinct from the per-channel-
        cap sentinel above per ADR-0024 D-N8 §"Sentinel test name +
        assertion shape grows by one per week" recommendation: rather
        than overloading the per-channel-cap sentinel test with cross-
        channel concerns (the cross-channel rules don't fit the
        ``(source, channel)`` tuple pattern — they don't have a
        ``source:`` field at all), Week 11 adds this parallel sentinel
        with cross-channel-specific tuple assertions
        ``(block_when.channel, consider_channels)`` for the two new
        rules.

        Week 11 STRUCTURAL DIVERGENCE pins: the two cross-channel rules
        use ``cooldown.cross-channel-touch`` rule class (NOT
        ``budget.window-cap`` like Weeks 7-10); ``consider_channels:``
        field (NOT ``source:``); mirror-symmetric direction pair (Rule
        A blocks linkedin considering email; Rule B blocks email
        considering linkedin)."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        text = (synthetic_state_dir.policy_dir / "cooldowns.yml").read_text(
            encoding="utf-8",
        )
        # Both canonical rule names appear in the file.
        assert "cross-channel-email-suppresses-linkedin" in text
        assert "cross-channel-linkedin-suppresses-email" in text
        # Parse + verify the rules' field shapes match the cross-
        # channel pattern (NOT the per-channel-cap pattern).
        import yaml as _yaml
        data = _yaml.safe_load(text)
        rules_by_name = {r["name"]: r for r in data["rules"]}
        rule_a = rules_by_name["cross-channel-email-suppresses-linkedin"]
        rule_b = rules_by_name["cross-channel-linkedin-suppresses-email"]
        # The rules use cooldown.cross-channel-touch type (NOT
        # budget.window-cap like Weeks 7-10).
        assert rule_a["type"] == "cooldown.cross-channel-touch"
        assert rule_b["type"] == "cooldown.cross-channel-touch"
        # No source: field on either rule (the cross-channel pattern
        # per ADR-0024 D-N4).
        assert "source" not in rule_a
        assert "source" not in rule_b
        # No max_units: field either (cross-channel-touch doesn't take
        # a count threshold).
        assert "max_units" not in rule_a
        assert "max_units" not in rule_b
        # consider_channels: present on both, mirror-symmetric.
        assert rule_a["consider_channels"] == ["email"]
        assert rule_b["consider_channels"] == ["linkedin"]
        # block_when.channel: mirror-symmetric.
        assert rule_a["block_when"]["channel"] == "linkedin"
        assert rule_b["block_when"]["channel"] == "email"
        # window_days: 14 on both (matches the factory's Pillar A shape
        # per ADR-0024 D-N5).
        assert rule_a["window_days"] == 14
        assert rule_b["window_days"] == 14
        # Mirror-symmetric (block_when.channel, consider_channels)
        # tuples — the cross-channel equivalent of the per-channel-cap
        # (source, channel) tuple assertion above.
        cross_channel_tuples = {
            (rules_by_name[n]["block_when"]["channel"],
             tuple(rules_by_name[n]["consider_channels"]))
            for n in (
                "cross-channel-email-suppresses-linkedin",
                "cross-channel-linkedin-suppresses-email",
            )
        }
        assert cross_channel_tuples == {
            ("linkedin", ("email",)),
            ("email", ("linkedin",)),
        }
        # APPEND semantics (ADR-0020 D73 inherited): the cross-channel
        # rules go AFTER all four per-channel caps (which themselves go
        # after pre-existing rules). The bundled bidirectional pair is
        # applied last per the per-week ordering (Week 11 ships after
        # Weeks 7-10).
        rule_names_in_order = [r["name"] for r in data["rules"]]
        # Per-channel caps land before cross-channel rules.
        cal_idx = rule_names_in_order.index("calendar-booking-daily-cap")
        rule_a_idx = rule_names_in_order.index("cross-channel-email-suppresses-linkedin")
        rule_b_idx = rule_names_in_order.index("cross-channel-linkedin-suppresses-email")
        assert cal_idx < rule_a_idx < rule_b_idx, (
            "Cross-channel pair (Week 11) must appear AFTER the four "
            "per-channel caps (Weeks 7-10); Rule A (email-suppresses-"
            "linkedin) must appear BEFORE Rule B (linkedin-suppresses-"
            "email) per the canonical insertion order"
        )

    def test_carol_is_the_only_orphan_emitted(self, synthetic_state_dir):
        """Backfill orphan is Carol (last_touch but no matching touch note)."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        orphans = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed_orphan",
        )
        assert len(orphans) == 1
        assert "Carol Cole" in orphans[0]["note_path"]
        # Alice — who DOES have a touch — is not an orphan.
        assert not any("Alice" in o.get("note_path", "") for o in orphans)

    def test_policy_rules_byte_identical_after_apply(
        self, synthetic_state_dir,
    ):
        """Policy migration preserves operator comments + rule order."""
        # Read before.
        before = (synthetic_state_dir.policy_dir / "cooldowns.yml").read_text(
            encoding="utf-8",
        )
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        after = (synthetic_state_dir.policy_dir / "cooldowns.yml").read_text(
            encoding="utf-8",
        )
        # Rules + comments preserved (everything except the version
        # bump + the inserted engine_compat block).
        for marker in (
            "# ---- Rule 1: never cold-pitch the same person twice.",
            "name: no-double-cold-pitch",
            "type: cooldown.no-duplicate-register",
            "# ---- Rule 2: follow-up requires a prior cold-pitch ≥7d ago.",
            "name: followup-needs-prior-pitch",
            "min_age_days: 7",
        ):
            assert marker in before, f"missing in before: {marker!r}"
            assert marker in after, f"lost after migration: {marker!r}"


# ---------------------------------------------------------------------------
# (c) Dry-run preview before apply
# ---------------------------------------------------------------------------


class TestDryRunPreview:
    def test_dry_run_reports_all_pending(self, synthetic_state_dir):
        """Dry-run produces a 19-result preview without mutation
        (Pillar B set: 5 + Pillar C Week 2: 2 + Week 3: 1 + Week 5: 1
        + Week 6: 1 + Week 7: 1 + Week 8: 1 + Week 9: 1 + Week 10: 1 +
        Week 11: 1 + Pillar D Week 4-5: 1 + Pillar D Week 6-8: 1 +
        Pillar E Week 9-11: 2)."""
        runner = _build_runner(synthetic_state_dir)
        preview = runner.dry_run()
        assert len(preview) == 19
        # Every result is marked dry_run + applied=True.
        for r in preview:
            assert r.dry_run is True
            assert r.applied is True
        # State file shows nothing applied yet.
        from orchestrator.migrations.state import load_state
        state = load_state(synthetic_state_dir.state_dir)
        assert all(not v for v in state.applied.values())

    def test_dry_run_does_not_write(self, synthetic_state_dir):
        """Dry-run leaves vault + ledger + policy byte-identical."""
        before_notes = {
            n.name: n.read_text(encoding="utf-8")
            for n in (synthetic_state_dir.vault_dir / "10 People").glob("*.md")
        }
        before_ledger = list(iter_events(synthetic_state_dir.ledger_dir))
        before_policy = (
            synthetic_state_dir.policy_dir / "cooldowns.yml"
        ).read_text(encoding="utf-8")

        runner = _build_runner(synthetic_state_dir)
        runner.dry_run()

        after_notes = {
            n.name: n.read_text(encoding="utf-8")
            for n in (synthetic_state_dir.vault_dir / "10 People").glob("*.md")
        }
        after_ledger = list(iter_events(synthetic_state_dir.ledger_dir))
        after_policy = (
            synthetic_state_dir.policy_dir / "cooldowns.yml"
        ).read_text(encoding="utf-8")

        assert before_notes == after_notes
        assert before_ledger == after_ledger
        assert before_policy == after_policy

    def test_dry_run_then_real_apply_produces_same_counts_modulo_xcat_deps(
        self, synthetic_state_dir,
    ):
        """Real apply after dry-run produces matching counts EXCEPT for
        migrations that read state mutated by an earlier migration in
        the same batch.

        Known dry-run limitation: cross-category-dependent migrations
        cannot be accurately previewed in a single ``dry_run()`` call
        because the earlier migration's mutations don't land. The
        replay vehicle's ``ledger/0002`` reads ``id:`` stamped by
        ``vault/0002`` — at dry-run time those ids don't exist yet, so
        the ledger preview reports zero affected. Per ADR-0013 D24-N
        the limitation is documented + Week 6 (or Pillar I) explores
        a sequenced preview mode.

        This test pins both behaviors:

        * Migrations WITHOUT cross-category dependency
          (vault/0001, vault/0002, ledger/0001, policy/0001) report
          identical counts in dry-run vs apply.
        * ledger/0002 dry-run reports zero (the documented limitation).
        """
        runner = _build_runner(synthetic_state_dir)
        preview = runner.dry_run()
        results = runner.apply()
        assert len(preview) == len(results) == 19
        by_id = {(p.migration_id, r.migration_id): (p, r)
                 for p, r in zip(preview, results)}
        for (p_id, r_id), (p, r) in by_id.items():
            assert p_id == r_id, "dry-run + apply must walk in same order"
            if p_id == "0002_backfill_send_history":
                # The dry-run limitation. Real apply emits 12 (6
                # enrolled + 5 send-pairs + 1 orphan — Pillar C Week 5
                # fixture extension added Evan + his Twitter DM;
                # Week 6 added Fiona + her calendar booking touch);
                # dry-run sees 0 affected because vault/0002 hasn't
                # actually stamped Person notes with id.
                assert p.affected_count == 0
                assert r.affected_count == 12
            elif p_id == "0003_baseline_li_invite_history":
                # Same shape as ledger/0002 — dry-run reports 0 because
                # vault/0002 hasn't stamped Person.id yet; real apply
                # emits 1 LinkedIn invite pair (Alice's touch). Pillar
                # C inherits the documented limitation from ADR-0013
                # D24-N; ADR-0015 §"Dry-run interaction" notes it
                # explicitly.
                assert p.affected_count == 0
                assert r.affected_count == 1
            elif p_id == "0004_baseline_li_dm_history":
                # Same shape — dry-run reports 0 because vault/0002
                # hasn't stamped Person.id yet; real apply emits 1
                # LinkedIn DM pair (Dana's touch). Pillar C Week 3
                # inherits the limitation from ADR-0013 D24-N +
                # ADR-0016 §"Dry-run interaction".
                assert p.affected_count == 0
                assert r.affected_count == 1
            elif p_id == "0005_baseline_tw_dm_history":
                # Same shape — dry-run reports 0 because vault/0002
                # hasn't stamped Person.id yet; real apply emits 1
                # Twitter DM pair (Evan's touch). Pillar C Week 5
                # inherits the limitation from ADR-0013 D24-N +
                # ADR-0018 §"Dry-run interaction".
                assert p.affected_count == 0
                assert r.affected_count == 1
            elif p_id == "0006_baseline_calendar_booking_history":
                # Same shape — dry-run reports 0 because vault/0002
                # hasn't stamped Person.id yet; real apply emits 1
                # Calendar booking intent (Fiona's touch; no paired
                # _confirmed per ADR-0019 D69's asymmetric semantics).
                # Pillar C Week 6 inherits the limitation from
                # ADR-0013 D24-N + ADR-0019 §"Dry-run interaction".
                assert p.affected_count == 0
                assert r.affected_count == 1
            elif p_id == "0005_add_discovery_lineage_to_identity_keys":
                # Same documented dry-run limitation — vault/0005 reads
                # the identity_keys: block stamped by vault/0002, and
                # the id: stamped by vault/0002. In dry-run, vault/0002
                # hasn't mutated yet, so vault/0005 sees Persons without
                # identity_keys/id and skips all 6 (skipped_no_person_id).
                # Real apply: all 6 Persons get manual-floor backfills
                # (the synthetic fixture lacks _source.md + source_channel +
                # ledger source attribution). Pillar E Week 9-11 inherits
                # the limitation from ADR-0013 D24-N.
                assert p.affected_count == 0
                assert r.affected_count == 6
            else:
                # All other migrations: dry-run = real-apply count.
                assert p.affected_count == r.affected_count, (
                    f"{p_id}: dry-run preview {p.affected_count} != "
                    f"real apply {r.affected_count}"
                )


# ---------------------------------------------------------------------------
# (d) Re-apply is no-op (framework-level idempotence)
# ---------------------------------------------------------------------------


class TestReapplyIdempotence:
    def test_second_apply_returns_empty(self, synthetic_state_dir):
        """After full apply, a second ``apply()`` returns zero results
        (state file already shows everything applied; the runner skips
        every migration)."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        results_2 = runner.apply()
        assert results_2 == []

    def test_pending_returns_empty_after_apply(self, synthetic_state_dir):
        """pending() reports zero after a successful full apply."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        assert runner.pending() == []
        assert runner.pending(MigrationCategory.VAULT) == []
        assert runner.pending(MigrationCategory.LEDGER) == []
        assert runner.pending(MigrationCategory.POLICY) == []

    def test_vault_files_unchanged_on_re_apply(self, synthetic_state_dir):
        """Re-applying via direct migration call leaves vault byte-identical."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        snapshot = {
            n.name: n.read_text(encoding="utf-8")
            for n in (synthetic_state_dir.vault_dir / "10 People").glob("*.md")
        }
        # Direct call (the runner's apply() short-circuits applied
        # migrations; we want to exercise the migration's own
        # idempotence guards).
        from orchestrator.migrations.vault.migration_0002 import (
            MIGRATION as VAULT_BACKFILL,
        )
        import logging as _logging
        from datetime import datetime, timezone
        from orchestrator.migrations.types import MigrationContext
        ctx = MigrationContext(
            dry_run=False,
            state_dir=synthetic_state_dir.state_dir,
            ledger_dir=synthetic_state_dir.ledger_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            policy_dir=synthetic_state_dir.policy_dir,
            now=datetime.now(timezone.utc),
            logger=_logging.getLogger("test.replay.idempotence"),
        )
        VAULT_BACKFILL.upgrade(ctx)
        after = {
            n.name: n.read_text(encoding="utf-8")
            for n in (synthetic_state_dir.vault_dir / "10 People").glob("*.md")
        }
        assert snapshot == after

    def test_ledger_event_count_stable_on_re_apply(self, synthetic_state_dir):
        """Direct call to ledger/0002 after first apply produces only a
        new migration_event (audit-trail) — zero new enrolled / send /
        orphan events."""
        runner = _build_runner(synthetic_state_dir)
        runner.apply()
        enrolled_before = len(_events_by_type(
            synthetic_state_dir.ledger_dir, "enrolled"))
        sends_before = len(_events_by_type(
            synthetic_state_dir.ledger_dir, "send_intent"))
        orphans_before = len(_events_by_type(
            synthetic_state_dir.ledger_dir,
            "send_confirmed_orphan",
        ))
        me_before = len(_events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event"))

        # Direct call exercising the per-event idempotence (not
        # short-circuited by the runner).
        from orchestrator.migrations.ledger.migration_0002 import (
            MIGRATION as LEDGER_BACKFILL,
        )
        import logging as _logging
        from datetime import datetime, timezone
        from orchestrator.migrations.types import MigrationContext
        ctx = MigrationContext(
            dry_run=False,
            state_dir=synthetic_state_dir.state_dir,
            ledger_dir=synthetic_state_dir.ledger_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            policy_dir=synthetic_state_dir.policy_dir,
            now=datetime.now(timezone.utc),
            logger=_logging.getLogger("test.replay.idempotence"),
        )
        result = LEDGER_BACKFILL.upgrade(ctx)
        assert result.affected_count == 0

        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir, "enrolled")) == enrolled_before
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir,
            "send_intent")) == sends_before
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir,
            "send_confirmed_orphan",
        )) == orphans_before
        # One new migration_event from this direct call.
        assert len(_events_by_type(
            synthetic_state_dir.ledger_dir,
            "migration_event")) == me_before + 1


# ---------------------------------------------------------------------------
# Cross-cutting — the exit-criterion property
# ---------------------------------------------------------------------------


class TestExitCriterionProperty:
    """The Pillar B exit criterion property (PILLAR-PLAN §2 Pillar B):

    *"the Phase 5.5 backfills replayed cleanly through the migration
    runner against a fresh synthetic vault."*

    Property: after one ``apply()`` against the synthetic before-state,
    the after-state preserves every SoT invariant the production code
    preserves AND no further pending migrations remain.

    Week 5 ships this test as a foundation. Week 6 hardens by adding
    doctor refuse-on-pending integration + multi-category dependency
    coverage when future Pillar D / E migrations land.
    """

    def test_clean_replay_against_fresh_synthetic(self, synthetic_state_dir):
        """The exit-criterion property — one shot, full apply, clean state.

        Pillar B exit criterion still holds. Pillar C Week 2 extends the
        property assertions to cover li_invite_* events with
        channel=linkedin per ADR-0014 D33. Pillar C Week 3 extends to
        cover li_dm_* events with channel=linkedin per the same D33.
        Pillar C Week 5 extends to cover tw_dm_* events with
        channel=twitter per the same D33. Pillar C Week 6 extends to
        cover calendar_booking_* events with channel=calendar per the
        same D33 (asymmetric pair semantics per ADR-0019 D69 — intent
        without matching confirmed is the operator-pending state).
        Pillar C Week 7 adds policy/0002 (per-channel LinkedIn invite
        cap rule). Pillar C Week 8 adds policy/0003 (per-channel
        LinkedIn DM cap rule). Pillar C Week 9 adds policy/0004 (per-
        channel Twitter DM cap rule). Pillar C Week 10 adds policy/0005
        (per-channel Calendar booking DAILY cap rule — first per-channel
        cap with window_hours: 24 + operator-side-runaway-loop framing
        per ADR-0023 D89-D95). Pillar C Week 11 adds policy/0006
        (cross-channel email↔LinkedIn cooldown — TWO rules per
        migration, bidirectional shape, cooldown.cross-channel-touch
        rule class, per ADR-0024 D-N1-N8). Pillar D Week 4-5 adds
        vault/0004 (conversation_status). Pillar D Week 6-8 adds
        policy/0007 (reply-classifier LLM monthly cap per ADR-0029
        D127). Pillar E Week 9-11 adds vault/0005 (discovery_lineage
        per ADR-0036 D168) + ledger/0007 (backfill enrolled.source_skill
        per ADR-0036 D170). Total = 19."""
        runner = _build_runner(synthetic_state_dir)
        results = runner.apply()
        assert len(results) == 19
        assert runner.pending() == []

        # I3 invariant: every Person frontmatter declares schema_version.
        for name in (
            "Alice Anderson.md", "Bob Brown.md",
            "Carol Cole.md", "Dana Davis.md", "Evan Estefan.md",
            "Fiona Forrest.md",
        ):
            fm = _person_fm(synthetic_state_dir.vault_dir, name)
            assert fm["schema_version"] == 1
            # Identity SoT invariant: every Person has id + identity_keys.
            assert isinstance(fm["id"], str) and fm["id"]
            assert isinstance(fm["identity_keys"], dict)

        # I2 invariant: every send_intent has a matching outcome.
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_intent",
        )
        outcome_intent_ids = {
            e.get("intent_id") for e in iter_events(synthetic_state_dir.ledger_dir)
            if e.get("type") in ("send_confirmed", "send_failed", "send_aborted")
        }
        for intent in intents:
            assert intent.get("intent_id") in outcome_intent_ids, (
                f"orphan intent {intent.get('intent_id')!r} should have "
                f"been closed by ledger/0001 or paired by ledger/0002"
            )

        # I3 invariant: every policy file declares version + engine_compat.
        fm_policy = _policy_fm(synthetic_state_dir.policy_dir)
        assert fm_policy["version"] == 2
        assert "engine_compat" in fm_policy

        # Pillar C Week 2 invariants: every li_invite_intent has a
        # matching li_invite_confirmed; every li_invite_* event carries
        # channel="linkedin" per ADR-0014 D33. Exception: the Pillar C
        # Week 4 fixture orphan (li_synthetic_orphan_invite_01) has no
        # matching outcome by design — substrate for reconcile Pass D
        # recovery; the orphan invariant is healed by Pass D, not by
        # ledger/0003. The two-phase pairing assertion below explicitly
        # exempts this intent_id (the migration runner doesn't touch it).
        li_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_intent",
        )
        li_confirmed_intent_ids = {
            e.get("intent_id")
            for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_invite_confirmed",
            )
        }
        for intent in li_intents:
            iid = intent.get("intent_id")
            if iid == "li_synthetic_orphan_invite_01":
                # Pillar C Week 4 fixture orphan — recovered by Pass D,
                # not by ledger/0003. Skip the matching-confirmed check.
                continue
            assert iid in li_confirmed_intent_ids, (
                f"li_invite_intent {iid!r} has no matching "
                f"li_invite_confirmed — Pillar C Week 2 two-phase "
                f"invariant violated."
            )
            assert intent.get("channel") == "linkedin", (
                f"li_invite_intent {iid!r} missing channel='linkedin' "
                f"(ADR-0014 D33 invariant)."
            )
        for confirmed in _events_by_type(
            synthetic_state_dir.ledger_dir, "li_invite_confirmed",
        ):
            assert confirmed.get("channel") == "linkedin", (
                f"li_invite_confirmed {confirmed.get('intent_id')!r} "
                f"missing channel='linkedin' (ADR-0014 D33 invariant)."
            )

        # ledger/0003 emitted at least one new backfill pair.
        bf_li_intents = [
            e for e in li_intents
            if str(e.get("intent_id", "")).startswith("bf_li_")
        ]
        assert len(bf_li_intents) >= 1, (
            "Pillar C Week 2 ledger/0003 should have emitted at least "
            "one backfilled li_invite pair against the fixture's "
            "Alice LinkedIn touch (2026-04-18)."
        )

        # Pillar C Week 3 invariants: every li_dm_intent has a
        # matching li_dm_confirmed; every li_dm_* event carries
        # channel="linkedin" per ADR-0014 D33.
        li_dm_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_intent",
        )
        li_dm_confirmed_intent_ids = {
            e.get("intent_id")
            for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "li_dm_confirmed",
            )
        }
        for intent in li_dm_intents:
            iid = intent.get("intent_id")
            if iid == "lidm_synthetic_orphan_dm_01":
                # Pillar C Week 4 fixture orphan — recovered by Pass E,
                # not by ledger/0004. Skip the matching-confirmed check.
                continue
            assert iid in li_dm_confirmed_intent_ids, (
                f"li_dm_intent {iid!r} has no matching "
                f"li_dm_confirmed — Pillar C Week 3 two-phase "
                f"invariant violated."
            )
            assert intent.get("channel") == "linkedin", (
                f"li_dm_intent {iid!r} missing channel='linkedin' "
                f"(ADR-0014 D33 invariant)."
            )
        for confirmed in _events_by_type(
            synthetic_state_dir.ledger_dir, "li_dm_confirmed",
        ):
            assert confirmed.get("channel") == "linkedin", (
                f"li_dm_confirmed {confirmed.get('intent_id')!r} "
                f"missing channel='linkedin' (ADR-0014 D33 invariant)."
            )

        # ledger/0004 emitted at least one new backfill pair.
        bf_li_dm_intents = [
            e for e in li_dm_intents
            if str(e.get("intent_id", "")).startswith("bf_lidm_")
        ]
        assert len(bf_li_dm_intents) >= 1, (
            "Pillar C Week 3 ledger/0004 should have emitted at least "
            "one backfilled li_dm pair against the fixture's Dana "
            "LinkedIn DM touch (2026-04-20)."
        )

    def test_apply_is_atomic_against_per_migration_failures(
        self, synthetic_state_dir, monkeypatch,
    ):
        """If one migration mid-batch raises, earlier ones are persisted
        but the failing one + later ones are NOT marked applied.

        This is the framework-level atomicity contract ADR-0009 D4
        pins. Verified here against the replay vehicle because the
        contract's blast radius is most visible across multiple
        categories.
        """
        from orchestrator.migrations.ledger import migration_0002 as mod

        # Simulate ledger/0002's upgrade raising.
        def raising_upgrade(self, ctx):
            raise RuntimeError("simulated ledger/0002 crash")

        monkeypatch.setattr(
            mod.BackfillSendHistory, "upgrade", raising_upgrade,
        )

        runner = _build_runner(synthetic_state_dir)
        with pytest.raises(RuntimeError, match="ledger/0002 crash"):
            runner.apply()

        # Per the apply order (VAULT → LEDGER → POLICY), vault/0001 +
        # vault/0002 + vault/0003 + vault/0004 + vault/0005 + ledger/0001
        # ran successfully. ledger/0002 crashed. ledger/0003+ + policy/0001
        # were not reached.
        from orchestrator.migrations.state import load_state
        state = load_state(synthetic_state_dir.state_dir)
        assert state.applied[MigrationCategory.VAULT.value] == [
            "0001_add_schema_version_to_person_notes",
            "0002_backfill_identity_lineage",
            "0003_add_linkedin_action_to_touch_notes",
            "0004_add_conversation_status_to_person_notes",
            "0005_add_discovery_lineage_to_identity_keys",
        ]
        assert state.applied[MigrationCategory.LEDGER.value] == [
            "0001_close_orphan_send_intents",
        ]
        assert state.applied[MigrationCategory.POLICY.value] == []

    def test_degenerate_order_when_ledger_runs_before_vault(
        self, synthetic_state_dir,
    ):
        """Per ADR-0013 D27 the default apply order is VAULT → LEDGER →
        POLICY because ``ledger/0002_backfill_send_history`` reads
        ``id:`` stamped by ``vault/0002_backfill_identity_lineage``.

        If a contributor reverts ``_DEFAULT_APPLY_ORDER`` to (LEDGER,
        VAULT, POLICY), the happy-path replay test would silently
        continue to pass — but the after-state would be degenerate:
        ledger/0002 would walk Person notes that lack ``id:`` (not yet
        stamped), skip every one of them, and report
        ``persons_without_id: 3`` in its migration_event.
        ``enrolled`` would never fire; the send-pair from Alice's
        touch would never emit; the orphan from Carol's last_touch
        would never emit.

        This test pins the failure mode the reorder protects against
        by EXPLICITLY calling ``runner.apply(MigrationCategory.LEDGER)``
        BEFORE ``runner.apply(MigrationCategory.VAULT)`` — bypassing
        the default order — and asserting the degenerate after-state.

        A future revert of ``_DEFAULT_APPLY_ORDER`` would not change
        this test's pass/fail (because we explicitly invoke the per-
        category path); the test's purpose is to make the SHAPE of
        the degeneration loud + named, so the failure mode is in the
        test corpus rather than lurking as an undocumented
        consequence. Closes Week 5 review §Testing coverage gap #5.
        """
        runner = _build_runner(synthetic_state_dir)
        # Apply LEDGER first — the degenerate order. ledger/0001 runs
        # cleanly (close orphan doesn't need vault state); ledger/0002
        # walks Person notes that lack id and silently records them in
        # persons_without_id; ledger/0003 + ledger/0004 + ledger/0005
        # walk per-channel touches but can't resolve person_id without
        # vault/0002 having stamped id. ledger/0007 walks enrolled
        # events lacking source_skill — but ledger/0002 didn't emit any
        # enrolled events in the degenerate order, so ledger/0007 is a
        # no-op (zero backfills + 1 migration_event audit trail).
        ledger_results = runner.apply(MigrationCategory.LEDGER)
        # Pillar C Week 2 added ledger/0003; Week 3 added ledger/0004;
        # Week 5 added ledger/0005; Week 6 added ledger/0006; Pillar E
        # Week 9-11 added ledger/0007. ledger/0001 + 0002 + 0003 + 0004
        # + 0005 + 0006 + 0007 = 7
        assert len(ledger_results) == 7

        # The degenerate-state assertions:
        # 1. Zero enrolled events emitted — no Person had an id for
        #    ledger/0002 to enroll on.
        enrolled = _events_by_type(
            synthetic_state_dir.ledger_dir, "enrolled",
        )
        assert len(enrolled) == 0, (
            f"Expected zero enrolled events in the degenerate order "
            f"(LEDGER before VAULT). Got {len(enrolled)}. If this "
            f"fails, the degenerate-shape protection D27 names has "
            f"changed — check that ledger/0002 still walks vault for "
            f"id stamping and that the failure-mode rationale in "
            f"_DEFAULT_APPLY_ORDER's comment block still holds."
        )

        # 2. Zero backfilled send_intents — Alice's touch doesn't
        #    enroll because Alice has no id; the send-pair never emits.
        backfill_intents = [
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "send_intent")
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 0

        # 3. Zero send_confirmed_orphan emissions — Carol's last_touch
        #    can't be flagged orphan because she has no id either.
        orphans = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed_orphan",
        )
        assert len(orphans) == 0

        # 4. ledger/0002's migration_event records 5 persons_without_id
        #    — the diagnostic surface operators inspect to figure out
        #    "why did the backfill produce zero enrolled events?"
        migration_events = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        # ledger/0001 + 0002 + 0003 + 0004 + 0005 + 0006 + 0007 each
        # emit one migration_event (Pillar C Week 2 added the third;
        # Week 3 added the fourth; Week 5 added the fifth; Week 6 added
        # the sixth; Pillar E Week 9-11 added the seventh — ledger/0007
        # backfill enrolled.source_skill per ADR-0036 D170).
        assert len(migration_events) == 7
        ledger_0002_event = next(
            e for e in migration_events
            if e.get("migration_id") == "0002_backfill_send_history"
        )
        assert ledger_0002_event.get("persons_without_id") == 6, (
            f"ledger/0002 should record persons_without_id=6 in the "
            f"degenerate order; got "
            f"{ledger_0002_event.get('persons_without_id')!r}. The "
            f"diagnostic surface is the operator-facing 'why did this "
            f"backfill emit nothing' explainer."
        )
        assert ledger_0002_event.get("enrolled_emitted") == 0
        assert ledger_0002_event.get("sends_emitted") == 0
        assert ledger_0002_event.get("orphans_emitted") == 0

        # 5. After this degenerate apply, running VAULT does stamp
        #    ids — but ledger/0002 is already marked applied (it
        #    "succeeded" with zero affected). A naïve operator who
        #    later applies VAULT then re-runs apply() sees zero
        #    further backfill emissions because ledger/0002 won't
        #    re-fire. This is exactly the "silent degenerate after-
        #    state" failure mode D27's reorder prevents.
        runner.apply(MigrationCategory.VAULT)
        # Re-running full apply is a no-op for ledger because it's
        # already marked applied — pinning that the framework's
        # applies-once contract STRENGTHENS the degeneration rather
        # than recovering from it. Recovery requires either
        # `mark_unapplied` (operator intervention) or a hypothetical
        # future "force re-run" path neither of which exists at
        # Week 6.
        runner.apply()
        enrolled_after_vault = _events_by_type(
            synthetic_state_dir.ledger_dir, "enrolled",
        )
        assert len(enrolled_after_vault) == 0, (
            "Once ledger/0002 is marked applied in the degenerate "
            "order, a subsequent VAULT apply does not re-fire it — "
            "this is the framework's applies-once contract working "
            "as designed. The reorder in D27 prevents operators from "
            "reaching this state in the first place via no-arg "
            "apply()."
        )
