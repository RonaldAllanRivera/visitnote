"""Note templates: the schema-driven definition of each note format.

The review editor renders sections from `section_schema` and the flag engine validates
against `flag_schema`. Neither client contains format-specific components, so adding a
third note format is a data change plus a prompt module -- not a UI rewrite.

Provider and model identifiers live on the row so different formats can pin different
models, and so a model change is a configuration change rather than a deployment.
"""

from sqlalchemy import Boolean, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Json, Timestamped, UUIDPrimaryKey
from app.models.enums import Jurisdiction, NoteFormat, jurisdiction_column
from app.models.enums import note_format_column as _format_column


class NoteTemplate(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "note_templates"
    __table_args__ = (
        # Spelled out in full rather than left short: this project's `uq` naming
        # convention (app/models/base.py) interpolates the constraint's columns, not
        # `%(constraint_name)s`, so an explicit name here is used verbatim and never
        # gets the `uq_note_templates_` prefix applied. A short name would silently
        # disagree with what migration 0009 actually created in the database, and
        # `alembic revision --autogenerate` would propose dropping and recreating it.
        UniqueConstraint(
            "jurisdiction",
            "format",
            "version",
            name="uq_note_templates_jurisdiction_format_version",
        ),
        Index("ix_note_templates_jurisdiction_format", "jurisdiction", "format"),
    )

    # A separate axis from format: the same format carries different flag schemas in
    # different regimes. PH SOAPIE is SOAPIE without the CMS survey requirements.
    jurisdiction: Mapped[Jurisdiction] = mapped_column(jurisdiction_column(), nullable=False)

    # VARCHAR rather than a Postgres ENUM: formats are a growing set, and a format's
    # validity is established by having a row in this table -- not by the column type.
    format: Mapped[NoteFormat] = mapped_column(_format_column(), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Ordered section definitions the editor renders, and the flag codes with the
    # severities the evaluator is allowed to emit for this format.
    section_schema: Mapped[Json] = mapped_column(nullable=False)
    flag_schema: Mapped[Json] = mapped_column(nullable=False)

    # A US home visit has two to four speakers and a mis-attributed quote is a
    # fabrication. A PH spoken recap has one speaker; diarizing a monologue is spend
    # with no buyer.
    requires_diarization: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Points at an immutable prompt module (e.g. "soapie_v1"). Promotion to a new
    # version requires a passing eval run; see evals/.
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<NoteTemplate {self.format} v{self.version} prompt={self.prompt_version}>"
