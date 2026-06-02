"""State-file shape + atomicity + lock-contention tests.

Covers ``orchestrator.migrations.state`` directly. The runner's
state-file behavior is exercised in ``tests/test_migrations_runner.py``
on top of these primitives.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.migrations.state import (
    STATE_SCHEMA_VERSION,
    MigrationState,
    acquire_state_lock,
    is_applied,
    load_state,
    lock_file_path,
    mark_applied,
    mark_unapplied,
    save_state_atomic,
    state_file_path,
)
from orchestrator.migrations.types import MigrationCategory


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Isolated state directory per test."""
    d = tmp_path / "outreach-factory"
    d.mkdir()
    return d


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


class TestMigrationStateShape:
    def test_default_is_empty_per_category(self):
        s = MigrationState()
        for cat in MigrationCategory:
            assert s.applied[cat.value] == []
        assert s.schema_version == STATE_SCHEMA_VERSION
        assert s.last_applied_at is None
        assert s.last_runner_version is None

    def test_to_dict_round_trips(self):
        s = MigrationState()
        mark_applied(
            s, MigrationCategory.LEDGER, "0001_a",
            now=_now(), runner_version="0.1.0",
        )
        d = s.to_dict()
        s2 = MigrationState.from_dict(d)
        assert s2.applied == s.applied
        assert s2.schema_version == s.schema_version
        assert s2.last_applied_at == s.last_applied_at
        assert s2.last_runner_version == s.last_runner_version

    def test_from_dict_discards_unknown_categories(self):
        """Forward-compat: a future runner might add a new category;
        an older runner should ignore it rather than choke."""
        d = {
            "schema_version": 1,
            "applied": {
                "ledger": ["0001_a"],
                "vault": [],
                "policy": [],
                "future_category": ["0001_x"],
            },
        }
        s = MigrationState.from_dict(d)
        assert "future_category" not in s.applied
        assert s.applied["ledger"] == ["0001_a"]

    def test_from_dict_tolerates_missing_applied(self):
        s = MigrationState.from_dict({"schema_version": 1})
        for cat in MigrationCategory:
            assert s.applied[cat.value] == []

    def test_from_dict_drops_non_list_applied_values(self):
        """Defensive: a corrupt or hand-edited state file with an
        applied[cat] value that isn't a list shouldn't crash the load
        — the entry is silently dropped + replaced with the empty list
        via ``__post_init__``."""
        d = {
            "schema_version": 1,
            "applied": {
                "ledger": ["0001_a"],
                "vault": "not a list",  # corrupt
            },
        }
        s = MigrationState.from_dict(d)
        assert s.applied["ledger"] == ["0001_a"]
        assert s.applied["vault"] == []

    def test_schema_version_coerced_to_int(self):
        """JSON could theoretically carry the version as a string."""
        d = {"schema_version": "1", "applied": {}}
        s = MigrationState.from_dict(d)
        assert s.schema_version == 1
        assert isinstance(s.schema_version, int)


# ---------------------------------------------------------------------------
# load_state / save_state_atomic
# ---------------------------------------------------------------------------


class TestLoadSaveRoundTrip:
    def test_missing_file_returns_empty(self, state_dir: Path):
        s = load_state(state_dir)
        for cat in MigrationCategory:
            assert s.applied[cat.value] == []

    def test_write_then_read(self, state_dir: Path):
        s = MigrationState()
        mark_applied(
            s, MigrationCategory.VAULT, "0001_foo",
            now=_now(), runner_version="test",
        )
        save_state_atomic(state_dir, s)
        s2 = load_state(state_dir)
        assert s2.applied["vault"] == ["0001_foo"]
        assert s2.last_runner_version == "test"

    def test_save_creates_parent_dir(self, tmp_path: Path):
        d = tmp_path / "nonexistent" / "child"
        save_state_atomic(d, MigrationState())
        assert state_file_path(d).exists()

    def test_corrupt_json_raises(self, state_dir: Path):
        state_file_path(state_dir).write_text("not json {")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_state(state_dir)

    def test_non_object_json_raises(self, state_dir: Path):
        state_file_path(state_dir).write_text('["array", "not", "object"]')
        with pytest.raises(ValueError, match="must be a JSON object"):
            load_state(state_dir)

    def test_future_schema_version_logs_warning_not_error(
        self, state_dir: Path, caplog: pytest.LogCaptureFixture,
    ):
        """A state file with schema_version > STATE_SCHEMA_VERSION
        was written by a newer runner. The current runner proceeds
        (forward-compat grace) but logs a WARNING so the operator
        knows they're reading state from a newer runner. This is the
        framework's own I3 invariant applied to itself — schema
        version mismatches surface, never silent."""
        import json as _json
        import logging as _logging
        p = state_file_path(state_dir)
        p.write_text(_json.dumps({"schema_version": 999, "applied": {}}))
        with caplog.at_level(
            _logging.WARNING, logger="orchestrator.migrations.state",
        ):
            s = load_state(state_dir)
        assert s.schema_version == 999
        assert "schema_version=999" in caplog.text
        assert f"schema_version={STATE_SCHEMA_VERSION}" in caplog.text

    def test_current_schema_version_does_not_warn(
        self, state_dir: Path, caplog: pytest.LogCaptureFixture,
    ):
        """A state file at the current schema version does NOT log a
        warning. Only future-schema_version triggers the warning."""
        import json as _json
        import logging as _logging
        p = state_file_path(state_dir)
        p.write_text(_json.dumps({
            "schema_version": STATE_SCHEMA_VERSION,
            "applied": {},
        }))
        with caplog.at_level(
            _logging.WARNING, logger="orchestrator.migrations.state",
        ):
            load_state(state_dir)
        assert "schema_version=" not in caplog.text

    def test_save_writes_via_tmp_then_rename(self, state_dir: Path):
        """The ``.tmp`` file does NOT exist after a successful save.

        If save left the tmp file around, the next save would race on
        the fixed tmp path. This pins the post-rename cleanup."""
        save_state_atomic(state_dir, MigrationState())
        target = state_file_path(state_dir)
        tmp = target.with_suffix(target.suffix + ".tmp")
        assert target.exists()
        assert not tmp.exists()

    def test_save_overwrites_existing(self, state_dir: Path):
        s = MigrationState()
        mark_applied(
            s, MigrationCategory.LEDGER, "0001_a",
            now=_now(), runner_version="v1",
        )
        save_state_atomic(state_dir, s)

        s2 = load_state(state_dir)
        mark_applied(
            s2, MigrationCategory.LEDGER, "0002_b",
            now=_now(), runner_version="v2",
        )
        save_state_atomic(state_dir, s2)

        s3 = load_state(state_dir)
        assert s3.applied["ledger"] == ["0001_a", "0002_b"]
        assert s3.last_runner_version == "v2"

    def test_save_produces_valid_json(self, state_dir: Path):
        """Sanity: the on-disk format is human-readable JSON, not
        Python-repr or some other accidental format."""
        s = MigrationState()
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        save_state_atomic(state_dir, s)
        raw = state_file_path(state_dir).read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["applied"]["vault"] == ["0001_a"]
        # Pretty-printed (sorted keys, indented).
        assert "\n" in raw

    def test_save_is_deterministic_for_same_state(self, state_dir: Path):
        """Same in-memory state should produce byte-identical files.
        Useful for human diffs + reproducibility under tests."""
        s = MigrationState()
        mark_applied(
            s, MigrationCategory.VAULT, "0001_a",
            now=datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc),
            runner_version="0.1.0",
        )
        save_state_atomic(state_dir, s)
        first = state_file_path(state_dir).read_bytes()

        # Re-write same state.
        save_state_atomic(state_dir, s)
        second = state_file_path(state_dir).read_bytes()
        assert first == second


# ---------------------------------------------------------------------------
# Atomicity — write-temp-then-rename survives a simulated mid-write crash
# ---------------------------------------------------------------------------


class TestAtomicWriteUnderCrash:
    def test_partial_write_does_not_overwrite_target(
        self, state_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """If save_state_atomic crashes AFTER writing tmp but BEFORE
        os.replace, the target file should be untouched. This is the
        exact failure mode the tmp-then-rename pattern exists to
        prevent — a partial write should never be observable through
        ``load_state``."""
        good = MigrationState()
        mark_applied(
            good, MigrationCategory.VAULT, "0001_good",
            now=_now(), runner_version="good",
        )
        save_state_atomic(state_dir, good)

        target = state_file_path(state_dir)
        tmp = target.with_suffix(target.suffix + ".tmp")
        original_replace = os.replace

        def crashing_replace(src, dst):
            assert Path(src).exists()  # tmp must have been written
            raise OSError("simulated crash before rename")

        monkeypatch.setattr(os, "replace", crashing_replace)
        bad = MigrationState()
        mark_applied(
            bad, MigrationCategory.VAULT, "0002_partial",
            now=_now(), runner_version="bad",
        )
        with pytest.raises(OSError, match="simulated crash"):
            save_state_atomic(state_dir, bad)

        # tmp exists but target is untouched.
        assert tmp.exists()
        monkeypatch.setattr(os, "replace", original_replace)

        # Reading state still gives us the good pre-crash state.
        recovered = load_state(state_dir)
        assert recovered.applied["vault"] == ["0001_good"]
        assert recovered.last_runner_version == "good"

    def test_tmp_leftover_does_not_corrupt_next_save(
        self, state_dir: Path,
    ):
        """If a previous crash left a stale tmp file behind, the next
        save_state_atomic must overwrite it cleanly — not append or
        fail. We use O_TRUNC explicitly to handle this case."""
        target = state_file_path(state_dir)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("garbage from a prior crash", encoding="utf-8")

        s = MigrationState()
        mark_applied(s, MigrationCategory.LEDGER, "0001_clean", now=_now())
        save_state_atomic(state_dir, s)

        recovered = load_state(state_dir)
        assert recovered.applied["ledger"] == ["0001_clean"]
        # tmp cleaned up by the rename.
        assert not tmp.exists()


# ---------------------------------------------------------------------------
# mark_applied / mark_unapplied / is_applied
# ---------------------------------------------------------------------------


class TestMarkApplied:
    def test_appends_to_category_list(self):
        s = MigrationState()
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        assert s.applied["vault"] == ["0001_a"]
        mark_applied(s, MigrationCategory.VAULT, "0002_b", now=_now())
        assert s.applied["vault"] == ["0001_a", "0002_b"]

    def test_idempotent_when_already_applied(self):
        s = MigrationState()
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        assert s.applied["vault"] == ["0001_a"]

    def test_updates_last_applied_at(self):
        s = MigrationState()
        ts = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=ts)
        assert s.last_applied_at == ts.isoformat()

    def test_naive_datetime_raises(self):
        s = MigrationState()
        naive = datetime(2026, 5, 19, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            mark_applied(s, MigrationCategory.VAULT, "0001_a", now=naive)

    def test_records_runner_version(self):
        s = MigrationState()
        mark_applied(
            s, MigrationCategory.VAULT, "0001_a",
            now=_now(), runner_version="0.1.0",
        )
        assert s.last_runner_version == "0.1.0"

    def test_categories_are_independent(self):
        s = MigrationState()
        mark_applied(s, MigrationCategory.LEDGER, "0001_a", now=_now())
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        assert s.applied["ledger"] == ["0001_a"]
        assert s.applied["vault"] == ["0001_a"]
        # Same id under different categories does not cross-contaminate.
        assert s.applied["policy"] == []


class TestIsApplied:
    def test_returns_true_after_mark(self):
        s = MigrationState()
        mark_applied(s, MigrationCategory.LEDGER, "0001_a", now=_now())
        assert is_applied(s, MigrationCategory.LEDGER, "0001_a")

    def test_returns_false_for_other_category(self):
        s = MigrationState()
        mark_applied(s, MigrationCategory.LEDGER, "0001_a", now=_now())
        assert not is_applied(s, MigrationCategory.VAULT, "0001_a")

    def test_returns_false_for_unknown_id(self):
        s = MigrationState()
        assert not is_applied(s, MigrationCategory.VAULT, "0001_nope")


class TestMarkUnapplied:
    def test_removes_from_category_list(self):
        s = MigrationState()
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        mark_unapplied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        assert s.applied["vault"] == []

    def test_idempotent_when_not_present(self):
        s = MigrationState()
        mark_unapplied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        assert s.applied["vault"] == []

    def test_naive_datetime_raises(self):
        s = MigrationState()
        naive = datetime(2026, 5, 19, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            mark_unapplied(s, MigrationCategory.VAULT, "0001_a", now=naive)

    def test_preserves_other_ids_in_category(self):
        s = MigrationState()
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=_now())
        mark_applied(s, MigrationCategory.VAULT, "0002_b", now=_now())
        mark_applied(s, MigrationCategory.VAULT, "0003_c", now=_now())
        mark_unapplied(s, MigrationCategory.VAULT, "0002_b", now=_now())
        assert s.applied["vault"] == ["0001_a", "0003_c"]

    def test_mark_unapplied_updates_last_applied_at(self):
        """mark_unapplied updates last_applied_at — the field tracks
        "last framework activity," not "last forward-apply." This pins
        the documented behavior so future refactors don't drop it."""
        s = MigrationState()
        t1 = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        mark_applied(s, MigrationCategory.VAULT, "0001_a", now=t1)
        assert s.last_applied_at == t1.isoformat()
        t2 = datetime(2026, 5, 19, 13, 0, 0, tzinfo=timezone.utc)
        mark_unapplied(s, MigrationCategory.VAULT, "0001_a", now=t2)
        # last_applied_at reflects the most recent state change,
        # whether that was an apply or a rollback.
        assert s.last_applied_at == t2.isoformat()


# ---------------------------------------------------------------------------
# Lock contention — cross-process serialization
# ---------------------------------------------------------------------------


# Worker function MUST be module-level for multiprocessing spawn to be
# able to pickle it. See ``TestLockContention.test_concurrent_writers``.
def _lock_worker(
    state_dir_str: str,
    sentinel_file_str: str,
    hold_secs: float,
) -> None:
    """Acquire the state lock, write a marker, hold, release."""
    state_dir = Path(state_dir_str)
    sentinel = Path(sentinel_file_str)
    with acquire_state_lock(state_dir):
        sentinel.write_text(str(time.time()), encoding="utf-8")
        time.sleep(hold_secs)


class TestLockContention:
    def test_concurrent_writers_serialize(
        self, state_dir: Path, tmp_path: Path,
    ):
        """Two processes acquiring the lock must NOT overlap.

        Each writes a sentinel timestamp at the moment of acquire.
        If serialization works, the second timestamp must be at least
        ``hold_secs`` after the first (the second was waiting on the
        first to finish)."""
        sentinel_a = tmp_path / "a.marker"
        sentinel_b = tmp_path / "b.marker"
        hold = 0.3

        ctx = multiprocessing.get_context("spawn")
        p_a = ctx.Process(
            target=_lock_worker,
            args=(str(state_dir), str(sentinel_a), hold),
        )
        p_b = ctx.Process(
            target=_lock_worker,
            args=(str(state_dir), str(sentinel_b), hold),
        )

        p_a.start()
        # Small head-start so A definitely takes the lock first.
        time.sleep(0.05)
        p_b.start()

        p_a.join(timeout=10)
        p_b.join(timeout=10)
        assert p_a.exitcode == 0
        assert p_b.exitcode == 0

        t_a = float(sentinel_a.read_text())
        t_b = float(sentinel_b.read_text())
        # B must have acquired the lock at least 90% of `hold` seconds
        # after A (small slack for scheduler jitter).
        assert (t_b - t_a) >= hold * 0.9, (
            f"second writer acquired lock at {t_b - t_a:.3f}s after "
            f"first; expected at least {hold * 0.9:.3f}s — lock did "
            f"not serialize."
        )

    def test_lock_is_released_on_exception(self, state_dir: Path):
        """An exception inside the context must release the lock."""
        with pytest.raises(RuntimeError, match="inner"):
            with acquire_state_lock(state_dir):
                raise RuntimeError("inner")

        # Should re-acquire immediately without blocking.
        # (Process-internal — POSIX advisory locks per-process don't
        # block re-entry from the same process, but the test still
        # verifies the context manager doesn't leak file descriptors.)
        with acquire_state_lock(state_dir):
            pass

    def test_lock_file_is_created_in_state_dir(self, state_dir: Path):
        """The lock file lives beside the state file under state_dir."""
        with acquire_state_lock(state_dir):
            assert lock_file_path(state_dir).exists()
        # Lock file is intentionally NOT deleted on release — keeping
        # it avoids a TOCTOU race on lock-file create + lock between
        # processes (same convention as ledger.py).
        assert lock_file_path(state_dir).exists()


# ---------------------------------------------------------------------------
# Pillar B Week 6 parallel-review P1 fixes
# (see .planning/REVIEW-pillar-b-boil-the-ocean.md §P1-1, §P1-2)
# ---------------------------------------------------------------------------


class TestLoadStateAdversarialShapes:
    """Pillar B Week 6 second follow-up — pins the operator-readable
    failure mode for hand-edited / corrupted state files. The contract:
    a JSON-valid but shape-wrong state file (``"applied": "not a dict"``
    or ``"applied": []``) MUST surface as a WARNING + treat-as-empty
    behavior, NEVER a bare ``AttributeError`` from calling ``.items()``
    on a non-mapping.

    This is the conservative posture per the asymmetric-failure-cost
    calculus: treating wrong-typed ``applied`` as empty-applied lets
    the framework continue running (operator re-runs all migrations,
    each of which is idempotent via per-migration checks); raising
    ValueError would block the entire framework until manual repair,
    which is the wrong posture for a state file the operator may have
    just restored from backup.
    """

    def test_applied_as_string_warns_and_treats_as_empty(
        self, state_dir: Path, caplog: pytest.LogCaptureFixture,
    ):
        """`"applied": "not a dict"` is a plausible hand-edit shape.

        Pre-fix: ``MigrationState.from_dict`` would call ``.items()``
        on the string + crash with ``AttributeError``. Post-fix:
        treats as empty-applied + WARNs."""
        import logging as _logging
        sf = state_file_path(state_dir)
        sf.write_text(
            json.dumps({"schema_version": 1, "applied": "not a dict"}),
            encoding="utf-8",
        )
        with caplog.at_level(
            _logging.WARNING, logger="orchestrator.migrations.state",
        ):
            s = load_state(state_dir)
        for cat in MigrationCategory:
            assert s.applied[cat.value] == []
        # Operator-visible WARNING surfaces the actual on-disk type so
        # they can investigate.
        assert "str" in caplog.text

    def test_applied_as_list_warns_and_treats_as_empty(
        self, state_dir: Path, caplog: pytest.LogCaptureFixture,
    ):
        """`"applied": ["ledger"]` is another plausible hand-edit shape
        (operator confused a list-of-applied with a dict-of-category-
        applied-lists)."""
        import logging as _logging
        sf = state_file_path(state_dir)
        sf.write_text(
            json.dumps({"schema_version": 1, "applied": ["ledger"]}),
            encoding="utf-8",
        )
        with caplog.at_level(
            _logging.WARNING, logger="orchestrator.migrations.state",
        ):
            s = load_state(state_dir)
        for cat in MigrationCategory:
            assert s.applied[cat.value] == []
        assert "list" in caplog.text

    def test_applied_as_int_warns_and_treats_as_empty(
        self, state_dir: Path, caplog: pytest.LogCaptureFixture,
    ):
        """JSON-decoded number where a dict was expected (the
        pathological end of the spectrum)."""
        import logging as _logging
        sf = state_file_path(state_dir)
        sf.write_text(
            json.dumps({"schema_version": 1, "applied": 42}),
            encoding="utf-8",
        )
        with caplog.at_level(
            _logging.WARNING, logger="orchestrator.migrations.state",
        ):
            s = load_state(state_dir)
        for cat in MigrationCategory:
            assert s.applied[cat.value] == []

    def test_applied_dict_still_works_after_guard(
        self, state_dir: Path,
    ):
        """The guard MUST NOT regress the happy path: a valid
        ``applied`` dict still loads as expected."""
        sf = state_file_path(state_dir)
        sf.write_text(
            json.dumps({
                "schema_version": 1,
                "applied": {
                    "vault": ["0001_a"],
                    "ledger": [],
                    "policy": [],
                },
            }),
            encoding="utf-8",
        )
        s = load_state(state_dir)
        assert s.applied["vault"] == ["0001_a"]
        assert s.applied["ledger"] == []
        assert s.applied["policy"] == []


class TestLockFileDeletionRobustness:
    """Pillar B Week 6 second follow-up — pins the inode-recheck
    behavior of ``acquire_state_lock``. POSIX advisory locks attach
    to the ``(process, inode)`` pair, not the path; if the lock file
    is deleted while held + recreated by another process, both
    processes would believe they hold the exclusive lock (defeating
    cross-process serialization).

    The fix: re-stat the path after ``fcntl.lockf`` succeeds; if
    the fd's inode != path's inode, release + retry up to
    ``_LOCK_MAX_RETRIES`` (10) times. Persistent mismatch raises
    ``RuntimeError`` so a rogue cleanup script (e.g. ``find ... -name
    "*.lock" -delete``) in the operator's environment surfaces loud
    rather than producing silent state-file double-writes.
    """

    def test_inode_mismatch_triggers_retry_until_stable(
        self, state_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Pin the retry path directly: monkeypatch ``os.stat`` to
        return a fake inode on the first call (forcing mismatch with
        ``os.fstat``), then the real inode on the second call.
        ``acquire_state_lock`` must release + retry + succeed on the
        second attempt.

        We can't reliably race a real concurrent unlinker against the
        sub-microsecond gap between ``fcntl.lockf`` and the verify
        ``os.stat`` — a threaded simulation would be flaky. Direct
        path exercise via monkeypatch is the deterministic shape."""
        import os as _os
        real_stat = _os.stat
        call_count = {"n": 0}

        def flaky_stat(path, *args, **kwargs):
            # Only intercept stats against the lock file path; pass
            # through everything else (the mkdir helper stats other
            # paths during setup).
            if str(path) == str(lock_file_path(state_dir)):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # First call returns a stat with a fake inode that
                    # won't match the fd's real inode → triggers retry.
                    real = real_stat(path, *args, **kwargs)
                    # Build a synthetic stat result with st_ino = 0
                    # (a never-real inode value on macOS / Linux).
                    fields = list(real)
                    fields[1] = 0  # st_ino is index 1 in os.stat_result
                    import os as _os2
                    return _os2.stat_result(fields)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(_os, "stat", flaky_stat)

        # Should succeed on the second attempt (mismatch on first,
        # real-stat match on second).
        with acquire_state_lock(state_dir):
            pass
        assert call_count["n"] >= 2, (
            f"expected at least 2 inode-verify stat calls (one mismatch + "
            f"one match); got {call_count['n']}. The retry loop wasn't "
            f"exercised."
        )

    def test_persistent_inode_mismatch_raises_after_max_retries(
        self, state_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """If ``os.stat`` keeps returning a mismatched inode forever
        (the operator's cleanup script is actively + repeatedly
        deleting the lock file), the retry loop hits the cap and
        raises ``RuntimeError`` with an actionable message naming the
        likely cause."""
        import os as _os
        real_stat = _os.stat

        def always_mismatch_stat(path, *args, **kwargs):
            if str(path) == str(lock_file_path(state_dir)):
                real = real_stat(path, *args, **kwargs)
                fields = list(real)
                fields[1] = 0  # always wrong inode
                import os as _os2
                return _os2.stat_result(fields)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(_os, "stat", always_mismatch_stat)

        with pytest.raises(RuntimeError, match="repeatedly deleted"):
            with acquire_state_lock(state_dir):
                pass  # pragma: no cover (never reached)

    def test_lock_succeeds_on_happy_path_with_no_deletion(
        self, state_dir: Path,
    ):
        """The retry loop MUST NOT regress the happy path: no
        deletion, lock acquires on the first attempt, releases
        cleanly."""
        with acquire_state_lock(state_dir):
            assert lock_file_path(state_dir).exists()
        # File persists after release per convention.
        assert lock_file_path(state_dir).exists()
