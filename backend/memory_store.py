"""Long-term memory store for Discovery conversations.

Facts extracted from past conversations are embedded into a dedicated ChromaDB
collection ("piq_memories") and retrieved semantically at the start of each new
Discovery session so the model has relevant prior context.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import chromadb

if TYPE_CHECKING:
    from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)

# Cosine similarity above this threshold → update the existing memory instead
# of inserting a new one.  0.88 corresponds to very close paraphrase.
SIMILARITY_THRESHOLD = 0.88


class MemoryStore:
    """Thin wrapper around a ChromaDB collection for user memory facts.

    Each memory is stored as a short text string with its embedding.  The
    collection lives alongside the documents collection in the same persistent
    Chroma directory.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        persist_directory: str = "/data/chroma",
    ) -> None:
        self._llm = llm_provider
        self._chroma = chromadb.PersistentClient(path=persist_directory)
        self._col = self._chroma.get_or_create_collection(
            name="piq_memories",
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _embed(self, text: str) -> list[float]:
        return await self._llm.embed(text)

    def _count(self) -> int:
        return self._col.count()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upsert(self, memory_id: str, text: str) -> None:
        """Embed ``text`` and store / update the entry for ``memory_id``."""
        embedding = await self._embed(text)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._col.upsert(
                ids=[memory_id],
                embeddings=[embedding],
                documents=[text],
            ),
        )

    async def delete(self, memory_id: str) -> None:
        """Remove a single memory entry by ID."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self._col.delete(ids=[memory_id])
            )
        except Exception:
            logger.debug("MemoryStore.delete: %s not found in Chroma", memory_id)

    async def delete_all(self) -> None:
        """Remove every memory from the collection."""
        loop = asyncio.get_event_loop()
        all_ids = await loop.run_in_executor(
            None, lambda: self._col.get(include=[])["ids"]
        )
        if all_ids:
            await loop.run_in_executor(
                None, lambda: self._col.delete(ids=all_ids)
            )

    async def query(self, text: str, top_n: int = 5) -> list[tuple[str, float]]:
        """Return ``(memory_id, cosine_similarity)`` pairs for the top-N matches.

        Returns an empty list when the collection is empty.
        """
        count = self._count()
        if count == 0:
            return []
        embedding = await self._embed(text)
        loop = asyncio.get_event_loop()
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

    async def find_similar(self, text: str) -> str | None:
        """Return the ID of the most similar existing memory if it exceeds the
        deduplication threshold, otherwise ``None``."""
        pairs = await self.query(text, top_n=1)
        if pairs and pairs[0][1] >= SIMILARITY_THRESHOLD:
            return pairs[0][0]
        return None
