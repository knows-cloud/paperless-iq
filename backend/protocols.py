"""Protocol definitions for LLM providers and vector stores."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

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

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        """Generate an embedding vector for the given text.

        ``is_query`` distinguishes a search query from a document being indexed.
        Asymmetric embedding models (e.g. Cohere) optimise the two differently;
        providers that don't differentiate may ignore it.
        """
        ...

    async def health_check(self) -> bool:
        """Return True if the provider is reachable and operational."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Re-scores (query, passage) pairs after the vector store returns candidates."""

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        """Return a relevance score in ``[0, 1]`` per passage, in input order."""
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

    async def query_chunks(self, text: str, top_n_chunks: int) -> list[dict[str, Any]]:
        """Return the top-N most relevant chunks (not grouped by document).

        Each result carries ``document_id``, ``title``, ``passage``, ``score``,
        ``deeplink_url`` and ``chunk_index``. Used by Discovery.
        """
        ...

    async def query_similar_metadata(
        self,
        text: str,
        top_n: int,
        exclude_tag_id: int | None = None,
    ) -> dict[str, set[str]]:
        """Collect entity metadata (tags/correspondents/types/custom fields)
        from the top-N most similar documents. ``exclude_tag_id`` lets a backend
        omit documents carrying a given tag (e.g. the inbox tag)."""
        ...

    async def query_chunks_by_vector(
        self,
        vector: list[float],
        top_n_chunks: int,
        entity_filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Like query_chunks() but takes a precomputed vector — no embed call.

        Each result carries ``document_id``, ``title``, ``passage``, ``score``
        and chunk metadata (``tags_json``, ``correspondent``,
        ``document_type``). ``entity_filter`` restricts results to chunks
        carrying a given entity (cohort scoring for the grooming scan), e.g.
        ``{"correspondent": "Telekom"}`` or ``{"tag_id": 12}``. Backends that
        cannot express a given filter raise ``NotImplementedError`` for that
        filter (Chroma cannot filter on tag_id; Bedrock KB supports no vector
        queries at all)."""
        ...

    async def count(self) -> int:
        """Return the number of stored vectors (chunks)."""
        ...

    async def reset(self) -> None:
        """Wipe all vectors (e.g. before switching embedding models)."""
        ...

    async def embed_health_check(self) -> bool:
        """Return True if the backend's embedding provider is reachable."""
        ...

    async def embed_probe(self) -> bool:
        """Attempt a real minimal embed call to verify the service actually works.

        Unlike embed_health_check(), which may only verify credentials, this
        sends a genuine embed request (1-token text) and returns True on success.
        Used by the circuit-breaker recovery monitor.
        """
        ...

    async def get_indexed_chunk_counts(self) -> tuple[dict[int, int], dict[int, int]]:
        """Return ``(per_doc_chunk_count, per_doc_expected_total)`` for the
        currently indexed vectors, used to detect partially-indexed documents."""
        ...

    @property
    def embed_concurrency(self) -> int:
        """The current embedding concurrency limit (read-only)."""
        ...
