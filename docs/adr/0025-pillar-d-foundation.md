# ADR-0025: Pillar D foundation — reply event-type naming, classifier output convention, conversation state shape, cross-pillar integration audit, auto-unsubscribe enforcement contract, exit-criterion vehicle scope

- **Status:** Accepted
- **Date:** 2026-05-23
- **Pillar:** D (Reply + conversation handling — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0008 shipped Pillar A (declarative policy engine). ADRs 0009-0013 shipped Pillar B (migration framework + synthetic-replay exit vehicle). ADRs 0014-0024 shipped Pillar C (multi-channel coherence — four channels, six reconcile passes, five per-channel policy migrations, the cross-channel rule activated end-to-end). Pillar D — reply + conversation handling (`docs/PILLAR-PLAN.md` §2 Pillar D, Weeks 13–24) — extends the substrate again: every reply that lands in any of the four channels must be CLASSIFIED, ATTRIBUTED to a conversation-state machine, and (for the legal-liability subset — unsubscribe) AUTO-ENFORCED into the suppression list. The substrate is in place; what Pillar D Week 1 needs is the **convention-setting decisions** the next eleven weeks build on.

Pillar C's Week 12 retrospective (`.planning/RETRO-pillar-c.md` §"What to do differently in Pillar D") named the THREE highest-leverage Pillar C → Pillar D recommendations: (1) land the Pillar D reply-correlator integration test in Week 1, not Week N (Pillar C Week 12's exit-criterion stress test caught a Pass A latent bug 8 weeks after introduction); (2) audit existing surfaces for symmetric assumptions when extending Pillar A/B/C primitives (the Pass A bug was a pre-existing surface that Pillar C's broader index population silently broadened); (3) inherit the per-week-handoff + per-week-review-with-follow-up-commit + per-ADR ≥3 rejected alternatives + §Downstream pillar impact + holistic-exit-review discipline.

The seven concerns this ADR resolves:

1. **Reply event-type names must be pinned across all four channels before the first classifier ships.** Email reply events (`reply_received`, `bounce_detected`) already exist from Phase 5.5 Pass B. Pillar D extends per-channel reply detection in Weeks 2+ (LinkedIn inbox, Twitter DM inbox); the event-type prefix MUST be decided before the per-channel passes ship. D96 pins the names.

2. **The classifier's output is a SEPARATE event class — not an annotation on the reply event itself.** The append-only ledger discipline (per ADR-0011 D24) means rewriting events is forbidden; the classifier's output must land as a sibling event correlated by `reply_message_id` + `channel`. D97 pins the contract + the load-bearing legal-liability constraint (PILLAR-PLAN §5: "unsubscribe is rule-based ONLY — no LLM in the legal-liability path").

3. **The conversation state machine is DISTINCT from the send-state machine.** The send-state machine (`derived_stage`'s `queued → researched → drafted → ready → sent`) is per-person. The conversation-state machine (`replied → classified → unsubscribed | dormant | active`) is per-thread. The two states are independent — a Person can have multiple conversation threads (one per channel, sometimes more) and the send-state advances only on outbound action, while the conversation-state advances on inbound classification. D98 pins the two state machines as DISTINCT + names how Pillar D's events interact with the existing `derived_stage` surface.

4. **Cross-pillar integration audit — the load-bearing anti-regression decision.** Per Pillar C Week 12's surfaced Pass A bug (RETRO-pillar-c.md §"What surprised" #1), every Pillar D week's per-week review MUST audit existing Pillar A/B/C surfaces for symmetric assumptions when Pillar D's commit silently expands the input space. The Week 1 audit (`.planning/REVIEW-pillar-d-surface-audit.md`) covers every existing surface; D99 pins the audit as the surface map. Future Pillar D weeks extend the audit row-by-row.

5. **Auto-unsubscribe enforcement contract.** The classifier's `unsubscribe` classification triggers a write to the suppression list within 60 seconds (PILLAR-PLAN §2 Pillar D exit criterion). The legal-liability path (CAN-SPAM compliance) is rule-based ONLY — D97's invariant is reinforced here. D100 pins the contract: `reply_classified` (with `category: unsubscribe`) + `suppression_added` are appended in the same atomic ledger batch + the suppression YAML is updated FIRST so the suppression is live even if the ledger events are mid-write; on the next dispatch the existing Pillar A `SuppressEmailRule` / `SuppressDomainRule` / `SuppressIdentityKeyRule` (ADR-0004) refuses; the suppression rule contract is UNCHANGED. The contract names the failure modes the auto-unsubscribe handler must defend against (LLM-hallucinated classification of unsubscribe; classifier-misclassifies-as-unsubscribe; race between reply detection and dispatch; suppression-list-update-fails).

6. **The Pillar D exit-criterion verification vehicle must exist in Week 1.** Per PILLAR-PLAN §2 Pillar D exit criterion: *"100-message synthetic inbox classifier benchmark with documented rule precision/recall; suppression updates idempotent; attribution funnel reproducible."* Without the vehicle landing in Week 1, the cross-cutting properties (classifier accuracy across categories; suppression idempotence under race; attribution-funnel reconstructability) would only surface end-of-pillar, repeating Pillar B Week 5 + Pillar C Week 12's pattern. D101 names the vehicle scope: `tests/test_multi_channel_coherence.py` is EXTENDED with `TestReplyClassification` + `TestUnsubscribeEnforcement` + `TestPillarDExitCriterion` test classes (Option A from the Week 1 handoff's design-decision menu) per the precedent ADR-0014 D37 established. Per-week deliverables un-skip rows; the binding `TestPillarDExitCriterion.test_100_message_synthetic_inbox_classifier_benchmark` gates Pillar D's "stable" flip at the end of the pillar.

7. **Pre-existing email-reply emit-site (Pass B) must be brought into the channel-on-every-event invariant.** The audit (D99) surfaced P2-A: Pass B's emitted `reply_received` + `bounce_detected` events do NOT carry `channel: email`. This Week 1 commit fixes the omission (one line per emit + regression tests) — mirrors Pillar C Week 1's ADR-0014 D33 §"Backfill `send_confirmed` carries `channel`" fix pattern. The Week 1 fix is named here so future Pillar D weeks' per-week reviewers see the precedent.

Risks this ADR mitigates by design: **R011 (cross-channel double-engagement)** continues mitigated by ADR-0003; Pillar D's reply-state additions do NOT change the cross-channel rule's behavior (the rule predicates on `*_confirmed` events only — replies don't match). **R010 (Regulatory shift)** — CAN-SPAM / GDPR enforcement — gains its first auto-write contract (D100); operator's compliance posture improves from "manual append to suppressions.yml on unsubscribe" to "60-second SLA classifier-write".

A new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`: **R012 (LLM hallucinates unsubscribe → over-suppression)** — the classifier's `category: unsubscribe` decision is irreversible (suppression is a kill switch per ADR-0004). D97's "unsubscribe = rule-based ONLY" invariant + the regression test `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_unsubscribe_classification_method_is_always_rule` defends.

## Decision

### D96. Per-channel reply event-type naming convention

Pillar D ships per-channel reply event types matching the ADR-0014 D33 prefix convention (`<channel>_<action>_<lifecycle>`):

| Channel | Reply event | Bounce/undeliverable event | Notes |
|---|---|---|---|
| Email (existing — Phase 5.5 Pass B) | `reply_received` | `bounce_detected` | Pre-existing names. Pillar D's Week 1 P2-A fix extends them with `channel: "email"`. |
| LinkedIn invite (Pillar D Week 2+) | `li_invite_reply_received` | *(none — LinkedIn invites don't bounce; the recipient either accepts, ignores, or declines)* | Per-channel reply pass (TBD; Week 2-3) detects accepted-invite + reply-via-DM-on-same-thread. |
| LinkedIn DM (Pillar D Week 2+) | `li_dm_reply_received` | *(none — same)* | Per-channel reply pass scrapes inbox via `mcp__linkedin__get_conversation`. |
| Twitter DM (Pillar D Week 2+) | `tw_dm_reply_received` | *(none — same)* | Per-channel reply pass scrapes inbox via `mcp__linkedin__*` analog. |
| Calendar booking (Pillar D Week 2+) | `calendar_booking_reply_received` | *(none — calendar replies are bookings or cancellations, distinct event classes)* | The Cal.com webhook handler (ADR-0019) emits `calendar_booking_confirmed` for the booking; a reply-style touch from the recipient that isn't a booking lands as a `calendar_booking_reply_received` if the channel has a comment surface (Cal.com does; v1 of the handler doesn't consume yet). |

**Channel field on every reply event.** Every reply / bounce event MUST carry a top-level `channel: <value>` field. The classifier (D97) discriminates per-channel. The pre-Pillar-D-Week-1 Phase 5.5 Pass B emit-site is fixed in this commit (P2-A in `.planning/REVIEW-pillar-d-surface-audit.md`); future Pillar D weeks' per-channel reply passes inherit the invariant.

**Per-channel reply correlation field.** Every reply event MUST also carry a `reply_to_intent_id: <value>` field correlating back to the originating `*_intent` event. The correlation is the Pillar D analog of Pass B's gmail_thread_id correlation but is intent-scoped (not thread-scoped) — the classifier joins reply → intent → person + channel directly. For Pass B's pre-existing email-reply emits, the correlation is via `gmail_thread_id` → `send_confirmed.gmail_thread_id` → `send_confirmed.intent_id` (an indirect join Pillar D Week 2's classifier handles). New per-channel reply events (Week 2+) carry `reply_to_intent_id` directly because LinkedIn / Twitter / calendar don't have an email-style thread surface that the existing primitives query.

**Distinct event class for bounces (email-only).** `bounce_detected` is a distinct event class because the legal/operational handling differs from reply: a bounce indicates the address is invalid (deliverability concern + verification cache invalidation), not a recipient action. Pillar D's classifier treats `bounce_detected` as a separate category in the conversation-state machine (the conversation never started; `dormant` is the right end-state). The classifier reads `bounce_detected` events but does NOT emit `reply_classified` for them (per D97).

### D97. Classifier output convention — separate event class + load-bearing legal-liability invariant

The classifier (Pillar D Week 2-3 implementation) emits a SEPARATE `reply_classified` event class for every reply event it processes:

```python
{
    "type": "reply_classified",
    "person_id": "<pid>",
    "channel": "email | linkedin | twitter | calendar",
    "reply_message_id": "<gmail_message_id | linkedin_message_id | ...>",
    "reply_to_intent_id": "<intent_id of the originating *_intent>",  # may be None for email replies from Pass B (pre-Week-1 emits)
    "category": "unsubscribe | ooo | wrong_person | interest | rejection | uncategorized",
    "classification_method": "rule | llm",
    "confidence": 1.0,  # rule = 1.0; llm = 0.0-1.0 from the LLM
    "matched_pattern": "<the regex / keyword that matched, OR null for LLM>",
    "_emitted_by": "reply_classifier",  # observability marker per ADR-0010 convention
}
```

**Separate event class (rejected: annotate the reply event itself).** Two reasonable shapes: (a) emit a SEPARATE `reply_classified` event linked to the originating reply by `reply_message_id` + `channel`; (b) annotate the reply event with classification fields (one event per reply). Pillar D Week 1 picks (a). The rationale:

* **Append-only ledger discipline.** Pillar B's ledger primitive (ADR-0011 D24) is append-only; rewriting events is forbidden by construction. Annotating a reply event would require either rewriting (forbidden) or a sibling "annotation" event that's structurally identical to the separate-event approach.
* **Classifier rerun.** The classifier is expected to evolve (rule list refinement; LLM fallback model updates; new categories). A separate `reply_classified` event lets the classifier rerun against historical reply events without churning the original `*_reply_received` events. The operator can `python -m orchestrator.classify --rerun-since 30d` and the existing `reply_received` events stay as-is + new `reply_classified` events land.
* **Queryability.** "Show me every email reply that was classified as unsubscribe" is one query (`type == "reply_classified" AND category == "unsubscribe" AND channel == "email"`). With annotated reply events, the same query reads less naturally + requires filtering on a nullable `classification:` sub-object.

**`unsubscribe` MUST be classified by rule, not LLM (load-bearing legal-liability invariant).** Per PILLAR-PLAN §5: *"No LLM-first reply classification. Unsubscribe is rule-based ONLY — no LLM in the legal-liability path."* The contract:

* Every `reply_classified` event with `category: "unsubscribe"` MUST carry `classification_method: "rule"` AND `confidence: 1.0`.
* The LLM fallback (Pillar D Week 6-8 implementation) is consulted ONLY for the long-tail categories (ooo / wrong_person / interest / rejection / uncategorized). The unsubscribe path is NEVER consulted via the LLM, even as a tiebreaker.
* The rule list (regex + keyword lists for unsubscribe patterns) is operator-tunable per `~/.outreach-factory/classifier/unsubscribe-patterns.yml` (TBD shape; Pillar D Week 2-3 ships).

**Pin:** `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_unsubscribe_classification_method_is_always_rule` asserts that every `reply_classified` event with `category: "unsubscribe"` has `classification_method == "rule"`. A future contributor adding an LLM fallback to the unsubscribe path would fail this test loudly. **The test stub lands in this Week 1 commit + un-skips when the classifier ships in Week 2-3.**

**Confidence scoring convention.** Rule matches always carry `confidence: 1.0` (deterministic regex / keyword match — either it matched or it didn't). LLM matches carry `confidence: 0.0-1.0` from the model's logprob (calibration TBD; Pillar D Week 6-8). The classifier's `reply_classified` event drives Pillar G's classifier-precision/recall dashboard.

### D98. Conversation state shape — distinct from the send-state machine

The conversation state machine is **per-thread** (one state machine per `gmail_thread_id` for email; per LinkedIn DM thread; per Twitter DM thread; per calendar booking flow). The send state machine (`derived_stage` per ADR-0011 + ledger.py:649) is **per-person**. The two are independent:

| State machine | Scope | Source events | Stages |
|---|---|---|---|
| Send-state (existing) | Per-person | `enrolled` / `research_complete` / `draft_complete` / `review_approved` / `*_confirmed` / `state_transition` / `review_rejected` / `draft_rejected` | `queued → researched → drafted → ready → sent` |
| Conversation-state (Pillar D Week 4-5+) | Per-thread | `*_reply_received` / `reply_classified` / `bounce_detected` / `suppression_added` / `conversation_state_changed` | `replied → classified → (unsubscribed | dormant | active)` — actual stage names TBD per Week 4-5+ implementation |

**Pillar D's `derived_stage` interaction (P3-A in the audit).** Pillar D Week 1 does NOT extend `_STAGE_BY_EVENT_TYPE` (the send-state machine's dispatch table). The send-state machine continues to advance on outbound actions only; reply events do not change `derived_stage` output.

**Future-week consideration.** If a future Pillar D week decides to advance the send-state machine on `reply_received` (e.g., `sent → contacted` once any reply lands), it must amend `_STAGE_BY_EVENT_TYPE` + ship a regression test in `tests/test_ledger.py::TestDerivedStage`. The audit (`.planning/REVIEW-pillar-d-surface-audit.md` §P3-A) names this boundary explicitly so the future amendment is loud at review time.

**Conversation-state-transition events** carry the channel-on-every-event invariant per D33-extended-by-D96:

```python
{
    "type": "conversation_state_changed",
    "person_id": "<pid>",
    "channel": "email | linkedin | twitter | calendar",
    "thread_key": "<gmail_thread_id | linkedin_thread_id | tw_dm_thread_id | calendar_booking_intent_id>",
    "from_state": "replied",
    "to_state": "classified",
    "trigger_event_id": "<reply_classified event's id or a synthesized marker>",
    "_emitted_by": "conversation_state_machine",
}
```

The thread-key field discriminates per-thread (a person with multiple email threads + a LinkedIn DM thread + a calendar booking has FOUR independent conversation state machines). Future Pillar D week implementation pins the thread-key shape per channel.

### D99. Cross-pillar integration audit — load-bearing surface map

`.planning/REVIEW-pillar-d-surface-audit.md` (this commit) is the surface map. The audit walks every existing Pillar A / B / C surface that touches ledger events; verifies each is either closed-set protected or literal-string filtered against Pillar D's new event classes. The audit's verdict: **no P1 latent-bug pattern; one P2 (Pass B `channel: email` omission — fixed in this commit) + one P3 (`derived_stage` boundary — documentation-only).**

**The audit IS the contract.** Future Pillar D weeks' per-week reviewers consult the audit as the surface map; new code added in Week N+ that touches a ledger index or a query method extends the audit with a new row. The discipline mirrors Pillar B + C's per-week-review pattern + carries forward the Pillar C Week 12 retrospective's "audit existing surfaces" recommendation.

**Pin:** the audit document is referenced from this ADR + every subsequent Pillar D ADR's §References. Pillar D Week N's per-week reviewer's checklist (per HANDOFF-pillar-d-week-N.md §"Validation gate") includes "the surface audit was extended (or confirmed unchanged) by this week's commit."

**Categories the audit pins for future Pillar D week reviewers** (extracted from §"Categories the Pillar D Week N per-week reviewer must keep auditing"):

1. Does the week's commit broaden `_idx_person` (any event with `person_id`) in a way pre-Week-N consumers don't expect?
2. Does the week's commit add a new `*_confirmed`-suffixed event (would silently activate `CrossChannelTouchRule`)?
3. Does the week's commit add to `_STAGE_BY_EVENT_TYPE` (extends `derived_stage`)?
4. Does the week's commit add a new per-channel reply-message-id index analogous to `_idx_gmail_msg`?
5. Does the week's commit modify Pass B (the email reply pass) or any pre-existing reconcile pass?

### D100. Auto-unsubscribe enforcement contract (CAN-SPAM compliance)

The classifier's `unsubscribe` classification triggers a write to the suppression list within 60 seconds. The atomic write contract:

**Write order (load-bearing):**

1. **YAML first.** The classifier appends the email / domain / identity_key to `~/.outreach-factory/suppressions/auto-unsubscribe.yml` (a new factory file Pillar D Week 4-5+ introduces; per ADR-0004's directory-merge convention the file unions with `gdpr-forget.yml` + operator-curated files) via the existing `suppression.forget_append` primitive (ADR-0004). The append is atomic at the file level (write-temp-then-rename per `forget_append`'s contract). After this write returns, the suppression is LIVE — any dispatcher that runs `policy.load_suppression_dir(...)` on its next gate call will refuse the next send to this prospect.
2. **Ledger second.** The classifier appends two events to the ledger in a single batched call (per Pillar B's `ledger.append_batch` primitive — TBD; Pillar D Week 2-3 ships if not already present): `reply_classified` (with `category: "unsubscribe"`) AND `suppression_added` (with the YAML write's outcome). The two-event batched append is atomic at the file level (the ledger's `O_APPEND + fcntl.lockf` discipline batches both lines in one syscall).

**Why YAML first.** If the YAML write succeeds + the ledger write fails (process crash, disk full), the suppression is LIVE despite the ledger lacking the audit trail. The next gate call refuses; the operator's compliance posture is preserved. The ledger reconcile-pass H (TBD; Pillar D Week 4-5+) detects YAML entries without a paired `suppression_added` event and emits one retroactively (the asymmetric-failure-cost calculus: false-positive suppression is one missed conversation; false-negative is a CAN-SPAM violation).

**Why ledger-after.** If the YAML write fails + the ledger write succeeds, the audit trail records the intent but the suppression isn't live → the next send could reach the unsubscribed prospect. This is the failure mode the YAML-first order prevents. The reconcile pass H also detects this (ledger events without a paired YAML entry) and emits a `suppression_remediation` event prompting the operator's attention.

**60-second SLA.** The classifier writes synchronously (no background queue) per the PILLAR-PLAN §2 Pillar D binding text. For batched operators (`python -m skills.send-outreach.scripts.send_queued` run in batches), the suppression update applies on the next batch's first gate call. For the Pillar H daemon (future), SIGHUP-on-classification triggers the engine's live-reload + the suppression update applies within seconds of classification.

**`suppression_added` event shape:**

```python
{
    "type": "suppression_added",
    "person_id": "<pid>",
    "channel": "email | linkedin | twitter | calendar",
    "suppressed_dimension": "email | domain | identity_key",
    "suppressed_value": "<the email/domain/identity_key written to YAML>",
    "source_reply_classified_event": "<the paired reply_classified event's hash or correlation key>",
    "yaml_file": "~/.outreach-factory/suppressions/auto-unsubscribe.yml",
    "_emitted_by": "auto_unsubscribe_handler",
}
```

**Failure modes the contract defends against:**

| Failure mode | Defense |
|---|---|
| LLM hallucinates `unsubscribe` classification | D97's invariant: unsubscribe = rule-based ONLY. The LLM is NEVER consulted for unsubscribe. Regression test pins. |
| Classifier rule misclassifies (false-positive unsubscribe) | The rule list is operator-tunable. Pillar D Week 2-3 ships a `unsubscribe-patterns.example.yml` with conservative defaults; operators tune. A false-positive suppression is one missed conversation (per asymmetric-failure-cost — the safer side). |
| Classifier rule misses real unsubscribe (false-negative) | Manual operator backstop: `policy.py forget --person <id>` (Pillar A ADR-0004's existing surface) catches the long tail. Pillar D Week 6-8's LLM fallback expands the classifier's coverage for non-unsubscribe categories; the unsubscribe rule list stays operator-curated. |
| Race between reply detection + dispatch | The dispatcher's gate is the single arbiter; the suppression update is live on YAML write (step 1 above). The dispatcher MAY have already loaded the policy bundle before the YAML write; the next gate call after the YAML write picks up the new suppression. For batch operators, the worst-case race is one already-loaded-bundle batch — i.e., one send to the unsubscribed prospect can slip through if the classifier writes the YAML mid-batch. **Pillar D Week 4-5+ MUST surface this race as a documented limitation + ship a Pillar H SIGHUP-on-classifier-write hook for the daemon case.** Tracking in HANDOFF-pillar-d-week-2.md. |
| Suppression-list-update fails | `forget_append` raises on file-level failure (disk full, permission). The classifier propagates the exception → the `reply_classified` event does NOT land + `suppression_added` does NOT land → the operator sees the failure in their dispatcher logs. The reconcile pass H surfaces the inconsistency on next run. |

**Pin:** `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement` (the stub class added in this Week 1 commit) carries the regression tests as the classifier + handler implementation lands in Pillar D Weeks 2-5. The stubs land in Week 1 + un-skip incrementally.

**Existing suppression-rule contract held (Pillar A ADR-0004 + ADR-0025).** Pillar D's auto-unsubscribe writes to the same suppression-list YAML files that `SuppressEmailRule` / `SuppressDomainRule` / `SuppressIdentityKeyRule` read. No engine change required; the suppression-rule contract is UNCHANGED.

### D101. Pillar D exit-criterion vehicle scope

`tests/test_multi_channel_coherence.py` is the Pillar D exit-criterion verification vehicle (extended from the Pillar C vehicle per ADR-0014 D37). The file gains three new test classes in this Week 1 commit:

* **`TestReplyClassification`** — per-channel reply-event coherence (channel-on-every-reply-event invariant; reply-to-intent correlation; classifier output convention). All test rows skip in Week 1 with `Pillar D Week N delivers` messages. Email-baseline rows un-skip in Week 1 once Pass B's P2-A fix is verified.

* **`TestUnsubscribeEnforcement`** — auto-unsubscribe contract (the YAML-first write order; the 60-second SLA; the load-bearing `classification_method == "rule"` invariant; the suppression-rule integration). All test rows skip in Week 1 with `Pillar D Week 4-5 delivers` messages.

* **`TestPillarDExitCriterion`** — the binding exit-criterion test. One method: `test_100_message_synthetic_inbox_classifier_benchmark` per PILLAR-PLAN §2 Pillar D's binding text. Skipped in Week 1; un-skips at the final Pillar D week (Week 12 — Week 24 of the program; see HANDOFF-pillar-d-week-1.md per-week trajectory).

**The Option-A choice (extend the existing file) over Option B (new file).** Pillar C's exit-criterion vehicle (ADR-0014 D37) explicitly chose the single-file shape; Pillar D inherits the rationale:

* The vehicle's load-bearing property is cross-pillar coherence visible from Week 1 in ONE place per-week reviewers consult.
* Splitting Pillar D into a separate `tests/test_pillar_d_reply_coherence.py` would create the "look in two places" mental model ADR-0014 D37 §Decision rejected.
* File growth (the test file is ~2746 lines post-Pillar-C-Week-12) is a real concern (Pillar C Week 12 P3-A); Pillar D Week 1's extension adds ~150-300 lines of stubs. If the file crosses ~4000 lines the split argument resurfaces — TBD per the per-week reviewer's call in a future Pillar D week.

**Reusing the Pillar C 50-prospect fixture (`synthetic_pillar_c_stress_state_dir`).** The Pillar C Week 12 fixture is reusable for Pillar D's binding exit-criterion test. Per HANDOFF-pillar-d-week-1.md §"Categories to watch in Pillar D Week 1 per-week review" the fixture key-naming will need extension when Pillar D adds reply substrate (per-prospect `replies:` list of synthetic inbound messages with category labels). **The fixture extension is a Pillar D Week 4-5+ deliverable**, not Week 1. Week 1's binding test stub references the fixture without requiring it to be extended yet.

## Alternatives considered

### D96-Alt1: Uniform `reply_received` event-type for every channel + use `channel:` field to discriminate

A single event type `reply_received` for every channel; consumers discriminate via the `channel:` field. **Rejected** because:

* Naming would diverge from the existing email shape (`send_intent` → `send_confirmed` → `reply_received` is the email family; the per-channel symmetric extension is `li_invite_intent` → `li_invite_confirmed` → `li_invite_reply_received`).
* ADR-0014 D33 explicitly chose per-channel-prefix naming for the two-phase send family; the same rationale carries to the reply family. Diverging would create the cognitive load of "two naming conventions in one codebase."
* The per-channel reply pass naming `run_pass_h_li_invite_replies` etc. would lose the convention "Pass D reads `li_invite_*` events; Pass E reads `li_dm_*`; the analog Pass-H-i / Pass-H-j reads `li_*_reply_received`."

### D96-Alt2: Single `inbound_message` event-type discriminated by `direction: bounce | reply | classification | suppression`

Collapse every inbound classification into one event type with a `direction:` field. **Rejected** because:

* Conflates structurally distinct events (bounce = no recipient action; reply = recipient action; classification = framework-side decision; suppression = framework-side action). Each has different downstream consumers + different semantic weight.
* Query-by-type would require `type == "inbound_message" AND direction == "reply"` everywhere — verbose vs the `type == "reply_received"` direct match.
* The append-only ledger's queryability suffers (no index on `direction:`); operators would have to consult two fields to filter.

### D96-Alt3: Defer per-channel reply event-type naming to Pillar D Week 2 (when the first per-channel pass ships)

The naming can land at the implementation site rather than in the foundation ADR. **Rejected** explicitly per the Pillar C Week 12 retrospective's "audit existing surfaces" lesson. The cross-pillar surface audit (D99) requires concrete event-type names to verify which existing surfaces broaden; deferring the names defers the audit. Pillar C Week 1 ADR-0014 D33 set the precedent — names land in the foundation week so the audit can run.

### D97-Alt1: Annotate the reply event with classification fields (one event per reply)

Add classification fields directly to the `reply_received` event when the classifier lands. **Rejected** because:

* Violates Pillar B's append-only ledger discipline (ADR-0011 D24). The reply event already exists when the classifier runs; modifying it would require rewriting.
* A sibling "annotation" event would be structurally identical to the separate-event approach (different name, same data shape) without the rerun-against-history affordance.
* Pillar G's classifier-precision/recall dashboard needs to query "every classifier output in window N" — much simpler against a typed `reply_classified` event than against a nullable annotation on `reply_received`.

### D97-Alt2: Allow LLM fallback on unsubscribe with `confidence > 0.95` threshold

The classifier's unsubscribe rule list might miss some patterns; an LLM fallback gated on high confidence (>0.95) would extend coverage. **Rejected** with high prejudice because:

* PILLAR-PLAN §5 explicitly forbids LLM in the legal-liability path. The constraint is a load-bearing program-level decision, not a Pillar D implementation detail.
* LLM confidence calibration is poorly understood; a 0.95-threshold suppression decision is a legal exposure no matter how good the model. The asymmetric-failure-cost calculus (PILLAR-PLAN §0): the cost of a missed unsubscribe is one prospect we send to one extra time; the cost of a false-positive unsubscribe (suppressing someone who didn't actually unsubscribe) is one missed conversation. The LLM extension would invert this — missed unsubscribes become CAN-SPAM violations.
* Operator-tuning the rule list is the right escape valve. A pattern the operator wants to catch + the LLM would catch can be added to `unsubscribe-patterns.yml` as a regex; the rule fires deterministically thereafter.

### D97-Alt3: Classifier output as a `reply_received.classification:` field added later (Pillar G observability)

Defer the classifier output's shape decision to Pillar G when the observability dashboards need it. **Rejected** because:

* The classifier output's shape IS the contract between the per-channel reply passes (Week 2+) and the auto-unsubscribe handler (Week 4-5+). Both consumers need the shape pinned in Week 1.
* Deferring to Pillar G would create a cross-pillar dependency that the per-week-handoff pattern handles poorly (Pillar D Week 4-5 author would have to wait for Pillar G to ship before knowing the shape).

### D98-Alt1: Merge the conversation-state machine into the send-state machine

Extend `derived_stage` with new stages (`sent → contacted → in_conversation → closed`) advancing on reply events. **Rejected** because:

* The two state machines have different scopes (per-person vs per-thread). A Person with two email threads has two conversation-states + one send-state; merging would require either flattening (losing per-thread granularity) or per-thread send-state (which doesn't match the per-person send-flow).
* `derived_stage` is a SoT for the send-state machine; consumers (Pass C, the doctor preflight, the funnel CLI) assume it returns the per-person send-flow stage. A merged state machine would silently broaden the SoT — exactly the Pass-A-class pattern the audit defends against.
* The "did this person ever reply on any channel?" query (which the merged state machine would make easy) is one `query_by_person` + `any(e.type.endswith("_reply_received"))` — trivial without merging.

### D98-Alt2: One conversation-state machine per person (not per-thread)

Aggregate the per-thread states into one per-person state. **Rejected** because:

* A person can have an active LinkedIn DM thread (in `active`) WHILE their email thread is in `dormant` (recipient stopped replying after one reply). Per-person aggregation would either pick one (wrong for most queries) or compute a derived "overall" state that loses information.
* The conversation-state machine's downstream consumer (Pillar D Week 6+ win/loss attribution; Pillar G observability) needs per-thread granularity to compute reply-rate-by-channel + cross-channel conversion funnels.

### D98-Alt3: No conversation state machine — the classifier's per-reply category is enough

Skip the state machine entirely; downstream consumers (Pillar G dashboards) derive state from the latest `reply_classified` event per thread. **Rejected** because:

* State transitions are queryable in their own right (Pillar G dashboards: "how many conversations transitioned from `active` to `dormant` in the last 30 days?"). Without explicit state-transition events, this query requires complex temporal correlation.
* The auto-unsubscribe handler (D100) emits a `suppression_added` event that's NOT a state transition; the conversation-state machine wraps the unified shape "every interaction with the recipient that changes our framework's posture" into one event class.
* Pillar D Week 6+ win/loss attribution needs to know "the conversation ended with X outcome" — an explicit `conversation_state_changed` event with `to_state: closed_won | closed_lost | closed_unsubscribed` is the right surface.

### D99-Alt1: Spawn a separate code-reviewer agent for the audit

Use the `code-reviewer` agent type instead of inline author audit. **Rejected for Week 1**; the audit IS the load-bearing artifact + benefits from sharing context with the ADR's author. Pillar D Week 1's per-week independent reviewer (spawned post-commit per the standing convention) WILL re-audit the surfaces from a fresh-context perspective; the inline audit + the per-week-review audit are complementary (per the Pillar C Week 12 per-week review's §"Categories to watch" pattern lesson).

### D99-Alt2: Skip the audit entirely; rely on per-week reviews to catch broadening surfaces

Pillar A + B + C all relied on per-week reviews. **Rejected explicitly** per Pillar C Week 12's retrospective lesson: the per-week reviewer's threshold for "ship-stopping" is biased toward "defer to holistic" for pre-existing surfaces (RETRO-pillar-c.md §"What surprised" #1). The audit IS the structural intervention against the Pass-A-class pattern. Future Pillar D weeks' per-week reviewers consult the audit as the surface map + extend it; the discipline is the surface-symmetry-check + the per-week-review-with-follow-up-commit pattern compounding.

### D99-Alt3: Defer the audit to Pillar D Week 12 (the exit-gate close)

A holistic-review-style audit at the end of the pillar. **Rejected** because the audit's value is forward-looking (preventing broadening in Weeks 2-N). A Week-12 audit catches what's been broken by then; a Week-1 audit prevents the breakage. Per the Pillar B → C lesson: cross-cutting tests + cross-pillar audits land Week 1.

### D100-Alt1: Ledger-first write order; YAML second

Reverse the D100 write order (append ledger events first, then write YAML). **Rejected** because:

* A crash between the two leaves the ledger with `suppression_added` but the YAML unchanged → the next dispatch sends to the unsubscribed prospect (the failure mode D100 explicitly defends against). YAML-first guarantees the suppression is live before the audit trail records the intent.
* The asymmetric-failure-cost calculus: a missing audit trail (suppression live without `suppression_added` event) is operator-visible and recoverable (reconcile pass H detects); a missing suppression (CAN-SPAM violation) is legally exposed.

### D100-Alt2: Single atomic write combining YAML + ledger via a new framework primitive

A new `atomic_suppress_and_log` primitive that wraps both writes in one syscall (via a transaction journal or similar). **Rejected** as over-engineered for Pillar D Week 4-5 scope. The Pillar B atomicity contract is file-level; cross-file atomicity (YAML file + ledger file) requires a transaction log primitive that's a substantial framework addition. The YAML-first + ledger-second discipline + reconcile pass H's detect surface is the right grain for v1. A future Pillar I OSS-bring-up may revisit if the operator-facing failure mode warrants.

### D100-Alt3: Defer auto-unsubscribe to Pillar I (manual operator append until OSS bring-up)

Operators manually append to `gdpr-forget.yml` on every classified unsubscribe until Pillar I CLI ships. **Rejected** because:

* PILLAR-PLAN §2 Pillar D exit criterion explicitly names the 60-second SLA as binding for Pillar D's "stable" flip. Deferring to Pillar I would require ADR amendment of PILLAR-PLAN.
* CAN-SPAM compliance is the load-bearing reason Pillar D exists in its current scope; deferring is incoherent with the pillar's purpose.
* The classifier is doing the work anyway (Week 2-3 ships the rule-based classifier); the auto-unsubscribe write is one additional line of code in the handler.

### D101-Alt1: New file `tests/test_pillar_d_reply_coherence.py` (Option B from HANDOFF-pillar-d-week-1.md)

Per-pillar test file split. **Rejected** per the Option-A rationale above. Pillar C's ADR-0014 D37 explicitly chose Option A; Pillar D inherits the same rationale.

### D101-Alt2: Defer the test vehicle stub to Pillar D Week 4-5 (when the classifier ships)

Skip the test stubs in Week 1; land them with the implementation. **Rejected** per the same Week-1-vehicle lesson that Pillar B + C inherited. The stubs ARE the surface contract; per-week reviewers consult them.

### D101-Alt3: Skip `TestUnsubscribeEnforcement` stubs and rely on `tests/test_policy_suppression.py` regression tests

Defer the auto-unsubscribe regression tests to the existing suppression test file. **Rejected** because:

* The auto-unsubscribe contract (D100) is cross-cutting — it spans Pillar A (suppression rules) + Pillar B (ledger event shape) + Pillar D (classifier handler). The test file's home should be the cross-cutting coherence vehicle, not the per-rule unit test file.
* `tests/test_policy_suppression.py` covers the suppression rule's `evaluate` path; it doesn't (and shouldn't) cover the auto-unsubscribe write path or the YAML-first + ledger-second contract.

## Consequences

### Positive

- **Reply event-type naming is pinned across all four channels before the first per-channel reply pass ships.** Pillar D Week 2-3's per-channel reply detection lands against the convention; no retroactive rename.
- **The cross-pillar surface audit (D99) closes the Pass-A-class latent-bug pattern by construction.** Every existing surface is verified; the new event classes either don't broaden the surface or broaden expected-by-design with a literal-string or closed-set filter.
- **The unsubscribe = rule-based ONLY invariant (D97) is pinned by a regression test.** A future contributor adding an LLM fallback to the unsubscribe path would fail the test loudly — the legal-liability constraint is enforced by the test corpus, not just documentation.
- **The conversation state machine is distinct from the send-state machine (D98).** `derived_stage` doesn't broaden silently; future amendments are loud at review time.
- **The auto-unsubscribe contract (D100) bounds the failure modes explicitly.** The YAML-first + ledger-second write order, the reconcile pass H detect surface, the asymmetric-failure-cost calculus's bias toward refuse — all named, none implicit.
- **Pillar D Week 1's commit includes a real-world fix (P2-A: Pass B reply events now carry `channel: "email"`).** Mirrors Pillar C Week 1's foundation-week fix pattern (ADR-0014 D33 §"Backfill `send_confirmed` carries `channel`"). The structural intervention works as designed — the audit surfaced the gap, the gap is closed Week 1.
- **Pillar G observability has a clear classifier data shape.** D97's `reply_classified` event with `category` + `classification_method` + `confidence` powers per-category precision/recall + per-channel reply-rate dashboards without bespoke parsing.

### Negative

- **Five new event types (`*_reply_received` family) are reserved in Week 1 but emitted only in Week 2+.** A casual reader of the codebase sees the names in this ADR + the test stubs but no production emit-site until Pillar D Week 2-3 ships. **Mitigation:** the stubs name the week that delivers; per-week reviewers consult the ADR as the contract.
- **The conversation-state machine's exact transitions are TBD per Pillar D Week 4-5+ implementation.** D98 names the shape (`replied → classified → unsubscribed | dormant | active`) but doesn't pin every transition. **Mitigation:** the foundation ADR is the right grain for Week 1; the Week 4-5+ implementation ADR (TBD numbering) extends with the transition map.
- **D100's auto-unsubscribe write contract requires a `ledger.append_batch` primitive that may not exist yet.** Pillar B's `Ledger.append` is single-event; batched appends may need a new framework method. **Mitigation:** Pillar D Week 2-3's classifier implementation either uses the existing single-event append twice (acceptable per the reconcile pass H detect surface — both writes are eventually consistent + the YAML write order guarantees correctness) or ships the batch primitive. The decision lands at Week 2-3's ADR; Week 1's contract is shape-only.
- **The D100 race-window between YAML write + dispatcher policy-bundle reload is documented as a limitation.** For batched operators a send may slip through after a YAML write but before the next bundle load. **Mitigation:** the Pillar H SIGHUP hook (TBD) closes the race; until then the operator's batched cadence is the bound.
- **The audit (D99) is a one-time snapshot.** Future Pillar D weeks must extend the audit row-by-row; a lazy week could ship without updating the audit. **Mitigation:** the per-week-reviewer's checklist (HANDOFF-pillar-d-week-N.md §"Validation gate") includes "the surface audit was extended (or confirmed unchanged)"; the discipline is the safeguard.
- **The exit-criterion stub test class adds ~150-300 LOC of skipped stubs to `tests/test_multi_channel_coherence.py`.** The file is already ~2746 lines post-Pillar-C-Week-12 (Pillar C Week 12 P3 noted file growth as a concern). **Mitigation:** Pillar D Week 12+'s split-file argument may resurface; until then the file-per-pillar discipline carries forward from ADR-0014 D37.

### Neutral / observability

- The `reply_classified` events Pillar D Week 2-3 emits are queryable via the existing `query_by_person` + filter-by-type pattern. Pillar G's classifier-precision/recall dashboard reads these directly.
- The `suppression_added` events Pillar D Week 4-5+ emits feed Pillar G's CAN-SPAM compliance audit dashboard (every auto-unsubscribe write recorded with timestamp + matched-pattern + person_id).
- The `conversation_state_changed` events Pillar D Week 4-5+ emits power Pillar G's reply-funnel dashboards (per-channel reply rate + per-category classifier breakdown + per-state-transition counts).
- No new SoT introduced. The classifier output is a derived index of the reply events; the reply events are themselves a derived index of the inbox state (which IS the SoT for "did the recipient reply?"). The suppression-list YAML is the SoT for "may we contact this recipient?" per the existing ADR-0004 contract — Pillar D's auto-unsubscribe handler writes through to the SoT, not into a new shadow surface.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. Reply events are denormalized from the inbox state (Gmail / LinkedIn / Twitter / Cal.com); classifier output is denormalized from reply events; auto-unsubscribe writes through to the existing suppression-list YAML SoT. The `docs/SOURCES-OF-TRUTH.md` registry gains no new row in Week 1 (per ADR-0004's existing row for `~/.outreach-factory/suppressions/*.yml`). A future Pillar D week may add a row for "Reply state per thread" if the conversation-state machine's per-thread state warrants distinct SoT — TBD per Week 4-5+ implementation.
- **I2 (two-phase commit on every external side effect):** Per-channel reply DETECTION is a READ from the external inbox + a WRITE to the ledger (one-phase from our side; the inbox is the SoT). Classifier is a pure FRAMEWORK operation (no external side effect; classifier output is ledger-only). Auto-unsubscribe IS an external-effect-adjacent operation (the suppression rule's enforcement IS the external effect; the YAML write is the local SoT update). The D100 YAML-first + ledger-second write order is the two-phase analog for this case: YAML write = "intent" (the suppression is live); ledger write = "confirmed" (the audit trail). The reconcile pass H is the recovery surface for asymmetric crashes.
- **I3 (schema versioning):** Reply events carry `v: 1` (existing ledger event versioning). Classifier output events carry `v: 1`. Suppression-list YAML carries the existing `version: 1` (ADR-0004). No I3 change required in Week 1; future Pillar D weeks may bump schemas if the classifier output evolves.
- **I4 (reproducible state):** Every Pillar D event class is durable in the append-only ledger; the inbox-detection passes are idempotent (per-channel reply-message-id indexes Pillar D Week 2+ ship). Replaying the ledger reconstructs the conversation state + the suppression list (per ADR-0004's existing `forget_append` reconstructability).
- **I5 (observable by default):** D97's classifier output, D98's state-transition events, D100's suppression_added events all emit structured events with full diagnostic context (matched pattern, classification method, confidence, channel, person_id, thread_key). Pillar G observability has scalar-field queries (`category == "unsubscribe"`, `classification_method == "rule"`, etc.).
- **I6 (tests prove invariants):** D101's test vehicle (extended in this Week 1 commit) is the integrative test surface. The D99 audit's P2-A fix to Pass B is pinned by a regression test in `tests/test_reconcile.py::TestPassB`. The D97 unsubscribe-rule-only invariant is pinned by `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_unsubscribe_classification_method_is_always_rule` (stub in Week 1; un-skips when the classifier ships).
- **I7 (cost is a first-class concern):** LLM fallback cost (Pillar D Week 6-8) emits `cost_incurred` events with `source: "reply_classifier_llm"` per the ADR-0006 convention. Pillar D Week 1 doesn't ship the LLM; the cost-source name is reserved in this ADR + named in `orchestrator.policy.budget.COST_RATES_USD` at the Week 6-8 implementation. The cost cap is operator-tunable per `cooldowns.yml` (a future `policy/000N_add_reply_classifier_llm_cap` migration ships in Pillar D's per-week trajectory — TBD week).
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0025 row. The per-week trajectory in HANDOFF-pillar-d-week-2.md (TBD this commit) names planned ADRs 0026+.

Does not weaken any invariant. I2's enforcement extends to the auto-unsubscribe path (D100's two-phase analog). I5's enforcement extends to the classifier + state-transition events.

### Downstream pillar impact

Per the Pillar A / B / C convention (every ADR explicitly names cross-pillar impact):

* **Pillar E (discovery quality + lineage).** Pillar E's discovery-lineage tracking already-suppressed prospects: when Pillar D's auto-unsubscribe writes to the YAML, the next discovery pass that surfaces the prospect (re-enrichment via Apollo / PDL) checks suppression at the enroll-gate + emits `enrollment_skipped_suppressed`. The contract is operator-deliberate at Pillar E's enrollment ADR (TBD). Pillar D Week 4-5+ surfaces the operator-visible "this prospect would have been re-enrolled but is now suppressed" signal via Pillar G's discovery-funnel breakdown.

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring is per-touch (not per-reply); Pillar F migrations operate on touch notes regardless of classification status. Pillar F may add a `voice_fidelity_after_reply_score:` field denormalized from the conversation-state machine — TBD per Pillar F's ADR.

* **Pillar G (observability).** Pillar G's classifier-precision/recall dashboard reads `reply_classified` events; the per-channel reply-rate funnel reads `*_reply_received` events filtered by `channel:`; the conversation-state funnel reads `conversation_state_changed` events filtered by `to_state:`. The auto-unsubscribe audit dashboard reads `suppression_added` events. All four dashboards are scalar-field queries against the D33-extended-by-D96 channel field.

* **Pillar H (daemon + dispatcher).** Pillar H's SIGHUP-on-classifier-write hook closes the D100 race-window between the YAML write + the dispatcher's policy-bundle reload. The Pillar H daemon also handles the per-channel reply detection passes as long-running consumers (rather than the batched-operator pattern). Pillar H's `live_reload_on_suppression_update` is the Pillar D Week 4-5+ forward-reference.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel reply state isolation. The auto-unsubscribe YAML files are per-tenant (per the existing `~/.outreach-factory/suppressions/` layout). The Pillar I doctor preflight extends to check classifier rule-list version + auto-unsubscribe YAML schema-conformance.

* **Pillar J (security + compliance).** Pillar J's CAN-SPAM compliance gate consumes Pillar D's auto-unsubscribe contract: the doctor preflight verifies the classifier is configured + the rule list is non-empty + the auto-unsubscribe YAML is writable. Pillar J's GDPR-forget transaction inherits the existing `forget_append` primitive (ADR-0004 §Decision step 2) + adds a new step "purge per-person reply events from the ledger" (tombstoning approach TBD per Pillar J's ADR — likely a `gdpr_purged` event that the reconcile passes skip when surfacing replies).

## Migration / rollout

The Week 1 deliverable is convention-setting + the test vehicle stub + the cross-pillar surface audit + the P2-A Pass B `channel: email` fix.

**Operator-facing changes (Week 1):**

1. **No new pending migrations.** `runner.pending()` still returns 15 (the Pillar C final state). Pillar D Week 4-5+ MAY ship vault migrations to add per-Person `conversation_status:` field denormalization OR per-touch `reply_state:` field stamping — TBD per the Week 2+ ADRs.

2. **Pass B's emit shape changes (P2-A fix).** Every `reply_received` and `bounce_detected` event Pass B emits from this commit onward carries `channel: "email"`. Pre-commit events lack the field; the classifier (Pillar D Week 2-3+) treats absent-channel as `email` per the historical default.

3. **Existing operators with pre-Pillar-D-Week-1 reply events** carry a small known limitation analogous to Pillar C Week 1's `ledger/0002` channel-field gap (per ADR-0014 §Migration/rollout item 3): their pre-fix `reply_received` / `bounce_detected` events lack the `channel` field. Pillar D Week 2-3's classifier handles this via "treat absent channel as email" per the historical-default rule. **Recommended remediation (Pillar I forward-reference):** the Pillar I CLI ships a one-time `python -m orchestrator.classifier replay --since <date>` that re-emits classifier outputs against the pre-fix events; the operator's classifier-precision/recall dashboard converges to consistency on the next replay. For Yang specifically (the current sole operator), the pre-Pillar-D-Week-1 reply event count is small (Phase 5.5 Pass B has only emitted in the recent reply-detection runs); the historical-default handling is sufficient until Pillar I.

**Operator-facing changes (Pillar D Weeks 2+, planned):**

4. **Each per-week ships a coordinated dispatcher / pass / migration + ADR.** Per HANDOFF-pillar-d-week-2.md (this commit's sibling). Per the D36 convention inherited from Pillar C, each Pillar D ADR ships its own §Existing-operator-seed subsection for operators with pre-existing channel-specific reply state (TBD per the per-week ADRs).

5. **The exit-criterion test (`TestPillarDExitCriterion.test_100_message_synthetic_inbox_classifier_benchmark`) un-skips at the final Pillar D week.** The test is the operator-visible signal that Pillar D is "stable" — when it passes, the per-week trajectory has completed.

**The Week 1 commit's verification surface:**

```python
# 1. The Pass B P2-A fix has regression tests.
$ python -m pytest tests/test_reconcile.py::TestPassB -v
# Expected: 1+ new tests passing pinning channel: email on reply + bounce events.

# 2. The coherence test vehicle extension exists and runs the email reply baseline.
$ python -m pytest tests/test_multi_channel_coherence.py::TestReplyClassification \
                   tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement \
                   tests/test_multi_channel_coherence.py::TestPillarDExitCriterion -v
# Expected: email-baseline rows passing; per-channel rows + classifier rows + binding test SKIPPED.

# 3. The full suite is green at +N tests (1847 + N — Pass B regression + new test class stubs).
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 1847+N passed, ~similar skipped count.

# 4. ADR-0025 exists; README index gains the row; PILLAR-PLAN §6 Pillar D row flipped.
$ ls docs/adr/0025-pillar-d-foundation.md
$ grep "0025" docs/adr/README.md
$ grep "Pillar D" docs/PILLAR-PLAN.md
```

### Existing-operator seed

Pillar D Week 1 ships NO new migrations + NO new ledger-state primitives that require an existing-operator seed. The P2-A Pass B fix takes effect on the next Pass B invocation (no seed); pre-fix events are handled by the classifier's "absent channel = email" default.

The first Pillar D week that ships a migration requiring an existing-operator seed (TBD — likely Pillar D Week 4-5+'s vault migration adding per-touch `reply_state:` fields) WILL include the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface Pillar D's auto-unsubscribe write integrates with (no engine change required).
- ADR-0003 (channel as first-class policy predicate) — the cross-channel rule whose behavior Pillar D events deliberately don't trigger (replies don't end in `_confirmed`).
- ADR-0004 (suppression rules + GDPR-forget) — the `forget_append` primitive D100's auto-unsubscribe write reuses; the suppression rule contract Pillar D inherits unchanged.
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention Pillar D Week 6-8's LLM fallback will emit against.
- ADR-0009 (migration framework) — Pillar D vault/policy migrations (Week 4-5+) register into the existing framework.
- ADR-0010 (ledger migrations) — Pillar D `migration_event` audit-trail emissions follow the D35 `channel=` kwarg convention (inherited from Pillar C).
- ADR-0011 (vault migrations) — Pillar D touch-note migrations consume the existing `iter_touch_notes` + `add_frontmatter_block_text` primitives.
- ADR-0012 (policy migrations) — Pillar D classifier-cap policy migration (TBD week) follows the engine-version-range-acceptance contract.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — the D27 cross-category-ordering contract Pillar D's migrations inherit; the D24 fixture-builder pattern Pillar D Week 4-5+ extends.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-two-phase-event invariant D96 extends to reply events; the D37 exit-criterion vehicle Pillar D extends per D101; the D36 existing-operator-seed pattern Pillar D inherits.
- ADR-0017 (Pillar C reconcile passes D + E) — the D48 + D50 asymmetric-failure-cost calculus Pillar D's per-channel reply passes inherit.
- ADR-0018 (Pillar C Twitter DM) — the D62 generalized `_run_channel_intent_pass` helper Pillar D's per-channel reply detection extends to a `_run_channel_reply_pass` analog (TBD week).
- ADR-0019 (Pillar C calendar booking) — the D66 webhook-driven recovery pattern Pillar D may extend for calendar-comment-reply detection (TBD week).
- ADR-0020 (Pillar C per-channel policy migrations) — the D72-D78 per-channel policy-migration shape Pillar D's classifier-cap migration follows.
- ADR-0024 (Pillar C cross-channel cooldown) — the D-N1-N8 multi-rule-per-migration shape Pillar D may extend for cross-channel reply correlation (TBD).
- `docs/PILLAR-PLAN.md` §2 Pillar D — exit criterion (binding text); §5 "What we will not do" — the unsubscribe = rule-based ONLY constraint D97 pins; §6 Pillar D row flipped to In progress in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D97's exclusion of LLM from the unsubscribe path AND D100's YAML-first write order.
- `docs/RISK-REGISTER.md` R010 (Regulatory shift) — risk Pillar D mitigates by design via the auto-unsubscribe enforcement contract. R011 (Cross-channel double-engagement) — risk Pillar D does NOT regress (reply events don't trigger the cross-channel rule). R012 (LLM hallucinates unsubscribe — NEW, added in this commit) — risk D97's invariant mitigates by construction.
- `docs/SOURCES-OF-TRUTH.md` — existing rows for "Suppression list" (Pillar D writes through) + "Send-history" (unchanged); no new rows in Week 1.
- `.planning/RETRO-pillar-c.md` §"What to do differently in Pillar D" items 1-3 — the carry-forward recommendations this ADR's structure implements.
- `.planning/REVIEW-pillar-c-holistic.md` §"Operator-Facing Instructions Audit" + §"Boil-the-Ocean Robustness Check" — the precedent shape Pillar D's holistic exit review (at the final Pillar D week) follows.
- `.planning/REVIEW-pillar-c-week-12.md` §"Categories to watch in Pillar D Week 1 per-week review" — the per-week reviewer checklist this ADR's D99 audit feeds.
- `.planning/REVIEW-pillar-d-surface-audit.md` — the D99 audit document; THE load-bearing anti-regression artifact for Pillar D Week 1.
- `.planning/HANDOFF-pillar-d-week-1.md` — the per-week handoff that scoped Week 1.
- `orchestrator/reconcile.py::run_pass_b` — the Phase 5.5 email reply-detection pass; D96's P2-A fix touches the emit shape; the docstring is extended to name the Pillar D Week 1 fix.
- `orchestrator/policy/suppression.py::forget_append` — the existing primitive D100's auto-unsubscribe write reuses.
- `orchestrator/ledger.py` — the `_idx_*` indexes the D99 audit walks; `_STAGE_BY_EVENT_TYPE` the P3-A boundary names.
- `tests/test_multi_channel_coherence.py` — the D101 vehicle Pillar D extends.
- `tests/test_reconcile.py::TestPassB` — the regression test home for D96's P2-A fix.
- Forward-references (planned):
  - **ADR-0026** (Pillar D Week 2-3): rule-based reply classifier — regex + keyword lists for the six categories; per-channel reply detection passes for LinkedIn / Twitter / calendar.
  - **ADR-0027** (Pillar D Week 4-5): conversation state machine implementation + auto-unsubscribe handler + Pillar D vault migration (`vault/0004_add_reply_state_to_touch_notes` — TBD shape).
  - **ADR-0028** (Pillar D Week 6-8): LLM fallback for non-unsubscribe categories + classifier-cap policy migration (`policy/0007_add_reply_classifier_llm_cap` — TBD shape).
  - **ADR-0029+** (Pillar D Week 9-11): win/loss attribution; conversation_outcome event; reply-funnel observability surface.
  - **ADR-00NN** (Pillar D Week 12): exit-gate close — the binding 100-message synthetic inbox classifier benchmark un-skips.
  - **Pillar H SIGHUP** (Weeks 37-48): the live-reload hook that closes the D100 race-window.
  - **Pillar I CLI** (Weeks 43-48): aggregation of per-ADR seed blocks + the classifier-replay command + the doctor-preflight extension.
