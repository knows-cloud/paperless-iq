"""HTTP route tests for system, tracking, reindex, and piq-users endpoints."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check(app_client) -> None:
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /api/tracking/stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tracking_stats_shape(app_client) -> None:
    resp = await app_client.get("/api/tracking/stats")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("tracked_documents", "suggestions_pending", "suggestions_approved", "suggestions_rejected"):
        assert key in data, f"Missing key: {key}"
    assert data["tracked_documents"] >= 0


# ---------------------------------------------------------------------------
# POST /api/tracking/reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tracking_reset_returns_200(app_client) -> None:
    resp = await app_client.post("/api/tracking/reset")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_tracking_reset_rejected_returns_200(app_client) -> None:
    resp = await app_client.post("/api/tracking/reset-rejected")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/reindex — requires vector_store and paperless_client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reindex_without_vector_store_returns_503(app_client) -> None:
    """app_client has vector_store=None → trigger_reindex returns 503."""
    resp = await app_client.post("/api/reindex")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_vector_migrate_without_services_returns_503(app_client) -> None:
    resp = await app_client.post("/api/vector/migrate")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/piq-users/me — open auth (no PAPERLESS_URL)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_my_permissions_open_auth_returns_all_true(app_client) -> None:
    """In open-auth mode /api/piq-users/me returns a fully-permissive response."""
    resp = await app_client.get("/api/piq-users/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "anonymous"
    assert body["can_access"] is True
    assert body["can_approve"] is True
    assert body["can_settings"] is True


# ---------------------------------------------------------------------------
# GET /api/piq-users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_piq_users_returns_list(app_client) -> None:
    """GET /api/piq-users returns a list (empty when no users in DB)."""
    resp = await app_client.get("/api/piq-users")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# PUT + DELETE /api/piq-users/{username}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_piq_user_creates_record(app_client) -> None:
    body = {
        "can_access": True,
        "can_view_queue": True,
        "can_approve": False,
        "can_analyze": False,
        "can_discover": False,
        "can_settings": False,
    }
    resp = await app_client.put("/api/piq-users/testuser", json=body)
    assert resp.status_code == 200
    assert "testuser" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_delete_piq_user_not_found_returns_404(app_client) -> None:
    resp = await app_client.delete("/api/piq-users/nonexistent-user")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_piq_user_removes_record(app_client) -> None:
    # Create first
    await app_client.put("/api/piq-users/to-delete", json={
        "can_access": False, "can_view_queue": False,
        "can_approve": False, "can_analyze": False,
        "can_discover": False, "can_settings": False,
    })
    # Then delete
    resp = await app_client.delete("/api/piq-users/to-delete")
    assert resp.status_code == 200
    # Deleting again should 404
    resp2 = await app_client.delete("/api/piq-users/to-delete")
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_endpoint_returns_200(app_client) -> None:
    resp = await app_client.get("/api/status")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/audit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_log_empty(app_client) -> None:
    resp = await app_client.get("/api/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data or isinstance(data, list)
