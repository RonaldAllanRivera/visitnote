"""Processing status and operator job schemas."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import JobStage, JobStatus, VisitStatus


class VisitProcessingStatus(BaseModel):
    """What the capture screen polls while a note is being written.

    `stage` and `attempts` are included because "processing" for twenty minutes is
    indistinguishable from "stuck", and a client that cannot tell the difference
    either worries the user or hides a real failure.
    """

    visit_id: uuid.UUID
    status: VisitStatus
    stage: JobStage | None = None
    job_status: JobStatus | None = None
    attempts: int = 0
    error: str | None = None
    note_id: uuid.UUID | None = None


class OpsJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visit_id: uuid.UUID
    stage: JobStage
    status: JobStatus
    attempts: int
    error_message: str | None
    audio_minutes: Decimal | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    latency_ms: int | None
    trace_id: str | None
    created_at: datetime
    updated_at: datetime


class OpsJobPage(BaseModel):
    items: list[OpsJob]
    total: int
