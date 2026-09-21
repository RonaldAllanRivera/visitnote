"""The pipeline's own record of what it did to a visit.

One row per visit, updated as the pipeline advances, rather than one row per attempt.
The operator console needs to answer "what is stuck and why", and a table that grows
a row per retry answers that worse, not better.

Cost lives here rather than on the note because it is a property of the work, not of
the document: a note that took two transcription attempts and a repair retry cost
more than an identical note that did not, and margin is only visible if that is
recorded.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPrimaryKey
from app.models.enums import JobStage, JobStatus


def _enum(enum_type: type, name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


class ProcessingJob(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        # /ops/jobs lists failures newest first; this is the query it runs.
        Index("ix_processing_jobs_status_created_at", "status", "created_at"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Which step the job reached. On a failure this is the most useful single field
    # in the table: "failed at transcription" and "failed at generation" are
    # different incidents with different fixes.
    stage: Mapped[JobStage] = mapped_column(
        _enum(JobStage, "job_stage"), nullable=False, default=JobStage.QUEUED
    )
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), nullable=False, default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Numeric, not float. These are money and billable minutes; binary floating point
    # quietly loses cents, and a margin figure nobody trusts is a margin figure
    # nobody looks at.
    audio_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Links the row to its Langfuse trace, so an operator looking at a failure here
    # can open the spans that produced it.
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<ProcessingJob visit={self.visit_id} {self.stage}/{self.status}>"
