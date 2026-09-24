"""Note read and update models.

The read carries the producing template's section schema because the client renders
from it and contains no format-specific component: a third note format is a seeded
row and a prompt module, never a new screen.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import FlagSeverity, Jurisdiction, NoteFormat, ReviewStatus

# A section is prose, or -- for a repeating group like FDAR's focus entries -- a list
# of entries. Mirrors `app.llm.contract.SectionValue`, which is the shape the pipeline
# validates and stores.
SectionValue = str | list[dict[str, str | None]] | None


class SectionSpecRead(BaseModel):
    key: str
    label: str
    order: int
    description: str
    repeating: bool
    fields: list["SectionSpecRead"]


class TemplateRead(BaseModel):
    jurisdiction: Jurisdiction
    format: NoteFormat
    version: int
    name: str
    sections: list[SectionSpecRead]


class NoteFlagRead(BaseModel):
    code: str
    message: str
    severity: FlagSeverity


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visit_id: uuid.UUID
    format: NoteFormat
    version: int
    edited: bool
    review_status: ReviewStatus
    signed_at: datetime | None
    visit_details: dict[str, Any]
    sections: dict[str, SectionValue]
    flags: list[NoteFlagRead]
    template: TemplateRead
