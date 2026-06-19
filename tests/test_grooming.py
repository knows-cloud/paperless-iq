"""Grooming tests (GROOMING_PLAN §12).

Covers:
- Name normalisation + transitive clustering (property: order-independence)
- Scan classification rules — add / remove(a)(b)(c) / replace / needs-decision,
  hysteresis dead band, cohort percentile path, dismissal filtering
- Scan pipeline end-to-end over a fake VectorStore into enqueued SuggestionORM
  rows with correct evidence_json; dry-run enqueues nothing; per-scan cap
- Rejection → GroomingDismissalORM memory (and record_dismissals=False paths)
- Merge writes audit rows and deletes loser entities (Paperless mocked via
  httpx MockTransport)
- Route guards: scan unavailable on bedrock_kb; grooming routes 403 without
  can_groom when auth is enforced
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.grooming import (
    GroomingService,
    _name_similarity,
    _normalise_name,
    _transitive_clusters,
    classify_single_valued_entity,
    classify_tag_entity,
    compute_cohort_percentiles,
)
from backend.orm_models import (
    AuditLogORM,
    EntityDescriptionORM,
    GroomingDismissalORM,
    SuggestionORM,
)

# ---------------------------------------------------------------------------
# Name normalisation + clustering
# ---------------------------------------------------------------------------

def test_normalise_name_folds_case_and_diacritics() -> None:
    assert _normalise_name("  Köln ") == "koln"
    assert _normalise_name("ABC") == _normalise_name("abc")


def test_name_similarity_identical_after_normalisation() -> None:
    assert _name_similarity("Insurance", "insurance ") == 1.0
    assert _name_similarity("Insurance", "Banking") < 0.5


def test_transitive_clusters_chains_pairs() -> None:
    clusters = {frozenset(c) for c in _transitive_clusters([(1, 2), (2, 3), (5, 6)])}
    assert frozenset({1, 2, 3}) in clusters
    assert frozenset({5, 6}) in clusters


@given(
    pairs=st.lists(
        st.tuples(st.integers(min_value=1, max_value=30), st.integers(min_value=1, max_value=30)),
        max_size=40,
    ),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_property_clustering_is_order_independent(pairs: list[tuple[int, int]], seed: int) -> None:
    """# Feature: grooming, clustering order-independence (GROOMING_PLAN §12)"""
    shuffled = pairs[:]
    random.Random(seed).shuffle(shuffled)
    a = {frozenset(c) for c in _transitive_clusters(pairs)}
    b = {frozenset(c) for c in _transitive_clusters(shuffled)}
    assert a == b


# ---------------------------------------------------------------------------
# Cohort percentiles
# ---------------------------------------------------------------------------

def test_cohort_percentiles_small_cohort_disabled() -> None:
    assert compute_cohort_percentiles({1: 0.5, 2: 0.9}) == {}


def test_cohort_percentiles_bottom_is_zero_top_is_hundred() -> None:
    scores = {i: i / 10 for i in range(1, 11)}  # 10 docs
    pct = compute_cohort_percentiles(scores)
    assert pct[1] == 0.0
    assert pct[10] == 100.0
    assert 0.0 < pct[5] < 100.0


# ---------------------------------------------------------------------------
# Tag classification
# ---------------------------------------------------------------------------

_TAG_DEFAULTS = dict(
    cohort_percentiles={},
    add_threshold=0.80,
    remove_threshold=0.35,
    remove_percentile=10,
    min_supporting_chunks=2,
    top_k=100,
)


def test_tag_add_fires_above_threshold_with_enough_chunks() -> None:
    actions = classify_tag_entity(
        doc_scores={7: 0.9},
        supporting_chunks={7: 2},
        assigned_doc_ids=set(),
        **_TAG_DEFAULTS,
    )
    assert actions == [
        {"document_id": 7, "action": "add", "score": 0.9, "cohort_percentile": None,
         "distance": pytest.approx(0.1)},
    ]


def test_tag_add_requires_min_supporting_chunks() -> None:
    actions = classify_tag_entity(
        doc_scores={7: 0.9},
        supporting_chunks={7: 1},  # one lucky chunk is not enough
        assigned_doc_ids=set(),
        **_TAG_DEFAULTS,
    )
    assert actions == []


def test_tag_add_skipped_when_already_assigned() -> None:
    actions = classify_tag_entity(
        doc_scores={7: 0.9},
        supporting_chunks={7: 5},
        assigned_doc_ids={7},
        **_TAG_DEFAULTS,
    )
    assert actions == []


def test_tag_hysteresis_dead_band_produces_no_action() -> None:
    # 0.5 is between remove (0.35) and add (0.80) — assigned or not, no action.
    for assigned in (set(), {7}):
        actions = classify_tag_entity(
            doc_scores={7: 0.5},
            supporting_chunks={7: 5},
            assigned_doc_ids=assigned,
            **_TAG_DEFAULTS,
        )
        assert actions == []


def test_tag_remove_rule_a_low_score() -> None:
    actions = classify_tag_entity(
        doc_scores={7: 0.1},
        supporting_chunks={},
        assigned_doc_ids={7},
        **_TAG_DEFAULTS,
    )
    assert len(actions) == 1
    assert actions[0]["action"] == "remove"
    assert actions[0]["reason"] == "low_score"


def test_tag_remove_rule_b_absence_needs_deep_topk() -> None:
    # Doc 7 carries the tag but is absent from results.
    # top_k=100 ≥ 3×1 assigned → absence is evidence.
    actions = classify_tag_entity(
        doc_scores={},
        supporting_chunks={},
        assigned_doc_ids={7},
        **_TAG_DEFAULTS,
    )
    assert [a["action"] for a in actions] == ["remove"]
    assert actions[0]["reason"] == "absent"

    # Shallow top_k: absence is "unknown", not evidence.
    shallow = {**_TAG_DEFAULTS, "top_k": 2}
    actions = classify_tag_entity(
        doc_scores={},
        supporting_chunks={},
        assigned_doc_ids={7},
        **shallow,
    )
    assert actions == []


def test_tag_remove_rule_c_cohort_bottom_despite_ok_score() -> None:
    # Score 0.5 clears the absolute remove threshold, but the doc sits in the
    # bottom 10% of its cohort → flagged via the percentile path (D-18 mitigation).
    kwargs = {**_TAG_DEFAULTS, "cohort_percentiles": {7: 5.0}}
    actions = classify_tag_entity(
        doc_scores={7: 0.5},
        supporting_chunks={},
        assigned_doc_ids={7},
        **kwargs,
    )
    assert [a["action"] for a in actions] == ["remove"]
    assert actions[0]["reason"] == "cohort_bottom"
    assert actions[0]["cohort_percentile"] == 5.0


# ---------------------------------------------------------------------------
# Single-valued classification (correspondent / document_type)
# ---------------------------------------------------------------------------

_SV_DEFAULTS = dict(
    cohort_percentiles={},
    add_threshold=0.80,
    remove_threshold=0.35,
    remove_percentile=10,
    min_supporting_chunks=2,
    top_k=100,
)


def test_single_valued_add_only_without_incumbent() -> None:
    actions = classify_single_valued_entity(
        entity_id=1,
        doc_scores={7: 0.9},
        supporting_chunks={7: 3},
        assigned_doc_ids=set(),
        incumbent_by_doc={},
        competitor_best={},
        **_SV_DEFAULTS,
    )
    assert [a["action"] for a in actions] == ["add"]

    # Same scores, but the document already has an incumbent → no add.
    actions = classify_single_valued_entity(
        entity_id=1,
        doc_scores={7: 0.9},
        supporting_chunks={7: 3},
        assigned_doc_ids=set(),
        incumbent_by_doc={7: 2},
        competitor_best={},
        **_SV_DEFAULTS,
    )
    assert actions == []


def test_single_valued_replace_when_competitor_outranks() -> None:
    actions = classify_single_valued_entity(
        entity_id=1,
        doc_scores={7: 0.1},                 # incumbent mismatches (rule a)
        supporting_chunks={},
        assigned_doc_ids={7},
        incumbent_by_doc={7: 1},
        competitor_best={7: (2, 0.92)},       # outranks + clears add threshold
        **_SV_DEFAULTS,
    )
    assert len(actions) == 1
    a = actions[0]
    assert a["action"] == "replace"
    assert a["replacement_entity_id"] == 2
    assert a["replacement_score"] == 0.92


def test_single_valued_review_when_no_replacement_clears_bar() -> None:
    actions = classify_single_valued_entity(
        entity_id=1,
        doc_scores={7: 0.1},
        supporting_chunks={},
        assigned_doc_ids={7},
        incumbent_by_doc={7: 1},
        competitor_best={7: (2, 0.5)},        # below add threshold → review
        **_SV_DEFAULTS,
    )
    assert [a["action"] for a in actions] == ["review"]


def test_single_valued_no_action_when_incumbent_fits() -> None:
    actions = classify_single_valued_entity(
        entity_id=1,
        doc_scores={7: 0.9},                 # incumbent scores well
        supporting_chunks={7: 5},
        assigned_doc_ids={7},
        incumbent_by_doc={7: 1},
        competitor_best={7: (2, 0.95)},       # competitor better — but no mismatch
        **_SV_DEFAULTS,
    )
    assert actions == []


# ---------------------------------------------------------------------------
# Dismissal filtering
# ---------------------------------------------------------------------------

def test_is_dismissed_blocks_exact_action_and_replace_review_pair() -> None:
    dismissed = {("tag", 1, 7, "add"), ("correspondent", 2, 9, "replace")}
    assert GroomingService._is_dismissed(dismissed, {
        "entity_type": "tag", "entity_id": 1, "document_id": 7, "action": "add",
    })
    assert not GroomingService._is_dismissed(dismissed, {
        "entity_type": "tag", "entity_id": 1, "document_id": 7, "action": "remove",
    })
    # A rejected replace blocks a future review for the same (entity, doc) and
    # vice versa — both mean "keep the incumbent, stop asking".
    assert GroomingService._is_dismissed(dismissed, {
        "entity_type": "correspondent", "entity_id": 2, "document_id": 9, "action": "review",
    })


# ---------------------------------------------------------------------------
# Scan pipeline over a fake VectorStore
# ---------------------------------------------------------------------------

class FakeVectorStore:
    """query_chunks_by_vector over canned per-entity results.

    Entity vectors are encoded as ``[float(entity_id)]`` so the store can look
    up the right result set; ``entity_filter`` filters on chunk metadata the
    same way Qdrant would (Chroma's tag_id limitation is emulated via the
    ``supports_tag_filter`` flag).
    """

    def __init__(self, results_by_entity: dict[int, list[dict]], supports_tag_filter: bool = True) -> None:
        self._results = results_by_entity
        self._supports_tag_filter = supports_tag_filter

    async def query_chunks_by_vector(self, vector, top_n_chunks, entity_filter=None):
        results = list(self._results.get(int(vector[0]), []))
        if entity_filter:
            if "tag_id" in entity_filter:
                if not self._supports_tag_filter:
                    raise NotImplementedError("no tag filter")
                tid = entity_filter["tag_id"]
                results = [r for r in results if tid in json.loads(r.get("tag_ids_json", "[]"))]
            for key in ("correspondent", "document_type"):
                if key in entity_filter:
                    results = [r for r in results if r.get(key) == entity_filter[key]]
        return results[:top_n_chunks]


def _chunk(doc_id: int, score: float, *, title: str = "", tag_ids: list[int] | None = None,
           correspondent: str = "", document_type: str = "", passage: str = "p") -> dict:
    return {
        "document_id": doc_id, "title": title or f"Doc {doc_id}", "passage": passage,
        "score": score, "tags_json": "[]",
        "tag_ids_json": json.dumps(tag_ids or []),
        "correspondent": correspondent, "document_type": document_type,
    }


def _config(**overrides) -> SimpleNamespace:
    base = dict(
        grooming_scan_top_k=100,
        grooming_add_threshold=0.80,
        grooming_remove_threshold=0.35,
        grooming_remove_percentile=10,
        grooming_min_supporting_chunks=2,
        grooming_max_suggestions_per_scan=50,
        grooming_resuggest_after_days=0,
        embedding_model="test-model",
        embed_provider="ollama",
        inbox_tag_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _entity_row(entity_type: str, entity_id: int, name: str) -> EntityDescriptionORM:
    return EntityDescriptionORM(
        entity_type=entity_type, entity_id=entity_id, name_snapshot=name,
        description=f"About {name}", description_source="llm",
        embedding_json=json.dumps([float(entity_id)]), embedding_stored=True,
        embed_model="test-model", embed_dim=1,
    )


def _make_scan_service(session, vs, config) -> GroomingService:
    pc = SimpleNamespace(_base_url="http://paperless.test", _headers={})
    return GroomingService(session, pc, None, config, vector_store=vs)


@pytest.mark.asyncio
async def test_scan_pipeline_enqueues_suggestion_with_evidence(db_engine) -> None:
    """Tag-add candidate flows end-to-end into a SuggestionORM with evidence."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_entity_row("tag", 1, "Insurance"))
        await session.commit()

        vs = FakeVectorStore({1: [
            _chunk(7, 0.9, title="Policy 2024"),
            _chunk(7, 0.85),
        ]})
        svc = _make_scan_service(session, vs, _config())

        async def fake_entity_docs(filter_param, entity_id, limit):
            return []  # entity has no documents yet → doc 7 is an add candidate

        async def fake_document(doc_id):
            return {"id": doc_id, "title": "Policy 2024", "tags": [5], "correspondent": None, "document_type": None}

        async def fake_entities(etype):
            return {"tag": [{"id": 1, "name": "Insurance", "document_count": 0},
                            {"id": 5, "name": "2024", "document_count": 1}],
                    "correspondent": [], "document_type": []}[etype]

        svc._fetch_entity_docs = fake_entity_docs
        svc._fetch_document = fake_document
        svc._fetch_paperless_entities = fake_entities

        candidates, stats = await svc.collect_scan_candidates(["tag"])
        assert len(candidates) == 1
        assert candidates[0]["action"] == "add"

        summary = {"added": 0, "removed": 0, "replaced": 0, "review": 0,
                   "skipped_dismissed": 0, "skipped_pending": 0, "capped": 0}
        enqueued = await svc._enqueue_candidates(candidates, summary)
        assert enqueued == 1
        assert summary["added"] == 1

        rows = (await session.execute(select(SuggestionORM))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.analysis_mode == "grooming"
        assert row.llm_model == "test-model"
        assert row.prompt_used == ""
        # Corrected tag list = current tags + the addition
        assert sorted(row.tags) == ["2024", "Insurance"]
        evidence = json.loads(row.evidence_json)
        assert evidence["base_tags"] == ["2024"]
        assert evidence["actions"][0]["action"] == "add"
        assert evidence["actions"][0]["entity_name"] == "Insurance"
        assert evidence["actions"][0]["entity_id"] == 1


@pytest.mark.asyncio
async def test_scan_dry_run_enqueues_nothing(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_entity_row("tag", 1, "Insurance"))
        await session.commit()

        vs = FakeVectorStore({1: [_chunk(7, 0.9), _chunk(7, 0.85)]})
        svc = _make_scan_service(session, vs, _config())

        async def fake_entity_docs(filter_param, entity_id, limit):
            return []
        svc._fetch_entity_docs = fake_entity_docs

        candidates = await svc.run_scan_dry(["tag"])
        assert len(candidates) == 1
        assert candidates[0]["deeplink_url"].endswith("/documents/7/")

        rows = (await session.execute(select(SuggestionORM))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_scan_skips_dismissed_candidates(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_entity_row("tag", 1, "Insurance"))
        session.add(GroomingDismissalORM(
            entity_type="tag", entity_id=1, document_id=7, action="add",
        ))
        await session.commit()

        vs = FakeVectorStore({1: [_chunk(7, 0.9), _chunk(7, 0.85)]})
        svc = _make_scan_service(session, vs, _config())

        async def fake_entity_docs(filter_param, entity_id, limit):
            return []
        svc._fetch_entity_docs = fake_entity_docs

        candidates, stats = await svc.collect_scan_candidates(["tag"])
        assert candidates == []
        assert stats["skipped_dismissed"] == 1


@pytest.mark.asyncio
async def test_scan_skips_docs_with_pending_suggestions(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_entity_row("tag", 1, "Insurance"))
        session.add(SuggestionORM(
            id=str(uuid4()), document_id=7, status="pending",
            created_at=datetime.now(timezone.utc), tags=[],
            custom_fields={}, llm_provider="x", llm_model="y",
            analysis_mode="ocr", prompt_used="", raw_llm_response="",
        ))
        await session.commit()

        vs = FakeVectorStore({1: [_chunk(7, 0.9), _chunk(7, 0.85)]})
        svc = _make_scan_service(session, vs, _config())

        async def fake_entity_docs(filter_param, entity_id, limit):
            return []
        svc._fetch_entity_docs = fake_entity_docs

        candidates, stats = await svc.collect_scan_candidates(["tag"])
        assert candidates == []
        assert stats["skipped_pending"] == 1


@pytest.mark.asyncio
async def test_scan_cap_keeps_highest_evidence_documents(db_engine) -> None:
    """max_suggestions_per_scan caps documents, strongest |score−threshold| first."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_entity_row("tag", 1, "Insurance"))
        await session.commit()

        vs = FakeVectorStore({1: [
            _chunk(7, 0.99), _chunk(7, 0.98),   # distance 0.19
            _chunk(8, 0.85), _chunk(8, 0.84),   # distance 0.05
        ]})
        svc = _make_scan_service(session, vs, _config(grooming_max_suggestions_per_scan=1))

        async def fake_entity_docs(filter_param, entity_id, limit):
            return []

        async def fake_document(doc_id):
            return {"id": doc_id, "title": f"Doc {doc_id}", "tags": [], "correspondent": None, "document_type": None}

        async def fake_entities(etype):
            return [{"id": 1, "name": "Insurance", "document_count": 0}] if etype == "tag" else []

        svc._fetch_entity_docs = fake_entity_docs
        svc._fetch_document = fake_document
        svc._fetch_paperless_entities = fake_entities

        candidates, _stats = await svc.collect_scan_candidates(["tag"])
        assert len(candidates) == 2

        summary = {"added": 0, "removed": 0, "replaced": 0, "review": 0,
                   "skipped_dismissed": 0, "skipped_pending": 0, "capped": 0}
        enqueued = await svc._enqueue_candidates(candidates, summary)
        assert enqueued == 1
        assert summary["capped"] == 1

        rows = (await session.execute(select(SuggestionORM))).scalars().all()
        assert [r.document_id for r in rows] == [7]  # the stronger candidate won


@pytest.mark.asyncio
async def test_scan_stale_add_dropped_at_enqueue_time(db_engine) -> None:
    """A tag-add whose tag was applied between scan and enqueue is dropped."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_entity_row("tag", 1, "Insurance"))
        await session.commit()

        vs = FakeVectorStore({1: [_chunk(7, 0.9), _chunk(7, 0.85)]})
        svc = _make_scan_service(session, vs, _config())

        async def fake_entity_docs(filter_param, entity_id, limit):
            return []

        async def fake_document(doc_id):
            # The document already carries the tag now
            return {"id": doc_id, "title": "Doc", "tags": [1], "correspondent": None, "document_type": None}

        async def fake_entities(etype):
            return [{"id": 1, "name": "Insurance", "document_count": 1}] if etype == "tag" else []

        svc._fetch_entity_docs = fake_entity_docs
        svc._fetch_document = fake_document
        svc._fetch_paperless_entities = fake_entities

        candidates, _ = await svc.collect_scan_candidates(["tag"])
        summary = {"added": 0, "removed": 0, "replaced": 0, "review": 0,
                   "skipped_dismissed": 0, "skipped_pending": 0, "capped": 0}
        enqueued = await svc._enqueue_candidates(candidates, summary)
        assert enqueued == 0
        rows = (await session.execute(select(SuggestionORM))).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# Rejection → dismissal memory
# ---------------------------------------------------------------------------

def _grooming_suggestion_row(**overrides) -> SuggestionORM:
    evidence = {
        "actions": [
            {"action": "add", "entity_type": "tag", "entity_id": 1,
             "entity_name": "Insurance", "score": 0.9, "cohort_percentile": None,
             "best_passage": "p"},
        ],
        "base_tags": [],
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
    defaults = dict(
        id=str(uuid4()), document_id=7, status="pending",
        created_at=datetime.now(timezone.utc), tags=["Insurance"],
        custom_fields={}, llm_provider="ollama", llm_model="test-model",
        analysis_mode="grooming", prompt_used="", raw_llm_response="",
        evidence_json=json.dumps(evidence),
    )
    defaults.update(overrides)
    return SuggestionORM(**defaults)


@pytest.mark.asyncio
async def test_reject_grooming_suggestion_writes_dismissals(db_engine) -> None:
    from backend.approval_queue import ApprovalQueueService
    from uuid import UUID

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        row = _grooming_suggestion_row()
        session.add(row)
        await session.commit()

        svc = ApprovalQueueService(session)
        await svc.reject(UUID(row.id))

        dismissals = (await session.execute(select(GroomingDismissalORM))).scalars().all()
        assert len(dismissals) == 1
        d = dismissals[0]
        assert (d.entity_type, d.entity_id, d.document_id, d.action) == ("tag", 1, 7, "add")


@pytest.mark.asyncio
async def test_reject_without_record_dismissals_writes_none(db_engine) -> None:
    """Empty Queue / re-analyze swaps must not record permanent judgments."""
    from backend.approval_queue import ApprovalQueueService
    from uuid import UUID

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        row = _grooming_suggestion_row()
        session.add(row)
        await session.commit()

        svc = ApprovalQueueService(session)
        await svc.reject(UUID(row.id), record_dismissals=False)

        dismissals = (await session.execute(select(GroomingDismissalORM))).scalars().all()
        assert dismissals == []


@pytest.mark.asyncio
async def test_reject_non_grooming_suggestion_writes_no_dismissals(db_engine) -> None:
    from backend.approval_queue import ApprovalQueueService
    from uuid import UUID

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        row = _grooming_suggestion_row(analysis_mode="ocr", evidence_json=None)
        session.add(row)
        await session.commit()

        svc = ApprovalQueueService(session)
        await svc.reject(UUID(row.id))

        dismissals = (await session.execute(select(GroomingDismissalORM))).scalars().all()
        assert dismissals == []


# ---------------------------------------------------------------------------
# Merge — audit rows + loser deletion (Paperless mocked via httpx transport)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_merge_writes_audit_rows_and_deletes_losers(db_engine, monkeypatch) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/documents/" and request.method == "GET":
            return httpx.Response(200, json={
                "results": [{"id": 100, "title": "Doc 100"}, {"id": 101, "title": "Doc 101"}],
                "next": None,
            })
        if request.url.path == "/api/documents/bulk_edit/":
            return httpx.Response(200, json={"result": "OK"})
        if request.url.path.startswith("/api/tags/"):
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, base_url="", **kwargs)

    monkeypatch.setattr("backend.grooming.httpx.AsyncClient", patched_client)

    async with factory() as session:
        session.add(_entity_row("tag", 1, "Insurance"))
        session.add(_entity_row("tag", 2, "Insurances"))
        await session.commit()

        pc = SimpleNamespace(_base_url="http://paperless.test", _headers={})
        svc = GroomingService(session, pc, None, _config())

        result = await svc.merge_entities("tag", keep_id=1, remove_ids=[2], actor="tester")
        assert result == {"documents_updated": 2, "entities_deleted": 1}

        audits = (await session.execute(select(AuditLogORM))).scalars().all()
        assert len(audits) == 2
        assert {a.document_id for a in audits} == {100, 101}
        assert all(a.action_type == "entity_merge" for a in audits)
        assert all(a.previous_value == "Insurances" and a.new_value == "Insurance" for a in audits)

        remaining = (await session.execute(select(EntityDescriptionORM))).scalars().all()
        assert [r.entity_id for r in remaining] == [1]

        assert ("POST", "/api/documents/bulk_edit/") in calls
        assert ("DELETE", "/api/tags/2/") in calls


# ---------------------------------------------------------------------------
# Route guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_route_unavailable_on_bedrock_kb(app_client, monkeypatch) -> None:
    import backend.main as m

    monkeypatch.setattr(m._settings_svc.config, "vector_store_backend", "bedrock_kb")
    resp = await app_client.post("/api/grooming/scan", json={"entity_types": ["tag"], "dry_run": True})
    assert resp.status_code == 409
    assert "Bedrock" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scan_route_503_without_vector_store(app_client, monkeypatch) -> None:
    import backend.main as m

    monkeypatch.setattr(m._settings_svc.config, "vector_store_backend", "local")
    resp = await app_client.post("/api/grooming/scan", json={"entity_types": ["tag"], "dry_run": True})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_scan_route_validates_entity_types(app_client) -> None:
    resp = await app_client.post("/api/grooming/scan", json={"entity_types": ["bogus"], "dry_run": True})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_scan_status_route_returns_shape(app_client) -> None:
    resp = await app_client.get("/api/grooming/scan/status")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("running", "done", "total", "last_run_at", "last_summary"):
        assert key in data


_GROOMING_ROUTES = [
    ("GET", "/api/grooming/entities?entity_type=tag", None),
    ("PATCH", "/api/grooming/entities/tag/1", {"description": "x"}),
    ("POST", "/api/grooming/generate", {"entity_type": "tag", "overwrite": False}),
    ("GET", "/api/grooming/generate/status", None),
    ("POST", "/api/grooming/generate/cancel", None),
    ("GET", "/api/grooming/tag/dedup", None),
    ("POST", "/api/grooming/tag/dedup/dismiss", {"entity_id": 1, "other_entity_id": 2}),
    ("POST", "/api/grooming/tag/merge", {"keep_id": 1, "remove_ids": [2]}),
    ("POST", "/api/grooming/scan", {"entity_types": ["tag"], "dry_run": True}),
    ("GET", "/api/grooming/scan/status", None),
]


@pytest.mark.asyncio
async def test_all_grooming_routes_403_without_can_groom(app_client, db_engine, monkeypatch) -> None:
    """With auth enforced, a user lacking can_groom is rejected on every
    /api/grooming/* route (GROOMING_PLAN §12)."""
    import backend.auth as auth_mod
    import backend.main as m
    from backend.orm_models import UserPermissionsORM

    # Enforce auth (PAPERLESS_URL set) and route the middleware's direct
    # AsyncSessionLocal use to the test engine.
    monkeypatch.setenv("PAPERLESS_URL", "http://paperless.test")
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(m, "AsyncSessionLocal", factory)
    monkeypatch.setattr(m._settings_svc.config, "grooming_enabled", True)

    async with factory() as session:
        session.add(UserPermissionsORM(
            username="nogroom", ng_admin=False,
            can_access=True, can_view_queue=True, can_approve=True,
            can_analyze=True, can_discover=True, can_settings=True,
            can_groom=False,
        ))
        await session.commit()

    token = auth_mod.create_session("nogroom")
    headers = {"Authorization": f"Bearer {token}"}

    for method, url, body in _GROOMING_ROUTES:
        resp = await app_client.request(method, url, json=body, headers=headers)
        assert resp.status_code == 403, f"{method} {url} returned {resp.status_code}"
        assert "can_groom" in resp.json()["detail"] or "Grooming" in resp.json()["detail"]
