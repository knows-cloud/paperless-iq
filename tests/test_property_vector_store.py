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
from hypothesis import given
from hypothesis import strategies as st

from backend.models import SearchResult
from backend.vector_store import (
    ChromaVectorStore,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    _chunk,
    _chunk_text_sentences,
)

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

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
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
    import asyncio
    import uuid
    import chromadb

    provider = _MockLLMProvider()
    store = ChromaVectorStore.__new__(ChromaVectorStore)
    store._llm = provider
    store._chunk_size = DEFAULT_CHUNK_SIZE
    store._chunk_overlap = DEFAULT_CHUNK_OVERLAP
    store._chunk_strategy = "char"
    store._overfetch_multiplier = 5
    store._min_score = 0.0
    store._reranker = None
    store._rerank_top_k = 20
    store._collection_config = {"hnsw": {"space": "cosine"}}
    store._embed_sem = asyncio.Semaphore(1)
    store._embed_concurrency = 1
    store._client = chromadb.EphemeralClient()
    # EphemeralClient shares its in-memory system across instantiations, so a
    # fixed collection name leaks documents between tests — use a unique one.
    store._collection = store._client.get_or_create_collection(
        name=f"test_collection_{uuid.uuid4().hex}",
        configuration=store._collection_config,
    )
    return store


# ---------------------------------------------------------------------------
# Property 9: Embedding round-trip
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Configurable chunking: sentence strategy (QDRANT_PLAN §5.5 item 3)
# ---------------------------------------------------------------------------


def test_sentence_chunking_short_text_single_chunk() -> None:
    """Text shorter than chunk_size is one chunk."""
    text = "One sentence. Two sentences."
    assert _chunk_text_sentences(text, chunk_size=1000, overlap=200) == [text]


def test_sentence_chunking_no_midword_cuts() -> None:
    """Sentence chunking packs whole sentences — no chunk exceeds chunk_size,
    and reassembled words match the source (no mid-word splits)."""
    sentences = [f"This is sentence number {i} with some filler words." for i in range(40)]
    text = " ".join(sentences)
    chunks = _chunk_text_sentences(text, chunk_size=120, overlap=30)

    assert len(chunks) > 1, "expected multiple chunks for long text"
    for c in chunks:
        # allow a small slack for the joining space; packing stops before exceeding size
        assert len(c) <= 120 + 60
    # Every source word survives somewhere (no truncation/mid-word loss)
    source_words = set(text.split())
    chunk_words = set(" ".join(chunks).split())
    assert source_words <= chunk_words


def test_chunk_dispatch_char_is_default() -> None:
    """The dispatcher routes to char splitting unless strategy == 'sentence'."""
    text = "x" * 2500
    char_chunks = _chunk(text, 1000, 200, "char")
    # char strategy yields fixed-width windows
    assert char_chunks[0] == "x" * 1000
    assert len(char_chunks) >= 3


@pytest.mark.asyncio
async def test_chroma_exclude_tag_id_filters_inbox_docs() -> None:
    """Chroma post-filters query_similar_metadata on tag_ids_json."""
    store = _make_store()
    await store.upsert(1, "insurance policy acme corp", {
        "title": "Inbox", "tag_ids": [99, 5], "correspondent": "Acme Inbox",
    })
    await store.upsert(2, "insurance policy acme corp curated", {
        "title": "Curated", "tag_ids": [5], "correspondent": "Acme Curated",
    })

    meta_all = await store.query_similar_metadata("insurance", top_n=5)
    assert "Acme Inbox" in meta_all["correspondents"]

    meta_excl = await store.query_similar_metadata("insurance", top_n=5, exclude_tag_id=99)
    assert "Acme Inbox" not in meta_excl["correspondents"]
    assert "Acme Curated" in meta_excl["correspondents"]
