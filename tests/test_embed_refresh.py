"""Deferred re-embedding tests (GROOMING_PLAN §12, Step 0).

Covers schedule_reembed mode behaviour, dirty-stamp collapsing, the flush
path, and the manual-refresh 409 while a flush runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.orm_models import DocumentTrackingORM


class SpyVectorStore:
    def __init__(self) -> None:
        self.upserts: list[tuple[int, str, dict]] = []

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        self.upserts.append((doc_id, text, metadata))


def _tracking_row(doc_id: int = 7) -> DocumentTrackingORM:
    return DocumentTrackingORM(
        document_id=doc_id,
        first_seen_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_schedule_reembed_immediate_upserts_right_away(monkeypatch) -> None:
    import backend.main as m

    monkeypatch.setattr(m._settings_svc.config, "embed_refresh_mode", "immediate")
    vs = SpyVectorStore()
    await m.schedule_reembed(7, "content", {"title": "T"}, vs)
    assert vs.upserts == [(7, "content", {"title": "T"})]


@pytest.mark.asyncio
async def test_schedule_reembed_deferred_stamps_marker_only(db_engine, monkeypatch) -> None:
    import backend.main as m

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(m, "AsyncSessionLocal", factory)
    monkeypatch.setattr(m._settings_svc.config, "embed_refresh_mode", "daily")

    async with factory() as session:
        session.add(_tracking_row(7))
        await session.commit()

    vs = SpyVectorStore()
    await m.schedule_reembed(7, "content", {"title": "T"}, vs)

    assert vs.upserts == []  # deferred — no embed call
    async with factory() as session:
        row = await session.get(DocumentTrackingORM, 7)
        assert row.reembed_dirty_since is not None


@pytest.mark.asyncio
async def test_schedule_reembed_repeated_stamps_collapse(db_engine, monkeypatch) -> None:
    """Two metadata changes before the flush produce ONE dirty marker —
    the original timestamp is preserved (one flush, not two)."""
    import backend.main as m

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(m, "AsyncSessionLocal", factory)
    monkeypatch.setattr(m._settings_svc.config, "embed_refresh_mode", "manual")

    async with factory() as session:
        session.add(_tracking_row(7))
        await session.commit()

    vs = SpyVectorStore()
    await m.schedule_reembed(7, "v1", {}, vs)
    async with factory() as session:
        first_stamp = (await session.get(DocumentTrackingORM, 7)).reembed_dirty_since

    await m.schedule_reembed(7, "v2", {}, vs)
    async with factory() as session:
        second_stamp = (await session.get(DocumentTrackingORM, 7)).reembed_dirty_since

    assert vs.upserts == []
    assert first_stamp == second_stamp


@pytest.mark.asyncio
async def test_flush_dirty_reembeds_upserts_and_clears_marker(db_engine, monkeypatch) -> None:
    import httpx

    import backend.main as m

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(m, "AsyncSessionLocal", factory)

    async with factory() as session:
        row = _tracking_row(7)
        row.reembed_dirty_since = datetime.now(timezone.utc)
        session.add(row)
        await session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/documents/7/"
        return httpx.Response(200, json={
            "title": "Doc 7", "tags": [1], "correspondent": None,
            "document_type": None,
        })

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr("backend.main.httpx.AsyncClient", patched_client)

    class FakePC:
        _base_url = "http://paperless.test"
        _headers: dict = {}

        async def get_document_ocr_text(self, doc_id: int) -> str:
            return "ocr content"

    vs = SpyVectorStore()
    await m._flush_dirty_reembeds(vs, FakePC())

    assert len(vs.upserts) == 1
    assert vs.upserts[0][0] == 7
    assert vs.upserts[0][1] == "ocr content"

    async with factory() as session:
        row = await session.get(DocumentTrackingORM, 7)
        assert row.reembed_dirty_since is None  # marker cleared after flush


@pytest.mark.asyncio
async def test_manual_refresh_409_while_flush_running(app_client) -> None:
    import backend.main as m

    await m._embed_flush_lock.acquire()
    try:
        resp = await app_client.post("/api/embeddings/refresh")
        assert resp.status_code == 409
    finally:
        m._embed_flush_lock.release()


@pytest.mark.asyncio
async def test_manual_refresh_503_without_stores(app_client) -> None:
    # app_client fixture sets vector_store=None and paperless_client=None
    resp = await app_client.post("/api/embeddings/refresh")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_pending_endpoint_counts_dirty_docs(app_client, db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        dirty = _tracking_row(7)
        dirty.reembed_dirty_since = datetime.now(timezone.utc)
        clean = _tracking_row(8)
        session.add_all([dirty, clean])
        await session.commit()

    resp = await app_client.get("/api/embeddings/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["oldest_dirty_since"] is not None
