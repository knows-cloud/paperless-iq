"""Unit tests for _automation_loop in backend/main.py.

The plan says: single-iteration test — patch asyncio.sleep to raise CancelledError
after first pass; assert batch_size=None vs batch_size=N behavior (the single-loop
design rule — no two separate loops, just _automation_loop with different args).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


def _make_app_stub(
    paperless_client=None,
    manual_svc=None,
    ollama_queue=None,
) -> FastAPI:
    """Return a minimal FastAPI instance with the app.state attrs the loop reads."""
    app = FastAPI()
    app.state.paperless_client = paperless_client
    app.state.manual_analysis_svc = manual_svc
    app.state.ollama_queue = ollama_queue
    return app


@pytest.mark.asyncio
async def test_automation_loop_skips_when_services_unconfigured() -> None:
    """When paperless_client or manual_svc is None the loop logs and sleeps.

    Cancels after the first sleep so we don't loop forever.
    """
    from backend.main import _automation_loop

    app = _make_app_stub(paperless_client=None, manual_svc=None)

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError()

    with patch("backend.main.asyncio.sleep", side_effect=_fake_sleep):
        with patch("backend.main.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            with pytest.raises(asyncio.CancelledError):
                await _automation_loop(app, poll_interval=5, batch_size=None)

    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 5


@pytest.mark.asyncio
async def test_automation_loop_inbox_mode_uses_monitor() -> None:
    """With batch_size=None the loop delegates to InboxMonitor.poll(), not Scheduler."""
    from backend.main import _automation_loop

    mock_monitor = AsyncMock()
    mock_monitor.poll = AsyncMock(return_value=[])

    async def _fake_sleep(_: float) -> None:
        raise asyncio.CancelledError()

    with patch("backend.main.asyncio.sleep", side_effect=_fake_sleep):
        with patch("backend.main.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            with patch("backend.main.InboxMonitor", return_value=mock_monitor) as MockMonitor:
                with patch("backend.main.Scheduler") as MockScheduler:
                    app = _make_app_stub(
                        paperless_client=MagicMock(),
                        manual_svc=MagicMock(),
                    )
                    with pytest.raises(asyncio.CancelledError):
                        await _automation_loop(app, poll_interval=1, batch_size=None)

    MockMonitor.assert_called_once()
    MockScheduler.assert_not_called()


@pytest.mark.asyncio
async def test_automation_loop_scheduler_mode_uses_scheduler() -> None:
    """With batch_size=N the loop delegates to Scheduler.run_batch(), not InboxMonitor."""
    from backend.main import _automation_loop

    mock_scheduler = AsyncMock()
    mock_scheduler.run_batch = AsyncMock(return_value=[])

    async def _fake_sleep(_: float) -> None:
        raise asyncio.CancelledError()

    with patch("backend.main.asyncio.sleep", side_effect=_fake_sleep):
        with patch("backend.main.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            with patch("backend.main.Scheduler", return_value=mock_scheduler) as MockScheduler:
                with patch("backend.main.InboxMonitor") as MockMonitor:
                    app = _make_app_stub(
                        paperless_client=MagicMock(),
                        manual_svc=MagicMock(),
                    )
                    with pytest.raises(asyncio.CancelledError):
                        await _automation_loop(app, poll_interval=1, batch_size=10)

    MockScheduler.assert_called_once()
    MockMonitor.assert_not_called()
