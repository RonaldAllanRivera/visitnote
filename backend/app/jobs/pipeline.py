"""The arq task that runs the pipeline.

Thin on purpose. Everything that decides what a note says lives in
`app.llm.pipeline`, which has no arq import and can therefore be driven by a test,
by the eval runner, or by a future scheduler without dragging a worker along.

What belongs here, and only here, is the queue's concerns: building the real
providers, owning a session for the duration of the job, and deciding whether a
failure is worth another attempt.
"""

import logging
import uuid
from typing import Any

from arq import Retry

from app.core.db import SessionFactory
from app.llm.pipeline import Pipeline, PipelineError
from app.llm.providers import get_llm_provider
from app.observability import get_tracer
from app.storage import get_storage_provider
from app.transcription import get_transcription_provider

logger = logging.getLogger(__name__)

# Matches `WorkerSettings.max_tries`. Stated here as well because this is where the
# decision to stop is actually made, and a silent disagreement between the two would
# either give up early or retry forever.
MAX_ATTEMPTS = 3

# Exponential, from a base wide enough to outlast a brief provider outage without
# holding a worker slot: 30s, 60s, 120s.
RETRY_BASE_SECONDS = 30


async def process_visit(ctx: dict[str, Any], visit_id: str) -> dict[str, str]:
    """Transcribe a visit's audio and generate its note."""
    identifier = uuid.UUID(visit_id)
    tracer = get_tracer()

    # Taken from the context rather than imported directly. arq's startup hook owns
    # the factory for the worker process, and a pooled asyncpg connection belongs to
    # the event loop that opened it -- so a task that reaches for a module-level
    # factory is one that cannot be driven by anything but the worker.
    factory = ctx.get("session_factory") or SessionFactory

    async with factory() as session:
        pipeline = Pipeline(
            session=session,
            storage=get_storage_provider(),
            transcription=get_transcription_provider(),
            llm=get_llm_provider(),
            tracer=tracer,
        )

        try:
            job = await pipeline.run(identifier)
        except PipelineError as exc:
            attempt = int(ctx.get("job_try", 1))
            if exc.retryable and attempt < MAX_ATTEMPTS:
                # arq re-enqueues with this delay. The job row is already marked
                # failed with the stage and the error, so a visit being retried is
                # visible in /ops/jobs rather than silently in flight.
                defer = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                logger.info(
                    "deferring retry",
                    extra={"visit_id": visit_id, "attempt": attempt, "defer_seconds": defer},
                )
                raise Retry(defer=defer) from exc

            logger.error(
                "giving up on visit",
                extra={
                    "visit_id": visit_id,
                    "stage": exc.stage,
                    "retryable": exc.retryable,
                    "attempt": attempt,
                },
            )
            # Swallowed rather than re-raised: the outcome is recorded on the job
            # row, and arq logging a traceback for an outcome the system has already
            # handled turns an ordinary bad recording into an apparent incident.
            return {"visit_id": visit_id, "status": "failed", "stage": str(exc.stage)}
        finally:
            # Spans are buffered by the backend; a worker that moves straight to the
            # next job can lose the last ones of this one.
            tracer.flush()

        return {"visit_id": visit_id, "status": str(job.status), "stage": str(job.stage)}
