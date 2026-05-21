"""Machine key generation and persistent storage.

On first startup a cryptographically-random 256-bit key is generated and
written to /data/.secret_key (chmod 600).  On subsequent startups the same
file is read so the key is stable across container restarts.

Falls back to the SECRET_KEY environment variable for backward-compatibility
with existing deployments that set it explicitly.

The key is used for:
  - Fernet encryption of credentials at rest
  - HMAC signing / verification of session tokens
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

_KEY_FILE = Path("/data/.secret_key")

# Module-level cache — populated on first call to get_machine_key()
_CACHE: str | None = None


def get_machine_key() -> str:
    """Return the stable machine key.

    Resolution order:
    1. In-process cache (fastest path after first call)
    2. SECRET_KEY env var (explicit override / backward compat)
    3. /data/.secret_key key file (created on first use)
    """
    global _CACHE
    if _CACHE:
        return _CACHE

    # Explicit env var takes precedence (backward compat for existing deployments)
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key and env_key not in ("change-me-in-production", ""):
        _CACHE = env_key
        logger.debug("Machine key loaded from SECRET_KEY env var.")
        return _CACHE

    # Try the persistent key file
    if _KEY_FILE.exists():
        try:
            stored = _KEY_FILE.read_text().strip()
            if stored:
                _CACHE = stored
                logger.debug("Machine key loaded from %s", _KEY_FILE)
                return _CACHE
        except Exception:
            logger.warning(
                "Could not read machine key from %s; will regenerate.",
                _KEY_FILE,
                exc_info=True,
            )

    # First run — generate a new key and save it
    _CACHE = _generate_and_save()
    return _CACHE


def _generate_and_save() -> str:
    """Generate a new random 256-bit key and persist it to /data/.secret_key."""
    import secrets

    key = secrets.token_hex(32)  # 32 bytes = 256 bits, hex-encoded (64 chars)
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(key)
        # chmod 600 — readable/writable only by the process owner
        _KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
        logger.info(
            "Generated new machine key and saved to %s (chmod 600). "
            "Back up this file if you want to keep credentials readable after a rebuild.",
            _KEY_FILE,
        )
    except Exception:
        logger.warning(
            "Could not persist machine key to %s — "
            "credentials will be lost on restart.  "
            "Ensure /data is a persistent Docker volume.",
            _KEY_FILE,
            exc_info=True,
        )
    return key
