"""Programmatic Alembic migration runner used at application startup.

Production and dev both manage schema through Alembic — a single source of truth.
The migration tree is the numbered chain ``001`` (initial schema) → ``002``
(grooming objects) → ``003`` (``last_embedded_at``).

This runner self-heals two classes of database that a plain ``upgrade`` can't
advance:

* **Pre-Alembic** — has the application tables but no ``alembic_version`` row
  (schema built by the old ``create_all`` + inline ``ALTER TABLE`` approach, or
  a half-initialised DB whose ``alembic_version`` table exists but is empty —
  SQLite DDL is non-transactional, so a crashed first migration leaves exactly
  that). We stamp the matching baseline so the baseline ``CREATE TABLE``
  statements are skipped.
* **Stale/unknown revision** — ``alembic_version`` holds a revision id that no
  longer exists in our migration tree (e.g. ``f4d9771c79eb`` from an earlier,
  since-replaced Alembic setup). ``upgrade`` would abort with "Can't locate
  revision identified by …", silently leaving the schema behind. We detect the
  unknown id, pick the baseline that matches the *live* schema, and re-stamp
  (purging the orphan id) before upgrading.

The baseline is chosen from the live schema, not assumed: if the grooming
objects already exist we stamp ``002``, otherwise ``001`` (so ``002`` then
applies).

Tests create their schema directly via ``Base.metadata.create_all`` and do not
call this module.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect as sa_inspect

from backend.database import DATABASE_URL

logger = logging.getLogger(__name__)


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parent.parent  # repo root (holds alembic.ini)
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "alembic"))
    return cfg


def _run_migrations_sync() -> None:
    """Self-heal stamp (if needed), then upgrade to head. Runs in a worker thread."""
    sync_url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
    sync_engine = create_engine(sync_url, future=True)
    cfg = _alembic_config()
    try:
        with sync_engine.connect() as conn:
            mc = MigrationContext.configure(conn)
            current_rev = mc.get_current_revision()
            known_revs = {
                sc.revision for sc in ScriptDirectory.from_config(cfg).walk_revisions()
            }

            inspector = sa_inspect(conn)
            tables = set(inspector.get_table_names())
            has_app_tables = "suggestions" in tables or "document_tracking" in tables

            # current_rev is None        → pre-Alembic database
            # current_rev not in known   → orphaned id from a prior Alembic setup
            needs_stamp = has_app_tables and (
                current_rev is None or current_rev not in known_revs
            )
            if needs_stamp:
                # Pick the highest revision whose schema is *fully present* in the
                # live database, so ``upgrade head`` only runs genuinely-pending
                # migrations. Stamping too low would re-run a migration whose
                # objects already exist (e.g. 003's ALTER → duplicate column).
                #   001 — initial schema
                #   002 — grooming objects (entity_descriptions + can_groom column)
                #   003 — document_tracking.last_embedded_at column
                user_perm_cols = (
                    {c["name"] for c in inspector.get_columns("user_permissions")}
                    if "user_permissions" in tables
                    else set()
                )
                dt_cols = (
                    {c["name"] for c in inspector.get_columns("document_tracking")}
                    if "document_tracking" in tables
                    else set()
                )
                has_grooming = "entity_descriptions" in tables and "can_groom" in user_perm_cols
                has_last_embedded = "last_embedded_at" in dt_cols
                if has_grooming and has_last_embedded:
                    baseline = "003"
                elif has_grooming:
                    baseline = "002"
                else:
                    baseline = "001"
                # purge=True drops the orphan alembic_version row before stamping,
                # so an unknown current revision can't block it.
                command.stamp(cfg, baseline, purge=True)
                logger.info(
                    "Stamped database at %s based on live schema (was %r).",
                    baseline,
                    current_rev,
                )
    finally:
        sync_engine.dispose()

    command.upgrade(cfg, "head")
    logger.info("Database migrations applied (alembic upgrade head).")


async def run_migrations() -> None:
    """Apply Alembic migrations off the event loop.

    Alembic's env runs ``asyncio.run`` internally, which cannot be called from a
    running loop — so we execute it in a worker thread (which has no loop).
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_migrations_sync)
