"""FastAPI application entry point for Paperless IQ."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyzer import PaperlessNGXClient
from backend.approval_queue import ApprovalQueueService
from backend.audit_log import AuditLogService
from backend.auth import require_auth
from backend.database import AsyncSessionLocal, get_session
from backend.inbox_monitor import InboxMonitor, Scheduler
from backend.manual_analysis import ManualAnalysisService
from backend.models import MetadataSuggestion
from backend.provider_registry import build_providers
from backend.rate_limiter import RateLimiter
from backend.settings_service import SettingsService
from backend.vector_store import ChromaVectorStore

logger = logging.getLogger(__name__)

# Global settings service instance
_settings_svc = SettingsService()


async def _inbox_polling_loop(
    app: FastAPI,
    poll_interval: int,
) -> None:
    """Run the InboxMonitor poll loop at the configured interval."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                config = _settings_svc.config
                paperless_client: PaperlessNGXClient | None = app.state.paperless_client
                manual_svc: ManualAnalysisService | None = app.state.manual_analysis_svc

                if paperless_client is None or manual_svc is None:
                    logger.warning("Inbox polling skipped: services not configured.")
                    await asyncio.sleep(poll_interval)
                    continue

                inbox_tag_id = config.inbox_tag_id

                async def fetch_inbox_docs() -> list[int]:
                    import httpx
                    url = f"{paperless_client._base_url}/api/documents/"
                    params: dict[str, Any] = {"page_size": 100}
                    if inbox_tag_id is not None:
                        params["tags__id__in"] = inbox_tag_id
                    async with httpx.AsyncClient(
                        headers=paperless_client._headers, timeout=30
                    ) as client:
                        resp = await client.get(url, params=params)
                        resp.raise_for_status()
                        data = resp.json()
                    return [d["id"] for d in data.get("results", [])]

                async def submit_for_analysis(doc_id: int) -> Any:
                    try:
                        suggestion = await manual_svc.analyze(doc_id)
                        from backend.approval_queue import ApprovalQueueService
                        queue_svc = ApprovalQueueService(session)
                        enqueued = await queue_svc.enqueue(suggestion)
                        if config.auto_apply:
                            # Auto-approve: apply to Paperless NGX immediately
                            # Use create_missing=True when creation policies allow new values
                            create_missing = (
                                config.tag_creation_policy == "allow_new"
                                or config.correspondent_creation_policy == "allow_new"
                                or config.doctype_creation_policy == "allow_new"
                            )
                            await queue_svc.approve(
                                enqueued.id, merge_tags=True, create_missing=create_missing,
                            )
                            logger.info("Auto-approved suggestion for document %d.", doc_id)
                        else:
                            logger.info("Enqueued suggestion for document %d.", doc_id)
                    except Exception:
                        logger.exception("Inbox analysis failed for doc %d", doc_id)

                monitor = InboxMonitor(session, fetch_inbox_docs, submit_for_analysis)
                submitted = await monitor.poll()
                if submitted:
                    logger.info("Inbox poll submitted %d documents.", len(submitted))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Inbox polling loop error")

        await asyncio.sleep(poll_interval)


async def _scheduler_loop(
    app: FastAPI,
    poll_interval: int,
    batch_size: int,
) -> None:
    """Run the Scheduler batch loop at the configured interval."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                config = _settings_svc.config
                paperless_client: PaperlessNGXClient | None = app.state.paperless_client
                manual_svc: ManualAnalysisService | None = app.state.manual_analysis_svc

                if paperless_client is None or manual_svc is None:
                    logger.warning("Scheduler skipped: services not configured.")
                    await asyncio.sleep(poll_interval)
                    continue

                inbox_tag_id = config.inbox_tag_id

                async def fetch_inbox_docs() -> list[int]:
                    import httpx
                    url = f"{paperless_client._base_url}/api/documents/"
                    params: dict[str, Any] = {"page_size": 100}
                    if inbox_tag_id is not None:
                        params["tags__id__in"] = inbox_tag_id
                    async with httpx.AsyncClient(
                        headers=paperless_client._headers, timeout=30
                    ) as client:
                        resp = await client.get(url, params=params)
                        resp.raise_for_status()
                        data = resp.json()
                    return [d["id"] for d in data.get("results", [])]

                async def submit_for_analysis(doc_id: int) -> Any:
                    try:
                        suggestion = await manual_svc.analyze(doc_id)
                        from backend.approval_queue import ApprovalQueueService
                        queue_svc = ApprovalQueueService(session)
                        enqueued = await queue_svc.enqueue(suggestion)
                        if config.auto_apply:
                            create_missing = (
                                config.tag_creation_policy == "allow_new"
                                or config.correspondent_creation_policy == "allow_new"
                                or config.doctype_creation_policy == "allow_new"
                            )
                            await queue_svc.approve(
                                enqueued.id, merge_tags=True, create_missing=create_missing,
                            )
                            logger.info("Scheduler auto-approved suggestion for document %d.", doc_id)
                        else:
                            logger.info("Scheduler enqueued suggestion for document %d.", doc_id)
                    except Exception:
                        logger.exception("Scheduler analysis failed for doc %d", doc_id)

                scheduler = Scheduler(
                    session, fetch_inbox_docs, submit_for_analysis, batch_size
                )
                batches = await scheduler.run_batch()
                if batches:
                    total = sum(len(b) for b in batches)
                    logger.info("Scheduler processed %d documents in %d batches.", total, len(batches))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler loop error")

        await asyncio.sleep(poll_interval)


async def _background_index(
    paperless_client: PaperlessNGXClient,
    vector_store: ChromaVectorStore,
    config: Any,
) -> None:
    """Index processed documents into the vector store in the background.

    Fetches all documents from Paperless NGX (excluding the inbox tag),
    and upserts those not already in the store.
    """
    import httpx

    try:
        existing_count = vector_store.count()
        logger.info("Vector store has %d documents. Starting background index...", existing_count)

        base = paperless_client._base_url
        headers = paperless_client._headers
        inbox_tag_id = config.inbox_tag_id
        indexed = 0

        # Fetch entity name lookups for metadata enrichment
        tag_id_to_name: dict[int, str] = {}
        corr_id_to_name: dict[int, str] = {}
        dt_id_to_name: dict[int, str] = {}

        async with httpx.AsyncClient(headers=headers, timeout=30) as lookup_client:
            for entity, lookup in [("tags", tag_id_to_name), ("correspondents", corr_id_to_name), ("document_types", dt_id_to_name)]:
                eurl: str | None = f"{base}/api/{entity}/?page_size=100"
                while eurl:
                    r = await lookup_client.get(eurl)
                    if r.status_code != 200:
                        break
                    d = r.json()
                    for item in d.get("results", []):
                        lookup[item["id"]] = item.get("name", "")
                    eurl = d.get("next")

        url: str | None = f"{base}/api/documents/?page_size=50&ordering=-added"
        async with httpx.AsyncClient(headers=headers, timeout=60) as client:
            while url:
                resp = await client.get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
                for doc in data.get("results", []):
                    doc_id = doc["id"]
                    doc_tags = doc.get("tags", [])
                    # Skip docs with the inbox tag (unprocessed)
                    if inbox_tag_id and inbox_tag_id in doc_tags:
                        continue
                    content = doc.get("content", "")
                    if not content:
                        continue
                    # Resolve tag/correspondent/doctype names for metadata
                    meta = {
                        "title": doc.get("title", ""),
                        "tags": [tag_id_to_name.get(tid, "") for tid in doc_tags if tag_id_to_name.get(tid)],
                        "correspondent": corr_id_to_name.get(doc.get("correspondent") or 0, ""),
                        "document_type": dt_id_to_name.get(doc.get("document_type") or 0, ""),
                    }
                    try:
                        await vector_store.upsert(doc_id, content, meta)
                        indexed += 1
                    except Exception:
                        logger.debug("Failed to index document %d", doc_id, exc_info=True)
                url = data.get("next")
                # Yield to event loop periodically
                await asyncio.sleep(0.1)

        logger.info("Background indexing complete: %d documents indexed.", indexed)
    except Exception:
        logger.warning("Background indexing failed.", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    logger.info("Paperless IQ starting up")

    # Ensure DB tables exist (dev convenience; production uses Alembic)
    from backend.database import engine
    from backend.orm_models import Base  # noqa: F401 — registers all ORM models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Load persisted settings from DB (seeds from env vars on first run)
    await _settings_svc.load_from_db()

    # Initialize all app.state attributes to safe defaults
    app.state.providers = None
    app.state.paperless_client = None
    app.state.manual_analysis_svc = None
    app.state.rate_limiter = RateLimiter()
    app.state.inbox_task = None
    app.state.scheduler_task = None
    app.state.vector_store = None

    config = _settings_svc.config
    secret_key = os.environ.get("SECRET_KEY", "")

    # Build LLM providers (graceful degradation if credentials missing)
    providers: dict[str, Any] | None = None
    try:
        providers = build_providers(config, secret_key)
        app.state.providers = providers
        logger.info("LLM providers initialized: %s", list(providers.keys()))
    except Exception:
        logger.warning("Could not initialize LLM providers — analysis will be unavailable.", exc_info=True)

    # Create Paperless NGX client (graceful degradation if env vars missing)
    paperless_url = os.environ.get("PAPERLESS_URL", "")
    paperless_token = os.environ.get("PAPERLESS_TOKEN", "")
    paperless_client: PaperlessNGXClient | None = None
    try:
        if paperless_url and paperless_token:
            paperless_client = PaperlessNGXClient(paperless_url, paperless_token)
            app.state.paperless_client = paperless_client
            logger.info("Paperless NGX client initialized for %s", paperless_url)
        else:
            logger.warning(
                "PAPERLESS_URL or PAPERLESS_TOKEN not set — Paperless NGX integration disabled."
            )
    except Exception:
        logger.warning("Could not create Paperless NGX client.", exc_info=True)

    # Create ManualAnalysisService if both providers and client are available
    if providers and paperless_client:
        # Initialize vector store for smart entity selection
        try:
            from backend.providers.ollama_provider import OllamaProvider as _OllamaEmbed
            embed_model = config.embedding_model or "nomic-embed-text"
            ollama_url = config.ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
            embed_provider = _OllamaEmbed(base_url=ollama_url, model=embed_model)
            vector_store = ChromaVectorStore(
                llm_provider=embed_provider,
                persist_directory="/data/chroma",
            )
            app.state.vector_store = vector_store
            logger.info("Vector store initialized (ChromaDB, embedding model: %s).", embed_model)
        except Exception:
            logger.warning("Could not initialize vector store — smart entity selection disabled.", exc_info=True)
            vector_store = None

        try:
            app.state.manual_analysis_svc = ManualAnalysisService(
                config, providers, paperless_client, vector_store=vector_store
            )
            logger.info("ManualAnalysisService initialized.")
        except Exception:
            logger.warning("Could not create ManualAnalysisService.", exc_info=True)

        # Start background indexing of existing processed documents
        if vector_store and paperless_client:
            asyncio.create_task(_background_index(paperless_client, vector_store, config))

    # Start automation tasks if enabled
    if config.automation_enabled:
        logger.info("Automation enabled — starting inbox monitor and scheduler.")
        app.state.inbox_task = asyncio.create_task(
            _inbox_polling_loop(app, config.poll_interval_seconds)
        )
        if config.schedule_cron:
            app.state.scheduler_task = asyncio.create_task(
                _scheduler_loop(app, config.poll_interval_seconds, config.batch_size)
            )

    yield

    # Shutdown: cancel automation tasks
    for task_name in ("inbox_task", "scheduler_task"):
        task: asyncio.Task[Any] | None = getattr(app.state, task_name, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info("Cancelled %s.", task_name)

    logger.info("Paperless IQ shutting down")


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


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate-limit requests to Paperless NGX proxy and document endpoints."""
    path = request.url.path
    if path.startswith("/api/paperless/") or path == "/api/documents":
        rate_limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if rate_limiter is not None:
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = rate_limiter.check(client_ip)
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
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
    merge_tags: bool = False
    create_missing: bool = False


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
    request: Request,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
    body: ApproveBody = Body(default_factory=ApproveBody),
) -> MetadataSuggestion:
    """Approve a suggestion, optionally with field edits."""
    try:
        result = await svc.approve(
            suggestion_id,
            edits=body.edits,
            merge_tags=body.merge_tags,
            create_missing=body.create_missing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    # Index the approved document into the vector store for future similarity queries
    vs = getattr(request.app.state, "vector_store", None)
    pc = getattr(request.app.state, "paperless_client", None)
    if vs and pc:
        try:
            content = await pc.get_document_ocr_text(result.document_id)
            if content:
                meta = {
                    "title": result.title or "",
                    "tags": result.tags,
                    "correspondent": result.correspondent or "",
                    "document_type": result.document_type or "",
                }
                await vs.upsert(result.document_id, content, meta)
        except Exception:
            logger.debug("Post-approve indexing failed for doc %d", result.document_id, exc_info=True)

    return result


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
    request: Request,
    q: str = Query(..., min_length=1, description="Natural language query"),
    top_n: int = Query(default=5, ge=1, le=50),
) -> dict:
    """Search the document archive using semantic similarity."""
    vs = getattr(request.app.state, "vector_store", None)
    if vs is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store not configured. Enable smart entity selection in settings.",
        )
    try:
        results = await vs.query(q, top_n)
        return {
            "results": [r.model_dump(mode="json") for r in results],
            "query": q,
            "top_n": top_n,
        }
    except Exception as exc:
        logger.exception("Semantic search failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}")


class DiscoverBody(BaseModel):
    question: str
    top_n: int = 5


@app.post("/api/discover", tags=["search"])
async def discover(body: DiscoverBody, request: Request) -> dict:
    """RAG-powered document discovery: find relevant docs and answer the question.

    1. Embeds the question and finds similar documents via vector store
    2. Builds a context from the top-N document passages
    3. Sends the question + context to the LLM for a grounded answer with quotes
    """
    vs = getattr(request.app.state, "vector_store", None)
    if vs is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store not available.",
        )
    providers = getattr(request.app.state, "providers", None)
    if not providers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM provider not configured.",
        )

    config = _settings_svc.config
    provider = providers.get(config.llm_provider)
    if provider is None:
        raise HTTPException(status_code=503, detail="LLM provider not available.")

    try:
        # Get raw chunks for richer context (multiple chunks per document possible)
        chunks = await vs.query_chunks(body.question, body.top_n * 3)
        # Also get grouped results for the source list
        results = await vs.query(body.question, body.top_n)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector search failed: {exc}")

    if not results:
        return {
            "answer": "No relevant documents found for your question.",
            "sources": [],
            "question": body.question,
        }

    # Build context from the best chunks (may include multiple from same doc)
    context_parts: list[str] = []
    for i, chunk in enumerate(chunks[:body.top_n * 2]):
        passage = chunk["passage"] or ""
        if passage:
            context_parts.append(
                f"[Document: \"{chunk['title']}\" (ID {chunk['document_id']})]\n{passage}"
            )

    # Build source list (grouped by document)
    sources: list[dict] = []
    for r in results:
        sources.append({
            "document_id": r.document_id,
            "title": r.document_title,
            "score": round(r.score, 3),
            "deeplink_url": r.deeplink_url,
            "snippet": (r.passage or "")[:500],
        })

    context = "\n\n".join(context_parts)
    prompt = (
        "You are a helpful document assistant. Answer the user's question based ONLY on the "
        "provided document excerpts. Include direct quotes from the documents to support your answer. "
        "Cite documents by their title. If the documents don't contain enough information to answer, "
        "say so clearly.\n\n"
        f"Documents:\n{context}\n\n"
        f"Question: {body.question}\n\n"
        "Answer (include quotes from the documents):"
    )

    try:
        answer = await provider.complete(prompt, 2048)
    except Exception as exc:
        logger.exception("Discovery LLM call failed")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {exc}")

    return {
        "answer": answer,
        "sources": sources,
        "question": body.question,
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
async def manual_analyze(body: AnalyzeBody, request: Request) -> dict:
    """Trigger manual analysis for a single document with optional overrides.

    Overrides apply to this run only and do not change global settings.
    """
    svc: ManualAnalysisService | None = request.app.state.manual_analysis_svc
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis service not configured. Configure an LLM provider in settings.",
        )
    try:
        suggestion = await svc.analyze(
            document_id=body.document_id,
            provider_override=body.provider,
            model_override=body.model,
            mode_override=body.mode,
        )
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not connect to LLM provider: {exc}",
        )
    except Exception as exc:
        logger.exception("Analysis failed for document %d", body.document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {exc}",
        )
    return suggestion.model_dump(mode="json")


@app.get("/api/documents", tags=["documents"])
async def list_documents(
    request: Request,
    tag_id: int | None = Query(default=None, description="Filter by tag ID"),
    correspondent_id: int | None = Query(default=None, description="Filter by correspondent ID"),
    document_type_id: int | None = Query(default=None, description="Filter by document type ID"),
    query: str | None = Query(default=None, alias="query", description="Full-text search"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    """List/search documents from Paperless NGX."""
    import os
    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Paperless NGX not configured. Set PAPERLESS_URL and PAPERLESS_TOKEN.")
    import httpx
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if tag_id is not None:
        params["tags__id__in"] = tag_id
    if correspondent_id is not None:
        params["correspondent__id"] = correspondent_id
    if document_type_id is not None:
        params["document_type__id"] = document_type_id
    if query:
        params["query"] = query
    # Forward custom field filters (e.g. custom_fields__5=value) to Paperless NGX
    for key, value in request.query_params.items():
        if key.startswith("custom_fields__"):
            params[key] = value
    async with httpx.AsyncClient(headers={"Authorization": f"Token {paperless_token}"}, timeout=30) as client:
        resp = await client.get(f"{paperless_url.rstrip('/')}/api/documents/", params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Paperless NGX request failed")
        data = resp.json()
    results = data.get("results", [])
    return {
        "items": [{"id": d["id"], "title": d.get("title", ""), "correspondent": d.get("correspondent"),
                    "document_type": d.get("document_type"), "tags": d.get("tags", []),
                    "created": d.get("created"), "added": d.get("added")} for d in results],
        "total": data.get("count", len(results)),
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Paperless NGX metadata proxy endpoints
# ---------------------------------------------------------------------------

async def _paperless_list(entity: str) -> list[dict]:
    """Fetch all entities of a given type from Paperless NGX with pagination."""
    import os
    import httpx
    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Paperless NGX not configured. Set PAPERLESS_URL and PAPERLESS_TOKEN.")
    items: list[dict] = []
    url: str | None = f"{paperless_url.rstrip('/')}/api/{entity}/?page_size=100"
    async with httpx.AsyncClient(headers={"Authorization": f"Token {paperless_token}"}, timeout=30) as client:
        while url:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Paperless NGX {entity} request failed")
            data = resp.json()
            for item in data.get("results", []):
                items.append({"id": item["id"], "name": item.get("name", "")})
            url = data.get("next")
    return items


@app.get("/api/paperless/tags", tags=["paperless"])
async def list_tags() -> list[dict]:
    """List all tags from Paperless NGX."""
    return await _paperless_list("tags")


@app.get("/api/paperless/correspondents", tags=["paperless"])
async def list_correspondents() -> list[dict]:
    """List all correspondents from Paperless NGX."""
    return await _paperless_list("correspondents")


@app.get("/api/paperless/document_types", tags=["paperless"])
async def list_document_types() -> list[dict]:
    """List all document types from Paperless NGX."""
    return await _paperless_list("document_types")


@app.get("/api/paperless/custom_fields", tags=["paperless"])
async def list_custom_fields() -> list[dict]:
    """List all custom fields from Paperless NGX."""
    import os
    import httpx
    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Paperless NGX not configured.")
    items: list[dict] = []
    url: str | None = f"{paperless_url.rstrip('/')}/api/custom_fields/?page_size=100"
    async with httpx.AsyncClient(headers={"Authorization": f"Token {paperless_token}"}, timeout=30) as client:
        while url:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Paperless NGX custom_fields request failed")
            data = resp.json()
            for item in data.get("results", []):
                items.append({"id": item["id"], "name": item.get("name", ""), "data_type": item.get("data_type", "")})
            url = data.get("next")
    return items


@app.get("/api/paperless/storage_paths", tags=["paperless"])
async def list_storage_paths() -> list[dict]:
    """List all storage paths from Paperless NGX."""
    import os
    import httpx
    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Paperless NGX not configured.")
    items: list[dict] = []
    url: str | None = f"{paperless_url.rstrip('/')}/api/storage_paths/?page_size=100"
    async with httpx.AsyncClient(headers={"Authorization": f"Token {paperless_token}"}, timeout=30) as client:
        while url:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Paperless NGX storage_paths request failed")
            data = resp.json()
            for item in data.get("results", []):
                items.append({"id": item["id"], "name": item.get("name", "")})
            url = data.get("next")
    return items


@app.get("/api/paperless/test", tags=["paperless"])
async def test_paperless_connection() -> JSONResponse:
    """Test connectivity to the configured Paperless NGX instance."""
    import httpx

    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "detail": "Paperless NGX not configured. Set PAPERLESS_URL and PAPERLESS_TOKEN."},
        )

    try:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Token {paperless_token}"}, timeout=15
        ) as client:
            resp = await client.get(f"{paperless_url.rstrip('/')}/api/")
            resp.raise_for_status()
            data = resp.json()
            version = data.get("version") or data.get("paperless_version")
            result: dict[str, str] = {"status": "ok"}
            if version:
                result["version"] = str(version)
            return JSONResponse(content=result)
    except httpx.HTTPStatusError as exc:
        detail = f"Paperless NGX returned HTTP {exc.response.status_code}"
        return JSONResponse(content={"status": "error", "detail": detail})
    except httpx.ConnectError:
        return JSONResponse(content={"status": "error", "detail": "Could not connect to Paperless NGX. Check PAPERLESS_URL."})
    except httpx.TimeoutException:
        return JSONResponse(content={"status": "error", "detail": "Connection to Paperless NGX timed out."})
    except Exception as exc:
        return JSONResponse(content={"status": "error", "detail": str(exc)})


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------


@app.get("/api/settings", tags=["settings"])
async def get_settings() -> dict:
    """Return current settings with credentials masked."""
    return _settings_svc.get_masked()


@app.put("/api/settings", tags=["settings"])
async def update_settings(request: Request, body: dict[str, Any] = Body(...)) -> dict:
    """Update settings with validation.

    After persisting the new config this endpoint re-wires live services:
    - Rebuilds LLM providers and ManualAnalysisService.
    - Starts or stops inbox/scheduler automation tasks when automation_enabled changes.
    - Rate limiter config could be extended here in the future.
    """
    old_automation = _settings_svc.config.automation_enabled

    try:
        await _settings_svc.update_and_persist(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    new_config = _settings_svc.config
    secret_key = os.environ.get("SECRET_KEY", "")

    # Re-build LLM providers with the updated config
    try:
        providers = build_providers(new_config, secret_key)
        request.app.state.providers = providers
        logger.info("Providers re-built after settings update: %s", list(providers.keys()))

        # Re-create ManualAnalysisService if Paperless client is available
        paperless_client: PaperlessNGXClient | None = getattr(
            request.app.state, "paperless_client", None
        )
        if paperless_client is not None:
            vs = getattr(request.app.state, "vector_store", None)
            request.app.state.manual_analysis_svc = ManualAnalysisService(
                new_config, providers, paperless_client, vector_store=vs
            )
            logger.info("ManualAnalysisService re-created after settings update.")
    except Exception:
        logger.warning(
            "Could not re-build providers after settings update — analysis may be unavailable.",
            exc_info=True,
        )
        request.app.state.providers = None
        request.app.state.manual_analysis_svc = None

    # Toggle automation tasks when automation_enabled changes
    new_automation = new_config.automation_enabled

    if new_automation and not old_automation:
        # Start inbox polling if not already running
        inbox_task: asyncio.Task[Any] | None = getattr(request.app.state, "inbox_task", None)
        if inbox_task is None or inbox_task.done():
            request.app.state.inbox_task = asyncio.create_task(
                _inbox_polling_loop(request.app, new_config.poll_interval_seconds)
            )
            logger.info("Inbox polling started after settings update.")

        # Start scheduler if cron is configured and not already running
        scheduler_task: asyncio.Task[Any] | None = getattr(request.app.state, "scheduler_task", None)
        if new_config.schedule_cron and (scheduler_task is None or scheduler_task.done()):
            request.app.state.scheduler_task = asyncio.create_task(
                _scheduler_loop(request.app, new_config.poll_interval_seconds, new_config.batch_size)
            )
            logger.info("Scheduler started after settings update.")

    elif not new_automation and old_automation:
        # Cancel inbox task if running
        inbox_task = getattr(request.app.state, "inbox_task", None)
        if inbox_task is not None and not inbox_task.done():
            inbox_task.cancel()
            logger.info("Inbox polling cancelled after settings update.")
        request.app.state.inbox_task = None

        # Cancel scheduler task if running
        scheduler_task = getattr(request.app.state, "scheduler_task", None)
        if scheduler_task is not None and not scheduler_task.done():
            scheduler_task.cancel()
            logger.info("Scheduler cancelled after settings update.")
        request.app.state.scheduler_task = None

    # Rate limiter: currently uses default 60/60. Could be extended here
    # if rate limit fields are added to PaperlessIQConfig.

    return _settings_svc.get_masked()


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
    await _settings_svc._persist()
    return summary


# ---------------------------------------------------------------------------
# Static frontend serving (single-container deployment)
# ---------------------------------------------------------------------------

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR / "assets"), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve the SPA index.html for any non-API route."""
        file_path = _FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_FRONTEND_DIR / "index.html")
