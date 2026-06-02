"""Unit tests for the ledger-migration helper module.

Covers ``orchestrator.migrations.ledger._ledger_io``:

* ``iter_events`` — walks every ``events-YYYY-MM-DD.jsonl`` file in
  the ledger directory, yields events in chronological order by
  ``ts``, skips malformed lines (parsing-tolerant, matches
  ``orchestrator.ledger.Ledger._load_events``).
* ``append_event_atomic`` — delegates to ``Ledger.append`` so every
  ledger-migration write goes through the same ``O_APPEND +
  fcntl.lockf + fsync`` durability path the production send loop
  uses. Auto-fills ``ts`` and ``v`` defaults.
* ``emit_migration_event`` — writes the ``migration_event`` audit-trail
  event every ledger migration emits at the end of ``upgrade``.
* ``latest_intent_outcome`` — returns the latest
  ``send_confirmed | send_failed | send_aborted`` event for an
  ``intent_id``, or ``None`` when the intent has no outcome yet.
* ``events_by_type`` — convenience filter for "every event with
  type=X."

No real ``apply`` / ``runner`` exercise here — those live in
``test_migrations_ledger_0001.py`` and ``test_migrations_runner.py``.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Iterable

import pytest

from orchestrator.migrations.ledger._ledger_io import (
    append_event_atomic,
    emit_migration_event,
    events_by_type,
    iter_events,
    latest_intent_outcome,
)


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    """Isolated ledger directory per test."""
    d = tmp_path / "ledger"
    d.mkdir()
    return d


def _write_jsonl(
    ledger_dir: Path, filename: str, events: Iterable[dict],
) -> Path:
    """Write raw JSONL to a ledger file, bypassing append_event_atomic.

    Used to seed test fixtures without going through Ledger.append
    (so tests can control ``ts`` precisely and write malformed lines
    on purpose).
    """
    p = ledger_dir / filename
    p.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# iter_events
# ---------------------------------------------------------------------------


class TestIterEvents:
    def test_empty_ledger_dir_yields_nothing(self, ledger_dir: Path):
        assert list(iter_events(ledger_dir)) == []

    def test_missing_ledger_dir_yields_nothing(self, tmp_path: Path):
        """A ledger dir that doesn't exist yet is treated as empty.

        Some tests construct a runner with ``ledger_dir=tmp / "ledger"``
        without pre-creating the directory; the helper must tolerate
        that the same way ``Ledger.__init__`` does (it mkdirs).
        """
        nonexistent = tmp_path / "no_ledger_yet"
        # iter_events should not blow up; treats missing as empty.
        assert list(iter_events(nonexistent)) == []

    def test_walks_single_file(self, ledger_dir: Path):
        _write_jsonl(ledger_dir, "events-2026-05-19.jsonl", [
            {"v": 1, "ts": "2026-05-19T10:00:00.000Z",
             "type": "send_intent", "intent_id": "i1"},
            {"v": 1, "ts": "2026-05-19T11:00:00.000Z",
             "type": "send_confirmed", "intent_id": "i1"},
        ])
        events = list(iter_events(ledger_dir))
        assert len(events) == 2
        assert events[0]["type"] == "send_intent"
        assert events[1]["type"] == "send_confirmed"

    def test_walks_multiple_files_in_chronological_order(
        self, ledger_dir: Path,
    ):
        """Two daily files with events that interleave by ts.

        The helper sorts globally by ``ts``, so the May 16 send_confirmed
        comes BEFORE the May 17 send_intent even though file order says
        otherwise (alphabetic file order would also work here, but the
        chronological guarantee matters for backfilled events whose
        ``ts`` is older than the file mtime).
        """
        _write_jsonl(ledger_dir, "events-2026-05-15.jsonl", [
            {"v": 1, "ts": "2026-05-15T10:00:00.000Z",
             "type": "enrolled", "person_id": "p1"},
        ])
        _write_jsonl(ledger_dir, "events-2026-05-17.jsonl", [
            {"v": 1, "ts": "2026-05-17T10:00:00.000Z",
             "type": "send_intent", "intent_id": "i1"},
        ])
        _write_jsonl(ledger_dir, "events-2026-05-16.jsonl", [
            {"v": 1, "ts": "2026-05-16T10:00:00.000Z",
             "type": "research_complete", "person_id": "p1"},
        ])
        events = list(iter_events(ledger_dir))
        types = [e["type"] for e in events]
        assert types == ["enrolled", "research_complete", "send_intent"]

    def test_backfilled_events_sort_before_live_ones(
        self, ledger_dir: Path,
    ):
        """A backfill event ``ts`` may be older than the file's name's
        date (the file was written today but represents past activity).
        Global ts-sort yields the backfill event first."""
        _write_jsonl(ledger_dir, "events-2026-05-19.jsonl", [
            {"v": 1, "ts": "2026-05-19T10:00:00.000Z",
             "type": "enrolled", "person_id": "p_today"},
            {"v": 1, "ts": "2024-01-01T00:00:00.000Z",
             "type": "enrolled", "person_id": "p_old",
             "_recovered_by": "backfill"},
        ])
        events = list(iter_events(ledger_dir))
        assert events[0]["person_id"] == "p_old"
        assert events[1]["person_id"] == "p_today"

    def test_skips_malformed_json_lines(self, ledger_dir: Path):
        """A truncated tail or partially-written line is skipped
        with no fatal error (matches Ledger._load_events tolerance)."""
        p = ledger_dir / "events-2026-05-19.jsonl"
        p.write_text(
            json.dumps({"v": 1, "ts": "2026-05-19T10:00:00.000Z",
                        "type": "send_intent", "intent_id": "i1"}) + "\n"
            + "this-is-not-json{\n"
            + json.dumps({"v": 1, "ts": "2026-05-19T11:00:00.000Z",
                          "type": "send_confirmed", "intent_id": "i1"}) + "\n",
            encoding="utf-8",
        )
        events = list(iter_events(ledger_dir))
        assert len(events) == 2
        assert events[0]["type"] == "send_intent"
        assert events[1]["type"] == "send_confirmed"

    def test_skips_blank_lines(self, ledger_dir: Path):
        p = ledger_dir / "events-2026-05-19.jsonl"
        p.write_text(
            "\n"
            + json.dumps({"v": 1, "ts": "2026-05-19T10:00:00.000Z",
                          "type": "enrolled", "person_id": "p1"}) + "\n"
            + "\n"
            + "  \n",
            encoding="utf-8",
        )
        events = list(iter_events(ledger_dir))
        assert len(events) == 1

    def test_skips_lines_without_type_field(self, ledger_dir: Path):
        """Per Ledger._load_events: a JSON object missing ``type`` is
        not a valid event; skip silently with the same tolerance the
        production reader applies."""
        p = ledger_dir / "events-2026-05-19.jsonl"
        p.write_text(
            json.dumps({"v": 1, "ts": "2026-05-19T10:00:00.000Z",
                        "type": "enrolled", "person_id": "p1"}) + "\n"
            + json.dumps({"v": 1, "ts": "2026-05-19T11:00:00.000Z",
                          "person_id": "p2"}) + "\n",  # no type
            encoding="utf-8",
        )
        events = list(iter_events(ledger_dir))
        assert len(events) == 1
        assert events[0]["person_id"] == "p1"

    def test_skips_lines_that_are_json_but_not_objects(
        self, ledger_dir: Path,
    ):
        p = ledger_dir / "events-2026-05-19.jsonl"
        p.write_text(
            json.dumps({"v": 1, "ts": "2026-05-19T10:00:00.000Z",
                        "type": "enrolled", "person_id": "p1"}) + "\n"
            + json.dumps([1, 2, 3]) + "\n"  # array, not an object
            + json.dumps("just a string") + "\n",
            encoding="utf-8",
        )
        events = list(iter_events(ledger_dir))
        assert len(events) == 1

    def test_returns_dicts_not_events(self, ledger_dir: Path):
        """Migrations operate on raw dicts; the helper does NOT wrap
        in Event (avoid pulling Ledger internals into the migration's
        surface)."""
        _write_jsonl(ledger_dir, "events-2026-05-19.jsonl", [
            {"v": 1, "ts": "2026-05-19T10:00:00.000Z",
             "type": "send_intent", "intent_id": "i1"},
        ])
        events = list(iter_events(ledger_dir))
        assert isinstance(events[0], dict)

    def test_ignores_non_event_files_in_ledger_dir(
        self, ledger_dir: Path,
    ):
        """The ledger dir contains the symlink + lock files. Only
        ``events-YYYY-MM-DD.jsonl`` files are iterated."""
        _write_jsonl(ledger_dir, "events-2026-05-19.jsonl", [
            {"v": 1, "ts": "2026-05-19T10:00:00.000Z",
             "type": "enrolled", "person_id": "p1"},
        ])
        # Decoy files the iterator must ignore.
        (ledger_dir / "events.jsonl.lock").write_text("not an event\n")
        (ledger_dir / "README.md").write_text("a stray doc")
        (ledger_dir / "events-malformed").write_text("no .jsonl suffix")
        events = list(iter_events(ledger_dir))
        assert len(events) == 1


# ---------------------------------------------------------------------------
# append_event_atomic
# ---------------------------------------------------------------------------


class TestAppendEventAtomic:
    def test_appends_an_event(self, ledger_dir: Path):
        result = append_event_atomic(
            ledger_dir,
            {"type": "send_aborted", "intent_id": "i1",
             "_recovered_by": "test"},
        )
        events = list(iter_events(ledger_dir))
        assert len(events) == 1
        assert events[0]["type"] == "send_aborted"
        assert events[0]["intent_id"] == "i1"

    def test_returns_event_with_ts_and_v_filled_in(self, ledger_dir: Path):
        """Like ``Ledger.append``, the helper fills ``ts`` and ``v``
        defaults if absent. The returned dict has both."""
        result = append_event_atomic(
            ledger_dir, {"type": "send_aborted", "intent_id": "i1"},
        )
        assert "ts" in result
        assert result["v"] == 1

    def test_preserves_explicit_ts(self, ledger_dir: Path):
        """A caller can pin ``ts`` explicitly (used by backfill); the
        helper does NOT overwrite a present ``ts``."""
        result = append_event_atomic(
            ledger_dir,
            {"type": "send_aborted", "intent_id": "i1",
             "ts": "2025-01-01T00:00:00.000Z"},
        )
        assert result["ts"] == "2025-01-01T00:00:00.000Z"

    def test_refuses_event_without_type(self, ledger_dir: Path):
        """``Ledger.append`` raises ValueError on missing type; the
        helper inherits that."""
        with pytest.raises(ValueError, match="type"):
            append_event_atomic(ledger_dir, {"intent_id": "i1"})

    def test_appends_two_events_independently(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {"type": "send_intent",
                                         "intent_id": "i1"})
        append_event_atomic(ledger_dir, {"type": "send_confirmed",
                                         "intent_id": "i1"})
        events = list(iter_events(ledger_dir))
        assert len(events) == 2

    def test_creates_ledger_dir_if_missing(self, tmp_path: Path):
        """Mirror Ledger's mkdir-on-init behavior — if a migration
        runs against a fresh state directory whose ledger sub-dir
        doesn't yet exist, the helper creates it."""
        nonexistent = tmp_path / "fresh_ledger"
        append_event_atomic(
            nonexistent,
            {"type": "migration_event", "migration_id": "test"},
        )
        assert nonexistent.exists()
        events = list(iter_events(nonexistent))
        assert len(events) == 1


def _append_n_times_in_subprocess(args):
    """Helper for the cross-process concurrency test below.

    Pytest's ``multiprocessing.spawn`` context requires top-level
    callables (not closures, not test-method-bound methods).
    """
    ledger_dir_str, n, worker_id = args
    from orchestrator.migrations.ledger._ledger_io import (  # noqa: E501
        append_event_atomic,
    )
    for i in range(n):
        append_event_atomic(
            Path(ledger_dir_str),
            {"type": "send_intent",
             "intent_id": f"w{worker_id}_i{i}"},
        )


class TestConcurrentAppends:
    def test_two_processes_appending_dont_corrupt(
        self, ledger_dir: Path,
    ):
        """Cross-process concurrency test: two workers each append 10
        events. The fcntl.lockf serialization in ``Ledger.append``
        guarantees no torn lines. Exactly 20 events are visible after
        both workers complete.
        """
        n = 10
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=2) as pool:
            pool.map(_append_n_times_in_subprocess, [
                (str(ledger_dir), n, 0),
                (str(ledger_dir), n, 1),
            ])
        events = list(iter_events(ledger_dir))
        assert len(events) == 2 * n
        intent_ids = {e["intent_id"] for e in events}
        assert intent_ids == {f"w{w}_i{i}" for w in (0, 1) for i in range(n)}


# ---------------------------------------------------------------------------
# emit_migration_event
# ---------------------------------------------------------------------------


class TestEmitMigrationEvent:
    def test_writes_event_with_migration_id(self, ledger_dir: Path):
        out = emit_migration_event(
            ledger_dir,
            migration_id="0001_test_migration",
            affected_count=5,
        )
        assert out["type"] == "migration_event"
        assert out["migration_id"] == "0001_test_migration"
        assert out["affected_count"] == 5
        events = list(iter_events(ledger_dir))
        assert len(events) == 1

    def test_passes_through_extra_fields(self, ledger_dir: Path):
        """Extra kwargs are added as event fields (for free-form
        diagnostic context like which category, which runner version)."""
        out = emit_migration_event(
            ledger_dir,
            migration_id="0001_test",
            affected_count=0,
            runner_version="0.1.0",
            category="ledger",
            note="initial run; no orphans found",
        )
        assert out["runner_version"] == "0.1.0"
        assert out["category"] == "ledger"
        assert out["note"] == "initial run; no orphans found"

    def test_fills_ts_and_v(self, ledger_dir: Path):
        out = emit_migration_event(
            ledger_dir, migration_id="0001_x", affected_count=0,
        )
        assert "ts" in out
        assert out["v"] == 1

    def test_multiple_emit_calls_each_get_their_own_event(
        self, ledger_dir: Path,
    ):
        emit_migration_event(
            ledger_dir, migration_id="0001_x", affected_count=0,
        )
        emit_migration_event(
            ledger_dir, migration_id="0002_y", affected_count=3,
        )
        events = list(iter_events(ledger_dir))
        migration_events = [e for e in events
                            if e.get("type") == "migration_event"]
        assert len(migration_events) == 2
        ids = sorted(e["migration_id"] for e in migration_events)
        assert ids == ["0001_x", "0002_y"]

    def test_reserved_field_type_in_extra_raises_value_error(
        self, ledger_dir: Path,
    ):
        """Per ADR-0010 D17, the helper raises ValueError if **extra
        includes a reserved field name. The reserved set is
        {type, migration_id, affected_count, ts, v}; passing any of
        them as a kwarg via **extra is a programming error caught at
        write time (not at Pillar G / J query time)."""
        with pytest.raises(ValueError, match="collide with reserved"):
            emit_migration_event(
                ledger_dir,
                migration_id="0001_test",
                affected_count=0,
                type="override_attempt",  # reserved
            )

    def test_reserved_field_v_in_extra_raises_value_error(
        self, ledger_dir: Path,
    ):
        with pytest.raises(ValueError, match="collide with reserved"):
            emit_migration_event(
                ledger_dir,
                migration_id="0001_test",
                affected_count=0,
                v=99,  # reserved
            )

    def test_reserved_field_ts_in_extra_raises_value_error(
        self, ledger_dir: Path,
    ):
        with pytest.raises(ValueError, match="collide with reserved"):
            emit_migration_event(
                ledger_dir,
                migration_id="0001_test",
                affected_count=0,
                ts="2026-01-01T00:00:00.000Z",  # reserved
            )

    def test_reserved_field_error_names_the_colliding_field(
        self, ledger_dir: Path,
    ):
        """The ValueError message names which reserved field collided
        (a sorted list), so the contributor sees the offending field
        without cross-referencing the reserved set in the source.

        Note: ``migration_id`` and ``affected_count`` are explicit
        kwargs of :func:`emit_migration_event`, so Python's call
        binding guards them BEFORE the reserved-field check runs —
        a caller that tries to pass them via ``**extra`` triggers a
        ``TypeError: ... got multiple values for keyword argument``
        directly. The reserved-field check is therefore practically
        reachable only for ``type``, ``ts``, ``v``; the larger
        reserved set is defensive against future changes to the
        function signature (if ``ts`` ever becomes an explicit kwarg,
        the check still names the reserved namespace correctly).
        """
        with pytest.raises(ValueError, match="'ts'"):
            emit_migration_event(
                ledger_dir,
                migration_id="0001_test",
                affected_count=0,
                ts="2026-01-01T00:00:00.000Z",
                v=99,
            )

    def test_non_reserved_extras_still_pass_through(
        self, ledger_dir: Path,
    ):
        """Non-reserved kwargs go into the event as extra fields —
        unchanged from the happy-path tests; this reasserts that the
        collision check is narrow + doesn't reject legitimate extras."""
        out = emit_migration_event(
            ledger_dir,
            migration_id="0001_test",
            affected_count=0,
            runner_version="0.1.0",     # not reserved
            category="ledger",          # not reserved
            notes="non-reserved fields are fine",
            skipped_raced=2,            # not reserved
        )
        assert out["runner_version"] == "0.1.0"
        assert out["category"] == "ledger"
        assert out["skipped_raced"] == 2


# ---------------------------------------------------------------------------
# latest_intent_outcome
# ---------------------------------------------------------------------------


class TestLatestIntentOutcome:
    def test_returns_none_when_no_outcome(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {
            "type": "send_intent", "intent_id": "i1",
        })
        assert latest_intent_outcome(ledger_dir, "i1") is None

    def test_returns_none_when_no_intent_at_all(self, ledger_dir: Path):
        assert latest_intent_outcome(ledger_dir, "never_existed") is None

    def test_returns_send_confirmed(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {
            "type": "send_intent", "intent_id": "i1",
        })
        append_event_atomic(ledger_dir, {
            "type": "send_confirmed", "intent_id": "i1",
        })
        out = latest_intent_outcome(ledger_dir, "i1")
        assert out is not None
        assert out["type"] == "send_confirmed"

    def test_returns_send_failed(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {
            "type": "send_intent", "intent_id": "i1",
        })
        append_event_atomic(ledger_dir, {
            "type": "send_failed", "intent_id": "i1",
        })
        out = latest_intent_outcome(ledger_dir, "i1")
        assert out is not None
        assert out["type"] == "send_failed"

    def test_returns_send_aborted(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {
            "type": "send_intent", "intent_id": "i1",
        })
        append_event_atomic(ledger_dir, {
            "type": "send_aborted", "intent_id": "i1",
        })
        out = latest_intent_outcome(ledger_dir, "i1")
        assert out is not None
        assert out["type"] == "send_aborted"

    def test_latest_outcome_wins_when_multiple(self, ledger_dir: Path):
        """If a flaky network produced both fail and confirm for the
        same intent_id, the chronologically-latest outcome wins.
        Matches ``Ledger._idx_intent_outcome`` behavior (chronological
        last write wins)."""
        _write_jsonl(ledger_dir, "events-2026-05-19.jsonl", [
            {"v": 1, "ts": "2026-05-19T10:00:00.000Z",
             "type": "send_intent", "intent_id": "i1"},
            {"v": 1, "ts": "2026-05-19T10:01:00.000Z",
             "type": "send_failed", "intent_id": "i1"},
            {"v": 1, "ts": "2026-05-19T10:02:00.000Z",
             "type": "send_confirmed", "intent_id": "i1"},
        ])
        out = latest_intent_outcome(ledger_dir, "i1")
        assert out is not None
        assert out["type"] == "send_confirmed"

    def test_ignores_unrelated_intents(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {
            "type": "send_intent", "intent_id": "i1",
        })
        append_event_atomic(ledger_dir, {
            "type": "send_confirmed", "intent_id": "i2",  # different intent
        })
        assert latest_intent_outcome(ledger_dir, "i1") is None
        out = latest_intent_outcome(ledger_dir, "i2")
        assert out is not None and out["type"] == "send_confirmed"


# ---------------------------------------------------------------------------
# events_by_type
# ---------------------------------------------------------------------------


class TestEventsByType:
    def test_filters_to_one_type(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {"type": "send_intent",
                                         "intent_id": "i1"})
        append_event_atomic(ledger_dir, {"type": "send_intent",
                                         "intent_id": "i2"})
        append_event_atomic(ledger_dir, {"type": "send_confirmed",
                                         "intent_id": "i1"})
        intents = list(events_by_type(ledger_dir, "send_intent"))
        assert len(intents) == 2
        assert all(e["type"] == "send_intent" for e in intents)

    def test_returns_empty_when_no_matches(self, ledger_dir: Path):
        append_event_atomic(ledger_dir, {"type": "send_intent",
                                         "intent_id": "i1"})
        out = list(events_by_type(ledger_dir, "migration_event"))
        assert out == []

    def test_preserves_chronological_order(self, ledger_dir: Path):
        _write_jsonl(ledger_dir, "events-2026-05-19.jsonl", [
            {"v": 1, "ts": "2026-05-19T10:00:00.000Z",
             "type": "send_intent", "intent_id": "i2"},
            {"v": 1, "ts": "2026-05-19T09:00:00.000Z",
             "type": "send_intent", "intent_id": "i1"},
        ])
        intents = list(events_by_type(ledger_dir, "send_intent"))
        # Globally sorted by ts even though file-order put i2 first.
        assert [e["intent_id"] for e in intents] == ["i1", "i2"]
