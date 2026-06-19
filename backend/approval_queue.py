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
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import MetadataSuggestion
from backend.orm_models import AuditLogORM, SuggestionORM

logger = logging.getLogger(__name__)

# Simple TTL cache for entity name→ID lookups (avoids re-fetching on every approve)
_entity_cache: dict[str, tuple[float, dict[str, int]]] = {}
_CACHE_TTL = 60.0  # seconds

PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://localhost:8000")
PAPERLESS_TOKEN = os.getenv("PAPERLESS_TOKEN", "")


def _format_custom_field_value(value: Any, data_type: str) -> Any:
    """Format a custom field value to match Paperless NGX expectations.

    - monetary: must be a string like "EUR123.45" or "123.45" (2 decimal places)
    - integer: must be an int
    - float: must be a float
    - boolean: must be a bool
    - date: must be a string in YYYY-MM-DD format
    - string/url: passed as-is
    """
    if value is None:
        return value

    if data_type == "monetary":
        try:
            num = float(str(value).replace(",", ".").strip())
            return f"{num:.2f}"
        except (ValueError, TypeError):
            return str(value)

    if data_type == "integer":
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return value

    if data_type == "float":
        try:
            return float(str(value))
        except (ValueError, TypeError):
            return value

    if data_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "on")

    return value


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
        extracted_content=row.extracted_content,
        original_ocr_content=row.original_ocr_content,
        evidence_json=row.evidence_json,
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
        extracted_content=suggestion.extracted_content,
        original_ocr_content=suggestion.original_ocr_content,
        evidence_json=suggestion.evidence_json,
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

        Idempotent: if a suggestion with the same UUID already exists in the
        database (e.g. because the backend auto-enqueued it inside the
        /api/analyze endpoint before returning), the existing record is
        returned without attempting a second INSERT.

        Validates: Requirements 7.1
        """
        # Guard against double-enqueue: the /api/analyze endpoint already
        # inserts the suggestion before returning it to the caller.  If the
        # frontend (or any other code path) calls enqueue() a second time with
        # the same object, we return the already-persisted row instead of
        # raising IntegrityError on the UNIQUE constraint.
        existing = await self._session.get(SuggestionORM, str(suggestion.id))
        if existing is not None:
            logger.debug(
                "Suggestion %s already exists (status=%s); skipping duplicate enqueue.",
                existing.id, existing.status,
            )
            return _orm_to_pydantic(existing)

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
        merge_tags: bool = False,
        create_missing: bool = False,
        document_title: str | None = None,
        session_id: str | None = None,
        apply_content: bool = False,
        supersede_siblings: bool = True,
    ) -> MetadataSuggestion:
        """
        Approve a suggestion, optionally applying field edits.

        Steps:
          1. Load the suggestion from DB (must be "pending")
          2. Apply edits to the suggestion fields
          3. Write metadata to Paperless NGX via HTTP PATCH
          4. Write one AuditLogEntry per changed field + one "approved" event
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

        doc_title = document_title or row.title

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

        # Content write-back (opt-in) — only when the suggestion carries transcribed
        # content from full-document analysis and the approver kept it enabled.
        content_applied = bool(apply_content and row.extracted_content)
        if content_applied:
            patch_payload["content"] = row.extracted_content

        # Write to Paperless NGX
        await self._patch_paperless(
            row.document_id, patch_payload,
            merge_tags=merge_tags, create_missing=create_missing,
        )

        # Write audit log entries — one per changed field
        now = datetime.now(timezone.utc)
        for field in editable_fields:
            old_val = original[field]
            new_val = getattr(row, field)
            if old_val != new_val:
                audit = AuditLogORM(
                    id=str(uuid4()),
                    document_id=row.document_id,
                    document_title=doc_title,
                    field_name=field,
                    previous_value=_value_to_str(old_val),
                    new_value=_value_to_str(new_val),
                    change_source=change_source,
                    action_type="field_change",
                    session_id=session_id,
                    changed_at=now,
                    suggestion_id=row.id,
                )
                self._session.add(audit)

        # Audit the content write-back separately (content isn't an editable field).
        # Values are truncated — the full document text would bloat the audit log.
        if content_applied:
            self._session.add(AuditLogORM(
                id=str(uuid4()),
                document_id=row.document_id,
                document_title=doc_title,
                field_name="content",
                previous_value=((row.original_ocr_content or "")[:500] or None),
                new_value=(row.extracted_content or "")[:500],
                change_source=change_source,
                action_type="field_change",
                session_id=session_id,
                changed_at=now,
                suggestion_id=row.id,
            ))

        # Always write an "approved" event even when no fields changed
        approval_event = AuditLogORM(
            id=str(uuid4()),
            document_id=row.document_id,
            document_title=doc_title,
            field_name="_event",
            previous_value=None,
            new_value=f"suggestion:{row.id}",
            change_source=change_source,
            action_type="approved",
            session_id=session_id,
            changed_at=now,
            suggestion_id=row.id,
        )
        self._session.add(approval_event)

        row.status = "approved"

        # Supersede the other pending suggestions for this document: approving one
        # resolves the document, so the rest are rejected (one card → one decision).
        if supersede_siblings:
            siblings = await self._session.execute(
                select(SuggestionORM).where(
                    SuggestionORM.document_id == row.document_id,
                    SuggestionORM.status == "pending",
                    SuggestionORM.id != row.id,
                )
            )
            for sib in siblings.scalars():
                sib.status = "rejected"
                self._session.add(AuditLogORM(
                    id=str(uuid4()),
                    document_id=sib.document_id,
                    document_title=doc_title,
                    field_name="_event",
                    previous_value=None,
                    new_value=f"superseded_by:{row.id}",
                    change_source=change_source,
                    action_type="rejected",
                    session_id=session_id,
                    changed_at=now,
                    suggestion_id=sib.id,
                ))

        await self._session.commit()
        await self._session.refresh(row)
        logger.info("Approved suggestion %s for document %d.", row.id, row.document_id)
        return _orm_to_pydantic(row)

    # ------------------------------------------------------------------
    # reject
    # ------------------------------------------------------------------

    async def reject(
        self,
        suggestion_id: UUID,
        change_source: str = "human",
        document_title: str | None = None,
        session_id: str | None = None,
        record_dismissals: bool = True,
    ) -> MetadataSuggestion:
        """
        Reject a suggestion — no Paperless NGX write.

        Idempotent: rejecting an already-rejected suggestion is a no-op.

        For grooming suggestions a rejection is a permanent answer: one
        GroomingDismissalORM row is written per action in evidence_json so
        the scan never re-suggests it (unless grooming_resuggest_after_days
        elapses). ``record_dismissals=False`` skips this — used by the
        Empty Queue wipe, which clears clutter without recording judgments.

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

        if record_dismissals and row.analysis_mode == "grooming" and row.evidence_json:
            self._record_grooming_dismissals(row)

        rejection_event = AuditLogORM(
            id=str(uuid4()),
            document_id=row.document_id,
            document_title=document_title or row.title,
            field_name="_event",
            previous_value=None,
            new_value=f"suggestion:{row.id}",
            change_source=change_source,
            action_type="rejected",
            session_id=session_id,
            changed_at=datetime.now(timezone.utc),
            suggestion_id=row.id,
        )
        self._session.add(rejection_event)

        await self._session.commit()
        await self._session.refresh(row)
        logger.info("Rejected suggestion %s for document %d.", row.id, row.document_id)
        return _orm_to_pydantic(row)

    def _record_grooming_dismissals(self, row: SuggestionORM) -> None:
        """Add one GroomingDismissalORM per evidence action (no commit)."""
        from backend.orm_models import GroomingDismissalORM

        try:
            evidence = json.loads(row.evidence_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return
        for action in evidence.get("actions", []):
            entity_id = action.get("entity_id")
            if entity_id is None:
                continue
            self._session.add(GroomingDismissalORM(
                entity_type=action.get("entity_type", ""),
                entity_id=int(entity_id),
                document_id=row.document_id,
                action=action.get("action", ""),
                other_entity_id=action.get("replacement_entity_id"),
            ))

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
        # Bulk approve is an explicit multi-approve — don't supersede siblings, or
        # approving one would reject the others in the same batch.
        results: list[MetadataSuggestion] = []
        for sid in suggestion_ids:
            result = await self.approve(sid, change_source=change_source, supersede_siblings=False)
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

    async def _patch_paperless(
        self,
        document_id: int,
        payload: dict[str, Any],
        merge_tags: bool = False,
        create_missing: bool = False,
    ) -> None:
        """
        PATCH document metadata to Paperless NGX.

        Resolves entity names to IDs. When merge_tags is True, fetches the
        document's existing tags and merges them with the suggested ones.
        When create_missing is True, creates entities that don't exist yet.
        """
        if not PAPERLESS_URL or not PAPERLESS_TOKEN:
            logger.warning(
                "PAPERLESS_URL or PAPERLESS_TOKEN not set; skipping Paperless NGX write for doc %d.",
                document_id,
            )
            return

        headers = {"Authorization": f"Token {PAPERLESS_TOKEN}"}
        base = PAPERLESS_URL.rstrip("/")
        patch: dict[str, Any] = {}

        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            if payload.get("title"):
                patch["title"] = payload["title"]

            # Tags — resolve names to IDs, optionally merge with existing.
            # Use `is not None` (not truthiness) so an empty list still sets tags=[],
            # which removes all tags from the document as intended.
            if payload.get("tags") is not None:
                tag_ids = await self._resolve_or_create_entity_ids(
                    client, base, "tags", payload["tags"], create_missing
                )
                if merge_tags:
                    existing = await self._get_document_tag_ids(client, base, document_id)
                    merged = list(dict.fromkeys(existing + tag_ids))  # preserve order, dedupe
                    tag_ids = merged
                patch["tags"] = tag_ids  # always set — empty list = remove all tags

            # Correspondent
            if payload.get("correspondent"):
                corr_ids = await self._resolve_or_create_entity_ids(
                    client, base, "correspondents", [payload["correspondent"]], create_missing
                )
                if corr_ids:
                    patch["correspondent"] = corr_ids[0]

            # Document type
            if payload.get("document_type"):
                dt_ids = await self._resolve_or_create_entity_ids(
                    client, base, "document_types", [payload["document_type"]], create_missing
                )
                if dt_ids:
                    patch["document_type"] = dt_ids[0]

            if payload.get("storage_path"):
                sp_ids = await self._resolve_or_create_entity_ids(
                    client, base, "storage_paths", [payload["storage_path"]], create_missing
                )
                if sp_ids:
                    patch["storage_path"] = sp_ids[0]

            if payload.get("custom_fields"):
                cf_list = await self._resolve_custom_fields(
                    client, base, payload["custom_fields"], create_missing
                )
                if cf_list:
                    patch["custom_fields"] = cf_list

            # Document content (OCR text) — written back from full-document analysis
            # when the approver opted in. Empty/None is ignored (never wipes content).
            if payload.get("content"):
                patch["content"] = payload["content"]

            if not patch:
                logger.info("No fields to patch for document %d.", document_id)
                return

            url = f"{base}/api/documents/{document_id}/"
            try:
                resp = await client.patch(url, json=patch)
                resp.raise_for_status()
                logger.info("Patched Paperless NGX document %d.", document_id)
            except httpx.HTTPStatusError as exc:
                detail = ""
                try:
                    detail = exc.response.text
                except Exception:
                    pass
                logger.error(
                    "Failed to patch Paperless NGX document %d: %s\nPayload: %s\nResponse: %s",
                    document_id, exc, json.dumps(patch, default=str), detail,
                )
                raise ValueError(
                    f"Paperless NGX rejected the update for document {document_id}: {detail or exc}"
                ) from exc
            except httpx.HTTPError as exc:
                logger.error("Failed to patch Paperless NGX document %d: %s", document_id, exc)
                raise

    async def _get_document_tag_ids(
        self, client: httpx.AsyncClient, base_url: str, document_id: int
    ) -> list[int]:
        """Fetch the current tag IDs for a document from Paperless NGX."""
        try:
            resp = await client.get(f"{base_url}/api/documents/{document_id}/")
            resp.raise_for_status()
            return resp.json().get("tags", [])
        except Exception:
            logger.warning("Could not fetch existing tags for document %d", document_id)
            return []

    async def _resolve_or_create_entity_ids(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        entity_type: str,
        names: list[str],
        create_missing: bool = False,
    ) -> list[int]:
        """Resolve entity names to IDs. Optionally create missing entities.
        Uses a TTL cache to avoid re-fetching entity lists on every approval.
        """
        cache_key = f"{base_url}:{entity_type}"
        now = time.monotonic()
        cached = _entity_cache.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            name_to_id = cached[1]
        else:
            name_to_id = {}
            url: str | None = f"{base_url}/api/{entity_type}/?page_size=100"
            while url:
                resp = await client.get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
                for item in data.get("results", []):
                    name_to_id[item.get("name", "").lower()] = item["id"]
                url = data.get("next")
            _entity_cache[cache_key] = (now, name_to_id)

        ids: list[int] = []
        for name in names:
            eid = name_to_id.get(name.lower())
            if eid is not None:
                ids.append(eid)
            elif create_missing:
                try:
                    resp = await client.post(
                        f"{base_url}/api/{entity_type}/", json={"name": name}
                    )
                    resp.raise_for_status()
                    new_id = resp.json().get("id")
                    if new_id:
                        ids.append(new_id)
                        logger.info("Created %s %r with ID %d", entity_type, name, new_id)
                        # Invalidate cache so next resolve picks up the new entity
                        _entity_cache.pop(f"{base_url}:{entity_type}", None)
                except Exception:
                    logger.warning("Failed to create %s %r", entity_type, name, exc_info=True)
            else:
                logger.warning("Could not resolve %s name %r to an ID; skipping.", entity_type, name)
        return ids

    async def _resolve_custom_fields(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        custom_fields: dict[str, Any],
        create_missing: bool = False,
    ) -> list[dict[str, Any]]:
        """Convert a {name: value} dict to Paperless NGX [{field: id, value: val}] format.

        When create_missing is True, creates custom field definitions that don't exist yet.
        New fields are created as 'string' type by default.
        """
        cache_key = f"{base_url}:custom_fields_defs"
        now = time.monotonic()
        cached = _entity_cache.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            name_to_info = cached[1]
        else:
            url: str | None = f"{base_url}/api/custom_fields/?page_size=100"
            name_to_info: dict[str, dict[str, Any]] = {}
            while url:
                resp = await client.get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
                for item in data.get("results", []):
                    name_to_info[item.get("name", "").lower()] = {
                        "id": item["id"],
                        "data_type": item.get("data_type", "string"),
                    }
                url = data.get("next")
            _entity_cache[cache_key] = (now, name_to_info)

        result: list[dict[str, Any]] = []
        for name, value in custom_fields.items():
            info = name_to_info.get(name.lower())
            if info is not None:
                value = _format_custom_field_value(value, info["data_type"])
                result.append({"field": info["id"], "value": value})
            elif create_missing:
                try:
                    resp = await client.post(
                        f"{base_url}/api/custom_fields/",
                        json={"name": name, "data_type": "string"},
                    )
                    resp.raise_for_status()
                    new_id = resp.json().get("id")
                    if new_id:
                        result.append({"field": new_id, "value": value})
                        logger.info("Created custom field %r with ID %d", name, new_id)
                except Exception:
                    logger.warning("Failed to create custom field %r", name, exc_info=True)
            else:
                logger.warning("Could not resolve custom field %r to an ID; skipping.", name)
        return result
