"""Fernet-based credential encryption utilities.

Two on-disk formats are supported:
  enc1 (legacy) — fixed salt ``b"paperless-iq-salt"``.  Still readable for
                   backward compatibility; no longer written.
  enc2 (current) — 32-byte random salt prepended as URL-safe base64, separated
                   from the Fernet token by ``:``.  Format stored by
                   settings_service as ``enc2:<salt_b64>:<fernet_token>``.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ITERATIONS = 100_000

# enc1 legacy salt — never change; used only for decryption of old blobs
_LEGACY_SALT = b"paperless-iq-salt"


def _derive_key(secret_key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))


# ---------------------------------------------------------------------------
# enc1 — legacy fixed-salt (decrypt only)
# ---------------------------------------------------------------------------

def encrypt_credential(plaintext: str, secret_key: str) -> str:
    """Encrypt using the legacy enc1 fixed-salt scheme.

    Kept for callers that build transient in-memory providers (e.g. the Bedrock
    embed-only path in main.py). Settings persistence uses ``encrypt_credential_v2``.
    """
    key = _derive_key(secret_key, _LEGACY_SALT)
    return Fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_credential(token: str, secret_key: str) -> str:
    """Decrypt an enc1 (fixed-salt) Fernet token."""
    key = _derive_key(secret_key, _LEGACY_SALT)
    return Fernet(key).decrypt(token.encode()).decode()


# ---------------------------------------------------------------------------
# enc2 — random-salt (current scheme)
# ---------------------------------------------------------------------------

def encrypt_credential_v2(plaintext: str, secret_key: str) -> str:
    """Encrypt with a random per-credential salt.

    Returns ``<salt_b64>:<fernet_token>`` (no prefix — the ``enc2:`` prefix is
    added by the caller in settings_service).
    """
    salt = os.urandom(32)
    key = _derive_key(secret_key, salt)
    token = Fernet(key).encrypt(plaintext.encode()).decode()
    return base64.urlsafe_b64encode(salt).decode() + ":" + token


def decrypt_credential_v2(token_str: str, secret_key: str) -> str:
    """Decrypt an enc2 ``<salt_b64>:<fernet_token>`` string."""
    salt_b64, _, fernet_token = token_str.partition(":")
    # urlsafe_b64decode tolerates missing padding
    salt = base64.urlsafe_b64decode(salt_b64 + "==")
    key = _derive_key(secret_key, salt)
    return Fernet(key).decrypt(fernet_token.encode()).decode()
