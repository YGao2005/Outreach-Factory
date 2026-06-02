# ADR-0077: Pillar J Week 2 — J1 OAuth refresh-and-retry middleware

- **Status:** Accepted
- **Date:** 2026-05-29
- **Pillar:** J (Security + compliance)
- **Deciders:** Ralph (autonomous loop), per ADR-0076 D387 trajectory row Week 2

## Context

ADR-0076 D387 pins Week 2 of Pillar J as J1 — the OAuth refresh-and-retry
middleware that mitigates **R002** (a mid-batch token expiry orphaning a send).
The signature shipped in Week 1 (`orchestrator/security/__init__.py:send_with_token_rotation`
+ `build_auth_token_refreshed_payload`) as `NotImplementedError`. The golden-path
red `TestGoldenPathL0SecurityCompliance::test_pillar_J_oauth_refresh_and_retry_on_midbatch_401`
is the binding definition-of-done: a fake `send_fn` raises a 401 on its first
call, and the middleware must refresh once, retry, return the send result, and
leave an `auth_token_refreshed` event in the ledger.

Two forces shape the body. First, J1 wraps an **opaque** `send_fn` — the real
send path (`skills/send-outreach/scripts/gmail_client.py:108`) re-raises a
googleapiclient `HttpError` as `RuntimeError(f"Gmail API send failed: {e}")`, and
a stale refresh token surfaces as `google.auth.exceptions.RefreshError`; J1 cannot
import every channel client's exception type. Second, the emitted event class is
**not Pillar J's** — ADR-0070 D371 pre-provisioned `auth_token_refreshed` in
`TENANT_NEW_EVENT_CLASSES` (Pillar I), so it is already in `EVENT_CLASS_CATALOG`
and J1 is merely its first emitter.

## Decision

**D388 — `send_with_token_rotation` classifies auth failures by signal, retries
once, emits-after-refresh-before-retry.** The middleware runs `send_fn`; on an
exception it consults `_is_auth_error` (structured `401` status via `.status_code`
/ `.code` / `.resp.status`, else a lowercased substring match against
`_AUTH_ERROR_SIGNALS` — `401`, `invalid_grant`, `invalid_token`, `unauthorized`,
`invalid credentials`, token-expired, `refresherror`). A **non-auth** exception
propagates unchanged (J1 owns credential rotation, not generic retry). On an auth
error it calls `refresh_fn` once, then appends `auth_token_refreshed`, then retries
`send_fn`. The emit lands **after** the refresh actually runs (the ledger never
claims a refresh that did not happen) and **before** the retry (a rotation is
recorded even if the retry then fails), exactly once per refresh. After
`max_retries` (default 1) auth failures the last exception re-raises — no unbounded
refresh loop (refuse-loud, ADR-0001 D2).

**D389 — the `auth_token_refreshed` payload reuses Pillar I's class and keeps its
`_emitted_by="multi_tenant"` attribution.** `build_auth_token_refreshed_payload`
returns the ADR-0070 D371 line-85 shape exactly — `tenant_id` + `token_scope` +
`refreshed_at_ts` + `_emitted_by` — stamping `multi_tenant.EMITTED_BY` (NOT
`"security"`), because the class is multi_tenant-owned + cataloged and is
deliberately excluded from `SECURITY_NEW_EVENT_CLASSES`. The builder validates via
Pillar I's own `_validate_tenant_id` + `TENANT_OAUTH_TOKEN_SCOPES` (identical rules
on the single- and per-tenant paths) and carries its own `type` so the caller
appends it directly. Single-tenant callers (no `tenant_id`) get `_DEFAULT_TENANT_ID
= "default"`, which satisfies the same pattern.

## Alternatives considered

### Alternative 1: classify auth failures by exception type
Catch `HttpError` / `RefreshError` explicitly. **Rejected because:** J1 wraps an
opaque `send_fn` across channels (Gmail today, LinkedIn/Twitter later) and the real
Gmail path already flattens `HttpError` into a bare `RuntimeError` — a type check
would miss the production surface the golden-path L0 mirrors.

### Alternative 2: re-home `auth_token_refreshed` into Pillar J with `_emitted_by="security"`
Treat J1 as the owner. **Rejected because:** ADR-0070 D371 already cataloged the
class under Pillar I with `_emitted_by="multi_tenant"`, and ADR-0076 D377 keeps it
out of `SECURITY_NEW_EVENT_CLASSES` precisely so it stays a reused class; changing
the attribution would split one cataloged class into two payload shapes.

### Alternative 3: emit `auth_token_refreshed` only on a successful retry
Record the rotation after the retry succeeds. **Rejected because:** a refresh that
happened is audit-worthy regardless of whether the subsequent retry succeeds;
emitting before the retry keeps the audit trail honest about what the credential
layer actually did (R002 is about consistency, not optimism).

## Consequences

### Positive
- The golden-path J1 red is a permanent regression barrier (xfail removed); a
  mid-batch 401 can no longer orphan a send.
- Single-emitter guarantee pinned by `test_auth_token_refreshed_single_emitter`.

### Negative
- Text-based classification could in principle false-positive on a non-auth error
  whose message happens to contain `"401"`; bounded by `max_retries=1` (one wasted
  refresh at worst, then re-raise).

### Neutral / observability
- Operators see one `auth_token_refreshed` per rotation in their ledger; the class
  was already in the catalog, so no observability snapshot/funnel change.

## Compliance with invariants

- **I2 (append-only ledger):** preserved — J1 only appends.
- **I5 (refuse-loud):** non-auth errors + post-retry auth failures re-raise; the
  builder rejects malformed `tenant_id` / out-of-set `token_scope`.
- **I8 (privacy):** the payload carries no per-Person field (tenant + scope + ts).

## Migration / rollout

N/A — additive. No new event class (reuses the cataloged `auth_token_refreshed`),
no ledger/vault schema change, no migration.

## Pre-commit verification

| Claim in this ADR | Verification command | Output (pasted) |
|---|---|---|
| `send_with_token_rotation` signature | `python -c "import inspect; from orchestrator import security as s; print(inspect.signature(s.send_with_token_rotation))"` | `(send_fn, *, refresh_fn, led, tenant_id='Optional[str]'=None, token_scope='str'='gmail.send', max_retries='int'=1, now="'Optional[datetime]'"=None) -> 'Any'` |
| `build_auth_token_refreshed_payload` signature | `…print(inspect.signature(s.build_auth_token_refreshed_payload))` | `(*, tenant_id: 'str', token_scope: 'str', refreshed_at_ts: 'str') -> 'dict[str, Any]'` |
| `auth_token_refreshed` already cataloged (Pillar I), absent from J's set | `…'auth_token_refreshed' in EVENT_CLASS_CATALOG / in SECURITY_NEW_EVENT_CLASSES` | `True` / `False` |
| reused attribution constant | `python -c "from orchestrator.multi_tenant import EMITTED_BY; print(repr(EMITTED_BY))"` | `'multi_tenant'` |
| built payload shape | `…s.build_auth_token_refreshed_payload(tenant_id='aiyara', token_scope='gmail.send', refreshed_at_ts='2026-05-28T17:00:00.000Z')` | `{'type': 'auth_token_refreshed', 'tenant_id': 'aiyara', 'token_scope': 'gmail.send', 'refreshed_at_ts': '2026-05-28T17:00:00.000Z', '_emitted_by': 'multi_tenant'}` |
| real 401 surface J1 must classify | `grep -n "Gmail API send failed" skills/send-outreach/scripts/gmail_client.py` | `108:    raise RuntimeError(f"Gmail API send failed: {e}") from e` |

## References

- ADR-0076 D387 (Pillar J per-week trajectory — Week 2 row), D377 (`SECURITY_NEW_EVENT_CLASSES` disjoint)
- ADR-0070 D371 (line 85: `auth_token_refreshed` event-class spec + `_emitted_by="multi_tenant"`)
- `docs/RISK-REGISTER.md` R002 (OAuth token rotation)
- Enforced at `orchestrator/security/__init__.py` (`send_with_token_rotation`, `build_auth_token_refreshed_payload`); barriers at `tests/golden_path/test_l0_spine_liveness.py::TestGoldenPathL0SecurityCompliance::test_pillar_J_oauth_refresh_and_retry_on_midbatch_401` + `tests/test_multi_channel_coherence.py::…::test_auth_token_refreshed_single_emitter`
