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

import chromadb

from backend.models import SearchResult
from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)

PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://localhost:8000")

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


class ChromaVectorStore:
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
    ) -> None:
        self._llm = llm_provider
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._chunk_strategy = chunk_strategy
        self._overfetch_multiplier = overfetch_multiplier
        self._min_score = min_score
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

    async def _embed(self, text: str) -> list[float]:
        """Embed a single chunk of text."""
        return await self._llm.embed(text)

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        """Split document into chunks, embed all in parallel, and store with metadata."""
        # First delete any existing chunks for this document
        await self.delete(doc_id)

        chunks = _chunk(text, self._chunk_size, self._chunk_overlap, self._chunk_strategy)
        if not chunks:
            return

        # Build a metadata prefix that is prepended to every chunk before embedding.
        # This means the vector captures WHO and WHAT the document is (title, type,
        # correspondent, tags, custom fields) in addition to the raw OCR content —
        # preventing a salary-slip chunk that merely mentions "Lebensversicherung"
        # from outranking an actual life-insurance document.
        prefix_parts: list[str] = []
        if metadata.get("title"):
            prefix_parts.append(f"Title: {metadata['title']}")
        if metadata.get("document_type"):
            prefix_parts.append(f"Type: {metadata['document_type']}")
        if metadata.get("correspondent"):
            prefix_parts.append(f"From: {metadata['correspondent']}")
        tags = metadata.get("tags") or []
        if isinstance(tags, list) and any(tags):
            prefix_parts.append(f"Tags: {', '.join(t for t in tags if t)}")
        for cf_name, cf_value in (metadata.get("custom_fields") or {}).items():
            if cf_value is not None and str(cf_value).strip():
                prefix_parts.append(f"{cf_name}: {cf_value}")
        embed_prefix = "\n".join(prefix_parts) + "\n\n" if prefix_parts else ""

        base_meta: dict[str, Any] = {
            "document_id": doc_id,
            "title": metadata.get("title", ""),
            "tags_json": json.dumps(metadata.get("tags", [])),
            "correspondent": metadata.get("correspondent") or "",
            "document_type": metadata.get("document_type") or "",
            "custom_fields_json": json.dumps(metadata.get("custom_fields") or {}),
        }
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

    async def query(self, text: str, top_n: int) -> list[SearchResult]:
        """Find the most relevant document chunks and group by document.

        Returns up to top_n documents, each with the best matching passage.
        """
        embedding = await self._embed(text)
        loop = asyncio.get_running_loop()
        count = self._collection.count()
        if count == 0:
            return []

        # Fetch more chunks than needed to ensure we get top_n unique documents
        n_chunks = min(top_n * self._overfetch_multiplier, count)
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

        # Group chunks by document, keeping the best (lowest distance) chunk per doc
        seen_docs: dict[int, dict[str, Any]] = {}
        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            doc_id = meta.get("document_id", 0)
            if not doc_id:
                # Try parsing from chunk_id format "docid_chunkidx"
                try:
                    doc_id = int(chunk_id.split("_")[0])
                except (ValueError, IndexError):
                    continue

            dist = distances[i] if i < len(distances) else 1.0
            passage = documents[i] if i < len(documents) else ""

            # Keep the best (lowest distance) chunk per document.
            # Process all fetched chunks — don't break early — so every unique
            # document gets its best chunk recorded before we rank and slice.
            if doc_id not in seen_docs or dist < seen_docs[doc_id]["distance"]:
                seen_docs[doc_id] = {
                    "distance": dist,
                    "passage": passage,
                    "title": meta.get("title", ""),
                }

        search_results: list[SearchResult] = []
        for doc_id, info in sorted(seen_docs.items(), key=lambda x: x[1]["distance"]):
            score = 1.0 - (info["distance"] / 2.0)
            if score < self._min_score:
                continue
            search_results.append(SearchResult(
                document_id=doc_id,
                document_title=info["title"],
                passage=info["passage"] or "",
                score=score,
                deeplink_url=_deeplink(doc_id),
            ))

        return search_results[:top_n]

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
        embedding = await self._embed(text)
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

    def count(self) -> int:
        """Return the number of chunks in the store."""
        return self._collection.count()

    @property
    def embed_concurrency(self) -> int:
        """The current embedding concurrency limit (read-only)."""
        return self._embed_concurrency

    def set_embed_provider(self, provider: LLMProvider, concurrency: int) -> None:
        """Swap the embedding provider and rebuild the semaphore if the
        concurrency limit changed (e.g. switching Ollama ↔ Bedrock)."""
        self._llm = provider
        if self._embed_concurrency != concurrency:
            self._embed_sem = asyncio.Semaphore(concurrency)
            self._embed_concurrency = concurrency

    async def embed_health_check(self) -> bool:
        """Return True if the embedding provider is reachable."""
        return await self._llm.health_check()

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
        embedding = await self._embed(text)
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

        chunks: list[dict[str, Any]] = []
        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            doc_id = meta.get("document_id", 0)
            dist = distances[i] if i < len(distances) else 1.0
            score = 1.0 - (dist / 2.0)
            if score < self._min_score:
                continue
            chunks.append({
                "document_id": doc_id,
                "title": meta.get("title", ""),
                "passage": documents[i] if i < len(documents) else "",
                "score": score,
                "deeplink_url": _deeplink(doc_id),
                "chunk_index": meta.get("chunk_index", 0),
            })

        return chunks

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
