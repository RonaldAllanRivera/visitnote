"""Move note_format off the Postgres ENUM.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-21

An ENUM was the right type when formats were a fixed pair. They are now a growing,
data-driven set: ALTER TYPE ... ADD VALUE cannot run inside a transaction block, and a
value can never be removed. Four columns reference the type -- note_templates.format,
users.default_note_format, visits.note_format, and notes.format -- and all four must be
converted before it can be dropped.

Validity is enforced by note_templates -- a format with no template row cannot be
generated -- rather than by the column type.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, nullable)
_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("note_templates", "format", False),
    ("users", "default_note_format", True),
    ("visits", "note_format", False),
    ("notes", "format", False),
)


def upgrade() -> None:
    for table, column, nullable in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length=32),
            existing_type=postgresql.ENUM("shift_note", "soapie", name="note_format"),
            existing_nullable=nullable,
            postgresql_using=f"{column}::text",
        )
    sa.Enum(name="note_format").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Recreate the type and convert back.

    Fails if any row holds a format outside the original pair, which is correct: the
    data would not fit the type being restored.
    """
    note_format = postgresql.ENUM("shift_note", "soapie", name="note_format")
    note_format.create(op.get_bind(), checkfirst=True)
    for table, column, nullable in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=note_format,
            existing_type=sa.String(length=32),
            existing_nullable=nullable,
            postgresql_using=f"{column}::note_format",
        )
