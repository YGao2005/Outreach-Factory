# ADR-0062: Pillar H Week 3 — `attach_signal_handlers` body wiring SIGTERM + SIGINT + SIGHUP via asyncio + `DaemonRunner.shutdown` body with lifecycle state transitions through `"draining"` → `"stopped"` via `object.__setattr__` frozen-dataclass escape hatch + `build_daemon_stopping_payload` + `build_daemon_stopped_payload` emit-shape factories + `SHUTDOWN_REASONS` + `DAEMON_EXIT_REASONS` closed-sets

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** H (Daemon + dispatcher — Week 3 signal handler + shutdown bodies)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0060 (Pillar H Week 1 foundation, D331-D336) pinned the daemon primitive shape — `DaemonConfig` + `DaemonRunner` + `PolicyReloadResult` + `HealthStatus` frozen dataclasses + closed-sets + primitive signatures — at `orchestrator/daemon/`. ADR-0061 (Pillar H Week 2, D337-D340) shipped the `init_daemon` body + the `EVENT_CLASS_CATALOG` extension + the `build_daemon_started_payload` emit-shape factory + closed Week 1 carry-forwards P3-1 (startup ordering regression-barrier) + P3-2 (OTel set-once enforcement). The Pillar H Week 2 follow-up commit `9954fd5` shipped 2 P2 + 8 P3 reviewer findings closures (the per-week-reviewer pattern at NINETEEN consecutive weeks at start of Pillar H Week 3); the Week 2 follow-up extended `_validate_config` with refuse-loud rules for next-tier invariant-bearing fields + extended `build_daemon_started_payload` with input validation per the Pillar G raw-primitive factory convention + added `TestModuleConstants` + `TestComputeConfigHash` + `TestDefaultPolicyLoad` regression-barriers + corrected ADR-0061 D337's OTel `Resource` rationale.

Pillar H Week 3 ships the **`attach_signal_handlers` body** wiring asyncio signal handlers for SIGTERM + SIGINT + SIGHUP + the **`DaemonRunner.shutdown` body** with lifecycle state transitions through `"draining"` (emit `daemon_stopping`) → `"stopped"` (emit `daemon_stopped`) + the **`build_daemon_stopping_payload`** + **`build_daemon_stopped_payload`** emit-shape factories + the **`SHUTDOWN_REASONS`** (`sigterm` | `sigint` | `operator_requested`) + **`DAEMON_EXIT_REASONS`** (`clean` | `timeout` | `crash`) closed-sets. The four concerns this ADR resolves:

1. **The `attach_signal_handlers` body MUST wire asyncio signal handlers per the ADR-0060 D332 framework decision.** The Python stdlib's `signal.signal()` does NOT integrate with asyncio's event loop — the canonical asyncio pattern is `loop.add_signal_handler(sig, callback)`. The signal handlers run on the asyncio event loop's main thread; callbacks are sync, fast, and non-blocking. SIGTERM → `runner.shutdown("sigterm")`; SIGINT → `runner.shutdown("sigint")`; SIGHUP (iff `config.policy_reload_signal == "SIGHUP"`) → `runner.reload_policy()`. The SIGHUP handler at Week 3 wires the dispatch BUT the actual `reload_policy` body lands at Week 7+ per ADR-0060 D332's trajectory; the Week 3 handler swallows `NotImplementedError` + logs to stderr so operators tracing the signal flow at Week 3-6 see the wired-but-no-op intermediate state.

2. **The `DaemonRunner.shutdown` body MUST transition lifecycle state through `"draining"` → `"stopped"` per ADR-0060 D335 invariant 3 (graceful-shutdown).** The `DaemonRunner` is a frozen dataclass per ADR-0060 D331; the per-pillar-H lifecycle transition is the internal allow-listed mutation site per the documented Python frozen-dataclass escape hatch (`object.__setattr__`). The Pillar H Week 3 body transitions state via `object.__setattr__(self, "lifecycle_state", new_state)`; operator/external mutation continues to refuse-loud via the dataclass's frozen `__setattr__`. The transitions span TWO emits per the per-pillar-H sequence: (1) transition to `"draining"` → emit `daemon_stopping` (with `drain_deadline_ts = now + graceful_shutdown_seconds` + `in_flight_task_count = 0` at Week 3 because the per-stage worker pool body lands at Week 5+) → (2) [Week 5+ extends with actual drain loop here] → (3) transition to `"stopped"` → emit `daemon_stopped` (with `exit_reason = "clean"` at Week 3 because no per-stage drain to time out; Week 5+ extends with `"timeout"` / `"crash"` path selection).

3. **The `build_daemon_stopping_payload` + `build_daemon_stopped_payload` emit-shape factories pin the canonical payload shape per the Pillar G `build_*_payload` convention.** Both factories mirror the Pillar H Week 2 `build_daemon_started_payload` precedent — raw-primitive factories with refuse-loud at construction time per the Pillar G `discovery_dedup.build_discovery_dedup_hit_payload` + Pillar H Week 2 follow-up P2-2 closure conventions. The `build_daemon_stopping_payload(pid, reason, drain_deadline_ts, in_flight_task_count)` validates `pid > 0` + `reason in SHUTDOWN_REASONS` + non-empty `drain_deadline_ts` + `in_flight_task_count >= 0`. The `build_daemon_stopped_payload(pid, exit_reason, uptime_seconds, in_flight_task_count_at_exit)` validates `pid > 0` + `exit_reason in DAEMON_EXIT_REASONS` + `uptime_seconds >= 0.0` + `in_flight_task_count_at_exit >= 0`. Both OMIT the `channel` field per ADR-0014 D33 (daemon lifecycle events are tenant-process-scoped, not per-channel). Both round `uptime_seconds` (the stopped factory) to 3 decimal places per ADR-0031 D140's deterministic-output contract.

4. **The `SHUTDOWN_REASONS` + `DAEMON_EXIT_REASONS` closed-sets pin the operator-deliberate vocabulary per the per-pillar mirror constants parity discipline.** `SHUTDOWN_REASONS = frozenset({"sigterm", "sigint", "operator_requested"})` captures the operator's INTENT (which signal/CLI surface initiated the shutdown). `DAEMON_EXIT_REASONS = frozenset({"clean", "timeout", "crash"})` captures the daemon's ACTUAL exit status (drain completed cleanly / drain timed out / crash-recovery path emit). The two closed-sets are deliberately disjoint — intent and outcome are operationally distinct in the same way Pillar G's `_SLO_NAMES` + `_DRIFT_REASONS` are mutually exclusive per ADR-0049 D263 + ADR-0056 D311. The closed-set discipline catches operator typos at the validator boundary + future Pillar I per-tenant extensions follow the same per-pillar mirror constants parity discipline.

Risks this ADR mitigates by design: **R005 / R016 / R023 / R033 / R037 / R038 / R039** all continue mitigated per ADR-0060 D335 + D336; the Week 3 body satisfies the graceful-shutdown structural commitment. The `attach_signal_handlers` body is the test-time barrier per the per-week-reviewer pattern — operators sending SIGTERM see the daemon transition to `"draining"` + emit `daemon_stopping`; the binding exit-criterion test at `test_multi_channel_coherence.py::TestPillarHDaemon::test_sigterm_triggers_draining_lifecycle_transition` un-skips at this Week 3 commit + pins the structural commitment at test time.

The Pillar G framework adoption surfaces preserve verbatim across this Week 3 commit. The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The Pillar D + E + F + G binding exit-criterion tests STAY GREEN. The brand-and-legal-liability invariant + the privacy invariant + the FIVE-layer hallucination-detection defense all hold with FULL weight. The Pillar H Week 1 + Week 1 follow-up + Week 2 + Week 2 follow-up surfaces preserve VERBATIM; Week 3 EXTENDS via NEW closed-sets + NEW factories + body fills.

## Decision

### D341. `attach_signal_handlers` body — asyncio signal handler wiring for SIGTERM + SIGINT + SIGHUP

`orchestrator/daemon/runner.py::attach_signal_handlers` body lands per the ADR-0060 D335 invariants 3 + 4 contract + ADR-0060 D332's asyncio framework decision:

```python
def attach_signal_handlers(
    runner: DaemonRunner,
    *,
    loop: Any | None = None,
    shutdown_fn: Callable[[str], None] | None = None,
    reload_fn: Callable[[], Any] | None = None,
) -> None:
    import asyncio
    import signal

    if loop is None:
        loop = asyncio.get_running_loop()
    if shutdown_fn is None:
        shutdown_fn = runner.shutdown
    if reload_fn is None:
        def _reload_with_notimpl_swallow() -> None:
            try:
                runner.reload_policy()
            except NotImplementedError:
                print(
                    "WARNING: SIGHUP received at Pillar H Week 3 trajectory; "
                    "DaemonRunner.reload_policy body lands at Pillar H "
                    "Week 7+ per ADR-0060 D332. SIGHUP is a no-op until then.",
                    file=sys.stderr,
                )
        reload_fn = _reload_with_notimpl_swallow

    loop.add_signal_handler(signal.SIGTERM, lambda: shutdown_fn("sigterm"))
    loop.add_signal_handler(signal.SIGINT, lambda: shutdown_fn("sigint"))
    if runner.config.policy_reload_signal == "SIGHUP":
        loop.add_signal_handler(signal.SIGHUP, reload_fn)
```

The body uses **operator-deliberate test seam kwargs** per the Pillar G TEST-ONLY convention + the Pillar H Week 2 `init_daemon` precedent — production callers (inside `DaemonRunner.run` at Week 5+) omit all kwargs; tests inject substrate loops + spy callables to verify signal-to-callback wiring without registering real OS signal handlers.

The SIGHUP handler's `NotImplementedError` swallow is the Week 3 → Week 7 trajectory bridge. The Week 7 author un-swallows + ships the actual `reload_policy` body per ADR-0060 D332's trajectory; the Week 7 commit removes the swallow + extends the handler to dispatch to `runner.reload_policy()` directly.

### D342. `DaemonRunner.shutdown` body — lifecycle transitions through `"draining"` → `"stopped"` via `object.__setattr__` + emit `daemon_stopping` + `daemon_stopped`

`orchestrator/daemon/runner.py::DaemonRunner.shutdown` body lands per the ADR-0060 D335 invariant 3 (graceful-shutdown) contract:

```python
def shutdown(
    self,
    reason: str,
    *,
    emit_fn: Callable[[dict], Any] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> None:
    if reason not in SHUTDOWN_REASONS:
        raise ValueError(...)
    if now_fn is None:
        now_fn = lambda: datetime.now(tz=timezone.utc)
    if emit_fn is None:
        from orchestrator.ledger import Ledger
        ledger = Ledger(self.config.ledger_dir)
        emit_fn = ledger.append

    # Step 1: transition to "draining" via frozen-dataclass escape hatch.
    object.__setattr__(self, "lifecycle_state", "draining")
    # Step 2: emit daemon_stopping.
    now = now_fn()
    drain_deadline = now + timedelta(seconds=self.config.graceful_shutdown_seconds)
    drain_deadline_ts = drain_deadline.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    emit_fn({
        "type": "daemon_stopping",
        **build_daemon_stopping_payload(
            pid=self.pid, reason=reason,
            drain_deadline_ts=drain_deadline_ts,
            in_flight_task_count=0,  # Week 5+ wires actual count.
        ),
    })
    # Step 3: [Week 5+ extends with drain loop here.]
    # Step 4: transition to "stopped".
    object.__setattr__(self, "lifecycle_state", "stopped")
    # Step 5: emit daemon_stopped.
    started_at = datetime.strptime(
        self.started_at_ts, "%Y-%m-%dT%H:%M:%S.%fZ",
    ).replace(tzinfo=timezone.utc)
    uptime_seconds = (now - started_at).total_seconds()
    emit_fn({
        "type": "daemon_stopped",
        **build_daemon_stopped_payload(
            pid=self.pid, exit_reason="clean",  # Week 5+ extends.
            uptime_seconds=uptime_seconds,
            in_flight_task_count_at_exit=0,  # Week 5+ wires actual count.
        ),
    })
```

The **`object.__setattr__` frozen-dataclass escape hatch** is the documented Python convention for internal allow-listed mutation of frozen dataclass fields (see Python docs `dataclasses` module). The frozen invariant continues to refuse-loud external/operator mutation via `FrozenInstanceError`; the per-pillar-H lifecycle transitions are the internal mutation site per this ADR's structural commitment. The cell-level matrix coverage discipline pins the lifecycle_state value at the intermediate `"draining"` emit + the final `"stopped"` emit via the spy emit_fn pattern at `tests/test_daemon.py::TestShutdownBody`.

The **test-only seam kwargs** (`emit_fn` + `now_fn`) extend the Pillar G TEST-ONLY convention to the shutdown body. Production callers inside the daemon event loop omit kwargs; the default `emit_fn` lazy-constructs `Ledger` from `runner.config.ledger_dir`; the default `now_fn` returns `datetime.now(tz=timezone.utc)`. Tests inject deterministic clocks + spy emit_fns to verify the intermediate state transitions + the emit payloads at construction time.

Week 3 ALWAYS emits `exit_reason="clean"` because the per-stage worker pool body lands at Week 5+ per ADR-0060 D332's trajectory — there are no in-flight tasks to drain at Week 3, so no path to `"timeout"` exists. Week 5+'s `DaemonRunner.run` body extends `shutdown` with the actual drain loop + the timeout/crash path selection per ADR-0062 D344. The crash-recovery path (`exit_reason="crash"`) is the backfill emit from a prior crash detected via Pass C+ per ADR-0014 D33 at Pillar H Week 10-11 per ADR-0060 D332's trajectory.

### D343. `build_daemon_stopping_payload` + `build_daemon_stopped_payload` emit-shape factories

Two NEW emit-shape factories at `orchestrator/daemon/runner.py` mirror the Pillar G `build_*_payload` convention per ADR-0010 D17 + the Pillar H Week 2 `build_daemon_started_payload` precedent:

```python
def build_daemon_stopping_payload(
    pid: int, reason: str,
    drain_deadline_ts: str, in_flight_task_count: int,
) -> dict[str, Any]:
    # Refuse-loud validation per Pillar H Week 2 follow-up P2-2 closure.
    if pid <= 0: raise ValueError(...)
    if reason not in SHUTDOWN_REASONS: raise ValueError(...)
    if not drain_deadline_ts: raise ValueError(...)
    if in_flight_task_count < 0: raise ValueError(...)
    return {
        "pid": pid, "reason": reason,
        "drain_deadline_ts": drain_deadline_ts,
        "in_flight_task_count": in_flight_task_count,
    }


def build_daemon_stopped_payload(
    pid: int, exit_reason: str,
    uptime_seconds: float, in_flight_task_count_at_exit: int,
) -> dict[str, Any]:
    if pid <= 0: raise ValueError(...)
    if exit_reason not in DAEMON_EXIT_REASONS: raise ValueError(...)
    if uptime_seconds < 0.0: raise ValueError(...)
    if in_flight_task_count_at_exit < 0: raise ValueError(...)
    return {
        "pid": pid, "exit_reason": exit_reason,
        "uptime_seconds": round(uptime_seconds, 3),
        "in_flight_task_count_at_exit": in_flight_task_count_at_exit,
    }
```

Both factories take RAW primitives (NOT frozen dataclasses with construction-time invariants) — so refuse-loud lives at the factory boundary per the Pillar G `discovery_dedup.build_discovery_dedup_hit_payload` precedent + the Pillar H Week 2 follow-up P2-2 closure convention. Both OMIT the `channel` field per ADR-0014 D33 (daemon lifecycle events tenant-process-scoped). The `type` field is set by the caller (the emitter in `DaemonRunner.shutdown` writes `{"type": "daemon_stopping", **build_..._payload(...)}` per the established Pillar D/E/F/G emit convention) and the `ts` field is auto-filled by `Ledger.append` per its `setdefault("ts")` contract.

**Pillar H Week 3 follow-up P2-1 correction** — the original D343 narrative claimed `_emitted_by` was "auto-filled by Ledger.append" but `Ledger.append` (orchestrator/ledger.py:393-397) only `setdefault`s `v` + `ts`. The `_emitted_by` audit-marker per ADR-0010 D17 is stamped at the factory boundary by EACH per-pillar factory per the established framework convention (the Pillar E `tier_assignment.build_tier_suggested_payload` factory sets `"_emitted_by": "tier_assignment"`; the Pillar E `discovery_lineage` factories set `"_emitted_by": "discovery_lineage"`; the Pillar G `observability` emit dicts set `"_emitted_by": "observability"`). The Pillar H Week 3 factories now mirror the convention via the NEW module-level `EMITTED_BY = "daemon"` constant at `orchestrator/daemon/runner.py` — the THREE factories (`build_daemon_started_payload` + `build_daemon_stopping_payload` + `build_daemon_stopped_payload`) include `"_emitted_by": EMITTED_BY` in their output. The Week 3 follow-up commit adds regression-barrier tests at `tests/test_daemon.py::TestDaemonStartedPayload::test_payload_carries_emitted_by_marker` + the equivalent at the two new factories + `TestModuleConstants::test_emitted_by_marker_is_daemon`. This was the SECOND ADR-vs-actual-impl drift in Pillar H (the FIRST was Week 2 follow-up P3-8 OTel Resource rationale); the per-week-reviewer's cross-pillar back-audit discipline EXTENDED to ADR-vs-actual-impl drift at Week 2 follow-up caught this drift in Week 3.

The factory shape pinning at Week 3 means the Week 5+ author wiring the actual drain + emit reuses the SAME factory; the cell-level matrix coverage discipline at `tests/test_daemon.py::TestDaemonStoppingPayload` + `::TestDaemonStoppedPayload` (8 + 8 = 16 cells; each closed-set enum × validation rule combination) is the structural barrier.

### D344. `SHUTDOWN_REASONS` + `DAEMON_EXIT_REASONS` closed-sets + the disjoint-closed-sets invariant

Two NEW closed-sets at `orchestrator/daemon/runner.py` per the per-pillar mirror constants parity discipline (introduced at Pillar G Week 10-11 + ADR-0058 D322 + extended at Pillar G Week 12 follow-up + Pillar H Week 1 follow-up + Week 2 follow-up):

```python
SHUTDOWN_REASONS: frozenset[str] = frozenset({
    "sigterm", "sigint", "operator_requested",
})

DAEMON_EXIT_REASONS: frozenset[str] = frozenset({
    "clean", "timeout", "crash",
})
```

The `SHUTDOWN_REASONS` captures operator INTENT — which signal/CLI surface initiated the shutdown:
- `"sigterm"` — systemd / k8s / orchestrator sent SIGTERM (the canonical graceful-shutdown signal per the POSIX convention).
- `"sigint"` — operator sent SIGINT (typically Ctrl+C); same graceful-shutdown semantics but distinguished in the emit for dashboard correlation.
- `"operator_requested"` — explicit `runner.shutdown("operator_requested")` call from a daemon CLI shutdown surface (Week 5+ scope) or programmatic shutdown.

The `DAEMON_EXIT_REASONS` captures daemon ACTUAL exit status — what happened during the drain:
- `"clean"` — drain completed within `graceful_shutdown_seconds`; all in-flight tasks finished; process exits with code 0. (Week 3 always emits `"clean"`; Week 5+ extends.)
- `"timeout"` — drain exceeded the deadline; in-flight tasks were cancelled; process exits with code 124 per the Pillar D Pass A through O exit code convention.
- `"crash"` — daemon process crashed; this value is emitted ONLY by the crash-recovery path through Pass C+ per ADR-0014 D33 at Pillar H Week 10-11. Process exits with code 1.

The two closed-sets are **deliberately disjoint** — the regression-barrier test `tests/test_daemon.py::TestShutdownReasons::test_disjoint_from_daemon_exit_reasons` pins the structural commitment. The same disjoint-closed-sets pattern as Pillar G's `_SLO_NAMES` ↔ `_DRIFT_REASONS` mutually-exclusive contract per ADR-0049 D263 + ADR-0056 D311; intent and outcome are operationally distinct.

Future Pillar I per-tenant audit-tooling MAY extend `SHUTDOWN_REASONS` with per-tenant reasons (e.g., `"tenant_quota_exceeded"`) per the per-pillar-foundation precedent + the per-pillar mirror constants parity discipline; the regression-barrier test at `tests/test_daemon.py::TestShutdownReasons` pins Pillar H Week 3 contents.

## Alternatives considered

### D341 alternatives (attach_signal_handlers body)

1. **Use `signal.signal()` instead of `loop.add_signal_handler()`.** Considered + REJECTED — `signal.signal()` does NOT integrate with asyncio's event loop; signal handlers run on the OS-thread-context where Python receives the signal, NOT on the asyncio loop. Asyncio operations from inside a `signal.signal()` handler are unsafe (`asyncio.get_event_loop()` may return wrong loop; calling `loop.create_task()` from outside the loop's thread context races). The asyncio framework decision per ADR-0060 D332 binds the daemon to asyncio's cooperative scheduling; `loop.add_signal_handler` is the canonical pattern.
2. **Skip the SIGHUP handler at Week 3; defer entire SIGHUP wiring to Week 7.** Considered + REJECTED — the per-week-handoff convention's "stub the trajectory at the foundation week + un-skip progressively" discipline binds; deferring SIGHUP wiring to Week 7 would leave a structural commitment gap at Week 3-6 (operators sending SIGHUP at Week 3-6 see Python's default handler — process termination — instead of the intended no-op-with-log). The Week 3 wires the handler; the Week 7 ships the actual reload body.
3. **Inline the NotImplementedError swallow at the lambda site instead of a named helper.** Considered + REJECTED — the named helper improves test introspection (the `reload_fn` test-only seam kwarg + the spy callable pattern needs a callable identity; a lambda with internal try/except is hard to spot-check); the per-week-reviewer's cell-level matrix coverage discipline asks for the named helper. The helper's logging at stderr provides operator-traceable signal flow.
4. **Make `attach_signal_handlers` accept an event loop param positionally (not via kwarg).** Considered + REJECTED — the kwarg-with-default pattern matches the Pillar G `set_global=False` + Pillar H Week 2 `init_daemon` test-only seam kwarg convention. Positional event loop would surface to operators as "this is a public API parameter" which it is not — the test-only seam status is operationally important.

### D342 alternatives (DaemonRunner.shutdown body)

1. **Use `dataclasses.replace` instead of `object.__setattr__` for lifecycle state transitions.** Considered + REJECTED — `dataclasses.replace` returns a NEW DaemonRunner instance; the caller (signal handler) holds a stale reference + the per-pillar-H lifecycle is split across instances. The `shutdown()` method's `-> None` signature is structurally inconsistent with returning the new runner. The Python frozen-dataclass docs explicitly bless `object.__setattr__` for internal allow-listed mutation; the frozen invariant continues to refuse-loud external mutation via the dataclass's frozen `__setattr__`.
2. **Make `DaemonRunner` non-frozen + use plain assignment.** Considered + REJECTED — the frozen invariant is the structural commitment from ADR-0060 D331 (the per-pillar-H dataclasses mirror Pillar G's frozen snapshot convention per ADR-0050 D272 + R033); making it non-frozen would allow operator/external mutation of `config_hash` / `pid` / `version` / `started_at_ts` — a privacy / determinism regression-barrier breach. `object.__setattr__` preserves the frozen invariant for the operator-visible fields while allowing internal lifecycle transitions.
3. **Track lifecycle state in a separate mutable holder (e.g., `_LifecycleHolder` with a `state: str` field).** Considered + REJECTED — adds dataclass shape complexity (DaemonRunner gains a non-frozen field) + violates the per-pillar mirror constants parity discipline (Pillar G's snapshot dataclasses are uniformly frozen). The `object.__setattr__` escape hatch is one line + matches Python idiom.
4. **Make `DaemonRunner.shutdown` async.** Considered + REJECTED at Week 3 — the actual drain loop (which would need `await asyncio.gather(...)`) lands at Week 5+ per ADR-0060 D332's trajectory. Week 3's sync body has no `await` points (state transition + emit are sync); making it async would force tests to wrap in `asyncio.run()` for no benefit. The Week 5+ author MAY extract an `_async_shutdown` helper if the drain loop requires async; the sync `shutdown` method's signature persists.

### D343 alternatives (build_daemon_stopping_payload + build_daemon_stopped_payload)

1. **Merge the two emits into one `daemon_lifecycle` event with a `transition` field.** Considered + REJECTED — operators querying per-event-class aggregations per ADR-0050 D272 expect per-event-class semantics (`daemon_stopping` count != `daemon_stopped` count when drain timeouts). The two-event shape matches the Pillar A two-phase commit precedent per ADR-0014 D33 (intent / confirmed pair semantics generalize to lifecycle / stopped pair).
2. **Add `channel` field to the daemon lifecycle event payloads.** Considered + REJECTED — daemon lifecycle events are tenant-process-scoped per ADR-0060 D335 invariant 1 (process-isolation), NOT per-channel. The channel-on-every-event invariant per ADR-0014 D33 applies at the dispatcher layer; the consumer surface treats absence as `None` per ADR-0050 D272. Pillar H Week 2's `build_daemon_started_payload` set the precedent; Week 3's two new factories follow.
3. **Skip refuse-loud validation in the factories; rely on caller-side validation.** Considered + REJECTED — the Pillar H Week 2 follow-up P2-2 closure pinned the raw-primitive factory convention (validation at the factory boundary, NOT at the caller). The Pillar G `discovery_dedup.build_discovery_dedup_hit_payload` precedent + the cell-level matrix coverage discipline (NINETEEN consecutive weeks pre-Week-3) bind. The Week 3 commit extends the discipline.
4. **Build the factories around a frozen dataclass input (e.g., `ShutdownContext`).** Considered + REJECTED — `shutdown()` is called with raw primitives (the `reason` string from the signal handler; the computed `drain_deadline_ts` + `in_flight_task_count`); constructing a frozen dataclass wrapper adds shape complexity without invariant gain. The raw-primitive factory pattern at Pillar G is the established convention.

### D344 alternatives (SHUTDOWN_REASONS + DAEMON_EXIT_REASONS)

1. **Use a single `SHUTDOWN_OUTCOMES` closed-set merging reasons + exit_reasons.** Considered + REJECTED — operator intent (`sigterm`) and daemon outcome (`clean`) are operationally distinct; merging breaks the disjoint-closed-sets invariant + makes per-event aggregations ambiguous (operators querying `count(reason="sigterm")` vs `count(exit_reason="clean")` need two distinct namespaces).
2. **Add `sigusr1` / `sigusr2` / etc. to `SHUTDOWN_REASONS` at Week 3.** Considered + REJECTED — Pillar H Week 3 ships only the THREE reasons the signal handler wires (SIGTERM / SIGINT / explicit shutdown). Pillar I per-tenant audit-tooling MAY extend; the per-pillar mirror constants parity discipline + the regression-barrier test pin Pillar H Week 3 contents.
3. **Use an `Enum` instead of a `frozenset[str]`.** Considered + REJECTED — the per-pillar closed-set convention at Pillar H Week 1 (DAEMON_LIFECYCLE_STATES + DAEMON_NEW_EVENT_CLASSES + HEALTH_PROBE_OUTCOMES) + Pillar H Week 1 follow-up (DAEMON_POLICY_RELOAD_SIGNALS + POLICY_RELOAD_STATUSES) uses `frozenset[str]`. Pillar G's `_SLO_NAMES` + `_DRIFT_REASONS` similarly. Enum would surface as `SHUTDOWN_REASONS.SIGTERM.value == "sigterm"` — operator-confusing vs the closed-set's direct string semantics.

## Consequences

### Positive

- **The graceful-shutdown structural commitment per ADR-0060 D335 invariant 3 is OPERATIONAL.** Operators sending SIGTERM see the daemon transition to `"draining"` + emit `daemon_stopping` → `"stopped"` + emit `daemon_stopped` per the binding-question test `test_sigterm_triggers_draining_lifecycle_transition` at `test_multi_channel_coherence.py::TestPillarHDaemon`.
- **The per-pillar mirror constants parity discipline EXTENDS via TWO NEW closed-sets** (`SHUTDOWN_REASONS` + `DAEMON_EXIT_REASONS`) — Pillar H Week 1 main shipped THREE closed-sets; Week 1 follow-up added TWO (5 total); Week 3 adds TWO (7 total). The closed-set discipline catches operator typos at the validator boundary + at the factory boundary; Pillar I per-tenant extensions follow the same pattern.
- **The cell-level matrix coverage discipline EXTENDS via the +36 net new daemon tests** (102 → 138 contract tests at test_daemon.py; 1 new un-skipped binding-question test at test_multi_channel_coherence.py — NINETEEN consecutive weeks pre-Week-3 → TWENTY at this Week 3 commit).
- **The behavioral-passthrough-not-signature-only discipline EXTENDS via the spy emit_fn pattern** at `TestShutdownBody` — the spy captures the runner's `lifecycle_state` at emit-time so the test verifies the intermediate `"draining"` state matches the structural commitment. Same pattern as Pillar H Week 2's `TestInitDaemonBody::test_startup_ordering_invariant_per_adr_0061_d340_P3_1` `call_order` spy.
- **The Pillar G framework adoption surfaces preserve verbatim** — the daemon CONSUMES OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + cost aggregation + per-Person observability surface adapters + funnel CLI extension at Week 5+. The Week 3 commit does NOT touch the consumer-side surfaces.

### Negative

- **The `object.__setattr__` frozen-dataclass escape hatch is operator-confusing without the ADR explanation.** A future per-week reviewer or Pillar I author reading the `shutdown` body sees `object.__setattr__(self, "lifecycle_state", "draining")` + may interpret as a violation of the frozen invariant. The ADR-0062 D342 narrative + the regression-barrier test at `tests/test_daemon.py::TestShutdownBody` pin the structural commitment + the documented Python convention; the per-week-reviewer pattern's cross-pillar back-audit discipline catches drift at test time. The mitigation: explicit comment at the `object.__setattr__` site naming "ADR-0062 D342 frozen-dataclass escape hatch."
- **The SIGHUP handler at Week 3 is wired-but-no-op until Week 7.** Operators sending SIGHUP at Week 3-6 see a stderr log + no policy reload. The structural commitment is the handler attachment + the Week 7 trajectory; the per-week-handoff convention's "stub the trajectory at the foundation week + un-skip progressively" discipline binds.
- **The Week 3 `shutdown` body's `exit_reason` always emits `"clean"`.** A future per-week reviewer reading the body sees the hard-coded `"clean"` + may interpret as missing the timeout/crash path selection. The Week 5+ author extends with the actual drain loop + path selection per ADR-0060 D332; the Week 10-11 author extends with the crash-recovery backfill per ADR-0060 D332. The mitigation: explicit comment at the `exit_reason="clean"` site naming the Week 5+ trajectory.

### Neutral

- **No new pip dependencies at Pillar H Week 3.** The body uses stdlib (`asyncio` + `signal` + `datetime`) + the Pillar G OTel SDK deps already wired at Week 3 baseline.
- **No new ledger migrations at Pillar H Week 3.** Pending count stays at 19 (UNCHANGED from Pillar G Week 12 + Pillar H Week 1 + Week 1 follow-up + Week 2 + Week 2 follow-up).
- **No new R-risks at Pillar H Week 3.** The existing R031-R039 mitigations carry through verbatim.
- **No new event classes.** The FIVE Pillar H event classes from `DAEMON_NEW_EVENT_CLASSES` joined `EVENT_CLASS_CATALOG` at Pillar H Week 2 per ADR-0061 D338; Week 3 wires the actual emit at `shutdown` body (two of the five — `daemon_stopping` + `daemon_stopped`).
- **No changes to the binding exit-criterion tests of Pillar D / E / F / G.** All four STAY GREEN across the Pillar H Week 3 commit.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — the daemon's lifecycle events emit to the ledger; the ledger remains the source of truth. The `build_daemon_stopping_payload` + `build_daemon_stopped_payload` factory outputs exclude `person_id` / body content / source_list per the privacy invariant.
- **I2 (Atomicity contract).** Compliant + EXTENDED — D342's lifecycle transition through `"draining"` → `"stopped"` preserves the atomicity-preservation-across-process-boundary invariant per ADR-0060 D335 invariant 2; per-channel two-phase intent/confirmed pairs continue to complete via reconcile loop at Pass A through O.
- **I3 (Single source of truth).** Compliant — `SHUTDOWN_REASONS` + `DAEMON_EXIT_REASONS` are the SoT for shutdown reason + exit reason vocabularies; per-pillar mirror constants parity pins parity at test time.
- **I4 (Determinism).** Compliant — `build_daemon_stopped_payload` rounds `uptime_seconds` to 3 decimal places per ADR-0031 D140; the drain_deadline_ts format matches the ms-precision Z-suffix convention from `_utc_iso_now`.
- **I5 (Refuse loud).** Compliant — `DaemonRunner.shutdown` refuses-loud via `ValueError` on `reason not in SHUTDOWN_REASONS`; both factories refuse-loud per the Pillar H Week 2 follow-up P2-2 closure convention.
- **I6 (No silent state).** Compliant — lifecycle transitions emit `daemon_stopping` + `daemon_stopped` events at every state change; the emit_fn seam permits test verification but production callers see all transitions in the ledger.
- **I7 (Refuse loud on broken pipelines).** Compliant — invalid shutdown reason refuses-loud BEFORE the state transition fires (regression-barrier at `TestShutdownBody::test_invalid_reason_refuses_loud_before_state_transition`).
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — the `daemon_stopping` + `daemon_stopped` payloads contain pid + reason + drain_deadline_ts + in_flight_task_count / exit_reason + uptime_seconds + in_flight_task_count_at_exit; NEVER `person_id` / body content / source_list.
- **The channel-on-every-event invariant per ADR-0014 D33** — Unaffected — both new event classes are daemon-lifecycle events WITHOUT channel context; the per-channel two-phase commit invariant preserves verbatim at the dispatcher layer.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — the daemon does NOT modify the per-send gate.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — the daemon does NOT modify the Layer 1-5 surfaces.
- **The one-CLI-invocation invariant per ADR-0050 D276(a)** — Preserved — operators invoking `python orchestrator/funnel.py --since N` from outside the daemon get the same byte-identical output per ADR-0031 D140.
- **The READ-ONLY funnel CLI contract per ADR-0059 D325** — Preserved — the daemon does NOT modify `funnel.build_report`.
- **The byte-identical determinism contract per ADR-0031 D140** — Preserved — `round(uptime_seconds, 3)` preserves byte-identical output across consecutive emits for identical input.

## Downstream pillar impact

- **Pillar I (OSS bring-up + multi-tenant).** Per-tenant fan-out at the daemon process boundary — Pillar I authors may extend `SHUTDOWN_REASONS` with per-tenant reasons (e.g., `"tenant_quota_exceeded"`) via the per-pillar mirror constants parity discipline; the regression-barrier test pins Pillar H Week 3 contents + Pillar I author extends both the closed-set + the test concurrently. Per-tenant fan-out at SIGTERM: operators wanting per-tenant graceful shutdown wire one daemon process per tenant per ADR-0060 D335 invariant 1; SIGTERM signals the per-tenant daemon process directly. Per-tenant audit-tooling: the `daemon_stopping` + `daemon_stopped` event classes join the per-Person observability surface adapters; Pillar I author MAY add a per-tenant `tenant_id` field to the payloads via the per-pillar mirror constants parity discipline (Pillar I extension adds `tenant_id` + the regression-barrier test pins the extension).
- **Pillar J (Security + compliance).** The daemon's graceful-shutdown path preserves the GDPR-purge transaction per ADR-0050 §Downstream — operator triggering GDPR purge sees the daemon transition to `"draining"` + complete in-flight purges within `graceful_shutdown_seconds` + emit `daemon_stopped` with `exit_reason="clean"`. SLSA supply-chain attestation per Pillar J extends to the daemon's shutdown emit — the `_DAEMON_VERSION` constant + the emit's per-pillar mirror constants parity discipline preserve verbatim.

## Migration / rollout

- **Operator-side action required at Pillar H Week 3 upgrade:** **NONE — content-additive at the framework boundary.** The Week 3 commit adds the `attach_signal_handlers` body + the `DaemonRunner.shutdown` body + the TWO new factories + the TWO new closed-sets + the regression-barrier tests. Operators continue to invoke `python orchestrator/funnel.py --since N` + the per-skill `claude /find-leads` / `/research-prospect` / `/draft-outreach` / `/send-outreach` surfaces unchanged.
- **Recommended (optional):** operators wanting to PREVIEW the Pillar H daemon shutdown invoke `from orchestrator.daemon import init_daemon, DaemonConfig; r = init_daemon(DaemonConfig(...)); r.shutdown("operator_requested")` to see the daemon_stopping + daemon_stopped events emit to the ledger. The actual production daemon (event loop + per-stage worker pool) lands at Pillar H Week 5+.
- **No ledger schema migration** — Week 3 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new pip dependencies at Pillar H Week 3** — the body uses stdlib (`asyncio` + `signal` + `datetime`).

## Existing-operator seed

Operator action required at Pillar H Week 3: **NONE — content-additive at the framework boundary.**

Recommended (optional): operators following the Pillar H per-week trajectory consume the per-week handoff docs at `.planning/HANDOFF-pillar-h-week-N.md` + the per-week ADRs at `docs/adr/006N-pillar-h-week-N-*.md`. Operators wanting the Pillar H daemon-as-systemd-service wait for Pillar H Week 5+ per ADR-0060 D332's trajectory.

## References

- **ADR-0061** (Pillar H Week 2 — `init_daemon` body + EVENT_CLASS_CATALOG extension + `build_daemon_started_payload` factory + Week 1 P3-1 + P3-2 carry-forward closures). D337-D340. **D339's `build_daemon_started_payload` factory shape is the Pillar H Week 3 precedent for `build_daemon_stopping_payload` + `build_daemon_stopped_payload`; the raw-primitive factory convention per the Pillar H Week 2 follow-up P2-2 closure extends.**
- **ADR-0060** (Pillar H Week 1 foundation — daemon module shape + closed-sets + dataclasses + signatures + cross-pillar audit + exit-criterion vehicle + load-bearing invariants + per-event-class indexing trajectory). D331-D336. **D335 invariant 3 (graceful-shutdown) is the structural commitment this Week 3 body satisfies; D332's asyncio framework decision binds the signal handler wiring to `loop.add_signal_handler`.**
- **ADR-0058** (Pillar G Week 10-11 — per-pillar mirror constants parity discipline + cross-pillar `_DRIFT_REASONS` consumption + Layer 5 BOTH-reasons-present invariant). D319-D324. **D322's per-pillar mirror constants parity discipline EXTENDS via Pillar H Week 3's TWO new closed-sets (SHUTDOWN_REASONS + DAEMON_EXIT_REASONS).**
- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector + `slo_violation_detected` producer + Slack webhook). D307-D313. **D311's `_recovered_by` synthetic-event exclusion preserves verbatim across the daemon.**
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. **The per-pillar-foundation precedent extends to Pillar H Week 3.**
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. **D263's disjoint-closed-sets pattern (_SLO_NAMES ↔ _DRIFT_REASONS) generalizes to Pillar H Week 3's SHUTDOWN_REASONS ↔ DAEMON_EXIT_REASONS.**
- **ADR-0031** (Pillar D Week 12 — funnel CLI deterministic-output contract). D140. **The `build_daemon_stopped_payload` factory's `round(uptime_seconds, 3)` preserves byte-identical output per the determinism contract.**
- **ADR-0014** (Pillar C foundation — channel-on-every-event invariant). D33. **The `daemon_stopping` + `daemon_stopped` payloads OMIT the `channel` field per the daemon-lifecycle-events-are-tenant-process-scoped rationale.**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). **The THREE Pillar H factories (`build_daemon_started_payload` + `build_daemon_stopping_payload` + `build_daemon_stopped_payload`) mirror the 10+ per-event factory convention; each factory stamps `"_emitted_by": EMITTED_BY` at the factory boundary (where `EMITTED_BY = "daemon"` is the module constant at `orchestrator/daemon/runner.py`) per the Pillar E `tier_assignment.EMITTED_BY` + `discovery_lineage.EMITTED_BY` precedent + the Pillar H Week 3 follow-up P2-1 closure. The `type` field is set by the caller; the `ts` field is auto-filled by `Ledger.append` via its `setdefault("ts")` contract.**
- **ADR-0001** (Pillar A foundation — declarative policy engine). D2 (refuse-loud convention). **The shutdown body refuses-loud at every invalid input per the framework convention.**
- `.planning/REVIEW-pillar-h-surface-audit.md` — cross-pillar surface audit (Pillar H Week 1 baseline; Week 2 + Week 2 follow-up + Week 3 extensions at this commit per the per-week-handoff convention).
- `.planning/HANDOFF-pillar-h-week-3.md` — Pillar H Week 3 close summary + handoff to Pillar H Week 4 (this commit; gitignored).
- `docs/PILLAR-PLAN.md` §2 Pillar H + §6 Pillar H row Week 3 status flip + Notes column appended Week 3 close summary.
- `orchestrator/daemon/runner.py` (Week 3 body) — `attach_signal_handlers` body + `DaemonRunner.shutdown` body + `build_daemon_stopping_payload` + `build_daemon_stopped_payload` + `SHUTDOWN_REASONS` + `DAEMON_EXIT_REASONS` per D341 + D342 + D343 + D344.
- `orchestrator/daemon/__init__.py` — re-exports the new closed-sets + factories; `__all__` extension (13 → 17 names).
- `tests/test_daemon.py` — `TestShutdownReasons` × 4 NEW + `TestDaemonExitReasons` × 3 NEW + `TestDaemonStoppingPayload` × 8 NEW + `TestDaemonStoppedPayload` × 8 NEW + `TestShutdownBody` × 7 NEW + `TestAttachSignalHandlers` × 6 NEW + `TestDaemonRunner::test_shutdown_signature_raises_not_implemented_at_week_1` RENAMED + INVERTED to `test_shutdown_rejects_invalid_reason` + `TestPrimitiveSignatures::test_attach_signal_handlers_raises_not_implemented_at_week_1` RENAMED + INVERTED to `test_attach_signal_handlers_requires_running_event_loop` + `TestPublicSurface` updated with 4 new exports.
- `tests/test_multi_channel_coherence.py` — `TestPillarHDaemon::test_sigterm_triggers_draining_lifecycle_transition` un-skipped + body lands.
