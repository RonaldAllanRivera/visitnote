"""The processing pipeline, end to end with fake providers.

Real storage bytes, real ffmpeg, fake transcription and fake LLM. That split is
deliberate: the audio path is where a wiring mistake hides, and the provider calls
are where a paid API call would hide. Neither is served by mocking the other.
"""

import asyncio
import shutil
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audio import AudioInfo
from app.llm.pipeline import Pipeline, PipelineError
from app.llm.providers import FakeLLMProvider, LLMOutputError
from app.models import Client, Note, NoteFlag, ProcessingJob, Transcript, User, Visit
from app.models.enums import CaptureMode, JobStage, JobStatus, Jurisdiction, NoteFormat, VisitStatus
from app.observability import RecordingTracer
from app.storage import FakeStorageProvider
from app.transcription import FakeTranscriptionProvider, TranscriptTurn

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

SHIFT_SECTIONS = {
    "shift_details": "Morning shift for Mrs R.",
    "care_provided_adls": "Assisted with washing and dressing.",
    "medications": None,
    "vitals": None,
    "observations": "Ate half of breakfast.",
    "changes_from_baseline": None,
    "incidents": None,
    "tasks_not_completed": None,
    "handover": "Restock incontinence pads.",
}

SOAPIE_SECTIONS = {
    "visit_details": "Skilled nursing visit.",
    "subjective": 'Patient stated "my hip was aching most of the night".',
    "objective": "Blood pressure 132/78.",
    "assessment": "Pain consistent with documented osteoarthritis.",
    "plan": "Reassess pain at next visit.",
    "intervention": "Wound dressing changed; sterile technique required a nurse.",
    "evaluation": "Patient tolerated the dressing change without distress.",
    "homebound_status": "Unable to leave home without a two-person assist.",
    "coordination_of_care": None,
    "medication_review": None,
}


def _details() -> dict[str, str | None]:
    return {
        "client_label": "Mrs R",
        "visit_date": "2026-09-21",
        "start_time": "08:00",
        "end_time": "12:00",
    }


def _generation(sections: dict[str, str | None], flags: list[dict[str, str]]) -> dict[str, object]:
    return {"visit_details": _details(), "sections": sections, "flags": flags}


@pytest.fixture(scope="module")
def audio_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """A real one-second recording, so ffmpeg has something genuine to convert."""
    path = tmp_path_factory.mktemp("audio") / "tone.wav"

    async def _generate() -> None:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "44100", "-ac", "2", str(path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

    asyncio.run(_generate())
    return path.read_bytes()


async def _visit(
    session: AsyncSession,
    note_format: NoteFormat = NoteFormat.SHIFT_NOTE,
    *,
    jurisdiction: Jurisdiction = Jurisdiction.US,
    capture_mode: CaptureMode = CaptureMode.LIVE_AUDIO,
) -> Visit:
    user = User(
        email=f"{uuid.uuid4().hex}@visitnote-testing.com",
        timezone="America/Los_Angeles",
        jurisdiction=jurisdiction,
    )
    session.add(user)
    await session.flush()

    care_recipient = Client(owner_id=user.id, label="Mrs R")
    session.add(care_recipient)
    await session.flush()

    visit = Visit(
        user_id=user.id,
        client_id=care_recipient.id,
        jurisdiction=jurisdiction,
        note_format=note_format,
        capture_mode=capture_mode,
        status=VisitStatus.UPLOADED,
        timezone="America/Los_Angeles",
        idempotency_key=uuid.uuid4().hex,
        audio_key=f"audio/{uuid.uuid4().hex}",
    )
    session.add(visit)
    await session.commit()
    await session.refresh(visit)
    return visit


def _pipeline(
    session: AsyncSession,
    *,
    storage: FakeStorageProvider,
    llm: FakeLLMProvider,
    transcription: FakeTranscriptionProvider | None = None,
    tracer: RecordingTracer | None = None,
) -> Pipeline:
    return Pipeline(
        session=session,
        storage=storage,
        transcription=transcription or FakeTranscriptionProvider(),
        llm=llm,
        tracer=tracer or RecordingTracer(redact_content=True),
    )


async def _stocked_storage(visit: Visit, audio_bytes: bytes) -> FakeStorageProvider:
    storage = FakeStorageProvider()
    assert visit.audio_key is not None
    storage.objects[visit.audio_key] = audio_bytes
    return storage


# -- the happy path --------------------------------------------------------


async def test_a_processed_visit_becomes_ready(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    await session.refresh(visit)
    assert visit.status == VisitStatus.READY


async def test_a_processed_visit_has_a_note(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    note = (
        await session.execute(select(Note).where(Note.visit_id == visit.id))
    ).scalar_one()
    assert note.sections["handover"] == "Restock incontinence pads."


async def test_the_same_pipeline_generates_a_soapie_note(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """One pipeline, both formats. The only difference is which template row it read."""
    visit = await _visit(session, note_format=NoteFormat.SOAPIE)
    llm = FakeLLMProvider(responses=[_generation(SOAPIE_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    note = (
        await session.execute(select(Note).where(Note.visit_id == visit.id))
    ).scalar_one()
    assert note.format == NoteFormat.SOAPIE
    assert note.prompt_version == "soapie_v2"


async def test_the_transcript_is_stored_as_speaker_turns(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    transcript = (
        await session.execute(select(Transcript).where(Transcript.visit_id == visit.id))
    ).scalar_one()
    assert transcript.speaker_count >= 2
    assert transcript.turns[0]["speaker_label"]
    assert transcript.turns[0]["text"]


async def test_flags_are_written_to_both_the_payload_and_the_rows(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(
        responses=[
            _generation(
                SHIFT_SECTIONS,
                [{"code": "MISSING_MEDS", "message": "None stated.", "severity": "warning"}],
            )
        ]
    )

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    note = (await session.execute(select(Note).where(Note.visit_id == visit.id))).scalar_one()
    rows = (
        (await session.execute(select(NoteFlag).where(NoteFlag.note_id == note.id)))
        .scalars()
        .all()
    )
    assert [flag["code"] for flag in note.flags] == [row.code for row in rows]


# -- diarization -------------------------------------------------------------


async def test_the_pipeline_asks_the_provider_to_diarize_when_the_template_requires_it(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """Read off the visit's spec, not hardcoded: every seeded US template requires it."""
    visit = await _visit(session)
    fake = FakeTranscriptionProvider()
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(
        session, storage=await _stocked_storage(visit, audio_bytes), llm=llm, transcription=fake
    ).run(visit.id)

    assert fake.diarize_requests == [True]


async def test_the_transcribe_stage_passes_diarize_through_to_the_provider(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The plumbing between spec.requires_diarization and the provider call, for both
    values. PH templates (requires_diarization=False) are not seeded until Task 8, so
    this drives the stage directly rather than needing a second full visit fixture --
    _transcribe touches only self.transcription and self.tracer, never the database.
    """
    fake = FakeTranscriptionProvider()
    pipeline = _pipeline(
        session, storage=FakeStorageProvider(), llm=FakeLLMProvider(), transcription=fake
    )
    audio_info = AudioInfo(duration_seconds=12.0, sample_rate=16_000, channels=1)
    audio_path = tmp_path / "normalised.wav"
    audio_path.write_bytes(b"not really audio")

    await pipeline._transcribe(audio_path, trace_id="t-true", audio=audio_info, diarize=True)
    await pipeline._transcribe(audio_path, trace_id="t-false", audio=audio_info, diarize=False)

    assert fake.diarize_requests == [True, False]


# -- what the model is shown -----------------------------------------------


async def test_the_model_receives_the_transcript_as_labelled_turns(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """Turn structure is the whole basis for attributing a quote to a speaker."""
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    user_content = llm.calls[0].user
    assert "speaker_0:" in user_content
    assert "speaker_1:" in user_content


async def test_a_dominant_opening_speaker_is_named_as_the_caregiver(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    assert "speaker_0 is the caregiver or nurse" in llm.calls[0].user


async def test_an_ambiguous_transcript_forbids_the_model_from_guessing(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """The multi-speaker case that matters: a family member reporting a symptom."""
    visit = await _visit(session)
    ambiguous = FakeTranscriptionProvider(
        turns=[
            TranscriptTurn(speaker_label="speaker_0", start_ms=0, end_ms=1_000, text="Hello."),
            TranscriptTurn(
                speaker_label="speaker_1",
                start_ms=1_000,
                end_ms=20_000,
                text="She has been complaining about her hip all week, though she says it is fine.",
            ),
        ]
    )
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(
        session,
        storage=await _stocked_storage(visit, audio_bytes),
        llm=llm,
        transcription=ambiguous,
    ).run(visit.id)

    assert "could not be determined" in llm.calls[0].user


async def test_the_model_is_given_the_prompt_for_the_templates_version(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session, note_format=NoteFormat.SOAPIE)
    llm = FakeLLMProvider(responses=[_generation(SOAPIE_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    assert "SOAPIE" in llm.calls[0].system


# -- the repair retry ------------------------------------------------------


async def test_invalid_output_is_repaired_once_and_then_succeeds(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(
        responses=[
            _generation({"observations": "Ate half of breakfast."}, []),  # sections missing
            _generation(SHIFT_SECTIONS, []),
        ]
    )

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    await session.refresh(visit)
    assert len(llm.calls) == 2
    assert visit.status == VisitStatus.READY


async def test_the_repair_turn_tells_the_model_what_was_wrong(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """A retry that repeats the same request is just a second chance at the same error."""
    visit = await _visit(session)
    llm = FakeLLMProvider(
        responses=[
            _generation({"observations": "Ate half of breakfast."}, []),
            _generation(SHIFT_SECTIONS, []),
        ]
    )

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    assert "handover" in llm.calls[1].user


async def test_output_that_is_still_invalid_after_repair_fails_the_job(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    broken = _generation({"observations": "x"}, [])
    llm = FakeLLMProvider(responses=[broken, broken])

    with pytest.raises(PipelineError):
        await _pipeline(
            session, storage=await _stocked_storage(visit, audio_bytes), llm=llm
        ).run(visit.id)

    await session.refresh(visit)
    job = (
        await session.execute(select(ProcessingJob).where(ProcessingJob.visit_id == visit.id))
    ).scalar_one()
    assert visit.status == VisitStatus.FAILED
    assert (job.status, job.stage) == (JobStatus.FAILED, JobStage.GENERATE)


async def test_a_failed_generation_writes_no_note(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """A half-written note is worse than none: it looks like a real clinical record."""
    visit = await _visit(session)
    broken = _generation({"observations": "x"}, [])
    llm = FakeLLMProvider(responses=[broken, broken])

    with pytest.raises(PipelineError):
        await _pipeline(
            session, storage=await _stocked_storage(visit, audio_bytes), llm=llm
        ).run(visit.id)

    notes = (
        (await session.execute(select(Note).where(Note.visit_id == visit.id))).scalars().all()
    )
    assert notes == []


async def test_a_repair_is_not_attempted_for_a_transport_failure(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """Repairing a 500 wastes the budget for repairing actual bad output."""
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[LLMOutputError("model returned prose")])

    with pytest.raises(PipelineError):
        await _pipeline(
            session, storage=await _stocked_storage(visit, audio_bytes), llm=llm
        ).run(visit.id)

    assert len(llm.calls) == 1


# -- failure reporting -----------------------------------------------------


async def test_a_missing_recording_fails_at_the_download_stage(
    session: AsyncSession,
) -> None:
    """"It failed" is not actionable; "it failed at download" is."""
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    with pytest.raises(PipelineError):
        await _pipeline(session, storage=FakeStorageProvider(), llm=llm).run(visit.id)

    job = (
        await session.execute(select(ProcessingJob).where(ProcessingJob.visit_id == visit.id))
    ).scalar_one()
    assert job.stage == JobStage.DOWNLOAD


async def test_a_file_that_is_not_audio_fails_at_the_normalise_stage(
    session: AsyncSession,
) -> None:
    visit = await _visit(session)
    storage = FakeStorageProvider()
    assert visit.audio_key is not None
    storage.objects[visit.audio_key] = b"this is not a recording"
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    with pytest.raises(PipelineError):
        await _pipeline(session, storage=storage, llm=llm).run(visit.id)

    job = (
        await session.execute(select(ProcessingJob).where(ProcessingJob.visit_id == visit.id))
    ).scalar_one()
    assert job.stage == JobStage.NORMALIZE


async def test_a_corrupt_recording_is_not_worth_retrying(
    session: AsyncSession,
) -> None:
    """It will not decode on the third attempt either."""
    visit = await _visit(session)
    storage = FakeStorageProvider()
    assert visit.audio_key is not None
    storage.objects[visit.audio_key] = b"this is not a recording"
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    with pytest.raises(PipelineError) as exc:
        await _pipeline(session, storage=storage, llm=llm).run(visit.id)

    assert exc.value.retryable is False


async def test_the_error_is_recorded_on_the_job(session: AsyncSession) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    with pytest.raises(PipelineError):
        await _pipeline(session, storage=FakeStorageProvider(), llm=llm).run(visit.id)

    job = (
        await session.execute(select(ProcessingJob).where(ProcessingJob.visit_id == visit.id))
    ).scalar_one()
    assert job.error_message


async def test_each_run_counts_as_an_attempt(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """The retry ceiling is enforced against this counter."""
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])
    storage = await _stocked_storage(visit, audio_bytes)

    with pytest.raises(PipelineError):
        await _pipeline(session, storage=FakeStorageProvider(), llm=llm).run(visit.id)
    await _pipeline(session, storage=storage, llm=llm).run(visit.id)

    job = (
        await session.execute(select(ProcessingJob).where(ProcessingJob.visit_id == visit.id))
    ).scalar_one()
    assert job.attempts == 2


# -- cost ------------------------------------------------------------------


async def test_the_job_records_what_the_note_cost(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
        visit.id
    )

    job = (
        await session.execute(select(ProcessingJob).where(ProcessingJob.visit_id == visit.id))
    ).scalar_one()
    assert job.input_tokens and job.input_tokens > 0
    assert job.output_tokens and job.output_tokens > 0
    assert job.audio_minutes is not None and job.audio_minutes > Decimal("0")
    assert job.cost_usd is not None and job.cost_usd > Decimal("0")


# -- tracing ---------------------------------------------------------------


async def test_every_stage_is_traced(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])
    tracer = RecordingTracer(redact_content=True)

    await _pipeline(
        session, storage=await _stocked_storage(visit, audio_bytes), llm=llm, tracer=tracer
    ).run(visit.id)

    assert {"download", "normalize", "transcribe", "generate", "persist"} <= {
        span.name for span in tracer.spans
    }


async def test_a_redacted_trace_still_carries_the_flag_codes(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """Codes are a fixed vocabulary, not patient content -- and they are the signal."""
    visit = await _visit(session)
    llm = FakeLLMProvider(
        responses=[
            _generation(
                SHIFT_SECTIONS,
                [{"code": "MISSING_MEDS", "message": "None stated.", "severity": "warning"}],
            )
        ]
    )
    tracer = RecordingTracer(redact_content=True)

    await _pipeline(
        session, storage=await _stocked_storage(visit, audio_bytes), llm=llm, tracer=tracer
    ).run(visit.id)

    generate = next(span for span in tracer.spans if span.name == "generate")
    assert generate.attributes["flag_codes"] == ["MISSING_MEDS"]


async def test_the_generate_span_carries_the_templates_jurisdiction(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """`TemplateSpec.jurisdiction` is set at `from_template` but otherwise unread --
    `eval_runs.jurisdiction` will want it once the eval phase exists, and a field
    nothing reads is how this project has lost track of a value before."""
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])
    tracer = RecordingTracer(redact_content=True)

    await _pipeline(
        session, storage=await _stocked_storage(visit, audio_bytes), llm=llm, tracer=tracer
    ).run(visit.id)

    generate = next(span for span in tracer.spans if span.name == "generate")
    assert generate.attributes["jurisdiction"] == "US"


async def test_a_redacted_trace_carries_no_transcript_text(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    visit = await _visit(session)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])
    tracer = RecordingTracer(redact_content=True)

    await _pipeline(
        session, storage=await _stocked_storage(visit, audio_bytes), llm=llm, tracer=tracer
    ).run(visit.id)

    for span in tracer.spans:
        assert "transcript_text" not in span.attributes
        assert "note_sections" not in span.attributes


# -- reprocessing ----------------------------------------------------------


async def test_retrying_a_failed_visit_replaces_its_transcript(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """A retry must not leave two candidate answers to "what was said".

    The realistic path: generation failed, so the visit is FAILED but a transcript
    was already written. An operator retry from /ops/jobs transcribes again.
    """
    visit = await _visit(session)
    storage = await _stocked_storage(visit, audio_bytes)
    broken = _generation({"observations": "x"}, [])

    with pytest.raises(PipelineError):
        await _pipeline(
            session, storage=storage, llm=FakeLLMProvider(responses=[broken, broken])
        ).run(visit.id)
    first = (
        await session.execute(select(Transcript).where(Transcript.visit_id == visit.id))
    ).scalar_one()

    await _pipeline(
        session,
        storage=storage,
        llm=FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])]),
    ).run(visit.id)

    transcripts = (
        (await session.execute(select(Transcript).where(Transcript.visit_id == visit.id)))
        .scalars()
        .all()
    )
    assert len(transcripts) == 1
    assert transcripts[0].id != first.id


async def test_a_retry_after_a_failure_produces_a_note(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """The whole point of the retry path: a failed visit can still become a note."""
    visit = await _visit(session)
    storage = await _stocked_storage(visit, audio_bytes)
    broken = _generation({"observations": "x"}, [])

    with pytest.raises(PipelineError):
        await _pipeline(
            session, storage=storage, llm=FakeLLMProvider(responses=[broken, broken])
        ).run(visit.id)
    await _pipeline(
        session,
        storage=storage,
        llm=FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])]),
    ).run(visit.id)

    await session.refresh(visit)
    note = (await session.execute(select(Note).where(Note.visit_id == visit.id))).scalar_one()
    assert visit.status == VisitStatus.READY
    assert note.sections["handover"] == "Restock incontinence pads."


async def test_a_visit_that_is_already_ready_is_not_processed_again(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """A duplicate enqueue must not overwrite a note someone may already have edited."""
    visit = await _visit(session)
    storage = await _stocked_storage(visit, audio_bytes)
    llm = FakeLLMProvider(responses=[_generation(SHIFT_SECTIONS, [])])

    await _pipeline(session, storage=storage, llm=llm).run(visit.id)
    with pytest.raises(PipelineError):
        await _pipeline(session, storage=storage, llm=llm).run(visit.id)

    assert len(llm.calls) == 1


async def test_an_unknown_visit_is_an_error(session: AsyncSession) -> None:
    llm = FakeLLMProvider()

    with pytest.raises(PipelineError):
        await _pipeline(session, storage=FakeStorageProvider(), llm=llm).run(uuid.uuid4())


# -- PH FDAR -----------------------------------------------------------------


async def test_the_pipeline_generates_a_ph_fdar_note_through_the_unscripted_fake(
    session: AsyncSession, audio_bytes: bytes
) -> None:
    """Composes the real seeded PH FDAR row -> TemplateSpec -> json_schema_for ->
    validate_output, end to end through the unscripted fake provider.

    Every other `Visit(...)` in this file is `Jurisdiction.US`; nothing else here
    drives the one format this phase exists to add. An unscripted `FakeLLMProvider`
    (no responses, so it derives its answer from the schema, exactly like
    `docker compose up` with no API key) is used deliberately: a scripted payload
    would hide a fake that cannot itself satisfy FDAR's repeating focus_entries
    section.
    """
    visit = await _visit(
        session,
        NoteFormat.FDAR,
        jurisdiction=Jurisdiction.PH,
        capture_mode=CaptureMode.SPOKEN_RECAP,
    )
    llm = FakeLLMProvider()
    # Read before the try block: `session.rollback()` in `finally` expires `visit`,
    # and an expired attribute's implicit reload is a lazy load SQLAlchemy's async
    # session cannot perform outside an awaited call, so `visit.id` there would raise
    # MissingGreenlet instead of running the cleanup it is needed for.
    visit_id = visit.id

    # This test commits against the real, shared database (see conftest -- there is
    # no per-test rollback or truncation), so the visit and note rows below are
    # durable the moment they are written. `alembic downgrade` past 0011 deliberately
    # refuses while any `visits.note_format='fdar'` or `notes.format='fdar'` row
    # exists (0011's own downgrade), so this is the one test in the file that must
    # clean up after itself -- everything else stays 'shift_note' or 'soapie', which
    # downgrade tolerates. rollback() first clears whatever transaction state the try
    # block left behind, matching the pattern in test_note_templates.py, so the
    # cleanup DELETE always runs in a fresh transaction. Deleting the visit by id
    # (never by format, which would reach every other test's accumulated rows too)
    # cascades to its note, transcript, and processing job.
    try:
        await _pipeline(session, storage=await _stocked_storage(visit, audio_bytes), llm=llm).run(
            visit.id
        )

        await session.refresh(visit)
        assert visit.status == VisitStatus.READY

        note = (await session.execute(select(Note).where(Note.visit_id == visit.id))).scalar_one()
        assert note.format == NoteFormat.FDAR
        assert note.prompt_version == "ph_fdar_v1"

        entries = note.sections["focus_entries"]
        assert isinstance(entries, list) and len(entries) == 2
        for entry in entries:
            assert set(entry) == {"focus", "data", "action", "response"}

        # The other finding this test guards: a PH request's user content must never
        # carry a code PH's flag_schema does not declare, or _normalise_flags would
        # have rejected this run's own generation and this assertion would never run.
        assert "UNATTRIBUTED_STATEMENT" not in llm.calls[0].user
    finally:
        await session.rollback()
        await session.execute(sa.text("DELETE FROM visits WHERE id = :id"), {"id": visit_id})
        await session.commit()
