"""Tests for backend-agnostic embedding migration (QDRANT_PLAN §8)."""

from __future__ import annotations

import hashlib

import chromadb
import pytest

from backend.memory_store import ChromaMemoryStore, QdrantMemoryStore
from backend.vector_migrate import migrate_embeddings, migrate_memories
from backend.vector_store import (
    ChromaVectorStore,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    QdrantVectorStore,
)

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


class _MockLLMProvider:
    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]

    async def health_check(self) -> bool:
        return True


def _chroma_store(collection: str = "migrate_src") -> ChromaVectorStore:
    store = ChromaVectorStore.__new__(ChromaVectorStore)
    store._llm = _MockLLMProvider()
    store._chunk_size = DEFAULT_CHUNK_SIZE
    store._chunk_overlap = DEFAULT_CHUNK_OVERLAP
    store._chunk_strategy = "char"
    store._overfetch_multiplier = 5
    store._min_score = 0.0
    store._reranker = None
    store._rerank_top_k = 20
    store._collection_config = {"hnsw": {"space": "cosine"}}
    import asyncio
    store._embed_sem = asyncio.Semaphore(1)
    store._embed_concurrency = 1
    # Fresh client per store so collections don't leak across tests.
    store._client = chromadb.EphemeralClient()
    store._collection = store._client.get_or_create_collection(
        name=collection, configuration=store._collection_config,
    )
    return store


def _qdrant_store(collection="migrate_dst") -> QdrantVectorStore:
    return QdrantVectorStore(_MockLLMProvider(), url=":memory:", collection_name=collection)


# ---------------------------------------------------------------------------
# Document migration: Chroma -> Qdrant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_chroma_to_qdrant_preserves_vectors() -> None:
    src = _chroma_store(collection="src_main")
    await src.upsert(1, "tax document about income", {"title": "Tax", "tags": ["finance"]})
    await src.upsert(2, "vacation photos description", {"title": "Trip"})
    src_n = await src.count()
    assert src_n > 0

    dst = _qdrant_store()
    result = await migrate_embeddings(src, dst)

    assert result.needs_reindex is False
    assert result.migrated == src_n
    assert await dst.count() == src_n

    # Migrated (not re-embedded): an exact source vector still scores ~1.0,
    # and metadata survived the copy.
    results = await dst.query("tax document about income", top_n=5)
    assert any(r.document_id == 1 for r in results)
    meta = await dst.query_similar_metadata("tax", top_n=5)
    assert "finance" in meta["tags"]


@pytest.mark.asyncio
async def test_migrate_empty_source_is_noop_success() -> None:
    src = _chroma_store(collection="src_empty")
    dst = _qdrant_store(collection="empty_dst")
    result = await migrate_embeddings(src, dst)
    assert result.migrated == 0
    assert result.needs_reindex is False


@pytest.mark.asyncio
async def test_migrate_skips_when_destination_populated() -> None:
    src = _chroma_store(collection="src_pop")
    await src.upsert(1, "source content", {"title": "S"})
    dst = _qdrant_store(collection="populated_dst")
    await dst.upsert(99, "existing destination content", {"title": "D"})

    result = await migrate_embeddings(src, dst)
    assert result.migrated == 0
    assert result.needs_reindex is False
    assert "already populated" in result.reason


@pytest.mark.asyncio
async def test_migrate_unsupported_backend_needs_reindex() -> None:
    class _NoDump:
        async def count(self):
            return 5

    result = await migrate_embeddings(_NoDump(), _qdrant_store(collection="x"))
    assert result.needs_reindex is True


# ---------------------------------------------------------------------------
# Memory migration
# ---------------------------------------------------------------------------


def _chroma_memory() -> ChromaMemoryStore:
    store = ChromaMemoryStore.__new__(ChromaMemoryStore)
    store._llm = _MockLLMProvider()
    store._chroma = chromadb.EphemeralClient()
    store._col = store._chroma.get_or_create_collection(
        name="mem_src", configuration={"hnsw": {"space": "cosine"}},
    )
    return store


@pytest.mark.asyncio
async def test_migrate_memories_chroma_to_qdrant() -> None:
    src = _chroma_memory()
    await src.upsert("m1", "the user prefers brief answers")
    await src.upsert("m2", "the user works in finance")

    dst = QdrantMemoryStore(_MockLLMProvider(), url=":memory:", collection_name="mem_dst")
    result = await migrate_memories(src, dst)
    assert result.migrated == 2

    pairs = await dst.query("the user prefers brief answers", top_n=3)
    assert pairs[0][0] == "m1"
    assert pairs[0][1] == pytest.approx(1.0)
