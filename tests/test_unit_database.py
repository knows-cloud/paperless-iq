"""Smoke tests for backend/database.py — get_session dependency."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_get_session_yields_async_session() -> None:
    """get_session yields an AsyncSession and closes it cleanly."""
    from backend.database import get_session

    gen = get_session()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    # Drive the generator to completion (simulates FastAPI calling it after the request)
    try:
        await gen.asend(None)
    except StopAsyncIteration:
        pass
