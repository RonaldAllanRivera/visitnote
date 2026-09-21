"""Transcripts, notes, note_flags and processing_jobs.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-21

Hand-written rather than left as autogenerate produced it. Autogenerate proposed
dropping `uq_users_email` and `uq_visits_user_id_idempotency_key` and stripping the
server defaults from `users` and `clients` -- all false positives from comparing the
naming convention against constraints created before it, and one of them silently
removes the uniqueness guarantee on the login identifier. The new tables below are
the only real change.

`note_format` already exists as a type, so it is reused with `create_type=False`.
The other four enum types are new and are created explicitly, which keeps the
downgrade path honest: a table drop does not remove a type, and a rollback that
leaves types behind fails on the next upgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_ENUMS: dict[str, tuple[str, ...]] = {
    "flag_severity": ("info", "warning", "critical"),
    "review_status": ("unreviewed", "needs_correction", "accepted"),
    "job_stage": (
        "queued",
        "download",
        "normalize",
        "transcribe",
        "generate",
        "persist",
        "complete",
    ),
    "job_status": ("queued", "running", "succeeded", "failed"),
}


def _existing(name: str) -> postgresql.ENUM:
    """A reference to a type this migration must not try to create."""
    return postgresql.ENUM(name=name, create_type=False)


def _new(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*NEW_ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in NEW_ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "transcripts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("visit_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("turns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("speaker_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["visit_id"], ["visits.id"], name="fk_transcripts_visit_id_visits", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transcripts"),
        # One transcript per visit. A retry replaces it rather than adding a second
        # candidate answer to "what was said".
        sa.UniqueConstraint("visit_id", name="uq_transcripts_visit_id"),
    )

    op.create_table(
        "notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("visit_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=True),
        sa.Column("format", _existing("note_format"), nullable=False),
        sa.Column("visit_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_by", sa.UUID(), nullable=True),
        sa.Column(
            "review_status",
            _new("review_status"),
            nullable=False,
            server_default="unreviewed",
        ),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["visit_id"], ["visits.id"], name="fk_notes_visit_id_visits", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notes_user_id_users", ondelete="CASCADE"
        ),
        # SET NULL rather than CASCADE: deleting the signer must not delete the
        # signed record. Who signed it can be lost; that it was signed cannot.
        sa.ForeignKeyConstraint(
            ["signed_by"], ["users.id"], name="fk_notes_signed_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notes"),
        sa.UniqueConstraint("visit_id", name="uq_notes_visit_id"),
    )
    op.create_index("ix_notes_user_id", "notes", ["user_id"])
    op.create_index("ix_notes_agency_id_created_at", "notes", ["agency_id", "created_at"])

    op.create_table(
        "note_flags",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("note_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("severity", _new("flag_severity"), nullable=False),
        sa.Column("section_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["note_id"], ["notes.id"], name="fk_note_flags_note_id_notes", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_note_flags_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_note_flags"),
    )
    op.create_index("ix_note_flags_note_id", "note_flags", ["note_id"])
    op.create_index(
        "ix_note_flags_agency_id_created_at_code",
        "note_flags",
        ["agency_id", "created_at", "code"],
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("visit_id", sa.UUID(), nullable=False),
        sa.Column("stage", _new("job_stage"), nullable=False, server_default="queued"),
        sa.Column("status", _new("job_status"), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("audio_minutes", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            name="fk_processing_jobs_visit_id_visits",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_jobs"),
        sa.UniqueConstraint("visit_id", name="uq_processing_jobs_visit_id"),
    )
    op.create_index(
        "ix_processing_jobs_status_created_at", "processing_jobs", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_status_created_at", table_name="processing_jobs")
    op.drop_table("processing_jobs")

    op.drop_index("ix_note_flags_agency_id_created_at_code", table_name="note_flags")
    op.drop_index("ix_note_flags_note_id", table_name="note_flags")
    op.drop_table("note_flags")

    op.drop_index("ix_notes_agency_id_created_at", table_name="notes")
    op.drop_index("ix_notes_user_id", table_name="notes")
    op.drop_table("notes")

    op.drop_table("transcripts")

    # Types outlive their tables in PostgreSQL. Leaving them behind would make the
    # next upgrade fail on a duplicate type -- the classic way a rollback path is
    # discovered to be broken during an incident.
    bind = op.get_bind()
    for name in NEW_ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
