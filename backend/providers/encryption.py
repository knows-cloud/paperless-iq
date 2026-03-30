"""Fernet-based credential encryption utilities."""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Fixed salt — changing this would invalidate all stored credentials
_SALT = b"paperless-iq-salt"


def derive_fernet_key(secret_key: str) -> bytes:
    """Derive a 32-byte Fernet-compatible key from SECRET_KEY using PBKDF2HMAC."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=100_000,
    )
    raw = kdf.derive(secret_key.encode())
    return base64.urlsafe_b64encode(raw)


def encrypt_credential(plaintext: str, secret_key: str) -> str:
    """Encrypt a plaintext credential string; returns a Fernet token as str."""
    key = derive_fernet_key(secret_key)
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_credential(token: str, secret_key: str) -> str:
    """Decrypt a Fernet token back to plaintext."""
    key = derive_fernet_key(secret_key)
    f = Fernet(key)
    return f.decrypt(token.encode()).decode()
