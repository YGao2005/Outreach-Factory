# ADR-0080: Pillar J Week 5/6 - encrypted-at-rest credentials (J5) + GDPR crypto-shred forget (J6)

- **Status:** Accepted
- **Date:** 2026-06-01
- **Pillar:** J (Security + compliance)
- **Deciders:** Operator (human-gated build - the J5/J6 fence is lifted deliberately, not in the autonomous loop)

## Context

ADR-0076 D379/D380 reserved **J5** (encrypted-at-rest credentials) and **J6**
(GDPR `forget --person` via crypto-shred) as FENCED, human-gated builds: Week 1
shipped the closed-sets (`CREDENTIAL_KEYSTORE_BACKENDS`,
`SECURITY_NEW_EVENT_CLASSES`), the `CredentialKeystore` Protocol, and six
`NotImplementedError` signatures. ADR-0078 D390 catalogued `gdpr_forget` +
`credentials_reencrypted` into `EVENT_CLASS_CATALOG`. The two golden-path
liveness tests (`test_pillar_J_credentials_encrypted_at_rest`,
`test_pillar_J_forget_person_crypto_shred_leaves_audit`) were authored
`xfail(strict=False)` against those seams.

The fence existed because crypto-shred erasure is irreversible and credential
encryption is security-critical: the autonomous loop must not build it
unsupervised. This ADR lifts the fence under human authorship.

The trigger is the OSS-launch credibility audit: shipping
`NotImplementedError` for the exact GDPR-forget + credential-security surface
that ADR-0004 presents as designed reads as compliance theater. The decision
(operator, 2026-06-01) is to **implement both for real**, not to relabel them
roadmap.

## Decision

**D396 - J5 keystore seam: two backends, both satisfying the `CredentialKeystore`
Protocol; crypto libs lazy-imported.**
`resolve_keystore(*, backend, passphrase=None, service_name="outreach-factory",
tenant_id=None, store_path=None)` returns a concrete keystore:
- `"passphrase_argon2id"` - `_PassphraseKeystore`. An Argon2id-derived master key
  (from `passphrase` + a 16-byte salt) wraps per-`key_id` data-encryption keys
  (DEKs) **at rest**. MANDATORY for Docker / CI / headless (no OS keyring). DEKs
  live in memory by default (hermetic for tests); persistence is opt-in via
  `store_path` (the wrapped-DEK JSON + salt). Refuse-loud (`ValueError`) on an
  empty passphrase.
- `"os_keyring"` - `_OSKeyringKeystore`. DEKs stored in the OS-native secret
  store (macOS Keychain / Linux Secret Service / Windows Credential Locker) via
  a **lazily-imported** `keyring`. A clear `RuntimeError` (not `ImportError`)
  fires if `keyring` is absent, naming the install. The dev box default.

`cryptography` (AES-GCM) and `argon2-cffi` (Argon2id) are imported INSIDE the J5
functions, never at module top, so `import orchestrator.security` still succeeds
for the CAN-SPAM / J1 / J8 surfaces in an environment without the crypto extras.
They are nonetheless first-class runtime deps in `orchestrator/requirements.txt`
(the feature is supported, not optional). `keyring` stays uninstalled-by-default
(only the OS-keyring backend needs it).

**D397 - J5 encryption + crypto-shred erasure model.**
`encrypt_credential(plaintext, *, keystore, key_id) -> bytes` mints a random
256-bit DEK for `key_id` on first use (`keystore.put_key`), then AES-GCM-encrypts
with a fresh 12-byte nonce and `key_id` as additional authenticated data,
returning `nonce || ciphertext`. `decrypt_credential(ciphertext, *, keystore,
key_id) -> bytes` fetches the DEK (`keystore.get_key`, which **raises** if the
key was destroyed) and AES-GCM-decrypts. `keystore.destroy_key(key_id)` removes
the DEK - **crypto-shred**: with the only key gone, the ciphertext is
mathematically unrecoverable, so `decrypt_credential` raises afterward. This is
the J6 erasure primitive: destroying one small key erases an arbitrary volume of
ciphertext without touching the ciphertext bytes. Nonces are `os.urandom` (the
ADR-0031 byte-identical-determinism contract governs ledger timestamps, NOT
crypto nonces - those MUST be non-deterministic).

**D398 - J6 `forget_person` transaction: shred → suppress → purge → emit, under
a lock, with the append-only ledger NEVER mutated (I2 sacrosanct).**
`forget_person(person_id, *, led, vault_dir, suppressions_dir, keystore,
tenant_id=None, now=None) -> dict` runs, holding a forget lock spanning all
steps (mirrors the ADR-0004 §"GDPR forget path" + §Compliance I2 atomicity
requirement):
1. Resolve the person's vault note + extract their email / identity keys
   (BEFORE purge, so the suppression entry can be written).
2. **Crypto-shred** the person's DEK (`keystore.destroy_key(person_id)`). The
   append-only ledger bytes are NEVER rewritten - erasure is achieved by
   destroying the key that decrypts the person's at-rest PII, preserving the
   I2 append-only invariant (ADR-0076 invariant 2; ADR-0060 D335 invariant 2)
   under GDPR Art. 17.
3. Atomic `policy.suppression.forget_append(suppressions_dir, email=...,
   identity_key=...)` → `gdpr-forget.yml`, so a rebuilt vault cannot re-enroll
   the person.
4. Purge the derived vault Person note(s) (reconstructable, unlike the ledger
   SoT - safe to delete).
5. Emit `gdpr_forget` (D400) into the ledger.

The order is shred-first so a crash after step 2 still leaves the person
un-decryptable (fail-safe toward erasure). `forget_person` returns the tombstone
dict (carrying `key_destroyed`).

**D399 - `person_id` → vault-note resolution by re-minting the canonical id,
pinned by a parity regression test.**
The canonical person-id mint is `"p_" + re.sub(r"[^a-z0-9]+","_",
name.lower()).strip("_")` (`multi_tenant._default_enroll`). It is lossy and not
invertible, so J6 resolves a note by re-minting EACH note's display name
(frontmatter `name:` or filename stem) and comparing to the target `person_id`
(also honoring an explicit frontmatter `person_id:`). A new regression test
asserts `security._mint_person_id` agrees with the `multi_tenant` mint on a
sample set, so the two cannot drift (the recurring Pillar-H/I failure mode:
local re-derivation diverging from the canonical source).

**D400 - `gdpr_forget` tombstone + `credentials_reencrypted` payloads; privacy
invariant: the tombstone carries a HASH, never a cleartext `person_id`.**
`build_gdpr_forget_payload(*, person_ref, key_destroyed, n_events_shredded,
suppression_appended, vault_purged, forgotten_at_ts, audit) -> dict` returns the
`gdpr_forget` event. `forget_person` computes `person_ref = "sha256:" +
sha256(person_id)[:16]` - the same opaque-person-hash convention as the D385
unsubscribe token (I8). `build_gdpr_forget_payload` refuses-loud if `person_ref`
is not a `sha256:` hash (defense against a cleartext leak) and never includes a
`person_id` key. `build_credentials_reencrypted_payload(*, tenant_id, key_id,
backend, reencrypted_at_ts) -> dict` returns the `credentials_reencrypted` event
(emitted on key rotation; `backend` ∈ `CREDENTIAL_KEYSTORE_BACKENDS`). Both stamp
`_emitted_by="security"`.

**D401 - un-fence: the two J5/J6 golden-path liveness tests drop their `xfail`
markers and become permanent GREEN regression barriers.**
This closes the J5/J6 BUILD. The v1-release human tier from ADR-0076 D384/D387
(J4 SLSA provenance, J9 external pen-test all-findings-closed, legal sign-off)
remains open and is NOT claimed by this ADR.

## Consequences

- **Positive:** GDPR Art. 17 erasure is real and provable (destroy the key →
  decrypt raises), with the append-only ledger intact. Credentials are
  AES-GCM-encrypted at rest under a passphrase- or OS-protected key. The two
  fenced tests become regression barriers. The OSS tree no longer ships
  `NotImplementedError` for advertised compliance features.
- **Negative / cost:** Two new runtime deps (`cryptography`, `argon2-cffi`).
  `keyring` is required only for the OS-keyring backend (lazy, clear error).
  Operators using the passphrase backend MUST persist the salt + wrapped-DEK
  store (`store_path`) for cross-process credential continuity; an ephemeral
  in-memory keystore loses its DEKs on restart (documented).
- **Invariant preserved (I2):** the ledger is never rewritten under erasure -
  crypto-shred + a hashed tombstone, not a delete. `forget_person` holds a lock
  spanning the shred + suppression + purge + emit so the suppression list and
  the ledger cannot diverge.
- **Privacy (I8):** no `gdpr_forget` payload carries a cleartext `person_id`.

## References

- ADR-0076 D377/D379/D380/D384/D387 - Pillar J foundation, the J5/J6 fence, the
  two-tier Stable decision, the trajectory.
- ADR-0004 §"GDPR forget path" - the forget transaction shape + I2 atomicity.
- ADR-0078 D390 - `gdpr_forget` + `credentials_reencrypted` catalog entries.
- ADR-0079 D385 - the `sha256(person_id)[:16]` opaque-person-hash convention.
- ADR-0031 - byte-identical determinism (timestamps; explicitly NOT crypto nonces).
- ADR-0001 D2 - refuse-loud convention.
