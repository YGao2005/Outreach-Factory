---
description: Conversational zero-to-first-send onboarding. Inspects reality (config, vault, Gmail token, MCPs, DNS) and ADAPTS - a warm setup gets a 2-minute fast path, a greenfield setup gets the full path - then orchestrates the existing CLI (config / init / status / doctor), dns_check, the warming ramp, and the opt-in Cloudflare auto-set to drive an operator from nothing to a first test send. Reuses the wizard and config bridge, never reimplements them.
---

# /onboard - conversational zero-to-first-send onboarding

> _Take an operator from "I just cloned the repo" to "my first test send round-tripped and I can see my daily headroom." The agent's superpower is that it INSPECTS REALITY (digs DNS, reads config, detects the Gmail token and connected MCPs, parses `doctor --json`) and ADAPTS, rather than reading instructions at the operator. Detect state, then branch: skip every phase that is already done, run only what is missing._

This skill is an ORCHESTRATOR. It does not reimplement anything. It calls the existing `outreach-factory` CLI (`config` / `init` / `status` / `doctor`) and the existing Python helpers (`orchestrator.dns_check`, `orchestrator.warming`, `orchestrator.dns_autoset`). The init wizard and the config-to-TenantConfig bridge already exist inside the CLI; this skill drives them and holds the conversation.

---

## What this does and does not do (read this first)

Onboarding attacks **activation** - the first gate every new operator hits, where a clone sits unused because OAuth, vault layout, and DNS are each a small wall. This skill knocks those walls down in one conversation.

It honestly does NOT:

- **Fix email sourcing.** Finding real, verified prospect addresses is still the fragile part of the whole product (it leans on MCP servers and scraping, both of which break). Onboarding gets you sending; it does not get you a reliable list.
- **Prove the product works for a second human.** There is no case study yet. Onboarding makes the machine run for you; it does not promise outcomes.
- **Build reputation or deliver "instant warmth."** Warming is weeks of real, engaged sending. The framework owns the ramp schedule and the health gate (it stops escalating when the bounce rate climbs); it does not manufacture reputation. A warmup network is a recommend-only step in v1, not an integration.
- **Auto-edit your DNS by default.** The default deliverability path is guide-and-verify: the skill prints the exact records and tells you where to paste them. Cloudflare auto-set is strictly OPT-IN and only fires if you hand it a `CLOUDFLARE_API_TOKEN`. DKIM is never auto-set; it is always minted in your email provider's console.

Keep this framing in front of the operator. Overpromising warming or sourcing is the fastest way to lose their trust.

---

## How to run it

```
/onboard            # detect current state, then run only the missing phases
/onboard --fast     # bias toward the fast path: assume a warm/configured setup, verify, stop early
/onboard --dry-run  # greenfield walkthrough: narrate every phase without real OAuth/send (uses `init --dry-run`)
```

There are no required arguments. The skill figures out where the operator is from reality, not from flags.

---

## The six phases

```
Phase 0:  Detect + adapt        build the done-vs-needed checklist; decide which phases to run
Phase 1:  Identity + config     `outreach-factory config`, then converse to fill config.yml + .env
Phase 2:  Sending channel       Gmail OAuth (exact console steps + detect creds + `init`) OR Resend
Phase 3:  Deliverability        dns_check report -> exact records -> paste-or-opt-in-Cloudflare -> re-check
Phase 4:  Warmth                health-gated ramp (warming module) + honest multi-week timeline + recommend a warmup network
Phase 5:  Prove the loop        `outreach-factory init` (vault scaffold + self-test send) then `outreach-factory status`
```

Each phase has a concrete GATE (a checkable condition). A phase is SKIPPED when its gate is already satisfied. The fast path is just "most gates already pass."

---

## Phase 0 - Detect + adapt

**This is the phase that makes the skill smart. Do it before saying anything prescriptive.** Inspect the real state of the machine, build a checklist, and only then decide what to run.

Honor the config override the whole factory honors: if `OUTREACH_FACTORY_CONFIG` is set in the environment, that path is the config; otherwise it is `~/.outreach-factory/config.yml`.

Run these probes (each is read-only):

1. **Config present?**
   ```bash
   # honor the override the CLI honors
   test -n "$OUTREACH_FACTORY_CONFIG" && CFG="$OUTREACH_FACTORY_CONFIG" || CFG="$HOME/.outreach-factory/config.yml"
   test -f "$CFG" && echo "config: present at $CFG" || echo "config: MISSING"
   ```
   If present, read it. Note `founder.email`, `vault.path`, `email_send.gmail_api`, `email_send.resend_api_key`, `email_send.daily_send_cap`, and the `warming:` block.

2. **Doctor's machine-readable view.** This is the single richest probe; it already runs most of the checks this phase needs. Note: the `outreach-factory doctor` subcommand prints the human-readable report (no flags), so for the JSON view call the script directly - it is the same checker:
   ```bash
   python3 scripts/doctor.py --json          # run from the factory.home repo root
   ```
   Parse the JSON. It carries `required[]` and `optional[]` checks, each with `name`, `status` (`ok` / `warn` / `fail`), `message`, and `hint`. Pull out:
   - `config`, `factory.home`, `vault` (required) - tells you if the install + vault are sane.
   - `gmail_creds` (optional) - tells you whether Gmail send is wired and whether the OAuth credentials file is on disk.
   - `deliverability` (optional) - this check ALREADY runs `dns_check.inspect_domain` on the domain of `founder.email` and reports SPF / DKIM / DMARC. Read its `message` and `hint` instead of re-deriving from scratch.
   - `mcp.obsidian`, `mcp.linkedin`, `mcp.ScraplingServer` (OPTIONAL feature MCPs, now in `optional[]`) - which MCPs are configured. They power discovery and the LinkedIn channel; the core config -> draft -> send-via-Gmail loop needs none of them, so a missing one is a WARN, not a blocker. (Reachability is only confirmed on first real use; "configured" is what doctor can see.)
   - `migrations` - whether Pillar B migrations are pending.

3. **Vault scaffolded?** `doctor`'s `vault` check covers existence + required subdirs. If it is `fail`, the vault is greenfield (the Phase 5 `init` step scaffolds it).

4. **Gmail token vs credentials.** `gmail_creds` tells you about the credentials JSON (the OAuth client file you download from Google). The TOKEN (the post-consent refresh token) lives at `email_send.gmail_token_path` or the default `~/.outreach-factory/credentials/gmail_token.json`:
   ```bash
   ls -1 "$HOME/.outreach-factory/credentials/" 2>/dev/null || echo "no credentials dir yet"
   ```
   Credentials present + token present + an `init_wizard_completed` event in the ledger means Phase 2 and Phase 5 are likely already done.

5. **Already onboarded?** The init wizard is idempotent and records an `init_wizard_completed` event. The cleanest signal is to just look at status:
   ```bash
   ./bin/outreach-factory status
   ```
   If status shows prior sends (a non-empty ledger), the loop has run before; lead with the fast path.

6. **DNS, directly.** Even though doctor's `deliverability` check runs `dns_check`, you can dig the sending domain yourself for a fuller picture (doctor probes a focused selector set). Use the helper directly so the report matches Phase 3:
   ```bash
   python3 -c "
   from orchestrator import dns_check
   import sys
   domain = dns_check.domain_of_email('FOUNDER_EMAIL_HERE')  # from config founder.email
   if not domain or domain in ('example.com','yourcompany.com'):
       print('deliverability: no real sending domain configured yet'); sys.exit(0)
   r = dns_check.inspect_domain(domain)   # live resolver; defaults to dnspython
   print('domain:', domain)
   print('summary:', r.summary)
   "
   ```
   (Substitute the real `founder.email`. If there is no network, note that and defer the live check to Phase 3.)

**Build the checklist.** From the probes, mark each phase DONE or NEEDED:

| Phase | Gate (satisfied = DONE = skip) |
|---|---|
| 1 Identity + config | config file exists AND `founder.email`, `company.name`, `vault.path`, `email_send.daily_send_cap` are real (not placeholders like `you@example.com` / `YourCompany` / `/path/to/your/vault`) |
| 2 Sending channel | a send channel is wired: `gmail_creds` is `ok` AND a Gmail token file exists, OR `RESEND_API_KEY` / `email_send.resend_api_key` is set |
| 3 Deliverability | doctor `deliverability` is `ok` (SPF + DKIM + DMARC all present and not weak) on the real sending domain |
| 4 Warmth | `warming.enabled: true` in config with a sane schedule, OR the operator confirms the domain is already warmed |
| 5 Prove the loop | the ledger has an `init_wizard_completed` event (status shows prior activity) |

**Then branch.** Tell the operator plainly what is already done and what is left, and run ONLY the needed phases in order. A fully warm setup reaches "you are already onboarded; here is your status" in about two minutes. A greenfield setup walks all five.

---

## Phase 1 - Identity + config

Gate: a real, filled config. Skip if Phase 0 marked it done.

If the config file does not exist, create it from the templates (this is the CLI's job, do not hand-copy):

```bash
./bin/outreach-factory config
```

That copies `config-template/config.example.yml` -> `~/.outreach-factory/config.yml` and `config-template/.env.example` -> `~/.outreach-factory/.env`, leaving any existing file untouched. Then **converse** to fill it. Ask for, and write into `config.yml`:

- `factory.home`: the absolute path where they cloned this repo (run `pwd` from the repo root to get it). The template default `~/code/outreach-factory` is only a guess, and doctor BLOCKS on `factory.home` until it points at the real clone (the skills read their reference files from it). Set this first; you can detect it yourself since you are running inside the repo.
- `company.name`, `company.one_liner`, and the three wedge flavors (`wedge_plain` / `wedge_analogy` / `wedge_failure_mode`). The operator usually has one of these in their head; offer to draft the other two from it.
- `founder.name`, `founder.short_name`, `founder.email` (this IS the sending address, so it drives the whole deliverability phase), `founder.footer_email`.
- The wedge / ICP: `icp.buyer_description` at minimum (a sentence on who the buyer is). Pointers like `icp.tier_playbook_path` are optional.
- `vault.path` (the markdown CRM root). If they do not have a vault yet, the Phase 5 `init` scaffolds the directory; just get a path from them.
- `email_send.daily_send_cap` (start conservative, ~25/day on a warmed mailbox).

For secrets, write into `~/.outreach-factory/.env` (NOT config.yml): `RESEND_API_KEY` if they pick Resend in Phase 2, `CLOUDFLARE_API_TOKEN` only if they opt into auto-set in Phase 3.

**Do not reimplement the config-to-TenantConfig bridge.** The CLI's `_tenant_config_from_user_config` already consumes this exact `config.yml` shape (company, factory.tenant_id, vault.path, email_send.gmail_token_path) and builds the `TenantConfig` the init wizard needs. Your job is only to fill the YAML correctly so that bridge succeeds in Phase 5. In particular `vault.path` must be set, or the bridge raises.

Gate check before leaving: re-run `python3 scripts/doctor.py --json` and confirm `config`, `factory.home`, and `vault` are no longer `fail` (vault may still be `fail` until Phase 5 scaffolds it - that is fine, note it and move on).

---

## Phase 2 - Sending channel

Gate: one send channel is wired (Gmail token on disk, or a Resend key set). Skip if Phase 0 marked it done.

Ask which channel. Two paths:

### Gmail OAuth (the common path)

The agent CANNOT click through Google's console, so give the operator the EXACT steps, then detect the result and run the wizard. Walk them through, in their own browser:

1. Go to the Google Cloud Console, create (or pick) a project.
2. Enable the **Gmail API** for that project (APIs & Services -> Library -> Gmail API -> Enable).
3. Configure the OAuth consent screen (External is fine for a personal sender; add your own address as a test user).
4. Create an **OAuth client ID** of type **Desktop app**. Download the resulting JSON.
5. Save that JSON to `~/.outreach-factory/credentials/gmail_credentials.json` (or wherever `email_send.gmail_credentials_path` points). Set `email_send.gmail_api: true` in config.

Then DETECT that the file landed:

```bash
ls -l "$HOME/.outreach-factory/credentials/gmail_credentials.json" 2>/dev/null \
  && echo "credentials detected" || echo "still missing - wait for the download"
```

Once the credentials file is present, the token round-trip (the actual OAuth consent + refresh-token exchange) is what `outreach-factory init` performs - it is one of the wizard's four steps (`gmail_oauth`). Do NOT build a separate OAuth flow here; the wizard owns the token exchange. The full `init` run happens in Phase 5 (it also scaffolds the vault and does the self-test send), so Phase 2's job is just to get the credentials JSON in place and `gmail_api: true` set. If you want to confirm the token exchange in isolation before Phase 5, you can run `./bin/outreach-factory init --dry-run` (fake Gmail seam, no real consent) to prove the wiring, then do the real `init` in Phase 5.

### Resend (alternative)

If the operator prefers Resend (transactional email, simpler than Gmail OAuth):

1. Get an API key from the Resend dashboard.
2. Write it into `~/.outreach-factory/.env` as `RESEND_API_KEY=...` (or set `email_send.resend_api_key` in config).
3. Note for Phase 3: Resend's SPF include is `amazonses.com` and DKIM is set by adding the domain in the Resend dashboard. The `dns_check` provider for a Resend sender is `"resend"`, which the helpers already know.

Gate check: a Gmail credentials file exists (token comes in Phase 5) OR a Resend key is set.

---

## Phase 3 - Deliverability

Gate: SPF + DKIM + DMARC all published and not weak on the real sending domain. Skip if Phase 0's doctor `deliverability` check was already `ok`.

This phase is "report concretely, then fix." Use `dns_check` directly (the same module doctor uses) so the report and the generated records cannot drift.

**Step 1 - report.** Inspect the sending domain (the domain of `founder.email`; for a Resend sender pass `provider="resend"`):

```bash
python3 -c "
from orchestrator import dns_check
domain = dns_check.domain_of_email('FOUNDER_EMAIL_HERE')
r = dns_check.inspect_domain(domain, provider='google', rua_email='FOUNDER_EMAIL_HERE')
for c in (r.spf, r.dmarc, r.dkim):
    state = 'present' if c.present else 'MISSING'
    if c.weak: state = 'weak'
    print(f'{c.kind.upper():6} {state:8} {c.detail}')
    if c.recommendation: print('       ->', c.recommendation)
"
```

Report each record as present / missing / weak in plain words. A weak DMARC (`p=none`) is "present but monitor-only"; say so.

**Step 2 - generate the exact records.** For anything missing, hand the operator the literal TXT values and where each goes:

```bash
python3 -c "
from orchestrator import dns_check
print('SPF   - add a TXT record at the apex (your domain):')
print('       ', dns_check.generate_spf_record('google'))     # 'resend' for a Resend sender
print('DMARC - add a TXT record at  _dmarc.<your-domain>:')
print('       ', dns_check.generate_dmarc_record('none', 'FOUNDER_EMAIL_HERE'))
"
```

Tell them exactly where to paste: the SPF value as a TXT record on the apex (the bare domain), the DMARC value as a TXT record on the `_dmarc.` subdomain. DMARC starts at `p=none` (monitor only); they ramp to `quarantine` then `reject` later, once SPF and DKIM are confirmed aligned.

**DKIM is provider-console, always.** Never generate or auto-set a DKIM value. For Google Workspace: Apps -> Google Workspace -> Gmail -> Authenticate email, then publish the TXT record Google gives you. For Resend: add the domain in the Resend dashboard and publish the records it generates. Say this plainly; DKIM is the one record you cannot hand them a value for.

**Step 3 (OPT-IN) - Cloudflare auto-set.** If, and only if, the operator's DNS is on Cloudflare AND they hand you a `CLOUDFLARE_API_TOKEN` (read it from the environment / their `.env`, never from `config.yml`), you can write the SPF + DMARC records for them via the `dns_autoset` helper. The record VALUES come from the same `dns_check` generators, so the auto-set path can never drift from the guide path. DKIM is still NOT auto-set.

```bash
python3 -c "
import os
from orchestrator import dns_autoset
token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
writer = dns_autoset.CloudflareDNSWriter(token)   # refuses loud on a blank token
res = writer.ensure_records('YOUR_DOMAIN', provider='google', rua_email='FOUNDER_EMAIL_HERE')
print('zone:', res.zone_id)
print('SPF  ', res.spf['action'], '->', res.spf['content'])
print('DMARC', res.dmarc['action'], '->', res.dmarc['content'])
for n in res.notes: print('note:', n)
"
```

`ensure_records` is idempotent (an equivalent record already present is a no-op, action `exists`) and refuses loud if the domain's zone is not on that Cloudflare account. If the operator does NOT provide a token, stay on the guide-and-verify default - that is the right default and works for every DNS provider.

**Step 4 - re-check propagation.** DNS takes time to propagate, so re-run the Step 1 inspect after a few minutes (or after they paste). A freshly written record may not be visible to the resolver yet; if it still reads missing, that is propagation lag, not a failure. Re-run until SPF + DMARC read present (DKIM follows once they finish the provider-console step).

Gate check: re-run `python3 scripts/doctor.py --json` and confirm `deliverability` is `ok` (or, honestly, "SPF + DMARC present, DKIM pending in the provider console" if they have not finished DKIM - note it, do not block the first test send on it).

---

## Phase 4 - Warmth

Gate: warming is configured (`warming.enabled: true` with a sane schedule), OR the operator confirms the sending domain is already warmed. Skip if Phase 0 marked it done.

Ask one question: **is this sending domain already warmed?** (Has it been sending real, engaged mail for weeks?)

- **If yes (warm):** no ramp needed. Leave `warming.enabled: false`; status will just show raw counts against the daily cap. Move on.
- **If no (fresh domain or mailbox):** set up the health-gated ramp and be HONEST about the timeline.

Set up the ramp by enabling the `warming:` block in config:

```yaml
warming:
  enabled: true
  start_date: "2026-06-02"   # the day warming begins (usually the day of the first send); blank = inferred from the earliest send_confirmed
  # weeks_to_full: 5          # optional; default is a 5-week 20/40/60/80/100% schedule
```

The `warming` module computes the per-week ceiling and the health gate; `outreach-factory status` surfaces it. You can preview today's ceiling so the operator sees what the ramp will say:

```bash
python3 -c "
from datetime import datetime, timezone
from orchestrator import warming
d = warming.compute_ramp(now=datetime.now(timezone.utc), start_date=None, daily_send_cap=25, events=[])
print(warming.status_line(d, total=warming.total_weeks(daily_send_cap=25)))
"
# e.g. -> warming ceiling  5/day  (week 1 of 5 ramp; health ok)
```

**Be honest about what warming is.** Tell the operator, in plain words:

- Warming is **weeks of time plus real engagement** (opens, replies, low complaints). It is not a setting you flip.
- The framework owns the **ramp schedule and the health gate** only: it starts low, climbs each week toward your daily cap, and HOLDS (stops escalating) if the trailing 7-day bounce rate climbs over 5%. A degrading mailbox is never asked to send more. That is a guardrail, not reputation-building.
- The framework does NOT build reputation for you. For that, **recommend a warmup network** (Mailwarm, Warmup Inbox, Instantly, and similar) that sends and engages real mail on your behalf. In v1 this is recommend-only; there is no integration. Hand them the names and let them choose.

Gate check: if they have a fresh domain, `warming.enabled: true` is set with a start_date (or blank, to infer). If warm, no change needed.

---

## Phase 5 - Prove the loop

Gate: an `init_wizard_completed` event exists (status shows prior activity). This is the payoff phase: scaffold the vault, do a real self-test send, then show the readiness report.

**Step 1 - run init.** This is the existing wizard, driven by the CLI. Do NOT reimplement it.

```bash
./bin/outreach-factory init
```

`init` builds the `TenantConfig` from `config.yml` via the CLI's bridge and runs the four-step wizard: `gmail_oauth` (the real token exchange, which is also where Gmail consent happens if it has not yet), `vault_setup` (creates the vault directory + runs migrations, idempotent), `first_prospect` (enrolls a placeholder), and `test_send` (sends a verification email to the operator's OWN address and reads it back - it never spams a prospect). It is idempotent: a re-run after success prints "Already onboarded" and does nothing.

If a step fails, the wizard raises with the failing step name in the message (for example `gmail_oauth` if consent did not complete, or `vault_setup` if the vault path is not writable). Read that step name, fix that one thing, and re-run `init`. Do not paper over it.

If the operator wants to confirm the whole wiring WITHOUT a real OAuth round-trip or a real send first, run the dry run, which uses a fake Gmail seam and throwaway directories:

```bash
./bin/outreach-factory init --dry-run
```

**Step 2 - show readiness.** Once the real `init` succeeds, run status for the readiness report:

```bash
./bin/outreach-factory status
```

Read it back to the operator in plain terms: how many emails went out today, the daily cap and remaining headroom, this week's warming ceiling (if warming is enabled), replies, bounces, blocked sends, and the pipeline counts. Frame it as: "You are cleared to send N/day this week, ramping to M over the next few weeks. Here is what is still optional (DKIM if you have not finished it, a warmup network, real prospect sourcing)."

Gate check: `status` shows the `init_wizard_completed` round-trip happened (a non-empty ledger with the test send). The operator has now proven the machine end to end.

---

## The greenfield walkthrough (what `--dry-run` must reach)

A `/onboard --dry-run` on a clean machine (no `config.yml`, no vault, no Gmail token) must walk the full detect-then-branch logic end to end and reach "init -> first test send" without real OAuth or a real send. The path:

1. **Phase 0** probes: `config: MISSING`, `python3 scripts/doctor.py --json` shows `config: fail`, no credentials dir, empty ledger. Checklist: ALL FIVE phases NEEDED. Branch to the full path.
2. **Phase 1**: `outreach-factory config` copies the templates; converse to fill `company` / `founder.email` / wedge / ICP / `vault.path` / `daily_send_cap`. Re-run `python3 scripts/doctor.py --json`: `config` now `ok`, `vault` still `fail` (greenfield, scaffolded in Phase 5).
3. **Phase 2**: operator picks Gmail; walk the Google Cloud Console steps; detect `gmail_credentials.json` lands; set `gmail_api: true`. (The token exchange is deferred to `init`.)
4. **Phase 3**: `dns_check.inspect_domain` on the sending domain reports SPF/DKIM/DMARC missing; generate the exact SPF + DMARC TXT values and where to paste them; DKIM routed to the provider console; Cloudflare auto-set offered only if a token is present; re-check after paste.
5. **Phase 4**: fresh domain, so enable `warming` with a 5-week ramp; preview today's ceiling via `warming.compute_ramp`; recommend a warmup network; state the honest multi-week timeline.
6. **Phase 5**: run `outreach-factory init --dry-run` (fake Gmail seam, throwaway dirs) to prove the wizard wiring end to end - `gmail_oauth -> vault_setup -> first_prospect -> test_send` all green - then `outreach-factory status`. In a real run, this is the real `init` and a real self-test send.

That sequence is the definition of a successful greenfield onboard: from nothing to a proven first test send, with every fix the operator needs surfaced concretely.

---

## Reuse, do not duplicate

This skill is glue. It MUST NOT reimplement:

- the init wizard (`run_init_wizard`) - call `outreach-factory init`.
- the config-to-TenantConfig bridge (`_tenant_config_from_user_config`) - call `outreach-factory init`, which uses it.
- template copying - call `outreach-factory config`.
- the preflight checks - call `python3 scripts/doctor.py --json` (the JSON view of the same checker `outreach-factory doctor` runs) and parse it.
- the ledger read for the readiness report - call `outreach-factory status`.
- DNS inspection + record generation - call `orchestrator.dns_check`.
- the warming ramp + health gate - call `orchestrator.warming`.
- Cloudflare writes - call `orchestrator.dns_autoset` (opt-in only).

If you find yourself writing OAuth code, ledger-walking code, or DNS-record-building code inline, stop: there is already a function for it.

---

## Don't

- Do not be prescriptive before Phase 0. Detect first, then branch. Reading instructions at an already-warm operator wastes their time and signals the skill is dumb.
- Do not run a phase whose gate already passes. Skipping done work IS the value.
- Do not auto-set DNS without an explicit `CLOUDFLARE_API_TOKEN` from the operator. Guide-and-verify is the default.
- Do not auto-set or generate a DKIM value, ever. DKIM is provider-console only.
- Do not overpromise warming. It is weeks of time plus engagement; the framework owns the ramp and the gate, not the reputation.
- Do not claim onboarding fixes email sourcing or proves product-market fit. It attacks activation only. Say so.
- Do not reimplement the wizard, the config bridge, doctor, dns_check, warming, or dns_autoset. Orchestrate them.
- Do not read `CLOUDFLARE_API_TOKEN` from `config.yml`. It belongs in `.env` / the environment.
- Do not block the first test send on a not-yet-propagated DKIM record. Note it as pending and let `init` prove the send path.

---

## See also

- `orchestrator/cli.py` - the `outreach-factory` CLI (`config` / `init` / `status` / `doctor` / `demo`); holds the config bridge `_tenant_config_from_user_config` and `cmd_status`.
- `orchestrator/multi_tenant/__init__.py` - `run_init_wizard` (the four-step wizard `init` drives).
- `orchestrator/dns_check.py` - SPF / DKIM / DMARC inspect + record generation.
- `orchestrator/dns_autoset.py` - the opt-in Cloudflare SPF + DMARC writer.
- `orchestrator/warming.py` - the health-gated warming ramp surfaced in `status`.
- `scripts/doctor.py` - the preflight checker; `python3 scripts/doctor.py --json` is the machine-readable view Phase 0 parses (`outreach-factory doctor` runs the same checks in human-readable form).
- `config-template/config.example.yml`, `config-template/.env.example` - what `outreach-factory config` copies.
- `/draft-outreach` - the next thing the operator runs once onboarded (write the first real touch).
