"""Model registry.

Every model must be imported here. Alembic autogenerate only sees what has been
imported into the metadata, and a model missing from this list produces an empty
migration that looks like success.
"""

from app.models.base import Base
from app.models.enums import FlagSeverity, NoteFormat, RoleTitle
from app.models.note_template import NoteTemplate
from app.models.refresh_token import RefreshToken
from app.models.user import User

__all__ = [
    "Base",
    "FlagSeverity",
    "NoteFormat",
    "NoteTemplate",
    "RefreshToken",
    "RoleTitle",
    "User",
]
