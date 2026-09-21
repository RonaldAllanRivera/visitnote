"""Audio normalisation with ffmpeg.

Recordings arrive as whatever the browser or the phone produced -- WebM/Opus,
MP4/AAC, stereo, 48kHz. Transcription wants one predictable thing, so everything is
converted to 16kHz mono PCM before it leaves this module.

ffmpeg is invoked as a subprocess rather than through a binding. The binding would
add a compiled dependency to both containers to wrap a tool that already has a
stable command-line interface, and streaming through the subprocess keeps a
90-minute recording off the heap.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# What the transcription providers actually want. Higher rates cost more to upload
# and transcribe without improving speech recognition.
TARGET_SAMPLE_RATE = 16_000
TARGET_CHANNELS = 1

# Generous: this covers a 90-minute recording on a small VM. The job timeout is the
# real ceiling; this exists so a wedged ffmpeg cannot hold a worker slot forever.
FFMPEG_TIMEOUT_SECONDS = 600.0


class AudioDecodeError(Exception):
    """ffmpeg could not read the file as audio.

    A distinct failure from "transcription found no speech". This one means the
    upload is not a recording at all, and no number of retries will change that.
    """


@dataclass(frozen=True, slots=True)
class AudioInfo:
    duration_seconds: float
    sample_rate: int
    channels: int


async def normalize(source: Path, destination: Path) -> AudioInfo:
    """Convert to 16kHz mono PCM, returning what the result turned out to be."""
    await _run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        # Never wait on a prompt: a worker has no terminal to answer it.
        "-y",
        "-i",
        str(source),
        "-ac",
        str(TARGET_CHANNELS),
        "-ar",
        str(TARGET_SAMPLE_RATE),
        # Explicit codec rather than relying on the extension, so the container
        # format cannot quietly change what is sent to the provider.
        "-c:a",
        "pcm_s16le",
        str(destination),
    )
    return await probe(destination)


async def probe(path: Path) -> AudioInfo:
    """Read duration, sample rate and channel count from a file."""
    stdout = await _run(
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-show_entries",
        "stream=sample_rate,channels:format=duration",
        "-select_streams",
        "a:0",
        "-of",
        "json",
        str(path),
    )

    try:
        payload = json.loads(stdout)
        stream = payload["streams"][0]
        return AudioInfo(
            duration_seconds=float(payload["format"]["duration"]),
            sample_rate=int(stream["sample_rate"]),
            channels=int(stream["channels"]),
        )
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as exc:
        raise AudioDecodeError(f"could not read audio properties from {path.name}") from exc


async def _run(*command: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=FFMPEG_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise AudioDecodeError(f"{command[0]} timed out after {FFMPEG_TIMEOUT_SECONDS}s") from exc

    if process.returncode != 0:
        # ffmpeg's own message is the useful part; it names the actual decode
        # failure, which a generic "conversion failed" would throw away.
        raise AudioDecodeError(
            f"{command[0]} exited {process.returncode}: {stderr.decode(errors='replace').strip()}"
        )

    return stdout.decode(errors="replace")
