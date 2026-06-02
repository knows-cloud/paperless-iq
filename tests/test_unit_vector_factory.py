"""Unit tests for make_vector_store backend selection (QDRANT_PLAN §7.1)."""

from __future__ import annotations

import hashlib

import pytest

import backend.vector_factory as vf
from backend.models import PaperlessIQConfig
from backend.vector_store import QdrantVectorStore


class _MockLLMProvider:
    async def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]

    async def health_check(self) -> bool:
        return True


def _config(**overrides) -> PaperlessIQConfig:
    base = {"llm_provider": "ollama", "llm_model": "llama3"}
    base.update(overrides)
    return PaperlessIQConfig(**base)


def test_factory_qdrant_backend() -> None:
    cfg = _config(vector_store_backend="qdrant", qdrant_url=":memory:")
    store = vf.make_vector_store(cfg, _MockLLMProvider(), 1, providers={})
    assert isinstance(store, QdrantVectorStore)


def test_factory_bedrock_kb_without_id_returns_none() -> None:
    cfg = _config(vector_store_backend="bedrock_kb", bedrock_kb_id=None)
    assert vf.make_vector_store(cfg, _MockLLMProvider(), 1, providers={}) is None


def test_factory_bedrock_kb_with_id(monkeypatch) -> None:
    captured = {}

    class _StubKB:
        def __init__(self, kb_id):
            captured["kb_id"] = kb_id

    monkeypatch.setattr(vf, "BedrockKnowledgeBaseStore", _StubKB)
    cfg = _config(vector_store_backend="bedrock_kb", bedrock_kb_id="kb-123")
    store = vf.make_vector_store(cfg, _MockLLMProvider(), 1, providers={})
    assert isinstance(store, _StubKB)
    assert captured["kb_id"] == "kb-123"


def test_factory_local_default_is_chroma(monkeypatch) -> None:
    captured = {}

    class _StubChroma:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(vf, "ChromaVectorStore", _StubChroma)
    cfg = _config(vector_store_backend="local")
    store = vf.make_vector_store(cfg, _MockLLMProvider(), 3, providers={})
    assert isinstance(store, _StubChroma)
    assert captured["persist_directory"] == "/data/chroma"
    assert captured["embed_concurrency"] == 3
    # search-tuning + reranker knobs are threaded through
    assert captured["hnsw_search_ef"] == cfg.chroma_hnsw_search_ef
    assert captured["reranker"] is None  # rerank disabled by default
