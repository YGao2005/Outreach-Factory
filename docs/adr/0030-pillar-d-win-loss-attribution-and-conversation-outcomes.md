# ADR-0030: Pillar D Week 9-11 — win/loss attribution + conversation_outcome event class + TTL-based dormant transitions

- **Status:** Accepted
- **Date:** 2026-05-23
- **Pillar:** D (Reply + conversation handling — Week 9-11)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0025 (Pillar D Week 1 foundation) pinned the per-channel reply event-type naming (D96), the classifier output convention as a separate `reply_classified` event class (D97), the conversation state shape (D98), the cross-pillar surface audit (D99), the auto-unsubscribe enforcement contract (D100), and the exit-criterion vehicle scope (D101). ADR-0026 (Pillar D Week 2) shipped the rule-based classifier (D102-D107). ADR-0027 (Pillar D Week 3) shipped long-tail classifier categories + per-channel reply detection (D108-D114). ADR-0028 (Pillar D Week 4-5) shipped the auto-unsubscribe handler + the conversation state machine (D115-D121). ADR-0029 (Pillar D Week 6-8) shipped the LLM fallback for long-tail categories + the classifier-cap policy migration (D122-D128). Week 9-11 ships the LAST coordinated extension before the exit-criterion close: **win/loss attribution + the `conversation_outcome` event class + TTL-based `* → dormant` transitions.**

**Pillar D Week 9-11 is the outcome-derivation commit.** The handoff (`.planning/HANDOFF-pillar-d-week-9.md` — committed in the Week 6-8 follow-up) scopes Week 9-11 to three coordinated extensions of Pillar D's substrate:

1. **Win/loss attribution derivation** — a new surface that walks the canonical conversation-state machine's terminal states + the dispatcher's send history + maps each per-thread conversation to a binary win/loss outcome (with attribution to the touch that drove the conversion). The attribution feeds Pillar G's funnel dashboards.

2. **`conversation_outcome` event class** — the canonical record of "this conversation thread ended with X outcome at time T attributed to touch Y." Per-thread event class (analog of `conversation_state_changed` from Week 4-5). Emitted by the new Pass O on every terminal-state thread.

3. **TTL-based `* → dormant` transitions** per ADR-0028 §Negative consequences's deferral. A conversation thread in `replied` / `classified` / `active` state for more than `--conversation-ttl-days` days (operator-tunable; default 30) transitions to `dormant` automatically via Pass N's TTL driver extension.

The seven concerns this ADR resolves:

1. **Module placement for the outcome derivation logic.** Three plausible homes: (a) standalone `orchestrator/conversation_outcomes.py` (sibling of `conversation_state.py` + `auto_unsubscribe.py`); (b) extension of `orchestrator/conversation_state.py`; (c) subpackage `orchestrator/reply_handlers/`. D129 picks (a).

2. **Event shape + idempotence key for `conversation_outcome`.** ADR-0025 D98 named the conversation-state-changed shape but win/loss attribution has different requirements (`attributed_touch_intent_id`, distinct triggering-event class). D130 pins.

3. **Attribution algorithm.** Three plausible models: (a) last-touch wins (most-recent same-channel `*_confirmed`); (b) first-touch wins; (c) decay-weighted multi-touch. D131 picks (a) for v1.

4. **TTL window default + configuration surface.** Three options: (a) 30 days; (b) 60 days; (c) operator-required (no default). D132 picks (a) with CLI flag override.

5. **Pass placement.** ADR-0028 D120's design-decision-menu pattern continues — either extend Pass N OR ship a new Pass O. D133 picks "extend Pass N for TTL + new Pass O for outcome computation" (separation of concerns).

6. **Per-Person aggregation logic.** ADR-0028 D119 pinned the per-Person `conversation_status:` aggregation; Week 9-11 ships the per-Person `derived_conversation_outcome` analog with a NEW outcome-priority ordering. D134 pins.

7. **Cross-pillar audit row extension (per ADR-0025 D99).** Week 9-11 ships ONE new event class (`conversation_outcome`) + ONE new emit-shape extension to existing `conversation_state_changed` events (TTL driver field). D135 names the audit extension.

Risks this ADR mitigates by design: **R012 (LLM hallucinates unsubscribe)** continues mitigated — the THREE-layer carry-forward from ADR-0029 D123 STAYS WITH FULL WEIGHT; Pass O reads the canonical conversation-state machine's terminal states which propagate the `classification_method == "rule"` invariant transitively. **R015 (asymmetric-crash inconsistency between YAML + ledger)** continues mitigated per ADR-0028 D116; Pass O does NOT write outside the ledger (no new asymmetric-crash surface). **R016 (LLM cost runaway)** continues mitigated per ADR-0029 D127.

A new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`: **R017 (TTL-driven dormancy of active threads — false-positive abandonment of engaged conversations)**. A thread in `active` state (interest classification, no booking yet) past TTL transitions to dormant — but the operator may still be in the middle of an active back-and-forth that the framework hasn't observed (operator's pipeline may have moved the conversation offline). Mitigations: (i) the TTL is operator-tunable + 0-disables; (ii) operators with long sales cycles tune up via `--conversation-ttl-days`; (iii) per-channel TTL refinement deferred to Pillar I CLI extension if operator demand materializes.

## Decision

### D129. Outcome derivation module placement — `orchestrator/conversation_outcomes.py`

The outcome derivation logic ships as a single top-level module under `orchestrator/`, sibling of `conversation_state.py` (per ADR-0028 D118's precedent):

```
orchestrator/
├── reply_classifier.py          ← Pillar D Week 2-3 (ADR-0026, ADR-0027)
├── reply_classifier_llm.py      ← Pillar D Week 6-8 (ADR-0029)
├── auto_unsubscribe.py          ← Pillar D Week 4-5 (ADR-0028)
├── conversation_state.py        ← Pillar D Week 4-5 (ADR-0028) + Week 9-11 TTL extension (this ADR)
├── conversation_outcomes.py     ← Pillar D Week 9-11 (this ADR)
├── policy/                      ← Pillar A (policy rule classes — UNCHANGED)
├── migrations/                  ← Pillar B (migration framework — UNCHANGED Week 9-11)
├── ledger.py
├── reconcile.py                 ← extended with Pass O (D133); Pass N TTL kwargs (D132)
└── ...
```

**Why standalone (rejected: inline in conversation_state.py).** The outcome derivation logic is non-trivial:

* It depends on the conversation_state machine's terminal states (consumes `compute_thread_states`).
* It depends on the dispatcher's send history (consumes `*_confirmed` events from Pillar B + C).
* It optionally consumes `calendar_booking_confirmed` events for closed_won detection (per D131).
* It maintains its own `OUTCOMES` + `OUTCOME_PRIORITY` constant surface (per D134).

A sibling module keeps `conversation_state.py` focused on the state-transition primitive. Pillar G dashboards + Pillar I CLI extensions import this module directly without dragging in the classifier / handler / state-machine concerns.

**The OUTCOMES surface is operator-readable separately.** A future Pillar I CLI surface `python -m orchestrator.conversation_outcomes report --since 30d` (TBD) consumes the module standalone for the per-Person outcome breakdown — without invoking the full reconcile chain.

**Sharing helpers with conversation_state.** Both modules use `ThreadKey` + `ThreadState` (the canonical thread-state primitives). `conversation_outcomes.py` imports from `conversation_state` rather than duplicating. The closed-set of canonical channel names (`_CHANNELS`) is duplicated (small + close-to-callsite); a future Pillar I refactor MAY extract to a shared `orchestrator/per_channel.py` constants module if more consumers materialize.

**Pin:** `tests/test_conversation_outcomes.py::TestPublicSymbolSurface::test_public_api_present` enumerates the module's public symbols.

### D130. `conversation_outcome` event shape + idempotence key

Per-thread event class (analog of `conversation_state_changed` from ADR-0025 D98). Emitted by Pass O for every terminal-state thread.

```python
{
    "type": "conversation_outcome",
    "person_id": "<pid>",
    "channel": "email | linkedin | twitter | calendar",
    "thread_key": "<gmail_thread_id | linkedin_thread_id |
                   linkedin_invitation_id | twitter_thread_id |
                   calendar_booking_intent_id>",
    "outcome": "closed_won | closed_lost | closed_unsubscribed | dormant",
    "attributed_touch_intent_id": "<intent_id of winning/losing touch | None>",
    "triggering_event_id": {
        "type": "<event type that drove the outcome>",
        "channel": "<channel>",
        "ts": "<event ts>",
        # type-specific correlator(s) — best-effort:
        # for suppression_added: "reply_message_id"
        # for reply_classified: "reply_message_id"
        # for conversation_state_changed (TTL-driven): "driver": "ttl"
        # for calendar_booking_confirmed: "intent_id"
    },
    "ts": "<emit ts>",
    "_emitted_by": "conversation_outcomes",
}
```

**Idempotence key:** `(person_id, channel, thread_key, outcome)`. Re-running Pass O against the same ledger emits NO new events for outcomes already pinned. A thread that subsequently UPGRADES (e.g., active becomes closed_won after a booking) emits a SECOND outcome event under the new (pid, ch, tk, "closed_won") tuple — distinct from any prior tuple. Today, only `closed_won` upgrade-pathway exists (the other terminal states are absorbing); future ADRs may extend.

**Why a separate event class (rejected: annotation on `conversation_state_changed`).** The outcome carries semantics distinct from the state transition:

* **Attribution** — `attributed_touch_intent_id` correlates back to the dispatcher's send history. The state-changed event carries the trigger that drove the TRANSITION; the outcome event carries the trigger PLUS the attributed touch. Conflating fields in one event class obscures the per-event semantic intent.
* **Idempotence keying differs.** State transitions key on `(pid, ch, tk, to_state)` — one event per state-DESTINATION. Outcomes key on `(pid, ch, tk, outcome)` — one event per terminal outcome. A single state transition can drive multiple outcomes over time (e.g., a thread transitions to active, then closed_won lands later when a booking fires).
* **Downstream consumers differ.** State-changed events feed Pass C's `conversation_status:` heal + Pillar G's transition-funnel dashboards. Outcome events feed Pillar G's win/loss attribution funnel + Pillar I CLI outcome-report surfaces. Separation lets each consumer's query stay focused.

**Channel-on-every-event invariant per ADR-0014 D33 + ADR-0025 D96 + ADR-0030 D135 carry-forward.** Every emit carries `channel: <value>`. The thread's channel IS the outcome's channel (per the per-thread substrate).

**Pin:** `tests/test_conversation_outcomes.py::TestConversationOutcomeEventShape::*` (every required field) + `::TestRunOutcomesPass::test_idempotent_under_rerun` (idempotence key) + `tests/test_multi_channel_coherence.py::TestWinLossAttribution::test_conversation_outcome_is_separate_event_not_annotation` (cross-pillar coherence pin).

### D131. Attribution algorithm — last-touch-wins per-channel

The winning/losing touch is the **most-recent `*_confirmed` event on the SAME channel as the thread, for the same person, before the outcome-driving event's timestamp.** If no such touch exists, `attributed_touch_intent_id` is `None` (the recipient initiated contact OR an operator-side hand-sent message landed outside the framework).

```python
def _attribute_touch(touches, *, person_id, channel, before_ts):
    """Find the intent_id of the most-recent same-channel touch
    BEFORE the cutoff ts. Returns None if no qualifying touch exists.
    """
    bucket = touches.get((person_id, channel))
    if not bucket:
        return None
    last = None
    for ts, iid in bucket:  # sorted by ts ascending
        if ts < before_ts:
            last = iid
        else:
            break
    return last
```

**Outcome derivation map** per the canonical thread state:

| Source state / signal                                | Outcome             |
|------------------------------------------------------|---------------------|
| `state == unsubscribed`                              | `closed_unsubscribed` |
| `state == dormant` via `rejection` classification    | `closed_lost`         |
| `state == dormant` via `ooo` classification          | `dormant`             |
| `state == dormant` via TTL driver                    | `dormant`             |
| `state == active` + booking AFTER active transition  | `closed_won`          |
| `state == active` (no booking yet)                   | (no outcome — pending) |
| `state == classified`                                | (no outcome — pending) |
| `state == replied`                                   | (no outcome — pending) |

**Asymmetric semantics for `dormant`** (rejection → closed_lost; ooo → dormant; TTL → dormant) capture the operator-meaningful distinction:

* **Rejection** is a HARD signal — the recipient explicitly said "not interested." Closing as `lost` is operator-faithful.
* **OOO** is a SOFT signal — the recipient is temporarily unavailable. Reusing the `dormant` outcome avoids over-confident `closed_lost` (the conversation may resume).
* **TTL** is an INFERRED signal — no response in N days could mean lost, ooo, or "operator moved offline." Defaulting to `dormant` preserves uncertainty.

**closed_won correlation is per-PERSON** (not per-thread). Cal.com bookings don't carry the active-thread's `thread_key`. The closed_won outcome attribution looks for the EARLIEST booking AFTER the per-thread active-transition timestamp, independently per active thread. **When a person has multiple active threads + one booking lands after BOTH active-transitions, ALL eligible active threads receive a `closed_won` outcome event** — the framework cannot determine which active thread actually drove the booking, so the conservative v1 choice is to attribute won to every eligible thread (per-thread events let Pillar G dashboards compute decay-weighted refinement; collapsing to one event would lose information). The per-Person aggregation surface (`derived_conversation_outcome`) reflects `closed_won` regardless of how many threads emit. A future Pillar I CLI extension MAY refine per-thread correlation if Cal.com adds a custom-field surface that lets bookings carry the active-thread correlator (e.g., the booking URL's intent_id query-param surface per ADR-0019 D65 — the booking surface is structurally extensible).

**closed_won attributed touch** is the most-recent same-channel touch on the active thread BEFORE the booking. Per the v1 same-channel rule: a person whose active thread is on LinkedIn + who books a Cal.com session attributes the win to the most-recent LinkedIn touch (NOT to the Cal.com booking intent itself, which is the conversion signal, not the touch).

**Why same-channel attribution (rejected: cross-channel-shared-credit).** The per-thread state-machine substrate IS per-channel; attributing across channels would require a different aggregation primitive. Multi-touch shared-credit attribution is a Pillar G dashboard refinement, NOT a v1 ledger-event concern — Pillar G can derive cross-channel breakdowns from the per-thread outcome events without baking the model into the event class.

**Pin:** `tests/test_conversation_outcomes.py::TestAttributionSingleTouch::*` (one-touch happy path) + `::TestAttributionMultiTouchSameChannel::*` (multi-touch last-wins + after-driver-excluded) + `::TestAttributionCrossChannel::*` (cross-channel same-channel-only rule + None when no same-channel touch) + `::TestAttributionForBookingDrivenWon::*` (closed_won attribution to active-thread's touch).

### D132. TTL window default — 30 days; CLI flag `--conversation-ttl-days`

The TTL window default is `DEFAULT_CONVERSATION_TTL_DAYS = 30` (in `orchestrator/conversation_state.py`). Operator-tunable via the reconcile CLI flag `--conversation-ttl-days`:

```bash
# 30-day default — conservative B2B sales-cycle horizon
python -m orchestrator.reconcile --full

# 60-day window — operators with longer sales cycles
python -m orchestrator.reconcile --full --conversation-ttl-days 60

# 0 — disables the TTL driver (manual pipeline operators)
python -m orchestrator.reconcile --full --conversation-ttl-days 0
```

**TTL semantics**:

* The TTL driver evaluates AFTER the event-driven state-machine walk. For each thread, compute `last_activity_ts` (max ts across all driver events). If `now - last_activity_ts > ttl_days days` AND `current_state in {replied, classified, active}`, the TTL driver transitions to `dormant`.
* The TTL driver respects `STATE_PRIORITY` — it CANNOT demote `unsubscribed` (priority 4) to `dormant` (priority 2). The legal-liability invariant per ADR-0025 D97 + ADR-0028 D119 STAYS WITH FULL WEIGHT.
* The TTL transition's `trigger_event_id` carries `driver: "ttl"` so downstream consumers (Pass O outcome derivation, Pillar G dashboards) can distinguish TTL-driven dormancy from category-driven dormancy.
* `ttl_days=0` disables TTL evaluation entirely (operator-explicit). `now=None` (the default when callers don't supply it) ALSO disables — preserves backwards-compat with Week 4-5 callsites.

**Why 30 days default (rejected: 60 days; rejected: no default).** 30 days matches:

* The Pillar G observability convention (per the handoff's framing).
* A common B2B sales-cycle horizon for cold-touch outreach (the first 30 days are the highest-conversion window; past that, the operator is typically in re-engage mode).
* The `FULL_WINDOW = timedelta(days=30)` constant in `reconcile.py` — operators running `--full` see TTL transitions in the same cadence as the reconcile cadence.

60 days would be too patient — operators waiting longer to mark dormant lose visibility into "this thread is cold." No-default would force every operator to configure explicitly, breaking the "works out of the box" posture per ADR-0025 D101.

**Why CLI flag (rejected: cooldowns.yml extension; rejected: dedicated config file).** Three reasons CLI flag wins:

* **The TTL is one scalar value.** A YAML file is overkill for a single integer.
* **`cooldowns.yml` is the WRONG home.** It's the policy-rules surface — the policy engine consumes it. The TTL is NOT a policy rule (no gate evaluation); it's a conversation-state-machine driver. Embedding violates the separation of concerns + creates a non-obvious load-bearing coupling.
* **A dedicated config file (e.g., `~/.outreach-factory/conversation/conversation.yml`) is over-engineering for v1.** If a future Pillar I CLI extension ships persistent operator-config (e.g., per-channel TTLs, per-vertical defaults), the config file lands then. The CLI flag is sufficient for v1.

**Per-channel TTL refinement is a Pillar I extension.** Today: ONE global TTL. Future Pillar I CLI extension MAY allow `--conversation-ttl-days email=30,linkedin=14,twitter=7,calendar=60` if operator demand materializes; the parsing surface is namespace-isolated from the v1 scalar shape.

**Pin:** `tests/test_conversation_outcomes.py::TestTTLTransitions::*` (per-state TTL behavior + unsubscribed-not-affected + zero-disables + recent-activity-resets-window) + `tests/test_conversation_outcomes.py::TestPassNTTL::*` (Pass N integration — TTL-driven dormant emit shape) + `tests/test_conversation_state.py::*` (Week 4-5 callsites unchanged via backwards-compat default).

### D133. Pass placement — Pass N extended for TTL + new Pass O for outcomes

`ALL_PASSES` extends to 13 entries:

```python
ALL_PASSES = ("A", "B", "C", "D", "H", "E", "I", "F", "J", "G", "M", "N", "O")
```

**Pass N extension (TTL driver).** Pass N's existing surface (`conversation_state.run_conversation_state_pass`) gains two optional kwargs: `now` + `ttl_days`. When `now` is provided, the state-machine walk includes the TTL driver per D132. Pass N's wrapper in `reconcile.py` passes through the kwargs; the reconcile orchestrator stamps `now=datetime.now(timezone.utc)` when dispatching to Pass N (so TTL evaluation fires on every reconcile run).

**Pass O (NEW — conversation outcomes).** Standalone pass in `reconcile.py`:

```python
def run_pass_o(*, led, apply, now=None, ttl_days=30) -> PassResult:
    """Thin wrapper around conversation_outcomes.
    run_conversation_outcomes_pass — emits conversation_outcome events
    per ADR-0030 D130-D133."""
```

**Pass O placement — AFTER Pass N.** Pass O reads the canonical thread state (computed by `conversation_state.compute_thread_states` — the same source Pass N emits from). Running Pass O AFTER Pass N means the same reconcile run sees:

* Pass N's TTL-driven dormant transitions (now in the ledger as `conversation_state_changed` events).
* Pass O's per-thread outcomes (now in the ledger as `conversation_outcome` events).

Within Pass O, the outcome derivation re-computes the canonical state directly (does NOT depend on Pass N having persisted the events) — defense in depth against partial reconcile runs. The canonical-state-from-events approach mirrors Pass N's own deterministic-event-walk discipline.

**Pass O is NOT run-window-bounded by `since`.** Outcome attribution walks back through the FULL historical context (a touch from 90 days ago may still be the attributed touch for a recent outcome). A `since` window would arbitrarily exclude past touches. The (person_id, channel, thread_key, outcome) idempotence index ensures re-runs are cheap; the full-historical-walk cost is amortized via the index.

**`--full` invocation extended.** `python -m orchestrator.reconcile --full` defaults to `"A,B,C,D,H,E,I,F,J,G,M,N,O"` (previously `"A,B,C,D,H,E,I,F,J,G,M,N"`). Operators running `--full` get outcome attribution coverage automatically. `--quick` is UNCHANGED (Pass O is NOT in the quick path — outcome derivation is an end-of-cycle artifact, not a per-quick-run concern).

**Pass O has no external resource dependency.** Like Pass N, Pass O is a pure ledger-walker — no Gmail / LinkedIn / Twitter client needed. The reconcile orchestrator dispatches Pass O when requested in `--passes` without checking client availability.

**Why "extend Pass N for TTL + new Pass O for outcomes" (rejected: all-in-Pass-N; rejected: both-as-Pass-O).** Two design forces:

* **TTL is a NEW DRIVER for the EXISTING state machine.** It belongs in `compute_thread_states` (the state machine's primitive) + Pass N (the state machine's pass). Moving TTL evaluation into a separate pass would split the state machine surface across two files.
* **Outcome derivation is a NEW CONCERN with a NEW event class.** A new pass with its own dispatcher row keeps the per-pass-per-concern discipline per ADR-0027 D111. Conflating Pass N to also emit `conversation_outcome` events would push two distinct concerns through one wrapper.

The split matches the ADR-0028 D118 sibling-module discipline at the pass layer.

**Pin:** `tests/test_conversation_outcomes.py::TestReconcileIntegration::*` (Pass O in ALL_PASSES + after Pass N + reconcile integration emit). Pass N TTL emit shape pinned by `TestPassNTTL::*`.

### D134. Per-Person aggregation — `derived_conversation_outcome` + `OUTCOME_PRIORITY`

Across all threads belonging to one Person, the aggregated outcome is the highest-priority per-thread outcome (per `OUTCOME_PRIORITY`):

```python
OUTCOME_PRIORITY: dict[str, int] = {
    "dormant": 1,
    "closed_lost": 2,
    "closed_unsubscribed": 3,
    "closed_won": 4,
}

def derived_conversation_outcome(led, person_id, *, outcomes=None):
    oc_map = outcomes or compute_conversation_outcomes(led)
    return max(
        (oc.outcome for tk, oc in oc_map.items()
         if tk.person_id == person_id),
        key=lambda o: OUTCOME_PRIORITY[o],
        default=None,
    )
```

**Priority ordering**: `closed_won > closed_unsubscribed > closed_lost > dormant`. Reflects operator-facing signal:

* **closed_won dominates.** A person with one closed_won thread + N other outcomes is operationally "won" — the booking landed; downstream pipeline owns next steps.
* **closed_unsubscribed beats closed_lost.** The legal-liability surface is structurally weightier than a soft rejection. An operator dashboard query "who's actively unsubscribed?" sees the right answer.
* **closed_lost beats dormant.** A hard rejection signal is more operator-actionable than a TTL/ooo dormancy.
* **dormant is the floor.** Default state for "no signal."

**Why a NEW aggregation function (rejected: reuse `derived_conversation_status`; rejected: outcome lives on Person frontmatter via Pass C heal).** Three reasons:

* **The outcomes are SEPARATE from the conversation states.** `STATE_PRIORITY` orders `unsubscribed > active > dormant > classified > replied`. `OUTCOME_PRIORITY` orders `closed_won > closed_unsubscribed > closed_lost > dormant`. Two distinct priority systems for two distinct value spaces.
* **The Person frontmatter `conversation_status:` field STAYS per Week 4-5's design.** Adding a second `conversation_outcome:` Person frontmatter field would (a) require a new vault migration + Pass C heal extension, and (b) be redundant — Pillar G dashboards query the ledger directly, not the vault, for outcome breakdowns. The vault-denormalization story for outcomes is a future Pillar G concern, NOT Week 9-11's scope.
* **The aggregation function's caller surface is operator-readable.** Pillar G dashboards call `derived_conversation_outcome(led, person_id)` to get the per-Person aggregated outcome. Pillar I CLI surfaces the same value for the operator-facing report (`python -m orchestrator.conversation_outcomes report --since 30d` — TBD).

**No Person frontmatter heal in Week 9-11.** Pass C continues to heal `conversation_status:` (per ADR-0028 D119); no new field. Future Pillar G ADR may add `conversation_outcome:` if vault-denormalization warrants — TBD.

**Pin:** `tests/test_conversation_outcomes.py::TestDerivedConversationOutcome::*` (no-terminal-threads-returns-none + won-dominates + unsubscribed-beats-lost + precomputed-outcomes-accepted) + `TestOutcomesConstants::test_outcome_priority_canonical_order`.

### D135. Cross-pillar audit row extension (per ADR-0025 D99)

The Week 9-11 commit extends `.planning/REVIEW-pillar-d-surface-audit.md` with new rows for:

1. **ONE new event class — `conversation_outcome`.** Carries `person_id` → lands in `_idx_person` (broadens). Every `query_by_person` consumer is re-audited (every consumer already closed-set or literal-string-filtered against the existing event types per Weeks 1-8 audits; the new event class doesn't end in `_confirmed` so the cross-channel rule doesn't fire; not in `_STAGE_BY_EVENT_TYPE` so `derived_stage` doesn't broaden; not in `_INTENT_TYPES` so `open_intents` doesn't return them; not in REPLY_EVENT_TYPES so Pass G doesn't consume).

2. **ONE new emit-shape extension to `conversation_state_changed`** — the `trigger_event_id.driver: "ttl"` field for TTL-driven dormant transitions. Every consumer that reads `conversation_state_changed.trigger_event_id` is re-audited (Pass C heal reads `to_state` only; Pillar G dashboards by-design broaden; Pass O reads the driver field explicitly per D131 — by-design consumer).

3. **ONE new ledger-walk pattern — Pass O's per-thread outcome computation.** Walks `*_confirmed` events (the four touch-types in `_TOUCH_CONFIRMED_TYPES`) for attribution + `reply_classified` events for category cross-reference + `calendar_booking_confirmed` events for closed_won detection + the canonical state-machine output. Literal-string filters on every type → closed-set-protected.

4. **ONE new public-symbol surface — `orchestrator/conversation_outcomes.py`** (`ConversationOutcome`, `OUTCOMES`, `OUTCOME_PRIORITY`, `compute_conversation_outcomes`, `derived_conversation_outcome`, `build_outcome_payload`, `run_conversation_outcomes_pass`, `EMITTED_BY`). The cross-pillar audit names the module + the public symbols so future Pillar G dashboards + Pillar I CLI consume the stable surface.

5. **The TTL driver's interaction with terminal states.** The audit verifies the priority-respecting design — TTL CANNOT demote unsubscribed (the load-bearing legal-liability invariant per ADR-0025 D97 + ADR-0028 D119). Pinned by `tests/test_conversation_outcomes.py::TestTTLTransitions::test_unsubscribed_NOT_affected_by_ttl`.

The audit's verdict carries: **zero new P1 latent-bug patterns; the new event class's consumer surfaces are fully covered by the Weeks 1-8 audit's existing consumer enumeration + the new ledger-walk pattern is closed-set-protected by construction.**

**Pin:** `.planning/REVIEW-pillar-d-surface-audit.md` updated in the Week 9-11 commit with the Week 9-11 audit extension.

## Alternatives considered

### D129-Alt1: Inline outcome derivation in `conversation_state.py`

Extend `orchestrator/conversation_state.py` with `compute_conversation_outcomes` + `derived_conversation_outcome` + `run_conversation_outcomes_pass`. **Rejected** because:

* The state machine's surface stays focused on transitions (one concern); the outcome derivation adds a SECOND concern (terminal-state interpretation + attribution + booking correlation) to the same module. Per ADR-0026 D102's single-concern-per-module discipline.
* The outcome derivation has its own constant surface (`OUTCOMES`, `OUTCOME_PRIORITY`, `EMITTED_BY`) + its own dataclass (`ConversationOutcome`). Bundling these into `conversation_state.py` would push its public-symbol surface from 9 (today) to 17 (after merge), making the module's role harder to discover.
* The Pillar G dashboards consume one module OR the other depending on their query — the outcome-focused dashboards don't need the state machine's primitives + vice versa. Separation lets each consumer import precisely.

### D129-Alt2: Subpackage `orchestrator/reply_handlers/`

`orchestrator/reply_handlers/__init__.py` + `auto_unsubscribe.py` + `conversation_state.py` + `conversation_outcomes.py`. **Rejected for Week 9-11** (same reasoning as ADR-0028 D115-Alt2):

* Over-organization for three modules. The single-file convention from Weeks 2-8 + ADR-0028 D115's rationale continues — a subpackage shape lands if a future Pillar D / E / G week adds a 4th handler module that warrants shared abstraction.
* The three modules share small helpers (`ThreadKey` is the only common primitive); a subpackage would imply a shared `Handler` base class that doesn't exist + isn't needed.

### D129-Alt3: Inline in `reconcile.py` as part of Pass O

`run_pass_o` + every helper as private functions in `reconcile.py`. **Rejected** because:

* `reconcile.py` is already ~3100 lines after Pass O wiring. Inlining the outcome derivation primitives (4+ helpers + dataclass + constants + main computation) would push past 3400 lines.
* The outcome derivation primitives are reusable in the Pillar I CLI surface; encapsulating them in a dedicated module keeps `reconcile.py` focused on reconcile orchestration.

### D130-Alt1: Annotate the existing `conversation_state_changed` event with outcome fields

Add `outcome:` + `attributed_touch_intent_id:` to existing `conversation_state_changed` events. **Rejected** because:

* The state transition + the outcome are semantically distinct. A state transition fires whenever the state changes; an outcome fires only for TERMINAL states with attribution data. Conflating them would emit outcome fields with empty / placeholder values for every non-terminal transition.
* The idempotence keys differ (per D130 rationale). The state-changed event's key is `(pid, ch, tk, to_state)`; the outcome's key is `(pid, ch, tk, outcome)`. A thread that transitions through multiple states would emit multiple state-changed events with conflicting outcome-fields.
* Pillar G dashboards querying outcomes would have to filter `conversation_state_changed` events to terminal states + interpret the conflated shape. A dedicated event class is operator-readable + downstream-consumer-friendly.

### D130-Alt2: Per-Person outcome event instead of per-thread

Emit one `conversation_outcome` per Person (aggregated). **Rejected** because:

* Loses per-thread information. A person with three threads (one won, one lost, one dormant) has THREE distinct outcomes; collapsing to one Person-level outcome obscures the per-thread breakdown.
* Pillar G dashboards want both the per-thread breakdown (for funnel analytics) AND the per-Person roll-up. The per-thread events are the SoT; the per-Person aggregation is a denormalized view computed via `derived_conversation_outcome`.
* Cross-channel attribution would be ill-defined for a Person-level event (which channel's intent_id is the attributed_touch?).

### D130-Alt3: Multi-event outcome chain (per-touch credit instead of per-thread)

Emit one event per touch with fractional credit (decay-weighted attribution). **Rejected** for v1:

* Multi-touch attribution is a Pillar G dashboard analytic, NOT a ledger-event concern. The ledger events should be the canonical observations (terminal state reached, attributed to most-recent same-channel touch); per-touch decay-weighted credit is derivable from the per-touch send-side events.
* The fractional-credit shape adds complexity (per-touch weight, total-weight normalization) without operator-facing value at the event layer. Pillar G can compute decay-weighted from the per-thread outcomes + the per-touch send history.

### D131-Alt1: First-touch wins

The FIRST `*_confirmed` event in the thread's history is the attributed touch (the touch that "opened the door"). **Rejected** for v1:

* B2B cold-touch outreach typically has the most-recent touch be the most-likely driver (the recipient saw the latest email or LinkedIn message and replied to it). First-touch attribution would over-credit the initial cold pitch + under-credit follow-ups.
* The dispatcher's per-thread send cadence (typically 3-7 touches per active thread) means most threads have multiple touches; first-touch would skew the operator's understanding of "which touch worked."
* Operators wanting first-touch attribution for specific dashboards can derive it from the per-thread touch history; the v1 last-touch-wins captures the conversion-driver intuition for the majority case.

### D131-Alt2: Decay-weighted attribution

Multiple touches share credit, weighted by recency (e.g., exponential decay with 7-day half-life). **Rejected** for v1:

* More accurate for nuanced analytics but adds complexity (per-touch weight assignment, total normalization across touches). The per-event ledger shape becomes ambiguous (one outcome event with fractional credit across multiple intent_ids?).
* Pillar G dashboard is the right home for multi-touch refinement — the v1 outcome event provides the per-thread anchor; Pillar G computes the decay-weighted breakdown from the per-touch send history.
* Operators don't have observability data yet to validate which decay function is right; shipping a specific decay model would lock in an arbitrary choice.

### D131-Alt3: Cross-channel shared credit

A reply on LinkedIn after an email + LinkedIn touch shares credit across both channels. **Rejected** for v1:

* The per-thread state-machine substrate is per-channel — a reply on LinkedIn creates a LinkedIn thread; attributing to email crosses the per-channel boundary.
* Cross-channel attribution is operator-deliberate (some operators want it, others don't). Baking it into the v1 ledger shape would lock operators in; the dashboard layer (Pillar G) can compute cross-channel breakdowns from the per-channel outcome events.

### D132-Alt1: 60 days default

**Rejected** because:

* Too patient for typical B2B cold-touch sales-cycle. By 30 days, the recipient has seen multiple touches; lack of response strongly signals lost / dormant.
* Operators with longer cycles can tune up; the default should target the median operator.

### D132-Alt2: No default (operator-required)

Force every operator to specify `--conversation-ttl-days N` explicitly; refuse to run if absent. **Rejected** because:

* Breaks the "works out of the box" posture per ADR-0025 D101. Operators running `python -m orchestrator.reconcile --full` should get reasonable defaults.
* Operators rarely want to configure every knob; conservative defaults with operator-tunability is the right balance.

### D132-Alt3: Per-channel TTL with separate defaults per channel

`email: 30, linkedin: 14, twitter: 7, calendar: 60`. **Rejected** for v1:

* No data to validate per-channel defaults. Per-channel refinement is a Pillar I CLI extension if operator demand materializes (the v1 single-knob is parse-shape-compatible with a future `email=30,linkedin=14` extension).
* Increases the v1 configuration complexity without operator-visible value (operators rarely have data to tune per-channel TTLs differently).

### D133-Alt1: All-in-Pass-N — TTL + outcome computation in one extended Pass N

Extend Pass N to also emit `conversation_outcome` events. **Rejected** because:

* TTL is a state-machine concern (a new driver for the state machine's existing transitions). Outcome derivation is a DIFFERENT concern (terminal-state interpretation + attribution + booking correlation + a new event class).
* Conflating would push Pass N's role from "emit state transitions" to "emit state transitions + outcomes." The per-pass-per-concern discipline per ADR-0027 D111 favors separation.
* Pillar G dashboard queries that want outcomes only would have to filter Pass N's mixed-emit; separation lets each dashboard query precisely.

### D133-Alt2: Both as new Pass O (move TTL to Pass O too)

Pass N stays unchanged (Week 4-5 behavior); new Pass O handles BOTH TTL transitions AND outcome computation. **Rejected** because:

* TTL is a NEW DRIVER for the existing state machine — it belongs in `compute_thread_states` (the state machine's primitive). Moving TTL evaluation OUT of `compute_thread_states` would mean the state machine's "canonical state" computation depends on whether Pass O has run, violating the state machine's "deterministic from events" discipline.
* The per-Person aggregation surface (`derived_conversation_status`) calls `compute_thread_states` for per-thread aggregation. If TTL evaluation lived in Pass O, `derived_conversation_status` would miss TTL-driven dormancy unless Pass O had run first — coupling the state machine's read surface to the pass execution order.
* The current split (TTL in `compute_thread_states` + Pass N; outcomes in `compute_conversation_outcomes` + Pass O) keeps each surface's responsibility clear.

### D133-Alt3: Pillar I CLI standalone — Pass O ships as a Pillar I extension

Defer Pass O to Pillar I OSS bring-up; Week 9-11 ships the primitives + tests only. **Rejected** because:

* The handoff scopes Pass O to Week 9-11 explicitly. Deferring would push the outcome derivation past the Pillar D Week 12 exit-criterion close, conflicting with PILLAR-PLAN §2 Pillar D's binding text.
* The Pillar I CLI surface depends on Pillar D being stable; shipping outcome derivation in Pillar I would invert the dependency.
* The reconcile chain is the natural home for the outcome derivation — it's the cadence that already produces the per-thread state machine emits.

### D134-Alt1: Reuse STATE_PRIORITY for outcome aggregation

Treat `closed_won / closed_lost / closed_unsubscribed / dormant` as extensions of `STATE_PRIORITY`. **Rejected** because:

* The two priority systems have DIFFERENT orderings. STATES order: `unsubscribed > active > dormant > classified > replied`. OUTCOMES order: `closed_won > closed_unsubscribed > closed_lost > dormant`. Conflating would force one ordering on both consumers.
* The states are NON-TERMINAL (a thread in `active` may move to `closed_won` later); the outcomes are TERMINAL (once `closed_won`, no further upgrade). Different lifecycle semantics warrant different priority systems.

### D134-Alt2: Outcome lives on Person frontmatter via new Pass C heal extension

Add `conversation_outcome:` frontmatter field to Person notes; Pass C heals it from `derived_conversation_outcome`. **Rejected** for Week 9-11:

* Requires a new vault migration (`vault/0005_add_conversation_outcome_to_person_notes`) + Pass C heal extension + new SoT row. Increases the v1 scope without operator-visible value (Pillar G dashboards query the ledger directly).
* The `conversation_status:` Person frontmatter field (per ADR-0028 D119) is the operator-facing snapshot. The OUTCOME is a derived analytic; surfacing it in the vault risks confusing operators with two similar-looking fields.
* Future Pillar G ADR may add the field if vault-denormalization warrants — TBD.

### D134-Alt3: First-outcome-fires aggregation (no priority — earliest outcome wins)

A person's outcome is the EARLIEST terminal outcome (the first thread to reach a terminal state defines the Person's outcome). **Rejected** because:

* A person with one thread closed_lost first + a later thread closed_won would be reported as "lost" — operationally wrong (the booking landed; the operator's pipeline owns next steps).
* The priority-based aggregation captures the operator-facing signal ordering; earliest-wins captures temporal ordering without operator-meaning.

### D135-Alt1: Skip the audit extension; rely on Week 10+ to surface broadening

**Rejected** explicitly per ADR-0025 D99 + the Pillar C Week 12 retrospective lesson: every Pillar D week's commit extends the audit row-by-row. Skipping creates a precedent that future weeks could skip — the discipline compounds OR erodes.

### D135-Alt2: Land the audit extension in a separate follow-up PR

**Rejected** because the audit extension IS part of the Week 9-11 deliverable per `.planning/HANDOFF-pillar-d-week-9.md` §"Validation gate". Splitting the commit risks the audit landing days after the code change it documents.

## Consequences

### Positive

- **The conversation_outcome event class IS the canonical per-thread outcome record.** Pillar G dashboards query a single event class for win/loss attribution; Pillar I CLI surfaces the same shape.
- **The last-touch-wins attribution algorithm is the simplest correct v1.** Operators understand the rule; Pillar G dashboards can compute decay-weighted breakdowns from the per-touch send history.
- **The TTL driver closes the "stale active thread" failure mode.** Threads with no follow-up engagement past TTL auto-transition to dormant; operator's pipeline sees a clean signal.
- **Pass O is the LAST reconcile-pass surface for Pillar D's conversation lifecycle.** Pillar D Week 12 ships the exit-criterion close; no new passes after Week 9-11.
- **The cross-pillar surface audit (D135) continues the ADR-0025 D99 discipline.** One new event class + one new emit-shape extension are audited; future Pillar D week 12 reviewers consult the audit as the surface map.
- **The legal-liability invariant per ADR-0025 D97 + ADR-0028 D119 + ADR-0029 D123 STAYS WITH FULL WEIGHT** at FIVE layers + the TTL-respects-priority + Pass M unchanged + Pass O method-agnostic. No regression risk on the load-bearing CAN-SPAM compliance posture.

### Negative

- **Three new event types reserved across Weeks 1-8 are now emitted (`conversation_outcome` + `conversation_state_changed` with TTL driver field).** Operators upgrading to Week 9-11 see new event classes / shape values in the ledger; the per-week trajectory + the surface audit name them, but operators not consulting documentation may be surprised. **Mitigation:** the ADR + the funnel CLI's `by_type` breakdown surface the new event class operator-facing.
- **The TTL driver may transition active threads to dormant if the operator's offline pipeline isn't visible to the framework.** R017 names the risk; operators with long sales cycles or offline pipelines tune via `--conversation-ttl-days` OR disable via `--conversation-ttl-days 0`. **Mitigation:** TTL is operator-tunable + 0-disables; per-channel TTL deferred to Pillar I CLI extension if demand materializes.
- **closed_won correlation is per-Person, not per-thread, due to Cal.com's lack of custom-field surface.** A person with multiple active threads + one booking attributes the won outcome to the earliest active thread (which may not be the thread that actually drove the booking). **Mitigation:** Pillar I CLI extension MAY refine per-thread correlation if Cal.com adds a custom-field surface; until then, operators understand the per-Person correlation via the ADR + the audit.
- **Outcome derivation walks the full historical ledger (no `since` window).** For long-lived deployments, the walk's cost scales with ledger size. **Mitigation:** the (pid, ch, tk, outcome) idempotence index makes re-runs cheap; the per-run walk is O(events) but amortized across operator cadence (typically daily for batched operators).

### Neutral / observability

- **Pillar G dashboards see two new data dimensions: per-thread outcome breakdowns + TTL-driver-vs-category-driven dormancy.** The dashboard implementation is Pillar G's concern.
- **The TTL driver's behavior is observable via the `trigger_event_id.driver: "ttl"` field on `conversation_state_changed` events.** Operators querying the ledger for "which threads went dormant via TTL?" filter on this field.
- **Pass O's pass-result summary surfaces in `--json` mode** + the per-pass status persistence. Operators see the per-run outcome emission counts via `python -m orchestrator.reconcile --status`.

## Compliance with invariants

- **I1 (one writer per fact):** Pass O is the sole writer of `conversation_outcome` events. The `derived_conversation_outcome` aggregation is a read-side helper (no writes).
- **I2 (idempotent re-runs):** Pass O's (pid, ch, tk, outcome) idempotence key matches the ADR-0011 D24 + ADR-0025 D98 + ADR-0028 D119 discipline. Re-running emits no duplicate outcomes.
- **I3 (atomicity contract):** Pass O appends per-outcome via `Ledger.append` (single-event-per-call). No multi-event batching needed; no new atomicity surface.
- **I4 (reproducible state):** Deterministic walk + idempotence key + canonical state machine source = byte-identical re-emit on the same ledger.
- **I5 (append-only):** New `conversation_outcome` event class is append-only. Existing `conversation_state_changed` events get the `trigger_event_id.driver:` field on NEW emits only (existing ledger entries are unchanged — historical TTL emits don't exist pre-Week-9-11).
- **I6 (Pillar A policy SoT):** No new policy rules; no new policy YAML files.
- **I7 (Pillar B migration framework SoT):** Week 9-11 ships ZERO new migrations. The `conversation_outcome` event class is content-additive to the ledger; the TTL configuration is CLI-flag-tunable (no YAML migration needed).

### Downstream pillar impact

- **Pillar E (discovery quality + lineage).** Pillar E's discovery-pass logic may consume `conversation_outcome` events to learn discovery-source-to-outcome correlations (e.g., "prospects discovered via funded-founders source have a 12% closed_won rate; competitor-customers source has 8%"). The per-Person `derived_conversation_outcome` helper is the right consumer surface for Pillar E's enrollment quality dashboard.

- **Pillar F (vault rendering quality).** No direct impact. The vault denormalization for outcomes is a future Pillar G concern, not Pillar F's scope (vault rendering = how data is shown in Obsidian, not which data lives there).

- **Pillar G (observability + dashboards).** PRIMARY consumer. Pillar G's reply-funnel dashboard EXPANDS with the per-thread outcome breakdown (`emails sent → replied → classified → outcome breakdown`). The cross-channel attribution funnel uses `derived_conversation_outcome(person_id)` for per-Person roll-ups. The TTL-driven dormancy metric is a NEW dashboard row (operator visibility into "how many threads went dormant via TTL vs explicit rejection?"). Pillar G's dashboard implementation is Pillar G's concern; the event-class shape is the API surface this ADR pins.

- **Pillar H (continuous operations / daemon mode).** Pass O runs on the same reconcile cadence as Passes A-N; the daemon mode (TBD) invokes Pass O alongside other passes. No daemon-specific surface needed.

- **Pillar I (OSS bring-up + CLI).** Future Pillar I CLI surfaces consume the outcome-derivation primitives:
  - `python -m orchestrator.conversation_outcomes report --since 30d` — per-Person outcome breakdown.
  - `python -m orchestrator.conversation_outcomes replay --since <date>` — re-emit outcomes against pre-Pillar-D-Week-9-11 ledgers.
  - `--conversation-ttl-days` per-channel refinement extension (if operator demand materializes).
  These are Pillar I's scope; Week 9-11 ships the primitives as importable surface.

- **Pillar J (privacy + retention).** Outcome events carry `person_id` + correlate to historical touches. The Pillar J right-to-be-forgotten flow MUST tombstone outcome events alongside the other PII-carrying events when a person requests deletion. The existing tombstone primitive (per ADR-0011 D24's append-only-with-tombstone discipline) handles the new event class transparently — no new tombstone surface needed.

## Migration / rollout

**Existing operators (pre-Pillar-D-Week-9-11) seed three states**:

**Shape A — canonical (operator already running Week 4-5+ reconcile cadence)**:
- Ledger has `conversation_state_changed` events from Pass N.
- Operator runs `python -m orchestrator.reconcile --full` post-upgrade.
- Pass N emits TTL-driven dormant transitions for any non-terminal thread past 30 days inactivity.
- Pass O emits per-thread `conversation_outcome` events for every terminal-state thread (across the full ledger history — no `since` window).
- Operator sees the new event classes in the funnel CLI output.

**Shape B — gap (operator skipped Week 4-5; Week 9-11 is the first reconcile cadence with Pass N + Pass O)**:
- Ledger lacks `conversation_state_changed` events.
- Operator runs `python -m orchestrator.reconcile --full`.
- Pass N seeds `conversation_state_changed` for every historical thread (one event per thread per canonical state).
- Pass O immediately follows + emits outcomes against the now-populated state machine.
- Same end-state as Shape A.

**Shape C — new operator (cold start, no historical events)**:
- Ledger is empty.
- Pass O is a no-op (no terminal-state threads).
- Operator's first replies + classifications + suppressions drive the state machine on subsequent reconcile runs; Pass O emits outcomes as terminal states are reached.

**The TTL-driven dormancy MAY surprise long-cycle operators on the first post-upgrade run.** Threads that have been "active but stale" for >30 days (e.g., an operator was waiting on a recipient who never responded) get transitioned to dormant + emitted as `dormant` outcome. **Mitigation**: operators can override TTL via `--conversation-ttl-days 90` (or higher) for the first post-upgrade run + observe the breakdown via `--json`; subsequent runs use the default 30 days. The `dormant` outcome is operationally reversible (a new reply or operator-initiated touch creates a new thread; the dormant outcome stays in the ledger as historical observation).

**No new policy migration**. Pillar D Week 9-11 ships ZERO new policy / ledger / vault migrations. The pending migration count stays at 17 (unchanged from Week 6-8).

## Existing-operator seed

Per Shape A above: existing operators see Pass O emit per-thread outcomes for every terminal-state thread in their ledger on the first `python -m orchestrator.reconcile --full` post-upgrade. The outcome count is bounded by the number of terminal-state threads (typically <1000 for a year-long operator).

The TTL-driven dormancy MAY emit a burst of `dormant` outcomes on first run for operators with long-stale threads. The burst is one-time; subsequent runs see only newly-stale threads cross the TTL boundary.

The `--conversation-ttl-days 0` flag is the panic button — operators surprised by the burst can disable TTL transitions + re-run to see only the category-driven outcomes (rejection / unsubscribe). The per-Person aggregation `derived_conversation_outcome` reflects only the events in the ledger; disabling TTL preserves the operator's existing per-Person state.

## References

- ADR-0011 D24 — append-only ledger discipline; the load-bearing per-event-class shape pin.
- ADR-0014 D33 — channel-on-every-two-phase-event invariant carried forward via ADR-0025 D96 to all reply events + via this ADR to outcome events.
- ADR-0025 D96-D101 — Pillar D foundation; D98 forward-references the `closed_won | closed_lost | closed_unsubscribed` outcome states this ADR ships.
- ADR-0026 D102-D107 — Pillar D Week 2 rule-based classifier; Pass O consumes `reply_classified` events for category-driven outcome derivation.
- ADR-0027 D108-D114 — Pillar D Week 3 long-tail categories + per-channel reply detection; Pass O is method-agnostic (consumes regardless of classification_method).
- ADR-0028 D115-D121 — Pillar D Week 4-5 auto-unsubscribe handler + conversation state machine; Pass O builds on `compute_thread_states` per D118-D119. §Negative consequences's TTL deferral to Pillar D Week 9-11 — explicitly consumed by this ADR's D132.
- ADR-0029 D122-D128 — Pillar D Week 6-8 LLM fallback + classifier-cap; Pass O does NOT touch the LLM dispatch path. The THREE-layer (now FIVE-layer per the Week 6-8 follow-up reconciliation) legal-liability carry-forward STAYS WITH FULL WEIGHT.
- `.planning/HANDOFF-pillar-d-week-9.md` — the handoff this ADR consumes; scopes Week 9-11's deliverables.
- `.planning/REVIEW-pillar-d-surface-audit.md` — extended in Week 9-11's commit per D135.
- `docs/PILLAR-PLAN.md` §2 Pillar D — binding exit criterion; §5 — "What we will not do" (the unsubscribe = rule-based ONLY constraint stays with full weight).
- `docs/RISK-REGISTER.md` R017 — TTL-driven dormancy of active threads (new risk surfaced in this ADR).
