"""Programmatic Alembic migration runner used at application startup.

Production and dev both manage schema through Alembic — a single source of truth.
Databases created before Alembic was adopted (schema built by the old
``create_all`` + inline ``ALTER TABLE`` approach) have no ``alembic_version``
table; we detect that and ``stamp`` them at the baseline before upgrading, so an
existing database adopts Alembic without re-creating its tables.

Tests create their schema directly via ``Base.metadata.create_all`` and do not
call this module.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from backend.database import DATABASE_URL

logger = logging.getLogger(__name__)

# Baseline revision — the first migration, which creates the full current schema.
_BASELINE_REVISION = "f4d9771c79eb"

# A table present in every released schema; used to tell a pre-Alembic database
# (already has data, no alembic_version bookkeeping) apart from a brand-new one.
_SENTINEL_TABLE = "settings"


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parent.parent  # repo root (holds alembic.ini)
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "alembic"))
    return cfg


def _run_migrations_sync() -> None:
    """Stamp pre-Alembic DBs, then upgrade to head. Runs in a worker thread."""
    # Synchronous engine purely for inspection; Alembic's env builds its own.
    sync_url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
    engine = create_engine(sync_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    cfg = _alembic_config()

    if "alembic_version" not in tables and _SENTINEL_TABLE in tables:
        # Existing pre-Alembic database: adopt it at the baseline without
        # re-creating tables, then let upgrade apply anything newer.
        logger.info(
            "Existing pre-Alembic database detected — stamping baseline %s",
            _BASELINE_REVISION,
        )
        command.stamp(cfg, _BASELINE_REVISION)

    command.upgrade(cfg, "head")
    logger.info("Database migrations applied (alembic upgrade head).")


async def run_migrations() -> None:
    """Apply Alembic migrations off the event loop.

    Alembic's env runs ``asyncio.run`` internally, which cannot be called from a
    running loop — so we execute it in a worker thread (which has no loop).
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_migrations_sync)
