---
name: dispatch-outreach
version: 1.0.0
description: |
  Orchestrate the outreach pipeline. Scans Person notes for the `pipeline_stage:`
  frontmatter field, picks prospects ready to advance, and spawns fresh-context
  Agent-tool subagents in parallel - each one runs the appropriate stage skill
  (research → draft → send). Subscription-billed via the Claude Code session.
  Use when you want to advance the pipeline in batch.
  Stages: queued → researched → drafted → ready → sent.
license: MIT
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - Glob
  - AskUserQuestion
  - Agent
---

# /dispatch-outreach - Advance the pipeline in parallel

You orchestrate the outreach factory. Your job: find prospects with `pipeline_stage:` set in vault frontmatter, advance them through the state machine by spawning **fresh-context Agent-tool subagents** that run the appropriate stage skill, then write the new stage back to the Person note.

This is the headline factory loop. Everything else in the repo is a building block called by this skill.

---

## ⚙️ Pre-flight - load config

**Before doing anything else, read the user's config:**

```bash
cat ~/.outreach-factory/config.yml
```

The orchestrator Python helpers live at:
- `{config.factory.home}/orchestrator/state_machine.py` - pipeline logic + vault scan
- `{config.factory.home}/orchestrator/locks.py` - marker-file locking

**If `~/.outreach-factory/config.yml` does not exist**: abort and tell the user to copy `config-template/config.example.yml` from the outreach-factory repo to `~/.outreach-factory/config.yml`.

---

## State machine (single source of truth)

```
queued → researched → drafted → ready → sent
```

| From       | To         | Skill              | Automated? |
|------------|------------|--------------------|------------|
| queued     | researched | /research-prospect | ✅ yes |
| researched | drafted    | /draft-outreach    | ✅ yes |
| drafted    | ready      | (user review)      | ⏸ NO - manual gate |
| ready      | sent       | /send-outreach     | ✅ yes |
| sent       | -          | terminal           | - |

Only automated transitions are eligible for dispatch. `drafted → ready` is a manual gate - the operator reviews the draft and flips `pipeline_stage:` to `ready` himself.

`pipeline_stage:` is the orchestrator's field. It is **distinct from `status:`** (CRM lifecycle, owned by `/send-outreach` and manual edits). Do not touch `status:` from this skill.

---

## Usage

```
/dispatch-outreach                    # interactive: scan, plan, confirm, dispatch
/dispatch-outreach --status           # show pipeline counts per stage, exit
/dispatch-outreach --max 3            # cap parallel subagents (default 3)
/dispatch-outreach --stage queued     # only advance prospects in this stage
/dispatch-outreach --dry-run          # show plan only, don't dispatch
/dispatch-outreach --clean-locks      # release stale locks (>30 min old), exit
/dispatch-outreach --enroll <name>    # set pipeline_stage: queued on one note, exit
```

---

## Phase 1 - Scan + status

**Auto-release stale locks first.** Always - at the start of every dispatch (before scanning, status, or planning):

```bash
python {config.factory.home}/orchestrator/locks.py clean-stale --max-age-min 30 --json
```

The output is `{"cleaned": [<lock paths>], "count": N}`. If `count > 0`, log `Released N stale lock(s) (>30 min old).` to the user as the first line of output so they know cleanup happened. If `count == 0`, stay quiet - no need to mention.

Skip this auto-cleanup ONLY when the user invoked `--clean-locks` explicitly (then the utility-only path below handles it and exits).

Run the Python scanner:

```bash
python {config.factory.home}/orchestrator/state_machine.py status
```

Show the per-stage counts to the user. If `--status`, stop here.

Then list eligible (automated-only) prospects:

```bash
python {config.factory.home}/orchestrator/state_machine.py list-eligible --automated-only --json
```

The JSON output is an array of objects with `note_path`, `name`, `current_stage`, `target_stage`, `skill`, `automated`, `pipeline_error`. Filter further if the user passed `--stage <X>`.

If a prospect already has `pipeline_error:` set, surface it in the listing and ask the user whether to retry or skip it.

---

## Phase 2 - Plan + confirm

Show the user the dispatch plan in this shape:

```
Plan (concurrency cap: 3):
  1. Sai Gurrapu      queued     → researched   (/research-prospect)
  2. Alex Liu         queued     → researched   (/research-prospect)
  3. Ian McInnis      researched → drafted      (/draft-outreach)

⏸ Manual gate (review these drafts and flip pipeline_stage to `ready`):
  - Pranjali Awasthi  drafted
  - Gaurav Malhotra   drafted

Estimated message-window cost: ~60-120 Claude calls (Max window: ~200-225 per 5h).
```

Use `AskUserQuestion` to confirm: "Dispatch these N prospects? (yes / no / change concurrency)". If `--dry-run`, stop after showing the plan.

If the user-implied cost exceeds half their window, warn explicitly.

---

## Phase 3 - Acquire locks

For each prospect chosen in Phase 2, acquire a lock:

```bash
python {config.factory.home}/orchestrator/locks.py acquire \
  --prospect "Sai Gurrapu" \
  --stage "researching"
```

The output is `{"ok": true/false, "agent_id": "...", "message": "..."}`. If `ok: false`, skip that prospect (another dispatch is already running on it) and note it in the final summary. Record the returned `agent_id` for each acquired lock.

---

## Phase 4 - Dispatch (parallel Agent-tool subagents)

For each prospect with a held lock, spawn ONE Agent-tool subagent. **Put every Agent call in a single message so they run concurrently.**

Per subagent:
- `subagent_type`: `general-purpose`
- `description`: `"Advance <name>: <current> → <target>"`
- `prompt`: see template below

Subagent prompt template (substitute `<...>` placeholders):

```
You are a single-prospect worker in the outreach-factory dispatcher.

PROSPECT: <name>
PERSON NOTE: <note_path>
TASK: Run /<skill> on this prospect end-to-end.

Rules:
1. You have a FRESH context. The skill's body is your instructions. Read
   ~/.outreach-factory/config.yml for config, then invoke the skill normally.
2. Do NOT modify the `pipeline_stage:` frontmatter field. The dispatcher will
   write it back when you finish.
3. Do NOT spawn further subagents. Do the work yourself in this context.
4. If you cannot proceed (missing data, blocked tool, ambiguous prospect),
   exit early. The FIRST line of your response MUST be exactly
   `BLOCKED: <one-line reason>` - no other prefix is accepted, no leading
   prose, no markdown. The dispatcher parses this strictly to record
   `pipeline_error:` on the note.
5. On success, return a short (≤200 word) summary of what you did. Be terse.

Begin.
```

Wait for all subagents to return.

---

## Phase 5 - Write back state + release locks

For each subagent result, before any `Edit`:

### 5a. Re-locate the Person note (handles mid-flight file moves)

`/send-outreach` (and any future stage skill that reorganizes the vault) may move
the note from `{vault.queue_subdir}/` → `{vault.active_subdir}/` mid-flight.
The pre-dispatch `note_path` cached in Phase 1 can therefore be stale by the
time the subagent returns. Always re-locate before editing:

```bash
python {config.factory.home}/orchestrator/state_machine.py find-person-note \
  --name "Sai Gurrapu" --json
```

Output is `{"ok": true/false, "name": "...", "path": "/abs/path or null"}`. Use
the returned `path` for the `Edit` below - NOT the cached one. If `ok: false`,
log a warning (`could not re-locate Person note for <name> - leaving stage
unchanged`) and skip the writeback for this prospect (still release the lock
in 5d). The note may have been deleted or renamed beyond recovery; surfacing
the miss is better than guessing.

### 5b. Classify the subagent return

Parse the subagent's response text using the strict contract from the Phase 4
prompt template:

- **BLOCKED**: the FIRST non-empty line of the response begins with `BLOCKED:`.
  Extract the reason (everything after the prefix on that line, trimmed,
  ≤200 chars).
- **SUCCESS**: anything else (the subagent returned a normal summary).

Strict prefix matching is intentional - a loose match risks false-classifying
a real failure as success and silently advancing `pipeline_stage`. If a
subagent ad-libbed an error report without the prefix, treat it as SUCCESS
and let the next dispatch cycle re-detect via the downstream skill failing
again. (Yes, this is a defensible silent failure - better than silently
ADVANCING a broken prospect.)

### 5c. Edit the Person note frontmatter

**Read the freshly re-located note FIRST** (`Read` tool on the path returned
in 5a), then construct the Edit payloads from that fresh read. Do NOT cache
an earlier read of the same path - a stage skill may have rewritten it
mid-flight. The `Edit` tool requires exact-match `old_string`, so reading
the current contents is mandatory.

Use the `Edit` tool against the path returned in 5a.

**On SUCCESS**:

- Change `pipeline_stage: <current>` → `pipeline_stage: <target>`.
- Add or update `pipeline_advanced_at: <ISO-8601 UTC timestamp>`. If the line
  is absent, insert it on the line after `pipeline_stage:`. If present,
  Edit the old timestamp value to the new one.
- If `pipeline_error:` and `pipeline_error_at:` were present from a prior
  failed run, remove BOTH lines via Edit. If they're absent, this step is a
  no-op - do nothing. Do not Edit with an empty `old_string`.

**On BLOCKED**: leave `pipeline_stage:` unchanged. Two cases:

- If `pipeline_error:` already exists in frontmatter (prior failed run):
  Edit it to the new reason from 5b, AND Edit `pipeline_error_at:` to the
  new timestamp. Use exact-match `old_string` from the fresh read.
- If `pipeline_error:` is absent: insert two new lines on the line
  immediately after `pipeline_stage:`:

  ```yaml
  pipeline_error: <one-line reason from 5b>
  pipeline_error_at: <ISO-8601 UTC timestamp>
  ```

The next dispatch run picks these up via the JSON output of `state_machine.py
list-eligible` (the `pipeline_error` field) and surfaces them to the user as
the "needs retry" set.

### 5d. Release the lock

```bash
python {config.factory.home}/orchestrator/locks.py release --prospect "Sai Gurrapu"
```

Always release the lock, even on failure or when 5a couldn't re-locate the note.

---

## Phase 6 - Summary

Report to the user:

```
Dispatched N prospects:
  ✅ K succeeded → advanced to <target_stage>
  ❌ F failed    → see pipeline_error: on those notes
  ⏭  S skipped   → already locked by another dispatch

Time elapsed: Xm Ys.
```

If there are still eligible prospects (the cap kept us from running them all), offer to re-run.

---

## --clean-locks (utility)

```bash
python {config.factory.home}/orchestrator/locks.py clean-stale --max-age-min 30
```

Report N locks released. Use when a previous dispatch crashed and left locks behind.

---

## --enroll <name> (legacy single-prospect utility)

> **Naming note:** this `--enroll <name>` is the LEGACY one-prospect utility for
> promoting an existing hand-written Person note onto the pipeline. It is
> NOT the same as the new batch `--enroll` flag on the discovery skills
> (`/find-leads --enroll`, `/find-funded-founders --enroll`,
> `/competitor-customers --enroll`), which CREATE Person stubs from discovery
> rows via `orchestrator/enrollment.py`. Both use the word "enroll" but mean
> different things; use the discovery-skill variant when you can.

This legacy path is for the case where a Person note already exists in the
vault (perhaps a manual edit or a stub written by some other tool) and just
needs the orchestrator field flipped on:

1. Read the Person note at `{vault.path}/{vault.people_dir}/.../<name>.md` (search the queue + active subdirs).
2. If the frontmatter already has `pipeline_stage:`, refuse and tell the user the current stage.
3. Otherwise, insert `pipeline_stage: queued` into the frontmatter (after `status:` is fine).
4. Confirm with the user: "Enrolled <name> at `pipeline_stage: queued`."

---

## How a prospect EXITS the pipeline

When `pipeline_stage: sent`, the note is terminal for this round UNLESS follow-ups are enabled (see below). Reply handling is manual (the operator reads the inbox, decides per-prospect). If the operator wants to re-engage outside the cadence, they flip the stage manually to whatever's appropriate for the next round.

---

## Follow-ups (a deterministic business-day cadence after `sent`)

When `followup.enabled: true` in config, a `sent` prospect who has not replied is not terminal: the cadence engine sequences them through touch 2, then touch 3, on a business-day schedule. The engine (`orchestrator/followup.py`) decides WHO is due for WHICH follow-up touch by READING the ledger. It is deterministic and read-only. It NEVER sends and NEVER bypasses a gate. Your job is to turn its worklist into drafts, keep the manual review gate, and let `/send-outreach` do the gated send.

**Step 1 - get the due-now worklist (the source of truth for who to follow up):**

```bash
python {config.factory.home}/orchestrator/followup.py --json
```

Output: `{"enabled": true, "max_touches": 3, "due": [{"person_id", "next_step", "touch_no", "last_touch_ts", "last_touch_intent_id", "register"}, ...]}`. Each entry is a person genuinely due RIGHT NOW (delay elapsed, under `max_touches`, and no reply / unsubscribe / bounce since the last touch). If `enabled` is false, follow-ups are off: skip this whole section.

Do NOT re-implement "who replied" or "how long since the last touch" yourself. The engine re-derives all of it from the ledger every run; a prospect who replied between touches simply will not appear in `due`.

**Step 2 - draft each due follow-up (re-engagement register, the right step):**

For each due person, spawn a `/draft-outreach` subagent with `--register re-engagement --followup-step <next_step>` (1 = touch 2 short bump, 2 = touch 3 breakup). Resolve the person's note the same way the other stages do. The subagent saves the Touch note and sets `pipeline_stage: followup_<next_step>_drafted`.

**Step 3 - the MANUAL review gate (do not auto-advance):**

`followup_<N>_drafted → followup_<N>_ready` is a manual gate, exactly like `drafted → ready`. The operator reviews the bump / breakup and flips the stage to `followup_<N>_ready` himself. Never auto-advance this transition. (`followup.auto_send: false` is the default and this skill honors it; an opt-in auto-send is a separate, later step.)

**Step 4 - send (still fully gated):**

A `followup_<N>_ready` prospect is sent by `/send-outreach`, which advances the stage to `followup_<N>_sent`. The follow-up is STILL a send: it passes suppression + cooldown + the daily cap + the warming ceiling at send time, exactly like a first touch. The send path itself re-confirms with the cadence engine that the person is genuinely due before letting a second touch past the duplicate-send guard, so a follow-up can never go out to someone who opted out, even if a stale draft is left around.

**Stages (the follow-up extension of the state machine):**

```
sent → followup_1_drafted → followup_1_ready → followup_1_sent
     → followup_2_drafted → followup_2_ready → followup_2_sent   (terminal at max_touches)
```

| From                | To                  | Skill              | Automated? |
|---------------------|---------------------|--------------------|------------|
| sent (+ due)        | followup_1_drafted  | /draft-outreach    | ✅ yes (when due) |
| followup_1_drafted  | followup_1_ready    | (user review)      | ⏸ NO - manual gate |
| followup_1_ready    | followup_1_sent     | /send-outreach     | ✅ yes |
| followup_1_sent (+ due) | followup_2_drafted | /draft-outreach | ✅ yes (when due) |
| followup_2_drafted  | followup_2_ready    | (user review)      | ⏸ NO - manual gate |
| followup_2_ready    | followup_2_sent     | /send-outreach     | ✅ yes |

`--status` should also surface the follow-up due count (or run `outreach-factory status`, which prints "FOLLOW-UPS  due now N" + the per-touch send counts).

---

## Subscription billing - non-negotiable

This skill uses the **Agent tool only** for spawning subagents. Agent-tool subagents inherit the Claude Code session's subscription billing.

❌ Do NOT shell out to `claude -p` subprocess from this skill.
❌ Do NOT call the Anthropic SDK or API directly.
❌ Do NOT import `anthropic` from any new helper.

If a user asks for unattended overnight runs, that is a future `dispatcher.py` Python entry-point - a separate file with its own subprocess discipline (must unset `ANTHROPIC_API_KEY` per `docs/BILLING.md`). Don't build it from inside this skill body.

---

## Anti-patterns

- ❌ Modifying `status:` field. That's CRM lifecycle, owned by `/send-outreach`.
- ❌ Running more than `--max` concurrent subagents. Burns the message window.
- ❌ Skipping the lock step. Two dispatches on one prospect = corrupted state.
- ❌ Auto-advancing `drafted → ready`. That's the user's review gate.
- ❌ Treating `pipeline_error:` as fatal. Surface it; ask the user to retry or skip.
- ❌ Telling the subagent to update `pipeline_stage:` itself. The dispatcher is the single writer.

---

## Sanity checks before dispatch

- Vault path resolves (`{vault.path}` exists)
- Config has `factory.home` set (Python scripts loadable)
- Each chosen prospect's `note_path` exists and parses as valid frontmatter
- No prospect appears twice in the dispatch list
- `--max` is between 1 and 10 (sanity bound on concurrency)
