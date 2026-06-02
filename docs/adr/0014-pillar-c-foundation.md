# ADR-0014: Pillar C foundation — channel naming, cross-category ordering, `channel=` kwarg, existing-operator seed, exit-criterion vehicle

- **Status:** Accepted
- **Date:** 2026-05-21
- **Pillar:** C (Multi-channel coherence — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001–0008 shipped Pillar A (the declarative policy engine). ADRs 0009–0013 shipped Pillar B (the migration framework + the synthetic-replay exit-criterion vehicle). Pillar C — multi-channel coherence (`docs/PILLAR-PLAN.md` §2 Pillar C, Weeks 7–18) — extends the two-phase commit shape from email to LinkedIn invites, LinkedIn DMs, Twitter DMs, and calendar bookings. The substrate is in place; what Pillar C Week 1 needs is the **convention-setting decisions** the next eleven weeks build on.

Pillar B's Week 5 retrospective (`.planning/RETRO-pillar-b.md` §"What surprised") named the single most important lesson: *"the cross-category dependency was the architectural discovery of the pillar... when shipping multiple per-channel dispatchers, design the cross-channel coherence test in Week 1, not Week N."* Pillar B's per-week-handoff pattern catches per-week defects; cross-week coherence problems land only when the integration test surfaces them — which by Pillar B Week 5 was four weeks late. Pillar C has four channels, each with `intent` + `confirmed` + (mostly) `failed` + `aborted` event types — the dependency-shape space is much larger than Pillar B's three categories. Without a Week 1 structural intervention, the same cross-channel-discovery pattern would land in Week N with four weeks of dispatcher work to retrofit.

The five concerns this ADR resolves:

1. **Channel event-type names must be pinned across all four channels before the first dispatcher lands.** Pillar A's `CrossChannelTouchRule` (ADR-0003 §Decision "Event-type predicate") already filters on `type.endswith("_confirmed")` and a per-event `channel` field, anticipating Pillar C's `li_invite_confirmed` / `li_dm_confirmed` / `tw_dm_confirmed` / `calendar_booking_confirmed` types by name. The rule begins firing the moment Pillar C writes the first matching event. The naming convention is therefore load-bearing — a Week 2 dispatcher that emitted `linkedin_invite_confirmed` instead of `li_invite_confirmed` would silently fail the cross-channel rule. D33 pins the names.

2. **The cross-category ordering contract (per ADR-0013 D27 — VAULT → LEDGER → POLICY) must be confirmed for Pillar C's coming migrations.** Pillar C will add per-channel ledger migrations (one per channel for retroactive backfill — the equivalent of `ledger/0002_backfill_send_history` for each channel) AND per-channel policy migrations (per-channel rate limits per `cooldowns.yml`). The current default apply order works for Pillar C without changes IF future per-channel migrations follow the same pattern (vault is the operator-edited substrate; ledger denormalizes; policy is orthogonal). D34 documents this explicitly and names what would require a future amendment.

3. **`migration_event` audit-trail emissions need a `channel` field for Pillar G observability.** Pillar B's `emit_migration_event` helper (in `orchestrator/migrations/ledger/_ledger_io.py` per ADR-0010 D17) accepts arbitrary `**extra` kwargs. Pillar G's "when did each channel's migration apply?" dashboard query would otherwise require text-matching against `migration_id` slugs (e.g. `migration_id.contains("linkedin")`) — fragile. D35 pins the `channel=<channel_name>` convention as a load-bearing convention for every per-channel ledger migration; the helper's `**extra` mechanism is the existing extension point.

4. **Existing operators (Yang) have months of LinkedIn invite history from the pre-Pillar-C MCP-mediated flow.** When Pillar C ships `ledger/0003_baseline_li_invite_history` (the Pillar C analog of `ledger/0002_backfill_send_history`), existing operators need a one-time seed instruction. ADR-0013 D32 explicitly decided against shipping `scripts/seed_pillar_b_state.py` because Pillar I OSS bring-up provides the CLI; the same rationale carries to Pillar C. D36 names the documentation convention (every per-channel ADR ships a §"Existing-operator seed" subsection following the ADR-0013 §Migration/rollout pattern) so Pillar I's CLI can aggregate from a known template.

5. **The Pillar C exit-criterion verification vehicle must exist in Week 1.** Per PILLAR-PLAN §2 Pillar C: *"synthetic 50-prospect run across all four channels with injected failures at each two-phase boundary on 10 of them; reconcile recovers every intent; no cross-channel double-engagement."* Without the vehicle landing in Week 1, the cross-channel coherence properties — the integrative concerns this pillar gates on — would only surface end-of-pillar, repeating Pillar B Week 5's pattern. D37 names `tests/test_multi_channel_coherence.py` as the vehicle, with per-week un-skipping as channels land and a single binding `TestExitCriterion.test_50_prospect_4_channel_run_with_10_injected_failures` that gates Pillar C's "stable" flip.

A sixth concern surfaced during this ADR's authoring: **the synthetic fixture's backfilled `send_confirmed` events lacked a `channel` field** (`ledger/0002_backfill_send_history` did not denormalize channel from the paired intent onto the confirmed event). The cross-channel rule's safety check (ADR-0003 §Decision "Event-type predicate" — skip events whose `channel` is not in `consider_channels`) silently masked this gap because production `send_queued.py:gated_send_one` correctly stamps channel on both sides of the pair. The coherence test stub (D37 vehicle) is what surfaced the gap; the fix shipped in the same Week 1 commit. This is the structural intervention working as designed — the test that would have landed in Week N landed in Week 1 and caught a real-but-latent coherence bug.

Risks this ADR mitigates by design: **R011 (cross-channel double-engagement)** moves from "Mitigated by design (rules in place; activate when Pillar C ships LinkedIn events)" toward "Mitigated by design AND verified end-to-end by the coherence test vehicle" — the rule shape and the integration test now compose. The Week 1 channel-naming convention forecloses the silent-rule-bypass failure mode where a Week 2+ dispatcher emits the wrong event type and the cross-channel rule never fires.

## Decision

### D33. Channel event-type naming convention

The four channels' event types follow the existing email shape (`send_intent` / `send_confirmed` / `send_failed` / `send_aborted`) with channel-specific prefixes that match the `CrossChannelTouchRule` forward-references in `orchestrator/policy/cross_channel.py::CrossChannelTouchRule` docstring "Event recognition":

| Channel | Intent | Confirmed | Failed | Aborted |
|---|---|---|---|---|
| Email (existing — Phase 5.5) | `send_intent` | `send_confirmed` | `send_failed` | `send_aborted` |
| LinkedIn invite (Pillar C Week 2) | `li_invite_intent` | `li_invite_confirmed` | `li_invite_failed` | `li_invite_aborted` |
| LinkedIn DM (Pillar C Week 3) | `li_dm_intent` | `li_dm_confirmed` | `li_dm_failed` | `li_dm_aborted` |
| Twitter DM (Pillar C Week 5) | `tw_dm_intent` | `tw_dm_confirmed` | `tw_dm_failed` | `tw_dm_aborted` |
| Calendar booking (Pillar C Week 6) | `calendar_booking_intent` | `calendar_booking_confirmed` | `calendar_booking_failed` | *(none)* |

**Channel field on every two-phase event.** Every event of type `*_intent` / `*_confirmed` / `*_failed` / `*_aborted` MUST carry a top-level `channel: <value>` field where value is one of `{email, linkedin, twitter, calendar}`. The cross-channel rule's safety check (ADR-0003) skips events without this field; an event missing the field is silently invisible to the rule. The `tests/test_multi_channel_coherence.py::TestEmailChannel::test_every_send_family_event_carries_a_channel_field` test pins this contract today against email; Pillar C Weeks 2+ extend the assertion as each channel's dispatcher lands.

**Channel value distinct from event-type prefix.** The event-type prefix carries action shape (invite vs DM vs booking); the `channel` field carries the upstream service identity. Both LinkedIn invites (`li_invite_*`) and LinkedIn DMs (`li_dm_*`) carry `channel: linkedin` — they share the upstream rate-limit pool and the cross-channel rule's `consider_channels: [linkedin]` matches both. Twitter DMs carry `channel: twitter`. Calendar bookings carry `channel: calendar`.

**Why `calendar_booking_` has no `_aborted` type.** The abort case for a calendar booking is "user cancelled the booking" — a semantically distinct event from a recoverable mid-flight failure. ADR-0019 (planned, Pillar C Week 6) will introduce a separate `calendar_booking_cancelled` event class that Pillar D's conversation-state tracker consumes for win/loss attribution; Pillar C's reconcile pass for the calendar channel does not need an `_aborted` type because the Cal.com webhook either delivers the confirmed event or it doesn't (no orphan intent state to recover, because the booking link itself is the "intent" — the event lands when the recipient acts).

**Backfill `send_confirmed` carries `channel` (Pillar C Week 1 fix).** `ledger/0002_backfill_send_history` is patched in this Week 1 commit to denormalize `channel` from the paired `send_intent` onto the emitted `send_confirmed`. The gap was pre-existing — production `send_queued.py:gated_send_one` always stamped channel on both sides of the pair, but the backfill did not. The cross-channel rule's safety check silently masked the absence (an event without channel is treated as "not in `consider_channels`" — Allow). The Week 1 coherence test stub surfaced this; `tests/test_migrations_ledger_0002.py::TestUpgradeHappyPath::test_backfilled_send_confirmed_carries_channel_from_paired_intent` pins the contract.

### D34. Cross-category ordering contract for per-channel migrations

Pillar C's per-channel migrations reuse the existing `_DEFAULT_APPLY_ORDER = (VAULT, LEDGER, POLICY)` constant (per ADR-0013 D27) **without modification**. The rationale holds:

* **Vault is the operator-edited substrate.** Per-channel touch notes carry channel-specific identity / state fields (e.g. `li_invite_intent_id:` on a LinkedIn touch note); vault migrations stamp these via the existing `_vault_io.iter_touch_notes` walker + the `add_frontmatter_field_text` / `add_frontmatter_block_text` primitives (Pillar B Week 6 third follow-up). Vault migrations land first because they evolve the substrate ledger migrations subsequently read.
* **Ledger denormalizes / retroactively emits from vault state.** Per-channel ledger backfill migrations (the Pillar C analog of `ledger/0002_backfill_send_history` per channel) walk touch notes (now stamped with channel-specific identity fields) and emit retroactive `<channel>_intent` + `<channel>_confirmed` event pairs. Ledger migrations land second because they read what vault migrations wrote.
* **Policy is orthogonal to vault and ledger.** Per-channel rate-limit rules (e.g. a `budget.window-cap` rule on `source=linkedin_invite` with a weekly cap) are inserted into `cooldowns.yml` via the existing `_policy_io.add_top_level_block_text` + `bump_version_text` primitives. Policy migrations land last because they reference event types the ledger has now demonstrated it can hold.

**Operator-discipline contract: any per-channel migration that BREAKS this order must surface as its own ADR amendment.** A future Pillar D / E / F migration that requires a different ordering (e.g. a ledger migration that adds a new event type that a co-landing policy migration's rule references) MUST land with an ADR explicitly amending D34 — the apply-order constant is not the enforcement vehicle for this; it is operator discipline backed by ADR convention. ADR-0009 Alternative 8 + ADR-0013 D27's rejection of `depends_on:` continues to hold: the cost of a full dependency DAG is over-engineered for a known-small dependency space; the cost of documentation discipline is two paragraphs per amended ADR.

**Forward-compatibility for "channel adoption order" decisions.** Pillar C Weeks 2–6 ship per-channel dispatchers in a deliberate sequence (LinkedIn invite → LinkedIn DM → Twitter DM → calendar). The sequence is NOT load-bearing in the framework's apply-order sense — each per-channel migration's `id:` follows the existing per-category sequential convention (`ledger/0003_*`, `ledger/0004_*`, etc. — D23 pattern) and the runner applies in numeric prefix order within each category. The week ordering reflects estimated operator-visible value (LinkedIn first because LinkedIn-as-channel is already the most-used adjacent channel; calendar last because Cal.com webhook integration has the highest external-system risk).

### D35. `channel=` kwarg convention for `emit_migration_event`

Every Pillar C per-channel ledger migration MUST pass `channel=<channel_name>` as an extra kwarg to `_ledger_io.emit_migration_event`. The migration_event dict on disk will then carry a top-level `channel` field; Pillar G observability filters via `event.get("channel") == "linkedin"` rather than text-matching against the free-form `migration_id` slug.

The existing `**extra` mechanism (per `emit_migration_event`'s docstring — "Any `**extra` kwargs are merged into the event as additional fields") is the documented extension point. No code change to `_ledger_io.py` is required; the convention is documentation-only.

**Example pattern (Pillar C Week 2's `ledger/0003_baseline_li_invite_history` will do):**

```python
emit_migration_event(
    ledger_dir,
    migration_id="0003_baseline_li_invite_history",
    affected_count=n_pairs_emitted + n_orphans_emitted,
    category="ledger",
    channel="linkedin",   # D35 convention
    runner_version=RUNNER_VERSION,
    enrolled_emitted=...,
    pairs_emitted=...,
    orphans_emitted=...,
)
```

**Why `channel` and not `channels` (plural).** Every per-channel migration concerns exactly one channel (a Pillar C migration that touched LinkedIn AND Twitter would be the wrong shape — split into two migrations). A future cross-channel migration (e.g. a Pillar D migration that adds reply-classifier fields to touch notes across all channels) would explicitly pass `channels=["email", "linkedin", "twitter", "calendar"]` or omit the field entirely (cross-channel scope = no channel filter). The singular `channel` carries the "this migration is per-channel" semantic.

**Reserved field collision avoidance.** `_ledger_io.emit_migration_event` already raises `ValueError` when `extra` includes any of `{type, migration_id, affected_count, ts, v}`. `channel` is not in the reserved set; the convention is safe.

### D36. Existing-operator seed pattern for per-channel backfill migrations

Every Pillar C per-channel migration that may apply to operators with pre-existing state MUST include an **"Existing-operator seed"** subsection in its ADR following the ADR-0013 §Migration/rollout pattern. The subsection provides the one-time REPL incantation an operator with pre-existing channel-specific state runs to mark the migration applied without re-applying.

**The template (Pillar C Week 2's ADR-0015 will instantiate for LinkedIn invites):**

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

The shape is mechanical — only the migration id changes per ADR. Pillar I OSS bring-up's CLI (Weeks 43–48) absorbs these per-ADR blocks into a unified seed command (`python -m orchestrator.migrations seed --pillar-c`). Until Pillar I, operators consult each Pillar C ADR's seed block; the consistent template means the operator's workflow is "find the ADR, copy the block, run."

**Why one block per ADR and not a shared `docs/PILLAR-C-OPERATOR-SEED.md`.** Per-ADR placement keeps the seed instruction adjacent to the migration's own context — an operator reading ADR-0015 to understand why the migration exists immediately sees how to skip it if their state already has the effects. A shared document would require operators to cross-reference; ADR-0013 D32's rejection of `scripts/seed_pillar_b_state.py` already established the precedent that per-ADR documentation is the right grain.

**Operators with zero pre-Pillar-C channel-specific state skip the seed entirely.** A new OSS operator who installs outreach-factory after Pillar C lands has no pre-existing LinkedIn invite history; `apply()` runs `ledger/0003_baseline_li_invite_history` and emits zero events (no touch notes to walk). The seed exists only for operators who have been using LinkedIn invites via the pre-Pillar-C MCP-mediated flow.

### D37. Pillar C exit-criterion vehicle scope

`tests/test_multi_channel_coherence.py` is the Pillar C exit-criterion verification vehicle. The file ships in Pillar C Week 1 as a stub:

* **`TestEmailChannel`** — four tests that run today against the synthetic fixture, asserting the channel-coherence invariants every Pillar C channel MUST mirror: two-phase intent+confirmed pairing, orphan recovery to `_aborted`, `channel` field on every two-phase event, end-to-end cross-channel rule firing against backfilled email touches.
* **`TestLinkedInInviteChannel`** (Week 2 un-skip), **`TestLinkedInDMChannel`** (Week 3), **`TestTwitterDMChannel`** (Week 5), **`TestCalendarBookingChannel`** (Week 6) — per-channel test classes whose rows un-skip as the corresponding dispatcher lands. Each class mirrors the email-channel invariants.
* **`TestCrossChannelCoherence`** — twelve rows (CC-01..CC-12) mirroring ADR-0003's matrix from the coherence (not unit-test) angle. `tests/test_policy_cross_channel.py` remains the rule-level SoT (synthetic in-memory events); these rows exercise the rule against ledger events actually written by Pillar C dispatchers. Most stay skipped until the corresponding dispatcher lands; some (CC-08 / CC-09 / CC-11 / CC-12) reference `test_policy_cross_channel.py` as the SoT and stay skipped to avoid duplication.
* **`TestExitCriterion`** — one test, `test_50_prospect_4_channel_run_with_10_injected_failures`, the binding exit-criterion test. Stays skipped until Pillar C Week 12's final reconcile pass lands; passing it is the structural gate on Pillar C's "stable" flip.

**The vehicle's load-bearing property.** The file's existence in Week 1 — with explicit skip messages naming the week that delivers each row — means cross-channel coherence problems surface in the test corpus, not in retrospective archaeology. Every Pillar C week's per-week independent review reads this file as part of the exit-gate check; a week that lands a dispatcher without un-skipping the corresponding rows is incomplete by the per-week review's own discipline. The structural intervention against Pillar B Week 5's late-discovered cross-category-dependency surprise is exactly this: the contract is visible from Week 1.

**Counter-argument: a separate `tests/test_pillar_c_exit_criterion.py` would isolate the binding exit test.** The single-file shape was chosen because the binding test is conceptually "the integration of every other test in the file under stress." Splitting it across files would require the operator-readable mental model "look in two places to understand Pillar C's exit-criterion contract." The single file ships as the vehicle; the discrete `TestExitCriterion` class is the binding-assertion home; the discrete `test_50_prospect_4_channel_run_with_10_injected_failures` method is the binding assertion.

### Downstream pillar impact

Per the ADR-0009 / 0010 / 0011 / 0012 / 0013 convention (every Pillar B ADR explicitly names cross-pillar impact; Pillar C inherits the convention):

* **Pillar D (reply + conversation handling).** Pillar D's reply classifier consumes per-channel reply events. The per-channel `*_confirmed` event types from D33 give Pillar D's reply joiner a known set of event types to correlate replies against — `reply_received` events carry `channel: <value>` matching the source `*_confirmed`. Pillar D's `vault/000N_add_reply_state_fields` migration extends per-channel touch notes (which Pillar C will have introduced via per-channel vault migrations); the cross-category ordering convention (D34) carries.

* **Pillar E (discovery quality + lineage).** Pillar E adds `discovery_lineage:` blocks to Person frontmatter via vault migrations. Per-channel touch notes (from Pillar C) inherit the same `add_frontmatter_block_text` primitive — Pillar E's `vault/000N_add_discovery_lineage` migration walks Person notes (not touch notes), so there is no overlap with Pillar C's per-channel migrations. The cross-channel rule (ADR-0003) does NOT consume discovery_lineage fields.

* **Pillar F (voice corpus + draft quality).** Voice-fidelity scoring is per-touch (not per-channel); Pillar F migrations operate on touch notes regardless of channel. The per-channel touch-note shapes Pillar C introduces (e.g. `li_invite_*` touches in `40 Conversations/`) become inputs to Pillar F's scoring — the `voice_fidelity_score:` field Pillar F stamps applies across all channels uniformly.

* **Pillar G (observability).** Pillar G's "per-channel migration audit-trail" dashboard queries `migration_event` events filtered by the D35 `channel` field. Without D35, the dashboard would text-match against `migration_id` slugs — fragile. D35 makes this a one-line filter (`event.channel == "linkedin"`). Pillar G's "per-channel send-funnel" dashboard reads the `channel:` field on `<channel>_confirmed` events (the D33 invariant); without D33's channel-on-every-event contract, the funnel would have to text-match event types — fragile in the same way.

* **Pillar H (daemon + dispatcher).** Pillar H's per-stage parallelism limits become per-channel (e.g. "no more than N concurrent LinkedIn invite sends"); the D33 `channel` field is the dispatch-router's discriminator. Pillar H inherits Pillar C's per-channel dispatcher shape unchanged.

* **Pillar I (multi-tenant + OSS hardening).** Per-tenant per-channel state isolation. The D36 existing-operator-seed pattern (per-ADR seed blocks) gets aggregated into the Pillar I CLI as `python -m orchestrator.migrations seed --pillar-c` (or finer-grain `seed --channel linkedin_invite`). The D34 cross-category-ordering contract continues to hold per-tenant — each tenant's runner walks the same `_DEFAULT_APPLY_ORDER`.

* **Pillar J (security + compliance).** GDPR-forget on a Person who has touches across multiple channels: every per-channel touch note for that Person is deleted, and per-channel ledger events for that Person are tombstoned (per the ADR-0010 §Downstream pillar impact for Pillar J pattern). The D33 channel-field invariant means Pillar J's forget tooling can query "every event with `person_id: X`" without channel-specific code paths — the same query covers all four channels.

## Alternatives considered

### D33-Alt1: Uniform prefix scheme — `channel_email_*`, `channel_linkedin_invite_*`

A more uniform prefix (every event type starts with `channel_`) would be more parseable in regex tools. **Rejected** because:

* The naming would diverge from the existing email `send_*` shape, which Phase 5.5 shipped and operators have been reading in their ledgers for months. Renaming `send_intent` → `channel_email_intent` would require a vault + ledger migration, churning ~70 tests' literal-string assertions across the test suite, and orphaning every existing tool that text-matches against `send_intent`.
* The Pillar A `CrossChannelTouchRule` (ADR-0003) already forward-references `li_invite_confirmed` + `li_dm_confirmed` by name (`orchestrator/policy/cross_channel.py::CrossChannelTouchRule` docstring "Event recognition"). A different naming would invalidate those forward-references and re-open ADR-0003.
* The `type.endswith("_confirmed")` predicate in the cross-channel rule works equally well for both naming schemes; uniformity gains no engine-side benefit.

### D33-Alt2: Drop the `_aborted` event type for channels that have explicit `_failed`

The `_aborted` events specifically represent reconcile-mediated recoveries (per the email shape: `send_aborted` is what `ledger/0001_close_orphan_send_intents` emits for an intent with no outcome). A simpler scheme would consolidate `_failed` and `_aborted`. **Rejected** because:

* The asymmetric-failure-cost semantics differ. `send_failed` means "we know the send didn't reach the human, the API told us so"; `send_aborted` means "we don't know if the send reached the human; we close by fiat because the asymmetric-cost principle says we'd rather false-positive on 'sent' than block a re-attempt forever." The cross-channel rule's safety check depends on this distinction (only `_confirmed` blocks; both `_failed` and `_aborted` do not).
* Pillar C's per-channel reconcile passes (Weeks 4+ per the per-week trajectory) will emit `<channel>_aborted` for orphan recovery; consolidating with `_failed` would force the reconcile pass to write `_failed` events for the "we don't know" case, which is operationally confusing.

### D33-Alt3: Calendar booking should have an `_aborted` type for symmetry

Adopt `calendar_booking_aborted` even though the underlying webhook model doesn't surface orphan-intent states. **Rejected** because:

* The intent for a calendar booking is the operator sending the booking link in a touch; the confirmed event is the recipient clicking and booking a slot. There is no orphan state between intent and confirmed — the link either gets clicked or it doesn't. Adopting `calendar_booking_aborted` would either be dead code (never emitted) or would require synthesizing an aborted event by some arbitrary "we waited N days and the recipient never booked" timeout policy, which is an arbitrary choice that doesn't reflect a real recoverable state.
* Calendar bookings have their own distinct event class for "user cancelled the booking" (`calendar_booking_cancelled` per ADR-0019 planned) which Pillar D's conversation-state tracker consumes. Adding `_aborted` would muddy that distinction.

### D34-Alt1: Add per-migration `depends_on:` field to the Migration Protocol

Each Pillar C per-channel migration declares its dependencies; the runner builds a DAG. **Rejected** as over-engineered. ADR-0009 Alternative 8 + ADR-0013 D27 Rejected-alternatives 2 already considered this for Pillar B; the same rationale carries to Pillar C: the dependency space is small (VAULT → LEDGER → POLICY covers every known cross-category dep), the documentation cost is two paragraphs per amended ADR, and the DAG cost is a non-trivial framework primitive that would defer the Week 2 dispatcher landing. If Pillar D or later introduces a complex DAG-shaped dependency, a future ADR adds `depends_on:` cleanly.

### D34-Alt2: Reorder `_DEFAULT_APPLY_ORDER` to (LEDGER, VAULT, POLICY) for Pillar C

Pillar C's per-channel ledger migrations write event types that operator vault migrations might subsequently consume. **Rejected** because:

* The hypothetical Pillar C vault migration consuming Pillar C ledger event types doesn't exist and isn't on the per-week trajectory. Pillar C vault migrations stamp touch-note frontmatter fields (`li_invite_intent_id:`, etc.) — these are forward-emitted by the dispatcher per-touch, not retroactively backfilled from ledger state.
* The current order (VAULT → LEDGER → POLICY) was set by ADR-0013 D27 specifically because ledger/0002 reads `id:` stamped by vault/0002. Reverting would re-introduce the Pillar B Week 5 degeneracy.
* The asymmetry "vault is operator-edited substrate; ledger denormalizes" continues to hold for Pillar C — per-channel touch notes are operator-deliberate; per-channel ledger backfill events are reconstructed from them.

### D34-Alt3: Make Pillar C's per-channel cross-category dependency explicit by introducing a `MigrationCategoryGroup` or similar enum

A new "channel" axis added orthogonally to the existing (VAULT, LEDGER, POLICY) category axis, with apply order considering both. **Rejected** because:

* Channels are not a migration-category-level concept. A vault migration is a vault migration regardless of which channel its frontmatter fields concern; a policy migration is a policy migration regardless of which channel its rules scope. Adding a channel axis to the framework would mix two orthogonal concepts (what kind of artifact does the migration mutate? vs which channel does its semantic concern?).
* The D35 `channel=` kwarg on `migration_event` is the right place for the channel discriminator — it's an event-level annotation for Pillar G to query, not a framework-level category.

### D35-Alt1: Add a typed `MigrationEventChannel` enum field to the migration_event shape

A formal `migration_event` schema field (not a free-form `**extra`) for type-safety. **Rejected** as premature. The `**extra` mechanism is the documented extension point; adding a typed field would require a `migration_event` schema bump, which would require a schema migration on the ledger files, which would churn every existing operator's ledger reader. The convention covers the foreseeable Pillar G use case; a future Pillar G ADR can amend if observability work surfaces a need for stronger typing.

### D35-Alt2: Use `tags=["channel:linkedin"]` as a list of free-form tags instead of a singular `channel` field

A tag list is more flexible (a multi-channel migration could pass `tags=["channel:linkedin", "channel:twitter"]`). **Rejected** because:

* Every Pillar C migration is per-channel by design (D34 ordering contract assumes this). A multi-channel migration would be the wrong shape.
* List-shaped queries are harder to write than scalar-shaped queries. `event.get("channel") == "linkedin"` is one line; `"channel:linkedin" in event.get("tags", [])` is one line but parses through a string-prefix scheme. The scalar field wins on cleanliness.

### D35-Alt3: Add a `channel` parameter to `emit_migration_event`'s signature instead of using `**extra`

A keyword-only parameter `channel: str | None = None` on the function signature would be more discoverable. **Rejected** because:

* It would change the function signature, requiring every existing call site to be reviewed — and the Pillar B migrations that DON'T have a channel (vault/0001, vault/0002, ledger/0001, ledger/0002, policy/0001) shouldn't need to pass `channel=None` explicitly.
* The `**extra` mechanism's existing docstring already names the extension pattern. Adding a discoverable kwarg without standardizing the field convention would land in two places (signature + ADR); centralizing in the ADR per the convention is the lower-churn choice.

### D36-Alt1: Ship `scripts/seed_pillar_c_state.py` in Pillar C Week 1

A standalone seed CLI that aggregates every Pillar C migration's seed instructions. **Rejected** per the ADR-0013 D32 precedent — Pillar I OSS bring-up's CLI is the canonical home for cross-pillar seed tooling; shipping one-pillar-at-a-time seed scripts would create per-pillar tools that Pillar I would then have to consolidate (or that would diverge). The per-ADR documentation pattern means Pillar I aggregates from a known template; no inter-pillar tool divergence.

### D36-Alt2: Make per-channel migrations always idempotent and skip the seed entirely

Per-channel ledger migrations could implement an idempotence check that finds existing channel-specific events (e.g. existing `li_invite_confirmed` events in the operator's ledger from the pre-Pillar-C MCP flow) and skips emission for those — no seed needed. **Rejected** because:

* The pre-Pillar-C MCP-mediated LinkedIn invite path does NOT write ledger events at all (the MCP call's success is captured as touch-note `sent: true` only). The migration's idempotence check would have nothing to match against.
* Treating "missing events" as "needs backfill" would re-emit retroactive events for every operator on every apply, churning their ledger on every git-pull. The seed instruction is the discrete signal "this operator already has the effects; skip the migration."

### D36-Alt3: Auto-detect pre-Pillar-C state and skip without an explicit seed

The migration walks the operator's vault for touch notes with `sent: true` AND `channel: linkedin` AND a `last_touch:` date older than the migration's release date; if it finds any, refuses to apply automatically and prints the seed instruction. **Rejected** because:

* Refusing to apply automatically would block the new-operator case (operators with zero pre-existing state want the migration to apply without intervention). Distinguishing "this is a new operator" from "this is an existing operator who hasn't seeded" requires the operator-supplied signal — which is exactly what the seed instruction provides.
* Heuristic detection ("last_touch older than release date") is fragile — a new operator who imports historical data from a CSV would trip the heuristic.

### D37-Alt1: A separate `tests/test_pillar_c_exit_criterion.py` for the binding test

Isolate the binding `test_50_prospect_4_channel_run_with_10_injected_failures` in its own file. **Partially accepted, but the discrete-class shape captures the same isolation benefit without the file split.** Keeping `TestExitCriterion` as a discrete class in the same file means:

* The vehicle's load-bearing property (cross-channel coherence is visible from Week 1) lives in ONE place that per-week reviewers consult; splitting across files would create the "look in two places" mental model the §Decision D37 rationale rejects.
* The class boundary preserves the isolation — `pytest tests/test_multi_channel_coherence.py::TestExitCriterion` runs only the binding test if a reviewer wants to focus on it.

### D37-Alt2: Build the test vehicle bottom-up (build per-channel tests as each channel's dispatcher lands)

The vehicle exists implicitly in the per-channel test files Pillar C Weeks 2+ ship; a top-level coherence vehicle is not needed. **Rejected** explicitly by the Pillar B retrospective (`.planning/RETRO-pillar-b.md` §"What to do differently in Pillar C", item 1) — the retrospective NAMED the absence of a Week-1 coherence test as the single most important carry-over lesson from Pillar B Week 5's cross-category-dependency surprise. The bottom-up shape is exactly what was rejected by the retro's analysis.

### D37-Alt3: The exit-criterion test runs against a real-operator-scale fixture (1000 prospects)

The 50-prospect / 10-failure shape is too small to surface scale-related coherence bugs. **Rejected for Week 1 scope; deferred to Pillar I OSS bring-up's stress-test work.** The 50-prospect / 10-failure shape mirrors PILLAR-PLAN §2 Pillar C's exit-criterion text verbatim — "synthetic 50-prospect run across all four channels with injected failures at each two-phase boundary on 10 of them." Scaling beyond would diverge from the binding text; PILLAR-PLAN §2 would have to be re-opened. Pillar I's stress test layers volume on top of this baseline per the existing programmatic-builder pattern (ADR-0013 D24).

## Consequences

### Positive

- **Cross-channel coherence problems surface in Week 1, not Week N.** The `tests/test_multi_channel_coherence.py` vehicle (D37) sets the contract; Pillar B Week 5's late-discovered cross-category-dependency failure mode is structurally prevented.
- **The Week 1 stub already caught a real coherence regression.** The `ledger/0002` `send_confirmed`-missing-channel gap (D33's "Backfill `send_confirmed` carries `channel`" clause) was pre-existing and silently masked by the cross-channel rule's safety check; the coherence test stub surfaced it within the first run. The structural intervention is working as designed.
- **The channel naming convention is forecloses a class of silent dispatcher bugs.** A Week 2+ dispatcher that emitted the wrong event-type prefix would fail the per-week test rows (`TestLinkedInInviteChannel::test_li_invite_two_phase_intent_confirmed` etc.) and be caught at write time, not at integration time.
- **Pillar G's per-channel observability work has a clear data shape.** D33 guarantees every two-phase event carries a `channel` field; D35 guarantees every `migration_event` carries `channel` for per-channel migrations. Pillar G writes scalar filters, not text-matchers.
- **The cross-category ordering contract (D34) is documented + carries forward without code change.** Pillar C Weeks 2+ slot into the existing apply order; future per-pillar migrations either compose (no ADR amendment) or break the order (explicit ADR amendment per D34).
- **Existing-operator seed pattern (D36) is the canonical template.** Pillar I CLI aggregates per-ADR seed blocks mechanically; the inter-pillar consolidation cost is paid once at Pillar I rather than per-pillar.
- **The Pillar C exit-criterion test vehicle is real from Week 1.** The binding test stays skipped until Week 12, but every intermediate per-week independent review consults it as the gate-check. Cross-channel coherence is a tested contract, not a hoped-for property.

### Negative

- **Five test classes are skipped today, deferring most coherence assertions to per-channel weeks.** A casual reader of `test_multi_channel_coherence.py` sees ~30 skipped tests and could mistake the file for a placeholder. **Mitigation:** every skip message explicitly names the week that delivers and references the relevant ADR (planned or shipped); the per-week independent reviewer reads this as the work tracker. The file's value compounds — by Week 6 the file's running-test count grows substantially.
- **The D33 channel-naming convention pins names that the dispatchers haven't yet implemented.** A Week 2+ author who disagrees with `li_invite_intent` (perhaps preferring `linkedin_invite_intent`) would have to either follow the convention or open an amendment. **Mitigation:** the naming is already forward-referenced by `cross_channel.py` lines 54–56 (ADR-0003 §Decision "Event-type predicate"); the convention is grandfathered from Pillar A's shipped code, not invented here.
- **The D34 cross-category-ordering contract is documentation-discipline, not code-enforcement.** A future migration that needs a different ordering can silently break the convention if the author skips the ADR amendment. **Mitigation:** every per-week independent reviewer reads the per-week's commit against the existing ADRs; an unamended apply-order divergence is loud at review time. The cost of one missed amendment is recoverable in the follow-up commit (no production state corruption — the ordering decision is at the framework level, not the migration level).
- **The D36 per-ADR seed-block convention requires every Pillar C ADR author to remember to include the subsection.** A Week 2+ ADR that omits the seed block leaves existing operators without a self-service skip path. **Mitigation:** the per-week independent review's exit checklist (per HANDOFF-pillar-c-week-1.md §"Validation gate") includes "ADR-NNNN contains the §Existing-operator seed subsection" as a per-week gate.
- **The D37 vehicle's `TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures` test stays skipped for Weeks 2–11, deferring the binding integrative assertion.** **Mitigation:** the skip message explicitly names the Week 12 un-skip; per-week reviewers know to expect the skip throughout the body of Pillar C.

### Neutral / observability

- The `migration_event` events from Pillar C's per-channel migrations will carry `channel: <value>` per D35; Pillar G observability dashboards filter by this field without changes to the existing `migration_event` shape (the `**extra` mechanism is the seam).
- Every Pillar C migration's `id:` follows the existing per-category sequential convention; the runner pinning + the registry pattern (ADR-0009 D2 + D6) carry to Pillar C unchanged. New Pillar C migration IDs land as `ledger/0003_*`, `ledger/0004_*`, `vault/0003_*`, etc.
- The Pillar C ADR series begins at ADR-0014 (this ADR); planned ADRs: ADR-0015 (LinkedIn invite — Week 2), ADR-0016 (LinkedIn DM — Week 3), ADR-0017 (reconcile passes D + E — Week 4; Pass D = LinkedIn invites per PILLAR-PLAN §2 Pillar C + ADR-0003 §Decision "Pillar C's scope shrinks accordingly", Pass E = LinkedIn DMs), ADR-0018 (Twitter DM + reconcile Pass F — Week 5), ADR-0019 (calendar booking + reconcile Pass G — Week 6).

## Compliance with invariants

- **I1 (single source of truth):** No new SoT introduced. Per-channel touch notes are operator-edited (vault is SoT for touch shape); per-channel ledger events denormalize per the same I1 row "Send-history" that covers email today. The D34 cross-category-ordering contract preserves the I1 invariant by establishing which SoT a downstream consumer reads from (vault → ledger).
- **I2 (two-phase commit on every external side effect):** D33 names the per-channel event-type shapes that operationalize I2 for every Pillar C channel. The `<channel>_intent` → external API call → `<channel>_confirmed | _failed | _aborted` shape is uniform across all four channels. The Week 1 fix to `ledger/0002` (denormalizing channel onto backfilled `send_confirmed`) closes a latent gap in I2's enforcement — without it, the cross-channel rule (which enforces "no double-engagement", an I2-adjacent invariant) silently failed against backfilled events.
- **I3 (schema versioning):** Pillar C per-channel migrations follow the existing `v: 1` shape on ledger events; per-channel vault migrations follow the existing `schema_version:` shape on touch notes; per-channel policy migrations follow the existing `version:` shape on YAML files. No I3 change required.
- **I4 (reproducible state):** Pillar C does not change the reproducibility surface. Per-channel `<channel>_intent` + `<channel>_confirmed` events are durable in the append-only ledger; per-channel touch notes are durable in the vault; both are recoverable via the existing `rebuild_vault.py` + ledger-backup paths. The D34 cross-category-ordering contract preserves reproducibility — the same `_DEFAULT_APPLY_ORDER` produces byte-identical after-states from a known before-state. No I4 change required.
- **I5 (observable by default):** D35's `channel=` kwarg on `migration_event` ensures every per-channel migration emits an observable channel-tagged audit-trail event. D33's channel-on-every-event invariant ensures Pillar G can chart per-channel funnels via scalar field filters. Cross-channel `policy_blocked` events (Pillar A ADR-0003) inherit the per-event channel field; per-channel breakdown of `policy_blocked` is one query.
- **I6 (tests prove invariants):** D37's `tests/test_multi_channel_coherence.py` is the integrative test vehicle; `tests/test_migrations_ledger_0002.py::TestUpgradeHappyPath::test_backfilled_send_confirmed_carries_channel_from_paired_intent` is the regression pin for the D33 channel-on-backfill clause. Per-week additions extend both files.
- **I7 (cost is a first-class concern):** Per-channel cost events (`cost_incurred` with `source=<channel>`) follow the existing ADR-0006 shape; Pillar C per-channel dispatchers emit cost events at the API-success path per the email pattern (`send_queued.py:gated_send_one` lines 480–501). No I7 change required.
- **I8 (decisions documented):** This ADR. `docs/adr/README.md` gains an ADR-0014 row. The per-week trajectory in HANDOFF-pillar-c-week-1.md §"Per-week trajectory" names planned ADRs 0015–0019.

Does not weaken any invariant. I2's enforcement is strengthened (the D33 channel-on-every-event invariant + the Week 1 `ledger/0002` fix close a latent cross-channel-rule gap).

## Migration / rollout

The Week 1 deliverable is convention-setting + the test vehicle stub + the latent `ledger/0002` channel-field fix. No new framework primitive ships; no new migration ships; no new dispatcher ships.

**Operator-facing changes (Week 1):**

1. **No new pending migrations.** `runner.pending()` still returns 5 (the Pillar B set: vault/0001, vault/0002, ledger/0001, ledger/0002, policy/0001). Pillar C Week 2 will be the first commit that adds a pending migration (`ledger/0003_baseline_li_invite_history` planned).

2. **An operator who has already applied Pillar B migrations sees no change.** The `ledger/0002` channel-field fix only affects the BACKFILLED `send_confirmed` events on re-application, but per the migration's idempotence check (`existing_intents` set in `migration_0002.py:531–534`), re-application is a no-op for already-emitted backfill events. The fix lands for any future operator who applies Pillar B migrations after this commit; existing operators (Yang) keep their pre-fix `send_confirmed` events without channel.

3. **Existing operators with already-applied `ledger/0002` carry a small known limitation:** their backfilled `send_confirmed` events lack the `channel` field. The cross-channel rule (ADR-0003) returns Allow() for these events when evaluating future cross-channel sends — meaning a future LinkedIn send to a person with a historically-backfilled email touch would not be blocked by the rule. **Recommended remediation:** existing operators run a one-time backfill-replay against a hypothetical `cooldowns.example.yml` rule set in dry-run mode to identify the affected events; if any cross-channel blocks would be expected and missing, the operator can manually emit a remediation `policy_blocked` event with `rule: cross-channel-email-suppresses-linkedin` and `_recovered_by: "manual-remediation"`. For Yang specifically (the current sole operator), the affected window is the small pre-Pillar-C historical period; the practical risk is low because Yang did not previously cross-channel email + LinkedIn the same person within the 14d window.

**Operator-facing changes (Pillar C Weeks 2+, planned):**

4. **Each per-channel week ships a coordinated dispatcher + ledger migration + ADR.** The week's handoff document (per the Pillar B pattern) walks the operator through dry-run + apply + verification. Per the D36 convention, each per-channel ADR ships its own §Existing-operator seed subsection for operators with pre-existing channel-specific state.

5. **The exit-criterion test (`TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures`) un-skips at Week 12.** The test is the operator-visible signal that Pillar C is "stable" — when it passes, the per-week trajectory has completed.

**The Week 1 commit's verification surface:**

```python
# 1. The coherence test vehicle exists and runs the email baseline.
$ python -m pytest tests/test_multi_channel_coherence.py -v
# Expected: 4 passed (TestEmailChannel), ~28 skipped (other channels).

# 2. The ledger/0002 channel-field fix has a regression pin.
$ python -m pytest tests/test_migrations_ledger_0002.py::TestUpgradeHappyPath::test_backfilled_send_confirmed_carries_channel_from_paired_intent -v
# Expected: 1 passed.

# 3. The full suite is green at +8 tests (1144 passing, up from 1136 —
#    4 email-baseline coherence + 1 ledger/0002 regression in the Week 1
#    commit; 3 Pillar-C-readiness foundation-primitive smoke tests in
#    the Week 1 follow-up commit).
$ python -m pytest tests/ --ignore=tests/test_verify_email.py -q
# Expected: 1144 passed, 32 skipped.

# 4. ADR-0014 exists; README index gains the row; PILLAR-PLAN §6 Pillar C
#    row flipped to "In progress."
$ ls docs/adr/0014-pillar-c-foundation.md
$ grep "0014" docs/adr/README.md
$ grep -A1 "C — Multi-channel coherence" docs/PILLAR-PLAN.md
```

## References

- ADR-0001 (policy engine architecture) — `RuleContext.channel` field; the engine surface Pillar C's per-channel events feed.
- ADR-0003 (channel as first-class policy predicate) — the `CrossChannelTouchRule` Pillar C activates by writing `<channel>_confirmed` events; D33's naming convention is bound by ADR-0003's forward-references in `cross_channel.py::CrossChannelTouchRule` (the docstring + the `evaluate` method's event-type predicate).
- ADR-0006 (budget rules + cost_incurred event) — the per-channel cost-emission convention Pillar C dispatchers follow; D33's `channel` field on `cost_incurred` events matches.
- ADR-0008 (LinkedIn weekly invite cap) — the precedent for "rule lands in Pillar A; event-source lands in Pillar C."
- ADR-0009 (migration framework) — D2 sequential ID convention; D6 explicit registry; the framework Pillar C migrations register into.
- ADR-0010 (ledger migrations) — D17 `migration_event` audit-trail contract that D35 extends with the `channel=` kwarg convention.
- ADR-0011 (vault migrations) — the per-file atomicity + surgical-edit primitives Pillar C touch-note migrations consume; `iter_touch_notes` + `add_frontmatter_block_text` shipped Pillar B Week 6 third follow-up specifically for Pillar C consumption.
- ADR-0012 (policy migrations) — D22 engine-version-range-acceptance contract; Pillar C per-channel rate-limit policy migrations bump policy version per the established pattern.
- ADR-0013 (synthetic-replay exit-criterion vehicle) — D27 `_DEFAULT_APPLY_ORDER = (VAULT, LEDGER, POLICY)` that D34 reuses; D32 per-ADR seed pattern that D36 inherits.
- `docs/PILLAR-PLAN.md` §2 Pillar C — exit criterion (binding text); §6 Pillar C row flipped to In progress in this commit.
- `docs/PILLAR-PLAN.md` §0 — asymmetric failure cost; the principle that justifies D33's exclusion of `_intent` events from the cross-channel rule's match set.
- `docs/RISK-REGISTER.md` R011 (cross-channel double-engagement) — risk this ADR mitigates by design via the D37 verification vehicle.
- `docs/SOURCES-OF-TRUTH.md` — per-channel touch notes inherit the existing "Touch notes" row's SoT semantics; per-channel ledger events inherit "Send-history."
- `.planning/RETRO-pillar-b.md` §"What to do differently in Pillar C", item 1 — the explicit retrospective recommendation that mandated D37's Week 1 vehicle landing.
- `.planning/REVIEW-pillar-b-pillar-c-readiness.md` §3 + §4 — the readiness review's per-ADR forward-reference audit + the Week 1 deliverables list that this ADR fulfills.
- `.planning/HANDOFF-pillar-c-week-1.md` — the per-week handoff that scoped Week 1.
- `orchestrator/policy/cross_channel.py` — the rule class Pillar C wires events into; D33's naming is bound here at lines 54–56.
- `orchestrator/migrations/ledger/_ledger_io.py::emit_migration_event` — the `**extra` extension point D35 documents.
- `orchestrator/migrations/ledger/migration_0002.py:535–565` — the Week 1 `send_confirmed` channel-denormalization fix.
- `tests/test_multi_channel_coherence.py` — the D37 exit-criterion verification vehicle.
- `tests/test_migrations_ledger_0002.py::TestUpgradeHappyPath::test_backfilled_send_confirmed_carries_channel_from_paired_intent` — the D33 channel-on-backfilled-confirmed regression pin.
- `tests/fixtures/synthetic_pillar_b/` — the static fixture Pillar C Week 1 builds on; Pillar B Week 6 third follow-up extended it with LinkedIn substrate (`synthetic_pillar_b/README.md` §"Pillar C foundation extensions").
- `tests/conftest.py::synthetic_state_dir` — the programmatic builder fixture.
- Forward-references (planned):
  - **ADR-0015** (Pillar C Week 2): LinkedIn invite dispatcher + `ledger/0003_baseline_li_invite_history` migration.
  - **ADR-0016** (Pillar C Week 3): LinkedIn DM dispatcher + `ledger/0004_baseline_li_dm_history` migration.
  - **ADR-0017** (Pillar C Week 4): Reconcile passes D (LinkedIn invites — per PILLAR-PLAN §2 Pillar C and ADR-0003 §Decision "Pillar C's scope shrinks accordingly") + E (LinkedIn DMs).
  - **ADR-0018** (Pillar C Week 5): Twitter DM dispatcher + `ledger/0005_baseline_tw_dm_history` migration; live tests gated by `OUTREACH_FACTORY_LIVE_TESTS=1` per PILLAR-PLAN §3 I6.
  - **ADR-0019** (Pillar C Week 6): Calendar booking dispatcher + Cal.com webhook + `ledger/0006_baseline_calendar_history` migration.
  - **Pillar I CLI** (Weeks 43–48): aggregation of D36 per-ADR seed blocks into `python -m orchestrator.migrations seed --pillar-c` (or finer-grain `seed --channel <name>`).
