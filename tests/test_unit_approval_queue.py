"""Unit tests for the ApprovalQueueService state machine.

Tests:
  - pending → approved transition
  - pending → rejected transition
  - Idempotency: approving an already-approved suggestion raises ValueError
  - Idempotency: rejecting an already-rejected suggestion is a no-op
  - approve() with edits writes edited values, not originals
  - reject() does NOT call Paperless NGX API

Requirements: 7.4, 7.6, 7.7
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.approval_queue import (
    ApprovalQueueService,
    _may_create,
    creation_policy_map,
)
from backend.models import MetadataSuggestion, PaperlessIQConfig
from backend.orm_models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """In-memory SQLite session with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    await sess.close()


def _make_suggestion(**overrides: Any) -> MetadataSuggestion:
    defaults: dict[str, Any] = dict(
        id=uuid4(),
        document_id=42,
        status="pending",
        created_at=datetime.now(timezone.utc),
        title="Invoice from ACME",
        tags=["invoice", "acme"],
        correspondent="ACME Corp",
        document_type="Invoice",
        storage_path=None,
        custom_fields={},
        llm_provider="openai",
        llm_model="gpt-4o",
        analysis_mode="ocr",
        prompt_used="test prompt",
        raw_llm_response="{}",
    )
    defaults.update(overrides)
    return MetadataSuggestion(**defaults)


# ---------------------------------------------------------------------------
# 1. pending → approved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_to_approved(session: AsyncSession) -> None:
    """Approving a pending suggestion transitions it to 'approved'."""
    svc = ApprovalQueueService(session)
    suggestion = _make_suggestion()

    with patch.object(svc, "_patch_paperless", AsyncMock()):
        enqueued = await svc.enqueue(suggestion)
        assert enqueued.status == "pending"

        approved = await svc.approve(enqueued.id)

    assert approved.status == "approved"
    assert approved.id == enqueued.id


# ---------------------------------------------------------------------------
# 2. pending → rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_to_rejected(session: AsyncSession) -> None:
    """Rejecting a pending suggestion transitions it to 'rejected'."""
    svc = ApprovalQueueService(session)
    suggestion = _make_suggestion()

    enqueued = await svc.enqueue(suggestion)
    assert enqueued.status == "pending"

    rejected = await svc.reject(enqueued.id)
    assert rejected.status == "rejected"
    assert rejected.id == enqueued.id


# ---------------------------------------------------------------------------
# 3. Idempotency: approving an already-approved suggestion raises ValueError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_already_approved_raises(session: AsyncSession) -> None:
    """
    Approving an already-approved suggestion raises ValueError.

    Design choice: we raise rather than silently no-op to prevent accidental
    double-writes to Paperless NGX.
    """
    svc = ApprovalQueueService(session)
    suggestion = _make_suggestion()

    with patch.object(svc, "_patch_paperless", AsyncMock()):
        enqueued = await svc.enqueue(suggestion)
        await svc.approve(enqueued.id)

        with pytest.raises(ValueError, match="already 'approved'"):
            await svc.approve(enqueued.id)


# ---------------------------------------------------------------------------
# 4. Idempotency: rejecting an already-rejected suggestion is a no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_already_rejected_is_noop(session: AsyncSession) -> None:
    """Rejecting an already-rejected suggestion returns the same record unchanged."""
    svc = ApprovalQueueService(session)
    suggestion = _make_suggestion()

    enqueued = await svc.enqueue(suggestion)
    first = await svc.reject(enqueued.id)
    assert first.status == "rejected"

    # Second reject — should be a no-op, not raise
    second = await svc.reject(enqueued.id)
    assert second.status == "rejected"
    assert second.id == first.id


# ---------------------------------------------------------------------------
# 5. approve() with edits writes edited values, not originals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_with_edits_writes_edited_values(session: AsyncSession) -> None:
    """When edits are provided, the values written to Paperless NGX are the edited ones."""
    svc = ApprovalQueueService(session)
    suggestion = _make_suggestion(
        title="Original Title",
        tags=["original"],
        correspondent="Original Corp",
    )

    edits = {
        "title": "Edited Title",
        "tags": ["edited", "new"],
        "correspondent": "Edited Corp",
    }

    captured: dict[str, Any] = {}

    async def _capture(document_id: int, payload: dict[str, Any], **kwargs: Any) -> None:
        captured.update(payload)

    with patch.object(svc, "_patch_paperless", side_effect=_capture):
        enqueued = await svc.enqueue(suggestion)
        approved = await svc.approve(enqueued.id, edits=edits)

    # Paperless NGX received the edited values
    assert captured["title"] == "Edited Title"
    assert captured["tags"] == ["edited", "new"]
    assert captured["correspondent"] == "Edited Corp"

    # The returned suggestion also reflects the edits
    assert approved.title == "Edited Title"
    assert approved.tags == ["edited", "new"]
    assert approved.correspondent == "Edited Corp"


# ---------------------------------------------------------------------------
# 6. reject() does NOT call Paperless NGX API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_does_not_call_paperless(session: AsyncSession) -> None:
    """Rejecting a suggestion must never write to Paperless NGX."""
    svc = ApprovalQueueService(session)
    suggestion = _make_suggestion()

    patch_mock = AsyncMock()

    with patch.object(svc, "_patch_paperless", patch_mock):
        enqueued = await svc.enqueue(suggestion)
        await svc.reject(enqueued.id)

    patch_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 7. list() returns paginated results filtered by status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_filters_by_status(session: AsyncSession) -> None:
    """list() returns only suggestions matching the requested status."""
    svc = ApprovalQueueService(session)

    s1 = _make_suggestion(document_id=1)
    s2 = _make_suggestion(document_id=2)
    s3 = _make_suggestion(document_id=3)

    with patch.object(svc, "_patch_paperless", AsyncMock()):
        e1 = await svc.enqueue(s1)
        e2 = await svc.enqueue(s2)
        e3 = await svc.enqueue(s3)

        await svc.approve(e1.id)
        await svc.reject(e2.id)
        # e3 stays pending

    pending_items, pending_total = await svc.list(status="pending", page=1, page_size=10)
    assert pending_total == 1
    assert pending_items[0].id == e3.id

    approved_items, approved_total = await svc.list(status="approved", page=1, page_size=10)
    assert approved_total == 1
    assert approved_items[0].id == e1.id

    rejected_items, rejected_total = await svc.list(status="rejected", page=1, page_size=10)
    assert rejected_total == 1
    assert rejected_items[0].id == e2.id

    all_items, all_total = await svc.list(status=None, page=1, page_size=10)
    assert all_total == 3


# ---------------------------------------------------------------------------
# 8. approve() without edits writes original values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_without_edits_writes_original_values(session: AsyncSession) -> None:
    """When no edits are provided, the original suggestion values are written."""
    svc = ApprovalQueueService(session)
    suggestion = _make_suggestion(
        title="My Title",
        tags=["tag1"],
        correspondent="Corp A",
    )

    captured: dict[str, Any] = {}

    async def _capture(document_id: int, payload: dict[str, Any], **kwargs: Any) -> None:
        captured.update(payload)

    with patch.object(svc, "_patch_paperless", side_effect=_capture):
        enqueued = await svc.enqueue(suggestion)
        await svc.approve(enqueued.id)

    assert captured["title"] == "My Title"
    assert captured["tags"] == ["tag1"]
    assert captured["correspondent"] == "Corp A"


# ---------------------------------------------------------------------------
# 9. create_missing is resolved per entity type
# ---------------------------------------------------------------------------

def test_creation_policy_map_gates_each_entity_type_independently() -> None:
    """allow_new on one entity type must not permit creating the others.

    Regression: create_missing used to be a single OR across the three
    policies, so allow_new on tags alone also created correspondents,
    document types and storage paths.
    """
    config = PaperlessIQConfig(
        llm_provider="openai",
        llm_model="gpt-4o",
        tag_creation_policy="allow_new",
        correspondent_creation_policy="existing_only",
        doctype_creation_policy="existing_only",
        storage_path_creation_policy="existing_only",
    )

    assert creation_policy_map(config) == {
        "tags": True,
        "correspondents": False,
        "document_types": False,
        "storage_paths": False,
        "custom_fields": False,
    }


def test_may_create_bool_applies_to_all_types() -> None:
    """A plain bool is the human-approve case: one answer for every type."""
    assert _may_create(True, "tags") is True
    assert _may_create(True, "storage_paths") is True
    assert _may_create(False, "tags") is False


def test_may_create_mapping_defaults_missing_types_to_false() -> None:
    """An entity type absent from the mapping must not be created."""
    assert _may_create({"tags": True}, "tags") is True
    assert _may_create({"tags": True}, "correspondents") is False


@pytest.mark.asyncio
async def test_patch_paperless_passes_per_type_flags(session: AsyncSession) -> None:
    """_patch_paperless must gate each resolve call on that type's own flag."""
    svc = ApprovalQueueService(session)
    calls: dict[str, bool] = {}

    async def _capture(
        client: Any, base: str, entity_type: str, names: list[str],
        create_missing: bool = False,
    ) -> list[int]:
        calls[entity_type] = create_missing
        return [1]

    payload = {
        "title": "T",
        "tags": ["new-tag"],
        "correspondent": "New Corp",
        "document_type": "New Type",
        "storage_path": "New/Path",
    }

    with (
        patch.object(svc, "_resolve_or_create_entity_ids", side_effect=_capture),
        patch("backend.approval_queue.PAPERLESS_URL", "http://paperless.test"),
        patch("backend.approval_queue.PAPERLESS_TOKEN", "tok"),
        patch("backend.approval_queue.httpx.AsyncClient") as mock_client,
    ):
        mock_client.return_value.__aenter__.return_value.patch = AsyncMock()
        await svc._patch_paperless(
            42, payload,
            create_missing={"tags": True, "correspondents": False,
                            "document_types": False, "storage_paths": True},
        )

    assert calls == {
        "tags": True,
        "correspondents": False,
        "document_types": False,
        "storage_paths": True,
    }
