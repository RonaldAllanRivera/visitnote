"""Create visits and consent_logs.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTE_FORMAT = postgresql.ENUM("shift_note", "soapie", name="note_format", create_type=False)
CAPTURE_MODE = sa.Enum("live_audio", "spoken_recap", name="capture_mode")
VISIT_STATUS = sa.Enum(
    "recording", "uploaded", "processing", "ready", "signed", "failed", name="visit_status"
)


def upgrade() -> None:
    op.create_table(
        "visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_format", NOTE_FORMAT, nullable=False),
        sa.Column("capture_mode", CAPTURE_MODE, nullable=False),
        sa.Column("status", VISIT_STATUS, nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("visit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shift_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shift_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("audio_key", sa.String(length=512), nullable=True),
        sa.Column("upload_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upload_id", sa.String(length=256), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_visits_user_id_users"), ondelete="CASCADE"),
        # RESTRICT, not CASCADE: deleting a care recipient must never silently destroy
        # signed clinical documentation. The API deactivates instead of deleting.
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("fk_visits_client_id_clients"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_visits")),
        sa.UniqueConstraint("user_id", "idempotency_key", name=op.f("uq_visits_user_id_idempotency_key")),
    )
    op.create_index("ix_visits_user_id_status", "visits", ["user_id", "status"])

    op.create_table(
        "consent_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capture_mode", postgresql.ENUM(name="capture_mode", create_type=False), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], name=op.f("fk_consent_logs_visit_id_visits"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_consent_logs_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_logs")),
    )
    op.create_index(op.f("ix_consent_logs_visit_id"), "consent_logs", ["visit_id"])


def downgrade() -> None:
    op.drop_table("consent_logs")
    op.drop_index("ix_visits_user_id_status", table_name="visits")
    op.drop_table("visits")
    # Enum types outlive the tables that use them unless dropped explicitly.
    VISIT_STATUS.drop(op.get_bind(), checkfirst=True)
    CAPTURE_MODE.drop(op.get_bind(), checkfirst=True)
