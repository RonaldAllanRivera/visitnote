"""Create note_templates.

Revision ID: 0001
Revises:
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "note_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "format",
            sa.Enum("shift_note", "soapie", name="note_format"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("section_schema", postgresql.JSONB(), nullable=False),
        sa.Column("flag_schema", postgresql.JSONB(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_note_templates")),
        sa.UniqueConstraint(
            "format", "version", name=op.f("uq_note_templates_format_version")
        ),
    )
    op.create_index(
        op.f("ix_note_templates_format"), "note_templates", ["format"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_note_templates_format"), table_name="note_templates")
    op.drop_table("note_templates")
    # The enum type is created implicitly with the table but is not dropped with it.
    sa.Enum(name="note_format").drop(op.get_bind(), checkfirst=True)
