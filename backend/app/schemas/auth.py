"""Authentication request and response models."""

import uuid
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import Jurisdiction, NoteFormat, RoleTitle

# Length beats composition rules. NIST withdrew the character-class requirements
# because they push people toward predictable substitutions; length is what actually
# costs an attacker.
MIN_PASSWORD_LENGTH = 12


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        """Lowercase on the way in, so one address cannot register twice."""
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    # No length floor on login: the rule applies when a password is chosen, and
    # rejecting a short one here would report that it failed policy rather than
    # simply being wrong.
    password: str = Field(max_length=1024)

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    role_title: RoleTitle | None
    default_note_format: NoteFormat | None
    timezone: str
    jurisdiction: Jurisdiction
    is_staff: bool


# Role determines which note format a user gets by default, so they never have to know
# what "SOAPIE" means to start working. Licensed clinicians document under Medicare
# skilled-nursing rules; everyone else writes non-clinical shift notes.
DEFAULT_FORMAT_BY_ROLE: dict[RoleTitle, NoteFormat] = {
    RoleTitle.CAREGIVER: NoteFormat.SHIFT_NOTE,
    RoleTitle.HHA: NoteFormat.SHIFT_NOTE,
    RoleTitle.CNA: NoteFormat.SHIFT_NOTE,
    RoleTitle.LPN: NoteFormat.SOAPIE,
    RoleTitle.RN: NoteFormat.SOAPIE,
    RoleTitle.OTHER: NoteFormat.SHIFT_NOTE,
}


class OnboardingRequest(BaseModel):
    """Partial profile update.

    `extra="forbid"` is a security control, not tidiness: without it a client could
    post is_staff and, if the handler ever grew a loop over the payload, escalate
    privilege. Rejecting unknown fields makes that class of bug impossible to write.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=255)
    role_title: RoleTitle | None = None
    default_note_format: NoteFormat | None = None
    timezone: str | None = Field(default=None, max_length=64)
    jurisdiction: Jurisdiction | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        """Reject an unknown zone at the edge.

        Storing a zone that ZoneInfo cannot resolve means every later render of this
        user's notes raises -- months after the bad value was accepted.
        """
        if value is None:
            return None
        if value not in available_timezones():
            raise ValueError(f"unknown IANA timezone: {value}")
        ZoneInfo(value)
        return value


class GoogleSignInRequest(BaseModel):
    id_token: str = Field(min_length=1, max_length=8192)
