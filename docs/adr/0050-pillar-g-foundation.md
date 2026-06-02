# ADR-0050: Pillar G foundation — per-event-class observability primitive shape, observability framework decision, cross-pillar integration audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface consuming Pillar F event classes

- **Status:** Accepted
- **Date:** 2026-05-25
- **Pillar:** G (Observability — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0008 shipped Pillar A (declarative policy engine). ADRs 0009-0013 shipped Pillar B (migration framework + synthetic-replay exit-criterion vehicle). ADRs 0014-0024 shipped Pillar C (multi-channel coherence — four channels, six reconcile passes, five per-channel policy migrations). ADRs 0025-0031 shipped Pillar D (reply + conversation handling — rule + LLM classifier, auto-unsubscribe, conversation state machine, win/loss attribution, funnel CLI). ADRs 0032-0037 shipped Pillar E (discovery quality + lineage — dedup + email-verification cache + tier auto-assignment + discovery_lineage stamping + three-skills-one-day binding exit-criterion). ADRs 0038-0049 shipped Pillar F (voice corpus + draft quality — voice-corpus schema + canonical location, embedding-retrieval primitive, per-register adapters, threshold loader + CLI, FIVE-layer hallucination-detection defense across Layers 1-5, per-claim-type corpus + measurement, voice-fidelity scoring, fuzzy-match Layer 3 extension, Layer 4 post-engine guard, Layer 3 corpus revision with paraphrased-ready pairs + bound tightening, and Layer 5 reconcile heal-pass refusal closing the FIVE-layer defense + binding 200-draft eval set + Stable flip). **Pillar F is Stable as of 2026-05-25.** Pillars G / H / I / J are unblocked from the "F stable" dependency.

Pillar G — Observability (`docs/PILLAR-PLAN.md` §2 Pillar G, Weeks 31-42) — extends the substrate at the operator-visibility end of the funnel: every refusal (gate / cooldown / suppression / identity conflict / vault drift / hallucination-detection finding / Layer 5 backstop drift) emits a structured event with full diagnostic context (per I5), and the operator answers "where is my pipeline leaking?" / "why is dispatch slow today?" / "what did the gate refuse this week?" in ONE CLI invocation. The substrate is in place; what Pillar G Week 1 needs is the **convention-setting decisions** the next eleven weeks build on.

Pillar F's Week 12 retrospective (`.planning/RETRO-pillar-f.md` §"What to do differently in Pillar G") named EIGHT carry-forward recommendations: (1) land the Pillar G observability test in Week 1, NOT Week N (Pillar D + E + F Week 1 each shipped binding test stubs); (2) audit pre-existing surfaces for symmetric assumptions whenever extending a Pillar A/B/C/D/E/F primitive (every prior pillar's Week 1 audit caught ≥1 P2); (3) continue the per-week-handoff + per-week-review-with-follow-up-commit + per-ADR ≥3-rejected-alternatives + §Downstream-pillar-impact + holistic-exit-review discipline; (4) design Pillar G's per-dashboard load-bearing invariants at Week 1; (5) design the per-event-class-symmetry-with-shared-aggregation pattern at Week 1 (Pillar D's per-channel reply detection + Pillar E's per-skill integration + Pillar F's per-register adapters all shipped via shared-helper-with-thin-adapters convention); (6) apply the THREE Pillar F per-week-reviewer disciplines (cell-level matrix coverage + behavioral-passthrough-not-signature-only + cross-claim-type extraction cascade) to Pillar G's primitives; (7) the TEST-ONLY embed_fn + retrieve_fn seam preservation pattern generalizes; (8) the Week 12 legacy-state-vs-new-defense-layer tension generalizes — future pillars extending an existing pass's structural commitment audit legacy fixtures.

The six concerns this ADR resolves:

1. **Per-event-class observability primitive shape must be pinned before per-dashboard adapters ship.** The Pillar A/B/C/D/E/F substrate emits ~30 distinct event classes across the ledger (every two-phase intent/confirmed pair per channel; every reconcile drift/healed; every classifier verdict; every dedup hit / cache hit / tier suggested / discovery_lineage stamp; every voice-exemplar retrieval / hallucination-detected / draft-quality-scored / draft-ready emit; every cost_incurred + manual_override). Pillar G dashboards consume these uniformly + render per-pillar / per-channel / per-register / per-reason breakdowns. D272 pins the canonical primitive shape so the per-week-2+ adapters land against an established target. The `~/.outreach-factory/observability/` row in `docs/SOURCES-OF-TRUTH.md` is pre-declared as a Pillar G consumer-derived view (the ledger remains the SoT per I1; observability outputs are denormalized rebuildable views).

2. **Observability framework decision — OpenTelemetry SDK vs Prometheus-direct vs structured-logs-only.** Per PILLAR-PLAN §2 Pillar G: *"OpenTelemetry tracing through the whole pipeline ... Prometheus metrics export (or OTLP if we go full OTel)."* The PILLAR-PLAN allows two viable framework choices; the Week 1 commit pins the choice so per-week implementations don't reopen the question. D273 picks OpenTelemetry SDK (OTel SDK) as the canonical observability framework + Prometheus as a downstream sink via OTel's Prometheus exporter; Grafana-as-code dashboards consume from Prometheus. The rationale + 3+ rejected alternatives at D273.

3. **Cross-pillar surface audit — THE load-bearing anti-regression decision.** Per Pillar A/B/C/D/E/F Week 1 precedents (every prior pillar's Week 1 audit caught ≥1 pre-existing P2): Pillar A surfaced policy-engine version concerns; Pillar B surfaced `ledger/0002`'s channel-field gap; Pillar C surfaced Pass A's channel-filter gap; Pillar D surfaced Pass B's channel-on-every-event gap; Pillar E surfaced `needs_identity_upgrade`'s source-attribution gap; Pillar F surfaced the all-cited-claims-path vacuity gap in `tests/test_multi_channel_coherence.py::TestHallucinationDetection`. Pillar G Week 1's per-week reviewer MUST audit existing Pillar A/B/C/D/E/F surfaces for symmetric assumptions when Pillar G's commit silently expands the operator-visible surface space. D274 pins the audit + names the new event classes Pillar G adds (`observability_snapshot_emitted` / `slo_violation_detected`) + names the per-pillar event-class enumeration the audit consumes; `.planning/REVIEW-pillar-g-surface-audit.md` is the load-bearing artifact future Pillar G weeks extend.

4. **The Pillar G exit-criterion verification vehicle must exist in Week 1.** Per PILLAR-PLAN §2 Pillar G binding text: *"Yang can answer any 'why is dispatch slow today?' / 'where am I losing prospects?' / 'what did the gate refuse this week?' in one CLI invocation."* Without the vehicle landing in Week 1, the cross-cutting properties (per-event-class snapshot completeness; per-pillar event-class observability coverage; per-question CLI-invocation answerability; privacy-respecting aggregation) would only surface end-of-pillar, repeating Pillar B Week 5 + Pillar C Week 12 + Pillar D Week 12 + Pillar E Week 12 + Pillar F Week 12's pattern. D275 names the vehicle scope: `tests/test_multi_channel_coherence.py` is EXTENDED with `TestPillarGObservability` + `TestPillarGSLOAlerting` + `TestPillarGExitCriterion` test classes (Option A per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 single-file rationale inherited). The file currently sits at ~8000 LOC — crossing the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266 — but the Pillar G Week 1 commit does NOT split (the per-pillar test classes' Week 1 stubs belong adjacent to the per-pillar primitive contracts they verify; the split argument resurfaces if Pillar G's Week 2+ commits add another ~1000 LOC, becoming a Pillar G Week N reviewer's call).

5. **One-CLI-invocation invariant + per-dashboard load-bearing invariants.** Per RETRO-pillar-f.md item 4 (continuing Pillar D Week 1's CAN-SPAM precedent per ADR-0025 D97 + Pillar E Week 1's privacy precedent per ADR-0032 D148 + Pillar F Week 1's hallucination-detection FIVE-layer precedent per ADR-0038 D180) — Pillar G ships its load-bearing invariants at Week 1. D276 names: (a) **operator answers the three load-bearing questions in ONE CLI invocation per the binding-text discipline** (the exit-criterion text is not "in one dashboard" or "via one log search" — it's ONE CLI invocation); (b) **observability respects the privacy invariant per I8 + ADR-0032 D148** (the `source_list` field stays operator-private — Pillar G dashboards aggregate by `source_skill` but NEVER by `source_list`; per-Person draft body content stays out of observability aggregations per ADR-0038 D182 category 8); (c) **the channel-on-every-event invariant per ADR-0014 D33 is the per-event-class consumer surface** — Pillar G's per-event-class aggregator MUST consume `channel` uniformly across every event class that carries it (the four two-phase channels + the reply-classification channels + the dedup/cache/tier/lineage non-channel events + the Pillar F per-draft channels); (d) **no per-tenant fan-out at Pillar G** — multi-tenant aggregation lives at Pillar I per the per-tenant audit-tooling trajectory (ADR-0049 §Downstream pillar impact); Pillar G's primitive is single-tenant.

6. **Per-Person observability surface consuming Pillar F's four event classes + the Layer 5 reconcile_drift reason.** Pillar F's Week 12 close (ADR-0049 D262-D271) named Pillar G's per-Person dashboard as the consumer of: (a) `voice_exemplar_retrieved` (Week 2 per ADR-0039 + ADR-0038 D182) — per-draft retrieval signal; (b) `hallucination_detected` (Week 6+ per ADR-0043 D219) — per-draft un-cited-claim trace; (c) `draft_quality_scored` (Week 8 per ADR-0045 D231) — per-draft fidelity + hallucination verdict; (d) `draft_ready` (Week 10 per ADR-0047 D246) — per-draft Layer 4 emit-guard verdict; (e) the NEW `reconcile_drift.reason: "ready_without_draft_ready_event"` value (Week 12 per ADR-0049 D262) — per-Person Layer 5 backstop drift surface. D277 pins the Pillar G per-Person observability surface's consumption pattern of these five surfaces + names the per-pillar event-class observability symmetry — Pillar A/B/C/D/E's event classes are consumed via the same primitive shape; the Pillar F consumption is NOT a special case.

Risks this ADR mitigates by design: **R005 (Gmail API quota exhaustion)** continues mitigated by per-channel rate-limit policies + Pillar G's per-channel quota dashboard surfaces the bound. **R016 (LLM cost runaway)** continues mitigated by Pillar A's budget rules + Pillar G's cost dashboard makes the bound operator-visible. **R023 (hallucination-detection false-negative)** — FINAL mitigation closed at Pillar F Week 12 — Pillar G dashboards SURFACE the binding 200-draft eval's `<1%` bound for ongoing operator-visible regression detection (per-Pass-C `reason: ready_without_draft_ready_event` drift-rate dashboard). **R030 (Layer 4 emit-guard bypass)** — FINAL mitigation closed at Pillar F Week 12 — Pillar G dashboards SURFACE the Layer 5 drift count for operator-visible audit.

Three new risks surface in this ADR's authoring + named in `docs/RISK-REGISTER.md`:

- **R031 (Per-event-class observability primitive over-broadens the consumer surface)** — Pillar G's per-event-class aggregator walks every event class in the ledger; a future contributor adding a NEW event class without coordinating with the aggregator's expected-event-class enumeration would either silently fail to surface the new class (operator-visibility gap) OR force the aggregator to crash on unknown class names (refuse-loud regression). Mitigation by design: D272's primitive contract pins **permissive-aggregate-with-explicit-enumeration** — the aggregator consumes a closed-set list of expected event classes (sourced from each pillar's foundation ADR's "new event classes" table) + emits a NEW `observability_class_uncatalogued` event when it encounters an unknown class (operator-visible signal that a contributor shipped a class without updating the enumeration). The discipline is enforced by Pillar G's per-week-reviewer's checklist row + a regression-barrier test at the cross-pillar coherence vehicle.

- **R032 (SLO violation alerting false-positive — synthetic-data spike fires an alert)** — Pillar G's SLO violation alerting per PILLAR-PLAN §2 Pillar G fires on p99 send latency > 5s, reconcile success < 99%, bounce > 5%, any `manual_override` event. A synthetic data spike (e.g., a one-time backfill from the migration framework per ADR-0010 D17 emitting a flood of `enrolled` events with `_recovered_by: "backfill"`) MAY trip the bounce-rate or reconcile-rate alert without operator intent. Mitigation by design: D276(d) names the alerting's per-event-class filter — `_recovered_by` events (backfill / reconcile / migration_<id>) are EXCLUDED from SLO alerting by-design (the per-Pillar-B migration framework's synthetic events are not operator-actionable signals); the per-alert window's denominator excludes these.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — operators running the framework on multiple machines / daemons (e.g., Pillar H's daemon + a manual `python orchestrator/funnel.py` invocation + a Pillar G dashboard auto-refresh) all consume the same ledger but may compute aggregations at different windows; the per-process cache may diverge. Mitigation by design: D272 names the primitive contract — **stateless aggregation, no in-process cache** — every call re-walks the ledger (the per-call cost is O(N) per ADR-0034 D156's analysis at sub-second for v1 scale; Pillar H may revisit if multi-machine scale surfaces). Pillar G's primitive is single-process by design; the dashboard's rendering layer (Grafana-as-code) consumes the primitive's output via the existing Prometheus pull contract — Prometheus handles cross-process aggregation downstream.

## Decision

### D272. Per-event-class observability primitive shape — `orchestrator/observability.py::collect_event_class_snapshots`

Pillar G ships `orchestrator/observability.py` (NEW module Week 2+ ships; Week 1 stub commits the module + the contract + the closed-set enumeration). The Week 1 commit ships the **module shape** + **the closed-set enumeration of Pillar A-F event classes** + **the `MetricSnapshot` dataclass** + **the `collect_event_class_snapshots` primitive signature** + **the `EVENT_CLASS_CATALOG` closed-set enumeration**. The Week 2+ commit ships the implementation body.

The contract:

```python
# Pillar G Week 1 ships the contract; Week 2+ ships the body.
from orchestrator.observability import (
    MetricSnapshot,
    EVENT_CLASS_CATALOG,
    collect_event_class_snapshots,
)

snapshots: list[MetricSnapshot] = collect_event_class_snapshots(
    led=led,
    since=parse_since("30d", now=now),
    now=now,                                  # deterministic-clock kwarg
    expected_classes=EVENT_CLASS_CATALOG,     # closed-set enumeration
)
# Each MetricSnapshot carries: event_class, channel | None, total_count,
# per_breakdown_counts (sorted dict), oldest_ts, newest_ts.
```

**`MetricSnapshot` dataclass shape:**

```python
@dataclass(frozen=True)
class MetricSnapshot:
    event_class: str                                # e.g., "reply_classified"
    channel: str | None                             # per ADR-0014 D33; None for non-channel events
    total_count: int                                # count in the window
    per_breakdown_counts: dict[str, int]            # sorted dict per event-class-specific dimensions
    oldest_ts: str | None                           # ISO 8601 UTC of earliest in window
    newest_ts: str | None                           # ISO 8601 UTC of latest in window
```

**`EVENT_CLASS_CATALOG` closed-set enumeration.** A module-level `frozenset[str]` listing every Pillar A-F event class the primitive expects to encounter:

```python
EVENT_CLASS_CATALOG: frozenset[str] = frozenset({
    # Phase 5.5 + Pillar A — policy engine
    "enrolled", "enrollment_skipped_exists", "enrollment_conflict",
    "needs_identity_upgrade", "identity_upgraded",
    "state_transition", "research_complete", "research_failed",
    "draft_complete", "draft_failed", "draft_rejected",
    "review_approved", "review_rejected",
    "policy_blocked", "cooldown_blocked", "dedup_blocked",
    "manual_override", "cost_incurred",
    # Pillar B — migration framework
    "migration_event",
    # Pillar C — multi-channel coherence (per ADR-0014 D33 channels)
    "send_intent", "send_confirmed", "send_failed", "send_aborted",
    "send_confirmed_orphan", "send_run_complete",
    "li_invite_intent", "li_invite_confirmed", "li_invite_failed",
    "li_invite_aborted",
    "li_dm_intent", "li_dm_confirmed", "li_dm_failed", "li_dm_aborted",
    "tw_dm_intent", "tw_dm_confirmed", "tw_dm_failed", "tw_dm_aborted",
    "calendar_booking_intent", "calendar_booking_confirmed",
    "calendar_booking_failed",
    "bounce_detected", "reply_received",
    "reconcile_drift", "reconcile_healed",
    # Pillar D — reply + conversation handling
    "reply_classified", "suppression_added", "conversation_state_changed",
    "conversation_outcome", "calendar_booking_cancelled",
    # Pillar E — discovery quality + lineage
    "discovery_dedup_hit", "discovery_dedup_conflict",
    "email_verification_cache_hit", "tier_suggested",
    # Pillar F — voice corpus + draft quality
    "voice_exemplar_retrieved", "hallucination_detected",
    "draft_quality_scored", "draft_ready",
})
```

**Why a closed-set enumeration (rejected: open-set walk + emit-all-classes-encountered; rejected: per-pillar sub-frozensets; rejected: per-call enumeration via caller-passed kwarg).** Three reasonable shapes: (a) closed-set frozenset at module level (D272's choice — every pillar's foundation ADR registers its new classes); (b) open-set walk (the primitive collects every event type encountered + emits a snapshot per class); (c) per-pillar sub-frozensets `_PILLAR_A_EVENT_CLASSES` + `_PILLAR_B_EVENT_CLASSES` etc. composed at module level. Pillar G Week 1 picks (a). The rationale:

* **The closed-set enumeration IS the regression-barrier per R031.** A future contributor adding a NEW event class without updating `EVENT_CLASS_CATALOG` triggers the `observability_class_uncatalogued` event (operator-visible signal) — the contributor's PR can't silently introduce a class that observability misses.
* **Open-set walk (option b) loses the structural commitment.** Pillar G's role is operator-visible regression-prevention; if observability quietly absorbs any new event class, the SLO alerting + the dashboards drift silently from the per-pillar binding events. The closed-set enforces the per-pillar foundation ADR's discipline — every new event class MUST coordinate with the catalog.
* **Per-pillar sub-frozensets (option c) creates the "look in seven places" mental model.** The catalog's load-bearing role is a SINGLE reference point for operators + dashboards + future pillar authors; splitting across per-pillar frozensets re-introduces the discoverability problem the single-file coherence vehicle solves.

**`collect_event_class_snapshots` primitive contract:**

* **Stateless + per-call ledger walk.** Per R033 mitigation, the primitive does NOT cache state in-process; every call re-walks the ledger via `led.all_events()` + filters by `ts >= since` + groups by event class. The per-call cost is O(N) at v1 scale (~5K events) → sub-second; Pillar H may revisit at scale.
* **Deterministic-clock contract per ADR-0034 D156 + ADR-0035 D162 + ADR-0038 D179 + ADR-0049 D265.** The primitive accepts an optional `now: datetime | None = None` kwarg; production callers omit (wall-clock used); tests pass `now` for byte-identical reproducibility.
* **Privacy-respecting per I8 + ADR-0032 D148 + ADR-0038 D182 category 8.** The snapshot's `per_breakdown_counts` field MAY NOT include `source_list` (operator-private per ADR-0032 D148), `draft_body` (per ADR-0038 D182), `dossier_body` (per ADR-0038 D182), `exemplar_body` (per ADR-0038 D182), `claim_text` (per ADR-0038 D182 — the un-cited-claim TRACE is privacy-relevant; only per-claim-type COUNTS surface). Allowed breakdown dimensions: `channel` / `register` / `source_skill` / `category` / `classification_method` / `outcome` / `reason` / `result_state` / `event_class`. The `_breakdown_dims_allowed` frozenset constrains the primitive's per-call kwarg.
* **Permissive-aggregate-with-explicit-enumeration per R031 mitigation.** Events whose type is in `EVENT_CLASS_CATALOG` aggregate into per-class snapshots; events whose type is NOT in the catalog trigger ONE emission of `observability_class_uncatalogued` (rate-limited per the primitive's per-call emit budget — at most ONE such emission per call regardless of count, to prevent ledger flooding) carrying the unknown class name + count. Operators see this as a refuse-loud signal that the catalog drifted from the actual ledger surface.

**Pin:** `tests/test_multi_channel_coherence.py::TestPillarGObservability::test_collect_event_class_snapshots_walks_every_pillar_a_through_f_event_class` asserts the per-pillar coverage contract. **Stub lands in this Week 1 commit + un-skips when the primitive ships in Week 2.**

### D273. Observability framework decision — OpenTelemetry SDK + Prometheus exporter + Grafana-as-code

Pillar G adopts **OpenTelemetry SDK (OTel SDK) as the canonical observability framework** + **Prometheus as the downstream metrics sink via OTel's Prometheus exporter** + **Grafana-as-code dashboards in `infra/grafana/`** (NEW directory; Pillar G Week 4+ ships). The choice resolves PILLAR-PLAN §2 Pillar G's "or OTLP if we go full OTel" alternative in favor of OTel.

**Why OTel SDK + Prometheus exporter (rejected: Prometheus-direct via `prometheus_client`; rejected: structured-logs-only via `structlog`; rejected: defer the framework choice to Pillar H).** Four reasonable framework shapes: (a) OTel SDK + Prometheus exporter (D273's choice); (b) Prometheus-direct via `prometheus_client` (Python's bare-bones Prometheus client); (c) structured-logs-only via `structlog` + post-hoc log aggregation; (d) defer the choice. Pillar G Week 1 picks (a). The rationale:

* **OTel SDK is the cross-vendor standard.** Multi-cloud / multi-vendor portability is a Pillar I OSS-hardening concern; OTel's vendor-neutral instrumentation surface means operators with different observability backends (Honeycomb / Datadog / Grafana Cloud / self-hosted Prometheus) point their OTLP collector at the same OTel-instrumented codebase without code changes.
* **Tracing IS a load-bearing Pillar G deliverable.** PILLAR-PLAN §2 Pillar G NAMES "OpenTelemetry tracing through the whole pipeline (discovery → enrichment → research → draft → review → send → reply → win/loss)." Prometheus-direct (option b) covers metrics but NOT traces; structured-logs-only (option c) covers events but reconstructs traces post-hoc at high cost. OTel covers both metrics + traces uniformly.
* **OTel's Prometheus exporter is the bridge to Grafana.** Grafana-as-code dashboards consume Prometheus query language (PromQL); OTel's exporter publishes metrics in Prometheus's exposition format at an HTTP endpoint. The bridge preserves the Prometheus + Grafana ecosystem operators are familiar with.
* **structured-logs-only (option c) loses real-time aggregation.** Post-hoc log aggregation (e.g., Loki + LogQL) is operator-readable for one-off queries but doesn't surface SLO violations in real time. Pillar G's alerting requires real-time metric evaluation; structured-logs alone don't deliver this.
* **Deferring (option d) breaks the Week 1 foundation precedent.** Pillar A through F each pinned its framework choice at Week 1; deferring Pillar G's choice creates a structural gap (per-week implementations can't proceed without the framework substrate).

**Adoption trajectory (per Pillar G's per-week ticker; revisable per the Pillar B compression pattern):**

| Pillar G Week | Deliverable |
|---|---|
| **1 (this commit)** | Foundation ADR + cross-pillar surface audit + test class stubs + handoff doc + `EVENT_CLASS_CATALOG` + `MetricSnapshot` shape + `collect_event_class_snapshots` signature (no body) + OTel framework decision pinned. ZERO new event classes implemented at Week 1 (the two NEW classes named below are deferred to Week 2+); ZERO new migrations. |
| **2** | `orchestrator/observability.py::collect_event_class_snapshots` body — stateless per-call ledger walk; closed-set aggregation; deterministic-clock kwarg; permissive-aggregate per R031. `observability_class_uncatalogued` event class ships. Per-pillar regression-barrier test rows un-skipped. |
| **3** | OTel SDK initialization at `orchestrator/observability/_otel_init.py` (deferred sub-module if surface grows; co-locate at `observability.py` if minimal); per-event-class metric emit at the existing ledger append point (the structural commitment — observability is a SEPARATE concern from ledger append; emit is consumer-side, not producer-side). |
| **4** | OTel Prometheus exporter wiring + the bare metric set (per-event-class counter + per-channel histogram + reconcile success ratio). Grafana-as-code first dashboard at `infra/grafana/dashboards/overview.yml`. |
| **5-6** | OTel tracing instrumentation through the discovery → enrichment → research → draft → review → send → reply → win/loss pipeline (per PILLAR-PLAN §2 Pillar G). Per-stage span surface. |
| **7-8** | SLO violation detector at `orchestrator/observability/_slo_alerts.py` (or co-located) — `slo_violation_detected` event class emit + Slack webhook wiring (operator-configurable; off by default). |
| **9** | Cost dashboard rendering — per-source `cost_incurred` aggregation; per-tenant attribution deferred to Pillar I per RETRO-pillar-f.md item 8. |
| **10-11** | Per-Person observability surface — per-Pillar-F event-class dashboards (per-register fidelity distribution; per-claim-type hallucination counts; per-Person Layer 5 drift rate). |
| **12** | Binding exit-criterion test un-skip + Pillar G Stable flip + Pillar G retrospective + handoff to Pillar H. |

**TWO new event classes Pillar G adds** (named here so the audit lands against concrete event-type names; Pillar G's downstream PR cycles add NO new event classes beyond these two):

| Event class | Pillar G week that emits | Purpose |
|---|---|---|
| `observability_class_uncatalogued` | Week 2 | Per-call refuse-loud signal when `collect_event_class_snapshots` encounters an event type NOT in `EVENT_CLASS_CATALOG`. Carries the unknown class name + count. Rate-limited to ONE emission per call. R031 mitigation. |
| `slo_violation_detected` | Week 7-8 | Per-window SLO violation signal — fires when p99 send latency > 5s OR reconcile success < 99% OR bounce > 5% OR `manual_override` count > 0 in the window. Carries the SLO name + observed value + threshold. Channel: derived from the violating metric's channel (if applicable). Operator-actionable. |

**Closed-enum for the new event classes** + **channel-on-every-event invariant per ADR-0014 D33**: both new classes carry `channel: <channel>` when the violating signal is per-channel (`send_latency` is per-channel; `bounce_rate` is per-channel; `manual_override` is per-channel via the underlying rule's channel scope; `reconcile_success` is NOT per-channel — uses `channel: null` per the existing `send_confirmed_orphan` precedent at `ledger.py:104`).

**Pin:** `tests/test_multi_channel_coherence.py::TestPillarGObservability::test_observability_framework_is_opentelemetry_sdk` asserts the framework choice via a static check on `orchestrator/observability.py`'s import contract. **Stub lands in this Week 1 commit + un-skips when the OTel SDK initialization ships in Week 3.**

### D274. Cross-pillar integration audit — load-bearing surface map

`.planning/REVIEW-pillar-g-surface-audit.md` (this commit) is the surface map. The audit walks every existing Pillar A / B / C / D / E / F surface that touches the ledger event stream / operator-facing CLI / dashboard substrate; verifies each is either closed-set protected or literal-string filtered against Pillar G's two new event classes + the new observability primitive's per-event-class aggregation surface + the new Grafana-as-code dashboard substrate. The audit's verdict: **see `.planning/REVIEW-pillar-g-surface-audit.md` for the per-surface walk + the verdict for Week 1**.

**The audit IS the contract.** Future Pillar G weeks' per-week reviewers consult the audit as the surface map; new code added in Week N+ that touches a ledger index or a query method extends the audit with a new row. The discipline mirrors Pillar A/B/C/D/E/F's per-week-review pattern + carries forward the RETRO-pillar-f.md item-2 "Audit pre-existing surfaces for symmetric assumptions" recommendation.

**Categories the audit pins for future Pillar G week reviewers** (mirrors ADR-0038 D182's category 1-8 structure; extends with Pillar G-specific category 9-12):

1. Does the week's commit broaden `EVENT_CLASS_CATALOG` (adds a new event class)? IF YES, the new class MUST also be documented at the pillar's foundation ADR's "new event classes" table + the audit row extension.
2. Does the week's commit add a NEW operator-facing CLI surface (a new flag, a new sub-command)? IF YES, verify the closed-enum protection per ADR-0042 D210 + the deterministic-output contract per ADR-0031 D140.
3. Does the week's commit extend the Grafana-as-code dashboard set? IF YES, verify the per-dashboard load-bearing invariants per D276.
4. Does the week's commit modify the OTel SDK initialization or the Prometheus exporter wiring? IF YES, verify the framework-neutrality contract per D273 (operators with different OTLP backends still consume the same instrumentation).
5. Does the week's commit add a NEW SLO threshold? IF YES, verify the per-SLO refuse-loud contract per D276(d) + the `slo_violation_detected` emit-shape consistency.
6. Does the week's commit add a NEW breakdown dimension to `collect_event_class_snapshots`? IF YES, verify the dimension is in `_breakdown_dims_allowed` + the privacy invariant per I8 (NOT `source_list`, NOT `draft_body`, NOT `dossier_body`, NOT `exemplar_body`, NOT `claim_text`).
7. Does the week's commit aggregate across multiple Pillar A/B/C/D/E/F event classes (e.g., "all _confirmed events")? IF YES, verify the aggregation respects the channel-on-every-event invariant per ADR-0014 D33 + does NOT silently collapse per-channel counts when operators expect them broken out.
8. Does the week's commit surface a `hallucination_detected` / `voice_fidelity_score` / `draft_ready` / `reconcile_drift.reason` in operator-facing dashboard? IF YES, verify the privacy invariant per I8 + ADR-0038 D182 category 8 + the per-Person observability surface contract per D277.
9. **(Pillar G-specific)** Does the week's commit add a NEW Slack webhook surface OR change the per-alert payload shape? IF YES, verify the operator-configurable opt-in (default OFF per the OSS bring-up trajectory) + the per-alert deduplication discipline (one alert per SLO violation per window; no per-event flood).
10. **(Pillar G-specific)** Does the week's commit add per-tenant aggregation surface? IF YES, deferred to Pillar I per RETRO-pillar-f.md item 8 + ADR-0049 §Downstream pillar impact — Pillar G is single-tenant by D276(d).
11. **(Pillar G-specific)** Does the week's commit extend the funnel.py CLI's existing breakdown dimensions or output JSON shape? IF YES, verify backwards-compatibility with the Pillar D Week 12 byte-identical contract per ADR-0031 D140 (the funnel CLI's existing output shape is operator-readable; Pillar G EXTENDS the existing breakdown set but DOES NOT change the existing output shape).
12. **(Pillar G-specific)** Does the week's commit modify the legacy-state-vs-new-defense-layer reason-precedence per the Pillar F Week 12 follow-up NEW pattern (`_LAYER_5_DRIFT_REASON` vs `vault_ahead_of_ledger` precedence per ADR-0049 D263)? IF YES, the consumer-surface migration MUST be documented + the precedence MUST be pinned by a regression-barrier test (per the Pillar F Week 12 follow-up's discipline).

### D275. Pillar G exit-criterion vehicle scope

`tests/test_multi_channel_coherence.py` is the Pillar G exit-criterion verification vehicle (extended from Pillar C/D/E/F's vehicles per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183). The file gains THREE new test classes in this Week 1 commit:

* **`TestPillarGObservability`** — observability primitive coherence + per-event-class aggregation contract (per D272 + D277; per-pillar coverage pins; closed-set enumeration pins; `MetricSnapshot` shape pins; privacy-respecting breakdown pins). All test rows skip in Week 1 with `Pillar G Week N delivers` messages.

* **`TestPillarGSLOAlerting`** — SLO violation alerting contract (per D273 + D276; the per-SLO refuse-loud pins; the `slo_violation_detected` emit-shape pins; the synthetic-event exclusion pins per R032; the operator-configurable opt-in pins). All test rows skip in Week 1 with `Pillar G Week N delivers` messages.

* **`TestPillarGExitCriterion`** — the binding exit-criterion test. One method: `test_operator_answers_three_questions_in_one_cli_invocation` per PILLAR-PLAN §2 Pillar G's binding text. The three binding questions: (i) "why is dispatch slow today?" — answered by per-channel send-latency p99 + per-Pass-A intent-recovery-rate over the window; (ii) "where am I losing prospects?" — answered by per-stage funnel (enrolled → researched → drafted → ready → sent → replied → outcome) with per-stage drop count; (iii) "what did the gate refuse this week?" — answered by per-`reason` reconcile_drift count + per-`category` reply_classified count + per-Layer hallucination_detected count + per-Layer-4 build_draft_ready_payload refusal count + per-policy-rule policy_blocked count. Skipped in Week 1; un-skips at the final Pillar G week (Week 12 of the Pillar G body — Week 42 of the program).

**The Option-A choice (extend the existing file) over Option B (new file).** Pillar C's exit-criterion vehicle (ADR-0014 D37) explicitly chose the single-file shape; Pillar D inherited per ADR-0025 D101; Pillar E inherited per ADR-0032 D147; Pillar F inherited per ADR-0038 D183; Pillar G inherits the same rationale:

* The vehicle's load-bearing property is cross-pillar coherence visible from Week 1 in ONE place per-week reviewers consult.
* Splitting Pillar G into a separate `tests/test_pillar_g_observability.py` would create the "look in two places" mental model ADR-0014 D37 §Decision rejected.
* File growth (the test file is ~8000 LOC post-Pillar-F-Week-12) crosses the ~7500 LOC split-threshold flagged by ADR-0037 D172 + ADR-0049 D266. Pillar G Week 1's extension adds ~250-400 lines of stubs. The split argument is now LIVE — Pillar G Week N's per-week reviewer's call. **Pillar G Week 1 does NOT split** (the per-pillar Week 1 stub belongs adjacent to the per-pillar primitive contracts they verify); future Pillar G weeks MAY split when un-skipping rows pushes a clean split-point.

### D276. One-CLI-invocation invariant + per-dashboard load-bearing invariants

Per RETRO-pillar-f.md item 4 (continuing Pillar D Week 1's CAN-SPAM precedent per ADR-0025 D97 + Pillar E Week 1's privacy precedent per ADR-0032 D148 + Pillar F Week 1's hallucination-detection precedent per ADR-0038 D180) — Pillar G ships FOUR load-bearing invariants designed at Week 1:

**(a) The operator answers the three load-bearing questions in ONE CLI invocation per the binding-text discipline.** The exit-criterion text is not "in one dashboard" or "via one log search" — it's ONE CLI invocation. Pillar G Week 1 names the convention:

* The canonical CLI is `python orchestrator/funnel.py` (already exists per ADR-0031 D140 from Pillar D Week 12; Pillar G EXTENDS this CLI's breakdown dimensions + emits a NEW report section per the three binding questions).
* The CLI's output is byte-identical across consecutive invocations against a fixed ledger state per ADR-0031 D140 (the determinism contract Pillar D Week 12 pinned; Pillar G inherits).
* The three binding questions answered in ONE invocation: a single `python orchestrator/funnel.py --since 7d` (or whatever window) emits a JSON report carrying ALL THREE answer payloads per the binding-test contract.

**(b) Observability respects the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8.** Pillar G Week 1 names the invariant:

* The `source_list` field (per Pillar E ADR-0032 D148) STAYS operator-private — Pillar G dashboards aggregate by `source_skill` but NEVER by `source_list`.
* Per-Person draft body content (per Pillar F ADR-0038 D182) stays out of observability aggregations — the `draft_quality_scored` event's `voice_fidelity_score` + `hallucination_verdict` aggregate; the per-claim trace + the per-exemplar body do NOT.
* Per-Person dossier content stays out of observability aggregations — Pillar G's per-Person dashboards may surface `voice_exemplar_retrieved` COUNTS per draft but NOT the exemplar bodies.
* The `_breakdown_dims_allowed` frozenset constrains the primitive's per-call kwarg to the allowed dimensions; operators passing a privacy-violating dimension see a refuse-loud error.

**(c) The channel-on-every-event invariant per ADR-0014 D33 is the per-event-class consumer surface.** Pillar G's per-event-class aggregator MUST consume `channel` uniformly across every event class that carries it. The Pillar A/B/C/D/E/F event classes that carry `channel`: every two-phase intent/confirmed pair per channel + reply events + reconcile events; the classes that do NOT carry `channel`: discovery/enrollment events + cost_incurred events + Pillar E primitive events + Pillar F draft-quality events (the per-DRAFT channel is per-event optional — depends on the channel the draft targets). The primitive's `channel: str | None` field on `MetricSnapshot` distinguishes these uniformly.

**(d) No per-tenant fan-out at Pillar G.** Multi-tenant aggregation lives at Pillar I per the per-tenant audit-tooling trajectory (ADR-0049 §Downstream pillar impact). Pillar G's primitive is single-tenant by design. The per-tenant fan-out adds:

* Per-tenant `~/.outreach-factory-<tenant>/ledger/` substrate (Pillar I OSS bring-up convention; not Pillar G's scope).
* Per-tenant Prometheus namespace + Grafana folder isolation (Pillar I per-tenant audit-tooling).
* Per-tenant SLO threshold overrides (Pillar I's per-tenant config substrate).

Pillar G Week 1 explicitly names this boundary so future Pillar I authors don't re-open it at Pillar G's per-week reviews.

**Operator-stamping discipline per ADR-0006 D5 + ADR-0025 D97 + ADR-0035 D162 + ADR-0043 D217 + ADR-0049 D263:**

* The SLO violation alerting per D273 + D276 is **opt-in operator-deliberate** (default OFF). Operators wiring the Slack webhook stamp the `slo_alert_webhook_url` config in `~/.outreach-factory/config.yml`'s `observability:` block (NEW config block Week 7-8 ships); absence = SLOs are observed via dashboard rendering only, no alerting fires.

**Pin:** `tests/test_multi_channel_coherence.py::TestPillarGSLOAlerting::test_slo_alerting_default_is_off` asserts the operator-deliberate opt-in. **Stub lands in this Week 1 commit + un-skips when SLO alerting ships in Week 7-8.**

### D277. Per-Person observability surface — consuming Pillar F's four event classes + the Layer 5 reconcile_drift reason

Per ADR-0049 §Downstream pillar impact + ADR-0038 §Downstream pillar impact + ADR-0047 §Downstream pillar impact + ADR-0045 §Downstream pillar impact + ADR-0043 §Downstream pillar impact + ADR-0039 §Downstream pillar impact — Pillar G's per-Person observability dashboards CONSUME the four Pillar F event classes + the Layer 5 reconcile_drift reason. Pillar G Week 1 pins the consumption pattern:

**Per-Person dashboard rows (Pillar G Week 10-11 ships rendering):**

| Pillar G dashboard surface | Consumes | Filter / aggregation |
|---|---|---|
| Per-register fidelity-score distribution | `draft_quality_scored.voice_fidelity_score` | per-register (cold-pitch / congrats / re-engagement / reply / public-comment per ADR-0038 D181) |
| Per-claim-type hallucination count | `hallucination_detected.uncited_claims` | per-claim-type (date_reference / named_entity / you_phrase / quoted_text / dated_event per ADR-0043 D214) — COUNTS only, not trace per I8 |
| Per-Layer hallucination-detection refusal count | Cross-event aggregate (Layer 1 = test-only; Layers 2-5 from `hallucination_detected` + `draft_quality_scored` + Layer4GuardRefusal-via-`draft_ready` absence + `reconcile_drift.reason == "ready_without_draft_ready_event"`) | per-Layer breakdown |
| Per-Person Layer 5 drift rate | `reconcile_drift.reason == "ready_without_draft_ready_event"` | per-Person aggregation; surfaces Layer 4 emit-guard bypass operationally |
| Per-operator override-rate | `draft_ready.hallucination_check == "passed_via_override"` OR `draft_ready.voice_fidelity_check == "passed_via_override"` | per-operator deliberate-override signal for Pillar I per-tenant audit-tooling |
| Per-register threshold-effectiveness | `draft_quality_scored.voice_fidelity_score` vs `voice_thresholds.yml` per-register thresholds | per-register threshold-mis-calibration signal per R028 |

**Channel-on-every-event consumption per ADR-0014 D33:** The per-DRAFT Pillar F event classes carry `channel: <draft channel>` where channel is one of `{email, linkedin-dm, linkedin-comment, twitter-dm}` per ADR-0038 D178. The per-Person Pillar G dashboard rows respect this — e.g., the per-register fidelity distribution may further break down by channel for cross-channel-coherence operator audit.

**Privacy-respecting consumption per I8:** Pillar G's per-Person dashboards aggregate COUNTS + scores; they do NOT surface per-claim trace text, per-exemplar body content, dossier content, or draft body content. The `_breakdown_dims_allowed` frozenset constrains the primitive's per-call kwarg per D272.

**Per-event-class symmetry per RETRO-pillar-f.md item 5 (continuing Pillar D's per-channel reply detection + Pillar E's per-skill integration + Pillar F's per-register adapters):** Pillar G's per-Person observability surfaces follow the **shared-aggregation-primitive-with-thin-adapters** pattern. The shared primitive is `collect_event_class_snapshots` (per D272); the thin per-dashboard adapters consume the snapshot list + filter / group / render per the dashboard's specific aggregation grain. Per-dashboard adapters land at Pillar G Week 10-11 per the trajectory in D273's adoption table.

**Pin:** `tests/test_multi_channel_coherence.py::TestPillarGObservability::test_per_person_dashboard_consumes_pillar_f_event_classes` asserts the per-Pillar-F event-class consumption + the per-event-class symmetry. **Stub lands in this Week 1 commit + un-skips when the per-Person dashboard adapters ship in Week 10-11.**

## Alternatives considered

### D272-Alt1: Open-set walk + emit-all-classes-encountered

The primitive collects every event type encountered + emits a snapshot per class regardless of the catalog. **Rejected** because:

* Loses the structural commitment — Pillar G's role is operator-visible regression-prevention; if observability quietly absorbs any new event class, the SLO alerting + the dashboards drift silently from the per-pillar binding events.
* The closed-set enforces the per-pillar foundation ADR's discipline — every new event class MUST coordinate with the catalog.
* Operators consuming the dashboards have no way to detect a contributor's silent introduction of a new class without comparing against an external catalog; the closed-set IS the catalog.

### D272-Alt2: Per-pillar sub-frozensets composed at module level

`_PILLAR_A_EVENT_CLASSES` + `_PILLAR_B_EVENT_CLASSES` + ... composed into `EVENT_CLASS_CATALOG = frozenset.union(...)`. **Rejected** because:

* Creates the "look in seven places" mental model. The catalog's load-bearing role is a SINGLE reference point for operators + dashboards + future pillar authors.
* The per-pillar split duplicates the per-pillar foundation ADR's event-class table; the catalog IS the consolidated view.
* Future pillar authors adding a NEW event class would need to update both the foundation ADR table AND the per-pillar sub-frozenset — split-source-of-truth.

### D272-Alt3: Per-call enumeration via caller-passed kwarg

The primitive accepts a caller-supplied `expected_classes: frozenset[str]` kwarg without a module-level default. **Rejected** because:

* Forces every caller to know the full event-class catalog; the module-level constant is the canonical source.
* Tests + dashboards + alerts would each duplicate the catalog at their call sites — high drift risk.
* The module-level catalog IS the operator-readable single-point reference per D272.

### D272-Alt4: Schema-discovery primitive that introspects every event type in the ledger

The primitive walks the ledger + emits a snapshot for every distinct event type encountered. **Rejected** because:

* Per-call cost balloons (every call requires a full ledger walk to discover types; the current contract walks the ledger ONCE per call but only aggregates within the catalog).
* Loses the closed-set regression-barrier — the same concern as D272-Alt1.
* For "what types exist?" diagnostics, operators consult `python orchestrator/ledger.py grep` + sort/uniq; that's a different use case than per-event-class aggregation.

### D273-Alt1: Prometheus-direct via `prometheus_client`

The framework uses Python's bare-bones Prometheus client without OTel. **Rejected** because:

* Loses traces — PILLAR-PLAN §2 Pillar G explicitly names "OpenTelemetry tracing through the whole pipeline." Prometheus-direct covers metrics but not traces.
* Cross-vendor portability is lost — operators with Honeycomb / Datadog / Grafana Cloud / etc. would need to re-instrument; OTel SDK's vendor-neutral instrumentation surface lets operators point their OTLP collector at the framework without code changes.
* Operators with different observability backends would need bespoke adapters; OTel SDK is the cross-vendor standard.

### D273-Alt2: Structured-logs-only via `structlog` + post-hoc log aggregation

The framework emits structured logs + operators post-hoc aggregate via Loki + LogQL OR similar. **Rejected** because:

* Loses real-time aggregation — SLO violation alerting requires real-time metric evaluation; structured-logs alone don't deliver this.
* Loses traces' parent-span relationships — structured logs are per-event flat; traces are hierarchical (a `send_intent` span has child `gmail_api_call` + `vault_write` spans). Post-hoc reconstruction is high-cost.
* The `cost_incurred` event aggregation per Pillar A budget rules would still need a real-time path — structured-logs add a redundant aggregation layer.

### D273-Alt3: Defer the framework choice to Pillar H

Pillar G Week 1 ships the audit + the primitive shape but defers the framework choice to Pillar H. **Rejected** because:

* Breaks the Week 1 foundation precedent — Pillar A through F each pinned its framework choice at Week 1; deferring creates a structural gap.
* Per-week implementations can't proceed without the framework substrate; Week 2 ships the primitive body, Week 3 needs the framework to wire OTel SDK initialization.
* The Pillar H + I deferral pattern applies to specific per-tenant + scale optimizations, NOT foundational framework choices.

### D273-Alt4: Multiple frameworks (OTel SDK + Prometheus-direct + structlog) for flexibility

The framework supports operator-configurable choice of OTel SDK vs Prometheus-direct vs structlog. **Rejected** because:

* Inflates surface area — each framework's per-week implementation cost is comparable; supporting all three increases implementation cost ~3x with no proportional operator-visibility gain.
* Operators with different backends still consume one framework's output; the OTel-with-Prometheus-exporter bridge already supports the dominant operator setups.
* Per-framework drift would compound across Pillar G weeks; one framework simplifies the per-week-reviewer's checklist.

### D274-Alt1: Skip the audit since Pillar G doesn't extend the ledger event class set materially

The Week 1 commit ships only test stubs + ADR + handoff; the two new event classes (`observability_class_uncatalogued` + `slo_violation_detected`) are content-additive. **Rejected** because:

* The PILLAR-PLAN §2 Pillar G binding text names cross-pillar consumption ("OpenTelemetry tracing through the whole pipeline" + "where am I losing prospects?" requires walking every pillar's event class); the audit must walk every existing consumer for whether the new dashboards silently broaden the input space.
* The Pillar A/B/C/D/E/F precedent at Week 1 is the audit lands AT WEEK 1 against the EVENTUAL event-class set + the EVENTUAL operator-facing surfaces — every prior pillar's Week 1 audit caught ≥1 pre-existing P2 (the "Pillar X Week 1 catches a pre-existing surface bug" pattern is the load-bearing prediction from RETRO-pillar-f.md).
* Without the audit at Week 1, the Week 2-12 commits' P1/P2 catch rate drops.

### D274-Alt2: Defer the audit to Week 2 (when the first primitive ships)

The Week 1 commit ships only test stubs; the audit lands at Week 2 alongside the `collect_event_class_snapshots` body. **Rejected** because:

* The Pillar A/B/C/D/E/F precedent at Week 1 is unambiguous: the audit lands AT WEEK 1.
* Deferring creates a structural gap (the per-week-reviewer's Week 1 checklist row "the surface audit was extended" has nothing to check); the discipline degrades.

### D274-Alt3: Defer the audit to Pillar I OSS bring-up

Treat the audit as a Pillar I deliverable. **Rejected** because:

* The audit's role is per-pillar load-bearing anti-regression; deferring to Pillar I (two pillars later) creates a 2-pillar-wide gap where Pillar G's Week 1-12 commits are not audit-protected.
* The Pillar A/B/C/D/E/F precedent is unambiguous.

### D275-Alt1: Separate `tests/test_pillar_g_observability.py` file

A new file dedicated to Pillar G's exit-criterion vehicle. **Rejected** because:

* Fragments the coherence vehicle; the `tests/test_multi_channel_coherence.py` file's load-bearing property is single-file cross-pillar coherence per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183.
* Splits the per-Pillar-G test classes from the per-Pillar-C/D/E/F test classes that share the same coherence-vehicle imports + fixtures.
* Creates the "look in two places" mental model rejected at every Pillar A/B/C/D/E/F foundational ADR.

### D275-Alt2: Defer Pillar G test class additions to Week 2 (when the primitive ships)

The Week 1 commit lands the ADR + the audit; the test classes land at Week 2. **Rejected** because:

* The Pillar A/B/C/D/E/F precedent at Week 1 is the test classes land AT WEEK 1 as stubs; the per-week deliverables un-skip rows incrementally per the carry-forward conventions.
* Deferring creates a structural gap (the per-week-reviewer's Week 1 checklist row "the test stubs name the per-week un-skip trajectory" has nothing to check).

### D275-Alt3: Split `tests/test_multi_channel_coherence.py` at Week 1 since it crosses ~7500 LOC

The Week 1 commit splits the test file into `tests/test_multi_channel_coherence.py` (Pillar C/D core) + `tests/test_pillar_e_f_g_coherence.py` (Pillar E+F+G stubs) per the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266. **Rejected** because:

* The split should land at a CLEAN test-class boundary (a natural break point in the file's per-pillar structure); the Pillar G Week 1 commit's stub additions don't dictate the split-point.
* Pillar G Week 1's extension adds ~250-400 lines; the file grows from ~8000 to ~8400 LOC — still operator-readable.
* Splitting at Pillar G Week 1 forces every Pillar G Week 2-12 author to navigate the split + re-justify the boundary; deferring to a Pillar G Week N reviewer's call lets the boundary land at a natural break.
* The Pillar F Week 12 commit explicitly DEFERRED the split per ADR-0049 D266; Pillar G Week 1 inherits the deferral.

### D275-Alt4: ONE Pillar G class instead of three

Combine all three test classes into one `TestPillarG` class. **Rejected** because:

* The three concerns (observability primitive coherence + SLO alerting + exit-criterion composition) are structurally distinct — the primitive is the substrate; SLO alerting is a downstream consumer; exit-criterion is the composition test.
* Per-class test organization mirrors the per-primitive shape (Pillar E's four primitives have four per-primitive test classes + one exit-criterion class; Pillar F's three per-primitive test classes + one exit-criterion class); Pillar G follows the same convention.

### D276-Alt1: Make SLO alerting default ON (not opt-in)

Default the Slack webhook alerting ON; operators opt OUT if they don't want alerts. **Rejected** because:

* The OSS bring-up trajectory (Pillar I) treats operator-deliberate configuration as the default posture; alerting that fires without operator intent is a privacy + noise hazard for new operators evaluating the framework.
* Slack webhook URLs are operator-private + per-tenant; default-ON requires either a global webhook (privacy violation) or per-tenant config that doesn't exist at Pillar G's single-tenant scope.
* Asymmetric-failure-cost: an alert that fires when operator didn't want it is recoverable (operator disables); an alert that DOESN'T fire when operator wanted it is recoverable too (operator enables); the cost asymmetry slightly favors default-OFF because new operators don't see surprise alerts.

### D276-Alt2: Defer the privacy invariant naming to a separate Pillar G week

Pillar G Week 1 ships only the framework + primitive shape; the privacy invariants land at a Pillar G Week N. **Rejected** because:

* Per RETRO-pillar-f.md item-4 + RETRO-pillar-e.md item-4 + RETRO-pillar-d.md item-5: invariants are DESIGNED at Week 1 even when the implementation lands later. The Week 1 design pins the convention; the implementation consumes the convention.
* Deferring contradicts the eight Pillar A/B/C/D/E/F carry-forward conventions.
* The privacy invariant per I8 is load-bearing — it gates EVERY Pillar G dashboard + EVERY Pillar G CLI extension; deferring would force every Pillar G week 2-N commit to re-design the constraint.

### D276-Alt3: Allow per-tenant fan-out at Pillar G

Pillar G ships per-tenant aggregation surfaces. **Rejected** because:

* Multi-tenant is Pillar I OSS-hardening scope per RETRO-pillar-f.md item 8 + ADR-0049 §Downstream pillar impact.
* Pillar G's substrate (Prometheus + Grafana + OTel SDK) is single-tenant by convention; multi-tenant aggregation would require per-tenant Prometheus namespace + per-tenant Grafana folder isolation — adding ~2 weeks of implementation cost at Pillar G with no Pillar G-specific operator value.
* Pillar I's per-tenant audit-tooling is the natural home; Pillar G stays single-tenant by design.

### D277-Alt1: Defer the per-Person observability surface to Pillar G Week 10+ entirely

Pillar G Week 1 doesn't pin the per-Person consumption pattern; future Pillar G weeks design it ad-hoc. **Rejected** because:

* Loses the structural commitment from Pillar F's Week 12 close (ADR-0049 D262-D271 + ADR-0049 §Downstream pillar impact named Pillar G's consumption of Pillar F's four event classes + the Layer 5 reason).
* Per-week implementations would re-design the per-Person dashboard surface without a foundation; the per-event-class symmetry pattern per RETRO-pillar-f.md item 5 would not amortize.
* Future Pillar I per-tenant audit-tooling consumes the Pillar G per-Person dashboard's aggregation primitives; deferring leaves Pillar I without a substrate to extend.

### D277-Alt2: Per-Person dashboard shape diverges from per-pillar dashboard shape

Pillar G's per-Person dashboards have a separate aggregation primitive from the per-pillar dashboards. **Rejected** because:

* Loses the per-event-class symmetry pattern — Pillar G's value is uniform per-event-class consumption; per-Person + per-pillar dashboards should share the substrate per the shared-aggregation-primitive-with-thin-adapters convention.
* Inflates surface area — two aggregation primitives + two test surfaces + two ADR forward-references per future Pillar G week.

### D277-Alt3: Surface per-claim trace + per-exemplar body in per-Person dashboards

The per-claim trace text + the per-exemplar body content surface in per-Person dashboards for operator-deliberate audit. **Rejected** because:

* Violates the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 — per-claim trace text + per-exemplar bodies contain operator-confidential content (prospect dossier extracts + Yang's curated email corpus content).
* Operators inspect per-claim trace via upstream `hallucination_detected` event's per-claim trace + per-exemplar IDs via upstream `voice_exemplar_retrieved` event's `exemplar_id` — the existing ledger primitives surface this; observability dashboards should NOT.

## Consequences

### Positive consequences

* **The Pillar G substrate is named at Week 1.** Future Pillar G Week 2-12 commits land against an established target (the per-event-class observability primitive shape + the OTel SDK framework + the closed-set `EVENT_CLASS_CATALOG` + the four load-bearing invariants + the per-Person observability surface contract + the audit + the test classes). The per-week reviewer's fresh-context catch rate (per RETRO-pillar-f.md §"What worked") amortizes.
* **The OTel SDK + Prometheus exporter + Grafana-as-code framework choice is pinned.** Pillar G's per-week implementations consume the framework without re-opening the choice; operators with different observability backends consume the same OTel-instrumented codebase via OTLP collectors.
* **The privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 is the structural commitment.** Pillar G's dashboards + CLI extensions + SLO alerting all respect the per-pillar privacy invariants; the `_breakdown_dims_allowed` frozenset is the regression-barrier.
* **The closed-set `EVENT_CLASS_CATALOG` is the regression-barrier per R031.** A future contributor adding a NEW event class without coordinating with the catalog triggers the `observability_class_uncatalogued` event (operator-visible signal); the catalog IS the per-pillar event-class enumeration's canonical source.
* **The cross-pillar audit per D274 is the per-week reviewer's load-bearing artifact.** Every Pillar G week's commit either extends the audit OR confirms unchanged; the per-week reviewer's checklist row is concrete.
* **The exit-criterion test vehicle per D275 is the binding gate.** The "ONE CLI invocation answers the three load-bearing questions" is the structural verification; Pillar G's Stable flip at Week 12 is gated by the binding test passing.
* **The per-Person observability surface per D277 consumes Pillar F's four event classes + the Layer 5 reason uniformly.** The brand-and-legal-liability surface from Pillar F is operationally visible; Pillar I per-tenant audit-tooling extends on the Pillar G substrate.

### Negative consequences

* **Test count grows by 3 (three test class stubs).** The cumulative test count: 3334 (post-Pillar-F-Week-12-follow-up) + ~3-5 (per-class stub additions, with most skipped at Week 1; the few un-skipped rows that pin contract-level invariants un-skipped at Week 1 add ≤ 5 passing tests). The growth is bounded.
* **Skip count rises by ~10-15 (per-class stub additions).** Pillar G adds three test classes with ~4-5 stubs each per the per-primitive coherence pattern. Most stays SKIPPED through Week 1; un-skips happen incrementally per the D273 trajectory table + the per-week ship pattern.
* **The `tests/test_multi_channel_coherence.py` file's size grows.** Currently ~8000 lines; this commit adds ~250-400 lines (the stub classes). The file is past the ~7500 LOC split threshold flagged by ADR-0037 D172 + ADR-0049 D266; Pillar G Week 1 does NOT split (the per-pillar Week 1 stub belongs adjacent); future Pillar G weeks MAY split.
* **The per-week-reviewer's load grows.** The audit's per-week extensions + the per-week handoff doc + the per-week test-class extensions + the per-week-review-with-follow-up-commit discipline create per-week artifact volume. The Pillar A/B/C/D/E/F precedent shows the load amortizes per the per-week pattern.
* **OTel SDK adds a dependency.** Pillar G's framework choice adds `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-prometheus` (or equivalent) to the framework's Python dependency surface. The dependencies land at Pillar G Week 2-3 (when the SDK initialization ships); operators upgrading from Pillar F see a `pip install` step in the §Existing-operator seed below.

### Risks

The asymmetric-failure-cost calculus (PILLAR-PLAN §0) carries:

* **The Week 1 ADR's design decisions get challenged at Week 2-12 (P2):** the `EVENT_CLASS_CATALOG`'s closed-set proves inadequate for a Week 6+ adapter need; OR the OTel SDK framework choice surfaces a vendor-portability concern. **Bounded by** the per-week amendment pattern per ADR-0033's §Amendment 2026-05-24 — the foundation ADR receives an amendment without re-opening the per-week shipping.
* **The OTel SDK initialization surfaces a per-process state concern (P2):** the SDK's global state model (the OTel TracerProvider + MeterProvider are process-global by convention) conflicts with multi-process operator setups. **Bounded by** D276(d) — Pillar G is single-tenant single-process by design; Pillar H (daemon) revisits at multi-process scale.
* **The Grafana-as-code dashboard repository surfaces a per-tenant concern (P3):** Pillar I per-tenant audit-tooling may want per-tenant dashboard folders. **Bounded by** D276(d) — Pillar G stays single-tenant; Pillar I extends.

The framework's existing safeguards bound the regression failure modes by design.

## Compliance with invariants

* **I1 — Ledger is single source of truth.** Preserved. Pillar G is consumer-side; observability outputs are denormalized rebuildable views per the existing SOURCES-OF-TRUTH.md convention.
* **I2 — Two-phase commit (intent + outcome) for every send.** Preserved. Pillar G is downstream of every send-path event; no changes to send-path semantics.
* **I3 — Atomic per-Person enrollment.** Preserved. Pillar G is consumer-side; no changes to enrollment semantics.
* **I4 — Per-channel state isolation.** Preserved. Pillar G's per-event-class aggregator respects the channel-on-every-event invariant per ADR-0014 D33; the `MetricSnapshot.channel` field carries the channel uniformly.
* **I5 — Observable by default.** EXTENDED. Pillar G IS the operationalization of I5 — every refusal + every external call + every reconcile drift surfaces in operator-visible dashboards via the per-event-class aggregator + the SLO alerting.
* **I6 — Channel-on-every-event invariant.** Preserved. The two new Pillar G event classes (`observability_class_uncatalogued` + `slo_violation_detected`) carry `channel: <channel | null>` per the channel-stamping convention.
* **I7 — Refuse-loud on operator misconfiguration.** Preserved. The `EVENT_CLASS_CATALOG`'s permissive-aggregate-with-explicit-enumeration refuse-loud via `observability_class_uncatalogued` emit; the `_breakdown_dims_allowed` frozenset's refuse-loud on privacy-violating dimensions; the SLO alerting's default-OFF posture refuses to fire without operator-deliberate opt-in.
* **I8 — Privacy-respecting (`source_list` operator-private + recipient research-dossier content operator-private + voice-corpus exemplar bodies operator-private).** Preserved + EXTENDED. Pillar G's per-event-class aggregator's `_breakdown_dims_allowed` frozenset enforces the privacy invariant at the primitive's call surface; the per-Person dashboards aggregate COUNTS + scores but NOT trace text / dossier content / exemplar bodies / draft body content.

## Downstream pillar impact

* **Pillar H (Daemon + dispatcher, begins Week 37).** Pillar H consumes the Pillar G OTel SDK instrumentation for per-stage parallelism observability + the per-channel rate-limit dashboards for backpressure tuning. The daemon's health endpoint + readiness probe + per-stage latency histograms feed the Pillar G Prometheus exporter; the daemon's SIGHUP-based policy reload emits a `manual_override`-shaped event that Pillar G's SLO alerting per D276 surfaces for compliance review. Pillar H also surfaces multi-process state concerns the OTel SDK's process-global model addresses (per-process Tracer / Meter providers; cross-process aggregation via Prometheus pull).

* **Pillar I (Multi-tenant + OSS hardening, begins Week 43).** Pillar I extends the Pillar G substrate with per-tenant fan-out per the per-tenant audit-tooling trajectory:
  * Per-tenant Prometheus namespace + per-tenant Grafana folder isolation.
  * Per-tenant SLO threshold overrides (operator-tunable per-tenant config).
  * Per-tenant `EVENT_CLASS_CATALOG` extensions (per-tenant event classes for per-tenant integrations).
  * Per-tenant `_breakdown_dims_allowed` overrides (per-tenant privacy invariants).
  * Per-tenant CLI doctor extension verifying observability config + OTel collector reachability.
  * Per-tenant audit-tooling that consumes the Pillar G per-Person observability surface per D277 — per-operator override-rate dashboards (filtering `draft_ready.hallucination_check == "passed_via_override"` per ADR-0049 §Downstream pillar impact); per-tenant Layer 5 drift-rate dashboards (filtering `reconcile_drift.reason == "ready_without_draft_ready_event"` per ADR-0049 D263); per-tenant fuzzy_threshold tuning dashboards (consuming Pillar F per-claim-type bound tables per ADR-0048 D256).

* **Pillar J (Security + compliance, begins Week 49).** GDPR-purge transaction extends to purge Pillar G observability state for a Person on forget request. Per-Person dashboard cache entries are purged; aggregate metrics (per-tenant counts, per-channel ratios) survive (operator-aggregate-only, no per-Person identifiable content). Pillar J's compliance audit consumes Pillar G's per-`manual_override` event surface for the legal-audit trail. The Pillar J commit extends the cross-pillar audit with the per-Person Pillar G observability surface's verdict.

## Migration / rollout

**Week 1 ships ZERO new migrations.** Pending count stays at 19 (vault/0005 + ledger/0007 from Pillar E Week 9-11 + the 17 pre-existing pending migrations). Operators upgrading from Pillar F Week 12 to Pillar G Week 1:

1. **Operator updates the framework** to Pillar G Week 1's commit (the standard `git pull`).
2. **Operator runs `python -m orchestrator.migrations doctor apply`** — no-op since Pillar G Week 1 ships zero migrations.
3. **Operator runs `python -m pytest tests/test_multi_channel_coherence.py::TestPillarGObservability tests/test_multi_channel_coherence.py::TestPillarGSLOAlerting tests/test_multi_channel_coherence.py::TestPillarGExitCriterion -v`** to verify the Week 1 test stubs are collectable + the few un-skipped contract-level rows pass. Optional but recommended.

**Subsequent Pillar G weeks' migrations** (forward-reference): Week 2 ships zero migrations (the `collect_event_class_snapshots` body is content-additive); Weeks 7-8 MAY ship `ledger/0008_observability_event_index` for per-event-class indexing IF the per-call O(N) ledger walk's cost surfaces as a bottleneck (TBD per the per-week design); Week 12 ships the binding test un-skip (zero migrations).

**Python dependencies (Week 2-3 ships):**
* `opentelemetry-api` (Apache 2.0; vendor-neutral)
* `opentelemetry-sdk` (Apache 2.0)
* `opentelemetry-exporter-prometheus` (Apache 2.0)
* Plus an OTel-instrumented Prometheus client. The `pip install` step lands in the operator-side §Existing-operator seed below at Week 2-3's commit.

No operator-facing surface changes at Week 1. The Week 1 commit is foundation + test stubs + audit + ADR + handoff + framework decision + per-pillar event-class catalog; operators benefit from the structural stability the foundation pins.

## Existing-operator seed

**Pillar G Week 1 ships no operator-side state changes.** The observability primitive shape is pinned but the implementation lands at Week 2+.

The operator-side migration trajectory (per-week ships across Pillar G Weeks 1-12):

* **Week 1 (this commit):** Foundation ADR + test stubs + audit + handoff. NO operator action required. The `EVENT_CLASS_CATALOG` constant is named (read-only); the `MetricSnapshot` dataclass shape is named (read-only); the OTel SDK + Prometheus exporter + Grafana-as-code framework choice is pinned.
* **Week 2:** The `collect_event_class_snapshots` primitive body ships ALONGSIDE the existing `funnel.py` CLI; operators consume via the existing CLI's NEW extended breakdown dimensions. No operator action required at upgrade.
* **Week 3-4:** OTel SDK initialization + Prometheus exporter ship; operators wire the OTel collector at `~/.outreach-factory/config.yml`'s `observability:` block (NEW block); default endpoint is `localhost:4318` (OTLP/HTTP). Operators with a local Prometheus + Grafana stack add the framework as a scrape target.
* **Weeks 5-6:** OTel tracing instrumentation lands; operators see per-stage spans in their OTel backend.
* **Weeks 7-8:** SLO violation alerting ships (default OFF); operators opt in via `observability.slo_alert_webhook_url` config.
* **Week 9:** Cost dashboard renders the per-source `cost_incurred` aggregation (Anthropic + Apollo + PDL + Reoon + Gmail + LinkedIn); operators see per-vendor spend.
* **Weeks 10-11:** Per-Person observability dashboards render per-Pillar-F event-class aggregations; operators see per-register fidelity distributions + per-claim-type hallucination counts + per-Person Layer 5 drift rates.
* **Week 12:** Binding exit-criterion test un-skips; Pillar G flips to Stable.

**Operator action required at Week 1:** NONE. The foundation is read-only.

**Operator action recommended at Week 1:** review `docs/PILLAR-PLAN.md` §6 Pillar G row's updated trajectory. Operators planning to wire an OTel backend (Honeycomb / Datadog / Grafana Cloud / self-hosted Prometheus) may begin reading the OTel SDK + Prometheus exporter docs ahead of the Week 2-3 primitive ship.

## References

- **ADR-0006 (D5)** — Pillar A budget rules + `cost_incurred` event substrate. Pillar G's cost dashboard consumes this directly.
- **ADR-0014 (D33 + D37)** — Pillar C foundation (channel-on-every-event invariant + the cross-pillar coherence test vehicle's single-file rationale). Pillar G inherits both.
- **ADR-0025 (D97 + D101)** — Pillar D foundation (the CAN-SPAM legal-liability invariant precedent + the cross-pillar coherence vehicle's Pillar D extension). Pillar G's load-bearing invariants per D276 mirror.
- **ADR-0031 (D140 + D141)** — Pillar D Week 12 funnel CLI + Pillar D Stable-flip discipline. Pillar G EXTENDS the funnel CLI per D276(a) + mirrors the Stable-flip discipline.
- **ADR-0032 (D142-D148)** — Pillar E foundation (the discovery_lineage shape + the cross-pillar audit + the exit-criterion vehicle scope + the privacy invariant). Pillar G mirrors at D277 (per-Person observability surface) + D274 (cross-pillar audit) + D275 (exit-criterion vehicle) + D276(b) (privacy invariant per I8).
- **ADR-0037 (D172-D177)** — Pillar E Week 12 exit-criterion close (the binding-test-as-gate + per-pillar stable-flip checklist + per-pillar retrospective discipline precedent). Pillar G's Week 12 will mirror.
- **ADR-0038 (D178-D184)** — Pillar F foundation (the voice-corpus schema + the embedding-retrieval contract + the FIVE-layer hallucination-detection defense + the per-register-symmetry pattern + the cross-pillar audit + the exit-criterion vehicle + the voice-fidelity invariant + the hallucination-detection invariant). Pillar G's D272 + D273 + D274 + D275 + D276 + D277 mirror.
- **ADR-0049 (D262-D271)** — Pillar F Week 12 exit-criterion close (Layer 5 reconcile heal-pass refusal + Pillar F Stable flip + retrospective + per-week-reviewer carry-forward checklist). Pillar G's D274 + D277 + the cross-pillar audit's category 12 inherit the per-week-reviewer carry-forward discipline + the Layer 5 reason-precedence drift pattern.
- **ADR-0036 (D166-D171)** — Pillar E Week 9-11 discovery_lineage stamping (the symmetric per-skill stamping precedent). Pillar G's per-event-class symmetry pattern per D277 mirrors.
- **ADR-0035 (D160-D165)** — Pillar E Week 6-8 tier auto-assignment (the operator-tunable per-signal weights precedent + the graceful-degradation contract). Pillar G's operator-tunable SLO thresholds per D276(d) mirror.
- **ADR-0034 (D154-D159)** — Pillar E Week 4-5 cache primitive (the cost-event substrate extension precedent + the deterministic-clock per-call kwarg pattern). Pillar G's D272 inherits the deterministic-clock pattern.
- **`.planning/REVIEW-pillar-g-surface-audit.md`** — the load-bearing cross-pillar audit; Week 1 establishes baseline + per-Pillar-A/B/C/D/E/F surface walk + per-week-reviewer carry-forward disciplines from Pillar F.
- **`.planning/HANDOFF-pillar-g-week-1.md`** — this week's handoff document (per the per-week handoff convention).
- **`.planning/RETRO-pillar-f.md` §"What to do differently in Pillar G"** — the eight carry-forward recommendations Pillar G Week 1 honors.
- **`docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row** — the binding exit-criterion text + the per-week trajectory ticker that flips to **In progress** at this commit.
- **`docs/SOURCES-OF-TRUTH.md` Observability row** — the SoT registry's pre-declared row (Pillar G formalizes at Week 1 per D272; observability outputs are denormalized rebuildable views).
- **`docs/RISK-REGISTER.md` R031 + R032 + R033** — the three new Pillar G risks named at design time per Week 1's risk surfacing discipline.
- **`orchestrator/funnel.py`** — the existing Pillar D Week 12 funnel CLI (per ADR-0031 D140); Pillar G EXTENDS this CLI's breakdown dimensions per D276(a) + adds the per-event-class snapshot section per D272.
- **`orchestrator/ledger.py`** — the per-Person `_idx_person` index + the `Event` class shape + the `Ledger.all_events()` walk. Pillar G's primitive consumes these via the existing query patterns.
- **`orchestrator/policy/budget.py`** — the `cost_incurred` event substrate (per ADR-0006). Pillar G cost dashboard consumes this directly.
- **`orchestrator/reconcile.py`** — Pass C's Layer 5 backstop + the `_DRIFT_REASONS` closed-enum + the `_person_has_draft_ready_event` predicate. Pillar G per-Person observability surface per D277 consumes the `reconcile_drift.reason` field.
- **`tests/test_multi_channel_coherence.py`** — the cross-pillar coherence test vehicle. Pillar G Week 1 extends with `TestPillarGObservability` + `TestPillarGSLOAlerting` + `TestPillarGExitCriterion` test classes per D275.
