---
description: Dispatch the content-distribution worklist (the broadcast sibling of /dispatch-outreach). Reads the deterministic due-posts list from the scheduler, runs each due post through the policy guardrails, and produces a DRAFT-AND-REMIND worklist: the post text + where to post it + a "paste this yourself" note. In v2 every channel is human-gated (you paste); the dispatcher never auto-posts. After you post, it records the post in the ledger (confirm_manual_post) so the piece moves to "posted" and drops out of the due list. The post button is yours.
---

# /dispatch-content - the draft-and-manual posting worklist

> _The scheduler decides which approved posts are due now (read-only). This skill turns that worklist into "post these, here is the text, here is where" reminders, runs the guardrails, and records each post once you have pasted it. No auto-posting in v2: the post button is human-gated (ADR-0082 D414)._

This is the broadcast (1:many) sibling of `/dispatch-outreach`. It reuses the same review-gate discipline and the same two-phase ledger commit, but the "send" is you pasting the post. See `docs/adr/0082-content-distribution-foundation.md` (Phase 2 addendum) and `.planning/PHASE2-content-distribution-PLAN.md`.

---

## ⚙️ Pre-flight - load config

```bash
cat ~/.outreach-factory/config.yml
```

Read the `content:` block (`enabled`, `auto_publish` is off and stays off in v2, `channels`). If `content.enabled` is false, tell the operator and stop. `{config.X}` means substitute the loaded value.

---

## Phase 1 - the due-posts worklist (read-only)

Get the deterministic due list. This is a pure ledger read; it never posts.

```bash
python {config.factory.home}/orchestrator/content_scheduler.py --json
```

Each entry is `{content_id, channel, register, scheduled_at, requires_manual_post, ...}`. If the list is empty, say "no posts due" and stop.

---

## Phase 2 - resolve bodies + run the dispatcher (draft-and-manual)

The post bodies live in the vault Content notes under `{vault.path}/70 Content/`, not in the ledger (the prose is kept out of the aggregate surface). For each due post, read the matching variant body from the Content note (`70 Content/<content_id>.md`, the per-channel variant block). Then run the dispatcher to apply the guardrails and build the reminder worklist:

```bash
python {config.factory.home}/orchestrator/post_dispatch.py --json   # if a CLI is wired
```

Or, if driving it inline, call `post_dispatch.dispatch_due_posts(led, calendar, now=..., resolve_body=<reads the vault note>, gate=<the content guardrails>)`. The dispatcher:

- runs each due post through the policy guardrails (per-channel cap, no-double-post, promotional-ratio); a blocked post emits `policy_blocked` and is dropped from the worklist;
- produces a `DraftReminder` for every channel (v2 is draft-and-manual, so nothing auto-posts and NO `distribution_intent` is written yet);
- flags community channels (`requires_manual_post`), which never had an auto path anyway.

---

## Phase 3 - present the worklist for the operator to paste

For each reminder, show the operator a clean block:

```
LinkedIn  (post)   ->  Post to your LinkedIn feed
---
<the humanized LinkedIn body>
```

Group by channel. Do NOT auto-post anything. The operator copies each body and posts it themselves on the platform.

---

## Phase 4 - record what was posted (the manual two-phase close)

After the operator confirms they posted a piece (and gives the post URL / id), record it so the piece moves to `posted` and drops out of the due list:

```bash
python {config.factory.home}/orchestrator/post_dispatch.py confirm \
  --content-id <id> --channel <channel> --post-id <platform post id> --body-hash <hash>
```

Or inline: `post_dispatch.confirm_manual_post(led, content_id=..., channel=..., post_id=..., body_hash=...)`. This writes the two-phase pair (`distribution_intent` + `distribution_confirmed`) at confirm time. The body_hash is the variant's `content.variant_body_hash(channel, body)`.

Later, the engagement pass (Scrapling-backed, opt-in) scrapes the post's like / reshare / comment counts and feeds the optimization report. If the operator never confirms a post, it simply stays "due" and the dispatcher reminds again next run; nothing is lost.

What you do NOT do: you never auto-post (no platform write of any kind), you never bypass a guardrail, and you never fabricate a post id. You hand the operator a clean, guardrail-checked worklist and record what they actually posted.
