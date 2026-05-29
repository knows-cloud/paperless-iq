"""Protocol definitions for LLM providers and vector stores."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from backend.models import SearchResult


@runtime_checkable
class LLMProvider(Protocol):
    """Unified interface for all LLM provider implementations."""

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Send a multi-turn chat request and return the response text.

        ``messages`` is a list of ``{role, content}`` dicts.  A leading entry
        with ``role == "system"`` is extracted and forwarded correctly for each
        provider's API.

        ``output_schema``: JSON Schema dict — enables native structured output.
        ``images``: JPEG bytes for each page — enables multimodal/vision input.
        """
        ...

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Single-turn convenience wrapper — equivalent to chat([user_msg])."""
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
