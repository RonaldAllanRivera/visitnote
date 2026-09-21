"""Visit request and response models."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CaptureMode, Jurisdiction, NoteFormat, VisitStatus


class VisitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    capture_mode: CaptureMode

    # Client-generated, so a retry over a dropped connection resolves to the visit
    # that already exists instead of creating a second one.
    idempotency_key: str = Field(min_length=8, max_length=64)

    # Omitted means "use my default", set at onboarding from the user's role.
    note_format: NoteFormat | None = None

    consent_acknowledged: bool = False

    @model_validator(mode="after")
    def _live_audio_requires_consent(self) -> "VisitCreate":
        """Refuse to open a live recording without an acknowledgment.

        Enforced server side rather than trusted to the client, because the client is
        the part an attacker -- or a rushed patch -- can change.
        """
        if self.capture_mode is CaptureMode.LIVE_AUDIO and not self.consent_acknowledged:
            raise ValueError("live_audio capture requires consent_acknowledged")
        return self


class VisitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    jurisdiction: Jurisdiction
    note_format: NoteFormat
    capture_mode: CaptureMode
    status: VisitStatus
    timezone: str
    duration_seconds: int | None
    audio_key: str | None
