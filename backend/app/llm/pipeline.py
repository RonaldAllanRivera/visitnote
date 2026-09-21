"""The processing pipeline.

Download the audio, normalise it, transcribe it with diarization, generate a note
from the active template, validate it, and persist the note with its flags. One
pipeline serves both note formats: everything format-specific is read from the
`note_templates` row, so a third format is a data change plus a prompt module.

This module contains no arq import and no model identifier. It is a plain async
object with its providers injected, which is what lets the whole thing run in a test
against fakes -- and what lets the eval runner drive the same code the worker runs.
"""

import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.audio import AudioDecodeError, AudioInfo, normalize
from app.core.config import get_settings
from app.llm.contract import GeneratedNote, NoteValidationError, validate_output
from app.llm.costs import compute_cost
from app.llm.prompts import get_prompt, infer_recording_speaker, render_transcript
from app.llm.providers import LLMOutputError, LLMProvider, LLMUsage
from app.llm.templates import TemplateSpec, json_schema_for
from app.models import ProcessingJob, Visit
from app.models.enums import JobStage, VisitStatus
from app.observability import NoOpTracer, Tracer
from app.repositories.jobs import ProcessingJobRepository
from app.repositories.note_templates import NoteTemplateRepository
from app.repositories.notes import NoteRepository, TranscriptRepository
from app.storage import ObjectNotFoundError, StorageProvider
from app.transcription import Transcription, TranscriptionProvider

logger = logging.getLogger(__name__)

# Statuses a visit may be processed from. A visit that already has a note is not one
# of them: reprocessing would overwrite a note the author may already have corrected,
# and a duplicate enqueue must not be able to do that.
PROCESSABLE = frozenset({VisitStatus.UPLOADED, VisitStatus.PROCESSING, VisitStatus.FAILED})

_SECONDS_PER_MINUTE = Decimal(60)


class PipelineError(Exception):
    """A stage failed.

    Carries the stage it failed at, because "processing failed" is not something an
    operator can act on, and `retryable`, because that is what decides whether the
    worker defers and tries again or gives up now. A file that is not audio will not
    decode on the third attempt either; a timeout might.
    """

    def __init__(self, message: str, *, stage: JobStage, retryable: bool) -> None:
        super().__init__(message)
        self.stage = stage
        self.retryable = retryable


@dataclass(slots=True)
class Pipeline:
    session: AsyncSession
    storage: StorageProvider
    transcription: TranscriptionProvider
    llm: LLMProvider
    tracer: Tracer = field(default_factory=NoOpTracer)

    async def run(self, visit_id: uuid.UUID) -> ProcessingJob:
        visit = await self.session.get(Visit, visit_id)
        if visit is None:
            raise PipelineError(
                f"visit {visit_id} does not exist", stage=JobStage.QUEUED, retryable=False
            )

        jobs = ProcessingJobRepository(self.session)
        job = await jobs.get_or_create(visit)

        if visit.status not in PROCESSABLE:
            raise PipelineError(
                f"visit is {visit.status} and will not be reprocessed",
                stage=job.stage,
                retryable=False,
            )
        if visit.audio_key is None:
            raise PipelineError(
                "visit has no audio", stage=JobStage.DOWNLOAD, retryable=False
            )

        trace_id = uuid.uuid4().hex
        await jobs.mark_running(job, visit, trace_id=trace_id)

        try:
            return await self._process(visit=visit, job=job, jobs=jobs, trace_id=trace_id)
        except PipelineError as exc:
            await jobs.mark_failed(job, visit, stage=exc.stage, error=str(exc))
            logger.warning(
                "pipeline failed",
                extra={
                    "visit_id": str(visit.id),
                    "stage": exc.stage,
                    "retryable": exc.retryable,
                    "trace_id": trace_id,
                },
            )
            raise

    async def _process(
        self,
        *,
        visit: Visit,
        job: ProcessingJob,
        jobs: ProcessingJobRepository,
        trace_id: str,
    ) -> ProcessingJob:
        spec = await self._template(visit)

        # A scratch directory per run, removed on the way out whatever happens. The
        # worker's only disk usage, and it must not survive a failure -- an orphaned
        # recording on a small VM is both a disk-space problem and a privacy one.
        with tempfile.TemporaryDirectory(prefix="visitnote-") as scratch:
            directory = Path(scratch)
            source = directory / "source"
            normalised = directory / "normalised.wav"

            await self._download(visit, source, trace_id=trace_id)
            audio = await self._normalize(source, normalised, trace_id=trace_id)
            transcription = await self._transcribe(normalised, trace_id=trace_id, audio=audio)

        # Persisted outside the scratch block: the audio is no longer needed, and
        # holding the directory open across a database write serves nothing.
        await TranscriptRepository(self.session).replace_for_visit(
            visit=visit, transcription=transcription
        )

        generated, usage, repaired = await self._generate(
            spec=spec, transcription=transcription, trace_id=trace_id
        )

        with self.tracer.span("persist", trace_id=trace_id, visit_id=str(visit.id)):
            await NoteRepository(self.session).create_for_visit(
                visit=visit, spec=spec, generated=generated
            )

        settings = get_settings()
        audio_minutes = (
            Decimal(str(round(audio.duration_seconds, 2))) / _SECONDS_PER_MINUTE
        ).quantize(Decimal("0.01"))

        return await jobs.mark_succeeded(
            job,
            visit,
            audio_minutes=audio_minutes,
            usage=usage,
            cost_usd=compute_cost(
                model_id=usage.model_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                audio_minutes=audio_minutes,
                prices=settings.llm_prices,
                transcription_usd_per_minute=settings.transcription_usd_per_minute,
            ),
            repaired=repaired,
        )

    # -- stages ------------------------------------------------------------

    async def _template(self, visit: Visit) -> TemplateSpec:
        template = await NoteTemplateRepository(self.session).get_active(visit.note_format)
        if template is None:
            raise PipelineError(
                f"no active template for {visit.note_format}",
                stage=JobStage.GENERATE,
                retryable=False,
            )
        return TemplateSpec.from_template(template)

    async def _download(self, visit: Visit, destination: Path, *, trace_id: str) -> None:
        assert visit.audio_key is not None  # guarded in run()
        with self.tracer.span(
            "download", trace_id=trace_id, visit_id=str(visit.id)
        ) as span:
            try:
                await self.storage.download(visit.audio_key, destination)
            except ObjectNotFoundError as exc:
                # Not retryable: the object will still be absent in thirty seconds.
                raise PipelineError(
                    f"audio object {visit.audio_key} is missing",
                    stage=JobStage.DOWNLOAD,
                    retryable=False,
                ) from exc
            except Exception as exc:
                raise PipelineError(
                    f"could not download audio: {exc}",
                    stage=JobStage.DOWNLOAD,
                    retryable=True,
                ) from exc
            span.set(bytes_downloaded=destination.stat().st_size)

    async def _normalize(self, source: Path, destination: Path, *, trace_id: str) -> AudioInfo:
        with self.tracer.span("normalize", trace_id=trace_id) as span:
            try:
                audio = await normalize(source, destination)
            except AudioDecodeError as exc:
                raise PipelineError(
                    f"audio could not be decoded: {exc}",
                    stage=JobStage.NORMALIZE,
                    retryable=False,
                ) from exc
            span.set(
                audio_seconds=audio.duration_seconds,
                sample_rate=audio.sample_rate,
                channels=audio.channels,
            )
            return audio

    async def _transcribe(
        self, audio_path: Path, *, trace_id: str, audio: AudioInfo
    ) -> Transcription:
        with self.tracer.span(
            "transcribe", trace_id=trace_id, audio_seconds=audio.duration_seconds
        ) as span:
            try:
                transcription = await self.transcription.transcribe(audio_path)
            except Exception as exc:
                # Transcription failures are usually the provider being unavailable
                # or rate-limiting, both of which a later attempt may survive.
                raise PipelineError(
                    f"transcription failed: {exc}", stage=JobStage.TRANSCRIBE, retryable=True
                ) from exc

            span.set(
                speaker_count=transcription.speaker_count,
                transcript_confidence=transcription.confidence,
                transcription_provider=transcription.provider,
                transcription_model_id=transcription.model_id,
                transcript_text=transcription.raw_text,
            )
            return transcription

    async def _generate(
        self, *, spec: TemplateSpec, transcription: Transcription, trace_id: str
    ) -> tuple[GeneratedNote, LLMUsage, bool]:
        """Generate, validate, and repair once if the output does not conform."""
        prompt = get_prompt(spec.prompt_version)
        schema = json_schema_for(spec)
        recording_speaker = infer_recording_speaker(transcription.turns)
        user_content = render_transcript(
            transcription.turns, recording_speaker=recording_speaker
        )

        with self.tracer.span(
            "generate",
            trace_id=trace_id,
            prompt_version=spec.prompt_version,
            llm_provider=spec.llm_provider,
            model_id=spec.model_id,
            recording_speaker_known=recording_speaker is not None,
        ) as span:
            generated, usage, repaired = await self._generate_with_repair(
                spec=spec, system=prompt.system_prompt, user=user_content, schema=schema
            )
            span.set(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                generation_latency_ms=usage.latency_ms,
                schema_valid=True,
                repair_attempted=repaired,
                flag_codes=[flag.code for flag in generated.flags],
                flag_severities=[flag.severity.value for flag in generated.flags],
                note_sections=generated.sections,
            )
            return generated, usage, repaired

    async def _generate_with_repair(
        self, *, spec: TemplateSpec, system: str, user: str, schema: dict[str, object]
    ) -> tuple[GeneratedNote, LLMUsage, bool]:
        try:
            result = await self.llm.complete_json(
                system=system, user=user, schema=schema, model_id=spec.model_id
            )
        except LLMOutputError as exc:
            # Unusable output with nothing to repair -- the model returned prose, or
            # no content at all. There is no specific instruction to send back, so
            # this goes to the job's retry budget rather than the repair budget.
            raise PipelineError(
                f"generation produced no usable output: {exc}",
                stage=JobStage.GENERATE,
                retryable=True,
            ) from exc

        try:
            return validate_output(result.data, spec), result.usage, False
        except NoteValidationError as first:
            # Bound to a local here on purpose: Python deletes the `as` name at the
            # end of the except block, so reading it below would raise.
            repair_instruction = first.repair_instruction
            logger.info("note failed validation; repairing", extra={"error": str(first)})

        # One repair attempt, carrying the specific defect. A retry that repeats the
        # original request unchanged is just a second chance at the same mistake.
        repair_user = (
            f"{user}\n\nYOUR PREVIOUS RESPONSE WAS REJECTED\n"
            f"{repair_instruction}\n"
            "Return the corrected JSON object. Do not add information that is not in "
            "the transcript to satisfy this correction."
        )
        try:
            repaired_result = await self.llm.complete_json(
                system=system, user=repair_user, schema=schema, model_id=spec.model_id
            )
            return validate_output(repaired_result.data, spec), repaired_result.usage, True
        except (NoteValidationError, LLMOutputError) as exc:
            raise PipelineError(
                f"generation did not conform after a repair attempt: {exc}",
                stage=JobStage.GENERATE,
                retryable=False,
            ) from exc
