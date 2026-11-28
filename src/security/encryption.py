"""AES-256-GCM field-level encryption for regulated identifiers.

Regulated identifiers (account numbers, customer IDs) are encrypted at the
persistence boundary with AES-GCM (256-bit key). A fresh 96-bit nonce is
generated for every value via ``os.urandom``; the nonce is prepended to the
ciphertext+tag blob and base64-encoded with a self-describing version prefix.

Security properties
-------------------
* **Confidentiality + integrity** — AES-GCM authenticates both the ciphertext
  and optional associated data (e.g. a case ID or column name). Any bit flip,
  wrong key, wrong nonce or wrong AAD raises :class:`DecryptionTamperError`.
* **No equality leakage** — randomized nonces mean encrypting the same
  identifier twice yields different ciphertext. Regulated identifiers are
  therefore *not* used as SQL filter keys.
* **No hardcoded secrets** — ``ENCRYPTION_KEY`` must contain a base64-encoded
  32-byte key. It is loaded lazily so importing this module never fails in
  local development or in the existing test suite; only actual
  encryption/decryption requires the key.

Generate a key with::

    python -c "from security.encryption import generate_key; print(generate_key())"
"""
from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

__all__ = [
    "CIPHERTEXT_PREFIX",
    "DecryptionTamperError",
    "EncryptionConfigurationError",
    "decrypt",
    "decrypt_identifier",
    "encrypt",
    "encrypt_identifier",
    "generate_key",
    "is_encrypted",
]

CIPHERTEXT_PREFIX = "enc:v1:"
_NONCE_BYTES = 12
_KEY_BYTES = 32


class DecryptionTamperError(Exception):
    """Raised when a ciphertext fails GCM authentication or is malformed."""


class EncryptionConfigurationError(RuntimeError):
    """Raised when ``ENCRYPTION_KEY`` is missing or invalid."""


def generate_key() -> str:
    """Return a freshly generated base64-encoded 256-bit key.

    Intended for key provisioning only. Never commit the returned value.
    """
    return base64.b64encode(os.urandom(_KEY_BYTES)).decode("ascii")


def _load_key(explicit_key: Optional[str] = None) -> bytes:
    """Resolve the AES key from an explicit override or ``ENCRYPTION_KEY``."""
    raw = explicit_key if explicit_key is not None else os.getenv("ENCRYPTION_KEY")
    if not raw:
        raise EncryptionConfigurationError(
            "ENCRYPTION_KEY is not set. Generate a 256-bit key with "
            "'python -c \"from security.encryption import generate_key; "
            "print(generate_key())\"' and add it to the environment."
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EncryptionConfigurationError("ENCRYPTION_KEY must be valid base64.") from exc
    if len(key) != _KEY_BYTES:
        raise EncryptionConfigurationError(
            f"ENCRYPTION_KEY must decode to exactly {_KEY_BYTES} bytes "
            f"(got {len(key)})."
        )
    return key


def _aad_bytes(aad: Optional[Any]) -> Optional[bytes]:
    if aad is None:
        return None
    if isinstance(aad, bytes):
        return aad
    return str(aad).encode("utf-8")


def encrypt(
    plaintext: str,
    *,
    aad: Optional[Any] = None,
    key: Optional[str] = None,
) -> str:
    """Encrypt *plaintext* with AES-256-GCM.

    Args:
        plaintext: Regulated value to protect (e.g. an account number).
        aad: Optional associated data bound to the ciphertext (column name,
             case ID, ...). Must be supplied again on decryption.
        key: Optional explicit base64 key override (used by tests).

    Returns:
        A string of the form ``enc:v1:<base64(nonce || ciphertext || tag)>``.
    """
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be str")
    aesgcm = AESGCM(_load_key(key))
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), _aad_bytes(aad))
    return CIPHERTEXT_PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt(
    token: str,
    *,
    aad: Optional[Any] = None,
    key: Optional[str] = None,
) -> str:
    """Decrypt and authenticate a value produced by :func:`encrypt`.

    Raises:
        DecryptionTamperError: On a malformed blob or any GCM authentication
            failure (tampering, wrong key, wrong nonce or wrong AAD).
    """
    if not isinstance(token, str) or not token.startswith(CIPHERTEXT_PREFIX):
        raise DecryptionTamperError("Malformed encrypted value.")
    try:
        blob = base64.b64decode(token[len(CIPHERTEXT_PREFIX) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DecryptionTamperError("Malformed encrypted value.") from exc
    if len(blob) <= _NONCE_BYTES:
        raise DecryptionTamperError("Malformed encrypted value.")

    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    aesgcm = AESGCM(_load_key(key))
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, _aad_bytes(aad))
    except InvalidTag as exc:
        raise DecryptionTamperError(
            "Ciphertext failed authentication (tamper detected)."
        ) from exc
    return plaintext.decode("utf-8")


# Explicit aliases make the regulated-identifier intent clear at call sites.
encrypt_identifier = encrypt
decrypt_identifier = decrypt


def is_encrypted(value: Any) -> bool:
    """Return True when *value* looks like a versioned ciphertext blob."""
    return isinstance(value, str) and value.startswith(CIPHERTEXT_PREFIX)
