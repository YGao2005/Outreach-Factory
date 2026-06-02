# ADR-0015: Pillar C Week 2 — LinkedIn invite dispatcher, retroactive backfill, and per-channel rollout convention

- **Status:** Accepted
- **Date:** 2026-05-21
- **Pillar:** C (Multi-channel coherence — Week 2)
- **Deciders:** Yang, Claude (architect)

## Context

Pillar C Week 1 (ADR-0014) shipped the convention-setting decisions every per-channel week composes against: D33 channel event-type naming (`li_invite_*` etc.), D34 cross-category ordering reuse, D35 `channel=` kwarg on `migration_event`, D36 per-ADR existing-operator seed pattern, D37 `tests/test_multi_channel_coherence.py` exit-criterion vehicle. Week 2 is the **first per-channel week** — the template every subsequent per-channel week (Week 3 LinkedIn DM, Week 5 Twitter DM, Week 6 calendar booking) replicates modulo per-channel semantic differences. The substrate Week 1 set is now load-bearing.

The five concerns Week 2 resolves:

1. **Pre-Pillar-C LinkedIn touches need a backfill, but invite-vs-DM distinction lives in filenames, not frontmatter.** Operators' touch notes are named "linkedin invite" or "linkedin dm" but their frontmatter typically just says `channel: linkedin`. The Week 2 backfill migration (`ledger/0003_baseline_li_invite_history`) needs to discriminate invite vs DM so it emits `li_invite_*` events ONLY for invite touches (Week 3's `ledger/0004_baseline_li_dm_history` walks the DM touches). D38 pins the heuristic + the explicit-field convention going forward.

2. **MCP-mediated LinkedIn invites have a different intent-id round-trip surface than Gmail's `extra_headers`.** Gmail lets us round-trip an `X-Outreach-Intent-Id` header invisibly + recover via `reconcile.Pass A` by querying sent messages. LinkedIn's MCP (`mcp__linkedin__connect_with_person`) doesn't expose a "set custom header" surface; the connection note text is the only round-trip channel. D39 pins the marker scheme + the reconcile-Pass-D-Week-4 dependency.

3. **The `linkedin-weekly-invite-cap` rule (ADR-0008) ships factory-commented in `cooldowns.example.yml`, waiting for the Pillar C dispatcher to emit `cost_incurred` events.** Activating the rule is operator-deliberate (uncomment + reload). The Week 2 dispatcher must emit `cost_incurred` events with `source="linkedin_invite"` matching the rule's `source:` field exactly — without that, the rule activates but reports zero usage, silently allowing over-quota sends. D40 names what Week 2 does (emit the event) and what Week 2 does NOT do (auto-uncomment the rule).

4. **Existing operators (Yang) have months of LinkedIn invite history from the pre-Pillar-C MCP-mediated flow.** The retroactive `ledger/0003` backfill emits `li_invite_intent` + `li_invite_confirmed` pairs against these touches; an operator who wants their historical state preserved as-is (no retroactive emissions) needs the one-time `mark_applied` incantation per ADR-0014 D36. D41 instantiates the D36 template for `ledger/0003` + the companion `vault/0003`.

5. **Future per-channel weeks inherit this week's pattern.** Week 3 (LinkedIn DM), Week 5 (Twitter DM), Week 6 (calendar booking) each ship the same per-week deliverable shape: a per-channel dispatcher + a per-channel retroactive backfill migration + a per-channel ADR. D42 names the impact across Pillars D / E / F / G / H / I / J so downstream-pillar planners know what Week 2 commits them to + what subsequent per-channel weeks will add.

A sixth concern surfaces only on close inspection: **`ledger/0003` and `ledger/0002` both emit two-phase pairs for the same LinkedIn touch.** Alice's LinkedIn touch on 2026-04-18 (the synthetic fixture) produces both a `send_intent`+`send_confirmed` pair (ledger/0002 walks every `sent: true` touch regardless of channel) AND a `li_invite_intent`+`li_invite_confirmed` pair (ledger/0003 walks LinkedIn invites specifically). The dual representation is by design — see §"Backfill overlap with ledger/0002" below for the rationale + why this doesn't surface as cross-channel double-engagement.

Risks this ADR mitigates by design: **R011 (cross-channel double-engagement)** — the LinkedIn invite dispatcher's `li_invite_confirmed` events fire the existing cross-channel rule (ADR-0003) the moment they land in the ledger. Pillar C Week 1's coherence test vehicle (D37) pins this end-to-end starting Week 2.

## Decision

### D38. Pre-Pillar-C invite-vs-DM distinction via filename heuristic; explicit `linkedin_action:` field going forward

Pre-Pillar-C touch notes are classified invite vs DM via a filename-pattern heuristic for backfill ONLY:

* Filename matches `\b(?:invite|connect)\b` (case-insensitive, word-boundary) → `linkedin_action: invite`. The migration emits `li_invite_*` events; Week 3's `ledger/0004` skips.
* Filename matches `\b(?:dm|message)\b` → `linkedin_action: dm`. The migration skips (Week 3's `ledger/0004` will pick up).
* Default (neither pattern matches) → `linkedin_action: invite`. The migration emits. Rationale: pre-Pillar-C touch notes empirically tend to be invites (the LinkedIn DM register landed in the `draft-outreach` skill later than the connection-request register did); the historical-prevalence default reduces operator manual triage from O(N touches) to O(1 default + manual override for unusual cases).

Going forward, the Pillar C LinkedIn dispatcher writes an explicit `linkedin_action: invite | dm` frontmatter field on every new touch note. The companion vault migration `vault/0003_add_linkedin_action_to_touch_notes` backports the field to historical touches via the same heuristic.

**The explicit field always wins over the heuristic.** A touch note with `linkedin_action: dm` set is classified as DM regardless of filename. Operators with non-conventional filenames stamp the field manually before running `ledger/0003`, OR they can audit + correct after `vault/0003` runs (the migration logs each classification at INFO level).

**Word-boundary matching is load-bearing.** A touch note named "Connecticut intro.md" must NOT classify as invite (no whole-word "connect" or "invite"); `\b...\b` ensures the regex matches `(?:invite|connect)` only as standalone words, not as substrings.

### D39. Intent-id correlation via zero-width-Unicode marker in connection note text

Pillar C reconcile Pass D (Week 4) recovers crashes between `li_invite_intent` and `li_invite_confirmed` writes by querying the LinkedIn MCP's sent-invitations surface for invitations matching the operator's pending intent ids. The matching surface is the **connection note text**, which is the only payload `mcp__linkedin__connect_with_person` round-trips through the MCP.

The Week 2 dispatcher embeds the intent_id as a zero-width-Unicode marker appended to the connection note text:

```
{operator-supplied note body}
​outreach-intent:<intent_id>​
```

The leading and trailing characters are U+200B (zero-width space) — invisible to the recipient in LinkedIn's UI; preserved through LinkedIn's note storage; recoverable by scanning the operator's outbox via the MCP's `get_sent_invitations` surface. Same shape as the email body footer (`INTENT_FOOTER_TEMPLATE` per `send_queued.py:79`), differing only in:

* Marker length (~30 chars vs email's ~28). LinkedIn personal-account connection notes have a 300-char limit; the marker eats ~10% of the budget.
* No "header" round-trip path. Gmail's `extra_headers` is a second redundant surface (per `send_queued.py:442`); LinkedIn has only the body text.

**Reconcile correlation (shipped Week 4 — ADR-0017, commit `0191b50`).** Week 2 ships the marker emission; Week 4's `reconcile.py::run_pass_d` walks `li_invite_intent` events without matching `_confirmed` outcomes, queries the LinkedIn client's sent-invitations surface for recent invitations, and looks for the marker in each invitation's note text. The intent's reconcile path is symmetric to email's Pass A.

**Operator outreach-text discipline (recommended).** Operators should keep their LinkedIn connection notes ≤270 chars (vs the 300 hard limit) so the ~30-char marker doesn't push the total over LinkedIn's enforcement boundary. The `draft-outreach` skill's `voice-li-connect` register already targets ≤250 chars per UX research; the marker discipline is consistent with existing guidance.

### D40. Activate ADR-0008's `linkedin-weekly-invite-cap` rule via `cost_incurred` emission; no new policy migration in Week 2

ADR-0008 ships the `linkedin-weekly-invite-cap` rule factory-commented in `cooldowns.example.yml` (lines 220-240 — the rule's transitional-emit-site note explicitly anticipates Pillar C). Week 2's LinkedIn dispatcher emits a `cost_incurred` event with `source="linkedin_invite"` per the existing ADR-0006 convention on every successful invite send. The moment an operator uncomments the rule in their `cooldowns.yml`, the rule starts enforcing — the activation gap closes per the existing convention.

**Week 2 does NOT ship a policy migration to auto-uncomment the rule.** Two reasons:

1. **Operator-deliberate activation per ADR-0008.** The rule's existence in `cooldowns.example.yml` is operator-visible documentation; activating it is an operator-deliberate edit (uncomment the block). Auto-activating via migration would surface as "outreach-factory silently started rate-limiting my LinkedIn invites" — a Mode change Pillar I OSS bring-up handles deliberately with operator-visible release notes, not Pillar C Week 2 invisibly.

2. **The factory rule's parameters (window_days=7, max_units=100) are LinkedIn's personal-account terms.** Operators on LinkedIn Sales Navigator (different cap) or LinkedIn enterprise plans (different cap) will tune the parameters themselves; auto-uncommenting the factory rule would force operators to either accept the factory parameters or delete + re-add. Operator override discipline is the right friction here.

**The `cost_incurred` field convention is load-bearing.** The Week 2 dispatcher MUST emit `source="linkedin_invite"` exactly (not `"linkedin"` or `"linkedin_connect"`). The rule's `source:` field in `cooldowns.example.yml` is `linkedin_invite`; a mismatch silently breaks the activation. Pillar C Week 3 (LinkedIn DM) emits `source="linkedin_dm"` separately so the operator can configure separate caps for invites vs DMs (LinkedIn's enforcement on DMs to existing connections differs from connection-request limits).

**Why `source="linkedin_invite"` not `source="linkedin"`.** ADR-0006 §"Source taxonomy" pins per-action-class sources (`gmail`, `apollo`, `pdl`). `linkedin` is too coarse — a Pillar C operator who wants "block any LinkedIn action beyond N/week" combines a `cross-channel` rule with per-source budget caps. Splitting `linkedin_invite` vs `linkedin_dm` matches the per-action-class taxonomy.

### D41. Existing-operator seed instructions for `ledger/0003` + `vault/0003`

Operators with pre-existing LinkedIn invite touches (Yang specifically; future OSS operators with pre-Pillar-C LinkedIn history) may want to skip the retroactive backfill — their historical state is what it is, and re-emitting backfill events would churn the ledger. Per ADR-0014 D36, this ADR provides the §"Existing-operator seed" REPL incantation.

#### Skipping `ledger/0003` only

For operators who want their pre-Pillar-C LinkedIn invite ledger state preserved as-is (no `li_invite_*` events emitted retroactively):

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
    state, MigrationCategory.LEDGER, "0003_baseline_li_invite_history",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `ledger/0003` as applied; `apply()` skips it; the operator's LinkedIn invite history stays exactly as it was pre-Week-2 (touch notes + no ledger events).

#### Skipping `vault/0003` only

For operators who want their pre-Pillar-C LinkedIn touch notes to remain frontmatter-unchanged (no `linkedin_action:` field stamped retroactively):

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
    state, MigrationCategory.VAULT, "0003_add_linkedin_action_to_touch_notes",
    now=now, runner_version="0.1.0",
)
save_state_atomic(DEFAULT_STATE_DIR, state)
```

After running this, the migration runner reports `vault/0003` as applied; `apply()` skips it. `ledger/0003` (if not also seed-skipped) will fall back to the filename heuristic for invite-vs-DM classification.

#### Recommended posture per operator profile

| Operator profile | Recommended action |
|---|---|
| New OSS operator (zero pre-Pillar-C LinkedIn history) | Run `apply()` normally. Both migrations emit zero events (no touch notes to walk); the migration_event audit trail records the no-op for continuity. |
| Existing operator who wants historical events preserved as-is | Seed BOTH migrations. The pre-existing touch notes remain unstamped (the field is forward-only); the ledger contains no retroactive events. New touches via the Week 2 dispatcher carry `linkedin_action:` from the dispatcher itself. |
| Existing operator who wants the retroactive emissions for cross-channel rule activation | Run `apply()` normally. `ledger/0003` emits the backfill pairs; the cross-channel rule starts firing against historical LinkedIn invites the moment a future email send attempt evaluates against them. |
| Yang (current sole operator, as of 2026-05-21) | Recommended: run `apply()` normally. Yang's pre-Pillar-C LinkedIn invite history is small (the practical risk of cross-channel rule mis-fires against backfilled events is low) and the explicit-field migration (`vault/0003`) is operator-inspectable (the INFO log records each classification). |

**Why one block per migration and not a combined seed.** Per ADR-0014 D36 + ADR-0013 D32 — Pillar I OSS bring-up's CLI aggregates per-ADR seed blocks mechanically. The combined seed would be a Pillar-C-specific tool that Pillar I would then have to consolidate; the per-migration blocks compose into Pillar I's `python -m orchestrator.migrations seed --pillar-c --channel linkedin_invite` without further work.

### D42. Per-week per-channel rollout convention (template for Weeks 3 / 5 / 6)

Week 2 establishes the per-channel-week deliverable shape. Subsequent per-channel weeks (3, 5, 6) replicate the structure modulo per-channel semantics:

| Deliverable | Week 2 (LinkedIn invite) | Week 3 (LinkedIn DM) | Week 5 (Twitter DM) | Week 6 (calendar booking) |
|---|---|---|---|---|
| Vault migration | `vault/0003_add_linkedin_action_to_touch_notes` | (re-uses `linkedin_action: dm` set by vault/0003) | `vault/0004_add_twitter_handle_to_touch_notes` (planned) | `vault/0005_add_calendar_link_to_touch_notes` (planned) |
| Ledger migration | `ledger/0003_baseline_li_invite_history` | `ledger/0004_baseline_li_dm_history` | `ledger/0005_baseline_tw_dm_history` | `ledger/0006_baseline_calendar_history` |
| Dispatcher | `gated_li_invite_one` in `send_queued.py` | `gated_li_dm_one` (planned) | `gated_tw_dm_one` (planned) | `gated_calendar_booking_one` (planned) |
| MCP integration | `mcp__linkedin__connect_with_person` | `mcp__linkedin__send_message` | Stealth-fetch cookie-scrape | Cal.com webhook |
| Intent-id round-trip | Connection note marker (D39) | DM body marker (Week 3 ADR) | Stealth-fetch token (Week 5 ADR) | URL fragment (Week 6 ADR) |
| Cost-event source | `linkedin_invite` | `linkedin_dm` | `twitter_dm` | `calendar_booking` |
| Coherence test class | `TestLinkedInInviteChannel` un-skipped | `TestLinkedInDMChannel` un-skipped | `TestTwitterDMChannel` un-skipped | `TestCalendarBookingChannel` un-skipped |
| ADR number | 0015 (this) | 0016 (planned) | 0018 (planned) | 0019 (planned) |
| Reconcile-pass un-skip | Week 4 (Pass D) | Week 4 (Pass E) | Week 5 (Pass F) | Week 6 (Pass G) |

**The shape is symmetric — Week 3+ authors copy Week 2's structure with per-channel substitutions.** Per-week independent review checks that the shape carries: per-week handoff + per-week ADR + per-week ledger migration + (optionally) per-week vault migration + per-week dispatcher + per-week tests + per-channel coherence-test un-skips. A week that ships a dispatcher without un-skipping the coherence-test rows is incomplete by the per-week review's discipline.

**The MCP integration shape varies by channel.** LinkedIn's MCP exposes a structured connect/send API; Twitter has no public DM API for individuals (cookie-scrape required per Pillar A's `OUTREACH_FACTORY_LIVE_TESTS=1` convention); Cal.com is webhook-driven (push, not poll). Per-channel ADR §"MCP integration" subsections capture the per-channel idiosyncrasies; Week 2's D39 is the LinkedIn-specific version of the more general convention.

## Alternatives considered

### D38-Alt1: Require operators to manually stamp `linkedin_action:` on every pre-Pillar-C touch before running ledger/0003

The migration refuses to emit pairs for touches without an explicit `linkedin_action:` frontmatter field; operators with N pre-Pillar-C touches must audit + stamp all N. **Rejected** because:

* O(N) operator work for a feature that has a reasonable default. Yang's pre-Pillar-C touch count is small but the OSS bring-up's first wave of operators may have hundreds; forcing manual triage would block adoption.
* The filename heuristic is operator-inspectable + auditable (`vault/0003` logs every classification at INFO level). An operator who disagrees with the heuristic can post-hoc edit + re-run with the `_seed` path.
* The default-to-invite case is safe-by-construction: emitting a `li_invite_*` pair for a touch that was actually a DM produces a one-time double-emission (Week 3's `ledger/0004` won't re-emit for the same intent_id because the deterministic-hash dedup catches the existing `li_invite_*` event). The mis-classification's blast radius is the operator's ledger reports being slightly off for the affected touches — recoverable in a future audit migration; not load-bearing on cross-channel rule correctness because the cross-channel rule fires on ANY `*_confirmed` event matching `consider_channels: [linkedin]` regardless of invite vs DM prefix.

### D38-Alt2: Use frontmatter `dm_text:` field presence as the heuristic (touches with `dm_text:` set → DM; without → invite)

The `dm_text:` field is set on touch notes that include a draft DM body; invites typically have no DM body (the LinkedIn personal-account free tier doesn't support connection notes for most operators per `_emit_linkedin_manifest`'s legacy path). **Rejected** because:

* `dm_text:` is not universally set on DM touches — operators draft DMs in the body content of the touch note (the `## LinkedIn DM` block), not the frontmatter. The frontmatter signal is unreliable.
* Connection notes (when the operator's account supports them) DO use a body — the field-presence heuristic would mis-classify connection-note-with-body invites as DMs.
* The filename heuristic is the operator-deliberate signal: operators NAMED their files "linkedin invite" or "linkedin dm" precisely because they were thinking about the distinction at write time.

### D38-Alt3: Default to DM (not invite) when neither pattern matches

Symmetric inversion of D38. **Rejected** because the historical-prevalence calculus inverts: pre-Pillar-C LinkedIn touches were predominantly invites (the `draft-outreach` skill's LinkedIn register shipped invite-first; DMs were added later). Defaulting to DM would mis-classify the majority case as the minority. Operators with DM-heavy pre-Pillar-C state can run `vault/0003` then bulk-edit the stamped fields before running `ledger/0003` — an O(K-edits) workflow where K is small.

### D39-Alt1: Embed intent_id as an explicit YAML block at the END of the connection note text

```
{operator-supplied body}

---
outreach-intent: {intent_id}
---
```

**Rejected** because:

* Connection notes don't support YAML rendering; the literal `---` characters would appear in the recipient's invite preview. Less invisible than the zero-width-space marker.
* LinkedIn's 300-char limit is more constrained with multi-line markers than single-line ones. The zero-width-space marker is ~30 chars (no newline overhead); the YAML block is ~50+ chars.
* The zero-width-space invisibility matches email's body-footer convention (`​outreach-intent:<intent_id>​`); operators reading both ledgers via reconcile output see one convention.

### D39-Alt2: Skip intent-id round-trip entirely; recover crashes by querying LinkedIn for recent invitations + matching by timestamp

Reconcile Pass D walks `li_invite_intent` events without outcomes; queries the MCP for sent invitations in the last N hours; correlates by timestamp + recipient profile URL. **Rejected** because:

* Timestamp correlation is fragile under operator concurrency. If the operator sent two LinkedIn invites to different people within the same minute (Pillar H daemon parallelism makes this realistic), the timestamp-match heuristic would correlate incorrectly under crash.
* Profile-URL correlation is less fragile but slower (multi-page result iteration via the MCP's `get_sent_invitations` surface; up to 10+ seconds per reconcile pass).
* The marker scheme costs ~30 chars of note budget; the timestamp-correlation scheme costs reliability + reconcile latency. The marker wins on correctness.

### D39-Alt3: Use the `client_token` / `tracking_id` field if LinkedIn's MCP exposes one

Some LinkedIn API surfaces (the official partner API, not the personal-account MCP) accept an opaque tracking token round-trippable through the sent-invitations response. **Rejected for Week 2** because the `mcp__linkedin__connect_with_person` MCP that this dispatcher uses does NOT expose such a field (the connection-note text IS the only round-trip surface). A future LinkedIn MCP upgrade that adds tracking-token support would be a follow-up amendment to this ADR; Week 2 ships against the actual MCP surface, not a hypothetical future one.

### D40-Alt1: Ship a policy migration that auto-uncomments the factory rule in `cooldowns.example.yml`

A migration walks the operator's `cooldowns.yml`; if the file contains the commented `linkedin-weekly-invite-cap` block, uncomments it. **Rejected** because:

* The factory rule's parameters are LinkedIn's personal-account terms. Operators on other plans need different parameters; the auto-uncomment forces the wrong defaults onto them.
* Operator-deliberate activation per ADR-0008 is the established convention. Pillar C Week 2 should not invent a new convention that diverges from Pillar A.
* If activating-by-default was the right choice, ADR-0008 would have shipped the rule uncommented in the first place. The rule shipped commented BECAUSE the activation is operator-deliberate.

### D40-Alt2: Ship the cost emission but a DIFFERENT `source` value (e.g. `source="linkedin"`)

Drop the `_invite` suffix so the factory rule + future LinkedIn DM dispatcher (Week 3) share one budget. **Rejected** because the operator's likely-intent is per-action caps (per-invite cap because LinkedIn's invite-spam enforcement is harsher than DM-spam enforcement). Sharing a budget across invites + DMs forces operators who want per-action caps to write per-channel-policy rules per action — more YAML, not less. The split-source convention is the lower-friction default.

### D41-Alt1: Auto-detect pre-Pillar-C LinkedIn state + refuse to apply without operator confirmation

The migration walks for any pre-existing touch note with `channel: linkedin` AND `sent: true`; if found, refuses to apply automatically + prints the seed instruction. **Rejected** per the ADR-0014 D36-Alt3 precedent — the auto-detect heuristic is fragile (an operator who imported historical LinkedIn data from a CSV trips the heuristic), and the new-operator case (zero pre-existing state) should run frictionlessly without intervention. The explicit operator-supplied signal (the seed `mark_applied` call) is the safe shape.

### D41-Alt2: Combine `ledger/0003` + `vault/0003` seed into a single Pillar-C-LinkedIn-invite block

A single block that marks both migrations applied. **Rejected** per ADR-0014 D36 — Pillar I OSS bring-up's CLI aggregates per-migration seed blocks mechanically; a combined block would be a Pillar-C-specific tool that Pillar I would then have to disaggregate. The per-migration blocks compose into Pillar I's `--migration <id>` filter without rewriting.

### D42-Alt1: Defer the per-channel-week template to Pillar I OSS bring-up

Week 2 ships its own deliverable shape; subsequent per-channel weeks (3 / 5 / 6) figure out their own structure. **Rejected** explicitly by Pillar B Week 5's retrospective ("design the cross-channel coherence test in Week 1, not Week N") — the same structural-intervention rationale carries to per-channel-week structure. Without a Week 2 template, Week 3 would re-derive every per-week deliverable choice (does it ship a vault migration? what's the cost-event source? what's the MCP integration shape?) — a per-week-rederivation overhead that compounds across four channels.

### D42-Alt2: Make the per-channel-week template a separate doc (`docs/PILLAR-C-PER-CHANNEL-WEEK-TEMPLATE.md`) rather than an ADR section

A standalone document outside any ADR. **Partially accepted, but the inline ADR section captures the same benefit.** The template's load-bearing content (the table in D42) is six rows × eight columns — fits comfortably in an ADR. A standalone document would be a separate operator-facing surface that diverges from the per-ADR convention Pillar B established. The inline placement keeps the template adjacent to the Week 2 design context that motivates it.

### D42-Alt3: Aggregate the per-channel templates into a Pillar C exit-criterion checklist

A `tests/test_pillar_c_exit_criterion.py` (separate from `test_multi_channel_coherence.py`) that exercises the template's row-by-row contract. **Rejected** per ADR-0014 D37 — `test_multi_channel_coherence.py` is the exit-criterion vehicle; an additional checklist file would split the operator-facing surface. The per-week independent review's discipline (every per-channel week un-skips its coherence-test class's rows) is the runtime check; the D42 table is the design-time check.

### Existing-operator seed pattern (no separate alternative — established by ADR-0014 D36)

The per-ADR §"Existing-operator seed" subsection is the established convention. Pillar I OSS bring-up's CLI (`python -m orchestrator.migrations seed --pillar-c`) aggregates from per-ADR blocks. No standalone alternative is needed; the convention IS the alternative-set's resolution.

## Backfill overlap with `ledger/0002`

`ledger/0002_backfill_send_history` walks every `sent: true` touch regardless of channel and emits `send_intent` + `send_confirmed` pairs with the `channel:` field set to the touch's channel value (the Pillar C Week 1 fix ensures this carries to the confirmed event). For Alice's LinkedIn touch on 2026-04-18, ledger/0002 emits a `send_intent`+`send_confirmed` pair with `channel: "linkedin"`.

`ledger/0003_baseline_li_invite_history` walks LinkedIn invite touches specifically and emits `li_invite_intent` + `li_invite_confirmed` pairs with `channel: "linkedin"`. For Alice's same touch, ledger/0003 emits a separate pair with a distinct intent_id (`bf_li_<hash>` vs `bf_<hash>`).

**The dual representation is by design.** Three reasons:

1. **Backwards compatibility.** Operators with existing `backfill_ledger.py`-emitted history (Phase 5.5 Week 2 — the pre-migration backfill script) have `send_*` events for their LinkedIn touches; ledger/0003's `li_invite_*` events are additive, not replacement. Migrating the existing events in-place would violate the append-only-ledger invariant (ADR-0010 D14).

2. **Per-channel funnel observability (Pillar G).** Pillar G's dashboard reads `send_confirmed` events for "total touches sent" funnels AND `li_invite_confirmed` events for "LinkedIn-specific outreach activity" funnels. Both queries need their own event type — collapsing into one would break one or the other query.

3. **The cross-channel rule short-circuits correctly under dual representation.** ADR-0003's `CrossChannelTouchRule` matches any event whose `type.endswith("_confirmed")` AND whose `channel` is in `consider_channels`. Both `send_confirmed` (from ledger/0002) and `li_invite_confirmed` (from ledger/0003) carry `channel: "linkedin"` for Alice's touch; the rule's first-match-wins semantics block as expected. No double-engagement occurs because the rule fires once and short-circuits.

**Future Pillar I OSS hardening MAY ship a consolidation migration** that supersedes the ledger/0002 LinkedIn-touch emissions with the ledger/0003 LinkedIn-invite emissions (via the append-only "emit a superseding event" pattern from ADR-0010). The Pillar C Week 2 commit explicitly defers this; the dual representation is operationally correct without it.

## Dry-run interaction

Per ADR-0013 D24-N, cross-category-dependent migrations cannot be accurately previewed in a single `dry_run()` call because the earlier migration's mutations don't land. Pillar C Week 2 inherits the limitation:

* `vault/0003` reads touch notes' `channel:` field (set by operators historically, not by an earlier migration) and stamps `linkedin_action:`. Dry-run reports the count it WOULD stamp accurately.
* `ledger/0003` reads Person notes' `id:` field (set by vault/0002) AND touch notes' `linkedin_action:` field (optionally set by vault/0003). Dry-run reports zero affected because vault/0002 + vault/0003 haven't run yet.

`tests/test_migrations_replay.py::TestDryRunPreview::test_dry_run_then_real_apply_produces_same_counts_modulo_xcat_deps` pins both behaviors. Pillar I OSS bring-up's sequenced-preview mode (deferred per ADR-0013 D24-N) addresses the limitation.

## Downstream pillar impact

Per the ADR-0009 / 0010 / 0011 / 0012 / 0013 / 0014 convention (every Pillar B + C ADR explicitly names cross-pillar impact):

* **Pillar D (reply + conversation handling).** Pillar D's reply joiner correlates `li_invite_reply_received` events (per ADR-0025 D96's per-channel-prefixed naming convention; supersedes the generic `reply_received` placeholder this paragraph used pre-ADR-0025) to their originating `li_invite_confirmed` by `intent_id`. The Week 2 dispatcher's `li_invite_confirmed` stamps the LinkedIn `linkedin_invitation_id` (when the MCP returns it); Pillar D's joiner reads BOTH `intent_id` (Pillar C's canonical correlator) AND `linkedin_invitation_id` (LinkedIn's canonical correlator) for double-check robustness. The `linkedin_action: invite` field on touch notes lets Pillar D distinguish invite-accepted-then-replied from DM-replied-directly conversation states.

* **Pillar E (discovery quality + lineage).** No direct interaction. Pillar E adds `discovery_lineage:` blocks to Person frontmatter; per-touch LinkedIn fields are orthogonal. Pillar E's `discovery_lineage:` may include a `discovered_via_linkedin:` field that ties to a Pillar C `li_invite_confirmed` event — the cross-pillar query is one join, no Pillar C schema change.

* **Pillar F (voice corpus + draft quality).** Pillar F's voice-fidelity scoring operates on touch body content (the connection-note text). The Week 2 dispatcher's intent-id marker (D39) appends to the body; Pillar F's voice-scorer must strip the marker before scoring or the scorer would penalize the marker's "AI-shape" artifacts. The marker is at a known position (end of text) and surrounded by zero-width spaces — Pillar F's text-cleanup step strips it deterministically.

* **Pillar G (observability).** Pillar G's per-channel migration audit-trail dashboard reads ledger/0003's `migration_event` event filtered by `channel="linkedin"` per ADR-0014 D35; the Week 2 migration's diagnostic fields (`linkedin_pairs_emitted`, `linkedin_pairs_skipped`, `touches_without_person_match`, `touches_skipped_not_invite`) become per-migration observability rows. Pillar G's per-channel funnel dashboard reads `li_invite_intent` / `li_invite_confirmed` / `li_invite_failed` events with `channel: linkedin` per D33 — one query per funnel state.

* **Pillar H (daemon + dispatcher).** Pillar H's per-stage parallelism limits become per-channel + per-action (e.g. "no more than N concurrent LinkedIn invite sends"; "no more than M concurrent LinkedIn DM sends"). The Week 2 `cost_incurred` event's `source="linkedin_invite"` is the discriminator Pillar H's dispatcher uses to throttle independently from LinkedIn DM throughput.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel state isolation. The D41 existing-operator-seed blocks aggregate into Pillar I's CLI as `python -m orchestrator.migrations seed --pillar-c --channel linkedin_invite` (or the looser `--pillar-c` aggregates every Pillar C ADR's seed blocks). The OSS bring-up's per-operator config knob `vault.conversations_dir` should propagate into ledger/0003 + vault/0003 (Pillar B Week 6's deferred work surfaces here for Pillar I per the existing carry-over).

* **Pillar J (security + compliance).** GDPR-forget on a Person who has LinkedIn invite touches: the touch notes are deleted (Pillar J's forget tooling per ADR-0010's pattern), and per-Person `li_invite_*` events are tombstoned. The Week 2 dispatcher's `linkedin_invitation_id` field (when populated from the MCP's response) is potentially-PII — Pillar J's forget tooling redacts it on tombstone.

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. Per-channel touch notes are operator-edited (vault is SoT for touch shape); per-channel ledger events denormalize per the same I1 row "Send-history" that covers email today. The D38 explicit `linkedin_action:` field is denormalized from operator-edited filenames + per-touch operator overrides; the SoT for invite-vs-DM remains the operator's deliberate naming + (in the dispatcher's forward path) the operator's choice of action.
- **I2 (two-phase commit on every external side effect):** D33's `li_invite_*` event-type shape operationalizes I2 for LinkedIn invites. The `gated_li_invite_one` dispatcher writes `li_invite_intent` BEFORE the MCP call and `li_invite_confirmed | li_invite_failed` AFTER, mirroring email's `gated_send_one` shape exactly. The MCP-call-without-intent failure mode (crash between intent-write and MCP-call) is recoverable via reconcile Pass D (shipped Week 4 — ADR-0017, commit `0191b50`).
- **I3 (schema versioning):** Pillar C per-channel ledger events follow the existing `v: 1` shape; the `vault/0003` vault migration adds a new frontmatter field (`linkedin_action:`) to touch notes — touch-note schema version stays at 1 (the field is additive, the schema-evolution contract is "fields are additive within a major version per the existing Phase 5.5 convention"). No I3 schema-version bump.
- **I4 (reproducible state):** `li_invite_intent` + `li_invite_confirmed` events are durable in the append-only ledger; touch notes' `linkedin_action:` field is durable in the vault; both are recoverable via the existing `rebuild_vault.py` + ledger-backup paths. The deterministic-hash intent_id (`_synth_intent_id`) means re-running ledger/0003 against the same vault produces byte-identical events. No I4 change required.
- **I5 (observable by default):** ledger/0003's `migration_event` carries `channel="linkedin"` per ADR-0014 D35 + per-migration diagnostic fields (per the D42 template). The dispatcher emits `cost_incurred` with `source="linkedin_invite"` per ADR-0006 — Pillar G can chart per-channel costs without text-matching.
- **I6 (tests prove invariants):** `tests/test_migrations_ledger_0003.py` + `tests/test_migrations_vault_0003.py` are direct unit tests; `tests/test_send_gate_linkedin.py` exercises the dispatcher's two-phase shape + gate sequence; `tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel` un-skips 6 rows; `tests/test_migrations_replay.py` extends the exit-criterion assertions to cover Week 2's events.
- **I7 (cost is a first-class concern):** Per-channel cost emission per D40. The dispatcher emits `cost_incurred` with `source="linkedin_invite"` on the success path; the linkedin-weekly-invite-cap rule activates once operator-uncommented.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains an ADR-0015 row. The Week 2 commit's per-week handoff document (`.planning/HANDOFF-pillar-c-week-2.md`) scoped the deliverables.

Does not weaken any invariant. I2's enforcement extends to LinkedIn invites (previously the LinkedIn manifest path was pre-two-phase; Week 2 closes that gap).

## Migration / rollout

The Week 2 deliverable replaces the pre-Pillar-C LinkedIn manifest path with a two-phase dispatcher + ships retroactive backfill + ships the explicit-field convention.

**Operator-facing changes:**

1. **Two new pending migrations after `git pull`.** `runner.pending()` returns 7 (Pillar B's 5 + Pillar C Week 2's 2). The doctor preflight + Week 1 strict-mode feature flag (`OUTREACH_FACTORY_STRICT_MIGRATIONS=1`) surface the new migrations to the operator on the next CLI run.

2. **`apply()` walks vault/0003 + ledger/0003 in the standard apply order.** No new operator action required for the common case; operators with pre-existing LinkedIn state can opt out per D41.

3. **The pre-Week-2 LinkedIn manifest emission (`_emit_linkedin_manifest`) remains in the codebase as a legacy fallback** for operators who haven't migrated to the two-phase dispatcher yet. Pillar I OSS bring-up's release notes will name the manifest path as deprecated; Pillar I CLI's `send` command uses `gated_li_invite_one` exclusively. Until then, the manifest is operator-deliberate (the operator runs `send_queued.py` and chooses to emit the manifest vs use the dispatcher).

4. **The `linkedin-weekly-invite-cap` rule activates when the operator uncomments it in their `cooldowns.yml`.** Week 2 makes the rule's cost-event source actually populate; pre-Week-2 the rule was operator-uncommentable but would have reported zero usage (the manifest path emitted `cost_incurred` events manually per `_emit_linkedin_manifest`'s printed instructions, but operators rarely did the manual emit). Post-Week-2 the dispatcher emits the cost event automatically; operators uncommenting the rule see real enforcement.

5. **Pre-existing operators with months of LinkedIn invite history** see retroactive `li_invite_*` events emitted by ledger/0003 unless they run the D41 seed incantation. The retroactive events are tagged `_recovered_by: "backfill"` so an operator inspecting the ledger after `apply()` can distinguish them from forward-emitted dispatcher events.

**The Week 2 commit's verification surface:**

```bash
# 1. ledger/0003 + vault/0003 are pending; total = 7.
$ python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print(len(r.pending()))"
7

# 2. The new coherence-test class has 5-6 running rows (Week 2 un-skips).
$ python -m pytest tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel -v
# Expected: 5-6 passing (was 6 skipped pre-Week-2).

# 3. The full suite is green at +N tests (N is approximately 35-50 new
#    tests; 1144 + N = ~1180-1195 passing).
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q

# 4. ADR-0015 exists; README index gains the row; PILLAR-PLAN §6 Pillar C
#    row updated to reflect Week 2 ship.
$ ls docs/adr/0015-pillar-c-linkedin-invite-dispatcher.md
$ grep "0015" docs/adr/README.md
$ grep "Week 2" docs/PILLAR-PLAN.md

# 5. The cross-channel rule fires correctly against Week 2's
#    li_invite_confirmed events (the coherence test pins this).
$ python -m pytest tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel::test_li_invite_every_event_carries_channel_linkedin -v
```

## References

- ADR-0001 (policy engine architecture) — `RuleContext.channel` field; the engine surface Week 2's dispatcher's policy gate feeds.
- ADR-0003 (channel as first-class policy predicate) — the `CrossChannelTouchRule` Week 2's `li_invite_confirmed` events fire. ADR-0014 D33 pinned the naming; this ADR ships the events.
- ADR-0006 (budget rules + cost_incurred event) — the per-channel cost-emission convention Week 2's dispatcher follows. D40 names the `source="linkedin_invite"` value.
- ADR-0008 (LinkedIn weekly invite cap) — the rule Week 2 activates via cost-event emission. D40 details the activation path.
- ADR-0009 (migration framework) — D2 sequential ID convention; ledger/0003 + vault/0003 follow.
- ADR-0010 (ledger migrations) — D14 append-only invariant (ledger/0003 is `is_reversible=False`); D15 idempotence via deterministic intent_id; D17 `migration_event` audit-trail per migration.
- ADR-0011 (vault migrations) — D8 per-file atomicity; vault/0003 uses `write_person_frontmatter_atomic`.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — D24-N dry-run limitation (Pillar C inherits); D27 `_DEFAULT_APPLY_ORDER = (VAULT, LEDGER, POLICY)` (Week 2's migrations slot in without amendment per D34); D32 per-ADR existing-operator seed pattern (D41 instantiates).
- ADR-0014 (Pillar C foundation) — D33 channel event-type naming convention; D34 cross-category ordering reuse; D35 `channel=` kwarg; D36 per-ADR seed pattern; D37 exit-criterion vehicle.
- `docs/PILLAR-PLAN.md` §2 Pillar C — exit criterion (binding text); §6 Pillar C row updated to reflect Week 2 ship.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D38's default-to-invite for ambiguous filenames (the cost of mis-classifying a DM as invite is recoverable; the cost of refusing to backfill is operator friction).
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — risk this ADR mitigates by design via the dispatcher's correct `channel: linkedin` stamping + the cross-channel rule's automatic firing.
- `docs/SOURCES-OF-TRUTH.md` — per-channel touch notes inherit the existing "Touch notes" row's SoT semantics; per-channel ledger events inherit "Send-history."
- `.planning/HANDOFF-pillar-c-week-1.md` — the prior week's handoff documenting Week 1's deliverables.
- `.planning/HANDOFF-pillar-c-week-2.md` — the handoff that scoped this commit's deliverables.
- `.planning/HANDOFF-pillar-c-week-3.md` — the next week's handoff scoping LinkedIn DM dispatcher.
- `orchestrator/migrations/ledger/migration_0003_baseline_li_invite_history.py` — the migration ledger/0003.
- `orchestrator/migrations/vault/migration_0003_add_linkedin_action_to_touch_notes.py` — the migration vault/0003.
- `orchestrator/ledger.py` — `_OUTCOME_TYPES` + `_INTENT_TYPES` + `_CONFIRMED_TYPES` (Week 2 generalized the indexer to recognize per-channel intent/outcome types); `last_send_for` (Week 2 generalized to accept any per-channel confirmed type).
- `orchestrator/policy/cross_channel.py` — the rule class Week 2's events fire (no code change needed; the rule's forward-references in ADR-0003 already accommodate `li_invite_confirmed`).
- `skills/send-outreach/scripts/send_queued.py` — `gated_li_invite_one` (Week 2's dispatcher); `_li_invite_vault_writeback`; `LI_INVITE_INTENT_MARKER_TEMPLATE`.
- `tests/test_multi_channel_coherence.py::TestLinkedInInviteChannel` — un-skipped Week 2 (was 6 skipped pre-Week-2).
- `tests/test_migrations_ledger_0003.py` — Week 2 ships the direct unit tests.
- `tests/test_migrations_vault_0003.py` — Week 2 ships the direct unit tests.
- `tests/test_send_gate_linkedin.py` — Week 2 ships the dispatcher gate tests.
- `tests/fixtures/synthetic_pillar_b/` — substrate (the Pillar B Week 6 third follow-up pre-shipped the Alice LinkedIn touch + Carol synthetic LinkedIn invite pair).
- Forward-references (planned):
  - **ADR-0016** (Pillar C Week 3): LinkedIn DM dispatcher + `ledger/0004_baseline_li_dm_history` migration. Reads vault/0003's `linkedin_action: dm` field; backfills DM touches.
  - **ADR-0017** (Pillar C Week 4): Reconcile passes D (LinkedIn invites — recovers `li_invite_intent` crashes via the D39 marker) + E (LinkedIn DMs).
  - **ADR-0018** (Pillar C Week 5): Twitter DM dispatcher + reconcile Pass F.
  - **ADR-0019** (Pillar C Week 6): Calendar booking dispatcher + Cal.com webhook + reconcile Pass G.
  - **Pillar I CLI** (Weeks 43–48): aggregation of D41 per-ADR seed blocks into `python -m orchestrator.migrations seed --pillar-c --channel linkedin_invite`.
