"""Transcription provider seam.

Diarization is the part of this that is not optional. Both note formats quote the
patient's own words, and attributing a quote to the wrong speaker is a fabrication --
so the protocol returns ordered speaker turns, and a provider that could only return
a flat string would not satisfy it.
"""

from pathlib import Path

import pytest

from app.transcription import (
    FakeTranscriptionProvider,
    TranscriptTurn,
    get_transcription_provider,
    raw_text_from,
    speaker_count_of,
)


def _turns(*items: tuple[str, str]) -> list[TranscriptTurn]:
    return [
        TranscriptTurn(speaker_label=speaker, start_ms=i * 1000, end_ms=(i + 1) * 1000, text=text)
        for i, (speaker, text) in enumerate(items)
    ]


def test_raw_text_joins_every_turn_in_order() -> None:
    """raw_text is what the fabrication checker greps, so no turn may be dropped."""
    turns = _turns(("speaker_0", "How are you today?"), ("speaker_1", "My hip hurts."))

    assert raw_text_from(turns) == "How are you today? My hip hurts."


def test_speaker_count_counts_distinct_labels() -> None:
    turns = _turns(
        ("speaker_0", "Good morning."),
        ("speaker_1", "Morning."),
        ("speaker_0", "Did you sleep?"),
    )

    assert speaker_count_of(turns) == 2


async def test_fake_provider_returns_more_than_one_speaker(tmp_path: Path) -> None:
    audio = tmp_path / "visit.wav"
    audio.write_bytes(b"not really audio")

    result = await FakeTranscriptionProvider().transcribe(audio)

    assert result.speaker_count >= 2
    assert len({turn.speaker_label for turn in result.turns}) == result.speaker_count


async def test_fake_provider_can_be_scripted_with_specific_turns(tmp_path: Path) -> None:
    """Pipeline tests need to control what was said; that is the whole point of a fake."""
    audio = tmp_path / "visit.wav"
    audio.write_bytes(b"not really audio")
    scripted = _turns(("speaker_0", "Blood pressure 130 over 80."))

    result = await FakeTranscriptionProvider(turns=scripted).transcribe(audio)

    assert result.raw_text == "Blood pressure 130 over 80."
    assert result.speaker_count == 1


async def test_fake_provider_reports_its_own_model_id(tmp_path: Path) -> None:
    """Every transcript records what produced it, fakes included."""
    audio = tmp_path / "visit.wav"
    audio.write_bytes(b"not really audio")

    result = await FakeTranscriptionProvider().transcribe(audio)

    assert result.provider == "fake"
    assert result.model_id


def test_provider_selection_falls_back_to_the_fake_without_credentials() -> None:
    """Local development has no Deepgram key and must still run the pipeline."""
    get_transcription_provider.cache_clear()

    assert isinstance(get_transcription_provider(), FakeTranscriptionProvider)

    get_transcription_provider.cache_clear()


def test_provider_selection_refuses_to_start_production_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently transcribing production audio with a fake would be a data-loss bug."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    get_transcription_provider.cache_clear()

    with pytest.raises(RuntimeError, match="transcription is not configured"):
        get_transcription_provider()

    get_transcription_provider.cache_clear()


def test_provider_selection_uses_deepgram_when_a_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings
    from app.transcription.deepgram import DeepgramProvider

    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg-test-key")
    get_transcription_provider.cache_clear()

    assert isinstance(get_transcription_provider(), DeepgramProvider)

    get_transcription_provider.cache_clear()
