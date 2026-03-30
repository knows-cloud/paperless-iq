"""Approval queue service for Paperless IQ.

Manages the lifecycle of MetadataSuggestion records:
  - enqueue()       — add to queue with status "pending"
  - approve()       — apply metadata to Paperless NGX, write audit log, set "approved"
  - reject()        — set "rejected", no Paperless NGX write
  - bulk_approve()  — call approve() for each id in sequence
  - bulk_reject()   — call reject() for each id in sequence
  - list()          — paginated, optionally filtered by status

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import MetadataSuggestion
from backend.orm_models import AuditLogORM, SuggestionORM

logger = logging.getLogger(__name__)

PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://localhost:8000")
PAPERLESS_TOKEN = os.getenv("PAPERLESS_TOKEN", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _orm_to_pydantic(row: SuggestionORM) -> MetadataSuggestion:
    """Convert a SuggestionORM row to a MetadataSuggestion Pydantic model."""
    return MetadataSuggestion(
        id=UUID(row.id),
        document_id=row.document_id,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
        title=row.title,
        tags=row.tags or [],
        correspondent=row.correspondent,
        document_type=row.document_type,
        storage_path=row.storage_path,
        custom_fields=row.custom_fields or {},
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        analysis_mode=row.analysis_mode,  # type: ignore[arg-type]
        prompt_used=row.prompt_used,
        raw_llm_response=row.raw_llm_response,
    )


def _pydantic_to_orm(suggestion: MetadataSuggestion) -> SuggestionORM:
    """Convert a MetadataSuggestion Pydantic model to a SuggestionORM row."""
    return SuggestionORM(
        id=str(suggestion.id),
        document_id=suggestion.document_id,
        status=suggestion.status,
        created_at=suggestion.created_at,
        title=suggestion.title,
        tags=suggestion.tags,
        correspondent=suggestion.correspondent,
        document_type=suggestion.document_type,
        storage_path=suggestion.storage_path,
        custom_fields=suggestion.custom_fields,
        llm_provider=suggestion.llm_provider,
        llm_model=suggestion.llm_model,
        analysis_mode=suggestion.analysis_mode,
        prompt_used=suggestion.prompt_used,
        raw_llm_response=suggestion.raw_llm_response,
    )


def _value_to_str(value: Any) -> str | None:
    """Serialize a field value to a string for audit log storage."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ApprovalQueueService:
    """
    Manages the approval queue lifecycle for MetadataSuggestion records.

    All methods require an AsyncSession to be injected. The session is NOT
    committed inside the service — callers are responsible for committing.
    For convenience, the public methods commit after each operation.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # enqueue
    # ------------------------------------------------------------------

    async def enqueue(self, suggestion: MetadataSuggestion) -> MetadataSuggestion:
        """
        Add a suggestion to the queue with status "pending".

        Validates: Requirements 7.1
        """
        pending = suggestion.model_copy(update={"status": "pending"})
        row = _pydantic_to_orm(pending)
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        logger.info("Enqueued suggestion %s for document %d.", row.id, row.document_id)
        return _orm_to_pydantic(row)

    # ------------------------------------------------------------------
    # approve
    # ------------------------------------------------------------------

    async def approve(
        self,
        suggestion_id: UUID,
        edits: dict | None = None,
        change_source: str = "human",
    ) -> MetadataSuggestion:
        """
        Approve a suggestion, optionally applying field edits.

        Steps:
          1. Load the suggestion from DB (must be "pending")
          2. Apply edits to the suggestion fields
          3. Write metadata to Paperless NGX via HTTP PATCH
          4. Write one AuditLogEntry per changed field
          5. Transition status to "approved"

        Raises ValueError if the suggestion is not in "pending" status.

        Validates: Requirements 7.3, 7.4, 7.6
        """
        row = await self._session.get(SuggestionORM, str(suggestion_id))
        if row is None:
            raise ValueError(f"Suggestion {suggestion_id} not found.")
        if row.status != "pending":
            raise ValueError(
                f"Suggestion {suggestion_id} is already '{row.status}'; cannot approve."
            )

        # Apply edits
        editable_fields = ("title", "tags", "correspondent", "document_type", "storage_path", "custom_fields")
        original: dict[str, Any] = {f: getattr(row, f) for f in editable_fields}

        if edits:
            for field, value in edits.items():
                if field in editable_fields:
                    setattr(row, field, value)

        # Build the Paperless NGX PATCH payload
        patch_payload: dict[str, Any] = {}
        for field in editable_fields:
            patch_payload[field] = getattr(row, field)

        # Write to Paperless NGX
        await self._patch_paperless(row.document_id, patch_payload)

        # Write audit log entries — one per changed field
        now = datetime.now(timezone.utc)
        for field in editable_fields:
            old_val = original[field]
            new_val = getattr(row, field)
            if old_val != new_val:
                audit = AuditLogORM(
                    id=str(uuid4()),
                    document_id=row.document_id,
                    field_name=field,
                    previous_value=_value_to_str(old_val),
                    new_value=_value_to_str(new_val),
                    change_source=change_source,
                    changed_at=now,
                    suggestion_id=row.id,
                )
                self._session.add(audit)

        row.status = "approved"
        await self._session.commit()
        await self._session.refresh(row)
        logger.info("Approved suggestion %s for document %d.", row.id, row.document_id)
        return _orm_to_pydantic(row)

    # ------------------------------------------------------------------
    # reject
    # ------------------------------------------------------------------

    async def reject(self, suggestion_id: UUID) -> MetadataSuggestion:
        """
        Reject a suggestion — no Paperless NGX write.

        Idempotent: rejecting an already-rejected suggestion is a no-op.

        Validates: Requirements 7.4, 7.7
        """
        row = await self._session.get(SuggestionORM, str(suggestion_id))
        if row is None:
            raise ValueError(f"Suggestion {suggestion_id} not found.")
        if row.status == "rejected":
            # Already rejected — no-op
            return _orm_to_pydantic(row)
        if row.status == "approved":
            raise ValueError(
                f"Suggestion {suggestion_id} is already 'approved'; cannot reject."
            )
        row.status = "rejected"
        await self._session.commit()
        await self._session.refresh(row)
        logger.info("Rejected suggestion %s for document %d.", row.id, row.document_id)
        return _orm_to_pydantic(row)

    # ------------------------------------------------------------------
    # bulk operations
    # ------------------------------------------------------------------

    async def bulk_approve(
        self,
        suggestion_ids: list[UUID],
        change_source: str = "human",
    ) -> list[MetadataSuggestion]:
        """
        Approve multiple suggestions in sequence.

        Validates: Requirements 7.5, 7.6
        """
        results: list[MetadataSuggestion] = []
        for sid in suggestion_ids:
            result = await self.approve(sid, change_source=change_source)
            results.append(result)
        return results

    async def bulk_reject(self, suggestion_ids: list[UUID]) -> list[MetadataSuggestion]:
        """
        Reject multiple suggestions in sequence.

        Validates: Requirements 7.5, 7.7
        """
        results: list[MetadataSuggestion] = []
        for sid in suggestion_ids:
            result = await self.reject(sid)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------

    async def list(
        self,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[MetadataSuggestion], int]:
        """
        Return paginated suggestions, optionally filtered by status.

        Returns (items, total_count).

        Validates: Requirements 7.2
        """
        query = select(SuggestionORM)
        count_query = select(func.count()).select_from(SuggestionORM)

        if status is not None:
            query = query.where(SuggestionORM.status == status)
            count_query = count_query.where(SuggestionORM.status == status)

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(SuggestionORM.created_at.desc())

        result = await self._session.execute(query)
        rows = result.scalars().all()

        count_result = await self._session.execute(count_query)
        total = count_result.scalar_one()

        return [_orm_to_pydantic(r) for r in rows], total

    # ------------------------------------------------------------------
    # Internal: Paperless NGX write
    # ------------------------------------------------------------------

    async def _patch_paperless(self, document_id: int, payload: dict[str, Any]) -> None:
        """
        PATCH document metadata to Paperless NGX.

        Validates: Requirements 7.6
        """
        if not PAPERLESS_URL or not PAPERLESS_TOKEN:
            logger.warning(
                "PAPERLESS_URL or PAPERLESS_TOKEN not set; skipping Paperless NGX write for doc %d.",
                document_id,
            )
            return

        url = f"{PAPERLESS_URL.rstrip('/')}/api/documents/{document_id}/"
        headers = {"Authorization": f"Token {PAPERLESS_TOKEN}"}

        try:
            async with httpx.AsyncClient(headers=headers, timeout=30) as client:
                resp = await client.patch(url, json=payload)
                resp.raise_for_status()
                logger.info("Patched Paperless NGX document %d.", document_id)
        except httpx.HTTPError as exc:
            logger.error(
                "Failed to patch Paperless NGX document %d: %s", document_id, exc
            )
            raise
