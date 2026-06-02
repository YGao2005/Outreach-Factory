# ADR-0058: Pillar G Week 10-11 — per-Person observability surface adapters consuming Pillar F's four event classes + the Layer 5 `reconcile_drift.reason` value + per-`(person_id, register)` voice-fidelity snapshot + per-`(person_id, claim_type)` hallucination snapshot + per-`(person_id, reason)` Layer 5 drift snapshot + `_DIAGNOSTIC_KINDS` extension to 6 + per-Person Grafana dashboard

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 10-11 per-Person observability surface)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape + the OTel SDK + Prometheus exporter + Grafana-as-code framework decision per D273. D273's per-week trajectory table named **Week 10-11 as the per-Person observability surface adapters consuming Pillar F event classes + Layer 5 `reconcile_drift.reason`**.

D277 specifically pinned the consumption pattern:

> Per-Person dashboard rows (Pillar G Week 10-11 ships rendering):
>
> | Pillar G dashboard surface | Consumes | Filter / aggregation |
> |---|---|---|
> | Per-register fidelity-score distribution | `draft_quality_scored.voice_fidelity_score` | per-register |
> | Per-claim-type hallucination count | `hallucination_detected.uncited_claims` | per-claim-type — COUNTS only, not trace per I8 |
> | Per-Layer hallucination-detection refusal count | Cross-event aggregate (Layer 1 = test-only; Layers 2-5 from `hallucination_detected` + `draft_quality_scored` + Layer4GuardRefusal-via-`draft_ready` absence + `reconcile_drift.reason == "ready_without_draft_ready_event"`) | per-Layer breakdown |
> | Per-Person Layer 5 drift rate | `reconcile_drift.reason == "ready_without_draft_ready_event"` | per-Person aggregation; surfaces Layer 4 emit-guard bypass operationally |

ADR-0049 (Pillar F Week 12) shipped the FIVE-layer defense closing at Layer 5 backstop per D262. The Pillar F Week 12 follow-up commit `1489d09` surfaced a NEW pattern at §66 P2-2 — the **legacy-state-vs-new-defense-layer reason-precedence drift** pattern:

> P2-2 silent semantic drift from vault_ahead_of_ledger reason to Layer 5 reason on vault=ready+ledger=drafted+no-draft_ready — pre-Week-12 a Person with vault=ready + ledger=drafted l_rank=2 < v_rank=4 surfaced reason: vault_ahead_of_ledger at the existing branch; post-Week-12 the Layer 5 check at lines 1152-1158 PRE-EMPTS that branch whenever vault_stage == "ready" regardless of l_rank because ratifies_ready = vault_stage == "ready" OR ... short-circuits; the same Person with no draft_ready event now surfaces reason: ready_without_draft_ready_event; the ADR-0049 §65 audit treated the new reason as "unknown" to existing consumers — but operators / Pillar I audit-tooling filtering on vault_ahead_of_ledger LOSE visibility of refusals that previously surfaced under that reason.

The implication for Pillar G Week 10-11: the per-Person Layer 5 drift dashboard MUST subscribe to BOTH `vault_ahead_of_ledger` AND `ready_without_draft_ready_event` reason values to preserve operational visibility across the reason-precedence drift.

ADR-0051 (Pillar G Week 2, D278-D281) shipped the `collect_event_class_snapshots` body + the `observability_class_uncatalogued` diagnostic emit + R034 mitigation (diagnostic emit at every primitive call inflates ledger when catalog drift persists). The at-most-ONE-per-kind-per-call rate-limit pattern is the structural pattern Week 10-11 inherits for THREE new diagnostic kinds (per-pillar-F catalog drift).

ADR-0057 (Pillar G Week 9, D314-D318) shipped the `collect_cost_snapshots` per-source aggregation primitive + the `cost_source_uncatalogued` diagnostic kind extension (extended `_DIAGNOSTIC_KINDS` from 2 to 3). Week 10-11 further extends `_DIAGNOSTIC_KINDS` from 3 to 6 per the per-pillar catalog discipline.

Pillar G Week 10-11 ships the **per-Person observability surface adapters** that consume Pillar F's four event classes (`voice_exemplar_retrieved` + `hallucination_detected` + `draft_quality_scored` + `draft_ready`) + the Layer 5 `reconcile_drift.reason` value per ADR-0049 D262 + ADR-0050 D277. The six concerns this ADR resolves:

1. **Per-`(person_id, register)` voice-fidelity aggregation grain.** PILLAR-PLAN §6 Pillar G row + ADR-0050 D277 names the per-register fidelity distribution dashboard. The framework MUST decide WHERE the aggregation happens — at the existing `collect_event_class_snapshots` (per-event-class grain), at a NEW sibling primitive `collect_per_person_register_fidelity_snapshots` (per-(person_id, register) grain). The existing primitive's `MetricSnapshot.per_breakdown_counts` is `dict[str, int]` — counts only; it CANNOT carry the per-event `voice_fidelity_score` distribution stats (min / max / sum). A dedicated per-Person primitive IS the cleanest seam.

2. **`PersonRegisterFidelitySnapshot` + `PersonClaimTypeHallucinationSnapshot` + `PersonLayer5DriftSnapshot` dataclasses.** Three per-Person dashboard surfaces; each gets its own frozen dataclass with the per-(person_id, sub_axis) shape. The dataclasses mirror the `MetricSnapshot` + `CostSnapshot` per-Pillar-G-primitive convention but scope to per-Person + sub-axis.

3. **Privacy invariant on the per-Person surfaces.** The per-Person primitives aggregate by `person_id` — which IS the dashboard's purpose per ADR-0050 D277. The privacy invariant per I8 + ADR-0038 D182 category 8 + ADR-0050 D276(b) requires the dataclass fields surface COUNTS + SCORES only; NEVER `draft_body` / `exemplar_body` / `dossier_body` / `claim_text` / `query` / `source_list`. The dataclass shape IS the structural commitment.

4. **`PILLAR_F_LAYER_5_DRIFT_REASONS` closed-set containing BOTH legacy + new reasons.** Per the Pillar F Week 12 follow-up's reason-precedence drift discipline per ADR-0049 §66 P2-2 — the per-Person Layer 5 drift dashboard MUST subscribe to BOTH `vault_ahead_of_ledger` (the pre-Week-12 reason that the Layer 5 check PRE-EMPTS) AND `ready_without_draft_ready_event` (the new canonical Layer 5 backstop reason). Operators using EITHER reason alone LOSE visibility across the post-Week-12 reason-precedence drift.

5. **Per-pillar-F catalog drift diagnostic kinds.** Three new diagnostic kinds extend `_DIAGNOSTIC_KINDS` from 3 to 6: `pillar_f_register_uncatalogued` + `pillar_f_claim_type_uncatalogued` + `pillar_f_drift_reason_uncatalogued`. Reuses the existing `observability_class_uncatalogued` event class per ADR-0051 D279 (single event class for catalog-drift diagnostics; per-kind discriminator via `kind` field). At-most-ONE per kind per call per R034 mitigation.

6. **Mirror constants `PILLAR_F_REGISTERS_MIRROR` + `PILLAR_F_CLAIM_TYPES_MIRROR` + `PILLAR_F_ALL_DRIFT_REASONS_MIRROR`.** The per-Person primitives' closed-set enforcement requires consulting the upstream closed-sets at `voice_corpus.REGISTERS` + `draft_quality.CLAIM_TYPES` + `reconcile._DRIFT_REASONS`. Mirror constants at `orchestrator/observability.py` keep the module decoupled from the upstream pillars at runtime; regression-barrier tests pin parity at test time.

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED + EXTENDED. The closed-set discipline (`EVENT_CLASS_CATALOG` + `OBSERVABILITY_NEW_EVENT_CLASSES` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` + `_SLO_NAMES` + `COST_SOURCES_CATALOG`) extends with `PILLAR_F_PERSON_EVENT_CLASSES` + `PILLAR_F_LAYER_5_DRIFT_REASONS` + `PILLAR_F_REGISTERS_MIRROR` + `PILLAR_F_CLAIM_TYPES_MIRROR` + `PILLAR_F_ALL_DRIFT_REASONS_MIRROR` at Week 10-11. The closed-set IS the R031-shape regression-barrier extended to the per-Person observability surface — a future contributor adding a NEW register / claim_type / drift_reason without coordinating with the closed-set triggers the appropriate diagnostic emit (operator-visible signal).

- **R032 (SLO violation alerting false-positive on synthetic-data spike)** — UNCHANGED. The structural mitigation (events with `_recovered_by` are EXCLUDED) extends to ALL THREE per-Person primitives — operators running migration backfills do NOT see synthetic-data spikes inflate the per-Person dashboards. The exclusion preserves the per-operator per-Person dashboard signal.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED. Week 10-11's three primitives are stateless (re-walk the ledger per call); multi-process daemons (Pillar H scope) consume per-process aggregations independently.

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED + EXTENDED. Week 10-11's three new diagnostic kinds follow the at-most-ONE-per-kind-per-call rate-limit pattern from ADR-0051 D279; the per-call emit rate caps at 1 per kind. Worst case: 6 diagnostic kinds × 1440 calls/day = ~8640/day per single-tenant operator (up from ~4320/day at Week 9). Same order-of-magnitude as the existing kinds; ledger daily rotation per `events-YYYY-MM-DD.jsonl` absorbs the load.

- **R035 (OTel SDK's set-once `set_meter_provider` + `set_tracer_provider` enforcement)** — UNCHANGED. Week 10-11 consumes the existing global MeterProvider via the per-event-class ObservableCounter filtered by event_class ∈ `PILLAR_F_PERSON_EVENT_CLASSES`; ZERO new OTel SDK initialization at Week 10-11.

- **R036 (Prometheus HTTP exposition server exposes per-process metrics)** — UNCHANGED. Week 10-11 does NOT introduce new HTTP exposition surfaces; the Grafana per-Person dashboard panels render via PromQL queries against the existing exposition.

ZERO new R-risks surfaced at Week 10-11. The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 + ADR-0055 D303 + ADR-0056 D311 + ADR-0057 D314 preserves the operator-choice posture; the closed-set discipline per the three new closed-sets + three mirror constants extends the R031-shape regression-barrier to the per-Person observability surface; the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0051 D278 + ADR-0052 D284 + ADR-0053 D292 + ADR-0054 D297 + ADR-0055 D304 + ADR-0056 D308 + ADR-0057 D316 carries through to the per-Person dataclass shapes via the structural commitment (NO body fields).

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12. The Pillar G Week 1-9 surfaces preserve verbatim.

## Decision

### D319. Per-`(person_id, register)` voice-fidelity aggregation primitive — `collect_per_person_register_fidelity_snapshots(led, *, since, now, expected_registers)`

`orchestrator/observability.py::collect_per_person_register_fidelity_snapshots` is the canonical per-call per-`(person_id, register)` voice-fidelity aggregation primitive. The function walks the ledger via `Ledger.all_events()`, filters `type == "draft_quality_scored"`, applies the per-call window filter (`ts >= since_iso`) + the R032 synthetic-event exclusion (events with `_recovered_by` are skipped), aggregates per `(person_id, register)` pair, and returns a list of `PersonRegisterFidelitySnapshot` sorted by `(person_id_or_empty, register)` for deterministic output per ADR-0031 D140.

```python
def collect_per_person_register_fidelity_snapshots(
    led: Ledger,
    *,
    since: datetime,
    now: datetime | None = None,
    expected_registers: frozenset[str] = PILLAR_F_REGISTERS_MIRROR,
) -> list[PersonRegisterFidelitySnapshot]:
```

**Stateless contract** per ADR-0050 D272 + R033 mitigation — no in-process cache; every call re-walks the ledger.

**R032 synthetic-event exclusion** per ADR-0056 D311 + ADR-0057 D314 — events carrying `_recovered_by` are EXCLUDED from the per-Person fidelity aggregation.

**Deterministic-clock contract** per ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265 + ADR-0051 D278 + ADR-0056 D311 + ADR-0057 D314.

**Channel-on-every-event invariant** per ADR-0014 D33 — `PersonRegisterFidelitySnapshot.channel` is the single non-null channel value if every in-window event for the pair carries the same channel; `None` otherwise.

**Per-state breakdown** — the snapshot carries `ready_count` + `refused_count` per ADR-0045 D229's `DraftFidelityResult.state` enum. Operators see per-(person_id, register) accept-vs-refuse cadence.

**Score distribution stats** — the snapshot carries `total_fidelity_score` (sum) + `min_fidelity_score` + `max_fidelity_score`. Operators compute the mean via `total / event_count`. For per-(person_id, register) distribution operators want richer stats (e.g., median, percentiles), they consume the ledger directly via `Ledger.all_events_for_person` + filter by event class.

**`PersonRegisterFidelitySnapshot` frozen dataclass:**

```python
@dataclass(frozen=True)
class PersonRegisterFidelitySnapshot:
    person_id: str | None        # None for ad-hoc validation events
    register: str                # one of PILLAR_F_REGISTERS_MIRROR
    channel: str | None          # homogeneous per ADR-0014 D33
    event_count: int             # count of draft_quality_scored events
    total_fidelity_score: float  # sum of voice_fidelity_score
    min_fidelity_score: float | None
    max_fidelity_score: float | None
    ready_count: int             # count of state == "ready"
    refused_count: int           # count of state == "refused"
    oldest_ts: str | None
    newest_ts: str | None
```

### D320. Per-`(person_id, claim_type)` hallucination aggregation primitive — `collect_per_person_claim_type_hallucination_snapshots`

`orchestrator/observability.py::collect_per_person_claim_type_hallucination_snapshots` walks the ledger via `Ledger.all_events()`, filters `type == "hallucination_detected"`, walks each `uncited_claims[].claim_type` entry per ADR-0043 D219's emit-only-on-uncited posture, aggregates per `(person_id, claim_type)` pair, and returns a list of `PersonClaimTypeHallucinationSnapshot` sorted by `(person_id_or_empty, claim_type)` for deterministic output.

```python
def collect_per_person_claim_type_hallucination_snapshots(
    led: Ledger,
    *,
    since: datetime,
    now: datetime | None = None,
    expected_claim_types: frozenset[str] = PILLAR_F_CLAIM_TYPES_MIRROR,
) -> list[PersonClaimTypeHallucinationSnapshot]:
```

**Per-claim walking** — each `hallucination_detected` event carries an `uncited_claims` list (Pillar F Week 6 emits when non-empty per ADR-0043 D219). The primitive walks each entry + aggregates per `(person_id, claim_type)` pair. ONE event with multiple uncited claims of the SAME type contributes `event_count=1` + `uncited_claim_count=<entry count>` to that pair (the event_count tracks "how many events for this Person mentioned this claim_type"; uncited_claim_count tracks "how many uncited claims of this type across those events"). ONE event with multiple uncited claims of DIFFERENT types contributes one snapshot per claim_type.

**Same contracts as D319** — stateless, R032 exclusion, deterministic-clock, channel/register homogeneity.

**`PersonClaimTypeHallucinationSnapshot` frozen dataclass:**

```python
@dataclass(frozen=True)
class PersonClaimTypeHallucinationSnapshot:
    person_id: str | None
    claim_type: str              # one of PILLAR_F_CLAIM_TYPES_MIRROR
    channel: str | None          # homogeneous
    register: str | None         # homogeneous; None if heterogeneous
    event_count: int             # count of hallucination_detected events
    uncited_claim_count: int     # total uncited_claims of this type
    oldest_ts: str | None
    newest_ts: str | None
```

### D321. Per-`(person_id, reason)` Layer 5 drift aggregation primitive — `collect_per_person_layer_5_drift_snapshots`

`orchestrator/observability.py::collect_per_person_layer_5_drift_snapshots` walks the ledger via `Ledger.all_events()`, filters `type == "reconcile_drift"`, applies the per-call window filter + R032 synthetic-event exclusion, filters by `subscribed_reasons` (default `PILLAR_F_LAYER_5_DRIFT_REASONS` = BOTH `vault_ahead_of_ledger` + `ready_without_draft_ready_event`), aggregates per `(person_id, reason)` pair, and returns a list of `PersonLayer5DriftSnapshot` sorted by `(person_id_or_empty, reason)`.

```python
def collect_per_person_layer_5_drift_snapshots(
    led: Ledger,
    *,
    since: datetime,
    now: datetime | None = None,
    subscribed_reasons: frozenset[str] = PILLAR_F_LAYER_5_DRIFT_REASONS,
    known_reasons: frozenset[str] = PILLAR_F_ALL_DRIFT_REASONS_MIRROR,
) -> list[PersonLayer5DriftSnapshot]:
```

**Three-tier reason classification:**

1. **Reason in `subscribed_reasons`** → AGGREGATED into per-pair snapshot.
2. **Reason in `known_reasons` but NOT in `subscribed_reasons`** → SILENTLY SKIPPED (intentional — those drift surfaces are NOT Layer 5 backstop concerns; e.g., `vault_has_stage_but_ledger_empty` is Pass C bootstrap drift). Operators consume that signal via OTHER dashboards.
3. **Reason NOT in `known_reasons` at all** → contributes to `pillar_f_drift_reason_uncatalogued` diagnostic kind (schema drift; at-most-ONE emit per call per R034 mitigation).

**Pillar F Week 12 follow-up's reason-precedence drift pattern per ADR-0049 §66 P2-2.** The default `PILLAR_F_LAYER_5_DRIFT_REASONS` set contains BOTH `vault_ahead_of_ledger` AND `ready_without_draft_ready_event` to preserve operational visibility across the post-Week-12 Layer 5 PRE-EMPTION precedence. The structural commitment is pinned by `test_pillar_f_layer_5_drift_reasons_includes_both_legacy_and_new` at `tests/test_observability.py`.

**`PersonLayer5DriftSnapshot` frozen dataclass:**

```python
@dataclass(frozen=True)
class PersonLayer5DriftSnapshot:
    person_id: str | None
    reason: str                  # one of PILLAR_F_LAYER_5_DRIFT_REASONS
    event_count: int
    oldest_ts: str | None
    newest_ts: str | None
```

### D322. `_DIAGNOSTIC_KINDS` extension from 3 to 6 values + mirror constants

`_DIAGNOSTIC_KINDS` closed-set extends from 3 to 6 values at Week 10-11:

```python
_DIAGNOSTIC_KINDS: frozenset[str] = frozenset({
    "uncatalogued",                       # Week 2
    "missing_ts",                         # Week 2
    "cost_source_uncatalogued",           # Week 9
    "pillar_f_register_uncatalogued",     # Week 10-11 NEW
    "pillar_f_claim_type_uncatalogued",   # Week 10-11 NEW
    "pillar_f_drift_reason_uncatalogued", # Week 10-11 NEW
})
```

**Single event class** — all three new kinds reuse the existing `observability_class_uncatalogued` event class per ADR-0051 D279. Operators consuming the per-event-class observability surface (per ADR-0050 D272) see all six kinds via a single event class filter; the per-kind discriminator is the `kind` field. The single-event-class shape preserves the per-pillar foundation's closed-set at TWO members (`OBSERVABILITY_NEW_EVENT_CLASSES = {"observability_class_uncatalogued", "slo_violation_detected"}`) — Week 10-11 does NOT extend the event class set.

**Diagnostic payload schema** for the three new kinds:

```jsonc
{
    "type": "observability_class_uncatalogued",
    "ts": "<ISO 8601 UTC>",
    "kind": "pillar_f_register_uncatalogued",
    "offending_value": "<first-seen unknown register>",
    "count": <int>,
    "channel": null,
    "_emitted_by": "observability"
}
```

The `offending_value` field carries the first-seen unknown value (operators investigate the producer); the `count` field carries the total seen in the call.

**At-most-ONE per kind per call** per ADR-0051 D279 + R034 mitigation pattern. The per-call diagnostic rate-limit caps the per-call emit rate at 1 per kind. Worst case (6 kinds × 1440 calls/day = ~8640/day per single-tenant operator) is same order-of-magnitude as the existing kinds.

**Mirror constants:**

```python
PILLAR_F_REGISTERS_MIRROR: frozenset[str] = frozenset({
    "cold-pitch", "congrats", "re-engagement", "reply", "public-comment",
})  # mirrors voice_corpus.REGISTERS per ADR-0038 D178

PILLAR_F_CLAIM_TYPES_MIRROR: frozenset[str] = frozenset({
    "date_reference", "named_entity", "you_phrase", "quoted_text", "dated_event",
})  # mirrors draft_quality.CLAIM_TYPES per ADR-0043 D214

PILLAR_F_ALL_DRIFT_REASONS_MIRROR: frozenset[str] = frozenset({
    "vault_has_stage_but_ledger_empty",
    "vault_ahead_of_ledger",
    "ready_without_draft_ready_event",
})  # mirrors reconcile._DRIFT_REASONS per ADR-0049 D263
```

**Mirror constants** decouple `orchestrator/observability.py` from the upstream pillars at runtime; regression-barrier tests pin parity at test time:

```python
def test_pillar_f_registers_mirror_matches_voice_corpus_registers():
    from orchestrator.voice_corpus import REGISTERS
    assert PILLAR_F_REGISTERS_MIRROR == REGISTERS
```

If the upstream closed-set drifts (e.g., a future contributor adds a new register without coordinating), the regression-barrier test fails — surfacing the structural commitment to update BOTH the upstream + the mirror.

### D323. Privacy invariant on the per-Person observability surface

The three per-Person primitives aggregate by `person_id` — which IS the dashboard's purpose per ADR-0050 D277. The privacy invariant per I8 + ADR-0038 D182 category 8 + ADR-0050 D276(b) requires:

**Allowed on the per-Person dataclass shapes:**

* `person_id` (the per-Person aggregation grain).
* `register` / `claim_type` / `reason` (the per-sub-axis aggregation grain).
* `channel` (per ADR-0014 D33 homogeneous channel-on-every-event).
* `event_count` / `uncited_claim_count` / `ready_count` / `refused_count` (counts).
* `total_fidelity_score` / `min_fidelity_score` / `max_fidelity_score` (scores).
* `oldest_ts` / `newest_ts` (time bounds).

**DISALLOWED on the per-Person dataclass shapes** per I8 + ADR-0038 D182 category 8:

* `draft_body` / `raw_body` — the prose content of the draft (operator-private).
* `exemplar_body` / `exemplar_bodies` — voice-corpus exemplar prose (operator-private).
* `dossier_body` — research dossier prose (operator-private).
* `claim_text` — per-claim trace text from `hallucination_detected.uncited_claims[].claim_text` (operator-private).
* `query` / `query_text` — raw query text from `voice_exemplar_retrieved` (operator-private).
* `source_list` — operator's curated discovery list names per ADR-0032 D148 (operator-private).
* `uncited_claims` — the full per-claim list from `hallucination_detected` (carries `claim_text`; operators consume per-Person trace via `Ledger.all_events_for_person`).
* `vault_stage` / `ledger_stage` — operator-private per-Person operational state.

**Structural commitment** — the dataclass shape IS the privacy invariant's regression-barrier. Tests pin the absence of forbidden fields:

```python
def test_person_register_fidelity_snapshot_has_no_body_fields(self):
    fields = PersonRegisterFidelitySnapshot.__dataclass_fields__.keys()
    forbidden = {"draft_body", "exemplar_body", "claim_text", ...}
    assert forbidden.isdisjoint(set(fields))
```

If a future contributor adds a body field, the test fails — operator-visible signal that the privacy invariant violated.

**Operators wanting per-Person body content** consume the ledger directly via `Ledger.all_events_for_person(person_id)` + filter by event class. The per-Person dashboard surface is COUNTS + SCORES; per-Person body content lives at the ledger query surface (operator-deliberate access).

### D324. Grafana per-Person dashboard `infra/grafana/dashboards/per_person.yml` + deterministic ordering contract

Week 10-11 ships `infra/grafana/dashboards/per_person.yml` (NEW) — operator-readable YAML describing five panels rendering the per-Person dashboard rows pinned at ADR-0050 D277:

1. **Per-register `draft_quality_scored` event rate (1h window)** — `rate(outreach_factory_events_total{event_class="draft_quality_scored"}[1h])` rendered as a time-series with per-channel legend. The aggregate signal; per-Person + per-register score distribution lives at the per-call `collect_per_person_register_fidelity_snapshots` primitive.
2. **Per-claim-type `hallucination_detected` event count (24h cumulative)** — `sum by (channel) (increase(outreach_factory_events_total{event_class="hallucination_detected"}[24h]))` rendered as a bar chart. Per-(person_id, claim_type) aggregation lives at the primitive.
3. **Per-Person Layer 5 drift rate (24h cumulative `reconcile_drift`)** — `sum by (channel) (increase(outreach_factory_events_total{event_class="reconcile_drift"}[24h]))` rendered as a bar chart. Per-(person_id, reason) aggregation lives at the primitive.
4. **Per-Person `voice_exemplar_retrieved` event rate (1h window)** — `rate(outreach_factory_events_total{event_class="voice_exemplar_retrieved"}[1h])`. Operators see per-DRAFT voice-corpus retrieval cadence (the upstream of per-DRAFT fidelity scoring).
5. **Per-channel `draft_ready` event count (24h cumulative)** — `sum by (channel) (increase(outreach_factory_events_total{event_class="draft_ready"}[24h]))`. Operators see per-channel Layer 4 emit-guard cadence.

The panels render via the Week 3 `outreach_factory_events_total` `ObservableCounter` per ADR-0052 D284 — the same OTel-side metric the overview + cost dashboards render, scoped to per-event-class filters. Per-Person drill-down is via `Ledger.all_events_for_person` per the privacy invariant per D323.

**Deterministic ordering** per ADR-0031 D140 + ADR-0051 D280 + ADR-0058 D324. All three per-Person primitives sort snapshots by `(person_id_or_empty, sub_axis)`:

* `person_id is None` sorts BEFORE Person-stamped (empty-string sentinel sorts first).
* Within each `person_id` group, sort by the per-snapshot sub-axis (`register` / `claim_type` / `reason`).

Byte-identical reproducibility across consecutive calls against a fixed ledger state holds when (a) ledger state is fixed; (b) `now` kwarg is fixed (diagnostic emit's ts field IS sensitive to `now`); (c) diagnostic emit's per-call rate-limiting holds.

## Alternatives considered

### D319 alternatives (per-Person register fidelity primitive grain)

1. **Extend `collect_event_class_snapshots` with a per-Person breakdown** (caller passes `breakdown_by=("person_id", "register")`). Rejected — the existing primitive's `MetricSnapshot.per_breakdown_counts` is `dict[str, int]` — counts only. Per-Person fidelity dashboard NEEDS richer stats: per-(person_id, register) `voice_fidelity_score` sum / min / max + per-state (`ready` / `refused`) counts. The counts-only shape cannot carry these. The dedicated primitive IS the per-grain-mismatch solution.

2. **Compute per-(person_id, register) aggregation inside the OTel SDK ObservableCounter callback** (the Week 3 per-event-class counter N-times-ifies per-(person_id, register) observations). Rejected — the OTel ObservableCounter grain is per-event-class (one observation per `MetricSnapshot`); coupling per-Person aggregation to the OTel callback would (a) N-times-ify per-scrape cost (one observation per (person_id, register) per scrape; at 1000 Persons × 5 registers = 5000 observations per scrape); (b) couple to operator-side Prometheus scrape interval; (c) violate the privacy invariant per ADR-0050 D276(b) (`person_id` is operator-confidential per I8 — putting it on the per-Counter observation surface would surface to Prometheus exposition, which operators may share externally). The per-call primitive surfaces per-Person aggregation at OPERATOR-DELIBERATE access; the OTel surface stays operator-aggregate.

3. **Make the primitive accept an arbitrary aggregation field (e.g., `aggregate_by_field="voice_fidelity_score"`).** Rejected — open-set generalization N-times-ifies the per-primitive contract surface; the per-(person_id, register) voice-fidelity aggregation is a named operator-facing concern per ADR-0050 D277. Future per-Person dashboards (e.g., per-(person_id, dispatcher_outcome) success-rate) follow the same per-pillar-foundation pattern — one ADR-named primitive per dashboard concern.

4. **Walk the per-Person index via `Ledger._idx_person` directly.** Rejected — the per-Person index is `Ledger.all_events_for_person`'s implementation detail; walking it directly couples the primitive to the index shape. `Ledger.all_events()` IS the canonical ledger walk per ADR-0050 D272's stateless contract; per-Person filtering happens at the primitive's `(person_id, register)` aggregation key.

### D320 alternatives (per-(person_id, claim_type) hallucination primitive)

1. **Aggregate per-event count instead of per-uncited-claim count.** Rejected — operators consuming the per-(person_id, claim_type) dashboard want to see "how many claims of THIS type slipped through for THIS Person" — that's the per-claim count, not per-event count. The snapshot carries BOTH `event_count` (how many events) + `uncited_claim_count` (how many uncited claims) so operators can compute per-event aggregation if needed.

2. **Include per-claim trace text in the snapshot.** Rejected per D323 privacy invariant — `claim_text` is operator-private per I8 + ADR-0043 D216. Operators inspect per-claim trace via the upstream `hallucination_detected.uncited_claims[].claim_text` field through `Ledger.all_events_for_person`.

3. **Skip the per-claim walking + just count events.** Rejected — loses the per-claim-type sub-axis fidelity. Operators wanting "how many `named_entity` slips for `person-001`" would have to walk the events themselves. The per-claim walking IS the dashboard's value.

### D321 alternatives (per-(person_id, reason) Layer 5 drift primitive)

1. **Subscribe to ALL reconcile_drift reasons (including `vault_has_stage_but_ledger_empty`).** Rejected — the per-Person Layer 5 drift dashboard is SPECIFICALLY about Layer 5 backstop visibility. The bootstrap drift reason is a DIFFERENT operational concern (vault has stage but ledger empty = bootstrap state divergence). Operators consume that signal via the overview dashboard or a separate per-Pass-C drift dashboard. Mixing them dilutes the per-Layer-5 signal.

2. **Subscribe to ONLY `ready_without_draft_ready_event` (the canonical Layer 5 reason).** Rejected per ADR-0049 §66 P2-2's reason-precedence drift discipline — operators using only the new reason LOSE visibility of refusals that the Layer 5 check PRE-EMPTS from `vault_ahead_of_ledger`. The dashboard MUST subscribe to BOTH to preserve operational visibility. The default closed-set IS the structural protection.

3. **Use a per-reason filter at the OTel SDK ObservableCounter level instead of a per-call primitive.** Rejected — same reasoning as D319-Alt2; the per-Person aggregation grain is operator-deliberate-access, not aggregate-export.

4. **Refuse-loud (raise ValueError) on non-subscribed-but-known reasons instead of silently skipping.** Rejected — refusing-loud would break the dashboard whenever operators have legitimate `vault_has_stage_but_ledger_empty` drift events in the ledger (which is normal Pass C behavior). The silent-skip-with-intentional-rationale IS the right posture; the diagnostic emit only fires on SCHEMA drift (reason NOT in any known set).

### D322 alternatives (diagnostic kinds + mirror constants)

1. **Add ONE composite diagnostic kind `pillar_f_person_uncatalogued` with `dimension` discriminator on payload.** Rejected — the at-most-ONE-per-kind-per-call rate-limit per R034 mitigation would apply at the SINGLE kind level, capping at 1 diagnostic per call across all three sub-domains. Operators investigating per-domain drift would have to filter the payload by `dimension` — extra cognitive load. Three distinct kinds + per-kind rate limit preserves per-domain visibility.

2. **Add THREE NEW event classes (extend `OBSERVABILITY_NEW_EVENT_CLASSES` from 2 to 5 members).** Rejected — extending the per-pillar foundation ADR's "new event classes" table is a load-bearing decision (the closed-set was named at ADR-0050 D273 with two members + extended via per-kind discriminator at ADR-0051 D279 + ADR-0057 D317). The kind-extension approach is content-additive at the per-kind level; the existing event class consumer surface preserves verbatim.

3. **Import upstream closed-sets directly instead of mirror constants.** Rejected — importing `voice_corpus.REGISTERS` + `draft_quality.CLAIM_TYPES` + `reconcile._DRIFT_REASONS` at observability.py runtime would force loading those modules whenever observability is imported (heavy if Pillar G is just being used for SLO detection). The mirror constants + test-time parity check decouples runtime + provides the regression-barrier.

4. **Define mirror constants but only check parity in production-side import (not in test).** Rejected — production-side parity checks would surface as runtime errors at the per-Person primitive's first call; test-time check surfaces at CI gate (faster feedback + structural commitment).

### D323 alternatives (privacy invariant on per-Person surface)

1. **Add `person_id` to `_BREAKDOWN_DIMS_ALLOWED` (allow per-Person breakdown on existing primitives).** Rejected per ADR-0032 D148 + ADR-0050 D276(b) + ADR-0057 D316 — `person_id` is operator-private; the existing primitives (per-event-class + cost) are operator-aggregate-only. The per-Person aggregation lives at the dedicated per-Person primitives (which are operator-deliberate-access — operators KNOW they're consuming per-Person data).

2. **Include forbidden fields on the per-Person dataclasses but redact at consumer surface.** Rejected — the dataclass shape IS the structural commitment; allowing forbidden fields on the shape + relying on consumer-side redaction creates a layered failure mode (a consumer skipping redaction silently surfaces operator-private data).

3. **Use the `_BREAKDOWN_DIMS_ALLOWED` closed-set + reject `person_id` at primitive runtime.** Rejected — the per-Person primitives DON'T have `breakdown_by` kwargs (their shape is fixed per-(person_id, sub_axis)). The structural commitment lives at the dataclass shape, not at a runtime kwarg validation.

### D324 alternatives (Grafana per-Person dashboard panel set)

1. **Add per-Person panels rendering per-Prometheus-label `person_id`.** Rejected — `person_id` is operator-private per I8; surfacing per-Person panels on the SHARED Grafana dashboard would surface operator-private data to anyone with dashboard access. Per-Person drill-down lives at the per-call primitive (operator-deliberate access via `collect_per_person_*`).

2. **Add per-register Grafana panels with PromQL label-filter on `register`.** Considered + DEFERRED — the OTel SDK's per-event-class ObservableCounter does NOT currently carry `register` as an attribute (only `channel`). Adding `register` as an attribute would inflate the OTel cardinality at exposition (per-(event_class, register, channel) tuples for the per-DRAFT classes). Future Pillar G week may extend; Week 10-11 ships the aggregate per-channel panels + the per-call per-Person primitives for richer drill-down.

3. **Add Grafana alert rules on per-Person dashboard panels.** Rejected at Week 10-11 — the per-Person dashboard is a dashboard, not an alerting surface. Operators wanting per-Person SLO alerting wire Grafana alert rules + the alerting integration. The Week 7-8 SLO violation detector is the SLO surface; Week 10-11 is the per-Person VISIBILITY surface.

4. **Use a single composite panel that combines all three per-Person dashboard rows.** Rejected — operators consuming per-register / per-claim-type / per-Layer-5-reason want INDEPENDENT visibility on each axis. A composite panel would force a chosen aggregation that loses per-axis fidelity.

## Consequences

### Positive

- **The framework's per-Person observability surface is now operationally complete at Week 10-11** — operators wiring `collect_per_person_register_fidelity_snapshots(led, since=parse_since("30d"))` see per-(person_id, register) voice-fidelity score distributions over the rolling window; `collect_per_person_claim_type_hallucination_snapshots` for per-(person_id, claim_type) hallucination uncited-claim counts; `collect_per_person_layer_5_drift_snapshots` for per-(person_id, reason) Layer 5 backstop drift counts.
- **The closed-set discipline per `PILLAR_F_PERSON_EVENT_CLASSES` + `PILLAR_F_LAYER_5_DRIFT_REASONS` + three mirror constants IS the R031-shape regression-barrier extended to the per-Person observability surface** — a future contributor adding a NEW register / claim_type / drift_reason without coordinating with the closed-set + the per-pillar ADR triggers refuse-loud at the appropriate diagnostic emit.
- **The privacy invariant per I8 + ADR-0050 D276(b) flows through to the per-Person observability surface** via the dataclass shape — `person_id` IS the aggregation grain (the dashboard's purpose), but `draft_body` / `exemplar_body` / `dossier_body` / `claim_text` / `query` / `source_list` / `uncited_claims` / `vault_stage` are STRUCTURALLY absent from the dataclass shapes. The privacy invariant tests pin the absence.
- **The legacy-state-vs-new-defense-layer reason-precedence drift discipline holds at NINE consecutive weeks (Pillar F W12 + Pillar G W2-W6 + W7-W8 + W9 + W10-11)** — Week 10-11 introduces `PILLAR_F_LAYER_5_DRIFT_REASONS` containing BOTH legacy + new reasons per the Pillar F Week 12 follow-up's discipline; the regression-barrier test `test_pillar_f_layer_5_drift_reasons_includes_both_legacy_and_new` pins the structural commitment.
- **The behavioral-passthrough-not-signature-only discipline holds at ELEVEN consecutive weeks (Pillar F W8-W11 + Pillar G W3-W6 + W7-W8 + W9 + W10-11)** — Week 10-11 tests capture per-call kwarg passthrough via behavioral verification (`TestWeek10_11BehavioralPassthrough` × 4 tests pass restricted `expected_registers` / `expected_claim_types` / `subscribed_reasons` / `known_reasons` + verify the aggregation actually changes).
- **The cell-level matrix coverage discipline holds at FOURTEEN consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8 + W9 + W10-11)** — Week 10-11 ships 86 new tests covering per-(person_id, register) × per-(person_id, claim_type) × per-(person_id, reason) × per-channel × per-state × per-R032-exclusion × per-uncatalogued × per-privacy-invariant × per-deterministic-clock × per-deterministic-ordering × per-precedence-drift-pattern cells.
- **The module-level docstring drift discipline holds at THIRTEEN consecutive weeks (Pillar F W8-W12 + Pillar G W2-W6 + W7-W8 + W9 + W10-11)** — the observability module docstring extension names Week 10-11 + ADR-0058 + the three per-Person primitive functions + the three dataclasses + the new closed-sets.
- **ZERO new R-risks** at Week 10-11 — the existing R031/R032/R033/R034/R035/R036 mitigations carry through verbatim; the closed-set discipline extends R031 to the per-Person surface; R032's `_recovered_by` exclusion extends to all three per-Person primitives.

### Negative

- **The per-call cost grows with the ledger size** — at v1 scale (~5K events) the per-call cost is sub-second; at v2 scale (~100K events) the per-call cost may surface as a per-cron-interval latency concern. Mitigation: operators query at appropriate intervals (1h is typical for per-Person dashboard refresh); Pillar H scale revisit may surface per-event-class indexing as a NEW concern.
- **Per-tenant per-Person attribution is deferred to Pillar I** — the Week 10-11 framework default is single-tenant per ADR-0050 D276(d); operators with multi-tenant per-Person attribution needs consume the per-Person ledger query surface for now. Pillar I per-tenant audit-tooling at OSS bring-up extends with per-tenant per-Person dashboards.
- **The Pillar F mirror constants require coordinated upstream + downstream updates** — a future contributor adding a new register / claim_type / drift_reason MUST update BOTH the upstream closed-set (voice_corpus / draft_quality / reconcile) AND the mirror at observability.py. Mitigation: the regression-barrier test fires at CI gate if the mirror drifts.
- **The test surface grows by 86 tests** — `tests/test_observability.py` ships 86 NEW tests covering the cell-level matrix; file size grows from ~6350 LOC to ~7400+ LOC, approaching the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266. Future Pillar G Week 12 may split.
- **The Week 10-11 ship does NOT add per-Person breakdown at the OTel ObservableCounter level** — the per-Person aggregation lives at the per-call primitive (operator-deliberate access). The Grafana per-Person dashboard renders aggregate per-channel signals; per-Person drill-down via the primitive's snapshot list.
- **`_DIAGNOSTIC_KINDS` extends from 3 to 6** — worst-case diagnostic emit rate doubles (was 3 kinds × 1440/day = 4320/day; now 6 kinds × 1440/day = 8640/day per single-tenant operator). Ledger absorbs the load; per-tenant Pillar I extension may surface as a concern at multi-tenant scale.

### Neutral

- **The OTel scope version stays at `0.1.0`** per ADR-0052 D283 + ADR-0054 D295 — the Week 10-11 per-Person primitives render via the existing `outreach_factory_events_total` ObservableCounter filtered by event class; ZERO new OTel instruments at Week 10-11.
- **No new pip dependencies at Week 10-11** — the three primitives + dataclasses + closed-sets are stdlib (`Counter`, `dataclasses.dataclass`, `datetime`, `typing`); the Grafana YAML is operator-readable text.
- **No ledger schema migration** — Week 10-11 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1-9). The four Pillar F event classes + `reconcile_drift` are ALREADY in `EVENT_CLASS_CATALOG` per ADR-0050 D272 (no recursive uncatalogued).
- **No new event classes** — Week 10-11 ships ZERO new event classes. The three new `kind` values reuse the existing `observability_class_uncatalogued` event class.
- **No new operator-facing CLI surfaces** — Week 10-11 does NOT extend `orchestrator/funnel.py` or any other CLI; operators invoke the three per-Person primitives programmatically OR consume via the Grafana per-Person dashboard. Week 12 may extend `funnel.py` to surface per-Person snapshots as part of the one-CLI-invocation binding exit-criterion test.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — per-Person events are emitted to the ledger; the per-Person dashboard's primitives walk the ledger.
- **I2 (Atomicity contract).** Compliant — the three primitives' diagnostic emit via `Ledger.append` for `observability_class_uncatalogued` events with the new `kind` values is atomic per the existing ledger append contract.
- **I3 (Single source of truth).** Compliant — every per-Person aggregation re-derives from the per-call ledger walk; no state cached at the primitive level.
- **I4 (Determinism).** Compliant — the `now` kwarg controls the deterministic-clock stamp on the diagnostic emit ts; the return list is sorted by `(person_id_or_empty, sub_axis)` for byte-identical reproducibility across consecutive calls against a fixed ledger state per ADR-0031 D140 + ADR-0051 D280 + ADR-0058 D324.
- **I5 (Refuse loud).** Compliant — three new diagnostic kinds enforce closed-set discipline on register / claim_type / drift_reason; unknown values trigger diagnostic emit.
- **I6 (No silent state).** Compliant — every per-Pillar-F-domain catalog drift is observable on the ledger (via the three new diagnostic kinds); the per-call rate-limit caps emission but ZERO events are silently dropped.
- **I7 (Refuse loud on broken pipelines).** Compliant — the primitives' per-event walk surfaces diagnostics for any unknown value; the diagnostic event surfaces operator-visible catalog drift signal.
- **I8 (Privacy invariant — operator-confidential fields).** Compliant per D323 — the per-Person dataclass shapes structurally EXCLUDE `person_id` aggregation breakdown on the per-event-class + cost primitives + EXCLUDE body / trace / query / source_list fields on the per-Person dataclass shapes themselves. The privacy invariant tests pin the absence.
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D319 + D320 — the per-Person dataclass `channel` field is the homogeneous channel value if every in-window event for the pair carries the same channel; None otherwise.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 10-11 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected at structural level — Pillar G Week 10-11 does not extend any of the five layers; Layer 5 backstop preserved verbatim. The per-Person Layer 5 drift dashboard CONSUMES the Layer 5 `reconcile_drift` events.

## Downstream pillar impact

- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — Week 12 composes the per-Person observability surface + the per-event-class observability dashboard + the per-channel send-latency histogram + the reconcile success ratio gauge + the SLO violation detector + the Slack webhook dispatcher + the cost dashboard into the one-CLI-invocation binding scenario per ADR-0050 D275 + PILLAR-PLAN §2 Pillar G's binding text. The `funnel.py --per-person` extension MAY surface per-Person snapshots as part of the one-CLI-invocation answer.
- **Pillar H (daemon + scale)** — the per-call per-Person primitives are stateless + per-process; multi-process daemons consume per-process aggregations independently. Pillar H may surface per-event-class indexing (for `draft_quality_scored` / `hallucination_detected` / `draft_ready` / `reconcile_drift`) as a NEW concern at multi-machine scale.
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling consumes the per-Person observability surface for:
  - per-operator override-rate dashboards (filtering `draft_ready.hallucination_check == "passed_via_override"` per ADR-0049 §Downstream pillar impact);
  - per-tenant Layer 5 drift-rate dashboards (consuming `PILLAR_F_LAYER_5_DRIFT_REASONS` per the same reason-precedence drift discipline);
  - per-tenant fuzzy_threshold tuning dashboards (consuming Pillar F per-claim-type bound tables per ADR-0048 D256 + the per-Person per-claim-type primitive's `uncited_claim_count` for calibration).
  - per-tenant labels on the per-Person metric for multi-tenant aggregation.
- **Pillar J (GDPR purge)** — per-Person events from the four Pillar F event classes + `reconcile_drift` are subject to per-Person GDPR purge per ADR-0049 §Downstream pillar impact. The Week 10-11 per-Person primitives' snapshots are derived state (rebuildable from the ledger); the per-Person GDPR purge transaction extends to purging per-Person event records, which automatically causes the per-Person primitives to return empty snapshots for the purged Person on the next call.

## Migration / rollout

- **Operator-side action required at Week 10-11 upgrade:** **NONE — content-additive.** The Week 10-11 commit adds three per-Person primitives + three dataclasses + five new closed-sets (`PILLAR_F_PERSON_EVENT_CLASSES` + `PILLAR_F_LAYER_5_DRIFT_REASONS` + `PILLAR_F_REGISTERS_MIRROR` + `PILLAR_F_CLAIM_TYPES_MIRROR` + `PILLAR_F_ALL_DRIFT_REASONS_MIRROR`) + extends `_DIAGNOSTIC_KINDS` from 3 to 6 + creates `infra/grafana/dashboards/per_person.yml`; existing surfaces are PRESERVED verbatim. Operators upgrading from Week 9 to Week 10-11 see identical behavior — the primitives are NOT auto-called at module load; operators invoke the per-Person primitives programmatically OR consume via the Grafana per-Person dashboard.
- **Recommended (optional):** operators wanting per-Person observability at Week 10-11:

  ```python
  from datetime import datetime, timedelta, timezone

  from observability import (
      collect_per_person_register_fidelity_snapshots,
      collect_per_person_claim_type_hallucination_snapshots,
      collect_per_person_layer_5_drift_snapshots,
  )

  now = datetime.now(timezone.utc)
  since = now - timedelta(days=30)

  fidelity = collect_per_person_register_fidelity_snapshots(
      led, since=since, now=now,
  )
  hallucinations = collect_per_person_claim_type_hallucination_snapshots(
      led, since=since, now=now,
  )
  layer_5_drifts = collect_per_person_layer_5_drift_snapshots(
      led, since=since, now=now,
  )

  for snap in fidelity:
      mean = (
          snap.total_fidelity_score / snap.event_count
          if snap.event_count else 0.0
      )
      print(
          f"{snap.person_id}/{snap.register}: "
          f"mean fidelity {mean:.3f} "
          f"(min {snap.min_fidelity_score:.3f} / "
          f"max {snap.max_fidelity_score:.3f}) "
          f"[{snap.ready_count} ready / {snap.refused_count} refused]"
      )
  ```

- **First primitive run post-upgrade MAY surface diagnostics** if the operator's ledger contains pre-Week-10-11 events with unknown `register` / `claim_type` / `reason` values (e.g., legacy events from prior framework versions OR operator-script-injected events). Operators inspect the surfaced diagnostics + coordinate the closed-set extension via the per-pillar foundation ADR pattern.
- **No ledger schema migration** — Week 10-11 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes** — Week 10-11 ships ZERO new event classes.
- **No new pip dependencies** — the three primitives are stdlib (`Counter`, `dataclasses`, `datetime`, `typing`); the Grafana YAML is operator-readable text.

## Existing-operator seed

Operator action required at Week 10-11: **NONE — content-additive.**

Recommended (optional): operators wanting per-Person observability at Week 10-11 invoke the canonical wiring per the Migration section above. Operators waiting for the framework-side binding exit-criterion test + Pillar G Stable flip see them land at Pillar G Week 12.

## References

- **ADR-0057** (Pillar G Week 9 — cost dashboard rendering + per-source `cost_incurred` aggregation primitive + `CostSnapshot` dataclass + `COST_SOURCES_CATALOG` closed-set + `cost_source_uncatalogued` diagnostic kind extension + `_SLO_NAMES` extension PUNT decision). D314-D318. Week 10-11 extends `_DIAGNOSTIC_KINDS` from 3 to 6; Week 9's extension from 2 to 3 IS the precedent.
- **ADR-0056** (Pillar G Week 7-8 — SLO violation detector + `slo_violation_detected` event class producer + Slack webhook dispatcher + R032 synthetic-event exclusion + at-most-ONE-per-(slo_name, channel)-per-call rate-limit + `_SLO_NAMES` closed-enum). D307-D313. The R032 exclusion + closed-set discipline patterns Week 10-11 inherits.
- **ADR-0055** (Pillar G Week 6 — Per-stage span instrumentation + send-latency Histogram dispatcher integration). D300-D306. Week 10-11 preserves the per-call-site span wiring verbatim.
- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization + canonical Tracer scope + per-stage `traced_stage` + `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED`). D294-D299. Week 10-11 preserves the tracing initialization + closed-sets verbatim.
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring + per-channel send-latency Histogram + reconcile success ratio ObservableGauge + Prometheus HTTP exposition server + framework-default Views + first Grafana-as-code dashboard). D288-D293. Week 10-11's per-Person Grafana dashboard YAML mirrors the Week 4 overview + Week 9 cost dashboard's structure + renders via the per-event-class `outreach_factory_events_total` ObservableCounter per D284.
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope + per-event-class ObservableCounter + cumulative-counter semantics + framework-neutrality contract). D282-D287. Week 10-11 consumes the per-event-class ObservableCounter via per-event-class filters in PromQL.
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281. Week 10-11's three new diagnostic kinds follow the at-most-ONE-per-kind-per-call rate-limit pattern + R034 mitigation from D279.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. **D277 explicitly named Week 10-11 as the per-Person observability surface adapters consuming Pillar F event classes + Layer 5 `reconcile_drift.reason` value.**
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip + retrospective + per-week-reviewer carry-forward checklist). D262-D271 + §66 P2-2 (the Pillar F Week 12 follow-up's NEW legacy-state-vs-new-defense-layer reason-precedence drift pattern). **The reason-precedence drift discipline IS the structural commitment Week 10-11's `PILLAR_F_LAYER_5_DRIFT_REASONS` closed-set encodes.**
- **ADR-0047** (Pillar F Week 10 — Layer 4 post-engine guard + `draft_ready` event class). D244-D251. Week 10-11's per-Person primitives consume `draft_ready` event per ADR-0050 D277.
- **ADR-0045** (Pillar F Week 8 — `draft_quality_scored` event class + emit-always posture). D229-D231. Week 10-11's per-(person_id, register) fidelity primitive consumes `draft_quality_scored.voice_fidelity_score`.
- **ADR-0043** (Pillar F Week 6 — `hallucination_detected` event class + emit-only-on-uncited posture + per-claim trace shape). D213-D219. Week 10-11's per-(person_id, claim_type) hallucination primitive consumes `hallucination_detected.uncited_claims[].claim_type`.
- **ADR-0042** (Pillar E Week 9-11 — discovery lineage primitive + idempotence key contract). D210 (closed-enum discipline). Week 10-11's three new closed-sets follow the same closed-enum pattern.
- **ADR-0039** (Pillar F Week 2 — `voice_exemplar_retrieved` event class + voice-corpus retrieval primitive). D189. Week 10-11's per-Person observability surface CONSUMES `voice_exemplar_retrieved` per ADR-0050 D277 (panel 4 in the Grafana per-Person dashboard).
- **ADR-0038** (Pillar F foundation). D178 (REGISTERS closed-enum); D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields). Week 10-11's `PILLAR_F_REGISTERS_MIRROR` mirrors D178's closed-set.
- **ADR-0034** (Pillar E Week 1 — discovery dedup primitive + deterministic-clock contract). D154-D158.
- **ADR-0032** (Pillar E foundation). D148 (privacy invariant — operator-confidential `source_list` field).
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state). Week 10-11's three primitives sort by `(person_id_or_empty, sub_axis)` for deterministic output.
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant). Week 10-11's three dataclasses' `channel` field surfaces the channel uniformly per this invariant.
- **ADR-0011** (Pass C heal-pass at `orchestrator/reconcile.py`). The Layer 5 backstop integrates at Pass C per ADR-0049 D262.
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers). Week 10-11's R032 mitigation consumes `_recovered_by` for synthetic-event exclusion; the three new diagnostic kinds carry `_emitted_by: "observability"`.
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2-9 sections + Week 10-11 §25 extension per this commit).
- `.planning/HANDOFF-pillar-g-week-9.md` — Pillar G Week 9 close summary + Pillar G Week 10-11 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 10-11 close summary.
- `docs/RISK-REGISTER.md` R031-R036 (no new R-rows at Week 10-11; R031 mitigation surface extends to per-Person observability via three new closed-sets + three mirrors; R032 mitigation extends to three per-Person primitives via `_recovered_by` exclusion).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 10-11 ADR-0058 references.
- `orchestrator/observability.py` — extended Week 10-11 with `PILLAR_F_PERSON_EVENT_CLASSES` + `PILLAR_F_LAYER_5_DRIFT_REASONS` + `PILLAR_F_REGISTERS_MIRROR` + `PILLAR_F_CLAIM_TYPES_MIRROR` + `PILLAR_F_ALL_DRIFT_REASONS_MIRROR` + `PersonRegisterFidelitySnapshot` + `PersonClaimTypeHallucinationSnapshot` + `PersonLayer5DriftSnapshot` + `collect_per_person_register_fidelity_snapshots` + `collect_per_person_claim_type_hallucination_snapshots` + `collect_per_person_layer_5_drift_snapshots` + `_DIAGNOSTIC_KINDS` extended from 3 to 6 values + module docstring extension.
- `tests/test_observability.py` (extended Week 10-11) — 86 NEW tests covering the cell-level matrix per the per-week-reviewer discipline NOW FOURTEEN consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6 + W7-W8 + W9 + W10-11).
- `tests/test_multi_channel_coherence.py::TestPillarGObservability::test_per_person_dashboard_consumes_pillar_f_event_classes` (un-skipped Week 10-11) — binding cross-pillar coherence test verifies the per-Person observability surface adapter contract.
- `infra/grafana/dashboards/per_person.yml` (NEW) — operator-readable Grafana per-Person dashboard YAML rendering five panels for the per-Person dashboard rows pinned at ADR-0050 D277.
