"""Pillar B migration framework — state file management.

The applies-once SoT for migration runs. JSON file at
``~/.outreach-factory/migrations.state.json``. Single-writer with an
advisory file lock at ``migrations.state.json.lock``; atomic writes via
tmp-then-rename (the same pattern ``orchestrator.policy.suppression.
forget_append`` uses for the GDPR-forget atomic add, per ADR-0004).

Schema (D3 + ADR-0009 §Decision item "State file shape")::

    {
      "schema_version": 1,
      "applied": {
        "ledger": ["0001_baseline", ...],
        "vault":  ["0001_add_schema_version", ...],
        "policy": []
      },
      "last_applied_at": "2026-05-20T12:34:56.789Z",
      "last_runner_version": "0.1.0"
    }

* ``schema_version`` — the STATE FILE's schema. Future bumps would be
  migrations on the state file itself, lived outside this framework
  (an external launcher would migrate before invoking the runner).
* ``applied`` — per-category list of applied migration ids, in apply
  order. Used by ``is_applied`` to filter pending migrations.
* ``last_applied_at`` / ``last_runner_version`` — diagnostic only.
  Operators use these to answer "when was the last migration?" and
  "which runner version wrote this state?".
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .types import MigrationCategory


_LOGGER_NAME = "orchestrator.migrations.state"


# Bumped when the on-disk schema of `migrations.state.json` itself
# changes. The runner stamps every write with the current version.
# A future runner reading an older-versioned state file would consult
# a (yet-to-be-written) inline upgrade path — that path lives outside
# this module because the framework can't run a migration that would
# upgrade its own state-file schema.
STATE_SCHEMA_VERSION = 1

DEFAULT_STATE_DIR = Path.home() / ".outreach-factory"
STATE_FILENAME = "migrations.state.json"
STATE_LOCK_FILENAME = "migrations.state.json.lock"


@dataclass
class MigrationState:
    """In-memory representation of ``migrations.state.json``.

    Mutable by design: ``mark_applied`` / ``mark_unapplied`` mutate
    the ``applied`` dict + ``last_*`` fields. The runner is responsible
    for ``save_state_atomic`` after every mutation — this dataclass
    does not auto-persist.

    Fields
    ------
    schema_version:
        The state-file format version. Bumping requires a coordinated
        upgrade path outside this framework (the framework can't run
        a migration that would upgrade its own state-file schema). See
        ADR-0009 §Migration / rollout. ``load_state`` emits a WARNING
        log when the on-disk version exceeds ``STATE_SCHEMA_VERSION``
        — that signals the operator downgraded their runner; behavior
        is "proceed with unknown fields dropped" but the warning is
        load-bearing for operator awareness.
    applied:
        ``{category_value: [migration_id, ...]}``. Lists are in apply
        order; the runner appends after each successful ``upgrade``.
        Per-category list keeps the namespaces clean per D2 (the
        per-category numeric ID convention).
    last_applied_at:
        ISO-8601 timestamp of the most recent framework activity (any
        category). Updated by BOTH ``mark_applied`` AND ``mark_unapplied``
        — the field name is a historical accident; semantically it is
        "last activity at." Diagnostic-only; the runner doesn't load-
        bear on this for the applies-once check (that's purely the
        ``applied`` list). Renaming to ``last_activity_at`` would
        require a state-file schema bump, which the framework can't
        self-apply — deferred indefinitely; documented here so
        operators reading rollback-touched state files aren't
        misled.
    last_runner_version:
        Version string of the runner that wrote the file. Diagnostic-
        only — operators use this to detect "the last writer was a
        newer runner than me; consult the changelog before applying."
    """

    schema_version: int = STATE_SCHEMA_VERSION
    applied: dict[str, list[str]] = field(default_factory=dict)
    last_applied_at: str | None = None
    last_runner_version: str | None = None

    def __post_init__(self) -> None:
        # Ensure every category has an entry — simplifies downstream code
        # (no `.get(cat, [])` everywhere). Adding new MigrationCategory
        # enum members automatically gets a fresh empty list here.
        for cat in MigrationCategory:
            self.applied.setdefault(cat.value, [])

    def to_dict(self) -> dict:
        """JSON-ready snapshot. Sorted for stable on-disk diffs."""
        return {
            "schema_version": self.schema_version,
            "applied": {k: list(v) for k, v in self.applied.items()},
            "last_applied_at": self.last_applied_at,
            "last_runner_version": self.last_runner_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MigrationState":
        """Parse an on-disk dict. Tolerant of forward-compat extras.

        Forward-compat rules:

        * Unknown keys at the top level are dropped silently.
        * Unknown category names in ``applied`` are dropped silently
          (a future runner might add ``inbox`` as a fourth category;
          an older runner reading that state file should ignore the
          unknown category, not choke).

        Strict rules:

        * The ``schema_version`` is coerced to ``int`` (the JSON might
          carry a string in pathological cases).
        * ``applied`` values that aren't lists are dropped.
        * ``applied`` itself that isn't a dict (operator hand-edit
          to ``"applied": "not a dict"``, ``"applied": []``, etc.) is
          treated as empty-applied with a WARNING — never an
          ``AttributeError`` from calling ``.items()`` on a non-mapping.
          The conservative default (treat as empty-applied) lets the
          framework continue running; the operator re-runs all
          migrations, which is idempotent. The alternative (raise
          ValueError) would block the framework entirely until
          manual repair, which is the wrong asymmetric-failure-cost
          posture for a state file the operator might have already
          recovered from backup. Pillar B Week 6 parallel-review P1
          fix (`.planning/REVIEW-pillar-b-boil-the-ocean.md` §P1-1).
        """
        raw_applied = d.get("applied")
        if raw_applied is None or raw_applied == {}:
            applied: dict = {}
        elif not isinstance(raw_applied, dict):
            logging.getLogger(_LOGGER_NAME).warning(
                "migration state file's `applied` field has type %s "
                "(expected dict); treating as empty-applied so the "
                "framework can continue. All migrations will be "
                "re-evaluated and skipped via per-migration "
                "idempotence checks if their effects are already "
                "on disk. If migrations have actually been applied, "
                "restore the state file from backup before re-running.",
                type(raw_applied).__name__,
            )
            applied = {}
        else:
            applied = raw_applied
        known = {cat.value for cat in MigrationCategory}
        clean_applied = {
            k: list(v) for k, v in applied.items()
            if k in known and isinstance(v, list)
        }
        return cls(
            schema_version=int(d.get("schema_version", STATE_SCHEMA_VERSION)),
            applied=clean_applied,
            last_applied_at=d.get("last_applied_at"),
            last_runner_version=d.get("last_runner_version"),
        )


def state_file_path(state_dir: Path) -> Path:
    """The on-disk location of ``migrations.state.json`` under a state dir."""
    return Path(state_dir) / STATE_FILENAME


def lock_file_path(state_dir: Path) -> Path:
    """The on-disk location of the advisory lock file."""
    return Path(state_dir) / STATE_LOCK_FILENAME


def load_state(state_dir: Path) -> MigrationState:
    """Read the state file. Returns a fresh empty state if the file is missing.

    A missing file is the greenfield install — no migrations have been
    applied yet, so empty-applied is the correct interpretation. A
    corrupt or shape-wrong file raises ``ValueError`` (the operator must
    fix it; we don't paper over corruption by silently overwriting).

    Future-schema-version awareness: if the on-disk state file declares
    ``schema_version`` greater than the runner's :data:`STATE_SCHEMA_VERSION`,
    a WARNING is logged. The runner proceeds (forward-compat grace —
    unknown fields are dropped by :meth:`MigrationState.from_dict`) but
    the operator is alerted that they're reading state written by a
    newer runner. This is the framework's own I3 invariant applied to
    itself.

    Raises
    ------
    ValueError:
        On unparseable JSON or non-object top-level. The error message
        includes the file path so the operator can investigate.
    """
    p = state_file_path(state_dir)
    if not p.exists():
        return MigrationState()
    text = p.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"migration state file {p} is not valid JSON: {exc}. "
            f"Manual repair required (or restore from backup); the "
            f"runner refuses to overwrite a corrupt state file.",
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"migration state file {p} must be a JSON object, "
            f"got {type(data).__name__}",
        )
    state = MigrationState.from_dict(data)
    if state.schema_version > STATE_SCHEMA_VERSION:
        logging.getLogger(_LOGGER_NAME).warning(
            "migration state file %s carries schema_version=%d but this "
            "runner only knows schema_version=%d. The file was written "
            "by a newer runner. Proceeding — unknown fields are dropped. "
            "Upgrade the runner before applying new migrations to avoid "
            "writing back state in an older format.",
            p, state.schema_version, STATE_SCHEMA_VERSION,
        )
    return state


def save_state_atomic(state_dir: Path, state: MigrationState) -> Path:
    """Write the state file atomically via tmp-then-rename.

    The caller is responsible for holding the state lock via
    ``acquire_state_lock`` — concurrent writers would race on the
    fixed tmp path otherwise. The runner holds the lock for the
    entire apply/rollback cycle, so individual ``save_state_atomic``
    calls inside a cycle are always lock-protected.

    Atomicity is two-layered:

    * **Tmp write + fsync** — the tmp file is written and fsync'd
      before ``os.replace`` is called. So even a crash between write
      and rename leaves a fully-formed tmp file (recoverable) and an
      untouched target.
    * **os.replace** — on POSIX this is atomic when source and target
      are on the same filesystem. We write the tmp file next to the
      target, so they always are.

    Matches the convention from ``orchestrator.policy.suppression.
    forget_append`` (ADR-0004 §GDPR-forget atomicity).
    """
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    target = state_file_path(state_dir)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n"
    # Write to tmp file with explicit fsync so the rename can never
    # expose a zero-length file under crash. Matches the durability
    # bar set by ``orchestrator.ledger.Ledger.append``.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)
    return target


_LOCK_MAX_RETRIES = 10


@contextlib.contextmanager
def acquire_state_lock(state_dir: Path) -> Iterator[None]:
    """Advisory file lock around state-file read+modify+write sequences.

    Pattern matches ``orchestrator.ledger.Ledger.append`` — ``fcntl.lockf``
    on a dedicated lock file. Concurrent runners block at the
    ``LOCK_EX`` call, ensuring at most one runner modifies the state
    file at a time across processes. Single-process re-entry is NOT
    supported (POSIX advisory locks are per-process; the second
    acquire from the same process succeeds without blocking — do not
    rely on this for in-process mutual exclusion).

    Use as ``with acquire_state_lock(state_dir): ...``. The lock is
    released on context exit (success or exception).

    Lock-file deletion robustness (Pillar B Week 6 parallel-review P1
    fix per ``.planning/REVIEW-pillar-b-boil-the-ocean.md`` §P1-2).
    POSIX advisory locks attach to the ``(process, inode)`` pair, not
    the filename. If a concurrent process (or a stale-lock-cleanup
    script like ``find ~/.outreach-factory -name "*.lock" -delete``)
    removes the lock file while we hold the lock, a second runner can
    ``open(O_CREAT)`` a fresh file at the same path, get a different
    inode, and acquire ``LOCK_EX`` on it — both runners would believe
    they hold the exclusive lock, defeating cross-process
    serialization and allowing state-file double-writes.

    The mitigation: after acquiring the lock, re-stat the path and
    compare against the held fd's inode. On mismatch, our fd's lock
    is on an orphaned inode (correct mutual exclusion against any
    NEW openers on that orphan, but the path now points to a
    different file the world is racing against). Release, retry.
    Bounded retries (``_LOCK_MAX_RETRIES``); persistent mismatch
    after the cap raises ``RuntimeError`` so an operator with a
    rogue cleanup script in their environment gets a loud failure
    instead of silent corruption.
    """
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    p = lock_file_path(state_dir)
    for _attempt in range(_LOCK_MAX_RETRIES):
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT, 0o644)
        acquired = False
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX)
            acquired = True
            # Re-verify our fd's inode matches the path's current inode.
            # Mismatch = path was unlinked + recreated between our open
            # and our lockf; our lock is on an orphaned inode and the
            # world races on the new one.
            try:
                fd_ino = os.fstat(fd).st_ino
                path_ino = os.stat(str(p)).st_ino
            except OSError:
                # Path stat failed — file vanished after our open;
                # treat as inode mismatch (retry).
                fd_ino, path_ino = 0, 1
            if fd_ino == path_ino:
                try:
                    yield
                finally:
                    fcntl.lockf(fd, fcntl.LOCK_UN)
                return
            # Inode mismatch — release + retry.
            fcntl.lockf(fd, fcntl.LOCK_UN)
            acquired = False
        finally:
            if acquired:
                # Defensive: if yield raised before our return, lockf
                # release happens in the inner finally; we still need
                # to close the fd here.
                pass
            os.close(fd)
    raise RuntimeError(
        f"failed to acquire a stable lock on {p} after "
        f"{_LOCK_MAX_RETRIES} attempts — the lock file is being "
        f"repeatedly deleted or recreated by another process. "
        f"Investigate any script that deletes lock files (e.g. "
        f"`find ~/.outreach-factory -name '*.lock' -delete`) and "
        f"remove it before re-running apply.",
    )


def is_applied(
    state: MigrationState,
    category: MigrationCategory,
    migration_id: str,
) -> bool:
    """True if this migration appears in the applied list for its category."""
    return migration_id in state.applied.get(category.value, [])


def mark_applied(
    state: MigrationState,
    category: MigrationCategory,
    migration_id: str,
    *,
    now: datetime,
    runner_version: str | None = None,
) -> None:
    """Append a migration id to the applied list. No-op if already present.

    Mutates ``state`` in place. The caller is responsible for calling
    ``save_state_atomic`` to persist. The mutation is split from the
    persist so the runner can batch + serialize via the state lock
    without per-call file I/O when convenient (today the runner does
    save after every mark, but future batch operations could amortize).

    Always updates ``last_applied_at`` (even if the migration was
    already in the list) — the diagnostic value of "last activity at"
    includes idempotent re-marks.

    Raises
    ------
    ValueError:
        If ``now`` is not timezone-aware. We refuse naive datetimes to
        prevent silent UTC-vs-local timezone confusion in the on-disk
        timestamp.
    """
    if not now.tzinfo:
        raise ValueError(
            "mark_applied requires a timezone-aware `now` — pass "
            "datetime.now(timezone.utc), not datetime.now()",
        )
    lst = state.applied.setdefault(category.value, [])
    if migration_id not in lst:
        lst.append(migration_id)
    state.last_applied_at = now.isoformat()
    if runner_version is not None:
        state.last_runner_version = runner_version


def mark_unapplied(
    state: MigrationState,
    category: MigrationCategory,
    migration_id: str,
    *,
    now: datetime,
    runner_version: str | None = None,
) -> None:
    """Remove a migration id from the applied list. No-op if not present.

    Used by ``MigrationRunner.rollback`` to reverse a prior
    ``mark_applied``. Per D4 only ``is_reversible=True`` migrations
    get this treatment — the runner enforces (this function is the
    state-file mechanic; the policy lives in the runner).

    Updates ``state.last_applied_at`` to ``now`` — same as
    ``mark_applied``. The field tracks "last framework activity," not
    "last forward-apply"; the name is a historical accident. After a
    rollback, ``cat ~/.outreach-factory/migrations.state.json`` shows
    a ``last_applied_at`` timestamp that reflects the rollback time.
    See :class:`MigrationState` for the rationale on deferring a rename.

    Raises
    ------
    ValueError:
        If ``now`` is not timezone-aware (mirrors ``mark_applied``).
    """
    if not now.tzinfo:
        raise ValueError(
            "mark_unapplied requires a timezone-aware `now`",
        )
    lst = state.applied.get(category.value, [])
    if migration_id in lst:
        lst.remove(migration_id)
    state.last_applied_at = now.isoformat()
    if runner_version is not None:
        state.last_runner_version = runner_version
