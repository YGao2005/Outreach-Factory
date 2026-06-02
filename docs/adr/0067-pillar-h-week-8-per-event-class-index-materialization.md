# ADR-0067: Pillar H Week 8 — per-event-class index materialization at daemon startup + per-Person primitive ledger-walk-avoidance via optional `event_class_index` kwarg

## Status

Accepted — 2026-05-27.

## Context

Per ADR-0060 D332's per-week trajectory table, Pillar H Week 8 ships per-event-class index materialization at daemon startup per R039 mitigation + ledger-walk-avoidance at the per-Person primitives. Per ADR-0060 D336:

> Pillar H Week 8-9 ships per-event-class index materialization at daemon startup + invalidation on `Ledger.append`. The index is denormalized from the ledger (rebuildable per I3) + invalidated on each `Ledger.append`; the per-call observability primitive aggregations consult the index instead of walking `Ledger.all_events()` directly.

The Week 8 commit ships:

1. The **structural commitment** at the `DaemonRunner` field level — the daemon process owns two in-memory indexes populated at startup. The shape was pinned by ADR-0060 D336:

```python
EventClassIndex = dict[str, list[dict]]   # event_class → events in time-order
PersonEventIndex = dict[str, list[dict]]  # person_id → per-Person events
```

2. The **materialization at `init_daemon` Step 8** (NEW step inserted between Prometheus exposition Step 7 + DaemonRunner construction Step 9). The walk is O(N) at startup; per-call lookups become O(M_class) where M_class is the per-class subset.

3. The **per-Person primitive ledger-walk-avoidance** via optional `event_class_index` kwarg on the THREE `collect_per_person_*` primitives at `orchestrator/observability.py` (`collect_per_person_register_fidelity_snapshots` + `collect_per_person_claim_type_hallucination_snapshots` + `collect_per_person_layer_5_drift_snapshots`). When the daemon-process consumer passes the index, the primitive iterates only the relevant event class's entries (O(M_class)); when the kwarg is omitted (the funnel CLI / external operator invocation per ADR-0059 D325 READ-ONLY contract), the primitive walks the ledger directly (O(N) preserved).

Week 9 trajectory per ADR-0060 D336: ships invalidation on `Ledger.append` + per-pillar-H Grafana index-age panel.

The Week 7 follow-up's per-week-reviewer caught a **SIXTH consecutive ADR-vs-actual-impl drift in Pillar H** (the D358 narrative claimed Pass G was pure-framework but the body required `RuleBasedClassifier` per ADR-0026 D103); the per-week-reviewer pattern is now established at SIX consecutive Pillar H weeks of ADR-vs-actual-impl drift catches (W2 P3-8 OTel Resource rationale → W3 P2-1 `_emitted_by` audit-marker → W4 P2-1 framework-neutrality text → W5 P1-1 `traced_stage` signature → W6 P2-2 Step 5.5 ordering → W7 P1-1 Pass G classifier dependency). The Week 8 author MUST verify ADR-0067 narrative claims match the actual `init_daemon` Step 8 + the index materialization + the per-Person primitive consumer wiring before commit.

## Decisions

### D359. `EventClassIndex` + `PersonEventIndex` mutable holder shape via per-pillar-H `_PolicyState` precedent

Both indexes are mutable `dataclass` (NOT frozen) holders matching the Pillar H Week 7 `_PolicyState` precedent per ADR-0066 D356. Each carries a single internal `_data: dict[str, list[dict]]` field + a `events_for_class(event_class)` / `events_for(person_id)` query API method.

The mutable-holder pattern is the documented alternative to extending the `object.__setattr__` frozen-dataclass escape hatch per the Pillar H Week 3 follow-up P3-1 + Week 5 follow-up NEW-5 + Week 7 P3-1 closures' lifecycle_state-only scope:

```python
@dataclass
class EventClassIndex:
    """Pillar H Week 8 — in-memory per-event-class index per ADR-0060
    D336 + ADR-0067 D359.

    The :class:`DaemonRunner` is FROZEN but :class:`EventClassIndex`
    is a mutable holder; the frozen-dataclass invariant protects the
    field REFERENCE (e.g., ``runner.event_class_index = new_idx`` is
    refused) but allows mutating the held instance directly
    (``runner.event_class_index._data[event_class].append(ev)`` is
    permitted at Week 9's :meth:`Ledger.append`-driven invalidation).
    """

    _data: dict[str, list[dict]] = field(default_factory=dict)

    def events_for_class(self, event_class: str) -> list:
        """Return Event-wrapped chronologically-sorted events for the
        given class.

        Refuses-loud on event_class outside :data:`EVENT_CLASS_CATALOG`
        per the per-pillar mirror constants parity discipline + the
        closed-set discipline per ADR-0042 D210 + ADR-0050 D276(b).
        """
        if event_class not in _observability.EVENT_CLASS_CATALOG:
            raise ValueError(
                f"event_class {event_class!r} not in EVENT_CLASS_CATALOG"
            )
        return [
            _ledger.Event.from_dict(d)
            for d in self._data.get(event_class, [])
        ]


@dataclass
class PersonEventIndex:
    """Pillar H Week 8 — in-memory per-Person index per ADR-0060 D336
    + ADR-0067 D359.
    """

    _data: dict[str, list[dict]] = field(default_factory=dict)

    def events_for(self, person_id: str) -> list:
        """Return Event-wrapped chronologically-sorted events for the
        given Person.
        """
        return [
            _ledger.Event.from_dict(d)
            for d in self._data.get(person_id, [])
        ]
```

**Privacy invariant** per I8 + ADR-0050 D276(b) + ADR-0058 D323. The `PersonEventIndex` is keyed by `person_id` (operator-private operationally per the Person/Identity separation in Phase 5.5). The keyed surface is daemon-process-local + rebuilt from the ledger at startup — the daemon contributes NO new state that bypasses the ledger per ADR-0060 D335 invariant 2. The stored `_data` values are event DICT views (with the same fields as the ledger event); no body / source_list / draft body is materialized that isn't already in the ledger. The `events_for(person_id)` query returns Event-wrapped objects (identical shape to `led.all_events()`) so operators consuming the index get the same surface they get from the ledger.

**The query API returns DEFENSIVE COPIES** (list comprehension wrapping each dict in a fresh `Event`). Operators mutating the returned list do NOT mutate the index's internal `_data`. The Week 9 invalidation contract per ADR-0060 D336 will mutate `_data` directly; the query API's defensive-copy posture insulates callers from concurrent mutation.

Rejected alternatives (D359 × 4):

1. **Frozen dataclass holding immutable mappings.** Rejected per the same rationale as Week 7's `_PolicyState` — Week 9's `Ledger.append`-driven invalidation requires per-event-class list mutation; freezing the holder would force `dataclasses.replace(idx, _data=new_dict)` per append (O(N) garbage-collection pressure at v2 scale).
2. **Module-level `_event_class_index: dict[str, list[dict]] = {}` + free functions.** Rejected per the per-pillar-H per-tenant isolation invariant per ADR-0060 D335 invariant 1 — Pillar I per-tenant fan-out runs one daemon process per tenant; module-level mutable state would silently share index across tenant processes IF Pillar I ever transitions to in-process tenant fan-out (the Week 8 author should NOT lock in a single-tenant-only structural choice that Pillar I might revisit). Per-`DaemonRunner` field-scoped indexes preserve tenant-isolation by construction.
3. **`PersonEventIndex` keyed by `(person_id, event_class)` tuple.** Considered + REJECTED at Week 8 — the per-Person primitives (Pillar G Week 10-11 per ADR-0058 D319-D321) walk events of ONE class then filter by `person_id` (not the reverse); the natural index for those primitives is `EventClassIndex`. `PersonEventIndex` keyed by `person_id` alone is the natural index for the future Pillar I per-tenant operator dashboard's "show me all events for this Person" surface. The tuple key would conflate two distinct use cases + force redundant lookups (lookup by `(pid, "draft_quality_scored")` then by `(pid, "hallucination_detected")` etc., when the natural shape is "all events for pid, then group by class downstream").
4. **Persist the indexes to disk.** Rejected per I1 + I3 — the ledger is the source of truth; the index is denormalized + rebuildable. Persisting would introduce a cross-process state divergence risk (one daemon process writes the index; another reads stale) + violate the "rebuildable per I3" structural commitment per ADR-0060 D336.

### D360. `init_daemon` Step 8 — single-walk dual-index materialization per ADR-0060 D336

`init_daemon` extended with a NEW Step 8 (inserted between the existing Step 7 Prometheus exposition + the now-renumbered Step 9 DaemonRunner construction). Step 8 walks the ledger ONCE + populates both indexes via the shared `_materialize_indexes(led)` helper. The single-walk discipline mirrors the Pillar G Week 2 `collect_event_class_snapshots` body's single-walk pattern per ADR-0051 D278.

```python
def _materialize_indexes(led: "_ledger.Ledger") -> tuple[EventClassIndex, PersonEventIndex]:
    """Walk the ledger ONCE; populate both indexes for the daemon
    process per ADR-0060 D336 + ADR-0067 D360.

    Events whose ``type`` is NOT in :data:`EVENT_CLASS_CATALOG` are
    silently SKIPPED at index-population time — the
    :func:`observability.collect_event_class_snapshots` primitive's
    uncatalogued diagnostic posture per ADR-0050 D272 + ADR-0051
    D279 fires at primitive-call time (not at index-population
    time); pre-allocating a per-class bucket for known classes at
    index-population time would be redundant work without value at
    v1 scale (~5K events) or v2 scale (~100K events).

    Events with NULL ``person_id`` are skipped from
    :class:`PersonEventIndex` (per the "Person-less events bucket"
    convention per ADR-0045 D231 — ad-hoc validation events do NOT
    have person_id; they are still indexed in
    :class:`EventClassIndex` by type).

    The walk preserves the ledger's chronological order via
    :meth:`Ledger.all_events` which sorts by ``ts`` per
    ``ledger.py::Ledger._load_events`` body; both indexes' per-key
    lists are append-only chronologically.
    """
    event_class_idx = EventClassIndex()
    person_idx = PersonEventIndex()
    catalog = _observability.EVENT_CLASS_CATALOG
    for ev in led.all_events():
        ev_dict = ev.to_dict()
        ev_type = ev.type
        if ev_type in catalog:
            event_class_idx._data.setdefault(ev_type, []).append(ev_dict)
        pid = ev.person_id
        if pid is not None:
            person_idx._data.setdefault(pid, []).append(ev_dict)
    return event_class_idx, person_idx
```

`init_daemon` Step 8 wiring (NEW; inserted after existing Step 7 Prometheus exposition):

```python
# Step 8: NEW per ADR-0067 D360 — materialize the per-event-class +
# per-Person indexes at daemon startup per R039 mitigation per
# ADR-0060 D336. The walk amortizes to startup; per-call lookups
# from the daemon-process per-Person primitives drop to O(M_class).
if index_materialize_fn is None:
    _led = Ledger(config.ledger_dir)
    event_class_idx, person_idx = _materialize_indexes(_led)
else:
    event_class_idx, person_idx = index_materialize_fn()

# Step 9: construct + return DaemonRunner in "initializing" state.
# (Was Step 8; renumbered to Step 9 per the W8 D360 step insertion.)
return DaemonRunner(
    config=config,
    config_hash=config_hash,
    pid=pid,
    started_at_ts=started_at_ts,
    version=version,
    lifecycle_state="initializing",
    policy_state=initial_policy_state,
    event_class_index=event_class_idx,
    person_event_index=person_idx,
)
```

The NEW `index_materialize_fn` test-only seam follows the Pillar G TEST-ONLY embed_fn convention per ADR-0061 D337 + the per-pillar-H seam-vs-fork two-tiered distinction per the W4 follow-up P2-1 closure. Production callers omit; tests inject pre-populated indexes to skip the ledger walk for unit-test substrate isolation.

**Behavioral-passthrough discipline** per the W5 P1-1 + W7 P1-1 closures' CANONICAL safeguard at TWENTY-SIX consecutive weeks. The W8 commit ships TWO regression-barrier tests pinning the production-default path:

1. `TestInitDaemonIndexMaterialization::test_default_walks_real_ledger_per_w8_d360_behavioral_passthrough` — passes a real `Ledger(tmp_path)` substrate with pre-seeded events + verifies the production default (omitted `index_materialize_fn`) populates both indexes from the real ledger walk. The `_behavioral_passthrough` suffix names the W5/W7 P1-1 closures' canonical safeguard discipline.
2. `TestMaterializeIndexes::test_uncatalogued_event_class_skipped_from_event_class_index_per_w8_d360` — pre-seeds the ledger with one event of class NOT in EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES (W8 follow-up P2-1 closure's extended scope) + verifies the event is silently skipped from `EventClassIndex` (the uncatalogued diagnostic posture stays at primitive-call time per ADR-0051 D279). [W8 follow-up P3-1 closure: test-class attribution corrected from `TestInitDaemonIndexMaterialization` to `TestMaterializeIndexes`.]

Rejected alternatives (D360 × 4):

1. **Lazy materialization on first query.** Rejected per the operator-deliberate startup amortization — the daemon's startup cost (Migration apply + Policy load + OTel init + Prometheus start) is already ~1-5s at v1; adding ~100-500ms of index materialization is inside the daemon's expected startup budget. Lazy materialization on first query would push the cost to the first per-Person primitive call (typically Pillar G Week 10-11's per-Person dashboard refresh) where operators would see an inexplicable latency spike on first dashboard load.
2. **Per-process subprocess (one process walks the ledger; another consumes).** Rejected per ADR-0060 D331 alternative 2 + D332 alternative 2 — cross-process Ledger contention + cross-process OTel SDK init conflict + cross-process state divergence are all complexity-amplifiers that the single-process / asyncio framework choice avoids.
3. **Skip materialization at Week 8; defer to Week 9-10.** Rejected per the per-pillar-week trajectory at ADR-0060 D332 — the Week 8 commitment is the materialization; deferring would force the Week 8 commit's "ledger-walk-avoidance at per-Person primitives" deliverable to depend on a structural piece that doesn't exist yet.
4. **Materialize at the SAME step as policy load (Step 5).** Rejected — the policy load loads YAML files from disk (operator-controlled deployment state); the index materializes from the ledger (operator-data store). Bundling would conflate two distinct concerns at the same step + force the test substrate to mock both at once. The Step 8 placement (after Prometheus, before DaemonRunner construction) is structurally minimal — the index is the LAST piece of operator-visible state before the daemon enters "initializing" → "ready" transition trajectory at Week 5+'s `DaemonRunner.run` body.

### D361. Per-Person primitive ledger-walk-avoidance via optional `event_class_index` kwarg — Pillar G framework adoption preservation per ADR-0059 D325

The THREE per-Person primitives at `orchestrator/observability.py` are extended with an optional `event_class_index: "EventClassIndex | None" = None` kwarg:

* `collect_per_person_register_fidelity_snapshots` — walks `"draft_quality_scored"` events
* `collect_per_person_claim_type_hallucination_snapshots` — walks `"hallucination_detected"` events
* `collect_per_person_layer_5_drift_snapshots` — walks `"reconcile_drift"` events

When the kwarg is provided (the daemon-process consumer per ADR-0060 D336's trajectory), the primitive iterates only the matching event class's entries from the index (O(M_class)). When the kwarg is omitted (the funnel CLI per ADR-0059 D325 READ-ONLY contract; external operator invocations; pre-Week-8 callers), the primitive walks `led.all_events()` as before (O(N) preserved).

```python
def collect_per_person_register_fidelity_snapshots(
    led: "_ledger.Ledger",
    *,
    since: datetime,
    now: datetime | None = None,
    expected_registers: frozenset[str] = PILLAR_F_REGISTERS_MIRROR,
    # Pillar H Week 8 NEW per ADR-0067 D361 — optional in-process
    # daemon-local index for ledger-walk-avoidance per R039 mitigation
    # per ADR-0060 D336. Default None → walk ledger directly per
    # ADR-0059 D325's READ-ONLY contract preservation.
    event_class_index: "EventClassIndex | None" = None,
) -> list[PersonRegisterFidelitySnapshot]:
    ...
    # Body extracts the iteration source:
    if event_class_index is not None:
        events_iter = event_class_index.events_for_class("draft_quality_scored")
        # Index entries are pre-filtered by class; no in-loop type check needed.
        for ev in events_iter:
            # ... existing _recovered_by + ts >= since + register + person_id walks ...
    else:
        for ev in led.all_events():
            if ev.type != "draft_quality_scored":
                continue
            # ... existing walks ...
```

**Pillar G READ-ONLY contract preservation** per ADR-0059 D325 + ADR-0050 D272 + R033. The kwarg default is `None` → the existing ledger-walk behavior is preserved verbatim. The funnel CLI continues to walk the ledger directly when operators invoke `python orchestrator/funnel.py --since N`. The byte-identical determinism contract per ADR-0031 D140 is preserved — the daemon's index walk yields the same MetricSnapshot results as the ledger walk (the index is a denormalized projection of the same data).

**Stateless contract preservation** per ADR-0050 D272 + R033 mitigation. The primitive's per-call cost is now O(M_class) instead of O(N) when index is provided, BUT the primitive itself remains stateless — it does not cache; every call consults the current index (whose state reflects the ledger via Week 9's `Ledger.append`-driven invalidation; at Week 8 the index is populated once at startup + never refreshed, which is consistent with the Week 8 commit's narrow scope).

**Diagnostic-emit posture preservation** per ADR-0051 D279. The primitives' `pillar_f_register_uncatalogued` + `pillar_f_claim_type_uncatalogued` + `pillar_f_drift_reason_uncatalogued` diagnostic emits fire at primitive-call time exactly as before — the index-vs-ledger choice does NOT affect diagnostic emission. The `observability_class_uncatalogued` diagnostic per ADR-0050 D272 fires from `collect_event_class_snapshots` per its own body; the per-Person primitives' diagnostic emit is for register/claim-type/reason drift, NOT event-class drift.

**Behavioral-passthrough discipline** per the W5 P1-1 + W7 P1-1 closures. The W8 commit ships THREE regression-barrier tests per primitive (NINE total) verifying the index-vs-ledger paths produce byte-identical snapshot lists.

Rejected alternatives (D361 × 4):

1. **Transparent (no kwarg) consumption — primitive auto-detects daemon context.** Rejected — there is no clean signal at the primitive-call site distinguishing daemon-process vs CLI invocation. A thread-local / context-variable would introduce a hidden coupling between the observability primitive + the daemon's process context (cross-pillar concern); the kwarg is operator-explicit + test-substrate-injectable.
2. **Force the primitive to ALWAYS consume the index — fail if index is None.** Rejected per ADR-0059 D325 READ-ONLY contract — the funnel CLI's `aggregate_per_stage_funnel` invocations consume per-Person primitives directly via `python orchestrator/funnel.py`; forcing the index would break those callers + require funnel.py to construct an index per invocation (a CLI-side O(N) walk PLUS the materialization overhead — strictly worse than the existing ledger walk).
3. **Replace `led` kwarg with `event_class_index` kwarg outright (NO ledger fallback).** Rejected — the diagnostic-emit path (uncatalogued register / claim-type / reason) needs to call `led.append({...})` per ADR-0051 D279; the primitive needs a `Ledger` reference for emit even when the read path is the index. The kwarg-additive shape preserves the diagnostic-emit reference.
4. **Add the kwarg to `collect_event_class_snapshots` as well.** Considered + DEFERRED to Week 9-10 per scoping discipline — `collect_event_class_snapshots` is the per-event-class snapshot primitive; the Week 8 commit's ledger-walk-avoidance is at the per-Person primitive surface (which is where the v2-scale O(N) concern surfaces per the Pillar G retrospective per RETRO-pillar-g.md). The `collect_event_class_snapshots` walk is the per-event-class aggregation primitive consumed by the funnel CLI READ-ONLY surface; index-wiring it would touch the funnel CLI contract surface that ADR-0059 D325 pinned at Pillar G Week 12. Deferring to Week 9-10 preserves the Pillar G STABLE 2026-05-26 claim's structural posture (the funnel CLI body does NOT change at Week 8).

## Surface extensions

### Public surface

* NEW `EventClassIndex` dataclass at `orchestrator/daemon/runner.py` — mutable holder; `events_for_class(event_class) -> list[Event]` query method; refuses-loud on uncatalogued event_class.
* NEW `PersonEventIndex` dataclass at `orchestrator/daemon/runner.py` — mutable holder; `events_for(person_id) -> list[Event]` query method.
* `DaemonRunner` extended with TWO new fields: `event_class_index: EventClassIndex` + `person_event_index: PersonEventIndex` (default `field(default_factory=...)` so `DaemonRunner` constructed directly by tests bypassing `init_daemon` works without explicit kwargs).
* `init_daemon` extended with NEW Step 8 (single-walk dual-index materialization) + the existing DaemonRunner construction renumbered to Step 9.
* NEW `index_materialize_fn` test-only seam at `init_daemon` per the Pillar G TEST-ONLY embed_fn convention + the per-pillar-H seam-vs-fork two-tiered distinction.
* THREE `collect_per_person_*` primitives at `orchestrator/observability.py` extended with optional `event_class_index: "EventClassIndex | None" = None` kwarg.

### Re-exports at `orchestrator/daemon/__init__.py`

* `EventClassIndex` + `PersonEventIndex` re-exported per the per-pillar-foundation precedent (Pillar G Week 1 re-exported `MetricSnapshot` + `EVENT_CLASS_CATALOG`).

### Pillar G framework adoption surfaces (preserve VERBATIM)

* OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension + READ-ONLY contract per ADR-0059 D325 ALL preserve verbatim across Pillar H Week 8.

### Pillar A/B/C/D/E/F surfaces (preserve VERBATIM)

* The legal-liability + privacy invariants stay with FULL weight. The Pillar F primitive surfaces + Layer 5 backstop preserve verbatim. The per-channel two-phase commit per ADR-0014 D33 preserves verbatim. The per-pillar mirror constants parity discipline EXTENDED via the SEVENTH closed-set if the index implementation requires (NOT NEEDED at v1 — `EVENT_CLASS_CATALOG` is the existing closed-set the index respects; no new closed-set).

## Downstream pillar impact

### Pillar I (OSS bring-up + multi-tenant)

Per-tenant fan-out per ADR-0060 D335 invariant 1 extends naturally: one daemon process per tenant → one `EventClassIndex` + one `PersonEventIndex` per tenant container. The index is `DaemonRunner`-field-scoped + per-process-isolated by construction. Pillar I per-tenant audit-tooling MAY extend the index with per-tenant labels (e.g., a `(tenant_id, event_class)` composite key) per the multi-tenant fan-out trajectory; the Week 8 commit ships the single-tenant framework.

### Pillar J (Security + compliance)

GDPR purge per ADR-0050 §Downstream: a per-Person purge MUST invalidate the per-Person index entries + emit the per-Person purge event. The Week 8 commit ships the index materialization; the GDPR purge extension lands at Pillar J's per-Person-purge surface (which consumes `PersonEventIndex.events_for(person_id)` + clears the entries). SLSA supply-chain attestation per Pillar J extends to the `_DAEMON_VERSION` constant + the daemon container image — the index does NOT affect the supply-chain surface (it's in-process state, not persistent).

## Migration / rollout

**Operator action: NONE.**

Production operators invoking `init_daemon(DaemonConfig(...))` at v1 see the index populated at daemon startup (the materialization is silent + the structural commitment surfaces via the `daemon_started` event's payload at Pillar H Week 9+'s index-age dashboard panel). Existing per-Person primitive callers (the funnel CLI) continue to walk the ledger directly per the optional kwarg's `None` default.

Pre-Week-8 callers of the per-Person primitives (tests / external operator invocations) continue to work verbatim — the new kwarg is optional + non-positional + non-breaking.

ZERO new ledger migrations at Week 8 (pending stays at 19). The existing events already carry the `type` field per ADR-0010 D17 + ADR-0014 D33; no new schema is needed.

## Existing-operator seed

Operators preview the W8 surface via:

```python
from orchestrator.daemon import (
    EventClassIndex,
    PersonEventIndex,
    init_daemon,
    DaemonConfig,
)
import asyncio

runner = init_daemon(DaemonConfig(...))

# The indexes are populated at startup; query API is O(M_class):
sent_events = runner.event_class_index.events_for_class("send_confirmed")
person_events = runner.person_event_index.events_for("p-abc-123")

# Index-aware per-Person primitive call (daemon-process consumer):
from orchestrator import observability
fidelity = observability.collect_per_person_register_fidelity_snapshots(
    led, since=...,
    event_class_index=runner.event_class_index,
)
```

Operators wanting the EXISTING (pre-Week-8) primitive behavior simply OMIT the `event_class_index` kwarg — the ledger-walk path is preserved verbatim.

## References

* **ADR-0060** (Pillar H foundation). **D332** per-week trajectory table — Week 8 row: "Per-event-class index materialization at startup per R039 + ledger-walk-avoidance at per-Person primitives". **D335** per-daemon load-bearing invariants (preserved). **D336** per-event-class indexing trajectory — Week 8 ships materialization; Week 9 ships invalidation.
* **ADR-0061** (Pillar H Week 2 — `init_daemon` body + EVENT_CLASS_CATALOG extension). **D337** startup ordering invariant (extended with NEW Step 8; existing Steps 1-7 preserve; DaemonRunner construction renumbered to Step 9).
* **ADR-0066** (Pillar H Week 7 — `reload_policy` body + `_PolicyState` mutable holder). **D356** the `_PolicyState` precedent for the mutable-holder pattern Week 8 mirrors at `EventClassIndex` + `PersonEventIndex`.
* **ADR-0050** (Pillar G Week 1 — per-event-class observability primitive). **D272** stateless contract preserved (the index is per-process state, not cross-process; multi-tenant operators run one daemon per tenant). **D276(b)** privacy invariant preserved (the index excludes draft body / source_list / claim_text).
* **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body). **D278** single-walk discipline mirrored at `_materialize_indexes(led)`. **D279** diagnostic-emit posture preserved (uncatalogued classes fire at primitive-call time, NOT at index-population time).
* **ADR-0058** (Pillar G Week 10-11 — per-Person observability surface adapters). **D319-D324** per-Person primitives that Week 8 extends with the optional `event_class_index` kwarg (3 of the 3 adapters).
* **ADR-0059** (Pillar G Week 12 — binding exit-criterion + funnel CLI extension). **D325** READ-ONLY funnel CLI contract — preserved (the funnel CLI continues to walk the ledger directly; the index is daemon-process-local + transparent).
* **R039 mitigation** — Per-Person primitive's O(N) ledger walk at daemon-cron-interval cost. Mitigated at Week 8 via the per-event-class index materialization + the per-Person primitive consumer extension.

---

## Pillar H Week 8 follow-up addendum (per per-week-reviewer findings on commit `f23a0e3`)

The per-week independent review of the Week 8 main commit surfaced **0 P1 + 2 P2 + 6 P3 + 1 NEW addressed + 4 REFUTED**. The W8 follow-up closes each per the per-pillar-foundation precedent (Pillar G Week 12 follow-up `43612a8` + Pillar H Week 1-7 follow-ups). ZERO new ADRs (the closures are in the spirit of ADR-0067's existing decisions per the per-week-reviewer's follow-up convention).

**P2-1 closure — the SEVENTH ADR-vs-actual-impl drift in Pillar H caught by the per-week-reviewer's cross-pillar back-audit discipline.** The W8 main commit's `EventClassIndex` catalog scope at `events_for_class` + `_materialize_indexes` was `EVENT_CLASS_CATALOG` only — diverging from the Pillar G `collect_event_class_snapshots` consumer surface precedent at `orchestrator/observability.py:910` which uses `expected_classes | OBSERVABILITY_NEW_EVENT_CLASSES` as its "known classes" set. The W8 follow-up extends the catalog scope to `EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES` at BOTH the `_materialize_indexes` body + the `events_for_class` query boundary. Operators now see `slo_violation_detected` (Pillar G Week 7-8 emit per ADR-0056) + `observability_class_uncatalogued` (Pillar G Week 2 emit per ADR-0051 D279) accepted by the EventClassIndex query API + indexed by `_materialize_indexes` at daemon startup. The closure preserves the per-pillar mirror constants parity discipline by aligning the daemon's index closed-set scope with the Pillar G consumer surface's closed-set scope. Cross-pillar back-audit discipline EXTENDED to SEVEN consecutive Pillar H weeks of ADR-vs-actual-impl drift catches (W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2 → W7 P1-1 → W8 follow-up P2-1); FIVE regression-barrier tests at `TestW8FollowupEventClassIndexCatalogScope` (`test_events_for_class_accepts_observability_new_event_classes_per_w8_followup_p2_1` + `test_materialize_indexes_includes_observability_new_event_classes_per_w8_followup_p2_1` + `test_events_for_class_query_returns_indexed_slo_violation_events_per_w8_followup_p2_1` + `test_uncatalogued_event_still_skipped_per_w8_followup_p2_1` + `test_events_for_class_refuses_loud_on_truly_uncatalogued_per_w8_followup_p2_1`).

**P2-2 closure — `orchestrator/observability.py` module-docstring drift.** The W8 main commit made MATERIAL changes to `orchestrator/observability.py` (NEW `_iter_events_of_class` helper + THREE per-Person primitives extended with optional `event_class_index` kwarg + NEW TYPE_CHECKING-guarded import of `EventClassIndex`) but did NOT extend the module docstring naming the Week 8 changes. Per the W3 follow-up P3-5 closure's discipline-scope extension to materially-changed modules in the same per-week commit (now THIRTY consecutive weeks of module-docstring-drift discipline), the W8 follow-up extends the `orchestrator/observability.py` module docstring to name "Pillar H Week 8 + Pillar H Week 8 follow-up" + ADR-0067 D361 + the THREE per-Person primitive extensions + the W8 follow-up P2-2 closure rationale.

**P3-1 + P3-2 closure — ADR-0067 D360 test-name attribution drifts.** The W8 main commit's ADR-0067 D360 narrative at lines 174-177 (in the "Behavioral-passthrough discipline" sub-section) named:
- Line 176: `TestInitDaemonIndexMaterialization::test_default_walks_real_ledger_per_w8_d360` (missing `_behavioral_passthrough` suffix).
- Line 177: `TestInitDaemonIndexMaterialization::test_uncatalogued_events_skipped_per_w8_d360` (incorrect test-class — the test actually lives at `TestMaterializeIndexes::test_uncatalogued_event_class_skipped_from_event_class_index_per_w8_d360`).

The W8 follow-up aligns ADR-0067 D360 to the actual test names + classes. The `_behavioral_passthrough` suffix is load-bearing for the W5/W7 P1-1 discipline trace; the test-class attribution drift was the proximate cause of the P3-1 finding.

**P3-3 closure — `events_for_class` body comment ordering clarity.** The W8 main commit's `events_for_class` body had a "Lazy import" comment that was misleading about the actual import-order (the body references `_observability.EVENT_CLASS_CATALOG` BEFORE the lazy `from orchestrator.ledger import Event` line because observability is module-top per Pillar H Week 5 follow-up P3-6 closure; ledger is local). The W8 follow-up tightens the docstring + the body comment to name the actual ordering + the W8 follow-up P2-1 closure's extended catalog scope.

**P3-4 closure — ADR-0067 D360 "TWO regression-barrier tests" claim over-stated.** The W8 main commit's ADR-0067 D360 narrative claimed "TWO regression-barrier tests pin the production-default path"; the actual test_default_walks_real_ledger_per_w8_d360_behavioral_passthrough IS the production-default-exercise; the second test (`test_uncatalogued_event_class_skipped_from_event_class_index_per_w8_d360`) lives in `TestMaterializeIndexes` and invokes `_materialize_indexes(led)` directly, NOT via `init_daemon`'s production-default path. The W8 follow-up corrects the count + naming in ADR-0067 D360.

**P3-5 closure — `_materialize_indexes` docstring lazy-allocate trade-off documentation.** The W8 main commit's `_materialize_indexes` docstring discussed the lazy-allocate vs pre-allocate trade-off implicitly via the "pre-allocating a per-class bucket for known classes at index-population time would be redundant work without value" sentence. The W8 follow-up extends the docstring with a dedicated paragraph naming the lazy-allocate choice + the v1 (~5K events) + v2 (~100K events) scale rationale + the operator-readability concern (operators reading the function code see `setdefault(...).append(...)` and may wonder why not pre-allocate; the docstring now names the trade-off).

**P3-6 closure — `_data` field naming convention.** Pre-W8-follow-up, both `EventClassIndex` + `PersonEventIndex` carry an identically-named `_data` field. A future Pillar I extension that wants a third index variant (e.g., per-(tenant, event_class) tuple key) would have THREE identically-named `_data` fields — operationally confusing. The W8 follow-up DEFERS the rename (to `_per_class_data` + `_per_person_data` etc.) to Pillar I trajectory because the v1 use case is unambiguous (only two indexes; the dataclass type discriminates the use case at the field-access site). Documented at the class-level docstrings naming the deferral.

**NEW-1 closure — `_iter_events_of_class` byte-identical Event-wrapping invariant.** The W8 main commit's `_iter_events_of_class` helper relied on a structural property — `Event.to_dict() ↔ Event.from_dict(d)` round-trip equivalence — for the byte-identical determinism contract per ADR-0031 D140. The W8 follow-up extends the `_iter_events_of_class` docstring with a dedicated paragraph naming this invariant + the structural dependency on `Event.from_dict` + the regression-barrier tests at `TestPerPersonPrimitiveIndexConsumption` that pin the v1 equivalence (any future Pillar I+ extension that modifies `Event.from_dict` MUST verify both paths remain equivalent).

**REFUTED #1** — Defensive-copy posture preserved (verified empirically via `test_defensive_copy_query_isolates_caller_per_w8_d359` at both index test classes; each invocation constructs a FRESH list of FRESH Event objects via `from_dict` which deep-copies via `e._d = dict(d)`).

**REFUTED #2** — Per-tenant key-space concern (Pillar I per ADR-0060 D335 invariant 1 runs one daemon process per tenant; per-tenant isolation is structural by construction).

**REFUTED #3** — Atomicity-preservation per ADR-0060 D335 invariant 2 (the index is rebuildable from the ledger per I3; verified via `_materialize_indexes`'s re-walk pattern at every daemon startup).

**REFUTED #4** — Pre-allocation operator clarity (the lazy-allocate choice IS now documented in the W8 follow-up P3-5 closure's `_materialize_indexes` docstring extension; the P3-5 finding is closed via the extension, not via re-architecting).

### Per-week-reviewer disciplines status after W8 follow-up

| Discipline | Status after W8 follow-up |
|---|---|
| Cell-level matrix coverage | **THIRTY-ONE** consecutive weeks (+5 net new W8 follow-up daemon contract tests 266 → 271) |
| Behavioral-passthrough-not-signature-only | **TWENTY-EIGHT** consecutive weeks (the SEVEN W8 follow-up tests verify the extended catalog scope's behavioral-passthrough — the index is populated + queryable for the TWO Pillar G observability-internal classes; not signature-only) |
| Module-level docstring drift | **THIRTY** consecutive weeks (W8 follow-up P2-2 closure extends `orchestrator/observability.py` module docstring per the W3 follow-up P3-5 closure's discipline-scope-extension to materially-changed modules) |
| Per-pillar mirror constants parity | EXTENDED — the W8 follow-up P2-1 closure aligns the EventClassIndex catalog scope with the Pillar G `collect_event_class_snapshots` consumer surface precedent (the structural commitment that BOTH the daemon's index + the Pillar G primitive use `EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES` as the "known classes" set) |
| Cross-pillar back-audit | EXTENDED to **SEVEN consecutive Pillar H weeks** of ADR-vs-actual-impl drift catches (W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2 → W7 P1-1 → W8 follow-up P2-1); the per-week-reviewer pattern's structural value is empirically validated at SEVEN consecutive Pillar H weeks |
| Framework-neutrality contract | PRESERVED via `index_materialize_fn` seam following W4 follow-up P2-1's two-tiered seam-vs-fork distinction |
| Privacy invariant | CONFIRMED — the W8 follow-up does NOT alter PersonEventIndex's daemon-process-local + rebuildable-from-ledger posture; the catalog scope extension at EventClassIndex includes Pillar G observability-internal classes which are themselves operator-observable per ADR-0050 D276(b) |

---

## Pillar H Week 9 extension — per-event-class index invalidation on `Ledger.append` + operator-visible freshness gauge

Per ADR-0060 D332's per-week trajectory table row 9 (`Per-event-class index invalidation on Ledger.append + index-age dashboard panel — ADR-0067 (continued)`), Pillar H Week 9 extends ADR-0067 with TWO NEW decisions:

### D362. Per-event-class index invalidation on `Ledger.append` via post-append observer seam

The Pillar H Week 8 commit (D359-D361) shipped per-event-class index materialization at daemon startup — a one-shot O(N) walk that captures the ledger's state-at-startup but goes stale on subsequent appends. Pillar H Week 9 ships the invalidation contract per ADR-0060 D336: **every `Ledger.append` triggers an in-memory index update; the index reflects the ledger's current state exactly per ADR-0031 D140's byte-identical determinism contract**.

The structural commitment is a post-append observer seam at `Ledger`:

* **NEW `Ledger._post_append_observers: list[Callable[[dict], None]]` instance attribute** at `orchestrator/ledger.py::Ledger.__init__`. Operators register callbacks via `Ledger.append_observer(observer)`; each callback fires AFTER the durable fsync + symlink + mtime-cache invalidation of `Ledger.append` per Phase 5.5 + ADR-0060 D335 invariant 2's atomicity contract.

* **NEW `Ledger.append_observer(observer: Callable[[dict], None])` registration method** — operators register a callback that fires with the serialized event dict (`ts` + `v` defaults filled in by `Ledger.append`) on each successful append. Observers fire in registration order; observer exceptions are logged to stderr but DO NOT propagate (preserves the durability contract per ADR-0060 D335 invariant 2 — the ledger is durable BEFORE observers fire; observer failure does NOT roll back the append).

* **NEW `Ledger.append` body extension** at the end (after fsync + symlink + mtime invalidation):

```python
for _observer in self._post_append_observers:
    try:
        _observer(d)
    except Exception as _exc:
        print(f"WARNING: ledger post-append observer ... raised ...", file=sys.stderr)
```

* **NEW `_invalidate_indexes_on_append(event_class_index, person_event_index, ev_dict, known_classes, now_ts_fn)` helper** at `orchestrator/daemon/runner.py` — per-event invalidation function mirroring `_materialize_indexes`'s per-event branch shape:

```python
def _invalidate_indexes_on_append(
    event_class_index: EventClassIndex,
    person_event_index: PersonEventIndex,
    ev_dict: dict,
    known_classes: frozenset[str],
    now_ts_fn: Callable[[], float] = time.time,
) -> None:
    ev_type = ev_dict.get("type")
    if isinstance(ev_type, str) and ev_type in known_classes:
        event_class_index._data.setdefault(ev_type, []).append(ev_dict)
    pid = ev_dict.get("person_id")
    if pid is not None and isinstance(pid, str):
        person_event_index._data.setdefault(pid, []).append(ev_dict)
    now_ts = now_ts_fn()
    event_class_index._last_updated_at_ts = now_ts
    person_event_index._last_updated_at_ts = now_ts
```

The structural mirror of `_materialize_indexes`'s per-event branch preserves the post-condition equivalence: "N appends WITH the observer registered" = "N appends + from-scratch `_materialize_indexes` walk". This is the byte-identical determinism contract per ADR-0031 D140 — the index reflects the ledger's current state EXACTLY. The regression-barrier test `TestInstallIndexInvalidationObserver::test_post_invalidation_state_equals_materialization_per_byte_identical_determinism` pins this invariant.

* **NEW `_install_index_invalidation_observer(led, event_class_index, person_event_index, now_ts_fn)` registration helper** at `orchestrator/daemon/runner.py` — invoked at NEW `init_daemon` Step 8.5 between Step 8 materialization + the Step 9 DaemonRunner construction. The `known_classes` set is computed ONCE at registration time as `EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES` (the W8 follow-up P2-1 closure's extended scope — preserves the per-pillar mirror constants parity discipline). **Pillar H Week 9 follow-up P2-1 closure** — the W9 main commit's narrative claimed "renumbered Step 10 DaemonRunner construction" but the actual code at `runner.py:3832` still labels DaemonRunner construction as Step 9 (no renumber occurred at W9 — the gauge registration at Step 9.5 inserts AFTER existing Step 9 NOT renumbering it); the W9 follow-up aligns the narrative to match the code at runner.py + __init__.py module docstrings + ledger.py module docstring + this ADR addendum (the **EIGHTH consecutive ADR-vs-actual-impl drift in Pillar H** caught by the per-week-reviewer's cross-pillar back-audit discipline — the prior SEVEN: W2 P3-8 OTel Resource rationale → W3 P2-1 `_emitted_by` audit-marker → W4 P2-1 framework-neutrality text → W5 P1-1 `traced_stage` signature → W6 P2-2 Step 5.5 ordering → W7 P1-1 Pass G classifier dependency → W8 follow-up P2-1 EventClassIndex catalog scope).

* **NEW `DaemonRunner.ledger: Ledger | None = None` field** lifting the daemon's Ledger instance out of the Week 8 `init_daemon`-body-local scope. The daemon's `_default_dispatch_for_stage` body extended to consume `runner.ledger` (fallback to lazy construction when `runner.ledger is None` preserves backward compat with pre-Week-9 tests + external operator-invoked dispatchers).

* **`init_daemon` Step 8 extended** — the Ledger instance now stored on the runner (instead of local-only):

```python
# Step 8: materialize indexes — LIFTED at W9.
if index_materialize_fn is None:
    daemon_ledger = Ledger(config.ledger_dir)
    event_class_idx, person_idx = _materialize_indexes(daemon_ledger)
else:
    daemon_ledger = None
    event_class_idx, person_idx = index_materialize_fn()

# Step 8.5: NEW at W9 — register observer (production-path only).
if daemon_ledger is not None:
    _install_index_invalidation_observer(
        daemon_ledger, event_class_idx, person_idx,
    )
```

* **Cross-process consistency note** — observers are per-Ledger-instance; appends made on a DIFFERENT Ledger instance (operator running `python orchestrator/funnel.py` from a separate process; the `/send-outreach` skill; standalone CLI invocations) are NOT visible to the daemon-process index until the next daemon-process restart re-walks the ledger via `_materialize_indexes`. Pillar I per-tenant fan-out per ADR-0060 D335 invariant 1 runs one daemon process per tenant; the cross-process gap is a v1 single-tenant + concurrent-CLI concern. Operators concerned about cross-process consistency at v1 should either: (a) drive all appends through the daemon's Ledger (the production-default path); OR (b) restart the daemon after batch CLI invocations. Pillar I per-tenant audit-tooling MAY add a cross-process invalidation channel (Redis pub/sub / sqlite watcher / filesystem mtime polling) per the per-tenant trajectory — deferred at v1.

Rejected alternatives (D362 × 4):

1. **Daemon `IndexingLedger(Ledger)` subclass** — Considered + REJECTED. Forces the daemon to construct an `IndexingLedger` consistently across `init_daemon` + `_default_dispatch_for_stage` + every reconcile callsite. Reconcile passes that internally construct Ledgers (for queries; per `orchestrator.reconcile` patterns) would NOT trigger invalidation if they used the base class. The instance-attribute observer pattern is more robust + extends naturally to Pillar I per-tenant audit-tooling + Pillar J GDPR purge observers.

2. **Mtime polling between ticks** — Considered + REJECTED. The daemon's `run()` body would `Ledger.dir.stat().st_mtime` each tick + re-walk `_materialize_indexes` if changed. Trade-offs: O(N) re-walk per detected change defeats R039 mitigation at v2 scale; race on concurrent writers (the mtime stat happens BEFORE the re-walk; a writer between the stat + the walk would leave the index reflecting a transient state); operator-deliberate latency window (the index lags the ledger by up to `tick_seconds`). The observer seam delivers O(1) per-append invalidation with no lag.

3. **Module-level observer registry** — Considered + REJECTED. A module-level `_observers: list[Callable]` would leak state across Pillar I per-tenant fan-out (each tenant's daemon process imports the same `orchestrator.ledger` module; module-level state would silently share observers across tenant processes IF Pillar I ever transitions to in-process tenant fan-out). Per-Ledger-instance observers preserve tenant-isolation by construction per ADR-0060 D335 invariant 1.

4. **Persistent observer state file** — Considered + REJECTED. The index is denormalized + rebuildable per I3; persisting observer state adds another file to keep consistent with the ledger (cross-process consistency invariant violation) + introduces a recovery path for "observer state diverged from ledger" that defeats the I3 commitment. Daemon restarts re-materialize cleanly from the ledger; no observer state to recover.

### D363. Per-event-class index age Prometheus observable gauge + Grafana panel #6

The Week 9 invalidation contract delivers per-event O(1) index updates — operators need an SLO signal that the invalidation IS firing (the observer registration silently broke; the daemon stopped receiving appends; cross-process consistency surface visible). Pillar H Week 9 ships the operator-visible freshness gauge per ADR-0067 D363:

* **NEW `EventClassIndex._last_updated_at_ts: float = 0.0` field** + **NEW `PersonEventIndex._last_updated_at_ts: float = 0.0` field** — Unix-epoch timestamp (seconds, float) advanced on every index update. Default `0.0` (sentinel for "never materialized"); `_materialize_indexes` sets to `time.time()` at daemon startup; `_invalidate_indexes_on_append` advances on each per-append invalidation. The two indexes' timestamps advance in LOCKSTEP at v1 because the same observer invalidates both per `Ledger.append`; the lockstep invariant is documented at the `PersonEventIndex._last_updated_at_ts` field docstring + pinned by `TestEventClassIndexLastUpdatedAtTs::test_both_indexes_share_last_updated_at_ts_at_v1_per_lockstep_invariant`.

* **NEW `observability.register_daemon_index_observable_gauge(get_last_updated_ts_fn, meter)`** at `orchestrator/observability.py` — registers an OTel `ObservableGauge` named `outreach_factory_daemon_index_last_updated_timestamp` with a callback that returns the index's `_last_updated_at_ts` on each OTel scrape. The callback is stateless per ADR-0050 D272 + R033 mitigation pattern.

* **NEW `init_daemon` Step 9.5** — best-effort registration of the gauge AFTER DaemonRunner construction:

```python
try:
    _observability.register_daemon_index_observable_gauge(
        get_last_updated_ts_fn=lambda: runner.event_class_index._last_updated_at_ts,
    )
except Exception as _exc:
    print(f"WARNING: register_daemon_index_observable_gauge failed ...", file=sys.stderr)
```

The registration is wrapped in try/except + logs to stderr but does NOT propagate; the gauge is operator-observability scaffolding, NOT a daemon correctness contract. Operators running the daemon without the OTel SDK initialized (test substrate at unit-test scope OR no-op `otel_meter_init_fn` / `prometheus_start_fn` injection) get a silent no-op.

* **NEW Grafana panel #6** at `infra/grafana/dashboards/per_daemon.yml` — renders the index age via PromQL:

```yaml
- id: 6
  title: "Per-event-class index age (Week 9)"
  type: stat
  targets:
    - expr: |
        time() - outreach_factory_daemon_index_last_updated_timestamp
      legendFormat: 'index age'
  fieldConfig:
    defaults:
      unit: "s"
      thresholds:
        steps:
          - color: green
            value: null
          - color: orange
            value: 30
          - color: red
            value: 60
```

The panel goes RED at > 60s — operator SLO signal for invalidation stalls. Operationally, v1 single-tenant operators should see this stay sub-second under normal daemon load; the 60s threshold catches the observer-registration-silently-broke failure mode (the W9 follow-up reviewer's pre-identified weak-spot category for this panel).

Rejected alternatives (D363 × 4):

1. **Per-event-class age gauge (one label per class)** — Considered + REJECTED at v1. Per-class age would surface as a per-event-class timestamp; at v1 with infrequent events of some classes (`daemon_started` ~1/day operationally), the per-class age would stay high for those classes → operator confusion. Deferred to Pillar I per-tenant trajectory IF the per-tenant operator dashboard's per-Person panel requires per-class freshness.

2. **Cumulative invalidation counter** — Considered + REJECTED. A counter (`outreach_factory_daemon_index_invalidations_total`) would count invalidations cumulatively; operators would query the rate via `rate(...)[5m]`. The freshness gauge is more direct: operators see the age in seconds, not the rate. The counter is a Pillar I extension if operators want invalidation-rate dashboards.

3. **Histogram of invalidation latency** — Considered + REJECTED. The per-append invalidation is in-process O(1) (a dict `setdefault().append()` + a float assignment); the latency is sub-microsecond + not the operator concern. The freshness signal is the operator concern.

4. **Skip the gauge at Week 9; ship at Week 10-11** — Considered + REJECTED. Deferring the operator-visible signal would mean Week 9 ships the invalidation contract without operator visibility into whether it's firing; the W5/W7 P1-1 + W8 follow-up P2-1 behavioral-passthrough-not-signature-only discipline established at TWENTY-EIGHT consecutive weeks expects the structural commitment to ship WITH operator visibility.

### W9 surface extensions

#### Public surface

* `Ledger.append_observer(observer)` — Pillar H Week 9 NEW per ADR-0067 D362; cross-pillar surface extension at `orchestrator/ledger.py`.
* `Ledger.append` — Pillar H Week 9 body extension invoking registered observers AFTER fsync.
* `EventClassIndex._last_updated_at_ts` + `PersonEventIndex._last_updated_at_ts` — Pillar H Week 9 NEW dataclass fields per ADR-0067 D363.
* `DaemonRunner.ledger: Ledger | None = None` — Pillar H Week 9 NEW field per ADR-0067 D362.
* `_invalidate_indexes_on_append` + `_install_index_invalidation_observer` — Pillar H Week 9 NEW internal helpers (NOT in `__all__` per Python convention for `_`-prefixed names; importable for tests + Pillar I per-tenant audit-tooling extension).
* `observability.register_daemon_index_observable_gauge` — Pillar H Week 9 NEW public function per ADR-0067 D363.
* `_INSTRUMENT_NAME_DAEMON_INDEX_LAST_UPDATED_TIMESTAMP = "outreach_factory_daemon_index_last_updated_timestamp"` — NEW module constant at observability.py.
* `init_daemon` — Pillar H Week 9 Step 8 extended + NEW Step 8.5 + NEW Step 9.5 (gauge registration).
* `_default_dispatch_for_stage` — Pillar H Week 9 body extended to consume `runner.ledger` (with fallback to lazy construction).
* Grafana dashboard panel #6 at `infra/grafana/dashboards/per_daemon.yml` — Pillar H Week 9 NEW.
* `tests/test_multi_channel_coherence.py::TestPillarHDaemon::test_index_invalidates_on_ledger_append` — Pillar H Week 9 NEW coherence stub (un-skipped at W9 commit).

#### Pillar G framework adoption surfaces (preserve VERBATIM)

OTel SDK + Prometheus + Grafana-as-code + per-stage spans + dispatcher histogram + SLO violation detector + Slack webhook + cost aggregation + per-Person observability surface adapters + funnel CLI extension + READ-ONLY contract per ADR-0059 D325 ALL preserve verbatim across Pillar H Week 9.

#### Pillar A/B/C/D/E/F surfaces (preserve VERBATIM)

The legal-liability + privacy invariants stay with FULL weight. The Pillar B Ledger surface extends VIA the `_post_append_observers` instance attribute + `append_observer()` method + the post-fsync observer-fire block in `append()` — the structural commitment is the Pillar B atomicity contract per Phase 5.5 + I2 holds verbatim (fsync completes BEFORE observers fire; observer failure does NOT propagate). The Pillar F primitive surfaces + Layer 5 backstop preserve verbatim. The per-channel two-phase commit per ADR-0014 D33 preserves verbatim.

### W9 downstream pillar impact

#### Pillar I (OSS bring-up + multi-tenant)

Per-tenant fan-out per ADR-0060 D335 invariant 1 extends naturally: one daemon process per tenant → one `EventClassIndex` + one `PersonEventIndex` + one set of registered observers per tenant container. Pillar I per-tenant audit-tooling MAY register additional observers per the documented observer registry seam — for example, a per-tenant audit-log observer that mirrors appends to a tenant-specific WAL. The W9 commit ships the observer surface; Pillar I per-tenant extensions consume.

#### Pillar J (Security + compliance)

GDPR purge per ADR-0050 §Downstream extends to per-Person index invalidation — a per-Person purge MUST invalidate the per-Person index entries (clear `runner.person_event_index._data[purged_person_id]`) + emit the per-Person purge event. The W9 commit ships the invalidation surface; the GDPR purge extension lands at Pillar J's per-Person-purge surface. SLSA supply-chain attestation per Pillar J extends to the `_DAEMON_VERSION` constant + the daemon container image; the W9 commit's observer + gauge wiring does NOT affect the supply-chain surface.

### W9 migration / rollout

**Operator action: NONE.**

Production operators invoking `init_daemon(DaemonConfig(...))` at v1 see the observer registered silently at Step 8.5 + the gauge registered silently at Step 9.5. Subsequent `Ledger.append` calls trigger the in-place index invalidation; per-Person primitive consumers (the W8-D361 kwarg-bearing primitives) see the post-append state without operator intervention.

Pre-Week-9 callers of `init_daemon` see the W9 wiring transparently — the new internal helpers + Step 8.5 + Step 9.5 are silent extensions. The `DaemonRunner.ledger` field defaults to `None` for tests + external dispatchers constructing `DaemonRunner` directly without `ledger=` kwarg.

ZERO new ledger migrations at Week 9 (pending stays at 19). The observer surface is an in-memory contract; no schema change.

### W9 existing-operator seed

Operators preview the W9 surface via:

```python
from orchestrator.daemon import init_daemon, DaemonConfig
from orchestrator.ledger import Ledger

runner = init_daemon(DaemonConfig(...))

# The W9 lift: the daemon's Ledger is on the runner.
assert isinstance(runner.ledger, Ledger)

# The W9 invalidation observer is registered; appends mutate the indexes.
runner.ledger.append({"type": "enrolled", "person_id": "p-abc-123"})

# Index reflects the post-append state without restart.
enrolled = runner.event_class_index.events_for_class("enrolled")
assert len(enrolled) == 1  # Was 0 before the append.

# The freshness gauge per ADR-0067 D363 advanced.
import time
age = time.time() - runner.event_class_index._last_updated_at_ts
assert age < 1.0  # sub-second freshness at v1 single-tenant.
```

Operators wanting custom observer registration (Pillar I per-tenant audit-log mirror; Pillar J GDPR purge cascade) call `runner.ledger.append_observer(my_callback)` after `init_daemon` returns — the observer fires per append in registration order.

### Per-week-reviewer disciplines status after Pillar H Week 9 main

| Discipline | Status after W9 main |
|---|---|
| Cell-level matrix coverage | **THIRTY-TWO** consecutive weeks (+27 net new W9 daemon contract tests 271 → 298 — TestLedgerAppendObserverSeam × 6 + TestInvalidateIndexesOnAppend × 6 + TestInstallIndexInvalidationObserver × 4 + TestEventClassIndexLastUpdatedAtTs × 3 + TestDaemonRunnerLedgerField × 2 + TestInitDaemonStep8_5IndexInvalidationWiring × 3 + TestObservabilityRegisterDaemonIndexObservableGauge × 3) |
| Behavioral-passthrough-not-signature-only | **TWENTY-NINE** consecutive weeks (the W9 commit's `TestInstallIndexInvalidationObserver::test_register_then_append_invalidates_event_class_index` + `test_post_invalidation_state_equals_materialization_per_byte_identical_determinism` regression-barriers exercise the production-default `_install_index_invalidation_observer` body END-TO-END on real `Ledger` substrate + verify the post-append state matches the materialization-from-scratch post-condition per ADR-0031 D140's byte-identical determinism contract; the W9 `test_init_daemon_registers_observer_on_daemons_ledger` exercises the production-default `init_daemon` Step 8.5 wiring) |
| Module-level docstring drift | **THIRTY-ONE** consecutive weeks (runner.py + `__init__.py` + observability.py + ledger.py module docstrings ALL extended naming Pillar H Week 9 + ADR-0067 D362-D363; per_daemon.yml header + dashboard description + carry-forwards section extended naming W9 panel #6) |
| Per-pillar mirror constants parity | EXTENDED — the W9 invalidation observer's `known_classes` set MATCHES the W8 follow-up P2-1 closure's union `EVENT_CLASS_CATALOG ∪ OBSERVABILITY_NEW_EVENT_CLASSES`; the per-pillar mirror constants parity discipline preserves verbatim through the per-append invalidation site. ZERO new closed-sets at W9 (the invalidation contract consumes existing closed-sets) |
| Cross-pillar back-audit | EXTENDED — the Week 9 author verified ADR-0067 W9 extension narrative claims (D362 observer seam + D363 gauge) match the actual implementation BEFORE commit per the SEVEN-consecutive Pillar H weeks of ADR-vs-actual-impl drift catches at W2 → W8 follow-up; the per-week-reviewer at Phase 3 catches any EIGHTH drift |
| Framework-neutrality contract | PRESERVED via the observer registration's per-Ledger-instance scope + the OTel SDK `ObservableGauge` primitive following the existing `register_reconcile_success_ratio_gauge` + `register_event_class_observable_counter` precedent. Operators wanting alternative concurrency models (threading / trio / gevent) for the observer fire still MUST fork the function body per the per-pillar-H precedent. |
| Privacy invariant | CONFIRMED — the W9 observer fires with the same serialized event dict the ledger holds; the index stores event dicts (no new fields). The `PersonEventIndex` keyed by `person_id` is daemon-process-local + rebuildable-from-ledger per I3 (unchanged from W8). The Prometheus gauge value is a Unix-epoch timestamp (NOT person-data; operator-private operationally). |
| Atomicity-preservation per ADR-0060 D335 invariant 2 | OPERATIONALLY ENFORCED at W9 — the observer fires AFTER fsync + symlink + mtime-cache invalidation; the ledger is durable BEFORE the index updates. Observer exceptions log to stderr but do NOT propagate; a daemon crash BETWEEN fsync + observer fire leaves the ledger consistent + the index re-materializable from I3 at restart. |
| Byte-identical determinism per ADR-0031 D140 | OPERATIONALLY ENFORCED at W9 — the per-event invalidation post-condition equals the materialization-from-scratch post-condition (the structural mirror at `_invalidate_indexes_on_append` body); pinned by `TestInstallIndexInvalidationObserver::test_post_invalidation_state_equals_materialization_per_byte_identical_determinism`. |
| Cross-process consistency | DOCUMENTED v1 single-tenant + concurrent-CLI gap — observers are per-Ledger-instance; cross-process appends NOT visible until daemon restart re-materializes. Pillar I per-tenant trajectory MAY add a cross-process invalidation channel. |

---

## Pillar H Week 9 follow-up addendum (per per-week-reviewer findings on commit `fb0196d`)

The per-week independent review of the Week 9 main commit surfaced **0 P1 + 3 P2 + 6 P3 + 1 NEW addressed + 4 REFUTED**. The W9 follow-up closes each per the per-pillar-foundation precedent (Pillar G Week 12 follow-up `43612a8` + Pillar H Week 1-8 follow-ups). ZERO new ADRs (the closures are in the spirit of ADR-0067's existing decisions per the per-week-reviewer's follow-up convention).

**P2-1 closure — the EIGHTH ADR-vs-actual-impl drift in Pillar H caught by the per-week-reviewer's cross-pillar back-audit discipline.** The W9 main commit's narrative claimed "renumbered Step 10 DaemonRunner construction" at FOUR sites (commit message body + `orchestrator/daemon/runner.py:322` module docstring + `orchestrator/daemon/runner.py:2742` `_install_index_invalidation_observer` docstring + `orchestrator/daemon/__init__.py:327` public-surface section + `orchestrator/ledger.py:12` module docstring + `docs/adr/0067-...md:416` W9 extension addendum) but the actual code at `runner.py:3832` still labels DaemonRunner construction as Step 9 (no renumber occurred at W9 — the gauge registration at Step 9.5 inserts AFTER existing Step 9 NOT renumbering it). The W9 follow-up aligns the narrative to match the code at all five sites + the ADR addendum. The drift is at the narrative level (NOT the actual implementation, so milder than W5 P1-1 or W7 P1-1 which broke production-default behavior) but still operator-confusing for readers consulting the ADR + the module docstrings for the step ordering. Cross-pillar back-audit discipline EXTENDED to EIGHT consecutive Pillar H weeks of ADR-vs-actual-impl drift catches (W2 P3-8 OTel Resource → W3 P2-1 `_emitted_by` → W4 P2-1 framework-neutrality → W5 P1-1 `traced_stage` signature → W6 P2-2 Step 5.5 ordering → W7 P1-1 Pass G classifier dependency → W8 follow-up P2-1 EventClassIndex catalog scope → **W9 follow-up P2-1 Step 9/Step 10 narrative drift**); the per-week-reviewer pattern's structural value is now empirically validated at EIGHT consecutive Pillar H weeks.

**P2-2 closure — `_default_dispatch_for_stage` fallback path regression-barrier gap.** The W9 main commit introduced the fallback branch (`if runner.ledger is not None: led = runner.ledger; else: led = Ledger(runner.config.ledger_dir)`) but verified ONLY the production-default path via `test_default_dispatch_for_stage_uses_runner_ledger_when_present`. The fallback semantic (`runner.ledger is None` → lazy-construct + appends on the fallback Ledger do NOT trigger the daemon-process index invalidation observer) was UNTESTED. A future Week-N author refactoring the fallback (e.g., removing the `else` branch + making `runner.ledger` non-optional) would NOT break any existing test — exactly the failure mode the W5 P1-1 + W7 P1-1 closures' behavioral-passthrough-not-signature-only discipline exists to catch. CLOSED via NEW `TestW9FollowupDefaultDispatchFallbackPath::test_default_dispatch_for_stage_lazy_constructs_ledger_when_runner_ledger_is_none` cell — constructs DaemonRunner DIRECTLY (NOT via init_daemon) so `runner.ledger=None`; triggers dispatch + verifies (a) a NEW Ledger is lazy-constructed for `runner.config.ledger_dir`; (b) the fallback Ledger has NO registered observers (cross-process consistency note rationale: appends here would NOT trigger the daemon-process invalidation; operators see stale data).

**P2-3 closure — `Ledger.append_observer` non-callable refuse-loud at boundary.** The W9 main commit's `append_observer` body silently accepted non-callable observers; the failure surfaced ONLY at first append time as a stderr WARNING `... raised TypeError: '<type>' object is not callable`. This violates the per-pillar-H raw-primitive refuse-loud-at-boundary discipline established by the W2 follow-up P2-2 closure (`build_*_payload` factories refuse-loud) + the W3 follow-up P2-1 closure (factory-boundary stamping). CLOSED via `Ledger.append_observer` body extended with `if not callable(observer): raise TypeError(...)` boundary check naming Pillar H Week 9 follow-up P2-3 closure + the per-pillar-H raw-primitive refuse-loud-at-boundary discipline + NEW regression-barrier tests at `TestW9FollowupAppendObserverRefuseLoud` (test_register_non_callable_raises_type_error_at_boundary verifies list / dict / None all raise; test_register_callable_does_not_raise verifies lambda / function / bound method all accepted).

**P3-1 closure — `PersonEventIndex._last_updated_at_ts` docstring test-name attribution drift.** The W9 main commit's `PersonEventIndex._last_updated_at_ts` docstring at `runner.py:1282` referenced `TestIndexInvalidationOnLedgerAppend::test_both_indexes_share_last_updated_at_ts` but the actual test class is `TestEventClassIndexLastUpdatedAtTs` and the actual test name is `test_both_indexes_share_last_updated_at_ts_at_v1_per_lockstep_invariant`. CLOSED via docstring correction at runner.py:1282; mirrors the W8 follow-up P3-1 + P3-2 closures' discipline at the same site (test-name attribution drifts caught at consecutive follow-ups).

**P3-2 closure — `observability.EVENT_CLASS_CATALOG` "Last reviewed" line bump at W9.** The W9 main commit MATERIALLY changed `observability.py` (+~130 LOC including `register_daemon_index_observable_gauge` + `_INSTRUMENT_NAME_DAEMON_INDEX_LAST_UPDATED_TIMESTAMP` constant) but did NOT bump the EVENT_CLASS_CATALOG "Last reviewed" line at `observability.py:504` (still said "Pillar H Week 6 follow-up commit"). Per the W3 follow-up P3-5 closure's discipline-scope extension to materially-changed modules + the W6 follow-up NEW-1 closure precedent (the "Last reviewed" line is the operator-facing audit cadence surface), CLOSED via bumping to "2026-05-27 (Pillar H Week 9 follow-up commit; ADR-0067 D362-D363 W9 extension addendum + Pillar H Week 9 follow-up P3-2 closure; 25 entries UNCHANGED at W9 — the W9 commit's invalidation contract per ADR-0067 D362 consumes the existing closed-set without extending the catalog)".

**P3-3 closure — `DaemonRunner.ledger` field declaration narrative-vs-code drift.** The W9 main commit message claimed "Default `field(default=None)`" but the actual code at `runner.py:1391` uses bare `ledger: "Ledger | None" = None` (functionally identical for dataclass behavior). The bare-assignment pattern is consistent with the existing `DaemonRunner.lifecycle_state: str = "initializing"` field (line 1302) which also uses bare `= "initializing"`. CLOSED via the W9 follow-up module docstring extension naming the bare-assignment consistency with the existing `lifecycle_state` field pattern + naming the narrative-vs-code drift in the W9 main commit message. The code preserves verbatim (the bare assignment is operator-readable + the pattern stays consistent with the existing field).

**P3-4 closure — `now_ts_fn` test-only seam threaded through `init_daemon`.** The W9 main commit's `_install_index_invalidation_observer(led, ec_idx, pe_idx, now_ts_fn=time.time)` had a test-only `now_ts_fn` seam, but `init_daemon` did NOT thread it through. Tests that need deterministic timestamps for the W9 freshness gauge through the FULL `init_daemon` path couldn't inject — they had to bypass init_daemon + call `_install_index_invalidation_observer` directly. CLOSED via NEW `init_daemon` kwarg `invalidation_now_ts_fn: Callable[[], float] = time.time` threaded through to the Step 8.5 observer registration + NEW regression-barriers at `TestW9FollowupInitDaemonInvalidationNowTsFnSeam` (test_init_daemon_threads_invalidation_now_ts_fn_to_observer + test_init_daemon_default_invalidation_now_ts_fn_is_time_time). The seam follows the Pillar G TEST-ONLY embed_fn convention + the Pillar H Week 2-8 precedent.

**P3-5 closure — `_invalidate_indexes_on_append` partial-mutation invariant documented.** The W9 main commit's `_invalidate_indexes_on_append` body's four sub-steps (event_class_index mutation → person_event_index mutation → `now_ts_fn` call → timestamp assignment to both indexes) are NOT atomic; if `now_ts_fn()` raises (production default `time.time` does NOT raise in practice; test-only deterministic-clock fakes MAY raise), the per-index `_data` mutations have already occurred + propagate to operators querying the index; the `_last_updated_at_ts` fields stay at their PRIOR values. The failure-mode posture "data updated, timestamps stale" was NOT documented at the docstring. CLOSED via `_invalidate_indexes_on_append` docstring extension naming the partial-mutation invariant + the "data updated, timestamps stale" failure-mode + the production-default-safety note (`time.time()` does NOT raise so the partial-mutation window is test-only at v1).

**P3-6 closure — `_install_index_invalidation_observer` `known_classes` documentation clarification.** The W9 main commit's `_install_index_invalidation_observer` docstring claimed "The `known_classes` set is computed ONCE at registration time (frozenset is immutable; the `OBSERVABILITY_NEW_EVENT_CLASSES` + `EVENT_CLASS_CATALOG` are module-level constants that don't mutate at runtime)" — technically correct but operator-confusing because the captured set is the UNION (computed at the function call site, producing a NEW frozenset) NOT either operand directly. CLOSED via docstring rephrasing naming the union-at-call-time semantic + the module-level frozenset operands' immutability per the Pillar G + Pillar H closed-set discipline.

**NEW-1 closure — ADR-0067 W9 extension addendum example code annotation consistency.** The W9 main commit's `_invalidate_indexes_on_append` signature at `runner.py:2664` used string-quoted forward reference `known_classes: "frozenset[str]"` while the ADR-0067 W9 extension addendum's example at line 400 used bare `known_classes: frozenset[str]`. Both are valid (the `from __future__ import annotations` at `runner.py:473` makes the string quotes redundant) but operator-readability suffers from the inconsistency. CLOSED via unquoting at the function signature to bare `frozenset[str]` (aligned with the ADR example + with the `from __future__ import annotations` semantics).

**REFUTED #1** — Observer exception logging at `Ledger.append` test pollution concern. Verified that the existing `TestLedgerAppendObserverSeam::test_observer_exception_does_not_propagate_per_durability_contract` test uses `capfd` to capture + assert the WARNING text; other tests don't register failing observers → no test pollution. The 4147 → 4150 follow-up test count run shows no pollution.

**REFUTED #2** — Best-effort gauge registration at Step 9.5 test pollution concern. Verified that `init_daemon` with `otel_meter_init_fn=lambda *a, **kw: None` test substrate returns the global NoOp meter from `get_meter()`; `meter.create_observable_gauge(...)` returns a no-op gauge silently — no exception, no stderr pollution.

**REFUTED #3** — Atomicity invariant per ADR-0060 D335 invariant 2 concern. Verified by careful re-reading of `Ledger.append` body: fsync → fcntl unlock → close → ensure_symlink → mtime invalidation → observer fire loop. Observer fires AFTER the durable fsync; observer exception caught + logged; ledger durable contract preserved.

**REFUTED #4** — Byte-identical determinism per ADR-0031 D140 concern. Verified by `TestInstallIndexInvalidationObserver::test_post_invalidation_state_equals_materialization_per_byte_identical_determinism` — exercises cross-pillar event mix + asserts observer-driven indexes equal from-scratch materialized indexes.

### Per-week-reviewer disciplines status after W9 follow-up

| Discipline | Status after W9 follow-up |
|---|---|
| Cell-level matrix coverage | **THIRTY-THREE** consecutive weeks (+5 net new W9 follow-up daemon contract tests 298 → 303 — `TestW9FollowupDefaultDispatchFallbackPath::test_default_dispatch_for_stage_lazy_constructs_ledger_when_runner_ledger_is_none` × 1 + `TestW9FollowupAppendObserverRefuseLoud` × 2 + `TestW9FollowupInitDaemonInvalidationNowTsFnSeam` × 2) |
| Behavioral-passthrough-not-signature-only | **THIRTY** consecutive weeks (the W9 follow-up P2-2 closure's `test_default_dispatch_for_stage_lazy_constructs_ledger_when_runner_ledger_is_none` exercises the fallback path's actual `_default_dispatch_for_stage` body END-TO-END WITHOUT the daemon-process invalidation observer; the P3-4 closure's `test_init_daemon_threads_invalidation_now_ts_fn_to_observer` exercises the `invalidation_now_ts_fn` kwarg END-TO-END through init_daemon Step 8.5) |
| Module-level docstring drift | **THIRTY-TWO** consecutive weeks (W9 follow-up extends runner.py + __init__.py + ledger.py + observability.py "Last reviewed" line ALL naming Pillar H Week 9 follow-up + the EIGHT closure categories) |
| Per-pillar mirror constants parity | EXTENDED — the W9 follow-up P3-2 closure's "Last reviewed" bump preserves the per-pillar mirror constants parity discipline (the catalog still 25 entries; the W9 main commit + follow-up did NOT extend the catalog); ZERO new closed-sets at W9 follow-up |
| Cross-pillar back-audit | EXTENDED to **EIGHT consecutive Pillar H weeks** of ADR-vs-actual-impl drift catches (W2 P3-8 → W3 P2-1 → W4 P2-1 → W5 P1-1 → W6 P2-2 → W7 P1-1 → W8 follow-up P2-1 → **W9 follow-up P2-1**); the per-week-reviewer pattern's structural value is empirically validated at EIGHT consecutive Pillar H weeks |
| Framework-neutrality contract | PRESERVED via per-Ledger-instance observer scope + the OTel SDK ObservableGauge primitive |
| Privacy invariant | CONFIRMED — the W9 follow-up does NOT alter PersonEventIndex's daemon-process-local + rebuildable-from-ledger posture; the boundary refuse-loud at `Ledger.append_observer` does NOT introduce any new persistent state |
| Atomicity-preservation per ADR-0060 D335 invariant 2 | OPERATIONALLY ENFORCED at W9 follow-up — the boundary refuse-loud at registration time does NOT alter the `Ledger.append` body's observer-fire ordering |
| Byte-identical determinism per ADR-0031 D140 | OPERATIONALLY ENFORCED at W9 follow-up — the `invalidation_now_ts_fn` seam preserves the deterministic-clock contract; tests injecting deterministic timestamps through the full init_daemon path get byte-identical reproducibility |
| Cross-process consistency | DOCUMENTED v1 single-tenant + concurrent-CLI gap (unchanged from W9 main); the W9 follow-up P2-2 closure's fallback-path regression-barrier explicitly verifies the "no observer firing on fallback Ledger" semantic |
