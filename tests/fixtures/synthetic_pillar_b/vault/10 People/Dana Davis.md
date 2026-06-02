---
type: person
name: Dana Davis
linkedin: https://linkedin.com/in/danadavis
company: "[[Davis Robotics]]"
status: contacted
research_tier: B
created: 2026-04-12
first_touch: 2026-04-20
last_touch: 2026-04-20
pipeline_stage: contacted
country: US
linkedin_connected: true
---

# Dana Davis

Founder, Davis Robotics. Pre-existing LinkedIn connection from a prior
conference intro.

## Notes

Pillar C Week 3 fixture extension (synthetic_pillar_b/vault/10 People/):
Dana is a LinkedIn-only Person already connected to the operator. The
`linkedin_connected: true` field is the per-Person state Pillar C Week 3's
LinkedIn DM dispatcher reads (per ADR-0016 D45 — lazy-stamping convention)
to decide whether a DM may be sent. The Week 3 DM dispatcher refuses-loud
on unknown connection state (DM to non-connections silently lands in the
message-request inbox per ADR-0016 D44); Dana's `true` value is the gate
signal for the DM-to-existing-connection happy path.

Dana's `last_touch:` matches her DM touch (`40 Conversations/2026-04-20
Dana linkedin dm.md`), so ledger/0002's orphan-emit logic does NOT mark
her as an orphan (the touch matches the last_touch invariant per
ADR-0013 D24). Pillar C Week 3's `ledger/0004_baseline_li_dm_history`
walks her touch + emits a retroactive `li_dm_intent` + `li_dm_confirmed`
pair with deterministic `bf_lidm_<hash>` intent_id.
