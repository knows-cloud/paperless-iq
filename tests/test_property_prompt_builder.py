# Feature: paperless-live-integration, Property 4: Field descriptions in prompt
# Feature: paperless-live-integration, Property 11: Entity lists in prompt
"""Property-based tests for DocumentAnalyzer prompt builder enhancements.

Validates: Requirements 5.5, 9.1, 9.2, 9.3, 9.4, 12.1, 12.2, 12.3, 12.4, 12.5
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.analyzer import DocumentAnalyzer, PaperlessNGXClient
from backend.models import PaperlessIQConfig

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid core field names that _build_field_instructions handles directly
_core_field_names = st.sampled_from([
    "title", "tags", "correspondent", "document_type", "storage_path",
])

# Non-empty description text (printable, no control chars)
_description_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs", "Po")),
    min_size=1,
    max_size=100,
)

# Dict of core field name -> description (at least 1 entry)
_field_descriptions_strategy = st.dictionaries(
    keys=_core_field_names,
    values=_description_strategy,
    min_size=1,
    max_size=5,
)

# Entity name: non-empty printable string without commas (commas are join delimiters)
_entity_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=1,
    max_size=30,
)

_tag_list_strategy = st.lists(_entity_name_strategy, min_size=0, max_size=10)
_correspondent_list_strategy = st.lists(_entity_name_strategy, min_size=0, max_size=10)
_doctype_list_strategy = st.lists(_entity_name_strategy, min_size=0, max_size=10)

# Custom field definition dicts
_custom_field_def_strategy = st.fixed_dictionaries({
    "id": st.integers(min_value=1, max_value=9999),
    "name": _entity_name_strategy,
    "data_type": st.sampled_from(["string", "integer", "float", "date", "boolean", "url"]),
})

_custom_field_defs_strategy = st.lists(
    _custom_field_def_strategy,
    min_size=0,
    max_size=8,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(field_descriptions: dict[str, str] | None = None) -> PaperlessIQConfig:
    """Build a minimal PaperlessIQConfig with optional field_descriptions."""
    return PaperlessIQConfig(
        llm_provider="openai",
        llm_model="gpt-4o",
        field_descriptions=field_descriptions or {},
    )


def _make_analyzer(
    config: PaperlessIQConfig,
    paperless: AsyncMock | None = None,
) -> DocumentAnalyzer:
    """Build a DocumentAnalyzer with mock provider and client."""
    provider = AsyncMock()
    if paperless is None:
        paperless = AsyncMock(spec=PaperlessNGXClient)
    return DocumentAnalyzer(
        provider=provider,
        paperless_client=paperless,
        config=config,
        provider_name="openai",
    )


def _make_mock_paperless(
    tags: list[str],
    correspondents: list[str],
    document_types: list[str],
    custom_field_defs: list[dict[str, Any]],
) -> AsyncMock:
    """Build a mock PaperlessNGXClient returning the given entity lists."""
    client = AsyncMock(spec=PaperlessNGXClient)

    async def _list_entities(entity_type: str) -> list[str]:
        if entity_type == "tags":
            return list(tags)
        if entity_type == "correspondents":
            return list(correspondents)
        if entity_type == "document_types":
            return list(document_types)
        return []

    client.list_entities = AsyncMock(side_effect=_list_entities)
    client.list_custom_field_definitions = AsyncMock(return_value=list(custom_field_defs))
    return client


# ---------------------------------------------------------------------------
# Property 4: Field descriptions in prompt
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(field_descriptions=_field_descriptions_strategy)
def test_property_4_field_descriptions_appear_in_prompt(
    field_descriptions: dict[str, str],
) -> None:
    """
    # Feature: paperless-live-integration, Property 4: Field descriptions in prompt

    For any non-empty field_descriptions dictionary in the config, the prompt
    built by DocumentAnalyzer._build_field_instructions() shall contain a
    labeled instruction section for every entry in the dictionary.

    **Validates: Requirements 5.5, 9.1, 9.2**
    """
    config = _make_config(field_descriptions=field_descriptions)
    analyzer = _make_analyzer(config)
    # No custom fields for this test — only core field names
    analyzer._custom_field_defs = []

    result = analyzer._build_field_instructions()

    for field_name, description in field_descriptions.items():
        expected = f"Instructions for {field_name}: {description}"
        assert expected in result, (
            f"Expected instruction line {expected!r} not found in result:\n{result}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(field_descriptions=_field_descriptions_strategy)
def test_property_4_absent_fields_not_in_prompt(
    field_descriptions: dict[str, str],
) -> None:
    """
    # Feature: paperless-live-integration, Property 4: Field descriptions in prompt

    For any field NOT present in field_descriptions, the prompt shall not
    contain an instruction section for that field.

    **Validates: Requirements 9.4**
    """
    all_core_fields = {"title", "tags", "correspondent", "document_type", "storage_path"}
    absent_fields = all_core_fields - set(field_descriptions.keys())

    config = _make_config(field_descriptions=field_descriptions)
    analyzer = _make_analyzer(config)
    analyzer._custom_field_defs = []

    result = analyzer._build_field_instructions()

    for field_name in absent_fields:
        marker = f"Instructions for {field_name}:"
        assert marker not in result, (
            f"Instruction for absent field {field_name!r} should not appear in result:\n{result}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    field_descriptions=_field_descriptions_strategy,
)
def test_property_4_instruction_count_matches(
    field_descriptions: dict[str, str],
) -> None:
    """
    # Feature: paperless-live-integration, Property 4: Field descriptions in prompt

    The number of instruction lines shall equal the number of entries in
    field_descriptions (for core fields with no custom field keys).

    **Validates: Requirements 9.1, 9.2, 9.3**
    """
    config = _make_config(field_descriptions=field_descriptions)
    analyzer = _make_analyzer(config)
    analyzer._custom_field_defs = []

    result = analyzer._build_field_instructions()
    lines = [line for line in result.split("\n") if line.strip()]

    assert len(lines) == len(field_descriptions), (
        f"Expected {len(field_descriptions)} instruction lines, got {len(lines)}.\n"
        f"Lines: {lines}"
    )


# ---------------------------------------------------------------------------
# Property 11: Entity lists in prompt
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    tags=_tag_list_strategy,
    correspondents=_correspondent_list_strategy,
    document_types=_doctype_list_strategy,
    custom_field_defs=_custom_field_defs_strategy,
)
@pytest.mark.asyncio
async def test_property_11_entity_lists_appear_in_prompt(
    tags: list[str],
    correspondents: list[str],
    document_types: list[str],
    custom_field_defs: list[dict[str, Any]],
) -> None:
    """
    # Feature: paperless-live-integration, Property 11: Entity lists in prompt

    For any set of entity lists returned by PaperlessNGXClient, the prompt
    built by DocumentAnalyzer._fetch_entity_context() shall contain a labeled
    section for each non-empty entity type that includes every entity name.

    **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**
    """
    paperless = _make_mock_paperless(tags, correspondents, document_types, custom_field_defs)
    config = _make_config()
    analyzer = _make_analyzer(config, paperless=paperless)

    result = await analyzer._fetch_entity_context()

    # Tags
    if tags:
        assert "Available tags:" in result, "Missing 'Available tags:' section"
        for tag in tags:
            assert tag in result, f"Tag {tag!r} not found in entity context"
    else:
        assert "Available tags:" not in result, "Empty tag list should not produce a section"

    # Correspondents
    if correspondents:
        assert "Available correspondents:" in result, "Missing 'Available correspondents:' section"
        for corr in correspondents:
            assert corr in result, f"Correspondent {corr!r} not found in entity context"
    else:
        assert "Available correspondents:" not in result, "Empty correspondent list should not produce a section"

    # Document types
    if document_types:
        assert "Available document types:" in result, "Missing 'Available document types:' section"
        for dt in document_types:
            assert dt in result, f"Document type {dt!r} not found in entity context"
    else:
        assert "Available document types:" not in result, "Empty document type list should not produce a section"

    # Custom fields
    if custom_field_defs:
        assert "Available custom fields:" in result, "Missing 'Available custom fields:' section"
        for cf in custom_field_defs:
            assert cf["name"] in result, f"Custom field {cf['name']!r} not found in entity context"
            assert cf["data_type"] in result, f"Custom field data_type {cf['data_type']!r} not found"
    else:
        assert "Available custom fields:" not in result, "Empty custom field list should not produce a section"


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    tags=st.lists(_entity_name_strategy, min_size=1, max_size=10),
)
@pytest.mark.asyncio
async def test_property_11_tags_section_contains_all_names(
    tags: list[str],
) -> None:
    """
    # Feature: paperless-live-integration, Property 11: Entity lists in prompt

    The "Available tags:" section shall contain every tag name from the list,
    joined by commas.

    **Validates: Requirements 12.1, 12.5**
    """
    paperless = _make_mock_paperless(tags, [], [], [])
    config = _make_config()
    analyzer = _make_analyzer(config, paperless=paperless)

    result = await analyzer._fetch_entity_context()

    # Extract the tags line
    for line in result.split("\n"):
        if line.startswith("Available tags:"):
            tag_section = line
            break
    else:
        pytest.fail("'Available tags:' line not found")

    for tag in tags:
        assert tag in tag_section, (
            f"Tag {tag!r} not found in tags section: {tag_section!r}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    correspondents=st.lists(_entity_name_strategy, min_size=1, max_size=10),
)
@pytest.mark.asyncio
async def test_property_11_correspondents_section_contains_all_names(
    correspondents: list[str],
) -> None:
    """
    # Feature: paperless-live-integration, Property 11: Entity lists in prompt

    The "Available correspondents:" section shall contain every correspondent name.

    **Validates: Requirements 12.2, 12.5**
    """
    paperless = _make_mock_paperless([], correspondents, [], [])
    config = _make_config()
    analyzer = _make_analyzer(config, paperless=paperless)

    result = await analyzer._fetch_entity_context()

    for line in result.split("\n"):
        if line.startswith("Available correspondents:"):
            corr_section = line
            break
    else:
        pytest.fail("'Available correspondents:' line not found")

    for corr in correspondents:
        assert corr in corr_section, (
            f"Correspondent {corr!r} not found in correspondents section: {corr_section!r}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    custom_field_defs=st.lists(_custom_field_def_strategy, min_size=1, max_size=8),
)
@pytest.mark.asyncio
async def test_property_11_custom_fields_section_contains_all_defs(
    custom_field_defs: list[dict[str, Any]],
) -> None:
    """
    # Feature: paperless-live-integration, Property 11: Entity lists in prompt

    The "Available custom fields:" section shall contain every custom field
    name and its data_type.

    **Validates: Requirements 12.4, 12.5**
    """
    paperless = _make_mock_paperless([], [], [], custom_field_defs)
    config = _make_config()
    analyzer = _make_analyzer(config, paperless=paperless)

    result = await analyzer._fetch_entity_context()

    for line in result.split("\n"):
        if line.startswith("Available custom fields:"):
            cf_section = line
            break
    else:
        pytest.fail("'Available custom fields:' line not found")

    for cf in custom_field_defs:
        expected_part = f"{cf['name']} ({cf['data_type']})"
        assert expected_part in cf_section, (
            f"Custom field {expected_part!r} not found in section: {cf_section!r}"
        )
