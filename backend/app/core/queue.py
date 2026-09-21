"""Job queue dependency.

Separate from `app.jobs.queue` so that importing the dependency does not pull the
worker's job modules into the API process, and so the FastAPI override used by tests
has an obvious, single place to hook.
"""

import logging
from functools import lru_cache

from app.core.config import get_settings
from app.jobs.queue import ArqJobQueue, FakeJobQueue, JobQueue

logger = logging.getLogger(__name__)


@lru_cache
def get_job_queue() -> JobQueue:
    """Resolve the queue backend.

    Unlike the storage and provider seams there is no credential to check: Redis is
    always configured, because the application does not start without it. The fake
    exists for tests, which override this dependency rather than reaching Redis.
    """
    settings = get_settings()
    if settings.environment == "ci" and not settings.redis_url:  # pragma: no cover
        logger.warning("no Redis configured; jobs will be discarded")
        return FakeJobQueue()
    return ArqJobQueue()
