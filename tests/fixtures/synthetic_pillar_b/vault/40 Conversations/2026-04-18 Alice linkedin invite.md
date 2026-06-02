---
type: touch
person: "[[Alice Anderson]]"
channel: linkedin
register: cold-pitch
sent: true
sent_at: 2026-04-18
date: 2026-04-18
---

# LinkedIn invite — Alice Anderson

Hi Alice, would love to connect — saw your Anderson AI launch. Happy to
share notes from the agent-infra side.

[…body elided…]

Pre-Pillar-C fixture extension (synthetic_pillar_b/vault/40 Conversations/):
this is the LinkedIn touch shape Pillar C's coherence test will assert
against. Date 2026-04-18 is 8 days after Alice's email cold-pitch
(2026-04-10), modeling a realistic email → LinkedIn cross-channel
sequence. ledger/0002's backfill picks this up as a second send-pair
(channel: linkedin); Carol's last_touch-without-touch orphan status
is unaffected (her orphan invariant lives in the email-touch absence).
