# Postmortems

Every production incident in outreach-factory gets a written postmortem in this directory before the action items close. Filename: `YYYY-MM-DD-<slug>.md`. The 10-pillar plan's engineering practices section requires this — see `docs/PILLAR-PLAN.md` §3.

## Definition of "incident"

- A `send_confirmed` event for the wrong person (false positive).
- A `send_confirmed` event without a corresponding human-visible Gmail message (silent ledger lie).
- A reconcile pass that runs without errors but leaves the ledger inconsistent.
- A vault state that contradicts the ledger and can't be healed by Pass C.
- An OAuth / API outage that produces partial-send orphans surviving longer than reconcile freshness window.
- An unsubscribe request not honored within 60 seconds.
- An identity false-merge surfaced via human report.
- Any `manual_override` event triggered by an emergency (vs. a planned exception).
- Any LinkedIn / Gmail account suspension or warning.

Non-incidents (don't postmortem; just fix and commit):
- Test failures caught by CI.
- Bugs caught in dry-run / `--apply` simulation.
- Lint / type-check regressions.

## Template

```markdown
# Postmortem: <one-line title>

- **Date of incident:** YYYY-MM-DD
- **Date of postmortem:** YYYY-MM-DD (≤ 5 business days after)
- **Author:** <who wrote this>
- **Severity:** 1–5 (1 = catastrophic, see risk register scale)
- **Status:** Draft | Reviewed | Action items closed

## Summary

2–3 sentences. What happened, who/what was affected, what's the current state.

## Timeline (UTC)

- `HH:MM` — <event>
- `HH:MM` — <event>
- `HH:MM` — Detection: <how the incident surfaced>
- `HH:MM` — Mitigation: <first action that stopped the bleed>
- `HH:MM` — Resolution: <final fix in place>

## Root cause

The actual cause, not the proximate symptom. Cite ledger event IDs, commit hashes, policy rule names, code paths. If the root cause is "human error," that's not a root cause — keep going: why did the system allow the human to make that error?

## Contributing factors

Things that made the incident worse or harder to detect. Stale documentation. Missing test coverage. Alert that fired but went unread. Each factor links to a follow-up action item.

## What went well

Genuine. "We had backups" counts. "Reconcile caught the drift within 5 minutes" counts. Helps balance the audit against survivorship bias on what to change.

## Action items

| # | Item | Owner | Due | Status |
|---|---|---|---|---|
| 1 | <action> | <name> | YYYY-MM-DD | Open |

Action items live in this table until done. Closing the postmortem means **every action item is shipped**, not "we identified them."

## Links

- Risk register row, if this triggered an existing risk (or created a new one).
- ADR, if the resolution introduces a new architectural decision.
- Related commits / PRs.
- Customer / user communication, if applicable.
```

## Index

(Empty. First entry will go here when the first incident occurs. May this section stay short.)
