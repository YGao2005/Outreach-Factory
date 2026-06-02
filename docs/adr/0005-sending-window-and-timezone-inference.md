# ADR-0005: Sending-window rules + recipient timezone inference

- **Status:** Accepted
- **Date:** 2026-05-18
- **Pillar:** A (Policy engine — third concrete rule batch)
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0001 established the policy engine surface; ADR-0002 shipped four cooldown rule classes (UTC age math, deliberate tz-invariance); ADR-0003 added the cross-channel rule shape; ADR-0004 added three suppression rule classes. Pillar A Week 3 ships the **sending-window** rule class — the fourth concrete rule batch — covering the "don't email a recipient at 3am their time" failure mode and the related "weekend send signals impersonal automation" deliverability concern.

Two questions ADR-0002 deliberately left open until this ADR:

1. **What does `RuleContext.timezone` mean operationally?** ADR-0001 added the field and ADR-0002 reserved it for "sending-window rules (Pillar A Week 3 task)" but did not specify how the field is populated, what valid values look like, or what the rules using it actually compute. Until this ADR, the field has been semantically inert — every test passes `"America/Los_Angeles"` and no rule consults the value.

2. **How does the gate know the recipient's country?** PILLAR-PLAN §5 commits to "per-person tz inferred from `identity_keys.country`; fallback `America/Los_Angeles`," but no `country` field exists on `IdentityKeys` and no `tz_inference` module exists. The send-gate cannot start populating `RuleContext.timezone` from a person-specific signal until both surfaces ship.

A third concern surfaces here: the cooldown DST property test (`tests/test_policy_cooldown.py::TestDSTSafetyProperty`) asserts that cooldown verdicts are tz-invariant. This is the contract that cooldown's UTC-only design rests on. Sending-window rules invert the contract — their verdicts must depend on tz. Without an inverse property test, a future refactor that drifted cooldown into tz-dependence (or sending-window into tz-invariance) could go unnoticed until a customer-visible bug. The two contracts must fence each other in.

Risk this ADR mitigates by design: **R009** (sending at off-hours / weekends damages relationship + deliverability).

## Decision

**Two factory rule classes** in a new module `orchestrator/policy/sending_window.py`, one per dimension of the sending-window concept:

| YAML discriminator | Class | Role |
|---|---|---|
| `sending-window.local-time-of-day` | `LocalTimeOfDayRule` | Block when recipient's local time-of-day is outside `[start_local, end_local)`. Supports midnight-wrapping windows (`22:00 → 06:00`) for night-shift / off-hours patterns. |
| `sending-window.day-of-week` | `DayOfWeekRule` | Block when recipient's local weekday is not in `allowed_days`. Standard B2B pattern: `[mon, tue, wed, thu, fri]`. |

**Local-time math, with UTC handoff to cooldown.** Both rules convert `ctx.now` (UTC, contractually per ADR-0001 §Decision item 1 and ADR-0002 §Decision) to the recipient's local timezone via `zoneinfo.ZoneInfo(ctx.timezone)`. The conversion happens in a new shared helper `_helpers._local_now(ctx)` so both rule classes use identical logic. Cooldown's UTC math (ADR-0002) is unchanged — the two regimes are complementary, not overlapping.

**Boundary semantics: half-open interval `[start, end)`.** `LocalTimeOfDayRule`'s window matches the cooldown `DomainThrottleRule` lower-end-inclusive convention (ADR-0002) and the cross-channel `CrossChannelTouchRule` boundary (ADR-0003 CC-06). Concretely: `start_local <= local_now < end_local`. A send at exactly `09:00:00` is inside the 09:00-17:00 window; a send at exactly `17:00:00` is outside. Boundary tests in `tests/test_policy_sending_window.py::TestLocalTimeOfDayRule` (`test_at_start_boundary_allows`, `test_at_end_boundary_blocks`, `test_one_microsecond_before_end_allows`) pin the `<=` vs `<` choice on both ends.

**Midnight-wrapping windows.** When `start_local > end_local`, the window is interpreted as wrapping midnight: in-window iff `local_now >= start OR local_now < end`. So a `22:00 → 06:00` window allows sends at 23:00 (after start, before midnight) and at 02:00 (after midnight, before end). Tested by `TestWindowWrapsMidnight`.

**Degenerate windows refuse, not allow.** `start_local == end_local` (LocalTimeOfDay) and `allowed_days == []` (DayOfWeek) both yield `Block`. The asymmetric-failure-cost principle compels this: a typo'd YAML producing an empty window should refuse every send, not open the floodgates. The `detail.degenerate` field surfaces this in `policy_blocked` events so audit can distinguish a typo-induced block from an in-spec block.

**DST conventions (spring-forward, fall-back).**

* **Non-existent local times (spring-forward day, e.g. 02:30 PST on the day DST starts):** `zoneinfo`'s default `fold=0` behavior applies — the helper does no special-casing. Any UTC instant that would have mapped to a skipped wall time resolves to the post-jump local time (03:30 PDT). The rule sees a well-defined local time-of-day and returns a deterministic verdict. The contract is documented in `_helpers._local_now` so a future refactor that "fixes" non-existent times by raising knows it's breaking the contract.
* **Ambiguous local times (fall-back day, e.g. 01:30 occurring twice):** the rule reads only `local_now.time()`. Both UTC instants on either side of the fold produce the same local time-of-day, so the verdict is naturally identical. No fold handling needed.

The DST tests `TestDSTNonExistentTime` and `TestDSTAmbiguousTime` pin these conventions concretely.

**Unparseable `ctx.timezone` → restrictive Block.** If `_local_now` raises `UnparseableTimezoneError` (the documented error class added in `_helpers.py`), the rule converts it into a `Block` with `detail.invalid_timezone: true`. The tz inference layer is supposed to ensure every `RuleContext` carries a valid IANA name; this defense-in-depth path exists so a bug elsewhere doesn't silently allow sends past a broken sending-window rule.

**Both rules support `block_when:`.** Like cooldown rules (ADR-0002) and the cross-channel rule (ADR-0003), sending-window rules accept a `block_when:` filter to scope themselves to specific channels / registers. The shared `_block_when_matches` helper applies. Unlike suppression rules (ADR-0004 §Alternative 8 explicitly refused `block_when:` on kill-switch semantics), sending-window rules are not kill switches — they encode operator-tunable timing policy, where scoping by register or channel is a legitimate need.

### Timezone inference

**New module `orchestrator/policy/tz_inference.py`** with public surface:

* `infer_timezone(country: str | None) -> str` — free-form country signal → IANA name.
* `DEFAULT_TIMEZONE = "America/Los_Angeles"` — the fallback per ADR-0002 §5 resolution row (and PILLAR-PLAN §5).
* `COUNTRY_CODE_TO_TIMEZONE: dict[str, str]` — ISO 3166-1 alpha-2 → IANA, ~50 entries covering the ICP audience.
* `COUNTRY_NAME_TO_TIMEZONE: dict[str, str]` — full English names + common aliases (`"USA"`, `"UK"`, `"Great Britain"`) → IANA.

The function tolerates three input forms — alpha-2 code, full name, `"City, Country"` location string — because Person notes scraped from LinkedIn use all three inconsistently. When the input is a multi-comma location string (`"London, England, UK"`), the trailing non-empty segment is treated as the country candidate.

**Where the country signal lives: `identity_keys.country`.** Added as a new field on `orchestrator.identity.IdentityKeys` in this same commit. The field is **not a match key** — two people sharing a country do not match on identity. It is stored on `IdentityKeys` only so the send-gate's existing `identity.read_person_keys(person_path)` call returns it alongside the rest of the person-shaped data without a second I/O pass.

**`identity.read_person_keys` parses country with precedence:**

1. `identity_keys.country` in the frontmatter (canonical going forward).
2. Top-level `location:` (per the current `skills/research-prospect/SKILL.md` schema). Accepts both string form (`"San Francisco, USA"`) and dict form (`{city: "San Francisco", country: "USA"}`) — the most common existing-notes shapes.

The fallback to `location:` ensures every existing Person note benefits from inference immediately, without waiting on a Pillar B migration. When Pillar E (discovery quality + lineage) lands and starts populating structured `identity_keys.country` directly, the precedence-1 path activates and the precedence-2 fallback becomes vestigial.

**The send-gate caller wires inference in `_build_rule_context`** (`skills/send-outreach/scripts/send_queued.py`). Before this ADR, the gate hardcoded `_DEFAULT_RECIPIENT_TIMEZONE = "America/Los_Angeles"`; that constant is removed in this commit. The new call shape:

```python
recipient_tz = _policy.tz_inference.infer_timezone(keys.country)
return _policy.RuleContext(..., timezone=recipient_tz, ...)
```

### Cooldown DST property test must continue to hold

Week 3 makes `RuleContext.timezone` semantically load-bearing for the first time. If a refactor accidentally leaked tz consultation into a cooldown rule, the cooldown DST property test (`tests/test_policy_cooldown.py::TestDSTSafetyProperty`) would fail.

The complementary property test `tests/test_policy_sending_window.py::TestTimezoneDependence` asserts the opposite contract: sending-window verdicts MUST depend on tz. The two tests fence in the contract — a regression in either direction surfaces immediately.

A regression sentinel `TestCooldownDSTPropertyStillHolds::test_no_duplicate_register_invariant_to_tz` is mirrored into `test_policy_sending_window.py` so a Week-3-introduced regression in cooldown lands at the right test file.

### ADR numbering shift

ADR-0002 §References listed followups as ADR-0005=budget, ADR-0006=sending-window, ADR-0007=tier. This ADR pulls sending-window forward to ADR-0005 (so the rule class and the field it consumes land in the same number). Downstream numbering shifts +1:

* ADR-0006 → budget rules (was ADR-0005)
* ADR-0007 → tier rules (was ADR-0006)
* (ADR-0007 originally numbered tier; no shift needed there)

The References sections of ADR-0002, ADR-0003, and ADR-0004 are updated in this same commit, and `docs/adr/README.md` gains the ADR-0005 row.

## Alternatives considered

### Alternative 1: Use UTC + a per-rule `utc_window:` field instead of local-time-of-day
A rule could specify `utc_start: "17:00", utc_end: "01:00"` instead of `start_local`/`end_local`. **Rejected because:** the entire point of sending-window rules is recipient circadian rhythm. Operator-UTC windows make no sense to the recipient — a 17:00-01:00 UTC window is 09:00-17:00 PT but 02:00-10:00 in Tokyo. Forcing operators to manually compute UTC windows per timezone breaks the value proposition. Local-time-of-day IS the rule shape this concept exists to express.

### Alternative 2: Use `ctx.now`'s tz directly
`ctx.now` is contractually UTC per ADR-0001 §Decision item 1 and ADR-0002 §Decision. A rule could read `ctx.now.astimezone(some_recipient_tz)` without `RuleContext.timezone` existing as a separate field. **Rejected because:** the cooldown DST property test depends on `ctx.now` being UTC. Mixing the tz of `ctx.now` between rule classes would break the property's "for any tz, cooldown's verdict is identical" assertion. Keeping `ctx.now` UTC and adding a separate `timezone` field for the rules that need recipient-local math preserves both contracts.

### Alternative 3: Defer country→tz inference to Pillar E (discovery quality + lineage)
Pillar E formalizes `identity_keys.discovery_lineage:` and could fold country into that work. **Rejected because:** without tz inference, the sending-window rule class has no way to know the recipient's tz. Shipping the rule class without a country signal source would be the same anti-pattern Week 2 already rejected for the cross-channel rule (ADR-0003 §Alternative 1) — landing a rule shape without the data it joins on means the rule's path is never exercised until a much-later pillar. The cross-channel ADR's rationale applies here verbatim: the rule's behavior on the default config must be verifiable from day 0.

### Alternative 4: Single rule class `SendingWindowRule` with a `dimension:` discriminator
One class, dispatching internally between `time-of-day` and `day-of-week` modes. **Rejected because:** the field shapes differ (start/end vs. allowed_days), the validation differs (HH:MM strings vs. weekday name aliases), the DST semantics differ slightly (time-of-day is sensitive to wall-clock; day-of-week to calendar date crossing midnight in tz). Merging them into a switch-on-mode class shrinks code by maybe 30 lines but loses each class's focused docstring + dedicated test surface. Same trade-off as ADR-0004's three suppression classes — the cost is paid in two discriminators, not two concepts.

### Alternative 5: Store country on `PersonInfo` (vault.py) instead of `IdentityKeys`
`PersonInfo` already carries name, email, linkedin, status — adding country there is a smaller surface change. **Rejected because:** the send-gate already calls `identity.read_person_keys(person_path)` to get `IdentityKeys`. Adding country to that call's return is a free I/O optimization. Threading country through a second source (`PersonInfo`) means the gate either does a second frontmatter parse (wasteful) or has to coordinate two sources of the same field (fragile). The single-read pattern is also why `identity_keys.country` is documented as the canonical-going-forward source even though it doesn't gate anything else identity-related: it's about *where the data is fetched*, not *what it's used for*.

### Alternative 6: Encode country→tz mapping in a JSON / YAML data file
`config-template/country-timezones.yml` could ship as a data file and `tz_inference` could parse it at module-import time. **Rejected because:** the table is small (~100 entries), hot-path lookup is dict-O(1) without parsing on every invocation, and a Python dict literal can't go missing or parse-fail at runtime. The asymmetric-failure-cost principle: sending-window evaluation must not crash on missing data. Pillar B migration framework handles consumer-side schema evolution; the source table itself is invariant code.

### Alternative 7: Require `country` to be ISO 3166-1 alpha-2 only
The tz_inference module could reject full names and location strings, forcing callers to pre-normalize. **Rejected because:** the only existing source of country data is `Person.location` (a free-form string from research-prospect skill output). A strict ISO requirement would mean every Person note goes through inference's fallback path until a Pillar B migration normalizes existing notes — defeating the value of inference on day 0. Tolerant parsing at the consumer is cheaper than a migration of unknown duration.

### Alternative 8: Raise on unparseable `ctx.timezone` instead of returning Block
Per ADR-0001 §Decision the engine doesn't swallow exceptions — a rule raising bubbles up to the gate caller. The sending-window rule class could raise on `ZoneInfoNotFoundError` and let the gate halt the run. **Rejected because:** an invalid tz string is recipient-data-shape (one Person note has a typo) not policy-shape (the YAML rule is broken). The gate should refuse the one send and log a `policy_blocked` event with `detail.invalid_timezone: true`, not halt the entire run because one Person frontmatter is malformed. Engine-level halt is appropriate for `evaluate` itself crashing (policy outage); per-recipient data malformity is appropriate for per-recipient refusal.

### Alternative 9: Make `start_local`/`end_local` time objects instead of strings
The from_yaml path could parse to `datetime.time` and store the parsed form on the rule. **Rejected because:** YAML doesn't natively know `datetime.time` (only `datetime.datetime`), so the stored shape would diverge from the on-disk form, complicating round-trip. Storing the original string and parsing on each `evaluate` call is cheap (regex match + two `int()` calls) and keeps the YAML form authoritative. Strict validation at from_yaml time catches typos before any send is attempted; runtime parsing is just rebuilding from the already-validated string.

## Consequences

### Positive
- Off-hours / weekend send refusal is one factory rule away. R009 mitigated by design.
- The `RuleContext.timezone` field — semantically inert since ADR-0001 — is now operationally meaningful; every existing context construction site gets recipient-aware tz automatically because the inference layer fills in the default for missing country data.
- Country signal lives on `IdentityKeys` — a single canonical home, queryable from anywhere the gate already touches.
- The cooldown DST property test now has an explicit inverse property (`TestTimezoneDependence`), so future regressions in either direction surface immediately.
- Sending-window rules use the same `block_when:` filter pattern as cooldown + cross-channel — no new YAML schema for operators to learn.
- ADR numbering re-aligned: sending-window is 0005 (the immediate-next number), not 0006 — followups (budget, tier) shift forward consistently.

### Negative
- `IdentityKeys` gains a non-match field (`country`). The dataclass is no longer strictly identity-match data; it's now "identity + non-match-per-person facets we want a single read for." A future contributor expecting the class to be "only what matches identities" will be surprised. Mitigation: the field's docstring explicitly calls out the non-match status, and a follow-up could split into `IdentityKeys` + `PersonFacets` if the surface accumulates. ADR-0004 §Alternative 7 (the prior "no cross-package coupling" stance for suppression) is not violated — suppression doesn't read country; sending-window does — but operators reading the codebase will need to understand that `country` is a payload, not a key.
- The country→tz mapping is opinionated: countries spanning multiple zones (US, RU, AU, BR, CA, CN, ID) pick a single representative zone. A US prospect in New York gets `America/Los_Angeles`-shaped business-hours windows, which is 3 hours off. Mitigation: documented in the module docstring; a future Pillar E enhancement can refine with a state/province signal. Until then, the asymmetric cost is acceptable — a 9-17 LA window translates to 12-20 NY, which is still business hours, just shifted.
- Two factory rules ship in `cooldowns.example.yml` (commented out by default). An operator who doesn't read the comments may be surprised when they uncomment and the rules begin firing. Mitigation: the example YAML's comments explain the activation behavior + the recipient-local semantics.
- Adding `country` to `IdentityKeys` is a schema change to a frozen dataclass. Existing identity tests still pass because the field defaults to `None`, but any future code that does `IdentityKeys(linkedin="...")` positionally (instead of kwarg) would break if we ever change the field order. Mitigation: the dataclass has been kwarg-only in practice; documented as such going forward.

### Neutral / observability
- Sending-window blocks emit the standard `policy_blocked` event (per ADR-0001) with `detail` carrying: `local_time` (HH:MM:SS), `timezone`, `start_local`, `end_local`, `wraps_midnight` for `LocalTimeOfDayRule`; `local_weekday`, `local_date`, `allowed_days`, `timezone` for `DayOfWeekRule`. The funnel CLI (`ledger.py funnel --breakdown rule`) surfaces these as distinct rule categories without new code.
- Risk register R009 moves from `Open` to `Mitigated by design (rules ship in v1 factory ruleset; activate by operator uncommenting in cooldowns.yml)` in the same commit as this ADR.
- The new `_local_now` helper is package-private — it's documented as the only sanctioned path for tz conversion in policy rules, so a code-review reflex of "is this rule consulting tz correctly?" reduces to "does it call `_local_now` or roll its own?"

## Compliance with invariants

- **I1 (single source of truth):** `identity_keys.country` is the SoT for recipient country going forward; the precedence-2 fallback to `location:` is a denormalized read of the same logical state during the transition. No new SoT row is required — the existing "Person identity (id + identity_keys)" row in `docs/SOURCES-OF-TRUTH.md` already covers the identity_keys frontmatter block; `country` is a new field within that block, not a new SoT. The country→tz mapping table in `tz_inference.py` is invariant source code, not state, so it doesn't need a row.
- **I2 (two-phase commit):** Sending-window rules consume only `ctx.now` and `ctx.timezone` — no ledger writes, no external side effects. The two-phase guarantee on send is unchanged.
- **I3 (schema versioning):** Adding `country` to the `identity_keys:` YAML block is an additive schema change with a default of `None`. Existing notes that don't have the field parse identically — no migration is required to keep the gate functional. A future Pillar B migration can backfill `country` from `location:` parsing if operators want the data formally normalized.
- **I5 (observable by default):** Every Block emits `policy_blocked` with the diagnostic shape above.
- **I6 (tests prove invariants):** The Hypothesis property `TestTimezoneDependence` proves tz-dependence; the explicit regression sentinel `TestCooldownDSTPropertyStillHolds` proves cooldown's tz-invariance still holds after Week 3 makes the field load-bearing. The DST edge-case tests (`TestDSTNonExistentTime`, `TestDSTAmbiguousTime`) pin the spring-forward and fall-back conventions concretely.
- **I8 (decisions documented):** This ADR. ADR-0002 §References, ADR-0003 §References, ADR-0004 §References, and `docs/adr/README.md` are updated to reflect the +1 numbering shift in the same commit.

Does not weaken any invariant. The tz-dependence property strengthens I6's coverage of the cooldown/sending-window split.

## Migration / rollout

Greenfield: `orchestrator/policy/sending_window.py` and `orchestrator/policy/tz_inference.py` are new files. The `country` field on `IdentityKeys` has a `None` default; existing tests pass without modification.

The factory `cooldowns.example.yml` is extended with two commented-out sending-window rules. Operators opt in by uncommenting; until they do, the rules are not in the active rule list and never fire. The asymmetric-failure-cost principle (default-off for a new rule shape that could refuse-on-misconfiguration) compels this — once an operator has tuned their YAML, they may activate.

`docs/PILLAR-PLAN.md` §2 Pillar A's package list is updated in the same commit: `sending_window.py` is removed from the outstanding-modules list. `budget.py`, `tier.py`, and `simulation.py` remain outstanding (Weeks 4, 5, 6 — numbering unchanged from PILLAR-PLAN as those are scheduled-week names, not ADR numbers).

Doctor preflight (Phase 5 / Pillar A Week 1 task #6) already validates `cooldowns.yml` structure at install time; once the example file gains sending-window rules (commented-out), preflight covers their structural validity automatically when an operator uncomments — they don't get a separate validation pass for the new rule type.

The `country` field on `IdentityKeys` does NOT trigger an identity migration. Existing Person notes parse the same as before: precedence-1 returns `None` (no `identity_keys.country` set), precedence-2 returns the `location:` field if present, both cases land in `infer_timezone()` which has a robust fallback. A Pillar B migration could normalize existing location strings into structured `identity_keys.country` entries, but that's a quality-of-life improvement, not a correctness requirement.

`RuleContext.timezone` semantics change from "operator-default constant" to "recipient-inferred per send." Every existing test that constructed a `RuleContext` with `timezone="UTC"` or `timezone="America/Los_Angeles"` continues to pass — the field was already shaped as `str` and the value is still a valid IANA name. No test fixtures require modification.

## References

- ADR-0001 (policy engine architecture) — `RuleContext.timezone` field introduced; reserved for sending-window rules per §Decision item 1.
- ADR-0002 (cooldown rules + recipient timezone semantics) — locks the UTC-only cooldown contract this ADR's local-time rules complement. The §5 PILLAR-PLAN resolution row for the `America/Los_Angeles` fallback is the binding source for `tz_inference.DEFAULT_TIMEZONE`.
- ADR-0003 (channel as first-class policy predicate) — channel-as-filter pattern; `block_when:` semantics that sending-window rules also support.
- ADR-0004 (suppression rules + GDPR forget) — sibling rule batch; the deliberate-non-`block_when:` rationale there contrasts with sending-window's deliberate-yes-`block_when:` here (kill switch vs. tunable policy).
- `docs/PILLAR-PLAN.md` §2 Pillar A (Week 3) and §5 (timezone resolution row).
- `docs/RISK-REGISTER.md` R009 (off-hours / weekend sends) — risk this ADR mitigates by design.
- `orchestrator/policy/sending_window.py` — rule classes.
- `orchestrator/policy/tz_inference.py` — country signal → IANA name.
- `orchestrator/policy/_helpers.py` — `_local_now` + `UnparseableTimezoneError`.
- `orchestrator/identity.py` — `IdentityKeys.country` field + `read_person_keys` precedence handling.
- `skills/send-outreach/scripts/send_queued.py:_build_rule_context` — the call site that consumes `tz_inference.infer_timezone(keys.country)`.
- `tests/test_policy_sending_window.py` — rule-class tests, DST edge cases, tz-dependence property test, cooldown-regression sentinel.
- `tests/test_tz_inference.py` — country mapping tests + every-output-is-valid-IANA property test.
- ADR-0006 (budget rules + `cost_incurred` event) — Week 4 sibling; landed 2026-05-18. The sending-window tz-dependence property test continues to hold after Week 4 (regression sentinel in `tests/test_policy_budget.py::TestSendingWindowTzDependenceStillHolds`).
- Followups: ADR-0007 tier rules (Week 5).
