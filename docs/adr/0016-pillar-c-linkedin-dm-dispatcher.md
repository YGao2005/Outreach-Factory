# ADR-0016: Pillar C Week 3 — LinkedIn DM dispatcher, retroactive backfill, and requires-existing-connection gate

- **Status:** Accepted
- **Date:** 2026-05-21
- **Pillar:** C (Multi-channel coherence — Week 3)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar C Week 1 (ADR-0014) shipped the convention-setting decisions every per-channel week composes against. Pillar C Week 2 (ADR-0015) shipped the **first** per-channel dispatcher — `gated_li_invite_one` in `send_queued.py` + `ledger/0003_baseline_li_invite_history` + `vault/0003_add_linkedin_action_to_touch_notes` + the per-week per-channel rollout convention (D42). Week 3 is the **second** per-channel week — structurally near-identical to Week 2 per the D42 template, modulo the DM-vs-invite semantic + the requires-existing-connection gate.

The five concerns Week 3 resolves:

1. **LinkedIn DMs to non-connections silently land in the message-request inbox.** Per LinkedIn's behavior, sending a DM to a non-connection routes the message to a "message requests" sub-inbox the recipient must explicitly approve before seeing. The dispatcher cannot track delivery into that sub-inbox; a "success" return from `mcp__linkedin__send_message` does NOT guarantee the recipient saw the message. The asymmetric-failure-cost calculus (PILLAR-PLAN §0) favors refuse-loud over send-with-uncertainty for this class of failure — better to refuse a send than to fire-and-forget into a void. D44 pins the gate posture.

2. **`linkedin_connected:` discovery has competing strategies, each with different operator-time costs.** Two options surface: (a) per-Person MCP scan via a one-time vault migration that walks every Person note + calls `mcp__linkedin__get_person_profile` for each (`O(N persons × 3s + rate limit)` — for an operator with 1000+ Persons, 50+ minutes); (b) lazy stamping via the dispatcher (read MCP once per Person on first DM attempt; stamp result; subsequent reads from vault). D45 pins the lazy-stamping convention.

3. **MCP-mediated LinkedIn DMs have a different round-trip surface than invites.** Where the invite path's connection-note text has a 300-char hard limit (~10% of budget for the ~30-char marker), DM bodies have an 8000-char limit (~<1% of budget). The intent-id marker scheme (zero-width-Unicode-wrapped per ADR-0015 D39) carries forward unchanged; D43 reaffirms the marker shape + names the dispatcher's body-length pre-flight refuse-loud at the 8000-char boundary.

4. **Per-action cost-event source split per ADR-0015 D40.** The Week 3 dispatcher emits `cost_incurred` events with `source="linkedin_dm"` (distinct from Week 2's `source="linkedin_invite"`). Operators who want separate per-action budget caps configure two distinct `budget.window-cap` rules in their `cooldowns.yml`. D43 reaffirms the convention; no policy migration ships in Week 3 (operator-deliberate activation per ADR-0008 + Week 2's D40 rationale).

5. **Existing operators have pre-Pillar-C LinkedIn DM history.** Yang's pre-Pillar-C touches with `linkedin_action: dm` (after Week 2's vault/0003 stamps it) AND filename-DM-classified touches generate retroactive `li_dm_*` events when ledger/0004 runs. Operators who want to preserve historical state as-is need the one-time `mark_applied` incantation per ADR-0014 D36. D46 instantiates the seed pattern for ledger/0004.

A sixth concern surfaces only on close inspection: **`ledger/0004` and `ledger/0002` both emit two-phase pairs for the same DM touch.** Dana's DM touch on 2026-04-20 (the synthetic fixture extension) produces both a `send_intent`+`send_confirmed` pair (ledger/0002 walks every `sent: true` touch regardless of channel) AND a `li_dm_intent`+`li_dm_confirmed` pair (ledger/0004 walks DM-classified LinkedIn touches specifically). The dual representation is by design — see ADR-0015 §"Backfill overlap with ledger/0002" for the rationale (which carries verbatim to ledger/0004); the cross-channel rule's first-match-wins semantics short-circuit correctly under dual representation.

Risks this ADR mitigates by design: **R011 (cross-channel double-engagement)** — the Week 3 dispatcher's `li_dm_confirmed` events fire the existing cross-channel rule (ADR-0003) the moment they land in the ledger. The synthetic-replay exit-criterion vehicle (`tests/test_multi_channel_coherence.py::TestLinkedInDMChannel`) pins this end-to-end starting Week 3.

## Decision

### D43. LinkedIn DM event-type prefix `li_dm_*`; cost-event source `linkedin_dm`; intent-id marker via zero-width-Unicode in DM body

Pillar C Week 3 dispatcher emits two-phase events with the event-type prefix `li_dm_*` (per ADR-0014 D33 — `li_dm_intent` / `li_dm_confirmed` / `li_dm_failed` / `li_dm_aborted`). Every event carries `channel: "linkedin"` (same channel value as LinkedIn invites because both share the upstream rate-limit pool and the cross-channel rule's `consider_channels: [linkedin]` matches both event-type prefixes).

The cost-event source is `source="linkedin_dm"` per ADR-0015 D40's split-source convention. Operators who want a single combined LinkedIn cap configure a `budget.window-cap` rule with `source: linkedin_*` (glob-aware future Pillar A extension) or write two cooldown rules referencing the two distinct sources.

The intent-id marker scheme (per ADR-0015 D39) carries verbatim: a zero-width-space-wrapped marker (`​outreach-intent:<intent_id>​`) is appended to the DM body before the MCP call. Reconcile Pass E (Week 4) reads the marker back via the LinkedIn MCP's conversation-history surface. The marker's length (~30 chars) eats <1% of LinkedIn's 8000-char DM body limit; the dispatcher refuses-loud when the operator-supplied body + marker would exceed the limit (mirror of the invite path's note-length pre-flight per Week 2 P2-1).

**Both decisions D33 (event-type prefix) and D40 (cost-event source) were established by ADR-0014 + ADR-0015 respectively; D43 is the reaffirmation that no Week 3 author should regress them.** The reaffirmation pattern is structural: every subsequent per-channel week's first decision in its ADR is the channel-event-naming + cost-source confirmation per ADR-0015 D42's template. Without the explicit reaffirmation, a Week 3 author who skimmed the templates could plausibly land on `linkedin_dm_*` (verbose) or `lidm_*` (different glyph order) — both would diverge from the cross-channel rule's forward-references in `cross_channel.py`. D43 forecloses.

### D44. Requires-existing-connection gate posture — refuse-loud on unknown; refuse-loud on false; `allow_unconnected=True` operator override

The Week 3 dispatcher's pre-flight gate sequence (after identity / no-linkedin-url / ledger-prior-send / policy.evaluate / lock acquire) adds an **is-the-recipient-an-existing-LinkedIn-connection** check:

* **`linkedin_connected: true` on Person frontmatter** → gate passes; the send proceeds.
* **`linkedin_connected: false`** → gate refuses-loud with reason `not_a_connection`. The dispatcher emits a `dedup_blocked` event with `channel: linkedin` + the structured detail naming the failure mode.
* **Field absent or unparseable** → gate refuses-loud with reason `connection_state_unknown`. Same `dedup_blocked` event shape.
* **`allow_unconnected=True` keyword to `gated_li_dm_one`** → bypass the gate entirely. Operator-deliberate override (Pillar I CLI exposes the flag explicitly; until then, programmatic callers pass it).

**Why refuse-loud and not refuse-soft (warn-then-send).** LinkedIn's message-request-inbox routing is silent at the API surface — the MCP call succeeds, returns a thread_id, and the operator's dispatcher records the send as confirmed. The only signal the recipient never read it is the absence of a reply over time (a Pillar D concern). Refuse-soft would let the operator-system emit a `li_dm_confirmed` event for a message the recipient may never see, biasing the cross-channel rule's downstream behavior (a 14-day-window block on a probably-unread DM). Refuse-loud forecloses this systemic mis-state by refusing to write the confirmed event in the first place.

**Why refuse-loud and not refuse-quiet (skip silently).** The operator who wrote a DM touch in vault expected it to send. Silently skipping the send would surface as "why didn't my DM go out?" — debuggable only by ledger inspection. Refusing loud, with a `dedup_blocked` event carrying the operator-readable detail ("stamp linkedin_connected: true on the Person note after verifying via LinkedIn UI"), gives the operator a clear remediation path on the spot.

**Why an operator-deliberate override exists at all.** Three legitimate use cases for sending to a non-connection:
1. The operator has prior context with the recipient (e.g., the recipient subscribed to the operator's newsletter; the operator is replying to a message the recipient initiated in a different channel) and accepts the message-request-inbox routing risk.
2. The operator is sending to a LinkedIn Premium / Sales Navigator account with InMail, which delivers to non-connections by design.
3. Testing or debugging — the operator wants to fire-and-test the dispatcher's flow against a known-unconnected recipient.

The `allow_unconnected=True` kwarg gives all three a clean path; programmatic callers (Pillar H daemon, Pillar I CLI) thread it explicitly. The operator-deliberate-override discipline mirrors ADR-0006's "shadow-mode evaluation" pattern for budget rules — the framework refuses by default, accepts an explicit override.

**Edge case: `linkedin_connected: false` + `allow_unconnected=True`.** The combination is operator-deliberate: the operator KNOWS the recipient isn't a connection AND chooses to send anyway. The gate honors the override (the send proceeds); the `li_dm_confirmed` event lands; the operator accepts the message-request-inbox delivery risk. No additional warning is needed beyond the override's explicit nature.

### D45. `linkedin_connected:` discovery strategy — lazy stamping via dispatcher

The Week 3 dispatcher reads the `linkedin_connected:` field from each Person note on its first DM attempt to that Person. When the field is absent, the dispatcher refuses-loud per D44 (the operator stamps it manually after verifying via LinkedIn's UI); the dispatcher does NOT auto-stamp by calling the LinkedIn MCP's `get_person_profile` surface to learn connection state.

**Why lazy stamping and not per-Person MCP scan via a vault migration.** Two reasons:

1. **Cost.** Per-Person MCP scan is `O(N persons × 3s + rate limit)`. For Yang's vault (a few hundred Persons) the bulk scan is ~15-20 minutes. For Pillar I OSS bring-up's eventual operator base with 1000+ Person notes, the bulk scan runs 50+ minutes (or longer when the rate limit hits — LinkedIn's MCP throttles at ~30 calls/minute). The lazy-stamping path amortizes the per-Person scan cost across normal operation: operators only pay the MCP-read latency for Persons they actually attempt to DM.

2. **Operator agency.** A bulk scan would silently learn-and-stamp connection state across an entire vault, including Persons the operator has no intention of DMing. Lazy stamping ties the read to the operator's deliberate send attempt; the operator's manual stamp (after verifying in the LinkedIn UI) gives them the chance to also note the connection-context in the Person note's body.

**Why dispatcher doesn't auto-stamp on first send attempt.** Three reasons:

1. **The LinkedIn MCP's `get_person_profile` call is not a substitute for "is this person a connection?".** The profile API surface returns "connected" only for first-degree connections; second-degree + invited-not-yet-accepted both surface as "not connected" but operationally distinct (an InMail to second-degree may work; a DM to invited-not-yet-accepted definitely won't). The operator's manual verification via LinkedIn's UI captures the nuance the MCP collapses.

2. **MCP failures during the gate would propagate unhelpfully.** If the dispatcher tried to auto-stamp on first attempt and the MCP rate-limited (LinkedIn's enforcement), the dispatcher would either retry (slowing down the gate latency materially) or refuse with an opaque "connection state lookup failed" — both worse UX than the explicit "stamp it manually" path the operator gets via D44's `connection_state_unknown` reason.

3. **The lazy-stamping convention generalizes.** Future Pillar D / E migrations may add per-Person frontmatter fields with similar dispatcher-time-discovery shapes (e.g., a `reply_classifier_consent:` field that the operator stamps when they observe an inbound DM thread). The lazy-stamping convention is the per-Person-stateful default; the per-Person-MCP-scan migration is the exception that requires explicit ADR justification.

**Counter-argument: bulk-send patterns.** Operators with a bulk-send pattern (Pillar H daemon firing many DMs in a single run) hit the operator-manual-stamp friction sequentially. Mitigation: the operator pre-stamps the `linkedin_connected:` field on the candidate Persons before starting the bulk send (e.g., via Pillar I CLI's batch `mark-connected` command, or by hand-editing the Person notes). The bulk-send path is operator-deliberate; pre-stamping is consistent with that deliberation.

**Counter-counter-argument: this is operator-time friction.** Yes — operator-deliberate friction is the design intent. The alternative (auto-stamping + risking message-request-inbox delivery) has worse failure modes per D44's rationale.

### D46. Existing-operator seed for `ledger/0004_baseline_li_dm_history`

Operators with pre-existing LinkedIn DM touches (Yang specifically; future OSS operators with pre-Pillar-C LinkedIn DM history) may want to skip the retroactive backfill. Per ADR-0014 D36 + ADR-0015 D41 (the established convention), this ADR provides the §"Existing-operator seed" REPL incantation.

#### Skipping `ledger/0004` only

For operators who want their pre-Pillar-C LinkedIn DM ledger state preserved as-is (no `li_dm_*` events emitted retroactively):

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
    state, MigrationCategory.LEDGER, "0004_baseline_li_dm_history",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `ledger/0004` as applied; `apply()` skips it; the operator's LinkedIn DM history stays exactly as it was pre-Week-3 (touch notes + no `li_dm_*` ledger events).

#### Recommended posture per operator profile

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero pre-Pillar-C LinkedIn DM history) | Run `apply()` normally. The migration emits zero events (no DM touches to walk); the migration_event audit trail records the no-op for continuity. |
| Existing operator who wants historical events preserved as-is | Seed `ledger/0004`. Pre-existing DM touches remain unstamped at the ledger level; new touches via the Week 3 dispatcher carry full two-phase events. |
| Existing operator who wants retroactive emissions for cross-channel rule activation | Run `apply()` normally. `ledger/0004` emits the backfill pairs; the cross-channel rule starts firing against historical LinkedIn DMs the moment a future email send attempt evaluates against them. |
| Yang (current sole operator, as of 2026-05-21) | Recommended: run `apply()` normally. Yang's pre-Pillar-C LinkedIn DM count is small (the practical risk of cross-channel rule mis-fires against backfilled DM events is low). |

**Week 3 does NOT ship a vault migration.** Week 2's `vault/0003_add_linkedin_action_to_touch_notes` already stamps `linkedin_action:` on every LinkedIn touch (invite OR DM); Week 3's ledger/0004 reads the field directly. No new vault primitive is required because the field's two valid values (`invite`, `dm`) cover both per-channel weeks. A future Week 5 (Twitter DM) ADR may ship a vault migration for `twitter_handle:` per-Person state per ADR-0015 D42's template; Week 3 specifically does not need one.

**Why no `vault/0004` for `linkedin_connected:` field initialization.** Per D45's lazy-stamping convention, the field is operator-deliberate-on-first-DM-attempt. A vault migration that initialized `linkedin_connected: null` on every Person note would clutter Person frontmatter with an unset-by-default field that confuses operators ("why does every Person have an empty `linkedin_connected` field they didn't set?"). Lazy stamping keeps the field opt-in.

### D47. Downstream pillar impact

Per the ADR-0009 / 0010 / 0011 / 0012 / 0013 / 0014 / 0015 convention (every Pillar B + C ADR explicitly names cross-pillar impact):

* **Pillar D (reply + conversation handling).** Pillar D's reply joiner correlates `li_dm_reply_received` events (per ADR-0025 D96's per-channel-prefixed naming convention; supersedes the generic `reply_received` placeholder this paragraph used pre-ADR-0025) to their originating `li_dm_confirmed` by `intent_id` AND by `linkedin_thread_id`. The Week 3 dispatcher stamps both on the confirmed event (`intent_id` is Pillar C's canonical correlator; `linkedin_thread_id` is LinkedIn's). Pillar D's joiner reads both for double-check robustness — same shape as Week 2's `linkedin_invitation_id` correlation. The `linkedin_action: dm` field on touch notes lets Pillar D distinguish "operator started a DM thread" from "operator sent an invite + the recipient hasn't accepted yet" conversation states.

* **Pillar E (discovery quality + lineage).** No direct interaction. Pillar E adds `discovery_lineage:` blocks to Person frontmatter; per-touch DM fields are orthogonal. Pillar E's `discovery_lineage:` may include a `discovered_via_linkedin_dm:` field that ties to a Pillar C `li_dm_confirmed` event — the cross-pillar query is one join, no Pillar C schema change.

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring operates on touch body content (the DM body). The Week 3 dispatcher's intent-id marker (D43) appends to the body; Pillar F's voice-scorer must strip the marker before scoring or the scorer would penalize the marker's "AI-shape" artifacts. The marker is at a known position (end of text) and surrounded by zero-width spaces — Pillar F's text-cleanup step strips it deterministically (same logic as Week 2's invite marker per ADR-0015 D42).

* **Pillar G (observability).** Pillar G's per-channel migration audit-trail dashboard reads ledger/0004's `migration_event` event filtered by `channel="linkedin"` per ADR-0014 D35; Week 3's diagnostic fields (`linkedin_dm_pairs_emitted`, `linkedin_dm_pairs_skipped`, `touches_without_person_match`, `touches_skipped_not_dm`) become per-migration observability rows. Pillar G's per-channel funnel dashboard reads `li_dm_intent` / `li_dm_confirmed` / `li_dm_failed` events with `channel: linkedin` per D33 — one query per funnel state, distinct from the `li_invite_*` funnel queries.

* **Pillar H (daemon + dispatcher).** Pillar H's per-stage parallelism limits become per-channel + per-action (e.g. "no more than N concurrent LinkedIn invite sends"; "no more than M concurrent LinkedIn DM sends"). The Week 3 `cost_incurred` event's `source="linkedin_dm"` is the discriminator Pillar H's dispatcher uses to throttle independently from LinkedIn invite throughput. Pillar H's bulk-send workflow per-Person threading reads `linkedin_connected:` per D45 (lazy stamping); the per-Person friction surfaces here as a possible "first send per Person costs an MCP read; subsequent reads are vault-only." The daemon design accommodates by chunking + cache warming if operator scale demands.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel state isolation. The D46 existing-operator-seed block aggregates into Pillar I's CLI as `python -m orchestrator.migrations seed --pillar-c --channel linkedin_dm` (or the looser `--pillar-c` aggregates every Pillar C ADR's seed blocks). The lazy-stamping convention per D45 surfaces as a Pillar I CLI ergonomic: `python -m orchestrator.linkedin mark-connected <person>` for operators who want to pre-stamp connection state before bulk sends; this CLI command is the Pillar I home for D45's per-Person discovery surface.

* **Pillar J (security + compliance).** GDPR-forget on a Person who has LinkedIn DM touches: the DM touch notes are deleted (Pillar J's forget tooling per ADR-0010's pattern), and per-Person `li_dm_*` events are tombstoned. The Week 3 dispatcher's `linkedin_thread_id` field is potentially-PII — Pillar J's forget tooling redacts it on tombstone. The `linkedin_connected:` field per D45 is also tombstoned (the operator's observation that a specific Person is/isn't connected is also potentially-PII).

## Alternatives considered

### D43-Alt1: Use a single `li_*` prefix for all LinkedIn events, with action discriminated by frontmatter field

Drop the `_invite_` / `_dm_` suffix and stamp a `linkedin_action:` field on every event. **Rejected** because:

* ADR-0014 D33 explicitly forward-references `li_invite_*` and `li_dm_*` as distinct event-type prefixes; `orchestrator/policy/cross_channel.py::CrossChannelTouchRule` filters on `type.endswith("_confirmed")` and the action-discriminating prefix is load-bearing for that filter to distinguish invite-confirmed from DM-confirmed in the rule's `prior_touch_type` detail field.
* Pillar G's funnel queries are stronger with per-action event types (no need to join with the action field; the type itself is the discriminator). Collapsing into a single prefix would force every query to add the action filter.
* The convention ships factory-uniform across all four channels — Twitter DM (`tw_dm_*`), calendar booking (`calendar_booking_*`); collapsing LinkedIn alone would be a special case.

### D43-Alt2: Use `linkedin_dm_*` (verbose) instead of `li_dm_*` (compact)

Spell out the channel prefix to avoid the `li_` two-letter contraction. **Rejected** because:

* ADR-0014 D33 ships the contraction across all four channels (`li_invite_*`, `li_dm_*`, `tw_dm_*`, `calendar_booking_*`). Defaulting to compact prefixes keeps event-type strings short for grep + logging readability.
* The contraction is consistent with Pillar A's `RuleContext.channel = "linkedin"` (the channel field is spelled out for human-readability in the gate; the event-type prefix is compact for storage + filtering ergonomics).
* Spelling out one prefix would orphan the existing test corpus that asserts on the compact form (~10 tests in `tests/test_send_gate_linkedin.py` + `tests/test_multi_channel_coherence.py` + this file).

### D43-Alt3: Combine the LinkedIn invite + DM cost sources into one `linkedin` source for budget rules

Drop the `_invite` / `_dm` action discriminator on `cost_incurred.source`. **Rejected** by ADR-0015 D40's already-decided split-source convention — the operator's likely-intent is per-action caps (LinkedIn's invite-spam enforcement is harsher than DM-spam enforcement on personal accounts). Sharing a budget across invites + DMs forces operators who want per-action caps to write per-channel-policy rules per action — more YAML, not less. D43 reaffirms D40; no divergence.

### D44-Alt1: Refuse-soft (warn-and-send) when connection state is unknown

The dispatcher emits a warning to stderr but proceeds with the send. **Rejected** because:

* LinkedIn's message-request-inbox routing is silent at the API surface — the MCP returns "success" regardless of where the message lands. Refuse-soft would let the dispatcher write a `li_dm_confirmed` event for a message the recipient may never read, biasing the cross-channel rule's downstream behavior (the rule's 14-day-window block treats the DM as if it landed).
* The asymmetric-failure-cost calculus (PILLAR-PLAN §0): the cost of a refuse-when-the-recipient-WOULD-have-seen-it is a small operator-time annoyance ("stamp the field, retry"); the cost of a send-that-the-recipient-DOESN'T-see is a corrupted ledger state that affects Pillar D + G + H downstream. Refuse-loud is the safe side.

### D44-Alt2: Refuse-loud only on `linkedin_connected: false`; allow when absent (assume connection)

Distinguish "field absent — operator hasn't checked" from "field false — operator confirmed not connected" by allowing the former. **Rejected** because:

* Optimistic defaults on the LinkedIn-non-connection path bias toward the wrong-direction failure mode. An operator who created a new Person note but hasn't yet verified the connection state in the LinkedIn UI would silently send to a non-connection.
* The friction of "stamp the field manually" is the SAME for field-absent AND field-false operators — both need to set a value (true or false) before the send proceeds. Asymmetric treatment would surface as a footgun in the field-absent case.
* The `connection_state_unknown` vs `not_a_connection` reason codes give the operator a distinct signal in the `dedup_blocked` event — the operator can act on the more-specific signal without the gate's pre-action posture changing.

### D44-Alt3: Send-with-best-effort (try the MCP; if it returns "delivered" stamp connected:true; if not, stamp false)

The dispatcher tries the MCP first; on success, stamps `linkedin_connected: true` retroactively; on a known failure mode, stamps `linkedin_connected: false`. **Rejected** because:

* The LinkedIn MCP's `send_message` doesn't expose a "did the message reach the main inbox?" signal — both connection + non-connection routings return the same shape. Distinguishing them retroactively requires the operator to check LinkedIn's UI anyway; the dispatcher can't infer.
* This option inverts the order — sending first + learning second — which biases the gate sequence against the asymmetric-failure-cost principle (send before checking is "act then verify"; the existing gate sequence is "verify then act").
* The retroactive-stamping convention would also have to handle the rate-limit case (MCP timeout doesn't tell us anything about connection state), leaving the field unstamped + the operator's next attempt re-firing the same indeterminacy.

### D45-Alt1: Per-Person MCP scan via `vault/0004_add_linkedin_connection_state` migration

A one-time vault migration walks every Person note with a `linkedin:` URL + calls `mcp__linkedin__get_person_profile` for each + stamps `linkedin_connected:` per the API response. **Rejected** because:

* Cost: `O(N persons × 3s + rate limit)`. For Yang's vault (~200 Persons) the bulk scan is ~10-15 minutes; for OSS bring-up's first-wave operators with 1000+ Persons, 50+ minutes (or longer under rate-limit). The lazy-stamping path amortizes this cost across normal operation.
* Operator agency: a bulk scan silently learns-and-stamps state across an entire vault, including Persons the operator has no intent to DM. The lazy path ties the read to deliberate operator action.
* The MCP's `get_person_profile` doesn't perfectly distinguish first-degree from second-degree (or invited-not-accepted) connections — the operator's manual UI-based verification captures the nuance the API surface collapses.

### D45-Alt2: Lazy stamping with operator-confirm prompt (interactive)

The dispatcher prompts the operator via stdin on first DM attempt to a Person without `linkedin_connected:` set. **Rejected** because:

* The dispatcher is invoked from non-interactive contexts (Pillar H daemon, automated workflows, the send-outreach skill). A stdin prompt would deadlock automated invocations.
* Even in interactive contexts, the prompt would interrupt batch sends with a "please go check LinkedIn for this person" — bad UX. The refuse-loud path lets the operator queue + check + retry in their own time.

### D45-Alt3: Lazy stamping with dispatcher-auto-stamp on first send (MCP-mediated)

The dispatcher calls `mcp__linkedin__get_person_profile` on first DM attempt + stamps the result + proceeds. **Rejected** because:

* MCP rate limits surface during the gate sequence, which would slow gate latency by ~3s per first-attempt Person (compounding under bulk send).
* MCP failure modes (timeout, transient error) would propagate as opaque "couldn't check connection state" — worse UX than the explicit "stamp it manually" path D44/D45 ship.
* The MCP profile API doesn't perfectly distinguish connection types (per the D45-Alt1 rejection).

### D46-Alt1: Auto-detect pre-Pillar-C LinkedIn DM state + refuse to apply without operator confirmation

The migration walks for any pre-existing touch note with `channel: linkedin` AND `sent: true` AND DM-classified; if found, refuses to apply automatically + prints the seed instruction. **Rejected** per the ADR-0014 D36-Alt3 + ADR-0015 D41-Alt1 precedent — the auto-detect heuristic is fragile (an operator who imported historical LinkedIn data from a CSV trips the heuristic) + the new-operator case (zero pre-existing state) should run frictionlessly without intervention. The explicit operator-supplied signal (the seed `mark_applied` call) is the safe shape.

### D46-Alt2: Combine `ledger/0003` + `ledger/0004` seeds into a single "Pillar C LinkedIn" block

A single block that marks both per-channel migrations applied. **Rejected** per ADR-0014 D36 + ADR-0015 D41-Alt2 — Pillar I OSS bring-up's CLI aggregates per-migration seed blocks mechanically; a combined block would be a Pillar-C-LinkedIn-specific tool that Pillar I would then have to disaggregate. The per-migration blocks compose into Pillar I's `--migration <id>` filter without rewriting.

### D46-Alt3: Skip the seed instruction entirely; rely on the migration's idempotence check

Per-channel ledger migrations are idempotent (the existing-intent-id set check); operators with pre-existing state could just re-apply + the idempotence check catches it. **Rejected** because:

* The pre-Pillar-C LinkedIn DM path does NOT write `li_dm_*` ledger events at all (the MCP call's success was captured as touch-note `sent: true` only). The migration's idempotence check (against existing `li_dm_intent` events) would have nothing to match against; it would re-emit retroactive events for every operator on every apply.
* The seed instruction is the discrete signal "this operator already has the effects; skip the migration entirely."

### Existing-operator seed pattern (no separate alternative — established by ADR-0014 D36 + ADR-0015 D41)

The per-ADR §"Existing-operator seed" subsection is the established convention. Pillar I OSS bring-up's CLI (`python -m orchestrator.migrations seed --pillar-c`) aggregates from per-ADR blocks. No standalone alternative is needed.

## Existing-operator seed

See D46 above for the full ledger/0004 seed block + per-operator-profile guidance table. No vault migration ships in Week 3, so no vault seed block is needed; operators retain Week 2's vault/0003 seed block (per ADR-0015 D41) for the `linkedin_action:` field stamping.

## Backfill overlap with `ledger/0002` + `ledger/0003`

`ledger/0002_backfill_send_history` walks every `sent: true` touch regardless of channel and emits `send_intent` + `send_confirmed` pairs with the `channel:` field set to the touch's channel value (Pillar C Week 1 fix). For Dana's DM touch on 2026-04-20, ledger/0002 emits a `send_intent`+`send_confirmed` pair with `channel: "linkedin"`.

`ledger/0003_baseline_li_invite_history` (Week 2) walks LinkedIn invite touches specifically and emits `li_invite_intent` + `li_invite_confirmed` pairs. Dana's DM touch is DM-classified, so ledger/0003 skips it (`touches_skipped_not_invite` += 1).

`ledger/0004_baseline_li_dm_history` (Week 3) walks LinkedIn DM touches specifically and emits `li_dm_intent` + `li_dm_confirmed` pairs. For Dana's touch, ledger/0004 emits the pair with a distinct intent_id (`bf_lidm_<hash>` vs `bf_<hash>` from ledger/0002).

**The dual representation (ledger/0002's send_* + ledger/0004's li_dm_*) is by design.** Three reasons mirror ADR-0015 §"Backfill overlap with ledger/0002":

1. **Backwards compatibility.** Operators with existing `backfill_ledger.py`-emitted history have `send_*` events for their LinkedIn touches; ledger/0004's `li_dm_*` events are additive, not replacement.

2. **Per-channel funnel observability (Pillar G).** Pillar G's dashboard reads `send_confirmed` events for "total touches sent" funnels AND `li_dm_confirmed` events for "LinkedIn DM-specific outreach activity" funnels. Both queries need their own event type.

3. **The cross-channel rule short-circuits correctly under dual representation.** Both `send_confirmed` (from ledger/0002) and `li_dm_confirmed` (from ledger/0004) carry `channel: "linkedin"` for Dana's touch; the rule's first-match-wins semantics block as expected. No double-engagement.

**Future Pillar I OSS hardening MAY ship a consolidation migration** that supersedes the ledger/0002 LinkedIn-touch emissions with the ledger/0003 + ledger/0004 LinkedIn-action-specific emissions (via the append-only "emit a superseding event" pattern). The Pillar C Week 3 commit explicitly defers this; the dual representation is operationally correct without it.

## Dry-run interaction

Per ADR-0013 D24-N + ADR-0015 §"Dry-run interaction", cross-category-dependent migrations cannot be accurately previewed in a single `dry_run()` call because the earlier migration's mutations don't land. Pillar C Week 3 inherits the limitation:

* `ledger/0004` reads Person notes' `id:` field (set by vault/0002) AND touch notes' `linkedin_action:` field (set by vault/0003). Dry-run reports zero affected because vault/0002 + vault/0003 haven't run yet.

`tests/test_migrations_replay.py::TestDryRunPreview::test_dry_run_then_real_apply_produces_same_counts_modulo_xcat_deps` pins the behavior (extended to cover ledger/0004's case). Pillar I OSS bring-up's sequenced-preview mode (deferred per ADR-0013 D24-N) addresses the limitation.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. Per-channel touch notes are operator-edited (vault is SoT for touch shape); per-channel ledger events denormalize per the existing "Send-history" SoT row. The D45 lazy-stamping `linkedin_connected:` field is denormalized from operator-verified LinkedIn UI state — the SoT for connection state remains LinkedIn itself; the vault field is a cached observation. ADR-0015 D38's invite-vs-DM classification SoT (operator-deliberate filenames + the explicit `linkedin_action:` field) carries to Week 3 unchanged.
- **I2 (two-phase commit on every external side effect):** D43's `li_dm_*` event-type shape operationalizes I2 for LinkedIn DMs. The `gated_li_dm_one` dispatcher writes `li_dm_intent` BEFORE the MCP call and `li_dm_confirmed | li_dm_failed` AFTER, mirroring `gated_li_invite_one` (per ADR-0015 D33). The MCP-call-without-intent failure mode (crash between intent-write and MCP-call) is recoverable via reconcile Pass E (shipped Week 4 — ADR-0017, commit `0191b50`).
- **I3 (schema versioning):** Pillar C per-channel ledger events follow the existing `v: 1` shape; no new vault frontmatter fields are introduced in Week 3 (the `linkedin_connected:` field per D45 is lazy-stamped per-Person, not migration-stamped — touch-note schema version stays at 1; Person-note schema version stays at 1).
- **I4 (reproducible state):** `li_dm_intent` + `li_dm_confirmed` events are durable in the append-only ledger; touch notes' `linkedin_action:` field is durable in the vault (per Week 2's vault/0003); both are recoverable via existing rebuild paths. The deterministic-hash intent_id (`_synth_intent_id`) means re-running ledger/0004 against the same vault produces byte-identical events.
- **I5 (observable by default):** ledger/0004's `migration_event` carries `channel="linkedin"` per ADR-0014 D35 + per-migration diagnostic fields (per D42 template + D43). The dispatcher emits `cost_incurred` with `source="linkedin_dm"` per D43 — Pillar G can chart per-action costs without text-matching.
- **I6 (tests prove invariants):** `tests/test_migrations_ledger_0004.py` is the direct unit test set; `tests/test_send_gate_linkedin_dm.py` exercises the dispatcher's two-phase shape + requires-connection gate; `tests/test_multi_channel_coherence.py::TestLinkedInDMChannel` un-skips 4 rows; `tests/test_migrations_replay.py` extends the exit-criterion assertions to cover Week 3's events.
- **I7 (cost is a first-class concern):** Per-channel + per-action cost emission per D43 (continuation of ADR-0015 D40). The dispatcher emits `cost_incurred` with `source="linkedin_dm"` on the success path; operators configuring a `budget.window-cap` rule on `source: linkedin_dm` see real enforcement.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains an ADR-0016 row. The Week 3 commit's per-week handoff document (`.planning/HANDOFF-pillar-c-week-3.md`) scoped the deliverables.

Does not weaken any invariant. I2's enforcement extends to LinkedIn DMs (previously the LinkedIn manifest path emitted no two-phase events for DMs; Week 3 closes that gap, mirroring Week 2's invite closure).

## Migration / rollout

The Week 3 deliverable extends the LinkedIn dispatcher coverage from invites to DMs + ships retroactive backfill + introduces the lazy-stamping `linkedin_connected:` convention.

**Operator-facing changes:**

1. **One new pending migration after `git pull`.** `runner.pending()` returns 8 (Pillar B's 5 + Pillar C Week 2's 2 + Pillar C Week 3's 1). The doctor preflight + Week 1 strict-mode feature flag (`OUTREACH_FACTORY_STRICT_MIGRATIONS=1`) surface the new migration to the operator on the next CLI run.

2. **`apply()` walks ledger/0004 in the standard apply order.** No new operator action required for the common case; operators with pre-existing LinkedIn DM state can opt out per D46.

3. **The new DM-channel `linkedin_connected:` gate is operator-deliberate.** Operators using the Week 3 dispatcher for the first time on a given Person will see the `connection_state_unknown` refuse-loud (per D44) until they stamp `linkedin_connected: true` (or `false`) on the Person note. The stamping is one-time-per-Person; subsequent DMs to the same Person bypass the gate via the vault-cached state. The dispatcher's `dedup_blocked` event carries the operator-readable detail naming the remediation path.

4. **Pre-existing operators with months of LinkedIn DM history** see retroactive `li_dm_*` events emitted by ledger/0004 unless they run the D46 seed incantation. The retroactive events are tagged `_recovered_by: "backfill"` so an operator inspecting the ledger after `apply()` can distinguish them from forward-emitted dispatcher events.

5. **The `linkedin-weekly-dm-cap` rule (hypothetical, factory-uncommented in `cooldowns.example.yml` after Pillar A's relevant cooldowns file lands) activates the moment Week 3's dispatcher emits its first `cost_incurred` event with `source="linkedin_dm"`.** Same activation pattern as ADR-0008 / ADR-0015 D40 for invites; operators uncomment the rule in their `cooldowns.yml` to opt in.

**The Week 3 commit's verification surface:**

```bash
# 1. ledger/0004 is pending; total = 8.
$ python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print(len(r.pending()))"
8

# 2. The DM coherence-test class has 4 running rows (one stays
#    skipped pending Week 4's reconcile Pass E).
$ python -m pytest tests/test_multi_channel_coherence.py::TestLinkedInDMChannel -v
# Expected: 4 passed, 1 skipped (was 5 skipped pre-Week-3).

# 3. The full suite is green at +N tests (N is approximately 50-60
#    new tests; 1215 + N = ~1265-1275 passing).
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q

# 4. ADR-0016 exists; README index gains the row; PILLAR-PLAN §6 Pillar C
#    row updated to reflect Week 3 ship.
$ ls docs/adr/0016-pillar-c-linkedin-dm-dispatcher.md
$ grep "0016" docs/adr/README.md
$ grep "Week 3" docs/PILLAR-PLAN.md

# 5. The cross-channel rule fires correctly against Week 3's
#    li_dm_confirmed events (the coherence test pins this).
$ python -m pytest tests/test_multi_channel_coherence.py::TestLinkedInDMChannel::test_li_dm_every_event_carries_channel_linkedin -v
```

## References

- ADR-0001 (policy engine architecture) — `RuleContext.channel` field; the engine surface Week 3's dispatcher's policy gate feeds.
- ADR-0003 (channel as first-class policy predicate) — the `CrossChannelTouchRule` Week 3's `li_dm_confirmed` events fire. ADR-0014 D33 pinned the naming; this ADR ships the events.
- ADR-0006 (budget rules + cost_incurred event) — the per-channel + per-action cost-emission convention Week 3's dispatcher follows.
- ADR-0009 (migration framework) — D2 sequential ID convention; ledger/0004 follows.
- ADR-0010 (ledger migrations) — D14 append-only invariant (ledger/0004 is `is_reversible=False`); D15 idempotence via deterministic intent_id; D17 `migration_event` audit-trail per migration.
- ADR-0011 (vault migrations) — D8 per-file atomicity; Week 3 does NOT ship a vault migration (Week 2's vault/0003 already stamps the `linkedin_action:` field).
- ADR-0013 (synthetic-replay exit-criterion vehicle) — D24-N dry-run limitation (Pillar C inherits); D27 `_DEFAULT_APPLY_ORDER = (VAULT, LEDGER, POLICY)` (Week 3's ledger/0004 slots in without amendment); D32 per-ADR existing-operator seed pattern (D46 instantiates).
- ADR-0014 (Pillar C foundation) — D33 channel event-type naming convention; D34 cross-category ordering reuse; D35 `channel=` kwarg; D36 per-ADR seed pattern; D37 exit-criterion vehicle.
- ADR-0015 (Pillar C Week 2 — LinkedIn invite) — D38 filename-heuristic + explicit-field convention; D39 zero-width-Unicode marker; D40 split-source cost-event convention; D41 per-migration seed pattern; D42 per-week per-channel rollout template. D43 reaffirms D40's split-source convention for DMs.
- `docs/PILLAR-PLAN.md` §2 Pillar C — exit criterion (binding text); §6 Pillar C row updated to reflect Week 3 ship.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D44's refuse-loud posture on unknown connection state.
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — risk this ADR mitigates by design via the dispatcher's correct `channel: linkedin` stamping + the cross-channel rule's automatic firing against `li_dm_confirmed` events.
- `docs/SOURCES-OF-TRUTH.md` — per-channel touch notes inherit the existing "Touch notes" row's SoT semantics; per-channel ledger events inherit "Send-history."
- `.planning/HANDOFF-pillar-c-week-2.md` — the prior week's handoff documenting Week 2's deliverables.
- `.planning/HANDOFF-pillar-c-week-3.md` — the handoff that scoped this commit's deliverables.
- `.planning/HANDOFF-pillar-c-week-4.md` — the next week's handoff scoping reconcile passes D + E.
- `orchestrator/migrations/ledger/migration_0004_baseline_li_dm_history.py` — the migration ledger/0004.
- `orchestrator/ledger.py` — `_OUTCOME_TYPES` + `_INTENT_TYPES` + `_CONFIRMED_TYPES` already include `li_dm_*` types per Week 2's generalization; Week 3 ships the events that exercise the indexer.
- `orchestrator/policy/cross_channel.py` — the rule class Week 3's events fire (no code change needed; the rule's forward-references in ADR-0003 already accommodate `li_dm_confirmed`).
- `skills/send-outreach/scripts/send_queued.py` — `gated_li_dm_one` (Week 3's dispatcher); `_li_dm_vault_writeback`; `_read_person_linkedin_connected`; `_stamp_person_linkedin_connected`; `LI_DM_INTENT_MARKER_TEMPLATE`; `LINKEDIN_DM_BODY_MAX_CHARS`.
- `tests/test_multi_channel_coherence.py::TestLinkedInDMChannel` — un-skipped Week 3 (was 5 skipped pre-Week-3; 4 of 5 now pass; 1 stays skipped pending Week 4 reconcile Pass E).
- `tests/test_migrations_ledger_0004.py` — Week 3 ships the direct unit tests.
- `tests/test_send_gate_linkedin_dm.py` — Week 3 ships the dispatcher gate tests (including the requires-existing-connection gate per D44).
- `tests/test_policy_cross_channel.py::TestCrossChannelAgainstLiveLinkedInDMShape` — Week 3 ships the cross-channel-rule live-shape tests.
- `tests/fixtures/synthetic_pillar_b/` — extended with Dana Davis Person + her LinkedIn DM touch (Pillar C Week 3 fixture extension).
- Forward-references (planned):
  - **ADR-0017** (Pillar C Week 4): Reconcile passes D (LinkedIn invites — recovers `li_invite_intent` crashes via the ADR-0015 D39 marker) + E (LinkedIn DMs — recovers `li_dm_intent` crashes via the D43 marker).
  - **ADR-0018** (Pillar C Week 5): Twitter DM dispatcher + reconcile Pass F.
  - **ADR-0019** (Pillar C Week 6): Calendar booking dispatcher + Cal.com webhook + reconcile Pass G.
  - **Pillar I CLI** (Weeks 43–48): aggregation of D46 per-ADR seed blocks into `python -m orchestrator.migrations seed --pillar-c --channel linkedin_dm`; the lazy-stamping `linkedin_connected:` field exposed as a `python -m orchestrator.linkedin mark-connected <person>` command.
