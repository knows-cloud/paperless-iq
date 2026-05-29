"""Property-based tests for the ApprovalQueueService.

# Feature: paperless-iq, Property 18: Approval queue routing
# Feature: paperless-iq, Property 19: Approval applies edited values
# Feature: paperless-iq, Property 20: Bulk approval state transition

Validates: Requirements 7.1, 7.3, 7.5, 7.6, 7.7, 7.8
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.approval_queue import ApprovalQueueService
from backend.models import MetadataSuggestion
from backend.orm_models import Base

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_doc_id_strategy = st.integers(min_value=1, max_value=100_000)

_text_or_none = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
        min_size=0,
        max_size=50,
    ),
)

_tags_strategy = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=1,
        max_size=20,
    ),
    min_size=0,
    max_size=5,
)


def _suggestion_strategy() -> st.SearchStrategy[MetadataSuggestion]:
    """Generate random MetadataSuggestion instances with status='pending'."""
    return st.builds(
        MetadataSuggestion,
        id=st.builds(uuid4),
        document_id=_doc_id_strategy,
        status=st.just("pending"),
        created_at=st.just(datetime.now(timezone.utc)),
        title=_text_or_none,
        tags=_tags_strategy,
        correspondent=_text_or_none,
        document_type=_text_or_none,
        storage_path=_text_or_none,
        custom_fields=st.just({}),
        llm_provider=st.just("openai"),
        llm_model=st.just("gpt-4o"),
        analysis_mode=st.just("ocr"),
        prompt_used=st.just("test prompt"),
        raw_llm_response=st.just("{}"),
    )


def _edits_strategy() -> st.SearchStrategy[dict[str, Any]]:
    """Generate random field edits for approve()."""
    return st.fixed_dictionaries(
        {},
        optional={
            "title": _text_or_none,
            "tags": _tags_strategy,
            "correspondent": _text_or_none,
            "document_type": _text_or_none,
        },
    )


# ---------------------------------------------------------------------------
# In-memory DB fixture (function-scoped, created per test via asyncio)
# ---------------------------------------------------------------------------

async def _make_session() -> AsyncSession:
    """Create a fresh in-memory SQLite session with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


# ---------------------------------------------------------------------------
# Property 18: Approval queue routing
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    suggestion=_suggestion_strategy(),
    auto_apply=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_18_approval_queue_routing(
    suggestion: MetadataSuggestion,
    auto_apply: bool,
) -> None:
    """
    # Feature: paperless-iq, Property 18: Approval queue routing

    When auto_apply=False: suggestion ends up in queue with status "pending"
    and Paperless NGX write is NOT called.
    When auto_apply=True: Paperless NGX write IS called and no queue entry exists.

    Validates: Requirements 7.1, 7.8
    """
    session = await _make_session()

    paperless_patch = AsyncMock(return_value=None)

    try:
        svc = ApprovalQueueService(session)

        with patch.object(svc, "_patch_paperless", paperless_patch):
            if not auto_apply:
                # Enqueue — should NOT call Paperless NGX
                result = await svc.enqueue(suggestion)

                assert result.status == "pending"
                paperless_patch.assert_not_called()

                # Verify it's in the DB
                items, total = await svc.list(status="pending", page=1, page_size=100)
                ids = [s.id for s in items]
                assert result.id in ids, "Enqueued suggestion must appear in queue"

            else:
                # Auto-apply: enqueue then immediately approve
                enqueued = await svc.enqueue(suggestion)
                await svc.approve(enqueued.id, change_source="ai")

                paperless_patch.assert_called_once()

                # After approval, status is "approved" — not "pending"
                items, _ = await svc.list(status="pending", page=1, page_size=100)
                pending_ids = [s.id for s in items]
                assert enqueued.id not in pending_ids, (
                    "Auto-applied suggestion must not remain in pending queue"
                )
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Property 19: Approval applies edited values
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    suggestion=_suggestion_strategy(),
    edits=_edits_strategy(),
)
@pytest.mark.asyncio
async def test_property_19_approval_applies_edited_values(
    suggestion: MetadataSuggestion,
    edits: dict[str, Any],
) -> None:
    """
    # Feature: paperless-iq, Property 19: Approval applies edited values

    When approve(id, edits=edits) is called, the values written to Paperless NGX
    must match the edited values, NOT the original LLM-suggested values.

    Validates: Requirements 7.3
    """
    session = await _make_session()

    captured_payload: dict[str, Any] = {}

    async def _capture_patch(document_id: int, payload: dict[str, Any], **kwargs: Any) -> None:
        captured_payload.update(payload)

    try:
        svc = ApprovalQueueService(session)

        with patch.object(svc, "_patch_paperless", side_effect=_capture_patch):
            enqueued = await svc.enqueue(suggestion)
            approved = await svc.approve(enqueued.id, edits=edits if edits else None)

        # For each edited field, the written value must match the edit
        for field, edited_value in edits.items():
            assert captured_payload.get(field) == edited_value, (
                f"Field '{field}': expected edited value {edited_value!r}, "
                f"but Paperless NGX received {captured_payload.get(field)!r}"
            )

        # The approved suggestion must also reflect the edits
        for field, edited_value in edits.items():
            assert getattr(approved, field) == edited_value, (
                f"Field '{field}': approved suggestion has {getattr(approved, field)!r}, "
                f"expected {edited_value!r}"
            )
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Property 20: Bulk approval state transition
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    suggestions=st.lists(_suggestion_strategy(), min_size=1, max_size=20),
    do_approve=st.booleans(),
)
@pytest.mark.asyncio
async def test_property_20_bulk_state_transition(
    suggestions: list[MetadataSuggestion],
    do_approve: bool,
) -> None:
    """
    # Feature: paperless-iq, Property 20: Bulk approval state transition

    bulk_approve: ALL suggestions transition to "approved" and Paperless NGX
    write called for each.
    bulk_reject: ALL suggestions transition to "rejected" and Paperless NGX
    write NOT called for any.

    Validates: Requirements 7.5, 7.6, 7.7
    """
    session = await _make_session()

    patch_call_count = 0

    async def _count_patch(document_id: int, payload: dict[str, Any], **kwargs: Any) -> None:
        nonlocal patch_call_count
        patch_call_count += 1

    try:
        svc = ApprovalQueueService(session)

        # Enqueue all suggestions
        enqueued_ids = []
        for s in suggestions:
            enqueued = await svc.enqueue(s)
            enqueued_ids.append(enqueued.id)

        with patch.object(svc, "_patch_paperless", side_effect=_count_patch):
            if do_approve:
                results = await svc.bulk_approve(enqueued_ids)

                # All must be "approved"
                for r in results:
                    assert r.status == "approved", (
                        f"Expected 'approved', got '{r.status}' for suggestion {r.id}"
                    )

                # Paperless NGX write called for each
                assert patch_call_count == len(suggestions), (
                    f"Expected {len(suggestions)} Paperless NGX writes, got {patch_call_count}"
                )

            else:
                results = await svc.bulk_reject(enqueued_ids)

                # All must be "rejected"
                for r in results:
                    assert r.status == "rejected", (
                        f"Expected 'rejected', got '{r.status}' for suggestion {r.id}"
                    )

                # Paperless NGX write must NOT be called
                assert patch_call_count == 0, (
                    f"Expected 0 Paperless NGX writes on bulk reject, got {patch_call_count}"
                )
    finally:
        await session.close()
