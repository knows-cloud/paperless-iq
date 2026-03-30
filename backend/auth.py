"""Authentication middleware for Paperless IQ.

Validates session cookies and Bearer tokens. Protects all /api/* routes
except /api/auth/login.

Validates: Requirements 5.4
"""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, Request, status

# Token derived from SECRET_KEY for Bearer auth
# In production, this would be a proper JWT or session-based system
SECRET_KEY = os.getenv("SECRET_KEY", "")

# Valid session tokens (in production, stored in DB with expiry)
_VALID_SESSIONS: set[str] = set()


def _derive_api_token(secret: str) -> str:
    """Derive a deterministic API token from the secret key."""
    if not secret:
        return ""
    return hashlib.sha256(f"paperless-iq-api:{secret}".encode()).hexdigest()


def register_session(session_id: str) -> None:
    """Register a valid session ID (called on login)."""
    _VALID_SESSIONS.add(session_id)


def clear_session(session_id: str) -> None:
    """Remove a session ID (called on logout)."""
    _VALID_SESSIONS.discard(session_id)


async def require_auth(request: Request) -> None:
    """Check for a valid Authorization header or session cookie.

    Raises HTTP 401 if neither is present or valid.
    Allows /api/auth/login through without auth.

    Validates: Requirements 5.4
    """
    if request.url.path == "/api/auth/login":
        return

    # Check Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        expected = _derive_api_token(SECRET_KEY)
        if expected and hmac.compare_digest(token, expected):
            return

    # Check session cookie
    session_cookie = request.cookies.get("session", "")
    if session_cookie and session_cookie in _VALID_SESSIONS:
        return

    # For development: if SECRET_KEY is not set, allow any non-empty auth
    if not SECRET_KEY:
        if auth_header or session_cookie:
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
