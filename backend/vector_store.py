"""Vector store implementations for Paperless IQ.

Provides ChromaVectorStore (local, chunked embeddings) and
BedrockKnowledgeBaseStore (cloud) conforming to the VectorStore Protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import uuid

import chromadb

from backend.models import SearchResult
from backend.protocols import LLMProvider, Reranker

logger = logging.getLogger(__name__)

PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://localhost:8000")

# Stable namespace for deriving Qdrant point UUIDs from "{doc_id}_{chunk_index}".
_QDRANT_POINT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

# Chunking defaults
DEFAULT_CHUNK_SIZE = 1000  # characters per chunk
DEFAULT_CHUNK_OVERLAP = 200  # overlap between consecutive chunks


def _deeplink(doc_id: int) -> str:
    base = PAPERLESS_URL.rstrip("/")
    return f"{base}/documents/{doc_id}/details"


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping character chunks.

    Returns at least one chunk (the full text if shorter than chunk_size).
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def _chunk_text_sentences(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split on sentence boundaries, then pack sentences up to chunk_size.

    Avoids mid-word/mid-sentence cuts. Consecutive chunks overlap by carrying
    trailing sentences totalling up to ``overlap`` characters. A single
    sentence longer than chunk_size falls back to character splitting.
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sentences = [s.strip() for s in _SENTENCE_BOUNDARY.split(text) if s.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        if len(sent) > chunk_size:
            # Oversized single sentence — flush, then char-split it.
            if current:
                chunks.append(" ".join(current))
                current, current_len = [], 0
            chunks.extend(_chunk_text(sent, chunk_size, overlap))
            continue
        if current and current_len + len(sent) + 1 > chunk_size:
            chunks.append(" ".join(current))
            # Carry trailing sentences (up to `overlap` chars) into the next chunk.
            carry: list[str] = []
            carry_len = 0
            for prev in reversed(current):
                if carry_len + len(prev) + 1 > overlap:
                    break
                carry.insert(0, prev)
                carry_len += len(prev) + 1
            current, current_len = carry, carry_len
        current.append(sent)
        current_len += len(sent) + 1

    if current:
        chunks.append(" ".join(current))
    return chunks


def _chunk(text: str, chunk_size: int, overlap: int, strategy: str) -> list[str]:
    """Dispatch to the configured chunking strategy."""
    if strategy == "sentence":
        return _chunk_text_sentences(text, chunk_size, overlap)
    return _chunk_text(text, chunk_size, overlap)


def _build_embed_prefix(metadata: dict) -> str:
    """Build the metadata prefix prepended to every chunk before embedding.

    Captures WHO/WHAT the document is (title, type, correspondent, tags,
    custom fields) so the vector reflects identity, not just raw OCR content.
    Shared by every backend so the embedded text is identical across stores.
    """
    prefix_parts: list[str] = []
    if metadata.get("title"):
        prefix_parts.append(f"Title: {metadata['title']}")
    if metadata.get("document_type"):
        prefix_parts.append(f"Type: {metadata['document_type']}")
    if metadata.get("correspondent"):
        prefix_parts.append(f"From: {metadata['correspondent']}")
    tags = metadata.get("tags") or []
    if isinstance(tags, list) and any(tags):
        # Coerce defensively: callers should pass tag names, but a stray ID
        # (int) must not crash embedding for the whole document.
        prefix_parts.append(f"Tags: {', '.join(str(t) for t in tags if t)}")
    for cf_name, cf_value in (metadata.get("custom_fields") or {}).items():
        if cf_value is not None and str(cf_value).strip():
            prefix_parts.append(f"{cf_name}: {cf_value}")
    return "\n".join(prefix_parts) + "\n\n" if prefix_parts else ""


def _build_base_meta(doc_id: int, metadata: dict) -> dict[str, Any]:
    """Per-chunk payload fields stored by every backend (shared shape).

    ``tag_ids_json`` is the canonical, migration-safe form of the document's
    tag IDs (Chroma metadata can't hold lists). Backends that can filter on
    arrays (Qdrant) derive a list from it; it powers ``exclude_tag_id``.
    """
    return {
        "document_id": doc_id,
        "title": metadata.get("title", ""),
        "tags_json": json.dumps(metadata.get("tags", [])),
        "tag_ids_json": json.dumps([int(t) for t in (metadata.get("tag_ids") or [])]),
        "correspondent": metadata.get("correspondent") or "",
        "document_type": metadata.get("document_type") or "",
        "custom_fields_json": json.dumps(metadata.get("custom_fields") or {}),
    }


def _meta_has_tag(meta: dict, tag_id: int) -> bool:
    """True if the chunk's stored tag_ids_json contains ``tag_id``."""
    try:
        ids = json.loads(meta.get("tag_ids_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        return False
    return tag_id in ids


async def _maybe_rerank(
    reranker: Reranker | None, query: str, passages: list[str]
) -> list[float] | None:
    """Per-passage rerank scores in [0,1], or None when no reranker is set."""
    if reranker is None or not passages:
        return None
    return await reranker.rerank(query, passages)


def _assemble_doc_results(
    candidates: list[dict[str, Any]],
    rerank_scores: list[float] | None,
    min_score: float,
    top_n: int,
) -> list[SearchResult]:
    """Group candidate chunks by document (best score per doc), drop those
    below min_score, sort by score desc, and return up to top_n results.

    Each candidate carries ``document_id``, ``title``, ``passage`` and a
    normalised ``score`` in [0,1]; ``rerank_scores`` (aligned to ``candidates``)
    overrides the score when present. Shared by every backend.
    """
    seen: dict[int, dict[str, Any]] = {}
    for i, c in enumerate(candidates):
        doc_id = c["document_id"]
        if not doc_id:
            continue
        score = rerank_scores[i] if rerank_scores is not None else c["score"]
        if doc_id not in seen or score > seen[doc_id]["score"]:
            seen[doc_id] = {"score": score, "passage": c["passage"], "title": c["title"]}

    results: list[SearchResult] = []
    for doc_id, info in sorted(seen.items(), key=lambda x: x[1]["score"], reverse=True):
        if info["score"] < min_score:
            continue
        results.append(SearchResult(
            document_id=doc_id,
            document_title=info["title"],
            passage=info["passage"] or "",
            score=info["score"],
            deeplink_url=_deeplink(doc_id),
        ))
    return results[:top_n]


def _assemble_chunk_results(
    candidates: list[dict[str, Any]],
    rerank_scores: list[float] | None,
    min_score: float,
) -> list[dict[str, Any]]:
    """Filter ungrouped chunk candidates by min_score; when reranked, override
    the score and re-sort by it (vector order is already distance-sorted)."""
    out: list[dict[str, Any]] = []
    for i, c in enumerate(candidates):
        score = rerank_scores[i] if rerank_scores is not None else c["score"]
        if score < min_score:
            continue
        out.append({**c, "score": score})
    if rerank_scores is not None:
        out.sort(key=lambda c: c["score"], reverse=True)
    return out


class _EmbeddingBackedStore:
    """Shared embedding plumbing for stores that embed via an ``LLMProvider``.

    Subclasses set ``_llm`` and ``_embed_concurrency`` in their constructor.
    """

    _llm: LLMProvider
    _embed_concurrency: int

    async def _embed(self, text: str, *, is_query: bool = False) -> list[float]:
        return await self._llm.embed(text, is_query=is_query)

    async def embed_health_check(self) -> bool:
        """Return True if the embedding provider is reachable."""
        return await self._llm.health_check()

    async def embed_probe(self) -> bool:
        """Attempt a real minimal embed call — same code path as production embeds."""
        try:
            await self._llm.embed("test")
            return True
        except Exception:
            return False

    @property
    def embed_concurrency(self) -> int:
        """The current embedding concurrency limit (read-only)."""
        return self._embed_concurrency


class ChromaVectorStore(_EmbeddingBackedStore):
    """Local persistent vector store backed by ChromaDB with chunked embeddings.

    Documents are split into overlapping chunks before embedding. Each chunk
    is stored as a separate vector with metadata linking back to the parent
    document. This ensures full document content is searchable regardless of
    embedding model context limits.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        persist_directory: str = "/data/chroma",
        collection_name: str = "paperless_iq_chunks",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        embed_concurrency: int = 1,
        chunk_strategy: str = "char",
        overfetch_multiplier: int = 5,
        min_score: float = 0.0,
        hnsw_search_ef: int = 100,
        hnsw_m: int = 16,
        hnsw_construction_ef: int = 100,
        reranker: Reranker | None = None,
        rerank_top_k: int = 20,
    ) -> None:
        self._llm = llm_provider
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._chunk_strategy = chunk_strategy
        self._overfetch_multiplier = overfetch_multiplier
        self._min_score = min_score
        self._reranker = reranker
        self._rerank_top_k = rerank_top_k
        # HNSW index configuration. ef_search is query-time; max_neighbors (M)
        # and ef_construction are build-time — they only take effect on a fresh
        # collection, so changing them requires reset()/reindex.
        self._collection_config = {
            "hnsw": {
                "space": "cosine",
                "ef_search": hnsw_search_ef,
                "max_neighbors": hnsw_m,
                "ef_construction": hnsw_construction_ef,
            }
        }
        self._embed_sem = asyncio.Semaphore(embed_concurrency)
        self._embed_concurrency = embed_concurrency
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            configuration=self._collection_config,
        )

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        """Split document into chunks, embed all in parallel, and store with metadata."""
        # First delete any existing chunks for this document
        await self.delete(doc_id)

        chunks = _chunk(text, self._chunk_size, self._chunk_overlap, self._chunk_strategy)
        if not chunks:
            return

        # Prefix captures WHO/WHAT the document is (title, type, correspondent,
        # tags, custom fields) so a salary-slip chunk that merely mentions
        # "Lebensversicherung" doesn't outrank an actual life-insurance document.
        embed_prefix = _build_embed_prefix(metadata)
        base_meta = _build_base_meta(doc_id, metadata)
        total = len(chunks)
        loop = asyncio.get_running_loop()
        succeeded = 0

        async def _embed_and_store(i: int, chunk: str) -> None:
            nonlocal succeeded
            async with self._embed_sem:
                try:
                    embedding = await self._embed(embed_prefix + chunk)
                except Exception:
                    logger.debug("Failed to embed chunk %d of doc %d", i, doc_id, exc_info=True)
                    return
            chunk_id = f"{doc_id}_{i}"
            chunk_meta = {**base_meta, "chunk_index": i, "total_chunks": total}
            await loop.run_in_executor(
                None,
                lambda cid=chunk_id, emb=embedding, ch=chunk, cm=chunk_meta: self._collection.upsert(
                    ids=[cid], embeddings=[emb], documents=[ch], metadatas=[cm],
                ),
            )
            succeeded += 1

        await asyncio.gather(*[_embed_and_store(i, chunk) for i, chunk in enumerate(chunks)])
        if succeeded == 0:
            raise RuntimeError(f"All {total} chunk embeddings failed for document {doc_id}")
        logger.info("Upserted %d/%d chunks for document %d.", succeeded, total, doc_id)

    async def delete(self, doc_id: int) -> None:
        """Remove all chunks for a document."""
        loop = asyncio.get_running_loop()
        try:
            existing = await loop.run_in_executor(
                None,
                lambda: self._collection.get(
                    where={"document_id": doc_id}, include=[]
                ),
            )
            if existing["ids"]:
                await loop.run_in_executor(
                    None,
                    lambda: self._collection.delete(ids=existing["ids"]),
                )
        except Exception:
            # Fallback: try deleting by ID pattern (for old single-embedding format)
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._collection.delete(ids=[str(doc_id)]),
                )
            except Exception:
                pass

    def _candidate_count(self, top_n: int) -> int:
        """How many chunks to fetch from the vector index before post-processing.

        With a reranker, pull the top rerank_top_k candidates; otherwise
        over-fetch to surface enough unique documents.
        """
        if self._reranker is not None:
            return max(self._rerank_top_k, top_n)
        return top_n * self._overfetch_multiplier

    async def query(self, text: str, top_n: int) -> list[SearchResult]:
        """Find the most relevant document chunks and group by document.

        Returns up to top_n documents, each with the best matching passage.
        When a reranker is configured, candidates are re-scored before grouping.
        """
        embedding = await self._embed(text, is_query=True)
        loop = asyncio.get_running_loop()
        count = self._collection.count()
        if count == 0:
            return []

        n_chunks = min(self._candidate_count(top_n), count)
        results = await loop.run_in_executor(
            None,
            lambda: self._collection.query(
                query_embeddings=[embedding],
                n_results=n_chunks,
                include=["documents", "metadatas", "distances"],
            ),
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        # Build candidates with a normalised score (1 - dist/2 ∈ [0,1]),
        # resolving doc_id from metadata or the "docid_chunkidx" id format.
        candidates: list[dict[str, Any]] = []
        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            doc_id = meta.get("document_id", 0)
            if not doc_id:
                try:
                    doc_id = int(chunk_id.split("_")[0])
                except (ValueError, IndexError):
                    continue
            dist = distances[i] if i < len(distances) else 1.0
            candidates.append({
                "document_id": doc_id,
                "title": meta.get("title", ""),
                "passage": documents[i] if i < len(documents) else "",
                "score": 1.0 - (dist / 2.0),
            })

        rerank_scores = await _maybe_rerank(
            self._reranker, text, [c["passage"] for c in candidates]
        )
        return _assemble_doc_results(candidates, rerank_scores, self._min_score, top_n)

    async def query_similar_metadata(
        self,
        text: str,
        top_n: int,
        exclude_tag_id: int | None = None,
    ) -> dict[str, set[str]]:
        """Query similar document chunks and return parent document metadata.

        Groups chunks by document and collects entity names from the top-N
        unique documents.
        """
        embedding = await self._embed(text, is_query=True)
        loop = asyncio.get_running_loop()
        count = self._collection.count()
        if count == 0:
            return {"tags": set(), "correspondents": set(), "document_types": set()}

        n_chunks = min(top_n * self._overfetch_multiplier, count)
        results = await loop.run_in_executor(
            None,
            lambda: self._collection.query(
                query_embeddings=[embedding],
                n_results=n_chunks,
                include=["metadatas"],
            ),
        )

        all_tags: set[str] = set()
        all_correspondents: set[str] = set()
        all_document_types: set[str] = set()
        all_custom_fields: dict[str, set[str]] = {}
        seen_doc_ids: set[int] = set()

        if results["metadatas"] and results["metadatas"][0]:
            for meta in results["metadatas"][0]:
                doc_id = meta.get("document_id", 0)
                if doc_id in seen_doc_ids:
                    continue
                # Skip documents carrying the excluded tag (e.g. the inbox tag)
                # so suggestions don't come from un-reviewed documents.
                if exclude_tag_id is not None and _meta_has_tag(meta, exclude_tag_id):
                    continue
                seen_doc_ids.add(doc_id)
                if len(seen_doc_ids) > top_n:
                    break

                tags_json = meta.get("tags_json", "[]")
                try:
                    tag_list = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
                except (json.JSONDecodeError, TypeError):
                    tag_list = []
                for t in tag_list:
                    if t:
                        all_tags.add(t)
                corr = meta.get("correspondent", "")
                if corr:
                    all_correspondents.add(corr)
                dt = meta.get("document_type", "")
                if dt:
                    all_document_types.add(dt)
                try:
                    cf_dict = json.loads(meta.get("custom_fields_json") or "{}")
                except (json.JSONDecodeError, TypeError):
                    cf_dict = {}
                for cf_name, cf_value in cf_dict.items():
                    if cf_value is not None and str(cf_value).strip():
                        all_custom_fields.setdefault(cf_name, set()).add(str(cf_value))

        return {
            "tags": all_tags,
            "correspondents": all_correspondents,
            "document_types": all_document_types,
            "custom_fields": all_custom_fields,
        }

    async def count(self) -> int:
        """Return the number of chunks in the store."""
        return self._collection.count()

    async def get_indexed_chunk_counts(self) -> tuple[dict[int, int], dict[int, int]]:
        """Enumerate stored chunks and return per-document counts.

        Returns ``(per_doc_chunk_count, per_doc_expected_total)`` where the
        expected total comes from each chunk's ``total_chunks`` metadata. Used
        to detect partially-indexed documents that need re-embedding.
        """
        loop = asyncio.get_running_loop()
        existing = await loop.run_in_executor(
            None,
            lambda: self._collection.get(include=["metadatas"]),
        )
        doc_chunk_counts: dict[int, int] = {}
        doc_expected_chunks: dict[int, int] = {}
        metadatas = existing.get("metadatas") or []
        for i, chunk_id in enumerate(existing.get("ids", [])):
            try:
                doc_id_part = int(str(chunk_id).split("_")[0])
                doc_chunk_counts[doc_id_part] = doc_chunk_counts.get(doc_id_part, 0) + 1
                meta = metadatas[i] if i < len(metadatas) else {}
                if meta and "total_chunks" in meta:
                    doc_expected_chunks[doc_id_part] = int(meta["total_chunks"])
            except (ValueError, IndexError):
                pass
        return doc_chunk_counts, doc_expected_chunks

    async def query_chunks(self, text: str, top_n_chunks: int) -> list[dict[str, Any]]:
        """Return the top-N most relevant chunks (not grouped by document).

        Each result includes document_id, title, passage, score, and deeplink.
        Multiple chunks from the same document may appear.
        """
        embedding = await self._embed(text, is_query=True)
        loop = asyncio.get_running_loop()
        count = self._collection.count()
        if count == 0:
            return []

        results = await loop.run_in_executor(
            None,
            lambda: self._collection.query(
                query_embeddings=[embedding],
                n_results=min(top_n_chunks, count),
                include=["documents", "metadatas", "distances"],
            ),
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        candidates: list[dict[str, Any]] = []
        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            doc_id = meta.get("document_id", 0)
            dist = distances[i] if i < len(distances) else 1.0
            candidates.append({
                "document_id": doc_id,
                "title": meta.get("title", ""),
                "passage": documents[i] if i < len(documents) else "",
                "score": 1.0 - (dist / 2.0),
                "deeplink_url": _deeplink(doc_id),
                "chunk_index": meta.get("chunk_index", 0),
            })

        rerank_scores = await _maybe_rerank(
            self._reranker, text, [c["passage"] for c in candidates]
        )
        return _assemble_chunk_results(candidates, rerank_scores, self._min_score)

    async def query_chunks_by_vector(
        self,
        vector: list[float],
        top_n_chunks: int,
        entity_filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Vector-input chunk query for the grooming scan — no embed, no rerank
        (scan thresholds need raw cosine-derived scores).

        Chroma can filter on the scalar ``correspondent`` / ``document_type``
        fields but not on tag ids (they live in ``tag_ids_json``, a JSON
        string) — a ``tag_id`` filter raises NotImplementedError so the caller
        falls back to absolute-threshold rules.
        """
        where: dict[str, Any] | None = None
        if entity_filter:
            if "tag_id" in entity_filter:
                raise NotImplementedError("Chroma cannot filter chunks by tag id")
            where = {
                k: v for k, v in entity_filter.items()
                if k in ("correspondent", "document_type")
            } or None

        loop = asyncio.get_running_loop()
        count = self._collection.count()
        if count == 0:
            return []

        results = await loop.run_in_executor(
            None,
            lambda: self._collection.query(
                query_embeddings=[vector],
                n_results=min(top_n_chunks, count),
                where=where,
                include=["documents", "metadatas", "distances"],
            ),
        )
        if not results["ids"] or not results["ids"][0]:
            return []

        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        out: list[dict[str, Any]] = []
        for i in range(len(ids)):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            out.append({
                "document_id": meta.get("document_id", 0),
                "title": meta.get("title", ""),
                "passage": documents[i] if i < len(documents) else "",
                "score": 1.0 - (dist / 2.0),
                "tags_json": meta.get("tags_json", "[]"),
                "tag_ids_json": meta.get("tag_ids_json", "[]"),
                "correspondent": meta.get("correspondent", ""),
                "document_type": meta.get("document_type", ""),
            })
        return out

    async def reindex_all(self, documents: list[dict[str, Any]]) -> None:
        """Re-index all documents with chunking. Clears existing data first."""
        await self.reset()
        for doc in documents:
            await self.upsert(doc["doc_id"], doc["text"], doc.get("metadata", {}))

    async def reset(self) -> None:
        """Delete and recreate the ChromaDB collection (wipes all vectors).

        Call this before switching embedding models or to recover from a
        dimension-mismatch error.  All documents will need to be re-indexed.
        """
        loop = asyncio.get_running_loop()
        collection_name = self._collection.name
        await loop.run_in_executor(
            None,
            lambda: self._client.delete_collection(collection_name),
        )
        self._collection = await loop.run_in_executor(
            None,
            lambda: self._client.get_or_create_collection(
                name=collection_name,
                configuration=self._collection_config,
            ),
        )
        logger.info("Vector store collection '%s' reset (all vectors cleared).", collection_name)

    async def dump_points(self) -> list[dict[str, Any]]:
        """Export all stored points (id, vector, document, metadata) for
        backend-agnostic migration. No re-embedding."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            lambda: self._collection.get(include=["embeddings", "documents", "metadatas"]),
        )
        ids = data.get("ids", []) or []
        embeddings = data.get("embeddings")
        embeddings = embeddings if embeddings is not None else []
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        points: list[dict[str, Any]] = []
        for i, pid in enumerate(ids):
            if i >= len(embeddings) or embeddings[i] is None:
                continue
            points.append({
                "id": str(pid),
                "vector": [float(x) for x in embeddings[i]],
                "document": documents[i] if i < len(documents) else "",
                "metadata": dict(metadatas[i]) if i < len(metadatas) and metadatas[i] else {},
            })
        return points

    async def load_points(self, points: list[dict[str, Any]]) -> int:
        """Bulk-insert points from dump_points() preserving ids/vectors/metadata."""
        if not points:
            return 0
        loop = asyncio.get_running_loop()
        ids = [p["id"] for p in points]
        embeddings = [p["vector"] for p in points]
        documents = [p.get("document", "") for p in points]
        metadatas = [p.get("metadata") or {} for p in points]
        await loop.run_in_executor(
            None,
            lambda: self._collection.upsert(
                ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
            ),
        )
        return len(points)


class QdrantVectorStore(_EmbeddingBackedStore):
    """Vector store backed by Qdrant with chunked embeddings.

    Mirrors ChromaVectorStore semantics (same chunking, embed prefix, payload
    shape, and SearchResult.score convention) so results are comparable across
    backends. Uses the async client (D-06: never get_event_loop()).
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        url: str = "http://qdrant:6333",
        api_key: str = "",
        collection_name: str = "paperless_iq_chunks",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        embed_concurrency: int = 1,
        chunk_strategy: str = "char",
        overfetch_multiplier: int = 5,
        min_score: float = 0.0,
        reranker: Reranker | None = None,
        rerank_top_k: int = 20,
        hnsw_ef: int = 128,
        hnsw_m: int = 16,
        quantization: str = "none",
        hybrid_search: bool = False,
        sparse_model: str = "Qdrant/bm25",
    ) -> None:
        from qdrant_client import AsyncQdrantClient

        self._llm = llm_provider
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._chunk_strategy = chunk_strategy
        self._overfetch_multiplier = overfetch_multiplier
        self._min_score = min_score
        self._reranker = reranker
        self._rerank_top_k = rerank_top_k
        self._hnsw_ef = hnsw_ef
        self._hnsw_m = hnsw_m
        self._quantization = quantization
        # Hybrid = dense + sparse (BM25/SPLADE) fused with RRF. The sparse encoder
        # (fastembed) is an optional dep, loaded lazily on first use. Tests may
        # inject a fake encoder by setting ``_sparse_encoder`` before indexing.
        self._hybrid_search = hybrid_search
        self._sparse_model = sparse_model
        self._sparse_encoder: Any = None
        self._embed_sem = asyncio.Semaphore(embed_concurrency)
        self._embed_concurrency = embed_concurrency
        self._collection = collection_name
        if url == ":memory:":
            self._client = AsyncQdrantClient(location=":memory:")
        else:
            self._client = AsyncQdrantClient(url=url, api_key=api_key or None)
        self._ready = False
        self._init_lock = asyncio.Lock()

    @staticmethod
    def _point_id(doc_id: int, chunk_index: int) -> str:
        return str(uuid.uuid5(_QDRANT_POINT_NAMESPACE, f"{doc_id}_{chunk_index}"))

    def _ensure_sparse_encoder(self):
        """Lazily load the fastembed sparse encoder (optional dependency)."""
        if self._sparse_encoder is None:
            try:
                from fastembed import SparseTextEmbedding
            except ImportError as exc:  # pragma: no cover - exercised via build path
                raise RuntimeError(
                    "Hybrid search needs the sparse encoder. Install it with "
                    "`pip install 'paperless-iq[qdrant-hybrid]'` (adds fastembed), "
                    "or disable qdrant_hybrid_search."
                ) from exc
            logger.info("Loading sparse encoder '%s' (first run downloads the model).", self._sparse_model)
            self._sparse_encoder = SparseTextEmbedding(self._sparse_model)
        return self._sparse_encoder

    async def _sparse_vectors(self, texts: list[str]) -> list:
        """Batch-encode texts to Qdrant SparseVectors (CPU encoder, off-loop)."""
        from qdrant_client import models

        if not texts:
            return []
        loop = asyncio.get_running_loop()

        def _encode():
            encoder = self._ensure_sparse_encoder()
            out = []
            for emb in encoder.embed(texts):
                indices = emb.indices.tolist() if hasattr(emb.indices, "tolist") else list(emb.indices)
                values = emb.values.tolist() if hasattr(emb.values, "tolist") else list(emb.values)
                out.append(models.SparseVector(indices=indices, values=values))
            return out

        return await loop.run_in_executor(None, _encode)

    async def _search_points(self, text: str, limit: int, query_filter=None):
        """Run dense (or hybrid dense+sparse RRF) retrieval, returning points."""
        from qdrant_client import models

        dense = await self._embed(text, is_query=True)
        if self._hybrid_search:
            sparse = (await self._sparse_vectors([text]))[0]
            res = await self._client.query_points(
                collection_name=self._collection,
                prefetch=[
                    models.Prefetch(query=dense, using="dense", limit=limit, filter=query_filter),
                    models.Prefetch(query=sparse, using="sparse", limit=limit, filter=query_filter),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=True,
            )
        else:
            res = await self._client.query_points(
                collection_name=self._collection,
                query=dense,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
            )
        return res.points

    def _quantization_config(self):
        from qdrant_client import models

        if self._quantization == "scalar":
            return models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, always_ram=True)
            )
        if self._quantization == "binary":
            return models.BinaryQuantization(
                binary=models.BinaryQuantizationConfig(always_ram=True)
            )
        return None

    async def _collection_present(self) -> bool:
        """True if the collection exists (cached once seen)."""
        if self._ready:
            return True
        try:
            exists = await self._client.collection_exists(self._collection)
        except Exception:
            return False
        self._ready = exists
        return exists

    async def _ensure_collection(self, dim: int) -> None:
        """Create the collection (with HNSW + quantization config) on first use."""
        from qdrant_client import models

        async with self._init_lock:
            if self._ready:
                return
            if not await self._client.collection_exists(self._collection):
                dense_params = models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                    hnsw_config=models.HnswConfigDiff(m=self._hnsw_m, ef_construct=self._hnsw_ef),
                    quantization_config=self._quantization_config(),
                )
                if self._hybrid_search:
                    # Named dense + sparse vectors for RRF fusion. Toggling hybrid
                    # changes the schema, so it requires a reindex (documented).
                    await self._client.create_collection(
                        collection_name=self._collection,
                        vectors_config={"dense": dense_params},
                        sparse_vectors_config={
                            "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
                        },
                    )
                else:
                    await self._client.create_collection(
                        collection_name=self._collection,
                        vectors_config=dense_params,
                    )
                # Payload indexes speed up filtering (server only; no-op locally).
                for field, schema in (
                    ("document_id", models.PayloadSchemaType.INTEGER),
                    ("document_type", models.PayloadSchemaType.KEYWORD),
                    ("correspondent", models.PayloadSchemaType.KEYWORD),
                    ("tag_ids", models.PayloadSchemaType.INTEGER),
                ):
                    try:
                        await self._client.create_payload_index(
                            self._collection, field_name=field, field_schema=schema
                        )
                    except Exception:
                        logger.debug("Qdrant payload index on %s skipped.", field, exc_info=True)
            self._ready = True

    def _doc_filter(self, doc_id: int):
        from qdrant_client import models

        return models.Filter(
            must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=doc_id))]
        )

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        """Chunk, embed in parallel under the semaphore, and bulk-upsert points."""
        from qdrant_client import models

        chunks = _chunk(text, self._chunk_size, self._chunk_overlap, self._chunk_strategy)
        if not chunks:
            await self.delete(doc_id)
            return

        embed_prefix = _build_embed_prefix(metadata)
        base_meta = _build_base_meta(doc_id, metadata)
        total = len(chunks)

        async def _embed_chunk(i: int, chunk: str) -> tuple[int, list[float] | None, str]:
            async with self._embed_sem:
                try:
                    return i, await self._embed(embed_prefix + chunk), chunk
                except Exception:
                    logger.debug("Failed to embed chunk %d of doc %d", i, doc_id, exc_info=True)
                    return i, None, chunk

        embedded = await asyncio.gather(*[_embed_chunk(i, c) for i, c in enumerate(chunks)])
        ok = [(i, emb, chunk) for (i, emb, chunk) in embedded if emb is not None]

        # tag_ids as a real list enables a server-side must_not filter for
        # exclude_tag_id (Qdrant-specific; derived from the canonical
        # tag_ids_json so it stays consistent and migration-safe).
        tag_ids = json.loads(base_meta.get("tag_ids_json") or "[]")

        # Sparse vectors for hybrid search — encode the same prefixed text as the
        # dense embedding so keyword matches include title/correspondent terms.
        sparse_by_idx: dict[int, Any] = {}
        if self._hybrid_search and ok:
            sparse_list = await self._sparse_vectors([embed_prefix + chunk for _, _, chunk in ok])
            sparse_by_idx = {i: sv for (i, _, _), sv in zip(ok, sparse_list)}

        points: list[Any] = []
        dim: int | None = None
        for i, emb, chunk in ok:
            dim = dim or len(emb)
            payload = {
                **base_meta,
                "tag_ids": tag_ids,
                "chunk_index": i,
                "total_chunks": total,
                "passage": chunk,
                "chunk_id": f"{doc_id}_{i}",
            }
            vector: Any = {"dense": emb, "sparse": sparse_by_idx[i]} if self._hybrid_search else emb
            points.append(models.PointStruct(id=self._point_id(doc_id, i), vector=vector, payload=payload))

        if not points or dim is None:
            raise RuntimeError(f"All {total} chunk embeddings failed for document {doc_id}")

        await self._ensure_collection(dim)
        await self.delete(doc_id)  # replace any existing chunks for this document
        await self._client.upsert(collection_name=self._collection, points=points)
        logger.info("Upserted %d/%d chunks for document %d.", len(points), total, doc_id)

    async def delete(self, doc_id: int) -> None:
        """Remove all points for a document."""
        if not await self._collection_present():
            return
        try:
            await self._client.delete(
                collection_name=self._collection, points_selector=self._doc_filter(doc_id)
            )
        except Exception:
            logger.debug("Qdrant delete failed for doc %d", doc_id, exc_info=True)

    def _candidate_count(self, top_n: int) -> int:
        if self._reranker is not None:
            return max(self._rerank_top_k, top_n)
        return top_n * self._overfetch_multiplier

    @staticmethod
    def _norm_score(similarity: float) -> float:
        """Qdrant returns cosine similarity in [-1,1]; map to the same [0,1]
        SearchResult.score convention Chroma uses ((cos+1)/2)."""
        return max(0.0, min(1.0, (similarity + 1.0) / 2.0))

    def _point_scores(self, points) -> list[float]:
        """Normalised [0,1] score per point. Dense: (cos+1)/2. Hybrid: RRF fused
        scores aren't similarities, so min-max normalise them across the result
        set (best→1.0); ordering is preserved either way."""
        if not self._hybrid_search:
            return [self._norm_score(p.score) for p in points]
        raw = [p.score for p in points]
        if not raw:
            return []
        lo, hi = min(raw), max(raw)
        if hi - lo < 1e-9:
            return [1.0 for _ in raw]
        return [(s - lo) / (hi - lo) for s in raw]

    async def query(self, text: str, top_n: int) -> list[SearchResult]:
        if not await self._collection_present():
            return []
        points = await self._search_points(text, self._candidate_count(top_n))
        scores = self._point_scores(points)
        candidates: list[dict[str, Any]] = []
        for p, sc in zip(points, scores):
            payload = p.payload or {}
            candidates.append({
                "document_id": payload.get("document_id", 0),
                "title": payload.get("title", ""),
                "passage": payload.get("passage", ""),
                "score": sc,
            })
        rerank_scores = await _maybe_rerank(
            self._reranker, text, [c["passage"] for c in candidates]
        )
        return _assemble_doc_results(candidates, rerank_scores, self._min_score, top_n)

    async def query_chunks(self, text: str, top_n_chunks: int) -> list[dict[str, Any]]:
        if not await self._collection_present():
            return []
        points = await self._search_points(text, top_n_chunks)
        scores = self._point_scores(points)
        candidates: list[dict[str, Any]] = []
        for p, sc in zip(points, scores):
            payload = p.payload or {}
            doc_id = payload.get("document_id", 0)
            candidates.append({
                "document_id": doc_id,
                "title": payload.get("title", ""),
                "passage": payload.get("passage", ""),
                "score": sc,
                "deeplink_url": _deeplink(doc_id),
                "chunk_index": payload.get("chunk_index", 0),
            })
        rerank_scores = await _maybe_rerank(
            self._reranker, text, [c["passage"] for c in candidates]
        )
        return _assemble_chunk_results(candidates, rerank_scores, self._min_score)

    async def query_chunks_by_vector(
        self,
        vector: list[float],
        top_n_chunks: int,
        entity_filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Vector-input chunk query for the grooming scan — no embed, no rerank
        (scan thresholds need raw cosine-derived scores).

        Always queries the dense vector even when hybrid search is enabled:
        RRF-fused scores are not similarities and would not be comparable to
        the scan thresholds. ``tag_id`` filters work here (``tag_ids`` is a
        real integer array in the payload).
        """
        if not await self._collection_present():
            return []
        from qdrant_client import models

        query_filter = None
        if entity_filter:
            conditions = []
            if "tag_id" in entity_filter:
                conditions.append(models.FieldCondition(
                    key="tag_ids", match=models.MatchValue(value=int(entity_filter["tag_id"]))
                ))
            for key in ("correspondent", "document_type"):
                if key in entity_filter:
                    conditions.append(models.FieldCondition(
                        key=key, match=models.MatchValue(value=entity_filter[key])
                    ))
            if conditions:
                query_filter = models.Filter(must=conditions)

        kwargs: dict[str, Any] = {
            "collection_name": self._collection,
            "query": vector,
            "limit": top_n_chunks,
            "query_filter": query_filter,
            "with_payload": True,
        }
        if self._hybrid_search:
            kwargs["using"] = "dense"
        res = await self._client.query_points(**kwargs)

        out: list[dict[str, Any]] = []
        for p in res.points:
            payload = p.payload or {}
            out.append({
                "document_id": payload.get("document_id", 0),
                "title": payload.get("title", ""),
                "passage": payload.get("passage", ""),
                "score": self._norm_score(p.score),
                "tags_json": payload.get("tags_json", "[]"),
                "tag_ids_json": payload.get("tag_ids_json", "[]"),
                "correspondent": payload.get("correspondent", ""),
                "document_type": payload.get("document_type", ""),
            })
        return out

    async def query_similar_metadata(
        self,
        text: str,
        top_n: int,
        exclude_tag_id: int | None = None,
    ) -> dict[str, set[str]]:
        empty = {
            "tags": set(),
            "correspondents": set(),
            "document_types": set(),
            "custom_fields": {},
        }
        if not await self._collection_present():
            return empty
        from qdrant_client import models

        # Exclude documents carrying the given tag (e.g. the inbox tag) server-side
        # so suggestions don't come from un-reviewed documents.
        query_filter = None
        if exclude_tag_id is not None:
            query_filter = models.Filter(
                must_not=[
                    models.FieldCondition(
                        key="tag_ids", match=models.MatchValue(value=exclude_tag_id)
                    )
                ]
            )
        points = await self._search_points(
            text, top_n * self._overfetch_multiplier, query_filter=query_filter
        )

        all_tags: set[str] = set()
        all_correspondents: set[str] = set()
        all_document_types: set[str] = set()
        all_custom_fields: dict[str, set[str]] = {}
        seen_doc_ids: set[int] = set()

        for p in points:
            payload = p.payload or {}
            doc_id = payload.get("document_id", 0)
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            if len(seen_doc_ids) > top_n:
                break
            try:
                tag_list = json.loads(payload.get("tags_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                tag_list = []
            for t in tag_list:
                if t:
                    all_tags.add(t)
            corr = payload.get("correspondent", "")
            if corr:
                all_correspondents.add(corr)
            dt = payload.get("document_type", "")
            if dt:
                all_document_types.add(dt)
            try:
                cf_dict = json.loads(payload.get("custom_fields_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                cf_dict = {}
            for cf_name, cf_value in cf_dict.items():
                if cf_value is not None and str(cf_value).strip():
                    all_custom_fields.setdefault(cf_name, set()).add(str(cf_value))

        return {
            "tags": all_tags,
            "correspondents": all_correspondents,
            "document_types": all_document_types,
            "custom_fields": all_custom_fields,
        }

    async def get_collection_dim(self) -> int | None:
        """Return the dense-vector dimension stored in the Qdrant collection, or None."""
        try:
            if not await self._client.collection_exists(self._collection):
                return None
            info = await self._client.get_collection(self._collection)
            vecs = info.config.params.vectors
            if self._hybrid_search and isinstance(vecs, dict):
                dense = vecs.get("dense")
                return dense.size if dense is not None else None
            return getattr(vecs, "size", None)
        except Exception:
            logger.debug("get_collection_dim failed", exc_info=True)
            return None

    async def count(self) -> int:
        if not await self._collection_present():
            return 0
        result = await self._client.count(collection_name=self._collection)
        return result.count

    async def get_indexed_chunk_counts(self) -> tuple[dict[int, int], dict[int, int]]:
        doc_chunk_counts: dict[int, int] = {}
        doc_expected_chunks: dict[int, int] = {}
        if not await self._collection_present():
            return doc_chunk_counts, doc_expected_chunks
        offset = None
        while True:
            points, offset = await self._client.scroll(
                collection_name=self._collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                doc_id = payload.get("document_id")
                if not isinstance(doc_id, int):
                    continue
                doc_chunk_counts[doc_id] = doc_chunk_counts.get(doc_id, 0) + 1
                if "total_chunks" in payload:
                    doc_expected_chunks[doc_id] = int(payload["total_chunks"])
            if offset is None:
                break
        return doc_chunk_counts, doc_expected_chunks

    async def reindex_all(self, documents: list[dict[str, Any]]) -> None:
        await self.reset()
        for doc in documents:
            await self.upsert(doc["doc_id"], doc["text"], doc.get("metadata", {}))

    async def reset(self) -> None:
        """Delete the collection; it is recreated lazily on the next upsert."""
        try:
            if await self._client.collection_exists(self._collection):
                await self._client.delete_collection(self._collection)
        except Exception:
            logger.debug("Qdrant reset: delete_collection failed.", exc_info=True)
        self._ready = False
        logger.info("Qdrant collection '%s' reset (all vectors cleared).", self._collection)

    async def dump_points(self) -> list[dict[str, Any]]:
        """Export all points (id, vector, document, metadata) for migration.

        ``id`` is the logical chunk id ("docid_chunkidx") so the destination can
        derive the same uuid5 point id; ``passage``/``chunk_id`` are split back
        out of the payload into the common shape Chroma uses.
        """
        if not await self._collection_present():
            return []
        points: list[dict[str, Any]] = []
        offset = None
        while True:
            records, offset = await self._client.scroll(
                collection_name=self._collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for r in records:
                if r.vector is None:
                    continue
                # Named-vector (hybrid) collections return a dict; migrate only
                # the dense vector (sparse is re-encoded from the passage on load).
                vec = r.vector["dense"] if isinstance(r.vector, dict) else r.vector
                payload = dict(r.payload or {})
                logical_id = payload.pop("chunk_id", None) or str(r.id)
                document = payload.pop("passage", "")
                # tag_ids is a Qdrant-only list (Chroma can't store lists);
                # tag_ids_json in the payload is the migration-safe form.
                payload.pop("tag_ids", None)
                points.append({
                    "id": logical_id,
                    "vector": [float(x) for x in vec],
                    "document": document,
                    "metadata": payload,
                })
            if offset is None:
                break
        return points

    async def load_points(self, points: list[dict[str, Any]]) -> int:
        """Bulk-insert points from dump_points() preserving ids/vectors/payload."""
        from qdrant_client import models

        if not points:
            return 0
        await self._ensure_collection(len(points[0]["vector"]))

        # For a hybrid destination, rebuild sparse vectors from the passages
        # (dump only carries dense). Batch-encode once.
        sparse_vecs: list[Any] = []
        if self._hybrid_search:
            sparse_vecs = await self._sparse_vectors([p.get("document", "") for p in points])

        structs = []
        for idx, p in enumerate(points):
            meta = dict(p.get("metadata") or {})
            # Re-derive the Qdrant-only tag_ids list from the canonical json so
            # exclude_tag_id filtering keeps working after a migration.
            try:
                tag_ids = json.loads(meta.get("tag_ids_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                tag_ids = []
            payload = {
                **meta, "tag_ids": tag_ids,
                "passage": p.get("document", ""), "chunk_id": p["id"],
            }
            vector: Any = (
                {"dense": p["vector"], "sparse": sparse_vecs[idx]}
                if self._hybrid_search else p["vector"]
            )
            structs.append(models.PointStruct(
                id=str(uuid.uuid5(_QDRANT_POINT_NAMESPACE, p["id"])),
                vector=vector,
                payload=payload,
            ))
        await self._client.upsert(collection_name=self._collection, points=structs)
        return len(structs)


class BedrockKnowledgeBaseStore:
    """Amazon Bedrock Knowledge Base vector store.

    Delegates embedding storage and retrieval to a managed Bedrock
    Knowledge Base. Uses boto3 for API calls.
    """

    def __init__(self, knowledge_base_id: str, region_name: str = "us-east-1") -> None:
        import boto3
        self._kb_id = knowledge_base_id
        self._region = region_name
        self._client = boto3.client("bedrock-agent-runtime", region_name=region_name)
        self._agent_client = boto3.client("bedrock-agent", region_name=region_name)

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        logger.warning("BedrockKnowledgeBaseStore.upsert() is a no-op; use data source sync for document %d.", doc_id)

    async def delete(self, doc_id: int) -> None:
        logger.warning("BedrockKnowledgeBaseStore.delete() is a no-op; use data source sync for document %d.", doc_id)

    async def query(self, text: str, top_n: int) -> list[SearchResult]:
        loop = asyncio.get_running_loop()
        def _retrieve() -> dict:
            return self._client.retrieve(
                knowledgeBaseId=self._kb_id,
                retrievalQuery={"text": text},
                retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": top_n}},
            )
        try:
            response = await loop.run_in_executor(None, _retrieve)
        except Exception as exc:
            logger.error("Bedrock KB query failed: %s", exc)
            raise
        results: list[SearchResult] = []
        for item in response.get("retrievalResults", []):
            content = item.get("content", {}).get("text", "")
            score = item.get("score", 0.0)
            metadata_attrs = item.get("metadata", {})
            doc_id = int(metadata_attrs.get("document_id", 0))
            location = item.get("location", {})
            uri = location.get("s3Location", {}).get("uri", "")
            results.append(SearchResult(
                document_id=doc_id, document_title=metadata_attrs.get("title", ""),
                passage=content, score=score,
                deeplink_url=_deeplink(doc_id) if doc_id else uri,
            ))
        return results[:top_n]

    async def reindex_all(self, documents: list[dict[str, Any]]) -> None:
        loop = asyncio.get_running_loop()
        def _start_sync() -> None:
            ds_response = self._agent_client.list_data_sources(knowledgeBaseId=self._kb_id)
            for ds in ds_response.get("dataSourceSummaries", []):
                ds_id = ds["dataSourceId"]
                self._agent_client.start_ingestion_job(knowledgeBaseId=self._kb_id, dataSourceId=ds_id)
                logger.info("Started Bedrock KB ingestion job for data source %s.", ds_id)
        try:
            await loop.run_in_executor(None, _start_sync)
        except Exception as exc:
            logger.error("Bedrock KB reindex failed: %s", exc)
            raise
