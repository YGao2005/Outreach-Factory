# Installation

## Prerequisites

- macOS or Linux with Claude Code installed (interactive CLI)
- Claude Max or Pro subscription (factory uses subscription billing, not API)
- Python 3.11+ (the only local Python is CPU-only and light, no model downloads)
- A markdown-based CRM (Obsidian vault recommended, but any directory of `.md` files with frontmatter works)

## Quick install

```bash
# 1. Clone the repo somewhere stable
git clone <your-fork> ~/code/outreach-factory
cd ~/code/outreach-factory

# 2. Install Python dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r orchestrator/requirements.txt
pip install -r skills/send-outreach/requirements.txt   # Gmail send deps (google-*); init needs these

# 3. Copy the config + .env templates into ~/.outreach-factory/
#    (auto-fills factory.home and a default vault.path for you).
./bin/outreach-factory config

# 4. Edit the copied config: company + founder identity, and set
#    founder.email to your real sending address. factory.home and vault.path
#    are pre-filled; change vault.path only if you want your CRM elsewhere
#    (e.g. an existing Obsidian vault).
#      ~/.outreach-factory/config.yml   company, founder, founder.email
#      ~/.outreach-factory/.env         secrets (Reoon / Resend / suppression), if you use them

# 5. (Optional, and can wait until you start handling replies.) Bootstrap the
#    reply-classifier pattern file. It is NOT needed for your first send; the
#    reconcile chain's Pass G (rule-based unsubscribe classification) uses it
#    later and refuses to run with a clear message until it exists (no silent
#    fallback, per ADR-0026 D103).
mkdir -p ~/.outreach-factory/classifier
cp config-template/unsubscribe-patterns.example.yml \
   ~/.outreach-factory/classifier/unsubscribe-patterns.yml

# 6. Install skills (symlinks repo skills into ~/.claude/skills/).
./install.sh

# 7. Scaffold the vault + apply pending migrations (no Gmail/OAuth needed).
#    Creates the vault subdirs the skills expect and applies the Pillar B
#    migrations. `init` does this too, but running it now means a user who
#    later stalls on Gmail OAuth still has a working, doctor-green vault.
./bin/outreach-factory migrate

# 8. Onboard end-to-end (Gmail OAuth, vault setup, first prospect, a real
#    test send). Preview the wiring with --dry-run first.
./bin/outreach-factory init --dry-run
./bin/outreach-factory init

# 9. Restart Claude Code so it picks up the new skills.
```

## MCP servers (optional: discovery + the LinkedIn channel)

These three MCP servers power **discovery** (finding prospects) and the
**LinkedIn channel**. They are NOT needed for onboarding or the core email
loop: `outreach-factory config | init | status` and the draft + Gmail-send path
run on your config, Gmail, and the markdown vault alone. Add an MCP when you
want the feature it unlocks; a missing one is a `doctor` WARN, not a failure.

| MCP | Package | Unlocks | Auth |
|---|---|---|---|
| `obsidian` | [mcp-obsidian](https://pypi.org/project/mcp-obsidian/) | Vault search/patch in the discovery + `/send-outreach` skills (the skills also edit the vault's `.md` files directly) | Obsidian's [Local REST API plugin](obsidian://show-plugin?id=obsidian-local-rest-api) - install in your vault, copy the API key the plugin shows |
| `linkedin` | [linkedin-scraper-mcp](https://pypi.org/project/linkedin-scraper-mcp/) | `/find-leads`, `/find-funded-founders`, `/competitor-customers`, `/research-prospect`, `/send-outreach` | Logged-in LinkedIn cookies - set up inside the MCP itself |
| `ScraplingServer` | [scrapling](https://pypi.org/project/scrapling/) | `/research-prospect` (Twitter / blog / web scraping) | None for the server; Twitter cookies if you want past-bio post content (see [docs/OPTIONAL-FEATURES.md](docs/OPTIONAL-FEATURES.md)) |

### Configure them

MCP servers live in `~/.claude.json` under the top-level `mcpServers` key
(user-scoped - available to every Claude Code session) or in a project-local
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

You can also add servers via CLI (`claude mcp add ...`) - see `claude mcp
--help`.

### Verify

```bash
claude mcp list
# Should list at least: obsidian, linkedin, ScraplingServer
```

The factory's preflight (`scripts/doctor.py`) parses `~/.claude.json` to
verify the MCPs are *configured*, but it can't probe live MCP servers - they
are session-scoped to a Claude Code session. Reachability is tested
implicitly when a skill first invokes a server.

## The humanizer (the de-AI step)

There is no voice-corpus build step. The thing that keeps drafts from reading
as AI-written is the humanizer pass: after `/draft-outreach` assembles a plain
prose draft, it hands that draft to the humanizer in a fresh context, along
with an anti-tell checklist and a single reference example of a good
human-written touch in the same register. The humanizer rewrites whatever
still reads as machine-written and returns the result verbatim.

Nothing to install for this: the humanizer runs inline in the agent's own LLM
call (subscription-billed via your Claude Code session, no Anthropic API call).
It is available as the `/humanizer` skill and runs automatically as the final
pass of `/draft-outreach`. For tier-S high-stakes sends, `/draft-outreach
--manual` emits scaffolds only so you can write the prose yourself.

## Verify install

```bash
# Run the preflight, covering config, factory, vault, deps, MCPs, and
# all optional features.
python3 scripts/doctor.py

# In Claude Code, restart your session and the skills should appear:
# /draft-outreach   /research-prospect   /find-leads   /humanizer
# /send-outreach   /dispatch-outreach   /find-funded-founders   /competitor-customers
```

If `doctor.py` reports any required failures, fix those first - the factory
will not work until they pass.

## Apply pending migrations

`doctor.py` reports the migration framework's schema-evolution state. On a fresh
install, it will warn about pending Pillar B migrations:

```
⚠ migrations             19 pending: vault/0001_* ... ledger/0001_* ... policy/0007_*
   hint: apply: outreach-factory migrate
```

Apply them with the CLI:

```bash
./bin/outreach-factory migrate
```

This scaffolds the vault (and its subdirs) plus the ledger/policy state dirs,
then applies every pending migration against the directories your
`~/.outreach-factory/config.yml` points at. It needs no Gmail or OAuth, so it
is also the way to reach a working, doctor-green vault when you are still
sorting out Google sign-in. It is idempotent: re-running after a clean apply is
a no-op.

Re-run `python3 scripts/doctor.py` after applying - the migrations check should
now report `✓ no pending migrations` and the vault check should pass.

### If apply fails mid-batch

The framework guarantees atomicity at the state-file level: a migration that
crashes mid-batch is NOT marked applied, and re-running `outreach-factory migrate` resumes
from where it failed. Per-file atomicity (tmp-then-rename) guarantees no
half-written Person notes or policy files. The safe recovery is to fix the
underlying cause (whatever the exception said) and re-run `outreach-factory migrate`. Do
NOT manually edit `~/.outreach-factory/migrations.state.json` - the
idempotence checks in each migration handle the resume cleanly.

For the conflict case specifically (`IdentityBackfillConflictError` from
`vault/0002` when two Person notes share an identity key), fix the conflict
by editing the offending Person notes' frontmatter (the error message names
the files + shared keys), then re-run `outreach-factory migrate`.

### Strict mode (opt-in)

Set `OUTREACH_FACTORY_STRICT_MIGRATIONS=1` in your environment to promote
pending migrations from WARN to FAIL - doctor's exit code becomes 1 when
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
