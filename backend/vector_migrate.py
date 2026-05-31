"""Backend-agnostic embedding migration (QDRANT_PLAN §8).

Copies stored vectors from one store to another **without re-embedding**, so
switching backend (e.g. Chroma → Qdrant) preserves the existing index. Relies
on the ``dump_points``/``load_points`` (documents) and ``dump_all``/``load_all``
(memories) methods; stores lacking them (e.g. Bedrock KB) can't be migrated and
yield ``needs_reindex=True``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    migrated: int
    needs_reindex: bool
    reason: str = ""


def _supports_dump_load(src: Any, dst: Any, dump: str, load: str) -> bool:
    return src is not None and dst is not None and hasattr(src, dump) and hasattr(dst, load)


async def migrate_embeddings(src: Any, dst: Any) -> MigrationResult:
    """Copy document vectors from ``src`` to ``dst``.

    No-ops (success) when the source is empty or the destination already holds
    data. Returns ``needs_reindex=True`` if a backend can't be dumped/loaded or
    the copy fails — the caller then prompts the user to re-index.
    """
    if not _supports_dump_load(src, dst, "dump_points", "load_points"):
        return MigrationResult(0, True, "backend does not support migration (re-index required)")
    try:
        if await src.count() == 0:
            return MigrationResult(0, False, "source is empty")
        if await dst.count() > 0:
            return MigrationResult(0, False, "destination already populated")
        points = await src.dump_points()
        if not points:
            return MigrationResult(0, False, "no points to migrate")
        migrated = await dst.load_points(points)
        logger.info("Migrated %d vector points to the new backend.", migrated)
        return MigrationResult(migrated, False, "")
    except Exception as exc:
        logger.warning("Embedding migration failed: %s", exc, exc_info=True)
        return MigrationResult(0, True, f"migration failed: {exc}")


async def migrate_memories(src: Any, dst: Any) -> MigrationResult:
    """Copy long-term memory vectors from ``src`` to ``dst`` (best-effort)."""
    if not _supports_dump_load(src, dst, "dump_all", "load_all"):
        return MigrationResult(0, False, "memory migration not supported")
    try:
        items = await src.dump_all()
        if not items:
            return MigrationResult(0, False, "no memories to migrate")
        migrated = await dst.load_all(items)
        logger.info("Migrated %d memory entries to the new backend.", migrated)
        return MigrationResult(migrated, False, "")
    except Exception as exc:
        logger.warning("Memory migration failed: %s", exc, exc_info=True)
        return MigrationResult(0, False, f"memory migration failed: {exc}")
