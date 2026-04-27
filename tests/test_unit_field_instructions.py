# Feature: paperless-live-integration, Task 4.3
# Unit tests for DocumentAnalyzer._build_field_instructions()
# Validates: Requirements 9.1, 9.2, 9.3, 9.4, 5.5

from __future__ import annotations

from unittest.mock import AsyncMock

from backend.analyzer import DocumentAnalyzer
from backend.models import PaperlessIQConfig


def _make_analyzer(
    field_descriptions: dict[str, str] | None = None,
    custom_field_defs: list[dict] | None = None,
) -> DocumentAnalyzer:
    """Create a DocumentAnalyzer with minimal mocks for unit testing."""
    config = PaperlessIQConfig(
        llm_provider="ollama",
        llm_model="test",
        field_descriptions=field_descriptions or {},
    )
    provider = AsyncMock()
    client = AsyncMock()
    analyzer = DocumentAnalyzer(
        provider=provider,
        paperless_client=client,
        config=config,
        provider_name="ollama",
    )
    if custom_field_defs is not None:
        analyzer._custom_field_defs = custom_field_defs
    return analyzer


class TestBuildFieldInstructions:
    """Tests for _build_field_instructions()."""

    def test_empty_descriptions_returns_empty(self) -> None:
        analyzer = _make_analyzer(field_descriptions={})
        assert analyzer._build_field_instructions() == ""

    def test_core_field_description(self) -> None:
        analyzer = _make_analyzer(field_descriptions={"title": "Use a descriptive title"})
        result = analyzer._build_field_instructions()
        assert result == "Instructions for title: Use a descriptive title"

    def test_multiple_core_fields(self) -> None:
        analyzer = _make_analyzer(field_descriptions={
            "title": "Use a descriptive title",
            "tags": "Pick relevant tags",
        })
        result = analyzer._build_field_instructions()
        assert "Instructions for title: Use a descriptive title" in result
        assert "Instructions for tags: Pick relevant tags" in result

    def test_custom_field_resolved_by_id(self) -> None:
        analyzer = _make_analyzer(
            field_descriptions={"cf:42": "Extract the invoice number"},
            custom_field_defs=[
                {"id": 42, "name": "Invoice Number", "data_type": "string"},
            ],
        )
        result = analyzer._build_field_instructions()
        assert result == "Instructions for Invoice Number: Extract the invoice number"

    def test_custom_field_unknown_id_skipped(self) -> None:
        analyzer = _make_analyzer(
            field_descriptions={"cf:999": "Some instruction"},
            custom_field_defs=[
                {"id": 42, "name": "Invoice Number", "data_type": "string"},
            ],
        )
        result = analyzer._build_field_instructions()
        assert result == ""

    def test_empty_description_skipped(self) -> None:
        analyzer = _make_analyzer(field_descriptions={"title": "", "tags": "Pick tags"})
        result = analyzer._build_field_instructions()
        assert "title" not in result
        assert "Instructions for tags: Pick tags" in result

    def test_invalid_cf_key_skipped(self) -> None:
        analyzer = _make_analyzer(
            field_descriptions={"cf:abc": "Bad key"},
            custom_field_defs=[],
        )
        result = analyzer._build_field_instructions()
        assert result == ""

    def test_mixed_core_and_custom_fields(self) -> None:
        analyzer = _make_analyzer(
            field_descriptions={
                "title": "Use a descriptive title",
                "cf:10": "Extract the invoice number",
            },
            custom_field_defs=[
                {"id": 10, "name": "Invoice Number", "data_type": "string"},
            ],
        )
        result = analyzer._build_field_instructions()
        assert "Instructions for title: Use a descriptive title" in result
        assert "Instructions for Invoice Number: Extract the invoice number" in result

    def test_custom_field_defs_not_set_uses_init_default(self) -> None:
        """When _fetch_entity_context hasn't run, _custom_field_defs is empty list."""
        analyzer = _make_analyzer(
            field_descriptions={"cf:1": "Some instruction"},
        )
        # _custom_field_defs defaults to [] from __init__
        result = analyzer._build_field_instructions()
        assert result == ""
