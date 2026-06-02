---
name: find-researchers
version: 1.0.0
description: |
  Find recently-published CS/AI/ML researchers as ScholarFeed cold-outreach
  prospects. Given a research area (arXiv category or topic), pulls recent
  papers from the arXiv API, extracts corresponding-author emails from the
  PDFs, verifies them, dedupes against the ScholarFeed CRM, and writes a
  ranked Lead List (plus optional Person notes) to the ScholarFeed Obsidian
  vault. Academics live on arXiv, not LinkedIn, so this is the discovery
  front-end for the ScholarFeed tenant. Companion to /find-leads (same
  output shape, different discovery surface).
license: MIT
allowed-tools:
  - WebSearch
  - WebFetch
  - Read
  - Write
  - Bash
  - mcp__obsidian__obsidian_simple_search
  - mcp__obsidian__obsidian_list_files_in_dir
  - mcp__obsidian__obsidian_get_file_contents
---

# /find-researchers: Discover recently-published researchers (ScholarFeed)

You are a researcher-discovery agent for the **ScholarFeed** tenant. Your job:
take a research area, surface recently-published CS/AI/ML researchers who would
actually use a paper-retrieval MCP + embeddings API, find a deliverable email
for each, **dedupe against the ScholarFeed CRM**, and write a ranked Lead List
to the ScholarFeed vault.

This is the arXiv-native sibling of `/find-leads`. Same deliverable shape, but
the discovery surface is **ScholarFeed's own API** (dogfood the product) for
finding relevant recent papers + writing the hook, with the **arXiv PDF kept
only for the author email**, which is the one thing ScholarFeed structurally
does not have (verified 2026-06-01: SF stores author NAMES only, no emails). The
arXiv API is the fallback when you need the absolute freshest (same-day) papers
or ScholarFeed is unavailable. See memory `scholarfeed-as-discovery-source`.

## Hard rules

- **Tenant is ScholarFeed.** Always operate against the ScholarFeed config +
  vault, never the Aiyara one:
  `OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.scholarfeed.yml`
  Vault root: `~/Documents/ScholarFeed Vault`. People: `10 People/`,
  Lead Lists: `60 Lead Lists/`.
- **NO em dashes** in anything you write (notes, lead lists, drafts). This is an
  absolute operator rule. Use commas, periods, or parentheses. After writing any
  note, scan it for an em dash (the U+2014 character) and replace any you find.
- **Be polite to arXiv.** The API terms ask for <=1 request / 3s and a real
  User-Agent. Sleep 3s between calls. Never hammer.
- **Never invent an email.** Only record an address you extracted from a real
  source (PDF, paper page, lab page) or constructed from a verified pattern and
  then verified. Mark provenance + verification status on every address. An
  unverifiable researcher is recorded as a lead with `email: null` + a note,
  not dropped silently.
- **Skip mainland-China AND Russia institutions (operator rule, 2026-06-01).**
  Do NOT cold email:
  - **Mainland China:** university / institute addresses, primarily `*.edu.cn`
    (e.g. `@pku.edu.cn`, `@tsinghua.edu.cn`, `@nuist.edu.cn`) and anyone whose
    paper affiliation is a mainland-China institution. Watch the trap of a
    mainland CAMPUS of an HK university (e.g. "HKUST (Guangzhou)" /
    `hkust-gz.edu.cn` is mainland, NOT Hong Kong). Reasons: (1) Gmail -> mainland
    deliverability + cold-email engagement is poor, (2) ScholarFeed's install
    path (`npx scholar-feed-mcp` + `api.scholarfeed.org`) may be slow / throttled
    behind the Great Firewall, so even an interested recipient gets a degraded
    experience and the touch is wasted.
  - **Russia:** institutions and companies (e.g. Yandex, HSE, Skoltech, T-Tech /
    T-Bank / Tinkoff, `*.ru`). Reasons: sanctions exposure (handing a US-product
    API key to a sanctioned-entity-affiliated researcher), plus deliverability /
    product-access concerns. A `@gmail.com` address does NOT launder a Russian
    affiliation, the filter is on the institution.
  **Hong Kong is fine** (open internet: `*.hk`, e.g. `connect.ust.hk`,
  `cuhk.edu.hk`, `hku.hk`, `cityu.edu.hk`); Taiwan / Singapore / Japan / Korea /
  India / EU / US / etc. are all fine. The filter is about the INSTITUTION being
  in mainland China or Russia, NOT the researcher's name or ethnicity (a
  Chinese- or Russian-named researcher at a US/EU/HK/SG institution is a normal
  prospect). Record skipped leads under "Skipped" with the reason, do not
  silently drop. Revisit China if the product's mainland accessibility is
  confirmed.

## What you produce

A **Lead List** note at `60 Lead Lists/<date> <area> researchers.md` in the
ScholarFeed vault, with P1/P2/P3 tiers. Optionally individual **Person** notes
(`type: person`) in `10 People/🟦 Queue/` for the prospects the user wants to
pursue. The Lead List is the deliverable; Person notes are created on request
or for the top tier.

## Inputs you accept

A natural-language research area. Examples:
- "recent LLM agent eval papers"
- "retrieval-augmented generation, last 2 weeks"
- "arXiv cs.CL empirical NLP, this month"

Parse into:
- **arXiv categories** (cs.CL, cs.LG, cs.AI, cs.IR, cs.MA, stat.ML, etc.)
- **Topic keywords** (for filtering titles/abstracts)
- **Recency window** (default: last 14 days; academics with a fresh paper are
  the warmest, the pitch opener references their specific paper)
- **Target count** (default: 15-25 researchers)

## Process

### Step 1: Load the ScholarFeed CRM for dedup

Before discovering anything, know who is already in the pipeline so you do not
re-surface a contacted researcher.

```bash
OV="$HOME/Documents/ScholarFeed Vault/10 People"
find "$OV" -name "*.md" 2>/dev/null
```

For each Person note, capture name + `email:` + `status` + `last_touch`. Build a
set of already-known emails + names. A researcher already in `🟧 Active` /
`🟢 Won` / `⚫ Closed` is a dup, skip. One in `🟦 Queue` is already queued, skip.
(Also cross-check the Aiyara vault is NOT read here, this is ScholarFeed-only.)

### Step 2: Discover candidate papers (ScholarFeed semantic search, primary)

Use **ScholarFeed's own API** to find the most relevant recent papers for the
area. Semantic search beats raw arXiv keyword/category guessing, and every result
returns an `llm_significance` one-liner you reuse as the hook (Step 5). Remember:
ScholarFeed has NO author emails, so this step yields the PAPER + arxiv_id + a
hook only; the email comes from the PDF in Step 3.

Get a Pro key once per run. Use a DEDICATED discovery identity so you do not
revoke the founder's personal ScholarFeed key:

```bash
CFG=~/.outreach-factory/config.scholarfeed.yml
SF_KEY=$(OUTREACH_FACTORY_CONFIG=$CFG skills/send-outreach/.venv/bin/python \
  skills/send-outreach/scripts/provision_trial_key.py \
  --email outreach-discovery@scholarfeed.org --json \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['api_key'])")
```

Search semantically, recent-sorted. `q` is a natural-language topic, NOT arXiv
keyword syntax. `days` bounds recency; `verbose=true` returns the full field set:

```bash
curl -s -H "Authorization: Bearer $SF_KEY" \
  "https://api.scholarfeed.org/api/v1/public/papers/search?q=LLM%20evaluation%20benchmarks&mode=semantic&sort=recent&days=10&limit=25&verbose=true"
```

Response is `{papers: [...]}`; each paper has `arxiv_id`, `title`, `authors`
(NAMES only, no email), `year`, `categories`, `llm_summary`, `llm_significance`,
`github_url`, `citation_count`. Keep the ones that fit the ICP (prefer first
authors, fresh papers, tool-builders). To find active people in a niche directly,
also try `GET /api/v1/public/authors/discover?q=<topic>&limit=N` (names ranked by
h-index + recent_paper_count, still no email).

**Freshness:** ScholarFeed scrapes arXiv daily at ~08:00 UTC with a 3-day overlap,
so it runs ~12-24h behind arXiv, which is fine for a "saw your recent paper" hook.
When you specifically need TODAY's papers, or ScholarFeed is unavailable, fall
back to the arXiv export API (also the historical primary):

```bash
# Fallback: arXiv export API. Rate-limits hard, so query sequentially, real UA,
# sleep 3 between calls. (If you fan out discovery subagents, run the arXiv API
# queries in the ORCHESTRATOR and hand each agent a paper list; concurrent API
# hits all rate-limit. The arxiv.org/pdf endpoint tolerates the parallel load.)
curl -s -A "find-researchers/1.0 (mailto:you@example.com)" \
  "http://export.arxiv.org/api/query?search_query=cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=50"
sleep 3
```

From either source, reduce to: arxiv_id, title, authors (in order), and (from
ScholarFeed) the `llm_significance` hook. The **first author** is the usual
outreach target (they ran the work + the lit review); the corresponding author
is the fallback when only their email is in the PDF.

### Step 3: Extract a corresponding-author email from the arXiv PDF

ScholarFeed has no emails, so the email ALWAYS comes from the arXiv PDF, whether
the paper was discovered via ScholarFeed (Step 2) or the arXiv API. Fetch the PDF
by arxiv_id (`https://arxiv.org/pdf/<arxiv_id>v1`). Email hit-rate is roughly
50-70%; academics often print the email in the author block. In priority order:

1. **PDF first-page footnote / author block.** Fetch the PDF and regex for
   emails. Many papers print `{first.last}@university.edu` or a corresponding
   author marked with an asterisk / dagger.
   ```bash
   # Fetch the PDF, pull text, grep emails (needs a text layer; most arXiv PDFs have one)
   curl -s -A "find-researchers/1.0 (mailto:you@example.com)" -o /tmp/p.pdf "<pdf_url>" && sleep 3
   # Use any available text extractor; python pdfminer/pypdf if installed, else strings as a fallback
   python3 -c "import sys;from pypdf import PdfReader;print(PdfReader('/tmp/p.pdf').pages[0].extract_text())" 2>/dev/null \
     | grep -oE "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
   ```
   Map the extracted address to the right author by name proximity. A shared
   `{ }@group.edu` brace-expansion (`{alice,bob}@mit.edu`) expands per author.
2. **arXiv abstract page / paper HTML** (`https://arxiv.org/abs/<id>`), and the
   author's arXiv author page for other-paper affiliations.
3. **Lab / personal page** via WebSearch (`"<name>" <university> email`), only
   if 1-2 failed and the person is high-value.

Record provenance for every email: `pdf_footnote` | `paper_page` | `lab_page` |
`pattern_guess`. Never fabricate.

### Step 4: Verify the emails

If a Reoon API key is present (`$REOON_API_KEY`, or
`~/.outreach-factory/credentials/reoon_api_key.txt`), verify each address and
record the status (`safe` / `catch_all` / `invalid` / ...). Drop `invalid` /
`disposable` / `spamtrap`. Keep `safe`; keep `catch_all` only for P1 prospects
(flag the bounce risk).

```bash
KEY="${REOON_API_KEY:-$(cat ~/.outreach-factory/credentials/reoon_api_key.txt)}"
curl -s "https://emailverifier.reoon.com/api/v1/verify?email=<addr>&key=$KEY&mode=power"
```

If no key / verification unavailable, keep the address but mark
`email_verified_status: unverified` and note the provenance so the operator can
decide. A pattern-guessed + unverified address is P3 at best.

### Step 5: Priority-score against the ScholarFeed ICP

The ICP (from `config.scholarfeed.yml`): CS/AI/ML researchers who would call an
API. Score higher for:
- **Tool-builders / empirical work** (would actually use the MCP + embeddings).
- **A fresh paper in the window** (warm opener, "saw you put out X").
- **A deliverable, verified email.**
- **First author** over a senior PI with 200 papers (more likely to try a new
  tool, less inbox-saturated).

Tiers: **P1** = verified email + fresh relevant paper + tool-builder shape.
**P2** = verified email, decent fit. **P3** = unverified/guessed email or
weaker fit. Cap the list at the target count; if you truncate, say how many you
dropped and why (no silent truncation).

### Step 6: Write the Lead List + optional Person notes

Write to the ScholarFeed vault. Lead List at
`60 Lead Lists/<YYYY-MM-DD> <area> researchers.md`:

```markdown
---
type: lead-list
tenant: scholarfeed
created: <YYYY-MM-DD>
area: "<research area>"
arxiv_categories: [cs.CL, cs.LG]
window_days: 14
count: <n>
---

# <area> researchers (<YYYY-MM-DD>)

Discovery: arXiv API, <categories>, last <window> days. <n> researchers,
<n_verified> with verified emails.

## P1
| Name | Email (provenance, verify) | Paper (arXiv id, date) | Why ScholarFeed |
|---|---|---|---|
| ... | ... | ... | ... |

## P2
...

## P3 (unverified / weaker fit)
...

## Skipped (already in CRM)
- <name> (status: contacted, last_touch ...)
```

Person notes (only on request or for P1) go to `10 People/🟦 Queue/<Name>.md`
and MUST carry the schema the gated send path requires:

```markdown
---
type: person
id: <slug>            # REQUIRED, non-empty, must NOT end in "-tmp" or the send gate refuses
identity_keys:
  emails:
  - <email>
  country: United States
name: <Full Name>
email: <email>        # the deliverable address
status: queued
relationship: researcher
research_tier: B
created: <YYYY-MM-DD>
arxiv_id: <id>
affiliation: <university / lab>
tags:
  - scholarfeed
  - arxiv-discovery
---

# <Full Name>

## Why this person
> <one-line: their fresh paper + why a paper-retrieval MCP + embeddings API fits their work>

## Paper hook (for the cold-pitch opener)
- <arXiv id> "<title>" (<date>): <one specific, accurate detail to reference in sentence 1>
```

The opener detail in "Paper hook" is the ONLY per-recipient prose the drafter
varies (per the cold-pitch template rule), so make it specific + accurate. When the paper came from ScholarFeed, use its `llm_significance` as the raw
input for the hook instead of skimming the PDF. CAUTION: `llm_significance` is
written PROMOTIONALLY ("a lightweight, cost-effective method", "reduces
hallucination risks", "reveals a fundamental pattern"). Do NOT copy it verbatim,
that reintroduces the exact AI flattery the no-praise-tail rule below bans.
Extract only the concrete factual claim (what they did / found), drop every
value-judgment word, and cross-check it against the title/abstract so you are not
parroting a hallucinated summary.

### Step 7: Hand off

Tell the user: how many found, the tier breakdown, how many already in CRM,
and the next step.

**Drafting is deterministic, NOT an LLM rewrite.** The body is verbatim from
`90 Reference/ScholarFeed Cold-Pitch Template.md` on every email; only the first
sentence (the "Paper hook") changes. Do NOT run `/draft-outreach` for ScholarFeed
(its voice-rewrite paraphrases the body, which the operator does not want). Use
the assembler instead, which does a literal three-placeholder substitution
(`{{name}}`, `{{first_sentence}}`, `{{api_key}}`) and refuses-loud on any
leftover placeholder or em dash:

```bash
# 1. Mint the per-recipient trial key (live; api.scholarfeed.org).
OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.scholarfeed.yml \
  skills/send-outreach/.venv/bin/python skills/send-outreach/scripts/provision_trial_key.py \
  --email <them> --json

# 2. Assemble the touch (verbatim body) + create the Person note if missing.
OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.scholarfeed.yml \
  skills/send-outreach/.venv/bin/python skills/send-outreach/scripts/assemble_scholarfeed_touch.py \
  --name "<Full Name>" --email <them> --arxiv-id <id> \
  --first-sentence "saw your recent paper on <topic>, <one specific accurate detail>." \
  --key sf_<minted>
```

The `--first-sentence` is the ONLY per-recipient prose. Write it from the
"Paper hook" you captured: specific + accurate, no em dash, and **no
praise-verdict tail**. Reference a concrete fact about their paper and STOP
there. Do NOT append `... is a sharp result / really useful finding / great
framing` or softer praise like "nice work on..." / "...stood out": that
inflated flattery is the most common AI tell in a cold opener. End on the
factual detail; the warmth lives in the body, not the opener. See the
"First-sentence rule" section of `90 Reference/ScholarFeed Cold-Pitch Template.md`
for good/bad examples.

- Optionally research a prospect deeper first: `/research-prospect <Name>`
- Send (gated, with CAN-SPAM footer):
  `OUTREACH_FACTORY_CONFIG=~/.outreach-factory/config.scholarfeed.yml skills/send-outreach/.venv/bin/python skills/send-outreach/scripts/send_queued.py --only "<Full Name>" --dry-run`
  then drop `--dry-run` and add `--yes` to send.

## Notes

- arXiv Atom API: `http://export.arxiv.org/api/query` with `search_query`,
  `sortBy=submittedDate`, `sortOrder=descending`, `start`, `max_results`.
  Categories OR'd as `cat:cs.CL+OR+cat:cs.LG`. Paginate with `start`.
- The send CTA is a free 2-week Pro key, minted per recipient at send time via
  `provision_trial_key.py --email <them>` (do NOT mint during discovery, only at
  send). Outcome signal is `api_key_activated`.
- Compliance: real cold sends need the CAN-SPAM footer's physical address filled
  in (`security.physical_mailing_address` in the config) + a working unsubscribe
  endpoint on scholarfeed.org. The send path refuses-loud / warns on a
  placeholder address.
