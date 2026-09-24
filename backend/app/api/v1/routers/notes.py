"""Note review routes."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.note import NoteListItem, NoteRead
from app.services.notes import NoteNotFoundError, NoteService

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
