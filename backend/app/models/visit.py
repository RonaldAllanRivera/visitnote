"""Visits and their consent records."""

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UtcDateTime, UUIDPrimaryKey
from app.models.enums import CaptureMode, Jurisdiction, NoteFormat, VisitStatus, jurisdiction_column
from app.models.enums import note_format_column as _format_column


def _enum(enum_type: type, name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


class Visit(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "visits"
    __table_args__ = (
        # Keys are generated client-side, so uniqueness is scoped per user. A global
        # constraint would let one user's key collide with another's and hand back a
        # visit belonging to someone else.
        #
        # Spelled out in full rather than left short: this project's `uq` naming
        # convention (app/models/base.py) interpolates the constraint's columns, not
        # `%(constraint_name)s`, so an explicit name here is used verbatim and never
        # gets the `uq_visits_` prefix applied. A short name would silently disagree
        # with what migration 0005 actually created in the database, and
        # `alembic revision --autogenerate` would propose dropping and recreating the
        # constraint that stops a dropped-connection retry from double-spending quota.
        UniqueConstraint("user_id", "idempotency_key", name="uq_visits_user_id_idempotency_key"),
        Index("ix_visits_user_id_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )

    # Copied from the user at creation, not read from them later -- the same argument
    # as `timezone` below. Changing your jurisdiction must not re-resolve the template
    # for work you already captured.
    jurisdiction: Mapped[Jurisdiction] = mapped_column(jurisdiction_column(), nullable=False)

    note_format: Mapped[NoteFormat] = mapped_column(_format_column(), nullable=False)
    capture_mode: Mapped[CaptureMode] = mapped_column(
        _enum(CaptureMode, "capture_mode"), nullable=False
    )
    status: Mapped[VisitStatus] = mapped_column(
        _enum(VisitStatus, "visit_status"), nullable=False, default=VisitStatus.RECORDING
    )

    # The zone the visit was captured in, carried on the row rather than read from the
    # user, because a user who later moves must not retro-date their old notes.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)

    visit_date: Mapped[UtcDateTime | None] = mapped_column(nullable=True)
    shift_start: Mapped[UtcDateTime | None] = mapped_column(nullable=True)
    shift_end: Mapped[UtcDateTime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Null until upload completes, and null again once the raw audio is deleted 24h
    # after sign-off.
    audio_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Set when an upload is negotiated, cleared on completion. Distinguishes a
    # single-PUT upload in progress -- which has no upload id -- from a visit where
    # nothing was ever started, and makes abandoned uploads findable for cleanup.
    upload_started_at: Mapped[UtcDateTime | None] = mapped_column(nullable=True)
    upload_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Lets the consent record be created alongside an unflushed visit; SQLAlchemy
    # orders the inserts so the foreign key is satisfied without a manual flush.
    consent_logs: Mapped[list["ConsentLog"]] = relationship(
        back_populates="visit", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Visit {self.id} {self.status}>"


class ConsentLog(UUIDPrimaryKey, Timestamped, Base):
    """Proof that the acknowledgment happened.

    Written in the same transaction as the visit, so a recording cannot exist without
    its corresponding record. "They said it was fine" is not a defence; this is.
    """

    __tablename__ = "consent_logs"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    capture_mode: Mapped[CaptureMode] = mapped_column(
        _enum(CaptureMode, "capture_mode"), nullable=False
    )
    # False is a legitimate, recorded state for spoken_recap: nobody else was
    # recorded, so there was nobody to ask.
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False)

    visit: Mapped[Visit] = relationship(back_populates="consent_logs")

    def __repr__(self) -> str:
        return f"<ConsentLog visit={self.visit_id} mode={self.capture_mode}>"
