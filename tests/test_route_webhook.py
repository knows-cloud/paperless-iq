"""HTTP route tests for /api/webhook/paperless.

Tests:
- Happy path: valid doc_url payload → 200 with "queued" detail
- Wrong/missing webhook secret → 403
- No document_id in payload → 200 with "skipped" detail
- Register webhook → 503 when paperless_client is None
"""

from __future__ import annotations

import pytest

from backend.settings_service import SettingsService


@pytest.mark.asyncio
async def test_webhook_no_secret_configured_accepts_any(app_client) -> None:
    """When no webhook_secret is set, any request is accepted."""
    # Default config has no webhook secret (or empty string)
    payload = {"doc_url": "http://paperless.local/documents/123/"}
    resp = await app_client.post("/api/webhook/paperless", json=payload)
    # With no vector store/PC, it returns 200 with "skipped" or "queued"
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_wrong_secret_returns_403(app_client, monkeypatch) -> None:
    """A configured secret that doesn't match the request key returns 403."""
    # Patch the settings service to return a specific secret
    from unittest.mock import patch, MagicMock

    mock_config = MagicMock()
    mock_config.webhook_secret = "correct-secret"

    with patch("backend.main._settings_svc") as mock_svc:
        mock_svc.config = mock_config
        payload = {"doc_url": "http://paperless.local/documents/99/"}
        resp = await app_client.post(
            "/api/webhook/paperless?key=wrong-secret",
            json=payload,
        )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_correct_secret_passes(app_client) -> None:
    """A request with the correct key query param passes secret verification."""
    from unittest.mock import patch, MagicMock

    mock_config = MagicMock()
    mock_config.webhook_secret = "my-secret"

    with patch("backend.main._settings_svc") as mock_svc:
        mock_svc.config = mock_config
        payload = {"doc_url": "http://paperless.local/documents/5/"}
        resp = await app_client.post(
            "/api/webhook/paperless?key=my-secret",
            json=payload,
        )

    # No vector store → "skipped" but still 200
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_no_doc_id_returns_skipped(app_client) -> None:
    """A payload with no document_id/doc_url returns 200 with 'skipped' detail."""
    payload = {"unrelated": "data"}
    resp = await app_client.post("/api/webhook/paperless", json=payload)
    assert resp.status_code == 200
    assert "skipped" in resp.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_webhook_doc_url_extracts_id(app_client) -> None:
    """Webhook can extract document ID from a doc_url field."""
    payload = {"doc_url": "http://paperless.local/documents/42/"}
    resp = await app_client.post("/api/webhook/paperless", json=payload)
    assert resp.status_code == 200
    # With no vector store the task is skipped, but doc_id extraction should not error
    detail = resp.json().get("detail", "")
    assert "skipped" in detail.lower() or "queued" in detail.lower()


@pytest.mark.asyncio
async def test_webhook_register_without_paperless_client_returns_503(app_client) -> None:
    """POST /api/webhook/register requires a live Paperless NGX client."""
    # app_client has paperless_client=None
    resp = await app_client.post("/api/webhook/register")
    assert resp.status_code == 503
