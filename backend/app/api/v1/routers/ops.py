"""Operator console routes.

Staff only, and gated with a 404 rather than a 403: a non-staff user should not
learn that the operator console exists, let alone which paths it occupies.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import SessionDep, StaffUser
from app.core.queue import get_job_queue
from app.jobs.queue import JobQueue
from app.models import ProcessingJob, Visit
from app.models.enums import JobStatus
from app.repositories.jobs import ProcessingJobRepository
from app.schemas.processing import OpsJob, OpsJobPage

router = APIRouter(prefix="/ops", tags=["ops"])

QueueDep = Annotated[JobQueue, Depends(get_job_queue)]


@router.get("/jobs", response_model=OpsJobPage)
async def list_jobs(
    user: StaffUser,
    session: SessionDep,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpsJobPage:
    """Jobs newest first, optionally filtered by status.

    The filter is the reason the console exists: an operator opens it to find what
    broke, and paging through successful jobs to reach the failures would make it
    useless at exactly the moment it is needed.
    """
    conditions = [ProcessingJob.status == job_status] if job_status is not None else []

    total = (
        await session.execute(select(func.count()).select_from(ProcessingJob).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(ProcessingJob)
                .where(*conditions)
                .order_by(ProcessingJob.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return OpsJobPage(items=[OpsJob.model_validate(row) for row in rows], total=total)


@router.post("/jobs/{visit_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(
    visit_id: uuid.UUID, user: StaffUser, session: SessionDep, queue: QueueDep
) -> Response:
    """Put a job back on the queue.

    The attempt counter is not reset. An operator retry is a further attempt at the
    same work, and clearing the history would hide a visit that has now failed six
    times behind a job that looks fresh.
    """
    jobs = ProcessingJobRepository(session)
    job = await jobs.get_for_visit(visit_id)
    visit = await session.get(Visit, visit_id)
    if job is None or visit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    await jobs.reset_for_retry(job, visit)
    await queue.enqueue_visit_processing(visit_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)
