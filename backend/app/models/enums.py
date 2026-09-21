"""Domain enumerations shared by models, schemas, and the LLM layer.

StrEnum rather than Enum so these serialise to readable JSON and compare cleanly
against values arriving from the API, the database, and eval fixtures alike.
"""

from enum import StrEnum


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
