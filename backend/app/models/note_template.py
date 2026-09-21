"""Note templates: the schema-driven definition of each note format.

The review editor renders sections from `section_schema` and the flag engine validates
against `flag_schema`. Neither client contains format-specific components, so adding a
third note format is a data change plus a prompt module -- not a UI rewrite.

Provider and model identifiers live on the row so different formats can pin different
models, and so a model change is a configuration change rather than a deployment.
"""

from sqlalchemy import Boolean, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Json, Timestamped, UUIDPrimaryKey
from app.models.enums import NoteFormat


class NoteTemplate(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "note_templates"
    __table_args__ = (
        UniqueConstraint("format", "version", name="format_version"),
    )

    format: Mapped[NoteFormat] = mapped_column(
        Enum(NoteFormat, name="note_format", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Ordered section definitions the editor renders, and the flag codes with the
    # severities the evaluator is allowed to emit for this format.
    section_schema: Mapped[Json] = mapped_column(nullable=False)
    flag_schema: Mapped[Json] = mapped_column(nullable=False)

    # Points at an immutable prompt module (e.g. "soapie_v1"). Promotion to a new
    # version requires a passing eval run; see evals/.
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<NoteTemplate {self.format} v{self.version} prompt={self.prompt_version}>"
