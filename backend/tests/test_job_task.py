"""The arq task wrapping the pipeline.

The task itself contains one decision: whether a failure is worth another attempt.
That decision is what these tests are for -- the pipeline's own behaviour is covered
in test_pipeline.py, and re-testing it through the queue would only make it slower.
"""

import uuid

import pytest
from arq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs import pipeline as task_module
from app.jobs.pipeline import MAX_ATTEMPTS, process_visit
from app.llm.pipeline import PipelineError
from app.models import Client, ProcessingJob, User, Visit
from app.models.enums import CaptureMode, JobStage, JobStatus, NoteFormat, VisitStatus
from app.observability import RecordingTracer


def _ctx(
    session_factory: async_sessionmaker[AsyncSession], job_try: int
) -> dict[str, object]:
    """The slice of arq's context the task actually reads."""
    return {"job_try": job_try, "session_factory": session_factory}


class _FlushingTracer(RecordingTracer):
    def __init__(self) -> None:
        super().__init__(redact_content=True)
        self.flushed = 0

    def flush(self) -> None:
        self.flushed += 1


async def _visit(session: AsyncSession) -> Visit:
    user = User(email=f"{uuid.uuid4().hex}@visitnote-testing.com", timezone="UTC")
    session.add(user)
    await session.flush()
    care_recipient = Client(owner_id=user.id, label="Mrs R")
    session.add(care_recipient)
    await session.flush()
    visit = Visit(
        user_id=user.id,
        client_id=care_recipient.id,
        note_format=NoteFormat.SHIFT_NOTE,
        capture_mode=CaptureMode.SPOKEN_RECAP,
        status=VisitStatus.UPLOADED,
        timezone="UTC",
        idempotency_key=uuid.uuid4().hex,
        audio_key=f"audio/{uuid.uuid4().hex}",
    )
    session.add(visit)
    await session.commit()
    await session.refresh(visit)
    return visit


@pytest.fixture
def tracer(monkeypatch: pytest.MonkeyPatch) -> _FlushingTracer:
    recorder = _FlushingTracer()
    monkeypatch.setattr(task_module, "get_tracer", lambda: recorder)
    return recorder


async def test_a_retryable_failure_is_deferred_for_another_attempt(
    session: AsyncSession,
    tracer: _FlushingTracer,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    visit = await _visit(session)

    async def _fail(self: object, visit_id: uuid.UUID) -> None:
        raise PipelineError("provider timed out", stage=JobStage.TRANSCRIBE, retryable=True)

    monkeypatch.setattr("app.llm.pipeline.Pipeline.run", _fail)

    with pytest.raises(Retry):
        await process_visit(_ctx(session_factory, 1), str(visit.id))


async def test_the_backoff_grows_between_attempts(
    session: AsyncSession,
    tracer: _FlushingTracer,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Retrying a rate-limited provider at the same interval just gets limited again."""
    visit = await _visit(session)

    async def _fail(self: object, visit_id: uuid.UUID) -> None:
        raise PipelineError("provider timed out", stage=JobStage.TRANSCRIBE, retryable=True)

    monkeypatch.setattr("app.llm.pipeline.Pipeline.run", _fail)

    with pytest.raises(Retry) as first:
        await process_visit(_ctx(session_factory, 1), str(visit.id))
    with pytest.raises(Retry) as second:
        await process_visit(_ctx(session_factory, 2), str(visit.id))

    assert second.value.defer_score > first.value.defer_score


async def test_the_last_attempt_gives_up_instead_of_deferring(
    session: AsyncSession,
    tracer: _FlushingTracer,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    visit = await _visit(session)

    async def _fail(self: object, visit_id: uuid.UUID) -> None:
        raise PipelineError("provider timed out", stage=JobStage.TRANSCRIBE, retryable=True)

    monkeypatch.setattr("app.llm.pipeline.Pipeline.run", _fail)

    result = await process_visit(_ctx(session_factory, MAX_ATTEMPTS), str(visit.id))

    assert result["status"] == "failed"


async def test_a_permanent_failure_is_not_retried_at_all(
    session: AsyncSession,
    tracer: _FlushingTracer,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A file that is not audio will not decode on the third attempt either."""
    visit = await _visit(session)

    async def _fail(self: object, visit_id: uuid.UUID) -> None:
        raise PipelineError("not audio", stage=JobStage.NORMALIZE, retryable=False)

    monkeypatch.setattr("app.llm.pipeline.Pipeline.run", _fail)

    result = await process_visit(_ctx(session_factory, 1), str(visit.id))

    assert result["status"] == "failed"
    assert result["stage"] == str(JobStage.NORMALIZE)


async def test_giving_up_does_not_raise_out_of_the_worker(
    session: AsyncSession,
    tracer: _FlushingTracer,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A bad recording is an expected outcome, not an incident to page someone about.

    The failure is already recorded on the job row; letting it escape would make arq
    log a traceback for something the system has handled.
    """
    visit = await _visit(session)

    async def _fail(self: object, visit_id: uuid.UUID) -> None:
        raise PipelineError("not audio", stage=JobStage.NORMALIZE, retryable=False)

    monkeypatch.setattr("app.llm.pipeline.Pipeline.run", _fail)

    result = await process_visit(_ctx(session_factory, 1), str(visit.id))

    assert result["visit_id"] == str(visit.id)


async def test_an_unknown_visit_does_not_crash_the_worker(
    tracer: _FlushingTracer, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A visit deleted between enqueue and execution must not take the worker down."""
    result = await process_visit(_ctx(session_factory, 1), str(uuid.uuid4()))

    assert result["status"] == "failed"


async def test_traces_are_flushed_when_the_job_ends(
    session: AsyncSession,
    tracer: _FlushingTracer,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The worker is long-lived but buffered spans are not; an unflushed span is lost."""
    visit = await _visit(session)

    async def _fail(self: object, visit_id: uuid.UUID) -> None:
        raise PipelineError("not audio", stage=JobStage.NORMALIZE, retryable=False)

    monkeypatch.setattr("app.llm.pipeline.Pipeline.run", _fail)

    await process_visit(_ctx(session_factory, 1), str(visit.id))

    assert tracer.flushed == 1


async def test_the_failure_is_visible_on_the_job_row(
    session: AsyncSession,
    tracer: _FlushingTracer,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """/ops/jobs reads this; a failure only in the worker's logs is invisible there."""
    visit = await _visit(session)

    await process_visit(_ctx(session_factory, 1), str(visit.id))

    job = (
        await session.execute(select(ProcessingJob).where(ProcessingJob.visit_id == visit.id))
    ).scalar_one()
    assert job.status == JobStatus.FAILED
    assert job.error_message
