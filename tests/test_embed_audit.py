"""Embed audit events + last_embedded_at + content-drift reindex.

Covers:
- _record_document_embed writes an 'embedded' audit row (with title) and stamps
  last_embedded_at, creating the tracking row if absent
- schedule_reembed (immediate) records the embed; deferred mode does not
- _run_content_drift_reindex re-embeds only docs whose Paperless `modified` is
  newer than last_embedded_at (no double-embed of unchanged docs)
- _parse_paperless_dt parsing
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.orm_models import AuditLogORM, DocumentTrackingORM


def _patch_session(monkeypatch, db_engine):
    """Route main.AsyncSessionLocal (used by the embed helpers) at the test DB."""
    import backend.main as m
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(m, "AsyncSessionLocal", factory)
    return factory


# ---------------------------------------------------------------------------
# _record_document_embed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_document_embed_writes_audit_and_stamp(db_engine, monkeypatch) -> None:
    import backend.main as m
    factory = _patch_session(monkeypatch, db_engine)

    await m._record_document_embed(2440, "Invoice ACME", "webhook")

    async with factory() as db:
        audits = (await db.execute(select(AuditLogORM).where(AuditLogORM.action_type == "embedded"))).scalars().all()
        assert len(audits) == 1
        a = audits[0]
        assert a.document_id == 2440
        assert a.document_title == "Invoice ACME"
        assert a.change_source == "webhook"

        t = await db.get(DocumentTrackingORM, 2440)
        assert t is not None and t.last_embedded_at is not None  # tracking row created + stamped


@pytest.mark.asyncio
async def test_record_document_embed_double_embed_is_visible(db_engine, monkeypatch) -> None:
    """Two embeds of the same doc (e.g. webhook-on-add + approval) → two rows."""
    import backend.main as m
    factory = _patch_session(monkeypatch, db_engine)

    await m._record_document_embed(7, "Doc 7", "webhook")
    await m._record_document_embed(7, "Doc 7", "approval")

    async with factory() as db:
        rows = (await db.execute(
            select(AuditLogORM).where(AuditLogORM.action_type == "embedded", AuditLogORM.document_id == 7)
        )).scalars().all()
        assert {r.change_source for r in rows} == {"webhook", "approval"}


# ---------------------------------------------------------------------------
# schedule_reembed records the embed (immediate) / defers (daily)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_reembed_immediate_records_embed(db_engine, monkeypatch) -> None:
    import backend.main as m
    factory = _patch_session(monkeypatch, db_engine)
    monkeypatch.setattr(m._settings_svc, "_config",
                        SimpleNamespace(embed_refresh_mode="immediate"))

    vs = SimpleNamespace(upsert=AsyncMock())
    await m.schedule_reembed(7, "content", {"title": "Doc 7"}, vs, source="approval")

    vs.upsert.assert_awaited_once()
    async with factory() as db:
        rows = (await db.execute(select(AuditLogORM).where(AuditLogORM.action_type == "embedded"))).scalars().all()
        assert len(rows) == 1 and rows[0].document_title == "Doc 7" and rows[0].change_source == "approval"


@pytest.mark.asyncio
async def test_schedule_reembed_deferred_records_nothing(db_engine, monkeypatch) -> None:
    import backend.main as m
    factory = _patch_session(monkeypatch, db_engine)
    monkeypatch.setattr(m._settings_svc, "_config",
                        SimpleNamespace(embed_refresh_mode="daily"))

    async with factory() as db:
        db.add(DocumentTrackingORM(document_id=7, first_seen_at=datetime.now(timezone.utc)))
        await db.commit()

    vs = SimpleNamespace(upsert=AsyncMock())
    await m.schedule_reembed(7, "content", {"title": "Doc 7"}, vs)

    vs.upsert.assert_not_awaited()
    async with factory() as db:
        rows = (await db.execute(select(AuditLogORM).where(AuditLogORM.action_type == "embedded"))).scalars().all()
        assert rows == []  # deferred — embed (and its audit) happen at flush time
        t = await db.get(DocumentTrackingORM, 7)
        assert t.reembed_dirty_since is not None
        assert t.last_embedded_at is None


# ---------------------------------------------------------------------------
# _parse_paperless_dt
# ---------------------------------------------------------------------------

def test_parse_paperless_dt() -> None:
    from backend.main import _parse_paperless_dt
    assert _parse_paperless_dt("2026-06-11T14:25:14+00:00") == datetime(2026, 6, 11, 14, 25, 14, tzinfo=timezone.utc)
    assert _parse_paperless_dt("2026-06-11T14:25:14Z") == datetime(2026, 6, 11, 14, 25, 14, tzinfo=timezone.utc)
    # naive → assumed UTC
    assert _parse_paperless_dt("2026-06-11T14:25:14").tzinfo == timezone.utc
    assert _parse_paperless_dt(None) is None
    assert _parse_paperless_dt("garbage") is None


# ---------------------------------------------------------------------------
# Content-drift reindex
# ---------------------------------------------------------------------------

def _drift_app(db_engine, monkeypatch, docs: list[dict]):
    """Build an app stub + mock Paperless that returns `docs` for the documents
    query and empty lists for entity lookups."""
    import backend.main as m
    monkeypatch.setattr(m._settings_svc, "_config", SimpleNamespace(
        content_drift_reindex_days=7, embed_refresh_mode="immediate",
    ))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/documents/":
            return httpx.Response(200, json={"results": docs, "next": None})
        # tags / correspondents / document_types / custom_fields lookups
        return httpx.Response(200, json={"results": [], "next": None})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr("backend.main.httpx.AsyncClient", patched)

    pc = SimpleNamespace(_base_url="http://paperless.test", _headers={})
    vs = SimpleNamespace(upsert=AsyncMock())
    app = SimpleNamespace(state=SimpleNamespace(vector_store=vs, paperless_client=pc))
    return m, app, vs


@pytest.mark.asyncio
async def test_drift_reembeds_only_changed_docs(db_engine, monkeypatch) -> None:
    factory = _patch_session(monkeypatch, db_engine)

    # Doc 1: embedded AFTER its modified → skip. Doc 2: modified AFTER embed → re-embed.
    # Doc 3: never embedded (no tracking row) → re-embed.
    t_old = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t_new = datetime(2026, 6, 10, tzinfo=timezone.utc)
    async with factory() as db:
        db.add(DocumentTrackingORM(document_id=1, first_seen_at=t_old, last_embedded_at=t_new))
        db.add(DocumentTrackingORM(document_id=2, first_seen_at=t_old, last_embedded_at=t_old))
        await db.commit()

    docs = [
        {"id": 1, "title": "Fresh",   "modified": "2026-06-05T00:00:00Z", "content": "c1", "tags": []},
        {"id": 2, "title": "Stale",   "modified": "2026-06-11T00:00:00Z", "content": "c2", "tags": []},
        {"id": 3, "title": "Unseen",  "modified": "2026-06-11T00:00:00Z", "content": "c3", "tags": []},
    ]
    m, app, vs = _drift_app(db_engine, monkeypatch, docs)

    await m._run_content_drift_reindex(app)

    embedded_ids = sorted(call.args[0] for call in vs.upsert.await_args_list)
    assert embedded_ids == [2, 3]  # doc 1 (already fresh) skipped


@pytest.mark.asyncio
async def test_drift_disabled_when_days_zero(db_engine, monkeypatch) -> None:
    import backend.main as m
    _patch_session(monkeypatch, db_engine)
    monkeypatch.setattr(m._settings_svc, "_config", SimpleNamespace(content_drift_reindex_days=0))
    vs = SimpleNamespace(upsert=AsyncMock())
    app = SimpleNamespace(state=SimpleNamespace(
        vector_store=vs, paperless_client=SimpleNamespace(_base_url="x", _headers={})))
    await m._run_content_drift_reindex(app)
    vs.upsert.assert_not_awaited()
