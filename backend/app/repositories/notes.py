"""Note persistence.

The single place where a generated note becomes rows. Both writes -- the note's own
flag payload and the normalized `note_flags` rows -- happen here, in one transaction,
because they are two representations of one fact and there is no correct state in
which only one of them exists.
"""

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.contract import GeneratedNote
from app.llm.templates import TemplateSpec
from app.models import Note, NoteFlag, Transcript, Visit
from app.models.enums import FlagSeverity
from app.transcription import Transcription


@dataclass(slots=True)
class NoteRepository:
    session: AsyncSession

    async def create_for_visit(
        self,
        *,
        visit: Visit,
        spec: TemplateSpec,
        generated: GeneratedNote,
        template_id: uuid.UUID,
    ) -> Note:
        """Write the note and its flag rows together.

        The flag payload is serialised from the same validated objects that produce
        the rows, rather than from the raw model output, so the two cannot disagree
        about a severity the template overrode.
        """
        note = Note(
            visit_id=visit.id,
            user_id=visit.user_id,
            format=spec.format,
            note_template_id=template_id,
            visit_details=dict(generated.visit_details),
            sections=dict(generated.sections),
            flags=[flag.model_dump(mode="json") for flag in generated.flags],
            prompt_version=spec.prompt_version,
            llm_provider=spec.llm_provider,
            model_id=spec.model_id,
        )
        self.session.add(note)

        for flag in generated.flags:
            # `note=note` rather than `note_id=note.id`: SQLAlchemy orders the
            # inserts so the foreign key is satisfied without a manual flush, which
            # keeps both writes inside one unit of work.
            self.session.add(
                NoteFlag(
                    note=note,
                    user_id=visit.user_id,
                    code=flag.code,
                    severity=flag.severity,
                )
            )

        await self.session.commit()
        await self.session.refresh(note)
        return note

    async def get_for_visit(self, visit_id: uuid.UUID) -> Note | None:
        return (
            await self.session.execute(select(Note).where(Note.visit_id == visit_id))
        ).scalar_one_or_none()

    async def get_for_user(self, note_id: uuid.UUID, user_id: uuid.UUID) -> Note | None:
        """One note, scoped to its owner.

        Scoping here rather than in the handler is what keeps a new route from
        forgetting it. A note belonging to someone else is indistinguishable from one
        that does not exist.
        """
        return (
            await self.session.execute(
                select(Note)
                .where(Note.id == note_id, Note.user_id == user_id)
                .options(selectinload(Note.template))
            )
        ).scalar_one_or_none()

    async def update_if_current(
        self,
        *,
        note: Note,
        expected_version: int,
        visit_details: dict[str, Any] | None,
        sections: dict[str, Any] | None,
    ) -> bool:
        """Apply an edit only if nobody has written since the client read.

        The check is a WHERE clause on the UPDATE rather than a read-then-write, so
        two concurrent saves cannot both pass the comparison before either commits.
        """
        values: dict[str, Any] = {
            "version": Note.version + 1,
            "edited": True,
        }
        if visit_details is not None:
            values["visit_details"] = visit_details
        if sections is not None:
            values["sections"] = sections

        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(Note)
                .where(Note.id == note.id, Note.version == expected_version)
                .values(**values),
                # The ORM's default "evaluate" strategy checks the WHERE clause
                # against the *in-memory* object's own attributes, not against what
                # the UPDATE actually matched in the database. When `note` was
                # loaded before a concurrent writer moved the row on, its in-memory
                # version can still equal `expected_version` even though the row no
                # longer does -- so "evaluate" would silently bump `note.version` in
                # place on a failed, zero-row UPDATE. Turning synchronization off
                # makes the explicit refresh below the only source of truth.
                execution_options={"synchronize_session": False},
            ),
        )
        await self.session.commit()
        applied = result.rowcount == 1
        # The bulk UPDATE above is Core-level and, with synchronize_session=False,
        # never touches the session's identity map either way -- `note` still holds
        # whatever it held before this call. Refresh it regardless of outcome:
        # on success that is the new version and sections; on failure it is the
        # version and content someone else actually committed, which is what a 409
        # built from this object needs to report.
        await self.session.refresh(note)
        return applied

    async def recent_for_user(self, user_id: uuid.UUID, limit: int = 50) -> list[Note]:
        """The user's most recent notes.

        Bounded rather than paginated: this list exists so someone can get back to a
        note they just wrote, and past fifty rows a list is the wrong tool. The
        roster with its filters is phase 7.
        """
        return list(
            (
                await self.session.execute(
                    select(Note)
                    .where(Note.user_id == user_id)
                    .order_by(Note.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def flag_counts(
        self, note_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[FlagSeverity, int]]:
        """Flag counts per note, per severity, computed in SQL.

        The API contract promises these aggregations are SQL rather than Python
        loops, and that promise is not keepable against a JSONB array at volume --
        which is the whole reason note_flags exists alongside notes.flags.
        """
        if not note_ids:
            return {}

        rows = (
            await self.session.execute(
                select(NoteFlag.note_id, NoteFlag.severity, func.count())
                .where(NoteFlag.note_id.in_(note_ids))
                .group_by(NoteFlag.note_id, NoteFlag.severity)
            )
        ).all()

        counts: dict[uuid.UUID, dict[FlagSeverity, int]] = {}
        for note_id, severity, count in rows:
            counts.setdefault(note_id, {})[severity] = count
        return counts


@dataclass(slots=True)
class TranscriptRepository:
    session: AsyncSession

    async def replace_for_visit(
        self, *, visit: Visit, transcription: Transcription
    ) -> Transcript:
        """Store the transcript, replacing any transcript from a previous attempt.

        A retry transcribes the audio again; keeping both would leave two candidate
        answers to "what was said", and the note is generated from only one of them.
        """
        existing = (
            await self.session.execute(
                select(Transcript).where(Transcript.visit_id == visit.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            await self.session.delete(existing)
            await self.session.flush()

        transcript = Transcript(
            visit_id=visit.id,
            provider=transcription.provider,
            model_id=transcription.model_id,
            raw_text=transcription.raw_text,
            turns=[
                {
                    "speaker_label": turn.speaker_label,
                    "start_ms": turn.start_ms,
                    "end_ms": turn.end_ms,
                    "text": turn.text,
                }
                for turn in transcription.turns
            ],
            speaker_count=transcription.speaker_count,
            confidence=transcription.confidence,
        )
        self.session.add(transcript)
        await self.session.commit()
        await self.session.refresh(transcript)
        return transcript
