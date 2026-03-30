"""Protocol definitions for LLM providers and vector stores."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from backend.models import SearchResult


@runtime_checkable
class LLMProvider(Protocol):
    """Unified interface for all LLM provider implementations."""

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Send a completion request and return the response text."""
        ...

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        ...

    async def health_check(self) -> bool:
        """Return True if the provider is reachable and operational."""
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Unified interface for vector store backends."""

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        """Insert or update a document embedding."""
        ...

    async def delete(self, doc_id: int) -> None:
        """Remove a document embedding by document ID."""
        ...

    async def query(self, text: str, top_n: int) -> list[SearchResult]:
        """Return the top-N most semantically similar documents."""
        ...

    async def reindex_all(self, documents: list) -> None:
        """Re-index all documents (used when switching backends)."""
        ...
