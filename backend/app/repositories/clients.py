"""Care recipient queries.

Every method takes an owner and filters on it. Scoping is applied here rather than
left to callers, so a new route cannot forget it and expose another tenant's data.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client


@dataclass(slots=True)
class ClientRepository:
    session: AsyncSession

    async def list_for_owner(self, owner_id: uuid.UUID) -> Sequence[Client]:
        result = await self.session.execute(
            select(Client)
            .where(Client.owner_id == owner_id, Client.is_active.is_(True))
            .order_by(Client.label)
        )
        return result.scalars().all()

    async def get_for_owner(self, client_id: uuid.UUID, owner_id: uuid.UUID) -> Client | None:
        """Owner is part of the lookup, not a check afterwards.

        Fetching by id and then comparing owners is the same query one `if` away from
        an authorisation bug. Filtering in SQL makes the safe version the only one.
        """
        return (
            await self.session.execute(
                select(Client).where(Client.id == client_id, Client.owner_id == owner_id)
            )
        ).scalar_one_or_none()

    def add(self, record: Client) -> Client:
        self.session.add(record)
        return record
