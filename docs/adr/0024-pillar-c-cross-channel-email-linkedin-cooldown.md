# ADR-0024: Per-channel policy migrations — Cross-channel email↔LinkedIn cooldown (Pillar C Week 11)

- **Status:** Accepted
- **Date:** 2026-05-22
- **Pillar:** C (Multi-channel coherence — Week 11's per-channel policy migration; fifth + FINAL of Weeks 7-11)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0020 (Week 7) shipped the first per-channel policy migration — `policy/0002_add_li_invite_weekly_cap` — and established the convention each subsequent per-channel cap migration follows. D72-D78 cover the structural decisions (ID convention, APPEND insertion, rule-name idempotence, content-additive-no-version-bump, existing-operator seed taxonomy, downstream pillar impact). ADR-0021 (Week 8) shipped `policy/0003_add_li_dm_weekly_cap` + decided D79-D83 (LinkedIn-DM-specific). ADR-0022 (Week 9) shipped `policy/0004_add_tw_dm_weekly_cap` + decided D84-D88 (Twitter-DM-specific). ADR-0023 (Week 10) shipped `policy/0005_add_calendar_booking_daily_cap` + decided D89-D95 (Calendar-booking-specific; **first structural divergence on TWO axes** — daily-window form + operator-side-runaway-loop failure-mode framing). **Week 11 diverges structurally on YET ANOTHER axis** — different from Weeks 7-9's same-channel cap pattern AND different from Week 10's daily-window-cap-with-operator-side-runaway-loop pattern:

1. **TWO rules per migration (not one).** The bidirectional shape per ADR-0003 §Decision "Two factory rules ship". One rule blocks LinkedIn sends when a prior email touch landed within 14d (`cross-channel-email-suppresses-linkedin`); a second rule blocks email sends when a prior LinkedIn touch landed within 14d (`cross-channel-linkedin-suppresses-email`). The two rules together form the bidirectional pair that mitigates R011 (cross-channel double-engagement). Ship-split-by-direction creates a transitional operator state that's R011-regression; bundled is the only safe shape.

2. **Different rule class: `cooldown.cross-channel-touch`** (NOT `budget.window-cap`). Per ADR-0003. The rule class has been registered since Pillar A Week 2; the engine code is unchanged. The migration writes INSTANCES of this rule class — the first per-channel policy migration to do so.

3. **Different field semantics: `consider_channels:` instead of `source:`.** Per ADR-0003. The cross-channel rule queries the LEDGER for prior `*_confirmed` touches whose event-level `channel:` field is in `consider_channels:` — NOT `cost_incurred` events with matching `source:` (the Weeks 7-10 pattern). The `block_when.channel:` field filters when the rule fires (matches the send-gate's channel); `consider_channels:` filters which ledger events the rule considers in its lookback.

4. **No `max_units:`, no window-unit divergence.** The rule uses `window_days: 14` (matching the factory's existing 14-day shape since Pillar A per ADR-0003 §Decision). No units-vs-USD-mode question; no max-units calibration. The cross-channel-touch rule is structurally simpler than the per-channel cap rules at the field level — there is no "count of events" threshold; ANY confirmed touch on a considered channel within the window blocks.

5. **Factory rules ALREADY ACTIVE.** Rules 5 + 6 in `config-template/cooldowns.example.yml` (lines 89-108) ship ACTIVE (uncommented) since Pillar A Week 2 — per ADR-0003 §Decision "Two factory rules ship in `config-template/cooldowns.example.yml` in the same commit that adds the rule class." **This is the FIRST per-channel migration where the factory rules pre-existed the migration.** Weeks 7-10 all shipped factory rules as COMMENTED examples (Rules 12b / 12c / 12d / 12e) — the operator copies the factory file + the migration activates the commented rule for them. Week 11's factory shape is FUNDAMENTALLY different: new operators get the active rules from day one (the factory is the documentation); existing operators with a hand-rolled `cooldowns.yml` predating Pillar A get the rules from the migration.

6. **Different failure-mode framing: recipient-side coordination perception (R011).** Different from BOTH Weeks 7-9 (platform-side enforcement: LinkedIn account suspension; LinkedIn shadowban; Twitter account flag) AND Week 10 (operator-side runaway loop: Cal.com calendar saturation). A recipient receiving an email + a LinkedIn DM within 14 days from the same sender perceives **coordinated outreach** — a perception-layer failure mode that damages the operator's reputation regardless of platform-side enforcement OR operator-side runaway loops. The cap mitigates a perception failure mode the prior weeks' caps don't address.

ADR-0003 (Pillar A Week 2) is the prerequisite ADR establishing the rule class. ADR-0003 §Decision item 2 introduces `CrossChannelTouchRule` + the `consider_channels:` field; §Decision "Two factory rules ship" introduces Rules 5 + 6 in the factory template + lists them as part of Pillar A's `tests/test_policy_matrix.py` CC-01 through CC-12 mandatory rows. Week 11 writes INSTANCES of this rule class via the migration framework; no engine change.

The eight concerns Week 11 resolves:

1. **Bundled bidirectional shape — TWO rules per migration.** D-N1 pins the bundled shape + rejects ship-split-by-direction (which creates R011-regression transitional state) + rejects single-rule-with-bidirectional-flag (engine schema change).

2. **Different rule class — `cooldown.cross-channel-touch` precedent.** D-N2 pins the class choice + names how the existing `add_rule_block_text` primitive composes unchanged (rule-class-agnostic; operates on text-level YAML).

3. **Factory rules ALREADY ACTIVE — operator-onboarding contrast.** D-N3 pins the contrast with Weeks 7-10's commented-factory-rule pattern + rejects rewriting the factory to commented form (which regresses new-operator onboarding) + rejects shipping a NEW Rule 5b/6b comment (which duplicates the active rule).

4. **`consider_channels:` field semantics.** D-N4 pins that the two rules' `consider_channels:` fields are intentionally different (`["email"]` for Rule A; `["linkedin"]` for Rule B) — not a typo; each rule blocks one channel based on touches in the OTHER. The mirror-symmetry IS the bidirectional shape.

5. **Window unit choice — `window_days: 14`.** D-N5 pins the choice matching the factory's existing Pillar A shape + rejects `window_hours` equivalent (Pillar A's 14-day decision is the precedent) + rejects longer/shorter windows.

6. **Stale-considered-channels operator detection — NO.** D-N6 pins the absence of the WARNING path; analogous to ADRs 0021 D81 + 0022 D86 + 0023 D93 (NO stale-source detection for Weeks 8-10). The `TestNoStaleConsiderChannelsWarning` invariant pins the negative posture; future contributors who reflexively add a heuristic by mirroring policy/0002 fail the test.

7. **Existing-operator seed — FOUR shapes (A / B / C / D).** D-N7 catalogs the operator states + recommended remediation. Shape A (both rules canonical) → migration skips. Shape B (one direction installed, the other absent — transitional, NORMAL for operators with hand-rolled cooldowns.yml) → migration inserts the missing direction. Shape C (both renamed) → migration adds canonical pair alongside; operator dedupes. Shape D (canonical name present but with stale `consider_channels:` value) → migration skips per name-match; operator's stale rule stays.

8. **Downstream pillar impact — adapted from ADR-0023 D95 + cross-channel-specific notes.** D-N8 names the Pillar D / E / F / G / H / I / J adaptations. Pillar D's reply correlator + Pillar G's per-rule dashboard get cross-channel-rule rows; Pillar I doctor preflight gets a Shape B detect surface ("only one direction of a bidirectional pair installed").

Risks this ADR mitigates by design:

- **R011 (cross-channel double-engagement).** ADR-0003 created the rule class + the factory rules in Pillar A v1 to mitigate R011 by design from day one. Week 11's migration EXTENDS the mitigation to operators who don't have the factory rules in their installed `cooldowns.yml` (operators with hand-rolled cooldowns.yml predating Pillar A; operators who copied a pre-Pillar-A factory snapshot and never refreshed). After Week 11 applies, every operator's `cooldowns.yml` carries the bidirectional pair — R011 is mitigated across the full operator population, not just the operator-copies-the-current-factory-template subset.

- **R-transitional-unidirectional-cooldown-from-split-migration.** A future contributor reflexively splitting a future bidirectional cooldown (e.g. for Twitter↔LinkedIn) into two migrations would create the unidirectional-cooldown transitional state during the apply window. D-N1's bundled-shape decision + ADR-0024's precedent makes the "bundle bidirectional pairs" pattern explicit + the `TestInsertsBothRulesInSingleApply` invariant test pins the runtime check.

## Decision

### D-N1. TWO rules per migration — bundled bidirectional shape

The Week 11 migration ships TWO rule blocks in one upgrade. Both rules MUST be inserted (or removed via downgrade) in the same migration commit — splitting into two migrations is structurally R011-regression.

**Why bundled, not split:**

- **The bidirectional shape is one logical unit per ADR-0003.** Rules 5 + 6 in the factory template ship together since Pillar A Week 2 — they implement the bidirectional cross-channel coordination guard as a pair. Separating them into two migrations would make the pair appear divisible at the migration framework layer — which it isn't. The bidirectional rule SET is the unit of mitigation; the unidirectional half is structurally incomplete.

- **Asymmetric-failure-cost calculus favors bundled.** A transitional operator state with one direction installed but not the other is exactly the R011 failure mode the rules exist to mitigate (in the gap direction). An operator who pulls Week 11 code + applies `policy/0006_add_cross_channel_email_suppresses_linkedin` but hasn't yet applied a hypothetical `policy/0007_add_cross_channel_linkedin_suppresses_email` is in a state where email touches block LinkedIn sends BUT LinkedIn touches don't block email sends — half the R011 surface is unmitigated. The bundled shape closes this window structurally; ship-split keeps it open during the per-operator apply gap.

- **Operator-friction is lower with bundled.** One migration to apply; one ID to track in the state file; one rollback if needed. The operator's mental model is "the bidirectional pair is one decision." Per ADR-0009 D7's per-category sequential ID convention, the bidirectional pair maps to one ID slot — natural in the framework.

- **Per-file APPEND ordering is deterministic.** Rule A → Rule B in the canonical insertion order; the file's final shape is reproducible across operators. Splitting the migration would let the two rules' file ordering vary based on which apply ran first (which IS deterministic per the runner's ID sort, BUT introduces unnecessary variance compared to the bundled case).

- **The composition primitive supports sequential calls.** `add_rule_block_text` called twice in sequence (once per rule block) produces the same output as a single insertion of a concatenated two-block string. Verified by `tests/test_migrations_policy_0006.py::TestSequentialAddRuleBlockTextComposition`. The primitive is composition-safe so the migration's TWO-rule inner loop is structurally clean.

**Rejected D-N1 alternatives:**

- **Ship as two separate migrations: `policy/0006_add_cross_channel_email_suppresses_linkedin` + `policy/0007_add_cross_channel_linkedin_suppresses_email`.** **Rejected** because:
  - Creates the unidirectional-cooldown transitional state during the apply window (operator pulls Week 11 code + has both migrations pending; the runner applies them in ID order; for the brief window between the two applies, only one direction is enforced — R011-regression in the gap direction).
  - Misrepresents the bidirectional pair as divisible. ADR-0003 §Decision "Two factory rules ship in the same commit" already established the pair as one logical unit; the migration framework should respect this unit structure.
  - The operator-state space grows from 4 shapes (Shape A/B/C/D per D-N7) to 8 (with the two-migration variant doubling the Shape A/B/C/D categories) — more friction in §"Existing-operator seed" without proportional benefit.
  - The framework's per-migration atomicity guarantee (per ADR-0011 + ADR-0012 per-file) does NOT cover cross-migration atomicity; the bundled shape is the only way to guarantee both rules land in one commit. Splitting trades framework correctness for marginal "smaller migrations are nicer to review" benefits.

- **Ship only the email→linkedin direction in Week 11; defer linkedin→email to Week 12 (or later).** **Rejected** because:
  - Same R011-regression argument as the previous alternative — the transitional state would persist for an entire week (or longer), giving every operator a window where R011 fires in the unmitigated direction.
  - Week 12 is the Pillar C exit-criterion-close week, NOT a per-channel migration week (per the Week 10 handoff's plan). Adding a fifth migration to Week 12 would conflict with the exit-criterion-test un-skipping focus.
  - The asymmetry across the two rules is operator-perplexing: "why does my email cap block LinkedIn but not vice versa?" is a question the bidirectional pair should never raise. ADR-0003 §Decision's bidirectional table makes the two-direction symmetry the load-bearing operator-readable shape; defer-one-direction would leak the framework-level decision (split-by-direction) into the operator surface (asymmetric enforcement).

- **Use a single rule with `bidirectional: true` flag — engine schema change.** **Rejected** because:
  - Requires a new field on `CrossChannelTouchRule` (`bidirectional: bool`) + new `__post_init__` semantics (when True, the rule fires on either channel-in-direction) + new YAML schema bump + engine SUPPORTED set extension. The schema-change cascade is exactly what content-additive migrations avoid per ADR-0020 D75.
  - The bidirectional flag would create two semantic paths in `evaluate()`: when `bidirectional=False`, the rule fires on `block_when.channel` only; when `True`, it fires on either `block_when.channel` OR any `consider_channels` channel. The two-paths logic invites edge-case bugs (which channel's `consider_channels` does the OTHER direction query? does the flag affect the cutoff math? does it interact with `_block_when_matches`?).
  - The factory file already ships TWO rules (Rules 5 + 6) per ADR-0003; introducing a `bidirectional: true` flag would deprecate the existing factory shape OR coexist with it (confusing operators about which form to use). The two-rules-per-pair shape IS the convention; the migration's job is to write that convention's instances, not invent a new one.
  - The existing `consider_channels: [<channel>]` field can already represent the multi-direction case via a list — e.g. `consider_channels: [email, linkedin]` would query both channels. The flag would duplicate this surface for the specific case where the user wants two block_when channels.

- **Ship as one mega-migration bundling Week 11 (cross-channel) + future Twitter cross-channel + future Calendar cross-channel.** **Rejected** because:
  - Per ADRs 0020 Alternative 3 + 0021 Alternative 1 + 0022 Alternative 1 + 0023 Alternative 1 (all rejected): per-week shipping discipline is the project's load-bearing process. A bundled migration spanning multiple channel-pairs would be a single 3+-week commit hard to review per-section.
  - The Twitter / Calendar cross-channel rules are NOT yet defined; bundling them with Week 11 would force premature commitment on field shapes the future weeks might revise.
  - Week 11 is the FINAL of Weeks 7-11's per-channel policy migration arc; future cross-channel-pair migrations belong in Pillar D or later (see D-N8 §"Pillar D / I" — `policy/0007_add_cross_channel_twitter_*_cooldown` is the natural future home).

### D-N2. Different rule class — `cooldown.cross-channel-touch`; `add_rule_block_text` composes unchanged

Week 11 is the first per-channel policy migration to write rules of `type: cooldown.cross-channel-touch` (vs Weeks 7-10's `type: budget.window-cap`). The rule class has been registered since Pillar A Week 2 per ADR-0003; the engine code is unchanged. The `add_rule_block_text` / `remove_rule_block_text` primitives compose with the new rule class unchanged because they operate on TEXT-level YAML (rule-class-agnostic), not on parsed-rule semantics.

**Why the primitives compose without modification:**

- **The primitives are text-level operations.** `add_rule_block_text` inserts a literal string into the `rules:` list block; `remove_rule_block_text` matches `- name: <name>` regex + removes the entry + continuation lines. Neither function inspects the rule's `type:` field or any other field beyond `- name:`. Adding a `cooldown.cross-channel-touch`-typed rule via `add_rule_block_text` is mechanically identical to adding a `budget.window-cap`-typed rule.

- **The primitives operate on the SHAPE of a rule entry, not the SEMANTICS.** Every rule entry under `rules:` follows the canonical `  - name: ...` head + indented field lines pattern. The primitives' regex anchors (`_RULE_ENTRY_HEAD_RE`, `_is_rule_continuation_line`) match this shape uniformly. The cross-channel rule's `consider_channels: [<value>]` line is indented at the canonical 4-space level just like the budget rule's `source: <value>` line; the primitives see "an indented continuation line" and apply the same continuation rules.

- **The primitives' round-trip invariant holds for any rule class.** `tests/test_migrations_policy_io.py::TestAddRuleBlockText` + `TestRemoveRuleBlockText` cover the round-trip property structurally — insert then remove returns byte-identical content for ANY rule-class instance whose block follows the canonical shape. Week 11's two rule blocks satisfy the canonical shape (verified by `tests/test_migrations_policy_0006.py::TestRealFactoryTemplateRoundTrip`).

- **Sequential composition is a tested property.** Calling `add_rule_block_text` twice in one upgrade() is verified by `tests/test_migrations_policy_0006.py::TestSequentialAddRuleBlockTextComposition` — the second call's `text` argument is the result of the first call; the final output appends both blocks in order. The primitive is composition-safe without any new "batch insertion" surface area.

- **The rule's YAML output validity is verified end-to-end via engine load.** `tests/test_migrations_policy_0006.py::TestEngineIntegration::test_engine_loads_migrated_file` asserts the engine successfully constructs `CrossChannelTouchRule` instances from the migrated file — the textual output is parseable + the parsed structure matches the class's `from_yaml` expectations.

**Rejected D-N2 alternatives:**

- **Introduce a per-rule-class helper (e.g. `add_cross_channel_rule_block_text`).** **Rejected** because:
  - Duplicates the existing primitive's logic without adding correctness. The cross-channel rule's block has the same canonical shape as a budget rule's block; a class-specific helper would be 95% identical to `add_rule_block_text` + diverge only in the literal block string (which Week 11 already encapsulates via `RULE_A_BLOCK_TEXT` / `RULE_B_BLOCK_TEXT` constants).
  - Maintenance burden grows linearly with rule classes — every new rule class would need a parallel `add_<class>_rule_block_text` helper. The text-level primitive is rule-class-agnostic by design; preserving that agnosticism is the maintainability invariant.
  - Future per-channel migrations (Pillar D or later) writing other rule classes (e.g. tier rules, sending-window rules) compose with the existing primitive too; per-class helpers would explode the helper surface for no semantic gain.

- **Pre-validate the rule's YAML matches `CrossChannelTouchRule.__init__` expectations before inserting.** **Rejected** because:
  - The migration's RULE_A_BLOCK_TEXT / RULE_B_BLOCK_TEXT constants are module-level + tested against `CrossChannelTouchRule.from_yaml` via `tests/test_migrations_policy_0006.py::TestEngineIntegration`. The validation happens at TEST TIME (CI catches a regression before commit); runtime pre-validation duplicates effort + slows the migration apply path.
  - The rule's structural validity is the engine's responsibility per ADR-0003 — `from_yaml` raises `ValueError` on missing `consider_channels` / empty `consider_channels` / missing `window_days`. The migration trusts its own constants are correct + relies on tests for verification.
  - A runtime pre-validation would couple the migration framework to the engine's rule-class registry — operators with custom rule classes (a future Pillar I OSS bring-up scenario) would need to register their classes with the migration framework's validator too, increasing framework complexity.

- **Emit a per-rule-class `migration_event` for downstream observability (Pillar G).** **Rejected** because:
  - Policy migrations are explicitly ledger-silent per ADR-0012 I5. The posture inherits unchanged through Weeks 7-10's policy/0002-0005; Week 11 inherits per ADR-0024 D-N6's analogous "no migration_event" framing.
  - Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories; per-rule-class events are within scope of Pillar G's design, not the migration framework's.
  - A migration_event carrying `rule_class: cooldown.cross-channel-touch` would couple Pillar B's migration framework to Pillar A's rule registry at runtime — a coupling the framework explicitly avoids per ADR-0009 D5's separation-of-concerns.

### D-N3. Factory rules ALREADY ACTIVE — operator-onboarding contrast with Weeks 7-10

The factory `config-template/cooldowns.example.yml` Rules 5 + 6 (lines 89-108) ship ACTIVE (uncommented) since Pillar A Week 2 per ADR-0003 §Decision "Two factory rules ship." Week 11 does NOT add new factory comments — the active rules ARE the operator-readable documentation.

**Contrast with Weeks 7-10**: those weeks all shipped commented factory rules (Rules 12b / 12c / 12d / 12e). The migration activated them in operator-installed files. Week 11's factory shape is FUNDAMENTALLY different:

- **Pillar A Week 2's `cross_channel.py` landed alongside the factory rules.** Per ADR-0003 §Migration/rollout item 2: "`cross_channel.py` lands alongside `suppression.py`; … `cooldowns.example.yml` extended with the two factory rules." The rules + the rule class + the engine support shipped together; the factory was designed from the start to carry the active rules.
- **Pillar C Weeks 7-10 activated pre-existing dispatcher emissions.** The dispatchers (Weeks 2-6) emitted `cost_incurred` events with new sources (`linkedin_invite` / `linkedin_dm` / `twitter_dm` / `calendar_booking`); the caps consume those sources. Until the Weeks 7-10 caps shipped, the dispatchers emitted events that no rule consumed. The Weeks 7-10 migration timing is "activate the cap after the dispatcher has been emitting for some weeks."
- **Week 11 activates Pillar A Week 2 rules for operators who don't have them.** The cross-channel rules don't depend on Pillar C dispatchers — they consume `send_confirmed` / `li_invite_confirmed` / `li_dm_confirmed` ledger events (the dispatchers' downstream confirmed events), which have existed since Pillar A. The rules have been ACTIVE in the factory since Pillar A Week 2; Week 11's migration is the operator-backfill for the population who don't have them yet.

**Why factory rules stay ACTIVE (not converted to commented):**

- **New-operator onboarding is the load-bearing semantic.** A new OSS operator copies the factory file → immediately has R011 mitigated. Converting the rules to commented would mean every new operator has zero R011 mitigation until they run the migration — a regression in the operator-onboarding-to-mitigated-state path.

- **Existing-operator deduplication is handled by name-match idempotence (D-N6).** Operators with the factory rules already installed (the majority case: anyone who copied the factory after Pillar A Week 2) have Shape A — both canonical names present. The migration skips. Shape B (one direction installed, other absent — transitional state for operators with hand-rolled cooldowns.yml predating Pillar A) gets the missing direction. Per D-N7.

- **The active rule IS the documentation.** Operators reading `cooldowns.example.yml` see Rules 5 + 6 with their `reason:` text describing the R011 framing inline. No separate commented documentation block is needed; the rule's YAML + `reason:` field document themselves.

- **The factory's per-channel symmetry stays.** Rules 5 + 6 are at lines 89-108 (early in the file, after the same-channel cooldowns); Rules 12b / 12c / 12d / 12e are at lines 215-368 (in the per-channel-cap section). The two surface areas serve different purposes — cross-channel coordination is a Pillar A concept; per-channel caps are a Pillar C concept. Placing Rules 5 + 6 in the per-channel-cap section would conflate the two layers.

**Rejected D-N3 alternatives:**

- **Add a NEW commented Rule 5b / 6b documenting the rule shape for new operators (redundant — the active rule documents itself).** **Rejected** because:
  - Duplicates the active rule's content. Operators reading the factory file would see the active Rule 5 + a commented Rule 5b with the same shape — confusing "which one is canonical?" question that doesn't exist if the active rule stays.
  - The active rule's `reason:` field already names the R011 framing inline ("Prior email touch within 14d; LinkedIn would look coordinated"). A separate commented block would either duplicate this text OR diverge from it (creating inconsistent operator-readable surfaces).
  - The Week 11 migration's job is NOT to add factory documentation; it's to backfill operator-installed files. Adding a commented Rule 5b would conflate migration-writeback discipline with factory-documentation discipline.

- **Rewrite the factory to comment out Rules 5 + 6 + treat Week 11 as the "activation" migration (mirror of Weeks 7-10).** **Rejected** because:
  - Regresses operator-onboarding — new operators copying the factory would have NO cross-channel coordination until they run the migration. This is fundamentally different from Weeks 7-10's case (where the dispatchers emitted but no cap consumed — the absence of the cap was an existing state for everyone). For Week 11, the absence would be a NEW state introduced by Week 11's rewrite — a regression.
  - Contradicts ADR-0003 §Decision "Two factory rules ship in `config-template/cooldowns.example.yml` in the same commit that adds the rule class." Reopening the Pillar A Week 2 decision via a Pillar C Week 11 rewrite would re-litigate a settled architectural choice.
  - Operators who already copied the factory post-Pillar-A-Week-2 (the majority) have ACTIVE Rules 5 + 6 in their installed files. A factory rewrite to commented form would mean the next factory-pull (e.g. via git or a future Pillar I `update-policies` CLI) would have a content-divergence between the factory's commented form + the operator's active form — operators inspecting their installed files vs the factory would see asymmetry.
  - The Pillar A Week 2 decision to ship active rules (per ADR-0003 §Consequences "Negative: v1 ships with two factory rules whose target events… don't exist in the ledger until Pillar C. Until then, the rules always return Allow(). … Mitigation: doc comments in the example YAML mark these rules as 'Activates when Pillar C lands LinkedIn event types'.") explicitly chose active-with-explanatory-comments over commented. Week 11 inherits this choice.

- **Ship Week 11 as a no-op for new operators + only-for-existing-operators-with-old-installs migration (skip-if-shape-X path).** **Rejected** because:
  - The migration framework doesn't have a "skip-if-shape-X" surface area. Every migration applies uniformly across all operator policy files. Adding a skip-if-shape predicate (e.g. "skip if the operator's file shape exactly matches the current factory") would be a significant framework extension for a one-off case.
  - The skip semantics would require the migration to know the current factory shape — a hardcoded reference to factory state at migration commit time. Future factory changes (e.g. Pillar D adds a new rule between Rules 6 + 7) would diverge from the migration's frozen factory snapshot, breaking the skip predicate.
  - The simpler shape (idempotence via name-match per D-N6) covers the same case — operators with both canonical names already present have Shape A; the migration skips per name-match. No new framework surface needed.

- **Generate Rules 5 + 6 dynamically from a "cross-channel pairs" table in the engine's YAML schema.** **Rejected** because:
  - Adds engine complexity (the schema would need a new top-level construct like `cross_channel_pairs: [{from: email, to: linkedin, window_days: 14}, ...]`) — scope creep against content-additive migrations per ADR-0020 D75.
  - The factory file's explicit rule entries (one per direction) make the bidirectional shape operator-readable at the YAML level. A pairs-table form hides the per-direction `reason:` text + the per-direction `block_when.channel:` + `consider_channels:` symmetry behind a derived view; operators inspecting individual rule firings would have to mentally unroll the pairs table.
  - Pillar A Week 2 already chose explicit-rules-per-direction per ADR-0003 §Decision "Two factory rules ship." Re-litigating this choice for Week 11's migration would scope-creep beyond per-channel migration concerns.

### D-N4. `consider_channels:` field semantic — mirror-symmetric across the two rules

Rule A uses `consider_channels: [email]` (queries email events); Rule B uses `consider_channels: [linkedin]` (queries LinkedIn events). The two values are intentionally different — each rule blocks ONE channel based on touches in the OTHER. The mirror-symmetry IS the bidirectional shape per ADR-0003 §Decision; operators reading the YAML should perceive the symmetry at a glance.

**Why mirror-symmetric, not unified:**

- **The two rules query DIFFERENT ledger surfaces.** Rule A's `consider_channels: [email]` makes it walk events with `channel: email` (e.g. `send_confirmed` with `channel: email`). Rule B's `consider_channels: [linkedin]` makes it walk events with `channel: linkedin` (e.g. `li_invite_confirmed`, `li_dm_confirmed`). Unifying them (e.g. `consider_channels: [email, linkedin]` on both rules) would make each rule fire on a prior touch in EITHER channel — which is structurally wrong for the bidirectional semantic.
  - Rule A SHOULD fire only when a prior email touch landed (because the operator is about to send LinkedIn — the perception risk is "coordinated email-then-LinkedIn"). A prior LinkedIn touch landing before this LinkedIn send is a SAME-channel concern (rules 4 / Pillar C per-channel caps) — not a cross-channel concern.
  - Rule B SHOULD fire only when a prior LinkedIn touch landed (perception risk: "coordinated LinkedIn-then-email"). A prior email touch landing before this email send is the same-channel concern handled by Rule 4 (domain-cooldown).

- **The mirror-symmetric pair has a single-rule-equivalent shape that's strictly less expressive.** ADR-0003 §Alternative 4 (Accepted) chose the per-pair-rules-with-YAML-configured-channel-pairs pattern over per-class-per-pair (rejected: "balloon as channels are added"). The per-rule explicit `consider_channels:` value per rule IS the canonical bidirectional representation.

- **Operator-readability favors mirror-symmetric.** Reading Rules 5 + 6 in the factory, an operator sees:
  ```
  Rule 5: fires on linkedin; considers email; window_days: 14 → "prior email blocks LinkedIn"
  Rule 6: fires on email; considers linkedin; window_days: 14 → "prior LinkedIn blocks email"
  ```
  The diagonal-swap pattern is immediately recognizable as the bidirectional pair. A unified-list shape would obscure it: `Rule X: fires on linkedin OR email; considers email OR linkedin; window_days: 14` doesn't communicate "two coordination directions."

**Rejected D-N4 alternatives:**

- **Unified `consider_channels: [email, linkedin]` on both rules (semantically wrong but textually shorter).** **Rejected** per the structural analysis above:
  - Rule A would fire on a prior LinkedIn touch (a same-channel concern Rule 4 already handles), introducing false-positives.
  - Rule B would fire on a prior email touch (same-channel concern), introducing false-positives.
  - The factory's existing Rules 5 + 6 per ADR-0003 use the mirror-symmetric form; deviating in Week 11 would create operator-file divergence from the factory shape.

- **Merge the two rules into one with bidirectional firing — single-row representation.** **Rejected** per D-N1 §"Use a single rule with `bidirectional: true` flag" rejection:
  - Engine schema change required.
  - Existing factory + ADR-0003 shape is two rules per pair.
  - The migration framework's per-rule idempotence (name-match) would need a per-pair idempotence shape — more complex without correctness gain.

- **Distinct `block_when.channel:` but unified `consider_channels:` — Rule A fires on linkedin and considers [email]; Rule B fires on email and considers [email] (or any other unified form).** **Rejected** per the same structural analysis: each rule's `consider_channels:` MUST match the OPPOSITE channel from its `block_when.channel:` for the bidirectional semantic to be correct. Any other unified-or-asymmetric choice introduces false-positives or false-negatives in one direction.

### D-N5. Window unit choice — `window_days: 14`

Both rules use `window_days: 14`. The factory's pre-existing Rules 5 + 6 (per ADR-0003 §Decision "Two factory rules ship") ship `window_days: 14` since Pillar A Week 2; Week 11's migration matches exactly.

**Why `window_days: 14` and not other forms:**

- **Matches the factory's existing shape.** Operators reading the factory or the migrated `cooldowns.yml` see consistent semantics across files; the migration's RULE_A_BLOCK_TEXT / RULE_B_BLOCK_TEXT match the factory's Rules 5 + 6 byte-equivalent (modulo line-ending convention) — verified by `tests/test_migrations_policy_0006.py::TestRealFactoryTemplateRoundTrip`.

- **The 14-day coordination horizon is operator-deliberate per ADR-0003.** ADR-0003 §Decision "Two factory rules ship" lists `window_days: 14` for both rules. The 14-day window is the recipient-coordination-perception horizon — long enough that "still recent" is plausible (a recipient who got an email last week vs this LinkedIn DM perceives coordination); short enough that "stale" is plausible past it (the same recipient getting a LinkedIn DM 30 days after an email is unlikely to remember the coordination context).

- **Matches Rule 4 (domain-cooldown) for cross-rule consistency.** Rule 4's `window_days: 14` is the per-domain deliverability throttle; Rules 5 + 6's same window means operators have ONE coordination horizon to remember across rules. Multiple horizons (e.g. 14d for domain + 7d for cross-channel + 30d for something else) would fragment the operator's mental model.

- **The engine has no rule-class-specific window semantics for `cooldown.cross-channel-touch`.** Per ADR-0003 §Decision "Boundary semantics": cutoff = `ctx.now - timedelta(days=window_days)`; events strictly older than cutoff are outside; events at the boundary instant are inside. The semantic is identical to `DomainThrottleRule`'s. Operators reasoning about "14d window" for both rules see the same boundary behavior.

**Rejected D-N5 alternatives:**

- **`window_hours: 336` (equivalent to 14 days in hours form).** **Rejected** because:
  - The factory's existing shape uses `window_days: 14`; deviating in the migration would create operator-file divergence.
  - `CrossChannelTouchRule.from_yaml` requires `window_days` (per the existing class shape per ADR-0003); there is no `window_hours` parameter on the cross-channel rule. The hours form would require an engine schema change (adding `window_hours` to `CrossChannelTouchRule.__init__`) — scope creep against content-additive migrations.
  - The 14-day window is semantically a multi-day horizon (the recipient-coordination-perception spans days, not sub-day units). Hours form is operator-readable only for sub-day windows (per ADR-0023 D90's "daily caps spell out hours" convention); for multi-day windows, days is the natural unit.

- **Longer window — `window_days: 21` or `window_days: 28` for more conservative posture.** **Rejected** because:
  - Diverges from the factory's existing 14-day shape (per ADR-0003) — operator-file inconsistency.
  - The 14-day coordination-perception horizon is calibrated against recipient memory + cold-outreach cadence research. Longer windows would over-suppress (operators who legitimately need to follow up across channels after 3 weeks of silence would be blocked despite no coordination perception risk).
  - The window is operator-tunable (one-line YAML edit in the operator's installed `cooldowns.yml`); operators wanting a more conservative posture can tune up. The factory default's job is to be safe for the median operator.
  - Per ADR-0003 §Consequences "Negative: v1 ships with two factory rules…" — the 14-day choice was already deliberated in Pillar A Week 2 + landed via ADR-0003 §Decision; Week 11's migration shouldn't re-litigate without strong cause.

- **Shorter window — `window_days: 7` for tighter posture.** **Rejected** because:
  - Diverges from the factory's existing 14-day shape — same operator-file inconsistency argument.
  - 7-day window may under-suppress for the recipient-perception horizon — a touch 10 days ago is still recent enough to be perceived as coordinated; a 7-day cap would allow the coordinated send.
  - The asymmetric-failure-cost calculus: false-block (recipient still gets one channel) is operator-recoverable; false-allow (R011 fires; recipient perceives coordination) is harder to recover from. The 14-day default biases conservatively per ADR-0003 §Decision.

- **Configurable per-pair window — operators can set different windows for email↔linkedin vs hypothetical future channel pairs.** **Rejected** because:
  - The migration's job is to ship a safe default; operators tune via the one-line YAML edit. Per-pair window configurability is already present at the rule level (each rule has its own `window_days:`); the migration writes the default per ADR-0003.
  - Future per-pair migrations (e.g. Twitter↔email, Calendar↔linkedin) would each ship their own `window_days:` default; Week 11's migration covers email↔linkedin only per the bundled-pair shape (D-N1).

### D-N6. NO stale-considered-channels detection — Pillar I doctor instead

The Week 11 migration's `upgrade()` does NOT emit a WARNING log when a canonical-named rule (`cross-channel-email-suppresses-linkedin` or `cross-channel-linkedin-suppresses-email`) is already present with a non-canonical `consider_channels:` value. The migration's idempotence check (D-N6 inherits D74 from ADR-0020) skips the file when the canonical name is present — it does NOT inspect the rule's other fields to surface staleness.

This is a deliberate inheritance from ADRs 0021 D81 + 0022 D86 + 0023 D93's posture. The structural reasons:

- **No historical precedent.** The factory's Rules 5 + 6 have always shipped `consider_channels: [email]` (Rule 5) and `consider_channels: [linkedin]` (Rule 6) since Pillar A Week 2 per ADR-0003. There has never been a factory-shipped variant with a different `consider_channels:` value (no `consider_channels: [email, twitter]` from a Pillar D-era factory; no `consider_channels: []` from a deprecated shape). Operators with hand-edited `consider_channels:` values are operator-deliberate — perhaps they're using a custom multi-channel cooldown shape, perhaps they're testing a future Pillar D scenario.

- **Operator-hand-written variants are operator-deliberate.** If an operator hand-wrote a `cross-channel-email-suppresses-linkedin` rule with `consider_channels: [email, twitter]` (a plausible multi-channel cooldown), the divergence from the canonical `[email]` is the operator's deliberate choice. The migration should not nag.

- **Asymmetric stale-source-or-considered-channels posture across the policy/0002-0006 range.** Per ADR-0020 §D77, Shape 1 (stale source) applies only to the invite rule (Week 7) because the factory file shipped only the invite rule's commented form with the historical `source: linkedin` value. Shapes 2 + 3 (canonical correct, or renamed) apply to every per-channel migration uniformly. For Week 11, no Shape-1-equivalent exists — the factory's Rules 5 + 6 have always carried the canonical `consider_channels:` values. The §"Existing-operator seed" shapes for Week 11 are A / B / C / D per D-N7 (where Shape D — canonical name with stale considered_channels value — is the closest analog to Shape 1, but the migration is silent on it).

- **The structural intervention against a future contributor reflexively adding a "stale considered_channels detection" branch by mirroring policy/0002 is the `TestNoStaleConsiderChannelsWarning` test class.** Any future contributor who adds a heuristic ("if the canonical rule has `consider_channels: [<unusual_value>]`, emit a WARNING") would fail these tests. The negative invariant is encoded explicitly per the carry-forward pattern from Weeks 8-10's `TestNoStaleSourceWarning`.

- **Pillar I's doctor preflight (future) is the home for general per-rule misconfig surfacing.** A future `python -m orchestrator.policy doctor` will inspect every active policy rule for canonical-shape conformance + warn on per-rule deviations (wrong `consider_channels:` value for canonical-named rules, wrong `block_when.channel:` for canonical-named rules, etc.). That command is the principled home; the per-migration WARNING path in policy/0002 is a one-off accommodation for the specific Shape 1 case (which has no Week 11 equivalent).

The `TestNoStaleConsiderChannelsWarning` test class in `tests/test_migrations_policy_0006.py` pins the negative invariant with sub-cases covering:
- `consider_channels: [twitter]` (a plausible hand-edit substituting one channel for another)
- `consider_channels: [email, twitter]` (a plausible multi-channel cooldown variant)
- `consider_channels: [linkedin]` for the email-suppresses-linkedin rule (a likely cross-direction confusion — the operator confused which direction is which)
- `consider_channels: [email]` for the email-suppresses-linkedin rule (the negative control — canonical; no warning even on the correct shape)

**Rejected D-N6 alternatives:**

- **Mirror Week 7's WARNING path: warn on any non-canonical `consider_channels:` value when the canonical name is present.** **Rejected** because:
  - Same rationale as ADRs 0021 D81 + 0022 D86 + 0023 D93's rejections of this alternative. Pillar I's doctor is the correct surface for general misconfig detection. A per-migration WARNING for every conceivable deviation pollutes the runner's apply logs + duplicates effort that Pillar I will land cleanly.
  - The Shape 1 case (Week 7's specific historical mistake from a specific factory shape) is fundamentally different from "operator's rule has the wrong considered_channels" — the former is a known-population state with a known operator base; the latter is an open-ended class.
  - Cross-channel rules are MORE prone to operator-tuning than per-channel caps (operators add additional channels to `consider_channels:` for custom multi-channel cooldowns); WARN-on-any-deviation would generate false-positive nags for legitimate operator-deliberate tunings.

- **Warn specifically on cross-direction confusion (`consider_channels: [linkedin]` for the email-suppresses-linkedin rule — operator confused which direction is which).** **Rejected** because:
  - The heuristic surface grows as more migrations land — every cross-channel migration would carry its own "cross-direction confusion" heuristic. Each per-migration heuristic is a maintenance burden + an audit-trail noise source.
  - The cross-direction confusion is a specific operator-mistake class; Pillar I doctor preflight is the principled home for detecting it (alongside other operator-mistake classes for other rule types). Per-migration heuristics fragment the detection surface.
  - The `TestNoStaleConsiderChannelsWarning` invariant test explicitly covers the cross-direction-confusion sub-case as a negative-invariant pin — future contributors who reflexively add the heuristic fail the test.

- **Emit an INFO log noting the operator's `consider_channels:` value when skipping, without a WARNING.** **Rejected** because:
  - Same rationale as ADRs 0021 D81 + 0022 D86 + 0023 D93's rejections of this alternative. INFO logs are noise in the runner's normal apply path; per-rule visibility belongs in the dry-run preview or Pillar I doctor.
  - Operators inspecting apply logs to confirm "did the migration do what I expected" don't benefit from per-rule field dumps — the affected_count + already_present counts already surface the file-level outcome.

- **Surface the warning via the dry-run preview only (no WARN in apply).** **Rejected** because:
  - Dry-run and apply must produce structurally equivalent outputs (per the migration framework's dry-run contract — the preview surfaces what apply WILL do; introducing per-mode warning divergence breaks the equivalence).
  - The dry-run preview is the operator's chance to inspect changes before commit; suppressing warnings in apply mode would mean the same content-divergence the operator saw in dry-run gets silently skipped in apply (and the operator might not have read the dry-run output).

### D-N7. Existing-operator seed — FOUR shapes (A / B / C / D)

ADR-0020 §D77 catalogs three pre-migration operator shapes for the LinkedIn invite cap (Week 7). For Week 11 (cross-channel email↔LinkedIn cooldown), the operator shapes are FOUR (one new shape due to the bidirectional pair's transitional state):

1. **Shape A — both canonical rules present (`cross-channel-email-suppresses-linkedin` AND `cross-channel-linkedin-suppresses-email`).** This is the MAJORITY case: operators who copied the factory after Pillar A Week 2 (i.e. anyone who ran `cp config-template/cooldowns.example.yml ~/.outreach-factory/policies/cooldowns.yml` since 2026-05-16) have both rules active in their installed file. The migration's name-match idempotence (D-N6) skips BOTH rules; the file is byte-identical post-apply. **Operator remediation:** none needed.

2. **Shape B — one canonical rule present, the other absent (transitional / mixed state).** This is a less-common but normal operator-state: operators with a hand-rolled `cooldowns.yml` predating Pillar A Week 2 might have manually added one direction of the cross-channel pair before pulling Pillar A code; OR operators who hand-edited a copy of the factory and accidentally deleted one of the two rules. The migration inserts ONLY the missing direction; the present direction stays. **Operator remediation:** none needed. The migration brings the operator to Shape A.

3. **Shape C — both rules renamed.** Operators who wrote their own cross-channel cooldown rules with different names (e.g. `my-custom-email-linkedin-cooldown` and `my-custom-linkedin-email-cooldown` — plausible for operators in the hand-rolled-policies era). The migration's name-match (canonical-name only) treats both renamed rules as "not present" + adds the canonical-named pair alongside. The operator now has FOUR rules: their two renamed ones + the canonical pair. **Operator remediation:** delete one of the two pairs. (The canonical version is operator-acceptable to delete — it's the migration's default; the operator's renamed version preserves any tuning. Or vice versa — operator's choice.) Same posture as Weeks 7-10's Shape 3 + the same doctor preflight (Pillar I) is the natural future warning surface.

4. **Shape D — canonical name present but with stale `consider_channels:` value (or other stale field).** Operators with a `cross-channel-email-suppresses-linkedin` rule whose `consider_channels:` is `[email, twitter]` (a hand-edited multi-channel cooldown variant) OR `[linkedin]` (a cross-direction confusion). The migration's name-match idempotence skips the file (D-N6); the operator's stale rule stays as-is. **Operator remediation:** none from the migration's perspective — the operator's `consider_channels:` value is operator-deliberate. Pillar I doctor preflight may warn in the future per D-N6.

The factory file's `cooldowns.example.yml` ships the ACTIVE Rules 5 + 6 (per D-N3) — new operators copying the factory get Shape A from day one. There is no pre-Week-11 commented factory shape they could have stale-copied.

**Rejected D-N7 alternatives:**

- **Treat Shape B as anomalous + force re-apply of BOTH rules even if one is present.** **Rejected** because:
  - Violates the migration framework's idempotence contract per ADR-0009 D4 + ADR-0020 D74. Operators who manually added one direction have their version preserved per the name-match idempotence; force re-applying both rules would either overwrite the operator's tuning (data loss) or duplicate the present rule (file corruption).
  - Shape B is a normal operator-state for the hand-rolled-policies era; treating it as anomalous would produce false-positive remediation work for legitimate operators.
  - The bidirectional shape is per ADR-0003 a logical-unit pair, BUT the per-rule idempotence is per ADR-0020 D74 a name-match operation. The two contracts compose: insert the missing direction(s); don't touch the present ones.

- **Add a Shape E (canonical name present with stale `block_when.channel:` value — operator wrote `block_when.channel: email` for the email-suppresses-linkedin rule instead of `linkedin`).** **Rejected** because:
  - This is a sub-case of Shape D (stale field in canonical-named rule); the migration's posture is uniform across all stale-field cases — name-match skips; the operator's choice stays. Adding Shape E would proliferate the taxonomy without changing migration behavior.
  - The `tests/test_migrations_policy_0006.py::TestNoStaleConsiderChannelsWarning` already covers the cross-direction-confusion case as a sub-test; the negative invariant pins the behavior without requiring a distinct shape label.
  - Operators with cross-direction-confusion-stamped rules have inert rules (fires-on-the-wrong-channel — never triggers); the natural feedback loop (Pillar G dashboard showing zero firings on a rule that should fire) is the recovery path.

- **Catalog Shape A / B / C / D + add explicit operator-recovery scripts to ADR-0024.** **Rejected** because:
  - Operator-recovery scripts belong in Pillar I OSS bring-up's `python -m orchestrator.policy doctor` + remediation flow. ADR-0024 is the design rationale; remediation is operational.
  - Per ADRs 0020-0023's existing-operator-seed sections, the recommended action per shape is the documentation; explicit scripts are over-scoped for the ADR.
  - The recovery is one-line YAML edit (delete the unwanted rule) — operators don't need scripts.

### D-N8. Downstream pillar impact

Per the ADR-0009 convention (every Pillar B + C ADR explicitly names cross-pillar impact); adapted from ADR-0023 D95 + cross-channel-specific adaptations rooted in ADR-0003's two-rules-per-pair shape + the bidirectional R011 mitigation.

* **Pillar D (reply + conversation handling).** Cross-channel cooldown rules don't directly interact with reply correlation; the rules fire at SEND time (one of the two channels), not at REPLY time. But Pillar D's win-attribution may want to query "did the recipient receive a coordinated touch?" — the rule's `policy_blocked` event with `rule: cross-channel-email-suppresses-linkedin` (or the inverse) is the Pillar D signal that a coordinated touch was PREVENTED. The reply correlator's per-Person view can show "operator wanted to send LinkedIn on day X; cross-channel-cooldown blocked because email landed on day X-7" — a coordination-discipline metric Pillar D dashboards alongside reply rates.

* **Pillar E (discovery quality + lineage).** No direct interaction. Discovery doesn't emit `send_confirmed` / `li_*_confirmed` events — those flow from the dispatcher. Pillar E's `discovery_lineage:` blocks (per ADR-0019 D70) may include cross-channel-touch metadata (e.g. "this Person was discovered via LinkedIn after an email cross-channel-block fired") — a research-loop signal Pillar E correlates with discovery sources.

* **Pillar F (voice corpus + draft quality).** No direct interaction. Pillar F's voice-fidelity scoring operates on touch body content; cross-channel cooldown rules fire at send-time independent of body content. Voice-fidelity-scoped policy rules (e.g. "block sends whose voice-fidelity score is below X") may be a future ADR; orthogonal to Week 11.

* **Pillar G (observability).** OTel + Prometheus will emit per-rule metrics; the cross-channel rules produce `policy_blocked` events with `rule: cross-channel-email-suppresses-linkedin` (Rule A direction) or `rule: cross-channel-linkedin-suppresses-email` (Rule B direction) + `channel: linkedin` or `channel: email` respectively (per ADR-0014 D33's channel-on-every-event invariant). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=cross-channel-email-suppresses-linkedin` / `cross-channel-linkedin-suppresses-email` without new code (per ADR-0001). Pillar G's dashboards group by `rule:` field — the two cross-channel rules surface as DISTINCT ROWS in the per-rule firing-rate dashboard (one row per direction; operators see "email→LinkedIn blocks: N" + "LinkedIn→email blocks: M"). The R011 dashboard tracks "how often does the cross-channel cooldown fire?" as a coordination-discipline metric — distinct from "how often does a same-channel cap fire?" which Weeks 7-10 contribute.

* **Pillar H (daemon + scheduled jobs).** Pre-send gating (per ADR-0006 §"Where budget rules fire") consumes the cross-channel rules at the same send-gate as the per-channel caps. Same surface area as Weeks 7-10. The daemon does NOT need to poll any external surface for cross-channel rules (unlike Cal.com webhook per ADR-0019 D68); the rules operate purely on the local ledger. Pillar H's bulk-send workflow per-Person threading may want to pre-check cross-channel rules AT JOB-DISPATCH time (vs. AT SEND time) to surface coordination-conflicts before send-attempt — Pillar H's job-dispatch layer composes with the existing rule via the same RULE_REGISTRY. No engine change.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant policy directories; each tenant's `cooldowns.yml` gets the Weeks 7-11 migrations independently. The doctor's refuse-on-pending applies uniformly. The CLI's `python -m orchestrator.migrations apply` lands here (deferred from ADR-0012 D20). **Pillar I doctor preflight: the §"Existing-operator seed" Shape B (transitional state with one direction present + other absent) is a natural detect surface** — the doctor warns when only one direction of a bidirectional pair is installed. This is the FIRST per-rule-pair doctor detect surface (Weeks 7-10's per-channel caps are single rules; their doctor surface is single-rule canonical-shape conformance). Pillar I's `python -m orchestrator.policy doctor --check-cross-channel-pairs` flag will surface Shape B explicitly. Pillar I's CLI cross-channel-pair extension: a future `policy/0007_add_cross_channel_twitter_*_cooldown` migration (for Twitter↔email or Twitter↔linkedin pairs) follows the same bundled-bidirectional pattern; the operator-facing CLI surfaces the pattern as `python -m orchestrator.policy add-cross-channel-pair --channels email,twitter --window-days 14` per a future Pillar I OSS bring-up.

* **Pillar J (security + compliance).** GDPR-forget on a policy file doesn't typically apply (rules don't contain PII). The cross-channel rule consumes `*_confirmed` ledger events whose detail blocks may carry PII (recipient email, LinkedIn URL); GDPR-forget operations on a Person remove those events per Pillar J's existing flow; cross-channel rules naturally stop firing for forgotten Persons because their events no longer exist in the ledger. No special handling needed at the rule level. Per-tenant rule deletion as part of an account-forget operation is a Pillar I + J intersection — neither Weeks 7-11 ship it.

**Rejected D-N8 alternatives:**

- **Defer downstream pillar impact to the consolidated Pillar I doctor.** **Rejected** because:
  - Every ADR since 0014 has named cross-pillar impact explicitly (per the ADR-0009 convention). Skipping for Week 11 would break the precedent + force a future reader to reconstruct the impact from absent context.
  - Cross-pillar impact for cross-channel rules is structurally DIFFERENT from per-channel caps (Pillar D's coordination-discipline metric is new; Pillar G's bidirectional-pair dashboard rows are new; Pillar I's Shape-B detect surface is new); restating it explicitly forces the per-channel-correctness check.

- **Mark cross-pillar impact identical to ADR-0023 D95 by reference, no restatement.** **Rejected** because:
  - The cross-channel-specific adaptations (Pillar D's coordination-discipline metric vs ADR-0023's reply-correlation-after-Calendar-booking; Pillar G's TWO distinct firing-rate rows vs ADR-0023's single Calendar booking row; Pillar I's Shape-B detect surface — the FIRST per-rule-pair doctor surface) are not identical to the Calendar booking version. Restating with adaptations forces the explicit cross-channel-correctness check.
  - ADRs should be self-contained per the §D94 rationale — a reader looking up "what does Week 11 do across Pillars D-J?" should get a self-contained answer without chasing ADR-0023 + ADR-0003 references.

- **Add a new Pillar K row anticipating future regulatory needs.** **Rejected** because:
  - PILLAR-PLAN does not include a Pillar K; introducing one in a Week 11 ADR is scope creep beyond the migration.
  - Pillar J already covers GDPR-forget + per-tenant rule deletion per the existing pillar definition.

- **Collapse the per-pillar bullets into a single "no significant downstream impact" sentence + forward-reference Pillar I doctor.** **Rejected** because:
  - The cross-channel-specific interactions ARE substantive — Pillar D's win-attribution per-Person view is enriched by cross-channel-block events; Pillar G's bidirectional-pair dashboard rows are new observability surface; Pillar I's Shape-B detect surface is novel (the first per-rule-pair doctor surface, distinguishable from Weeks 7-10's single-rule canonical-shape conformance). The per-pillar elaboration forces these to be surfaced explicitly.
  - The future Pillar I doctor can't substitute for the per-ADR-time explicit framing — the doctor is a runtime tool; the ADR is a design-time artifact.

## Alternatives considered

### Alternative 1: Defer Week 11 — bundle cross-channel cooldown into a future Pillar D migration

Defer the cross-channel email↔LinkedIn cooldown migration to Pillar D (where reply-coordination caps may also land). **Rejected** because:

- Per ADRs 0020 Alternative 3 + 0021 Alternative 1 + 0022 Alternative 1 + 0023 Alternative 1 (all rejected): per-week shipping discipline is the project's load-bearing process.
- Operators with hand-rolled `cooldowns.yml` predating Pillar A Week 2 (a small but real population) have NO R011 mitigation until Week 11 ships. Deferring extends the unmitigated window — directly contradicts ADR-0003's "R011 mitigated by design from Pillar A v1" intent for the full operator population (not just the factory-template subset).
- Pillar D is 6+ weeks out (per PILLAR-PLAN §6 timing); deferring 6+ weeks is asymmetric-failure-cost-unfavorable (the cost of waiting is operators staying unmitigated; the cost of shipping is 1 migration ID).

### Alternative 2: Schema-changing migration — bump `version:` to 3 to mark "Cross-channel pair installed"

Bump the policy file's `version:` to 3 + add a `cross_channel_pairs_installed: true` top-level field. **Rejected** because:

- Per ADR-0020 D75/D76 (inherited): per-channel rule additions are CONTENT-ADDITIVE, not SCHEMA-CHANGING. The engine's parser handles the new rule entries via its existing registry; no new field name, no new top-level structure, no new file shape.
- The "cross-channel pair installed" predicate is derivable from the rules list — check whether both canonical names are present. A separate top-level field would duplicate the rules-list view + introduce drift potential (operator deletes the rules but the flag stays).
- Schema bump cascades — engine SUPPORTED set extension + version-range acceptance discipline + per-tenant version-coordination. Content-additive migration avoids all of this.

### Alternative 3: Reuse Week 10's policy/0005 — bundle Calendar booking cap + cross-channel pair

Add the two cross-channel rules to Week 10's policy/0005 migration; rename to `0005_add_calendar_booking_daily_cap_and_cross_channel_pair`. **Rejected** because:

- Per ADR-0020 Alternative 3 (mega-migration alt) + ADR-0009 D2 (sequential ID convention): each migration is independently reversible at the migration level. An operator who wants to roll back just the cross-channel pair while keeping the Calendar booking cap needs them as separate migrations.
- The migration was already shipped (commit `1ef084d`); modifying it post-ship breaks the framework's append-only migration discipline (per ADR-0009 D4 + D7).
- Future per-channel migrations (Pillar D's reply-coordination cap, etc.) each ship as their own migration — bundling Week 11 with Week 10 would have to also bundle every future per-channel migration, defeating the per-week cadence.
- The rule classes diverge (Week 10: `budget.window-cap`; Week 11: `cooldown.cross-channel-touch`); bundling would make the migration's INNER LOOP more complex (different code paths for different rule classes).

### Alternative 4: Migration also emits a `migration_event` to record cross-channel pair activation

Per ADR-0010 D17 / ADR-0020 Alternative 4 / ADR-0021 Alternative 4 / ADR-0022 Alternative 4 / ADR-0023 Alternative 4 (all rejected): migrations could emit a `migration_event` audit-trail event. **Rejected** by inheritance:

- Policy migrations are explicitly ledger-silent per ADR-0012 I5. Week 11 inherits the posture.
- Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories.

### Alternative 5: Migration writes a single `cross-channel-touch` rule with `consider_channels: [email, linkedin]` and `block_when.channel:` matching ANY of `[email, linkedin]`

Construct a single rule that covers both directions via a multi-value `block_when.channel:` field. **Rejected** because:

- The `_block_when_matches` helper (per ADR-0001 §"_block_when_matches`") accepts a SINGLE scalar value per filter key, not a list. Multi-value `block_when.channel:` would require an engine schema change (extending `_block_when_matches` to handle list-valued filters).
- The single-rule shape would fire on EITHER channel when ANY OTHER channel has a touch — semantically wrong per D-N4 (each direction's `consider_channels:` should mirror its `block_when.channel:`'s OPPOSITE).
- The factory's existing Rules 5 + 6 use the two-rules-per-pair shape per ADR-0003; deviating in Week 11 would create operator-file divergence from the factory.

### Alternative 6: Ship the cross-channel pair as a Pillar A retroactive migration (policy/0001-equivalent for Pillar A Week 2)

Frame the cross-channel pair as Pillar A Week 2 backfill (operators who pre-date Pillar A Week 2 are the target); make it `policy/0001_b_add_cross_channel_pair` or similar. **Rejected** because:

- Per ADR-0009 D7's sequential ID convention: migrations are numbered append-only by commit order, not by "which pillar they belong to." Pillar A's `policy/0001` is the schema-change migration; Pillar C's `policy/0002-0006` are the per-channel additions. There's no Pillar-coupled numbering subspace.
- Inserting `policy/0001_b` between `policy/0001` and `policy/0002` would violate the sequential ordering + break the runner's per-ID sort.
- The migration's CONTENT is operator-backfill of a Pillar A shape — but the PROCESS is a Pillar C per-channel migration following Weeks 7-10's pattern. The numbering reflects the process (Pillar C Week 11's slot = `policy/0006`).

## Consequences

### Positive

- **Operators with hand-rolled `cooldowns.yml` predating Pillar A Week 2 get R011 mitigation automatically** when they run the next batch of pending migrations. The bidirectional pair installs in one commit; no transitional-state R011-regression window.
- **The migration is content-additive, not schema-changing** (D75/D76 inherited from ADR-0020 through ADR-0023). Files stay at their pre-migration version; the engine's SUPPORTED set is unchanged; no flag-day risk.
- **First per-channel migration with TWO rules per migration.** Establishes the bundled-bidirectional-pair pattern for future per-channel-pair migrations (e.g. Twitter↔email, Calendar↔linkedin). The composition primitive `add_rule_block_text` is verified composition-safe via `tests/test_migrations_policy_0006.py::TestSequentialAddRuleBlockTextComposition`.
- **First per-channel migration with `cooldown.cross-channel-touch` rule class.** Establishes the rule-class-agnostic posture of the migration framework — `add_rule_block_text` is verified to work uniformly across rule classes.
- **First per-channel migration where factory rules pre-existed the migration.** Establishes the operator-onboarding-contrast pattern: new operators get the active rules from day one; existing operators get them via the migration. Future similar cases (Pillar D's bidirectional reply-coordination caps, etc.) inherit the precedent.
- **Pillar C exit criterion progression.** Week 11 closes the cross-channel cooldown gap; Week 12 delivers the exit-criterion test un-skipping. After Week 12 Pillar C's per-channel policy coverage is complete + the pillar's exit gate closes.
- **R011 fully mitigated across operator population.** Pillar A Week 2 mitigated R011 for new operators (factory-template subset); Week 11 extends to the full operator population.

### Negative

- **Operators with renamed cross-channel rules (Shape C) end up with FOUR rules** (two renamed + two canonical) after the migration. They need to delete one of the two pairs to clean up. Same posture as Weeks 7-10's Shape 3; documented in §D-N7.
- **Operators with hand-edited `consider_channels:` values (Shape D) keep their stale rules.** The migration is silent; doctor preflight (Pillar I) is the future automated-detect surface. Same posture as ADRs 0021 D81 + 0022 D86 + 0023 D93.
- **The bidirectional pair's enforcement is more aggressive than the same-channel rules.** A recipient who got an email last week is blocked from receiving a LinkedIn DM this week — even if the email was a totally different campaign. Operators with multi-campaign coordination needs may need to tune the `window_days:` value down OR add register-scoped versions of the rules (a future ADR if the need surfaces).
- **The factory file does NOT grow** for Week 11 (Rules 5 + 6 are ALREADY there since Pillar A). Operators tracking the factory across versions via git see no change — but the MIGRATION is what changes their installed file.

### Neutral / observability

- The migration logs at INFO with `affected_count` + `already_present` counts. The runner's pending / dry-run / apply reports surface the migration ID + description as expected.
- Policy migrations remain ledger-silent (no `migration_event` events) per ADR-0012 I5; Pillar G is the future home for per-migration metrics on non-ledger categories.
- The rules' `policy_blocked` event shape is unchanged from existing cross-channel-touch rules (per ADR-0003 §Decision "Cross-channel blocks emit the standard `policy_blocked` event"). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=cross-channel-email-suppresses-linkedin` (or the inverse) without new code.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAML remains the SoT for "what rules are active" (per `docs/SOURCES-OF-TRUTH.md`). The migration writes to that SoT — no competing source.
- **I2 (two-phase commit):** Not applicable — policy migrations are internal state evolution, not external side effects. Per-file atomicity (tmp-then-rename + fsync via `write_policy_file_atomic`) is the migration-framework analog. Same posture as ADRs 0011 + 0012 + 0020 + 0021 + 0022 + 0023.
- **I3 (schema versioning):** The migration does NOT bump the file's `version:` field (D75 inherited from ADR-0020 through ADRs 0021 + 0022 + 0023 + 0024 — content-additive migrations don't bump). The engine's `SUPPORTED_POLICY_SCHEMA_VERSIONS` remains `frozenset({1, 2})` — no extension required.
- **I5 (observable by default):** Every apply + downgrade logs at INFO with `affected_count` + already-present counts. Doctor's WARN-on-pending surfaces the migration ID. Cross-channel cap firings emit standard `policy_blocked` events with `rule: cross-channel-email-suppresses-linkedin` (or the inverse) + the channel-on-every-event invariant per ADR-0014 D33.
- **I6 (tests prove invariants):** `tests/test_migrations_policy_0006.py` covers surface compliance, apply / dry-run / downgrade paths, idempotence (BOTH rules canonical + ONE direction canonical [Shape B] + BOTH renamed [Shape C] + canonical-with-stale-consider-channels [Shape D]), refuse-loud on every failure mode, runner integration, engine integration (both rules instantiate as `CrossChannelTouchRule`), round-trip byte-identical on the real factory template, coexistence with Weeks 7-10's prior per-channel cap rules (the cross-migration coexistence QUINTET — `test_coexists_with_invite_cap_rule` + `test_coexists_with_dm_cap_rule` + `test_coexists_with_tw_dm_cap_rule` + `test_coexists_with_calendar_booking_cap_rule` + extended `test_coexists_with_all_prior_per_channel_caps`), the NO-stale-considered-channels-warning invariant per D-N6 (`TestNoStaleConsiderChannelsWarning`), AND the two-rule-structure pins (`test_inserts_both_rules_in_single_apply` + `test_removes_both_rules_in_single_downgrade` + `test_idempotent_when_only_one_direction_present` + `test_uses_consider_channels_not_source` + `test_no_max_units_field` + `test_no_window_hours_field` + `test_rule_class_is_cross_channel_touch_not_budget_window_cap`).
- **I7 (cost is a first-class concern):** Policy migrations do not emit `cost_incurred` events. The migration's rules, once active, consume `*_confirmed` ledger events (NOT `cost_incurred` events) per ADR-0003's `CrossChannelTouchRule.evaluate` — a different consumption surface than Weeks 7-10's budget rules.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains the ADR-0024 row. `docs/PILLAR-PLAN.md` §6 Pillar C row extends to "Week 11 ✓."

Does not weaken any invariant. The migration is structurally additive: TWO new rule entries (in the bidirectional pair) under existing shapes, leveraging existing rule classes (`CrossChannelTouchRule` with the existing `consider_channels:` + `window_days:` parameters), with existing event-consumption surfaces (`*_confirmed` ledger events per ADR-0003).

## Existing-operator seed

Per §D-N7 above, ADR-0020's three §D77 operator shapes expand to FOUR for Week 11 (one additional shape for the bidirectional-pair-transitional-state case):

- **Shape A (both canonical rules present):** the migration skips both. No operator action needed. **Majority case** — operators who copied the factory after Pillar A Week 2.
- **Shape B (one canonical rule present, the other absent — transitional / mixed):** the migration inserts ONLY the missing direction. No operator action needed; the migration brings the operator to Shape A. Plausible for operators with hand-rolled `cooldowns.yml` predating Pillar A Week 2 who manually installed one direction; OR operators who hand-edited their installed file + accidentally deleted one rule.
- **Shape C (both rules renamed):** the migration adds the canonical pair alongside the operator's renamed pair. Operator should review + delete one of the two pairs to clean up the dual-enforcement state. Same posture as Weeks 7-10's Shape 3.
- **Shape D (canonical name present but with stale field — e.g. stale `consider_channels:` value):** the migration skips per name-match idempotence; the operator's stale rule stays. The migration is silent on this case (D-N6). Pillar I doctor preflight is the future automated-detect surface.

For operators who want to skip the migration entirely (e.g. "I don't use cross-channel coordination; don't add these rules"), the existing-operator seed pattern per ADRs 0014 D36 + 0015 D41 + 0020 §"Existing-operator seed" + 0021 §"Existing-operator seed" + 0022 §"Existing-operator seed" + 0023 §"Existing-operator seed" applies:

```python
from datetime import datetime, timezone
from orchestrator.migrations.state import (
    MigrationState, mark_applied, save_state_atomic,
    load_state, DEFAULT_STATE_DIR,
)
from orchestrator.migrations.types import MigrationCategory

state = load_state(DEFAULT_STATE_DIR)
now = datetime.now(timezone.utc)
mark_applied(
    state, MigrationCategory.POLICY,
    "0006_add_cross_channel_email_linkedin_cooldown",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `policy/0006` as applied; `apply()` skips it; the operator's `cooldowns.yml` files stay unmodified.

**Recommended posture per operator profile:**

| Operator profile | Recommended action |
|---|---|
| New OSS operator (copied factory after Pillar A Week 2 — has Rules 5 + 6 active) | Run `apply()` normally. The migration sees Shape A + skips. The active factory rules continue mitigating R011. |
| Existing operator with hand-rolled `cooldowns.yml` (predating Pillar A Week 2) — no cross-channel rules | Run `apply()` normally. The migration inserts both rules per the bundled bidirectional shape. R011 mitigation activates. |
| Existing operator with one cross-channel direction installed (Shape B) | Run `apply()` normally. The migration inserts the missing direction. R011 mitigation completes. |
| Existing operator with renamed cross-channel rules (Shape C) | Run `apply()` normally. Then manually delete one of the two pairs in your installed `cooldowns.yml` to deduplicate. Or seed `policy/0006` per the snippet above (if you want to keep ONLY your renamed pair without dual-enforcement). |
| Existing operator with canonical-named rules but stale `consider_channels:` value (Shape D) | Run `apply()` normally. The migration skips; your rule stays. Optionally edit your rule to match the canonical shape; OR rely on Pillar I doctor preflight (future) to surface the misconfig. |
| Yang (current sole operator, as of 2026-05-22) | Recommended: run `apply()` normally. Yang's vault carries the factory file's active Rules 5 + 6 (Shape A) since Pillar A. The migration skips. |

## Migration / rollout

The Week 11 migration is `policy/0006_add_cross_channel_email_linkedin_cooldown`. Rollout shape:

1. Operator pulls Week 11 code. Engine code unchanged (D76 inherited: no SUPPORTED set extension). Pre-existing policy files (at v2 post-policy/0001) continue to load fine. Doctor preflight surfaces `policy/0006` as pending.

2. Operator runs `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             N pending: ..., policy/0006_add_cross_channel_email_linkedin_cooldown
   ```

3. **Quiesce concurrent writers if any** (per ADR-0012 D21):
   * Close editor sessions on policy YAML files.
   * Stop any daemon that reloads policy on SIGHUP (Pillar H future).

4. Operator runs dry-run preview:
   ```python
   from orchestrator.migrations import MigrationRunner, MigrationCategory
   runner = MigrationRunner()
   preview = runner.dry_run(MigrationCategory.POLICY)
   ```
   The preview reports affected_count = (number of operator policy files where at least one of the two rules is absent).

5. Operator applies for real:
   ```python
   runner.apply(MigrationCategory.POLICY)
   ```
   Each policy file's `rules:` list gains the missing rule(s) at the end (after Weeks 7-10's per-channel caps, if present). For Shape A files: no change. For Shape B files: one rule appended. For new-operator-shape files: both rules appended (Rule A first, then Rule B).

6. Operator inspects the migrated file:
   ```bash
   tail -20 ~/.outreach-factory/policies/cooldowns.yml
   #   - name: cross-channel-email-suppresses-linkedin
   #     type: cooldown.cross-channel-touch
   #     block_when:
   #       channel: linkedin
   #     consider_channels: [email]
   #     window_days: 14
   #     reason: "Prior email touch within 14d; LinkedIn would look coordinated"
   #   - name: cross-channel-linkedin-suppresses-email
   #     type: cooldown.cross-channel-touch
   #     block_when:
   #       channel: email
   #     consider_channels: [linkedin]
   #     window_days: 14
   #     reason: "Prior LinkedIn touch within 14d; email would look coordinated"
   ```

7. The engine reloads `cooldowns.yml` on next dispatcher invocation. The rules join the active rule set. Cross-channel coordination is enforced from this point forward.

The factory `cooldowns.example.yml` is unchanged — Rules 5 + 6 have been active since Pillar A Week 2. Operators copying the factory template in the future see the existing documented Rules 5 + 6.

Doctor preflight does not need to change for this ADR — the rules are shape-identical to other `cooldown.cross-channel-touch` rules (which doctor already validates structurally since Pillar A Week 2). The bidirectional-pair detect surface (warn on Shape B — only one direction installed) is a Pillar I doctor preflight enhancement deferred per D-N8.

A CLI (`python -m orchestrator.migrations apply`) remains deferred to Pillar I OSS bring-up.

The migration is reversible — `runner.rollback(MigrationCategory.POLICY, "0006_add_cross_channel_email_linkedin_cooldown", allow_rollback=True)` removes BOTH canonical-named rules. Operators rarely invoke; the defense-in-depth `allow_rollback=True` flag (ADR-0009 D4) makes accidental rollback a deliberate operator action.

## References

- ADR-0001 (policy engine architecture) — `policy_blocked` event shape; `RULE_REGISTRY` discriminator + `CrossChannelTouchRule` consumer.
- **ADR-0003 (channel as first-class policy predicate) — THE PREREQUISITE ADR.** Establishes `CrossChannelTouchRule` + `consider_channels:` field + the bidirectional-pair shape (Rules 5 + 6 in the factory) + the CC-01 through CC-12 test matrix. Week 11's migration writes INSTANCES of the rule class established by this ADR. The migration's RULE_A_BLOCK_TEXT / RULE_B_BLOCK_TEXT match the factory's Rules 5 + 6 byte-equivalent.
- ADR-0006 (budget rules + cost_incurred event) — `BudgetWindowCapRule` (Weeks 7-10's rule class). Week 11 diverges to `CrossChannelTouchRule`; ADR-0006 is the contrast.
- ADR-0009 (migration framework foundation) — D1-D7 + the per-category ADR-per-dispatcher convention.
- ADR-0010 (ledger migrations) — `migration_event` audit-trail emission is ledger-specific; policy migrations remain ledger-silent.
- ADR-0011 (vault migrations) — surgical-edit precedent for in-place YAML rewrites.
- ADR-0012 (policy migrations — surgical YAML rewrite) — the policy-migration architecture this ADR builds on.
- ADR-0014 (channel-as-event-field invariant) — D33's "every policy_blocked event MUST stamp channel" invariant.
- ADR-0015 (Pillar C LinkedIn-invite dispatcher) — D40's split-source convention (orthogonal to cross-channel rules; the cross-channel rule queries `*_confirmed` events directly).
- ADR-0020 (Pillar C Week 7 — per-channel policy migrations) — D72-D78. ADR-0024 inherits the structural decisions through ADRs 0021 + 0022 + 0023.
- ADR-0021 (Pillar C Week 8 — LinkedIn weekly DM cap) — D79-D83. ADR-0024 inherits the NO-stale-source posture (extended to NO-stale-considered-channels per D-N6).
- ADR-0022 (Pillar C Week 9 — Twitter weekly DM cap) — D84-D88. ADR-0024 inherits the cross-migration coexistence posture (extended to a quintet).
- ADR-0023 (Pillar C Week 10 — Calendar booking daily cap) — D89-D95. ADR-0024 inherits the structural-divergence-on-different-axes pattern; Week 10 diverged on window-unit + failure-mode-framing axes, Week 11 diverges on two-rules-per-migration + rule-class + field-semantics + factory-already-active axes.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies the bundled-bidirectional shape per D-N1).
- `docs/PILLAR-PLAN.md` §1 — I1 (single source of truth), I3 (schema versioning), I5 (observable by default), I6 (tests prove invariants).
- `docs/PILLAR-PLAN.md` §2 Pillar C — scope + exit criterion. Week 11 ✓.
- `docs/PILLAR-PLAN.md` §6 Pillar C row — updated to "Week 1 ✓ + Week 2 ✓ + ... + Week 10 ✓ + Week 11 ✓".
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — the risk this ADR's migration mitigates by extending Pillar A Week 2's factory-template mitigation to the full operator population.
- `docs/SOURCES-OF-TRUTH.md` row "Cooldown / budget / window policy" — the SoT this migration writes to.
- `orchestrator/policy/cross_channel.py` — `CrossChannelTouchRule` (the rule class Week 11's migration writes instances of). Unchanged since Pillar A Week 2.
- `orchestrator/migrations/policy/_policy_io.py` — `add_rule_block_text`, `remove_rule_block_text` (landed Week 7; consumed unchanged by Weeks 8 + 9 + 10 + 11). The primitives are rule-class-agnostic; Week 11's calls compose without modification.
- `orchestrator/migrations/policy/migration_0006_add_cross_channel_email_linkedin_cooldown.py` — the migration class + module-level constants (`RULE_A_NAME`, `RULE_A_TYPE`, `RULE_A_BLOCK_WHEN_CHANNEL`, `RULE_A_CONSIDER_CHANNELS`, `RULE_A_WINDOW_DAYS`, `RULE_A_REASON`, `RULE_A_BLOCK_TEXT`, + the parallel `RULE_B_*` set). Note: TWO constant sets (one per direction) — the Week 11 structural divergence from Weeks 7-10.
- `orchestrator/migrations/policy/__init__.py` — `MIGRATIONS = [MIGRATION_0001_ADD_ENGINE_COMPAT, MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP, MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP, MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP, MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP, MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN]`.
- `config-template/cooldowns.example.yml` — Rules 5 + 6 (lines 89-108; ACTIVE since Pillar A Week 2). NOT modified by Week 11 — the factory rules pre-existed the migration.
- `tests/test_migrations_policy_0006.py` — direct migration tests including the two-rule-structure pins + the rule-class divergence pins + the `TestNoStaleConsiderChannelsWarning` invariant per D-N6 + the cross-migration coexistence quintet (`test_coexists_with_invite_cap_rule` + `test_coexists_with_dm_cap_rule` + `test_coexists_with_tw_dm_cap_rule` + `test_coexists_with_calendar_booking_cap_rule` + `test_coexists_with_all_prior_per_channel_caps`) + the `TestSequentialAddRuleBlockTextComposition` pin for the two-sequential-calls invariant.
- `tests/test_migrations_replay.py::TestFullBatchApply::test_full_apply_writes_cross_channel_cooldown_rules_to_policy_file` — the parallel cross-channel sentinel test that pins the production-path two-rule write (alongside the existing `test_full_apply_writes_all_per_channel_cap_rules_to_policy_file` sentinel for per-channel caps; the cross-channel tuple shape differs from the per-channel-cap tuple shape per D-N4).
- Forward-references (planned):
  - **Pillar D's reply-coordination cap** (a future ADR) may add register-scoped variants of the cross-channel rules (e.g. "block follow-up LinkedIn DM when prior cold-pitch email landed within 14d"). The bundled-bidirectional-pair pattern established by Week 11 carries forward.
  - **Pillar D's `policy/0007_add_cross_channel_twitter_*_cooldown` migrations** — extend the cross-channel pair pattern to Twitter↔email, Twitter↔linkedin, Calendar↔email, Calendar↔linkedin pairs. Each pair ships as one bundled migration per the precedent.
  - **Pillar I doctor preflight enhancement** — warn on §D-N7 Shape B (transitional state with one direction present + other absent) — the FIRST per-rule-pair doctor surface. Same detect surface as ADR-0020's Shape 3 + Weeks 8-10's per-week Shape 3, but for paired rules.
  - **Pillar I OSS bring-up CLI (`python -m orchestrator.policy add-cross-channel-pair --channels X,Y --window-days N`)** — the operator-facing command-line surface for ad-hoc cross-channel-pair installation without a per-migration commit. Inherits the bundled-bidirectional-pair pattern.
  - **Pillar I OSS bring-up CLI (`python -m orchestrator.migrations apply`)** — the operator-facing command-line surface for the per-category dispatcher. Inherits all of Pillar B + C's primitives.
