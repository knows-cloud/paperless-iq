"""Authentication and access-control helpers for Paperless IQ.

Session tokens are HMAC-SHA256 signed and self-contained — they survive
restarts because validity is verified by recomputing the signature, not by
looking up server-side state.

Auth flow:
  POST /api/auth/login  → rate-limit check
                          → validate creds against Paperless NGX /api/token/
                          → check NG admin status via user's token
                          → upsert user_permissions row
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

# Login rate limiter: max 10 attempts per IP within a 5-minute window.
_LOGIN_WINDOW = 300  # seconds
_LOGIN_MAX = 10
_LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}  # ip → (count, window_start)


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
# Login rate limiting
# ---------------------------------------------------------------------------

def check_login_rate_limit(ip: str) -> bool:
    """Return True if *ip* is allowed to attempt login.

    Allows up to _LOGIN_MAX attempts per _LOGIN_WINDOW seconds per IP.
    Old entries are lazily evicted when the window expires.
    """
    now = time.time()
    count, window_start = _LOGIN_ATTEMPTS.get(ip, (0, now))
    if now - window_start > _LOGIN_WINDOW:
        # Window expired — reset
        _LOGIN_ATTEMPTS[ip] = (1, now)
        return True
    if count >= _LOGIN_MAX:
        return False
    _LOGIN_ATTEMPTS[ip] = (count + 1, window_start)
    return True


# ---------------------------------------------------------------------------
# Webhook secret
# ---------------------------------------------------------------------------

def check_webhook_secret(request: Request, expected: str) -> bool:
    """Return True if the request carries the correct webhook secret.

    Checks the ``?key=`` query parameter (used when the secret is auto-embedded
    in the callback URL).  Falls back to the ``X-Webhook-Secret`` header for
    backward compatibility with deployments that set WEBHOOK_SECRET manually.
    When *expected* is empty, all requests are accepted.
    """
    if not expected:
        return True
    provided = request.query_params.get("key") or request.headers.get("X-Webhook-Secret", "")
    return hmac.compare_digest(expected, provided)


# ---------------------------------------------------------------------------
# Paperless NGX credential validation + admin check
# ---------------------------------------------------------------------------

async def check_ng_admin_status(paperless_url: str, user_token: str, username: str) -> bool:
    """Return True if *username* is a Paperless NGX superuser or staff member.

    Uses the user's own token to call GET /api/users/ — this endpoint returns
    403 for non-admin accounts, so a 200 response with matching user data
    confirms admin status without requiring the service token.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{paperless_url.rstrip('/')}/api/users/",
                params={"username": username},
                headers={"Authorization": f"Token {user_token}"},
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            for u in data.get("results", []):
                if u.get("username") == username:
                    return bool(u.get("is_staff") or u.get("is_superuser"))
            return False
    except Exception:
        logger.warning("Could not check NG admin status for %s", username, exc_info=True)
        return False


async def validate_paperless_credentials(
    username: str, password: str
) -> tuple[bool, str, bool]:
    """Validate credentials against Paperless NGX.

    Returns ``(valid, paperless_token, is_ng_admin)``.
    ``paperless_token`` is the short-lived token issued by Paperless — it is
    used only for the admin check and is never stored.
    """
    paperless_url = os.environ.get("PAPERLESS_URL", "").rstrip("/")
    if not paperless_url:
        return False, "", False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{paperless_url}/api/token/",
                json={"username": username, "password": password},
            )
            if resp.status_code != 200:
                return False, "", False
            ng_token = resp.json().get("token", "")
            is_admin = await check_ng_admin_status(paperless_url, ng_token, username)
            return True, ng_token, is_admin
    except Exception:
        logger.warning(
            "Could not reach Paperless NGX at %s to validate credentials.",
            paperless_url,
            exc_info=True,
        )
        return False, "", False


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
    _PUBLIC_PATHS = {"/api/status", "/api/theme", "/health"}
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
