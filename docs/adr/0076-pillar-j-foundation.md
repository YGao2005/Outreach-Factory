# ADR-0076: Pillar J foundation — security + compliance primitive shape, GDPR-forget crypto-shred decision, encrypted-at-rest keystore decision, CAN-SPAM gap scope, R001 assignment, two-tier Stable gate, load-bearing invariants, cross-pillar audit, per-week trajectory

- **Status:** Accepted
- **Date:** 2026-05-28
- **Pillar:** J (Security + compliance — Week 1 foundation)
- **Deciders:** Yang, Claude (architect)

## Context

ADRs 0001-0008 shipped Pillar A (policy engine), including **ADR-0004 (suppression + GDPR-forget)** which pinned the `forget --person` cross-pillar transaction shape and shipped the suppression-enforcement half (`suppression.forget_append`, already in `orchestrator/policy/suppression.py:276`). ADRs 0009-0013 shipped Pillar B (migration framework). ADRs 0014-0024 shipped Pillar C (multi-channel coherence — the per-channel two-phase commit with `extra_headers` + `body_footer` send seams). ADRs 0025-0031 shipped Pillar D (reply + conversation handling — including `auto_unsubscribe` which **already enforces suppression-on-unsubscribe**). ADRs 0032-0037 shipped Pillar E (discovery quality + lineage). ADRs 0038-0049 shipped Pillar F (voice corpus + FIVE-layer hallucination defense). ADRs 0050-0059 shipped Pillar G (observability — OTel/Prometheus/Grafana + the READ-ONLY funnel CLI contract per ADR-0059 D325). ADRs 0060-0069 shipped Pillar H (daemon + dispatcher). **ADR-0070 shipped Pillar I (multi-tenant + OSS hardening)** — Pillar I is Stable as of 2026-05-28 (per `.planning/RETRO-pillar-i.md`); its Week 2-6 surfaces (`orchestrator/multi_tenant/`, the Docker container runtime, the init wizard, the `orchestrator/ci/` cochange-discipline check) threaded into the golden path without per-week ADR files (per the RALPH-PROMPT §7 ceremony guard). **The highest decision-ID across all ADRs is D376** (ADR-0070); Pillar J's decisions begin at **D377**.

Pillar J — Security + compliance (`docs/PILLAR-PLAN.md` §2 Pillar J, Weeks 49-52) — is the **terminal pillar + the OSS-release gate**. Its binding exit criterion is *"zero unpatched CVEs > 14d; pen-test report with all findings closed; legal sign-off on GDPR + CAN-SPAM posture."* The PILLAR-PLAN §2 deliverables are J1-J9: OAuth token rotation (J1, R002 mitigation); secret scanning in pre-commit / gitleaks (J2); dependency vuln scanning / dependabot + osv-scanner (J3); SLSA supply-chain attestation (J4); encrypted-at-rest credentials (J5); GDPR `policy.py forget --person` (J6); CAN-SPAM physical-address footer + one-click unsubscribe header (J7); audit-log export (J8); external pen-test (J9).

Per the golden-path harness spec (`.planning/GOLDEN-PATH-HARNESS.md` §5), the Pillar J golden-path assertion is: *"send carries CAN-SPAM footer + `List-Unsubscribe` header; `forget --person` purges persona (tombstone) leaving audit."* Per the Pillar J handoff (`.planning/HANDOFF-pillar-j.md`), the Ralph-able subset is **J1/J2/J3/J8** (+ J7 after a gap-verify), and **J5/J6 each need a design decision before they can be built**, while **J9 + legal are non-automatable**. This Week 1 foundation makes those decisions so the per-week + the FENCED builds do not guess them.

**Three pre-existing surfaces re-scope the handoff's nine items** (verified — see §"Pre-commit verification"):

1. **J6 is more decided than the handoff implies.** ADR-0004 §"GDPR forget path" already locks the four-step transaction (purge ledger → atomic suppression append → purge vault → emit `gdpr_forget`) under one lock; step 2 (`forget_append`) is shipped. ADR-0004 explicitly deferred **only step 1's tombstoning approach** ("ADR-NNNN at that time will specify the tombstoning approach"). D380 is that ADR-NNNN.
2. **J7 is a narrow gap.** `gmail_client.GmailClient.send_email` already accepts `extra_headers` + `body_footer`; `auto_unsubscribe` already enforces suppression-on-unsubscribe. The genuine gap is only the **footer content** + the **`List-Unsubscribe` / `List-Unsubscribe-Post` header injection** — not the suppression machinery. D381 scopes J7 to exactly that.
3. **J1's event class already exists.** ADR-0070 D371 enumerated `auth_token_refreshed` in `TENANT_NEW_EVENT_CLASSES` (Pillar I pre-provisioned it); it is already in `EVENT_CLASS_CATALOG`. J1 EMITS it rather than inventing R002's working-name `oauth_rotated`. D377 keeps `SECURITY_NEW_EVENT_CLASSES` disjoint-from-catalog accordingly.

The six concerns this ADR's design resolves: (1) the security-primitive package shape before per-week bodies; (2) **the J5 encrypted-at-rest key-management decision** (Keychain vs OS-keyring vs passphrase); (3) **the J6 GDPR-purge tombstoning decision** (the hard append-only-vs-erasure call); (4) the J7 gap scope; (5) **R001's disposition** (the Sev-1 OPEN identity false-merge risk — assign or defer); (6) **the Pillar J Stable gate** (the real exit criterion is non-automatable, so when can the autonomous loop declare J done?). Plus the per-pillar-foundation deliverables (load-bearing invariants, cross-pillar audit, exit-criterion vehicle scope, per-week trajectory) carried forward from Pillar D/E/F/G/H/I Week 1.

The Pillar G framework-adoption surfaces, the Pillar H daemon surfaces, the Pillar I per-tenant surfaces, the Pillar F Layer 5 backstop, the append-only ledger invariant (I2), the privacy invariant (I8), and the brand-and-legal-liability invariant all preserve with FULL weight; the Pillar A-I binding exit-criterion tests STAY GREEN.

## Decision

### D377. `orchestrator/security/` package shape — module + dataclass + closed-sets + signatures

Pillar J ships the `orchestrator/security/` package (NEW Week 1; Weeks 2-4 + the FENCED builds ship the bodies). The Week 1 commit ships: the `SecurityConfig` frozen dataclass; the closed-sets `SECURITY_NEW_EVENT_CLASSES` (4), `CREDENTIAL_KEYSTORE_BACKENDS` (2), `AUDIT_LOG_EXPORT_FORMATS` (2), `SECURITY_SCANNERS` (3), `CANSPAM_REQUIRED_HEADERS` (2); the `CredentialKeystore` Protocol; and the J1/J5/J6/J7/J8/R001 primitive + emit-factory signatures raising `NotImplementedError`.

**FOUR new event classes** at `SECURITY_NEW_EVENT_CLASSES` — `gdpr_forget`, `audit_log_exported`, `identity_keys_modified`, `credentials_reencrypted`. Per ADR-0050 D273, they are EMITTED-but-not-yet-CONSUMED and so MUST be **disjoint** from `EVENT_CLASS_CATALOG` at Week 1; the Week 3 catalog extension (ADR-0078) moves all four into the catalog per the per-pillar mirror-constants-parity discipline. **`auth_token_refreshed` is NOT in this set** — it is already cataloged (ADR-0070 D371; Pillar I pre-provisioned it); J1 is its first emitter.

The privacy invariant per I8 + ADR-0070 D375(a) holds across every Pillar J surface: `gdpr_forget` carries a `person_ref` HASH (never cleartext `person_id` — the person is, by definition, forgotten); `audit_log_exported` is redact-by-default; `SecurityConfig` holds only operator config (addresses, URLs, backend names, paths).

### D378. J2 + J3 supply-chain scanning — config surfaces (gitleaks pre-commit + dependabot + osv-scanner)

J2 (secret scanning) + J3 (dependency vuln scanning) ship as **config + CI surfaces**, NOT spine primitives — they emit no ledger events. J2 = a `gitleaks` hook in `.pre-commit-config.yaml` (builds on the Pillar I W5 CI surface in `orchestrator/ci/`). J3 = `.github/dependabot.yml` + an `osv-scanner` GitHub Actions workflow. `SECURITY_SCANNERS = {"gitleaks", "dependabot", "osv-scanner"}` is the documentation closed-set. The "zero unpatched CVEs > 14d" exit criterion's automatable proxy is *the scanning machinery exists + runs in CI*; the human disposition of findings is the v1-release gate (D384). Week 3 (ADR-0078).

### D379. J5 encrypted-at-rest credentials — OS-keyring with Argon2id passphrase fallback

The credential keystore is **the OS keyring (`keyring` library: macOS Keychain / Linux Secret Service / Windows Credential Locker) when present, with an Argon2id passphrase-derived key fallback** for Docker / CI / headless environments. `CREDENTIAL_KEYSTORE_BACKENDS = {"os_keyring", "passphrase_argon2id"}`. Rationale: the OSS target is cross-platform, so a macOS-only keystore is a non-starter; and **the Pillar I per-tenant Docker container has no OS keyring**, so the passphrase fallback is not optional — it is mandatory for the multi-tenant container model shipped in ADR-0070 D372. The master key encrypts per-tenant OAuth tokens at rest and (coupled to D380) the per-person data-encryption keys. This is a **FENCED build** (depends on real key-management correctness a human verifies, like the Pillar I W4 OAuth precondition) — ADR-0080 ships the body; this ADR pins the decision so the build does not re-litigate it.

### D380. J6 GDPR `forget` step-1 — tombstone event + crypto-shred (NOT redaction-on-read, NOT ledger rewrite)

The append-only ledger (I2) forbids deletion, so "purge ledger person records" (ADR-0004 step 1) is achieved by **crypto-shredding**: person-identifying event fields are encrypted at rest under a per-person data-encryption key (DEK, from the D379 keystore); `forget --person` **destroys that person's DEK** (`keystore.destroy_key`), rendering the ciphertext mathematically unrecoverable. **The ledger bytes are never mutated — I2 stays sacrosanct** — yet the PII is genuinely erased (GDPR Art-17), not merely masked. The full transaction (D380 + ADR-0004): (1) crypto-shred the DEK; (2) atomic `suppression.forget_append`; (3) purge the vault Person + Touch notes (derived/reconstructable — safe to physically delete); (4) emit `gdpr_forget` with `person_ref` = hash + the purge audit. This **couples J5↔J6 into one crypto story** — J6 cannot land before J5's keystore + ledger-PII encryption. FENCED build (ADR-0080), after J5.

### D381. J7 CAN-SPAM — footer content + one-click `List-Unsubscribe` header (gap-scoped)

J7 is scoped to the **verified gap only**: suppression-on-unsubscribe is already enforced (Pillar D `auto_unsubscribe`), and `send_email` already exposes `extra_headers` + `body_footer`. J7 adds (a) `build_canspam_footer` — the physical-mailing-address + unsubscribe-link body footer, stamped via the existing `body_footer` seam; (b) `build_list_unsubscribe_headers` — `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058 + RFC 2369), stamped via the existing `extra_headers` seam. `CANSPAM_REQUIRED_HEADERS` pins the header set. Per the every-send invariant (D385.3), no email send path may bypass the footer + headers. Week 4 (ADR-0079). Ralph-able.

### D382. J8 audit-log export — read-only, redact-by-default

`export_audit_log` produces a compliance audit export over the ledger: READ-ONLY (per the funnel CLI contract per ADR-0059 D325 — never writes to the ledger it reads), **redact-by-default** (per the privacy invariant; PII redacted unless an operator-deliberate flag opts in for an internal review), `out_format` ∈ `AUDIT_LOG_EXPORT_FORMATS = {"jsonl", "csv"}`, emits `audit_log_exported`. Week 3 (ADR-0078). Ralph-able.

### D383. R001 (identity-graph false-merge cascade) — assigned INTO Pillar J

R001 (Sev-1, OPEN, previously unassigned) is **assigned to Pillar J Week 3**, paired with J8 (both are audit-trail work). The Ralph-able slice: (a) the `identity_keys_modified` audit event emitted on every frontmatter identity-key mutation; (b) an identity-history block (Pillar B migration) recording when keys were added + by whom; (c) `detect_identity_keys_drift` consumed by reconcile to flag a Person whose frontmatter keys diverge from the keys-ledger view. **The reverse-merge `identity.py split` tooling is deferred to v2** (it depends on the history block existing first + is a larger interactive surface). Rationale for assigning rather than deferring the whole risk: a Sev-1 OPEN risk should not ship to OSS with no audit trail at all; the audit-event + history-block slice closes the "manual merges have no audit trail today" gap named in the R001 mitigation plan, which is the load-bearing half.

### D384. Two-tier Stable + binding exit-criterion vehicle scope

Pillar J has **two tiers of "done"**:

- **Substrate-Stable (automatable; what the autonomous loop reaches):** J1 + J2 + J3 + J7 + J8 + R001-audit green. This flips the binding golden-path exit-criterion test + the EXIT_SIGNAL. The autonomous loop can genuinely reach this.
- **v1-RELEASE gate (human, parallel, does NOT block the loop):** the J9 external pen-test report with all findings closed + legal sign-off on GDPR + CAN-SPAM + the human disposition of zero-unpatched-CVEs > 14d. J4 (SLSA), J5, J6 builds also land in this tier. These are tracked as a release checklist, NOT as code assertions in the binding test.

`tests/test_multi_channel_coherence.py` extends with THREE new classes (Option A single-file vehicle per ADR-0014 D37 + ADR-0025 D101 + ADR-0032 D147 + ADR-0038 D183 + ADR-0050 D275 + ADR-0060 D334 + ADR-0070 D374): `TestPillarJSecurityCompliance` (per-week trajectory stubs, skipped → un-skip progressively), `TestPillarJSecurityComplianceObservabilityIntegration` (J↔G/H/I integration stubs), `TestPillarJExitCriterion::test_security_compliance_substrate_holds` (the binding substrate test, skipped, un-skipped at Week 4). The binding test asserts the FIVE automatable substrate rows + documents the pen-test/legal release gate as a checklist (not a code assertion). The golden-path L0 reds in `tests/golden_path/test_l0_spine_liveness.py` carry the per-surface xfail punch-list (J7/J1/J8/R001/J2-J3 Ralph-able; J6/J5 FENCED). The cumulative coherence-vehicle size crosses the ~7500 LOC split threshold for the FOURTH time; per the Pillar H/I precedent the foundation week does NOT split (the per-pillar stubs belong adjacent to the contracts they verify); a Pillar J Week N reviewer may revisit.

### D385. Six load-bearing invariants (extending Pillar I's FIVE per ADR-0070 D375)

1. **Forget-is-irreversible-and-enforced.** Once `forget --person` completes, no surface can re-derive the person: the crypto-shred makes the ledger PII unrecoverable AND `suppression.forget_append` blocks every future send (every-channel kill-switch per ADR-0004 Alternative 8). A re-discovery pass that re-enrolls the person is refused at the suppression gate.
2. **Append-only-preserved-under-erasure.** Erasure (J6) is achieved WITHOUT mutating any prior ledger byte — crypto-shred destroys keys, not events. I2 (two-phase / append-only) stays sacrosanct; ledger replay determinism per ADR-0031 D140 holds (replay of shredded events yields tombstoned/unreadable PII, not a different event stream).
3. **CAN-SPAM-on-every-send.** Every outbound email carries the physical-address footer + `List-Unsubscribe` + one-click `List-Unsubscribe-Post` header. No send path bypasses it (kill-switch semantics, like suppression). A send attempted with an empty `SecurityConfig.physical_mailing_address` refuses-loud.
4. **Secrets-never-at-rest-plaintext.** Credentials are encrypted at rest via the D379 keystore; no plaintext OAuth token persists on disk; the J2 secret-scanning hook blocks plaintext secrets from entering git. (Bootstrap exception: the one-time human OAuth consent writes a token the keystore then wraps — documented in the J5 build.)
5. **Audit-completeness.** Every compliance-relevant action is itself a ledger event — `gdpr_forget` (forget), `auth_token_refreshed` (rotation), `identity_keys_modified` (key mutation), `audit_log_exported` (export) — so the J8 export is a complete, tamper-evident compliance record derivable from the append-only ledger alone.
6. **Privacy-preserved-in-security-events.** Pillar J's own event payloads carry NO cleartext per-Person PII (`gdpr_forget` → `person_ref` hash; `audit_log_exported` → redact-by-default; cross-tenant isolation per ADR-0070 D375(a) extends to every J surface). Extends I8.

### D386. Cross-pillar surface audit at `.planning/REVIEW-pillar-j-surface-audit.md`

The Week 1 audit (load-bearing anti-regression artifact, extended per-week) walks every Pillar A-I surface that touches a credential / a PII field / a send path / the ledger-as-SoT for whether Pillar J's security fan-out silently broadens an assumption. Load-bearing concerns: (a) does `suppression.forget_append`'s single-writer file-level atomicity (ADR-0004 §Negative) hold under the J6 lock spanning crypto-shred + append + vault-purge? (b) does the Pillar C `send_email` `extra_headers`/`body_footer` seam carry the J7 footer+headers on ALL four channels' send paths (email only, by design — LinkedIn/Twitter/Calendar are not CAN-SPAM email)? (c) does the Pillar B migration framework host the R001 identity-history block migration idempotently per ADR-0009 D9? (d) does the Pillar G READ-ONLY funnel/observability contract per ADR-0059 D325 extend cleanly to the J8 export (read-only preserved)? (e) does the Pillar H daemon's `auth_token_refreshed` emit (Pillar I D371) compose with J1's emitter without double-emitting? (f) does the Pillar I per-tenant isolation per ADR-0070 D375(a) hold for per-tenant forget + per-tenant keystore + per-tenant audit export (no cross-tenant key access, no cross-tenant export leak)? Per-week-reviewer carry-forward disciplines (cell-level coverage, behavioral-passthrough `inspect.signature` barriers, module-docstring drift, mirror-constants parity, cross-pillar back-audit, framework-neutrality, privacy invariant) all apply.

### D387. Per-week trajectory + four new R-risks

| Week | Deliverable | New ADR? | Ralph-able? |
|---|---|---|---|
| 1 (49) | Pillar J foundation: `orchestrator/security/` shape + closed-sets + `SecurityConfig` + signatures + 6 invariants + cross-pillar audit + exit-criterion vehicle + golden-path reds + the four decisions (D379/D380/D383/D384) + 4 new R-risks + per-week trajectory (this commit) | ADR-0076 | human (now) |
| 2 (50) | J1 OAuth refresh-and-retry middleware (`send_with_token_rotation`) + `auth_token_refreshed` emit (reuses Pillar I class) + golden-path thread-in | ADR-0077 | **YES** |
| 3 (51) | J2 gitleaks pre-commit + J3 dependabot + osv-scanner + J8 audit-log export CLI + R001 `identity_keys_modified` audit + identity-history migration + `EVENT_CLASS_CATALOG` extension (the 4 SECURITY classes) | ADR-0078 | **YES** |
| 4 (52) | J7 CAN-SPAM footer + one-click `List-Unsubscribe` header on the send path + binding exit-criterion un-skip (substrate rows) + Pillar J substrate-Stable flip + retro + handoff | ADR-0079 | **YES** |
| FENCED (human-gated; NOT in the Ralph 4-week count) | J5 encrypted-at-rest keystore + ledger-PII encryption; J6 crypto-shred `forget` (depends on J5); J4 SLSA attestation | ADR-0080 (J5/J6), ADR-0081 (J4) reserved | human |
| v1-RELEASE gate (parallel) | J9 external pen-test all-closed + legal sign-off on GDPR + CAN-SPAM + CVE-disposition | — (release checklist) | non-automatable |

**Four new risks** (added to `docs/RISK-REGISTER.md`):

- **R043 (Crypto-shred master-key loss = catastrophic data loss)** — Sev 1 / Lk 2. If the D379 master key is lost, ALL ciphertext (not just forgotten persons) is unrecoverable. Mitigation by design: a two-level key hierarchy — a master KEK (key-encryption key) wraps per-person DEKs; `forget` destroys only the per-person DEK, never the KEK; KEK backup discipline is documented in the J5 build + the doctor preflight reports KEK presence.
- **R044 (Passphrase-fallback weak passphrase = brute-forceable at-rest creds)** — Sev 2 / Lk 2. The Docker/CI passphrase backend is only as strong as the passphrase. Mitigation: Argon2id with tuned params (memory/time cost) + a minimum-entropy refuse-loud at keystore init.
- **R045 (CAN-SPAM footer/header omitted on a non-default send path)** — Sev 2 / Lk 2. A future send path (a reply, a re-engagement, a new channel) could bypass the footer/header. Mitigation: the every-send invariant (D385.3) + a regression-barrier test asserting every email send path carries `CANSPAM_REQUIRED_HEADERS`.
- **R046 (Audit-log export leaks PII)** — Sev 2 / Lk 2. A compliance export could include cleartext PII. Mitigation: redact-by-default (D382) + the privacy invariant (D385.6) + a regression-barrier test asserting the default export carries no forbidden per-Person field.

## Alternatives considered

### D379 alternatives (J5 keystore)
1. **macOS Keychain only.** Rejected — the OSS target is cross-platform; a Keychain-only keystore breaks every Linux operator AND every Pillar I Docker container (no keyring), making it incompatible with the multi-tenant container model shipped in ADR-0070 D372.
2. **Passphrase-derived key only (no OS keyring).** Rejected as the *default* (kept as the fallback) — forcing every operator to supply a passphrase each start is worse UX than using the OS keyring where one exists; but it is the mandatory fallback for headless/container deploys, so it is half of the chosen answer.
3. **Cloud KMS (AWS KMS / GCP KMS).** Rejected at v1 — adds a hard cloud dependency to a tool whose v1 thesis is local-first single-machine (PILLAR-PLAN §4 "no custom database", local git backup); operators wanting KMS wire it via the keystore Protocol seam (Tier-1 backend substitution) post-v1.

### D380 alternatives (J6 step-1 tombstoning)
1. **Tombstone + redaction-on-read.** Rejected — raw PII bytes physically remain on disk + in backups; a `grep` of the JSONL still finds the "forgotten" person. That is masking, not erasure — a weak legal posture for an OSS compliance claim under GDPR Art-17.
2. **Out-of-band ledger rewrite / compaction.** Rejected — physically rewriting the JSONL to drop a person's events breaks the append-only immutability (I2) + invalidates replay determinism (ADR-0031 D140) + any future hash-chain; it needs a migration-grade compaction + re-derivation primitive with the highest blast radius on the ledger contract. Crypto-shred achieves true erasure with I2 intact.
3. **Do nothing in the ledger; rely on suppression + vault purge only.** Rejected — leaves the person's PII permanently in the ledger; fails the "purge ledger person records" half of ADR-0004 step 1 + GDPR Art-17.

### D383 alternatives (R001 disposition)
1. **Defer R001 entirely to v2.** Rejected — a Sev-1 OPEN risk shipping to OSS with zero audit trail for manual identity merges is the kind of silent-blast-radius failure the project's asymmetric-failure-cost principle (PILLAR-PLAN §0) weighs heavily; the audit-event + history-block slice is small + closes the load-bearing half. (The reverse-merge *tooling* IS deferred to v2 — a narrower deferral.)
2. **Spin R001 into its own mini-pillar.** Rejected — its fix is two well-scoped additions (an emit + a migration) that fit a single Pillar J week paired with J8's audit-trail work; a new pillar is disproportionate.

### D384 alternatives (Stable gate)
1. **Single legal-blocking gate.** Rejected — making Pillar J Stable require pen-test-closed + legal sign-off means the autonomous loop can NEVER flip it (it parks indefinitely waiting on human counsel); the substrate work (J1/J2/J3/J7/J8) would have no green definition-of-done. The two-tier split lets the loop genuinely finish the automatable substrate while the human-gated release gate runs in parallel — matching how pen-test/legal were always treated (gate-only) in the golden-path spec §9.
2. **Drop the binding exit-criterion test entirely (J is "config, not spine").** Rejected — J7 (CAN-SPAM on every send) + J6 (forget) + J1 (rotation consistency) + J8 (audit completeness) ARE spine-observable; a binding substrate test is both possible and the per-pillar-foundation precedent.

### D377 alternatives (package shape)
1. **Thread J primitives into existing modules (gmail_client, policy, ci) with no new package.** Rejected — the per-pillar-foundation precedent ships a package with a mirror-constants home; scattering J's closed-sets across modules loses the parity-regression-barrier discipline. (The *wiring* still touches gmail_client/policy/ci; the *primitives + closed-sets* live in `orchestrator/security/`.)
2. **Defer the package to Week 2.** Rejected per the Pillar G/H/I precedent — Week 1 ships the shape so Weeks 2-4 satisfy a fixed contract.

## Consequences

### Positive
- The four hard Pillar J decisions (J5 keystore, J6 crypto-shred, R001, Stable gate) are pinned at Week 1, so the per-week + FENCED builds + the autonomous loop never guess them.
- Crypto-shred reconciles GDPR Art-17 erasure with the append-only ledger (I2) with zero ledger mutation — the principled answer, and it unifies J5 + J6 into one crypto story.
- The two-tier Stable gate gives the autonomous loop a genuine, reachable definition-of-done (substrate-Stable) while keeping the real release gate (pen-test + legal) human + parallel.
- J7's gap-verify means Ralph builds only the genuine ~40-line footer/header gap, not a re-implementation of suppression.
- `auth_token_refreshed` reuse (Pillar I pre-provisioned it) is a clean cross-pillar handoff — no event-class churn.

### Negative
- J5 ↔ J6 coupling means J6 cannot ship before J5's keystore + ledger-PII-encryption land; both are FENCED (human-verified key correctness), so the headline GDPR-forget golden-path assertion stays xfail until the human-gated builds complete — the autonomous loop reaches substrate-Stable WITHOUT the forget assertion green (it is in the FENCED tier, documented in RALPH-BLOCKED.md).
- Ledger-PII encryption (D380 prerequisite) is a real data-model change touching how person-identifying fields are written — the largest single piece of Pillar J, and it is human-gated.
- The coherence vehicle crosses the split threshold a fourth time; the foundation week defers the split again.

### Neutral / observability
- The four SECURITY event classes become funnel/observability-visible once the Week 3 catalog extension lands (no new dashboard code per ADR-0050 §Neutral).

## Compliance with invariants
- **I2 (append-only / two-phase):** D380 crypto-shred preserves I2 fully — erasure destroys keys, never events. Explicitly strengthened, not weakened.
- **I8 (privacy):** D385.6 extends I8 to Pillar J's own events (`person_ref` hash, redact-by-default export, per-tenant isolation).
- **I1 (single source of truth):** the ledger remains SoT; the vault Person/Touch purge (J6 step 3) deletes only derived/reconstructable state. The keystore is a new SoT for credential keys — added to `docs/SOURCES-OF-TRUTH.md` in the J5 build.
- **I3 (schema versioning):** the R001 identity-history block ships as a Pillar B migration with a synthetic before-state snapshot test.

## Migration / rollout
- Week 1 is additive/greenfield (new `orchestrator/security/` package; no behavior change; bodies are `NotImplementedError`). The R001 identity-history block (Week 3) + the ledger-PII encryption (FENCED J5) ship as Pillar B migrations with synthetic before-state tests when they land.

## Pre-commit verification

Derive, don't assert. Commands run at authoring time (python3 = 3.13; some `orchestrator/` modules use bare imports → `PYTHONPATH=orchestrator`; `gmail_client` cannot import without Google libs → source-quoted).

| Claim in this ADR | Verification command | Output (pasted) |
|---|---|---|
| Highest existing decision-ID is D376 → Pillar J starts at D377 | `grep -rhoE "D[0-9]{3}" docs/adr/*.md \| sort -t D -k2 -n \| tail -1` | `D376` |
| ADRs 0071-0075 were never written as files | `ls docs/adr/007[1-5]*.md` | `no matches found` |
| `SECURITY_NEW_EVENT_CLASSES` is disjoint from `EVENT_CLASS_CATALOG` (D377) | `python3 -c "from orchestrator.security import SECURITY_NEW_EVENT_CLASSES as S; from orchestrator.observability import EVENT_CLASS_CATALOG as C; print(S.isdisjoint(C))"` | `True` |
| `auth_token_refreshed` already cataloged (Pillar I pre-provisioned; J1 reuses, not in SECURITY set) | `python3 -c "from orchestrator.observability import EVENT_CLASS_CATALOG as C; from orchestrator.security import SECURITY_NEW_EVENT_CLASSES as S; print('auth_token_refreshed' in C, 'auth_token_refreshed' not in S)"` | `True True` |
| `EVENT_CLASS_CATALOG` has 69 entries (the Week 3 extension adds 4 → 73) | `python3 -c "from orchestrator.observability import EVENT_CLASS_CATALOG as c; print(len(c))"` | `69` |
| Closed-set sizes (D377/D378/D379/D382) | `python3 -c "from orchestrator.security import *; print(len(SECURITY_NEW_EVENT_CLASSES), len(CREDENTIAL_KEYSTORE_BACKENDS), len(AUDIT_LOG_EXPORT_FORMATS), len(SECURITY_SCANNERS))"` | `4 2 2 3` |
| J7 gap: `send_email` already exposes the footer + header seams (D381) | `sed -n '71,79p' skills/send-outreach/scripts/gmail_client.py` | `def send_email(self, to, subject, body, from_name=None, extra_headers: Optional[dict]=None, body_footer: Optional[str]=None) -> tuple[str,str]` |
| J6 step-2 already shipped (D380 / ADR-0004) | `python3 -c "import inspect; from orchestrator.policy import suppression; print(inspect.signature(suppression.forget_append))"` | `(directory: 'Path', *, email='str\|None'=None, domain='str\|None'=None, identity_key='str\|None'=None, filename: 'str'='gdpr-forget.yml') -> 'Path'` |
| `reconcile.reconcile` is keyword-only with required `since` (R001 drift-flag consumer surface, D383/D386) | `PYTHONPATH=orchestrator python3 -c "import inspect, reconcile; print(inspect.signature(reconcile.reconcile))"` | `(*, passes='A', since: 'datetime', gmail=None, ..., apply=False, min_intent_age=timedelta(seconds=300), ...) -> 'ReconcileResult'` |
| Suppression-on-unsubscribe already enforced (J7 gap scope, D381) | `PYTHONPATH=orchestrator python3 -c "import auto_unsubscribe as a; print('build_suppression_added_payload' in dir(a))"` | `True` |

## References
- `.planning/HANDOFF-pillar-j.md` — the planning kickoff this ADR executes
- `.planning/GOLDEN-PATH-HARNESS.md` §5 (the J golden-path assertion) + §9 (Ralph-able vs human-gated)
- `.planning/PILLAR-J-PRD.md` — the product requirements this ADR's design satisfies
- ADR-0004 §"GDPR forget path" — the forget transaction this ADR completes (step 1 = D380)
- ADR-0070 D371-D376 — the Pillar I foundation precedent this ADR mirrors; `auth_token_refreshed` pre-provisioning
- `docs/RISK-REGISTER.md` — R001 (assigned D383), R002 (J1), R010 (J6/J7), R043-R046 (new, D387)
- Enforcement: `orchestrator/security/`, `tests/golden_path/test_l0_spine_liveness.py::TestGoldenPathL0SecurityCompliance`, `tests/test_multi_channel_coherence.py::TestPillarJExitCriterion`
