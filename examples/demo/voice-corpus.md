# Demo voice corpus for the Outreach Factory `--demo` path

These are FAKE example emails written in the voice of "Devon", the demo sender
(a developer shipping a small open-source library called Carillon). In a real
install your corpus is built from YOUR own sent mail and embedded with a local
model; see [voice/README.md](../../voice/README.md).

The demo deliberately uses NO machine learning. With a corpus this small,
ranking exemplars by similarity would be theater, and forcing a large model
download would defeat a zero-setup demo. The agent reads these directly to
ground the Phase 4 rewrite, and the CLI prints them as the voice reference.

This file is intentionally plain markdown (not the real `index.json` format) so
the `bin/outreach-factory demo` walkthrough parses it with the standard library
alone, no third-party packages. Each exemplar is one `##` block. The header line
is `id | register | channel | date`; an optional `Subject:` line follows; the
rest is the body.

What to notice across these: a specific opener, a plain wedge, a single ask, an
honest vulnerable note, a plain sign-off, and no em dashes anywhere.

## ex-001 | cold-pitch | email | 2026-02-11
Subject: your post on flaky cron jobs

Hi Priya,

Your writeup on the cron jobs that silently stopped firing hit close to home. I
lost a weekend to the same thing last month.

I have been building a small Python library called Carillon that runs typed
background jobs with retries and no broker. It is open source and early, so I am
mostly trying to find out where it breaks for other people.

Would you be up for a quick look? No worries if not.

Devon

## ex-002 | cold-pitch | email | 2026-02-19
Subject: the durability section in your paper

Hi Dr. Lin,

I read your paper on exactly-once delivery while trying to work out why my own
job runner double-fired under load. The section on idempotency keys is the part
I keep rereading.

I am building an open-source library that leans on that idea for background jobs
in Python. Still early and a bit rough.

Curious whether the approach holds up to your eye. Happy to send the design doc
if it is useful.

Devon

## ex-003 | congrats | linkedin-dm | 2026-03-02
Congrats on the launch, Marco! Letting people self-host from day one was the
right call, and it took some guts to ship it that way.

Devon

## ex-004 | re-engagement | email | 2026-03-20
Subject: picking this back up

Hi Sam,

We traded notes back in January about background jobs, and then I went quiet
while I rewrote the retry logic. That part is finally stable.

If you are still wrestling with the queue thing, I would love to hear how it
went. If you moved on, all good.

Devon

## ex-005 | reply | email | 2026-04-04
That makes sense, and you are right that the docs gloss over the at-least-once
case. I will fix that this week.

On your other question: yes, you can pin a job to a single worker. There is a
flag for it, it is just badly named. I will rename it.

Thanks for the careful read.

Devon

## ex-006 | cold-pitch | email | 2026-04-22
Subject: saw your talk on queue backpressure

Hi Aisha,

Your talk on backpressure finally made the topic click for me, especially the
part about dropping the oldest work instead of the newest.

I am building a small open-source job library and I think I got that exact
tradeoff backwards. Trying to fix it now.

Would you be open to a few questions when you have a minute?

Devon
