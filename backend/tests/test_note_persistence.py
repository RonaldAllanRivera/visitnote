"""Persisting a generated note.

The flags are written twice, deliberately: `notes.flags` is the payload the review
editor renders, and `note_flags` is the analytics shape the dashboards aggregate
over. Two copies of the same truth is a bug waiting to happen, so the test that they
never diverge is the point of this file.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.contract import GeneratedFlag, GeneratedNote
from app.llm.templates import TemplateSpec
from app.models import Client, Note, NoteFlag, NoteTemplate, User, Visit
from app.models.enums import (
    CaptureMode,
    FlagSeverity,
    Jurisdiction,
    NoteFormat,
    ReviewStatus,
    VisitStatus,
)
from app.repositories.note_templates import NoteTemplateRepository
from app.repositories.notes import NoteRepository


async def _visit(session: AsyncSession) -> Visit:
    user = User(email=f"{uuid.uuid4().hex}@visitnote-testing.com", timezone="America/Los_Angeles")
    session.add(user)
    await session.flush()

    care_recipient = Client(owner_id=user.id, label="Mrs R")
    session.add(care_recipient)
    await session.flush()

    visit = Visit(
        user_id=user.id,
        client_id=care_recipient.id,
        jurisdiction=Jurisdiction.US,
        note_format=NoteFormat.SHIFT_NOTE,
        capture_mode=CaptureMode.SPOKEN_RECAP,
        status=VisitStatus.PROCESSING,
        timezone="America/Los_Angeles",
        idempotency_key=uuid.uuid4().hex,
    )
    session.add(visit)
    await session.commit()
    await session.refresh(visit)
    return visit


async def _spec(session: AsyncSession) -> tuple[TemplateSpec, uuid.UUID]:
    # Jurisdiction-aware for the same reason NoteTemplateRepository.get_active is:
    # once a PH row exists for this format, `.scalar_one()` filtered on format alone
    # raises MultipleResultsFound instead of picking a row. These fixtures are all
    # US-format notes.
    #
    # Returns the row's id alongside the spec: `create_for_visit` now takes
    # `template_id` explicitly (see `TemplateSpec.from_template`'s docstring on why
    # the id does not live on the spec itself), and every caller here needs both.
    template = (
        await session.execute(
            select(NoteTemplate).where(
                NoteTemplate.jurisdiction == Jurisdiction.US,
                NoteTemplate.format == NoteFormat.SHIFT_NOTE,
            )
        )
    ).scalar_one()
    return TemplateSpec.from_template(template), template.id


def _generated() -> GeneratedNote:
    return GeneratedNote(
        visit_details={
            "client_label": "Mrs R",
            "visit_date": "2026-09-21",
            "start_time": "08:00",
            "end_time": None,
        },
        sections={"observations": "Ate half of lunch.", "handover": None},
        flags=[
            GeneratedFlag(
                code="MISSING_SHIFT_TIMES",
                message="No end time was stated.",
                severity=FlagSeverity.CRITICAL,
            ),
            GeneratedFlag(
                code="MISSING_MEDS",
                message="No medication statement.",
                severity=FlagSeverity.WARNING,
            ),
        ],
    )


@pytest.fixture
async def persisted(session: AsyncSession) -> tuple[Note, Visit]:
    visit = await _visit(session)
    spec, template_id = await _spec(session)
    note = await NoteRepository(session).create_for_visit(
        visit=visit, spec=spec, generated=_generated(), template_id=template_id
    )
    return note, visit


async def test_the_note_carries_the_generated_sections(persisted: tuple[Note, Visit]) -> None:
    note, _ = persisted

    assert note.sections["observations"] == "Ate half of lunch."
    assert note.sections["handover"] is None


async def test_the_flag_payload_and_the_flag_rows_never_diverge(
    persisted: tuple[Note, Visit], session: AsyncSession
) -> None:
    """The promise that the dashboards aggregate the same truth the editor shows."""
    note, _ = persisted

    rows = (
        (await session.execute(select(NoteFlag).where(NoteFlag.note_id == note.id)))
        .scalars()
        .all()
    )

    assert {(row.code, row.severity) for row in rows} == {
        (flag["code"], FlagSeverity(flag["severity"])) for flag in note.flags
    }


async def test_flag_rows_denormalise_the_owner_for_index_locality(
    persisted: tuple[Note, Visit], session: AsyncSession
) -> None:
    """Per-staff analytics must not join through notes and visits to find a user."""
    note, visit = persisted

    rows = (
        (await session.execute(select(NoteFlag).where(NoteFlag.note_id == note.id)))
        .scalars()
        .all()
    )

    assert {row.user_id for row in rows} == {visit.user_id}


async def test_a_new_note_starts_unreviewed_unedited_and_at_version_one(
    persisted: tuple[Note, Visit],
) -> None:
    """Version one is what the first section PATCH will check against."""
    note, _ = persisted

    assert (note.version, note.edited, note.review_status) == (
        1,
        False,
        ReviewStatus.UNREVIEWED,
    )


async def test_the_note_records_what_generated_it(
    persisted: tuple[Note, Visit], session: AsyncSession
) -> None:
    """Provenance: any note must be traceable to an exact prompt, provider and model."""
    note, _ = persisted
    spec, _ = await _spec(session)

    assert (note.prompt_version, note.llm_provider, note.model_id) == (
        spec.prompt_version,
        spec.llm_provider,
        spec.model_id,
    )


async def test_a_note_with_no_flags_writes_no_flag_rows(session: AsyncSession) -> None:
    """A clean note is a real outcome, not an empty edge case to hedge around."""
    visit = await _visit(session)
    spec, template_id = await _spec(session)
    generated = _generated().model_copy(update={"flags": []})

    note = await NoteRepository(session).create_for_visit(
        visit=visit, spec=spec, generated=generated, template_id=template_id
    )

    rows = (
        (await session.execute(select(NoteFlag).where(NoteFlag.note_id == note.id)))
        .scalars()
        .all()
    )
    assert note.flags == []
    assert rows == []


async def test_the_note_records_the_template_that_produced_it(
    session: AsyncSession,
) -> None:
    # Resolving the template at read time would render an old note against a newer
    # template's section_schema the day a second version is seeded.
    visit = await _visit(session)
    template = await NoteTemplateRepository(session).get_active(
        visit.jurisdiction, visit.note_format
    )
    assert template is not None

    note = await NoteRepository(session).create_for_visit(
        visit=visit,
        spec=TemplateSpec.from_template(template),
        generated=_generated(),
        template_id=template.id,
    )

    assert note.note_template_id == template.id
