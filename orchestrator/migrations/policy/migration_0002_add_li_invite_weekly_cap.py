"""Policy migration 0002 — add ``linkedin-weekly-invite-cap`` rule.

Pillar C Week 7's per-channel policy migration. Activates the rule
shape ADR-0008 ships factory-commented in
``config-template/cooldowns.example.yml``: the LinkedIn weekly invite
cap (100/week soft limit per LinkedIn's personal-account terms). The
factory rule is commented because operators with no LinkedIn outreach
shouldn't see refusals their use case doesn't motivate (ADR-0008
§Alternative 4). This migration adds the rule for operators who DO
use LinkedIn outreach without requiring them to manually copy the
factory rule into their installed ``~/.outreach-factory/policies/
cooldowns.yml``.

What it does
------------

For every ``*.yml`` file under ``ctx.policy_dir``:

1. Read the file. Refuse loud on unparseable / non-mapping / missing-
   ``rules:`` shape.
2. Sanity-check the file's ``version:`` is in
   :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.
   Refuse loud on any other version (operator-corrupted state).
3. Idempotence check: if a rule with the canonical name
   ``linkedin-weekly-invite-cap`` is already present, skip the file.
   Operators who manually uncommented the factory rule (per ADR-0008's
   suggested rollout) have their version preserved — including any
   threshold tuning (e.g. ``max_units: 80`` for a more conservative
   posture). Per ADR-0020 D74 (rule-name lookup).
4. Append the canonical rule to the ``rules:`` list via
   :func:`._policy_io.add_rule_block_text` (APPEND semantics per
   ADR-0020 D73 — operator-installed-first ordering preserved).
5. Atomically write the file (tmp-then-rename + fsync).

The rule appended:

.. code-block:: yaml

    - name: linkedin-weekly-invite-cap
      type: budget.window-cap
      block_when:
        channel: linkedin
      source: linkedin_invite
      window_days: 7
      max_units: 100
      reason: "LinkedIn weekly invite cap (100/wk soft limit ...)"

The ``source: linkedin_invite`` value is the load-bearing field that
makes the rule actually fire on real ledger events. Per ADR-0015 D40,
Pillar C Week 2's LinkedIn-invite dispatcher emits ``cost_incurred``
events with ``source="linkedin_invite"`` (distinct from
``source="linkedin_dm"`` per ADR-0016 and ``source="twitter_dm"`` per
ADR-0018). The rule's ``source:`` field MUST match the dispatcher's
emit value — otherwise the rule activates but reports zero usage,
silently allowing over-quota sends (the exact failure mode the cap
exists to prevent).

This deviates from ADR-0008's factory-shipped ``source: linkedin``
shape — that value was set before Pillar C Week 2's per-channel
source naming convention was established (ADR-0015 D40). ADR-0020
§Existing-operator seed documents the reconciliation path: operators
who already uncommented the factory rule (with ``source: linkedin``)
are preserved as-is (D74 name-match idempotence); operators on the
canonical migration path get the corrected ``source: linkedin_invite``.

Why no version bump
-------------------

Per ADR-0020 D75 (revised from ADR-0012 D22's "every bump"
recommendation): per-channel rule additions are CONTENT-ADDITIVE, not
SCHEMA-CHANGING. The engine's parser handles the new rule entry via
its existing ``budget.window-cap`` registry entry; no new field name,
no new top-level structure, no new file shape. The migration thus
does NOT bump the file's ``version:`` and does NOT extend
:data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.

The contrast with ``policy/0001_add_engine_compat_field`` is
deliberate: that migration introduced a new top-level field
(``engine_compat:``) — a schema change requiring version bump + engine
coordination. This migration adds list content under an existing
field — no shape change.

Why ``is_reversible=True``
--------------------------

:func:`._policy_io.add_rule_block_text` and
:func:`._policy_io.remove_rule_block_text` are paired inverses
verified by round-trip tests against the real factory
``cooldowns.example.yml``. ``downgrade`` removes the rule by canonical
name; operators who manually added a renamed version (e.g.
``linkedin-weekly-cap-100``) keep their version through rollback.

Refuse-on-missing-policy-dir
----------------------------

Per :class:`MigrationRunner`, ``ctx.policy_dir`` defaults to
``<state_dir>/policies`` — always set. The meaningful failure is "the
path doesn't exist on disk." The migration refuses loud
(``FileNotFoundError``) rather than silently creating an empty policy
dir — same asymmetric-failure-cost calculus as ``policy/0001``.

Empty policy dir (zero ``.yml`` files) is NOT a refusal — it's a
legitimate state (a fresh OSS install with no policy customization).
``affected_count = 0`` + the runner marks applied.

See ADR-0020 for the full design rationale.
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
MIGRATION_ID = "0002_add_li_invite_weekly_cap"

# The canonical rule the migration adds. The `name` field is the
# load-bearing identifier — `downgrade` matches on it; idempotence
# checks match on it; the `policy_blocked` audit event's `rule:` field
# carries it.
RULE_NAME = "linkedin-weekly-invite-cap"

# The rule's `type:` discriminator into the engine's
# `RULE_REGISTRY`. `budget.window-cap` is the existing rule class —
# the migration adds an INSTANCE of it, not a new class. ADR-0006
# §Decision item "Three concrete rule classes".
RULE_TYPE = "budget.window-cap"

# The rule's `source:` filter — which `cost_incurred` events it
# aggregates. Pillar C Week 2's LinkedIn-invite dispatcher emits
# events with `source="linkedin_invite"` per ADR-0015 D40. The rule
# must match exactly.
RULE_SOURCE = "linkedin_invite"

# The rule's `block_when.channel:` filter — only fires the rule when
# the send-gate's `ctx.channel` is "linkedin". An email send with the
# same invite history is allowed (channel mismatch → rule not
# applicable). Per ADR-0003.
RULE_BLOCK_WHEN_CHANNEL = "linkedin"

# The rule's window — 7 days, matching LinkedIn's weekly soft cap.
RULE_WINDOW_DAYS = 7

# The rule's quota — 100 invites per week (the LinkedIn personal-
# account soft cap; operators with Premium accounts may tune higher
# via manual edits to their cooldowns.yml).
RULE_MAX_UNITS = 100

# Human-readable reason surfaced in `policy_blocked` events.
RULE_REASON = (
    "LinkedIn weekly invite cap (100/wk soft limit per LinkedIn "
    "personal-account terms)"
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


# The stale `source:` value the ADR-0008 factory shape carried before
# Pillar C Week 2 established the per-channel source-naming convention.
# Operators who copied the factory rule pre-Week-2 + manually
# uncommented it have this value in their `cooldowns.yml`; the
# dispatcher's emit (`source="linkedin_invite"`) doesn't match, so
# their rule fires on zero events. ADR-0020 §D77 Shape 1.
_STALE_PRE_WEEK_2_SOURCE = "linkedin"


def _rule_present_by_name(data: dict, name: str) -> bool:
    """Whether ``data["rules"]`` contains an entry with ``name: <name>``.

    Uses the parsed-dict view (cheap, no regex). Quote-style is
    irrelevant — ``yaml.safe_load`` normalizes ``- name: foo`` /
    ``- name: 'foo'`` / ``- name: "foo"`` all to the same string.

    Returns ``False`` if ``rules`` is missing, ``None``, or empty.
    """
    rules = data.get("rules")
    if not isinstance(rules, list):
        return False
    for r in rules:
        if isinstance(r, dict) and r.get("name") == name:
            return True
    return False


def _find_rule_by_name(data: dict, name: str) -> dict | None:
    """Return the first rule entry with ``name: <name>``, or ``None``.

    Same lookup as :func:`_rule_present_by_name` but returns the entry
    itself so callers can inspect its fields (used by the warning path
    that surfaces stale-source rules per ADR-0020 §D77 Shape 1).
    """
    rules = data.get("rules")
    if not isinstance(rules, list):
        return None
    for r in rules:
        if isinstance(r, dict) and r.get("name") == name:
            return r
    return None


@dataclass
class AddLinkedInInviteWeeklyCap:
    """Add the LinkedIn weekly invite cap rule to every policy file.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work happens in
    :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as
    :data:`MIGRATION`; the category sub-package's ``__init__.py``
    registers it into ``MIGRATIONS = [...]``.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.POLICY
    description: str = (
        "Add linkedin-weekly-invite-cap rule (budget.window-cap, "
        "100 invites/7d on source=linkedin_invite) to every policy "
        "file's rules list — activates ADR-0008's factory-commented "
        "rule for operator-installed cooldowns.yml"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Append the canonical rule to every policy file.

        Refuses with ``FileNotFoundError`` if ``ctx.policy_dir`` does
        not exist as a real directory on disk.

        Per-file outcomes:

        * Rule already present (canonical name match) → skip.
        * Rule absent → append via ``add_rule_block_text`` + atomic
          write.
        * Unparseable / non-mapping / missing ``rules:`` / unsupported
          ``version:`` → refuse loud with :class:`PolicyFileError`.

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

            # Defense-in-depth version check. By the time policy/0002
            # runs through the runner, policy/0001 has applied (the
            # runner sequences migrations) so files are at version 2.
            # An operator who somehow bypassed policy/0001 has v1 files —
            # the engine accepts both v1 and v2 per ADR-0012 D22, so we
            # accept both too. Anything outside the SUPPORTED set is
            # operator-corrupted state.
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
            # (Per-week-review P2-A follow-up.)
            rules_value = data["rules"]
            if not isinstance(rules_value, list):
                raise PolicyFileError(
                    f"{path}: `rules:` is present but not a YAML "
                    f"list (got {type(rules_value).__name__}). "
                    f"Every policy file must declare `rules:` as a "
                    f"list (use `rules: []` for empty). Manual "
                    f"inspection required.",
                )

            # Idempotence check via rule-name lookup (ADR-0020 D74).
            # Operators who manually added the canonical-named rule
            # (per ADR-0008's suggested rollout) keep their version —
            # including any threshold tuning. The migration does NOT
            # overwrite operator-tuned values.
            if _rule_present_by_name(data, RULE_NAME):
                # Operator-friendly: when the operator has the
                # canonical-named rule but with the stale ADR-0008
                # `source: linkedin` (Pillar C pre-Week-2), warn at
                # WARNING level so the next dispatcher run's logs make
                # the inert-rule misconfig visible. Per ADR-0020 §D77
                # Shape 1 + per-week-review P2-B follow-up.
                stale_rule = _find_rule_by_name(data, RULE_NAME)
                if (
                    stale_rule is not None
                    and stale_rule.get("source") == _STALE_PRE_WEEK_2_SOURCE
                ):
                    ctx.logger.warning(
                        "%s: rule %r is present with stale "
                        "source=%r (pre-Pillar-C-Week-2 factory "
                        "shape). The Pillar C Week 2 dispatcher "
                        "emits cost_incurred events with "
                        "source=%r — your rule fires on zero events. "
                        "Manual remediation: edit `source: %s` -> "
                        "`source: %s` in the rule entry. Reference: "
                        "ADR-0015 D40 + ADR-0020 §D77 Shape 1.",
                        path, RULE_NAME, _STALE_PRE_WEEK_2_SOURCE,
                        RULE_SOURCE, _STALE_PRE_WEEK_2_SOURCE, RULE_SOURCE,
                    )
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
        ``linkedin-weekly-cap-100``) stay. Operators rarely invoke;
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
        ``linkedin-weekly-invite-cap``), then run downgrade — the
        renamed rule stays untouched. (Per-week-review follow-up
        documentation gap.)

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
MIGRATION: AddLinkedInInviteWeeklyCap = AddLinkedInInviteWeeklyCap()
