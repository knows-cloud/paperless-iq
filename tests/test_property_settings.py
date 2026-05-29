"""Property-based tests for settings and authentication.

# Feature: paperless-iq, Property 13: Settings validation rejects invalid values
# Feature: paperless-iq, Property 14: Authentication enforcement

Validates: Requirements 5.3, 5.4
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.settings_service import SettingsService

# ---------------------------------------------------------------------------
# Strategies for invalid settings
# ---------------------------------------------------------------------------

_invalid_settings = st.one_of(
    # Retention days below minimum (30)
    st.fixed_dictionaries({"audit_retention_days": st.integers(max_value=29)}),
    # Unknown provider
    st.fixed_dictionaries({"llm_provider": st.just("unknown_provider")}),
    # Invalid analysis mode
    st.fixed_dictionaries({"default_analysis_mode": st.just("invalid_mode")}),
    # Invalid vector store backend
    st.fixed_dictionaries({"vector_store_backend": st.just("nonexistent")}),
    # Negative poll interval
    st.fixed_dictionaries({"poll_interval_seconds": st.just(-1)}),
    # Negative batch size
    st.fixed_dictionaries({"batch_size": st.just(-5)}),
)


# ---------------------------------------------------------------------------
# Property 13: Settings validation rejects invalid values
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(invalid_values=_invalid_settings)
def test_property_13_settings_validation_rejects_invalid(
    invalid_values: dict[str, Any],
) -> None:
    """
    # Feature: paperless-iq, Property 13: Settings validation rejects invalid values

    Invalid setting values must be rejected with a descriptive error message
    and must not be persisted.

    Validates: Requirements 5.3
    """
    svc = SettingsService()
    original = svc.get_masked()

    with pytest.raises(ValueError, match="Invalid settings"):
        svc.update(invalid_values)

    # Config must be unchanged after failed validation
    after = svc.get_masked()
    assert after == original, "Config was modified despite validation failure"


# ---------------------------------------------------------------------------
# Property 14: Authentication enforcement
# ---------------------------------------------------------------------------

# Protected endpoints to test (method, path)
_PROTECTED_ENDPOINTS = [
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/queue"),
    ("GET", "/api/audit"),
    ("GET", "/api/search?q=test"),
    ("GET", "/api/documents"),
    ("GET", "/api/config/export"),
    ("POST", "/api/config/import"),
    ("POST", "/api/analyze"),
]


@pytest_asyncio.fixture
async def unauth_client():
    """Async HTTP test client WITHOUT any auth headers."""
    import os
    # Set PAPERLESS_URL so auth is enforced (auth.py checks this, not SECRET_KEY)
    os.environ["PAPERLESS_URL"] = "http://paperless.test"
    os.environ["SECRET_KEY"] = "test-secret-key-for-auth"

    # Re-import to pick up the env var
    import importlib
    import backend.auth
    importlib.reload(backend.auth)

    from backend.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    # Clean up
    os.environ.pop("PAPERLESS_URL", None)
    os.environ.pop("SECRET_KEY", None)
    importlib.reload(backend.auth)


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(
    endpoint_idx=st.integers(min_value=0, max_value=len(_PROTECTED_ENDPOINTS) - 1),
)
@pytest.mark.asyncio
async def test_property_14_authentication_enforcement(
    unauth_client: AsyncClient,
    endpoint_idx: int,
) -> None:
    """
    # Feature: paperless-iq, Property 14: Authentication enforcement

    Unauthenticated requests to protected endpoints must receive HTTP 401 or 403.

    Validates: Requirements 5.4
    """
    method, path = _PROTECTED_ENDPOINTS[endpoint_idx]

    if method == "GET":
        resp = await unauth_client.get(path)
    elif method == "PUT":
        resp = await unauth_client.put(path, json={})
    elif method == "POST":
        resp = await unauth_client.post(path, json={})
    else:
        pytest.fail(f"Unknown method: {method}")

    assert resp.status_code in (401, 403), (
        f"{method} {path} returned {resp.status_code}, expected 401 or 403"
    )

    # Must not expose protected data
    body = resp.json()
    assert "items" not in body or body.get("items") == [], (
        f"{method} {path} exposed protected data without auth"
    )


# ---------------------------------------------------------------------------
# Strategies for settings round-trip dicts
# ---------------------------------------------------------------------------

# Field names: core fields or custom field keys like "cf:1", "cf:42"
_field_name_strategy = st.one_of(
    st.sampled_from(["title", "tags", "correspondent", "document_type", "storage_path"]),
    st.integers(min_value=1, max_value=9999).map(lambda i: f"cf:{i}"),
)

_field_descriptions_strategy = st.dictionaries(
    keys=_field_name_strategy,
    values=st.text(min_size=1, max_size=200),
    min_size=0,
    max_size=10,
)

_per_field_prompt_templates_strategy = st.dictionaries(
    keys=st.sampled_from(["title", "tags", "correspondent", "document_type", "storage_path"]),
    values=st.text(min_size=1, max_size=200),
    min_size=0,
    max_size=5,
)

_per_doctype_prompt_templates_strategy = st.dictionaries(
    keys=st.integers(min_value=1, max_value=9999),
    values=st.text(min_size=1, max_size=200),
    min_size=0,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Property 3: Settings round-trip
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    field_descriptions=_field_descriptions_strategy,
    per_field_prompts=_per_field_prompt_templates_strategy,
    per_doctype_prompts=_per_doctype_prompt_templates_strategy,
)
def test_property_3_settings_round_trip(
    field_descriptions: dict[str, str],
    per_field_prompts: dict[str, str],
    per_doctype_prompts: dict[int, str],
) -> None:
    """
    # Feature: paperless-live-integration, Property 3: Settings round-trip

    For any valid partial settings update containing field_descriptions,
    per_field_prompt_templates, or per_doctype_prompt_templates, calling
    SettingsService.update() with those values and then reading back via
    SettingsService.config shall return a config whose corresponding fields
    match the values that were set.

    **Validates: Requirements 5.3, 5.4, 17.4, 17.5**
    """
    svc = SettingsService()

    # Update field_descriptions
    svc.update({"field_descriptions": field_descriptions})
    assert svc.config.field_descriptions == field_descriptions, (
        f"field_descriptions mismatch: expected {field_descriptions}, "
        f"got {svc.config.field_descriptions}"
    )

    # Update per_field_prompt_templates
    svc.update({"per_field_prompt_templates": per_field_prompts})
    assert svc.config.per_field_prompt_templates == per_field_prompts, (
        f"per_field_prompt_templates mismatch: expected {per_field_prompts}, "
        f"got {svc.config.per_field_prompt_templates}"
    )

    # Update per_doctype_prompt_templates
    svc.update({"per_doctype_prompt_templates": per_doctype_prompts})
    assert svc.config.per_doctype_prompt_templates == per_doctype_prompts, (
        f"per_doctype_prompt_templates mismatch: expected {per_doctype_prompts}, "
        f"got {svc.config.per_doctype_prompt_templates}"
    )

    # Verify all three fields are still correct after sequential updates
    assert svc.config.field_descriptions == field_descriptions
    assert svc.config.per_field_prompt_templates == per_field_prompts
    assert svc.config.per_doctype_prompt_templates == per_doctype_prompts


# ---------------------------------------------------------------------------
# Cross-field validation: HNSW search_ef must cover overfetched candidates
# (QDRANT_PLAN §3.4)
# ---------------------------------------------------------------------------


def test_search_ef_rejected_below_needed_local() -> None:
    """Local (Chroma) backend: chroma_hnsw_search_ef < count×overfetch is rejected."""
    svc = SettingsService()
    # defaults: similar_docs_count=10, overfetch=5 → needed=50
    with pytest.raises(ValueError, match="must be ≥ similar_docs_count"):
        svc.update({"chroma_hnsw_search_ef": 49})
    # unchanged after failure
    assert svc.config.chroma_hnsw_search_ef == 100


def test_search_ef_accepted_at_boundary_local() -> None:
    """Boundary (ef == needed) is accepted."""
    svc = SettingsService()
    svc.update({"chroma_hnsw_search_ef": 50})  # == 10×5
    assert svc.config.chroma_hnsw_search_ef == 50


def test_search_ef_validates_active_backend_qdrant() -> None:
    """Qdrant backend enforces qdrant_hnsw_ef, not the Chroma field."""
    svc = SettingsService()
    with pytest.raises(ValueError, match="qdrant_hnsw_ef"):
        svc.update({"vector_store_backend": "qdrant", "qdrant_hnsw_ef": 10})
    # boundary accepted
    svc.update({"vector_store_backend": "qdrant", "qdrant_hnsw_ef": 50})
    assert svc.config.qdrant_hnsw_ef == 50


def test_search_ef_skipped_for_bedrock_kb() -> None:
    """bedrock_kb manages its own retrieval — ef check does not apply."""
    svc = SettingsService()
    # low chroma ef is irrelevant once backend is bedrock_kb
    svc.update({"vector_store_backend": "bedrock_kb", "chroma_hnsw_search_ef": 1})
    assert svc.config.vector_store_backend == "bedrock_kb"
