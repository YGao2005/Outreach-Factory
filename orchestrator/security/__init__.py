"""Pillar J Week 1 — security + compliance foundation (per ADR-0076
D377-D387). Week 1 ships the **package shape** — the frozen
:class:`SecurityConfig` dataclass, the closed-sets, and the J1/J5/J6/J7/
J8/R001 primitive signatures raising :exc:`NotImplementedError`; Weeks
2-4 (+ the FENCED human-gated J5/J6/J4 builds) ship the bodies per
ADR-0076 D387's per-week trajectory table.

Per the per-pillar-foundation precedent (Pillar D ADR-0025 + Pillar E
ADR-0032 + Pillar F ADR-0038 + Pillar G ADR-0050 + Pillar H ADR-0060 +
Pillar I ADR-0070 — each pillar's Week 1 ships module shape + closed-sets
+ signatures + cross-pillar surface audit + exit-criterion vehicle scope
+ load-bearing invariants + per-week trajectory table). This module is
the canonical home for Pillar J's security + compliance primitives:

* **J1 — OAuth refresh-and-retry middleware** (R002 mitigation):
  :func:`send_with_token_rotation` wraps a per-channel send, catches a
  mid-batch ``401``/refresh error, refreshes the credential, retries
  ONCE, and emits ``auth_token_refreshed``. **The event class is REUSED
  from Pillar I** — ADR-0070 D371 already enumerated ``auth_token_refreshed``
  in :data:`orchestrator.multi_tenant.TENANT_NEW_EVENT_CLASSES` (Pillar I
  pre-provisioned J1's emit class), so it is ALREADY in
  :data:`orchestrator.observability.EVENT_CLASS_CATALOG` and MUST NOT
  appear in :data:`SECURITY_NEW_EVENT_CLASSES` (the new-class set is
  disjoint-from-catalog per ADR-0050 D273). J1 supersedes R002's
  ``oauth_rotated`` working name with the cataloged ``auth_token_refreshed``.

* **J5 — encrypted-at-rest credentials** (FENCED; ADR-0076 D379):
  :func:`resolve_keystore` selects the credential keystore backend —
  the OS keyring (macOS Keychain / Linux Secret Service / Windows
  Credential Locker via the ``keyring`` library) when present, falling
  back to an Argon2id passphrase-derived key for Docker / CI / headless
  environments that have no OS keyring (the Pillar I per-tenant container
  has no keyring, so the fallback is MANDATORY). :func:`encrypt_credential`
  / :func:`decrypt_credential` wrap per-tenant OAuth tokens at rest;
  :func:`derive_person_data_key` derives the per-person data-encryption
  key (DEK) that J6 crypto-shreds.

* **J6 — GDPR ``forget`` via tombstone + crypto-shred** (FENCED; depends
  on J5; ADR-0076 D380 + ADR-0004 §"GDPR forget path" step 1):
  :func:`forget_person` runs the four-step ADR-0004 transaction under a
  lock — (1) crypto-shred the person's DEK so the ciphertext PII in the
  append-only ledger becomes mathematically unrecoverable (the ledger
  bytes are NEVER mutated — I2 is sacrosanct), (2) atomic
  ``suppression.forget_append`` (Pillar A; already implemented), (3)
  purge the vault Person + Touch notes, (4) emit ``gdpr_forget`` with a
  ``person_ref`` HASH (never cleartext ``person_id``) + the purge audit.

* **J7 — CAN-SPAM footer + one-click unsubscribe** (ADR-0076 D381):
  :func:`build_canspam_footer` builds the physical-address body footer;
  :func:`build_list_unsubscribe_headers` builds the ``List-Unsubscribe``
  + ``List-Unsubscribe-Post: List-Unsubscribe=One-Click`` headers. The
  send path stamps BOTH onto every outbound email per the every-send
  invariant (suppression-on-unsubscribe is ALREADY enforced by Pillar D
  ``auto_unsubscribe`` — J7 closes only the footer-content + header gap).

* **J8 — audit-log export** (ADR-0076 D382): :func:`export_audit_log`
  produces a read-only, redact-by-default compliance export over the
  ledger + emits ``audit_log_exported``.

* **R001 — identity-graph false-merge audit** (ADR-0076 D383; assigned
  INTO Pillar J): :func:`detect_identity_keys_drift` +
  :func:`build_identity_keys_modified_payload` give every frontmatter
  identity-key mutation a ledger audit trail (``identity_keys_modified``)
  so reconcile can flag a Person whose keys diverge from the keys-ledger
  view. The reverse-merge ``identity.py split`` tooling is deferred to v2.

**J2 (gitleaks pre-commit) + J3 (dependabot + osv-scanner)** are CI /
config surfaces (``.pre-commit-config.yaml`` + ``.github/dependabot.yml``
+ ``.github/workflows/``) — they do NOT emit ledger events, so they have
no event class here; :data:`SECURITY_SCANNERS` documents the closed-set.
**J4 (SLSA attestation), J9 (external pen-test), legal sign-off** are
FENCED / non-automatable (the v1-RELEASE gate, not the substrate gate).

**Privacy invariant** per I8 + ADR-0050 D276(b) + ADR-0058 D323 +
ADR-0060 D335 + ADR-0070 D375 (a): Pillar J's OWN event payloads carry
NO cleartext per-Person PII — ``gdpr_forget`` carries ``person_ref``
(a hash), ``audit_log_exported`` is redact-by-default, and the per-tenant
isolation contract extends to every Pillar J surface.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol


#: The ``_emitted_by`` marker stamped onto every Pillar J event payload
#: (mirrors :data:`orchestrator.multi_tenant.EMITTED_BY` = "multi_tenant"
#: + the Pillar G/H per-pillar emit-attribution discipline).
EMITTED_BY = "security"


#: Closed-set of the FOUR new Pillar J event classes per ADR-0076 D377.
#:
#: These are EMITTED by Pillar J but not yet CONSUMED — they MUST be
#: disjoint from :data:`orchestrator.observability.EVENT_CLASS_CATALOG`
#: at Week 1 (per ADR-0050 D273; the catalog enumerates consumed classes,
#: the new-class set enumerates emitted-not-yet-cataloged classes). The
#: Week 3 catalog extension (ADR-0078) moves all four into the catalog
#: per the per-pillar mirror constants parity discipline.
#:
#: * ``gdpr_forget`` — emit on a completed ``forget --person`` transaction
#:   (J6); payload: ``person_ref`` (HASH, never cleartext ``person_id``)
#:   + ``key_destroyed`` (bool) + ``n_events_shredded`` (int) +
#:   ``suppression_appended`` (bool) + ``vault_purged`` (bool) +
#:   ``forgotten_at_ts`` + ``audit`` (dict) + ``_emitted_by="security"``.
#:   Named in ADR-0004 §"GDPR forget path" step 4; Pillar J is its home.
#: * ``audit_log_exported`` — emit on a completed audit-log export (J8);
#:   payload: ``exported_at_ts`` + ``n_events`` + ``out_format`` (member
#:   of :data:`AUDIT_LOG_EXPORT_FORMATS`) + ``redacted`` (bool) +
#:   ``since_ts`` + ``until_ts`` + ``_emitted_by="security"``. The export
#:   itself is audit-worthy.
#: * ``identity_keys_modified`` — emit on any frontmatter identity-key
#:   mutation (R001); payload: ``person_id`` + ``before_keys`` (list) +
#:   ``after_keys`` (list) + ``actor`` (operator|reconcile|enrollment) +
#:   ``modified_at_ts`` + ``_emitted_by="security"``. Named in the
#:   RISK-REGISTER R001 mitigation plan.
#: * ``credentials_reencrypted`` — emit on a credential key-rotation /
#:   re-encryption (J5); payload: ``tenant_id`` + ``key_id`` +
#:   ``backend`` (member of :data:`CREDENTIAL_KEYSTORE_BACKENDS`) +
#:   ``reencrypted_at_ts`` + ``_emitted_by="security"``.
SECURITY_NEW_EVENT_CLASSES: frozenset[str] = frozenset({
    "gdpr_forget",
    "audit_log_exported",
    "identity_keys_modified",
    "credentials_reencrypted",
})


#: Closed-set of credential-keystore backends per ADR-0076 D379.
#:
#: * ``"os_keyring"`` — the OS-native secret store via the ``keyring``
#:   library (macOS Keychain / Linux Secret Service / Windows Credential
#:   Locker). Preferred when present.
#: * ``"passphrase_argon2id"`` — an Argon2id passphrase-derived key for
#:   Docker / CI / headless environments with no OS keyring. The Pillar I
#:   per-tenant container has no keyring, so this fallback is MANDATORY
#:   for the multi-tenant container model.
CREDENTIAL_KEYSTORE_BACKENDS: frozenset[str] = frozenset({
    "os_keyring",
    "passphrase_argon2id",
})


#: Closed-set of audit-log export formats per ADR-0076 D382.
AUDIT_LOG_EXPORT_FORMATS: frozenset[str] = frozenset({
    "jsonl",
    "csv",
})


#: Closed-set of the supply-chain scanners wired at J2/J3 (documentation
#: only — these are CI/config surfaces that emit no ledger events) per
#: ADR-0076 D378.
#:
#: * ``"gitleaks"`` — secret scanning in pre-commit (J2).
#: * ``"dependabot"`` — dependency-update + vuln alerts (J3).
#: * ``"osv-scanner"`` — OSV dependency vulnerability scanning (J3).
SECURITY_SCANNERS: frozenset[str] = frozenset({
    "gitleaks",
    "dependabot",
    "osv-scanner",
})


#: The headers a CAN-SPAM-compliant one-click-unsubscribe email MUST
#: carry per RFC 8058 + RFC 2369 (J7; ADR-0076 D381). The send path
#: stamps BOTH on every outbound email via ``gmail_client``'s existing
#: ``extra_headers`` seam.
CANSPAM_REQUIRED_HEADERS: frozenset[str] = frozenset({
    "List-Unsubscribe",
    "List-Unsubscribe-Post",
})


@dataclass(frozen=True)
class SecurityConfig:
    """Operator-deliberate Pillar J security + compliance config (frozen;
    per ADR-0076 D377). Week 1 ships the shape; the per-week bodies +
    the FENCED J5/J6 builds consume it.

    Fields:

    * ``physical_mailing_address`` — the operator's CAN-SPAM-required
      physical postal address, stamped into the body footer of every
      outbound email (J7). Refuse-loud (Week 4 body) if empty when a
      send is attempted — a missing physical address is a CAN-SPAM
      violation per the asymmetric-failure-cost principle (PILLAR-PLAN
      §0): a missed footer costs a legal liability, far more than a
      missed send.
    * ``unsubscribe_base_url`` — the base URL the one-click-unsubscribe
      ``List-Unsubscribe`` header + the footer link point at (J7). The
      per-recipient token is appended by the send path.
    * ``unsubscribe_mailto`` — optional ``mailto:`` fallback for the
      ``List-Unsubscribe`` header (RFC 2369 dual-form).
    * ``keystore_backend`` — member of :data:`CREDENTIAL_KEYSTORE_BACKENDS`
      naming the at-rest credential keystore (J5). Defaults to
      ``"os_keyring"``; the Pillar I container deployment overrides to
      ``"passphrase_argon2id"``.
    * ``audit_export_dir`` — directory the J8 audit-log export writes to.
    * ``tenant_id`` — optional per-tenant binding (Pillar I); when set,
      the per-tenant forget / export / keystore surfaces isolate per
      ADR-0070 D375 (a).

    The frozen invariant matches the Pillar H :class:`DaemonConfig` +
    Pillar I :class:`TenantConfig` precedents — operators construct once;
    the per-week bodies validate + consume.

    **Privacy invariant** per I8 + ADR-0070 D375 (a): ``SecurityConfig``
    holds operator config (addresses, URLs, backend names, paths) +
    NEVER any per-Person field.

    Week 2+ bodies validate: ``keystore_backend`` member of
    :data:`CREDENTIAL_KEYSTORE_BACKENDS`; ``physical_mailing_address``
    non-empty before any send; ``unsubscribe_base_url`` well-formed.
    """

    physical_mailing_address: str
    unsubscribe_base_url: str
    unsubscribe_mailto: Optional[str] = None
    keystore_backend: str = "os_keyring"
    audit_export_dir: Optional[Path] = None
    tenant_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate the security config per ADR-0076 D377 + ADR-0079 (W4 body).

        Refuse-loud (``ValueError``) per the framework convention per
        ADR-0001 D2 on: ``keystore_backend`` outside
        :data:`CREDENTIAL_KEYSTORE_BACKENDS`, empty
        ``physical_mailing_address`` (a missing CAN-SPAM address is a legal
        liability — the asymmetric-failure-cost principle), malformed
        ``unsubscribe_base_url`` (must be ``http(s)://``).
        """
        if self.keystore_backend not in CREDENTIAL_KEYSTORE_BACKENDS:
            raise ValueError(
                f"SecurityConfig: keystore_backend {self.keystore_backend!r} outside "
                f"CREDENTIAL_KEYSTORE_BACKENDS {sorted(CREDENTIAL_KEYSTORE_BACKENDS)} "
                "(ADR-0076 D379)."
            )
        if not (self.physical_mailing_address or "").strip():
            raise ValueError(
                "SecurityConfig: physical_mailing_address must be non-empty — a "
                "missing CAN-SPAM physical address is a legal liability (ADR-0076 "
                "D381 + the asymmetric-failure-cost principle)."
            )
        if not str(self.unsubscribe_base_url).startswith(("http://", "https://")):
            raise ValueError(
                f"SecurityConfig: unsubscribe_base_url {self.unsubscribe_base_url!r} "
                "must be an http(s):// URL (ADR-0076 D381)."
            )


class CredentialKeystore(Protocol):
    """The at-rest credential keystore seam (J5; ADR-0076 D379).

    Two backends satisfy this Protocol per
    :data:`CREDENTIAL_KEYSTORE_BACKENDS`: the OS keyring and the Argon2id
    passphrase-derived key. The Protocol is the TEST-ONLY substitution
    seam (mirrors the Pillar F ``embed_fn`` / ``retrieve_fn`` + the
    Pillar I ``detect_fn`` seams) — tests inject an in-memory fake; the
    Docker container injects the passphrase backend; the dev box uses
    the OS keyring.
    """

    backend: str  # member of CREDENTIAL_KEYSTORE_BACKENDS

    def get_key(self, key_id: str) -> bytes:
        """Return the key bytes for ``key_id`` (raises if absent)."""
        ...

    def put_key(self, key_id: str, key: bytes) -> None:
        """Store ``key`` under ``key_id`` (idempotent overwrite)."""
        ...

    def destroy_key(self, key_id: str) -> bool:
        """Crypto-shred ``key_id`` — the J6 erasure primitive. Returns
        True iff a key was destroyed. After this, any ciphertext
        encrypted under ``key_id`` is mathematically unrecoverable."""
        ...


# ---------------------------------------------------------------------------
# J1 — OAuth refresh-and-retry middleware (R002 mitigation). Week 2 body
# (ADR-0077).
# ---------------------------------------------------------------------------

#: The tenant_id stamped on ``auth_token_refreshed`` when J1 runs in
#: single-tenant mode (no Pillar I per-tenant binding passed). Chosen to
#: match ``multi_tenant._TENANT_ID_PATTERN`` (``^[a-z][a-z0-9_-]{0,62}$``)
#: so the reused payload validates identically on both the single- and
#: per-tenant paths.
_DEFAULT_TENANT_ID = "default"


#: Substrings (lowercased) that mark an expired/invalid-credential failure
#: on a send — the J1 refresh-and-retry trigger (R002). Covers the L0 test
#: seam's ``_Expired401("401 invalid_grant")`` AND the real send surface:
#: ``gmail_client.send_email`` re-raises a googleapiclient ``HttpError`` as
#: ``RuntimeError("Gmail API send failed: <HttpError 401 ...>")`` (see
#: ``skills/send-outreach/scripts/gmail_client.py:108``), and a stale refresh
#: token surfaces as ``google.auth.exceptions.RefreshError`` carrying
#: ``invalid_grant``. We match on text because J1 wraps an OPAQUE ``send_fn``
#: and cannot import every channel client's exception type.
_AUTH_ERROR_SIGNALS: tuple[str, ...] = (
    "401",
    "invalid_grant",
    "invalid_token",
    "unauthorized",
    "invalid credentials",
    "token has been expired",
    "token expired",
    "refresherror",
)


def _iso_z(dt: datetime) -> str:
    """Millisecond-precision ISO-8601 UTC with a trailing ``Z`` —
    byte-identical to ``ledger._now_iso`` + ``multi_tenant._iso_z`` (the
    ADR-0031 determinism contract)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _is_auth_error(exc: BaseException) -> bool:
    """True iff ``exc`` is an expired/invalid-credential failure (HTTP 401
    or an OAuth refresh error) — the ONLY class J1 refreshes-and-retries on.
    A non-auth failure (a 5xx, a network error, a bad recipient) is NOT
    retried here; it propagates unchanged so the caller's own retry/abort
    policy applies (refuse-loud per ADR-0001 D2)."""
    # Structured status first — googleapiclient ``HttpError`` carries
    # ``.resp.status``; a custom client may expose ``.status_code`` / ``.code``.
    for _attr in ("status_code", "code"):
        if getattr(exc, _attr, None) == 401:
            return True
    _resp = getattr(exc, "resp", None)
    if getattr(_resp, "status", None) in (401, "401"):
        return True
    _text = f"{type(exc).__name__}: {exc}".lower()
    return any(_sig in _text for _sig in _AUTH_ERROR_SIGNALS)


def send_with_token_rotation(
    send_fn: Callable[[], Any],
    *,
    refresh_fn: Callable[[], Any],
    led: Any,
    tenant_id: Optional[str] = None,
    token_scope: str = "gmail.send",
    max_retries: int = 1,
    now: "Optional[datetime]" = None,
) -> Any:
    """Wrap a single per-channel send with mid-batch token rotation (J1;
    R002). Run ``send_fn``; on a ``401`` / refresh error, call
    ``refresh_fn`` ONCE, emit ``auth_token_refreshed`` (the cataloged
    Pillar I class — see module docstring), and retry. Guarantees the
    ledger ends consistent (no orphan ``send_intent`` without a matching
    ``send_confirmed`` / ``send_failed``) per R002's mitigation.

    Failure handling (refuse-loud per ADR-0001 D2):

    * A NON-auth exception propagates immediately — J1 only owns credential
      rotation, not generic retry.
    * After ``max_retries`` (default 1) auth failures the last exception
      re-raises — no unbounded refresh loop on a credential that stays bad.

    The ``auth_token_refreshed`` emit lands AFTER ``refresh_fn`` actually
    runs (the ledger never claims a refresh that did not happen) and BEFORE
    the retry (a rotation is recorded even if the retry itself then fails),
    and exactly ONCE per refresh (the single-emitter property).

    Week 2 (ADR-0077) ships the body; Week 1 ships the signature.
    """
    attempts = 0
    while True:
        try:
            return send_fn()
        except Exception as exc:  # noqa: BLE001 — re-raised unless _is_auth_error
            if attempts >= max_retries or not _is_auth_error(exc):
                raise
            attempts += 1
            refresh_fn()
            refreshed_at_ts = _iso_z(
                now if now is not None else datetime.now(timezone.utc)
            )
            led.append(build_auth_token_refreshed_payload(
                tenant_id=tenant_id or _DEFAULT_TENANT_ID,
                token_scope=token_scope,
                refreshed_at_ts=refreshed_at_ts,
            ))


def build_auth_token_refreshed_payload(
    *, tenant_id: str, token_scope: str, refreshed_at_ts: str,
) -> dict[str, Any]:
    """Build the ``auth_token_refreshed`` event payload (J1). REUSES the
    Pillar I event class per ADR-0070 D371 (``auth_token_refreshed`` is
    already in the catalog + :data:`orchestrator.multi_tenant.TENANT_NEW_EVENT_CLASSES`);
    J1 is its first EMITTER. Payload shape mirrors ADR-0070 D371 line 85
    EXACTLY — including ``_emitted_by="multi_tenant"`` (NOT ``"security"``):
    the class is multi_tenant-owned + cataloged, so it is deliberately
    excluded from :data:`SECURITY_NEW_EVENT_CLASSES` and keeps Pillar I's
    attribution regardless of which pillar emits it.

    Validation mirrors :func:`orchestrator.multi_tenant.build_init_wizard_completed_payload`
    (the sibling reused-context factory): refuse-loud (``ValueError``) on a
    malformed ``tenant_id``, a ``token_scope`` outside
    :data:`orchestrator.multi_tenant.TENANT_OAUTH_TOKEN_SCOPES`, or an empty
    ``refreshed_at_ts``. The returned dict carries its own ``type`` (consistent
    with the sibling :func:`build_identity_keys_modified_payload`), so the
    caller appends it directly: ``led.append(build_auth_token_refreshed_payload(...))``.

    Week 2 (ADR-0077) ships the body; Week 1 shipped the signature.
    """
    from orchestrator.multi_tenant import (
        EMITTED_BY as _PILLAR_I_EMITTED_BY,
        TENANT_OAUTH_TOKEN_SCOPES,
        _validate_tenant_id,
    )

    _validate_tenant_id(tenant_id)
    if token_scope not in TENANT_OAUTH_TOKEN_SCOPES:
        raise ValueError(
            f"build_auth_token_refreshed_payload: token_scope {token_scope!r} "
            f"outside TENANT_OAUTH_TOKEN_SCOPES {sorted(TENANT_OAUTH_TOKEN_SCOPES)} "
            "(ADR-0070 D371)."
        )
    if not refreshed_at_ts:
        raise ValueError(
            "build_auth_token_refreshed_payload requires a non-empty "
            "refreshed_at_ts (ISO-8601 UTC); J1 derives it from the "
            "deterministic-clock `now` anchor."
        )
    return {
        "type": "auth_token_refreshed",
        "tenant_id": tenant_id,
        "token_scope": token_scope,
        "refreshed_at_ts": refreshed_at_ts,
        "_emitted_by": _PILLAR_I_EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# J5 — encrypted-at-rest credentials (FENCED; human-gated). ADR-0080 body.
# ---------------------------------------------------------------------------
def resolve_keystore(
    *,
    backend: str = "os_keyring",
    passphrase: Optional[str] = None,
    service_name: str = "outreach-factory",
    tenant_id: Optional[str] = None,
) -> CredentialKeystore:
    """Select the at-rest credential keystore (J5; ADR-0076 D379).

    ``backend`` is a member of :data:`CREDENTIAL_KEYSTORE_BACKENDS`.
    ``"os_keyring"`` uses the ``keyring`` library; ``"passphrase_argon2id"``
    derives the master key from ``passphrase`` via Argon2id (MANDATORY in
    Docker / CI / headless — no OS keyring exists there). FENCED build —
    see ``.planning/RALPH-BLOCKED.md``.
    """
    raise NotImplementedError(
        "resolve_keystore is a FENCED Pillar J build (J5; ADR-0080) — see "
        ".planning/RALPH-BLOCKED.md; Week 1 ships the signature."
    )


def derive_person_data_key(
    person_id: str, *, keystore: CredentialKeystore, tenant_id: Optional[str] = None,
) -> bytes:
    """Derive / fetch the per-person data-encryption key (DEK) that
    encrypts that person's PII fields in the ledger at rest (J5). J6
    crypto-shreds this DEK to erase the person. FENCED build (ADR-0080).
    """
    raise NotImplementedError(
        "derive_person_data_key is a FENCED Pillar J build (J5; ADR-0080) — "
        "see .planning/RALPH-BLOCKED.md; Week 1 ships the signature."
    )


def encrypt_credential(
    plaintext: bytes, *, keystore: CredentialKeystore, key_id: str,
) -> bytes:
    """Encrypt a credential (or PII field) at rest under ``key_id`` (J5).
    FENCED build (ADR-0080)."""
    raise NotImplementedError(
        "encrypt_credential is a FENCED Pillar J build (J5; ADR-0080) — see "
        ".planning/RALPH-BLOCKED.md; Week 1 ships the signature."
    )


def decrypt_credential(
    ciphertext: bytes, *, keystore: CredentialKeystore, key_id: str,
) -> bytes:
    """Decrypt a credential (or PII field) under ``key_id`` (J5). Raises
    if ``key_id`` was crypto-shredded (the J6 erasure proof). FENCED
    build (ADR-0080)."""
    raise NotImplementedError(
        "decrypt_credential is a FENCED Pillar J build (J5; ADR-0080) — see "
        ".planning/RALPH-BLOCKED.md; Week 1 ships the signature."
    )


def build_credentials_reencrypted_payload(
    *, tenant_id: str, key_id: str, backend: str, reencrypted_at_ts: str,
) -> dict[str, Any]:
    """Build the ``credentials_reencrypted`` event payload (J5). FENCED
    build (ADR-0080)."""
    raise NotImplementedError(
        "build_credentials_reencrypted_payload is a FENCED Pillar J build "
        "(J5; ADR-0080) — see .planning/RALPH-BLOCKED.md."
    )


# ---------------------------------------------------------------------------
# J6 — GDPR forget via tombstone + crypto-shred (FENCED; depends on J5).
# ADR-0080 body + ADR-0004 §"GDPR forget path".
# ---------------------------------------------------------------------------
def forget_person(
    person_id: str,
    *,
    led: Any,
    vault_dir: Path,
    suppressions_dir: Path,
    keystore: CredentialKeystore,
    tenant_id: Optional[str] = None,
    now: "Optional[datetime]" = None,
) -> dict[str, Any]:
    """Run the GDPR ``forget --person`` transaction (J6; ADR-0076 D380 +
    ADR-0004 §"GDPR forget path"). Holds a lock spanning all steps:

    1. **Crypto-shred** the person's DEK (``keystore.destroy_key``) so the
       ciphertext PII in the append-only ledger is unrecoverable — the
       ledger bytes are NEVER mutated (I2 sacrosanct; append-only
       preserved under erasure per ADR-0076 invariant 2).
    2. Atomic ``suppression.forget_append`` (Pillar A; already shipped) so
       no future send can re-reach the person.
    3. Purge the vault Person + Touch notes (derived/reconstructable —
       safe to delete, unlike the ledger SoT).
    4. Emit ``gdpr_forget`` with a ``person_ref`` HASH (never cleartext
       ``person_id``) + the purge audit trail.

    Returns the audit dict. FENCED build (depends on J5; ADR-0080) — see
    ``.planning/RALPH-BLOCKED.md``.
    """
    raise NotImplementedError(
        "forget_person is a FENCED Pillar J build (J6, depends on J5; "
        "ADR-0080) — see .planning/RALPH-BLOCKED.md; Week 1 ships the signature."
    )


def build_gdpr_forget_payload(
    *,
    person_ref: str,
    key_destroyed: bool,
    n_events_shredded: int,
    suppression_appended: bool,
    vault_purged: bool,
    forgotten_at_ts: str,
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``gdpr_forget`` tombstone payload (J6). ``person_ref`` is
    a HASH of the forgotten ``person_id`` — NEVER the cleartext id (the
    privacy invariant; the whole point is that the person is forgotten).
    FENCED build (ADR-0080)."""
    raise NotImplementedError(
        "build_gdpr_forget_payload is a FENCED Pillar J build (J6; ADR-0080) "
        "— see .planning/RALPH-BLOCKED.md."
    )


# ---------------------------------------------------------------------------
# J7 — CAN-SPAM footer + one-click unsubscribe header. Week 4 body (ADR-0079).
# ---------------------------------------------------------------------------
def build_canspam_footer(
    *, physical_mailing_address: str, unsubscribe_url: str,
) -> str:
    """Build the CAN-SPAM physical-address + unsubscribe body footer (J7;
    ADR-0076 D381 + ADR-0079). Stamped into every outbound email body via
    ``gmail_client.send_email``'s existing ``body_footer`` seam. Refuse-loud
    (``ValueError``, ADR-0001 D2) on an empty address / URL — a missing
    CAN-SPAM physical address is a legal liability (asymmetric-failure-cost).
    """
    if not (physical_mailing_address or "").strip():
        raise ValueError(
            "build_canspam_footer requires a non-empty physical_mailing_address "
            "(CAN-SPAM §5; ADR-0076 D381)."
        )
    if not (unsubscribe_url or "").strip():
        raise ValueError(
            "build_canspam_footer requires a non-empty unsubscribe_url (one-click "
            "unsubscribe; ADR-0076 D381)."
        )
    # NB: the footer separator is a plain blank-line break, NOT an em dash.
    # Em dashes are a banned character in all outbound text (operator
    # preference: they read as machine-written). No test pins the separator
    # glyph (the J7 unit + golden-path barriers assert only the address +
    # unsubscribe-link presence), so this is safe against the gate.
    return (
        "\n\n"
        f"To unsubscribe: {unsubscribe_url}\n"
        f"{physical_mailing_address}\n"
    )


def build_list_unsubscribe_headers(
    *, unsubscribe_url: str, mailto: Optional[str] = None,
) -> dict[str, str]:
    """Build the one-click ``List-Unsubscribe`` + ``List-Unsubscribe-Post``
    headers (J7; RFC 8058 + RFC 2369; ADR-0076 D381 + ADR-0079). Returns a
    dict keyed by :data:`CANSPAM_REQUIRED_HEADERS`, stamped via
    ``gmail_client.send_email``'s existing ``extra_headers`` seam. The URL +
    optional ``mailto`` are RFC-2369 angle-bracketed; the ``-Post`` header
    carries the RFC-8058 one-click directive. Refuse-loud on an empty URL.
    """
    if not (unsubscribe_url or "").strip():
        raise ValueError(
            "build_list_unsubscribe_headers requires a non-empty unsubscribe_url "
            "(RFC 8058 one-click; ADR-0076 D381)."
        )
    targets = [f"<{unsubscribe_url}>"]
    if mailto:
        # Accept both "mailto:addr" and a bare "addr".
        targets.append(f"<{mailto if mailto.startswith('mailto:') else 'mailto:' + mailto}>")
    return {
        "List-Unsubscribe": ", ".join(targets),
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


# ---------------------------------------------------------------------------
# J8 — audit-log export for compliance reviews. Week 3 body (ADR-0078 D391).
# ---------------------------------------------------------------------------

#: Closed-set of ledger event fields the redact-by-default export
#: pseudonymizes (ADR-0078 D391; R031 closed-set). Default-ALLOW export with
#: this over-broad redact set keeps audit richness while the
#: asymmetric-failure-cost bias (hash anything that correlates to a Person)
#: holds the privacy line per I8 + ADR-0070 D375 (a) — a missed field is a
#: reviewable closed-set edit, not a silent leak. Covers:
#:
#: * **person-resolving identifiers** — ``person_id`` and ``intent_id`` (the
#:   intent id embeds the person_id as ``snd_<pid>`` per ledger.new_intent_id,
#:   so a person_id-only redaction would leak the substring);
#: * **contact handles** — email / linkedin / generic handle fields;
#: * **per-channel external message + thread ids** (gmail / linkedin);
#: * **operator-confidential free-text** (ADR-0038 D182 + I8) — subject /
#:   body / draft / reply text + the discovery ``signal`` blurb.
#:
#: Values are HASHED, not dropped (ADR-0078 Alt-2 rejected): stable
#: pseudonymization preserves within-export correlation (which rows concern
#: the same subject) that a compliance reviewer needs. Salted anonymization
#: is v2.
_AUDIT_REDACT_FIELDS: frozenset[str] = frozenset({
    # person-resolving identifiers
    "person_id",
    "intent_id",
    # contact handles
    "email",
    "to",
    "to_email",
    "from_email",
    "contact",
    "handle",
    "linkedin",
    # per-channel external message / thread ids
    "gmail_message_id",
    "gmail_thread_id",
    "message_id",
    "thread_id",
    "li_message_id",
    "li_thread_id",
    # operator-confidential free-text (ADR-0038 D182 + I8)
    "subject",
    "body",
    "body_preview",
    "snippet",
    "draft",
    "draft_text",
    "notes",
    "signal",
    "reply_text",
})


def _redact_token(value: Any) -> str:
    """Stable ``sha256:<12hex>`` pseudonym for a redacted field value
    (ADR-0078 D391). Deterministic per value → equal subjects collide →
    within-export correlation is preserved without cleartext."""
    return "sha256:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _redact_event(d: dict[str, Any], redact: bool) -> dict[str, Any]:
    """Return a copy of event dict ``d`` with every :data:`_AUDIT_REDACT_FIELDS`
    value replaced by a :func:`_redact_token` pseudonym (when ``redact``).
    ``None`` values pass through (nothing to leak)."""
    if not redact:
        return dict(d)
    return {
        k: (_redact_token(v) if (k in _AUDIT_REDACT_FIELDS and v is not None) else v)
        for k, v in d.items()
    }


def _covers(ts: Optional[str], since_ts: Optional[str], until_ts: Optional[str]) -> bool:
    """Inclusive [since, until] ISO-string-compare window (the same byte-wise
    chronological compare reconcile uses; ADR-0031 determinism). An event with
    no ``ts`` is always covered (it cannot be excluded by a time filter)."""
    if ts is None:
        return True
    if since_ts is not None and ts < since_ts:
        return False
    if until_ts is not None and ts > until_ts:
        return False
    return True


def export_audit_log(
    led: Any,
    *,
    out_path: Path,
    out_format: str = "jsonl",
    since: "Optional[datetime]" = None,
    until: "Optional[datetime]" = None,
    redact: bool = True,
    now: "Optional[datetime]" = None,
) -> dict[str, Any]:
    """Export a read-only, redact-by-default compliance audit log over the
    ledger (J8; ADR-0076 D382 + ADR-0078 D391). READ-ONLY contract per
    ADR-0059 D325 (the funnel-CLI precedent): walk the (optionally
    ``since``/``until``-filtered) ledger, write the covered events to
    ``out_path``, then append EXACTLY ONE ``audit_log_exported`` marker — the
    export never rewrites prior events (I2 append-only). ``n_events`` counts
    the covered (pre-marker) events. ``out_format`` is a member of
    :data:`AUDIT_LOG_EXPORT_FORMATS` (refuse-loud otherwise, ADR-0001 D2).
    """
    if out_format not in AUDIT_LOG_EXPORT_FORMATS:
        raise ValueError(
            f"export_audit_log: out_format {out_format!r} outside "
            f"AUDIT_LOG_EXPORT_FORMATS {sorted(AUDIT_LOG_EXPORT_FORMATS)} (ADR-0076 D382)."
        )

    since_ts = _iso_z(since) if since is not None else None
    until_ts = _iso_z(until) if until is not None else None

    # READ-ONLY pass — collect the covered events BEFORE appending the marker
    # so the marker never counts itself (n_events = pre-marker covered count).
    covered = [
        e.to_dict() for e in led.all_events()
        if _covers(e.to_dict().get("ts"), since_ts, until_ts)
    ]
    rows = [_redact_event(d, redact) for d in covered]
    n_events = len(covered)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_format == "jsonl":
        with out_path.open("w", encoding="utf-8") as fh:
            for d in rows:
                fh.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    else:  # "csv" — union of keys (stable sorted); list/dict cells JSON-encoded
        fields = sorted({k for d in rows for k in d})
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for d in rows:
                writer.writerow({
                    k: (json.dumps(v, ensure_ascii=False, sort_keys=True)
                        if isinstance(v, (list, dict)) else v)
                    for k, v in d.items()
                })

    exported_at_ts = _iso_z(now if now is not None else datetime.now(timezone.utc))
    led.append(build_audit_log_exported_payload(
        exported_at_ts=exported_at_ts,
        n_events=n_events,
        out_format=out_format,
        redacted=redact,
        since_ts=since_ts,
        until_ts=until_ts,
    ))

    return {
        "n_events": n_events,
        "out_path": str(out_path),
        "out_format": out_format,
        "redacted": redact,
        "since_ts": since_ts,
        "until_ts": until_ts,
        "exported_at_ts": exported_at_ts,
    }


def build_audit_log_exported_payload(
    *,
    exported_at_ts: str,
    n_events: int,
    out_format: str,
    redacted: bool,
    since_ts: Optional[str] = None,
    until_ts: Optional[str] = None,
) -> dict[str, Any]:
    """Build the ``audit_log_exported`` event payload (J8; ADR-0078 D391).
    Refuse-loud (``ValueError``, ADR-0001 D2) on a bad ``out_format``, an empty
    ``exported_at_ts``, or a negative ``n_events``. Carries
    ``_emitted_by="security"`` (the export is Pillar-J-owned) + a ``type`` so
    the caller appends it directly: ``led.append(build_audit_log_exported_payload(...))``.
    """
    if out_format not in AUDIT_LOG_EXPORT_FORMATS:
        raise ValueError(
            f"build_audit_log_exported_payload: out_format {out_format!r} outside "
            f"AUDIT_LOG_EXPORT_FORMATS {sorted(AUDIT_LOG_EXPORT_FORMATS)}."
        )
    if not exported_at_ts:
        raise ValueError(
            "build_audit_log_exported_payload requires a non-empty exported_at_ts "
            "(ISO-8601 UTC); J8 derives it from the deterministic-clock `now` anchor."
        )
    if n_events < 0:
        raise ValueError(
            f"build_audit_log_exported_payload: n_events {n_events} must be >= 0."
        )
    return {
        "type": "audit_log_exported",
        "exported_at_ts": exported_at_ts,
        "n_events": n_events,
        "out_format": out_format,
        "redacted": redacted,
        "since_ts": since_ts,
        "until_ts": until_ts,
        "_emitted_by": EMITTED_BY,
    }


# ---------------------------------------------------------------------------
# R001 — identity-graph false-merge audit (assigned INTO Pillar J).
# Week 3 body (ADR-0078 D392). Reverse-merge `identity.py split` tooling = v2.
# ---------------------------------------------------------------------------

#: Closed-set of valid R001 audit actors (ADR-0078 D392; R031). Who mutated a
#: Person's frontmatter identity keys: a human ``operator``, a ``reconcile``
#: pass, or the ``enrollment`` path that first minted them.
_IDENTITY_KEYS_ACTORS: frozenset[str] = frozenset({
    "operator",
    "reconcile",
    "enrollment",
})


def _flatten_identity_keys(keys: Any) -> list[str]:
    """Flatten an :class:`orchestrator.identity.IdentityKeys` into the sorted
    ``"<class>:<value>"`` string form R001 audits (``li:`` / ``em:`` / ``gh:``
    / ``tw:``). ``alt_names`` + ``country`` are NOT identity match-classes
    (``identity.keys_intersect`` — names are too unstable for dedup), so they
    are excluded from the audited key-set."""
    out: list[str] = []
    if getattr(keys, "linkedin", None):
        out.append(f"li:{keys.linkedin}")
    out.extend(f"em:{e}" for e in (getattr(keys, "emails", None) or ()))
    if getattr(keys, "github", None):
        out.append(f"gh:{keys.github}")
    if getattr(keys, "twitter", None):
        out.append(f"tw:{keys.twitter}")
    return sorted(out)


def detect_identity_keys_drift(
    led: Any, *, vault_dir: Path, now: "Optional[datetime]" = None,
) -> list[dict[str, Any]]:
    """Flag any Person whose vault frontmatter identity keys diverge from the
    ledger keys-view (R001; ADR-0076 D383 + ADR-0078 D392). READ-ONLY: build
    the ledger view (latest ``identity_keys_modified.after_keys`` per
    ``person_id`` is the last audited state), then compare each vault Person
    note's current keys. Returns one drift record per audited Person whose
    vault keys diverge — the manual-merge drift that has no audit trail today;
    reconcile consumes it. A Person with NO audit baseline is not flagged (it
    has nothing to diverge *from*). Returns ``[]`` when every audited Person
    matches. (``now`` is reserved for a future as-of window; the view spans the
    whole trail today.)
    """
    from orchestrator.identity import read_person_keys

    ledger_view: dict[str, list[str]] = {}
    for ev in led.all_events():
        d = ev.to_dict()
        if d.get("type") == "identity_keys_modified" and d.get("person_id"):
            ledger_view[d["person_id"]] = sorted(d.get("after_keys") or [])

    drift: list[dict[str, Any]] = []
    vault_dir = Path(vault_dir)
    if not vault_dir.exists():
        return drift
    for note in sorted(vault_dir.rglob("*.md")):
        parsed = read_person_keys(note)
        if parsed is None:
            continue
        pid, keys = parsed
        if not pid or pid not in ledger_view:
            continue
        recorded = ledger_view[pid]
        vault_keys = _flatten_identity_keys(keys)
        if vault_keys != recorded:
            drift.append({
                "person_id": pid,
                "ledger_keys": recorded,
                "vault_keys": vault_keys,
                "added": sorted(set(vault_keys) - set(recorded)),
                "removed": sorted(set(recorded) - set(vault_keys)),
                "note": str(note),
            })
    return drift


def build_identity_keys_modified_payload(
    *,
    person_id: str,
    before_keys: list[str],
    after_keys: list[str],
    actor: str,
    modified_at_ts: str,
) -> dict[str, Any]:
    """Build the ``identity_keys_modified`` audit payload (R001; ADR-0078 D392).
    ``actor`` is one of :data:`_IDENTITY_KEYS_ACTORS`
    (``operator`` / ``reconcile`` / ``enrollment``). The in-ledger audit row
    carries cleartext ``person_id`` exactly as every other ledger event does
    (the ledger is the SoT) — the no-cleartext-PII invariant applies to EXPORTS
    (J8 redacts) and the ``gdpr_forget`` tombstone (hashed ``person_ref``), NOT
    to in-ledger audit rows (ADR-0078 D392 + Alt-3 rejected). Refuse-loud
    (``ValueError``, ADR-0001 D2) on an empty ``person_id``, an ``actor``
    outside the closed-set, or an empty ``modified_at_ts``. Carries
    ``_emitted_by="security"`` + a ``type`` so the caller appends it directly.
    """
    if not person_id:
        raise ValueError(
            "build_identity_keys_modified_payload requires a non-empty person_id."
        )
    if actor not in _IDENTITY_KEYS_ACTORS:
        raise ValueError(
            f"build_identity_keys_modified_payload: actor {actor!r} outside "
            f"_IDENTITY_KEYS_ACTORS {sorted(_IDENTITY_KEYS_ACTORS)} (ADR-0078 D392)."
        )
    if not modified_at_ts:
        raise ValueError(
            "build_identity_keys_modified_payload requires a non-empty "
            "modified_at_ts (ISO-8601 UTC)."
        )
    return {
        "type": "identity_keys_modified",
        "person_id": person_id,
        "before_keys": list(before_keys),
        "after_keys": list(after_keys),
        "actor": actor,
        "modified_at_ts": modified_at_ts,
        "_emitted_by": EMITTED_BY,
    }


__all__ = [
    "EMITTED_BY",
    "SECURITY_NEW_EVENT_CLASSES",
    "CREDENTIAL_KEYSTORE_BACKENDS",
    "AUDIT_LOG_EXPORT_FORMATS",
    "SECURITY_SCANNERS",
    "CANSPAM_REQUIRED_HEADERS",
    "SecurityConfig",
    "CredentialKeystore",
    # J1 — OAuth refresh-and-retry (Week 2)
    "send_with_token_rotation",
    "build_auth_token_refreshed_payload",
    # J5 — encrypted-at-rest (FENCED)
    "resolve_keystore",
    "derive_person_data_key",
    "encrypt_credential",
    "decrypt_credential",
    "build_credentials_reencrypted_payload",
    # J6 — GDPR forget crypto-shred (FENCED)
    "forget_person",
    "build_gdpr_forget_payload",
    # J7 — CAN-SPAM (Week 4)
    "build_canspam_footer",
    "build_list_unsubscribe_headers",
    # J8 — audit-log export (Week 3)
    "export_audit_log",
    "build_audit_log_exported_payload",
    # R001 — identity audit (Week 3)
    "detect_identity_keys_drift",
    "build_identity_keys_modified_payload",
]
