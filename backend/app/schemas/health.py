from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "degraded"]


class DependencyHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Status
    environment: str
    version: str
    dependencies: dict[str, DependencyHealth] = Field(default_factory=dict)
