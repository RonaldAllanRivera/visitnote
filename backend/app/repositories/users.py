"""User queries.

All database access for users lives here. Services call these; routers never do.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


@dataclass(slots=True)
class UserRepository:
    session: AsyncSession

    async def get_by_email(self, email: str) -> User | None:
        return (
            await self.session.execute(select(User).where(User.email == email.lower()))
        ).scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def exists_by_email(self, email: str) -> bool:
        return (
            await self.session.execute(select(User.id).where(User.email == email.lower()))
        ).first() is not None

    def add(self, user: User) -> User:
        self.session.add(user)
        return user
