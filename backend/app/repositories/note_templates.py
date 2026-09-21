"""Note template lookup."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteTemplate
from app.models.enums import Jurisdiction, NoteFormat


@dataclass(slots=True)
class NoteTemplateRepository:
    session: AsyncSession

    async def get_active(
        self, jurisdiction: Jurisdiction, note_format: NoteFormat
    ) -> NoteTemplate | None:
        """The active template for a jurisdiction and format, newest version first.

        Jurisdiction leads because it is the coarser filter and because it matches the
        index. Ordered by version rather than filtered to one, so promoting a new
        template version is inserting a row and deactivating the old one -- never an
        update that rewrites what already-generated notes were produced from.
        """
        return (
            await self.session.execute(
                select(NoteTemplate)
                .where(
                    NoteTemplate.jurisdiction == jurisdiction,
                    NoteTemplate.format == note_format,
                    NoteTemplate.is_active.is_(True),
                )
                .order_by(NoteTemplate.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def all_active(self) -> list[NoteTemplate]:
        return list(
            (
                await self.session.execute(
                    select(NoteTemplate)
                    .where(NoteTemplate.is_active.is_(True))
                    .order_by(
                        NoteTemplate.jurisdiction, NoteTemplate.format, NoteTemplate.version.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
