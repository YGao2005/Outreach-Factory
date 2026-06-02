# Risk Register

Living list of named risks for outreach-factory. Each risk has an owner, severity (1=catastrophic, 5=cosmetic), likelihood (1=expected, 5=remote), mitigation, and status. Append-only with revisions in-place — don't delete entries; mark them `Status: Closed` with a date and link to the resolving ADR / commit / postmortem.

Severity × likelihood prioritization (lower number = more urgent). Anything 1×1 or 1×2 is reviewed weekly until closed.

## Active risks

### R001 — Identity-graph false-merge cascade
- **Severity / Likelihood:** 1 / 3
- **Owner:** Pillar J Week 3 (ADR-0076 D383) — audit slice assigned; reverse-merge tooling deferred to v2
- **Status:** Open (mitigation in flight: `identity_keys_modified` audit + identity-history block + reconcile drift-flag at Pillar J W3)
- **Description:** A single bad merge in `identity.resolve_strict` (or a manual frontmatter edit that joins two records) propagates through every ledger derivation: pipeline_stage, last_send_for, derived_stage, funnel counts. Downstream sends route to the wrong human. The strict-conflict-refuses-merge policy in `identity.py` mitigates auto-merges, but manual merges via frontmatter edit have no audit trail today.
- **Mitigation plan:**
  - Identity history block (when keys were added, by whom, via which conflict resolution) — schema change, Pillar B migration.
  - Reverse-merge tooling (`identity.py split <person_id> --by-key <class>`) once the history block exists.
  - Audit event `identity_keys_modified` on every frontmatter mutation; reconcile flags any Person frontmatter that differs from the keys ledger view.

### R002 — Gmail OAuth token rotation mid-batch
- **Severity / Likelihood:** 2 / 2
- **Owner:** Pillar J Week 2 (ADR-0076 D387; J1 — `send_with_token_rotation`)
- **Status:** Open (mitigation in flight: refresh-and-retry middleware emits `auth_token_refreshed`; ledger-consistency test at Pillar J W2)
- **Description:** Token expiry mid-batch causes partial-send orphans: half the batch sends, the other half fails with 401, ledger has `send_intent` events with no `send_confirmed` / `send_failed`. Reconcile Pass A eventually heals, but the failure mode is invisible until next reconcile.
- **Mitigation plan:**
  - Refresh-and-retry middleware in `gmail_client.py`: catch 401, refresh, retry once, log a `oauth_rotated` event.
  - Test that simulates token expiry exactly between two sends in the same batch; assert ledger ends consistent.
  - Health endpoint reports time-to-token-expiry; alert if <10 minutes at batch start.

### R003 — Ledger growth unbounded
- **Severity / Likelihood:** 3 / 3
- **Owner:** unassigned (Pillar G / H seam)
- **Status:** Open
- **Description:** 10K prospects × ~20 events × 5 years ≈ 1M events. Even at one line each, JSONL scanning becomes the slow path for query_by_* methods (the in-memory index amortizes but cold-start cost grows linearly). At 10M events, full rebuilds are minutes-long.
- **Mitigation plan:**
  - Monthly compaction job preserving hash chain (Pillar B migration framework).
  - SQLite mirror as derived-index for analytics queries (rebuildable from JSONL); ledger remains canonical write path.
  - Alarm at 10M events triggers re-architecture decision (Postgres? Per-month sharding?).

### R004 — Policy rule explosion
- **Severity / Likelihood:** 3 / 3
- **Owner:** unassigned (Pillar A)
- **Status:** Open
- **Description:** As the policy engine grows (cooldown + suppression + budget + window + tier + per-domain throttle + per-channel + per-persona), 50+ rules with overlapping conditions become impossible to reason about. A user adds a rule that silently shadows another; sends get blocked or allowed for non-obvious reasons.
- **Mitigation plan:**
  - Simulation mode: `policy.py simulate --person <id> --channel email --date <future>` reports every rule considered + winner.
  - Rule-coverage analyzer: which rules have ever fired? Which never have (potential dead rules)?
  - Max-rule-count alarm at 30 rules forces consolidation review.

### R005 — OSS fork-and-divergence
- **Severity / Likelihood:** 3 / 4
- **Owner:** unassigned (post-OSS-release)
- **Status:** Open (latent — no OSS users yet)
- **Description:** Contributors fork to add features (alt channels, alt LLM providers, custom rule classes) that conflict with the upstream roadmap. Merging back becomes hostile.
- **Mitigation plan:**
  - Published roadmap in `docs/PILLAR-PLAN.md` (visible at OSS release).
  - Contribution guide with the I1–I8 invariants front-and-center.
  - Lightweight RFC process for new pillars / channel adapters (PR template that asks "which invariants does this touch?").

### R006 — Anthropic API churn
- **Severity / Likelihood:** 3 / 3
- **Owner:** unassigned
- **Status:** Open
- **Description:** Model deprecations or pricing shifts break the draft / research skills mid-pipeline. The current draft skill hard-codes a model family.
- **Mitigation plan:**
  - Provider adapter in `orchestrator/llm/`. All skills route through it.
  - vLLM / local-model fallback path for cost-sensitive operations (research dossier scraping summaries, not the final draft).
  - Model-name in policy file (`~/.outreach-factory/policies/models.yml`), not in code.

### R007 — Vault corruption from concurrent Obsidian Sync
- **Severity / Likelihood:** 2 / 4
- **Owner:** unassigned (Pillar C / G seam)
- **Status:** Open (rare; one observed false-positive in burn-in)
- **Description:** Obsidian Sync occasionally creates `.conflicted` suffix files when two devices edit the same Person note. Reconcile Pass C currently ignores `.conflicted` files (correct), but a `.conflicted` file with `pipeline_stage:` drift can mask a real issue.
- **Mitigation plan:**
  - Pass C explicitly enumerates and reports `.conflicted` files; refuses to heal until they're resolved.
  - Nightly vault snapshot (already in place per Phase 5.5 migration plan) — RPO is 24h.
  - Vault is reconstructable from the ledger (Pillar I delivers `rebuild_vault.py`).

### R008 — Spam-flag cascade from one bad batch
- **Severity / Likelihood:** 1 / 3
- **Owner:** unassigned (Pillar A budget + Pillar C inbox-warming)
- **Status:** Open
- **Description:** One mis-targeted batch (50 cold pitches to non-matching prospects) tanks deliverability for the whole sender domain. Recovery takes weeks. This is the single worst non-suspension failure mode.
- **Mitigation plan:**
  - Per-domain throttle in Pillar A (≥3 emails to `acme.com` in 14d → block).
  - Per-day / per-week / per-month cap (Pillar A budget rules).
  - Inbox warming for new senders in Pillar C (ramp from 5/day → 50/day over 4 weeks).
  - Bounce-rate auto-throttle: if hourly bounce rate >5%, halt all sends; require manual override.

### R009 — LinkedIn account suspension
- **Severity / Likelihood:** 1 / 3
- **Owner:** unassigned (Pillar C)
- **Status:** Partially mitigated (weekly invite cap → policy rule via ADR-0008, 2026-05-19); remaining mitigation work tracked under Pillar C / H
- **Description:** Aggressive automation (high invite volume, fast cadence, scraping) triggers LinkedIn enforcement. Suspension = lose the channel entirely + the visibility that drives discovery.
- **Mitigation plan:**
  - ~~Weekly invite cap already in place (skill-level); migrate to Pillar A budget rule.~~ **Done — ADR-0008**, 2026-05-19. The cap is now expressed as `linkedin-weekly-invite-cap` (`budget.window-cap`, `source: linkedin`, `window_days: 7`, `max_units: 100`) in `cooldowns.example.yml`, commented out by default. Operators opt in by uncommenting; the policy engine refuses at the gate, not just warns. Transitional cost-event emit-site is documented in `_emit_linkedin_manifest`'s printed handoff until Pillar C lands `li_invite_intent` / `li_invite_confirmed`.
  - Randomized timing on dispatch (Pillar H daemon owns scheduling).
  - Per-account warming schedule for new LinkedIn-MCP-connected accounts.
  - No headless-scraper-style behavior — all calls go through `mcp__linkedin__*` which respects rate limits.

### R010 — Regulatory shift (GDPR / state laws / CAN-SPAM updates)
- **Severity / Likelihood:** 2 / 4
- **Owner:** Pillar J (ADR-0076 D380/D381; J6 forget crypto-shred + J7 CAN-SPAM)
- **Status:** Open (mitigation in flight: J7 CAN-SPAM footer+header at W4; J6 GDPR forget = FENCED human-gated build per ADR-0080)
- **Description:** New requirements invalidate existing data handling. Example: a state-level "right to deletion" law with a 30-day SLA we don't meet today.
- **Mitigation plan:**
  - Pillar J builds GDPR-compliant `policy.py forget --person <id>` (purges vault + ledger person records + caches; leaves tamper-evident audit record).
  - Quarterly compliance review (calendar event after Pillar J ships).
  - External counsel sign-off before OSS release.

### R011 — Cross-channel double-engagement
- **Severity / Likelihood:** 1 / 3
- **Owner:** unassigned (Pillar A rule class; Pillar C event types)
- **Status:** Mitigated by design (ADR-0003); enforcement activates when Pillar C lands LinkedIn `send_confirmed` events
- **Description:** A cold email to a prospect on Monday + a LinkedIn connect to the same prospect on Wednesday reads as coordinated automation to both the human recipient and to the platforms. The recipient marks one channel as spam (or both); LinkedIn's behavioral detection flags the sending account; Gmail deliverability tanks for the sending domain. This is the imminent failure mode now that LinkedIn-as-default-channel is on the roadmap (strategy discussion 2026-05-16). The Phase 5.5 identity model unifies prospects across channels (one Person.id holds email + LinkedIn URL), so the ledger already knows about both touches — the policy engine must act on that knowledge before Pillar C ships LinkedIn sending, otherwise the rule shape lands in Pillar C and composes poorly with the same-channel-only engine surface. Distinct from R008 (single-channel spam-flag cascade) and R009 (LinkedIn-only suspension); this risk is the coordination failure between two otherwise-healthy channels.
- **Mitigation plan:**
  - `cooldown.cross-channel-touch` rule class in Pillar A v1 (`orchestrator/policy/cross_channel.py`, Week 2); two factory rules shipped in `config-template/cooldowns.example.yml` covering email↔LinkedIn with a 14-day window in both directions. See ADR-0003.
  - Rules return `Allow()` until Pillar C lands `li_*_confirmed` event types; they begin enforcing automatically the moment those events first appear in the ledger — no policy-engine changes required at that point.
  - Pillar G observability surfaces `policy_blocked` events from this rule type in the funnel breakdown so cross-channel near-misses are visible.
  - Pillar A simulation mode (Week 5) can preview cross-channel verdicts before any live send is dispatched.

### R012 — LLM hallucinates unsubscribe → over-suppression
- **Severity / Likelihood:** 2 / 3
- **Owner:** unassigned (Pillar D classifier; Pillar A suppression contract)
- **Status:** Mitigated by design (ADR-0025 D97 — `unsubscribe = classification_method == "rule"` invariant; LLM is NEVER consulted for unsubscribe classification, even as a tiebreaker)
- **Description:** Pillar D Week 6-8 ships an LLM fallback for the long-tail classifier categories (ooo / wrong_person / interest / rejection / uncategorized) that the rule-based classifier can't reach with high precision. The LLM is gated against the unsubscribe path per ADR-0025 D97 + PILLAR-PLAN §5 ("unsubscribe is rule-based ONLY — no LLM in the legal-liability path"). The risk: a future contributor adding an LLM fallback to the unsubscribe path (perhaps as a `confidence > 0.95` tiebreaker for ambiguous replies) would invert the asymmetric-failure-cost calculus — missed unsubscribes become CAN-SPAM violations (legal exposure), while LLM-hallucinated unsubscribes become over-suppression (the prospect is suppressed despite never actually unsubscribing). Suppression is a kill switch (per ADR-0004 §Decision); once written to the suppression YAML, the prospect is unreachable until the operator manually removes the entry. The over-suppression failure mode is operator-discoverable only via "why aren't we contacting this person?" investigation — invisible by default.
- **Mitigation plan:**
  - `tests/test_multi_channel_coherence.py::TestUnsubscribeEnforcement::test_unsubscribe_classification_method_is_always_rule` regression test (stub lands Pillar D Week 1; un-skips when classifier ships Week 2-3). The test asserts `classification_method == "rule"` AND `confidence == 1.0` for every `reply_classified` event with `category == "unsubscribe"`. A future contributor adding an LLM fallback to the unsubscribe path would fail this test loudly.
  - ADR-0025 D97's invariant binds the contract; D97-Alt2 explicitly rejected the "LLM with confidence > 0.95 threshold" alternative with the asymmetric-failure-cost rationale.
  - Operator-curated `unsubscribe-patterns.yml` (Pillar D Week 2-3) is the escape valve: patterns the operator wants to catch can be added as regex without the LLM. The rule fires deterministically thereafter.
  - The auto-unsubscribe handler emits `suppression_added` events (per ADR-0025 D100) with `source_reply_classified_event` correlating back to the triggering classifier output — operator audit is one query: `type == "suppression_added"` filtered by ts.

### R013 — Operator pattern-list misconfiguration → suppression coverage gap or over-suppression
- **Severity / Likelihood:** 2 / 3
- **Owner:** unassigned (Pillar D classifier; Pillar I doctor preflight)
- **Status:** Mitigated by design (ADR-0026 D103 — refuse-loud bootstrap-failure error; conservative factory defaults)
- **Description:** Pillar D Week 2's classifier reads its unsubscribe pattern set from `~/.outreach-factory/classifier/unsubscribe-patterns.yml`. Two operator failure modes: (a) operators with no pattern file get NO classifier coverage — every reply lands in the ledger unclassified; if the operator believes the classifier is running but it isn't, unsubscribe replies are silently missed (CAN-SPAM exposure once Week 4-5 ships the auto-unsubscribe handler that reads classified events). (b) Operators with overbroad patterns (e.g., a bare `\bstop\b` regex matching "stop by my office") get false-positive unsubscribes that — post-Week-4-5 — trigger auto-suppression of legitimate prospects. The over-suppression failure mode is operator-discoverable only via "why aren't we contacting this person?" investigation — invisible by default. Week 2 ships ONLY the classifier emit (no auto-suppression — Week 4-5 ships the handler), so Week 2's blast radius is bounded to "wrong events in the ledger that the operator can ignore or manually correct"; the risk lands in earnest at Week 4-5.
- **Mitigation plan:**
  - Pass G refuses to run with a clear error message + bootstrap remediation when no pattern file exists (per ADR-0026 D103 — `mkdir -p ~/.outreach-factory/classifier && cp config-template/unsubscribe-patterns.example.yml ~/.outreach-factory/classifier/unsubscribe-patterns.yml`). NO silent fallback to factory file (silent fallback would mean the operator's classifier is the FACTORY's, not the operator's — divergent semantics across installs).
  - The factory `config-template/unsubscribe-patterns.example.yml` ships CONSERVATIVE defaults — 12 patterns, each with inline rationale + known-false-positive notes. Operators tune; the factory shape doesn't catch anything that ISN'T a real unsubscribe in production reply corpora.
  - Pillar I doctor preflight (planned) extends to check (a) pattern file existence, (b) pattern file schema-conformance, (c) pattern-set non-emptiness. The doctor surface is the operator-friendly version of Pass G's refuse-loud error.
  - The auto-unsubscribe handler (Pillar D Week 4-5; ADR-0028 — TBD) reads `reply_classified` events from a START_TS forward — old false-positive classifications produced during Week 2-3 don't trigger auto-suppression of already-onboarded prospects (the handler ships with its own seed-time window per the per-week ADR).
  - The `matched_pattern` field on every classified event surfaces the operator's audit reason — "which pattern caught this?" is a one-query answer. Operators reviewing classifier output can identify problematic patterns + tune the YAML.

### R014 — Per-channel reply false-emit (recipient sends unrelated message on known thread)

- **Severity / Likelihood:** 1 / 2
- **Owner:** unassigned (Pillar D Week 3 — `orchestrator/reconcile.py::run_pass_i` / `::run_pass_j`)
- **Status:** Mitigated by design (ADR-0027 D111 + D112 — three filters layered for defense-in-depth)
- **Description:** Pillar D Week 3 ships Pass H / I / J — per-channel reply detection. Pass I walks `li_dm_confirmed.linkedin_thread_id` + emits `li_dm_reply_received` for every inbound message on those threads. Pass J does the same for Twitter DMs. **Failure mode:** the operator's recipient sends an UNRELATED message on a known LinkedIn / Twitter DM thread (e.g., a months-later "happy birthday" or an unrelated topic-change on a previously-outreach thread). Pass I / J emit a `*_reply_received` event for that message; Pass G classifies it (likely as `uncategorized` or `interest` since the language doesn't match the unsubscribe / ooo / wrong_person / rejection patterns). The operator's classifier-precision dashboard shows a "reply" that wasn't actually a reply to OUR outreach.
- **Why severity 1 (low):** The false-emit doesn't trigger any irreversible action — Week 4-5's auto-unsubscribe handler only reads `category=unsubscribe`, so a false-`interest`-emit doesn't auto-anything. The classifier's `uncategorized` fallback (per ADR-0026 D107) is the safe failure mode. The operator's pipeline-state dashboard (Pillar G — Pillar D Week 12+) shows the slight inflation but no operational impact.
- **Why likelihood 2 (low):** B2B cold-outreach threads typically have at most one inbound reply per outreach touch. The "unrelated months-later message on the same thread" pattern is rare in practice. The `from_self: False` filter prevents OUR follow-ups from triggering false emits.
- **Mitigation plan (already shipped Week 3):**
  - **Filter 1: `from_self: False`.** Pass I / J skip every self-sent message. Only recipient-originated messages emit reply events. (Verified by `tests/test_reconcile_pass_h_i_j.py::TestPassIHappyPath::test_self_sent_message_does_not_emit` + Pass J analog.)
  - **Filter 2: known-thread filter.** Pass I / J only walk conversations whose `thread_id` matches a known `li_dm_confirmed.linkedin_thread_id` / `tw_dm_confirmed.twitter_thread_id` from our ledger. Random LinkedIn / Twitter DMs on unrelated threads don't trigger emit. (Verified by `TestPassIHappyPath::test_conversation_on_unknown_thread_does_not_emit` + Pass J analog.)
  - **Filter 3: classifier uncategorized fallback.** The classifier's six-category dispatch (per ADR-0027 D108-D110) means most random follow-up text classifies as `uncategorized` — no operational consequence (Week 4-5's handler ignores; Pillar G dashboards show the count).
- **Operator-side remediation:** Operators noticing false-emits in their reply timeline can:
  - Inspect the originating reply event via `python -m orchestrator.ledger grep --type li_dm_reply_received` → identify the offending message.
  - File a `manual_override` event (per ADR-0006 — TBD; the operator-deliberate override surface) to mark the reply event as not-a-reply. Pillar G dashboards filter `manual_override` events out of the precision/recall denominator.
  - Pillar D Week 6-8's LLM fallback (ADR-0029 — TBD) is expected to outperform rules on the "is this message a topic-relevant reply" classification specifically; operators wanting tighter precision wait for LLM.

### R015 — Asymmetric-crash inconsistency between YAML write + ledger append (auto-unsubscribe handler)

- **Severity / Likelihood:** 2 / 1
- **Owner:** unassigned (Pillar D Week 4-5 — `orchestrator/auto_unsubscribe.py::run_auto_unsubscribe`)
- **Status:** Mitigated by design (ADR-0028 D116 + ADR-0025 D100's failure-mode matrix); residual operator-visible inconsistency surface deferred to Pillar I doctor extension
- **Description:** Pillar D Week 4-5 ships the auto-unsubscribe handler. Per ADR-0025 D100 + ADR-0028 D116, the write order is YAML-first (`forget_append` to `~/.outreach-factory/suppressions/auto-unsubscribe.yml`) followed by ledger-second (`led.append({"type": "suppression_added", ...})`). **Failure mode:** the YAML write succeeds + the ledger append fails (process crash, disk full, fcntl lock contention, etc.). After the failure: the suppression is LIVE (the YAML reflects the entry; the next dispatcher gate refuses the recipient) but the AUDIT TRAIL is incomplete (no `suppression_added` event in the ledger). Pillar G's CAN-SPAM compliance audit dashboard shows a divergence between the YAML's entry-count + the ledger's `suppression_added`-event-count.
- **Why severity 2 (medium):** Operational impact bounded — CAN-SPAM compliance posture is PRESERVED (the suppression is live; the next send refuses). The cost is operator-visible audit-trail divergence, not legal exposure. Asymmetric-failure-cost calculus per PILLAR-PLAN §0 + ADR-0025 D100: missing audit trail > missing suppression. The YAML-first order biases toward the right failure mode.
- **Why likelihood 1 (low):** The write window between YAML rename + ledger append is microseconds in normal operation. Crash mid-window requires either a hardware/OS-level fault during the handler's hot path OR a deliberately-injected failure. Operators running on stable infrastructure see effectively zero occurrences.
- **Mitigation plan (already shipped Week 4-5):**
  - **YAML-first write order.** ADR-0028 D116 + the crash-injection test `tests/test_auto_unsubscribe.py::TestRunAutoUnsubscribeApplyPath::test_yaml_write_first_invariant_under_ledger_append_failure` pin the invariant. The handler's `forget_append` call completes BEFORE the `led.append` is attempted; a failure between them leaves the YAML LIVE.
  - **Within-batch dedup-by-(reply_message_id, channel) per ADR-0028 D117.** The handler's `seen_this_batch` set ensures a second classified event for the same pair WITHIN the same handler run doesn't re-attempt the YAML+ledger write (avoiding compounding the inconsistency).
  - **Cross-run dedup per ADR-0028 D117.** The `already_suppressed` set walks existing `suppression_added` events; a re-run after an asymmetric crash sees that the YAML entry is live but the suppression_added event ISN'T → re-emits the missing ledger event. Resolves the inconsistency by next-run convergence (operator can run `--passes M` after the crash to heal).
  - **Operator-visible failure mode.** The `errors` field in the `AutoUnsubscribeResult` surfaces the failed ledger append; the operator sees the failure in the per-pass log without it being silent.
  - **Pillar I doctor extension (planned).** A future reconcile-pass (or doctor preflight extension) walks the YAML + the ledger + emits a `suppression_remediation` event for entries lacking a paired `suppression_added` (or vice versa). The Pillar I CLI ergonomic for this is `python -m orchestrator.auto_unsubscribe verify` (TBD).
- **Operator-side remediation:** Operators observing an inconsistency can:
  - Compare `cat ~/.outreach-factory/suppressions/auto-unsubscribe.yml` against `python -m orchestrator.ledger grep --type suppression_added` — diff the email/identity-key sets.
  - Re-run `python -m orchestrator.reconcile --passes M --apply` — the cross-run dedup ensures the second handler run emits the missing `suppression_added` events for live YAML entries without re-writing the YAML.
  - File a `manual_override` event documenting the divergence for the audit trail.

### R016 — LLM cost runaway from inbox flood (LLM fallback classifier)

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar D Week 6-8 — `orchestrator/reply_classifier_llm.py::LLMFallbackClassifier`)
- **Status:** Mitigated by design (ADR-0029 D127's classifier-cap migration + opt-in posture); residual operator-side runaway-in-single-batch surface deferred to operator-deliberate `BudgetPerRunCapRule` configuration
- **Description:** Pillar D Week 6-8 ships the LLM fallback classifier. The LLM is invoked once per reply event whose rule classifier returns `category=uncategorized` per ADR-0029 D124's narrow trigger. **Failure mode:** a spam wave OR a malformed reply pattern surfaces hundreds of `uncategorized` rule outcomes in a single reconcile run; the LLMFallbackClassifier invokes the LLM for each one; the per-call cost ($0.0006 at Haiku 4.5 rates) compounds into ~$0.06 for 100 calls in one batch. Per-month runaway is bounded by the `reply-classifier-llm-monthly-cap` rule (per D127), but the within-batch runaway can exceed the operator's per-batch budget expectations before the monthly cap fires.
- **Why severity 2 (medium):** The runaway is bounded — Haiku rates are ~$0.0006/call, so even a 1000-reply flood costs ~$0.60 (under most operators' batch budgets). The monthly cap fires when the operator's total monthly spend reaches the configured `max_units`. The cost runaway is operator-visible (Pillar G dashboards show LLM cost; operators tune `max_units` accordingly).
- **Why likelihood 2 (medium):** Inbox floods are uncommon but not rare. Operators with high outreach volume + a recently-classified spam wave OR an attack campaign targeting their classifier can trigger. The asymmetric-failure-cost calculus per PILLAR-PLAN §0: bounded cost is preferable to crashed classifier or unbounded spend.
- **Mitigation plan (already shipped Week 6-8):**
  - **Classifier-cap migration (`policy/0007_add_reply_classifier_llm_cap`).** Per ADR-0029 D127 — adds operator-tunable `reply-classifier-llm-monthly-cap` rule of type `budget.window-cap` with `source: reply_classifier_llm` + `window_days: 30` + `max_units: 50` (calibrated against Yang's expected ~30 long-tail uncategorized replies/month with 1.5-2.5× safety margin). The factory ships commented; operators uncomment to activate.
  - **Known v1 limitation: the cap is OBSERVABILITY-ONLY, NOT pre-call enforcement.** Per the Week 6-8 surface audit (`.planning/REVIEW-pillar-d-surface-audit.md` §"The cap-rule firing surface — `policy_blocked` events"), the `LLMFallbackClassifier` does NOT consult the policy engine for a pre-call gate check before invoking the LLM. The cap aggregates `cost_incurred` events post-hoc; operators monitor via Pillar G dashboards + tune `max_units` accordingly. **The Pillar I CLI extension** (TBD) is the future enforcement surface — a pre-call gate check skips the LLM + emits `policy_blocked` when the cap fires. Until then, the cap's role is operator-visible accounting + risk surface, not absolute spend protection.
  - **Opt-in posture at wiring layer.** Per ADR-0029 D124 — the LLMFallbackClassifier is constructed at the operator's wiring site (Pillar I CLI surface; v1 operators implement the wiring). Pass G accepts a `RuleBasedClassifier` by default; operators who don't opt into the LLM fallback don't see the cost.
  - **Defense-in-depth per-run cap via existing `BudgetPerRunCapRule` (ADR-0006).** Operators wanting bounds within a single reconcile invocation ship a `BudgetPerRunCapRule` instance with `source: reply_classifier_llm` (using the existing rule class — no new code needed). Per-run defense bounds the cost within one batch even if the monthly cap hasn't fired yet. **Same v1 observability-only limitation applies** — the per-run cap aggregates events post-hoc; the future Pillar I pre-call gate check would enforce both caps together.
  - **Narrow dispatch trigger.** Per ADR-0029 D124 the LLM is consulted ONLY on `rule_result.category=uncategorized`. Rule matches (the high-precision subset) don't trigger LLM calls. The cost is bounded by the uncategorized rate, not total reply rate.
  - **Pillar G observability.** The `cost_incurred` event class surfaces per-source spend via Pillar G dashboards. Operators see the LLM cost trend over time + tune `max_units` accordingly.
- **Operator-side remediation:** Operators observing cost runaway can:
  - Uncomment the cap rule in `cooldowns.yml` if not already active: `name: reply-classifier-llm-monthly-cap`. After the next dispatcher invocation the cap takes effect.
  - Add a per-run defense rule via `BudgetPerRunCapRule` with `source: reply_classifier_llm` + `max_usd: <amount>` (e.g., `$1.00` per batch).
  - Skip the LLM fallback temporarily by passing the bare `RuleBasedClassifier` to Pass G (operator-deliberate wiring change at the script level).
  - Tune the rule patterns to capture more uncategorized replies as rule matches — reducing the LLM call surface to its semantic minimum. Operators inspecting the Pillar G uncategorized-pattern dashboard add patterns for the most common uncategorized text shapes.
  - File a `manual_override` event to bypass the cap for a window if the operator needs higher throughput for a one-time campaign.

### R017 — TTL-driven dormancy of active threads → false-positive abandonment of engaged conversations

- **Severity / Likelihood:** 1 / 2
- **Owner:** unassigned (Pillar D Week 9-11 — `orchestrator/conversation_state.py` TTL driver + `orchestrator/conversation_outcomes.py` Pass O)
- **Status:** Mitigated by design (ADR-0030 D132's operator-tunability + zero-disables); residual per-channel-refinement surface deferred to Pillar I CLI extension
- **Description:** Pillar D Week 9-11 ships the TTL-driven `* → dormant` transition. A conversation thread in `replied` / `classified` / `active` state for more than `--conversation-ttl-days` (default 30) days transitions to `dormant` automatically, and Pass O emits a corresponding `conversation_outcome` event (typically `dormant`, possibly `closed_won` if a booking lands later). **Failure mode:** an operator running a long sales-cycle outreach OR running an offline pipeline that the framework doesn't observe (e.g., conversation continues via Slack / phone / in-person meeting after an initial reply) has the framework mark the thread as dormant after 30 days. The dormant outcome triggers downstream Pillar G dashboard reporting + Pillar E re-engagement logic that may incorrectly assume the conversation is abandoned. **The false-positive is operationally reversible** — a new reply / operator-initiated touch creates a new thread or re-activates state via `compute_thread_states`'s deterministic walk — but the historical `conversation_outcome.dormant` event stays in the ledger as a snapshot observation.
- **Why severity 1 (low):** The dormant outcome is OBSERVATIONAL, not enforcing. Unlike `closed_unsubscribed` (which feeds suppression), `dormant` doesn't block future touches or actions. The operator's pipeline may still proceed normally; the event is a dashboard signal, not a gate. A false dormant marking causes noise in dashboards but no operational harm.
- **Why likelihood 2 (medium):** Long-cycle operators (B2B enterprise outreach with multi-month sales cycles) + operators with offline pipelines are not the median operator but exist. The 30-day default is calibrated for the median; outlier operators are at higher risk unless they tune.
- **Mitigation plan (already shipped Week 9-11):**
  - **Operator-tunable TTL via CLI flag.** Per ADR-0030 D132 — `python -m orchestrator.reconcile --full --conversation-ttl-days 60` (or higher) for operators with long sales cycles. Documented in the reconcile docstring + the `--conversation-ttl-days` flag's help text.
  - **Zero-disables TTL entirely.** `--conversation-ttl-days 0` disables the TTL driver per ADR-0030 D132. Operators with fully-offline pipelines (or operators who want to manage dormancy manually) bypass the TTL surface entirely.
  - **TTL respects STATE_PRIORITY.** Per ADR-0030 D132 + `tests/test_conversation_outcomes.py::TestTTLTransitions::test_unsubscribed_NOT_affected_by_ttl` — TTL CANNOT demote terminal `unsubscribed` (legal-liability invariant). The TTL surface is bounded to non-terminal states.
  - **Operator-visible failure mode.** The `trigger_event_id.driver: "ttl"` field on TTL-driven `conversation_state_changed` events lets operators distinguish TTL-driven from category-driven dormancy in dashboards + ad-hoc ledger queries. Operators investigating false dormant markings see the TTL provenance immediately.
  - **Recent-activity-resets-window discipline.** Per ADR-0030 D132 — `ThreadState.last_activity_ts` tracks the MOST RECENT driver event for the thread (not the first). A subsequent reply on a thread resets the TTL window. Operators who see a new reply land + the thread re-classified see the dormant marking auto-reverse on the next reconcile run.
  - **Pillar I CLI extension (planned).** Per-channel TTL refinement (`--conversation-ttl-days email=30,linkedin=14,twitter=7,calendar=60`) deferred to Pillar I CLI if operator demand materializes. The v1 single-knob is parse-shape-compatible with the future extension.
- **Operator-side remediation:** Operators observing false dormant markings can:
  - Tune `--conversation-ttl-days` upward (e.g., `--conversation-ttl-days 90` for long-cycle outreach).
  - Disable TTL entirely with `--conversation-ttl-days 0` and manage dormancy manually via direct ledger queries.
  - Query the ledger for TTL-driven dormancy: `python -m orchestrator.ledger grep --type conversation_state_changed | jq 'select(.trigger_event_id.driver == "ttl")'` (TBD CLI; today operators grep with `jq`).
  - Re-engage the thread by sending a follow-up touch — the new `*_confirmed` event resets the thread's `last_activity_ts`; the next reconcile run sees the thread within-window again. The historical `conversation_outcome.dormant` event remains as observation.

### R018 — Discovery-source poisoning (operator scrapes inaccurate list → misattributed `closed_won`)

- **Severity / Likelihood:** 3 / 3
- **Owner:** unassigned (Pillar E Week 1 surface + Pillar I doctor preflight)
- **Status:** Mitigated by design (ADR-0032 D142's `source_list` operator-private + `raw_input_hash` audit field; Pillar I CLI doctor extension deferred)
- **Description:** Pillar E Week 1 ships ADR-0032 D142's `discovery_lineage:` block carrying `source_skill` + `source_list` + `scraped_at` + `raw_input_hash` fields. **Failure mode:** the operator scrapes an inaccurate list (a competitor's customer-list page that lists prospects not actually using the competitor; a VC's portfolio page that lists deals that never closed; a stale conference-attendee list with disbanded companies). The discovery skill stamps `source_list: <inaccurate-list>` on every enrolled Person. Downstream `closed_won` attribution per ADR-0030 D131 incorrectly credits the misattributed source — Pillar G's per-source funnel breakdown reports the wrong "this list yielded N customers" signal; the operator's tuning loop (more scraping from sources that yield `closed_won`) amplifies the wrong source. The operator cannot easily distinguish "this prospect was found on list X but actually came from elsewhere" from "this prospect was correctly attributed to list X."
- **Why severity 3 (medium):** The operator's tuning-loop signal is degraded but not corrupted — `closed_won` is still real even when the source attribution is wrong; the operator's revenue is preserved. The cost is operator-tuning-feedback noise + potential misallocation of scraping effort. The operator-discoverable failure mode (sources that "shouldn't yield this many `closed_won`") is the early warning.
- **Why likelihood 3 (medium):** Operator-curated lists are operator-controlled; inaccurate lists exist (competitor pages are scraped from public-facing marketing, which may exaggerate; VC portfolio pages include deals that never closed or were redirected). The frequency is moderate — operator-attention catches most cases but the tail is real.
- **Mitigation plan (already shipped Week 1 + planned):**
  - **The `raw_input_hash` field surfaces the operator's scrape provenance for audit.** Operators questioning a source's attribution can reconstruct: "did this prospect's enrollment carry hash X? does hash X correspond to the list I scraped on date Y?" The hash is the immutable signature.
  - **`source_list` is operator-PRIVATE per ADR-0032 D148.** Not surfaced in operator-facing dashboards; only available via direct ledger query. Operator-internal audit (the operator KNOWS their lists) is the right grain for source-attribution review.
  - **Pillar I doctor preflight (planned).** A future doctor command walks the operator's recent `closed_won` events + groups by `source_list` + flags lists with anomalous per-list `closed_won` rates (e.g., 100% `closed_won` from one list = likely misattribution; 0% from another = likely poisoning).
  - **Operator-side remediation:** Operators noticing misattribution can `python -m orchestrator.ledger grep --type enrolled | jq '.[] | select(.source_list == "<bad-list>")'` → identify affected enrollments → file `manual_override` events documenting the correction. The corrections feed Pillar G's per-source dashboards' "operator-corrected attribution" filter.
- **Operator-side remediation:** Operators observing misattribution can:
  - Query the ledger for the affected prospects: `python -m orchestrator.ledger grep --type enrolled | jq '.[] | select(.identity_keys.discovery_lineage.source_list == "<list>")'` (TBD CLI surface; today operators grep + jq).
  - File `manual_override` events per ADR-0007 documenting the correction; Pillar G's per-source breakdown filters override events out of the per-list `closed_won` rate.
  - Tune their scraping process — exclude inaccurate sources or amend the per-source canonicalization (the `raw_input_hash` computation) to encode source-quality signals.

### R019 — Pre-enrichment dedup false-positive (distinct people share identity-key partial → collapsed enrollment)

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar E Week 2 — `orchestrator/discovery_dedup.py` — SHIPPED 2026-05-24)
- **Status:** Mitigated by design (ADR-0032 D143's REUSE of `identity.resolve_strict`'s strict 2+ refusal policy; the dedup primitive's concurrent-race back-stop is the existing identity-resolver's `enrollment_conflict` shape; the Week 2 dedup primitive ALSO emits `discovery_dedup_conflict` events for the pre-enrichment ambiguous-multi-match case — operator-visible parity with `enrollment_conflict`)
- **Description:** Pillar E Week 2 ships ADR-0033 (Accepted)'s pre-enrichment dedup primitive per ADR-0032 D143. The primitive consults `identity.find_matches` BEFORE the discovery skill calls Apollo / PDL / Reoon; on dedup hit, the enrichment is skipped. **Failure mode:** two distinct people share an identity-key partial (shared family email like `info@familybusiness.com`; cofounder mailbox like `team@startup.com`; shared LinkedIn slug after a profile takeover where the URL slug was reused). The dedup primitive's `find_matches` call returns the EXISTING person as a match for the NEW (distinct) candidate; the primitive emits `discovery_dedup_hit` + skips the enrichment; the operator's "new prospect" is silently absorbed into the existing Person's enrollment.
- **Why severity 2 (medium):** The false-positive collapses two distinct prospects into one — the second prospect is invisible to the dispatcher until manual investigation. The downstream consequences: missed outreach to the second prospect; potential mis-targeted touch using the first prospect's research dossier. The asymmetric-failure-cost calculus per PILLAR-PLAN §0: false-positive dedup is one missed enrollment we re-discover next surfacing (cheap); the true cost is the operator's manual-investigation overhead.
- **Why likelihood 2 (medium):** Shared-identity-partial scenarios are uncommon at v1 scale (Yang's ~500 Persons) but real (family businesses; cofounder mailboxes; LinkedIn slug reuse after profile-takeover). The existing `identity._is_ambiguous_single_class_email_match` refinement (per `orchestrator/identity.py:644-667`) catches the common case (single-class email match + candidate has distinct LinkedIn → escalate to Conflict); the residual likelihood reflects the cases NOT caught by the refinement.
- **Mitigation plan (already shipped Week 1 design + Week 2-3 implementation):**
  - **The dedup primitive REUSES `identity.resolve_strict`'s strict 2+ refusal policy per ADR-0032 D143.** When the dedup check returns 2+ matches, the primitive emits `discovery_dedup_conflict` (mirroring `enrollment_conflict`) instead of silently collapsing. The operator sees a conflict report per the existing `~/.outreach-factory/conflicts/` flow.
  - **The existing `_is_ambiguous_single_class_email_match` refinement (per `identity.py:644-667`) catches single-class-email-with-distinct-LinkedIn cases.** The refinement escalates to Conflict instead of returning a Match; the dedup primitive inherits this refinement (no new code).
  - **Pillar I doctor preflight (planned).** A future doctor command audits the dedup index's collision rate + surfaces clusters of suspected-shared-partial cases (e.g., emails matching `[info|hello|team|contact]@*.com` patterns; LinkedIn slugs that match the personal-vs-company prefix discrimination per `identity._LINKEDIN_URL_RE`).
  - **Operator-side remediation:** Operators noticing collapsed enrollments can query the ledger for `discovery_dedup_hit` events on their suspected-distinct prospect; if the hit refers to a structurally-different person, the operator manually creates the Person note + files a `manual_override` correction.
- **Operator-side remediation:** Operators observing false-positive collapses can:
  - Query the dedup-hit history: `python -m orchestrator.ledger grep --type discovery_dedup_hit | jq '.[] | select(.candidate_partial.emails | contains(["<the-shared-email>"]))'` (TBD CLI).
  - Manually create the distinct Person note in the vault (using a non-conflicting identifier — e.g., the LinkedIn slug if available; or a unique GitHub handle).
  - File a `manual_override` event documenting the correction + the rationale.
  - If the shared identifier is structural (cofounder mailbox), remove it from one of the Person notes' `identity_keys` block so future dedup checks don't collapse.

### R020 — Email-verification cache staleness (30-day-old verified email becomes invalid mid-cache-window)

- **Severity / Likelihood:** 2 / 3
- **Owner:** unassigned (Pillar E Week 4-5 — `orchestrator/email_verification_cache.py`)
- **Status:** Mitigated by design (ADR-0032 D144's 30-day TTL + cache-hit event surfaces age for operator audit; existing `bounce_detected` Pass B flow naturally surfaces stale-cache failures); operator-side eviction CLI deferred to Pillar I
- **Description:** Pillar E Week 4-5 ships ADR-0034 (TBD)'s email-verification cache primitive per ADR-0032 D144. The primitive caches Reoon verification results for 30 days; the dispatcher consults the cache before calling Reoon. **Failure mode:** a 30-day-old verified email becomes invalid mid-cache-window (the recipient changes mailbox; their domain changes ownership; the employee leaves the company). The cache returns the stale "verified" result; the dispatcher proceeds with the send; the message bounces. The cache's stale entry continues to return "verified" until the 30-day TTL expires + a re-verify happens.
- **Why severity 2 (medium):** The failure mode is operationally bounded by the existing `bounce_detected` Pass B flow — a bounced send produces a `bounce_detected` event; Pillar D Week 4-5's auto-unsubscribe handler emits `suppression_added` for hard bounces; the suppression rule prevents future sends to the stale email. The first stale-cache send is the cost; subsequent sends are bounded. The asymmetric-failure-cost calculus per PILLAR-PLAN §0: one bounced send per stale entry is cheap (vs the Reoon spend avoidance of caching ~50 emails over a 30-day window).
- **Why likelihood 3 (medium):** Email validity decays at a ~2-3%/year rate for B2B addresses (industry estimate); over a 30-day cache window, the per-cache-entry staleness probability is ~0.2%. With ~50 cached entries per operator at v1 scale, the expected stale-hit count is ~0.1/month — uncommon but real. At higher operator scale (~500 cached entries), the count rises to ~1/month.
- **Mitigation plan (already shipped Week 1 design + Week 4-5 implementation):**
  - **30-day TTL per ADR-0032 D144's `DEFAULT_EMAIL_VERIFICATION_CACHE_TTL_DAYS = 30`.** Bounded staleness window.
  - **Cache-hit event surfaces age for operator audit per D144.** The `email_verification_cache_hit` event carries `cache_age_seconds` + `cached_at`; operators reviewing Pillar G's cache-hit dashboard see the age distribution + can identify suspect-stale entries.
  - **Existing `bounce_detected` Pass B flow naturally surfaces stale-cache failures.** A stale-cache-driven bounced send produces a `bounce_detected` event; the operator's bounce dashboard surfaces the failure; Pillar D's auto-unsubscribe handler converts the bounce into a `suppression_added` event preventing future sends.
  - **Pillar I CLI doctor extension (planned).** A future `python -m orchestrator.email_verification_cache evict --email <addr>` surface for operators wanting to manually invalidate suspect entries.
  - **Pillar I CLI extension (planned).** A future doctor command audits the cache hit-rate + per-entry age distribution + flags entries near the TTL boundary for proactive re-verification.
- **Operator-side remediation:** Operators observing stale-cache failures can:
  - Query the cache history: `python -m orchestrator.ledger grep --type email_verification_cache_hit | jq '.[] | select(.email == "<addr>")'` (TBD CLI).
  - Tune the TTL downward (e.g., `--email-verification-cache-ttl-days 14`) for higher-staleness-rate operator contexts.
  - Manually evict suspect entries (Pillar I CLI extension); until then, operators can append a synthetic `cost_incurred.source=reoon` event with a recent ts that resets the cache's per-email window.
  - The auto-suppression via `bounce_detected` → `suppression_added` flow per ADR-0028 is the operational back-stop.

### R021 — Tier-weights config drift (operator-tuned weights diverge from corpus-validated default)

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar E Week 6-8 — `orchestrator/tier_assignment.py` + `~/.outreach-factory/tier_weights.yml`)
- **Status:** Mitigated by design (ADR-0035 D161 rationale field on every event surfaces decision tree for operator audit + default-shipped template at `config-template/tier_weights.example.yml`); Pillar I doctor preflight extension deferred for config-shape validation + drift detection
- **Description:** Pillar E Week 6-8 ships ADR-0035's tier auto-assignment primitive per ADR-0032 D145. The primitive computes tier suggestions from operator-tunable per-signal weights at `~/.outreach-factory/tier_weights.yml`; the default-shipped template at `config-template/tier_weights.example.yml` carries weights calibrated against Yang's ~500 Person operator-tagged corpus at Week 6-8 ship time. **Failure mode:** an operator tunes the weights file to values that diverge from the corpus-validated defaults; the per-signal weights become misaligned with the operator's actual SoT corpus; future tier suggestions surface conflicting recommendations (e.g., S tier for prospects the operator would stamp B, or vice versa). The drift compounds over operator-time; the operator's manual stamping rate increases; the auto-assignment's accuracy claim erodes.
- **Why severity 2 (medium):** The failure mode is operationally bounded — the auto-assignment is OBSERVATIONAL per the three-step decoupling per ADR-0032 D145 (SUPPLY → STAMP → READ); the operator-stamped `Person.research_tier` field remains the SoT; the existing `policy/tier.py::TierRequiresTierInRule` reads the operator-stamped value regardless of the suggestion. A drifted weights config does NOT affect send authorization or the operator's actual tier-stamping workflow — only the framework-supplied suggestions are affected. The operator may simply ignore drifted suggestions OR re-tune the weights config.
- **Why likelihood 2 (low-medium):** Operators tuning weights typically anchor against the default template + iterate based on observed mismatches; structural drift requires deliberate tuning away from the corpus baseline. The likelihood rises if the operator's ICP shifts substantially (e.g., from AI startups to enterprise SaaS) without re-tuning; for operators with stable ICPs, drift is unlikely.
- **Mitigation plan (Week 6-8 design + Pillar I extensions deferred):**
  - **Rationale field on every event per ADR-0035 D161.** The `rationale` string surfaces the decision tree per suggestion (e.g., `"Series A + AI/ML industry + funded-founders source → score 7 → high-intent S tier"`); operators auditing suggestions see exactly which signals + which weights drove the recommendation; mismatches with the operator's intuition are operator-readable.
  - **Default-shipped template at `config-template/tier_weights.example.yml`.** The template carries explanatory comments naming each weight's rationale; operators inheriting the framework get the corpus-validated defaults from the first invocation.
  - **Operator-tunable surface preserves flexibility.** Operators with different ICPs can tune without forking the framework; the per-signal weights are operator-deliberate.
  - **`signals_consulted` field for coverage audit.** Operators reviewing `tier_suggested` events see which signals were absent (e.g., `organization_size: None` when Apollo enrichment hasn't run); the per-signal coverage rate surfaces enrichment-gap-driven drift.
  - **Pillar I doctor preflight extension (planned).** A future `python -m orchestrator.doctor tier-weights` extension MAY validate the operator's config shape against the default template + flag per-signal weight divergence beyond a configurable threshold + surface the operator's per-tier distribution against the corpus baseline for drift detection.
  - **Pillar I `calibrate --corpus` CLI extension (planned).** A future `python -m orchestrator.tier_assignment calibrate --corpus <vault>` extension walks the operator's actual corpus + computes per-signal regression coefficients + emits a tuned weights file (overwrites the operator-private config). Operators with growing corpora (10K+ Persons with operator-stamped tiers) re-calibrate periodically.
- **Operator-side remediation:** Operators observing tier-suggestion accuracy drift can:
  - Diff their config against the default template: `diff ~/.outreach-factory/tier_weights.yml config-template/tier_weights.example.yml`.
  - Reset to the default template: `cp config-template/tier_weights.example.yml ~/.outreach-factory/tier_weights.yml`.
  - Query the suggestion history: `python -m orchestrator.ledger grep --type tier_suggested | jq '.[] | {pid: .person_id, suggested: .suggested_tier, rationale: .rationale}'` (existing).
  - Tune the weights based on observed mismatches between `tier_suggested.suggested_tier` and the operator-stamped `Person.research_tier`.
  - Wait for the Pillar I `calibrate --corpus` extension for automated re-calibration as the corpus grows.

### R022 — Discovery_lineage backfill heuristic precision (vault migration 0005's cascade mis-attributes a Person's source_skill)

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar E Week 9-11 — `orchestrator/migrations/vault/migration_0005_add_discovery_lineage_to_identity_keys.py` + `orchestrator/discovery_lineage.py`)
- **Status:** Mitigated by design (ADR-0036 D168's per-source backfill count logged at apply time + operator-resolution CLI command surfaced + R022 mitigation surface explicit in ADR-0036 §Risks); Pillar I doctor preflight extension deferred for backfill-confidence reporting
- **Description:** Pillar E Week 9-11 ships ADR-0036's vault migration 0005 per D168. The migration backfills the canonical `identity_keys.discovery_lineage:` sub-block on every pre-Week-9-11 Person note via a four-step cascade (`_source.md` parseable → `source_channel:` frontmatter → ledger `enrolled.source` → `source_skill: manual` floor). **Failure mode:** the cascade's per-source confidence is bounded but not guaranteed — (a) `_source.md` parsing depends on the operator's file-shape convention (markdown vs YAML vs free-form); (b) `source_channel:` legacy values use shortened naming (`"funded-founders"` not `"find-funded-founders"`) — the `LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL` normalization map MUST cover every legacy value; (c) Persons enrolled via the legacy `enroll_person` path before the `source_channel:` field convention land on the `source_skill: manual` floor — provenance is lost for those Persons; (d) unknown legacy values (operator-supplied free-form values not in the normalization map) all normalize to `"manual"` — the operator's deliberate provenance categorization is collapsed.
- **Why severity 2 (medium):** The failure mode is operationally bounded — the per-Person mis-attribution affects only the framework-supplied tier suggestion (Pillar E Week 6-8's `tier_assignment.py` consumes `discovery_lineage.source_skill` for the intent-signal contribution); a mis-attributed Person gets a slightly-different tier suggestion. The operator-stamped `Person.research_tier` field remains the SoT; the existing `policy/tier.py::TierRequiresTierInRule` reads the operator-stamped value regardless of the mis-attribution; the operator's send authorization is unaffected. Future Pillar G dashboards aggregating by `source_skill` would surface the mis-attribution as inflated `manual` counts, but the operator can correct per-Person via the CLI.
- **Why likelihood 2 (low-medium):** The cascade's earliest steps (`_source.md` + `source_channel:`) cover ~70-80% of typical post-Phase-5.5 Person corpora; the `source_skill: manual` floor catches the residual ~10-15% with operator-visible diagnostic logging. The mis-attribution likelihood depends on operator hygiene — operators maintaining `_source.md` files + canonical `source_channel:` values see ~99% accuracy; operators with free-form legacy values see proportionally higher mis-attribution rates.
- **Mitigation plan (Week 9-11 design + Pillar I extensions deferred):**
  - **Per-source backfill counts logged at apply time per ADR-0036 D168.** The migration's stderr summary names the per-source counts: `from _source.md: N Persons`, `from source_channel: N`, `from ledger enrolled.source: N`, `fallback to source_skill: manual: N`. Operators reviewing the apply output see the confidence distribution + identify high-manual-floor counts as the operator-correctable surface.
  - **Operator-resolution CLI command surfaced per ADR-0036 D168.** The migration's stderr summary names the per-Person resolution path: `python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>`. Operators correcting any per-Person mis-attribution shell to the CLI per-Person; the CLI handles the strict-insert + the construction-time validation.
  - **Operator-visible stderr enumeration of manual-floor person_ids.** The migration logs up to 10 of the first manual-floor person_ids at WARNING level (operators with >10 manual-floor Persons see the truncated list + the count for triage).
  - **Centralized normalization map per ADR-0036 D167.** The `LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL` dict is the single source of truth for the rename trajectory; future operator-supplied legacy values that surface in production can be added to the map via an ADR amendment.
  - **The cascade prefers richer sources.** The `_source.md` + `source_channel:` paths preserve operator-supplied provenance; the ledger fallback preserves event-time provenance; only the manual floor loses provenance entirely.
  - **Pillar I doctor preflight extension (planned).** A future `python -m orchestrator.doctor discovery-lineage-backfill` extension MAY audit the operator's per-Person discovery_lineage coverage + flag manual-floor counts beyond a configurable threshold + surface the per-source confidence distribution + recommend backfill operations.
  - **Reversible migration per ADR-0036 D168.** Operators applying the migration + observing high manual-floor counts can `python -m orchestrator.migrations doctor rollback --migration vault/0005_add_discovery_lineage_to_identity_keys` + re-tune their `_source.md` / `source_channel:` provenance + re-apply.
- **Operator-side remediation:** Operators observing high manual-floor counts (e.g., >20% of corpus) can:
  - Audit the cascade's per-source coverage: `python -m orchestrator.migrations doctor apply --dry-run` (the dry-run logs per-source counts without mutation).
  - Re-tune their vault's `source_channel:` fields to match the canonical `LEGACY_SOURCE_CHANNEL_TO_SOURCE_SKILL` mapping (e.g., rename operator-typed `"funded_founders"` to canonical `"funded-founders"`).
  - Add per-list `_source.md` files for any Persons under hand-curated lead lists (the migration's first-cascade source).
  - Run the per-Person CLI for each mis-attributed Person: `python -m orchestrator.discovery_lineage backfill --person <id> --source-skill <skill>` per ADR-0036 D168.
  - Filter the apply log for the manual-floor list: `grep "manual-floor person_id" <apply-log>`.
  - Defer to the Pillar I doctor preflight extension for automated per-Person triage at higher operator scale.

> **R023 through R030 are SUPERSEDED.** They all describe the voice-corpus / embedding-retrieval and draft-quality subsystem (Pillar F), which has been removed from the product. The de-AI step is now a fresh-context humanizer pass that rewrites the assembled draft against an anti-tell checklist plus a single reference example; there is no voice corpus, no embedding index, no `sentence-transformers` dependency, and no per-register fidelity scoring. These entries are retained for historical context only. See the Pillar F removal ADR.

### R023 — Hallucination-detection false-negative (un-cited claim slips past the gate)

- **Severity / Likelihood:** 1 / 3
- **Owner:** unassigned (Pillar F Week 6+ — `orchestrator/draft_quality.py` + `tests/test_multi_channel_coherence.py::TestHallucinationDetection` + `tests/test_multi_channel_coherence.py::TestPillarFExitCriterion`)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0038 D180's FIVE-layer defense-in-depth + the 200-draft eval set's `<1%` false-negative bound per PILLAR-PLAN §2 Pillar F + the per-claim trace per D180 + the per-week-ship trajectory of the layers); residual operator-visible per-claim audit surface lands at Week 6+ (Layer 3 ships the per-claim trace as `uncited_claims`)
- **Description:** Pillar F Week 6+ ships the hallucination-detection primitive per ADR-0038 D180. The primitive's FIVE-layer defense bounds the false-negative rate; the 200-draft eval set's `<1%` target per PILLAR-PLAN §2 Pillar F binding text is the binding exit-criterion gate per Week 12. **Failure mode:** an adversarial draft carries an un-cited claim ("you posted last week that X" where X is NOT in the research dossier) that the gate fails to catch; the draft reaches `ready` state; the dispatcher sends to the recipient. The recipient catches the lie + the operator's brand suffers + the relationship is destroyed + the failure may surface as a public callout (LinkedIn comment / Twitter post quoting the fabricated claim). **The first false-negative is the high-cost event** — operator brand recovery is months-long; the per-recipient relationship may be unrecoverable.
- **Why severity 1 (catastrophic):** The asymmetric-failure-cost calculus is unambiguous — a single false-negative in a cold-pitch to a high-profile recipient (CEO, public-facing founder, journalist) carries reputational + relational + (in extreme cases) legal-liability consequences. The failure is operator-visible only post-send (or never — if the recipient silently judges + disengages); operator-corrective action after the fact is bounded.
- **Why likelihood 3 (medium):** The hallucination space is large (every "you" + "your" phrase + every dated reference + every named-entity reference is a potential claim) but the gate's per-claim parser per D180 Layer 3 covers the common cases. The residual likelihood reflects the edge cases — paraphrased claims that match the citation set semantically but not lexically; multi-sentence claims that distribute across the draft; implicit claims that the parser doesn't extract.
- **Mitigation plan (designed Week 1; implementation Weeks 6-12):**
  - **Layer 1 (Week 1 — this commit): test corpus pin.** `tests/test_multi_channel_coherence.py::TestHallucinationDetection::test_draft_with_uncited_claim_fails_gate` stub names the binding behavior. Future contributors weakening the parser would fail the test loudly. The test corpus seeds the eventual 200-draft eval set's adversarial subset.
  - **Layer 2 (Week 6): construction-time invariant on `DraftQualityResult`.** Refuses to construct a `ready`-state result when `uncited_claims` is non-empty. Mirrors Pillar E's `DiscoveryLineage.__post_init__` per ADR-0036 D167.
  - **Layer 3 (Week 6): parse-level guard.** The draft engine's output parser (`orchestrator/draft_quality.py::parse_draft_for_claims`) extracts every claim + cross-references against the research dossier's citation set. Un-cited claims surface as `uncited_claims` on the result.
  - **Layer 4 (Week 10): post-engine guard on event emission.** The `draft_ready` event emission walks the `uncited_claims` field + refuses to emit when non-empty. Mirrors the Pillar D Week 4-5 `suppression_added` event's YAML-first-then-ledger discipline per ADR-0028 D116.
  - **Layer 5 (Week 12): reconcile heal-pass refusal.** The `pipeline_stage: ready` heal in `reconcile.py` Pass C refuses to advance a Person to `ready` when the linked draft's `draft_quality_scored` event carries `uncited_claims` non-empty. The final structural backstop — a draft that bypassed Layers 1-4 still cannot advance the pipeline.
  - **The 200-draft eval set's `<1%` false-negative bound (Week 12).** The binding exit-criterion test per PILLAR-PLAN §2 Pillar F: 180 valid drafts MUST pass the gate; 20 adversarial drafts MUST be caught. The test is the structural verification.
- **Operator-side remediation:** Operators observing a missed hallucination can:
  - Query the per-draft history: `python -m orchestrator.ledger grep --type hallucination_detected | jq '.[] | select(.person_id == "<pid>")'` (TBD CLI).
  - File a `manual_override` event documenting the missed claim + the operator-side correction.
  - Tune the per-register fidelity threshold per `~/.outreach-factory/voice_thresholds.yml` if the missed hallucination correlates with a low-fidelity score (the high-fidelity drafts may bias the parser toward acceptance).
  - Add the per-claim pattern to the operator's adversarial training corpus for the next periodic gate re-calibration.

### R024 — Voice-corpus drift (operator's voice changes over time, retrieval surfaces stale exemplars)

- **Severity / Likelihood:** 3 / 3
- **Owner:** unassigned (Pillar F Week 2+ — `orchestrator/voice_corpus.py` + per-register fidelity scoring at Week 8)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0038 D179's deterministic-clock contract + the existing `RECENT_BIAS` per-year multiplier per `voice_retrieve.py:113` + the per-register fidelity-score tracking at Week 8); Pillar I drift-detection doctor extension deferred
- **Description:** Pillar F Week 2+ ships the embedding-retrieval primitive per ADR-0038 D179. The primitive consults the operator's curated voice corpus (`~/.outreach-factory/voice-corpus/index.json`). **Failure mode:** the operator's voice evolves over time (new vocabulary, changed register conventions, updated company context per `~/.outreach-factory/config.yml` rewrites) but the static corpus stays at its build-time snapshot; the retrieval surfaces exemplars from a year ago that no longer reflect the operator's current voice. Over Pillar F Weeks 4-8 the per-register fidelity-score distribution surfaces drift — older exemplars start scoring lower against the operator's most-recent drafts; the operator's downstream drafts inherit stale-voice signals.
- **Why severity 3 (medium):** The failure mode is operator-discoverable + operator-correctable — operators noticing stale-voice signals can re-tag the most-recent corpus samples + re-build embeddings + tune the per-register thresholds. The cost is operator-tuning-feedback noise + potential mis-voice on draft outputs. Asymmetric-failure-cost: a stale-voice draft surfaces with lower fidelity score (Layer per-register threshold catches it pre-send); operators re-draft or override per their judgment.
- **Why likelihood 3 (medium):** Voice drift is gradual; over a 1-2 year operator window the drift is moderate (most operators' voice stays recognizable). The frequency is moderate — operators with rapidly-changing context (new company, new wedge, new product framing per ADR-0035-style ICP shifts) see proportionally higher drift rates.
- **Mitigation plan (designed Week 1; implementation Weeks 2-12):**
  - **The existing `RECENT_BIAS = True` per-year multiplier per `voice_retrieve.py:113` biases retrieval toward recent exemplars.** Pillar F Week 2's new primitive per D179 preserves this bias + extends with operator-tunable per-year multiplier strength (TBD per the Week 2 design — operators may tune recency-bias upward for high-drift contexts).
  - **The deterministic-clock contract per D179.** The retrieval primitive accepts an optional `now` kwarg per ADR-0031 D140 + ADR-0034 D156 + ADR-0035 D162 deterministic-clock precedent. Test-time reproducibility + operator-deliberate clock-skew investigations (e.g., "what would the retrieval surface 6 months ago?") are supported.
  - **The per-register fidelity-score tracking at Week 8+.** The `draft_quality_scored` event per ADR-0038 D182 carries the per-draft fidelity score; the Pillar G dashboards aggregate per-register score distributions over time + surface drift trends. Operators noticing per-register score decline correlate with corpus-age-percentile.
  - **The operator-tunable per-register thresholds at `~/.outreach-factory/voice_thresholds.yml` per D184.** Operators tune as drift accumulates.
  - **Pillar I doctor preflight extension (planned).** A future `python -m orchestrator.doctor voice-corpus-drift` extension MAY analyze the operator's per-register score distribution over time + flag drift beyond a configurable threshold + recommend corpus refresh.
- **Operator-side remediation:** Operators observing voice drift can:
  - Re-build embeddings against the current corpus: `python -m orchestrator.voice_corpus rebuild` (TBD CLI; Pillar F Week 2 ships).
  - Re-tag samples with current `register` + `channel` values + `is_substantive_reply: true` for the most-effective recent exemplars (per the Phase 2 voice-fingerprint discipline in `/draft-outreach` SKILL.md:111).
  - Tune the per-register fidelity thresholds downward to accept slightly-lower-score drafts during a transition period.
  - Add recent operator-stamped voice-anchor email at `voice.voice_anchor_path` per the existing config convention; the new primitive at Week 2+ MAY consume the anchor as a per-call retrieval boost.
  - File `manual_override` events for the persistently-stale-voice drafts; the override surface bypasses the gate.

### R025 — Embedding-cost runaway from cloud embedding model + frequent corpus rebuild

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar F Week 2+ — `orchestrator/voice_corpus.py` + `orchestrator/policy/budget.py::COST_RATES_USD`)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0038 D179's default-to-local `BAAI/bge-small-en-v1.5` model + operator-opt-in cloud model choice + R025-aware cap rule template at Week 2+ deferred)
- **Description:** Pillar F Week 2+ ships the embedding-retrieval primitive per ADR-0038 D179. The default embedding model is `BAAI/bge-small-en-v1.5` (local CPU; zero per-call cost; ~1-5 minutes CPU per 10K-sample rebuild). Operators MAY opt in to a cloud embedding model (e.g., OpenAI's `text-embedding-3-small` at $0.00002/1K tokens) for higher embedding quality or shared-machine convenience. **Failure mode:** an operator opts in to a cloud model + their corpus grows to 10K-100K samples + their rebuild cadence is high (per-week corpus refresh) → per-rebuild cost compounds. A 100K-sample corpus × ~500 tokens/sample × $0.00002/1K tokens = $1.00 per rebuild; weekly rebuilds = ~$52/year per operator. **Mid-sized operator concern; rebuild-cadence concern; opt-in concern.**
- **Why severity 2 (medium):** The failure mode is operator-visible (the operator opts in to the cloud model deliberately + sees the cost in Pillar G dashboards) + operator-correctable (tune the rebuild cadence; switch back to local model). The asymmetric-failure-cost calculus: bounded cost is preferable to crashed retrieval primitive or unbounded spend.
- **Why likelihood 2 (low-medium):** The default local model covers the median operator's use case (the embedding quality is sufficient for the per-register retrieval contract). Operators opting in to cloud models are deliberate; the opt-in is a config change with operator-readable cost note. Frequency depends on operator preferences.
- **Mitigation plan (designed Week 1; implementation Weeks 2+):**
  - **Default to local `BAAI/bge-small-en-v1.5` per D179.** Operators who don't opt in see zero per-call cost.
  - **Operator-tunable embedding model choice per `voice.embed_model` config field per the Week 2 deliverable.** Operators opting in to a cloud model see the cost in the operator-readable per-rebuild diagnostic.
  - **Pricing-table extension per ADR-0006 discipline.** IF an operator selects a paid model, the Week 2+ commit MUST update `orchestrator/policy/budget.py::COST_RATES_USD` with the new source name (`cost_incurred.source=voice_embedding` or per-vendor sub-source). Per ADR-0006 §"CI enforcement of the price-update == ADR-amendment discipline" the future Pillar I CI extension verifies the pricing-table change is accompanied by an ADR amendment.
  - **R025-aware cap rule template (Pillar F Week 2+).** The Week 2+ commit MAY ship a commented-out `voice-embedding-monthly-cap` rule template at `config-template/cooldowns.example.yml` (mirrors the existing `reply-classifier-llm-monthly-cap` per ADR-0029 D127). Operators opt in by uncommenting; the cap takes effect once the operator's `cost_incurred.source=voice_embedding` events accumulate. **Known v1 limitation: the cap is OBSERVABILITY-ONLY per the Pillar D Week 6-8 precedent** — the rebuild does NOT consult the policy engine for a pre-call gate check; the cap aggregates events post-hoc; operators monitor via Pillar G dashboards + tune `max_units` accordingly.
  - **Per-rebuild operator-readable cost estimate.** The rebuild CLI prints an estimate before executing (operator-deliberate confirmation prompt for cloud-model rebuilds beyond a threshold).
- **Operator-side remediation:** Operators observing embedding cost runaway can:
  - Switch back to the local model: `voice.embed_model: BAAI/bge-small-en-v1.5` in `~/.outreach-factory/config.yml`.
  - Tune the rebuild cadence (rebuild monthly instead of weekly; rebuild only when the corpus grows by ≥10% in size).
  - Add the cap rule template to `cooldowns.yml` with an operator-deliberate `max_units` per their budget.
  - File a `manual_override` event for the over-budget rebuild if needed.

### R026 — Operator-corpus split (multi-machine operator has divergent embedding indices)

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar F Week 2 — `orchestrator/voice_corpus.py` metadata-mismatch refuse-loud per D179)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0038 D179's metadata-mismatch refuse-loud, with embed_model + embed_version + sentence-transformers version + schema_version pinned in the cache's sidecar `metadata.json`; the retrieval primitive refuses-loud + auto-rebuilds when allowed)
- **Description:** Pillar F Week 2 ships the embedding-retrieval primitive per ADR-0038 D179. Operators running the framework on multiple machines (laptop + desktop + cloud daemon) each build LOCAL embeddings against their synced corpus directory. **Failure mode:** the corpus files (the operator's email corpus + the operator-stamped `index.json` schema fields) are synced via Obsidian Sync / Dropbox / Syncthing, but the per-machine `embeddings.npy` is built with different sentence-transformers versions / different model weights / different sample ordering. Per-machine retrieval surfaces different exemplars for the same query; the operator's draft consistency degrades across machines.
- **Why severity 2 (medium):** The failure mode is operator-discoverable + operator-correctable — operators noticing different retrieval results across machines can rebuild embeddings on each machine to match. The cost is operator-tuning-overhead + potential per-machine draft consistency drift. Asymmetric-failure-cost: bounded by the per-machine local-rebuild trajectory (each machine ships a deterministic build per machine-local sentence-transformers version).
- **Why likelihood 2 (low-medium):** Multi-machine operators are a minority (most operators run from one machine + one cloud daemon at most). The frequency depends on operator setup; operators with a single primary machine see effectively zero occurrence.
- **Mitigation plan (designed Week 1; implementation Week 2):**
  - **Metadata sidecar `metadata.json` per D179.** The cache directory carries a `metadata.json` recording `embed_model` + `embed_version` (sentence-transformers package version) + `built_at` (ISO 8601 UTC) + `corpus_count` (sample count) + `schema_version` (the D178 schema version — `1` at Week 1). The retrieval primitive verifies metadata-on-load matches the runtime + refuses-loud on mismatch.
  - **Auto-rebuild on metadata mismatch per the operator-controlled `--rebuild-on-mismatch` flag.** Operators opting in to auto-rebuild see the cost in the operator-readable per-rebuild diagnostic; operators opting out see the refuse-loud error + manual `rebuild` invocation.
  - **Per-machine pinning of the sentence-transformers version via the project's Python environment.** Operators sharing the framework across machines SHOULD use the same Python environment + the same `requirements.txt` per `orchestrator/voice_retrieve.py:48`'s sentence-transformers import. The framework's `config-template/config.example.yml` `voice.python_bin` field is operator-tunable per-machine; operators select the per-machine venv that matches the framework version.
  - **Operator-readable cross-machine doctor command (Pillar I extension — deferred).** A future `python -m orchestrator.doctor voice-corpus-machine-sync` extension MAY surface per-machine cache metadata + flag mismatches across operator's known machines (TBD per Pillar I CLI scope).
- **Operator-side remediation:** Operators observing cross-machine retrieval divergence can:
  - Compare per-machine cache metadata: `cat ~/.outreach-factory/voice-corpus/metadata.json` on each machine + diff.
  - Rebuild embeddings on each machine: `python -m orchestrator.voice_corpus rebuild` (TBD CLI; Pillar F Week 2 ships).
  - Pin the sentence-transformers version + the embedding model version across machines via the framework's `requirements.txt`.
  - For cloud-daemon vs laptop setups, use the SAME embedding model + the SAME sentence-transformers version; the per-machine sample-order non-determinism is bounded by the build's deterministic-clock contract (the corpus sort is by `id` per D178; the per-sample embedding is deterministic for a given model + version).

### R027 — Hallucination-detection false-positive (legitimate paraphrased citation rejected as un-cited)

- **Severity / Likelihood:** 3 / 2
- **Owner:** unassigned (Pillar F Week 6+ — `orchestrator/draft_quality.py` parser precision calibration)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0038 D184's operator-tunable per-register threshold + ADR-0007's existing `manual_override` event class + the per-claim trace per D180 surfaces operator-debuggable failure context); Pillar F Week 6+ Layer 3 parser's precision calibration target named in the 200-draft eval set per Week 12 binding test
- **Description:** Pillar F Week 6+ ships the hallucination-detection primitive's Layer 3 parser per ADR-0038 D180. The parser extracts every claim from the draft (per-claim type `date_reference` + `named_entity` + `you_phrase` + `quoted_text` + `dated_event`) + cross-references against the research dossier's citation set. **Failure mode:** a draft paraphrases a real citation legitimately (operator writes "you mentioned funding is tight" when the dossier says "Q1 CFO: runway <12 months") — the parser's lexical matching fails the semantic-equivalent claim → flagged as `uncited_claims` → blocks the draft from reaching `ready` state → the operator's per-draft cost: one `manual_override` event + one re-draft for the paraphrased sentence. **The false-positive failure mode is operator-cost asymmetric** (vs R023's false-negative which is brand-damage asymmetric) — bounded but real friction for operators with paraphrastic writing styles.
- **Why severity 3 (medium):** The failure mode is operationally bounded — the operator's per-draft override surface (file `manual_override` event + re-state the citation explicitly) is straightforward. The cost is per-draft re-work + operator-tuning-feedback noise. Asymmetric-failure-cost calculus: false-positive (block legitimate draft) cost = one re-draft; false-negative (let hallucination through) cost = brand damage + relationship destruction. The D184 default per-register thresholds bias the parser toward false-positive at framework default (acceptable trade-off — operators rework rather than ship lies).
- **Why likelihood 2 (low-medium):** Paraphrased citations are common (skilled writers paraphrase rather than quote verbatim) but the parser at Week 6+ may be calibrated to surface semantic-equivalent claims (e.g., word-overlap heuristic + named-entity reuse). The likelihood depends on Layer 3's parser sophistication — at v1 (lexical-only matching) likelihood is higher; future Pillar F + Pillar H scale optimizations may add semantic similarity matching reducing the rate.
- **Mitigation plan (Week 1 design + Weeks 6-12 implementation):**
  - **The operator-tunable per-register fidelity threshold per D184.** Operators with high paraphrastic styles tune the per-register threshold downward to accept slightly-lower-fidelity drafts during their writing trajectory.
  - **The ADR-0007 `manual_override` event class is the operator-escape valve.** Operators stamp `manual_override` for the per-draft false-positive; the override surface bypasses the gate for that draft + leaves the audit trail.
  - **The per-claim trace surfaces operator-debuggable failure context per D180.** Each `uncited_claims` entry carries the `(claim_type, claim_text, citation_anchor)` triple — operators see exactly which claim was flagged + can either re-state the citation explicitly or file the override.
  - **Layer 3 parser precision calibration in the 200-draft eval set per Week 12 binding test.** The binding exit-criterion test targets `<1%` false-negative rate; the corresponding false-positive rate is operator-tunable per the threshold. The Week 8+ commit's Layer 3 ship MAY calibrate against false-positive precision targets surfaced from operator feedback during Weeks 6-12.
  - **Future Pillar H scale optimization MAY add semantic-similarity matching at Layer 3.** Beyond lexical matching, vector-similarity cross-reference against the dossier's citation set (using the same embedding model per D179) reduces false-positives for paraphrased claims. Deferred to Pillar H per the per-call performance scope.
- **Operator-side remediation:** Operators observing repeated false-positive blocks can:
  - Query the per-draft history: `python -m orchestrator.ledger grep --type hallucination_detected | jq '.[] | select(.person_id == "<pid>")'` (TBD CLI).
  - File a `manual_override` event per ADR-0007 documenting the false-positive + re-stating the citation explicitly in the next draft.
  - Tune the per-register fidelity threshold per `~/.outreach-factory/voice_thresholds.yml` if the false-positive correlates with a specific register's paraphrastic style.
  - Re-write the draft with explicit citations (quote the dossier line verbatim instead of paraphrasing) — operator-deliberate trade-off for false-positive avoidance.
  - Document the recurring false-positive pattern for the Layer 3 parser's calibration corpus during Pillar F per-week ship cadence.

### R028 — Per-register voice-fidelity threshold mis-calibration (operator's corpus distribution materially diverges from Yang's curated calibration baseline)

- **Severity / Likelihood:** 3 / 3
- **Owner:** unassigned (Pillar F Week 8+ — `~/.outreach-factory/voice_thresholds.yml` operator-tuning + Pillar I per-tenant baseline measurement extension)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0041 D199-D204's operator-tunable per-register thresholds + ADR-0045 D232's `voice.use_embedding_primitive` default flip surfaces the `draft_quality_scored` event stream that operators consume to measure per-register score distributions against their corpus); Pillar I per-tenant baseline measurement extension named in ADR-0045 §Downstream pillar impact
- **Description:** Pillar F Week 4 shipped the per-register voice-fidelity thresholds per ADR-0041 D200 with framework defaults calibrated against Yang's curated corpus (cold-pitch ≥0.70 / congrats ≥0.65 / re-engagement ≥0.72 / reply ≥0.70 / public-comment ≥0.60). Pillar F Week 8 ships the per-draft fidelity-scoring primitive per ADR-0045 D230; the primitive consumes the per-register thresholds for the per-draft gate verdict. **Failure mode:** operators with materially different corpora (different voice; different register conventions; different recipient mix; different corpus size) see the Week 4 defaults mis-calibrated for their voice distribution — either too-strict (every draft refused; operator-friction path) or too-loose (low-fidelity drafts pass; brand-risk path). The mis-calibration is operator-discoverable via the `draft_quality_scored` event stream + per-register score distribution rendering; operators tune `~/.outreach-factory/voice_thresholds.yml` per their distribution.
- **Why severity 3 (medium):** The mis-calibration is operator-discoverable + operator-tunable via the existing ADR-0041 D199-D204 surface. The failure mode is per-operator-corpus (not system-wide); the per-register threshold YAML is the operator-tunable knob. The cost is per-operator-tuning + per-draft re-work during the tuning window. The asymmetric-failure-cost calculus: too-strict (operator-friction) cost = one re-draft + one threshold tweak; too-loose (brand-risk) cost = potentially-shipped low-fidelity draft + Pillar F D180 hallucination-detection gate as backstop catches the worst case.
- **Why likelihood 3 (medium):** Yang's curated corpus represents one operator's voice + register conventions; the framework's first ~3-5 external operators are likely to surface per-register threshold mis-calibrations against their own corpora. The likelihood drops as Pillar I per-tenant baseline measurement extension lands + operators tune from their own corpus's per-register distribution.
- **Mitigation plan (Week 8+ design + Pillar I implementation):**
  - **The per-register threshold YAML is operator-tunable per ADR-0041 D199-D204.** Operators with materially different corpora copy `config-template/voice_thresholds.example.yml` to `~/.outreach-factory/voice_thresholds.yml` + tune per-register at their cadence.
  - **The `draft_quality_scored` event stream surfaces per-register score distributions.** Per ADR-0045 D231's emit-always posture, BOTH ready + refused drafts emit the score; operators consume the per-event stream via `python -m orchestrator.ledger grep --type draft_quality_scored | jq '...'` to compute per-register distributions.
  - **Pillar I per-tenant baseline measurement extension named in ADR-0045 §Downstream pillar impact.** Future extension `draft_quality fidelity-baseline --corpus-dir <path>` measures per-register score distributions against the operator's corpus + suggests per-register thresholds at operator-chosen percentiles (e.g., "set threshold at the 10th percentile of the per-register score distribution to accept 90% of corpus exemplars at the gate").
  - **The Pillar G observability dashboard (deferred to Pillar G commit) renders per-register score distributions.** Operators see the per-register histogram + per-register acceptance rate at a glance.
  - **The Week 6 hallucination-detection gate is the symmetric backstop per ADR-0045 §Downstream pillar impact.** A too-loose voice-fidelity threshold is bounded by the hallucination-detection gate's per-claim cross-reference check; the per-draft gate is the SYMMETRIC two-dimensional verdict (hallucination-detection × voice-fidelity), and a draft passing the voice-fidelity gate with low score still must pass the hallucination-detection gate.
- **Operator-side remediation:** Operators observing per-register mis-calibration can:
  - Query the per-register distribution: `python -m orchestrator.ledger grep --type draft_quality_scored | jq '.[] | select(.register == "<reg>") | .voice_fidelity_score'` + compute percentiles via `awk` or `numpy`.
  - Tune the per-register threshold per `~/.outreach-factory/voice_thresholds.yml` (e.g., lower cold-pitch from 0.70 → 0.55 for paraphrastic operators).
  - Inspect per-draft fidelity score via the CLI: `python orchestrator/draft_quality.py score --draft-path <path> --register R --channel C --json` (dry-run; no event emit) to see the score against the threshold before tuning.
  - Document the recurring per-register mis-calibration pattern for the Pillar I per-tenant baseline measurement extension's calibration corpus.

### R029 — Per-claim fuzzy-match false-positive (paraphrased non-citation chunk fuzzy-matches a claim above threshold)

- **Severity / Likelihood:** 3 / 2
- **Owner:** unassigned (Pillar F Week 9+ — threshold calibration via `fuzzy_threshold` per-call kwarg per ADR-0046 D239 + Pillar F Week 10+ corpus revision to surface fuzzy-match WIN cases + Pillar G observability dashboard rendering)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0046 D239's empirically-calibrated 0.85 threshold against the Week 7 corpus + ADR-0046 D240's attribution-claim exclusion (`quoted_text` + `you_phrase` SKIP fuzzy) + the operator-readable `dossier:fuzzy-match@chunk-N` diagnostic in the `citation_anchor` field + the Pillar F Week 12 binding 200-draft eval set's `<1%` FN bound per PILLAR-PLAN §2 Pillar F)
- **Description:** Pillar F Week 9 ships the per-claim fuzzy-match citation extension at the Layer 3 parser per ADR-0046. The fuzzy-match path activates UNCONDITIONALLY when the deterministic-first substring + markdown-link-key + footnote-ref returns `None` AND the claim is not in the attribution-claim exclusion list (`quoted_text` + `you_phrase` per D240). **Failure mode:** the fuzzy-match path may stamp `citation_anchor` from a dossier chunk that LOOKS semantically similar but does NOT actually support the claim (e.g., a dossier sentence about "Series B funding" fuzzy-matching a draft claim about "Series A funding"; the named-entity embedding similarity is high but the substantive claim is wrong). The threshold (0.85) bounds the FP_rate against semantically-unrelated chunks AND negation-prose chunks ("no X mention" cosine ~ 0.75-0.90 against "X").
- **Why severity 3 (medium):** The fuzzy-match FP path is operator-discoverable via the `citation_anchor` field's `dossier:fuzzy-match@chunk-N` diagnostic — operators inspecting the per-claim trace in the `hallucination_detected` event see the fuzzy origin explicitly + can decide whether to override the auto-citation. The asymmetric-failure-cost calculus: a fuzzy-cited claim that ISN'T actually supported by the dossier carries brand-risk IF the operator ships the draft without manual review. The Pillar F Week 12 binding 200-draft eval set's `<1%` FN bound is the structural commitment the threshold calibration must support.
- **Why likelihood 2 (low):** The Week 9 calibration at threshold 0.85 was EMPIRICALLY validated against the Week 7 corpus — all five claim types' per-claim-type rates IDENTICAL to the Week 7 baseline (no FP_rate regression). The fuzzy-match path's FP cases are bounded by (a) the chunk's nearby URL diagnostic surfacing the operator-readable anchor; (b) the attribution-claim exclusion preserving the YOU + quote semantics; (c) the deterministic-first dispatch ensuring fuzzy never runs when deterministic finds a real match.
- **Mitigation plan (Week 9+ design + Pillar G/I implementation):**
  - **The threshold calibration is operator-tunable per-call.** Operators (or test harnesses; advanced callers) pass `fuzzy_threshold=X` at `parse_draft_for_claims` / `score_draft` callsites to tune per-corpus characteristics. The framework default 0.85 is the calibrated point against the Week 7 corpus; operators with materially different corpora MAY tune.
  - **The `citation_anchor` field surfaces the fuzzy origin.** Operators inspecting `hallucination_detected` events see `dossier:fuzzy-match@chunk-N` (or the chunk's nearby URL) — the per-claim trace surfaces the fuzzy-match diagnostic explicitly. Operators can review fuzzy-cited claims separately from deterministic-cited claims.
  - **The Pillar G observability dashboard (deferred to Pillar G commit) renders per-claim-type FP rates over time.** Operators see the per-claim-type per-fuzzy-vs-deterministic rate split + can detect FP trend regressions.
  - **The Pillar F Week 12 binding exit criterion's 200-draft eval set is the structural backstop.** The `<1%` FN bound per PILLAR-PLAN §2 Pillar F is the load-bearing commitment the threshold calibration must support; if Week 9's fuzzy-match introduces measurable FN regressions, the binding exit-criterion test fails.
  - **Pillar F Week 10+ corpus revision (operator-deferred) surfaces fuzzy-match WIN cases.** Future Pillar F weeks extend the Week 7 corpus with paraphrased-ready pairs that exercise fuzzy match's WIN case (deterministic returns None → fuzzy correctly cites → operator-friction FP avoided). The Week 9 commit's bound table stays UNCHANGED; the Week 10+ extended corpus's bound table tightens.
- **Operator-side remediation:** Operators observing fuzzy-match false-positives can:
  - Inspect the `citation_anchor` field of the per-claim trace in `hallucination_detected` events: `python -m orchestrator.ledger grep --type hallucination_detected | jq '.[] | .claims[] | select(.citation_anchor | startswith("dossier:fuzzy-match"))'`.
  - Pass a higher `fuzzy_threshold` at library callsites: `parse_draft_for_claims(draft, dossier, register=..., fuzzy_threshold=0.92)`.
  - Disable fuzzy entirely at library callsites: `parse_draft_for_claims(draft, dossier, register=..., embed_fn=lambda _: numpy.zeros(384, dtype=numpy.float32))`.
  - Document recurring FP patterns for the Pillar F Week 10+ corpus revision.

### R030 — Layer 4 emit-guard bypass via direct payload construction

- **Severity / Likelihood:** 2 / 1
- **Owner:** unassigned (Pillar F Week 10+ — factory-as-sole-construction-surface discipline per ADR-0047 D245 + Pillar I per-tenant audit-tooling extension for `_emitted_by != "draft_quality"` `draft_ready` event detection)
- **Status:** SUPERSEDED (Pillar F removed; see the Pillar F removal ADR). Historical: Mitigated by design (ADR-0047 D245's factory IS the only sanctioned construction surface + ADR-0010 D17's `_emitted_by` audit marker + ADR-0047 D249's SKILL.md Phase 6 narrative + ADR-0038 D180's Week 12 Layer 5 reconcile Pass C as the final structural backstop)
- **Description:** Pillar F Week 10 ships the Layer 4 post-engine guard per ADR-0047 — the `build_draft_ready_payload` factory consumes BOTH `DraftQualityResult` AND `DraftFidelityResult` + refuses-loud (raises `Layer4GuardRefusal`) when EITHER state is `"refused"` AND the per-dimension override is absent. **Failure mode:** a future contributor (or operator script) that constructs the `draft_ready` event payload DIRECTLY (bypassing the factory) would emit a `draft_ready` event without consulting the per-Layer verdicts — operators downstream of the emit (Pillar G dashboards reading the per-event stream; Week 12 Layer 5 reconcile Pass C consuming the per-Person event sequence) would act on a stale-state draft. The asymmetric-failure-cost calculus: a `draft_ready` event that bypasses the Layer 4 gate ships a per-Person dispatch-eligibility signal without the SYMMETRIC two-dimensional verdict.
- **Why severity 2 (low-medium):** The bypass path requires a contributor with module-internal access (the factory IS the framework's only sanctioned construction surface; operator-facing CLIs all funnel through the factory). The per-event `_emitted_by: "draft_quality"` marker (per ADR-0010 D17 + ADR-0043 D216) is the audit substrate — Pillar I per-tenant audit-tooling can grep for `draft_ready` events with `_emitted_by != "draft_quality"` to surface non-factory emissions. The Week 12 Layer 5 reconcile Pass C is the structural backstop — a Layer 4 bypass that emitted a `draft_ready` WITHOUT a passing `draft_quality_scored` would surface at the Pass C heal as a `pipeline_stage: ready` advancement refusal.
- **Why likelihood 1 (very low):** The framework convention is per-event factory functions per ADR-0010 D17 + ADR-0039 D189; direct payload construction is the anti-pattern that the framework's exception-handling + the per-event-shape discipline rejects. The Week 10 SKILL.md Phase 6 narrative explicitly names the factory as the LOAD-BEARING surface (operators reading the skill see the factory invocation, not a direct payload construction).
- **Mitigation plan (Week 10+ design + Pillar I implementation):**
  - **The factory IS the only sanctioned construction surface per ADR-0047 D245.** The factory's per-call refuse-loud (closed-enum + result-mismatch + cross-dimension draft_hash consistency + per-dimension override semantics) is the structural commitment; downstream consumers read against the per-event `draft_ready` shape assuming the factory's invariants held.
  - **The `_emitted_by: "draft_quality"` marker is the audit substrate.** Pillar I per-tenant audit-tooling extends with a `draft_quality audit-events --check-factory-origin` command (operator-deferred) that surfaces `draft_ready` events where `_emitted_by != "draft_quality"` OR the per-Person event sequence lacks the matching upstream `draft_quality_scored` event.
  - **The SKILL.md Phase 6 narrative names the factory as the LOAD-BEARING surface per D249.** Operators reading the skill see the `python orchestrator/draft_quality.py emit-ready ...` CLI invocation; the CLI dispatches to the factory; operators do NOT see direct payload construction as a sanctioned path.
  - **The Week 12 Layer 5 reconcile Pass C is the final structural backstop.** Per ADR-0038 D180 Layer 5: the `pipeline_stage: ready` advancement in reconcile Pass C refuses when the linked `draft_quality_scored` event carries `uncited_claims` non-empty OR `meets_threshold=False`. A Layer 4 bypass that emitted a `draft_ready` without the matching per-Layer 2 verdicts surfaces at the Pass C heal.
- **Operator-side remediation:** Operators observing suspicious `draft_ready` events (e.g., events with `_emitted_by != "draft_quality"` OR per-Person event sequences with `draft_ready` but no upstream `draft_quality_scored`) can:
  - Grep the ledger for non-factory `draft_ready` events: `python -m orchestrator.ledger grep --type draft_ready | jq '.[] | select(._emitted_by != "draft_quality")'`.
  - Verify per-Person event sequence consistency: `python -m orchestrator.ledger query-by-person <person-id> | jq '.[] | select(.type == "draft_ready" or .type == "draft_quality_scored" or .type == "hallucination_detected")'` — expect EVERY `draft_ready` event to be preceded by a matching `draft_quality_scored` event (per ADR-0045 D231's emit-always posture for the per-Layer event class) AND optionally a matching `hallucination_detected` event (per ADR-0043 D219's emit-only-on-uncited posture).
  - Wait for the Pillar I per-tenant audit-tooling extension that automates this verification.
  - Wait for the Week 12 Layer 5 reconcile Pass C heal-pass refusal as the framework's structural backstop.

### R031 — Per-event-class observability primitive over-broadens the consumer surface

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar G Week 1+ — closed-set `EVENT_CLASS_CATALOG` discipline per ADR-0050 D272 + the per-call `observability_class_uncatalogued` emit per ADR-0050 D273 + Pillar G per-week-reviewer's checklist row 1 per ADR-0050 D274)
- **Status:** Mitigated by design (ADR-0050 D272's permissive-aggregate-with-explicit-enumeration + the closed-set frozenset at module level + the per-call refuse-loud `observability_class_uncatalogued` emit + per-pillar foundation ADR's "new event classes" table as the canonical source for catalog updates)
- **Description:** Pillar G Week 2+ ships the per-event-class observability primitive (`collect_event_class_snapshots`) at `orchestrator/observability.py` per ADR-0050 D272. The primitive walks every event class in the ledger + aggregates per `EVENT_CLASS_CATALOG`'s closed-set enumeration. **Failure mode:** a future contributor adding a NEW event class without coordinating with the catalog would either (a) silently fail to surface the new class (operator-visibility gap — dashboards miss the new class; SLO alerting misses the new class's triggers) OR (b) force the aggregator to crash on unknown class names (refuse-loud regression — the primitive's per-call walk fails). The asymmetric-failure-cost calculus: an unobserved event class is a Pillar G value gap (operators thought they had observability; they don't); a crashing primitive is a Pillar G operational gap (operators can't run their dashboards). The closed-set catalog IS the regression-barrier — the catalog enumerates the events the primitive expects + the per-call diagnostic emit surfaces unknown classes.
- **Why severity 2 (low-medium):** The bypass path requires a contributor adding an event class without updating the catalog OR a future pillar's foundation ADR's "new event classes" table NOT extending the catalog. The catalog's location is a single source of truth + the per-week-reviewer's checklist row 1 per ADR-0050 D274 explicitly audits catalog extensions. The asymmetric-failure-cost is bounded by the per-call `observability_class_uncatalogued` emit — operators see the diagnostic at the next CLI invocation; the recovery is a per-PR coordination fix (extend the catalog + commit).
- **Why likelihood 2 (low):** The framework convention is per-pillar foundation ADRs name new event classes in their "new event classes" table; the discipline has held across Pillars A-F for ~50 event classes; Pillar G inherits the discipline + adds the closed-set catalog as the structural commitment. The per-week-reviewer's checklist row 1 is the explicit verification step.
- **Mitigation plan (Pillar G Week 1+ design + Pillar I implementation):**
  - **The `EVENT_CLASS_CATALOG` closed-set IS the regression-barrier per ADR-0050 D272.** A future contributor adding a NEW event class without updating the catalog triggers the `observability_class_uncatalogued` emit (operator-visible signal).
  - **The per-call `observability_class_uncatalogued` event is rate-limited per ADR-0050 D273.** Per-call emit cap of ONE diagnostic event regardless of count (prevents ledger flooding when a contributor introduces a NEW class with many instances).
  - **The per-pillar foundation ADR's "new event classes" table is the canonical source.** Future Pillars H / I / J adding new event classes update the table + the `EVENT_CLASS_CATALOG` constant + the audit row 17 in the same commit.
  - **The Pillar G per-week-reviewer's checklist row 1 per ADR-0050 D274** explicitly audits "does the week's commit broaden `EVENT_CLASS_CATALOG`?" — the structural reviewer commitment.
- **Operator-side remediation:** Operators observing `observability_class_uncatalogued` events in their ledger can:
  - Grep the diagnostic events: `python -m orchestrator.ledger grep --type observability_class_uncatalogued | jq '.[] | .unknown_class'` — surfaces the class names the primitive encountered but did NOT aggregate.
  - File a PR extending `EVENT_CLASS_CATALOG` in `orchestrator/observability.py` + the per-pillar foundation ADR's "new event classes" table.
  - Pillar I OSS bring-up adds a per-tenant `EVENT_CLASS_CATALOG` extension surface for operators with custom integrations (e.g., a per-tenant CRM event class).

### R032 — SLO violation alerting false-positive on synthetic-data spike

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar G Week 7-8 — SLO violation detector at `orchestrator/observability/_slo_alerts.py` per ADR-0050 D273 + Pillar G per-week-reviewer's checklist row 5 per ADR-0050 D274)
- **Status:** Mitigated by design (ADR-0050 D276(d)'s per-alert window denominator excludes `_recovered_by` events + the per-alert deduplication discipline per ADR-0050 D274 category 9 + the operator-deliberate opt-in posture per ADR-0050 D276(d))
- **Description:** Pillar G Week 7-8 ships the SLO violation detector + the `slo_violation_detected` event class + the Slack webhook wiring per ADR-0050 D273. The four SLO triggers per PILLAR-PLAN §2 Pillar G: (a) p99 send latency > 5s; (b) reconcile success < 99%; (c) bounce > 5%; (d) any `manual_override` event (compliance review). **Failure mode:** a synthetic data spike (e.g., a one-time backfill from the migration framework per ADR-0010 D17 emitting a flood of `enrolled` events with `_recovered_by: "backfill"`; or a reconcile pass synthesizing events with `_recovered_by: "reconcile"`) MAY trip the bounce-rate or reconcile-rate alert without operator intent. The asymmetric-failure-cost calculus: a false-positive alert is operator-toilsome (operator investigates → realizes it was a backfill → no real action needed) but recoverable; a false-NEGATIVE alert (real SLO violation missed) is the failure mode the alerting exists to prevent — the synthetic-event exclusion biases against false-positives, NOT against false-negatives.
- **Why severity 2 (low-medium):** A false-positive alert wastes operator time + degrades trust in the alerting; repeated false-positives risk operators ignoring real alerts. The per-event `_recovered_by` field's structural existence (per ADR-0010 D17 + ADR-0013 D24) is the audit substrate — the SLO detector consults the field + excludes synthetic events by-design.
- **Why likelihood 2 (low):** The framework's synthetic-event sources are well-bounded: (a) the backfill script + the migration framework's per-migration events emit `_recovered_by` UNIFORMLY; (b) the reconcile passes emit `_recovered_by: "reconcile"` UNIFORMLY. The structural commitment is preserved across Pillars A-F; Pillar G inherits.
- **Mitigation plan (Pillar G Week 7-8 design + Pillar I implementation):**
  - **The SLO detector EXCLUDES `_recovered_by` events from SLO evaluation per ADR-0050 D276(d).** The per-alert window's denominator + numerator both exclude synthetic events — the bounce-rate alert's denominator is "real send_confirmed in window" not "all send_confirmed + synthetic backfills."
  - **The per-alert deduplication discipline per ADR-0050 D274 category 9** — ONE alert per SLO violation per window; no per-event flood.
  - **The operator-deliberate opt-in posture per ADR-0050 D276(d)** — alerting default OFF; operators wire the Slack webhook deliberately; surprise alerts on new operator setups don't fire.
  - **The per-week-reviewer's checklist row 5 per ADR-0050 D274** explicitly audits "does the week's commit add a NEW SLO threshold?" — the structural reviewer commitment.
- **Operator-side remediation:** Operators observing false-positive SLO alerts can:
  - Inspect the per-alert event: `python -m orchestrator.ledger grep --type slo_violation_detected | jq '.[] | {ts, slo_name, observed, threshold}'` — surfaces the per-window observed vs threshold values.
  - Verify the per-window denominator excludes `_recovered_by` events: `python -m orchestrator.ledger grep --type send_confirmed --since 24h | jq '. | select(._recovered_by | not)' | wc -l` — compares against the per-alert's expected denominator.
  - Disable the alert temporarily via `~/.outreach-factory/config.yml`'s `observability.slo_alert_webhook_url: null`.
  - Pillar I per-tenant audit-tooling extends with per-tenant SLO threshold overrides for operators with materially different traffic patterns.

### R033 — Observability primitive's cache-substrate divergence on multi-process operator

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar G Week 2 — stateless contract per ADR-0050 D272 + Pillar H multi-process scale analysis per ADR-0050 §Downstream pillar impact)
- **Status:** Mitigated by design (ADR-0050 D272's stateless-aggregation contract — no in-process cache; per-call ledger walk; cross-process aggregation via Prometheus pull contract; Pillar H scale revisit)
- **Description:** Pillar G's `collect_event_class_snapshots` primitive walks the ledger stateless per ADR-0050 D272. **Failure mode:** operators running the framework on multiple machines / daemons (e.g., Pillar H's daemon + a manual `python orchestrator/funnel.py` invocation + a Pillar G dashboard auto-refresh) all consume the same ledger but may compute aggregations at different windows; the per-process cache may diverge silently. The asymmetric-failure-cost calculus: divergent aggregations across processes confuse operators (one dashboard says X; another says Y); the recovery is to identify the canonical window + re-aggregate.
- **Why severity 2 (low-medium):** The divergence is operator-confusing but recoverable; the framework's per-process aggregations are deterministic against the SAME ledger state at the SAME window. The structural commitment is the stateless contract — no in-process cache + per-call walk.
- **Why likelihood 2 (low):** The framework today is single-process by convention (operators run skills + reconcile passes from a single Claude Code session); multi-process is Pillar H scope. The Pillar G primitive's stateless contract prevents per-process drift; the cross-process aggregation happens at the Prometheus layer via the OTel SDK's exporter (per ADR-0050 D273 + D276(d)).
- **Mitigation plan (Pillar G Week 2 design + Pillar H implementation):**
  - **Stateless aggregation per ADR-0050 D272 + the per-week-reviewer's checklist verification per Week 2.** No in-process cache; every call re-walks the ledger via `led.all_events()` + filters by `ts >= since` + groups by event class.
  - **Cross-process aggregation via Prometheus pull contract per ADR-0050 D273.** Prometheus handles cross-process aggregation downstream — the per-process exporter publishes metrics; Prometheus pulls + aggregates.
  - **Pillar H scale revisit per ADR-0050 §Downstream pillar impact.** Pillar H may add per-event-class indexing if the per-call O(N) ledger walk's cost surfaces as a bottleneck at multi-machine scale.
- **Operator-side remediation:** Operators observing divergent aggregations across processes can:
  - Identify the canonical window: pass the same `--now <ISO>` + `--since <window>` to every aggregation invocation.
  - Verify per-process determinism: `python orchestrator/funnel.py --since 1d --now 2026-05-25T12:00:00Z` from each process; output is byte-identical against the same ledger state.
  - Wait for Pillar H multi-process scale analysis + per-event-class indexing.

### R034 — Diagnostic emit at every primitive call inflates ledger when catalog drift persists

- **Severity / Likelihood:** 1 / 2
- **Owner:** unassigned (Pillar G Week 2 — per-kind-per-call rate-limit per ADR-0051 D279; Pillar I per-tenant audit-tooling filter per ADR-0051 §Downstream pillar impact)
- **Status:** Mitigated by design (ADR-0051 D279's at-most-ONE-per-kind-per-call rate-limit; Pillar I per-tenant audit-tooling filter on `_emitted_by: "observability"` for per-operator override-rate dashboards)
- **Description:** Pillar G Week 2's `collect_event_class_snapshots` primitive emits `observability_class_uncatalogued` diagnostic events when it encounters (a) an event of an uncatalogued class OR (b) an event with missing `ts`. **Failure mode:** when operators consume Pillar G dashboards continuously (e.g., Grafana auto-refresh hitting the primitive every minute via the OTel SDK at Pillar G Week 3+) AND the catalog is in drift (a new event class shipped without updating `EVENT_CLASS_CATALOG`), the primitive emits up to ~2880 diagnostics/day per single-tenant operator (two `kind` values × 1440 calls). The diagnostic events accumulate in the ledger until the operator fixes the catalog drift OR a Pillar J GDPR-purge sweep occurs. The asymmetric-failure-cost calculus: under-emit risks operator-invisible catalog drift (the R031 case the diagnostic ITSELF mitigates); over-emit inflates the ledger but does NOT impair operational correctness — operators see the diagnostic + fix the catalog drift.
- **Why severity 1 (low):** The per-kind-per-call rate-limit caps the worst case at ~2880 diagnostics/day; the ledger's existing daily rotation per `events-YYYY-MM-DD.jsonl` absorbs the load. The diagnostic events do NOT impair pipeline correctness (Pillar A-F event classes are unaffected). Pillar I per-tenant audit-tooling filters `_emitted_by: "observability"` out of per-operator dashboards so the diagnostic events don't pollute per-operator override-rate analytics. Operators can disable Pillar G dashboard auto-refresh OR fix the catalog drift to drop emission rate to zero.
- **Why likelihood 2 (low):** Catalog drift requires a contributor to ship a new event class without updating `EVENT_CLASS_CATALOG` — the per-week-reviewer's checklist catches this. The ts-missing case requires a producer-side bug — also caught by the per-week reviewer's behavioral-passthrough discipline.
- **Mitigation plan (Pillar G Week 2 + Pillar I):**
  - **At-most-ONE emission per `kind` per call** per ADR-0051 D279 — the per-call rate-limit caps the worst case at TWO diagnostic events per call (one per kind), regardless of how many offending events are present.
  - **`_emitted_by: "observability"` audit marker** per ADR-0051 D279 + ADR-0010 D17 — Pillar I per-tenant audit-tooling filters on this marker to exclude diagnostic events from per-operator override-rate dashboards.
  - **Per-week-reviewer's checklist catches catalog drift** — the cell-level matrix coverage discipline + the cross-pillar back-audit discipline (compounded across Pillar A-F + Pillar G Week 1's audit) catches new event classes shipped without `EVENT_CLASS_CATALOG` updates.
  - **Pillar J GDPR-purge transaction extends** to delete `observability_class_uncatalogued` events with the purged Person's id alongside the rest of the per-Person event set per ADR-0051 §Downstream pillar impact.
- **Operator-side remediation:** Operators observing high `observability_class_uncatalogued` emission rates can:
  - Investigate the producer via `_emitted_by` audit trail + `offending_type` field + `person_id` (if any).
  - Update `EVENT_CLASS_CATALOG` in `orchestrator/observability.py` to include the new event class (if the contributor's intent is to extend the catalog).
  - Disable Pillar G dashboard auto-refresh temporarily while investigating.
  - Wait for Pillar I per-tenant audit-tooling filter to exclude the diagnostic events from per-operator dashboards.

### R035 — OTel SDK's set-once `set_meter_provider` + `set_tracer_provider` enforcement creates per-process global state

- **Severity / Likelihood:** 1 / 2
- **Owner:** unassigned (Pillar G Week 3 — `set_global=False` kwarg + production single-init mitigation per ADR-0052 D282; EXTENDED at Pillar G Week 5 to `set_tracer_provider` per ADR-0054 D294; Pillar H may revisit at multi-machine scale)
- **Status:** Mitigated by design (ADR-0052 D282 + ADR-0054 D294's `set_global=False` kwarg for tests + production callers initialize ONCE at startup per the OTel spec)
- **Description:** The OTel Python SDK enforces "set-once" semantics on BOTH `metrics.set_meter_provider` AND `trace.set_tracer_provider` — subsequent calls log a warning and do NOT take effect (with the OTel-specific nuance for tracing — the default `NoOpTracerProvider` IS replaceable by a real provider; subsequent sets after a real provider is in place log a warning + do NOT take effect). **Failure mode:** operators running multiple framework invocations in the same Python process (e.g., a long-running daemon at Pillar H + a manual `python orchestrator/funnel.py` invocation in the same interpreter) see the FIRST init's MeterProvider / TracerProvider persist; subsequent inits silently no-op. If the FIRST init used the default Resource (`service.name="outreach-factory"`) + the SECOND init wanted per-tenant Resource attributes (`outreach_factory.tenant_id="tenant-a"`), the second init's Resource attributes are LOST silently — the OTel SDK ignores the call. Production callers initializing ONCE at startup avoid this; multi-init scenarios (notebooks, REPL exploration, framework-as-library use cases) hit this. The Week 5 extension to `set_tracer_provider` is STRUCTURALLY identical to the Week 3 `set_meter_provider` posture — same mitigation applies symmetrically to both surfaces.
- **Why severity 1 (low):** The first init's MeterProvider + TracerProvider is FUNCTIONAL; operators with single-init flows see no failure. The set-once warning is logged + operator-visible. The `set_global=False` kwarg on BOTH `init_otel_meter_provider` (Week 3) AND `init_otel_tracer_provider` (Week 5) gives tests an escape hatch — local providers per test, isolated from global state.
- **Why likelihood 2 (low):** Pillar G Week 3 + Week 5 ship the framework in a "single-init" production posture; multi-init scenarios are NOT the common case. The risk surfaces at Pillar H's multi-machine daemon + multi-process notebook + framework-as-library use cases.
- **Mitigation plan (Pillar G Week 3 + Week 5 + Pillar H):**
  - **`set_global=False` kwarg** per ADR-0052 D282 + ADR-0054 D294 — tests pass `set_global=False` on BOTH `init_otel_meter_provider` + `init_otel_tracer_provider` to bypass set-once; tests create local MeterProvider/TracerProvider + pass them explicitly through `get_meter(meter_provider=...)` + `get_tracer(tracer_provider=...)` + the instrument-registration `meter=` / helper `tracer=` kwargs.
  - **Production single-init at startup** — the framework's canonical production callsite invokes `init_otel_meter_provider()` + `init_otel_tracer_provider()` ONCE at process startup; subsequent operator calls in the same process are no-ops by design.
  - **Pillar H multi-machine scale** — per-daemon-process Provider isolation: each daemon process initializes its own MeterProvider + TracerProvider; cross-process aggregation via Prometheus pull (the Prometheus exporter at Week 4) handles the multi-process metric case at the export layer; per-daemon-process trace export via operator-wired SpanProcessor handles the multi-process trace case at the export layer.
- **Operator-side remediation:** Operators seeing the OTel "Overriding of current Provider" warning:
  - Refactor framework usage to initialize ONCE at process startup.
  - For multi-process scenarios (notebooks, REPL): restart the Python process between init attempts OR use `set_global=False` + pass MeterProvider/TracerProvider explicitly.
  - For Pillar H daemon scale: rely on per-daemon-process isolation + Prometheus pull / operator-wired SpanProcessor at the exporter layer.

### R036 — Prometheus HTTP exposition server exposes per-process metrics over the network

- **Severity / Likelihood:** 1 / 2
- **Owner:** unassigned (Pillar G Week 4 — `_DEFAULT_PROMETHEUS_ADDR = "127.0.0.1"` security-by-default + operator-deliberate posture per ADR-0053 D291; Pillar I per-tenant audit-tooling MAY add per-tenant auth wrapper at OSS bring-up)
- **Status:** Mitigated by design (ADR-0053 D291's 127.0.0.1 default bind + operator-deliberate posture; Pillar I per-tenant auth wrapper at OSS bring-up)
- **Description:** Pillar G Week 4's `start_prometheus_http_server(port=, addr=)` function exposes the framework's per-process Prometheus metrics on `http://<addr>:<port>/metrics`. **Failure mode:** an operator binding to `0.0.0.0` (all interfaces) on a public-facing host without firewall + authentication separately wired exposes the framework's per-event-class counts + per-channel send latencies + reconcile success ratio to the public internet. The framework's metrics carry operator-confidential information about pipeline volumes (per-Person enrolled / drafted / sent / replied counts) + per-channel rates (email vs LinkedIn vs Twitter dispatch patterns) + reconcile drift counts (per-Person Layer 5 backstop activity per ADR-0049 D262). A malicious observer scraping `:8000/metrics` could infer operator activity patterns, identify operator tenants from Resource labels, or correlate observable timing with externally-visible signals.
- **Why severity 1 (low):** The framework's default bind is `127.0.0.1` (localhost-only) — operators on a single-host deployment see metrics; external observers see connection-refused. The default port 8000 is the Prometheus convention. Operators deliberately exposing externally via `addr="0.0.0.0"` are taking explicit action.
- **Why likelihood 2 (low):** Operators following the framework's recommended wiring (single-process production deployment + Prometheus scraping localhost) never expose to the network. The risk surfaces only when operators (a) deploy on multi-host scale + (b) bind to all interfaces + (c) skip firewall + auth wiring. Pillar I per-tenant audit-tooling at OSS bring-up surfaces a per-tenant auth wrapper for multi-tenant deployments.
- **Mitigation plan (Pillar G Week 4 + Pillar I):**
  - **Default bind `127.0.0.1`** per ADR-0053 D291 — security-by-default; operators deliberately expose externally via `addr="0.0.0.0"` IF they wire firewall + authentication separately.
  - **Operator-deliberate posture** per ADR-0053 D291 — the framework does NOT auto-start the HTTP server at module import; operators explicitly invoke `start_prometheus_http_server()` at process startup.
  - **No metrics in URL path** — the framework relies on Prometheus's default `/metrics` endpoint; operator-confidential information stays within the metric values + labels (NOT in the URL).
  - **Pillar I per-tenant auth wrapper** — the per-tenant audit-tooling at OSS bring-up MAY wrap the Prometheus HTTP endpoint with a per-tenant authentication layer (e.g., basic auth, mTLS, or sidecar-based auth proxy). Pillar G Week 4 names the carry-forward for Pillar I.
  - **Operator documentation** — the `start_prometheus_http_server` docstring + the ADR-0053 D291 §Migration/rollout text explicitly call out the security-by-default + operator-responsibility-for-external-exposure posture.
- **Operator-side remediation:** Operators wanting to expose the Prometheus endpoint externally:
  - Wire firewall rules to restrict `:8000` to known Prometheus scrape sources (the operator's internal monitoring host).
  - Wire authentication (basic auth via reverse proxy; mTLS via Prometheus configuration; sidecar-based auth proxy).
  - Consider scraping localhost from a node_exporter-style agent + forwarding to the operator's central Prometheus instance.
  - Wait for Pillar I per-tenant auth wrapper (Pillar I OSS bring-up).

### R037 — Daemon process-restart silent state loss (in-flight per-stage tasks appear "lost" without reconcile recovery)

- **Severity / Likelihood:** 1 / 2
- **Owner:** unassigned (Pillar H Week 1 — atomicity-preservation-across-process-boundary invariant per ADR-0060 D335 invariant 2; reconcile loop is the structural recovery backstop)
- **Status:** Mitigated by design (ADR-0060 D335 invariant 2's atomicity-preservation contract + Pass A through O reconcile loop)
- **Description:** The Pillar H daemon (per ADR-0060) runs per-stage worker pools that may have in-flight tasks at process-restart time (config change / migration / OS patch / crash recovery). A `send_intent` event may be written but the corresponding `send_confirmed` event NOT yet emitted because the per-channel SDK (Gmail / LinkedIn / Twitter / Apollo / PDL / Reoon) is rate-limited or the network is hiccupping. **Failure mode:** without structural mitigation, the in-flight tasks could appear "lost" — operators querying the funnel CLI's `prospect_funnel` panel would see the prospect stuck at `sent` stage without a corresponding `*_confirmed` event; the per-Person dashboard would show drift; the operator might manually re-queue + cause duplicate sends. The Pillar H daemon's per-stage worker pool MUST preserve the ledger's atomicity contract per I2 across process boundaries.
- **Why severity 1 (low):** The mitigation by design — D335 invariant 2 — pins the structural commitment + the existing Pass A through O reconcile loop is the recovery backstop. Operators do NOT see state loss; the reconcile loop heals in-flight pairs on next start. The operator-visible drift surfaces via the per-channel `*_failed` / `*_aborted` count surface (per ADR-0059 D325's funnel CLI extension) — operators see the per-stage drift + can investigate the producer via the Pillar G dashboard.
- **Why likelihood 2 (low):** Process-restart is operator-deliberate (config change / OS patch) or operationally-rare (crash recovery once-per-month or less). The Pillar H daemon's graceful-shutdown invariant per D335 invariant 3 + the configurable `DaemonConfig.graceful_shutdown_seconds` (default 30s) gives in-flight tasks structural time to complete before forced exit.
- **Mitigation plan (Pillar H Week 1 + Pillar H Week 11):**
  - **Atomicity-preservation-across-process-boundary invariant** per ADR-0060 D335 invariant 2 — the daemon contributes NO new state that bypasses the ledger; every per-stage tick's structural change emits a ledger event.
  - **Pass A recovery for `send_intent` orphans** per ADR-0010 D17 + Pillar C convention — the X-Outreach-Intent-Id header (and body-footer marker) is the structural recovery primitive; Pass A walks Gmail Sent + matches by the header to recover orphaned `send_intent` events.
  - **Graceful-shutdown invariant** per ADR-0060 D335 invariant 3 — SIGTERM / SIGINT transitions to `"draining"` + completes in-flight tasks within `DaemonConfig.graceful_shutdown_seconds`; `daemon_stopping` + `daemon_stopped` ledger events emit for operator-visible diagnosis.
  - **Pillar H Week 11 hardening** per ADR-0060 D332's trajectory — the `kill -9` test substrate + reconcile loop integration + Pass A/B/C tightening land at Week 11; the binding exit-criterion test (Week 12) verifies the crash-recovery row.
  - **Operator-visible drift surfaces** via Pillar G's `prospect_funnel` panel (per ADR-0059 D325) + per-Pillar-H Grafana drill-down (Week 4 per ADR-0060 D332).
- **Operator-side remediation:** Operators observing in-flight per-stage drift after daemon restart:
  - Wait for the reconcile loop to run (default cadence: every 5 minutes per the existing Pillar C convention).
  - Check the per-channel `*_failed` / `*_aborted` count in the funnel CLI's `dispatch_health` panel.
  - Investigate via the Pillar G overview dashboard's per-stage span trace for the affected per-Person spans.
  - For prolonged drift (>15min): invoke `python orchestrator/reconcile.py` manually to force-run all passes.

### R038 — Health probe event-emission flood (high-frequency k8s readiness probes inflate ledger)

- **Severity / Likelihood:** 2 / 3
- **Owner:** unassigned (Pillar H Week 1 — `DaemonConfig.health_probe_rate_limit_seconds` default 30s + Prometheus exporter alternative per ADR-0060 D334 + D335)
- **Status:** Mitigated by design (ADR-0060 D334 + D335's `DaemonConfig.health_probe_rate_limit_seconds` at-most-ONE-per-30s rate limit + Prometheus exporter alternative for sustained-high-rate probe metrics)
- **Description:** Pillar H Week 1 ships the `health_probe` event class per ADR-0060 D331 — emitted on each health endpoint hit for operator-visible debugging. **Failure mode:** k8s readiness probes typically hit the endpoint every 10 seconds (configurable); without rate-limiting, the `health_probe` event would emit ~8640 events/day per single-tenant operator + bloat the daily `events-YYYY-MM-DD.jsonl` file + dominate the per-event-class observability_class_uncatalogued diagnostic rate per R034. Operators with multiple daemon replicas (Pillar I per-tenant scope) see N× the emission rate.
- **Why severity 2 (low-medium):** The ledger's append-only contract holds; the `health_probe` event class is valid + queryable; operators wanting per-probe granularity disable the rate-limit (set to 0). However, the ledger's daily rotation per `events-YYYY-MM-DD.jsonl` absorbs the load + the per-event-class catalog regression-barrier per R034 caps the per-call diagnostic rate. The structural risk is operator-visible-noise rather than data corruption.
- **Why likelihood 3 (medium):** k8s deployments are the production-target shape per the OSS bring-up trajectory at Pillar I; the default k8s readiness probe interval is 10s + the failure threshold is typically 3 (so probes hit every 10s sustained). Operators not configuring the rate-limit explicitly see the emission flood from day one.
- **Mitigation plan (Pillar H Week 1):**
  - **`DaemonConfig.health_probe_rate_limit_seconds` default 30s** per ADR-0060 D334 — at-most-ONE `health_probe` event per 30s window per single-tenant operator caps the rate at ~2880 events/day (3x reduction from unmitigated ~8640/day). The 30s default matches the typical k8s readinessProbe.failureThreshold * periodSeconds product (3 × 10s = 30s).
  - **Prometheus exporter alternative** per ADR-0053 D291 — operators wanting sustained-high-rate probe metrics use the Prometheus exposition surface (the `outreach_factory_health_probes_total` counter + the `outreach_factory_health_probe_outcome` label) without per-probe ledger append.
  - **`health_probe` event class as operator-debugging surface** — the event class IS the structural diagnostic for "did the daemon respond to probes?"; the rate-limit caps the high-volume case while preserving the operator-debugging value.
  - **Pillar I per-tenant rate-limit override** — multi-tenant deployments may override `health_probe_rate_limit_seconds` per tenant via the per-tenant audit-tooling at Pillar I; the default value's structural mitigation preserves the framework default.
- **Operator-side remediation:** Operators observing high `health_probe` emission rates:
  - Verify k8s readinessProbe.periodSeconds (default 10s; adjustable per the operator's k8s deployment manifest).
  - Increase `DaemonConfig.health_probe_rate_limit_seconds` (e.g., to 60s) to halve the per-probe ledger emission rate.
  - Disable the `health_probe` emission entirely (set rate-limit to a very large value, e.g., 86400 for daily-only) + rely on the Prometheus exporter for probe metrics.
  - Switch to TCP-based readiness probes (k8s tcpSocket probe) instead of HTTP probes if the operator does not need response-body inspection.

### R039 — Per-Person primitive O(N) ledger walk at v2 scale (per-cron-interval latency concern at ~100K events)

- **Severity / Likelihood:** 2 / 3
- **Owner:** unassigned (Pillar H Week 1 — per-event-class index trajectory per ADR-0060 D336; Pillar H Week 8-9 ships the body)
- **Status:** Mitigated by design (ADR-0060 D336's per-event-class indexing trajectory; Pillar H Week 8 ships index materialization at daemon startup + Week 9 ships invalidation on `Ledger.append`)
- **Description:** The Pillar G per-Person observability surface adapters per ADR-0058 D319-D324 walk `Ledger.all_events()` per call; the v1 scale (~5K events) cost is sub-second; the v2 scale (~100K events) cost at daemon's per-cron-interval (typically 1m) MAY surface as a per-cron-interval latency concern. **Failure mode:** at v2 scale, the per-Person dashboard's panel-render time would exceed the per-cron-interval cadence; operators with single-tenant ~100K-event ledgers see Grafana panels lagging behind real-time + the dashboard auto-refresh consumes CPU at the daemon process. The structural risk is operator-experience-degradation rather than data corruption; the ledger's append-only contract holds + the per-Person aggregation's output is structurally identical to the v1 scale output (just slower).
- **Why severity 2 (low-medium):** v1 scale operators do NOT see the latency concern; the per-event-class index per ADR-0060 D336 is structurally a no-op at v1 scale. The Pillar H Week 8-9 mitigation lands within the per-pillar-week trajectory; the structural risk is contained to v2 scale operators between Pillar H Week 1 commit + Pillar H Week 8-9 commit.
- **Why likelihood 3 (medium):** Operators reach v2 scale ~100K events at ~6 months of v1 production usage (single-tenant ~500 active prospects × ~5 outreach touches × ~30 reconcile passes/day × 6 months ≈ 100K events). The Pillar I OSS bring-up trajectory targets multi-tenant ~10× per-tenant scale; the latency concern surfaces at the Pillar I level for multi-tenant operators.
- **Mitigation plan (Pillar H Week 1 + Pillar H Week 8-9 + Pillar I):**
  - **Per-event-class index trajectory** per ADR-0060 D336 — Pillar H Week 8-9 ships the per-event-class index materialization at daemon startup; the index is denormalized from the ledger (rebuildable per I3) + invalidated on `Ledger.append`. Per-Person primitives at `observability.collect_per_person_*` consume the `PersonEventIndex` directly at Week 8 (lookup by `person_id` is O(1); the per-Person primitive's per-call cost drops from O(N) to O(M) where M = events for that Person, typically tens).
  - **Daemon-process-local + transparent to funnel CLI** per ADR-0060 D336 — the per-event-class index is per-process (daemon process owns the index); the funnel CLI's READ-ONLY contract per ADR-0059 D325 is preserved (operators invoking `python orchestrator/funnel.py` outside the daemon continue to walk the ledger directly).
  - **Operator-visible index-age** via the `daemon_started` event payload + the per-pillar-H Grafana panel (Week 3 per ADR-0060 D332) — operators see the index's rebuild-age + the cumulative-event-count.
  - **Pillar I per-tenant indexing** — multi-tenant deployments may extend the index with per-tenant labels; the per-tenant audit-tooling at Pillar I handles per-tenant isolation.
- **Operator-side remediation:** Operators observing per-Person dashboard latency at v2 scale:
  - Wait for the Pillar H Week 8-9 per-event-class index materialization commit.
  - Reduce dashboard auto-refresh cadence (Grafana panel refresh interval) to >per-cron-interval to avoid overlapping panel renders.
  - Restrict the per-Person dashboard's PromQL query to the operator's active Person cohort (filter by `person_id` regex matching only active prospects).
  - Wait for Pillar I per-tenant indexing if operating at multi-tenant scale.

### R040 — Per-tenant ledger directory contention at multi-process write (single-machine multi-tenant operators at v2 scale)

- **Severity / Likelihood:** 2 / 2
- **Owner:** unassigned (Pillar I Week 1 — per-tenant directory isolation per ADR-0070 D371 + ADR-0070 D375 invariant (a) per-tenant-isolation; Pillar I Week 5 ships CI contention regression-barrier per ADR-0074)
- **Status:** Mitigated by design (ADR-0070 D371's per-tenant ledger directory isolation at separate filesystem subtrees + Pillar I Week 5 CI surface contention regression-barrier per ADR-0074)
- **Description:** Operators running many small tenants on the same machine MAY surface ledger directory contention at the OS-filesystem level (per-tenant directories share a parent directory + per-OS inotify limits + per-OS file-descriptor limits). **Failure mode:** at v2 scale (~100 tenants per machine), per-tenant Docker containers each open per-tenant ledger directories + the cumulative inotify watches + file-descriptor consumption + filesystem write contention MAY exceed per-OS resource limits; operators see per-tenant daemon startup failures (`OSError: too many open files`) or ledger append latency spikes when many tenants append concurrently. The structural risk is operator-experience-degradation at v2 scale rather than data corruption (the per-tenant ledger directory isolation per ADR-0070 D371 prevents cross-tenant data leakage; the append-only contract per I2 holds per-tenant).
- **Why severity 2 (low-medium):** v1 scale operators at ~10 tenants per machine see no contention; per-tenant directories are well within per-OS resource limits. The Pillar I Week 5 CI surface contention regression-barrier IS the v2-scale early-warning surface. The structural risk is contained to v2-scale single-machine multi-tenant operators between Pillar I Week 1 commit + Pillar I Week 5 commit (Pillar I Week 5 CI surface adds the regression-barrier; v2-scale operators get the OS-level limit early-warning).
- **Why likelihood 2 (low):** v1 OSS bring-up trajectory operators provision per-tenant Docker containers via docker-compose at single-machine ~10 tenants; multi-machine fan-out (one machine per tenant via cloud deploy templates per ADR-0070 D372) is the operator-preferred v2-scale shape. The contention concern surfaces ONLY at single-machine multi-tenant operators running ~100 tenants — a niche operator profile.
- **Mitigation plan (Pillar I Week 1 + Pillar I Week 5):**
  - **Per-tenant ledger directory isolation** per ADR-0070 D371 — each tenant's ledger directory lives at `<base_ledger_dir>/<tenant_id>/` (separate filesystem subtree); per-tenant Docker containers each mount their own per-tenant directory as a Docker volume; cross-tenant write contention is structurally minimized.
  - **Pillar I Week 5 CI surface contention regression-barrier** per ADR-0074 — the CI surface includes a per-tenant contention regression-barrier exercising ~10-100 per-tenant directories + asserting per-tenant ledger append latency stays within operator-tunable bounds.
  - **Cross-machine fan-out via cloud deploy templates** per ADR-0070 D372 — operators wanting many tenants run one machine per tenant via Fly.io / Railway / Render cloud deploy templates; the per-machine resource limits scale linearly.
  - **Pillar J trajectory note for per-tenant storage tier optimization** — v2+ operators MAY consume per-tenant cloud storage tiers (S3 / GCS) for ledger archival; out of scope for Pillar I.
- **Operator-side remediation:** Operators observing per-tenant ledger directory contention at v2 scale (single-machine multi-tenant):
  - Migrate to cross-machine fan-out via cloud deploy templates per ADR-0070 D372.
  - Tune per-OS file-descriptor limits via `ulimit -n` + per-OS inotify limits via `sysctl fs.inotify.max_user_watches`.
  - Wait for Pillar J's per-tenant storage tier optimization (v2+ scope).

### R041 — Docker container daemon-restart cycle inflates startup latency (cumulative startup time at v2 scale)

- **Severity / Likelihood:** 2 / 3
- **Owner:** unassigned (Pillar I Week 1 — Docker healthcheck + restart-policy at compose manifest per ADR-0070 D372 + ADR-0072; Pillar I Week 5 ships CI startup-latency regression-barrier per ADR-0074)
- **Status:** Mitigated by design (ADR-0070 D372's Docker healthcheck + restart-policy at compose manifest + ADR-0072's per-tenant container orchestration body + Pillar I Week 5 CI surface startup-latency regression-barrier per ADR-0074)
- **Description:** Per-tenant Docker containers MAY restart on operator-deliberate config changes (`docker-compose down && docker-compose up`); each per-tenant restart pays the Pillar H Week 8 per-event-class index materialization startup cost (~1-2s at v1 scale ~5K events; ~10s at v2 scale ~100K events per tenant). **Failure mode:** operators iterating per-tenant config see the restart cycle frequently; cumulative startup time at v2 scale MAY exceed 60s for ~10 tenants (10 × 6s ≈ 60s); operators perceive the per-tenant fan-out as "slow to start" + the per-tenant Grafana dashboard's `daemon_started` event lag confuses operator-visibility. The structural risk is operator-experience-degradation rather than data corruption.
- **Why severity 2 (low-medium):** v1 scale operators see sub-second per-tenant startup (`~1-2s` per tenant × ~10 tenants × ~10s total under v1 scale); operator-experience-degradation is bounded. The Pillar H Week 8 per-event-class index materialization startup cost IS the structural cost; the Pillar I Week 5 CI surface startup-latency regression-barrier surfaces v2-scale early-warning.
- **Why likelihood 3 (medium):** Operators iterating per-tenant config during the Pillar I OSS bring-up trajectory frequently restart per-tenant containers (init wizard + per-tenant OAuth provisioning + per-tenant policy YAML iteration are all restart-triggering operator actions); the restart cycle is observable across the Pillar I Week 4 init wizard + Week 5 CI bring-up trajectories.
- **Mitigation plan (Pillar I Week 1 + Pillar I Week 3 + Pillar I Week 5):**
  - **Docker healthcheck + restart-policy at compose manifest** per ADR-0070 D372 — Pillar I Week 3 ships the operator-tunable healthcheck interval + restart policy at `docker-compose.yml`; operators tune per-tenant restart cadence + healthcheck interval per per-tenant SLA.
  - **Per-tenant `daemon_started` event surfaces startup time** per Pillar H Week 2's emit factory per ADR-0061 D339 — operators see per-tenant startup_seconds in the per-tenant Grafana dashboard's lifecycle panel; per-tenant SLO threshold tuning informs operator-visibility.
  - **Pillar I Week 5 CI surface startup-latency regression-barrier** per ADR-0074 — the CI surface includes a startup-latency regression-barrier exercising ~10 per-tenant containers + asserting cumulative startup time stays within operator-tunable bounds.
- **Operator-side remediation:** Operators observing per-tenant Docker container daemon-restart cycle inflation:
  - Tune `docker-compose.yml` healthcheck interval to operator-tunable cadence per per-tenant SLA.
  - Use `docker-compose restart <tenant_a>` (per-tenant restart) instead of `docker-compose down && docker-compose up` (all-tenant restart).
  - Stagger per-tenant container start times via per-tenant Docker container `depends_on` chain to amortize the cumulative startup cost.
  - Monitor per-tenant Grafana dashboard's `daemon_started.startup_seconds` panel for per-tenant startup-time drift.

### R042 — Init wizard OAuth-flow failure modes operator-confusing (per-channel OAuth flows surface distinct error modes)

- **Severity / Likelihood:** 2 / 3
- **Owner:** unassigned (Pillar I Week 1 — per-step refuse-loud + operator-readable error messages per ADR-0070 D374 + ADR-0001 D2; Pillar I Week 4 ships init wizard body per ADR-0073)
- **Status:** Mitigated by design (ADR-0070 D374's per-step refuse-loud + operator-readable error messages + ADR-0073's init wizard body shipping per-step refuse-loud at every OAuth surface)
- **Description:** The Pillar I init wizard (Pillar I Week 4 per ADR-0073) walks operators through Gmail OAuth → LinkedIn OAuth → Twitter OAuth → Google Calendar OAuth → first prospect → first send; each OAuth surface has distinct failure modes (token revocation; scope mismatch; provider rate-limit; network failure; expired refresh token; insufficient OAuth scope per `TENANT_OAUTH_TOKEN_SCOPES` closed-set; missing OAuth client credentials). **Failure mode:** without per-step refuse-loud + operator-readable error messages, operators MAY hit a failure mode + not know which step to retry; the init wizard's idempotence per ADR-0070 D375 invariant (c) preserves the structural commitment (re-runs are NO-OPs at successful steps), but operators perceive the init wizard as "broken" if a single OAuth step fails without operator-readable diagnostic. The structural risk is operator-experience-degradation + operator-abandonment at the OSS bring-up entry point rather than data corruption.
- **Why severity 2 (low-medium):** first-time operators are by-definition unfamiliar; OAuth flows are the most error-prone surface in the framework (per the existing Phase 5.5 Gmail OAuth flow's operator-confusing failure modes). The Pillar I Week 4 init wizard body's per-step refuse-loud + operator-readable error messages structurally mitigate via per-step error message convention per ADR-0001 D2 + the Pillar H W10-11 follow-up P1-1 closure's discipline (operator-readable error message; NO Python traceback at operator-facing surfaces).
- **Why likelihood 3 (medium):** OAuth flows touch external systems (Gmail / LinkedIn / Twitter / Google Calendar) with per-provider error idiosyncrasies; per-provider rate-limits + per-provider scope-mismatch handling + per-provider token-expiry handling all surface failure modes at the init wizard surface. The init wizard's per-step refuse-loud at every OAuth surface is the structural mitigation.
- **Mitigation plan (Pillar I Week 1 + Pillar I Week 4):**
  - **Per-step refuse-loud + operator-readable error messages** per ADR-0070 D374 + ADR-0001 D2 — every init wizard step refuses-loud on failure with an operator-readable error message naming the specific failure mode (token revocation / scope mismatch / provider rate-limit / network failure) + the operator-actionable next step.
  - **Init wizard idempotence** per ADR-0070 D375 invariant (c) — running the init wizard twice on the same user produces a NO-OP at successful steps; operators can retry failed steps without re-running successful steps; the `init_wizard_completed` event class signals first-run completion + carries the list of completed step names per `wizard_steps` payload field.
  - **Per-step `auth_token_refreshed` event class** per ADR-0070 D371 — each per-channel OAuth token refresh emits a `auth_token_refreshed(tenant_id, token_scope, refreshed_at_ts)` ledger event; operators query the per-tenant ledger for per-channel OAuth flow status.
  - **NO Python traceback at operator-facing surfaces** per the Pillar H W10-11 follow-up P1-1 closure's discipline — exceptions wrap to operator-readable messages at the init wizard surface boundary; operators do NOT see raw Python stack traces.
- **Operator-side remediation:** Operators encountering init wizard OAuth-flow failure modes:
  - Read the per-step operator-readable error message at the init wizard surface (per ADR-0070 D374).
  - Query the per-tenant ledger for the most recent `auth_token_refreshed` event per channel.
  - Re-run the init wizard at the failed step (per ADR-0070 D375 invariant (c) idempotence preserves successful steps).
  - Verify per-channel OAuth client credentials at the per-channel provider console (Gmail / LinkedIn / Twitter / Google Calendar developer consoles).
  - Verify per-channel OAuth scope provisioning matches `TENANT_OAUTH_TOKEN_SCOPES` closed-set per ADR-0070 D371.

### R043 — Crypto-shred master-key loss = catastrophic data loss
- **Severity / Likelihood:** 1 / 2
- **Owner:** Pillar J (ADR-0076 D379/D380/D387; J5/J6)
- **Status:** Open (FENCED build)
- **Description:** The J6 GDPR-forget design (ADR-0076 D380) erases a person by destroying their data-encryption key. If the J5 master key (ADR-0076 D379) is lost — corrupted keyring, forgotten passphrase, lost backup — ALL ciphertext PII in the append-only ledger becomes unrecoverable, not just forgotten persons. The append-only ledger's irreplaceability (PILLAR-PLAN §5 backup strategy) makes this catastrophic.
- **Mitigation plan:**
  - Two-level key hierarchy: a master KEK (key-encryption key) wraps per-person DEKs; `forget` destroys ONLY the per-person DEK, never the KEK; routine operation never touches the KEK destructively.
  - KEK backup discipline documented in the J5 build (ADR-0080) + the `doctor.py` preflight reports KEK presence + reachability before any send.
  - Per-person DEK destruction is the only irreversible operation; it is gated behind the `forget` lock + an operator confirmation at the CLI.

### R044 — Passphrase-fallback weak passphrase → brute-forceable at-rest credentials
- **Severity / Likelihood:** 2 / 2
- **Owner:** Pillar J (ADR-0076 D379/D387; J5)
- **Status:** Open (FENCED build)
- **Description:** The `passphrase_argon2id` keystore backend (mandatory for the Pillar I Docker container, which has no OS keyring) is only as strong as the operator's passphrase. A weak passphrase makes the at-rest encryption brute-forceable, defeating J5.
- **Mitigation plan:**
  - Argon2id with tuned cost parameters (memory + time) documented in the J5 build.
  - Minimum-entropy refuse-loud at keystore init (ADR-0001 D2 convention) — reject a passphrase below an entropy floor.
  - Prefer the OS keyring (no passphrase) wherever one exists; the passphrase backend is the container/CI fallback only.

### R045 — CAN-SPAM footer/header omitted on a non-default send path
- **Severity / Likelihood:** 2 / 2
- **Owner:** Pillar J (ADR-0076 D381/D385; J7)
- **Status:** Open
- **Description:** A future email send path (a reply, a re-engagement touch, a new channel adapter) could bypass the J7 CAN-SPAM footer + `List-Unsubscribe` header, shipping a non-compliant email. A missed footer is a CAN-SPAM violation (asymmetric-failure-cost per PILLAR-PLAN §0).
- **Mitigation plan:**
  - The every-send invariant (ADR-0076 D385.3) — every email send path stamps `CANSPAM_REQUIRED_HEADERS` + the footer; kill-switch semantics like suppression.
  - A regression-barrier test asserting every email send path carries the footer + headers; a send with an empty `SecurityConfig.physical_mailing_address` refuses-loud.

### R046 — Audit-log export leaks PII
- **Severity / Likelihood:** 2 / 2
- **Owner:** Pillar J (ADR-0076 D382/D385; J8)
- **Status:** Open
- **Description:** The J8 compliance audit-log export could include cleartext per-Person PII, turning a compliance artifact into a privacy leak.
- **Mitigation plan:**
  - Redact-by-default (ADR-0076 D382) — PII redacted unless an operator-deliberate flag opts in for an internal review.
  - The privacy invariant (ADR-0076 D385.6) + a regression-barrier test asserting the default (redacted) export carries no forbidden per-Person field.

## Closed risks

(None yet. Append below with closing date and resolving artifact link.)
