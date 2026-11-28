"""AES-256-GCM field encryption tests (Phase 2).

Covers round-trip, nonce uniqueness, tamper detection, AAD binding and key
validation. The Postgres ciphertext assertion is added once the DB fixture is
wired in (see the `test_encrypted_identifier_not_stored_in_plaintext` test at
the bottom, which uses the project's own DB abstraction).
"""
from __future__ import annotations

import base64
import os

import pytest

from security.encryption import (
    CIPHERTEXT_PREFIX,
    DecryptionTamperError,
    EncryptionConfigurationError,
    decrypt,
    decrypt_identifier,
    encrypt,
    encrypt_identifier,
    generate_key,
    is_encrypted,
)


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    """Provide a fresh, random 256-bit key for every test (never hardcoded)."""
    key = generate_key()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    return key


def test_generate_key_returns_32_base64_bytes():
    key = generate_key()
    assert len(base64.b64decode(key, validate=True)) == 32


def test_round_trip_returns_original_identifier():
    plaintext = "ACCT-123456789"
    token = encrypt_identifier(plaintext)
    assert token.startswith(CIPHERTEXT_PREFIX)
    assert is_encrypted(token)
    assert decrypt_identifier(token) == plaintext


def test_unique_nonces_produce_different_ciphertexts():
    plaintext = "CUST-0001"
    tokens = {encrypt(plaintext) for _ in range(25)}
    assert len(tokens) == 25, "AES-GCM nonces must never be reused"
    assert {decrypt(token) for token in tokens} == {plaintext}


def test_tampered_ciphertext_raises_tamper_error():
    token = encrypt("ACCT-999")
    prefix_len = len(CIPHERTEXT_PREFIX)
    blob = bytearray(base64.b64decode(token[prefix_len:], validate=True))
    blob[-1] ^= 0x01  # flip one authentication-tag bit
    tampered = CIPHERTEXT_PREFIX + base64.b64encode(bytes(blob)).decode("ascii")

    with pytest.raises(DecryptionTamperError):
        decrypt(tampered)


def test_truncated_ciphertext_raises_tamper_error():
    token = encrypt("ACCT-999")
    with pytest.raises(DecryptionTamperError):
        decrypt(token[:-8])


def test_malformed_token_raises_tamper_error():
    with pytest.raises(DecryptionTamperError):
        decrypt("not-an-encrypted-value")


def test_associated_data_is_bound_to_ciphertext():
    token = encrypt("ACCT-42", aad="cases.acct_no")
    assert decrypt(token, aad="cases.acct_no") == "ACCT-42"
    with pytest.raises(DecryptionTamperError):
        decrypt(token, aad="cases.other_column")


def test_wrong_key_raises_tamper_error(monkeypatch):
    token = encrypt("ACCT-77")
    monkeypatch.setenv("ENCRYPTION_KEY", generate_key())
    with pytest.raises(DecryptionTamperError):
        decrypt(token)


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(EncryptionConfigurationError):
        encrypt("ACCT-1")


def test_invalid_key_length_rejected(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", base64.b64encode(os.urandom(16)).decode("ascii"))
    with pytest.raises(EncryptionConfigurationError):
        encrypt("ACCT-1")


def test_encrypted_identifier_not_stored_in_plaintext():
    """The persistence boundary must store ciphertext, never the raw ID."""
    from omniguard.db import connect, fetchone, init_db
    from security.case_store import AAD_ACCOUNT, AAD_CUSTOMER, create_case

    init_db()
    account = "ACCT-PLAINTEXT-987654321"
    customer = "CUST-PLAINTEXT-123456789"
    meta = create_case(
        alert_id="alert-crypto-db-test",
        account_id=account,
        customer_id=customer,
        assigned_analyst="alice",
    )

    con = connect()
    try:
        row = fetchone(con.cursor(), "SELECT * FROM cases WHERE case_id=?", (meta["case_id"],))
    finally:
        con.close()

    assert row is not None
    assert row["account_id_enc"].startswith(CIPHERTEXT_PREFIX)
    assert row["customer_id_enc"].startswith(CIPHERTEXT_PREFIX)
    assert account not in str(row), "plaintext account ID leaked into the database row"
    assert customer not in str(row), "plaintext customer ID leaked into the database row"
    assert decrypt(row["account_id_enc"], aad=AAD_ACCOUNT) == account
    assert decrypt(row["customer_id_enc"], aad=AAD_CUSTOMER) == customer
