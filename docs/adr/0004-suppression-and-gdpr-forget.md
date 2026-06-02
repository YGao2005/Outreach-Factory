# ADR-0004: Suppression rules + GDPR forget

- **Status:** Accepted
- **Date:** 2026-05-16
- **Pillar:** A (Policy engine — second concrete rule batch) + cross-cutting hook into Pillar J
- **Deciders:** Yang, Claude (architect)

## Context

ADR-0001 established the policy engine; ADR-0002 shipped four cooldown rule classes; ADR-0003 added the cross-channel rule shape. Pillar A's Week 2 deliverable is the **suppression** rule class — the second concrete rule batch — covering CAN-SPAM unsubscribe enforcement, GDPR forget requests, and operator-curated blocklists (spam-trap domains, "do not contact" lists from acquisitions, legal-flagged identifiers).

Two questions the engine left open:

1. **Where do suppression lists live?** Cooldown rules read state from the ledger event stream (which is also where they write `policy_blocked`). Suppression is different: the list of "do not contact" emails, domains, and identity keys is *authored* data, not derived from events. It needs a SoT location separate from the policy YAML, because (a) the cadence of edits is different (a user unsubscribes daily; a cooldown rule changes monthly), (b) the editor is different (an auto-unsubscribe handler in Pillar D writes daily; only the human edits policy YAMLs), and (c) the format is different (a list, not a rule definition). The SoT registry row "Cooldown / suppression / budget policy" in `docs/SOURCES-OF-TRUTH.md` conflates these — this ADR splits suppression off.

2. **What is the GDPR-forget contract?** Pillar J §49–52 promises `policy.py forget --person <id>` purges vault + ledger + caches. The policy engine is the load-bearing seat for the *enforcement* half — once the person is forgotten, no future send may reach them, even if they re-appear in a fresh discovery pass. That enforcement is the suppression list. Pillar J cannot land in Week 49 in a clean state if the suppression-list shape isn't decided in Week 2.

The asymmetric-failure-cost principle (PILLAR-PLAN §0) compels strict suppression semantics: a false negative (refused send to someone who didn't actually unsubscribe) costs one missed conversation; a false positive (send-after-suppression) is a CAN-SPAM violation, a GDPR breach, or a "you said you'd stop emailing me" complaint that ends the operator relationship. Suppression rules **must err on the side of blocking**.

## Decision

**Three concrete rule classes**, one per suppression dimension:

| YAML discriminator | Class | Match dimension |
|---|---|---|
| `suppression.email` | `SuppressEmailRule` | Exact match on `ctx.email` (lowercased on both write + read). |
| `suppression.domain` | `SuppressDomainRule` | Case-insensitive match on the domain portion of `ctx.email`. |
| `suppression.identity-key` | `SuppressIdentityKeyRule` | Canonical-form match on `ctx.person_id`. LinkedIn-shaped values normalize to `in/<slug>` per `orchestrator.identity._normalize_linkedin`. |

**Lists live in `~/.outreach-factory/suppressions/*.yml`**, separate from `~/.outreach-factory/policies/*.yml`. Format:

```yaml
version: 1
emails:
  - foo@example.com
domains:
  - spamtrap.io
identity_keys:
  - in/john-doe
  - https://www.linkedin.com/in/jane-doe   # canonicalized on load
```

Every file carries a `version:` integer (independent from policy schema version — bumping suppression's schema must not force a policy YAML rewrite). Multiple files in the directory union — operators may keep e.g. `acquired-list.yml`, `gdpr-forget.yml`, `legal-blocklist.yml` separately for audit, and the loader merges them.

**Policy YAML references suppression lists by `source:`**:

```yaml
- name: gdpr-email-suppression
  type: suppression.email
  source: gdpr-forget.yml          # relative → ~/.outreach-factory/suppressions/
- name: all-domain-suppression
  type: suppression.domain
  source: {dir: .}                  # merge every *.yml in the directory
```

Relative paths resolve against `~/.outreach-factory/suppressions/`; absolute paths are taken verbatim (useful for tests + sandboxes).

**Canonicalization is symmetric — both on YAML load AND on rule evaluation.** Identity-key entries pass through `_canon_identity_key` (LinkedIn → `in/<slug>`; email → lowercased; everything else → lowercased+stripped) on both write and read so a user authoring the YAML with `https://www.linkedin.com/in/Jane-Doe` matches a `ctx.person_id` of `in/jane-doe` and vice versa.

**GDPR forget path.** Pillar J's `policy.py forget --person <id>` performs four steps in this order:

1. Purge ledger person records (Pillar J owns the purge primitive — not yet implemented; ADR-NNNN at that time will specify the tombstoning approach).
2. **Atomically append the person's `email` / `domain` / `identity_key` entries to `~/.outreach-factory/suppressions/gdpr-forget.yml`** via `suppression.forget_append(...)`. File-level atomicity (write-temp-then-rename) is implemented here in Pillar A; cross-pillar atomicity (purge + append succeed-or-fail together) is Pillar J's responsibility — the forget command must hold a lock spanning both steps and refuse to acknowledge success unless both land.
3. Purge vault Person + Touch notes for the forgotten id.
4. Emit a `gdpr_forget` ledger event with the purge audit trail (Pillar J).

This ADR locks step 2's contract. The other three steps are sketched here for context but specified by future ADRs when Pillar J lands.

**Rule ordering is load-bearing for audit specificity.** Operators should order suppression rules `email → identity-key → domain` so the *most specific* match is the one recorded in the `policy_blocked` event. A person blocked by both an email rule and a domain rule will produce a Block whose `detail.dimension` is `email` (the more specific dimension), preserving an auditable "we blocked this exact recipient, not just anyone at their domain" trail.

## Alternatives considered

### Alternative 1: One generic `SuppressRule` with `dimension:` field
A single class, configured via `dimension: email | domain | identity-key`. **Rejected because:** the three rules have different matching semantics (exact, domain-extraction, canonical form), and merging them forces a switch statement inside `evaluate` that defeats the value of the class boundary. Three distinct classes also let each one document its dimension's gotchas (case-insensitivity, URL canonicalization) in a focused docstring instead of one monster doc.

### Alternative 2: Lists live in the ledger as `suppression_added` events
Append-only suppression entries written as ledger events; rules query via `ledger.query_by_*`. **Rejected because:** suppression is *authored* data (a human or a Pillar D auto-unsubscribe handler types it; not derived from a send/reply event). Putting it in the ledger conflates authored state with derived state, violates the I1 SoT registry's separation (the registry already has separate rows for "Send-history" and "policy"), and makes operators' "show me my suppression list" workflows require a ledger query instead of `cat ~/.outreach-factory/suppressions/*.yml`.

### Alternative 3: Defer suppression entirely until Pillar D (auto-unsubscribe is the driver)
Pillar D's reply classifier is the most prolific writer of suppression entries. Wait until Week 13 to ship suppression rules. **Rejected because:** suppression is needed *now* for the manual case (an operator types "do not contact" entries), for the GDPR-forget contract Pillar J depends on, and for the spam-trap-domain blocklist a fresh OSS install needs from day 0. Auto-unsubscribe is the consumer of an already-existing suppression primitive, not the reason it exists.

### Alternative 4: One file (`suppressions.yml`) instead of a directory
Single file, no merging. **Rejected because:** operators want audit separation — the file Pillar D writes when an unsubscribe lands should not be intermixed with the file Pillar J writes on GDPR-forget, which should not be intermixed with the operator's hand-curated `legal-blocklist.yml`. Directory-merge with one file per author keeps the audit clean (the file's mtime + filename tell the story) and lets a re-application of a legal request overwrite *only that file* without disturbing operator-curated entries.

### Alternative 5: Encode suppression as a hardcoded gate in `gated_send_one` (no rule class)
Suppression is a "kill switch" — every send must check it; making it a configurable rule that can be omitted is dangerous. **Rejected because:** the entire ADR-0001 thesis is that policy is declarative and runs through the engine — bypassing the engine for suppression would (a) split the policy-blocked event shape (now there are two), (b) bypass the simulation mode the engine enables (Pillar A Week 5), and (c) make the live-reload story (Pillar H SIGHUP) incomplete. The "safer to hardcode" intuition is solved by making suppression rules part of the **default** factory `cooldowns.yml` so a greenfield install always has them — see `config-template/suppressions.example.yml` referenced from `config-template/cooldowns.example.yml`.

### Alternative 6: Canonicalize identity keys only on write (not on read)
The YAML stores fully-canonicalized values; the rule's `evaluate` does a plain `in` set test. **Rejected because:** `ctx.person_id` can also be uncanonicalized in edge cases — e.g. a backfilled person whose id was minted before the current canonicalization rules. Symmetric canonicalization (both write + read) is cheap (it's a `lower()` + a regex on the read path) and protects against the long tail of "the SoT and the lookup canonicalization drifted apart" bugs that ADR-0002 wrote down for cooldown rules in a different shape.

### Alternative 7: Import `_normalize_linkedin` from `orchestrator.identity` rather than inlining `_canon_linkedin`
`orchestrator/identity.py` already has a battle-tested `_normalize_linkedin` (used by every Person enrollment + identity merge code path); the suppression module could just call it. **Rejected because:** identity normalization rules can legitimately evolve under Pillar E (discovery quality + lineage) — a future change to identity matching semantics (e.g. recognizing additional URL hosts, handling Unicode slugs differently) could change a Person's stored `id` without intending to change suppression-list lookup behavior. Coupling the two creates an invisible failure mode where editing identity changes who is suppressed. Inlining `_canon_linkedin` is ~30 lines of duplicated parsing — small, well-tested, and lets suppression's canonicalization evolve independently. The cost is paid in a one-time parity audit when Pillar E lands; the benefit is a stable suppression contract for the OSS-release window. (A future ADR may revisit this if the two normalizers actually start diverging in ways that cause user confusion.)

### Alternative 8: Suppression rules support `block_when:` filters like cooldown rules do
The shared `_block_when_matches` helper already lives in `_helpers.py`; suppression rules could accept a `block_when:` to scope themselves to specific channels or registers. **Rejected because:** suppression is a *kill switch*, not a scoped policy. A do-not-contact entry that fires only on email and silently allows the same person to be DMed on LinkedIn is the worst kind of false positive — operationally appearing as compliance, actually leaving the human exposed to the channel switch. CAN-SPAM / GDPR / "stop contacting me" all imply *every channel*; encoding a `block_when:` on suppression would make footgun configurations trivially easy. Suppression rules deliberately fire on every send regardless of channel/register. The cooldown-style scoping is appropriate for cooldown (timing windows are inherently per-channel-pair) and inappropriate for suppression.

## Consequences

### Positive
- CAN-SPAM unsubscribe enforcement is one `policy.evaluate` call away from any send path that already goes through the gate.
- GDPR-forget gets a concrete cross-pillar contract: Pillar J calls `suppression.forget_append(...)` as half of its purge transaction; Pillar A guarantees subsequent sends are blocked.
- Operators may segregate suppression files by author (auto-unsubscribe vs GDPR vs legal vs ops-curated) for audit without code changes.
- The SoT registry gains a dedicated row for suppression — clearer than the conflated "policy" row.
- The three rule classes compose with the existing engine — `policy_blocked` events from suppression are observable in the funnel CLI without new code (per ADR-0001 §Neutral / observability).

### Negative
- Two YAML schema versions now exist (policy `version:` and suppression `version:`) — operators must understand they evolve independently. Mitigation: documented in both example files; migration runner (Pillar B) tracks them separately.
- Three rule classes for what is logically "one suppression concept" looks like over-design until you try to write the generic version (see Alternative 1). The naming convention `suppression.<dimension>` reads cleanly enough that the cost is paid in three discriminators, not three concepts.
- `suppression.forget_append` provides file-level atomicity but not cross-pillar atomicity — a crash between Pillar J's ledger purge and this append leaves the system in a state where the person is purged but not yet suppressed. Mitigation: Pillar J's forget command holds a lock spanning both steps; the lock is the same one the send-gate consults, so no send can race the forget into a refused-after-forget gap. ADR for Pillar J's forget transaction will lock the rest of the contract. The file-level write-temp-then-rename is **single-writer safe only** — two concurrent calls would race on the fixed `.tmp` filename; documented in `forget_append`'s docstring and again here because the lock requirement is operationally load-bearing.
- Symmetric canonicalization costs one regex per `identity-key` rule evaluation. Acceptable — suppression lists are bounded (low hundreds of entries in practice).
- Suppression rules **do not** accept a `block_when:` filter (cooldown rules do). A future contributor expecting parity with cooldown rules will reach for it and find it missing. This is deliberate (see Alternative 8) — kill-switch semantics demand every-send firing. Operators wanting register-specific or channel-specific suppression should encode the scoping in their *list files* (e.g. `email-only-suppressions.yml` referenced from one rule) rather than in `block_when:` on the rule itself. Documented in `suppression.py` module docstring + the example YAML.
- `_canon_linkedin` is inlined in `suppression.py` and may drift from `orchestrator.identity._normalize_linkedin` (see Alternative 7). One-time parity audit required when Pillar E ships changes to identity normalization.

### Neutral / observability
- Suppression blocks emit the standard `policy_blocked` event (per ADR-0001) with `detail` carrying `dimension` (`email` / `domain` / `identity_key`), the matched value, and the source file path so audit can answer "which file blocked this send?" without rebuilding state.
- The funnel CLI surfaces suppression refusals as a distinct category via the rule discriminator — no new dashboard code.
- The SoT registry row `~/.outreach-factory/suppressions/` is added in the same commit as this ADR (it was missing — the prior "Cooldown / suppression / budget policy" row conflated three things).

## Compliance with invariants

- **I1 (single source of truth):** `~/.outreach-factory/suppressions/*.yml` is the SoT for "may we contact this recipient at all?" decisions. Distinct from `~/.outreach-factory/policies/*.yml` (the SoT for cooldown / budget / window rules) because the cadence + editor + format differ. `docs/SOURCES-OF-TRUTH.md` gains the new row in the same commit.
- **I2 (two-phase commit):** Suppression rules do not write events directly — they only emit `policy_blocked` through the engine path that the gate already two-phases. The GDPR-forget operation IS a write, and it is two-phased (write-temp + rename) at the file level. The cross-pillar two-phase (ledger purge + suppression append) is Pillar J's contract.
- **I3 (schema versioning):** Suppression YAML carries `version:`; migrations for the suppression schema live in `orchestrator/migrations/policy/` alongside the policy YAML migrations (Pillar B), tagged with which schema they target.
- **I5 (observable by default):** Every Block emits `policy_blocked` with the dimension + matched value in `detail`.
- **I6 (tests prove invariants):** `tests/test_policy_suppression.py` covers each rule class's allow/block + canonicalization + empty-list-allows + YAML round-trip + the GDPR-forget atomic-append happy path.
- **I8 (documented decisions):** This ADR.

Does not weaken any invariant. The split of the SoT row from the conflated "policy" row strengthens I1's clarity.

## Migration / rollout

Greenfield: three new rule classes in a new module `orchestrator/policy/suppression.py`; one new directory shape `~/.outreach-factory/suppressions/`; a new factory example `config-template/suppressions.example.yml`. No existing code or data to migrate.

The factory `config-template/cooldowns.example.yml` is **not** modified to reference the suppression rules in this commit — operators opt in by adding a `- type: suppression.<dim>` entry to their own `cooldowns.yml`. (Rationale: shipping a default suppression rule that references a possibly-missing file complicates the doctor preflight; the suppression example file documents the YAML shape, and Pillar D will wire the auto-unsubscribe path that makes the rules load-bearing for an OSS user.)

Doctor preflight (Phase 5 / Pillar A Week 1 task #6) will be extended in a follow-up to validate suppression YAML structure at install time — out of scope for this commit; tracked in the cooldown-loader's existing TODO surface.

`RuleContext` is unchanged. `LedgerLike` is unchanged. The engine is unchanged.

## References

- ADR-0001 (policy engine architecture) — engine surface, rule registration.
- ADR-0002 (cooldown rules + recipient timezone) — same-shape factory rule pattern this ADR mirrors.
- ADR-0003 (channel as first-class policy predicate) — sibling Week-2 work.
- `docs/PILLAR-PLAN.md` §2 Pillar A (Week 2) and §2 Pillar J (GDPR-forget driver).
- `docs/RISK-REGISTER.md` R010 (Regulatory shift) — this ADR delivers half of the mitigation Pillar J inherits.
- `docs/SOURCES-OF-TRUTH.md` (new row for `~/.outreach-factory/suppressions/` added in the same commit).
- `orchestrator/policy/suppression.py` — rule classes + IO + `forget_append`.
- `orchestrator/identity.py:_normalize_linkedin` — canonicalization contract this ADR matches (inlined as `_canon_linkedin` to avoid the cross-package dependency, per Alternative 6's rationale).
- ADR-0005 (Sending-window rules + recipient timezone inference) — Week 3 sibling; uses the shared `_helpers._block_when_matches` helper this ADR co-introduced. The deliberate `block_when:` opt-out on suppression rules (§Alternative 8) contrasts with sending-window's deliberate opt-in: kill switches refuse scope, tunable policy embraces it.
- ADR-0006 (budget rules + `cost_incurred` event) — Week 4 sibling; landed 2026-05-18. The deliberate-yes-`block_when:` on budget rules (ADR-0006 §Alternative 4) contrasts with this ADR's deliberate-no-`block_when:` (§Alternative 8): budget is tunable policy, suppression is a kill switch.
- Followups: ADR-0007 tier rules (Week 5). (Numbering shifted +1 from this ADR's original list to accommodate sending-window landing at 0005; see ADR-0005 §ADR numbering shift.) ADR-NNNN (Pillar J): GDPR-forget transaction protocol.
