# ADR-0013: Synthetic-replay exit-criterion vehicle — wrapped Phase 5.5 backfills + synthetic fixture + apply-order reorder

- **Status:** Accepted
- **Date:** 2026-05-21
- **Pillar:** B (Migration framework — Week 5 + Week 6 exit-criterion vehicle)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0009 (Week 1) shipped the migration-framework foundation. ADR-0011 (Week 2), ADR-0010 (Week 3), and ADR-0012 (Week 4) shipped the three per-category dispatchers + first concrete migrations against vault, ledger, and policy YAML surfaces respectively. Per PILLAR-PLAN §2 Pillar B, the exit criterion is binding:

> *"the Phase 5.5 backfills replayed cleanly through the migration runner against a fresh synthetic vault; doctor.py checks migration state on every launch."*

ADRs 0009–0012 each individually deferred the synthetic-replay vehicle as out-of-scope. This ADR consumes that scope. The structural shape:

1. **Phase 5.5's two backfill scripts (`orchestrator/backfill_identity.py` + `orchestrator/backfill_ledger.py`) are repackaged as `Migration` instances.** They become the second migration in their respective categories: `vault/0002_backfill_identity_lineage` and `ledger/0002_backfill_send_history`. Existing operators (Yang) already ran the scripts against their real state; new operators apply via the runner as part of OSS bring-up.
2. **A synthetic before-state fixture lives at `tests/fixtures/synthetic_pillar_b/`.** Three Person notes, one touch note, one orphan ledger event, one factory-shape policy file. The replay test points a `MigrationRunner` at a fresh copy of the fixture and applies all five migrations.
3. **The runner's default cross-category apply order changes** from `LEDGER → VAULT → POLICY` (ADR-0009's hypothetical-future-shape choice) to `VAULT → LEDGER → POLICY` (the concrete dependency the wrapped backfills introduce — ledger/0002 reads `id:` stamped by vault/0002).
4. **Doctor's refuse-on-pending lands in Week 6 behind a feature flag** (`OUTREACH_FACTORY_STRICT_MIGRATIONS=1`); default stays warn-on-pending. Pillar I (Weeks 43–48) flips the default + removes the flag.

Concerns this ADR resolves:

- **The exit-criterion property has a verification vehicle.** Pillar B's exit criterion is reified as `tests/test_migrations_replay.py::TestExitCriterionProperty` — a single test that constructs a fresh synthetic before-state, runs `apply()`, and verifies every SoT invariant the production code preserves.
- **Cross-category dependency surfaces are named.** The Week 5 backfill replay is the first concrete cross-category dependency in the framework (`ledger/0002` reads vault state). The framework's default apply order is updated to honor it; future migrations follow the same convention (vault is the operator-edited substrate; ledger denormalizes / retroactively emits from it).
- **The wrapped backfills' atomicity contracts compose with their dispatchers.** vault/0002 writes through `_vault_io.write_person_frontmatter_atomic` (per-file tmp-then-rename + fsync). ledger/0002 writes through `_ledger_io.append_event_atomic` which delegates to `Ledger.append`'s O_APPEND + fcntl.lockf + fsync path. The wrap does not bypass either.
- **The doctor hardening posture is documented.** Refuse-on-pending behind a feature flag (Week 6) is the soft-rollout precursor to Pillar I's eventual default-on flip.

Risks this ADR mitigates: **R002 (vault frontmatter drift)** + **R005 (ledger schema bump regret)** by exercising the framework end-to-end against a representative before-state. **R-replay-fragility** (new): the framework promises "backfills replay cleanly," but without a verification vehicle the promise is words-only. ADR-0013 ships the vehicle.

## Decision

### D23. Migration IDs for the wrapped backfills — sequential per-category (`0002_`)

The Phase 5.5 backfill scripts become `vault/0002_backfill_identity_lineage` + `ledger/0002_backfill_send_history`. Sequential IDs in their respective categories (the second migration after vault/0001 + ledger/0001).

Two paths were considered:

* **`0002_` (sequential IDs).** Adopted. The wrapped backfills are semantic forward migrations — they take an unmigrated vault + ledger and produce a Phase-5.5-shape vault + ledger. A new operator who never ran the backfill scripts applies them as migrations as part of OSS bring-up; existing operators (Yang) whose state already shows the backfills' effects mark them applied via a one-time `mark_applied` call.
* **`0000_` (pre-zero IDs).** Rejected. Numeric-prefix ordering is the framework's load-bearing invariant (ADR-0009 D2). A `0000_` would require special-casing in the runner (sort `0000` before `0001`) which adds complexity for a one-time historical encoding.

**Operator-facing one-time bring-up for existing operators (Yang).** Pre-Week-5 operator state already shows the backfills' effects (id + identity_keys on Person notes; backfilled events with `_recovered_by: "backfill"` in the ledger). For these operators, the runner's state file needs to be seeded with `vault/0002_backfill_identity_lineage` and `ledger/0002_backfill_send_history` marked as already applied — otherwise the runner would re-apply them and the per-migration idempotence checks would have to do the heavy lifting (which they DO — the wrap preserves the original idempotence — but seeding state is cleaner).

The seed is a one-time operator instruction surfaced in Week 6 alongside the doctor feature-flag rollout. Until then, an operator who runs `apply()` against an already-backfilled state sees zero new emits (the per-migration idempotence checks short-circuit). The migration_event still emits (audit trail continuity per ADR-0010 D17).

### D24. Synthetic fixture shape — hybrid (static + programmatic builder)

The synthetic before-state lives at `tests/fixtures/synthetic_pillar_b/` (static) plus a `synthetic_state_dir` fixture in `tests/conftest.py` (programmatic builder that copies the static fixture into `tmp_path`).

Three shapes were considered:

* **Static checked-in fixture only.** Pros: deterministic, version-controlled, inspectable (`cat tests/fixtures/synthetic_pillar_b/vault/10 People/Alice Anderson.md` shows what the migration sees). Cons: schema evolution requires hand-editing.
* **Programmatic builder only.** Pros: schema-evolution updates the builder, not the files; consistent. Cons: the test reader must mentally execute the builder to understand the before-state.
* **Hybrid.** Adopted. Static portion is the operator-visible shapes (3 Person notes with different identity_keys shapes; 1 touch note; 1 orphan ledger event; 1 factory-template policy file). The `synthetic_state_dir` fixture copies it to `tmp_path` so tests can mutate freely. Future stress tests (1000 Person notes etc.) build programmatically on top of the baseline.

**The static portion (small, readable):**

```
tests/fixtures/synthetic_pillar_b/
├── README.md
├── vault/
│   ├── 10 People/
│   │   ├── Alice Anderson.md       # linkedin + email; matching touch
│   │   ├── Bob Brown.md            # email only; no touch
│   │   └── Carol Cole.md           # linkedin only; last_touch w/o touch → orphan
│   └── 40 Conversations/
│       └── 2026-04-10 Alice initial.md   # sent: true, channel: email
├── ledger/
│   └── events-2026-04-15.jsonl     # one orphan send_intent (no outcome)
└── policies/
    └── cooldowns.yml               # version: 1, factory-style rules + comments
```

Three Person-note shapes (linkedin+email, email-only, linkedin-only) exercise the `mint_id` provenance-suffix logic (`-li`, `-em`, `-li`). The orphan in the ledger exercises ledger/0001 (close orphan). The touch note exercises ledger/0002's send-pair emission. Carol's last_touch-without-touch exercises ledger/0002's orphan emission. The factory-style policy file with operator comments exercises policy/0001's surgical-edit preservation.

**Future Pillar D / E / F migrations extend the static fixture.** When Pillar D adds `vault/0003_add_reply_state_fields`, the Pillar D author appends new touch notes (or extends existing ones) to test the new fields. When Pillar E adds `vault/0004_add_discovery_lineage`, the author extends each Person note. The static portion grows incrementally as the framework evolves.

### D25. ADR-0013 scope — narrow (Week 5 + Week 6 vehicle work only)

This ADR covers:

* The wrapped-backfill migration shape (D23).
* The synthetic fixture shape (D24).
* The dry-run cross-category-dependency limitation (D24-N below).
* The doctor refuse-on-pending posture (D26: Week 6 feature flag; Pillar I flips default).
* The default-apply-order reorder VAULT → LEDGER → POLICY (D27).
* Downstream pillar impact.

Out of scope (deferred):

- **Pillar I OSS hardening.** The doctor's refuse-on-pending DEFAULT flip + the feature-flag removal land in Pillar I. ADR-0013 ships the feature flag (Week 6) as the soft-rollout precursor.
- **Future Pillar C / D / E / F migrations.** This ADR pins the replay vehicle's shape; new migrations extend the static fixture + the replay test. They get their own ADRs.
- **Multi-tenant per-vault replay (Pillar I).** The synthetic-state-dir fixture is single-tenant; multi-tenant work in Pillar I will spawn N parallel state dirs, one per tenant. Out of scope for Week 5–6.
- **A CLI (`python -m orchestrator.migrations apply` + `--dry-run` / `--rollback`).** Deferred to Pillar I OSS bring-up.

### D24-N. Cross-category dry-run limitation — documented + tested

**The problem.** `runner.dry_run()` invokes every migration's `upgrade` with `ctx.dry_run=True`. Migrations honor `dry_run` by NOT mutating their on-disk surface but DO read on-disk state (otherwise they couldn't produce counts). When migration N's `upgrade` reads state that an earlier migration in the same batch has mutated, the dry-run cannot accurately preview the chained outcome — the earlier migration's mutation didn't actually land.

Concretely: `ledger/0002_backfill_send_history` reads `id:` from Person notes (stamped by `vault/0002_backfill_identity_lineage`). On a dry-run of the full batch, vault/0002 returns its preview WITHOUT writing the `id:` field. Then ledger/0002 walks Person notes, sees no `id:`, and reports `affected_count = 0` (recording `persons_without_id: 3` in the migration_event's diagnostic field).

**Real apply** (no dry-run) flows correctly: vault/0002 writes the `id:` field; ledger/0002 then reads it; emits 3 enrolled + send-pair + orphan events.

**The contract** the framework promises is the actually-applied counts, which `apply()` produces correctly. Dry-run is a preview tool with a documented limitation: it cannot preview cross-category chained outcomes.

**Test coverage.** `tests/test_migrations_replay.py::TestDryRunPreview::test_dry_run_then_real_apply_produces_same_counts_modulo_xcat_deps` pins both behaviors:

* Migrations without cross-category dependency (vault/0001, vault/0002, ledger/0001, policy/0001): dry-run count == apply count.
* `ledger/0002`: dry-run reports 0 affected; apply reports 5. The asymmetry is the documented limitation.

**Future work (deferred).** A "sequenced preview" mode (apply migration N, dry-run migration N+1, roll back) would correctly preview chained outcomes but adds significant complexity. Pillar I (or a later sweep) can revisit if the operator-facing dry-run UX needs it. For Week 5–6 the documented asymmetry is acceptable — the test suite pins it; operators reading the dry-run report see the diagnostic counts (`persons_without_id`, `touches_without_person_match`) and infer the chained effect.

**Rejected alternative.** Make ledger/0002 robust to missing `id:` by re-deriving id from the Person note's `email:` / `linkedin:` fields directly. Rejected — would duplicate vault/0002's `mint_id` logic + diverge over time + violate the I1 invariant that the SoT for `id:` is vault frontmatter. The cross-category dependency is real and should be modeled, not hidden.

### D26. Doctor refuse-on-pending — Week 6 behind a feature flag

ADR-0011 D12 + ADR-0010 §D16 + ADR-0012 D20 each deferred doctor's refuse-on-pending to Pillar I. The PILLAR-PLAN §2 Pillar B exit criterion text mentions "doctor.py checks migration state on every launch" — this ADR resolves the interpretation:

* **Week 6 (Pillar B exit):** `scripts/doctor.py` gains opt-in refuse-on-pending behind environment variable `OUTREACH_FACTORY_STRICT_MIGRATIONS=1`. When the variable is set, doctor returns `FAIL` (exit code 1) on pending migrations instead of `WARN`. Default stays `WARN`.
* **Pillar I (Weeks 43–48):** flip the default to FAIL + remove the feature flag.

Rationale:

* **The exit-criterion text is about the FRAMEWORK being able to refuse**, not about it being the default. The feature flag closes the criterion-text bound while preserving the asymmetric-failure-cost calculus (operators with stale state files don't have their send loops bricked).
* **Pillar I is the canonical home for hard refuse-on-pending defaults.** By Pillar I, operators have had ~37 weeks (B Week 6 → I Week 43) to internalize the warn-on-pending discipline. A flip to refuse-by-default at Pillar I is a known-cost UX change, not a surprise.
* **The feature flag is operator-visible + tested.** Operators who want belt-and-suspenders enforcement opt in now; operators who haven't internalized yet keep the soft posture.

Rejected alternatives:

- **Hard refuse on day one of Week 6.** Breaks every existing operator's send loop the moment they pull Week 6 code (until they `apply()`). The vault migration `0002_backfill_identity_lineage` requires conflict resolution; an operator who hits a conflict can't proceed until they fix it — having the dispatcher refuse-on-pending forces a coupling between "apply migration" + "send dispatch" that the soft-rollout posture explicitly avoids.
- **Leave doctor at warn-on-pending in Week 6; do everything in Pillar I.** Doesn't close the exit-criterion text ("doctor.py checks migration state on every launch"). The feature flag is the soft middle.

**Counter-argument:** shipping the flag in Week 6 commits to a UX path Pillar I might want to revisit. **Accept** — the flag is a tested escape hatch; Pillar I can remove it without breaking flag-aware operators (they'll be no-ops once the default flips).

### D27. Default cross-category apply order — VAULT → LEDGER → POLICY

ADR-0009 D7 + the original `MigrationCategory` enum declaration order (`LEDGER, VAULT, POLICY`) chose ledger-first based on the hypothetical-future-shape argument: "ledger migrations may add new event types that vault migrations consume." This was a reasonable choice when no cross-category dependencies existed; Week 5 surfaces a real cross-category dependency that runs the OTHER direction:

* `ledger/0002_backfill_send_history` reads `id:` from Person notes.
* `id:` is stamped by `vault/0002_backfill_identity_lineage`.

If LEDGER runs first, Person notes lack `id:` when ledger/0002 walks them, and enrolled events are emitted only for Person notes that happen to already have `id:` set (operators who manually pre-stamped). The synthetic-replay vehicle would produce a degenerate after-state.

**The decision.** Reorder the runner's default cross-category apply order to `VAULT → LEDGER → POLICY`. The `MigrationCategory` enum declaration order (`LEDGER, VAULT, POLICY`) is preserved as the JSON-serialization key order for the state file's `applied:` dict (existing state files on disk are byte-identical after this change).

**Implementation (runner.py):**

```python
_DEFAULT_APPLY_ORDER: tuple[MigrationCategory, ...] = (
    MigrationCategory.VAULT,
    MigrationCategory.LEDGER,
    MigrationCategory.POLICY,
)
```

`pending()` and `_run()` (the shared dry-run/apply core) consult `_DEFAULT_APPLY_ORDER` when no explicit category is requested. Per-category calls (`runner.apply(MigrationCategory.LEDGER)`) are unchanged — operators can apply individual categories in any order they choose.

**Why the new rationale is sharper:** vault is the operator-edited substrate everything else reads. Ledger denormalizes / retroactively emits from vault state (Phase 5.5 backfill_ledger); policy is independent and runs last. Future migrations follow the same shape — vault evolves the surface; ledger picks up; policy is orthogonal.

**Rejected alternatives:**

- **Reorder the `MigrationCategory` enum declaration.** Rejected — would change JSON-serialization order on the state file's `applied:` dict. Existing state files on disk would round-trip with the new key order (Python dicts preserve insertion order on >=3.7), but tests that pin the serialization shape would break. Decoupling apply-order from declaration-order is the cleaner shape.
- **Add a per-migration `depends_on` field.** Rejected — over-engineered for the Week 5 case (one cross-category dep). If future migrations introduce more complex DAGs, a future ADR adds `depends_on` cleanly.
- **Have ledger/0002 robust to missing `id:`.** Rejected (covered in D24-N) — would duplicate vault/0002's mint logic + violate I1.

**Compliance with existing tests:** `TestDefaultRegistries.test_runner_with_no_registries_uses_real_packages` is updated to expect VAULT first (5 pending in the new order). `TestPending.test_pending_orders_by_default_apply_order` (renamed from `test_pending_orders_by_category_enum`) pins the new contract explicitly.

### Downstream pillar impact

Per the ADR-0009 convention (every Pillar B ADR explicitly names cross-pillar impact):

* **Pillar C (multi-channel coherence).** When Pillar C adds `li_invite_intent` / `li_invite_confirmed` event types, the Pillar C author adds a `ledger/000N_baseline_linkedin_events` migration (if any retroactive backfill is needed) and extends the synthetic fixture's `events-*.jsonl` with sample LinkedIn intents. The replay test's `TestExitCriterionProperty` extends to verify the LinkedIn shapes.

* **Pillar D (reply + conversation handling).** Pillar D adds `reply_classified` + `conversation_state_transition` event types and corresponding touch-note frontmatter fields. The Pillar D author adds:
  - `ledger/000N_add_reply_events.py` (if backfilling historical replies).
  - `vault/000N_add_reply_state_fields.py` for touch-note frontmatter.
  - Extends the synthetic fixture's `40 Conversations/` with sample touch notes carrying the new fields.
  - Extends the replay test's `TestExitCriterionProperty` to assert the new shapes.

* **Pillar E (discovery quality + lineage).** Pillar E adds `identity_keys.discovery_lineage:` blocks via a vault migration. Same shape: extends static fixture + replay test.

* **Pillar F (voice corpus + draft quality).** Voice-fidelity scoring may add per-draft frontmatter fields via vault migrations on touch notes. Same shape.

* **Pillar G (observability).** Pillar G consumes `migration_event` audit-trail events emitted by ledger migrations (per ADR-0010 D17). The Week 5 wrapped backfill `ledger/0002_backfill_send_history` emits one `migration_event` with diagnostic fields (`enrolled_emitted`, `sends_emitted`, `orphans_emitted`, `persons_without_id`, `touches_without_person_match`). Pillar G's "when did the schema evolve?" dashboard charts these directly.

* **Pillar I (multi-tenant + OSS hardening).** ADR-0013 D26 ships the doctor refuse-on-pending feature flag in Week 6; Pillar I flips the default. The cross-category apply-order reorder (D27) generalizes — Pillar I multi-tenant per-vault replay spawns one runner per tenant, each with the same default order. Operators upgrading from "I had Phase 5.5 backfill scripts already" need a one-time `mark_applied` instruction; Pillar I OSS bring-up provides the CLI for this.

* **Pillar J (security + compliance).** GDPR-forget on a vault Person note (purge ALL frontmatter fields including `id:` + `identity_keys:`) does not interact with the wrapped backfills — once a Person note is purged, the migration's idempotence check sees no `id:` field and could re-mint a different one. The forget tooling (Pillar J) deletes the Person note entirely rather than nulling fields, so the migration sees nothing to mint. ADR-0013 doesn't add new Pillar J concerns.

## Alternatives considered

### Alternative 1: Defer the entire replay vehicle to Pillar I

Wait for OSS bring-up to write the synthetic-replay vehicle; Pillar B exits without the verification test. **Rejected** because the PILLAR-PLAN §2 Pillar B exit criterion is binding (mentioned twice — once in the pillar summary and once in §6 status). Pillar I is Weeks 43–48; deferring the exit-criterion vehicle that long leaves Pillar B's "stable" claim un-anchored. The pattern from Pillar A (per-week handoff doc + per-week independent review) keeps each pillar's exit-criterion tight; this ADR matches.

### Alternative 2: Build the replay vehicle from scratch (no wrapping of existing backfill scripts)

Write a synthetic vault + ledger + policy from scratch in Python, then write migrations from scratch to walk them. **Rejected** because:

* The Phase 5.5 backfill scripts are the canonical historical truth. Operators (Yang) have already used them; their logic is the SoT for "how do you backfill identity + send history?" Re-writing from scratch would create a divergence between the scripts (used in production) and the migrations (used in the test).
* The wrapping IS the integration test — if the backfill scripts' logic changes (operator finds a bug, ships a fix), the migrations should track. Re-writing means tracking is manual.

The chosen approach (inlining the logic into the migrations while keeping the backfill scripts as standalone CLIs) accepts ~200 LOC of duplication in exchange for clean import boundaries. Future divergence would be operator-visible (the script + migration would behave differently on the same input).

### Alternative 3: Import backfill_identity / backfill_ledger directly from the migration

`vault/migration_0002.py` does `from orchestrator import backfill_identity` and calls `backfill_identity.build_plan` + `backfill_identity.render_with_identity` etc. **Rejected** because `backfill_identity.py` uses bare-name imports (`import identity` rather than `from orchestrator import identity`) — designed to run as `python orchestrator/backfill_identity.py` with that directory as CWD. Bringing it into the migration framework's import path would require either a `sys.path` shim inside the migration (subtle two-module-identity risk in production) or refactoring the backfill scripts to use absolute imports (out-of-scope churn).

The adopted approach inlines the logic — duplicates ~200 LOC per migration but produces clean, self-contained migration modules. The duplicated logic is deliberate (the backfill scripts are essentially frozen Phase 5.5 deliverables; their migration wrappers track them by code-similarity discipline, not import).

### Alternative 4: Make the wrapped backfills reversible

Define `downgrade` paths that remove the stamped fields. **Rejected** for two reasons:

* **vault/0002:** `id` mint is path-dependent (the provenance suffix is chosen from the strong-key inventory at mint time). If a downgrade removed the field and a future re-apply ran after operator vault edits (added an email, removed a linkedin), the new id could differ from the original — a denormalized-view drift the asymmetric-failure-cost calculus says we should structurally avoid.
* **ledger/0002:** the ledger is append-only (ADR-0010 D14). A "rollback" would require either deleting bytes (forbidden) or inventing a "re-open" event type. Backup + replay is the canonical recovery vehicle.

Both migrations declare `is_reversible=False`; the runner refuses rollback with `MigrationNotReversibleError`.

### Alternative 5: Migration IDs `0000_` instead of `0002_` for the wrapped backfills

Pre-zero prefix indicates "historical replay shape, not forward migration." **Rejected** per D23 — the framework's load-bearing invariant (ADR-0009 D2) is numeric-prefix ordering; adding `0000_` would require special-casing in the runner. The semantic is "second migration in the category" + the existing-operator state seed handles the "they already ran this" case.

### Alternative 6: Single static fixture, no programmatic builder

Just check in `tests/fixtures/synthetic_pillar_b/` and have tests refer to it directly via paths. **Rejected** because tests must mutate the synthetic state (apply migrations, then assert on the result). Without a per-test copy, tests would either interfere with each other or have to clean up after themselves (brittle). The `synthetic_state_dir` fixture's `tmp_path` copy is the standard pattern.

### Alternative 7: No reorder of default apply order — operators use per-category apply for first-run backfills

Keep `LEDGER → VAULT → POLICY` as default; operators run `runner.apply(MigrationCategory.VAULT)` before `runner.apply(MigrationCategory.LEDGER)` for the first-run backfill. **Rejected** because:

* It makes `runner.apply()` (no args) silently produce a degenerate after-state — the runner walks LEDGER first, ledger/0002 skips every Person (no id), then vault/0002 stamps id, then ledger/0002 is marked applied (it returned successfully with affected_count=0). Operators inspecting the post-state would see zero enrolled events + zero send-pair events. A debugging session ensues.
* The cross-category dep is real + concrete; the framework should model it correctly rather than push it to operator-discipline.

### Alternative 8: Add `depends_on` field to the Migration Protocol

Each migration declares `depends_on: list[Migration]`; the runner builds a DAG + topologically sorts. **Rejected** as over-engineering for one cross-category dep. If future migrations bring more complex dependency shapes, a future ADR adds `depends_on` cleanly. The Week 5 case is solved by the apply-order reorder + the documentation in D27.

### Alternative 9: Doctor's refuse-on-pending hard default in Week 6

Skip the feature flag; flip default to FAIL immediately. **Rejected** per D26 — would break operators in the warn-on-pending window between git-pull and migration-apply. The feature-flag rollout is the canonical soft-rollout pattern.

### Alternative 10: Doctor refuse-on-pending behind a config setting in `~/.outreach-factory/config.yml` rather than an env var

`config.yml:doctor.strict_migrations: true` instead of `OUTREACH_FACTORY_STRICT_MIGRATIONS=1`. **Accepted as the longer-term shape, but deferred** — Week 6 ships the env-var flag because the `config.yml` schema is itself version-controlled by policy migrations (ADR-0012), and adding a new top-level config key would require a config-schema migration. The env var is the simpler week-6 deliverable; Pillar I OSS hardening can promote it to a config setting if operator UX research surfaces the need.

### Alternative 11: Replay test runs against the OPERATOR'S real vault (not a synthetic)

Operators invoke the replay test with `--vault-path <real_vault>`. **Rejected** because:

* The exit criterion explicitly says "fresh synthetic vault" — not "real vault." The point is to exercise the framework against a known, deterministic, version-controlled before-state.
* Real vaults differ wildly across operators; a test that passes against Yang's vault may fail against another operator's (different Person-note shapes, different policy customization). The replay test must be deterministic to gate Pillar B's "stable" claim.
* Real-vault testing is what `python backfill_identity.py --apply` already does — the scripted, operator-facing path. The migration framework's replay test is a SEPARATE concern: "does the framework + the wrappers compose correctly?"

### Alternative 12: `_recovered_by: "migration_0002_backfill_send_history"` on ledger/0002's emitted events

Follow the ADR-0010 D15 + `ledger/0001` precedent and tag synthetic events with `_recovered_by: f"migration_{MIGRATION_ID}"` (literal `"migration_0002_backfill_send_history"`) instead of the Phase 5.5 script literal `"backfill"`. **Rejected** because:

* **The wrap is a literal replay of the Phase 5.5 script.** Events emitted by the standalone `orchestrator/backfill_ledger.py` (Phase 5.5 — operators like Yang already ran it against their real state) carry `_recovered_by: "backfill"`. If the wrapped migration emitted a different tag, an operator's ledger would have TWO distinct value classes for semantically-identical synthetic events — split across the script-era and migration-era event sets — for no analytical benefit.
* **Downstream readers that filter on `_recovered_by` benefit from a single value class.** `python orchestrator/ledger.py tail --type send_intent | grep '"_recovered_by": "backfill"'` finds Phase-5.5-shape retroactive events regardless of which subsystem emitted them.
* **The `migration_event` audit-trail event already provides the migration_id link.** An operator who needs to know "did the migration emit this specific event, or did the script?" cross-references the chronologically-adjacent `migration_event` (whose `migration_id: "0002_backfill_send_history"` identifies the apply); the synthetic events' chronological ts + the migration_event's ts together provide the temporal correlation.

**Counter-argument:** an operator running `ledger.py tail --type send_intent` sees `_recovered_by: "backfill"` and cannot infer at a glance which subsystem emitted it. **Accept** — the diagnostic value (knowing-which-subsystem) is lower than the analytical value (one tag for the Phase-5.5-shape semantic class). Pillar G observability dashboards that need to disambiguate cross-reference `migration_event.migration_id` per the existing audit-trail contract (ADR-0010 D17).

**Consequence:** `orchestrator/ledger.py` line 39's catalog entry is updated to note that `"backfill"` can come from either source. The Week 5 follow-up commit (per the per-week review pattern; see `.planning/REVIEW-pillar-b-week-5.md` P2-3) landed both the catalog clarification + this alternative.

## Consequences

### Positive

- **The Pillar B exit criterion has a verification vehicle.** `tests/test_migrations_replay.py::TestExitCriterionProperty::test_clean_replay_against_fresh_synthetic` is the binding test; it constructs a fresh synthetic before-state + runs `apply()` + verifies every SoT invariant. The exit criterion's property is now a tested contract.
- **The wrapped backfills give Phase 5.5's logic a second life through the framework.** A new operator doing OSS bring-up applies vault/0002 + ledger/0002 via the runner — no need to know about the standalone `backfill_identity.py` + `backfill_ledger.py` scripts. The scripts remain for operator-CLI use; the migrations are the framework-mediated path.
- **The cross-category apply order is now load-bearing + documented.** D27 names the dependency + the reorder rationale; future migrations follow the same convention (vault is the substrate; ledger picks up; policy is orthogonal).
- **The synthetic fixture is a regression baseline.** Reviewers can inspect `tests/fixtures/synthetic_pillar_b/` directly; future migrations extend it incrementally; the replay test scales with the framework.
- **Doctor's refuse-on-pending feature flag (Week 6) closes the exit-criterion text** without surprising existing operators. Pillar I's eventual default-flip is incremental.
- **The dry-run cross-category limitation is documented + tested.** D24-N pins both behaviors (faithful dry-run for non-dep migrations; documented zero-affected for ledger/0002). Future work has a clear home.

### Negative

- **The wrapped backfills duplicate ~200 LOC per migration with the standalone scripts.** A bug in the standalone script does not automatically propagate to the migration; future divergence requires discipline. **Mitigation:** the duplicated logic is small + well-tested; the per-migration test files (`test_migrations_vault_0002.py` + `test_migrations_ledger_0002.py`) pin every contract; the standalone scripts are essentially Phase 5.5 frozen artifacts unlikely to evolve.
- **The default apply-order reorder is a behavior change.** Operators with scripts that pinned the old order (`apply(MigrationCategory.LEDGER)` first then `apply(MigrationCategory.VAULT)`) see no functional difference (per-category applies are unchanged); only `apply()` with no args walks the new order. **Mitigation:** no production operator script exists yet (Week 5 is pre-OSS); the change is recorded in this ADR + the existing test `TestPending.test_pending_orders_by_default_apply_order` pins the new contract.
- **The synthetic fixture covers a narrow shape.** Three Person notes, one touch, one orphan, one policy file. Real operator vaults have hundreds of Person notes + dozens of touch notes + multiple policy files. **Mitigation:** D24's programmatic builder allows future stress tests to layer volume on top of the static baseline without churning the fixture; Pillar I OSS hardening's bring-up testing exercises real-operator scale.
- **Cross-category dry-run cannot accurately preview chained outcomes.** D24-N documents this; the test suite pins the documented behavior. **Mitigation:** the workaround is per-category apply (run vault first; then dry-run ledger; then apply ledger). Future work (Pillar I) may add a sequenced-preview mode.
- **The doctor feature flag is a separate UX surface to maintain through Pillar I.** Adding the flag in Week 6 commits to operator-visible behavior that Pillar I removes. **Mitigation:** the flag is a tested escape hatch; the test suite pins both behaviors (warn default; FAIL when flag set); Pillar I removes the flag in one line + a test update.

### Neutral / observability

- The wrapped backfills' `migration_event` audit-trail emissions (per ADR-0010 D17) carry diagnostic fields (`enrolled_emitted`, `sends_emitted`, `orphans_emitted`, `persons_without_id`, `touches_without_person_match`) that future Pillar G dashboards consume for "did the backfill complete cleanly?" reports.
- The synthetic-replay test is fast (<500ms for the full 5-migration apply); future Pillar I bring-up's CI can run it as a smoke test on every commit.
- `IdentityBackfillConflictError` is a public exception subclass of `FrontmatterError`; CLI / TUI / automation tools catch it by class.

## Compliance with invariants

- **I1 (single source of truth):** Vault Person frontmatter is the SoT for `id:` + `identity_keys:` (per `docs/SOURCES-OF-TRUTH.md`). vault/0002 stamps these from the existing legacy fields (`linkedin:`, `email:`, etc.); ledger/0002 reads them via `_walk_person_records`. Neither migration introduces a new SoT. The synthetic fixture's after-state preserves every existing SoT invariant.
- **I2 (two-phase commit):** ledger/0002's send-pair backfill emits `send_intent` + `send_confirmed` as a pair per touch note with `sent: true`. The pair shape is the canonical two-phase commit; the migration retroactively reconstructs it. Every backfilled `send_intent` has a matching outcome (the paired `send_confirmed`); every backfilled `send_confirmed_orphan` corresponds to a Person whose `last_touch:` had no touch note (operator-flagged for review). The replay test's `TestExitCriterionProperty.test_clean_replay_against_fresh_synthetic` asserts the I2 invariant holds after apply (every `send_intent` has a matching outcome).
- **I3 (schema versioning):** vault/0001 stamps `schema_version: 1` on Person notes; vault/0002 stamps `identity_version: 1`; policy/0001 bumps the policy `version:` 1 → 2. The synthetic fixture's after-state has every artifact at the expected version.
- **I4 (reproducible state):** The synthetic fixture IS a reproducible state — version-controlled before-state + deterministic migration sequence = deterministic after-state. Every test invocation produces byte-identical Person notes + canonical-order events + the same policy YAML.
- **I5 (observable by default):** Every migration logs at INFO with `affected_count`. The wrapped backfill emits a `migration_event` audit-trail event (ADR-0010 D17) carrying diagnostic fields. Pillar G consumes the structured events directly.
- **I6 (tests prove invariants):** 56 new tests across `test_migrations_vault_0002.py` (18) + `test_migrations_ledger_0002.py` (18) + `test_migrations_replay.py` (20). The exit-criterion test `TestExitCriterionProperty.test_clean_replay_against_fresh_synthetic` is the single test that pins the entire Pillar B exit criterion. The atomicity contract is verified across categories (`test_apply_is_atomic_against_per_migration_failures`).
- **I7 (cost is a first-class concern):** The wrapped backfills do not emit `cost_incurred` events — they are local IO with no external API calls. The `migration_event` audit trail carries no timing fields in Week 5 (consistent with ADR-0010 D17); Pillar G adds them via a future ADR amendment if needed.
- **I8 (decisions documented):** This ADR. ADR-0009 §References gains an entry in the "Shipped since this ADR landed" subsection for ADR-0013. `docs/adr/README.md` gets a new row. The cross-pillar impact section (above) names every future-pillar consumer.

Does not weaken any invariant. I2's enforcement is strengthened — every send_intent in the synthetic ledger has a matching outcome after `apply()`.

## Migration / rollout

The Week 5 deliverable is foundations (the wrapped backfills + the synthetic fixture + the replay test). Week 6 closes the exit gate (the doctor feature flag + this ADR's finalization).

**For new operators (OSS bring-up, post-Week-6):**

1. `git clone` + `pip install` + `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             5 pending: vault/0001_*, vault/0002_*, ledger/0001_*, ledger/0002_*, policy/0001_*
   ```

2. Operator runs the dry-run preview:
   ```python
   from orchestrator.migrations import MigrationRunner
   runner = MigrationRunner(vault_dir=Path("~/your-vault").expanduser())
   preview = runner.dry_run()
   # Prints all 5 previews. Note: ledger/0002 preview shows 0 affected
   # due to the documented cross-category dry-run limitation (D24-N).
   ```

3. Operator applies:
   ```python
   runner.apply()
   # Walks VAULT → LEDGER → POLICY per D27.
   # vault/0001 stamps schema_version: 1 on every Person.
   # vault/0002 stamps id + identity_keys + identity_version: 1.
   # ledger/0001 closes any orphan send_intent.
   # ledger/0002 backfills retroactive enrolled / send / orphan events.
   # policy/0001 inserts engine_compat + bumps version 1 → 2.
   ```

4. `python scripts/doctor.py` → no pending; OK.

**For existing operators (Yang) with Phase 5.5 backfills already applied:**

One-time seed instruction surfaced in the Week 6 commit's release notes. The state file is updated to mark `vault/0002_backfill_identity_lineage` + `ledger/0002_backfill_send_history` as already applied, so the runner skips them. The seed itself is operator-driven (not automatic) so it has the same "operator-deliberate" property as `manual_override` events:

```python
from datetime import datetime, timezone
from orchestrator.migrations.state import (
    MigrationState, mark_applied, save_state_atomic, load_state, DEFAULT_STATE_DIR,
)
from orchestrator.migrations.types import MigrationCategory

state = load_state(DEFAULT_STATE_DIR)
now = datetime.now(timezone.utc)
mark_applied(
    state, MigrationCategory.VAULT, "0002_backfill_identity_lineage",
    now=now, runner_version="0.1.0",
)
mark_applied(
    state, MigrationCategory.LEDGER, "0002_backfill_send_history",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

**Feature flag rollout (Week 6):**

```bash
# Strict mode — doctor refuses if any migration is pending.
OUTREACH_FACTORY_STRICT_MIGRATIONS=1 python scripts/doctor.py
# exit code 1 if any pending

# Default mode (no env var) — doctor warns but exit code 0.
python scripts/doctor.py
```

A future Pillar I commit removes the env-var conditional and makes refuse-on-pending the default. Operators with `OUTREACH_FACTORY_STRICT_MIGRATIONS=1` set in their environment see no behavior change at that point.

A CLI (`python -m orchestrator.migrations apply` / `--dry-run` / `--rollback`) is deferred to Pillar I OSS bring-up. Until then operators invoke via Python REPL.

## Week 6 — exit gate closed

Shipped 2026-05-21. Closes Pillar B; flips PILLAR-PLAN §6 Pillar B row from "In progress" to "Stable."

### What landed

1. **Doctor strict-mode feature flag** (`scripts/doctor.py:check_migrations`). Reads `os.environ.get("OUTREACH_FACTORY_STRICT_MIGRATIONS")` at call time (not import time, so the test harness's `monkeypatch.setenv` lands). Exact-match `"1"` promotes pending-migrations from WARN to FAIL (exit code 1). The message gains a `STRICT mode:` prefix when the flag took effect so operators can confirm via the doctor output without grepping their shell environment. The hint surfaces the env var name so the disable path is discoverable from a strict-mode FAIL line.

2. **Runner-level rollback-refusal pins for the wrapped backfills.** `tests/test_migrations_runner.py::TestRealMigrationRollbackRefusal` pins that `runner.rollback(VAULT, "0002_backfill_identity_lineage", allow_rollback=True)` and `runner.rollback(LEDGER, "0002_backfill_send_history", allow_rollback=True)` raise `MigrationNotReversibleError`. The generic refusal was already tested via `RecordingMigration`; these tests pin the specific irreversibility-by-design contracts of the migrations Pillar B's exit criterion depends on. A future refactor that flipped either `is_reversible` flag to `True` would be caught at the runner integration layer.

3. **Degenerate-order pin.** `tests/test_migrations_replay.py::TestExitCriterionProperty::test_degenerate_order_when_ledger_runs_before_vault` explicitly calls `runner.apply(MigrationCategory.LEDGER)` BEFORE `runner.apply(MigrationCategory.VAULT)` (bypassing `_DEFAULT_APPLY_ORDER`) and asserts the degenerate after-state: zero enrolled / send-pair / orphan emissions; `persons_without_id: 3` in the ledger/0002 migration_event; and the framework's applies-once contract STRENGTHENS the degeneration (ledger/0002 is marked applied "successfully" with zero affected, so a subsequent VAULT apply does not re-fire it). Closes Week 5 review §Testing coverage gap #5.

4. **Doctor preflight test fixture** (`_isolate_strict_env` autouse). Existing doctor tests now run with `monkeypatch.delenv(OUTREACH_FACTORY_STRICT_MIGRATIONS)` so operator environments that may have the var set don't leak into the test suite. Strict-mode tests set the var themselves after the fixture clears it.

### Week 6 design decisions

The handoff named D28–D32; the four that locked are recorded here.

**D28. Doctor refuse-on-pending — env var or CLI flag?** Env var (`OUTREACH_FACTORY_STRICT_MIGRATIONS=1`) — the soft-rollout deliverable. Set once at deploy time, applies to every `doctor.py` invocation in the same process tree; unambiguous in CI / systemd / container environments. A CLI flag would have to be remembered per-invocation. Pillar I OSS bring-up's CLI work surfaces the strict-mode posture explicitly (alongside `python -m orchestrator.migrations` CLI surface generally).

**D29. The flag's truthy interpretation — exact-match `"1"`, not truthy-string.** `OUTREACH_FACTORY_STRICT_MIGRATIONS=1` → strict; any other value (including `"true"`, `"yes"`, `"on"`, `"0"`, empty, case variants, whitespace-padded) → not strict. Reasons: (a) simpler contract; (b) operators learn one value; (c) matches the convention `OUTREACH_FACTORY_LIVE_TESTS=1` (PILLAR-PLAN §3 I6) sets up. Counter-argument: operators used to truthy-string conventions might set `=true` and silently get not-strict. Mitigation: the doctor's WARN output explicitly contains the env var name + the strict-mode hint, so an operator who set `=true` and sees WARN can see what they should have set instead. The strict-mode tests parametrize across `["true", "yes", "on", "0", "", "TRUE", "1 ", " 1"]` to pin the contract.

**D30. Doctor exit code when strict + pending — `1` (same as any other FAIL).** Not a granular distinction. The strict-mode failure is operationally equivalent to "doctor refused this launch"; calling code (CI, systemd, deploy scripts) checks `$? == 0`; the granular distinction "doctor failed due to migrations" vs "doctor failed due to some other check" is a parsing-the-output concern, not an exit-code concern. Auto-apply ops automation is a Pillar I concern; until then, FAIL is FAIL.

**D31. Holistic review at pillar exit — run it, even though per-week reviews caught zero P1s.** Per the Pillar A retrospective the habit pays for itself in cross-week architectural drift (Pillar A's holistic review caught 4 P1s the per-week reviews missed). Pillar B is a substrate Pillars C / D / E / F / G all depend on; cross-week drift compounds across future pillars. The 10-minute spawn cost is high-asymmetric-benefit. The reviewer's report lives at `.planning/REVIEW-pillar-b-holistic.md`.

**D32. Existing-operator state seed — REPL incantation in this ADR; no separate utility shipped Week 6.** ADR-0013 §Migration / rollout already documents the seed REPL block; the holistic review surfaced no operator-UX concrete problem that would justify shipping `scripts/seed_pillar_b_state.py` ahead of Pillar I's broader CLI. Pillar I OSS bring-up's CLI absorbs the seed.

### What did NOT change in Week 6

* **No new migration.** Pillar B's five concrete migrations (vault/0001 + vault/0002 + ledger/0001 + ledger/0002 + policy/0001) are the complete Pillar B body. Future migrations land in Pillars C / D / E / F / G.
* **No framework primitives changed.** `MigrationRunner`, the state file shape, the `Migration` Protocol, the atomicity contract, the apply-order constant — all unchanged from Week 5.
* **No CLI shipped.** `python -m orchestrator.migrations` deferred to Pillar I (operators invoke via Python REPL).
* **No flag-default flip.** Default stays WARN; opt-in only. Pillar I (Weeks 43–48) flips default and removes the flag.

## References

- ADR-0001 (policy engine architecture) — the engine surface this work coordinates with.
- ADR-0004 (suppression rules + GDPR forget) — the tmp-then-rename atomicity precedent; the `is_reversible=False` precedent.
- ADR-0009 (migration framework foundation) — D1–D7 + the per-category-ADR-per-dispatcher convention this ADR fulfills (Week 5–6 closes the convention).
- ADR-0010 (ledger migrations) — D14–D17 + the `migration_event` emission contract that ledger/0002 inherits + the append-only constraint that motivates `is_reversible=False`.
- ADR-0011 (vault migrations) — D8–D13 + the surgical-edit + per-file atomicity precedents that vault/0002 inherits.
- ADR-0012 (policy migrations) — D18–D22 + the engine-version-range-acceptance contract that the replay vehicle exercises end-to-end.
- `docs/PILLAR-PLAN.md` §2 Pillar B — exit criterion (binding text).
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies `is_reversible=False` + the conflict-refuse-loud posture in vault/0002).
- `docs/SOURCES-OF-TRUTH.md` — Person identity row (vault frontmatter is SoT for id + identity_keys); Send-history row (ledger is SoT for "did we send").
- `orchestrator/migrations/runner.py` — `_DEFAULT_APPLY_ORDER` constant + the documented reordering rationale.
- `orchestrator/migrations/vault/migration_0002.py` — `BackfillIdentityLineage` + `IdentityBackfillConflictError` + module-level singleton `MIGRATION`.
- `orchestrator/migrations/ledger/migration_0002.py` — `BackfillSendHistory` + module-level singleton.
- `orchestrator/backfill_identity.py` — the standalone Phase 5.5 Week 1b backfill the migration wraps in spirit. Logic was inlined per Alternative 3 above.
- `orchestrator/backfill_ledger.py` — the standalone Phase 5.5 Week 2 backfill the migration wraps in spirit. Same logic-inlining rationale.
- `tests/fixtures/synthetic_pillar_b/` — the static synthetic before-state fixture.
- `tests/conftest.py::synthetic_state_dir` — the programmatic builder fixture.
- `tests/test_migrations_vault_0002.py` — direct unit tests for the wrapped vault backfill.
- `tests/test_migrations_ledger_0002.py` — direct unit tests for the wrapped ledger backfill.
- `tests/test_migrations_replay.py` — the end-to-end synthetic-replay verification vehicle. Houses `TestExitCriterionProperty.test_clean_replay_against_fresh_synthetic` — the Pillar B exit-criterion test.
- `tests/test_migrations_runner.py::TestPending::test_pending_orders_by_default_apply_order` — pins the new apply-order contract.
- `tests/test_migrations_runner.py::TestDefaultRegistries` — pins the 5-pending + VAULT-first expectation.
- `tests/test_doctor_preflight_migrations.py::TestCheckMigrationsUnit::test_ok_when_no_pending_migrations` — seeds all five migrations applied.
- Shipped since this ADR landed (Week 6 — 2026-05-21):
  - **Doctor strict-mode feature flag** (`OUTREACH_FACTORY_STRICT_MIGRATIONS=1`) — `scripts/doctor.py:check_migrations` exact-match `"1"` (per D29) promotes pending-migrations from WARN to FAIL (per D26 + D30). 11 new tests in `tests/test_doctor_preflight_migrations.py::TestStrictMode`.
  - **Runner-level rollback-refusal pins for the wrapped backfills** — `tests/test_migrations_runner.py::TestRealMigrationRollbackRefusal` (2 tests). Closes Week 5 review §Testing coverage gap #4.
  - **Degenerate-order pin** — `tests/test_migrations_replay.py::TestExitCriterionProperty::test_degenerate_order_when_ledger_runs_before_vault`. Closes Week 5 review §Testing coverage gap #5.
- Forward-references (planned):
  - **Pillar I OSS bring-up** (Weeks 43–48): flip refuse-on-pending default; remove the feature flag; ship the operator CLI; document the existing-operator state-seed instruction.
  - **Pillar C / D / E / F future migrations** extend the static fixture + the replay test per the §Downstream pillar impact section above.
