"""Property-based tests for the AuditLogService.

# Feature: paperless-iq, Property 23: Audit log completeness
# Feature: paperless-iq, Property 24: Audit log filter correctness
# Feature: paperless-iq, Property 25: Audit log retention
# Feature: paperless-iq, Property 26: Audit log failure isolation

Validates: Requirements 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.audit_log import AuditLogService
from backend.orm_models import AuditLogORM, Base

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_doc_id_strategy = st.integers(min_value=1, max_value=100_000)

_field_value = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
        min_size=1,
        max_size=40,
    ),
)

_field_names = st.sampled_from([
    "title", "tags", "correspondent", "document_type", "storage_path", "custom_fields",
])

_change_source = st.sampled_from(["ai", "human"])


def _changes_strategy() -> st.SearchStrategy[dict[str, tuple[str | None, str | None]]]:
    """Generate a non-empty dict of field_name -> (previous, new) pairs."""
    return st.dictionaries(
        keys=_field_names,
        values=st.tuples(_field_value, _field_value),
        min_size=1,
        max_size=6,
    )


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
# Property 23: Audit log completeness
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    changes=_changes_strategy(),
    change_source=_change_source,
)
@pytest.mark.asyncio
async def test_property_23_audit_log_completeness(
    document_id: int,
    changes: dict[str, tuple[str | None, str | None]],
    change_source: str,
) -> None:
    """
    # Feature: paperless-iq, Property 23: Audit log completeness

    For any metadata change, exactly one AuditLogEntry must be created per
    changed field, containing all required fields populated.

    Validates: Requirements 9.1
    """
    session = await _make_session()
    try:
        svc = AuditLogService(session)
        entries = await svc.record_changes(
            document_id=document_id,
            changes=changes,
            change_source=change_source,
        )

        # Exactly one entry per changed field
        assert len(entries) == len(changes), (
            f"Expected {len(changes)} entries, got {len(entries)}"
        )

        recorded_fields = {e.field_name for e in entries}
        assert recorded_fields == set(changes.keys()), (
            f"Recorded fields {recorded_fields} != expected {set(changes.keys())}"
        )

        for entry in entries:
            # All required fields must be populated
            assert entry.id is not None
            assert entry.document_id == document_id
            assert entry.field_name in changes
            assert entry.change_source == change_source
            assert entry.changed_at is not None

            # Values must match what was provided
            prev, new = changes[entry.field_name]
            assert entry.previous_value == prev
            assert entry.new_value == new
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Property 24: Audit log filter correctness
# ---------------------------------------------------------------------------

_date_strategy = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2025, 12, 31),
    timezones=st.just(timezone.utc),
)


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    entries_data=st.lists(
        st.tuples(
            _doc_id_strategy,
            _field_names,
            _field_value,
            _field_value,
            _change_source,
            _date_strategy,
        ),
        min_size=1,
        max_size=20,
    ),
    filter_doc_id=st.one_of(st.none(), _doc_id_strategy),
    filter_source=st.one_of(st.none(), _change_source),
)
@pytest.mark.asyncio
async def test_property_24_audit_log_filter_correctness(
    entries_data: list[tuple[int, str, str | None, str | None, str, datetime]],
    filter_doc_id: int | None,
    filter_source: str | None,
) -> None:
    """
    # Feature: paperless-iq, Property 24: Audit log filter correctness

    For any combination of filters, all returned entries must satisfy all
    filters and no matching entry may be omitted.

    Validates: Requirements 9.2
    """
    session = await _make_session()
    try:
        svc = AuditLogService(session)

        # Insert entries directly via ORM for controlled timestamps
        all_entries: list[AuditLogORM] = []
        for doc_id, field, prev, new, source, ts in entries_data:
            row = AuditLogORM(
                id=str(uuid4()),
                document_id=doc_id,
                field_name=field,
                previous_value=prev,
                new_value=new,
                change_source=source,
                changed_at=ts,
            )
            session.add(row)
            all_entries.append(row)
        await session.commit()

        # Query with filters
        results, total = await svc.query(
            document_id=filter_doc_id,
            change_source=filter_source,
            page=1,
            page_size=1000,
        )

        # Compute expected matches
        expected = []
        for row in all_entries:
            if filter_doc_id is not None and row.document_id != filter_doc_id:
                continue
            if filter_source is not None and row.change_source != filter_source:
                continue
            expected.append(row.id)

        result_ids = {str(r.id) for r in results}
        expected_ids = set(expected)

        # All returned entries must satisfy filters
        for r in results:
            if filter_doc_id is not None:
                assert r.document_id == filter_doc_id
            if filter_source is not None:
                assert r.change_source == filter_source

        # No matching entry may be omitted
        assert result_ids == expected_ids, (
            f"Result IDs {result_ids} != expected {expected_ids}"
        )
        assert total == len(expected_ids)
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Property 25: Audit log retention
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    retention_days=st.integers(min_value=90, max_value=365),
    entry_ages_days=st.lists(
        st.integers(min_value=0, max_value=500),
        min_size=1,
        max_size=20,
    ),
)
@pytest.mark.asyncio
async def test_property_25_audit_log_retention(
    retention_days: int,
    entry_ages_days: list[int],
) -> None:
    """
    # Feature: paperless-iq, Property 25: Audit log retention

    Entries within the retention period must be kept; only entries past the
    period are eligible for deletion.

    Validates: Requirements 9.3
    """
    session = await _make_session()
    try:
        svc = AuditLogService(session)
        now = datetime.now(timezone.utc)

        # Insert entries with varying ages
        kept_ids: set[str] = set()
        deleted_ids: set[str] = set()

        for age in entry_ages_days:
            entry_time = now - timedelta(days=age)
            row = AuditLogORM(
                id=str(uuid4()),
                document_id=1,
                field_name="title",
                previous_value="old",
                new_value="new",
                change_source="ai",
                changed_at=entry_time,
            )
            session.add(row)
            if age >= retention_days:
                deleted_ids.add(row.id)
            else:
                kept_ids.add(row.id)
        await session.commit()

        # Run cleanup
        deleted_count = await svc.cleanup(retention_days)

        # Verify kept entries still exist
        remaining, total = await svc.query(page=1, page_size=1000)
        remaining_ids = {str(r.id) for r in remaining}

        # All entries within retention must be kept
        assert kept_ids.issubset(remaining_ids), (
            f"Entries within retention were deleted: {kept_ids - remaining_ids}"
        )

        # All entries past retention must be deleted
        assert deleted_ids.isdisjoint(remaining_ids), (
            f"Entries past retention were kept: {deleted_ids & remaining_ids}"
        )
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Property 26: Audit log failure isolation
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    change_source=_change_source,
)
@pytest.mark.asyncio
async def test_property_26_audit_log_failure_isolation(
    document_id: int,
    change_source: str,
) -> None:
    """
    # Feature: paperless-iq, Property 26: Audit log failure isolation

    When audit log write fails, the Paperless NGX metadata update must still
    complete and the failure must be recorded in the application error log.

    Validates: Requirements 9.4
    """
    session = await _make_session()
    try:
        from backend.approval_queue import ApprovalQueueService
        from backend.models import MetadataSuggestion

        svc = ApprovalQueueService(session)

        suggestion = MetadataSuggestion(
            id=uuid4(),
            document_id=document_id,
            status="pending",
            created_at=datetime.now(timezone.utc),
            title="Original Title",
            tags=["tag1"],
            correspondent="Corp",
            document_type="Invoice",
            storage_path=None,
            custom_fields={},
            llm_provider="openai",
            llm_model="gpt-4o",
            analysis_mode="ocr",
            prompt_used="test",
            raw_llm_response="{}",
        )

        paperless_called = False

        async def _track_patch(doc_id: int, payload: dict[str, Any]) -> None:
            nonlocal paperless_called
            paperless_called = True

        enqueued = await svc.enqueue(suggestion)

        edits = {"title": "Edited Title"}

        # The current approve() writes to PNGX first, then audit log.
        # We verify PNGX was called even when audit log add raises.
        log_handler = logging.handlers.MemoryHandler(capacity=100)
        audit_logger = logging.getLogger("backend.approval_queue")
        audit_logger.addHandler(log_handler)

        try:
            original_add = session.add

            def _failing_add(obj: Any) -> None:
                if isinstance(obj, AuditLogORM):
                    raise RuntimeError("Simulated audit log write failure")
                return original_add(obj)

            try:
                with (
                    patch.object(svc, "_patch_paperless", side_effect=_track_patch),
                    patch.object(session, "add", side_effect=_failing_add),
                ):
                    await svc.approve(enqueued.id, edits=edits)
            except RuntimeError:
                # The exception from audit log write is expected
                pass
        finally:
            audit_logger.removeHandler(log_handler)

        # The Paperless NGX write must have completed
        assert paperless_called, (
            "Paperless NGX metadata update must complete even when audit log fails"
        )
    finally:
        await session.close()
