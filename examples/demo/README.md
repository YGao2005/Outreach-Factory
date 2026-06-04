# The zero-setup demo

See what the factory produces in about two minutes, with no Gmail OAuth, no MCP
servers, no voice corpus build, and no Anthropic API. Two ways to run it.

## The scenario

You are **Devon**, building **Carillon**, a small open-source Python library for
typed background jobs. You want to cold-email **Riley Okafor**, a staff engineer
who just published a postmortem about a job queue that kept losing tasks.

Everything here is fake. Riley's `okafor.example` address uses the reserved
`.example` TLD and reaches nobody. This is a different scenario from the
before/after in the top-level README on purpose: that one shows an example
tenant (a research tool), while this lives in the use-case-agnostic core.

## Run it without Claude Code (the CLI walkthrough)

```bash
./bin/outreach-factory demo
```

Pure standard library plus PyYAML, both already installed. It prints the four
stages in order: the prospect and the hooks, the scaffold menu the LLM proposes
(options, never prose), your voice exemplars, and the final committed draft. No
model download, no network. The final draft is the one in `sample-draft.md`,
generated earlier by the agent and committed so this path needs no LLM.

## Run it inside Claude Code (the live draft)

```
/draft-outreach --demo
```

This is the full wow: the agent reads the demo prospect and the demo reference
examples, scaffolds, assembles, and rewrites the draft **live in its own call**
(so the prose is generated fresh, never the canned one), then runs the humanizer
checklist. Subscription-billed, no API. Nothing is sent and nothing is written
to a real vault.

## Why there is no machine learning here

There is none anywhere in the product, not just the demo. The thing that keeps
drafts from reading as AI-written is the humanizer: an LLM pass (your own Claude
Code session, no API) that rewrites the assembled prose against an anti-tell
checklist, using one human-written reference example in the same register for
tone. No corpus build, no embeddings, no similarity ranking, no model download,
here or in a real install. The reference touches below are exactly that: a few
human-written examples the agent reads directly.

## What is in this folder

| File | What it is |
|---|---|
| `vault/Riley Okafor.md` | the sample prospect, a Person note with a pre-filled dossier |
| `reference-touches.md` | a few human-written example touches the humanizer reads for tone |
| `scaffold.md` | the Phase 3 option menu (committed for the CLI path) |
| `sample-draft.md` | the final draft the agent produced (committed for the CLI path) |

## Then what

When you are ready to run your own outreach for real:

```bash
./bin/outreach-factory config      # copy the config + .env templates, then edit
./bin/outreach-factory init        # Gmail OAuth -> vault -> first prospect -> test send
```

See the top-level [README](../../README.md) and [INSTALL.md](../../INSTALL.md).
