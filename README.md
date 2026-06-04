# outreach-factory

**An all-in-one cold outreach pipeline that runs inside Claude Code.** Discover prospects, research them, draft the touch, and send it, all in one place. Subscription-billed on your Claude Max plan (no per-email API cost), one parallel agent per prospect, with a real state machine, dedup, and compliance baked in.

*Cold outreach, end to end, inside Claude Code.*

[![CI](https://github.com/YGao2005/Outreach-Factory/actions/workflows/ci.yml/badge.svg)](https://github.com/YGao2005/Outreach-Factory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
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
Discovery (background)  ->  Research      ->  Draft  ->  Humanizer pass  ->  [Review]  ->  Send
  find-leads etc.           research-prospect    draft-outreach   humanizer           you        send-outreach
  continuous                per-prospect         per-prospect     per-prospect        batched    batched
  fresh context             fresh context        fresh context    fresh context
```

Each stage is a separate Claude Code skill. Each prospect gets a **fresh-context subagent at each stage**, so there is no contamination across prospects or stages. State persists in markdown frontmatter (Obsidian-shaped vault, but any markdown CRM works).

## Why this exists

LLMs writing cold-pitch prose in a single session produce text that human readers reliably feel as AI-generated. The tells are structural: em-dash overuse, rule-of-three, marketing-copy intros, manufactured enthusiasm. A big part of the cause is single-session context pollution plus the model's averaged "neutral conversational" register.

The fix is two things, and neither one is a personal voice corpus:

1. **Good scaffolding up front.** Before any prose is generated, the draft is built from a specific dated hook (a real, cited thing the recipient did), a single clear ask, and one slightly vulnerable line that no marketing email would write. Get those three right and most of the AI smell never enters the draft.
2. **A humanizer pass in a fresh context.** A separate, clean-context agent reviews the assembled draft against an explicit anti-tell checklist (and a single reference example of the target style) and rewrites the parts that still read as machine-written. Running this in its own fresh context, rather than the polluted drafting session, is what makes the post-hoc edit actually land.

Pair that with a parallel-subagent orchestrator and you get ready-to-send drafts in roughly three minutes per prospect, without context pollution.

## What works today

- **A zero-setup demo**: `./bin/outreach-factory demo` prints a complete, scaffolded cold email for a fake prospect using only the Python standard library, with no Gmail, no API, and no model download. Inside Claude Code, `/draft-outreach --demo` generates one live. See [`examples/demo/`](examples/demo/).
- **The full pipeline**, end to end: discover leads, research a prospect, draft the touch, run the humanizer anti-tell pass, then batch-send over Gmail (and LinkedIn connection requests).
- **Orchestrator**: a dispatcher with a state machine, cross-process locks, auto-enrollment, and an append-only ledger as the source of truth (idempotent, crash-recoverable).
- **Humanizer**: a fresh-context anti-tell pass that reviews the assembled draft against an explicit checklist plus a single reference example, then rewrites whatever still reads as machine-written. Runs inline in the agent's own call. No Anthropic API calls.
- **Email verification**: free MX-check (Tier 1) plus optional Reoon (Tier 2).
- **Compliance**: CAN-SPAM body footer and RFC-8058 one-click unsubscribe; pre-send suppression checks; encrypted-at-rest credentials and GDPR right-to-erasure via crypto-shred (the key is destroyed; the append-only ledger is never rewritten). See [ADR-0080](docs/adr/0080-pillar-j-week-5-6-encrypted-credentials-and-gdpr-forget.md).
- **Operations**: OpenTelemetry / Prometheus observability, an optional long-running daemon, and multi-tenant support for running more than one sender from one install.
- **Tested**: a 3543-assertion cross-pillar gate runs in CI on every push.

### Roadmap (not yet shipped, and labeled as such)

- The v1-release security hardening tier: SLSA build provenance, an external penetration test, and formal legal sign-off. Tracked in the decision log, not claimed as done.

## Subscription-billed by design

The factory runs entirely on the Claude Max subscription via the Claude Code Agent tool. There are no Anthropic API calls in the happy path. The humanizer pass runs inline in the agent's own LLM call (subscription-billed), so the de-AI step costs nothing per email beyond your existing plan. The only local Python is CPU-only and light.

See [docs/BILLING.md](docs/BILLING.md) for the full billing matrix and the subprocess env trap.

## Quick start

See it work before installing anything: clone, then run the demo (standard library only, no `pip install` needed).

```bash
git clone https://github.com/YGao2005/Outreach-Factory.git ~/code/outreach-factory
cd ~/code/outreach-factory
./bin/outreach-factory demo        # zero-setup walkthrough, nothing to install

# then, to run your own outreach for real:
pip install -r orchestrator/requirements.txt
pip install -r skills/send-outreach/requirements.txt   # Gmail send deps (init needs these)
./bin/outreach-factory config      # copy templates (auto-fills factory.home + a default vault.path); edit company/founder
./install.sh                       # symlink the skills + run preflight (doctor)
./bin/outreach-factory migrate     # scaffold the vault + apply migrations (no OAuth needed)
./bin/outreach-factory init        # Gmail OAuth -> vault -> first prospect -> test send
```

Full walkthrough (MCP servers, migrations): [INSTALL.md](INSTALL.md). Per-feature credential matrix: [docs/OPTIONAL-FEATURES.md](docs/OPTIONAL-FEATURES.md).

## Make it yours

The repository is a **blank template plus a generic core**, kept separate from worked examples:

- **Core**: `orchestrator/` (the engine), the generic `skills/`, and `config-template/` (the blank `config.yml` + `.env` you fill in). Use-case agnostic: no company, tenant, or person is hardcoded.
- **Examples**: [`examples/`](examples/) holds complete worked tenants (e.g. [`examples/scholarfeed/`](examples/scholarfeed/)) you can read and adapt. They are not installed by default; you opt in per their README.

To run your own outreach: fill in the templates (the `init` command copies both), describe your ICP, and point `find-leads` at it. To run a second sender, register another tenant using the ScholarFeed example as the template.

## Documentation

- **Using it**: [INSTALL.md](INSTALL.md), [docs/OPTIONAL-FEATURES.md](docs/OPTIONAL-FEATURES.md), [docs/BILLING.md](docs/BILLING.md)
- **Understanding it**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Decision log** (for contributors): the numbered ADRs under [docs/adr/](docs/adr/) record why each part is built the way it is.

## License

MIT. See [LICENSE](LICENSE).
