"""Generated notes, their normalized flag rows, and the transcript behind them."""

import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Json, Timestamped, UtcDateTime, UUIDPrimaryKey
from app.models.enums import FlagSeverity, NoteFormat, ReviewStatus
from app.models.enums import note_format_column as _format_column


def _enum(enum_type: type, name: str) -> Enum:
    return Enum(enum_type, name=name, values_callable=lambda e: [m.value for m in e])


class Transcript(UUIDPrimaryKey, Timestamped, Base):
    """What was said, as ordered speaker turns.

    `turns` is the structured form the LLM is shown and the fabrication checker
    verifies quotes against. `raw_text` is the same content flattened, kept for
    display and for the "does this value appear anywhere in the audio" check. One is
    derived from the other on write, so they cannot drift.
    """

    __tablename__ = "transcripts"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    turns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    speaker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Recorded so a note generated from barely-intelligible audio is identifiable
    # after the fact, rather than only looking like a bad model day.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<Transcript visit={self.visit_id} speakers={self.speaker_count}>"


class Note(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_agency_id_created_at", "agency_id", "created_at"),)

    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # No foreign key yet: the agencies table arrives in phase 7. The column exists
    # now because it is written on the same path that creates the note, and
    # backfilling it later would mean reprocessing every note to find its author's
    # agency at the time of writing.
    agency_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # VARCHAR rather than a Postgres ENUM: formats are a growing set, and a format's
    # validity is established by having a row in note_templates -- not by the column type.
    format: Mapped[NoteFormat] = mapped_column(_format_column(), nullable=False)

    # The structured header: label, date, and the exact times. Separate from
    # `sections` because it is the part that gets checked rather than read -- the
    # missing-times flags are decided from these fields, not by parsing prose.
    visit_details: Mapped[Json] = mapped_column(nullable=False)
    sections: Mapped[Json] = mapped_column(nullable=False)
    # The note's own copy of its flags, matching the LLM output contract. Rendered,
    # never queried into; `note_flags` is what the dashboards read.
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    # Optimistic concurrency. A supervisor opening a note in the review queue while
    # the author edits it on their phone must not silently discard one of them --
    # this is a legal record that will be signed.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    signed_at: Mapped[UtcDateTime | None] = mapped_column(nullable=True)
    signed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "review_status"),
        nullable=False,
        default=ReviewStatus.UNREVIEWED,
        server_default="unreviewed",
    )

    # Provenance. A note that cannot say what produced it cannot be audited when a
    # prompt or model turns out to have been regressing.
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)

    note_flags: Mapped[list["NoteFlag"]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Note {self.id} {self.format} v{self.version}>"


class NoteFlag(UUIDPrimaryKey, Timestamped, Base):
    """The analytics shape of a flag.

    Five dashboard views aggregate across flag codes, and the API contract promises
    those are computed with SQL aggregation rather than Python loops. That promise is
    not keepable against a JSONB array at tens of thousands of notes, which is why
    the same flags are also rows.

    `user_id` and `agency_id` are denormalized for index locality: a per-staff
    breakdown should not have to join through notes and visits to find out who wrote
    the note.
    """

    __tablename__ = "note_flags"
    __table_args__ = (
        Index("ix_note_flags_agency_id_created_at_code", "agency_id", "created_at", "code"),
    )

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[FlagSeverity] = mapped_column(
        _enum(FlagSeverity, "flag_severity"), nullable=False
    )
    # Which section the flag is about, where that is known. The output contract does
    # not ask the model for it, and deriving it from the code would be guesswork, so
    # it stays null until the review UI lets a human attach one.
    section_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    note: Mapped[Note] = relationship(back_populates="note_flags")

    def __repr__(self) -> str:
        return f"<NoteFlag {self.code} {self.severity}>"
