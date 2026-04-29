"""Pydantic v2 data models for Paperless IQ."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

# Type alias for encrypted credential blobs
EncryptedBlob = bytes


class MetadataSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: int
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime

    # Suggested values
    title: str | None = None
    tags: list[str] = []
    correspondent: str | None = None
    document_type: str | None = None
    storage_path: str | None = None
    custom_fields: dict[str, Any] = {}

    # Provenance
    llm_provider: str
    llm_model: str
    analysis_mode: Literal["ocr", "full_document"]
    prompt_used: str
    raw_llm_response: str


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: int
    field_name: str
    previous_value: str | None = None
    new_value: str | None = None
    change_source: Literal["ai", "human"]
    changed_at: datetime  # UTC
    suggestion_id: UUID | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    document_title: str
    passage: str          # verbatim quoted passage
    score: float
    deeplink_url: str     # URL to document in Paperless NGX


class DocumentTrackingRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    first_seen_at: datetime
    last_analyzed_at: datetime | None = None
    embedding_stored: bool = False


class PaperlessIQConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # LLM
    llm_provider: Literal["bedrock", "anthropic", "ollama", "openai"]
    llm_model: str
    llm_credentials: EncryptedBlob = b""  # never returned to UI
    ollama_url: str = "http://localhost:11434"  # Ollama server URL (only used when provider is ollama)

    # Vector store
    vector_store_backend: Literal["local", "bedrock_kb"] = "local"
    bedrock_kb_id: str | None = None

    # Analysis defaults
    default_analysis_mode: Literal["ocr", "full_document"] = "ocr"
    context_window_chars: int = 128_000  # max chars sent to LLM (truncates if exceeded)
    per_doctype_analysis_mode: dict[int, Literal["ocr", "full_document"]] = {}

    # Smart entity selection (hybrid: vector similarity + frequency fallback)
    smart_entity_selection: bool = True
    similar_docs_count: int = 10  # how many similar docs to use for entity suggestions
    frequency_fallback_count: int = 20  # top-N most frequent entities as fallback
    embedding_model: str = "nomic-embed-text"  # model used for embeddings

    # Prompt templates
    global_prompt_template: str = (
        "You are a document metadata classifier for a Paperless NGX document management system.\n"
        "Your task is to analyze the provided document content and suggest appropriate metadata values.\n\n"
        "You will receive:\n"
        "- The document's OCR text or full content\n"
        "- A list of existing tags, correspondents, document types, and custom fields from the system\n\n"
        "You must return a JSON object with these keys (omit keys you cannot determine):\n"
        '{\n  "title": "<descriptive document title>",\n'
        '  "tags": ["<tag1>", "<tag2>", ...],\n'
        '  "correspondent": "<person or organization name>",\n'
        '  "document_type": "<type of document>",\n'
        '  "storage_path": "<folder path or null>",\n'
        '  "custom_fields": {"<field_name>": "<value>", ...}\n}\n\n'
        "Only use values from the provided lists for tags, correspondents, and document types "
        "unless instructed otherwise by the creation policy.\n"
        "Return ONLY the raw JSON object, no markdown, no explanation."
    )
    per_field_prompt_templates: dict[str, str] = {}
    per_doctype_prompt_templates: dict[int, str] = {}

    # Per-field descriptions: instructions for the LLM on how to populate each metadata field
    field_descriptions: dict[str, str] = {}

    # Creation policies
    tag_creation_policy: Literal["existing_only", "allow_new"] = "existing_only"
    correspondent_creation_policy: Literal["existing_only", "allow_new"] = "existing_only"
    doctype_creation_policy: Literal["existing_only", "allow_new"] = "existing_only"

    # Automation
    inbox_tag_id: int | None = None
    auto_apply: bool = False
    poll_interval_seconds: int = 10
    batch_size: int = 10
    schedule_cron: str | None = None
    automation_enabled: bool = False

    # Audit
    audit_retention_days: int = 90  # minimum 90

    # Localization
    target_language: str | None = None
    ui_language: str = "en"

    # Theme
    theme_primary_color: str = "#1a7288"
    theme_sidebar_from: str = "#0a3344"
    theme_sidebar_to: str = "#0e4458"
    theme_font: str = "Roboto"
    theme_font_size: str = "14px"
    theme_text_color: str = "#2d3239"
    theme_bg_color: str = "#f8f9fb"
    theme_card_color: str = "#ffffff"
    theme_card_alt_hex: str = "#1a7288"
    theme_card_alt_opacity: int = 12
    theme_logo: str = "iq_1.png"
    theme_nav_icons: dict[str, str] = {
        "manual": "🔍",
        "queue": "📋",
        "discovery": "💬",
        "audit": "📜",
        "settings": "⚙️",
    }

    @field_validator("audit_retention_days")
    @classmethod
    def validate_retention(cls, v: int) -> int:
        if v < 90:
            raise ValueError("audit_retention_days must be at least 90")
        return v

    @field_validator("poll_interval_seconds")
    @classmethod
    def validate_poll_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("poll_interval_seconds must be at least 1")
        return v

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError("batch_size must be at least 1")
        return v
