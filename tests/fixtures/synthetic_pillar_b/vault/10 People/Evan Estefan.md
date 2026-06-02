---
type: person
name: Evan Estefan
linkedin: https://linkedin.com/in/evanestefan
twitter_handle: evan_estefan
company: "[[Estefan Labs]]"
status: contacted
research_tier: A
created: 2026-04-15
first_touch: 2026-04-22
last_touch: 2026-04-22
pipeline_stage: contacted
country: US
---

# Evan Estefan

Founder, Estefan Labs. Discovered via a `/find-funded-founders` run from
his Twitter Series A announcement post; Twitter is his primary public
presence (LinkedIn profile exists but he posts ~10x more on Twitter).

## Notes

Pillar C Week 5 fixture extension (synthetic_pillar_b/vault/10 People/):
Evan is a Twitter-active founder. His `linkedin:` URL provides identity
provenance (Phase 5.5 mint logic produces a `-li` suffix from the LinkedIn
slug); his `twitter_handle:` is the channel-surface field Pillar C Week 5's
Twitter DM dispatcher (per ADR-0018) reads to decide where to deliver the
outbound DM. Per ADR-0018 D60, the Twitter dispatcher does NOT enforce a
follow-state gate — Twitter's filtered-DM-inbox is recipient-recoverable
(notification badge + approve/decline), so the asymmetric-failure-cost
calculus inverts from LinkedIn's refuse-loud posture.

Evan's `last_touch:` matches his Twitter DM touch (`40 Conversations/
2026-04-22 Evan twitter dm.md`), so ledger/0002's orphan-emit logic does
NOT mark him as an orphan (the touch matches the last_touch invariant per
ADR-0013 D24). Pillar C Week 5's `ledger/0005_baseline_tw_dm_history`
walks his touch + emits a retroactive `tw_dm_intent` + `tw_dm_confirmed`
pair with deterministic `bf_twdm_<hash>` intent_id.
