"""Library grooming service — dedup, descriptions, entity embedding, scan.

This module implements Steps 1–5 of the grooming rollout:
  1. Entity sync from Paperless (list_entities / sync_entities)
  2. Description CRUD + LLM generation (single + bulk)
  3. Entity embedding  (embed_entity)
  4. Dedup candidates  (get_dedup_candidates / merge_entities)
  5. Mismatch scan     (run_scan / collect_scan_candidates) — zero LLM,
     zero embed: entity vectors query document chunks, classification with
     hysteresis, dismissal memory, capped enqueue into the approval queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.orm_models import (
    AuditLogORM,
    DocumentTrackingORM,
    EntityDescriptionORM,
    GroomingDismissalORM,
)

logger = logging.getLogger(__name__)

# ── Module-level state for background generation task ──────────────────────

_generate_lock = asyncio.Lock()

_generate_status: dict[str, Any] = {
    "running": False,
    "done": 0,
    "total": 0,
    "current_entity": "",
    "cancelled": False,
}

# ── Module-level state for background scan task ────────────────────────────

_scan_lock = asyncio.Lock()

_scan_status: dict[str, Any] = {
    "running": False,
    "done": 0,
    "total": 0,
    "current_entity": "",
    "last_run_at": None,
    "last_summary": None,
}

# Cohort-percentile remove rule needs enough documents to make a "bottom N%"
# meaningful — tiny cohorts would always flag their weakest member.
_MIN_COHORT_FOR_PERCENTILE = 10

# Best-passage excerpt length stored in evidence_json (queue card truncates
# to 150 chars for display and expands to this).
_EVIDENCE_PASSAGE_CHARS = 300

_GROOMING_DESC_PROMPT = """\
You are documenting the metadata vocabulary of a document archive.
Write a 2-4 sentence description of what the {entity_type} "{name}" means \
in this archive, based on the documents that use it. State what content \
belongs under it and, if helpful, what does not. Do not list document titles.
{language_instruction}

"{name}" is used by {count} documents. Sample titles:
{bulleted_titles}

{optional_excerpts_block}

Return only the description text, no preamble, no quotes.\
"""


# ── Helpers ────────────────────────────────────────────────────────────────

def _normalise_name(name: str) -> str:
    """Casefold, strip, and fold diacritics for dedup name comparison."""
    nfkd = unicodedata.normalize("NFKD", name.strip().casefold())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalise_name(a), _normalise_name(b)).ratio()


def _as_utc(dt: "datetime | None") -> "datetime | None":
    """Treat naive timestamps as UTC for safe comparison."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _entity_needs_rescan(
    row: "EntityDescriptionORM", latest_doc_embed: "datetime | None" = None,
) -> bool:
    """For incremental (scheduled) scans: True when the entity is new (never
    scanned), its description changed since the last scan, or any document was
    re-embedded since the last scan (its content drifted, so the entity↔document
    similarity scores may now differ). Naive timestamps are treated as UTC.

    ``latest_doc_embed`` is the most recent ``last_embedded_at`` across the whole
    corpus — a single global watermark, since each entity is queried against the
    entire document set, so any re-embed can change its outcome.
    """
    if row.last_scanned_at is None:
        return True
    last = _as_utc(row.last_scanned_at)
    updated = _as_utc(row.description_updated_at)
    if updated is not None and updated > last:
        return True  # description edited since last scan
    embed = _as_utc(latest_doc_embed)
    if embed is not None and embed > last:
        return True  # a document was re-embedded since last scan
    return False


def _cosine(v1: list[float], v2: list[float]) -> float:
    dot = sum(x * y for x, y in zip(v1, v2))
    n1 = sum(x * x for x in v1) ** 0.5
    n2 = sum(x * x for x in v2) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def _transitive_clusters(pairs: list[tuple[int, int]]) -> list[list[int]]:
    """Group entity IDs into clusters by transitive closure of similarity pairs."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        # Path halving: point each visited node at its grandparent. The
        # fallback for a missing grandparent must be the parent itself —
        # defaulting to x would sever the link and split the cluster.
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    all_ids: set[int] = set()
    for a, b in pairs:
        all_ids.update([a, b])
        union(a, b)

    clusters: dict[int, list[int]] = {}
    for eid in sorted(all_ids):
        root = find(eid)
        clusters.setdefault(root, []).append(eid)
    return list(clusters.values())


# ── Scan classification (pure functions — unit-tested over fixture scores) ──

def compute_cohort_percentiles(cohort_scores: dict[int, float]) -> dict[int, float]:
    """Percentile rank (0–100, 0 = weakest) per document within its cohort.

    Documents missing from the filtered query are scored 0.0 by the caller, so
    they land at the bottom. Returns {} for cohorts too small for the bottom-N%
    rule to be meaningful.
    """
    n = len(cohort_scores)
    if n < _MIN_COHORT_FOR_PERCENTILE:
        return {}
    ordered = sorted(cohort_scores.items(), key=lambda kv: kv[1])
    return {
        doc_id: 100.0 * i / (n - 1)
        for i, (doc_id, _) in enumerate(ordered)
    }


def classify_tag_entity(
    *,
    doc_scores: dict[int, float],
    supporting_chunks: dict[int, int],
    assigned_doc_ids: set[int],
    cohort_percentiles: dict[int, float],
    add_threshold: float,
    remove_threshold: float,
    remove_percentile: int,
    min_supporting_chunks: int,
    top_k: int,
) -> list[dict]:
    """Classify add/remove candidates for one tag entity (GROOMING_PLAN §5).

    ``doc_scores`` is the best chunk score per document from the unfiltered
    entity-vector query; ``cohort_percentiles`` comes from the filtered cohort
    query ({} when the backend can't filter or the cohort is too small).
    Hysteresis is implicit: scores in the dead band between ``remove_threshold``
    and ``add_threshold`` produce no action.
    """
    actions: list[dict] = []

    for doc_id, score in doc_scores.items():
        if doc_id in assigned_doc_ids:
            continue
        if score >= add_threshold and supporting_chunks.get(doc_id, 0) >= min_supporting_chunks:
            actions.append({
                "document_id": doc_id, "action": "add", "score": round(score, 4),
                "cohort_percentile": None, "distance": score - add_threshold,
            })

    # Absence from the top-k is only evidence when the query was deep enough
    # to have plausibly covered the entity's whole document set.
    absence_is_evidence = top_k >= 3 * max(len(assigned_doc_ids), 1)
    for doc_id in sorted(assigned_doc_ids):
        score = doc_scores.get(doc_id)
        pct = cohort_percentiles.get(doc_id)
        reason = None
        if score is not None and score < remove_threshold:
            reason = "low_score"
        elif score is None and absence_is_evidence:
            reason = "absent"
            score = 0.0
        elif pct is not None and pct <= remove_percentile:
            reason = "cohort_bottom"
            score = score if score is not None else 0.0
        if reason:
            actions.append({
                "document_id": doc_id, "action": "remove", "score": round(score or 0.0, 4),
                "cohort_percentile": round(pct, 1) if pct is not None else None,
                "distance": remove_threshold - (score or 0.0), "reason": reason,
            })
    return actions


def classify_single_valued_entity(
    *,
    entity_id: int,
    doc_scores: dict[int, float],
    supporting_chunks: dict[int, int],
    assigned_doc_ids: set[int],
    incumbent_by_doc: dict[int, int | None],
    competitor_best: dict[int, tuple[int, float]],
    cohort_percentiles: dict[int, float],
    add_threshold: float,
    remove_threshold: float,
    remove_percentile: int,
    min_supporting_chunks: int,
    top_k: int,
) -> list[dict]:
    """Classify add/replace/review candidates for one correspondent or
    document_type entity (GROOMING_PLAN §5).

    Single-valued fields never get a bare remove: a mismatching incumbent is
    either replaced (a competitor clears ``add_threshold`` AND outscores the
    incumbent) or flagged ``review`` (needs decision).
    ``incumbent_by_doc`` maps document → currently assigned entity id of this
    type (None = unset); ``competitor_best`` maps document → (other_entity_id,
    score) for the best-scoring *other* entity of the same type.
    """
    actions: list[dict] = []

    # add — only for documents with no incumbent at all
    for doc_id, score in doc_scores.items():
        if doc_id in assigned_doc_ids:
            continue
        if incumbent_by_doc.get(doc_id) is not None:
            continue
        if score >= add_threshold and supporting_chunks.get(doc_id, 0) >= min_supporting_chunks:
            actions.append({
                "document_id": doc_id, "action": "add", "score": round(score, 4),
                "cohort_percentile": None, "distance": score - add_threshold,
            })

    # replace / review — mismatch rules (a)/(b)/(c) on the incumbent
    absence_is_evidence = top_k >= 3 * max(len(assigned_doc_ids), 1)
    for doc_id in sorted(assigned_doc_ids):
        score = doc_scores.get(doc_id)
        pct = cohort_percentiles.get(doc_id)
        mismatch = None
        if score is not None and score < remove_threshold:
            mismatch = "low_score"
        elif score is None and absence_is_evidence:
            mismatch = "absent"
            score = 0.0
        elif pct is not None and pct <= remove_percentile:
            mismatch = "cohort_bottom"
            score = score if score is not None else 0.0
        if not mismatch:
            continue

        incumbent_score = score or 0.0
        competitor = competitor_best.get(doc_id)
        if competitor is not None and competitor[1] >= add_threshold and competitor[1] > incumbent_score:
            actions.append({
                "document_id": doc_id, "action": "replace",
                "score": round(incumbent_score, 4),
                "cohort_percentile": round(pct, 1) if pct is not None else None,
                "distance": competitor[1] - incumbent_score,
                "reason": mismatch,
                "replacement_entity_id": competitor[0],
                "replacement_score": round(competitor[1], 4),
            })
        else:
            actions.append({
                "document_id": doc_id, "action": "review",
                "score": round(incumbent_score, 4),
                "cohort_percentile": round(pct, 1) if pct is not None else None,
                "distance": remove_threshold - incumbent_score,
                "reason": mismatch,
            })
    return actions


# ── GroomingService ────────────────────────────────────────────────────────

class GroomingService:
    """Orchestrates all library-grooming operations."""

    def __init__(
        self,
        session: AsyncSession,
        paperless_client: Any | None,
        providers: dict | None,
        config: Any,
        vector_store: Any | None = None,
    ) -> None:
        self._db = session
        self._pc = paperless_client
        self._providers = providers
        self._config = config
        self._vs = vector_store

    # ── Entity sync ────────────────────────────────────────────────────────

    async def _fetch_paperless_entities(self, entity_type: str) -> list[dict]:
        """Fetch all entities of a type from Paperless (paginated)."""
        etype_plural = {"tag": "tags", "correspondent": "correspondents", "document_type": "document_types"}[entity_type]
        base_url = self._pc._base_url
        headers = self._pc._headers

        entities: list[dict] = []
        url: str | None = f"{base_url}/api/{etype_plural}/?page_size=200"
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            while url:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
                for item in data.get("results", []):
                    entities.append({"id": item["id"], "name": item["name"], "document_count": item.get("document_count", 0)})
                url = data.get("next")
        return entities

    async def sync_and_list_entities(self, entity_type: str) -> list[dict]:
        """Fetch entities from Paperless, sync to DB, return enriched list.

        ``entity_type`` is one of ``"tag"``, ``"correspondent"``, ``"document_type"``.
        """
        if self._pc is None:
            raise RuntimeError("Paperless NGX client not available")

        entities = await self._fetch_paperless_entities(entity_type)

        # Sync to DB: upsert rows, prune deleted ones
        existing_ids = {item["id"] for item in entities}
        result = await self._db.execute(
            select(EntityDescriptionORM).where(EntityDescriptionORM.entity_type == entity_type)
        )
        rows: dict[int, EntityDescriptionORM] = {r.entity_id: r for r in result.scalars().all()}

        for item in entities:
            eid = item["id"]
            name = item["name"]
            if eid in rows:
                row = rows[eid]
                if row.name_snapshot != name:
                    row.name_snapshot = name
                    row.embedding_stored = False  # re-embed on name change
            else:
                row = EntityDescriptionORM(
                    entity_type=entity_type,
                    entity_id=eid,
                    name_snapshot=name,
                )
                self._db.add(row)
                rows[eid] = row

        # Prune entities deleted from Paperless
        for stale_id in set(rows) - existing_ids:
            await self._db.delete(rows[stale_id])

        await self._db.commit()

        # Force-exclude inbox tag
        inbox_tag_id = getattr(self._config, "inbox_tag_id", None)

        result2 = await self._db.execute(
            select(EntityDescriptionORM).where(EntityDescriptionORM.entity_type == entity_type)
        )
        row_map: dict[int, EntityDescriptionORM] = {r.entity_id: r for r in result2.scalars().all()}

        entity_map = {item["id"]: item for item in entities}
        out = []
        for eid, row in sorted(row_map.items()):
            info = entity_map.get(eid, {})
            is_forced_excluded = (entity_type == "tag" and eid == inbox_tag_id)
            out.append({
                "entity_type": entity_type,
                "entity_id": eid,
                "name": row.name_snapshot,
                "doc_count": info.get("document_count", 0),
                "description": row.description,
                "description_source": row.description_source,
                "excluded": row.excluded or is_forced_excluded,
                "forced_excluded": is_forced_excluded,
                "embedding_stored": row.embedding_stored,
                "description_updated_at": row.description_updated_at.isoformat() if row.description_updated_at else None,
            })
        return out

    async def update_entity(self, entity_type: str, entity_id: int, description: str | None, excluded: bool | None) -> dict:
        """PATCH an entity description row; re-embeds immediately on description change."""
        row = await self._db.get(EntityDescriptionORM, (entity_type, entity_id))
        if row is None:
            raise ValueError(f"Entity {entity_type}:{entity_id} not found")

        now = datetime.now(timezone.utc)
        changed = False
        if description is not None and description != row.description:
            row.description = description.strip() or None
            row.description_source = "user"
            row.embedding_stored = False
            row.description_updated_at = now
            changed = True
        if excluded is not None and excluded != row.excluded:
            row.excluded = excluded
            changed = True

        if changed:
            await self._db.commit()

        # Re-embed immediately after a description change
        if changed and row.description and not row.embedding_stored:
            await self._embed_entity_row(row)
            await self._db.commit()

        return {
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "name": row.name_snapshot,
            "description": row.description,
            "description_source": row.description_source,
            "excluded": row.excluded,
            "embedding_stored": row.embedding_stored,
            "description_updated_at": row.description_updated_at.isoformat() if row.description_updated_at else None,
        }

    # ── Description generation ─────────────────────────────────────────────

    async def generate_description_for(self, entity_type: str, entity_id: int) -> str:
        """Generate and persist a description for a single entity. Returns the text."""
        if self._pc is None:
            raise RuntimeError("Paperless NGX client not available")
        row = await self._db.get(EntityDescriptionORM, (entity_type, entity_id))
        if row is None:
            raise ValueError(f"Entity {entity_type}:{entity_id} not found")
        text = await self._generate_one(row)
        return text

    async def _generate_one(self, row: EntityDescriptionORM) -> str:
        """Generate a description for one entity, persist it, trigger embed."""
        provider = self._get_llm_provider()
        if provider is None:
            raise RuntimeError("LLM provider not available")
        if self._pc is None:
            raise RuntimeError("Paperless NGX client not available")

        sample_count = getattr(self._config, "grooming_desc_sample_docs", 5)
        snippet_chars = getattr(self._config, "grooming_desc_snippet_chars", 300)

        # Fetch documents using this entity
        filter_param = {"tag": "tags__id", "correspondent": "correspondent__id", "document_type": "document_type__id"}[row.entity_type]
        docs = await self._fetch_entity_docs(filter_param, row.entity_id, limit=sample_count)

        bulleted_titles = "\n".join(f"- {d['title']}" for d in docs[:sample_count]) or "(no documents)"
        doc_count = len(docs)

        excerpts = []
        for d in docs[:2]:
            if snippet_chars > 0:
                try:
                    content = await self._pc.get_document_ocr_text(d["id"])
                    if content:
                        excerpts.append(f'Excerpt from "{d["title"]}": {content[:snippet_chars]}')
                except Exception:
                    pass

        optional_excerpts_block = "\n\n".join(excerpts) if excerpts else ""

        target_lang = getattr(self._config, "target_language", None)
        language_instruction = (
            f"Write the description in {target_lang}." if target_lang else ""
        )

        prompt = _GROOMING_DESC_PROMPT.format(
            entity_type=row.entity_type,
            name=row.name_snapshot,
            count=doc_count,
            bulleted_titles=bulleted_titles,
            optional_excerpts_block=optional_excerpts_block,
            language_instruction=language_instruction,
        )

        description = await provider.complete(prompt, max_tokens=200)
        description = description.strip().strip('"').strip()

        now = datetime.now(timezone.utc)
        row.description = description
        row.description_source = "llm"
        row.embedding_stored = False
        row.description_updated_at = now
        await self._db.commit()

        await self._embed_entity_row(row)
        await self._db.commit()

        return description

    async def _fetch_entity_docs(self, filter_param: str, entity_id: int, limit: int) -> list[dict]:
        """Fetch up to `limit` documents from Paperless for a given entity filter."""
        if self._pc is None:
            return []
        base_url = self._pc._base_url
        headers = self._pc._headers
        docs = []
        url: str | None = f"{base_url}/api/documents/?{filter_param}={entity_id}&page_size={limit}&ordering=-created"
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            while url and len(docs) < limit:
                r = await client.get(url)
                if r.status_code != 200:
                    break
                data = r.json()
                for item in data.get("results", []):
                    docs.append({"id": item["id"], "title": item.get("title", "")})
                    if len(docs) >= limit:
                        break
                url = data.get("next") if len(docs) < limit else None
        return docs[:limit]

    # ── Bulk generation ────────────────────────────────────────────────────

    async def start_bulk_generate(self, entity_type: str | None, overwrite: bool) -> None:
        """Start background bulk generation task (409 if already running)."""
        if _generate_lock.locked():
            raise RuntimeError("generation_running")
        asyncio.create_task(self._bulk_generate_bg(entity_type, overwrite))

    async def _bulk_generate_bg(self, entity_type: str | None, overwrite: bool) -> None:
        global _generate_status
        async with _generate_lock:
            from backend.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                svc = GroomingService(db, self._pc, self._providers, self._config)
                q = select(EntityDescriptionORM)
                if entity_type:
                    q = q.where(EntityDescriptionORM.entity_type == entity_type)
                result = await db.execute(q)
                rows = result.scalars().all()

                to_process = [
                    r for r in rows
                    if overwrite or not r.description
                ]
                _generate_status = {
                    "running": True, "done": 0, "total": len(to_process),
                    "current_entity": "", "cancelled": False,
                }

                for row in to_process:
                    if _generate_status["cancelled"]:
                        break
                    _generate_status["current_entity"] = f"{row.entity_type}:{row.name_snapshot}"
                    try:
                        await svc._generate_one(row)
                    except Exception:
                        logger.warning("Bulk generate failed for %s:%d", row.entity_type, row.entity_id, exc_info=True)
                    _generate_status["done"] += 1

                _generate_status["running"] = False

    def cancel_bulk_generate(self) -> None:
        _generate_status["cancelled"] = True

    @staticmethod
    def get_generate_status() -> dict:
        return dict(_generate_status)

    async def count_pending_generate(self, entity_type: str | None, overwrite: bool) -> int:
        """Count how many entities would be generated in a bulk run."""
        q = select(EntityDescriptionORM)
        if entity_type:
            q = q.where(EntityDescriptionORM.entity_type == entity_type)
        result = await self._db.execute(q)
        rows = result.scalars().all()
        return sum(1 for r in rows if overwrite or not r.description)

    # ── Entity embedding ───────────────────────────────────────────────────

    async def _embed_entity_row(self, row: EntityDescriptionORM) -> None:
        """Embed name + description for one entity row (in-place, no commit)."""
        embed_provider = self._get_embed_provider()
        if embed_provider is None:
            return
        embed_text = f"{row.entity_type}: {row.name_snapshot}"
        if row.description:
            embed_text += f"\n{row.description}"
        if len(embed_text) > 2000:
            embed_text = embed_text[:2000]
        try:
            vector = await embed_provider.embed(embed_text)
            row.embedding_json = json.dumps(vector)
            row.embedding_stored = True
            row.embed_model = getattr(self._config, "embedding_model", "")
            row.embed_dim = len(vector)
        except Exception:
            logger.warning("Entity embed failed for %s:%d", row.entity_type, row.entity_id, exc_info=True)

    # ── Deduplication ──────────────────────────────────────────────────────

    async def get_dedup_candidates(self, entity_type: str) -> list[dict]:
        """Return duplicate clusters for the given entity type.

        Each cluster is ``{entities: [...], signal: "name"|"embedding", similarity: float}``.
        Pairs dismissed by the user are excluded.
        """
        result = await self._db.execute(
            select(EntityDescriptionORM).where(EntityDescriptionORM.entity_type == entity_type)
        )
        rows: list[EntityDescriptionORM] = result.scalars().all()

        dismissals = await self._db.execute(
            select(GroomingDismissalORM).where(
                GroomingDismissalORM.entity_type == entity_type,
                GroomingDismissalORM.action == "dedup",
            )
        )
        dismissed_pairs: set[frozenset] = {
            frozenset([d.entity_id, d.other_entity_id])
            for d in dismissals.scalars().all()
            if d.other_entity_id is not None
        }

        name_threshold = getattr(self._config, "grooming_dedup_name_threshold", 0.85)
        embed_threshold = getattr(self._config, "grooming_dedup_embed_threshold", 0.90)

        # Collect similar pairs
        pairs: list[tuple[int, int, str, float]] = []  # (id_a, id_b, signal, score)
        n = len(rows)
        for i in range(n):
            for j in range(i + 1, n):
                ra, rb = rows[i], rows[j]
                pair_key = frozenset([ra.entity_id, rb.entity_id])
                if pair_key in dismissed_pairs:
                    continue

                name_sim = _name_similarity(ra.name_snapshot, rb.name_snapshot)
                if name_sim >= name_threshold:
                    pairs.append((ra.entity_id, rb.entity_id, "name", round(name_sim, 3)))
                    continue  # name match is sufficient; skip embed check

                if ra.embedding_stored and rb.embedding_stored and ra.embedding_json and rb.embedding_json:
                    v1 = json.loads(ra.embedding_json)
                    v2 = json.loads(rb.embedding_json)
                    sim = _cosine(v1, v2)
                    if sim >= embed_threshold:
                        pairs.append((ra.entity_id, rb.entity_id, "embedding", round(sim, 3)))

        # Build clusters
        id_pairs = [(a, b) for a, b, _, _ in pairs]
        clusters = _transitive_clusters(id_pairs)

        # Map signal/score for the best pair per cluster
        best: dict[frozenset, tuple[str, float]] = {}
        for a, b, signal, score in pairs:
            k = frozenset([a, b])
            if k not in best or score > best[k][1]:
                best[k] = (signal, score)

        row_map = {r.entity_id: r for r in rows}
        out = []
        for cluster_ids in clusters:
            if len(cluster_ids) < 2:
                continue
            # Determine cluster-level signal (prefer embedding if any pair used it)
            signals_in_cluster = [best.get(frozenset([a, b]), ("name", 0.0)) for a in cluster_ids for b in cluster_ids if a < b]
            dominant_signal = "embedding" if any(s == "embedding" for s, _ in signals_in_cluster) else "name"
            best_score = max((sc for _, sc in signals_in_cluster), default=0.0)

            entities = []
            for eid in sorted(cluster_ids, key=lambda x: -(row_map[x].embedding_stored if x in row_map else 0)):
                r = row_map.get(eid)
                if r:
                    entities.append({
                        "entity_id": eid,
                        "name": r.name_snapshot,
                        "has_description": bool(r.description),
                        "embedding_stored": r.embedding_stored,
                    })
            # Sort entities by having most information (has_description + embedding)
            entities.sort(key=lambda e: -(int(e["has_description"]) + int(e["embedding_stored"])))
            out.append({
                "entities": entities,
                "signal": dominant_signal,
                "similarity": best_score,
            })
        return out

    async def dismiss_dedup_pair(self, entity_type: str, entity_id: int, other_entity_id: int) -> None:
        """Record a permanent dismissal for a dedup pair."""
        d = GroomingDismissalORM(
            entity_type=entity_type,
            entity_id=entity_id,
            document_id=0,
            action="dedup",
            other_entity_id=other_entity_id,
        )
        self._db.add(d)
        # Symmetric dismissal so neither direction re-surfaces
        d2 = GroomingDismissalORM(
            entity_type=entity_type,
            entity_id=other_entity_id,
            document_id=0,
            action="dedup",
            other_entity_id=entity_id,
        )
        self._db.add(d2)
        await self._db.commit()

    async def merge_entities(
        self,
        entity_type: str,
        keep_id: int,
        remove_ids: list[int],
        actor: str,
    ) -> dict:
        """Merge remove_ids into keep_id in Paperless, delete losers, audit.

        Returns ``{"documents_updated": N, "entities_deleted": M}``.
        """
        if self._pc is None:
            raise RuntimeError("Paperless NGX client not available")

        etype_plural = {"tag": "tags", "correspondent": "correspondents", "document_type": "document_types"}[entity_type]
        base_url = self._pc._base_url
        headers = self._pc._headers

        docs_updated = 0
        entities_deleted = 0

        keep_row = await self._db.get(EntityDescriptionORM, (entity_type, keep_id))
        keep_name = keep_row.name_snapshot if keep_row else str(keep_id)

        for remove_id in remove_ids:
            remove_row = await self._db.get(EntityDescriptionORM, (entity_type, remove_id))
            remove_name = remove_row.name_snapshot if remove_row else str(remove_id)

            # 1. Find affected documents
            filter_param = {
                "tag": "tags__id",
                "correspondent": "correspondent__id",
                "document_type": "document_type__id",
            }[entity_type]
            affected = await self._fetch_entity_docs(filter_param, remove_id, limit=10_000)
            affected_ids = [d["id"] for d in affected]

            if affected_ids:
                # 2. Reassign via bulk edit
                if entity_type == "tag":
                    payload = {
                        "documents": affected_ids,
                        "method": "modify_tags",
                        "parameters": {"add_tags": [keep_id], "remove_tags": [remove_id]},
                    }
                else:
                    method = "set_correspondent" if entity_type == "correspondent" else "set_document_type"
                    payload = {
                        "documents": affected_ids,
                        "method": method,
                        "parameters": {"correspondent" if entity_type == "correspondent" else "document_type": keep_id},
                    }
                async with httpx.AsyncClient(headers=headers, timeout=60) as client:
                    r = await client.post(f"{base_url}/api/documents/bulk_edit/", json=payload)
                    r.raise_for_status()

                # 3. Audit one row per affected document
                now = datetime.now(timezone.utc)
                for doc_id in affected_ids:
                    doc_info = next((d for d in affected if d["id"] == doc_id), {})
                    audit = AuditLogORM(
                        document_id=doc_id,
                        document_title=doc_info.get("title"),
                        field_name=entity_type,
                        previous_value=remove_name,
                        new_value=keep_name,
                        change_source=f"user:{actor}",
                        action_type="entity_merge",
                        changed_at=now,
                    )
                    self._db.add(audit)
                docs_updated += len(affected_ids)

            # 4. Delete the entity from Paperless
            async with httpx.AsyncClient(headers=headers, timeout=30) as client:
                r = await client.delete(f"{base_url}/api/{etype_plural}/{remove_id}/")
                if r.status_code not in (200, 204):
                    logger.warning("Could not delete %s %d: HTTP %d", entity_type, remove_id, r.status_code)

            # 5. Remove DB row for the removed entity
            if remove_row:
                await self._db.delete(remove_row)
            entities_deleted += 1

        await self._db.commit()
        return {"documents_updated": docs_updated, "entities_deleted": entities_deleted}

    # ── Mismatch scan (Step 5) ─────────────────────────────────────────────

    async def _fetch_document(self, doc_id: int) -> dict | None:
        """Fetch one document's current metadata from Paperless (None on 404)."""
        if self._pc is None:
            return None
        base_url = self._pc._base_url
        headers = self._pc._headers
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            r = await client.get(f"{base_url}/api/documents/{doc_id}/")
            if r.status_code != 200:
                return None
            return r.json()

    async def _load_dismissed_keys(self, entity_types: list[str]) -> set[tuple]:
        """(entity_type, entity_id, document_id, action) keys still in force.

        A dismissal expires after ``grooming_resuggest_after_days`` (0 = never).
        """
        from datetime import timedelta

        resuggest_days = getattr(self._config, "grooming_resuggest_after_days", 0)
        q = select(GroomingDismissalORM).where(
            GroomingDismissalORM.entity_type.in_(entity_types),
            GroomingDismissalORM.action != "dedup",
        )
        result = await self._db.execute(q)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=resuggest_days)
            if resuggest_days > 0 else None
        )
        keys: set[tuple] = set()
        for d in result.scalars().all():
            if cutoff is not None:
                dismissed_at = d.dismissed_at
                if dismissed_at is not None and dismissed_at.tzinfo is None:
                    dismissed_at = dismissed_at.replace(tzinfo=timezone.utc)
                if dismissed_at is not None and dismissed_at < cutoff:
                    continue  # expired — may re-suggest
            keys.add((d.entity_type, d.entity_id, d.document_id, d.action))
        return keys

    @staticmethod
    def _is_dismissed(dismissed: set[tuple], c: dict) -> bool:
        """True when a candidate is blocked by dismissal memory. A rejected
        replace blocks future review for the same (entity, document) and vice
        versa — both express "keep the incumbent, stop asking"."""
        key_actions = (
            ("replace", "review") if c["action"] in ("replace", "review")
            else (c["action"],)
        )
        return any(
            (c["entity_type"], c["entity_id"], c["document_id"], a) in dismissed
            for a in key_actions
        )

    async def collect_scan_candidates(
        self, entity_types: list[str], incremental: bool = False,
    ) -> tuple[list[dict], dict]:
        """Run the entity-vector queries and classification for all included
        entities — shared by dry-run and the real scan. No enqueueing here.

        With ``incremental=True`` (scheduled scans), only entities that are new
        (never scanned) or whose description changed since their last scan are
        examined — manual scans pass False and cover everything.

        Returns ``(candidates, stats)`` where each candidate carries
        entity_type/entity_id/entity_name/document_id/document_title/action/
        score/cohort_percentile/distance/best_passage (+ replacement fields).
        """
        if self._vs is None:
            raise RuntimeError("Vector store not available")

        top_k = getattr(self._config, "grooming_scan_top_k", 100)
        add_threshold = getattr(self._config, "grooming_add_threshold", 0.80)
        remove_threshold = getattr(self._config, "grooming_remove_threshold", 0.35)
        remove_percentile = getattr(self._config, "grooming_remove_percentile", 10)
        min_chunks = getattr(self._config, "grooming_min_supporting_chunks", 2)
        embedding_model = getattr(self._config, "embedding_model", "")
        inbox_tag_id = getattr(self._config, "inbox_tag_id", None)

        dismissed = await self._load_dismissed_keys(entity_types)

        # Incremental scans also re-examine entities whose documents drifted:
        # one global watermark = the newest re-embed across the whole corpus.
        latest_doc_embed: datetime | None = None
        if incremental:
            latest_doc_embed = (
                await self._db.execute(select(func.max(DocumentTrackingORM.last_embedded_at)))
            ).scalar_one_or_none()

        # Documents already covered by a pending suggestion are skipped.
        from backend.orm_models import SuggestionORM
        pending_q = await self._db.execute(
            select(SuggestionORM.document_id).where(SuggestionORM.status == "pending")
        )
        pending_doc_ids: set[int] = {row[0] for row in pending_q.all()}

        candidates: list[dict] = []
        stats = {"skipped_dismissed": 0, "skipped_pending": 0, "entities_scanned": 0}

        filter_params = {
            "tag": "tags__id",
            "correspondent": "correspondent__id",
            "document_type": "document_type__id",
        }

        for entity_type in entity_types:
            result = await self._db.execute(
                select(EntityDescriptionORM).where(
                    EntityDescriptionORM.entity_type == entity_type,
                    EntityDescriptionORM.excluded.is_(False),
                )
            )
            rows = [
                r for r in result.scalars().all()
                if not (entity_type == "tag" and r.entity_id == inbox_tag_id)
            ]

            # Incremental (scheduled) scans skip entities unchanged since their
            # last scan — new or description-changed entities only.
            if incremental:
                rows = [r for r in rows if _entity_needs_rescan(r, latest_doc_embed)]

            # Lazy re-embed (GROOMING_PLAN §2): vectors invalidated by a model
            # switch get one tiny embed call each. Entities that were never
            # embedded (no description generated yet) stay out of the scan —
            # embeddings are created by the description flow, not here.
            for row in rows:
                needs_refresh = (
                    (row.description and not row.embedding_stored)
                    or (row.embedding_json and row.embed_model != embedding_model)
                )
                if needs_refresh:
                    await self._embed_entity_row(row)
            await self._db.commit()
            rows = [r for r in rows if r.embedding_stored and r.embedding_json]

            # Pass 1 — per-entity unfiltered vector query + ground truth
            per_entity: dict[int, dict] = {}
            for row in rows:
                if _scan_lock.locked():  # progress only for the real scan, not dry-run
                    _scan_status["current_entity"] = f"{entity_type}:{row.name_snapshot}"
                vector = json.loads(row.embedding_json)
                results = await self._vs.query_chunks_by_vector(vector, top_k)

                doc_scores: dict[int, float] = {}
                supporting: dict[int, int] = {}
                passages: dict[int, str] = {}
                titles: dict[int, str] = {}
                payload_incumbent: dict[int, str] = {}
                for r in results:
                    d = r["document_id"]
                    if not d:
                        continue
                    if r["score"] > doc_scores.get(d, -1.0):
                        doc_scores[d] = r["score"]
                        passages[d] = (r.get("passage") or "")[:_EVIDENCE_PASSAGE_CHARS]
                        titles[d] = r.get("title", "")
                    if r["score"] >= add_threshold:
                        supporting[d] = supporting.get(d, 0) + 1
                    if entity_type in ("correspondent", "document_type"):
                        payload_incumbent[d] = r.get(entity_type, "") or ""

                assigned = await self._fetch_entity_docs(
                    filter_params[entity_type], row.entity_id, limit=10_000
                )
                assigned_ids = {d["id"] for d in assigned}
                titles.update({d["id"]: d["title"] for d in assigned})

                # Cohort scoring — filtered query where the backend supports it
                cohort_percentiles: dict[int, float] = {}
                if assigned_ids:
                    entity_filter = (
                        {"tag_id": row.entity_id} if entity_type == "tag"
                        else {entity_type: row.name_snapshot}
                    )
                    cohort_top_n = max(top_k, min(2000, 5 * len(assigned_ids)))
                    try:
                        cohort_results = await self._vs.query_chunks_by_vector(
                            vector, cohort_top_n, entity_filter=entity_filter
                        )
                        cohort_scores = {doc_id: 0.0 for doc_id in assigned_ids}
                        for r in cohort_results:
                            d = r["document_id"]
                            if d in cohort_scores and r["score"] > cohort_scores[d]:
                                cohort_scores[d] = r["score"]
                        cohort_percentiles = compute_cohort_percentiles(cohort_scores)
                    except NotImplementedError:
                        pass  # Chroma tag cohorts — absolute rules only

                per_entity[row.entity_id] = {
                    "row": row,
                    "doc_scores": doc_scores,
                    "supporting": supporting,
                    "passages": passages,
                    "titles": titles,
                    "assigned_ids": assigned_ids,
                    "cohort_percentiles": cohort_percentiles,
                    "payload_incumbent": payload_incumbent,
                }
                stats["entities_scanned"] += 1
                if _scan_lock.locked():
                    _scan_status["done"] = stats["entities_scanned"]

            # Pass 2 — classification (single-valued needs the cross-entity view)
            incumbent_by_doc: dict[int, int | None] = {}
            if entity_type in ("correspondent", "document_type"):
                for eid, data in per_entity.items():
                    for doc_id in data["assigned_ids"]:
                        incumbent_by_doc[doc_id] = eid
                # Chunk-payload fallback: a non-empty incumbent name we can't
                # map to an included entity still blocks "add" suggestions.
                for data in per_entity.values():
                    for doc_id, name in data["payload_incumbent"].items():
                        if name and doc_id not in incumbent_by_doc:
                            incumbent_by_doc[doc_id] = -1

            name_by_id = {eid: data["row"].name_snapshot for eid, data in per_entity.items()}

            for eid, data in per_entity.items():
                row = data["row"]
                kwargs = dict(
                    doc_scores=data["doc_scores"],
                    supporting_chunks=data["supporting"],
                    assigned_doc_ids=data["assigned_ids"],
                    cohort_percentiles=data["cohort_percentiles"],
                    add_threshold=add_threshold,
                    remove_threshold=remove_threshold,
                    remove_percentile=remove_percentile,
                    min_supporting_chunks=min_chunks,
                    top_k=top_k,
                )
                if entity_type == "tag":
                    actions = classify_tag_entity(**kwargs)
                else:
                    competitor_best: dict[int, tuple[int, float]] = {}
                    for other_eid, other in per_entity.items():
                        if other_eid == eid:
                            continue
                        for doc_id, sc in other["doc_scores"].items():
                            if doc_id not in competitor_best or sc > competitor_best[doc_id][1]:
                                competitor_best[doc_id] = (other_eid, sc)
                    actions = classify_single_valued_entity(
                        entity_id=eid,
                        incumbent_by_doc=incumbent_by_doc,
                        competitor_best=competitor_best,
                        **kwargs,
                    )

                for a in actions:
                    doc_id = a["document_id"]
                    c = {
                        **a,
                        "entity_type": entity_type,
                        "entity_id": eid,
                        "entity_name": row.name_snapshot,
                        "document_title": data["titles"].get(doc_id, ""),
                        "best_passage": data["passages"].get(doc_id, ""),
                    }
                    if "replacement_entity_id" in a:
                        c["replacement_entity_name"] = name_by_id.get(
                            a["replacement_entity_id"], str(a["replacement_entity_id"])
                        )
                    if self._is_dismissed(dismissed, c):
                        stats["skipped_dismissed"] += 1
                        continue
                    if doc_id in pending_doc_ids:
                        stats["skipped_pending"] += 1
                        continue
                    candidates.append(c)

        return candidates, stats

    async def run_scan_dry(self, entity_types: list[str]) -> list[dict]:
        """Full scan without enqueueing — the threshold-calibration preview."""
        candidates, _stats = await self.collect_scan_candidates(entity_types)
        candidates.sort(key=lambda c: -c["distance"])
        base_url = self._pc._base_url if self._pc else ""
        return [
            {
                "entity_type": c["entity_type"],
                "entity_name": c["entity_name"],
                "document_id": c["document_id"],
                "document_title": c["document_title"],
                "action": c["action"],
                "score": c["score"],
                "cohort_percentile": c["cohort_percentile"],
                "replacement_entity_name": c.get("replacement_entity_name"),
                "deeplink_url": f"{base_url}/documents/{c['document_id']}/" if base_url else "",
            }
            for c in candidates
        ]

    async def start_scan(self, entity_types: list[str], incremental: bool = False) -> None:
        """Start the background scan task (409 via RuntimeError if running)."""
        if _scan_lock.locked():
            raise RuntimeError("scan_running")
        asyncio.create_task(self._scan_bg(entity_types, incremental))

    async def _scan_bg(self, entity_types: list[str], incremental: bool = False) -> None:
        global _scan_status
        async with _scan_lock:
            from backend.database import AsyncSessionLocal
            _scan_status.update({
                "running": True, "done": 0, "total": 0, "current_entity": "",
            })
            summary = {
                "added": 0, "removed": 0, "replaced": 0, "review": 0,
                "skipped_dismissed": 0, "skipped_pending": 0, "capped": 0,
            }
            try:
                async with AsyncSessionLocal() as db:
                    svc = GroomingService(db, self._pc, self._providers, self._config, self._vs)
                    count_q = await db.execute(
                        select(EntityDescriptionORM).where(
                            EntityDescriptionORM.entity_type.in_(entity_types),
                            EntityDescriptionORM.excluded.is_(False),
                        )
                    )
                    _scan_status["total"] = len(count_q.scalars().all())

                    candidates, stats = await svc.collect_scan_candidates(entity_types, incremental)
                    summary["skipped_dismissed"] = stats["skipped_dismissed"]
                    summary["skipped_pending"] = stats["skipped_pending"]

                    enqueued = await svc._enqueue_candidates(candidates, summary)
                    logger.info(
                        "Grooming scan finished: %d suggestions enqueued (%s).",
                        enqueued, summary,
                    )

                    now = datetime.now(timezone.utc)
                    scanned = await db.execute(
                        select(EntityDescriptionORM).where(
                            EntityDescriptionORM.entity_type.in_(entity_types),
                            EntityDescriptionORM.excluded.is_(False),
                        )
                    )
                    for row in scanned.scalars().all():
                        row.last_scanned_at = now
                    await db.commit()
            except Exception:
                logger.exception("Grooming scan failed")
            finally:
                _scan_status.update({
                    "running": False,
                    "current_entity": "",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "last_summary": summary,
                })

    async def _enqueue_candidates(self, candidates: list[dict], summary: dict) -> int:
        """Cap, group per document, build corrected values, enqueue.

        Candidate actions are re-validated against the document's *current*
        metadata (fetched here) — anything the scan saw that has since changed
        is silently dropped rather than enqueued stale.
        """
        from backend.approval_queue import ApprovalQueueService
        from backend.models import MetadataSuggestion
        from uuid import uuid4

        max_suggestions = getattr(self._config, "grooming_max_suggestions_per_scan", 50)
        embed_provider_name = getattr(self._config, "embed_provider", "ollama")
        embedding_model = getattr(self._config, "embedding_model", "")

        candidates = sorted(candidates, key=lambda c: -c["distance"])

        # The cap applies to documents (one suggestion each), highest-evidence
        # actions first; remaining actions for a selected document ride along.
        selected_docs: list[int] = []
        for c in candidates:
            if c["document_id"] not in selected_docs:
                if len(selected_docs) >= max_suggestions:
                    continue
                selected_docs.append(c["document_id"])
        by_doc: dict[int, list[dict]] = {d: [] for d in selected_docs}
        for c in candidates:
            if c["document_id"] in by_doc:
                by_doc[c["document_id"]].append(c)
        summary["capped"] = len({c["document_id"] for c in candidates}) - len(selected_docs)

        # id→name maps for resolving current document metadata
        name_maps: dict[str, dict[int, str]] = {}
        for etype in ("tag", "correspondent", "document_type"):
            entities = await self._fetch_paperless_entities(etype)
            name_maps[etype] = {e["id"]: e["name"] for e in entities}

        queue_svc = ApprovalQueueService(self._db)
        now = datetime.now(timezone.utc)
        enqueued = 0

        for doc_id, actions in by_doc.items():
            doc = await self._fetch_document(doc_id)
            if doc is None:
                continue

            current_tags = [
                name_maps["tag"][tid] for tid in (doc.get("tags") or [])
                if tid in name_maps["tag"]
            ]
            corrected_tags = list(current_tags)
            current_corr_id = doc.get("correspondent")
            current_dt_id = doc.get("document_type")
            corrected_corr = name_maps["correspondent"].get(current_corr_id) if current_corr_id else None
            corrected_dt = name_maps["document_type"].get(current_dt_id) if current_dt_id else None

            valid_actions: list[dict] = []
            for a in actions:
                etype, name, act = a["entity_type"], a["entity_name"], a["action"]
                if etype == "tag":
                    if act == "add":
                        if name in corrected_tags:
                            continue  # stale — already applied
                        corrected_tags.append(name)
                    elif act == "remove":
                        if name not in corrected_tags:
                            continue  # stale — already gone
                        corrected_tags.remove(name)
                else:
                    current_id = current_corr_id if etype == "correspondent" else current_dt_id
                    if act == "add":
                        if current_id is not None:
                            continue  # stale — field set meanwhile
                        new_name = name
                    elif act == "replace":
                        if current_id != a["entity_id"]:
                            continue  # stale — incumbent changed
                        new_name = a.get("replacement_entity_name")
                    else:  # review — field stays at its current value
                        if current_id != a["entity_id"]:
                            continue
                        new_name = None
                    if new_name is not None:
                        if etype == "correspondent":
                            corrected_corr = new_name
                        else:
                            corrected_dt = new_name
                valid_actions.append({
                    "action": act,
                    "entity_type": etype,
                    "entity_id": a["entity_id"],
                    "entity_name": name,
                    "score": a["score"],
                    "cohort_percentile": a["cohort_percentile"],
                    "reason": a.get("reason"),
                    "best_passage": a["best_passage"],
                    **(
                        {
                            "replacement_entity_id": a["replacement_entity_id"],
                            "replacement_entity_name": a.get("replacement_entity_name"),
                            "replacement_score": a.get("replacement_score"),
                        }
                        if "replacement_entity_id" in a else {}
                    ),
                })

            if not valid_actions:
                continue

            suggestion = MetadataSuggestion(
                id=uuid4(),
                document_id=doc_id,
                status="pending",
                created_at=now,
                title=doc.get("title"),
                tags=corrected_tags,
                correspondent=corrected_corr,
                document_type=corrected_dt,
                storage_path=None,
                custom_fields={},
                llm_provider=embed_provider_name,
                llm_model=embedding_model,
                analysis_mode="grooming",
                prompt_used="",
                raw_llm_response="",
                evidence_json=json.dumps({
                    "actions": valid_actions,
                    "base_tags": current_tags,
                    "scanned_at": now.isoformat(),
                }),
            )
            await queue_svc.enqueue(suggestion)
            enqueued += 1
            for a in valid_actions:
                key = {"add": "added", "remove": "removed", "replace": "replaced", "review": "review"}[a["action"]]
                summary[key] += 1

        return enqueued

    @staticmethod
    def get_scan_status() -> dict:
        return dict(_scan_status)

    # ── Provider helpers ───────────────────────────────────────────────────

    def _get_llm_provider(self) -> Any | None:
        if not self._providers:
            return None
        llm_provider_name = getattr(self._config, "llm_provider", "ollama")
        return self._providers.get(llm_provider_name)

    def _get_embed_provider(self) -> Any | None:
        if not self._providers:
            return None
        embed_provider_name = getattr(self._config, "embed_provider", "ollama")
        provider = self._providers.get(embed_provider_name)
        if provider is None:
            provider = self._providers.get(getattr(self._config, "llm_provider", ""))
        return provider
