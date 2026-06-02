# ADR-0042: Pillar F Week 5 — voice-thresholds CLI extension

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** F (Voice corpus + draft quality — Week 5 voice-thresholds CLI)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar F Week 1 (ADR-0038 D178-D184) shipped the foundation. Pillar F Week 2 (ADR-0039 D185-D191) shipped the shared embedding-retrieval primitive. Pillar F Week 3 (ADR-0040 D192-D198) shipped the five per-register thin adapters in a single commit. Pillar F Week 4 (ADR-0041 D199-D205) shipped the per-register voice-fidelity threshold infrastructure — the loader `load_voice_thresholds` + helper `get_voice_threshold_for_register` + module-level constants `DEFAULT_VOICE_THRESHOLDS_PATH` + `DEFAULT_VOICE_THRESHOLD_PER_REGISTER` + the default-shipped template at `config-template/voice_thresholds.example.yml`. The Week 4 commit + follow-up shipped at c8ec6d2 + ff6ec22 with 0 P1 + 1 P2 + 4 P3s addressed; 2863 tests passing post-follow-up.

Pillar F Week 5 ships **the operator-facing CLI extension for the threshold loader** per ADR-0041 §Downstream pillar impact (Pillar I forward-reference) + the per-week author's call per `.planning/HANDOFF-pillar-f-week-4.md` §"Recommended Week 5 scope" (Option 4). The Week 4 infrastructure is library-only at this point — operators who want to inspect per-register thresholds without writing custom Python scripts need a CLI surface. Week 5 lands that surface as three nested subcommands under `python orchestrator/voice_corpus.py thresholds {list,get,dump}`.

Sequencing rationale: shipping the CLI at Week 5 (before the Week 6+ hallucination-detection primitive starts consuming per-register thresholds at draft-time) gives operators time to internalize the per-register threshold concept BEFORE downstream gates surface threshold-driven refusals. The CLI is content-additive against the Week 4 loader — no new event classes, no new migrations, no library-surface mutation.

The six concerns this ADR resolves:

1. **The CLI subcommand shape must be pinned at Week 5** so future Pillar I CLI extensions (per-tenant per-register inspection; multi-tenant config discovery) build against a stable convention. The Pillar E precedent at `tier_assignment.py suggest` (ADR-0035 D162 + CLI surface) + `discovery_dedup.py check` (ADR-0033 D149) + `email_verification_cache.py lookup` (ADR-0034 D154) + Week 2's `voice_corpus.py retrieve` (ADR-0039 D188 + D191) is the structural reference. **D206** pins.

2. **The JSON output schema must be pinned at Week 5** so operators scripting against the CLI (per-tenant audit tooling at Pillar I; per-register dashboard renderers at Pillar G; per-run threshold drift detectors) get a stable schema with provenance metadata. **D207** pins.

3. **The `dump` subcommand's default output format must be pinned at Week 5** as literal YAML re-emit so operators can pipe directly to their config (`thresholds dump > ~/.outreach-factory/voice_thresholds.yml`). The `_meta` provenance field is OMITTED from `dump` output (operators piping to file would otherwise pollute the loader's strict-gate). **D208** pins.

4. **The decision NOT to ship a `thresholds set <register> <value>` mutate subcommand at Week 5 must be pinned** so future contributors don't routinely add it without an operator-deliberate ADR amendment. The YAML is already operator-editable via standard editors; mutate would need atomic-write + idempotence + per-register validation re-runs that compound surface for marginal benefit. **D209** pins.

5. **The verb choice (`get` not `show`) + the closed-enum register validation at argparse-choices level must be pinned at Week 5.** `get` matches `git config --get` shell intuition + Pillar I doctor conventions; argparse-choices enforces the closed enum per ADR-0038 D178 BEFORE the loader's "missing required register key" diagnostic would surface (the loader's error would name ALL missing keys; the CLI's argparse error names the specific unknown register the operator typed — better operator-readable diagnostic). **D210** pins.

6. **The TEST-ONLY `embed_fn` seam preservation must be reaffirmed at Week 5** per the Week 2 audit's P3-B carry-forward + the Week 3 ADR-0040 D197 reaffirmation + the Week 4 ADR-0041 D205 N/A status. The CLI is read-only against YAML; no encoder runs; the carry-forward continues to Week 6+ hallucination-detection + Week 8+ fidelity-scoring (which WILL encode). **D211** pins.

Risks this ADR mitigates by design: **R024 (voice-corpus drift)** continues mitigated — the CLI's `list` + `get` + `dump` surface per-register thresholds with explicit provenance, so operators auditing per-tenant configs detect drift via the `_meta.source_path` + `_meta.is_fallback` fields. **R025 (embedding-cost runaway)** continues mitigated — the CLI is read-only against YAML; zero encoder calls. **R026 (operator-corpus split)** continues mitigated — the CLI is orthogonal to the corpus directory; it reads the threshold YAML at a separate path.

No new risks surface in this Week 5 commit. The Week 1-pinned R023-R026 cover the Pillar F design surface; Week 5's CLI extension is content-additive against those mitigations.

## Decision

### D206. CLI subcommand shape — nested subparsers under `thresholds`

The CLI extends `orchestrator/voice_corpus.py` with a fourth top-level subcommand `thresholds` carrying three nested actions:

```
python orchestrator/voice_corpus.py thresholds list [--json] [--thresholds-path PATH]
python orchestrator/voice_corpus.py thresholds get <register> [--json] [--thresholds-path PATH]
python orchestrator/voice_corpus.py thresholds dump [--json] [--thresholds-path PATH]
```

`list` emits the per-register threshold table + provenance metadata; `get` emits a single-register lookup; `dump` emits the literal YAML re-emit (operators pipe to file). The pre-existing `retrieve` / `validate` / `rebuild` subcommands are UNCHANGED — Week 5's extension is content-additive at the argparse layer.

`--thresholds-path` mirrors the library kwarg name (`load_voice_thresholds(thresholds_path=...)`); precedence: explicit `--thresholds-path` > `cfg.voice.thresholds_path` > `DEFAULT_VOICE_THRESHOLDS_PATH` (matches the library loader's precedence per ADR-0041 D199).

**Why nested subparsers under `thresholds` (rejected: three flat top-level subcommands `thresholds-list` / `thresholds-get` / `thresholds-dump`; rejected: single `thresholds` subcommand with `--action` arg; rejected: a separate per-action `voice_corpus.py threshold_list.py` script file).**

* **Nested subparsers** group the three actions under one operator-readable namespace. The `--help` output surfaces `thresholds` as one row + drills into the three actions via `thresholds --help`. This matches the framework convention of one subcommand per operation: `git remote add` / `git remote rm` / `git remote list` vs `git-remote-add` / `git-remote-rm` / `git-remote-list`.
* **Three flat top-level subcommands** is rejected because the help output gets cluttered (`retrieve` / `validate` / `rebuild` / `thresholds-list` / `thresholds-get` / `thresholds-dump` = 6 row at the top level; ill-grouped). The per-week reviewer + the operator-reader both prefer the grouped shape.
* **Single `thresholds` subcommand with `--action {list,get,dump}` arg** is rejected because the `get` action takes a positional register argument that doesn't apply to `list` or `dump` — flat-arg dispatch would require `--register` always-optional + runtime "required when action=get" checks, losing argparse's static enforcement.
* **Per-action script file** is rejected because the per-script discovery surface (operators learn the framework via `ls orchestrator/` + per-file `--help`) is operator-hostile compared to nested subparsers; the per-primitive flat-module convention per ADR-0036 D166 puts CLI commands at the existing module's subparser tree.

### D207. JSON output schema — `_meta.source_path` + `_meta.is_fallback` provenance

Per-action JSON schemas:

* **`thresholds list --json`** emits:
  ```json
  {
    "thresholds": {"cold-pitch": 0.70, "congrats": 0.65, ...},
    "_meta": {"source_path": "/abs/path/voice_thresholds.yml", "is_fallback": false}
  }
  ```
* **`thresholds get <register> --json`** emits:
  ```json
  {
    "register": "cold-pitch",
    "threshold": 0.70,
    "_meta": {"source_path": "/abs/path/voice_thresholds.yml", "is_fallback": false}
  }
  ```
* **`thresholds dump --json`** emits (no `_meta` per D208):
  ```json
  {"thresholds": {"cold-pitch": 0.70, ...}}
  ```

The `_meta.source_path` field is the absolute path to the YAML file the loader actually read (after any fallback rebind to the default template). The `_meta.is_fallback` boolean is `true` when the operator's path was absent + the loader fell back to `config-template/voice_thresholds.example.yml` per ADR-0041 D199 (matches the loader's stderr warning posture). Operators scripting against the CLI (per-tenant audit tooling; per-run threshold drift detectors; Pillar G dashboard renderers) get a stable shape with provenance.

**Why include provenance metadata in `list` + `get` but NOT `dump` (rejected: include `_meta` in `dump` too; rejected: omit `_meta` from all three actions; rejected: surface `_meta` only when `--verbose`).**

* **Provenance in `list` + `get`** serves the operator-inspection workflow: "what threshold am I going to use for cold-pitch?" needs the per-register value + the source of that value. Operators with multiple tenant configs see per-tenant `_meta.source_path` divergence in the CLI output.
* **No `_meta` in `dump`** preserves round-trip compatibility — operators `thresholds dump > ~/.outreach-factory/voice_thresholds.yml` to bootstrap their config from the default template; a `_meta` top-level key would be rejected by the loader's strict gate per ADR-0041 D202 (the loader's `unknown_keys = set(thresholds.keys()) - REGISTERS` check would flag `_meta` as an unknown key, but only at one nesting level — the loader checks `loaded["thresholds"]` keys, NOT top-level keys; a `_meta:` top-level key would parse cleanly but pollute the operator's config file).
* **Omit `_meta` everywhere** is rejected because `list` + `get` are operator-inspection paths; provenance is the load-bearing signal.
* **Surface `_meta` only when `--verbose`** is rejected because the operator-typical inspection use case is the per-call default; adding a `--verbose` flag is operator-friction for the typical case.

### D208. `dump` default output format — literal YAML re-emit

The `dump` action's default output is literal YAML (no flags needed):

```yaml
thresholds:
  cold-pitch: 0.70
  congrats: 0.65
  re-engagement: 0.72
  reply: 0.70
  public-comment: 0.60
```

The output preserves the SKILL.md register table's canonical order (cold-pitch → congrats → re-engagement → reply → public-comment per ADR-0040 D193) via `yaml.safe_dump(..., sort_keys=False)` + explicit dict-construction in the canonical order. The default-shipped template at `config-template/voice_thresholds.example.yml` carries this same order; operators bootstrapping a fresh config via `thresholds dump > voice_thresholds.yml` get the canonical SKILL.md order.

The `--json` flag opts into JSON output for scripting; the JSON form mirrors the YAML form's no-`_meta` posture per D207's rationale.

**Why YAML default + JSON optional (rejected: JSON default with `--yaml` flag; rejected: emit both YAML + JSON in separate stdout streams; rejected: format inferred from output redirection target).**

* **YAML default** matches the operator's expected use case — "dump my thresholds so I can edit them" implies a YAML file output. Operators in a one-shot `thresholds dump > voice_thresholds.yml` workflow get the right format by default; the `--json` flag is for the scripting-against-the-CLI case.
* **JSON default** is rejected because the typical operator use is bootstrap-the-config-from-template; a JSON output would require post-processing (operators run `yq` or `json2yaml`) before piping to the YAML config.
* **Emit both** is rejected because `stdout` is one stream; the operator can't disambiguate two formats in one stream.
* **Format inferred from redirection target** is rejected because argparse doesn't see the shell redirection (operators piping to `>` or `|` don't change argparse's view); inference would require runtime introspection of `sys.stdout.isatty()` which couples the format choice to terminal state.

### D209. NO `thresholds set <register> <value>` mutate subcommand at Week 5

Week 5 ships READ-only against the YAML. The mutate path (`thresholds set <register> <value>` that atomically writes the operator's YAML with a new per-register value) is operator-deferred to Pillar I per ADR-0038 §Downstream pillar impact's Pillar I forward-reference + ADR-0041 §Downstream pillar impact (Pillar I CLI extensions).

The deferral reasons:

* **The YAML is already operator-editable via standard editors.** Operators wanting to tune `cold-pitch` from 0.70 to 0.75 open `~/.outreach-factory/voice_thresholds.yml` + edit + save. The mutate subcommand would be ergonomic-sugar for the common case but the typical operator already has muscle memory for `vim` + `nano`.
* **The mutate path needs atomic-write + idempotence + per-register validation re-runs.** Mutate-during-process-running would race against the process-cache per ADR-0041 D203 (operator-edited values mid-process aren't picked up until next process start); the mutate subcommand would surface the same gotcha. Atomic-write (write-temp + rename) needs OS-level guarantees; idempotence (running `thresholds set cold-pitch 0.70` twice is a no-op) needs file-mtime checks. Per-register validation (`thresholds set cold-pitch 1.5` should refuse-loud + leave the YAML unchanged) needs partial-write rollback. All operator-deliberate; none free.
* **Pillar I is the structured surface for operator-deliberate CLI extensions.** The Pillar F Week 4 ADR named Pillar I as the home for advanced CLI tooling (per-tenant config discovery, threshold drift detection, multi-tenant overlay); the mutate subcommand naturally lives there.

If operator demand for the mutate subcommand materializes at Pillar F Week 8+ or Pillar I, the ADR amendment lands `D213+` decisions for atomic-write + idempotence + per-register validation re-runs.

**Why defer mutate to Pillar I (rejected: ship `set` at Week 5 with atomic-write + idempotence + validation; rejected: ship `set` as best-effort without atomic-write; rejected: ship `set` as a Python REPL helper rather than a CLI subcommand).**

* **Defer to Pillar I** is the operator-deliberate boundary — Week 5 is "ship the read surface for the Week 4 infrastructure" not "ship the operator-tunable mutate path." The Week 5 scope stays bounded.
* **Ship `set` at Week 5 with full atomic-write + idempotence + validation** is rejected as Week 5 scope creep — ~150-200 LOC for the full implementation + ~20-30 tests; the Week 5 scope per the handoff is ~50-100 LOC + ~10-15 tests for the read CLI.
* **Ship `set` as best-effort without atomic-write** is rejected because the asymmetric-failure-cost (operator running `thresholds set cold-pitch 0.75` mid-process gets a half-written YAML if the process is killed) is operator-hostile. The framework convention is "atomic operations" per ADR-0007's cap-rule writes; mutate would need to match.
* **Ship as a Python REPL helper** is rejected because operators don't run Python REPLs for routine config tuning; the CLI is the structured surface.

### D210. Verb choice (`get` not `show`) + argparse-choices for closed-enum register

The single-register lookup subcommand verb is `get` not `show`. Rationale:

* `get` matches `git config --get` shell intuition + Pillar I doctor conventions (`doctor get <key>` is common in operator-side config-inspection tooling).
* `show` is the alternative (Pillar E's `tier_assignment.py suggest` uses `suggest` not `show`, but `suggest` is a per-Person mutation-action verb that doesn't fit per-register read).

The register positional argument uses argparse's `choices=sorted(REGISTERS)` to enforce the closed enum per ADR-0038 D178 BEFORE the CLI handler runs. Argparse surfaces an `invalid choice: 'introduction' (choose from 'cold-pitch', ...)` error + exit code 2 + names the specific unknown register the operator typed. The loader's "missing required register key" diagnostic would NOT surface (the loader doesn't run when argparse rejects).

**Why `get` + argparse-choices (rejected: `show` verb; rejected: free-text register without argparse-choices; rejected: `--register` flag instead of positional).**

* **`get` verb** matches the operator-side shell convention (`git config --get`; `gh config get`; `docker config inspect <id>` is the read-without-mutation pattern). The verb signals "lookup-without-mutation"; operators reading `thresholds get cold-pitch` understand it's read-only.
* **`show` verb** is rejected because `show` connotes a longer/richer output (`git show <commit>` shows the commit's diff + metadata); for a single-register threshold read, `get` is the lighter-weight verb that matches the per-call output shape.
* **Free-text register without argparse-choices** is rejected because the loader's "missing required register key" diagnostic would surface for unknown registers (the loader gets called with `register=` not in REGISTERS → the helper raises `ValueError: register not in REGISTERS`); the argparse-level rejection is more operator-readable (names the specific unknown register the operator typed at the CLI level, not the helper level).
* **`--register` flag instead of positional** is rejected because the per-call register selection is the operator-deliberate primary argument; positional makes the typical case (`thresholds get cold-pitch`) the shortest form. The optional `--thresholds-path` + `--json` are kwarg modifiers.

### D211. TEST-ONLY `embed_fn` seam preservation — N/A AT CLI SURFACE; VERIFIED

The TEST-ONLY `embed_fn` injection seam preservation (Week 2 audit's P3-B carry-forward; reaffirmed at Week 3 per ADR-0040 D197; verified N/A at Week 4 per ADR-0041 D205) does NOT apply to Week 5's CLI extension. The CLI is read-only against YAML — it parses the threshold config + emits text/JSON/YAML output; there is no encoder; there is no `SentenceTransformer` load to amortize.

Week 5 verification: none of the three `thresholds {list, get, dump}` subcommands surface an `--embed-fn` flag. Verified via `test_thresholds_cli_has_no_embed_fn_flag` in `tests/test_voice_corpus.py::TestCLIThresholds` (inspects each subcommand's `--help` output + asserts `--embed-fn` is absent). The P3-B carry-forward continues to FLAG for the Week 6+ hallucination-detection primitive (which WILL encode the draft + each claim) + the Week 8+ fidelity-scoring primitive (which WILL encode the draft).

The per-week reviewer's checklist row continues at every subsequent Pillar F week that adds new public surfaces: "if the new public surface encodes anything (corpus, draft, claim text), it MUST expose a TEST-ONLY `embed_fn` kwarg labeled in its docstring + MUST NOT surface the kwarg via CLI."

**Why verify-only for Week 5 (rejected: surface `--embed-fn` defensively even though CLI doesn't encode; rejected: redesign the CLI to use embeddings; rejected: skip the verification + lose the carry-forward chain).**

* **Verify-only** is the correct posture per the seam's purpose — the seam exists to amortize per-test `SentenceTransformer` load cost; surfaces that don't encode don't need the seam. The Week 5 CLI is the second consecutive Pillar F week (Week 4 was the first) where the verification surface is N/A; carrying the explicit verification keeps the per-week reviewer's checklist row honest.
* **Surface `--embed-fn` defensively** is rejected because the flag's presence without corresponding behavior is operator-confusing + creates a security surface (arbitrary `--embed-fn module:fn` injection if the flag had teeth) + documentation surface (the `--help` would need to explain "this flag does nothing here, it's here for future-proofing"). YAGNI per the framework convention.
* **Redesign CLI to use embeddings** is rejected because the CLI's job is YAML inspection; embedding-based threshold derivation is Pillar F Week 8+ scope (the fidelity-scoring primitive's per-corpus distribution measurement).
* **Skip the verification** is rejected because the Week 2 P3-B carry-forward is a per-week-reviewer checklist row; explicitly naming the Week 5 status (N/A + verified) closes the row for Week 5 + carries it forward to Weeks 6+ with explicit naming.

## Alternatives considered

### D206-Alt1: Three flat top-level subcommands

Add `thresholds-list` / `thresholds-get` / `thresholds-dump` as flat top-level subcommands alongside `retrieve` / `validate` / `rebuild`. **Rejected** per D206 — the top-level `--help` becomes cluttered (six rows; ill-grouped); operators prefer grouped subcommands.

### D206-Alt2: Single `thresholds` subcommand with `--action {list,get,dump}` arg

One `thresholds` subcommand carrying an `--action` arg that dispatches between the three operations. **Rejected** because:

* The `get` action takes a positional register argument that doesn't apply to `list` or `dump`; flat-arg dispatch loses argparse's static enforcement (the per-action required-arg matrix becomes runtime checks).
* Less operator-readable than nested subparsers — `thresholds list` is shorter than `thresholds --action=list` + matches `git remote list` shell intuition.

### D206-Alt3: Per-action script file at `orchestrator/voice_thresholds_inspector.py`

A separate Python script for each action (or for the whole `thresholds` subsurface). **Rejected** because:

* The per-primitive flat-module convention per ADR-0036 D166 puts CLI commands at the existing module's subparser tree; splitting to a separate file fragments the per-primitive surface.
* Operators learning the framework via `ls orchestrator/` + per-file `--help` see fewer files when the CLI commands cluster under one module.

### D207-Alt1: Include `_meta` in `dump` output

The `dump` action's JSON + YAML outputs both carry `_meta.source_path` + `_meta.is_fallback`. **Rejected** because:

* Operators piping `thresholds dump > ~/.outreach-factory/voice_thresholds.yml` get a config file with a `_meta:` top-level key; the file is operator-confusing on read-back ("what is _meta?").
* The YAML loader's strict-gate per ADR-0041 D202 inspects the `thresholds:` sub-dict's keys (rejecting unknown registers); `_meta:` at the TOP level wouldn't trigger the strict-gate but would still pollute the operator's config-as-source-of-truth.
* Round-trip compatibility is the load-bearing property of `dump` — bootstrapping a fresh config via `thresholds dump > voice_thresholds.yml` must produce a file the loader accepts unchanged.

### D207-Alt2: Omit `_meta` from all three actions

`list` + `get` + `dump` all output WITHOUT `_meta`. **Rejected** because:

* Operators inspecting per-tenant configs lose the per-call provenance (which YAML did the loader actually read?).
* The `is_fallback` signal is load-bearing — operators inspecting an environment where the operator-tuned YAML doesn't exist (fresh install; per-tenant deployment without the per-tenant tune) see the fallback explicitly via JSON `_meta.is_fallback=true` rather than having to inspect stderr for the warning string.

### D207-Alt3: Surface `_meta` only when `--verbose` is passed

`list --verbose --json` + `get --verbose --json` include `_meta`; default omits it. **Rejected** because:

* The operator-typical inspection workflow (one-shot run to see "what's my threshold for cold-pitch?") is the default path; adding `--verbose` for the provenance is friction.
* Operator-side audit tooling (running `thresholds list --json` per-tenant in a Pillar I sweep) would need to remember the `--verbose` flag; the schema becomes context-dependent.

### D208-Alt1: JSON default with `--yaml` flag

`thresholds dump` emits JSON by default; `--yaml` opts into YAML. **Rejected** because:

* The typical operator workflow is "bootstrap-the-config-from-template" which needs YAML; the default should match the typical use.
* JSON default forces operators in the typical workflow to remember the `--yaml` flag.

### D208-Alt2: Emit both YAML + JSON in separate stdout streams

The `dump` action emits YAML to stdout + JSON to stderr (or vice versa). **Rejected** because:

* Pipe-to-file workflows (`thresholds dump > voice_thresholds.yml`) would still need the operator to disambiguate which stream is which.
* Stderr is for diagnostics (the loader's fallback warning per ADR-0035 D164); mixing structured output with diagnostics violates the per-stream convention.

### D208-Alt3: Format inferred from output redirection target

If `sys.stdout.isatty()` is `false` (operator is piping to a file), emit YAML; if `true` (operator is in a terminal), emit JSON for readability. **Rejected** because:

* The inference is operator-confusing — same command, different output depending on terminal state.
* Tab-completion + scripting tooling (the operator scripts `thresholds dump | yq '.thresholds.cold-pitch'`) gets the wrong format depending on whether the script ran in a TTY context.

### D209-Alt1: Ship `set <register> <value>` at Week 5 with full atomic-write + idempotence + validation

Land `set` as a fourth action with all the operator-deliberate guarantees (atomic temp-write + rename; idempotence check via file-mtime; per-register validation re-runs that leave the YAML unchanged on validation failure). **Rejected** because:

* Week 5 scope creep — ~150-200 LOC for full implementation + ~20-30 tests; the Week 5 scope per the handoff is ~50-100 LOC + ~10-15 tests for the read CLI.
* The atomic-write + idempotence + validation re-run trio is operator-deliberate; an ADR amendment landing the mutate path with full semantics is the appropriate vehicle, not a Week 5 sub-feature.

### D209-Alt2: Ship `set` as best-effort without atomic-write

The mutate subcommand writes the YAML in-place without temp-file + rename. **Rejected** because:

* The asymmetric-failure-cost (operator running `thresholds set cold-pitch 0.75` gets a half-written YAML if the process is killed mid-write) is operator-hostile.
* The framework convention is "atomic operations" per ADR-0007's cap-rule writes; the mutate path would need to match.

### D209-Alt3: Ship `set` as a Python REPL helper rather than a CLI subcommand

Provide a `voice_corpus.set_threshold(register, value)` function importable from Python; operators tune via `python -c "..."`. **Rejected** because:

* Operators don't run Python REPLs for routine config tuning.
* The CLI is the structured surface; an importable function doesn't surface in `--help`.

### D210-Alt1: `show` verb instead of `get`

`thresholds show <register>` instead of `thresholds get <register>`. **Rejected** per D210 — `show` connotes longer/richer output (`git show <commit>`); for a single-register threshold read, `get` is the lighter verb that matches the per-call output.

### D210-Alt2: Free-text register positional without argparse-choices

The register positional accepts any string; the loader's helper validates after the fact. **Rejected** because:

* The argparse-level rejection is more operator-readable (names the specific unknown register the operator typed at the CLI level, not the helper level).
* The argparse-level rejection happens BEFORE the loader runs (faster + cleaner exit code).

### D210-Alt3: `--register` flag instead of positional argument

`thresholds get --register cold-pitch`. **Rejected** because:

* The per-call register selection is the operator-deliberate primary argument; positional makes the typical case (`thresholds get cold-pitch`) the shortest form.
* The optional `--thresholds-path` + `--json` are kwarg modifiers; the register is the primary argument and deserves the positional slot.

### D211-Alt1: Surface `--embed-fn` defensively even though CLI doesn't encode

Add `--embed-fn module:fn` to one or more of the `thresholds` subcommands "for future-proofing." **Rejected** per D211 — the flag's presence without behavior is operator-confusing + creates security + documentation surface for no benefit. YAGNI.

### D211-Alt2: Redesign the CLI to use embeddings

Make `thresholds list` compute thresholds from corpus embeddings (e.g., per-register percentile cutoff). **Rejected** per D200-Alt3 + Week 5 scope — the CLI's job is YAML inspection; embedding-based threshold derivation is Pillar F Week 8+ scope.

### D211-Alt3: Skip the verification

Don't explicitly name Week 5's P3-B status. **Rejected** because the Week 2 P3-B carry-forward is a per-week-reviewer checklist row; explicitly naming the Week 5 status (N/A + verified) closes the row for Week 5 + carries it forward to Weeks 6+ where the verification surface will matter.

## Consequences

### Positive consequences

* **Operators get a structured surface for per-register threshold inspection without writing custom Python scripts.** The three subcommands cover the typical operator workflows (audit all → audit one → bootstrap-config-from-template).
* **The JSON `_meta.source_path` + `_meta.is_fallback` provenance unblocks Pillar I per-tenant audit tooling.** Future Pillar I CLI extensions consume the structured shape; per-tenant configs surface their source paths in scripts.
* **The `dump` round-trip-cleanly contract is operator-actionable.** Operators bootstrapping fresh configs via `thresholds dump > ~/.outreach-factory/voice_thresholds.yml` get a file the loader accepts unchanged — no post-processing.
* **The SKILL.md register table's canonical order is preserved in the YAML re-emit.** Operators reading the dumped config see registers in the SKILL.md order (cold-pitch → congrats → re-engagement → reply → public-comment); operator-readability matches the documentation.
* **The Week 5 CLI is content-additive against Week 4's library.** No library-surface mutation; no new event classes; no new migrations; no SKILL.md changes. The Week 4 threshold loader's public surface stays verbatim per the per-week invariant preservation.

### Negative consequences

* **Test count grows by ~18 tests** (TestCLIThresholds class). Cumulative: 2863 (post-Week-4-follow-up) → 2881 (post-Week-5). The growth is bounded; per-subcommand tests are ~5-6 each (happy path × 2 modes + refuse-loud + provenance + edge cases).
* **`orchestrator/voice_corpus.py` grows from ~1990 LOC to ~2170 LOC** (adding ~180 LOC for the three CLI handlers + the `_resolve_thresholds_cli_paths` helper + the argparse subparser + docstrings). The growth is intentional — the CLI extension lands all-at-once.
* **The `thresholds` subcommand is the fourth top-level subcommand at `voice_corpus.py`.** Operators learning the CLI via `--help` see one more row; the grouped shape (nested actions under `thresholds`) keeps the discoverability bounded.

### Risks

The asymmetric-failure-cost calculus carries:

* **The `dump` YAML round-trip's per-key sort order drift risk (P3):** A future Pillar F contributor might change the YAML emit's sort order (e.g., switch to alphabetical via `yaml.safe_dump(..., sort_keys=True)`) without updating the SKILL.md register table or the default-shipped template. **Bounded by** the test `test_thresholds_dump_yaml_preserves_canonical_order` (added in Week 5 follow-up per P3-1 — parses the YAML emit's literal per-register key sequence + asserts it matches `list(DEFAULT_VOICE_THRESHOLD_PER_REGISTER.keys())`; the round-trip-cleanly test does NOT cover the order claim because YAML key order is semantically irrelevant to the loader) + the explicit `sort_keys=False` + the canonical-order dict construction at the handler + the per-week reviewer's checklist row at every Pillar F week verifying the SKILL.md table + the template order matches.

* **The `_meta.source_path` absolute path leakage in operator-shared output (P3):** Operators sharing CLI output (e.g., for support tickets) leak their local filesystem path. **Bounded by** the path being non-sensitive (operator's home directory + config filename — no per-Person data; no credentials). The operator's CLI output disclosure is operator-discretionary; the framework does not redact.

* **The `thresholds set` mutate subcommand's operator-demand pressure (P3):** Operators may push for the mutate subcommand sooner than Pillar I; the deferral may surface as user requests. **Bounded by** D209's explicit defer-to-Pillar-I rationale + the YAML being operator-editable via standard tooling (the mutate subcommand is ergonomic-sugar, not a missing capability).

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. The CLI is upstream of the ledger (it reads YAML + emits stdout; it does NOT write to the ledger). The threshold YAML itself is NOT a SoT in the I1 sense (it's operator-tunable config; the ledger remains the SoT for per-event data per ADR-0041 §Compliance).
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. The CLI is read-only.
* **I3 — Atomic per-Person enrollment.** Preserved. Week 5 doesn't touch enrollment.
* **I4 — Per-channel state isolation.** Preserved. The CLI is per-register (orthogonal to per-channel state).
* **I5 — Migration framework discipline.** Preserved. Week 5 ships ZERO new migrations; pending count stays at 19.
* **I6 — Channel-on-every-event invariant.** Preserved. The CLI is READ-only — it doesn't emit events.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved + EXTENDED. The CLI surfaces all of the Week 4 loader's refuse-loud surfaces via non-zero exit code + ERROR diagnostic on stderr (malformed YAML; missing required register key; unknown register key; out-of-range threshold value; non-numeric threshold; bool threshold). The argparse `choices=sorted(REGISTERS)` adds a sixth refuse-loud surface at the CLI level (unknown register on `get` subcommand). Mirrors `tier_assignment.py suggest`'s error-handling per ADR-0035 D164.
* **I8 — Privacy-respecting.** Preserved. The CLI is read-only against a static YAML; no per-Person data. The `_meta.source_path` carries the operator's local filesystem path (operator-discretionary; not framework-redacted).

## Downstream pillar impact

* **Pillar F Week 6+ (hallucination-detection primitive).** The Week 6+ primitive consumes `get_voice_threshold_for_register(register=<draft-register>)` at Layer 2-3 (construction-time invariant + parse-level guard). The Week 5 CLI doesn't directly interact with the Week 6+ primitive — but operators tuning per-register thresholds (the operator-side workflow Week 5's CLI enables) feeds into Week 6+'s gate behavior. The CLI is the operator-side substrate; the gate is the consumer.

* **Pillar F Week 8+ (fidelity-scoring primitive).** Same pattern as Week 6+. The Week 8+ per-draft fidelity-score-vs-threshold comparison reads the same loader; the Week 5 CLI is the operator-side inspection path. Operators recalibrating per-register thresholds per the §"Recalibration trajectory" in `config-template/voice_thresholds.example.yml` use the Week 5 CLI to verify post-recalibration values.

* **Pillar G (Observability).** Dashboards consuming `voice_fidelity_score` events with per-register threshold annotation can shell to `voice_corpus.py thresholds list --json` to fetch the current per-register thresholds for per-event annotation. The Week 5 CLI's stable JSON schema makes the per-event annotation surface contract-deliberate.

* **Pillar H (Real-time + scale).** The CLI's per-call cost is negligible (~5-10ms one-time YAML parse via the library loader's process-cache per ADR-0041 D203; ~1-2ms argparse + JSON dump). Pillar H's scaling concerns target the per-draft fidelity-scoring primitive at Week 8+; the CLI is content-additive against the optimization.

* **Pillar I (Multi-tenant + OSS hardening).** The Week 5 CLI is the FIRST operator-facing extension of the threshold loader; Pillar I extensions per ADR-0038 §Downstream pillar impact + ADR-0041 §Downstream pillar impact may land:
  * **Per-tenant config discovery:** `voice_corpus.py thresholds list --tenant <id>` resolves the per-tenant YAML override path.
  * **Mutate subcommand:** `voice_corpus.py thresholds set <register> <value>` with atomic-write + idempotence + per-register validation re-runs per D209's deferred decisions.
  * **Per-register drift detection:** `voice_corpus.py thresholds drift` compares the operator's current per-register tunings against the framework defaults + surfaces deltas. Consumes Week 5's stable JSON schema.
  * **Per-tenant overlay validation:** Pillar I doctor extensions walk per-tenant config trees + invoke `voice_corpus.py thresholds list --json` per-tenant + cross-validate.

* **Pillar J (Compliance + audit).** Per-tenant GDPR-purge does NOT touch the threshold YAML (operator config, not personal data); the threshold values themselves are NOT subject to purge. The CLI is read-only; no audit trail mutation.

## Migration / rollout

**Week 5 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11). Operators upgrading from Pillar F Week 4 to Pillar F Week 5:

1. **Operator updates the framework** to Pillar F Week 5's commit (standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Week 5 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_voice_corpus.py -v`** to verify the new CLI tests pass. Optional but recommended.
4. **Operator MAY use the new CLI subcommands**:
   * `python orchestrator/voice_corpus.py thresholds list` — inspect all five per-register thresholds + the source path.
   * `python orchestrator/voice_corpus.py thresholds get <register>` — inspect a single register's threshold.
   * `python orchestrator/voice_corpus.py thresholds dump > ~/.outreach-factory/voice_thresholds.yml` — bootstrap fresh operator config from the default template.

**Operator action required at Week 5:** NONE. The CLI extension is content-additive; operators with established workflows continue unchanged.

**Operator action recommended at Week 5:** none beyond the per-week pytest verification. Operators MAY explore the new CLI subcommands; existing operators who have NOT copied the default template to `~/.outreach-factory/voice_thresholds.yml` can use `thresholds dump > ~/.outreach-factory/voice_thresholds.yml` to bootstrap.

**Subsequent Pillar F weeks' migrations** (forward-reference): Week 6+ ships hallucination-detection's Layer 2 + Layer 3 (no migration; consumes the threshold loader per ADR-0041 D204). Week 8+ ships fidelity-scoring + flips `voice.use_embedding_primitive` default + may ship `vault/0006_add_voice_fidelity_score` for per-Touch-note fidelity annotations (TBD per the per-week design). Week 12 ships the binding exit-criterion test.

## Existing-operator seed

**Pillar F Week 5's operator-side disposition is content-additive — no operator action required at Week 5.** The CLI extension is operator-facing but optional; existing operators continue to read per-register thresholds via the Week 4 library surface OR via direct `cat ~/.outreach-factory/voice_thresholds.yml` inspection. The Week 5 CLI is a NEW path for operators who prefer structured CLI tooling.

The operator-side trajectory (per-week ships across Pillar F Weeks 4-12):

* **Week 4 (prior commit):** Threshold loader library surface lands. SKILL.md UNCHANGED.
* **Week 5 (this commit):** CLI extension lands (`thresholds list/get/dump`). SKILL.md UNCHANGED.
* **Weeks 6-10:** Hallucination-detection primitive's Layers 2-4 ship per ADR-0038 D180; consumes `get_voice_threshold_for_register` at draft-time. SKILL.md Phase 5 / 5.5 extensions land at Weeks 6+ per the P2-B carry-forward.
* **Week 8+:** Fidelity-scoring primitive lands; per-draft fidelity-score-vs-threshold comparison. `voice.use_embedding_primitive` default flips to true. SKILL.md Phase 4 extends with per-register routing per ADR-0040 §Existing-operator seed.
* **Week 12:** Binding exit-criterion test un-skips; Pillar F flips to Stable.

**Operator action required at Week 5:** none. The framework upgrade is read-only with respect to operator state.

**Operator action recommended at Week 5:** none beyond the per-week pytest verification. Operators MAY use the new CLI subcommands for per-register threshold inspection.

## References

- **ADR-0038 (D178-D184)** — Pillar F foundation. D180 (hallucination-detection FIVE-layer defense) + D184(a) (voice-fidelity score per-register operator-tunable) are the design surfaces Week 5's CLI surfaces to operators.
- **ADR-0039 (D185-D191)** — Pillar F Week 2 embedding-retrieval primitive. D188 (`retrieve_voice_exemplars` per-call entry point with TEST-ONLY `embed_fn` seam in docstring) + D191 (SKILL.md Phase 4 dual-path dispatch) are the structural references for Week 5's CLI extension (the existing `retrieve` subcommand's argparse + JSON output conventions).
- **ADR-0040 (D192-D198)** — Pillar F Week 3 per-register adapters. D193 (per-register kwarg dispatch convention matching SKILL.md register table) + D195 (per-register channel defaults pinned at module level) are the structural references for Week 5's per-register order preservation in the YAML re-emit.
- **ADR-0041 (D199-D205)** — Pillar F Week 4 per-register threshold infrastructure. D199 (threshold YAML schema with top-level `thresholds:` dict + precedence chain) + D200 (default-shipped per-register threshold values) + D201 (refuse-loud out-of-range + bool catch) + D202 (strict per-register key requirement) + D203 (process-cache posture) + D204 (`get_voice_threshold_for_register` helper) + D205 (TEST-ONLY `embed_fn` N/A at threshold loader) are the LOAD-BEARING substrate Week 5's CLI consumes.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier_assignment primitive. D164 (operator-readable diagnostic discipline — stderr warning on fallback to default) carries through to Week 5's CLI fallback warning. The `tier_assignment.py suggest` CLI surface at the bottom of the module is the structural reference for Week 5's subparser convention.
- **ADR-0036 (D166)** — Pillar E Week 9-11 per-primitive-flat-module convention. Week 5's CLI extension at `orchestrator/voice_corpus.py` (sibling of `retrieve_voice_exemplars` per D188 + `load_voice_thresholds` per D204) preserves the convention.
- **ADR-0033 (D149)** — Pillar E Week 2 discovery_dedup primitive. The `discovery_dedup.py check` CLI subcommand convention is the structural reference for Week 5's `thresholds list/get/dump` subcommand naming.
- **ADR-0034 (D154)** — Pillar E Week 4-5 email-verification cache. The `email_verification_cache.py lookup` CLI subcommand convention is the structural reference for Week 5's read-only CLI surface.
- **ADR-0014 (D33)** — Pillar C foundation. The channel-on-every-event invariant continues through the per-register adapters' downstream callers at Week 6+ + Week 8+; the CLI is upstream + does NOT touch the invariant.
- **`.planning/REVIEW-pillar-f-surface-audit.md`** — the cross-pillar audit. §32+ extends with the Week 5 CLI subcommand surface verifying content-additive against existing categories.
- **`.planning/HANDOFF-pillar-f-week-5.md`** — this week's handoff document (per the per-week handoff convention). Names the Week 6 trajectory.
- **`orchestrator/voice_corpus.py`** — extended with `_cmd_thresholds_list` + `_cmd_thresholds_get` + `_cmd_thresholds_dump` + `_resolve_thresholds_cli_paths` + argparse nested subparser for `thresholds` per D206-D211.
- **`tests/test_voice_corpus.py`** — extended with `TestCLIThresholds` class (~18 tests covering happy paths × 3 actions × 2 output modes + provenance metadata + refuse-loud surfaces + fallback round-trip + closed-enum register at argparse layer + TEST-ONLY embed_fn N/A verification).
- **`docs/PILLAR-PLAN.md` §6 Pillar F row** — appended with the Week 5 close summary.
- **`docs/adr/README.md`** — ADR-0042 row appended.
