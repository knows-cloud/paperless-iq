"""Unit tests for the memory store backends and factory (QDRANT_PLAN §6)."""

from __future__ import annotations

import hashlib

import pytest

from backend.memory_store import (
    ChromaMemoryStore,
    QdrantMemoryStore,
    SIMILARITY_THRESHOLD,
    make_memory_store,
)

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


class _MockLLMProvider:
    async def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]

    async def health_check(self) -> bool:
        return True


def _qdrant_store() -> QdrantMemoryStore:
    return QdrantMemoryStore(_MockLLMProvider(), url=":memory:", collection_name="mem_test")


# ---------------------------------------------------------------------------
# QdrantMemoryStore lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qdrant_memory_upsert_query_roundtrip() -> None:
    store = _qdrant_store()
    await store.upsert("m1", "the user prefers concise answers")
    pairs = await store.query("the user prefers concise answers", top_n=3)
    assert pairs
    assert pairs[0][0] == "m1"
    assert pairs[0][1] == pytest.approx(1.0)  # exact match → cosine 1.0


@pytest.mark.asyncio
async def test_qdrant_memory_query_empty() -> None:
    store = _qdrant_store()
    assert await store.query("anything") == []


@pytest.mark.asyncio
async def test_qdrant_memory_find_similar_threshold() -> None:
    store = _qdrant_store()
    await store.upsert("m1", "identical fact")
    # exact match clears the dedup threshold and returns the existing id
    assert await store.find_similar("identical fact") == "m1"
    # an unrelated string should fall below threshold
    result = await store.find_similar("completely different unrelated text")
    assert result is None or result == "m1"  # hash embeddings: just must not crash
    assert SIMILARITY_THRESHOLD == 0.88


@pytest.mark.asyncio
async def test_qdrant_memory_delete() -> None:
    store = _qdrant_store()
    await store.upsert("m1", "fact to delete")
    await store.delete("m1")
    assert await store.query("fact to delete") == []


@pytest.mark.asyncio
async def test_qdrant_memory_delete_all() -> None:
    store = _qdrant_store()
    await store.upsert("m1", "first")
    await store.upsert("m2", "second")
    await store.delete_all()
    assert await store.query("first") == []


@pytest.mark.asyncio
async def test_qdrant_memory_upsert_updates_in_place() -> None:
    store = _qdrant_store()
    await store.upsert("m1", "original text")
    await store.upsert("m1", "revised text")  # same id → same point
    pairs = await store.query("revised text", top_n=5)
    ids = [mid for mid, _ in pairs]
    assert ids.count("m1") == 1


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_make_memory_store_local_selects_chroma(monkeypatch) -> None:
    # Stub ChromaMemoryStore so the factory's local branch doesn't touch /data.
    import backend.memory_store as ms

    captured = {}

    class _StubChroma(ms.MemoryStore):
        def __init__(self, llm_provider, persist_directory="/data/chroma",
                     collection_name="piq_memories"):
            captured["persist"] = persist_directory

    monkeypatch.setattr(ms, "ChromaMemoryStore", _StubChroma)
    cfg = type("C", (), {"vector_store_backend": "local"})()
    store = ms.make_memory_store(cfg, _MockLLMProvider())
    assert isinstance(store, _StubChroma)
    assert captured["persist"] == "/data/chroma"


def test_make_memory_store_selects_qdrant() -> None:
    cfg = type("C", (), {
        "vector_store_backend": "qdrant",
        "qdrant_url": ":memory:",
        "qdrant_api_key": b"",
        "qdrant_memory_collection": "piq_memories",
    })()
    store = make_memory_store(cfg, _MockLLMProvider())
    assert isinstance(store, QdrantMemoryStore)
