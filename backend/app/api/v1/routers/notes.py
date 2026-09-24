"""Note review routes."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.note import (
    NoteConflictResponse,
    NoteListItem,
    NoteNotFoundResponse,
    NoteRead,
    NoteUpdate,
)
from app.services.notes import (
    NoteNotFoundError,
    NoteService,
    NoteStructureError,
    StaleNoteVersionError,
)

router = APIRouter(prefix="/notes", tags=["notes"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")


@router.get("", response_model=list[NoteListItem])
async def list_notes(user: CurrentUser, session: SessionDep) -> list[NoteListItem]:
    return await NoteService(session).list(user)


@router.get("/{note_id}", response_model=NoteRead)
async def read_note(note_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> NoteRead:
    try:
        return await NoteService(session).get(note_id, user)
    except NoteNotFoundError as exc:
        raise _NOT_FOUND from exc


@router.patch(
    "/{note_id}",
    response_model=NoteRead,
    responses={
        # Declared so these reach the generated client types (see health.py for the
        # same pattern). Without it, openapi-typescript has nothing to type the error
        # branch from, and a malformed-body fallback in the client reads as real data
        # instead of the absence of it -- which is exactly what happened to a 409's
        # missing `current_version`.
        status.HTTP_404_NOT_FOUND: {
            "model": NoteNotFoundResponse,
            "description": "No such note, or it belongs to someone else.",
        },
        status.HTTP_409_CONFLICT: {
            "model": NoteConflictResponse,
            "description": "Someone else has written to this note since it was loaded.",
        },
    },
)
async def update_note(
    note_id: uuid.UUID, payload: NoteUpdate, user: CurrentUser, session: SessionDep
) -> NoteRead:
    try:
        return await NoteService(session).update(note_id, user, payload)
    except NoteNotFoundError as exc:
        raise _NOT_FOUND from exc
    except StaleNoteVersionError as exc:
        # The current version and nothing else: the client refetches, so there is one
        # code path that renders a note rather than two that could disagree.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This note was changed somewhere else.",
                "current_version": exc.current_version,
            },
        ) from exc
    except NoteStructureError as exc:
        # HTTP_422_UNPROCESSABLE_ENTITY is deprecated in this Starlette version (and
        # filterwarnings=["error"] turns that deprecation into a test failure).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message
        ) from exc
