"""Authentication endpoints.

These assert the contract the clients depend on, and the security properties that are
easy to lose in a refactor -- chiefly that a failed login reveals nothing about
whether the account exists.
"""

import uuid

import pytest
from httpx import AsyncClient


def _email() -> str:
    # Not a .test/.example TLD: those are IANA special-use names and email-validator
    # rejects them outright, which is correct behaviour we do not want to loosen.
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


PASSWORD = "a-sufficiently-long-password"


async def register(client: AsyncClient, email: str | None = None, password: str = PASSWORD) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email or _email(), "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- registration ----------------------------------------------------------------


async def test_registration_returns_an_access_and_refresh_token(client: AsyncClient) -> None:
    body = await register(client)
    assert body["access_token"] and body["refresh_token"]


async def test_registration_never_returns_the_password_hash(client: AsyncClient) -> None:
    assert "password" not in str(await register(client)).lower()


async def test_duplicate_email_is_rejected(client: AsyncClient) -> None:
    email = _email()
    await register(client, email)
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 409


async def test_email_is_stored_case_insensitively(client: AsyncClient) -> None:
    """Someone who registers as Alice@ must not be able to register again as alice@."""
    email = _email()
    await register(client, email.upper())
    response = await client.post(
        "/api/v1/auth/register", json={"email": email.lower(), "password": PASSWORD}
    )
    assert response.status_code == 409


@pytest.mark.parametrize("password", ["", "short"])
async def test_short_passwords_are_rejected(client: AsyncClient, password: str) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": _email(), "password": password}
    )
    assert response.status_code == 422


async def test_malformed_email_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD}
    )
    assert response.status_code == 422


# -- login -----------------------------------------------------------------------


async def test_login_with_correct_credentials_returns_tokens(client: AsyncClient) -> None:
    email = _email()
    await register(client, email)
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_with_a_wrong_password_is_rejected(client: AsyncClient) -> None:
    email = _email()
    await register(client, email)
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-but-long-enough"}
    )
    assert response.status_code == 401


async def test_unknown_email_and_wrong_password_are_indistinguishable(
    client: AsyncClient,
) -> None:
    """User enumeration: a different status or message for an unknown address lets an
    attacker harvest valid accounts before ever attempting a password."""
    email = _email()
    await register(client, email)

    wrong_password = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-but-long-enough"}
    )
    unknown_email = await client.post(
        "/api/v1/auth/login", json={"email": _email(), "password": PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_login_issues_a_new_session_each_time(client: AsyncClient) -> None:
    email = _email()
    first = await register(client, email)
    second = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert second.json()["refresh_token"] != first["refresh_token"]


# -- refresh ---------------------------------------------------------------------


async def test_refresh_exchanges_a_token_for_a_new_pair(client: AsyncClient) -> None:
    body = await register(client)
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.json()["refresh_token"] != body["refresh_token"]


async def test_replaying_a_refresh_token_is_rejected(client: AsyncClient) -> None:
    body = await register(client)
    await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert replay.status_code == 401


async def test_replay_invalidates_the_session_that_was_still_live(
    client: AsyncClient,
) -> None:
    """End to end proof of the reuse defence, through HTTP."""
    body = await register(client)
    rotated = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    ).json()["refresh_token"]

    await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})

    after_detection = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated}
    )
    assert after_detection.status_code == 401


async def test_unknown_refresh_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": "never-issued"}
    )
    assert response.status_code == 401


# -- logout ----------------------------------------------------------------------


async def test_logout_makes_the_refresh_token_unusable(client: AsyncClient) -> None:
    body = await register(client)
    logout = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]}
    )
    assert logout.status_code == 204

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert response.status_code == 401


async def test_logout_is_idempotent(client: AsyncClient) -> None:
    """A client retrying a logout over a flaky connection must not see an error."""
    body = await register(client)
    await client.post("/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]})
    again = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]}
    )
    assert again.status_code == 204


# -- current user ----------------------------------------------------------------


async def test_me_returns_the_authenticated_user(client: AsyncClient) -> None:
    email = _email()
    body = await register(client, email)
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == email.lower()


async def test_me_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_me_rejects_a_garbage_token(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_me_rejects_a_refresh_token_used_as_a_bearer_token(
    client: AsyncClient,
) -> None:
    body = await register(client)
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['refresh_token']}"}
    )
    assert response.status_code == 401


async def test_new_accounts_are_not_staff(client: AsyncClient) -> None:
    """Privilege escalation by registration would be the shortest possible attack."""
    body = await register(client)
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert response.json()["is_staff"] is False
