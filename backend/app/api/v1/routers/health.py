"""Liveness and readiness.

`/healthz` exercises both dependencies rather than returning a static 200. A container
that answers "ok" while its database is unreachable is worse than one that is plainly
down: the deploy pipeline polls this endpoint to decide whether a release succeeded,
and orchestration uses it to decide whether to keep routing traffic.

A failure returns 503 with which dependency failed. The endpoint is unauthenticated,
so the error text is deliberately generic -- an exception string can leak a hostname
or a credential.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.redis import get_redis
from app.schemas.health import DependencyHealth, HealthResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

VERSION = "0.1.0"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


async def _check_database(session: AsyncSession) -> DependencyHealth:
    started = time.perf_counter()
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("healthcheck database failed", extra={"error": str(exc)})
        return DependencyHealth(status="error", error="unreachable")
    return DependencyHealth(status="ok", latency_ms=_elapsed_ms(started))


async def _check_redis() -> DependencyHealth:
    started = time.perf_counter()
    client = get_redis()
    try:
        await client.ping()
    except Exception as exc:
        logger.warning("healthcheck redis failed", extra={"error": str(exc)})
        return DependencyHealth(status="error", error="unreachable")
    finally:
        await client.aclose()
    return DependencyHealth(status="ok", latency_ms=_elapsed_ms(started))


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Service health",
    responses={
        # Declared so the 503 appears in the OpenAPI schema. Without it the generated
        # client types the error branch as `never`, and a client written against those
        # types cannot handle a degraded API -- the exact case this endpoint exists for.
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": "One or more dependencies are unreachable.",
        },
    },
)
async def healthz(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    dependencies = {
        "database": await _check_database(session),
        "redis": await _check_redis(),
    }
    healthy = all(dep.status == "ok" for dep in dependencies.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if healthy else "degraded",
        environment=settings.environment,
        version=VERSION,
        dependencies=dependencies,
    )
