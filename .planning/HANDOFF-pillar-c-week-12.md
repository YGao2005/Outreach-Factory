# Handoff — Pillar C Week 12 startup (exit-gate-close week)

Authored 2026-05-22, immediately after Pillar C Week 11 closed (commit `4c65c8f` + per-week-review follow-up `144ce4f`). Week 11 shipped the **fifth + final per-channel policy migration** — `policy/0006_add_cross_channel_email_linkedin_cooldown`. The bidirectional cross-channel email↔LinkedIn cooldown pair is now installed for every operator who runs migrations; R011 (cross-channel double-engagement) is mitigated across the full operator population per ADR-0024 D-N1-N8. **1845 tests passing post-Week-11-follow-up; total pending = 15.**

**Week 12 is structurally different from Weeks 7-11.** This is the **Pillar C exit-gate-close week** — NOT a per-channel migration. The structure is:

1. **Un-skip + implement `TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures`** — the binding Pillar C exit-criterion test that has been skipped since Week 1 (per the placeholder in `tests/test_multi_channel_coherence.py:1712`). The test pins the 50-prospect-across-four-channels-with-10-injected-failures property + asserts no R011 double-engagement.

2. **Build the programmatic 50-prospect synthetic-state extension.** Analogous to Pillar B Week 5's `synthetic_state_dir` fixture extension. The 50 prospects need to be distributed across the four channels per a realistic ICP shape (~25 email / ~15 LinkedIn invite / ~5 LinkedIn DM / ~3 Twitter DM / ~2 Calendar booking — the exact distribution is operator-deliberate per the test docstring at `tests/test_multi_channel_coherence.py:1689-1694`).

3. **Inject failures at the two-phase boundary on 10 of the 50.** Two per channel (one at intent-write, one at outcome-write). The injection harness is the structurally novel surface — it needs to crash the dispatcher at a controlled point + leave the ledger / vault in a partially-written state that reconcile must recover.

4. **Run reconcile (all passes A through F).** Verify every injected-failure intent has a recovered outcome (`*_confirmed` if the external call landed; `*_aborted` if it didn't). Verify no cross-channel rule fires incorrectly (R011 guard at the live-engine level, not just synthetic). Verify no prospect ends with BOTH an email_confirmed AND a linkedin_confirmed within 14d window.

5. **Holistic exit review.** Analogous to Pillar B's `.planning/REVIEW-pillar-b-holistic.md`. Cross-week ADR coherence check (ADR-0014 + ADR-0015 + ADR-0016 + ADR-0017 + ADR-0018 + ADR-0019 + ADR-0020 + ADR-0021 + ADR-0022 + ADR-0023 + ADR-0024 — cumulative D33-D-N8). Systemic patterns assessment. Operator-facing instructions audit. Boil-the-ocean robustness check. Outcome: zero P1 findings is the structural gate.

6. **Pillar C retrospective.** Analogous to Pillar B's `.planning/RETRO-pillar-c.md`. What worked; what would do differently in Pillar D; carry-forward patterns.

7. **PILLAR-PLAN.md §6 Pillar C row stable flip.** Replace "In progress as of 2026-05-22 (Week 11 shipped — fifth + FINAL of the Weeks 7-11 per-channel policy migration arc...)" with "**Stable** as of 2026-MM-DD (Week 12 exit gate closed; holistic review + retrospective complete)."

8. **Pillar D unblocked.** Add the unblock-from-stable-C note to the §6 row.

**This is the LAST week of Pillar C.** The next week begins Pillar D (reply + conversation handling).

## Fresh-session prompt (paste between markers)

> BEGIN PROMPT
>
> Read in this order before starting:
>   1. `/Users/yang/code/outreach-factory/.planning/HANDOFF-pillar-c-week-12.md` end-to-end — this document.
>   2. `/Users/yang/code/outreach-factory/.planning/HANDOFF-pillar-c-week-11.md` — the immediate prior handoff (Week 11 ships policy/0006; Week 12 closes the pillar).
>   3. `/Users/yang/code/outreach-factory/docs/adr/0024-pillar-c-cross-channel-email-linkedin-cooldown.md` — Week 11's ADR. D-N1-N8. The most recent per-channel policy migration ADR; sets the precedent that the per-channel migration arc is complete.
>   4. `/Users/yang/code/outreach-factory/docs/adr/0014-pillar-c-foundation.md` — Pillar C's foundation ADR. **CRITICAL.** D33-D37 + the `tests/test_multi_channel_coherence.py` exit-criterion vehicle introduction. The exit-criterion test was DEFINED here as the binding gate; Week 12 ACTIVATES it.
>   5. `/Users/yang/code/outreach-factory/tests/test_multi_channel_coherence.py` (lines 1670-1720) — the `TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures` placeholder. The test docstring specifies the exact shape (4-step protocol; ICP distribution; injection at each two-phase boundary; recovery + R011 guard assertions).
>   6. `/Users/yang/code/outreach-factory/tests/conftest.py` + `/Users/yang/code/outreach-factory/tests/fixtures/synthetic_pillar_b/` — the `synthetic_state_dir` fixture infrastructure. Week 12 EXTENDS this with a 50-prospect programmatic fixture (analogous to Pillar B Week 5's stress-test extension).
>   7. `/Users/yang/code/outreach-factory/tests/test_migrations_replay.py::TestExitCriterionProperty::test_clean_replay_against_fresh_synthetic` — the Pillar B exit-criterion test (the PRECEDENT for what an exit-criterion test looks like). Pillar B's runs in <2s + asserts every SoT invariant after one `apply()`. Pillar C's is structurally more complex (50 prospects + injection + reconcile across 4 channels + R011 verification across the live engine).
>   8. `/Users/yang/code/outreach-factory/.planning/REVIEW-pillar-b-holistic.md` — Pillar B's holistic exit review (the precedent). Pillar C's holistic review mirrors the structure: Summary + P1/P2/P3 Findings + Systemic Patterns Assessment + Operator-Facing Instructions Audit + Boil-the-Ocean Robustness Check + Cross-Week ADR Coherence Check + Verdict.
>   9. `/Users/yang/code/outreach-factory/.planning/RETRO-pillar-b.md` — Pillar B's retrospective. Pillar C's retro mirrors the structure: What Worked + What I'd Do Differently + Carry-Forward Patterns.
>  10. `/Users/yang/code/outreach-factory/docs/PILLAR-PLAN.md` §2 Pillar C — binding exit criterion text. §6 Pillar C row — the stable-flip target.
>  11. `/Users/yang/code/outreach-factory/.planning/RETRO-pillar-b.md` — the per-week-handoff + per-week-review discipline carries (but Week 12's discipline is HOLISTIC review, not per-week — different rigor).
>  12. `/Users/yang/code/outreach-factory/.planning/REVIEW-pillar-c-week-11.md` — Week 11's per-week review report. Carry-forward patterns under "What looks good" — Week 12's holistic review subsumes the per-week reviews.
>  13. `/Users/yang/code/outreach-factory/orchestrator/reconcile.py` — Passes A-F (Pillar A: A/B/C; Pillar C: D/E/F). Week 12 verifies all 6 passes recover injected-failure intents end-to-end.
>  14. `/Users/yang/code/outreach-factory/skills/send-outreach/scripts/send_queued.py` — the four per-channel dispatchers (`gated_li_invite_one`, `gated_li_dm_one`, `gated_tw_dm_one`, `gated_calendar_booking_one`) — the dispatchers Week 12's stress test exercises.
>  15. `/Users/yang/code/outreach-factory/orchestrator/policy/cross_channel.py` — the `CrossChannelTouchRule` Week 12 verifies fires correctly against ledger events written by the live dispatchers (not just synthetic events).
>
> ## State of the world
>
> **Pillar A is stable** as of 2026-05-19 (ADRs 0001-0008; 700+ tests). **Pillar B is stable** as of 2026-05-21 (ADRs 0009-0013; 1136 tests). **Pillar C Weeks 1-11 shipped** as of 2026-05-22 (ADRs 0014-0024; 1845 tests passing). Four per-channel dispatchers shipped (LinkedIn invite / DM, Twitter DM, Calendar booking). Three reconcile passes shipped (D / E / F for LinkedIn invite / DM / Twitter DM). Pass G deferred per ADR-0019 D68. Five per-channel cost emit sources established (`linkedin_invite`, `linkedin_dm`, `twitter_dm`, `calendar_booking`, `gmail`). Five per-channel policy migrations shipped (Weeks 7-11): `policy/0002` LinkedIn invite + `policy/0003` LinkedIn DM + `policy/0004` Twitter DM + `policy/0005` Calendar booking daily + `policy/0006` cross-channel email↔LinkedIn cooldown.
>
> **The substrate ready for Week 12:**
>
> * **Every per-channel dispatcher exists.** Week 12 exercises all four (and email via `gmail` source) in the 50-prospect stress test.
> * **Every reconcile pass exists** (A-F; Pass G deferred per ADR-0019 D68 — the webhook IS the canonical Cal.com recovery surface, no periodic-reconcile needed). Week 12 verifies reconcile recovers every injected-failure intent across all six passes.
> * **Every per-channel policy migration exists** (Weeks 7-11 covered). Operators running migrations have R011 mitigation across the full operator population.
> * **The `synthetic_state_dir` fixture exists** (Pillar B Week 5; extended through Pillar C Weeks 2-6 to add per-channel Persons). Week 12 extends it with a 50-prospect programmatic fixture.
> * **The `TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures` placeholder exists** (since Week 1; pinned by skip-marker). Week 12 un-skips it + implements the test body.
>
> ## Phase 1: Confirm Pillar C Week 11 is closed cleanly
>
> Run before starting Week 12:
> * `git log --oneline -10` — verify Week 11 closing commit sequence is intact (Week 11 commit `4c65c8f` + per-week-review follow-up `144ce4f`).
> * `python -m pytest tests/ --ignore=tests/test_verify_email.py -q` — verify 1845+ passing.
> * `python -m pytest tests/test_migrations_policy_0006.py -v` — verify all 80 rows running.
> * `grep -rn WORKAROUND orchestrator/ skills/send-outreach/scripts/` — verify nothing.
> * `python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print('pending:', len(r.pending()))"` → expect `15` (Week 10's 14 + Week 11's policy/0006).
> * Verify ADR-0024 exists + §Downstream pillar impact section names Pillar D / E / F / G / H / I / J + D-N8 has its own "Rejected D-N8 alternatives:" subsection (NOT recurring the Week 10 P2-D pattern).
> * Verify `docs/adr/README.md` ADR-0024 row is present.
> * Verify `docs/PILLAR-PLAN.md` §6 Pillar C row reads "Week 1 ✓ + Week 2 ✓ + ... + Week 11 ✓".
> * Verify `tests/test_migrations_replay.py::TestFullBatchApply::test_full_apply_writes_cross_channel_cooldown_rules_to_policy_file` runs (the Week 11 parallel cross-channel sentinel test).
> * Verify `tests/test_multi_channel_coherence.py::TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures` still SKIPS (it should — Week 12's job is to un-skip it).
>
> No work in Phase 1 unless any of the above flags an anomaly.
>
> ## Phase 2: Pillar C Week 12 — exit-gate-close + Pillar C stable flip
>
> ### Week 12 deliverables
>
> 1. **Programmatic 50-prospect synthetic-state extension** to the `synthetic_state_dir` fixture infrastructure. Analogous to Pillar B Week 5's stress-test extension. The fixture produces:
>    * 50 Person notes distributed across four channels per the test docstring's ICP shape (~25 email / ~15 LinkedIn invite / ~5 LinkedIn DM / ~3 Twitter DM / ~2 Calendar booking; the exact distribution is operator-deliberate but should sum to 50).
>    * Each Person has the appropriate identity_keys for its primary channel (email: email + linkedin for identity strength; LinkedIn: linkedin + email; Twitter: twitter_handle + linkedin OR email; Calendar: email + linkedin).
>    * The ledger is pre-seeded with appropriate enrolled events per Person (per the existing fixture pattern).
>    * The fixture's interface mirrors the existing `synthetic_state_dir` shape: a programmatic builder that constructs the 50-prospect state in tmp + returns a `SyntheticStateDir`-like object.
>    * The fixture lives in `tests/conftest.py` (or a new `tests/fixtures/synthetic_pillar_c_stress/` static fixture combined with a programmatic builder, mirroring Pillar B's pattern).
>
> 2. **Failure-injection harness** for the two-phase boundary. The harness must:
>    * Wrap each dispatcher's send call to optionally raise a `RuntimeError` at one of two controlled points: AFTER the intent event has been written but BEFORE the outcome event is written (intent-only state; reconcile Pass D/E/F/Pass A picks up). OR BEFORE the intent event is written at all (no-effect state; reconcile sees no orphan).
>    * Apply the injection to a configurable set of 10 prospects out of the 50 (2 per channel; 1 of each injection type per channel).
>    * Be deterministic: the same fixture state + same injection seed produces the same failure pattern. Critical for reproducibility.
>    * Tracked via a Person frontmatter field like `injected_failure: intent_only` or `injected_failure: pre_intent` so the test body knows which prospects to verify recovered correctly.
>
> 3. **`tests/test_multi_channel_coherence.py::TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures`** — the un-skipped test. The body MUST:
>    * Remove the `pytest.skip(...)` call.
>    * Build the 50-prospect state via the fixture extension.
>    * Configure 10 injected failures across 4 channels (2 per channel; 1 intent-only + 1 pre-intent per channel for the four MCP-based channels; calendar booking uses 2 of one type per ADR-0019's asymmetric shape).
>    * Run the send-queued dispatcher batch — 40 prospects succeed cleanly; 10 fail per the injection pattern.
>    * Run reconcile (all passes A-F).
>    * Assert: every injected-failure prospect has a recovered outcome (`*_confirmed` if the external call actually landed; `*_aborted` if it didn't — the reconcile-via-marker semantics per ADRs 0015 D39 + 0016 D43 + 0018 D58 + 0019 D65 are the load-bearing recovery mechanism).
>    * Assert: NO cross-channel rule fires incorrectly (no `policy_blocked` event with `rule: cross-channel-*` for a prospect whose only touches are on ONE channel).
>    * Assert: NO prospect ends with BOTH email_confirmed AND linkedin_confirmed within a 14d window (the R011 double-engagement guard — verified end-to-end against ledger events written by live dispatchers, not synthetic).
>    * Assert: total `policy_blocked` events on cross-channel rules = expected count (which is ZERO for the test design — the 50 prospects are distributed so no cross-channel coordination conflict arises; if the test design has any prospects with multi-channel touches, the cross-channel rule SHOULD fire on the second-channel send + this should be asserted positively).
>
> 4. **`.planning/REVIEW-pillar-c-holistic.md`** — Pillar C exit holistic review. Mirror structure from `.planning/REVIEW-pillar-b-holistic.md`:
>    * **Summary** (1 paragraph)
>    * **P1 Findings** (must-fix in follow-up commit; aim for ZERO)
>    * **P2 Findings** (should-fix in follow-up commit; aim for ≤3)
>    * **P3 Findings** (consider; defer if low-value)
>    * **Systemic Patterns Assessment** — what patterns from Pillar C reappear across weeks? (the per-channel-symmetry pattern; the asymmetric-failure-cost pattern; the per-week-review-finding-becomes-carry-forward-test pattern; the ADR-RejectedDN-subsection pattern; the structural-divergence-on-different-axis-per-week pattern)
>    * **Operator-Facing Instructions Audit** — every per-channel migration's §Migration/rollout section + the operator-readable surface (factory comments, runner logs, doctor outputs) audited for clarity + correctness. Did Pillar C deliver operator-actionable surfaces, or did it accumulate ADR-only documentation?
>    * **Boil-the-Ocean Robustness Check** — every Pillar C ADR's robustness analysis was full-scope per the `feedback_boil_the_ocean.md` discipline. Did any ADRs cut corners? (Answer expected: no — but verify.)
>    * **Cross-Week ADR Coherence Check (D33-D-N8 Cumulative)** — every decision D33 through D-N8 inspected for cross-ADR coherence. Does any later D contradict an earlier D? (Answer expected: no; if yes, that's a P1.)
>    * **Verdict** — STABLE / NOT-STABLE-pending-followup-commit. The verdict gates the §6 row stable flip.
>
> 5. **`.planning/RETRO-pillar-c.md`** — Pillar C retrospective. Mirror structure from `.planning/RETRO-pillar-b.md`:
>    * **What Worked**
>    * **What I'd Do Differently in Pillar D**
>    * **Carry-Forward Patterns** (for Pillar D, E, F, G, H, I, J — which Pillar C patterns each next pillar will inherit)
>
> 6. **`docs/PILLAR-PLAN.md` §6 Pillar C row stable flip.** Replace "**In progress** as of 2026-05-22 (Week 11 shipped — fifth + FINAL of the Weeks 7-11 per-channel policy migration arc...)" with:
>    ```
>    **Stable** as of 2026-MM-DD (Week 12 exit gate closed + holistic exit review + Pillar C retrospective). Week 12 (`<commit>` + per-week-review follow-up `<followup>`): un-skipped `TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures` + implemented the 50-prospect synthetic-state extension + failure-injection harness; holistic exit review (`.planning/REVIEW-pillar-c-holistic.md` — N P1s + M P2s + K P3s); Pillar C retrospective (`.planning/RETRO-pillar-c.md`). N total tests passing post-Week-12. **Exit criterion met:** the 50-prospect 4-channel run with 10 injected failures replays cleanly through reconcile (every injected failure recovered; no R011 double-engagement); every per-channel dispatcher + every reconcile pass + every per-channel policy migration shipped; every ADR (0014-0024) covers its decisions + ≥3 rejected alternatives + §Downstream pillar impact; no `WORKAROUND` markers in `orchestrator/` or `skills/send-outreach/scripts/`. Pillar D + E + F + G + H + I + J unblocked from a "stable C" dependency.
>    ```
>    + Update the §6 Pillar C row's `Notes` column to "Week 1 ✓ + Week 2 ✓ + ... + Week 11 ✓ + Week 12 ✓ — STABLE".
>
> 7. **`docs/adr/README.md`** — no new ADR for Week 12 (the work is non-ADR-warranting: un-skipping a test + writing a holistic review + writing a retrospective). If the holistic review or test implementation surfaces a load-bearing decision that warrants an ADR (e.g. a failure-injection-harness pattern future pillars will inherit), ship it as ADR-0025 — but the default is no new ADR.
>
> 8. **Per-week independent review + follow-up commit.** Same per-week discipline as Weeks 7-11. The Week 12 review should be more rigorous than the per-week reviews (it IS the holistic exit review) but the per-week-review-with-follow-up-commit pattern still applies for any P1/P2 findings the independent reviewer surfaces.
>
> 9. **Pillar D scoping note.** Add a forward-reference in PILLAR-PLAN §6 Pillar D row (or as a separate `.planning/HANDOFF-pillar-d-week-1.md` document — the Pillar D author's choice). Pillar C's deliverables don't include Pillar D planning, but the close-of-pillar should leave a breadcrumb.
>
> ### Design decisions you may need to make
>
> **The handoff document doesn't pre-decide these because they depend on what the Week 12 work surfaces:**
>
> * **The 50-prospect ICP distribution** — the docstring suggests ~25 email / ~15 LinkedIn invite / ~5 LinkedIn DM / ~3 Twitter DM / ~2 Calendar booking but the exact split is operator-deliberate. The test author should pick a split that exercises every channel at least once and produces a meaningful R011-guard surface (i.e. at least 1-2 prospects with multi-channel touches so the cross-channel rule has a chance to fire).
>
> * **The failure-injection harness's API.** Two reasonable shapes:
>   - **Monkey-patched dispatcher**: pytest fixture monkey-patches the dispatcher function to raise at the controlled point. Pros: simple. Cons: tight coupling to dispatcher internals.
>   - **Configurable Person frontmatter flag**: each Person carries an `injected_failure: <type>` field; the dispatcher (in test-mode) reads the flag + raises accordingly. Pros: declarative; the fixture state describes the failures. Cons: dispatcher needs a test-mode entry point.
>   - **Recommendation**: monkey-patched dispatcher (simpler; the alternative requires changing production code for test-only behavior, which Pillar A's "no test-only paths" discipline rejects).
>
> * **Whether the holistic review identifies any P1 findings.** The aim is zero — Pillar A + B both closed with zero P1s per the per-pillar handoff pattern. If P1s surface, they MUST land in a Week 12 follow-up commit before the stable flip; the stable flip is gated on zero-P1.
>
> * **Whether to ship ADR-0025 for any structural decision the Week 12 work surfaces.** If the failure-injection harness introduces a pattern future pillars will inherit (e.g. a generalized failure-injection fixture in `tests/conftest.py`), an ADR documenting the pattern is justified. Otherwise the work is non-ADR-warranting per the deliverable list above.
>
> ### Validation gate (Week 12)
>
> Before considering Week 12 complete:
> * Every Week 12 deliverable shipped.
> * `python -m pytest tests/ --ignore=tests/test_verify_email.py -q` passes (test count TBD — the 50-prospect test adds 1 test row + the fixture extension may add 5-10 fixture-validation tests; conservative estimate is ~1851-1856 tests).
> * `python -m pytest tests/test_multi_channel_coherence.py::TestExitCriterion -v` shows the test PASSING (un-skipped + green).
> * `python -c "from orchestrator.migrations import MigrationRunner; r = MigrationRunner(); print('pending:', len(r.pending()))"` → still `15` (no new migrations in Week 12).
> * `docs/PILLAR-PLAN.md` §6 Pillar C row reads "**Stable** as of 2026-MM-DD" + "Week 1 ✓ + ... + Week 12 ✓ — STABLE".
> * `.planning/REVIEW-pillar-c-holistic.md` exists + ends with "**Verdict: STABLE**" (zero P1 findings; ≤3 P2 findings addressed in follow-up).
> * `.planning/RETRO-pillar-c.md` exists.
> * Per-week independent review with a separate follow-up commit if needed.
> * `grep -rn WORKAROUND orchestrator/ skills/send-outreach/scripts/` — verify nothing.
> * `docs/adr/README.md` — unchanged (or extended by 1 row if an ADR-0025 ships).
> * Pillar D first-week handoff scaffolded (either in PILLAR-PLAN.md §6 Pillar D row's `Notes` column or as `.planning/HANDOFF-pillar-d-week-1.md`).
>
> ### Pillar C Week 12 will NOT ship
>
> * **A sixth per-channel policy migration.** Weeks 7-11's arc is complete.
> * **A CLI** for any Pillar C policy operation. Deferred to Pillar I.
> * **Reconcile Pass G** — DEFERRED per ADR-0019 D68; webhook IS the canonical recovery surface.
> * **The Pillar I doctor preflight Shape-B detect surface** for cross-channel pairs. Pillar I OSS bring-up.
> * **Pillar D's reply-correlator.** Pillar D starts Week 13.
>
> ## Carry-over from Pillar C Week 11 — disposition
>
> Pillar C Week 11's per-week reviewer (commit `144ce4f`) caught **0 P1s + 1 P2 + 2 P3s**. P2-A (the `consider_channels: [twitter]` sub-case gap) was addressed in the Week 11 follow-up commit. P3-A (dead-code assertion branch) was addressed. P3-B (Shape B downgrade absence-assertion gap) was deferred. Week 12 inherits a clean substrate; the deferred P3-B is a documentation-completeness item the holistic review may surface (or may defer further; operator-side it's low impact).
>
> Categories to watch in Week 12 per-week review + holistic review (per the Week 11 review's "what looks good" + the structural-novelty of Week 12's work):
>
> * **P1 candidates:**
>   - **The 50-prospect test failing** — if reconcile fails to recover any injected failure, that's a P1 in the live system. The test's job is to surface this; if it does, debug + fix before the stable flip.
>   - **A cross-channel rule firing incorrectly** in the live engine — if Rule 5 or Rule 6 fires on a prospect with only single-channel touches, that's a R011-guard regression P1.
>   - **A reconcile pass crashing under stress load** — if any of Passes A-F crashes when processing the 50-prospect state, that's a P1.
>
> * **P2 candidates:**
>   - **Test-suite runtime degradation.** The 50-prospect test is structurally heavier than per-week unit tests; if it runs in >30s the test surface becomes friction. Target: <10s.
>   - **Holistic review surfacing systemic patterns from Pillar C that weren't documented** — e.g. the "structural divergence on different axes per week" pattern (Weeks 7-9 share the cap-shape; Week 10 diverges on window-unit + failure-mode; Week 11 diverges on rule-class + field + factory-state-precedent) is genuinely novel + should be documented.
>   - **Operator-facing instructions audit surfacing a gap** — e.g. operators don't know about the Shape B (transitional one-direction-installed) recovery path until they hit it.
>
> * **P3 candidates:**
>   - **Pillar D's reply-correlator design needs a sneak preview** — Pillar C's exit gate doesn't include Pillar D scoping, but a forward-reference is operator-friendly.
>   - **Factory-shipped `window_days: 14` default tuning** — operator feedback over time may motivate adjusting from 14.
>
> ## Carry-over conventions (from Pillars A + B + C Weeks 1-11)
>
> * **TDD per PILLAR-PLAN §3:** red → green → ADR → docstring. "Complete" requires all four. Week 12's test un-skip + test-body implementation follows this — the test is RED while skipped, GREEN when un-skipped + passes, the ADR is the §Verdict in the holistic review (if any ADR-0025 ships), the docstring is the test docstring + the holistic review document.
> * **`feedback_boil_the_ocean.md` applies** — no 80/20 framings on robustness work; full proposals only. The 50-prospect stress test is robustness work par excellence — the failure-injection harness must cover the full space of two-phase-boundary failure modes, not just the easy ones.
> * **`tests/conftest.py` aliases bare-name imports** — don't manipulate `sys.path` from inside a test file.
> * **No backwards-compat shims** for renamed fields, `# removed` comments, etc.
> * **ADRs append-only.** Week 12's optional ADR is 0025 (if any).
> * **Per-week handoff doc stays.** The Week 11 handoff was the LAST per-channel-migration handoff; Week 12's handoff (this doc) is the exit-gate-close handoff. Pillar D Week 1 may have its own handoff or may be absorbed into a Pillar D foundation ADR (Pillar D author's choice).
> * **Per-week independent review with a SEPARATE follow-up commit.** Pillar A + B + C Week 1-11 pattern continues. Week 12 adds the holistic exit review as a SEPARATE document (`.planning/REVIEW-pillar-c-holistic.md`) — the per-week review and the holistic review are distinct artifacts with overlapping but non-identical concerns.
> * **The atomicity contract is the framework's most load-bearing promise.** Every Pillar C design decision was checked against it. The 50-prospect stress test verifies the per-file atomicity holds under load (50 vault writes + 50 ledger writes + N reconcile-pass writes; per-file tmp-then-rename+fsync per ADR-0011 holds).
> * **"Doc-sweep before commit" discipline** (per RETRO-pillar-b §What to do differently in Pillar C, item 2). Whenever a commit touches a documented contract (ADRs, docstrings of public APIs, `docs/SOURCES-OF-TRUTH.md`, `docs/PILLAR-PLAN.md`), `git grep` for the prior-state phrasing + sweep every match. Week 12's stable-flip commit touches PILLAR-PLAN §6 Pillar C row + the holistic review + the retrospective; the doc-sweep should include `tests/test_doctor_preflight_migrations.py` docstrings (the "Week N" phrasing) + the `tests/test_migrations_replay.py` test names + docstrings naming the week count.
> * **Operator-facing surfaces matter** — every Pillar C ADR's Migration/rollout section is operator-readable. The holistic review's "Operator-Facing Instructions Audit" section verifies this end-to-end.
> * **Channel-on-every-event invariant** (per ADR-0014 D33). Every `policy_blocked` event MUST stamp `channel: <value>` per the existing dispatcher contract. Week 12's R011-guard assertions verify this end-to-end.
> * **Surgical YAML preservation** — operator comments + rule order in cooldowns.yml MUST survive every migration's apply. The Week 12 stress test verifies this in the 50-prospect state too.
> * **The `TestNoStaleSourceWarning` + `TestNoStaleConsiderChannelsWarning` carry-forward** — Weeks 8-11 use the "test the negative invariant" pattern when an ADR-decision says NO stale detection. Week 12 inherits these tests for the regression-guard role.
> * **The cross-migration coexistence test growing-quintet.** Week 11 extended to a quintet (4 per-channel caps + 1 cross-channel pair). Week 12 doesn't add new migrations; the quintet stays. Pillar D's reply-coordination caps may extend further.
>
> ## Carry-overs deferred (DON'T address in Pillar C Week 12 unless they bite directly)
>
> From Pillar A + B + C Weeks 1-11 (all deferred per the prior handoffs + reviews):
> * Pillar B Week 6 parallel-review P2s deferred to Pillar I: README/INSTALL operator polish; `docs/MIGRATIONS.md` operator guide; hardcoded subdir-name parameterization; ADR-0001 missing downstream-pillar-impact section; `migration_event` field schema formalization; engine-reload-after-migration contract.
> * The `_recovered_by` predicate consolidation across `_vault_io.py` / `_ledger_io.py` / `identity.py` / `backfill_*.py` / `reconcile.py` — Pillar I.
> * The `_emit_linkedin_manifest` legacy fallback path in `send_queued.py` — Pillar I deprecates per ADR-0015 §Migration/rollout item 3.
> * Week 11 P3-B (Shape B downgrade absence-assertion gap) — documentation-completeness; may surface in the holistic review.
>
> From Pillar C Week 1-11:
> * **Pre-Week-1 operators carry a small known limitation:** their backfilled `send_confirmed` events lack the `channel` field. ADR-0014 §Migration/rollout item 3 documents the remediation path.
> * **Pre-Week-2 / Week-3 / Week-5 / Week-6 operators have NO retroactive per-channel ledger state UNLESS the per-channel migrations run.** ADR-0015 D41 + ADR-0016 D46 + ADR-0018 D63 + ADR-0019 §"Existing-operator seed" document the seed.
> * **Pre-Week-4 operators have NO reconcile state file UNTIL first invocation.** ADR-0017 D51 documents the operator-facing rollout. Pass F (Week 5) extends per the same posture.
> * **Lazy-stamping `linkedin_connected:` is operator-manual.** Pillar I CLI's `python -m orchestrator.linkedin mark-connected <person>` will wrap the existing `_stamp_person_linkedin_connected` helper.
> * **Twitter cookie-scrape MCP capture story** is operator-deliberate per ADR-0018 D59. Pillar I OSS bring-up's `python -m orchestrator.twitter check-cookies` ergonomic is deferred.
> * **`mint_id` has no `-tw` provenance suffix.** Twitter-only Persons fall to `-tmp` ids and fail the identity_incomplete gate. Mitigation: Persons with Twitter handles also need LinkedIn or email for identity strength.
> * **Cal.com webhook handler's deployment story** is operator-deliberate per ADR-0019 D66 — Pillar I OSS bring-up ships the FastAPI route wiring + CLI replay ergonomics + `python -m orchestrator.cal_com check-webhook` validator.
> * **`twitter_handle:` vs `identity_keys.twitter` field split.** Pillar E enrichment may unify; per Week 5's pragmatic deferral.
> * **`calendar_booking_url_base:` Person-level override** introduced Week 6. If Pillar E enrichment adds bulk-discovery of operator-default URLs (the framework's per-Person field stays operator-deliberate), no schema change needed.
> * **Pre-Week-7 operators with stale `source: linkedin` (per ADR-0020 §D77 Shape 1)** keep their inert rule; Week 7's WARNING log surfaces the misconfig. Operator-side manual remediation; Pillar I doctor preflight is the future automated-detect surface.
> * **Pre-Week-8/9/10 operators with `linkedin-weekly-dm-cap` / `twitter-weekly-dm-cap` / `calendar-booking-daily-cap`-named rules with non-canonical sources** keep their rules; Weeks 8 + 9 + 10's policy migrations are silent (no WARNING per ADRs 0021 D81 + 0022 D86 + 0023 D93).
> * **Pre-Week-11 operators with `cross-channel-*` rules with stale `consider_channels:` values** keep their rules; Week 11's policy/0006 is silent (no WARNING per ADR-0024 D-N6).
> * **PILLAR-PLAN follow-up commit hashes** — left as `<followup>` placeholders across Weeks 3 + 4 + 5; a future doc-only sweep fills them. Weeks 6-9's main + follow-up commits hashes are filled. Weeks 10 + 11's main + follow-up commit hashes need filling. Week 12 should fill these as part of the doc-sweep before the stable flip.
>
> If the per-week review or the holistic review of Week 12 surfaces any deferred item as "would help Pillar C now," address it in the Week 12 follow-up commit OR in a Pillar I forward-reference per the per-week pattern.
>
> ## Don't hold back. GIVE IT YOUR ALL.
>
> END PROMPT

## Quick reference — what Week 11 delivered

| Artifact | Content |
|---|---|
| `docs/adr/0024-pillar-c-cross-channel-email-linkedin-cooldown.md` | D-N1 (bundled two-rules-per-migration shape; rejects ship-split + single-rule-bidirectional-flag + mega-migration); D-N2 (cooldown.cross-channel-touch rule class; `add_rule_block_text` composes unchanged); D-N3 (factory rules ALREADY ACTIVE since Pillar A Week 2; rejects rewriting-factory-to-commented + adding-Rule-5b-6b); D-N4 (consider_channels mirror-symmetric across the pair); D-N5 (window_days: 14 matching factory's existing shape); D-N6 (NO stale-considered-channels warning — Pillar I doctor is the future home); D-N7 (FOUR existing-operator shapes A/B/C/D); D-N8 (Downstream pillar impact across D/E/F/G/H/I/J + own "Rejected D-N8 alternatives:" subsection per Week 10 P2-D fix). ≥3 rejected alternatives per decision. |
| `orchestrator/migrations/policy/migration_0006_add_cross_channel_email_linkedin_cooldown.py` (NEW) | Migration class with TWO rule constant sets (RULE_A_NAME/TYPE/BLOCK_WHEN_CHANNEL/CONSIDER_CHANNELS/WINDOW_DAYS/REASON/BLOCK_TEXT + RULE_B equivalent); `_rule_present_by_name` helper; upgrade() composes `add_rule_block_text` calls sequentially per missing direction. |
| `orchestrator/migrations/policy/_policy_io.py` | UNCHANGED — Week 11 consumes the Week 7-landed primitives unchanged. |
| `orchestrator/migrations/policy/__init__.py` | Registers `MIGRATION_0006_ADD_CROSS_CHANNEL_EMAIL_LINKEDIN_COOLDOWN` after `MIGRATION_0005`. Module docstring's content-additive migration list extended to include policy/0006. |
| `config-template/cooldowns.example.yml` | UNCHANGED — Rules 5 + 6 ship active since Pillar A Week 2; D-N3 mandates no factory changes. |
| `tests/test_migrations_policy_0006.py` (NEW) | 80 direct migration tests including `TestNoStaleConsiderChannelsWarning` (5 sub-cases pinning D-N6 negative invariant; the `[twitter]` fully-substituted sub-case was added in the per-week-review follow-up per P2-A) + `TestRuleClassDivergence` (4 tests pinning D-N2 + D-N4) + `TestTwoRuleStructure` (6 tests pinning D-N1) + `TestSequentialAddRuleBlockTextComposition` (3 tests pinning the two-sequential-calls invariant) + `test_coexists_with_invite_cap_rule` + `test_coexists_with_dm_cap_rule` + `test_coexists_with_tw_dm_cap_rule` + `test_coexists_with_calendar_booking_cap_rule` + `test_coexists_with_all_prior_per_channel_caps` (five-way cross-migration coexistence quintet) + `TestRealFactoryTemplateRoundTrip` (3 tests pinning Shape A no-op + factory loadability + factory Rules 5 + 6 active assertion) + `TestShapeBDowngrade` (4 tests pinning shape-aware downgrade behavior) + `test_downgrade_does_not_remove_<each prior-week's rule>` (4 tests pinning cross-migration downgrade safety). |
| `tests/test_migrations_replay.py`, `tests/test_migrations_runner.py`, `tests/test_doctor_preflight_migrations.py` | Migration count updates (14→15) + new policy/0006 id added to applied lists. Sentinel test `test_full_apply_writes_cross_channel_cooldown_rules_to_policy_file` ships as a parallel cross-channel sentinel alongside the existing per-channel-cap sentinel. |
| `docs/adr/README.md` | ADR-0024 row appended. |
| `docs/PILLAR-PLAN.md` §6 Pillar C row | "Week 1 ✓ + Week 2 ✓ + ... + Week 11 ✓" + names Week 11 ship details + intro phrase updated from "Week 10 shipped" to "Week 11 shipped" + Week 11 commit hash filled (`4c65c8f`). |
| `.planning/REVIEW-pillar-c-week-11.md` | Per-week review report (0 P1s + 1 P2 + 2 P3s); carry-forward patterns under "What looks good." |

## Quick reference — invariants Pillar C Week 12 must preserve

* **Pillar B's "stable" claim holds.** No changes to `orchestrator/migrations/` framework primitives in Week 12. The 50-prospect stress test exercises the framework; doesn't modify it.
* **Pillar A's `CrossChannelTouchRule` (ADR-0003) is the cross-channel enforcement vehicle.** Week 12's R011 guard verifies the rule fires correctly against ledger events written by the live dispatchers.
* **Pillar C's per-channel migrations are complete.** Weeks 7-11 covered LinkedIn invite + LinkedIn DM + Twitter DM + Calendar booking + cross-channel pair. Week 12 ships ZERO new migrations (the pending count stays at 15).
* **Operator-facing surfaces matter from day one.** Week 12's holistic review's "Operator-Facing Instructions Audit" verifies this for the cumulative Pillar C deliverables.
* **Surgical YAML preservation** — every Pillar C migration preserves operator comments + rule order. The 50-prospect stress test verifies this in the high-load case.
* **The cross-migration coexistence test growing-quintet stays.** No new migrations in Week 12; the quintet is the final form for Pillar C.
* **No new `WORKAROUND` markers.** The Week 12 work is test + documentation; should not need workarounds.

## When you're done with Pillar C Week 12

1. **`TestExitCriterion::test_50_prospect_4_channel_run_with_10_injected_failures` passes** with the test body implementing the 4-step protocol from the docstring.
2. **`.planning/REVIEW-pillar-c-holistic.md` exists** + ends with "**Verdict: STABLE**" (zero P1 findings).
3. **`.planning/RETRO-pillar-c.md` exists** documenting what worked, what to do differently in Pillar D, and carry-forward patterns.
4. **`docs/PILLAR-PLAN.md` §6 Pillar C row** flipped to "**Stable** as of 2026-MM-DD" with the Week 12 ship details + "Week 1 ✓ + ... + Week 12 ✓ — STABLE".
5. **No new `WORKAROUND` markers; pending count still 15; full test suite green.**

Then Pillar C is closed. **Pillar D (reply + conversation handling) begins Week 13.**
