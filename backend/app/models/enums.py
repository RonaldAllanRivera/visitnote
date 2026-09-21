"""Domain enumerations shared by models, schemas, and the LLM layer.

StrEnum rather than Enum so these serialise to readable JSON and compare cleanly
against values arriving from the API, the database, and eval fixtures alike.
"""

from enum import StrEnum

from sqlalchemy import Enum


class NoteFormat(StrEnum):
    SHIFT_NOTE = "shift_note"
    SOAPIE = "soapie"


class FlagSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RoleTitle(StrEnum):
    """What the user does, which sets their default note format at onboarding."""

    CAREGIVER = "caregiver"
    HHA = "hha"
    CNA = "cna"
    LPN = "lpn"
    RN = "rn"
    OTHER = "other"


class CaptureMode(StrEnum):
    """How the audio was obtained.

    The distinction is legal, not technical: live_audio records a third party and
    requires their acknowledgment, spoken_recap is the user dictating afterwards and
    records nobody else.
    """

    LIVE_AUDIO = "live_audio"
    SPOKEN_RECAP = "spoken_recap"


class VisitStatus(StrEnum):
    RECORDING = "recording"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    SIGNED = "signed"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    """Where a note sits in an agency's review workflow.

    Separate from the visit's status: a note can be signed by its author and still
    be waiting on a supervisor, and those are different questions.
    """

    UNREVIEWED = "unreviewed"
    NEEDS_CORRECTION = "needs_correction"
    ACCEPTED = "accepted"


class JobStage(StrEnum):
    """How far the pipeline got.

    Recorded because "it failed" is not actionable and "it failed at transcription"
    is: the two failures have different causes, different costs, and different fixes.
    """

    QUEUED = "queued"
    DOWNLOAD = "download"
    NORMALIZE = "normalize"
    TRANSCRIBE = "transcribe"
    GENERATE = "generate"
    PERSIST = "persist"
    COMPLETE = "complete"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Jurisdiction(StrEnum):
    """Which regulatory regime a user, visit, and note template belong to.

    Stored as CHAR(2) with a check constraint rather than a Postgres ENUM, because
    the set grows and ALTER TYPE cannot run inside a transaction block.
    """

    US = "US"
    PH = "PH"


def jurisdiction_column() -> Enum:
    """Jurisdiction as a VARCHAR that still round-trips to the Python enum.

    `native_enum=False` emits VARCHAR instead of a Postgres ENUM; `create_constraint=False`
    leaves the DB-level check to the migration, which owns it. Without this, a bare String
    column typed `Mapped[Jurisdiction]` loads back as `str` and every `is` comparison
    silently fails while `==` still passes.
    """
    return Enum(
        Jurisdiction,
        native_enum=False,
        create_constraint=False,
        length=2,
        values_callable=lambda e: [m.value for m in e],
    )
