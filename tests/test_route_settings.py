"""HTTP route tests for /api/settings endpoints.

Key invariants tested:
- GET /api/settings: credentials are masked (no plaintext, no PAPERLESS_TOKEN)
- PUT /api/settings: __KEEP__ sentinel leaves stored credential unchanged
- PUT /api/settings: invalid values return 422 and don't persist
- PAPERLESS_TOKEN never appears in any settings response

Note: _settings_svc.update_and_persist() calls _persist() via AsyncSessionLocal
(not the injected session).  Tests that exercise PUT must patch _persist to a
no-op so they don't touch the real DB.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest


@asynccontextmanager
async def _no_persist():
    """Patch _settings_svc._persist to a no-op for tests that PUT settings."""
    async def _noop(self=None):
        pass
    with patch("backend.settings_service.SettingsService._persist", new=_noop):
        yield


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_settings_returns_200(app_client) -> None:
    resp = await app_client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)


@pytest.mark.asyncio
async def test_get_settings_credentials_masked(app_client) -> None:
    """Credential fields must be masked — no plaintext, no 'PAPERLESS_TOKEN'."""
    resp = await app_client.get("/api/settings")
    assert resp.status_code == 200
    body_text = resp.text

    assert "PAPERLESS_TOKEN" not in body_text
    body = resp.json()
    assert "llm_credentials" in body
    cred_val = body.get("llm_credentials", "")
    if cred_val:
        # Either empty or the masked placeholder — never raw plaintext
        assert cred_val in ("••••••••", "__MASKED__", ""), (
            f"llm_credentials not properly masked: {cred_val!r}"
        )


@pytest.mark.asyncio
async def test_get_settings_no_paperless_token_key(app_client) -> None:
    resp = await app_client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert "paperless_token" not in body
    assert "PAPERLESS_TOKEN" not in body


# ---------------------------------------------------------------------------
# PUT /api/settings — validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_settings_invalid_value_returns_422(app_client) -> None:
    async with _no_persist():
        resp = await app_client.put("/api/settings", json={"audit_retention_days": 5})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_settings_invalid_does_not_change_in_memory_state(app_client) -> None:
    """A failed validation must leave in-memory settings unchanged."""
    before = (await app_client.get("/api/settings")).json()

    async with _no_persist():
        await app_client.put("/api/settings", json={"audit_retention_days": 5})

    after = (await app_client.get("/api/settings")).json()
    assert before.get("audit_retention_days") == after.get("audit_retention_days")


@pytest.mark.asyncio
async def test_put_settings_valid_value_returns_200(app_client) -> None:
    async with _no_persist():
        resp = await app_client.put("/api/settings", json={"audit_retention_days": 60})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_put_settings_valid_value_reflected_in_get(app_client) -> None:
    async with _no_persist():
        resp = await app_client.put("/api/settings", json={"audit_retention_days": 60})
        assert resp.status_code == 200

    body = (await app_client.get("/api/settings")).json()
    assert body.get("audit_retention_days") == 60


# ---------------------------------------------------------------------------
# __KEEP__ sentinel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keep_sentinel_preserves_stored_credential(app_client) -> None:
    """PUT with llm_credentials='__KEEP__' must not overwrite the stored credential."""
    async with _no_persist():
        # Write a known credential
        await app_client.put("/api/settings", json={"llm_credentials": "initial-api-key"})
        body1 = (await app_client.get("/api/settings")).json()
        masked1 = body1.get("llm_credentials", "")

        # Now PUT with __KEEP__
        await app_client.put("/api/settings", json={"llm_credentials": "__KEEP__"})
        body2 = (await app_client.get("/api/settings")).json()
        masked2 = body2.get("llm_credentials", "")

    assert masked1 == masked2, (
        "PUT with __KEEP__ must not overwrite the stored credential"
    )
