"""FastAPI application entry point for Paperless IQ."""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import re as _re

# Configure application logging so INFO messages from all backend modules appear
# in the container log alongside uvicorn's own access log.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s: %(message)s",
    force=True,  # override any handler uvicorn may have added first
)
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator
from uuid import UUID, uuid4

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, func, select, text, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analyzer import PaperlessNGXClient
from backend.models import VisionAnalysisResult
from backend.pdf_utils import get_page_count
from backend.approval_queue import ApprovalQueueService
from backend.audit_log import AuditLogService, rows_to_csv
from backend.auth import (
    check_login_rate_limit,
    check_webhook_secret,
    create_session,
    get_session_user,
    require_auth,
    revoke_session,
    validate_paperless_credentials,
)
from backend.auth import _is_auth_required
from backend.database import AsyncSessionLocal, get_session
from backend.keystore import get_machine_key
from backend.inbox_monitor import InboxMonitor, Scheduler
from backend.manual_analysis import ManualAnalysisService
from backend.models import MetadataSuggestion
from backend.ollama_queue import OllamaQueue, Priority
from backend.models import UserPermissions
from backend.orm_models import (
    ConversationSessionORM,
    DocumentTrackingORM,
    SuggestionORM,
    UserMemoryORM,
    UserPermissionsORM,
)
from backend.provider_registry import build_providers
from backend.rate_limiter import RateLimiter
from backend.settings_service import SettingsService
from backend.vector_store import ChromaVectorStore

logger = logging.getLogger(__name__)

# Global settings service instance
_settings_svc = SettingsService()


_CLOUD_EMBED_PROVIDERS = {"bedrock", "openai", "anthropic"}


def _embed_concurrency_for(provider_name: str) -> int:
    """Return a safe embedding concurrency for the given provider.

    Cloud APIs (Bedrock, OpenAI, Anthropic) can handle many parallel calls.
    Local Ollama should stay sequential (1) to avoid burying the server.
    """
    return 10 if provider_name in _CLOUD_EMBED_PROVIDERS else 1


def _resolve_embed_provider(config: Any, providers: dict) -> Any | None:
    """Return the right embedding provider based on config.embed_provider.

    - ollama  → fresh OllamaProvider using config.ollama_url + config.embedding_model
    - bedrock → prefers the existing BedrockProvider instance when llm_provider=bedrock;
                falls back to building a standalone BedrockProvider from stored credentials
                so you can use Bedrock embeddings with any LLM (Ollama, Anthropic, etc.)
    - openai  → reuses the OpenAIProvider instance; requires llm_provider=openai
    """
    ep = getattr(config, "embed_provider", "ollama")

    if ep == "ollama":
        from backend.providers.ollama_provider import OllamaProvider  # local provider; only load if needed
        embed_model = config.embedding_model or "nomic-embed-text"
        ollama_url = config.ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        return OllamaProvider(base_url=ollama_url, model=embed_model)

    if ep == "bedrock":
        # Case 1: LLM is also Bedrock — reuse the existing provider instance
        provider = providers.get("bedrock")
        if provider is not None:
            provider._embed_model = config.embedding_model or "amazon.titan-embed-text-v1"
            return provider

        # Case 2: LLM is something else (Ollama, Anthropic, …) — build a standalone
        # BedrockProvider from the credentials stored in llm_credentials.
        raw = getattr(config, "llm_credentials", None)
        if raw:
            try:
                import json as _json
                creds_str = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
                creds = _json.loads(creds_str)
                secret_key = get_machine_key()
                from backend.providers.encryption import encrypt_credential
                from backend.providers.bedrock import BedrockProvider
                session_token_enc = None
                if creds.get("session_token"):
                    session_token_enc = encrypt_credential(creds["session_token"], secret_key)
                return BedrockProvider(
                    region=creds["region"],
                    access_key_id_enc=encrypt_credential(creds["access_key_id"], secret_key),
                    secret_access_key_enc=encrypt_credential(creds["secret_access_key"], secret_key),
                    secret_key=secret_key,
                    model="",  # unused — this instance is embed-only
                    session_token_enc=session_token_enc,
                    embed_model=config.embedding_model or "amazon.titan-embed-text-v1",
                )
            except Exception:
                logger.warning(
                    "embed_provider='bedrock' requested but could not build a standalone "
                    "Bedrock embed provider from stored credentials. "
                    "Check that Bedrock credentials are saved in Settings.",
                    exc_info=True,
                )
        raise ValueError(
            "embed_provider='bedrock' is configured but no Bedrock credentials are stored. "
            "Go to Settings → LLM Provider and save your AWS credentials."
        )

    if ep == "openai":
        provider = providers.get("openai")
        if provider is None:
            raise ValueError(
                "embed_provider='openai' requires llm_provider='openai' as well "
                "(credentials are shared). Use 'ollama' as embed_provider to mix providers."
            )
        return provider

    return None


async def _fetch_all_inbox_doc_ids(
    paperless_client: Any,
    inbox_tag_id: int | None,
) -> list[int]:
    """Fetch ALL document IDs with the inbox tag, following pagination."""
    all_ids: list[int] = []
    base_url = f"{paperless_client._base_url}/api/documents/"
    params: dict[str, Any] = {"page_size": 100}
    if inbox_tag_id is not None:
        params["tags__id__in"] = inbox_tag_id
    async with httpx.AsyncClient(headers=paperless_client._headers, timeout=30) as client:
        first = True
        url: str | None = base_url
        while url:
            if first:
                resp = await client.get(url, params=params)
                first = False
            else:
                resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            all_ids.extend(d["id"] for d in data.get("results", []))
            url = data.get("next")
    return all_ids


async def _automation_loop(
    app: FastAPI,
    poll_interval: int,
    batch_size: int | None = None,
) -> None:
    """Unified automation loop for inbox monitoring and scheduled batch processing.

    When ``batch_size`` is None the loop acts as an inbox monitor (processes every
    document with the inbox tag on each poll).  When ``batch_size`` is an integer
    the loop runs as a scheduler (processes up to *batch_size* unanalysed documents
    per tick).
    """
    mode_label = "Scheduler" if batch_size is not None else "Inbox polling"
    while True:
        try:
            async with AsyncSessionLocal() as session:
                config = _settings_svc.config
                paperless_client: PaperlessNGXClient | None = app.state.paperless_client
                manual_svc: ManualAnalysisService | None = app.state.manual_analysis_svc

                if paperless_client is None or manual_svc is None:
                    logger.warning("%s skipped: services not configured.", mode_label)
                    await asyncio.sleep(poll_interval)
                    continue

                inbox_tag_id = config.inbox_tag_id

                async def fetch_inbox_docs() -> list[int]:
                    return await _fetch_all_inbox_doc_ids(paperless_client, inbox_tag_id)

                async def submit_for_analysis(doc_id: int) -> Any:
                    try:
                        oq = getattr(app.state, "ollama_queue", None)
                        if oq:
                            suggestion = await oq.submit(
                                Priority.ANALYSIS,
                                lambda did=doc_id: manual_svc.analyze(did),
                                label=f"Auto-analyzing doc {doc_id}",
                            )
                        else:
                            suggestion = await manual_svc.analyze(doc_id)
                        queue_svc = ApprovalQueueService(session)
                        enqueued = await queue_svc.enqueue(suggestion)
                        if config.auto_apply:
                            # LLM now outputs the complete desired tag set (current state
                            # was passed to it), so merge_tags=False is correct.
                            # creation policies filter unknown entities before enqueue;
                            # allow_new policies leave them for creation at approve time.
                            create_missing = (
                                config.tag_creation_policy == "allow_new"
                                or config.correspondent_creation_policy == "allow_new"
                                or config.doctype_creation_policy == "allow_new"
                            )
                            await queue_svc.approve(
                                enqueued.id, merge_tags=False, create_missing=create_missing,
                            )
                            logger.info("%s auto-approved suggestion for doc %d.", mode_label, doc_id)
                        else:
                            logger.info("%s enqueued suggestion for doc %d.", mode_label, doc_id)
                    except Exception:
                        logger.exception("%s analysis failed for doc %d", mode_label, doc_id)

                if batch_size is not None:
                    scheduler = Scheduler(session, fetch_inbox_docs, submit_for_analysis, batch_size)
                    batches = await scheduler.run_batch()
                    if batches:
                        total = sum(len(b) for b in batches)
                        logger.info("Scheduler processed %d documents in %d batches.", total, len(batches))
                else:
                    monitor = InboxMonitor(session, fetch_inbox_docs, submit_for_analysis)
                    submitted = await monitor.poll()
                    if submitted:
                        logger.info("Inbox poll submitted %d documents.", len(submitted))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s loop error", mode_label)

        await asyncio.sleep(poll_interval)


async def _background_index(
    paperless_client: PaperlessNGXClient,
    vector_store: ChromaVectorStore,
    config: Any,
    queue: OllamaQueue | None = None,
) -> None:
    """Index processed documents into the vector store in the background.

    Fetches all documents from Paperless NGX (excluding the inbox tag),
    and upserts those not already in the store.
    """
    try:
        existing_count = vector_store.count()
        logger.info("Vector store has %d chunks. Starting background index...", existing_count)

        base = paperless_client._base_url
        headers = paperless_client._headers
        inbox_tag_id = config.inbox_tag_id
        indexed = 0
        total_to_index = 0

        # Fetch entity name lookups for metadata enrichment
        tag_id_to_name: dict[int, str] = {}
        corr_id_to_name: dict[int, str] = {}
        dt_id_to_name: dict[int, str] = {}
        cf_id_to_name: dict[int, str] = {}

        async with httpx.AsyncClient(headers=headers, timeout=30) as lookup_client:
            for entity, lookup in [
                ("tags", tag_id_to_name),
                ("correspondents", corr_id_to_name),
                ("document_types", dt_id_to_name),
                ("custom_fields", cf_id_to_name),
            ]:
                eurl: str | None = f"{base}/api/{entity}/?page_size=100"
                while eurl:
                    r = await lookup_client.get(eurl)
                    if r.status_code != 200:
                        break
                    d = r.json()
                    for item in d.get("results", []):
                        lookup[item["id"]] = item.get("name", "")
                    eurl = d.get("next")

        # Get total count first for progress tracking
        async with httpx.AsyncClient(headers=headers, timeout=30) as count_client:
            r = await count_client.get(f"{base}/api/documents/", params={"page_size": 1})
            if r.status_code == 200:
                total_to_index = r.json().get("count", 0)

        # Get already-indexed document IDs to skip re-embedding
        # Also checks chunk completeness: if a doc has fewer chunks than expected, re-index it
        already_indexed: set[int] = set()
        try:
            loop = asyncio.get_running_loop()
            existing = await loop.run_in_executor(
                None,
                lambda: vector_store._collection.get(include=["metadatas"])
            )
            # Count chunks per document and check against expected total
            doc_chunk_counts: dict[int, int] = {}
            doc_expected_chunks: dict[int, int] = {}
            for i, chunk_id in enumerate(existing.get("ids", [])):
                try:
                    doc_id_part = int(str(chunk_id).split("_")[0])
                    doc_chunk_counts[doc_id_part] = doc_chunk_counts.get(doc_id_part, 0) + 1
                    meta = existing.get("metadatas", [])[i] if existing.get("metadatas") else {}
                    if meta and "total_chunks" in meta:
                        doc_expected_chunks[doc_id_part] = int(meta["total_chunks"])
                except (ValueError, IndexError):
                    pass

            incomplete = 0
            for doc_id_part, count in doc_chunk_counts.items():
                expected = doc_expected_chunks.get(doc_id_part, count)
                if count >= expected:
                    already_indexed.add(doc_id_part)
                else:
                    incomplete += 1

            logger.info(
                "Vector store: %d documents fully indexed, %d incomplete (will re-index).",
                len(already_indexed), incomplete,
            )
        except Exception:
            logger.debug("Could not read existing index; will re-index all.", exc_info=True)

        # Initialise progress at the already-indexed count so the UI doesn't
        # misleadingly show 0/N on every restart when most docs are done.
        already_done = len(already_indexed)
        if queue:
            queue.set_embedding_progress(total_to_index, already_done)

        # inbox_skipped: docs seen in this run that are excluded by the inbox tag
        # (they are NOT in already_indexed, so we add them on top of already_done)
        inbox_skipped = 0
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
                    # Skip docs with the inbox tag (unprocessed); count them so
                    # progress can still reach total_to_index at the end
                    if inbox_tag_id and inbox_tag_id in doc_tags:
                        inbox_skipped += 1
                        if queue:
                            queue.set_embedding_progress(
                                total_to_index, already_done + indexed + inbox_skipped
                            )
                        continue
                    # Already indexed — don't double-count vs. already_done
                    if doc_id in already_indexed:
                        continue
                    content = doc.get("content", "")
                    if not content:
                        continue
                    # Resolve tag/correspondent/doctype/custom-field names for metadata
                    raw_cfs = doc.get("custom_fields") or []
                    custom_fields: dict[str, Any] = {}
                    for cf_entry in raw_cfs:
                        fid = cf_entry.get("field")
                        val = cf_entry.get("value")
                        name = cf_id_to_name.get(fid, "") if fid is not None else ""
                        if name and val is not None:
                            custom_fields[name] = val
                    meta = {
                        "title": doc.get("title", ""),
                        "tags": [tag_id_to_name.get(tid, "") for tid in doc_tags if tag_id_to_name.get(tid)],
                        "correspondent": corr_id_to_name.get(doc.get("correspondent") or 0, ""),
                        "document_type": dt_id_to_name.get(doc.get("document_type") or 0, ""),
                        "custom_fields": custom_fields,
                    }
                    try:
                        await vector_store.upsert(doc_id, content, meta)
                        indexed += 1
                        if queue:
                            queue.set_embedding_progress(
                                total_to_index, already_done + indexed + inbox_skipped
                            )
                    except Exception as exc:
                        exc_str = str(exc)
                        if "dimension" in exc_str.lower() and "got" in exc_str.lower():
                            logger.warning(
                                "Embedding dimension mismatch while indexing document %d: %s\n"
                                "  → The vector store was built with a different embedding model.\n"
                                "  → Go to Settings → Processing and click 'Reindex Vector Store' to rebuild it.",
                                doc_id, exc_str,
                            )
                            # Stop indexing — every remaining document will fail too
                            return
                        logger.debug("Failed to index document %d", doc_id, exc_info=True)
                        await asyncio.sleep(2.0)  # back off on failure
                url = data.get("next")
                # Yield to event loop between pages
                await asyncio.sleep(0.1)

        logger.info("Background indexing complete: %d new documents indexed, %d inbox-skipped, %d already indexed.", indexed, inbox_skipped, already_done)
        if queue:
            queue.set_embedding_progress(total_to_index, total_to_index)  # mark complete
    except Exception:
        logger.warning("Background indexing failed.", exc_info=True)


async def _audit_cleanup_loop() -> None:
    """Delete audit log entries older than the configured retention period.

    Runs once at startup and then every 24 hours. Honours the
    ``audit_retention_days`` setting (default 180 days).
    """
    while True:
        try:
            retention = _settings_svc.config.audit_retention_days
            async with AsyncSessionLocal() as db:
                deleted = await AuditLogService(db).cleanup(retention)
                if deleted:
                    logger.info("Audit log cleanup: removed %d entries older than %d days.", deleted, retention)
        except Exception:
            logger.warning("Audit log cleanup loop error", exc_info=True)
        await asyncio.sleep(86400)  # once per day


async def _session_expiry_loop(app: FastAPI) -> None:
    """Extract memories from sessions older than 24 hours, then delete them.

    Runs immediately at startup (to catch sessions that expired while the app
    was down) and then every hour. Memory extraction is skipped gracefully if
    providers are unavailable or memory is disabled.
    """
    while True:
        try:
            config = _settings_svc.config
            providers = getattr(app.state, "providers", None)
            memory_store = getattr(app.state, "memory_store", None)

            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ConversationSessionORM).where(
                        ConversationSessionORM.updated_at < cutoff
                    )
                )
                expired = result.scalars().all()

            if expired:
                logger.info("Session expiry: processing %d expired session(s)", len(expired))
                provider = providers.get(config.llm_provider) if providers else None
                for session in expired:
                    if provider and memory_store:
                        try:
                            await _extract_memories_from_session(session, provider, memory_store, config)
                        except Exception:
                            logger.warning(
                                "Session expiry: memory extraction failed for session %s",
                                session.id, exc_info=True,
                            )
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            sa_delete(ConversationSessionORM).where(
                                ConversationSessionORM.id == session.id
                            )
                        )
                        await db.commit()
        except Exception:
            logger.warning("Session expiry loop error", exc_info=True)

        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    logger.info("Paperless IQ starting up")

    # Ensure DB tables exist (dev convenience; production uses Alembic)
    from backend.database import engine
    from backend.orm_models import Base  # noqa: F401 — registers all ORM models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add columns introduced in audit log overhaul — safe for existing DBs.
        for col_ddl in [
            "ALTER TABLE audit_log ADD COLUMN document_title TEXT",
            "ALTER TABLE audit_log ADD COLUMN action_type VARCHAR(50) DEFAULT 'field_change'",
            "ALTER TABLE audit_log ADD COLUMN session_id VARCHAR(36)",
        ]:
            try:
                await conn.execute(text(col_ddl))
            except Exception:
                pass  # Column already exists — SQLite raises OperationalError

    # Load persisted settings from DB (seeds from env vars on first run)
    await _settings_svc.load_from_db()

    # Auto-generate webhook secret on first run so the callback URL is always authenticated.
    if not _settings_svc.config.webhook_secret:
        import secrets as _secrets
        await _settings_svc.update_and_persist({"webhook_secret": _secrets.token_urlsafe(24)})
        logger.info("Generated webhook secret (embedded in callback URL when webhook is registered).")

    # Initialize all app.state attributes to safe defaults
    app.state.providers = None
    app.state.paperless_client = None
    app.state.manual_analysis_svc = None
    app.state.rate_limiter = RateLimiter()
    app.state.inbox_task = None
    app.state.scheduler_task = None
    app.state.session_expiry_task = None
    app.state.vector_store = None
    app.state.ollama_queue = None
    app.state.memory_store = None

    config = _settings_svc.config
    secret_key = get_machine_key()

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
            embed_provider = _resolve_embed_provider(config, providers)
            if embed_provider is None:
                raise ValueError(
                    f"Provider '{config.llm_provider}' does not support embeddings; "
                    "smart entity selection disabled."
                )
            ep_name = getattr(config, "embed_provider", "ollama")
            vector_store = ChromaVectorStore(
                llm_provider=embed_provider,
                persist_directory="/data/chroma",
                embed_concurrency=_embed_concurrency_for(ep_name),
            )
            app.state.vector_store = vector_store
            logger.info(
                "Vector store initialized (ChromaDB, embed_provider: %s, concurrency: %d).",
                ep_name, vector_store._embed_concurrency,
            )
        except Exception:
            logger.warning("Could not initialize vector store — smart entity selection disabled.", exc_info=True)
            vector_store = None

        # Initialize the Ollama request queue
        ollama_queue = OllamaQueue(max_concurrency=1)
        ollama_queue.start()
        app.state.ollama_queue = ollama_queue

        try:
            app.state.manual_analysis_svc = ManualAnalysisService(
                config, providers, paperless_client, vector_store=vector_store
            )
            logger.info("ManualAnalysisService initialized.")
        except Exception:
            logger.warning("Could not create ManualAnalysisService.", exc_info=True)

        # Start background indexing of existing processed documents
        if vector_store and paperless_client:
            asyncio.create_task(_background_index(paperless_client, vector_store, config, ollama_queue))

        # Initialise long-term memory store (same embed provider + Chroma dir as vector store)
        try:
            from backend.memory_store import MemoryStore
            app.state.memory_store = MemoryStore(
                llm_provider=embed_provider,
                persist_directory="/data/chroma",
            )
            logger.info("Memory store initialised (embed_provider: %s).", ep_name)
        except Exception:
            logger.warning("Could not initialise memory store.", exc_info=True)

    # Start automation tasks if enabled
    if config.automation_enabled:
        logger.info("Automation enabled — starting inbox monitor and scheduler.")
        app.state.inbox_task = asyncio.create_task(
            _automation_loop(app, config.poll_interval_seconds)
        )
        if config.schedule_cron:
            app.state.scheduler_task = asyncio.create_task(
                _automation_loop(app, config.poll_interval_seconds, batch_size=config.batch_size)
            )

    # Always run the session expiry loop — extracts memories then deletes expired sessions
    app.state.session_expiry_task = asyncio.create_task(_session_expiry_loop(app))

    # Audit log cleanup loop — runs daily, honours audit_retention_days setting
    app.state.audit_cleanup_task = asyncio.create_task(_audit_cleanup_loop())

    yield

    # Shutdown: cancel automation tasks
    for task_name in ("inbox_task", "scheduler_task", "session_expiry_task", "audit_cleanup_task"):
        task: asyncio.Task[Any] | None = getattr(app.state, task_name, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info("Cancelled %s.", task_name)

    # Stop the Ollama queue
    oq = getattr(app.state, "ollama_queue", None)
    if oq:
        oq.stop()

    logger.info("Paperless IQ shutting down")


app = FastAPI(
    title="Paperless IQ",
    description="AI-powered metadata suggestions for Paperless NGX",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — restrict to configured origins in production.
# Set CORS_ALLOWED_ORIGINS to a comma-separated list of origins
# (e.g. "https://piq.example.com") for production deployments.
# Defaults to "*" for local dev / first-run convenience.
_cors_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],  # credentials + wildcard is invalid
    allow_methods=["*"],
    allow_headers=["*"],
)


_AUTH_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/me", "/api/webhook/paperless"}


async def _check_can_access(username: str) -> bool:
    """Return True if *username* has at least can_access permission.

    NG admins bypass individual flags when sync_ng_admins is enabled.
    Called from middleware — uses a fresh session, not Depends.
    """
    config = _settings_svc.config
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserPermissionsORM).where(UserPermissionsORM.username == username)
        )
        perms = result.scalar_one_or_none()
        if perms is None:
            return False
        if perms.ng_admin and config.sync_ng_admins:
            return True
        return bool(perms.can_access)


def require_perm(*perms: str):
    """Return a FastAPI dependency that checks one or more permission flags.

    The user is granted access if ANY of the listed permissions is True,
    or if they are an NG admin with sync_ng_admins enabled.
    """
    async def _dep(
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> None:
        if not _is_auth_required():
            return
        username = getattr(request.state, "user", None)
        if not username:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")
        result = await session.execute(
            select(UserPermissionsORM).where(UserPermissionsORM.username == username)
        )
        perms_row = result.scalar_one_or_none()
        config = _settings_svc.config
        if perms_row and perms_row.ng_admin and config.sync_ng_admins:
            return
        if perms_row and any(getattr(perms_row, p, False) for p in perms):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires permission: {' or '.join(perms)}",
        )
    return _dep


async def _upsert_user_permissions(username: str, is_ng_admin: bool) -> None:
    """Create or update the user_permissions row for *username* after login.

    When sync_ng_admins is enabled and the user is an NG admin, they are
    automatically granted all permissions.  Existing explicit grants are never
    downgraded — only ng_admin cache is refreshed for non-admin users.
    """
    config = _settings_svc.config
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserPermissionsORM).where(UserPermissionsORM.username == username)
        )
        perms = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if perms is None:
            if is_ng_admin and config.sync_ng_admins:
                perms = UserPermissionsORM(
                    username=username, ng_admin=True,
                    can_access=True, can_view_queue=True, can_approve=True,
                    can_analyze=True, can_discover=True, can_settings=True,
                    updated_at=now,
                )
            else:
                perms = UserPermissionsORM(
                    username=username, ng_admin=is_ng_admin, updated_at=now
                )
            session.add(perms)
        else:
            perms.ng_admin = is_ng_admin
            perms.updated_at = now
            # Auto-upgrade when a user gains NG admin status and sync is on
            if is_ng_admin and config.sync_ng_admins and not perms.can_access:
                perms.can_access = True
                perms.can_view_queue = True
                perms.can_approve = True
                perms.can_analyze = True
                perms.can_discover = True
                perms.can_settings = True

        await session.commit()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Authenticate and check base access for all /api/* routes."""
    path = request.url.path
    if path.startswith("/api/") and path not in _AUTH_EXEMPT_PATHS:
        try:
            await require_auth(request)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        # After valid token: check can_access (only when auth is enforced)
        if _is_auth_required():
            username = getattr(request.state, "user", None)
            if username and not await _check_can_access(username):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Access to Paperless IQ has not been granted for your account. Contact an administrator."},
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


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login", tags=["auth"])
async def login(body: LoginBody, request: Request) -> dict:
    """Validate credentials against Paperless NGX and issue a session token.

    Returns ``{"token": "...", "user": "..."}`` on success.
    Returns HTTP 401 on invalid credentials.
    Returns HTTP 429 when the per-IP login rate limit is exceeded.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not check_login_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a few minutes and try again.",
        )

    ok, _ng_token, is_ng_admin = await validate_paperless_credentials(body.username, body.password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    await _upsert_user_permissions(body.username, is_ng_admin)

    token = create_session(body.username)
    return {"token": token, "user": body.username}


@app.post("/api/auth/logout", tags=["auth"])
async def logout(request: Request) -> dict:
    """Revoke the current session token."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        revoke_session(auth_header[7:])
    return {"detail": "Logged out"}


@app.get("/api/auth/me", tags=["auth"])
async def auth_me(request: Request) -> dict:
    """Return current auth state.

    Response shape: ``{"user": str | null, "auth_required": bool}``

    - ``auth_required`` is True when PAPERLESS_URL is configured.
    - ``user`` is the authenticated username, or null when not logged in / open mode.
    """
    auth_required = bool(os.environ.get("PAPERLESS_URL", "").strip())
    user: str | None = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        user = get_session_user(auth_header[7:])
    return {"user": user, "auth_required": auth_required}


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


@app.post("/api/queue", tags=["queue"], response_model=MetadataSuggestion,
          dependencies=[Depends(require_perm("can_analyze"))])
async def enqueue_suggestion(
    suggestion: MetadataSuggestion,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> MetadataSuggestion:
    """Enqueue a metadata suggestion for review."""
    return await svc.enqueue(suggestion)


@app.get("/api/queue", tags=["queue"],
         dependencies=[Depends(require_perm("can_view_queue", "can_approve"))])
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


@app.post("/api/queue/{suggestion_id}/approve", tags=["queue"], response_model=MetadataSuggestion,
          dependencies=[Depends(require_perm("can_approve"))])
async def approve_suggestion(
    suggestion_id: UUID,
    request: Request,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
    body: ApproveBody = Body(default_factory=ApproveBody),
) -> MetadataSuggestion:
    """Approve a suggestion, optionally with field edits."""
    actor = getattr(request.state, "user", None)
    change_source = f"user:{actor}" if actor else "human"
    try:
        result = await svc.approve(
            suggestion_id,
            edits=body.edits,
            merge_tags=False,    # frontend computes the complete final tag set
            create_missing=True, # user reviewed and approved — always create missing entities
            change_source=change_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    # Index the approved document into the vector store in the background
    vs = getattr(request.app.state, "vector_store", None)
    pc = getattr(request.app.state, "paperless_client", None)
    if vs and pc:
        async def _index_bg() -> None:
            try:
                content = await pc.get_document_ocr_text(result.document_id)
                if content:
                    meta = {
                        "title": result.title or "",
                        "tags": result.tags,
                        "correspondent": result.correspondent or "",
                        "document_type": result.document_type or "",
                        "custom_fields": result.custom_fields or {},
                    }
                    await vs.upsert(result.document_id, content, meta)
            except Exception:
                logger.debug("Post-approve indexing failed for doc %d", result.document_id, exc_info=True)
        asyncio.create_task(_index_bg())

    return result


@app.post("/api/queue/{suggestion_id}/reject", tags=["queue"], response_model=MetadataSuggestion,
          dependencies=[Depends(require_perm("can_approve"))])
async def reject_suggestion(
    suggestion_id: UUID,
    request: Request,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> MetadataSuggestion:
    """Reject a suggestion."""
    actor = getattr(request.state, "user", None)
    change_source = f"user:{actor}" if actor else "human"
    try:
        return await svc.reject(suggestion_id, change_source=change_source)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@app.post("/api/queue/bulk-approve", tags=["queue"],
          dependencies=[Depends(require_perm("can_approve"))])
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


@app.post("/api/queue/bulk-reject", tags=["queue"],
          dependencies=[Depends(require_perm("can_approve"))])
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


@app.post("/api/queue/empty", tags=["queue"],
          dependencies=[Depends(require_perm("can_approve"))])
async def empty_queue(
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> dict:
    """Reject all pending suggestions (empty the queue)."""
    pending, total = await svc.list(status="pending", page=1, page_size=10000)
    rejected = 0
    for s in pending:
        try:
            await svc.reject(s.id)
            rejected += 1
        except ValueError:
            pass
    return {"rejected_count": rejected}


@app.get("/api/tracking/stats", tags=["queue"],
         dependencies=[Depends(require_perm("can_view_queue", "can_approve"))])
async def tracking_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Return document tracking and suggestion statistics."""
    tracked = (await session.execute(select(func.count()).select_from(DocumentTrackingORM))).scalar_one()
    pending = (await session.execute(select(func.count()).select_from(SuggestionORM).where(SuggestionORM.status == "pending"))).scalar_one()
    approved = (await session.execute(select(func.count()).select_from(SuggestionORM).where(SuggestionORM.status == "approved"))).scalar_one()
    rejected = (await session.execute(select(func.count()).select_from(SuggestionORM).where(SuggestionORM.status == "rejected"))).scalar_one()
    return {
        "tracked_documents": tracked,
        "suggestions_pending": pending,
        "suggestions_approved": approved,
        "suggestions_rejected": rejected,
    }


@app.post("/api/tracking/reset", tags=["queue"],
          dependencies=[Depends(require_perm("can_settings"))])
async def reset_tracking(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Clear the document tracking table so all inbox documents are re-processed.

    Does NOT delete suggestions — only resets the 'seen' status so the
    inbox monitor will pick up documents again.
    """
    result = await session.execute(sa_delete(DocumentTrackingORM))
    await session.commit()
    cleared = result.rowcount
    logger.info("Reset document tracking: cleared %d entries.", cleared)
    return {"cleared": cleared}


@app.post("/api/tracking/reset-rejected", tags=["queue"],
          dependencies=[Depends(require_perm("can_settings"))])
async def reset_rejected(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Delete all rejected suggestions and clear their tracking entries.

    This allows rejected documents to be re-analyzed by the inbox monitor.
    """
    # Get document IDs of rejected suggestions
    r = await session.execute(
        select(SuggestionORM.document_id).where(SuggestionORM.status == "rejected")
    )
    rejected_doc_ids = [row[0] for row in r.all()]

    # Delete rejected suggestions
    del_result = await session.execute(
        sa_delete(SuggestionORM).where(SuggestionORM.status == "rejected")
    )
    deleted_suggestions = del_result.rowcount

    # Clear tracking for those documents so they get re-processed
    if rejected_doc_ids:
        await session.execute(
            sa_delete(DocumentTrackingORM).where(
                DocumentTrackingORM.document_id.in_(rejected_doc_ids)
            )
        )

    await session.commit()
    logger.info("Reset rejected: deleted %d suggestions, cleared tracking for %d documents.",
                deleted_suggestions, len(rejected_doc_ids))
    return {"deleted_suggestions": deleted_suggestions, "cleared_tracking": len(rejected_doc_ids)}


class ReanalyzeBody(BaseModel):
    suggestion_id: UUID


@app.post("/api/queue/reanalyze", tags=["queue"],
          dependencies=[Depends(require_perm("can_analyze"))])
async def reanalyze_queue_item(
    body: ReanalyzeBody,
    request: Request,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> dict:
    """Re-analyze a queued document: analyze fresh first, then reject old and enqueue new."""
    manual_svc: ManualAnalysisService | None = request.app.state.manual_analysis_svc
    if manual_svc is None:
        raise HTTPException(status_code=503, detail="Analysis service not configured.")

    # Get the old suggestion to find the document ID
    row = await svc._session.get(SuggestionORM, str(body.suggestion_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    doc_id = row.document_id

    # Analyze fresh FIRST — if this fails, the old suggestion stays
    try:
        queue: OllamaQueue | None = getattr(request.app.state, "ollama_queue", None)
        if queue:
            suggestion = await queue.submit(
                Priority.ANALYSIS,
                lambda: manual_svc.analyze(doc_id),
                label=f"Re-analyzing doc {doc_id}",
            )
        else:
            suggestion = await manual_svc.analyze(doc_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Re-analysis failed (original kept): {exc}")

    # Only reject the old one after successful analysis
    try:
        await svc.reject(body.suggestion_id)
    except ValueError:
        pass

    enqueued = await svc.enqueue(suggestion)
    return enqueued.model_dump(mode="json")


@app.post("/api/queue/reanalyze-all", tags=["queue"],
          dependencies=[Depends(require_perm("can_analyze"))])
async def reanalyze_all_queue(
    request: Request,
    svc: Annotated[ApprovalQueueService, Depends(_queue_service)],
) -> dict:
    """Re-analyze all pending queue items in the background.

    Each item is re-analyzed individually: the old suggestion is only
    rejected after the new analysis succeeds.
    """
    manual_svc: ManualAnalysisService | None = request.app.state.manual_analysis_svc
    if manual_svc is None:
        raise HTTPException(status_code=503, detail="Analysis service not configured.")

    pending, _ = await svc.list(status="pending", page=1, page_size=10000)
    items = [(s.id, s.document_id) for s in pending]

    oq: OllamaQueue | None = getattr(request.app.state, "ollama_queue", None)

    async def _reanalyze_bg() -> None:
        for old_id, doc_id in items:
            try:
                if oq:
                    suggestion = await oq.submit(
                        Priority.ANALYSIS,
                        lambda did=doc_id: manual_svc.analyze(did),
                        label=f"Re-analyzing doc {doc_id}",
                    )
                else:
                    suggestion = await manual_svc.analyze(doc_id)
                async with AsyncSessionLocal() as session:
                    q = ApprovalQueueService(session)
                    # Reject old only after successful analysis
                    try:
                        await q.reject(old_id)
                    except ValueError:
                        pass
                    await q.enqueue(suggestion)
                    logger.info("Re-analyzed doc %d successfully.", doc_id)
            except Exception:
                logger.exception("Re-analysis failed for doc %d (original kept)", doc_id)

    asyncio.create_task(_reanalyze_bg())
    return {"detail": f"Re-analyzing {len(items)} documents in background."}


@app.get("/api/documents/{document_id}/tags", tags=["documents"])
async def get_document_existing_tags(document_id: int, request: Request) -> list[str]:
    """Fetch the existing tag names for a document from Paperless NGX."""
    pc = getattr(request.app.state, "paperless_client", None)
    if not pc:
        raise HTTPException(status_code=503, detail="Paperless NGX not configured.")
    try:
        async with httpx.AsyncClient(headers=pc._headers, timeout=15) as client:
            resp = await client.get(f"{pc._base_url}/api/documents/{document_id}/")
            resp.raise_for_status()
            doc = resp.json()
            tag_ids = doc.get("tags", [])
            if not tag_ids:
                return []
            # Resolve IDs to names
            tag_names: list[str] = []
            all_tags = (await client.get(f"{pc._base_url}/api/tags/?page_size=1000")).json().get("results", [])
            id_to_name = {t["id"]: t["name"] for t in all_tags}
            for tid in tag_ids:
                name = id_to_name.get(tid)
                if name:
                    tag_names.append(name)
            return tag_names
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/documents/{document_id}/preview", tags=["documents"])
async def proxy_document_preview(document_id: int, request: Request) -> Response:
    """Proxy the document preview (PDF/image) from Paperless NGX.

    The frontend fetches this with an Authorization header, creates a Blob URL,
    and embeds it in an iframe — avoiding any direct cross-origin auth issues.
    """
    pc = getattr(request.app.state, "paperless_client", None)
    if not pc:
        raise HTTPException(status_code=503, detail="Paperless NGX not configured.")
    try:
        async with httpx.AsyncClient(headers=pc._headers, timeout=60) as client:
            resp = await client.get(f"{pc._base_url}/api/documents/{document_id}/preview/")
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "application/octet-stream")
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={"Content-Disposition": "inline"},
            )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Could not fetch preview from Paperless NGX.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/documents/{document_id}/thumb", tags=["documents"])
async def proxy_document_thumb(document_id: int, request: Request) -> Response:
    """Proxy the document thumbnail (JPEG) from Paperless NGX."""
    pc = getattr(request.app.state, "paperless_client", None)
    if not pc:
        raise HTTPException(status_code=503, detail="Paperless NGX not configured.")
    try:
        async with httpx.AsyncClient(headers=pc._headers, timeout=15) as client:
            resp = await client.get(f"{pc._base_url}/api/documents/{document_id}/thumb/")
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="Could not fetch thumbnail from Paperless NGX.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
    action_type: str | None = Query(default=None),
    field_name: str | None = Query(default=None),
    document_title: str | None = Query(default=None, description="Substring match on document title"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Query audit log entries with optional filters."""
    items, total = await svc.query(
        document_id=document_id,
        date_from=date_from,
        date_to=date_to,
        change_source=change_source,
        action_type=action_type,
        field_name=field_name,
        document_title_pattern=document_title,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [e.model_dump(mode="json") for e in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/audit/export", tags=["audit"],
         dependencies=[Depends(require_perm("can_settings"))])
async def export_audit_log(
    svc: Annotated[AuditLogService, Depends(_audit_service)],
    document_id: int | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    change_source: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    field_name: str | None = Query(default=None),
    document_title: str | None = Query(default=None),
    fmt: str = Query(default="csv", pattern="^(csv|json)$"),
) -> Response:
    """Export filtered audit log entries as CSV or JSON."""
    rows = await svc.export_rows(
        document_id=document_id,
        date_from=date_from,
        date_to=date_to,
        change_source=change_source,
        action_type=action_type,
        field_name=field_name,
        document_title_pattern=document_title,
    )
    if fmt == "csv":
        content = rows_to_csv(rows)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
        )
    import json as _json_mod
    content_json = _json_mod.dumps([e.model_dump(mode="json") for e in rows], indent=2, default=str)
    return Response(
        content=content_json,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=audit_log.json"},
    )


# ---------------------------------------------------------------------------
# Semantic Search endpoint
# ---------------------------------------------------------------------------


@app.get("/api/search", tags=["search"],
         dependencies=[Depends(require_perm("can_discover"))])
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


# How many recent turns to keep verbatim before compressing older ones.
_DISCOVER_VERBATIM_WINDOW = 8


async def _extract_memories_from_session(session, provider, memory_store, config) -> int:
    """Extract memorable facts from a conversation session and persist them.

    Called from two paths: explicit session close (DELETE /api/discover/sessions/{id})
    and the periodic _session_expiry_loop (sessions older than 24 hours).
    Returns the number of memories created or updated.
    """
    if not getattr(config, "memory_enabled", True):
        return 0
    if memory_store is None:
        return 0

    # Build the full conversation text (summary + verbatim turns)
    parts: list[str] = []
    if getattr(session, "summary", None):
        parts.append(f"[Earlier summary]: {session.summary}")
    for t in (session.turns or []):
        role = "User" if t.get("role") == "user" else "Assistant"
        parts.append(f"{role}: {t.get('content', '')[:600]}")

    if not parts:
        return 0

    extraction_prompt = (
        "Analyze this conversation and extract memorable facts about the user's document archive.\n"
        "Output ONLY concrete, specific facts useful for future conversations — one per line.\n"
        "Each fact should be concise (under 120 characters). "
        "Skip questions, greetings, and vague statements.\n"
        "If no memorable facts were established, output exactly: NONE\n\n"
        "Good examples:\n"
        "- Telekom mobile contract ends 2025-08, 24 months, €30/month\n"
        "- Allianz home insurance #AH-123456, renews annually in March\n"
        "- Landlord: Meyer Immobilien GmbH\n\n"
        f"Conversation:\n{chr(10).join(parts)}\n\nFacts:"
    )

    try:
        raw = (await provider.complete(extraction_prompt, 400)).strip()
    except Exception:
        logger.warning("Memory extraction: LLM call failed", exc_info=True)
        return 0

    if not raw or raw.upper().startswith("NONE"):
        return 0

    facts = [
        line.strip().lstrip("-•*·▸→").strip()
        for line in raw.splitlines()
        if len(line.strip().lstrip("-•*·▸→").strip()) > 5
    ]
    if not facts:
        return 0

    count = 0
    async with AsyncSessionLocal() as db:
        for fact in facts:
            try:
                existing_id = await memory_store.find_similar(fact)
                if existing_id:
                    await db.execute(
                        sa_update(UserMemoryORM)
                        .where(UserMemoryORM.id == existing_id)
                        .values(text=fact, updated_at=datetime.now(timezone.utc))
                    )
                    await db.commit()
                    await memory_store.upsert(existing_id, fact)
                else:
                    mem = UserMemoryORM(
                        text=fact,
                        source_session_id=getattr(session, "id", None),
                        embedding_stored=True,
                    )
                    db.add(mem)
                    await db.commit()
                    await db.refresh(mem)
                    await memory_store.upsert(mem.id, fact)
                count += 1
            except Exception:
                logger.warning("Memory extraction: failed to store fact %r", fact, exc_info=True)

    logger.info("Memory extraction: %d fact(s) from session %s", count, getattr(session, "id", "?"))
    return count


class DiscoverBody(BaseModel):
    question: str
    top_n: int = 5
    # Session-based memory (Phase 2).  When provided the backend loads history
    # from the DB and persists the new turn automatically.
    session_id: str | None = None
    # Inline history fallback (Phase 1).  Used when session_id is absent.
    # Capped server-side to the last 8 entries (4 Q&A pairs).
    history: list[dict[str, str]] = []


# ---------------------------------------------------------------------------
# Discovery session management
# ---------------------------------------------------------------------------

@app.post("/api/discover/sessions", tags=["search"],
          dependencies=[Depends(require_perm("can_discover"))])
async def create_discover_session() -> dict:
    """Create a new Discovery conversation session and return its ID."""
    async with AsyncSessionLocal() as db:
        session = ConversationSessionORM()
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return {"session_id": session.id}


@app.delete("/api/discover/sessions/{session_id}", tags=["search"],
            dependencies=[Depends(require_perm("can_discover"))])
async def delete_discover_session(session_id: str, request: Request) -> dict:
    """Close a Discovery session: extract long-term memories, then delete."""
    config = _settings_svc.config
    providers = getattr(request.app.state, "providers", None)
    memory_store = getattr(request.app.state, "memory_store", None)

    async with AsyncSessionLocal() as db:
        session = await db.get(ConversationSessionORM, session_id)
        if session and providers and memory_store:
            provider = providers.get(config.llm_provider)
            if provider:
                try:
                    await _extract_memories_from_session(session, provider, memory_store, config)
                except Exception:
                    logger.warning("Session close: memory extraction failed", exc_info=True)

        await db.execute(
            sa_delete(ConversationSessionORM).where(ConversationSessionORM.id == session_id)
        )
        await db.commit()

    return {"deleted": session_id}


# ---------------------------------------------------------------------------
# Long-term memory management
# ---------------------------------------------------------------------------

class MemoryUpdateBody(BaseModel):
    text: str


@app.get("/api/memories", tags=["memory"],
         dependencies=[Depends(require_perm("can_discover"))])
async def list_memories(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    """Return all stored long-term memory facts, newest first."""
    rows = await db.execute(select(UserMemoryORM).order_by(UserMemoryORM.created_at.desc()))
    return [
        {
            "id": m.id,
            "text": m.text,
            "created_at": m.created_at.isoformat(),
            "updated_at": m.updated_at.isoformat(),
            "source_session_id": m.source_session_id,
        }
        for m in rows.scalars()
    ]


@app.put("/api/memories/{memory_id}", tags=["memory"],
         dependencies=[Depends(require_perm("can_discover"))])
async def update_memory(
    memory_id: str,
    body: MemoryUpdateBody,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Edit the text of a memory and re-embed it."""
    memory_store = getattr(request.app.state, "memory_store", None)
    mem = await db.get(UserMemoryORM, memory_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="Memory not found.")
    await db.execute(
        sa_update(UserMemoryORM)
        .where(UserMemoryORM.id == memory_id)
        .values(text=body.text.strip(), updated_at=datetime.now(timezone.utc))
    )
    await db.commit()
    if memory_store:
        try:
            await memory_store.upsert(memory_id, body.text.strip())
        except Exception:
            logger.warning("Failed to re-embed memory %s", memory_id, exc_info=True)
    return {"id": memory_id, "text": body.text.strip()}


@app.delete("/api/memories/{memory_id}", tags=["memory"],
            dependencies=[Depends(require_perm("can_discover"))])
async def delete_memory(
    memory_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Delete a single memory from both the DB and the vector store."""
    memory_store = getattr(request.app.state, "memory_store", None)
    await db.execute(sa_delete(UserMemoryORM).where(UserMemoryORM.id == memory_id))
    await db.commit()
    if memory_store:
        try:
            await memory_store.delete(memory_id)
        except Exception:
            logger.warning("Failed to delete memory %s from vector store", memory_id, exc_info=True)
    return {"deleted": memory_id}


@app.delete("/api/memories", tags=["memory"],
            dependencies=[Depends(require_perm("can_discover"))])
async def clear_all_memories(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Delete every long-term memory from both the DB and the vector store."""
    memory_store = getattr(request.app.state, "memory_store", None)
    await db.execute(sa_delete(UserMemoryORM))
    await db.commit()
    if memory_store:
        try:
            await memory_store.delete_all()
        except Exception:
            logger.warning("Failed to clear memory vector store", exc_info=True)
    return {"cleared": True}


# ---------------------------------------------------------------------------
# Document discovery (RAG)
# ---------------------------------------------------------------------------

@app.post("/api/discover", tags=["search"],
          dependencies=[Depends(require_perm("can_discover"))])
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

    # ── Retrieve relevant long-term memories ────────────────────────────────
    memory_store = getattr(request.app.state, "memory_store", None)
    injected_memories: list[str] = []
    if memory_store and getattr(config, "memory_enabled", True):
        try:
            mem_pairs = await memory_store.query(body.question, top_n=5)
            relevant_ids = [mid for mid, score in mem_pairs if score > 0.50]
            if relevant_ids:
                async with AsyncSessionLocal() as db:
                    rows = await db.execute(
                        sa_select(UserMemoryORM).where(UserMemoryORM.id.in_(relevant_ids))
                    )
                    injected_memories = [row.text for row in rows.scalars()]
        except Exception:
            logger.warning("Discovery: memory retrieval failed", exc_info=True)

    # ── Load session (Phase 2) or fall back to inline history (Phase 1) ──────
    session_id: str | None = body.session_id
    stored_turns: list[dict[str, str]] = []
    stored_summary: str | None = None

    if session_id:
        async with AsyncSessionLocal() as db:
            sess_row = await db.get(ConversationSessionORM, session_id)
            if sess_row:
                stored_turns = sess_row.turns or []
                stored_summary = sess_row.summary
            # else: unknown session ID — treat as a fresh session with that ID

        history = stored_turns
    else:
        # Phase 1 fallback: inline history from request body
        history = [
            h for h in body.history[-_DISCOVER_VERBATIM_WINDOW:]
            if h.get("role") in ("user", "assistant") and h.get("content", "").strip()
        ]

    # ── Query reformulation ─────────────────────────────────────────────────
    # Follow-up questions ("When does the first one expire?") embed poorly.
    # Ask the LLM to rewrite into a standalone search query given the context.
    search_question = body.question
    context_for_rewrite = history or stored_turns
    if context_for_rewrite:
        try:
            parts: list[str] = []
            if stored_summary:
                parts.append(f"[Earlier context]: {stored_summary}")
            parts.extend(
                f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content'][:400]}"
                for h in context_for_rewrite[-6:]
            )
            rewrite_prompt = (
                "Rewrite the latest user question as a self-contained search query "
                "for a document archive. Output ONLY the search query, nothing else.\n\n"
                f"Conversation:\n{chr(10).join(parts)}\n\n"
                f"Latest question: {body.question}\n\n"
                "Search query:"
            )
            reformulated = (await provider.complete(rewrite_prompt, 60)).strip()
            # Strip markdown formatting that some models add (**, *, ", #, etc.)
            reformulated = reformulated.strip('*"`#_ \t\n').strip("'")
            if reformulated and len(reformulated) <= 300:
                search_question = reformulated
                logger.info("Discovery: reformulated query %r → %r", body.question, search_question)
        except Exception:
            logger.warning("Discovery: query reformulation failed, using original", exc_info=True)

    try:
        # Fetch more candidates than needed — score filtering will reduce them.
        chunks = await vs.query_chunks(search_question, body.top_n * 4)
        results = await vs.query(search_question, body.top_n * 2)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector search failed: {exc}")

    # ── Relevance threshold ──────────────────────────────────────────────────
    # ChromaDB cosine distance ∈ [0, 1] for text → score = 1 - distance/2 ∈ [0.5, 1.0].
    # 0.60 ≈ cosine_similarity 0.2 — the minimum topical overlap worth sending to the LLM.
    _MIN_SCORE = 0.60
    chunks = [c for c in chunks if c["score"] >= _MIN_SCORE]
    results = [r for r in results if r.score >= _MIN_SCORE]
    # Deduplicate results to top_n after filtering (query fetched 2× as many)
    results = results[:body.top_n]
    logger.info(
        "Discovery: score filter %.2f → %d chunks, %d source docs",
        _MIN_SCORE, len(chunks), len(results),
    )
    for r in results:
        logger.info("  source doc: id=%d score=%.3f title=%r", r.document_id, r.score, r.document_title)

    if not results:
        lang = (config.target_language or "").strip()
        no_results_msg = (
            "Keine relevanten Dokumente für Ihre Frage gefunden." if lang.startswith("de")
            else "No relevant documents found for your question."
        )
        return {
            "answer": no_results_msg,
            "sources": [],
            "question": body.question,
            "session_id": session_id,
        }

    # Determine the public base URL for browser-facing deeplinks.
    # PAPERLESS_URL is the internal Docker network address; paperless_public_url is what
    # the user's browser can actually reach.
    internal_base = os.getenv("PAPERLESS_URL", "").rstrip("/")
    public_base = (config.paperless_public_url or "").rstrip("/")

    def _public_deeplink(url: str) -> str:
        """Rewrite an internal deeplink to use the public base URL."""
        if public_base and internal_base and url.startswith(internal_base):
            return public_base + url[len(internal_base):]
        return url

    # Build numbered context from the best chunks (may include multiple from same doc).
    # seen_doc_ids tracks insertion order — citation [N] always refers to seen_doc_ids[N-1].
    context_parts: list[str] = []
    seen_doc_ids: list[int] = []
    # Best chunk per document (for snippet and score in the sources panel)
    best_chunk_per_doc: dict[int, dict] = {}
    for chunk in chunks[:body.top_n * 2]:
        doc_id = chunk["document_id"]
        passage = chunk["passage"] or ""
        if not passage:
            continue
        if doc_id not in seen_doc_ids:
            seen_doc_ids.append(doc_id)
        # Keep the highest-scoring chunk per doc for the sources panel
        if doc_id not in best_chunk_per_doc or chunk["score"] > best_chunk_per_doc[doc_id]["score"]:
            best_chunk_per_doc[doc_id] = chunk
        cite_n = seen_doc_ids.index(doc_id) + 1
        context_parts.append(f"[{cite_n}] {chunk['title']} (ID {doc_id})\n{passage}")

    # Build source list in citation order so [1] → sources[0], [2] → sources[1], etc.
    # This guarantees the panel always has exactly as many entries as the highest citation number.
    sources: list[dict] = []
    for doc_id in seen_doc_ids:
        info = best_chunk_per_doc[doc_id]
        sources.append({
            "document_id": doc_id,
            "title": info.get("title", ""),
            "score": round(info.get("score", 0.0), 3),
            "deeplink_url": _public_deeplink(info.get("deeplink_url", "")),
            "snippet": (info.get("passage", ""))[:1500],
        })

    context = "\n\n".join(context_parts)
    lang = (config.target_language or "").strip()
    lang_rule = (
        f"- Always write your answer in {lang}.\n"
        if lang
        else "- Respond in the same language the user used for their question.\n"
    )

    # ── Build multi-turn messages ────────────────────────────────────────────
    # System message holds the persistent instructions + any rolling summary of
    # turns that were compressed away in earlier rounds.
    system_content = (
        "You are an expert document analyst helping a user research their personal document archive. "
        "Answer questions using ONLY the provided document excerpts — do not use outside knowledge.\n\n"
        "Formatting rules:\n"
        + lang_rule +
        "- Use **bold** for key names, amounts, dates, and important terms\n"
        "- Use bullet lists when enumerating multiple items or conditions\n"
        "- Use > blockquote for direct quotes from documents\n"
        "- Cite sources inline with bracketed numbers, e.g. [1], [2][3]\n"
        "- For contracts: identify parties, obligations, dates, amounts, termination clauses, and conditions\n"
        "- If documents partially answer the question, say what IS found and what is missing\n"
        "- If nothing relevant is found, say so directly"
    )
    if injected_memories:
        system_content += (
            "\n\nWhat I already know about your documents (from past conversations):\n"
            + "\n".join(f"- {m}" for m in injected_memories)
        )
    if stored_summary:
        system_content += (
            "\n\nContext from earlier in this conversation "
            "(summary of prior exchanges):\n" + stored_summary
        )

    # Current user message: fresh document context + the actual question
    current_user_msg = f"Documents:\n{context}\n\nQuestion: {body.question}"

    llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    llm_messages.extend(history)
    llm_messages.append({"role": "user", "content": current_user_msg})

    try:
        answer = await provider.chat(llm_messages, 2048)
    except Exception as exc:
        logger.exception("Discovery LLM call failed")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {exc}")

    # ── Persist session ──────────────────────────────────────────────────────
    # Auto-create a session ID on the first turn so memory extraction works
    # even when the frontend didn't explicitly create a session upfront.
    if session_id is None:
        session_id = str(uuid4())

    if session_id is not None:
        new_turns: list[dict[str, str]] = [
            *stored_turns,
            {"role": "user", "content": body.question},
            {"role": "assistant", "content": answer},
        ]
        new_summary = stored_summary

        # When the verbatim window overflows, compress the oldest turns.
        if len(new_turns) > _DISCOVER_VERBATIM_WINDOW:
            to_compress = new_turns[:-_DISCOVER_VERBATIM_WINDOW]
            new_turns   = new_turns[-_DISCOVER_VERBATIM_WINDOW:]
            try:
                compress_parts: list[str] = []
                if stored_summary:
                    compress_parts.append(f"[Prior summary]: {stored_summary}")
                compress_parts.append("\n".join(
                    f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content'][:500]}"
                    for t in to_compress
                ))
                summarize_prompt = (
                    "Summarize this conversation excerpt in 4-6 concise sentences. "
                    "Focus on what was asked, which documents were referenced, and any "
                    "key facts established (names, dates, amounts, contract terms). "
                    "Output ONLY the summary.\n\n"
                    + "\n\n".join(compress_parts)
                    + "\n\nSummary:"
                )
                new_summary = (await provider.complete(summarize_prompt, 300)).strip() or stored_summary
                logger.info("Discovery: compressed %d turns into summary", len(to_compress))
            except Exception:
                logger.warning("Discovery: summarisation failed, keeping old summary", exc_info=True)
                new_summary = stored_summary

        try:
            async with AsyncSessionLocal() as db:
                existing = await db.get(ConversationSessionORM, session_id)
                if existing:
                    await db.execute(
                        sa_update(ConversationSessionORM)
                        .where(ConversationSessionORM.id == session_id)
                        .values(
                            turns=new_turns,
                            summary=new_summary,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                else:
                    db.add(ConversationSessionORM(
                        id=session_id,
                        turns=new_turns,
                        summary=new_summary,
                    ))
                await db.commit()
        except Exception:
            logger.warning("Discovery: failed to persist session %s", session_id, exc_info=True)

    return {
        "answer": answer,
        "sources": sources,
        "question": body.question,
        "session_id": session_id,
    }


# ---------------------------------------------------------------------------
# Manual Analysis endpoints
# ---------------------------------------------------------------------------


class AnalyzeBody(BaseModel):
    document_id: int
    provider: str | None = None
    model: str | None = None
    mode: str | None = None


@app.post("/api/analyze", tags=["analyze"],
          dependencies=[Depends(require_perm("can_analyze"))])
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
        queue: OllamaQueue | None = getattr(request.app.state, "ollama_queue", None)
        if queue:
            suggestion = await queue.submit(
                Priority.ANALYSIS,
                lambda: svc.analyze(
                    document_id=body.document_id,
                    provider_override=body.provider,
                    model_override=body.model,
                    mode_override=body.mode,
                ),
                label=f"Analyzing doc {body.document_id}",
            )
        else:
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

    # Auto-enqueue into approval queue so the suggestion persists
    try:
        async with AsyncSessionLocal() as session:
            queue_svc = ApprovalQueueService(session)
            enqueued = await queue_svc.enqueue(suggestion)
            suggestion = enqueued  # use the enqueued version (has DB-assigned fields)
    except Exception:
        logger.warning("Failed to auto-enqueue suggestion for doc %d", body.document_id, exc_info=True)

    # Audit: record analysis trigger
    async def _audit_analyze() -> None:
        try:
            async with AsyncSessionLocal() as _db:
                actor = getattr(request.state, "user", None)
                await AuditLogService(_db).record_event(
                    action_type="analysis_triggered",
                    change_source=f"user:{actor}" if actor else "manual_analysis",
                    document_id=body.document_id,
                    new_value=f"ocr analysis via {suggestion.llm_provider}/{suggestion.llm_model}",
                )
        except Exception:
            logger.debug("Analyze audit log failed", exc_info=True)
    asyncio.create_task(_audit_analyze())

    return suggestion.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Vision analysis endpoints
# ---------------------------------------------------------------------------

class VisionAnalyzeBody(BaseModel):
    document_id: int
    include_content: bool = False
    max_pages: int | None = None


@app.post("/api/analyze/vision", tags=["analyze"],
          dependencies=[Depends(require_perm("can_analyze"))])
async def vision_analyze(body: VisionAnalyzeBody, request: Request) -> dict:
    """Analyze a document by rendering its pages as images and sending them to the LLM.

    When ``include_content`` is True, the LLM also extracts the full text and
    returns it in ``extracted_content`` alongside the original OCR text for
    the diff modal.
    """
    svc: ManualAnalysisService | None = request.app.state.manual_analysis_svc
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis service not configured. Configure an LLM provider in settings.",
        )

    pc = getattr(request.app.state, "paperless_client", None)
    if not pc:
        raise HTTPException(status_code=503, detail="Paperless NGX not configured.")

    try:
        queue: OllamaQueue | None = getattr(request.app.state, "ollama_queue", None)
        if queue:
            result: VisionAnalysisResult = await queue.submit(
                Priority.ANALYSIS,
                lambda: svc.analyze_vision(
                    document_id=body.document_id,
                    include_content=body.include_content,
                    max_pages=body.max_pages,
                ),
                label=f"Vision analysis doc {body.document_id}",
            )
        else:
            result = await svc.analyze_vision(
                document_id=body.document_id,
                include_content=body.include_content,
                max_pages=body.max_pages,
            )
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not connect to LLM provider: {exc}",
        )
    except Exception as exc:
        logger.exception("Vision analysis failed for document %d", body.document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vision analysis failed: {exc}",
        )

    # Persist the suggestion to the approval queue
    try:
        async with AsyncSessionLocal() as session:
            queue_svc = ApprovalQueueService(session)
            enqueued = await queue_svc.enqueue(result.suggestion)
            result = VisionAnalysisResult(
                suggestion=enqueued,
                extracted_content=result.extracted_content,
                original_ocr_content=result.original_ocr_content,
                page_count=result.page_count,
            )
    except Exception:
        logger.warning(
            "Failed to enqueue vision suggestion for doc %d", body.document_id, exc_info=True
        )

    return {
        "suggestion": result.suggestion.model_dump(mode="json"),
        "extracted_content": result.extracted_content,
        "original_ocr_content": result.original_ocr_content,
        "page_count": result.page_count,
    }


@app.get("/api/documents/{document_id}/page-count", tags=["documents"],
         dependencies=[Depends(require_perm("can_analyze"))])
async def get_document_page_count(document_id: int, request: Request) -> dict:
    """Return the number of pages in a document without rendering it."""
    pc = getattr(request.app.state, "paperless_client", None)
    if not pc:
        raise HTTPException(status_code=503, detail="Paperless NGX not configured.")
    try:
        pdf_bytes = await pc.get_document_bytes(document_id)
        return {"page_count": get_page_count(pdf_bytes)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class UpdateContentBody(BaseModel):
    content: str


@app.patch("/api/documents/{document_id}/content", tags=["documents"],
           dependencies=[Depends(require_perm("can_analyze"))])
async def update_document_content(
    document_id: int, body: UpdateContentBody, request: Request
) -> dict:
    """Update the content (OCR text) field of a document in Paperless NGX."""
    pc = getattr(request.app.state, "paperless_client", None)
    if not pc:
        raise HTTPException(status_code=503, detail="Paperless NGX not configured.")
    try:
        async with httpx.AsyncClient(headers=pc._headers, timeout=30) as client:
            resp = await client.patch(
                f"{pc._base_url}/api/documents/{document_id}/",
                json={"content": body.content},
            )
            resp.raise_for_status()
        return {"ok": True}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail="Failed to update document content in Paperless NGX.",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/ollama/vision-support", tags=["analyze"],
         dependencies=[Depends(require_perm("can_analyze"))])
async def ollama_vision_support(request: Request) -> dict:
    """Return whether the configured Ollama model supports vision."""
    from backend.providers.ollama_provider import OllamaProvider
    providers: dict = getattr(request.app.state, "providers", {})
    provider = providers.get("ollama")
    if not isinstance(provider, OllamaProvider):
        return {"supported": None, "reason": "Ollama not configured"}
    try:
        supported = await provider.supports_vision()
        return {"supported": supported}
    except Exception:
        return {"supported": None, "reason": "Could not check model capabilities"}


@app.get("/api/documents", tags=["documents"])
async def list_documents(
    request: Request,
    tag_ids: list[int] = Query(default=[], description="Filter by one or more tag IDs"),
    correspondent_ids: list[int] = Query(default=[], description="Filter by one or more correspondent IDs"),
    document_type_ids: list[int] = Query(default=[], description="Filter by one or more document type IDs"),
    query: str | None = Query(default=None, alias="query", description="Full-text search"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    """List/search documents from Paperless NGX."""
    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Paperless NGX not configured. Set PAPERLESS_URL and PAPERLESS_TOKEN.")
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if tag_ids:
        params["tags__id__in"] = ",".join(str(i) for i in tag_ids)
    if correspondent_ids:
        params["correspondent__id__in"] = ",".join(str(i) for i in correspondent_ids)
    if document_type_ids:
        params["document_type__id__in"] = ",".join(str(i) for i in document_type_ids)
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

async def _paperless_list(
    entity: str,
    extra_fields: list[str] | None = None,
) -> list[dict]:
    """Fetch all entities of a given type from Paperless NGX with pagination.

    ``extra_fields`` names additional JSON keys to include alongside ``id``
    and ``name`` (e.g. ``["data_type"]`` for custom fields).
    """
    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Paperless NGX not configured. Set PAPERLESS_URL and PAPERLESS_TOKEN.",
        )
    items: list[dict] = []
    url: str | None = f"{paperless_url.rstrip('/')}/api/{entity}/?page_size=100"
    async with httpx.AsyncClient(
        headers={"Authorization": f"Token {paperless_token}"}, timeout=30
    ) as client:
        while url:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Paperless NGX {entity} request failed",
                )
            data = resp.json()
            for item in data.get("results", []):
                entry: dict = {"id": item["id"], "name": item.get("name", "")}
                for field in (extra_fields or []):
                    entry[field] = item.get(field, "")
                items.append(entry)
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
    return await _paperless_list("custom_fields", extra_fields=["data_type"])


@app.get("/api/paperless/storage_paths", tags=["paperless"])
async def list_storage_paths() -> list[dict]:
    """List all storage paths from Paperless NGX."""
    return await _paperless_list("storage_paths")


@app.get("/api/paperless/test", tags=["paperless"])
async def test_paperless_connection() -> JSONResponse:
    """Test connectivity to the configured Paperless NGX instance."""
    paperless_url = os.getenv("PAPERLESS_URL", "")
    paperless_token = os.getenv("PAPERLESS_TOKEN", "")
    if not paperless_url or not paperless_token:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "detail": "Paperless NGX not configured. Set PAPERLESS_URL and PAPERLESS_TOKEN."},
        )

    try:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Token {paperless_token}"},
            timeout=15,
            follow_redirects=True,
        ) as client:
            resp = await client.get(f"{paperless_url.rstrip('/')}/api/")
            resp.raise_for_status()
            result: dict[str, str] = {"status": "ok"}
            try:
                data = resp.json()
                version = data.get("version") or data.get("paperless_version")
                if version:
                    result["version"] = str(version)
            except Exception:
                pass  # 200 OK but non-JSON body — connection is fine, version unknown
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


@app.get("/api/settings", tags=["settings"],
         dependencies=[Depends(require_perm("can_settings"))])
async def get_settings() -> dict:
    """Return current settings with credentials masked."""
    return _settings_svc.get_masked()


@app.put("/api/settings", tags=["settings"],
         dependencies=[Depends(require_perm("can_settings"))])
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
            # Update the embed provider in the vector store to match the new config
            try:
                new_embed = _resolve_embed_provider(new_config, providers)
                if new_embed is not None:
                    new_ep_name = getattr(new_config, "embed_provider", "ollama")
                    new_concurrency = _embed_concurrency_for(new_ep_name)
                    if vs is not None:
                        vs._llm = new_embed
                        # Update semaphore if concurrency changed (e.g. Ollama ↔ Bedrock)
                        if vs._embed_concurrency != new_concurrency:
                            vs._embed_sem = asyncio.Semaphore(new_concurrency)
                            vs._embed_concurrency = new_concurrency
                    else:
                        vs = ChromaVectorStore(
                            llm_provider=new_embed,
                            persist_directory="/data/chroma",
                            embed_concurrency=new_concurrency,
                        )
                        request.app.state.vector_store = vs
                    logger.info(
                        "Embed provider updated to '%s' (concurrency: %d) after settings change.",
                        new_ep_name, new_concurrency,
                    )
                else:
                    logger.info("Provider '%s' has no embedding support; vector store disabled.", new_config.llm_provider)
                    request.app.state.vector_store = None
                    vs = None
            except Exception:
                logger.warning("Could not update embed provider after settings change.", exc_info=True)
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
                _automation_loop(request.app, new_config.poll_interval_seconds)
            )
            logger.info("Inbox polling started after settings update.")

        # Start scheduler if cron is configured and not already running
        scheduler_task: asyncio.Task[Any] | None = getattr(request.app.state, "scheduler_task", None)
        if new_config.schedule_cron and (scheduler_task is None or scheduler_task.done()):
            request.app.state.scheduler_task = asyncio.create_task(
                _automation_loop(request.app, new_config.poll_interval_seconds, batch_size=new_config.batch_size)
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


@app.get("/api/config/export", tags=["config"],
         dependencies=[Depends(require_perm("can_settings"))])
async def export_config() -> dict:
    """Export configuration as JSON with credentials redacted."""
    return _settings_svc.export_config()


@app.post("/api/config/import", tags=["config"],
          dependencies=[Depends(require_perm("can_settings"))])
async def import_config(body: dict[str, Any] = Body(...)) -> dict:
    """Import configuration, skipping unknown/invalid fields."""
    summary = _settings_svc.import_config(body)
    await _settings_svc._persist()
    return summary


class TranslatePromptBody(BaseModel):
    text: str
    target_language: str


@app.post("/api/translate-prompt", tags=["config"],
          dependencies=[Depends(require_perm("can_settings"))])
async def translate_prompt(body: TranslatePromptBody, request: Request) -> dict:
    """Translate a prompt template to the target language using the configured LLM."""
    providers = getattr(request.app.state, "providers", None)
    if not providers:
        raise HTTPException(status_code=503, detail="LLM provider not configured.")
    config = _settings_svc.config
    provider = providers.get(config.llm_provider)
    if not provider:
        raise HTTPException(status_code=503, detail="LLM provider not available.")

    prompt = (
        f"Translate the following prompt template to {body.target_language}. "
        f"Preserve any {{placeholders}} exactly as they are (e.g. {{{{content}}}}). "
        f"Preserve all JSON structure and key names in English. "
        f"Only translate the natural language instructions and descriptions. "
        f"Return ONLY the translated text, nothing else.\n\n"
        f"Text to translate:\n{body.text}"
    )
    try:
        queue: OllamaQueue | None = getattr(request.app.state, "ollama_queue", None)
        if queue:
            translated = await queue.submit(Priority.ANALYSIS, lambda: provider.complete(prompt, 4096))
        else:
            translated = await provider.complete(prompt, 4096)
        return {"translated": translated.strip()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation failed: {exc}")


# ---------------------------------------------------------------------------
# Status & Reindex endpoints
# ---------------------------------------------------------------------------


@app.get("/api/status", tags=["system"])
async def get_status(request: Request) -> dict:
    """Return system status indicators for the sidebar dashboard."""
    config = _settings_svc.config
    queue: OllamaQueue | None = getattr(request.app.state, "ollama_queue", None)

    # /api/status is a public path so require_auth never sets request.state.user.
    # Detect authentication by reading the token directly from the header.
    is_authed = not _is_auth_required()
    if not is_authed:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            is_authed = bool(get_session_user(auth_header[7:]))

    # Use cached health if queue is busy or cache is fresh (< 30s)
    llm_online = False
    embed_online = False

    if queue and queue.health_cache_age < 60.0 and queue.cached_health:
        # Cache is fresh (< 60 s) — avoid a live check on every poll
        llm_online = queue.cached_health.get("llm", False)
        embed_online = queue.cached_health.get("embed", False)
    else:
        # Cache is stale — do a real health check and refresh it
        providers = getattr(request.app.state, "providers", None)
        if providers:
            provider = providers.get(config.llm_provider)
            if provider:
                try:
                    llm_online = await asyncio.wait_for(provider.health_check(), timeout=3.0)
                except Exception:
                    pass
        if queue:
            queue.update_health_cache("llm", llm_online)

        vs = getattr(request.app.state, "vector_store", None)
        if vs and hasattr(vs, "_llm"):
            try:
                embed_online = await asyncio.wait_for(vs._llm.health_check(), timeout=3.0)
            except Exception:
                pass
        if queue:
            queue.update_health_cache("embed", embed_online)

    # 3 & 4. Queue counts
    pending_count = 0
    processing_count = 0
    try:
        async with AsyncSessionLocal() as session:
            r = await session.execute(
                select(func.count()).select_from(SuggestionORM).where(SuggestionORM.status == "pending")
            )
            pending_count = r.scalar_one()
    except Exception:
        pass

    # 5. Embedding progress
    embedded_count = 0
    total_eligible = 0
    vs_store = getattr(request.app.state, "vector_store", None)
    if vs_store:
        try:
            embedded_count = vs_store.count()
        except Exception:
            pass
    # Count total documents in Paperless NGX (excluding inbox tag)
    pc = getattr(request.app.state, "paperless_client", None)
    if pc:
        try:
            inbox_tag_id = config.inbox_tag_id
            async with httpx.AsyncClient(headers=pc._headers, timeout=10) as client:
                resp = await client.get(
                    f"{pc._base_url}/api/documents/",
                    params={"page_size": 1},
                )
                if resp.status_code == 200:
                    total_eligible = resp.json().get("count", 0)
        except Exception:
            pass

    base: dict[str, Any] = {
        "llm_online": llm_online,
        "embed_online": embed_online,
    }

    if is_authed:
        base.update({
            "queue_pending": pending_count,
            "queue_processing": processing_count,
            "embedded_chunks": embedded_count,
            "total_documents": total_eligible,
            "processing": queue.processing_status if queue else {},
            "paperless_url": os.getenv("PAPERLESS_URL", ""),
            "paperless_public_url": _settings_svc.config.paperless_public_url or os.getenv("PAPERLESS_URL", ""),
        })

    return base


@app.post("/api/reindex", tags=["system"],
          dependencies=[Depends(require_perm("can_settings"))])
async def trigger_reindex(
    request: Request,
    svc: Annotated[AuditLogService, Depends(_audit_service)],
) -> dict:
    """Wipe the vector store and re-embed all documents from scratch.

    Always resets the collection first — this is required when the embedding
    model (or its output dimension) has changed since the last index run.
    """
    vs: ChromaVectorStore | None = getattr(request.app.state, "vector_store", None)
    pc = getattr(request.app.state, "paperless_client", None)
    if not vs or not pc:
        raise HTTPException(status_code=503, detail="Vector store or Paperless client not available.")

    actor = getattr(request.state, "user", None)
    change_source = f"user:{actor}" if actor else "system"
    await svc.record_event(
        action_type="reindex",
        change_source=change_source,
        new_value="full reindex started",
    )

    # Reset the collection so the new embedding model can set a fresh dimension
    await vs.reset()

    config = _settings_svc.config
    oq = getattr(request.app.state, "ollama_queue", None)
    asyncio.create_task(_background_index(pc, vs, config, oq))
    return {"detail": "Vector store cleared. Full reindex started in the background."}


class ReindexSinceRequest(BaseModel):
    modified_after: str  # ISO date string, e.g. "2025-01-15"


@app.post("/api/reindex/since", tags=["system"],
          dependencies=[Depends(require_perm("can_settings"))])
async def trigger_reindex_since(
    request: Request,
    body: ReindexSinceRequest,
    svc: Annotated[AuditLogService, Depends(_audit_service)],
) -> dict:
    """Re-embed only documents modified on or after the given date.

    Useful for catching up after a period without live webhook re-indexing.
    Does NOT wipe the existing vector store — only updates changed docs.
    """
    vs: ChromaVectorStore | None = getattr(request.app.state, "vector_store", None)
    pc: PaperlessNGXClient | None = getattr(request.app.state, "paperless_client", None)
    if not vs or not pc:
        raise HTTPException(status_code=503, detail="Vector store or Paperless client not available.")

    modified_after = body.modified_after
    base = pc._base_url
    headers = pc._headers

    # Collect matching document IDs from Paperless NGX
    doc_ids: list[int] = []
    url: str | None = (
        f"{base}/api/documents/?page_size=100&ordering=-modified"
        f"&modified__date__gte={modified_after}"
    )
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        while url:
            r = await client.get(url)
            if r.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Paperless NGX returned {r.status_code} when listing documents.",
                )
            data = r.json()
            doc_ids.extend(d["id"] for d in data.get("results", []))
            url = data.get("next")

    if not doc_ids:
        return {"detail": f"No documents modified on or after {modified_after}.", "count": 0}

    actor = getattr(request.state, "user", None)
    change_source = f"user:{actor}" if actor else "system"
    await svc.record_event(
        action_type="reindex",
        change_source=change_source,
        new_value=f"reindex-since {modified_after} ({len(doc_ids)} docs)",
    )

    oq: OllamaQueue | None = getattr(request.app.state, "ollama_queue", None)

    async def _reindex_batch() -> None:
        total = len(doc_ids)
        if oq:
            oq.set_embedding_progress(total, 0)
        for i, doc_id in enumerate(doc_ids, 1):
            await _reindex_document(doc_id, vs, pc)
            if oq:
                oq.set_embedding_progress(total, i)
        if oq:
            oq.set_embedding_progress(total, total)
        logger.info("Reindex-since %s complete: %d documents re-indexed.", modified_after, total)

    asyncio.create_task(_reindex_batch())
    return {
        "detail": f"Re-indexing {len(doc_ids)} documents modified since {modified_after} in the background.",
        "count": len(doc_ids),
    }


# ---------------------------------------------------------------------------
# Webhook: Paperless NGX live re-index on document update
# ---------------------------------------------------------------------------

_PAPERLESS_IQ_WORKFLOW_NAME = "Paperless IQ — Live Reindex"


async def _reindex_document(doc_id: int, vs: ChromaVectorStore, pc: PaperlessNGXClient) -> None:
    """Fetch current document metadata from Paperless NGX and upsert into the vector store."""
    base = pc._base_url
    headers = pc._headers

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        # Fetch entity name lookups
        tag_id_to_name: dict[int, str] = {}
        corr_id_to_name: dict[int, str] = {}
        dt_id_to_name: dict[int, str] = {}
        cf_id_to_name: dict[int, str] = {}
        for entity, lookup in [
            ("tags", tag_id_to_name),
            ("correspondents", corr_id_to_name),
            ("document_types", dt_id_to_name),
            ("custom_fields", cf_id_to_name),
        ]:
            url: str | None = f"{base}/api/{entity}/?page_size=200"
            while url:
                r = await client.get(url)
                if r.status_code != 200:
                    break
                d = r.json()
                for item in d.get("results", []):
                    lookup[item["id"]] = item.get("name", "")
                url = d.get("next")

        # Fetch document metadata
        r = await client.get(f"{base}/api/documents/{doc_id}/")
        if r.status_code != 200:
            logger.warning("Webhook reindex: document %d not found (HTTP %d).", doc_id, r.status_code)
            return
        doc = r.json()

    content = doc.get("content", "")
    if not content:
        logger.info("Webhook reindex: document %d has no OCR content, skipping.", doc_id)
        return

    doc_tags = doc.get("tags", [])
    raw_cfs = doc.get("custom_fields") or []
    custom_fields: dict[str, Any] = {}
    for cf_entry in raw_cfs:
        fid = cf_entry.get("field")
        val = cf_entry.get("value")
        name = cf_id_to_name.get(fid, "") if fid is not None else ""
        if name and val is not None:
            custom_fields[name] = val
    meta = {
        "title": doc.get("title", ""),
        "tags": [tag_id_to_name.get(tid, "") for tid in doc_tags if tag_id_to_name.get(tid)],
        "correspondent": corr_id_to_name.get(doc.get("correspondent") or 0, ""),
        "document_type": dt_id_to_name.get(doc.get("document_type") or 0, ""),
        "custom_fields": custom_fields,
    }
    await vs.upsert(doc_id, content, meta)
    logger.info("Webhook reindex: document %d re-indexed.", doc_id)


@app.post("/api/webhook/register", tags=["system"],
          dependencies=[Depends(require_perm("can_settings"))])
async def register_webhook(request: Request) -> dict:
    """Create or update the 'Paperless IQ — Live Reindex' workflow in Paperless NGX.

    Idempotent: if a workflow with that exact name already exists it is updated
    with the current callback URL; otherwise a new one is created.
    """
    pc: PaperlessNGXClient | None = getattr(request.app.state, "paperless_client", None)
    if not pc:
        raise HTTPException(status_code=503, detail="Paperless NGX client not available.")

    config = _settings_svc.config
    base_url = (
        config.paperless_iq_internal_url.rstrip("/")
        if config.paperless_iq_internal_url
        else str(request.base_url).rstrip("/")
    )
    secret = _settings_svc.config.webhook_secret
    callback_url = f"{base_url}/api/webhook/paperless?key={secret}" if secret else f"{base_url}/api/webhook/paperless"

    paperless_base = pc._base_url
    headers = {**pc._headers, "Content-Type": "application/json"}

    async with httpx.AsyncClient(headers=headers, timeout=15) as client:
        # Fetch existing workflows to check for duplicates
        r = await client.get(f"{paperless_base}/api/workflows/?page_size=100")
        if r.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Could not list Paperless NGX workflows: HTTP {r.status_code}",
            )
        existing = r.json().get("results", [])
        existing_wf: dict | None = next(
            (w for w in existing if w.get("name") == _PAPERLESS_IQ_WORKFLOW_NAME),
            None,
        )
        existing_id: int | None = existing_wf["id"] if existing_wf else None

        # When updating, preserve existing trigger/action IDs so Paperless NGX
        # patches in place rather than deleting and recreating them.
        triggers: list[dict] = [
            {"type": 2, "sources": [1, 2, 3]},  # document_added
            {"type": 3, "sources": [1, 2, 3]},  # document_updated
        ]
        actions: list[dict] = [
            {
                "type": 4,
                "webhook": {
                    "url": callback_url,
                    "include_document": False,
                    "use_params": False,
                    "as_json": True,
                    "body": '{"doc_url": "{{doc_url}}"}',
                },
            }
        ]
        if existing_wf:
            # Thread existing IDs back in so Paperless updates rather than recreates
            for i, t in enumerate(existing_wf.get("triggers", [])):
                if i < len(triggers) and t.get("id"):
                    triggers[i]["id"] = t["id"]
            for i, a in enumerate(existing_wf.get("actions", [])):
                if i < len(actions) and a.get("id"):
                    actions[i]["id"] = a["id"]
                    # Also preserve the existing webhook sub-object ID
                    existing_webhook = a.get("webhook") or {}
                    if existing_webhook.get("id"):
                        actions[i]["webhook"]["id"] = existing_webhook["id"]

        payload = {
            "name": _PAPERLESS_IQ_WORKFLOW_NAME,
            "order": 100,
            "enabled": True,
            "triggers": triggers,
            "actions": actions,
        }

        logger.info("Webhook register — sending payload: %s", payload)

        if existing_id is not None:
            r = await client.put(
                f"{paperless_base}/api/workflows/{existing_id}/",
                json=payload,
            )
            verb = "updated"
        else:
            r = await client.post(f"{paperless_base}/api/workflows/", json=payload)
            verb = "created"

        if r.status_code not in (200, 201):
            logger.error(
                "Webhook register — Paperless NGX responded HTTP %d: %s",
                r.status_code, r.text[:2000],
            )
            raise HTTPException(
                status_code=502,
                detail=f"Paperless NGX workflow {verb} failed: HTTP {r.status_code} — {r.text[:300]}",
            )

        stored = r.json()
        # Log the stored action/webhook data specifically so we can verify the URL was saved.
        for action in stored.get("actions", []):
            logger.info(
                "Webhook register — stored action id=%s type=%s webhook=%s",
                action.get("id"), action.get("type"), action.get("webhook"),
            )

    logger.info(
        "Webhook workflow %s (callback: %s).", verb, callback_url
    )
    return {
        "detail": f"Workflow '{_PAPERLESS_IQ_WORKFLOW_NAME}' {verb}.",
        "callback_url": callback_url,
        "stored_workflow": stored,
    }


@app.post("/api/webhook/paperless", tags=["system"])
async def paperless_webhook(request: Request) -> dict:
    """Receive a Paperless NGX webhook and re-index the affected document.

    This endpoint is intentionally unauthenticated so Paperless NGX can call it
    without a Paperless IQ session token. Configure a webhook secret in
    Settings → Automation → Webhook Security to restrict access.
    """
    logger.info("Webhook received from %s", request.client)

    expected = _settings_svc.config.webhook_secret or os.environ.get("WEBHOOK_SECRET", "")
    if not check_webhook_secret(request, expected):
        logger.warning(
            "Webhook rejected — key mismatch. URL key=%r, expected length=%d",
            request.query_params.get("key", "")[:8] + "…",
            len(expected),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing webhook secret.",
        )

    vs: ChromaVectorStore | None = getattr(request.app.state, "vector_store", None)
    pc: PaperlessNGXClient | None = getattr(request.app.state, "paperless_client", None)
    if not vs or not pc:
        logger.warning("Webhook received but vector store or paperless client not available; skipped.")
        return {"detail": "Vector store not available; skipped."}

    content_type = request.headers.get("content-type", "")
    doc_id: int | None = None

    if "multipart/form-data" in content_type:
        # Paperless NGX sends multipart when include_document=True.
        # Parse all form fields and log them; look for a document ID in any field.
        try:
            form = await request.form()
            fields: dict[str, str] = {}
            for key, val in form.multi_items():
                if hasattr(val, "read"):
                    fields[key] = f"<file: {getattr(val, 'filename', '?')}>"
                else:
                    fields[key] = str(val)[:500]
            logger.info("Webhook multipart fields: %s", fields)

            for key in ("document_id", "id", "pk"):
                if key in form and not hasattr(form[key], "read"):
                    doc_id = int(form[key])
                    break
            if doc_id is None:
                doc_json_str = form.get("document")
                if doc_json_str and not hasattr(doc_json_str, "read"):
                    try:
                        doc_data = _json.loads(doc_json_str)
                        doc_id = doc_data.get("id") or doc_data.get("document_id")
                    except Exception:
                        pass
        except Exception:
            logger.warning("Webhook: failed to parse multipart form.", exc_info=True)
    else:
        raw = await request.body()
        logger.info(
            "Webhook raw body (%d bytes) Content-Type=%r: %r",
            len(raw), content_type, raw[:500],
        )
        try:
            body = _json.loads(raw) if raw else {}
            # Paperless NGX double-encodes the body template as a JSON string.
            if isinstance(body, str):
                body = _json.loads(body)
        except Exception:
            logger.warning("Webhook received but body is not valid JSON.")
            return {"detail": "Invalid JSON; skipped."}
        if not isinstance(body, dict):
            logger.warning("Webhook body parsed to unexpected type %s: %r", type(body), body)
            return {"detail": "Unexpected payload type; skipped."}
        logger.info("Webhook payload: %s", body)
        raw_id = body.get("document_id") or body.get("id")
        if raw_id:
            doc_id = int(raw_id)
        elif body.get("doc_url"):
            m = _re.search(r"/documents/(\d+)", body["doc_url"])
            doc_id = int(m.group(1)) if m else None
            logger.info("Webhook extracted doc_id=%s from doc_url=%r", doc_id, body["doc_url"])

    if not doc_id:
        logger.warning("Webhook received but could not extract document_id.")
        return {"detail": "No document_id; skipped."}

    logger.info("Webhook queuing reindex of document %s.", doc_id)
    asyncio.create_task(_reindex_document(doc_id, vs, pc))

    # Fire-and-forget audit event — uses its own session to avoid coupling with request lifecycle.
    async def _audit_webhook() -> None:
        try:
            async with AsyncSessionLocal() as _db:
                await AuditLogService(_db).record_event(
                    action_type="webhook_received",
                    change_source="webhook",
                    document_id=doc_id,
                    new_value="reindex queued",
                )
        except Exception:
            logger.debug("Webhook audit log failed", exc_info=True)
    asyncio.create_task(_audit_webhook())

    return {"detail": f"Reindex of document {doc_id} queued."}


# ---------------------------------------------------------------------------
# User permissions management (/api/piq-users)
# ---------------------------------------------------------------------------

@app.get("/api/piq-users/me", tags=["users"])
async def get_my_permissions(request: Request) -> dict:
    """Return the effective permissions for the currently authenticated user.

    When auth is not required (no PAPERLESS_URL), returns a fully-permissive
    response so unauthenticated dev mode works without front-end guards.
    """
    if not _is_auth_required():
        return {
            "username": "anonymous",
            "ng_admin": True,
            "can_access": True,
            "can_view_queue": True,
            "can_approve": True,
            "can_analyze": True,
            "can_discover": True,
            "can_settings": True,
        }

    username = getattr(request.state, "user", None)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    async with AsyncSessionLocal() as db:
        row = await db.get(UserPermissionsORM, username)
        if row is None:
            return {
                "username": username,
                "ng_admin": False,
                "can_access": False,
                "can_view_queue": False,
                "can_approve": False,
                "can_analyze": False,
                "can_discover": False,
                "can_settings": False,
            }
        config = _settings_svc.config
        effective_all = row.ng_admin and config.sync_ng_admins
        return {
            "username": row.username,
            "ng_admin": row.ng_admin,
            "can_access": effective_all or row.can_access,
            "can_view_queue": effective_all or row.can_view_queue,
            "can_approve": effective_all or row.can_approve,
            "can_analyze": effective_all or row.can_analyze,
            "can_discover": effective_all or row.can_discover,
            "can_settings": effective_all or row.can_settings,
        }


@app.get("/api/piq-users", tags=["users"],
         dependencies=[Depends(require_perm("can_settings"))])
async def list_piq_users(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all user permission records, merged with all Paperless NGX users.

    Users who have never logged into PIQ appear with deny-all defaults and
    has_piq_record=false so the UI can distinguish them.
    """
    result = await session.execute(select(UserPermissionsORM))
    rows = result.scalars().all()
    config = _settings_svc.config

    piq_records: dict[str, dict] = {}
    for row in rows:
        effective_all = row.ng_admin and config.sync_ng_admins
        piq_records[row.username] = {
            "username": row.username,
            "ng_admin": row.ng_admin,
            "can_access": effective_all or row.can_access,
            "can_view_queue": effective_all or row.can_view_queue,
            "can_approve": effective_all or row.can_approve,
            "can_analyze": effective_all or row.can_analyze,
            "can_discover": effective_all or row.can_discover,
            "can_settings": effective_all or row.can_settings,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "has_piq_record": True,
        }

    # Merge with all Paperless NGX users so admins can pre-set permissions
    # before a user's first login. Gracefully skipped if NG is unavailable.
    pc: PaperlessNGXClient | None = getattr(request.app.state, "paperless_client", None)
    if pc:
        try:
            async with httpx.AsyncClient(headers=pc._headers, timeout=10) as client:
                url: str | None = f"{pc._base_url}/api/users/?page_size=200"
                while url:
                    r = await client.get(url)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    for ng_user in data.get("results", []):
                        uname = ng_user.get("username", "")
                        if uname and uname not in piq_records:
                            piq_records[uname] = {
                                "username": uname,
                                "ng_admin": bool(ng_user.get("is_superuser") or ng_user.get("is_staff")),
                                "can_access": False,
                                "can_view_queue": False,
                                "can_approve": False,
                                "can_analyze": False,
                                "can_discover": False,
                                "can_settings": False,
                                "updated_at": None,
                                "has_piq_record": False,
                            }
                    url = data.get("next")
        except Exception:
            logger.debug("Could not fetch Paperless NGX user list for merging.", exc_info=True)

    return sorted(piq_records.values(), key=lambda u: u["username"].lower())


class PiqUserUpdate(BaseModel):
    can_access: bool = False
    can_view_queue: bool = False
    can_approve: bool = False
    can_analyze: bool = False
    can_discover: bool = False
    can_settings: bool = False


@app.put("/api/piq-users/{username}", tags=["users"],
         dependencies=[Depends(require_perm("can_settings"))])
async def update_piq_user(
    username: str,
    body: PiqUserUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create or update permission flags for a user (upsert)."""
    row = await session.get(UserPermissionsORM, username)
    if row is None:
        row = UserPermissionsORM(username=username)
        session.add(row)
    row.can_access = body.can_access
    row.can_view_queue = body.can_view_queue
    row.can_approve = body.can_approve
    row.can_analyze = body.can_analyze
    row.can_discover = body.can_discover
    row.can_settings = body.can_settings
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"detail": f"Permissions updated for '{username}'."}


@app.delete("/api/piq-users/{username}", tags=["users"],
            dependencies=[Depends(require_perm("can_settings"))])
async def delete_piq_user(
    username: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a user's permission record (they will be denied all access on next login)."""
    row = await session.get(UserPermissionsORM, username)
    if row is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
    await session.delete(row)
    await session.commit()
    return {"detail": f"Permission record for '{username}' deleted."}


# ---------------------------------------------------------------------------
# Static frontend serving (single-container deployment)
# ---------------------------------------------------------------------------

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

_LEGACY_NAV_ICONS = {"🔍", "📋", "💬", "⚡", "📜", "⚙️"}


@app.get("/api/theme", tags=["theme"])
async def get_theme() -> dict:
    """Return current theme settings."""
    config = _settings_svc.config
    # Strip legacy emoji nav_icons so existing databases self-heal automatically.
    nav_icons = {k: v for k, v in config.theme_nav_icons.items() if v not in _LEGACY_NAV_ICONS}
    return {
        "primary_color": config.theme_primary_color,
        "sidebar_from": config.theme_sidebar_from,
        "sidebar_to": config.theme_sidebar_to,
        "font": config.theme_font,
        "font_size": config.theme_font_size,
        "text_color": config.theme_text_color,
        "bg_color": config.theme_bg_color,
        "card_color": config.theme_card_color,
        "card_alt_hex": config.theme_card_alt_hex,
        "card_alt_opacity": config.theme_card_alt_opacity,
        "nav_icons": nav_icons,
        "chip_color": config.theme_chip_color,
        "mantine_color": config.mantine_color,
        "color_scheme": config.color_scheme,
    }

if _FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR / "assets"), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> HTMLResponse:
        """Serve the SPA index.html for any non-API route.

        index.html is served with Cache-Control: no-store so browsers (Safari,
        Chrome, Firefox) always fetch the latest version after a container rebuild.
        JS/CSS assets use content-hash filenames and are served by the /assets
        StaticFiles mount — those can be cached indefinitely.
        """
        file_path = _FRONTEND_DIR / full_path
        if file_path.is_file() and full_path != "index.html":
            return FileResponse(file_path)
        html = (_FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
