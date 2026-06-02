# ADR-0027: Pillar D Week 3 — long-tail classifier categories + per-channel reply detection

- **Status:** Accepted
- **Date:** 2026-05-23
- **Pillar:** D (Reply + conversation handling — Week 3)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0025 (Pillar D Week 1 foundation) pinned the per-channel reply event-type naming (D96), the classifier output convention as a separate `reply_classified` event class (D97), the conversation state shape (D98), the cross-pillar surface audit (D99), the auto-unsubscribe enforcement contract (D100), and the exit-criterion vehicle scope (D101). ADR-0026 (Pillar D Week 2) shipped the rule-based classifier's foundation: the `orchestrator/reply_classifier.py` module (D102), the operator-tunable pattern-list YAML format + location (D103), the (reply_message_id, channel) idempotence pair (D104), Pass G's invocation cadence in the reconcile chain (D105), the cross-pillar audit row extension (D106), and the Week 4-5 deferral of the auto-unsubscribe handler (D107). Week 2's deliverable shipped the unsubscribe path + uncategorized fallback per D107; the other four categories (ooo / wrong_person / interest / rejection) + per-channel reply detection were deferred to Week 3.

**Pillar D Week 3 is the long-tail-category + per-channel-reply-detection commit.** The handoff (`.planning/HANDOFF-pillar-d-week-3.md` — committed in the Week 2 follow-up) scopes Week 3 to two independent extensions of Pillar D's substrate:

1. **The CATEGORY dimension** — the classifier gains per-category pattern lists for `ooo`, `wrong_person`, `interest`, and `rejection`. The existing `unsubscribe` path stays rule-based ONLY per ADR-0025 D97 (legal-liability invariant). The classifier's `classify()` method dispatches in fixed priority order: unsubscribe FIRST (legal liability), then ooo / wrong_person / rejection / interest, then `uncategorized` fallback. Each category gets its own factory file (`config-template/{category}-patterns.example.yml`); operators bootstrap at their own cadence (the unsubscribe file is required per D109's refuse-loud posture; the four long-tail files are OPTIONAL).

2. **The CHANNEL dimension** — three new reconcile passes (Pass H / I / J) ship the per-channel reply detection from LinkedIn / Twitter. Pass H detects LinkedIn invite ACCEPTANCES (state-change events; no inline message); Pass I detects LinkedIn DM replies (per-message inbound from the recipient); Pass J detects Twitter DM replies (structurally identical to Pass I via a shared helper). Pass K (Cal.com booking-reply detection) is DEFERRED to Pillar I OSS bring-up per D113 — Cal.com's public webhook API does not expose a per-booking comment surface; the calendar-channel reply signal is the booking-state event itself (`calendar_booking_confirmed` / `_rescheduled` / `_cancelled`), classified through the dispatcher/webhook path, NOT via Pass G's classifier. Pass G's filter is widened from Week 2's `type == "reply_received"` to the closed-set `REPLY_EVENT_TYPES` (Week 2 email reply + Week 3's per-channel reply event classes).

The seven concerns this ADR resolves:

1. **Classifier constructor shape — unified pattern dict vs per-category kwargs?** Three plausible shapes: (a) `patterns: dict[str, list[str]]` keyed by category — uniform but requires the caller to know category names; (b) per-category kwargs (`unsubscribe_patterns=`, `ooo_patterns=`, etc.) — IDE-friendly + backwards-compat with Week 2's existing kwarg; (c) `**categories` variadic shape — over-engineered. D108 picks (b).

2. **Pattern file SPLIT — one file per category vs one file with category sub-keys?** Two options: (a) per-category files (`unsubscribe-patterns.yml`, `ooo-patterns.yml`, ...) — matches ADR-0026 D103's directory-union semantics; operators tuning ONE category don't scroll past the others; (b) one file with category sub-keys — single-file convenience but co-mingles legal-liability + long-tail tuning in one editing surface. D109 picks (a).

3. **Category dispatch priority order.** Unsubscribe FIRST (legal liability — ADR-0025 D97); then ooo / wrong_person / rejection / interest in fixed priority; then uncategorized fallback. The priority rationale balances signal specificity against false-positive risk; interest is evaluated LAST among the long-tail because positive language is the most-ambiguous category. D110 pins.

4. **Per-channel reply detection pass placement.** Three plausible shapes: (a) standalone CLI per channel — fragments operator mental model; (b) inline in the existing Pass D / E / F intent-recovery passes — couples DETECT + REPLY concerns in one pass; (c) parallel passes H / I / J alongside the existing chain — clean separation, additive to ALL_PASSES. D111 picks (c).

5. **Per-channel reply event field shape.** Each new pass emits one event class per channel (`li_invite_reply_received` / `li_dm_reply_received` / `tw_dm_reply_received`) carrying `channel`, `reply_message_id`, `reply_to_intent_id` per ADR-0025 D96 + ADR-0026 D104. The `reply_message_id` discriminator is synthesized for LinkedIn invite ACCEPTANCES (no message exists; `li_accept:<invitation_id>`); the per-message message-id for DM replies (LinkedIn / Twitter); a deterministic synthesized fallback (`<thread_id>:<sent_at>:<idx>`) when the MCP backend omits per-message IDs. D112 pins the shape.

6. **Cal.com comment surface (Pass K).** Cal.com's public webhook API exposes booking-state events but NOT per-booking comments. The handoff allows two options: (a) ship Pass K if Cal.com has a comment API; (b) defer to Pillar I if not. Phase 1 investigation confirmed Cal.com has no comment API; D113 picks deferral.

7. **Cross-pillar audit row extension (per ADR-0025 D99).** Week 3 ships three new per-channel reply event classes + three new reconcile passes + a widening of Pass G's filter. Every consumer surface is re-audited; D114 documents the audit extension.

Risks this ADR mitigates by design: **R012 (LLM hallucinates unsubscribe → over-suppression)** stays mitigated structurally per ADR-0025 D97 + ADR-0026's `ClassifierResult.__post_init__` invariant; Week 3 does NOT introduce LLM in the unsubscribe path. **R013 (operator pattern-list misconfiguration)** is extended to the long-tail categories — the four new factory files ship CONSERVATIVE defaults (each pattern carries inline rationale + known-false-positive notes per the Week 2 convention); the unsubscribe file is REQUIRED (refuse-loud per D109), the four long-tail files are OPTIONAL (absent → empty pattern list → that category never fires → falls through to next priority or uncategorized).

A new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`: **R014 (per-channel reply false-emit — operator's recipient sends an unrelated message on a known thread; Pass I / J emit a reply event that's not a reply to OUR outreach)**. Mitigations: (i) the per-message `from_self: False` filter — Pass I / J skip self-sent messages, so only recipient-originated messages emit; (ii) the per-channel thread-id filter — Pass I / J only walk conversations whose `thread_id` matches a known `*_confirmed` event from our ledger, so random LinkedIn / Twitter DMs don't trigger emit; (iii) the classifier's `uncategorized` fallback per ADR-0026 D107 — even if a random message lands as a reply event, the classifier emits `category=uncategorized` (no auto-suppression triggered until Week 4-5's handler).

## Decision

### D108. Long-tail classifier categories ship rule-based first (LLM fallback deferred to Week 6-8)

The four long-tail categories (`ooo`, `wrong_person`, `interest`, `rejection`) ship with rule-based pattern matching FIRST. The unsubscribe path stays rule-based ONLY per ADR-0025 D97's load-bearing legal-liability invariant. The LLM fallback for the non-unsubscribe categories is deferred to Week 6-8 (ADR-0029 — TBD).

**Classifier constructor signature (per-category kwargs):**

```python
class RuleBasedClassifier:
    def __init__(
        self, *,
        unsubscribe_patterns: Sequence[str],
        ooo_patterns: Sequence[str] = (),
        wrong_person_patterns: Sequence[str] = (),
        interest_patterns: Sequence[str] = (),
        rejection_patterns: Sequence[str] = (),
    ) -> None:
```

The per-category-kwargs shape (option B from the handoff's design-decision menu):

* **Backwards-compatible with Week 2 callers.** `RuleBasedClassifier(unsubscribe_patterns=[...])` still works; the four new kwargs default to empty sequences so existing callers + tests don't change.
* **IDE-friendly.** Type-checker + autocomplete surface every category explicitly.
* **Tunable per-category cadence.** Operators may pass only the categories they've bootstrapped; absent categories default to empty (never fire → fall through to the next priority or uncategorized).

**The `WEEK_3_DELIVERED_CATEGORIES` constant** captures Week 3's delivery (all six categories of `CATEGORIES`). `WEEK_2_DELIVERED_CATEGORIES` is preserved as a documentation pin (Week 2's subset = `{unsubscribe, uncategorized}`).

**Pin:** `tests/test_reply_classifier.py::TestOOOClassification` + `TestWrongPersonClassification` + `TestInterestClassification` + `TestRejectionClassification` + `TestCategoryPriorityOrder` + `TestUncategorizedFallback` + `TestPerCategoryConstructorBackwardsCompat`. Each parametrized against the factory pattern set.

### D109. Per-category factory file naming + directory-union loading

Each long-tail category gets its own factory file under `config-template/`:

| Category | Factory file | Production location |
|---|---|---|
| `unsubscribe` (Week 2) | `config-template/unsubscribe-patterns.example.yml` | `~/.outreach-factory/classifier/unsubscribe-patterns.yml` |
| `ooo` (Week 3) | `config-template/ooo-patterns.example.yml` | `~/.outreach-factory/classifier/ooo-patterns.yml` |
| `wrong_person` (Week 3) | `config-template/wrong-person-patterns.example.yml` | `~/.outreach-factory/classifier/wrong-person-patterns.yml` |
| `interest` (Week 3) | `config-template/interest-patterns.example.yml` | `~/.outreach-factory/classifier/interest-patterns.yml` |
| `rejection` (Week 3) | `config-template/rejection-patterns.example.yml` | `~/.outreach-factory/classifier/rejection-patterns.yml` |

The naming convention is hyphenated kebab-case (`wrong-person-patterns.yml` for the Python identifier `wrong_person`). The `PATTERN_FILE_BY_CATEGORY` constant in `reply_classifier.py` is the load-bearing SoT for the mapping.

**New classmethod: `RuleBasedClassifier.from_yaml_dir(directory)`.** Loads every category's pattern file from a single directory:

* The **unsubscribe** file is REQUIRED. Absence raises `PatternLoadError` with bootstrap remediation (the legal-liability surface MUST be configured per ADR-0026 D103's refuse-loud rationale).
* The four **long-tail** files are OPTIONAL. Absence → empty pattern list → that category never fires → falls through to the next priority or to `uncategorized`. Operators may bootstrap the long-tail categories at their own cadence.

The existing `RuleBasedClassifier.from_yaml(path)` classmethod is preserved for Week 2 callers + the single-file `--classifier-rule-list <path>` CLI flag; it loads only the unsubscribe file (the Week 2 default behavior). The new `from_yaml_dir` is the Week 3 entry point for the full long-tail-aware classifier.

**Existing SoT registry row** in `docs/SOURCES-OF-TRUTH.md` (added in Week 2 per ADR-0026 D103) already documents the directory-union semantics + the multi-file shape. No change required.

**Existing-operator bootstrap.** Pre-Pillar-D-Week-3 operators have the unsubscribe file from Week 2's bootstrap. The four new files are factory-shipped; operators copy:

```bash
cp config-template/ooo-patterns.example.yml ~/.outreach-factory/classifier/ooo-patterns.yml
cp config-template/wrong-person-patterns.example.yml ~/.outreach-factory/classifier/wrong-person-patterns.yml
cp config-template/interest-patterns.example.yml ~/.outreach-factory/classifier/interest-patterns.yml
cp config-template/rejection-patterns.example.yml ~/.outreach-factory/classifier/rejection-patterns.yml
```

Operators may skip categories they're not ready to tune — the absent files default to empty pattern lists.

**Pin:** `tests/test_reply_classifier.py::TestLongTailPatternLoading` + `TestFromYamlDir`. Tests verify factory examples load cleanly, refuse-loud on the missing unsubscribe file, and optional long-tail files default to empty.

### D110. Category dispatch priority order

The `RuleBasedClassifier.classify()` method dispatches per-category in fixed priority order. Pinned by `DISPATCH_PRIORITY` constant in `reply_classifier.py`:

```python
DISPATCH_PRIORITY: tuple[str, ...] = (
    "unsubscribe",   # FIRST always (legal liability per ADR-0025 D97)
    "ooo",           # temporal-explicit (low ambiguity)
    "wrong_person",  # operator-routing (explicit redirect)
    "rejection",     # closing-signal (moderate ambiguity)
    "interest",      # positive-signal (HIGHEST ambiguity — last among long-tail)
)
# uncategorized is the implicit fallback when no category fires.
```

**Priority rationale (per category):**

1. **`unsubscribe` FIRST always.** ADR-0025 D97's load-bearing legal-liability invariant: a reply containing both unsubscribe + interest signals (e.g., "sounds interesting but please unsubscribe me") MUST classify as unsubscribe. CAN-SPAM compliance is non-negotiable; the LLM is NEVER consulted (rule-based ONLY); the priority guarantee MUST NOT be reordered without an ADR amendment.

2. **`ooo` second.** Temporal-explicit signals ("out of office until DATE", "on vacation", "currently away") follow a small vocabulary of standard auto-reply phrasings — LOW ambiguity. An OOO reply combined with positive language ("sounds interesting — I'm currently out of office, will reply next week") classifies as OOO; the operator's pipeline pauses until the OOO end-date passes, then re-engages (the temporal-deferral is the right action).

3. **`wrong_person` third.** Operator-routing signals ("you have the wrong person — try our CTO", "I'm not the right contact") are EXPLICIT and unambiguous about the recipient's intent (redirect; ignore further outreach to me). The signal often co-occurs with positive interest about the company; the wrong-person classification is the more-actionable signal.

4. **`rejection` fourth.** Closing signals ("not now", "we just signed with a competitor", "no thanks") are EXPLICIT but moderately ambiguous (some "not now" replies are temporal-deferred re-engagement opportunities; the Week 4-5+ conversation-state machine may treat them as `closed_lost` or `dormant` accordingly). Rejection is evaluated BEFORE interest because "sounds interesting but we're not in market" is a canonical polite-rejection — the rejection signal must win.

5. **`interest` LAST among long-tail.** Positive language ("sounds great", "would love to chat", "interested in learning more") is the HIGHEST-ambiguity category — "sounds interesting" can mean genuine interest OR polite-non-commit OR deflection. Evaluating LAST means more-specific categories (rejection / wrong_person / ooo / unsubscribe) win on competing matches. Week 6-8's LLM fallback (ADR-0029 — TBD) is expected to outperform rules here specifically (most-ambiguous category).

6. **`uncategorized` fallback.** When no category fires, the classifier emits `category=uncategorized` per ADR-0026 D107's emit-not-noop posture — the operator's ledger has full visibility into "the classifier saw this reply but had no match."

**Why this order rather than the alternatives?** The handoff allowed Week 3's author discretion on the long-tail ordering ("TBD by Week 3's classifier author"). Two alternatives considered:

* **Order by failure-cost ascending** (most-recoverable first): interest → rejection → wrong_person → ooo. **Rejected** because polite-positive language is high-frequency in cold-outreach replies; evaluating interest FIRST would over-classify polite-non-commit replies as interest. The "more-specific signal wins on competing matches" principle is the load-bearing reason for last-among-long-tail.

* **Order by frequency in B2B reply corpus** (operator-empirical). Operators in different verticals see different reply frequencies; pinning Week 3's order to one operator's corpus would make the ADR vertical-dependent. The fixed priority is operator-tunable indirectly (operators tuning patterns can REMOVE patterns from a category that mis-fires; they cannot reorder the priority without forking the classifier source).

**Pin:** `tests/test_reply_classifier.py::TestCategoryPriorityOrder` parametrized against the priority-conflict scenarios (unsubscribe-vs-interest, rejection-vs-interest, wrong_person-vs-interest, ooo-vs-interest, unsubscribe-vs-rejection, ooo-vs-wrong_person).

### D111. Per-channel reply detection pass placement — Pass H / I / J (Pass K deferred)

Three new reconcile passes ship Week 3:

* **Pass H — LinkedIn invite acceptance detection.** Walks `li_invite_confirmed` events in the window; for each, queries the LinkedIn surface (`list_sent_invitations`) for the invitation's `status` field; if `accepted`, emits `li_invite_reply_received` per ADR-0025 D96. The per-channel reply event correlates back to the originating intent via `reply_to_intent_id`; the `reply_message_id` is the synthesized `li_accept:<invitation_id>` token per D112 (LinkedIn invitation acceptance is a connection-state change, not a message-with-id).

* **Pass I — LinkedIn DM reply detection.** Walks `li_dm_confirmed` events to build the set of known LinkedIn thread ids; fetches recent conversations (`list_recent_conversations`); for each conversation whose `thread_id` is in our known set, iterates inbound (`from_self: False`) messages + emits `li_dm_reply_received` for each unseen message (idempotence keyed by per-message `message_id` per ADR-0026 D104).

* **Pass J — Twitter DM reply detection.** Structurally identical to Pass I via the shared `_run_channel_dm_reply_pass` helper. Walks `tw_dm_confirmed` events; fetches recent Twitter DMs (`list_recent_dms`); emits `tw_dm_reply_received` for inbound messages on known threads.

* **Pass K (Cal.com booking-reply detection) deferred** per D113.

**`ALL_PASSES` extended** to the ten-pass chain:

```python
ALL_PASSES = ("A", "B", "C", "D", "H", "E", "I", "F", "J", "G")
```

The order is **data-flow driven** (producers before consumers):

* Pass D (LinkedIn invite intent recovery) → Pass H (invite acceptance detection consumes `li_invite_confirmed` events Pass D may emit).
* Pass E (LinkedIn DM intent recovery) → Pass I (DM reply detection consumes `li_dm_confirmed.linkedin_thread_id`).
* Pass F (Twitter DM intent recovery) → Pass J (DM reply detection consumes `tw_dm_confirmed.twitter_thread_id`).
* Pass G runs LAST (consumes the reply events H / I / J emit + the email reply events B emits — the closed-set `REPLY_EVENT_TYPES` per D112).

**`--full` invocation extended** to `"A,B,C,D,H,E,I,F,J,G"`. Operators running `--full` get the full per-channel reply detection + classification chain. `--quick` remains UNCHANGED (Pass A only — the email-intent-recovery hot path); reply detection is NOT in the per-batch send-gate's freshness-check path.

**Helper generalization: `_run_channel_dm_reply_pass`.** Pass I + Pass J share a generalized helper (analogous to ADR-0018 D62's `_run_channel_intent_pass` for Pass D / E / F). The five parameterized dimensions cover every per-channel divergence (`channel`, `confirmed_type`, `confirmed_thread_field`, `reply_type`, `fetch_batch`). Pass H does NOT use the helper — it walks invitations (state-change events), not messages on threads, so the structural pattern diverges. Per the handoff's design-decision recommendation: "write the first pass first; if the rest look structurally identical, generalize." Pass I + Pass J are structurally identical (modulo the parameters); Pass H is not.

**Pass requires-client error shape.** Per ADRs 0017 + 0018 + 0026 — if Pass H / I is requested without a LinkedIn client, the dispatcher records "Pass {H,I} requires a LinkedIn client"; same shape for Pass J + Twitter. Tests inject fakes directly via `linkedin=` / `twitter=` kwargs to `reconcile()`.

**Pin:** `tests/test_reconcile_pass_h_i_j.py` — 42 unit tests covering happy-path, idempotence, channel discipline, failure modes, dry-run, orchestration.

### D112. Per-channel reply event field shape

Every reply event emitted by Pass H / I / J carries the same envelope per ADR-0025 D96 + ADR-0026 D104:

| Field | Required | Notes |
|---|---|---|
| `type` | ✓ | One of `{li_invite_reply_received, li_dm_reply_received, tw_dm_reply_received}` |
| `person_id` | ✓ | From the originating `*_confirmed` event |
| `channel` | ✓ | `linkedin` (Pass H / I) or `twitter` (Pass J) per ADR-0014 D33 + ADR-0025 D96 |
| `reply_message_id` | ✓ | See below — per-pass discriminator shape |
| `reply_to_intent_id` | ✓ | The `intent_id` of the originating `*_intent` (carried via the `*_confirmed` event) per ADR-0025 D96 |
| `linkedin_invitation_id` (Pass H) | per-pass | Cross-correlation back to the LinkedIn invitation |
| `linkedin_thread_id` (Pass I) | per-pass | Cross-correlation back to the LinkedIn DM thread |
| `twitter_thread_id` (Pass J) | per-pass | Cross-correlation back to the Twitter DM thread |
| `snippet` | per-pass (I / J) | Truncated reply body (≤500 chars) for Pass G's classifier input + Pillar G observability |
| `from` | optional | Sender display name or handle, when MCP returns it |
| `sent_at` | optional | The platform's per-message timestamp |
| `accepted_at` (Pass H) | optional | The LinkedIn surface's `accepted_at` timestamp |
| `_recovered_by` | ✓ | Always `"reconcile"` (per ADR-0017 D48's per-pass attribution convention) |

**Per-pass `reply_message_id` shape:**

* **Pass H — synthesized.** LinkedIn invitation acceptance is a connection-state change, NOT a message-with-id. The synthesized form `li_accept:<invitation_id>` satisfies ADR-0026 D104's (mid, channel) idempotence pair: stable per invitation (rerun is no-op); distinct across invitations; the `li_accept:` prefix surface-reads as "this isn't a real LinkedIn message id" so future debuggers don't grep the LinkedIn API for a matching message.

* **Pass I / J — per-message id, with synthesized fallback.** Modern LinkedIn / Twitter MCP backends expose per-message `message_id`. Pass I / J use this directly. Older / minimal backends may omit it; the synthesized fallback `<thread_id>:<sent_at>:<idx>` (per `_synthesize_dm_reply_message_id`) is deterministic per-(thread, message-position, send-time) — stable across reruns iff the MCP returns messages in stable order with stable sent_at.

**Pass G consumer-side extension per ADR-0027 D112.** Pass G's input filter widens from Week 2's `type == "reply_received"` to the closed-set `REPLY_EVENT_TYPES` frozenset:

```python
REPLY_EVENT_TYPES: frozenset[str] = frozenset({
    "reply_received",                  # Phase 5.5 Pass B (email)
    "li_invite_reply_received",        # Pillar D Week 3 Pass H
    "li_dm_reply_received",            # Pillar D Week 3 Pass I
    "tw_dm_reply_received",            # Pillar D Week 3 Pass J
})
```

The closed-set discipline mirrors `_INTENT_TYPES` / `_OUTCOME_TYPES` / `_CONFIRMED_TYPES` per the ADR-0025 D99 audit's pattern. Future event-type additions extend the set + the audit row + the test suite explicitly.

**Pin:** `tests/test_reconcile_pass_h_i_j.py::TestPassGConsumesWeek3ReplyTypes` — Pass G classifies all four reply event types end-to-end.

### D113. Cal.com comment surface decision — Pass K deferred to Pillar I

**Decision: defer Cal.com booking-reply detection to Pillar I OSS bring-up.**

Phase 1 investigation of Cal.com's public API surface (per the handoff's "investigate Cal.com's API surface in Phase 1; decide based on what exists" recommendation) confirmed:

* Cal.com's webhook API exposes booking-state events: `BOOKING_CREATED`, `BOOKING_RESCHEDULED`, `BOOKING_CANCELLED`. These are emitted by `orchestrator/cal_com_webhook.py` (ADR-0019) as `calendar_booking_confirmed` / `calendar_booking_rescheduled` / `calendar_booking_cancelled` ledger events — the booking-state machine IS the calendar-channel reply signal today.
* Cal.com has a `notes` field on bookings (the recipient may populate during booking) but no ongoing per-booking comment API. The notes are one-time at booking creation.
* Cal.com's paid tier includes Discussions, but the public webhook API does not surface them.

**Implication.** The calendar channel's reply signals today are the booking-state events themselves, classified through the dispatcher / webhook path NOT via Pass G's classifier. Pass G's filter does NOT include `calendar_booking_reply_received` (the event class is reserved in ADR-0025 D96 + the surface audit but not consumed by Pillar D's classifier today).

**Pillar I forward-reference.** If Cal.com ships a per-booking comment API (or operators wire a third-party comment surface — e.g., Slack / email follow-up integration), Pillar I OSS bring-up extends Pass K + extends `REPLY_EVENT_TYPES` + un-skips `tests/test_multi_channel_coherence.py::TestReplyClassification::test_calendar_booking_reply_received_carries_channel_calendar`.

**Asymmetric-failure-cost calculus.** A deferred Pass K is one missing observability surface for calendar-channel comment replies (low frequency); the booking-state events ALREADY capture the load-bearing recipient-action signals (booking, rescheduling, cancellation). The deferral cost is proportional to the rarity of inline-comment-as-reply behavior on Cal.com bookings — empirically, recipients reply via email-thread or LinkedIn DM, not via Cal.com comments. Operators wanting the comment-signal can manually file a ledger event via the future Pillar I CLI; auto-detection deferred until a comment API exists.

**Pin:** `tests/test_multi_channel_coherence.py::TestReplyClassification::test_calendar_booking_reply_received_carries_channel_calendar` carries the deferred-skip with a "deferred per ADR-0027 D113" message — un-skips alongside Pillar I's Pass K work.

### D114. Cross-pillar audit row extension (per ADR-0025 D99)

The Week 3 commit extends `.planning/REVIEW-pillar-d-surface-audit.md` with new rows for:

1. **Three new per-channel reply event classes** (`li_invite_reply_received` / `li_dm_reply_received` / `tw_dm_reply_received`) — each carries `person_id` → lands in `_idx_person`. Each `query_by_person` consumer is re-audited (every consumer already closed-set or literal-string-filtered against `_confirmed` / cost / suppression event types per Week 1 + Week 2 audits; the new event classes don't end in `_confirmed` so the cross-channel rule doesn't fire; not in `_STAGE_BY_EVENT_TYPE` so `derived_stage` doesn't broaden; not in `_INTENT_TYPES` so `open_intents` doesn't return them).

2. **Three new ledger-walk patterns** (Pass H / I / J each walk the ledger for `*_confirmed` events + emit `*_reply_received` events). Each pass uses literal-string filters on the event type → closed-set-protected against future event-type additions.

3. **Pass G's filter widening** from `type == "reply_received"` to `REPLY_EVENT_TYPES` (closed set). The closed-set discipline mirrors `_INTENT_TYPES` / `_OUTCOME_TYPES` per the existing audit pattern.

The audit's verdict carries: **zero new P1 latent-bug patterns; the three new event classes' consumer surfaces are fully covered by the Week 1 + Week 2 audit's existing consumer enumeration + the new ledger-walk patterns are closed-set-protected by construction.**

**Pin:** `.planning/REVIEW-pillar-d-surface-audit.md` updated in the Week 3 commit with the new rows.

## Alternatives considered

### D108-Alt1: Unified `patterns: dict[str, list[str]]` constructor

```python
def __init__(self, *, patterns: dict[str, list[str]]) -> None:
```

**Rejected** because:

* Backwards-incompatible with Week 2's `unsubscribe_patterns=` kwarg. The Week 2 test corpus + existing operator-facing callers (e.g., the live dispatcher's classifier construction) would need updating; the test churn is unnecessary.
* IDE autocomplete + type-checker support is weaker — the dict's keys are loose strings; the per-category-kwargs shape surfaces every category explicitly.
* The category-set is small (6 today; +0 expected for Week 4-5+ — the conversation-state machine adds STATES, not categories). Signature explosion is not a concern at this scale.

### D108-Alt2: `**categories` variadic constructor

```python
def __init__(self, **categories: Sequence[str]) -> None:
```

**Rejected** because:

* No type-checker / IDE support for the categories (every kwarg is loose `Sequence[str]`).
* The unsubscribe kwarg's required-ness can't be enforced at the type level — operators omitting `unsubscribe_patterns=` would silently default to empty (the legal-liability path with no patterns is the worst failure mode).

### D108-Alt3: Defer the long-tail categories to Week 4-5

Skip the long-tail rule-based shipping; jump straight to the LLM fallback in Week 6-8.

**Rejected** because:

* Week 4-5's scope is auto-unsubscribe handler + conversation state machine; bundling the long-tail rule-based shipping would extend the commit's blast radius. The two-extension Week 3 (categories + per-channel detection) is a self-contained scope per the handoff.
* The long-tail rule-based detection delivers operator value Week 3 (the classifier's visibility into ooo / wrong_person / rejection / interest categories informs the operator's pipeline management). LLM fallback in Week 6-8 EXTENDS the coverage but the rule-based detection is the operator-tunable baseline.

### D109-Alt1: One file with category sub-keys

```yaml
# ~/.outreach-factory/classifier/all-patterns.yml
version: 1
patterns:
  unsubscribe:
    - "(?i)\\bunsubscribe\\b"
    ...
  ooo:
    - "(?i)\\bout of office\\b"
    ...
```

**Rejected** because:

* Co-mingles the legal-liability surface (unsubscribe) with the long-tail (operator-tunable) surfaces in one editing surface. Operators tuning the unsubscribe rule list shouldn't have to scroll past 100 lines of OOO patterns; the audit posture (CAN-SPAM compliance) benefits from one-file-per-category isolation.
* Diverges from ADR-0026 D103's directory-union semantics established Week 2.
* The single-file shape makes per-category git-blame harder — tuning interest patterns shouldn't churn the unsubscribe file's git history.

### D109-Alt2: One file per pattern (each pattern in its own file)

```
~/.outreach-factory/classifier/patterns/unsubscribe-001.yml
~/.outreach-factory/classifier/patterns/unsubscribe-002.yml
~/.outreach-factory/classifier/patterns/ooo-001.yml
...
```

**Rejected** because:

* Over-organized for the operator. Tuning a category requires editing N files. The per-pattern inline comment + the per-category file shape (D109) is the right grain.
* The directory-walk consumer surface grows from O(category) to O(pattern) — Pillar G observability + Pillar I doctor preflight would have to scan O(pattern) files at startup.

### D109-Alt3: Inline factory defaults in source code; absent files = use factory

Skip the operator-bootstrap step; defaults live in `reply_classifier.py` as module constants; absent operator files mean "use the factory defaults."

**Rejected** because:

* Hides the legal-liability rule list from operator-audit. Operators can't point CAN-SPAM auditors at a versioned YAML file showing "this is our unsubscribe rule list, last reviewed YYYY-MM-DD."
* Prevents per-vertical / per-operator tuning. Different verticals see different reply phrasings; operators MUST be able to tune without forking the framework source.
* Violates ADR-0026 D103's refuse-loud bootstrap rationale: silent fallback to defaults means "the operator's classifier is the FACTORY's, not the operator's."

### D110-Alt1: Order by failure-cost ascending (most-recoverable first)

Priority: interest → rejection → wrong_person → ooo → unsubscribe (unsubscribe still last? — no, ADR-0025 D97 mandates first).

**Rejected** because:

* Reversing the ordering would make interest the FIRST long-tail category. Polite-non-commit replies ("sounds interesting, but ...") are high-frequency in cold outreach; the false-positive rate on interest would be much higher than the alternative.
* The "more-specific signal wins" principle (rejection / wrong_person / ooo > interest) is the load-bearing pattern-recognition heuristic; reversing it inverts the intent.

### D110-Alt2: Operator-tunable priority via the YAML file header

```yaml
version: 1
priority: [unsubscribe, rejection, wrong_person, ooo, interest]
patterns:
  ...
```

**Rejected** because:

* The legal-liability invariant (unsubscribe FIRST always) MUST NOT be tunable — operators with conservative compliance posture should not be able to (accidentally or maliciously) lower the unsubscribe priority below another category.
* Operator-tuning at the priority level adds a per-operator cognitive load on top of the per-pattern tuning. The Week 6-8 LLM fallback would also have to honor the per-operator priority; the priority becomes a cross-cutting variable.
* The fixed priority is operator-tunable INDIRECTLY (operators tuning patterns can REMOVE patterns from a category that mis-fires); the explicit priority knob is over-engineered for the actual tuning workflow.

### D110-Alt3: No fixed priority; first-match-across-all-categories wins

Iterate all five categories in arbitrary order; emit the first match.

**Rejected** because:

* Non-deterministic across runs if the iteration order depends on dict iteration (Python 3.7+ dict iteration is insertion-order but the contract isn't load-bearing for the classifier's tests).
* The unsubscribe FIRST invariant per ADR-0025 D97 requires deterministic priority. A naive first-match would not enforce it.

### D111-Alt1: Standalone CLI per channel

```bash
python -m orchestrator.linkedin_reply_detector --since 7d
python -m orchestrator.twitter_reply_detector --since 7d
```

**Rejected** because:

* Fragments the operator's mental model. "To reconcile state, run reconcile; to detect LinkedIn replies, run linkedin_reply_detector; to detect Twitter replies, run twitter_reply_detector" — each new surface adds operator-facing cognitive load.
* The reconcile chain IS the framework's canonical periodic-healing surface; reply detection BELONGS in the chain (per the per-pass attribution convention).
* The CLI flag surface (`--linkedin-scan-limit`, `--twitter-scan-limit`) already exists on `reconcile.py`; standalone CLIs would duplicate the surface.

### D111-Alt2: Inline reply detection in the existing Pass D / E / F intent-recovery passes

Extend Pass D / E / F to ALSO detect replies (after intent recovery).

**Rejected** because:

* Couples DETECT-INTENT-OUTCOME with DETECT-REPLY in one pass. A failure in one breaks the other; the per-pass `PassResult` records would conflate two distinct failure-mode surfaces.
* The intent-recovery pass walks `*_intent` events (open intents that need to be confirmed / aborted). The reply-detection pass walks `*_confirmed` events (already-sent outreach that may have received a reply). The two walks have different windows + different cardinalities.
* The Week 4-5+ conversation-state machine (ADR-0028) MAY introduce new reply detection cadences (e.g., long-window passes for stale conversations); decoupling reply detection from intent recovery keeps the per-pass cadence tunable.

### D111-Alt3: Generalize Pass D / E / F + H / I into one cross-channel "Pass D'"

Refactor the per-channel passes into a single mega-pass with channel-discriminator branching.

**Rejected** because:

* The per-channel passes have distinct purposes (Pass D / H = LinkedIn invites; Pass E / I = LinkedIn DMs; Pass F / J = Twitter DMs). Combining them obscures the per-channel reasoning. The existing helper (`_run_channel_intent_pass` for D / E / F; `_run_channel_dm_reply_pass` for I / J) is the right grain — generalize the IMPLEMENTATION, not the orchestration.
* Operators reading per-pass logs benefit from per-channel attribution. A mega-pass's log would have to be channel-prefixed everywhere.

### D113-Alt1: Ship Pass K with a polling pattern

Pass K polls Cal.com's booking-list API + diffs against the local ledger to detect new comments-on-bookings (even though no comment API exists; infer from `notes` field changes).

**Rejected** because:

* Cal.com's `notes` field is set at booking creation; subsequent changes via the operator's calendar UI don't reliably propagate to the public API. The polling pattern would have high false-positive risk + low coverage.
* Building a Pass K against an inferred API surface is a maintenance burden — Cal.com may change the `notes` field behavior in a future release; the per-channel reply detection would silently break.
* The booking-state events (`calendar_booking_confirmed` / `_rescheduled` / `_cancelled`) ALREADY cover the load-bearing recipient-action signals via the existing dispatcher / webhook path.

### D113-Alt2: Ship Pass K for the calendar-state-as-reply translation

Translate booking-state events into `calendar_booking_reply_received` events at emit-time (in `orchestrator/cal_com_webhook.py`).

**Rejected** because:

* The booking-state events are SEMANTICALLY distinct from a reply (a confirmed booking is recipient ACTION; a reply is recipient COMMUNICATION). Conflating them via a translation pass would muddy the classifier's input space.
* Pillar D Week 4-5's conversation-state machine (ADR-0028) is the right consumer of booking-state events as conversation-state transitions; the classifier (Pass G) is the wrong surface.
* The translation pattern is operator-deliberate; Pillar I's CLI may add `python -m orchestrator.calendar_reply manual <booking_id> <category>` for operator-initiated classification of follow-up comments (post-booking discussions in email-thread or LinkedIn — which Pass B / I already detect).

### D113-Alt3: Defer Cal.com comment detection to Pillar I but emit a stubbed `calendar_booking_reply_received` event for every booking-confirmed event

Always emit a `calendar_booking_reply_received` alongside `calendar_booking_confirmed` so the classifier surface is uniform.

**Rejected** because:

* Distorts the event-class semantics — a `calendar_booking_reply_received` event without an actual reply is operator-confusing in the ledger ("did the recipient comment?"; the event would say yes; the actual recipient did nothing).
* Inflates the classifier input → Pass G classifies a sentinel-empty body as uncategorized → operator's classifier-precision/recall dashboard (Pillar G) is skewed by the synthetic events.
* The deferral cost (Pass K not shipping today) is bounded; the corruption cost (synthetic reply events forever in the ledger) is unbounded.

## Consequences

### Positive

- **All six classifier categories ship with rule-based detection.** Operators get classifier visibility across the full PILLAR-PLAN §2 Pillar D category set (`unsubscribe` legal-liability + `ooo` / `wrong_person` / `interest` / `rejection` operator-tunable + `uncategorized` fallback).
- **Per-category factory pattern files are operator-readable + auditable.** Each file carries inline rationale + known-false-positive notes per the Week 2 convention; operators in different verticals tune at their own cadence.
- **The dispatch priority order is pinned by source + by test.** ADR-0027 D110 + `DISPATCH_PRIORITY` constant + `TestCategoryPriorityOrder` make the priority order reviewable + impossible to silently reorder.
- **Three new reconcile passes detect per-channel replies.** Pass H (LinkedIn invite acceptance) + Pass I (LinkedIn DM reply) + Pass J (Twitter DM reply) extend the framework from "send-state recovery" + "email-reply classification" to "per-channel reply detection + classification."
- **Pass G's input filter is closed-set-protected (REPLY_EVENT_TYPES).** Future event-type additions extend the set explicitly + extend the audit row + extend the test suite. The Pass-A-class latent-bug pattern (silent broadening) is structurally foreclosed.
- **The helper generalization (`_run_channel_dm_reply_pass`) covers Pass I + J.** Code reuse without forcing Pass H (which has a structurally different shape — invitation-state vs message-on-thread) into the same surface.
- **Cal.com comment surface is investigated + deferred with rationale.** ADR-0027 D113 names the deferral + the Pillar I forward-reference; future contributors find the decision in the ADR rather than as folklore.

### Negative

- **The four new factory pattern files are OPTIONAL — operators may bootstrap incompletely.** An operator who copies only `unsubscribe-patterns.yml` from Week 2 + skips the four long-tail files has a degraded classifier (every non-unsubscribe reply → uncategorized; no operator-visible signal for ooo / wrong_person / etc.). **Mitigation:** the bootstrap step is documented in ADR-0027 §Migration/rollout; the four factory examples ship conservative-default patterns operators copy as-is for baseline coverage.

- **The dispatch priority order is FIXED in source.** Operators wanting a different priority (e.g., interest BEFORE rejection for a vertical where positive-language conversion is the load-bearing metric) must fork the framework. **Mitigation:** Operator-tunable priority is rejected per D110-Alt2's rationale; the indirect tuning (remove patterns that mis-fire) is the right escape valve. If empirical evidence surfaces that a different priority is widely preferable, a future ADR amendment can update.

- **Pass H's synthesized `reply_message_id` (`li_accept:<invitation_id>`) is non-standard.** Future debuggers grepping the LinkedIn API for the synthesized token will find nothing (it's a framework-internal id). **Mitigation:** the `li_accept:` prefix surface-reads as "this isn't a real message id"; the ADR + docstring + audit document the synthesis explicitly.

- **Pass I / J's `_run_channel_dm_reply_pass` helper adds a new generalization surface alongside `_run_channel_intent_pass`.** A reader of `reconcile.py` now sees two helper-generalization patterns (one for intent recovery, one for DM reply detection). **Mitigation:** the helper's docstring names the shared structure + the per-pass parameterization explicitly; the two helpers serve different purposes (intent vs reply); the codebase is no more confusing than ADR-0018 D62's original generalization.

- **The Week 3 commit broadens `_idx_person` with three new event classes.** Every existing `query_by_person` consumer's result-set widens (audit re-verifies closed-set-or-literal-string filters; no broadening creates a latent bug). **Mitigation:** D114's audit extension verifies every consumer; the audit IS the surface map; future Pillar D weeks consult it.

- **Pass K (Cal.com) deferral leaves a known gap.** Operators using Cal.com as a primary channel have NO automated comment-reply detection. **Mitigation:** the booking-state events ALREADY cover the load-bearing recipient-action signals (booking, rescheduling, cancellation); inline-comment replies on Cal.com bookings are rare; operators wanting the comment-signal can manually file a ledger event via the future Pillar I CLI.

### Neutral / observability

- **Pass H / I / J emit one event per detected reply.** Pillar G dashboards (Pillar D Week 12+) can compute per-channel reply rates by filtering `type IN REPLY_EVENT_TYPES AND channel = <value>`. The closed-set REPLY_EVENT_TYPES is the load-bearing reference.
- **Per-category match rates are visible in the `funnel` CLI's by_type breakdown.** The classifier-precision/recall dashboard (Pillar G) reads `reply_classified` events filtered by `category`; per-category counts surface for free.
- **The pattern files are version-controlled.** Operators editing `~/.outreach-factory/classifier/{category}-patterns.yml` can track changes via git (the operator's vault is git-managed per `docs/PILLAR-PLAN.md` § shared conventions); the audit trail for "why was the rejection pattern set tightened on YYYY-MM-DD?" lives in git history alongside the operator's Person notes.
- **No new SoT introduced.** The Week 2 SoT row "Classifier pattern lists" (per ADR-0026 D103) already documents the directory-union semantics for multi-file shape; Week 3's per-category files land in the same directory under the existing row.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT. The Week 2 row covers the directory union; Week 3's per-category files land under it. The per-channel reply event classes are denormalized from the platform-specific inboxes (Gmail / LinkedIn / Twitter / Cal.com) — the inboxes ARE the SoT for "did the recipient reply?"; the ledger events are the framework's denormalized index.

- **I2 (two-phase commit on every external side effect):** Per-channel reply DETECTION is a READ from the platform inbox + a WRITE to the ledger (one-phase from our side; the platform inbox is the SoT). The classifier (Pass G) is a pure FRAMEWORK operation (no external side effect; classifier output is ledger-only). The auto-unsubscribe handler (Week 4-5+) carries the two-phase commit per ADR-0025 D100; Week 3's emit-only posture preserves the I2 invariant.

- **I3 (schema versioning):** Reply events carry `v: 1` (existing ledger event versioning). Per-category pattern files carry `version: 1` (per ADR-0026 D103 + extended by D109 for the long-tail files). No I3 change required.

- **I4 (reproducible state):** Every Pillar D Week 3 event class is durable in the append-only ledger; Pass H / I / J are idempotent per ADR-0026 D104 (the (reply_message_id, channel) pair). The synthesized `reply_message_id` (Pass H + the Pass I/J fallback) is deterministic per the underlying source data; reruns are no-ops. Replaying the ledger reconstructs the per-channel reply state.

- **I5 (observable by default):** Pass H / I / J each emit `PassResult` records with per-pass `examined` + `synthesized` + `errors` counts; operators see per-pass health in the reconcile CLI's status output. The per-channel reply events carry full diagnostic context (channel, person_id, reply_message_id, reply_to_intent_id, snippet, etc.).

- **I6 (tests prove invariants):** D108-D113's deliverables are pinned by `tests/test_reply_classifier.py` (8 new test classes; ~100 new tests including per-category dispatch + priority order + pattern loading + from_yaml_dir) + `tests/test_reconcile_pass_h_i_j.py` (42 new tests covering Pass H / I / J + Pass G's REPLY_EVENT_TYPES extension + end-to-end orchestration) + `tests/test_multi_channel_coherence.py::TestReplyClassification` (3 newly un-skipped Week 3 rows).

- **I7 (cost is a first-class concern):** No new external-LLM or external-API surface in Week 3 — Pass H / I / J consume the existing LinkedIn / Twitter MCP rate-limit pools per ADRs 0017 + 0018. No `cost_incurred` events emitted by Week 3's deliverables. Pillar D Week 6-8's LLM fallback (ADR-0029 — TBD) is the first cost-bearing Week of Pillar D.

- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0027 row. `docs/PILLAR-PLAN.md` §6 Pillar D row flips to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓".

Does not weaken any invariant. I2's enforcement extends to the per-channel reply detection paths (the platform inbox is the SoT; the ledger is the denormalized index). I5's enforcement extends to the per-channel reply event class emissions + the classifier's long-tail dispatch output.

### Downstream pillar impact

Per the Pillar A / B / C / D Week 1 + 2 convention (every ADR explicitly names cross-pillar impact):

* **Pillar E (discovery quality + lineage).** Pillar E's discovery-pass logic + lineage tracking already-suppressed prospects: when the long-tail classifier emits `category=rejection` or `category=wrong_person`, Pillar E's re-enrichment passes (TBD per Pillar E's ADR) MAY de-prioritize the prospect for re-surfacing. The Pillar D classifier output is the load-bearing signal; the de-prioritization logic lives at Pillar E. Pillar E's discovery-funnel breakdown (Pillar G) reads `reply_classified.category` to power the "rejected prospects re-enriched" cohort.

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring may consume `reply_classified.category=interest` events to flag "high-engagement touch" examples for the voice corpus (the operator's touches that converted to interest are the load-bearing exemplars). The corpus-curation logic is operator-deliberate per Pillar F's ADR.

* **Pillar G (observability).** Pillar G's classifier-precision/recall dashboard reads `reply_classified` events filtered by `category` + `classification_method`; per-channel reply-rate funnels read the new `*_reply_received` event types via the closed-set REPLY_EVENT_TYPES. Pass H / I / J's `PassResult` records feed the per-pass health dashboards. The Cal.com booking-reply gap (D113) means Pillar G's calendar-reply dashboard reads `calendar_booking_confirmed` / `_rescheduled` / `_cancelled` directly (not via a synthetic reply-event hop).

* **Pillar H (daemon + dispatcher).** Pillar H's daemon will run Pass H / I / J alongside the existing intent-recovery passes; the per-channel rate-limit pool considerations (LinkedIn MCP, Twitter cookie-scrape) apply to both. The daemon's reply-detection cadence (TBD per Pillar H's ADR) may be more frequent than the intent-recovery cadence — replies are higher-frequency per-prospect than orphan intents.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel reply state isolation. The Pillar I doctor preflight extends to check the per-category pattern file existence + schema-conformance. The Pillar I CLI ships:
  - `python -m orchestrator.classifier replay --since <date>` (Week 2's forward-reference) for the one-time backfill of pre-Pillar-D-Week-1 + pre-Week-3 replies against the new long-tail categories.
  - `python -m orchestrator.calendar_reply manual <booking_id> <category>` for the Cal.com per-booking comment-reply path (D113's deferred Pass K).

* **Pillar J (security + compliance).** Pillar J's CAN-SPAM compliance gate continues to consume only `category=unsubscribe` events per ADR-0025 D100. The long-tail categories are NOT routed to the auto-unsubscribe handler (Week 4-5 onward) — only `category=unsubscribe` triggers suppression. Operators with conservative compliance posture MAY tune `rejection-patterns.yml`'s borderline-unsubscribe pattern 10 ("please do not follow up") into `unsubscribe-patterns.yml` — the inline notes in `rejection-patterns.example.yml` document the operator-tuning workflow.

## Migration / rollout

The Week 3 deliverable is the long-tail classifier extension + per-channel reply detection passes + per-week trajectory doc for Week 4-5.

**Operator-facing changes (Week 3):**

1. **No new pending migrations.** `runner.pending()` still returns 15 (the Pillar C final state preserved through Pillar D Week 1 + 2 + 3). Pillar D Week 4-5+ MAY ship vault migrations to add per-Person `conversation_status:` field denormalization OR per-touch `reply_state:` field stamping — TBD per the Week 4-5 ADR.

2. **Four new factory pattern files in `config-template/`:**
   - `ooo-patterns.example.yml` (10 conservative defaults)
   - `wrong-person-patterns.example.yml` (10 conservative defaults; the +1 redirect pattern split across two regex rows for clarity)
   - `interest-patterns.example.yml` (10 conservative defaults)
   - `rejection-patterns.example.yml` (10 conservative defaults)

3. **Operator bootstrap for the long-tail categories (OPTIONAL):**

   ```bash
   cp config-template/ooo-patterns.example.yml ~/.outreach-factory/classifier/ooo-patterns.yml
   cp config-template/wrong-person-patterns.example.yml ~/.outreach-factory/classifier/wrong-person-patterns.yml
   cp config-template/interest-patterns.example.yml ~/.outreach-factory/classifier/interest-patterns.yml
   cp config-template/rejection-patterns.example.yml ~/.outreach-factory/classifier/rejection-patterns.yml
   ```

   Operators skipping a category get an empty pattern list for that category → that category never fires → falls through to the next priority or uncategorized. No regression vs Week 2's posture for the skipped categories.

4. **Pass H / I / J in the reconcile chain.** `python -m orchestrator.reconcile --full` defaults to `"A,B,C,D,H,E,I,F,J,G"` (previously `"A,B,C,D,E,F,G"`). Operators using `--full` get the per-channel reply detection automatically. `--quick` is UNCHANGED (Pass A only).

5. **CLI flag changes.** Existing `--linkedin-scan-limit` + `--twitter-scan-limit` apply to Pass H / I + Pass J respectively (the same MCP rate-limit pools). No new flags required.

**Existing-operator interaction.** Pre-Pillar-D-Week-3 operators with Pillar D Week 2's classifier deployed:

* Continue to receive unsubscribe-only classification (the long-tail categories default to empty pattern lists until the operator copies the factory files).
* Pass G's behavior is UNCHANGED for `reply_received` events (email; Pass B emits) — Week 3 widens the input filter but Week 2 emissions still flow through the same classifier dispatch.
* The Week 2 single-file classifier (constructed via `RuleBasedClassifier.from_yaml(path)`) continues to work; the new `RuleBasedClassifier.from_yaml_dir(dir)` is the Week 3 entry point for operators upgrading to the long-tail.

**Per-channel reply detection — operator-visible surface.** Operators observing the new per-channel reply event classes can query the ledger:

```bash
# All Week 3+ per-channel reply events:
python -m orchestrator.ledger grep --type li_invite_reply_received
python -m orchestrator.ledger grep --type li_dm_reply_received
python -m orchestrator.ledger grep --type tw_dm_reply_received

# Per-prospect reply timeline (Pillar G dashboard preview):
python -m orchestrator.ledger query --person <pid> --type-pattern '*_reply_received'
```

The `funnel` CLI's by_type breakdown surfaces per-channel reply counts for free per ADR-0025 D99's audit (the `funnel` walks all events + counts every type).

**The Week 3 commit's verification surface:**

```bash
# 1. The classifier extension's regression tests + per-category dispatch.
python -m pytest tests/test_reply_classifier.py -v
# Expected: 221 passing (76 Week 2 baseline + ~145 Week 3 additions across 8 new test classes).

# 2. Pass H / I / J unit tests.
python -m pytest tests/test_reconcile_pass_h_i_j.py -v
# Expected: 42 passing.

# 3. The coherence vehicle's un-skipped Week 3 rows.
python -m pytest tests/test_multi_channel_coherence.py::TestReplyClassification -v
# Expected: 7 passing + 1 skipped (Cal.com per D113 deferral).

# 4. The full suite is green at 1930 + N (Week 3 ~ +190 net new tests).
python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 2120 passed, 19 skipped (down from 22 — 3 Week 3 rows un-skipped).

# 5. ADR-0027 exists; README index gains the row; PILLAR-PLAN §6 Pillar D row flipped.
ls docs/adr/0027-pillar-d-long-tail-and-per-channel-reply-detection.md
grep "0027" docs/adr/README.md
grep "Week 1 ✓ + Week 2 ✓ + Week 3 ✓" docs/PILLAR-PLAN.md

# 6. No new pending migrations.
python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print('pending:', len(r.pending()))"
# Expected: pending: 15
```

### Existing-operator seed

Pillar D Week 3 ships NO new migrations + NO new ledger-state primitives that require an existing-operator seed.

The four new factory pattern files are operator-bootstrap surfaces (OPTIONAL — absence means "uncategorized fallback for that category"). The per-channel reply detection passes are emit-only against pre-existing `*_confirmed` ledger events — operators with pre-Pillar-D-Week-3 `li_invite_confirmed` / `li_dm_confirmed` / `tw_dm_confirmed` events will see Pass H / I / J retroactively emit replies for any in-window matches on the next `--full` run; the asymmetric-failure-cost calculus (PILLAR-PLAN §0) favors the retroactive emit (the classifier's visibility-now is better than visibility-from-Week-3-onward-only).

The first Pillar D week that ships a migration requiring an existing-operator seed is Week 4-5 (the auto-unsubscribe handler + conversation-state machine — TBD per ADR-0028); that ADR carries the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface Pillar D's auto-unsubscribe write integrates with (Week 4-5+; no engine change required for Week 3).
- ADR-0003 (channel as first-class policy predicate) — the cross-channel rule whose behavior Pillar D Week 3 events deliberately don't trigger (the new reply events don't end in `_confirmed`).
- ADR-0014 (Pillar C foundation) — D33's channel-on-every-event invariant Week 3's new event classes inherit; D37's exit-criterion vehicle Pillar D extends per ADR-0025 D101.
- ADR-0017 (Pillar C reconcile passes D + E) — D48 + D49 + D50's asymmetric-failure-cost calculus Pillar D's per-channel reply passes inherit; the `LinkedInClientLike` Protocol Pass H / I extend.
- ADR-0018 (Pillar C Twitter DM) — D58's marker scheme + D59's cookie-scrape MCP context + D62's `_run_channel_intent_pass` helper Pillar D Week 3's `_run_channel_dm_reply_pass` helper mirrors.
- ADR-0019 (Pillar C calendar booking) — D66's webhook-driven recovery pattern Pillar D Week 3 explicitly does NOT extend (Pass K deferred per D113).
- ADR-0025 (Pillar D foundation) — D96 (per-channel reply event-type naming) + D97 (classifier output convention + load-bearing legal-liability invariant) + D98 (conversation state shape) + D99 (cross-pillar audit) + D100 (auto-unsubscribe contract) + D101 (exit-criterion vehicle).
- ADR-0026 (Pillar D Week 2 classifier bootstrap) — D102 (module placement) + D103 (pattern-list YAML format + location) + D104 (idempotence by `(reply_message_id, channel)`) + D105 (Pass G in reconcile chain) + D106 (audit row extension) + D107 (Week 2 unsubscribe-only scope + uncategorized fallback + Week 4-5 handler deferral).
- `docs/PILLAR-PLAN.md` §2 Pillar D — exit criterion (binding text); §5 "What we will not do" — the unsubscribe = rule-based ONLY constraint D110 preserves; §6 Pillar D row updated to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓".
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies the long-tail categories' rule-based-first posture (Week 6-8 LLM fallback extends; the unsubscribe path stays rule-based ONLY).
- `docs/RISK-REGISTER.md` R013 (operator pattern-list misconfiguration) — extended to the long-tail categories Week 3. R014 (per-channel reply false-emit) — NEW Week 3 — mitigated by the from_self=False filter + the per-channel thread-id filter + the classifier's uncategorized fallback.
- `docs/SOURCES-OF-TRUTH.md` — Week 2 row "Classifier pattern lists" covers the directory-union semantics for multi-file shape; Week 3's per-category files land under it (no row change required).
- `.planning/REVIEW-pillar-d-surface-audit.md` — D114's audit extension. Pillar D Week 3 audit row covers the new per-channel reply event classes + Pass G's filter widening + the new Pass H / I / J ledger-walk patterns.
- `.planning/HANDOFF-pillar-d-week-3.md` — the per-week handoff that scoped Week 3.
- `.planning/HANDOFF-pillar-d-week-4.md` — the Week 3 commit's sibling document scoping Week 4-5 (auto-unsubscribe handler + conversation state machine + the LOAD-BEARING dedup-by-(reply_message_id, channel) requirement carry-over from Week 2's per-week reviewer's P2-B).
- `orchestrator/reply_classifier.py` — the classifier module; Week 3 extends with per-category pattern lists + `DISPATCH_PRIORITY` + `load_pattern_file` + `from_yaml_dir`.
- `orchestrator/reconcile.py::run_pass_h`, `::run_pass_i`, `::run_pass_j`, `::_run_channel_dm_reply_pass`, `::_li_invite_accept_reply_message_id`, `::_synthesize_dm_reply_message_id`, `::REPLY_EVENT_TYPES`.
- `tests/test_reply_classifier.py::TestOOOClassification`, `::TestWrongPersonClassification`, `::TestInterestClassification`, `::TestRejectionClassification`, `::TestCategoryPriorityOrder`, `::TestLongTailPatternLoading`, `::TestFromYamlDir`, `::TestPerCategoryConstructorBackwardsCompat`, `::TestUncategorizedFallback`, `::TestPassHIJSymbolSurface`.
- `tests/test_reconcile_pass_h_i_j.py` — the new per-pass test file (42 tests).
- `tests/test_multi_channel_coherence.py::TestReplyClassification` — 3 un-skipped Week 3 rows (LinkedIn invite reply / LinkedIn DM reply / Twitter DM reply); Cal.com row remains skipped per D113.
- Forward-references (planned):
  - **ADR-0028** (Pillar D Week 4-5): auto-unsubscribe handler + conversation state machine + the dedup-by-`(reply_message_id, channel)` requirement carry-over from Week 2's P2-B.
  - **ADR-0029** (Pillar D Week 6-8): LLM fallback for the long-tail categories + classifier-cap policy migration (`policy/0007_add_reply_classifier_llm_cap` — TBD shape).
  - **Pillar I CLI** (Weeks 43-48): `python -m orchestrator.classifier replay --since <date>` for the one-time backfill of pre-Pillar-D-Week-3 replies + `python -m orchestrator.calendar_reply manual <booking_id> <category>` for the Cal.com comment-reply path (D113's deferred Pass K).
