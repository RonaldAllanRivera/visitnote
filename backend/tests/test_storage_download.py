"""Fetching audio back out of object storage.

Uploads go straight from the client to the bucket and never touch the API. Downloads
are the opposite: the worker has to hold the bytes to run ffmpeg over them, so this
is the one direction where the application reads the object itself.
"""

from pathlib import Path

import pytest

from app.storage import FakeStorageProvider, ObjectNotFoundError


async def test_a_stored_object_is_written_to_the_destination(tmp_path: Path) -> None:
    storage = FakeStorageProvider()
    storage.objects["audio/visit-1"] = b"pretend-this-is-audio"
    destination = tmp_path / "downloaded.webm"

    await storage.download("audio/visit-1", destination)

    assert destination.read_bytes() == b"pretend-this-is-audio"


async def test_a_missing_object_raises_rather_than_writing_an_empty_file(
    tmp_path: Path,
) -> None:
    """An empty file would reach ffmpeg and fail there, blaming the wrong stage."""
    storage = FakeStorageProvider()
    destination = tmp_path / "downloaded.webm"

    with pytest.raises(ObjectNotFoundError):
        await storage.download("audio/never-uploaded", destination)

    assert not destination.exists()
