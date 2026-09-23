"""Authentication request and response models."""

import uuid
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import CaptureMode, Jurisdiction, NoteFormat, RoleTitle

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


class CaptureRestrictionRead(BaseModel):
    """A capture mode this account may not use, and the statute that says so."""

    code: str
    mode: CaptureMode
    message: str


class Capabilities(BaseModel):
    """What this account may do, decided from its jurisdiction.

    Published so the client can stop offering what the server will refuse. It is not
    the enforcement: every rule here is checked again, against the user's current row,
    on the request that depends on it. That matters because these limits change
    without a new session -- a jurisdiction switch takes effect on the next request,
    and a capability minted into a bearer token would outlive the switch that revoked
    it.
    """

    allowed_capture_modes: list[CaptureMode]
    capture_restriction: CaptureRestrictionRead | None
    # What this jurisdiction actually seeds templates for, read from note_templates
    # rather than listed here, so a new template row is a new option with no release.
    available_formats: list[NoteFormat]


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
    capabilities: Capabilities


# Role alone cannot pick a format once there are two jurisdictions: an RN on a Manila
# ward charts FDAR, an RN doing US home health charts SOAPIE. Keyed on both, so a
# missing pair is a KeyError at import-time review rather than a silent wrong default.
_DEFAULT_FORMAT: dict[tuple[Jurisdiction, RoleTitle], NoteFormat] = {
    (Jurisdiction.US, RoleTitle.CAREGIVER): NoteFormat.SHIFT_NOTE,
    (Jurisdiction.US, RoleTitle.HHA): NoteFormat.SHIFT_NOTE,
    (Jurisdiction.US, RoleTitle.CNA): NoteFormat.SHIFT_NOTE,
    (Jurisdiction.US, RoleTitle.LPN): NoteFormat.SOAPIE,
    (Jurisdiction.US, RoleTitle.RN): NoteFormat.SOAPIE,
    (Jurisdiction.US, RoleTitle.OTHER): NoteFormat.SHIFT_NOTE,
    # PH ships no shift_note template -- the PH market is hospital bedside nursing,
    # not home care -- so every PH role lands on a clinical format.
    (Jurisdiction.PH, RoleTitle.CAREGIVER): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.HHA): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.CNA): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.LPN): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.RN): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.OTHER): NoteFormat.FDAR,
}


def default_format_for(jurisdiction: Jurisdiction, role: RoleTitle) -> NoteFormat:
    return _DEFAULT_FORMAT[(jurisdiction, role)]


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
