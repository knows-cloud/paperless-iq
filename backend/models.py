"""Pydantic v2 data models for Paperless IQ."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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
    analysis_mode: Literal["ocr", "full_document", "grooming"]
    prompt_used: str
    raw_llm_response: str

    # Suggested content from full-document analysis (None unless transcribed).
    # original_ocr_content is the document's OCR text at analysis time, for the diff.
    extracted_content: str | None = None
    original_ocr_content: str | None = None

    # Grooming scan evidence (analysis_mode == "grooming" only): JSON-encoded
    # {actions: [{action, entity_type, entity_name, score, ...}], base_tags, scanned_at}.
    evidence_json: str | None = None


class VisionAnalysisResult(BaseModel):
    """Result of a vision-based full-document analysis."""
    suggestion: MetadataSuggestion
    extracted_content: str | None = None   # only present when include_content=True
    original_ocr_content: str | None = None  # current Paperless OCR text, for diff modal
    page_count: int


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: int
    document_title: str | None = None
    field_name: str
    previous_value: str | None = None
    new_value: str | None = None
    change_source: str  # actor: "user:<name>", "automation", "webhook", "system", legacy "ai"/"human"
    action_type: str = "field_change"
    session_id: str | None = None
    changed_at: datetime  # UTC
    suggestion_id: UUID | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    document_title: str
    passage: str          # verbatim quoted passage
    score: float
    deeplink_url: str     # URL to document in Paperless NGX


class UserPermissions(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    ng_admin: bool = False
    can_access: bool = False
    can_view_queue: bool = False
    can_approve: bool = False
    can_analyze: bool = False
    can_discover: bool = False
    can_settings: bool = False
    can_groom: bool = False
    updated_at: datetime | None = None


class DocumentTrackingRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    first_seen_at: datetime
    last_analyzed_at: datetime | None = None
    embedding_stored: bool = False
    reembed_dirty_since: datetime | None = None


class PaperlessIQConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # LLM
    llm_provider: Literal["bedrock", "anthropic", "ollama", "openai"]
    llm_model: str
    llm_credentials: EncryptedBlob = b""  # never returned to UI
    ollama_url: str = "http://localhost:11434"  # Ollama server URL (only used when provider is ollama)
    openai_base_url: str | None = None  # custom base URL for OpenAI-compatible APIs (open-webui, LM Studio, etc.)
    llm_timeout_seconds: int = 120  # max seconds to wait for LLM response (0 = no limit)

    # Vector store
    vector_store_backend: Literal["local", "bedrock_kb", "qdrant"] = "local"
    bedrock_kb_id: str | None = None

    # Qdrant backend
    qdrant_mode: Literal["local", "cloud"] = "local"
    qdrant_url: str = "http://qdrant:6333"  # default = compose service DNS
    qdrant_api_key: EncryptedBlob = b""  # Fernet-encrypted; never returned to UI
    qdrant_collection: str = "paperless_iq_chunks"
    qdrant_memory_collection: str = "piq_memories"

    # --- Search tuning: COMMON (apply to every backend) ---
    search_overfetch_multiplier: int = 5  # candidates fetched = top_n * this
    search_min_score: float = 0.0  # drop results below this normalized score (0 = off)
    chunk_size: int = 1000  # chars per chunk
    chunk_overlap: int = 200  # overlap between chunks
    chunk_strategy: Literal["char", "sentence"] = "char"
    rerank_enabled: bool = False  # master switch (ships OFF)
    rerank_method: Literal["llm", "local", "api"] = "llm"  # which reranker when enabled
    rerank_top_k: int = 20  # how many candidates to rerank
    rerank_model: str = "BAAI/bge-reranker-v2-m3"  # default local cross-encoder (multilingual)

    # --- Search tuning: CHROMA-specific ---
    chroma_hnsw_search_ef: int = 100  # recall vs latency at query time
    chroma_hnsw_m: int = 16  # graph connectivity (index build)
    chroma_hnsw_construction_ef: int = 100  # index build quality

    # --- Search tuning: QDRANT-specific ---
    qdrant_hnsw_ef: int = 128
    qdrant_hnsw_m: int = 16
    qdrant_quantization: Literal["none", "scalar", "binary"] = "none"
    qdrant_hybrid_search: bool = False  # dense + sparse (named vectors)

    # Analysis defaults
    # Standard analysis is always OCR-text based; full-document (vision) analysis is
    # on-demand only (via the vision flow / /api/analyze/vision), never the default.
    context_window_chars: int = 128_000  # max chars sent to LLM (truncates if exceeded)

    # Smart entity selection (hybrid: vector similarity + frequency fallback)
    smart_entity_selection: bool = True
    similar_docs_count: int = 10  # how many similar docs to use for entity suggestions
    frequency_fallback_count: int = 20  # top-N most frequent entities as fallback
    embed_provider: Literal["ollama", "bedrock", "openai"] = "ollama"  # provider used for embeddings
    embedding_model: str = "nomic-embed-text"  # embedding model name (used when embed_provider=ollama)
    embed_concurrency: int = 1  # parallel embed calls; 1 is safe for local Ollama, raise for remote/GPU
    # Deferred re-embedding — controls when metadata-change re-embeds are flushed.
    # "immediate" = current behaviour (re-embed on every change, zero latency).
    # "daily"     = batch all dirty documents once per day at embed_refresh_hour.
    # "manual"    = queue changes; user flushes via Re-embed now button.
    embed_refresh_mode: Literal["immediate", "daily", "manual"] = "immediate"
    embed_refresh_hour: int = 3  # UTC hour for the daily flush (0–23)

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
    discovery_system_prompt: str | None = None  # configurable body for the discovery RAG prompt

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

    # Access control
    sync_ng_admins: bool = True  # Paperless NGX superusers/staff auto-get full PIQ access

    # Webhook security
    webhook_secret: str = ""  # stored encrypted; empty = no auth required

    # Long-term memory
    memory_enabled: bool = True

    # Audit
    audit_retention_days: int = 180  # minimum 30

    # Localization
    target_language: str | None = None

    # Vision analysis
    vision_max_pages_warning: int = 5  # warn user (Keep/Limit/Cancel) when page count exceeds this
    vision_render_dpi: int = 150  # DPI for rendering pages to images (higher = sharper text, larger images)
    vision_pages_per_call: int = 10  # pages per transcription LLM call (respects per-call image limits)

    # Paperless NGX public URL for browser-facing links (may differ from PAPERLESS_URL which
    # uses the internal Docker hostname/network address)
    paperless_public_url: str = ""

    # Internal URL of Paperless IQ as reachable from Paperless NGX (used for webhook registration).
    # Leave empty to derive it from the incoming request's base URL.
    paperless_iq_internal_url: str = ""

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
    theme_chip_color: str = ""  # empty = derive from primary_color
    mantine_color: str = "teal"
    color_scheme: str = "dark"  # "light" | "dark" | "auto"
    theme_nav_icons: dict[str, str] = {}

    # ── Library Grooming ──────────────────────────────────────────────────────
    grooming_enabled: bool = False
    grooming_entity_types: list[str] = ["tag", "correspondent", "document_type"]
    grooming_dedup_name_threshold: float = 0.85
    grooming_dedup_embed_threshold: float = 0.90
    grooming_desc_sample_docs: int = 5
    grooming_desc_snippet_chars: int = 300
    grooming_add_threshold: float = 0.80
    grooming_remove_threshold: float = 0.35
    grooming_remove_percentile: int = 10
    grooming_min_supporting_chunks: int = 2
    grooming_scan_top_k: int = 100
    grooming_max_suggestions_per_scan: int = 50
    grooming_scan_cron: str | None = None
    grooming_resuggest_after_days: int = 0

    @field_validator("audit_retention_days")
    @classmethod
    def validate_retention(cls, v: int) -> int:
        if v < 30:
            raise ValueError("audit_retention_days must be at least 30")
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

    @model_validator(mode="after")
    def validate_grooming_thresholds(self) -> "PaperlessIQConfig":
        if self.grooming_add_threshold <= self.grooming_remove_threshold:
            raise ValueError(
                "grooming_add_threshold must be greater than grooming_remove_threshold "
                f"(got {self.grooming_add_threshold} ≤ {self.grooming_remove_threshold})"
            )
        return self

    @model_validator(mode="after")
    def validate_search_ef(self) -> "PaperlessIQConfig":
        """The active backend's HNSW query candidate list (search_ef) must be
        large enough to serve the requested + overfetched results, or recall
        silently caps. Only the active backend's ef field is enforced."""
        needed = self.similar_docs_count * self.search_overfetch_multiplier
        if self.vector_store_backend == "local":
            ef, field = self.chroma_hnsw_search_ef, "chroma_hnsw_search_ef"
        elif self.vector_store_backend == "qdrant":
            ef, field = self.qdrant_hnsw_ef, "qdrant_hnsw_ef"
        else:
            return self  # bedrock_kb manages its own retrieval
        if ef < needed:
            raise ValueError(
                f"{field} ({ef}) must be ≥ similar_docs_count × overfetch "
                f"({self.similar_docs_count} × {self.search_overfetch_multiplier} = {needed})"
            )
        return self
