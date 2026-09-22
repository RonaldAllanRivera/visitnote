"""Visit creation."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConsentLog, User, Visit
from app.models.enums import CaptureMode, Jurisdiction
from app.repositories.clients import ClientRepository
from app.repositories.note_templates import NoteTemplateRepository
from app.repositories.visits import VisitRepository
from app.schemas.visit import VisitCreate

# Jurisdictions in which recording a third party is not lawfully obtainable, and the
# statute that says so. Data rather than a branch, so adding a jurisdiction is a row.
PROHIBITED_CAPTURE_MODES: dict[Jurisdiction, tuple[CaptureMode, str]] = {
    Jurisdiction.PH: (
        CaptureMode.LIVE_AUDIO,
        "RA 4200 (Anti-Wiretapping Act) requires the consent of all parties to a "
        "private communication. Record a spoken recap instead.",
    ),
}


class UnknownClientError(Exception):
    """The care recipient does not exist, or does not belong to this user.

    One error for both, so a caller cannot probe for record ids they do not own.
    """


class ProhibitedCaptureModeError(Exception):
    """The capture mode is unlawful in this user's jurisdiction.

    Enforced here rather than in the schema, because the rule depends on the
    authenticated user and a Pydantic model validator cannot see them.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UnsupportedNoteFormatError(Exception):
    """No active template exists for this user's jurisdiction and note format.

    Covers both an unresolved format -- neither the payload nor the account's
    default named one -- and a resolved format this jurisdiction seeds no template
    for. Either way the pipeline would have nothing to render against, so this is
    refused at creation rather than accepted and left to fail non-retryably in
    `Pipeline._template` after a quota unit is already spent.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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

        # Resolve from the explicit payload, else the account's default. Unlike the
        # capture-mode and client checks below, there is no hardcoded fallback here:
        # a US format is not a safe default for a PH account, so an unresolved format
        # is an error, not a guess.
        note_format = payload.note_format or user.default_note_format
        template = (
            None
            if note_format is None
            else await NoteTemplateRepository(self.session).get_active(
                user.jurisdiction, note_format
            )
        )
        if template is None:
            raise UnsupportedNoteFormatError(
                f"No active note template exists for jurisdiction {user.jurisdiction} and "
                f"format {note_format}. Choose a format this jurisdiction supports."
            )

        prohibited = PROHIBITED_CAPTURE_MODES.get(user.jurisdiction)
        if prohibited is not None and payload.capture_mode is prohibited[0]:
            raise ProhibitedCaptureModeError(prohibited[1])

        care_recipient = await ClientRepository(self.session).get_for_owner(
            payload.client_id, user.id
        )
        if care_recipient is None:
            raise UnknownClientError

        visit = visits.add(
            Visit(
                user_id=user.id,
                client_id=care_recipient.id,
                jurisdiction=user.jurisdiction,
                note_format=note_format,
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
