"""Priority queue for Ollama requests.

Serializes all Ollama access to prevent overloading the server.
Analysis requests (high priority) pause background embedding (low priority).
Health checks only run when the queue is idle.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import IntEnum
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Priority(IntEnum):
    """Lower number = higher priority."""
    ANALYSIS = 0
    EMBEDDING = 1
    HEALTH_CHECK = 2


class OllamaQueue:
    """Priority-aware queue that serializes Ollama requests.

    - Only one request runs at a time (configurable concurrency).
    - High-priority requests (analysis) preempt low-priority ones (embedding)
      by pausing the background indexer after its current request finishes.
    - Health checks only run when nothing else is queued.
    """

    def __init__(self, max_concurrency: int = 1) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._queue: asyncio.PriorityQueue[tuple[int, float, asyncio.Future[Any], Callable[[], Awaitable[Any]], str]] = asyncio.PriorityQueue()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused initially
        self._running = False
        self._worker_task: asyncio.Task[None] | None = None
        self._active_priority: Priority | None = None
        # Cached health status
        self._last_health: dict[str, bool] = {}
        self._last_health_time: float = 0.0
        # Processing tracking
        self._active_label: str | None = None  # description of current task
        self._embedding_active: bool = False
        self._embedding_total: int = 0
        self._embedding_done: int = 0
        self._analysis_queue_labels: list[str] = []  # waiting analysis tasks

    def start(self) -> None:
        """Start the queue worker."""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())

    def stop(self) -> None:
        """Stop the queue worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()

    async def submit(self, priority: Priority, fn: Callable[[], Awaitable[T]], label: str = "") -> T:
        """Submit a request to the queue and wait for the result."""
        future: asyncio.Future[T] = asyncio.get_event_loop().create_future()
        await self._queue.put((priority.value, time.monotonic(), future, fn, label))

        # If this is a high-priority request, pause background work
        if priority == Priority.ANALYSIS:
            self._pause_event.clear()

        return await future

    async def submit_background(self, fn: Callable[[], Awaitable[T]], label: str = "") -> T:
        """Submit a low-priority background request. Waits if paused."""
        await self._pause_event.wait()
        return await self.submit(Priority.EMBEDDING, fn, label=label)

    def resume_background(self) -> None:
        """Resume background processing (called when analysis queue is empty)."""
        self._pause_event.set()

    @property
    def is_busy(self) -> bool:
        return self._active_priority is not None

    @property
    def cached_health(self) -> dict[str, bool]:
        return dict(self._last_health)

    def update_health_cache(self, key: str, value: bool) -> None:
        self._last_health[key] = value
        self._last_health_time = time.monotonic()

    @property
    def health_cache_age(self) -> float:
        return time.monotonic() - self._last_health_time if self._last_health_time else 999.0

    def set_embedding_progress(self, total: int, done: int) -> None:
        self._embedding_total = total
        self._embedding_done = done
        self._embedding_active = done < total

    @property
    def processing_status(self) -> dict[str, Any]:
        """Return current processing pipeline status."""
        return {
            "active_task": self._active_label,
            "active_priority": self._active_priority.name if self._active_priority else None,
            "embedding_active": self._embedding_active,
            "embedding_total": self._embedding_total,
            "embedding_done": self._embedding_done,
            "queue_size": self._queue.qsize(),
        }

    async def _worker(self) -> None:
        """Process queued requests one at a time."""
        while self._running:
            try:
                priority_val, _, future, fn, label = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                # Nothing in queue — resume background if paused
                if not self._pause_event.is_set():
                    self._pause_event.set()
                continue
            except asyncio.CancelledError:
                break

            self._active_priority = Priority(priority_val)
            self._active_label = label or None
            try:
                async with self._semaphore:
                    result = await fn()
                    if not future.done():
                        future.set_result(result)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                self._active_priority = None
                self._active_label = None
                self._queue.task_done()

                # If no more analysis requests, resume background
                if self._queue.empty() or self._queue.qsize() == 0:
                    self._pause_event.set()
