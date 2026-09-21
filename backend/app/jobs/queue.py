"""The job queue, behind a protocol.

Same shape as the storage, transcription and LLM seams. The API's only interaction
with the worker is "process this visit", so that is the entire interface -- and a
fake implementation of it lets the route tests assert that completing an upload
enqueues work, without a Redis round trip or a worker process.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings

logger = logging.getLogger(__name__)

PROCESS_VISIT = "process_visit"


class JobQueue(Protocol):
    async def enqueue_visit_processing(self, visit_id: uuid.UUID) -> None: ...


@dataclass
class FakeJobQueue:
    """Records what would have been enqueued."""

    enqueued: list[uuid.UUID] = field(default_factory=list)

    async def enqueue_visit_processing(self, visit_id: uuid.UUID) -> None:
        self.enqueued.append(visit_id)


class ArqJobQueue:
    """Enqueues onto Redis for the worker to pick up.

    The job id is derived from the visit id, which makes enqueueing idempotent: a
    client that retries `complete-upload` over a dropped connection cannot start the
    same expensive pipeline twice. arq rejects a duplicate job id while the original
    is still queued or running.
    """

    async def enqueue_visit_processing(self, visit_id: uuid.UUID) -> None:
        settings = get_settings()
        pool = await create_pool(RedisSettings.from_dsn(str(settings.redis_url)))
        try:
            job = await pool.enqueue_job(
                PROCESS_VISIT, str(visit_id), _job_id=f"{PROCESS_VISIT}:{visit_id}"
            )
            if job is None:
                logger.info(
                    "visit is already queued; not enqueued again",
                    extra={"visit_id": str(visit_id)},
                )
        finally:
            await pool.aclose()
