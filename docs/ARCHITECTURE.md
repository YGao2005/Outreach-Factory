# Architecture

## Pipeline stages

```
Discovery (background)  →  Research      →  Draft + voice translate  →  [Review]  →  Send
  find-leads etc.          research-prospect    draft-outreach              you         send-outreach
  continuous               per-prospect         per-prospect                 batched     batched
  fresh context            fresh context        fresh context (inline humanize)          (Gmail + LinkedIn)
```

Each stage is a separate Claude Code skill. State persists in markdown frontmatter on each Person note. The `/dispatch-outreach` skill (Phase 3) advances prospects through these stages by spawning fresh-context Agent-tool subagents.

## State machine (frontmatter-driven)

Each prospect's Person note has a `pipeline_stage` field that advances through:

```
queued → researched → drafted → ready → sent
```

| From       | To         | Skill              | Trigger        |
|------------|------------|--------------------|----------------|
| queued     | researched | /research-prospect | dispatcher     |
| researched | drafted    | /draft-outreach    | dispatcher     |
| drafted    | ready      | (user review)      | manual gate    |
| ready      | sent       | /send-outreach     | dispatcher     |
| sent       | —          | terminal           | —              |

`pipeline_stage` is the orchestrator's state-machine field. It is **distinct from the CRM `status:` field** (queued / contacted / replied / ...) — `/send-outreach` owns `status:`, the dispatcher owns `pipeline_stage:`. They don't conflict.

`/draft-outreach` already runs the humanizer inline as its final pass, so there is no separate `checked` stage. `/humanizer` remains available for manual second-passes.

Stage transitions are atomic per prospect — one subagent processes one prospect through one transition at a time, with marker-file locks at `<vault>/.outreach-factory/locks/<sanitized>.lock`. Stale locks (>30 min) are breakable.

## Subscription billing

All Claude work runs through Claude Code session subagents (Agent tool) or `/schedule` routines — both subscription-billed. The only Python is `orchestrator/voice_retrieve.py` which does local CPU-only retrieval (no Anthropic API calls).

See [BILLING.md](BILLING.md) for the full matrix.

## Why fresh context per stage

Single-session context pollution is the root cause of voice fidelity failures in LLM-generated outreach. When the same session does discovery + research + drafting + humanization, the model's context fills with prospect-specific facts AND drafting voice patterns AND prior session content. By the time it generates prose, the context is biased toward whichever previous output it produced.

Fresh subagent per stage solves this architecturally:
- Each subagent starts with no conversation history
- The skill execution is its only context
- The output is shaped by skill + retrieval + prospect dossier, not by what the parent session was doing
- Multiple prospects can be processed in parallel without contaminating each other

## Concurrency model

- **Across prospects**: parallel — N subagents on N different prospects simultaneously
- **Within a prospect**: serial — one stage at a time, frontmatter advances atomically
- **File locking**: the dispatcher holds the queue; agents only touch files for prospects assigned to them

## Voice translator (RAG + inline rewrite)

The voice translator has two pieces:

1. **Retrieval (`orchestrator/voice_retrieve.py`)** — local, CPU-only. Loads embeddings of the user's email corpus (bge-small-en-v1.5 from sentence-transformers), retrieves top-5 most-similar exemplars to the draft using cosine similarity with recency bias. Outputs JSON. $0, no API.

2. **Rewrite (in-agent)** — the skill instructs the agent to build a rewrite prompt from the retrieve output (5 exemplars + hard rules) and produce the rewritten draft as part of its own LLM output. Subscription-billed.

The split exists because the previous implementation (`voice_translate.py`) called the Anthropic API directly via `ANTHROPIC_API_KEY` and bypassed the subscription. See [BILLING.md](BILLING.md).

## Open design questions

- **Corpus quality**: how many emails are enough? n=224 (the original Aiyara corpus) is workable but reply-heavy; cold-pitch register is underrepresented. Recommendation: augment with explicit cold-pitch examples + register-tagged retrieval.
- **Per-window throughput**: Claude Max has a 5-hour rolling message window (~200-225 msgs). End-to-end factory at ~5-10 LLM calls per prospect = ~25-40 prospects per window. Real ceiling.
- **Template strategy**: cold-pitch is currently 2-question discovery-led. Free-work-offer pattern (lead with concrete value, low-friction CTA) is queued as a register variant.

## Roadmap

- **Phase 1** (✅ shipped 2026-05-14, commit `451f38a`): Repo scaffold + `/draft-outreach` migrated to config-driven.
- **Phase 2 + 2.5** (✅ shipped 2026-05-14, commits `ad477f2` + `7aa85d5`): Migrated remaining 6 skills (`humanizer`, `research-prospect`, `find-leads`, `send-outreach`, `find-funded-founders`, `competitor-customers`). Retired legacy `/draft-cold-touch`. Retired API-billed `voice_translate.py`.
- **Phase 3** (✅ shipped 2026-05-14, commit `c23c29d`): Orchestrator. `/dispatch-outreach` skill + `orchestrator/state_machine.py` + `orchestrator/locks.py`. State machine advances prospects through `queued → researched → drafted → ready → sent` via fresh-context Agent-tool subagents.
- **Phase 4** (✅ shipped 2026-05-14, commit `f38deba`): Hardening + auto-enrollment bridge. `find_person_note()` re-locator; explicit Phase 5 BLOCKED writeback; auto stale-lock cleanup at every dispatch; `orchestrator/enrollment.py` + `--enroll` flag on the 3 discovery skills (default OFF for one release).
- **Phase 5** (✅ shipped 2026-05-15, commits `7dcf5f1` + `f7f50b1` + `2b72000` + `75703f2`): OSS-readiness. Consolidated 6 voice + email scripts from the original author's private repo into `voice/` + `orchestrator/`. Added Tier 1 (MX-check) email verification via `verify_email.py` so OSS users don't need a Reoon API key by default. `scripts/doctor.py` preflight covers required + per-feature optional checks. Documentation (README + INSTALL + `docs/OPTIONAL-FEATURES.md`) walks a fresh user from clone to first-run.
- **Phase 5.5** (🚧 in progress, Week 1 shipped 2026-05-15): Robustness layer to land before public OSS release. Replaces the existing name-only dedup in `enrollment.py` / `state_machine.find_person_note` with a multi-key identity graph (LinkedIn slug + email + GitHub + Twitter, strict-policy matching with single-class-email ambiguity escalation). Followed by an append-only outreach ledger at `~/.outreach-factory/ledger/events.jsonl`, two-phase commit on every Gmail/LinkedIn send (intent → confirm with `X-Outreach-Intent-Id` header for crash recovery), bidirectional reconciliation against the Gmail API, declarative cooldown rules, and a full test harness. **Week 1a** (identity layer + 105 tests) is in tree. **Week 1b** (identity-aware refactor of `enrollment.py` and `state_machine.find_person_note`, `backfill_identity.py` one-time migration with Union-Find conflict clustering + surgical frontmatter insertion, 55 new tests; dry-run validated against Yang's 56-note vault: 0 identity-graph conflicts surfaced, 2 closed-cohort notes drop to `-tmp` IDs as expected) is in tree. Week 2 (ledger primitive + two-phase commit) is the next slice. Once 5.5 lands, "have we sent to this person already?" is a hard pre-send gate that never fails open.

### Parking lot

- **Voice corpus builder skill** (`/build-voice-corpus`): automate what
  `voice/README.md` documents manually today. Build if there's user demand;
  the manual path works.
- **Headless dispatcher** (`orchestrator/dispatcher.py`): subprocess `claude -p`
  for overnight runs with `ANTHROPIC_API_KEY` unset (per BILLING.md). Real
  bottleneck is human review at `drafted → ready`, not "wishing I could run
  this overnight" — parked.
- **Flip `--enroll` defaults from OFF→ON**: once a first weekly run with
  `--enroll` lands cleanly, flip the default in the 3 discovery skill bodies.
- **`/init-outreach-factory` skill**: interactive bootstrap that walks
  through `~/.outreach-factory/config.yml` with prompts and runs doctor.
  Doctor + INSTALL + OPTIONAL-FEATURES cover the same ground without skill
  UX polish; the skill is sugar.
