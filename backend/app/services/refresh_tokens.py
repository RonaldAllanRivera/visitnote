"""Refresh token issuing, rotation, and reuse detection.

The threat model: a refresh token can be stolen -- from device storage, from a proxy,
from a log. We cannot prevent the thief using it. What we can do is guarantee that the
theft is *detected* the moment both parties are active, and that detection costs the
attacker their access.

Rotation makes every token single-use. If a token is presented twice, two parties hold
it, and we cannot tell which one is legitimate. Revoking the whole family is the only
safe answer: the real user re-authenticates with their password, the attacker cannot.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import RefreshToken

# 256 bits. Long enough that guessing is not a threat worth modelling.
_TOKEN_BYTES = 32


class RefreshTokenError(Exception):
    """Base for every refresh failure."""


class UnknownRefreshTokenError(RefreshTokenError):
    """Token is unrecognised, expired, or already revoked by logout or detection.

    Deliberately indistinguishable to the caller from "never existed". Telling a
    client which of those applies tells an attacker whether they guessed a real token.
    """


class RefreshTokenReuseError(RefreshTokenError):
    """A token was presented after it had already been rotated.

    Raised only after the family has been revoked, so the caller cannot forget to.
    """


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(slots=True)
class RefreshTokenService:
    session: AsyncSession

    async def issue(
        self, user_id: uuid.UUID, ttl: timedelta | None = None, family_id: uuid.UUID | None = None
    ) -> tuple[str, RefreshToken]:
        """Mint a token. Omitting `family_id` starts a new session."""
        raw = secrets.token_urlsafe(_TOKEN_BYTES)
        lifetime = ttl or timedelta(seconds=get_settings().refresh_token_ttl_seconds)

        record = RefreshToken(
            user_id=user_id,
            token_hash=_hash(raw),
            family_id=family_id or uuid.uuid4(),
            expires_at=utcnow() + lifetime,
        )
        self.session.add(record)
        await self.session.commit()
        return raw, record

    async def rotate(self, raw: str) -> tuple[str, RefreshToken]:
        """Exchange a token for its successor, detecting reuse."""
        record = await self._find(raw)
        if record is None:
            raise UnknownRefreshTokenError("unrecognised refresh token")

        if record.revoked_at is not None:
            # A revoked token means one of two very different things, and conflating
            # them produces false reuse alarms every time a logged-out client retries.
            #
            #   - The family still has a live token: this token was superseded by
            #     rotation, and someone has just replayed it. Two parties hold the
            #     same secret and we cannot tell them apart, so neither keeps access.
            #   - The family is entirely revoked: logout, or a reuse detection that
            #     already fired. The session is simply over; there is nothing new to
            #     detect and nothing left to revoke.
            if await self._family_has_live_token(record.family_id):
                await self.revoke_family(record.family_id)
                raise RefreshTokenReuseError("refresh token replayed; family revoked")
            raise UnknownRefreshTokenError("refresh token belongs to a closed session")

        if record.expires_at <= utcnow():
            raise UnknownRefreshTokenError("expired refresh token")

        record.revoked_at = utcnow()
        await self.session.flush()
        return await self.issue(record.user_id, family_id=record.family_id)

    async def revoke(self, raw: str) -> None:
        """Log out. Revokes the family, not just the presented token.

        Revoking only the presented token would leave its already-issued predecessors
        live, so a logout would not actually end the session.
        """
        record = await self._find(raw)
        if record is not None:
            await self.revoke_family(record.family_id)

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await self.session.commit()

    async def _family_has_live_token(self, family_id: uuid.UUID) -> bool:
        """True when some token in this family is still usable."""
        return (
            await self.session.execute(
                select(RefreshToken.id)
                .where(
                    RefreshToken.family_id == family_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > utcnow(),
                )
                .limit(1)
            )
        ).first() is not None

    async def _find(self, raw: str) -> RefreshToken | None:
        return (
            await self.session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == _hash(raw))
            )
        ).scalar_one_or_none()
