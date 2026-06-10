# Feature: paperless-live-integration, Property 1: Search parameter forwarding
# Feature: paperless-live-integration, Property 5: Pagination fields in search response
# Feature: paperless-live-integration, Property 6: Proxy entities have required fields
# Feature: paperless-live-integration, Property 7: Proxy pagination completeness
"""Property-based tests for search proxy and pagination endpoints.

**Validates: Requirements 1.4, 1.5, 3.3, 7.1, 7.2, 7.3, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5**
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from hypothesis import given
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _paperless_json(
    results: list[dict[str, Any]],
    count: int | None = None,
    next_url: str | None = None,
) -> dict[str, Any]:
    """Build a Paperless NGX-style paginated JSON body."""
    return {
        "count": count if count is not None else len(results),
        "next": next_url,
        "previous": None,
        "results": results,
    }


def _doc_result(doc_id: int) -> dict[str, Any]:
    """Build a minimal Paperless NGX document result."""
    return {
        "id": doc_id,
        "title": f"Doc {doc_id}",
        "correspondent": 1,
        "document_type": 2,
        "tags": [1, 2],
        "created": "2024-01-01T00:00:00Z",
        "added": "2024-01-01T00:00:00Z",
    }


def _mock_httpx_client(get_handler):
    """Create a mock httpx.AsyncClient that delegates .get() to get_handler.

    Returns a class that can be used as a drop-in replacement for
    httpx.AsyncClient as an async context manager.
    """

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def get(self, url, **kwargs):
            return await get_handler(url, **kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return _FakeClient


_auth_patcher = None


def _setup_env():
    """Set env vars for Paperless proxy tests and bypass auth enforcement.

    PAPERLESS_URL being set triggers the auth middleware. Patch
    backend.main.require_auth to a no-op so proxy tests don't need real tokens.
    """
    global _auth_patcher
    os.environ["PAPERLESS_URL"] = "http://paperless.test"
    os.environ["PAPERLESS_TOKEN"] = "test-token"
    os.environ.pop("SECRET_KEY", None)

    from unittest.mock import patch, AsyncMock

    _auth_patcher = patch("backend.main.require_auth", new=AsyncMock(return_value=None))
    _auth_patcher.start()


def _cleanup_env():
    """Remove env vars and restore auth after tests."""
    global _auth_patcher
    os.environ.pop("PAPERLESS_URL", None)
    os.environ.pop("PAPERLESS_TOKEN", None)
    if _auth_patcher is not None:
        _auth_patcher.stop()
        _auth_patcher = None


# Strategies
_optional_text = st.one_of(
    st.none(),
    st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(whitelist_categories=("L", "N")),
    ),
)
_optional_pos_int = st.one_of(st.none(), st.integers(min_value=1, max_value=9999))


# ---------------------------------------------------------------------------
# Property 1: Search parameter forwarding
# ---------------------------------------------------------------------------


@given(
    query=_optional_text,
    tag_id=_optional_pos_int,
    correspondent_id=_optional_pos_int,
    document_type_id=_optional_pos_int,
    page=st.integers(min_value=1, max_value=100),
    page_size=st.integers(min_value=1, max_value=100),
)
@pytest.mark.asyncio
async def test_search_parameter_forwarding(
    query: str | None,
    tag_id: int | None,
    correspondent_id: int | None,
    document_type_id: int | None,
    page: int,
    page_size: int,
) -> None:
    """Property 1: All non-null search params are forwarded to Paperless NGX.

    For any combination of search parameters, the outgoing httpx request to
    Paperless NGX shall include every non-null parameter as the corresponding
    query parameter.

    **Validates: Requirements 1.4, 1.5, 3.3, 7.1, 7.2, 7.3**
    """
    captured_params: dict[str, Any] = {}

    async def handle_get(url: str, **kwargs: Any) -> httpx.Response:
        captured_params.update(kwargs.get("params", {}))
        body = _paperless_json([_doc_result(1)])
        return httpx.Response(status_code=200, json=body)

    _setup_env()
    try:
        from backend.main import app

        fake_client_cls = _mock_httpx_client(handle_get)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("httpx.AsyncClient", fake_client_cls):
                params: dict[str, Any] = {"page": page, "page_size": page_size}
                if query is not None:
                    params["query"] = query
                if tag_id is not None:
                    params["tag_ids"] = tag_id
                if correspondent_id is not None:
                    params["correspondent_ids"] = correspondent_id
                if document_type_id is not None:
                    params["document_type_ids"] = document_type_id

                resp = await client.get("/api/documents", params=params)
    finally:
        _cleanup_env()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    # Verify page/page_size always forwarded
    assert str(captured_params.get("page")) == str(page)
    assert str(captured_params.get("page_size")) == str(page_size)

    # Verify optional params forwarded when provided
    if query is not None:
        assert captured_params.get("query") == query
    if tag_id is not None:
        assert str(captured_params.get("tags__id__in")) == str(tag_id)
    if correspondent_id is not None:
        assert str(captured_params.get("correspondent__id__in")) == str(correspondent_id)
    if document_type_id is not None:
        assert str(captured_params.get("document_type__id__in")) == str(document_type_id)


# ---------------------------------------------------------------------------
# Property 5: Pagination fields in search response
# ---------------------------------------------------------------------------


@given(
    num_results=st.integers(min_value=0, max_value=20),
    total_count=st.integers(min_value=0, max_value=1000),
    page=st.integers(min_value=1, max_value=50),
    page_size=st.integers(min_value=1, max_value=100),
)
@pytest.mark.asyncio
async def test_pagination_fields_in_search_response(
    num_results: int,
    total_count: int,
    page: int,
    page_size: int,
) -> None:
    """Property 5: Response always contains items (list), total (>=0), page (>0), page_size (>0).

    For any successful response from /api/documents, the returned JSON shall
    contain exactly the keys items, total, page, and page_size with correct types.

    **Validates: Requirements 7.5**
    """
    results = [_doc_result(i + 1) for i in range(num_results)]

    async def handle_get(url: str, **kwargs: Any) -> httpx.Response:
        body = _paperless_json(results, count=total_count)
        return httpx.Response(status_code=200, json=body)

    _setup_env()
    try:
        from backend.main import app

        fake_client_cls = _mock_httpx_client(handle_get)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("httpx.AsyncClient", fake_client_cls):
                resp = await client.get(
                    "/api/documents", params={"page": page, "page_size": page_size}
                )
    finally:
        _cleanup_env()

    assert resp.status_code == 200
    data = resp.json()

    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data

    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int) and data["total"] >= 0
    assert isinstance(data["page"], int) and data["page"] >= 1
    assert isinstance(data["page_size"], int) and data["page_size"] >= 1

    assert len(data["items"]) == num_results


# ---------------------------------------------------------------------------
# Property 6: Proxy entities have required fields
# ---------------------------------------------------------------------------


@given(
    num_items=st.integers(min_value=1, max_value=15),
    entity_type=st.sampled_from(["tags", "correspondents", "document_types"]),
)
@pytest.mark.asyncio
async def test_proxy_entities_have_required_fields(
    num_items: int,
    entity_type: str,
) -> None:
    """Property 6: Proxy entity items always contain id (int) and name (str).

    For any entity type in {tags, correspondents, document_types} and any item
    returned by the proxy endpoint, the item shall contain id and name fields.

    **Validates: Requirements 8.1, 8.2, 8.3**
    """
    mock_results = [{"id": i + 1, "name": f"Entity {i + 1}"} for i in range(num_items)]

    async def handle_get(url: str, **kwargs: Any) -> httpx.Response:
        body = _paperless_json(mock_results)
        return httpx.Response(status_code=200, json=body)

    _setup_env()
    try:
        from backend.main import app

        fake_client_cls = _mock_httpx_client(handle_get)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("httpx.AsyncClient", fake_client_cls):
                resp = await client.get(f"/api/paperless/{entity_type}")
    finally:
        _cleanup_env()

    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) == num_items

    for item in items:
        assert "id" in item and isinstance(item["id"], int)
        assert "name" in item and isinstance(item["name"], str)


@given(
    num_items=st.integers(min_value=1, max_value=15),
    data_types=st.lists(
        st.sampled_from(["string", "integer", "boolean", "date", "float", "url", "monetary"]),
        min_size=1,
        max_size=15,
    ),
)
@pytest.mark.asyncio
async def test_proxy_custom_fields_have_required_fields(
    num_items: int,
    data_types: list[str],
) -> None:
    """Property 6 (custom_fields): Items contain id (int), name (str), and data_type (str).

    For custom_fields, each item shall additionally contain a data_type field.

    **Validates: Requirements 8.4**
    """
    actual_count = min(num_items, len(data_types))
    mock_results = [
        {"id": i + 1, "name": f"Field {i + 1}", "data_type": data_types[i]}
        for i in range(actual_count)
    ]

    async def handle_get(url: str, **kwargs: Any) -> httpx.Response:
        body = _paperless_json(mock_results)
        return httpx.Response(status_code=200, json=body)

    _setup_env()
    try:
        from backend.main import app

        fake_client_cls = _mock_httpx_client(handle_get)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("httpx.AsyncClient", fake_client_cls):
                resp = await client.get("/api/paperless/custom_fields")
    finally:
        _cleanup_env()

    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) == actual_count

    for item in items:
        assert "id" in item and isinstance(item["id"], int)
        assert "name" in item and isinstance(item["name"], str)
        assert "data_type" in item and isinstance(item["data_type"], str)


# ---------------------------------------------------------------------------
# Property 7: Proxy pagination completeness
# ---------------------------------------------------------------------------


@given(
    num_pages=st.integers(min_value=1, max_value=5),
    items_per_page=st.integers(min_value=1, max_value=10),
    entity_type=st.sampled_from(["tags", "correspondents", "document_types"]),
)
@pytest.mark.asyncio
async def test_proxy_pagination_completeness(
    num_pages: int,
    items_per_page: int,
    entity_type: str,
) -> None:
    """Property 7: Proxy follows all next links and returns all items.

    For any Paperless NGX entity list that spans multiple pages, the proxy
    endpoint shall follow all next links and return a result list whose length
    equals the total count.

    **Validates: Requirements 8.5**
    """
    total_items = num_pages * items_per_page
    base_url = f"http://paperless.test/api/{entity_type}/"

    # Build page lookup: map URL -> JSON body
    pages: dict[str, dict[str, Any]] = {}
    for page_num in range(1, num_pages + 1):
        start = (page_num - 1) * items_per_page
        results = [
            {"id": start + i + 1, "name": f"Item {start + i + 1}"}
            for i in range(items_per_page)
        ]
        next_url = (
            f"{base_url}?page={page_num + 1}&page_size=100"
            if page_num < num_pages
            else None
        )
        key = (
            f"{base_url}?page_size=100"
            if page_num == 1
            else f"{base_url}?page={page_num}&page_size=100"
        )
        pages[key] = _paperless_json(results, count=total_items, next_url=next_url)

    async def handle_get(url: str, **kwargs: Any) -> httpx.Response:
        for key, body in pages.items():
            if url == key:
                return httpx.Response(status_code=200, json=body)
        return httpx.Response(status_code=200, json=_paperless_json([]))

    _setup_env()
    try:
        from backend.main import app

        fake_client_cls = _mock_httpx_client(handle_get)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("httpx.AsyncClient", fake_client_cls):
                resp = await client.get(f"/api/paperless/{entity_type}")
    finally:
        _cleanup_env()

    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) == total_items, f"Expected {total_items} items, got {len(items)}"
