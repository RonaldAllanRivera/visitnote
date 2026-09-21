"""arq worker.

Runs the same image as the API with a different command. The pipeline lands in phase 4;
phase 1 establishes the process, its Redis connection, and the concurrency ceiling.

`max_jobs` is deliberately low. Audio work is CPU- and I/O-bound -- ffmpeg streams, so
memory is not the constraint -- and the ceiling exists to bound contention with the API
container sharing the same two cores, and to stay inside upstream provider concurrency
limits.

Exactly one worker container runs in production, so cron jobs cannot double-fire.
"""

import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import SessionFactory
from app.core.logging import configure_logging
from app.jobs import ping, process_visit

logger = logging.getLogger(__name__)
settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(settings.log_level)
    # Handed to the jobs through the context rather than imported by them. A pooled
    # asyncpg connection belongs to the event loop that opened it, so the process
    # that owns the loop is the right place to own the factory.
    ctx["session_factory"] = SessionFactory
    logger.info("worker starting", extra={"environment": settings.environment})


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker stopped")


class WorkerSettings:
    # arq refuses to start with an empty registry, which is the correct behaviour:
    # a worker with nothing to do is a misconfiguration, not a valid state.
    functions: ClassVar[list[Any]] = [ping, process_visit]
    cron_jobs: ClassVar[list[Any]] = []       # scheduled jobs land here in phase 6
    redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 2
    job_timeout = 900               # a 90-minute recording must fit inside one attempt
    # Kept in step with app.jobs.pipeline.MAX_ATTEMPTS, which is where the decision
    # to stop retrying is actually taken.
    max_tries = 3
    health_check_interval = 30
