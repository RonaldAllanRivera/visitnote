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
    NoteFormat,
    RoleTitle,
    VisitStatus,
)
from app.models.note_template import NoteTemplate
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.models.visit import ConsentLog, Visit

__all__ = [
    "Base",
    "CaptureMode",
    "Client",
    "ConsentLog",
    "FlagSeverity",
    "NoteFormat",
    "NoteTemplate",
    "RefreshToken",
    "RoleTitle",
    "User",
    "Visit",
    "VisitStatus",
]
