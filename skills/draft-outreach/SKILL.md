---
description: Register-aware outreach drafter. Generates scaffolds, assembles ONE prose draft, retrieves top-5 voice exemplars from the user's curated email corpus via local Python (voice_retrieve.py), then does the rewrite INLINE in the agent's own LLM call — subscription-billed, NOT API-billed. ~85% voice fidelity at zero user-time-per-email. `--manual` flag: scaffolds-only, user writes prose for 100% fidelity (recommended for tier-S high-stakes sends). Mandatory humanizer-checklist pass before send. Handles 5 distinct registers (cold-pitch / congrats / re-engagement / reply / public-comment), each with channel default, word ceiling, voice rules, and anti-tell checklist tailored to register.
---

# /draft-outreach — register-aware outreach drafter

> _Build a high-signal outreach message by routing on **register** (cold-pitch / congrats / re-engagement / reply / public-comment) and **channel** (email / LinkedIn DM / LinkedIn comment / Twitter DM). LLM produces structured scaffolds; user-corpus retrieval grounds the voice; LLM runs humanizer-check before send._

---

## ⚙️ Pre-flight — load user config

**Before doing anything else, read the user's config:**

```bash
cat ~/.outreach-factory/config.yml
```

This file contains the user's company, founder identity, vault paths, voice corpus paths, and ICP pointers. Throughout this skill, wherever you see `{config.X}` placeholders (e.g. `{company.name}`, `{founder.short_name}`, `{voice.corpus_dir}`), mentally substitute the loaded config value.

**If `~/.outreach-factory/config.yml` does not exist**: abort and tell the user to copy `config-template/config.example.yml` from the outreach-factory repo to `~/.outreach-factory/config.yml` and fill in their values.

---

## Usage

```bash
/draft-outreach <prospect> --register <cold-pitch|congrats|re-engagement|reply|public-comment> [--manual]

# Examples (default: auto-prose via voice translator)
/draft-outreach https://linkedin.com/in/example --register congrats
/draft-outreach "Some Founder" SomeCompany --register cold-pitch
/draft-outreach "{vault.people_dir}/{vault.active_subdir}/Some Person.md" --register congrats
/draft-outreach "{vault.lead_lists_dir}/2026-05-12-list.md" --register cold-pitch --bulk
/draft-outreach reply --inbound-message "..." --thread "..."

# Manual mode (scaffolds-only; user writes prose; 100% voice fidelity)
/draft-outreach "Some Founder" SomeCompany --register cold-pitch --manual

# Demo mode (zero-setup; bundled fake prospect; no config/research/MCP/corpus)
/draft-outreach --demo
```

Register is the primary routing parameter. Channel default is derived from register but overridable with `--channel <email|linkedin-dm|linkedin-comment|twitter-dm>`.

**Default behavior**: the skill auto-assembles a prose draft from scaffold options (Phase 3.5) and pipes through the voice retrieval + inline rewrite (Phase 4). ~85% user voice fidelity at zero user-time-per-email.

**`--manual` flag** (opt-out): skip the auto-assembly + voice rewrite, exit after Phase 3 scaffolds, hand off to user to write prose. Use this when 100% voice fidelity matters (tier-S high-stakes sends, or any time the recipient knows the user personally and would notice the ~15% gap).

---

## Demo mode (`--demo`)

`/draft-outreach --demo` is a zero-setup showcase: it drafts a real cold email for a bundled fake prospect with no config, no `/research-prospect` run, no MCP servers, no Gmail, and no voice-corpus build. Use it to see the pipeline produce live prose in about two minutes.

When `--demo` is set:

1. Skip the Pre-flight config load and Phases 0 and 1. Read the bundled prospect note at `examples/demo/vault/Riley Okafor.md` (it carries a pre-filled dossier with hooks) and the bundled voice corpus at `examples/demo/voice-corpus.md`. The demo sender identity (Devon / Carillon / devon@carillon.example) is stated in `examples/demo/README.md`; use it for the `{founder.*}` and `{company.*}` placeholders.
2. Run Phase 3 (scaffold) and Phase 3.5 (assemble) normally, using the note's hooks.
3. Phase 4: do the inline rewrite grounded by the cold-pitch exemplars read DIRECTLY from `voice-corpus.md`. Do NOT call `voice_corpus.py` or `voice_retrieve.py`, and do NOT load any embedding model: with a six-email demo corpus, retrieval ranking is meaningless, so hand the exemplars to the rewrite as-is. The prose is generated live in your own LLM call (subscription-billed), so it will differ from the committed `examples/demo/sample-draft.md` each run.
4. Run Phase 5's humanizer anti-tell checklist on the result and report it. Skip the hallucination-detection and voice-fidelity gates: they need a dossier path and the embedding substrate, neither of which the demo wires up.
5. Print the draft. Do NOT save a Touch note, do NOT write to any vault, and do NOT chain to `/send-outreach`. Nothing is sent.

The non-Claude-Code equivalent is `bin/outreach-factory demo`, which prints the same four stages from the committed sample files (no LLM, so its final draft is the canned `sample-draft.md`). See `examples/demo/README.md`.

---

## Why this exists

LLM-generated prose has structural tells (em-dash overuse, rule-of-three, marketing-copy intros, manufactured enthusiasm) that survive any number of after-the-fact edits. The fix is not better humanizing — it is **not generating the prose in the first place**.

The LLM is good at:
- Surfacing specific public facts (recent posts, M&A news, named features, verbatim quotes)
- Structural scaffolding (subject options, hook options, ask options)
- Anti-tell pattern detection (em-dash density, AI vocabulary, manufactured superlatives)
- Channel + register fit

The LLM is bad at (and should not produce):
- Final outreach prose (it defaults to neutral-conversational register that human readers feel as artificial)
- Vulnerability signals (LLMs position the sender as competent, not stuck)
- The user's exact phrasal patterns

So: **LLM produces *scaffolds*, retrieval grounds the *voice*, user reviews before send.**

---

## Pipeline (7 phases; `--manual` skips 3.5 and changes 4)

```
Phase 0:    Identity + register resolution
Phase 1:    Run /research-prospect (full mode — default tier S)
Phase 2:    Read user voice fingerprint (last 5 substantive-reply Touch notes)
Phase 3:    Generate scaffold menu (NOT prose)
Phase 3.5:  [skipped if --manual] LLM assembles ONE prose draft from scaffold options
Phase 4:    Default: voice retrieval + INLINE rewrite. --manual: hand off to user.
Phase 5:    Humanizer-checklist pass on the prose. Flag + stop on failures.
Phase 6:    Save Touch note + (optionally) chain to /send-outreach
```

---

## Phase 0 — Identity + register resolution

Resolve the input (URL / name+company / file path) to `{person, company, vault_paths}`. Confirm register from `--register` flag OR infer from context:

- Recent public news + no prior contact → likely `congrats`
- Prospect in `{vault.queue_subdir}/`, no prior touch → likely `cold-pitch`
- Prospect in `{vault.active_subdir}/` with prior outbound but no reply for ≥30 days → likely `re-engagement`
- Prospect just replied to a prior touch → `reply`
- Public LinkedIn post / Twitter thread the user wants to engage → `public-comment`

If ambiguous, ASK the user before continuing.

---

## Phase 1 — Run `/research-prospect`

Default tier S. The skill chain is:

1. `/research-prospect <prospect>` runs the full LinkedIn + X/Twitter + blog + GitHub + company + news + YC scrape
2. Dossier is written to the Person note + (if `--call-prep`) a separate brief
3. Critical: the dossier ends with 3-5 candidate intro hooks — verifiable specific findings (verbatim quotes, dated events, named features, specific posts)

**If full research yields ≤2 extractable hooks**: downgrade to A. **If 0 hooks**: drop to C, do not draft. A non-send is better than a generic send.

**Critical**: if research surfaces a context-killing fact (acquisition, role change, company shutdown), STOP and surface to user. Do not proceed to drafting on stale context.

---

## Phase 2 — Read user voice fingerprint

Before generating scaffolds, sample 5 Touch notes from `{vault.path}/{vault.conversations_dir}/` where:
- `direction: outbound`
- `sent: true`
- `substantive: true` (got a real reply) — OR if none yet, `direction: outbound + sent: true + register match`

Extract the user's actual phrasal patterns:
- Opening conventions (`Hey {Name}` vs `Hi {Name}`)
- Question framings (`I wonder how`, `I was wondering`, `Curious how`)
- Vulnerability signals (`honestly been a challenge`, `still figuring out`, `mostly trying to learn`)
- Sign-off conventions (plain `— {founder.short_name}` vs full footer with school + email)
- Punctuation patterns (exclamation marks where, em-dash usage if any, hyphen-vs-comma)

The voice-fingerprint is REFERENCE for scaffolding — it tells the LLM what phrasings the user naturally produces, so the scaffold options use user-shaped framings (not generic LLM phrasings).

---

## Phase 3 — Generate scaffold menu

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
- H1: [finding type: e.g. "their own quote 'left LinkedIn to chase a crazy idea'"] — full quote verbatim
- H2: [finding type: e.g. "M&A news 2026-03-31"] — date + parties
- H3: [finding type: e.g. "recent technical post Apr 2026"] — title + 1-line summary

### Context scaffolds (what the user is building — pick if register includes self-context)
- C1: plain version — "{company.wedge_plain}"
- C2: analogy version — "{company.wedge_analogy}"
- C3: failure-mode framed — "{company.wedge_failure_mode}"

### Ask scaffolds (one specific ask)
- A1: ...
- A2: ...
- A3: ...
- A0 (optional): "no ask" variant — for pure congrats / pure-relationship registers

### Sign-off (1, channel-appropriate)
- {`— {founder.short_name}` for LinkedIn DM; full footer ({founder.footer_email}) for email}
```

**Do NOT produce full prose in Phase 3.** Phase 3 outputs the menu of options only. Phase 3.5 is where assembly happens (default), or the skill exits here for the user to write (`--manual`).

---

## Phase 3.5 — Assemble (default; skipped if `--manual`)

Skip this phase entirely if `--manual` is set.

Otherwise: select ONE option per scaffold dimension (S + H + C + A + sign-off), assemble into a coherent draft per the register's word ceiling and channel. The draft should:
- Use the verbatim verifiable hook from the H option (not paraphrase the prospect's words)
- State the user's company context plainly from the C option (substituting the right wedge variant from config)
- Pose the ask from the A option as a single direct question
- Include opener + signoff appropriate to the register and channel
- Match the register's word ceiling (cold-pitch 75-200, congrats 35-50, re-engagement 50-75)

The output here is a "neutral LLM-flavored draft" — do NOT try to mimic the user's voice in this phase. That's Phase 4's job. Generate a clean, content-correct draft and pass it forward.

---

## Phase 4 — Prose generation

**Default (subscription-friendly):** Use `voice_retrieve.py` for local-only exemplar retrieval, then do the rewrite **INLINE in your own LLM call**. The rewrite is part of your skill execution → billed against the Claude Max subscription, NOT against API credits.

**`--manual` mode:** User picks scaffold elements + types the actual prose. The skill EXITS at this point and waits for the user's draft.

### Voice retrieval + inline rewrite (default mode)

**Step 1** — write the Phase 3.5 assembled draft to a temp file, then run the retrieval script. The framework ships TWO retrieval paths; pick based on `voice.use_embedding_primitive` in `~/.outreach-factory/config.yml`:

* **`voice.use_embedding_primitive: true`** (default at Pillar F Week 8+ per ADR-0039 §Existing-operator seed + ADR-0045 D232) — invoke the Pillar F Week 2 embedding-retrieval primitive (`orchestrator/voice_corpus.py`). Surfaces per-register / per-channel filtered exemplars with a deterministic-clock-controlled recency multiplier per ADR-0038 D179. The new primitive is the substrate for the per-register threshold loader (Week 4 per ADR-0041 D204), the hallucination-detection gate (Week 6 per ADR-0043), and the per-draft voice-fidelity scoring gate (Week 8 per ADR-0045 D230). **Default path at Week 8+.**
* **`voice.use_embedding_primitive: false`** — invoke the legacy heuristic at `orchestrator/voice_retrieve.py`. Operators with curated corpora not yet tagged with `register` + `channel` per ADR-0038 D178 opt OUT here. The Week 8 voice-fidelity gate (Phase 5 below) stays inactive on this path (the gate consumes the new primitive's substrate).

**Path A — new primitive (`voice.use_embedding_primitive: true` — default at Week 8+):**

```bash
{voice.python_bin} \
  {factory.home}/orchestrator/voice_corpus.py retrieve \
  --file /tmp/draft.txt \
  --k 5 \
  [--register {register-key}] \
  [--channel {channel-key}] \
  --json 2>/dev/null > /tmp/retrieve.json
```

The `--register` flag values are the five register keys per the table above (`cold-pitch` / `congrats` / `re-engagement` / `reply` / `public-comment`). The `--channel` flag values are the four channel keys per ADR-0014 D33 (`email` / `linkedin-dm` / `linkedin-comment` / `twitter-dm`). Pass the register + channel matching the current draft; the primitive filters the corpus before scoring.

**Path B — legacy heuristic (`voice.use_embedding_primitive: false` — explicit opt-out at Week 8+):**

```bash
{voice.python_bin} \
  {factory.home}/orchestrator/voice_retrieve.py \
  --file /tmp/draft.txt 2>/dev/null > /tmp/retrieve.json
```

Both scripts read `~/.outreach-factory/config.yml` themselves to find the corpus paths. You only need to invoke them with the draft file.

Output is a JSON object: `{"draft": ..., "exemplars": [top-5 emails ranked by cosine + recency bias], "hard_rules": [voice constraints]}` for Path B; or `{"ok": true, "k": 5, "register": ..., "channel": ..., "exemplars": [{id, date, subject, to, register, channel, score, is_substantive_reply, body}, ...], "embed_model": ...}` for Path A. Both shapes carry the `to` field; the Step 2 prompt's `to [...]` placeholder works against either path. Zero LLM cost in both paths — local sentence-transformers + cosine + index lookup.

> ⚠ **Deprecation note (Pillar F Week 8+):** `voice_retrieve.py` is preserved through Pillar F Week 12 exit gate per ADR-0038 §Existing-operator seed for backwards compatibility with corpora not yet tagged with `register` + `channel`. The Week 8 commit FLIPPED the framework default to Path A (per ADR-0039 §Existing-operator seed + ADR-0045 D232); operators with legacy corpora set `voice.use_embedding_primitive: false` explicitly to keep the legacy heuristic active. Deprecation timing for `voice_retrieve.py` is operator-deferred — the file ships through Week 12 + may surface a stderr deprecation notice on import IF operator transition demand materializes (TBD per the per-week reviewer's call).

**Step 2** — Read `/tmp/retrieve.json`. Build the voice-rewrite prompt yourself using this template:

```
You are rewriting an outreach draft to sound like {founder.short_name}'s actual voice.

Below are 5 of {founder.short_name}'s real past emails. Study them for voice. Pay special
attention to the most recent one — that's the current register.

--- Example 1 ({founder.short_name}'s actual email, YYYY-MM-DD, to [...]) ---
Subject: ...

[body]

[... 4 more exemplars, formatted same way ...]

--- DRAFT TO REWRITE ---
[draft content]

--- HARD RULES (do not violate) ---
1. [first hard rule from JSON]
2. [second hard rule from JSON]
[... all hard rules from JSON, numbered ...]

--- WHAT TO DO ---
Preserve all factual content, names, dates, and specific claims from the draft.
Match {founder.short_name}'s rhythm and word choice from the exemplars (especially the
most recent one). Output ONLY the rewritten email, no preamble, no explanation, no
quotation marks around the output.
```

**Step 3** — Produce the rewritten email AS YOUR OWN LLM OUTPUT. You ARE the rewriter — this isn't a tool call, it's part of your skill execution. Output goes to Phase 5 (humanizer-check) and then to the Touch note in Phase 6.

⚠ **Billing critical**: do NOT invoke any script named `voice_translate.py` — that name is reserved for the deprecated API-billed version. The correct script is either `voice_retrieve.py` (legacy heuristic) or `voice_corpus.py retrieve` (Pillar F Week 2 embedding-retrieval primitive). Both are subscription-friendly — local sentence-transformers + cosine + index lookup. See `docs/BILLING.md` in the outreach-factory repo.

### Why this split

The retrieval (sentence-transformers + cosine + index lookup) is deterministic and CPU-only. It belongs in Python. The rewrite is an LLM call. When the rewrite happens inside your skill execution, it's part of the parent Claude Code session and is subscription-billed.

---

## Phase 5 — Humanizer-checklist pass

Run the register-specific anti-tell checklist on the prose. Report green/yellow/red on each check with a 1-line justification. **Do not silently rewrite.** If a check fails, flag it and quote the offending phrase — the user decides whether to fix.

### Universal anti-tells (all registers)

| # | Check | Pattern |
|---|---|---|
| 1 | Em-dashes inside sentences | `—` between clauses (humans: 1/500 words; AI: 1/50-80) |
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
- Generic Q1 — must be vertical-specific (from `{icp.failure_mode_library_path}` if configured)
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
- `Thanks for getting back to me!` opener — recipient just sent the message; obvious "I read it" wastes line 1
- Restating their question before answering — pattern signals AI

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

### Hallucination-detection gate (Pillar F Week 6+ per ADR-0043 D217)

**After** the per-register anti-tell checklist completes, run the hallucination-detection gate against the prose + the research dossier. The gate refuses to advance the draft to `pipeline_stage: ready` when an uncited claim is detected.

Invoke the gate per the Week 6 primitive at `orchestrator/draft_quality.py`:

```bash
{voice.python_bin} \
  {factory.home}/orchestrator/draft_quality.py parse \
  --draft-path /tmp/draft.txt \
  --research-dossier-path <dossier-path> \
  --register {register-key} \
  --channel {channel-key} \
  --json 2>/dev/null > /tmp/draft_quality.json
```

The `<dossier-path>` is the Phase 1 `/research-prospect` output — either the Person note's body (when the dossier landed there) or the separate brief file (when `--call-prep` was set). Pass the SAME `--register` and `--channel` the draft was scaffolded against.

Read `/tmp/draft_quality.json`. The shape:

```json
{
  "state": "ready" | "refused",
  "register": "<register-key>",
  "channel": "<channel-key>",
  "draft_hash": "sha256:<hex>",
  "threshold": 0.70,
  "parsed_claims": [...],
  "uncited_claims": [{"claim_type": "...", "claim_text": "...", "citation_anchor": null}, ...]
}
```

**Gate verdict drives Phase 6's `pipeline_stage:` advancement:**

| `state` | Phase 6 action |
|---|---|
| `ready` (uncited empty) | Phase 6 proceeds; Touch note's `voice_rules_check: passed` continues; `pipeline_stage: ready` advances. |
| `refused` (uncited non-empty) | Phase 6 REFUSES to advance to `pipeline_stage: ready`. Set the Touch note's frontmatter: `pipeline_stage: drafted` (NOT `ready`) + `hallucination_check: failed` + drop the per-claim trace into the Touch note's body under a new `## Hallucination gate findings` section. |

**Operator remediation** (when `state == "refused"`):

The operator has two paths:

1. **Fix the draft** — add a dossier citation for each uncited claim (the dossier may need additional research, OR the draft's claim was speculative + should be removed).
2. **Stamp an override** — when the operator disagrees with the gate's verdict (a paraphrased citation the deterministic parser didn't match; a synonymous named entity), set `hallucination_check_override: true` + `hallucination_check_override_reason: "<rationale>"` on the Touch note's frontmatter. The override stamps the operator's deliberate decision; the operator MUST also manually advance `pipeline_stage: ready` after stamping (the override does NOT auto-clear the gate's refusal at Week 6).

**Per-claim trace formatting** for the Touch note's `## Hallucination gate findings` section:

```markdown
## Hallucination gate findings

The draft's claim parser surfaced N uncited claims per ADR-0038 D180
Layer 3 + ADR-0043 D214. Either add a dossier citation for each
claim OR stamp `hallucination_check_override: true` on this Touch
note's frontmatter (with a `hallucination_check_override_reason`).

- **[you_phrase]** "you posted about Phantom Project last week" — no matching anchor in dossier
- **[date_reference]** "April 2026" — date not referenced in dossier
- **[named_entity]** "Acme Corp" — entity not found in dossier

Per-register threshold: 0.70 (cold-pitch).
Source: `~/.outreach-factory/voice_thresholds.yml`.
```

> ⚠ **Ledger emit (Pillar G observability per ADR-0043 D216 + D219):** The gate's CLI also accepts `--apply` to append a `hallucination_detected` event to the ledger (emit-only-on-uncited per D219; accept-case never emits). For routine `/draft-outreach` invocations, OMIT `--apply` (dry-run); operators auditing per-Person refusal rates via Pillar G dashboards may enable `--apply` in their per-tenant config IF demand materializes (operator-deferred to Pillar I).

> ⚠ **Privacy invariant per I8 + ADR-0043 D216:** the gate's CLI output carries the per-claim `claim_text` (the draft's literal claim span — operator-visible diagnostic). The ledger event carries `draft_hash` (sha256:<hex>) NOT the raw draft body; the per-claim trace lands in the event with `claim_text` (the draft's literal span, NOT the dossier content). The dossier content NEVER lands in the event.

### Voice-fidelity gate (Pillar F Week 8+ per ADR-0045 D230 + D233)

**After** the hallucination-detection gate accepts the draft (`state: ready`), run the per-register voice-fidelity gate. The gate compares the draft's voice-fidelity score (mean of top-K voice-corpus exemplars' cosine × recency scores) against the per-register threshold from `~/.outreach-factory/voice_thresholds.yml` (Week 4 per ADR-0041 D204).

The gate runs ONLY when `voice.use_embedding_primitive: true` (the Week 8+ default per ADR-0045 D232). Operators on the legacy heuristic path (`voice.use_embedding_primitive: false`) skip this gate entirely — the gate consumes the new primitive's substrate.

Invoke the gate per the Week 8 primitive at `orchestrator/draft_quality.py`:

```bash
{voice.python_bin} \
  {factory.home}/orchestrator/draft_quality.py score \
  --draft-path /tmp/draft.txt \
  --register {register-key} \
  --channel {channel-key} \
  --json 2>/dev/null > /tmp/voice_fidelity.json
```

Pass the SAME `--register` and `--channel` the draft was scaffolded against (per ADR-0045 D231's channel/register-mismatch refuse-loud at the event factory).

Read `/tmp/voice_fidelity.json`. The shape:

```json
{
  "state": "ready" | "refused",
  "register": "<register-key>",
  "channel": "<channel-key>",
  "draft_hash": "sha256:<hex>",
  "voice_fidelity_score": 0.78,
  "voice_fidelity_threshold": 0.70,
  "meets_threshold": true,
  "exemplar_ids": ["ex-001", "ex-002", ...],
  "k": 5,
  "payload": { /* draft_quality_scored event shape per ADR-0045 D231 */ }
}
```

**Gate verdict drives Phase 6's `pipeline_stage:` advancement:**

| `state` | Phase 6 action |
|---|---|
| `ready` (score >= threshold) | Phase 6 proceeds; Touch note's `voice_fidelity_check: passed` + per-register score stamp; `pipeline_stage: ready` advances (assuming hallucination-detection ALSO passed). |
| `refused` (score < threshold) | Phase 6 REFUSES to advance to `pipeline_stage: ready`. Set the Touch note's frontmatter: `pipeline_stage: drafted` (NOT `ready`) + `voice_fidelity_check: failed` + `voice_fidelity_score: <score>` + `voice_fidelity_threshold: <threshold>`. |

**Operator remediation** (when `state == "refused"`):

The operator has two paths:

1. **Re-rewrite the draft** — loop back to Phase 4's voice-anchoring rewrite (the LLM call) with a stronger prompt that emphasizes the operator's voice exemplars. The Phase 5 humanizer-checklist + the hallucination-detection gate stay; the rewrite operates on the same scaffold from Phase 3.5.
2. **Tune the per-register threshold** — when the operator disagrees with the gate's verdict (the score is materially close to the threshold + the corpus is small or the operator's voice is varied), lower the per-register threshold in `~/.outreach-factory/voice_thresholds.yml`. This is operator-deliberate calibration; the Week 4 defaults are calibrated against the reference operator's curated corpus + may not generalize.

> ⚠ **Ledger emit (Pillar G observability per ADR-0045 D231 — emit-always posture):** The gate's CLI accepts `--apply` to append a `draft_quality_scored` event to the ledger. Unlike the Week 6 `hallucination_detected` event (emit-only-on-uncited per ADR-0043 D219), the Week 8 event is **emit-always** — BOTH `ready` and `refused` states emit when `--apply` is set. Pillar G dashboards consume the per-register score distribution rendering against the per-event stream. For routine `/draft-outreach` invocations, OMIT `--apply` (dry-run); operators auditing per-Person per-register baselines may enable `--apply` in their per-tenant config (operator-deferred to Pillar I).

> ⚠ **Privacy invariant per I8 + ADR-0045 D231:** the gate's CLI output carries the `voice_fidelity_score` + `voice_fidelity_threshold` + `meets_threshold` + `exemplar_ids` fields (operator-visible diagnostics). The ledger event carries `draft_hash` (sha256:<hex>) NOT the raw draft body; the `exemplar_ids` list carries per-exemplar IDs ONLY — per-exemplar bodies are NOT in the event payload. Operators look up bodies via the corpus directly.

---

## Phase 6 — Save + send mechanics + Layer 4 post-engine guard

**Step 1 — Invoke the Layer 4 emit-guard per ADR-0047 D248.** AFTER the Phase 5 humanizer-checklist pass + the Phase 5 hallucination-detection gate + the Phase 5 voice-fidelity gate, invoke the Week 10 composite per-draft entry point:

```bash
python orchestrator/draft_quality.py emit-ready \
    --draft-path /tmp/draft.txt \
    --research-dossier-path <dossier-path> \
    --register {register-key} --channel {channel-key} \
    [--hallucination-check-override --hallucination-check-override-reason "<rationale>"] \
    [--voice-fidelity-check-override --voice-fidelity-check-override-reason "<rationale>"] \
    [--skip-fidelity-check] \
    --json 2>/dev/null > /tmp/layer_4_check.json
```

The CLI runs BOTH per-Layer 2 gates (Layer 3 parser via `score_draft`; Layer 2 voice-fidelity scorer via `compute_draft_fidelity_score`) + invokes the Layer 4 emit-guard (`build_draft_ready_payload`) + emits the per-Layer events at their existing cardinality (per ADR-0043 D219 + ADR-0045 D231) AND the NEW `draft_ready` event (per ADR-0047 D246's emit-only-on-both-pass posture). When `voice.use_embedding_primitive: false` is set (legacy path per ADR-0045 §Migration/rollout Path B), pass `--skip-fidelity-check` to surface the `voice_fidelity_check: skipped` path.

The JSON output's shape:

```json
{
  "layer_4_check": "passed" | "refused",
  "register": "cold-pitch",
  "channel": "email",
  "draft_hash": "sha256:<hex>",
  "hallucination_state": "ready" | "refused",
  "fidelity_state": "ready" | "refused" | "skipped",
  "voice_fidelity_score": 0.78 | null,
  "voice_fidelity_threshold": 0.70 | null,
  "parsed_claims_count": 2,
  "uncited_claims_count": 0,
  "refused_dimensions": ["hallucination", "fidelity"],  // present when refused
  "uncited_claims": [ /* per-claim trace */ ],          // present when hallucination refused
  "draft_ready_payload": { /* event per ADR-0047 D246 */ }  // present when passed
}
```

**Gate verdict drives Phase 6's `pipeline_stage:` advancement:**

| `layer_4_check` | Phase 6 action |
|---|---|
| `passed` | Phase 6 proceeds; stamp `layer_4_check: passed` (or `layer_4_check: passed_via_override` when one or both per-dimension overrides fired); `pipeline_stage: ready` advances (assuming the upstream gates ALSO stamped passed). |
| `refused` | Phase 6 REFUSES to advance to `pipeline_stage: ready`. Set the Touch note's frontmatter: `pipeline_stage: drafted` (NOT `ready`) + `layer_4_check: failed` + leave `sent: false`. Surface the per-dimension trace to the operator + offer the per-dimension override paths. |

**Operator remediation** (when `layer_4_check == "refused"`):

The operator has two paths PER DIMENSION:

1. **Remediate the draft** — loop back to Phase 4's voice-anchoring rewrite (for fidelity refusals) OR add the missing dossier citation (for hallucination refusals). Re-run the CLI.
2. **Stamp the per-dimension override** — stamp `hallucination_check_override: true` + `hallucination_check_override_reason: "<rationale>"` on the Touch note's frontmatter AND re-run the CLI with `--hallucination-check-override --hallucination-check-override-reason "<rationale>"`. Similarly for `voice_fidelity_check_override: true` + `voice_fidelity_check_override_reason: "<rationale>"`.

The override surfaces in the emitted `draft_ready` event's `hallucination_check: passed_via_override` (or `voice_fidelity_check: passed_via_override`) marker; Pillar I per-tenant audit-tooling reads the override stream for per-operator override-rate signals.

> ⚠ **Ledger emit (Pillar G observability per ADR-0047 D246 — emit-only-on-both-pass posture):** The CLI accepts `--apply` to append the per-Layer events + the `draft_ready` event to the ledger. The per-Layer events emit at their existing cardinality (hallucination_detected per ADR-0043 D219 emit-only-on-uncited; draft_quality_scored per ADR-0045 D231 emit-always unless `--skip-fidelity-check`); the `draft_ready` event emits ONLY when both per-Layer 2 verdicts pass (natively OR via the per-dimension override). For routine `/draft-outreach` invocations, include `--apply` — the per-event audit trail IS the Week 12 Layer 5 reconcile Pass C heal-pass substrate.

> ⚠ **Privacy invariant per I8 + ADR-0047 D246:** the `draft_ready` event carries `draft_hash` (sha256:<hex>) NOT the raw draft body; the per-claim trace + per-exemplar bodies are NOT in the payload (only counts + per-Layer pass/refuse markers + per-dimension override reasons surface). Operators inspect per-claim diagnostics via the upstream `hallucination_detected` event + per-exemplar IDs via the upstream `draft_quality_scored` event.

**Step 2 — Save the Touch note + stamp frontmatter.** Save the final prose into the Touch note's draft section (markdown fence block under `## Email (ready to send)` or `## LinkedIn DM (ready to send)`). Set frontmatter:
- `sent: false`
- `humanizer_pass: complete` (after Phase 5)
- `voice_rules_check: passed` (only if all checks green/yellow — if any red, set `voice_rules_check: failed` + leave `sent: false`)
- `hallucination_check: passed` (only if Phase 5's gate returned `state: ready` per ADR-0043 D217 — if `state: refused`, set `hallucination_check: failed` + `pipeline_stage: drafted` (NOT `ready`) + leave `sent: false`; the operator must either remediate the draft OR stamp `hallucination_check_override: true` + `hallucination_check_override_reason: "<rationale>"`)
- `voice_fidelity_check: passed` ONLY when the Pillar F Week 8 voice-fidelity gate returned `state: ready` per ADR-0045 D230 — if `state: refused`, set `voice_fidelity_check: failed` + `voice_fidelity_score: <score>` + `voice_fidelity_threshold: <threshold>` + `pipeline_stage: drafted` (NOT `ready`) + leave `sent: false`. (When `voice.use_embedding_primitive: false`, the gate is inactive — set `voice_fidelity_check: skipped` + omit the score/threshold stamps. AND pass `--skip-fidelity-check` to the Step 1 CLI invocation.)
- `voice_fidelity_check_override: false` (operator-stamped to `true` only when the operator deliberately bypasses the voice-fidelity gate's refusal) + `voice_fidelity_check_override_reason: "<rationale>"` when override is `true`. Per ADR-0047 D247 the override is operator-deliberate per-draft + surfaces in the per-event audit trail.
- `layer_4_check: passed` ONLY when the Layer 4 emit-guard CLI returned `layer_4_check: passed` per ADR-0047 D245 — set `layer_4_check: passed_via_override` when one or both per-dimension overrides fired; set `layer_4_check: failed` + `pipeline_stage: drafted` (NOT `ready`) + leave `sent: false` when Layer 4 refused. (When `--skip-fidelity-check` is set, the Layer 4 verdict considers only the hallucination dimension; the fidelity dimension is `voice_fidelity_check: skipped`.)
- `research_tier`, `research_depth`, `opener_variant`, `voice_version` per Touch template
- `pipeline_stage: ready` ONLY when ALL of `voice_rules_check: passed` AND `hallucination_check: passed` (OR `hallucination_check_override: true`) AND `voice_fidelity_check: passed` (OR `voice_fidelity_check: skipped` on the legacy path OR `voice_fidelity_check_override: true`) AND `layer_4_check: passed` (OR `layer_4_check: passed_via_override`).

> ⚠ **Don't bypass the Layer 4 `emit-ready` CLI when stamping `pipeline_stage: ready`.** The Pillar F Week 12 Layer 5 backstop (per ADR-0049 D262 + ADR-0038 D180) refuses Pass C heal-to-ready when no `draft_ready` event exists in the ledger; bypassed stamps surface as `reconcile_drift` findings with `reason: ready_without_draft_ready_event` + the Person stays at the prior `pipeline_stage` until the operator re-emits the `draft_ready` event via `python orchestrator/draft_quality.py emit-ready --apply ...`. The Layer 4 CLI invocation in Step 1 is the load-bearing surface that produces the `draft_ready` event; skipping Step 1 (e.g., scripted automation that stamps frontmatter directly) trips Layer 5 at the next reconcile run.

**Step 3 — Send mechanics.** Then offer send mechanics via AskUserQuestion:
1. Send via Gmail API + writeback (chains to `/send-outreach`) — if `{email_send.gmail_api}` is true
2. Send via LinkedIn MCP — if `{email_send.linkedin_mcp}` is true
3. User sends manually, skill writes back

Never auto-send without explicit user confirmation.

---

## Register table (channel + length defaults)

| Register | Channel default | Word ceiling | Subject? | Sign-off | Notes |
|---|---|---|---|---|---|
| `cold-pitch` | email | 75-200 | yes | full footer | Tier S full research; vertical-specific Q1 mandatory |
| `congrats` | LinkedIn DM | 35-50 | no | `— {founder.short_name}` | Exclamation marks OK/expected; single ask max; can be no-ask |
| `re-engagement` | email | 50-75 | yes | full footer | Reference prior touch honestly (don't fake forgetting) |
| `reply` | same channel as inbound | match inbound | varies | varies | Mirror their register |
| `public-comment` | LinkedIn comment | 15-25 | no | none | Visible to their network; no asks |

If the channel-default doesn't fit (e.g., prospect publishes a personal Gmail as their "reach me" channel), override via `--channel` and document why in the Touch note's "Why this channel" section.

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
- Print 1-line scaffold summary per prospect, then PAUSE for user to write all the prose in a single sitting (batched writing)
- After all prose written, run humanizer-check on the batch; surface any failures by-name
- Save all Touch notes with `sent: false`; chain to `/send-outreach` for the final send

The bulk mode does NOT skip Phase 2 (voice fingerprint) or Phase 5 (humanizer check) — those are non-negotiable.

---

## Quality bar / refusal conditions

**Refuse and abort with explanation if:**
- Phase 1 research returns context-killing fact (acquisition, role change, prospect death, company shutdown) — surface to user, don't draft on stale context
- Phase 1 research yields zero extractable hooks — drop to C, surface to user
- User attempts to skip humanizer pass — block the send; surface refusal
- User's prose contains ≥3 universal anti-tells (red checks) — flag explicitly + offer redraft loop
- `~/.outreach-factory/config.yml` is missing — abort and tell user to create it
- **Phase 5 hallucination-detection gate returns `state: refused` per ADR-0043 D217** — leave `pipeline_stage: drafted` (NOT `ready`), surface the per-claim trace to the user, offer the two remediation paths (fix the draft OR stamp `hallucination_check_override: true`)
- **Phase 6 Layer 4 emit-guard returns `layer_4_check: refused` per ADR-0047 D245** — leave `pipeline_stage: drafted` (NOT `ready`), surface the per-dimension refusal trace to the user, offer the two per-dimension remediation paths (fix the draft OR stamp the matching per-dimension override `hallucination_check_override` / `voice_fidelity_check_override` with a rationale)

**Quality signals (good run):**
- Channel choice grounded in research
- ≥1 specific verifiable hook citing dated public artifact
- Single clear ask per register
- Word count within register ceiling
- Humanizer pass all green
- Vulnerability signal present (the load-bearing register-positive)
- Hallucination-detection gate returns `state: ready` (every claim cites the dossier OR no extractable claims surface)

**Anti-patterns:**
- Generating full prose in any phase before Phase 3.5 — that's a workflow break, restart at Phase 3
- Quoting marketing copy from the prospect's own homepage as the personalization hook
- Mass-applying same hook across multiple prospects in bulk mode
- Skipping the voice-fingerprint phase for "speed"

---

## See also

- `/research-prospect` — upstream: produces the dossier this skill consumes
- `/send-outreach` — downstream: actually sends the email / LinkedIn DM after this skill writes the Touch note
- `/humanizer` — sub-skill: invoked in Phase 5; sentence-level anti-tell detection
- `docs/ARCHITECTURE.md` — factory pipeline + state machine
- `docs/BILLING.md` — subscription vs API billing matrix + subprocess env trap

---

## Don't

- ❌ Don't generate full prose in Phase 3 — Phase 3.5 is where assembly happens
- ❌ For tier-S high-stakes prospects, prefer `--manual` mode. Default auto-prose trades ~15% voice fidelity for zero user-time-per-email — fine for bulk and tier-B, suboptimal where the recipient knows the user personally and would notice
- ❌ Don't edit the voice retrieval's rewrite output before Phase 5 — that re-injects session-LLM voice on top of user voice
- ❌ Don't run the humanizer pass and silently rewrite — flag failures, surface to user
- ❌ Don't auto-send without confirmation
- ❌ Don't bulk-process without Phase 2 (voice fingerprint) or Phase 5 (humanizer check)
- ❌ Don't ignore a context-killing research finding — surface immediately
- ❌ Don't quote marketing copy from the prospect's own homepage as the personalization hook
- ❌ Don't use em-dashes inside sentences — use hyphens with spaces, commas, or colons
- ❌ Don't strip exclamation marks from a `congrats` register — they're register-required
- ❌ Don't use any script named `voice_translate.py` — that's the deprecated API-billed version
- ❌ Don't bypass the Phase 5 hallucination-detection gate per ADR-0043 D217 — uncited claims signal operator-side hallucination risk that compounds at scale; either remediate the draft OR stamp `hallucination_check_override: true` with a rationale
- ❌ Don't advance `pipeline_stage: ready` when `hallucination_check: failed` without an operator override stamp — the framework's I7 invariant requires refuse-loud on operator misconfiguration
- ❌ Don't skip the Phase 6 Layer 4 emit-guard CLI invocation per ADR-0047 D248 — the Layer 4 verdict IS the structural backstop at the emit boundary + the `draft_ready` event IS the Week 12 Layer 5 reconcile Pass C heal-pass substrate; operators bypassing Layer 4 leave drafts in an unaudited per-dimension verdict state
- ❌ Don't construct the `draft_ready` event payload directly (bypassing `build_draft_ready_payload`) — the factory IS the only sanctioned construction surface per ADR-0047 D245; direct construction is the R030 risk surface and would emit `draft_ready` without consulting the per-Layer verdicts

---

## Origin

Built 2026-05-12 in the aiyara workspace after a personalization audit identified that 8/9 tier-B sends were template-filled. Iterated through three voice-translator versions:

- **v1 (2026-05-12)**: scaffolds-only, user writes prose. 100% fidelity but high user-time cost.
- **v2 (2026-05-13)**: added RAG-based voice translator (Anthropic SDK direct call). ~85% fidelity at zero user-time. Discovered after rollout that voice fidelity is acceptable but the SDK call was API-billed, bypassing the Claude Max subscription.
- **v3 (2026-05-14)**: split voice translator into `voice_retrieve.py` (local-only, CPU-only) + inline agent rewrite (subscription-billed). Same fidelity, $0 API spend.

Migrated from `~/.claude/skills/draft-outreach/` to this repo on 2026-05-14 as part of the outreach-factory open-source split. Aiyara-specific knowledge (company name, founder identity, vault paths, voice corpus paths, wedge framings) now lives in `~/.outreach-factory/config.yml` rather than baked into this file.
