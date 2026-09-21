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
