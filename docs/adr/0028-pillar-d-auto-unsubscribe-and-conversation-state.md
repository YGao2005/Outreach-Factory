# ADR-0028: Pillar D Week 4-5 — auto-unsubscribe handler + conversation state machine

- **Status:** Accepted
- **Date:** 2026-05-23
- **Pillar:** D (Reply + conversation handling — Week 4-5)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0025 (Pillar D Week 1 foundation) pinned the per-channel reply event-type naming (D96), the classifier output convention as a separate `reply_classified` event class (D97), the conversation state shape (D98), the cross-pillar surface audit (D99), the auto-unsubscribe enforcement contract (D100), and the exit-criterion vehicle scope (D101). ADR-0026 (Pillar D Week 2) shipped the rule-based classifier's foundation — module placement (D102), pattern-list YAML format + location (D103), the (reply_message_id, channel) idempotence pair (D104), Pass G's invocation cadence (D105), the cross-pillar audit row extension (D106), and the Week 4-5 deferral of the auto-unsubscribe handler (D107). ADR-0027 (Pillar D Week 3) shipped the long-tail classifier categories + per-channel reply detection — `RuleBasedClassifier.from_yaml_dir` (D109), dispatch priority order (D110), Passes H/I/J (D111), the `REPLY_EVENT_TYPES` closed-set (D112), Pass K deferral to Pillar I (D113), and the Week 3 audit extension (D114). Week 4-5 ships the TWO load-bearing consumers of the Week 2-3 classifier emit.

**Pillar D Week 4-5 is the auto-unsubscribe + conversation-state commit.** The handoff (`.planning/HANDOFF-pillar-d-week-4.md` — committed in the Week 3 follow-up) scopes Week 4-5 to two independent (but coordinated) extensions of Pillar D's substrate:

1. **The auto-unsubscribe handler** — reads `reply_classified` events filtered to `category=unsubscribe`, dedups by `(reply_message_id, channel)` per the load-bearing Week 2 P2-B carry-forward, and writes the matching email / domain / identity_key to `~/.outreach-factory/suppressions/auto-unsubscribe.yml` via the existing Pillar A `policy.suppression.forget_append` primitive (ADR-0004). The 60-second SLA per PILLAR-PLAN §2 Pillar D's binding text applies once Week 4-5 ships. The handler emits `suppression_added` ledger events correlating back to the originating classified event per ADR-0025 D100's atomic write contract.

2. **The conversation state machine** — per-thread state machine emitting `conversation_state_changed` events per ADR-0025 D98 (`replied → classified → unsubscribed | active | dormant`). Per-thread state, NOT per-person — a Person with multiple email threads + a LinkedIn DM thread + a Twitter DM thread has independent state machines per thread. The per-Person aggregation surface (`derived_conversation_status`) computes the highest-priority state across all threads belonging to one Person; Pass C extension heals the `conversation_status:` Person frontmatter from this derived value.

The seven concerns this ADR resolves:

1. **Handler module placement.** Three plausible homes: (a) `orchestrator/auto_unsubscribe.py` (single-file primitive sibling of `reply_classifier.py`); (b) `orchestrator/reply_handlers/` subpackage with `auto_unsubscribe.py` + future `conversation_state_handler.py` etc.; (c) inline in `orchestrator/reply_classifier.py` (conflates classifier + consumer). D115 picks (a).

2. **Write order and atomicity for the auto-unsubscribe contract.** ADR-0025 D100 pinned the contract shape; D116 names the Week 4-5 implementation — YAML-first via `forget_append` + ledger-second via `Ledger.append` (twice). The `append_batch` primitive Pillar B could have shipped is deferred (D116-Alt2 — the asymmetric-failure-cost calculus per ADR-0025 D100 already covers the failure mode; reconcile detects the asymmetric-crash inconsistency on next run).

3. **The LOAD-BEARING dedup-by-(reply_message_id, channel) requirement** (carry-forward from Week 2 P2-B). Concurrent Pass G runs CAN produce duplicate `reply_classified` events for the same pair per ADR-0026 §Negative consequences. The handler MUST dedup before writing OR it would double-write to YAML + emit two `suppression_added` events for one real unsubscribe. D117 pins.

4. **Conversation state machine module placement.** Two options: (a) `orchestrator/conversation_state.py` (standalone module, sibling of `reply_classifier.py` + `auto_unsubscribe.py`); (b) inlined into the auto-unsubscribe handler. D118 picks (a) — the state machine's downstream consumers (Pillar D Week 9-11 win/loss attribution + Pillar G dashboards) need it as a primitive independent of the handler.

5. **Per-thread state-machine transitions + per-Person aggregation logic.** ADR-0025 D98 named the shape but didn't pin the transition map. D119 fills in: `replied` (first `*_reply_received` event), `classified` (any `reply_classified`), `unsubscribed` (any `suppression_added`), `active` (`category=interest`), `dormant` (`category=rejection` or `category=ooo`). Per-Person aggregation picks the highest-priority state across all threads (unsubscribed > active > dormant > classified > replied).

6. **New pass placement in the reconcile chain.** The handoff's design-decision menu listed three letters (K / L / M). D120 picks **Pass M** = mutation (auto-unsubscribe handler — the first pass that writes outside the ledger to an external file) + **Pass N** (conversation state machine). Pass K stays reserved for Cal.com per ADR-0027 D113's deferral; Pass L is unused (the letter-skip preserves Pass K's operator-readable deferred slot).

7. **Cross-pillar audit row extension (per ADR-0025 D99).** Week 4-5 ships two new event classes (`suppression_added` + `conversation_state_changed`) + the new YAML-first write contract + the new `conversation_status:` Person frontmatter field. D121 names the audit extension.

Risks this ADR mitigates by design: **R012 (LLM hallucinates unsubscribe)** continues mitigated by ADR-0025 D97 + ADR-0026's `ClassifierResult.__post_init__` invariant. **R010 (Regulatory shift)** gains its production enforcement surface — the 60-second SLA + YAML-first write order make CAN-SPAM compliance the framework default. **R013 (operator pattern-list misconfiguration)** continues mitigated; the handler reads ONLY `category=unsubscribe` events from Pass G so a pattern mis-fire becomes auto-suppression only for unsubscribe-classified replies (the long-tail categories don't trigger writes).

A new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`: **R015 (asymmetric-crash inconsistency between YAML write + ledger append)**. Per ADR-0025 D100's failure-mode matrix, a crash between the YAML write + the ledger append leaves the suppression LIVE without an audit trail. Mitigations: (i) the YAML-first write order guarantees the suppression is live before the audit lands (CAN-SPAM posture preserved); (ii) reconcile surfaces YAML entries without paired `suppression_added` events on next run (future Pillar I doctor extension); (iii) the operator-visible failure-cost calculus per PILLAR-PLAN §0 biases toward suppression-without-audit > sent-after-unsubscribe.

## Decision

### D115. Handler module placement — `orchestrator/auto_unsubscribe.py`

The auto-unsubscribe handler ships as a single top-level module under `orchestrator/`, sibling of `reply_classifier.py` (per ADR-0026 D102's precedent) + `conversation_state.py` (per D118 below):

```
orchestrator/
├── reply_classifier.py        ← Pillar D Week 2-3 (ADR-0026, ADR-0027)
├── auto_unsubscribe.py        ← Pillar D Week 4-5 (this ADR)
├── conversation_state.py      ← Pillar D Week 4-5 (this ADR)
├── policy/                    ← Pillar A (policy rule classes — UNCHANGED)
├── migrations/                ← Pillar B (migration framework)
├── ledger.py
├── reconcile.py               ← extended with Pass M + Pass N (D120)
└── ...
```

**The handler is a pillar primitive, not a policy rule + not part of the reconcile module.** Policy rules consume events to make gate decisions; the handler produces ledger events + writes the suppression YAML. The handler also runs as part of the reconcile chain (Pass M wraps it per D120), but the primitive lives in its own module so:

* **Pillar I CLI may invoke the handler standalone.** A future `python -m orchestrator.auto_unsubscribe replay --since <date>` operator command (TBD) can re-run the handler against pre-Pillar-D-Week-4-5 classified events without invoking the full reconcile chain.
* **The handler's tests live in a dedicated file** (`tests/test_auto_unsubscribe.py`) rather than commingling with `tests/test_reconcile_*.py`.
* **The conversation_state machine is a sibling primitive** with overlapping helpers (`_extract_thread_key`); a top-level module shape avoids spurious cross-package dependencies.

**Subpackage rationale (option B) deferred.** A `orchestrator/reply_handlers/` subpackage would over-organize for Week 4-5's scope (2 modules: handler + state machine). The subpackage shape lands if a future Pillar D week adds 3+ handler modules — TBD per Week 6-8's ADR.

### D116. Write order — YAML-first + ledger-second via two `Ledger.append` calls

The handler implements ADR-0025 D100's atomic write contract via:

```python
# 1. YAML first — atomic per-file write-temp-then-rename via the
#    existing Pillar A primitive (ADR-0004).
written_path = forget_append(
    suppressions_dir,
    filename="auto-unsubscribe.yml",
    email=target.value,  # or domain= or identity_key=
)

# 2. Ledger append — single suppression_added event via Ledger.append.
led.append(build_suppression_added_payload(classified, target, written_path))
```

**Why two separate `Ledger.append` calls (rejected: ship a new `Ledger.append_batch` primitive).** Per ADR-0025 D100's failure-mode matrix, the YAML-first order already guarantees correctness for the CAN-SPAM posture:

* YAML write succeeds + ledger append succeeds → both written; happy path.
* YAML write succeeds + ledger append fails → suppression LIVE; audit trail incomplete. Reconcile surfaces on next run; operator's compliance posture preserved.
* YAML write fails + nothing else happens → handler propagates the exception; no `suppression_added` lands; operator sees the failure + can re-run.
* Both succeed but ledger-append-of-classifier-event-itself ALREADY HAPPENED → idempotence-by-pair (D117) catches the cross-run dedup case.

The `append_batch` primitive that ADR-0025 D100 proposed would tighten the audit-trail-completeness invariant (both events land atomically or neither does) but at the cost of a new Pillar B primitive. The asymmetric-failure-cost calculus per PILLAR-PLAN §0 biases toward suppression-live-without-audit over suppression-not-live-with-audit. Two `append` calls + reconcile detection is the right grain for v1.

**Why not write the auto-unsubscribe YAML to the existing `gdpr-forget.yml` file?** Operators reading the suppressions directory benefit from one file per write-source — `gdpr-forget.yml` (Pillar A's manual surface) stays distinct from `auto-unsubscribe.yml` (Pillar D's auto-suppression surface). The directory-merge semantics in ADR-0004's `load_suppression_dir` union both files at gate-evaluation time, so the dispatcher sees the combined set without operator wiring. The split lets a future operator (or auditor) grep `auto-unsubscribe.yml` for "what did the framework auto-suppress?" without sifting Pillar A's manual entries.

**Pin:** `tests/test_auto_unsubscribe.py::TestRunAutoUnsubscribeApplyPath::test_apply_writes_yaml_first_then_ledger` + `::test_yaml_write_first_invariant_under_ledger_append_failure` (the crash-injection test). Also `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_unsubscribe_classification_triggers_yaml_write_first` (the coherence-vehicle pin).

### D117. LOAD-BEARING dedup-by-(reply_message_id, channel) — Week 2 P2-B carry-forward

The handler maintains TWO dedup sets:

```python
# Cross-run dedup — built once at handler entry.
already_suppressed: set[tuple[str, str]] = _already_suppressed_keys(led)
# Within-batch dedup — built incrementally.
seen_this_batch: set[tuple[str, str]] = set()

for event in classified_events_filtered_to_unsubscribe:
    key = (event["reply_message_id"], event["channel"])
    if key in already_suppressed or key in seen_this_batch:
        deduped += 1
        continue
    # ... write YAML + ledger ...
    seen_this_batch.add(key)
```

**Why this dedup is LOAD-BEARING.** Per ADR-0026 §Negative consequences, concurrent Pass G runs (Pillar H daemon + a manual `--passes G` invocation racing on the in-memory idempotence index) CAN produce duplicate `reply_classified` events for the same `(reply_message_id, channel)` pair. The Week 2 emit-only posture bounds the failure to extra ledger entries; Week 4-5's handler — the FIRST CONSUMER of these events — would amplify the failure into:

* Double-write to the suppression YAML (set-idempotent so no on-disk corruption, but two atomic-rename IO ops where one suffices — performance noise).
* TWO `suppression_added` events for one real unsubscribe → audit-trail divergence; Pillar G dashboard double-counts.

The fix is the dedup pair. The cross-run set (`already_suppressed`) catches the case where one Pass G run has already emitted both classified events + an earlier handler run has already suppressed the first one; the second handler run sees the existing `suppression_added` event + skips. The within-batch set (`seen_this_batch`) catches the case where TWO duplicate classified events land within the same handler run; the second one is skipped.

**The pair (mid, channel) — NOT bare mid.** Mirrors ADR-0026 D104's discriminator. Per-channel message-id namespaces could in principle collide; the pair guarantees uniqueness regardless of platform-specific id schemes.

**Pin:** `tests/test_auto_unsubscribe.py::TestDedupRequirement::test_handler_deduplicates_by_reply_message_id_and_channel_within_batch` + `::test_handler_deduplicates_across_runs` + the LOAD-BEARING coherence-vehicle row `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_handler_deduplicates_by_reply_message_id_and_channel`.

### D118. Conversation state machine module placement — `orchestrator/conversation_state.py`

The conversation state machine ships as a STANDALONE module sibling of `auto_unsubscribe.py`, NOT inlined:

```python
# orchestrator/conversation_state.py
class ThreadKey: ...          # frozen dataclass (person_id, channel, thread_key)
class ThreadState: ...        # mutable; tracks state + per-state trigger
STATE_PRIORITY: dict[str, int]
def compute_thread_states(led, *, since=None) -> dict[ThreadKey, ThreadState]: ...
def derived_conversation_status(led, person_id, *, thread_states=None) -> str | None: ...
def run_conversation_state_pass(*, led, since, apply) -> ConversationStatePassResult: ...
```

**Why a standalone module (rejected: inline in auto_unsubscribe.py).** The conversation state machine has multiple downstream consumers BEYOND auto-unsubscribe:

* **Pass C extension** (this ADR's D119) reads `derived_conversation_status` to heal the per-Person `conversation_status:` frontmatter field. Pass C is in `reconcile.py`; coupling it to the auto-unsubscribe module would invert the dependency direction (Pillar D Week 4-5 makes reconcile depend on the handler module rather than the state machine module).

* **Pillar D Week 9-11 win/loss attribution** (ADR-0029 — TBD) consumes conversation state machine output for the per-thread + per-Person outcome dashboard.

* **Pillar G observability** consumes `conversation_state_changed` events for the reply-funnel + per-channel conversion dashboards.

* **The vault migration vault/0004** (D119 below) uses `derived_conversation_status` to compute the initial denormalized state for every Person on existing-operator upgrade.

A standalone module lets each consumer import the primitive without pulling in the auto-unsubscribe handler's dependencies (the suppression rule contract + the `forget_append` primitive).

**Sharing the per-channel thread-key helper.** Both `auto_unsubscribe.py` + `conversation_state.py` have a `_extract_thread_key(event) → str | None` helper. The two are duplicated (deliberately small + close-to-callsite); a future Pillar I refactor MAY extract to a shared `orchestrator/per_channel.py` if more consumers materialize.

### D119. Per-thread state transitions + per-Person aggregation logic

The per-thread state machine's canonical states + transitions:

| State | Driver event | Source |
|---|---|---|
| `replied` | First `*_reply_received` event on the thread | Pass B (email) or Pass H/I/J (LinkedIn/Twitter) |
| `classified` | Any `reply_classified` event for a reply on the thread | Pass G |
| `unsubscribed` | First `suppression_added` event correlating to a classified event on the thread | Pass M (this ADR) |
| `active` | First `reply_classified` with `category=interest` on the thread | Pass G |
| `dormant` | First `reply_classified` with `category=rejection` OR `category=ooo` on the thread | Pass G |

**Priority ordering** (used both for transition-conflict resolution + per-Person aggregation):

```
unsubscribed (4) > active (3) > dormant (2) > classified (1) > replied (0)
```

When multiple drivers fire on the same thread, the higher-priority state wins. Example: a thread with a `reply_classified.category=interest` (would yield `active`) followed by a `reply_classified.category=unsubscribe` + `suppression_added` (would yield `unsubscribed`) lands in `unsubscribed` because that state has higher priority.

**The priority captures the asymmetric-failure-cost calculus per PILLAR-PLAN §0.** A misclassified `unsubscribed` (top priority) is the most-conservative state — CAN-SPAM compliance is preserved even if the framework over-suppresses. An under-prioritized `active` thread costs one missed conversion opportunity; the trade-off favors the legal-liability posture.

**Per-Person aggregation logic.** Across all threads belonging to one Person, the aggregated `conversation_status:` value is the highest-priority per-thread state:

```python
def derived_conversation_status(led, person_id, *, thread_states=None):
    states = thread_states or compute_thread_states(led)
    return max(
        (ts.state for tk, ts in states.items()
         if tk.person_id == person_id and ts.state is not None),
        key=lambda s: STATE_PRIORITY[s],
        default=None,
    )
```

**Why per-thread state, not per-person (rejected: D98-Alt2's per-person aggregation as primary).** A Person with three active email threads + one unsubscribed-via-LinkedIn-DM thread has FOUR distinct conversation states; collapsing them to one loses information. The per-thread machines are the SoT; the per-Person aggregation is the denormalized view operators see via the `conversation_status:` Person frontmatter field.

**Pass C extension — `conversation_status:` heal.** Per Pass C's existing `pipeline_stage:` heal pattern, the extension:

1. Precomputes `thread_states` ONCE per Pass C run (avoids O(N persons × full-ledger-walk)).
2. For each Person note, computes `derived_conversation_status(led, person_id, thread_states=thread_states)`.
3. Compares to the Person's existing `conversation_status:` frontmatter; writes the ledger-derived value when drift detected (vault → ledger direction).
4. Emits `reconcile_healed` event with `field: "conversation_status"` for audit trail.

The heal direction is one-way (vault → ledger) UNLIKE `pipeline_stage:` (which has a conflict path for vault-ahead-of-ledger). The conversation state machine is fully ledger-derived; vault drift in either direction is operator-edited noise that the ledger overwrites. No "conflict" surface — the ledger is the SoT per I1.

**Vault migration `vault/0004_add_conversation_status_to_person_notes` ships the existing-operator seed.** The migration walks every Person note, computes `derived_conversation_status`, and stamps the field. Operators with pre-Pillar-D-Week-4-5 reply state see the field populated on the next `runner.apply()`. Pass C heals on each subsequent reconcile run.

**Pin:** `tests/test_conversation_state.py::TestComputeThreadStates::*` (per-state transitions) + `::TestDerivedConversationStatus::*` (per-Person aggregation) + `::TestRunPass::*` (Pass N orchestration). Pass C extension covered by extending the existing `test_reconcile.py::TestPassC` tests in the follow-up commit if surface-audit finds gaps.

### D120. New pass placement — Pass M (auto-unsubscribe) + Pass N (conversation state)

Two new passes join the reconcile chain after Pass G:

```python
ALL_PASSES = ("A", "B", "C", "D", "H", "E", "I", "F", "J", "G", "M", "N")
```

**Pass naming — "M" for mutation, "N" alphabetical.** Per the handoff's design-decision menu (recommendation: option C — "M = mutation" carries the most operator-clarity). Pass M is the FIRST pass that writes OUTSIDE the ledger (to the suppression YAML — a Pillar A SoT per ADR-0004); the naming signals the distinction. Pass N is the next alphabetical letter; the conversation state machine emits ledger events only (no external write).

**Pass K stays reserved.** Per ADR-0027 D113, Pass K is the deferred Cal.com booking-reply detection slot. Future Pillar I OSS bring-up may ship Pass K if Cal.com gains a comment API; preserving the letter keeps the deferred semantic operator-readable. Pass L is intentionally unused (skipped in the letter sequence to preserve Pass K's slot).

**Pass M placement — AFTER Pass G.** Pass G classifies + emits `reply_classified`; Pass M consumes Pass G's emit (filtered to `category=unsubscribe`) + writes the YAML + emits `suppression_added`. The data-flow order is producer-before-consumer per the chain's existing discipline (Pass D before Pass H per ADR-0027 D111; Pass G after H/I/J per ADR-0026 D105).

**Pass N placement — AFTER Pass M.** Pass N's `classified → unsubscribed` transition depends on `suppression_added` events; running Pass N after Pass M lets the same reconcile run produce both the suppression + the state transition. Per-thread states for `active` / `dormant` / `classified` (driven by `reply_classified` alone) would land regardless of Pass M's outcome; the `unsubscribed` transition is the one that requires the ordering.

**Pass C extension runs WITH Pass C, NOT as a separate pass.** The `conversation_status:` heal lives inside `run_pass_c` rather than as a standalone Pass — Pass C already walks every Person note to heal `pipeline_stage:`; adding a second heal in the same walk avoids a redundant vault iteration. The thread-states precomputation also serves both Pass C's heal + Pass N's emit if both passes run in the same reconcile invocation; future Pillar I optimization MAY share the precomputed map across passes via a per-run context (today's separate-precompute approach keeps the pass interface simple).

**`--full` invocation extended.** `python -m orchestrator.reconcile --full` defaults to `"A,B,C,D,H,E,I,F,J,G,M,N"` (previously `"A,B,C,D,H,E,I,F,J,G"`). Operators running `--full` get auto-unsubscribe + conversation state machine coverage automatically. `--quick` is UNCHANGED.

**New CLI flag — `--suppressions-dir`.** Mirrors the `--ledger-dir` + `--reconcile-dir` + `--classifier-rule-list` pattern. Defaults to `~/.outreach-factory/suppressions/`. Override for test injection + per-environment tuning.

**Pin:** `tests/test_reply_classifier.py::TestReconcileIntegration::test_pass_g_in_all_passes` + `::TestPassHIJSymbolSurface::test_all_passes_includes_h_i_j` (the data-flow ordering invariants extended). The detailed Pass M + Pass N behavior tests live in `tests/test_auto_unsubscribe.py` + `tests/test_conversation_state.py`.

### D121. Cross-pillar audit row extension (per ADR-0025 D99)

The Week 4-5 commit extends `.planning/REVIEW-pillar-d-surface-audit.md` with new rows for:

1. **Two new event classes — `suppression_added` + `conversation_state_changed`.** Each carries `person_id` → lands in `_idx_person` (broadens). Every `query_by_person` consumer is re-audited (every consumer already closed-set or literal-string-filtered against the existing event types per Weeks 1+2+3 audits; the new event classes don't end in `_confirmed` so the cross-channel rule doesn't fire; not in `_STAGE_BY_EVENT_TYPE` so `derived_stage` doesn't broaden; not in `_INTENT_TYPES` so `open_intents` doesn't return them).

2. **One new ledger-walk pattern — Pass M's `(reply_message_id, channel)` dedup index** (mirrors Pass G's idempotence walk per ADR-0026 D104). Literal-string filter on `type == "suppression_added"` → closed-set-protected against future event-type additions.

3. **One new ledger-walk pattern — Pass N's per-thread state computation.** Walks `*_reply_received` / `reply_classified` / `suppression_added` events; literal-string filters on every type → closed-set-protected.

4. **One new YAML-first write pattern — Pass M's `forget_append` call.** First reconcile-pass surface that writes to the suppression directory (`~/.outreach-factory/suppressions/`); the YAML-first invariant is the load-bearing CAN-SPAM compliance posture. Audit verifies the write is atomic (per ADR-0004's `forget_append` write-temp-then-rename contract) + the ledger append is decoupled (failure between the two is handled per ADR-0025 D100's failure-mode matrix).

5. **One new vault frontmatter field — `conversation_status:`** per Person. Pass C's heal extension is the SoT writer; Pillar G dashboards may read directly (denormalized for operator-facing query simplicity). The per-Person aggregation logic per D119 is the canonical SoT computation.

The audit's verdict carries: **zero new P1 latent-bug patterns; the two new event classes' consumer surfaces are fully covered by the Weeks 1-3 audit's existing consumer enumeration + the new ledger-walk patterns are closed-set-protected by construction.**

**Pin:** `.planning/REVIEW-pillar-d-surface-audit.md` updated in the Week 4-5 commit with the new rows.

## Alternatives considered

### D115-Alt1: Place the handler inside the reply_classifier module

Extend `orchestrator/reply_classifier.py` with `run_auto_unsubscribe_handler` + `build_suppression_added_payload`. **Rejected** because:

* Conflates the event-PRODUCER surface (classifier) with the event-CONSUMER surface (handler). The classifier's job is to interpret reply text → category; the handler's job is to write the suppression YAML + emit ledger events. Two distinct failure-mode surfaces in one module increases blast radius.
* Future Pillar D weeks (Week 6-8 LLM fallback) extend the classifier module; bundling the handler would force handler updates to coordinate with classifier updates even when their concerns are independent.
* The Pillar I CLI use-case (replay handler against historical classified events) benefits from importing only the handler module, not the classifier's pattern-loading + regex compilation surface.

### D115-Alt2: Spin up a `orchestrator/reply_handlers/` subpackage

`orchestrator/reply_handlers/__init__.py` + `auto_unsubscribe.py` + `conversation_state.py` + future handlers. **Rejected** for Week 4-5:

* Over-organization for two modules. The single-file convention from Weeks 2-3 (`reply_classifier.py`) + ADR-0026 D102's rationale continues — the subpackage shape lands when a future Pillar D week adds 3+ handler modules.
* The two Week 4-5 modules share a small helper (`_extract_thread_key`) but otherwise have orthogonal surfaces; a subpackage would imply a shared abstraction (e.g., a `Handler` base class) that doesn't exist + isn't needed.

### D115-Alt3: Inline the handler in `orchestrator/reconcile.py` as part of Pass M

`run_pass_m` in reconcile.py + every helper as private functions in the same file. **Rejected** because:

* `reconcile.py` is already ~2900 lines (12 passes × ~150 LOC + helpers + CLI). Inlining the handler would push the file past 3100 lines + future Pillar D weeks would push further.
* The handler's helpers (`resolve_suppression_target`, `build_suppression_added_payload`, `_already_suppressed_keys`) are reusable in the Pillar I CLI surface; encapsulating them in a dedicated module keeps reconcile.py focused on reconcile orchestration.

### D116-Alt1: Ledger-first write order; YAML second

Reverse the write order. **Rejected** explicitly per ADR-0025 D100's invariant — a crash between ledger append + YAML write leaves the audit trail recording an intent that the suppression list doesn't reflect → the next dispatch could send to the unsubscribed prospect. CAN-SPAM violation. YAML-first preserves the legal-liability posture.

### D116-Alt2: Ship `Ledger.append_batch(events: list[dict]) -> list[dict]` as a Pillar B primitive extension

A new atomic multi-event append via one fcntl-locked file write. The two-event batched append per ADR-0025 D100 would tighten the audit-trail-completeness invariant (both events land atomically or neither does). **Rejected for v1** because:

* The asymmetric-failure-cost calculus per ADR-0025 D100 already covers the failure mode — YAML-first guarantees correctness for the CAN-SPAM posture even when the ledger append fails.
* Pillar B's atomicity contract is single-event-per-`append`; extending to batch would require either a new `O_APPEND` + buffered-write semantics (which is the same atomicity as one large write) OR a multi-line append-with-lock (which requires the locking + crash-safety guarantees to be re-verified).
* No other Pillar B consumer wants `append_batch` today; the YAGNI principle defers the primitive until a second use-case justifies it.

The future Pillar I (or Pillar H) week MAY ship `append_batch` when the daemon's per-batch-write performance or the audit-trail-completeness invariant warrants. Until then, two `append` calls + reconcile detection is the right grain.

### D116-Alt3: Defer auto-unsubscribe writing to a Pillar H daemon-only path

The Pillar H daemon (Weeks 37-48) is the operationally-stronger surface for high-volume operators. Defer the write logic to the daemon + ship only the classifier in Week 4-5 as a Week-2-emit-only continuation. **Rejected** because:

* PILLAR-PLAN §2 Pillar D exit criterion explicitly names the 60-second SLA as binding for Pillar D's "stable" flip. Deferring to Pillar H would defer the exit criterion past Week 12.
* Batched operators (the current Yang use-case) get auto-unsubscribe coverage today via the batched-reconcile cadence; the Pillar H daemon is the OPERATIONAL STRONGER surface, not a prerequisite.

### D117-Alt1: Skip dedup; rely on YAML idempotence

The YAML `forget_append` writes a SET (per ADR-0004 — `existing.emails.add(...)`); duplicate writes produce the same on-disk state. Skip the handler-level dedup. **Rejected** because:

* The YAML write is set-idempotent; the LEDGER write is NOT (`Ledger.append` writes one new event per call). Without dedup, two duplicate `reply_classified` events for the same pair produce two `suppression_added` events in the ledger — audit-trail divergence + Pillar G dashboard double-count.
* The Week 2 P2-B reviewer's finding explicitly flagged this as load-bearing for Week 4-5; the handoff carry-forward names the dedup requirement.
* The dedup is cheap — one O(events) walk to build the `already_suppressed` set + O(1) per-event lookup. The protection is asymmetric: the calculus favors "do the cheap dedup" over "accept the audit-trail divergence."

### D117-Alt2: Use event timestamps for dedup (skip events emitted after the first one per pair)

Order classified events by ts; skip any with a duplicate (mid, channel) pair after the first. **Rejected** because:

* The classified events' timestamps are when Pass G emitted, not when the original reply arrived. Multiple Pass G runs can produce out-of-order timestamps (the Pillar H daemon + a manual `--passes G` may race). The (mid, channel) pair is the only deterministic discriminator.
* Per Pass G's per-(mid, channel) idempotence per ADR-0026 D104, Pass G itself defends against this; the handler's dedup is defense-in-depth.

### D117-Alt3: Dedup by `source_reply_classified_event` field on the suppression_added event

Discriminate via the emitted event's correlation key rather than the input event's pair. **Rejected** because:

* The `source_reply_classified_event` field is a dict (per D116) — set-membership doesn't work cleanly. Extracting the (mid, channel) pair from the dict + using THAT as the dedup key is the same shape as D117's existing implementation, just with extra indirection.
* The dedup happens BEFORE the handler emits the `suppression_added` event; using the emitted event for dedup is a chicken-and-egg problem.

### D118-Alt1: Inline the conversation state machine in the auto-unsubscribe handler

`compute_thread_states` + `derived_conversation_status` live inside `auto_unsubscribe.py`. **Rejected** because:

* The state machine's downstream consumers (Pass C heal, Pillar D Week 9-11 win/loss attribution, Pillar G dashboards) need it as a primitive independent of the handler. Inlining would force every consumer to depend on the handler's transitively-imported `policy.suppression.forget_append`.
* The state machine's `replied → classified` transition fires for EVERY reply (regardless of category). The auto-unsubscribe handler only cares about `category=unsubscribe`. Coupling them would mean the state machine inherits the handler's narrowing — wrong scope.

### D118-Alt2: Inline the state machine in `reconcile.py` as part of Pass N

`run_pass_n` + the per-thread state computation live in reconcile.py. **Rejected** because:

* `reconcile.py` is already large; encapsulating the state machine's primitives in a dedicated module lets future weeks extend without churning reconcile.py.
* The state machine has a non-trivial API surface (`ThreadKey`, `ThreadState`, `STATE_PRIORITY`, `compute_thread_states`, `derived_conversation_status`); the standalone module makes the surface discoverable.

### D118-Alt3: Skip the standalone state machine; compute the `conversation_status:` field directly in Pass C

Pass C reads `_idx_person.get(person_id)` + applies the state-driver logic inline; no module + no events emitted. **Rejected** because:

* The `conversation_state_changed` event class is the load-bearing surface for Pillar G's reply-funnel dashboard (per ADR-0025 D98). Without the events, Pillar G dashboards would have to re-compute the transitions on every query.
* Win/loss attribution (Pillar D Week 9-11) needs the per-thread state transitions as explicit events. Skipping them in Week 4-5 would force Week 9-11 to backfill.

### D119-Alt1: Operator-tunable state priority via YAML

Operators may want a different priority order for their vertical (e.g., interest > unsubscribed for a vertical where positive engagement is dominant). Ship `~/.outreach-factory/classifier/state-priority.yml`. **Rejected** because:

* The unsubscribed-FIRST invariant per ADR-0025 D97 is the load-bearing CAN-SPAM compliance surface; operators MUST NOT be able to (accidentally or maliciously) lower unsubscribed below another state. Operator-tunable priority would create the configuration-error surface.
* The fixed priority captures the asymmetric-failure-cost calculus per PILLAR-PLAN §0 + leaves no room for operator misconfiguration.

### D119-Alt2: Per-thread state-change events emit on EVERY transition (including unchanged)

Emit a `conversation_state_changed` event whenever ANY driver event lands, even if the thread's state doesn't actually change. **Rejected** because:

* Inflates the ledger with no-op events (a thread that's already `classified` getting a second `reply_classified` would emit a `classified → classified` event). Operator visibility benefit is nil; storage cost scales with reply volume.
* The current Pass N idempotence key `(person_id, channel, thread_key, to_state)` captures the right grain — one event per state-DESTINATION reached. Future Pillar G dashboards can compute "how often did the thread re-classify?" from the `reply_classified` event count directly.

### D119-Alt3: TTL-based `* → dormant` for inactive threads in Week 4-5

Add a time-based driver: any thread with no driver event in 30 days transitions to `dormant`. **Rejected for Week 4-5** (deferred to Pillar D Week 9-11):

* TTL semantics require an operator-tunable cadence (some operators want 14 days; others 90); the configuration surface is non-trivial.
* The win/loss attribution work in Week 9-11 (ADR-0029) is the natural home for the TTL — it's coupled to the outcome-tracking surface (`closed_won` / `closed_lost`).
* Operators can manually grep ledger events for "threads with no activity in N days" today; the auto-dormant transition is a UX improvement, not a load-bearing requirement.

### D120-Alt1: Pass K = auto-unsubscribe (reuse the deferred Cal.com slot)

Per the handoff's option A — the Cal.com Pass K deferral per ADR-0027 D113 may never resolve (Cal.com may never ship a comment API). Reuse the slot. **Rejected** because:

* If/when Cal.com SHIPS a comment API + Pillar I revisits Pass K, the conflict would require renaming OR re-purposing the slot. Preserving Pass K as deferred-with-rationale keeps the option open.
* The "M = mutation" naming carries operator-clarity: M is the first pass that writes outside the ledger. Pass K would be ambiguous (is it Cal.com? auto-unsubscribe? Both?).

### D120-Alt2: Pass L = auto-unsubscribe; reserve K for Cal.com

Use the next sequential letter. **Rejected** because:

* L has no operator-readable mnemonic. The "M = mutation" naming gives operators a hook ("Pass M writes to the suppression YAML, the only pass that writes outside the ledger").
* Letter-skipping signals the deferred Pass K's reserved nature; reusing L for auto-unsubscribe would lose that signal.

### D120-Alt3: Run Pass M + Pass N before Pass G in the chain (parallel-pass model)

The conversation state machine could process pre-existing `*_reply_received` events from prior runs without waiting for Pass G to emit new `reply_classified` events. **Rejected** because:

* Pass N's `classified → unsubscribed` transition driver is `suppression_added` events, which Pass M emits. Pass M's input is `reply_classified` events, which Pass G emits. The data-flow order REQUIRES G → M → N for in-same-run convergence.
* Pre-existing replies from prior reconcile runs ALREADY have their `reply_classified` events in the ledger; Pass G's same-run emit is the marginal case. The G → M → N order handles both.

### D121-Alt1: Skip the audit extension; rely on Week 5+ to surface broadening

Pillar D Weeks 5+'s per-week reviewers would extend the audit. **Rejected** explicitly per ADR-0025 D99 + the Pillar C Week 12 retrospective lesson: every Pillar D week's commit extends the audit row-by-row. Skipping creates a precedent that future weeks could skip too — the discipline compounds OR erodes.

### D121-Alt2: Land the audit extension in a separate follow-up PR

Ship the handler + state machine + Pass M/N first; ship the audit extension in a Week 4-5 follow-up. **Rejected** because the audit extension IS part of the Week 4-5 deliverable per HANDOFF-pillar-d-week-4.md §"Validation gate". Splitting the commit risks the audit landing days/weeks after the code change it documents.

## Consequences

### Positive

- **The auto-unsubscribe handler is the FIRST framework surface that auto-writes to a Pillar A SoT (the suppression YAML).** Operators get CAN-SPAM compliance from Week 4-5 forward; the 60-second SLA per PILLAR-PLAN §2 Pillar D is binding from this commit.
- **The dedup-by-(reply_message_id, channel) requirement is pinned + tested.** A future contributor producing duplicate `reply_classified` events sees the handler's defense-in-depth working OR is loudly told by `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_handler_deduplicates_by_reply_message_id_and_channel` that they broke it.
- **The YAML-first write order is verified by crash-injection.** The coherence-vehicle test (`test_unsubscribe_classification_triggers_yaml_write_first`) forces the ledger append to fail + asserts the YAML state intact. The CAN-SPAM compliance posture is structurally guaranteed.
- **The conversation state machine is a distinct primitive.** Pillar D Week 9-11 (win/loss attribution) + Pillar G dashboards consume the state-transition events directly; no re-derivation needed.
- **The per-Person `conversation_status:` denormalization heals automatically.** Operators see the field on every reconcile run; vault drift (operator hand-edits) auto-converges to the ledger-derived canonical.
- **The cross-pillar surface audit (D121) continues the ADR-0025 D99 discipline.** Two new event classes + the new YAML-first write contract are audited; future Pillar D weeks consult the audit as the surface map.
- **Pass M's "M = mutation" naming signals semantic distinction.** Operators reading the reconcile chain see Pass M as the only pass that writes outside the ledger — the operator-readable signpost for the load-bearing CAN-SPAM compliance write.

### Negative

- **Five new event types reserved in Weeks 1-3 are now emitted (`suppression_added` + `conversation_state_changed`).** Operators upgrading to Week 4-5 see new event classes in the ledger; the per-week trajectory + the surface audit name them, but operators not consulting documentation may be surprised. **Mitigation:** the ADR + the funnel CLI's `by_type` breakdown surface the new types operator-facing.
- **The asymmetric-crash failure mode (YAML written + ledger append failed) is not auto-recovered.** Per ADR-0025 D100's failure-mode matrix, reconcile pass surfaces YAML-without-paired-event inconsistencies on next run; the Week 4-5 implementation does NOT ship the recovery pass (it's a future Pillar I doctor extension). **Mitigation:** the failure mode is documented; operators can manually grep the suppression YAML + the ledger for divergence + emit a `suppression_added` event via the future Pillar I CLI.
- **The race-window between YAML write + dispatcher policy-bundle reload remains documented as a limitation** (per ADR-0025 D100). For batched operators a single send to the unsubscribed prospect MAY slip through after the YAML write but before the next bundle load. **Mitigation:** Pillar H SIGHUP closes the window operationally; until then, the batched cadence is the bound (typically <60s for an active operator + within the SLA).
- **The `conversation_status:` Person frontmatter field is new operator-facing surface.** Operators upgrading to Week 4-5 see the field appear on Person notes after `runner.apply()`; their Obsidian view may flag the field as new. **Mitigation:** the vault migration's `is_reversible=True` lets operators downgrade if they don't want the field; the field's purpose is documented in the migration's docstring.
- **The conversation state machine doesn't ship TTL-based `* → dormant` transitions in Week 4-5.** Threads with no activity in N days stay in their last-classified state (or `replied` if never classified). **Mitigation:** Pillar D Week 9-11 (ADR-0029 — TBD) ships the TTL driver; until then operators can manually inspect ledger events for inactive threads.
- **The handler reads the FULL ledger to build the dedup set on every run.** O(events) walk; for a 10K-event ledger sub-second, for a 1M+ ledger linear-growth. **Mitigation:** the cost is the same shape as Pass G's idempotence walk per ADR-0026 D104 + Pillar G observability may surface ledger-size growth as a pre-Pillar-H concern. Per-event-type indexing is the longer-term polish.

### Neutral / observability

- The `suppression_added` events Pass M emits feed Pillar G's CAN-SPAM audit dashboard (every auto-unsubscribe write recorded with timestamp + suppressed_dimension + person_id + matched_pattern via the originating classified event).
- The `conversation_state_changed` events Pass N emits power Pillar G's reply-funnel dashboards (per-channel reply rate + per-state-transition counts + per-Person aggregated status breakdown).
- The funnel CLI's `by_type` breakdown surfaces both new event classes per the existing Pillar D Week 1 audit (`orchestrator/ledger.py::funnel` counts every event type — no closed-set filter).
- The `conversation_status:` Person frontmatter field is queryable via vault grep (`grep "conversation_status: unsubscribed" 10\\ People/*.md`) for operator-facing pipeline-management workflows.
- No new SoT introduced. The auto-unsubscribe writes through to the existing suppression-list YAML SoT (per ADR-0004); the conversation state machine's per-thread states are denormalized from the ledger (the ledger is the SoT); the `conversation_status:` field is a per-Person denormalization of the per-thread states (the per-thread states are the SoT). Pass C's heal extension keeps the field consistent.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. The auto-unsubscribe writes through to `~/.outreach-factory/suppressions/auto-unsubscribe.yml` (a NEW file under the existing suppressions SoT per ADR-0004's directory-union convention). The conversation state machine's per-thread states are denormalized from the ledger; the `conversation_status:` field is a per-Person denormalization of the per-thread states. Pass C heals on each reconcile run.
- **I2 (two-phase commit on every external side effect):** The auto-unsubscribe write IS an external-effect-adjacent operation (the suppression rule's enforcement IS the external effect; the YAML write is the local SoT update). The D116 YAML-first + ledger-second write order is the two-phase analog: YAML write = "intent" (the suppression is live); ledger write = "confirmed" (the audit trail). Reconcile is the recovery surface for asymmetric crashes (per D121 — future Pillar I doctor extension).
- **I3 (schema versioning):** `suppression_added` events carry `v: 1` (existing ledger event versioning). `conversation_state_changed` events carry `v: 1`. The auto-unsubscribe YAML carries the existing `version: 1` (ADR-0004). The `conversation_status:` Person frontmatter field is stamped by vault/0004 + healed by Pass C; the field's value space (`replied | classified | unsubscribed | active | dormant`) is the canonical per ADR-0025 D98 + this ADR D119.
- **I4 (reproducible state):** Every Week 4-5 event class is durable in the append-only ledger; the auto-unsubscribe handler is idempotent per the (reply_message_id, channel) dedup; the conversation state machine is deterministic per the event-driven walk. Replaying the ledger reconstructs the conversation state + the suppression list (per ADR-0004's existing `forget_append` reconstructability).
- **I5 (observable by default):** D116's YAML-first write order, D117's dedup contract, D118's standalone state machine, D119's transition map — all emit structured events with full diagnostic context (matched_pattern via the originating classified event, classification method, channel, person_id, thread_key, from_state, to_state). Pillar G observability has scalar-field queries for every dimension.
- **I6 (tests prove invariants):** D115-D121's deliverables are pinned by `tests/test_auto_unsubscribe.py` (16 unit tests) + `tests/test_conversation_state.py` (18 unit tests) + `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement` (6 un-skipped Week 4-5 rows including the LOAD-BEARING dedup test). The crash-injection test pins the YAML-first invariant.
- **I7 (cost is a first-class concern):** Week 4-5 emits NO `cost_incurred` events (the auto-unsubscribe + state machine are pure framework operations — regex + ledger walks + YAML writes). Pillar D Week 6-8's LLM fallback (ADR-0029 — TBD) is the first cost-bearing Week of Pillar D's full deliverable.
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0028 row. The per-week trajectory in HANDOFF-pillar-d-week-6.md (TBD this commit) names planned ADRs 0029+.

Does not weaken any invariant. I2's enforcement extends to the auto-unsubscribe path (D116's two-phase analog). I5's enforcement extends to the suppression + state-transition events. I6's enforcement extends to the LOAD-BEARING dedup contract.

### Downstream pillar impact

Per the Pillar A / B / C / D Weeks 1-3 convention (every ADR explicitly names cross-pillar impact):

* **Pillar E (discovery quality + lineage).** Pillar E's discovery-pass logic may consume `conversation_state_changed` events to learn discovery-source-to-conversation-outcome correlations (e.g., "prospects discovered via funded-founders source unsubscribe at 5%; competitor-customers source at 2%"). Pillar E's enrollment ADR (TBD) may also gate re-enrollment on `conversation_status: unsubscribed` (don't re-enroll a person who unsubscribed; CAN-SPAM compliance).

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity-after-reply scoring may correlate `conversation_status: active` (the engaged conversations) with the draft's voice-fidelity score for the corpus-curation surface. The per-Person aggregation is the right grain for Pillar F's vault-walk.

* **Pillar G (observability).** Pillar G's reply-funnel dashboard reads `conversation_state_changed` events filtered by `to_state:`; the auto-unsubscribe audit dashboard reads `suppression_added` events. Both event classes carry full diagnostic context (channel, person_id, thread_key, trigger correlation) for scalar-field queries.

* **Pillar H (daemon + dispatcher).** Pillar H's daemon will run Pass M + Pass N alongside the existing passes; the per-channel rate-limit pool considerations don't apply (both passes are pure framework operations — no external API calls). The daemon's SIGHUP-on-classifier-write hook (D116-Alt3's deferral) closes the race-window between YAML write + dispatcher policy-bundle reload.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel auto-unsubscribe YAML isolation. The Pillar I doctor preflight extends to check the auto-unsubscribe YAML existence + schema-conformance + the `conversation_status:` field presence on Person notes. The Pillar I CLI ships:
  - `python -m orchestrator.auto_unsubscribe replay --since <date>` for the one-time backfill of pre-Pillar-D-Week-4-5 classified events against the handler.
  - `python -m orchestrator.conversation_state replay --since <date>` for the one-time emit of `conversation_state_changed` events from historical reply state.
  - A reconcile-pass extension that detects YAML-without-paired-ledger-event inconsistencies + emits a `suppression_remediation` event for operator review (per ADR-0025 D100's failure-mode matrix).

* **Pillar J (security + compliance).** Pillar J's CAN-SPAM compliance gate is now AUTO-SATISFIED by Pillar D's auto-unsubscribe write contract (no manual operator step required for unsubscribe-classified replies). The doctor preflight verifies the classifier + handler are wired; the integration is the operator-facing surface for CAN-SPAM compliance. Pillar J's GDPR-forget transaction inherits the `forget_append` primitive Pillar D also uses; the cross-pillar write contract is unified.

## Migration / rollout

The Week 4-5 deliverable is the auto-unsubscribe handler + conversation state machine + Pass M + Pass N in reconcile + Pass C extension for `conversation_status:` heal + vault migration `vault/0004_add_conversation_status_to_person_notes` + ADR-0028.

**Operator-facing changes (Week 4-5):**

1. **ONE new pending migration.** `runner.pending()` now returns 16 (was 15). The new migration is `vault/0004_add_conversation_status_to_person_notes` (Pillar D Week 4-5 — stamps `conversation_status:` on every Person note from ledger-derived per-thread aggregation per D119).

2. **New CLI flag — `--suppressions-dir <path>`.** Defaults to `~/.outreach-factory/suppressions/`. Useful for: test injection, per-environment overrides.

3. **`--full` now includes Pass M + Pass N.** `python -m orchestrator.reconcile --full` runs `"A,B,C,D,H,E,I,F,J,G,M,N"` (previously `"A,B,C,D,H,E,I,F,J,G"`). Operators using `--full` get auto-unsubscribe + conversation state machine coverage automatically.

4. **Pass C now heals `conversation_status:` alongside `pipeline_stage:`.** Operators running `--full` (or `--passes C`) see `reconcile_healed` events with `field: "conversation_status"` for any Person note whose vault value drifts from the ledger-derived canonical.

5. **New operator bootstrap step (one-time):**

   ```bash
   # The auto-unsubscribe YAML is created automatically on the first
   # Pass M write — no manual bootstrap required. Operators can
   # pre-create the directory to verify permissions:
   mkdir -p ~/.outreach-factory/suppressions

   # Apply the new vault migration to seed the per-Person conversation_status:
   # field from pre-Pillar-D-Week-4-5 ledger state.
   python -m orchestrator.migrations apply
   ```

6. **Existing operators with pre-Pillar-D-Week-4-5 classified events** see the handler retroactively suppress every `category=unsubscribe` event on the next `--full` run. The dedup-by-(reply_message_id, channel) per D117 prevents re-processing. The asymmetric-failure-cost calculus per PILLAR-PLAN §0 favors the retroactive emit (the classifier's visibility-now is better than visibility-from-Week-4-5-onward-only).

**Operator-facing changes (Pillar D Weeks 6-12, planned):**

7. **Week 6-8 ships the LLM fallback** for the long-tail categories per ADR-0029 (TBD). The unsubscribe path stays rule-based ONLY per ADR-0025 D97 + this ADR D115. The LLM is consulted only for `category in {ooo, wrong_person, interest, rejection, uncategorized}`.

8. **Weeks 9-11 ship win/loss attribution** + the `conversation_outcome` event class. The conversation state machine gains terminal transitions (`active → won` / `active → lost`) driven by operator-deliberate signals.

9. **Week 12 is the exit-gate close.** The binding 100-message synthetic inbox classifier benchmark un-skips per ADR-0025 D101.

**The Week 4-5 commit's verification surface:**

```bash
# 1. The handler module exists + is importable.
python -c "from orchestrator import auto_unsubscribe; from orchestrator import conversation_state"

# 2. The auto-unsubscribe handler's unit tests pass.
python -m pytest tests/test_auto_unsubscribe.py -v
# Expected: 16 passing.

# 3. The conversation state machine's unit tests pass.
python -m pytest tests/test_conversation_state.py -v
# Expected: 18 passing.

# 4. The coherence vehicle's Week 4-5 rows un-skip + pass.
python -m pytest tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement -v
# Expected: 6 passing (including the dedup + YAML-first + 60s SLA + engine-integration + correlation-key + the LOAD-BEARING dedup rows).

# 5. Pass M + Pass N run under reconcile.
python -m orchestrator.reconcile --passes M,N --apply --suppressions-dir /tmp/test-sups
# Expected: Pass M: examined=<n>, by_type={suppression_added: <m>}; Pass N: examined=<k>, by_type={conversation_state_changed: <j>}.

# 6. The full suite is green.
python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 2162 passing (2123 Week 3 baseline + ~39 net new tests).

# 7. ADR-0028 exists; README index gains the row; PILLAR-PLAN §6 Pillar D row updated.
ls docs/adr/0028-pillar-d-auto-unsubscribe-and-conversation-state.md
grep "0028" docs/adr/README.md
grep "Week 4-5 ✓" docs/PILLAR-PLAN.md

# 8. Pending migration count moves from 15 to 16.
python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print('pending:', len(r.pending()))"
# Expected: pending: 16
```

### Existing-operator seed

Pillar D Week 4-5 ships ONE new vault migration (`vault/0004_add_conversation_status_to_person_notes`) that requires an existing-operator seed. The migration walks every Person note + computes `derived_conversation_status` from the ledger; for Person notes with no derivable status (no conversation events for the person_id), the field is NOT stamped (absent field = "no conversation yet"). Pass C heals on subsequent reconcile runs.

**Bootstrap-step seed for existing operators (Yang):**

```bash
# One-time vault migration apply.
python -m orchestrator.migrations apply

# First Pass M + N run — auto-suppresses any pre-existing
# category=unsubscribe classified events + emits the conversation
# state transitions:
python -m orchestrator.reconcile --passes M,N --apply

# Verify:
python -m orchestrator.ledger grep --type suppression_added | head
python -m orchestrator.ledger grep --type conversation_state_changed | head
cat ~/.outreach-factory/suppressions/auto-unsubscribe.yml
```

For Yang specifically (the current sole operator), the pre-Pillar-D-Week-4-5 classified event count is small (Pillar D Week 2-3 has only emitted in recent reconcile runs). The first Pass M run handles all existing unsubscribe classifications in one go; the first Pass N run computes the per-thread states + emits transitions retroactively. The `conversation_status:` Person frontmatter field lands on the next migration apply OR the next Pass C run, whichever comes first.

The next Pillar D week that ships a migration requiring an existing-operator seed is Week 6-8 (the LLM-fallback classifier-cap policy migration — TBD per ADR-0029); that ADR carries the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface Pillar D Week 4-5's auto-unsubscribe handler integrates with via the existing `SuppressEmailRule` / `SuppressDomainRule` / `SuppressIdentityKeyRule` from ADR-0004; no engine change required.
- ADR-0003 (channel as first-class policy predicate) — the cross-channel rule whose behavior Pillar D Week 4-5 events deliberately don't trigger (`suppression_added` + `conversation_state_changed` don't end in `_confirmed`).
- ADR-0004 (suppression rules + GDPR-forget) — the `forget_append` primitive Pillar D Week 4-5's handler reuses; the directory-merge semantics that union `auto-unsubscribe.yml` with `gdpr-forget.yml` at gate-evaluation time; the suppression rule contract Pillar D inherits unchanged.
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention Pillar D Week 6-8's LLM fallback will emit against (the `reply_classifier_llm` source name reserved in ADR-0025 §I7).
- ADR-0009 (migration framework) — Pillar D vault migrations (Week 4-5 ships vault/0004) register into the existing framework.
- ADR-0010 (ledger migrations) — Pillar D `migration_event` audit-trail emissions follow the D35 `channel=` kwarg convention (inherited from Pillar C); Week 4-5 emits one migration event for vault/0004.
- ADR-0011 (vault migrations) — Pillar D vault migrations (Week 4-5 ships vault/0004) consume the existing `iter_person_notes` + `add_frontmatter_field_text` primitives.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — the D27 cross-category-ordering contract vault/0004 inherits; the D24 fixture-builder pattern Week 4-5's existing-operator seed extends.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-two-phase-event invariant extended by ADR-0025 D96 to reply events + extended again by this ADR's D121 to suppression + conversation-state events.
- ADR-0017 (Pillar C reconcile passes D + E) — the D48 + D50 asymmetric-failure-cost calculus Pillar D's auto-unsubscribe handler inherits.
- ADR-0025 (Pillar D foundation) — D96 (per-channel reply event-type naming) + D97 (classifier output convention + load-bearing legal-liability invariant) + D98 (conversation state shape — this ADR D119 fills in transitions) + D99 (cross-pillar audit — this ADR D121 extends) + D100 (auto-unsubscribe enforcement contract — this ADR D116-D117 implement) + D101 (exit-criterion vehicle scope — this ADR un-skips 6 Week 4-5 rows).
- ADR-0026 (Pillar D Week 2 classifier bootstrap) — D102 (classifier module placement — this ADR D115 follows the sibling pattern) + D104 (idempotence pair — this ADR D117 carry-forward) + D107 (Week 4-5 handler deferral — this ADR fulfills).
- ADR-0027 (Pillar D Week 3 long-tail + per-channel reply detection) — D108-D110 (classifier extension) + D111 (Pass H/I/J) + D112 (REPLY_EVENT_TYPES closed-set) + D113 (Pass K deferral — this ADR D120 reserves the slot).
- `docs/PILLAR-PLAN.md` §2 Pillar D — exit criterion (the 60-second SLA + the 100-message benchmark); §5 "What we will not do" — the unsubscribe = rule-based ONLY constraint D115-D117 preserve; §6 Pillar D row updated to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4-5 ✓".
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D116's YAML-first order + D117's dedup contract + D119's priority ordering.
- `docs/RISK-REGISTER.md` R010 (Regulatory shift) — risk Pillar D mitigates by design via the auto-unsubscribe enforcement contract; Week 4-5 lands the production surface. R012 (LLM hallucinates unsubscribe) — continues mitigated by ADR-0025 D97 + ADR-0026's source-level invariant. R013 (operator pattern-list misconfiguration) — continues mitigated. R015 (asymmetric-crash inconsistency between YAML + ledger — NEW, added in this commit) — mitigated by D116's YAML-first order + the deferred Pillar I reconcile-detection surface.
- `docs/SOURCES-OF-TRUTH.md` — existing rows for "Suppression list" (Pillar D Week 4-5 writes through) + "Send-history" (unchanged). The `conversation_status:` Person frontmatter field is a denormalized view of the ledger-derived per-thread states; no new SoT row required (Person notes are existing vault SoT per Phase 5.5).
- `.planning/RETRO-pillar-c.md` §"What to do differently in Pillar D" items 1-3 — the carry-forward recommendations this ADR's structure implements.
- `.planning/REVIEW-pillar-d-surface-audit.md` — the D99 audit document; this ADR's D121 extends with the new event classes + Pass M + N walk patterns + the YAML-first write contract.
- `.planning/HANDOFF-pillar-d-week-4.md` — the per-week handoff that scoped Week 4-5.
- `.planning/HANDOFF-pillar-d-week-6.md` — written in this commit; scopes Week 6-8 (LLM fallback for long-tail categories + classifier-cap policy migration).
- `orchestrator/auto_unsubscribe.py` — the handler module D115 names.
- `orchestrator/conversation_state.py` — the state machine module D118 names.
- `orchestrator/reconcile.py::run_pass_m`, `::run_pass_n`, `::run_pass_c` (extended) — the pass dispatchers D120 + D119 names.
- `orchestrator/migrations/vault/migration_0004_add_conversation_status_to_person_notes.py` — the vault migration D119 names.
- `tests/test_auto_unsubscribe.py` — the handler's 16 unit tests.
- `tests/test_conversation_state.py` — the state machine's 18 unit tests.
- `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement` — 6 un-skipped Week 4-5 rows including the LOAD-BEARING dedup.
- Forward-references (planned):
  - **ADR-0029** (Pillar D Week 6-8): LLM fallback for the long-tail categories + classifier-cap policy migration (`policy/0007_add_reply_classifier_llm_cap` — TBD shape).
  - **ADR-0030+** (Pillar D Week 9-11): win/loss attribution; conversation_outcome event; reply-funnel observability surface; TTL-based `* → dormant` transition.
  - **ADR-00NN** (Pillar D Week 12): exit-gate close — the binding 100-message synthetic inbox classifier benchmark un-skips.
  - **Pillar H SIGHUP** (Weeks 37-48): the live-reload hook for the auto-unsubscribe YAML (closes the D100 race-window).
  - **Pillar I CLI** (Weeks 43-48): the auto-unsubscribe replay command + the conversation-state replay command + the doctor preflight extension + the reconcile-detection pass for asymmetric-crash inconsistencies.
