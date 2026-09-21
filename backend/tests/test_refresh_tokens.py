"""Refresh token rotation and reuse detection.

The threat this defends against: an attacker steals a refresh token. They cannot be
stopped from using it, but the moment either they or the legitimate user presents a
token that has already been rotated, we know one of the two is an impostor -- and we
cannot tell which. The safe response is to revoke the entire family and force both to
re-authenticate.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken, User
from app.services.refresh_tokens import (
    RefreshTokenReuseError,
    RefreshTokenService,
    UnknownRefreshTokenError,
)


@pytest.fixture
async def user(session: AsyncSession) -> User:
    record = User(email=f"{uuid.uuid4().hex}@example.test", password_hash="x")
    session.add(record)
    await session.commit()
    return record


@pytest.fixture
def service(session: AsyncSession) -> RefreshTokenService:
    return RefreshTokenService(session)


async def test_issued_token_is_never_stored_in_plaintext(
    service: RefreshTokenService, session: AsyncSession, user: User
) -> None:
    """A database leak must not hand the attacker usable sessions."""
    raw, _ = await service.issue(user.id)

    stored = (await session.execute(select(RefreshToken))).scalars().all()
    assert all(row.token_hash != raw for row in stored)


async def test_rotation_returns_a_different_token(
    service: RefreshTokenService, user: User
) -> None:
    raw, _ = await service.issue(user.id)
    rotated, _ = await service.rotate(raw)
    assert rotated != raw


async def test_rotation_keeps_the_token_in_the_same_family(
    service: RefreshTokenService, user: User
) -> None:
    raw, first = await service.issue(user.id)
    _, second = await service.rotate(raw)
    assert second.family_id == first.family_id


async def test_rotation_revokes_the_presented_token(
    service: RefreshTokenService, session: AsyncSession, user: User
) -> None:
    raw, original = await service.issue(user.id)
    await service.rotate(raw)

    await session.refresh(original)
    assert original.revoked_at is not None


async def test_reusing_a_rotated_token_is_rejected(
    service: RefreshTokenService, user: User
) -> None:
    raw, _ = await service.issue(user.id)
    await service.rotate(raw)

    with pytest.raises(RefreshTokenReuseError):
        await service.rotate(raw)


async def test_reuse_revokes_every_token_in_the_family(
    service: RefreshTokenService, session: AsyncSession, user: User
) -> None:
    """The attacker's stolen token and the victim's live token die together.

    This is the whole point: after detection, neither party holds a working session.
    """
    raw, _ = await service.issue(user.id)
    current, _ = await service.rotate(raw)

    with pytest.raises(RefreshTokenReuseError):
        await service.rotate(raw)

    # The token that was legitimately current before detection must now be dead too.
    with pytest.raises(UnknownRefreshTokenError):
        await service.rotate(current)


async def test_reuse_does_not_touch_the_users_other_sessions(
    service: RefreshTokenService, user: User
) -> None:
    """A compromised phone must not log the user out of their laptop.

    Each login starts its own family, so revocation is scoped to the family that was
    actually replayed.
    """
    phone, _ = await service.issue(user.id)
    laptop, _ = await service.issue(user.id)
    await service.rotate(phone)

    with pytest.raises(RefreshTokenReuseError):
        await service.rotate(phone)

    rotated_laptop, _ = await service.rotate(laptop)
    assert rotated_laptop


async def test_rejects_an_expired_token(
    service: RefreshTokenService, user: User
) -> None:
    raw, _ = await service.issue(user.id, ttl=timedelta(seconds=-1))
    with pytest.raises(UnknownRefreshTokenError):
        await service.rotate(raw)


async def test_rejects_a_token_that_was_never_issued(
    service: RefreshTokenService, user: User
) -> None:
    with pytest.raises(UnknownRefreshTokenError):
        await service.rotate("never-issued-token")


async def test_logout_revokes_the_family_so_the_token_stops_working(
    service: RefreshTokenService, user: User
) -> None:
    raw, _ = await service.issue(user.id)
    await service.revoke(raw)

    with pytest.raises(UnknownRefreshTokenError):
        await service.rotate(raw)
