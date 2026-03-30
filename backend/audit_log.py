"""Audit log service for Paperless IQ.

Manages AuditLogEntry records:
  - record_changes()  — write one entry per changed field
  - query()           — filtered, paginated query
  - cleanup()         — delete entries past retention period

Validates: Requirements 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AuditLogEntry
from backend.orm_models import AuditLogORM

logger = logging.getLogger(__name__)


def _orm_to_pydantic(row: AuditLogORM) -> AuditLogEntry:
    return AuditLogEntry(
        id=UUID(row.id),
        document_id=row.document_id,
        field_name=row.field_name,
        previous_value=row.previous_value,
        new_value=row.new_value,
        change_source=row.change_source,  # type: ignore[arg-type]
        changed_at=row.changed_at,
        suggestion_id=UUID(row.suggestion_id) if row.suggestion_id else None,
    )


class AuditLogService:
    """Manages audit log entries for metadata changes.

    All methods require an AsyncSession. The service commits internally.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_changes(
        self,
        document_id: int,
        changes: dict[str, tuple[str | None, str | None]],
        change_source: str,
        suggestion_id: UUID | None = None,
        changed_at: datetime | None = None,
    ) -> list[AuditLogEntry]:
        """Write one AuditLogEntry per changed field.

        Args:
            document_id: The Paperless NGX document ID.
            changes: Mapping of field_name -> (previous_value, new_value).
            change_source: "ai" or "human".
            suggestion_id: Optional link to the MetadataSuggestion.
            changed_at: Override timestamp (defaults to now UTC).

        Returns:
            List of created AuditLogEntry records.

        Validates: Requirements 9.1
        """
        now = changed_at or datetime.now(timezone.utc)
        entries: list[AuditLogEntry] = []

        for field_name, (prev, new) in changes.items():
            row = AuditLogORM(
                id=str(uuid4()),
                document_id=document_id,
                field_name=field_name,
                previous_value=prev,
                new_value=new,
                change_source=change_source,
                changed_at=now,
                suggestion_id=str(suggestion_id) if suggestion_id else None,
            )
            self._session.add(row)
            entries.append(_orm_to_pydantic(row))

        await self._session.commit()
        return entries

    async def query(
        self,
        document_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        change_source: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLogEntry], int]:
        """Return filtered, paginated audit log entries.

        All filters are optional and combined with AND logic.

        Returns:
            (items, total_count)

        Validates: Requirements 9.2
        """
        conditions = []
        if document_id is not None:
            conditions.append(AuditLogORM.document_id == document_id)
        if date_from is not None:
            conditions.append(AuditLogORM.changed_at >= date_from)
        if date_to is not None:
            conditions.append(AuditLogORM.changed_at <= date_to)
        if change_source is not None:
            conditions.append(AuditLogORM.change_source == change_source)

        where_clause = and_(*conditions) if conditions else True

        count_q = select(func.count()).select_from(AuditLogORM).where(where_clause)
        count_result = await self._session.execute(count_q)
        total = count_result.scalar_one()

        offset = (page - 1) * page_size
        items_q = (
            select(AuditLogORM)
            .where(where_clause)
            .order_by(AuditLogORM.changed_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self._session.execute(items_q)
        rows = result.scalars().all()

        return [_orm_to_pydantic(r) for r in rows], total

    async def cleanup(self, retention_days: int) -> int:
        """Delete audit log entries older than the retention period.

        Args:
            retention_days: Minimum number of days to retain entries.

        Returns:
            Number of deleted entries.

        Validates: Requirements 9.3
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        stmt = delete(AuditLogORM).where(AuditLogORM.changed_at < cutoff)
        result = await self._session.execute(stmt)
        await self._session.commit()
        deleted = result.rowcount  # type: ignore[assignment]
        logger.info("Audit log cleanup: deleted %d entries older than %d days.", deleted, retention_days)
        return deleted
