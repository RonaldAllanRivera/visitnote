"""System jobs.

`ping` exists so the queue is verifiable end to end without the pipeline. Enqueue it
and observe the result, and you have proven that the API can reach Redis, that the
worker is consuming, and that results round-trip -- three things that otherwise only
get exercised once real audio arrives, which is a bad time to discover one is broken.

It is also the reference shape for every later job: async, context first, returns
something JSON-serialisable, logs with structured fields.
"""

import logging
from typing import Any

from app.core.time import utcnow

logger = logging.getLogger(__name__)


async def ping(ctx: dict[str, Any]) -> dict[str, str]:
    job_id = str(ctx.get("job_id", "unknown"))
    logger.info("ping", extra={"job_id": job_id})
    return {"pong": utcnow().isoformat(), "job_id": job_id}
