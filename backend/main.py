"""FastAPI application entry point for Paperless IQ."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.approval_queue import ApprovalQueueService
from backend.audit_log import AuditLogService
from backend.auth import require_auth
from backend.database import get_session
from backend.models import AuditLogEntry, MetadataSuggestion
from backend.settings_service import SettingsService

logger = logging.getLogger(__name__)

# Global settings service instance
_settings_svc = SettingsService()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    logger.info("Paperless IQ starting up")
    # Ensure DB tables exist (dev convenience; production uses Alembic)
    from backend.database import engine
    from backend.orm_models import Base  # noqa: F401 — registers all ORM models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # TODO: load translation cache if present
    # TODO: start APScheduler
    yield
    logger.info("Paperless IQ shutting down")
    # TODO: cleanup scheduler and connections


app = FastAPI(
    title="Paperless IQ",
    description="AI-powered metadata suggestions for Paperless NGX",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Auth middleware stub: protect all /api/* routes."""
    if request.url.path.startswith("/api/"):
        try:
            await require_auth(request)
        except Exception as exc:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Basic health check endpoint."""
    return {"status": "ok", "service": "paperless-iq"}


@app.post("/api/auth/login", tags=["auth"])
async def login() -> dict:
    """Authentication login stub."""
    # TODO: implement real credential validation
    return {"detail": "Login endpoint — not yet implemented"}


# ---------------------------------------------------------------------------
# Approval Queue endpoints
# ---------------------------------------------------------------------------

class ApproveBody(BaseModel):
    edits: dict[str, Any] | None = None


class BulkIdsBody(BaseModel):
    ids: list[UUID]


def _queue_service(session: Annotated[AsyncSession, Depends(get_session)]) -> ApprovalQueueService:
    return ApprovalQueueService(session)


def _audit_service(session: Annotated[AsyncSession, Depends(get_session)]) -> AuditLogService:
    return AuditLogService(session)


@app.post("/api/queue", tags=["queue"], response_model=MetadataSuggestion)
async def enqueue_suggestion(
    suggestion: MetadataSuggestion,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> MetadataSuggestion:
    """Enqueue a metadata suggestion for review."""
    return await svc.enqueue(suggestion)


@app.get("/api/queue", tags=["queue"])
async def list_queue(
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """List queue entries, optionally filtered by status."""
    items, total = await svc.list(status=status, page=page, page_size=page_size)
    return {
        "items": [s.model_dump(mode="json") for s in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/api/queue/{suggestion_id}/approve", tags=["queue"], response_model=MetadataSuggestion)
async def approve_suggestion(
    suggestion_id: UUID,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
    body: ApproveBody = Body(default_factory=ApproveBody),
) -> MetadataSuggestion:
    """Approve a suggestion, optionally with field edits."""
    try:
        return await svc.approve(suggestion_id, edits=body.edits)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@app.post("/api/queue/{suggestion_id}/reject", tags=["queue"], response_model=MetadataSuggestion)
async def reject_suggestion(
    suggestion_id: UUID,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> MetadataSuggestion:
    """Reject a suggestion."""
    try:
        return await svc.reject(suggestion_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@app.post("/api/queue/bulk-approve", tags=["queue"])
async def bulk_approve(
    body: BulkIdsBody,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> dict:
    """Bulk-approve a list of suggestions."""
    try:
        results = await svc.bulk_approve(body.ids)
        return {"approved": [s.model_dump(mode="json") for s in results]}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@app.post("/api/queue/bulk-reject", tags=["queue"])
async def bulk_reject(
    body: BulkIdsBody,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> dict:
    """Bulk-reject a list of suggestions."""
    try:
        results = await svc.bulk_reject(body.ids)
        return {"rejected": [s.model_dump(mode="json") for s in results]}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# Audit Log endpoints
# ---------------------------------------------------------------------------


@app.get("/api/audit", tags=["audit"])
async def query_audit_log(
    svc: Annotated[AuditLogService, Depends(_audit_service)],
    document_id: int | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    change_source: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Query audit log entries with optional filters."""
    items, total = await svc.query(
        document_id=document_id,
        date_from=date_from,
        date_to=date_to,
        change_source=change_source,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [e.model_dump(mode="json") for e in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Semantic Search endpoint
# ---------------------------------------------------------------------------


@app.get("/api/search", tags=["search"])
async def semantic_search(
    q: str = Query(..., min_length=1, description="Natural language query"),
    top_n: int = Query(default=5, ge=1, le=50),
) -> dict:
    """Search the document archive using semantic similarity.

    Requires a vector store to be configured. Returns an error if not available.
    """
    # TODO: inject vector store from app state once configured
    return {
        "detail": "Vector store not configured. Configure a vector store backend in settings.",
        "results": [],
        "query": q,
        "top_n": top_n,
    }


# ---------------------------------------------------------------------------
# Manual Analysis endpoints
# ---------------------------------------------------------------------------


class AnalyzeBody(BaseModel):
    document_id: int
    provider: str | None = None
    model: str | None = None
    mode: str | None = None


@app.post("/api/analyze", tags=["analyze"])
async def manual_analyze(body: AnalyzeBody) -> dict:
    """Trigger manual analysis for a single document with optional overrides.

    Overrides apply to this run only and do not change global settings.
    """
    # TODO: inject ManualAnalysisService from app state once providers are configured
    return {
        "detail": "Analysis service not configured. Configure an LLM provider in settings.",
        "document_id": body.document_id,
        "overrides": {
            "provider": body.provider,
            "model": body.model,
            "mode": body.mode,
        },
    }


@app.get("/api/documents", tags=["documents"])
async def list_documents(
    tag_id: int | None = Query(default=None, description="Filter by tag ID"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    """List documents from Paperless NGX, optionally filtered by tag."""
    # TODO: inject PaperlessNGXClient from app state
    return {
        "detail": "Paperless NGX client not configured.",
        "items": [],
        "total": 0,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------


@app.get("/api/settings", tags=["settings"])
async def get_settings() -> dict:
    """Return current settings with credentials masked."""
    return _settings_svc.get_masked()


@app.put("/api/settings", tags=["settings"])
async def update_settings(body: dict[str, Any] = Body(...)) -> dict:
    """Update settings with validation."""
    try:
        config = _settings_svc.update(body)
        return _settings_svc.get_masked()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Config Import/Export endpoints
# ---------------------------------------------------------------------------


@app.get("/api/config/export", tags=["config"])
async def export_config() -> dict:
    """Export configuration as JSON with credentials redacted."""
    return _settings_svc.export_config()


@app.post("/api/config/import", tags=["config"])
async def import_config(body: dict[str, Any] = Body(...)) -> dict:
    """Import configuration, skipping unknown/invalid fields."""
    summary = _settings_svc.import_config(body)
    return summary
