"""Policy migration 0001 — add ``engine_compat:`` block + bump version 1→2.

Pillar B Week 4's first real policy migration. Operationalizes
invariant I3 (PILLAR-PLAN §1) for policy YAML files: every policy file
declares its engine-compatibility range so future engine releases can
audit "this file targets engine version X; you're running version Y"
without inspecting the rules themselves.

What it does
------------

For every ``*.yml`` file under ``ctx.policy_dir``:

1. Read the file. Refuse loud on unparseable YAML / non-mapping top-
   level / missing ``version:`` line.
2. Idempotence check: if the file ALREADY has a top-level
   ``engine_compat:`` block AND its ``version:`` is 2, the migration's
   effect is in place — skip.
3. Refuse loud on inconsistent state (``version: 2`` but no
   ``engine_compat:``, or ``engine_compat:`` present but
   ``version: 1`` — both indicate a partial-failure that an operator
   should inspect).
4. For files in the expected pre-migration shape (``version: 1`` and
   no ``engine_compat:``), surgically insert the ``engine_compat:``
   block immediately after the ``version:`` line, then bump the
   version 1→2.
5. Write atomically (tmp-then-rename).

The block written:

.. code-block:: yaml

    engine_compat:
      min_engine_version: '0.1.0'

The minimum engine version is the policy engine's own
:data:`orchestrator.policy.engine.POLICY_ENGINE_VERSION` constant —
captured at migration apply time. A future engine release that drops
legacy schema support can refuse to load files whose
``min_engine_version`` is too old without consulting the rules
themselves.

Why this is a real transformation, not boundary-of-empty
--------------------------------------------------------

Every operator's installed policy YAML files are at version 1 with no
``engine_compat:``. The migration will modify every operator-visible
``.yml`` under their policy dir (typically just ``cooldowns.yml``).
Re-runs find the migration's effect in place + skip — idempotence at
the per-file level matches the framework atomicity contract.

Contrast with the rejected ``policy/0001_baseline_version_field``
alternative (D18 in ADR-0012), which would have been boundary-of-empty
because the factory-shipped baseline already declares ``version: 1``.

Why ``is_reversible=True``
--------------------------

Unlike ledger migrations (append-only; structurally irreversible), a
policy file rewrite IS reversible: ``downgrade`` removes the
``engine_compat:`` block + reverts ``version: 2`` to ``version: 1``.
The framework's atomicity contract handles batch-level rollback (one
file's downgrade succeeds-or-fails atomically; the runner stops on
first failure and the state file accurately reflects the partial
result).

The reversibility is bounded: a *future* migration that mutates rule
shape (e.g. renames a field on every rule entry) would be much harder
to reverse cleanly. For this Week 4 migration the reverse path is
straightforward — remove what was added, restore the version.

Engine coordination
-------------------

The migration's version bump 1→2 is coordinated with
:data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`,
which now accepts ``frozenset({1, 2})``. Operators between git-pull
and migration-apply have v1 files; the new engine accepts v1; the
dispatcher keeps running. After migration apply, files are at v2;
engine still accepts v2; dispatcher keeps running. Without this
range-acceptance step, a single-version engine would reject v1 files
the moment the operator pulls the migration code — a flag-day failure
that the migration framework was designed to prevent.

See ADR-0012 for the design rationale + the engine-version-range
contract for future bumps.

Refuse-on-missing-policy-dir
----------------------------

Per :class:`MigrationRunner`, ``ctx.policy_dir`` defaults to
``<state_dir>/policies`` — always set. The meaningful failure is "the
path doesn't exist on disk." The migration refuses loudly in that case
(``FileNotFoundError``) rather than silently creating an empty policy
dir:

* Silent creation could mask a misconfigured state dir (operator's
  ``OUTREACH_FACTORY_STATE_DIR`` env points at the wrong dir; the
  migration creates an empty policy dir; the migration is marked
  applied; the operator's real policy dir remains untouched).
* The asymmetric-failure-cost calculus (PILLAR-PLAN §0) says loud
  refusal is correct here: false-positive refuse is recoverable
  (operator creates the dir + re-runs); false-negative silent apply
  is catastrophic (real policy dir never gets the migration applied).

Empty policy dir (zero ``.yml`` files) is NOT a refusal — it's a
legitimate state (a fresh OSS install with no policy customization).
``affected_count = 0`` + the runner marks applied.

See ADR-0012 for the full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.policy.engine import POLICY_ENGINE_VERSION

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._policy_io import (
    PolicyFileError,
    add_top_level_block_text,
    bump_version_text,
    iter_policy_files,
    read_policy_file,
    remove_top_level_block_text,
    write_policy_file_atomic,
)


# The migration id — exported so tests + downstream consumers can refer
# to it symbolically without re-typing the string.
MIGRATION_ID = "0001_add_engine_compat_field"

# Schema versions the migration transitions between. Constants live at
# module scope so tests can reference them + the engine-version-range
# audit reads them without scraping the implementation.
FROM_VERSION = 1
TO_VERSION = 2

# The block-key the migration inserts. The single-level map shape is
# documented in :func:`add_top_level_block_text`; expanding to a deeper
# shape requires either flattening the children or adding a more
# capable helper (deferred — YAGNI for Week 4).
COMPAT_BLOCK_KEY = "engine_compat"

# The child value the migration writes. ``min_engine_version`` records
# the version of the policy engine the file is known compatible with —
# i.e. :data:`orchestrator.policy.engine.POLICY_ENGINE_VERSION`. A
# future engine release that drops legacy schema support consults this
# field to refuse files known to be too old.
#
# The constant lives in ``engine.py`` (not in this migration) because
# it versions the policy ENGINE, not the migration framework. Pillar C
# / D / E / F may bump it as new rule classes land; the migration
# framework's own :data:`orchestrator.migrations.runner.RUNNER_VERSION`
# evolves independently (bumps when the runner's behavior changes,
# which is rare). The two share ``"0.1.0"`` at Week 4 because the
# project is at v0.1.0 overall; they're expected to diverge over time.
#
# A future migration that needs to RE-STAMP files at a newer
# POLICY_ENGINE_VERSION (e.g. after Pillar C adds LinkedIn rules) would
# be a brand-new policy/000N_restamp_engine_compat with its own ADR.
MIN_ENGINE_VERSION_VALUE = POLICY_ENGINE_VERSION


@dataclass
class AddEngineCompatField:
    """Add ``engine_compat:`` block to every policy YAML + bump version.

    See module docstring for the full contract. This class is a thin
    dataclass implementing the ``Migration`` Protocol; the work happens
    in :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as ``MIGRATION``;
    the category sub-package's ``__init__.py`` registers it into
    ``MIGRATIONS = [MIGRATION]``.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.POLICY
    description: str = (
        "Add engine_compat block to every policy YAML and bump "
        "version: 1 -> 2 (I3 baseline for policy-file evolution)"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Add the engine_compat block + bump version on every file.

        Refuses with ``FileNotFoundError`` if ``ctx.policy_dir`` does
        not exist as a real directory on disk. Operators with a fresh
        state dir whose policy sub-dir hasn't been created yet should
        copy ``config-template/cooldowns.example.yml`` into place or
        ``mkdir -p`` the directory explicitly before invoking apply.

        Returns a :class:`MigrationResult` with ``affected_count`` set
        to the number of policy files actually rewritten (or in
        ``dry_run`` mode, the number that WOULD be rewritten).

        Per-file outcomes:

        * ``version: 1`` + no ``engine_compat:`` → migrated (insert
          block + bump version + atomic write).
        * ``version: 2`` + ``engine_compat:`` present → skipped
          (already at target).
        * Any other shape (``version: 2`` without block; ``version: 1``
          with block; ``version: 3+``; missing ``version:``) → refused
          loud with :class:`PolicyFileError`.

        Raises
        ------
        FileNotFoundError:
            When ``ctx.policy_dir`` does not exist.
        PolicyFileError:
            On any unparseable / mismatched-shape policy file.
            Propagated to the runner; state pointer does NOT advance.
        """
        policy_dir = Path(ctx.policy_dir)
        if not policy_dir.exists():
            raise FileNotFoundError(
                f"policy migration {self.id!r} requires "
                f"ctx.policy_dir to be an existing directory; got "
                f"{policy_dir!s}. Either copy the factory templates "
                f"from config-template/ or `mkdir -p` it before "
                f"applying.",
            )

        affected = 0
        already_at_target = 0

        for path in iter_policy_files(policy_dir):
            data, text = read_policy_file(path)

            current_version = data.get("version")
            has_block = COMPAT_BLOCK_KEY in data

            if current_version == TO_VERSION and has_block:
                already_at_target += 1
                continue

            # Refuse loud on any inconsistent / unexpected shape. The
            # asymmetric-failure-cost calculus: silent-skip on a half-
            # migrated file would silently leave it half-migrated;
            # the operator might never re-run apply to finish it.
            if current_version == TO_VERSION and not has_block:
                raise PolicyFileError(
                    f"{path}: declares version: {TO_VERSION} but "
                    f"lacks the {COMPAT_BLOCK_KEY!r} block. This is "
                    f"a half-migrated state — manual inspection "
                    f"required.",
                )
            if current_version == FROM_VERSION and has_block:
                raise PolicyFileError(
                    f"{path}: declares version: {FROM_VERSION} but "
                    f"already has the {COMPAT_BLOCK_KEY!r} block. "
                    f"This is a half-migrated state — manual "
                    f"inspection required.",
                )
            if current_version != FROM_VERSION:
                raise PolicyFileError(
                    f"{path}: declares version: {current_version!r}; "
                    f"this migration expects "
                    f"{FROM_VERSION} (pre-migration) or "
                    f"{TO_VERSION} (already-applied). Manual "
                    f"intervention required.",
                )

            # The file is in the expected pre-migration shape:
            # version: 1 + no engine_compat block. Surgically insert
            # the block + bump the version. Order matters — the
            # block insert references "version:" as the anchor, so
            # it must run before the version bump (the regex still
            # matches `version: 1` BEFORE the bump). After the
            # block insert, the version line still exists at the
            # same location; the bump rewrites just that line.
            new_text = add_top_level_block_text(
                text, COMPAT_BLOCK_KEY,
                {"min_engine_version": MIN_ENGINE_VERSION_VALUE},
            )
            new_text = bump_version_text(
                new_text, FROM_VERSION, TO_VERSION,
            )

            if not ctx.dry_run:
                write_policy_file_atomic(path, new_text)
            affected += 1

        verb = "would migrate" if ctx.dry_run else "migrated"
        ctx.logger.info(
            "%s %d policy file(s) (added %s block + bumped "
            "version: %d -> %d; %d already at target)",
            verb, affected, COMPAT_BLOCK_KEY,
            FROM_VERSION, TO_VERSION, already_at_target,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} {affected} policy file(s): inserted "
                f"{COMPAT_BLOCK_KEY!r} block + bumped version "
                f"{FROM_VERSION}->{TO_VERSION} "
                f"({already_at_target} already at target)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove engine_compat + revert version 2 → 1 on every file.

        Inverse of :meth:`upgrade`. Operators rarely invoke; the
        framework requires ``allow_rollback=True`` explicitly.

        Per-file outcomes:

        * ``version: 2`` + ``engine_compat:`` present → reverted
          (remove block + bump version 2→1 + atomic write).
        * ``version: 1`` + no ``engine_compat:`` → skipped (already
          downgraded).
        * Inconsistent / unexpected shapes → refused loud.

        Raises
        ------
        FileNotFoundError:
            When ``ctx.policy_dir`` does not exist.
        PolicyFileError:
            On any unexpected-shape policy file.
        """
        policy_dir = Path(ctx.policy_dir)
        if not policy_dir.exists():
            raise FileNotFoundError(
                f"policy migration {self.id!r} downgrade requires "
                f"ctx.policy_dir to be an existing directory; got "
                f"{policy_dir!s}.",
            )

        affected = 0
        already_downgraded = 0

        for path in iter_policy_files(policy_dir):
            data, text = read_policy_file(path)

            current_version = data.get("version")
            has_block = COMPAT_BLOCK_KEY in data

            if current_version == FROM_VERSION and not has_block:
                already_downgraded += 1
                continue

            if current_version == TO_VERSION and not has_block:
                raise PolicyFileError(
                    f"{path}: declares version: {TO_VERSION} but "
                    f"lacks the {COMPAT_BLOCK_KEY!r} block. This is "
                    f"a half-migrated state — manual inspection "
                    f"required.",
                )
            if current_version == FROM_VERSION and has_block:
                raise PolicyFileError(
                    f"{path}: declares version: {FROM_VERSION} but "
                    f"has the {COMPAT_BLOCK_KEY!r} block. This is a "
                    f"half-migrated state — manual inspection "
                    f"required.",
                )
            if current_version != TO_VERSION:
                raise PolicyFileError(
                    f"{path}: declares version: {current_version!r}; "
                    f"this migration's downgrade expects "
                    f"{TO_VERSION} (apply target) or "
                    f"{FROM_VERSION} (already-downgraded). Manual "
                    f"intervention required.",
                )

            # version: 2 + block present — the post-upgrade shape.
            # Revert version first (the regex needs to find
            # `version: 2`), then remove the block. The block-removal
            # regex doesn't depend on the version line.
            new_text = bump_version_text(
                text, TO_VERSION, FROM_VERSION,
            )
            new_text = remove_top_level_block_text(
                new_text, COMPAT_BLOCK_KEY,
            )

            if not ctx.dry_run:
                write_policy_file_atomic(path, new_text)
            affected += 1

        verb = "would revert" if ctx.dry_run else "reverted"
        ctx.logger.info(
            "%s %d policy file(s) (removed %s block + reverted "
            "version: %d -> %d; %d already at v%d)",
            verb, affected, COMPAT_BLOCK_KEY,
            TO_VERSION, FROM_VERSION, already_downgraded, FROM_VERSION,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} {affected} policy file(s): removed "
                f"{COMPAT_BLOCK_KEY!r} block + bumped version "
                f"{TO_VERSION}->{FROM_VERSION} "
                f"({already_downgraded} already at v{FROM_VERSION})"
            ),
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: AddEngineCompatField = AddEngineCompatField()
