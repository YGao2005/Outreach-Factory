"""Pillar J Week 5/6 (J5/J6) unit coverage for the un-fenced builds (ADR-0080).

The golden-path liveness tests
(`tests/golden_path/test_l0_spine_liveness.py::...credentials_encrypted_at_rest`
and `...forget_person_crypto_shred_leaves_audit`) are the binding contract.
This file adds the supporting regression barriers ADR-0080 commits to:

  * D399 mint-parity: `security._mint_person_id` MUST agree with the canonical
    `multi_tenant._default_enroll` mint, so J6's vault-note resolution cannot
    drift from how person_ids are actually minted.
  * D397 crypto: encrypt/decrypt round-trip, the crypto-shred erasure proof,
    and at-rest persistence under the Argon2id-wrapped store.
  * D400/D396 refuse-loud: the tombstone rejects a cleartext person_ref;
    resolve_keystore rejects an unknown backend / empty passphrase.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from orchestrator.security import (
    CREDENTIAL_KEYSTORE_BACKENDS,
    build_credentials_reencrypted_payload,
    build_gdpr_forget_payload,
    decrypt_credential,
    encrypt_credential,
    resolve_keystore,
)
from orchestrator.security import _mint_person_id


# --- D399: mint parity with the canonical multi_tenant source ---------------
class _FakeLed:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)
        return event


@pytest.mark.parametrize(
    "name",
    [
        "Dana Reyes",
        "Anya K. Muller",
        "  spaced   name  ",
        "MixedCASE Person",
        "Jean-Luc O'Brien",
        "X AE A 12",
    ],
)
def test_mint_person_id_matches_multi_tenant(name):
    """security._mint_person_id is byte-identical to the person_id that
    multi_tenant._default_enroll actually mints (ADR-0080 D399)."""
    from orchestrator.multi_tenant import _default_enroll

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    led = _FakeLed()
    canonical = _default_enroll(led, {"name": name, "email": ""}, now)
    assert _mint_person_id(name) == canonical, (
        f"mint drift for {name!r}: security={_mint_person_id(name)} "
        f"multi_tenant={canonical}"
    )
    # And the minted id is the one stamped onto the enrolled event.
    assert led.events[0]["person_id"] == canonical


def test_mint_person_id_empty_fallback():
    assert _mint_person_id("") == "p_first_prospect"
    assert _mint_person_id("!!!") == "p_first_prospect"


# --- D397: encrypt / decrypt / crypto-shred ---------------------------------
def test_encrypt_decrypt_roundtrip_and_shred():
    ks = resolve_keystore(backend="passphrase_argon2id", passphrase="a strong test passphrase")
    pt = b"oauth-refresh-token"
    kid = "tenant:gmail.send"
    ct = encrypt_credential(pt, keystore=ks, key_id=kid)
    assert ct != pt and b"oauth-refresh" not in ct
    assert decrypt_credential(ct, keystore=ks, key_id=kid) == pt
    # A wrong key_id fails AAD authentication even before any shred.
    with pytest.raises(Exception):
        decrypt_credential(ct, keystore=ks, key_id="tenant:other")
    # Crypto-shred: destroy the key, ciphertext is unrecoverable.
    assert ks.destroy_key(kid) is True
    assert ks.destroy_key(kid) is False  # idempotent: already gone
    with pytest.raises(Exception):
        decrypt_credential(ct, keystore=ks, key_id=kid)


def test_passphrase_keystore_persists_across_instances(tmp_path):
    """At-rest persistence: a fresh keystore with the same passphrase +
    store_path recovers the wrapped DEK and decrypts (Argon2id master key)."""
    store = tmp_path / "keystore.json"
    pp = "persisted passphrase 9z!"
    ks1 = resolve_keystore(backend="passphrase_argon2id", passphrase=pp, store_path=store)
    pt = b"a-secret"
    kid = "tenant:cred"
    ct = encrypt_credential(pt, keystore=ks1, key_id=kid)
    assert store.exists()

    ks2 = resolve_keystore(backend="passphrase_argon2id", passphrase=pp, store_path=store)
    assert decrypt_credential(ct, keystore=ks2, key_id=kid) == pt


# --- D396 / D400: refuse-loud validation ------------------------------------
def test_resolve_keystore_rejects_unknown_backend():
    with pytest.raises(ValueError):
        resolve_keystore(backend="rot13")


def test_resolve_keystore_rejects_empty_passphrase():
    with pytest.raises(ValueError):
        resolve_keystore(backend="passphrase_argon2id", passphrase="")


def test_gdpr_forget_payload_refuses_cleartext_person_ref():
    with pytest.raises(ValueError):
        build_gdpr_forget_payload(
            person_ref="p_dana_reyes",  # cleartext, not a hash
            key_destroyed=True,
            n_events_shredded=0,
            suppression_appended=True,
            vault_purged=True,
            forgotten_at_ts="2026-06-01T00:00:00.000Z",
            audit={},
        )


def test_credentials_reencrypted_payload_validates_backend():
    with pytest.raises(ValueError):
        build_credentials_reencrypted_payload(
            tenant_id="t", key_id="k", backend="rot13",
            reencrypted_at_ts="2026-06-01T00:00:00.000Z",
        )
    payload = build_credentials_reencrypted_payload(
        tenant_id="t", key_id="k",
        backend=sorted(CREDENTIAL_KEYSTORE_BACKENDS)[0],
        reencrypted_at_ts="2026-06-01T00:00:00.000Z",
    )
    assert payload["type"] == "credentials_reencrypted"
    assert payload["_emitted_by"] == "security"
