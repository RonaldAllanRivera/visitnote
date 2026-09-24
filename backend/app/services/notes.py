"""Reading and correcting a generated note."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.contract import NoteValidationError, validate_sections_structure
from app.llm.templates import SectionSpec, TemplateSpec
from app.models import Note, User
from app.repositories.notes import NoteRepository
from app.schemas.note import (
    NoteFlagRead,
    NoteListItem,
    NoteRead,
    NoteUpdate,
    SectionSpecRead,
    TemplateRead,
)


class NoteNotFoundError(Exception):
    """No such note, or it belongs to someone else.

    One error for both, so a caller cannot probe for note ids they do not own.
    """


class StaleNoteVersionError(Exception):
    """Someone else has written to this note since the client read it."""

    def __init__(self, current_version: int) -> None:
        super().__init__(f"Note has moved on to version {current_version}")
        self.current_version = current_version


class NoteStructureError(Exception):
    """The edit does not fit the template's shape."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _section_spec_read(section: SectionSpec) -> SectionSpecRead:
    return SectionSpecRead(
        key=section.key,
        label=section.label,
        order=section.order,
        description=section.description,
        repeating=section.repeating,
        fields=[_section_spec_read(field) for field in section.fields],
    )


@dataclass(slots=True)
class NoteService:
    session: AsyncSession

    async def get(self, note_id: uuid.UUID, user: User) -> NoteRead:
        note = await NoteRepository(self.session).get_for_user(note_id, user.id)
        if note is None:
            raise NoteNotFoundError
        return self._read(note)

    async def update(self, note_id: uuid.UUID, user: User, payload: NoteUpdate) -> NoteRead:
        notes = NoteRepository(self.session)
        note = await notes.get_for_user(note_id, user.id)
        if note is None:
            raise NoteNotFoundError

        if payload.sections is not None:
            spec = TemplateSpec.from_template(note.template)
            try:
                # Structure only. BANNED_PHRASES is not applied: it governs how the
                # model writes, and a nurse is the author of a clinical record.
                validate_sections_structure(payload.sections, spec)
            except NoteValidationError as exc:
                raise NoteStructureError(str(exc)) from exc

        applied = await notes.update_if_current(
            note=note,
            expected_version=payload.version,
            visit_details=payload.visit_details,
            sections=payload.sections,
        )
        if not applied:
            fresh = await notes.get_for_user(note_id, user.id)
            assert fresh is not None  # it existed a moment ago and nothing deletes notes here
            raise StaleNoteVersionError(fresh.version)

        # `notes.update_if_current` refreshed `note` in place after its bulk UPDATE,
        # since the session's identity map is not otherwise notified of a Core-level
        # write. Serialising that same object -- rather than re-reading -- is what
        # keeps the response in sync with what the database now holds.
        return self._read(note)

    async def list(self, user: User) -> list[NoteListItem]:
        notes = await NoteRepository(self.session).recent_for_user(user.id)
        counts = await NoteRepository(self.session).flag_counts([note.id for note in notes])
        return [
            NoteListItem(
                id=note.id,
                visit_id=note.visit_id,
                format=note.format,
                # Read from the note's own header rather than joined from the visit:
                # this is the label as it was written into the note, which is what a
                # reader is looking for when scanning the list.
                client_label=note.visit_details.get("client_label"),
                visit_date=note.visit_details.get("visit_date"),
                edited=note.edited,
                signed_at=note.signed_at,
                flag_counts=counts.get(note.id, {}),
            )
            for note in notes
        ]

    def _read(self, note: Note) -> NoteRead:
        spec = TemplateSpec.from_template(note.template)
        return NoteRead(
            id=note.id,
            visit_id=note.visit_id,
            format=note.format,
            version=note.version,
            edited=note.edited,
            review_status=note.review_status,
            signed_at=note.signed_at,
            visit_details=dict(note.visit_details),
            sections=dict(note.sections),
            flags=[NoteFlagRead(**flag) for flag in note.flags],
            template=TemplateRead(
                jurisdiction=spec.jurisdiction,
                format=spec.format,
                version=spec.version,
                name=spec.name,
                sections=[_section_spec_read(section) for section in spec.sections],
            ),
        )
