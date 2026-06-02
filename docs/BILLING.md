# Billing — read this before scaling

The factory is designed to run entirely on the Claude Max (or Pro) subscription. There are paths in this codebase that, if wired wrong, will silently charge your Anthropic API account instead. Know the matrix.

## TL;DR

| Path | Billing | Use? |
|---|---|---|
| Claude Code session + Agent-tool subagents | ✅ Subscription | ✅ YES — this is the factory's main runtime |
| `/schedule` routines (Anthropic-hosted cron) | ✅ Subscription | ✅ YES — for background discovery |
| `orchestrator/voice_retrieve.py` | ✅ Subscription (no API call) | ✅ YES — local retrieval only |
| `claude -p "..."` subprocess | ⚠ DEPENDS | Caution — see below |
| Anthropic SDK direct (`from anthropic import Anthropic`) | ❌ API per-token | ❌ NO |
| Claude Agent SDK (`@anthropic-ai/claude-agent-sdk`) | ❌ API per-token (separate credit pool post-June-2026) | ❌ NO |

## The subprocess env trap

If your orchestrator shells out to `claude -p`, the subprocess inherits the parent's env. If `ANTHROPIC_API_KEY` is in your shell env, the subprocess will silently use API billing instead of subscription.

Real-world incident: someone got a $1,800 surprise API bill from this pattern.

**The fix** in Python:

```python
import os
import subprocess

clean_env = {**os.environ, "ANTHROPIC_API_KEY": ""}
# or: clean_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

result = subprocess.run(
    ["claude", "-p", "your prompt"],
    env=clean_env,
    capture_output=True,
)
```

When `ANTHROPIC_API_KEY` is empty/unset in the subprocess env, `claude -p` falls back to the Claude Code subscription auth.

## Why the voice translator was split

The original `voice_translate.py` did embedding retrieval + Sonnet rewrite as one Python script via the Anthropic SDK. That second step was API-billed per token. The split moved retrieval to `voice_retrieve.py` (CPU-only, $0) and the rewrite to the Claude Code agent's own LLM call (subscription-billed).

## Max plan usage cap

Claude Max has a 5-hour rolling message window, reportedly ~5× Pro's quota (~200-225 messages per 5-hour window). At ~5-10 LLM calls per prospect end-to-end, the factory at full tilt = ~25-40 prospects per window.

If you spawn many parallel subagents, you'll saturate this window quickly. Discovery runs should be paced.

## How to verify a session is on subscription

1. Check Anthropic Console usage dashboard before vs after a run
2. Grep your code for `from anthropic import` or `import anthropic` — those are SDK imports = API billing
3. Grep for `ANTHROPIC_API_KEY` — if a script reads it, it's probably API-billed
4. When in doubt: set `ANTHROPIC_API_KEY=` (empty) in the script's env and re-run. If still works → subscription. If errors → API.
