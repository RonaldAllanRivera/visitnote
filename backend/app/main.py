"""Application entrypoint.

Assembles the app: logging, middleware, routers, and the lifespan that owns the
database engine and Redis pool. Nothing here contains business logic -- if a rule
belongs to the product rather than to HTTP, it belongs in a service.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.api.v1.routers import health
from app.core.config import Settings, get_settings
from app.core.db import engine
from app.core.logging import configure_logging
from app.core.redis import pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "starting",
        extra={"environment": settings.environment, "version": health.VERSION},
    )
    yield
    # Connections are released explicitly. A container that exits without closing its
    # pool leaves the database holding sessions open until they time out, which on a
    # small managed instance is enough to exhaust the connection limit during a deploy.
    await engine.dispose()
    await pool.aclose()
    logger.info("stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.project_name,
        version=health.VERSION,
        lifespan=lifespan,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    # Order matters: TrustedHost rejects a forged Host header before anything else
    # looks at the request.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    # No cookies anywhere in this system -- the access token travels in the
    # Authorization header, so CORS does not need credentials and CSRF does not apply.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
