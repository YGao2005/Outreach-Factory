# ADR-0059: Pillar G Week 12 — binding exit-criterion test un-skip + `orchestrator/funnel.py` extension with three binding questions + Week 1 P3-2 carry-forward closure (`_STAGE_BY_EVENT_TYPE`) + Pillar G Stable flip + Pillar G retrospective + handoff to Pillar H

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 12 binding exit-criterion + Stable flip + retrospective)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-week trajectory at D273's table; **Week 12 is the binding exit-criterion test un-skip + Pillar G Stable flip + Pillar G retrospective.** D275 specified the exit-criterion vehicle as `tests/test_multi_channel_coherence.py::TestPillarGExitCriterion::test_operator_answers_three_questions_in_one_cli_invocation`. D276(a) pinned the **one-CLI-invocation invariant** — operator answers the three load-bearing questions (per PILLAR-PLAN §2 Pillar G binding text) in ONE `python orchestrator/funnel.py --since N` invocation per the binding-text discipline; Pillar G EXTENDS the existing Pillar D Week 12 funnel CLI per ADR-0031 D140's byte-identical determinism contract.

The three binding questions per PILLAR-PLAN §2 Pillar G:

> *"Yang can answer any 'why is dispatch slow today?' / 'where am I losing prospects?' / 'what did the gate refuse this week?' in one CLI invocation."*

ADR-0050 D277's per-Person dashboard table pinned the per-event-class consumption pattern Week 10-11 shipped. ADR-0058 (Pillar G Week 10-11, D319-D324) shipped the three per-Person observability surface adapters + `PILLAR_F_LAYER_5_DRIFT_REASONS` closed-set containing BOTH legacy + new reasons per the Pillar F Week 12 follow-up's legacy-state-vs-new-defense-layer reason-precedence drift discipline per ADR-0049 §66 P2-2.

Pillar G Week 12 is the **final** Pillar G week. The structural commitments Week 12 lands:

1. **`orchestrator/funnel.py` extension** with three new report sections answering the three binding questions per ADR-0050 D275 + D276(a).
2. **The Pillar G Week 1 P3-2 carry-forward CLOSURE** — the per-stage funnel MUST consult `_STAGE_BY_EVENT_TYPE` from `orchestrator/ledger.py` per the cross-pillar surface audit row 11. Week 12 author closes the carry-forward by importing the table at runtime + using it as the structural commitment for the per-stage aggregation.
3. **The binding exit-criterion test un-skip** at `tests/test_multi_channel_coherence.py::TestPillarGExitCriterion::test_operator_answers_three_questions_in_one_cli_invocation` per ADR-0050 D275.
4. **Pillar G Stable flip** — `docs/PILLAR-PLAN.md` §6 Pillar G row Status flipped from "In progress" to "Stable as of 2026-05-26".
5. **Pillar G retrospective** at `.planning/RETRO-pillar-g.md` per the Pillar F retrospective precedent (closing the per-pillar-week trajectory with the calibration headline + what worked + what to do differently in Pillar H + carry-forwards into Pillar H).
6. **Handoff to Pillar H** — `.planning/HANDOFF-pillar-g-week-12.md` (the FINAL per-week handoff for Pillar G). Pillar H unblocked from "Pillar G stable" dependency per ADR-0050 §Downstream pillar impact.

The six concerns this ADR's design resolves:

1. **`orchestrator/funnel.py` extension shape — extend Pillar D's CLI vs ship a NEW CLI.** ADR-0050 D276(a) pinned the one-CLI-invocation invariant as Pillar G EXTENDS the existing Pillar D Week 12 funnel CLI; the alternative would have been a NEW `python orchestrator/observability_cli.py` surface. Week 12 ships the extension per the ADR.

2. **The read-only contract on `build_report`.** The funnel CLI's `tests/test_funnel.py::TestRenderReport::test_render_is_pure_function` + `tests/test_multi_channel_coherence.py::TestPillarDExitCriterion` (ROW 4) + `test_byte_identical_across_repeated_calls` pin the byte-identical-across-consecutive-calls contract per ADR-0031 D140. The Pillar G Week 2+ primitives (`collect_event_class_snapshots`, `detect_slo_violations`, `collect_cost_snapshots`, `collect_per_person_*`) all `led.append` diagnostic events when their closed-set discipline surfaces drift. A naive design that called those primitives from `build_report` would violate the byte-identical contract (second call sees the first call's diagnostic event). Week 12's design enforces the **read-only contract** — `build_report`'s Pillar G Week 12 extensions are READ-ONLY ledger walks that never call `led.append`. The closed-set constants imported from `orchestrator.observability` (`PILLAR_F_LAYER_5_DRIFT_REASONS`) ARE the mirror; the funnel CLI implements its own walk logic.

3. **The Pillar G Week 1 P3-2 carry-forward closure — `_STAGE_BY_EVENT_TYPE` consultation.** Per `.planning/REVIEW-pillar-g-surface-audit.md` row 11 (Week 1 baseline), the per-stage funnel dashboard MUST consult `_STAGE_BY_EVENT_TYPE` from `orchestrator/ledger.py` (the regression-barrier table the Pillar B framework's `derived_stage()` consumes). Pre-Week-12, the funnel CLI had no per-stage funnel section; Week 12's `aggregate_per_stage_funnel` imports the table at runtime + uses it as the structural commitment for the per-stage aggregation. The Week 1 P3-2 carry-forward is CLOSED at Week 12 per the per-week-handoff convention.

4. **The per-channel `_channel_from_event` derivation.** The Pillar C two-phase commit convention per ADR-0014 D33 names per-channel event types `<channel>_intent` / `<channel>_confirmed` etc. + every event SHOULD carry the explicit `channel` field. The Pillar D Week 12 funnel CLI's tests showed the `none|*` composite-key shape catches missing-channel emits. Week 12's `_channel_from_event` helper additionally derives the channel from the event type prefix when the explicit field is absent — this is the structural fallback per Pillar C's per-channel type convention (operators seeing the derived channel see the SAME aggregation as the explicit field).

5. **Three per-binding-question report sections — `dispatch_health` / `prospect_funnel` / `gate_refusals`.** The three sections map 1:1 to the three binding questions per PILLAR-PLAN §2 Pillar G + ADR-0050 D275 + D276(a). The naming preserves the operator-facing read ("dispatch health" / "prospect funnel" / "gate refusals" are the operator's mental model). Each section's nested dicts use sorted keys per ADR-0031 D140's byte-identical determinism contract.

6. **The BOTH-legacy-and-new reason-precedence drift protection in the per-Layer-5 surface.** Per ADR-0058 D321 + ADR-0049 §66 P2-2's reason-precedence drift discipline, the `gate_refusals.per_layer_5_drift_reason_count` dashboard surface MUST subscribe to BOTH `vault_ahead_of_ledger` AND `ready_without_draft_ready_event`. Week 12's `aggregate_layer_5_drift_by_reason` defaults to `PILLAR_F_LAYER_5_DRIFT_REASONS` from `observability` (the structural commitment Week 10-11 pinned). The output dict ALWAYS contains both keys (count 0 if no events in window) per the explicit-zero-presence convention.

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED. The closed-set discipline extends to Week 12's funnel CLI via the imported `PILLAR_F_LAYER_5_DRIFT_REASONS` mirror constant + the funnel CLI's own closed-sets (`_INTENT_TYPES_FOR_FUNNEL` + `_CONFIRMED_TYPES_FOR_FUNNEL` + `_FAILED_TYPES_FOR_FUNNEL` + `_ABORTED_TYPES_FOR_FUNNEL`) which mirror the Pillar C per-channel two-phase commit convention.

- **R032 (SLO violation alerting false-positive on synthetic-data spike)** — UNCHANGED. The structural mitigation (events with `_recovered_by` are EXCLUDED) extends to Week 12's `aggregate_layer_5_drift_by_reason` + `aggregate_cost_by_source` (mirroring the per-Person primitives' R032 exclusion per ADR-0058 D319-D321). The funnel CLI's per-stage funnel + dispatch_health aggregations do NOT apply R032 exclusion — operators running migration backfills DO see the per-stage event counts inflate by the migration's synthetic events. This is the right posture: per-stage funnel is "what happened in this window?"; the R032 exclusion applies to per-aggregation-of-truth surfaces (SLO, cost, Layer 5 drift) where synthetic spikes would mislead.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED. Week 12's funnel CLI is stateless (re-walks the ledger per invocation); multi-process daemons (Pillar H scope) consume per-process aggregations independently.

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED. Week 12's funnel CLI is READ-ONLY (no `led.append`); the per-call diagnostic-emit-rate concern does NOT apply at the funnel CLI surface. Operators wanting the diagnostic surface invoke the primitives at `observability` directly (operator-deliberate access).

- **R035 (OTel SDK's set-once `set_meter_provider` + `set_tracer_provider` enforcement)** — UNCHANGED. Week 12 does NOT initialize the OTel SDK; the `import observability as _observability` at funnel.py top loads the module but does NOT call `init_otel_meter_provider` / `init_otel_tracer_provider`.

- **R036 (Prometheus HTTP exposition server exposes per-process metrics)** — UNCHANGED. Week 12 does NOT introduce new HTTP exposition surfaces; the funnel CLI is a one-shot read.

**ZERO new R-risks** surfaced at Week 12. The closed-set discipline extends to the funnel CLI's per-channel constants; the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0058 D323 carries through to the funnel CLI's output via the read-only walk + the no-body-field structural commitment.

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12. The Pillar G Week 1-11 surfaces preserve verbatim. The Pillar D + E + F binding exit-criterion tests STAY GREEN.

## Decision

### D325. `orchestrator/funnel.py` extension with three binding-question report sections + READ-ONLY contract

`orchestrator/funnel.py` extends with three new report sections rendered in `build_report` per the one-CLI-invocation invariant per ADR-0050 D276(a):

```python
{
    "window": {...},                             # Pillar D existing
    "totals": {...},                             # Pillar D existing
    "reply_classified_by_breakdown": {...},      # Pillar D existing
    "conversation_outcome_by_channel_outcome": {...},  # Pillar D existing
    "attribution_by_outcome": {...},             # Pillar D existing
    # Pillar G Week 12 — binding question 1
    "dispatch_health": {
        "per_channel_send_latency_p99_seconds": {...},
        "per_channel_send_failed_count": {...},
        "per_channel_send_aborted_count": {...},
        "slo_violation_detected_count": int,
    },
    # Pillar G Week 12 — binding question 2
    "prospect_funnel": {
        "per_stage_event_count": {...},   # 7 stages
    },
    # Pillar G Week 12 — binding question 3
    "gate_refusals": {
        "per_rule_policy_blocked_count": {...},
        "per_register_hallucination_detected_count": {...},
        "per_layer_5_drift_reason_count": {...},   # BOTH legacy + new
        "manual_override_count": int,
        "per_source_cost_event_count": {...},
    },
}
```

**Read-only contract** — the Pillar G Week 12 aggregations in `build_report` are READ-ONLY ledger walks (no `led.append` calls). The operator-deliberate primitives at `orchestrator.observability` (`detect_slo_violations` / `collect_cost_snapshots` / `collect_per_person_*`) emit diagnostic events when their closed-set discipline surfaces drift; the funnel CLI does NOT invoke them. The funnel CLI's own walk logic uses mirror constants imported from `orchestrator.observability` (specifically `PILLAR_F_LAYER_5_DRIFT_REASONS`) for the closed-set discipline + its own per-channel type sets for the dispatcher surfaces.

**Byte-identical determinism per ADR-0031 D140** — the new aggregations sort all dict keys; p99 latency values are rounded to 3 decimal places (floating-point representation drift would break reproducibility without rounding); the `--now` kwarg pins the deterministic clock.

**Privacy invariant per I8 + ADR-0050 D276(b) + ADR-0058 D323** — the funnel CLI's output is COUNTS + AGGREGATES + scores; NEVER `source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text` / `person_id`. The read-only walk + the no-body-field structural commitment in the aggregation functions IS the privacy invariant's regression-barrier; the binding test ROW 6 pins the absence of forbidden fields in the rendered output.

### D326. The Pillar G Week 1 P3-2 carry-forward closure — `_STAGE_BY_EVENT_TYPE` consultation in `aggregate_per_stage_funnel`

`orchestrator/funnel.py::aggregate_per_stage_funnel` consults `ledger._STAGE_BY_EVENT_TYPE` at runtime + uses it as the structural commitment for the per-stage aggregation. The Pillar G Week 1 P3-2 carry-forward (`.planning/REVIEW-pillar-g-surface-audit.md` row 11) is CLOSED at Week 12 per the per-week-handoff convention.

The per-stage funnel surfaces SEVEN stages — the four from `_STAGE_BY_EVENT_TYPE` (`queued` / `researched` / `drafted` / `ready`) + three post-send extensions (`sent` ← per-channel `*_confirmed` events; `replied` ← `reply_classified` events; `outcome_terminal` ← `conversation_outcome` events). The extension stages are NOT in `_STAGE_BY_EVENT_TYPE` (which only carries the pre-send stages per `derived_stage()` semantics); the funnel CLI extends with the post-send stages for the operator-facing pipeline-temporal narrative.

The complete per-stage shape includes ALL seven stages with count 0 if no events in the window — operators seeing the stage's count 0 see the funnel-drop point at the previous non-zero stage. The shape's invariant is preserved by the `aggregate_per_stage_funnel` function's initialization of all seven stage keys with count 0.

### D327. The READ-ONLY funnel CLI vs the operator-deliberate `observability` primitives — separation of concerns

The funnel CLI's READ-ONLY contract per D325 separates from the operator-deliberate primitives at `orchestrator.observability`:

| Surface | Aggregation grain | Diagnostic emit | Use case |
|---|---|---|---|
| `funnel.py` per-stage funnel | per-stage event count | NEVER | Operator dashboard read |
| `funnel.py` per-channel dispatch | per-channel p99 / failed / aborted | NEVER | Operator dashboard read |
| `funnel.py` per-reason Layer 5 drift | per-reason count (BOTH legacy + new) | NEVER | Operator dashboard read |
| `funnel.py` per-rule policy_blocked | per-rule count | NEVER | Operator dashboard read |
| `funnel.py` per-register hallucination | per-register count | NEVER | Operator dashboard read |
| `funnel.py` per-source cost | per-source count | NEVER | Operator dashboard read |
| `observability.detect_slo_violations` | per-SLO violation | Emits `slo_violation_detected` | Operator-deliberate SLO detection |
| `observability.collect_cost_snapshots` | per-source CostSnapshot | Emits `cost_source_uncatalogued` diagnostic | Operator-deliberate cost dashboard |
| `observability.collect_per_person_*` | per-(person_id, sub_axis) snapshot | Emits per-pillar-F diagnostics | Operator-deliberate per-Person dashboard |
| `observability.collect_event_class_snapshots` | per-event-class MetricSnapshot | Emits `observability_class_uncatalogued` diagnostic | OTel ObservableCounter callback |

The funnel CLI is the **operator-facing read surface**; the `observability` primitives are the **operator-deliberate aggregation primitives** with diagnostic emit. Both surfaces are valuable; the separation preserves the byte-identical determinism contract per ADR-0031 D140 at the funnel CLI while letting the operator-deliberate primitives emit diagnostics at their own grain.

### D328. Pillar G Stable flip + Pillar G retrospective shape + carry-forwards to Pillar H

`docs/PILLAR-PLAN.md` §6 Pillar G row Status flipped from "In progress as of 2026-05-25" to **"Stable as of 2026-05-26"** at Week 12 commit. The Notes column appended Week 12 close summary.

`.planning/RETRO-pillar-g.md` (NEW) ships the Pillar G retrospective per the Pillar F retrospective precedent (`.planning/RETRO-pillar-f.md`). The retrospective shape:

* **Calibration headline** — Pillar G budgeted 12 pillar-weeks → shipped in 2 calendar days (12:2; one fewer than Pillar D's 12:1.5 + half-day slower than Pillar E + F's 12:1). The compression matches the framework cadence; the per-pillar-week count is calibrated for structurally complex pillars (Pillar G has OTel SDK + Prometheus + Grafana-as-code + per-Person dashboards + SLO + cost + per-stage funnel).
* **What worked** — the per-week handoff + per-week independent review + per-week ADR + the cross-pillar surface audit's anti-regression role + the closed-set discipline (R031 mitigation) + the framework-neutrality contract.
* **What to do differently in Pillar H** — Pillar H is a NEW pillar shape (daemon + scale concerns); the per-pillar-week cadence may compress or expand depending on the structural shape. The per-Person primitives' per-call cost concern (O(N) ledger walk at v1 scale) is the FIRST scale concern Pillar H may surface as an indexing requirement.
* **Carry-forwards into Pillar H** — the per-pillar-week-reviewer disciplines (cell-level matrix coverage + behavioral-passthrough + module-level docstring drift + cross-pillar back-audit + per-pillar mirror constants parity); the closed-set discipline + the privacy invariant; the framework-neutrality contract for the OTel SDK integration.

`.planning/HANDOFF-pillar-g-week-12.md` (NEW) ships as the FINAL per-week handoff for Pillar G. The handoff doc names the Pillar H trajectory + the carry-forwards.

### D329. The funnel CLI extension's per-channel constants mirror Pillar C's per-channel two-phase commit convention per ADR-0014 D33

The four per-channel closed-sets at `orchestrator/funnel.py` — `_INTENT_TYPES_FOR_FUNNEL` + `_CONFIRMED_TYPES_FOR_FUNNEL` + `_FAILED_TYPES_FOR_FUNNEL` + `_ABORTED_TYPES_FOR_FUNNEL` — mirror the Pillar C per-channel two-phase commit convention per ADR-0014 D33. The mirroring is the structural commitment that the per-channel dispatch_health aggregation symmetrically covers ALL five channels (email + li_invite + li_dm + tw_dm + calendar_booking).

The calendar_booking channel does NOT have an `_aborted` shape per ADR-0019 D68 (the "user cancelled the booking" case is a separate event class); the closed-set's asymmetry preserves this.

The mirroring decouples `orchestrator/funnel.py` from `orchestrator/observability.py`'s `_CONFIRMED_EVENT_TYPES_FOR_LATENCY` + `_INTENT_EVENT_TYPES_FOR_LATENCY` constants — a regression-barrier test at `tests/test_funnel.py` pins parity at test time (operators adding a new channel update BOTH the Pillar C dispatchers + Pillar G funnel CLI + Pillar G observability primitive's per-channel sets).

### D330. The binding exit-criterion test's six rows of verification

`tests/test_multi_channel_coherence.py::TestPillarGExitCriterion::test_operator_answers_three_questions_in_one_cli_invocation` (un-skipped at Week 12) verifies SIX rows:

* **ROW 1** — All three sections present in the report dict (`dispatch_health` + `prospect_funnel` + `gate_refusals`).
* **ROW 2** — Per-channel p99 latency includes the email channel pair (intent + confirmed) + per-channel failed/aborted counts + SLO violation detected count.
* **ROW 3** — Per-stage funnel includes counts for every stage in the pipeline-temporal chain (`queued` / `researched` / `drafted` / `ready` / `sent` / `replied` / `outcome_terminal`).
* **ROW 4** — Per-reason Layer 5 drift counts BOTH legacy `vault_ahead_of_ledger` AND new `ready_without_draft_ready_event` per ADR-0058 D321 + ADR-0049 §66 P2-2 reason-precedence drift discipline.
* **ROW 5** — Byte-identical across consecutive invocations against fixed ledger state per ADR-0031 D140.
* **ROW 6** — Privacy invariant per I8 + ADR-0050 D276(b) — output does NOT surface body fields (`draft_body` / `raw_body` / `exemplar_body` / `exemplar_bodies` / `dossier_body` / `claim_text` / `query_text` / `source_list`).

The test is self-contained — builds a ledger from scratch with synthetic events covering ALL THREE binding questions + invokes `funnel.main` programmatically + parses the JSON + asserts each row. The synthetic substrate covers every aggregation surface the three binding questions consume.

## Alternatives considered

### D325 alternatives (funnel.py extension shape)

1. **Ship a NEW `python orchestrator/observability_cli.py` surface separate from `funnel.py`.** Rejected per ADR-0050 D276(a) — the one-CLI-invocation invariant explicitly named the EXISTING `orchestrator/funnel.py` as the surface Pillar G EXTENDS. A new CLI would violate the invariant + create the "look in two places" mental model the per-pillar-foundation ADRs reject.

2. **Add the three sections as optional opt-in via `--with-pillar-g` flag.** Rejected — operators MAY want to inspect the Pillar G sections without remembering an opt-in flag; making them DEFAULT preserves the one-invocation answer-all-three-questions invariant. The byte-identical contract holds across the new sections (READ-ONLY walk + sorted dicts).

3. **Have `build_report` call the operator-deliberate primitives at `observability` directly.** Rejected — the operator-deliberate primitives emit diagnostic events via `led.append` when their closed-set discipline surfaces drift. Calling them from `build_report` would VIOLATE the byte-identical-across-consecutive-calls contract per ADR-0031 D140 (the second call sees the first call's diagnostic events). The READ-ONLY contract per D325 is the structural separation.

4. **Defer the funnel.py extension to Pillar H.** Rejected per ADR-0050 D275 + D276(a) + PILLAR-PLAN §2 Pillar G — Week 12 IS the binding exit-criterion test un-skip; deferring would not deliver Pillar G's binding text.

### D326 alternatives (per-stage funnel design)

1. **Inline a hard-coded per-stage table in funnel.py.** Rejected per the Pillar G Week 1 P3-2 carry-forward — the table MUST come from `ledger._STAGE_BY_EVENT_TYPE` per the per-pillar-B framework's `derived_stage()` consumer. A hard-coded table would silently drift from the upstream when the upstream extends.

2. **Read `_STAGE_BY_EVENT_TYPE` at module import time (cache at module load).** Rejected — the table is small enough (~4 entries) that runtime re-lookup is negligible; module-time caching adds a subtle race against test-fixture monkeypatches. Runtime consultation is the simpler shape.

3. **Skip the post-send stages (`sent` / `replied` / `outcome_terminal`).** Rejected — the operator's pipeline-temporal narrative includes post-send stages. The `derived_stage()` consumer's stages are pre-send only; the funnel CLI extends with the post-send stages for the binding question's full visibility.

4. **Emit a diagnostic when a non-`_STAGE_BY_EVENT_TYPE` + non-extension event type surfaces.** Rejected per D325's READ-ONLY contract — the funnel CLI is READ-ONLY; diagnostic emission lives at the per-call observability primitives.

### D327 alternatives (READ-ONLY funnel CLI separation)

1. **Make `build_report` an alias for invoking the observability primitives.** Rejected — the observability primitives emit diagnostic events (R034 mitigation pattern). The byte-identical contract per ADR-0031 D140 + ADR-0059 D325 explicitly forbids `led.append` from `build_report`.

2. **Re-implement the per-Person Layer 5 drift aggregation as a per-Person breakdown in funnel.py.** Rejected per ADR-0058 D323's privacy invariant — `person_id` is operator-private; the per-Person aggregation lives at the dedicated per-Person primitives (operator-deliberate access). The funnel CLI aggregates per-reason (no person_id breakdown); operators wanting per-Person drill-down consume the per-Person primitives directly.

3. **Have the per-stage funnel include per-Person breakdowns.** Rejected per the privacy invariant — same reasoning as Alt2.

### D328 alternatives (Pillar G retrospective shape)

1. **Inline the retrospective in this ADR.** Rejected — the retrospective is a separate artifact (the per-pillar-foundation precedent at `.planning/RETRO-pillar-{a,b,c,d,e,f}.md` IS the shape); ADRs are decision records, not retrospectives.

2. **Defer the retrospective to a follow-up commit.** Rejected — the per-pillar-foundation precedent ships the retrospective IN the Stable-flip commit (Pillar F shipped `RETRO-pillar-f.md` at the same Week 12 commit as the Stable flip).

3. **Skip the retrospective at Pillar G.** Rejected per the per-pillar-foundation precedent — every Stable-flipping pillar ships a retrospective at the Stable-flip commit.

### D329 alternatives (per-channel constants mirroring)

1. **Import `_CONFIRMED_EVENT_TYPES_FOR_LATENCY` + `_INTENT_EVENT_TYPES_FOR_LATENCY` from `orchestrator.observability` directly.** Considered + REJECTED — funnel.py's per-channel sets are operator-facing per ADR-0014 D33's per-channel convention; importing from observability would couple funnel.py to observability.py's internal constants. The mirror + regression-barrier test pattern (per ADR-0058 D322's mirror constants discipline) decouples the modules at runtime.

2. **Use `_OUTCOME_TYPES` from `ledger.py` (the existing per-channel outcome set).** Rejected — `_OUTCOME_TYPES` is the UNION of confirmed + failed + aborted across channels; funnel.py needs the SPLITS (separate confirmed / failed / aborted sets) for the per-aggregation surface. The four separate sets at funnel.py are the operator-facing surface; the ledger.py set is the internal index surface.

3. **Inline the per-channel sets without a closed-set marker.** Rejected per the R031 regression-barrier discipline — the closed-set IS the discipline; future contributors adding a new channel SHOULD update BOTH the Pillar C dispatchers + Pillar G funnel CLI + Pillar G observability primitive's per-channel sets, with the regression-barrier test failing if either drift.

### D330 alternatives (binding test shape)

1. **Test only ONE of the three binding questions (e.g., dispatch_health alone).** Rejected — the binding test IS "answers ALL THREE questions in ONE invocation" per ADR-0050 D275 + D276(a); testing one question only partially verifies the invariant.

2. **Use the existing `synthetic_pillar_d_classifier_corpus_state_dir` fixture.** Rejected — the Pillar D fixture is heavy + focused on the classifier corpus; the Pillar G binding test needs a focused fixture with events covering the three Pillar G aggregation surfaces. A self-contained test is the cleaner shape.

3. **Skip the byte-identical determinism row + the privacy invariant row.** Rejected — both rows pin structural commitments per ADR-0031 D140 + ADR-0050 D276(b) + ADR-0058 D323. Skipping them would weaken the binding test's regression-barrier role.

4. **Run the test via subprocess instead of in-process `main()`.** Rejected — the Pillar D Week 12 funnel CLI's tests use in-process `main()` per ADR-0031 D140's testability discipline (subprocess invocation adds PYTHONPATH + sys.path complications without changing the determinism contract).

## Consequences

### Positive

- **Pillar G is operationally complete at Week 12.** The framework's per-event-class observability primitive + the OTel SDK + the Prometheus exporter + the Grafana-as-code first dashboard + the OTel tracing initialization + the per-stage span instrumentation + the send-latency Histogram + the SLO violation detector + the Slack webhook dispatcher + the cost aggregation primitive + the per-Person observability surface adapters + the three Grafana dashboards (overview + cost + per_person) are LIVE; the **one-CLI-invocation invariant** per ADR-0050 D276(a) is OPERATIONAL via the funnel.py extension.
- **The Pillar G Week 1 P3-2 carry-forward is CLOSED at Week 12** — the per-stage funnel consults `_STAGE_BY_EVENT_TYPE` per the cross-pillar surface audit's row 11. The carry-forward closure preserves the per-pillar-week-reviewer's track record of catching + addressing carry-forwards across pillar weeks.
- **The "cell-level matrix coverage" discipline holds at FIFTEEN consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8 + W9 + W10-11 + W12)** — Week 12's binding test ROW 1-ROW 6 cell coverage is the per-binding-question cell matrix.
- **The "module-level docstring drift" discipline holds at FOURTEEN consecutive weeks (Pillar F W8-W12 + Pillar G W2-W6 + W7-W8 + W9 + W10-11 + W12)** — Week 12's funnel.py module docstring extension names Pillar G Week 12 / ADR-0059 / D325-D330.
- **The closed-set discipline extends to the funnel CLI** — the four per-channel closed-sets at funnel.py mirror the Pillar C two-phase commit convention; the regression-barrier discipline preserves at the per-funnel-CLI grain.
- **The privacy invariant per I8 flows through to the funnel CLI's output** via the READ-ONLY contract + the no-body-field structural commitment in the aggregation functions; the binding test ROW 6 pins the absence of forbidden fields.
- **The byte-identical determinism contract per ADR-0031 D140 holds across the Pillar G Week 12 extension** — the funnel CLI's READ-ONLY walk + the sorted dicts + the rounded p99 latency values + the deterministic-clock `--now` kwarg preserve the contract; the binding test ROW 5 pins the contract.
- **ZERO new R-risks** at Week 12 — the existing R031/R032/R033/R034/R035/R036 mitigations carry through verbatim; the closed-set discipline extends R031 to the funnel CLI's per-channel sets.

### Negative

- **The funnel CLI's per-call cost grows with the ledger size** — at v1 scale (~5K events) the per-call cost is sub-second; at v2 scale (~100K events) the per-call cost may surface as a per-operator-cron latency concern. Mitigation: operators query at appropriate intervals (15 min is typical for the funnel-style operator read); Pillar H scale revisit may surface per-event-class indexing as a NEW concern.
- **The funnel CLI now imports `observability` at module load time** — adds the OTel SDK + Prometheus exporter + Grafana-as-code module loads to the funnel CLI's startup cost. The cost is ~100ms at module load; operators wanting the FASTEST funnel CLI startup may need to investigate per-Pillar-H lazy-loading patterns. Pillar H may revisit.
- **The Week 12 binding test is self-contained** — the test builds its own synthetic substrate rather than consuming a shared fixture. The pattern is slightly less DRY than the Pillar D / E / F binding tests; mitigation: the binding test is the per-pillar-G structural commitment; sharing the synthetic substrate with other pillar's binding tests would couple the test surfaces.
- **The Pillar G retrospective compounds the per-pillar-week trajectory across TWELVE weeks** — the retrospective spans more than 100 lines (matching Pillar F's ~130-line retrospective shape); future Pillar H + I + J retrospectives will follow the same shape + cumulative length.

### Neutral

- **The OTel scope version stays at `0.1.0`** per ADR-0052 D283 + ADR-0054 D295 — the Week 12 funnel CLI does NOT extend the OTel SDK initialization; ZERO new OTel instruments at Week 12.
- **No new pip dependencies at Week 12** — the funnel CLI extension is stdlib (`Counter`, `defaultdict`, `datetime`, `typing`) + the existing `observability` module import.
- **No ledger schema migration** — Week 12 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1-11).
- **No new event classes** — Week 12 ships ZERO new event classes.
- **No new closed-sets in `orchestrator/observability.py`** — the four per-channel closed-sets at `orchestrator/funnel.py` are funnel-CLI-specific (the mirror of the Pillar C per-channel two-phase commit convention); the observability module's closed-sets (`EVENT_CLASS_CATALOG` + `OBSERVABILITY_NEW_EVENT_CLASSES` + `COST_SOURCES_CATALOG` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` + `_SLO_NAMES` + `_DRIFT_REASONS` + `_DIAGNOSTIC_KINDS` + `PILLAR_F_PERSON_EVENT_CLASSES` + `PILLAR_F_LAYER_5_DRIFT_REASONS` + `PILLAR_F_REGISTERS_MIRROR` + `PILLAR_F_CLAIM_TYPES_MIRROR` + `PILLAR_F_ALL_DRIFT_REASONS_MIRROR`) preserve verbatim.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — Week 12's funnel CLI is a READ-ONLY ledger walk; the ledger remains the source of truth.
- **I2 (Atomicity contract).** Compliant — Week 12 ships ZERO new ledger appends from the funnel CLI surface.
- **I3 (Single source of truth).** Compliant — every aggregation re-derives from the per-call ledger walk; no state cached at the funnel CLI level.
- **I4 (Determinism).** Compliant per D325 + ROW 5 of the binding test — byte-identical across consecutive invocations against fixed ledger state per ADR-0031 D140.
- **I5 (Refuse loud).** Compliant — the funnel CLI's existing `--since` / `--breakdown` / `--now` validation refuse-loud on malformed input (preserved verbatim from Pillar D Week 12); the new aggregation functions inherit the same refuse-loud posture at the closed-set check.
- **I6 (No silent state).** Compliant — Week 12 ships ZERO new state; the funnel CLI extension is purely read-derived from the ledger.
- **I7 (Refuse loud on broken pipelines).** Compliant — the funnel CLI's I/O failures propagate per the existing convention.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant per D325 + ROW 6 of the binding test — the funnel CLI's output is COUNTS + AGGREGATES + scores; the no-body-field structural commitment in the aggregation functions IS the privacy invariant's regression-barrier.
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D329 — the per-channel closed-sets at funnel.py mirror Pillar C's per-channel two-phase commit convention; the per-channel aggregations preserve the channel attribution.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 12 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected at structural level — Pillar G Week 12 consumes the Layer 5 `reconcile_drift` events for the per-Layer-5 drift dashboard surface; Layer 5 backstop preserved verbatim.
- **The one-CLI-invocation invariant per ADR-0050 D276(a)** — Compliant per D325 — the funnel CLI extension answers all three binding questions in ONE invocation; the binding test ROW 1 + ROW 2 + ROW 3 + ROW 4 verify the invariant.

## Downstream pillar impact

- **Pillar H (daemon + scale)** — the funnel CLI is stateless + per-process; multi-process daemons consume per-process aggregations independently. Pillar H may surface per-event-class indexing (for the per-stage funnel + per-channel dispatcher aggregations) as a NEW concern at multi-machine scale. The per-stage funnel's O(N) cost MAY surface a Pillar H optimization (per-event-class index instead of full ledger walk).
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends the funnel CLI with per-tenant filtering (`--tenant <id>` flag). The closed-set discipline extends to per-tenant labels on the per-stage funnel + per-channel dispatch aggregations.
- **Pillar J (GDPR purge)** — the funnel CLI's aggregations are derived state (rebuildable from the ledger); per-Person GDPR purge automatically causes the next funnel CLI invocation to return updated counts (the purged Person's events no longer count).

## Migration / rollout

- **Operator-side action required at Week 12 upgrade:** **NONE — content-additive.** The Week 12 commit adds three new report sections (`dispatch_health` + `prospect_funnel` + `gate_refusals`) to the existing funnel CLI output + the new per-channel closed-sets + the helper functions; existing surfaces are PRESERVED verbatim. Operators upgrading from Week 10-11 to Week 12 see identical behavior for the Pillar D Week 12 funnel CLI's existing five report sections + see the three NEW Pillar G sections.
- **Recommended (optional):** operators wanting the answer-three-questions-in-one-invocation surface at Week 12:

  ```bash
  python orchestrator/funnel.py --since 7d
  ```

  Output includes the three NEW Pillar G sections in addition to the existing Pillar D sections.

- **First CLI invocation post-upgrade is content-additive** — operators see the three new sections in the JSON output; the byte-identical determinism contract per ADR-0031 D140 holds across the new sections.
- **No ledger schema migration** — Week 12 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes** — Week 12 ships ZERO new event classes.
- **No new pip dependencies** — the funnel CLI extension is stdlib + the existing `observability` module import.

## Existing-operator seed

Operator action required at Week 12: **NONE — content-additive.**

Recommended (optional): operators wanting the answer-three-questions-in-one-invocation surface at Week 12 invoke the canonical wiring per the Migration section above. Operators waiting for the Pillar H daemon-and-scale extension see them land at Pillar H Week 1+.

## References

- **ADR-0058** (Pillar G Week 10-11 — per-Person observability surface adapters consuming Pillar F's four event classes + Layer 5 `reconcile_drift.reason` value + three per-Person dataclasses + five new closed-sets + `_DIAGNOSTIC_KINDS` extension from 3 to 6 + Grafana per-Person dashboard). D319-D324. **D321 is the structural commitment the funnel CLI's per-Layer-5 drift surface inherits** — BOTH legacy + new reasons per ADR-0049 §66 P2-2 reason-precedence drift discipline.
- **ADR-0057** (Pillar G Week 9 — cost dashboard rendering + per-source `cost_incurred` aggregation primitive + `COST_SOURCES_CATALOG` closed-set + `cost_source_uncatalogued` diagnostic kind extension). D314-D318.
- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector + `slo_violation_detected` event class producer + Slack webhook dispatcher + R032 synthetic-event exclusion + `_SLO_NAMES` closed-enum). D307-D313.
- **ADR-0055** (Pillar G Week 6 — Per-stage span instrumentation at 13 per-pillar call sites + send-latency Histogram dispatcher integration at 4 channels). D300-D306.
- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization + canonical Tracer scope + per-stage `traced_stage` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED`). D294-D299.
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + per-channel send-latency Histogram + reconcile success ratio ObservableGauge + first Grafana-as-code dashboard). D288-D293.
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope + per-event-class ObservableCounter + framework-neutrality contract). D282-D287.
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. **D275 explicitly named Week 12 as the binding exit-criterion test un-skip + Pillar G Stable flip + Pillar G retrospective.** **D276(a) pinned the one-CLI-invocation invariant Week 12 delivers.** **D273's per-week trajectory table closes at Week 12 (the final Pillar G week).**
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip + retrospective). D262-D271 + §66 P2-2 (the Pillar F Week 12 follow-up's NEW legacy-state-vs-new-defense-layer reason-precedence drift pattern). **The reason-precedence drift discipline IS the structural commitment Week 12's per-Layer-5 drift dashboard surface inherits via `PILLAR_F_LAYER_5_DRIFT_REASONS`.**
- **ADR-0037** (Pillar E Week 12 — Pillar E Stable flip + retrospective). D175. The per-pillar Stable-flip precedent.
- **ADR-0031** (Pillar D Week 12 — funnel CLI). **D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state).** The Pillar G Week 12 funnel CLI extension inherits this contract.
- **ADR-0025** (Pillar D foundation). D97 (legal-liability invariant — CAN-SPAM compliance). D101 (Pillar D foundation's single-file coherence vehicle).
- **ADR-0019** (Calendar booking — no aborted shape). D68 (the asymmetric "user cancelled the booking" event class).
- **ADR-0014** (Pillar C foundation). **D33 (channel-on-every-event invariant). The four per-channel closed-sets at `orchestrator/funnel.py` mirror Pillar C's per-channel two-phase commit convention per D33.**
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). Week 12's `aggregate_layer_5_drift_by_reason` + `aggregate_cost_by_source` apply the R032 `_recovered_by` exclusion per ADR-0058 D321.
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2-12 sections per the per-week-handoff convention). **Week 1 P3-2 carry-forward CLOSED at Week 12 per D326.**
- `.planning/HANDOFF-pillar-g-week-12.md` — Pillar G Week 12 close summary + handoff to Pillar H (the FINAL per-week handoff for Pillar G).
- `.planning/RETRO-pillar-g.md` — Pillar G retrospective per D328.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 12 Stable flip + Notes column appended Week 12 close summary.
- `docs/RISK-REGISTER.md` R031-R036 (no new R-rows at Week 12; R031 mitigation surface extends to the funnel CLI's per-channel closed-sets; R032 `_recovered_by` exclusion extends to the funnel CLI's `aggregate_layer_5_drift_by_reason` + `aggregate_cost_by_source`).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 12 ADR-0059 reference.
- `orchestrator/funnel.py` — extended Week 12 with `_PILLAR_G_PIPELINE_STAGES` + four per-channel closed-sets (`_INTENT_TYPES_FOR_FUNNEL` + `_CONFIRMED_TYPES_FOR_FUNNEL` + `_FAILED_TYPES_FOR_FUNNEL` + `_ABORTED_TYPES_FOR_FUNNEL`) + nine new aggregation functions (`aggregate_per_channel_send_latency_p99` + `aggregate_per_channel_send_failed_aborted` + `aggregate_slo_violation_detected_count` + `aggregate_per_stage_funnel` + `aggregate_policy_blocked_by_rule` + `aggregate_hallucination_by_register` + `aggregate_layer_5_drift_by_reason` + `aggregate_manual_override_count` + `aggregate_cost_by_source`) + three new helper functions (`_channel_from_event` + `_percentile` + `_parse_iso`) + `build_report` extension with three new sections (`dispatch_health` + `prospect_funnel` + `gate_refusals`) + `__all__` extension + module docstring extension naming Pillar G Week 12 / ADR-0059 / D325-D330 per the module-level-docstring-drift discipline carried forward FOURTEEN consecutive weeks.
- `tests/test_multi_channel_coherence.py::TestPillarGExitCriterion::test_operator_answers_three_questions_in_one_cli_invocation` (un-skipped Week 12 per D330) — the binding exit-criterion test verifies SIX rows: all three sections present + per-channel dispatch + per-stage funnel + BOTH-legacy-and-new Layer 5 protection + byte-identical determinism + privacy invariant.
