---
name: find-leads
version: 3.0.0
description: |
  Find candidate companies + buyer-shaped people for cold outreach. Given a
  natural-language ICP query (vertical, agent type, company size), discovers
  matching companies via web search + Scrapling stealth fetches, identifies likely
  buyer roles + people, deduplicates against the existing CRM (skip already-contacted,
  re-surface dormant past-due), and saves a state-aware ranked lead list to the
  user's Obsidian vault. Use when the user wants to find new prospects, expand the
  pipeline, or convert an ICP description into outreach-ready leads.
license: MIT
allowed-tools:
  - WebSearch
  - WebFetch
  - Read
  - Write
  - Bash
  - mcp__obsidian__obsidian_simple_search
  - mcp__obsidian__obsidian_complex_search
  - mcp__obsidian__obsidian_list_files_in_dir
  - mcp__obsidian__obsidian_get_file_contents
  - mcp__obsidian__obsidian_batch_get_file_contents
  - mcp__ScraplingServer__open_session
  - mcp__ScraplingServer__close_session
  - mcp__ScraplingServer__list_sessions
  - mcp__ScraplingServer__get
  - mcp__ScraplingServer__bulk_get
  - mcp__ScraplingServer__fetch
  - mcp__ScraplingServer__bulk_fetch
  - mcp__ScraplingServer__stealthy_fetch
  - mcp__ScraplingServer__bulk_stealthy_fetch
  - mcp__ScraplingServer__screenshot
---

# /find-leads — Discover prospects matching your ICP (state-aware)

You are a lead-discovery agent. Your job: take a natural-language ICP description, surface 10-20 candidate companies that fit, identify the right buyer-shaped person at each, **dedupe against the existing CRM**, and save a structured lead list to the user's Obsidian vault.

---

## ⚙️ Pre-flight — load user config

**Before doing anything else, read the user's config:**

```bash
cat ~/.outreach-factory/config.yml
```

This file contains the user's company, ICP definitions, vault paths, and tier-playbook pointers. Throughout this skill, wherever you see `{config.X}` placeholders (e.g. `{company.name}`, `{vault.path}`, `{vault.people_dir}`, `{icp.tier_playbook_path}`, `{icp.buyer_description}`), mentally substitute the loaded config value.

**If `~/.outreach-factory/config.yml` does not exist**: abort and tell the user to copy `config-template/config.example.yml` from the outreach-factory repo to `~/.outreach-factory/config.yml` and fill in their values.

---

## Usage

```
/find-leads <ICP description>                  # lead-list-only (default for now)
/find-leads <ICP description> --enroll         # also create Person stubs at pipeline_stage: queued
/find-leads <ICP description> --no-enroll      # explicit opt-out (same as default today)
```

Examples:
- `/find-leads AI agents for customer support, 10-100 employees, US-based`
- `/find-leads YC Spring 2026 sales agents not on yc-wave-1 list --enroll`
- `/find-leads production AI agents in fintech with public engineering blog`
- `/find-leads agent companies that recently posted job openings for AI/ML platform engineers`

**`--enroll` (opt-in for now):** when set, every NEW row also gets a Person note stub created in `{vault.queue_subdir}/` with `pipeline_stage: queued` so `/dispatch-outreach` will pick it up in the next run. See Phase 4.5 below. Default is OFF for one release while the auto-enrollment path is being shaken out — once trusted, flip the default to ON in this skill body.

---

## Pipeline (5 phases)

```
Phase 0: Load CRM state         → existing People/Companies/Lead Lists in memory
Phase 1: Open Scrapling session → reused for all per-source fetches
Phase 2: Discover candidates    → WebSearch + Scrapling per source
Phase 3: Dedup + bucket         → NEW / RE-ENGAGE / SKIP per candidate
Phase 4: Save Lead List         → 3-section table; close Scrapling session
```

---

## Phase 0: Required context (read before searching)

Load these from the user's vault (paths from config):

| File | Why |
|---|---|
| `{icp.tier_playbook_path}` (optional) | Tier-S/A/B rules + ICP filter definitions. Drives Phase 3c. Skip if empty. |
| `{vault.lead_lists_dir}/` (list all files) | Existing pipeline — don't re-discover what we already have |

Use `mcp__obsidian__obsidian_list_files_in_dir` on `{vault.lead_lists_dir}/` to see all prior lists.

### Build the dedup index (in-memory)

Before searching, load every previously-evaluated company/person name into memory so dedup is O(1) per candidate. **Three sources, all vault-native** (no git lookups):

#### Source 1: Entity cohort folders (current pipeline)

`obsidian_list_files_in_dir` on each existing subdir of `{vault.people_dir}/` and `{vault.companies_dir}/` (typically `{vault.queue_subdir}`, `{vault.active_subdir}`, and any user-defined closed/won/dormant subdirs).

For closed-cohort entries only (subdirs that hold finished prospects — user-defined; check vault listing), `obsidian_batch_get_file_contents` to read `status` (dead/dormant/dropped) and `next_action_date` (dormant re-touch eligibility). Don't read Queue/Active files — name match alone = skip.

#### Source 2: Prior Lead Lists (frontmatter `companies:` + `companies_parked:` arrays)

`obsidian_list_files_in_dir` on `{vault.lead_lists_dir}/`, then `obsidian_batch_get_file_contents` on every `.md` in that directory. From each Lead List's frontmatter, read:
- `companies:` — names actively pursued from that list
- `companies_parked:` — names evaluated and rejected (parked vertical, wrong ICP, etc.)

Both go into the dedup index with provenance: `{name, list_file, bucket: pursued|parked}`.

#### Source 3: Single canonical view (optional cross-check)

If the user has a `00 Maps/Known Companies.md` or similar Dataview rollup, `obsidian_get_file_contents` on it as a sanity check. Skip if not present.

#### Index shape

```python
dedup_index = {
    "company_name_normalized": {
        "source": "entity" | "lead_list",
        "folder_or_list": "{vault.companies_dir}/{vault.active_subdir}/" | "{vault.lead_lists_dir}/YC Wave 1.md",
        "status": "active" | "parked" | "dead" | "dormant" | "queued",
        "reason": "<one-line>",
        "next_action_date": "<YYYY-MM-DD or null>",
    },
    ...
}
```

**Normalization rules** for matching candidate names against the index:
- Lowercase
- Strip trailing " AI" / "-ai" / ".ai"
- Collapse whitespace + hyphens
- E.g., `"Trycardinal AI"` and `"Cardinal"` both normalize to `cardinal` → match.

---

## Phase 1: Scrapling session

Open ONE persistent stealthy session at the start of the run. Reuse for all per-source fetches. Close it at the end.

```python
# Conceptual — open once
session_id = mcp__ScraplingServer__open_session(
    session_type="stealthy",
    headless=True,
    solve_cloudflare=True,
    google_search=True,
    timeout=45000
)
```

Pass `session_id=...` to every `fetch` / `stealthy_fetch` / `screenshot` call. This avoids the 5-10s browser cold-start per request and shares cookies across same-domain navigations.

At the end of the run, ALWAYS call `close_session(session_id)`. If you exit via error, still try to close.

---

## Phase 2: Discovery (smart escalation)

### Fetcher selection (per source)

Use the cheapest fetcher that works. Escalate on failure.

| Source | Default fetcher | Why |
|---|---|---|
| Google search results | `WebSearch` | Native Claude, fastest, zero cost |
| YC company directory (`ycombinator.com/companies/...`) | `stealthy_fetch` + `solve_cloudflare: true` | Cloudflare-protected; WebFetch fails |
| Wellfound (`wellfound.com/...`) | `stealthy_fetch` | Aggressive bot detection |
| Crunchbase (`crunchbase.com/...`) | `stealthy_fetch` + `solve_cloudflare: true` | Cloudflare + JS-heavy |
| LinkedIn guest pages (`linkedin.com/in/...`, `/company/...`) | `stealthy_fetch` | Bot-walled for unauthenticated reads |
| Product Hunt (`producthunt.com/...`) | `stealthy_fetch` | Cloudflare in front |
| HN front + show pages (`news.ycombinator.com/...`) | `get` | Static HTML, server-rendered |
| GitHub team pages, contributor lists | `get` | Static HTML |
| Job boards (Lever, Greenhouse, Ashby) | `bulk_stealthy_fetch` if many at once, else `fetch` | JS-rendered, sometimes bot-walled |
| Generic company `/about` `/team` pages | `fetch` first; on empty/blocked → `stealthy_fetch` | Most are JS-rendered |
| Engineering blog posts | `get` (cheap) | Usually static |

### Escalation rule

If a fetch returns:
- `403 / 429 / Cloudflare challenge page` → retry with `stealthy_fetch` + `solve_cloudflare: true`
- empty body / "JavaScript required" / "Please enable cookies" → retry with `fetch` (or `stealthy_fetch`)
- still empty after stealth → log "blocked: {url}" and skip that source for this candidate; don't burn 3+ retries

### Parallelization

When fetching N>3 URLs from the same source at the same time, prefer `bulk_get` / `bulk_fetch` / `bulk_stealthy_fetch`. Don't open multiple sessions; pass `session_id` to each bulk call.

### Discovery sources

#### Tier 1 — high-quality lead sources

1. **YC company directory** — search `site:ycombinator.com/companies/{keyword}` via WebSearch, then `stealthy_fetch` each company page for description + team
2. **Hacker News** — "Show HN: <agent-related>", "Ask HN: who's hiring" with AI/agent keywords; `get` for HN pages
3. **Product Hunt** — recent launches in AI agents category; `stealthy_fetch`
4. **Wellfound** — search by tag (AI, LLM, agents); `stealthy_fetch`
5. **Crunchbase** — funding rounds in AI agent space; `stealthy_fetch` (often metered)

#### Tier 2 — discovery via inference

6. **Job postings** — companies hiring "ML platform engineer," "agent reliability engineer," "AI infrastructure" → they likely run agents in production. Use `bulk_stealthy_fetch` on Lever/Greenhouse/Ashby URLs.
7. **Conference speakers** — AI Engineer Summit, Latent Space, AI tinkerers — speakers' companies
8. **GitHub contributors** — to popular agent libs (langchain, langgraph, openai-agents, autogen) → their employer often runs agents; `get` for static GH pages
9. **Twitter/X public posts** — search via WebSearch for "our agent did X" + similar; `stealthy_fetch` profile pages

#### Tier 3 — adjacent-but-noisy

10. **AI newsletter mentions** — Latent Space podcast, Last Week in AI — companies they cover
11. **Public engineering blogs** — `get` is usually enough

---

## Phase 3: Per-candidate workflow + dedup

For EACH candidate company surfaced in Phase 2:

### 3a. Confirm fit + identify buyer

1. Fetch the company's `/about`, `/team`, `/careers` pages (per fetcher table above)
2. Identify the buyer-shaped person per `{icp.buyer_description}` (typically: CTO, Head of AI, VP Eng, founding engineer with relevant product ownership). If multiple, pick the most public-facing technical leader.
3. Find their LinkedIn URL — search `"{Name}" "{Company}" LinkedIn` if not on team page
4. Score ICP fit (1-10) — be honest; reject anything <6
5. Note one specific public artifact — a blog post, talk, GitHub repo, conference appearance — that proves they're a real prospect (not a stub)

### 3b. State-aware dedup (the "learning" part)

For both **company name** and **person name** (after normalization), look up in the dedup index built in Phase 0:

| Match found | Bucket | Reason recorded |
|---|---|---|
| Person/Company in `{vault.active_subdir}` or any user-defined "won" subdir | **SKIP** | "in pipeline ({status})" |
| Person in a "closed" subdir with `status: dead` | **SKIP** | "dead ({last_touch})" |
| Person in a "closed" subdir with `status: dropped` | **SKIP** | "dropped pre-contact" |
| Person in a "closed" subdir with `status: dormant` AND `next_action_date` ≤ today | **RE-ENGAGE** | "dormant past-due since {next_action_date}" |
| Person in a "closed" subdir with `status: dormant` AND `next_action_date` > today | **SKIP** | "dormant; re-touch {next_action_date}" |
| Person in `{vault.queue_subdir}` | **SKIP** | "queued from {source_list or 'manual'}" |
| Company in Lead List `companies:` array | **SKIP** | "in {list-name} (pursued)" |
| Company in Lead List `companies_parked:` array | **SKIP** | "in {list-name} (parked-vertical)" |
| No match anywhere | **NEW** | — |

Track the bucket + reason on every candidate as you process. **Do this BEFORE any per-company detail fetch** — saves Scrapling fetches on names you'll skip anyway.

### 3c. ICP filter (apply only to NEW + RE-ENGAGE)

If `{icp.tier_playbook_path}` is configured, apply the rules defined there. Otherwise, use the prose criteria in `{icp.buyer_description}` from config, augmented with these structural defaults:

- **Has public surface area** — website, blog, GitHub, Twitter, podcast, talks. Need things to reference for hyper-personalization.
- **Has a buyer-shaped role visible** — public team page lists the kind of role described in `{icp.buyer_description}`.
- **Stage** — typically Series Seed → Series C (10-200 employees) unless user explicitly broadens. Pre-seed too early; enterprise too slow without warm intro.

If the user's wedge (`{company.wedge_plain}`) implies vertical exclusions (e.g. SOC2/HIPAA-blocking), respect them. The buyer_description should encode these.

### 3d. Assign `research_tier` (default S; A/B are downgrades)

If `{icp.tier_playbook_path}` defines tier rules, use them. Default semantics if none:

1. Is the candidate a buyer-shape title per `{icp.buyer_description}`? If no → tag `peer-not-buyer`; downgrade one tier from where they'd otherwise land.
2. Does the company match the wedge (`{company.wedge_plain}`)? If no → bucket should be SKIP (vertical mismatch), not NEW.
3. **Default → S.** Assume full `/research-prospect` will run downstream.
4. **Downgrade to A** ONLY if the public surface is constrained: LinkedIn locked-private + no X presence + no podcast/blog → `/research-prospect` would yield ≤2 hooks. Note "downgrade reason" in the Hook column.
5. **Downgrade to B** ONLY if even light research returns nothing extractable (rare; usually this is a C — drop). Note "downgrade reason."

Record the tier in the candidate's row and add a `tier-S` / `tier-A` / `tier-B` tag entry to be propagated onto the Person note at draft time.

**Expected distribution per ~10-prospect batch**: ~7-9 S + ~1-3 A + 0-1 B. If a batch comes back with >2 A/B candidates, the ICP filter (3c above) is leaking thin-surface prospects — tighten it (or sharpen `{icp.buyer_description}`) before saving the Lead List.

### 3e. Pre-enrichment dedup check (Pillar E)

> **Added Pillar E Week 2 (ADR-0033 D152).** Before any future Apollo / PDL / Reoon enrichment lands in this skill, consult the dedup primitive so a candidate already in the vault doesn't burn a Reoon credit on re-verification. Today `find-leads` doesn't call Apollo/PDL/Reoon (per the rule in the "Don't" section below), so the practical Week 2 effect is the operator-visible `discovery_dedup_hit` ledger event for Pillar G's per-source cost-attribution dashboard — but the integration is in place so when Apollo/PDL/Reoon lands here (or in the other three discovery skills in subsequent Pillar E weeks), the cost-avoidance behavior is wired by default.

For each NEW candidate row (from Phase 3b's NEW bucket), after Phase 3a confirmed buyer fit + Phase 3c passed ICP + Phase 3d assigned tier:

```bash
python {config.factory.home}/orchestrator/discovery_dedup.py check \
  --linkedin "<LinkedIn URL>" \
  --source-skill find-leads \
  --source-list "[[{YYYY-MM-DD}-{slug}]]" \
  --apply \
  --json
```

The CLI returns JSON with `status` ∈ `{not_duplicate, duplicate, conflict}` + `should_skip_enrichment` bool:

| `status` | `should_skip_enrichment` | Action |
|---|---|---|
| `not_duplicate` | `false` | Proceed with Phase 4 (lead-list save) + Phase 4.5 (auto-enrollment) as today. |
| `duplicate` | `true` | The candidate is already in the vault. Re-bucket the row to SKIP with reason `"dedup-hit: matched <person_id> on <matched_classes>"`. The `--apply` flag has already emitted the `discovery_dedup_hit` event. Do NOT call enrollment (avoids a redundant `enrollment_skipped_exists` event). |
| `conflict` | `true` | 2+ existing Persons match the candidate's keys OR an ambiguous-shared-email scenario. The CLI's JSON output names the `report_path` (a YAML conflict report at `~/.outreach-factory/conflicts/<ts>-<random>.yml`). Re-bucket the row to SKIP with reason `"dedup-conflict: see <report_path>"`. The `--apply` flag has emitted the `discovery_dedup_conflict` event. Aggregate the conflict count + surface at run end. |

> **Why `--apply`:** the dry-run default (no `--apply`) reports the dedup outcome but does NOT append the event to the ledger. Pillar G's per-source cost-attribution dashboard depends on the ledger event landing — operators running `/find-leads` interactively (the production cadence) pass `--apply` so the dashboard sees every dedup hit. Test injection / CI / a future `--dry-run` skill flag MAY omit `--apply`; that's the escape valve.

> **Per ADR-0032 D148 the privacy invariant:** the `--source-list` value is OPERATOR-PRIVATE. The CLI stamps it on the emitted event for direct ledger query but Pillar G dashboards NEVER aggregate by `source_list` (only by `source_skill`). The Layer 1 defense is the test corpus pin (`test_source_list_is_operator_private`) which fails loud if a future Pillar G contributor adds `--breakdown source_list` to the funnel CLI.

This phase is content-additive — the existing Phase 3b state-aware dedup (against the in-memory cohort + lead-list index) still runs first; the dedup primitive's Phase 3e check is the SECOND layer (against the canonical `identity_keys:` block on Person notes — catches dedup hits that Phase 3b's name-only index misses because of normalization mismatches).

---

## Phase 4: Output (state-aware Lead List)

Save to `{vault.lead_lists_dir}/{YYYY-MM-DD}-{slug}.md` in the vault.

Slug = compressed query (e.g., `cs-agents-mid-market`, `yc-spring-26-ops`).

### Required frontmatter

```yaml
---
type: lead-list
source: <yc | hn | wellfound | producthunt | crunchbase | web-search | jobs | github | mixed>
query: "<original ICP query verbatim>"
total: <count of NEW + RE-ENGAGE>
new_count: <count of NEW>
reengage_count: <count of RE-ENGAGE>
skip_count: <count of SKIP>
processed: 0
created: <YYYY-MM-DD>
last_drained:
tags:
  - <relevant tags from query>
companies:
  # company display names of all NEW + RE-ENGAGE candidates (so future runs dedupe against them)
  - <Company Name 1>
  - <Company Name 2>
companies_parked:
  # company display names of SKIP candidates that were rejected for ICP/vertical reasons
  # (do NOT include companies SKIP'd because they're already in pipeline — those are tracked elsewhere)
  - <Parked Company 1>
---
```

**Why both arrays:** future `/find-leads` runs read these to skip names you've already evaluated, even if they're not entity records yet. Companies parked here = "we've considered + rejected" = future runs auto-SKIP with reason "in {this-list} (parked-vertical)."

### Required body sections

#### 1. Header

```markdown
# {Query slug} — {N} new + {M} re-engage ({date})

> _Source: {source channel}. Query: "{original query}". Dedupe ran against {entity_count} existing entities + {leadlist_count} prior Lead Lists._
```

#### 2. Drain state (Dataview)

```dataview
TABLE WITHOUT ID
  link(file.link) as "Person",
  link(company) as "Company",
  status as "Status",
  last_touch as "Last touch"
FROM "{vault.people_dir}"
WHERE source_list = this.file.link
SORT status ASC
```

#### 3. Drain protocol

```markdown
## Drain protocol

1. NEW table → `/draft-outreach <Lead List path> --row=N --register cold-pitch` (the skill auto-populates `source_list` and `source_channel` on the new Person notes)
2. RE-ENGAGE table → manual; load the existing Person note, draft a re-touch (NOT a fresh cold touch — reference prior conversation)
3. SKIP table is informational only (no action needed)
```

#### 4. NEW candidates table

```markdown
## NEW — {count} fresh candidates

| # | Company | Website | AI Agent Product | Buyer (role) | Buyer (name) | LinkedIn | Score | Tier | Hook | Source URL |
|---|---|---|---|---|---|---|---|---|---|---|
```

The **Tier** column carries `S` / `A` / `B` per Phase 3d. `/draft-outreach` reads this column when drafting from `--row=N` and routes research depth + variant accordingly.

#### 5. RE-ENGAGE table (only if any)

```markdown
## RE-ENGAGE — {count} dormant past-due

| # | Person | Company | Last touch | Past-due since | Notes for re-touch |
|---|---|---|---|---|---|
```

#### 6. SKIP — collapsed summary (not a full table)

> **Do NOT print a 13-row SKIP table inline.** It dilutes the NEW/RE-ENGAGE signal. Output a 1-line count + collapsed callout.

```markdown
## SKIP — {count} already covered

> {count_in_pipeline} in active pipeline · {count_lead_list_pursued} in prior lead lists · {count_parked_vertical} parked-vertical · {count_other} other

> [!info]- Audit trail (click to expand)
> | Name | Why | Where |
> |---|---|---|
> | <Company> | in pipeline | `{vault.companies_dir}/{vault.active_subdir}/X.md` |
> | <Company> | parked-vertical | `{vault.lead_lists_dir}/YC Wave 1.md` |
> | ... | ... | ... |
```

The `[!info]-` Obsidian callout is collapsed by default. Reader sees only the 1-line summary unless they click to expand.

If `count` is 0, omit this section entirely.

#### 7. Score legend + scoring methodology

Brief 1-line explanation per score band.

---

## Phase 4.5: Auto-enrollment into the pipeline (`--enroll`)

> **DEFAULT OFF for the first release.** This phase is a no-op unless `--enroll` was on the command line. The disclaimer is repeated here so a reader landing on Phase 4.5 in isolation doesn't assume auto-enrollment is on by default. Once you've shaken out the path on a few Lead Lists, flip the default to ON in this skill body and remove this banner.

For each NEW candidate row in the Lead List (skip RE-ENGAGE — those already have Person notes; skip SKIP — those are intentionally out), shell out to the shared enrollment helper:

```bash
python {config.factory.home}/orchestrator/enrollment.py enroll \
  --name "<Buyer name>" \
  --linkedin "<LinkedIn URL>" \
  --source-skill find-leads \
  --source-list "[[{YYYY-MM-DD}-{slug}]]" \
  --scraped-at "<ISO 8601 UTC>" \
  --raw-input-hash "<sha256:hex>" \
  --frontmatter "<YAML string with company, role, source_list, source_channel, tier, score>" \
  --body "<minimal body — see template below>" \
  --json
```

> **Identity-graph dedup (Phase 5.5 Week 1b):** pass `--linkedin` explicitly so dedup runs on the stable LinkedIn slug, not the display name. New status `conflict` (with `report_path`) means 2+ existing records intersect the candidate's identity keys — aggregate into `conflict_count` and surface at run end.

> **Discovery lineage stamping (Pillar E Week 9-11, per ADR-0036 D169):** the four `--source-*` / `--scraped-at` / `--raw-input-hash` flags stamp the canonical `identity_keys.discovery_lineage:` sub-block on the new Person frontmatter + denormalize the lineage onto every emitted enrollment event (`enrolled` + `enrollment_skipped_exists` + `enrollment_conflict` + `needs_identity_upgrade`). The `--source-skill` value is the closed enum `find-leads` for this skill. The `--source-list` matches the Lead List filename (operator-private per ADR-0032 D148 — never aggregated by Pillar G dashboards). The `--scraped-at` is the run's start ISO 8601 UTC timestamp. The `--raw-input-hash` is `sha256:` + sha256 hex of the per-candidate canonical input (e.g., `<linkedin-url>|<source-url>`). The frontmatter YAML's legacy `source_channel:` + `source_list:` fields stay (back-compat for any consumer not yet reading `source_skill`).

The frontmatter YAML to pass per row (substitute from the row's columns):

```yaml
company: "[[<Company>]]"
role: <Buyer (role)>
linkedin: <LinkedIn URL>
source_list: "[[{YYYY-MM-DD}-{slug}]]"
source_channel: find-leads
research_tier: <S | A | B>
score: <1-10>
```

The `company` value is wrapped in `[[…]]` to match the wikilink convention `/research-prospect` writes — keeps the field consistent before and after a refresh, and renders as a clickable link in Obsidian.

The body to pass:

```markdown
# <Buyer name>

## Why this person

<Hook column from this row, verbatim>

Source: <Source URL column>.
```

Helper output is JSON: `{"ok": bool, "status": "created" | "exists" | "error", "path": str | null, "reason": str}`.

- `created` → enrolled successfully; count toward `enrolled_count`.
- `exists` → Person note already in the vault (dedup matched a prior entry the lead list dedup didn't catch — usually means a name normalization mismatch). Count toward `skipped_count`. Don't error; the prospect was meant to be in the pipeline anyway.
- `error` → rare; log the `reason` and proceed to next row.

After the loop, surface the count in the skill's return string AND in the Lead List frontmatter:

```yaml
enrolled_count: <created>
enrolled_at: <YYYY-MM-DDTHH:MM:SSZ>
```

---

## Output quality bar

- **No generic entries.** Every NEW row must have at least one specific public artifact in "Hook".
- **Buyer name when possible.** "CTO unknown" is acceptable for ~20% of rows; >40% means you didn't research enough.
- **Source URL** for each NEW candidate (not just "found via Google").
- **Real dedup numbers.** Skip count of 0 means the dedup didn't run — verify Phase 0 actually loaded the index.
- **Close the Scrapling session.** Always call `close_session` at the end (or via finally).

---

## When the query is too vague

If the user runs `/find-leads ai agents` (no specifics), respond with a clarifying question via AskUserQuestion (if available) or ask in plain text:

> The query is too broad to produce useful leads. Sharpen by picking 2 of:
> - **Vertical:** sales/CS, ops, fintech-adjacent, healthcare-adjacent, DevOps, marketing, legal-tech
> - **Stage:** YC current batch / seed / Series A-C / mid-market
> - **Geography:** US-only / global / specific region
> - **Public-surface filter:** has engineering blog / has GitHub / has recent funding
>
> Then re-run `/find-leads <sharper query>`.

---

## Don't

- Don't return synthetic / fake companies. If a search comes up empty, say so honestly.
- Don't include companies in regulated industries unless user explicitly asks or the user's `{icp.buyer_description}` permits it (banking, insurance, healthcare-direct, fintech-direct).
- Don't include LinkedIn URLs you guessed without verifying — say "LinkedIn: not found" if you couldn't confirm.
- Don't dump 50 leads. 10-20 high-quality NEW > 50 low-quality. Filter aggressively.
- Don't try email-find via Hunter/Apollo (paid APIs unavailable). LinkedIn URL is enough at this stage.
- Don't open multiple Scrapling sessions in one run. One session, reused, closed at end.
- Don't skip Phase 0. Without the dedup index, you'll re-surface dead/active prospects and waste the user's time.
- **Don't print a full SKIP table inline.** Use the collapsed callout (Phase 4 #6). 13 SKIP rows in plaintext dilutes the NEW signal.
- **Don't fetch detail pages for SKIP candidates.** Bucket from listing-name dedup BEFORE per-company stealthy_fetch. Saves time + Scrapling load.
- **Don't `bulk_stealthy_fetch` more than 4 URLs at once with `extraction_type: markdown`.** Output exceeds the tool result token cap (~97k chars for 6 full YC company pages). Either limit batch size, or pass `css_selector: "main"` to narrow extraction.

---

## Example invocation flow

```
User: /find-leads YC Spring 2026 customer support agents not on yc-wave-1 list

Skill:
1. [Phase 0] Lists all subfolders of {vault.people_dir}/, {vault.companies_dir}/, {vault.lead_lists_dir}/.
   Builds dedup index (e.g., 47 people + 15 companies + 4 prior lead lists).
   Reads frontmatter of closed-subdir Person notes (1 dead, 0 dormant).
2. [Phase 1] Opens Scrapling stealthy session (session_id=abc123).
3. [Phase 2] WebSearches "yc spring 2026 customer support AI agent",
   stealthy_fetches each YC company page in parallel via bulk_stealthy_fetch.
4. [Phase 3] For each candidate:
   - stealthy_fetch /team page
   - Identify CTO/buyer per {icp.buyer_description}
   - Dedupe → NEW (12) | RE-ENGAGE (1, dormant past-due) | SKIP (3, already in vault)
5. [Phase 4] Saves to {vault.lead_lists_dir}/2026-05-09-yc-spring-cs-agents.md with 3 tables.
6. [Phase 4.5] If --enroll, shells to enrollment.py per NEW row. Counts created vs exists.
7. Closes Scrapling session.

Returns (without --enroll): "Saved 12 NEW + 1 RE-ENGAGE + 3 SKIP to [path]. Top NEW: [Company A, B, C].
RE-ENGAGE: <Name> @ <Company> (dormant since 2026-04-22). Open the file to drain."

Returns (with --enroll): "Saved 12 NEW + 1 RE-ENGAGE + 3 SKIP to [path]. Enrolled 11 new prospects
into pipeline at `pipeline_stage: queued` (1 already existed in vault). Run `/dispatch-outreach` to
advance them. RE-ENGAGE: <Name> @ <Company> (dormant since 2026-04-22). Open the file to drain."
```

---

## See also

- `/research-prospect` — pairs with this skill; produces dossiers from Lead List rows
- `/draft-outreach` — pairs with this skill; auto-populates `source_list` + `source_channel` when called from a Lead List row
- `docs/ARCHITECTURE.md` (in outreach-factory repo) — factory pipeline + state machine
