"""Reading and correcting a generated note."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.templates import SectionSpec, TemplateSpec
from app.models import Note, User
from app.repositories.notes import NoteRepository
from app.schemas.note import NoteFlagRead, NoteListItem, NoteRead, SectionSpecRead, TemplateRead


class NoteNotFoundError(Exception):
    """No such note, or it belongs to someone else.

    One error for both, so a caller cannot probe for note ids they do not own.
    """


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
