---
name: competitor-customers
version: 2.0.0
description: |
  Mine competitor LinkedIn posts for their named customers + decision-makers, then
  rank as outreach prospects. Customer-mining inverts the keyword-search pattern —
  every competitor names its customers in announcement posts, and those customers
  are proven production agent operators (high-precision buyers). Pairs with
  /find-leads as a complementary discovery channel. Source: `competitor-customers`.
license: MIT
allowed-tools:
  - mcp__linkedin__get_company_posts
  - mcp__linkedin__get_company_profile
  - mcp__linkedin__search_people
  - mcp__obsidian__obsidian_simple_search
  - mcp__obsidian__obsidian_complex_search
  - mcp__obsidian__obsidian_list_files_in_dir
  - mcp__obsidian__obsidian_get_file_contents
  - mcp__obsidian__obsidian_batch_get_file_contents
  - Read
  - Write
  - Bash
  - WebFetch
---

# /competitor-customers — Mine competitor LinkedIn posts for named customers

You are a customer-mining agent. Your job: load the curated competitor list, fetch each competitor's recent LinkedIn posts, extract the customer companies they publicly name, dedupe against the existing CRM, identify buyer-shape contacts at each NEW customer, and save a ranked Lead List in the user's Obsidian vault.

---

## ⚙️ Pre-flight — load user config

**Before doing anything else, read the user's config:**

```bash
cat ~/.outreach-factory/config.yml
```

This file contains the user's company, ICP, vault paths, and discovery source lists. Throughout this skill, wherever you see `{config.X}` placeholders (e.g. `{company.name}`, `{vault.lead_lists_dir}`, `{discovery.competitor_list_path}`, `{icp.buyer_description}`), mentally substitute the loaded config value.

**If `~/.outreach-factory/config.yml` does not exist**: abort and tell the user to copy `config-template/config.example.yml` from the outreach-factory repo to `~/.outreach-factory/config.yml` and fill in their values.

---

## When to use

- Pace-of-leads is slowing (e.g., keyword search yielding <5% NEW per 100 profiles)
- Recent batches surfaced more competitors than buyers
- You want high-precision "proven production agent operator" prospects, not engagement-noise
- Triggered ~weekly to capture fresh customer-announcement signal

## Usage

```
/competitor-customers                          # default: read curated competitor list
/competitor-customers --competitors=<csv>      # override: explicit list
/competitor-customers --max_posts=N            # default 30 per competitor
/competitor-customers --enroll                 # also create Person stubs at pipeline_stage: queued
/competitor-customers --no-enroll              # explicit opt-out (same as default today)
```

**`--enroll` (opt-in for now):** when set, every NEW row also gets a Person note stub created in `{vault.queue_subdir}/` with `pipeline_stage: queued` so `/dispatch-outreach` will pick it up. See Phase 4.5 below. Default is OFF for one release while the auto-enrollment path is being shaken out — once trusted, flip the default to ON in this skill body.

---

## Pipeline (4 phases + Pillar E pre-enrichment dedup)

```
Phase 0: Load CRM state + competitor list
Phase 1: Mine posts (one get_company_posts per competitor)
Phase 2: Extract candidates + dedupe
Phase 3: ICP filter + buyer-shape search
  └─ 3e: Pre-enrichment dedup check (Pillar E — ADR-0033 D152)
Phase 4: Save Lead List
```

---

## Phase 0: Required context

### Competitor list (input)

Source priority:
1. `--competitors=<csv>` flag if passed (takes precedence)
2. `{discovery.competitor_list_path}` if configured → read the markdown, parse LinkedIn slugs from inline list / table / bullet points. Convert each name to a slug (lowercase, hyphenate). For ambiguous slugs, try `search_companies(keywords=<name>)` first to find the right URL.
3. `{discovery.competitor_slugs}` if non-empty → use as-is

If none of the three is available: abort and ask the user to populate one.

### Dedup index (build, same shape as /find-leads Phase 0)

- `obsidian_list_files_in_dir` on each subdir of `{vault.people_dir}/` (typically `{vault.queue_subdir}`, `{vault.active_subdir}`, and any user-defined closed/won subdirs)
- `obsidian_list_files_in_dir` on each subdir of `{vault.companies_dir}/`
- `obsidian_list_files_in_dir` on `{vault.lead_lists_dir}/` then `obsidian_batch_get_file_contents` on each to read `companies:` + `companies_parked:` arrays
- For closed-subdir People, read `status` and `next_action_date`

Use the same `dedup_index` dict shape and normalization rules (lowercase, strip ` AI`/`.ai`/`-ai`, collapse whitespace+hyphens).

**Additionally**: the competitor list itself goes into the dedup index as `kind: competitor` so we never recommend a competitor as a candidate.

---

## Phase 1: Mine posts

For each competitor slug, call `mcp__linkedin__get_company_posts(company_name=<slug>)`. This is ONE call per competitor. Each call returns `{sections.posts: <markdown>, references: [...]}`.

Expected runtime: 5-15s per competitor (browser session). For 13 competitors = ~2-3 minutes total. Run them sequentially (the LinkedIn MCP shares one session under the hood; no benefit from parallelism here).

**Cache the raw output** in conversational context for Phase 2 extraction. Don't write to disk — it's transient.

If a competitor returns `This LinkedIn Page isn't available`, log and skip. Try one alternate slug only; after that, move on.

---

## Phase 2: Extract candidates + dedupe

For each competitor's post bundle, do TWO extractions:

### 2a. Structured (from `references[]`)

Filter `references` to `kind=="company"`. Each gives a slug like `/company/wealthsimple/`. These are companies the competitor tagged in posts. Note: tagged companies include **customers, partners, investors, event hosts, integration partners, and competitor peers**. You'll filter in Phase 3.

Capture: `{company_slug, display_name, found_in_competitor: <slug>}`.

### 2b. Unstructured (from post text)

Most customer names are NOT tagged — they appear as plain text in announcement posts. Parse for these patterns:

| Pattern | Example |
|---|---|
| Welcome/onboarding | `"Welcome SimplePractice to the Decagon customer family"` |
| Now-using | `"GlossGenius as a Decagon customer"` / `"now working with Wealthsimple and Open Farm Pet"` |
| Partnership | `"We're proud to partner with Block"` |
| Customer testimonial quote | `"...— Brian Choi, CEO at Avis Budget Group"` |
| Featured-customer list | `"Used by Hertz and 8 featured customers"` (note count for follow-up) |
| Customer-event mention | `"customers Chime, ClassPass, Mercado Libre, Spring Health, and Wonder"` |
| Logo callouts | `"Leading companies like Afterpay, Contiki, ŌURA, Fusion Markets"` |

Extract `{display_name, found_in_competitor, snippet (the sentence), individual (if a quote: Name+Title)}`.

**Anti-patterns** (do NOT extract as customers):
- Investor names tagged in funding-round announcements (`"led by Brightmind Partners"`)
- Event/conference hosts (`"at RSAC 2026"`, `"AI Agent Conference"`)
- Industry analysts (`"Gartner"`, `"Forrester"`)
- Other vendors mentioned in MAST-style category posts (`"alongside Anthropic's Claude Code, Cursor, Warp, Cognition..."`)
- The competitor's own employees being celebrated
- Open-source projects

**Score the extraction confidence** as you go:
- `HIGH`: explicit customer/welcome/partnership language directly attributed
- `MEDIUM`: appears in customer logo list or testimonial quote
- `LOW`: tagged in references but not contextualized in post text

Drop LOW unless the structured + unstructured signals both fire on the same name.

### 2c. Dedupe against vault

For each extracted candidate company name, run normalization (lowercase, strip ` AI`/`.ai`/`-ai`, collapse). Look up in dedup index:

| Match | Bucket | Reason |
|---|---|---|
| In `{vault.active_subdir}` / won-subdir | SKIP | "in pipeline" |
| In a closed-subdir with `status: dead` | SKIP | "dead" |
| In a closed-subdir with `status: dropped` | SKIP | "dropped pre-contact" |
| In a closed-subdir with `status: dormant` AND `next_action_date ≤ today` | RE-ENGAGE | "dormant past-due" |
| In Lead List `companies:` / `companies_parked:` | SKIP | "in {list}" |
| In competitor list | SKIP | "is a competitor (don't pitch them)" |
| No match | NEW (continue to Phase 3) | — |

---

## Phase 3: ICP filter + buyer-shape search

For each NEW candidate company, do this in order — cheap to expensive:

### 3a. Sanity check the company

Call `mcp__linkedin__get_company_profile(company_name=<slug>)` to confirm:
- Company exists at that slug
- Industry / employee count / location are visible
- Capture the URN from `references[].kind=="company_urn"` — needed for Phase 3c

If the company doesn't resolve, try `search_companies(keywords=<display_name>)` once. If still nothing, drop with reason `linkedin-unresolvable`.

### 3b. ICP filter

Defer to the user's ICP rules (`{icp.tier_playbook_path}` if configured, else `{icp.buyer_description}`), augmented with these structural defaults:

| Reject if | Reason |
|---|---|
| >200 employees (enterprise-only without warm intro) | too slow |
| <10 employees (pre-seed) | too early |
| No public surface (website + LinkedIn presence) | low actionability |
| Out of `{icp.buyer_description}` vertical / wedge | vertical mismatch |

Tag each candidate with `icp_pass: yes|no`. Drop `no` from the NEW list, but record in `companies_parked` with the reject reason.

**Annotate vertical fit explicitly:** the wedge in `{company.wedge_plain}` defines who's a buyer. For example, "production AI agents (tool-calling, multi-step flows) at companies that operate them" means a SaaS company that USES an agent-platform vendor (e.g., uses Decagon for CX) IS a production agent operator and IS in-ICP. A consultancy that ships agents for clients is murkier — note that.

### 3c. Buyer-shape search

For each ICP-pass company, call:

```
mcp__linkedin__search_people(
  keywords="CTO OR Head of AI OR VP Engineering OR founding engineer OR Head of Engineering",
  current_company=<URN>,
)
```

Pick the best buyer-shape match. Prefer in this order:
1. **CTO / Co-founder & CTO** — highest authority on agent-platform decisions
2. **Head of AI / Head of ML / VP AI** — operational owner
3. **VP Engineering / Head of Engineering** — overall tech ownership
4. **Founding engineer with agent ownership** (if visible from headline) — operator-shape
5. **Director of AI / AI Platform Lead** — middle but actionable

If a customer-testimonial quote in Phase 2b already named a person (e.g., `"Rob Sanderson, Senior Director of Customer Intelligence at SimplePractice"`), use that person FIRST — they're publicly engaged with this category and quote-able in the cold-touch.

Record: `linkedin_username`, `full_name`, `title`, `linkedin_url`.

### 3d. Score + tier assignment

Score 1-10:
- 9-10: testimonial-quoted at the competitor + ICP-pass + role exact-fit
- 7-8: ICP-pass + buyer-shape contact found + 1+ public hook
- 5-6: ICP-pass but contact is peer-not-buyer OR public surface thin
- ≤4: drop

Default `tier-S` per `{icp.tier_playbook_path}`. Downgrade to A only if buyer-shape couldn't be confirmed publicly.

### 3e. Pre-enrichment dedup check (Pillar E)

> **Added Pillar E Week 3 (ADR-0033 D152 amendment).** Before any future Apollo / PDL / Reoon enrichment lands in this skill, consult the dedup primitive so a named customer already in the vault doesn't burn a Reoon credit on re-verification. Today `competitor-customers` doesn't call Apollo/PDL/Reoon directly (LinkedIn MCP only), so the practical Week 3 effect is the operator-visible `discovery_dedup_hit` ledger event for Pillar G's per-source cost-attribution dashboard — but the integration is in place so when paid enrichment APIs land here, the cost-avoidance behavior is wired by default. Mirrors `find-leads` Phase 3e exactly; the canonical caller pattern is ADR-0033 D152's code block.

For each NEW candidate row (from Phase 2c's NEW bucket), after Phase 3a sanity-check + Phase 3b ICP-pass + Phase 3c buyer-shape resolved + Phase 3d score + tier assigned:

```bash
python {config.factory.home}/orchestrator/discovery_dedup.py check \
  --linkedin "<LinkedIn URL>" \
  --source-skill competitor-customers \
  --source-list "[[{YYYY-MM-DD}-competitor-customers]]" \
  --apply \
  --json
```

The CLI returns JSON with `status` ∈ `{not_duplicate, duplicate, conflict}` + `should_skip_enrichment` bool:

| `status` | `should_skip_enrichment` | Action |
|---|---|---|
| `not_duplicate` | `false` | Proceed with Phase 4 (lead-list save) + Phase 4.5 (auto-enrollment) as today. |
| `duplicate` | `true` | The named customer is already in the vault. Re-bucket the row to SKIP with reason `"dedup-hit: matched <person_id> on <matched_classes>"`. The `--apply` flag has already emitted the `discovery_dedup_hit` event. Do NOT call enrollment (avoids a redundant `enrollment_skipped_exists` event); surface the dedup-hit row in the SKIP table. |
| `conflict` | `true` | 2+ existing Persons match the candidate's keys OR an ambiguous-shared-email scenario. The CLI's JSON output names the `report_path` (YAML conflict report at `~/.outreach-factory/conflicts/<ts>-<random>.yml`). Re-bucket the row to SKIP with reason `"dedup-conflict: see <report_path>"`. The `--apply` flag has emitted the `discovery_dedup_conflict` event. Aggregate the conflict count + surface at run end. |

> **Why `--apply`:** the dry-run default (no `--apply`) reports the dedup outcome but does NOT append the event to the ledger. Pillar G's per-source cost-attribution dashboard depends on the ledger event landing — operators running `/competitor-customers` interactively (the production cadence) pass `--apply` so the dashboard sees every dedup hit. Test injection / CI / a future `--dry-run` skill flag MAY omit `--apply`; that's the escape valve.

> **Per ADR-0032 D148 the privacy invariant:** the `--source-list` value is OPERATOR-PRIVATE. The CLI stamps it on the emitted event for direct ledger query but Pillar G dashboards NEVER aggregate by `source_list` (only by `source_skill`). The Layer 1 defense is the test corpus pin (`test_source_list_is_operator_private`) which fails loud if a future Pillar G contributor adds `--breakdown source_list` to the funnel CLI.

This phase is content-additive — the existing Phase 2c state-aware dedup (against the in-memory cohort + lead-list + competitor index) still runs first; the dedup primitive's Phase 3e check is the SECOND layer (against the canonical `identity_keys:` block on Person notes — catches dedup hits that Phase 2c's name-only index misses because of normalization mismatches or LinkedIn-slug-only matches where the display name diverges, which is common when competitors paraphrase customer names in announcement posts).

---

## Phase 4: Save Lead List

Save to `{vault.lead_lists_dir}/{YYYY-MM-DD}-competitor-customers.md`.

If multiple runs in one day, suffix with morning/afternoon/evening.

### Frontmatter

```yaml
---
type: lead-list
source: competitor-customers
query: "Customer-mining from {N} curated competitors: {comma-separated competitor slugs}"
total: <NEW + RE-ENGAGE>
new_count: <NEW>
reengage_count: <RE-ENGAGE>
skip_count: <SKIP>
processed: 0
created: <YYYY-MM-DD>
last_drained:
tags:
  - competitor-customers
  - cold-pipeline
companies:
  - <NEW + RE-ENGAGE display names>
companies_parked:
  - <SKIP-for-ICP reasons (NOT in-pipeline skips)>
competitors_mined:
  - <slug 1>
  - <slug 2>
---
```

The `competitors_mined` field is unique to this skill — it lets future runs see which competitors have been swept recently and rotate stale ones to the front.

### Body — required sections

#### 1. Header

```markdown
# Competitor customer mining — {N} new + {M} re-engage ({date})

> _Source: mined {N_competitors} LinkedIn competitor feeds. Total raw mentions: {raw_count}.
> Dedupe against {entity_count} entities + {leadlist_count} prior lead lists._
```

#### 2. Per-competitor yield summary

```markdown
## Yield per competitor

| Competitor | Posts mined | Customer mentions | NEW after dedup | ICP-pass |
|---|---|---|---|---|
| decagon-ai | 30 | 17 | 8 | 4 |
| vijil | 30 | 1 | 1 | 1 |
| ... | | | | |
```

This is the diagnostic loop closure — over time the user can see which competitors are productive customer-mining surfaces.

#### 3. Drain state Dataview

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

1. NEW table → `/research-prospect <linkedin_url>` then `/draft-outreach`. **Reference the competitor attribution in the discovery framing** — e.g., "I noticed you're a {Competitor} customer for {use case}; curious about [wedge-relevant concern] of running agents in production."
2. RE-ENGAGE table → manual; load existing Person note; re-touch references prior conversation, NOT the competitor mention (that'd be weird if you've already talked to them).
3. SKIP table → audit trail only.
```

#### 5. NEW candidates table (with `Competitor` column)

```markdown
## NEW — {count} fresh customer-derived candidates

| # | Company | Website | Used By Customer For | Competitor (mined) | Buyer (role) | Buyer (name) | LinkedIn | Score | Tier | Hook | Source Post |
|---|---|---|---|---|---|---|---|---|---|---|---|
```

**`Source Post` column** — link to the `feed_post` URN from references where the customer was named. This is the audit trail.

**`Hook` column** — include the post snippet that named them, plus any quote. This gives `/draft-outreach` raw material.

#### 6. RE-ENGAGE table (if any)

Same as find-leads.

#### 7. SKIP — collapsed callout

Same as find-leads Phase 4 #6. Bucket: `in-pipeline | parked-vertical | is-competitor | linkedin-unresolvable | dedup-hit | dedup-conflict`.

The `dedup-hit` + `dedup-conflict` buckets are populated by Phase 3e (the Pillar E pre-enrichment dedup primitive). `dedup-hit` means an existing Person note already carries one of the candidate's identity keys; `dedup-conflict` means the candidate's keys match 2+ existing Person notes ambiguously (the operator-visible YAML report at `~/.outreach-factory/conflicts/` carries the merge/split decision tree).

#### 8. Methodology footer

```markdown
## Methodology

- Mined posts via LinkedIn MCP (`get_company_posts`)
- Customer extraction: structured (`references.kind=company`) + unstructured (post-text pattern matching)
- Dedupe (Phase 2c): name normalization vs. entity folders + lead list frontmatter arrays + competitor list
- **Pre-enrichment dedup (Phase 3e, Pillar E)**: identity-key dedup against existing Person notes' `identity_keys:` block via `orchestrator/discovery_dedup.py`. Catches the LinkedIn-slug-match scenarios that Phase 2c's display-name dedup misses (common when competitors paraphrase customer names). Emits `discovery_dedup_hit` events for Pillar G cost-attribution.
- ICP filter: defers to `{icp.tier_playbook_path}` or `{icp.buyer_description}` from config
- Buyer-shape: `search_people` filtered on customer company URN
- Confidence scoring during extraction: HIGH/MED/LOW; LOW dropped unless dual-signal
```

---

## Phase 4.5: Auto-enrollment into the pipeline (`--enroll`)

> **DEFAULT OFF for the first release.** This phase is a no-op unless `--enroll` was on the command line. The disclaimer is repeated here so a reader landing on Phase 4.5 in isolation doesn't assume auto-enrollment is on by default. Once you've shaken out the path on a few Lead Lists, flip the default to ON in this skill body and remove this banner.

For each NEW row in the Lead List (skip RE-ENGAGE — those already have Person notes), shell out to the shared enrollment helper:

```bash
python {config.factory.home}/orchestrator/enrollment.py enroll \
  --name "<Buyer name>" \
  --linkedin "<LinkedIn URL>" \
  --source-skill competitor-customers \
  --source-list "[[{YYYY-MM-DD}-competitor-customers]]" \
  --scraped-at "<ISO 8601 UTC>" \
  --raw-input-hash "<sha256:hex>" \
  --frontmatter "<YAML string with company, role, source_list, source_channel, score, tier, competitor_source>" \
  --body "<minimal body — see template below>" \
  --json
```

> **Identity-graph dedup (Phase 5.5 Week 1b):** pass `--linkedin` explicitly so dedup runs on the stable LinkedIn slug, not the display name. Status `conflict` (with `report_path`) means 2+ existing records match the candidate — count it toward `conflict_count` and surface to the operator at run end so they can resolve in `~/.outreach-factory/conflicts/` before the next dispatch.

> **Discovery lineage stamping (Pillar E Week 9-11, per ADR-0036 D169):** the four `--source-*` / `--scraped-at` / `--raw-input-hash` flags stamp the canonical `identity_keys.discovery_lineage:` sub-block on the new Person frontmatter + denormalize the lineage onto every emitted enrollment event. The `--source-skill` value is the closed enum `competitor-customers`. The `--source-list` matches the Lead List filename. The `--scraped-at` is the run's start ISO 8601 UTC timestamp. The `--raw-input-hash` is `sha256:<sha256 of canonical input>` (e.g., the competitor source post URL + the customer's LinkedIn URL).

The frontmatter YAML to pass per row:

```yaml
company: "[[<Company>]]"
role: <Buyer (role)>
linkedin: <LinkedIn URL>
source_list: "[[{YYYY-MM-DD}-competitor-customers]]"
source_channel: competitor-customers
score: <1-10>
research_tier: <S | A | B>
competitor_source: <competitor-slug-they-were-mined-from>
```

The `company` value is wrapped in `[[…]]` to match the wikilink convention `/research-prospect` writes — keeps the field consistent before and after a refresh, and renders as a clickable link in Obsidian.

The body to pass:

```markdown
# <Buyer name>

## Why this person

<Hook column from this row, verbatim>

Customer of: <Competitor (mined)> (per their public announcement).
Source: <Source Post URL>.
```

Helper output is JSON: `{"ok": bool, "status": "created" | "exists" | "conflict" | "error", "path": str | null, "person_id": str | null, "report_path": str | null, "matched_classes": list | null, "reason": str}`.

- `created` → enrolled successfully; count toward `enrolled_count`. `person_id` is the minted identity id (`<slug>-li`, `<hash>-em`, or `<...>-tmp`).
- `exists` → identity-graph match against an existing Person note. Count toward `skipped_count`. `matched_classes` lists which key classes matched (e.g. `["linkedin"]`, `["email"]`).
- `conflict` → 2+ existing records intersect the candidate's identity keys, OR a single-class email match with a distinct LinkedIn (shared-inbox ambiguity). The helper writes a report to `report_path` and refuses to enroll. Count toward `conflict_count`; surface to operator at run end.
- `error` → rare; log the `reason` and proceed to next row.

After the loop, surface the count in the skill's return string AND in the Lead List frontmatter:

```yaml
enrolled_count: <created>
enrolled_at: <YYYY-MM-DDTHH:MM:SSZ>
```

---

## Output quality bar

- **Every NEW row has a `Source Post`** linking back to the specific competitor announcement.
- **Customer attribution is named** (which competitor mined them).
- **Buyer name when possible** — testimonial-quoted individuals take priority over search_people results.
- **Real dedup numbers** — if SKIP count is 0, the dedup didn't run; verify Phase 0.
- **Anti-pattern check before save**: scan NEW list for any competitor names, investor firms, or analyst orgs. If found, move to `companies_parked`.

---

## Don't

- Don't include the competitor's own employees in NEW.
- Don't include companies in the curated competitor list.
- Don't accept tagged companies blindly — investors/event-hosts/analyst-firms tag too.
- Don't extract from posts older than 6 months — customer relationships churn, and a 12-month-old customer announcement says nothing about today.
- Don't run `search_people` on customer companies that failed ICP — wastes the LinkedIn MCP rate budget.
- Don't pitch customers in regulated verticals when the user's `{icp.buyer_description}` forbids them.
- Don't auto-discover new competitors via `search_companies("agent evaluation")` — that's the keyword-saturation trap. Use the curated list from config.
- Don't overlap with `/find-leads` runs — this skill produces its own Lead List with `source: competitor-customers`. They're complementary, not redundant.

---

## When the competitor list is stale

If a competitor in the input list returns `This LinkedIn Page isn't available` AND `search_companies` returns nothing, flag in the run summary:

> ⚠ Competitor `<slug>` not findable. Check `{discovery.competitor_list_path}` — may have rebranded / shut down. Update doc before next run.

If you discover during mining that a "competitor" is actually a now-popular *partner* or *integration target* (e.g., a tagged company in the references is itself in the eval/safety space), surface for review:

> 💡 New competitor candidate surfaced: `<name>` (mentioned in {competitor}'s posts in eval/safety context). Add to `{discovery.competitor_list_path}`?

---

## See also

- `{discovery.competitor_list_path}` — locked input (user-curated competitor list)
- `/find-leads` — complementary general-ICP discovery
- `/find-funded-founders` — sibling discovery channel (VC-mined funding signals)
- `/research-prospect` — next step after picking a row
- `/draft-outreach` — drafting; reference competitor-customer framing for the hook
- `docs/ARCHITECTURE.md` (in outreach-factory repo) — factory pipeline + state machine
