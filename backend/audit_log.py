"""Audit log service for Paperless IQ.

Manages AuditLogEntry records:
  - record_changes()  — write one entry per changed field
  - record_event()    — write a single non-field-change event (reindex, webhook, etc.)
  - query()           — filtered, paginated query
  - export_rows()     — return all matching rows for CSV/JSON export
  - cleanup()         — delete entries past retention period

Actor values:
  "user:<username>"     — action performed by a logged-in user
  "automation"          — background automation loop
  "webhook"             — triggered by Paperless NGX webhook
  "manual_analysis"     — manual OCR analysis triggered via UI
  "vision_analysis"     — manual vision analysis triggered via UI
  "system"              — internal system action (startup, reindex, etc.)
  Legacy: "ai", "human" — old values; still displayed as-is
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AuditLogEntry
from backend.orm_models import AuditLogORM

logger = logging.getLogger(__name__)


def _orm_to_pydantic(row: AuditLogORM) -> AuditLogEntry:
    return AuditLogEntry(
        id=UUID(row.id),
        document_id=row.document_id,
        document_title=row.document_title,
        field_name=row.field_name,
        previous_value=row.previous_value,
        new_value=row.new_value,
        change_source=row.change_source,
        action_type=getattr(row, "action_type", "field_change") or "field_change",
        session_id=getattr(row, "session_id", None),
        changed_at=row.changed_at,
        suggestion_id=UUID(row.suggestion_id) if row.suggestion_id else None,
    )


class AuditLogService:
    """Manages audit log entries for document and system events.

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
        document_title: str | None = None,
        session_id: str | None = None,
    ) -> list[AuditLogEntry]:
        """Write one AuditLogEntry per changed field.

        Args:
            document_id: The Paperless NGX document ID.
            changes: Mapping of field_name -> (previous_value, new_value).
            change_source: Actor string (e.g. "user:john", "automation", "webhook").
            suggestion_id: Optional link to the MetadataSuggestion.
            changed_at: Override timestamp (defaults to now UTC).
            document_title: Optional document title for display.
            session_id: Optional UUID string for correlating related events.
        """
        now = changed_at or datetime.now(timezone.utc)
        entries: list[AuditLogEntry] = []

        for field_name, (prev, new) in changes.items():
            row = AuditLogORM(
                id=str(uuid4()),
                document_id=document_id,
                document_title=document_title,
                field_name=field_name,
                previous_value=prev,
                new_value=new,
                change_source=change_source,
                action_type="field_change",
                session_id=session_id,
                changed_at=now,
                suggestion_id=str(suggestion_id) if suggestion_id else None,
            )
            self._session.add(row)
            entries.append(_orm_to_pydantic(row))

        await self._session.commit()
        return entries

    async def record_event(
        self,
        action_type: str,
        change_source: str,
        document_id: int | None = None,
        document_title: str | None = None,
        field_name: str = "_event",
        new_value: str | None = None,
        suggestion_id: UUID | None = None,
        session_id: str | None = None,
        changed_at: datetime | None = None,
    ) -> AuditLogEntry:
        """Write a single audit event (not a field change).

        Suitable for: approved, rejected, reindex, webhook_received, analysis_triggered.

        Args:
            action_type: Event type string (e.g. "approved", "reindex", "webhook_received").
            change_source: Actor string (e.g. "user:john", "automation", "webhook").
            document_id: Affected document ID (0 for system-wide events).
            document_title: Optional document title.
            field_name: Convention: "_event" for non-field events.
            new_value: Optional human-readable description of the event.
            suggestion_id: Optional link to a MetadataSuggestion.
            session_id: Optional UUID string for correlating related events.
            changed_at: Override timestamp.
        """
        now = changed_at or datetime.now(timezone.utc)
        row = AuditLogORM(
            id=str(uuid4()),
            document_id=document_id or 0,
            document_title=document_title,
            field_name=field_name,
            previous_value=None,
            new_value=new_value,
            change_source=change_source,
            action_type=action_type,
            session_id=session_id,
            changed_at=now,
            suggestion_id=str(suggestion_id) if suggestion_id else None,
        )
        self._session.add(row)
        await self._session.commit()
        return _orm_to_pydantic(row)

    async def query(
        self,
        document_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        change_source: str | None = None,
        action_type: str | None = None,
        field_name: str | None = None,
        document_title_pattern: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLogEntry], int]:
        """Return filtered, paginated audit log entries.

        All filters are optional and combined with AND logic.
        document_title_pattern is a case-insensitive substring match.

        Returns:
            (items, total_count)
        """
        conditions = self._build_conditions(
            document_id=document_id,
            date_from=date_from,
            date_to=date_to,
            change_source=change_source,
            action_type=action_type,
            field_name=field_name,
            document_title_pattern=document_title_pattern,
        )

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

    async def export_rows(
        self,
        document_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        change_source: str | None = None,
        action_type: str | None = None,
        field_name: str | None = None,
        document_title_pattern: str | None = None,
        max_rows: int = 100_000,
    ) -> list[AuditLogEntry]:
        """Return all matching rows for export (up to max_rows)."""
        conditions = self._build_conditions(
            document_id=document_id,
            date_from=date_from,
            date_to=date_to,
            change_source=change_source,
            action_type=action_type,
            field_name=field_name,
            document_title_pattern=document_title_pattern,
        )
        where_clause = and_(*conditions) if conditions else True
        items_q = (
            select(AuditLogORM)
            .where(where_clause)
            .order_by(AuditLogORM.changed_at.desc())
            .limit(max_rows)
        )
        result = await self._session.execute(items_q)
        return [_orm_to_pydantic(r) for r in result.scalars().all()]

    def _build_conditions(
        self,
        document_id: int | None,
        date_from: datetime | None,
        date_to: datetime | None,
        change_source: str | None,
        action_type: str | None,
        field_name: str | None,
        document_title_pattern: str | None,
    ) -> list:
        conditions = []
        if document_id is not None:
            conditions.append(AuditLogORM.document_id == document_id)
        if date_from is not None:
            conditions.append(AuditLogORM.changed_at >= date_from)
        if date_to is not None:
            conditions.append(AuditLogORM.changed_at <= date_to)
        if change_source is not None:
            conditions.append(AuditLogORM.change_source == change_source)
        if action_type is not None:
            conditions.append(AuditLogORM.action_type == action_type)
        if field_name is not None:
            conditions.append(AuditLogORM.field_name == field_name)
        if document_title_pattern is not None:
            conditions.append(
                AuditLogORM.document_title.ilike(f"%{document_title_pattern}%")
            )
        return conditions

    async def cleanup(self, retention_days: int) -> int:
        """Delete audit log entries older than the retention period.

        Args:
            retention_days: Minimum number of days to retain entries.

        Returns:
            Number of deleted entries.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        stmt = delete(AuditLogORM).where(AuditLogORM.changed_at < cutoff)
        result = await self._session.execute(stmt)
        await self._session.commit()
        deleted = result.rowcount  # type: ignore[assignment]
        logger.info("Audit log cleanup: deleted %d entries older than %d days.", deleted, retention_days)
        return deleted


def rows_to_csv(entries: list[AuditLogEntry]) -> str:
    """Serialize a list of AuditLogEntry records to CSV text."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "document_id", "document_title", "field_name",
        "previous_value", "new_value", "change_source", "action_type",
        "session_id", "changed_at", "suggestion_id",
    ])
    for e in entries:
        writer.writerow([
            str(e.id),
            e.document_id,
            e.document_title or "",
            e.field_name,
            e.previous_value or "",
            e.new_value or "",
            e.change_source,
            e.action_type,
            e.session_id or "",
            e.changed_at.isoformat(),
            str(e.suggestion_id) if e.suggestion_id else "",
        ])
    return output.getvalue()
