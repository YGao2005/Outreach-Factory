---
description: Source-to-distribution content drafter (the broadcast sibling of /draft-outreach). Given a configured SOURCE (a codebase whose feature ships are announce-worthy, or a new/high-ranked paper feed), surfaces candidates via salience, drafts ONE canonical source-of-truth piece, then projects it into register-aware per-channel variants (LinkedIn post / X post or thread / blog or newsletter essay / community draft). Each variant is humanized in a FRESH context window anchored to one reference example and taken verbatim; identical or truncated cross-posting is structurally refused. NO em dashes. Writes the Content note + the content_drafted / content_humanized ledger events. The review -> scheduled gate stays manual (auto_publish off). "Claude as CMO."
---

# /draft-content - source-to-distribution content drafter

> _Turn the operator's own work into audience content. Configurable input (a codebase ship, a hot paper) becomes ONE canonical source-of-truth piece, which branches into register-aware per-channel projections. Hub and spoke: review the story once, glance the projections. The humanizer runs PER spoke in a fresh context; the spine schedules + posts on the operator's gate._

This is the broadcast (1:many) sibling of `/draft-outreach`. It reuses the same scaffold -> assemble -> humanize-in-a-fresh-context pattern, the same anti-tell discipline, and the same absolute NO-em-dash rule. It differs in three ways: the input is a SOURCE (not a prospect), the output is ONE canonical piece plus per-channel projections (not one message), and per-channel adaptation is MANDATORY and structurally enforced.

See `docs/adr/0082-content-distribution-foundation.md` for the architecture and `.planning/SCOPING-content-distribution.md` for the scope.

---

## ⚙️ Pre-flight - load config

```bash
cat ~/.outreach-factory/config.yml
```

Read the `content:` block: `enabled`, `auto_publish` (keep off), `sources` (the typed registry), and `channels`. Throughout, `{config.X}` means substitute the loaded value. If `content.enabled` is false, tell the operator and stop (the surface is opt-in). The body voice reuses `{voice.reference_example_path}` and the draft-style memory (peer framing, plain, no marketing gloss).

The ledger + content helpers live in `orchestrator/content.py` and `orchestrator/content_scheduler.py`. Run helper snippets with the orchestrator dir on the path:

```bash
PYTHONPATH={config.factory.home}/orchestrator python3 - <<'PY'
import content as c
# ... use c.select_shipped_features / c.filter_papers / c.validate_adaptation / c.build_* ...
PY
```

---

## Phase 1 - pick a source + surface candidates (salience)

Take the `--source <id>` argument (or list enabled sources and ask). Resolve it from `content.sources`.

**A `codebase` source** (e.g. `sf-feature-ships`): read the commit range since the last post and keep only the announce-worthy ships. The salience selector is the load-bearing primitive - most commits are not content.

```bash
PYTHONPATH={config.factory.home}/orchestrator python3 - <<'PY'
import content as c
commits = c.git_commits_since(c.Path("{source.repo}"), "{source.since}")
for k in c.select_shipped_features(commits):
    print(k.sha[:8], "|", k.salience_reason, "|", k.subject)
PY
```

`shipped_feature` keeps release tags + conventional `feat:` commits; it drops chore / docs / test / ci / refactor / style / build / perf / fix / revert / unconventional noise. If nothing qualifies, say so and stop (do NOT manufacture a post from a chore commit).

**A `paper_feed` source** (e.g. `sf-top-papers`): pull new / high-ranked papers via the ScholarFeed MCP (the `scholar-feed` skill), or fall back to the public API:

```bash
curl -s -H "Authorization: Bearer $SF_KEY" \
  "https://api.scholarfeed.org/api/v1/public/papers/search?q={topic}&mode=semantic&sort=recent&days={max_age_days}&limit=25&verbose=true"
```

Then filter with `c.filter_papers(papers, min_rank=..., max_age_days=..., topics=(...), now=<now>)`. Keep the `llm_significance` as a HOOK candidate, but strip its promo language (it reads like marketing; you are writing a peer, not a brochure).

Present the candidates to the operator and let them pick ONE to draft. One source candidate becomes one content piece.

---

## Phase 2 - draft the CANONICAL (the substance, reviewed once)

Write ONE canonical piece: the long-form source of truth (the `essay` register). This is the substance - the claims, the story, the verifiable facts - in plain prose. It is what every channel projects from.

Rules for the canonical:
- Lead with the concrete thing that shipped / the concrete finding. A verbatim, verifiable fact (a feature name, a metric, an arXiv id), never a paraphrase.
- Peer voice. State what it does and why it matters. No "excited to announce", no "thrilled", no "game-changing", no "revolutionize".
- NO em dashes or en dashes anywhere (commas, periods, parentheses, spaced hyphens instead). This is Yang's #1 AI tell and a hard global rule.
- One idea, followed through. The canonical can be 150-400 words; it is the hub, not a tweet.

Show the canonical to the operator. This is the SUBSTANCE GATE: they edit the story here, once, before any projection happens.

---

## Phase 3 - project per channel (register-aware, NOT truncation)

For each channel in `{source.registers}` (or the operator's pick), produce a projection. A projection is a register-aware RE-EXPRESSION of the canonical's substance in that channel's voice and shape. It is NOT the canonical's first N characters.

| Register | Channels | Feel | Length | Norms |
|---|---|---|---|---|
| `essay` | blog, newsletter | the canonical itself, lightly framed | 150-400 words | a real title; a clear open; the operator's voice; no listicle filler |
| `post` | linkedin_post, x_post, reddit, hn, discord | one idea, one hook, plain | LinkedIn 50-120 words; X under 280 chars; community matches the sub's norm | LinkedIn: a hook line + the substance + an honest close, NO hashtag spam; X: one claim, lowercase-ok, no thread |
| `thread` | x_thread | a hook tweet + 2-5 substance tweets | each tweet under 280 chars | tweet 1 is the hook (the verifiable fact); the rest carry one point each; last tweet is a plain close, not a CTA blast |

Per-channel adaptation is MANDATORY. A LinkedIn post is not an X thread is not a blog post. Communities (reddit / hn / discord) get a DRAFT only - the system never auto-posts there; you produce the text + the target + a "paste this yourself" note.

---

## Phase 4 - humanize each projection in a FRESH SUBAGENT (not this context)

For EACH projection, spawn a SEPARATE fresh-context subagent (the Agent tool) to humanize it, and take its output verbatim. This is mandatory, not optional, and the vehicle matters: the context that assembled the canonical and the projections carries the assembler's register, so if YOU rewrite the prose here it stays faintly AI-sounding even after a self-edit. A subagent that never saw the fact-assembly rewrites purely for voice. (Dogfood finding 2026-06-04: an inline rewrite left negative parallelism + a "shipped X this week" opener that a fresh subagent removed cleanly.) Do NOT re-edit the subagent's output in your own voice. One subagent per spoke; launch them in one message so they run concurrently.

Run each humanizer subagent on the configured cheap model: pass `model: {config.models.humanizer}` (default `haiku`) on the Agent call. The de-AI rewrite is a focused, mechanical pass and does not need a frontier model; the cost posture lives in the `models:` config block. Bump it to `sonnet` only if a pass reads thin.

Subagent prompt (substitute the channel's register + the draft):

```
You are a humanizer. Rewrite the draft below so it reads like a real working
engineer posted it as a {register} for {channel}. You did NOT write this draft and
have no attachment to its phrasing; rewrite freely for voice while preserving every
fact, name, and number. Add no new facts.

Hard rules:
- NO em dashes or en dashes anywhere. Commas, periods, or parentheses instead.
- Kill AI tells: negative parallelism ("it is not that X, it is Y" / "not just X,
  it's Y"); self-narrating framing ("the interesting part is", "the trick is");
  rule-of-three lists; and any "shipped X this week" announcement-bait opener.
- Plain peer voice, a little terse is good. No marketing gloss, no "excited", no
  hashtags, no emoji. Lowercase is fine for X.
- {length constraint for this channel, e.g. "under 280 characters, count them"}.
- Restructure sentences completely if it helps; do not mirror the draft's shapes.

Output ONLY the rewritten text. No preamble, no quotation marks, no commentary.

--- REFERENCE EXAMPLE ({register}, human-written), if {voice.reference_example_path} has one ---
[a register-matched example]

--- DRAFT TO REWRITE ---
[the Phase 3 projection for this channel]
```

The subagents run inside the Claude Code session (subscription-billed, not API-billed). If you have no human-written reference example for this register yet, the voice instructions above are enough; adding real content-register reference examples is a worthwhile later anchor. Do NOT use the inline `/humanizer` skill as a substitute here: it shares this context and so leaks the same register the fresh subagent is meant to escape.

---

## Phase 5 - validate adaptation + anti-tell, then refuse on failure

Run the STRUCTURAL adaptation refusal. Identical or mechanically-truncated cross-posting is forbidden and is the fastest way to read as a cross-post bot:

```bash
PYTHONPATH={config.factory.home}/orchestrator python3 - <<'PY'
import content as c
piece = c.ContentPiece(content_id="<cid>", source_ref="<ref>", topic="<topic>",
    canonical="""<canonical>""",
    variants=(
        c.ContentVariant("linkedin_post", "post", """<linkedin body>"""),
        c.ContentVariant("x_post", "post", """<x body>"""),
    ))
c.validate_adaptation(piece)   # raises ValueError on identical / truncated / empty
print("adaptation OK")
PY
```

If it raises, re-draft the offending variant (do NOT ship it). Then run the anti-tell pass per variant: no em or en dashes (scan for the U+2014 / U+2013 glyphs), no "delve / leverage / tapestry / vibrant / pivotal", no rule-of-three filler, no negative parallelism ("not just X, it's Y"), no hashtag spam, no fake urgency.

---

## Phase 6 - persist (Content note + ledger events)

Write the Content note under `{vault.path}/70 Content/` (frontmatter: `type: content`, `id`, `source_ref`, `topic`, `pipeline_stage: humanized`, a per-channel variant block each with `channel`, `register`, `scheduled_at: ""`, `body`), then append the lifecycle events:

```bash
PYTHONPATH={config.factory.home}/orchestrator python3 - <<'PY'
import content as c, ledger as L
led = L.Ledger()
cid = "<cid>"   # the c.new_content_id() you generated
led.append({**c.build_content_drafted_payload(content_id=cid, source_ref="<ref>", topic="<topic>"), "type": "content_drafted"})
led.append({**c.build_content_humanized_payload(content_id=cid), "type": "content_humanized"})
print("wrote drafted + humanized for", cid)
PY
```

STOP here. The review -> scheduled step is the operator's MANUAL gate (`auto_publish` is off). The operator reviews each variant, sets its `scheduled_at`, and approves it (the `content_review_approved` event, written when they flip the variant). Only then does `orchestrator/content_scheduler.py` surface it as due, and only then (Phase 2 of the milestone) does the dispatcher post it.

What you do NOT do here: you do not post, you do not approve, you do not auto-schedule, and you never auto-post to a community. You draft, you humanize per spoke, you refuse a bad cross-post, and you hand a reviewable piece to the operator.
