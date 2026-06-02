## What this changes

## Why

## Checklist
- [ ] `python3 tests/golden_path/gate.py --full` passes locally
- [ ] New behavior has a test (or a fixed xfail had its marker removed so it becomes a permanent regression barrier)
- [ ] No em dashes or en dashes in added text (the project bans them; see CONTRIBUTING.md)
- [ ] No secrets, credentials, or real recipient data in the diff
- [ ] If a governed constant changed, its governing ADR changed in the same PR (the cochange-discipline CI job enforces this)
