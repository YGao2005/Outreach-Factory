# ADR-0023: Per-channel policy migrations — Calendar booking daily cap (Pillar C Week 10)

- **Status:** Accepted
- **Date:** 2026-05-22
- **Pillar:** C (Multi-channel coherence — Week 10's per-channel policy migration; fourth of Weeks 7-11)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0020 (Week 7) shipped the first per-channel policy migration — `policy/0002_add_li_invite_weekly_cap` — and established the convention each subsequent per-channel cap migration follows. D72-D78 cover the structural decisions (ID convention, APPEND insertion, rule-name idempotence, content-additive-no-version-bump, existing-operator seed taxonomy, downstream pillar impact). ADR-0021 (Week 8) shipped `policy/0003_add_li_dm_weekly_cap` + decided D79-D83 (LinkedIn-DM-specific). ADR-0022 (Week 9) shipped `policy/0004_add_tw_dm_weekly_cap` + decided D84-D88 (Twitter-DM-specific). Weeks 8 + 9 are derivative — same rule class, same window unit (weekly), same failure-mode framing (platform-side enforcement of cold-DM volume). **Week 10 diverges structurally on TWO axes**:

1. **The window is DAILY (`window_hours: 24`), not WEEKLY** (`window_days: 7`). The engine's `BudgetWindowCapRule` (per ADR-0006) accepts both forms; Weeks 7-9 use `window_days:`; Week 10 is the first per-channel cap to use `window_hours:` per the factory file's existing Rule 9 (commented Apollo daily cap) convention.

2. **The failure-mode framing inverts from "platform-side enforcement" to "operator-side runaway loop."** Weeks 7-9 all defended against platform-side cold-outreach enforcement (LinkedIn account suspension, LinkedIn shadowban, Twitter account flag). **Cal.com has NO platform-side daily cap on shared booking links** — the platform is content-neutral to volume; the operator's calendar surface is what binds. The cap mitigates a different failure mode: a dispatcher-in-bad-loop sharing booking links with too many recipients in one batch run, overwhelming the operator's calendar + creating reputational damage with recipients who book overlapping slots. ADR-0006 Rule 11 (`per-run-spend-cap`) is the structurally adjacent existing rule — also a runaway-loop guard.

ADR-0019 (Pillar C Week 6) is the prerequisite ADR establishing the dispatcher whose emissions this rule consumes. ADR-0019 D65 names `source="calendar_booking"` as the Calendar booking dispatcher's `cost_incurred` emission shape + `channel="calendar"` as the channel value (distinct from `linkedin` / `twitter`). ADR-0019 D66 establishes the asymmetric two-phase shape (`calendar_booking_intent` unconditionally at link-share time; `calendar_booking_confirmed` only via webhook on actual booking). ADR-0015 D40's split-source convention separates `calendar_booking` from `linkedin_invite` / `linkedin_dm` / `twitter_dm` so operators configure per-action caps; Weeks 7-9 activated three caps; Week 10 activates the calendar-booking cap.

The seven concerns Week 10 resolves:

1. **`max_units:` default — Cal.com's enforcement surface is FUNDAMENTALLY DIFFERENT from LinkedIn / Twitter's.** Where Weeks 7-9 all defend against platform-side cold-outreach enforcement, Cal.com does NOT impose a per-day cap on booking links shared via URL. The asymmetric-failure-cost calculus pivots from "platform-side enforcement triggers" to "operator-side runaway loop triggers"; D89 pins 10 + names the operator-side-runaway-loop failure-mode framing.

2. **Window unit choice — `window_hours: 24` vs `window_days: 1`.** The engine accepts both forms; the operator-facing semantic is what differs. D90 pins `window_hours: 24` per the factory file's existing Rule 9 (commented Apollo daily cap) precedent — daily caps spell out hours; weekly caps spell out days; the hours form makes the daily nature explicit at the rule-entry level without scanning the value.

3. **Intent-vs-confirmed counting semantics.** Cal.com's asymmetric two-phase shape (ADR-0019 D66) emits `calendar_booking_intent` at link-share time (operator's outbound action) + `calendar_booking_confirmed` via webhook (recipient's responsive action). The cap could count intents, confirmed bookings, or both. D91 pins INTENTS — the cap protects the operator from runaway send loops; recipient booking action is operator-positive, not operator-negative.

4. **Factory template Rule 12e — whether to ship a commented documentation example.** Weeks 7-9 all shipped factory Rules 12b / 12c / 12d. Week 10 has the same choice. D92 pins YES + names the longer comment shape required to explain the operator-side-runaway-loop failure mode (a framing genuinely new to the Pillar C operator-readable surface).

5. **Stale-source detection — whether to mirror Week 7's WARNING log path.** Weeks 8 + 9's ADRs D81 + D86 already rejected the analogous staleness path for LinkedIn DM + Twitter DM. Week 10 asks whether an analogous staleness path applies for Calendar booking. D93 pins NO (same posture as ADRs 0021 D81 + 0022 D86 — no historical factory shape exists for operators to have stale-copied).

6. **Existing-operator seed — which of ADR-0020 §D77's three shapes apply.** The Calendar booking dispatcher shipped after the split-source convention; Shape 1 (canonical name with stale source) has no historical precedent. D94 pins the subset that applies (Shape 2 + Shape 3; not Shape 1).

7. **Downstream pillar impact — adapted from ADR-0022 D88 + Calendar-booking-specific notes.** The Week 10 rule has the same shape Pillar D / E / F / G / H / I / J query/observe as Weeks 7-9, but the asymmetric two-phase dispatcher shape (per ADR-0019 D66) changes Pillar D / H's interaction patterns. D95 names the Calendar-booking-specific adaptations.

Risks this ADR mitigates by design: **R-operator-side-runaway-loop-on-calendar-booking** — operators with the Calendar booking dispatcher can over-share booking links silently if a dispatcher loops on the same recipient list (the dispatcher's per-Person idempotence covers per-Person but doesn't cover "this is the third batch I've run today against overlapping cohorts"). A misbehaving batch sharing 50 booking links in one run would overwhelm the operator's calendar — recipients booking overlapping slots; the operator's calendar surface becoming first-come-first-served chaos; reputational damage with the recipients who can't get the slot they expected. The per-channel daily cap closes the gap by refusing further sends after 10 booking-link shares in 24 hours — well above the operator's normal 3-5/day cadence + well below the runaway-loop volume. Additionally **R-calendar-surface-overwhelm** — operators sharing too many booking links in a short window saturate their available Cal.com slots; recipients see "no availability" or "fully booked"; the cap prevents the saturation by capping the link-share rate.

## Decision

### D89. `max_units: 10` — operator-side-runaway-loop guard, NOT platform-side-enforcement guard

The factory-shipped + migration-written `calendar-booking-daily-cap` rule's `max_units:` is **10** (10 calendar-booking-link shares per 24 hours per operator).

**Why 10 — and why the failure-mode framing is fundamentally different from Weeks 7-9:**

- **Cal.com does NOT impose a per-day cap on shared booking links.** The platform's pricing model is per-user (or per-team), not per-link-share; there is no documented daily-share limit operators can hit. This is structurally distinct from Weeks 7-9, all of which defend against platform-side cold-outreach enforcement:
  - **Week 7 (LinkedIn invite, ADR-0020):** LinkedIn enforces a ~100/week soft cap on personal accounts; exceeding it risks account suspension (multi-week recovery; outreach surface lost).
  - **Week 8 (LinkedIn DM, ADR-0021):** LinkedIn does NOT publish a DM cap but enforces silently via shadowban + account-level penalties (multi-week recovery; outreach surface lost; recipient notifications silently dropped).
  - **Week 9 (Twitter DM, ADR-0022):** Twitter's cookie-scrape MCP rate-limit (~10 calls/minute per ADR-0018 D59) is the more-common failure mode (recoverable: re-capture cookies + resume); Twitter's account-level enforcement is rarer but more severe.
  - **Week 10 (Calendar booking):** Cal.com has NO platform-side daily cap. The constraint is OPERATOR-SIDE — the operator's own calendar surface (number of available slots) + reputation with recipients who book overlapping slots.

- **The asymmetric-failure-cost calculus inverts.**
  - **False-block (cap too low + operator hits 10 in a single day):** one-line YAML edit raises the cap. Operator-time cost ~30 seconds. Operators with high booking volume (a salesperson sharing 20+ booking links/day routinely) tune up before they hit 10.
  - **False-allow (cap too high + dispatcher-in-bad-loop fires):** a misbehaving dispatcher loops on a recipient cohort + shares 50 booking links in one run. Recipients all book the same available slots; operator's calendar surfaces 5 confirmed bookings + 45 "fully booked" frustrations. Operator-time cost: hours-to-days reconciling with frustrated recipients + rebuilding Cal.com slot availability + reputational damage with the 45 recipients who got blocked. Not platform-enforced but operator-painful — the operator's outbound surface is the constraint.
  - The cost ratio is asymmetric (false-allow is days-of-recovery; false-block is 30-seconds-tune-up); the default biases toward refuse.

- **Yang's current cadence + headroom math.** Yang's normal Cal.com booking-link sharing cadence is ~3-5/day (per the current state of the prospect pipeline). A cap at 10 gives 2-3x headroom for normal use + catches a dispatcher-in-bad-loop scenario at ~10x normal cadence (a runaway sharing 50 booking links in one batch run would fire the cap after 10). Operators with substantially higher booking volume (~15-20/day routinely) tune up; the factory default covers Yang + the median early-adopter operator profile.

- **The cap is NOT a published platform threshold; it is an OPERATOR-DELIBERATE safety guardrail.** Operators reading the rule's `reason:` field in `policy_blocked` events should understand the cap is operator-tunable + operator-deliberate, NOT a platform-published soft limit (unlike LinkedIn's 100/week per ADR-0008). The rule's `reason:` text names "operator-deliberate guardrail against runaway link-sharing loops" explicitly.

- **Operator-tunability.** Operators with high booking volume tune up (one-line YAML edit; `name:` idempotence preserves tuning across re-applies). Operators in the very-low-volume phase (~1-2/day) can tune down to 5 for tighter operator-side discipline. The factory's 10 covers the median use case.

- **Doctor preflight (Pillar I) is the natural future home for tuning advice.** A future Pillar I doctor preflight pass may inspect the operator's actual `cost_incurred.source=calendar_booking` history + suggest a tuned cap based on observed volume. Until then, 10 is the safe-by-default starting point.

**Rejected D89 alternatives:**

- **`max_units: 20` — more permissive, catches only egregious loops.** **Rejected** because:
  - 20/day is plausibly above the operator-friction threshold for a runaway loop. A dispatcher sharing 20 booking links in one run would still produce 20 recipients all competing for the operator's available slots — half the operator-pain of 50, but still painful at the operator-reputation layer. The default should bias toward the operator's safety-margin (10) rather than the runaway-detection-threshold (20).
  - The 20/day default would require operators with normal 3-5/day cadence to hit a cap they'd never hit at 10/day; the friction-vs-protection tradeoff favors the lower default since runaway loops are the worst-case + operator-deliberate tune-up is cheap.
  - The asymmetric-failure-cost calculus argues for the lower default — false-block is 30-seconds-tune-up; false-allow is hours-of-reconciliation + reputational damage. 10 sits well below the operator-friction threshold for the median operator.

- **`max_units: 5` — very tight, operators ramping up calendar usage may hit it routinely.** **Rejected** because:
  - 5/day is plausibly below the operator's actual safe-quota — it forces every operator with the dispatcher to tune up after their first or second batch run, which is friction without protection (the operator runs into the cap on their normal cadence + has to edit YAML to proceed).
  - The factory default's job is to be safe for the median operator, not the most-conservative one. 5 is plausibly the right number for operators in the very-low-volume warm-up phase; the migration could surface that recommendation in commit notes / Pillar I doctor as "consider tuning down to 5 for warm-up." But the factory default for an operator with normal 3-5/day cadence should not be a value they routinely hit.
  - A more-restrictive default would make operators less likely to keep the rule active (rather than disable / remove it), which is the opposite of the migration's purpose.

- **`max_units: 50` — mirror Weeks 7-9's defaults for cross-channel consistency.** **Rejected** because:
  - The cross-channel-consistency argument that justified Week 9 D84's `max_units: 50` (matching Week 8's LinkedIn DM default) does NOT apply here. Weeks 7-9 are all platform-side-enforcement caps with similar cold-outreach intensity profiles; the cross-channel-consistency benefit was operator mental-model coherence ("DM cap is 50 per week regardless of platform").
  - Week 10's failure-mode framing is fundamentally different (operator-side-runaway-loop, NOT platform-side-enforcement). The cross-channel-consistency tiebreaker that justified Week 9's 50 doesn't translate; operators don't reason about "calendar booking cap" the same way they reason about "DM cap."
  - 50/day calendar-booking-link shares would not catch a runaway loop until far into the failure mode. A dispatcher in a bad loop sharing 50 links in one run would fire the cap exactly at the runaway threshold — too late to prevent the operator-pain.
  - The platform-side calculus that justified `50/week` doesn't justify `50/day` (the daily-vs-weekly divergence interacts with the asymmetric framing).

- **`max_units: 70` with `window_days: 7` — preserve weekly window for cross-week-consistency.** **Rejected** because:
  - The relevant failure mode is the per-day runaway loop (a dispatcher firing in a single batch run; runs are bounded by hours, not days). A weekly window with 70/week (~10/day average) would only catch a runaway loop AFTER the operator has cumulative 70 link-shares across the week — providing zero protection against a single-day runaway that produces 50 shares in 4 hours.
  - The daily window is structurally correct for the failure mode being mitigated. The weekly windowing of Weeks 7-9 is structurally correct for THEIR failure modes (platform-side enforcement aggregates over rolling windows). Different failure modes warrant different window units.
  - See D90 below for the window-unit choice rationale.

### D90. Window unit choice — `window_hours: 24`, NOT `window_days: 1`

The factory-shipped + migration-written `calendar-booking-daily-cap` rule's window is **`window_hours: 24`** (24 hours per the engine's `BudgetWindowCapRule` semantics). The engine accepts both `window_hours:` AND `window_days:` per ADR-0006 §"Three concrete rule classes"; the choice is operator-readability.

**Why `window_hours: 24` and not `window_days: 1`:**

- **The factory file's existing Rule 9 precedent.** `config-template/cooldowns.example.yml` Rule 9 (commented Apollo daily cap example, lines 154-160) uses `window_hours: 24` for its daily-cap shape. The convention established by Rule 9 (the only pre-Pillar-C daily-window example in the factory file) is "daily caps spell out hours; weekly caps spell out days." Operators reading the factory file see a consistent semantic: hours-based windows for sub-day caps + days-based windows for multi-day caps. Week 10's Rule 12e follows the Rule 9 convention.

- **Operator-facing semantic clarity at the rule-entry level.** A rule that reads `window_days: 1` requires the operator to mentally translate "1 day → 24 hours → daily cap." A rule that reads `window_hours: 24` is self-evidently a 24-hour rolling window at first glance. The semantic clarity matters more for a rule whose failure-mode framing is operator-deliberate (D89's runaway-loop framing depends on the operator understanding the rule's scope; the explicit hours value supports the explicit framing).

- **The engine treats `window_hours: 24` AND `window_days: 1` identically.** Per ADR-0006 §"Three concrete rule classes" (`BudgetWindowCapRule.__init__`'s `window_days` AND `window_hours` parameters convert to a single `window_seconds` internal value), the two forms are computationally equivalent. The choice is purely cosmetic; the cosmetic favoring `window_hours: 24` is the factory file's existing convention.

- **Pillar G's per-rule dashboards group by `rule:` field name, not by window-unit.** Pillar G's observability surface reads the rule's canonical name; the window-unit choice doesn't affect dashboard composition. The factory-readability is the load-bearing concern.

**Rejected D90 alternatives:**

- **`window_days: 1` — equivalent semantic, different surface.** **Rejected** because:
  - Diverges from the factory file's Rule 9 daily-cap convention (which uses `window_hours: 24`). The factory file's per-cap-shape convention is operator-reading-discipline; introducing `window_days: 1` for a daily cap when the existing daily example uses `window_hours: 24` creates surface inconsistency for no semantic gain.
  - The reading-order question "is this a daily or weekly cap?" is faster-answered by the explicit hours/days unit than by the numeric value. `window_days: 1` requires reading the numeric value; `window_hours: 24` is self-evident at the unit level.

- **`window_hours: 12` — half-day cap for half-day-scale runaway detection.** **Rejected** because:
  - 12-hour windows interact poorly with operator-active-hours patterns. An operator working across two timezones (e.g., US-east morning calls + US-west afternoon calls) plausibly spans 12+ hours of legitimate calendar-link sharing in one workday; a 12-hour cap would falsely fire on the timezone-spanning legitimate use case.
  - The 24-hour rolling window aligns with the operator's natural day boundary. A dispatcher-in-bad-loop scenario presents within hours; the cap fires regardless of whether the runaway happens at 09:00 or 18:00 because the 24-hour rolling window catches it.
  - The 12-hour-vs-24-hour distinction is unmotivated by the failure mode — the question is whether the cap catches a runaway loop, and 24 hours is the natural day-boundary anchor.

- **`window_hours: 48` — bigger window for cross-day cumulative protection.** **Rejected** because:
  - A 48-hour window with `max_units: 10` (the D89 default) would mean the operator's effective per-day cap is 5 — undermining D89's calibration. Operators routinely sharing 3-5 links/day would frequently hit the cap on day-2 of a busy stretch.
  - The 48-hour window doesn't catch runaway loops earlier (the loop fires within hours; the 24-hour window catches the same scenario as the 48-hour window in the runaway case). The longer window adds friction without adding protection.
  - The 24-hour-rolling-window framing is operator-readable + matches the failure mode being mitigated.

### D91. Count INTENTS (link shares), NOT confirmed bookings

The `calendar-booking-daily-cap` rule's `source: calendar_booking` filter consumes `cost_incurred` events emitted by the Calendar booking dispatcher per ADR-0019 D65. The dispatcher emits the `cost_incurred` event **at intent-time** (when the operator shares the booking link), NOT at confirmed-time (when the recipient books). Per the existing `BudgetWindowCapRule` contract (ADR-0006 §"Budget blocks emit the standard `policy_blocked` event"), the rule aggregates `cost_incurred` events with matching `source:` over the window — so the cap automatically counts intents, not confirmed bookings.

**Why count intents and not confirmed bookings — and why this is the correct semantic:**

- **The cap protects the operator's OUTBOUND action.** D89's failure mode (operator-side runaway loop) fires at OPERATOR-share-time, not at RECIPIENT-book-time. A dispatcher in a bad loop produces 50 share events in one batch run; the cap should refuse after 10 share events, BEFORE the operator has shared 50 links + caused the downstream operator-pain (recipients booking overlapping slots; calendar surface saturation; reputational damage). Counting confirmed bookings would mean the cap only fires after recipients HAVE booked — too late to prevent the failure mode.

- **Recipients booking IS operator-positive.** If the operator legitimately shares 10 booking links and all 10 recipients book within the same 24-hour window, that's 10 confirmed bookings + a fully-utilized operator calendar — the desired outcome. Counting confirmed bookings would incorrectly penalize the high-success-rate operator (they hit the cap on the day everyone happens to book). The cap's semantic is "protect the operator from over-sharing," not "throttle the recipient response rate."

- **The structural correctness of intent-counting follows from ADR-0019 D66's asymmetric two-phase shape.** The dispatcher emits `calendar_booking_intent` unconditionally at share time + emits `cost_incurred` paired with the intent. The `calendar_booking_confirmed` event lands LATER (via Cal.com webhook) when the recipient actually books — the cost event for that case is NOT re-emitted (the cost was already incurred at intent-time; the recipient's responsive action doesn't add to the operator's cost). The BudgetWindowCapRule's `source: calendar_booking` filter automatically picks up the intent-time emission; there is no secondary emission to potentially double-count.

- **No engine code change needed.** The `BudgetWindowCapRule` consumes `cost_incurred` events with matching `source:` already; no new field, no new event type, no new rule class. The intent-vs-confirmed semantic is enforced by WHEN the dispatcher emits the cost event (intent-time per ADR-0019 D65), not by any new aggregation logic in the rule.

- **Pillar G's funnel observability still surfaces the link-share-to-booking conversion ratio.** Per ADR-0019 D70's funnel observability, Pillar G charts `calendar_booking_intent` count vs `calendar_booking_confirmed` count to expose the "shared but not booked" rate. The cap's intent-counting semantic does NOT affect this surface — the intent + confirmed events both flow to Pillar G's queries; the funnel-conversion metric is computed from the event stream, not from the cap's gate decisions.

**Rejected D91 alternatives:**

- **Count confirmed bookings — the cap fires only when 10 recipients have actually booked.** **Rejected** because:
  - Defeats the failure-mode framing (D89). A dispatcher sharing 50 booking links in one batch run would NOT fire the cap until 10 of those 50 recipients booked — by which point the operator has already shared 50 links + the operator-pain is already inflicted (recipients seeing overlapping slot availability + competing for slots).
  - Incorrectly penalizes the high-success-rate operator. An operator sharing 10 booking links AND all 10 recipients book within the same 24-hour window would hit the cap exactly at the optimal outcome — the cap firing on day-11's first share when the operator's calendar is finally booked-out is desired-vs-undesired behavior contradiction.
  - Requires either a new rule class (`BudgetWindowConfirmedCapRule` filtering on event-type, not on cost-incurred `source:`) or schema-changing migration; either is scope creep against the content-additive migration shape (D75 inherited from ADR-0020).

- **Count both intents AND confirmed bookings — sum them as the cap value.** **Rejected** because:
  - Double-counts the desired outcome. An operator sharing 5 links + all 5 recipients booking would count as 10 events (5 intents + 5 confirmeds), hitting the 10-unit cap exactly when the operator wants to share their 6th link.
  - The semantic conflates "operator action" with "recipient action" — the cap's purpose is to protect against operator-side runaway loops, NOT to throttle the recipient's responsive engagement. Mixing the two muddies the rule's meaning.
  - The engine's current `BudgetWindowCapRule` doesn't natively support "sum of two event types" — would require a new rule class + schema bump + engine code change. Same content-additive scope-creep argument as the previous alternative.

- **Count outbound deliveries (a hypothetical "share event" the dispatcher would emit).** **Rejected** because:
  - There is no distinct "share event" emitted by the Calendar booking dispatcher; the share IS the intent. The dispatcher per ADR-0019 D65 emits `calendar_booking_intent` + `cost_incurred` at share time; introducing a third event-type would duplicate the existing share semantic without adding information.
  - The `calendar_booking_intent` event IS the canonical operator-action record per ADR-0019 D66; the cap counts it correctly via the cost event's `source:` filter.

### D92. Ship factory-template Rule 12e — commented Calendar booking cap example with the operator-side-runaway-loop failure-mode framing

The Week 10 commit adds a commented `Rule 12e` block to `config-template/cooldowns.example.yml`. The block mirrors Rule 12d's shape (Twitter DM cap) modulo channel filter / source / window unit / max_units / reason; it ships BETWEEN Rule 12d (Twitter DM cap) and Rule 13 (the tier-scoped budget cap example) — the next slot in the file's existing ordering per ADRs 0021 D80 + 0022 D85's precedent. **Rule 12e's comment is meaningfully LONGER than Rules 12b / 12c / 12d** because the operator-side-runaway-loop failure-mode framing requires explicit explanation that the cap is operator-deliberate-safety-guardrail, NOT a platform-published soft limit.

**Why ship Rule 12e:**

- **Per-channel symmetry — closes the per-channel-action documentation set.** Pillar C's structural identity is "every channel gets full primitive coverage." The factory template's documentation should reflect this. After Week 9 there are Rule 12b (LinkedIn invite) + Rule 12c (LinkedIn DM) + Rule 12d (Twitter DM). Rule 12e (Calendar booking) closes the per-channel-action set for the four Weeks-2-6 channel dispatchers (LinkedIn invite + LinkedIn DM + Twitter DM + Calendar booking). Skipping Rule 12e would leave operators reading "Rules 12b-d cover three channels; is there a Calendar booking cap too? where is it documented?" The mirror closes the documentation gap.

- **New-operator onboarding — operators reading the factory file see the operator-side-runaway-loop framing INLINE.** Operators copying `cooldowns.example.yml` to `~/.outreach-factory/policies/cooldowns.yml` get the commented Rule 12e as documentation in their installed file. When they later run `runner.apply(MigrationCategory.POLICY)`, the migration's APPEND semantics (D73 inherited from ADR-0020) drops the active rule AFTER the existing rule list — the operator's commented Rule 12e remains as documentation alongside the migration-installed active rule. The two coexist legibly.

- **The longer comment names the failure-mode framing operators need to understand BEFORE tuning.** Rules 12b-d's comments name platform-side enforcement (LinkedIn's 100/week soft limit; LinkedIn's silent shadowban; Twitter's cookie-scrape rate-limit). Rule 12e's comment names the operator-side-runaway-loop failure mode + the explicit "Cal.com has NO platform-side daily cap" context. Operators reading the factory file should NOT confuse the cap with a platform-published limit (which would suggest tuning is operator-irresponsible); they should understand the cap is operator-deliberate-safety-guardrail (which makes tuning operator-deliberate). The comment's job is to surface that framing at the operator's first read of the factory file.

- **Operator-tuning template.** Operators with high booking volume (~15-20/day routinely) can uncomment Rule 12e BEFORE running the migration + set `max_units:` higher than the factory default of 10. The migration's name-match idempotence (D74) then skips the file because the operator's rule shares the canonical name. The factory comment is the on-ramp for operator-deliberate tuning at install time.

- **Identical maintenance cost to skipping.** Adding Rule 12e is ~50 lines of comment + YAML in the factory file (longer than Rules 12b / 12c / 12d because the operator-side-runaway-loop context needs explicit explanation). Skipping has zero file-edit cost but creates an asymmetric file (Weeks 7-9 each got a documented example; Week 10 wouldn't) AND leaves the operator-side-runaway-loop framing undocumented at the operator's first-read surface (operators would have to read ADR-0023 to discover it). The cost-benefit clearly favors shipping.

**Rejected D92 alternatives:**

- **Skip Rule 12e — let the migration's writeback be the operator's first exposure.** **Rejected** because:
  - Operators inspecting the factory file before running migrations see Rules 12b-d for LinkedIn + Twitter but nothing for Calendar booking — surface asymmetry the per-channel migration sequence should not introduce. Same rationale as ADRs 0021 D80 + 0022 D85's rejections of this alternative.
  - The operator-side-runaway-loop failure mode (D89) is genuinely new to Pillar C; operators encountering the cap firing without prior context would investigate ADR-0023 rather than understanding it from the factory file's documentation. The inline comment is the operator-readable explanation surface.
  - The Pillar I doctor preflight (future) will plausibly grep the factory file for canonical rule names; an absent canonical name forces a special-case "Pillar C Week 10's rule has no factory example" branch in the doctor. Shipping the example keeps the doctor's grep uniform.

- **Ship Rule 12e with Rule 12d's comment structure verbatim (just swap field values).** **Rejected** because:
  - The per-channel failure-mode framing is genuinely different. Rules 12b-d all name platform-side enforcement; Rule 12e's failure mode is operator-side runaway loop. Verbatim reuse would misdirect operators about what the cap protects against — operators would assume Cal.com has a platform-side daily cap (which it doesn't) + would tune the rule based on an incorrect mental model.
  - The factory file's job is to document per-channel context; a uniform comment block defeats the per-channel documentation discipline established by Weeks 7-9.
  - The Week 10 comment needs to explicitly name: (a) Cal.com has NO platform-side daily cap; (b) the cap mitigates operator-side runaway loops; (c) Yang's normal ~3-5/day cadence + the 2x-headroom math; (d) operators with high booking volume tune up. Verbatim reuse of Rule 12d's comment can't fit this content.

- **Ship Rule 12e with a placeholder for `max_units:` (e.g., `max_units: <TUNE_ME>`) to force operator-deliberate tuning.** **Rejected** because:
  - Placeholders break the YAML — a commented-out rule with `max_units: <TUNE_ME>` is not parseable if the operator uncomments without first replacing the placeholder. Operator-deliberate friction at the wrong layer (the operator has to know to replace the placeholder; YAML's parse error if they don't is opaque).
  - The factory's job is to ship a working default. Placeholders push the "what's the right value?" question to every operator individually, when the migration's actual purpose is to ship a safe default + let operators tune. D89's 10 is the safe default; Rule 12e documents it.
  - Per the same logic as Week 8's ADR-0021 D80 rejection of this alternative.

- **Ship Rule 12e with `max_units: 20` to demonstrate operator-tunability via the commented example.** **Rejected** because:
  - The factory documentation must match the migration's actual writeback. If Rule 12e shows `max_units: 20` but the migration writes `max_units: 10`, operators reading both surfaces see contradictory recommendations — confusing + a maintenance hazard. Same rationale as ADRs 0021 D80 + 0022 D85's rejections of this alternative.
  - Per D89's analysis, 10 is the correct factory default; documenting 20 in Rule 12e would be a misdirection at the operator's first-read surface.

### D93. NO stale-source detection — same posture as ADRs 0021 D81 + 0022 D86

The Week 10 migration's `upgrade()` does NOT emit a WARNING log when the canonical `calendar-booking-daily-cap` rule is already present with a non-canonical `source:` value. The migration's idempotence check (D74 inherited from ADR-0020) skips the file when the canonical name is present — it does NOT inspect the rule's other fields to surface staleness.

This is a deliberate inheritance from ADRs 0021 D81 + 0022 D86's posture, which itself diverges from Week 7's policy/0002 WARNING path. The structural reason is identical: no historical factory shape exists for Calendar booking operators to have stale-copied.

**Why no stale-source path for Week 10:**

- **No historical precedent.** The Calendar booking dispatcher (ADR-0019) shipped 2026-05-22 — AFTER ADR-0015 D40's split-source convention (Week 2 — 2026-05-20). There has never been a factory-shipped `calendar-booking-daily-cap` rule with any non-canonical `source:` value for operators to have copied. ADR-0008's factory comment was invite-specific; ADRs 0016 / 0018 / 0019 all shipped after the split-source convention; no equivalent staleness shape exists for the post-Week-2 channels.

- **Operator-hand-written rules are operator-deliberate.** If an operator hand-wrote a `calendar-booking-daily-cap` rule with `source: calendar` (without the `_booking` suffix — a plausible un-suffixed naming choice) or `source: calendar_booking_intent` (a plausible mis-conflation with the event-type prefix per ADR-0019 D65) or `source: linkedin_invite` (a likely copy-paste mistake from Week 7's rule), the divergence is operator-deliberate — perhaps they're using a custom dispatcher emitting a different source, perhaps they made a copy-paste mistake they'll find on next inspection. The migration should not nag.

- **Asymmetric stale-source posture across the policy/0002-0006 range.** Per ADR-0020 §D77, Shape 1 (stale source) applies only to the invite rule (Week 7) because the factory file ships only the invite rule's commented form with the historical `source: linkedin` value. Shapes 2 + 3 (canonical correct, or renamed) apply to every per-channel migration uniformly. Per the Week 7 / Week 8 / Week 9 / Week 10 sequence: Shape 1 applies only to Week 7; Shapes 2 + 3 apply to Weeks 7-11.

- **The structural intervention against a future contributor reflexively adding a "stale source detection" branch by mirroring policy/0002 is the `TestNoStaleSourceWarning` test class introduced in Week 8 + extended in Weeks 9 + 10.** Any future per-channel migration whose ADR-decision says NO stale-source detection gets a `TestNoStaleSourceWarning` class with sub-cases covering the values an operator might hand-write. Week 10's sub-cases cover: `source: calendar` (plausible un-suffixed), `source: calendar_booking_intent` (plausible event-type-mis-conflation), `source: linkedin_invite` (plausible copy-paste from Week 7), AND the negative-control `source: calendar_booking` (canonical — no warning even on the correct shape).

- **A future Pillar I doctor preflight is the home for misconfig detection.** The Pillar I OSS bring-up will ship a `python -m orchestrator.policy doctor` command that inspects every active policy rule for canonical-shape conformance + warns on per-rule deviations (wrong source value, wrong channel value, wrong scope, etc.). That command is the principled home for per-rule misconfig surfacing; the per-migration WARNING path in policy/0002 is a one-off accommodation for the specific Shape 1 case. Week 10 does not introduce a parallel one-off for a shape that does not exist.

**Rejected D93 alternatives:**

- **Mirror Week 7's WARNING path: warn on any non-canonical `source:` value when the canonical name is present.** **Rejected** because:
  - Same rationale as ADRs 0021 D81 + 0022 D86's rejections of this alternative. Pillar I's doctor is the correct surface for general misconfig detection. A per-migration WARNING for every conceivable deviation pollutes the runner's apply logs + duplicates effort that Pillar I will land cleanly.
  - The Shape 1 case (a specific historical mistake from a specific factory shape) is fundamentally different from "operator's rule has the wrong source" — the former is a known-population state with a known operator base; the latter is an open-ended class. Treating them the same conflates remediation paths.

- **Add a "warn-on-linkedin-or-twitter-source-mistake" path specifically for Calendar booking (the most likely copy-paste mistakes from Weeks 7-9).** **Rejected** because:
  - The migration would be encoding heuristics about likely operator mistakes; the heuristic surface grows as more migrations land (Week 11's cross-channel migration with "warn-on-single-channel-source" path?). Each per-migration heuristic is a maintenance burden + an audit-trail noise source.
  - The `TestNoStaleSourceWarning` invariant test pins the negative posture explicitly — future contributors who reflexively add the heuristic fail the test + are forced to re-think.
  - Operators who make copy-paste mistakes find them via dispatcher-not-firing observation (the rule activates but reports zero usage); the natural feedback loop is more reliable than a migration-time warning.

- **Emit an INFO log noting the operator's source value when skipping, without a WARNING.** **Rejected** because:
  - Same rationale as ADRs 0021 D81 + 0022 D86's rejections of this alternative. INFO logs are noise in the runner's normal apply path; per-rule visibility belongs in the dry-run preview or Pillar I doctor.

### D94. Existing-operator seed — which ADR-0020 §D77 shapes apply to Week 10

ADR-0020 §D77 catalogs three pre-migration operator shapes for the LinkedIn invite cap (Week 7). For Calendar booking (Week 10), the operator shapes are:

1. **Shape 1 (canonical name, stale source) — DOES NOT APPLY.** Per D93's analysis: there is no historical factory-shipped Calendar booking daily cap rule; no operator could have copied a stale `source: calendar` (or any other non-canonical value) from a factory shape that never existed. Operators with hand-written non-canonical-source rules are operator-deliberate per D93; the migration is silent. Same posture as ADRs 0021 §D82 + 0022 §D87.

2. **Shape 2 (canonical name, correct source `calendar_booking`) — applies.** Operators who hand-wrote the rule before Week 10 (anticipating the migration, or installed it via copy-paste from the Week 7-9 commits' forward-references in ADRs 0020 / 0021 / 0022) have the rule with the canonical source. The migration's name-match idempotence skips. **Operator remediation:** none needed.

3. **Shape 3 (renamed) — applies.** Operators who wrote their own Calendar booking cap rule with a different name (e.g. `calendar-cap-10` or `my-cal-throttle`) have a rule that delivers the same enforcement under a different name. The migration's name-match (canonical-name only) treats it as "not present" + adds the canonical-named version alongside. The operator now has TWO rules with overlapping enforcement. **Operator remediation:** delete one of the two rules. (The canonical version is operator-acceptable to delete — it's the migration's default; the operator's renamed version preserves their tuning. Or vice versa — operator's choice.) Same posture as Weeks 7-9's Shape 3 + the same doctor preflight (Pillar I) is the natural future warning surface.

The factory file's `cooldowns.example.yml` ships the commented Rule 12e (per D92) — new operators copying the factory get the canonical shape with `source: calendar_booking` from day one. There is no pre-Week-10 factory shape they could have stale-copied (Shape 1's non-applicability).

**Rejected D94 alternatives:**

- **Catalog Shape 1 anyway with a hypothetical "what-if-Cal.com-changes-API-emit-shape" path.** **Rejected** because:
  - ADR-0023 is recording the state of the world today, not speculating on future Cal.com API changes. The migration's `source: calendar_booking` matches the Pillar C Week 6 dispatcher's emit value (ADR-0019 D65); if Cal.com changes the underlying webhook payload shape (per the schema-version cascade in ADR-0019 D71), the dispatcher updates first + the rule's source value follows.
  - Hypothetical future-state Shape 1 would be confusing in the operator-facing rollout text (operators reading the ADR look for actionable advice; speculative scenarios dilute it).

- **Use a tag system (e.g. ADR-0023 references ADR-0022 §D87 by tag instead of restating).** **Rejected** because:
  - ADR-0023 is read independently of ADRs 0020-0022 — operators looking up "what does Week 10 do?" should get a self-contained answer. Cross-references force readers to chase a chain of ADRs that erodes the ADR-per-decision discipline.
  - The restatement is short (3 shapes × ~2 sentences each) — not a maintenance burden.

- **Defer existing-operator seed entirely to Pillar I doctor.** **Rejected** because:
  - Pillar I is 34+ weeks out (per PILLAR-PLAN §6 timing). The migration ships now; operator-facing rollout documentation must be in this ADR.
  - The Pillar I doctor is the future automated-detect surface; the ADR is the current operator-readable explanation. Both are needed; deferring one to the other creates documentation gaps.

### D95. Downstream pillar impact

Per the ADR-0009 convention (every Pillar B + C ADR explicitly names cross-pillar impact); adapted from ADRs 0021 D83 + 0022 D88 modulo the Calendar-booking-specific adaptations rooted in ADR-0019's asymmetric two-phase shape (D66) + webhook-driven flow (D67) + deferred Pass G (D68).

* **Pillar D (reply + conversation handling).** Cal.com bookings ARE replies-in-the-Pillar-D-sense — the recipient's positive engagement is the canonical "they responded" signal. Pillar D's reply joiner correlates `calendar_booking_reply_received` events (per ADR-0025 D96's per-channel-prefixed naming convention; supersedes the generic `reply_received` placeholder this paragraph used pre-ADR-0025; reserved for the Cal.com comment-surface case which the v1 webhook doesn't yet consume) to their originating `calendar_booking_intent` via the URL-fragment intent_id per ADR-0019 D65 (`cb_<ULID>`). **The cap rule's enforcement at link-share time does NOT affect this surface** (the rule fires at intent-time, not at booking-time; Pillar D's correlator queries the event stream regardless of whether the cap fired). Pillar D's win-attribution metric reads `calendar_booking_confirmed` events (recipient action) — the cap's intent-counting semantic per D91 does not interfere; both event types flow to Pillar D independently. The cap rule's `policy_blocked` event with `rule: "calendar-booking-daily-cap"` + `channel: calendar` is a Pillar D signal that the operator is about to share another link in a saturated batch — Pillar D may emit a "consider pausing" advisory event if observed in conjunction with low `_confirmed` rates.

* **Pillar E (discovery quality + lineage).** No direct interaction. Discovery doesn't emit `cost_incurred` with `source="calendar_booking"` — that source is reserved for the Calendar booking dispatcher's per-share cost emission. Pillar E may add its own `BudgetWindowCapRule` instances filtering by discovery-source values (`source: pdl`, `source: apollo`); the per-channel migration shape composes. Pillar E's `discovery_lineage:` blocks (per ADR-0019 D70) may include a `discovered_via_calendar:` field that ties to a Pillar C `calendar_booking_confirmed` event — the cross-pillar query is one join, no Pillar C schema change.

* **Pillar F (voice corpus + draft quality).** No direct interaction. Pillar F's voice-fidelity scoring operates on touch body content (the cover message wrapping the booking URL). The dispatcher's URL-fragment intent-id marker per ADR-0019 D65 lives in the URL — NOT in free text — so Pillar F's voice-scorer doesn't need a marker-stripping step (the LinkedIn / Twitter marker-stripping discipline doesn't apply for calendar bookings). Voice-fidelity-scoped policy rules (e.g. "block sends whose voice-fidelity score is below X") may need new rule classes — orthogonal to Week 10's per-channel cap.

* **Pillar G (observability).** OTel + Prometheus will emit per-rule metrics; the `calendar-booking-daily-cap` rule produces `policy_blocked` events with `rule: "calendar-booking-daily-cap"` + `channel: calendar` (per ADR-0014 D33's channel-on-every-event invariant). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=calendar-booking-daily-cap` without new code (per ADR-0001). Pillar G's dashboards group by `rule:` field — the per-channel cap rules surface as distinct rows in the per-rule firing-rate dashboard. **Pillar G's link-share-to-booking funnel metric (per ADR-0019 D70) is unaffected by the cap's intent-counting semantic** — both the `_intent` and `_confirmed` event streams flow to Pillar G independently; the cap-firing event is a third signal that Pillar G dashboards alongside the funnel. Operators see a triple-stack of "shared today / booked today / cap-fired today" in their Pillar G dashboard — the operator-side-runaway-loop framing surfaces as "cap-fired-N-times-this-week" Pillar G can chart over time.

* **Pillar H (daemon + scheduled jobs).** Pre-API-call gating (per ADR-0006 §"Where budget rules fire") may consume the same per-channel rule at additional gates. **The webhook-driven asymmetric shape means the daemon does NOT poll Cal.com** (per ADR-0019 D68 — Pass G is DEFERRED; the webhook IS the canonical recovery surface; the daemon doesn't add a periodic-reconcile Cal.com query). The cap rule's enforcement at link-share time is the only Pillar H-relevant interaction. Pillar H's bulk-send workflow per-Person threading may want a per-channel BudgetWindowCapRule instance evaluated AT JOB-DISPATCH time (vs. AT SEND time) — Pillar H's job-dispatch layer composes with the existing rule via the same RULE_REGISTRY. No engine change. Pillar H's per-channel throttling layer should treat Calendar independently from LinkedIn + Twitter — the operator's Cal.com calendar surface is distinct from LinkedIn MCP's + Twitter cookie-scrape MCP's per ADR-0019 D65; the daemon's per-channel worker budgets compose with the `source="calendar_booking"` cost emission's separate accounting.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant policy directories; each tenant's `cooldowns.yml` gets the Weeks 7-11 migrations independently. The doctor's refuse-on-pending applies uniformly. The CLI's `python -m orchestrator.migrations apply` lands here (deferred from ADR-0012 D20). Pillar I doctor preflight: the §"Existing-operator seed" Shape 3 (renamed + dual-rule transitional state) is the natural detect surface — the doctor scans operator policy files for rules with overlapping `source:` + `block_when.channel:` + `type:` and warns when more than one rule fires on the same event class. Pillar I's CLI may also surface the deferred **`python -m orchestrator.cal_com check-webhook` validator** per ADR-0019 D66 — operators discovering "my webhook secret is misconfigured; that's why my Calendar booking cap is firing on intents but my Pillar G dashboard shows zero confirmed bookings" via the future ergonomic. The cap rule is **orthogonal** to the webhook validator; the cap fires at link-share time regardless of webhook state.

* **Pillar J (security + compliance).** GDPR-forget on a policy file doesn't typically apply (rules don't contain PII). A policy migration that removes a deprecated rule class is structurally reversible — `is_reversible=True` carries. Per-tenant rule deletion as part of an account-forget operation is a Pillar I + J intersection — neither Weeks 7-10 ship it. Calendar-booking-specific: the `calendar_booking_url` field is potentially-PII per ADR-0019 D70 (it contains the recipient's Person-derived intent_id); the cap rule does NOT consume the field (it filters on `source:` + `channel:`, not per-Person identifiers), so Pillar J's forget tooling operates orthogonally.

**Rejected D95 alternatives:**

- **Defer downstream pillar impact to the consolidated Pillar I doctor.** **Rejected** because:
  - Every ADR since 0014 has named cross-pillar impact explicitly (per the ADR-0009 convention). Skipping for Week 10 would break the precedent + force a future reader to reconstruct the impact from absent context.
  - Cross-pillar impact is structurally similar to ADR-0022 D88 — restating it explicitly with Calendar-booking-specific adaptations forces the explicit per-channel-correctness check; ADRs 0021 D83 + 0022 D88 both ship their own "Rejected DN alternatives:" subsections precisely because the §Downstream pillar impact framing has decision-making structure that deserves the rejected-alternatives treatment.

- **Mark cross-pillar impact identical to ADR-0022 D88 by reference, no restatement.** **Rejected** because:
  - The Calendar-booking-specific adaptations (Pillar D's `cb_<ULID>` URL-fragment intent-id correlator vs Twitter's `tw_dm_thread_id`; Pillar G's link-share-to-booking funnel metric specifically unaffected by the cap's intent-counting semantic per D91; Pillar H's webhook-driven asymmetric shape per ADR-0019 D66 + deferred Pass G per D68 — distinct from Twitter's cookie-scrape MCP rate-limit pool; Pillar I's `check-webhook` validator deferral per ADR-0019 D66 vs Twitter's `check-cookies` ergonomic per ADR-0018 D59) are not identical to the Twitter DM version. Restating with adaptations forces the explicit per-channel-correctness check.
  - ADRs should be self-contained per the §D94 rationale — a reader looking up "what does Week 10 do across Pillars D-J?" should get a self-contained answer without chasing ADR-0022 + ADR-0021 references.

- **Add a new Pillar K (compliance audit) row anticipating future regulatory needs.** **Rejected** because:
  - PILLAR-PLAN does not include a Pillar K; introducing one in a Week 10 ADR is scope creep beyond the migration. Future ADRs covering compliance shapes belong in their own ADR sequence.
  - Pillar J already covers GDPR-forget + per-tenant rule deletion per the existing pillar definition; expanding into a Pillar K would duplicate the existing surface without adding analytical clarity.

- **Collapse the per-pillar bullets into a single "no significant downstream impact" sentence + a forward-reference to Pillar I doctor.** **Rejected** because:
  - The Calendar-booking-specific interactions ARE substantive — Pillar D's reply correlator queries the same event stream the cap reads; Pillar G's funnel metric specifically depends on the cap NOT interfering (D91's intent-counting semantic is load-bearing for the funnel-conversion observability); Pillar H's webhook-driven shape per ADR-0019 D68 specifically means the daemon does NOT poll Cal.com (an absence-of-interaction worth naming explicitly so a future Pillar H contributor doesn't add a periodic-reconcile pass that would conflict with the webhook surface). The per-pillar elaboration forces these interactions to be surfaced explicitly rather than discovered later.
  - The future Pillar I doctor can't substitute for the per-ADR-time explicit framing — the doctor is a runtime tool; the ADR is a design-time artifact.

## Alternatives considered

### Alternative 1: Skip Week 10 + bundle Calendar booking cap into Week 11's cross-channel migration

Defer the Calendar booking cap to Week 11 (the cross-channel cooldown week) — bundle the per-channel + cross-channel rules in one mega-migration. **Rejected** because:

- Per ADRs 0020 Alternative 3 + 0021 Alternative 1 + 0022 Alternative 1 (all rejected): per-week shipping discipline is the project's load-bearing process. A bundled migration would be a single 2+-week commit that's hard to review per-section.
- The cross-channel cooldown rule (Week 11) has a DIFFERENT shape than per-channel caps (it uses `CrossChannelTouchRule` per ADR-0003, not `BudgetWindowCapRule`; it adds TWO rules in one migration per the bidirectional shape). Bundling them conflates rule classes — fixing one would force the other into the same commit's review window unnecessarily.
- Operators with Calendar booking dispatchers (Week 6) shipped 2026-05-22 — operators on the Week 6 commit + before Week 11 have weeks-to-months of unprotected calendar-link-sharing. The per-week shipping discipline minimizes the unprotected window per channel.

### Alternative 2: Per-Person Calendar booking cap (`budget.per-person-cap` filter, not `budget.window-cap`)

Use the `BudgetPerPersonCapRule` shape (ADR-0006) — "max N booking links per Person per lifetime" — instead of the window-cap shape. **Rejected** because:

- The failure mode the rule mitigates is OPERATOR-side runaway loop, which is aggregated across all recipients. A per-Person cap doesn't constrain operator-side volume; an operator could be at 1 booking link per Person but 50 booking links/day total + still trigger the runaway-loop failure mode.
- Per-Person caps belong in a separate rule (e.g. `calendar-booking-per-person-cooldown`) addressing a different failure mode (don't pester the same recipient with multiple booking links — recipient-spam-flag aggregation). Conflating the two rule shapes muddies the policy file's per-rule purpose.
- The factory can ship BOTH a per-Person cooldown AND a daily window cap — they're complementary. Week 10 ships the daily window cap; the per-Person cooldown for Calendar bookings is a future ADR if the use case surfaces.

### Alternative 3: Reuse Week 9's policy/0004 — drop in `calendar_booking` rule into the same migration

Add the Calendar booking cap rule as a second `RULE_BLOCK_TEXT` inside Week 9's policy/0004 migration; rename to `0004_add_tw_dm_and_calendar_caps`. **Rejected** because:

- Per ADR-0020 Alternative 3 (mega-migration alt) + ADR-0009 D2 (sequential ID convention): each migration is independently reversible at the migration level. An operator who wants to roll back just the Calendar booking cap while keeping the Twitter DM cap needs them as separate migrations.
- The migration was already shipped (commit `c12c636`); modifying it post-ship breaks the framework's append-only migration discipline (per ADR-0009 D4 + D7).
- Future per-channel migrations (Week 11's cross-channel cooldown) each ship as their own migration — bundling Week 10 with Week 9 would have to also bundle every future per-channel cap, defeating the per-week cadence.
- Week 10's window-unit divergence (`window_hours: 24` vs Week 9's `window_days: 7`) makes the bundling structurally messy — the two rules can't share a `RULE_WINDOW_DAYS` constant; they'd need separate per-rule constant groups in the same migration module.

### Alternative 4: Migration also emits a `migration_event` to record the per-channel-cap activation

Per ADR-0010 D17 / ADR-0020 Alternative 4 / ADR-0021 Alternative 4 / ADR-0022 Alternative 4 (all rejected): migrations could emit a `migration_event` audit-trail event. **Rejected** by inheritance:

- Policy migrations are explicitly ledger-silent per ADR-0012 I5. Week 10 inherits the posture.
- Pillar G's observability layer is the future home for per-migration metrics on non-ledger categories.

### Alternative 5: Migration writes a `calendar-booking-daily-cap` rule with both `source: calendar_booking` AND a wildcard for future Calendar event-types

Construct a single rule that aggregates `calendar_booking` + any future `calendar_*` sources into one daily cap. **Rejected** because:

- The `BudgetWindowCapRule` (ADR-0006) accepts a SINGLE `source:` value per instance; wildcard-source matching would require a new rule class (e.g. `BudgetWindowMultiSourceCap`). Schema change → bump version → coordinate engine update → scope creep against content-additive migration. Same rationale as ADRs 0021 Alternative 5 + 0022 Alternative 5.
- Per ADR-0015 D40's split-source convention: operators want per-action visibility on caps. Aggregating sources hides the per-action breakdown in the `policy_blocked` event stream (Pillar G's per-rule dashboard would surface a single "calendar-combined-cap" row instead of distinct ones for each Calendar action class).
- The Calendar dispatcher currently has only one action class (link share per ADR-0019 D69 — no group-booking-link discrimination yet). A future Pillar F may add a Calendar group-booking action class (per ADR-0019 D70's deferred case); that future ADR would ship its own per-action cap migration following the established pattern. Bundling now would be premature.

### Alternative 6: Ship the Calendar booking cap as a WEEKLY cap matching Weeks 7-9 for cross-channel consistency

Use `window_days: 7` + `max_units: 50` (~7/day average) to maintain consistency with the Weeks 7-9 weekly-window pattern. **Rejected** because:

- The failure mode being mitigated (operator-side runaway loop) is structurally DAILY, not weekly. A dispatcher in a bad loop produces 50 share events in 4 hours; the operator-pain is inflicted within hours, not over a week. A weekly window would catch the cumulative-across-week scenario (operator gradually over-shares 70+ links over a week) which is NOT the failure mode the cap exists to prevent.
- Cross-channel consistency in window-unit is operator-mental-model-coherence — but Week 10's failure mode is genuinely different (operator-side, not platform-side). The cross-channel-consistency argument that justified Week 9's `window_days: 7` (matching Week 8) does NOT apply when the underlying failure mode warrants different windowing.
- The factory file's Rule 9 (Apollo daily cap) establishes the daily-window precedent independently — operators reading the factory file see daily caps for daily concerns + weekly caps for weekly concerns. The window-unit choice tracks the failure-mode framing.

### Alternative 7: Count `calendar_booking_confirmed` events (recipient action) instead of intents

Make the cap fire only when 10 recipients have actually booked in the rolling 24-hour window. **Rejected** per D91's analysis:

- Defeats the operator-side-runaway-loop framing (D89). The cap should refuse BEFORE the operator has shared 50 links, not AFTER 10 recipients have booked.
- Incorrectly penalizes the high-success-rate operator — sharing 10 links + all 10 recipients booking is the optimal outcome; the cap should not fire on optimal-outcome days.
- Requires a new rule class or schema-changing migration; scope creep against the content-additive shape.

## Consequences

### Positive

- **Operators using Calendar booking dispatcher (Week 6 onward) get operator-side-runaway-loop protection automatically** when they run the next batch of pending migrations. The 10/day default is a safe starting point for the median operator; operators tune via the one-line YAML edit per D74's name-match idempotence preserves tuning.
- **The migration is content-additive, not schema-changing** (D75/D76 inherited from ADR-0020 through ADR-0021 + ADR-0022). Files stay at their pre-migration version; the engine's SUPPORTED set is unchanged; no flag-day risk.
- **Per-channel symmetry of the factory template** — Rule 12e documents the Calendar booking cap shape alongside Rules 12b (LinkedIn invite) + 12c (LinkedIn DM) + 12d (Twitter DM). New operators reading the factory file see one example per channel-action combination Pillar C delivers.
- **The first per-channel migration with a DAILY window AND the operator-side-runaway-loop failure-mode framing.** Weeks 7-9 all share weekly windowing + platform-side-enforcement framing; Week 10 demonstrates the framework's flexibility — the same migration shape composes with different window units + different failure-mode framings. Future per-channel migrations (Pillar D / E / F additions) inherit the precedent that window unit + failure-mode framing are migration-author-deliberate choices, not framework constraints.
- **Pillar C exit criterion progression.** Week 10 closes the Calendar booking cap gap; Week 11 delivers the cross-channel cooldown. After Week 11 Pillar C's per-channel policy coverage is complete.
- **The `add_rule_block_text` + `remove_rule_block_text` primitives compose with the daily-window form unchanged.** The primitives are window-unit-agnostic — they operate on text-level YAML, not on rule-class semantics. Week 10's `window_hours: 24` exercises the primitive's existing surface; the test `TestEngineIntegration::test_engine_loads_migrated_file` pins the engine's correct parse of the hours form.

### Negative

- **Operators with high Calendar booking volume (~15-20/day routinely) will hit the 10 default + need to tune up.** The tuning is a one-line YAML edit, but it's friction the operator only discovers when the cap fires for the first time. Documented in §D89 + the migration's notes; doctor preflight (Pillar I) could plausibly observe the operator's actual `cost_incurred.source=calendar_booking` volume + suggest a tuned value in a future iteration.
- **The Shape 3 (renamed) transitional state** requires operator action to deduplicate when the migration adds the canonical-named rule alongside the operator's renamed version. Same posture as Weeks 7-9; documented in §D94.
- **The factory `cooldowns.example.yml` grows by ~50 lines** for Rule 12e — slightly more than Rule 12d's ~35 lines because the operator-side-runaway-loop framing needs explicit explanation. Operators tracking the factory across versions via git see a new commented block. Acceptable cost for the per-channel-symmetry + framing-clarity benefit.
- **The operator-side-runaway-loop framing in Rule 12e's comment is genuinely new to Pillar C** — operators reading the factory file from Week 7 → Week 10 see four per-channel cap examples, three of which name platform-side enforcement + one of which names operator-side-runaway-loop. The asymmetry is intentional (it tracks the actual failure modes); operators who skim the factory file may notice the framing shift + investigate ADR-0023 for the rationale.

### Neutral / observability

- The migration logs at INFO with `affected_count` + `already_present` counts. The runner's pending / dry-run / apply reports surface the migration ID + description as expected.
- Policy migrations remain ledger-silent (no `migration_event` events) per ADR-0012 I5; Pillar G is the future home for per-migration metrics on non-ledger categories.
- The rule's `policy_blocked` event shape is unchanged from existing budget-window-cap rules (per ADR-0006 §"Budget blocks emit the standard `policy_blocked` event"). The funnel CLI's `--breakdown gate_reason` view surfaces firings as `gate_reason=calendar-booking-daily-cap` without new code.

## Compliance with invariants

- **I1 (single source of truth):** Policy YAML remains the SoT for "what rules are active" (per `docs/SOURCES-OF-TRUTH.md`). The migration writes to that SoT — no competing source.
- **I2 (two-phase commit):** Not applicable — policy migrations are internal state evolution, not external side effects. Per-file atomicity (tmp-then-rename + fsync via `write_policy_file_atomic`) is the migration-framework analog. Same posture as ADRs 0011 + 0012 + 0020 + 0021 + 0022.
- **I3 (schema versioning):** The migration does NOT bump the file's `version:` field (D75 inherited from ADR-0020 through ADRs 0021 + 0022 — content-additive migrations don't bump). The engine's `SUPPORTED_POLICY_SCHEMA_VERSIONS` remains `frozenset({1, 2})` — no extension required.
- **I5 (observable by default):** Every apply + downgrade logs at INFO with `affected_count` + already-present counts. Doctor's WARN-on-pending surfaces the migration ID. Per-channel cap firings emit standard `policy_blocked` events with `rule: "calendar-booking-daily-cap"` + `channel: calendar`.
- **I6 (tests prove invariants):** `tests/test_migrations_policy_0005.py` (60 tests) covers surface compliance, apply / dry-run / downgrade paths, idempotence (canonical-name + operator-renamed + already-present), refuse-loud on every failure mode, runner integration, engine integration (the rule loads + instantiates as `BudgetWindowCapRule` with `window_hours=24`), round-trip byte-identical on the real factory template, coexistence with Weeks 7-9's prior per-channel cap rules (the cross-migration coexistence QUAD per Weeks 8 + 9's review carry-forward — `test_coexists_with_invite_cap_rule` + `test_coexists_with_dm_cap_rule` + `test_coexists_with_tw_dm_cap_rule` + extended `test_coexists_with_all_prior_per_channel_caps`), four-way coexistence assertion (all four per-channel caps cohabit a single file with pairwise-distinct (source, channel) tuples), the NO-stale-source-warning invariant per D93, AND the window-unit divergence pins (`test_uses_window_hours_not_window_days` + `test_engine_loads_rule_with_window_hours` + `test_rule_uses_units_mode_not_usd_mode`).
- **I7 (cost is a first-class concern):** Policy migrations do not emit `cost_incurred` events. The migration's rule, once active, consumes `cost_incurred` events with `source="calendar_booking"` per ADR-0006's existing contract + ADR-0019 D65.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains the ADR-0023 row. `docs/PILLAR-PLAN.md` §6 Pillar C row extends to "Week 10 ✓."

Does not weaken any invariant. The migration is structurally additive: a new rule entry under existing shapes, leveraging existing rule classes (`BudgetWindowCapRule` with the existing `window_hours:` parameter), with existing event schemas.

## Existing-operator seed

Per §D94 above, ADR-0020's three §D77 operator shapes reduce to two for Week 10 (same pattern as ADRs 0021 §D82 for LinkedIn DM + 0022 §D87 for Twitter DM):

- **Shape 2 (canonical name, correct `source: calendar_booking`):** the migration skips. No operator action needed.
- **Shape 3 (renamed):** the migration adds the canonical-named rule. Operator should review + delete one of the two overlapping rules to clean up the dual-enforcement state.

Shape 1 (canonical name, stale source) does NOT apply — there has never been a pre-Week-10 factory-shipped Calendar booking daily cap rule, so no operator could have copied a stale shape. Per D93, the migration is silent on operator-hand-written rules with non-canonical source values (those are operator-deliberate; not stale-from-factory).

For operators who want to skip the migration entirely (e.g. "I never use Calendar booking dispatcher; don't add this rule to my files"), the existing-operator seed pattern per ADRs 0014 D36 + 0015 D41 + 0020 §"Existing-operator seed" + 0021 §"Existing-operator seed" + 0022 §"Existing-operator seed" applies:

```python
from datetime import datetime, timezone
from orchestrator.migrations.state import (
    MigrationState, mark_applied, save_state_atomic,
    load_state, DEFAULT_STATE_DIR,
)
from orchestrator.migrations.types import MigrationCategory

state = load_state(DEFAULT_STATE_DIR)
now = datetime.now(timezone.utc)
mark_applied(
    state, MigrationCategory.POLICY, "0005_add_calendar_booking_daily_cap",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `policy/0005` as applied; `apply()` skips it; the operator's `cooldowns.yml` files stay unmodified.

**Recommended posture per operator profile:**

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero Calendar booking history) | Run `apply()` normally. The migration writes the rule with the safe default; if you never share booking links the rule fires zero times. |
| Existing operator who uses Calendar booking with normal volume (~3-5/day) | Run `apply()` normally. The 10/day default gives 2-3x headroom for your normal cadence + catches runaway loops at ~10x normal. No tuning needed. |
| Existing operator with high Calendar booking volume (~15-20/day routinely) | Run `apply()` normally + tune `max_units:` in your operator-installed `cooldowns.yml` up to 25 (or your observed daily-max-with-headroom). The cap is operator-deliberate; the factory default targets the median operator. |
| Existing operator in very-low-volume warm-up phase (~1-2/day) | Run `apply()` normally OR tune `max_units:` down to 5 for tighter operator-side discipline. The default of 10 is safe; 5 is the operator-deliberate option for very-low-volume operators. |
| Existing operator who does NOT use Calendar booking + does NOT want the rule in their files | Seed `policy/0005` per the snippet above. Your `cooldowns.yml` stays untouched. |
| Yang (current sole operator, as of 2026-05-22) | Recommended: run `apply()` normally. Yang's current Calendar booking cadence is well under 10/day; the default is conservative + appropriate for the current operator. |

## Migration / rollout

The Week 10 migration is `policy/0005_add_calendar_booking_daily_cap`. Rollout shape:

1. Operator pulls Week 10 code. Engine code unchanged (D76 inherited: no SUPPORTED set extension). Pre-existing policy files (at v2 post-policy/0001) continue to load fine. Doctor preflight surfaces `policy/0005` as pending.

2. Operator runs `python scripts/doctor.py` → sees:
   ```
   ⚠ migrations             N pending: ..., policy/0005_add_calendar_booking_daily_cap
   ```

3. **Quiesce concurrent writers if any** (per ADR-0012 D21):
   * Close editor sessions on policy YAML files.
   * Stop any daemon that reloads policy on SIGHUP (Pillar H future).

4. Operator runs dry-run preview:
   ```python
   from orchestrator.migrations import MigrationRunner, MigrationCategory
   runner = MigrationRunner()
   preview = runner.dry_run(MigrationCategory.POLICY)
   ```
   The preview reports affected_count = (number of operator policy files that don't yet have the canonical rule).

5. Operator applies for real:
   ```python
   runner.apply(MigrationCategory.POLICY)
   ```
   Each policy file's `rules:` list gains one new entry at the end (after Weeks 7-9's per-channel caps, if present).

6. Operator inspects the migrated file:
   ```bash
   tail -10 ~/.outreach-factory/policies/cooldowns.yml
   #   - name: calendar-booking-daily-cap
   #     type: budget.window-cap
   #     block_when:
   #       channel: calendar
   #     source: calendar_booking
   #     window_hours: 24
   #     max_units: 10
   #     reason: "Calendar booking daily cap (...)"
   ```

7. The engine reloads `cooldowns.yml` on next dispatcher invocation. The rule joins the active rule set. Calendar booking link shares from this point forward are gated by the per-day cap.

The factory `cooldowns.example.yml`'s commented `Rule 12e` ships as part of Week 10's commit. Operators copying the factory template in the future see the documented Calendar-booking-cap shape with the operator-side-runaway-loop framing inline.

Doctor preflight does not need to change for this ADR — the rule is shape-identical to other `budget.window-cap` rules, which doctor already validates structurally. The window-unit divergence (`window_hours: 24` vs Weeks 7-9's `window_days: 7`) doesn't affect doctor's shape validation; the engine accepts both forms per ADR-0006.

A CLI (`python -m orchestrator.migrations apply`) remains deferred to Pillar I OSS bring-up.

The migration is reversible — `runner.rollback(MigrationCategory.POLICY, "0005_add_calendar_booking_daily_cap", allow_rollback=True)` removes the canonical-named rule. Operators rarely invoke; the defense-in-depth `allow_rollback=True` flag (ADR-0009 D4) makes accidental rollback a deliberate operator action.

## References

- ADR-0001 (policy engine architecture) — `policy_blocked` event shape; `RULE_REGISTRY` discriminator + `BudgetWindowCapRule` consumer.
- ADR-0003 (channel as first-class policy predicate) — `block_when.channel:` semantics consumed by the migrated rule.
- ADR-0006 (budget rules + cost_incurred event) — `BudgetWindowCapRule` units mode + `cost_incurred` schema. The rule the migration adds is an instance of this class. ADR-0006 §"Three concrete rule classes" establishes the `window_hours:` AND `window_days:` parameters as equivalent — Week 10 exercises the hours form for the first time in the per-channel cap migration sequence.
- ADR-0008 (LinkedIn weekly invite cap migration from hardcoded constant to policy rule) — the original cap rule shape that established the per-channel-cap pattern; Weeks 7-10 are sequential applications.
- ADR-0009 (migration framework foundation) — D1-D7 + the per-category ADR-per-dispatcher convention.
- ADR-0010 (ledger migrations) — `migration_event` audit-trail emission is ledger-specific; policy migrations remain ledger-silent.
- ADR-0011 (vault migrations) — surgical-edit precedent for in-place YAML rewrites.
- ADR-0012 (policy migrations — surgical YAML rewrite) — the policy-migration architecture this ADR builds on.
- ADR-0014 (channel-as-event-field invariant) — D33's "every policy_blocked event MUST stamp channel" invariant.
- ADR-0015 (Pillar C LinkedIn-invite dispatcher) — D40's split-source convention. The migration's `source: calendar_booking` is the Calendar booking portion of the split.
- ADR-0016 (Pillar C LinkedIn-DM dispatcher) — D43's `source="linkedin_dm"` emit convention (precedent for the per-channel source-naming pattern Week 10's `source="calendar_booking"` follows via ADR-0019 D65).
- ADR-0018 (Pillar C Twitter-DM dispatcher) — D58's `source="twitter_dm"` emit convention + `channel="twitter"` value (precedent for the per-channel pattern Week 10's calendar channel applies independently).
- ADR-0019 (Pillar C Calendar-booking dispatcher) — D65's `source="calendar_booking"` emit convention + `channel="calendar"` value (the rule's `source:` + `block_when.channel:` fields match exactly); D66's asymmetric two-phase shape (the cap fires at intent-time per D91); D67's HMAC webhook verification (orthogonal to the cap); D68's deferred Pass G (the webhook is the canonical recovery surface; the cap doesn't add a periodic-reconcile concern); D70's downstream pillar impact (D95 adapts to Week 10's per-channel scope).
- ADR-0020 (Pillar C Week 7 — per-channel policy migrations) — D72-D78. ADR-0023 inherits the structural decisions through ADRs 0021 + 0022.
- ADR-0021 (Pillar C Week 8 — LinkedIn weekly DM cap) — D79-D83. ADR-0023's D93's NO-stale-source posture is identical to D81's; D94's existing-operator seed reduces to Shape 2 + Shape 3 (same posture as D82).
- ADR-0022 (Pillar C Week 9 — Twitter weekly DM cap) — D84-D88. ADR-0023 inherits the Twitter-DM-specific decisions modulo the Calendar-booking-specific adaptations (D89's failure-mode framing inverts to operator-side-runaway-loop; D90's window unit changes to hours; D91's intent-vs-confirmed semantic explicit).
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost (the principle that justifies the conservative D89 default).
- `docs/PILLAR-PLAN.md` §1 — I1 (single source of truth), I3 (schema versioning), I5 (observable by default), I6 (tests prove invariants).
- `docs/PILLAR-PLAN.md` §2 Pillar C — scope + exit criterion. Week 10 ✓.
- `docs/PILLAR-PLAN.md` §6 Pillar C row — updated to "Week 1 ✓ + Week 2 ✓ + Week 3 ✓ + Week 4 ✓ + Week 5 ✓ + Week 6 ✓ + Week 7 ✓ + Week 8 ✓ + Week 9 ✓ + Week 10 ✓".
- `docs/SOURCES-OF-TRUTH.md` row "Cooldown / budget / window policy" — the SoT this migration writes to.
- `orchestrator/migrations/policy/_policy_io.py` — `add_rule_block_text`, `remove_rule_block_text` (landed Week 7; consumed unchanged by Weeks 8 + 9 + 10).
- `orchestrator/migrations/policy/migration_0005_add_calendar_booking_daily_cap.py` — the migration class + module-level constants (`RULE_NAME`, `RULE_TYPE`, `RULE_SOURCE`, `RULE_BLOCK_WHEN_CHANNEL`, `RULE_WINDOW_HOURS`, `RULE_MAX_UNITS`, `RULE_REASON`, `RULE_BLOCK_TEXT`). Note: `RULE_WINDOW_HOURS` (NOT `RULE_WINDOW_DAYS`) is the window-unit constant — the Week 10 structural divergence from Weeks 7-9.
- `orchestrator/migrations/policy/__init__.py` — `MIGRATIONS = [MIGRATION_0001_ADD_ENGINE_COMPAT, MIGRATION_0002_ADD_LI_INVITE_WEEKLY_CAP, MIGRATION_0003_ADD_LI_DM_WEEKLY_CAP, MIGRATION_0004_ADD_TW_DM_WEEKLY_CAP, MIGRATION_0005_ADD_CALENDAR_BOOKING_DAILY_CAP]`.
- `config-template/cooldowns.example.yml` — Rule 12e (commented Calendar booking cap example) added as part of Week 10. The existing Rule 9 (commented Apollo daily cap) is the precedent for `window_hours: 24` convention.
- `tests/test_migrations_policy_0005.py` — 60 direct migration tests including the four-way coexistence assertion (Weeks 7 + 8 + 9 + 10 caps cohabit a single file) + the `TestNoStaleSourceWarning` invariant per D93 + the window-unit divergence pins (`test_uses_window_hours_not_window_days` + `test_engine_loads_rule_with_window_hours` + `test_rule_uses_units_mode_not_usd_mode`).
- `tests/test_migrations_replay.py::TestFullBatchApply::test_full_apply_writes_all_per_channel_cap_rules_to_policy_file` — extended Week 10 to four caps. The sentinel-test "all" naming carries forward; the assertion shape grows by one (source, channel) tuple per week.
- Forward-references (planned):
  - **ADR-0024** (Pillar C Week 11) — Cross-channel email/LinkedIn cooldown migration (bidirectional). **Structurally divergent from Weeks 7-10** on a DIFFERENT axis from Week 10's: two rules per migration (bidirectional shape per ADR-0003); `cooldown.cross-channel-touch` rule class (NOT `budget.window-cap`); `consider_channels:` field (NOT `source:` field). ADR-0024 will diverge meaningfully from ADRs 0020-0023.
  - Pillar I doctor preflight enhancement — warn on §D94 Shape 3 (dual-rule transitional state). Same detect surface as ADR-0020's Shape 3.
  - Pillar I OSS bring-up CLI (`python -m orchestrator.migrations apply`) — the operator-facing command-line surface for the per-category dispatcher. Inherits all of Pillar B + C's primitives.
  - Pillar I OSS bring-up CLI (`python -m orchestrator.cal_com check-webhook`) — the Cal.com webhook-config validator deferred per ADR-0019 D66. Operators discovering "my webhook secret is misconfigured; the cap fires on intents but Pillar G shows zero confirmed bookings" via the future ergonomic. Orthogonal to the cap rule.
