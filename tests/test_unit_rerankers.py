"""Unit tests for the reranker layer (QDRANT_PLAN §5.5 item 4 / A.3)."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from backend.rerankers import LLMReranker, build_reranker


# ---------------------------------------------------------------------------
# Minimal deterministic provider
# ---------------------------------------------------------------------------


class _MockProvider:
    """LLMProvider stand-in: deterministic embeddings + scripted complete()."""

    def __init__(self, complete_response: str | None = None) -> None:
        self._complete_response = complete_response

    async def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]

    async def complete(self, prompt, max_tokens, output_schema=None, images=None) -> str:
        return self._complete_response or "{}"

    async def chat(self, messages, max_tokens, output_schema=None, images=None) -> str:
        return self._complete_response or "{}"

    async def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# build_reranker factory
# ---------------------------------------------------------------------------


def test_build_reranker_disabled_returns_none() -> None:
    cfg = type("C", (), {"rerank_enabled": False})()
    assert build_reranker(cfg, {}) is None


def test_build_reranker_llm_method() -> None:
    cfg = type("C", (), {
        "rerank_enabled": True, "rerank_method": "llm",
        "llm_provider": "ollama", "rerank_model": "x",
    })()
    r = build_reranker(cfg, {"ollama": _MockProvider()})
    assert isinstance(r, LLMReranker)


def test_build_reranker_llm_missing_provider_disables() -> None:
    cfg = type("C", (), {
        "rerank_enabled": True, "rerank_method": "llm",
        "llm_provider": "ollama", "rerank_model": "x",
    })()
    assert build_reranker(cfg, {}) is None  # provider not present → disabled


def test_build_reranker_api_requires_bedrock() -> None:
    cfg = type("C", (), {
        "rerank_enabled": True, "rerank_method": "api",
        "llm_provider": "ollama", "rerank_model": "x",
    })()
    assert build_reranker(cfg, {"ollama": _MockProvider()}) is None


# ---------------------------------------------------------------------------
# LLMReranker scoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_reranker_normalizes_to_unit_interval() -> None:
    provider = _MockProvider(json.dumps({"scores": [10, 5, 0]}))
    r = LLMReranker(provider)
    scores = await r.rerank("q", ["a", "b", "c"])
    assert scores == [1.0, 0.5, 0.0]


@pytest.mark.asyncio
async def test_llm_reranker_pads_length_mismatch() -> None:
    provider = _MockProvider(json.dumps({"scores": [10]}))  # too few
    r = LLMReranker(provider)
    scores = await r.rerank("q", ["a", "b", "c"])
    assert len(scores) == 3
    assert scores[0] == 1.0


@pytest.mark.asyncio
async def test_llm_reranker_failure_returns_neutral() -> None:
    provider = _MockProvider("not json")
    r = LLMReranker(provider)
    scores = await r.rerank("q", ["a", "b"])
    assert scores == [0.5, 0.5]  # preserves vector order


@pytest.mark.asyncio
async def test_reranker_empty_passages() -> None:
    r = LLMReranker(_MockProvider())
    assert await r.rerank("q", []) == []


# ---------------------------------------------------------------------------
# ChromaVectorStore applies the reranker in query()
# ---------------------------------------------------------------------------


def _make_store(reranker):
    import chromadb
    from backend.vector_store import ChromaVectorStore, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP

    store = ChromaVectorStore.__new__(ChromaVectorStore)
    store._llm = _MockProvider()
    store._chunk_size = DEFAULT_CHUNK_SIZE
    store._chunk_overlap = DEFAULT_CHUNK_OVERLAP
    store._chunk_strategy = "char"
    store._overfetch_multiplier = 5
    store._min_score = 0.0
    store._reranker = reranker
    store._rerank_top_k = 20
    store._collection_config = {"hnsw": {"space": "cosine"}}
    store._embed_sem = asyncio.Semaphore(1)
    store._embed_concurrency = 1
    store._client = chromadb.EphemeralClient()
    store._collection = store._client.get_or_create_collection(
        name="rerank_test", configuration=store._collection_config,
    )
    return store


class _PreferReranker:
    """Scores passages containing 'PREFER' highly, regardless of vector rank."""

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        return [1.0 if "PREFER" in p else 0.1 for p in passages]


@pytest.mark.asyncio
async def test_query_uses_reranker_scores_and_order() -> None:
    store = _make_store(_PreferReranker())
    await store.upsert(1, "ordinary content about taxes", {"title": "Doc 1"})
    await store.upsert(2, "PREFER this document about taxes", {"title": "Doc 2"})

    results = await store.query("taxes", top_n=2)
    assert results[0].document_id == 2, "reranked-preferred doc must rank first"
    assert results[0].score == pytest.approx(1.0)
    assert results[1].score == pytest.approx(0.1)
