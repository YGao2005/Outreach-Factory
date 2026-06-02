# ADR-0081: Remove the Pillar F voice/embedding subsystem

- **Status:** Accepted
- **Date:** 2026-06-02
- **Pillar:** F (Voice corpus + draft quality) - RETIRED
- **Deciders:** Operator (product-direction call, not in the autonomous loop)

## Context

Pillar F (ADRs 0038-0049) built a voice-fidelity subsystem: a per-user email
corpus (`index.json` + `embeddings.npy` + a sidecar `metadata.json`), an
embedding-retrieval primitive (`voice_corpus.py` / `voice_retrieve.py`), a
five-layer hallucination-and-fidelity gate (`draft_quality.py`), and a `voice/`
build pipeline that ingested the operator's sent mail into the cache. The goal
was that a draft "does not read as AI-written" by anchoring it to the operator's
own past emails via cosine-nearest exemplars.

In practice the subsystem proved brittle and low-yield:

- **It silently no-opped.** The retrieval primitive depends on a curated
  per-user corpus plus a `metadata.json` whose `embed_model` /
  `embed_version` / `schema_version` must match the runtime (ADR-0039 D179 +
  ADR-0038 D178). When the corpus is absent, stale, or version-mismatched, the
  path degrades silently to "no exemplars" rather than refusing loud. A new
  adopter gets zero voice lift with no signal that anything is wrong.
- **It carried a heavy install.** `sentence-transformers` pulls a ~2GB `torch`
  install plus `numpy`, which dominates the dependency footprint of an otherwise
  light tool and makes Docker / CI / fresh-laptop bring-up slow and fragile.
- **Marginal value over a good humanizer pass was low.** The embedding-anchored
  rewrite delivered roughly 85% voice fidelity at best, and only when the corpus
  was rich and current (ADR-0038 R024 voice-drift). A fresh-context rewrite pass
  anchored by one reference example, run inside the agent's own subscription-billed
  LLM call, lands close enough for cold outreach without any of the corpus,
  embedding, or version-matching machinery.
- **The product has been repositioned.** The framing is now an all-in-one
  outreach pipeline for Claude Code, not a per-user voice-cloning engine. A
  multi-gigabyte ML dependency and a corpus-bootstrap step are at odds with that
  positioning and with the OSS-readiness work (ADR-0070; the onboarding CLI).

The hallucination-detection concern Pillar F also carried (un-cited claims must
not ship) is real, but it is enforced more simply by the humanizer-checklist
pass and the draft-outreach register rules, not by an embedding gate.

## Decision

**D402 - Remove the voice/embedding modules and their tests.**
Delete `orchestrator/voice_corpus.py`, `orchestrator/voice_retrieve.py`,
`orchestrator/draft_quality.py`, and the `voice/` build pipeline that populated
the corpus cache (`index.json` + `embeddings.npy` + `metadata.json`). Delete the
roughly 584 tests that exercised these surfaces (the Pillar F unit suites plus
the `TestVoiceCorpusFidelity` / `TestHallucinationDetection` /
`TestPillarFExitCriterion` coherence rows from ADR-0038 D183). The corpus schema,
the per-register adapters, and the five-layer gate go with them.

**D403 - Purge the Pillar F event classes from the catalog, reconcile, and the
daemon index.**
Remove `draft_ready`, `hallucination_detected`, `draft_quality_scored`, and
`voice_exemplar_retrieved` from `EVENT_CLASS_CATALOG`, from any reconcile pass
that emitted or healed on them, and from the per-event-class daemon index
materialization (ADR-0067). The `pipeline_stage: ready` heal no longer consults
a `draft_quality_scored` verdict (it advances on the draft body being present
plus the humanizer-checklist marker). No consumer of these four event classes
remains after this change.

**D404 - Drop the ML dependencies.**
Remove `torch`, `sentence-transformers`, and `numpy` from
`orchestrator/requirements.txt` and any extras group. These were Pillar F's only
callers; nothing else in the tree imports them after D402.

**D405 - Replace the draft prose path with a fresh-context humanizer pass.**
The draft-outreach skill no longer retrieves top-K voice exemplars. Instead it
runs a fresh-context rewrite anchored by a single reference example (one
hand-humanized template body), then a mandatory humanizer-checklist pass, all
inside the agent's own LLM call (subscription-billed, not API-billed, consistent
with the prior `voice_retrieve.py` discipline of keeping the rewrite out of the
framework). The `--manual` scaffolds-only path is unchanged.

## Consequences

- **Positive:** Simpler UX and install - no corpus bootstrap, no
  version-matching `metadata.json`, no silent no-op. No ML dependency, so the
  install drops by roughly 2GB and Docker / CI / fresh-laptop bring-up is fast.
  One fewer source-of-truth (the corpus cache) to back up and sync.
- **Gate total:** the full gate total changes to 3543 by design (the roughly 584
  Pillar F tests are removed). This is expected, not a regression; CI baselines
  update to the new total.
- **Historical ledgers:** existing ledgers may still contain the retired event
  names (`draft_ready`, `hallucination_detected`, `draft_quality_scored`,
  `voice_exemplar_retrieved`). Ledger replay and reconcile tolerate these as
  inert historical records; they are no longer in the catalog and no consumer
  acts on them. The append-only ledger is never rewritten (ADR-0076 invariant 2).
- **Voice fidelity:** drafts rely on the single-reference humanizer pass rather
  than corpus-anchored retrieval. Voice lift is slightly lower than a rich,
  current corpus could deliver, but is consistent across adopters (no corpus to
  curate) and adequate for cold outreach. The no-em-dash and anti-tell rules
  still apply.
- **Plan:** Pillar F is retired. The ten-pillar plan loses its voice-corpus
  pillar; the remaining substrate pillars are unaffected (the Pillar DAG had no
  hard edge into F).

## References

- ADR-0038 D178-D184 - Pillar F foundation (corpus schema, embedding-retrieval
  contract, five-layer hallucination gate, exit-criterion vehicle).
- ADR-0039 D179 - embedding-retrieval primitive + `metadata.json` version match.
- ADRs 0040-0049 - the per-register adapters, fidelity scoring, and the Pillar F
  Stable flip now being retired.
- ADR-0067 - per-event-class daemon index materialization (the index entries for
  the four retired event classes are removed).
- ADR-0070 - Pillar I OSS-readiness foundation (the simpler-install direction
  this decision advances).
- ADR-0001 D2 - refuse-loud convention (the failure mode the silent-no-op
  corpus path violated).
