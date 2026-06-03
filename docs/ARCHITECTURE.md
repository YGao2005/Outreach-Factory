# Architecture

## Pipeline stages

```
Discovery (background)  ->  Research      ->  Draft + humanizer pass  ->  [Review]  ->  Send
  find-leads etc.           research-prospect    draft-outreach             you         send-outreach
  continuous                per-prospect         per-prospect               batched     batched
  fresh context             fresh context        fresh context              (Gmail + LinkedIn)
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
| sent       | -          | terminal           | -              |

`pipeline_stage` is the orchestrator's state-machine field. It is **distinct from the CRM `status:` field** (queued / contacted / replied / ...) - `/send-outreach` owns `status:`, the dispatcher owns `pipeline_stage:`. They don't conflict.

`/draft-outreach` already runs the humanizer inline as its final pass, so there is no separate `checked` stage. `/humanizer` remains available for manual second-passes.

Stage transitions are atomic per prospect - one subagent processes one prospect through one transition at a time, with marker-file locks at `<vault>/.outreach-factory/locks/<sanitized>.lock`. Stale locks (>30 min) are breakable.

## The framework beneath the skills: four jobs

The skills above are most of what you see. The framework underneath them earns
its keep with exactly four jobs. Everything else in `orchestrator/` is advanced
and optional, and stays off the path that actually sends a cold email.

1. **Onboarding.** Clone to a real, deliverable first send. `outreach-factory
   config` copies the templates; `outreach-factory init` runs the wizard (Gmail
   OAuth, vault scaffold, a self-test send); `outreach-factory doctor` checks
   your setup.
2. **Guardrails.** The honest answer to "why not just skills." A bare skill
   would let you torch your own domain. The framework will not: it never
   double-sends (ledger dedup), never over-contacts (cooldown + cross-channel
   rules), stays compliant (CAN-SPAM footer + one-click unsubscribe +
   suppression), and refuses on a stale or ambiguous identity.
3. **State.** An append-only ledger (`~/.outreach-factory/ledger/`) is the
   source of truth for who was contacted, what stage they reached, and who
   replied. Vault frontmatter is a denormalized view; the ledger is
   authoritative, so a crash or a hand-edit of the vault cannot fail the send
   gate open.
4. **Status.** `outreach-factory status` answers "what went out, who replied,
   what is queued, and am I safe to send more today" from the ledger. No
   dashboards required.

### Where the core lives

| Job | Code |
| --- | --- |
| Onboarding | `orchestrator/cli.py`, `orchestrator/multi_tenant/` (the init wizard), `scripts/doctor.py`, `config-template/` |
| Guardrails | `orchestrator/policy/` (cooldown / suppression / budget / sending-window / cross-channel / tier rules), `orchestrator/security/` (CAN-SPAM + unsubscribe + at-rest encryption), `orchestrator/identity.py` (dedup keys) |
| State | `orchestrator/ledger.py` |
| Status | `outreach-factory status` (`orchestrator/cli.py`) |
| The gated send | `skills/send-outreach/scripts/send_queued.py` (two-phase commit through the guardrails), `orchestrator/obs.py` (a no-op telemetry shim that keeps the send path dependency-light) |

A cold send needs only `google-auth`, `PyYAML`, and `python-dotenv`.

### Advanced / operations (opt-in, off the send path)

The rest of `orchestrator/` is for operators who want continuous, self-reconciling
operation. **None of it is on the path that sends a cold email.** That boundary
is enforced by `tests/test_import_graph_lean.py`, which fails if the send path
ever imports the advanced tier.

- `orchestrator/daemon/` - a long-running supervisor that runs the pipeline as a service.
- `orchestrator/observability.py` - full OpenTelemetry metrics + tracing + a Prometheus exposition. Opt in with `OUTREACH_FACTORY_OTEL=1`; otherwise the no-op `obs.py` shim is used and the OTel SDK is not needed.
- `orchestrator/reconcile.py` - crash recovery + reply/bounce ingestion against the Gmail API.
- reply classification, conversation tracking, discovery dedup/lineage, email enrichment, the calendar webhook, tier assignment, and the funnel diagnostic.
- `orchestrator/migrations/` - a schema-migration framework for the ledger / policy / vault stores.

### Verifying the split

`python3 tests/golden_path/gate.py --core` runs the four jobs + the send path (fast); `--full` runs everything. The suite is about 80% advanced (704 core tests vs 2818 operations), a fair picture of where the surface area is: a small core, a large optional tier.

## Subscription billing

All Claude work runs through Claude Code session subagents (Agent tool) or `/schedule` routines, both subscription-billed. The humanizer pass that de-AIs each draft runs inline in the agent's own LLM call, so it is subscription-billed too with no Anthropic API calls. The only local Python is CPU-only and light.

See [BILLING.md](BILLING.md) for the full matrix.

## Why fresh context per stage

Single-session context pollution is a big part of why LLM-generated outreach reads as machine-written. When the same session does discovery + research + drafting + humanization, the model's context fills with prospect-specific facts AND drafting patterns AND prior session content. By the time it generates prose, the context is biased toward whichever previous output it produced. The humanizer pass in particular only lands when it runs in a clean context: a humanizer sharing the polluted drafting session tends to rubber-stamp its own prose.

Fresh subagent per stage solves this architecturally:
- Each subagent starts with no conversation history
- The skill execution is its only context
- The output is shaped by skill + prospect dossier, not by what the parent session was doing
- The humanizer reviews the assembled draft in its own fresh context, against an anti-tell checklist and a single reference example
- Multiple prospects can be processed in parallel without contaminating each other

## Concurrency model

- **Across prospects**: parallel - N subagents on N different prospects simultaneously
- **Within a prospect**: serial - one stage at a time, frontmatter advances atomically
- **File locking**: the dispatcher holds the queue; agents only touch files for prospects assigned to them

## Humanizer (fresh-context anti-tell pass)

> **Note:** the prior voice-corpus / embedding-retrieval subsystem (Pillar F) was removed. See the Pillar F removal ADR. The de-AI step is now the humanizer pass described here. There is no embedding index, no `sentence-transformers`, and no curated email corpus.

The humanizer is a single rewrite pass that runs after `/draft-outreach` assembles a plain prose draft:

1. **Scaffolding first.** The draft is built from a specific dated hook (a real, cited thing the recipient did), a single clear ask, and one slightly vulnerable line. Getting these right keeps most AI tells out of the draft before any rewrite.

2. **Rewrite (in-agent, fresh context).** The assembled draft is handed to the humanizer in a fresh context (a fresh-context subagent or the `/humanizer` skill), along with an explicit anti-tell checklist and a single reference example of a good human-written touch in the same register. The humanizer rewrites whatever still reads as machine-written and returns the result. This runs as part of the agent's own LLM output, so it is subscription-billed.

The rewrite stays in the agent; it is never shelled out to a Python script that calls the Anthropic API. See [BILLING.md](BILLING.md).

## Open design questions

- **Per-window throughput**: Claude Max has a 5-hour rolling message window (~200-225 msgs). End-to-end factory at ~5-10 LLM calls per prospect = ~25-40 prospects per window. Real ceiling.
- **Template strategy**: cold-pitch is currently 2-question discovery-led. Free-work-offer pattern (lead with concrete value, low-friction CTA) is queued as a register variant.
- **Reference-example selection**: the humanizer takes one reference example per register. Choosing the best single example per register, and whether to vary it per recipient, is open.

## Status

Shipped and public. The skills pipeline, the four framework jobs, and the
guardrails described above are all in tree. The identity graph, the append-only
ledger with two-phase-commit sends, the declarative cooldown/policy rules, and
Gmail reconciliation all landed. For the change history see
[CHANGELOG.md](../CHANGELOG.md); for the decision records see [docs/adr/](adr/).

### Parking lot

- **Headless dispatcher** (`orchestrator/dispatcher.py`): subprocess `claude -p`
  for overnight runs with `ANTHROPIC_API_KEY` unset (per BILLING.md). Real
  bottleneck is human review at `drafted → ready`, not "wishing I could run
  this overnight" - parked.
- **Flip `--enroll` defaults from OFF→ON**: once a first weekly run with
  `--enroll` lands cleanly, flip the default in the 3 discovery skill bodies.
- **`/init-outreach-factory` skill**: interactive bootstrap that walks
  through `~/.outreach-factory/config.yml` with prompts and runs doctor.
  Doctor + INSTALL + OPTIONAL-FEATURES cover the same ground without skill
  UX polish; the skill is sugar.
