"""Library grooming service — dedup, descriptions, entity embedding.

This module implements Steps 1–4 of the grooming rollout:
  1. Entity sync from Paperless (list_entities / sync_entities)
  2. Description CRUD + LLM generation (single + bulk)
  3. Entity embedding  (embed_entity)
  4. Dedup candidates  (get_dedup_candidates / merge_entities)

Step 5 (mismatch scan) adds query_chunks_by_vector and is not here yet.
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.orm_models import (
    AuditLogORM,
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
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), x)
            x = parent.get(x, x)
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


# ── GroomingService ────────────────────────────────────────────────────────

class GroomingService:
    """Orchestrates all library-grooming operations."""

    def __init__(
        self,
        session: AsyncSession,
        paperless_client: Any | None,
        providers: dict | None,
        config: Any,
    ) -> None:
        self._db = session
        self._pc = paperless_client
        self._providers = providers
        self._config = config

    # ── Entity sync ────────────────────────────────────────────────────────

    async def sync_and_list_entities(self, entity_type: str) -> list[dict]:
        """Fetch entities from Paperless, sync to DB, return enriched list.

        ``entity_type`` is one of ``"tag"``, ``"correspondent"``, ``"document_type"``.
        """
        if self._pc is None:
            raise RuntimeError("Paperless NGX client not available")

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

        # Sync to DB: upsert rows, prune deleted ones
        existing_ids = {item["id"] for item in entities}
        result = await self._db.execute(
            select(EntityDescriptionORM).where(EntityDescriptionORM.entity_type == entity_type)
        )
        rows: dict[int, EntityDescriptionORM] = {r.entity_id: r for r in result.scalars().all()}

        now = datetime.now(timezone.utc)
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
        etype_plural = {"tag": "tags", "correspondent": "correspondents", "document_type": "document_types"}[row.entity_type]
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
