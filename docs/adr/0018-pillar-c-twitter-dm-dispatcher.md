# ADR-0018: Pillar C Week 5 — Twitter DM dispatcher, retroactive backfill, and reconcile Pass F

- **Status:** Accepted
- **Date:** 2026-05-22
- **Pillar:** C (Multi-channel coherence — Week 5)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar C Week 1 (ADR-0014) shipped the convention-setting decisions every per-channel week composes against. Weeks 2 + 3 + 4 (ADRs 0015 / 0016 / 0017) shipped the first two per-channel dispatchers (LinkedIn invite + LinkedIn DM) + the first reconcile-pass week (Pass D + Pass E for LinkedIn recovery). Week 5 is structurally the **third per-channel week** + the **second reconcile-pass week** in one bundle (per ADR-0015 D42's per-week template — the per-channel weeks bundle dispatcher + backfill + reconcile in one week now that the recovery primitive shape is established by Week 4).

The seven concerns Week 5 resolves:

1. **Twitter has no first-class outreach surface today.** Pre-Pillar-C-Week-5 the operator either reaches Twitter contacts through the LinkedIn DM dispatcher (mis-channel), through email (when a Twitter contact happens to have a guessable address), or by hand-DMing via Twitter's web UI (no ledger trace). Pillar C's exit criterion requires a four-channel synthetic run; Twitter is the third channel that lands as a first-class dispatcher in Week 5.

2. **Twitter DM-to-non-follows behaves differently from LinkedIn DM-to-non-connections.** LinkedIn's message-request-inbox routing is silent at the API surface (ADR-0016 D44's refuse-loud rationale); Twitter's filtered-DM inbox is observable to the recipient (a notification badge surfaces; the recipient can approve or decline the message request from within their normal DM UI). The asymmetric-failure-cost calculus inverts: Twitter's filtered-DM path is a recoverable delivery channel, not a silent void. D60 pins the gate posture as **allow** — the opposite of ADR-0016 D44's refuse-loud — and names the rationale.

3. **Twitter has no public DM API for individual operators as of 2026.** Twitter's official v2 API gates DM access behind enterprise developer tier ($5000+/month minimum); cookie-scrape MCPs (`mcp__scraplingserver__*` shape) give DM send / read access without API credentials, at the cost of operator-cookie-capture friction + rate-limit fragility. D59 pins the MCP surface choice + names the operator-facing capture story (deferred to Pillar I OSS bring-up; Week 5 ships the protocol + a fake-injection test surface).

4. **The intent-id marker scheme generalizes verbatim.** Twitter DM bodies have a 10,000-char limit (vs LinkedIn DM's 8,000 — Twitter Premium accounts get even more room). The ~30-char zero-width-Unicode marker per ADR-0015 D39 / ADR-0016 D43 eats <0.5% of the budget. D58 reaffirms the marker shape; reconcile Pass F reads it back via the cookie-scrape MCP's recent-DMs surface.

5. **Per-action cost-event source split per ADR-0015 D40.** The Week 5 dispatcher emits `cost_incurred` events with `source="twitter_dm"` (distinct from LinkedIn invites' `linkedin_invite` + DMs' `linkedin_dm`). Operators who want separate per-channel caps configure distinct `budget.window-cap` rules; operators who want a combined cap configure a glob rule (future Pillar A extension). D58 reaffirms the convention.

6. **Reconcile generalization: the LinkedIn-shaped helper carries to Twitter.** The `_run_linkedin_intent_pass` shared core (ADR-0017 D48-D50) already parameterizes the six per-channel divergence points: intent type, outcome types, fetch callable, marker-scan callable, correlation field names, abort reason prefix. Twitter slots in cleanly. D62 pins the rename to `_run_channel_intent_pass` (the LinkedIn-only name is now misleading) + names the alternative (clone-per-channel-helper) it rejects.

7. **Existing operators have pre-Pillar-C Twitter DM history.** Yang's vault has no pre-Pillar-C Twitter touches (the channel never had a dispatcher); future OSS operators with hand-managed Twitter DM history can stamp `channel: twitter` + `sent: true` on retroactive touch notes and run `ledger/0005`. D63 instantiates the seed pattern for `ledger/0005`.

A vault migration `vault/0004_add_twitter_action_to_touch_notes` is **deferred** — Twitter has no invite-vs-DM ambiguity (Twitter DMs are the only Twitter outreach action), so the `linkedin_action:` field's rationale per ADR-0015 D38 doesn't generalize. D61 names the deferral + the future trigger (Pillar F quality scoring may need a per-touch `twitter_action:` discriminator for thread-mention vs DM distinction; if so, ship the migration then).

Risks this ADR mitigates by design: **R001 (dispatcher crash between intent and outcome)** — Pass F recovers the Twitter-specific gap; **R011 (cross-channel double-engagement)** — the Week 5 dispatcher's `tw_dm_confirmed` events fire the existing cross-channel rule (ADR-0003) the moment they land in the ledger. The synthetic-replay exit-criterion vehicle (`tests/test_multi_channel_coherence.py::TestTwitterDMChannel`) pins this end-to-end starting Week 5.

## Decision

### D58. Twitter DM event-type prefix `tw_dm_*`; cost-event source `twitter_dm`; intent-id marker via zero-width-Unicode in DM body

Pillar C Week 5 dispatcher emits two-phase events with the event-type prefix `tw_dm_*` (per ADR-0014 D33 — `tw_dm_intent` / `tw_dm_confirmed` / `tw_dm_failed` / `tw_dm_aborted`). Every event carries `channel: "twitter"` (distinct channel value from LinkedIn's; the cross-channel rule's `consider_channels:` matches against the channel string, so `consider_channels: [email, linkedin, twitter]` covers all three).

The cost-event source is `source="twitter_dm"` per ADR-0015 D40's split-source convention. The dispatcher emits a single `cost_incurred` event per confirmed send with `amount_usd=0.0` + `units=1` (Twitter cookie-scrape is quota-bounded by the MCP's rate-limit, not USD-billed); operators who configure budget-cap rules against `source=twitter_dm` get per-channel daily/weekly throughput caps.

The intent-id marker scheme (per ADR-0015 D39 + ADR-0016 D43) carries verbatim: a zero-width-space-wrapped marker (`​outreach-intent:<intent_id>​`) is appended to the DM body before the MCP call. Reconcile Pass F (this ADR) reads the marker back via the cookie-scrape MCP's recent-DMs surface. The marker's length (~30 chars) eats <0.5% of Twitter's 10,000-char DM body limit; the dispatcher refuses-loud when the operator-supplied body + marker would exceed the limit (mirror of the LinkedIn DM path's body-length pre-flight per ADR-0016 D43).

**The reaffirmation pattern continues.** Every per-channel week's first decision in its ADR is the channel-event-naming + cost-source confirmation per ADR-0015 D42's template. Without the explicit reaffirmation, a Week 5 author who skimmed the templates could land on `twitter_dm_*` (verbose), `tw_*` (no action discriminator), or `x_dm_*` (Twitter rebrand to "X" — orthogonal; the channel value is `twitter` because the cross-channel rule's existing references say so). D58 forecloses.

### D59. Twitter MCP surface — cookie-scrape

The Week 5 dispatcher uses the cookie-scrape MCP surface (`mcp__scraplingserver__*` shape — or any equivalent the operator's environment exposes via the `TwitterClientLike` Protocol). The cookie-scrape variant gives DM send / read access without requiring Twitter API credentials (which gate on enterprise developer tier + $5000+/month at the official v2 surface); the rate-limit is the cookie-scrape's enforcement (~10 calls/minute per Twitter's anti-abuse threshold, lower than LinkedIn's ~30/minute).

**Why cookie-scrape and not the official Twitter API v2.** Three reasons:

1. **Cost.** Twitter's official DM API access is gated behind Enterprise tier ($5000+/month minimum, with multi-month commitments). Pillar C's exit criterion requires the framework to ship for solo operators + small teams who cannot justify that price point. The cookie-scrape MCP's per-operator cost is the time to capture cookies from a logged-in browser session — bounded, one-time, with re-capture friction on cookie expiration (typically every 30 days).

2. **Surface stability under Twitter's product changes.** The cookie-scrape MCP wraps the same web-UI surface human operators use; product changes affect both equally (and the MCP's maintainer updates the scraper when Twitter ships a UI revision). The official v2 API has had multiple major-version breaks since the Musk-era ownership change (DM endpoints have been deprecated, restored, gated, re-pricing — even Enterprise customers report instability). The scrape surface's drift cadence matches the operator's normal UI exposure.

3. **Operator agency.** Cookie capture is operator-deliberate — the operator logs into Twitter in their browser, copies cookies via the MCP's documented capture flow, configures the MCP. The dispatcher does NOT auto-discover cookies; an explicit configuration step is the operator's affirmative consent that their Twitter session is being used for outbound DMs. The API path's "give us your developer credentials" surface has the same consent shape with a different artifact + a vastly higher price point.

The `TwitterClientLike` Protocol (this ADR + `orchestrator/reconcile.py`) wraps whatever cookie-scrape MCP the operator's environment exposes. The reference adapter ships as `skills/send-outreach/scripts/twitter_client.py::build_reconcile_adapter` (Pillar I OSS bring-up's concern; tests inject fakes directly). The Protocol's two methods (`send_dm` + `list_recent_dms`) cover the two reconcile-relevant surfaces; the dispatcher uses `send_dm` only.

**Edge case: operator without cookie-scrape MCP access.** The dispatcher refuses-loud (`tw_client_unavailable` reason in `dedup_blocked`) when no adapter is wired. Pillar I OSS bring-up may ship a CLI prompt ("install the cookie-scrape MCP and configure cookies") for first-time operators; until then the failure mode is a clear ledger event the operator can act on.

### D60. Twitter follow-state gate posture — ALLOW

The Week 5 dispatcher's pre-flight gate sequence (after identity / no-twitter-handle / ledger-prior-send / policy.evaluate / lock acquire) does **NOT** include a follow-state check. Twitter DMs to non-follows route to the recipient's "Message Requests" tab (filtered DM inbox), which is operator-observable + recipient-recoverable (the recipient sees a notification badge + can approve the request to move the DM into their primary inbox).

* **`twitter_handle:` present on Person frontmatter** → gate passes; the send proceeds.
* **`twitter_handle:` absent** → gate refuses-loud with reason `no_twitter_handle`; same shape as LinkedIn's `no_linkedin_url` per ADR-0016.

No `twitter_followed:` field on Person frontmatter. No `allow_unfollowed=True` kwarg on `gated_tw_dm_one` — the gate doesn't enforce a follow check in the first place, so no override is needed.

**Why allow and not refuse-loud (the LinkedIn DM posture per ADR-0016 D44).** The asymmetric-failure-cost calculus inverts on Twitter because the failure mode inverts:

* **LinkedIn DM-to-non-connection failure mode (per ADR-0016 D44):** the MCP returns "success", the message lands in a silent message-request sub-inbox, the recipient may never see it, and the dispatcher would emit a `li_dm_confirmed` event for an effectively-undelivered send — biasing the cross-channel rule's downstream state.
* **Twitter DM-to-non-follow failure mode:** the MCP returns "success", the message lands in the recipient's filtered Message Requests tab, the recipient sees a notification badge in their primary DM inbox (Twitter's UX surfaces filtered requests), and the recipient can approve / decline / ignore on their own time. The cross-channel rule's downstream behavior (a 14-day-window block) is **correct** even if the recipient declines — the operator did make a meaningful outreach attempt; cooldown applies regardless.

**Why no advisory mode (warn-but-send).** Twitter's filtered Message Requests delivery is the canonical Twitter cold-outreach path. Warning on every send would create alert fatigue without operator-actionable signal. Operators who want to know whether a recipient is a mutual-follow before sending can consult Pillar F's pre-send quality scoring (future Week — `tier_score` extends with a `relationship_strength: mutual_follow | one_way_follow | no_follow` enrichment field); the gate stays clean.

**Counter-argument: filtered DMs have lower open / response rates than primary-inbox DMs.** True empirically. Mitigation lives upstream of the gate: Pillar F's quality scoring + register-aware drafting (the `cold-pitch` register's voice-fidelity scoring weights message-clarity higher for filtered-inbox deliveries). The gate's refuse-loud posture for LinkedIn DM was an asymmetric-failure-cost intervention; the cooldown-fires-correctly property holds for Twitter without that intervention.

**Counter-counter-argument: operators may want a "no DM to non-follows" guard.** The cooldown system (ADR-0003) already accommodates this: a `tier.match-rule` matching `follow_state: not_follow` + `block_when: {channel: twitter}` refuses operator-deliberately. Per-operator policy YAML is the right surface for per-operator gate divergence — not a hardcoded refuse-loud in the dispatcher.

### D61. Defer `vault/0004_add_twitter_action_to_touch_notes`

Week 5 ships **zero vault migrations**. The `vault/0003_add_linkedin_action_to_touch_notes` migration (ADR-0015 D38) was operator-deliberate for LinkedIn because LinkedIn touches have an invite-vs-DM ambiguity the filename heuristic addresses imperfectly. Twitter has no equivalent ambiguity:

* Twitter has one outreach action: send a DM.
* Twitter's web-UI surface does not expose "send a friend request" or "send a connection invite" as a separate action class (Twitter's "follow" action is not an outreach action — it's a feed subscription).
* The `twitter_action:` field has only one valid value (`dm`); the field would be uniformly populated with the same string.

**Why not ship the migration anyway for symmetry.** Three reasons:

1. **Operator clutter.** A uniformly-`dm` field would add zero discriminator power + visible noise to every Twitter touch note's frontmatter. Operators reading their own touch notes would see the field + reasonably ask "what's the alternative value? am I missing something?" The clutter has no upside.

2. **Migration framework load.** Every shipped migration adds maintenance burden — schema doc, ADR migration-rollout note, dry-run test, runner-state-file slot. Shipping a no-op-discriminator migration for the framework's symmetry would tax the framework for no operator-visible benefit.

3. **Future-trigger semantics.** If Pillar F's quality scoring later needs a per-touch action discriminator (e.g., a future "Twitter thread-mention" action class for replying-to-conversation outreach), the discriminator's introduction can ship at THAT point with the actual two values that need distinguishing. The vault migration would then meaningfully populate a field with operator-meaningful divergence. Shipping the field empty-now would force Pillar F to either re-purpose the field (semantic drift) or ship a `vault/00NN_extend_twitter_action_values` migration that adds the second value (the operator pays the migration cost twice).

D61 commits to the deferral. If Pillar F later needs the discriminator, it ships then per the **operator-deliberate-on-actual-need** discipline.

**Consequence for `ledger/0005`:** the migration's invite-vs-DM filter (compare to `ledger/0004`) is absent. Every `channel: twitter` + `sent: true` touch backfills to a `tw_dm_*` pair unconditionally. No `_classify_twitter_action` heuristic; no filename-pattern fallback. The simpler shape is correct because the ambiguity it would resolve doesn't exist.

### D62. Generalize `_run_linkedin_intent_pass` to `_run_channel_intent_pass`

The shared helper in `reconcile.py` that powers Pass D (`run_pass_d`) + Pass E (`run_pass_e`) is renamed to `_run_channel_intent_pass`. Pass F (`run_pass_f`) calls it with Twitter-specific arguments; the existing call sites (D + E) pass `channel="linkedin"` explicitly so the helper's `channel: "..."` event-stamp is no longer hard-coded.

**Why generalize and not clone.** Three reasons:

1. **The six parameterized dimensions are channel-agnostic.** The helper's existing parameters (intent type, outcome types, fetch callable, marker-scan callable, correlation field names, abort reason prefix) already accommodate per-channel divergence. The only LinkedIn-specific aspect is the hard-coded `channel: "linkedin"` event-stamp — adding a `channel:` parameter is one line. Cloning per-channel would copy the entire helper body for the one-line difference; the copy would be maintenance debt the moment a Pillar G observability refactor wants to stamp additional fields uniformly.

2. **OSS bring-up consolidation.** Pillar I's reference-implementation discipline minimizes duplicated logic — the operator-facing surface is the dispatcher + reconcile entry points; the shared helper is internal. One helper per recovery-shape is easier to document, version, and bug-fix than three near-identical helpers.

3. **Future-channel ergonomics.** Pillar D's hypothetical reply-correlation pass (Pass H, future) may reuse the same shape (walk intent-shaped events; query an external surface; emit a confirmed-or-aborted outcome). The generalized helper is the structural intervention against three more clones.

**Why not name it `_run_two_phase_recovery_pass` or `_run_periodic_intent_pass`.** Both names accurately describe the helper's behavior; both are wordier than `_run_channel_intent_pass`. The "channel" framing is the orienting concept (the helper's per-channel parameters dominate its interface), so the channel-centric name is the clearer match. The full docstring carries the "two-phase recovery" semantic; the function name carries the channel-parameterized framing.

**Migration shape:** the existing `run_pass_d` + `run_pass_e` callers pass `channel="linkedin"` explicitly + the new `channel="twitter"` arg flows from `run_pass_f`. The helper's internal `channel: "linkedin"` event-stamp becomes `channel: <param>`. Tests for Pass D + Pass E still pass without modification (the helper's external behavior is unchanged for those call sites).

### D63. Existing-operator seed for `ledger/0005_baseline_tw_dm_history`

Operators with pre-existing Twitter DM touches (future OSS operators with pre-Pillar-C Twitter history; Yang specifically has none as of 2026-05-22) may want to skip the retroactive backfill. Per ADR-0014 D36 + ADR-0015 D41 + ADR-0016 D46 + ADR-0017 D51 (the established convention), this ADR provides the §"Existing-operator seed" REPL incantation.

#### Skipping `ledger/0005` only

For operators who want their pre-Pillar-C Twitter DM ledger state preserved as-is (no `tw_dm_*` events emitted retroactively):

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
    state, MigrationCategory.LEDGER, "0005_baseline_tw_dm_history",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `ledger/0005` as applied; `apply()` skips it; the operator's Twitter DM history stays exactly as it was pre-Week-5 (touch notes + no `tw_dm_*` ledger events).

#### Recommended posture per operator profile

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero pre-Pillar-C Twitter DM history) | Run `apply()` normally. The migration emits zero events (no Twitter touches to walk); the migration_event audit trail records the no-op for continuity. |
| Existing operator who wants historical events preserved as-is | Seed `ledger/0005`. Pre-existing Twitter touches (if any) remain unstamped at the ledger level; new touches via the Week 5 dispatcher carry full two-phase events. |
| Existing operator who wants retroactive emissions for cross-channel rule activation | Run `apply()` normally. `ledger/0005` emits the backfill pairs; the cross-channel rule starts firing against historical Twitter DMs the moment a future LinkedIn or email send attempt evaluates against them. |
| Yang (current sole operator, as of 2026-05-22) | Recommended: run `apply()` normally. Yang's pre-Pillar-C Twitter DM count is zero (the channel didn't have a dispatcher); the migration is a no-op for the current operator. The seed-then-skip is operationally identical for Yang; the `apply()` path keeps the convention uniform across all four channels. |

**Week 5 does NOT ship a vault migration.** Per D61, the Twitter touch-note shape has no invite-vs-DM ambiguity that warrants a per-touch action field. Touch notes with `channel: twitter` + `sent: true` are unconditionally DM-classified; `ledger/0005` walks them all.

### D64. Downstream pillar impact

Per the ADR-0009 / 0010 / 0011 / 0012 / 0013 / 0014 / 0015 / 0016 / 0017 convention (every Pillar B + C ADR explicitly names cross-pillar impact):

* **Pillar D (reply + conversation handling).** Pillar D's reply joiner correlates `reply_received` events to their originating `tw_dm_confirmed` by `intent_id` AND by `tw_dm_thread_id` (Twitter's per-conversation correlator; the cookie-scrape MCP returns a thread_id on send + a matching thread_id on inbound). The Week 5 dispatcher stamps both on the confirmed event. Pillar D's joiner reads both for double-check robustness — same shape as Week 3's `linkedin_thread_id` correlation per ADR-0016 D47.

* **Pillar E (discovery quality + lineage).** No direct interaction. Pillar E adds `discovery_lineage:` blocks to Person frontmatter; per-touch DM fields are orthogonal. Pillar E's `discovery_lineage:` may include a `discovered_via_twitter:` field that ties to a Pillar C `tw_dm_confirmed` event — the cross-pillar query is one join, no Pillar C schema change.

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring operates on touch body content (the DM body). The Week 5 dispatcher's intent-id marker (D58) appends to the body; Pillar F's voice-scorer must strip the marker before scoring or the scorer would penalize the marker's "AI-shape" artifacts. The marker is at a known position (end of text) and surrounded by zero-width spaces — Pillar F's text-cleanup step strips it deterministically (same logic as Week 2's invite marker per ADR-0015 D42 + Week 3's DM marker per ADR-0016 D47). Pillar F's future `twitter_action:` discriminator (per D61's deferral) lands here if needed.

* **Pillar G (observability).** Pillar G's per-channel migration audit-trail dashboard reads `ledger/0005`'s `migration_event` event filtered by `channel="twitter"` per ADR-0014 D35; Week 5's diagnostic fields (`twitter_dm_pairs_emitted`, `twitter_dm_pairs_skipped`, `touches_without_person_match`) become per-migration observability rows. Pillar G's per-channel funnel dashboard reads `tw_dm_intent` / `tw_dm_confirmed` / `tw_dm_failed` / `tw_dm_aborted` events with `channel: twitter` per D33 — one query per funnel state, distinct from LinkedIn's funnel queries. Pillar G's per-pass last-run-clean status (Pass F adds a new row in `~/.outreach-factory/reconcile/status.yml`) becomes the per-Twitter-channel health indicator.

* **Pillar H (daemon + dispatcher).** Pillar H's per-stage parallelism limits become per-channel + per-action — Twitter DM throughput is independent from LinkedIn DM throughput because the MCP rate-limit pools are distinct (cookie-scrape vs LinkedIn MCP). The Week 5 `cost_incurred` event's `source="twitter_dm"` is the discriminator Pillar H's dispatcher uses to throttle independently. Pillar H's reconcile-worker runs Pass F in series with Pass D + Pass E (per ADR-0017 D48's serial-execution convention — the helper's rate-limit-pool-sharing concern is per-pass, not per-channel, but the worker-loop respects each channel's MCP boundary).

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel state isolation. The D63 existing-operator-seed block aggregates into Pillar I's CLI as `python -m orchestrator.migrations seed --pillar-c --channel twitter_dm` (or the looser `--pillar-c` aggregates every Pillar C ADR's seed blocks). The cookie-scrape MCP capture story per D59 is a Pillar I doc concern — the framework ships the Protocol; the per-environment adapter is operator-deliberate. Pillar I's CLI may surface a `python -m orchestrator.twitter check-cookies` ergonomic for cookie-expiration discovery (the typical 30-day re-capture cadence is operator-visible friction).

* **Pillar J (security + compliance).** GDPR-forget on a Person who has Twitter DM touches: the DM touch notes are deleted (Pillar J's forget tooling per ADR-0010's pattern), and per-Person `tw_dm_*` events are tombstoned. The Week 5 dispatcher's `tw_dm_thread_id` field is potentially-PII — Pillar J's forget tooling redacts it on tombstone. The `twitter_handle:` field per D60 is the operator's discovered identifier for the Person; Pillar J's forget tooling also redacts it.

## Alternatives considered

### D58-Alt1: Use `twitter_dm_*` (verbose) instead of `tw_dm_*` (compact)

Spell out the channel prefix to match the channel value (`twitter`) rather than the contraction. **Rejected** because:

* ADR-0014 D33 ships the contraction across all four channels (`li_invite_*`, `li_dm_*`, `tw_dm_*`, `calendar_booking_*`). The contraction is consistent — Defaulting to compact prefixes keeps event-type strings short for grep + logging readability + matches the ledger's existing `_INTENT_TYPES` / `_OUTCOME_TYPES` registrations (which already name `tw_dm_*` per Week 1's generalization).
* The contraction is consistent with Pillar A's `RuleContext.channel = "twitter"` (the channel field is spelled out for human-readability in the gate; the event-type prefix is compact for storage + filtering ergonomics — same discipline as LinkedIn).
* Spelling out one prefix would orphan the existing test corpus that asserts on the compact form (`tests/test_multi_channel_coherence.py::TestTwitterDMChannel`'s 4 Week-1 stub tests reference `tw_dm_*`; the ledger's frozenset entries are already `tw_dm_*`).

### D58-Alt2: Use `x_dm_*` to match Twitter's "X" rebrand

Adopt Twitter's 2023-onwards corporate rebrand into the event-type prefix. **Rejected** because:

* The product-rebrand is operator-visible but the framework's channel-value identifier (`twitter`) reflects the existing cross-channel rule's references + the API surface's hostnames (still `twitter.com` + `api.twitter.com` as of 2026); changing the prefix to `x_*` would diverge from the channel value.
* Future rebrands (Twitter has had two name changes since 2006; further rebrands plausible) would force more prefix changes. Stability of the identifier matters more than chasing brand updates.
* The `channel: "twitter"` value is what the cross-channel rule + the ledger's `last_send_for` query against — changing the prefix without changing the channel value would create dual representations the indexer must reconcile.

### D58-Alt3: Use a single `tw_*` prefix without action discriminator

Drop the `_dm_` infix because Twitter DMs are the only Twitter outreach action (per D61). **Rejected** because:

* ADR-0014 D33's catalog ships `tw_dm_*` explicitly — the action discriminator is structural symmetry across all four channels, not action-class-required-by-Twitter.
* Future Pillar F may add a Twitter thread-mention action class (D61's deferral case); the prefix `tw_thread_mention_*` would slot in naturally if the existing prefix already has the action discriminator. Dropping the infix now would force a future migration to rename `tw_*` → `tw_dm_*` to make room for `tw_thread_mention_*`.
* The contraction `tw_dm_` is two chars longer than `tw_` but ten chars shorter than `twitter_dm_`; the median position is the right one for grep ergonomics + structural-symmetry preservation.

### D59-Alt1: Use the official Twitter API v2 with Enterprise tier credentials

Skip the cookie-scrape MCP; require operators to acquire Enterprise developer access. **Rejected** because:

* The $5000+/month entry point is incompatible with Pillar I's solo-operator + small-team OSS targeting. The framework would ship a Twitter dispatcher that no individual operator can practically use.
* Enterprise DM access has had multiple deprecation cycles since 2022 (the Musk-era ownership shipped breaking API changes that even paying customers reported as production-blocking). The framework's reliability commitment is weaker the higher the per-operator cost; a price-sensitive adapter (cookie-scrape) is the lower-friction, lower-risk path.
* Operators who DO have Enterprise access can still configure their own `TwitterClientLike` adapter that wraps the official API; the Protocol is intentionally surface-agnostic.

### D59-Alt2: Use a Selenium-based browser-driver scraper

Run a headless browser session per send. **Rejected** because:

* Selenium adds heavyweight runtime dependencies (Chrome/Firefox binary + WebDriver), which Pillar I OSS bring-up's "single Python install" discipline rejects.
* Per-send browser-spin-up latency is 10-30 seconds (vs cookie-scrape's <2s); the bulk-send pattern would be operationally slow.
* The cookie-scrape MCP's HTTP-level scraping is what the headless-browser would do underneath anyway — Selenium is wrapping a wrapper. The MCP path is structurally closer to the surface.

### D59-Alt3: Use email-as-Twitter-DM (notification-email reply-back) as the transport

Twitter's notification emails for received DMs include a reply-back affordance (replying to the email sends the body as a DM reply). **Rejected** because:

* The reply-back path only works for replying to existing threads; cold outreach (the primary Week 5 use case) initiates new threads, which the reply-back path doesn't support.
* The reply-back-from-email surface is opt-in per recipient (the recipient must have email-reply enabled on their Twitter notification settings); silently fails for recipients who haven't enabled it.
* No round-trip correlation surface — the dispatcher couldn't read its own marker back because the outbound is email + the inbound is DM thread state, not the same surface.

### D60-Alt1: Refuse-loud on `twitter_followed: false` (mirror LinkedIn's D44)

Replicate ADR-0016 D44's refuse-loud posture for Twitter. **Rejected** because:

* The asymmetric-failure-cost calculus inverts on Twitter (filtered DMs are recipient-recoverable; the failure mode is "lower open rate" not "silent void"). Per the rationale in D60, refuse-loud forecloses legitimate cold outreach without operator-protective benefit.
* Operators who DO want a refuse-loud policy can write a cooldown rule that refuses on `tier.match-rule` with `block_when: {channel: twitter, follow_state: not_follow}`. The framework's policy YAML is the right surface for per-operator divergence.
* The dispatcher's hardcoded refuse-loud would be a system-wide intervention; the cooldown rule is operator-deliberate per-vault.

### D60-Alt2: Advisory mode (warn-but-send)

Print a stderr warning when the recipient isn't a follow, but proceed. **Rejected** because:

* Alert fatigue: warning on every Twitter DM send (Twitter's cold-outreach default is to non-follows) would surface a warning for nearly every send. Operators would learn to ignore the warning, defeating its purpose.
* The cross-channel rule's downstream behavior is correct regardless of follow state (cooldown applies; double-engagement is prevented). The warning would convey no operator-actionable information beyond the gate's existing logs.
* Operators who want pre-send signal can consult Pillar F's quality scoring or the `tier_score` (when shipped). The dispatcher's gate is the wrong place for advisory-only signal.

### D60-Alt3: Refuse-loud only on `twitter_followed: false` set by operator-manual stamping

Allow when the field is absent, refuse when explicitly false. **Rejected** because:

* The absent-field default conflates "operator hasn't checked" with "no follow relationship", silently treating the latter as the former.
* The operator-manual stamping per-Person ergonomic (mirroring D45's lazy-stamping discipline) would be friction without filtered-DM-failure-mode payoff. Twitter's filtered-DM path is observable; the LinkedIn lazy-stamping rationale doesn't generalize.
* Operators who DO want this behavior can write a policy rule (per D60-Alt1's mitigation); the dispatcher stays clean.

### D61-Alt1: Ship `vault/0004_add_twitter_action_to_touch_notes` for symmetry with `vault/0003`

Add a `twitter_action: dm` field on every Twitter touch note, mirroring LinkedIn. **Rejected** because:

* Twitter has no invite-vs-DM ambiguity (D61 rationale); the field would be uniformly populated, adding zero discriminator power.
* Visible noise in every Twitter touch's frontmatter without operator-meaningful divergence. The clutter has no upside.
* Symmetry-for-symmetry's-sake is the wrong design heuristic; per-channel migrations should ship when they solve a real operator-visible problem (per the asymmetric-failure-cost framing).

### D61-Alt2: Ship `vault/0004_add_twitter_handle_to_person_notes` for Person-level state

Walk Person notes + stamp `twitter_handle:` from a discovery surface (e.g., enrichment). **Rejected** because:

* No reliable bulk-discovery surface for Twitter handles. Operators stamp the field manually when they identify a Person's Twitter presence; the field is operator-deliberate-on-discovery, not bulk-derivable.
* The dispatcher reads the field directly; absent → refuses-loud per D60. The framework doesn't need to pre-populate it; the operator-manual stamping is the right shape (mirrors `linkedin:` field per Phase 5.5 conventions).
* Future enrichment integration (Pillar E) may add `twitter_handle:` discovery via Apollo / People Data Labs APIs; that integration ships as part of Pillar E, not as a Week 5 vault migration.

### D61-Alt3: Ship `vault/0004_initialize_twitter_state` with `twitter_state:` field initialization

Add a per-Person `twitter_state:` field that the dispatcher writes on send (`messaged`, `replied`, etc.) — mirroring `linkedin_state:`. **Rejected as a migration**, accepted as a **dispatcher writeback contract**:

* The field is dispatcher-time-discoverable (no value before the operator sends the first DM); a migration that initializes it to `null` on every Person adds clutter without operator benefit. Same rationale as D45's "no `vault/0004` for `linkedin_connected:` field initialization" in ADR-0016.
* The dispatcher's vault writeback per ADR-0014 + this ADR's writeback section stamps `twitter_state: messaged` on first send. The field is lazy-populated; reading-before-first-write produces `None` which the dispatcher accommodates.
* The dispatcher's writeback is the right surface; the migration would be redundant.

### D62-Alt1: Clone `_run_linkedin_intent_pass` to a Twitter-specific `_run_twitter_intent_pass` helper

Copy the helper body, adjust the channel-stamp + the parameter wiring. **Rejected** because:

* Three near-identical helper bodies would be maintenance debt — a Pillar G refactor that adds field stamping (e.g., a uniform `_run_id` correlation) would need to land in three places.
* The helper's parameter surface already accommodates per-channel divergence; renaming + adding one `channel:` parameter is one line of diff vs ~100 lines of cloned body.
* Future Pillar D Pass H (hypothetical reply-correlation pass) would clone-clone-clone — the structural intervention against three more clones is to generalize now.

### D62-Alt2: Keep `_run_linkedin_intent_pass` as-is + add a `_run_twitter_intent_pass` for Pass F specifically

A hybrid: keep the LinkedIn helper for D + E, add a Twitter-specific one for F. **Rejected** because:

* Same maintenance-debt concern as D62-Alt1 (two helper bodies for the same shape).
* The naming would be misleading after the addition — `_run_linkedin_intent_pass` would still be LinkedIn-only but the framework would have a `_run_twitter_intent_pass` of identical shape. Either both renaming or neither; both is the cleaner end-state.
* The rename-to-`_run_channel_intent_pass` consolidation is small (one rename + one parameter); the alternative gains nothing for the maintenance cost.

### D62-Alt3: Extract a `ChannelRecoveryHelper` class and have D + E + F all instantiate it

OO refactor: `class ChannelRecoveryHelper: def run(self, ...)`. **Rejected** because:

* The helper is internal — the channel-class is not consumer-facing surface. The function-with-named-args shape is simpler than a class-with-an-init + a-run-method.
* The framework's existing style is function-first (per `orchestrator/policy/` per-rule shape); a class-based helper would diverge from the codebase's idiom.
* Pillar I's reference-implementation discipline favors functions over classes when no state needs preserving between calls; the helper has no per-call state.

### D63-Alt1: Auto-detect pre-Pillar-C Twitter DM state + refuse to apply without operator confirmation

Migration walks the vault for Twitter touches + prints a "would emit N pairs; proceed?" prompt. **Rejected** because:

* Interactive prompts deadlock non-interactive contexts (daemon, cron) — same rationale as ADR-0017 D51-Alt2.
* The migration's idempotence check (per the existing intent-id set) already prevents duplicate emissions on re-run; no operator-confirmation safety is needed.
* The seed-then-skip path per D63 covers the operator-deliberate skip-the-backfill case without runtime interactivity.

### D63-Alt2: Combine `ledger/0003`, `ledger/0004`, and `ledger/0005` seeds into a single "Pillar C all-channels" block

Ship one combined seed incantation that marks all per-channel backfills applied at once. **Rejected** because:

* Different operators have different per-channel pre-history; the combined seed would force the all-or-nothing choice. Some operators have LinkedIn invite history but no DM history, or LinkedIn but no Twitter — per-channel granularity is the right level for operator control.
* The per-ADR §"Existing-operator seed" section is the canonical per-channel seed location; aggregating across channels would hide the per-channel-decision shape from operators reading the ADRs.
* Pillar I's CLI can offer a `--all-channels` aggregator over the per-channel incantations; the ADR seed remains per-channel.

### D63-Alt3: Skip the seed instruction entirely; rely on the migration's idempotence check

Operators who don't want the backfill can pre-emit `tw_dm_intent` events with the same deterministic IDs the migration would generate; the migration's idempotence skips them. **Rejected** because:

* The deterministic-ID computation is internal to the migration; expecting operators to mirror it for the skip-the-backfill case is leaking implementation detail.
* The `mark_applied` path is the canonical skip surface; the ADR-0014 D36 convention names it; operators learn the pattern once + apply it per migration.

### D64-Alt1: Defer the §Downstream pillar impact section to a future ADR

Skip it in Week 5; cover in Pillar D's ADR. **Rejected** by the established ADR-0009-onwards convention; every Pillar C ADR ships the section to give downstream pillars a forward-references contract.

### D64-Alt2: Combine D64 with ADR-0017 D52's §Downstream pillar impact (cross-week aggregation)

Treat the per-week §Downstream impact sections as cumulative; Week 5's references are additive to Week 4's. **Rejected** because the per-ADR section gives readers a per-week scope without requiring a multi-ADR read-through; the cumulative pattern would be hidden context.

### D64-Alt3: Defer the Pillar D / E / F sections; only document G / H / I / J (where Twitter touches directly)

Skip the downstream sections for pillars that don't interact directly. **Rejected** by the established convention — every per-Pillar-C ADR documents every downstream pillar so future readers see the explicit "no interaction" rather than ambiguous absence.

## Existing-operator seed

See D63 above for the full operator-facing posture + the `mark_applied` incantation + the per-operator-profile recommendations.

## Backfill overlap with `ledger/0002`

Twitter touches that are `sent: true` produce TWO event pairs after a full apply:

1. `send_intent` + `send_confirmed` from `ledger/0002` (channel-agnostic walker emits a generic pair for every `sent: true` touch).
2. `tw_dm_intent` + `tw_dm_confirmed` from `ledger/0005` (per-channel Twitter DM backfill).

The dual representation is by design per ADR-0015 §"Backfill overlap with ledger/0002" (Pillar C Week 2 established the rationale for the LinkedIn-invite case; the same logic applies to Twitter DMs). The cross-channel rule's first-match-wins semantics short-circuit correctly under dual representation — no double-engagement; both events carry `channel: twitter` and the rule fires once. The `ledger/0002` pair's `channel: "twitter"` is denormalized from the touch's `channel:` field per the Pillar C Week 1 generalization.

## Dry-run interaction

Per ADR-0013 D24-N + the ADR-0014 / 0015 / 0016 / 0017 inheritance pattern, dry-run interaction for Week 5's deliverables works as follows:

* **`ledger/0005` apply with `ctx.dry_run=True`** runs the walker + classification logic + intent-id computation WITHOUT writing any events to the ledger. The result reports the would-emit counts; no `tw_dm_*` events are appended; no `migration_event` is emitted (per ADR-0010 D17 "a dry run mutates nothing").
* **`reconcile.py --dry-run --passes F`** runs Pass F's read path (intent enumeration + Twitter batch fetch + marker scan) WITHOUT writing any `_confirmed | _aborted` events to the ledger. The result reports the would-emit events with `_dry_run: True` markers.
* **`reconcile.py --apply --passes F`** is the operational write path. Per the existing `--quick` / `--full` mode conventions, mode-default-apply applies; explicit `--dry-run` always wins. The Twitter MCP is read-only by definition; dry-run still calls it for the marker scan.
* **`gated_tw_dm_one`** has no dry-run mode (consistent with `gated_send_one` + `gated_li_invite_one` + `gated_li_dm_one`); operators who want a dry-run path skip the dispatcher call entirely.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. The ledger is authoritative; Twitter is the channel surface for I/O; the cookie-scrape MCP is a transport. The `_recovered_by: "reconcile"` field on Pass F emissions denormalizes the recovery source for observability.
- **I2 (two-phase commit on every external side effect):** Every Twitter DM send goes through `tw_dm_intent` → `mcp__scraplingserver__*::send_dm` → `tw_dm_confirmed | tw_dm_failed`. Pass F is the recovery vehicle for crashes between intent-write and MCP-call success — same shape as Pass A (email), Pass D (LinkedIn invites), Pass E (LinkedIn DMs).
- **I3 (schema versioning):** No new event-schema versions introduced. The Twitter event types (`tw_dm_intent | tw_dm_confirmed | tw_dm_failed | tw_dm_aborted`) are already in `_INTENT_TYPES` + `_OUTCOME_TYPES` per Week 1's generalization (ADR-0014 D33).
- **I4 (reproducible state):** `ledger/0005`'s intent_ids are deterministic (`bf_twdm_<hash>`); re-runs produce identical results. Pass F is idempotent (the indexer's outcome-for-intent check prevents duplicate emissions).
- **I5 (observable by default):** `migration_event` audit-trail emitted per `ledger/0005` apply with per-diagnostic field counts. Per-pass result counts in `ReconcileResult.passes[].summary()`. The `--json` CLI flag emits machine-readable per-pass diagnostics for Pillar G dashboard integration.
- **I6 (tests prove invariants):** `tests/test_send_gate_twitter_dm.py` (direct unit tests for `gated_tw_dm_one`) + `tests/test_migrations_ledger_0005.py` (direct unit tests for the backfill) + `tests/test_reconcile_tw_dm.py` (direct unit tests for Pass F). `tests/test_multi_channel_coherence.py::TestTwitterDMChannel` un-skips all 4 rows for end-to-end coherence.
- **I7 (cost is a first-class concern):** The Week 5 dispatcher emits `cost_incurred` events with `source="twitter_dm"` per ADR-0015 D40's split-source convention. Pass F doesn't emit cost events — the MCP call is read-only + the operator-time cost is amortized over the marker-scan batch per ADR-0017 D49.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains an ADR-0018 row. The Week 5 commit's per-week handoff document (`.planning/HANDOFF-pillar-c-week-5.md`) scoped the deliverables.

Does not weaken any invariant. I2's recovery guarantee extends to the Twitter channel (previously Twitter had no dispatcher; Week 5 closes the loop on send + recovery).

## Migration / rollout

Week 5 ships one new ledger migration + one new reconcile pass + one new dispatcher function. No vault migrations (per D61's deferral). No new policy migrations (per ADR-0015 D40's split-source operator-deliberate-activation convention).

**Operator-facing changes:**

1. **`runner.pending()` increments by 1 → 9.** The new `ledger/0005_baseline_tw_dm_history` joins the apply order after `ledger/0004`. Operators who want to skip it use the D63 seed incantation.

2. **CLI extends: `python orchestrator/reconcile.py --full` now runs all 6 passes (A,B,C,D,E,F) by default.** Operators who want the prior 5-pass behavior pass `--passes A,B,C,D,E` explicitly. The new default is the operator-facing breaking change of Week 5; the rollout doc above (D63 + the per-operator-profile table) names it.

3. **A new dispatcher entry point — `gated_tw_dm_one` in `skills/send-outreach/scripts/send_queued.py`.** The dispatch-outreach skill (Pillar C's send-time entry) gets a new branch for the Twitter DM register. Operators who manage their pipelines via the skill see new ledger events the moment they send their first Twitter DM through the new path.

4. **A new TwitterClientLike adapter shim is required for production CLI invocation of Pass F** — `skills/send-outreach/scripts/twitter_client.py::build_reconcile_adapter`. Without it, the CLI records "Pass F requires a Twitter client" + skips the pass (same shape as Pass D's missing-LinkedIn error). Pillar I OSS bring-up will ship the reference adapter; until then, programmatic callers inject a fake (e.g. `FakeTwitter` in `tests/test_reconcile_tw_dm.py`).

5. **First-invocation against a stale ledger may emit a recovery wave** per D63's first-invocation semantics. Operators see new `tw_dm_*` events in their first `--full` run; subsequent runs are quiet.

**The Week 5 commit's verification surface:**

```bash
# 1. One new migration (8 → 9 pending).
$ python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print(len(r.pending()))"
9

# 2. New dispatcher + Pass F + backfill tests pass.
$ python -m pytest tests/test_send_gate_twitter_dm.py tests/test_reconcile_tw_dm.py tests/test_migrations_ledger_0005.py -v
# Expected: ~60-80 passed.

# 3. The previously-skipped Twitter coherence rows un-skip and pass.
$ python -m pytest tests/test_multi_channel_coherence.py::TestTwitterDMChannel -v
# Expected: 4 passed, 0 skipped.

# 4. The full suite is green with the new tests added.
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: ~1380-1410 passing.

# 5. ADR-0018 exists; README index gains the row; PILLAR-PLAN §6 Pillar C
#    row updated to reflect Week 5 ship.
$ ls docs/adr/0018-pillar-c-twitter-dm-dispatcher.md
$ grep "0018" docs/adr/README.md
$ grep "Week 5" docs/PILLAR-PLAN.md
```

## References

- ADR-0001 (policy engine architecture) — `RuleContext.channel` field; the Week 5 dispatcher constructs context with `channel="twitter"`.
- ADR-0003 (channel as first-class policy predicate) — the `CrossChannelTouchRule` Week 5's `tw_dm_confirmed` events fire against; the rule's `consider_channels:` matches `twitter` as a first-class value.
- ADR-0006 (cost-event model) — Week 5 emits `cost_incurred` events with `source="twitter_dm"` per D58.
- ADR-0008 (budget rules) — operators configure `budget.window-cap` rules against `source=twitter_dm` for per-channel throughput caps.
- ADR-0009 (migration framework) — `ledger/0005` is the fifth ledger migration; the runner's apply order accommodates it without amendment.
- ADR-0010 (ledger migrations) — D14 append-only invariant (Week 5 emissions are append-only); D17 migration_event emission contract (Week 5 ships the diagnostic counts).
- ADR-0013 (synthetic-replay exit-criterion vehicle) — D24-N dry-run interaction (Week 5 deliverables respect dry-run); D32 per-ADR existing-operator seed pattern (D63 instantiates).
- ADR-0014 (Pillar C foundation) — D33 channel event-type naming convention (D58 reaffirms `tw_dm_*` prefix); D35 per-channel `migration_event` channel field (ledger/0005 stamps `channel="twitter"`); D36 per-ADR seed pattern (D63 instantiates).
- ADR-0015 (Pillar C Week 2 — LinkedIn invite) — D38 per-channel vault-action discriminator (D61 defers Twitter's equivalent); D39 zero-width-Unicode marker (D58 reaffirms); D40 cost-event source split (D58 reaffirms with `twitter_dm`); D41 per-migration seed pattern (D63 instantiates); D42 per-week per-channel rollout template (Week 5 is the third application).
- ADR-0016 (Pillar C Week 3 — LinkedIn DM) — D43 reaffirms D39's marker shape (D58 reaffirms again for Twitter); D44 requires-existing-connection gate (D60 inverts to allow for Twitter); D45 lazy-stamping convention (no Twitter equivalent per D60's no-gate posture); D46 per-migration seed pattern (D63 instantiates).
- ADR-0017 (Pillar C Week 4 — reconcile Pass D + E) — D48 serial-execution convention (Pass F joins the serial sequence after E); D49 marker-scan window (Pass F inherits the 100-item default); D50 marker-not-found abort semantics (Pass F inherits); D51 operator-facing rollout (D63 follows the convention); D52 downstream pillar impact (D64 follows the convention).
- `docs/PILLAR-PLAN.md` §2 Pillar C — exit criterion (binding text); §6 Pillar C row updated to reflect Week 5 ship.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D60's allow posture (the failure mode inverts from LinkedIn's; the principle's application produces the opposite gate posture).
- `docs/RISK-REGISTER.md` R001 (dispatcher crash between intent and outcome) — risk this ADR mitigates by design via Pass F recovery.
- `docs/RISK-REGISTER.md` R002 (false-confirm from delayed MCP response) — risk this ADR mitigates via retroactive confirm on marker match.
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — risk this ADR mitigates by design via the cross-channel rule firing against `tw_dm_confirmed`.
- `docs/SOURCES-OF-TRUTH.md` — Twitter cookie-scrape MCP is a transport, not an SoT; the ledger is authoritative.
- `.planning/HANDOFF-pillar-c-week-4.md` — the prior week's handoff documenting Week 4's deliverables.
- `.planning/HANDOFF-pillar-c-week-5.md` — the handoff that scoped this commit's deliverables.
- `.planning/HANDOFF-pillar-c-week-6.md` — the next week's handoff scoping the calendar booking dispatcher + Cal.com webhook + reconcile Pass G.
- `orchestrator/reconcile.py` — `run_pass_f` + `TwitterClientLike` Protocol + the generalized `_run_channel_intent_pass` core (renamed from `_run_linkedin_intent_pass` per D62).
- `orchestrator/ledger.py` — `_OUTCOME_TYPES` + `_INTENT_TYPES` + `_CONFIRMED_TYPES` already include `tw_dm_*` types per Week 1's generalization; Week 5 ships the events that exercise the indexer.
- `orchestrator/policy/cross_channel.py` — the rule class Week 5's `tw_dm_confirmed` events fire against; the rule's `type.endswith("_confirmed")` predicate matches `tw_dm_confirmed` per ADR-0014 D33.
- `orchestrator/migrations/ledger/migration_0005_baseline_tw_dm_history.py` — the Week 5 ledger backfill.
- `skills/send-outreach/scripts/send_queued.py` — `gated_tw_dm_one` + `_tw_dm_vault_writeback` + the Twitter section constants (TW_DM_INTENT_MARKER_TEMPLATE + TWITTER_DM_BODY_MAX_CHARS + TW_DM_BLOCK_EXTRAS).
- `skills/send-outreach/scripts/vault.py` — `PersonInfo.twitter_handle` + `TouchDraft.twitter_dm` + the `## Twitter DM` section regex.
- `tests/test_send_gate_twitter_dm.py` — direct unit tests for `gated_tw_dm_one`.
- `tests/test_migrations_ledger_0005.py` — direct unit tests for the backfill.
- `tests/test_reconcile_tw_dm.py` — direct unit tests for Pass F.
- `tests/test_multi_channel_coherence.py::TestTwitterDMChannel` — un-skipped Week 5 (was skipped pre-Week-5; verifies end-to-end coherence against the synthetic fixture's Evan + Twitter touch + orphan substrate).
- `tests/fixtures/synthetic_pillar_b/vault/10 People/Evan Estefan.md` — Twitter-only Person added Week 5.
- `tests/fixtures/synthetic_pillar_b/vault/40 Conversations/2026-04-22 Evan twitter dm.md` — Twitter DM touch added Week 5.
- `tests/fixtures/synthetic_pillar_b/ledger/events-2026-04-15.jsonl` — extended Week 5 with one orphan `tw_dm_intent` (Evan's `twdm_synthetic_orphan_dm_01`) — substrate for the coherence test.
- Forward-references (planned):
  - **ADR-0019** (Pillar C Week 6): Calendar booking dispatcher + Cal.com webhook + reconcile Pass G (calendar-booking orphan recovery; the webhook surface may obviate the need for a periodic reconcile pass — see ADR-0019's planned analysis).
  - **Pillar H daemon** (Weeks 31-36): per-stage parallelism for reconcile-on-cadence; the serial-execution convention per D48 (carried by D62's helper rename) informs the per-channel-pass worker budget — Twitter MCP rate-limit is distinct from LinkedIn's, so a daemon can run Pass F in parallel with Pass D + E (the cross-MCP boundary is the parallelism unit).
  - **Pillar I OSS bring-up**: ships `skills/send-outreach/scripts/twitter_client.py::build_reconcile_adapter` as the operator-facing cookie-scrape MCP wrapper; the cookie-capture story per D59 becomes Pillar I operator-doc content.
