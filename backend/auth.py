"""Authentication for Paperless IQ.

Session tokens are HMAC-SHA256 signed and self-contained — they survive
restarts because validity is verified by recomputing the signature, not by
looking up server-side state.

Auth flow:
  POST /api/auth/login  → validate creds against Paperless NGX /api/token/
                          → issue a signed 7-day session token
  GET  /api/auth/me     → return {user, auth_required}
  POST /api/auth/logout → revoke the current token (in-memory; clears on restart)

Bypass mode: when PAPERLESS_URL is not set all /api/* routes are open.
This is intentional for local-dev / first-run scenarios.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Optional

import httpx
from fastapi import HTTPException, Request, status

from backend.keystore import get_machine_key

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# In-memory revocation set (JTIs only).  Cleared on restart — acceptable
# because tokens expire after 7 days anyway.
_REVOKED: set[str] = set()


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _sign(message: str) -> str:
    """Return a hex HMAC-SHA256 of message using the machine key."""
    key = get_machine_key().encode()
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def create_session(username: str) -> str:
    """Create a signed session token for *username*.

    Token format (dot-separated, URL-safe):
        <jti>.<username_b64>.<exp>.<sig>

    sig = HMAC-SHA256(machine_key, "<jti>:<username>:<exp>")
    """
    jti = secrets.token_hex(16)
    exp = str(int(time.time()) + TOKEN_TTL_SECONDS)
    u_b64 = base64.urlsafe_b64encode(username.encode()).decode().rstrip("=")
    sig = _sign(f"{jti}:{username}:{exp}")
    return f"{jti}.{u_b64}.{exp}.{sig}"


def get_session_user(token: str) -> Optional[str]:
    """Validate *token* and return the username, or None if invalid/expired."""
    try:
        parts = token.split(".")
        if len(parts) != 4:
            return None
        jti, u_b64, exp, sig = parts

        # Revocation check
        if jti in _REVOKED:
            return None

        # Expiry check
        if int(exp) < int(time.time()):
            return None

        # Decode username (pad base64 back to multiple of 4)
        padding = "=" * (4 - len(u_b64) % 4) if len(u_b64) % 4 else ""
        username = base64.urlsafe_b64decode((u_b64 + padding).encode()).decode()

        # Signature verification
        expected = _sign(f"{jti}:{username}:{exp}")
        if not hmac.compare_digest(sig, expected):
            return None

        return username
    except Exception:
        return None


def revoke_session(token: str) -> None:
    """Add token's JTI to the revocation set (logout)."""
    try:
        jti = token.split(".")[0]
        if jti:
            _REVOKED.add(jti)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Paperless NGX credential validation
# ---------------------------------------------------------------------------

async def validate_paperless_credentials(username: str, password: str) -> bool:
    """Return True if (username, password) are valid Paperless NGX credentials.

    Calls POST {PAPERLESS_URL}/api/token/ — the standard DRF token endpoint.
    Returns False if PAPERLESS_URL is not configured.
    """
    paperless_url = os.environ.get("PAPERLESS_URL", "").rstrip("/")
    if not paperless_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{paperless_url}/api/token/",
                json={"username": username, "password": password},
            )
            return resp.status_code == 200
    except Exception:
        logger.warning(
            "Could not reach Paperless NGX at %s to validate credentials.",
            paperless_url,
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def _is_auth_required() -> bool:
    """Return True when PAPERLESS_URL is configured (auth is enforced)."""
    return bool(os.environ.get("PAPERLESS_URL", "").strip())


async def require_auth(request: Request) -> None:
    """Enforce authentication on all /api/* routes.

    Passes through:
      - /api/auth/* (login, logout, me)
      - Everything when PAPERLESS_URL is not set (open / dev mode)

    For protected routes: expects ``Authorization: Bearer <token>`` header.
    Sets ``request.state.user`` to the authenticated username on success.
    """
    path = request.url.path

    # Auth routes are always public (they issue/revoke tokens)
    if path.startswith("/api/auth/"):
        return

    # These endpoints are safe to expose without auth — they contain no
    # sensitive data and are needed for health monitoring / login-page styling.
    _PUBLIC_PATHS = {"/api/status", "/api/theme", "/api/logos", "/health"}
    if path in _PUBLIC_PATHS:
        return

    # Open when Paperless NGX is not configured
    if not _is_auth_required():
        return

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        user = get_session_user(token)
        if user:
            request.state.user = user
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
