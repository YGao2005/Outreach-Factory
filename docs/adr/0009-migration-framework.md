# ADR-0009: Migration framework foundation — runner, state file, reversibility contract

- **Status:** Accepted
- **Date:** 2026-05-19
- **Pillar:** B (Migration framework + schema versioning — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001–0008 shipped Pillar A (the declarative policy engine). Pillar A is read-only logic: rules consume `RuleContext` + ledger events, return `Allow` / `Block`, never mutate persistent state. Pillar B has the opposite shape — it **mutates** persistent state: rewriting ledger event semantics, vault frontmatter, policy YAML. The asymmetric-failure-cost principle (PILLAR-PLAN §0) compels a different design discipline: a half-applied migration that leaves the ledger inconsistent with vault frontmatter is the catastrophic failure mode, and the framework must structurally prevent it.

Five concerns this ADR resolves:

1. **PILLAR-PLAN §1 I3 names migrations as load-bearing.** *"Every ledger event carries `v:`. Every Person / touch frontmatter carries `schema_version:`. Every policy file carries `version:`. Migrations are first-class code with tests, reversible where possible."* Ledger events already carry `v: 1` (per `orchestrator/ledger.py:94`); policy YAMLs already carry `version: 1` (per `engine.load_rules_from_yaml`). Person frontmatter does NOT yet carry `schema_version:` — adding it requires a vault migration, which requires a migration framework, which is what Pillar B Week 1 ships.

2. **The "Migration state" registry row in `docs/SOURCES-OF-TRUTH.md` is named but the code that mints it doesn't exist.** Row 25 reads: *"Migration state | `~/.outreach-factory/migrations.state.json` | Doctor preflight report | — | Pillar B. Numbered, applies-once."* This file path has been declared since 2026-05-16 (when the 10-pillar plan was adopted); Pillar B Week 1 fills in the implementation.

3. **Pillar B's exit criterion is a replay test, not a verdict matrix.** PILLAR-PLAN §2 Pillar B: *"the Phase 5.5 backfills replayed cleanly through the migration runner against a fresh synthetic vault; doctor.py checks migration state on every launch."* The vehicle that meets this exit criterion is an integration test (Week 5–6) that constructs a synthetic before-state vault + ledger + policy dir, runs the migrations forward, and asserts on the after-state. The Week 1 foundation must support that vehicle: the runner needs `dry_run()` + `apply()` against caller-provided directories (test fixtures supply synthetic paths; production supplies real ones).

4. **Asymmetric failure cost forces atomicity at the framework level.** A migration that mutates 100 vault notes and crashes on note 67 leaves the vault in an inconsistent state at the per-file level (which is the migration's responsibility to mitigate) AND at the framework level (which is the framework's responsibility). The framework's contract: if `upgrade()` raises, the state file pointer does NOT advance — the migration is NOT marked applied. Re-running `apply()` retries the failing migration from the same starting state. Migrations that succeeded BEFORE the failing one in the same batch ARE marked applied (their effects persist, and there's no value in re-applying them).

5. **Reversibility is per-migration, not per-framework.** PILLAR-PLAN §2 Pillar B says *"Forward + backward (where possible)."* GDPR-forget (per ADR-0004) is structurally irreversible — the whole point is that the data goes away. Some schema bumps are similarly one-way (dropping a deprecated field; the prior value is gone). Other migrations are reversible (renaming a field; the rename is invertible). The Migration Protocol forces every author to declare `is_reversible: bool` explicitly — no default — so the question is answered at write time, not deferred to incident time.

Risks this ADR mitigates by design: **R002 (vault frontmatter drift)** by giving Pillar D / E onwards a migration-shaped tool to bump `schema_version:` per Person note; **R005 (ledger schema bump regret)** by providing the framework that future ledger event-type additions will use; and the structural prerequisite for **Pillar I doctor preflight** (which Week 2+ wires once there's a real pending migration to detect).

## Decision

### Layout — three categories, one runner

```
orchestrator/migrations/
├── __init__.py          # public surface (MigrationRunner, Migration, ...)
├── types.py             # Migration Protocol, MigrationCategory, MigrationContext, MigrationResult
├── state.py             # load/save/lock for migrations.state.json
├── runner.py            # MigrationRunner.{pending, dry_run, apply, rollback}
├── ledger/__init__.py   # MIGRATIONS: list[Migration] = []  (Week 2+ populates)
├── vault/__init__.py    # MIGRATIONS: list[Migration] = []  (Week 2+ populates)
└── policy/__init__.py   # MIGRATIONS: list[Migration] = []  (future weeks)
```

`MigrationRunner` is generic over category. It dispatches through the `Migration` Protocol — it does not know what a ledger migration is vs a vault migration. The category sub-packages own the per-category dispatch (Week 2+).

### D1. Week 1 scope cut

Land the framework primitives **without any real migrations**. Week 1 ships:

* Types (`Migration` Protocol, `MigrationCategory` enum, `MigrationContext` + `MigrationResult` dataclasses).
* Runner (`pending`, `dry_run`, `apply`, `rollback`).
* State file management (`load_state`, `save_state_atomic`, `acquire_state_lock`, `is_applied`, `mark_applied`, `mark_unapplied`).
* Tests against synthetic in-memory `Migration` instances (no real ledger / vault / policy files touched).
* This ADR.

Week 2 lands per-category dispatcher boundary + the first real migration (`vault/0001_add_schema_version_to_person_notes`) + doctor preflight wiring. Splitting Week 1 (framework) from Week 2 (first real use) means the runner is exercise-tested before any production state is at risk.

### D2. Migration ID convention — sequential numeric per category

Each migration has an `id` of the form `<NNNN>_<slug>` where `NNNN` is a zero-padded counter unique within its category:

* `vault/0001_add_schema_version_to_person_notes.py`
* `vault/0002_normalize_email_field.py`
* `ledger/0001_baseline.py`
* `policy/0001_drop_deprecated_rule_class.py`

The runner pins per-category ordering: the registry list MUST equal `sorted(ids)`. An out-of-order registry raises `MigrationOrderError` at load time. Per-category counters keep namespaces clean (ledger / vault / policy evolve at different cadences); merge conflicts on the same NNNN are loud (git refuses to silently combine `vault/0007_a.py` and `vault/0007_b.py`).

### D3. State file shape — JSON, per-category applied list

`~/.outreach-factory/migrations.state.json`:

```json
{
  "schema_version": 1,
  "applied": {
    "ledger": ["0001_baseline"],
    "vault": ["0001_add_schema_version"],
    "policy": []
  },
  "last_applied_at": "2026-05-20T12:34:56.789000+00:00",
  "last_runner_version": "0.1.0"
}
```

Timestamp format is the output of ``datetime.now(timezone.utc).isoformat()`` — fixed-width ISO-8601 with microsecond precision and an explicit ``+00:00`` UTC offset. Lexicographic string comparison is correct for monotonic ordering as long as the timezone offset stays fixed (which the runner guarantees by always writing in UTC).

* **JSON, not YAML.** Machine-written / machine-read; humans look at it via `cat` rarely. JSON is unambiguous + tools-friendly + the precedent shape for state-mirror files (the ledger uses JSONL; locks use plain text; this is the state-mirror category).
* **Per-category applied list** — each list is migration ids in apply order. `is_applied(state, category, migration_id)` is `O(N)` set membership on the category's list; for N in the 10s this is fine and the alternative (a hash set) would be a serialization-shape choice we'd have to undo if we ever wanted apply order back.
* **State-file schema version on the state file itself.** Future bumps to the state-file format have a known anchor. Note: the framework cannot run a migration that would upgrade its own state-file schema — that upgrade path lives outside `orchestrator/migrations/` (an external launcher would migrate before invoking the runner).
* **`last_applied_at` + `last_runner_version`** — diagnostic only. Operators use these to answer "when did anything last apply?" and "which runner version wrote this?". Never load-bearing for the applies-once check (that's purely the `applied` list).

**Atomicity** — write via `state.json.tmp` then `os.replace`. Matches the convention in `orchestrator/policy/suppression.py:forget_append` (ADR-0004 §GDPR-forget atomicity). The fsync-tmp-before-replace pattern guarantees crash-recovery: a half-written tmp can never overwrite the prior target.

**Concurrency** — advisory file lock at `migrations.state.json.lock`, acquired via `fcntl.lockf(LOCK_EX)`. Same pattern as `orchestrator/ledger.py:Ledger.append`. Concurrent runners across processes serialize at the lock; in-process re-entry is NOT supported (POSIX advisory locks are per-process; the runner does not nest its own lock acquisitions).

### D4. Reversibility contract — explicit, defense-in-depth

The `Migration` Protocol declares:

```python
class Migration(Protocol):
    id: str
    category: MigrationCategory
    description: str
    is_reversible: bool
    def upgrade(self, ctx: MigrationContext) -> MigrationResult: ...
    def downgrade(self, ctx: MigrationContext) -> MigrationResult: ...
```

`is_reversible` has no default — every author MUST think about it. `is_reversible=False` migrations raise `NotImplementedError` from `downgrade`; the runner catches + translates into a clean `MigrationNotReversibleError` ("this migration is one-way; rollback is impossible by design").

**Forward-only by default in practice.** `MigrationRunner.apply()` is the primary path; `MigrationRunner.rollback()` exists but requires `allow_rollback=True` to invoke. The default-False shape means a caller that forgot the flag (or a CLI that didn't surface it) gets a refusal, not an accidental rollback. Accidental rollback of a real migration is the catastrophic failure mode this defense-in-depth exists to prevent.

**Atomicity contract for upgrade.** If `upgrade()` raises:
* The state file pointer does NOT move for that migration.
* The state file DOES persist marks for migrations that succeeded earlier in the same batch.
* The exception propagates uncaught to the caller; the runner does NOT try/except.

Re-running `apply()` after a failure resumes from the failing migration. The migration's own internals may have written partially — that's the migration's responsibility to either rebuild forward or to advertise as non-idempotent + require operator intervention. The framework guarantees only the state-file-level atomicity.

### D5. Doctor integration timing — deferred to Week 2

Doctor.py preflight runs at every launch (Phase 5 / Pillar I). The migration check is one new doctor check: "any migrations pending?" — warn (Week 2) or refuse (Pillar I).

Week 1 has nothing pending (no real migrations yet, only synthetic test migrations). A doctor check that always returns "all good" is dead code. Land it in Week 2 alongside the first real migration when there's something to actually detect.

### D6. Migration discovery — explicit registry

Each category's `__init__.py` exports `MIGRATIONS: list[Migration]`. The runner reads that list directly. A new migration is added by:

1. Writing `vault/0007_my_migration.py` with a module-level `MIGRATION = MyMigration(...)`.
2. Adding `from .migration_0007 import MIGRATION as M0007` (or equivalent) to `vault/__init__.py`.
3. Appending `M0007` to `MIGRATIONS`.

Step 2 + 3 are 2 lines of code per migration. They are paid once at write time; the safety is paid every operator-run. A forgotten-from-registry migration is detected at runner load time (the file exists but the runner doesn't know about it — a contributor catches this immediately on the next test run). A file-system-scan alternative would silently include or exclude based on file naming conventions — louder failure modes win.

### D7. ADR-0009 scope — framework foundation only

Per-category ADRs land alongside per-category dispatchers + first migrations:

* **ADR-0009** (this one, Week 1): framework foundation — runner, state, reversibility, atomicity, dry-run vs apply, applies-once invariant, per-category dispatcher boundary.
* **ADR-0010** (Week 2 or 3): ledger migrations specifically — append-only superseding event pattern.
* **ADR-0011** (Week 3 or 4): vault migrations specifically — in-place frontmatter rewrite; concurrent-Obsidian-Sync handling.
* **ADR-0012** (Week 4 or 5): policy migrations specifically — YAML rewrite + version bump; backward-compat shape.
* **ADR-0013** (Week 5 or 6): Phase 5.5 backfill replay — the exit-criterion vehicle.

ADR-0009 stays foundation-scoped so per-category ADRs can amend or contradict it cleanly without invalidating the framework primitives.

### Downstream pillar impact

Per the Pillar A retrospective (RETRO-pillar-a.md), every Pillar B ADR explicitly names cross-pillar impact:

* **Pillar D (reply + conversation handling).** The reply classifier needs `schema_version:` on touch notes to safely evolve the touch frontmatter shape; this framework is the vehicle. Pillar D inherits a working migration runner; doesn't have to redesign one.
* **Pillar E (discovery quality + lineage).** Pillar E adds `discovery_lineage:` to Person frontmatter. This is a vault migration shaped exactly like the planned Week 2 `0001_add_schema_version_to_person_notes`. Pillar E inherits the pattern.
* **Pillar F (voice corpus + draft quality).** The voice-fidelity scoring layer needs frontmatter fields per draft; vault migrations are the supply line.
* **Pillar I (multi-tenant + OSS hardening).** Doctor preflight calls into `MigrationRunner.pending()` at every launch. Per-tenant process isolation means the runner is invoked from N processes in parallel against N independent state files (one per tenant's `~/.outreach-factory/`) — the per-tenant state-file lock is sufficient since tenants don't share state.
* **Pillar J (security + compliance).** GDPR-forget is structurally irreversible — declares `is_reversible=False`, refuses rollback. The per-tenant atomicity contract (a forget that purges ledger events AND writes the suppression entry atomically) extends to a forget migration: either both succeed or neither does, at the per-migration level. Pillar J's forget tooling can compose on this framework.

## Alternatives considered

### Alternative 1: Use Alembic for migrations

Adopt the de-facto Python migration framework. **Rejected** because Alembic assumes SQLAlchemy + a relational schema. Outreach-factory has JSONL events + Markdown frontmatter + YAML files — none of which Alembic models. Pulling Alembic in would require shimming three custom drivers (one per category), each as much code as the entire bespoke runner. The PILLAR-PLAN §5 Resolved-decisions table records this trade-off: *"Custom (Alembic-pattern), not Alembic — Alembic assumes SQLAlchemy; we have JSONL events + Markdown frontmatter."*

### Alternative 2: SQLite for the state file

Use SQLite (`migrations.db`) instead of JSON. Better concurrency primitives (transactions); atomic by construction; query-able. **Rejected** because one writer per operator install + advisory file lock is sufficient for the load we have. PILLAR-PLAN §4 "no custom database" applies: *"SQLite mirror of the ledger for analytics; append-only JSONL for writes."* The state file is in the "writes" category; SQLite would be the "analytics" shape. The simpler JSON + lockfile beats the added dependency.

### Alternative 3: File-system scan for migration discovery

Walk `orchestrator/migrations/<cat>/` at runner construction, import every `NNNN_*.py`, collect `MIGRATION` module attributes. **Rejected** because:

* The cost saved is 2 lines per migration in `__init__.py` (the import + the registry-append).
* The safety lost is loud failure on forgotten-from-registry. With file-system scan, a half-merged migration file silently shows up in the next apply; with explicit registry, the runner refuses to load with "not in `MIGRATIONS`" — a contributor catches it on the first test run.
* Type-checker can verify the registered objects implement `Migration` (mypy will type-check `MIGRATIONS: list[Migration]`); a file-system scan returns `Any`-typed module attributes that bypass static checks.

### Alternative 4: Auto-rollback on `upgrade` failure within a batch

When migration N raises mid-batch, automatically `downgrade` migrations 1..N-1 to leave the state file at the pre-batch starting position. **Rejected** because:

* It conflates two different concerns. Atomicity at the per-migration level is the framework's job; rebuilding from a multi-migration failure is the operator's call — they might prefer to fix the failing migration and re-apply (the framework's behavior), or to roll back the partial work (the operator invokes `rollback` per migration), or to accept the partial state as the new starting point.
* Auto-rollback would silently invoke `downgrade` on migrations the operator hadn't decided to roll back. For `is_reversible=False` migrations, auto-rollback would either fail loudly (defeating the auto-recovery purpose) or skip (leaving the framework's claim "the batch is atomic" untrue). Either resolution is worse than the per-migration atomicity contract we ship.

### Alternative 5: Reversibility default — force every migration to be reversible

Forbid `is_reversible=False`. **Rejected** because GDPR-forget (ADR-0004) is structurally irreversible (the whole point is the data goes away). Dropping a deprecated column is similarly one-way. The framework must permit irreversible migrations + make their reversibility status loud (every Migration declares `is_reversible: bool` explicitly, no default).

### Alternative 6: Single global migration counter

Use `0001_runner_boilerplate.py`, `0002_vault_schema_version.py`, etc., regardless of category. **Rejected** because:

* Categories evolve at different cadences. Ledger migrations are append-only events; vault migrations rewrite frontmatter; policy migrations rewrite YAML. Forcing a global counter mixes namespaces that are otherwise independent.
* Operator readability: `vault/0003` clearly means "third vault migration." `0008_vault_normalize_emails` doesn't tell you whether it's a vault migration without parsing the filename.
* Per-category sequences make per-category replay-tests (Week 5–6) easier to author.

### Alternative 7: Ship doctor.py integration in Week 1 with a placeholder check

Wire `doctor.py` to call `MigrationRunner().pending()` and report "0 pending — all good!" **Rejected** because placeholder doctor checks accumulate. Pillar I's doctor refactor (Week 43–48) will sweep them all together; don't add to the sweep pile until there's a real migration to detect.

### Alternative 8: Hex-IDed migrations (Alembic-style `down_revision` chain)

`7a3f2b1c_add_schema_version.py` with explicit `down_revision: <hex>`. **Rejected** because:

* Hex IDs don't read at-a-glance — `vault/0003` vs `7a3f2b1c` for the same migration.
* The merge-conflict-on-same-number argument Alembic uses (sequential IDs collide; hex IDs don't) is real but rare. For a single-maintainer codebase, the cost of renumbering on conflict (rename the file, update the docstring) is lower than the cost of operator-illegible IDs forever.
* `down_revision` chains can diverge if two branches both pick the same hex predecessor — a silent fork at apply time, the failure mode hex-IDs were supposed to avoid.

### Alternative 9: Defer the entire Week 1 framework; start with one ad-hoc vault migration in Week 1

Land `vault/0001_add_schema_version_to_person_notes` as a one-off script (not a framework migration); generalize to a framework in Week 2 once we have a concrete shape. **Rejected** because:

* The vault migration is the *consumer* of the framework; designing the framework around one consumer's needs would bake in shape decisions we'd later regret.
* The synthetic-migration test suite (Week 1) is what proves the runner's contracts (atomicity, idempotence, rollback). Without it, the first real migration would land without those contracts pinned.
* The handoff-doc-as-load-bearing-artifact pattern from Pillar A applies: design decisions go in ADRs before the first code change that depends on them, not after.

### Alternative 10: Per-category schema version on every event / file / rule

`v: 1` on ledger events; `schema_version: 1` on Person frontmatter; `version: 1` on policy YAMLs — each independent. **Accepted, but orthogonal to this ADR.** I3 is the invariant; this framework is the *vehicle* for evolving those versions. The ADR records the invariant as already-met for ledger events + policy YAMLs; not-yet-met for Person frontmatter (Week 2's first vault migration adds it).

## Consequences

### Positive

- **Pillar B exit criterion is on a clear path.** The runner exists; Week 2 adds the first real migration; Week 5–6 builds the synthetic-vault replay test on top of these primitives. The exit criterion's vehicle (the replay test) is now an integration-level use of the framework, not a separately-built thing.
- **Downstream pillars inherit a working migration runner.** Pillar D / E / F can add vault schema bumps in 2–3 hours each (write the migration, register it, write the test). Pillar I's doctor preflight check is ~20 LOC once a real migration exists.
- **The state file lock + atomicity contract structurally rule out partial-apply at the framework level.** The remaining risk surface is per-migration (a migration that itself half-writes its own state); that's the migration author's responsibility + the per-category ADRs (0010–0012) lock down per-category atomicity contracts.
- **Reversibility is forced into design at write time, not deferred to incident time.** Every author declares `is_reversible: bool` — the question is answered before the migration ships.
- **The synthetic-migration test suite (67 tests) pins every framework contract:** dry-run no-mutation, apply moves pointer, idempotent re-apply, rollback reverses, rollback refuses when irreversible, partial-apply atomicity, registry validation (duplicates / ordering / category mismatch), concurrent-runner serialization across processes, MigrationContext shape, defense-in-depth `allow_rollback` flag.
- **Future contributors get a load-bearing template.** Each per-category ADR (0010–0012) inherits this ADR's shape; per-migration files inherit the `Migration` Protocol; per-category `MIGRATIONS` lists inherit the registry pattern.

### Negative

- **No real migrations ship in Week 1.** The framework is exercised only by synthetic test migrations; the first real migration (`vault/0001_add_schema_version_to_person_notes`) waits for Week 2. **Mitigation:** Week 2's first real migration validates the framework on a real surface; the 67 synthetic tests give high confidence the framework is correct independent of any one real consumer.
- **State-file schema bump path is out-of-band.** The framework can't run a migration that would upgrade its own state-file schema; an external launcher would have to do it. **Mitigation:** the state-file schema is unlikely to bump frequently (it's three fields); when it does, an external upgrade script is ~20 LOC. Documented in the `MigrationState.schema_version` field's docstring.
- **Single-writer convention requires operators to not run two `dispatcher` processes against the same `~/.outreach-factory/`.** The advisory file lock catches the concurrent-runner case, but does not prevent it — the second runner blocks instead of refusing. **Mitigation:** doctor.py (Pillar I) is the right surface for "stale lock detected — is another runner active?" warnings. Pillar B Week 1 doesn't ship doctor integration; Pillar I's broader process-isolation work covers this case.
- **Per-category dispatcher boundary lives in the per-category sub-packages, which Week 1 ships empty.** A reader of `orchestrator/migrations/vault/__init__.py` sees only `MIGRATIONS: list[Migration] = []` — the shape of what a vault migration looks like is documented in ADR-0011 (Week 3–4), not yet visible in code. **Mitigation:** the docstring in `vault/__init__.py` describes the expected shape + cites the ADR forward-reference. Week 2's first real migration makes the shape concrete.
- **The runner's `vault_dir` is `Optional[Path]`** because operator config (`~/.outreach-factory/config.yml` `vault.path:`) is the source. A runner constructed without a `vault_dir` cannot apply vault migrations — the per-migration `ctx.vault_dir is not None` check is the per-migration's responsibility. **Mitigation:** future vault migrations check `ctx.vault_dir is not None` at the top of `upgrade()` and refuse if unset. ledger + policy migrations don't need it.

### Neutral / observability

- The runner uses `logging.getLogger("orchestrator.migrations.runner")`; operators can route those messages to their existing observability stack (Pillar G's OTel work will wire this end-to-end).
- The `last_applied_at` + `last_runner_version` fields surface in `cat ~/.outreach-factory/migrations.state.json` for operator debugging.
- `MigrationOrderError` + `MigrationNotReversibleError` are public exception types — operators (and ops tooling) catch them by class, not by string-match.

## Compliance with invariants

- **I1 (single source of truth):** The state file's "applied" list is the SoT for "has migration N been applied?" The `Migration state` row in `docs/SOURCES-OF-TRUTH.md` is updated to point at `orchestrator/migrations/state.py` as the read/write SoT.
- **I2 (two-phase commit):** Migrations themselves are not external side effects in the I2 sense — they're internal state evolution. The framework's atomicity contract (state-file pointer moves only on `upgrade` success) is the migration-framework analog of the email-send two-phase commit: `upgrade` succeeds → `mark_applied` → `save_state_atomic` is the sequence, with the lock held across all three. Failure at any step does not corrupt the state file.
- **I3 (schema versioning):** This ADR delivers the framework that operationalizes I3. The state file itself carries `schema_version: 1`. The `Migration` Protocol forces every migration to declare its identity + reversibility — schema migrations are now first-class code.
- **I5 (observable by default):** Every `apply` + `rollback` logs at INFO with the migration id + category + description. Future Pillar G OTel wiring picks up the existing log calls without changes.
- **I6 (tests prove invariants):** 67 new tests across `tests/test_migrations_state.py` (33) + `tests/test_migrations_runner.py` (34). Cross-process serialization is pinned by multiprocessing-based tests; tmp-then-rename atomicity is pinned by a monkey-patched-os.replace crash simulation; rollback refusal + defense-in-depth + per-migration atomicity each have explicit tests.
- **I7 (cost is a first-class concern):** Migrations themselves do not emit `cost_incurred` events (they're internal state evolution, not external API calls). When a Pillar G observability concern requires per-migration cost attribution, an additional event type would be added in a future ADR; not in scope here.
- **I8 (decisions documented):** This ADR. ADR-0008 §References does not yet point forward (the migration framework was Pillar B work, deliberately decoupled from Pillar A's exit). `docs/adr/README.md` gains the ADR-0009 row.

Does not weaken any invariant. The "Migration state" SoT row gains a code pointer where it had a path-only stub.

## Migration / rollout

Greenfield: `orchestrator/migrations/` is a new package; no existing on-disk state to migrate. The state file is created on first `apply()` (or first `save_state_atomic` from any tool); a missing file is the greenfield install signal — `load_state(state_dir)` returns an empty `MigrationState()`.

Week 1 does not touch `~/.outreach-factory/` on an operator's machine. Running `python -c "from orchestrator import migrations"` is a no-op import (the runner reads the empty Week 1 `MIGRATIONS = []` lists). Operators are unaffected until Week 2 ships the first real migration.

Week 2's first migration (`vault/0001_add_schema_version_to_person_notes`) is when operators will first see migrations apply on their vault. The Week 2 handoff document is responsible for the rollout instructions (run dry-run first; verify against a vault backup; then apply).

When ADR-0010 / 0011 / 0012 land (per-category dispatcher ADRs), the per-category sub-packages gain concrete code; this ADR's shape contracts hold.

Doctor preflight integration is Week 2.

### Recovery from a mid-flight crash

Per the atomicity contract (D4), a migration that raises mid-batch leaves the framework in a recoverable state. Operators recover by re-running `apply()`; the framework's design makes this safe by construction. The recovery procedure (Pillar B Week 6 parallel-review P1 fix per `.planning/REVIEW-pillar-b-operator-ux.md` §P1-2):

1. **Read the exception.** The exception that propagated names the failing migration + the cause. Common shapes:
   - `IdentityBackfillConflictError` (from `vault/0002`): two Person notes share a strong identity key (linkedin or email). The error names the files + shared key values. Resolve the conflict by editing the offending Person notes' frontmatter, then continue.
   - `FrontmatterError` (from any vault migration): a Person note has malformed YAML frontmatter. The error names the file path. Fix the YAML by hand, then continue.
   - `PolicyFileError` (from any policy migration): a policy YAML file is shape-wrong. The error names the file + the malformed shape. Fix the YAML, then continue.
   - `OSError` (disk full / permissions): fix the underlying OS condition (free disk space, fix permissions on `~/.outreach-factory/` or the vault path), then continue.

2. **Re-run `apply()`.** Per D4:
   - The state file pointer did NOT advance for the failing migration. The runner re-attempts it from the same starting state.
   - Migrations that succeeded BEFORE the failing one in the same batch ARE marked applied. Their per-migration idempotence checks skip already-completed work on the resume.
   - Per-file atomicity (tmp-then-rename + fsync) guarantees no half-written Person notes, ledger events, or policy files exist on disk.

3. **Do NOT manually edit `migrations.state.json`.** The state file's `applied` list is the runner's source of truth for "what's done." Hand-editing it can desync the state file from on-disk effects (a migration whose effects are present on disk but is marked un-applied will re-run; a migration whose effects are absent but is marked applied will be skipped silently). The right tools for state-file changes are `mark_applied` + `mark_unapplied` from `orchestrator.migrations.state`, which the framework calls under the state-file lock.

4. **If `apply()` keeps failing after a fix, restore from backup.** Operator backup of `~/.outreach-factory/` is the recovery floor — the framework cannot manufacture a state it didn't preserve. For irreversible migrations specifically (any `is_reversible=False`), backup-and-restore is the only rollback vehicle by design (per D4).

The operator-facing surface (`scripts/doctor.py` hint + `INSTALL.md` "Apply pending migrations" section) point operators here.

## References

- ADR-0001 (policy engine architecture) — the engine surface this framework parallels (rules → migrations; ledger → state file; YAML → registry).
- ADR-0004 (suppression rules + GDPR forget) — the `is_reversible=False` precedent; the tmp-then-rename atomicity precedent (`forget_append`).
- ADR-0006 (budget rules + cost_incurred event) — the `v: 1` schema-version-on-event precedent that I3 generalizes to all persistent state.
- `docs/PILLAR-PLAN.md` §1 I3 — schema versioning invariant; this framework operationalizes.
- `docs/PILLAR-PLAN.md` §2 Pillar B — scope + exit criterion.
- `docs/PILLAR-PLAN.md` §5 — "Migration framework: Custom (Alembic-pattern), not Alembic" resolved decision.
- `docs/SOURCES-OF-TRUTH.md` row "Migration state" — updated to point at `orchestrator/migrations/state.py`.
- `docs/RISK-REGISTER.md` — R002 (vault frontmatter drift), R005 (ledger schema bump regret) — both inherit mitigation from this framework existing.
- `.planning/HANDOFF-pillar-b-week-1.md` — the per-week handoff that scoped Week 1.
- `.planning/RETRO-pillar-a.md` — the retrospective that mandates per-ADR "Downstream pillar impact" + per-week independent review.
- `orchestrator/migrations/types.py` — `Migration` Protocol, `MigrationCategory`, `MigrationContext`, `MigrationResult`.
- `orchestrator/migrations/state.py` — `MigrationState`, `load_state`, `save_state_atomic`, `acquire_state_lock`, `is_applied`, `mark_applied`, `mark_unapplied`.
- `orchestrator/migrations/runner.py` — `MigrationRunner`, `MigrationOrderError`, `MigrationNotReversibleError`, `RUNNER_VERSION`.
- `orchestrator/migrations/{ledger,vault,policy}/__init__.py` — per-category `MIGRATIONS: list[Migration]` registries (Week 1 ships empty).
- `tests/test_migrations_state.py` — 33 tests covering shape, round-trip, atomicity, lock contention.
- `tests/test_migrations_runner.py` — 34 tests covering pending / dry-run / apply / rollback / validation / concurrency / context.
- Shipped since this ADR landed:
  - **ADR-0011** — vault migrations: per-file atomicity, helper-module dispatcher, Obsidian Sync handling. **Accepted** 2026-05-19 (Pillar B Week 2).
  - Doctor preflight integration (warn-on-pending) — `scripts/doctor.py:check_migrations` shipped Week 2.
  - First real vault migration (`vault/0001_add_schema_version_to_person_notes`) — shipped Week 2 alongside ADR-0011.
  - **ADR-0010** — ledger migrations: append-only superseding event pattern, `migration_event` audit trail, helper-module dispatcher. **Accepted** 2026-05-19 (Pillar B Week 3).
  - First real ledger migration (`ledger/0001_close_orphan_send_intents`) — shipped Week 3 alongside ADR-0010.
  - **ADR-0012** — policy migrations: surgical YAML rewrite, helper-module dispatcher, engine version-range coordination. **Accepted** 2026-05-20 (Pillar B Week 4).
  - First real policy migration (`policy/0001_add_engine_compat_field`) — shipped Week 4 alongside ADR-0012, with coordinated engine update (`SUPPORTED_POLICY_SCHEMA_VERSIONS = frozenset({1, 2})`).
  - **ADR-0013** — synthetic-replay exit-criterion vehicle: wrapped Phase 5.5 backfills + static fixture + apply-order reorder (VAULT → LEDGER → POLICY per D27). **Accepted** 2026-05-21 (Pillar B Week 5 ships foundations; Week 6 closes the gate via doctor refuse-on-pending feature flag).
  - Wrapped vault backfill (`vault/0002_backfill_identity_lineage`) + wrapped ledger backfill (`ledger/0002_backfill_send_history`) — shipped Week 5 alongside ADR-0013.
  - Default cross-category apply-order reorder (`_DEFAULT_APPLY_ORDER = (VAULT, LEDGER, POLICY)` per ADR-0013 D27) — supersedes this ADR's original §D7 reference to `MigrationCategory` enum declaration order as the default. The enum declaration order is retained as the state-file JSON-serialization key order; the apply-order constant is a separate decision surface.
  - Doctor strict-mode feature flag (`OUTREACH_FACTORY_STRICT_MIGRATIONS=1`) — `scripts/doctor.py:check_migrations` Week 6 (Pillar B exit gate; ADR-0013 D26 + D29 + D30). Exact-match `"1"` promotes pending-migrations from WARN to FAIL; default stays WARN. Pillar I (Weeks 43–48) flips the default + removes the flag.
- Reserved / planned:
  - Doctor refuse-on-pending default flip + flag removal — Pillar I (Weeks 43–48); the Week 6 feature flag is the soft-rollout precursor.
