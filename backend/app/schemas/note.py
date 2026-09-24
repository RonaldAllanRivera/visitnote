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


class NoteUpdate(BaseModel):
    """A correction to a generated note.

    `extra="forbid"` is a security control rather than tidiness: version, edited,
    review_status, signed_at, format and the provenance fields are not the client's
    to set, and rejecting unknown fields makes a future column client-writable by
    accident impossible to write.
    """

    model_config = ConfigDict(extra="forbid")

    # The version the client loaded. A mismatch means someone else has written since,
    # and the edit is refused rather than applied on top of work it never saw.
    version: int
    # Typed to the shape generation itself produces (str | None per key), not `Any`.
    # `Any` let a client PATCH a non-string value straight into a column that
    # `NoteListItem` later reads as `str | None` -- every subsequent `GET /notes` for
    # that user then raised inside the service. The key set itself is checked in
    # `NoteService.update`, against the same `VISIT_DETAIL_KEYS` generation enforces.
    visit_details: dict[str, str | None] | None = None
    sections: dict[str, SectionValue] | None = None


class NoteConflictDetail(BaseModel):
    """The body of a 409 from `PATCH /notes/{note_id}`: what actually happened."""

    message: str
    current_version: int


class NoteConflictResponse(BaseModel):
    """Declared on the route purely so the 409 reaches the generated client types.

    Without this, openapi-typescript has nothing to type that branch from, and the
    web client is left guessing at the shape of `error.detail` -- which is exactly
    how a malformed-body fallback (`currentVersion: 0`) read as a real version.
    """

    detail: NoteConflictDetail


class NoteNotFoundResponse(BaseModel):
    """The body of a 404 from a note route: no such note, or it belongs to someone else."""

    detail: str


class NoteListItem(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    format: NoteFormat
    client_label: str | None
    visit_date: str | None
    edited: bool
    signed_at: datetime | None
    # Keyed by severity. Absent severities are omitted rather than sent as zero, so
    # the client renders what exists instead of three counters that are mostly noise.
    flag_counts: dict[FlagSeverity, int]
