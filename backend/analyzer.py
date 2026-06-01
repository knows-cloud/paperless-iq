"""Document analyzer: fetches content from Paperless NGX, resolves prompts, calls LLM."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from backend.models import MetadataSuggestion, PaperlessIQConfig, VisionAnalysisResult
from backend.pdf_utils import get_page_count, render_pages
from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)

# Default context window (tokens ≈ chars/4); providers may override via config
DEFAULT_CONTEXT_WINDOW_CHARS = 32_000

# Fallback suffix used when native structured output is unavailable (e.g. old Ollama, custom models).
# When output_schema is passed to the provider, this suffix is omitted.
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
The "tags" list must be the COMPLETE desired set — include every tag you want on the document,
both existing ones to keep and new ones to add. Current tags you omit will be removed.
Do not include any explanation or markdown — only the raw JSON object.
"""


def _build_output_schema(
    include_content: bool = False,
    custom_field_defs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a JSON Schema for the LLM output, used with native structured output APIs.

    Nullable string fields use anyOf so providers that support it (Anthropic, OpenAI,
    Ollama) return proper null values.  Custom fields are enumerated from
    ``custom_field_defs`` so the schema stays Bedrock-compatible
    (``additionalProperties: false`` required on all objects).
    """
    cf_properties: dict[str, Any] = {}
    if custom_field_defs:
        for cf in custom_field_defs:
            cf_properties[cf["name"]] = {"type": "string", "description": cf.get("data_type", "")}

    properties: dict[str, Any] = {
        "title": {"type": "string", "description": "Descriptive document title"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Complete desired tag set — include every tag to keep plus new ones",
        },
        "correspondent": {"type": "string", "description": "Correspondent name, or omit if unknown"},
        "document_type": {"type": "string", "description": "Document type name, or omit if unknown"},
        "storage_path": {"type": "string", "description": "Storage path, or omit if unknown"},
        "custom_fields": {
            "type": "object",
            "properties": cf_properties,
            "additionalProperties": False,
            "description": "Custom field values keyed by field name",
        },
    }

    if include_content:
        properties["content"] = {
            "type": "string",
            "description": "Full text extracted from the document images",
        }

    return {
        "type": "object",
        "properties": properties,
        "required": ["title", "tags"],
        "additionalProperties": False,
    }

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
        names, _ = await self.list_entities_with_map(entity_type)
        return names

    async def list_entities_with_map(
        self, entity_type: str
    ) -> tuple[list[str], dict[int, str]]:
        """
        Fetch all existing entity names from Paperless NGX.

        entity_type must be one of: "tags", "correspondents", "document_types", "storage_paths".
        Returns ``(names, id_to_name)`` so callers can resolve integer IDs
        from document metadata to display names without a second API round-trip.

        Validates: Requirements 2.6, 2.8
        """
        endpoint_map = {
            "tags": "tags",
            "correspondents": "correspondents",
            "document_types": "document_types",
            "storage_paths": "storage_paths",
        }
        endpoint = endpoint_map[entity_type]
        names: list[str] = []
        id_to_name: dict[int, str] = {}
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
                        id_to_name[item["id"]] = name
                url = data.get("next")  # follow pagination
        return names, id_to_name

    async def list_custom_field_definitions(self) -> list[dict[str, Any]]:
        """
        Fetch all custom field definitions from Paperless NGX.

        Returns a list of dicts with ``id``, ``name``, and ``data_type`` per field.
        Follows pagination (``next`` links) to retrieve the complete set.

        Validates: Requirements 12.4
        """
        fields: list[dict[str, Any]] = []
        url: str | None = f"{self._base_url}/api/custom_fields/"
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            while url:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("results", []):
                    fields.append({
                        "id": item["id"],
                        "name": item["name"],
                        "data_type": item.get("data_type", ""),
                    })
                url = data.get("next")
        return fields

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

    return config.global_prompt_template


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


def _parse_llm_response(raw: str, *, structured_output_attempted: bool = False) -> dict[str, Any]:
    """Extract a JSON object from the LLM response.

    When ``structured_output_attempted`` is True and strict json.loads fails,
    logs a warning — structured output should have guaranteed valid JSON.
    Falls back to regex extraction in all cases.
    """
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    if structured_output_attempted:
        logger.warning(
            "Structured output was requested but LLM response is not valid JSON — "
            "falling back to regex extraction. Response: %.200s", raw,
        )

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
    *,
    all_tags: list[str] | None = None,
    all_correspondents: list[str] | None = None,
    all_document_types: list[str] | None = None,
) -> MetadataSuggestion:
    """
    Enforce creation policies for tags, correspondents, and document types.

    For each entity type:
    - "existing_only": filter suggested values to those already present in Paperless NGX.
    - "allow_new": keep all suggested values as-is (creation happens at approval time).

    When the caller passes pre-fetched entity lists via ``all_tags``,
    ``all_correspondents``, or ``all_document_types``, those are used directly
    and no additional API calls are made for that entity type.

    Returns a new MetadataSuggestion with the policy applied.
    """
    # --- Tags ---
    if suggestion.tags and config.tag_creation_policy == "existing_only":
        existing = all_tags if all_tags is not None else await paperless_client.list_entities("tags")
        existing_set = {t.lower() for t in existing}
        filtered = [t for t in suggestion.tags if t.lower() in existing_set]
        suggestion = suggestion.model_copy(update={"tags": filtered})

    # --- Correspondent ---
    if suggestion.correspondent and config.correspondent_creation_policy == "existing_only":
        existing = (
            all_correspondents
            if all_correspondents is not None
            else await paperless_client.list_entities("correspondents")
        )
        existing_set = {c.lower() for c in existing}
        if suggestion.correspondent.lower() not in existing_set:
            suggestion = suggestion.model_copy(update={"correspondent": None})

    # --- Document type ---
    if suggestion.document_type and config.doctype_creation_policy == "existing_only":
        existing = (
            all_document_types
            if all_document_types is not None
            else await paperless_client.list_entities("document_types")
        )
        existing_set = {d.lower() for d in existing}
        if suggestion.document_type.lower() not in existing_set:
            suggestion = suggestion.model_copy(update={"document_type": None})

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
      3. Fetch entity lists (tags, correspondents, document types, custom fields) for prompt context
      4. Resolve prompt template (per-doctype → per-field → global → default)
      5. Truncate input to context window, logging a warning if needed
      6. Build final prompt with entity context injected between template and document content
      7. Call LLMProvider.complete() with the resolved prompt
      8. Parse JSON response into MetadataSuggestion
      9. Enforce creation policies (existing_only / allow_new) for tags, correspondents, document types

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8,
               12.1, 12.2, 12.3, 12.4, 12.5, 12.6
    """

    def __init__(
        self,
        provider: LLMProvider,
        paperless_client: PaperlessNGXClient,
        config: PaperlessIQConfig,
        provider_name: str,
        context_window_chars: int = DEFAULT_CONTEXT_WINDOW_CHARS,
        max_tokens: int = 1024,
        vector_store: Any | None = None,
    ) -> None:
        self._provider = provider
        self._paperless = paperless_client
        self._config = config
        self._provider_name = provider_name
        self._context_window_chars = context_window_chars
        self._max_tokens = max_tokens
        self._custom_field_defs: list[dict[str, Any]] = []
        self._vector_store = vector_store

    async def _fetch_entity_context(
        self,
        document_content: str = "",
        doc_meta: dict[str, Any] | None = None,
    ) -> tuple[str, list[str], list[str], list[str]]:
        """Fetch entity lists for the LLM prompt.

        Returns ``(context_str, all_tags, all_correspondents, all_document_types)``.
        The raw lists are returned so the caller can pass them to
        ``_apply_creation_policy`` and avoid a second round of API calls.

        When ``doc_meta`` is provided, a "Current metadata on this document"
        section is appended so the LLM knows what is already assigned and can
        output the complete desired tag set (including existing tags to keep).

        When smart_entity_selection is enabled and a vector store is available,
        queries similar documents to build a focused entity set (hybrid approach:
        entities from similar docs + top-N most frequent as fallback).

        Otherwise falls back to sending all entities.

        On any failure, logs a warning and returns empty values.
        """
        try:
            custom_field_defs = await self._paperless.list_custom_field_definitions()
            self._custom_field_defs = custom_field_defs
        except Exception:
            logger.warning("Failed to fetch custom field definitions.", exc_info=True)
            self._custom_field_defs = []
            custom_field_defs = []

        try:
            all_tags, tags_id_map = await self._paperless.list_entities_with_map("tags")
            all_correspondents, corrs_id_map = await self._paperless.list_entities_with_map("correspondents")
            all_document_types, doctypes_id_map = await self._paperless.list_entities_with_map("document_types")
        except Exception:
            logger.warning(
                "Failed to fetch entity lists from Paperless NGX; "
                "proceeding without entity context.",
                exc_info=True,
            )
            return "", [], [], []

        try:
            all_storage_paths, _ = await self._paperless.list_entities_with_map("storage_paths")
        except Exception:
            logger.warning("Failed to fetch storage paths; proceeding without them.", exc_info=True)
            all_storage_paths = []

        # Smart entity selection: use vector similarity + frequency fallback
        similar_cf: dict[str, set[str]] = {}
        using_similar = False
        if (
            self._config.smart_entity_selection
            and self._vector_store is not None
            and document_content
            and hasattr(self._vector_store, "query_similar_metadata")
            and hasattr(self._vector_store, "count")
            and await self._vector_store.count() > 0
        ):
            try:
                similar_meta = await self._vector_store.query_similar_metadata(
                    document_content,
                    self._config.similar_docs_count,
                    exclude_tag_id=self._config.inbox_tag_id,
                )
                # Hybrid: entities from similar docs + top-N frequent as fallback
                fallback_n = self._config.frequency_fallback_count
                tags = sorted(similar_meta["tags"]) + [
                    t for t in all_tags[:fallback_n] if t not in similar_meta["tags"]
                ]
                correspondents = sorted(similar_meta["correspondents"]) + [
                    c for c in all_correspondents[:fallback_n] if c not in similar_meta["correspondents"]
                ]
                document_types = sorted(similar_meta["document_types"]) + [
                    d for d in all_document_types[:fallback_n] if d not in similar_meta["document_types"]
                ]
                similar_cf = similar_meta.get("custom_fields", {})
                using_similar = True
                logger.info(
                    "Smart entity selection: %d tags, %d correspondents, %d doc types, %d cf names "
                    "(from %d similar docs + frequency fallback)",
                    len(tags), len(correspondents), len(document_types), len(similar_cf),
                    self._config.similar_docs_count,
                )
            except Exception:
                logger.warning("Smart entity selection failed; falling back to full lists.", exc_info=True)
                tags, correspondents, document_types = all_tags, all_correspondents, all_document_types
        else:
            tags, correspondents, document_types = all_tags, all_correspondents, all_document_types

        sections: list[str] = []

        if using_similar:
            # Group entities from similar docs under one header
            similar_lines = []
            if tags:
                similar_lines.append(f"  Tags: {', '.join(tags)}")
            if correspondents:
                similar_lines.append(f"  Correspondents: {', '.join(correspondents)}")
            if document_types:
                similar_lines.append(f"  Document types: {', '.join(document_types)}")
            if similar_cf:
                for name, vals in sorted(similar_cf.items()):
                    if vals:
                        similar_lines.append(f"  {name}: {', '.join(sorted(vals))}")
            if similar_lines:
                sections.append("Similar documents use the following:\n" + "\n".join(similar_lines))

            available_lines = []
            if all_storage_paths:
                available_lines.append(f"  Storage paths: {', '.join(all_storage_paths)}")
            if custom_field_defs:
                cf_parts = [f"{cf['name']} ({cf['data_type']})" for cf in custom_field_defs]
                available_lines.append(f"  Custom fields: {', '.join(cf_parts)}")
            if available_lines:
                sections.append("Available:\n" + "\n".join(available_lines))
        else:
            available_lines = []
            if tags:
                available_lines.append(f"  Tags: {', '.join(tags)}")
            if correspondents:
                available_lines.append(f"  Correspondents: {', '.join(correspondents)}")
            if document_types:
                available_lines.append(f"  Document types: {', '.join(document_types)}")
            if all_storage_paths:
                available_lines.append(f"  Storage paths: {', '.join(all_storage_paths)}")
            if custom_field_defs:
                cf_parts = [f"{cf['name']} ({cf['data_type']})" for cf in custom_field_defs]
                available_lines.append(f"  Custom fields: {', '.join(cf_parts)}")
            if available_lines:
                sections.append("Available:\n" + "\n".join(available_lines))

        # Inject current document state so the LLM outputs the full desired set
        if doc_meta:
            current_tag_ids: list[int] = doc_meta.get("tags") or []
            inbox_tag_id = self._config.inbox_tag_id
            current_tag_names = [
                tags_id_map[tid]
                for tid in current_tag_ids
                if tid in tags_id_map and tid != inbox_tag_id
            ]
            current_corr_id: int | None = doc_meta.get("correspondent")
            current_corr = corrs_id_map.get(current_corr_id) if current_corr_id else None
            current_dt_id: int | None = doc_meta.get("document_type")
            current_dt = doctypes_id_map.get(current_dt_id) if current_dt_id else None

            current_lines = [
                f"  Tags: {', '.join(current_tag_names) if current_tag_names else 'none'}",
                f"  Correspondent: {current_corr or 'none'}",
                f"  Document type: {current_dt or 'none'}",
            ]

            cf_id_to_name = {cf["id"]: cf["name"] for cf in custom_field_defs}
            for cf_entry in (doc_meta.get("custom_fields") or []):
                field_id = cf_entry.get("field")
                value = cf_entry.get("value")
                name = cf_id_to_name.get(field_id)
                if name and value is not None and str(value).strip():
                    current_lines.append(f"  {name}: {value}")

            sections.append(
                "Current metadata already on this document:\n"
                + "\n".join(current_lines)
                + "\n\n"
                "Your 'tags' output must be the COMPLETE desired set — include all tags you want "
                "to keep (from the current set above) plus any new ones to add. "
                "Current tags you omit will be removed."
            )

        return "\n\n".join(sections), all_tags, all_correspondents, all_document_types

    def _build_field_instructions(self) -> str:
        """
        Build per-field instruction lines from ``config.field_descriptions``.

        For keys starting with ``cf:<id>``, resolves the custom field name from
        ``self._custom_field_defs``.  For other keys, uses the key directly as
        the field name.  Only fields that have a non-empty description are
        included.

        Returns a newline-joined string of instruction lines, or an empty
        string if there are no descriptions.

        Validates: Requirements 9.1, 9.2, 9.3, 9.4, 5.5
        """
        lines: list[str] = []
        cf_lookup: dict[int, str] = {
            cf["id"]: cf["name"] for cf in self._custom_field_defs
        }

        for key, description in self._config.field_descriptions.items():
            if not description:
                continue

            if key.startswith("cf:"):
                # Resolve custom field name from definitions
                try:
                    cf_id = int(key[3:])
                except (ValueError, IndexError):
                    continue
                field_name = cf_lookup.get(cf_id)
                if field_name is None:
                    # Custom field definition not found; skip
                    continue
            else:
                field_name = key

            lines.append(f"Instructions for {field_name}: {description}")

        return "\n".join(lines)

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

    def _build_prompt(
        self,
        template: str,
        content: str,
        entity_context: str,
        field_instructions: str,
        lang: str | None,
        use_structured_output: bool,
    ) -> str:
        """Assemble the final prompt string from components.

        When ``use_structured_output`` is True, the _SYSTEM_SUFFIX (which
        describes the expected JSON format) is omitted — the schema carries
        that information instead.
        """
        context_parts = [p for p in (entity_context, field_instructions) if p]
        context_block = "\n\n".join(context_parts)

        lang_instruction = ""
        if lang:
            lang_instruction = (
                f"\nIMPORTANT: All output values (title, tags, correspondent, document_type, "
                f"storage_path, custom field values) MUST be in {lang}. "
                f"Use {lang} language for all metadata values. "
                f"Do NOT use English unless the original value is a proper noun or brand name.\n"
            )

        suffix = "" if use_structured_output else _SYSTEM_SUFFIX

        if "{content}" in template:
            combined_content = (context_block + "\n\n" + content) if context_block else content
            return template.format(content=combined_content) + lang_instruction + suffix
        else:
            context_section = f"\n\n{context_block}" if context_block else ""
            return (
                template
                + context_section
                + f"\n\nDocument content:\n{content}\n"
                + lang_instruction
                + suffix
            )

    async def analyze(self, document_id: int) -> MetadataSuggestion:
        """Run a full analysis for the given document ID.

        Returns a MetadataSuggestion with status='pending'.
        When the configured mode is 'full_document', delegates to analyze_vision().
        """
        # 1. Fetch document metadata to determine type
        doc_meta = await self._paperless.get_document_metadata(document_id)
        document_type_id: int | None = doc_meta.get("document_type")

        # 2. Route full_document mode to vision analysis
        mode = self._resolve_analysis_mode(document_type_id)
        if mode == "full_document":
            result = await self.analyze_vision(document_id, include_content=False)
            return result.suggestion

        # OCR text is already in the metadata response — avoids a second API call.
        content = doc_meta.get("content", "") or ""

        # 3. Fetch entity lists for prompt context
        entity_context, all_tags, all_correspondents, all_document_types = (
            await self._fetch_entity_context(document_content=content, doc_meta=doc_meta)
        )

        # 4. Build per-field instructions
        field_instructions = self._build_field_instructions()

        # 5. Resolve prompt template
        template = resolve_prompt_template(self._config, document_type_id)

        # 6. Truncate to context window
        content = truncate_to_context_window(content, self._context_window_chars, document_id)

        # 7. Build output schema for native structured output
        output_schema = _build_output_schema(
            include_content=False,
            custom_field_defs=self._custom_field_defs or None,
        )

        # 8. Build prompt (no _SYSTEM_SUFFIX when schema is provided)
        prompt = self._build_prompt(
            template=template,
            content=content,
            entity_context=entity_context,
            field_instructions=field_instructions,
            lang=self._config.target_language,
            use_structured_output=True,
        )

        logger.info(
            "Sending doc %d to LLM: provider=%s model=%s mode=ocr "
            "content=%d chars entity_ctx=%d chars total_prompt=%d chars (~%d tokens est.)",
            document_id, self._provider_name, self._config.llm_model,
            len(content), len(entity_context), len(prompt), len(prompt) // 4,
        )

        raw_response = await self._provider.complete(
            prompt, self._max_tokens, output_schema=output_schema
        )
        logger.info("LLM response for doc %d: %d chars", document_id, len(raw_response))

        parsed = _parse_llm_response(raw_response, structured_output_attempted=True)

        suggestion = _build_suggestion(
            document_id=document_id,
            parsed=parsed,
            llm_provider=self._provider_name,
            llm_model=self._config.llm_model,
            analysis_mode="ocr",
            prompt_used=prompt,
            raw_llm_response=raw_response,
        )

        suggestion = await _apply_creation_policy(
            suggestion=suggestion,
            config=self._config,
            paperless_client=self._paperless,
            all_tags=all_tags,
            all_correspondents=all_correspondents,
            all_document_types=all_document_types,
        )

        return suggestion

    async def analyze_vision(
        self,
        document_id: int,
        include_content: bool = False,
        max_pages: int | None = None,
    ) -> VisionAnalysisResult:
        """Analyze a document by rendering its pages as images and sending them to the LLM.

        Returns a VisionAnalysisResult containing the suggestion plus, when
        ``include_content=True``, the LLM-extracted text and the original OCR content.
        """
        # 1. Fetch metadata (for entity context and original OCR content)
        doc_meta = await self._paperless.get_document_metadata(document_id)
        document_type_id: int | None = doc_meta.get("document_type")
        original_ocr_content: str = doc_meta.get("content", "") or ""

        # 2. Download and render PDF pages
        pdf_bytes = await self._paperless.get_document_bytes(document_id)
        page_count = get_page_count(pdf_bytes)
        page_images = render_pages(pdf_bytes, max_pages=max_pages)

        logger.info(
            "Vision analysis: doc %d — %d total pages, rendering %d page(s)",
            document_id, page_count, len(page_images),
        )

        # 3. Fetch entity lists (use original OCR content for similarity search)
        entity_context, all_tags, all_correspondents, all_document_types = (
            await self._fetch_entity_context(
                document_content=original_ocr_content, doc_meta=doc_meta
            )
        )

        # 4. Build per-field instructions and prompt template
        field_instructions = self._build_field_instructions()
        template = resolve_prompt_template(self._config, document_type_id)

        # 5. Build vision-specific prompt — no text content to inject, images are the content
        context_parts = [p for p in (entity_context, field_instructions) if p]
        context_block = "\n\n".join(context_parts)
        lang = self._config.target_language
        lang_instruction = ""
        if lang:
            lang_instruction = (
                f"\nIMPORTANT: All output values MUST be in {lang}.\n"
            )

        content_instruction = (
            "\n\nExtract and return the full document text in the 'content' field."
            if include_content else ""
        )

        # Replace {content} placeholder with a vision-specific instruction
        vision_notice = "[Document provided as image(s) above — analyze the visual content]"
        if "{content}" in template:
            prompt = (
                template.format(content=vision_notice)
                + (f"\n\n{context_block}" if context_block else "")
                + lang_instruction
                + content_instruction
            )
        else:
            prompt = (
                template
                + f"\n\n{vision_notice}"
                + (f"\n\n{context_block}" if context_block else "")
                + lang_instruction
                + content_instruction
            )

        # 6. Build output schema (include content field when requested)
        output_schema = _build_output_schema(
            include_content=include_content,
            custom_field_defs=self._custom_field_defs or None,
        )

        logger.info(
            "Vision analysis: doc %d — provider=%s model=%s pages=%d include_content=%s",
            document_id, self._provider_name, self._config.llm_model,
            len(page_images), include_content,
        )

        raw_response = await self._provider.complete(
            prompt,
            self._max_tokens if not include_content else self._max_tokens * 4,
            output_schema=output_schema,
            images=page_images,
        )
        logger.info("Vision LLM response for doc %d: %d chars", document_id, len(raw_response))

        parsed = _parse_llm_response(raw_response, structured_output_attempted=True)
        extracted_content: str | None = parsed.pop("content", None) if include_content else None

        suggestion = _build_suggestion(
            document_id=document_id,
            parsed=parsed,
            llm_provider=self._provider_name,
            llm_model=self._config.llm_model,
            analysis_mode="full_document",
            prompt_used=prompt,
            raw_llm_response=raw_response,
        )

        suggestion = await _apply_creation_policy(
            suggestion=suggestion,
            config=self._config,
            paperless_client=self._paperless,
            all_tags=all_tags,
            all_correspondents=all_correspondents,
            all_document_types=all_document_types,
        )

        return VisionAnalysisResult(
            suggestion=suggestion,
            extracted_content=extracted_content,
            original_ocr_content=original_ocr_content if include_content else None,
            page_count=page_count,
        )
