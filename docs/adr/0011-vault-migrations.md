# ADR-0011: Vault migrations — per-file atomicity, helper-module dispatcher, Obsidian Sync handling

- **Status:** Accepted
- **Date:** 2026-05-19
- **Pillar:** B (Migration framework — Week 2 vault dispatcher + first real migration)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0009 (Week 1) shipped the migration-framework foundation: runner, state file, reversibility contract, applies-once invariant. Per ADR-0009 D7, per-category ADRs (0010 ledger, 0011 vault, 0012 policy, 0013 replay) land alongside the per-category dispatchers + first concrete migrations. Pillar B Week 2 ships vault first, leaving 0010 reserved for ledger (Week 3) — vault migrations are structurally lower-risk than ledger migrations (vault is denormalized + reconcile-recoverable; ledger is SoT and irreplaceable).

The vault is the operator's Obsidian markdown CRM: Person notes under `<vault>/10 People/**`, touch notes under `<vault>/40 Conversations/**`, company notes, lead-list notes. The single source of truth for "did we send to this human?" lives in the ledger, but Pillar D / E / F all read **denormalized** frontmatter (`pipeline_stage:`, `status:`, `research_tier:`, eventually `schema_version:`, `discovery_lineage:`) at gate-time, draft-time, or display-time. The frontmatter shape evolves; vault migrations are the framework's vehicle for that evolution.

Three concerns this ADR resolves:

1. **Per-file atomicity is the load-bearing promise.** ADR-0009 D4 names the framework's atomicity contract: state-file pointer moves only on `upgrade` success. That contract is necessary but not sufficient — a vault migration that rewrites 100 notes and crashes on note 67 leaves the **vault** half-rewritten even though the **state file** stays clean. Per-file atomicity (every individual rewrite is tmp-then-rename) is the migration's responsibility; this ADR pins the convention.

2. **The per-category dispatcher boundary has a shape now.** ADR-0009 §Decision item "Layout" promised `orchestrator/migrations/vault/` would gain "per-category dispatcher boundary" without yet defining what that means. Week 2 makes it concrete: a private helper module (`_vault_io.py`) exposes the per-file IO surface; migrations import the helpers and stay narrow. The shape generalizes to ledger (`_ledger_io.py`) + policy (`_policy_io.py`) in future weeks.

3. **Obsidian Sync concurrency is unsolved at the framework level.** Operators with Obsidian Sync (or git, or iCloud) running write to the same files the migration rewrites. A migration that completes while Sync is uploading concurrent edits can produce `.conflicted.md` files. The asymmetric-failure-cost calculus differs from ledger / policy: the vault is reconstructable from the ledger via reconcile, so a Sync-conflict-induced rewrite is recoverable. Pillar I's process-isolation work is the right place to enforce; Week 2 documents the risk + prints a warning.

Risks this ADR mitigates: **R002 (vault frontmatter drift)** by stamping `schema_version:` on every Person note + giving Pillar D / E / F a vehicle for additive frontmatter migrations. ADR-0009's R005 (ledger schema-bump regret) is unchanged — ledger work waits for ADR-0010.

## Decision

### D8. Per-category dispatcher shape — helper module, not class

`orchestrator/migrations/vault/_vault_io.py` exposes module-level functions + a `FrontmatterError` exception. Migrations import what they need:

```python
from ._vault_io import (
    FrontmatterError,
    add_frontmatter_field_text,
    is_person_note,
    iter_person_notes,
    read_person_frontmatter,
    remove_frontmatter_field_text,
    write_person_frontmatter_atomic,
)
```

Rejected the dispatcher-class shape (`VaultDispatcher` wrapping all helpers with a per-file transaction context). The class shape would:

* Drag in all helpers via the wrapping class even when a migration only needs one.
* Be unprecedented — Pillar A's `policy.cooldown`, `policy.suppression`, etc. are modules with module-level functions + dataclass rule classes. The dispatcher-class shape would be a structural departure.
* Add ceremony — migrations are small (`vault/0001` is ~150 LOC); a transaction context for per-file atomicity is overkill when each individual rewrite is independently atomic.

The helper module IS the dispatcher boundary — concrete migrations consume the surface; the surface owns the per-file IO conventions; the runner stays generic-over-category and doesn't know what a vault migration is.

### D9. Obsidian Sync concurrent-edit handling — document + warn, no enforcement

A vault migration that rewrites N notes while Obsidian Sync is uploading concurrent edits creates merge conflicts (`.conflicted.md` files). Pillar B Week 2 ships **a runtime warning printed at upgrade/downgrade start**, regardless of `dry_run`. No process-isolation enforcement.

Rejected:

* **Refuse migration if Obsidian process is running** (detect via `pgrep`). Platform-specific (macOS / Linux / Windows differ); operators on macOS would get a false-positive abort when Obsidian is open but not actively syncing. The asymmetric-failure-cost calculus: missed warning is recoverable (rerun after closing Obsidian); false-positive abort is a worse UX for the common case.

* **Acquire vault-wide lock.** Adds complexity for a rare operation (operators run migrations a handful of times per year as schema evolves). Pillar I's per-tenant process isolation is the right place to hard-coordinate.

The warning is the only operator-facing surface. Pillar I revisits with proper isolation primitives.

### D10. First real vault migration — `vault/0001_add_schema_version_to_person_notes`

`orchestrator/migrations/vault/migration_0001.py` is the first concrete vault migration. It stamps `schema_version: 1` on every Person note's frontmatter.

Contract:

* **Idempotent.** Notes already at `schema_version: 1` are silently skipped (preserve existing `affected_count` semantics). Re-running `apply` after a successful apply is a no-op.

* **Reversible.** `downgrade` removes the field via the inverse surgical-edit helper; `is_reversible=True`. Operators rarely invoke; the framework still requires `allow_rollback=True` explicitly (ADR-0009 D4).

* **Per-file atomic.** Each rewrite goes through `write_person_frontmatter_atomic` — tmp-then-rename with `fsync` (same pattern as `save_state_atomic` / `forget_append`). A crash mid-batch leaves every file in either the pre- or post-migration shape, never half-written.

* **Surgical-edit, not YAML round-trip.** `add_frontmatter_field_text` / `remove_frontmatter_field_text` insert / delete one frontmatter line and leave every other line + comment + ordering intact. Rejected a full `yaml.safe_dump` round-trip — it would clobber operator comments, normalize quote styles, and reorder fields, all of which break the operator's editing flow. The surgical helpers match the convention `orchestrator.reconcile._write_pipeline_stage` already uses for the only other in-place frontmatter mutation in the orchestrator.

* **Refuses on missing vault.** `ctx.vault_dir is None` raises `ValueError` before any file is touched.

* **Refuses on schema_version-mismatch.** A Person note declaring `schema_version: 2` (or any non-1 value) raises `FrontmatterError`. Operator must inspect + decide.

* **Refuses on corrupt YAML.** Per the ADR-0009 §Decision item "Asymmetric failure cost" principle — silently skipping a corrupt note would hide a real problem. The migration propagates `FrontmatterError` with the file path; the runner's atomicity contract means the migration is not marked applied; re-running `apply` after the operator fixes the file retries idempotently.

* **Skips non-Person files silently.** Files with `type != "person"` in their frontmatter, or files with no parseable frontmatter (sub-notes, drafts), are not Person notes and have no schema-version contract to honor.

### D11. Ledger migration in Week 2 — no

The Week 1 handoff named the vault migration as Week 2's deliverable. This ADR confirms: **no ledger migration in Week 2.** ADR-0010 + the first ledger migration land in Week 3.

Rationale:

* Vault migrations are bounded (rewrite N files; N is bounded by vault size). Ledger migrations involve append-only-superseding semantics that require careful design — the ADR-0010 work is structurally harder.
* Week 2 already has scope: vault dispatcher (`_vault_io.py`) + first vault migration + doctor preflight integration + this ADR. Adding ledger doubles the scope.
* The synthetic-replay exit-criterion vehicle (Week 5–6) is where ledger migrations land naturally — `backfill_identity.py` / `backfill_ledger.py` replay through the framework there.

Rejected a no-op ledger migration in Week 2 (`ledger/0001_baseline` emits a `migration_event` and nothing else). Exercising boundary-of-empty is not the same as boundary-of-real; the empty placeholder in Week 1 already proves the boundary exists; the surface a real migration consumes is what's missing, and we add that surface for vault here.

### D12. Doctor preflight surface — warn, not refuse

ADR-0009 D5 deferred doctor integration. Week 2 lands it: `scripts/doctor.py` gains a `check_migrations` function that calls `MigrationRunner().pending()` and surfaces a WARN result (not FAIL) when non-empty.

Rationale:

* Week 2 is the FIRST time operators will see migrations pending. A refuse-on-pending would break every existing operator's send loop on their next launch. The soft warn lets operators discover the new check + apply on their schedule.
* Pillar I (Weeks 43–48) hardens to refuse-on-pending. By then, operators have had multiple cycles to internalize the discipline, and refuse-on-pending becomes the right posture (a stale state file is a real signal of "the operator forgot to apply").
* Doctor's exit code stays `0` for WARN results — the asymmetric-failure-cost calculus says Week-2 false-positive refuse (operator mid-applying, doctor blocks) is worse than Week-2 false-negative warn (operator sees notice, applies on schedule).

Rejected refusing in Week 2 + a `--allow-pending` flag for emergency bypass. The flag would accumulate caller sites that need to forward it; the soft-warn approach has zero such friction and the same eventual destination (Pillar I refuses by default).

### D13. ADR-0011 lands before ADR-0010 — reserve 0010 for ledger

ADR-0009 §References names the planned ADR order: 0010 ledger → 0011 vault → 0012 policy → 0013 replay. Week 2 ships a vault migration first, so ADR-0011 lands first. ADR-0010 stays reserved for the Week-3 ledger work.

Rejected renumbering (making vault ADR-0010 since it ships first). Renumbering would break ADR-0009's forward references (which already point at 0010=ledger, 0011=vault). Reserving 0010 advertises "ledger migrations get an ADR; one is owed; here's the placeholder." A reader of `docs/adr/README.md` sees the gap and knows what's coming.

### Downstream pillar impact

Per the ADR-0009 convention (every Pillar B ADR explicitly names cross-pillar impact):

* **Pillar D (reply + conversation handling).** The reply classifier reads touch-note frontmatter; once Pillar D adds `reply_classified:` / `conversation_state:` fields, those land via vault migrations consuming this ADR's surface. The Pillar D author writes `vault/000N_add_reply_state_fields.py` following the `vault/0001` pattern + reuses `_vault_io.py` helpers wholesale.

* **Pillar E (discovery quality + lineage).** Pillar E's `discovery_lineage:` block lands as a vault migration. The block is a nested map (`source_skill:`, `source_list:`, `scraped_at:`, `raw_input_hash:`), which exceeds the scalar-only contract of `add_frontmatter_field_text`. Pillar E author either (a) extends `_vault_io.py` with a `add_frontmatter_block_text` helper, or (b) accepts a YAML-round-trip cost for that one migration. ADR-0011 does not pre-bake the block helper — YAGNI until Pillar E surfaces the need.

* **Pillar F (voice corpus + draft quality).** Voice-fidelity scoring needs per-draft frontmatter fields. Same shape — vault migrations on touch notes (not Person notes), so the iterator default `people_subdir="10 People"` does NOT apply. Future migrations operating on `40 Conversations/` pass a different `subdir` argument; `iter_person_notes` is named for clarity but its shape generalizes (a future `iter_touch_notes` would be a thin wrapper or a rename).

* **Pillar I (multi-tenant + OSS hardening).** The Obsidian Sync warning becomes a hard refuse-on-pending check in Pillar I. The vault-wide lock primitive (rejected here in D9) lands in Pillar I if multi-tenant per-vault isolation needs it.

* **Pillar J (security + compliance).** GDPR-forget on a vault migration (e.g. `vault/000N_purge_deprecated_pii_field`) is structurally irreversible — `is_reversible=False`. ADR-0011's contract holds: per-file atomicity, the framework's state-file lock, but `downgrade` raises `NotImplementedError` (translated by the runner to `MigrationNotReversibleError`).

## Alternatives considered

### Alternative 1: Dispatcher class per category (`VaultDispatcher`)

A class wrapping all per-category IO + offering a per-file transaction context manager. Migrations instantiate and use. **Rejected** because:

* Migrations are small (~150 LOC each); a class wraps them in ceremony.
* The helper-module shape lets a migration import only what it needs; a class drags in everything.
* Pillar A precedent — `policy.cooldown`, `policy.suppression` are modules with module-level functions. A class would be unprecedented.

### Alternative 2: Full YAML round-trip via `yaml.safe_dump` for frontmatter rewrites

Parse the entire frontmatter, mutate the dict, serialize back. **Rejected** because:

* Clobbers operator comments. Many Person notes have inline `# guess-unverified` annotations next to email addresses; YAML round-trip drops them.
* Normalizes quote styles. Yang's vault hand-quotes some strings; `yaml.safe_dump` would unquote or re-quote inconsistently.
* Reorders fields. Operators have a mental order (`name:` first, `email:` second, `linkedin:` third); the round-trip is alphabetical or insertion-order depending on Python version.

Surgical-edit (`add_frontmatter_field_text` / `remove_frontmatter_field_text`) preserves every concern that round-trip would damage.

### Alternative 3: Per-file lock during vault migration

Each Person note acquires its own `<note>.lock` file before rewrite; releases after. **Rejected** because:

* The migration is single-writer (the framework's state-file lock serializes concurrent runners at the batch level). Per-file locks add no real protection.
* Lock-file proliferation pollutes the vault — operators see `Foo.md.lock` next to `Foo.md` and reasonably wonder.
* Obsidian Sync would attempt to sync the lock files, creating its own conflicts.

The framework's state-file lock + the migration's per-file tmp-then-rename atomicity are sufficient. Per-file locks would solve a problem we don't have.

### Alternative 4: Skip notes with corrupt YAML (silent recovery)

Instead of raising `FrontmatterError` on malformed YAML, log a warning + continue. **Rejected** because:

* The asymmetric-failure-cost principle (PILLAR-PLAN §0): silently skipping a corrupt Person note hides a real problem. The operator might never look at the log and a Person who was supposed to be reached out to silently isn't.
* `vault/0001` is idempotent — the operator can fix the corrupt note + re-run `apply` and the migration resumes from where it stopped (the framework's atomicity contract means the migration isn't marked applied during the failure, so re-apply re-walks the directory).
* The loud refusal is uniform with every other refusal in the framework (D4-style "refuse, log, ask the human" per §0).

### Alternative 5: Ship a no-op ledger migration in Week 2 (boundary-of-empty proof)

`ledger/0001_baseline` emits a `migration_event` and nothing else, exercising the per-category dispatcher boundary for both vault AND ledger. **Rejected** because:

* Exercising boundary-of-empty is not the same as boundary-of-real. The empty placeholder in Week 1 already proves the dispatcher boundary exists.
* The surface a real migration consumes is what's missing; we add that surface for vault here, then for ledger in Week 3 alongside ADR-0010 and the first real ledger migration.

### Alternative 6: Refuse-on-pending in doctor for Week 2

`scripts/doctor.py` returns exit code 1 + FAIL status when migrations are pending. **Rejected** because:

* Week 2 is the FIRST time operators see migrations pending. Refuse-on-pending breaks every existing operator's send loop on their next launch.
* Pillar I's broader process-isolation work is the right surface — by then, operators have had multiple cycles to internalize.

The soft-warn matches the asymmetric-failure-cost calculus for the early-rollout phase.

### Alternative 7: `iter_person_notes` reads `vault.people_dir` from config

Instead of hardcoding `"10 People"` as the default subdir, load the operator's config inside the helper. **Rejected** because:

* Couples the iterator to operator-config shape, which the runner explicitly does NOT do (the runner takes `vault_dir` as a path; config-resolution happens at construction time).
* Pillar I's multi-tenant work needs per-tenant config; reading config inside helpers wouldn't compose.
* The default matches the `config-template/config.example.yml` shipped value. Operators who renamed the subdir pass `people_subdir=` explicitly to the iterator.

## Consequences

### Positive

- **Per-file atomicity contract is uniform.** Every vault migration uses `write_person_frontmatter_atomic`; every write is tmp-then-rename + fsync. Operators have one mental model — "a migration crash leaves every file in pre- or post- shape, never half."
- **Pillar D / E / F have a working pattern.** A future Pillar E author writes `vault/000N_add_discovery_lineage.py` by copying `migration_0001.py` and changing the field name; the helper module covers every IO concern.
- **Doctor surfaces pending migrations.** Operators discover schema bumps before they bite. Pillar I's refuse-on-pending hardening is now incremental, not introductory.
- **Surgical-edit preserves operator workflow.** Person notes with inline comments + custom field ordering survive the migration unchanged. The migration adds one line; the rest is byte-identical.
- **Reversibility is a tested contract.** `vault/0001` is reversible + has tests; future irreversible vault migrations (purges) declare `is_reversible=False` and the runner refuses rollback uniformly.

### Negative

- **Obsidian Sync conflicts are still possible.** The warning is operator-facing but easy to miss in CI / unattended runs. Pillar I closes this gap; Week 2 lives with the documented risk.
- **`add_frontmatter_field_text` is scalar-only.** Nested-map fields (Pillar E's `discovery_lineage:`) need a future extension. Documented in the helper's docstring; not pre-baked here.
- **The `people_subdir` default is hardcoded.** Operators with renamed subdirs (`People/` instead of `10 People/`) pass `people_subdir=` explicitly. The migration's caller would need to be aware; currently the migration uses the default.
- **No CLI yet.** `python -m orchestrator.migrations apply` doesn't exist. Operators invoke `MigrationRunner().apply()` from a Python REPL or a script. The CLI is deferred to a future week once the per-category dispatchers stabilize.

### Neutral / observability

- The migration logs at INFO with affected_count + skipped breakdowns. Doctor's WARN message surfaces the pending list. Pillar G's OTel wiring picks up both surfaces unchanged.
- `FrontmatterError` is a public exception. CLI / TUI / future automation tools catch by class.

## Compliance with invariants

- **I1 (single source of truth):** Vault frontmatter is a denormalized view of the ledger; reconcile heals from the ledger. This migration's `schema_version` field is a marker for "which generation of frontmatter shape does this note hold." The marker is metadata about the view, not a new SoT. No SoT changes.
- **I2 (two-phase commit):** Not applicable — vault migrations are internal state evolution, not external side effects. The per-file atomicity contract is the migration-framework analog (tmp-then-rename + fsync at the file level; framework's atomicity contract at the batch level).
- **I3 (schema versioning):** This migration operationalizes I3 for Person notes — every Person note now declares `schema_version: 1`. Future Person-note schema evolutions (Pillar D / E / F) bump the field each time they migrate. The state file's own `schema_version: 1` (ADR-0009) is unchanged.
- **I5 (observable by default):** Every apply + downgrade logs at INFO with affected_count + skipped counts. The Obsidian Sync warning logs at WARNING regardless of dry_run. Doctor's WARN result surfaces pending migrations.
- **I6 (tests prove invariants):** New tests across `tests/test_migrations_vault_io.py` + `tests/test_migrations_vault_0001.py` + `tests/test_doctor_preflight_migrations.py`. Per-file atomicity is pinned by a simulated-crash test (write-tmp-then-fail-rename, verify target untouched). Idempotence + reversibility have explicit tests. Doctor warn-but-pass exit code is tested.
- **I7 (cost is a first-class concern):** Vault migrations are local IO; no `cost_incurred` events emitted. When Pillar G observability needs per-migration timing, a future ADR adds the event type.
- **I8 (decisions documented):** This ADR. ADR-0009 amended to point forward at ADR-0011. `docs/adr/README.md` gets a new row.

Does not weaken any invariant.

## Migration / rollout

The first real vault migration is `vault/0001_add_schema_version_to_person_notes`. Rollout shape:

1. Operator runs `python scripts/doctor.py` → sees `migrations: WARN — 1 pending: vault/0001_add_schema_version_to_person_notes`.
2. Operator quits Obsidian (per the D9 warning).
3. Operator runs (from a Python shell or script):

   ```python
   from pathlib import Path
   from orchestrator.migrations import MigrationRunner
   runner = MigrationRunner(vault_dir=Path("~/your-vault").expanduser())
   preview = runner.dry_run()  # prints affected_count without writing
   runner.apply()               # applies for real
   ```

4. Re-runs `python scripts/doctor.py` → sees `migrations: OK — no pending migrations`.
5. Re-opens Obsidian.

A CLI (`python -m orchestrator.migrations apply`) is deferred until the per-category dispatcher pattern is fully established (Week 3 ledger + Week 4 policy). Pillar I will likely ship the operator-friendly CLI as part of the OSS bring-up.

The migration is forward-only in practice — `downgrade` exists for ADR-compliance + defensive testing, but operators who roll back Pillar D / E / F schema bumps run those migrations' downgrades, not 0001's.

## References

- ADR-0001 (policy engine architecture) — the engine surface this framework parallels (rules → migrations).
- ADR-0004 (suppression rules + GDPR forget) — the tmp-then-rename atomicity precedent (`forget_append`); the `is_reversible=False` precedent for irreversible migrations.
- ADR-0009 (migration framework foundation) — D1–D7 + the per-category-ADR-per-dispatcher convention this ADR fulfills.
- `docs/PILLAR-PLAN.md` §1 I3 — schema versioning invariant; this migration operationalizes for Person notes.
- `docs/PILLAR-PLAN.md` §2 Pillar B — scope + exit criterion.
- `docs/SOURCES-OF-TRUTH.md` — Person identity row (vault frontmatter is SoT for identity_keys; everything else denormalized).
- `orchestrator/migrations/vault/_vault_io.py` — `FrontmatterError`, `read_person_frontmatter`, `write_person_frontmatter_atomic`, `add_frontmatter_field_text`, `remove_frontmatter_field_text`, `is_person_note`, `iter_person_notes`.
- `orchestrator/migrations/vault/migration_0001.py` — `AddSchemaVersionToPersonNotes`, `MIGRATION` module-level instance.
- `orchestrator/migrations/vault/__init__.py` — `MIGRATIONS = [MIGRATION_0001_ADD_SCHEMA_VERSION]`.
- `orchestrator/reconcile.py:_write_pipeline_stage` — the surgical-edit precedent this ADR generalizes via `add_frontmatter_field_text` / `remove_frontmatter_field_text`.
- `orchestrator/identity.py:_walk_people_dir`, `orchestrator/reconcile.py:_walk_people_dir` — the iteration convention (hidden + conflict-file skipping) this ADR reuses.
- `scripts/doctor.py:check_migrations` — the warn-on-pending preflight surface (D12).
- `tests/test_migrations_vault_io.py` — helper module tests (frontmatter round-trip, atomicity under crash, surgical-edit comment preservation, etc.).
- `tests/test_migrations_vault_0001.py` — migration tests (idempotence, reversibility, refuse-on-corrupt, refuse-on-missing-vault, etc.).
- `tests/test_doctor_preflight_migrations.py` — doctor warn-on-pending test.
- Forward-references:
  - **ADR-0010** — ledger migrations (Week 3). **Accepted** 2026-05-19.
  - **ADR-0012** — policy migrations (Week 4). **Accepted** 2026-05-20.
  - **ADR-0013** — synthetic-replay exit-criterion vehicle (Week 5 foundations + Week 6 exit gate). Wraps `backfill_identity.py` as `vault/0002_backfill_identity_lineage` composing with this ADR's `_vault_io.write_person_frontmatter_atomic` per-file atomicity + surgical-edit precedents. **Accepted** 2026-05-21.
