"""SQLAlchemy ORM models for Paperless IQ."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SuggestionORM(Base):
    """Persisted MetadataSuggestion record."""

    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # Suggested values
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    correspondent: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Provenance
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    analysis_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    prompt_used: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_llm_response: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AuditLogORM(Base):
    """Persisted AuditLogEntry record."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    document_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # change_source holds the actor string: "user:<name>", "automation", "webhook", "system", etc.
    change_source: Mapped[str] = mapped_column(String(200), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, default="field_change")
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    suggestion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class DocumentTrackingORM(Base):
    """Tracks documents seen by the inbox monitor."""

    __tablename__ = "document_tracking"

    document_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    embedding_stored: Mapped[bool] = mapped_column(default=False)


class SettingsORM(Base):
    """Single-row table that persists PaperlessIQConfig as JSON."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class ConversationSessionORM(Base):
    """A Discovery chat session with sliding-window conversation history.

    ``turns`` holds the most recent verbatim Q&A pairs (capped at
    VERBATIM_WINDOW entries).  When the window fills, older turns are folded
    into ``summary`` via an LLM summarisation call so the model always has
    full context without unbounded token growth.

    Sessions expire automatically after 24 hours of inactivity.
    """

    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # Verbatim recent turns: [{role: "user"|"assistant", content: str}, ...]
    turns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Rolling prose summary of turns that were compressed away
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserMemoryORM(Base):
    """A single long-term memory fact extracted from a Discovery conversation.

    Each row is one concrete fact (e.g. "Telekom contract ends 2025-08, €30/mo").
    Facts are embedded into a dedicated ChromaDB collection for semantic retrieval
    and injected into new Discovery conversations as prior context.
    """

    __tablename__ = "user_memories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # Which conversation session this fact was extracted from (for traceability)
    source_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Whether this fact has been embedded into ChromaDB
    embedding_stored: Mapped[bool] = mapped_column(default=False)


class UserPermissionsORM(Base):
    """Per-user access-control record for Paperless IQ.

    Created or updated at every login. ``ng_admin`` caches the Paperless NGX
    superuser/staff status checked at login time.  When ``sync_ng_admins`` is
    enabled in settings, ``ng_admin=True`` bypasses individual permission flags.
    """

    __tablename__ = "user_permissions"

    username: Mapped[str] = mapped_column(String(150), primary_key=True)
    ng_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_view_queue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_analyze: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_discover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_settings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
