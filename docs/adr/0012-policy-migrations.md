# ADR-0012: Policy migrations — surgical YAML rewrite, helper-module dispatcher, engine version-range coordination

- **Status:** Accepted
- **Date:** 2026-05-20
- **Pillar:** B (Migration framework — Week 4 policy dispatcher + first real policy migration)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0009 (Week 1) shipped the migration-framework foundation; ADR-0011 (Week 2) shipped the vault per-category dispatcher + first real vault migration; ADR-0010 (Week 3) shipped the ledger per-category dispatcher + first real ledger migration. Per ADR-0009 D7, per-category ADRs land alongside per-category dispatchers + first concrete migrations. Pillar B Week 4 ships the **policy** per-category dispatcher.

The policy surface is structurally different from both predecessors:

1. **Policy YAML is the SoT for "what rules are active"** (per `docs/SOURCES-OF-TRUTH.md` row "Cooldown / budget / window policy"). Unlike the vault (denormalized from ledger; reconcile heals) and unlike the ledger (append-only with backup as the recovery vehicle), policy YAML has **no framework-level recovery primitive**. A corrupting migration is recoverable only via the operator's own git history of their `~/.outreach-factory/policies/` directory. Per-file atomicity (tmp-then-rename) is the only safety belt the framework provides.

2. **Operator-edited content is the dominant concern.** The factory-shipped `config-template/cooldowns.example.yml` is 275 lines, of which ~80% are commented-out rule templates the operator can uncomment + tune (Rules 7–13). A migration that uses `yaml.safe_dump` to round-trip the file would destroy every comment, normalize quote styles, and reorder fields — the operator's editing workflow would be unrecoverably damaged. The surgical-edit pattern ADR-0011 D10 specifies for vault frontmatter applies here with even higher stakes.

3. **The policy engine actively consumes the file's `version:` field** to gate "this build knows how to read this file." `orchestrator/policy/engine.py:load_rules_from_yaml` raises `ValueError` on any version it doesn't recognize. A migration that bumps `version: 1 → version: 2` without coordinated engine support would brick every operator's send loop the moment they pull the new code, before they've run the migration. The vault analog (the `schema_version:` field on Person notes) has no such consumer — it's a marker for future migrations to read, not a gate the engine checks. ADR-0012 must resolve the coordination question.

4. **Multiple files per category, each with independent `version:`.** A policy directory typically contains `cooldowns.yml`; operators may add `extras.yml`, `overrides.yml`, etc. The engine loads each via `load_rules_from_yaml`, which reads the file's own `version:`. A migration may target ONE file (e.g. add a rule to a specific file) or ALL (e.g. bump every file to a new schema). This ADR's first concrete migration bumps every file uniformly — the "all" case.

5. **Pillar B's exit-criterion vehicle (Weeks 5–6 synthetic replay) consumes this surface.** Per PILLAR-PLAN §2 Pillar B, replay against a synthetic before-state vault is the exit gate. Week 4's helper module + first migration MUST compose cleanly with a synthetic-policy-dir constructor in that vehicle. Every helper accepts an arbitrary `policy_dir` path; the migration body operates on the path it's given without ambient config lookups.

Three concerns this ADR resolves:

- **The per-category dispatcher boundary for policy has a shape now** (D19). Helper module `_policy_io.py`, mirroring ADR-0011 D8 / ADR-0010 D14.
- **The first concrete policy migration shape demonstrates the pattern** (D18). `policy/0001_add_engine_compat_field` exercises every contract this ADR pins: surgical add + version bump, per-file atomicity, per-file idempotence, refuse-loud on inconsistent state, reversibility, refuse-on-missing-policy-dir.
- **The engine version-range coordination contract is named** (D22 — the new decision item for this ADR). Every policy migration that bumps `version:` MUST ship coordinated with an `engine.SUPPORTED_POLICY_SCHEMA_VERSIONS` update that ADDS the new version to the accepted set. Forward-compat range acceptance prevents the operator's send loop from breaking during the warn-on-pending window between git-pull and migration-apply.

Risks this ADR mitigates: **R002 (vault frontmatter drift)** is unchanged — vault work is ADR-0011's surface. **R005 (ledger schema bump regret)** is also unchanged — ledger work is ADR-0010's surface. ADR-0012 mitigates a previously-unnamed risk: **R-policy-flag-day** — operators upgrading the code without simultaneously running the migration would have their dispatcher break on policy-version mismatch. The forward-compat range-acceptance contract closes this risk by design.

## Decision

### D18. First real policy migration — `policy/0001_add_engine_compat_field`

`orchestrator/migrations/policy/migration_0001.py` is the first concrete policy migration. For every `*.yml` file under `ctx.policy_dir`:

1. Surgically insert an `engine_compat:` block immediately after the `version:` line.
2. Bump `version: 1 → version: 2`.
3. Atomically rewrite the file (tmp-then-rename + fsync).

The block written:

```yaml
engine_compat:
  min_engine_version: '0.1.0'
```

`min_engine_version` records the policy engine's own version at migration apply time — `orchestrator.policy.engine.POLICY_ENGINE_VERSION`. The constant lives in `engine.py` (not in the migration) because it versions the policy ENGINE, not the migration framework. Pillar C / D / E / F may bump it as new rule classes land; the migration framework's own `RUNNER_VERSION` evolves independently. The two share `"0.1.0"` at Week 4 because the project is at v0.1.0 overall, but they're expected to diverge over time. A future engine release that drops legacy schema support can refuse to load files whose `min_engine_version` is too old without consulting the rules themselves.

Contract:

* **Idempotent at the per-file level.** A file already at `version: 2` AND with `engine_compat:` present is the migration's target state — skip silently (`affected_count = 0` contribution). A re-run of `upgrade(ctx)` after success finds zero files to migrate.
* **Reversible.** `downgrade(ctx)` removes the `engine_compat:` block + reverts the version 2 → 1, restoring byte-identical content on the round trip (verified by the surgical-edit test suite).
* **Per-file atomic.** Each rewrite goes through `_policy_io.write_policy_file_atomic` — tmp-then-rename with `fsync`. A crash mid-batch leaves every file in either the pre- or post-migration shape, never half-written.
* **Refuse-loud on inconsistent state.** Per the asymmetric-failure-cost principle (PILLAR-PLAN §0):
  - `version: 2` WITHOUT `engine_compat:` → half-migrated state. Refuse with `PolicyFileError`.
  - `version: 1` WITH `engine_compat:` → half-migrated state. Refuse with `PolicyFileError`.
  - `version:` is any value other than 1 or 2 → unknown schema. Refuse.
  - YAML is unparseable / top-level isn't a mapping / file is empty → corrupt input. Refuse.
* **Refuse-loud on missing policy dir.** `ctx.policy_dir` not existing raises `FileNotFoundError`. The state file's pointer does NOT advance; re-running after `mkdir -p` resumes cleanly.
* **Empty policy dir is NOT a refusal.** A fresh OSS install with no policy customization is a legitimate zero-file state — the migration succeeds with `affected_count = 0` + the runner marks applied.

Rejected D18 alternatives:

- **`policy/0001_baseline_version_field`** — add `version: 1` to any policy file missing the field. **Rejected** because boundary-of-empty: the factory-shipped `cooldowns.example.yml` already declares `version: 1`, and any operator-installed file that's missing `version:` would have already failed `load_rules_from_yaml` (which raises on missing version). Real-world `affected_count = 0`; the migration would exercise the framework on nothing.

- **`policy/0001_canonicalize_block_when_register`** — normalize any operator-installed file using a deprecated `register_filter:` shape to the canonical `block_when: {register: X}`. **Rejected** because Pillar A's ADRs introduced `block_when:` cleanly; no deprecated form exists in any operator's policy YAML. Boundary-of-empty.

- **Defer the first real policy migration; ship just the dispatcher.** The Pillar A retrospective accepts "deferred indefinitely" as a valid outcome (per ADR-0007 §Alternative 4 `simulation.py` precedent). **Rejected** because Week 4's handoff explicitly recommended a real migration, AND `add_engine_compat_field` is a genuinely-useful schema-evolution-infrastructure transformation: every operator's policy file gets the field, future Pillar G observability work consumes it ("which engine versions know this rule shape?"), and the schema-bump precedent is exercised end-to-end with operator-visible bytes.

Counter-argument: the `engine_compat:` field has no current consumer — the engine doesn't read it (per D21). **Accept** — the field is schema-evolution infrastructure rather than dead code. ADR-0012 documents the future-consumer intent (Pillar G dashboards; Pillar I OSS hardening's engine-version-compat refuse logic).

### D19. Per-category dispatcher shape — helper module, mirroring ADR-0011 D8 + ADR-0010 D14

`orchestrator/migrations/policy/_policy_io.py` exposes module-level functions + a `PolicyFileError` exception. Migrations import what they need:

```python
from ._policy_io import (
    PolicyFileError,
    add_top_level_block_text,
    add_top_level_field_text,
    bump_version_text,
    iter_policy_files,
    read_policy_file,
    remove_top_level_block_text,
    remove_top_level_field_text,
    write_policy_file_atomic,
)
```

Surface (8 module-level functions + 1 exception class):

* `iter_policy_files(policy_dir) -> Iterator[Path]` — walks `<policy_dir>/*.yml` non-recursively, sorted, skipping hidden + Obsidian Sync conflict files. Yields nothing when the dir doesn't exist (legitimate fresh-install state).
* `read_policy_file(path) -> tuple[dict, str]` — parse YAML + return `(parsed_dict, raw_text)`. The raw text is what surgical edits operate on (preserving comments + ordering); the parsed dict is for shape validation. CRLF normalized to LF on read.
* `write_policy_file_atomic(path, text) -> None` — tmp-then-rename atomic write with fsync. Same durability bar as `_vault_io.write_person_frontmatter_atomic` + `state.save_state_atomic`.
* `add_top_level_field_text(text, key, value) -> str` — surgical insert of a scalar top-level field, immediately after the `version:` line. Refuses if `key` already present (idempotence is the caller's responsibility).
* `add_top_level_block_text(text, key, block) -> str` — surgical insert of a multi-line block (single-level map of scalars). Same insertion point + idempotence contract.
* `remove_top_level_field_text(text, key) -> str` — surgical delete of a scalar field. Idempotent (absent key = unchanged text).
* `remove_top_level_block_text(text, key) -> str` — surgical delete of a multi-line block. Stops at the first non-indented line (preserves blank lines + subsequent top-level constructs).
* `bump_version_text(text, from_version, to_version) -> str` — rewrite the top-level `version:` line. Preserves prefix whitespace, quote style, and trailing comment. Refuses if current value isn't `from_version` (defense-in-depth).

Why surgical edits (not YAML round-trip via `yaml.safe_dump`):

- **Clobbers operator comments.** `cooldowns.example.yml` has 200+ comment lines; a round-trip would erase all of them.
- **Normalizes quote styles.** Hand-quoted strings (`reason: "Already cold-pitched ..."`) get re-quoted inconsistently.
- **Reorders fields.** Operators have mental ordering (`version:` first, `rules:` last); round-trip is unpredictable.

The surgical-edit pattern matches what ADR-0011 D10 specifies for vault frontmatter + what `orchestrator/reconcile._write_pipeline_stage` uses for the only other in-place YAML mutation in the orchestrator.

Why the deterministic "immediately after `version:`" insertion point:

- `rules:` is a top-level block-map that spans most of the file body. Appending after `rules:` would put the new field inside the block, changing its meaning.
- The deterministic point makes the operator-facing diff minimal: one block-of-lines inserted in a predictable location; every other line byte-identical.

Why two-helper shape (`add_top_level_field_text` for scalars; `add_top_level_block_text` for blocks):

- Scalar inserts are far more common (every future Pillar D / E migration that adds a top-level scalar field uses the scalar helper).
- Block inserts are rarer + have additional shape constraints (single-level maps only — deeper nesting needs a more capable helper).
- Splitting keeps each function's contract simple + testable in isolation.

### D20. ADR-0012 scope — narrow, per the per-ADR convention

This ADR covers:

* The surgical-edit pattern for policy YAML (D19: no `yaml.safe_dump` round-trip; preserve operator comments + field order).
* Per-file atomicity (tmp-then-rename + fsync; same as ADR-0011 D10 + ADR-0010 D14).
* The helper-module dispatcher boundary (D19).
* First migration shape (D18: `add_engine_compat_field`).
* Concurrent-edit handling (D21).
* Engine version-range coordination (D22).
* Downstream pillar impact (cross-cutting per the ADR-0009 convention).

Out of scope (explicitly deferred):

- **Synthetic-replay exit-criterion vehicle (Week 5–6 / ADR-0013).** Per the Pillar A retrospective on per-ADR scoping: keep each ADR narrow; replay-vehicle work is its own ADR. Week 4's helper module + first migration are designed to compose cleanly with the Week 5–6 vehicle (every helper accepts an arbitrary `policy_dir`).
- **CLI (`python -m orchestrator.migrations apply`).** Same shape as ADR-0011 / ADR-0010's deferral; lands once per-category dispatchers stabilize. Operators invoke `MigrationRunner().apply(MigrationCategory.POLICY)` via Python REPL / script in Week 4.
- **Refuse-on-pending in doctor for policy migrations.** ADR-0011 D12 punted this to Pillar I; ADR-0012 inherits the same posture. Week 4's `doctor.py:check_migrations` surfaces all three pending migrations (vault, ledger, policy) via the same WARN-on-pending shape — no category-specific tightening here.
- **`add_top_level_block_text` deeper-nesting support.** Single-level map only in Week 4. Pillar D / E / F migrations that need deeper structure either flatten the children or extend the helper. YAGNI until a concrete need surfaces.
- **`add_rule_block_text`** (appending a new rule entry to the `rules:` list). Pillar D / E / F may need this; the helper module's shape is ready to host it without restructuring. Not pre-baked in Week 4.
- **Suppression-file migrations.** Suppression YAML files (`~/.outreach-factory/suppressions/*.yml`) have their own `SUPPORTED_SUPPRESSION_SCHEMA_VERSION` constant in `orchestrator.policy.suppression`. A future migration that bumps the suppression schema would either reuse this helper module (the surgical-edit primitives generalize cleanly) or get its own per-category dispatcher. Out of scope for Week 4 — the Week 4 migration's `ctx.policy_dir` is `~/.outreach-factory/policies/` only.

### D21. Concurrent-edit handling — document + warn, no enforcement

A policy migration that rewrites N policy files while an operator is editing one in `$EDITOR` (or while a daemon SIGHUP-reloads policies; Pillar H) creates the same race the vault migration's ADR-0011 D9 names: the migration writes to disk; the operator's editor was holding the old text in memory; saving the editor's buffer reverts the migration.

The asymmetric-failure-cost calculus is the same as ADR-0011 D9:

- Policy migrations run a handful of times per year; coordinating with an active editor session is operator-discipline, not framework-enforcement.
- A per-tenant policy-write lock would be heavy + Pillar I's process-isolation work is the right home.

**Rejected:**

- **Detect $EDITOR sessions via lockfiles.** Brittle (operators may use editors that don't take exclusive locks; the migration would still race against a daemon SIGHUP).
- **Refuse migration if a daemon process is running.** Platform-specific + the Pillar H daemon doesn't exist yet; pre-coordinating with a future system creates a coupling the framework should not own.

**Accepted (Week 4 posture):**

- Document the risk in ADR-0012 + this section.
- Operator-discipline: quiesce any concurrent writer (close editor; stop daemon SIGHUP loop) before applying.
- Pillar I revisits with proper isolation primitives.

Why no per-file warning is logged (unlike ADR-0011 D9's Obsidian Sync warning):

- The vault has a known concurrent-writer (Obsidian Sync) that's nearly universal among operators.
- Policy files have NO known concurrent-writer at OSS bring-up time (`~/.outreach-factory/policies/` is rarely synced; the daemon is Pillar H future work).
- A warning printed during every policy-migration apply would be noise without signal at this stage. Pillar H wires the warning when the daemon ships.

### D22. Engine version-range coordination — the policy-migration-specific contract

**The problem.** Pre-Week-4, `orchestrator/policy/engine.py` declared:

```python
SUPPORTED_POLICY_SCHEMA_VERSION = 1
```

and `load_rules_from_yaml` raised `ValueError("unsupported version")` on anything not equal to 1. The Week 4 migration bumps `version: 1 → version: 2`. If the engine code shipped without coordinated update, the sequence would be:

1. Operator pulls Week 4 code. Engine code still wants version 1 (unchanged). Files at version 1. Dispatcher loads fine.
2. Operator delays running the migration (per ADR-0011 D12's warn-on-pending posture, the dispatcher doesn't refuse). Doctor warns about pending policy/0001.
3. Operator runs migration. Files bump to version 2. Engine still wants version 1.
4. **Dispatcher fails on next reload — engine raises "unsupported version 2."**

The flag-day failure mode the migration framework was designed to prevent. The fix is structural: the engine must accept a **range** of versions during the transition window between two adjacent migrations.

**The contract:** every policy migration that bumps `version:` ships coordinated with an `engine.SUPPORTED_POLICY_SCHEMA_VERSIONS` update that ADDS the new version to the accepted set. The set is frozen + sorted + bounded — currently `frozenset({1, 2})`. A future migration that drops legacy support REMOVES the old version from the set (Pillar I OSS hardening is the natural home for that step — by then operators have had multiple cycles to apply the intermediate bumps).

**The implementation (Week 4 changes to `engine.py`):**

```python
SUPPORTED_POLICY_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})
SUPPORTED_POLICY_SCHEMA_VERSION = max(SUPPORTED_POLICY_SCHEMA_VERSIONS)
```

`SUPPORTED_POLICY_SCHEMA_VERSION` (singular) is preserved as the "latest" sentinel for backwards-compat with code that imports the constant. The loader actually checks the set:

```python
if version not in SUPPORTED_POLICY_SCHEMA_VERSIONS:
    raise ValueError(...)
```

**Why this is a Pillar A touch, not Pillar A drift.** Pillar A's stability claim (per PILLAR-PLAN §6) covers rule semantics + rule classes + the policy-engine evaluation contract. Range-acceptance for the `version:` field is a NEW shape — schema-evolution infrastructure that the policy engine grew to support the migration framework's coordination contract. No rule's evaluate path changes; no rule class is added or removed; the new behavior strictly extends what files the loader accepts.

**Rejected alternatives:**

- **Bump `SUPPORTED_POLICY_SCHEMA_VERSION = 2` atomically without range acceptance.** Operators in the warn-on-pending window have v1 files; the engine refuses to load them; dispatcher breaks. The flag-day failure mode. Rejected.

- **Keep `version: 1` on the migration; don't bump.** The migration would only insert `engine_compat:` without bumping the version. **Rejected** because the schema-bump precedent is the whole point of exercising the framework on a third surface — the helper module's `bump_version_text` would be tested in isolation but never used by a real migration. Future Pillar D / E migrations would have no end-to-end reference to follow.

- **Make the engine bump itself a separate migration (`policy/0001_baseline_compat`) so Week 4 ships only the engine change + no file rewrite.** **Rejected** because the framework's purpose is to ship coordinated changes via migrations. Splitting the engine bump from the file rewrite into two separate migrations would double the operator-facing apply count without changing the failure-mode surface.

- **Read the file with both v1 + v2 shape-acceptance branches; reject any other version.** **Rejected** because that's exactly what `SUPPORTED_POLICY_SCHEMA_VERSIONS = frozenset({1, 2})` expresses; the helper is the cleaner way to write it.

**Future contract:** any migration that bumps to version N+1 ships with `SUPPORTED_POLICY_SCHEMA_VERSIONS` extended to include N+1. The set grows monotonically until Pillar I's compaction step drops legacy versions. The compaction step is itself a migration that operators apply on their schedule — same framework-level contract.

### Downstream pillar impact

Per the ADR-0009 convention (every Pillar B ADR explicitly names cross-pillar impact):

* **Pillar C (multi-channel coherence).** LinkedIn / Twitter cooldown rules land as additions to `cooldowns.yml`. A Pillar C author writes `policy/000N_add_linkedin_cooldown_rules.py` following the `policy/0001` pattern: reads each file, appends new rule entries (via a future `add_rule_block_text` helper), bumps the version, atomic write. The forward-compat range-acceptance contract (D22) carries the operator across the Pillar C transition.

* **Pillar D (reply + conversation handling).** Reply-classifier configuration lives in a new policy file (or as a new rule type in `cooldowns.yml`). Either path uses this ADR's helpers wholesale. The `read_policy_file` parse + surgical-edit pattern covers any single-file or multi-file shape Pillar D produces.

* **Pillar E (discovery quality + lineage).** Pillar E's `discovery_lineage:` rules need policy YAML evolution — likely a new rule class. The helper module's `add_rule_block_text` extension (deferred from D20) is the Pillar E author's natural deliverable; the pattern composes with the existing `add_top_level_field_text` / `add_top_level_block_text` surface.

* **Pillar F (voice corpus + draft quality).** Voice-fidelity scoring may add a budget-rule analog (`voice.requires-minimum-score`). Same shape — policy migration adds the rule class + bumps version.

* **Pillar G (observability).** OTel + Prometheus will emit per-migration metrics; Pillar G is the natural home for "did this migration apply?" gauges across all three categories (ledger / vault / policy), separate from the ledger-specific `migration_event` audit-trail events that ADR-0010 D17 already emits. The Pillar G dashboard "which policy version is each operator on?" reads the file's `version:` directly (a Prometheus gauge per category). The `engine_compat.min_engine_version` field this Week's migration introduces becomes a queryable observable — Pillar G dashboards can chart "which engine versions know each operator's rules."

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant policy directories; each tenant gets independent migration state. The doctor's refuse-on-pending hardening applies uniformly to vault/ledger/policy. The drop-legacy-version step (D22's monotonically-growing range) is a Pillar I deliverable — by then operators have had multiple cycles to apply the intermediate bumps + the set can be trimmed safely.

* **Pillar J (security + compliance).** GDPR-forget on a policy file (removing a rule that was emitting PII to logs) is structurally reversible — `is_reversible=True` per the policy-file shape. The two-step compaction-tool pattern (ADR-0010 §Downstream pillar impact for Pillar J) doesn't apply here because policy files don't accumulate append-only data the way the ledger does.

## Alternatives considered

### Alternative 1: Dispatcher class per category (`PolicyDispatcher`)

A class wrapping all per-category IO + offering a per-file transaction context manager. **Rejected** — same shape as ADR-0011 §Alternative 1 + ADR-0010 §Alternative 1. Helper-module shape is precedented across Pillar A + Pillar B Weeks 2–3; a class would be a structural departure.

### Alternative 2: Full YAML round-trip via `yaml.safe_dump` for policy file rewrites

Parse the entire file, mutate the dict, serialize back. **Rejected** because:

- Clobbers operator comments. `cooldowns.example.yml` has 200+ comment lines including ~7 commented-out rule templates the operator can uncomment + tune.
- Normalizes quote styles. Hand-quoted strings get re-quoted inconsistently.
- Reorders fields. Insertion order vs alphabetical depends on Python version.

Surgical-edit (`add_top_level_field_text` / `add_top_level_block_text` / `bump_version_text`) preserves every concern that round-trip would damage.

### Alternative 3: Per-file lock during policy migration

Each policy file acquires its own `<file>.lock` before rewrite; releases after. **Rejected** because:

- The migration is single-writer (framework's state-file lock serializes concurrent runners at the batch level). Per-file locks add no real protection.
- Lock-file proliferation pollutes the policy dir.
- Operator-discipline (quiesce concurrent writers before apply) is the canonical safety belt per D21.

### Alternative 4: Skip files with corrupt YAML (silent recovery)

Instead of raising `PolicyFileError` on malformed YAML, log a warning + continue. **Rejected** because the asymmetric-failure-cost principle (PILLAR-PLAN §0): silently skipping a corrupt policy file hides a real problem. The operator's policy YAML is the SoT for active rules; a half-loaded ruleset is silent policy weakening. Refuse-loud + per-file atomicity means the operator can fix the file + re-run apply; the migration resumes idempotently.

### Alternative 5: Ship the dispatcher in Week 4 without the first real migration

Land `_policy_io.py` + ADR-0012; mark `policy/MIGRATIONS = []`; defer the first real migration until a concrete Pillar D / E / F need surfaces. **Rejected** because Week 4's handoff explicitly recommended a real migration AND `add_engine_compat_field` is a genuinely-useful transformation (every operator's policy file gets the field; future Pillar G work consumes it; the schema-bump precedent is exercised). The Pillar A retrospective accepts "deferred indefinitely" as a valid outcome, but Week 4's circumstances don't force it.

### Alternative 6: First real migration is `policy/0001_baseline_version_field`

Add `version: 1` to any policy file missing the field. **Rejected** — boundary-of-empty per D18: every operator's file already declares `version: 1` (the engine refuses load otherwise).

### Alternative 7: First real migration is `policy/0001_canonicalize_block_when_register`

Normalize any operator-installed file using a deprecated `register_filter:` shape to the canonical `block_when: {register: X}`. **Rejected** — boundary-of-empty per D18: Pillar A's ADRs introduced `block_when:` cleanly; no deprecated form exists.

### Alternative 8: Don't bump the engine's `SUPPORTED_POLICY_SCHEMA_VERSION` — make the engine accept any version it can parse

Drop the version check entirely; trust `yaml.safe_load` to parse + the rule classes to validate their own shape. **Rejected** because:

- The version check is the engine's only forward-compat guard. Removing it means a file written by a much-newer migration (using rule classes this build doesn't know) would partial-load + the operator's send loop would silently miss the new rules.
- The asymmetric-failure-cost calculus says explicit refuse > silent partial load. The version check is cheap + the error message is operator-actionable.

### Alternative 9: Engine bumps `SUPPORTED_POLICY_SCHEMA_VERSION = 2` (no range) coordinated with the Week 4 migration

Operators must apply the migration immediately on git-pull. **Rejected** because ADR-0011 D12's warn-on-pending posture is the framework's contract: the dispatcher must continue to work between git-pull and migration-apply. A hard bump would force a flag-day. The forward-compat range-acceptance (D22) is the structural answer.

### Alternative 10: Make `engine_compat:` a child of `version:` (not a top-level block)

```yaml
version:
  current: 2
  min_engine: '0.1.0'
```

Restructure the version field into a map. **Rejected** because:

- Breaking change for every existing consumer of `data["version"]` (the engine, the migration framework, every test). A different ADR's worth of work.
- The `engine_compat:` block is a separate concern (engine-version-compat info) from the schema version itself (which generation of the file's shape). Mixing them couples future evolutions.
- A top-level sibling block is the simpler shape + composes with future `engine_compat: {min_engine_version: X, max_engine_version: Y, deprecated_in: Z}` extensions without breaking `version:` consumers.

### Alternative 11: First migration also reads the engine_compat field in Pillar A

Wire `engine.load_rules_from_yaml` to consult `engine_compat:` + refuse files whose `min_engine_version` is newer than this build. **Rejected** because:

- Pillar A is stable; adding consumption logic for a brand-new field is scope creep — Pillar A's exit gate covers existing rule classes + their semantics, not infrastructure.
- The right place to consume `engine_compat:` is Pillar G's observability dashboards + Pillar I's OSS hardening's engine-version-compat refuse logic. Future work has a defined home; Week 4 ships the structural primitive.
- The field is "schema-evolution infrastructure" rather than dead code — future consumers exist, just not yet.

## Consequences

### Positive

- **The surgical-edit pattern is uniform across vault + policy migrations.** Operators have one mental model: a migration adds / removes specific lines; the rest of the file stays byte-identical. Comments, quote styles, and field ordering survive untouched.
- **Pillar C / D / E / F inherit a working pattern.** A future Pillar C author writes `policy/000N_add_linkedin_rules.py` by following the `policy/0001` shape + using the helper module's primitives. No category-specific design needed.
- **The forward-compat range-acceptance contract (D22) is named.** Every future policy schema bump knows the contract: ship the engine update + the migration in the same commit; the set of accepted versions grows; Pillar I trims legacy versions on a later schedule.
- **Per-file atomicity is a tested contract.** Every policy migration uses `write_policy_file_atomic`; every write is tmp-then-rename + fsync. A crash mid-batch leaves every file in either the pre- or post-migration shape, never half.
- **Reversibility is a tested contract.** `policy/0001` is reversible + has tests; the round-trip on the real factory `cooldowns.example.yml` is byte-identical. Future irreversible policy migrations (purges) declare `is_reversible=False` and the runner refuses rollback uniformly.
- **`engine_compat:` becomes a first-class observable.** Pillar G's "which engine versions know each operator's rules?" dashboard reads directly from this field.

### Negative

- **Manual coordination required for every future schema bump.** A contributor writing a new policy migration must remember to also update `SUPPORTED_POLICY_SCHEMA_VERSIONS`. **Mitigation:** ADR-0012 D22 names the contract; the migration's tests can assert the new version is in the set (per `TestEngineForwardCompat.test_supported_versions_set_contains_both`); a future CI check could enforce automatically.
- **`add_top_level_block_text` is single-level-only.** Nested-map blocks (e.g. `engine_compat: {ranges: {min: ..., max: ...}}`) need a future extension. Documented in the helper's docstring; not pre-baked here.
- **No CLI yet.** `python -m orchestrator.migrations apply` still doesn't exist. Operators invoke `MigrationRunner().apply()` from a Python REPL or script. **Mitigation:** deferred to Pillar I's OSS bring-up; the helper-module pattern + `__init__.py` registry list are CLI-ready.
- **The `min_engine_version` field has no consumer in Week 4.** It's schema-evolution infrastructure for future Pillar G + Pillar I work. **Mitigation:** documented as such in ADR-0012 D18 + the migration's docstring + the field's value (`RUNNER_VERSION` constant) is a tested invariant.

### Neutral / observability

- The migration logs at INFO with `affected_count` + already-at-target counts. The doctor's WARN-on-pending message surfaces "policy/0001_add_engine_compat_field" by id. Pillar G's OTel wiring picks up both surfaces unchanged.
- The set of supported versions in `engine.py` is a module-level constant; tests assert its membership (per `TestEngineForwardCompat.test_supported_versions_set_contains_both`). A future contributor changing the set without updating the migration framework's tests would see the failure immediately.
- `PolicyFileError` is a public exception. CLI / TUI / future automation tools catch by class.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAML files are the SoT for "what rules are active" (per `docs/SOURCES-OF-TRUTH.md`). This migration's `engine_compat:` field is metadata about the file's compatibility; it does NOT change which rules are active + does not introduce a new SoT. The `version:` field is still the file's self-declared schema generation. No SoT changes.
- **I2 (two-phase commit):** Not applicable — policy migrations are internal state evolution, not external side effects. Per-file atomicity (tmp-then-rename + fsync) is the migration-framework analog.
- **I3 (schema versioning):** This migration operationalizes I3 for policy files — every policy file now declares its engine-compat range AND its schema generation (`version:`). Future schema evolutions bump the version each time. The engine's `SUPPORTED_POLICY_SCHEMA_VERSIONS` set provides the forward-compat range-acceptance contract; D22 names the discipline.
- **I5 (observable by default):** Every apply + downgrade logs at INFO with `affected_count` + already-at-target counts. Doctor's WARN result surfaces pending policy migrations alongside vault + ledger. The `migration_event` audit-trail emission contract (ADR-0010 D17) is **ledger-specific** — policy migrations write to YAML files, not to the ledger, and do NOT emit `migration_event` events. Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories (see §Downstream pillar impact). This matches ADR-0011 I5's posture for vault migrations.
- **I6 (tests prove invariants):** New tests across `tests/test_migrations_policy_io.py` (65) + `tests/test_migrations_policy_0001.py` (38). Per-file atomicity is pinned by a simulated-crash test. Idempotence + reversibility have explicit tests. The forward-compat range-acceptance contract is pinned by `TestEngineForwardCompat` + the engine's existing `test_wrong_version_raises` (version 999 still rejected).
- **I7 (cost is a first-class concern):** Policy migrations do not emit `cost_incurred` events — they're local IO with no external API calls. The `migration_event` audit-trail does NOT carry timing fields in Week 4 (consistent with ADR-0010); Pillar G adds them via a future ADR amendment if needed.
- **I8 (decisions documented):** This ADR. ADR-0009 §References gains an entry in the "Shipped since this ADR landed" subsection for ADR-0012. `docs/adr/README.md` gets a new row.

Does not weaken any invariant. The engine's version-acceptance posture is strictly extended (range instead of singleton) — backwards-compatible with the existing `test_wrong_version_raises` contract (version 999 still rejected since 999 ∉ {1, 2}).

## Migration / rollout

The first real policy migration is `policy/0001_add_engine_compat_field`. Rollout shape:

1. Operator runs `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             3 pending: ledger/0001_close_orphan_send_intents,
                            vault/0001_add_schema_version_to_person_notes,
                            policy/0001_add_engine_compat_field
   ```

1.5. **Quiesce concurrent writers** if any are active (per D21):
   * Close any open editor sessions on policy YAML files.
   * Stop any daemon process that reloads policy on SIGHUP (Pillar H future work — no concurrent writer exists at OSS bring-up time).

2. Operator runs the dry-run preview:
   ```python
   from pathlib import Path
   from orchestrator.migrations import MigrationRunner, MigrationCategory
   runner = MigrationRunner()
   preview = runner.dry_run(MigrationCategory.POLICY)
   # Prints "would migrate N policy file(s) ..."
   ```

3. Operator applies for real:
   ```python
   runner.apply(MigrationCategory.POLICY)
   # Rewrites each policy file: inserts engine_compat block + bumps version 1->2.
   ```

4. Re-runs `python scripts/doctor.py` → policy/0001 is no longer pending.

5. Operator inspects the migrated files:
   ```bash
   head -5 ~/.outreach-factory/policies/cooldowns.yml
   # version: 2
   # engine_compat:
   #   min_engine_version: '0.1.0'
   # ...
   ```

The dispatcher continues to load each file via `engine.load_rules_from_yaml` — the engine now accepts both v1 and v2 files (per D22) so an operator who delays the apply does NOT see their send loop break. The schema-evolution infrastructure is in place for future Pillar G / Pillar I consumption.

A CLI (`python -m orchestrator.migrations apply`) is deferred until per-category dispatchers stabilize (Week 5–6 ships ADR-0013 replay vehicle; Pillar I OSS bring-up ships the operator-friendly CLI).

The migration is reversible — `runner.rollback(MigrationCategory.POLICY, "0001_add_engine_compat_field", allow_rollback=True)` removes the block + reverts the version. Operators rarely invoke; the defense-in-depth `allow_rollback=True` flag (ADR-0009 D4) makes accidental rollback a deliberate operator action.

## References

- ADR-0001 (policy engine architecture) — the engine surface this ADR's migration coordinates with. `engine.SUPPORTED_POLICY_SCHEMA_VERSIONS` is the new range-acceptance constant; `load_rules_from_yaml` is the loader the contract preserves.
- ADR-0004 (suppression rules + GDPR forget) — the tmp-then-rename atomicity precedent (`forget_append`); the `is_reversible=False` precedent for irreversible migrations.
- ADR-0007 (tier rules + simulation surface) — the "deferred indefinitely" precedent (ADR-0007 §Alternative 4 `simulation.py`) that D18 considers + rejects.
- ADR-0009 (migration framework foundation) — D1–D7 + the per-category-ADR-per-dispatcher convention this ADR fulfills.
- ADR-0010 (ledger migrations) — D14–D17 + the helper-module dispatcher precedent this ADR mirrors for policy. The `migration_event` audit-trail emission (ADR-0010 D17) is **ledger-specific** — policy migrations do not write to the ledger and do not emit `migration_event` events. Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories.
- ADR-0011 (vault migrations) — D8–D13 + the surgical-edit precedent (`add_frontmatter_field_text` / `remove_frontmatter_field_text`) that this ADR generalizes for policy YAML's no-delimiter shape.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies refuse-loud on inconsistent state + refuse-on-missing-policy-dir).
- `docs/PILLAR-PLAN.md` §1 — I1 (single source of truth: policy YAML for active rules), I3 (schema versioning), I5 (observable by default), I6 (tests prove invariants).
- `docs/PILLAR-PLAN.md` §2 Pillar B — scope + exit criterion.
- `docs/SOURCES-OF-TRUTH.md` row "Cooldown / budget / window policy" — verifies the policy SoT invariant this migration preserves.
- `orchestrator/policy/engine.py` — `SUPPORTED_POLICY_SCHEMA_VERSIONS` (the new range-acceptance set + the latest sentinel `SUPPORTED_POLICY_SCHEMA_VERSION = max(...)`). `load_rules_from_yaml` checks membership in the set.
- `orchestrator/migrations/policy/_policy_io.py` — `PolicyFileError`, `iter_policy_files`, `read_policy_file`, `write_policy_file_atomic`, `add_top_level_field_text`, `add_top_level_block_text`, `remove_top_level_field_text`, `remove_top_level_block_text`, `bump_version_text`.
- `orchestrator/migrations/policy/migration_0001.py` — `AddEngineCompatField`, `MIGRATION` module-level instance, `MIGRATION_ID`, `FROM_VERSION`, `TO_VERSION`, `COMPAT_BLOCK_KEY`, `MIN_ENGINE_VERSION_VALUE` constants.
- `orchestrator/migrations/policy/__init__.py` — `MIGRATIONS = [MIGRATION_0001_ADD_ENGINE_COMPAT]`.
- `config-template/cooldowns.example.yml` — the 275-line factory template the migration was designed to handle; the test suite verifies byte-identical round-trip against this file.
- `scripts/doctor.py:check_migrations` — surfaces policy/0001 in the WARN-on-pending list (no code change — the existing implementation walks every category).
- `tests/test_migrations_policy_io.py` — helper module tests (iteration, parsing, atomicity under crash, surgical insert/remove, round-trip preservation, version bumping).
- `tests/test_migrations_policy_0001.py` — migration tests (per-file outcomes, dry-run no-op, refuse-loud on inconsistent state, downgrade round-trip, runner integration, engine forward-compat, real factory-template round-trip).
- Forward-references (planned):
  - **ADR-0013** — synthetic-replay exit-criterion vehicle (Week 5 foundations + Week 6 exit gate). The replay test exercises this ADR's `policy/0001_add_engine_compat_field` against the synthetic policy fixture (a `version: 1` cooldowns.yml with operator comments); the surgical-edit pattern's byte-identical preservation is verified end-to-end in `tests/test_migrations_replay.py::TestFullBatchApply::test_policy_rules_byte_identical_after_apply`. **Accepted** 2026-05-21.
  - Doctor refuse-on-pending feature flag (`OUTREACH_FACTORY_STRICT_MIGRATIONS=1`) — Week 6 per ADR-0013 D26. Pillar I (Weeks 43–48) flips the default + removes the flag.
  - The drop-legacy-version migration that trims `SUPPORTED_POLICY_SCHEMA_VERSIONS` — Pillar I OSS hardening, once operators have had multiple cycles to apply intermediate bumps.
