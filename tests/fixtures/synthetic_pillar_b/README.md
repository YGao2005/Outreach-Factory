# Synthetic Pillar B before-state fixture

Static fixture for the Pillar B Week 5–6 synthetic-replay exit-criterion
vehicle (ADR-0013). Represents a fresh, pre-migration outreach-factory
install: a vault with un-stamped Person notes, a ledger with one orphan
`send_intent`, and a policy file at `version: 1` with no `engine_compat`
block.

After all five migrations apply against a copy of this fixture, the
state should be equivalent to a Phase 5.5–shape install:

* `vault/0001_add_schema_version_to_person_notes` → every Person note
  declares `schema_version: 1`.
* `vault/0002_backfill_identity_lineage` → every Person note declares
  `id:` + `identity_keys:` + `identity_version: 1`.
* `ledger/0001_close_orphan_send_intents` → the orphan `send_intent`
  in `events-2026-04-15.jsonl` is superseded by a synthetic
  `send_aborted` with `_recovered_by: migration_0001_*`.
* `ledger/0002_backfill_send_history` → retroactive `enrolled` events
  per Person, `send_intent`+`send_confirmed` pairs per touch note with
  `sent: true`, and a `send_confirmed_orphan` for any Person whose
  `last_touch:` lacks a matching touch note.
* `policy/0001_add_engine_compat_field` → every policy file gains
  `engine_compat: {min_engine_version: ...}` and bumps `version: 1 → 2`.

Why static (not purely programmatic): a reviewer can `cat` each file in
this fixture and see exactly what the migration sees. Schema evolution
of the fixture is intentional: changing the Person-note shape requires
editing these files alongside the migration that bumps the shape, which
keeps the regression baseline aligned with what operators in the wild
will have.

The programmatic builder in `tests/conftest.py` (`synthetic_state_dir`)
copies this fixture to a tmp path so tests can mutate it freely.

## Pillar C foundation extensions (Pillar B Week 6 second follow-up)

Per the Pillar C readiness review
(`.planning/REVIEW-pillar-b-pillar-c-readiness.md` §P2-2 — recommended
extending the fixture to honor the retro's "design the cross-channel
coherence test in Week 1, not Week N" lesson), the fixture has been
extended with a minimal LinkedIn substrate so Pillar C Week 1's
multi-channel coherence test stub has something to assert against
on day one:

* **`vault/40 Conversations/2026-04-18 Alice linkedin invite.md`** —
  a second touch note for Alice modeling a realistic email →
  LinkedIn cross-channel sequence (her email touch on 2026-04-10,
  her LinkedIn invite on 2026-04-18). `sent: true`, so
  `ledger/0002` backfills a second send-pair from it (channel:
  linkedin). Carol's `last_touch:`-without-matching-touch orphan
  invariant is preserved because the new touch is Alice's, not
  Carol's.

* **`ledger/events-2026-04-15.jsonl` LinkedIn events** — one
  `li_invite_intent` + one `li_invite_confirmed` pair for Carol.
  These are forward-looking event types Pillar C will introduce;
  Pillar B's five migrations are channel-agnostic and don't consume
  them (`ledger/0001` closes only `send_intent` orphans; ledger/0002
  walks Person + touch notes, not arbitrary event types). They sit
  in the ledger as substrate Pillar C's coherence test will read
  against.

The factory-shape policy file is unchanged — Pillar C's per-channel
rate-limit rules ship as separate Pillar C policy migrations, not as
fixture additions here. The Pillar A `CrossChannelTouchRule` factory
rules in `config-template/cooldowns.example.yml` already anticipate
the LinkedIn event types via `type.endswith("_confirmed")` predicates.

## Pillar C Week 3 extension (LinkedIn DM substrate)

Per the Pillar C Week 3 handoff (`.planning/HANDOFF-pillar-c-week-3.md`
§"Phase 2 deliverable 11" — fixture extension for the DM dispatcher +
ledger/0004 backfill coherence assertions), the fixture has been extended
with a LinkedIn-DM substrate so Week 3's `TestLinkedInDMChannel` rows
have something to assert against:

* **`vault/10 People/Dana Davis.md`** — a fourth Person modeling a
  LinkedIn-only existing connection (`linkedin_connected: true` per
  ADR-0016 D45's lazy-stamping convention; no `email:` field). Dana's
  `last_touch:` is the day her DM was sent (2026-04-20) — like Alice
  but for the DM channel.

* **`vault/40 Conversations/2026-04-20 Dana linkedin dm.md`** — Dana's
  DM touch note. Carries the explicit `linkedin_action: dm` field per
  ADR-0015 D38 (Week 2's vault/0003 convention) + a filename that
  matches the DM heuristic. `sent: true`, so:
  * `ledger/0002_backfill_send_history` walks it + emits a generic
    `send_intent`+`send_confirmed` pair with `channel: linkedin`
    (channel-agnostic walker).
  * `ledger/0003_baseline_li_invite_history` (Week 2) SKIPS it because
    it's DM-classified — `touches_skipped_not_invite` tracks the
    skip in the migration_event diagnostic.
  * `ledger/0004_baseline_li_dm_history` (Week 3) walks it + emits a
    retroactive `li_dm_intent`+`li_dm_confirmed` pair with a
    deterministic `bf_lidm_<hash>` intent_id.

Aggregate count impact on the existing migrations:

* `vault/0002`: 3 → 4 enrolled (Alice / Bob / Carol / Dana). Dana's id
  ends in `-li` per the mint_id contract (linkedin-only Person).
* `ledger/0002`: `enrolled_emitted` 3 → 4; `sends_emitted` 2 → 3
  (Alice email + Alice linkedin invite + Dana linkedin dm);
  `orphans_emitted` 1 unchanged (Carol's last-touch-without-touch is
  not affected; Dana's last_touch HAS a matching touch). Total
  `affected_count` 6 → 8.
* `ledger/0003`: `linkedin_pairs_emitted` 1 unchanged (still Alice
  only); `touches_skipped_not_invite` 0 → 1 (Dana's DM).
* `ledger/0004` (Week 3): `linkedin_dm_pairs_emitted` 1 (Dana's DM).

## Pillar C Week 4 extension (reconcile Pass D + Pass E substrate)

Per the Pillar C Week 4 handoff (`.planning/HANDOFF-pillar-c-week-4.md`
§"Phase 2 deliverable 8" — fixture extension for the reconcile Pass D
+ Pass E coherence assertions), the fixture has been extended with
two LinkedIn orphan intents (one per per-channel pass) so Week 4's
`test_li_invite_aborted_for_orphan_intent` + `test_li_dm_aborted_for_orphan_intent`
rows have something to assert against:

* **`ledger/events-2026-04-15.jsonl` orphan `li_invite_intent`** for
  Carol on 2026-04-19 (intent_id `li_synthetic_orphan_invite_01`).
  Models a Pillar C Week 2 dispatcher crash between `li_invite_intent`
  write and the MCP-call's success — the orphan has no matching
  `li_invite_confirmed | li_invite_failed | li_invite_aborted`
  outcome event. Reconcile Pass D (Week 4) walks this intent +
  queries the (fake) LinkedIn sent-invitations surface; the empty
  fixture (no matching marker) triggers the abort-after-grace path
  per ADR-0017 D50.

* **`ledger/events-2026-04-15.jsonl` orphan `li_dm_intent`** for
  Dana on 2026-04-19 (intent_id `lidm_synthetic_orphan_dm_01`).
  Models a Week 3 dispatcher crash between `li_dm_intent` write and
  the MCP-call's success. Reconcile Pass E (Week 4) walks this
  intent + queries the (fake) LinkedIn conversation surface; the
  empty fixture triggers the abort-after-grace path per ADR-0017 D50.

Both orphans coexist with the existing migration-emitted pairs (Carol
already has a `li_invite_intent`+`li_invite_confirmed` pair at
2026-04-18; Dana's `ledger/0004` backfilled `li_dm_intent`+
`li_dm_confirmed` pair lives under a `bf_lidm_<hash>` intent_id).
The orphans' intent_ids are distinct, so the indexer treats them
as independent two-phase commit instances.

Aggregate count impact on the existing migrations:

* `vault/0001` / `vault/0002` / `vault/0003`: unchanged (Week 4
  ships no vault migration; orphans are ledger-only).
* `ledger/0001` / `ledger/0002` / `ledger/0003` / `ledger/0004`:
  unchanged — Week 4's orphans are typed `li_invite_intent` /
  `li_dm_intent`, not `send_intent`; `ledger/0001` is the only
  intent-closing migration and it targets `send_intent` exclusively
  per ADR-0010. The orphans pass through every migration untouched,
  ready for reconcile Pass D / E to recover.

## Pillar C Week 5 extension (Twitter DM dispatcher + reconcile Pass F substrate)

Per the Pillar C Week 5 handoff (`.planning/HANDOFF-pillar-c-week-5.md`
§"Phase 2 deliverable 10-12" — fixture extension for the Twitter DM
dispatcher + ledger/0005 backfill + reconcile Pass F coherence test),
the fixture has been extended with one Twitter Person + one Twitter
DM touch + one orphan `tw_dm_intent`:

* **`vault/10 People/Evan Estefan.md`** — a fifth Person modeling a
  Twitter-active founder. Has both `linkedin:` (for identity strength
  via the `-li` mint_id provenance per Phase 5.5) AND `twitter_handle:`
  (the Pillar C Week 5 Twitter DM channel-surface field per ADR-0018
  D60; no follow-state gate). Evan's identity_keys for vault/0002
  resolve to `evan-estefan-li`.

* **`vault/40 Conversations/2026-04-22 Evan twitter dm.md`** — Evan's
  Twitter DM touch with `channel: twitter` + `sent: true`. Pillar C
  Week 5's `ledger/0005_baseline_tw_dm_history` walks this + emits a
  retroactive `tw_dm_intent` + `tw_dm_confirmed` pair with deterministic
  `bf_twdm_<hash>` intent_id. No `twitter_action:` frontmatter field
  per ADR-0018 D61's deferral (Twitter has no invite-vs-DM ambiguity).

* **`ledger/events-2026-04-15.jsonl` orphan `tw_dm_intent`** for
  Evan on 2026-04-21 (intent_id `twdm_synthetic_orphan_dm_01`).
  Models a Pillar C Week 5 dispatcher crash between `tw_dm_intent`
  write and the cookie-scrape MCP-call's success — the orphan has no
  matching `tw_dm_confirmed | tw_dm_failed | tw_dm_aborted` outcome
  event. Reconcile Pass F (Week 5) walks this intent + queries the
  (fake) Twitter recent-DMs surface; the empty fixture (no matching
  marker) triggers the abort-after-grace path per ADR-0017 D50
  (inherited by Pass F via D62's generalized helper).

The orphan coexists with the migration-emitted pair (Evan has a
`ledger/0005`-backfilled `tw_dm_intent`+`tw_dm_confirmed` pair under a
`bf_twdm_<hash>` intent_id; the synthetic orphan uses a distinct
`twdm_synthetic_orphan_dm_01` id). Independent two-phase commit
instances.

Aggregate count impact on the existing migrations:

* `vault/0001` / `vault/0002`: 4 → 5 enrolled (Alice / Bob / Carol /
  Dana / Evan). Evan's id ends in `-li` per the mint_id contract.
* `vault/0003`: unchanged — Evan's Twitter touch has no
  `linkedin_action:` field to stamp.
* `ledger/0001`: unchanged — Week 5's orphan is `tw_dm_intent`, not
  `send_intent`; passes through untouched.
* `ledger/0002`: `enrolled_emitted` 4 → 5; `sends_emitted` 3 → 4
  (Alice email + Alice linkedin invite + Dana linkedin dm +
  Evan twitter dm); `orphans_emitted` unchanged.
* `ledger/0003` / `ledger/0004`: unchanged — Week 5's Twitter touch
  is `channel: twitter`, which the LinkedIn-channel walkers
  (`_walk_linkedin_touch_records`) silently skip.
* `ledger/0005` (Week 5): `twitter_dm_pairs_emitted` 1 (Evan's DM).

## Pillar C Week 6 extension (Calendar booking dispatcher + Cal.com webhook substrate)

Per the Pillar C Week 6 handoff (`.planning/HANDOFF-pillar-c-week-6.md`
§"Phase 2 deliverable 10-12" — fixture extension for the Calendar
booking dispatcher + ledger/0006 backfill + Cal.com webhook coherence
test), the fixture has been extended with one Calendar-active Person +
one Calendar booking touch:

* **`vault/10 People/Fiona Forrest.md`** — a sixth Person modeling a
  Calendar-engaged founder. Has `email:` (for cross-channel rule
  substrate) AND `linkedin:` (for identity strength via `-li` mint_id
  provenance) AND `calendar_booking_url_base:` (the Pillar C Week 6
  per-Person Cal.com base URL override per ADR-0019 D65; absent →
  dispatcher uses operator-default). Fiona's identity_keys for
  vault/0002 mint to `fionaforrest-li` (from the LinkedIn slug
  ``in/fionaforrest`` per the existing `identity.mint_id` shape).

* **`vault/40 Conversations/2026-04-25 Fiona calendar booking.md`** —
  Fiona's Calendar booking touch with `channel: calendar` +
  `sent: true`. NO `calendar_booking_confirmed_at:` field — modeling
  the "link shared, recipient has not yet booked" state per ADR-0019
  D69's asymmetric backfill semantics. Pillar C Week 6's
  `ledger/0006_baseline_calendar_booking_history` walks this + emits a
  retroactive `calendar_booking_intent` (no paired `_confirmed`)
  with deterministic `bf_cb_<hash>` intent_id.

NO orphan `calendar_booking_intent` substrate (Week 6 does NOT ship a
reconcile Pass G per ADR-0019 D68's defer-with-rationale decision —
the Cal.com webhook is the canonical recovery path; periodic reconcile
would duplicate effort). The webhook handler's tests (in
`tests/test_cal_com_webhook.py`) exercise the receipt path directly
via hand-constructed Cal.com payloads.

Aggregate count impact on the existing migrations:

* `vault/0001` / `vault/0002`: 5 → 6 enrolled (Alice / Bob / Carol /
  Dana / Evan / Fiona). Fiona's id ends in `-li` per the mint_id
  contract.
* `vault/0003`: unchanged — Fiona's calendar touch has no
  `linkedin_action:` field to stamp.
* `ledger/0001`: unchanged — Week 6 ships no orphan substrate.
* `ledger/0002`: `enrolled_emitted` 5 → 6; `sends_emitted` 4 → 5
  (Alice email + Alice linkedin invite + Dana linkedin dm +
  Evan twitter dm + Fiona calendar booking); `orphans_emitted` unchanged.
* `ledger/0003` / `ledger/0004` / `ledger/0005`: unchanged — Week 6's
  Calendar touch is `channel: calendar`, which the LinkedIn / Twitter
  walkers silently skip.
* `ledger/0006` (Week 6): `calendar_intents_emitted` 1 (Fiona's
  booking touch); `calendar_confirmeds_emitted` 0 (asymmetric — touch
  has no `calendar_booking_confirmed_at:` per ADR-0019 D69).
