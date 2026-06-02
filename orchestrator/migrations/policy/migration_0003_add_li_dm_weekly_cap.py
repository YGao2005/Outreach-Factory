"""Policy migration 0003 — add ``linkedin-weekly-dm-cap`` rule.

Pillar C Week 8's per-channel policy migration. Second of Weeks 7-11's
per-channel cap migration range per ADR-0020 §D72's per-week trajectory.
Structurally mirrors Week 7's
:mod:`orchestrator.migrations.policy.migration_0002_add_li_invite_weekly_cap`
modulo the channel filter / source value / max_units default. The
shared primitives (:func:`._policy_io.add_rule_block_text` /
:func:`._policy_io.remove_rule_block_text`) land in Week 7; Week 8
consumes them unchanged.

What it does
------------

For every ``*.yml`` file under ``ctx.policy_dir``:

1. Read the file. Refuse loud on unparseable / non-mapping / missing-
   ``rules:`` / rules-not-a-list shape (inherited from Week 7's
   per-week-review P2-A guard).
2. Sanity-check the file's ``version:`` is in
   :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.
   Refuse loud on any other version (operator-corrupted state).
3. Idempotence check: if a rule with the canonical name
   ``linkedin-weekly-dm-cap`` is already present, skip the file. Per
   ADR-0020 D74 (rule-name lookup; inherited by ADR-0021).
4. Append the canonical rule to the ``rules:`` list via
   :func:`._policy_io.add_rule_block_text` (APPEND semantics per
   ADR-0020 D73 — operator-installed-first ordering preserved).
5. Atomically write the file (tmp-then-rename + fsync).

The rule appended:

.. code-block:: yaml

    - name: linkedin-weekly-dm-cap
      type: budget.window-cap
      block_when:
        channel: linkedin
      source: linkedin_dm
      window_days: 7
      max_units: 50
      reason: "LinkedIn weekly DM cap (conservative default; ...)"

The ``source: linkedin_dm`` value is the load-bearing field that makes
the rule actually fire on real ledger events. Per ADR-0016 D43, Pillar
C Week 3's LinkedIn-DM dispatcher emits ``cost_incurred`` events with
``source="linkedin_dm"`` (distinct from ``source="linkedin_invite"``
per ADR-0015 D40). The rule's ``source:`` field MUST match the
dispatcher's emit value — otherwise the rule activates but reports
zero usage, silently allowing over-quota sends (the exact failure mode
the cap exists to prevent).

Why ``max_units: 50``
---------------------

Per ADR-0021 D79. LinkedIn does NOT publish an official DM-specific
weekly soft cap — only the better-known ~100/week INVITE cap that
ADR-0008's hardcoded constant + Week 7's policy/0002 migration
deliver. The DM cap is operator-deliberate; the factory ships 50 as a
conservative half-of-invite default. The asymmetric-failure-cost
calculus:

* DM throttling is recipient-visible (recipients stop seeing
  notifications); recovery is opaque + account-level.
* The cost of an over-quota DM (account throttled / suspended) is
  catastrophic — multiple weeks of outreach surface lost.
* The cost of an under-quota cap (operators with established sender
  reputations bottleneck at the cap) is one-line YAML edit.
* Asymmetric cost favors the conservative default.

Operators with established sender reputations tune up; operators in
the warm-up phase tune down. The factory's commented Rule 12c
documents the shape for new operators.

Why no stale-source detection (unlike Week 7's policy/0002)
-----------------------------------------------------------

Per ADR-0021 D81. Week 7's policy/0002 detects + warns on operators
who have the canonical ``linkedin-weekly-invite-cap`` rule with a
``source: linkedin`` field (the pre-Pillar-C-Week-2 ADR-0008 factory
shape — see ADR-0020 §D77 Shape 1). The warning surfaces an inert-
rule misconfig.

Week 8 has no analogous staleness path. LinkedIn DM dispatcher
(ADR-0016) shipped 2026-05-21, AFTER ADR-0015 D40's split-source
convention was established 2026-05-20. There has never been a
factory-shipped ``linkedin-weekly-dm-cap`` rule with a stale ``source:
linkedin`` field — the canonical source from day one is
``linkedin_dm``. No operator could have copied a stale factory shape;
no warning is needed. ADR-0021 §"Existing-operator seed" is shorter
than ADR-0020's by exactly Shape 1.

Why no version bump
-------------------

Per ADR-0020 D75 / D76 (inherited by ADR-0021): per-channel rule
additions are CONTENT-ADDITIVE, not SCHEMA-CHANGING. The engine's
parser handles the new rule entry via its existing ``budget.window-cap``
registry entry; no new field name, no new top-level structure, no new
file shape. The migration does NOT bump the file's ``version:`` and
does NOT extend :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.

Why ``is_reversible=True``
--------------------------

:func:`._policy_io.add_rule_block_text` and
:func:`._policy_io.remove_rule_block_text` are paired inverses
verified by round-trip tests against the real factory
``cooldowns.example.yml``. ``downgrade`` removes the rule by canonical
name; operators who manually added a renamed version (e.g.
``linkedin-weekly-dm-cap-50``) keep their version through rollback.

Refuse-on-missing-policy-dir
----------------------------

Per :class:`MigrationRunner`, ``ctx.policy_dir`` defaults to
``<state_dir>/policies`` — always set. The meaningful failure is "the
path doesn't exist on disk." The migration refuses loud
(``FileNotFoundError``) rather than silently creating an empty policy
dir — same asymmetric-failure-cost calculus as ``policy/0001`` +
``policy/0002``.

Empty policy dir (zero ``.yml`` files) is NOT a refusal — it's a
legitimate state (a fresh OSS install with no policy customization).
``affected_count = 0`` + the runner marks applied.

See ADR-0021 for the full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.policy.engine import SUPPORTED_POLICY_SCHEMA_VERSIONS

from ..types import MigrationCategory, MigrationContext, MigrationResult
from ._policy_io import (
    PolicyFileError,
    add_rule_block_text,
    iter_policy_files,
    read_policy_file,
    remove_rule_block_text,
    write_policy_file_atomic,
)


# The migration id — exported so tests + downstream consumers can refer
# to it symbolically without re-typing the string.
MIGRATION_ID = "0003_add_li_dm_weekly_cap"

# The canonical rule the migration adds. The `name` field is the
# load-bearing identifier — `downgrade` matches on it; idempotence
# checks match on it; the `policy_blocked` audit event's `rule:` field
# carries it.
RULE_NAME = "linkedin-weekly-dm-cap"

# The rule's `type:` discriminator into the engine's
# `RULE_REGISTRY`. `budget.window-cap` is the existing rule class —
# the migration adds an INSTANCE of it, not a new class. ADR-0006
# §Decision item "Three concrete rule classes". Same class Week 7's
# policy/0002 uses; the two rules are independent instances filtered
# by `source:`.
RULE_TYPE = "budget.window-cap"

# The rule's `source:` filter — which `cost_incurred` events it
# aggregates. Pillar C Week 3's LinkedIn-DM dispatcher emits events
# with `source="linkedin_dm"` per ADR-0016 D43. The rule must match
# exactly. Distinct from `linkedin_invite` per ADR-0015 D40's split-
# source convention.
RULE_SOURCE = "linkedin_dm"

# The rule's `block_when.channel:` filter — only fires the rule when
# the send-gate's `ctx.channel` is "linkedin". An email send with the
# same DM history is allowed (channel mismatch → rule not applicable).
# Per ADR-0003. Same `channel:` value as Week 7's invite cap because
# both share the upstream rate-limit pool (LinkedIn's personal-account
# enforcement is account-wide); the `source:` field is the per-action
# discriminator.
RULE_BLOCK_WHEN_CHANNEL = "linkedin"

# The rule's window — 7 days, matching the operator's normal weekly
# cadence for outreach planning. Same window as Week 7's invite cap.
RULE_WINDOW_DAYS = 7

# The rule's quota — 50 DMs per week. LinkedIn does NOT publish a
# DM-specific soft cap; operator-tunable conservative default. Per
# ADR-0021 D79 the asymmetric-failure-cost calculus biases toward
# refuse-by-default: the cost of an account-level penalty (multiple
# weeks of outreach surface lost) vastly outweighs the cost of a
# false-block (one-line YAML edit to raise the cap).
RULE_MAX_UNITS = 50

# Human-readable reason surfaced in `policy_blocked` events. Names the
# soft-cap-by-convention shape so operators inspecting the event
# stream understand why the cap exists.
RULE_REASON = (
    "LinkedIn weekly DM cap (conservative 50/wk default; LinkedIn "
    "doesn't publish an official DM cap — operator-tunable in "
    "cooldowns.yml)"
)

# The block of YAML text the migration inserts. Pre-formatted with
# leading 2-space indent (one level under `rules:`) per the
# `add_rule_block_text` contract. Constructed at module-load time so
# tests can inspect the literal bytes the migration writes.
RULE_BLOCK_TEXT = (
    f"  - name: {RULE_NAME}\n"
    f"    type: {RULE_TYPE}\n"
    f"    block_when:\n"
    f"      channel: {RULE_BLOCK_WHEN_CHANNEL}\n"
    f"    source: {RULE_SOURCE}\n"
    f"    window_days: {RULE_WINDOW_DAYS}\n"
    f"    max_units: {RULE_MAX_UNITS}\n"
    f'    reason: "{RULE_REASON}"\n'
)


def _rule_present_by_name(data: dict, name: str) -> bool:
    """Whether ``data["rules"]`` contains an entry with ``name: <name>``.

    Uses the parsed-dict view (cheap, no regex). Quote-style is
    irrelevant — ``yaml.safe_load`` normalizes ``- name: foo`` /
    ``- name: 'foo'`` / ``- name: "foo"`` all to the same string.

    Returns ``False`` if ``rules`` is missing, ``None``, or empty.

    Identical implementation to Week 7's policy/0002; the two
    migrations could share a helper, but the convention so far is one
    file per migration for grep + diff legibility. A future
    consolidation into a shared ``_policy_rule_helpers`` module is a
    Pillar I OSS bring-up opportunity (deferred).
    """
    rules = data.get("rules")
    if not isinstance(rules, list):
        return False
    for r in rules:
        if isinstance(r, dict) and r.get("name") == name:
            return True
    return False


@dataclass
class AddLinkedInDMWeeklyCap:
    """Add the LinkedIn weekly DM cap rule to every policy file.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work happens in
    :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as
    :data:`MIGRATION`; the category sub-package's ``__init__.py``
    registers it into ``MIGRATIONS = [...]`` after policy/0002.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.POLICY
    description: str = (
        "Add linkedin-weekly-dm-cap rule (budget.window-cap, 50 DMs/7d "
        "on source=linkedin_dm) to every policy file's rules list — "
        "activates the per-channel cap for the LinkedIn-DM dispatcher "
        "(ADR-0016) at a conservative default; operator-tunable"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Append the canonical rule to every policy file.

        Refuses with ``FileNotFoundError`` if ``ctx.policy_dir`` does
        not exist as a real directory on disk.

        Per-file outcomes:

        * Rule already present (canonical name match) → skip (no
          stale-source warning path — see module docstring).
        * Rule absent → append via ``add_rule_block_text`` + atomic
          write.
        * Unparseable / non-mapping / missing ``rules:`` / non-list
          ``rules:`` / unsupported ``version:`` → refuse loud with
          :class:`PolicyFileError`.

        Raises
        ------
        FileNotFoundError:
            When ``ctx.policy_dir`` does not exist.
        PolicyFileError:
            On any unparseable / unexpected-shape / unsupported-version
            policy file. Propagated to the runner; state pointer does
            NOT advance — re-running after the operator fixes the file
            resumes cleanly.
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
        already_present = 0

        for path in iter_policy_files(policy_dir):
            data, text = read_policy_file(path)

            # Defense-in-depth version check. By the time policy/0003
            # runs through the runner, policy/0001 + policy/0002 have
            # applied (the runner sequences migrations) so files are at
            # version 2. An operator who somehow bypassed policy/0001
            # has v1 files — the engine accepts both v1 and v2 per
            # ADR-0012 D22, so we accept both too. Anything outside the
            # SUPPORTED set is operator-corrupted state.
            version = data.get("version")
            try:
                version_int = int(version) if version is not None else None
            except (TypeError, ValueError):
                version_int = None
            if version_int not in SUPPORTED_POLICY_SCHEMA_VERSIONS:
                supported = ", ".join(
                    str(v) for v in sorted(SUPPORTED_POLICY_SCHEMA_VERSIONS)
                )
                raise PolicyFileError(
                    f"{path}: declares version: {version!r} which is "
                    f"not in SUPPORTED_POLICY_SCHEMA_VERSIONS "
                    f"({{{supported}}}). This migration handles only "
                    f"engine-supported versions; manual inspection "
                    f"required.",
                )

            # The migration appends to the `rules:` list. A file with
            # no `rules:` key is structurally unusual — refuse rather
            # than silently creating one. (The engine treats absent
            # `rules:` as `[]`, but policy files in the wild always
            # declare it; an absent `rules:` likely indicates operator
            # corruption.)
            if "rules" not in data:
                raise PolicyFileError(
                    f"{path}: missing top-level `rules:` key. Every "
                    f"policy file must declare `rules:` even if "
                    f"empty (`rules: []`). Manual inspection required.",
                )

            # `rules:` present but not a list (e.g. `rules: null`,
            # `rules: some-string`, `rules: {}`) — operator-corrupted
            # state. The text-level `add_rule_block_text` helper would
            # see the inline scalar value, fall through to the
            # multi-line branch (no entries to scan), and append the
            # new rule below the scalar — producing a structurally
            # broken file that the engine refuses to load.
            # Refuse loud per the asymmetric-failure-cost principle.
            # (Inherited from Week 7's per-week-review P2-A guard.)
            rules_value = data["rules"]
            if not isinstance(rules_value, list):
                raise PolicyFileError(
                    f"{path}: `rules:` is present but not a YAML "
                    f"list (got {type(rules_value).__name__}). "
                    f"Every policy file must declare `rules:` as a "
                    f"list (use `rules: []` for empty). Manual "
                    f"inspection required.",
                )

            # Idempotence check via rule-name lookup (ADR-0020 D74
            # inherited by ADR-0021). Operators who manually added the
            # canonical-named rule keep their version — including any
            # threshold tuning. The migration does NOT overwrite
            # operator-tuned values.
            #
            # No stale-source warning path here (per ADR-0021 D81):
            # there has never been a factory-shipped `linkedin-weekly-
            # dm-cap` rule with a non-canonical source, so no operator
            # could have copied a stale shape. Contrast with
            # policy/0002 which DOES warn for `source: linkedin` per
            # ADR-0020 §D77 Shape 1.
            if _rule_present_by_name(data, RULE_NAME):
                already_present += 1
                continue

            # Append the rule. The `add_rule_block_text` primitive
            # handles inline-empty + multi-line forms uniformly; the
            # APPEND semantics put the new rule AFTER any existing
            # operator-installed rules (D73).
            new_text = add_rule_block_text(text, RULE_BLOCK_TEXT)

            if not ctx.dry_run:
                write_policy_file_atomic(path, new_text)
            affected += 1

        verb = "would add" if ctx.dry_run else "added"
        ctx.logger.info(
            "%s %r rule to %d policy file(s) (%d already present)",
            verb, RULE_NAME, affected, already_present,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} {RULE_NAME!r} rule to {affected} policy "
                f"file(s) ({already_present} already at target)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove the canonical-named rule from every policy file.

        Inverse of :meth:`upgrade`. Removes ONLY the rule with the
        canonical name — operator-renamed versions (e.g.
        ``linkedin-weekly-dm-cap-50``) stay. Operators rarely invoke;
        the framework requires ``allow_rollback=True`` explicitly.

        Per-file outcomes:

        * Canonical rule present → remove via
          ``remove_rule_block_text`` + atomic write.
        * Canonical rule absent → skip (idempotent re-run).
        * ``rules:`` missing or not a list → refuse loud
          (operator-corrupted state).

        Operator-tuned-value loss
        -------------------------

        Downgrade removes by canonical NAME, not by structural identity.
        If the operator tuned the rule's ``max_units``, ``window_days``,
        or ``reason`` fields after the migration applied, those tuned
        values are LOST when downgrade removes the rule. Operators who
        want to preserve tuning + revert the migration's effect should
        rename their tuned rule first (any name not equal to
        ``linkedin-weekly-dm-cap``), then run downgrade — the renamed
        rule stays untouched. Same posture as Week 7's policy/0002
        documented.

        Raises
        ------
        FileNotFoundError:
            When ``ctx.policy_dir`` does not exist.
        PolicyFileError:
            On any unparseable / unexpected-shape policy file, or
            files with non-list ``rules:`` values.
        """
        policy_dir = Path(ctx.policy_dir)
        if not policy_dir.exists():
            raise FileNotFoundError(
                f"policy migration {self.id!r} downgrade requires "
                f"ctx.policy_dir to be an existing directory; got "
                f"{policy_dir!s}.",
            )

        affected = 0
        already_absent = 0

        for path in iter_policy_files(policy_dir):
            data, text = read_policy_file(path)

            # Defense-in-depth type check matching upgrade's guard.
            # A non-list `rules:` is operator-corrupted state; the
            # remove helper would silently do nothing (the regex
            # match on `- name:` would not match anything in a non-
            # list rules: value), masking the corruption.
            if "rules" in data:
                rules_value = data["rules"]
                if not isinstance(rules_value, list):
                    raise PolicyFileError(
                        f"{path}: `rules:` is present but not a YAML "
                        f"list (got {type(rules_value).__name__}). "
                        f"Manual inspection required before downgrade.",
                    )

            if not _rule_present_by_name(data, RULE_NAME):
                already_absent += 1
                continue

            new_text = remove_rule_block_text(text, RULE_NAME)

            if not ctx.dry_run:
                write_policy_file_atomic(path, new_text)
            affected += 1

        verb = "would remove" if ctx.dry_run else "removed"
        ctx.logger.info(
            "%s %r rule from %d policy file(s) (%d already absent)",
            verb, RULE_NAME, affected, already_absent,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} {RULE_NAME!r} rule from {affected} policy "
                f"file(s) ({already_absent} already absent)"
            ),
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: AddLinkedInDMWeeklyCap = AddLinkedInDMWeeklyCap()
