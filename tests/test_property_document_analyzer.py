"""Property-based tests for the DocumentAnalyzer.

# Feature: paperless-iq, Property 1: LLM input mode selection
# Feature: paperless-iq, Property 2: Context window truncation
# Feature: paperless-iq, Property 3: Metadata suggestion completeness
# Feature: paperless-iq, Property 4: Metadata suggestion JSON schema conformance
# Feature: paperless-iq, Property 5: Prompt template resolution
# Feature: paperless-iq, Property 6: Creation policy enforcement

Validates: Requirements 1.1, 1.2, 1.4, 2.1, 2.2, 2.3, 2.4, 2.6, 2.7, 2.8, 12.2, 12.3
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.analyzer import (
    DocumentAnalyzer,
    PaperlessNGXClient,
    _apply_creation_policy,
    _build_suggestion,
    _parse_llm_response,
    resolve_prompt_template,
    truncate_to_context_window,
)
from backend.models import MetadataSuggestion, PaperlessIQConfig

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_doc_id_strategy = st.integers(min_value=1, max_value=100_000)

_text_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs", "Po")),
    min_size=0,
    max_size=5_000,
)

_long_text_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
    min_size=1,
    max_size=20_000,
)

_tag_strategy = st.lists(
    st.text(alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), min_size=1, max_size=30),
    min_size=0,
    max_size=10,
)

_analysis_mode_strategy = st.sampled_from(["ocr", "full_document"])

_doctype_id_strategy = st.one_of(st.none(), st.integers(min_value=1, max_value=999))

_prompt_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs", "Po")),
    min_size=1,
    max_size=200,
)


def _config_strategy(
    default_mode: str | None = None,
    per_doctype_mode: dict | None = None,
    global_prompt: str = "",
    per_field_prompts: dict | None = None,
    per_doctype_prompts: dict | None = None,
) -> PaperlessIQConfig:
    return PaperlessIQConfig(
        llm_provider="openai",
        llm_model="gpt-4o",
        default_analysis_mode=default_mode or "ocr",
        per_doctype_analysis_mode=per_doctype_mode or {},
        global_prompt_template=global_prompt,
        per_field_prompt_templates=per_field_prompts or {},
        per_doctype_prompt_templates=per_doctype_prompts or {},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_provider(response_text: str = '{"title": "Test", "tags": []}') -> AsyncMock:
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value=response_text)
    return provider


def _make_mock_paperless(ocr_text: str = "ocr content", doc_bytes: bytes = b"pdf bytes") -> AsyncMock:
    client = AsyncMock(spec=PaperlessNGXClient)
    client.get_document_ocr_text = AsyncMock(return_value=ocr_text)
    client.get_document_bytes = AsyncMock(return_value=doc_bytes)
    # OCR text is embedded in the metadata response so analyze() does not need a
    # second API call in OCR mode.
    client.get_document_metadata = AsyncMock(return_value={"document_type": None, "content": ocr_text})
    return client


# ---------------------------------------------------------------------------
# Property 1: LLM input mode selection
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    ocr_text=_text_strategy,
    doc_bytes=st.binary(min_size=1, max_size=500),
    default_mode=_analysis_mode_strategy,
    doctype_id=_doctype_id_strategy,
)
@pytest.mark.asyncio
async def test_property_1_llm_input_mode_selection(
    document_id: int,
    ocr_text: str,
    doc_bytes: bytes,
    default_mode: str,
    doctype_id: int | None,
) -> None:
    """
    # Feature: paperless-iq, Property 1: LLM input mode selection

    For any document submitted for analysis, the content sent to the LLM must be
    the Full_Document bytes when full-document mode is enabled for that document's
    type, and the OCR_Text otherwise. The two modes must never be mixed.

    Validates: Requirements 1.1, 1.2
    """
    config = _config_strategy(default_mode=default_mode)
    provider = _make_mock_provider()
    paperless = _make_mock_paperless(ocr_text=ocr_text, doc_bytes=doc_bytes)
    # Metadata response includes the content field so analyze() can avoid a
    # second API call in OCR mode.
    paperless.get_document_metadata = AsyncMock(
        return_value={"document_type": doctype_id, "content": ocr_text}
    )

    analyzer = DocumentAnalyzer(
        provider=provider,
        paperless_client=paperless,
        config=config,
        provider_name="openai",
    )

    await analyzer.analyze(document_id)

    # Determine expected mode
    expected_mode = config.per_doctype_analysis_mode.get(doctype_id, default_mode) if doctype_id else default_mode

    if expected_mode == "full_document":
        paperless.get_document_bytes.assert_called_once_with(document_id)
        # get_document_ocr_text must NOT be called — bytes mode fetches the file directly
        paperless.get_document_ocr_text.assert_not_called()
        # The prompt passed to the LLM must contain the decoded bytes content
        call_args = provider.complete.call_args
        prompt_sent = call_args[0][0]
        assert doc_bytes.decode("utf-8", errors="replace") in prompt_sent or len(doc_bytes) == 0
    else:
        # OCR mode: content comes from get_document_metadata(), NOT a separate
        # get_document_ocr_text() call.
        paperless.get_document_ocr_text.assert_not_called()
        paperless.get_document_bytes.assert_not_called()
        # The prompt must contain the OCR text
        call_args = provider.complete.call_args
        prompt_sent = call_args[0][0]
        # Truncation may have occurred; check the text is a prefix of what was sent
        assert ocr_text[:50] in prompt_sent or len(ocr_text) == 0 or ocr_text[:50] in prompt_sent


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    doctype_id=st.integers(min_value=1, max_value=999),
    per_doctype_mode=_analysis_mode_strategy,
    default_mode=_analysis_mode_strategy,
)
@pytest.mark.asyncio
async def test_property_1_per_doctype_mode_overrides_default(
    document_id: int,
    doctype_id: int,
    per_doctype_mode: str,
    default_mode: str,
) -> None:
    """
    # Feature: paperless-iq, Property 1: LLM input mode selection (per-doctype override)

    Per-document-type mode must override the global default.

    Validates: Requirements 1.3
    """
    config = PaperlessIQConfig(
        llm_provider="openai",
        llm_model="gpt-4o",
        default_analysis_mode=default_mode,  # type: ignore[arg-type]
        per_doctype_analysis_mode={doctype_id: per_doctype_mode},  # type: ignore[dict-item]
    )
    provider = _make_mock_provider()
    paperless = _make_mock_paperless()
    paperless.get_document_metadata = AsyncMock(
        return_value={"document_type": doctype_id, "content": "sample ocr text"}
    )

    analyzer = DocumentAnalyzer(
        provider=provider,
        paperless_client=paperless,
        config=config,
        provider_name="openai",
    )

    await analyzer.analyze(document_id)

    if per_doctype_mode == "full_document":
        paperless.get_document_bytes.assert_called_once()
        paperless.get_document_ocr_text.assert_not_called()
    else:
        # OCR mode: content comes from the metadata response, no separate ocr call
        paperless.get_document_ocr_text.assert_not_called()
        paperless.get_document_bytes.assert_not_called()


# ---------------------------------------------------------------------------
# Property 2: Context window truncation
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    text=_long_text_strategy,
    context_limit=st.integers(min_value=10, max_value=500),
    document_id=_doc_id_strategy,
)
def test_property_2_truncation_respects_limit(
    text: str,
    context_limit: int,
    document_id: int,
) -> None:
    """
    # Feature: paperless-iq, Property 2: Context window truncation

    For any text that exceeds the context window limit, the truncated result
    must be at most context_limit characters long.

    Validates: Requirements 1.4
    """
    result = truncate_to_context_window(text, context_limit, document_id)
    assert len(result) <= context_limit


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    text=_long_text_strategy,
    context_limit=st.integers(min_value=10, max_value=500),
    document_id=_doc_id_strategy,
)
def test_property_2_truncation_logs_warning_when_needed(
    text: str,
    context_limit: int,
    document_id: int,
) -> None:
    """
    # Feature: paperless-iq, Property 2: Context window truncation (warning logged)

    When truncation occurs, a warning must be logged. When no truncation is
    needed, no warning is emitted.

    Validates: Requirements 1.4
    """
    # Use a custom handler to capture log records within this call only
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    analyzer_logger = logging.getLogger("backend.analyzer")
    handler = _Capture(level=logging.WARNING)
    analyzer_logger.addHandler(handler)
    try:
        truncate_to_context_window(text, context_limit, document_id)
    finally:
        analyzer_logger.removeHandler(handler)

    if len(text) > context_limit:
        assert any("truncat" in r.getMessage().lower() for r in records), (
            f"Expected a truncation warning for text of length {len(text)} "
            f"with limit {context_limit}"
        )
    else:
        assert not any("truncat" in r.getMessage().lower() for r in records), (
            "No truncation warning expected when text fits within context window"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    text=_long_text_strategy,
    context_limit=st.integers(min_value=10, max_value=500),
    document_id=_doc_id_strategy,
)
def test_property_2_truncated_text_is_prefix(
    text: str,
    context_limit: int,
    document_id: int,
) -> None:
    """
    # Feature: paperless-iq, Property 2: Context window truncation (prefix preserved)

    The truncated text must be a prefix of the original text.

    Validates: Requirements 1.4
    """
    result = truncate_to_context_window(text, context_limit, document_id)
    assert text.startswith(result), (
        "Truncated text must be a prefix of the original"
    )


# ---------------------------------------------------------------------------
# Property 3: Metadata suggestion completeness
# ---------------------------------------------------------------------------

_llm_response_strategy = st.fixed_dictionaries({
    "title": st.one_of(st.none(), st.text(min_size=0, max_size=100)),
    "tags": st.one_of(st.none(), _tag_strategy),
    "correspondent": st.one_of(st.none(), st.text(min_size=0, max_size=50)),
    "document_type": st.one_of(st.none(), st.text(min_size=0, max_size=50)),
    "storage_path": st.one_of(st.none(), st.text(min_size=0, max_size=100)),
    "custom_fields": st.one_of(st.none(), st.fixed_dictionaries({})),
})


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    parsed=_llm_response_strategy,
)
def test_property_3_suggestion_completeness(
    document_id: int,
    parsed: dict[str, Any],
) -> None:
    """
    # Feature: paperless-iq, Property 3: Metadata suggestion completeness

    For any completed document analysis, the resulting MetadataSuggestion must
    contain entries for all required fields — even if the LLM returns null/empty
    values (represented as None or empty list/dict).

    Validates: Requirements 2.1
    """
    suggestion = _build_suggestion(
        document_id=document_id,
        parsed=parsed,
        llm_provider="openai",
        llm_model="gpt-4o",
        analysis_mode="ocr",
        prompt_used="test prompt",
        raw_llm_response=json.dumps(parsed),
    )

    # All required fields must be present (not missing from the model)
    assert hasattr(suggestion, "title")
    assert hasattr(suggestion, "tags")
    assert hasattr(suggestion, "correspondent")
    assert hasattr(suggestion, "document_type")
    assert hasattr(suggestion, "storage_path")
    assert hasattr(suggestion, "custom_fields")

    # tags and custom_fields must be collections (never None)
    assert suggestion.tags is not None
    assert isinstance(suggestion.tags, list)
    assert suggestion.custom_fields is not None
    assert isinstance(suggestion.custom_fields, dict)

    # Provenance fields must be populated
    assert suggestion.llm_provider == "openai"
    assert suggestion.llm_model == "gpt-4o"
    assert suggestion.analysis_mode in ("ocr", "full_document")
    assert isinstance(suggestion.prompt_used, str)
    assert isinstance(suggestion.raw_llm_response, str)


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(document_id=_doc_id_strategy)
def test_property_3_empty_llm_response_still_complete(document_id: int) -> None:
    """
    # Feature: paperless-iq, Property 3: Metadata suggestion completeness (empty response)

    Even when the LLM returns an empty or unparseable response, the suggestion
    must still have all required fields present.

    Validates: Requirements 2.1
    """
    suggestion = _build_suggestion(
        document_id=document_id,
        parsed={},
        llm_provider="openai",
        llm_model="gpt-4o",
        analysis_mode="ocr",
        prompt_used="test",
        raw_llm_response="",
    )

    assert suggestion.tags == []
    assert suggestion.custom_fields == {}
    assert suggestion.title is None
    assert suggestion.correspondent is None
    assert suggestion.document_type is None
    assert suggestion.storage_path is None


# ---------------------------------------------------------------------------
# Property 4: Metadata suggestion JSON schema conformance
# ---------------------------------------------------------------------------

# Minimal Paperless NGX REST API schema for a metadata update payload
_PAPERLESS_PATCH_SCHEMA_KEYS = {"title", "tags", "correspondent", "document_type", "storage_path"}


def _validate_against_paperless_schema(data: dict) -> list[str]:
    """
    Validate a serialized MetadataSuggestion against the Paperless NGX REST API
    schema for a document PATCH payload.

    Returns a list of validation error messages (empty = valid).
    """
    errors: list[str] = []

    if "title" in data and data["title"] is not None:
        if not isinstance(data["title"], str):
            errors.append(f"title must be str, got {type(data['title'])}")

    if "tags" in data:
        if not isinstance(data["tags"], list):
            errors.append(f"tags must be list, got {type(data['tags'])}")
        else:
            for tag in data["tags"]:
                if not isinstance(tag, str):
                    errors.append(f"each tag must be str, got {type(tag)}")

    if "correspondent" in data and data["correspondent"] is not None:
        if not isinstance(data["correspondent"], str):
            errors.append(f"correspondent must be str or null")

    if "document_type" in data and data["document_type"] is not None:
        if not isinstance(data["document_type"], str):
            errors.append(f"document_type must be str or null")

    if "storage_path" in data and data["storage_path"] is not None:
        if not isinstance(data["storage_path"], str):
            errors.append(f"storage_path must be str or null")

    if "custom_fields" in data:
        if not isinstance(data["custom_fields"], dict):
            errors.append(f"custom_fields must be dict")

    return errors


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    parsed=_llm_response_strategy,
    analysis_mode=_analysis_mode_strategy,
)
def test_property_4_json_schema_conformance(
    document_id: int,
    parsed: dict[str, Any],
    analysis_mode: str,
) -> None:
    """
    # Feature: paperless-iq, Property 4: Metadata suggestion JSON schema conformance

    For any MetadataSuggestion, serializing it to JSON and validating against
    the Paperless NGX REST API schema must succeed without errors.

    Validates: Requirements 2.2
    """
    suggestion = _build_suggestion(
        document_id=document_id,
        parsed=parsed,
        llm_provider="openai",
        llm_model="gpt-4o",
        analysis_mode=analysis_mode,
        prompt_used="test",
        raw_llm_response=json.dumps(parsed),
    )

    # Serialize to JSON (as it would be sent over HTTP)
    serialized = suggestion.model_dump(mode="json")

    # Must be JSON-serializable without error
    json_str = json.dumps(serialized)
    assert isinstance(json_str, str)

    # Re-parse to get the dict for schema validation
    reparsed = json.loads(json_str)

    # Validate against Paperless NGX schema
    errors = _validate_against_paperless_schema(reparsed)
    assert errors == [], (
        f"MetadataSuggestion failed schema validation: {errors}\n"
        f"Suggestion: {reparsed}"
    )


# ---------------------------------------------------------------------------
# Property 5: Prompt template resolution
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    doctype_id=st.integers(min_value=1, max_value=999),
    per_doctype_prompt=_prompt_strategy,
    per_field_prompt=_prompt_strategy,
    global_prompt=_prompt_strategy,
)
def test_property_5_per_doctype_template_takes_priority(
    doctype_id: int,
    per_doctype_prompt: str,
    per_field_prompt: str,
    global_prompt: str,
) -> None:
    """
    # Feature: paperless-iq, Property 5: Prompt template resolution

    When a per-document-type template is configured, it must be selected over
    per-field and global templates.

    Validates: Requirements 2.3, 12.2
    """
    config = _config_strategy(
        global_prompt=global_prompt,
        per_field_prompts={"title": per_field_prompt},
        per_doctype_prompts={doctype_id: per_doctype_prompt},
    )

    result = resolve_prompt_template(config, document_type_id=doctype_id, field="title")
    assert result == per_doctype_prompt, (
        f"Per-doctype template must take priority. "
        f"Expected {per_doctype_prompt!r}, got {result!r}"
    )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    doctype_id=st.integers(min_value=1, max_value=999),
    per_field_prompt=_prompt_strategy,
    global_prompt=_prompt_strategy,
)
def test_property_5_per_field_template_when_no_doctype(
    doctype_id: int,
    per_field_prompt: str,
    global_prompt: str,
) -> None:
    """
    # Feature: paperless-iq, Property 5: Prompt template resolution (per-field fallback)

    When no per-doctype template is configured, the per-field template must be used.

    Validates: Requirements 2.3, 2.4
    """
    config = _config_strategy(
        global_prompt=global_prompt,
        per_field_prompts={"title": per_field_prompt},
        per_doctype_prompts={},  # no per-doctype template
    )

    result = resolve_prompt_template(config, document_type_id=doctype_id, field="title")
    assert result == per_field_prompt, (
        f"Per-field template must be used when no per-doctype template exists. "
        f"Expected {per_field_prompt!r}, got {result!r}"
    )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    global_prompt=_prompt_strategy,
)
def test_property_5_global_template_fallback(global_prompt: str) -> None:
    """
    # Feature: paperless-iq, Property 5: Prompt template resolution (global fallback)

    When neither per-doctype nor per-field templates are configured, the global
    template must be used.

    Validates: Requirements 2.4, 12.3
    """
    config = _config_strategy(
        global_prompt=global_prompt,
        per_field_prompts={},
        per_doctype_prompts={},
    )

    result = resolve_prompt_template(config, document_type_id=None, field="title")
    assert result == global_prompt, (
        f"Global template must be used as fallback. "
        f"Expected {global_prompt!r}, got {result!r}"
    )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    doctype_id=_doctype_id_strategy,
    global_prompt=st.text(min_size=0, max_size=200),
)
def test_property_5_builtin_default_when_nothing_configured(
    doctype_id: int | None,
    global_prompt: str,
) -> None:
    """
    # Feature: paperless-iq, Property 5: Prompt template resolution (global fallback)

    When no per-doctype or per-field template is configured, the global template
    must be returned unchanged.

    Validates: Requirements 2.4
    """
    config = _config_strategy(
        global_prompt=global_prompt,
        per_field_prompts={},
        per_doctype_prompts={},
    )

    result = resolve_prompt_template(config, document_type_id=doctype_id, field=None)
    assert result == config.global_prompt_template


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    doctype_id=st.integers(min_value=1, max_value=999),
    other_doctype_id=st.integers(min_value=1000, max_value=1999),
    per_doctype_prompt=_prompt_strategy,
    global_prompt=_prompt_strategy,
)
def test_property_5_unmatched_doctype_falls_back_to_global(
    doctype_id: int,
    other_doctype_id: int,
    per_doctype_prompt: str,
    global_prompt: str,
) -> None:
    """
    # Feature: paperless-iq, Property 5: Prompt template resolution (unmatched doctype)

    When a per-doctype template is configured for a different document type,
    the global template must be used for the current document type.

    Validates: Requirements 12.3
    """
    config = _config_strategy(
        global_prompt=global_prompt,
        per_doctype_prompts={other_doctype_id: per_doctype_prompt},
    )

    result = resolve_prompt_template(config, document_type_id=doctype_id, field=None)
    assert result == global_prompt, (
        f"Global template must be used when doctype {doctype_id} has no configured template. "
        f"Expected {global_prompt!r}, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Property 6: Creation policy enforcement
# ---------------------------------------------------------------------------

# Strategies for entity names: non-empty strings of letters/digits
_entity_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=1,
    max_size=30,
)

_creation_policy_strategy = st.sampled_from(["existing_only", "allow_new"])


def _make_suggestion_with_entities(
    document_id: int,
    tags: list[str],
    correspondent: str | None,
    document_type: str | None,
) -> MetadataSuggestion:
    """Build a MetadataSuggestion with specific entity values."""
    return _build_suggestion(
        document_id=document_id,
        parsed={
            "title": "Test",
            "tags": tags,
            "correspondent": correspondent,
            "document_type": document_type,
        },
        llm_provider="openai",
        llm_model="gpt-4o",
        analysis_mode="ocr",
        prompt_used="test",
        raw_llm_response="{}",
    )


def _make_config_with_policies(
    tag_policy: str,
    correspondent_policy: str,
    doctype_policy: str,
) -> PaperlessIQConfig:
    return PaperlessIQConfig(
        llm_provider="openai",
        llm_model="gpt-4o",
        tag_creation_policy=tag_policy,  # type: ignore[arg-type]
        correspondent_creation_policy=correspondent_policy,  # type: ignore[arg-type]
        doctype_creation_policy=doctype_policy,  # type: ignore[arg-type]
    )


def _make_mock_paperless_with_entities(
    existing_tags: list[str],
    existing_correspondents: list[str],
    existing_doctypes: list[str],
) -> AsyncMock:
    """
    Build a mock PaperlessNGXClient whose list_entities returns the given lists
    and whose create_entity is a no-op that records calls.
    """
    client = AsyncMock(spec=PaperlessNGXClient)

    async def _list_entities(entity_type: str) -> list[str]:
        if entity_type == "tags":
            return list(existing_tags)
        if entity_type == "correspondents":
            return list(existing_correspondents)
        if entity_type == "document_types":
            return list(existing_doctypes)
        return []

    client.list_entities = AsyncMock(side_effect=_list_entities)
    client.create_entity = AsyncMock(return_value=None)
    return client


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    existing_tags=st.lists(_entity_name_strategy, min_size=0, max_size=10),
    suggested_tags=st.lists(_entity_name_strategy, min_size=0, max_size=10),
    tag_policy=_creation_policy_strategy,
)
@pytest.mark.asyncio
async def test_property_6_tag_creation_policy(
    document_id: int,
    existing_tags: list[str],
    suggested_tags: list[str],
    tag_policy: str,
) -> None:
    """
    # Feature: paperless-iq, Property 6: Creation policy enforcement

    For tags with "existing_only" policy, only tags already present in Paperless NGX
    may appear in the final suggestion. With "allow_new", all suggested tags are kept.

    Validates: Requirements 2.6, 2.7
    """
    suggestion = _make_suggestion_with_entities(
        document_id=document_id,
        tags=suggested_tags,
        correspondent=None,
        document_type=None,
    )
    config = _make_config_with_policies(
        tag_policy=tag_policy,
        correspondent_policy="existing_only",
        doctype_policy="existing_only",
    )
    paperless = _make_mock_paperless_with_entities(
        existing_tags=existing_tags,
        existing_correspondents=[],
        existing_doctypes=[],
    )

    result = await _apply_creation_policy(suggestion, config, paperless)

    existing_lower = {t.lower() for t in existing_tags}

    if tag_policy == "existing_only":
        # All result tags must be in the existing set
        for tag in result.tags:
            assert tag.lower() in existing_lower, (
                f"Tag {tag!r} not in existing set {existing_tags!r} "
                f"but appeared in result with 'existing_only' policy"
            )
    else:  # allow_new
        # All originally suggested tags must still be present
        assert set(result.tags) == set(suggested_tags), (
            f"With 'allow_new' policy, all suggested tags must be kept. "
            f"Expected {suggested_tags!r}, got {result.tags!r}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    existing_correspondents=st.lists(_entity_name_strategy, min_size=0, max_size=10),
    suggested_correspondent=st.one_of(st.none(), _entity_name_strategy),
    correspondent_policy=_creation_policy_strategy,
)
@pytest.mark.asyncio
async def test_property_6_correspondent_creation_policy(
    document_id: int,
    existing_correspondents: list[str],
    suggested_correspondent: str | None,
    correspondent_policy: str,
) -> None:
    """
    # Feature: paperless-iq, Property 6: Creation policy enforcement (correspondents)

    For correspondents with "existing_only" policy, a suggested correspondent not
    already in Paperless NGX must be removed from the suggestion. With "allow_new",
    it is kept.

    Validates: Requirements 2.8
    """
    suggestion = _make_suggestion_with_entities(
        document_id=document_id,
        tags=[],
        correspondent=suggested_correspondent,
        document_type=None,
    )
    config = _make_config_with_policies(
        tag_policy="existing_only",
        correspondent_policy=correspondent_policy,
        doctype_policy="existing_only",
    )
    paperless = _make_mock_paperless_with_entities(
        existing_tags=[],
        existing_correspondents=existing_correspondents,
        existing_doctypes=[],
    )

    result = await _apply_creation_policy(suggestion, config, paperless)

    existing_lower = {c.lower() for c in existing_correspondents}

    if suggested_correspondent is None:
        assert result.correspondent is None
    elif correspondent_policy == "existing_only":
        if suggested_correspondent.lower() not in existing_lower:
            assert result.correspondent is None, (
                f"Correspondent {suggested_correspondent!r} not in existing set "
                f"but kept with 'existing_only' policy"
            )
        else:
            assert result.correspondent == suggested_correspondent
    else:  # allow_new
        assert result.correspondent == suggested_correspondent, (
            f"With 'allow_new' policy, correspondent must be kept. "
            f"Expected {suggested_correspondent!r}, got {result.correspondent!r}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    existing_doctypes=st.lists(_entity_name_strategy, min_size=0, max_size=10),
    suggested_doctype=st.one_of(st.none(), _entity_name_strategy),
    doctype_policy=_creation_policy_strategy,
)
@pytest.mark.asyncio
async def test_property_6_doctype_creation_policy(
    document_id: int,
    existing_doctypes: list[str],
    suggested_doctype: str | None,
    doctype_policy: str,
) -> None:
    """
    # Feature: paperless-iq, Property 6: Creation policy enforcement (document types)

    For document types with "existing_only" policy, a suggested document type not
    already in Paperless NGX must be removed from the suggestion. With "allow_new",
    it is kept.

    Validates: Requirements 2.8
    """
    suggestion = _make_suggestion_with_entities(
        document_id=document_id,
        tags=[],
        correspondent=None,
        document_type=suggested_doctype,
    )
    config = _make_config_with_policies(
        tag_policy="existing_only",
        correspondent_policy="existing_only",
        doctype_policy=doctype_policy,
    )
    paperless = _make_mock_paperless_with_entities(
        existing_tags=[],
        existing_correspondents=[],
        existing_doctypes=existing_doctypes,
    )

    result = await _apply_creation_policy(suggestion, config, paperless)

    existing_lower = {d.lower() for d in existing_doctypes}

    if suggested_doctype is None:
        assert result.document_type is None
    elif doctype_policy == "existing_only":
        if suggested_doctype.lower() not in existing_lower:
            assert result.document_type is None, (
                f"Document type {suggested_doctype!r} not in existing set "
                f"but kept with 'existing_only' policy"
            )
        else:
            assert result.document_type == suggested_doctype
    else:  # allow_new
        assert result.document_type == suggested_doctype, (
            f"With 'allow_new' policy, document type must be kept. "
            f"Expected {suggested_doctype!r}, got {result.document_type!r}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=_doc_id_strategy,
    existing_tags=st.lists(_entity_name_strategy, min_size=1, max_size=8),
    new_tags=st.lists(_entity_name_strategy, min_size=1, max_size=5),
)
@pytest.mark.asyncio
async def test_property_6_allow_new_keeps_all_suggested_entities(
    document_id: int,
    existing_tags: list[str],
    new_tags: list[str],
) -> None:
    """
    # Feature: paperless-iq, Property 6: Creation policy enforcement (allow_new)

    With "allow_new" policy, all suggested tags are kept in the result
    regardless of whether they exist in Paperless NGX. Entity creation
    is deferred to approval time.

    Validates: Requirements 2.7
    """
    # Ensure new_tags are genuinely new (not in existing_tags, case-insensitive)
    existing_lower = {t.lower() for t in existing_tags}
    truly_new = [t for t in new_tags if t.lower() not in existing_lower]

    all_suggested = existing_tags[:3] + truly_new  # mix of existing + new

    suggestion = _make_suggestion_with_entities(
        document_id=document_id,
        tags=all_suggested,
        correspondent=None,
        document_type=None,
    )
    config = _make_config_with_policies(
        tag_policy="allow_new",
        correspondent_policy="existing_only",
        doctype_policy="existing_only",
    )
    paperless = _make_mock_paperless_with_entities(
        existing_tags=existing_tags,
        existing_correspondents=[],
        existing_doctypes=[],
    )

    result = await _apply_creation_policy(suggestion, config, paperless)

    # All suggested tags must be kept in the result (no filtering)
    assert set(result.tags) == set(all_suggested)

    # create_entity must NOT be called — creation is deferred to approval
    paperless.create_entity.assert_not_called()
