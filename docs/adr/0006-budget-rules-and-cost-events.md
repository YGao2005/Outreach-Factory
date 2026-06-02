# ADR-0006: Budget rules + `cost_incurred` event

- **Status:** Accepted
- **Date:** 2026-05-18
- **Pillar:** A (Policy engine — fourth concrete rule batch) + cross-cutting hook into Pillar G (observability)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0001 established the policy engine; ADR-0002 shipped four cooldown rule classes; ADR-0003 added the cross-channel rule; ADR-0004 added three suppression rule classes; ADR-0005 added two sending-window rule classes plus the timezone-inference module. Pillar A Week 4 ships the **budget** rule class — the fourth concrete rule batch — locking in the I7 invariant ("cost is a first-class concern") that ADR-0001 §Compliance carved out a seat for but did not implement.

Three concerns this ADR resolves:

1. **The seat ADR-0001 reserved has been empty since Week 1.** ADR-0001 §Compliance I7 reads: "Budget rules (Week 2 task) consume `cost_incurred` events from the ledger; this ADR establishes the seat for them." The seat exists but no event type and no consumer have been wired. Week 4 fills both halves in one commit — the rule class without its events would have a never-firing path (the anti-pattern ADR-0003 §Alternative 1 explicitly rejected for the cross-channel rule).

2. **`cost_incurred` shape.** PILLAR-PLAN §1 I7 names the required fields ("USD-equivalent and the per-prospect attribution"); ADR-0006 locks the concrete event schema and the per-source pricing-table contract. The pricing table is the SoT for USD/unit conversion at every emit site.

3. **The `manual_override` contract.** PILLAR-PLAN §2 Pillar A line 53 promises "`manual_override` event with explicit user sign-off; no flag bypasses the audit trail," but no ADR has locked its shape. Budget rules are the first operational location where override is needed (a legitimate "spend $501 today on Apollo" decision must not require a code deploy). This ADR locks the override event schema and the consumption contract; cooldown / suppression / sending-window rules may opt into the same mechanism in later ADRs.

The asymmetric-failure-cost principle (PILLAR-PLAN §0) applies to budget the way it does to cooldown: the rule must err toward refusal under ambiguity. A pricing-table miss (we don't know what a vendor costs) emits `amount_usd: 0.0` for the corresponding event — that biases toward "spent more than reported," which is the safer side because the operator's `max_usd` threshold tuning is what protects them; under-reporting forces them to tune tighter, over-reporting would block their legitimate spend. The reverse bias — overestimating cost — would silently throttle the pipeline. This is the same tradeoff that drives the lower-end-inclusive convention on the window math.

Risks this ADR mitigates by design: I7 (cost is first-class); the "dispatcher in a bad loop" failure mode named in I7.

## Decision

### Three concrete rule classes

| YAML discriminator | Class | Role |
|---|---|---|
| `budget.window-cap` | `BudgetWindowCapRule` | Block when the sum of `cost_incurred` events in the configured window exceeds `max_usd` (or `max_units` for quota-only sources). Factory pattern: "daily Apollo $50 cap." |
| `budget.per-person-cap` | `BudgetPerPersonCapRule` | Block when the sum of `cost_incurred` events attributed to `ctx.person_id` exceeds `max_usd`. Factory pattern: "$1.00 per-prospect Apollo cap." |
| `budget.per-run-cap` | `BudgetPerRunCapRule` | Block when the sum of `cost_incurred` events with the in-flight `ctx.run_id` exceeds `max_usd`. Guards the "dispatcher in a bad loop" failure mode. |

All three live in `orchestrator/policy/budget.py` and register themselves into `RULE_REGISTRY` at import time (the standard pattern set by ADR-0002).

### `cost_incurred` event schema

```json
{
  "v": 1,
  "ts": "<ISO 8601 UTC>",
  "type": "cost_incurred",
  "source": "<vendor name>",
  "amount_usd": <float>,
  "units": <int>,
  "model_or_endpoint": "<free-form diagnostic>",
  "person_id": "<id>",
  "run_id": "<run-…>",
  "intent_id": "<snd_…>"
}
```

* **`source`** — exact vendor identifier (`"anthropic" | "apollo" | "pdl" | "reoon" | "gmail" | "linkedin"`). Lowercased; new vendors require a new entry in `COST_RATES_USD` (see §Pricing table). Source filtering on rules is exact-match on this string.
* **`amount_usd`** — USD cost of this one event. `0.0` for quota-only sources (Gmail, LinkedIn — see §Pricing table). USD-priced sources compute this from `COST_RATES_USD` at emit time.
* **`units`** — per-source natural unit count. Tokens for Anthropic, credits for Apollo / PDL, sends for Gmail, invites for LinkedIn, verify-checks for Reoon. The `BudgetWindowCapRule.max_units` mode sums this field for quota-only sources where USD has no meaning.
* **`model_or_endpoint`** — free-form string for diagnostic context. E.g. `"claude-opus-4-7:input"`, `"messages.send"`, `"verifier/power"`. Not consumed by any rule; surfaced in the funnel CLI for "what cost what" analytics (Pillar G).
* **`person_id`** *(optional)* — present when the cost is per-prospect attributable (most enrichment + every send). Absent for run-level overhead (e.g. OAuth probe at the start of a batch). `BudgetPerPersonCapRule` excludes events with no `person_id` from its sum.
* **`run_id`** *(optional)* — the dispatcher batch identifier. Present whenever the emit site has it. `BudgetPerRunCapRule` consumes this field; the other budget rules ignore it.
* **`intent_id`** *(optional)* — for Gmail-send cost events, correlates back to the originating `send_intent`. Lets future analytics passes join cost back to its send without re-running the rule path. Not consumed by any current rule.

The event coexists with the existing event-type catalog in `orchestrator/ledger.py` — no Event-dataclass change required (the wrapper passes arbitrary `**fields` through unchanged). The catalog docstring gains an entry under a new "Cost" header.

### Per-emit-site emission contract

Every external API call's **success** path emits one `cost_incurred` event before returning to the caller. Failed calls do **not** emit — the per-vendor pricing assumption is that the operator is not billed for HTTP-error responses, validated per vendor:

| Vendor | Billable on failure? | Reference |
|---|---|---|
| Anthropic | No | anthropic.com docs §pricing; 4xx/5xx not metered |
| Apollo | No | apollo.io/help; credits returned on 4xx/5xx |
| PDL | No | peopledatalabs.com/pricing; only "match found" credits charged |
| Reoon | No | emailverifier.reoon.com/pricing; only "verified" calls counted |
| Gmail | N/A (quota) | The quota counter does NOT advance on 4xx/5xx |
| LinkedIn | N/A (quota) | Invite quota does NOT advance on rejected invites |

If a vendor changes to billing on failure, this ADR is amended and the emit-site code at that vendor's call site changes simultaneously. The `try: ... except: re-raise (no event)` pattern is the binding shape.

### Pricing table contract

`COST_RATES_USD` in `orchestrator/policy/budget.py` is the source of truth for per-source USD/unit conversion. Hardcoded into source code — not loaded from a data file — so the budget rule evaluate path is deterministic and cannot crash on missing data. (See §Alternative 3 for the rejected alternative.)

Schema:

```python
COST_RATES_USD = {
    "anthropic": {
        "claude-opus-4-7:input_per_mtok": 15.0,
        "claude-opus-4-7:output_per_mtok": 75.0,
        # ... per-model + per-input/output keys
    },
    "apollo": {"credit": 0.05},
    "pdl": {"credit": 0.10},
    "reoon": {"verify": 0.005},
    "gmail": {"send": 0.0},        # quota-only
    "linkedin": {"invite": 0.0},   # quota-only
}
```

Freshness contract: price updates are code changes accompanied by an amendment to this ADR's pricing-table-as-of-date row. The discipline: **a vendor price change is a new ADR amendment + commit**, not a silent edit. Operators with custom pricing should fork the constant or open an issue with their negotiated rate.

The pricing-table-as-of date is recorded in the module docstring of `budget.py` and in §Pricing table snapshot below.

### `manual_override` event schema + consumption contract

```json
{
  "v": 1,
  "ts": "<ISO 8601 UTC>",
  "type": "manual_override",
  "rule": "<rule name to override>",
  "expires_ts": "<ISO 8601 UTC>",
  "scope": {
    "person_id": "<id>",
    "run_id": "<run-…>"
  },
  "reason": "<human-readable justification>",
  "approved_by": "<user identifier>"
}
```

* **`rule`** *(required)* — the `name` field of the rule to override. Must match exactly. Wildcarding is deliberately not supported (see §Alternative 7).
* **`expires_ts`** *(required)* — ISO 8601 UTC. The override is honored only while `ctx.now < expires_ts`. At the exact expiry instant the override is treated as expired and the cap is back in force (the safer-side choice — mirrors the asymmetric-failure-cost principle even though the convention is opposite to the cooldown lower-end-inclusive default). Forces "I'll allow this for the next 6 hours, after which the cap is back in force" rather than "permanently bypass this rule."
* **`scope`** *(optional)* — fields the override applies to. Currently supports `person_id` and `run_id`. An override with no `scope` (or a `scope` whose values are `None` / absent) applies to every send the rule would otherwise gate. **A scope field set to explicit `null` is treated as "no constraint on this field," NOT as "matches only ctx.<field> == None."** Operators serializing the absence-of-constraint as JSON `null` (the natural gesture) get the expected behavior; the alternative reading would let a `scope: {run_id: null}` override silently apply only to non-batched sends — the opposite of what the operator intends.
* **`reason`** *(required by convention, not by code)* — human audit trail. Surfaced in the funnel CLI's override-summary view.
* **`approved_by`** *(audit trail)* — user identifier. Required by operational convention (CI / pre-commit hook will fail if missing once Pillar J ships); not currently validated by the budget rule code.

**Consumption is per-rule, not at the engine layer.** Each budget rule's `evaluate` calls `_is_overridden(self.name, ctx) -> bool` after computing the would-be-Block but before returning it. If an unexpired matching override exists, the rule returns `Allow`. The defense-in-depth choice: any rule forgetting to call `_is_overridden` continues to enforce — the override is an opt-in by the rule class, not a default the engine swallows. Cooldown / suppression / sending-window rules do **not** currently consult overrides; a future ADR may extend the contract. The helper's return type is plain `bool` (not `(bool, dict)`) — the override's full payload is observable via the ledger's existing audit path; carrying it through the rule's Allow path would couple every Block branch to an unused audit-trail responsibility.

### `run_id` on `RuleContext`

The `RuleContext` dataclass gains a `run_id: str | None = None` field. Additive change with a `None` default — every existing test context construction site continues to work without modification. The send-gate caller in `skills/send-outreach/scripts/send_queued.py:main` already generates a `run_id` (line 672 pre-Week-4); Week 4 threads it through `gated_send_one` → `_build_rule_context` → `RuleContext`. Standalone callers (e.g. a manual one-off send invoked outside the dispatcher) leave it `None`, and `BudgetPerRunCapRule` correctly returns `Allow` on that input.

### LedgerLike Protocol shape

The `LedgerLike` Protocol is **unchanged**. Budget rules walk `ctx.ledger.all_events()` and filter by `type == "cost_incurred"` plus source / person_id / run_id / window — the same pattern `cooldown.DomainThrottleRule` uses for `send_confirmed` filtering. Timestamp comparison parses each event's `ts` to a UTC `datetime` rather than lex-comparing strings: `Ledger._now_iso` formats with millisecond precision (`...HH:MM:SS.MMMZ`) while a naively-serialized cutoff datetime has none (`...HH:MM:SS+00:00`), and string-lex would silently exclude events in the same second as the cutoff because `.` (0x2E) < both `Z` and `+`. Parsed-datetime compare is what `DomainThrottleRule` does too. No new method is added because:

1. Adding a method to the Protocol would force every test fake (`_FakeLedger` across cooldown / cross-channel / suppression / sending-window tests) to grow a stub, even though most of them don't care about cost queries.
2. The `all_events()` walk is bounded by the daily-rotated JSONL file's size; mtime-based caching in `Ledger._build_indexes` already amortizes the parse cost.
3. If/when budget rule evaluation becomes a hot-path bottleneck — likely only after Pillar H's daemon mode ships and the dispatch rate climbs — a per-event-type index can land as an internal `Ledger` optimization without touching the Protocol surface. (Same precedent the cooldown ADR-0002 established for the `DomainThrottleRule` walk.)

This is documented as a deliberate-deferral rather than a missed optimization. The funnel CLI's own `funnel()` function walks `all_events` similarly; the patterns are consistent.

### `block_when:` support

Budget rules accept `block_when:` per the cooldown / cross-channel / sending-window precedent (ADR-0002 / ADR-0003 / ADR-0005). The rationale that **drove** suppression's no-`block_when:` stance (ADR-0004 §Alternative 8 — kill switches refuse scope) does NOT apply to budget: budget is tunable policy. An operator may legitimately want different caps per register (cold-pitch sends from a $100/day budget, follow-up sends from a $25/day budget) or per channel (email caps from one bucket, LinkedIn from another). The `block_when:` filter expresses this without code changes.

Documentation in `cooldowns.example.yml` explicitly notes the scoping support to head off "should I `block_when:` here?" confusion when operators copy cooldown patterns into their budget rules.

### Where budget rules fire

Pillar A Week 4 wires budget rules **only at the send gate**. Pre-API-call gating (refusing an Apollo enrich because the daily cap was already hit before the enrich would have happened) is a separate surface that requires every enrich-time skill to consult the policy engine before making the API call.

The send-gate placement is sufficient for the I7 "runaway dispatcher cannot spend $500 of Apollo without override" requirement: even if the enrich code lacks pre-call gating, the dispatcher will refuse subsequent sends as soon as the budget rule fires at the next gate evaluation. Pre-API-call gating is a quality-of-life improvement (saves a few Apollo credits between the cap-hit and the next gate eval), not a correctness requirement.

This decision is recorded explicitly because a future contributor will reach for "why isn't the budget rule preventing the Apollo enrich itself?" The answer is: by design, deferred to Pillar G observability + Pillar H daemon; a Pillar A budget rule is a send-gate guard, not a pre-API-call guard. The seat for the daemon-side pre-call gating is the same `policy.evaluate` surface — no engine changes will be needed there either.

### Pillar A Week 4 emit sites (initial wiring)

Only two paid Python-side API calls exist in the current codebase. Both gain `cost_incurred` emission in this commit:

| Emit site | Vendor | Pricing | `person_id` populated? | `run_id` populated? |
|---|---|---|---|---|
| `skills/send-outreach/scripts/send_queued.py:gated_send_one` (after `send_confirmed`) | Gmail | quota-only (units=1, amount_usd=0.0) | yes (the gate already has it) | yes (threaded from `main`) |
| `orchestrator/enrich_emails.py:process_one` (after successful Reoon verify) | Reoon | `COST_RATES_USD["reoon"]["verify"]` * 1 | yes (filename stem) | yes (a new `enrich-<id>` run id minted in `main`) |

Anthropic / Apollo / PDL / LinkedIn API calls happen via Claude Code skills (MCP-mediated) that run outside this Python codebase. Their emit sites are out of scope for Pillar A Week 4 and will land as Pillar G (observability) wires cross-process cost capture. The pricing table entries for those vendors ship in this commit so the future Pillar G wiring has a stable target.

## Alternatives considered

### Alternative 1: Emit `cost_incurred` on every API attempt (success + failure)

Track every API call regardless of outcome. **Rejected because:** per-vendor pricing confirms we don't pay for failures (see the failure-billing table in §Per-emit-site emission contract). Counting failures would inflate the running sum, causing premature budget blocks (false-positive refusals). The cooldown principle applies: count what actually consumed the resource, not what was attempted.

### Alternative 2: Per-source rule classes (`budget.apollo-cap`, `budget.anthropic-cap`, …)

One class per vendor. **Rejected because:** same anti-pattern ADR-0002 §Alternative 2 rejected for cooldown ("one class per dimension > one class per concrete-named instance"). Three classes scoping on `source:` cover every vendor we ship + every vendor we'll add — the cost is paid in one discriminator entry, not one source-file per vendor. New vendors require a `COST_RATES_USD` entry and a YAML rule, not a code class.

### Alternative 3: Hardcode the pricing table OR load from a data file

Two opposed paths considered:

* **Hardcode (chosen)** — invariant-immutable source code; cannot crash on missing data; price updates are version-controlled diffs. The asymmetric-failure-cost principle compels it: a missing/corrupt data file would silently produce $0 sums and never block.
* **Data file (`config-template/cost-rates.example.yml` loaded at startup)** — operator-customizable without forking. **Rejected** for the asymmetric-failure-cost reason above; also, the per-source pricing rarely changes (quarterly at most), and operator customization is a feature wanted by ~0 OSS users in the next year. Yang specifically asked the question; the answer is hardcode with the discipline that "price update == new ADR amendment."

### Alternative 4: Refuse `block_when:` on budget rules (mirror suppression's kill-switch posture)

Force every budget rule to apply to every send unconditionally. **Rejected because:** budget is tunable policy, not a kill switch. The suppression rationale (a do-not-contact entry firing on every channel/register is operationally correct) does not apply here — an operator legitimately wants per-register / per-channel caps, and shipping without `block_when:` would force them to write separate rule lists per scope (or wait for cap-rule composition primitives that aren't worth building). The cooldown / sending-window precedent applies.

### Alternative 5: Defer budget rules until Pillar G (observability) so they can use a real cost dashboard

Pillar G ships OTel + Prometheus + Grafana cost dashboards. Budget rules might want to consume those instead of raw `cost_incurred` events. **Rejected because:** the ledger IS the SoT for cost (per the SOURCES-OF-TRUTH.md "Cost ledger" row — populated by this ADR). Pillar G's dashboards will be denormalized views of the ledger. Building budget rules against the ledger first means the dashboard derivation comes later without disrupting the rule code. The reverse ordering (rules consume dashboards) would couple Pillar A to Pillar G's exact dashboard schema, blocking both pillars on a single timeline.

### Alternative 6: `BudgetPerRunCapRule` requires `ctx.run_id` and raises if missing

Force every send through a run-id-bearing dispatcher. **Rejected because:** the manual-send / one-off-test path exists (Yang regularly runs a single send for QA) and that path has no batch identifier. Raising would convert a legitimate non-batched send into a `policy_engine_error` (per ADR-0001 the engine doesn't swallow exceptions). The chosen `None → Allow` semantics document the rule as "scope is a run when one exists; otherwise no-op." Operators who want a no-run-can-bypass cap should use `BudgetWindowCapRule` with a very short window (e.g. 5 minutes).

### Alternative 7: Wildcard / glob support in `manual_override.rule`

An override like `rule: "budget.*"` would bypass every budget rule. **Rejected because:** the asymmetric-failure-cost principle compels narrow overrides. A wildcarded override is one keystroke away from disabling every cap (the operator types `*` when they meant `budget.daily-apollo-cap`). The per-rule exact match forces the operator to write the name they're overriding, which is also the name in the audit trail.

A future enhancement could add a `rules: [list, of, names]` field for "override these N specific rules at once" workflows, but the multi-rule override case isn't urgent and the wildcard form is what gets explicitly rejected here.

### Alternative 8: Override at the engine layer, not per-rule

The engine could consult overrides before dispatching to any rule, returning `Allow` for any rule a matching override covers. **Rejected because:** any rule forgetting to opt in still gets the override applied — a footgun for rules where override is operationally inappropriate (suppression should NEVER honor an "override the do-not-contact entry" override; that's a CAN-SPAM violation). The per-rule consultation model lets each rule class decide whether override is even semantically valid; budget opts in here, suppression deliberately stays out. A future ADR can revisit if a clean "engine knows which rules are override-eligible" pattern emerges.

### Alternative 9: Defer per-API-call gating to Pillar G/H

Already covered in §Where budget rules fire. Accepted as the chosen plan: Week 4 wires send-gate budget rules only; pre-API-call gating is a Pillar G/H surface that will reuse the same `policy.evaluate` mechanism.

### Alternative 10: Extend `LedgerLike` Protocol with `query_by_event_type` / `sum_cost` methods

Add a typed query method to make budget evaluation O(1) lookup instead of O(events) walk. **Rejected because:** the walk pattern is the established precedent (`DomainThrottleRule`), test-fake compatibility matters (eight fake ledgers would need updates), and the performance gain only becomes meaningful at high event volumes that the OSS user base will not hit for years. A future ADR can revisit if Pillar H's daemon hits the wall. Documented in §LedgerLike Protocol shape.

## Consequences

### Positive

- I7 invariant has a concrete enforcement mechanism. A runaway dispatcher cannot spend $500 of Apollo without an explicit `manual_override` + audit trail.
- The `manual_override` contract is locked. Cooldown / suppression / sending-window rules may opt in via future ADRs without revisiting the event schema.
- The pricing table is a single, version-controlled SoT; price changes are diff-reviewable.
- `BudgetPerPersonCapRule` prevents the per-prospect runaway-enrichment failure mode (Apollo+PDL loops re-enriching one prospect indefinitely).
- `BudgetPerRunCapRule` provides a hard ceiling against the "dispatcher in a bad loop" mode I7 names.
- Three classes cover every cost-cap pattern the OSS deployment will need for the foreseeable future. New patterns are YAML edits, not code changes.
- `run_id` on `RuleContext` is a forward-compatible field other Pillar A rule classes (or future per-run cooldowns) may consume.
- Cooldown's DST property test + sending-window's tz-dependence property test both continue to hold (verified by the regression sentinels in `test_policy_budget.py`).

### Negative

- The pricing table is hardcoded. An operator whose Apollo plan has different per-credit pricing must fork. **Mitigation:** documented in the module docstring + this ADR; a future Pillar I (multi-tenant) enhancement can layer per-tenant pricing overrides on top.
- Failed API calls are not recorded as cost events, so the funnel CLI's per-source breakdown only counts successful calls. **Mitigation:** the existing `*_failed` event types (`send_failed`, future `enrich_failed`) carry the diagnostic; cost is a separate concern from "did the call succeed."
- The `intent_id` field on `cost_incurred` events is informational only — no current rule consumes it. **Mitigation:** future analytics passes (Pillar G dashboards) will use it to join cost back to its send.
- `manual_override` consultation runs inside each rule's evaluate, costing one extra `all_events()` walk per gate evaluation. **Mitigation:** the walk is amortized by mtime-cached index in the real `Ledger`; the override-events filter is fast. A future Protocol extension could surface "active overrides" as a constant-time query if profiling shows it matters.
- Pre-API-call gating is not wired this commit. **Mitigation:** documented; the rule path itself is reusable when those gates ship in Pillar G/H.

### Neutral / observability

- Budget blocks emit the standard `policy_blocked` event (per ADR-0001) with `detail` carrying: `mode` (`usd` / `units`), `source`, `total_usd` / `total_units`, `max_usd` / `max_units`, `window_seconds`, `event_count_in_window` (for window-cap); `person_id` (for per-person-cap); `run_id` (for per-run-cap). The funnel CLI surfaces budget refusals as distinct rule categories without new code.
- `cost_incurred` events are queryable via `python orchestrator/ledger.py tail --type cost_incurred` for ad-hoc cost auditing.
- Adding `cost_incurred` to the ledger event-type catalog updates the docstring; `Ledger.healthcheck` continues to count cost events alongside everything else.
- The SoT registry's "Cost ledger" row (added before Week 4 as a placeholder) now has a populated consumer + producer; the row's notes are updated.

## Compliance with invariants

- **I1 (single source of truth):** The ledger is the SoT for cost. `COST_RATES_USD` is the SoT for per-source unit prices (a separate concern from the per-event ledger record). The "Cost ledger" row in `docs/SOURCES-OF-TRUTH.md` is updated to reflect the producer/consumer wiring.
- **I2 (two-phase commit):** Budget rules consume only ledger events — no writes, no external side effects. The `cost_incurred` emission itself is a single-event append, not a two-phase action: the cost is already incurred when we attempt to record it (the failure mode is "we paid for it but didn't log it," not "we logged a cost we didn't pay for"). The emit-site `try / except` swallows ledger-append failures with a stderr warning; the audit miss is biased toward under-reporting, consistent with the asymmetric-failure-cost principle.
- **I3 (schema versioning):** `cost_incurred` and `manual_override` events carry `v: 1`. Schema changes go through `orchestrator/migrations/ledger/` (Pillar B). The `COST_RATES_USD` table is invariant source code; its updates are versioned via git + this ADR's amendment record (no schema migration needed because no on-disk state changes).
- **I5 (observable by default):** Every Block emits `policy_blocked` with the rule-specific detail dict. Every `cost_incurred` event is queryable via the funnel CLI. `manual_override` events are surfaced as a distinct event-type breakdown.
- **I6 (tests prove invariants):** `tests/test_policy_budget.py` covers each rule class's allow/block branches, threshold + window boundary semantics, source-filter scoping, override consultation, and the empty-history invariant. The `TestCostIncurredAggregation` Hypothesis property proves verdict-commutativity-under-event-ordering. The `TestCooldownDSTPropertyStillHolds` + `TestSendingWindowTzDependenceStillHolds` sentinels prove Week 4 didn't break ADR-0002 / ADR-0005 contracts. `tests/test_cost_incurred_event.py` covers ledger-level round-trip + backward compatibility. `tests/test_enrichment_costs.py` covers the Reoon emit-site contract. `tests/test_send_gate.py::TestCostIncurredEmissionGmail` covers the Gmail emit-site contract end-to-end.
- **I7 (cost is first-class):** This ADR delivers I7's enforcement seat. Every cost-incurring path emits `cost_incurred`; budget rules block on the per-prospect / per-run / per-window aggregates. The dispatcher cannot spend $500 of Apollo without an explicit `manual_override`.
- **I8 (decisions documented):** This ADR. ADR-0002 / ADR-0003 / ADR-0004 / ADR-0005 References sections are updated to point forward to ADR-0006. `docs/adr/README.md` gains the ADR-0006 row.

Does not weaken any invariant. The pricing-table-as-SoT for USD/unit conversion is a new SoT entry (cost-rate metadata) noted in the SoT registry; the "Cost ledger" row is enriched with producer/consumer details.

## Migration / rollout

Greenfield: `orchestrator/policy/budget.py` is a new file; `cost_incurred` and `manual_override` are new event types (the existing `Event` dataclass accepts arbitrary fields, so no migration needed for the event-shape change); `RuleContext.run_id` is an additive optional field (default `None`).

The factory `cooldowns.example.yml` is extended with three commented-out budget rules. Operators opt in by uncommenting; until they do, the rules are not in the active rule list and never fire. The asymmetric-failure-cost principle (default-off for a new rule shape whose threshold is operator-specific) compels this — Yang's $50/day Apollo cap is not the right number for every operator.

`docs/PILLAR-PLAN.md` §2 Pillar A's package list is updated in the same commit: `budget.py` is removed from the outstanding-modules list. `tier.py` and `simulation.py` remain outstanding (Weeks 5, 6 — unchanged from prior commits).

Doctor preflight already validates `cooldowns.yml` structure at install time; once the example file gains budget rules (commented-out), preflight covers their structural validity automatically when an operator uncomments.

The `intent_id` correlation field on Gmail-emitted cost events does NOT trigger any migration — existing events ignore the field (they don't have it). The field is opt-in at the emit site.

Existing `RuleContext(...)` callers continue to work unchanged because `run_id` defaults to `None`. The send-gate caller in `send_queued.py:gated_send_one` is updated to thread `run_id` through; tests that construct contexts directly leave it unset.

## Pricing table snapshot

Last reviewed: **2026-05-18** (this ADR's date).

| Source | Key | USD/unit | Reference |
|---|---|---|---|
| anthropic | `claude-opus-4-7:input_per_mtok` | $15.00 / 1M tokens | docs.anthropic.com/pricing |
| anthropic | `claude-opus-4-7:output_per_mtok` | $75.00 / 1M tokens | docs.anthropic.com/pricing |
| anthropic | `claude-sonnet-4-6:input_per_mtok` | $3.00 / 1M tokens | docs.anthropic.com/pricing |
| anthropic | `claude-sonnet-4-6:output_per_mtok` | $15.00 / 1M tokens | docs.anthropic.com/pricing |
| anthropic | `claude-haiku-4-5:input_per_mtok` | $0.80 / 1M tokens | docs.anthropic.com/pricing |
| anthropic | `claude-haiku-4-5:output_per_mtok` | $4.00 / 1M tokens | docs.anthropic.com/pricing |
| apollo | `credit` | $0.05 | apollo.io/pricing (Basic tier) |
| pdl | `credit` | $0.10 | peopledatalabs.com/pricing (pay-as-you-go) |
| reoon | `verify` | $0.005 | emailverifier.reoon.com/pricing (power mode) |
| gmail | `send` | $0.0 (quota-only) | Google Workspace / Gmail API quotas |
| linkedin | `invite` | $0.0 (quota-only) | LinkedIn personal account invite cap |
| linkedin | `dm` | $0.0 (quota-only) | LinkedIn DM rate-limit |

A vendor price change between today and the next ADR amendment is a **bug** in this table. Operators noticing a discrepancy should open an issue with the dated vendor pricing screenshot; a follow-up ADR amendment + commit updates the constant.

### CI enforcement of the price-update == ADR-amendment discipline (Week 6 §D3 deferral)

The Week 4 follow-up review (commit `09abdf9`) named W2 — "the price-update == ADR-amendment discipline is words-only, not CI-enforced; a future commit that touches `COST_RATES_USD` could silently land without an ADR-0006 amendment." Week 6 §D3 of the Pillar A exit-gate handoff revisited W2 and asked: ship the CI hook now or defer?

**Deferred** to Pillar I (multi-tenant + OSS hardening, Weeks 43-48). Rationale:

* The repo has no CI surface today — no `.github/workflows/`, no pre-commit configuration, no `.git/hooks/` beyond Git's default samples. Introducing a 20-LOC bash hook in Week 6 would be the *first* CI artifact in the repo, which means there's no convention to follow (do we use GitHub Actions? a pre-commit framework? a Husky-style local hook? a Makefile target?). That decision belongs in Pillar I where the OSS-hardening week range owns the CI bring-up.
* The discipline is honored today by convention: every `COST_RATES_USD` edit in the git log has been accompanied by an ADR-0006 amendment (verified at Week 6). The discipline has not been violated in the absence of CI enforcement; the cost-of-deferral is low.
* Pillar I's "init wizard" and "Docker compose for one-command-up" deliverables (PILLAR-PLAN §2 Pillar I) imply a CI surface for the OSS release; the price-table check is one rule in whatever CI configuration Pillar I lands.

**When Pillar I ships:** add a check (likely `.github/workflows/policy-discipline.yml` or equivalent) that fails the commit if `git diff --cached orchestrator/policy/budget.py` contains a change to the `COST_RATES_USD` block and `docs/adr/0006-budget-rules-and-cost-events.md` is not also in the same commit. ~20 LOC. The check generalizes to the same shape for any future "constant + ADR" pair (e.g. ADR-0008 + the `LINKEDIN_WEEKLY_INVITE_LIMIT` constant if it ever moves from cosmetic display to load-bearing).

**Until Pillar I:** code reviewers (and `claude-code-guide` style automated reviewers in PR reviews) are the enforcement surface. The discipline is documented in this ADR's §Pricing table contract and in the module docstring of `budget.py`; the documentation is visible to every contributor whose diff touches the pricing table.

## References

- ADR-0001 (policy engine architecture) — engine surface; §Compliance I7 reserved the seat this ADR fills.
- ADR-0002 (cooldown rules + recipient timezone) — same-shape factory rule pattern this ADR mirrors. The `block_when:` semantics are reused; the `_block_when_matches` and `_parse_iso_utc` helpers from `_helpers.py` are shared.
- ADR-0003 (channel as first-class policy predicate) — cross-channel rule precedent; the "rule + event type in the same commit" discipline this ADR also follows.
- ADR-0004 (suppression rules + GDPR forget) — the deliberate non-`block_when:` stance there contrasts with this ADR's deliberate-yes (§Alternative 4). The override-vs-kill-switch distinction here is the load-bearing reason for the difference.
- ADR-0005 (sending-window rules + recipient timezone inference) — most recent ADR; the factory-rule-module structure (factory class + helper module + ADR + tests + example YAML + cross-link updates) is the template this ADR matches.
- `docs/PILLAR-PLAN.md` §1 I7 (cost is first-class) — the binding invariant. §2 Pillar A Week 4 — the package-list update.
- `docs/RISK-REGISTER.md` — risks this ADR mitigates: "runaway API spend" (the I7-derived risk).
- `docs/SOURCES-OF-TRUTH.md` — the "Cost ledger" row's notes are updated to reflect this ADR's producer/consumer wiring.
- `orchestrator/policy/budget.py` — the three rule classes + the `COST_RATES_USD` table + the `_is_overridden` helper + the `_sum_cost_events` aggregator.
- `orchestrator/policy/types.py` — `RuleContext.run_id` field added.
- `orchestrator/ledger.py` — event-type catalog docstring updated; `Event` class unchanged (accepts arbitrary `**fields`).
- `skills/send-outreach/scripts/send_queued.py:gated_send_one` — Gmail cost emit site; `run_id` propagation through `_build_rule_context`.
- `orchestrator/enrich_emails.py:emit_reoon_cost_event` — Reoon cost emit helper; the `process_one` caller emits at the API-success path.
- `tests/test_policy_budget.py` — rule-class tests + commutativity property + DST regression sentinels.
- `tests/test_cost_incurred_event.py` — ledger-level event round-trip + backward-compat.
- `tests/test_enrichment_costs.py` — Reoon emit-site contract.
- `tests/test_send_gate.py::TestCostIncurredEmissionGmail` — Gmail emit-site contract end-to-end.
- ADR-0007 (tier rules + cross-cutting `block_when: {tier|tier_in}` + simulation surface) — accepted 2026-05-19. Adds a tier-scoping shape that composes with budget rules (`block_when: {tier: S}` on a budget cap is the canonical "premium-prospect Apollo budget" pattern). The override CLI shipped in ADR-0007 §Operator tooling writes the same `manual_override` schema this ADR locked.
- Followups: ADR-NNNN (Pillar G observability) will land the cost dashboard + cross-process cost capture for the MCP-mediated skills. The override mechanism here is the seat for any future override-aware rule class; cooldown / suppression / sending-window may opt in via a future ADR.
