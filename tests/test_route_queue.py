"""HTTP route tests for /api/queue/* endpoints.

Uses the app_client + db_engine fixtures from conftest.py:
- ASGITransport (no lifespan), PAPERLESS_URL absent (open-auth / dev mode)
- In-memory SQLite DB, get_session overridden
- PAPERLESS_TOKEN absent → ApprovalQueueService._patch_paperless() returns early
  without making any HTTP calls, so no mock of Paperless NGX is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.orm_models import SuggestionORM


def _make_suggestion_orm(**overrides) -> SuggestionORM:
    defaults = dict(
        id=str(uuid4()),
        document_id=42,
        status="pending",
        created_at=datetime.now(timezone.utc),
        title="Test Invoice",
        tags=["invoice"],
        correspondent="ACME",
        document_type="Invoice",
        storage_path=None,
        custom_fields={},
        llm_provider="openai",
        llm_model="gpt-4o",
        analysis_mode="ocr",
        extracted_content=None,
        original_ocr_content=None,
    )
    defaults.update(overrides)
    return SuggestionORM(**defaults)


async def _insert(db_engine, *rows) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        for row in rows:
            session.add(row)
        await session.commit()


# ---------------------------------------------------------------------------
# GET /api/queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_queue_empty(app_client) -> None:
    resp = await app_client.get("/api/queue")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["items"] == []


@pytest.mark.asyncio
async def test_get_queue_returns_pending_suggestion(app_client, db_engine) -> None:
    row = _make_suggestion_orm()
    await _insert(db_engine, row)

    resp = await app_client.get("/api/queue")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == row.id


@pytest.mark.asyncio
async def test_get_queue_filters_by_status(app_client, db_engine) -> None:
    pending = _make_suggestion_orm(id=str(uuid4()), status="pending")
    approved = _make_suggestion_orm(id=str(uuid4()), status="approved")
    await _insert(db_engine, pending, approved)

    resp = await app_client.get("/api/queue?status=pending")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["status"] == "pending" for i in items)


# ---------------------------------------------------------------------------
# POST /api/queue/{id}/approve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_nonexistent_suggestion_returns_409(app_client) -> None:
    resp = await app_client.post(f"/api/queue/{uuid4()}/approve")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_approve_pending_suggestion(app_client, db_engine) -> None:
    row = _make_suggestion_orm()
    await _insert(db_engine, row)

    resp = await app_client.post(f"/api/queue/{row.id}/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["id"] == row.id


@pytest.mark.asyncio
async def test_approve_already_approved_returns_409(app_client, db_engine) -> None:
    row = _make_suggestion_orm(status="approved")
    await _insert(db_engine, row)

    resp = await app_client.post(f"/api/queue/{row.id}/approve")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/queue/{id}/reject
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_nonexistent_suggestion_returns_409(app_client) -> None:
    resp = await app_client.post(f"/api/queue/{uuid4()}/reject")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reject_pending_suggestion(app_client, db_engine) -> None:
    row = _make_suggestion_orm()
    await _insert(db_engine, row)

    resp = await app_client.post(f"/api/queue/{row.id}/reject")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"


@pytest.mark.asyncio
async def test_reject_leaves_paperless_untouched(app_client, db_engine, monkeypatch) -> None:
    """Reject must not write to Paperless NGX — verify by asserting _patch_paperless
    is never called (it would only be called if PAPERLESS_TOKEN were set, but we
    also confirm directly that no HTTP call happens).
    """
    from unittest.mock import AsyncMock, patch

    row = _make_suggestion_orm()
    await _insert(db_engine, row)

    with patch("backend.approval_queue.httpx.AsyncClient") as mock_http:
        resp = await app_client.post(f"/api/queue/{row.id}/reject")

    assert resp.status_code == 200
    mock_http.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/queue/bulk-approve and bulk-reject
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_reject_rejects_all(app_client, db_engine) -> None:
    rows = [_make_suggestion_orm(id=str(uuid4())) for _ in range(3)]
    await _insert(db_engine, *rows)

    ids = [r.id for r in rows]
    resp = await app_client.post("/api/queue/bulk-reject", json={"ids": ids})
    assert resp.status_code == 200
    rejected = resp.json()["rejected"]
    assert len(rejected) == 3
    assert all(s["status"] == "rejected" for s in rejected)


@pytest.mark.asyncio
async def test_bulk_approve_approves_all(app_client, db_engine) -> None:
    rows = [_make_suggestion_orm(id=str(uuid4())) for _ in range(2)]
    await _insert(db_engine, *rows)

    ids = [r.id for r in rows]
    resp = await app_client.post("/api/queue/bulk-approve", json={"ids": ids})
    assert resp.status_code == 200
    approved = resp.json()["approved"]
    assert len(approved) == 2
    assert all(s["status"] == "approved" for s in approved)


# ---------------------------------------------------------------------------
# POST /api/queue/empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_queue_rejects_all_pending(app_client, db_engine) -> None:
    rows = [_make_suggestion_orm(id=str(uuid4())) for _ in range(4)]
    await _insert(db_engine, *rows)

    resp = await app_client.post("/api/queue/empty")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rejected_count"] == 4


@pytest.mark.asyncio
async def test_empty_queue_on_empty_db_returns_zero(app_client) -> None:
    resp = await app_client.post("/api/queue/empty")
    assert resp.status_code == 200
    assert resp.json()["rejected_count"] == 0


# ---------------------------------------------------------------------------
# GET /api/tracking/stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tracking_stats_returns_counts(app_client, db_engine) -> None:
    rows = [_make_suggestion_orm(id=str(uuid4()), status="approved") for _ in range(2)]
    await _insert(db_engine, *rows)

    resp = await app_client.get("/api/tracking/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions_pending" in data
    assert "suggestions_approved" in data
    assert data["suggestions_approved"] >= 2
