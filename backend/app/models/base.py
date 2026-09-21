"""Declarative base and shared column conventions.

Two things are enforced here rather than left to each model:

1. Every `datetime` maps to TIMESTAMPTZ. SQLAlchemy's default is a naive TIMESTAMP,
   which would silently discard timezone information on the way into the database --
   the exact failure the time rules exist to prevent.
2. Naming conventions for constraints and indexes, so Alembic autogenerate produces
   stable names instead of database-assigned ones that differ between environments
   and make migrations unreviewable.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Reusable column types. `UtcDateTime` is the mypy-visible spelling of the UTC rule:
# a reviewer can see at the column definition that the value is timezone-aware.
UtcDateTime = Annotated[datetime, mapped_column(DateTime(timezone=True))]
Json = Annotated[dict[str, Any], mapped_column(JSONB)]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: JSONB,
        uuid.UUID: UUID(as_uuid=True),
    }


class UUIDPrimaryKey:
    """UUID primary keys, generated in the database.

    UUIDs rather than serial integers because identifiers appear in URLs and audit
    logs; a sequential id leaks how many notes an agency has written and lets one
    tenant guess another's resource ids.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


class Timestamped:
    """created_at / updated_at maintained by the database, not the application.

    Defaulted server-side so a row written by a migration, the seed CLI, or a direct
    SQL fix carries the same guarantees as one written through the ORM.
    """

    created_at: Mapped[UtcDateTime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[UtcDateTime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
