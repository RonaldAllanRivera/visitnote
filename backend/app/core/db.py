"""Database engine and session management.

The session is handed out by dependency injection and nothing else. Routers never
construct one; repositories receive one. That constraint is what keeps transaction
boundaries visible at the edge of a request instead of scattered through call sites.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.sqlalchemy_url,
    echo=_settings.db_echo,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,  # managed Postgres closes idle connections without warning
)

SessionFactory = async_sessionmaker(
    engine,
    expire_on_commit=False,  # let response serialisation read attributes after commit
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding one session per request.

    Commit is the caller's decision; rollback on exception is not. A handler that
    raises must never leave a partial write behind.
    """
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
