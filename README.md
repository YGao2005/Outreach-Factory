# outreach-factory

AI-orchestrated cold outreach factory for Claude Code. Subscription-billed (Claude Max plan), parallel agents per prospect, fresh context per stage. Built on top of the Claude Code Agent tool + Obsidian (or any markdown-frontmatter CRM).

## What it does

Runs cold outreach as a factory line:

```
Discovery (background)  →  Research      →  Draft + voice translate  →  Humanizer check  →  [Review]  →  Send
  find-leads etc.          research-prospect    draft-outreach              humanizer            you        send-outreach
  continuous               per-prospect         per-prospect                 per-prospect         batched    batched
  fresh context            fresh context        fresh context                fresh context
```

Each stage is a separate Claude Code skill. Each prospect gets a **fresh-context subagent at each stage** — no contamination across prospects or stages. State persists in markdown frontmatter (Obsidian-shaped vault, but any markdown CRM works).

## Why this exists

LLMs writing cold-pitch prose in a single session produce text that human readers reliably feel as AI-generated, even after multiple humanizer passes. Three drafts produced in one session today (2026-05-14) all carried lexical AI-tells ("basically", "literally", "directly adjacent") that survived editing. Root cause: single-session context pollution + the model's averaged "neutral conversational" register.

Architectural fix: **fresh context per prospect per stage**, with the LLM's role explicitly scoped to scaffolding + retrieval-grounded rewriting. Pair that with a parallel-subagent orchestrator and you get a factory that produces ready-to-send drafts in ~3 minutes per prospect without context pollution.

## Status

**Beta (2026-05-15)** — Phases 1–5 shipped. The full pipeline is operational:
7 config-driven skills; orchestrator dispatcher with state machine + locks +
auto-enrollment; Tier 2 (Reoon) and Tier 1 (free MX-check) email verification;
preflight `scripts/doctor.py`; per-feature opt-in for Reoon / Gmail / Twitter;
voice translator runs locally (no API). Cloneable by a stranger:
`git clone <repo> && ./install.sh && ./bin/outreach-factory init`.

Daily-use ready for the original author; OSS-ready for new users following
[INSTALL.md](INSTALL.md). See [docs/OPTIONAL-FEATURES.md](docs/OPTIONAL-FEATURES.md)
for the per-feature credential matrix.

## Subscription-billed by design

The factory runs entirely on the Claude Max subscription via the Claude Code Agent tool. There is one local Python script (`orchestrator/voice_retrieve.py`) that does CPU-only embedding retrieval — **no Anthropic API calls**. The rewrite happens inline in the agent's own LLM call.

See [docs/BILLING.md](docs/BILLING.md) for the full billing matrix and the subprocess env trap.

## Quick start

```bash
git clone <repo> ~/code/outreach-factory && cd ~/code/outreach-factory
pip install -r orchestrator/requirements.txt
./install.sh                       # symlink the skills + run preflight
./bin/outreach-factory config      # copy the config + .env templates, then edit them
./bin/outreach-factory init        # Gmail OAuth -> vault -> first prospect -> test send
```

Full walkthrough (MCP servers, voice corpus, migrations): [INSTALL.md](INSTALL.md).

## Core vs examples

The repository is a **blank template plus a generic core**, kept separate from
worked examples:

- **Core** — `orchestrator/` (the engine), the generic `skills/`, and
  `config-template/` (the blank `config.yml` + `.env` you fill in). Use-case
  agnostic: no company, tenant, or person is hardcoded into it.
- **Examples** — [`examples/`](examples/) holds complete worked tenants (e.g.
  [`examples/scholarfeed/`](examples/scholarfeed/)) you can read and adapt. They
  are NOT installed by default; you opt in per their README.

To run your own outreach, fill in the templates (the `init` command copies both)
and bring your own voice corpus (see [voice/README.md](voice/README.md)).

## Install

See [INSTALL.md](INSTALL.md).

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT. See [LICENSE](LICENSE).
