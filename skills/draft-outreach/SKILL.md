---
description: Register-aware outreach drafter. Generates scaffolds, assembles ONE plain prose draft, then hands it to the humanizer in a FRESH context window (a fresh-context subagent or the /humanizer skill) with a single reference example of a good human-written touch in this register, and takes the humanizer's output verbatim. The humanizer runs inline / in a subagent, so it is subscription-billed via the Claude Code session, NOT API-billed. `--manual` flag: scaffolds-only, user writes the prose for 100% voice fidelity (recommended for tier-S high-stakes sends). Handles 5 distinct registers (cold-pitch / congrats / re-engagement / reply / public-comment), each with channel default, word ceiling, and anti-tell checklist tailored to register.
---

# /draft-outreach - register-aware outreach drafter

> _Build a high-signal outreach message by routing on **register** (cold-pitch / congrats / re-engagement / reply / public-comment) and **channel** (email / LinkedIn DM / LinkedIn comment / Twitter DM). The LLM produces structured scaffolds and assembles a plain draft; the humanizer rewrites that draft in a fresh context window anchored to ONE reference example; a final anti-tell checklist runs before send._

---

## ⚙️ Pre-flight - load user config

**Before doing anything else, read the user's config:**

```bash
cat ~/.outreach-factory/config.yml
```

This file contains the user's company, founder identity, vault paths, an optional voice reference example path, and ICP pointers. Throughout this skill, wherever you see `{config.X}` placeholders (e.g. `{company.name}`, `{founder.short_name}`, `{voice.reference_example_path}`), mentally substitute the loaded config value.

**If `~/.outreach-factory/config.yml` does not exist**: abort and tell the user to copy `config-template/config.example.yml` from the outreach-factory repo to `~/.outreach-factory/config.yml` and fill in their values.

---

## Usage

```bash
/draft-outreach <prospect> --register <cold-pitch|congrats|re-engagement|reply|public-comment> [--manual]

# Examples (default: assemble a plain draft, then humanize in a fresh context)
/draft-outreach https://linkedin.com/in/example --register congrats
/draft-outreach "Some Founder" SomeCompany --register cold-pitch
/draft-outreach "{vault.people_dir}/{vault.active_subdir}/Some Person.md" --register congrats
/draft-outreach "{vault.lead_lists_dir}/2026-05-12-list.md" --register cold-pitch --bulk
/draft-outreach reply --inbound-message "..." --thread "..."

# Manual mode (scaffolds-only; user writes prose; 100% voice fidelity)
/draft-outreach "Some Founder" SomeCompany --register cold-pitch --manual

# Demo mode (zero-setup; bundled fake prospect; no config/research/MCP)
/draft-outreach --demo
```

Register is the primary routing parameter. Channel default is derived from register but overridable with `--channel <email|linkedin-dm|linkedin-comment|twitter-dm>`.

**Default behavior**: the skill auto-assembles a plain prose draft from scaffold options (Phase 3.5), then hands that draft to the humanizer in a fresh context window with one register-matched reference example (Phase 4) and takes the humanizer's output verbatim. Zero user-time-per-email; the humanizer runs inline / in a subagent, so it is subscription-billed.

**`--manual` flag** (opt-out): skip the auto-assembly + humanizer pass, exit after Phase 3 scaffolds, hand off to the user to write the prose. Use this when 100% voice fidelity matters (tier-S high-stakes sends, or any time the recipient knows the user personally and would notice the gap).

---

## Demo mode (`--demo`)

`/draft-outreach --demo` is a zero-setup showcase: it drafts a real cold email for a bundled fake prospect with no config, no `/research-prospect` run, no MCP servers, and no Gmail. Use it to see the pipeline produce live prose in about two minutes.

When `--demo` is set:

1. Skip the Pre-flight config load and Phases 0 and 1. Read the bundled prospect note at `examples/demo/vault/Riley Okafor.md` (it carries a pre-filled dossier with hooks). The demo sender identity (Devon / Carillon / devon@carillon.example) is stated in `examples/demo/README.md`; use it for the `{founder.*}` and `{company.*}` placeholders.
2. Run Phase 3 (scaffold) and Phase 3.5 (assemble a plain draft) normally, using the note's hooks.
3. Phase 4: hand the assembled draft to the humanizer in a fresh context window, anchored to the bundled cold-pitch reference example. The prose is generated live (subscription-billed), so it will differ from the committed `examples/demo/sample-draft.md` each run.
4. Run Phase 5's humanizer anti-tell checklist on the result and report it.
5. Print the draft. Do NOT save a Touch note, do NOT write to any vault, and do NOT chain to `/send-outreach`. Nothing is sent.

The non-Claude-Code equivalent is `bin/outreach-factory demo`, which prints the same stages from the committed sample files (no LLM, so its final draft is the canned `sample-draft.md`). See `examples/demo/README.md`.

---

## Why this exists

LLM-generated prose has structural tells (em-dash overuse, rule-of-three, marketing-copy intros, manufactured enthusiasm) that survive any number of after-the-fact edits. The fix is not better humanizing of prose the drafting LLM already wrote in its own register. The fix is to **assemble only the content (scaffolds), then have a humanizer rewrite it in a separate, clean context** where it is not anchored to the drafting LLM's neutral-conversational defaults.

The LLM is good at:
- Surfacing specific public facts (recent posts, M&A news, named features, verbatim quotes)
- Structural scaffolding (subject options, hook options, ask options)
- Anti-tell pattern detection (em-dash density, AI vocabulary, manufactured superlatives)
- Channel + register fit

The LLM is bad at (and should not ship as final prose):
- Final outreach prose written in its own neutral-conversational register that human readers feel as artificial
- Vulnerability signals (LLMs position the sender as competent, not stuck)

So: **LLM produces *scaffolds*, assembles a plain draft, then the humanizer rewrites in a fresh context anchored to ONE good human example.**

---

## Pipeline (6 phases; `--manual` skips 3.5 and changes 4)

```
Phase 0:    Identity + register resolution
Phase 1:    Run /research-prospect (full mode - default tier S)
Phase 2:    Read user voice fingerprint (last 5 substantive-reply Touch notes)
Phase 3:    Generate scaffold menu (NOT prose)
Phase 3.5:  [skipped if --manual] LLM assembles ONE plain prose draft from scaffold options
Phase 4:    Default: hand the draft + ONE reference example to the humanizer in a fresh context; take its output verbatim. --manual: hand off to user.
Phase 5:    Humanizer anti-tell checklist on the prose. Flag + stop on failures.
Phase 6:    Save Touch note + (optionally) chain to /send-outreach
```

---

## Phase 0 - Identity + register resolution

Resolve the input (URL / name+company / file path) to `{person, company, vault_paths}`. Confirm register from `--register` flag OR infer from context:

- Recent public news + no prior contact → likely `congrats`
- Prospect in `{vault.queue_subdir}/`, no prior touch → likely `cold-pitch`
- Prospect in `{vault.active_subdir}/` with prior outbound but no reply for ≥30 days → likely `re-engagement`
- Prospect just replied to a prior touch → `reply`
- Public LinkedIn post / Twitter thread the user wants to engage → `public-comment`

If ambiguous, ASK the user before continuing.

---

## Phase 1 - Run `/research-prospect`

Default tier S. The skill chain is:

1. `/research-prospect <prospect>` runs the full LinkedIn + X/Twitter + blog + GitHub + company + news + YC scrape
2. Dossier is written to the Person note + (if `--call-prep`) a separate brief
3. Critical: the dossier ends with 3-5 candidate intro hooks - verifiable specific findings (verbatim quotes, dated events, named features, specific posts)

**If full research yields ≤2 extractable hooks**: downgrade to A. **If 0 hooks**: drop to C, do not draft. A non-send is better than a generic send.

**Critical**: if research surfaces a context-killing fact (acquisition, role change, company shutdown), STOP and surface to user. Do not proceed to drafting on stale context.

---

## Phase 2 - Read user voice fingerprint

Before generating scaffolds, sample 5 Touch notes from `{vault.path}/{vault.conversations_dir}/` where:
- `direction: outbound`
- `sent: true`
- `substantive: true` (got a real reply) - OR if none yet, `direction: outbound + sent: true + register match`

Extract the user's actual phrasal patterns:
- Opening conventions (`Hey {Name}` vs `Hi {Name}`)
- Question framings (`I wonder how`, `I was wondering`, `Curious how`)
- Vulnerability signals (`honestly been a challenge`, `still figuring out`, `mostly trying to learn`)
- Sign-off conventions (plain `- {founder.short_name}` vs full footer with school + email)
- Punctuation patterns (exclamation marks where, hyphen-vs-comma)

The voice-fingerprint is REFERENCE for scaffolding - it tells the LLM what phrasings the user naturally produces, so the scaffold options use user-shaped framings (not generic LLM phrasings).

---

## Phase 3 - Generate scaffold menu

The LLM produces a **menu of options**, never full prose. Structure:

```markdown
### Channel + length
- Recommended channel: {register default} (override if research suggests differently)
- Word ceiling: {per register table}
- Subject required: {yes/no based on channel}

### Subject scaffolds (if email)
- S1: ...
- S2: ...
- S3: ...

### Hook scaffolds (1 per option; each cites a specific finding)
- H1: [finding type: e.g. "their own quote 'left LinkedIn to chase a crazy idea'"] - full quote verbatim
- H2: [finding type: e.g. "M&A news 2026-03-31"] - date + parties
- H3: [finding type: e.g. "recent technical post Apr 2026"] - title + 1-line summary

### Context scaffolds (what the user is building - pick if register includes self-context)
- C1: plain version - "{company.wedge_plain}"
- C2: analogy version - "{company.wedge_analogy}"
- C3: failure-mode framed - "{company.wedge_failure_mode}"

### Ask scaffolds (one specific ask)
- A1: ...
- A2: ...
- A3: ...
- A0 (optional): "no ask" variant - for pure congrats / pure-relationship registers

### Sign-off (1, channel-appropriate)
- {`- {founder.short_name}` for LinkedIn DM; full footer ({founder.footer_email}) for email}
```

**Do NOT produce full prose in Phase 3.** Phase 3 outputs the menu of options only. Phase 3.5 is where assembly happens (default), or the skill exits here for the user to write (`--manual`).

---

## Phase 3.5 - Assemble (default; skipped if `--manual`)

Skip this phase entirely if `--manual` is set.

Otherwise: select ONE option per scaffold dimension (S + H + C + A + sign-off), assemble into a coherent draft per the register's word ceiling and channel. The draft should:
- Use the verbatim verifiable hook from the H option (not paraphrase the prospect's words)
- State the user's company context plainly from the C option (substituting the right wedge variant from config)
- Pose the ask from the A option as a single direct question
- Include opener + signoff appropriate to the register and channel
- Match the register's word ceiling (cold-pitch 75-200, congrats 35-50, re-engagement 50-75)

The output here is a "plain, content-correct draft" - do NOT try to mimic the user's voice in this phase. That's Phase 4's job. Generate a clean draft and pass it forward.

---

## Phase 4 - Humanize

**Default:** hand the assembled draft to the humanizer in a **fresh context window** and take its output verbatim. The humanizer runs inside your skill execution (a fresh-context subagent or the `/humanizer` skill), so the rewrite is part of the parent Claude Code session and is **subscription-billed, NOT API-billed**. There is no Anthropic API call and no voice corpus.

**`--manual` mode:** the user picks scaffold elements + types the actual prose. The skill EXITS at this point and waits for the user's draft.

### How to run the humanizer (default mode)

The whole point is a CLEAN context: the humanizer must rewrite the draft without being anchored to the neutral-conversational defaults the drafting LLM already used in Phases 3 and 3.5. So do NOT rewrite the draft inline in the same train of thought that produced it. Instead, hand it off to a fresh context.

**Step 1 - pick the fresh-context vehicle.** Either is fine:
- Spawn a fresh-context subagent (an Agent-tool task) whose entire job is to humanize the one draft you hand it, OR
- Invoke the `/humanizer` skill on the assembled draft.

When you spawn the subagent, run it on the configured cheap model: pass `model: {config.models.humanizer}` (default `haiku`) on the Agent call. The de-AI rewrite is a focused, mechanical pass and does not need a frontier model (the cost posture lives in the `models:` config block; bump to `sonnet` if a pass reads thin).

**Step 2 - give the humanizer exactly two inputs:**
1. **(a) The assembled draft** from Phase 3.5 (verbatim).
2. **(b) ONE reference example** of a good, human-written touch in this register. Pull it from `{voice.reference_example_path}` (defaults to `skills/draft-outreach/reference-examples.md`); select the single example whose label matches the current register (cold-pitch / congrats / re-engagement / reply / public-comment). If the user has their own curated example for this register, prefer that one.

Hand off with an instruction like:

```
Rewrite the draft below so it reads like a real person wrote it, in the same
voice and rhythm as the reference example. Preserve every fact, name, date, and
specific claim from the draft. Match the reference example's cadence, opener
style, vulnerability, and sign-off. Do NOT add facts that are not in the draft.
Output ONLY the rewritten message, no preamble, no quotation marks, no em dashes.

--- REFERENCE EXAMPLE ({register}, human-written) ---
[the single register-matched example from reference-examples.md]

--- DRAFT TO REWRITE ---
[the Phase 3.5 assembled draft]
```

**Step 3 - take the humanizer's output verbatim.** Do NOT re-edit it in your own voice; that re-injects the drafting LLM's register on top of the humanized prose. The humanizer's output is the candidate prose that goes to Phase 5 (anti-tell checklist) and then to the Touch note in Phase 6.

### Why a fresh context

When the same context that assembled the draft also "rewrites" it, the rewrite stays anchored to the draft's existing phrasing and the model's default register; the tells survive. A fresh context, anchored only to one strong human example plus the bare content, produces prose that reads human. And because the humanizer runs inside the Claude Code session (subagent or skill), it is subscription-billed; there is no API call.

---

## Phase 5 - Humanizer anti-tell checklist

Run the register-specific anti-tell checklist on the prose. Report green/yellow/red on each check with a 1-line justification. **Do not silently rewrite.** If a check fails, flag it and quote the offending phrase - the user decides whether to fix (or to re-run Phase 4's humanizer with a stronger anchor).

### Universal anti-tells (all registers)

| # | Check | Pattern |
|---|---|---|
| 1 | Em-dashes inside sentences | `-` between clauses (humans: 1/500 words; AI: 1/50-80) |
| 2 | Rule-of-three lists | `X, Y, and Z` adjective/noun triplets |
| 3 | AI vocabulary | `delve`, `intricate`, `underscore`, `palpable`, `leverage`, `at the intersection of`, `pivotal`, `unprecedented` |
| 4 | "Impressed" / forced enthusiasm | `I was impressed by`, `incredible journey`, `inspiring story`, `amazing arc` |
| 5 | Marketing-copy intros | Quoting prospect's own homepage tagline |
| 6 | Vague hedges | `I'd love to pick your brain`, `would love to learn from your insights` |
| 7 | Manufactured superlatives | `most X this week/month`, `one of the most thoughtful` |
| 8 | Filler phrases | `at the end of the day`, `in today's landscape`, `going forward` |
| 9 | Open-loop teases without payload | `there's something interesting I've been wondering about` (without saying what) |
| 10 | Negative parallelisms | `not just X, but Y`, `not only A but also B` |
| 11 | Lexical AI-tells | `basically`, `literally`, `actually-as-filler`, `approximately`, `pretty-as-hedge`, `kind of`, `sort of`, `honestly`, `essentially`, `fundamentally`, `really-as-intensifier`, `just-as-softener`, `directly adjacent`, `notoriously` |

### Register-specific anti-tells

**cold-pitch**:
- Generic Q1 - must be vertical-specific (from `{icp.failure_mode_library_path}` if configured)
- Triple-naming the prospect's arc (subject + DM + email body)

**congrats**:
- "Watching from afar" / "following your journey from afar" / "inspiring trajectory"
- No exclamation marks (this register *requires* them on the congrats line)
- Length over 50 words (signals AI; humans congratulate briefly)
- Pitches embedded inside congrats (poisons the register's intent)

**re-engagement**:
- `Just bumping this to the top of your inbox` / `Following up on my previous email` / `Hope you're well`
- Quoting prior email verbatim (defensive)
- Apologizing for the prior touch

**reply**:
- `Thanks for getting back to me!` opener - recipient just sent the message; obvious "I read it" wastes line 1
- Restating their question before answering - pattern signals AI

**public-comment**:
- Over 25 words (LinkedIn comments are short by convention)
- Self-promoting in the comment body
- "Congrats {name and rush}!" name-stacking + repeat tag (signals batch)

### Register-positive signals (encourage these)

- Vulnerability / honesty: `honestly been a challenge`, `still figuring out`, `not sure if this holds up`, `early on this`. These are the LOAD-BEARING signals that make outreach read human. LLMs do not volunteer them.
- Specific verifiable hook on a public dated event
- Single clear ask (not two layered asks)
- Question-mark intimacy (a real question, not a rhetorical pose)
- Conversational close ("If you've got the time, would help a lot. If not, no stress.") over formal close ("Looking forward to hearing your thoughts.")

---

## Phase 6 - Save + send mechanics

**Step 1 - Save the Touch note + stamp frontmatter.** Save the final prose into the Touch note's draft section (markdown fence block under `## Email (ready to send)` or `## LinkedIn DM (ready to send)`). Set frontmatter:
- `sent: false`
- `humanizer_pass: complete` (after Phase 5)
- `voice_rules_check: passed` (only if all checks green/yellow - if any red, set `voice_rules_check: failed` + leave `sent: false`)
- `research_tier`, `research_depth`, `opener_variant`, `voice_version` per Touch template
- `pipeline_stage: ready` ONLY when `voice_rules_check: passed`. If any anti-tell check is red, set `pipeline_stage: drafted` (NOT `ready`) + leave `sent: false`, and surface the offending phrase to the user.

**Step 2 - Send mechanics.** Then offer send mechanics via AskUserQuestion:
1. Send via Gmail API + writeback (chains to `/send-outreach`) - if `{email_send.gmail_api}` is true
2. Send via LinkedIn MCP - if `{email_send.linkedin_mcp}` is true
3. User sends manually, skill writes back

Never auto-send without explicit user confirmation.

---

## Register table (channel + length defaults)

| Register | Channel default | Word ceiling | Subject? | Sign-off | Notes |
|---|---|---|---|---|---|
| `cold-pitch` | email | 75-200 | yes | full footer | Tier S full research; vertical-specific Q1 mandatory |
| `congrats` | LinkedIn DM | 35-50 | no | `- {founder.short_name}` | Exclamation marks OK/expected; single ask max; can be no-ask |
| `re-engagement` | email | 50-75 | yes | full footer | Reference prior touch honestly (don't fake forgetting) |
| `reply` | same channel as inbound | match inbound | varies | varies | Mirror their register |
| `public-comment` | LinkedIn comment | 15-25 | no | none | Visible to their network; no asks |

If the channel-default doesn't fit (e.g., prospect publishes a personal Gmail as their "reach me" channel), override via `--channel` and document why in the Touch note's "Why this channel" section.

---

## Follow-up sequences (re-engagement touches 2 and 3)

A follow-up is just the `re-engagement` register at a specific step in a cadence.
The factory's cadence engine (`orchestrator/followup.py`) decides WHO is due for
WHICH follow-up touch and WHEN, by reading the ledger; `/dispatch-outreach`
routes a due prospect here with the step number. You do NOT decide timing or
eligibility; you draft the touch the engine asked for.

```bash
/draft-outreach "{vault.active_subdir}/Some Person.md" --register re-engagement --followup-step 1
```

`--followup-step N` selects the variant (1 = touch 2, 2 = touch 3). If the flag
is absent, infer the step from the prospect's `followup_step:` frontmatter (the
denormalized count of follow-ups already sent) plus one.

- **Touch 2 (follow-up 1) - a short bump, new angle.** 40-60 words. Reference the
  prior unanswered touch honestly in one clause (do NOT restate the whole pitch,
  do NOT fake forgetting, do NOT apologize for the first email). Lead with a NEW,
  specific reason to reply: a fresh hook, a sharper one-line framing of the
  wedge, or a smaller ask than the first. The body is fixed; only the first
  sentence varies per prospect (per the outreach-draft-style rule).
- **Touch 3 (follow-up 2) - a brief breakup.** 25-40 words. Give permission to
  close the loop ("if this isn't a fit or the timing's off, no worries, I'll
  leave it here"). One sentence of why-it-could-still-matter, then the close.
  Breakups get replies precisely because they ask for nothing.

Everything else is unchanged: the humanizer runs in a fresh context anchored to
the `re-engagement` reference example, the Phase 5 anti-tell checklist runs, and
NO em dashes. The re-engagement anti-tells above still apply verbatim (`Just
bumping this to the top of your inbox`, `Following up on my previous email`,
`Hope you're well`, quoting the prior email, apologizing).

Save the Touch note with `pipeline_stage: followup_<N>_drafted` (NOT `ready`):
`/dispatch-outreach` and the operator handle the manual review gate from there.

---

## Channel fallback rules

- **LinkedIn invite blocked** (`connect_unavailable`, "Follow" default profile) → fallback order: (1) email if address known + verified, (2) Twitter DM if both follow each other, (3) public-comment if they have a recent relevant post, (4) hold + look for a warm intro path
- **Email bounced** → if verifier says `invalid` + no alt, route to LinkedIn DM if available, else hold
- **Email is `catch_all`** → tier S/A allow with warning; tier B skip
- **Prospect has explicit `prefers_<channel>` flag** in their Person frontmatter → honor it

---

## Bulk mode

```bash
/draft-outreach "{vault.lead_lists_dir}/2026-05-12-list.md" --register cold-pitch --bulk
```

Process each NEW + RE-ENGAGE row sequentially. For bulk:
- Auto-tag channel based on each prospect's available signals (email present → email; only LinkedIn → DM)
- Skip the channel-confirmation prompt; honor research-derived channel
- Print 1-line scaffold summary per prospect, then assemble a plain draft per prospect (Phase 3.5)
- Humanize each draft in a fresh context (Phase 4), anchored to the register-matched reference example
- After all prose is humanized, run the Phase 5 anti-tell checklist on the batch; surface any failures by-name
- Save all Touch notes with `sent: false`; chain to `/send-outreach` for the final send

The bulk mode does NOT skip Phase 2 (voice fingerprint), Phase 4 (humanize), or Phase 5 (anti-tell checklist) - those are non-negotiable.

---

## Quality bar / refusal conditions

**Refuse and abort with explanation if:**
- Phase 1 research returns context-killing fact (acquisition, role change, prospect death, company shutdown) - surface to user, don't draft on stale context
- Phase 1 research yields zero extractable hooks - drop to C, surface to user
- User attempts to skip the Phase 4 humanizer or Phase 5 anti-tell checklist - block the send; surface refusal
- User's prose contains ≥3 universal anti-tells (red checks) - flag explicitly + offer a re-humanize loop (re-run Phase 4 with a stronger reference anchor)
- `~/.outreach-factory/config.yml` is missing - abort and tell user to create it

**Quality signals (good run):**
- Channel choice grounded in research
- ≥1 specific verifiable hook citing dated public artifact
- Single clear ask per register
- Word count within register ceiling
- Anti-tell checklist all green
- Vulnerability signal present (the load-bearing register-positive)

**Anti-patterns:**
- Generating full prose in any phase before Phase 3.5 - that's a workflow break, restart at Phase 3
- Humanizing in the SAME context that assembled the draft - defeats the point; the tells survive. Always use a fresh context.
- Quoting marketing copy from the prospect's own homepage as the personalization hook
- Mass-applying same hook across multiple prospects in bulk mode
- Skipping the voice-fingerprint phase for "speed"

---

## See also

- `/research-prospect` - upstream: produces the dossier this skill consumes
- `/send-outreach` - downstream: actually sends the email / LinkedIn DM after this skill writes the Touch note
- `/humanizer` - the humanizer invoked in Phase 4 (fresh-context rewrite) and used as reference for the Phase 5 checklist
- `skills/draft-outreach/reference-examples.md` - the default per-register reference examples the humanizer anchors to
- `docs/ARCHITECTURE.md` - factory pipeline + state machine
- `docs/BILLING.md` - subscription vs API billing matrix

---

## Don't

- ❌ Don't generate full prose in Phase 3 - Phase 3.5 is where assembly happens
- ❌ Don't humanize the draft in the same context that assembled it - use a fresh-context subagent or the `/humanizer` skill, or the tells survive
- ❌ For tier-S high-stakes prospects, prefer `--manual` mode. Default auto-prose is fine for bulk and tier-B, suboptimal where the recipient knows the user personally and would notice
- ❌ Don't edit the humanizer's output before Phase 5 - that re-injects the drafting LLM's voice on top of the humanized prose
- ❌ Don't run the Phase 5 checklist and silently rewrite - flag failures, surface to user
- ❌ Don't auto-send without confirmation
- ❌ Don't bulk-process without Phase 2 (voice fingerprint), Phase 4 (humanize), or Phase 5 (anti-tell checklist)
- ❌ Don't ignore a context-killing research finding - surface immediately
- ❌ Don't quote marketing copy from the prospect's own homepage as the personalization hook
- ❌ Don't use em-dashes inside sentences - use hyphens with spaces, commas, or colons
- ❌ Don't strip exclamation marks from a `congrats` register - they're register-required
- ❌ Don't make an Anthropic API call for the rewrite - the humanizer runs inline / in a subagent and is subscription-billed; there is no voice corpus and no API call

---

## Origin

Built 2026-05-12 in the aiyara workspace after a personalization audit identified that 8/9 tier-B sends were template-filled. Iterated through several drafting designs:

- **v1 (2026-05-12)**: scaffolds-only, user writes prose. 100% fidelity but high user-time cost.
- **v2 (2026-05-13)**: added a RAG-based voice translator (Anthropic SDK direct call). Acceptable fidelity at zero user-time, but the SDK call was API-billed, bypassing the Claude Max subscription.
- **v3 (2026-05-14)**: split into local retrieval + inline rewrite (subscription-billed). Same fidelity, $0 API spend, but carried a heavy embedding/voice-corpus substrate.
- **v4 (current)**: dropped the voice corpus entirely. The draft is assembled plain, then handed to the humanizer in a FRESH context window anchored to ONE strong human reference example. The fresh context is what actually removes the tells; a curated multi-email corpus was not needed. Runs inline / in a subagent, so it stays subscription-billed.

Migrated from `~/.claude/skills/draft-outreach/` to this repo on 2026-05-14 as part of the outreach-factory open-source split. Aiyara-specific knowledge (company name, founder identity, vault paths, reference-example path, wedge framings) now lives in `~/.outreach-factory/config.yml` rather than baked into this file.
