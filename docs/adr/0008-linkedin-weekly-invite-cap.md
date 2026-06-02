# ADR-0008: LinkedIn weekly invite cap migration from hardcoded constant to policy rule

- **Status:** Accepted
- **Date:** 2026-05-19
- **Pillar:** A (Policy engine — exit-gate cleanup; "zero hardcoded policy in skills")
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0001 established the policy engine; ADR-0002 / 0003 / 0004 / 0005 / 0006 / 0007 shipped the six concrete rule classes (cooldown / cross-channel / suppression / sending-window / budget / tier). The PILLAR-PLAN §2 Pillar A exit criterion contains a load-bearing line: *"zero hardcoded policy in skills."* As of commit `50711a5` (end of Week 5) one violation remained: `skills/send-outreach/scripts/send_queued.py:77` defines `LINKEDIN_WEEKLY_SOFT_LIMIT = LINKEDIN_WEEKLY_INVITE_LIMIT` (read from `config.py`, defaulting to 100), and lines 119–127 use that constant to print a pre-send warning when the planned LinkedIn invites would exceed the soft cap.

The constant is a soft warning, not a gate — the skill prints `"⚠ Planned LinkedIn invites (N) would EXCEED weekly budget by M"` but does not refuse the send. The actual gate decision (whether the LinkedIn invite is OK to send) is delegated to Claude, who consumes the manifest emitted by `_emit_linkedin_manifest` and calls `mcp__linkedin__connect_with_person` per entry. There is no enforcement layer between Claude's MCP invocation and LinkedIn's API; the hardcoded threshold is operationally a hope-not-process.

Three concerns this ADR resolves:

1. **The PILLAR-PLAN exit criterion is partially honored.** Email sends are fully policy-gated (ADR-0001 wired `gated_send_one`). LinkedIn invites are not. The exit criterion's "zero hardcoded policy in skills" doesn't pre-resolve as "email only"; the constant in `send_queued.py` is a counter-example that must be migrated before Pillar A can be declared stable. Operators considering whether to trust the policy engine as the single gate need every gate-shaped decision in policy YAML, not split across YAML + Python constants in skill scripts.

2. **The 100/week cap's blast radius is large.** Personal LinkedIn accounts that exceed the soft cap risk being throttled (cooldown applied to invite-send for days) or, in repeat-offender cases, restricted (the account loses the invite-send surface entirely). Losing the LinkedIn channel for the outreach pipeline is a higher-cost incident than losing one cold-pitch send. The asymmetric-failure-cost principle (PILLAR-PLAN §0) compels: this cap deserves first-class enforcement, not a soft warning.

3. **Pillar C needs a clean handoff target.** Pillar C lands `li_invite_intent` + `li_invite_confirmed` two-phase events; the moment those exist, the LinkedIn-invite path becomes structurally identical to the email-send path (`gated_send_one`-shaped). If the cap is in policy YAML before Pillar C lands, Pillar C inherits the rule — Pillar C just wires the events the rule queries. If the cap stays hardcoded, Pillar C inherits a constant whose meaning has to be re-thought and re-implemented as a rule then; the cleanup gets deferred to Pillar C's already-busy week range.

The transitional period (Pillar A end → Pillar C start) creates an awkwardness: LinkedIn invites are still operator-mediated via the LinkedIn MCP, so the `cost_incurred` ledger event that the rule reads must be appended by Claude after each successful MCP call. This is hope-not-process for one week range, but the alternative (leave the hardcoded constant) leaves Pillar A exit unmet. See §Decision item "Transitional emit site" below.

Risks this ADR mitigates by design: existing risk register row **R009 (LinkedIn account suspension)** — specifically the "weekly invite cap already in place (skill-level); migrate to Pillar A budget rule" sub-bullet of R009's mitigation plan. This ADR closes that sub-bullet; the rest of R009's mitigation plan (randomized timing, per-account warming) remains open work for Pillar C / Pillar H. The "operator bypass of a soft warning" aspect that previously existed (the hardcoded constant only printed a warning, didn't refuse) is closed structurally by promoting the threshold to a `Block` verdict.

## Decision

### Migrate the cap to a `budget.window-cap` rule

Add the following commented-out factory rule to `config-template/cooldowns.example.yml`:

```yaml
- name: linkedin-weekly-invite-cap
  type: budget.window-cap
  block_when:
    channel: linkedin
  source: linkedin
  window_days: 7
  max_units: 100
  reason: "LinkedIn weekly invite cap (100/wk soft limit per LinkedIn personal-account terms)"
```

`budget.window-cap` already supports the `max_units` mode (ADR-0006 §Decision); units-mode with `source: linkedin` is the structurally exact shape for a quota-only cap. No new rule class required; no engine change required; one YAML entry.

The rule is commented out by default per the asymmetric-failure-cost principle: operators on the OSS install with no LinkedIn outreach should not see policy refusals their use case doesn't motivate. The cap is documented in the example file with a one-paragraph explanation of why it exists; operators who use LinkedIn uncomment + adjust per their tolerance.

### Transitional cost emit site (Pillar A → Pillar C handoff)

Until Pillar C lands `li_invite_intent` / `li_invite_confirmed`, LinkedIn invites are not two-phase. The skill emits a manifest (`_emit_linkedin_manifest` in `send_queued.py`), prints handoff instructions for Claude, and Claude calls `mcp__linkedin__connect_with_person` per entry. There is no Python-side success callback into which a `cost_incurred` event can be appended automatically.

The transitional contract:

* The skill's printed handoff (in `_emit_linkedin_manifest`) gains a new step: *"4. Append a `cost_incurred` ledger event after each successful invite: `python -m orchestrator.ledger append '{...}'` with `source=linkedin`, `units=1`, `amount_usd=0.0`."*
* Each successful MCP invite must be followed by this append. The policy engine's `linkedin-weekly-invite-cap` rule reads these events to evaluate the 7-day window cap. If Claude forgets the append, the rule under-reports and allows over-quota sends — same failure mode the constant warning had, except now the gate is missed silently rather than warned-noisily.
* This is hope-not-process for one Pillar C week range. The risk register row R013 carries this explicitly: "transitional emit until Pillar C lands two-phase."

When Pillar C ships, the emit site moves from the operator-instructed manual append to the post-confirm hook in the LinkedIn two-phase handler (the same shape as `send_queued.gated_send_one`'s gmail cost emit). The rule itself does not change; only the emit site moves from human-typed to machine-emitted.

### The hardcoded `_print_preview` warning stays as cosmetic display

`send_queued.py:_print_preview` lines 119–127 print a tally and a budget-remaining count to the operator's terminal. This is informational — the operator sees "you've used 45 of 100" and can plan accordingly. It is NOT a gate; the policy engine is the gate.

The cosmetic tally is allowed to keep the hardcoded `LINKEDIN_WEEKLY_SOFT_LIMIT` constant for now. Justification:

* Display values aren't policy decisions. The cap value the policy engine enforces could theoretically diverge from the cosmetic value the preview displays — but for the OSS default (both = 100), there is no observable divergence.
* Refactoring the preview to read from policy YAML adds engine-coupling to the preview code path with no operator-visible win.
* A future enhancement could replace the preview with a `python -m orchestrator.policy simulate --batch` invocation that reads the YAML and shows "policy rule N would fire on M of these invites" — but that's quality-of-life, not blocking.

ADR-0008 explicitly does NOT require the preview to consume policy YAML. The Pillar A exit criterion is about the GATE, not the display.

### The factory rule ships commented out (consistent with all other budget rules)

ADR-0006 §Migration / rollout established the convention: budget rules in `cooldowns.example.yml` ship commented-out by default. Operators opt in by uncommenting. The LinkedIn cap follows the same convention.

Counter-argument: the LinkedIn cap's failure mode (account suspension) is severe enough to ship enabled-by-default. **Rejected.** Operators with no LinkedIn outreach (a sizable subset of the OSS user base) should not get refusals from a rule whose preconditions (LinkedIn MCP configured, invites being sent) they don't meet. Doctor preflight is the right surface for "you have linkedin sends in the manifest but the cap rule is not configured — uncomment it" warnings; that's a Pillar I deliverable, not a Pillar A one.

### Pillar A exit criterion satisfied by this ADR

PILLAR-PLAN §2 Pillar A's exit criterion ends with "zero hardcoded policy in skills." After this ADR lands:

* `skills/send-outreach/scripts/send_queued.py` retains the `LINKEDIN_WEEKLY_INVITE_LIMIT` constant **only** as a cosmetic display in `_print_preview`. The constant is no longer load-bearing for any gate decision.
* The actual cap enforcement lives in `cooldowns.example.yml` as a `budget.window-cap` factory rule. Operators copy + uncomment to enable.
* Every other Pillar A rule class (cooldown / cross-channel / suppression / sending-window / budget / tier) is already policy-defined, not skill-hardcoded. With the LinkedIn cap migrated, no hardcoded policy remains in `skills/`.

The exit criterion is met after this ADR lands.

## Alternatives considered

### Alternative 1: defer the LinkedIn cap migration to Pillar C

Wait for Pillar C to land `li_invite_intent` / `li_invite_confirmed`, then migrate the cap in the same commit that wires the two-phase events. **Rejected** because:

* The Pillar A exit criterion explicitly says "zero hardcoded policy in skills" — not "zero hardcoded policy in skills that are fully-wired channels." Deferring forces Pillar A to ship with an unmet exit criterion, which is the failure mode the ADR-0007 work (matrix consolidation + simulation surface) was trying to close.
* Pillar C's week range is already busy with the four-channel two-phase wiring. Adding "and also migrate the LinkedIn cap from a Python constant to a YAML rule" stuffs more into a week range that's already 11 weeks of work. Pillar A pays the cleanup cost now; Pillar C inherits the rule, not the constant.
* The transitional emit-site cost (six lines of SKILL.md instruction Claude must follow per invite) is six lines, not a redesign. The cost is small; the benefit (Pillar A actually stable) is high.

### Alternative 2: migrate without the transitional emit-site instruction

Just add the YAML rule, count on operators / Claude to figure out the emit. **Rejected** because:

* Without the emit, the rule's behavior is "Allow every linkedin send because the cost ledger shows zero linkedin units." That's worse than the hardcoded constant — the constant at least produced a warning at 100 sends.
* The emit instruction is documented in `_emit_linkedin_manifest`'s printed handoff; Claude reads that handoff on every batch, so the instruction is in front of the operator's eyes on every dispatcher run.
* Six lines of SKILL.md instruction is cheaper than a silent regression in cap enforcement.

### Alternative 3: hardcode the rule definition in Python instead of YAML

Have `send_queued.py` (or a new `orchestrator/policy/__init__.py` factory) construct a `BudgetWindowCapRule` instance for the LinkedIn cap, not require YAML. **Rejected** because:

* The whole point of Pillar A is YAML-declarative policy. Hardcoding the rule in Python is "exact same problem as the constant, just in a different shape."
* Operators who want to tune the cap (e.g. for a LinkedIn Premium account with a wider quota) would have to fork Python code; the YAML form lets them edit a single number in a config file.
* Doctor preflight (Pillar I) can validate operator YAML against a schema; it can't validate hardcoded Python that some operator might have monkeypatched.

### Alternative 4: ship the rule uncommented (enabled by default)

Make the cap fire on every install with LinkedIn outreach configured. **Rejected** per §Decision item "The factory rule ships commented out" above — operators with no LinkedIn outreach shouldn't see refusals from a rule their use case doesn't motivate; the doctor preflight is the right place to nudge operators with LinkedIn manifests but no cap rule.

### Alternative 5: tighten the cap to 90/week (build in safety margin)

Ship `max_units: 90` instead of `100` so the rule fires before LinkedIn does. **Rejected** for v1 — the cap is operator-tunable; let operators decide their safety margin. The example value matches LinkedIn's published soft limit; operators with a conservative posture uncomment with `max_units: 80`, operators with a Premium account uncomment with `max_units: 200`. The example value should match the published default; safety-margin tuning is operator policy, not engine policy.

### Alternative 6: refactor the `_print_preview` warning to consult the policy engine

Have the preview run a synthetic `evaluate_all` against a hypothetical "if you sent all of these now" context and surface "policy rule N would fire on M of these invites." **Rejected for this ADR** — the preview-to-policy coupling is real quality-of-life work but doesn't unblock the Pillar A exit. Tracked as a future enhancement; see ADR-0007 §Decision item "Simulation surface" for the surface this would consume.

### Alternative 7: use `budget.per-run-cap` instead of `budget.window-cap`

Scope the cap to the dispatcher run rather than a 7-day rolling window. **Rejected because:**

* The LinkedIn soft cap is per-week, not per-run. Multiple runs in the same week should accumulate against the same cap.
* The dispatcher might legitimately do one run per day for a week; each run could be 14 invites and stay under the per-run cap, but together they'd hit LinkedIn's soft cap on day 7.
* `budget.window-cap` with a 7-day rolling window is the structurally correct shape for LinkedIn's published behavior.

## Consequences

### Positive

- The Pillar A exit criterion's "zero hardcoded policy in skills" line is met. No more in-skill numeric thresholds that gate sends.
- R009 (LinkedIn account suspension)'s "migrate to Pillar A budget rule" sub-mitigation is now complete — the policy engine refuses at the gate when the rule is enabled.
- Pillar C inherits a rule, not a constant. The two-phase wiring becomes "emit `cost_incurred` from the success path" — no policy redesign required.
- The factory ruleset in `cooldowns.example.yml` gains symmetry: every quota / cost concern is expressed as a policy YAML entry; nothing is in Python.
- The matrix grows by two rows (LIA-01 + LIA-02) that exercise units-mode with channel scoping — a previously uncovered combination on the matrix file's single-verdict surface.

### Negative

- The transitional emit site is operator-mediated. If Claude forgets the `cost_incurred` append after a successful invite, the cap under-reports and silently allows over-quota sends. **Mitigation:** the SKILL.md instruction in `_emit_linkedin_manifest` is printed on every dispatcher run; the instruction is explicit + concrete; Claude follows the printed handoff per its system prompt convention. Pillar C closes this transitional window by replacing the manual append with a post-confirm hook.
- The cap is commented out by default, so operators must opt in. Operators who DO use LinkedIn outreach but don't read the example file will run unprotected. **Mitigation:** doctor preflight (Pillar I) is the right warning surface — "you have linkedin sends in the manifest, no linkedin-cap rule active; consider uncommenting." Not a Pillar A blocker.
- The `_print_preview` cosmetic tally and the policy rule's `max_units` could theoretically diverge if an operator tunes one without the other. **Mitigation:** the OSS default is the same value on both sides; an operator who tunes one is by definition an operator who knows what they're doing.
- The `LINKEDIN_WEEKLY_INVITE_LIMIT` constant in `config.py` is now used only for the cosmetic display. A future cleanup could remove it entirely (the preview reads from policy YAML). Tracked as a quality-of-life follow-up; out of scope for this ADR.

### Neutral / observability

- The LinkedIn cap fires via the same `policy_blocked` event shape (per ADR-0001) every other policy rule uses. The funnel CLI's `--breakdown gate_reason` view surfaces LinkedIn refusals as `gate_reason=linkedin-weekly-invite-cap` without new code.
- The cost_incurred events the rule reads carry `source: linkedin`, `units: 1`, `amount_usd: 0.0`. These appear in the funnel CLI's `--breakdown source` view alongside gmail / anthropic / apollo entries, with USD totals of $0 (LinkedIn is quota-only).
- The matrix file's LIA-01 / LIA-02 rows exercise the channel-scoping branch — the rule fires only on LinkedIn sends, not on email sends with the same invite history. This is the same `block_when:` contract the existing matrix rows pin for other channel-scoped rules.

## Compliance with invariants

- **I1 (single source of truth):** The LinkedIn invite count is derivable from `cost_incurred` events in the ledger (the existing `Cost ledger` SoT row in `docs/SOURCES-OF-TRUTH.md` covers this). The cap THRESHOLD lives in `cooldowns.example.yml` / `~/.outreach-factory/policies/cooldowns.yml` — also already covered by the existing `Cooldown / budget / window policy` SoT row. **No new SoT registry rows required** — the LinkedIn cap is shape-identical to the existing budget rules.
- **I2 (two-phase commit):** The cap rule consumes `cost_incurred` events; the events are appended (by Claude in the transitional period, by Pillar C's post-confirm hook later) AFTER the LinkedIn API call succeeds. The "we don't pay for failures" emit-site contract from ADR-0006 carries forward: failed `mcp__linkedin__connect_with_person` calls do not emit cost events; only successful ones do. The cap therefore can't false-fire on failed invites.
- **I3 (schema versioning):** No new event types; no schema bump. The `cost_incurred` event with `source: linkedin` is the existing ADR-0006 schema with the existing `v: 1`. Existing policy YAML files with no `linkedin-weekly-invite-cap` rule continue to parse and evaluate identically; the rule is additive opt-in.
- **I5 (observable by default):** Every cap refusal emits `policy_blocked` per ADR-0001's contract. The funnel CLI's existing `--breakdown gate_reason` axis surfaces the LinkedIn-cap firings as a distinct rule name without changes.
- **I6 (tests prove invariants):** `tests/test_policy_matrix.py::test_matrix_row[LIA-01]` pins the at-threshold-blocks contract; `LIA-02` pins the channel-scoping contract. The existing `tests/test_policy_budget.py` deep-coverage of `BudgetWindowCapRule` units-mode (TestBudgetWindowCapRule::test_units_mode_blocks_at_threshold) is the per-class proof; the matrix rows are the integration proof.
- **I7 (cost is a first-class concern):** The LinkedIn cap consumes `cost_incurred` events; the existing emit-site contract (ADR-0006) extends to a new source (`linkedin`). The transitional emit-site (Claude-typed append) honors the same shape the future Pillar C post-confirm hook will produce — the rule reads identical events either way.
- **I8 (decisions documented):** This ADR. ADR-0007 §References is updated to point forward to ADR-0008. `docs/adr/README.md` gains the ADR-0008 row. Risk register R013 added with this ADR's section as the mitigation pointer.

Does not weaken any invariant. The migration is shape-preserving — the same gate decision (refuse over 100 invites/week) was always conceptually a policy decision; it just lived in Python until this ADR moved it to YAML.

## Migration / rollout

Greenfield: a new commented-out rule in `config-template/cooldowns.example.yml`. Operators who haven't copied the template yet receive the rule on their next copy. Operators who already have a `cooldowns.yml` in `~/.outreach-factory/policies/` keep their file unchanged; adding the rule is a manual paste (or a future migration runner — Pillar B — can offer to add it as a new entry on policy version bump).

`skills/send-outreach/scripts/send_queued.py`:

* The `LINKEDIN_WEEKLY_INVITE_LIMIT` import + `LINKEDIN_WEEKLY_SOFT_LIMIT` alias remain. Lines 119–127's preview warning is unchanged. These are the cosmetic-display surfaces and ADR-0008 explicitly does not require their migration.
* `_emit_linkedin_manifest` gains four new lines in the printed handoff instructing Claude to append a `cost_incurred` event after each successful invite. This is the transitional emit-site convention.

Doctor preflight does not need to change for this ADR — the rule is shape-identical to the other budget rules, which doctor already validates.

When Pillar C lands `li_invite_intent` / `li_invite_confirmed`:

* The post-confirm code path emits `cost_incurred` with `source: linkedin`, `units: 1`, `amount_usd: 0.0`, `person_id: <id>`, `intent_id: <id>` — same shape as `gated_send_one`'s gmail emit. No rule change.
* The `_emit_linkedin_manifest` handoff's "step 4" instruction can be removed; the emit moves from manual to automatic. The SKILL.md edit is reverted at Pillar C ship time.
* The factory rule continues to be commented out by default in the example file. Operators who already enabled it during Pillar A keep their enabled config; nothing they wrote breaks.

## References

- ADR-0001 (policy engine architecture) — `policy_blocked` event shape; `_block_when_matches` filter mechanism.
- ADR-0006 (budget rules + `cost_incurred` event) — `BudgetWindowCapRule` units mode; `cost_incurred` event schema; per-emit-site attribution contract; the "we don't pay for failures" convention this ADR inherits.
- ADR-0007 (tier rules + simulation surface) — most recent ADR; this ADR follows immediately and inherits the same convention discipline.
- `docs/PILLAR-PLAN.md` §2 Pillar A exit criterion — the "zero hardcoded policy in skills" line this ADR closes.
- `docs/PILLAR-PLAN.md` §2 Pillar C — the two-phase LinkedIn handler that will replace the transitional emit-site convention.
- `docs/SOURCES-OF-TRUTH.md` — existing "Cost ledger" + "Cooldown / budget / window policy" rows cover the LinkedIn cap structurally; no new rows added.
- `docs/RISK-REGISTER.md` — risk this ADR mitigates: **R009 (LinkedIn account suspension)** sub-bullet "weekly invite cap already in place (skill-level); migrate to Pillar A budget rule." The other R009 sub-bullets (randomized timing, per-account warming) remain open work for Pillar C / H.
- `config-template/cooldowns.example.yml` — Rule 12b (the new factory rule).
- `skills/send-outreach/scripts/send_queued.py:_emit_linkedin_manifest` — transitional emit-site instruction.
- `orchestrator/policy/budget.py:BudgetWindowCapRule` — the rule class this ADR consumes (no class changes).
- `tests/test_policy_matrix.py::test_matrix_row[LIA-01]` — at-threshold Block proof for the LinkedIn cap.
- `tests/test_policy_matrix.py::test_matrix_row[LIA-02]` — channel-scoping proof (rule does not fire on email sends).
- Followups: Pillar C wires the two-phase events; Pillar I doctor preflight can warn operators with linkedin manifests but no cap rule active; quality-of-life follow-up could refactor `_print_preview` to consume policy YAML for the cosmetic tally.
