# outreach-factory

**Cold outreach that does not read as AI-written, produced by a factory line of fresh-context Claude Code agents.** Subscription-billed on your Claude Max plan (no per-email API cost), one parallel agent per prospect, state in plain markdown.

[![CI](https://github.com/YGao2005/Outreach-Factory/actions/workflows/ci.yml/badge.svg)](https://github.com/YGao2005/Outreach-Factory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Billing: subscription, no API](https://img.shields.io/badge/billing-subscription%2C%20no%20API-success.svg)](docs/BILLING.md)

## See the difference

The whole point is the prose. Here is a generic one-session LLM cold email, then the same touch through this factory (illustrative, following the documented anti-tell rules):

**A single-session LLM writes this** (every reader feels the tells):

> Hi Dr. Chen,
>
> I came across your recent paper and was absolutely blown away by your groundbreaking work on retrieval-augmented agents. You are clearly a leading voice in this space.
>
> I'm building a tool that helps researchers like you basically automate their literature reviews. It leverages cutting-edge AI to surface relevant papers, synthesize key findings, and accelerate your workflow.
>
> I'd love to hop on a quick call to explore how we might collaborate. Let me know what works!

Superlatives, "basically", "leverages cutting-edge", a rule-of-three, manufactured enthusiasm. No edit pass removes that smell, because it is baked in at generation time.

**The factory produces this instead:**

> Hi Dr. Chen,
>
> Your RAG-agents paper came up while I was tracing citation chains for something I'm building, and the retrieval-grounding section is the part I keep coming back to.
>
> The thing is an MCP server that gives a research agent direct access to a 560k-paper corpus with citation graphs and full-text, so the agent does the lookup itself instead of you feeding it PDFs. Free two-week key if you want to point your own agent at it.
>
> Worth a look?

Specific opener, no superlatives, no rule-of-three, no em dashes, concrete and low-key. The difference is architectural, not a better prompt (see [Why this exists](#why-this-exists)).

## What it does

Runs cold outreach as a factory line:

```
Discovery (background)  ->  Research      ->  Draft + voice translate  ->  Humanizer check  ->  [Review]  ->  Send
  find-leads etc.           research-prospect    draft-outreach              humanizer            you        send-outreach
  continuous                per-prospect         per-prospect                 per-prospect         batched    batched
  fresh context             fresh context        fresh context                fresh context
```

Each stage is a separate Claude Code skill. Each prospect gets a **fresh-context subagent at each stage**, so there is no contamination across prospects or stages. State persists in markdown frontmatter (Obsidian-shaped vault, but any markdown CRM works).

## Why this exists

LLMs writing cold-pitch prose in a single session produce text that human readers reliably feel as AI-generated, even after multiple humanizer passes. The tells are structural (em-dash overuse, rule-of-three, marketing-copy intros, manufactured enthusiasm) and survive any number of after-the-fact edits. The root cause is single-session context pollution plus the model's averaged "neutral conversational" register.

The fix is not better humanizing. It is **not generating the averaged prose in the first place**: a fresh context per prospect per stage, with the LLM scoped to scaffolding plus retrieval-grounded rewriting against your own real sent emails. Pair that with a parallel-subagent orchestrator and you get ready-to-send drafts in roughly three minutes per prospect, in your voice, without context pollution.

## What works today

- **A zero-setup demo**: `./bin/outreach-factory demo` prints a complete, voice-grounded cold email for a fake prospect using only the Python standard library, with no Gmail, no API, and no model download. Inside Claude Code, `/draft-outreach --demo` generates one live. See [`examples/demo/`](examples/demo/).
- **The full pipeline**, end to end: discover leads, research a prospect, draft with voice translation, run the humanizer anti-tell checklist, then batch-send over Gmail (and LinkedIn connection requests).
- **Orchestrator**: a dispatcher with a state machine, cross-process locks, auto-enrollment, and an append-only ledger as the source of truth (idempotent, crash-recoverable).
- **Voice translator**: CPU-only local embedding retrieval over your curated email corpus, then an inline rewrite in the agent's own call. No Anthropic API calls.
- **Email verification**: free MX-check (Tier 1) plus optional Reoon (Tier 2).
- **Compliance**: CAN-SPAM body footer and RFC-8058 one-click unsubscribe; pre-send suppression checks; encrypted-at-rest credentials and GDPR right-to-erasure via crypto-shred (the key is destroyed; the append-only ledger is never rewritten). See [ADR-0080](docs/adr/0080-pillar-j-week-5-6-encrypted-credentials-and-gdpr-forget.md).
- **Operations**: OpenTelemetry / Prometheus observability, an optional long-running daemon, and multi-tenant support for running more than one sender from one install.
- **Tested**: a 4286-assertion cross-pillar gate runs in CI on every push.

### Roadmap (not yet shipped, and labeled as such)

- The v1-release security hardening tier: SLSA build provenance, an external penetration test, and formal legal sign-off. Tracked in the decision log, not claimed as done.

## Subscription-billed by design

The factory runs entirely on the Claude Max subscription via the Claude Code Agent tool. There is one local Python script (`orchestrator/voice_retrieve.py`) that does CPU-only embedding retrieval, with no Anthropic API calls. The rewrite happens inline in the agent's own LLM call.

See [docs/BILLING.md](docs/BILLING.md) for the full billing matrix and the subprocess env trap.

## Quick start

See it work before installing anything: clone, then run the demo (standard library only, no `pip install` needed).

```bash
git clone https://github.com/YGao2005/Outreach-Factory.git ~/code/outreach-factory
cd ~/code/outreach-factory
./bin/outreach-factory demo        # zero-setup walkthrough, nothing to install

# then, to run your own outreach for real:
pip install -r orchestrator/requirements.txt
./install.sh                       # symlink the skills + run preflight
./bin/outreach-factory config      # copy the config + .env templates, then edit them
./bin/outreach-factory init        # Gmail OAuth -> vault -> first prospect -> test send
```

Full walkthrough (MCP servers, voice corpus, migrations): [INSTALL.md](INSTALL.md). Per-feature credential matrix: [docs/OPTIONAL-FEATURES.md](docs/OPTIONAL-FEATURES.md).

## Make it yours

The repository is a **blank template plus a generic core**, kept separate from worked examples:

- **Core**: `orchestrator/` (the engine), the generic `skills/`, and `config-template/` (the blank `config.yml` + `.env` you fill in). Use-case agnostic: no company, tenant, or person is hardcoded.
- **Examples**: [`examples/`](examples/) holds complete worked tenants (e.g. [`examples/scholarfeed/`](examples/scholarfeed/)) you can read and adapt. They are not installed by default; you opt in per their README.

To run your own outreach: fill in the templates (the `init` command copies both), bring your own voice corpus (see [voice/README.md](voice/README.md)), describe your ICP, and point `find-leads` at it. To run a second sender, register another tenant using the ScholarFeed example as the template.

## Documentation

- **Using it**: [INSTALL.md](INSTALL.md), [docs/OPTIONAL-FEATURES.md](docs/OPTIONAL-FEATURES.md), [docs/BILLING.md](docs/BILLING.md), [voice/README.md](voice/README.md)
- **Understanding it**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Decision log** (for contributors): the numbered ADRs under [docs/adr/](docs/adr/) record why each part is built the way it is.

## License

MIT. See [LICENSE](LICENSE).
