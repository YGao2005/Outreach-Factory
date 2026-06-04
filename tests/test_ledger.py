"""Tests for orchestrator/ledger.py.

Covers the load-bearing properties:
  - Append round-trips through every index correctly
  - Concurrent appenders from multiple processes don't corrupt the file
  - Truncated tails are skipped with a warning, not propagated
  - Schema versioning: v=2 (future) events readable by current code
  - Daily rotation: writes after UTC midnight land in the new day's file
  - derived_stage replays event sequences correctly

The concurrency test uses real OS processes (multiprocessing) so the fcntl
+ O_APPEND atomicity is exercised end-to-end, not mocked.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import random
import string
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from orchestrator import ledger as ledger_mod
from orchestrator.ledger import (
    DEFAULT_LEDGER_DIR,
    Event,
    Ledger,
    funnel,
    new_intent_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ledger"
    d.mkdir()
    return d


@pytest.fixture
def led(ledger_dir: Path) -> Ledger:
    return Ledger(ledger_dir)


# ---------------------------------------------------------------------------
# Event wrapper
# ---------------------------------------------------------------------------


class TestEvent:
    def test_event_requires_type(self):
        with pytest.raises(ValueError):
            Event(person_id="abc")

    def test_event_defaults_schema_version(self):
        e = Event(type="enrolled")
        assert e.v == ledger_mod.SCHEMA_VERSION

    def test_event_accessors(self):
        e = Event(type="send_intent", person_id="p1", intent_id="snd_x",
                  channel="email", ts="2026-01-01T00:00:00Z")
        assert e.type == "send_intent"
        assert e.person_id == "p1"
        assert e.intent_id == "snd_x"
        assert e["channel"] == "email"
        assert e.ts == "2026-01-01T00:00:00Z"

    def test_event_round_trip(self):
        d = {"v": 1, "ts": "2026-05-15T10:00:00.000Z",
             "type": "draft_complete", "person_id": "p1", "custom": [1, 2]}
        e = Event.from_dict(d)
        assert e.to_dict() == d

    def test_event_from_dict_preserves_unknown_fields(self):
        # Forward-compat — readers must not drop fields they don't know about.
        d = {"type": "future_type_v9", "future_field": {"nested": True}}
        e = Event.from_dict(d)
        assert e.to_dict()["future_field"] == {"nested": True}


# ---------------------------------------------------------------------------
# Basic append + query
# ---------------------------------------------------------------------------


class TestAppendAndQuery:
    def test_append_creates_today_file(self, led: Ledger, ledger_dir: Path):
        led.append({"type": "enrolled", "person_id": "p1"})
        files = list(ledger_dir.glob("events-*.jsonl"))
        assert len(files) == 1
        assert files[0].name.startswith("events-")

    def test_append_creates_symlink(self, led: Ledger, ledger_dir: Path):
        led.append({"type": "enrolled", "person_id": "p1"})
        symlink = ledger_dir / "events.jsonl"
        assert symlink.is_symlink()

    def test_append_fills_ts_and_v(self, led: Ledger):
        out = led.append({"type": "enrolled", "person_id": "p1"})
        assert "ts" in out
        assert out["v"] == ledger_mod.SCHEMA_VERSION

    def test_append_preserves_explicit_ts(self, led: Ledger):
        out = led.append({"type": "enrolled", "person_id": "p1",
                          "ts": "2026-05-01T00:00:00.000Z"})
        assert out["ts"] == "2026-05-01T00:00:00.000Z"

    def test_append_rejects_missing_type(self, led: Ledger):
        with pytest.raises(ValueError):
            led.append({"person_id": "p1"})

    def test_query_by_person(self, led: Ledger):
        led.append({"type": "enrolled", "person_id": "p1"})
        led.append({"type": "research_complete", "person_id": "p1"})
        led.append({"type": "enrolled", "person_id": "p2"})
        events = led.query_by_person("p1")
        assert len(events) == 2
        assert all(e.person_id == "p1" for e in events)

    def test_query_by_person_since(self, led: Ledger):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": "2026-01-01T00:00:00.000Z"})
        led.append({"type": "research_complete", "person_id": "p1",
                    "ts": "2026-06-01T00:00:00.000Z"})
        cutoff = datetime(2026, 5, 1, tzinfo=timezone.utc)
        events = led.query_by_person("p1", since=cutoff)
        assert len(events) == 1
        assert events[0].type == "research_complete"

    def test_query_by_intent_returns_origin(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        led.append({"type": "send_confirmed", "intent_id": "snd_x",
                    "gmail_message_id": "abc"})
        e = led.query_by_intent("snd_x")
        assert e is not None
        assert e.type == "send_intent"

    def test_outcome_for_intent(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        led.append({"type": "send_confirmed", "intent_id": "snd_x",
                    "gmail_message_id": "abc"})
        outcome = led.outcome_for_intent("snd_x")
        assert outcome is not None
        assert outcome.type == "send_confirmed"

    def test_query_by_gmail_message_id(self, led: Ledger):
        led.append({"type": "send_confirmed", "intent_id": "snd_x",
                    "gmail_message_id": "msg_abc"})
        e = led.query_by_gmail_message_id("msg_abc")
        assert e is not None
        assert e["gmail_message_id"] == "msg_abc"

    def test_query_by_intent_missing(self, led: Ledger):
        assert led.query_by_intent("nonexistent") is None

    def test_query_by_email(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email",
                    "email": "Alice@Example.com"})
        # Lowercase normalization on lookup.
        assert "p1" in led.query_by_email("alice@example.com")


# ---------------------------------------------------------------------------
# Content distribution two-phase index (ADR-0082 D408/D416 Phase 2)
# ---------------------------------------------------------------------------


class TestDistributionIndex:
    def test_query_by_post_id(self, led: Ledger):
        led.append({"type": "distribution_confirmed", "content_id": "cpc_1",
                    "channel": "linkedin_post", "intent_id": "cont_x",
                    "post_id": "urn:li:activity:7"})
        e = led.query_by_post_id("urn:li:activity:7", channel="linkedin_post")
        assert e is not None
        assert e["post_id"] == "urn:li:activity:7"

    def test_post_id_keyed_by_channel(self, led: Ledger):
        # Opaque ids can collide across platforms; the (channel, post_id) key
        # keeps them distinct.
        led.append({"type": "distribution_confirmed", "content_id": "cpc_1",
                    "channel": "linkedin_post", "intent_id": "cont_a", "post_id": "123"})
        led.append({"type": "distribution_confirmed", "content_id": "cpc_2",
                    "channel": "x_post", "intent_id": "cont_b", "post_id": "123"})
        assert led.query_by_post_id("123", channel="linkedin_post")["content_id"] == "cpc_1"
        assert led.query_by_post_id("123", channel="x_post")["content_id"] == "cpc_2"

    def test_query_by_post_id_missing(self, led: Ledger):
        assert led.query_by_post_id("nope", channel="x_post") is None

    def test_distribution_stays_out_of_cold_side_intent_index(self, led: Ledger):
        # ADR-0082 D416: distribution two-phase events are NOT in the generic
        # cold-side intent/outcome index (which feeds dispatch-health latency);
        # the broadcast surface has its own report + its own correlation walk.
        led.append({"type": "distribution_intent", "content_id": "cpc_1",
                    "channel": "x_post", "intent_id": "cont_y"})
        assert led.query_by_intent("cont_y") is None
        since = datetime(2000, 1, 1, tzinfo=timezone.utc)
        open_ids = {i.get("intent_id") for i in led.open_intents(since=since)}
        assert "cont_y" not in open_ids

    def test_distribution_event_does_not_pollute_person_indexes(self, led: Ledger):
        # The KEY isolation invariant: distribution events carry content_id, NOT
        # person_id, and a POST_CHANNELS channel, so they never enter the
        # per-person walk even though distribution_confirmed auto-enrolls into
        # _CONFIRMED_TYPES.
        led.append({"type": "distribution_confirmed", "content_id": "cpc_1",
                    "channel": "linkedin_post", "intent_id": "cont_z", "post_id": "p9"})
        assert led.last_send_for("p_any", channel="linkedin_post") is None
        assert led.confirmed_send_count("p_any", channel="linkedin_post") == 0


# ---------------------------------------------------------------------------
# Last-send gate
# ---------------------------------------------------------------------------


class TestLastSendFor:
    def test_no_send_returns_none(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        # No outcome yet → not "confirmed" → not a barrier.
        assert led.last_send_for("p1", "email") is None

    def test_send_failed_does_not_block(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        led.append({"type": "send_failed", "intent_id": "snd_x"})
        assert led.last_send_for("p1", "email") is None

    def test_send_confirmed_blocks(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        led.append({"type": "send_confirmed", "intent_id": "snd_x",
                    "gmail_message_id": "msg_abc"})
        e = led.last_send_for("p1", "email")
        assert e is not None
        assert e.type == "send_confirmed"

    def test_send_confirmed_other_channel_does_not_block(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "linkedin"})
        led.append({"type": "send_confirmed", "intent_id": "snd_x",
                    "gmail_message_id": "msg_abc"})
        assert led.last_send_for("p1", "email") is None
        assert led.last_send_for("p1", "linkedin") is not None

    def test_picks_latest_confirmed(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_1",
                    "person_id": "p1", "channel": "email",
                    "ts": "2026-01-01T00:00:00.000Z"})
        led.append({"type": "send_confirmed", "intent_id": "snd_1",
                    "ts": "2026-01-01T00:01:00.000Z"})
        led.append({"type": "send_intent", "intent_id": "snd_2",
                    "person_id": "p1", "channel": "email",
                    "ts": "2026-03-01T00:00:00.000Z"})
        led.append({"type": "send_confirmed", "intent_id": "snd_2",
                    "ts": "2026-03-01T00:01:00.000Z"})
        e = led.last_send_for("p1", "email")
        assert e is not None
        assert e["intent_id"] == "snd_2"


# ---------------------------------------------------------------------------
# Open intents
# ---------------------------------------------------------------------------


class TestOpenIntents:
    def test_open_intent_no_outcome(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        opens = led.open_intents(
            since=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert len(opens) == 1

    def test_open_intent_with_outcome_excluded(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        led.append({"type": "send_confirmed", "intent_id": "snd_x"})
        opens = led.open_intents(
            since=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert opens == []

    def test_min_age_filters_fresh_intents(self, led: Ledger):
        # Recent intent, min_age=5min → filtered out
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        opens = led.open_intents(
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            min_age=timedelta(minutes=5),
        )
        assert opens == []

    def test_channel_filter(self, led: Ledger):
        led.append({"type": "send_intent", "intent_id": "snd_a",
                    "person_id": "p1", "channel": "email"})
        led.append({"type": "send_intent", "intent_id": "snd_b",
                    "person_id": "p1", "channel": "linkedin"})
        opens_email = led.open_intents(
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            channel="email",
        )
        assert len(opens_email) == 1
        assert opens_email[0]["intent_id"] == "snd_a"


# ---------------------------------------------------------------------------
# derived_stage
# ---------------------------------------------------------------------------


class TestDerivedStage:
    def test_no_events_returns_none(self, led: Ledger):
        assert led.derived_stage("nobody") is None

    def test_enrolled_only_is_queued(self, led: Ledger):
        led.append({"type": "enrolled", "person_id": "p1"})
        assert led.derived_stage("p1") == "queued"

    def test_progression_through_stages(self, led: Ledger):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": "2026-01-01T00:00:00.000Z"})
        assert led.derived_stage("p1") == "queued"
        led.append({"type": "research_complete", "person_id": "p1",
                    "ts": "2026-01-02T00:00:00.000Z"})
        assert led.derived_stage("p1") == "researched"
        led.append({"type": "draft_complete", "person_id": "p1",
                    "ts": "2026-01-03T00:00:00.000Z"})
        assert led.derived_stage("p1") == "drafted"
        led.append({"type": "review_approved", "person_id": "p1",
                    "ts": "2026-01-04T00:00:00.000Z"})
        assert led.derived_stage("p1") == "ready"

    def test_confirmed_send_overrides_to_sent(self, led: Ledger):
        led.append({"type": "enrolled", "person_id": "p1",
                    "ts": "2026-01-01T00:00:00.000Z"})
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email",
                    "ts": "2026-01-02T00:00:00.000Z"})
        led.append({"type": "send_confirmed", "intent_id": "snd_x",
                    "ts": "2026-01-02T00:01:00.000Z"})
        assert led.derived_stage("p1") == "sent"

    def test_review_rejected_pushes_back_to_drafted(self, led: Ledger):
        led.append({"type": "draft_complete", "person_id": "p1",
                    "ts": "2026-01-01T00:00:00.000Z"})
        led.append({"type": "review_approved", "person_id": "p1",
                    "ts": "2026-01-02T00:00:00.000Z"})
        led.append({"type": "review_rejected", "person_id": "p1",
                    "ts": "2026-01-03T00:00:00.000Z"})
        assert led.derived_stage("p1") == "drafted"


# ---------------------------------------------------------------------------
# Property test — random events round-trip
# ---------------------------------------------------------------------------


class TestPropertyRandomEvents:
    def test_1000_random_events_round_trip(self, led: Ledger):
        rng = random.Random(42)  # deterministic
        person_pool = [f"p_{i}" for i in range(50)]
        intent_pool: list[tuple[str, str]] = []  # (intent_id, person_id)

        # Pre-generate ts values that are strictly increasing so the
        # chronological-order index is unambiguous to assert against.
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        timestamps = [
            (base + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            for i in range(1000)
        ]

        expected_by_person: dict[str, list[dict]] = {}
        expected_by_intent: dict[str, dict] = {}
        expected_by_gmail: dict[str, dict] = {}

        for i in range(1000):
            ts = timestamps[i]
            roll = rng.random()
            if roll < 0.4 or not intent_pool:
                # enrollment / pipeline event
                pid = rng.choice(person_pool)
                kind = rng.choice([
                    "enrolled", "research_complete", "draft_complete",
                    "review_approved",
                ])
                evt = {"type": kind, "person_id": pid, "ts": ts}
                expected_by_person.setdefault(pid, []).append(evt)
            elif roll < 0.65:
                # send_intent
                pid = rng.choice(person_pool)
                iid = f"snd_{i:04d}_{''.join(rng.choices(string.ascii_lowercase, k=4))}"
                channel = rng.choice(["email", "linkedin"])
                evt = {"type": "send_intent", "intent_id": iid,
                       "person_id": pid, "channel": channel, "ts": ts}
                expected_by_person.setdefault(pid, []).append(evt)
                expected_by_intent[iid] = evt
                intent_pool.append((iid, pid))
            else:
                # outcome on an existing intent
                iid, pid = rng.choice(intent_pool)
                kind = rng.choice([
                    "send_confirmed", "send_failed", "send_aborted",
                ])
                evt = {"type": kind, "intent_id": iid, "ts": ts}
                if kind == "send_confirmed":
                    gid = f"gmail_{i:04d}"
                    evt["gmail_message_id"] = gid
                    expected_by_gmail[gid] = evt
            led.append(evt)

        # Assert every person's events appear in the index
        for pid, expected_events in expected_by_person.items():
            indexed = [e.to_dict() for e in led.query_by_person(pid)]
            assert len(indexed) == len(expected_events), \
                f"person {pid}: expected {len(expected_events)}, got {len(indexed)}"

        # Assert every intent round-trips
        for iid, expected_intent in expected_by_intent.items():
            got = led.query_by_intent(iid)
            assert got is not None, f"intent {iid} missing"
            assert got["intent_id"] == iid

        # Assert every gmail msg round-trips
        for gid in expected_by_gmail:
            got = led.query_by_gmail_message_id(gid)
            assert got is not None, f"gmail msg {gid} missing"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestConcurrentAppend:
    def test_ten_workers_hundred_events_each(self, ledger_dir: Path):
        """Spawn 10 OS processes, each appending 100 events.

        Asserts:
          - All 1000 events present.
          - All 1000 intent_ids unique (no two writers stomped each other).
          - Every line is parseable (no torn writes).
        """
        # Use 'spawn' for cross-platform consistency. macOS default is
        # 'spawn' for Python 3.8+; this is explicit.
        ctx = mp.get_context("spawn")
        from tests._ledger_worker import write_n
        with ctx.Pool(processes=10) as pool:
            results = pool.map(
                write_n,
                [(str(ledger_dir), worker_id, 100) for worker_id in range(10)],
            )
        assert sum(results) == 1000

        # Re-read fresh — the in-memory cache was held in the parent
        # process and didn't see worker writes.
        led = Ledger(ledger_dir)
        led._build_indexes(force=True)
        assert len(led._all_events) == 1000

        # All intent_ids unique?
        ids = [e.get("intent_id") for e in led._all_events
               if e.get("type") == "send_intent"]
        assert len(ids) == 1000
        assert len(set(ids)) == 1000

        # No bad lines.
        hc = led.healthcheck()
        assert hc["bad_lines"] == 0
        assert hc["events_parsed"] == 1000


# ---------------------------------------------------------------------------
# Crash recovery — truncated tail
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    def test_truncated_last_line_skipped_with_warning(
        self, led: Ledger, ledger_dir: Path, capsys
    ):
        led.append({"type": "enrolled", "person_id": "p1"})
        led.append({"type": "enrolled", "person_id": "p2"})

        # Simulate a SIGKILL mid-write: append a partial JSON line with no
        # newline. (Real partial writes look exactly like this — the kernel
        # wrote some bytes before the process died.)
        current = ledger_dir / f"events-{ledger_mod._utc_date()}.jsonl"
        with current.open("a") as f:
            f.write('{"type":"enrolled","person_id":"p3","ts":"2026-')  # truncated

        led2 = Ledger(ledger_dir)
        events = led2.all_events()
        # Two good events recovered; the truncated one skipped.
        assert len(events) == 2
        captured = capsys.readouterr()
        assert "skipped" in captured.err.lower() or \
               "unparseable" in captured.err.lower()

    def test_garbage_line_in_middle_skipped(
        self, led: Ledger, ledger_dir: Path, capsys
    ):
        led.append({"type": "enrolled", "person_id": "p1"})
        current = ledger_dir / f"events-{ledger_mod._utc_date()}.jsonl"
        with current.open("a") as f:
            f.write("THIS IS NOT JSON\n")
        led.append({"type": "enrolled", "person_id": "p2"})

        led2 = Ledger(ledger_dir)
        events = led2.all_events()
        assert len(events) == 2

    def test_not_a_json_object_skipped(
        self, led: Ledger, ledger_dir: Path, capsys
    ):
        current = ledger_dir / f"events-{ledger_mod._utc_date()}.jsonl"
        with current.open("w") as f:
            f.write('"a bare string"\n')
            f.write('12345\n')
            f.write('{"type":"enrolled","person_id":"p1"}\n')
        led2 = Ledger(ledger_dir)
        events = led2.all_events()
        assert len(events) == 1
        assert events[0].person_id == "p1"


# ---------------------------------------------------------------------------
# Schema versioning — forward + backward compat
# ---------------------------------------------------------------------------


class TestSchemaVersioning:
    def test_v2_event_readable_by_v1_code(self, led: Ledger, ledger_dir: Path):
        current = ledger_dir / f"events-{ledger_mod._utc_date()}.jsonl"
        with current.open("w") as f:
            f.write(json.dumps({
                "v": 2,
                "ts": "2026-05-15T10:00:00.000Z",
                "type": "enrolled",
                "person_id": "p1",
                "v2_only_field": {"nested": "stuff"},
            }) + "\n")
        events = Ledger(ledger_dir).query_by_person("p1")
        assert len(events) == 1
        # The unknown field round-trips intact.
        assert events[0]["v2_only_field"] == {"nested": "stuff"}

    def test_missing_v_field_defaults(self, led: Ledger, ledger_dir: Path):
        # Old logs from before schema versioning rolled out.
        current = ledger_dir / f"events-{ledger_mod._utc_date()}.jsonl"
        with current.open("w") as f:
            f.write(json.dumps({
                "ts": "2026-01-01T00:00:00.000Z",
                "type": "enrolled",
                "person_id": "p_legacy",
            }) + "\n")
        events = Ledger(ledger_dir).query_by_person("p_legacy")
        assert len(events) == 1
        assert events[0].v == ledger_mod.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Daily rotation
# ---------------------------------------------------------------------------


class TestDailyRotation:
    def test_writes_across_utc_midnight_split_into_two_files(
        self, ledger_dir: Path,
    ):
        led = Ledger(ledger_dir)

        # Day 1
        with mock.patch.object(ledger_mod, "_utc_date",
                               return_value="2026-05-14"):
            with mock.patch.object(ledger_mod, "_now_iso",
                                   return_value="2026-05-14T23:59:59.000Z"):
                led.append({"type": "enrolled", "person_id": "p_day1"})

        # Day 2
        with mock.patch.object(ledger_mod, "_utc_date",
                               return_value="2026-05-15"):
            with mock.patch.object(ledger_mod, "_now_iso",
                                   return_value="2026-05-15T00:00:00.000Z"):
                led.append({"type": "enrolled", "person_id": "p_day2"})

        files = sorted(ledger_dir.glob("events-*.jsonl"))
        assert [f.name for f in files] == [
            "events-2026-05-14.jsonl",
            "events-2026-05-15.jsonl",
        ]
        # Each file has exactly one line.
        for f in files:
            assert sum(1 for line in f.read_text().splitlines()
                       if line.strip()) == 1

    def test_symlink_repoints_at_new_day(self, ledger_dir: Path):
        led = Ledger(ledger_dir)
        with mock.patch.object(ledger_mod, "_utc_date",
                               return_value="2026-05-14"):
            led.append({"type": "enrolled", "person_id": "p1"})
        symlink = ledger_dir / "events.jsonl"
        import os as _os
        assert _os.readlink(symlink) == "events-2026-05-14.jsonl"

        with mock.patch.object(ledger_mod, "_utc_date",
                               return_value="2026-05-15"):
            led.append({"type": "enrolled", "person_id": "p2"})
        assert _os.readlink(symlink) == "events-2026-05-15.jsonl"


# ---------------------------------------------------------------------------
# Healthcheck + funnel
# ---------------------------------------------------------------------------


class TestHealthcheck:
    def test_healthcheck_clean(self, led: Ledger):
        led.append({"type": "enrolled", "person_id": "p1"})
        h = led.healthcheck()
        assert h["ok"] is True
        assert h["bad_lines"] == 0
        assert h["events_parsed"] == 1

    def test_healthcheck_surfaces_old_open_intents(
        self, led: Ledger, ledger_dir: Path,
    ):
        # An intent from 30 days ago with no outcome — that's a smoke
        # signal the user should investigate.
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)) \
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        led.append({
            "type": "send_intent", "intent_id": "snd_old",
            "person_id": "p1", "channel": "email", "ts": old_ts,
        })
        h = led.healthcheck()
        assert "snd_old" in h["open_intents_over_24h"]


class TestFunnel:
    def test_funnel_counts_distinct_persons_per_stage(
        self, led: Ledger,
    ):
        led.append({"type": "enrolled", "person_id": "p1"})
        led.append({"type": "enrolled", "person_id": "p2"})
        led.append({"type": "research_complete", "person_id": "p1"})
        led.append({"type": "draft_complete", "person_id": "p1"})
        led.append({"type": "send_intent", "intent_id": "snd_x",
                    "person_id": "p1", "channel": "email"})
        led.append({"type": "send_confirmed", "intent_id": "snd_x"})

        result = funnel(led, since=datetime.now(timezone.utc)
                        - timedelta(days=1))
        stages = result["persons_reached_stage"]
        assert stages["queued"] == 2     # p1 + p2
        assert stages["researched"] == 1 # p1
        assert stages["drafted"] == 1
        assert stages["sent"] == 1

    def test_funnel_window_excludes_old_events(self, led: Ledger):
        old = "2026-01-01T00:00:00.000Z"
        recent_ts = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")
        led.append({"type": "enrolled", "person_id": "p_old", "ts": old})
        led.append({"type": "enrolled", "person_id": "p_recent",
                    "ts": recent_ts})
        result = funnel(led, since=datetime.now(timezone.utc)
                        - timedelta(hours=1))
        # Only the recent enrollment counts.
        assert result["persons_reached_stage"]["queued"] == 1


# ---------------------------------------------------------------------------
# Intent id generation
# ---------------------------------------------------------------------------


class TestIntentId:
    def test_prefix_and_length(self):
        iid = new_intent_id()
        assert iid.startswith("snd_")
        assert len(iid) == 4 + 26  # "snd_" + 26 char ulid body

    def test_uniqueness(self):
        ids = {new_intent_id() for _ in range(1000)}
        assert len(ids) == 1000
