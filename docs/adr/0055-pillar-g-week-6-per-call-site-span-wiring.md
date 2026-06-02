# ADR-0055: Pillar G Week 6 — Per-stage span instrumentation at the per-pillar Python call sites, send-latency Histogram dispatcher integration (Week 4 carry-forward), per-stage operation naming conventions, privacy invariant propagation at call-site span emissions

- **Status:** Accepted
- **Date:** 2026-05-26
- **Pillar:** G (Observability — Week 6 per-call-site span wiring + dispatcher integration)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0050 (Pillar G Week 1 foundation, D272-D277) pinned the per-event-class observability primitive shape + the OTel SDK + Prometheus exporter + Grafana-as-code framework decision per D273. ADR-0051 (Pillar G Week 2, D278-D281) shipped the `collect_event_class_snapshots` body + the `observability_class_uncatalogued` diagnostic emit. ADR-0052 (Pillar G Week 3, D282-D287) shipped the OTel SDK initialization + the single canonical Meter scope + the per-event-class ObservableCounter + the cumulative-counter semantics + the framework-neutrality contract + the default Resource-attribute closed-set. ADR-0053 (Pillar G Week 4, D288-D293) shipped the Prometheus exporter wiring + the per-channel send-latency Histogram instrument + the reconcile success ratio ObservableGauge + the Prometheus HTTP exposition server + the framework-default View set + the first Grafana-as-code dashboard. ADR-0054 (Pillar G Week 5, D294-D299) shipped the OTel tracing initialization + the canonical Tracer scope + the per-stage `traced_stage` context manager + the `_PIPELINE_STAGES` closed-set + the `_SPAN_ATTRIBUTES_ALLOWED` closed-set + the framework-neutrality contract for tracing + the **ZERO call-site wiring at Week 5** posture (D299) which explicitly deferred per-stage span instrumentation at the pipeline call sites to Week 6.

Pillar G Week 6 ships the **per-stage span instrumentation at the per-pillar Python call sites across the eight pipeline stages** (discovery → enrichment → research → draft → review → send → reply → win_loss) + **completes the Week 4 carry-forward for the send-latency Histogram dispatcher integration** at the per-channel two-phase commit point in `skills/send-outreach/scripts/send_queued.py`. The seven concerns this ADR resolves:

1. **Per-call-site span wiring at the per-pillar primitives.** The Week 5 `traced_stage` helper is a context manager wrapping a function body. The framework MUST decide WHICH primitives' bodies get wrapped (Pillar E discovery primitives + Pillar E enrichment primitives + Pillar F voice-corpus retrieval + Pillar F draft-quality scoring + Pillar F Layer 5 reconcile backstop + Pillar D reply classifier + Pillar D conversation outcomes + Pillar C dispatchers) AND WHAT span name + attribute conventions each call site uses. Per ADR-0050 D273's per-week trajectory + ADR-0054 D299's Week 5 → Week 6 split: Week 6 IS the application week.

2. **Per-stage operation naming conventions.** Each call site's `operation` parameter is FREE-FORM (per ADR-0054 D296 — no closed-set on `operation`, only on `stage`). Operators consuming the OTel tracing backend filter by `outreach_factory.<stage>.<operation>` span name. The framework MUST pin canonical operation names per primitive to preserve cross-pillar consistency + prevent the per-week-reviewer's `cross-pillar back-audit` discipline from surfacing inconsistent naming as a NEW finding pattern.

3. **Span attribute set at each call site.** Each primitive's call-site `attributes` dict MUST respect `_SPAN_ATTRIBUTES_ALLOWED` per ADR-0054 D297. The framework MUST decide which attributes ARE passed at each call site (channel + register + person_id + source_skill + category + classification_method + outcome + reason + result_state are the per-event-class breakdown dims) — under-attribution loses operator-actionable per-Person filtering, over-attribution violates the privacy invariant.

4. **Body-wrapping convention vs partial-wrapping.** For each primitive, the framework MUST decide WHERE the span wrapping begins (entry point of the public function vs entry of a sub-section). The Week 5 design ships the helper as a context manager; the wrapping shape determines what scope of operations the span covers + which attributes are knowable at entry-time vs deferred via `set_attribute`. Two patterns surface across the 13 call sites:
   * **Inner-function pattern** (5 of 13: `compute_tier_from_signals`, `run_pass_c`, `gated_send_one`, `gated_li_invite_one`, `gated_li_dm_one`, `gated_tw_dm_one`, `gated_calendar_booking_one`): public function wraps `with traced_stage(...) as _span:` around a call to a new `_<name>_inner` private function carrying the existing body. Preserves the body's indentation + readability for ~50-300 line bodies.
   * **In-body context-manager pattern** (3 of 13: `check_dedup`, `score_draft`, `emit_classified_event`, `run_conversation_outcomes_pass`): public function indents the existing body inside `with traced_stage(...):`. Acceptable for short bodies (~10-50 lines).
   The pattern choice IS per-call-site; both patterns preserve the existing primitive surfaces verbatim per the legacy-state-vs-new-defense-layer tension discipline.

5. **Send-latency Histogram dispatcher integration (Week 4 carry-forward).** Per ADR-0053 D289 + §Negative — the per-channel send-latency Histogram instrument shipped at Week 4 as SHAPE-only; the dispatcher integration was deferred. The integration MUST (a) record elapsed time at the external API call boundary (not at function entry — the Histogram measures the API call latency that drives the p99 SLO per PILLAR-PLAN §2 Pillar G); (b) carry the per-channel attribute per ADR-0014 D33 + ADR-0053 D289; (c) be best-effort — observability failure MUST NOT break dispatch per the historical convention from `cost_incurred` emit's try/except-best-effort posture in the same dispatcher.

6. **Calendar dispatcher histogram exclusion.** The `gated_calendar_booking_one` dispatcher's send action is URL synthesis (no external API call per ADR-0019 D66); the Cal.com `calendar_booking_confirmed` event arrives LATER via the webhook handler (`orchestrator/cal_com_webhook.py`). The framework MUST decide whether to record histogram (a) at URL synthesis time (would measure ~microseconds — uninformative against the 5s SLO threshold per PILLAR-PLAN §2 Pillar G); (b) at the webhook handler's confirmation time (would measure days-of-delay between intent + confirmation — uninformative as a send-latency signal); (c) skip the histogram for calendar entirely (matches the dispatcher's asymmetric two-phase shape per ADR-0019 D66). Per the framework-neutrality + minimum-surface discipline: option (c).

7. **Privacy invariant propagation at the per-call site.** Each primitive's call-site MUST pass attribute dict keys from `_SPAN_ATTRIBUTES_ALLOWED` (per ADR-0054 D297). The framework MUST verify the `source_list` / `draft_body` / `dossier_body` / `exemplar_body` / `claim_text` keys do NOT enter ANY span at ANY call site — the per-call-site enforcement of `_SPAN_ATTRIBUTES_ALLOWED` IS the structural mitigation (the helper refuses-loud at attribute validation time; per-week reviewer's cell-level matrix verifies via positive + negative tests).

Risks this ADR's design surfaces:

- **R031 (Per-event-class observability primitive over-broadens consumer surface)** — UNCHANGED from ADR-0050 + ADR-0052 + ADR-0053 + ADR-0054; the closed-sets `EVENT_CLASS_CATALOG | OBSERVABILITY_NEW_EVENT_CLASSES` (Week 1) + `_PIPELINE_STAGES` (Week 5) + `_SPAN_ATTRIBUTES_ALLOWED` (Week 5) IS the layered mitigation. Week 6's per-call-site wiring CONSUMES the closed-sets via `traced_stage`.

- **R033 (Observability primitive's cache-substrate divergence on multi-process operator)** — UNCHANGED. Week 6's per-call-site span emit is per-process via OTel's TracerProvider; multi-process daemons (Pillar H scope) may need per-daemon-process TracerProvider isolation. The stateless callback contract per ADR-0052 D284 + the `set_global=False` mitigation per ADR-0052 D282 + ADR-0054 D294 + R035 are unchanged at Week 6.

- **R034 (Diagnostic emit at every primitive call inflates ledger when catalog drift persists)** — UNCHANGED. Week 6's per-call-site wiring does NOT introduce new ledger writes (spans go via OTel SDK; the diagnostic emit per ADR-0051 D279 is unaffected).

- **R035 (OTel SDK's set-once `set_meter_provider` + `set_tracer_provider` enforcement)** — UNCHANGED + EXTENDED at Week 6 via the per-call-site `traced_stage` invocations. Each invocation consults the global TracerProvider via `get_tracer()`; production callers initialize ONCE at startup. Tests bypass via `monkeypatch.setattr(observability, "get_tracer", ...)` + `monkeypatch.setattr(observability, "get_meter", ...)` — the patch surface preserves test isolation without OTel's set-once enforcement on the global state.

- **R036 (Prometheus HTTP exposition server exposes per-process metrics)** — UNCHANGED. Week 6's send-latency Histogram dispatcher integration writes to the EXISTING Histogram instrument shipped at Week 4; no new HTTP exposition surface lands.

ZERO new R-risks surfaced at Week 6. The framework-neutrality contract per ADR-0052 D286 + ADR-0053 D288 + ADR-0054 D298 preserves the operator-choice posture across both metric + trace surfaces; the closed-set discipline per `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` preserves the R031-shape regression-barrier; the privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0051 D278 + ADR-0052 D284 + ADR-0053 D292 + ADR-0054 D297 carries through to per-call-site span attributes via D304.

The Pillar F primitive surfaces preserve verbatim. The Layer 5 backstop preserves verbatim. The TEST-ONLY embed_fn + retrieve_fn seams stay LIVE at the FIVE upstream surfaces unchanged from Pillar F Week 12. The Pillar G Week 1-5 surfaces preserve verbatim.

## Decision

### D300. Pillar E call-site span wiring — discovery + enrichment stages

`orchestrator/discovery_dedup.py::check_dedup` wraps its body with:

```python
with traced_stage(
    "discovery", "check_dedup",
    attributes={"source_skill": source_skill},
):
    # ... existing body ...
```

`orchestrator/tier_assignment.py::compute_tier_from_signals` wraps its body via the **inner-function pattern**:

```python
def compute_tier_from_signals(person_id, frontmatter, *, weights=None, now=None):
    with traced_stage(
        "enrichment", "compute_tier",
        attributes={"person_id": person_id},
    ):
        return _compute_tier_from_signals_inner(
            person_id, frontmatter, weights=weights, now=now,
        )
```

The inner-function pattern preserves ~50-line body indentation. The public function's signature + return shape is unchanged.

**Span attributes per ADR-0055 D304:**

| Call site | Stage | Operation | Attributes at entry | Attributes via `set_attribute` |
|---|---|---|---|---|
| `check_dedup` | `discovery` | `check_dedup` | `source_skill` (always known) | — |
| `compute_tier_from_signals` | `enrichment` | `compute_tier` | `person_id` (always known) | — |

The `source_list` field on `check_dedup` is DELIBERATELY EXCLUDED from the span attributes per the privacy invariant per I8 + ADR-0032 D148 + ADR-0050 D276(b) + ADR-0054 D297 — operators investigating per-source-list aggregates consume the ledger directly (the `discovery_dedup_hit` / `discovery_dedup_conflict` events carry `source_list` for direct ledger query but the per-event-class metric breakdown surface NEVER aggregates by it).

### D301. Pillar F call-site span wiring — research + draft + review stages

`orchestrator/draft_quality.py::score_draft` wraps its body in-line:

```python
def score_draft(draft, dossier, *, register, channel, ...):
    with traced_stage(
        "review", "score_draft",
        attributes={"register": register, "channel": channel},
    ) as _span:
        # ... existing body ...
        _span.set_attribute("result_state", state)
        return DraftQualityResult(...)
```

`orchestrator/reconcile.py::run_pass_c` wraps via the inner-function pattern (~250-line body):

```python
def run_pass_c(*, led, people_dir, apply):
    with traced_stage("review", "reconcile_pass_c"):
        return _run_pass_c_inner(
            led=led, people_dir=people_dir, apply=apply,
        )
```

The Layer 5 backstop integration per ADR-0049 D262 happens INSIDE `_run_pass_c_inner` — the per-Person Layer 5 refusal events (`reconcile_drift` with `reason="ready_without_draft_ready_event"`) flow through the per-event-class observability surface per ADR-0050 D272 + the per-Pillar-F event class consumption per ADR-0050 D277. Pillar G Week 10-11's per-Person dashboard adapters consume the Layer 5 reason via the existing `reconcile_drift.reason` ledger field; the Week 6 span emit at Pass C's wrapping boundary is the operator-visible trace surface for the per-Pass-C timing.

**Span attributes per ADR-0055 D304:**

| Call site | Stage | Operation | Attributes at entry | Attributes via `set_attribute` |
|---|---|---|---|---|
| `score_draft` | `review` | `score_draft` | `register`, `channel` (closed-enum kwargs) | `result_state` (post-compute) |
| `run_pass_c` | `review` | `reconcile_pass_c` | — | — |

The `voice_corpus.retrieve_voice_exemplars` primitive's call-site wiring at the `outreach_factory.research.voice_corpus_retrieve` span name is **DEFERRED to a future Pillar G iteration** OR consumed indirectly via the `score_draft` review-stage span (when `score_draft` triggers fuzzy-fallback per ADR-0046 D237 — the fuzzy-fallback's encoder load happens INSIDE the review-stage span's wrapping context, so operators see the encoder-load latency in the review span). The Week 6 commit ships the review-stage instrumentation; future iterations MAY extend per the operator-visibility need.

The `build_draft_ready_payload` Layer 4 emit guard's call-site wiring is **DEFERRED to a future Pillar G iteration**. The Layer 4 refusal events (`Layer4GuardRefusal` raised; no event emitted on refusal per ADR-0047 D245) flow through the per-event-class observability surface as the absence of the `draft_ready` event — operators see refusals via the per-event-class delta. Future iterations MAY wrap `build_draft_ready_payload` with a `review.build_draft_ready` span if per-call timing surface is operator-actionable.

### D302. Pillar D call-site span wiring — reply + win_loss stages

`orchestrator/reply_classifier.py::emit_classified_event` wraps its body in-line:

```python
def emit_classified_event(led, reply_event, result):
    channel = reply_event.get("channel") or "email"
    span_attrs = {
        "channel": channel,
        "category": result.category,
        "classification_method": result.classification_method,
    }
    person_id = reply_event.get("person_id")
    if person_id:
        span_attrs["person_id"] = person_id
    with traced_stage("reply", "classify", attributes=span_attrs):
        return led.append(build_classified_payload(reply_event, result))
```

`orchestrator/conversation_outcomes.py::run_conversation_outcomes_pass` wraps its body in-line:

```python
def run_conversation_outcomes_pass(*, led, apply, now=None, ttl_days=...):
    with traced_stage("win_loss", "derive_outcomes"):
        # ... existing body ...
```

**Span attributes per ADR-0055 D304:**

| Call site | Stage | Operation | Attributes at entry | Attributes via `set_attribute` |
|---|---|---|---|---|
| `emit_classified_event` | `reply` | `classify` | `channel`, `category`, `classification_method`, `person_id` (when present) | — |
| `run_conversation_outcomes_pass` | `win_loss` | `derive_outcomes` | — | — |

The per-Person outcome attributes (per-thread `outcome` + per-Person aggregated `outcome` per ADR-0030 D134) flow through the inner per-Person operations via the standard `conversation_outcome` event emission surface; the Week 6 span emit at the pass-level wrapping boundary is the operator-visible trace surface for the per-Pass-O timing.

### D303. Pillar C dispatcher call-site span wiring — send stage across five channels

The five `skills/send-outreach/scripts/send_queued.py` dispatchers wrap via the **inner-function pattern** (each ~150-200 line bodies):

```python
def gated_send_one(draft, *, gmail_client, led, ..., register="cold-pitch", ...):
    with traced_stage(
        "send", "email",
        attributes={"channel": "email", "register": register},
    ) as _span:
        return _gated_send_one_inner(
            draft, gmail_client=gmail_client, led=led, ...,
            register=register, _span=_span,
        )

def _gated_send_one_inner(draft, *, gmail_client, led, ..., _span):
    person_path = draft.person.note_path if draft.person else None
    if person_path is None:
        return _blocked(led, draft, person_id=None, reason="no_person_note")
    parsed = identity.read_person_keys(person_path)
    if parsed is None:
        return _blocked(led, draft, person_id=None, reason="not_a_person_note")
    person_id, keys = parsed
    # Stamp person_id on the span once known.
    if person_id:
        try:
            _span.set_attribute("person_id", person_id)
        except Exception:
            pass
    # ... rest of body ...
```

The five dispatchers + their per-span shapes:

| Dispatcher | Stage | Operation | Channel | Histogram channel attr (D305) |
|---|---|---|---|---|
| `gated_send_one` | `send` | `email` | `email` | `email` |
| `gated_li_invite_one` | `send` | `li_invite` | `linkedin` | `linkedin` |
| `gated_li_dm_one` | `send` | `li_dm` | `linkedin` | `linkedin` |
| `gated_tw_dm_one` | `send` | `tw_dm` | `twitter` | `twitter` |
| `gated_calendar_booking_one` | `send` | `calendar_booking` | `calendar` | (NO histogram per D306) |

The `register` attribute is passed at entry (always known via the kwarg default `"cold-pitch"` + operator-supplied override). The `person_id` attribute is stamped via `set_attribute` AFTER `identity.read_person_keys` parses the person note (the early-return paths `no_person_note` + `not_a_person_note` complete the span WITHOUT `person_id` — operators querying tracing see the early-return path's per-stage span without per-Person granularity, which matches the dispatcher's operational reality at those paths).

### D304. Span attribute privacy-invariant propagation — closed-set enforcement at every call site

Per ADR-0054 D297's `_SPAN_ATTRIBUTES_ALLOWED` closed-set, every per-call-site span attribute key MUST be one of the 12 allowed values. The Week 6 wiring's attribute selection per call site (D300 + D301 + D302 + D303) NEVER includes the five privacy-disallowed keys:

| Privacy-disallowed key | Per | Why NEVER in spans |
|---|---|---|
| `source_list` | ADR-0032 D148 | operator-private discovery list names |
| `draft_body` | ADR-0038 D182 cat 8 + I8 | operator-confidential prose content |
| `dossier_body` | ADR-0038 D182 cat 8 + I8 | operator-confidential research prose |
| `exemplar_body` | ADR-0038 D182 cat 8 + I8 | operator-confidential voice-corpus prose |
| `claim_text` | ADR-0038 D182 cat 8 + I8 | operator-confidential per-claim trace |

The per-call-site enforcement at `traced_stage`'s attribute-validation time IS the structural mitigation — a future contributor adding `attributes={"draft_body": draft}` at ANY call site triggers a `ValueError` per ADR-0054 D297. Tests pin this per call site via `TestWeek6PrivacyInvariantPropagation::test_discovery_span_has_no_privacy_attrs` + `test_review_span_has_no_privacy_attrs` (cell-level matrix coverage discipline NOW ELEVEN consecutive weeks: Pillar F W6-W12 + Pillar G W2-W5 + W6).

**Operator-deliberate bypass.** Operators using the raw OTel `Tracer.start_as_current_span` API directly + `span.set_attribute("draft_body", "...")` bypass the helper's refuse-loud. The helper IS the canonical surface; the per-week-reviewer's behavioral-passthrough-not-signature-only discipline catches direct-API bypasses at audit time. Pillar I per-tenant audit-tooling MAY surface a per-tenant span-attribute filter at OSS bring-up per ADR-0054 D297's carry-forward.

### D305. Send-latency Histogram dispatcher integration — Week 4 carry-forward completion

Per ADR-0053 D289 + §Negative — the per-channel send-latency Histogram instrument shipped at Week 4 as SHAPE-only; the dispatcher integration was deferred. Week 6 wires the integration at FOUR of the five dispatchers (calendar excluded per D306):

```python
import time
from observability import get_send_latency_histogram

# Inside _gated_send_one_inner, around the gmail_client.send_email call:
_send_start = time.monotonic()
try:
    msg_id, thread_id = gmail_client.send_email(...)
except Exception as exc:
    led.append({"type": "send_failed", ...})
    return {"ok": False, "reason": "send_failed", ...}
finally:
    try:
        get_send_latency_histogram().record(
            time.monotonic() - _send_start,
            {"channel": "email"},
        )
    except Exception:
        pass  # observability MUST NOT break dispatch
```

**Best-effort posture per the historical convention.** The `try/except Exception: pass` around the histogram record mirrors the `cost_incurred` emit's try/except-best-effort posture (line ~544 in `gated_send_one`). Observability failure (e.g., OTel SDK runtime exception; meter no-op fallback) MUST NOT break dispatch — the dispatcher's correctness contract is preserved. The histogram's no-op fallback when no meter is initialized is silently absorbed; operators wiring `init_otel_meter_provider()` at startup see the histogram populate.

**Per-channel attribute per ADR-0014 D33 + ADR-0053 D289.** Each dispatcher's histogram.record call carries the canonical per-channel value matching the per-event-class metric counter's channel attribute (email + linkedin + twitter + calendar — the four operationally distinct dispatcher channels). Operators querying the Prometheus exposition see `outreach_factory_send_latency_seconds_bucket{channel="email", le="..."}` + `..._bucket{channel="linkedin", le="..."}` + ... per the Prometheus + OTel exposition format per ADR-0053 §References.

**Elapsed-time scope: external API call only.** The histogram measures the elapsed time between the start + end of the dispatcher's external API call (gmail_client.send_email + linkedin_client.connect_with_person + linkedin_client.send_message + twitter_client.send_dm). The Phase 1 (intent append) + Phase 2 (confirmed append) ledger writes + the policy + lock + writeback operations are NOT in the histogram's scope. Operators querying the p99 SLO threshold per PILLAR-PLAN §2 Pillar G see the external API call latency cleanly isolated from the dispatcher's framework overhead.

### D306. Calendar dispatcher histogram exclusion

`gated_calendar_booking_one` does NOT wire `get_send_latency_histogram().record(...)`. The calendar dispatcher's send action is URL synthesis (per ADR-0019 D66) — no external API call at send time; the matching `calendar_booking_confirmed` event arrives LATER via the Cal.com webhook handler (`orchestrator/cal_com_webhook.py`). Three alternatives:

1. **Record at URL-synthesis time** — measures ~microseconds (the `_build_calendar_booking_url` call's CPU time). Uninformative against the 5s SLO threshold per PILLAR-PLAN §2 Pillar G.
2. **Record at webhook-handler confirmation time** — measures days-of-delay between intent + confirmation. Uninformative as a send-latency signal (the Cal.com booking is recipient-driven, not operator-driven).
3. **Skip the histogram for calendar entirely** (CHOSEN).

The calendar dispatcher's per-stage span emit (per D303) IS the operator-visible trace surface for the per-call-site timing. The asymmetric two-phase shape per ADR-0019 D66 means the matching `calendar_booking_confirmed` event flows through the per-event-class observability surface separately; operators query per-channel booking conversion rates via the per-event-class counter (`outreach_factory_events_total{event_class="calendar_booking_confirmed", channel="calendar"}`) — NOT via the send-latency Histogram.

## Alternatives considered

### D300 alternatives (Pillar E call-site span wiring)

1. **Wrap `discovery_dedup.check_dedup` via inner-function pattern (mirror D300's `compute_tier_from_signals` pattern).** Rejected — `check_dedup`'s body is ~50 lines; the in-line context-manager wrapping preserves readability without the inner-function split. The inner-function pattern is reserved for ~150+ line bodies where indenting would obscure the existing logic flow.

2. **Wrap `discovery_lineage` primitives (NOT `check_dedup`).** Rejected — the per-skill discovery lineage stamping primitives (`build_enrolled_source_skill_backfill_payload` + the CLI `_cli_backfill`) are ADMINISTRATIVE — operators invoke them manually to backfill legacy state per ADR-0036 D167. The CLI invocation is operator-deliberate + low-frequency; the per-stage span emit at the CLI invocation surface is deferred to Pillar I per-tenant audit-tooling at OSS bring-up. Per-call-site spans at the high-frequency `check_dedup` + `compute_tier_from_signals` primitives provide the operator-actionable per-discovery-skill trajectory.

3. **Wrap email_verification_cache primitives.** Rejected — email verification is a per-Person caching layer (per ADR-0034 D154-D158); the per-call latency at the cache-hit path is sub-millisecond. Per-call-site spans at the cache primitive would N-times-ify the trace volume without operator-actionable signal. Pillar G Week 10-11's per-Person dashboards consume the `email_verification_cache_hit` event class via the existing per-event-class observability surface; the per-call-site span is deferred.

4. **Wrap all 4 Pillar E primitives uniformly.** Rejected — the per-pillar trajectory at Pillar G Week 1's `.planning/REVIEW-pillar-g-surface-audit.md` §6 specifies that the per-call-site span wiring SHOULD bias toward the high-frequency operator-actionable surfaces. `check_dedup` + `compute_tier_from_signals` are the two surfaces operators query via the per-discovery-skill + per-Person trajectory dashboards at Week 10-11. The other Pillar E primitives (discovery_lineage CLI + email_verification_cache) are administrative + sub-millisecond respectively.

### D301 alternatives (Pillar F call-site span wiring)

1. **Wrap `voice_corpus.retrieve_voice_exemplars` at Week 6.** Rejected at Week 6 — voice-corpus retrieval is consumed INDIRECTLY via `draft_quality.score_draft`'s fuzzy-fallback path per ADR-0046 D237. Operators see the encoder-load latency within the `review.score_draft` span's wrapping context. Future Pillar G iterations MAY add the `research.voice_corpus_retrieve` span if operators want per-retrieval timing isolated from per-draft-scoring timing — the trajectory is documented inline at D301.

2. **Wrap `build_draft_ready_payload` (Layer 4 emit guard) at Week 6.** Rejected at Week 6 — the Layer 4 refusal IS structural (raises `Layer4GuardRefusal` per ADR-0047 D245); no event emits on refusal. Operators see refusals via the absence of the `draft_ready` event in the per-event-class observability surface. Future Pillar G iterations MAY add the `review.build_draft_ready` span if per-call timing surface is operator-actionable.

3. **Wrap each per-Layer 2-3 sub-primitive (`parse_draft_for_claims`, `_find_citation_anchor`, `_find_citation_anchor_fuzzy`).** Rejected — sub-primitive granularity N-times-ifies the trace volume per draft (`score_draft` calls `parse_draft_for_claims` which calls per-claim `_find_citation_anchor` which calls `_find_citation_anchor_fuzzy` on the fuzzy-fallback path). The per-draft `review.score_draft` span carries the aggregate timing; per-claim sub-spans would explode the per-draft trace size from 1 span to ~5-15 spans. Operators investigating per-draft hallucination detection patterns consume the existing `hallucination_detected` event class via the per-event-class observability surface (per ADR-0043 D219); the per-draft span is the per-call-site granularity at Week 6.

### D302 alternatives (Pillar D call-site span wiring)

1. **Wrap `RuleBasedClassifier.classify` (the per-message classifier method) instead of `emit_classified_event` (the ledger-emit factory).** Rejected — the classifier method is invoked once per reply event; the emit factory is the ledger-writing surface that operators consume via the per-event-class observability primitive. The wrapping at the emit factory ensures the span covers BOTH the classify call AND the ledger append; the per-stage span semantics matches the per-event-class metric emit's grain.

2. **Wrap each Pass G/H/I/J reconcile pass (per the four channel reply detection passes per ADR-0027 + ADR-0028).** Rejected — the per-pass reconcile invocations are administrative (operator runs `python orchestrator/reconcile.py` periodically). The per-pass span at the pass invocation surface is deferred to Pillar I per-tenant audit-tooling at OSS bring-up. The per-Reply `emit_classified_event` IS the high-frequency operator-actionable surface that flows into the per-Person trajectory dashboards at Week 10-11.

3. **Wrap `compute_conversation_outcomes` (the per-Person outcome computation) instead of `run_conversation_outcomes_pass` (the pass-runner factory).** Rejected — the per-Person computation is a sub-call of the pass-runner; wrapping the runner ensures the span covers both the computation + the per-Person ledger appends. The pass-runner IS the operator-deliberate invocation surface (per the Pillar D Week 11 conversation-outcomes shipping).

### D303 alternatives (Pillar C dispatcher call-site span wiring)

1. **Wrap per-Phase (Phase 1 + Phase 2 + writeback) sub-spans.** Rejected — sub-phase granularity N-times-ifies the trace volume per dispatch (~3-4 sub-spans per send). The per-dispatcher `send.<channel>` span carries the aggregate two-phase commit timing; operators investigating per-phase delays consume the existing per-event-class observability surface (`send_intent` vs `send_confirmed` timing delta via the per-event-class metric snapshot's `oldest_ts` + `newest_ts` per ADR-0050 D272). Future Pillar G iterations MAY add per-phase sub-spans if operators want per-phase isolation at the trace surface.

2. **Wrap at the lock-acquisition boundary (after the per-person lock is held).** Rejected — the span emit MUST cover the EARLY-RETURN paths (`no_person_note`, `not_a_person_note`, `identity_incomplete`, `already_sent`, `policy_blocked`, etc.). Wrapping at the lock-acquisition boundary would lose visibility on the gate-refusal paths — operators investigating gate-refusal patterns via the tracing backend would see NO span for refused dispatches. The function-entry wrapping ensures every dispatch invocation produces a span regardless of outcome.

3. **Use a decorator instead of context manager.** Rejected — the dispatcher's body needs to call `_span.set_attribute("person_id", person_id)` AFTER `identity.read_person_keys` parses the note. A decorator would not expose the `_span` reference to the wrapped function's body. The context-manager + inner-function pattern preserves the per-call-site attribute-stamping convention per ADR-0054 D296.

### D304 alternatives (privacy invariant propagation)

1. **Audit attribute keys via a CI lint instead of helper-time refuse-loud.** Rejected — the helper-time refuse-loud per ADR-0054 D297 IS the structural mitigation that survives operator-side wiring drift. A CI lint would catch the FRAMEWORK's call sites but NOT operator-side `traced_stage` invocations. The closed-set + helper-time validation is the layered defense.

2. **Add per-call-site attribute-allowlist sub-sets (e.g., a `discovery.check_dedup` MAY only carry `source_skill`; a `send.email` MAY only carry `channel` + `person_id` + `register`).** Rejected — over-restricts the per-call-site flexibility. The `_SPAN_ATTRIBUTES_ALLOWED` super-set covers ALL allowed attributes; per-call-site sub-sets would N-times-ify the closed-set surface. Operators wanting per-call-site attribute audits consume the per-call-site behavioral tests per the cell-level matrix coverage discipline.

3. **Sample span attributes at OTel SDK exporter time (Honeycomb / Datadog / Grafana Cloud have per-tenant attribute filters).** Accepted as a forward-reference for Pillar I OSS bring-up. The framework default at Week 6 ships the closed-set refuse-loud at helper time; operators wanting per-tenant attribute filters wire their backend's filter at the operator-side configuration (per ADR-0054 D298's framework-neutrality contract).

### D305 alternatives (send-latency Histogram dispatcher integration)

1. **Record histogram OUTSIDE the per-channel try/except.** Rejected — observability failure MUST NOT break the dispatch contract. The `try/except: pass` around the `histogram.record()` call mirrors the existing `cost_incurred` emit's best-effort posture in the same dispatchers; the pattern preserves dispatch correctness.

2. **Record histogram in a `finally` clause at a wider scope (around the entire `_gated_*_one_inner` body).** Rejected — the histogram measures the EXTERNAL API call latency, NOT the dispatcher framework's total time. Wider scope would conflate gate timing + lock timing + writeback timing + API call timing into one metric; operators querying the p99 SLO threshold per PILLAR-PLAN §2 Pillar G need the API call latency isolated.

3. **Record per-event histogram values via callback at the per-event ledger emit (similar to the per-event-class ObservableCounter callback).** Rejected — the Histogram is a SYNCHRONOUS instrument per ADR-0053 D289 (OTel Python SDK 1.38 has no `ObservableHistogram`). Operators MUST call `.record()` at the per-event boundary; the per-event callback pattern doesn't apply.

### D306 alternatives (calendar dispatcher histogram exclusion)

1. **Record histogram at URL-synthesis time for calendar.** Rejected — measures ~microseconds (uninformative against the 5s SLO threshold per PILLAR-PLAN §2 Pillar G).

2. **Record histogram at webhook-handler confirmation time for calendar.** Rejected — measures days-of-delay between intent + confirmation (uninformative as a send-latency signal; the booking is recipient-driven, not operator-driven).

3. **Introduce a separate `outreach_factory_booking_conversion_seconds` Histogram for calendar.** Rejected at Week 6 — Pillar G Week 9-11 may introduce a per-channel conversion timing instrument as part of the cost dashboard + per-Person trajectory work; the Week 6 commit keeps the existing send-latency Histogram's semantic clean (external API call latency).

## Consequences

### Positive

- **The framework's per-stage span trace surface is now operationally complete at Week 6** — operators wiring `init_otel_tracer_provider(span_processors=[BatchSpanProcessor(operator_exporter)])` at startup see per-stage traces flow through the eight pipeline stages (discovery → enrichment → research → draft → review → send → reply → win_loss) at the per-pillar Python call sites.
- **The Week 4 carry-forward for the send-latency Histogram dispatcher integration is COMPLETE** — operators consuming the Prometheus exposition see `outreach_factory_send_latency_seconds` populate with per-channel timing data; the p99 SLO threshold per PILLAR-PLAN §2 Pillar G is operator-queryable via `histogram_quantile(0.99, sum(rate(outreach_factory_send_latency_seconds_bucket[5m])) by (le, channel))`.
- **The per-pillar-symmetry contract holds at the canonical scope `orchestrator.observability` + version `0.1.0`** — every Pillar G instrument (metric + trace) shares the scope; operators see one namespace.
- **The closed-set discipline per `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` IS the regression-barrier per the R031-shape mitigation pattern** extended to the per-call-site span surface — a future contributor adding a span for an unrecognized stage OR a privacy-relevant attribute triggers per-call refuse-loud at `traced_stage`.
- **The privacy invariant per I8 + ADR-0032 D148 + ADR-0038 D182 category 8 + ADR-0050 D276(b) + ADR-0054 D297 flows through to per-call-site span attributes** — every call site's attribute dict respects the closed-set; tests pin per call site per the cell-level matrix coverage discipline.
- **The legacy-state-vs-new-defense-layer tension discipline holds at SIX consecutive weeks (Pillar F W12 + Pillar G W2-W6)** — Week 6 per-call-site wiring preserves the existing Pillar A-F primitive surfaces verbatim; the Pillar D + E + F binding exit-criterion tests STAY GREEN; the FIVE-layer hallucination defense closes verbatim at Layer 5 per ADR-0049 D262.
- **The behavioral-passthrough-not-signature-only discipline holds at EIGHT consecutive weeks (Pillar F W8-W11 + Pillar G W3-W6)** — Week 6 tests capture spans via `InMemorySpanExporter` + verify per-call-site span name + attributes + parent-child relationships (NOT signature-only).
- **The cell-level matrix coverage discipline holds at ELEVEN consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6)** — Week 6 ships 21 new tests covering per-Pillar-call-site cells + per-dispatcher span cells + per-privacy-invariant cells + per-histogram cells + per-legacy-state-no-impact cells.
- **ZERO new R-risks** at Week 6 — the existing R031/R033/R034/R035/R036 mitigations carry through verbatim; the test fixture `monkeypatch.setattr(observability, "get_tracer", ...)` + `monkeypatch.setattr(observability, "get_meter", ...)` preserves test isolation without OTel's set-once enforcement.

### Negative

- **The per-call-site wiring at 13 call sites grows the framework's surface area** — operators inspecting the per-pillar modules see `with traced_stage(...)` context managers at the public function entry points; the inner-function pattern adds `_<name>_inner` private functions for the 7 dispatchers + reconcile.run_pass_c + compute_tier_from_signals. Mitigation: the existing public function signatures are PRESERVED verbatim; operators consuming the primitives via the public surface see identical behavior.
- **The send-latency Histogram dispatcher integration adds per-dispatch overhead (~microseconds per `time.monotonic()` call + `histogram.record()` call)** — the overhead is sub-microsecond when no meter is initialized (NoOpHistogram); ~tens of microseconds when meter is initialized + the histogram aggregation runs. Mitigation: the best-effort posture absorbs failures; the per-dispatch overhead is dwarfed by the external API call latency (10ms-5s typical).
- **The calendar dispatcher's histogram exclusion creates an asymmetry across the five send-channel dispatchers** — operators querying `outreach_factory_send_latency_seconds{channel="calendar"}` see no data. Mitigation: D306 documents the exclusion + the trajectory at Pillar G Week 9-11 may introduce a separate booking conversion timing instrument.
- **The test surface grows by ~21 tests** — `tests/test_observability.py` ships 21 NEW tests covering the per-call-site behavioral pins + privacy invariant propagation + legacy-state-no-impact verification; file size grows from ~3349 LOC to ~4100+ LOC, still below the ~7500 LOC split threshold.

### Neutral

- **The OTel scope version stays at `0.1.0`** per ADR-0052 D283 + ADR-0054 D295 — the Week 6 per-call-site wiring is content-additive (new spans under the same scope); operators consuming the OTLP / Prometheus export see the scope version unchanged.
- **No new pip dependencies at Week 6** — the OTel SDK's tracing + metric surfaces are in `opentelemetry-sdk>=1.38` pinned at Week 3.
- **No ledger schema migration** — Week 6 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED from Pillar G Week 1 + 2 + 3 + 4 + 5).
- **No new event classes** — Week 6 ships ZERO new event classes; spans go via OTel SDK, NOT via `Ledger.append`.
- **No new operator-facing CLI surfaces** — Week 6 does NOT extend `orchestrator/funnel.py` or any other CLI; the per-stage span surface flows through the OTel SDK to operator-chosen backends.

## Compliance with invariants

- **I1 (Privacy by default — ledger is SoT).** Compliant — Week 6 per-call-site spans do NOT touch the ledger surface; spans go via OTel SDK. The Prometheus exposition is a denormalized rebuildable view per `docs/SOURCES-OF-TRUTH.md`.
- **I2 (Atomicity contract).** Compliant — the per-call-site span emit is read-only at the helper level; `traced_stage` does NOT mutate the ledger. The dispatcher's two-phase commit semantics per ADR-0014 D33 are preserved verbatim.
- **I3 (Single source of truth).** Compliant — every span emit re-derives from the per-call context; no state cached at the call-site level.
- **I4 (Determinism).** Compliant — the per-call-site span emit does NOT depend on wall-clock; span timestamps are managed by the OTel SDK per ADR-0054 D296's deterministic-clock carry-forward.
- **I5 (Refuse loud).** Compliant — `_PIPELINE_STAGES` + `_SPAN_ATTRIBUTES_ALLOWED` refuse-loud at the helper's attribute validation time per ADR-0054 D296 + D297.
- **I6 (No silent state).** Compliant — every state change (span emit) is observable on the operator's tracing backend.
- **I7 (Refuse loud on broken pipelines).** Compliant per the same refuse-loud posture at the helper. The dispatcher's existing refuse-loud posture on gate-refusal paths (`no_person_note`, `policy_blocked`, etc.) is preserved verbatim; spans are emitted on refuse paths too (the wrapping at function entry ensures every invocation produces a span).
- **I8 (Privacy invariant — operator-confidential fields).** Compliant per D304 — `_SPAN_ATTRIBUTES_ALLOWED` refuse-loud is operationally LIVE at every per-call-site invocation.
- **The channel-on-every-event invariant per ADR-0014 D33** — Compliant per D303 + D305 — every dispatcher's per-channel span attribute + every dispatcher's histogram.record's per-channel attribute carry the channel uniformly.
- **The brand-and-legal-liability invariant per ADR-0025 D97** — Unaffected — Pillar G Week 6 does not interact with the brand/legal surface.
- **The FIVE-layer hallucination-detection defense per ADR-0038 D180 + ADR-0049 D262** — Unaffected at structural level — Pillar G Week 6 does not extend any of the five layers; Layer 5 backstop preserved verbatim at `_run_pass_c_inner` which Week 6 wraps via the `review.reconcile_pass_c` span.

## Downstream pillar impact

- **Pillar G Week 7-8** (SLO violation detector + `slo_violation_detected` event class emit + Slack webhook wiring) — the per-stage span surface IS the seam Weeks 7-8 builds on. The SLO check's per-window aggregation reuses `collect_event_class_snapshots`; the Slack webhook dispatch wraps in `traced_stage("send", "slack_webhook", ...)` for operator-visible tracing.
- **Pillar G Week 9** (cost dashboard) — extends the per-stage span surface with per-source cost spans (the per-source breakdown surfaces as the `source_skill` span attribute, already in `_SPAN_ATTRIBUTES_ALLOWED`).
- **Pillar G Week 10-11** (per-Person observability surface) — the per-Person dashboard adapters CONSUME the per-stage span surface via the tracing backend's per-Person filter (`person_id` is in `_SPAN_ATTRIBUTES_ALLOWED`); operators query per-Person trajectories via the tracing UI's per-Person filter. The Layer 5 backstop's per-Person `reconcile_drift.reason: ready_without_draft_ready_event` flows through `review.reconcile_pass_c` span's parent-child context to the per-Person `reconcile_drift` event emit.
- **Pillar G Week 12** (binding exit-criterion test un-skip + Pillar G Stable flip) — composes the per-stage tracing surface + the SLO alerting + the per-Person dashboards + the per-channel send-latency histogram + the cost dashboard into the one-CLI-invocation binding scenario per ADR-0050 D275 + PILLAR-PLAN §2 Pillar G's binding text.
- **Pillar H (daemon + scale)** — the per-process TracerProvider's set-once enforcement (R035 EXTENDED to tracing per ADR-0054 D294) creates per-process state; multi-process daemons may need per-daemon-process TracerProvider isolation. The framework-neutrality contract per ADR-0054 D298 is preserved at multi-machine scale. The per-call-site span emit at Week 6 is per-process via OTel's TracerProvider; multi-process scaling may surface per-daemon-process span aggregation as a NEW concern.
- **Pillar I (OSS bring-up + multi-tenant)** — per-tenant audit-tooling extends `Resource` with per-tenant labels (already content-additive per ADR-0052 D287); per-tenant `SpanProcessor` configuration follows the framework-neutrality contract per ADR-0054 D298. Per-tenant span-attribute filters MAY surface here (e.g., per-tenant `_SPAN_ATTRIBUTES_ALLOWED` extensions for operator-confidential per-tenant labels).
- **Pillar J (GDPR purge)** — the per-Person span attribute `person_id` (Week 6's per-call-site spans + Week 10-11's per-Person dashboard surfaces) extends Pillar J's per-Person purge transaction to per-Person spans. The tracing backend (operator-chosen) retains spans for its own retention period; Pillar J's per-Person purge transaction extends to the tracing backend via per-Person filter on `person_id` attribute (the operator's tracing backend's per-Person filter API surface).

## Migration / rollout

- **Operator-side action required at Week 6 upgrade:** **NONE — content-additive.** The Week 6 commit adds `with traced_stage(...)` context managers at the per-pillar Python call sites + `histogram.record(...)` calls at the four dispatcher external-API boundaries; existing primitive signatures + return shapes are PRESERVED verbatim. Operators upgrading from Week 5 to Week 6 see identical behavior — the per-call-site span emit is no-op at the OTel SDK level when no provider is initialized (the helper inherits OTel SDK's safe-default `NoOpTracer` per ADR-0054 D296); the histogram record is no-op when no meter is initialized (NoOpHistogram).
- **Recommended (optional):** operators wanting per-stage tracing + send-latency histogram at Week 6:
  ```python
  from observability import (
      init_otel_meter_provider, init_otel_tracer_provider,
      init_prometheus_metric_reader,
      register_event_class_observable_counter,
      register_reconcile_success_ratio_gauge,
      start_prometheus_http_server,
  )
  from opentelemetry.sdk.trace.export import BatchSpanProcessor
  from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

  # Metrics + Prometheus exposition (Week 3 + 4).
  reader = init_prometheus_metric_reader()
  init_otel_meter_provider(metric_readers=[reader])
  register_event_class_observable_counter(led, since_window=timedelta(days=30))
  register_reconcile_success_ratio_gauge(led, since_window=timedelta(days=30))
  start_prometheus_http_server(port=8000)

  # Traces (Week 5 + 6).
  exporter = OTLPSpanExporter(endpoint="https://api.honeycomb.io/v1/traces")
  init_otel_tracer_provider(
      span_processors=[BatchSpanProcessor(exporter)],
  )

  # Now invoke the per-pillar primitives — spans emit automatically
  # + histogram records automatically at the dispatcher.
  ```
- **Operators with OTLP backends** install their backend's OTLP exporter package separately (`pip install opentelemetry-exporter-otlp-proto-http` for HTTP OTLP; or vendor-specific package for Honeycomb / Datadog / Grafana Cloud) — the framework does NOT ship the OTLP exporter import.
- **No ledger schema migration** — Week 6 ships ZERO new ledger migrations; pending count stays at 19 (UNCHANGED).
- **No new event classes** — Week 6 ships ZERO new event classes.
- **No new pip dependencies** — Week 6 uses the three OTel packages pinned at Week 3.
- **OTel set-once caveat for tests:** tests use `monkeypatch.setattr(observability, "get_tracer", ...)` + `monkeypatch.setattr(observability, "get_meter", ...)` patterns to install per-test InMemorySpanExporter + InMemoryMetricReader without OTel's set-once enforcement on the global state.

## Existing-operator seed

Operator action required at Week 6: **NONE — content-additive.**

Recommended (optional): operators wanting per-stage tracing + send-latency histogram at Week 6 invoke the canonical wiring per the Migration section above. Operators waiting for the framework-side SLO violation detector + Slack webhook see it land at Pillar G Week 7-8.

## References

- **ADR-0054** (Pillar G Week 5 — OTel tracing initialization + canonical Tracer scope + per-stage `traced_stage` context manager + `_PIPELINE_STAGES` closed-set + privacy invariant on span attributes via `_SPAN_ATTRIBUTES_ALLOWED` + framework-neutrality contract for tracing + zero call-site wiring at Week 5). D294-D299. Week 5 explicitly deferred the per-call-site wiring to Week 6 via D299.
- **ADR-0053** (Pillar G Week 4 — Prometheus exporter wiring, per-channel send-latency Histogram, reconcile success ratio ObservableGauge, Prometheus HTTP exposition server, framework-default View set, first Grafana-as-code dashboard). D288-D293. Week 4 explicitly deferred the dispatcher integration for the send-latency Histogram via §Negative.
- **ADR-0052** (Pillar G Week 3 — OTel SDK initialization + single canonical Meter scope + per-event-class ObservableCounter + cumulative-counter semantics + framework-neutrality contract + default Resource-attribute closed-set). D282-D287.
- **ADR-0051** (Pillar G Week 2 — `collect_event_class_snapshots` body + `observability_class_uncatalogued` diagnostic emit + ts-missing refuse-loud + deterministic ordering + channel-on-every-event invariant verification). D278-D281.
- **ADR-0050** (Pillar G Week 1 foundation — per-event-class observability primitive shape, OTel SDK framework decision, cross-pillar surface audit, exit-criterion vehicle scope, one-CLI-invocation invariant, per-Person observability surface). D272-D277. The Week 1 framework decision pinned OpenTelemetry SDK + Prometheus exporter + Grafana-as-code; D273's per-week trajectory table names Week 6 as the per-call-site wiring + dispatcher integration application week.
- **ADR-0049** (Pillar F Week 12 — Layer 5 reconcile heal-pass refusal + binding exit-criterion test un-skip + Pillar F Stable flip). D262-D271. The Layer 5 backstop preserves verbatim under Week 6's `review.reconcile_pass_c` span wrapping.
- **ADR-0038** (Pillar F foundation). D180 (FIVE-layer hallucination-detection defense); D182 category 8 (privacy invariant for operator-confidential fields).
- **ADR-0037** (Pillar E Week 12 close + Stable flip). D172 (Pillar E Stable flip discipline; ~7500 LOC split threshold flag for the cross-pillar coherence test vehicle).
- **ADR-0035** (Pillar E Week 6-8 — tier auto-assignment primitive). D161-D162 (per-Person tier-derivation surface; consumed by `compute_tier_from_signals` Week 6 span wrapping).
- **ADR-0034** (Pillar E Week 1 — discovery dedup primitive + deterministic-clock contract). D154-D158 (per-Person discovery dedup; consumed by `check_dedup` Week 6 span wrapping).
- **ADR-0031** (Pillar D Week 12 — funnel CLI). D140 (deterministic-output contract — byte-identical across consecutive invocations against a fixed ledger state).
- **ADR-0030** (Pillar D Week 9-11 — conversation outcomes + per-Person outcome aggregation). D131-D134 (per-Pass-O outcome derivation; consumed by `run_conversation_outcomes_pass` Week 6 span wrapping).
- **ADR-0027** (Pillar D Week 4-5 — per-channel reply detection passes G/H/I/J). D109-D112 (per-channel reply classification; consumed by `emit_classified_event` Week 6 span wrapping).
- **ADR-0019** (Pillar C Week 6 — Calendar booking dispatcher). D65-D69 (asymmetric two-phase shape; URL-synthesis-not-API-call; no per-channel send-latency Histogram per D306).
- **ADR-0018** (Pillar C Week 5 — Twitter DM dispatcher). D58-D60 (per-channel two-phase commit; consumed by `gated_tw_dm_one` Week 6 span wrapping + histogram integration).
- **ADR-0016** (Pillar C Week 3 — LinkedIn DM dispatcher). D43-D44 (per-channel two-phase commit; consumed by `gated_li_dm_one` Week 6 span wrapping + histogram integration).
- **ADR-0015** (Pillar C Week 2 — LinkedIn invite dispatcher). D39-D40 (per-channel two-phase commit; consumed by `gated_li_invite_one` Week 6 span wrapping + histogram integration).
- **ADR-0014** (Pillar C foundation). D33 (channel-on-every-event invariant).
- **ADR-0010** (Phase 5.5 ledger schema + event factory + audit-marker discipline). D17 (per-event factory + `_recovered_by` / `_emitted_by` audit markers).
- `.planning/REVIEW-pillar-g-surface-audit.md` — cross-pillar surface audit (Pillar G Week 1 baseline + Week 2 §18 + Week 3 §19 + Week 4 §20 + Week 5 §21 + Week 6 §22 extension per this commit).
- `.planning/HANDOFF-pillar-g-week-5.md` — Pillar G Week 5 close summary + Pillar G Week 6 trajectory breadcrumb.
- `docs/PILLAR-PLAN.md` §2 Pillar G + §6 Pillar G row Week 6 close summary.
- `docs/RISK-REGISTER.md` R031 + R032 + R033 + R034 + R035 + R036 (no new R-rows at Week 6).
- `docs/SOURCES-OF-TRUTH.md` — observability snapshots row extended with Week 6 ADR-0055 references.
- `orchestrator/discovery_dedup.py` — extended Week 6 with `traced_stage("discovery", "check_dedup", ...)` body wrap.
- `orchestrator/tier_assignment.py` — extended Week 6 with `traced_stage("enrichment", "compute_tier", ...)` + inner function `_compute_tier_from_signals_inner`.
- `orchestrator/draft_quality.py` — extended Week 6 with `traced_stage("review", "score_draft", ...)` body wrap + per-result `set_attribute("result_state", state)`.
- `orchestrator/reconcile.py` — extended Week 6 with `traced_stage("review", "reconcile_pass_c")` + inner function `_run_pass_c_inner`.
- `orchestrator/reply_classifier.py` — extended Week 6 with `traced_stage("reply", "classify", ...)` body wrap.
- `orchestrator/conversation_outcomes.py` — extended Week 6 with `traced_stage("win_loss", "derive_outcomes")` body wrap.
- `skills/send-outreach/scripts/send_queued.py` — extended Week 6 with `traced_stage("send", "<channel>", ...)` wraps + inner functions `_gated_*_one_inner` × 5 + `histogram.record(elapsed, {"channel": ...})` at the per-channel external-API boundaries × 4 (calendar excluded per D306).
- `tests/test_observability.py` (extended Week 6) — 21 NEW tests covering the cell-level matrix per the per-week-reviewer discipline NOW ELEVEN consecutive weeks (Pillar F W6-W12 + Pillar G W2-W6).
