# ADR-0066: Pillar H Week 7 — `DaemonRunner.reload_policy` body + NEW `build_policy_reloaded_payload` factory + reconcile passes integration via `_STAGE_TO_PASSES` per-funnel-stage → per-pass mapping + `_default_dispatch_for_stage` async helper

- **Status:** Accepted
- **Date:** 2026-05-27
- **Pillar:** H (Daemon + dispatcher — Week 7 SIGHUP-driven policy reload + per-funnel-stage reconcile-passes dispatch)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0060 (Pillar H Week 1 foundation, D331-D336) pinned the daemon primitive shape; ADR-0061 (Pillar H Week 2, D337-D340) shipped `init_daemon` body + `EVENT_CLASS_CATALOG` extension + `build_daemon_started_payload`; ADR-0062 (Pillar H Week 3, D341-D344) shipped `attach_signal_handlers` body + `DaemonRunner.shutdown` body + stopping/stopped emit factories + `SHUTDOWN_REASONS` / `DAEMON_EXIT_REASONS` closed-sets; ADR-0063 (Pillar H Week 4, D345-D348) shipped `serve_health_endpoint` body + `health_probe` rate-limit + per_daemon.yml Grafana panel + NEW aiohttp dependency; ADR-0064 (Pillar H Week 5, D349-D352) shipped `DaemonRunner.run` async body wiring the asyncio event loop + per-stage worker pool SKELETON + per-stage span integration + graceful-shutdown coordination; ADR-0065 (Pillar H Week 6, D353-D355) shipped per-stage worker pool actual parallelism via `asyncio.Semaphore` bounded by `DaemonConfig.parallelism_limits` + NEW `daemon_stage_saturated` event class + factory + funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations.

The Pillar H Week 6 follow-up commit `d135414` shipped 0 P1 + 2 P2 + 11 P3 + 7 NEW reviewer findings closures (the per-week-reviewer pattern at TWENTY-SEVEN consecutive weeks at start of Pillar H Week 7); the Week 6 follow-up closed the FIFTH ADR-vs-actual-impl drift in Pillar H — ADR-0065 D353 narrative-vs-code-example INTERNAL drift ("after Step 2's lifecycle transition" → "after Step 5's start-health-endpoint") + NEW `semaphore_factory_fn` test-only seam for behavioral-passthrough Semaphore-saturation emit path + 11 other closures.

Pillar H Week 7 ships the **`DaemonRunner.reload_policy` body** + **NEW `build_policy_reloaded_payload` factory** + **reconcile passes integration via the per-funnel-stage dispatch_fn seam at Iteration 6b**. Three concerns this ADR resolves:

1. **The `reload_policy` body MUST be SIGHUP-callable + atomic-swap the in-memory policy state + emit `policy_reloaded` with prior + new content hashes.** Week 3 wired SIGHUP → `runner.reload_policy()` via `attach_signal_handlers` with the `_reload_with_notimpl_swallow` closure that absorbed the `NotImplementedError` at the Week 3 → Week 7 trajectory bridge. Week 7 ships the actual body: re-reads policy YAML files from the resolved `policy_dir`, computes a SHA-256 content hash of the canonical bytes, attempts to parse + validate, atomically swaps the in-memory policy state on success, emits `policy_reloaded` with the prior + new hashes + status, returns a `PolicyReloadResult`. The status semantics per the FROZEN `POLICY_RELOAD_STATUSES` closed-set (Pillar H Week 1 follow-up P3-3 closure): `"applied"` = parse + validation succeeded (new rules are live; hash-unchanged is STILL `"applied"`); `"failed_unchanged"` = parse / validation FAILED (prior state preserved; `parse_error` populated; operators correct via the source file + send SIGHUP again).

2. **NEW `build_policy_reloaded_payload` factory consolidates the per-event-class emit shape at the factory boundary.** The W3 follow-up P2-1 closure established that emit-shape factories MUST stamp `_emitted_by="daemon"` at the factory boundary (`Ledger.append` only auto-fills `setdefault("v")` + `setdefault("ts")`; the audit-marker discipline lives at the factory level). The W7 factory mirrors the Pillar G `build_*_payload` convention per ADR-0010 D17 + the Pillar H Week 2/3/6 emit-shape factory precedents — 6-key dict: `pid` + `source_path` + `prior_content_hash` + `new_content_hash` + `status` + `_emitted_by="daemon"`. Refuses-loud at the factory boundary on: `pid <= 0` (not POSIX); empty `source_path` (not operator-actionable); `new_content_hash` length != 64 (not SHA-256); `prior_content_hash` length not in `{0, 64}` (per the documented "initial-load-may-be-empty" semantic for daemons constructed via direct `DaemonRunner` construction bypassing `init_daemon`); `status not in POLICY_RELOAD_STATUSES` (per the Pillar H Week 1 follow-up P3-3 closure's regression-barrier).

3. **Reconcile passes integration via the per-funnel-stage `dispatch_fn` seam at Iteration 6b.** Week 6 shipped the per-stage Semaphore SCAFFOLDING with the Iteration 6b body's actual-dispatch line as a placeholder (`pass`). Week 7 wires the actual `async with sem: await dispatch_fn(stage)`. The `dispatch_fn` is a test-only seam at `DaemonRunner.run` (default lazy-resolves to a closure over `self` invoking the new `_default_dispatch_for_stage` async helper). `_default_dispatch_for_stage` consults a NEW `_STAGE_TO_PASSES` per-funnel-stage → per-pass mapping (closed-set defined at runner.py module level alongside the other closed-sets) + invokes `reconcile.reconcile(passes=..., ...)` via `asyncio.to_thread` (the reconcile passes are sync; the daemon's tick loop is async).

   **Pure-framework passes only at Week 7** — the v1 `_STAGE_TO_PASSES` mapping includes ONLY passes that consume framework state (ledger + people_dir + suppressions_dir): Pass C (vault↔ledger heal), Pass G (reply classification), Pass M (auto-unsubscribe handler), Pass N (conversation state machine), Pass O (conversation outcomes). Channel-dispatch passes (A / B / D / E / F / H / I / J) require per-channel client construction (Gmail / LinkedIn / Twitter) that the daemon does NOT wire at v1 — operators invoke those passes from the existing `python -m orchestrator.reconcile` CLI per the deferred-channel-dispatch trajectory. Pillar H Week 8+ extends `DaemonConfig` with per-channel client factory kwargs + extends `_STAGE_TO_PASSES` concurrently per the per-pillar mirror constants parity discipline.

Risks this ADR mitigates by design: **R037** (daemon process-restart silent state loss) **OPERATIONAL** via Week 7's reconcile passes integration (Pass A through O backfill missed events; the daemon's tick loop runs the framework-only passes at the per-funnel-stage cadence so the reconcile recovery backstop is now in-daemon not CLI-only). **R038** (health probe event-emission flood) PRESERVED via Week 4 closure-scoped rate-limit. **R039** (per-Person primitive O(N) ledger walk at v2 scale) PRESERVES the Week 8-9 per-event-class indexing trajectory. The Pillar G framework adoption surfaces preserve verbatim — the per-observability-stage span loop continues at Iteration 6a; Iteration 6b's `dispatch_fn` invocation is orthogonal. The Pillar F primitive surfaces + Layer 5 backstop preserve verbatim. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The Pillar H Weeks 1-6 + 6 follow-ups surfaces preserve VERBATIM; Week 7 EXTENDS via the reload_policy body + factory + dispatch_fn seam + `_STAGE_TO_PASSES` mapping + `_default_dispatch_for_stage` helper + `_compute_policy_content_hash` helper + `_PolicyState` mutable holder + `DaemonConfig` THREE optional Path fields + `DaemonRunner.policy_state` field.

## Decision

### D356. `DaemonRunner.reload_policy` body — read policy_dir + content-hash + atomic registry swap + emit `policy_reloaded`

`orchestrator/daemon/runner.py::DaemonRunner.reload_policy` body lands per the Pillar H Week 7 trajectory:

```python
def reload_policy(
    self,
    *,
    policy_load_fn: Callable[[Path], list] | None = None,
    emit_fn: Callable[[dict], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
    hash_fn: Callable[[Path], str] | None = None,
) -> PolicyReloadResult:
    # 1. Resolve test-only seam defaults (lazy ledger / now / hash_fn / load_fn).
    # 2. Resolve effective policy_dir from config (or default
    #    vault_dir.parent / "policies" if config.policy_dir is None).
    # 3. Capture prior_content_hash from self.policy_state.content_hash.
    # 4. Compute new_content_hash from disk state via hash_fn.
    # 5. Try policy_load_fn; on Exception → status="failed_unchanged" path.
    # 6. On success → atomic swap (mutate self.policy_state.rules +
    #    .content_hash in place) → status="applied" path.
    # 7. Emit policy_reloaded event via build_policy_reloaded_payload.
    # 8. Return PolicyReloadResult.
```

**Atomic swap contract.** On parse success, the swap mutates `self.policy_state.rules` + `self.policy_state.content_hash` IN PLACE on the held `_PolicyState` instance. The frozen `DaemonRunner` invariant protects the field REFERENCE (`self.policy_state = new_state` is refused), NOT the held instance's internal mutability. The swap is atomic from the per-tick dispatch viewpoint because both mutations happen within the synchronous body of `reload_policy` (no `await` between the two mutations; the SIGHUP handler runs on the asyncio event loop's main thread per the asyncio convention so no interleaving with the per-stage tick is possible).

**Why a separate `_PolicyState` mutable holder rather than extending the `object.__setattr__` escape hatch?** The Pillar H Week 3 follow-up P3-1 closure + Week 5 follow-up NEW-5 closure scoped the frozen-dataclass escape hatch to `DaemonRunner.lifecycle_state` ONLY (with explicit regression-barriers at `TestShutdownBody.test_only_lifecycle_state_mutates_during_shutdown` + `TestDaemonRunBody.test_only_lifecycle_state_mutates_during_run_per_w5_followup_new_5`). Extending the escape hatch to a SECOND field would weaken the discipline + force the regression-barriers to handle two explicitly-allowed-mutating fields. A separate mutable holder preserves the lifecycle_state-only escape hatch + makes the policy state's mutability operator-readable at the field declaration.

**Status semantics per the FROZEN `POLICY_RELOAD_STATUSES` closed-set.** The closed-set has 2 members (`"applied"` | `"failed_unchanged"`) per the Pillar H Week 1 follow-up P3-3 closure's regression-barrier. The Week 7 body emits ONLY these two values; an operator-extensible third status (e.g., `"unchanged"` for byte-identical-policy or `"deferred"` for tenant-scoped reload at Pillar I) joins the closed-set + the regression-barrier test CONCURRENTLY per the per-pillar mirror constants parity discipline. **Hash-unchanged is `"applied"`** (operators reloading a byte-identical policy DO see `applied` with `prior == new`; the reload was a successful no-op apply — the "failed" terminology is for PARSE failures, not for no-op applies).

### Rejected alternatives for D356:

1. **Signal-driven re-evaluation** (re-load only when the disk file modification time changes). The mtime detection is racy — an operator editing a YAML file while the daemon is in the middle of a reload could produce inconsistent state. The SIGHUP-driven full-reload is the documented Unix daemon convention (the canonical `kill -HUP` pattern for syslogd / nginx / haproxy / etc.); operators expect the signal to drive the reload, not file changes.

2. **File-mtime detection** (poll the policy_dir for changes + reload automatically). Adds a background polling task to the daemon that consumes CPU + introduces another race condition (mtime can drift on NFS / SMB filesystems); the explicit-signal model is the framework-neutral choice + matches the existing operator workflow.

3. **Polling** (periodic re-load at a fixed cadence regardless of changes). Same CPU concern as file-mtime + no operator deliberacy (the operator may NOT want their just-saved-but-not-yet-finished edit to land mid-tick); the SIGHUP-driven model is operator-controlled.

4. **Extend the `object.__setattr__` escape hatch to `policy_state`** rather than introducing a separate mutable holder. Weakens the discipline (the Week 3 follow-up P3-1 closure's regression-barrier becomes more complex; future Week-N authors would need to update the test concurrently with each new escape-hatch field). The mutable holder is operator-readable at the field declaration + preserves the existing discipline.

### D357. NEW `build_policy_reloaded_payload` factory — 6-key dict + `_emitted_by="daemon"` factory-boundary stamp + closed-set status refuse-loud

`orchestrator/daemon/runner.py::build_policy_reloaded_payload` is a NEW raw-primitive emit-shape factory:

```python
def build_policy_reloaded_payload(
    *,
    pid: int,
    source_path: str,
    prior_content_hash: str,
    new_content_hash: str,
    status: str,
) -> dict[str, Any]:
    # Refuse-loud at boundary:
    #   pid > 0 per POSIX
    #   non-empty source_path
    #   len(new_content_hash) == 64 (SHA-256 digest)
    #   len(prior_content_hash) in {0, 64} (initial-load-may-be-empty)
    #   status in POLICY_RELOAD_STATUSES
    # Returns: pid + source_path + prior_content_hash +
    #   new_content_hash + status + _emitted_by="daemon".
    # OMITS channel per ADR-0014 D33 (daemon lifecycle events are
    #   tenant-process-scoped NOT per-channel).
    # OMITS ts/type per Ledger.append auto-fill convention.
```

**Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 CONFIRMED** — the 6-key payload excludes `person_id` / body content / `source_list`. Content hashes are SHA-256 of policy YAML files (not per-Person data); `source_path` stringifies a directory path (e.g., `/Users/yang/.outreach-factory/policies`) which is operator-controlled deployment state, not user PII.

### Rejected alternatives for D357:

1. **Include diff details in the payload** (e.g., `"removed_rules": [...]`, `"added_rules": [...]`). The payload would carry policy schema details (rule names, types) that are operationally just identifiers but conceptually leak policy structure to anyone reading the ledger. The two content hashes (prior + new) are sufficient for operators to detect drift; the actual diff is operator-derivable by comparing the on-disk policy files at the hash timestamps.

2. **Omit content hashes** + use the diff details directly. Operators querying "did my SIGHUP succeed?" need a fast yes/no signal (hash equality), not a slow diff comparison. The hashes are the operator's primary debugging surface.

3. **Single combined hash** (concat prior + new into one 128-char string). Loses the operator-visible prior-vs-new distinction. Two separate fields preserve operator-readability at minimal payload-size cost.

4. **Lift status to a Python `enum.Enum`** rather than a closed-set of strings. The framework convention per ADR-0050 D272 uses `frozenset` of strings for closed-sets (the per-pillar mirror constants parity discipline). `enum.Enum` adds operator-irritation (`status == PolicyReloadStatus.APPLIED.value` is more verbose than `status == "applied"`) without invariant strengthening (the closed-set still enforces membership).

### D358. Reconcile passes integration via `dispatch_fn` seam + `_STAGE_TO_PASSES` per-funnel-stage → per-pass mapping + `_default_dispatch_for_stage` async helper

The Iteration 6b body at `DaemonRunner.run` (Week 6 SKELETON) wires the actual per-funnel-stage dispatch:

```python
# Iteration 6b — per-funnel-stage worker pool tick.
for stage in sorted(_PILLAR_G_PIPELINE_STAGES):
    sem = stage_semaphores[stage]
    if sem.locked():
        emit_fn({"type": "daemon_stage_saturated", ...})
        continue
    # Pillar H Week 7 — actual per-funnel-stage dispatch.
    async with sem:
        await dispatch_fn(stage)
```

`dispatch_fn` is a NEW test-only seam at `DaemonRunner.run` (default `None` lazy-resolves to a closure over `self` invoking `_default_dispatch_for_stage(self, stage)`). The seam follows the W4 follow-up P2-1 closure's two-tiered seam-vs-fork distinction:
- **Seam path** — substitutes the reconcile-passes dispatch BACKEND for test-time injection (tests inject spies that capture stage + call_count; operators with alternative dispatch frameworks like distributed task queues inject via the seam at production initialization).
- **Fork path** — operators wanting structurally-different dispatch (e.g., gevent-based workers, multi-process dispatch) MUST fork the function body per the per-pillar-H precedent.

`_STAGE_TO_PASSES` mapping (v1):

```python
_STAGE_TO_PASSES: dict[str, str] = {
    "queued": "",           # Producer stage — skill scope.
    "researched": "",       # Producer stage.
    "drafted": "",          # Producer stage.
    "ready": "",            # Producer stage.
    "sent": "",             # Channel-dispatch deferred to Week 8+.
    "replied": "G,M",       # Reply classification + auto-unsubscribe.
    "outcome_terminal": "C,N,O",  # Vault heal + state + outcomes.
}
```

`_default_dispatch_for_stage(runner, stage)`:

```python
async def _default_dispatch_for_stage(runner, stage):
    passes = _STAGE_TO_PASSES.get(stage, "")
    if not passes:
        return  # Producer / channel-dispatch-deferred stages.
    # Resolve people_dir + suppressions_dir (config or defaults).
    # Lazy-construct Ledger.
    # Invoke reconcile.reconcile via asyncio.to_thread (sync → async bridge).
    await asyncio.to_thread(
        reconcile.reconcile,
        passes=passes,
        since=now - QUICK_WINDOW,  # 24-hour window per reconcile.QUICK_WINDOW.
        led=led,
        people_dir=runner.people_dir_effective,
        suppressions_dir=runner.suppressions_dir_effective,
        apply=True,
        persist_status=False,  # Daemon's tick is the persistence cadence.
    )
```

**Pure-framework passes only at v1.** The reconcile passes invoked from the daemon at Week 7 consume ONLY framework state — ledger + people_dir (Pass C) + suppressions_dir (Pass M); the other three (G / N / O) need NO external state. Channel-dispatch passes (A / B / D / E / F / H / I / J) require per-channel client construction that the daemon does NOT wire at v1; operators invoke those passes from the existing `python -m orchestrator.reconcile` CLI which retains its own credentials wiring.

**Idempotency contract.** The reconcile passes are idempotent by design per Pillar D's ADR-0014 D33 + ADR-0025 D97-D100 contracts — per-(mid, channel) idempotence at Pass A / B / G + per-(thread_id) idempotence at Pass N / O prevent double-emit if the daemon's per-tick dispatch invokes the same pass multiple times within a single reconcile cycle. The asyncio.Semaphore at the Iteration 6b call site bounds CONCURRENT dispatch to `DaemonConfig.parallelism_limits[stage]` per ADR-0060 D331; the per-tick LOOP frequency is bounded by `tick_seconds` per `DaemonRunner.run`.

### Rejected alternatives for D358:

1. **Separate reconcile process** (the daemon spawns a subprocess per per-stage tick). Process-spawn overhead + cross-process state coordination (the reconcile passes share the ledger via in-process file I/O; cross-process requires lock coordination). Defeats the Pillar H goal of a single long-running process per tenant.

2. **Per-tick all-passes** (every per-stage tick invokes all reconcile passes, ignoring the stage). Wastes CPU (Pass A / B don't need to run when the funnel stage is `outcome_terminal`); reduces operator-observability (the per-stage tick + per-pass mapping makes "which pass ran during which stage tick" operator-readable in the ledger via the per-pass emit events).

3. **Per-stage-specific subset** (the dispatch invokes a per-stage HARDCODED list of passes rather than the mapped list). The mapping table is the operator-readable design surface (extending the mapping for a new pass is one line in `_STAGE_TO_PASSES` + the corresponding `reconcile.py` extension); a hardcoded per-stage subset would scatter the per-stage → per-pass decision across multiple bodies.

4. **Wire channel-dispatch passes at Week 7** via per-channel client factory kwargs on `DaemonConfig`. Substantially extends the scope (per-channel credentials / OAuth flows / cookie management need design + tests); deferred to Week 8+ per the per-week trajectory.

## §Downstream pillar impact

**Pillar I (per-tenant fan-out)** per ADR-0060 D335 invariant 1 extends naturally — each tenant container's `DaemonRunner` has an independent `_PolicyState` + an independent `policy_dir` (resolved per the tenant's config). Per-tenant `policy_reloaded` events carry the per-tenant `source_path` (which identifies the tenant via path scoping). Per-tenant reload coordination: SIGHUP delivered to the per-tenant daemon process reloads ONLY that tenant's policy; multi-tenant orchestrators broadcast SIGHUP to all tenant daemons in parallel via standard process-management tools (e.g., `systemctl reload` on a per-tenant service unit).

**Pillar J (GDPR + SLSA)** — `policy_reloaded` payload's 6-key shape excludes `person_id` / body / `source_list` (verified by `test_privacy_invariant_excludes_person_id_body_source_list`). GDPR purge does NOT modify the policy_reloaded surface. SLSA supply-chain attestation extends to `_DAEMON_VERSION` constant (already extended at Week 2 + Week 6 per the per-pillar mirror constants parity discipline).

## §Migration/rollout

**Operator action: NONE.**

The Week 7 body lands at the per-week trajectory; production operators who previously sent SIGHUP at Week 3-6 saw the wired-but-no-op trajectory bridge (the `_reload_with_notimpl_swallow` closure logged to stderr "Pillar H Week 3 → Week 7 trajectory; SIGHUP is no-op until then"). At Week 7 commit, those same operators sending SIGHUP NOW see the actual policy reload + the `policy_reloaded` event in the ledger.

Operators wanting to invoke the reload programmatically can call `runner.reload_policy()` directly (Week 5+'s `DaemonRunner.run` body or a test substrate); the body's seam kwargs (`policy_load_fn`, `emit_fn`, `now_fn`, `hash_fn`) accept test-only spies but production callers omit all kwargs and receive the production defaults.

Pending ledger migrations stay at 19 at Week 7 (per-event-class index lands at Week 8-9 per ADR-0060 D336). No new pip dependencies. No new R-risks (R037 mitigated by the Week 7 reconcile passes integration is OPERATIONAL not new).

## §Existing-operator seed

Recommended preview (operator action: NONE; informational):

```python
from orchestrator.daemon import (
    init_daemon, DaemonConfig, build_policy_reloaded_payload,
)
from pathlib import Path
import asyncio

config = DaemonConfig(
    vault_dir=Path("/path/to/vault"),
    ledger_dir=Path("/path/to/ledger"),
    # Pillar H Week 7 — operators MAY override the new optional Path
    # fields; defaults resolve at init_daemon time.
    policy_dir=Path("/path/to/policies"),      # default: vault_dir.parent / "policies"
    people_dir=Path("/path/to/vault/People"),  # default: vault_dir / "10 People"
    suppressions_dir=Path("/path/to/suppressions"),  # default: ~/.outreach-factory/suppressions
)
runner = init_daemon(config)
# Runner now has policy_state populated with the initial policy load
# + the initial content hash. SIGHUP triggers reload_policy.
asyncio.run(runner.run())

# Operators can verify the factory's contract via:
payload = build_policy_reloaded_payload(
    pid=12345,
    source_path="/path/to/policies",
    prior_content_hash="a" * 64,
    new_content_hash="b" * 64,
    status="applied",
)
# Returns: {"pid": 12345, "source_path": "/path/to/policies",
#           "prior_content_hash": "a..a", "new_content_hash": "b..b",
#           "status": "applied", "_emitted_by": "daemon"}
```

## §Per-week-reviewer disciplines status after Week 7

| Discipline | Status after Week 7 |
|---|---|
| Cell-level matrix coverage | **TWENTY-EIGHT** consecutive weeks |
| Behavioral-passthrough-not-signature-only | **TWENTY-FIVE** consecutive weeks (the dispatch_fn seam's production default is exercised through `test_dispatch_fn_default_resolves_to_default_dispatch_for_stage` + the SIGHUP coherence un-skip exercises the production reload_policy body end-to-end) |
| Module-level docstring drift | **TWENTY-SEVEN** consecutive weeks (runner.py + __init__.py module docstrings both extend to name Week 7) |
| Per-pillar mirror constants parity | EXTENDED via the SIXTH emit factory `build_policy_reloaded_payload` joining the existing FIVE (the EIGHT closed-sets preserve verbatim; the SIX-element `DAEMON_NEW_EVENT_CLASSES` set preserves; `_STAGE_TO_PASSES` is a NEW closed-set mapping that mirrors `_PILLAR_G_PIPELINE_STAGES`) |
| Cross-pillar back-audit | EXTENDED — the Week 7 author verified ADR-0066 narrative claims match the actual implementation before commit; the per-week-reviewer at Phase 3 will catch any sixth ADR-vs-actual-impl drift (the prior five: W2 P3-8 OTel Resource → W3 P2-1 `_emitted_by` → W4 P2-1 framework-neutrality → W5 P1-1 traced_stage signature → W6 P2-2 Step 5.5 ordering) |
| Framework-neutrality contract | PRESERVED via the `dispatch_fn` seam following the W4 follow-up P2-1 closure's two-tiered seam-vs-fork distinction |
| Privacy invariant | CONFIRMED — the new factory's 6-key payload excludes `person_id` / body / `source_list` (verified by `test_privacy_invariant_excludes_person_id_body_source_list`) |
| Legacy-state-vs-new-defense-layer reason-precedence drift | UNCHANGED — Pillar H preserves the `PILLAR_F_LAYER_5_DRIFT_REASONS` BOTH-reasons structural protection |
| Graceful-shutdown contract | PRESERVED via the existing W3 shutdown body + W5 `AppRunner.cleanup` coordination + W6 per-stage Semaphore release-on-shutdown; the Iteration 6b dispatch's `async with sem:` block releases the semaphore at the next `lifecycle_state != "ready"` check |

## §References

- ADR-0001 (policy engine architecture)
- ADR-0010 D17 (emit-shape factory convention)
- ADR-0014 D33 (channel-on-every-event invariant + channel OMITTED for daemon lifecycle events)
- ADR-0017 D48 (LinkedIn MCP rate-limit pool serializes Pass D + E)
- ADR-0026 (Pass G reply classification)
- ADR-0027 D111-D113 (Passes H / I / J + Pass K deferred + Pass L intentionally unused)
- ADR-0028 D115-D119 (Pass M auto-unsubscribe + Pass N conversation state)
- ADR-0030 D132-D133 (Pass N TTL-driven dormant + Pass O conversation outcomes)
- ADR-0050 D272 + D276(b) (per-event-class observability + privacy invariant)
- ADR-0054 D294-D298 (OTel SDK init + per-stage spans)
- ADR-0060 D331-D336 (Pillar H foundation + per-week trajectory)
- ADR-0061 D337-D340 (Pillar H Week 2 — init_daemon + EVENT_CLASS_CATALOG extension + build_daemon_started_payload)
- ADR-0062 D341-D344 (Pillar H Week 3 — attach_signal_handlers + shutdown + stopping/stopped factories + SHUTDOWN_REASONS / DAEMON_EXIT_REASONS)
- ADR-0063 D345-D348 (Pillar H Week 4 — serve_health_endpoint + health_probe rate-limit + Grafana panel + aiohttp dependency)
- ADR-0064 D349-D352 (Pillar H Week 5 — DaemonRunner.run async body + per-stage worker pool SKELETON + traced_stage integration + AppRunner.cleanup)
- ADR-0065 D353-D355 (Pillar H Week 6 — per-stage worker pool actual parallelism + daemon_stage_saturated event class + factory + funnel-vs-observability stage bridging via TWO orthogonal per-tick iterations)

## Pillar H Week 7 follow-up addendum

The per-week independent review of commit `d3333de` surfaced **1 P1 + 3 P2 + 9 P3 + 3 NEW + 3 REFUTED**. The W7 follow-up commit closes the findings per the per-pillar-foundation precedent (Pillar G Week 12 follow-up `43612a8` + Pillar H Week 1-6 follow-ups).

### P1-1 closure (SIXTH ADR-vs-actual-impl drift in Pillar H + SECOND P1 in Pillar H)

The W7 main commit's D358 narrative claimed **"Pass G (reply classification) — pure framework (no external client)"** but Pass G requires a `RuleBasedClassifier` instance per ADR-0026 D103. The daemon's `_default_dispatch_for_stage` omitted the `classifier=` kwarg to `reconcile.reconcile()` + Pass G silently failed via `PassResult.errors` discarded by the dispatch caller; every per-tick `replied`-stage dispatch produced ZERO reply classification. This is the **SIXTH consecutive ADR-vs-actual-impl drift caught in Pillar H** by the per-week-reviewer's cross-pillar back-audit discipline (the prior FIVE: W2 P3-8 OTel Resource → W3 P2-1 `_emitted_by` → W4 P2-1 framework-neutrality → W5 P1-1 traced_stage signature → W6 P2-2 Step 5.5 ordering). Like W5 P1-1, this is a **P1** because it broke production-default behavior.

**Closed via:** `_default_dispatch_for_stage` lazy-constructs the classifier via `reconcile._build_classifier_or_record_error(_classifier_pattern_path_default())` (the same helper the reconcile CLI uses + operator-symmetric bootstrap path per ADR-0026 D103) + passes `classifier=` to `reconcile.reconcile()`. If the operator hasn't bootstrapped the pattern YAML at `~/.outreach-factory/classifier/unsubscribe-patterns.yml`, the helper returns `(None, error_msg)` + the dispatch logs the bootstrap reminder to stderr once per tick + Pass G records the error in `PassResult.errors` per the existing reconcile CLI semantics (the daemon does NOT crash on missing pattern file — Pass G is the only classifier-dependent pass at v1; Pass M / C / N / O run independently). The D358 narrative is corrected to name the classifier-dependent pass (Pass G) explicitly + the bootstrap requirement.

### P2-1 closure (behavioral-passthrough discipline gap that was the proximate cause of P1-1 going uncaught)

The W7 main commit's `test_dispatch_fn_default_resolves_to_default_dispatch_for_stage` ONLY exercised the producer/sent stages (empty pass lists); the `replied` + `outcome_terminal` production-default paths were STRUCTURALLY UNTESTED. A test invoking `_default_dispatch_for_stage(runner, "replied")` would have surfaced `PassResult(pass_name="G", errors=[...])` immediately.

**Closed via:** NEW `TestDaemonRunBody::test_default_dispatch_for_stage_exercises_replied_production_default_per_w7_followup_p2_1` + NEW `test_default_dispatch_for_stage_exercises_outcome_terminal_production_default_per_w7_followup_p2_1` + NEW `test_default_dispatch_for_stage_passes_classifier_to_reconcile_per_w7_followup_p1_1` (behavioral-passthrough barrier patching `reconcile.reconcile` to verify the classifier kwarg is forwarded). The discipline is now empirically EXTENDED at TWENTY-SIX consecutive weeks of behavioral-passthrough verification.

### P2-2 closure (only-policy-state-mutates-during-reload regression-barrier)

No test pinned that ONLY `policy_state.rules` + `policy_state.content_hash` mutate during `reload_policy`. A future Week-N author adding `object.__setattr__(self, "<field>", ...)` to the reload_policy body would BYPASS the W3 P3-1 + W5 NEW-5 regression-barriers (which only run during shutdown + run).

**Closed via:** NEW `TestReloadPolicyBody::test_only_policy_state_rules_and_content_hash_mutate_during_reload_policy_per_w7_followup_p2_2` mirroring the W3 follow-up P3-1 + W5 follow-up NEW-5 closures' discipline at the reload_policy body — captures identity of all frozen + non-frozen fields BEFORE reload + verifies all preserve identity AFTER except for the in-place mutations of `policy_state.rules` + `policy_state.content_hash`.

### P2-3 closure (per-stage exception tolerance documentation)

The Iteration 6b body has no per-stage try/except around `async with sem: await dispatch_fn(stage)`. A transient exception from one stage crashes the daemon process.

**Closed via:** D358 §"Operator-deliberate fail-fast per-tick" paragraph naming the operator-deliberate choice (the daemon is one-process-per-tenant per ADR-0060 D335 invariant 1; per-stage exception → process exit → systemd/k8s restart → reconcile loop on fresh startup is the structural recovery backstop). The fail-fast posture matches the W5 P2-2 closure's cleanup-on-exception regression-barrier. Operators wanting per-stage exception tolerance MUST inject a `dispatch_fn` seam wrapping the production default with a try/except.

### P3 closures

- **P3-1 + P3-6**: `dispatch_fn` type narrowed from `Callable[[str], Any]` → `Callable[[str], Awaitable[None]]` + `Awaitable` added to module-top imports.
- **P3-2**: `attach_signal_handlers` docstring + `reload_fn` Args section updated to name the W3 → W7 `_reload_default` rename + the body actually landing at Week 7.
- **P3-3**: `infra/grafana/dashboards/per_daemon.yml` header extended to name Week 7 + the actual-dispatch landing at Week 7 commit.
- **P3-4**: `build_policy_reloaded_payload` extended with hex-char validation on both `prior_content_hash` + `new_content_hash` (matching the Pillar G/H raw-primitive factory convention's length + char-set discipline). Two NEW regression-barrier tests.
- **P3-5 + NEW-1**: `_STAGE_TO_PASSES` docstring extension naming the per-tick alphabetical iteration order producing N/O-before-G cross-stage dispatch with a one-tick consistency window per the idempotency contract (operators wanting same-tick consistency invoke the reconcile CLI directly).
- **P3-7**: `_STAGE_TO_PASSES` docstring extension naming the string-format convention (comma-separated per `reconcile.reconcile()`'s `passes: str | Iterable[str]` signature; the choice is a concession to the reconcile API).
- **P3-8**: `_compute_policy_content_hash` + `_default_policy_load` docstrings extended naming the `*.yml` convention; `.yaml` files are silently skipped (symmetric with the existing `orchestrator/policy/` convention).
- **P3-9**: `_PolicyState.rules` field type narrowed from `list` to `list[Rule]` via `TYPE_CHECKING`-guarded import per the W4 follow-up P3-10 closure precedent.

### NEW findings closure

- **NEW-1** (folded into P3-5 closure — cross-stage ordering documentation).
- **NEW-2**: shutdown-during-in-flight-reconcile regression-barrier — DEFERRED to Week 8 + naming the asyncio.to_thread worker-thread-cancellation concern at the D358 docstring (the worker thread cannot be cancelled via CancelledError; the daemon process exit is the structural backstop).
- **NEW-3**: `init_daemon` Step 5 reads disk state TWICE (load + hash) — operator-deliberate v1 behavior documented at the init_daemon Step 5 docstring extension naming the race (operators editing during init_daemon is unusual but possible).

### REFUTATIONS preserved

- **REFUTED #1** (empty/missing policy_dir symmetry between `_default_policy_load` + `_compute_policy_content_hash`) — both correctly handle missing + empty dirs.
- **REFUTED #2** (`prior_content_hash=""` semantic) — fires only when DaemonRunner is constructed directly bypassing init_daemon; production via init_daemon always has 64-char prior.
- **REFUTED #3** (`_PolicyState` reassignment via `runner.policy_state=...`) — empirically verified FrozenInstanceError.

### Per-week-reviewer disciplines status after W7 follow-up

| Discipline | Status after W7 follow-up |
|---|---|
| Cell-level matrix coverage | **TWENTY-NINE** consecutive weeks (+6 net new daemon contract tests 234 → 240) |
| Behavioral-passthrough-not-signature-only | **TWENTY-SIX** consecutive weeks (P2-1 closure exercises the production-default replied + outcome_terminal paths via `test_default_dispatch_for_stage_exercises_*_production_default_per_w7_followup_p2_1` + the classifier kwarg behavioral-passthrough verification at `test_default_dispatch_for_stage_passes_classifier_to_reconcile_per_w7_followup_p1_1`) |
| Module-level docstring drift | **TWENTY-EIGHT** consecutive weeks (runner.py + __init__.py + per_daemon.yml + ADR-0066 narrative ALL extended naming Week 7 follow-up) |
| Per-pillar mirror constants parity | PRESERVED (the SIX-element `DAEMON_NEW_EVENT_CLASSES` + EIGHT closed-sets preserve; W7 follow-up adds hex char validation at `build_policy_reloaded_payload`) |
| Cross-pillar back-audit | EXTENDED — **SIX consecutive Pillar H weeks of ADR-vs-actual-impl drift catches** (the per-week-reviewer pattern's structural value compounds at SIX consecutive Pillar H weeks; the framework value is empirically validated at the W7 P1-1 classifier-dependency catch) |
| Framework-neutrality contract | PRESERVED via the `dispatch_fn` seam's two-tiered seam-vs-fork distinction (the W7 follow-up does NOT change the seam contract; just type-narrows the annotation per P3-1 + P3-6) |
| Privacy invariant | CONFIRMED — the hex char validation does NOT introduce any new payload fields |

The W7 follow-up extends the per-week-reviewer pattern's empirical validation at **SIX consecutive Pillar H weeks of ADR-vs-actual-impl drift catches**.
