# ADR-0020: Per-channel policy migrations — the first concrete migration (LinkedIn weekly invite cap)

- **Status:** Accepted
- **Date:** 2026-05-22
- **Pillar:** C (Multi-channel coherence — Week 7's per-channel policy migration; first of Weeks 7-11)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0014 (Week 1) shipped the channel-as-event-field invariant + linkedin-confirmed→li_invite_confirmed rename; ADR-0015 (Week 2) shipped the LinkedIn-invite dispatcher with `source="linkedin_invite"` cost emission per D40; ADR-0016 (Week 3) shipped the LinkedIn-DM dispatcher with `source="linkedin_dm"` cost emission; ADR-0017 (Week 4) shipped reconcile Pass D + Pass E for LinkedIn-invite + LinkedIn-DM; ADR-0018 (Week 5) shipped the Twitter-DM dispatcher with `source="twitter_dm"` cost emission + reconcile Pass F; ADR-0019 (Week 6) shipped the Calendar-booking dispatcher with `source="calendar_booking"` cost emission + the webhook-driven asymmetric-two-phase shape.

Per the PILLAR-PLAN, Pillar C's Week 7-11 range delivers the **per-channel policy migrations** — the operator-facing migrations that activate the cooldown / cap rule shapes Pillar A established. Week 7 ships the first one (LinkedIn invite weekly cap); Weeks 8-11 follow the same shape with different channels / scopes.

The structural shape of Pillar C Weeks 7-11 differs from Weeks 2-6 in three ways:

1. **Migration target.** Weeks 2-6 shipped dispatchers + ledger backfill migrations. Weeks 7-11 ship **policy migrations** — surgical YAML rewrites of operators' `~/.outreach-factory/policies/cooldowns.yml`. The substrate moves from the ledger (append-only event stream) to operator-edited YAML (the most operator-visible Pillar C surface).

2. **No new rule classes.** Weeks 7-11 add INSTANCES of existing rule classes (Pillar A's `BudgetWindowCapRule` / `CrossChannelTouchRule` etc.), not new classes. The engine's `RULE_REGISTRY` is unchanged; the migrations just write YAML that operators could have hand-written but typically wouldn't.

3. **No engine-version coordination needed.** Per ADR-0012 D22, every policy migration that bumps `version:` must extend `SUPPORTED_POLICY_SCHEMA_VERSIONS`. Week 7-11 migrations add CONTENT (a new rule entry under `rules:`) — not schema. The file's `version:` stays at its pre-migration value; the engine's SUPPORTED set is untouched.

This third point requires resolving an inconsistency in the handoff's D75/D76 recommendations:

- **D75 handoff-recommended:** every migration bumps the policy file version.
- **D76 handoff-recommended:** NO engine-version bump for Week 7.

Under ADR-0012 D22 ("every policy migration that bumps `version:` MUST ship coordinated with an `engine.SUPPORTED_POLICY_SCHEMA_VERSIONS` update"), these recommendations are contradictory: D75's "bump" forces D22's "extend SUPPORTED set" which contradicts D76's "no engine change." ADR-0020 resolves this by **revising D75**: per-channel rule additions (Weeks 7-11's canonical pattern) are content-additive, not schema-changing — they do NOT bump the file version. The handoff's "every migration bumps" rule was inherited from policy/0001's case (which DID change schema by introducing `engine_compat:`); it doesn't generalize to content-additive migrations.

Three concerns this ADR resolves:

- **D72.** Per-channel policy migration ID convention. The naming shape that Weeks 7-11 follow uniformly so a future contributor adding Week N+1 knows exactly what to call their migration file.
- **D73.** Rule insertion position. APPEND vs PREPEND vs sorted-by-name. The operator-facing diff shape.
- **D74.** Idempotence check semantics. Rule-name lookup vs shape-match vs operator-confirmation.
- **D75.** Version-bump policy. Revised from ADR-0012 D22's strict reading — only schema-changing migrations bump version.
- **D76.** Engine-version coordination — explicitly NO bump for Weeks 7-11 (existing rule shape, content-additive).
- **D77.** Existing-operator seed for operators who manually uncommented the factory rule per ADR-0008.
- **D78.** Downstream pillar impact for Pillar D / E / F / G / H / I / J.

Risks this ADR mitigates by design: **R-policy-rule-drift** (operator-installed `cooldowns.yml` drifts from the factory's commented examples; new operators rely on factory comments but existing operators don't refresh from upstream). Per-channel policy migrations close this gap by actively writing the canonical rule shape to operator-installed YAML.

## Decision

### D72. Per-channel policy migration ID convention — `policy/000N_add_<channel>_<rule-class>_<scope>.py`

Migration ID shape: `<NNNN>_add_<channel-abbrev>_<rule-class-abbrev>_<scope-abbrev>`.

Per-week trajectory for Pillar C Weeks 7-11:

| Week | ID | Rule added |
|------|----|------------|
| 7 | `policy/0002_add_li_invite_weekly_cap` | LinkedIn invite weekly throttle (100/week per ADR-0008) |
| 8 | `policy/0003_add_li_dm_weekly_cap` | LinkedIn DM weekly throttle (mirror of invite) |
| 9 | `policy/0004_add_tw_dm_weekly_cap` | Twitter DM weekly throttle |
| 10 | `policy/0005_add_calendar_booking_daily_cap` | Calendar booking daily throttle |
| 11 | `policy/0006_add_cross_channel_email_linkedin_cooldown` | Bidirectional cross-channel cooldowns (ADR-0003) |

The abbreviations match the dispatcher `source:` values established in Weeks 2-6: `li_invite`, `li_dm`, `tw_dm`, `calendar_booking`. The `_cap` / `_cooldown` suffix names the rule class shape (cap vs cooldown — different rule families in Pillar A's vocabulary).

**Rejected D72 alternatives:**

- **`policy/000N_add_<rule-name>`** — e.g. `policy/0002_add_linkedin_weekly_invite_cap` (use the rule's canonical `name:` field directly). **Rejected** because rule names are operator-facing (they surface in `policy_blocked` events). The migration ID is internal infrastructure; using the rule name couples the framework to operator-visible artifacts in a way that limits future renames. The convention's `<channel>_<class>_<scope>` shape derives identity from STRUCTURAL properties (which channel, which rule class) — those properties are invariant even when the rule's user-visible name evolves.

- **`policy/000N_<sequential>`** — e.g. `policy/0002`, `policy/0003`, ... without descriptive suffix. **Rejected** because the convention's purpose is operator readability + diff legibility. A bare-numeric ID forces the reader to consult the file's contents to understand intent; the descriptive suffix surfaces intent at the `git log` + `migrations.state.json` levels.

- **`policy/000N_pillar_c_week_M_<descriptor>`** — embed the originating week in the ID. **Rejected** because week-numbering is internal scheduling; the migration's STRUCTURAL identity (which channel, which rule) is what matters at apply time. Operators who skip ahead and apply Week 11's migration before Week 7's see a "policy/0006" ID that's about CONTENT, not WEEK — same as the ledger / vault migration conventions.

### D73. Rule insertion position — APPEND after last active rule

Migration appends the new rule entry AFTER the LAST active rule in the operator's `rules:` list. The `_policy_io.add_rule_block_text` primitive finds the last `  - name:` entry's last continuation line and inserts immediately after it.

**Why APPEND:**

- **Operator-installed-first ordering.** Operators who write rules in their `cooldowns.yml` expect their rules to come first in evaluation order (per ADR-0001's "first Block wins" semantics, ordering is operator-visible policy). The migration's rules go at the end so the operator's existing ordering is unchanged.

- **Lowest-priority block.** Per-channel caps are "you sent too many" warnings, not "this specific send is wrong" verdicts. Putting them at the end of the first-Block-wins evaluation order means a more-specific operator-written rule (e.g. "block this prospect specifically") fires first; the cap fires only when no more-specific rule applies. That's the structurally correct precedence: prospect-level decisions trump aggregate-level decisions.

- **Visual stability.** Inserting at a deterministic position (after last active rule, before commented templates) makes the operator-facing diff predictable. An operator running multiple per-channel migrations (Weeks 7-11) sees their `cooldowns.yml` grow in a known, predictable way — the new rules cluster at the end of the rules list.

**Rejected D73 alternatives:**

- **PREPEND (insert before first rule).** **Rejected** because it changes the operator's evaluation order — every operator-installed rule is suddenly evaluated AFTER the migration's rules. Operators who carefully ordered their rules see those decisions silently inverted; a migration that mutates evaluation semantics that aggressively is unsafe by default.

- **Sorted-by-name (alphabetical insert).** **Rejected** because it interleaves migration-added rules with operator-installed rules unpredictably. An operator's `business-hours-only` rule (Pillar A's Rule 7) would sort between `cross-channel-email-suppresses-linkedin` and `domain-cooldown` — surprising for an operator who reads their file top-to-bottom. Alphabetical also fights with the "first Block wins" semantic by re-ordering verdicts.

- **End-of-file (after commented-out templates).** **Rejected** because the new rule visually lives at the file's bottom, BELOW the commented-out templates that documentation-only. Operator's mental model is "active rules at top; reference templates at bottom" — putting the migration's active rule below the templates inverts this. The APPEND-after-last-active-rule position respects the mental model.

### D74. Idempotence check — rule-name lookup (canonical name match)

The migration's per-file idempotence check walks the parsed `data["rules"]` list and tests `r.get("name") == "linkedin-weekly-invite-cap"`. Match → skip the file. No match → append.

**Why rule-name lookup:**

- **Cheap and obvious.** No regex; no fuzzy matching. The parsed dict is already in hand from `read_policy_file`; the check is one walk over a small list.

- **Respects operator agency.** An operator who manually uncommented + tuned the factory rule (e.g. `max_units: 80` for a more conservative posture) keeps their tuning. The migration recognizes their version by name + skips — no overwrite.

- **D74 specifically addresses the operator-renamed case.** Operators may rename the rule (e.g. `linkedin-weekly-cap-100` instead of `linkedin-weekly-invite-cap`). The migration treats name-mismatch as "rule not present" and ADDS the canonical-named version alongside. The operator now has two rules with overlapping enforcement; this is a known tradeoff. ADR-0020 §"Existing-operator seed" documents the operator-side remediation (delete one or the other).

**Rejected D74 alternatives:**

- **Shape-match (filter the parsed rules for `type: budget.window-cap` + `source: linkedin_invite` + `block_when.channel: linkedin`).** **Rejected** as the SOLE idempotence check because operators who tuned the rule's `source:` field (e.g. to a custom emit source for a pre-Week-2 setup) would have their version not match the canonical shape; the migration would add a duplicate. Shape-match alone is too brittle. ADR-0020 keeps shape-match as a possible future enhancement: emit an info-log noting "operator has a rule matching the canonical filter under a different name `<name>`" for awareness, but the idempotence check is still name-based.

- **Structural equivalence (rule's normalized YAML form matches the migration's exact bytes).** **Rejected** as too strict. Operators who reformatted whitespace, reordered fields, or added comments inside the rule entry would fail equivalence and trigger duplicate addition. The migration cares about SEMANTIC presence ("a rule named X is in the file"), not bytewise equivalence.

- **Operator-confirmation prompt (the migration prompts before adding).** **Rejected** because migrations run non-interactively (the framework's batch-apply semantics don't support per-file prompts). Defer to Pillar I's OSS bring-up if interactive operator confirmation becomes a need; for Week 7's headless runner, automatic-add is the correct posture.

### D75. Version-bump policy — bump ONLY on schema changes (revised from ADR-0012 D22's strict reading)

Per-channel rule additions (Weeks 7-11's pattern) do NOT bump the file's `version:` field. The file's pre-migration and post-migration shape is structurally identical to the engine — a new rule entry under an existing `rules:` list, parseable by the existing `RULE_REGISTRY`-driven loader.

**Why revise D75:**

The handoff recommended "every migration bumps." Under ADR-0012 D22 ("every policy migration that bumps `version:` MUST ship coordinated with an `engine.SUPPORTED_POLICY_SCHEMA_VERSIONS` update"), strict every-migration-bump would force 5 engine code changes across Weeks 7-11 — each adding the new version to the SUPPORTED set. This is structurally unmotivated: no engine change is needed; the rule shape is already supported.

The revised contract:

- **Migrations that introduce a new top-level field or restructure existing shapes bump version** (the policy/0001 case — added `engine_compat:`). These DO require coordinated `SUPPORTED_POLICY_SCHEMA_VERSIONS` extension per D22.
- **Migrations that add content under existing shapes do NOT bump version** (the policy/0002-0006 case — add rule entries). These leave the engine's SUPPORTED set untouched.

The `_policy_io.bump_version_text` primitive remains available for the former case; it's just not invoked from the latter. A future contributor who is uncertain whether their migration is "schema-changing" or "content-additive" asks: *does the engine code need to change to parse the post-migration file?* If yes → schema change → bump version + extend SUPPORTED. If no → content-additive → no bump.

**Rejected D75 alternatives:**

- **Every migration bumps (handoff's original recommendation).** **Rejected** per the analysis above — forces SUPPORTED extension on every content-additive migration, polluting the engine's version-acceptance set without semantic motivation.

- **No migration ever bumps; rely on engine_compat's `min_engine_version` only.** **Rejected** because legitimately-schema-changing migrations (like policy/0001 itself) need version-bump semantics to enforce the per-file shape contract. Removing version-bump entirely would force every future schema change to go through a different mechanism (e.g. a per-rule-class compatibility flag), proliferating concepts.

- **Operator-deliberate: every migration has a `bumps_version: bool` field; contributors set it explicitly.** **Rejected** as redundant given the structural question is decidable: does the engine code need to change? The `bumps_version` flag would just re-encode that question as data; the contributor still answers it.

### D76. Engine-version coordination — NO engine bump for Week 7 (or Weeks 8-11)

Week 7's migration does NOT extend `orchestrator.policy.engine.SUPPORTED_POLICY_SCHEMA_VERSIONS`. The set stays at `frozenset({1, 2})` (the post-policy/0001 state). Operators between git-pull and migration-apply have files at version 2 (already migrated by policy/0001) or version 1 (pre-migration); both load fine.

This follows directly from D75 (content-additive migration → no version bump → no SUPPORTED extension).

**Rejected D76 alternatives:**

- **Bump SUPPORTED set anyway as a hygiene measure.** **Rejected** — extending the set without bumping any file's version means the engine accepts version 3 files that no one ever produces. The set should grow lockstep with actual file versions.

- **Bump file version + extend SUPPORTED set anyway for forward consistency.** **Rejected** — see D75. Forcing version bumps on content-additive migrations creates per-week engine code changes that have no semantic purpose.

- **Use a per-rule-class `min_engine_version` requirement field instead.** **Rejected** as scope creep — Pillar A's rule classes don't currently consult engine-compat; introducing per-rule version-requirement semantics is a future Pillar I enhancement (engine-version-compat refuse logic). Week 7's migration is not the right place to ship that infrastructure.

### D77. Existing-operator seed — reconciling pre-Week-7 manual uncomments

Operators who manually uncommented the factory `Rule 12b` per ADR-0008's suggested rollout already have a `linkedin-weekly-invite-cap` rule in their `cooldowns.yml`. Three possible pre-Week-7 shapes:

1. **Canonical name, canonical filter** (`source: linkedin`): the operator copied the factory template verbatim. The factory's `source: linkedin` is stale because Pillar C Week 2's dispatcher emits `source="linkedin_invite"` (per ADR-0015 D40). Operators in this state have an inert rule (the source-filter mismatch means the rule fires on zero events).

2. **Canonical name, Pillar-C-aware filter** (`source: linkedin_invite`): the operator updated their version when Pillar C Week 2 shipped, or they hand-wrote the rule using the dispatcher's emit value. Their rule fires correctly.

3. **Renamed, custom filter:** the operator wrote their own rule with a different name + filter (e.g. `linkedin-cap-90-per-week` with `source: linkedin_invite, max_units: 90`). Their rule fires correctly under their own name.

The migration's behavior across all three:

- **Shape 1 (canonical name, stale source):** the migration's name-match idempotence check (D74) identifies the rule + skips. The operator's stale-source rule stays untouched. **Operator remediation:** manually update `source: linkedin` → `source: linkedin_invite` to make their rule fire. ADR-0020's §Migration/rollout documents this; Pillar I doctor preflight can warn on the stale-source state in a future iteration.

- **Shape 2 (canonical name, correct source):** the migration's name-match identifies + skips. The file is byte-identical post-migration. **Operator remediation:** none needed.

- **Shape 3 (renamed):** the migration adds the canonical-named rule. The operator now has TWO rules with overlapping enforcement (their renamed + the canonical). Both fire the same Block on the same evaluation. **Operator remediation:** delete one of the two rules. (The canonical version is operator-acceptable to delete — it's the migration's default; the operator's renamed version preserves their tuning. Or vice versa — operator's choice.) ADR-0020 documents the dual-rule transitional state; doctor preflight (Pillar I) is the natural place to detect + nudge.

The factory file's `cooldowns.example.yml` `Rule 12b` comment block ships updated as part of Week 7 — `source: linkedin` → `source: linkedin_invite` — so new operators copying the factory get the correct, Pillar-C-aware shape. Operators who copied pre-Week-7 are in Shape 1 (above) until they manually update.

### D78. Downstream pillar impact

Per the ADR-0009 convention (every Pillar B + C ADR explicitly names cross-pillar impact):

* **Pillar D (reply + conversation handling).** Reply classifiers may need their own per-channel policy rules (e.g. "if reply received in last 14d, suppress further sends in same channel"). Pillar D authors follow the same `policy/000N_add_<channel>_<rule-class>_<scope>.py` pattern; the `_policy_io.add_rule_block_text` primitive composes with their needs. The D75 revision (content-additive migrations don't bump version) carries to Pillar D's reply-policy migrations.

* **Pillar E (discovery quality + lineage).** Pillar E may add discovery-budget rules (e.g. "no more than $X/week on PDL enrichment per Person"). The `BudgetWindowCapRule` rule class composes with discovery sources (`source: pdl`, `source: apollo`) per ADR-0006; Pillar E's policy migrations are the per-channel-cap shape with discovery sources. Same primitive surface; same D75/D76 posture.

* **Pillar F (voice corpus + draft quality).** Voice-fidelity policy rules (e.g. "block sends whose voice-fidelity score is below X") may need new rule classes (a `voice.requires-minimum-score` shape). Adding a new rule CLASS bumps the engine; the policy migration that activates an INSTANCE of it follows the D75 "schema change → bump" path. The Week 7 pattern doesn't directly apply; ADR-0020 is the precedent for the content-additive case.

* **Pillar G (observability).** OTel + Prometheus will emit per-rule metrics; the per-channel cap rules surfaced by Weeks 7-11 produce `policy_blocked` events with stable `rule:` field values (the canonical rule names). The funnel CLI's `--breakdown gate_reason` view surfaces them without new code (per ADR-0001). Pillar G's dashboards group by `rule:` field.

* **Pillar H (daemon + scheduled jobs).** Pre-API-call gating (per ADR-0006 §"Where budget rules fire") may consume the same per-channel rules at additional gates. The migration's rule entries don't change; only the EVALUATION sites grow. Pillar H is additive; no migration-framework change.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant policy directories; each tenant's `cooldowns.yml` gets the Weeks 7-11 migrations independently. The doctor's refuse-on-pending applies uniformly. The CLI's `python -m orchestrator.migrations apply` lands here (deferred from ADR-0012). The Pillar I "engine-version-compat refuse" feature consults each policy file's `engine_compat:` block to refuse incompatible files at engine load.

* **Pillar J (security + compliance).** GDPR-forget on a policy file doesn't typically apply (rules don't contain PII). A policy migration that removes a deprecated rule class is structurally reversible — `is_reversible=True` carries.

## Alternatives considered

### Alternative 1: Defer per-channel policy migrations to Pillar I (OSS bring-up)

Wait for Pillar I to ship the doctor preflight + CLI + version-compat enforcement, then bundle all per-channel migrations into one big "bring-up your cooldowns.yml" step. **Rejected** because:

- The Pillar A exit criterion's "zero hardcoded policy in skills" was closed by ADR-0008 — but the migration that actually delivers the cap to operators is in Pillar C's range. Deferring further means the cap is "documented + factory-shipped" but not "operator-active by default."
- Pillar I is 36 weeks out (Weeks 43-48 per PILLAR-PLAN). The operator-friction window (operators with linkedin manifests but no active cap rule) is a year-long failure mode if deferred.
- Per-channel migrations are independently shippable. Bundling them into one Pillar I megamigration creates exit-criterion coupling Pillar I doesn't need.

### Alternative 2: Auto-uncomment the factory rule (single migration scans all .yml files; uncomments any commented `linkedin-weekly-invite-cap` block)

**Rejected** because:

- Operators may have removed the commented block entirely (their `cooldowns.yml` is a clean operator-edited copy, not a fork-of-factory). The auto-uncomment migration would have nothing to do for those operators — defeating the migration's purpose.
- The factory file's commented blocks are documentation; mutating them in operators' installed copies blurs the documentation/active-policy distinction.
- An "uncomment if found, otherwise add" hybrid is more complex than just "add unless name-match" — Occam's razor.

### Alternative 3: Single mega-migration for all Pillar C policy rules (one file: `policy/0002_add_all_pillar_c_caps.py`)

Bundle the 5 per-channel rules (Weeks 7-11) into one migration that adds all five at once. **Rejected** because:

- Per-week shipping discipline (PILLAR-PLAN §3 TDD shape) is the project's load-bearing process — each week's commit is independently reviewable. A 5-week migration would be a single 5-week commit that's hard to review per-section.
- Migrations are reversible at the per-migration level. An operator who wants to roll back just the LinkedIn DM cap (Week 8) without affecting the LinkedIn invite cap (Week 7) needs them as separate migrations.
- Future per-channel additions (a hypothetical Pillar D channel) compose cleanly with the existing pattern; a mega-migration would need to be amended each time, polluting its semantic identity.

### Alternative 4: Migration adds the canonical rule's content + emits a `migration_event` ledger entry to record the operator's substrate change

Add the rule + emit `migration_event` per ADR-0010 D17 for audit. **Rejected** because:

- Policy migrations are explicitly ledger-silent per ADR-0012 I5: "the `migration_event` audit-trail emission contract is **ledger-specific** — policy migrations write to YAML files, not to the ledger, and do NOT emit `migration_event` events." Week 7 inherits this posture.
- Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories. Premature emission of `migration_event` from policy migrations would create a per-category emission inconsistency the framework deliberately avoided.

### Alternative 5: Ship the rule shape with `source: linkedin` (matching ADR-0008's factory rule) instead of `source: linkedin_invite`

Preserve backward-compat with the factory's commented rule + the LIA-01 / LIA-02 matrix test rows. **Rejected** because:

- Pillar C Week 2's dispatcher emits `source="linkedin_invite"` per ADR-0015 D40. A rule with `source: linkedin` filter matches zero events from the real dispatcher; the rule activates but never fires — the exact failure mode the cap exists to prevent.
- ADR-0008 was written before ADR-0015 D40 established the per-channel source-naming convention. The factory's `source: linkedin` is stale; Week 7 corrects it.
- Operators who manually uncommented the factory rule (Shape 1 in §D77) have an inert rule today; the migration's `source: linkedin_invite` actually delivers the protection.
- LIA-01 / LIA-02 matrix tests use their own fixture YAML with `source: linkedin`. Those tests pin the rule's evaluation contract for synthetic cost ledger; they don't test the production dispatcher's emit value. The matrix tests remain valid; the migration uses the production-correct value.

### Alternative 6: Migration also updates the factory `cooldowns.example.yml`'s `Rule 12b` comment block to use `source: linkedin_invite`

Make the factory's commented documentation match the dispatcher's emit value. **Accepted as a bundled change.** This isn't a separate ADR-able decision but an obvious correctness fix: the factory's documentation should match the runtime. Bundled into Week 7's commit + recorded in the migration / rollout section.

## Consequences

### Positive

- **Operators using LinkedIn outreach get the cap enforcement automatically** when they run the next batch of pending migrations. No manual policy-file editing required.
- **The migration is content-additive, not schema-changing.** Files stay at their pre-migration version; the engine's SUPPORTED set is unchanged; no flag-day risk.
- **Future per-channel migrations (Weeks 8-11) inherit the working pattern.** D72-D78 define a reusable shape; each subsequent week is a smaller delta on the precedent.
- **Operator-installed rule order is preserved.** APPEND semantics mean operator-deliberate ordering decisions are honored.
- **Idempotent across the operator-state shapes catalogued in §D77.** Re-running the migration produces no surprises regardless of whether the operator pre-uncommented, renamed, or did nothing.
- **The `add_rule_block_text` + `remove_rule_block_text` primitive surface is reusable.** ADR-0012 D20 deferred this; ADR-0020 lands it. Subsequent policy migrations (Weeks 8-11; Pillar D / E / F reply / discovery / voice migrations) compose without new helpers.

### Negative

- **The dual-rule transitional state for operators in §D77 Shape 3 (renamed)** requires operator action to deduplicate. Documented in ADR-0020 + the migration's notes; doctor preflight (Pillar I) is the natural future warning surface.
- **Operators in §D77 Shape 1 (canonical name with stale `source: linkedin`)** keep their inert rule + need to manually update the source to `linkedin_invite`. The migration's name-match idempotence preserves their version (the right call — don't silently mutate operator-tuned values) but means they don't get automatic remediation. Pillar I's doctor preflight is the future home for the warning.
- **The factory's commented rule changes between pre-Week-7 and Week-7 versions** (`source: linkedin` → `source: linkedin_invite`). Operators who copy the factory file at different points see different commented examples. **Mitigation:** the change is in the file's git history; the difference is one field on one commented-out rule.
- **The Pillar A LIA-01 / LIA-02 matrix tests use a non-canonical fixture source value (`source: linkedin`).** Those tests remain valid (they test the rule's evaluation contract synthetically), but they don't exercise the production dispatcher's emit value. **Mitigation:** Week 7's `tests/test_migrations_policy_0002.py::TestEngineIntegration::test_engine_loads_migrated_file` + `test_rule_class_is_budget_window_cap` pin the production-correct shape end-to-end.

### Neutral / observability

- The migration logs at INFO with `affected_count` + `already_present` counts. The runner's pending / dry-run / apply reports surface the migration ID + description as expected.
- Policy migrations remain ledger-silent (no `migration_event` events) per ADR-0012 I5; Pillar G is the future home for per-migration metrics on non-ledger categories.
- The rule's `policy_blocked` event shape is unchanged from existing budget-window-cap rules (per ADR-0006 §"Budget blocks emit the standard `policy_blocked` event"). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=linkedin-weekly-invite-cap` without new code.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAML remains the SoT for "what rules are active" (per `docs/SOURCES-OF-TRUTH.md`). The migration writes to that SoT — it doesn't introduce a competing source.
- **I2 (two-phase commit):** Not applicable — policy migrations are internal state evolution, not external side effects. Per-file atomicity (tmp-then-rename + fsync via `write_policy_file_atomic`) is the migration-framework analog. Same posture as ADR-0011 + ADR-0012.
- **I3 (schema versioning):** The migration does NOT bump the file's `version:` field (D75 revised — content-additive migrations don't bump). The file's existing `version:` + `engine_compat:` block continue to declare its schema generation. The engine's `SUPPORTED_POLICY_SCHEMA_VERSIONS` remains `frozenset({1, 2})` — no extension required.
- **I5 (observable by default):** Every apply + downgrade logs at INFO with `affected_count` + already-present counts. Doctor's WARN-on-pending surfaces the migration ID. Per-channel cap firings emit standard `policy_blocked` events.
- **I6 (tests prove invariants):** `tests/test_migrations_policy_0002.py` (42 tests) covers surface compliance, apply / dry-run / downgrade paths, idempotence (canonical-name + operator-renamed + already-present), refuse-loud on every failure mode, runner integration, engine integration (the rule loads + instantiates as `BudgetWindowCapRule`), and round-trip byte-identical on the real factory template. `tests/test_migrations_policy_io.py::TestAddRuleBlockText` + `TestRemoveRuleBlockText` (18 tests) cover the new primitive surface in isolation.
- **I7 (cost is a first-class concern):** Policy migrations do not emit `cost_incurred` events — they're local IO with no external API calls. The migration's rule, once active, consumes `cost_incurred` events with `source="linkedin_invite"` per ADR-0006's existing contract.
- **I8 (decisions documented):** This ADR. ADR-0019 References gains an entry pointing forward. `docs/adr/README.md` gains the ADR-0020 row.

Does not weaken any invariant. The migration is structurally additive: a new rule entry under existing shapes, leveraging existing rule classes, with existing event schemas.

## Migration / rollout

The Week 7 migration is `policy/0002_add_li_invite_weekly_cap`. Rollout shape:

1. Operator pulls Week 7 code. Engine code unchanged (D76: no SUPPORTED set extension). Pre-existing policy files (at v2 post-policy/0001) continue to load fine. Doctor preflight surfaces `policy/0002` as pending.

2. Operator runs `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             N pending: ..., policy/0002_add_li_invite_weekly_cap
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
   The preview reports affected_count = (number of operator policy files that don't yet have the canonical rule).

5. Operator applies for real:
   ```python
   runner.apply(MigrationCategory.POLICY)
   ```
   Each policy file's `rules:` list gains one new entry at the end.

6. Operator inspects the migrated file:
   ```bash
   tail -10 ~/.outreach-factory/policies/cooldowns.yml
   #   - name: linkedin-weekly-invite-cap
   #     type: budget.window-cap
   #     block_when:
   #       channel: linkedin
   #     source: linkedin_invite
   #     window_days: 7
   #     max_units: 100
   #     reason: "LinkedIn weekly invite cap (...)"
   ```

7. The engine reloads `cooldowns.yml` on next dispatcher invocation. The rule joins the active rule set. LinkedIn invite sends from this point forward are gated by the per-week cap.

**Existing operators (per §D77 shapes):**

- **Shape 1 (canonical name, stale source):** the migration skips the file. Operator should manually update `source: linkedin` → `source: linkedin_invite` to make their existing rule fire correctly. Recommended one-line edit; the rule's `name:` stays the same.
- **Shape 2 (canonical name, correct source):** the migration skips the file. No operator action needed.
- **Shape 3 (renamed):** the migration adds the canonical-named rule. Operator should review + delete one of the two overlapping rules to clean up the dual-enforcement state.

The factory `cooldowns.example.yml`'s commented `Rule 12b` ships with the corrected `source: linkedin_invite` value as part of Week 7's commit. Operators copying the factory template in the future get the right shape.

Doctor preflight does not need to change for this ADR — the rule is shape-identical to other `budget.window-cap` rules, which doctor already validates structurally.

A CLI (`python -m orchestrator.migrations apply`) remains deferred to Pillar I OSS bring-up.

The migration is reversible — `runner.rollback(MigrationCategory.POLICY, "0002_add_li_invite_weekly_cap", allow_rollback=True)` removes the canonical-named rule. Operators rarely invoke; the defense-in-depth `allow_rollback=True` flag (ADR-0009 D4) makes accidental rollback a deliberate operator action.

## References

- ADR-0001 (policy engine architecture) — `policy_blocked` event shape; `RULE_REGISTRY` discriminator + `BudgetWindowCapRule` consumer.
- ADR-0003 (channel as first-class policy predicate) — `block_when.channel:` semantics consumed by the migrated rule.
- ADR-0006 (budget rules + cost_incurred event) — `BudgetWindowCapRule` units mode + `cost_incurred` schema. The rule the migration adds is an instance of this class.
- ADR-0008 (LinkedIn weekly invite cap migration from hardcoded constant to policy rule) — the original cap rule shape this migration delivers to operators. ADR-0020 corrects the factory's stale `source: linkedin` → `source: linkedin_invite`.
- ADR-0009 (migration framework foundation) — D1-D7 + the per-category ADR-per-dispatcher convention. ADR-0020 is the second policy-specific ADR (after ADR-0012).
- ADR-0010 (ledger migrations) — `migration_event` audit-trail emission is ledger-specific; policy migrations remain ledger-silent.
- ADR-0011 (vault migrations) — surgical-edit precedent for in-place YAML rewrites.
- ADR-0012 (policy migrations — surgical YAML rewrite, helper-module dispatcher, engine version-range coordination) — the policy-migration architecture this ADR builds on. D20's deferral of `add_rule_block_text` is landed in this commit.
- ADR-0014 (channel-as-event-field invariant) — D33's "every policy_blocked event MUST stamp channel" invariant.
- ADR-0015 (Pillar C LinkedIn-invite dispatcher) — D40's `source="linkedin_invite"` cost emission convention. The migration's `source:` filter matches this exactly.
- ADR-0016 (Pillar C LinkedIn-DM dispatcher) — `source="linkedin_dm"` — the channel-naming pattern this ADR's Week 8 will mirror.
- ADR-0018 (Pillar C Twitter-DM dispatcher) — `source="twitter_dm"` — the channel-naming pattern this ADR's Week 9 will mirror.
- ADR-0019 (Pillar C Calendar-booking dispatcher) — `source="calendar_booking"` — the channel-naming pattern this ADR's Week 10 will mirror.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies refuse-loud on inconsistent state).
- `docs/PILLAR-PLAN.md` §1 — I1 (single source of truth), I3 (schema versioning), I5 (observable by default), I6 (tests prove invariants).
- `docs/PILLAR-PLAN.md` §2 Pillar C — scope + exit criterion. Week 7 ✓.
- `docs/PILLAR-PLAN.md` §6 Pillar C row — updated to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4 ✓ + Week 5 ✓ + Week 6 ✓ + Week 7 ✓".
- `docs/SOURCES-OF-TRUTH.md` row "Cooldown / budget / window policy" — the SoT this migration writes to.
- `orchestrator/migrations/policy/_policy_io.py` — `add_rule_block_text`, `remove_rule_block_text` (new in Week 7), `_RULES_HEADER_RE`, `_RULE_ENTRY_HEAD_RE`, `_is_rule_continuation_line`. The deferred-from-ADR-0012-D20 surface is now landed.
- `orchestrator/migrations/policy/migration_0002_add_li_invite_weekly_cap.py` — the migration class + module-level constants (`RULE_NAME`, `RULE_TYPE`, `RULE_SOURCE`, `RULE_BLOCK_WHEN_CHANNEL`, `RULE_WINDOW_DAYS`, `RULE_MAX_UNITS`, `RULE_REASON`, `RULE_BLOCK_TEXT`).
- `orchestrator/migrations/policy/__init__.py` — `MIGRATIONS = [MIGRATION_0001_ADD_ENGINE_COMPAT, MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP]`.
- `config-template/cooldowns.example.yml` — Rule 12b's commented block updated to `source: linkedin_invite` as part of Week 7.
- `tests/test_migrations_policy_0002.py` — 42 direct migration tests.
- `tests/test_migrations_policy_io.py::TestAddRuleBlockText` + `TestRemoveRuleBlockText` — 18 primitive tests.
- Forward-references (planned):
  - **ADR-0021** (Pillar C Week 8) — LinkedIn DM weekly cap migration. Same shape; D72-D74 directly inherited; D75/D76 inherited (content-additive); D77 specific to LinkedIn DM operators.
  - **ADR-0022** (Pillar C Week 9) — Twitter DM weekly cap migration.
  - **ADR-0023** (Pillar C Week 10) — Calendar booking daily cap migration.
  - **ADR-0024** (Pillar C Week 11) — Cross-channel email/LinkedIn cooldown migration (bidirectional). The cross-channel shape adds two rules in one migration — slight variation on the single-rule pattern but same primitives.
  - Pillar I doctor preflight enhancement — warn on §D77 Shape 1 (stale-source rule) + Shape 3 (dual-rule transitional state). The detection logic is shape-match on the parsed `rules` list; the warning is operator-actionable.
  - Pillar I OSS bring-up CLI (`python -m orchestrator.migrations apply`) — the operator-facing command-line surface for the per-category dispatcher. Inherits all of Pillar B + C's primitives.
