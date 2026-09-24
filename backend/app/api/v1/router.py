"""Aggregate router for API v1.

Versioning at the prefix means a v2 can exist beside v1 rather than replacing it --
which matters once a released mobile client exists that cannot be forced to upgrade.

`/healthz` is mounted at the application root rather than here, because
infrastructure probes it and should not have to track an API version.
"""

from fastapi import APIRouter

from app.api.v1.routers import auth, clients, notes, ops, visits

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(clients.router)
api_router.include_router(visits.router)
api_router.include_router(notes.router)
api_router.include_router(ops.router)
