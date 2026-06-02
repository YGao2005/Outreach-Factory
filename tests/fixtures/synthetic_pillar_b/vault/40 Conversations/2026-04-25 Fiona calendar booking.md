---
type: touch
person: "[[Fiona Forrest]]"
channel: calendar
register: cold-pitch
sent: true
sent_at: 2026-04-25
date: 2026-04-25
calendar_booking_invited_at: 2026-04-25
calendar_booking_intent_id: bf_cb_synthetic_pre_run
---

# Calendar booking — Fiona Forrest

## Calendar

```
Hey Fiona — would love to compare notes on the agent-orchestration
work you're shipping. Grab any 30 minutes that works for you here:

<booking-link will be inserted by the dispatcher>

Looking forward to it.
```

[…body elided…]

Pillar C Week 6 fixture extension (synthetic_pillar_b/vault/40
Conversations/): this is the Calendar booking touch shape Week 6's
coherence test asserts against. `channel: calendar` is the discriminator
that ledger/0006_baseline_calendar_booking_history walks (per ADR-0019).
The touch carries NO `calendar_booking_confirmed_at:` field, so per
ADR-0019 D69's asymmetric semantics the backfill emits ONLY
`calendar_booking_intent` (no paired `_confirmed`) — modeling the
"recipient has not yet booked" state at the moment of the fixture
snapshot. ledger/0002 picks this up as a generic send-pair (channel:
calendar) because it walks every `sent: true` touch regardless of
channel; ledger/0006 walks it AGAIN and emits the per-channel intent.
The dual representation is by design per ADR-0019 §"Backfill overlap
with ledger/0002".
