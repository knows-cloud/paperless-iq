"""Document analyzer: fetches content from Paperless NGX, resolves prompts, calls LLM."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from backend.models import MetadataSuggestion, PaperlessIQConfig
from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)

# Default context window (tokens ≈ chars/4); providers may override via config
DEFAULT_CONTEXT_WINDOW_CHARS = 32_000

# System prompt instructing the LLM to return structured JSON
_SYSTEM_SUFFIX = """
Return ONLY a JSON object with these keys (omit keys you cannot determine):
{
  "title": "<string>",
  "tags": ["<string>", ...],
  "correspondent": "<string or null>",
  "document_type": "<string or null>",
  "storage_path": "<string or null>",
  "custom_fields": {"<field_name>": "<value>", ...}
}
Do not include any explanation or markdown — only the raw JSON object.
"""

_DEFAULT_PROMPT = (
    "Analyze the following document and suggest appropriate metadata.\n\n"
    "Document content:\n{content}\n"
)


class PaperlessNGXClient:
    """Minimal async client for the Paperless NGX REST API."""

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Token {token}"}

    async def get_document_ocr_text(self, document_id: int) -> str:
        """Fetch the OCR-extracted text for a document."""
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/api/documents/{document_id}/",
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("content", "") or ""

    async def get_document_bytes(self, document_id: int) -> bytes:
        """Download the original document file bytes."""
        async with httpx.AsyncClient(headers=self._headers, timeout=60) as client:
            resp = await client.get(
                f"{self._base_url}/api/documents/{document_id}/download/",
            )
            resp.raise_for_status()
            return resp.content

    async def get_document_metadata(self, document_id: int) -> dict[str, Any]:
        """Fetch full document metadata from Paperless NGX."""
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/api/documents/{document_id}/",
            )
            resp.raise_for_status()
            return resp.json()

    async def list_entities(self, entity_type: str) -> list[str]:
        """
        Fetch all existing entity names from Paperless NGX.

        entity_type must be one of: "tags", "correspondents", "document_types".
        Returns a list of name strings.

        Validates: Requirements 2.6, 2.8
        """
        endpoint_map = {
            "tags": "tags",
            "correspondents": "correspondents",
            "document_types": "document_types",
        }
        endpoint = endpoint_map[entity_type]
        names: list[str] = []
        url: str | None = f"{self._base_url}/api/{endpoint}/"
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            while url:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("results", []):
                    name = item.get("name")
                    if name:
                        names.append(name)
                url = data.get("next")  # follow pagination
        return names

    async def create_entity(self, entity_type: str, name: str) -> None:
        """
        Create a new entity (tag, correspondent, or document type) in Paperless NGX.

        entity_type must be one of: "tags", "correspondents", "document_types".

        Validates: Requirements 2.7, 2.8
        """
        endpoint_map = {
            "tags": "tags",
            "correspondents": "correspondents",
            "document_types": "document_types",
        }
        endpoint = endpoint_map[entity_type]
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/api/{endpoint}/",
                json={"name": name},
            )
            resp.raise_for_status()
            logger.info("Created new %s %r in Paperless NGX.", entity_type, name)


def resolve_prompt_template(
    config: PaperlessIQConfig,
    document_type_id: int | None,
    field: str | None = None,
) -> str:
    """
    Resolve the prompt template using the priority chain:
      1. Per-document-type template (if document_type_id is known and configured)
      2. Per-field template (if field is specified and configured)
      3. Global default template
      4. Built-in fallback

    Validates: Requirements 2.3, 2.4, 12.2, 12.3
    """
    if document_type_id is not None:
        per_doctype = config.per_doctype_prompt_templates.get(document_type_id)
        if per_doctype:
            return per_doctype

    if field is not None:
        per_field = config.per_field_prompt_templates.get(field)
        if per_field:
            return per_field

    if config.global_prompt_template:
        return config.global_prompt_template

    return _DEFAULT_PROMPT


def truncate_to_context_window(
    text: str,
    max_chars: int,
    document_id: int,
) -> str:
    """
    Truncate text to fit within the context window.
    Logs a warning when truncation occurs.

    Validates: Requirements 1.4
    """
    if len(text) <= max_chars:
        return text

    logger.warning(
        "Document %d content (%d chars) exceeds context window (%d chars); truncating.",
        document_id,
        len(text),
        max_chars,
    )
    return text[:max_chars]


def _parse_llm_response(raw: str) -> dict[str, Any]:
    """
    Extract a JSON object from the LLM response.
    Attempts strict parse first, then falls back to regex extraction.
    """
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to extract a JSON object from within markdown code fences or prose
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse LLM response as JSON; returning empty suggestion.")
    return {}


async def _apply_creation_policy(
    suggestion: MetadataSuggestion,
    config: PaperlessIQConfig,
    paperless_client: PaperlessNGXClient,
) -> MetadataSuggestion:
    """
    Enforce creation policies for tags, correspondents, and document types.

    For each entity type:
    - "existing_only": filter suggested values to those already present in Paperless NGX.
    - "allow_new": keep all suggested values; create any that don't yet exist in Paperless NGX.

    Returns a new MetadataSuggestion with the policy applied.

    Validates: Requirements 2.5, 2.6, 2.7, 2.8
    """
    # Fetch existing entities once per type (only if needed)
    existing_tags: list[str] | None = None
    existing_correspondents: list[str] | None = None
    existing_doctypes: list[str] | None = None

    # --- Tags ---
    if suggestion.tags:
        existing_tags = await paperless_client.list_entities("tags")
        existing_set = {t.lower() for t in existing_tags}
        if config.tag_creation_policy == "existing_only":
            filtered = [t for t in suggestion.tags if t.lower() in existing_set]
            suggestion = suggestion.model_copy(update={"tags": filtered})
        else:  # allow_new
            for tag in suggestion.tags:
                if tag.lower() not in existing_set:
                    await paperless_client.create_entity("tags", tag)
                    existing_set.add(tag.lower())

    # --- Correspondent ---
    if suggestion.correspondent:
        existing_correspondents = await paperless_client.list_entities("correspondents")
        existing_set = {c.lower() for c in existing_correspondents}
        if config.correspondent_creation_policy == "existing_only":
            if suggestion.correspondent.lower() not in existing_set:
                suggestion = suggestion.model_copy(update={"correspondent": None})
        else:  # allow_new
            if suggestion.correspondent.lower() not in existing_set:
                await paperless_client.create_entity("correspondents", suggestion.correspondent)

    # --- Document type ---
    if suggestion.document_type:
        existing_doctypes = await paperless_client.list_entities("document_types")
        existing_set = {d.lower() for d in existing_doctypes}
        if config.doctype_creation_policy == "existing_only":
            if suggestion.document_type.lower() not in existing_set:
                suggestion = suggestion.model_copy(update={"document_type": None})
        else:  # allow_new
            if suggestion.document_type.lower() not in existing_set:
                await paperless_client.create_entity("document_types", suggestion.document_type)

    return suggestion


def _build_suggestion(
    document_id: int,
    parsed: dict[str, Any],
    llm_provider: str,
    llm_model: str,
    analysis_mode: str,
    prompt_used: str,
    raw_llm_response: str,
) -> MetadataSuggestion:
    """Construct a MetadataSuggestion from parsed LLM output."""
    return MetadataSuggestion(
        id=uuid4(),
        document_id=document_id,
        status="pending",
        created_at=datetime.now(timezone.utc),
        title=parsed.get("title") or None,
        tags=parsed.get("tags") or [],
        correspondent=parsed.get("correspondent") or None,
        document_type=parsed.get("document_type") or None,
        storage_path=parsed.get("storage_path") or None,
        custom_fields=parsed.get("custom_fields") or {},
        llm_provider=llm_provider,
        llm_model=llm_model,
        analysis_mode=analysis_mode,  # type: ignore[arg-type]
        prompt_used=prompt_used,
        raw_llm_response=raw_llm_response,
    )


class DocumentAnalyzer:
    """
    Orchestrates a single document analysis run.

    Steps:
      1. Determine analysis mode (ocr vs full_document) per config
      2. Fetch OCR text or full document bytes from Paperless NGX
      3. Resolve prompt template (per-doctype → per-field → global → default)
      4. Truncate input to context window, logging a warning if needed
      5. Call LLMProvider.complete() with the resolved prompt
      6. Parse JSON response into MetadataSuggestion
      7. Enforce creation policies (existing_only / allow_new) for tags, correspondents, document types

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
    """

    def __init__(
        self,
        provider: LLMProvider,
        paperless_client: PaperlessNGXClient,
        config: PaperlessIQConfig,
        provider_name: str,
        context_window_chars: int = DEFAULT_CONTEXT_WINDOW_CHARS,
        max_tokens: int = 1024,
    ) -> None:
        self._provider = provider
        self._paperless = paperless_client
        self._config = config
        self._provider_name = provider_name
        self._context_window_chars = context_window_chars
        self._max_tokens = max_tokens

    def _resolve_analysis_mode(self, document_type_id: int | None) -> str:
        """
        Determine whether to use 'ocr' or 'full_document' for this document.
        Per-doctype setting takes precedence over the global default.

        Validates: Requirements 1.1, 1.2, 1.3
        """
        if document_type_id is not None:
            per_doctype = self._config.per_doctype_analysis_mode.get(document_type_id)
            if per_doctype is not None:
                return per_doctype
        return self._config.default_analysis_mode

    async def analyze(self, document_id: int) -> MetadataSuggestion:
        """
        Run a full analysis for the given document ID.

        Returns a MetadataSuggestion with status='pending'.
        """
        # 1. Fetch document metadata to determine type
        doc_meta = await self._paperless.get_document_metadata(document_id)
        document_type_id: int | None = doc_meta.get("document_type")

        # 2. Determine analysis mode and fetch content
        mode = self._resolve_analysis_mode(document_type_id)

        if mode == "full_document":
            raw_bytes = await self._paperless.get_document_bytes(document_id)
            # Decode bytes to text for LLM; non-decodable bytes are replaced
            content = raw_bytes.decode("utf-8", errors="replace")
        else:
            content = await self._paperless.get_document_ocr_text(document_id)

        # 3. Resolve prompt template
        template = resolve_prompt_template(self._config, document_type_id)

        # 4. Truncate to context window
        content = truncate_to_context_window(
            content, self._context_window_chars, document_id
        )

        # 5. Build final prompt and call LLM
        if "{content}" in template:
            prompt = template.format(content=content) + _SYSTEM_SUFFIX
        else:
            prompt = template + f"\n\nDocument content:\n{content}\n" + _SYSTEM_SUFFIX

        raw_response = await self._provider.complete(prompt, self._max_tokens)

        # 6. Parse response into MetadataSuggestion
        parsed = _parse_llm_response(raw_response)

        suggestion = _build_suggestion(
            document_id=document_id,
            parsed=parsed,
            llm_provider=self._provider_name,
            llm_model=self._config.llm_model,
            analysis_mode=mode,
            prompt_used=prompt,
            raw_llm_response=raw_response,
        )

        # 7. Enforce creation policies for tags, correspondents, document types
        suggestion = await _apply_creation_policy(
            suggestion=suggestion,
            config=self._config,
            paperless_client=self._paperless,
        )

        return suggestion
