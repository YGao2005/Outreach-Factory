# Final draft - Riley Okafor (cold-pitch / email)

This is what the factory produces. The agent assembles one option per scaffold
dimension (Phase 3.5), then the humanizer rewrites it inline against the
anti-tell checklist, using a human-written reference touch for tone (Phase 4-5).

It is committed here so the CLI demo can show a complete result with no LLM call.
To generate a fresh one live, run `/draft-outreach --demo` inside Claude Code.

---

Subject: the "queue was not the source of truth" line

Hi Riley,

Your postmortem on the jobs that kept vanishing under deploy restarts is the one
I keep sending to people. The bit about assuming the queue was the source of
truth and finding out it was not is exactly the hole I fell into.

I have been building a small Python library called Carillon that runs typed
background jobs with retries and no broker. I started it after losing a weekend
to jobs that silently stopped firing, so your writeup felt a little personal.

It is open source and still early. Would you be up for a quick look at whether
the retry model holds up to your eye? No stress if you are heads down.

Devon
Carillon
devon@carillon.example

---

Why this reads human, against the checklist:
- Specific opener tied to a dated public artifact (their postmortem), not a
  homepage tagline.
- No superlatives, no "I came across", no manufactured enthusiasm.
- No rule-of-three list, no em dashes.
- One honest vulnerable note ("felt a little personal", "still early").
- A single, low-key ask.
