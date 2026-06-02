"""Tests for ``ledger/0006_baseline_calendar_booking_history``.

Direct unit tests against the synthetic fixture. Mirrors
``tests/test_migrations_ledger_0005.py`` shape — the per-migration test
classes (TestMigrationSurface, TestUpgradeHappyPath,
TestUpgradeWithoutVaultBackfill, TestDryRun, TestIdempotence,
TestRefuseLoud, TestDowngrade, TestIntentIdDeterminism,
TestChannelFiltering, TestAsymmetricSemantics) match Pillar B's
per-migration test convention.

Pillar C Week 6 (ADR-0019) extended the synthetic fixture with:

* Fiona Forrest Person note (``vault/10 People/Fiona Forrest.md``,
  ``email: fiona@forrestlabs.io``, ``linkedin: in/fionaforrest``,
  ``calendar_booking_url_base: https://cal.com/acme/intro-30``) — a
  calendar-engaged founder.
* Fiona's Calendar booking touch (``vault/40 Conversations/2026-04-25
  Fiona calendar booking.md``, ``sent: true``, ``channel: calendar``)
  — the substrate ledger/0006 backfills. NO
  ``calendar_booking_confirmed_at:`` field, so per ADR-0019 D69's
  asymmetric semantics the backfill emits ONLY
  ``calendar_booking_intent`` (no paired ``_confirmed``).

This migration depends on vault/0002 having stamped ``id:`` on Person
notes — without that, the ``person_id`` lookup fails for every touch.

See ADR-0019 for the full Week 6 design.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.migrations.ledger._ledger_io import iter_events
from orchestrator.migrations.ledger.migration_0006_baseline_calendar_booking_history import (
    CALENDAR_CHANNEL,
    MIGRATION,
    MIGRATION_ID,
    RECOVERED_BY_TAG,
    SYNTHETIC_INTENT_PREFIX,
    BaselineCalendarBookingHistory,
    _synth_intent_id,
    _walk_calendar_touch_records,
)
from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext,
)
from orchestrator.migrations.vault._vault_io import iter_touch_notes
from orchestrator.migrations.vault.migration_0002 import (
    MIGRATION as VAULT_BACKFILL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    state_dir: Path,
    vault_dir: Path | None,
    ledger_dir: Path | None = None,
    dry_run: bool = False,
) -> MigrationContext:
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir if ledger_dir is not None else state_dir / "ledger",
        vault_dir=vault_dir,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.ledger.0006"),
    )


def _apply_vault_backfill_first(state) -> None:
    """Run vault/0002 first so Person notes have ``id:`` set."""
    ctx = _make_ctx(state_dir=state.state_dir, vault_dir=state.vault_dir)
    VAULT_BACKFILL.upgrade(ctx)


def _events_by_type(ledger_dir: Path, type_name: str) -> list[dict]:
    return [e for e in iter_events(ledger_dir) if e.get("type") == type_name]


# ---------------------------------------------------------------------------
# Migration surface — Protocol compliance
# ---------------------------------------------------------------------------


class TestMigrationSurface:
    def test_singleton_implements_protocol(self):
        assert MIGRATION.id == MIGRATION_ID
        assert MIGRATION.id == "0006_baseline_calendar_booking_history"
        assert MIGRATION.category == MigrationCategory.LEDGER
        assert MIGRATION.is_reversible is False

    def test_description_is_one_line(self):
        assert "\n" not in MIGRATION.description
        # The description names the channel + action so operators
        # scanning the migration manifest can recognize what runs.
        assert "calendar" in MIGRATION.description.lower()

    def test_is_distinct_singleton_from_ledger_0005(self):
        from orchestrator.migrations.ledger.migration_0005_baseline_tw_dm_history import (
            MIGRATION as LEDGER_0005,
        )
        assert MIGRATION is not LEDGER_0005
        assert MIGRATION.id != LEDGER_0005.id

    def test_registered_in_migrations_list(self):
        from orchestrator.migrations.ledger import MIGRATIONS
        assert MIGRATION in MIGRATIONS

    def test_registered_after_ledger_0005(self):
        """The apply order places ledger/0006 after ledger/0005."""
        from orchestrator.migrations.ledger import MIGRATIONS
        from orchestrator.migrations.ledger.migration_0005_baseline_tw_dm_history import (
            MIGRATION as LEDGER_0005,
        )
        idx_0005 = MIGRATIONS.index(LEDGER_0005)
        idx_0006 = MIGRATIONS.index(MIGRATION)
        assert idx_0006 == idx_0005 + 1


# ---------------------------------------------------------------------------
# upgrade() — happy path
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:
    def test_emits_calendar_intent_per_touch(self, synthetic_state_dir):
        """Each ``sent: true`` Calendar touch produces a
        ``calendar_booking_intent`` event.

        Fixture has one Calendar touch (Fiona's 2026-04-25). Per
        ADR-0019 D69's asymmetric semantics: no ``_confirmed`` because
        the touch has no ``calendar_booking_confirmed_at:`` field."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 1
        ev = backfill_intents[0]
        assert ev.get("channel") == "calendar"
        assert ev.get("_recovered_by") == "backfill"
        assert ev.get("person_id") == "fionaforrest-li"

    def test_no_confirmed_when_touch_lacks_confirmed_at_field(
        self, synthetic_state_dir,
    ):
        """ADR-0019 D69's asymmetric semantics: touches without
        ``calendar_booking_confirmed_at:`` produce intent-only — the
        ``calendar_booking_confirmed`` is NOT backfilled because the
        recipient may not have actually booked."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_confirmed",
        )
        backfill_confirms = [
            e for e in confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        # Zero — Fiona's touch has no ``calendar_booking_confirmed_at:``
        # field so the backfill emits intent only.
        assert len(backfill_confirms) == 0

    def test_emits_confirmed_when_touch_has_confirmed_at_field(
        self, synthetic_state_dir, monkeypatch,
    ):
        """ADR-0019 D69: a touch carrying ``calendar_booking_confirmed_at:``
        produces a paired ``calendar_booking_confirmed`` in the
        backfill."""
        # Mutate Fiona's touch in-place to add the confirmed_at field.
        fiona_touch = (
            synthetic_state_dir.vault_dir / "40 Conversations" /
            "2026-04-25 Fiona calendar booking.md"
        )
        original = fiona_touch.read_text()
        # Insert confirmed_at into frontmatter (before closing ---).
        patched = original.replace(
            "calendar_booking_intent_id: bf_cb_synthetic_pre_run",
            (
                "calendar_booking_intent_id: bf_cb_synthetic_pre_run\n"
                "calendar_booking_confirmed_at: 2026-04-26"
            ),
        )
        fiona_touch.write_text(patched)

        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_confirmed",
        )
        backfill_confirms = [
            e for e in confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_confirms) == 1
        assert backfill_confirms[0].get("channel") == "calendar"
        assert backfill_confirms[0].get("_recovered_by") == "backfill"

    def test_emits_migration_event_with_channel_calendar(
        self, synthetic_state_dir,
    ):
        """Per ADR-0014 D35: the migration_event audit-trail event
        carries channel=calendar so Pillar G observability filters by
        scalar field, not text-match against migration_id."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        events = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        # Find the migration_event for this migration_id.
        my_event = next(
            (e for e in events if e.get("migration_id") == MIGRATION_ID),
            None,
        )
        assert my_event is not None
        assert my_event.get("channel") == "calendar"

    def test_migration_event_carries_per_diagnostic_counts(
        self, synthetic_state_dir,
    ):
        """The migration_event surfaces calendar_intents_emitted +
        calendar_confirmeds_emitted + calendar_pairs_skipped +
        touches_without_person_match for Pillar G dashboards."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        events = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        my_event = next(
            (e for e in events if e.get("migration_id") == MIGRATION_ID),
            None,
        )
        assert my_event is not None
        assert "calendar_intents_emitted" in my_event
        assert "calendar_confirmeds_emitted" in my_event
        assert "calendar_pairs_skipped" in my_event
        assert "touches_without_person_match" in my_event


# ---------------------------------------------------------------------------
# upgrade() — without vault/0002 having run first
# ---------------------------------------------------------------------------


class TestUpgradeWithoutVaultBackfill:
    def test_touches_without_person_match_when_vault_not_backfilled(
        self, synthetic_state_dir,
    ):
        """Without vault/0002 the Person notes lack ``id:`` so the
        person-name → id lookup fails for every touch — the migration
        records them in touches_without_person_match."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # NOTE: skipping _apply_vault_backfill_first
        result = MIGRATION.upgrade(ctx)
        # The synthetic fixture's Calendar touch (Fiona) lands in
        # touches_without_person_match because Fiona's note has no id:.
        # Affected count is therefore 0.
        assert result.affected_count == 0


# ---------------------------------------------------------------------------
# upgrade() — dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_writes_no_events(self, synthetic_state_dir):
        """Per ADR-0010 D17: dry-run mutates nothing."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        # Snapshot the calendar event count before running.
        before = len(_events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        ))
        result = MIGRATION.upgrade(ctx)
        # After dry-run no new events landed.
        after = len(_events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        ))
        assert before == after
        # The result reports the would-emit count.
        assert result.affected_count == 1
        assert result.dry_run is True

    def test_dry_run_emits_no_migration_event(self, synthetic_state_dir):
        """Per ADR-0010 D17: dry-run doesn't emit migration_event
        either (a dry run mutates nothing — including the audit trail)."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
            dry_run=True,
        )
        before_count = len([
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "migration_event",
            ) if e.get("migration_id") == MIGRATION_ID
        ])
        MIGRATION.upgrade(ctx)
        after_count = len([
            e for e in _events_by_type(
                synthetic_state_dir.ledger_dir, "migration_event",
            ) if e.get("migration_id") == MIGRATION_ID
        ])
        assert before_count == after_count


# ---------------------------------------------------------------------------
# upgrade() — idempotence
# ---------------------------------------------------------------------------


class TestAsymmetricPartialRerun:
    """Per Week 6 per-week review migration P2-1: pin the asymmetric
    partial-rerun path as a tested contract.

    The operator workflow described in ADR-0019 D69 + the §"Existing-
    operator seed" per-operator-profile table row "stamp before running
    apply" is: (1) run upgrade once on a fresh ledger with a touch that
    has NO ``calendar_booking_confirmed_at:`` — the migration emits
    intent only; (2) operator later learns the recipient actually
    booked, stamps ``calendar_booking_confirmed_at: <ISO>`` on the
    touch; (3) re-run upgrade — the migration emits ONLY the confirmed
    (intent is already present + dedup'd).

    Without this test the partial-rerun path is implementation-defined;
    a future refactor that broke the asymmetric semantics would slip
    silently through the symmetric-rerun tests.
    """

    def test_partial_rerun_emits_confirmed_after_stamping_field(
        self, synthetic_state_dir,
    ):
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # First apply — Fiona's touch has no confirmed_at, so only the
        # intent emits.
        result_1 = MIGRATION.upgrade(ctx)
        intents_1 = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        )
        confirms_1 = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_confirmed",
        )
        bf_intents_1 = [
            e for e in intents_1
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        bf_confirms_1 = [
            e for e in confirms_1
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(bf_intents_1) == 1
        assert len(bf_confirms_1) == 0

        # Operator stamps calendar_booking_confirmed_at on the touch
        # AFTER the first apply.
        fiona_touch = (
            synthetic_state_dir.vault_dir / "40 Conversations" /
            "2026-04-25 Fiona calendar booking.md"
        )
        original = fiona_touch.read_text()
        patched = original.replace(
            "calendar_booking_intent_id: bf_cb_synthetic_pre_run",
            (
                "calendar_booking_intent_id: bf_cb_synthetic_pre_run\n"
                "calendar_booking_confirmed_at: 2026-04-27"
            ),
        )
        fiona_touch.write_text(patched)

        # Second apply — intent already in ledger; the migration emits
        # ONLY the newly-stampable confirmed.
        result_2 = MIGRATION.upgrade(ctx)
        intents_2 = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        )
        confirms_2 = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_confirmed",
        )
        bf_intents_2 = [
            e for e in intents_2
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        bf_confirms_2 = [
            e for e in confirms_2
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        # No new intent (already present).
        assert len(bf_intents_2) == 1
        # The confirmed landed.
        assert len(bf_confirms_2) == 1
        assert bf_confirms_2[0].get("channel") == "calendar"
        # The result's affected_count = 1 (just the new confirmed) +
        # the new diagnostic field `calendar_confirmeds_added_on_rerun`
        # tracks this path explicitly (per Week 6 per-week-review
        # migration P2-2).
        assert result_2.affected_count == 1
        assert "1 confirmed added on rerun" in result_2.notes

    def test_partial_rerun_migration_event_records_new_diagnostic(
        self, synthetic_state_dir,
    ):
        """Per Week 6 per-week-review migration P2-2: the migration_event
        emitted for the partial-rerun apply records the
        ``calendar_confirmeds_added_on_rerun`` diagnostic count so
        Pillar G observability can chart the partial-rerun rate
        separately from "nothing happened" (calendar_pairs_skipped).
        """
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        # Stamp confirmed_at and re-run.
        fiona_touch = (
            synthetic_state_dir.vault_dir / "40 Conversations" /
            "2026-04-25 Fiona calendar booking.md"
        )
        original = fiona_touch.read_text()
        patched = original.replace(
            "calendar_booking_intent_id: bf_cb_synthetic_pre_run",
            (
                "calendar_booking_intent_id: bf_cb_synthetic_pre_run\n"
                "calendar_booking_confirmed_at: 2026-04-27"
            ),
        )
        fiona_touch.write_text(patched)
        MIGRATION.upgrade(ctx)
        events = _events_by_type(
            synthetic_state_dir.ledger_dir, "migration_event",
        )
        my_events = [
            e for e in events
            if e.get("migration_id") == MIGRATION_ID
        ]
        # Two migration_events (one per apply).
        assert len(my_events) == 2
        # The second migration_event records the partial-rerun.
        second = my_events[-1]
        assert "calendar_confirmeds_added_on_rerun" in second
        assert second["calendar_confirmeds_added_on_rerun"] == 1


class TestIdempotence:
    def test_re_apply_no_op(self, synthetic_state_dir):
        """Per ADR-0009 D4 + ADR-0013 + the per-event idempotence check:
        re-running upgrade emits NO new events (the intent_id set
        already contains every synthetic intent)."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # First apply.
        MIGRATION.upgrade(ctx)
        intents_after_first = len(_events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        ))
        # Second apply.
        result_2 = MIGRATION.upgrade(ctx)
        intents_after_second = len(_events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        ))
        # Same count.
        assert intents_after_first == intents_after_second
        # Result reports zero net emissions.
        assert result_2.affected_count == 0


# ---------------------------------------------------------------------------
# upgrade() — refuse-loud (missing vault / missing ledger)
# ---------------------------------------------------------------------------


class TestRefuseLoud:
    def test_refuses_without_vault_dir(self, tmp_path):
        """The migration needs to read touch notes; vault_dir=None
        refuses-loud."""
        ctx = MigrationContext(
            dry_run=False,
            state_dir=tmp_path / "state",
            ledger_dir=tmp_path / "ledger",
            vault_dir=None,
            policy_dir=tmp_path / "policies",
            now=datetime.now(timezone.utc),
            logger=logging.getLogger("test"),
        )
        (tmp_path / "ledger").mkdir()
        with pytest.raises(ValueError, match="vault_dir"):
            MIGRATION.upgrade(ctx)

    def test_refuses_without_ledger_dir(self, tmp_path):
        """The migration needs to append events; missing ledger_dir
        refuses-loud."""
        (tmp_path / "vault").mkdir()
        ctx = MigrationContext(
            dry_run=False,
            state_dir=tmp_path / "state",
            ledger_dir=tmp_path / "nonexistent_ledger",
            vault_dir=tmp_path / "vault",
            policy_dir=tmp_path / "policies",
            now=datetime.now(timezone.utc),
            logger=logging.getLogger("test"),
        )
        with pytest.raises(FileNotFoundError, match="ledger_dir"):
            MIGRATION.upgrade(ctx)


# ---------------------------------------------------------------------------
# downgrade() — irreversible per ADR-0010 D14
# ---------------------------------------------------------------------------


class TestDowngrade:
    def test_downgrade_raises(self, synthetic_state_dir):
        """Per ADR-0010 D14: ledger migrations are append-only;
        downgrade raises NotImplementedError."""
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        with pytest.raises(NotImplementedError):
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# intent_id determinism
# ---------------------------------------------------------------------------


class TestIntentIdDeterminism:
    def test_intent_id_deterministic_across_runs(self):
        """The same (person_id, date, touch_stem) input produces the
        same hash on every call."""
        iid_1 = _synth_intent_id(
            "alice-li", "2026-04-10T00:00:00.000Z",
            touch_stem="2026-04-10 Alice initial",
        )
        iid_2 = _synth_intent_id(
            "alice-li", "2026-04-10T00:00:00.000Z",
            touch_stem="2026-04-10 Alice initial",
        )
        assert iid_1 == iid_2

    def test_intent_id_distinguishes_different_persons(self):
        iid_a = _synth_intent_id(
            "alice-li", "2026-04-10T00:00:00.000Z",
            touch_stem="touch",
        )
        iid_b = _synth_intent_id(
            "bob-li", "2026-04-10T00:00:00.000Z",
            touch_stem="touch",
        )
        assert iid_a != iid_b

    def test_intent_id_distinguishes_different_dates(self):
        iid_1 = _synth_intent_id(
            "alice-li", "2026-04-10T00:00:00.000Z",
            touch_stem="touch",
        )
        iid_2 = _synth_intent_id(
            "alice-li", "2026-04-11T00:00:00.000Z",
            touch_stem="touch",
        )
        assert iid_1 != iid_2

    def test_intent_id_distinguishes_different_touch_stems(self):
        """Same-day initial + follow-up touches don't hash-collide."""
        iid_1 = _synth_intent_id(
            "alice-li", "2026-04-10T00:00:00.000Z",
            touch_stem="initial",
        )
        iid_2 = _synth_intent_id(
            "alice-li", "2026-04-10T00:00:00.000Z",
            touch_stem="followup",
        )
        assert iid_1 != iid_2

    def test_intent_id_prefix(self):
        iid = _synth_intent_id(
            "alice-li", "2026-04-10T00:00:00.000Z",
            touch_stem="touch",
        )
        assert iid.startswith(SYNTHETIC_INTENT_PREFIX)
        assert iid.startswith("bf_cb_")


# ---------------------------------------------------------------------------
# Channel filtering — the walker only picks ``channel: calendar`` touches
# ---------------------------------------------------------------------------


class TestChannelFiltering:
    def test_skips_non_calendar_touches(self, synthetic_state_dir):
        """The fixture has email + linkedin + twitter + calendar
        touches; the walker only picks up channel:calendar."""
        _apply_vault_backfill_first(synthetic_state_dir)
        # _walk_calendar_touch_records returns only Fiona's touch
        # (channel: calendar) and ignores the others.
        records = _walk_calendar_touch_records(
            iter_touch_notes(synthetic_state_dir.vault_dir),
        )
        assert len(records) == 1
        # The matched record is Fiona's.
        assert "Fiona" in str(records[0].path)

    def test_other_channel_walkers_do_not_pick_calendar_touch(
        self, synthetic_state_dir,
    ):
        """The LinkedIn / Twitter walkers should NOT pick up Fiona's
        calendar touch — channel-specific walkers are tight."""
        from orchestrator.migrations.ledger.migration_0003_baseline_li_invite_history import (
            _walk_linkedin_touch_records,
        )
        from orchestrator.migrations.ledger.migration_0005_baseline_tw_dm_history import (
            _walk_twitter_touch_records,
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        li_records = _walk_linkedin_touch_records(
            iter_touch_notes(synthetic_state_dir.vault_dir),
        )
        tw_records = _walk_twitter_touch_records(
            iter_touch_notes(synthetic_state_dir.vault_dir),
        )
        # Neither contains Fiona's calendar touch.
        for r in li_records + tw_records:
            assert "Fiona" not in str(r.path)


# ---------------------------------------------------------------------------
# Asymmetric pair semantics (the Week 6 structural distinction per D69)
# ---------------------------------------------------------------------------


class TestAsymmetricSemantics:
    def test_intent_emitted_without_confirmed_when_field_absent(
        self, synthetic_state_dir,
    ):
        """The fixture's Fiona touch has no
        ``calendar_booking_confirmed_at:`` — backfill emits ONLY the
        intent."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        )
        confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_confirmed",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        backfill_confirms = [
            e for e in confirms
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 1
        assert len(backfill_confirms) == 0

    def test_walker_records_confirmed_at_when_present(self, tmp_path):
        """Direct walker test: a touch with confirmed_at: stamps it on
        the record."""
        from orchestrator.migrations.vault._vault_io import iter_touch_notes
        conv = tmp_path / "40 Conversations"
        conv.mkdir()
        touch_path = conv / "2026-05-01 test calendar.md"
        touch_path.write_text(
            "---\n"
            "type: touch\n"
            "person: '[[Test Person]]'\n"
            "channel: calendar\n"
            "sent: true\n"
            "date: 2026-05-01\n"
            "calendar_booking_confirmed_at: 2026-05-02\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        records = _walk_calendar_touch_records(iter_touch_notes(tmp_path))
        assert len(records) == 1
        assert records[0].confirmed_at_ts is not None
        assert "2026-05-02" in records[0].confirmed_at_ts

    def test_walker_skips_unsent_calendar_touches(self, tmp_path):
        """``sent: false`` touches are not backfilled."""
        from orchestrator.migrations.vault._vault_io import iter_touch_notes
        conv = tmp_path / "40 Conversations"
        conv.mkdir()
        touch_path = conv / "2026-05-01 test draft.md"
        touch_path.write_text(
            "---\n"
            "type: touch\n"
            "person: '[[Test Person]]'\n"
            "channel: calendar\n"
            "sent: false\n"
            "date: 2026-05-01\n"
            "---\n"
            "body\n",
            encoding="utf-8",
        )
        records = _walk_calendar_touch_records(iter_touch_notes(tmp_path))
        assert records == []


# ---------------------------------------------------------------------------
# touch_note field stamping (per Week 2 P2-4 discipline + carried)
# ---------------------------------------------------------------------------


class TestTouchNoteFieldStamping:
    def test_intent_carries_touch_note_field(self, synthetic_state_dir):
        """The intent event stamps the originating touch_note path so
        queries on the event can find the source touch without
        re-walking the vault."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        MIGRATION.upgrade(ctx)
        intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        )
        backfill_intents = [
            e for e in intents
            if e.get("intent_id", "").startswith(SYNTHETIC_INTENT_PREFIX)
        ]
        assert len(backfill_intents) == 1
        touch_note = backfill_intents[0].get("touch_note")
        assert touch_note is not None
        assert "Fiona" in touch_note
        assert "calendar booking" in touch_note.lower()


# ---------------------------------------------------------------------------
# Cross-migration interaction with ledger/0002
# ---------------------------------------------------------------------------


class TestLedger0002Interaction:
    def test_ledger_0002_walks_fiona_too(self, synthetic_state_dir):
        """Fiona's calendar touch is ``sent: true`` so ledger/0002's
        channel-agnostic walker emits a generic send_intent+send_confirmed
        pair (channel:calendar). The dual representation is by design
        per ADR-0019."""
        from orchestrator.migrations.ledger.migration_0002 import (
            MIGRATION as LEDGER_0002,
        )
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        LEDGER_0002.upgrade(ctx)
        send_confirms = _events_by_type(
            synthetic_state_dir.ledger_dir, "send_confirmed",
        )
        # At least one send_confirmed is channel: calendar (Fiona's).
        calendar_send_confirms = [
            e for e in send_confirms if e.get("channel") == "calendar"
        ]
        assert len(calendar_send_confirms) >= 1

    def test_ledger_0006_runs_independently_of_0002(
        self, synthetic_state_dir,
    ):
        """ledger/0006 emits its own per-channel events; ledger/0002's
        events don't share intent_ids with ledger/0006's, so no
        deduplication interference."""
        _apply_vault_backfill_first(synthetic_state_dir)
        ctx = _make_ctx(
            state_dir=synthetic_state_dir.state_dir,
            vault_dir=synthetic_state_dir.vault_dir,
        )
        # Run ledger/0006 only (skip ledger/0002).
        MIGRATION.upgrade(ctx)
        # Fiona's calendar_booking_intent lands.
        calendar_intents = _events_by_type(
            synthetic_state_dir.ledger_dir, "calendar_booking_intent",
        )
        assert any(
            e.get("person_id") == "fionaforrest-li"
            for e in calendar_intents
        )
