"""Audio normalisation.

Run against real ffmpeg on a real file. A mocked subprocess would assert that we
built a command string, which is not the thing that breaks -- what breaks is the
codec, the sample rate, or a file the decoder rejects.
"""

import asyncio
import shutil
from pathlib import Path

import pytest

from app.audio import AudioDecodeError, normalize, probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


async def _tone(path: Path, seconds: int = 2) -> Path:
    """A synthetic recording, so the test carries no audio fixture."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={seconds}",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.wait()
    return path


async def test_normalisation_produces_mono_audio(tmp_path: Path) -> None:
    """Diarization and transcription both expect one channel."""
    source = await _tone(tmp_path / "source.wav")
    destination = tmp_path / "normalised.wav"

    await normalize(source, destination)

    assert (await probe(destination)).channels == 1


async def test_normalisation_produces_16khz_audio(tmp_path: Path) -> None:
    """16kHz is what speech models want; sending 44.1kHz wastes bandwidth and money."""
    source = await _tone(tmp_path / "source.wav")
    destination = tmp_path / "normalised.wav"

    await normalize(source, destination)

    assert (await probe(destination)).sample_rate == 16_000


async def test_normalisation_reports_the_duration(tmp_path: Path) -> None:
    """Billable audio minutes are computed from this, so it is not incidental."""
    source = await _tone(tmp_path / "source.wav", seconds=2)
    destination = tmp_path / "normalised.wav"

    info = await normalize(source, destination)

    assert info.duration_seconds == pytest.approx(2.0, abs=0.2)


async def test_normalisation_preserves_the_audio_length(tmp_path: Path) -> None:
    source = await _tone(tmp_path / "source.wav", seconds=3)
    destination = tmp_path / "normalised.wav"

    info = await normalize(source, destination)

    assert (await probe(destination)).duration_seconds == pytest.approx(
        info.duration_seconds, abs=0.1
    )


async def test_a_file_that_is_not_audio_fails_loudly(tmp_path: Path) -> None:
    """An upload that is not audio must fail here, not silently transcribe to nothing."""
    source = tmp_path / "not-audio.wav"
    source.write_bytes(b"this is not a recording")

    with pytest.raises(AudioDecodeError):
        await normalize(source, tmp_path / "normalised.wav")


async def test_probing_a_file_that_is_not_audio_fails_loudly(tmp_path: Path) -> None:
    source = tmp_path / "not-audio.wav"
    source.write_bytes(b"still not a recording")

    with pytest.raises(AudioDecodeError):
        await probe(source)
