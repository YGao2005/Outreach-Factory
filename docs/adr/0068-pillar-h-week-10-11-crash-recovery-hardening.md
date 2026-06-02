# ADR-0068: Pillar H Week 10-11 — crash recovery hardening via `daemon_stopped` synthesis at `init_daemon` Step 4.5 + operator-deliberate reconcile pre-flight pass at Step 4.6 + `kill -9` test substrate

## Status

Accepted — 2026-05-27.

## Context

Per ADR-0060 D332's per-week trajectory table, Pillar H Week 10-11 ships crash recovery hardening — `kill -9` test substrate + reconcile loop integration + Pass A/B/C tightening. Per ADR-0060 D335 invariant 2 (atomicity-preservation-across-process-boundary):

> The ledger's append-only contract per I2 holds across daemon restarts. The per-channel two-phase intent/confirmed pairs per ADR-0014 D33 still complete via the reconcile loop (Pass A through O) if the daemon crashes between phases. The daemon contributes NO new state that bypasses the ledger.

The Week 3 commit per ADR-0062 D344 pinned `DAEMON_EXIT_REASONS = frozenset({"clean", "timeout", "crash"})` and reserved the `"crash"` value for emission ONLY when a crash-recovery path through Pass C+ per ADR-0014 D33 backfills the `daemon_stopped` event from a prior crash. Week 10-11 is the trajectory's commitment to operationally land that backfill.

The Week 9 commit per ADR-0067 D362-D363 shipped the per-event-class index invalidation on `Ledger.append` via the `Ledger.append_observer` post-fsync seam + the `outreach_factory_daemon_index_last_updated_timestamp` operator-visible freshness gauge. The Week 9 follow-up commit caf03ce per W9 follow-up P2-1 closure caught the **EIGHTH consecutive ADR-vs-actual-impl drift in Pillar H** (Step 9/Step 10 narrative-vs-code drift; W9 main claimed "renumbered Step 10" but actual code labels Step 9 — no renumber occurred; narrative-only drift CLOSED via correction). The per-week-reviewer pattern's structural value is empirically validated at EIGHT consecutive Pillar H weeks of ADR-vs-actual-impl drift catches (W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2 → W7 P1-1 → W8 follow-up P2-1 → W9 follow-up P2-1). The Week 10-11 author cross-checks every ADR-0068 narrative claim vs actual implementation before commit; the Week 10-11 per-week-reviewer catches any NINTH drift.

The crash-recovery design space:

1. **Failure-mode taxonomy at the daemon process boundary** — what counts as a "crash"?
   - **Ungraceful exit BEFORE the first fsync** (e.g., `kill -9` between `init_daemon` Step 3's PID resolution and `run()` Step 3's `daemon_started` emit) — no ledger event exists for this daemon; no crash detection possible by ledger walk; recovery is N/A because no in-flight state was persisted.
   - **Ungraceful exit AFTER `daemon_started` BUT BEFORE `daemon_stopping`** — the canonical "daemon crashed mid-tick" case. The ledger has `daemon_started(pid=P)` but no matching `daemon_stopped(pid=P)`. Detection: the next daemon's startup walks the ledger, finds the unmatched `daemon_started`, synthesizes `daemon_stopped(pid=P, exit_reason="crash", _recovered_by="reconcile")`.
   - **Ungraceful exit AFTER `daemon_stopping` BUT BEFORE `daemon_stopped`** — the daemon was draining and crashed mid-drain. The ledger has `daemon_started(pid=P)` + `daemon_stopping(pid=P)` but no matching `daemon_stopped(pid=P)`. Detection identical to case 2; synthesis identical (the `daemon_stopping` event preserves operator-visible context — the daemon's INTENT was clean shutdown but the actual OUTCOME was a crash).
   - **Ungraceful exit DURING `reload_policy`** — the Pillar H Week 7 reload body's atomicity contract per ADR-0066 D356 ensures the held `_PolicyState` instance either has the prior rules OR the new rules; a crash mid-reload preserves the prior `_PolicyState` until the daemon restarts (the policy YAML on disk is the source of truth; the daemon restart re-loads from disk at `init_daemon` Step 5).
   - **Ungraceful exit BETWEEN `send_intent` AND `send_confirmed`** — the Pillar D Pass A's existing recovery surface per ADR-0014 D33 + ADR-0015 handles this. The orphan `send_intent` is detected by `Ledger.open_intents()` at the next reconcile invocation; Pass A queries Gmail for the intent_id + synthesizes `send_confirmed` OR `send_aborted` per the existing 5-minute grace window. The W10-11 commit's crash-recovery synthesis at the daemon level is COMPLEMENTARY to Pass A's per-channel recovery — together they cover the daemon-lifecycle + the per-channel-state recovery surfaces.

2. **Crash detection location** — where in `init_daemon` does the synthesis fire?

   The synthesis MUST run BEFORE the per-stage worker pool starts (so the worker pool sees the post-recovery state) and BEFORE the index materialization at Step 8 (so the indexes include the synthesized `daemon_stopped` events). After Step 4 (migrations applied; ledger schema current) and BEFORE Step 5 (policy load). Step 4.5 is the canonical insertion point — symmetric with Step 8.5 (W9 invalidation observer install) + Step 9.5 (W9 gauge registration) per the per-pillar-H half-step convention.

3. **Pass A pre-flight invocation trajectory** — when does the daemon auto-run the reconcile loop?

   The W10-11 commitment per ADR-0060 D332 is "reconcile loop integration". The simplest design is: NEW operator-deliberate config field `DaemonConfig.reconcile_passes_at_startup: str | None = None` (default None = no pre-flight reconcile; operators set to `"A"` or `"A,B,D,E,F,H,I,J"` to invoke specific passes at startup). When set, `init_daemon` Step 4.6 invokes `reconcile.reconcile(passes=value, apply=True, ...)` synchronously BEFORE the per-stage worker pool starts. Default None preserves the test substrate (no Gmail mocking needed unless operator opts in); production operators wanting auto-recovery set `reconcile_passes_at_startup="A"` per the §Existing-operator seed.

4. **`kill -9` test substrate strategy** — fork+kill or synthesized state?

   Two options:
   - **Real fork+kill**: spawn a subprocess running `init_daemon` + `runner.run()`, send `os.kill(pid, signal.SIGKILL)`, then start a fresh daemon in the same ledger directory. Brittle in CI (timing-dependent; subprocess + asyncio + signal-handling combination is fragile across CI environments + Python versions); the test substrate's value is the failure-mode coverage, not the literal process-spawn mechanism.
   - **Synthesized crash state**: pre-seed the ledger with a `daemon_started(pid=P)` event for a fake PID with NO matching `daemon_stopped(pid=P)`, then invoke `init_daemon` in the same ledger directory + verify the synthesis fires. Captures the exact failure mode at the ledger level without subprocess complexity.

   W10-11 ships the synthesized-state substrate (faster + more reliable + same failure-mode coverage); the W12 binding exit-criterion test MAY layer a real fork+kill on top for end-to-end verification.

5. **Audit-marker convention per ADR-0010 D17 + R032 synthetic-event exclusion** — the synthesized `daemon_stopped` events MUST carry `_recovered_by="reconcile"` so the Pillar G observability primitives + the funnel CLI's READ-ONLY aggregation per ADR-0059 D325 surface them as recovery synthesis, not operator-emitted events. The R032 synthetic-event exclusion at Pillar G Week 7-8's SLO violation detector per ADR-0056 D311 already filters events with `_recovered_by` set — the W10-11 synthesis preserves that filter behavior verbatim.

The per-pillar-foundation precedent for the W10-11 commit shape matches Pillar G Week 7-8's ADR-0056 D307-D313 + Pillar H Week 8-9's ADR-0067 D359-D363 — multi-decision ADR shipping the structural commitment + the failure-mode taxonomy + the test substrate + the operator-deliberate opt-in surface within a single per-pillar-week commit. The per-week-reviewer's checklist at THIRTY-THREE consecutive weeks of cell-level matrix coverage applies; the cross-pillar back-audit at EIGHT consecutive Pillar H weeks of ADR-vs-actual-impl drift catches sets the bar for the W10-11 author's ADR-vs-impl alignment before commit.

## Decisions

### D364. Crash-recovery synthesis at `init_daemon` Step 4.5 — `_recover_from_prior_crash` helper synthesizes `daemon_stopped(exit_reason="crash", _recovered_by="reconcile")` for unmatched prior `daemon_started` events

**The structural commitment**: a daemon process is detected as crashed when the ledger has a `daemon_started(pid=P)` event without a matching subsequent `daemon_stopped(pid=P)` event. The next daemon's `init_daemon` startup synthesizes the missing `daemon_stopped` for each such crashed daemon.

**Where the synthesis fires**: `init_daemon` Step 4.5 (NEW; inserted between Step 4's migration apply + Step 5's policy load). Rationale:
- AFTER Step 4 (migrations applied) — the ledger schema is current; the walk doesn't trip on stale migrations.
- BEFORE Step 5 (policy load) — a policy parse error doesn't prevent crash-recovery synthesis; the recovery completes BEFORE any operator-visible policy state is constructed.
- BEFORE Step 8 (index materialization) — the synthesized `daemon_stopped` events flow into the indexes naturally; subsequent index-age + per-event-class queries surface the crash-recovery events without special handling.

**The synthesis helper signature**:

```python
def _recover_from_prior_crash(
    *,
    led: _Ledger,
    current_pid: int,
    now_fn: Callable[[], datetime] | None = None,
    emit_fn: Callable[[dict], dict] | None = None,
) -> int:
    """Synthesize ``daemon_stopped`` events for crashed prior daemons.

    Walks the ledger for ``daemon_started`` events lacking matching
    ``daemon_stopped`` events (matched by ``pid``). For each unmatched
    ``daemon_started``, synthesizes a ``daemon_stopped`` event with:

    * ``exit_reason="crash"`` per :data:`DAEMON_EXIT_REASONS`
    * ``pid`` = prior daemon's PID (from ``daemon_started`` payload)
    * ``uptime_seconds`` = (last_observed_ts_for_pid - started_at_ts);
      surfaces ``0.0`` if no later events exist for the prior PID
    * ``in_flight_task_count_at_exit=0`` (cannot be reconstructed from
      ledger walk; operator-visible v1 surface is the synthesis-time
      placeholder; Pillar I per-tenant audit-tooling MAY extend with
      reconciliation against the per-tenant work queue)
    * ``_recovered_by="reconcile"`` audit marker per ADR-0010 D17;
      excludes the synthesized event from R032 SLO aggregation per
      ADR-0056 D311's synthetic-event filter
    * ``_recovered_for_pid`` field naming the prior PID being recovered
      (for operator-visible cross-reference); the same value as ``pid``
      but semantically explicit ("this synthesis ran for the prior
      daemon whose PID is P")

    Skips the current daemon's PID (the current daemon has not emitted
    its own ``daemon_started`` yet at Step 4.5).

    Args:
        led: the daemon's :class:`Ledger` instance (lazy-constructed at
            Step 4.5 if not already constructed at Step 8). The walk is
            O(N) at startup; v2 scale ~100K events surfaces as ~10s
            startup latency (operator-acceptable for the recovery
            structural value).
        current_pid: the current daemon's PID (excluded from synthesis
            candidate set).
        now_fn: test-only seam — returns current datetime for the
            ``ts`` stamp on the synthesized event. Default
            ``lambda: datetime.now(tz=timezone.utc)``.
        emit_fn: test-only seam — emit function for the synthesized
            event. Default ``led.append``.

    Returns:
        Count of recovered crashes (number of ``daemon_stopped`` events
        synthesized). Zero means no prior crashes detected (the v1
        clean-restart case).
    """
```

**Failure-mode taxonomy** (see Context section above) — the helper covers cases (2) and (3); case (1) is N/A by construction (no ledger event); case (4) is handled by the Week 7 `reload_policy` atomicity contract; case (5) is handled by Pass A's existing recovery surface (the W10-11 commit's D366 wires Pass A pre-flight invocation as an operator-deliberate opt-in).

**Atomicity contract per ADR-0060 D335 invariant 2** — the synthesis fires `led.append({"type": "daemon_stopped", **build_daemon_stopped_payload(...), "_recovered_by": "reconcile", "_recovered_for_pid": prior_pid})` per the existing emit-shape factory + the standard audit-marker discipline. The W9 post-append observer seam fires for the synthesis (the per-event-class index gets updated; the freshness gauge advances) — verified at the regression-barrier test `test_synthesis_fires_w9_observer_per_w10_11_d364`.

**Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323** — the synthesized event payload contains pid + exit_reason + uptime_seconds + in_flight_task_count_at_exit + audit markers. NO `person_id` / body content / source_list. The Pillar H per-week-reviewer's privacy invariant check applies at the W10-11 commit.

**Byte-identical determinism contract per ADR-0031 D140** — the synthesis is deterministic given a fixed ledger state: walking the ledger for unmatched `daemon_started` events is a pure function of the ledger contents; the synthesized `daemon_stopped` event's `ts` is the synthesis-time stamp (NOT the prior daemon's crash-time stamp, which is unknown). Operators querying the ledger see the synthesis-time stamp; cross-daemon-process consistency holds at the per-process granularity.

### D365. `kill -9` test substrate at `tests/test_multi_channel_coherence.py` — un-skips `test_recovers_from_kill_9_via_reconcile` via synthesized crash state

**The W11 stub un-skipped** at `tests/test_multi_channel_coherence.py::TestPillarHDaemon::test_recovers_from_kill_9_via_reconcile`. The W12 binding exit-criterion stub (`test_daemon_24h_run_zero_anomalies_recovers_from_kill_9_reloads_policy`) stays skipped at W10-11; the W12 author un-skips at the Stable flip week per ADR-0060 D332 trajectory.

**The substrate strategy**: synthesized crash state (NOT real fork+kill). Pre-seed the ledger with a `daemon_started(pid=fake_pid)` event for a fake PID with NO matching `daemon_stopped`. Invoke `init_daemon` in the same ledger directory with a different PID via the `pid_fn` test-only seam. Verify:

1. The ledger now contains a synthesized `daemon_stopped(pid=fake_pid, exit_reason="crash", _recovered_by="reconcile")` event for the prior PID.
2. The new daemon's subsequent operations (e.g., emitting its own events via `runner.ledger.append`) succeed — the daemon is in a "ready-to-emit" state after Step 4.5 + onward.
3. The W9 observer fires for the synthesis — the post-Step-8 index materialization includes the synthesized event in the `daemon_stopped` bucket.

**Why synthesized state over real fork+kill**: subprocess + asyncio + signal-handling combination is brittle in CI (timing-dependent; varies across Python versions + OS schedulers). The synthesized-state substrate captures the exact ledger-level failure mode without subprocess complexity. The W12 binding exit-criterion test MAY layer a real fork+kill on top for end-to-end verification (the W12 author decides based on CI substrate readiness).

**Test cell-level coverage** per the THIRTY-THREE-consecutive-weeks discipline: the W10-11 contract tests at `tests/test_daemon.py` cover the unit-test scope (8+ tests covering empty ledger no-op + unmatched `daemon_started` synthesis + matched `daemon_started` skip + current PID excluded + audit markers + uptime computation + multiple crashes + ledger observer fires). The coherence test at `test_multi_channel_coherence.py` covers the integration scope (the full `init_daemon` path + the operator-visible recovery surface).

### D366. Operator-deliberate reconcile pre-flight pass at `init_daemon` Step 4.6 via NEW `DaemonConfig.reconcile_passes_at_startup: str | None = None` field

**The structural commitment per ADR-0060 D335 invariant 2's R037 mitigation**: the reconcile loop is the recovery backstop for in-flight per-channel two-phase intent/confirmed pairs. The W10-11 commit wires the reconcile loop's pre-flight invocation as an operator-deliberate config option; operators on production opt-in via `reconcile_passes_at_startup="A"` (or a broader pass set) to recover orphan `send_intent` events on every daemon restart.

**The NEW DaemonConfig field**:

```python
@dataclass(frozen=True)
class DaemonConfig:
    ...
    #: Pillar H Week 10-11 — optional reconcile pass list to invoke
    #: at daemon startup AFTER crash-recovery synthesis (Step 4.5)
    #: + BEFORE policy load (Step 5). Default ``None`` = no pre-flight
    #: reconcile (test substrate + dev path; no Gmail / LinkedIn /
    #: Twitter SDK calls at startup). Operators on production set to
    #: ``"A"`` (Gmail intent recovery only) or ``"A,B,D,E,F,H,I,J"``
    #: (the full intent-recovery pass set per ADR-0014/0017/0018/0027).
    #: When set, ``init_daemon`` Step 4.6 invokes
    #: :func:`reconcile.reconcile(passes=value, apply=True, ...)`
    #: synchronously; failures log to stderr + do NOT prevent daemon
    #: startup (the reconcile loop's per-tick invocation via the
    #: Pillar H Week 7 dispatch_fn IS the structural backstop;
    #: pre-flight is operator convenience).
    reconcile_passes_at_startup: str | None = None
```

**The Step 4.6 wiring**:

```python
# Step 4.6: NEW per ADR-0068 D366 — operator-deliberate reconcile
# pre-flight pass invocation per ADR-0060 D335 invariant 2's R037
# mitigation. Runs AFTER Step 4.5's crash-recovery synthesis +
# BEFORE Step 5's policy load. Default config.reconcile_passes_at_startup
# is None (test substrate + dev path); production operators set to
# "A" or broader pass set for auto-recovery of orphan send_intents.
if config.reconcile_passes_at_startup is not None:
    if reconcile_at_startup_fn is None:
        from orchestrator import reconcile as _reconcile  # noqa: PLC0415
        reconcile_at_startup_fn = _reconcile.reconcile
    try:
        reconcile_at_startup_fn(
            passes=config.reconcile_passes_at_startup,
            ledger_dir=config.ledger_dir,
            apply=True,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort pre-flight
        print(
            f"WARNING: init_daemon reconcile pre-flight pass "
            f"{config.reconcile_passes_at_startup!r} failed "
            f"({type(exc).__name__}: {exc}); the daemon continues "
            f"startup. The per-tick reconcile dispatch via Pillar H "
            f"Week 7's dispatch_fn IS the structural backstop. Per "
            f"ADR-0068 D366.",
            file=sys.stderr,
        )
```

**Best-effort posture rationale** — Pass A queries Gmail; transient Gmail API failures (rate-limit / network blip / SDK initialization race) MUST NOT prevent daemon startup. The per-tick reconcile dispatch via Pillar H Week 7's `dispatch_fn` is the structural backstop — orphan intents detected at startup but not recovered will surface at the next per-tick `send` stage dispatch (the dispatch_fn invokes `reconcile.reconcile(passes="A,B")` via `_STAGE_TO_PASSES`). The pre-flight invocation is operator-convenience for immediate recovery on restart, not a correctness contract.

**Test-only seam** `reconcile_at_startup_fn` at `init_daemon` follows the Pillar G TEST-ONLY embed_fn convention + the per-pillar-H seam-vs-fork two-tiered distinction per the W4 follow-up P2-1 closure. Tests inject a no-op or capture-call function; production callers omit the kwarg + receive the default `reconcile.reconcile` invocation.

**No Pass A body changes at W10-11** — the existing Pass A body per ADR-0014 D33 + ADR-0015 already handles orphan `send_intent` recovery via Gmail query + the 5-minute grace window per `DEFAULT_MIN_INTENT_AGE`. The W10-11 commitment is the daemon-side INVOCATION wiring, not the per-pass body. The "Pass A/B/C tightening" trajectory text at ADR-0060 D332 is satisfied by the W10-11 wiring + the existing per-pass bodies — operators querying the recovery surface see the per-pass error classification + per-channel filtering already in place.

## Alternatives considered

### D364 alternatives (crash-recovery synthesis)

1. **Persist a `daemon_pid_file` to disk at `init_daemon` Step 3.5 + check at startup for stale PIDs.** Rejected — per ADR-0060 D335 invariant 2 the daemon contributes NO new state that bypasses the ledger. A `daemon_pid_file` would be cross-process state outside the ledger; on crash the file could be left stale OR truncated mid-write; the recovery would consult the file instead of the ledger, introducing a divergent source-of-truth. The ledger-walk approach preserves the structural commitment.

2. **Run the crash-recovery synthesis at Step 8 (after index materialization) so the indexes already include the prior daemon's events.** Rejected — the synthesis APPENDS new events to the ledger; if it ran AFTER index materialization the indexes wouldn't include the synthesized events until the next per-event append (which might not fire for hours on a quiet daemon). Running at Step 4.5 (BEFORE index materialization) ensures the indexes naturally include the synthesis at Step 8.

3. **Defer the synthesis to a Pillar I per-tenant audit-tooling pass.** Rejected — the W10-11 trajectory per ADR-0060 D332 explicitly names "crash recovery hardening" as the deliverable. Deferring to Pillar I would leave the W12 Stable flip without crash-recovery coverage; the binding exit-criterion test per PILLAR-PLAN §2 Pillar H explicitly requires "recovers cleanly from `kill -9`".

4. **Synthesize `daemon_aborted` (NEW event class) instead of `daemon_stopped(exit_reason="crash")`.** Considered + REJECTED — the W3 commit per ADR-0062 D344 already reserved `"crash"` as a valid `exit_reason` for this exact W10-11 trajectory. Adding a NEW event class would require extending `DAEMON_NEW_EVENT_CLASSES` (6 → 7) + `EVENT_CLASS_CATALOG` (25 → 26) + a new `build_daemon_aborted_payload` factory + a new Pillar G observability primitive consumer surface — significant scope expansion for what is structurally a `daemon_stopped` variant. Reusing the existing event class with `exit_reason="crash"` preserves the closed-set discipline + the per-pillar mirror constants parity.

### D365 alternatives (kill -9 test substrate)

1. **Real fork+kill via `subprocess.Popen` + `os.kill(pid, signal.SIGKILL)`.** Considered + REJECTED for the W10-11 main commit — subprocess + asyncio + signal-handling combination is brittle in CI (timing-dependent; varies across Python versions + OS schedulers); the test substrate's value is the failure-mode coverage at the ledger level, NOT the literal process-spawn mechanism. The W12 binding exit-criterion test MAY layer a real fork+kill on top for end-to-end verification.

2. **Mock the `daemon_started` event via `unittest.mock` patches.** Rejected — the synthesized-state substrate (pre-seeding the ledger with real events via `Ledger.append`) is structurally truer to production behavior than mock patches. The W5 P1-1 behavioral-passthrough-not-signature-only discipline + the SEVEN follow-on closures' regression-barrier discipline establish the preference for real-substrate tests over mock-only tests.

3. **Skip the test substrate at W10-11; defer to W12 binding exit-criterion test.** Rejected per the per-pillar-foundation precedent — Pillar H Week 1 shipped the test stub at Week 1; each Week N un-skips the per-week trajectory rows. W10-11's commitment per ADR-0060 D332 explicitly includes `kill -9` test substrate; the binding exit-criterion test at W12 is a higher-bar test (24h-run-zero-anomaly + crash-recovery + policy-hot-reload composite); the W11 stub un-skip at W10-11 is the structural commitment.

### D366 alternatives (reconcile pre-flight pass)

1. **Always invoke Pass A at startup (no opt-in config).** Rejected — Pass A queries Gmail at startup; default-on would force every test to mock Gmail (dev path + unit-test path + CI path all touched). The operator-deliberate opt-in via `reconcile_passes_at_startup` preserves the test substrate's no-Gmail-mocking posture + lets production operators opt-in via config.

2. **Auto-detect operator-deliberacy by inspecting whether Gmail credentials are configured.** Rejected — implicit auto-detect introduces silent behavior changes (operators upgrading their Gmail SDK setup would suddenly see pre-flight reconcile fire); the operator-deliberate config field surfaces the choice explicitly. Per the Pillar G framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298, operator-deliberate set-once posture is the framework convention.

3. **Wire pre-flight reconcile as a `pre_start_hook` callback that operators register at runtime.** Rejected — the callback abstraction adds indirection without value at v1; the `reconcile_passes_at_startup` config field is operator-readable + serializes through `_compute_config_hash` for operator-visible config-drift tracking. Pillar I per-tenant audit-tooling MAY extend with per-tenant config + pre-start hooks per the per-tenant trajectory.

4. **Always invoke Pass A AND additionally Pass B/D/E/F/H/I/J (the full intent-recovery set) at startup.** Rejected at v1 — Pass B (DSN/bounce detection) queries Gmail's inbox; Pass D/E (LinkedIn) queries the LinkedIn SDK; Pass F (Twitter) queries the Twitter SDK; Pass H/I/J (per-channel reply recovery) queries each channel. The combined SDK setup + the per-channel rate-limit + the operator-deliberacy of running multi-channel queries at startup all argue for opt-in via the config field (operators set `reconcile_passes_at_startup="A,B,D,E,F,H,I,J"` if they want the full set; "A" alone is the canonical minimal opt-in for Gmail intent recovery).

## Consequences

### Positive

- **The Pillar H exit-criterion binding test's crash-recovery row** (ROW 2 per PILLAR-PLAN §2 Pillar H + ADR-0060 D334's 6-row binding test) is structurally satisfied at W10-11. The W12 author un-skips the binding exit-criterion test on the W10-11 foundation.
- **The W10-11 commit lands the operationally-observable `daemon_stopped(exit_reason="crash")` event** — operators querying the funnel CLI's per-event-class aggregation per ADR-0059 D325 + the Grafana Panel #7 (W10-11 NEW) see the crash-recovery distribution; the Pillar G observability framework's existing surface adopts the W10-11 events without code changes (the surface was pre-wired at W3 per ADR-0062 D344).
- **The R037 mitigation pattern per ADR-0060 §Risks is operationally landed** — operators restarting the daemon (for any reason: config change / migration / OS patch / crash recovery) see the in-flight intent recovery via the operator-deliberate `reconcile_passes_at_startup` opt-in OR the per-tick reconcile dispatch via Pillar H Week 7's `dispatch_fn` (the structural backstop). The R037 risk is downgraded from "open" to "operationally mitigated" in the risk register at W10-11.
- **The per-pillar-foundation precedent extends to Pillar H Week 10-11** — Pillar G Week 7-8 (ADR-0056) shipped multi-decision per-week ADR; Pillar H Week 8-9 (ADR-0067) shipped multi-decision per-week ADR with W9 extension addendum; Pillar H Week 10-11 (ADR-0068) ships THREE decisions in a single per-week ADR matching the per-pillar trajectory.
- **The per-week-reviewer's checklist for Pillar H carries the THIRTY-THREE-consecutive-weeks track record forward at W10-11** — cell-level matrix coverage + behavioral-passthrough + module-level docstring drift + cross-pillar back-audit + per-pillar mirror constants parity all hold at the W10-11 commit.
- **The closed-set discipline extends to Pillar H Week 10-11** — NO new closed-sets at W10-11; the existing `DAEMON_EXIT_REASONS` already reserved "crash" at W3 per ADR-0062 D344. The per-pillar mirror constants parity preserves verbatim.
- **The privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 holds across the W10-11 surface** — the synthesized `daemon_stopped` event payload excludes `person_id` / body content / source_list per ADR-0062 D343's existing factory contract.
- **The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + the Pillar H Week 4 follow-up P2-1 closure's two-tiered seam-vs-fork distinction preserve at W10-11** — the `crash_recovery_fn` + `reconcile_at_startup_fn` test-only seams substitute BACKENDS without replacing the function body.
- **No new event classes at W10-11** — `DAEMON_NEW_EVENT_CLASSES` stays at SIX (W6 added `daemon_stage_saturated` per ADR-0065 D355; W9's invalidation contract consumed existing classes); `EVENT_CLASS_CATALOG` content-additive at W10-11 (ZERO new event classes — the catalog's absolute count is unaffected by W10-11 because the synthesis emits via the existing `daemon_stopped` class). The W10-11 synthesis emits via the existing `daemon_stopped` class. **W12 follow-up P3-1 correction:** the original "stays at 25" absolute-count claim was incorrect — `EVENT_CLASS_CATALOG` actually contains 63 entries spanning Pillar A-H + Phase 5.5 surfaces; the substantive claim is "ZERO new event classes at W10-11" (verified by the existing `len(DAEMON_NEW_EVENT_CLASSES) == 6` regression-barrier at `tests/test_daemon.py::TestModuleConstants` per the W6 follow-up P3-6 closure). The "stays at 25" propagated from ADR-0065's W6 narrative (which was already incorrect) through W8 follow-up + W10-11 + W12; the W12 follow-up corrects + names the TENTH consecutive ADR-vs-actual-impl drift in Pillar H caught by the per-week-reviewer's cross-pillar back-audit discipline.
- **No new ledger migrations at W10-11** — the pending count stays at 19 (UNCHANGED from W9 follow-up). The crash-recovery synthesis is an in-process append + observer fire; no schema change.
- **No new pip dependencies at W10-11**.

### Negative

- **The W10-11 commit extends `init_daemon` with TWO new steps (4.5 + 4.6) + a new DaemonConfig field + a new helper function** — the body's surface grows by ~150 LOC at W10-11. The per-pillar-week trajectory budget (12 weeks for Pillar H) accommodates this growth; the W12 commit ships the Stable flip without further body extension.
- **The operator-deliberate `reconcile_passes_at_startup` opt-in surface adds a config field operators may overlook on first-time daemon setup.** The §Existing-operator seed documents the recommended `reconcile_passes_at_startup="A"` for production; the §Migration/rollout section names the operator action. The structural commitment is the per-tick reconcile dispatch via the W7 `dispatch_fn` — operators that DON'T opt-in to pre-flight still get recovery within one tick.
- **The synthesized-state test substrate does NOT exercise the actual `kill -9` syscall path** — the W12 author may layer a real fork+kill on top of the W10-11 substrate to fully verify the syscall-level recovery. The W10-11 substrate's coverage at the ledger level is the structural commitment; the W12 layer is the binding exit-criterion test.
- **The `uptime_seconds` of the synthesized `daemon_stopped` event MAY surface a stale value** — if the prior daemon emitted events to the ledger AFTER its `daemon_started` (e.g., `health_probe` events at the R038 rate-limit cadence), the synthesis uses the latest ts observed for that PID. If no later events exist, `uptime_seconds=0.0` is the synthesis-time placeholder. Operators wanting per-second-accurate crash-time stamps wire a separate watchdog (Pillar I per-tenant audit-tooling trajectory).

### Neutral

- **The W10-11 commit's per-week ADR scope is comparable to ADR-0067 (W8-9)** — ADR-0067 had FIVE decisions (D359-D363 across W8 + W9 + W8 follow-up + W9 follow-up); ADR-0068 ships THREE decisions (D364-D366) at the W10-11 commit. The per-week ADR scope is roughly constant across the per-pillar-H trajectory.
- **The `_recover_from_prior_crash` helper is module-internal at v1** — re-exported via `orchestrator.daemon.__init__` for Pillar I per-tenant fan-out's potential consumer (the per-tenant audit-tooling MAY call the helper with a per-tenant Ledger). Test substrate at `tests/test_daemon.py` consumes it directly.
- **The Grafana Panel #7 (NEW at W10-11) joins the existing 6 panels at `infra/grafana/dashboards/per_daemon.yml`** — operators navigate the per-pillar-H tab in Grafana to see the daemon's clean-vs-crash distribution + the per-pillar-H trajectory continues at W11→W12 with the binding exit-criterion test verification.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — the crash-recovery synthesis appends events to the ledger; the ledger remains the source of truth. The synthesized `daemon_stopped` events flow through `Ledger.append` + the W9 observer seam + the per-event-class index materialization at Step 8 per ADR-0067 D360.
- **I2 (Atomicity contract).** Compliant + EXTENDED — D364's synthesis uses the existing `Ledger.append` body's atomicity contract per Phase 5.5 + ADR-0060 D335 invariant 2. The synthesis fires observer callbacks AFTER fsync per the W9 observer-fire-after-durable-write ordering. The recovery synthesis itself is operator-deliberately durable BEFORE the daemon transitions to "ready".
- **I3 (Single source of truth).** Compliant — every crash-recovery synthesis is reconstructible from the ledger walk; no cross-process state introduced.
- **I4 (Determinism).** Compliant — the synthesis is deterministic given a fixed ledger state; the synthesis-time `ts` is the runtime stamp (operators querying byte-identical reproducibility get byte-identical synthesis at fixed-substrate level per ADR-0031 D140 — the `ts` is the externalized clock per the established `now_fn` test-seam convention).
- **I5 (Refuse loud).** Compliant — the synthesis validates inputs via `build_daemon_stopped_payload`'s existing refuse-loud per the raw-primitive factory convention; invalid prior `daemon_started` events (missing `pid`) are skipped + logged to stderr (the synthesis cannot synthesize a crash event without a known prior PID).
- **I6 (No silent state).** Compliant — every synthesized `daemon_stopped` event is operator-visible in the ledger + the per-event-class index + the Grafana Panel #7 + the per-call observability primitives.
- **I7 (Refuse loud on broken pipelines).** Compliant — the synthesis is best-effort at the daemon startup boundary; failures log to stderr + do NOT prevent daemon startup (operators see the failure in the daemon's startup logs + investigate). The structural backstop is the per-tick reconcile dispatch via Pillar H Week 7's `dispatch_fn`.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant — the synthesized `daemon_stopped` event payload excludes `person_id` / body content / source_list. The Pillar H per-week-reviewer's privacy invariant check is the structural barrier.
- **The channel-on-every-event invariant per ADR-0014 D33** — Unaffected — the synthesized `daemon_stopped` events are daemon-lifecycle events without channel context per ADR-0060 D331's existing convention.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — the synthesis does NOT touch the per-send gate; the CAN-SPAM compliance preserves verbatim.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected — the synthesis does NOT touch the Layer 1-5 surfaces; the Pillar F primitive surfaces + Layer 5 backstop preserve verbatim.
- **The one-CLI-invocation invariant per ADR-0050 D276(a)** — Preserved — operators invoking `python orchestrator/funnel.py --since N` from outside the daemon see the synthesized `daemon_stopped` events naturally in the per-event-class aggregation; the funnel CLI's READ-ONLY contract per ADR-0059 D325 preserves verbatim.
- **The READ-ONLY funnel CLI contract per ADR-0059 D325** — Preserved — the W10-11 commit does NOT modify `funnel.build_report` or the per-funnel-stage aggregation logic.
- **The byte-identical determinism contract per ADR-0031 D140** — Preserved at the per-process granularity — the synthesis is deterministic given a fixed ledger state + a fixed `now_fn`.
- **The graceful-shutdown structural commitment per ADR-0060 D335 invariant 3** — Preserved + EXTENDED via the crash-recovery synthesis covering the failure mode where graceful shutdown could NOT complete (per the failure-mode taxonomy case (3) in Context section). Operators see the synthesis-time `daemon_stopped(exit_reason="crash")` event for crashed daemons that did NOT complete graceful shutdown.
- **The R032 synthetic-event exclusion per `_recovered_by`** — Preserved + REINFORCED — the synthesized `daemon_stopped` events carry `_recovered_by="reconcile"` per the existing audit-marker discipline; the Pillar G SLO aggregation per ADR-0056 D311 filters them naturally.

## Downstream pillar impact

- **Pillar I (OSS bring-up + multi-tenant).** Per-tenant fan-out at the daemon process boundary — one daemon process per tenant per ADR-0060 D335 invariant 1; the crash-recovery synthesis is per-tenant-isolated by construction (each tenant's daemon walks its own ledger; cross-tenant crashes are not visible). Pillar I author MAY extend `_recover_from_prior_crash` with per-tenant labels in the synthesized event payload (the helper signature is structured to accept this extension via additional kwargs).
- **Pillar J (Security + compliance).** GDPR-purge transaction per ADR-0050 §Downstream extends to the crash-recovery synthesis — a per-Person purge invalidates the per-Person index entries; the synthesis's `daemon_stopped` events are NOT per-Person + are unaffected by the purge. SLSA supply-chain attestation per Pillar J extends to the daemon's `_DAEMON_VERSION` constant + the container image; the W10-11 commit preserves the `_DAEMON_VERSION` discipline.

## Migration / rollout

- **Operator-side action required at Pillar H Week 10-11 upgrade:** **NONE for the crash-recovery synthesis** (the synthesis fires transparently at `init_daemon` Step 4.5 on every daemon startup; operators upgrading to W10-11 see synthesized `daemon_stopped(exit_reason="crash")` events for any prior crashed daemons that lacked `daemon_stopped` events in their ledger).
- **Recommended (optional) for production**: operators set `DaemonConfig.reconcile_passes_at_startup="A"` for auto-recovery of orphan `send_intent` events on every daemon restart. The per-tick reconcile dispatch via Pillar H Week 7's `dispatch_fn` is the structural backstop; pre-flight invocation is operator convenience.
- **No ledger schema migration** — W10-11 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes** — W10-11 reuses the existing `daemon_stopped` event class per ADR-0062 D344's pre-reserved `"crash"` exit_reason value.
- **No new pip dependencies at Pillar H Week 10-11**.
- **Grafana dashboard upgrade** — operators using the Grafana-as-code provisioning per ADR-0053 D292 re-apply `infra/grafana/dashboards/per_daemon.yml` (the W10-11 commit extends with NEW Panel #7 rendering `daemon_stopped` event's `exit_reason` distribution).

## Existing-operator seed

Operator action required at Pillar H Week 10-11: **NONE for the crash-recovery synthesis** (transparent at `init_daemon` Step 4.5).

Recommended (optional) for production operators:

```python
from pathlib import Path
from orchestrator.daemon import DaemonConfig, init_daemon

config = DaemonConfig(
    vault_dir=Path("~/Documents/...").expanduser(),
    ledger_dir=Path("~/.outreach-factory/ledger/").expanduser(),
    # ... existing fields ...
    # Pillar H Week 10-11 — operator-deliberate opt-in to auto-recover
    # orphan send_intent events on every daemon restart per ADR-0068 D366.
    # Recommended "A" for production (Gmail intent recovery only);
    # set to "A,B,D,E,F,H,I,J" for the full intent-recovery pass set.
    reconcile_passes_at_startup="A",
)
runner = init_daemon(config)
```

Operators waiting for the Pillar H Stable flip at Week 12 see the binding exit-criterion test land — verify the daemon recovers cleanly from `kill -9` + the 24h-uptime + zero-anomaly + policy-hot-reload composite.

## Pillar H Week 10-11 follow-up addendum

Per the per-week-reviewer's independent review of the W10-11 main commit (`4c0da3e` at the top of `git log --oneline -1`):

**P1-1 closure — the NINTH ADR-vs-actual-impl drift in Pillar H** caught by the per-week-reviewer's cross-pillar back-audit discipline (the prior EIGHT: W2 P3-8 OTel Resource rationale → W3 P2-1 `_emitted_by` audit-marker → W4 P2-1 framework-neutrality text → W5 P1-1 `traced_stage` signature → W6 P2-2 Step 5.5 ordering → W7 P1-1 Pass G classifier dependency → W8 follow-up P2-1 EventClassIndex catalog scope → W9 follow-up P2-1 Step 9/Step 10 narrative). The W10-11 main commit's Step 4.6 invocation called `reconcile_at_startup_fn(passes=..., ledger_dir=..., apply=True)` but `orchestrator.reconcile.reconcile`'s actual signature has NO `ledger_dir` parameter — it takes `led: Ledger` (NOT `ledger_dir`) + `since: datetime` (REQUIRED, no default). The production-default `reconcile_at_startup_fn=None` path lazy-imported the actual reconcile + raised `TypeError: reconcile() got an unexpected keyword argument 'ledger_dir'` which was caught by the broad `except Exception` + logged + silently swallowed — operators opting in via `DaemonConfig(reconcile_passes_at_startup="A")` got the §Existing-operator-seed-recommended config but NO pre-flight reconcile. **Like W7 P1-1, this is severity P1** because production-default behavior was broken — operators following the §Existing-operator seed got a silently-failing pre-flight reconcile every restart.

**P1-1 CLOSED** via the W10-11 follow-up commit's Step 4.6 body correction:

```python
# Pillar H Week 10-11 follow-up P1-1 closure — use the actual
# reconcile.reconcile signature: led=Ledger(...) + since=...
# (NOT the broken ledger_dir=... that the W10-11 main commit
# used). The 7-day since window catches operator-deliberate
# orphan intents up to a week old; Pass A's min_intent_age=5min
# threshold filters the "too-young" intent case naturally.
_recovery_led = Ledger(config.ledger_dir)
_since = datetime.now(tz=timezone.utc) - timedelta(days=7)
reconcile_at_startup_fn(
    passes=config.reconcile_passes_at_startup,
    since=_since,
    led=_recovery_led,
    apply=True,
    persist_status=False,
)
```

**P2-1 closure — behavioral-passthrough discipline gap at Step 4.6** (the proximate cause of P1-1 going uncaught). The W10-11 main commit's `TestInitDaemonStep4_6ReconcileAtStartup` × 3 tests ALL used a spy `_spy_reconcile(**kwargs)` accepting any kwargs — no test exercised the production-default `reconcile_at_startup_fn=None` path against the actual `reconcile.reconcile`. The W5 P1-1 + W7 P1-1 + W8/W9 closures' behavioral-passthrough-not-signature-only discipline (now THIRTY-TWO consecutive weeks post-W10-11-follow-up) was applied at Step 4.5 (`test_default_invokes_recover_from_prior_crash_behavioral_passthrough`) but NOT at Step 4.6 — exactly the asymmetric gap that allowed P1-1 to ship. **P2-1 CLOSED** via NEW `TestW10_11FollowupReconcileSignaturePassthrough` × 3 regression-barrier tests:

* `test_step_4_6_default_kwargs_match_reconcile_actual_signature` — introspects `inspect.signature(reconcile.reconcile)` + verifies the W10-11 follow-up Step 4.6 invocation kwargs are ALL accepted by the actual signature AND the REQUIRED params (no default) are all present. Would have caught P1-1 directly.
* `test_step_4_6_passes_led_not_ledger_dir` — verifies `led=Ledger(...)` is passed AND `ledger_dir` is NOT passed (the W10-11 main commit's drift mode).
* `test_step_4_6_passes_since_per_required_param` — verifies `since: datetime` is passed (REQUIRED per actual signature) AND the value is the 7-day window per ADR-0068 D366 follow-up rationale.

**P2-2 closure — cross-class uptime tracking regression-barrier**. The W10-11 main commit's `_recover_from_prior_crash` docstring claimed `uptime_seconds` derivation is "across daemon-lifecycle event classes (daemon_started / daemon_stopping / policy_reloaded / health_probe / daemon_stage_saturated)" but the W10-11 main commit only tested daemon_started + daemon_stopping; the THREE additional event classes' cross-class assertions were docstring-claims-only. A future refactor that, say, removed `pid` from the `health_probe` payload would silently break the cross-class uptime tracking. **P2-2 CLOSED** via NEW `TestW10_11FollowupCrossClassUptimeTracking` × 3 regression-barrier tests covering each of the three documented-but-untested event classes (`test_uptime_derived_from_health_probe_ts` + `test_uptime_derived_from_policy_reloaded_ts` + `test_uptime_derived_from_daemon_stage_saturated_ts`).

**P3-1 closure — TWO ledger walks at startup** documented at the W10-11 main commit code comment (operator-acceptable at v1; Pillar I trajectory MAY consolidate to single walk). The W10-11 follow-up confirms the trajectory note is correct + no code change at v1.

**P3-2 closure — all synthesized events share same `ts`** documented at the W10-11 main commit's `now = now_fn()` capture before the loop (correctly byte-identical-deterministic; the ledger's monotonic-ts contract per ADR-0010 D17 is preserved; operators querying for "which crash happened first" within a single synthesis batch see ambiguity at v1 — acceptable trade-off). The W10-11 follow-up adds a docstring note naming the shared-ts semantic.

**P3-3 closure — ADR-0068 §Existing-operator seed example** — the example `DaemonConfig(reconcile_passes_at_startup="A")` + `init_daemon(config)` is the operator-facing surface. With the W10-11 follow-up's P1-1 closure, this NOW WORKS correctly — the §Existing-operator seed text doesn't need changing because the operator-facing surface didn't change; only the internal Step 4.6 invocation kwargs changed.

**P3-4 closure — W7 follow-up NEW-2 (shutdown-during-in-flight-reconcile)** STAYS DEFERRED to W12 OR a separate W10-11 follow-up commit. The W10-11 commit's structural commitment is the crash detection + the operator-deliberate pre-flight reconcile; the asyncio.to_thread worker thread cancellation under shutdown is a SEPARATE concern. The W10-11 follow-up explicitly defers per the existing W7 follow-up's deferral.

**REFUTED concerns** (preserved from the W10-11 main review):
1. Same-PID-reuse edge case at Step 4.5 — defensive `current_pid != ev_pid` exclusion is correct + verified at `test_current_pid_excluded_per_w10_11_d364`.
2. Pass A pre-flight invocation timing (Step 4.6 BEFORE Step 5 policy load) — Pass A does NOT consume policy state.
3. ADR-0068 D364 step ordering claim — verified at `test_step_4_5_fires_after_migration_before_policy_load`.
4. ADR-0068 D364 `_recovered_for_pid` field claim — verified at `test_audit_marker_preserved_per_r032_filter`.
5. ADR-0068 D366 `reconcile_passes_at_startup` empty-string validation — verified at `test_validate_config_refuses_loud_on_empty_string`.
6. Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323 — verified at the synthesized payload contents.
7. Atomicity contract per ADR-0060 D335 invariant 2 — verified — synthesis uses `Ledger.append` + W9 observer fires.

**Per-week-reviewer disciplines status after W10-11 follow-up**:
- Cell-level matrix coverage **THIRTY-FIVE consecutive weeks** (Pillar F W6-W12 + Pillar G W2-W12 + W12 follow-up + Pillar H W1 follow-up + Pillar H W2 + W2 follow-up + W3 + W3 follow-up + W4 + W4 follow-up + W5 + W5 follow-up + W6 + W6 follow-up + W7 + W7 follow-up + W8 + W8 follow-up + W9 + W9 follow-up + W10-11 + W10-11 follow-up; +6 net new W10-11 follow-up tests at `TestW10_11FollowupReconcileSignaturePassthrough` × 3 + `TestW10_11FollowupCrossClassUptimeTracking` × 3).
- Behavioral-passthrough-not-signature-only **THIRTY-TWO consecutive weeks** (the W10-11 follow-up P2-1 closure's THREE regression-barriers exercise the production-default Step 4.6 path's call kwargs via `inspect.signature` introspection — would have caught P1-1 directly).
- Module-level docstring drift **THIRTY-FOUR consecutive weeks** (runner.py + `__init__.py` module docstrings ALL extended naming Pillar H Week 10-11 follow-up + the SIX closure categories).
- Per-pillar mirror constants parity PRESERVED (the EIGHT closed-sets + SIX-element DAEMON_NEW_EVENT_CLASSES + SIX emit factories all preserve verbatim).
- Cross-pillar back-audit EXTENDED to NINE consecutive Pillar H weeks of ADR-vs-actual-impl drift catches (W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2 → W7 P1-1 → W8 follow-up P2-1 → W9 follow-up P2-1 → W10-11 main P1-1). THREE of the NINE catches have been P1 escalations (W5, W7, W10-11) — the discipline's empirical structural value is now non-trivial across the per-pillar-week trajectory.
- Framework-neutrality contract PRESERVED at the seam level (the seams substitute BACKENDS correctly); the production call site's bug at P1-1 was a separate concern from the seam shape.
- Privacy invariant CONFIRMED (the W10-11 follow-up does NOT alter the synthesized event payload's privacy posture).
- Atomicity-preservation per ADR-0060 D335 invariant 2 OPERATIONALLY ENFORCED + byte-identical determinism per ADR-0031 D140 OPERATIONALLY ENFORCED.

## References

- **ADR-0067** (Pillar H Week 8 — per-event-class index materialization). D359-D363. **The W9 observer seam at `Ledger.append` per ADR-0067 D362 fires for the W10-11 synthesis** — the per-event-class index updates naturally; the freshness gauge advances per the W9 invalidation contract.
- **ADR-0066** (Pillar H Week 7 — reload_policy body + reconcile passes integration). D356-D358. **The W7 `dispatch_fn` seam + `_STAGE_TO_PASSES` mapping is the structural backstop for per-tick reconcile dispatch** — operators NOT opting-in to W10-11's pre-flight reconcile still get recovery within one tick.
- **ADR-0064** (Pillar H Week 5 — `DaemonRunner.run` body). D349-D352. **The run() body's Step 4 signal handler wiring + the existing graceful-shutdown coordination preserve at W10-11**.
- **ADR-0062** (Pillar H Week 3 — `attach_signal_handlers` body + `DaemonRunner.shutdown` body). D341-D344. **D344 pre-reserved `exit_reason="crash"` for the W10-11 trajectory** — the W10-11 commit operationally lands the synthesis.
- **ADR-0060** (Pillar H foundation). D331-D336. **D335 invariant 2 (atomicity-preservation-across-process-boundary) is the structural commitment the W10-11 commit satisfies**. D332's trajectory table row 10-11 names the W10-11 deliverable.
- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector). D307-D313. **D311's R032 synthetic-event exclusion per `_recovered_by` filter applies to the W10-11 synthesized `daemon_stopped` events** — the SLO aggregation naturally excludes them.
- **ADR-0050** (Pillar G Week 1 foundation). D272-D277. **D276(b) operator-confidential fields invariant** — the W10-11 synthesis preserves verbatim.
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (byte-identical determinism). **Preserved at W10-11 via the `now_fn` test seam + the `_recover_from_prior_crash` helper's pure-function determinism**.
- **ADR-0027** (Pillar D Week 4 — Pass H/I/J inter-channel reply recovery). D111. **The full intent-recovery pass set per `reconcile_passes_at_startup="A,B,D,E,F,H,I,J"` operator-deliberate opt-in**.
- **ADR-0025** (Pillar D foundation). D97 (legal-liability invariant). **Preserved at W10-11**.
- **ADR-0017** (Pillar C Week 4 — Pass D + E LinkedIn invite recovery). D58. **Per-channel intent recovery surface preserves at W10-11**.
- **ADR-0015** (Pillar C Week 2 — Pass A send_intent recovery). **The Pass A body per ADR-0015 is the canonical recovery surface; W10-11 wires the daemon-side pre-flight invocation as operator-deliberate opt-in**.
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant + per-channel two-phase commit contract). **Preserved + EXTENDED at W10-11 — the per-channel two-phase intent/confirmed pairs still complete via Pass A through O if the daemon crashes mid-flight; the daemon-side D364 synthesis backfills the `daemon_stopped` event for the crashed daemon process**.
- **ADR-0010** (Phase 5.5 ledger schema). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). **The W10-11 synthesis preserves the audit-marker discipline verbatim**.
- `.planning/REVIEW-pillar-h-surface-audit.md` §36 — Pillar H Week 10-11 cross-pillar surface audit extension (gitignored).
- `.planning/HANDOFF-pillar-h-week-10-11.md` — Pillar H Week 10-11 close summary + handoff to Pillar H Week 12 (gitignored).
- `docs/PILLAR-PLAN.md` §6 Pillar H row Week 10-11 Notes column appended.
- `docs/adr/README.md` ADR-0068 row appended.
- `docs/SOURCES-OF-TRUTH.md` daemon-state row Week 10-11 reference appended.
- `infra/grafana/dashboards/per_daemon.yml` NEW Panel #7 (`daemon_stopped` exit_reason distribution).
- `orchestrator/daemon/runner.py` extended with `_recover_from_prior_crash` helper + `init_daemon` Step 4.5 + Step 4.6 + `DaemonConfig.reconcile_passes_at_startup` field.
- `orchestrator/daemon/__init__.py` extended with `_recover_from_prior_crash` re-export + module docstring extension naming Week 10-11.
- `tests/test_daemon.py` extended with NEW `TestRecoverFromPriorCrash` × 8 + `TestInitDaemonStep4_5CrashRecovery` × 4 + `TestDaemonConfigReconcilePassesAtStartup` × 3 + `TestInitDaemonStep4_6ReconcileAtStartup` × 3 test classes.
- `tests/test_multi_channel_coherence.py::TestPillarHDaemon::test_recovers_from_kill_9_via_reconcile` un-skipped at W10-11.
