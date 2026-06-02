# ADR-0003: Channel is a first-class policy predicate

- **Status:** Accepted
- **Date:** 2026-05-16
- **Pillar:** A (Policy engine)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0001 §Decision item 1 added `channel: str` to `RuleContext`. ADR-0002 used it as a **filter predicate** — `block_when: {channel: email}` scopes a rule to fire only when `ctx.channel == "email"`. The four factory cooldown rules in `orchestrator/policy/cooldown.py` and `config-template/cooldowns.example.yml` all use this same-channel pattern: a rule fires on channel X and queries events on channel X.

Pillar C of `docs/PILLAR-PLAN.md` (§2, Weeks 7–18) lists "channel-aware policy: cross-channel cooldown ('don't email AND DM in same 14d')" as a Pillar C deliverable. That schedule defers not just the LinkedIn integration but the cross-channel rule **shape** itself to Pillar C — which is the architectural mistake this ADR corrects.

**The problem.** A rule that fires on channel A and queries events on channel B is qualitatively different from one that fires on channel A and queries events on channel A. The first requires:

1. A rule type whose query scope is decoupled from its fire scope, and
2. A v1 default ruleset that exercises that decoupling so future contributors don't accidentally re-introduce a same-channel assumption.

If Pillar A v1 ships with same-channel rules only and the LinkedIn-side wiring lands in Pillar C, the natural path of least resistance is to *also* land the cross-channel rule class in Pillar C. By then the engine, YAML schema, helper functions in `cooldown.py`, and every factory rule have been written under a same-channel assumption, and the cross-channel rule arrives as a special case that doesn't compose cleanly. This is the textbook refactor-twice failure mode.

**Adjacent context.** Phase 5.5's identity model unifies a single Person.id with multiple `identity_keys` (LinkedIn URL + email + GitHub), so the ledger can already record touches across channels for the same identity. The ledger primitive is ready; the policy engine needs to keep up. The outreach factory is on the verge of adopting LinkedIn as a default channel alongside email (strategy discussion 2026-05-16) — the cross-channel double-touch failure mode is no longer hypothetical, it is imminent. Risk R011 in `docs/RISK-REGISTER.md` formalizes the failure mode.

## Decision

**Channel is a first-class predicate in two distinct senses, both supported by Pillar A v1:**

1. **Channel-as-filter (already shipped, ADR-0002):** `block_when: {channel: X}` scopes a rule to fire only when `ctx.channel == X`. Unchanged.

2. **Channel-as-join (new):** A rule may declare separately *which channel's events* it queries against the ledger, independent of which channel it fires on. The YAML shape is:

   ```yaml
   - name: cross-channel-email-suppresses-linkedin
     type: cooldown.cross-channel-touch
     block_when:
       channel: linkedin            # fire when ctx.channel == "linkedin"
     consider_channels: [email]     # block based on email events
     window_days: 14
     reason: "Prior email touch within 14d; LinkedIn would look coordinated"
   ```

**New rule class `CrossChannelTouchRule`** lands in Pillar A v1 in a new module `orchestrator/policy/cross_channel.py`. Discriminator: `cooldown.cross-channel-touch`. The rule consumes the existing `LedgerLike` Protocol (no new methods) — it calls `ctx.ledger.query_by_person(ctx.person_id)`, filters for events that (a) satisfy the **confirmed-send predicate** and (b) carry a `channel` field that is in the rule's `consider_channels` list, and applies the `window_days` threshold against `ctx.now` using the same UTC age math as ADR-0002 cooldown rules.

**Event-type predicate (load-bearing).** "Confirmed send" is recognized by `type.endswith("_confirmed")` — wider than just `type == "send_confirmed"` so that Pillar C's `li_invite_confirmed` and `li_dm_confirmed` types match automatically without a code change the day Pillar C ships. The safety check is the channel filter: an event whose `channel` is not in `consider_channels` is skipped regardless of type, so the suffix predicate cannot accidentally match an unrelated future event whose name happens to end `_confirmed`. (Verified against `orchestrator/ledger.py:EVENT_TYPES` as of this commit: the only `_confirmed`-suffixed type today is `send_confirmed`; `send_confirmed_orphan` ends `_orphan` and is correctly excluded.) Reviewers extending `EVENT_TYPES` with a new `*_confirmed` type that should NOT participate in cross-channel coordination must either (a) name it without the suffix, or (b) not give it a `channel` field — both keep this rule's predicate sound.

**Boundary semantics (window_days threshold).** Cutoff = `ctx.now - timedelta(days=window_days)`. An event whose `ts` is **strictly older** than the cutoff is outside the window. The boundary instant itself (`ev_ts == cutoff`) is **inside** the window — i.e. inclusive on the lower end. This matches `DomainThrottleRule`'s convention (`ev_ts < window_cutoff: continue` in `cooldown.py`) and the natural reading of "within N days" (a touch exactly 14 days ago is still recent). The CC-06 / CC-06b rows below pin this contract; the parallel boundary tests on `DomainThrottleRule` (`tests/test_policy_cooldown.py::TestDomainThrottleRule::test_at_exact_boundary_blocks`) pin the same convention on the sibling rule.

**Two factory rules ship in `config-template/cooldowns.example.yml`** in the same commit that adds the rule class:

| Name | Fires on | Considers | Window | Reason |
|---|---|---|---|---|
| `cross-channel-email-suppresses-linkedin` | `linkedin` | `[email]` | 14d | Recent email touch; LinkedIn would look coordinated |
| `cross-channel-linkedin-suppresses-email` | `email` | `[linkedin]` | 14d | Recent LinkedIn touch; email would look coordinated |

These ship even though the LinkedIn `li_invite_confirmed` / `li_dm_confirmed` event types don't land until Pillar C. With no LinkedIn events in the ledger, the rules return `Allow()` — same idempotent shape as a fresh `cooldowns.yml` returning `Allow()` for the empty-rules case. When Pillar C wires the LinkedIn event types, the rules begin firing without any change to the rule class, the policy engine, or the YAML schema.

**Pillar C's scope shrinks accordingly.** Pillar C delivers (i) the LinkedIn event types (`li_invite_intent` / `li_invite_confirmed` / `li_dm_intent` / `li_dm_confirmed`), (ii) the two-phase commit wiring for those events, (iii) reconcile Pass D (ledger ↔ LinkedIn sent-invites). The cross-channel rule class is **not** a Pillar C deliverable — it ships in Pillar A v1 as part of the engine surface. `docs/PILLAR-PLAN.md` §2 Pillar A and §2 Pillar C are updated in the same commit as this ADR.

**Cross-channel test cases are mandatory rows in `tests/test_policy_matrix.py`** (Pillar A exit criterion). Twelve rows lock the shape:

| Row | Scenario | Expected verdict |
|---|---|---|
| CC-01 | linkedin send, no prior events in ledger | Allow |
| CC-02 | linkedin send, email `send_confirmed` within window | Block (rule=`cross-channel-email-suppresses-linkedin`) |
| CC-03 | linkedin send, email `send_confirmed` beyond window | Allow |
| CC-04 | email send, `li_dm_confirmed` within window | Block (rule=`cross-channel-linkedin-suppresses-email`) |
| CC-05 | linkedin send, email `send_intent` only (no confirmed pair) | Allow (rules only count confirmed touches — ADR-0001 asymmetric-cost) |
| CC-06 | linkedin send, email `send_confirmed` exactly at `now - window_days` | **Block** (window is **inclusive** on the lower end — matches `DomainThrottleRule` convention; an event at the boundary instant is still "within window_days"). Pinned by `TestCC06BoundaryInclusiveOnLowerEnd::test_at_exact_boundary_blocks`. |
| CC-06b | linkedin send, email `send_confirmed` 1µs older than `now - window_days` | Allow (strictly older than cutoff → outside the window). Pinned by `TestCC06BoundaryInclusiveOnLowerEnd::test_one_microsecond_past_boundary_allows`. The CC-06 / CC-06b pair together pin the comparator (`<` vs `<=`); without both, the choice could silently drift. |
| CC-07 | linkedin send, email `send_confirmed` 1 second inside the window (i.e. at `now - (window_days - 1s)`) | Block (clearly inside the window under any boundary convention) |
| CC-08 | `consider_channels: []` (empty list) → `from_yaml` raises | structural error at load time |
| CC-09 | `consider_channels: [email]` AND `block_when: {channel: email}` (rule queries same channel it fires on) | load-time warning logged via stderr; rule still loads (the user may want this for non-touch-recency reasons) |
| CC-10 | `consider_channels: [email, twitter]` | Block if either channel has confirmed touch in window |
| CC-11 | Hypothesis property: rule verdict is independent of `ctx.timezone` (inherits ADR-0002 DST property for cross-channel rules) | property holds |
| CC-12 | Rule ordering: cross-channel rule placed before same-channel rule whose Block would otherwise fire | first Block wins — engine short-circuit per ADR-0001 |

The CC-* rows extend the existing per-rule sections of the Pillar A 50-case matrix; they do not replace existing rows.

## Alternatives considered

### Alternative 1: Defer cross-channel rule class to Pillar C (the status quo before this ADR)
Ship Pillar A v1 with same-channel rules only; cross-channel arrives in Pillar C alongside the LinkedIn integration. **Rejected because:** by Pillar C, the engine, YAML schema, helper functions, and every factory rule have been written under a same-channel assumption. The cross-channel rule arrives as a special case that composes poorly with the existing pattern — a known refactor-twice pain point. Cross-channel is not an integration concern, it is a rule-shape concern; it belongs in the engine pillar. The cost of doing it now is one new module + two factory rules + 12 test rows; the cost of doing it later is renegotiating the YAML schema with downstream users already in production.

### Alternative 2: Treat channel as an identity attribute (a tag on Person, not a context predicate)
Store `channels: [email, linkedin]` on Person frontmatter and gate sends by tag match. **Rejected because:** the source-of-truth for "did we touch this person on channel X" is the ledger event stream (SOURCES-OF-TRUTH row "Send-history"), not a denormalized identity attribute. Identity attributes describe *who someone is*; channel touches describe *what we did*. Conflating them violates I1 and the Phase 5.5 identity-vs-touch separation. Same reason cross-channel coordination doesn't live on `identity_keys`.

### Alternative 3: Extend `block_when:` to accept asymmetric channel filters
Treat `block_when: {channel: linkedin, consider_channel: email}` as a single filter spec. **Rejected because:** `block_when:` semantics ("when does this rule fire?") and `consider_channels:` semantics ("which events does this rule join?") are conceptually distinct. Overloading `block_when:` to do both makes YAML harder to read — a reader has to know that `consider_channel:` is special-cased inside the filter, not part of the filter. Separate keys at the top level of the rule spec are clearer.

### Alternative 4: A single cross-channel rule class with YAML-configured channel pairs
One `CrossChannelTouchRule` parameterized by `block_when:` + `consider_channels:` covers every pair. **Accepted** — this *is* the decision. (Recorded here so a reader looking for "why not one rule class per pair?" finds the answer.) Per-pair classes (`EmailSuppressesLinkedinRule`, `LinkedinSuppressesEmailRule`, `TwitterSuppressesEmailRule`, ...) would balloon as channels are added. The single-class + YAML-configuration pattern matches the existing `cooldown.requires-prior-send` shape (one class, many configurations).

### Alternative 5: Add a separate engine for cross-channel ("cooldown engine" + "coordination engine")
Two independent engines, each with its own rule registry and evaluation pass. **Rejected because:** there is no operational reason to evaluate cross-channel rules separately from same-channel rules. The gate makes one decision per send. Two engines means two `policy_blocked` event shapes, two simulation modes, two live-reload paths. The existing engine handles both rule kinds because both implement the same `Rule` Protocol — the engine doesn't know or care which kind it's evaluating.

### Alternative 6: Make the rule class a Pillar A Week 1 retrofit instead of Week 2 work
Land `cross_channel.py` in the same Week 1 commit that just shipped (`types.py` + `engine.py` + `cooldown.py`). **Rejected because:** Week 1 task #4 has shipped (commit `b20b203`); reopening that commit's scope re-tests territory already verified. Week 2's suppression work is the natural seat — `suppression.py` and `cross_channel.py` ship in the same commit, with the test matrix extended in lockstep.

## Consequences

### Positive
- Cross-channel double-engagement (R011) is impossible by construction in the default config — the v1 factory ruleset ships both pair directions (email↔LinkedIn).
- The imminent LinkedIn-as-default-channel strategy adoption can land without a policy-engine refactor.
- Pillar C's scope is cleaner — event types + reconcile, not policy logic.
- The pattern generalizes: when Twitter DMs arrive (Pillar D or later), the existing rule class accepts `consider_channels: [email, linkedin]` without code changes.
- Pillar A's simulation mode (Week 5) covers cross-channel scenarios automatically — same engine path, same `policy_blocked` event shape.

### Negative
- v1 ships with two factory rules whose target events (`<chan>_confirmed` where chan ∈ `{linkedin}`) don't exist in the ledger until Pillar C. Until then, the rules always return `Allow()`. A user reading `cooldowns.example.yml` sees rules they can't immediately verify firing. Mitigation: doc comments in the example YAML mark these rules as `# Activates when Pillar C lands LinkedIn event types`. The rule class skips its query path cheaply when zero matching events exist.
- One more rule class to maintain (`CrossChannelTouchRule` in a new `cross_channel.py` module). Acceptable cost — the alternative (refactor in Pillar C) costs more.
- The Pillar A test matrix grows by 12 rows. Acceptable; the exit criterion already targets 50 cases.

### Neutral / observability
- Cross-channel blocks emit the standard `policy_blocked` event (per ADR-0001). The `detail` field carries `rule`, `fires_on`, `considers`, `prior_touch_channel`, `prior_touch_ts`, `prior_touch_intent_id`, `window_days`. The funnel CLI (`ledger.py funnel --breakdown rule`) surfaces cross-channel refusals as a distinct rule category without new code.
- Risk register R011 moves from `Open` to `Mitigated by design (rules in place; activate when Pillar C ships LinkedIn events)` in the same commit as this ADR.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAMLs remain the SoT for blocking logic. Channel touches are read from the ledger event stream (existing SoT row "Send-history"). No new SoT introduced; no denormalized view added.
- **I2 (two-phase commit):** Cross-channel rules consume `<channel>_confirmed` events only — they intentionally do **not** block on `<channel>_intent` alone, because the intent might fail and never reach the human. The asymmetric-failure-cost principle (PILLAR-PLAN §0) compels this: blocking on an intent that later fails is a false-positive (worse) than missing one prior touch (a false-negative).
- **I5 (observable by default):** Every cross-channel `Block` emits `policy_blocked` with the standard detail shape plus cross-channel-specific fields enumerated above.
- **I6 (tests prove invariants):** Rows CC-01 through CC-12 are mandatory. CC-11 (the Hypothesis property test) inherits the ADR-0002 DST-safety guarantee through the same UTC age math.
- **I8 (documented decisions):** This ADR.

Does not weaken any invariant.

## Migration / rollout

Greenfield: `orchestrator/policy/cross_channel.py` is a new file (no existing code to migrate). The YAML schema gains two new keys (`consider_channels:`, `window_days:`) on a new rule type (`cooldown.cross-channel-touch`) — existing YAML files that don't use the new type are unaffected. The factory `cooldowns.example.yml` is extended with the two cross-channel preview rules in the same commit that adds the rule class.

`RuleContext` is unchanged — `channel` was already present per ADR-0001.

The rule class queries the ledger via `ctx.ledger.query_by_person(ctx.person_id)` (already in `LedgerLike` Protocol), filters events by `type.endswith("_confirmed")` (per §Decision "Event-type predicate" above) and by event-level `channel` membership in `consider_channels`, then applies the `window_days` threshold against `ctx.now` using UTC age math (ADR-0002 convention; inclusive lower-end per §Decision "Boundary semantics"). No ledger schema changes required. No `LedgerLike` Protocol changes required.

Doctor preflight (Phase 5 / Pillar A Week 1 task #6) parses `cooldowns.yml` at install time; once `cooldowns.example.yml` includes the cross-channel rules, preflight covers their YAML validity automatically.

Order of work:
1. **Now (with this ADR):** PILLAR-PLAN.md scope update, RISK-REGISTER.md R011 row, ADR-0001 / ADR-0002 cross-links. **No code yet.**
2. **Pillar A Week 2:** `cross_channel.py` lands alongside `suppression.py`; test matrix rows CC-01 through CC-12 added to `tests/test_policy_matrix.py` (or to `tests/test_policy_cross_channel.py`, mirroring the per-class organization of `test_policy_cooldown.py`); `cooldowns.example.yml` extended with the two factory rules.
3. **Pillar C Week 7+:** LinkedIn event types land. Cross-channel rules begin enforcing; verify via the simulation CLI before any live LinkedIn send.

## References

- ADR-0001 (policy engine architecture) — `RuleContext.channel` field introduced here.
- ADR-0002 (cooldown rules + recipient timezone semantics) — channel-as-filter pattern; UTC age math principle that cross-channel inherits.
- `docs/PILLAR-PLAN.md` §2 Pillar A and §2 Pillar C (scope updated in same commit as this ADR).
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — risk this ADR mitigates by design.
- `orchestrator/policy/cross_channel.py` — lands in Pillar A Week 2.
- `config-template/cooldowns.example.yml` — extended in same commit as Week 2 implementation.
- ADR-0004 (suppression + GDPR forget) — Week 2 sibling; landed 2026-05-16.
- ADR-0005 (sending-window + tz inference) — Week 3 sibling; landed 2026-05-18.
- ADR-0006 (budget rules + `cost_incurred` event) — Week 4 sibling; landed 2026-05-18.
- Followups: ADR-0007 tier rules (Week 5). (Sending-window pulled forward to 0005, shifting budget+tier +1; see ADR-0005 §ADR numbering shift.)
