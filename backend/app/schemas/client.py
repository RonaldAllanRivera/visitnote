"""Care recipient request and response models."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_content(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("label cannot be blank")
    return cleaned


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Short on purpose. There is nowhere to record a full name, an address, or a date
    # of birth, because the schema is a control and not just a container.
    label: str = Field(min_length=1, max_length=120)

    _clean = field_validator("label")(_require_content)


class ClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str | None) -> str | None:
        return None if value is None else _require_content(value)


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    is_active: bool
