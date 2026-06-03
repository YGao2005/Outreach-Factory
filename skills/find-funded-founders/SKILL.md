---
name: find-funded-founders
version: 2.0.0
description: |
  Mine VC LinkedIn posts for recently-funded Seed / Series A founders, dedupe
  against the CRM, identify the buyer-shape (founder / CTO / Head of AI),
  priority-score against your ICP, and save a Lead List with P1/P2/P3 tiers
  in the user's Obsidian vault. Bias the top of the funnel toward low-key
  early-stage founders in active growth mode (newly-funded = buying intent).
  Companion to /competitor-customers; same shape, different discovery surface.
  Source: `funded-founders`.
license: MIT
allowed-tools:
  - mcp__linkedin__get_company_posts
  - mcp__linkedin__get_company_profile
  - mcp__linkedin__get_person_profile
  - mcp__linkedin__search_people
  - mcp__linkedin__search_companies
  - mcp__obsidian__obsidian_simple_search
  - mcp__obsidian__obsidian_complex_search
  - mcp__obsidian__obsidian_list_files_in_dir
  - mcp__obsidian__obsidian_get_file_contents
  - mcp__obsidian__obsidian_batch_get_file_contents
  - mcp__ScraplingServer__open_session
  - mcp__ScraplingServer__close_session
  - mcp__ScraplingServer__stealthy_fetch
  - mcp__ScraplingServer__fetch
  - mcp__ScraplingServer__get
  - Read
  - Write
  - Bash
  - WebFetch
  - WebSearch
---

# /find-funded-founders - Mine VC posts for recently-funded early-stage founders

You are a funded-founder mining agent. Your job: load a curated list of seed / early-stage VC firms + individual investors, fetch their recent LinkedIn posts, extract the portfolio companies they publicly announced investments in, filter to in-ICP companies, dedupe against the CRM, identify the founder (or buyer-shape exec) at each, **priority-score using the Fit / Intent / Engagement weighted model**, and save a ranked Lead List with P1/P2/P3 tiers to the user's Obsidian vault.

---

## ⚙️ Pre-flight - load user config

**Before doing anything else, read the user's config:**

```bash
cat ~/.outreach-factory/config.yml
```

This file contains the user's company, ICP, vault paths, and discovery source lists. Throughout this skill, wherever you see `{config.X}` placeholders (e.g. `{company.name}`, `{vault.lead_lists_dir}`, `{discovery.vc_list_path}`, `{icp.buyer_description}`), mentally substitute the loaded config value.

**If `~/.outreach-factory/config.yml` does not exist**: abort and tell the user to copy `config-template/config.example.yml` from the outreach-factory repo to `~/.outreach-factory/config.yml` and fill in their values.

---

## When to use

- Pace-of-leads slowing on existing channels (`/find-leads`, `/competitor-customers` saturating)
- You want "in active growth mode" prospects - newly-funded founders have budget + urgency
- Post-YC demo day weeks (S25 / F25 / W26 batches surface heavily)
- ~Weekly cadence to catch fresh announcements within the 7-30 day signal-decay window
- You want to bias toward **low-key early-stage** - founders whose company isn't in the press yet but whose VC announced the round

## Usage

```
/find-funded-founders                          # default: read curated VC list, max_age=90 days
/find-funded-founders --vcs=<csv>              # override the VC list
/find-funded-founders --max_posts=N            # default 30 per VC
/find-funded-founders --max_age_days=N         # default 90; signal decay floor
/find-funded-founders --stage=seed|series-a|both   # default both
/find-funded-founders --include-tc-rss         # optional v1.1: also pull TechCrunch /venture RSS
/find-funded-founders --enroll                 # also create Person stubs at pipeline_stage: queued
/find-funded-founders --no-enroll              # explicit opt-out (same as default today)
```

**`--enroll` (opt-in for now):** when set, every NEW row also gets a Person note stub created in `{vault.queue_subdir}/` with `pipeline_stage: queued` so `/dispatch-outreach` will pick it up. See Phase 5.5 below. Default is OFF for one release while the auto-enrollment path is being shaken out - once trusted, flip the default to ON in this skill body.

---

## Pipeline (5 phases + Pillar E pre-enrichment dedup)

```
Phase 0: Load CRM state + VC list
Phase 1: Mine VC posts (one get_company_posts per VC)
Phase 2: Extract candidates + funding metadata + dedupe
Phase 3: ICP filter + buyer-shape (founder) search
Phase 4: Priority scoring (Fit / Intent / Engagement → P1-P5)
  └─ 4f: Pre-enrichment dedup check (Pillar E - ADR-0033 D152)
Phase 5: Save Lead List with priority tiers
```

---

## Phase 0: Required context

### VC list (input)

Source priority:
1. `--vcs=<csv>` flag if passed (takes precedence)
2. `{discovery.vc_list_path}` if configured → read the markdown, parse LinkedIn slugs from inline list / table / bullet points
3. `{discovery.vc_slugs}` if non-empty → use as-is
4. Inline factory default below (seed-stage AI-vertical VCs, as of 2026-05-13)

**Factory default canonical list** (use when none of the above is configured):

```
# Tier 1 - high-volume seed/A AI infrastructure investors
y-combinator, andreessenhorowitz, sequoia-capital, initialized-capital,
first-round-capital, greylock-partners, conviction-partners, founders-fund,
lightspeed-venture-partners, khosla-ventures, general-catalyst, accel-partners

# Tier 2 - boutique / specialist seed funds
south-park-commons, hustle-fund, 500-startups, pioneer-fund, floodgate,
felicis, mayfield-fund, bessemer-venture-partners, bain-capital-ventures, neaglobal

# Tier 3 - AI-specific micro-funds (verify slugs at runtime via search_companies)
ai-grant, conviction-vc, ai-fund, character-vc, basis-set-ventures
```

For each slug, try `get_company_profile(company_name=<slug>)` first. If it returns `not available`, run `search_companies(keywords=<readable_name>)` once to find the correct slug; if still nothing, log and skip that VC.

**Optional individual-investor accounts** (if `--include-individuals` flag is passed - v1.1):
Use `get_person_profile(linkedin_username=<handle>)` then `get_*` for their posts. Slugs: `garrytan`, `pmarca`, `naval`, `eladgil`, `reid-hoffman`, `sama` (if accessible).

### Dedup index (build, same shape as /competitor-customers Phase 0)

Use the exact pattern from `competitor-customers` SKILL.md Phase 0:

- `obsidian_list_files_in_dir` on each subdir of `{vault.people_dir}/` (typically `{vault.queue_subdir}`, `{vault.active_subdir}`, and any user-defined closed/won subdirs)
- `obsidian_list_files_in_dir` on each subdir of `{vault.companies_dir}/`
- `obsidian_list_files_in_dir` on `{vault.lead_lists_dir}/` then `obsidian_batch_get_file_contents` on each → read `companies:` + `companies_parked:` frontmatter
- For closed-subdir People, read `status` and `next_action_date`

Use the same `dedup_index` dict shape and normalization rules (lowercase, strip ` AI`/`.ai`/`-ai`, collapse whitespace+hyphens).

**Additionally**: load the curated VC list itself + the competitor list (from `{discovery.competitor_list_path}` or `{discovery.competitor_slugs}`) into the dedup index as `kind: vc` / `kind: competitor` so we never accidentally pitch an investor firm or competitor.

---

## Phase 1: Mine VC posts

For each VC slug, call `mcp__linkedin__get_company_posts(company_name=<slug>)`. ONE call per VC. Each call returns `{sections.posts: <markdown>, references: [...]}`.

Expected runtime: 5-15s per VC. For 20+ VCs = ~3-5 minutes. Run sequentially (LinkedIn MCP shares one underlying session; parallelism gives no benefit and risks rate limits).

**Cache the raw output** in conversational context for Phase 2. Don't write to disk - it's transient.

If a VC returns `This LinkedIn Page isn't available`, log and skip. Try one alternate slug only (e.g., `a16z` instead of `andreessenhorowitz`); after that, move on.

**Volume control:** for high-volume VCs (a16z, Sequoia post 5+ times/week), the latest 30 posts will cover roughly 30-60 days. If `--max_age_days=N` is restrictive, ignore posts older than N days during extraction (Phase 2).

---

## Phase 2: Extract candidates + funding metadata

For each VC's post bundle, do TWO extractions, same as `competitor-customers`:

### 2a. Structured (from `references[]`)

Filter `references` to `kind=="company"`. These are companies the VC tagged. Note: tagged companies include **portfolio companies, peer VCs, event hosts, integration partners**. You'll filter in Phases 2b-3.

Capture: `{company_slug, display_name, found_in_vc: <slug>}`.

### 2b. Unstructured (from post text - funding announcement patterns)

Most portfolio mentions ARE in plain post text. Parse for these patterns:

| Pattern | Example |
|---|---|
| Led-the-round | `"Excited to lead the $3M Seed in NoteDrop"` / `"Led the seed round in @parakeet"` |
| Our-investment | `"Excited to announce our investment in Aleph"` / `"thrilled to back the team at Stamp"` |
| Welcome-to-portfolio | `"Welcoming Cardinal to the Initialized family"` / `"Adding @nullbase to our portfolio"` |
| Founder-raised | `"Today @parakeet_ai announced their $4M seed led by..."` |
| Congrats-on-raise | `"Congrats to the nullbase team on closing their seed"` |
| Partnering-with | `"Partnering with the GammaTau team on their journey"` |
| Demo-day | `"YC S25 Demo Day favorites: @companyA, @companyB, @companyC..."` |

For each match, extract:
- `display_name` (company name)
- `found_in_vc` (the VC whose post mentioned them)
- `round_stage` - parse "seed" / "pre-seed" / "Series A" / "Series B" from the text. If unstated, `unknown`.
- `round_size_usd` - parse `$Xm` / `$Y` patterns. If unstated, `null`.
- `post_date` - from the post's frontmatter / metadata (LinkedIn MCP usually returns ISO date)
- `snippet` - the full sentence containing the mention
- `individual` - if a founder is named/quoted, capture (Name, optional Title)

**Anti-patterns** (do NOT extract as portfolio candidates):

- Peer VC firms (`"led by Brightmind Partners, with participation from Sequoia"`) - the co-investors aren't candidates
- Event hosts (`"at YC Demo Day"`, `"at AI Summit"`)
- Industry analysts (`"Gartner"`, `"Forrester"`)
- The VC's own portfolio service-providers (legal firms, accounting)
- Founders' personal accounts being tagged as a courtesy without an investment context
- LP / co-investor LP firms
- Late-stage announcements (Series C+ unless small follow-on)
- Acquisitions or IPOs (exited founders = not buyers for an early-stage product)

**Extraction confidence** (same as competitor-customers):

- `HIGH`: explicit lead / investment / portfolio language directly attributed to the VC posting
- `MEDIUM`: appears in a portfolio roll-up or congrats post
- `LOW`: tagged in references with no contextual support

Drop `LOW` unless the structured + unstructured signals both fire on the same name.

### 2c. Stage filter (applied early)

Filter by `--stage`:

- `seed` → keep `round_stage in {pre-seed, seed}` OR `round_size_usd <= 5M` (when stage is unstated but size is)
- `series-a` → keep `round_stage == Series A` OR `5M < round_size_usd <= 15M`
- `both` (default) → keep `round_stage in {pre-seed, seed, Series A}` OR `round_size_usd <= 15M`
- Drop anything Series B+ or `round_size_usd > 20M` even if in ICP

Founders past Series B have different incentives - the funnel for them needs warm intros, not cold touch.

### 2d. Dedupe against vault

For each candidate company name (after normalization), look up in dedup index:

| Match | Bucket | Reason |
|---|---|---|
| In `{vault.active_subdir}` / won-subdir | SKIP | "in pipeline" |
| In a closed-subdir with `status: dead` | SKIP | "dead" |
| In a closed-subdir with `status: dropped` | SKIP | "dropped pre-contact" |
| In a closed-subdir with `status: dormant` AND `next_action_date ≤ today` | RE-ENGAGE | "dormant past-due" |
| In Lead List `companies:` / `companies_parked:` | SKIP | "in {list}" |
| In curated VC list | SKIP | "is a VC (don't pitch them)" |
| In curated competitor list | SKIP | "is a competitor" |
| No match | NEW (continue to Phase 3) | - |

---

## Phase 3: ICP filter + buyer-shape (founder) search

For each NEW candidate company, cheap to expensive:

### 3a. Sanity check the company

Call `mcp__linkedin__get_company_profile(company_name=<slug>)`. Capture:

- Industry / employee count / location
- The numeric URN (from `references[].kind=="company_urn"`) - needed for Phase 3c
- Company `founded` year (if visible) - for "low-key early-stage" filter

If unresolvable, try `search_companies(keywords=<display_name>)` once. If still nothing, drop with reason `linkedin-unresolvable`.

### 3b. ICP filter

Defer to the user's ICP rules (`{icp.tier_playbook_path}` if configured, else `{icp.buyer_description}`), augmented with these funded-founder-specific structural filters:

| Reject if | Reason |
|---|---|
| **>50 employees** | this skill targets low-key early-stage; defer to `/find-leads` for mid-market |
| <3 employees | pre-incorporation / stealth - too early |
| No website yet | low actionability; check back in 30 days |
| Last funded >12 months ago | the funding signal is stale; treat as cold lead via `/find-leads` |
| Founded >5 years ago AND still seed-stage | stagnant; deprioritize |
| Out of `{icp.buyer_description}` vertical / wedge | vertical mismatch |

Tag each `icp_pass: yes|no`. Drop `no` from NEW but record in `companies_parked` with the reject reason.

**Bias for low-key:** if the company has <100 LinkedIn followers AND <10 employees AND the funding announcement is the first public mention surface-able, mark `low_key: true` - these are the highest-novelty leads vs. the press-darling YC darlings.

### 3c. Buyer-shape (founder-first) search

For each ICP-pass company, call:

```
mcp__linkedin__search_people(
  keywords="Founder OR Co-founder OR CEO OR CTO OR Head of AI OR Head of Engineering OR founding engineer",
  current_company=<URN>,
)
```

For early-stage companies, **prefer founders** over operational ICs. Priority order:

1. **Solo founder / CEO + technical co-founder** - at <10 employees, the founder IS the buyer
2. **CTO / Co-founder & CTO** - if there's a non-technical CEO, the CTO owns agent decisions
3. **Founding engineer** with agent-product ownership (visible in headline/bio)
4. **Head of AI / Head of ML** (rare at this stage; usually means later-seed / Series A)
5. **VP Engineering / Head of Engineering** - only if 20+ employees

If the funding-announcement post in Phase 2b already named/quoted a founder (e.g., `"- Sarah Chen, CEO at Aleph"`), use that person FIRST - they're publicly engaged and quote-able in the cold-touch.

Record: `linkedin_username`, `full_name`, `title`, `linkedin_url`, `is_founder: yes|no`.

If no buyer-shape person resolves on the company, downgrade Tier (Phase 4 → 4b) but don't drop the row - the company is still a real prospect; user can manually research.

---

## Phase 4: Priority scoring (Fit / Intent / Engagement)

Adopt the GTM Flywheel weighted model. Formula:

```
Priority Score = (Fit × 0.30) + (Intent × 0.45) + (Engagement × 0.25)
Maximum: 100
```

Compute three sub-scores per candidate.

### 4a. Fit Score (0-100)

| Component | Max | Scoring rule |
|---|---|---|
| Employee count in target window (3-50) | 25 | 5-30 emp = 25; 3-5 or 30-50 = 15; outside = 5 |
| Vertical match per `{icp.buyer_description}` | 20 | Primary = 20; adjacent = 12; tangential = 5 |
| Buyer-shape role found | 25 | Founder/CTO/CEO = 25; Head-of-Eng/AI = 18; peer-not-buyer = 8 |
| Public surface (website + LinkedIn + ≥1 blog/talk/GitHub) | 15 | ≥3 surfaces = 15; 2 = 10; 1 = 5; 0 = drop |
| Geography (US default; non-US ok but warmer in time zone) | 10 | US = 10; EU = 7; APAC = 4 |
| Funding stage in window (Seed-Series A) | 5 | seed = 5; series-A = 4; pre-seed = 3 |

Sum capped at 100.

### 4b. Intent Score (0-100) - funding signal is the intent

| Component | Max | Scoring rule |
|---|---|---|
| Funding recency (days since announcement) | 40 | 0-7d = 40; 8-30d = 30; 31-60d = 18; 61-90d = 8; >90d = drop (Phase 2) |
| Round size in fit window | 20 | $1-15M = 20; $0-1M = 12; $15-20M = 10 |
| Wedge-relevant keyword density in announcement post | 20 | Words matching `{company.wedge_plain}` / `{company.wedge_failure_mode}` = 20; generic AI = 10; LLM/RAG-adjacent = 5 |
| First-party post (VC firm OR founder posted directly vs. retweeted) | 10 | VC direct = 10; retweet/syndication = 5 |
| Multi-VC stack (funding announcement names ≥2 reputable VCs) | 10 | yes = 10; solo VC = 6; angel-only = 3 |

Sum capped at 100.

**Signal decay:** Funding signal decay -2 per month. Already encoded above via the recency bracket (8-30d at 30 ≈ -10 from peak; 31-60d at 18 ≈ -22).

### 4c. Engagement Score (0-100)

Default `0` for net-new (no prior outreach).

| Activity | Points |
|---|---|
| Lead is RE-ENGAGE (dormant past-due) | 40 |
| Person previously replied "not now" / timing | 30 |
| Company was previously parked (now ready?) | 15 |
| Person engaged with `{company.name}` content publicly (LI post like/comment) | 20 |
| Met at an event or warm intro available | 50 |

Sum capped at 100.

### 4d. Compute final priority + tier

```python
priority_score = round(fit * 0.30 + intent * 0.45 + engagement * 0.25)
```

Map to priority tier:

| Score | Tier | SLA | Action |
|---|---|---|---|
| 80-100 | **P1** | Contact within 24h | Multi-channel: email + LinkedIn DM, P1 personalization |
| 60-79 | **P2** | Contact within 3 days | Email + LinkedIn connection request |
| 40-59 | **P3** | Contact within 1 week | Email only, batched into next /draft-outreach run |
| 20-39 | **P4** | Backburner | Park; monitor for new signal |
| 0-19 | **P5** | Drop | Move to `companies_parked` |

### 4e. Research tier (`tier-S` / `tier-A` / `tier-B`) - keep alongside priority

This is separate from priority - research-depth, not conversion-likelihood. Per `/find-leads` Phase 3d:

- Default `tier-S` (full `/research-prospect` will run downstream)
- Downgrade to `tier-A` if public surface is constrained
- Downgrade to `tier-B` if even light research returns nothing extractable

A row can be `P1 + tier-A` (high priority, do shallow research) or `P3 + tier-S` (low priority, but if you do reach out, full research).

### 4f. Pre-enrichment dedup check (Pillar E)

> **Added Pillar E Week 3 (ADR-0033 D152 amendment).** Before any future Apollo / PDL / Reoon enrichment lands in this skill, consult the dedup primitive so a founder already in the vault doesn't burn a Reoon credit on re-verification. Today `find-funded-founders` doesn't call Apollo/PDL/Reoon directly (LinkedIn MCP only), so the practical Week 3 effect is the operator-visible `discovery_dedup_hit` ledger event for Pillar G's per-source cost-attribution dashboard - but the integration is in place so when paid enrichment APIs land here, the cost-avoidance behavior is wired by default. Mirrors `find-leads` Phase 3e exactly; the canonical caller pattern is ADR-0033 D152's code block.

For each NEW candidate row (from Phase 2d's NEW bucket, after Phase 3 ICP-pass + Phase 4d priority + Phase 4e research tier are assigned), call the dedup primitive **before** the row goes into the Phase 5 lead list save + Phase 5.5 auto-enrollment shell:

```bash
python {config.factory.home}/orchestrator/discovery_dedup.py check \
  --linkedin "<LinkedIn URL>" \
  --source-skill find-funded-founders \
  --source-list "[[{YYYY-MM-DD}-funded-founders]]" \
  --apply \
  --json
```

The CLI returns JSON with `status` ∈ `{not_duplicate, duplicate, conflict}` + `should_skip_enrichment` bool:

| `status` | `should_skip_enrichment` | Action |
|---|---|---|
| `not_duplicate` | `false` | Proceed with Phase 5 (lead-list save) + Phase 5.5 (auto-enrollment) as today. |
| `duplicate` | `true` | The founder is already in the vault. Re-bucket the row to SKIP with reason `"dedup-hit: matched <person_id> on <matched_classes>"`. The `--apply` flag has already emitted the `discovery_dedup_hit` event. Do NOT call enrollment (avoids a redundant `enrollment_skipped_exists` event); update the SKIP table to surface the dedup-hit row. |
| `conflict` | `true` | 2+ existing Persons match the candidate's keys OR an ambiguous-shared-email scenario. The CLI's JSON output names the `report_path` (YAML conflict report at `~/.outreach-factory/conflicts/<ts>-<random>.yml`). Re-bucket the row to SKIP with reason `"dedup-conflict: see <report_path>"`. The `--apply` flag has emitted the `discovery_dedup_conflict` event. Aggregate the conflict count + surface at run end. |

> **Why `--apply`:** the dry-run default (no `--apply`) reports the dedup outcome but does NOT append the event to the ledger. Pillar G's per-source cost-attribution dashboard depends on the ledger event landing - operators running `/find-funded-founders` interactively (the production cadence) pass `--apply` so the dashboard sees every dedup hit. Test injection / CI / a future `--dry-run` skill flag MAY omit `--apply`; that's the escape valve.

> **Per ADR-0032 D148 the privacy invariant:** the `--source-list` value is OPERATOR-PRIVATE. The CLI stamps it on the emitted event for direct ledger query but Pillar G dashboards NEVER aggregate by `source_list` (only by `source_skill`). The Layer 1 defense is the test corpus pin (`test_source_list_is_operator_private`) which fails loud if a future Pillar G contributor adds `--breakdown source_list` to the funnel CLI.

This phase is content-additive - the existing Phase 2d state-aware dedup (against the in-memory cohort + lead-list + VC + competitor index) still runs first; the dedup primitive's Phase 4f check is the SECOND layer (against the canonical `identity_keys:` block on Person notes - catches dedup hits that Phase 2d's name-only index misses because of normalization mismatches or LinkedIn-slug-only matches where the display name diverges).

**Recommended placement in the loop:** run Phase 4f INSIDE the per-candidate priority-scoring loop, immediately after Phase 4e assigns research tier. The dedup-hit row's SKIP re-bucketing is reflected in Phase 5's lead-list frontmatter counters (`skip_count` increments; `new_count` / `p1_count` / `p2_count` / `p3_count` decrement) - keeping the counts honest.

---

## Phase 5: Save Lead List

Save to `{vault.lead_lists_dir}/{YYYY-MM-DD}-funded-founders.md`.

If multiple runs in one day, suffix with morning/afternoon/evening.

### Frontmatter

```yaml
---
type: lead-list
source: funded-founders
query: "Funded-founder mining from {N} curated VC firms: {comma-separated VC slugs}"
total: <NEW + RE-ENGAGE>
new_count: <NEW>
reengage_count: <RE-ENGAGE>
skip_count: <SKIP>
p1_count: <count where tier == P1>
p2_count: <count where tier == P2>
p3_count: <count where tier == P3>
processed: 0
created: <YYYY-MM-DD>
last_drained:
stage_filter: <seed | series-a | both>
max_age_days: <N>
tags:
  - funded-founders
  - cold-pipeline
  - early-stage
companies:
  - <NEW + RE-ENGAGE display names>
companies_parked:
  - <SKIP-for-ICP reasons; NOT in-pipeline skips>
vcs_mined:
  - <slug 1>
  - <slug 2>
---
```

The `vcs_mined` field is unique to this skill - lets future runs see which VCs have been swept recently and rotate stale ones.

### Body - required sections

#### 1. Header

```markdown
# Funded founders mining - {N} new + {M} re-engage ({date})

> _Source: mined {N_vcs} VC LinkedIn feeds (stage: {stage_filter}, max age: {max_age_days}d).
> Raw mentions: {raw_count}. Dedupe against {entity_count} entities + {leadlist_count} prior lead lists.
> Priority tiers: {p1_count} P1 (24h SLA) · {p2_count} P2 (3d) · {p3_count} P3 (1w)._
```

#### 2. Per-VC yield summary

```markdown
## Yield per VC

| VC | Posts mined | Funding mentions | NEW after dedup | ICP-pass | P1 | P2 | P3 |
|---|---|---|---|---|---|---|---|
| y-combinator | 30 | 14 | 9 | 5 | 2 | 2 | 1 |
| initialized-capital | 30 | 8 | 4 | 3 | 1 | 1 | 1 |
| ... | | | | | | | |
```

Diagnostic loop closure - over time the user can see which VCs are productive funding-mining surfaces.

#### 3. Drain state Dataview (same as competitor-customers)

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

#### 4. Drain protocol

```markdown
## Drain protocol

1. **P1 rows first** (24h SLA): `/research-prospect <linkedin_url>` then `/draft-outreach`.
   Reference the funding round in the discovery framing - e.g., "Saw the {VC} seed
   announcement last week - curious how the team is thinking about [wedge-relevant
   concern] as you scale beyond the first cohort of customers."
2. **P2 rows next** (3d SLA): batched `/draft-outreach`.
3. **P3 rows** (1w SLA): batch through `/draft-outreach --auto-prose` for volume.
4. RE-ENGAGE → manual; load existing Person note; re-touch references prior
   conversation, NOT the funding mention (would be weird if you've already talked).
5. SKIP table → audit trail only.
```

#### 5. NEW candidates table (with `Priority` + `Tier` columns)

```markdown
## NEW - {count} fresh funded-founder candidates

| # | Priority | Score | Company | Round | Date | Website | AI Agent Product | Founder/Buyer | LinkedIn | Tier (research) | Hook | Source Post |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
```

Sort the table by `Priority` (P1 first), then by `Score` descending within tier.

**Column notes:**
- `Priority`: P1 / P2 / P3 (computed in Phase 4d)
- `Score`: 0-100 (the raw priority score)
- `Round`: e.g., `Seed $3M` or `Series A $8M` or `Seed (size unstated)`
- `Date`: ISO date of the funding announcement
- `Founder/Buyer`: name + role (e.g., `Sarah Chen, CEO`)
- `Tier (research)`: S/A/B for `/research-prospect` depth
- `Hook`: 1-2 sentence snippet from the announcement post + any quote
- `Source Post`: link to the VC's announcement post URN

#### 6. RE-ENGAGE table (if any)

Same shape as `competitor-customers`.

#### 7. SKIP - collapsed callout

Same as `competitor-customers` Phase 4 #6. Buckets:
`in-pipeline | parked-vertical | is-vc | is-competitor | linkedin-unresolvable | too-late-stage | too-stale-signal | dedup-hit | dedup-conflict`.

The `dedup-hit` + `dedup-conflict` buckets are populated by Phase 4f (the Pillar E pre-enrichment dedup primitive). `dedup-hit` means an existing Person note already carries one of the candidate's identity keys; `dedup-conflict` means the candidate's keys match 2+ existing Person notes ambiguously (the operator-visible YAML report at `~/.outreach-factory/conflicts/` carries the merge/split decision tree).

#### 8. Methodology footer

```markdown
## Methodology

- Mined posts via LinkedIn MCP (`get_company_posts` per VC)
- Funding extraction: structured (`references.kind=company`) + unstructured (post-text pattern matching)
- Stage filter applied early: seed / pre-seed / Series A only (size <= $15M default)
- Dedupe (Phase 2d): name normalization vs. entity folders + lead list frontmatter arrays + VC list + competitor list
- **Pre-enrichment dedup (Phase 4f, Pillar E)**: identity-key dedup against existing Person notes' `identity_keys:` block via `orchestrator/discovery_dedup.py`. Catches the LinkedIn-slug-match scenarios that Phase 2d's display-name dedup misses. Emits `discovery_dedup_hit` events for Pillar G cost-attribution.
- ICP filter: defers to `{icp.tier_playbook_path}` or `{icp.buyer_description}` + low-key early-stage bias (<50 employees)
- Buyer-shape: founder-first (`search_people` keywords prioritize Founder/CEO/CTO)
- **Priority scoring (Fit × 0.30 + Intent × 0.45 + Engagement × 0.25)** - Signal decay encoded
  in Intent.Recency bracket. P1/P2/P3 tiers determine drain SLA.
- Research tier (S/A/B) separate from priority tier - research-depth, not conversion-likelihood.
```

---

## Phase 5.5: Auto-enrollment into the pipeline (`--enroll`)

> **DEFAULT OFF for the first release.** This phase is a no-op unless `--enroll` was on the command line. The disclaimer is repeated here so a reader landing on Phase 5.5 in isolation doesn't assume auto-enrollment is on by default. Once you've shaken out the path on a few Lead Lists, flip the default to ON in this skill body and remove this banner.

For each NEW row WHERE `priority in {P1, P2, P3}` (skip RE-ENGAGE - those already have Person notes; skip P4 backburner and P5 drop - they're explicitly low-priority and should stay out of the active queue), shell out to the shared enrollment helper:

```bash
python {config.factory.home}/orchestrator/enrollment.py enroll \
  --name "<Founder/Buyer name>" \
  --linkedin "<LinkedIn URL>" \
  --source-skill find-funded-founders \
  --source-list "[[{YYYY-MM-DD}-funded-founders]]" \
  --scraped-at "<ISO 8601 UTC>" \
  --raw-input-hash "<sha256:hex>" \
  --frontmatter "<YAML string with company, role, source_list, source_channel, priority, score, tier, round_stage, round_size_usd, funding_date, vc_source>" \
  --body "<minimal body - see template below>" \
  --json
```

> **Identity-graph dedup (Phase 5.5 Week 1b, shipped 2026-05-15):** `enrollment.py` no longer deduplicates by name - it intersects LinkedIn slug + email + GitHub + Twitter against every existing Person note. Always pass `--linkedin` explicitly so the helper can mint a stable `<slug>-li` id and recognize the prospect on re-discovery. Returned `status` is one of `created` / `exists` / `conflict` / `error`. On `conflict` (2+ existing records match), the helper writes a report under `~/.outreach-factory/conflicts/` and returns `report_path`; aggregate conflict counts in the run summary so the operator can resolve them manually before the next dispatch.

> **Discovery lineage stamping (Pillar E Week 9-11, per ADR-0036 D169):** the four `--source-*` / `--scraped-at` / `--raw-input-hash` flags stamp the canonical `identity_keys.discovery_lineage:` sub-block on the new Person frontmatter + denormalize the lineage onto every emitted enrollment event. The `--source-skill` value is `find-funded-founders` (the closed-enum form per ADR-0032 D142; the legacy `source_channel: funded-founders` short form stays in the frontmatter for back-compat). The `--scraped-at` is the run's start ISO 8601 UTC timestamp. The `--raw-input-hash` is `sha256:<sha256 of canonical input>` (e.g., the VC post URL + the founder's LinkedIn URL).

The frontmatter YAML to pass per row:

```yaml
company: "[[<Company>]]"
role: <Founder/Buyer role>
linkedin: <LinkedIn URL>
source_list: "[[{YYYY-MM-DD}-funded-founders]]"
source_channel: funded-founders
priority: <P1 | P2 | P3>
score: <0-100 priority score>
research_tier: <S | A | B>
round_stage: <pre-seed | seed | Series A | unknown>
round_size_usd: <number or null>
funding_date: <YYYY-MM-DD>
vc_source: <vc-slug>
```

The `company` value is wrapped in `[[…]]` to match the wikilink convention `/research-prospect` writes - keeps the field consistent before and after a refresh, and renders as a clickable link in Obsidian.

The body to pass:

```markdown
# <Founder/Buyer name>

## Why this person

<Hook column from this row, verbatim>

Funding: <Round> on <Date> (mined from <vc-slug>'s post).
Source: <Source Post URL>.
```

Helper output is JSON: `{"ok": bool, "status": "created" | "exists" | "error", "path": str | null, "reason": str}`.

- `created` → enrolled successfully; count toward `enrolled_count`.
- `exists` → Person note already in the vault. Count toward `skipped_count`. Don't error.
- `error` → rare; log the `reason` and proceed to next row.

After the loop, surface the count in the skill's return string AND in the Lead List frontmatter:

```yaml
enrolled_count: <created>
enrolled_at: <YYYY-MM-DDTHH:MM:SSZ>
```

**Order matters:** enroll P1 rows first, then P2, then P3. If `--max_enroll N` is set (future flag), cap by priority order so the highest-SLA prospects always make it into the queue.

---

## Output quality bar

- **Every NEW row has a `Source Post`** linking to the VC announcement.
- **Funding metadata is filled** - round stage + size + date. If the post didn't state them, mark `(unstated)` honestly; don't fabricate.
- **Buyer is named where possible** - quoted founders take priority over `search_people` results.
- **Priority sort is enforced** - P1 rows at top, then P2, then P3. Don't shuffle by alphabetical or row-number.
- **Real dedup numbers** - if SKIP count is 0, dedup didn't run; verify Phase 0.
- **Anti-pattern check before save** - scan NEW for any VC firms, competitor names, analyst orgs. If found, move to `companies_parked`.
- **At least one P1 per run is a good signal**. If a run yields ZERO P1s, either the funding-signal window is dry that week OR the VC list needs rotation (some VCs going stale).

---

## Don't

- Don't include the VC's own employees in NEW (e.g., a16z partners showing up as `search_people` results on a16z URN).
- Don't include companies in the curated VC list as candidates.
- Don't extract from posts older than 6 months - funding signal fully decayed.
- Don't run `search_people` on companies that failed ICP - wastes LinkedIn rate budget.
- Don't pitch founders in regulated verticals when the user's `{icp.buyer_description}` forbids them.
- Don't fabricate round size - if the announcement post didn't state a number, leave the cell `(unstated)`.
- Don't auto-discover new VCs via `search_companies("venture capital ai")` - that's the keyword-saturation trap. Use the curated list.
- Don't overlap with `/competitor-customers` runs - they're complementary discovery channels with `source: funded-founders` vs. `source: competitor-customers` for analytics separation.
- **Don't downgrade Priority based on Tier (research-depth) or vice versa.** They're orthogonal axes.

---

## When the VC list is stale

If a VC returns `not available` AND `search_companies` returns nothing, flag in the run summary:

> ⚠ VC `<slug>` not findable. Check LinkedIn manually - may have rebranded. Update reference doc before next run.

If you find a new VC repeatedly tagged across multiple seed announcements (e.g., "led by Brightmind, with @newvc participating"), surface for review:

> 💡 New seed-stage VC candidate surfaced: `<name>` (mentioned in {count} co-investor positions). Add to curated VC list?

---

## See also

- `/competitor-customers` - sibling discovery channel (curated competitor mining)
- `/find-leads` - general-ICP discovery
- `/research-prospect` - next step after picking a row
- `/draft-outreach` - funding-aware hook framing in cold-pitch register
- `docs/ARCHITECTURE.md` (in outreach-factory repo) - factory pipeline + state machine
