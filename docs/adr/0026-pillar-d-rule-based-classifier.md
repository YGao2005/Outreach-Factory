# ADR-0026: Pillar D Week 2 — rule-based reply classifier (bootstrap)

- **Status:** Accepted
- **Date:** 2026-05-23
- **Pillar:** D (Reply + conversation handling — Week 2 classifier bootstrap)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0025 (Pillar D Week 1 foundation) pinned the per-channel reply event-type naming (D96), the classifier output convention as a separate `reply_classified` event class (D97), the conversation state shape (D98), the cross-pillar surface audit (D99), the auto-unsubscribe enforcement contract (D100), and the exit-criterion vehicle scope (D101). The Week 1 commit shipped the foundation ADR + the load-bearing surface audit + the Pass B P2-A fix (`channel: "email"` stamped on every emitted `reply_received` + `bounce_detected`) + the test-vehicle stubs in `tests/test_multi_channel_coherence.py`.

**Pillar D Week 2 is the classifier bootstrap.** The handoff (`.planning/HANDOFF-pillar-d-week-2.md` — committed in the Week 1 follow-up) scopes Week 2 to the rule-based classifier's foundation primitive + the unsubscribe rule list + the unsubscribe-detection pass. Week 3 extends to the other five categories (ooo / wrong_person / interest / rejection / uncategorized) AND per-channel reply detection for LinkedIn / Twitter / calendar. The two-week split lets the unsubscribe path — the legal-liability path per PILLAR-PLAN §5 — land + verify in isolation before extending to the long-tail categories. Auto-unsubscribe enforcement (the YAML-first write contract per ADR-0025 D100) lands Pillar D Week 4-5; Week 2 emits the events the future handler will read.

The six concerns this ADR resolves:

1. **The classifier module's PLACEMENT must be pinned before the implementation lands.** Three plausible homes: (a) `orchestrator/reply_classifier.py` (top-level, sibling of `policy/`); (b) `orchestrator/policy/classifier.py` (inside the policy directory despite the classifier not being a rule); (c) `orchestrator/classifier/` (new top-level subpackage). D102 picks (a).

2. **The pattern-list YAML's FORMAT and LOCATION must be pinned before operators consume it.** The classifier reads operator-tunable regex patterns from a YAML file. Three plausible locations: (a) `~/.outreach-factory/classifier/*.yml` (new SoT row analogous to `~/.outreach-factory/suppressions/*.yml`); (b) `~/.outreach-factory/policies/classifier.yml` (inside the policies directory); (c) inline constant in source code (operator must fork code to tune). D103 picks (a) + adds a new SoT registry row + ships `config-template/unsubscribe-patterns.example.yml`.

3. **Idempotence-by-key must be pinned so reruns are safe.** The classifier pass walks `reply_received` events; rerunning must NOT produce duplicate `reply_classified` events. The discriminator is the (reply_message_id, channel) pair — channel is required because LinkedIn / Twitter / calendar use platform-specific message-id namespaces that could collide with gmail_message_ids by coincidence. D104 pins the pair.

4. **The classifier pass's INVOCATION cadence + ordering + CLI surface must be pinned.** The pass extends the existing reconcile chain. Three options: (a) add Pass G to `ALL_PASSES` (the natural extension); (b) make the classifier a standalone CLI (`python -m orchestrator.classifier`); (c) inline the classifier in Pass B (mixes detect + classify concerns). D105 picks (a) + extends `--full` to `"A,B,C,D,E,F,G"` + adds `--classifier-rule-list` for pattern-list override.

5. **The cross-pillar surface audit (per ADR-0025 D99) MUST be extended row-by-row each Pillar D week.** Week 2 ships the `reply_classified` event class, which lands in `_idx_person` (broadens) + introduces a NEW idempotence-discriminator consumer (Pass G itself walks all events to build the (reply_message_id, channel) index). D106 names the audit extension + the new consumer surface.

6. **The auto-unsubscribe HANDLER must be deferred to Week 4-5** so the classifier's event emit can be verified in isolation before the YAML-first write contract (per ADR-0025 D100) lands. Three options: (a) ship the classifier + handler together in Week 2 (couples two failure-mode surfaces in one commit); (b) ship the handler in Week 3 with the other 5 categories (different concerns); (c) defer the handler indefinitely + require manual operator append (violates D100's 60-second SLA). D107 picks Week 4-5 deferral.

Risks this ADR mitigates by design: **R012 (LLM hallucinates unsubscribe → over-suppression)** is mitigated structurally — Week 2's classifier IS rule-based ONLY; the LLM is never consulted; the `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_unsubscribe_classification_method_is_always_rule` un-skipped row enforces. **R010 (regulatory shift)** continues mitigated by ADR-0025 D100 — the classifier's emit is one half of the auto-unsubscribe pipeline; the handler ships Week 4-5 and the 60-second SLA lands with it.

A new risk surfaces in this ADR's authoring + named in `docs/RISK-REGISTER.md`: **R013 (operator pattern-list misconfiguration → suppression coverage gap or over-suppression)** — operators with no `~/.outreach-factory/classifier/unsubscribe-patterns.yml` get no classifier coverage; operators with overbroad patterns (e.g., a bare `\bstop\b` regex catching "stop by my office") get false-positive unsubscribes that, post-Week-4-5, would trigger auto-suppression. The defenses: (i) Pass G refuses to run with a clear error message + remediation instructions when no pattern file exists (no silent default to factory file — the operator must explicitly bootstrap); (ii) the factory `unsubscribe-patterns.example.yml` ships CONSERVATIVE defaults (every pattern accompanied by an inline rationale + a known-false-positive note); (iii) ADR-0025 D100's asymmetric-failure-cost calculus continues to apply — a false-positive suppression is one missed conversation (recoverable); the 60-second SLA only takes effect Week 4-5 when the handler lands, so Week 2's operator can review classified events before any irreversible action.

## Decision

### D102. Classifier module placement — `orchestrator/reply_classifier.py`

The classifier ships as a single top-level module under `orchestrator/`, sibling of the `policy/` subpackage:

```
orchestrator/
├── reply_classifier.py       ← NEW (Pillar D Week 2)
├── policy/                   ← Pillar A (policy rule classes)
├── migrations/               ← Pillar B (migration framework)
├── ledger.py
├── reconcile.py              ← extended with Pass G (D105)
└── ...
```

**The classifier is a pillar primitive, not a policy rule.** Policy rules (`orchestrator/policy/*.py`) implement the `evaluate(ctx) → RuleResult` contract — they CONSUME events to make gate decisions. The classifier implements a different contract — it PRODUCES events (it walks `reply_received` events + emits `reply_classified` events). Conflating the two surfaces would invite confusion: a future contributor reading `orchestrator/policy/classifier.py` would expect a rule class with `evaluate(ctx)`, not an event producer with `classify(reply_event)`.

**Top-level placement matches the existing per-primitive convention.** `orchestrator/ledger.py` + `orchestrator/reconcile.py` + `orchestrator/identity.py` + `orchestrator/cal_com_webhook.py` are each single-file pillar primitives. The classifier follows the same shape. A `orchestrator/classifier/` subpackage would be over-organization for one module; if Pillar D Week 6-8's LLM fallback grows the surface beyond one file, a subpackage split lands then with an ADR amendment.

**The pass implementation lives in `orchestrator/reconcile.py` (extending `run_pass_a` … `run_pass_f` with `run_pass_g`)**, NOT in `orchestrator/reply_classifier.py`. Rationale: the pass IS part of the reconcile chain (D105 below) + the existing `run_pass_*` symbols are the reviewer-discoverable surface for "what does reconcile do?". The classifier module exposes the primitives (`RuleBasedClassifier` + `ClassifierResult` + `emit_classified_event`); the pass orchestrates the primitives within the reconcile lifecycle.

### D103. Pattern-list YAML format + location + SoT registry row

Operators tune the unsubscribe regex pattern list via a YAML file at `~/.outreach-factory/classifier/unsubscribe-patterns.yml`. The factory ships `config-template/unsubscribe-patterns.example.yml` operators copy on bootstrap.

**Schema:**

```yaml
# ~/.outreach-factory/classifier/unsubscribe-patterns.yml
version: 1
patterns:
  - "(?i)\\bunsubscribe\\b"
  - "(?i)\\bremove me from your (email )?list\\b"
  - "(?i)\\bplease stop (emailing|contacting)( me)?\\b"
  - "(?i)\\bdo not (contact|email) me( again)?\\b"
  - "(?i)\\bopt[- ]?out\\b"
  # ... more patterns; operator-tunable
```

* **`version: 1`** is REQUIRED; future schema additions (e.g., pattern weights for partial-match scoring; per-language pattern sets) bump the version + ship through a Pillar B `policy/000N` migration (TBD week).
* **`patterns:`** is a list of Python regex source strings. Patterns SHOULD use `(?i)` for case-insensitivity (the classifier ALSO applies `re.IGNORECASE` defensively, so the inline flag is redundant but operator-clarifying). Each pattern is compiled once at classifier construction time; a malformed regex raises `PatternLoadError` at load time (no silent skip — refuse loud per the ADR-0019 D67 calculus).
* **Comments are encouraged.** Operators reading the file after months should see the rationale for each pattern + any known false-positive notes. The factory example carries inline comments as the discoverable convention.

**SoT registry row added to `docs/SOURCES-OF-TRUTH.md`:**

```
| Classifier pattern lists (operator-tunable regex patterns for reply classification) |
  `~/.outreach-factory/classifier/*.yml` (with `version:`; directory union — multiple files
  merge if Week 3+ adds per-category files like `ooo-patterns.yml` / `rejection-patterns.yml`) |
  — | — |
  Pillar D. Pattern-driven, not rule-driven — separate cadence + editor + format from policy YAML.
  ADR-0026 D103 specifies the schema. The unsubscribe pattern list is the legal-liability surface
  (CAN-SPAM) per ADR-0025 D97 — false-negatives become missed unsubscribes; false-positives
  become missed conversations. Operator-curated with conservative factory defaults.
```

**Why not `~/.outreach-factory/policies/classifier.yml`?** Conflates classifier patterns (event-emit primitive) with policy rules (gate decisions). Operators inspecting `policies/` expect rules they could simulate via `python -m orchestrator.policy simulate`; classifier patterns have no equivalent simulation surface. The directory-per-purpose convention from ADR-0004 (suppression split off the policy row) carries here.

**Why not inline factory defaults in source?** Operators can't tune the regex set without a code fork. Pattern-tuning is the FIRST operator-facing knob Pillar D ships; the asymmetric-failure-cost calculus (PILLAR-PLAN §0) biases toward operator-tunable from Day 1. The factory ships conservative defaults so the bootstrap experience is "copy + go"; advanced operators tune.

**Why not require `--classifier-rule-list <path>` on every Pass G invocation?** The default location convention (`~/.outreach-factory/classifier/unsubscribe-patterns.yml`) matches the `~/.outreach-factory/{suppressions,policies}/` convention so operators don't have to remember per-run flags. The `--classifier-rule-list` flag is the ESCAPE VALVE for tests + per-environment override; the bootstrap experience is `cp config-template/unsubscribe-patterns.example.yml ~/.outreach-factory/classifier/unsubscribe-patterns.yml` once + run `python -m orchestrator.reconcile --full` thereafter.

**Bootstrap-failure error message.** If Pass G is requested but no pattern file is found at the resolved path, Pass G's PassResult carries an error of the form:

```
Pass G: classifier pattern file not found at <path>.
  Bootstrap: mkdir -p ~/.outreach-factory/classifier && \
             cp config-template/unsubscribe-patterns.example.yml \
                ~/.outreach-factory/classifier/unsubscribe-patterns.yml
  Then re-run with --full (or --passes G).
```

The refuse-loud posture mirrors the `Pass D requires a LinkedIn client` / `Pass F requires a Twitter client` error shape from ADRs 0017 + 0018. Operators see a clear remediation step; no silent fallback to factory file (silent fallback would mean the operator's classifier is the FACTORY's, not the operator's — divergent semantics across installs).

### D104. Idempotence by (reply_message_id, channel)

Pass G's idempotence key is the `(reply_message_id, channel)` PAIR. The pass:

1. Walks every `reply_classified` event in the ledger; builds a `set[tuple[str, str]]` of (reply_message_id, channel) pairs.
2. Walks every `reply_received` event in the requested window; for each one, computes the pair (mid, ch) where `mid = event["gmail_message_id"]` (the existing field on Pass B's emit shape) and `ch = event["channel"]` (the field stamped by ADR-0025 D96's P2-A fix; defaults to `"email"` for pre-Week-1 events per ADR-0025 §Migration/rollout item 3).
3. Skips reply events whose pair is already in the set.
4. For each remaining reply event, dispatches to the classifier + emits a `reply_classified` event.

**Why the pair (not just `reply_message_id`)?** Per Pillar D Week 3+ when per-channel reply detection lands, LinkedIn / Twitter / calendar replies use platform-specific message-id namespaces. A bare `linkedin_message_id` could in principle collide with a gmail_message_id by coincidence (both are opaque opaque-string identifiers from third parties). The (mid, channel) pair guarantees uniqueness across channels.

**Why not (reply_message_id only) under the assumption that the namespaces don't collide?** The framework's invariant I4 (reproducible state per PILLAR-PLAN §1) demands that the idempotence key be discriminative regardless of platform behavior. A future LinkedIn API change that swapped to gmail-shaped opaque tokens would not regress Pillar D's idempotence under the pair-keyed approach; under the bare-mid approach, it would silently collide. The Pillar C Week 12 retrospective's lesson (don't assume invariants you haven't pinned) carries here.

**Why not `reply_to_intent_id` as the discriminator?** Pre-Pillar-D-Week-1 Pass B emits have no `reply_to_intent_id` field (ADR-0025 D96 names this as a future per-channel-reply-pass field, not a Pass B field). Using intent_id as the key would require backfilling intent_id on every existing Pass B emit (cross-pillar invasive) OR special-casing email-replies (forks the discrimination logic). The (reply_message_id, channel) pair is uniform across all channels Week 1+.

**Defense-in-depth: classifier marks-seen during pass execution.** Within a single Pass G run, after classifying a reply, the (mid, ch) pair is added to the in-memory set so a duplicate reply event in the same window (shouldn't happen — gmail_message_id is unique on Pass B's emits — but defense in depth) doesn't double-classify. The protection is belt-and-suspenders alongside the ledger-state idempotence check.

**Pin:** `tests/test_reply_classifier.py::test_classifier_idempotent_against_already_classified_replies` + `tests/test_multi_channel_coherence.py::TestReplyClassification::test_classifier_idempotent_against_already_classified_replies` (un-skipped Week 2).

### D105. Pass invocation cadence — Pass G added to the reconcile chain

The classifier pass joins the existing reconcile chain as Pass G:

```python
ALL_PASSES = ("A", "B", "C", "D", "E", "F", "G")  # G added Week 2
```

**Position in the chain.** Pass G runs AFTER Pass B (and after the channel-specific reply detection passes Week 3 lands as Pass H / I / etc. — TBD per Week 3's ADR). The dependency: Pass G classifies events emitted by Pass B (email replies) + the future per-channel reply passes. The chain ordering is by data-flow (producers before consumers); the existing A → B → C → D → E → F → G order satisfies this.

**`--full` invocation extended.** `python -m orchestrator.reconcile --full` defaults to `"A,B,C,D,E,F,G"` (previously `"A,B,C,D,E,F"`). Operators using `--full` get classifier coverage automatically once they've bootstrapped the pattern file (D103).

**`--quick` invocation UNCHANGED.** `--quick` continues to run Pass A only (the email-intent-recovery hot path). Classifier runs are NOT in the per-batch send-gate's freshness-check path — classification can be deferred to the next `--full` run without blocking sends. (Pillar H's daemon-eventually-runs-classifier-on-classifier-cadence — distinct from send-gate cadence — is the longer-term polish for Week-2-deferred operators.)

**New CLI flag — `--classifier-rule-list`.** The flag accepts a path overriding the default `~/.outreach-factory/classifier/unsubscribe-patterns.yml`. Useful for: test injection (CI / pytest); per-environment overrides (staging vs prod); operator A/B testing of pattern-set tuning.

**Pass G requires no external client.** The classifier is a pure FRAMEWORK operation (regex + ledger walk); unlike Passes A/B (Gmail), D/E (LinkedIn), F (Twitter), Pass G has no platform dependency. The signature is `run_pass_g(*, led, classifier, since, apply) → PassResult`.

**Why NOT a standalone CLI (`python -m orchestrator.classifier`)?** Standalone CLI fragments the operator's mental model — "to reconcile state, run reconcile; to classify replies, run classifier?". The reconcile chain is the framework's canonical periodic-healing surface; classifier IS a reconcile pass (in the abstract sense: it brings the framework's classifier-output state into agreement with the framework's reply-event state). Operators already know `python -m orchestrator.reconcile --full`; Pass G joins that operation. A future Pillar I CLI MAY ship `python -m orchestrator.classifier replay --since <date>` as a standalone for the one-time backfill of pre-Pillar-D-Week-1 replies; that's a different surface (replay against pre-existing state) from the periodic reconcile surface.

**Why NOT inline in Pass B?** Pass B's job is DETECT (inbox ↔ ledger). The classifier's job is INTERPRET (reply text → category). Combining them couples two failure-mode surfaces (Gmail API errors + regex-pattern-misconfiguration) in one pass. A failure in classification should not roll back the detection (the reply event MUST land regardless of whether classification succeeded). Separate passes give separate `PassResult` records → operators see per-pass health + per-pass error breakdowns.

**Why NOT lazily-on-write (the classifier triggers from `Ledger.append` whenever a `reply_received` event lands)?** Mixes write-path concerns with read-only-walk concerns. The `Ledger.append` primitive (ADR-0011 D24) is deliberately single-purpose (atomic append; no side effects). A future operator with a stuck regex (e.g., a catastrophic backtracking pattern) would experience write-path latency. Periodic reconcile gives operators the failure-mode boundary they expect.

### D106. Cross-pillar audit row extension (per ADR-0025 D99)

The Week 2 commit extends `.planning/REVIEW-pillar-d-surface-audit.md` with new rows for:

1. **`_idx_person` consumption.** `reply_classified` events carry `person_id` → land in `_idx_person`. Every `query_by_person` consumer is already audited (per the Week 1 audit's §Ledger query methods section); the new event type lands in their result sets. Audit verdict for each consumer:
   * **`CrossChannelTouchRule.evaluate`** — filters `endswith("_confirmed")`. `reply_classified` does NOT match. **SAFE.**
   * **`cooldown._confirmed_send_intent_pairs`** — literal `t == "send_intent" OR "send_confirmed"`. `reply_classified` does NOT match. **SAFE.**
   * **`DomainThrottleRule.evaluate`** — literal `t != "send_confirmed"`. `reply_classified` does NOT match. **SAFE.**
   * **`derived_stage`** — closed dispatch table `_STAGE_BY_EVENT_TYPE`. `reply_classified` is NONE. **SAFE.**
   * **`Pass G itself`** — walks `all_events()` filtering `type == "reply_classified"` (to build the idempotence index) + `type == "reply_received"` (to find candidates). LITERAL filter. **SAFE-by-construction.**

2. **`_idx_gmail_thread` consumption (intended broadening).** When the reply is on an email thread, `reply_classified` is emitted with `gmail_thread_id` (preserved from the originating reply event) so `query_by_gmail_thread_id` returns the classifier output alongside the reply + the originating send. Pillar G dashboards can query "every event on this thread chronologically" to render the conversation timeline. The broadening is intentional + operator-useful.

3. **A new ledger-walk pattern: the classifier-output idempotence index.** Pass G's idempotence check builds a set of (reply_message_id, channel) pairs from `reply_classified` events. The new pattern is structurally analogous to Pass B's `query_by_gmail_message_id` idempotence check (per the Week 1 audit's §Reconcile surfaces section). Both patterns are CLOSED-set protected (the literal-string filter on `type == "reply_classified"` forecloses Pass-A-class broadening). **SAFE.**

The audit's verdict carries: zero new P1 latent-bug patterns introduced by Week 2; the `reply_classified` event class's consumer surface is fully covered by the Week 1 audit's existing-consumer enumeration + the new pattern is closed-set-protected.

**Pin:** `.planning/REVIEW-pillar-d-surface-audit.md` updated in the Week 2 commit with the new rows. Future Pillar D weeks consult the audit before adding new event classes or new consumers; the audit grows with the pillar.

### D107. Auto-unsubscribe handler deferred to Pillar D Week 4-5

Week 2 emits `reply_classified` events with `category: "unsubscribe"` but does NOT write to the suppression YAML. The handler that consumes the events + writes to `~/.outreach-factory/suppressions/auto-unsubscribe.yml` (per ADR-0025 D100) lands Pillar D Week 4-5 alongside the conversation state machine.

**Why the two-week split.** Both the classifier emit + the handler write are correctness-critical surfaces. Bundling them in one commit would:

* **Couple two failure-mode surfaces in one commit.** A bug in the classifier's pattern matching would corrupt the suppression YAML; a bug in the handler's atomic write would lose audit trail. Decoupling lets each surface be verified in isolation against focused tests.
* **Block the classifier's operator-visible value pending the handler's completion.** Operators can review classified events in the ledger (`python -m orchestrator.ledger grep --type reply_classified`) starting Week 2; the auto-suppression follows in Week 4-5 once operators have built confidence in the pattern-set tuning.
* **Increase the blast radius of a Week 2 mistake.** A pattern misconfiguration in Week 2 produces wrong `reply_classified` events that operators can correct (delete the event class via a one-time `policy.py forget --person <id>` undo for any over-suppression; tune the pattern; re-run); the same mistake in a coupled Week 2 = classifier + handler would have written to the suppression YAML before the operator caught it.

**Week 2 operator-visible surface.** Operators see classifier output by querying the ledger:

```bash
$ python -m orchestrator.ledger grep --type reply_classified
{"type":"reply_classified","person_id":"...","channel":"email",
 "reply_message_id":"gid_001","category":"unsubscribe",
 "classification_method":"rule","confidence":1.0,
 "matched_pattern":"\\bunsubscribe\\b","_emitted_by":"reply_classifier","ts":"..."}
```

If the classifier produces a false-positive unsubscribe in Week 2 (e.g., the operator's pattern set is too broad), the operator can: (i) tune the pattern set; (ii) re-run Pass G with a tighter pattern set (the existing classified event STAYS — append-only ledger — but the operator's review pipeline can prompt manual review of false-positive entries); (iii) when Week 4-5's handler ships, the handler reads classified events from a START_TS forward, so old false-positive classifications don't trigger auto-suppression of already-onboarded prospects.

**Week 4-5 handover.** The Week 4-5 handler reads `reply_classified` events (filtering `category == "unsubscribe"`) + writes to the suppression YAML per ADR-0025 D100's YAML-first + ledger-second contract. The handler also emits `suppression_added` events linking back to the originating `reply_classified` event (per ADR-0025 D100's event shape). The handler is a sibling consumer of Week 2's emit; the contract between them is the `reply_classified` event shape pinned by ADR-0025 D97 + this ADR's confirmation of the schema.

**Asymmetric-failure-cost calculus for Week 2's emit-only posture.** Per PILLAR-PLAN §0: the cost of a missed Week-2 unsubscribe is one prospect we MAY send to one extra time (the classifier doesn't auto-suppress; the operator's manual review catches it). The cost of a false-positive Week-2 unsubscribe is one ledger entry the operator can ignore. The cost of a Week-2 classifier bug that lands the handler in Week 4-5 with corrupt suppression state is much higher; the two-week split bounds the failure cost to the smaller of the two failure modes.

**Uncategorized-fallback.** Week 2's classifier returns `category: "uncategorized"` (with `classification_method: "rule"`, `confidence: 1.0`, `matched_pattern: None`) for any reply that doesn't match the unsubscribe patterns. Week 3 extends to the other five categories (ooo / wrong_person / interest / rejection); Week 3's classifier replaces the "uncategorized" fallback with rule-matching for the long-tail categories + a remaining fallback for replies that match none of the six categories. The uncategorized fallback IS an emit (not a no-op) so the operator's ledger has full visibility into "the classifier saw this reply but had no match" — distinct from "the classifier didn't see this reply" (Pass G error path).

## Alternatives considered

### D102-Alt1: Place the classifier inside `orchestrator/policy/`

`orchestrator/policy/classifier.py`. **Rejected** because:

* Conflates the event-PRODUCER surface (classifier) with the event-CONSUMER surface (policy rules). A future contributor reading `orchestrator/policy/` expects rule classes that implement `evaluate(ctx) → RuleResult`; the classifier doesn't.
* `orchestrator/policy/__init__.py` re-exports every rule class for the engine's rule-name → class dispatch. Adding the classifier to this re-export would either pollute the rule namespace OR require an exclusion mechanism — both worse than placement elsewhere.
* The classifier's tests would land in `tests/test_policy_*.py` by convention; the test file's audience (policy rule shape verifiers) doesn't match the test content (event-producer regex verification).

### D102-Alt2: Spin up a `orchestrator/classifier/` subpackage

`orchestrator/classifier/__init__.py` + `orchestrator/classifier/rule_based.py` + `orchestrator/classifier/patterns.py` + ... **Rejected** because:

* Over-organization for Week 2's scope (~150 LOC of classifier code). The single-file convention used by `orchestrator/ledger.py` + `orchestrator/identity.py` + `orchestrator/cal_com_webhook.py` is the precedent for a pillar primitive that fits in one module.
* The subpackage rationale would land in Pillar D Week 6-8 when the LLM fallback adds enough surface area to warrant the split. Premature subpackaging in Week 2 invites refactoring debt + would land code in module boundaries that don't yet have proven coherence.

### D102-Alt3: Inline the classifier in `orchestrator/reconcile.py`

`run_pass_g` lives in reconcile.py + the classifier's pattern-loading + classification helpers live as private functions in the same file. **Rejected** because:

* reconcile.py is already ~1900 lines (6 passes × ~150 LOC + helpers + CLI). Adding Pillar D's classifier inline would push the file past 2200 lines; future Pillar D weeks would push further. The Week 1 reviewer's "file growth is a concern" carry-forward (per `.planning/REVIEW-pillar-d-surface-audit.md` Week 1 review notes) carries here.
* The classifier MODULE has reusable primitives (`ClassifierResult`, `RuleBasedClassifier`, `load_unsubscribe_patterns`, `emit_classified_event`) that Pillar D Week 3-12+ extends. Encapsulating the primitives in a dedicated module lets future weeks extend without churning reconcile.py.

### D103-Alt1: Hardcode factory defaults in source code; operator can't tune

`UNSUBSCRIBE_PATTERNS = [...]` as a module-level constant in `orchestrator/reply_classifier.py`. **Rejected** because:

* Pattern tuning is the FIRST operator-facing knob Pillar D ships. Operators in different verticals will see different reply phrasings (B2B SaaS unsubscribe phrases differ from consumer-app phrases); requiring code forks to tune is incoherent with the OSS-bring-up posture (Pillar I).
* The asymmetric-failure-cost calculus (PILLAR-PLAN §0): a missed unsubscribe is a CAN-SPAM violation; operator-tuning is the right escape valve. Hardcoding closes the escape valve.
* Operators auditing CAN-SPAM compliance need a single human-readable file to point to — "this is our unsubscribe rule list, version N, last reviewed YYYY-MM-DD." A YAML file with version + comments serves this; a source constant doesn't.

### D103-Alt2: Place the pattern file inside `~/.outreach-factory/policies/`

`~/.outreach-factory/policies/classifier.yml` (alongside the operator's `cooldowns.yml` + `suppressions.yml`). **Rejected** because:

* Conflates classifier patterns (regex match → event emit) with policy rules (rule evaluation → gate decision). Operators inspecting `policies/` expect rules they could simulate via `python -m orchestrator.policy simulate`; classifier patterns have no equivalent simulation surface.
* Pillar A ADR-0004 already established the directory-per-purpose convention by splitting suppression off the policy row. The classifier ships its own directory by symmetry.
* The directory union semantics differ: policy YAML files are MERGED rule-by-rule (a single conceptual rule set across multiple files); classifier pattern files are POTENTIALLY per-category (Week 3+ may ship `ooo-patterns.yml` separately from `unsubscribe-patterns.yml`). Distinct semantics warrant distinct directories.

### D103-Alt3: One pattern file per category (Week 2 ships `~/.outreach-factory/classifier/unsubscribe.yml` only; Week 3 adds `ooo.yml`, `wrong_person.yml`, etc.)

Per-category files starting Week 2. **Rejected for Week 2** (deferred to Week 3's ADR):

* Week 2 ships ONE category (unsubscribe) — premature per-category split. The convention should land when the second category lands.
* The single-file vs per-category-file argument is a Week 3 decision. Week 2's file is named `unsubscribe-patterns.yml` (not `classifier.yml`) so future per-category files (`ooo-patterns.yml`, `wrong_person-patterns.yml`, etc.) follow the naming convention without renaming.
* The directory union semantics (D103 SoT row) accommodate both shapes (single file with all categories OR per-category files); Week 3's ADR picks.

### D104-Alt1: Idempotence by `reply_message_id` only (no channel)

Bare-`mid`-keyed deduplication. **Rejected** because:

* The framework's I4 invariant (reproducible state) demands that the discriminator be defensive against platform-namespace collisions. A future LinkedIn API change that swapped to gmail-shaped opaque tokens would silently collide under bare-mid keying; under (mid, channel) keying, the collision is structurally impossible.
* The (mid, channel) pair carries the same uniqueness guarantee for free (channel field is already required per ADR-0025 D96); adding it to the key has zero runtime cost + maximum defense.
* The Pillar C Week 12 retrospective's lesson (don't assume invariants you haven't pinned) carries here. The cost of pinning the pair is zero; the cost of NOT pinning is a Pass-A-class latent bug 8 weeks later when a per-channel reply id namespace shifts.

### D104-Alt2: Idempotence by `reply_to_intent_id`

Use the intent_id correlation as the deduplication key. **Rejected** because:

* Pre-Pillar-D-Week-1 Pass B emits have NO `reply_to_intent_id` field — the field lands in Week 2+'s per-channel reply detection passes per ADR-0025 D96. Using intent_id as the key would require either backfilling on every existing Pass B emit (cross-pillar invasive) or special-casing email replies (forks the discrimination logic).
* The (reply_message_id, channel) pair is uniform across all channels Week 1+ + works for Pass B's existing email-reply emits. No special-case logic.
* Even WITH `reply_to_intent_id` populated, a single intent could in principle have multiple reply events on the same thread (one recipient replying twice). Discriminating by intent_id alone would dedupe across replies that SHOULD be classified independently. The reply_message_id IS the right grain.

### D104-Alt3: Idempotence by content hash (`sha256(reply_event.body + reply_event.from)`)

Hash the reply payload + use the digest as the discriminator. **Rejected** because:

* Over-engineered. The (reply_message_id, channel) pair already provides the uniqueness guarantee with O(1) lookup; a hash adds CPU cost without correctness gain.
* A content-changing reply rewrite (operator edits the reply text downstream — shouldn't happen but theoretically) would silently produce a duplicate classification under hash keying. The message-id-based pair is more robust.
* Hashing creates a forward-compat hazard: if the hash algorithm changes (sha256 → blake3 in some future Python version), historical idempotence collisions would land. The (mid, channel) pair has no such cliff.

### D105-Alt1: Standalone CLI (`python -m orchestrator.classifier classify --since 30d`)

Classifier as its own CLI surface, NOT part of reconcile. **Rejected** because:

* Fragments the operator's mental model — "to reconcile state, run reconcile; to classify replies, run classifier?" The reconcile chain IS the framework's canonical periodic-healing surface; the classifier IS a healing operation (bringing the classifier-output state into agreement with the reply-event state).
* Operators already know `python -m orchestrator.reconcile --full`; Pass G joins that operation seamlessly.
* The CLI fragmentation invites operator-forgetting (operator runs reconcile but forgets classifier; reply events accumulate unclassified). The unified chain eliminates the forgetting risk.

A FUTURE Pillar I CLI MAY ship `python -m orchestrator.classifier replay --since <date>` as a standalone surface for the ONE-TIME backfill of pre-Pillar-D-Week-1 replies (per ADR-0025 §Migration/rollout item 3) — that's a DIFFERENT surface (replay against pre-existing state) from the periodic reconcile surface, with its own UX rationale.

### D105-Alt2: Inline classifier in Pass B (single combined detect-and-classify pass)

`run_pass_b` calls into the classifier as part of its inbox-walk. **Rejected** because:

* Couples two failure-mode surfaces (Gmail API errors + pattern misconfiguration) in one pass. A classifier failure should not roll back detection (the reply event MUST land regardless).
* Separate passes give separate `PassResult` records → operators see per-pass health + per-pass error breakdowns. Combined pass loses this granularity.
* Pass B already exists as a stable surface (Phase 5.5 territory); extending it with classifier concerns invites regression risk. The additive pass is the safer extension.

### D105-Alt3: Lazy-on-write classifier (classifier triggers from `Ledger.append` whenever a `reply_received` event lands)

Hook the classifier into the ledger's append path. **Rejected** because:

* Mixes write-path concerns with read-only-walk concerns. The `Ledger.append` primitive (ADR-0011 D24) is deliberately single-purpose (atomic append; no side effects). A future operator with a catastrophic-backtracking regex would experience write-path latency.
* The on-write trigger fires inside the writer process — concurrent writers (dispatcher + manual /send-outreach + reconcile + Pillar H daemon) would each independently classify, racing on the (mid, channel) idempotence check. Periodic Pass G + ledger-state idempotence check has clear semantics; on-write doesn't.
* On-write changes the framework's append-only ledger discipline (per ADR-0011 D24): every event was append-only EXCEPT this one event-class that triggered a side-effecting classifier? Inconsistent.

### D106-Alt1: Skip the audit extension; rely on Week 3+ to surface broadening

A weekly audit is overkill for a single new event class. **Rejected** because:

* Per the Pillar C Week 12 retrospective + ADR-0025 D99: every Pillar D week's per-week review MUST extend the audit. Skipping a week creates a precedent that future weeks could skip too — the discipline compounds OR erodes.
* The Week 2 commit adds the SECOND new event class to the ledger (Week 1 added bounce-with-channel + reply-with-channel; Week 2 adds reply_classified). Each addition is small individually; the audit's value is documenting the SMALL additions so the large Pillar D total doesn't surprise.

### D106-Alt2: Land the audit extension in a separate PR after the classifier

Ship the classifier first; ship the audit extension in a Week 2 follow-up. **Rejected** because:

* The audit extension IS part of the Week 2 deliverable per HANDOFF-pillar-d-week-2.md §"Validation gate". Splitting the commit risks the audit landing days/weeks after the code change it documents — exactly the gap the audit discipline is designed to prevent.
* Per the per-week-review-with-follow-up-commit pattern (Pillar A/B/C/D Week 1): the MAIN commit ships every artifact the validation gate names. Follow-up commits address findings the per-week reviewer surfaces; they don't ship deferred-from-main deliverables.

### D107-Alt1: Ship the auto-unsubscribe handler in Week 2 alongside the classifier

Both surfaces land together. **Rejected** because:

* Couples two failure-mode surfaces in one commit. The asymmetric-failure-cost calculus (PILLAR-PLAN §0): the cost of a Week-2 classifier mistake + a Week-2 handler mistake compounds (corrupt classifier emits drive corrupt YAML writes); decoupling bounds the failure cost.
* The handler's contract (YAML-first + ledger-second + reconcile pass H detect surface) is substantial; bundling with the classifier increases the Week 2 scope by ~200 LOC + 30+ tests. The two-week split keeps each week's surface focused.
* The handler also gates on the conversation state machine (per ADR-0025 D98 — Week 4-5 deliverable); the natural pairing is handler + state machine, not handler + classifier.

### D107-Alt2: Defer the auto-unsubscribe handler to Pillar I OSS bring-up

Operators manually append to the suppression YAML on every classified unsubscribe until Pillar I CLI ships. **Rejected** because:

* PILLAR-PLAN §2 Pillar D exit criterion explicitly names the 60-second SLA as binding for Pillar D's "stable" flip. Deferring to Pillar I would require ADR amendment of PILLAR-PLAN.
* CAN-SPAM compliance is the load-bearing reason Pillar D exists in its current scope; deferring is incoherent with the pillar's purpose.
* The classifier emits the events anyway (Week 2); the handler is one additional consumer of those events. Deferring the handler past Pillar D wastes the classifier's work for the legal-liability path.

### D107-Alt3: Ship the auto-unsubscribe handler in Week 3 alongside the other five categories

Bundle handler + Week 3's per-channel reply detection + the long-tail category expansion. **Rejected** because:

* Couples three concerns (handler write contract + per-channel reply detection + long-tail category expansion) in one week — bigger than Week 2 + handler combined.
* The handler's contract (YAML-first write + atomic ledger append + reconcile pass H detect surface) is testable in isolation against email replies ONLY. Pulling in per-channel reply detection would require the handler to be channel-aware before the per-channel reply passes have shipped — premature parameterization.
* The natural pairing per ADR-0025 D98 + D100 is handler + conversation state machine (both are downstream consumers of `reply_classified` events + both have per-thread state that needs coordinated design). Week 4-5 ships both together.

## Consequences

### Positive

- **The classifier MODULE is a clean pillar primitive.** Future Pillar D weeks (Week 3 category extension, Week 6-8 LLM fallback) extend the module's surface without churning reconcile.py.
- **The pattern-list YAML is operator-tunable from Day 1.** Operators in different verticals tune the pattern set without code forks; the factory defaults are conservative + the bootstrap experience is `cp + run`.
- **Idempotence-by-(mid, channel) is robust against per-channel message-id namespace collisions.** Future LinkedIn / Twitter / calendar reply detection landing in Week 3+ inherits the discrimination shape without retrofit.
- **Pass G integrates cleanly into the reconcile chain.** Operators run `python -m orchestrator.reconcile --full` + the classifier runs automatically; no new mental model.
- **The auto-unsubscribe handler deferral to Week 4-5 bounds the Week 2 failure cost.** A pattern misconfiguration in Week 2 produces classified events the operator can review; the YAML write doesn't happen until Week 4-5's handler ships + the operator has built confidence in pattern tuning.
- **The classifier output (`reply_classified` events) is the contract between Week 2's emit and Week 4-5's handler.** The contract is testable in isolation against each surface; the handler can be ADDED without rework to the classifier.
- **The cross-pillar surface audit (D106) continues the ADR-0025 D99 discipline.** Every new event class extends the audit; the audit grows with the pillar; the Pass-A-class latent-bug pattern is foreclosed by construction.

### Negative

- **Operators with no pattern file get no classifier coverage.** Pass G refuses to run loudly with a clear error message + remediation, but the missing-file case is a real operator-onboarding cliff. **Mitigation:** the doctor preflight (Pillar I) MAY check for the pattern file's existence as a future operator-friendliness improvement; until then, the refuse-loud error is the explicit operator-instruction surface.
- **Week 2 emits only — no auto-suppression.** Operators who want CAN-SPAM compliance from Day-1-Week-2 have to manually append to the suppression YAML based on classified events. **Mitigation:** the 60-second SLA is Week 4-5; operators with pre-Pillar-D unsubscribe workflows (manual review + manual append) carry that workflow through Week 4. The operator-visible benefit Week 2 ships is the LEDGER VISIBILITY into "which replies were classified as unsubscribe?" — a workflow accelerator even without auto-suppression.
- **The pattern list's regex format requires operators to know Python regex syntax.** A non-developer operator may struggle to author regex patterns. **Mitigation:** the factory `unsubscribe-patterns.example.yml` ships conservative defaults that cover the most common cases; advanced operators tune. Pillar I OSS bring-up MAY ship a pattern-list-builder TUI (TBD) as an ergonomic improvement.
- **The `uncategorized` fallback emits an event for every non-matching reply.** Week 2's classifier emits one `reply_classified` event per reply event (one with `category: "unsubscribe"` OR one with `category: "uncategorized"`). The ledger grows by one event per reply. **Mitigation:** the emit shape is small (one JSON line); the operator's ledger growth scales with reply volume (a 10% reply rate operator at 1000 prospects/year = 100 reply events/year = 100 classifier events/year). Acceptable storage cost for full per-reply audit visibility.
- **Pass G's `all_events()` walk is O(ledger size).** Building the (reply_message_id, channel) idempotence index walks every event. For an operator with 10K events, the walk is sub-second; for 1M+ events the walk grows linearly. **Mitigation:** Pillar G observability MAY surface ledger-size growth as a pre-Pillar-H concern. The walk is a known cost of the closed-set-protected discriminator approach; per-event-type indexing is the longer-term polish (per the Week 1 audit's §Performance note).
- **Concurrent Pass G runs can race on the idempotence check and produce duplicate `reply_classified` events for the same `(reply_message_id, channel)` pair.** The current implementation builds the `classified_keys` in-memory set at the START of `run_pass_g` from a ledger read, then emits events during the loop. If two Pass G instances run concurrently (e.g., the Pillar H daemon + a manual `--passes G` invocation), Process A and Process B can both build their `classified_keys` set from the same pre-append ledger state, both classify the same reply, and both call `Ledger.append()`. The `fcntl.lockf` in `Ledger.append` serializes the writes at the file level, so both `reply_classified` events land — producing a duplicate. **Week 2 bounding:** the duplicate is emit-only (no auto-suppression yet); the operator sees two ledger entries for one reply. **Load-bearing requirement for Week 4-5:** the auto-unsubscribe handler (ADR-0028 — TBD) MUST deduplicate `reply_classified` events by `(reply_message_id, channel)` before writing to the suppression YAML — a naive handler that processes every `reply_classified` event with `category=unsubscribe` would land two `suppression_added` events + two YAML append calls for one real unsubscribe action. The YAML append is content-idempotent (the set-membership write produces no corruption from a duplicate email), but the audit trail diverges. The Week 4-5 ADR's handler-implementation MUST name + test this dedup. **Documented in `.planning/HANDOFF-pillar-d-week-3.md` carry-overs** as a load-bearing Week 4-5 requirement. Surfaced by the Week 2 per-week reviewer's P2-B finding.

### Neutral / observability

- The `reply_classified` events are queryable via the existing `query_by_person` + filter-by-type pattern. Pillar G's classifier-precision/recall dashboard (planned) reads these directly.
- The `_emitted_by: "reply_classifier"` marker (per ADR-0010 D17 convention) lets operators filter classifier output from other event sources in funnel queries.
- The `matched_pattern` field surfaces the operator's regex set for audit; "which pattern fired for this classification?" is a one-query answer.
- No new SoT introduced (per I1 invariant). The classifier output is denormalized from the reply events; the reply events are denormalized from the inbox state. The new SoT row in `docs/SOURCES-OF-TRUTH.md` documents the PATTERN LIST (operator config), not the classifier output (denormalized).

## Compliance with invariants

- **I1 (single source of truth):** One new SoT row added (Classifier pattern lists → `~/.outreach-factory/classifier/*.yml`). The classifier output is a denormalized view of the reply events; no SoT collision.
- **I2 (two-phase commit on every external side effect):** The classifier is a pure FRAMEWORK operation (regex + ledger walk + ledger append); no external side effects. The auto-unsubscribe handler (Week 4-5) IS external-side-effect-adjacent (the suppression rule's enforcement IS the external effect); the handler's contract (D100) is the two-phase analog (YAML-first + ledger-second). I2 holds end-to-end through the future handler.
- **I3 (schema versioning):** Pattern YAML carries `version: 1`. `reply_classified` events carry `v: 1`. The classifier's pattern-loading helper refuses non-version-1 files explicitly (`PatternLoadError`). I3 holds.
- **I4 (reproducible state):** Pass G is deterministic — the same ledger state + the same pattern set produces the same `reply_classified` events on every run. The (reply_message_id, channel) idempotence key ensures reruns are no-ops. Replaying the ledger reconstructs the classifier output as a deterministic function of the inputs.
- **I5 (observable by default):** Every `reply_classified` event carries `matched_pattern` (the regex source) + `confidence` (always 1.0 for rule matches) + `classification_method` ("rule"). Pillar G dashboards have scalar-field queries for every classifier dimension. The `_emitted_by: "reply_classifier"` marker makes the classifier's emits filterable.
- **I6 (tests prove invariants):** `tests/test_reply_classifier.py` ships per-method unit tests (pattern matching, idempotence, per-channel discrimination, output shape, the load-bearing legal-liability invariant). The `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_unsubscribe_classification_method_is_always_rule` un-skipped row enforces D97's load-bearing legal-liability constraint via the test corpus, not just documentation.
- **I7 (cost is a first-class concern):** Week 2 emits NO `cost_incurred` events (rule-based classification has no per-call cost). The LLM fallback (Pillar D Week 6-8) WILL emit cost events; the source name `reply_classifier_llm` is reserved in ADR-0025 §I7 and ADR-0006's pricing table will be extended at Week 6-8's implementation.
- **I8 (documented decisions):** This ADR. `docs/adr/README.md` gains an ADR-0026 row. The per-week trajectory in HANDOFF-pillar-d-week-3.md (TBD this commit) names planned ADRs 0027+ (Week 3 ADR for per-channel reply detection + long-tail categories).

Does not weaken any invariant. I3's enforcement extends to the pattern YAML's version field. I5's enforcement extends to the classifier output's matched_pattern + confidence + classification_method fields.

### Downstream pillar impact

Per the Pillar A / B / C / D Week 1 convention (every ADR explicitly names cross-pillar impact):

* **Pillar E (discovery quality + lineage).** Pillar E's discovery-lineage tracking may consume `reply_classified` events to learn discovery-source-to-reply-rate correlations (e.g., "founders discovered via competitor-customers source unsubscribe at 3% vs founders discovered via funded-founders source at 7%"). The classifier's `_emitted_by: "reply_classifier"` marker + `matched_pattern` field surface the data Pillar E needs. Pillar E's enrollment ADR (TBD) may also gate re-enrollment on `category: unsubscribe` classifications (don't re-enroll a person who unsubscribed; CAN-SPAM compliance).

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity-after-reply scoring may correlate `category` with the draft's voice-fidelity score (does a low-fidelity draft elicit more `wrong_person` classifications? does a high-fidelity draft elicit more `interest` classifications?). Pillar F's draft-quality ADR (TBD) MAY reference the `reply_classified` event's `category` field for the correlation surface.

* **Pillar G (observability).** Pillar G's classifier-precision/recall dashboard reads `reply_classified` events; the per-channel reply-rate funnel reads `reply_received` events filtered by `channel:`; the per-category breakdown reads `reply_classified` events filtered by `category:`; the operator-tuning surface reads `matched_pattern` for "which pattern fires most often?" insights. All scalar-field queries against the D33-extended-by-D96 channel field + D97-pinned `reply_classified` event class.

* **Pillar H (daemon + dispatcher).** Pillar H's daemon MAY run the classifier in a live-update loop (Pillar H's SIGHUP-on-pattern-list-change hook reloads the classifier; per-reply classification fires within seconds of the reply landing). The Week 2 batched-Pass-G shape is the operator-onboarding posture; Pillar H is the operationally-stronger surface for high-volume operators. The classifier's primitives (`RuleBasedClassifier`, `emit_classified_event`) are reusable in Pillar H's daemon context.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel pattern lists. The classifier pattern YAML files are per-tenant (per the existing `~/.outreach-factory/` per-install layout). The Pillar I doctor preflight extends to check classifier pattern file existence + schema-conformance + pattern-set non-emptiness. The Pillar I CLI ships `python -m orchestrator.classifier replay --since <date>` for the one-time backfill of pre-Pillar-D-Week-1 reply events.

* **Pillar J (security + compliance).** Pillar J's CAN-SPAM compliance gate consumes the classifier's `reply_classified` events with `category: "unsubscribe"` as the SoT for "which prospects requested unsubscribe?" — the audit trail for external compliance review. The doctor preflight verifies the classifier's pattern list is non-empty + the auto-unsubscribe handler (Week 4-5) is wired. Pillar J's GDPR-forget transaction also inherits the classifier's `reply_classified` events (for prospects whose Person notes are GDPR-purged, the corresponding classifier output is purged or tombstoned per Pillar J's ADR — TBD).

## Migration / rollout

The Week 2 deliverable is the classifier module + the pattern-list YAML + the example config + Pass G integration + the un-skipped coherence test rows + the cross-pillar audit row extension.

**Operator-facing changes (Week 2):**

1. **No new pending migrations.** `runner.pending()` still returns 15 (the Pillar D Week 1 final state). Pillar D Week 4-5+ MAY ship vault migrations to add per-Person `conversation_status:` field denormalization; Week 2 leaves the migration count unchanged.

2. **New CLI flag — `--classifier-rule-list <path>`.** Defaults to `~/.outreach-factory/classifier/unsubscribe-patterns.yml`. Useful for: test injection, per-environment overrides, operator A/B testing of pattern-set tuning.

3. **`--full` now includes Pass G.** `python -m orchestrator.reconcile --full` runs `"A,B,C,D,E,F,G"` (previously `"A,B,C,D,E,F"`). Operators bootstrapped per (4) below get classifier coverage automatically.

4. **New operator bootstrap step (one-time):**

   ```bash
   mkdir -p ~/.outreach-factory/classifier
   cp config-template/unsubscribe-patterns.example.yml \
      ~/.outreach-factory/classifier/unsubscribe-patterns.yml
   # (optionally tune the pattern list for the operator's vertical)
   ```

   Operators who don't bootstrap get a clear refuse-loud error on the first `--full` (or `--passes G`) invocation; no silent skip.

5. **Existing operators with pre-Pillar-D-Week-1 reply events** carry the same small known limitation per ADR-0025 §Migration/rollout item 3 (their pre-fix `reply_received` events lack the `channel` field). Pillar D Week 2's classifier handles this via "treat absent channel as email" per the historical-default rule — the existing-operator's pre-fix events get classified as email replies. The Pillar I CLI's `python -m orchestrator.classifier replay --since <date>` ships the one-time backfill ergonomic for any pre-fix events that need re-stamping.

**Operator-facing changes (Pillar D Weeks 3+, planned):**

6. **Week 3 ships per-channel reply detection passes** (LinkedIn inbox scraper / Twitter DM scraper / calendar comment scraper if Cal.com's API allows) + the other five classifier categories (ooo / wrong_person / interest / rejection / uncategorized — the uncategorized fallback narrows as Week 3 extends category coverage).

7. **Weeks 4-5 ship the auto-unsubscribe handler + conversation state machine.** The handler reads `reply_classified` events (filtering `category == "unsubscribe"`) + writes to the suppression YAML per ADR-0025 D100. The conversation state machine emits `conversation_state_changed` events tracking per-thread state.

8. **Weeks 6-8 ship the LLM fallback** for the long-tail categories. The unsubscribe path STAYS rule-based (D97's invariant); the LLM is consulted only for the non-unsubscribe categories where the rule list misses.

**The Week 2 commit's verification surface:**

```python
# 1. The classifier module exists + is importable.
$ python -c "from orchestrator.reply_classifier import RuleBasedClassifier, ClassifierResult, emit_classified_event"

# 2. The classifier unit tests pass.
$ python -m pytest tests/test_reply_classifier.py -v
# Expected: every per-method test passes (pattern matching, idempotence, per-channel discrimination,
# output shape, load-bearing legal-liability invariant, pattern-list-as-input loads cleanly).

# 3. The coherence test vehicle's Week 2 rows un-skip + pass.
$ python -m pytest tests/test_multi_channel_coherence.py::TestReplyClassification \
                   tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement -v
# Expected: TestReplyClassification.test_reply_classified_is_separate_event_not_annotation +
# test_reply_classified_carries_classification_method_and_confidence +
# test_classifier_idempotent_against_already_classified_replies pass.
# TestUnsubscribeEnforcement.test_unsubscribe_classification_method_is_always_rule passes.
# Per-channel rows for LinkedIn/Twitter/calendar still skipped per Week 3 trajectory.

# 4. Pass G runs under reconcile.
$ python -m orchestrator.reconcile --passes G --apply --classifier-rule-list config-template/unsubscribe-patterns.example.yml
# Expected: Pass G: examined=<n>, by_type={reply_classified: <m>}  (where m == n if no events already classified)

# 5. The full suite is green at +N tests.
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 1850+N passed (the +N comes from: classifier unit tests + un-skipped coherence rows + Pass G regression tests).

# 6. ADR-0026 exists; README index gains the row; PILLAR-PLAN §6 Pillar D row updated.
$ ls docs/adr/0026-pillar-d-rule-based-classifier.md
$ grep "0026" docs/adr/README.md
$ grep "Week 2 ✓" docs/PILLAR-PLAN.md

# 7. SoT registry gains the Classifier pattern lists row.
$ grep "Classifier pattern lists" docs/SOURCES-OF-TRUTH.md
```

### Existing-operator seed

Pillar D Week 2 ships NO new migrations + NO new ledger-state primitives that require an existing-operator seed beyond the new bootstrap step (4 above).

**Bootstrap-step seed for existing operators (Yang):**

```bash
# One-time bootstrap (idempotent — safe to re-run):
mkdir -p ~/.outreach-factory/classifier
cp config-template/unsubscribe-patterns.example.yml \
   ~/.outreach-factory/classifier/unsubscribe-patterns.yml

# First Pass G run (will classify all pre-existing reply events):
python -m orchestrator.reconcile --passes G --apply

# Verify:
python -m orchestrator.ledger grep --type reply_classified | head
```

For Yang specifically (the current sole operator), the pre-Pillar-D-Week-1 reply event count is small (Phase 5.5 Pass B has only emitted in recent reply-detection runs). The first `--passes G` invocation classifies all of them in one go; the ledger gains one `reply_classified` event per reply event.

The first Pillar D week that ships a vault migration requiring an existing-operator seed (TBD — likely Pillar D Week 4-5+'s vault migration adding per-touch `reply_state:` fields) WILL include the §Existing-operator-seed subsection per the D36 convention from ADR-0014.

## References

- ADR-0001 (policy engine architecture) — the engine surface Pillar D Week 4-5's auto-unsubscribe handler will integrate with (no engine change required for the classifier; handler integration is in Week 4-5's ADR).
- ADR-0003 (channel as first-class policy predicate) — the cross-channel rule whose behavior Pillar D's classifier output does NOT trigger (`reply_classified` does not end in `_confirmed`).
- ADR-0004 (suppression rules + GDPR-forget) — the `forget_append` primitive Pillar D Week 4-5's auto-unsubscribe handler will reuse; the suppression rule contract Pillar D inherits unchanged.
- ADR-0006 (budget rules + cost_incurred event) — the cost-event convention Pillar D Week 6-8's LLM fallback will emit against (the `reply_classifier_llm` source name is reserved in ADR-0025 §I7).
- ADR-0009 (migration framework) — Pillar D vault/policy migrations (Week 4-5+) will register into the existing framework; Week 2 ships ZERO migrations.
- ADR-0010 (ledger migrations) — Pillar D `migration_event` audit-trail emissions follow the D35 `channel=` kwarg convention (inherited from Pillar C); Week 2 emits no migration events.
- ADR-0011 (vault migrations) — Pillar D touch-note migrations (Week 4-5+) consume the existing `iter_touch_notes` + `add_frontmatter_block_text` primitives.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — the D27 cross-category-ordering contract Pillar D's future migrations inherit; the D24 fixture-builder pattern Pillar D Week 4-5+ extends.
- ADR-0014 (Pillar C foundation) — the D33 channel-on-every-two-phase-event invariant extended by ADR-0025 D96 to reply events; the D37 exit-criterion vehicle Pillar D extends per ADR-0025 D101.
- ADR-0017 (Pillar C reconcile passes D + E) — the D48 + D50 asymmetric-failure-cost calculus + the serial-pass ordering pattern Pass G inherits.
- ADR-0018 (Pillar C Twitter DM) — the D62 generalized `_run_channel_intent_pass` helper Pillar D Week 3+'s per-channel reply detection MAY extend to a `_run_channel_reply_pass` analog (TBD per Week 3's ADR).
- ADR-0019 (Pillar C calendar booking) — the D66 webhook-driven recovery pattern Pillar D Week 3+ MAY extend for calendar-comment-reply detection (TBD per Week 3's ADR).
- ADR-0025 (Pillar D foundation) — D96 (per-channel reply event-type naming) + D97 (classifier output convention + the load-bearing legal-liability invariant) + D98 (conversation state shape — distinct from send-state) + D99 (cross-pillar surface audit — Week 2 extends per D106) + D100 (auto-unsubscribe enforcement contract — Week 2 emits the events the future handler reads) + D101 (exit-criterion vehicle scope — Week 2 un-skips four rows).
- `docs/PILLAR-PLAN.md` §2 Pillar D — exit criterion (binding text); §5 "What we will not do" — the unsubscribe = rule-based ONLY constraint D97 + this ADR's D107 pin; §6 Pillar D row Notes column extended to "Week 1 ✓ + Week 2 ✓" in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D107's Week-2-emit-only-handler-deferred posture.
- `docs/RISK-REGISTER.md` R010 (Regulatory shift) — risk Pillar D mitigates by design via the auto-unsubscribe enforcement contract; Week 2 lays the foundation. R012 (LLM hallucinates unsubscribe — added in ADR-0025) — risk D97's invariant + the un-skipped regression test mitigate by construction. R013 (operator pattern-list misconfiguration — NEW, added in this commit) — risk D103's refuse-loud bootstrap + the conservative factory defaults mitigate.
- `docs/SOURCES-OF-TRUTH.md` — new row added in this commit: "Classifier pattern lists" → `~/.outreach-factory/classifier/*.yml` (per D103).
- `.planning/RETRO-pillar-c.md` §"What to do differently in Pillar D" item 2 — the audit-existing-surfaces lesson; Pillar D Week 2's D106 audit extension operationalizes.
- `.planning/REVIEW-pillar-d-surface-audit.md` — the D99 audit document; THIS commit's D106 extends with the `reply_classified` consumer surface + the new ledger-walk pattern (idempotence index).
- `.planning/HANDOFF-pillar-d-week-2.md` — the per-week handoff that scoped Week 2.
- `.planning/HANDOFF-pillar-d-week-3.md` — written in this commit; scopes Week 3 (per-channel reply detection + the other five classifier categories).
- `orchestrator/reply_classifier.py` — the classifier module D102 names.
- `orchestrator/reconcile.py::run_pass_g` — the classifier pass D105 names (extension of the existing run_pass_a … run_pass_f family).
- `config-template/unsubscribe-patterns.example.yml` — the factory pattern list D103 names.
- `tests/test_reply_classifier.py` — the classifier's unit tests.
- `tests/test_multi_channel_coherence.py::TestReplyClassification` + `TestUnsubscribeEnforcement` — the un-skipped coherence rows that pin the classifier output shape + the load-bearing legal-liability invariant.
- Forward-references (planned):
  - **ADR-0027** (Pillar D Week 3): per-channel reply detection (LinkedIn / Twitter / calendar) + the other five classifier categories (ooo / wrong_person / interest / rejection / uncategorized).
  - **ADR-0028** (Pillar D Week 4-5): auto-unsubscribe handler + conversation state machine + Pillar D vault migration.
  - **ADR-0029** (Pillar D Week 6-8): LLM fallback for non-unsubscribe categories + classifier-cap policy migration.
  - **ADR-0030+** (Pillar D Week 9-11): win/loss attribution; conversation_outcome event; reply-funnel observability surface.
  - **ADR-00NN** (Pillar D Week 12): exit-gate close — the binding 100-message synthetic inbox classifier benchmark un-skips.
  - **Pillar H SIGHUP** (Weeks 37-48): the live-reload hook for the classifier pattern list (Pillar H also closes the D100 race-window).
  - **Pillar I CLI** (Weeks 43-48): the classifier-replay command + the doctor-preflight extension (pattern-list existence + schema-conformance check).
