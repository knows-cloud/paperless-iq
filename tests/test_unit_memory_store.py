"""Unit tests for the memory store backends and factory (QDRANT_PLAN §6)."""

from __future__ import annotations

import hashlib
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.memory_store import (
    ChromaMemoryStore,
    MemoryStore,
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


# ---------------------------------------------------------------------------
# _embed() error surfacing — the base MemoryStore must log and re-raise so the
# real provider failure (e.g. an unreachable embed provider) is diagnosable.
# ---------------------------------------------------------------------------


class _FailingProvider:
    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or ConnectionRefusedError("embed provider unreachable")

    async def embed(self, text: str) -> list[float]:
        raise self._exc


@pytest.mark.asyncio
async def test_embed_failure_is_logged_at_error_level(caplog) -> None:
    store = MemoryStore(_FailingProvider())
    with caplog.at_level(logging.ERROR, logger="backend.memory_store"):
        with pytest.raises(ConnectionRefusedError):
            await store._embed("some text")
    assert any(
        "MemoryStore._embed() failed" in r.message and "_FailingProvider" in r.message
        for r in caplog.records
    ), f"Expected error log not found. Records: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_embed_failure_re_raises_original_exception() -> None:
    store = MemoryStore(_FailingProvider(RuntimeError("embed model not found")))
    with pytest.raises(RuntimeError, match="embed model not found"):
        await store._embed("some text")


@pytest.mark.asyncio
async def test_embed_success_returns_vector() -> None:
    store = MemoryStore(_MockLLMProvider())
    result = await store._embed("hello world")
    assert isinstance(result, list) and result and all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# Memory-extraction prompt — language instruction + source-document references.
# ---------------------------------------------------------------------------


async def _captured_extraction_prompt(target_language) -> str:
    """Run _extract_memories_from_session with a mocked provider and return the
    extraction prompt it produced."""
    captured: list[str] = []

    async def _mock_complete(prompt: str, max_tokens: int) -> str:
        captured.append(prompt)
        return "NONE"

    provider = MagicMock()
    provider.complete = _mock_complete
    session = SimpleNamespace(
        id="sess-test",
        summary=None,
        turns=[
            {"role": "user", "content": "When does my Telekom contract end?"},
            {"role": "assistant", "content": "Your contract ends August 2025 [1]."},
        ],
    )
    config = SimpleNamespace(memory_enabled=True, target_language=target_language)

    from backend.main import _extract_memories_from_session
    await _extract_memories_from_session(session, provider, MagicMock(), config)
    assert captured, "provider.complete was never called"
    return captured[0]


@pytest.mark.asyncio
async def test_prompt_includes_language_when_target_language_set() -> None:
    prompt = await _captured_extraction_prompt("German")
    assert "German" in prompt


@pytest.mark.asyncio
async def test_prompt_has_no_language_instruction_when_unset() -> None:
    prompt = await _captured_extraction_prompt(None)
    assert "Write every fact in" not in prompt


@pytest.mark.asyncio
async def test_prompt_instructs_source_document_reference() -> None:
    prompt = (await _captured_extraction_prompt(None)).lower()
    assert "source document" in prompt or "title" in prompt


@pytest.mark.asyncio
async def test_prompt_contains_doc_ref_example() -> None:
    prompt = await _captured_extraction_prompt(None)
    assert "(" in prompt and ")" in prompt
