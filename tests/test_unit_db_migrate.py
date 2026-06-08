"""Unit tests for the startup Alembic migration runner.

Covers the three database states the runner must handle on boot:
  1. Brand-new DB              → build the schema, stamp head.
  2. Pre-Alembic DB            → sentinel table exists, no alembic_version → stamp.
  3. Half-stamped/wedged DB    → alembic_version table exists but is *empty*.

State 3 is the regression: SQLite's non-transactional DDL means a first
migration that crashes can leave an empty alembic_version table. A naive
"stamp only when the table is absent" check then lets ``upgrade`` re-run the
baseline CREATE TABLEs against the existing schema, crash-looping the app.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

import backend.database as database
import backend.db_migrate as db_migrate


def _run_migrations() -> None:
    """Run the migration sync routine in a worker thread, as production does.

    ``run_migrations`` dispatches ``_run_migrations_sync`` via run_in_executor, so
    Alembic's internal ``asyncio.run`` always executes on a loop-less worker
    thread. Calling it directly from the test's main thread instead would churn
    the event loop that pytest-asyncio manages for other tests. Mirroring the
    production threading keeps this test from polluting later async tests.
    """
    error: dict[str, BaseException] = {}

    def target() -> None:
        try:
            db_migrate._run_migrations_sync()
        except BaseException as exc:  # noqa: BLE001 — re-raised on the main thread
            error["exc"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "exc" in error:
        raise error["exc"]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point both the runner and Alembic's env at an isolated temp SQLite file."""
    db_path = tmp_path / "piq.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setattr(database, "DATABASE_URL", url)
    monkeypatch.setattr(db_migrate, "DATABASE_URL", url)
    return db_path


def _current_revision(db_path) -> str | None:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _table_names(db_path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_fresh_db_migrates_to_head(temp_db):
    _run_migrations()

    assert _current_revision(temp_db) == db_migrate._BASELINE_REVISION
    assert db_migrate._SENTINEL_TABLE in _table_names(temp_db)


def test_pre_alembic_db_is_stamped_not_recreated(temp_db):
    # Sentinel table present, no alembic_version at all (classic pre-Alembic DB).
    con = sqlite3.connect(temp_db)
    con.execute(f"CREATE TABLE {db_migrate._SENTINEL_TABLE} (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()

    _run_migrations()  # must not raise re-creating the table

    assert _current_revision(temp_db) == db_migrate._BASELINE_REVISION


def test_empty_alembic_version_is_restamped(temp_db):
    """Regression: an existing schema with an empty alembic_version must re-stamp,
    not re-run the baseline migration."""
    # Build the full schema and stamp head…
    _run_migrations()
    # …then wedge it: table exists but holds no revision row.
    con = sqlite3.connect(temp_db)
    con.execute("DELETE FROM alembic_version")
    con.commit()
    con.close()
    assert _current_revision(temp_db) is None

    # Second boot must recover cleanly rather than crash on CREATE TABLE.
    _run_migrations()

    assert _current_revision(temp_db) == db_migrate._BASELINE_REVISION
