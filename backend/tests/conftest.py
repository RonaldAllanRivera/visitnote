"""Shared test fixtures.

Tests run against real PostgreSQL and real Redis, not in-memory substitutes. Half of
what is worth testing here -- cross-tenant isolation, aggregation correctness, unique
constraints, TIMESTAMPTZ behaviour across a DST boundary -- either does not exist or
behaves differently in SQLite.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.db import engine
from app.core.redis import pool
from app.main import create_app
from app.storage import FakeStorageProvider, get_storage_provider

# The app under test runs the real TrustedHostMiddleware, so requests must carry a
# Host header the application actually trusts. Using a fake host here would either
# fail every request or require disabling the middleware -- and a middleware that is
# switched off in tests is a middleware nobody is testing.
BASE_URL = "http://localhost"


@pytest.fixture(autouse=True, scope="session")
async def _dispose_pools() -> AsyncGenerator[None]:
    """Release the module-level engine and Redis pool at the end of the session.

    Tests that talk to the database directly, without going through the app lifespan,
    leave connections open. `filterwarnings = ["error"]` turns the resulting
    ResourceWarning into a failure -- which is the setting doing its job, so the fix
    is to close the pools rather than to silence the warning.
    """
    yield
    await engine.dispose()
    await pool.aclose()


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    """A database session on a throwaway engine, one per test.

    Tests get their own engine rather than importing the application's module-level
    `SessionFactory`, because a pooled asyncpg connection is bound to the event loop
    that opened it and pytest-asyncio gives each test a fresh loop. Borrowing a
    connection across loops produces failures that appear only when tests run
    together -- the worst kind to debug.

    NullPool means no connection outlives the test that opened it.
    """
    test_engine = create_async_engine(get_settings().sqlalchemy_url, poolclass=NullPool)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    try:
        async with factory() as db_session:
            yield db_session
    finally:
        await test_engine.dispose()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """An HTTP client bound to the ASGI app, with no network in between.

    ASGITransport exercises the real middleware stack and dependency graph, so a
    broken dependency override or a misordered middleware fails here rather than in
    production.
    """
    app = create_app()
    # Storage is faked for the whole suite. A test that silently reached a real
    # bucket would be slow, flaky, and would leave objects behind.
    storage = FakeStorageProvider()
    app.dependency_overrides[get_storage_provider] = lambda: storage

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as ac,
        app.router.lifespan_context(app),
    ):
        yield ac
