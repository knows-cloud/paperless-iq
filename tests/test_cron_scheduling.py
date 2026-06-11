"""Step 6 — cron scheduling + incremental grooming scan.

Covers:
- _cron_next: valid expressions return the next UTC fire time; invalid → None
- _cron_loop: fires the job when due, idle when the expression is None
- _entity_needs_rescan + collect_scan_candidates(incremental=True): unchanged
  entities are skipped on scheduled runs
- _run_scheduled_grooming_scan guards: disabled / bedrock_kb / busy short-circuit
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.grooming import GroomingService, _entity_needs_rescan

# Reuse the scan fixtures from the grooming test module.
from tests.test_grooming import FakeVectorStore, _chunk, _config, _entity_row


# ---------------------------------------------------------------------------
# _cron_next
# ---------------------------------------------------------------------------

def test_cron_next_returns_following_fire_time() -> None:
    from backend.main import _cron_next

    base = datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)
    assert _cron_next("0 3 * * *", base) == datetime(2026, 6, 12, 3, 0, tzinfo=timezone.utc)
    assert _cron_next("*/15 * * * *", base) == datetime(2026, 6, 11, 10, 15, tzinfo=timezone.utc)


def test_cron_next_invalid_returns_none() -> None:
    from backend.main import _cron_next

    base = datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)
    assert _cron_next("not a cron", base) is None
    assert _cron_next("99 99 * * *", base) is None


# ---------------------------------------------------------------------------
# _cron_loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cron_loop_fires_job_when_due(monkeypatch) -> None:
    from backend import main as m

    calls: list[int] = []

    async def job() -> None:
        calls.append(1)
        raise asyncio.CancelledError()  # stop after the first fire

    # Force "due": next fire is always one second in the past.
    monkeypatch.setattr(m, "_cron_next", lambda expr, after: after - timedelta(seconds=1))

    with pytest.raises(asyncio.CancelledError):
        await m._cron_loop("Test", lambda: "0 3 * * *", job, check_interval=0)

    assert calls == [1]


@pytest.mark.asyncio
async def test_cron_loop_idle_when_expr_none(monkeypatch) -> None:
    from backend import main as m

    calls: list[int] = []

    async def job() -> None:
        calls.append(1)

    async def fake_sleep(_seconds) -> None:
        raise asyncio.CancelledError()  # break out after the first idle tick

    monkeypatch.setattr(m.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await m._cron_loop("Test", lambda: None, job, check_interval=0)

    assert calls == []


# ---------------------------------------------------------------------------
# Incremental rescan predicate
# ---------------------------------------------------------------------------

def _row(last_scanned, desc_updated) -> SimpleNamespace:
    return SimpleNamespace(last_scanned_at=last_scanned, description_updated_at=desc_updated)


def test_entity_needs_rescan_rules() -> None:
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=1)

    assert _entity_needs_rescan(_row(None, None)) is True      # never scanned
    assert _entity_needs_rescan(_row(None, t0)) is True        # never scanned (has desc)
    assert _entity_needs_rescan(_row(t1, None)) is False       # scanned, never edited
    assert _entity_needs_rescan(_row(t0, t1)) is True          # edited after last scan
    assert _entity_needs_rescan(_row(t1, t0)) is False         # edited before last scan


def test_entity_needs_rescan_treats_naive_as_utc() -> None:
    naive_old = datetime(2026, 6, 1)            # naive
    aware_new = datetime(2026, 6, 2, tzinfo=timezone.utc)
    # last scan naive, edited (aware) afterwards → rescan
    assert _entity_needs_rescan(_row(naive_old, aware_new)) is True


@pytest.mark.asyncio
async def test_collect_scan_candidates_incremental_skips_unchanged(db_engine) -> None:
    """Scheduled (incremental) scan ignores an entity scanned with no later edit."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        row = _entity_row("tag", 1, "Insurance")
        # Already scanned after its last description edit → should be skipped.
        row.description_updated_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        row.last_scanned_at = datetime(2026, 6, 2, tzinfo=timezone.utc)
        session.add(row)
        await session.commit()

        vs = FakeVectorStore({1: [_chunk(7, 0.9), _chunk(7, 0.85)]})
        pc = SimpleNamespace(_base_url="http://paperless.test", _headers={})
        svc = GroomingService(session, pc, None, _config(), vector_store=vs)

        async def fake_entity_docs(filter_param, entity_id, limit):
            return []
        svc._fetch_entity_docs = fake_entity_docs

        inc_candidates, inc_stats = await svc.collect_scan_candidates(["tag"], incremental=True)
        assert inc_candidates == []
        assert inc_stats["entities_scanned"] == 0

        # Full scan (manual) still examines it.
        full_candidates, full_stats = await svc.collect_scan_candidates(["tag"], incremental=False)
        assert full_stats["entities_scanned"] == 1
        assert len(full_candidates) == 1


# ---------------------------------------------------------------------------
# _run_scheduled_grooming_scan guards
# ---------------------------------------------------------------------------

def _scan_app(config, vector_store=MagicMock(), embed_ok=True) -> SimpleNamespace:
    oq = SimpleNamespace(cached_health={"embed": embed_ok})
    return SimpleNamespace(
        state=SimpleNamespace(
            vector_store=vector_store, paperless_client=None, providers=None, ollama_queue=oq,
        )
    )


@pytest.mark.asyncio
async def test_scheduled_scan_skipped_when_grooming_disabled(monkeypatch) -> None:
    from backend import main as m

    monkeypatch.setattr(m._settings_svc, "_config",
                        SimpleNamespace(grooming_enabled=False, vector_store_backend="local"))
    with patch.object(m.GroomingService, "start_scan", new=AsyncMock()) as start:
        await m._run_scheduled_grooming_scan(_scan_app(m._settings_svc.config))
    start.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_scan_skipped_on_bedrock_kb(monkeypatch) -> None:
    from backend import main as m

    cfg = SimpleNamespace(grooming_enabled=True, vector_store_backend="bedrock_kb")
    monkeypatch.setattr(m._settings_svc, "_config", cfg)
    with patch.object(m.GroomingService, "start_scan", new=AsyncMock()) as start:
        await m._run_scheduled_grooming_scan(_scan_app(cfg))
    start.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_scan_skipped_when_embed_circuit_open(monkeypatch) -> None:
    from backend import main as m

    cfg = SimpleNamespace(
        grooming_enabled=True, vector_store_backend="local",
        grooming_entity_types=["tag"],
    )
    monkeypatch.setattr(m._settings_svc, "_config", cfg)
    with patch.object(m.GroomingService, "start_scan", new=AsyncMock()) as start:
        await m._run_scheduled_grooming_scan(_scan_app(cfg, embed_ok=False))
    start.assert_not_called()
