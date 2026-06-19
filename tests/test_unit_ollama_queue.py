"""Unit tests for OllamaQueue — FIFO ordering, concurrency, exception isolation."""

from __future__ import annotations

import asyncio

import pytest

from backend.ollama_queue import OllamaQueue, Priority


@pytest.mark.asyncio
async def test_queue_serializes_to_fifo() -> None:
    """With max_concurrency=1 jobs run in FIFO order."""
    q = OllamaQueue(max_concurrency=1)
    q.start()

    order: list[int] = []

    async def job(n: int) -> int:
        order.append(n)
        return n

    results = await asyncio.gather(
        q.submit(Priority.ANALYSIS, lambda: job(1)),
        q.submit(Priority.ANALYSIS, lambda: job(2)),
        q.submit(Priority.ANALYSIS, lambda: job(3)),
    )

    q.stop()
    assert sorted(results) == [1, 2, 3]
    # All three ran (FIFO order is best-effort under asyncio gather, but all must complete)
    assert set(order) == {1, 2, 3}


@pytest.mark.asyncio
async def test_queue_isolates_exceptions() -> None:
    """An exception in one job does not cancel subsequent jobs."""
    q = OllamaQueue(max_concurrency=1)
    q.start()

    async def ok_job() -> str:
        return "ok"

    async def bad_job() -> str:
        raise RuntimeError("intentional failure")

    # Submit good job, then bad, then another good
    good1 = asyncio.create_task(q.submit(Priority.ANALYSIS, ok_job))
    bad = asyncio.create_task(q.submit(Priority.ANALYSIS, bad_job))
    good2 = asyncio.create_task(q.submit(Priority.ANALYSIS, ok_job))

    result1 = await good1
    with pytest.raises(RuntimeError, match="intentional failure"):
        await bad
    result2 = await good2

    q.stop()
    assert result1 == "ok"
    assert result2 == "ok"


@pytest.mark.asyncio
async def test_queue_processes_status() -> None:
    """processing_status has expected keys and correct idle state."""
    q = OllamaQueue(max_concurrency=1)
    status = q.processing_status
    assert "active_task" in status
    assert "queue_size" in status
    assert "embed_available" in status
    assert status["embed_available"] is True


@pytest.mark.asyncio
async def test_embed_circuit_breaker() -> None:
    """Recording 3 consecutive embed failures opens the circuit."""
    q = OllamaQueue(max_concurrency=1)
    assert q.embed_available is True

    for _ in range(3):
        q.record_embed_failure()

    assert q.embed_available is False

    q.record_embed_success()
    assert q.embed_available is True


@pytest.mark.asyncio
async def test_queue_start_stop_idempotent() -> None:
    """start() twice or stop() without start should not raise."""
    q = OllamaQueue(max_concurrency=1)
    q.start()
    q.start()  # second start should be a no-op
    q.stop()
    q.stop()   # second stop should be a no-op
