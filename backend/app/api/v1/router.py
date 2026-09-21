"""Aggregate router for API v1.

Versioning at the prefix means a v2 can exist beside v1 rather than replacing it --
which matters once a released mobile client exists that cannot be forced to upgrade.

Phase 1 registers no versioned routes yet; `/healthz` is mounted at the application
root because infrastructure probes it and should not have to track an API version.
"""

from fastapi import APIRouter

api_router = APIRouter()
