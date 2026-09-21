"""Note persistence.

The single place where a generated note becomes rows. Both writes -- the note's own
flag payload and the normalized `note_flags` rows -- happen here, in one transaction,
because they are two representations of one fact and there is no correct state in
which only one of them exists.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.contract import GeneratedNote
from app.llm.templates import TemplateSpec
from app.models import Note, NoteFlag, Transcript, Visit
from app.transcription import Transcription


@dataclass(slots=True)
class NoteRepository:
    session: AsyncSession

    async def create_for_visit(
        self, *, visit: Visit, spec: TemplateSpec, generated: GeneratedNote
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
