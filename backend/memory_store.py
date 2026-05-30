"""Long-term memory store for Discovery conversations.

Facts extracted from past conversations are embedded into a dedicated vector
collection ("piq_memories") and retrieved semantically at the start of each new
Discovery session so the model has relevant prior context.

The store follows the configured vector backend: ChromaMemoryStore (local) or
QdrantMemoryStore. Both share the dedup logic (``find_similar``) and the
``(memory_id, cosine_similarity)`` query contract; pick one via
``make_memory_store``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

import chromadb

if TYPE_CHECKING:
    from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)

# Cosine similarity above this threshold → update the existing memory instead
# of inserting a new one.  0.88 corresponds to very close paraphrase.
SIMILARITY_THRESHOLD = 0.88

# Stable namespace for deriving Qdrant point UUIDs from a memory id string.
_MEMORY_POINT_NAMESPACE = uuid.UUID("1b4e28ba-2fa1-11d2-883f-0016d3cca427")


class MemoryStore:
    """Base class: shared embedding + dedup logic. Subclasses implement storage."""

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm = llm_provider

    async def _embed(self, text: str) -> list[float]:
        return await self._llm.embed(text)

    # Storage operations — implemented by subclasses.
    async def upsert(self, memory_id: str, text: str) -> None:
        raise NotImplementedError

    async def delete(self, memory_id: str) -> None:
        raise NotImplementedError

    async def delete_all(self) -> None:
        raise NotImplementedError

    async def query(self, text: str, top_n: int = 5) -> list[tuple[str, float]]:
        """Return ``(memory_id, cosine_similarity)`` for the top-N matches."""
        raise NotImplementedError

    async def find_similar(self, text: str) -> str | None:
        """Return the ID of the most similar existing memory if it exceeds the
        deduplication threshold, otherwise ``None``."""
        pairs = await self.query(text, top_n=1)
        if pairs and pairs[0][1] >= SIMILARITY_THRESHOLD:
            return pairs[0][0]
        return None


class ChromaMemoryStore(MemoryStore):
    """Memory facts in a ChromaDB collection (shares the documents' Chroma dir)."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        persist_directory: str = "/data/chroma",
        collection_name: str = "piq_memories",
    ) -> None:
        super().__init__(llm_provider)
        self._chroma = chromadb.PersistentClient(path=persist_directory)
        self._col = self._chroma.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
        )

    async def upsert(self, memory_id: str, text: str) -> None:
        embedding = await self._embed(text)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._col.upsert(ids=[memory_id], embeddings=[embedding], documents=[text]),
        )

    async def delete(self, memory_id: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: self._col.delete(ids=[memory_id]))
        except Exception:
            logger.debug("MemoryStore.delete: %s not found in Chroma", memory_id)

    async def delete_all(self) -> None:
        loop = asyncio.get_running_loop()
        all_ids = await loop.run_in_executor(None, lambda: self._col.get(include=[])["ids"])
        if all_ids:
            await loop.run_in_executor(None, lambda: self._col.delete(ids=all_ids))

    async def query(self, text: str, top_n: int = 5) -> list[tuple[str, float]]:
        count = self._col.count()
        if count == 0:
            return []
        embedding = await self._embed(text)
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self._col.query(
                query_embeddings=[embedding],
                n_results=min(top_n, count),
                include=["distances"],
            ),
        )
        return [
            (mid, 1.0 - dist)
            for mid, dist in zip(results["ids"][0], results["distances"][0])
        ]


class QdrantMemoryStore(MemoryStore):
    """Memory facts in a Qdrant collection (async client; D-06)."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        url: str = "http://qdrant:6333",
        api_key: str = "",
        collection_name: str = "piq_memories",
    ) -> None:
        super().__init__(llm_provider)
        from qdrant_client import AsyncQdrantClient

        self._collection = collection_name
        if url == ":memory:":
            self._client = AsyncQdrantClient(location=":memory:")
        else:
            self._client = AsyncQdrantClient(url=url, api_key=api_key or None)
        self._ready = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _point_id(memory_id: str) -> str:
        return str(uuid.uuid5(_MEMORY_POINT_NAMESPACE, memory_id))

    async def _present(self) -> bool:
        if self._ready:
            return True
        try:
            exists = await self._client.collection_exists(self._collection)
        except Exception:
            return False
        self._ready = exists
        return exists

    async def _ensure(self, dim: int) -> None:
        from qdrant_client import models

        async with self._lock:
            if self._ready:
                return
            if not await self._client.collection_exists(self._collection):
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
                )
            self._ready = True

    async def upsert(self, memory_id: str, text: str) -> None:
        from qdrant_client import models

        embedding = await self._embed(text)
        await self._ensure(len(embedding))
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=self._point_id(memory_id),
                    vector=embedding,
                    payload={"memory_id": memory_id, "text": text},
                )
            ],
        )

    async def delete(self, memory_id: str) -> None:
        if not await self._present():
            return
        try:
            await self._client.delete(
                collection_name=self._collection,
                points_selector=[self._point_id(memory_id)],
            )
        except Exception:
            logger.debug("MemoryStore.delete: %s not found in Qdrant", memory_id)

    async def delete_all(self) -> None:
        try:
            if await self._client.collection_exists(self._collection):
                await self._client.delete_collection(self._collection)
        except Exception:
            logger.debug("MemoryStore.delete_all failed", exc_info=True)
        self._ready = False

    async def query(self, text: str, top_n: int = 5) -> list[tuple[str, float]]:
        if not await self._present():
            return []
        embedding = await self._embed(text)
        res = await self._client.query_points(
            collection_name=self._collection,
            query=embedding,
            limit=top_n,
            with_payload=True,
        )
        # Qdrant cosine score is the similarity directly (no 1 - dist).
        return [((p.payload or {}).get("memory_id", str(p.id)), p.score) for p in res.points]


def make_memory_store(config: Any, llm_provider: LLMProvider) -> MemoryStore:
    """Build the memory store matching the configured vector backend."""
    backend = getattr(config, "vector_store_backend", "local")
    collection = getattr(config, "qdrant_memory_collection", "piq_memories")
    if backend == "qdrant":
        raw_key = getattr(config, "qdrant_api_key", b"")
        api_key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key or "")
        return QdrantMemoryStore(
            llm_provider,
            url=getattr(config, "qdrant_url", "http://qdrant:6333"),
            api_key=api_key,
            collection_name=collection,
        )
    return ChromaMemoryStore(llm_provider, persist_directory="/data/chroma")
