---
name: send-outreach
version: 1.0.0
description: |
  Send queued cold-touch outreach in batch — emails via Gmail API + LinkedIn
  connection requests via the LinkedIn MCP — and writeback to the Obsidian vault
  (flip `sent: true`, tick outcome checkboxes, update Person status to `contacted`).
  Use when the user wants to ship the touch drafts that the `/draft-outreach`
  skill has prepared. Step 5 in the outreach pipeline (after find → research → draft → humanize).
license: MIT
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - mcp__linkedin__connect_with_person
  - mcp__linkedin__send_message
  - mcp__linkedin__get_person_profile
  - mcp__linkedin__get_inbox
  - mcp__linkedin__get_my_profile
  - mcp__obsidian__obsidian_get_file_contents
  - mcp__obsidian__obsidian_patch_content
---

# /send-outreach — Ship queued touches (email + LinkedIn) with vault writeback

You are the send-step of the outreach pipeline. Your job: take touch drafts that already exist in the Obsidian vault, send them, and update vault state. The Python core handles email + reconciliation; you handle LinkedIn in-session via the MCP because MCPs aren't callable from standalone Python.

---

## ⚙️ Pre-flight — load user config

**Before doing anything else, read the user's config:**

```bash
cat ~/.outreach-factory/config.yml
```

The Python scripts (under `scripts/`) load the same config automatically. Throughout this skill body, `{config.X}` placeholders (e.g. `{founder.name}`, `{vault.path}`, `{email_send.gmail_credentials_path}`) refer to that file.

**If `~/.outreach-factory/config.yml` does not exist**: abort and tell the user to copy `config-template/config.example.yml` from the outreach-factory repo to `~/.outreach-factory/config.yml` and fill in their values.

---

## Usage

```
/send-outreach                  # default: send queued emails + queue LinkedIn invites
/send-outreach --dry-run        # preview only, no sends
/send-outreach --reconcile      # one-time: fix stale sent:false on already-sent touches
/send-outreach --check-bounces  # scan inbox for mailer-daemon DSNs; mark bounced person notes
/send-outreach --li-check       # re-check pending LinkedIn invites; send DMs to accepted contacts
/send-outreach --only "Name"    # filter to one person (substring match)
```

CLI shortcuts (the symlinked skill resolves to the outreach-factory repo):
- `python ~/.claude/skills/send-outreach/scripts/run.py send`
- `python ~/.claude/skills/send-outreach/scripts/run.py reconcile`
- `python ~/.claude/skills/send-outreach/scripts/run.py check-bounces`

---

## Prerequisites (one-time, ~10 min)

### Gmail OAuth setup

The skill sends from whatever Gmail account you authenticate. **Pick one and stick with it** —
re-auth from a different inbox means re-doing the OAuth flow.

**Setup steps:**

1. Go to [Google Cloud Console → APIs & Credentials](https://console.cloud.google.com/apis/credentials)
2. Create project (e.g. `outreach-factory`)
3. Enable Gmail API
4. Configure OAuth consent screen (External, add your sender email as test user)
5. Create OAuth client ID → Desktop app → download JSON
6. Save the JSON to the path in `email_send.gmail_credentials_path` (default: `~/.outreach-factory/credentials/gmail_credentials.json`)
7. Run `python ~/.claude/skills/send-outreach/scripts/run.py auth` — opens browser consent. Refresh token is written to `email_send.gmail_token_path`.

If you see "blocked by your administrator" on a Google Workspace account, that route is gated; fall back to a personal Gmail or use SMTP with an app password (not currently supported, file an issue).

### Sender identity considerations (informational)

Choice of sending address affects deliverability + trust:
- **University / corporate** — best deliverability for cold opens, BUT many institutions' AUPs prohibit "commercial purposes" / "personal financial gain" / "solicitations." Enforcement is complaint-driven and rare for 1:1 personalized outreach, but the risk is account loss if a recipient reports.
- **Personal `@gmail.com`** — fully compliant, slight loss of trust premium.
- **Custom domain** — most defensible long-term, requires warmup (2-3 weeks via Smartlead/Instantly).

---

## Pipeline

```
Phase 0: Reconcile state (first run only)
         python run.py reconcile         → flip stale sent:false on already-sent emails

Phase 1: Send queued emails
         python run.py send              → preview table → confirm → Gmail API send → writeback

Phase 2: Send LinkedIn connection requests
         Read {email_send.linkedin_manifest_path} (emitted by Phase 1)
         For each entry with linkedin_state == "not_invited":
           call mcp__linkedin__connect_with_person (no note, free-tier constraint)
           update touch frontmatter: linkedin_state: invited, linkedin_invited_at: today
           tick "LinkedIn sent" outcome checkbox

Phase 3 (separate run, days later): Check for accepted invites
         /send-outreach --li-check
           For each linkedin_state == "invited":
             check if accepted (via get_inbox or profile-connection-degree)
             if accepted → mcp__linkedin__send_message with the queued DM
             → flip linkedin_state: dm_sent, tick "LinkedIn DM sent"
```

---

## Step-by-step (Phase 1 + 2 default flow)

### 1. Scan + preview

```bash
python ~/.claude/skills/send-outreach/scripts/run.py send --dry-run
```

This prints a categorized table:
- **EMAILS READY** — touches with valid recipient + parseable subject/body
- **LINKEDIN-ONLY READY** — touches with no email but LinkedIn URL
- **SKIPPED: no email** — touches whose person note has no email (often `status: closed`)
- **SKIPPED: unparseable** — touches with structural issues; list `issues` per row

Walk the list with the user. Common questions:
- "Are the `# guess-unverified` emails okay to send?" → Yes; ~70% land for `first@domain` at <50-person companies. Bounces are expected and informative.
- "Should I skip person X?" → Use `--only` to send a single one, or temporarily flip `sent: true` in their touch note.

### 2. Send emails

```bash
python ~/.claude/skills/send-outreach/scripts/run.py send
```

After preview, the script asks `Continue? [y/N]`. On `y`:
- Sends each email via Gmail API (synchronous, one at a time, ~1-2s each)
- On success: writes back `sent: true` + `sent_at: YYYY-MM-DD` to the touch note,
  ticks `- [x] Email sent` in the Outcome section, updates Person note
  (`status: queued → contacted`, `first_touch`, `last_touch`)
- On failure: prints the error but continues with the rest
- Writes `{email_send.linkedin_manifest_path}` with all LinkedIn touches that still need handling

The email From header uses `{email_send.sender_name}` if set, otherwise falls back to `{founder.name}` from config.

### 3. Handle LinkedIn invites (in-session, via MCP)

After the Python script exits, **you** (Claude) read the manifest:

```bash
cat {email_send.linkedin_manifest_path}
```

For each entry where `current_li_state == "not_invited"`:

1. **Send connection request** via `mcp__linkedin__connect_with_person`:
   - Use the `linkedin_url` from the manifest
   - **No note** on the invite (free-tier LinkedIn limits personalized invites to 5/month;
     skip the note to avoid hitting the cap)
   - The full DM text stays in the manifest for Phase 3
2. **Update touch note frontmatter** (use Edit on the `note_path` from the manifest):
   - Add: `linkedin_state: invited`
   - Add: `linkedin_invited_at: <today>`
3. **Tick the outcome checkbox**: change `- [ ] LinkedIn sent` to `- [x] LinkedIn sent`
4. **Append a `cost_incurred` ledger event** (ADR-0008 transitional emit until
   Pillar C lands `li_invite_intent` / `li_invite_confirmed`):

   ```bash
   python -m orchestrator.ledger append '{
     "type": "cost_incurred",
     "source": "linkedin",
     "units": 1,
     "amount_usd": 0.0,
     "model_or_endpoint": "connect_with_person",
     "person_id": "<person.id from the touch note frontmatter>"
   }'
   ```

   The policy engine's `linkedin-weekly-invite-cap` rule (in `cooldowns.yml`)
   reads these events to enforce the 100/week soft limit. **If you skip step 4,
   the cap under-reports and silently allows over-quota sends** — exactly the
   failure mode the rule exists to prevent. There is no programmatic
   enforcement of this step until Pillar C wires the two-phase events; until
   then, the discipline is on you. Treat step 4 as inseparable from step 1:
   do them together per invite or not at all.

Report a summary line per person: `✓ invited First Last  (linkedin.com/in/handle)`.

If MCP returns an error (already connected, profile not found, daily limit hit):
print the error inline, mark `linkedin_state: invite_failed` with reason, do NOT
tick the checkbox, and do NOT append the cost_incurred event (the cap counts
successful invites, not attempts). Move on.

---

## Phase 3: --li-check (run separately, ~2-7 days after invites)

When the user runs `/send-outreach --li-check`:

1. Scan vault for touches where `linkedin_state: invited` (use `mcp__obsidian__obsidian_complex_search` or grep)
2. For each, check acceptance — use whichever MCP path is cheapest:
   - `mcp__linkedin__get_inbox` + check if a conversation exists with this person (they accepted = inbox conversation auto-created)
   - OR `mcp__linkedin__get_person_profile` and check connection degree (1st-degree = accepted)
3. For accepted contacts: send the queued DM via `mcp__linkedin__send_message`
   - DM text is in `{email_send.linkedin_manifest_path}` keyed by `note_path`, OR
     re-parse it fresh from the touch note's `## LinkedIn DM` fenced block
4. Update frontmatter: `linkedin_state: dm_sent`, `linkedin_dm_sent_at: <today>`
5. Tick `- [x] LinkedIn DM sent` (separate from the invite checkbox)

---

## Frontmatter contract

The skill assumes this shape on touch notes (created by `/draft-outreach`):

```yaml
---
type: touch
date: YYYY-MM-DD
channel: email | linkedin | linkedin-and-email
person: "[[Name]]"
sent: false              # → true after email sent
sent_at:                 # → YYYY-MM-DD set on send
linkedin_state:          # → not_invited|invited|connected|dm_sent|invite_failed (managed by skill)
linkedin_invited_at:     # → YYYY-MM-DD set on invite
linkedin_dm_sent_at:     # → YYYY-MM-DD set on DM send
---
```

Body must contain (when channel includes email/linkedin):

- `**Subject:** \`<subject>\`` line followed by fenced code block under any `## Email` heading
- Fenced code block under any `## LinkedIn DM` heading
- An `## Outcome` checklist with `- [ ] Email sent` / `- [ ] LinkedIn sent` / `- [ ] LinkedIn DM sent`

If the contract drifts (`/draft-outreach` updated), update the parsers in `scripts/vault.py`.

---

## Anti-patterns

- ❌ **Don't auto-send without preview** — always run `--dry-run` first OR look at the preview table before confirming `y`. Unverified emails bounce and damage sender reputation.
- ❌ **Don't add a custom note on LinkedIn invites under free tier** — you only get 5 personalized invites per month; the script + this skill assume no-note invites.
- ❌ **Don't re-send to someone whose touch is already `sent: true`** — the parser filters them out, but if reconcile didn't run first you might accidentally double-send. Always reconcile on first use.
- ❌ **Don't change `sent_at` on a touch you didn't send** — it's the audit trail.
- ❌ **Don't bulk-send more than ~30 emails in one run** — Gmail throttles, and conversion is what matters not throughput. Personalization-led volume is the wedge.

---

## Cost / external dependencies

| Component | Free tier? | Notes |
|---|---|---|
| Gmail API | Yes | 1 billion quota units/day; sends are 100 units. Effectively unlimited at this volume |
| LinkedIn MCP | Yes (account-bound) | Free LinkedIn = no personalized invite notes; ~`{email_send.linkedin_weekly_invite_limit}` invites/week soft limit |
| OAuth setup | Yes | One-time, ~5 min |

---

## Pipeline position

```
/find-leads → /research-prospect → /draft-outreach → /humanizer → /send-outreach
                                                                  ^^^^^^^^^^^^^^
```

Updates the suite's "Don't auto-send" rule to: **send is batch-confirmed human in the loop**.

---

## Cost-ledger discipline (LinkedIn invites)

The LinkedIn `linkedin-weekly-invite-cap` policy rule (Pillar A, ADR-0008)
enforces the 100/week soft cap that LinkedIn uses to throttle / suspend
personal accounts. The rule reads `cost_incurred` events from the ledger;
if those events are missing, the cap under-reports and silently allows
over-quota sends — losing the LinkedIn channel for the whole pipeline.

Until Pillar C lands `li_invite_intent` / `li_invite_confirmed` two-phase
events, the emit is operator-mediated (you, Claude). Phase 2 step 4 above
is the load-bearing instruction. See `docs/adr/0008-linkedin-weekly-invite-
cap.md` for the full transitional contract.

## See also

- `/draft-outreach` — upstream: drafts the touch notes this skill ships
- `/research-prospect` — upstream: produces the dossier `/draft-outreach` consumes
- `/humanizer` — sibling: standalone AI-tell detector
- `docs/ARCHITECTURE.md` (in outreach-factory repo) — factory pipeline + state machine
- `docs/BILLING.md` (in outreach-factory repo) — subscription vs API billing matrix
- `docs/adr/0008-linkedin-weekly-invite-cap.md` — Pillar A policy rule + transitional emit contract
