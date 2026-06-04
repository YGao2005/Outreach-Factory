# ADR-0082: Content distribution foundation, the broadcast surface on the existing spine (hub-and-spoke canonical + per-channel projections, typed source registry, codebase salience primitive, Claude-as-CMO boundary)

- **Status:** Accepted
- **Date:** 2026-06-04
- **Milestone:** Content distribution (the second surface; broadcast 1:many alongside the cold-email 1:1 engine)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0081 built a gated, stateful DISTRIBUTION SPINE: the append-only ledger (source of truth), a declarative policy/guardrail engine, a per-channel two-phase commit with reconcile recovery, a deterministic read-only cadence engine (`orchestrator/followup.py`), a read-only aggregation report (`orchestrator/funnel.py`), warming/cadence pacing, and a humanizer-in-a-fresh-context drafter with an anti-tell checklist. Cold email is the FIRST register on that spine, not the whole product. A `public-comment` register already reaches past 1:1 email.

This milestone adds the SECOND surface: audience content (broadcast), to drive inbound and brand. It takes the operator's own work (a shipped feature in their codebase, a new or high-ranked research paper, a notes file), drafts audience content optimized per channel, distributes it across LinkedIn / X / a blog or newsletter / communities, ingests the engagement signal, and reports what is working. Off by default; the manual review gate is preserved. The scope is pinned in `.planning/SCOPING-content-distribution.md` (the locked-decisions section, 2026-06-04 session 2).

The operator framing is "turn Claude into a CMO": a configurable input (a watcher on a codebase, or a scheduled/filtered feed) writes into ONE canonical source-of-truth piece, which then branches out into whatever distribution platform will consume it (LinkedIn long, X short, blog is the canonical, and so on). The concrete first customer is ScholarFeed: it is both the SUBJECT (the thing being promoted) and the SOURCE (a codebase whose feature ships are announceable, plus a paper corpus reachable via the ScholarFeed MCP).

What is genuinely new here, versus what the spine already carries:

1. A NEW entity (the content piece + its per-channel variants) and its ledger surface.
2. A NEW deterministic engine that decides which approved, scheduled posts are DUE, mirroring the read-only ledger-walk shape of `followup.py` + `funnel.py`.
3. ONE genuinely new sub-primitive: a salience selector over codebase events (most commits are not content; something decides which feature ships earn a post). This is the analog, over diffs, of ScholarFeed's `llm_significance` hook over papers.
4. A NEW engagement feedback loop (the cold side deliberately lacks one), which is what gives "content optimization" teeth.

Everything else reuses an existing primitive: the registers + humanizer, the two-phase dispatch, the policy engine, the warming/cadence pacing, the migration discipline, the status surface, and the binding-criterion gate.

The six concerns this ADR resolves:

1. The content entity shape must be pinned before per-channel dispatch + engagement land. D406 pins `orchestrator/content.py`.
2. The canonical-vs-variant relationship must be decided, or cross-posting silently degrades into truncation. D407 pins hub-and-spoke.
3. The new event classes + the per-channel post-id index must follow the ADR-0014 D33 channel-on-every-event convention + the per-pillar mirror-constant parity discipline. D408.
4. The scheduler + report must preserve the read-only ledger-walk contract per ADR-0059 D325 + the byte-identical determinism per ADR-0031 D140. D409.
5. The source-selection surface (the operator's stated core want, "config what to outreach, easily") must be a typed registry, not a flat list, and the codebase salience primitive must be named as the one net-new build. D410.
6. The reputation-safety + human-gate invariants must be structural, not advisory: communities never auto-post, auto_publish is off, per-channel adaptation is mandatory, no em dashes. D411. The phase staging is D412.

Risks this ADR mitigates by design: R005 (Gmail quota) is untouched (the broadcast surface does not share the Gmail send rail). A NEW risk R043 (self-promo reputation damage) is mitigated by the promotional-ratio guard + the communities-draft-only structural enforcement (D411). A NEW risk R044 (engagement-signal fabrication) is mitigated by the best-effort-per-channel honesty contract: a channel with no readable signal produces no signal and the report says "no signal" rather than guessing (D409). A NEW risk R045 (cross-post-as-truncation read as a bot) is mitigated by the per-channel-adaptation-mandatory invariant + the binding adaptation-refusal test (D407 + D412).

## Decision

### D406. `orchestrator/content.py` entity + typed source registry shape

A NEW module `orchestrator/content.py` ships the entity value types, the source registry, the salience selector seam, the refuse-loud event-builder factories, and the read-only derived-state walk for content pieces. It imports ONLY the ledger + stdlib, mirroring `followup.py`'s lean-import discipline so the surface stays off the heavy operations tier.

The contract:

- `ContentPiece` (frozen dataclass): `content_id`, `source_ref` (the originating source + its key, e.g. a commit range or an arXiv id), `topic`, `pipeline_stage`, `canonical` (the long-form source-of-truth body), `variants` (mapping channel to `ContentVariant`).
- `ContentVariant` (frozen dataclass): `channel`, `body`, `register` (post / thread / essay), plus a `body_hash` for the no-double-post guard. A variant is a register-aware PROJECTION of the canonical, never a byte-slice of it (see D407).
- A typed source registry: `ContentSource` is parsed from a config block into one of `CodebaseSource` (type `codebase`: a `repo` path + a `salience` selector name + a `since` anchor) or `PaperFeedSource` (type `paper_feed`: a `provider` + a `filter` with `min_rank` / `max_age_days` / `topics`). Both implement a uniform `SourceAdapter` seam: `candidates(now) -> list[SourceCandidate]`. Unknown source types refuse loud.
- Refuse-loud event-builder factories (`build_*_payload`) per the ADR-0010 D17 raw-primitive-factory convention, each stamping `_emitted_by="content"`; the caller sets `type`.
- `derived_content_stage(events, content_id) -> str | None`: the content-piece analog of `ledger.derived_stage`, replaying the content lifecycle events to compute the current stage.

The Week-1 (Phase 1) commit ships the module + the two adapters + the salience selector body; the dispatcher is mocked (no real posting) per D412.

### D407. Hub-and-spoke: one canonical source of truth, per-channel projections that are re-expressions not truncations

A `ContentPiece` has ONE `canonical` long-form body (the SUBSTANCE: the claims, the story; the essay/blog register) and per-channel `variants` that are PROJECTIONS of it. Two levels of source of truth: the LEDGER is the source of truth for STATE (drafted, approved, posted, engagement seen); the `canonical` body is the source of truth for SUBSTANCE. The channel variants are denormalized views of the canonical, exactly as vault notes are denormalized views of the ledger.

A variant is a register-aware RE-EXPRESSION of the canonical's substance, not a mechanical truncation of its bytes. X gets the same claims in X's voice and shape (a thread, a hook), not the canonical's first 280 characters. The humanizer + anti-tell runs PER variant. Identical or mechanically-truncated cross-posting is FORBIDDEN and pinned by the binding adaptation-refusal test (D412). This is the load-bearing reputation decision: a CMO that clips one body across N channels reads as a cross-post bot, the fastest way to torch the reputation the spine protects.

### D408. New event classes + the per-channel post-id index (ADR-0014 D33 + the per-pillar mirror-constant parity discipline)

The content lifecycle + distribution two-phase commit + engagement ingest add these event classes, all carrying a top-level `channel` field per ADR-0014 D33 (the pipeline-marker events carry `channel: null` until a per-channel variant exists):

- Pipeline markers: `content_drafted`, `content_humanized`, `content_review_approved`, `content_review_rejected`.
- Two-phase distribution per channel: `distribution_intent`, `distribution_confirmed`, `distribution_failed`. The `channel` is a member of `{linkedin_post, x_post, x_thread, blog, newsletter, reddit, hn, discord}`; the platform post id is the correlation key (the analog of `gmail_message_id`).
- Engagement: `engagement_observed` (per piece, per channel, at a ts: likes / reshares / comments / impressions, whatever the channel exposes).

A NEW mirror constant `content.CONTENT_NEW_EVENT_CLASSES` (frozenset) enumerates these, per the per-pillar mirror-constant parity discipline (ADR-0050 D272, ADR-0070 D376). `observability.EVENT_CLASS_CATALOG` is extended with the same set; the symmetric assertion is a regression-barrier test. The content-piece stage map (`_CONTENT_STAGE_BY_EVENT_TYPE`) and the content lifecycle / two-phase correlation walk live in `content.py` (the entity owns its own derived-state walk, like `followup.py` owns its sequence walk), keeping `ledger.py` lean. Distribution intents use `new_intent_id(prefix="cont_")`.

Phase staging of the ledger edits (so impl matches this ADR): the catalog extension + the `CONTENT_NEW_EVENT_CLASSES` mirror constant + the parity regression-barrier land in PHASE 1 (declarative, and consumed by the observability primitive + the content walk). The `ledger.py` index edits land in PHASE 2 alongside the real two-phase dispatch + reconcile, because only reconcile read-back exercises them: `_INTENT_TYPES` gains `distribution_intent`, `_OUTCOME_TYPES` gains `distribution_confirmed` + `distribution_failed` (the convention holds: intent types end in `_intent`, the confirmed outcome ends in `_confirmed`), and a NEW `_idx_post_id` index (keyed by the platform post id) mirrors `_idx_gmail_msg`. Phase 1's mocked dispatcher does not exercise reconcile, so the content engine does its own correlation walk over the events rather than relying on the ledger intent index.

### D409. The scheduler engine + the optimization report (read-only, deterministic)

A NEW `orchestrator/content_scheduler.py` ships the pure function `compute_due_posts(events, calendar_config, *, now) -> list[PostAction]`, mirroring `compute_due_followups` exactly: `now` is keyword-only (no wall-clock call inside), `events` is an `Iterable[object]` (dicts or `ledger.Event`), the walk is a single read-only pass, and the result is sorted for a stable operator-facing order. Eligibility: the variant is review-approved, scheduled, not yet posted, the channel has cap headroom in the window, and the scheduled time has arrived (business-day / quiet-hours aware, reusing the warming/cadence machinery). It NEVER posts, NEVER mutates the vault, NEVER bypasses a guardrail. Every actual post still passes the policy engine at post time, exactly as a send passes the send gates.

The same module ships the optimization report (a funnel-style read: per hook / format / topic / channel, the engagement rate, "what is working"), deterministic + byte-identical + read-only per ADR-0059 D325 + ADR-0031 D140, surfaced via `--report` / `--json`. The report is correlational + human-in-the-loop: it surfaces, it does not auto-tune. A channel with no readable engagement produces no signal and the report says "no signal" rather than fabricating one (R044 mitigation). In Phase 1 the report is a skeleton (empty until engagement events exist).

### D410. The typed source registry is the operator surface; the codebase salience selector is the one net-new primitive

The Phase 1 centerpiece is a TYPED SOURCE REGISTRY in config (`content.sources`), NOT a flat list. Each source is a declarative block with its own salience knob; adding a source is editing config, not code. This is the operator's stated core want: "config what exactly I want to outreach, easily."

Two first adapters, both pointed at ScholarFeed (the subject and the source):

- `CodebaseSource` (type `codebase`): points at a repo; the `shipped_feature` salience selector decides which commits/releases are announce-worthy. This selector is the ONE genuinely-new primitive in this milestone. Most commits are not content; the selector reads a commit range and returns the announceable subset (release tags, feature-shaped commit subjects, a configurable include/exclude). It is the analog, over diffs, of ScholarFeed's `llm_significance` hook over papers.
- `PaperFeedSource` (type `paper_feed`): points at the ScholarFeed MCP; its "salience" is just a filter (`min_rank` / `max_age_days` / `topics`), which the MCP already exposes, so this adapter is mostly wiring.

The cross-repo / cross-API target (the source points at ScholarFeed, a different repo + a different API than this engine) rides the existing multi-tenant config: a source is tenant-scoped via `OUTREACH_FACTORY_CONFIG` / `TenantConfig`.

The continuous watch loop is DEFERRED: Phase 1 is operator-triggered (`content draft` pulls candidates since the last post across enabled sources). The later daemon watch pass is a thin trigger that calls the same pass on a cadence, so deferring it costs nothing architecturally.

### D411. Reputation-safety + human-gate invariants are STRUCTURAL, not advisory

1. **auto_publish off by default.** The operator reviews every piece before it is scheduled (review to scheduled is the manual gate, mirroring outreach's drafted to ready). Opt-in auto-publish (owned channels only) is a deliberate later step behind the flag.
2. **Communities are draft-and-manual-post in v1, structurally.** The dispatcher has NO auto-post path for reddit/hn/discord; `communities.mode: draft_only` is enforced by the absence of the code path, not a config check, and pinned by the binding test. Auto-promotion in communities is a ban + reputation landmine.
3. **Per-channel adaptation is mandatory.** No identical or truncated cross-posting (D407); the generation skill refuses to emit the same body across channels.
4. **Every post passes the policy engine at post time:** per-channel posting cap, no-double-post (hash of variant body + channel), quiet-hours / posting-window, and a promotional-ratio guard (do not let the feed be 100% self-promo). These are new rules on the SAME engine, not a new gate.
5. **No em dashes anywhere** (the global rule). Reuse the existing draft-style memory for the body voice.
6. **The "Claude as CMO" boundary.** The pipeline IS the five CMO motions (salience, canonical, projections, cadence/guardrails, engagement report). It is the ship-to-distribution reflex, not the strategist: no conversation/community management, no paid, no audience farming, no auto-tuning, no brand/positioning strategy. These omissions are the scope doc's Out-of-scope list.

### D412. Phase staging (build the spine fully, ship channels in risk order)

All four channels in one shot is a scope-creep trap. Build the spine + the channel ABSTRACTION fully, but ship channels in risk/feasibility order so each phase is independently dogfood-able.

| Phase | Deliverable |
|---|---|
| 1 | The entity + ledger events + the scheduler engine (pure, tested) + the generation skill + the optimization report skeleton. NO real posting (mocked dispatcher). Dogfood: draft from a ScholarFeed paper + a ScholarFeed feature ship, review, see the variants + the empty report. |
| 2 | LinkedIn + X dispatch (the two clients we already have) + two-phase commit + reconcile recovery + the guardrails + engagement ingest for these two. |
| 3 | Blog / newsletter (owned channels) + their engagement signal. |
| 4 | Communities in draft_only mode + the per-community norm checklists. |
| 5 | The binding golden-path test + status surface + publish. |

Phase 1's binding unit coverage lands now: the scheduler's eligibility math + the per-channel adaptation-refusal (an identical cross-post is rejected). The full golden-path binding row (source to drafted per-channel variants to review gate to mocked publish to `distribution_confirmed`, plus the guardrail blocking an over-cap + duplicate post, plus an engagement ingest flowing into the report, plus communities never auto-posting) lands at Phase 5 per the scope doc, with the structural pieces pinned from Phase 1.

## Alternatives considered

### D406 alternatives (entity location)

1. **Co-locate the content entity in `orchestrator/ledger.py` or a generic `entity.py`.** Rejected: the content surface is a distinct entity with its own lifecycle, source registry, and salience seam; co-locating would conflate it with the Person entity + bloat the lean ledger module. A dedicated module mirrors the per-surface package precedent (`multi_tenant`, `policy`).
2. **A thin script-only surface instead of a module with value types.** Rejected per the per-surface-foundation precedent: the typed registry + the mirror-constant parity discipline need a structural home; a script would lose the closed-set regression-barriers.

### D407 alternatives (canonical vs variants)

1. **Co-equal per-channel variants with no canonical (the original scope-doc framing).** Rejected: without a canonical, the operator reviews N independent drafts and there is no single substance source of truth; the hub-and-spoke model lets the operator review the story once and glance the projections, and it nests cleanly into the ledger-is-SoT discipline.
2. **Canonical-only, mechanically truncated per channel.** Rejected: mechanical truncation is exactly the cross-post-bot failure mode (R045). Per-channel adaptation must be a re-expression.

### D408 alternatives (event classes)

1. **Reuse the `send_*` family for posts.** Rejected: a post is not a 1:1 send; the correlation key is a platform post id, not a gmail message id, and the channel set is disjoint. A distinct `distribution_*` family keeps the two-phase shape while keeping the surfaces legible. The shape still generalizes per ADR-0014 D33.
2. **Skip the post-id index; scan the ledger per reconcile.** Rejected: the gmail-message-id index precedent exists precisely so reconcile read-back is O(1); the post-id index mirrors it.

### D409 alternatives (scheduler)

1. **Fold the due-posts computation into the dispatcher.** Rejected: the read-only eligibility brain must be separable from the acting dispatcher, exactly as `followup.py` is separable from the send path; this is what keeps the scheduler a pure, testable, byte-deterministic function and lets status + dispatch + the gate share one source of truth.
2. **A stateful scheduler that records "scheduled" state outside the ledger.** Rejected: any scheduled state outside the ledger can survive a cancellation; eligibility is re-derived from the ledger every run (the follow-up cadence's no-stale-state lesson).

### D410 alternatives (source surface)

1. **Keep the flat `sources: []` list from the original scope doc.** Rejected: the operator's core want is easy per-source configuration with per-source salience; a flat list cannot express "high-ranked papers only" vs "announceable ships only" without a type + a knob.
2. **Build the continuous watch loop now.** Rejected (operator's call): defer it; the operator-triggered pass + the salience selector are the load-bearing build, and the watch loop is a thin later trigger over the same pass.

### D411 alternatives (auto-post)

1. **Auto-post to communities behind a config flag in v1.** Rejected: auto-promotion in Reddit/HN/Discord is a ban + reputation landmine; draft-only must be structural (no code path), not a flag a future edit can flip by accident.
2. **auto_publish on for owned channels in v1.** Rejected: the review gate is the spine invariant; opt-in auto-publish for owned channels is a deliberate later step behind the flag.

## Consequences

### Positive

- The broadcast surface reuses every spine primitive (ledger, policy, two-phase dispatch, warming/cadence, humanizer, migration discipline, status, binding gate); the hard substrate is already built.
- The hub-and-spoke model gives the operator a single substance review + clean projections, and nests into the ledger-is-SoT discipline.
- The typed source registry makes "config what to outreach" a config edit; the codebase salience selector is the one net-new primitive and is cleanly testable in isolation.
- The reputation-safety + human-gate invariants are structural (no auto-post code path for communities, auto_publish off, adaptation mandatory), so they cannot be silently regressed.
- The engagement loop gives content optimization teeth without an auto-tuner (the cold-side discipline: surface the signal, the operator decides).

### Negative

- The milestone is multi-phase; only Phase 1 (entity + scheduler + generation + report skeleton, mocked dispatcher) lands first. Real posting + engagement land in Phases 2-3.
- The codebase salience selector is a genuinely new judgment surface; its precision is the variable, and a low-salience commit slipping through produces a weak draft (caught at the review gate, never auto-published).
- The engagement signal is only as good as each channel's readable analytics; channels with no API produce no signal, and the report is honest about that rather than complete.

### Neutral

- The continuous watch loop is deferred; the operator-triggered pass is the Phase 1 trigger and the watch loop is a later thin wrapper.
- ScholarFeed is the first source + subject; the held-out-tenant topology (a different repo + the MCP feed) guards against golden-path overfit, as the cold side's ScholarFeed tenant already does.
