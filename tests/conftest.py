"""Pytest configuration and fixtures for Paperless IQ tests.

Hypothesis policy
-----------------
* Randomness stays ON — never set derandomize=True or pin seeds in committed code.
  A new counterexample is the tool working, not a flake.
* A Hypothesis failure is a bug report. Reproduce with the printed
  ``@reproduce_failure(...)`` blob, shrink, classify (app bug vs. test bug),
  fix the root cause. Never loosen an assertion just to go green.
* The ``.hypothesis/`` directory is git-ignored (accumulates falsifying examples
  locally and in CI; not committed).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Hypothesis settings profile
# ---------------------------------------------------------------------------

settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,                          # wall-clock time is not a correctness signal
    print_blob=True,                        # every failure prints a @reproduce_failure blob
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "deep",
    max_examples=2000,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci")


# ---------------------------------------------------------------------------
# Async test client fixture (legacy — kept for existing tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def async_client():
    """Async HTTP test client for the FastAPI app."""
    from backend.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Route-test infrastructure
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_engine():
    """In-memory SQLite engine with all ORM tables created.

    Shared between app_client and direct DB helpers so that data written
    by tests is visible to the route handler and vice-versa.
    """
    from backend.orm_models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def app_client(db_engine):
    """ASGI test client wired to an in-memory SQLite DB.

    * ASGITransport does NOT run the lifespan, so automation/audit loops never
      start and app.state is not populated by startup code.  All app.state attrs
      that routes touch are set to safe defaults here.
    * get_session is overridden so every route handler (and require_perm) uses
      the same in-memory engine as the test.
    * PAPERLESS_URL is absent → _is_auth_required() returns False → all routes
      are open (no token needed) and require_perm is a no-op.
    """
    from backend.database import get_session
    from backend.main import app
    from backend.rate_limiter import RateLimiter

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def _override_session() -> AsyncSession:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session

    # Populate app.state so middleware/routes don't AttributeError on access
    app.state.rate_limiter = RateLimiter()
    app.state.paperless_client = None
    app.state.vector_store = None
    app.state.memory_store = None
    app.state.ollama_queue = None
    app.state.providers = None
    app.state.manual_analysis_svc = None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.pop(get_session, None)
