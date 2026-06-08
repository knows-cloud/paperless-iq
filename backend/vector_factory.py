"""Factory selecting the vector store backend from configuration.

Centralises construction of ChromaVectorStore / QdrantVectorStore /
BedrockKnowledgeBaseStore so the lifespan and settings-reload paths build them
identically (and so the reranker + search-tuning knobs are wired in one place).
Also fixes the pre-existing gap where the lifespan never honoured bedrock_kb.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.protocols import LLMProvider, VectorStore
from backend.rerankers import build_reranker
from backend.vector_store import (
    BedrockKnowledgeBaseStore,
    ChromaVectorStore,
    QdrantVectorStore,
)

logger = logging.getLogger(__name__)


def _plaintext(value: Any) -> str:
    """Decode an in-memory credential blob (already decrypted on load)."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value or "")


def make_vector_store(
    config: Any,
    embed_provider: LLMProvider,
    embed_concurrency: int,
    providers: dict | None = None,
) -> VectorStore | None:
    """Build the configured vector store, or None when it can't be satisfied."""
    backend = getattr(config, "vector_store_backend", "local")
    reranker = build_reranker(config, providers)
    embed_batch_size = getattr(config, "embed_batch_size", 1)

    if backend == "qdrant":
        return QdrantVectorStore(
            llm_provider=embed_provider,
            url=config.qdrant_url,
            api_key=_plaintext(getattr(config, "qdrant_api_key", b"")),
            collection_name=config.qdrant_collection,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            embed_concurrency=embed_concurrency,
            embed_batch_size=embed_batch_size,
            chunk_strategy=config.chunk_strategy,
            overfetch_multiplier=config.search_overfetch_multiplier,
            min_score=config.search_min_score,
            reranker=reranker,
            rerank_top_k=config.rerank_top_k,
            hnsw_ef=config.qdrant_hnsw_ef,
            hnsw_m=config.qdrant_hnsw_m,
            quantization=config.qdrant_quantization,
            hybrid_search=config.qdrant_hybrid_search,
        )

    if backend == "bedrock_kb":
        kb_id = getattr(config, "bedrock_kb_id", None)
        if not kb_id:
            logger.warning("bedrock_kb backend selected but bedrock_kb_id is empty; no vector store.")
            return None
        return BedrockKnowledgeBaseStore(kb_id)

    # Default: local Chroma
    return ChromaVectorStore(
        llm_provider=embed_provider,
        persist_directory="/data/chroma",
        embed_concurrency=embed_concurrency,
        embed_batch_size=embed_batch_size,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        chunk_strategy=config.chunk_strategy,
        overfetch_multiplier=config.search_overfetch_multiplier,
        min_score=config.search_min_score,
        hnsw_search_ef=config.chroma_hnsw_search_ef,
        hnsw_m=config.chroma_hnsw_m,
        hnsw_construction_ef=config.chroma_hnsw_construction_ef,
        reranker=reranker,
        rerank_top_k=config.rerank_top_k,
    )
