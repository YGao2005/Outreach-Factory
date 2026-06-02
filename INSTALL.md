# Installation

## Prerequisites

- macOS or Linux with Claude Code installed (interactive CLI)
- Claude Max or Pro subscription (factory uses subscription billing, not API)
- Python 3.11+
- A markdown-based CRM (Obsidian vault recommended, but any directory of `.md` files with frontmatter works)
- Your own email corpus for the voice translator (see "Voice corpus setup" below)

## Quick install

```bash
# 1. Clone the repo somewhere stable
git clone <your-fork> ~/code/outreach-factory
cd ~/code/outreach-factory

# 2. Install Python dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r orchestrator/requirements.txt

# 3. Copy the config + .env templates into ~/.outreach-factory/
./bin/outreach-factory config

# 4. Edit the copied files:
#      ~/.outreach-factory/config.yml   company, founder, vault, voice corpus paths
#      ~/.outreach-factory/.env         secrets (Reoon / Resend / suppression), if you use them

# 5. Bootstrap the reply classifier pattern file (Pillar D Week 2).
#    The classifier is part of the reconcile chain: `reconcile.py --full`
#    runs Pass G (rule-based unsubscribe classification) once the pattern
#    file exists. Without it, Pass G refuses to run with a clear bootstrap
#    message (no silent fallback). Per ADR-0026 D103.
mkdir -p ~/.outreach-factory/classifier
cp config-template/unsubscribe-patterns.example.yml \
   ~/.outreach-factory/classifier/unsubscribe-patterns.yml
#    Optionally tune the pattern set for your vertical (B2B vs consumer vs
#    regulated industries see different reply phrasings). The defaults are
#    conservative: they catch the common unsubscribe phrasings without
#    false-positives on legitimate replies.

# 6. Install skills (symlinks repo skills into ~/.claude/skills/).
./install.sh

# 7. Onboard end-to-end (Gmail OAuth, vault setup, first prospect, a real
#    test send). Preview the wiring with --dry-run first.
./bin/outreach-factory init --dry-run
./bin/outreach-factory init

# 8. Restart Claude Code so it picks up the new skills.
```

## MCP servers (required)

The factory talks to your CRM, LinkedIn, and the web through three MCP servers
that run alongside Claude Code. **The factory will silently fail on first skill
invocation without them.** Install all three:

| MCP | Package | Used by | Auth |
|---|---|---|---|
| `obsidian` | [mcp-obsidian](https://pypi.org/project/mcp-obsidian/) | All skills (CRM read/write) | Obsidian's [Local REST API plugin](obsidian://show-plugin?id=obsidian-local-rest-api) — install in your vault, copy the API key the plugin shows |
| `linkedin` | [linkedin-scraper-mcp](https://pypi.org/project/linkedin-scraper-mcp/) | `/find-leads`, `/find-funded-founders`, `/competitor-customers`, `/research-prospect`, `/send-outreach` | Logged-in LinkedIn cookies — set up inside the MCP itself |
| `ScraplingServer` | [scrapling](https://pypi.org/project/scrapling/) | `/research-prospect` (Twitter / blog / web scraping) | None for the server; Twitter cookies if you want past-bio post content (see [docs/OPTIONAL-FEATURES.md](docs/OPTIONAL-FEATURES.md)) |

### Configure them

MCP servers live in `~/.claude.json` under the top-level `mcpServers` key
(user-scoped — available to every Claude Code session) or in a project-local
`.mcp.json` (limited to one project). For factory use, prefer user scope.

A minimal `~/.claude.json` `mcpServers` block looks like:

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "uvx",
      "args": ["mcp-obsidian"],
      "env": {
        "OBSIDIAN_API_KEY": "<paste from Obsidian Local REST API plugin>",
        "OBSIDIAN_HOST": "127.0.0.1",
        "OBSIDIAN_PORT": "27124"
      }
    },
    "linkedin": {
      "type": "stdio",
      "command": "uvx",
      "args": ["linkedin-scraper-mcp"]
    },
    "ScraplingServer": {
      "type": "stdio",
      "command": "scrapling",
      "args": ["mcp"]
    }
  }
}
```

You can also add servers via CLI (`claude mcp add ...`) — see `claude mcp
--help`.

### Verify

```bash
claude mcp list
# Should list at least: obsidian, linkedin, ScraplingServer
```

The factory's preflight (`scripts/doctor.py`) parses `~/.claude.json` to
verify the MCPs are *configured*, but it can't probe live MCP servers — they
are session-scoped to a Claude Code session. Reachability is tested
implicitly when a skill first invokes a server.

## Voice corpus setup

The voice translator retrieves the top-5 most-similar emails from your own
corpus to ground tone rewrites. To build it:

1. Export your sent mail (Gmail Takeout `.mbox`).
2. Build embeddings + index with the flag-driven scripts documented in
   [voice/README.md](voice/README.md): `parse_mbox`, then `refine`, `curate`,
   `build_index`. They default to writing `~/.outreach-factory/voice-corpus/`.
3. Point `voice.corpus_dir` in your config at that directory (the one holding
   `embeddings.npy` + `index.json`).

Without a corpus the voice translator falls back to plain agent-only rewriting
(lower fidelity but still works).

## Verify install

```bash
# Run the preflight — covers config, factory, vault, deps, MCPs, and
# all optional features.
python3 scripts/doctor.py

# Should load without error
python3 orchestrator/voice_retrieve.py --help

# In Claude Code, restart your session and the skills should appear:
# /draft-outreach   /research-prospect   /find-leads   /humanizer
# /send-outreach   /dispatch-outreach   /find-funded-founders   /competitor-customers
```

If `doctor.py` reports any required failures, fix those first — the factory
will not work until they pass.

## Apply pending migrations

`doctor.py` reports the migration framework's schema-evolution state. On a fresh
install, it will warn about pending Pillar B migrations:

```
⚠ migrations             5 pending: vault/0001_*, vault/0002_*, ledger/0001_*, ledger/0002_*, policy/0001_*
   hint: apply: python -c "..."
```

Apply them via the migration runner (the hint surfaces the exact REPL command;
the canonical form is):

```bash
python -c "from pathlib import Path; \
  from orchestrator.migrations import MigrationRunner; \
  r = MigrationRunner(vault_dir=Path('~/your-vault').expanduser()); \
  print('dry-run preview:'); \
  [print(' ', x.migration_id, '→', x.affected_count, 'affected') for x in r.dry_run()]; \
  print('applying...'); \
  r.apply(); \
  print('done')"
```

Replace `~/your-vault` with the path you set as `vault.path` in
`~/.outreach-factory/config.yml`. The dry-run prints one line per pending
migration with the affected count; `ledger/0002` will report 0 because of the
documented cross-category dependency on `vault/0002` (see [docs/adr/0013-replay-exit-criterion-vehicle.md](docs/adr/0013-replay-exit-criterion-vehicle.md)
§D24-N) — the real `apply()` produces the correct counts.

Re-run `python3 scripts/doctor.py` after applying — the migrations check should
now report `✓ no pending migrations`.

### If apply fails mid-batch

The framework guarantees atomicity at the state-file level: a migration that
crashes mid-batch is NOT marked applied, and re-running `r.apply()` resumes
from where it failed. Per-file atomicity (tmp-then-rename) guarantees no
half-written Person notes or policy files. The safe recovery is to fix the
underlying cause (whatever the exception said) and re-run `r.apply()`. Do
NOT manually edit `~/.outreach-factory/migrations.state.json` — the
idempotence checks in each migration handle the resume cleanly.

For the conflict case specifically (`IdentityBackfillConflictError` from
`vault/0002` when two Person notes share an identity key), fix the conflict
by editing the offending Person notes' frontmatter (the error message names
the files + shared keys), then re-run `r.apply()`.

### Strict mode (opt-in)

Set `OUTREACH_FACTORY_STRICT_MIGRATIONS=1` in your environment to promote
pending migrations from WARN to FAIL — doctor's exit code becomes 1 when
anything is pending. Pillar I will flip this as the default; the env var
opts in early. See [docs/adr/0013-replay-exit-criterion-vehicle.md](docs/adr/0013-replay-exit-criterion-vehicle.md)
§D26 for the rationale.

## Worked examples

The core ships use-case agnostic. Complete worked tenants live under
[`examples/`](examples/) and are NOT installed by `install.sh`. The
[`examples/scholarfeed/`](examples/scholarfeed/) tenant is a full reference:
arXiv-based researcher discovery, a verbatim cold-touch assembler, trial-key
provisioning, and a per-tenant config that wires the generic suppression check.
Opt in by following that directory's README (symlink its skill, copy its
`config.scholarfeed.example.yml`, and select it with `OUTREACH_FACTORY_CONFIG`).

## Running headless (Docker)

For an always-on, single-tenant daemon (instead of the interactive Claude Code
skills), the repo ships a container bring-up:

```bash
docker compose -f infra/docker-compose.yml up
```

The daemon (`orchestrator/daemon/`) runs the reconcile + dispatch loop on a
schedule, sharing the same ledger and config as the skills track. The skills
track above is the interactive path; this is the unattended one.

## Uninstall

```bash
./uninstall.sh
# OR manually:
rm ~/.claude/skills/draft-outreach     # only if symlink to repo
rm -rf ~/.outreach-factory             # your config (CAUTION: deletes your config)
```
