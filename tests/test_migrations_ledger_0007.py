"""Tests for ledger migration 0007 — backfill enrolled.source_skill.

Pillar E Week 9-11 — per ADR-0036 D170. Coverage:

* TestMigrationSurface — Migration Protocol shape pins
* TestUpgradeHappyPath — per-event backfill emission shape
* TestUpgradeNormalization — legacy source → canonical source_skill mapping
* TestUpgradeIdempotence — re-running upgrade is a no-op
* TestUpgradeAppendOnly — original enrolled events unchanged
* TestUpgradeRefuseLoud — missing ledger; downgrade unsupported
* TestDryRun — dry-run doesn't append events

See ADR-0036 D170 for the design rationale (append-only-backfill
pattern instead of in-place rewrite).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.migrations.ledger._ledger_io import (
    append_event_atomic,
    events_by_type,
    iter_events,
)
from orchestrator.migrations.ledger.migration_0007_backfill_enrolled_source_skill import (
    BACKFILL_EVENT_TYPE,
    MIGRATION,
    MIGRATION_ID,
    BackfillEnrolledSourceSkill,
)
from orchestrator.migrations.types import (
    MigrationCategory, MigrationContext,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    *,
    state_dir: Path,
    ledger_dir: Path,
    dry_run: bool = False,
) -> MigrationContext:
    return MigrationContext(
        dry_run=dry_run,
        state_dir=state_dir,
        ledger_dir=ledger_dir,
        vault_dir=None,
        policy_dir=state_dir / "policies",
        now=datetime.now(timezone.utc),
        logger=logging.getLogger("test.ledger.0007"),
    )


def _write_enrolled_event(
    ledger_dir: Path,
    person_id: str,
    source: str | None,
    ts: str = "2026-05-13T10:00:00Z",
    source_skill: str | None = None,
    source_list: str = "[[2026-05-13-test]]",
) -> dict:
    """Append a synthetic enrolled event to the ledger."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ev = {
        "type": "enrolled",
        "person_id": person_id,
        "ts": ts,
        "v": 1,
        "source_list": source_list,
    }
    if source is not None:
        ev["source"] = source
    if source_skill is not None:
        ev["source_skill"] = source_skill
    append_event_atomic(ledger_dir, ev)
    return ev


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ledger"
    d.mkdir()
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# TestMigrationSurface — Migration Protocol pins
# ---------------------------------------------------------------------------


class TestMigrationSurface:

    def test_migration_id(self):
        assert MIGRATION.id == "0007_backfill_enrolled_source_skill"
        assert MIGRATION_ID == MIGRATION.id

    def test_category_is_ledger(self):
        assert MIGRATION.category == MigrationCategory.LEDGER

    def test_is_not_reversible(self):
        """Per ADR-0010 D14 the ledger is append-only — no rollback."""
        assert MIGRATION.is_reversible is False

    def test_description_mentions_source_skill(self):
        assert "source_skill" in MIGRATION.description.lower()

    def test_singleton_is_dataclass_instance(self):
        assert isinstance(MIGRATION, BackfillEnrolledSourceSkill)

    def test_backfill_event_type_constant(self):
        assert BACKFILL_EVENT_TYPE == "enrolled_source_skill_backfill"


# ---------------------------------------------------------------------------
# TestUpgradeHappyPath
# ---------------------------------------------------------------------------


class TestUpgradeHappyPath:

    def test_emits_backfill_per_enrolled_lacking_source_skill(
        self, ledger_dir, state_dir,
    ):
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        _write_enrolled_event(
            ledger_dir, "bob-li", source="funded-founders",
            ts="2026-05-13T11:00:00Z",
        )

        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)

        assert result.applied is True
        assert result.affected_count == 2

        backfills = list(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE))
        assert len(backfills) == 2
        bf_by_pid = {ev["person_id"]: ev for ev in backfills}
        assert bf_by_pid["alice-li"]["source_skill"] == "find-leads"
        assert bf_by_pid["bob-li"]["source_skill"] == "find-funded-founders"

    def test_backfill_event_carries_pairing_key(self, ledger_dir, state_dir):
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)

        bf = next(iter(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE)))
        assert bf["_backfill_of_ts"] == "2026-05-13T10:00:00Z"

    def test_backfill_event_carries_recovered_by(self, ledger_dir, state_dir):
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)
        bf = next(iter(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE)))
        assert bf["_recovered_by"] == "migration_0007_backfill_enrolled_source_skill"

    def test_backfill_event_carries_channel_none(self, ledger_dir, state_dir):
        """Per ADR-0014 D33 channel-on-every-event invariant."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)
        bf = next(iter(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE)))
        assert bf["channel"] == "none"

    def test_backfill_event_carries_emitted_by(self, ledger_dir, state_dir):
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)
        bf = next(iter(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE)))
        assert bf["_emitted_by"] == "discovery_lineage"

    def test_migration_event_emitted_at_end(self, ledger_dir, state_dir):
        """Per ADR-0010 D17 — every ledger migration emits a migration_event."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)

        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert len(migration_events) == 1
        me = migration_events[0]
        assert me["migration_id"] == "0007_backfill_enrolled_source_skill"
        assert me["affected_count"] == 1


# ---------------------------------------------------------------------------
# TestUpgradeNormalization
# ---------------------------------------------------------------------------


class TestUpgradeNormalization:

    def test_funded_founders_normalizes(self, ledger_dir, state_dir):
        """Legacy "funded-founders" → canonical "find-funded-founders"."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="funded-founders",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)
        bf = next(iter(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE)))
        assert bf["source_skill"] == "find-funded-founders"

    def test_canonical_value_passes_through(self, ledger_dir, state_dir):
        """Operator who pre-wrote canonical form gets canonical form back."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-funded-founders",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)
        bf = next(iter(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE)))
        assert bf["source_skill"] == "find-funded-founders"

    def test_unknown_source_normalizes_to_manual(self, ledger_dir, state_dir):
        _write_enrolled_event(
            ledger_dir, "alice-li", source="legacy-csv-import",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)
        bf = next(iter(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE)))
        assert bf["source_skill"] == "manual"

    def test_every_canonical_skill_emits(self, ledger_dir, state_dir):
        """Every value in the legacy→canonical map produces a valid backfill."""
        from orchestrator.discovery_lineage import (
            LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL,
        )
        for i, (legacy, _) in enumerate(LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL.items()):
            _write_enrolled_event(
                ledger_dir, f"person-{i}", source=legacy,
                ts=f"2026-05-{13 + i:02d}T10:00:00Z",
            )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)
        # Backfill emitted for every event.
        assert result.affected_count == len(LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL)


# ---------------------------------------------------------------------------
# TestUpgradeIdempotence
# ---------------------------------------------------------------------------


class TestUpgradeIdempotence:

    def test_already_canonical_skipped(self, ledger_dir, state_dir):
        """Enrolled events ALREADY carrying source_skill are not re-backfilled."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            source_skill="find-leads",  # already canonical
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0

    def test_re_running_upgrade_does_not_duplicate(self, ledger_dir, state_dir):
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        r1 = MIGRATION.upgrade(ctx)
        r2 = MIGRATION.upgrade(ctx)
        assert r1.affected_count == 1
        assert r2.affected_count == 0

        backfills = list(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE))
        assert len(backfills) == 1

    def test_enrolled_without_source_skipped(self, ledger_dir, state_dir):
        """Pre-source-attribution enrolled events are skipped."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source=None,  # no source field
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0

    def test_idempotence_key_is_ts_plus_person_id_not_ts_alone(
        self, ledger_dir, state_dir,
    ):
        """Pillar E Week 9-11 review P2-B regression pin.

        Two enrolled events sharing the same `ts` (different Persons)
        MUST each get their own backfill event. A third enrolled event
        arriving with the same `ts` after the migration has run MUST
        also get a backfill on the next migration run — the idempotence
        key MUST be (ts, person_id), not ts alone.

        Scenario:
        1. Run #1: ledger has 2 enrolled events (alice + bob) at the
           same ts. Migration emits 2 backfill events.
        2. Manually append a 3rd enrolled event (carol) at the same ts.
        3. Run #2: migration must emit 1 NEW backfill for carol — NOT
           silently skip her because alice's pair is already
           backfilled at the same ts.
        """
        # Run #1: two enrolled events sharing ts.
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        _write_enrolled_event(
            ledger_dir, "bob-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",  # SAME ts as alice
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        r1 = MIGRATION.upgrade(ctx)
        assert r1.affected_count == 2

        # Now append a 3rd enrolled event for carol at the SAME ts.
        _write_enrolled_event(
            ledger_dir, "carol-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",  # SAME ts
        )
        # Run #2: should emit ONE NEW backfill for carol (alice + bob
        # already done). With ts-only key (the bug), carol would be
        # silently skipped because her ts is already in the set.
        r2 = MIGRATION.upgrade(ctx)
        assert r2.affected_count == 1, (
            "Expected exactly 1 new backfill event for carol-li. The "
            "idempotence key must be (ts, person_id), not ts alone. "
            "With ts-only keying, carol would be silently skipped "
            "because alice/bob's pair shares her ts — P2-B regression."
        )

        # Verify carol got her backfill paired correctly.
        backfills = list(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE))
        carol_backfills = [
            b for b in backfills if b["person_id"] == "carol-li"
        ]
        assert len(carol_backfills) == 1
        assert carol_backfills[0]["_backfill_of_ts"] == "2026-05-13T10:00:00Z"


# ---------------------------------------------------------------------------
# TestUpgradeAppendOnly
# ---------------------------------------------------------------------------


class TestUpgradeAppendOnly:

    def test_original_enrolled_unchanged(self, ledger_dir, state_dir):
        """The original enrolled event is unchanged after backfill (append-only)."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="funded-founders",
            ts="2026-05-13T10:00:00Z",
        )
        # Capture original event count + shape.
        before = list(events_by_type(ledger_dir, "enrolled"))
        assert len(before) == 1
        original_event = dict(before[0])

        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)

        after = list(events_by_type(ledger_dir, "enrolled"))
        assert len(after) == 1  # NO duplicate enrolled event
        # Original event preserved verbatim (except possibly ts/v defaults).
        assert after[0]["person_id"] == original_event["person_id"]
        assert after[0]["source"] == original_event["source"]
        assert after[0].get("source_skill") is None  # not added to original

    def test_no_double_counting_for_enrollment_metric(self, ledger_dir, state_dir):
        """Backfill events do NOT count as enrollments per the backfill_ledger consumer."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        MIGRATION.upgrade(ctx)

        enrolled_count = sum(
            1 for ev in iter_events(ledger_dir) if ev.get("type") == "enrolled"
        )
        assert enrolled_count == 1


# ---------------------------------------------------------------------------
# TestUpgradeRefuseLoud
# ---------------------------------------------------------------------------


class TestUpgradeRefuseLoud:

    def test_refuses_missing_ledger_dir(self, tmp_path):
        """Per ADR-0010 D15 — refuses-loud on non-existent ledger dir."""
        nonexistent = tmp_path / "no_ledger"
        ctx = _make_ctx(state_dir=tmp_path, ledger_dir=nonexistent)
        with pytest.raises(FileNotFoundError, match="does not exist"):
            MIGRATION.upgrade(ctx)

    def test_downgrade_raises_not_implemented(self, ledger_dir, state_dir):
        """Per ADR-0010 D14 — append-only ledger, no rollback."""
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        with pytest.raises(NotImplementedError, match="append-only"):
            MIGRATION.downgrade(ctx)


# ---------------------------------------------------------------------------
# TestDryRun
# ---------------------------------------------------------------------------


class TestDryRun:

    def test_dry_run_does_not_append(self, ledger_dir, state_dir):
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir, dry_run=True)
        result = MIGRATION.upgrade(ctx)
        assert result.dry_run is True
        assert result.affected_count == 1  # would affect, but didn't

        # No backfill events emitted.
        backfills = list(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE))
        assert backfills == []

        # No migration_event emitted on dry-run either.
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert migration_events == []


# ---------------------------------------------------------------------------
# TestEmptyLedger
# ---------------------------------------------------------------------------


class TestEmptyLedger:

    def test_zero_enrolled_events_emits_zero_backfills(self, ledger_dir, state_dir):
        """Ledger with no enrolled events — migration is a no-op + still emits migration_event."""
        # Empty ledger dir.
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 0

        backfills = list(events_by_type(ledger_dir, BACKFILL_EVENT_TYPE))
        assert backfills == []

        # But migration_event IS emitted per ADR-0010 D17.
        migration_events = list(events_by_type(ledger_dir, "migration_event"))
        assert len(migration_events) == 1
        assert migration_events[0]["affected_count"] == 0


# ---------------------------------------------------------------------------
# TestPerEnrolledMultipleEventsForSamePerson
# ---------------------------------------------------------------------------


class TestPerEventBackfill:
    """Each enrolled event gets its own backfill (not per-person)."""

    def test_multiple_enrolled_for_same_person_each_backfilled(
        self, ledger_dir, state_dir,
    ):
        """If a Person has multiple enrolled events (rare but possible per
        backfill_ledger), each one gets its own paired backfill."""
        _write_enrolled_event(
            ledger_dir, "alice-li", source="find-leads",
            ts="2026-05-13T10:00:00Z",
        )
        _write_enrolled_event(
            ledger_dir, "alice-li", source="competitor-customers",
            ts="2026-05-14T10:00:00Z",
        )
        ctx = _make_ctx(state_dir=state_dir, ledger_dir=ledger_dir)
        result = MIGRATION.upgrade(ctx)
        assert result.affected_count == 2

        backfills = sorted(
            events_by_type(ledger_dir, BACKFILL_EVENT_TYPE),
            key=lambda e: e["_backfill_of_ts"],
        )
        assert len(backfills) == 2
        assert backfills[0]["source_skill"] == "find-leads"
        assert backfills[1]["source_skill"] == "competitor-customers"
