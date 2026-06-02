# Optional features

The factory works on a minimum viable setup (3 MCPs + config + vault + Python
deps — see [INSTALL.md](../INSTALL.md)). Beyond that, each capability below is
**opt-in per feature** — set it up if you want what it unlocks, skip it if not.
`scripts/doctor.py` reports which features are ready and which need setup.

## At a glance

| Feature | Skill(s) it unlocks | What you need | What you lose without it |
|---|---|---|---|
| **Reoon API key** | `/research-prospect` Tier 2 email verify | API key from [reoon.com](https://reoon.com/) (free 100/mo or paid 600/mo recurring) | Catch-all + spamtrap detection. Falls back to Tier 1 (free MX-check) — works for ~80% of cases (dead domains caught) but misses catch-all-domain risk |
| **Gmail OAuth** | `/send-outreach` Gmail channel | OAuth credentials JSON from Google Cloud Console + a one-time auth flow | Email send. Can still send via LinkedIn DM as fallback |
| **Twitter cookies** | `/research-prospect` cross-platform research | Logged-in browser cookies exported as JSON | Twitter scrape past the public bio. Profile dossiers fall back to bio-only |
| **LinkedIn cookies** | `linkedin` MCP itself (so: discovery + send) | Logged-in browser cookies — set up *inside* the linkedin MCP, not in the factory's config | LinkedIn discovery + LinkedIn send both broken. This one is effectively required if you want any LinkedIn channel |
| **Voice corpus** | `/draft-outreach` voice-translate (RAG) | A built corpus at `voice.corpus_dir` with `embeddings.npy` + `index.json` (see [voice/README.md](../voice/README.md)) | Tone fidelity drops from ~85% to "agent-default" register. Drafts still ship; they sound less like you |

## Setup

### Reoon (Tier 2 email verification)

```bash
# 1. Sign up at https://reoon.com/, get an API key
# 2. Save the key to a file (chmod 600)
mkdir -p ~/.outreach-factory/credentials
echo "<your-key>" > ~/.outreach-factory/credentials/reoon_api_key.txt
chmod 600 ~/.outreach-factory/credentials/reoon_api_key.txt

# 3. Point your config at it
# Edit ~/.outreach-factory/config.yml:
#   email_enrich:
#     reoon_key_path: "~/.outreach-factory/credentials/reoon_api_key.txt"
```

The skill auto-detects: with `reoon_key_path` set + the file present,
`/research-prospect` runs Tier 2 (Reoon power-mode verify, ~$0.005/check).
Without it, falls through to Tier 1 (free MX-check via `dnspython`).

### Gmail send

```bash
# 1. In Google Cloud Console:
#    a. Create a new project (or use an existing one)
#    b. Enable the Gmail API
#    c. Create OAuth credentials (Desktop app type)
#    d. Download the credentials JSON
mkdir -p ~/.outreach-factory/credentials
mv ~/Downloads/credentials.json ~/.outreach-factory/credentials/gmail_credentials.json
chmod 600 ~/.outreach-factory/credentials/gmail_credentials.json

# 2. Edit ~/.outreach-factory/config.yml:
#   email_send:
#     gmail_api: true
#     gmail_credentials_path: "~/.outreach-factory/credentials/gmail_credentials.json"
#     gmail_token_path: "~/.outreach-factory/credentials/gmail_token.json"

# 3. Run the auth flow once (opens browser, you approve, token saved)
#    /send-outreach prompts for this on first invocation if gmail_token_path
#    is missing — no separate auth script needed.
```

The token is refreshed automatically after the initial auth.

### Twitter cookies (cross-platform research)

```bash
# 1. Log into x.com in your browser
# 2. Export cookies as JSON. Either:
#    - Use a browser extension like "Cookie-Editor" → Export
#    - Or use Playwright/Puppeteer to grab them programmatically
# 3. Save to the path the skill expects:
mkdir -p ~/code/outreach-factory/skills/research-prospect/auth
mv ~/Downloads/x.com-cookies.json \
   ~/code/outreach-factory/skills/research-prospect/auth/x.com-cookies.json
chmod 600 ~/code/outreach-factory/skills/research-prospect/auth/x.com-cookies.json

# 4. (Optional) Override the path in config:
#   scraper_auth:
#     twitter_cookies_path: "<your path>"
```

Cookies expire — the skill detects `"Don't miss what's happening"` in fetched
markdown as the "logged out" signal and surfaces a refresh hint.

### LinkedIn cookies

LinkedIn auth lives **inside the `linkedin` MCP**, not in the factory's
config. Refer to the MCP's own README for cookie setup
(`uvx linkedin-scraper-mcp --help` or its PyPI page).

### Voice corpus

See [voice/README.md](../voice/README.md). Quick version:

```bash
# 1. Gmail Takeout → download Sent Mail .mbox
# 2. Edit hardcoded paths at the top of each script in voice/
# 3. Run the 4-step pipeline:
cd ~/code/outreach-factory/voice
python parse_mbox.py
python refine.py
python curate.py
python build_index.py

# 4. Point config at the output:
#   voice:
#     corpus_dir: "~/path/to/your/corpus"
```

A `/build-voice-corpus` skill that automates this is on the parking lot — for
now, the manual path is the only path.

## How to check what's set up

```bash
python3 scripts/doctor.py
```

Output groups checks into Required and Optional, with a one-line message and
"→ enables: ..." line per optional feature. Run any time something feels off
or after changing config.

## Per-feature implications for skills

The factory degrades gracefully — every skill checks for what it needs at
runtime and either falls back or surfaces the gap clearly:

- `/research-prospect` without Reoon → Tier 1 MX-check, slightly higher
  bounce risk on real sends.
- `/research-prospect` without Twitter cookies → bio-only Twitter footprint
  in dossiers, no recent posts.
- `/send-outreach` without Gmail → LinkedIn DM only (or manual paste from
  drafts the factory leaves in `40 Conversations/`).
- `/draft-outreach` without voice corpus → drafts from agent's default
  register; lower voice fidelity.
- Any LinkedIn-touching skill without LinkedIn cookies → fails at first
  invocation with an MCP error. There's no useful fallback for LinkedIn.

If a skill needs a credential you don't have, it'll surface that explicitly
rather than failing silently.
