"""Policy migrations — YAML rewrite (and sometimes version bump).

Every policy file under ``~/.outreach-factory/policies/*.yml`` carries
``version:``. Pillar B + C have established two migration shapes; the
runner sequences both kinds uniformly. Migration authors choose the
shape that matches the change they're making.

**Schema-changing migrations** (e.g. ``policy/0001_add_engine_compat_field``):

1. Read the existing YAML.
2. Verify the file's ``version:`` matches the migration's expected
   ``from_version``.
3. Transform the file's top-level structure (add/remove top-level
   fields; rewrite the version value).
4. Write the file back with the new ``version:`` set.
5. Ship coordinated with a
   :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`
   update per ADR-0012 D22 — extending the accepted-version set so the
   engine continues to load files between operator pulling code and
   running the migration.

**Content-additive migrations** (e.g. ``policy/0002_add_li_invite_weekly_cap``,
``policy/0003_add_li_dm_weekly_cap``, ``policy/0004_add_tw_dm_weekly_cap``,
``policy/0005_add_calendar_booking_daily_cap``,
``policy/0006_add_cross_channel_email_linkedin_cooldown``, and any
future per-channel-pair cross-channel cooldown migrations):

1. Read the existing YAML.
2. Accept any file whose ``version:`` is in
   :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`
   (no per-migration ``from_version`` check; the engine's SUPPORTED set
   is the version-acceptance contract).
3. Append or remove rule entries from the ``rules:`` list via the
   surgical-edit primitives ``add_rule_block_text`` /
   ``remove_rule_block_text`` — without changing the file's
   ``version:``.
4. Write the file back atomically.

Content-additive migrations do NOT bump ``version:`` and do NOT extend
:data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS` —
per ADR-0020 D75-D76. The file's structural shape is unchanged; only
the content under an existing top-level key (``rules:``) changes.

A migration author deciding which shape applies asks: *does the engine
code need to change to parse the post-migration file?* If yes →
schema-changing migration → bump + extend SUPPORTED. If no →
content-additive → no bump.

The migration framework (``MigrationRunner``) tracks "did this
migration apply?" at the framework level via the state file; the
per-file ``version:`` is the in-file marker the policy engine consults
to gate version-acceptance.

Policy migrations are usually reversible (the YAML structure permits
inverse transformations). Operators with custom policy files outside
the factory ruleset may experience friction — the migration must be
robust enough to handle operator-edited rules, or it must refuse +
print "this file has a custom rule the migration does not know how
to upgrade; manual edit required" rather than corrupt the file.

Per-category dispatcher boundary
--------------------------------

Policy migrations consume :mod:`._policy_io` for the per-file IO. The
helper module exposes:

* :func:`._policy_io.iter_policy_files` — walk
  ``<policy_dir>/*.yml`` (non-recursive), sorted, skipping hidden +
  Obsidian Sync conflict files.
* :func:`._policy_io.read_policy_file` — parse YAML + return raw
  text. The raw text is what surgical edits operate on (to preserve
  comments); the parsed dict is for version + shape validation.
* :func:`._policy_io.write_policy_file_atomic` — tmp-then-rename
  atomic write per file.
* :func:`._policy_io.add_top_level_field_text` /
  :func:`._policy_io.add_top_level_block_text` — surgical insert
  preserving comments + ordering of unaffected lines. Used by
  schema-changing migrations.
* :func:`._policy_io.remove_top_level_field_text` /
  :func:`._policy_io.remove_top_level_block_text` — surgical delete
  inverses. Used by schema-changing migrations' rollback paths.
* :func:`._policy_io.add_rule_block_text` /
  :func:`._policy_io.remove_rule_block_text` — surgical insert/delete
  of one rule entry under the top-level ``rules:`` list. Used by
  content-additive migrations (Pillar C Weeks 7-11). The two are
  paired inverses; round-trip byte-identical is a tested invariant.
* :func:`._policy_io.bump_version_text` — rewrite the top-level
  ``version:`` line with defense-in-depth current-value check. Used
  ONLY by schema-changing migrations.

Engine coordination
-------------------

Schema-changing migrations that bump ``version:`` MUST ship
coordinated with an update to
:data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`
that ADDS the new version to the accepted set. Forward-compat range
acceptance prevents the operator's send loop from breaking during the
window between git-pull and migration-apply (per ADR-0011 D12's
warn-on-pending posture; doctor warns but the dispatcher keeps
running).

Content-additive migrations require NO engine coordination — the
existing SUPPORTED set already accepts the file shape they produce.
Per ADR-0020 D76.

See ADR-0012 for the policy-migration-specific design (per-file
atomicity, surgical-edit pattern, version-bump coordination contract,
first concrete migration ``0001_add_engine_compat_field``). See
ADR-0020 for the content-additive migration pattern + the revised
version-bump policy that distinguishes the two shapes (D75).
"""

from __future__ import annotations

from ..types import Migration
from .migration_0001 import MIGRATION as MIGRATION_0001_ADD_ENGINE_COMPAT
from .migration_0002_add_li_invite_weekly_cap import (
    MIGRATION as MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP,
)
from .migration_0003_add_li_dm_weekly_cap import (
    MIGRATION as MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP,
)
from .migration_0004_add_tw_dm_weekly_cap import (
    MIGRATION as MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP,
)
from .migration_0005_add_calendar_booking_daily_cap import (
    MIGRATION as MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP,
)
from .migration_0006_add_cross_channel_email_linkedin_cooldown import (
    MIGRATION as MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN,
)
from .migration_0007_add_reply_classifier_llm_cap import (
    MIGRATION as MIGRATION_0007_ADD_REPLY_CLASSIFIER_LLM_CAP,
)


MIGRATIONS: list[Migration] = [
    MIGRATION_0001_ADD_ENGINE_COMPAT,
    MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP,
    MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP,
    MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP,
    MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP,
    MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN,
    MIGRATION_0007_ADD_REPLY_CLASSIFIER_LLM_CAP,
]
