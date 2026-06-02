# Contributing

Thanks for your interest in outreach-factory. This is a customizable framework:
the goal is a clean, use-case-agnostic core that anyone can build their own
outreach on top of. A few conventions keep it that way.

## Dev setup

```bash
git clone <repo> ~/code/outreach-factory && cd ~/code/outreach-factory
python3 -m venv .venv && source .venv/bin/activate
pip install -r orchestrator/requirements.txt -r requirements-dev.txt
pre-commit install          # gitleaks + lint hooks (see .pre-commit-config.yaml)
```

## Running the tests

The golden-path gate is the binding definition-of-done. Its exit code is the
signal:

```bash
python3 tests/golden_path/gate.py          # fast golden-path regression check
python3 tests/golden_path/gate.py --full   # also runs the whole suite (~2 min)
python3 tests/golden_path/gate.py --status  # per-test outcome table
```

Run `--full` before opening a PR. New behavior should come with a test; a fixed
xfail should have its marker removed so it becomes a permanent regression
barrier.

## Core vs examples (the important one)

Keep the core generic. Do NOT hardcode a company, tenant, person, email, or
absolute home path into:

- `orchestrator/` (the engine)
- the generic `skills/`
- `config-template/`

Anything use-case-specific belongs in a per-tenant config (`config.yml`) or in a
worked example under [`examples/`](examples/). If you build a complete tenant
worth sharing, add it under `examples/<name>/` with its own README, the way
`examples/scholarfeed/` is structured. Examples are not installed by default.

## Secrets and PII

- Secrets (API keys, tokens) load from `~/.outreach-factory/.env` via
  `orchestrator/env_loader.py`. Never read a secret from committed config and
  never commit a real `.env` (`config-template/.env.example` is the template).
- Test fixtures must use synthetic data: RFC-2606 `.example` / `.test` domains
  and made-up names. No real recipients or live addresses in the repo.
- A gitleaks pre-commit hook + osv-scanner/Dependabot are wired in; keep them
  green.

## Architecture decisions

Significant or cross-cutting changes get an ADR in [`docs/adr/`](docs/adr/)
(see the existing numbered files for the shape). Match the surrounding code's
style and comment density.

## Writing style

Outreach copy, docs, and comments avoid em dashes and en dashes (the project
treats them as an AI-writing tell, and `voice/curate.py` even scores for them).
Use commas, colons, or separate sentences instead.
