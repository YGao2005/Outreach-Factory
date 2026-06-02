---
type: person
name: Fiona Forrest
email: fiona@forrestlabs.io
linkedin: https://linkedin.com/in/fionaforrest
company: "[[Forrest Labs]]"
status: contacted
research_tier: A
created: 2026-04-15
first_touch: 2026-04-25
last_touch: 2026-04-25
pipeline_stage: contacted
country: US
calendar_booking_url_base: https://cal.com/acme/intro-30
---

# Fiona Forrest

Founder, Forrest Labs. Reached via a follow-up calendar-booking offer
after an email touch on 2026-04-20 (not in this fixture — modeled
abstractly via the calendar touch's frontmatter). Discovered via
`/find-funded-founders` from her Series A announcement.

## Notes

Pillar C Week 6 fixture extension (synthetic_pillar_b/vault/10 People/):
Fiona is a calendar-booking-engaged founder. Her `calendar_booking_url_base:`
overrides the operator-default base URL with a per-Person ``intro-30``
event type (a Cal.com configuration choice — a 30-minute intro call vs
the operator's longer default). Per ADR-0019 D65 the dispatcher
synthesizes ``<base>?intent_id=cb_<ULID>`` and stamps the URL on the
touch note for the operator to share in their outbound message.

The ``calendar_booking_url_base:`` field is OPTIONAL — Persons without
it fall back to the dispatcher's ``cal_com_base_url`` kwarg (the
operator-default per ADR-0019 D65's URL-fragment-marker rationale).

Fiona's identity_keys for vault/0002 mint to ``fionaforrest-li`` (from
the LinkedIn slug ``in/fionaforrest`` per the existing
:func:`identity.mint_id` shape). Her `last_touch:` matches her
calendar-booking touch (`40 Conversations/2026-04-25 Fiona calendar
booking.md`). Pillar C Week 6's
`ledger/0006_baseline_calendar_booking_history` walks her touch + emits
a retroactive `calendar_booking_intent` (no `_confirmed` because her
touch carries NO `calendar_booking_confirmed_at:` field — the recipient
in this fixture has not yet booked; the asymmetric backfill semantics
per ADR-0019 D69 preserve "link shared, not yet booked" vs the
LinkedIn/Twitter "send happened" semantics).
