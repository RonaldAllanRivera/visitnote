"""In-memory transcription provider for tests and local development.

Deliberately not a mock. It returns a real, plausible, multi-speaker transcript, so a
pipeline test exercised against it is exercising the pipeline's real behaviour rather
than an expectation about a call.
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.transcription.base import (
    Transcription,
    TranscriptTurn,
    raw_text_from,
    speaker_count_of,
)

# Two speakers by default, because the single-speaker case is the one that hides
# attribution bugs. A fake that never exercises diarization would let a pipeline that
# silently drops speaker labels pass every test.
DEFAULT_TURNS: tuple[TranscriptTurn, ...] = (
    TranscriptTurn(
        speaker_label="speaker_0",
        start_ms=0,
        end_ms=4_000,
        text="Good morning, I'm here for your visit. How did you sleep?",
    ),
    TranscriptTurn(
        speaker_label="speaker_1",
        start_ms=4_000,
        end_ms=9_500,
        text="Not well. My left hip was aching most of the night.",
    ),
    TranscriptTurn(
        speaker_label="speaker_0",
        start_ms=9_500,
        end_ms=14_000,
        text="I'll note that. Blood pressure is 132 over 78 and you ate half your breakfast.",
    ),
)


@dataclass
class FakeTranscriptionProvider:
    turns: list[TranscriptTurn] | tuple[TranscriptTurn, ...] = DEFAULT_TURNS
    confidence: float = 0.94
    model_id: str = "fake-diarized-v1"
    transcribed: list[Path] = field(default_factory=list)

    async def transcribe(self, audio: Path) -> Transcription:
        self.transcribed.append(audio)
        turns = tuple(self.turns)
        return Transcription(
            turns=turns,
            raw_text=raw_text_from(turns),
            speaker_count=speaker_count_of(turns),
            confidence=self.confidence,
            provider="fake",
            model_id=self.model_id,
        )
