"""Staff privilege: how it is granted, and how it is enforced."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_staff
from app.cli import StaffUserExistsError, create_staff_user
from app.models import User

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


# -- enforcement -----------------------------------------------------------------


async def test_staff_gate_admits_a_staff_user() -> None:
    user = User(email=_email(), is_staff=True)
    assert await require_staff(user) is user


async def test_staff_gate_reports_not_found_rather_than_forbidden() -> None:
    """403 would confirm /ops exists. A non-staff user should not learn that at all."""
    with pytest.raises(HTTPException) as exc:
        await require_staff(User(email=_email(), is_staff=False))

    assert exc.value.status_code == 404


# -- granting --------------------------------------------------------------------


async def test_cli_creates_a_staff_user(session: AsyncSession) -> None:
    """Staff privilege is granted out of band only.

    There is no API route that sets is_staff. Someone with shell access on the server
    is already trusted; a web endpoint that grants admin is an attack surface with no
    corresponding benefit.
    """
    email = _email()
    await create_staff_user(session, email=email, password=PASSWORD)

    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one()
    assert user.is_staff is True
    assert user.is_active is True


async def test_cli_stores_a_usable_password_hash(session: AsyncSession) -> None:
    from app.core.security import verify_password

    email = _email()
    await create_staff_user(session, email=email, password=PASSWORD)

    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.password_hash is not None
    assert verify_password(PASSWORD, user.password_hash)


async def test_cli_normalises_the_email(session: AsyncSession) -> None:
    email = _email()
    await create_staff_user(session, email=email.upper(), password=PASSWORD)

    assert (
        await session.execute(select(User).where(User.email == email.lower()))
    ).scalar_one_or_none() is not None


async def test_cli_refuses_to_clobber_an_existing_account(
    session: AsyncSession,
) -> None:
    """Silently promoting an existing user would be a way to escalate a known address."""
    email = _email()
    await create_staff_user(session, email=email, password=PASSWORD)

    with pytest.raises(StaffUserExistsError):
        await create_staff_user(session, email=email, password=PASSWORD)


async def test_cli_rejects_a_short_password(session: AsyncSession) -> None:
    """An operator account is the highest-value target in the system."""
    with pytest.raises(ValueError, match="at least"):
        await create_staff_user(session, email=_email(), password="short")
