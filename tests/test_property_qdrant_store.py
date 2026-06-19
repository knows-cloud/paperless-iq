"""Property/integration tests for QdrantVectorStore against an in-memory Qdrant.

Mirrors the ChromaVectorStore properties (embedding round-trip, result-count
bound, result structure, reindex completeness) so the two backends are
behaviourally comparable. Uses AsyncQdrantClient(location=":memory:") — no
server required.
"""

from __future__ import annotations

import hashlib

import pytest

from backend.models import SearchResult
from backend.vector_store import QdrantVectorStore

# Local (:memory:) Qdrant logs a benign "payload indexes have no effect" warning.
pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


# ---------------------------------------------------------------------------
# Deterministic mock embedding provider (8-dim hash embedding)
# ---------------------------------------------------------------------------


class _MockLLMProvider:
    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]

    async def health_check(self) -> bool:
        return True


def _make_store(**kwargs) -> QdrantVectorStore:
    return QdrantVectorStore(
        llm_provider=_MockLLMProvider(),
        url=":memory:",
        collection_name="paperless_iq_test",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Round-trip & lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_then_query_finds_document() -> None:
    store = _make_store()
    await store.upsert(42, "annual tax return for fiscal year", {"title": "Tax 2024"})
    results = await store.query("tax return", top_n=5)
    assert any(r.document_id == 42 for r in results)
    assert all(isinstance(r, SearchResult) for r in results)
    assert all(0.0 <= r.score <= 1.0 for r in results)


@pytest.mark.asyncio
async def test_query_empty_collection_returns_empty() -> None:
    store = _make_store()
    assert await store.query("anything", top_n=5) == []
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_count_and_chunk_counts() -> None:
    store = _make_store(chunk_size=50, chunk_overlap=10)
    long_text = " ".join(f"Invoice line {i} with amounts." for i in range(30))
    await store.upsert(7, long_text, {"title": "Invoice"})
    assert await store.count() > 0
    counts, expected = await store.get_indexed_chunk_counts()
    assert counts.get(7, 0) >= 1
    # expected total recorded from payload, and we indexed exactly that many
    assert expected.get(7) == counts.get(7)


@pytest.mark.asyncio
async def test_upsert_replaces_existing_document() -> None:
    store = _make_store()
    await store.upsert(1, "first version about cats", {"title": "v1"})
    first = await store.count()
    await store.upsert(1, "second version about cats", {"title": "v2"})
    second = await store.count()
    # replacing the same doc must not accumulate duplicate points
    assert second == first
    results = await store.query("cats", top_n=5)
    titles = {r.document_title for r in results if r.document_id == 1}
    assert titles == {"v2"}


@pytest.mark.asyncio
async def test_delete_removes_document() -> None:
    store = _make_store()
    await store.upsert(5, "document to delete about loans", {"title": "Loan"})
    assert await store.count() > 0
    await store.delete(5)
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_reindex_all_completeness() -> None:
    store = _make_store()
    docs = [
        {"doc_id": i, "text": f"Unique content for document {i}", "metadata": {"title": f"Doc {i}"}}
        for i in (1, 2, 3, 4)
    ]
    for d in docs:
        await store.upsert(d["doc_id"], d["text"], d["metadata"])
    await store.reindex_all(docs)
    for d in docs:
        results = await store.query(d["text"], top_n=len(docs))
        assert d["doc_id"] in {r.document_id for r in results}


@pytest.mark.asyncio
async def test_result_count_bounded_by_top_n() -> None:
    store = _make_store()
    for i in range(1, 8):
        await store.upsert(i, f"shared topic document variant {i}", {"title": f"Doc {i}"})
    results = await store.query("shared topic", top_n=3)
    assert len(results) <= 3


@pytest.mark.asyncio
async def test_query_similar_metadata_collects_entities() -> None:
    store = _make_store()
    await store.upsert(
        1, "insurance policy document",
        {"title": "Policy", "tags": ["insurance", "finance"],
         "correspondent": "Acme Insurance", "document_type": "Policy"},
    )
    meta = await store.query_similar_metadata("insurance", top_n=5)
    assert "insurance" in meta["tags"]
    assert "Acme Insurance" in meta["correspondents"]
    assert "Policy" in meta["document_types"]


@pytest.mark.asyncio
async def test_exclude_tag_id_filters_inbox_docs() -> None:
    """query_similar_metadata(exclude_tag_id=...) must drop docs carrying that tag."""
    store = _make_store()
    # Doc 1 carries the inbox tag (id 99); doc 2 is curated.
    await store.upsert(1, "insurance policy from acme", {
        "title": "Inbox doc", "tags": ["insurance"], "tag_ids": [99, 5],
        "correspondent": "Acme Inbox", "document_type": "Inbox Type",
    })
    await store.upsert(2, "insurance policy from acme curated", {
        "title": "Curated doc", "tags": ["insurance"], "tag_ids": [5],
        "correspondent": "Acme Curated", "document_type": "Policy",
    })

    # Without exclusion both contribute.
    meta_all = await store.query_similar_metadata("insurance", top_n=5)
    assert "Acme Inbox" in meta_all["correspondents"]

    # Excluding tag 99 drops doc 1's entities.
    meta_excl = await store.query_similar_metadata("insurance", top_n=5, exclude_tag_id=99)
    assert "Acme Inbox" not in meta_excl["correspondents"]
    assert "Acme Curated" in meta_excl["correspondents"]


@pytest.mark.asyncio
async def test_exclude_tag_id_survives_migration() -> None:
    """tag_ids is reconstructed from tag_ids_json on load, so exclusion still works."""
    from backend.vector_migrate import migrate_embeddings

    src = _make_store()
    await src.upsert(1, "inbox doc about loans", {
        "title": "I", "tag_ids": [99], "correspondent": "Inbox Bank"})
    await src.upsert(2, "curated doc about loans", {
        "title": "C", "tag_ids": [5], "correspondent": "Curated Bank"})

    dst = QdrantVectorStore(_MockLLMProvider(), url=":memory:", collection_name="excl_dst")
    result = await migrate_embeddings(src, dst)
    assert result.migrated > 0

    # tag_ids was dropped on dump and re-derived from tag_ids_json on load —
    # so the must_not filter still excludes doc 1 after migrating.
    meta = await dst.query_similar_metadata("loans", top_n=5, exclude_tag_id=99)
    assert "Inbox Bank" not in meta["correspondents"]
    assert "Curated Bank" in meta["correspondents"]


@pytest.mark.asyncio
async def test_score_convention_matches_identity_high() -> None:
    """An exact match should score 1.0 under the (cos+1)/2 map.

    Empty metadata → no embed prefix, so the stored chunk text equals the query
    and the (deterministic) embedding is identical → cosine 1.0.
    """
    store = _make_store()
    await store.upsert(9, "exactly this passage", {})
    results = await store.query("exactly this passage", top_n=1)
    assert results
    assert results[0].score == pytest.approx(1.0)
