"""Policy migration 0005 — add ``calendar-booking-daily-cap`` rule.

Pillar C Week 10's per-channel policy migration. Fourth of Weeks 7-11's
per-channel cap migration range per ADR-0020 §D72's per-week trajectory.
Structurally mirrors Week 9's
:mod:`orchestrator.migrations.policy.migration_0004_add_tw_dm_weekly_cap`
modulo **TWO structural divergences** unique to the Calendar booking
channel:

1. **The window is DAILY (``window_hours: 24``), not WEEKLY**
   (``window_days: 7``). The engine's :class:`BudgetWindowCapRule`
   accepts both forms per ADR-0006 §"Three concrete rule classes"; Week
   10 is the first per-channel cap to use the hours form per the
   factory file's existing Rule 9 (commented Apollo daily cap)
   convention. The ``RULE_WINDOW_HOURS = 24`` constant replaces
   Weeks 7-9's ``RULE_WINDOW_DAYS = 7``; the ``RULE_BLOCK_TEXT`` format
   string's window-unit line changes from ``window_days: {…}`` to
   ``window_hours: {…}``.

2. **The failure-mode framing inverts from "platform-side enforcement"
   to "operator-side runaway loop."** Weeks 7-9 all defend against
   platform-side cold-outreach enforcement (LinkedIn account suspension;
   Twitter account flag). Cal.com has NO platform-side daily cap on
   shared booking links — the cap mitigates a dispatcher-in-bad-loop
   scenario where the operator's calendar surface gets overwhelmed by
   too many link-shares in one batch run. ADR-0006 Rule 11
   (``per-run-spend-cap``) is the structurally adjacent existing rule —
   also a runaway-loop guard. The ``RULE_MAX_UNITS = 10`` default
   reflects this fundamentally different calibration (the reference operator's normal
   ~3-5/day cadence with 2x-3x headroom; catches runaway loops at ~10x
   normal cadence).

The shared primitives (:func:`._policy_io.add_rule_block_text` /
:func:`._policy_io.remove_rule_block_text`) land in Week 7; Week 10
consumes them unchanged. The primitives are window-unit-agnostic —
they operate on text-level YAML, not on rule-class semantics.

What it does
------------

For every ``*.yml`` file under ``ctx.policy_dir``:

1. Read the file. Refuse loud on unparseable / non-mapping / missing-
   ``rules:`` / rules-not-a-list shape (inherited from Week 7's
   per-week-review P2-A guard through Weeks 8 + 9).
2. Sanity-check the file's ``version:`` is in
   :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.
   Refuse loud on any other version (operator-corrupted state).
3. Idempotence check: if a rule with the canonical name
   ``calendar-booking-daily-cap`` is already present, skip the file.
   Per ADR-0020 D74 (rule-name lookup; inherited by ADRs 0021 + 0022 +
   0023).
4. Append the canonical rule to the ``rules:`` list via
   :func:`._policy_io.add_rule_block_text` (APPEND semantics per
   ADR-0020 D73 — operator-installed-first ordering preserved).
5. Atomically write the file (tmp-then-rename + fsync).

The rule appended:

.. code-block:: yaml

    - name: calendar-booking-daily-cap
      type: budget.window-cap
      block_when:
        channel: calendar
      source: calendar_booking
      window_hours: 24
      max_units: 10
      reason: "Calendar booking daily cap (operator-deliberate guardrail; ...)"

The ``source: calendar_booking`` value is the load-bearing field that
makes the rule actually fire on real ledger events. Per ADR-0019 D65,
Pillar C Week 6's Calendar-booking dispatcher emits ``cost_incurred``
events with ``source="calendar_booking"`` at link-share time (intent-
time per ADR-0019 D66's asymmetric two-phase shape; the paired
``calendar_booking_confirmed`` arrives later via webhook + does NOT
re-emit cost). The rule's ``source:`` field MUST match the
dispatcher's emit value — otherwise the rule activates but reports
zero usage, silently allowing over-quota link shares (the exact
failure mode the cap exists to prevent).

The ``block_when.channel: calendar`` value distinguishes Calendar
booking sends from LinkedIn + Twitter sends. Per ADR-0019 D65,
Calendar's channel value is ``calendar`` (distinct from LinkedIn's
``linkedin`` per Weeks 7-8 + Twitter's ``twitter`` per Week 9); the
cross-channel rule's ``consider_channels:`` matches the string
exactly, so Calendar is an independent join target.

Why ``max_units: 10`` (and not 50 like Weeks 7-9)
--------------------------------------------------

Per ADR-0023 D89. Cal.com's enforcement surface is FUNDAMENTALLY
DIFFERENT from LinkedIn / Twitter's — there is no platform-side
daily cap on shared booking links. The cap mitigates the
**operator-side runaway loop** failure mode: a dispatcher-in-bad-loop
sharing 50 booking links in one batch run overwhelms the operator's
calendar (recipients booking overlapping slots; calendar surface
saturation; reputational damage with recipients who can't get the
slot they expected).

Asymmetric failure-cost calculus:

* **False-block (cap too low + operator hits 10 in one day):** one-line
  YAML edit raises the cap; operator-time cost ~30 seconds. Operators
  with high booking volume (~15-20/day routinely) tune up.
* **False-allow (cap too high + dispatcher-in-bad-loop fires):** 50
  booking links shared in one batch run; 5 recipients book overlapping
  slots; operator's calendar surfaces 5 confirmed bookings + 45
  "fully booked" frustrations. Operator-time cost: hours-to-days of
  reconciliation + reputational damage.

Calibration math: the reference operator's current Cal.com booking-link cadence is
~3-5/day. A cap at 10 gives 2-3x headroom for normal use + catches a
dispatcher-in-bad-loop scenario at ~10x normal cadence (a runaway
sharing 50 links would fire the cap after 10).

The cap is operator-deliberate — operators reading the
``policy_blocked`` event's ``reason:`` field should understand the
cap is an operator-deliberate safety guardrail, NOT a platform-
published soft limit (unlike LinkedIn's 100/week per ADR-0008). The
rule's ``reason:`` text names "operator-deliberate guardrail against
runaway link-sharing loops" explicitly.

The factory's commented Rule 12e documents the shape for new
operators alongside Rules 12b (LinkedIn invite) + 12c (LinkedIn DM) +
12d (Twitter DM) — Pillar C's per-channel symmetry per ADR-0023 D92.
Rule 12e's comment is meaningfully longer than Rules 12b-d because
the operator-side-runaway-loop framing requires explicit explanation.

Why ``window_hours: 24`` (and not ``window_days: 1``)
------------------------------------------------------

Per ADR-0023 D90. The engine accepts both forms equivalently per
ADR-0006 §"Three concrete rule classes"; the choice is operator-
readability. The factory file's Rule 9 (commented Apollo daily cap
example) uses ``window_hours: 24`` — the convention is "daily caps
spell out hours; weekly caps spell out days." A rule that reads
``window_hours: 24`` is self-evidently a 24-hour rolling window at
first glance; ``window_days: 1`` requires reading the numeric value
to determine the cap's scope.

The engine treats the two forms identically (both convert to a
``window_seconds`` internal value); the cosmetic choice favors the
factory file's existing convention.

Why no stale-source detection (unlike Week 7's policy/0002)
-----------------------------------------------------------

Per ADR-0023 D93 (same posture as ADRs 0021 D81 + 0022 D86). Week 7's
policy/0002 detects + warns on operators who have the canonical
``linkedin-weekly-invite-cap`` rule with a ``source: linkedin`` field
(the pre-Pillar-C-Week-2 ADR-0008 factory shape — see ADR-0020 §D77
Shape 1). The warning surfaces an inert-rule misconfig.

Week 10 has no analogous staleness path. The Calendar booking
dispatcher (ADR-0019) shipped 2026-05-22, AFTER ADR-0015 D40's split-
source convention was established 2026-05-20. There has never been a
factory-shipped ``calendar-booking-daily-cap`` rule with any non-
canonical ``source:`` field — the canonical source from day one is
``calendar_booking``. No operator could have copied a stale factory
shape; no warning is needed. ADR-0023 §"Existing-operator seed" is
shorter than ADR-0020's by exactly Shape 1 (same shape as ADRs 0021
+ 0022's seed).

Why no version bump
-------------------

Per ADR-0020 D75 / D76 (inherited by ADRs 0021 + 0022 + 0023):
per-channel rule additions are CONTENT-ADDITIVE, not SCHEMA-CHANGING.
The engine's parser handles the new rule entry via its existing
``budget.window-cap`` registry entry; no new field name, no new
top-level structure, no new file shape. The migration does NOT bump
the file's ``version:`` and does NOT extend
:data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.

The ``window_hours:`` parameter is NOT a new field — the engine has
supported both ``window_hours:`` AND ``window_days:`` since Pillar A
Week 1 per ADR-0006; Week 10 is just the first per-channel cap
migration to exercise the hours form.

Why ``is_reversible=True``
--------------------------

:func:`._policy_io.add_rule_block_text` and
:func:`._policy_io.remove_rule_block_text` are paired inverses
verified by round-trip tests against the real factory
``cooldowns.example.yml``. ``downgrade`` removes the rule by
canonical name; operators who manually added a renamed version (e.g.
``calendar-cap-10``) keep their version through rollback.

Refuse-on-missing-policy-dir
----------------------------

Per :class:`MigrationRunner`, ``ctx.policy_dir`` defaults to
``<state_dir>/policies`` — always set. The meaningful failure is "the
path doesn't exist on disk." The migration refuses loud
(``FileNotFoundError``) rather than silently creating an empty policy
dir — same asymmetric-failure-cost calculus as ``policy/0001`` +
``policy/0002`` + ``policy/0003`` + ``policy/0004``.

Empty policy dir (zero ``.yml`` files) is NOT a refusal — it's a
legitimate state (a fresh OSS install with no policy customization).
``affected_count = 0`` + the runner marks applied.

See ADR-0023 for the full design rationale.
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
MIGRATION_ID = "0005_add_calendar_booking_daily_cap"

# The canonical rule the migration adds. The `name` field is the
# load-bearing identifier — `downgrade` matches on it; idempotence
# checks match on it; the `policy_blocked` audit event's `rule:` field
# carries it.
RULE_NAME = "calendar-booking-daily-cap"

# The rule's `type:` discriminator into the engine's
# `RULE_REGISTRY`. `budget.window-cap` is the existing rule class —
# the migration adds an INSTANCE of it, not a new class. ADR-0006
# §Decision item "Three concrete rule classes". Same class Weeks 7-9
# use; all four per-channel rules are independent instances filtered
# by `source:` + `block_when.channel:` + (now) window unit.
RULE_TYPE = "budget.window-cap"

# The rule's `source:` filter — which `cost_incurred` events it
# aggregates. Pillar C Week 6's Calendar-booking dispatcher emits
# events with `source="calendar_booking"` per ADR-0019 D65. The rule
# must match exactly. Distinct from `linkedin_invite` (Week 7) +
# `linkedin_dm` (Week 8) + `twitter_dm` (Week 9) per ADR-0015 D40's
# split-source convention.
RULE_SOURCE = "calendar_booking"

# The rule's `block_when.channel:` filter — only fires the rule when
# the send-gate's `ctx.channel` is "calendar". An email / LinkedIn /
# Twitter send with the same Calendar booking history is allowed
# (channel mismatch → rule not applicable). Per ADR-0003 + ADR-0019
# D65. Distinct from LinkedIn's `channel: linkedin` (Weeks 7 + 8) and
# Twitter's `channel: twitter` (Week 9) because Calendar bookings have
# their own enforcement surface (the operator's own calendar surface,
# not a platform-side rate-limit pool — see ADR-0023 D89 for the
# failure-mode framing).
RULE_BLOCK_WHEN_CHANNEL = "calendar"

# The rule's window — 24 hours (NOT 7 days like Weeks 7-9). Per
# ADR-0023 D90: daily caps spell out hours; the factory file's Rule 9
# (commented Apollo daily cap) is the precedent. The engine accepts
# both `window_hours:` AND `window_days:` equivalently per ADR-0006
# §"Three concrete rule classes"; the cosmetic choice favors operator-
# facing semantic clarity (the hours form makes the daily nature
# explicit at the rule-entry level).
RULE_WINDOW_HOURS = 24

# The rule's quota — 10 link-shares per 24 hours. Per ADR-0023 D89:
# Cal.com has NO platform-side daily cap; the cap mitigates the
# OPERATOR-SIDE runaway-loop failure mode. the reference operator's normal Cal.com
# booking-link cadence is ~3-5/day; the cap at 10 gives 2-3x headroom
# for normal use + catches a dispatcher-in-bad-loop scenario at ~10x
# normal cadence (a runaway sharing 50 links would fire the cap after
# 10). Operators with high booking volume (~15-20/day routinely) tune
# up; operators in the very-low-volume warm-up phase can tune down to
# 5. The factory's 10 covers the median use case + the reference operator's current
# operator profile.
#
# IMPORTANT: this default is fundamentally different from Weeks 7-9's
# 50 / 100 because the failure mode is different. Weeks 7-9 defend
# against platform-side enforcement (rates at which the platform
# starts throttling / suspending the account); Week 10 defends against
# operator-side runaway (rates at which the operator's own calendar
# surface gets overwhelmed). Cross-channel-consistency in the cap
# VALUE is NOT a goal here — cross-channel-consistency in the cap
# SHAPE (rule class + insertion semantics + idempotence) is the goal.
RULE_MAX_UNITS = 10

# Human-readable reason surfaced in `policy_blocked` events. Names the
# operator-deliberate-safety-guardrail framing explicitly so operators
# inspecting the event stream understand the cap is NOT a platform-
# published limit. Per ADR-0023 D89 emphasis on "operator-deliberate."
RULE_REASON = (
    "Calendar booking daily cap (operator-deliberate guardrail "
    "against runaway link-sharing loops; Cal.com has NO platform-side "
    "daily cap — this default protects the operator's own calendar "
    "surface from saturation when a dispatcher loops on overlapping "
    "cohorts; 10/day default ≈ 2-3x normal cadence; operator-tunable "
    "in cooldowns.yml)"
)

# The block of YAML text the migration inserts. Pre-formatted with
# leading 2-space indent (one level under `rules:`) per the
# `add_rule_block_text` contract. Constructed at module-load time so
# tests can inspect the literal bytes the migration writes.
#
# NOTE the window-unit divergence from Weeks 7-9: this template uses
# `window_hours: {RULE_WINDOW_HOURS}` (NOT `window_days: {…}`). The
# `RULE_WINDOW_HOURS` constant replaces the `RULE_WINDOW_DAYS` constant
# Weeks 7-9 used; the format string's window-unit line follows.
RULE_BLOCK_TEXT = (
    f"  - name: {RULE_NAME}\n"
    f"    type: {RULE_TYPE}\n"
    f"    block_when:\n"
    f"      channel: {RULE_BLOCK_WHEN_CHANNEL}\n"
    f"    source: {RULE_SOURCE}\n"
    f"    window_hours: {RULE_WINDOW_HOURS}\n"
    f"    max_units: {RULE_MAX_UNITS}\n"
    f'    reason: "{RULE_REASON}"\n'
)


def _rule_present_by_name(data: dict, name: str) -> bool:
    """Whether ``data["rules"]`` contains an entry with ``name: <name>``.

    Uses the parsed-dict view (cheap, no regex). Quote-style is
    irrelevant — ``yaml.safe_load`` normalizes ``- name: foo`` /
    ``- name: 'foo'`` / ``- name: "foo"`` all to the same string.

    Returns ``False`` if ``rules`` is missing, ``None``, or empty.

    Identical implementation to Weeks 7-9's policy migrations; the four
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
class AddCalendarBookingDailyCap:
    """Add the Calendar booking daily cap rule to every policy file.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work happens in
    :meth:`upgrade` and :meth:`downgrade`.

    Constructed once at module import time and exported as
    :data:`MIGRATION`; the category sub-package's ``__init__.py``
    registers it into ``MIGRATIONS = [...]`` after policy/0004.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.POLICY
    description: str = (
        "Add calendar-booking-daily-cap rule (budget.window-cap, 10 "
        "link-shares/24h on source=calendar_booking) to every policy "
        "file's rules list — activates the per-channel daily cap for "
        "the Calendar-booking dispatcher (ADR-0019) against the "
        "operator-side runaway-loop failure mode (NOT a platform-side "
        "enforcement guard like Weeks 7-9); operator-tunable"
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

            # Defense-in-depth version check. By the time policy/0005
            # runs through the runner, policy/0001 + 0002 + 0003 + 0004
            # have applied (the runner sequences migrations) so files
            # are at version 2. An operator who somehow bypassed
            # policy/0001 has v1 files — the engine accepts both v1
            # and v2 per ADR-0012 D22, so we accept both too. Anything
            # outside the SUPPORTED set is operator-corrupted state.
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
            # (Inherited from Week 7's per-week-review P2-A guard
            # through Weeks 8 + 9.)
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
            # inherited by ADRs 0021 + 0022 + 0023). Operators who
            # manually added the canonical-named rule keep their
            # version — including any threshold tuning. The migration
            # does NOT overwrite operator-tuned values.
            #
            # No stale-source warning path here (per ADR-0023 D93,
            # same posture as ADRs 0021 D81 + 0022 D86): there has
            # never been a factory-shipped `calendar-booking-daily-
            # cap` rule with a non-canonical source, so no operator
            # could have copied a stale shape. Contrast with
            # policy/0002 which DOES warn for `source: linkedin` per
            # ADR-0020 §D77 Shape 1.
            if _rule_present_by_name(data, RULE_NAME):
                already_present += 1
                continue

            # Append the rule. The `add_rule_block_text` primitive
            # handles inline-empty + multi-line forms uniformly; the
            # APPEND semantics put the new rule AFTER any existing
            # operator-installed rules (D73). The primitive is window-
            # unit-agnostic — operates on text-level YAML, not on
            # rule-class semantics; Week 10's `window_hours: 24` line
            # is just bytes the primitive inserts as-is.
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
        ``calendar-cap-10``) stay. Operators rarely invoke; the
        framework requires ``allow_rollback=True`` explicitly.

        Per-file outcomes:

        * Canonical rule present → remove via
          ``remove_rule_block_text`` + atomic write.
        * Canonical rule absent → skip (idempotent re-run).
        * ``rules:`` missing or not a list → refuse loud
          (operator-corrupted state).

        Operator-tuned-value loss
        -------------------------

        Downgrade removes by canonical NAME, not by structural identity.
        If the operator tuned the rule's ``max_units``, ``window_hours``,
        or ``reason`` fields after the migration applied, those tuned
        values are LOST when downgrade removes the rule. Operators who
        want to preserve tuning + revert the migration's effect should
        rename their tuned rule first (any name not equal to
        ``calendar-booking-daily-cap``), then run downgrade — the
        renamed rule stays untouched. Same posture as Weeks 7-9
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
MIGRATION: AddCalendarBookingDailyCap = AddCalendarBookingDailyCap()
