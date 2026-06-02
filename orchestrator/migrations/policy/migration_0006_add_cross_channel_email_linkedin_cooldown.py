"""Policy migration 0006 — add cross-channel email↔LinkedIn cooldown rules.

Pillar C Week 11's per-channel policy migration. Fifth + FINAL of
Weeks 7-11's per-channel cap migration range per ADR-0020 §D72's
per-week trajectory. Structurally **divergent from Weeks 7-10** on a
DIFFERENT axis from Week 10's: **TWO rules per migration**; **different
rule class** (``cooldown.cross-channel-touch`` vs ``budget.window-cap``);
**different field semantics** (``consider_channels:`` vs ``source:``);
**factory rules ALREADY ACTIVE** in ``config-template/cooldowns.example.yml``
since Pillar A (lines 89-108) — NOT commented like Rules 12b / 12c /
12d / 12e.

Structural divergences from Weeks 7-10
--------------------------------------

1. **TWO rules per migration (not one).** The bidirectional shape per
   ADR-0003: one rule blocking LinkedIn sends when a prior email touch
   landed within 14d (``cross-channel-email-suppresses-linkedin``), AND
   one rule blocking email sends when a prior LinkedIn touch landed
   within 14d (``cross-channel-linkedin-suppresses-email``). Both rules
   MUST ship in one migration commit because operators with only one
   direction installed have a unidirectional cooldown that's
   structurally incomplete (email gates LinkedIn but not vice versa, or
   vice versa) — a Pillar A R011 (cross-channel double-engagement)
   regression. Per ADR-0024 D-N1.

2. **Different rule class: ``cooldown.cross-channel-touch``.** Per
   ADR-0003. NOT ``budget.window-cap`` like Weeks 7-10. The rule class
   has been registered since Pillar A Week 1; no engine code change.
   The migration writes INSTANCES of this rule class.

3. **Different field semantics: ``consider_channels:`` instead of
   ``source:``.** Per ADR-0003. The cross-channel rule queries the
   LEDGER for prior touches in ``consider_channels:`` channels, NOT
   ``cost_incurred`` events with matching ``source:``. The
   ``block_when.channel:`` field filters when the rule fires (matches
   the send-gate's channel); ``consider_channels:`` filters which
   ledger events the rule considers in its lookback.

4. **No ``max_units:``, no ``window_hours:`` vs ``window_days:``
   divergence.** The rule uses ``window_days: 14`` (matching the
   factory's existing 14-day shape per ADR-0003 §Decision). No
   units-vs-USD-mode question; no max-units calibration. The
   cross-channel-touch rule is structurally simpler than the per-
   channel cap rules at the field level — there is no "count of
   events" threshold; ANY confirmed touch on a considered channel
   within the window blocks.

5. **Factory rules ALREADY ACTIVE.** Rules 5 + 6 in ``config-template/
   cooldowns.example.yml`` ship ACTIVE (uncommented) since Pillar A.
   The migration's job is to backfill operators who don't have these
   rules in their installed ``cooldowns.yml`` — NOT to activate a
   commented factory rule (which is what Weeks 7-10 did). Per ADR-0024
   D-N3. **This is the FIRST per-channel migration where the factory
   rules pre-existed the migration**; operator-side-onboarding contrast
   with Weeks 7-10 is structural.

6. **Different failure-mode framing: cross-channel double-engagement
   (R011) — recipient-side coordination signal.** Different from BOTH
   Weeks 7-9 (platform-side enforcement) AND Week 10 (operator-side
   runaway loop). A recipient receiving an email + a LinkedIn DM
   within 14 days from the same sender perceives coordinated outreach
   that damages the operator's reputation regardless of platform-side
   enforcement OR operator-side runaway loops. The cap mitigates a
   PERCEPTION-LAYER failure mode the prior weeks' caps don't address.

What it does
------------

For every ``*.yml`` file under ``ctx.policy_dir``:

1. Read the file. Refuse loud on unparseable / non-mapping / missing-
   ``rules:`` / rules-not-a-list shape (inherited from Week 7's per-
   week-review P2-A guard through Weeks 8 + 9 + 10).
2. Sanity-check the file's ``version:`` is in
   :data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.
   Refuse loud on any other version (operator-corrupted state).
3. **TWO idempotence checks** — once per rule. If a rule with name
   ``cross-channel-email-suppresses-linkedin`` is already present, do
   NOT re-insert it. If a rule with name
   ``cross-channel-linkedin-suppresses-email`` is already present, do
   NOT re-insert it. **Transitional state (one direction present, the
   other absent) is normal** (Shape B per ADR-0024 §"Existing-operator
   seed") — the migration inserts only the missing direction(s).
4. Append the missing canonical rule(s) to the ``rules:`` list via
   :func:`._policy_io.add_rule_block_text`. When both rules need
   inserting, the primitive is called TWICE in sequence — the second
   insertion's ``text`` argument is the result of the first insertion.
   Verified composition: see ``tests/test_migrations_policy_0006.py::
   TestSequentialAddRuleBlockTextComposition``.
5. Atomically write the file (tmp-then-rename + fsync).

The rules appended (in order Rule A → Rule B for determinism):

.. code-block:: yaml

    - name: cross-channel-email-suppresses-linkedin
      type: cooldown.cross-channel-touch
      block_when:
        channel: linkedin
      consider_channels: [email]
      window_days: 14
      reason: "Prior email touch within 14d; LinkedIn would look coordinated"

    - name: cross-channel-linkedin-suppresses-email
      type: cooldown.cross-channel-touch
      block_when:
        channel: email
      consider_channels: [linkedin]
      window_days: 14
      reason: "Prior LinkedIn touch within 14d; email would look coordinated"

The ``consider_channels:`` field is the load-bearing cross-channel join
target. Per ADR-0003 §Decision "Channel-as-join": the rule queries
ledger events whose ``channel`` field is in ``consider_channels`` AND
whose ``type`` ends with ``"_confirmed"`` — the rule fires regardless
of dispatcher emission source, because cross-channel coordination is a
RECIPIENT-side perception layer (not an operator-side cost-tracking
layer per Weeks 7-10's ``source:`` filter).

Why ``window_days: 14`` (matching the factory's existing shape)
---------------------------------------------------------------

Per ADR-0024 D-N5. The factory's pre-existing Rules 5 + 6 (lines 89-
108 of ``config-template/cooldowns.example.yml``) ship with
``window_days: 14`` since Pillar A Week 2 (per ADR-0003 §Decision's
"Two factory rules ship" table). The migration's RULE_BLOCK_TEXT
matches exactly so operators who hand-installed the factory rule shape
have a name-match idempotence skip (per D-N6).

The 14-day window is calibrated against the operator-and-recipient
coordination-perception horizon: a recipient who got an email 14 days
ago + receives a LinkedIn DM today perceives "still recent enough to
be coordinated"; a recipient who got an email 30 days ago likely does
not. The 14-day boundary matches the existing
``domain-cooldown.window_days: 14`` (factory Rule 4) for cross-rule
consistency — both rules use the same coordination horizon.

Why bundled bidirectional shape
-------------------------------

Per ADR-0024 D-N1. Splitting into two migrations
(``0006_add_cross_channel_email_suppresses_linkedin`` +
``0007_add_cross_channel_linkedin_suppresses_email``) creates a
transitional operator state where the first migration is applied but
the second isn't — email touches block LinkedIn sends but LinkedIn
touches don't block email sends. That's R011-regression (cross-channel
double-engagement) for operators who pulled code mid-migration-pair.
Bundling avoids the regression window.

Operators who manually installed one direction before pulling Week 11
(plausible per ADR-0024 §"Existing-operator seed" Shape B —
``cross-channel-email-suppresses-linkedin`` from a hand-rolled cooldowns
.yml predating Pillar A; ``cross-channel-linkedin-suppresses-email``
not yet installed) get the OTHER direction inserted alongside their
existing rule. The migration's name-match idempotence (D-N6) inserts
only what's missing.

Why no stale-considered-channels detection (Pillar I doctor instead)
--------------------------------------------------------------------

Per ADR-0024 D-N6. Unlike the ``source:`` field on Weeks 7-10's
per-channel cap rules (where ADR-0020 §D77 Shape 1 stale-source path
exists for Week 7 only), the ``consider_channels:`` field has NO
analogous staleness shape: the factory rules' ``consider_channels:``
value has always been ``[email]`` (Rule 5) and ``[linkedin]`` (Rule 6)
since Pillar A. Operators with hand-edited variants (e.g.
``consider_channels: [email, twitter]`` for a custom multi-channel
cooldown) are operator-deliberate; the migration's name-match
idempotence skips on canonical name; the migration does NOT inspect
``consider_channels:`` values.

The structural intervention against a future contributor reflexively
adding a "stale considered_channels detection" branch by mirroring
policy/0002 is the ``TestNoStaleConsiderChannelsWarning`` invariant
test class — same pattern as Weeks 8-10's ``TestNoStaleSourceWarning``,
extended to the cross-channel field.

Pillar I's doctor preflight (deferred per ADR-0024 D-N6 +
ADR-0023 D93) is the future home for general per-rule misconfig
detection.

Why no version bump
-------------------

Per ADR-0020 D75 / D76 (inherited by ADRs 0021 + 0022 + 0023 + 0024):
per-channel rule additions are CONTENT-ADDITIVE, not SCHEMA-CHANGING.
The engine's parser handles the new rule entries via its existing
``cooldown.cross-channel-touch`` registry entry (registered since
Pillar A Week 2 per ADR-0003); no new field name, no new top-level
structure, no new file shape. The migration does NOT bump the file's
``version:`` and does NOT extend
:data:`orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`.

The ``consider_channels:`` field is NOT a new field — the engine has
supported it since Pillar A Week 2 per ADR-0003. Week 11 is the first
per-channel policy migration to write rules that USE it (Weeks 7-10
all used ``source:``).

Why ``is_reversible=True``
--------------------------

:func:`._policy_io.add_rule_block_text` and
:func:`._policy_io.remove_rule_block_text` are paired inverses verified
by round-trip tests against the real factory ``cooldowns.example.yml``.
``downgrade`` removes BOTH canonical-named rules by name; operators who
manually added renamed versions (e.g.
``my-custom-email-linkedin-cooldown``) keep their versions through
rollback. The two rule-removal calls inside one ``downgrade`` are
independently idempotent — each remove call is a no-op if the rule is
already absent.

Refuse-on-missing-policy-dir
----------------------------

Per :class:`MigrationRunner`, ``ctx.policy_dir`` defaults to
``<state_dir>/policies`` — always set. The meaningful failure is "the
path doesn't exist on disk." The migration refuses loud
(``FileNotFoundError``) rather than silently creating an empty policy
dir — same asymmetric-failure-cost calculus as ``policy/0001`` +
``policy/0002`` + ``policy/0003`` + ``policy/0004`` + ``policy/0005``.

Empty policy dir (zero ``.yml`` files) is NOT a refusal — it's a
legitimate state (a fresh OSS install with no policy customization).
``affected_count = 0`` + the runner marks applied.

See ADR-0024 for the full design rationale.
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
MIGRATION_ID = "0006_add_cross_channel_email_linkedin_cooldown"

# ---------------------------------------------------------------------------
# Rule A — email touch suppresses subsequent LinkedIn send
# ---------------------------------------------------------------------------

# The canonical name for Rule A. ``downgrade`` matches on it; idempotence
# checks match on it; the ``policy_blocked`` audit event's ``rule:``
# field carries it. Matches the factory's Rule 5 name (line 89 of
# ``config-template/cooldowns.example.yml``) so operators who hand-
# installed the factory shape have name-match idempotence skip.
RULE_A_NAME = "cross-channel-email-suppresses-linkedin"

# The rule's `type:` discriminator into the engine's `RULE_REGISTRY`.
# `cooldown.cross-channel-touch` is the existing rule class — the
# migration adds an INSTANCE of it, not a new class. ADR-0003 §Decision
# "New rule class CrossChannelTouchRule". Distinct from Weeks 7-10's
# `budget.window-cap` (a fundamentally different rule class with
# different fields: max_units / max_usd + source / window_days +
# window_hours).
RULE_A_TYPE = "cooldown.cross-channel-touch"

# The rule's `block_when.channel:` filter — fires the rule when the
# send-gate's `ctx.channel` is "linkedin". A LinkedIn send (invite OR
# DM — both carry `channel: linkedin` per Weeks 7-8) with a prior email
# touch in the lookback window is blocked. An email send with a prior
# email touch is NOT blocked by Rule A (the firing channel filter
# matches LinkedIn only); same-channel coordination is the job of the
# same-channel rules (Rule 1 no-double-cold-pitch + Rule 4
# domain-cooldown). Per ADR-0003 §Decision.
RULE_A_BLOCK_WHEN_CHANNEL = "linkedin"

# The rule's `consider_channels:` filter — which ledger events the rule
# queries in its lookback. `[email]` means: only EMAIL touches block a
# LinkedIn send. Per ADR-0003 §Decision "Channel-as-join". This is the
# load-bearing cross-channel-coordination field; the LinkedIn send-gate
# sees a confirmed email touch within `window_days` and refuses.
#
# Distinct semantically from Weeks 7-10's `source:` field: source filters
# `cost_incurred` events by emitter (per ADR-0006); consider_channels
# filters `*_confirmed` ledger events by their event-level `channel:`
# field (per ADR-0014 D33). The two are NOT interchangeable; the cross-
# channel rule's failure mode (recipient perception of coordination)
# warrants ledger-event-level filtering, not cost-event-level.
RULE_A_CONSIDER_CHANNELS = ["email"]

# The rule's window — 14 days. Per ADR-0024 D-N5. Matches the factory's
# Rule 5 + Rule 6 since Pillar A (ADR-0003 §Decision "Two factory rules
# ship") + matches Rule 4 (domain-cooldown.window_days: 14) for cross-
# rule consistency.
RULE_A_WINDOW_DAYS = 14

# Human-readable reason surfaced in `policy_blocked` events. Matches
# the factory file's Rule 5 reason text verbatim so operators reading
# the event stream see consistent messaging between the factory + the
# migration. Per ADR-0024 D-N4.
RULE_A_REASON = (
    "Prior email touch within 14d; LinkedIn would look coordinated"
)

# The block of YAML text for Rule A. Pre-formatted with leading 2-space
# indent (one level under `rules:`) per the `add_rule_block_text`
# contract. Constructed at module-load time so tests can inspect the
# literal bytes the migration writes.
#
# NOTE the format matches the factory's Rule 5 (lines 89-95 of
# `config-template/cooldowns.example.yml`) EXACTLY:
# - quote style on `name:` value: unquoted (the engine's safe_load
#   accepts all three forms per ADR-0012 D19; the unquoted form is
#   the factory convention).
# - `consider_channels: [<value>]` uses YAML flow-style list notation
#   (single inline scalar in brackets) matching the factory exactly.
#   The engine's `CrossChannelTouchRule.from_yaml` accepts both flow-
#   style + block-style equivalently per yaml.safe_load semantics.
# - `reason:` value uses double-quoted form matching the factory.
RULE_A_BLOCK_TEXT = (
    f"  - name: {RULE_A_NAME}\n"
    f"    type: {RULE_A_TYPE}\n"
    f"    block_when:\n"
    f"      channel: {RULE_A_BLOCK_WHEN_CHANNEL}\n"
    f"    consider_channels: [{RULE_A_CONSIDER_CHANNELS[0]}]\n"
    f"    window_days: {RULE_A_WINDOW_DAYS}\n"
    f'    reason: "{RULE_A_REASON}"\n'
)


# ---------------------------------------------------------------------------
# Rule B — LinkedIn touch suppresses subsequent email send (mirror of A)
# ---------------------------------------------------------------------------

# The canonical name for Rule B. Matches the factory's Rule 6 name
# (line 102 of `config-template/cooldowns.example.yml`).
RULE_B_NAME = "cross-channel-linkedin-suppresses-email"

# Same rule class as Rule A — both directions of the bidirectional pair
# instantiate `CrossChannelTouchRule`. Per ADR-0003.
RULE_B_TYPE = "cooldown.cross-channel-touch"

# The MIRROR of Rule A's block_when.channel: Rule A fires on linkedin
# (when a prior email touch landed); Rule B fires on email (when a
# prior linkedin touch landed). The two rules together form the
# bidirectional pair per ADR-0003 §Decision.
RULE_B_BLOCK_WHEN_CHANNEL = "email"

# The MIRROR of Rule A's consider_channels: Rule A considers email
# events; Rule B considers linkedin events. Operators reading the YAML
# should perceive the bidirectional symmetry at a glance.
RULE_B_CONSIDER_CHANNELS = ["linkedin"]

# Same window as Rule A — bidirectional pair shares the coordination
# horizon. ADR-0024 D-N5.
RULE_B_WINDOW_DAYS = 14

# Matches the factory file's Rule 6 reason text verbatim. ADR-0024
# D-N4.
RULE_B_REASON = (
    "Prior LinkedIn touch within 14d; email would look coordinated"
)

# The block of YAML text for Rule B. Pre-formatted matching Rule A's
# shape exactly modulo the channel-pair fields.
RULE_B_BLOCK_TEXT = (
    f"  - name: {RULE_B_NAME}\n"
    f"    type: {RULE_B_TYPE}\n"
    f"    block_when:\n"
    f"      channel: {RULE_B_BLOCK_WHEN_CHANNEL}\n"
    f"    consider_channels: [{RULE_B_CONSIDER_CHANNELS[0]}]\n"
    f"    window_days: {RULE_B_WINDOW_DAYS}\n"
    f'    reason: "{RULE_B_REASON}"\n'
)


def _rule_present_by_name(data: dict, name: str) -> bool:
    """Whether ``data["rules"]`` contains an entry with ``name: <name>``.

    Uses the parsed-dict view (cheap, no regex). Quote-style is
    irrelevant — ``yaml.safe_load`` normalizes ``- name: foo`` /
    ``- name: 'foo'`` / ``- name: "foo"`` all to the same string.

    Returns ``False`` if ``rules`` is missing, ``None``, or empty.

    Identical implementation to Weeks 7-10's policy migrations; the five
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
class AddCrossChannelEmailLinkedinCooldown:
    """Add the bidirectional cross-channel email↔LinkedIn cooldown rules.

    See module docstring for the full contract. Thin dataclass
    implementing the ``Migration`` Protocol; the work happens in
    :meth:`upgrade` and :meth:`downgrade`. **Both rules are inserted
    (or removed) in one call** — they form a bidirectional pair per
    ADR-0024 D-N1; ship-split is structurally R011-regression.

    Constructed once at module import time and exported as
    :data:`MIGRATION`; the category sub-package's ``__init__.py``
    registers it into ``MIGRATIONS = [...]`` after policy/0005.
    """

    id: str = MIGRATION_ID
    category: MigrationCategory = MigrationCategory.POLICY
    description: str = (
        "Add bidirectional cross-channel email↔LinkedIn cooldown rules "
        "(cooldown.cross-channel-touch, window_days: 14) to every "
        "policy file's rules list — activates the cross-channel "
        "coordination guard (ADR-0003) against R011 (cross-channel "
        "double-engagement); ships TWO rules in one migration per the "
        "bidirectional shape (D-N1)"
    )
    is_reversible: bool = True

    def upgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Append the two canonical rules to every policy file.

        Refuses with ``FileNotFoundError`` if ``ctx.policy_dir`` does
        not exist as a real directory on disk.

        Per-file outcomes:

        * Both rules already present (Shape A — canonical pair already
          installed; factory-template case OR operator-already-applied
          case) → skip file entirely (no stale-considered-channels
          warning path per D-N6).
        * Rule A present, Rule B absent OR Rule A absent, Rule B
          present (Shape B — transitional / one-direction-installed) →
          insert only the missing direction.
        * Both absent (Shape new-operator) → insert both, Rule A first
          then Rule B in deterministic order.
        * Unparseable / non-mapping / missing ``rules:`` / non-list
          ``rules:`` / unsupported ``version:`` → refuse loud with
          :class:`PolicyFileError`.

        The ``affected_count`` returned counts the number of FILES that
        had at least one rule inserted — NOT the number of rules
        inserted. A file that had Rule A inserted but not Rule B
        (Shape B) is counted ONCE. A file that had both rules inserted
        is also counted ONCE. This matches Weeks 7-10's per-file count
        semantics (the runner surfaces affected_count to the operator;
        operators reason about "how many files changed?" not "how many
        rules were added?").

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

            # Defense-in-depth version check. By the time policy/0006
            # runs through the runner, policy/0001 + 0002 + 0003 + 0004
            # + 0005 have applied (the runner sequences migrations) so
            # files are at version 2. An operator who somehow bypassed
            # policy/0001 has v1 files — the engine accepts both v1 and
            # v2 per ADR-0012 D22, so we accept both too. Anything
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
            # state. Inherited Week 7 per-week-review P2-A guard
            # through Weeks 8-10.
            rules_value = data["rules"]
            if not isinstance(rules_value, list):
                raise PolicyFileError(
                    f"{path}: `rules:` is present but not a YAML "
                    f"list (got {type(rules_value).__name__}). "
                    f"Every policy file must declare `rules:` as a "
                    f"list (use `rules: []` for empty). Manual "
                    f"inspection required.",
                )

            # Per-rule idempotence checks via rule-name lookup (D-N6
            # inherits D74 from ADR-0020). The two rules are
            # independently idempotent — Shape B (transitional / one
            # direction present) is a normal operator state that gets
            # the missing direction inserted.
            #
            # No stale-considered-channels warning path (D-N6, same
            # posture as ADRs 0021 D81 + 0022 D86 + 0023 D93):
            # operators with hand-edited `consider_channels:` values
            # are operator-deliberate. Pillar I doctor preflight is
            # the future home for general per-rule misconfig
            # detection.
            rule_a_present = _rule_present_by_name(data, RULE_A_NAME)
            rule_b_present = _rule_present_by_name(data, RULE_B_NAME)

            if rule_a_present and rule_b_present:
                # Shape A — both rules already installed (factory
                # template case OR operator-already-applied case). Skip
                # the file entirely.
                already_present += 1
                continue

            # Compose insertions. For each missing rule, call
            # `add_rule_block_text` sequentially — the second
            # insertion's `text` argument is the result of the first.
            # The primitive's sequential-call composition is verified
            # by `tests/test_migrations_policy_0006.py::
            # TestSequentialAddRuleBlockTextComposition`.
            #
            # APPEND semantics (D73 inherited): the two rules go
            # AFTER any existing operator-installed rules in the
            # canonical Rule A → Rule B order (deterministic across
            # operator-state shapes; Shape new-operator inserts both;
            # Shape B-A-only inserts B; Shape B-B-only inserts A).
            new_text = text
            if not rule_a_present:
                new_text = add_rule_block_text(new_text, RULE_A_BLOCK_TEXT)
            if not rule_b_present:
                new_text = add_rule_block_text(new_text, RULE_B_BLOCK_TEXT)

            if not ctx.dry_run:
                write_policy_file_atomic(path, new_text)
            affected += 1

        verb = "would add" if ctx.dry_run else "added"
        ctx.logger.info(
            "%s cross-channel email↔LinkedIn cooldown rules to %d "
            "policy file(s) (%d already present)",
            verb, affected, already_present,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=True,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} cross-channel email↔LinkedIn cooldown rules "
                f"to {affected} policy file(s) ({already_present} "
                f"already at target)"
            ),
        )

    def downgrade(self, ctx: MigrationContext) -> MigrationResult:
        """Remove the two canonical-named rules from every policy file.

        Inverse of :meth:`upgrade`. Removes ONLY the rules with
        canonical names — operator-renamed versions (e.g.
        ``my-custom-email-linkedin-cooldown``) stay. Operators rarely
        invoke; the framework requires ``allow_rollback=True``
        explicitly.

        Per-file outcomes:

        * Both canonical rules present → remove both via
          ``remove_rule_block_text`` (called twice, once per name) +
          atomic write. Counted as ONE file affected.
        * One canonical rule present, the other absent (Shape B
          transitional) → remove the present one. Counted as ONE file
          affected.
        * Neither present → skip (idempotent re-run).
        * ``rules:`` missing or not a list → refuse loud
          (operator-corrupted state).

        Operator-tuned-value loss
        -------------------------

        Downgrade removes by canonical NAME, not by structural
        identity. If the operator tuned the rule's ``window_days`` or
        ``reason`` fields after the migration applied, those tuned
        values are LOST when downgrade removes the rule. Operators who
        want to preserve tuning + revert the migration's effect should
        rename their tuned rules first (any name not equal to the
        canonical names), then run downgrade — the renamed rules stay
        untouched. Same posture as Weeks 7-10 documented.

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

            rule_a_present = _rule_present_by_name(data, RULE_A_NAME)
            rule_b_present = _rule_present_by_name(data, RULE_B_NAME)

            if not rule_a_present and not rule_b_present:
                already_absent += 1
                continue

            # Remove each present canonical-named rule. The
            # `remove_rule_block_text` primitive is idempotent — if
            # the rule is absent it returns text unchanged — so the
            # rule_X_present guards are belt-and-suspenders but make
            # the intent explicit + match upgrade's guard shape.
            new_text = text
            if rule_a_present:
                new_text = remove_rule_block_text(new_text, RULE_A_NAME)
            if rule_b_present:
                new_text = remove_rule_block_text(new_text, RULE_B_NAME)

            if not ctx.dry_run:
                write_policy_file_atomic(path, new_text)
            affected += 1

        verb = "would remove" if ctx.dry_run else "removed"
        ctx.logger.info(
            "%s cross-channel email↔LinkedIn cooldown rules from %d "
            "policy file(s) (%d already absent)",
            verb, affected, already_absent,
        )

        return MigrationResult(
            migration_id=self.id,
            category=self.category,
            applied=False,
            dry_run=ctx.dry_run,
            affected_count=affected,
            notes=(
                f"{verb} cross-channel email↔LinkedIn cooldown rules "
                f"from {affected} policy file(s) ({already_absent} "
                f"already absent)"
            ),
        )


# Module-level singleton — the registry imports this directly.
MIGRATION: AddCrossChannelEmailLinkedinCooldown = (
    AddCrossChannelEmailLinkedinCooldown()
)
