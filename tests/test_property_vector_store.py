"""Property-based tests for the vector store.

# Feature: paperless-iq, Property 9: Embedding round-trip
# Feature: paperless-iq, Property 10: Search result count bound
# Feature: paperless-iq, Property 11: Search result structure
# Feature: paperless-iq, Property 12: Vector store backend re-index completeness

Validates: Requirements 4.1, 4.3, 4.4, 4.5, 4.8
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.models import SearchResult
from backend.vector_store import ChromaVectorStore

# ---------------------------------------------------------------------------
# Deterministic mock LLM provider
# ---------------------------------------------------------------------------


class _MockLLMProvider:
    """Deterministic embedding provider for testing.

    Produces a fixed-length embedding derived from a hash of the input text,
    so identical texts always produce identical embeddings and different texts
    produce different (but deterministic) embeddings.
    """

    async def complete(self, prompt: str, max_tokens: int) -> str:
        return "{}"

    async def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        # 64-dimensional embedding from hash bytes
        return [b / 255.0 for b in h[:32]] + [b / 255.0 for b in h[:32]]

    async def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_doc_id_strategy = st.integers(min_value=1, max_value=100_000)

_doc_text = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
    min_size=10,
    max_size=200,
)


# ---------------------------------------------------------------------------
# Helper: create a fresh ChromaVectorStore with ephemeral storage
# ---------------------------------------------------------------------------

def _make_store() -> ChromaVectorStore:
    """Create a ChromaVectorStore backed by an ephemeral (in-memory) client."""
    import chromadb

    provider = _MockLLMProvider()
    store = ChromaVectorStore.__new__(ChromaVectorStore)
    store._llm = provider
    store._client = chromadb.EphemeralClient()
    store._collection = store._client.get_or_create_collection(
        name="test",
        metadata={"hnsw:space": "cosine"},
    )
    return store


# ---------------------------------------------------------------------------
# Property 9: Embedding round-trip
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    doc_id=_doc_id_strategy,
    text=_doc_text,
)
@pytest.mark.asyncio
async def test_property_9_embedding_round_trip(
    doc_id: int,
    text: str,
) -> None:
    """
    # Feature: paperless-iq, Property 9: Embedding round-trip

    An indexed document must appear in query results. After deletion,
    it must be absent.

    Validates: Requirements 4.1, 4.3
    """
    store = _make_store()
    # Upsert
    await store.upsert(doc_id, text, {"title": f"Doc {doc_id}"})

    # Query with the same text — should find the document
    results = await store.query(text, top_n=5)
    found_ids = {r.document_id for r in results}
    assert doc_id in found_ids, (
        f"Document {doc_id} not found in query results after upsert"
    )

    # Delete
    await store.delete(doc_id)

    # Query again — should NOT find the document
    results_after = await store.query(text, top_n=5)
    found_ids_after = {r.document_id for r in results_after}
    assert doc_id not in found_ids_after, (
        f"Document {doc_id} still found in query results after deletion"
    )


# ---------------------------------------------------------------------------
# Property 10: Search result count bound
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    num_docs=st.integers(min_value=1, max_value=15),
    top_n=st.integers(min_value=1, max_value=20),
)
@pytest.mark.asyncio
async def test_property_10_search_result_count_bound(
    num_docs: int,
    top_n: int,
) -> None:
    """
    # Feature: paperless-iq, Property 10: Search result count bound

    For any query with parameter top-N, the number of results must be at most N.

    Validates: Requirements 4.4
    """
    store = _make_store()
    # Insert num_docs documents with distinct text
    for i in range(1, num_docs + 1):
        await store.upsert(i, f"Document number {i} with unique content xyz{i}", {"title": f"Doc {i}"})

    results = await store.query("Document content", top_n=top_n)
    assert len(results) <= top_n, (
        f"Got {len(results)} results but top_n={top_n}"
    )


# ---------------------------------------------------------------------------
# Property 11: Search result structure
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    doc_id=_doc_id_strategy,
    text=_doc_text,
)
@pytest.mark.asyncio
async def test_property_11_search_result_structure(
    doc_id: int,
    text: str,
) -> None:
    """
    # Feature: paperless-iq, Property 11: Search result structure

    Each search result must have a non-empty verbatim passage and a valid
    deeplink URL.

    Validates: Requirements 4.5
    """
    store = _make_store()
    await store.upsert(doc_id, text, {"title": f"Doc {doc_id}"})
    results = await store.query(text, top_n=5)

    for r in results:
        assert isinstance(r, SearchResult)
        assert r.passage, "Passage must be non-empty"
        assert r.deeplink_url, "Deeplink URL must be non-empty"
        assert "/documents/" in r.deeplink_url, (
            f"Deeplink URL must contain /documents/: {r.deeplink_url}"
        )
        assert r.document_id > 0


# ---------------------------------------------------------------------------
# Property 12: Vector store backend re-index completeness
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    doc_ids=st.lists(
        st.integers(min_value=1, max_value=10_000),
        min_size=1,
        max_size=10,
        unique=True,
    ),
)
@pytest.mark.asyncio
async def test_property_12_reindex_completeness(
    doc_ids: list[int],
) -> None:
    """
    # Feature: paperless-iq, Property 12: Vector store backend re-index completeness

    After re-indexing all documents into a new backend, every previously
    indexed document must be queryable.

    Validates: Requirements 4.8
    """
    store = _make_store()
    # Index documents in the "old" store
    documents = []
    for doc_id in doc_ids:
        text = f"Unique document content for id {doc_id} reindex test"
        await store.upsert(doc_id, text, {"title": f"Doc {doc_id}"})
        documents.append({"doc_id": doc_id, "text": text, "metadata": {"title": f"Doc {doc_id}"}})

    # Simulate backend switch by re-indexing into the same store
    # (clears and re-inserts all documents)
    await store.reindex_all(documents)

    # Every document must be queryable from the "new" backend
    for doc in documents:
        results = await store.query(doc["text"], top_n=len(doc_ids))
        found_ids = {r.document_id for r in results}
        assert doc["doc_id"] in found_ids, (
            f"Document {doc['doc_id']} not queryable after re-index"
        )
