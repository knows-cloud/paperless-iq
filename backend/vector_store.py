"""Vector store implementations for Paperless IQ.

Provides ChromaVectorStore (local) and BedrockKnowledgeBaseStore (cloud)
conforming to the VectorStore Protocol.

Validates: Requirements 4.1, 4.2, 4.3, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import chromadb

from backend.models import SearchResult
from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)

PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://localhost:8000")


def _deeplink(doc_id: int) -> str:
    """Build a Paperless NGX deeplink URL for a document."""
    base = PAPERLESS_URL.rstrip("/")
    return f"{base}/documents/{doc_id}/details"


class ChromaVectorStore:
    """Local persistent vector store backed by ChromaDB.

    Uses an LLMProvider for embedding generation. ChromaDB handles
    storage and similarity search.

    Validates: Requirements 4.1, 4.3, 4.6
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        persist_directory: str = "/data/chroma",
        collection_name: str = "paperless_iq",
    ) -> None:
        self._llm = llm_provider
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        """Insert or update a document embedding with rich metadata."""
        embedding = await self._llm.embed(text)
        doc_id_str = str(doc_id)
        # Store entity metadata for smart entity selection
        stored_meta: dict[str, Any] = {
            "document_id": doc_id,
            "title": metadata.get("title", ""),
            "tags_json": json.dumps(metadata.get("tags", [])),
            "correspondent": metadata.get("correspondent") or "",
            "document_type": metadata.get("document_type") or "",
        }
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._collection.upsert(
                ids=[doc_id_str],
                embeddings=[embedding],
                documents=[text],
                metadatas=[stored_meta],
            ),
        )
        logger.info("Upserted embedding for document %d.", doc_id)

    async def query_similar_metadata(
        self,
        text: str,
        top_n: int,
        exclude_tag_id: int | None = None,
    ) -> dict[str, set[str]]:
        """Query similar documents and return their metadata entities.

        Returns a dict with keys 'tags', 'correspondents', 'document_types',
        each containing a set of entity names from the top-N similar docs.
        """
        embedding = await self._llm.embed(text)
        loop = asyncio.get_event_loop()
        count = self._collection.count()
        if count == 0:
            return {"tags": set(), "correspondents": set(), "document_types": set()}

        results = await loop.run_in_executor(
            None,
            lambda: self._collection.query(
                query_embeddings=[embedding],
                n_results=min(top_n * 2, count),  # fetch extra to allow filtering
                include=["metadatas"],
            ),
        )

        all_tags: set[str] = set()
        all_correspondents: set[str] = set()
        all_document_types: set[str] = set()

        if results["metadatas"] and results["metadatas"][0]:
            for meta in results["metadatas"][0][:top_n]:
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

        return {
            "tags": all_tags,
            "correspondents": all_correspondents,
            "document_types": all_document_types,
        }

    def count(self) -> int:
        """Return the number of documents in the store."""
        return self._collection.count()

    async def delete(self, doc_id: int) -> None:
        """Remove a document embedding by document ID."""
        doc_id_str = str(doc_id)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._collection.delete(ids=[doc_id_str]),
        )
        logger.info("Deleted embedding for document %d.", doc_id)

    async def query(self, text: str, top_n: int) -> list[SearchResult]:
        """Return the top-N most semantically similar documents."""
        embedding = await self._llm.embed(text)
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self._collection.query(
                query_embeddings=[embedding],
                n_results=min(top_n, self._collection.count()) if self._collection.count() > 0 else top_n,
                include=["documents", "metadatas", "distances"],
            ),
        )

        search_results: list[SearchResult] = []
        if not results["ids"] or not results["ids"][0]:
            return search_results

        ids = results["ids"][0]
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []

        for i, doc_id_str in enumerate(ids):
            doc_id = int(doc_id_str)
            passage = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if i < len(metadatas) else {}
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity score: 1 - (distance / 2)
            dist = distances[i] if i < len(distances) else 1.0
            score = 1.0 - (dist / 2.0)

            search_results.append(SearchResult(
                document_id=doc_id,
                document_title=meta.get("title", ""),
                passage=passage or "",
                score=score,
                deeplink_url=_deeplink(doc_id),
            ))

        return search_results

    async def reindex_all(self, documents: list[dict[str, Any]]) -> None:
        """Re-index all documents. Clears existing data first.

        Args:
            documents: List of dicts with keys: doc_id, text, metadata
        """
        # Clear existing collection
        loop = asyncio.get_event_loop()
        collection_name = self._collection.name
        await loop.run_in_executor(
            None,
            lambda: self._client.delete_collection(collection_name),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        for doc in documents:
            await self.upsert(doc["doc_id"], doc["text"], doc.get("metadata", {}))

        logger.info("Re-indexed %d documents.", len(documents))


class BedrockKnowledgeBaseStore:
    """Amazon Bedrock Knowledge Base vector store.

    Delegates embedding storage and retrieval to a managed Bedrock
    Knowledge Base. Uses boto3 for API calls.

    Validates: Requirements 4.6, 4.7
    """

    def __init__(
        self,
        knowledge_base_id: str,
        region_name: str = "us-east-1",
    ) -> None:
        import boto3

        self._kb_id = knowledge_base_id
        self._region = region_name
        self._client = boto3.client(
            "bedrock-agent-runtime",
            region_name=region_name,
        )
        self._agent_client = boto3.client(
            "bedrock-agent",
            region_name=region_name,
        )

    async def upsert(self, doc_id: int, text: str, metadata: dict) -> None:
        """Upsert is managed by Bedrock data source sync — no-op here.

        In a Bedrock Knowledge Base, documents are ingested via a data source
        sync job rather than individual upserts. This method logs a warning.
        """
        logger.warning(
            "BedrockKnowledgeBaseStore.upsert() is a no-op; "
            "use data source sync for document %d.",
            doc_id,
        )

    async def delete(self, doc_id: int) -> None:
        """Delete is managed by Bedrock data source sync — no-op here."""
        logger.warning(
            "BedrockKnowledgeBaseStore.delete() is a no-op; "
            "use data source sync for document %d.",
            doc_id,
        )

    async def query(self, text: str, top_n: int) -> list[SearchResult]:
        """Query the Bedrock Knowledge Base for relevant passages."""
        loop = asyncio.get_event_loop()

        def _retrieve() -> dict:
            return self._client.retrieve(
                knowledgeBaseId=self._kb_id,
                retrievalQuery={"text": text},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": top_n,
                    }
                },
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
            # Extract document ID from metadata if available
            location = item.get("location", {})
            uri = location.get("s3Location", {}).get("uri", "")

            # Try to extract doc_id from metadata or URI
            metadata_attrs = item.get("metadata", {})
            doc_id = int(metadata_attrs.get("document_id", 0))

            results.append(SearchResult(
                document_id=doc_id,
                document_title=metadata_attrs.get("title", ""),
                passage=content,
                score=score,
                deeplink_url=_deeplink(doc_id) if doc_id else uri,
            ))

        return results[:top_n]

    async def reindex_all(self, documents: list[dict[str, Any]]) -> None:
        """Trigger a Bedrock Knowledge Base data source sync.

        This starts an ingestion job. The actual re-indexing is async
        on the AWS side.
        """
        loop = asyncio.get_event_loop()

        def _start_sync() -> None:
            # List data sources for this KB and start sync for each
            ds_response = self._agent_client.list_data_sources(
                knowledgeBaseId=self._kb_id,
            )
            for ds in ds_response.get("dataSourceSummaries", []):
                ds_id = ds["dataSourceId"]
                self._agent_client.start_ingestion_job(
                    knowledgeBaseId=self._kb_id,
                    dataSourceId=ds_id,
                )
                logger.info(
                    "Started Bedrock KB ingestion job for data source %s.", ds_id
                )

        try:
            await loop.run_in_executor(None, _start_sync)
        except Exception as exc:
            logger.error("Bedrock KB reindex failed: %s", exc)
            raise
