"""Upload negotiation models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MEGABYTE = 1024 * 1024

# Anything larger is uploaded in parts. Below this a single PUT is simpler and a
# retry costs little; above it, losing the whole transfer to one dropped connection
# is the difference between a re-upload and a lost visit.
MULTIPART_THRESHOLD_BYTES = 8 * MEGABYTE
PART_SIZE_BYTES = 8 * MEGABYTE

# A 90-minute recording at a sensible bitrate is far below this; the ceiling exists
# to stop the bucket being used as general file storage.
MAX_UPLOAD_BYTES = 200 * MEGABYTE

# Formats the browser MediaRecorder and the native recorder actually produce, plus
# the ones users pick when importing an existing file.
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/aac",
    }
)


class UploadBegin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: str = Field(max_length=128)
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)


class PartUrl(BaseModel):
    part_number: int
    url: str


class UploadTicket(BaseModel):
    mode: Literal["single", "multipart"]
    url: str | None = None
    upload_id: str | None = None
    part_size_bytes: int | None = None
    # Required, not defaulted. The API always sends this field -- empty for a single
    # PUT -- and a default would make it optional in the generated client types,
    # forcing every caller to handle an absence that never occurs.
    parts: list[PartUrl]


class PartsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Resume: the client asks for fresh URLs only for the parts it has not finished.
    part_numbers: list[int] = Field(min_length=1, max_length=10_000)


class PartsResponse(BaseModel):
    upload_id: str
    parts: list[PartUrl]


class CompletedPartIn(BaseModel):
    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1, max_length=256)


class UploadComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[CompletedPartIn] = Field(default_factory=list)
