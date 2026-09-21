"""Model registry.

Every model must be imported here. Alembic autogenerate only sees what has been
imported into the metadata, and a model missing from this list produces an empty
migration that looks like success.
"""

from app.models.base import Base
from app.models.client import Client
from app.models.enums import (
    CaptureMode,
    FlagSeverity,
    JobStage,
    JobStatus,
    NoteFormat,
    ReviewStatus,
    RoleTitle,
    VisitStatus,
)
from app.models.note import Note, NoteFlag, Transcript
from app.models.note_template import NoteTemplate
from app.models.processing_job import ProcessingJob
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.models.visit import ConsentLog, Visit

__all__ = [
    "Base",
    "CaptureMode",
    "Client",
    "ConsentLog",
    "FlagSeverity",
    "JobStage",
    "JobStatus",
    "Note",
    "NoteFlag",
    "NoteFormat",
    "NoteTemplate",
    "ProcessingJob",
    "RefreshToken",
    "ReviewStatus",
    "RoleTitle",
    "Transcript",
    "User",
    "Visit",
    "VisitStatus",
]
