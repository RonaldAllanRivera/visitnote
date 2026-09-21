"""Transcription provider protocol.

The protocol returns **ordered speaker turns**, never a flat string. That is a
product requirement rather than a stylistic one: both note formats quote the
patient's own words, and attributing a quote to the wrong speaker is a fabrication --
the easiest one in the whole system to commit. A provider that cannot diarize cannot
satisfy this interface.

No vendor type escapes this package. The pipeline, the evals, and the tracing layer
see only the dataclasses defined here.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TranscriptTurn:
    """One continuous stretch of speech by one speaker.

    `speaker_label` is the provider's own opaque label (typically "speaker_0"). It
    carries no identity: mapping a label to the recording user is a separate,
    explicitly hedged inference made in the pipeline.
    """

    speaker_label: str
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class Transcription:
    turns: tuple[TranscriptTurn, ...]
    raw_text: str
    speaker_count: int
    confidence: float
    provider: str
    model_id: str


def raw_text_from(turns: list[TranscriptTurn] | tuple[TranscriptTurn, ...]) -> str:
    """The flat rendering kept alongside the turns.

    It exists for display and for the fabrication checker, which asks whether a value
    in the note appears anywhere in what was actually said. Every turn must be
    present, in order, or the checker would reject true statements.
    """
    return " ".join(turn.text.strip() for turn in turns if turn.text.strip())


def speaker_count_of(turns: list[TranscriptTurn] | tuple[TranscriptTurn, ...]) -> int:
    return len({turn.speaker_label for turn in turns})


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio: Path) -> Transcription: ...


@lru_cache
def get_transcription_provider() -> TranscriptionProvider:
    """Resolve the configured transcription backend.

    Mirrors the storage seam: local development without a key falls back to the fake
    so the pipeline is runnable end to end, and production refuses to start rather
    than silently writing invented transcripts into real notes.
    """
    settings = get_settings()

    if not settings.deepgram_api_key:
        if settings.is_production:
            raise RuntimeError("transcription is not configured; set DEEPGRAM_API_KEY")
        logger.warning(
            "transcription is not configured; using the fake provider. "
            "Transcripts will be fixtures, not audio.",
            extra={"environment": settings.environment},
        )
        from app.transcription.fake import FakeTranscriptionProvider

        return FakeTranscriptionProvider()

    from app.transcription.deepgram import DeepgramProvider

    return DeepgramProvider()
