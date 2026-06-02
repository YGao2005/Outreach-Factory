# Scaffold menu - Riley Okafor (cold-pitch / email)

This is the Phase 3 output of `/draft-outreach`: the LLM proposes a menu of
options and never writes prose. (Pre-generated and committed so the CLI demo can
show this stage without an LLM call.)

### Channel and length
- Channel: email
- Word ceiling: 75 to 200 (cold-pitch)
- Subject required: yes

### Subject scaffolds
- S1: your post on the queue that lost tasks
- S2: the "queue was not the source of truth" line
- S3: retryable, and where the queue ends

### Hook scaffolds (each cites a dated public artifact)
- H1: [blog 2026-05-21] their own line, "we assumed the queue was the source of truth, it was not"
- H2: [github 2026-05-10] their `retryable` decorator, about 200 stars in a week
- H3: [talk 2026-04] their lightning talk on at-least-once delivery tradeoffs

### Context scaffolds (what you, Devon, are building)
- C1 plain: "a tiny Python library for typed background jobs with retries and no broker"
- C2 failure-mode: "built it after losing a weekend to jobs that silently stopped firing"

### Ask scaffolds (one ask)
- A1: "would you be up for a quick look?"
- A2: "curious whether the retry model holds up to your eye"

### Sign-off
- Full footer: Devon / Carillon / devon@carillon.example
