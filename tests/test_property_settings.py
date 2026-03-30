"""Property-based tests for settings and authentication.

# Feature: paperless-iq, Property 13: Settings validation rejects invalid values
# Feature: paperless-iq, Property 14: Authentication enforcement

Validates: Requirements 5.3, 5.4
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.settings_service import SettingsService

# ---------------------------------------------------------------------------
# Strategies for invalid settings
# ---------------------------------------------------------------------------

_invalid_settings = st.one_of(
    # Negative retention days
    st.fixed_dictionaries({"audit_retention_days": st.integers(max_value=89)}),
    # Unknown provider
    st.fixed_dictionaries({"llm_provider": st.just("unknown_provider")}),
    # Invalid analysis mode
    st.fixed_dictionaries({"default_analysis_mode": st.just("invalid_mode")}),
    # Invalid vector store backend
    st.fixed_dictionaries({"vector_store_backend": st.just("nonexistent")}),
    # Negative poll interval
    st.fixed_dictionaries({"poll_interval_seconds": st.just(-1)}),
    # Negative batch size
    st.fixed_dictionaries({"batch_size": st.just(-5)}),
)


# ---------------------------------------------------------------------------
# Property 13: Settings validation rejects invalid values
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(invalid_values=_invalid_settings)
def test_property_13_settings_validation_rejects_invalid(
    invalid_values: dict[str, Any],
) -> None:
    """
    # Feature: paperless-iq, Property 13: Settings validation rejects invalid values

    Invalid setting values must be rejected with a descriptive error message
    and must not be persisted.

    Validates: Requirements 5.3
    """
    svc = SettingsService()
    original = svc.get_masked()

    with pytest.raises(ValueError, match="Invalid settings"):
        svc.update(invalid_values)

    # Config must be unchanged after failed validation
    after = svc.get_masked()
    assert after == original, "Config was modified despite validation failure"


# ---------------------------------------------------------------------------
# Property 14: Authentication enforcement
# ---------------------------------------------------------------------------

# Protected endpoints to test (method, path)
_PROTECTED_ENDPOINTS = [
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/queue"),
    ("GET", "/api/audit"),
    ("GET", "/api/search?q=test"),
    ("GET", "/api/documents"),
    ("GET", "/api/config/export"),
    ("POST", "/api/config/import"),
    ("POST", "/api/analyze"),
]


@pytest_asyncio.fixture
async def unauth_client():
    """Async HTTP test client WITHOUT any auth headers."""
    import os
    # Set a SECRET_KEY so auth is enforced
    os.environ["SECRET_KEY"] = "test-secret-key-for-auth"

    # Re-import to pick up the env var
    import importlib
    import backend.auth
    importlib.reload(backend.auth)

    from backend.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    # Clean up
    os.environ.pop("SECRET_KEY", None)
    importlib.reload(backend.auth)


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(
    endpoint_idx=st.integers(min_value=0, max_value=len(_PROTECTED_ENDPOINTS) - 1),
)
@pytest.mark.asyncio
async def test_property_14_authentication_enforcement(
    unauth_client: AsyncClient,
    endpoint_idx: int,
) -> None:
    """
    # Feature: paperless-iq, Property 14: Authentication enforcement

    Unauthenticated requests to protected endpoints must receive HTTP 401 or 403.

    Validates: Requirements 5.4
    """
    method, path = _PROTECTED_ENDPOINTS[endpoint_idx]

    if method == "GET":
        resp = await unauth_client.get(path)
    elif method == "PUT":
        resp = await unauth_client.put(path, json={})
    elif method == "POST":
        resp = await unauth_client.post(path, json={})
    else:
        pytest.fail(f"Unknown method: {method}")

    assert resp.status_code in (401, 403), (
        f"{method} {path} returned {resp.status_code}, expected 401 or 403"
    )

    # Must not expose protected data
    body = resp.json()
    assert "items" not in body or body.get("items") == [], (
        f"{method} {path} exposed protected data without auth"
    )
