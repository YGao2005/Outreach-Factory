---
type: touch
person: "[[Evan Estefan]]"
channel: twitter
register: cold-pitch
sent: true
sent_at: 2026-04-22
date: 2026-04-22
---

# Twitter DM — Evan Estefan

Hey Evan — saw your Series A thread. The agent-infra direction at Estefan
Labs maps closely to what we've been building at [redacted]; happy to
compare notes on the orchestration architecture if you're open to a quick
exchange.

[…body elided…]

Pillar C Week 5 fixture extension (synthetic_pillar_b/vault/40
Conversations/): this is the Twitter DM touch shape Week 5's coherence
test asserts against. `channel: twitter` is the discriminator that
ledger/0005_baseline_tw_dm_history walks (per ADR-0018); no
`twitter_action:` field per ADR-0018 D61's deferral (Twitter has no
invite-vs-DM ambiguity). ledger/0002 picks this up as a send-pair
(channel: twitter) because it walks every `sent: true` touch regardless
of channel; ledger/0005 walks it AGAIN and emits a retroactive
`tw_dm_intent` + `tw_dm_confirmed` pair. The dual representation is by
design per ADR-0018 §"Backfill overlap with ledger/0002".
