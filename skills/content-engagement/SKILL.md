---
description: Read engagement back for published content posts and recover any orphaned posts, using the Scrapling MCP (the broadcast surface's feedback loop). Scrapes each confirmed post's like / reshare / comment / impression counts via a stealth browser session and feeds them into the optimization report as DELTAS (never cumulative snapshots, so re-polls do not double-count). Also recovers an auto-published post whose confirm was lost to a crash by scraping the author's recent posts. Best-effort and honest: a channel with no readable signal or a broken scrape produces no event, and the report says "no signal" rather than a fabricated number.
---

# /content-engagement - scrape-back the feedback loop

> _The cold side has no feedback loop by design. The broadcast side does: this reads each published post's engagement back via the Scrapling MCP and feeds the optimization report. Scrapling can READ (fetch + extract) but cannot POST, which is exactly the safe half. Read-only against the platform; it never writes a post._

Pairs with `/dispatch-content`. See ADR-0082 D415. The pure correlation + delta + ledger-write logic lives in `orchestrator/content_reconcile.py`; this skill supplies the Scrapling reads.

---

## ⚙️ Pre-flight - config + session cookies

```bash
cat ~/.outreach-factory/config.yml
```

Engagement read needs your platform SESSION COOKIES (logged-out LinkedIn shows almost nothing; X is increasingly gated). Reuse the same cookie sources `/find-leads` and `/research-prospect` already use (`{scraper_auth.twitter_cookies_path}`, your LinkedIn session). Open one stealth Scrapling session and reuse it across fetches:

```
open_session(session_type="stealthy", cookies=<your platform cookies>)  -> session_id
```

Close it at the end (`close_session`).

---

## Phase 1 - recover any orphaned posts (the read-back, Pass A analog)

Auto-published posts can crash between `distribution_intent` and `distribution_confirmed`. Find them:

```bash
python {config.factory.home}/orchestrator/content_reconcile.py --orphans --json   # if a CLI is wired
```

Or inline: `content_reconcile.find_orphaned_distribution_intents(led.all_events(), now=...)`. For each orphan, scrape the author's recent posts on that channel with `stealthy_fetch(<author profile/posts URL>, session_id=..., css_selector=...)`, find the post whose body matches the piece's hook (author + recency + the verbatim hook line), and record it:

`content_reconcile.synthesize_confirmed_from_readback(led, intent_event=orphan, post_id=<scraped id>)`

If no match is found, leave it: do NOT fabricate a post id. (Under the v2 draft-and-manual posture there are usually no orphans, since manual posts write their intent + confirm together at confirm time.)

---

## Phase 2 - read engagement back (the feedback loop)

List the confirmed posts to poll, then scrape each:

```bash
python {config.factory.home}/orchestrator/content_reconcile.py --poll --json
```

Or inline: `content_reconcile.posts_to_poll(led.all_events())` returns `{content_id, channel, post_id}` per published post. For each, `stealthy_fetch` the post's public URL and extract the CUMULATIVE counts with a CSS selector (likes / reshares / comments / impressions, whatever the channel exposes). Then ingest:

`content_reconcile.ingest_engagement(led, content_id=..., channel=..., scraped_metrics={"likes": 50, "comments": 8}, observed_at=<now>)`

`ingest_engagement` converts the cumulative scrape into a DELTA versus what is already in the ledger and appends `engagement_observed` only when something changed. Pass the CUMULATIVE numbers you scraped; the module does the delta math (ADR-0082 D416). A failed or empty scrape (selector broke, post deleted, channel not readable) -> pass `{}` and it emits nothing; the report shows "no signal" honestly.

Cadence: re-poll a post a few times over its first week (engagement front-loads), then stop. Do not hammer; you are using a logged-in session.

---

## Phase 3 - read the report

```bash
python {config.factory.home}/orchestrator/content_scheduler.py --report
```

The per-channel engagement totals are the summed deltas (the cumulative). The "what is working" read is correlational and human-in-the-loop: it surfaces, you decide. What you never do here: post anything, write to any platform, or invent a number a scrape did not return.
