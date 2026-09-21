"""Google sign-in.

The client obtains an ID token from Google and posts it here; the server verifies it
and issues its own tokens. Chosen over the redirect flow because one code path serves
both the SPA and the native app, and because the server never handles a Google
refresh token it has no use for.

Verification sits behind a protocol with a fake implementation, matching how the LLM
and transcription providers are structured, so these tests never touch the network.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.models import User
from app.services.google import (
    GoogleIdentity,
    GoogleTokenError,
    get_google_verifier,
)

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


def _identity(*, verified: bool = True) -> GoogleIdentity:
    return GoogleIdentity(
        sub=uuid.uuid4().hex, email=_email(), email_verified=verified, name="Alex"
    )


class FakeVerifier:
    """Returns a scripted identity, or raises, without calling Google."""

    def __init__(self, identity: GoogleIdentity | None = None) -> None:
        self._identity = identity

    async def verify(self, id_token: str) -> GoogleIdentity:
        if self._identity is None or id_token == "bad-token":
            raise GoogleTokenError("invalid id token")
        return self._identity


@pytest.fixture
def google_client():
    """A client whose Google verifier is overridden per test."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _build(identity: GoogleIdentity | None):
        from httpx import ASGITransport

        app = create_app()
        app.dependency_overrides[get_google_verifier] = lambda: FakeVerifier(identity)
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as ac,
            app.router.lifespan_context(app),
        ):
            yield ac

    return _build


async def test_a_new_google_user_gets_an_account_and_tokens(google_client) -> None:
    identity = _identity()
    async with google_client(identity) as client:
        response = await client.post("/api/v1/auth/google", json={"id_token": "good"})

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_signing_in_twice_does_not_create_a_second_account(
    google_client, session: AsyncSession
) -> None:
    identity = _identity()
    async with google_client(identity) as client:
        await client.post("/api/v1/auth/google", json={"id_token": "good"})
        await client.post("/api/v1/auth/google", json={"id_token": "good"})

    rows = (
        await session.execute(select(User).where(User.email == identity.email))
    ).scalars().all()
    assert len(rows) == 1


async def test_a_google_only_account_has_no_password(
    google_client, session: AsyncSession
) -> None:
    """And so must never be loggable-into via the password route."""
    identity = _identity()
    async with google_client(identity) as client:
        await client.post("/api/v1/auth/google", json={"id_token": "good"})

    user = (
        await session.execute(select(User).where(User.email == identity.email))
    ).scalar_one()
    assert user.password_hash is None


async def test_google_links_to_an_existing_password_account(
    google_client, session: AsyncSession
) -> None:
    """Someone who signed up with a password then uses Google keeps one account.

    Safe only because the email is verified by Google. Linking on an unverified
    address would let anyone who can claim an address take over its account.
    """
    identity = _identity()
    email = identity.email

    async with google_client(identity) as client:
        await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
        response = await client.post("/api/v1/auth/google", json={"id_token": "good"})

    assert response.status_code == 200
    rows = (await session.execute(select(User).where(User.email == email))).scalars().all()
    assert len(rows) == 1
    assert rows[0].google_sub == identity.sub


async def test_an_unverified_google_email_is_refused(google_client) -> None:
    """Account takeover: an unverified address proves nothing about who controls it."""
    identity = _identity(verified=False)
    async with google_client(identity) as client:
        response = await client.post("/api/v1/auth/google", json={"id_token": "good"})

    assert response.status_code == 401


async def test_an_invalid_id_token_is_refused(google_client) -> None:
    identity = _identity()
    async with google_client(identity) as client:
        response = await client.post("/api/v1/auth/google", json={"id_token": "bad-token"})

    assert response.status_code == 401


async def test_password_login_is_refused_for_a_google_only_account(
    google_client, session: AsyncSession
) -> None:
    identity = _identity()
    async with google_client(identity) as client:
        await client.post("/api/v1/auth/google", json={"id_token": "good"})
        response = await client.post(
            "/api/v1/auth/login", json={"email": identity.email, "password": PASSWORD}
        )

    assert response.status_code == 401
