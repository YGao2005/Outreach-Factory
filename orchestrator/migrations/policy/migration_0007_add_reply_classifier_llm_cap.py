"""Policy migration 0007 — add reply-classifier LLM monthly cap rule.

Pillar D Week 6-8's per-channel-cap-analog policy migration. SIXTH
policy migration overall; FIRST policy migration of Pillar D. Mirrors
Week 7's ``policy/0002_add_li_invite_weekly_cap`` shape MOST CLOSELY:

* **Single rule per migration** (one ``add_rule_block_text`` call
  per file; not Week 11's bidirectional two-rule shape).
* **Same rule class** ``budget.window-cap`` (not Week 11's
  ``cooldown.cross-channel-touch``).
* **Commented factory rule** (operator uncomments to activate;
  matches Weeks 7-10's pattern, not Week 11's already-active
  pattern).

Structural divergences from Pillar C Weeks 7-10:

1. **First Pillar D policy migration.** Weeks 7-11 were Pillar C.
   Week 6-8 is the first Pillar D policy migration; the cap consumes
   ``cost_incurred`` events with ``source: "reply_classifier_llm"``
   (a Pillar D source — ADR-0025 §I7 reservation; ADR-0029 D126's
   emit-site contract). The structural mechanics inherit from
   ADR-0020 D72-D78.

2. **Source is a framework primitive, not a vendor.** Weeks 7-10's
   per-channel caps filter on ``source`` values that identify
   per-channel dispatcher emitters (``linkedin_invite``,
   ``linkedin_dm``, ``twitter_dm``, ``calendar_booking``). Week 6-8's
   cap filters on ``reply_classifier_llm`` — a framework-internal
   source naming an LLM-classifier-call event, not a vendor identifier.
   The pattern is uniform (any string source name works); the
   semantics differ (this is operator-side spend tracking on a
   framework subsystem, not platform-side cap matching).

3. **Window unit `window_days: 30` (monthly).** Distinct from Weeks
   7-9 (`window_days: 7` weekly) AND from Week 10 (`window_hours: 24`
   daily). Per ADR-0029 D127's calibration — operators budget LLM
   spend in monthly terms; the monthly window matches the operator's
   mental model. Daily would over-fire on traffic-concentrated days;
   weekly would feel arbitrary for a non-platform-side cap.

4. **`max_units: 50` calibrated against expected reply volume × LLM
   tokens-per-call.** the reference operator's expected ~30 long-tail uncategorized
   replies/month × 1 unit per call = 30 calls; 50 is a 1.5-2× safety
   margin. The math is documented inline (per ADR-0029 D127). Operators
   with higher reply volume tune up; warm-up phase operators tune down.

What it does
------------

For every ``*.yml`` file under ``ctx.policy_dir``:

1. Read the file. Refuse loud on unparseable / non-mapping / missing-
   ``rules:`` / rules-not-a-list shape (inherited from the Week 7
   per-week-review P2-A guard through Weeks 8-11).
2. Sanity-check the file's ``version:`` is in
   :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.
3. Idempotence check — if a rule with name
   ``reply-classifier-llm-monthly-cap`` is already present, skip.
4. Append the canonical rule to the ``rules:`` list via
   :func:`._policy_io.add_rule_block_text`.
5. Atomically write the file (tmp-then-rename + fsync).

The rule appended:

.. code-block:: yaml

    - name: reply-classifier-llm-monthly-cap
      type: budget.window-cap
      source: reply_classifier_llm
      window_days: 30
      max_units: 50
      reason: "Reply-classifier LLM monthly call cap (≈$0.03/month at Haiku 4.5 rates; operator-tunable in cooldowns.yml)"

The ``source`` field is the load-bearing per-source filter. Per
ADR-0006 §"Cost ledger contract" + ADR-0029 D126 — the
``BudgetWindowCapRule`` walks ``cost_incurred`` events whose
``source`` field equals the configured value. Pillar D Week 6-8's
``LLMFallbackClassifier`` emits these events at every successful LLM
call (per ADR-0029 D126).

Why `max_units: 50` (per ADR-0029 D127)
---------------------------------------

* the reference operator's normal cadence: ~100 replies/month inbound.
* Roughly 20-30% miss the rule-based classifier's pattern set → fall
  to ``uncategorized`` → trigger the LLM fallback. That's ~20-30
  calls/month under normal operation.
* `max_units: 50` is a 1.5-2.5× safety margin over normal cadence;
  catches a runaway-loop or inbox-flood scenario before it exhausts
  the budget.
* At Haiku 4.5 rates (~$0.0006 per call), 50 calls/month ≈ $0.03/month.
* Operators with higher reply volume tune up (e.g., ``max_units: 500``
  for ~1000 replies/month → ~$0.30/month).

Why `window_days: 30` (per ADR-0029 D127)
-----------------------------------------

* LLM cost is operator-budget-aggregated in MONTHLY terms.
* Daily window would over-fire on traffic-concentrated days.
* Weekly window is less natural than monthly for spend tracking.
* Per-run defense-in-depth is operator-deliberate via the existing
  ``BudgetPerRunCapRule`` class — no migration needed for that
  variant (ship-this-migration's-monthly-cap + add-per-run-rule-
  manually pattern).

Why `units` mode (not `usd` mode)
---------------------------------

* Operators reading the cap field see "50 calls/month" — easier
  mental model than "$0.03/month" (small dollar amounts are hard to
  reason about; call counts are tangible).
* Operators wanting $-based caps configure with ``max_usd: <amount>``
  mode by overriding the rule's field; the rule class supports both
  modes per ADR-0006 §"Mode selection".

Why commented factory rule (not active)
---------------------------------------

Per ADR-0029 D127 — matches Pillar C Weeks 7-10's pattern (Rules
12b/12c/12d/12e are all commented in
``config-template/cooldowns.example.yml``). The LLM fallback itself is
opt-in at the wiring layer (Pass G accepts a ``RuleBasedClassifier``
by default; the ``LLMFallbackClassifier`` is constructed at the
wiring site). The cap's commented-by-default posture matches the
opt-in posture — operators who don't enable the LLM fallback don't
see the cap fire.

The migration backfills the rule shape into operator-installed
``cooldowns.yml`` files so an operator who later opts into the LLM
fallback has the cap shape ready to uncomment.

Why no version bump
-------------------

Per ADR-0020 D75 / D76 (inherited by ADRs 0021-0024 + 0029 D127):
per-channel-cap-analog rule additions are CONTENT-ADDITIVE, not
SCHEMA-CHANGING. The engine's parser handles the new rule entry via
its existing ``budget.window-cap`` registry entry (registered since
Pillar A Week 4 per ADR-0006); no new field name, no new top-level
structure, no new file shape. The migration does NOT bump the file's
``version:`` and does NOT extend
:data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.

Why ``is_reversible=True``
--------------------------

:func:`._policy_io.add_rule_block_text` and
:func:`._policy_io.remove_rule_block_text` are paired inverses
verified by round-trip tests against the real factory
``cooldowns.example.yml``. ``downgrade`` removes the canonical-named
rule by name; operators who manually renamed (e.g.
``my-llm-budget``) keep their version through rollback.

Refuse-on-missing-policy-dir
----------------------------

Per :class:`MigrationRunner`, ``ctx.policy_dir`` defaults to
``<state_dir>/policies`` — always set. The meaningful failure is "the
path doesn't exist on disk." The migration refuses loud
(``FileNotFoundError``) rather than silently creating an empty policy
dir — same asymmetric-failure-cost calculus as policy/0001-0006.

Empty policy dir (zero ``.yml`` files) is NOT a refusal — it's a
legitimate state (a fresh OSS install with no policy customization).
``affected_count = 0`` + the runner marks applied.

See ADR-0029 for the full design rationale.
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
MIGRATION_ID = "0007_add_reply_classifier_llm_cap"


# ---------------------------------------------------------------------------
# The classifier-cap rule — single rule per migration (Week 7-10 shape)
# ---------------------------------------------------------------------------


# The canonical name for the rule. ``downgrade`` matches on it;
# idempotence checks match on it; the ``policy_blocked`` audit event's
# ``rule:`` field carries it.
RULE_NAME = "reply-classifier-llm-monthly-cap"

# The rule's `type:` discriminator into the engine's `RULE_REGISTRY`.
# `budget.window-cap` is the existing rule class — the migration adds
# an INSTANCE of it, not a new class. ADR-0006 §"BudgetWindowCapRule".
# Same rule class as Weeks 7-10 (Pillar C's per-channel caps).
RULE_TYPE = "budget.window-cap"

# The rule's `source:` filter — names the ``cost_incurred`` event
# source the rule's window aggregation considers. Per ADR-0029 D126 +
# ADR-0025 §I7's reservation, the LLM fallback's cost-event emit
# carries `source: "reply_classifier_llm"`. The cap's `source` filter
# matches this exact string.
RULE_SOURCE = "reply_classifier_llm"

# The rule's window — 30 days (monthly). Per ADR-0029 D127. Distinct
# from Weeks 7-9's `window_days: 7` weekly + Week 10's
# `window_hours: 24` daily; matches the operator's monthly LLM-spend
# mental model.
RULE_WINDOW_DAYS = 30

# The rule's per-call cap — 50 calls per month. Per ADR-0029 D127's
# calibration: ~30 expected calls × ~1.5-2× safety margin. At Haiku
# 4.5 rates ≈ $0.03/month. Operators tune in their cooldowns.yml.
RULE_MAX_UNITS = 50

# Human-readable reason surfaced in `policy_blocked` events. The cost
# reference is documentation for operators reading the rule + the
# event stream + the operator-onboarding context.
RULE_REASON = (
    "Reply-classifier LLM monthly call cap "
    "(≈$0.03/month at Haiku 4.5 rates; "
    "operator-tunable in cooldowns.yml)"
)

# The block of YAML text for the rule. Pre-formatted with leading
# 2-space indent (one level under `rules:`) per the
# `add_rule_block_text` contract. Constructed at module-load time so
# tests can inspect the literal bytes the migration writes.
#
# The format matches the factory's Rule 12b/12c/12d shape (per ADR-0020
# D72's per-week trajectory + the factory's existing per-channel-cap
# blocks) EXACTLY:
# - quote style on `name:` value: unquoted (the engine's safe_load
#   accepts all three forms per ADR-0012 D19; the unquoted form is
#   the factory convention).
# - `source:` value: unquoted.
# - `reason:` value: double-quoted (matches the factory's per-channel-
#   cap rules).
# - field ordering: name → type → source → window_days → max_units →
#   reason. Matches Weeks 7-10's field order for cross-migration
#   visual consistency.
RULE_BLOCK_TEXT = (
    f"  - name: {RULE_NAME}\n"
    f"    type: {RULE_TYPE}\n"
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

    Identical implementation to Weeks 7-11's policy migrations; the
    convention is one file per migration for grep + diff legibility.
    A future consolidation into a shared ``_policy_rule_helpers``
    module is a Pillar I OSS bring-up opportunity (deferred).
    """
    rules = data.get("rules")
    if not isinstance(rules, list):
        return False
    for r in rules:
        if isinstance(r, dict) and r.get("name") == name:
            return True
    return False


@dataclass
class AddReplyClassifierLlmCap:
    """Add the reply-classifier LLM monthly cap rule to operator policy files.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work happens in
    :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as
    :data:`MIGRATION`; the category sub-package's ``__init__.py``
    registers it into ``MIGRATIONS = [...]`` after policy/0006.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.POLICY
    description: str = (
        "Add reply-classifier LLM monthly cap rule "
        "(budget.window-cap, source: reply_classifier_llm, "
        "window_days: 30, max_units: 50) to every policy file's "
        "rules list — operator-tunable cap bounding LLM fallback "
        "classifier monthly call count (ADR-0029 D127); commented "
        "factory matches Week 7-10 pattern (operator uncomments to "
        "activate when enabling the LLM fallback wiring)"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Append the canonical rule to every policy file.

        Refuses with ``FileNotFoundError`` if ``ctx.policy_dir`` does
        not exist as a real directory on disk.

        Per-file outcomes:

        * Rule already present (canonical name) → skip file entirely
          (idempotence per name-match; Shape A per ADR-0029 D127
          §"Existing-operator seed").
        * Rule absent → insert via ``add_rule_block_text``.
        * Unparseable / non-mapping / missing ``rules:`` / non-list
          ``rules:`` / unsupported ``version:`` → refuse loud with
          :class:`PolicyFileError`.

        The ``affected_count`` returned counts the number of FILES
        that had the rule inserted — matches Weeks 7-11's per-file
        count semantics.

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

            # Defense-in-depth version check. The runner sequences
            # migrations so policy/0001-0006 have applied by the time
            # policy/0007 runs (files are at version 2). An operator
            # who somehow bypassed policy/0001 has v1 files — the
            # engine accepts both v1 and v2 per ADR-0012 D22.
            # Anything outside the SUPPORTED set is operator-corrupted
            # state.
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

            # The migration appends to the `rules:` list. Missing
            # `rules:` is operator-corrupted state — refuse rather
            # than silently creating.
            if "rules" not in data:
                raise PolicyFileError(
                    f"{path}: missing top-level `rules:` key. Every "
                    f"policy file must declare `rules:` even if "
                    f"empty (`rules: []`). Manual inspection required.",
                )

            # `rules:` present but not a list (e.g. `rules: null`,
            # `rules: some-string`) — operator-corrupted state.
            # Inherited Week 7 per-week-review P2-A guard through
            # Weeks 8-11.
            rules_value = data["rules"]
            if not isinstance(rules_value, list):
                raise PolicyFileError(
                    f"{path}: `rules:` is present but not a YAML "
                    f"list (got {type(rules_value).__name__}). "
                    f"Every policy file must declare `rules:` as a "
                    f"list (use `rules: []` for empty). Manual "
                    f"inspection required.",
                )

            # Per-rule idempotence check via rule-name lookup.
            # No stale-source warning path (matches ADR-0021 D81 +
            # 0022 D86 + 0023 D93 + 0024 D-N6 posture). Pillar I
            # doctor preflight is the future home for general per-
            # rule misconfig detection.
            if _rule_present_by_name(data, RULE_NAME):
                # Shape A — rule already canonical-named.
                already_present += 1
                continue

            # APPEND semantics (D73 inherited through Weeks 7-11) —
            # the new rule goes AFTER any existing operator-installed
            # rules.
            new_text = add_rule_block_text(text, RULE_BLOCK_TEXT)

            if not ctx.dry_run:
                write_policy_file_atomic(path, new_text)
            affected += 1

        verb = "would add" if ctx.dry_run else "added"
        ctx.logger.info(
            "%s reply-classifier LLM monthly cap rule to %d policy "
            "file(s) (%d already present)",
            verb, affected, already_present,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} reply-classifier LLM monthly cap rule to "
                f"{affected} policy file(s) ({already_present} "
                f"already at target)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove the canonical-named rule from every policy file.

        Inverse of :meth:`upgrade`. Removes ONLY the rule with the
        canonical name — operator-renamed versions (e.g.
        ``my-llm-budget``) stay. Operators rarely invoke; the
        framework requires ``allow_rollback=True`` explicitly.

        Per-file outcomes:

        * Canonical rule present → remove via
          ``remove_rule_block_text`` + atomic write.
        * Rule absent → skip (idempotent re-run).
        * ``rules:`` missing or not a list → refuse loud (operator-
          corrupted state).

        Operator-tuned-value loss
        -------------------------

        Downgrade removes by canonical NAME, not by structural
        identity. If the operator tuned the rule's ``max_units`` or
        ``window_days`` fields after the migration applied, those
        tuned values are LOST when downgrade removes the rule.
        Operators who want to preserve tuning + revert the migration's
        effect should rename their tuned rule first (any name not
        equal to the canonical name), then run downgrade — the
        renamed rule stays untouched. Same posture as Weeks 7-11
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
            "%s reply-classifier LLM monthly cap rule from %d policy "
            "file(s) (%d already absent)",
            verb, affected, already_absent,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} reply-classifier LLM monthly cap rule from "
                f"{affected} policy file(s) ({already_absent} "
                f"already absent)"
            ),
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: AddReplyClassifierLlmCap = AddReplyClassifierLlmCap()
