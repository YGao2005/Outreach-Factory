# ADR-0079: Pillar J Week 4 — CAN-SPAM footer + one-click unsubscribe (J7) + substrate-Stable flip

- **Status:** Accepted
- **Date:** 2026-05-29
- **Pillar:** J (Security + compliance)
- **Deciders:** Ralph (autonomous loop), per ADR-0076 D387 trajectory row Week 4

## Context

ADR-0076 D387 pins Week 4 of Pillar J as the final substrate red — **J7**
(CAN-SPAM footer + RFC-8058 one-click `List-Unsubscribe`) — followed by the
**substrate-Stable flip** per the two-tier Stable decision (ADR-0076 D384). W1
shipped the `SecurityConfig` shape + signatures; W2 shipped J1; W3 shipped
J2/J3 + J8 + R001 + the catalog extension. J5/J6 stay FENCED (ADR-0080,
human-gated). This is the last automatable Pillar J week.

D381 scoped J7 to the **verified gap only**: `gmail_client.send_email` already
exposes `extra_headers` + `body_footer`, and suppression-on-unsubscribe is
already enforced (Pillar D `auto_unsubscribe`). J7 adds the footer CONTENT + the
header INJECTION, nothing more.

## Decision

**D394 — J7 = two builders + `SecurityConfig` validation, wired into the send
path via the existing seams.**
`build_canspam_footer(*, physical_mailing_address, unsubscribe_url) -> str`
returns a body footer carrying both the operator's CAN-SPAM physical postal
address and the one-click unsubscribe link (stamped via the existing
`body_footer` seam). `build_list_unsubscribe_headers(*, unsubscribe_url,
mailto=None) -> dict[str,str]` returns `{List-Unsubscribe: <url>[, <mailto>],
List-Unsubscribe-Post: List-Unsubscribe=One-Click}` (RFC 8058 + RFC 2369;
keyed by `CANSPAM_REQUIRED_HEADERS`; stamped via the existing `extra_headers`
seam). `SecurityConfig.__post_init__` refuses-loud (`ValueError`, ADR-0001 D2)
on a `keystore_backend` outside `CREDENTIAL_KEYSTORE_BACKENDS`, an empty
`physical_mailing_address` (a missing CAN-SPAM address is a legal liability —
the asymmetric-failure-cost principle, PILLAR-PLAN §0), or an
`unsubscribe_base_url` that is not `http(s)://`.

**Every-send invariant (D385.3):** `send_queued.gated_send_one` takes an
optional `security_cfg: SecurityConfig`. The operator dispatch entrypoint
constructs it from config (which refuses-loud if the address is unset) and
passes it; the inner send body then MERGES the CAN-SPAM footer into the
existing intent `body_footer` and the `List-Unsubscribe` headers into the
existing intent `extra_headers` — no send path bypasses them. The
**per-recipient unsubscribe token is an opaque person hash**
(`sha256(person_id)[:16]`), so the URL carries no cleartext `person_id` (I8);
it is stable per-person so the recipient can unsubscribe. The parameter is
optional (not required) to preserve the "every external dependency is
parameterized" testability contract of `gated_send_one` — existing send tests
that pass no config keep the legacy (intent-footer-only) behavior; the
production path always supplies it.

**D395 — Pillar J substrate-Stable flip (two-tier per ADR-0076 D384).**
`tests/test_multi_channel_coherence.py::TestPillarJExitCriterion::test_security_compliance_substrate_holds`
un-skips and verifies the AUTOMATABLE substrate tier:
- **ROW 1 (J1)** — `send_with_token_rotation` refreshes-and-retries a mid-batch
  401 once and the ledger ends consistent (an `auth_token_refreshed` row).
- **ROW 2 (J2/J3)** — gitleaks + dependabot + osv-scanner are wired
  (`SECURITY_SCANNERS` + the repo-state files).
- **ROW 3 (J7)** — every email send through `gated_send_one` carries the
  CAN-SPAM footer + the one-click `List-Unsubscribe` headers (integration test
  with a capturing FakeGmail + a `SecurityConfig`).
- **ROW 4 (J8)** — a read-only, redact-by-default `export_audit_log` covers a
  run, emits `audit_log_exported`, and leaks no cleartext `person_id`.
- **ROW 5 (R001)** — `build_identity_keys_modified_payload` produces the
  `identity_keys_modified` audit row + `detect_identity_keys_drift` is callable.
- **Privacy (D385.6 + I8)** — no Pillar J event payload (`audit_log_exported`,
  `identity_keys_modified`) carries cleartext PII in its export/tombstone form.

The **v1-release tier** (external pen-test all-findings-closed, legal sign-off
on GDPR + CAN-SPAM, CVE disposition, and the FENCED J4/J5/J6 builds) is a human,
parallel release checklist tracked in `.planning/PILLAR-J-PRD.md` §6 — NOT a
code assertion (a unit test cannot stand in for counsel or a pen-tester). The
flip declares the **substrate** done; the OSS-release TAG is the human gate.

## Alternatives considered

### Alt 1 (J7): make `security_cfg` a required parameter of `gated_send_one`
Strongest every-send invariant — impossible to bypass. **Rejected:** breaks
every existing send test (and the multi_tenant init-wizard send) that passes no
config, and forces a config-source refactor this week. The optional-param +
refuse-loud-at-construction + production-path-always-passes design enforces the
invariant where it matters (production) without the blast radius. A required
param is a clean v2 refactor once a single send entrypoint owns config loading.

### Alt 2 (J7): put the cleartext `person_id` (or email) in the unsubscribe URL
Simplest token. **Rejected:** a `List-Unsubscribe` URL is logged by every relay
in the path; a cleartext id there is an I8 leak. An opaque per-person hash is
stable (recipient can unsubscribe) without the leak.

### Alt 3 (Stable): wait for pen-test + legal before flipping Stable
**Rejected:** that is exactly the two-tier decision ADR-0076 D384 already made —
the substrate tier is what the autonomous loop can verify + flip; the release
tier is the human checklist. Conflating them would block the loop forever on a
human-gated artifact.

## Consequences

### Positive
- The Pillar J **substrate** is complete + binding-tested; the OSS-release work
  (pen-test, legal, J4/J5/J6) proceeds in parallel against a frozen substrate.
- Every production email carries a compliant CAN-SPAM footer + one-click
  unsubscribe — the legal-liability gap closes.

### Negative
- The every-send invariant is enforced by convention at the production
  dispatch entrypoint (it passes `security_cfg`), not by a required signature;
  a future new send entrypoint must remember to pass it. Mitigated by ROW 3 +
  the v2 single-entrypoint refactor note.

### Neutral
- No new event classes (J7 emits none — suppression already emits its own).

## Compliance with invariants
- **I2 (append-only):** J7 adds only message headers/footer; no ledger mutation.
- **I8 / privacy:** opaque per-person unsubscribe token; no cleartext id in URL.
- **Closed-set (R031):** `CANSPAM_REQUIRED_HEADERS`, `CREDENTIAL_KEYSTORE_BACKENDS`.
- **Refuse-loud (ADR-0001 D2):** empty address / malformed URL / bad backend raise.
- **Every-send (D385.3):** footer + headers merged on the `gated_send_one` path.

## Migration / rollout
Additive + backward-compatible. `security_cfg` defaults to `None` (legacy
behavior). The operator adds `security.physical_mailing_address` +
`security.unsubscribe_base_url` to `~/.outreach-factory/config.yml`; a send
attempted with the address unset refuses-loud at `SecurityConfig` construction.

## Pre-commit verification

Derive, don't assert — signatures pasted from `inspect`, not memory.

| Claim in this ADR | Verification command | Output (pasted) |
|---|---|---|
| `build_canspam_footer` shape | `python -c "import inspect; from orchestrator import security as s; print(inspect.signature(s.build_canspam_footer))"` | `(*, physical_mailing_address: 'str', unsubscribe_url: 'str') -> 'str'` |
| `build_list_unsubscribe_headers` shape | `python -c "import inspect; from orchestrator import security as s; print(inspect.signature(s.build_list_unsubscribe_headers))"` | `(*, unsubscribe_url: 'str', mailto: 'Optional[str]' = None) -> 'dict[str, str]'` |
| `CANSPAM_REQUIRED_HEADERS` | `python -c "from orchestrator import security as s; print(sorted(s.CANSPAM_REQUIRED_HEADERS))"` | `['List-Unsubscribe', 'List-Unsubscribe-Post']` |
| `SecurityConfig` fields | `python -c "from orchestrator import security as s; print(list(s.SecurityConfig.__dataclass_fields__))"` | `['physical_mailing_address', 'unsubscribe_base_url', 'unsubscribe_mailto', 'keystore_backend', 'audit_export_dir', 'tenant_id']` |
| `gmail_client.send_email` exposes the J7 seams | `sed -n '71,79p' skills/send-outreach/scripts/gmail_client.py` | `def send_email(self, to, subject, body, from_name=None, extra_headers: Optional[dict]=None, body_footer: Optional[str]=None) -> tuple[str,str]` |
| `gated_send_one` is keyword-parameterized (an optional `security_cfg` fits the contract) | `sed -n '416,427p' skills/send-outreach/scripts/send_queued.py` | `def gated_send_one(draft, *, gmail_client, led, sender_name='', register='cold-pitch', run_id=None, acquire_lock=None, release_lock=None, writeback=_vault_writeback) -> dict` |

## References
- ADR-0076 (Pillar J foundation; D381 J7 gap-scope, D384 two-tier Stable, D385.3 every-send / D385.6 privacy)
- ADR-0077 (J1), ADR-0078 (J2/J3 + J8 + R001 + catalog), ADR-0080 (FENCED J5/J6)
- RFC 8058 (one-click unsubscribe) + RFC 2369 (`List-Unsubscribe`)
- `.planning/PILLAR-J-PRD.md` §6 (the v1-release human checklist)
- Enforced in `orchestrator/security/__init__.py`, `skills/send-outreach/scripts/send_queued.py`, `tests/golden_path/test_l0_spine_liveness.py::TestGoldenPathL0SecurityCompliance`, `tests/test_multi_channel_coherence.py::TestPillarJExitCriterion`
