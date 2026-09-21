"""Visit queries, always scoped to their owner."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Visit


@dataclass(slots=True)
class VisitRepository:
    session: AsyncSession

    async def get_for_user(self, visit_id: uuid.UUID, user_id: uuid.UUID) -> Visit | None:
        return (
            await self.session.execute(
                select(Visit).where(Visit.id == visit_id, Visit.user_id == user_id)
            )
        ).scalar_one_or_none()

    async def get_by_idempotency_key(self, user_id: uuid.UUID, key: str) -> Visit | None:
        return (
            await self.session.execute(
                select(Visit).where(Visit.user_id == user_id, Visit.idempotency_key == key)
            )
        ).scalar_one_or_none()

    def add(self, visit: Visit) -> Visit:
        self.session.add(visit)
        return visit
