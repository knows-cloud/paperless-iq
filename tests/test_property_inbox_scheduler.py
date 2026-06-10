"""Property-based tests for InboxMonitor and Scheduler.

# Feature: paperless-iq, Property 21: Inbox tag trigger
# Feature: paperless-iq, Property 22: Scheduled run completeness
# Feature: paperless-iq, Property 17: Batch size enforcement

Validates: Requirements 6.5, 8.1, 8.4
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.inbox_monitor import InboxMonitor, Scheduler
from backend.orm_models import Base, DocumentTrackingORM


# ---------------------------------------------------------------------------
# In-memory DB helper
# ---------------------------------------------------------------------------

async def _make_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


# ---------------------------------------------------------------------------
# Property 21: Inbox tag trigger
# ---------------------------------------------------------------------------

@given(
    doc_ids=st.lists(
        st.integers(min_value=1, max_value=100_000),
        min_size=1,
        max_size=20,
        unique=True,
    ),
    num_polls=st.integers(min_value=1, max_value=3),
)
@pytest.mark.asyncio
async def test_property_21_inbox_tag_trigger(
    doc_ids: list[int],
    num_polls: int,
) -> None:
    """
    # Feature: paperless-iq, Property 21: Inbox tag trigger

    Each document must be submitted exactly once per inbox event,
    even across multiple polls.

    Validates: Requirements 8.1
    """
    session = await _make_session()
    try:
        submitted: list[int] = []

        async def _fetch_inbox() -> list[int]:
            return doc_ids

        async def _submit(doc_id: int) -> None:
            submitted.append(doc_id)

        monitor = InboxMonitor(
            session=session,
            fetch_inbox_docs=_fetch_inbox,
            submit_for_analysis=_submit,
        )

        # Poll multiple times — same docs should only be submitted once
        for _ in range(num_polls):
            await monitor.poll()

        # Each doc submitted exactly once
        assert sorted(submitted) == sorted(doc_ids), (
            f"Expected each doc submitted once: {sorted(doc_ids)}, got {sorted(submitted)}"
        )
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Property 22: Scheduled run completeness
# ---------------------------------------------------------------------------

@given(
    all_doc_ids=st.lists(
        st.integers(min_value=1, max_value=100_000),
        min_size=1,
        max_size=20,
        unique=True,
    ),
    already_analyzed_fraction=st.floats(min_value=0.0, max_value=1.0),
)
@pytest.mark.asyncio
async def test_property_22_scheduled_run_completeness(
    all_doc_ids: list[int],
    already_analyzed_fraction: float,
) -> None:
    """
    # Feature: paperless-iq, Property 22: Scheduled run completeness

    A scheduled run must submit all unanalyzed docs and skip already-analyzed ones.

    Validates: Requirements 8.4
    """
    session = await _make_session()
    try:
        # Split docs into analyzed and unanalyzed
        split_idx = int(len(all_doc_ids) * already_analyzed_fraction)
        analyzed_ids = set(all_doc_ids[:split_idx])
        expected_unanalyzed = [d for d in all_doc_ids if d not in analyzed_ids]

        # Pre-populate tracking records for "already analyzed" docs
        now = datetime.now(timezone.utc)
        for doc_id in analyzed_ids:
            row = DocumentTrackingORM(
                document_id=doc_id,
                first_seen_at=now,
                last_analyzed_at=now,
            )
            session.add(row)
        await session.commit()

        submitted: list[int] = []

        async def _fetch_inbox() -> list[int]:
            return all_doc_ids

        async def _submit(doc_id: int) -> None:
            submitted.append(doc_id)

        scheduler = Scheduler(
            session=session,
            fetch_inbox_docs=_fetch_inbox,
            submit_for_analysis=_submit,
            batch_size=5,
        )

        await scheduler.run_batch()

        # All unanalyzed docs must be submitted
        assert sorted(submitted) == sorted(expected_unanalyzed), (
            f"Expected unanalyzed {sorted(expected_unanalyzed)}, got {sorted(submitted)}"
        )

        # No already-analyzed doc should be re-submitted
        for doc_id in analyzed_ids:
            assert doc_id not in submitted, (
                f"Already-analyzed doc {doc_id} was re-submitted"
            )
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Property 17: Batch size enforcement
# ---------------------------------------------------------------------------

@given(
    num_docs=st.integers(min_value=1, max_value=50),
    batch_size=st.integers(min_value=1, max_value=20),
)
@pytest.mark.asyncio
async def test_property_17_batch_size_enforcement(
    num_docs: int,
    batch_size: int,
) -> None:
    """
    # Feature: paperless-iq, Property 17: Batch size enforcement

    Documents must be processed in groups of at most B, and all Q documents
    must be processed across ceil(Q/B) batches.

    Validates: Requirements 6.5
    """
    session = await _make_session()
    try:
        doc_ids = list(range(1, num_docs + 1))
        submitted: list[int] = []

        async def _fetch_inbox() -> list[int]:
            return doc_ids

        async def _submit(doc_id: int) -> None:
            submitted.append(doc_id)

        scheduler = Scheduler(
            session=session,
            fetch_inbox_docs=_fetch_inbox,
            submit_for_analysis=_submit,
            batch_size=batch_size,
        )

        batches = await scheduler.run_batch()

        # All documents must be processed
        assert sorted(submitted) == sorted(doc_ids), (
            f"Not all documents processed: expected {sorted(doc_ids)}, got {sorted(submitted)}"
        )

        # Number of batches must be ceil(Q/B)
        expected_batches = math.ceil(num_docs / batch_size)
        assert len(batches) == expected_batches, (
            f"Expected {expected_batches} batches, got {len(batches)}"
        )

        # Each batch must have at most batch_size documents
        for i, batch in enumerate(batches):
            assert len(batch) <= batch_size, (
                f"Batch {i} has {len(batch)} docs, exceeds batch_size={batch_size}"
            )
    finally:
        await session.close()
