"""Redis connection pool.

Redis is the arq broker and nothing else in this system -- no caching, no sessions.
Persistence is disabled in production because a lost queue is recoverable (jobs are
re-enqueued from `processing_jobs`) and a corrupted append-only file is not.
"""

from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings

_settings = get_settings()

pool = ConnectionPool.from_url(str(_settings.redis_url), decode_responses=True)


def get_redis() -> Redis:
    return Redis(connection_pool=pool)
