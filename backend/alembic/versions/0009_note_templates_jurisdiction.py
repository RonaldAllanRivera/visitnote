"""Add jurisdiction and diarization to note templates.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21

Jurisdiction is a separate axis from format. Filipino nurses also chart SOAPIE, but PH
SOAPIE must not flag homebound status -- that is one format with two flag schemas,
which (format, version) could not express.

Diarization moves onto the row because it is a property of the note being produced: a
US home visit has several speakers, a PH spoken recap has one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills the two existing US rows, then is dropped so the
    # application must state a jurisdiction explicitly on every insert.
    op.add_column(
        "note_templates",
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="US"),
    )
    op.add_column(
        "note_templates",
        sa.Column("requires_diarization", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_check_constraint(
        "ck_note_templates_jurisdiction", "note_templates", "jurisdiction IN ('US', 'PH')"
    )
    op.alter_column("note_templates", "jurisdiction", server_default=None)
    op.alter_column("note_templates", "requires_diarization", server_default=None)

    op.drop_constraint("uq_note_templates_format_version", "note_templates", type_="unique")
    op.create_unique_constraint(
        "uq_note_templates_jurisdiction_format_version",
        "note_templates",
        ["jurisdiction", "format", "version"],
    )
    op.drop_index("ix_note_templates_format", table_name="note_templates")
    op.create_index(
        "ix_note_templates_jurisdiction_format",
        "note_templates",
        ["jurisdiction", "format"],
    )


def downgrade() -> None:
    op.drop_index("ix_note_templates_jurisdiction_format", table_name="note_templates")
    op.create_index("ix_note_templates_format", "note_templates", ["format"])
    op.drop_constraint(
        "uq_note_templates_jurisdiction_format_version", "note_templates", type_="unique"
    )
    op.create_unique_constraint(
        "uq_note_templates_format_version", "note_templates", ["format", "version"]
    )
    op.drop_constraint("ck_note_templates_jurisdiction", "note_templates", type_="check")
    op.drop_column("note_templates", "requires_diarization")
    op.drop_column("note_templates", "jurisdiction")
