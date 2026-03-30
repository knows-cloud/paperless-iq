"""Inbox monitor and automation scheduler for Paperless IQ.

InboxMonitor polls Paperless NGX for documents bearing the configured
Inbox_Tag and submits new (unseen) documents for analysis.

Scheduler runs batch analysis at a configured cron interval.

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.orm_models import DocumentTrackingORM

logger = logging.getLogger(__name__)


class InboxMonitor:
    """Polls Paperless NGX for inbox-tagged documents and deduplicates submissions.

    The monitor tracks which documents have been seen in the local DB.
    New documents are submitted to the provided analysis callback exactly once.

    Validates: Requirements 8.1, 8.2
    """

    def __init__(
        self,
        session: AsyncSession,
        fetch_inbox_docs: Callable[[], Coroutine[Any, Any, list[int]]],
        submit_for_analysis: Callable[[int], Coroutine[Any, Any, Any]],
    ) -> None:
        self._session = session
        self._fetch_inbox_docs = fetch_inbox_docs
        self._submit = submit_for_analysis

    async def poll(self) -> list[int]:
        """Poll for new inbox documents and submit unseen ones for analysis.

        Returns:
            List of document IDs that were newly submitted.
        """
        inbox_doc_ids = await self._fetch_inbox_docs()
        if not inbox_doc_ids:
            return []

        # Find which ones we've already seen
        stmt = select(DocumentTrackingORM.document_id).where(
            DocumentTrackingORM.document_id.in_(inbox_doc_ids)
        )
        result = await self._session.execute(stmt)
        seen_ids = {row[0] for row in result.all()}

        new_ids = [did for did in inbox_doc_ids if did not in seen_ids]

        submitted: list[int] = []
        now = datetime.now(timezone.utc)

        for doc_id in new_ids:
            # Record as seen BEFORE submitting to prevent duplicates
            tracking = DocumentTrackingORM(
                document_id=doc_id,
                first_seen_at=now,
            )
            self._session.add(tracking)
            await self._session.commit()

            await self._submit(doc_id)
            submitted.append(doc_id)
            logger.info("Submitted document %d for analysis.", doc_id)

        return submitted

    async def mark_analyzed(self, document_id: int) -> None:
        """Mark a document as analyzed after successful analysis."""
        row = await self._session.get(DocumentTrackingORM, document_id)
        if row:
            row.last_analyzed_at = datetime.now(timezone.utc)
            await self._session.commit()


class Scheduler:
    """Batch analysis scheduler.

    Fetches all unanalyzed inbox documents and submits them in batches
    of the configured batch_size.

    Validates: Requirements 8.3, 8.4, 8.5
    """

    def __init__(
        self,
        session: AsyncSession,
        fetch_inbox_docs: Callable[[], Coroutine[Any, Any, list[int]]],
        submit_for_analysis: Callable[[int], Coroutine[Any, Any, Any]],
        batch_size: int = 10,
    ) -> None:
        self._session = session
        self._fetch_inbox_docs = fetch_inbox_docs
        self._submit = submit_for_analysis
        self._batch_size = batch_size

    async def run_batch(self) -> list[list[int]]:
        """Run a scheduled batch analysis.

        Fetches all inbox documents, filters out already-analyzed ones,
        and processes them in batches of batch_size.

        Returns:
            List of batches, where each batch is a list of document IDs processed.
        """
        inbox_doc_ids = await self._fetch_inbox_docs()
        if not inbox_doc_ids:
            return []

        # Find already-analyzed documents
        stmt = select(DocumentTrackingORM).where(
            DocumentTrackingORM.document_id.in_(inbox_doc_ids)
        )
        result = await self._session.execute(stmt)
        tracked = {row.document_id: row for row in result.scalars().all()}

        # Filter to unanalyzed only
        unanalyzed = [
            did for did in inbox_doc_ids
            if did not in tracked or tracked[did].last_analyzed_at is None
        ]

        if not unanalyzed:
            logger.info("Scheduled run: no unanalyzed documents found.")
            return []

        # Process in batches
        batches: list[list[int]] = []
        num_batches = math.ceil(len(unanalyzed) / self._batch_size)
        now = datetime.now(timezone.utc)

        for i in range(num_batches):
            batch = unanalyzed[i * self._batch_size : (i + 1) * self._batch_size]
            for doc_id in batch:
                # Ensure tracking record exists
                if doc_id not in tracked:
                    tracking = DocumentTrackingORM(
                        document_id=doc_id,
                        first_seen_at=now,
                    )
                    self._session.add(tracking)
                    await self._session.commit()

                await self._submit(doc_id)

                # Mark as analyzed
                row = await self._session.get(DocumentTrackingORM, doc_id)
                if row:
                    row.last_analyzed_at = datetime.now(timezone.utc)
                    await self._session.commit()

            batches.append(batch)
            logger.info(
                "Scheduled batch %d/%d: processed %d documents.",
                i + 1, num_batches, len(batch),
            )

        logger.info(
            "Scheduled run complete: %d documents in %d batches.",
            len(unanalyzed), num_batches,
        )
        return batches
