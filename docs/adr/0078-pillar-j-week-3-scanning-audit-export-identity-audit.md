# ADR-0078: Pillar J Week 3 — supply-chain scanning + audit-log export + identity-key audit + catalog extension

- **Status:** Accepted
- **Date:** 2026-05-29
- **Pillar:** J (Security + compliance)
- **Deciders:** Ralph (autonomous loop), per ADR-0076 D387 trajectory row Week 3

## Context

ADR-0076 D387 pins Week 3 of Pillar J as four substrate reds: **J2/J3**
(supply-chain scanning), **J8** (audit-log export), **R001** (identity-key
mutation audit, assigned into Pillar J per D383), and the **catalog extension**
that moves the four `SECURITY_NEW_EVENT_CLASSES` into
`observability.EVENT_CLASS_CATALOG` (mirror-constants parity per ADR-0050 D272).
Week 1 shipped the `NotImplementedError` signatures + the closed-sets; this week
fills the automatable bodies. J5/J6 stay FENCED (ADR-0080, human-gated).

Each red is a golden-path / coherence assertion in
`tests/golden_path/test_l0_spine_liveness.py::TestGoldenPathL0SecurityCompliance`
and `tests/test_multi_channel_coherence.py::TestPillarJSecurityCompliance*`.

## Decision

**D390 — J2/J3 supply-chain scanning is repo-state config, not a ledger event.**
Ship `.pre-commit-config.yaml` (gitleaks secret scanning, J2),
`.github/dependabot.yml` (pip × {orchestrator, skills/send-outreach, root-dev} +
github-actions, J3), and `.github/workflows/osv-scanner.yml` (OSV dependency-CVE
scan via the official reusable workflows, J3). These emit NO ledger events
(`SECURITY_SCANNERS` documents the closed-set); the golden-path assertion is a
repo-state proxy — *the scanning machinery exists + runs*. Human disposition of
findings ("zero unpatched CVEs > 14d") is the v1-release gate (D384), not a code
assertion. The gitleaks/osv refs are operator-maintained release-gate items.

**D391 — J8 audit-log export is read-only + redact-by-default + pseudonymizing.**
`export_audit_log` walks the ledger (optionally `since`/`until`-filtered by the
same ISO string compare reconcile uses), writes a jsonl/csv file, then appends
EXACTLY ONE `audit_log_exported` marker — the READ-ONLY contract per ADR-0059
D325 (the funnel-CLI precedent): it never rewrites prior events. `n_events`
counts the covered (pre-marker) events. Redaction (default `redact=True`)
replaces each value of the closed-set `_AUDIT_REDACT_FIELDS` with a stable
`sha256:<12hex>` token. The set covers person-resolving identifiers
(`person_id`, **`intent_id`** — it embeds the person_id as `snd_<pid>` in the
harness, so a person_id-only redaction would leak the substring), contact
handles, per-channel external message/thread ids, and the operator-confidential
free-text fields (ADR-0038 D182 + I8). Hashing (not dropping) preserves
within-export correlation; it is pseudonymization, not salted anonymization
(v2). The closed-set errs toward over-redaction per the asymmetric-failure-cost
principle (a leak costs more than a thinner audit row).

**D392 — R001 emits `identity_keys_modified` carrying cleartext `person_id`;
that is consistent, not a leak.** `build_identity_keys_modified_payload` returns
`type` + `person_id` + `before_keys` + `after_keys` + `actor`
(`operator`|`reconcile`|`enrollment`, refuse-loud otherwise) + `modified_at_ts`
+ `_emitted_by="security"`. The in-ledger audit row carries `person_id` cleartext
exactly as every other ledger event does (the ledger is the SoT) — the
no-cleartext-PII invariant applies to EXPORTS (J8 redacts) and the `gdpr_forget`
tombstone (hashed `person_ref`, because the point is forgetting), NOT to
in-ledger audit rows. `detect_identity_keys_drift` flags a Person whose vault
frontmatter identity keys diverge from the ledger keys-view so reconcile
surfaces manual-merge drift that has no audit trail today. The reverse-merge
`identity.py split` tooling is deferred to v2 (D383).

**D393 — the four `SECURITY_NEW_EVENT_CLASSES` join `EVENT_CLASS_CATALOG`.**
Mirror-constants parity (ADR-0050 D272): the catalog enumerates known classes;
Week 1's disjoint-from-catalog invariant (`test_security_new_event_classes_frozenset`)
flips to a subset invariant at Week 3 (the classes are now cataloged), and
`test_security_event_classes_catalog_extension` un-skips. `auth_token_refreshed`
is NOT among the four — it is Pillar I's reused class (ADR-0070 D371), already
cataloged.

## Alternatives considered

### Alternative 1 (J8): default-deny redaction (keep a closed safe-field set)
Keep only known-structural fields, redact everything else. **Rejected:** it
silently drops useful audit fields a new event class adds, degrading the audit
without warning. Default-allow with an over-broad redact closed-set keeps audit
richness while the asymmetric-cost bias (hash anything that correlates) holds
the privacy line; a missed field is a reviewable closed-set edit, not silent.

### Alternative 2 (J8): drop PII fields instead of hashing
Delete redacted keys. **Rejected:** destroys within-export correlation (which
events concern the same pseudonymous subject) that a compliance reviewer needs.
Stable hashing keeps correlation without cleartext.

### Alternative 3 (R001): hash `person_id` in the audit event too
Mirror the `gdpr_forget` tombstone. **Rejected:** an identity-mutation audit
whose subject is unidentifiable is useless to reconcile drift-detection, which
correlates the row to a Person by `person_id`. The redaction boundary is the
export, not the ledger.

## Consequences

### Positive
- The J2/J3/J8/R001 substrate lands; only J5/J6 (FENCED) remain before the W4
  substrate-Stable flip.
- Manual identity merges gain a ledger audit trail + a reconcile drift flag.

### Negative
- The osv/gitleaks pinned refs need human maintenance at each release gate
  (Dependabot github-actions bumps the workflow `uses:` ref but not pre-commit
  revs).

### Neutral / observability
- `EVENT_CLASS_CATALOG` grows by four; `collect_event_class_snapshots` now
  recognises the Pillar J classes rather than flagging them uncatalogued.

## Compliance with invariants
- **I2 (append-only):** J8 only appends its marker; never mutates prior events.
- **I8 / privacy:** J8 redact-by-default; R001's cleartext `person_id` is
  in-ledger only (consistent with the SoT), never exported in cleartext.
- **Closed-set (R031):** `_AUDIT_REDACT_FIELDS`, `AUDIT_LOG_EXPORT_FORMATS`,
  `SECURITY_SCANNERS` are closed-sets.
- **Refuse-loud (ADR-0001 D2):** bad `out_format` / `actor` raise `ValueError`.

## Migration / rollout
Additive. The catalog extension is governed by this ADR (D393). No data
migration; `detect_identity_keys_drift` is read-only.

## Pre-commit verification

Derive, don't assert — signatures pasted from `inspect`, not memory.

| Claim in this ADR | Verification command | Output (pasted) |
|---|---|---|
| `export_audit_log` keyword-only after `led`, `redact=True` default | `python -c "import inspect; from orchestrator import security as s; print(inspect.signature(s.export_audit_log))"` | `(led: 'Any', *, out_path: 'Path', out_format: 'str' = 'jsonl', since: "'Optional[datetime]'" = None, until: "'Optional[datetime]'" = None, redact: 'bool' = True, now: "'Optional[datetime]'" = None) -> 'dict[str, Any]'` |
| `build_audit_log_exported_payload` shape | `python -c "import inspect; from orchestrator import security as s; print(inspect.signature(s.build_audit_log_exported_payload))"` | `(*, exported_at_ts: 'str', n_events: 'int', out_format: 'str', redacted: 'bool', since_ts: 'Optional[str]' = None, until_ts: 'Optional[str]' = None) -> 'dict[str, Any]'` |
| `build_identity_keys_modified_payload` shape | `python -c "import inspect; from orchestrator import security as s; print(inspect.signature(s.build_identity_keys_modified_payload))"` | `(*, person_id: 'str', before_keys: 'list[str]', after_keys: 'list[str]', actor: 'str', modified_at_ts: 'str') -> 'dict[str, Any]'` |
| `detect_identity_keys_drift` shape | `python -c "import inspect; from orchestrator import security as s; print(inspect.signature(s.detect_identity_keys_drift))"` | `(led: 'Any', *, vault_dir: 'Path', now: "'Optional[datetime]'" = None) -> 'list[dict[str, Any]]'` |
| `EMITTED_BY` is `"security"` | `python -c "from orchestrator import security as s; print(s.EMITTED_BY)"` | `security` |
| `AUDIT_LOG_EXPORT_FORMATS` | `python -c "from orchestrator import security as s; print(sorted(s.AUDIT_LOG_EXPORT_FORMATS))"` | `['csv', 'jsonl']` |
| `Ledger.append` / `all_events` | `python -c "import inspect; from orchestrator.ledger import Ledger as L; print(inspect.signature(L.append), inspect.signature(L.all_events))"` | `(self, event: 'Event \| dict') -> 'dict' (self) -> 'list[Event]'` |

## References
- ADR-0076 (Pillar J foundation; D377-D387 trajectory, D383 R001-into-J, D384 two-tier Stable)
- ADR-0059 D325 (funnel-CLI READ-ONLY contract precedent)
- ADR-0050 D272/D273 (mirror-constants parity; catalog disjointness)
- ADR-0038 D182 + I8 (operator-confidential free-text fields)
- `.planning/RALPH-BLOCKED.md` (J5/J6 FENCED)
- Enforced in `orchestrator/security/__init__.py`, `orchestrator/observability.py`
