"""Hybrid (dense + sparse RRF) search tests for QdrantVectorStore.

The sparse encoder (fastembed) is an optional production dependency. Tests
inject a deterministic fake encoder so the hybrid logic — named vectors, RRF
fusion, scoring, filtering, and migration — is covered without fastembed.
"""

from __future__ import annotations

import hashlib
from collections import Counter

import pytest

from backend.models import SearchResult
from backend.vector_migrate import migrate_embeddings
from backend.vector_store import QdrantVectorStore

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


class _MockLLMProvider:
    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]

    async def health_check(self) -> bool:
        return True


class _FakeSparseEmbedding:
    def __init__(self, indices, values):
        self.indices = indices
        self.values = values


class _FakeSparseEncoder:
    """Deterministic bag-of-words sparse encoder (term -> stable index)."""

    @staticmethod
    def _index(term: str) -> int:
        return int(hashlib.md5(term.encode()).hexdigest()[:8], 16)

    def embed(self, texts):
        for t in texts:
            counts = Counter(w.lower() for w in t.split() if w.strip())
            indices = [self._index(w) for w in counts]
            values = [float(c) for c in counts.values()]
            yield _FakeSparseEmbedding(indices, values)


def _hybrid_store(collection: str) -> QdrantVectorStore:
    store = QdrantVectorStore(
        _MockLLMProvider(), url=":memory:", collection_name=collection, hybrid_search=True,
    )
    store._sparse_encoder = _FakeSparseEncoder()  # avoid the lazy fastembed load
    return store


@pytest.mark.asyncio
async def test_hybrid_upsert_and_query() -> None:
    store = _hybrid_store("hybrid_q")
    await store.upsert(1, "annual tax return income statement", {"title": "Tax"})
    await store.upsert(2, "vacation beach holiday photos", {"title": "Trip"})

    results = await store.query("tax return income", top_n=5)
    assert results, "hybrid query returned nothing"
    assert all(isinstance(r, SearchResult) for r in results)
    assert all(0.0 <= r.score <= 1.0 for r in results)
    assert results[0].document_id == 1  # keyword + dense both favour the tax doc


@pytest.mark.asyncio
async def test_hybrid_query_chunks() -> None:
    store = _hybrid_store("hybrid_qc")
    await store.upsert(3, "loan agreement mortgage terms", {"title": "Loan"})
    chunks = await store.query_chunks("mortgage loan", top_n_chunks=5)
    assert chunks
    assert all(0.0 <= c["score"] <= 1.0 for c in chunks)


@pytest.mark.asyncio
async def test_hybrid_exclude_tag_id() -> None:
    store = _hybrid_store("hybrid_excl")
    await store.upsert(1, "insurance policy acme", {
        "title": "Inbox", "tag_ids": [99], "correspondent": "Acme Inbox"})
    await store.upsert(2, "insurance policy acme curated", {
        "title": "Curated", "tag_ids": [5], "correspondent": "Acme Curated"})

    meta = await store.query_similar_metadata("insurance", top_n=5, exclude_tag_id=99)
    assert "Acme Inbox" not in meta["correspondents"]
    assert "Acme Curated" in meta["correspondents"]


@pytest.mark.asyncio
async def test_hybrid_upsert_replaces_document() -> None:
    store = _hybrid_store("hybrid_replace")
    await store.upsert(1, "first version cats", {"title": "v1"})
    n1 = await store.count()
    await store.upsert(1, "second version cats", {"title": "v2"})
    assert await store.count() == n1  # no duplicate points


@pytest.mark.asyncio
async def test_migration_into_hybrid_reencodes_sparse() -> None:
    """A dense-only source migrates into a hybrid store; sparse is rebuilt from
    the passages so hybrid query still works."""
    src = QdrantVectorStore(_MockLLMProvider(), url=":memory:", collection_name="dense_src")
    await src.upsert(1, "tax document about income", {"title": "Tax"})
    await src.upsert(2, "holiday beach trip", {"title": "Trip"})

    dst = _hybrid_store("hybrid_dst")
    result = await migrate_embeddings(src, dst)
    assert result.needs_reindex is False
    assert result.migrated == await dst.count()

    results = await dst.query("tax income", top_n=5)
    assert any(r.document_id == 1 for r in results)
