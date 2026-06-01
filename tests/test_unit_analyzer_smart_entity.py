"""Regression test: smart entity selection must await the (now async) store.count().

When count() became async (QDRANT_PLAN §5), the analyzer's smart-entity guard
`... and self._vector_store.count() > 0` compared a coroutine to an int, raising
TypeError on every analyze() with a vector store present. This guards that path.
"""

from __future__ import annotations

import hashlib

import pytest

from backend.analyzer import DocumentAnalyzer
from backend.models import PaperlessIQConfig
from backend.vector_store import QdrantVectorStore

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


class _MockProvider:
    async def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]

    async def health_check(self) -> bool:
        return True


class _FakePaperless:
    async def list_custom_field_definitions(self) -> list:
        return []

    async def list_entities_with_map(self, kind: str):
        if kind == "tags":
            return (["finance", "tax"], {1: "finance", 2: "tax"})
        return ([], {})


def _config() -> PaperlessIQConfig:
    return PaperlessIQConfig(
        llm_provider="ollama", llm_model="llama3",
        smart_entity_selection=True,
    )


@pytest.mark.asyncio
async def test_fetch_entity_context_awaits_store_count() -> None:
    store = QdrantVectorStore(_MockProvider(), url=":memory:", collection_name="analyzer_test")
    await store.upsert(1, "annual tax return income statement", {
        "title": "Tax 2024", "tags": ["finance", "tax"],
        "correspondent": "Tax Office", "document_type": "Statement",
    })
    assert await store.count() > 0

    analyzer = DocumentAnalyzer(
        provider=_MockProvider(),
        paperless_client=_FakePaperless(),
        config=_config(),
        provider_name="ollama",
        vector_store=store,
    )

    # With the bug, this raised TypeError ("'>' not supported between coroutine
    # and int") before reaching the try/except. It must now return cleanly.
    ctx, tags, corrs, dts = await analyzer._fetch_entity_context(
        "tax return income", {"content": "tax return income"}
    )
    assert isinstance(ctx, str)
    assert isinstance(tags, list)


@pytest.mark.asyncio
async def test_fetch_entity_context_empty_store_no_crash() -> None:
    store = QdrantVectorStore(_MockProvider(), url=":memory:", collection_name="analyzer_empty")
    analyzer = DocumentAnalyzer(
        provider=_MockProvider(),
        paperless_client=_FakePaperless(),
        config=_config(),
        provider_name="ollama",
        vector_store=store,
    )
    # Empty store: count() == 0 short-circuits the smart path, but the await
    # still executes — the buggy version raised here regardless of count.
    ctx, tags, corrs, dts = await analyzer._fetch_entity_context("anything", {})
    assert isinstance(tags, list)
