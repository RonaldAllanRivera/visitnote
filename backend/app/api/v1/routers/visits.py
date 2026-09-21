"""Visit routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.models import Visit
from app.repositories.visits import VisitRepository
from app.schemas.upload import (
    PartsRequest,
    PartsResponse,
    UploadBegin,
    UploadComplete,
    UploadTicket,
)
from app.schemas.visit import VisitCreate, VisitRead
from app.services.uploads import (
    UnsupportedContentTypeError,
    UploadService,
    UploadStateError,
)
from app.services.visits import UnknownClientError, VisitService
from app.storage import StorageProvider, get_storage_provider

router = APIRouter(prefix="/visits", tags=["visits"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.post("", response_model=VisitRead, status_code=status.HTTP_201_CREATED)
async def create_visit(
    payload: VisitCreate, user: CurrentUser, session: SessionDep, response: Response
) -> Visit:
    """Open a visit.

    A replayed idempotency key answers 200 with the existing visit rather than 201,
    so a client can tell whether its retry created anything.
    """
    try:
        visit, created = await VisitService(session).create(user, payload)
    except UnknownClientError as exc:
        raise _NOT_FOUND from exc

    if not created:
        response.status_code = status.HTTP_200_OK
    return visit


@router.get("/{visit_id}", response_model=VisitRead)
async def get_visit(visit_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Visit:
    visit = await VisitRepository(session).get_for_user(visit_id, user.id)
    if visit is None:
        raise _NOT_FOUND
    return visit


StorageDep = Annotated[StorageProvider, Depends(get_storage_provider)]


async def _owned_visit(visit_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep) -> Visit:
    visit = await VisitRepository(session).get_for_user(visit_id, user_id)
    if visit is None:
        raise _NOT_FOUND
    return visit


@router.post("/{visit_id}/upload", response_model=UploadTicket)
async def begin_upload(
    visit_id: uuid.UUID,
    payload: UploadBegin,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> UploadTicket:
    """Negotiate an upload.

    Returns a single presigned PUT for a small file, or a multipart upload with one
    URL per part for anything sizeable. Bytes go straight to the bucket; they never
    pass through this API.
    """
    visit = await _owned_visit(visit_id, user.id, session)
    try:
        return await UploadService(session, storage).begin(visit, payload)
    except UnsupportedContentTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported audio content type",
        ) from exc


@router.post("/{visit_id}/upload/parts", response_model=PartsResponse)
async def reissue_parts(
    visit_id: uuid.UUID,
    payload: PartsRequest,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> PartsResponse:
    """Fresh URLs for parts that have not finished, so an interrupted upload resumes."""
    visit = await _owned_visit(visit_id, user.id, session)
    try:
        return await UploadService(session, storage).reissue_parts(visit, payload.part_numbers)
    except UploadStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{visit_id}/upload/complete", response_model=VisitRead)
async def complete_upload(
    visit_id: uuid.UUID,
    payload: UploadComplete,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> Visit:
    visit = await _owned_visit(visit_id, user.id, session)
    try:
        return await UploadService(session, storage).complete(visit, payload)
    except UploadStateError as exc:
        # 422 when the request itself is incomplete, 409 when the visit is in the
        # wrong state for the request. Different problems for the client to fix.
        code = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
            if "part list" in str(exc)
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
