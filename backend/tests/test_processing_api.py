"""Processing status, enqueueing, and the operator job console.

The status endpoint is what the capture screen polls while a note is being written,
so it has to answer usefully during the twenty minutes the work is in flight -- not
only once it is done.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import get_job_queue
from app.jobs.queue import FakeJobQueue
from app.main import create_app
from app.models import ProcessingJob, User, Visit
from app.models.enums import JobStage, JobStatus, VisitStatus
from app.storage import FakeStorageProvider, get_storage_provider

PASSWORD = "a-sufficiently-long-password"
BASE_URL = "http://localhost"


@pytest.fixture
async def queue() -> FakeJobQueue:
    return FakeJobQueue()


@pytest.fixture
async def client(queue: FakeJobQueue):  # type: ignore[no-untyped-def]
    """An app whose queue is a fake, so enqueueing is observable and touches no Redis."""
    app = create_app()
    app.dependency_overrides[get_storage_provider] = lambda: FakeStorageProvider()
    app.dependency_overrides[get_job_queue] = lambda: queue

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as ac,
        app.router.lifespan_context(app),
    ):
        yield ac


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def _account(client: AsyncClient) -> dict[str, str]:
    body = (
        await client.post("/api/v1/auth/register", json={"email": _email(), "password": PASSWORD})
    ).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"role_title": "rn", "timezone": "America/Los_Angeles"},
    )
    return headers


async def _uploaded_visit(client: AsyncClient, headers: dict[str, str]) -> str:
    care_recipient = (
        await client.post("/api/v1/clients", headers=headers, json={"label": "Mrs R"})
    ).json()["id"]
    visit = (
        await client.post(
            "/api/v1/visits",
            headers=headers,
            json={
                "client_id": care_recipient,
                "capture_mode": "spoken_recap",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
    ).json()
    await client.post(
        f"/api/v1/visits/{visit['id']}/upload",
        headers=headers,
        json={"content_type": "audio/webm", "size_bytes": 1024},
    )
    await client.post(
        f"/api/v1/visits/{visit['id']}/upload/complete", headers=headers, json={"parts": []}
    )
    return str(visit["id"])


# -- enqueueing ------------------------------------------------------------


async def test_completing_an_upload_enqueues_processing(
    client: AsyncClient, queue: FakeJobQueue
) -> None:
    headers = await _account(client)

    visit_id = await _uploaded_visit(client, headers)

    assert queue.enqueued == [uuid.UUID(visit_id)]


async def test_a_visit_is_not_enqueued_before_its_upload_completes(
    client: AsyncClient, queue: FakeJobQueue
) -> None:
    """Enqueueing at creation would send the worker after audio that does not exist."""
    headers = await _account(client)
    care_recipient = (
        await client.post("/api/v1/clients", headers=headers, json={"label": "Mrs R"})
    ).json()["id"]

    await client.post(
        "/api/v1/visits",
        headers=headers,
        json={
            "client_id": care_recipient,
            "capture_mode": "spoken_recap",
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert queue.enqueued == []


# -- status ----------------------------------------------------------------


async def test_status_reports_a_queued_visit_as_uploaded(client: AsyncClient) -> None:
    headers = await _account(client)
    visit_id = await _uploaded_visit(client, headers)

    response = await client.get(f"/api/v1/visits/{visit_id}/status", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"


async def test_status_reports_the_stage_once_a_job_exists(
    client: AsyncClient, session: AsyncSession
) -> None:
    """"Transcribing" is a far better answer to "is it stuck" than "processing"."""
    headers = await _account(client)
    visit_id = await _uploaded_visit(client, headers)
    session.add(
        ProcessingJob(
            visit_id=uuid.UUID(visit_id),
            stage=JobStage.TRANSCRIBE,
            status=JobStatus.RUNNING,
            attempts=1,
        )
    )
    await session.commit()

    body = (await client.get(f"/api/v1/visits/{visit_id}/status", headers=headers)).json()

    assert body["stage"] == "transcribe"
    assert body["attempts"] == 1


async def test_status_reports_the_error_of_a_failed_job(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = await _account(client)
    visit_id = await _uploaded_visit(client, headers)
    session.add(
        ProcessingJob(
            visit_id=uuid.UUID(visit_id),
            stage=JobStage.NORMALIZE,
            status=JobStatus.FAILED,
            attempts=3,
            error_message="audio could not be decoded",
        )
    )
    await session.commit()

    body = (await client.get(f"/api/v1/visits/{visit_id}/status", headers=headers)).json()

    assert body["error"] == "audio could not be decoded"


async def test_another_users_visit_status_is_not_found(client: AsyncClient) -> None:
    """404 rather than 403: a stranger must not learn the visit exists."""
    owner = await _account(client)
    visit_id = await _uploaded_visit(client, owner)
    stranger = await _account(client)

    response = await client.get(f"/api/v1/visits/{visit_id}/status", headers=stranger)

    assert response.status_code == 404


# -- the operator console --------------------------------------------------


async def _staff(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    headers = await _account(client)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    user = await session.get(User, uuid.UUID(me["id"]))
    assert user is not None
    user.is_staff = True
    await session.commit()
    return headers


async def test_the_job_console_is_invisible_to_a_normal_user(client: AsyncClient) -> None:
    headers = await _account(client)

    response = await client.get("/api/v1/ops/jobs", headers=headers)

    assert response.status_code == 404


async def test_the_job_console_lists_jobs(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = await _staff(client, session)
    visit_id = await _uploaded_visit(client, headers)
    session.add(
        ProcessingJob(
            visit_id=uuid.UUID(visit_id), stage=JobStage.GENERATE, status=JobStatus.FAILED
        )
    )
    await session.commit()

    body = (await client.get("/api/v1/ops/jobs", headers=headers)).json()

    assert any(job["visit_id"] == visit_id for job in body["items"])


async def test_the_job_console_can_filter_to_failures(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The console exists to find what broke; scrolling past successes defeats it."""
    headers = await _staff(client, session)
    failed_visit = await _uploaded_visit(client, headers)
    succeeded_visit = await _uploaded_visit(client, headers)
    session.add_all(
        [
            ProcessingJob(
                visit_id=uuid.UUID(failed_visit),
                stage=JobStage.GENERATE,
                status=JobStatus.FAILED,
            ),
            ProcessingJob(
                visit_id=uuid.UUID(succeeded_visit),
                stage=JobStage.COMPLETE,
                status=JobStatus.SUCCEEDED,
            ),
        ]
    )
    await session.commit()

    body = (await client.get("/api/v1/ops/jobs?status=failed", headers=headers)).json()

    returned = {job["visit_id"] for job in body["items"]}
    assert failed_visit in returned
    assert succeeded_visit not in returned


async def test_retrying_a_job_requeues_it(
    client: AsyncClient, session: AsyncSession, queue: FakeJobQueue
) -> None:
    headers = await _staff(client, session)
    visit_id = await _uploaded_visit(client, headers)
    session.add(
        ProcessingJob(
            visit_id=uuid.UUID(visit_id),
            stage=JobStage.GENERATE,
            status=JobStatus.FAILED,
            attempts=3,
        )
    )
    await session.commit()
    queue.enqueued.clear()

    response = await client.post(f"/api/v1/ops/jobs/{visit_id}/retry", headers=headers)

    assert response.status_code == 202
    assert queue.enqueued == [uuid.UUID(visit_id)]


async def test_a_retry_returns_the_visit_to_a_processable_state(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = await _staff(client, session)
    visit_id = await _uploaded_visit(client, headers)
    visit = await session.get(Visit, uuid.UUID(visit_id))
    assert visit is not None
    visit.status = VisitStatus.FAILED
    session.add(
        ProcessingJob(
            visit_id=uuid.UUID(visit_id), stage=JobStage.GENERATE, status=JobStatus.FAILED
        )
    )
    await session.commit()

    await client.post(f"/api/v1/ops/jobs/{visit_id}/retry", headers=headers)

    refreshed = (
        await session.execute(select(Visit).where(Visit.id == uuid.UUID(visit_id)))
    ).scalar_one()
    await session.refresh(refreshed)
    assert refreshed.status == VisitStatus.UPLOADED


async def test_a_retry_keeps_the_attempt_history(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Resetting the counter would hide a visit that has now failed six times."""
    headers = await _staff(client, session)
    visit_id = await _uploaded_visit(client, headers)
    session.add(
        ProcessingJob(
            visit_id=uuid.UUID(visit_id),
            stage=JobStage.GENERATE,
            status=JobStatus.FAILED,
            attempts=3,
        )
    )
    await session.commit()

    await client.post(f"/api/v1/ops/jobs/{visit_id}/retry", headers=headers)

    job = (
        await session.execute(
            select(ProcessingJob).where(ProcessingJob.visit_id == uuid.UUID(visit_id))
        )
    ).scalar_one()
    await session.refresh(job)
    assert job.attempts == 3


async def test_retrying_an_unknown_job_is_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = await _staff(client, session)

    response = await client.post(f"/api/v1/ops/jobs/{uuid.uuid4()}/retry", headers=headers)

    assert response.status_code == 404
