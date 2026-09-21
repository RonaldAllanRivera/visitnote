"""Processing job bookkeeping.

One row per visit, advanced through its stages rather than replaced. Every
transition commits, because the row's whole purpose is to be readable from another
process while the work is still running -- a status that is only written at the end
tells the operator console nothing during the twenty minutes it would most like to
know something.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.providers import LLMUsage
from app.models import ProcessingJob, Visit
from app.models.enums import JobStage, JobStatus, VisitStatus


@dataclass(slots=True)
class ProcessingJobRepository:
    session: AsyncSession

    async def get_for_visit(self, visit_id: uuid.UUID) -> ProcessingJob | None:
        return (
            await self.session.execute(
                select(ProcessingJob).where(ProcessingJob.visit_id == visit_id)
            )
        ).scalar_one_or_none()

    async def get_or_create(self, visit: Visit) -> ProcessingJob:
        existing = await self.get_for_visit(visit.id)
        if existing is not None:
            return existing

        job = ProcessingJob(visit_id=visit.id)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def mark_running(
        self, job: ProcessingJob, visit: Visit, *, trace_id: str
    ) -> ProcessingJob:
        job.attempts += 1
        job.status = JobStatus.RUNNING
        job.stage = JobStage.DOWNLOAD
        # Cleared so a retry does not display the previous attempt's error next to a
        # job that is currently running.
        job.error_message = None
        job.trace_id = trace_id
        visit.status = VisitStatus.PROCESSING
        await self.session.commit()
        return job

    async def mark_failed(
        self, job: ProcessingJob, visit: Visit, *, stage: JobStage, error: str
    ) -> ProcessingJob:
        job.status = JobStatus.FAILED
        job.stage = stage
        job.error_message = error
        visit.status = VisitStatus.FAILED
        await self.session.commit()
        return job

    async def mark_succeeded(
        self,
        job: ProcessingJob,
        visit: Visit,
        *,
        audio_minutes: Decimal,
        usage: LLMUsage,
        cost_usd: Decimal | None,
        repaired: bool,
    ) -> ProcessingJob:
        job.status = JobStatus.SUCCEEDED
        job.stage = JobStage.COMPLETE
        job.audio_minutes = audio_minutes
        job.input_tokens = usage.input_tokens
        job.output_tokens = usage.output_tokens
        job.latency_ms = usage.latency_ms
        job.cost_usd = cost_usd
        job.error_message = None
        visit.status = VisitStatus.READY
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def reset_for_retry(self, job: ProcessingJob, visit: Visit) -> ProcessingJob:
        """Put a failed job back in the queue, as /ops/jobs does.

        The attempt counter is deliberately *not* cleared: an operator retry is a
        further attempt at the same work, and losing that history would hide a visit
        that has now failed six times.
        """
        job.status = JobStatus.QUEUED
        job.stage = JobStage.QUEUED
        visit.status = VisitStatus.UPLOADED
        await self.session.commit()
        await self.session.refresh(job)
        return job
