"""Visit creation."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConsentLog, User, Visit
from app.models.enums import NoteFormat
from app.repositories.clients import ClientRepository
from app.repositories.visits import VisitRepository
from app.schemas.visit import VisitCreate


class UnknownClientError(Exception):
    """The care recipient does not exist, or does not belong to this user.

    One error for both, so a caller cannot probe for record ids they do not own.
    """


@dataclass(slots=True)
class VisitService:
    session: AsyncSession

    async def create(self, user: User, payload: VisitCreate) -> tuple[Visit, bool]:
        """Create a visit, or return the existing one for a replayed key.

        Returns (visit, created) so the route can answer 201 for a new visit and 200
        for a replay.
        """
        visits = VisitRepository(self.session)

        existing = await visits.get_by_idempotency_key(user.id, payload.idempotency_key)
        if existing is not None:
            return existing, False

        care_recipient = await ClientRepository(self.session).get_for_owner(
            payload.client_id, user.id
        )
        if care_recipient is None:
            raise UnknownClientError

        visit = visits.add(
            Visit(
                user_id=user.id,
                client_id=care_recipient.id,
                note_format=payload.note_format
                or user.default_note_format
                or NoteFormat.SHIFT_NOTE,
                capture_mode=payload.capture_mode,
                # Copied onto the visit rather than read from the user later: a user
                # who moves must not retro-date the notes they have already written.
                timezone=user.timezone,
                idempotency_key=payload.idempotency_key,
            )
        )
        # Same transaction as the visit, so a recording can never exist without its
        # consent record.
        self.session.add(
            ConsentLog(
                visit=visit,
                user_id=user.id,
                capture_mode=payload.capture_mode,
                acknowledged=payload.consent_acknowledged,
            )
        )

        try:
            await self.session.commit()
        except IntegrityError:
            # Two concurrent requests with the same key. The unique constraint is the
            # real guard; this is the race the check above cannot close on its own.
            await self.session.rollback()
            replayed = await visits.get_by_idempotency_key(user.id, payload.idempotency_key)
            if replayed is None:
                raise
            return replayed, False

        await self.session.refresh(visit)
        return visit, True
