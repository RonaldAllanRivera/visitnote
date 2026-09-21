"""Login throttling.

Password guessing is only expensive if we make it expensive. argon2 raises the cost
per attempt; a lockout caps the number of attempts outright.

The tradeoff is real and deliberate: per-account lockout lets someone deny service to
a user whose address they know. That is why the lockout is short and self-clearing
rather than requiring an administrator to unlock.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.redis import get_redis

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


@pytest.fixture(autouse=True)
async def _clear_throttle_state() -> None:
    """Counters live in Redis and outlive a test otherwise."""
    client = get_redis()
    keys = [key async for key in client.scan_iter("login:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


async def _register(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201


async def _fail_login(client: AsyncClient, email: str) -> int:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-but-long-enough"}
    )
    return response.status_code


async def test_repeated_failures_eventually_lock_the_account(
    client: AsyncClient,
) -> None:
    email = _email()
    await _register(client, email)

    limit = get_settings().login_max_attempts
    for _ in range(limit):
        assert await _fail_login(client, email) == 401

    assert await _fail_login(client, email) == 429


async def test_a_locked_account_rejects_even_the_correct_password(
    client: AsyncClient,
) -> None:
    """Otherwise the lockout is decorative -- an attacker who guesses right still wins."""
    email = _email()
    await _register(client, email)

    for _ in range(get_settings().login_max_attempts):
        await _fail_login(client, email)

    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 429


async def test_lockout_response_tells_the_client_when_to_retry(
    client: AsyncClient,
) -> None:
    email = _email()
    await _register(client, email)
    for _ in range(get_settings().login_max_attempts):
        await _fail_login(client, email)

    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert int(response.headers["Retry-After"]) > 0


async def test_a_successful_login_clears_the_failure_count(
    client: AsyncClient,
) -> None:
    """A user who mistypes twice then succeeds must not be one slip from a lockout."""
    email = _email()
    await _register(client, email)

    for _ in range(get_settings().login_max_attempts - 1):
        await _fail_login(client, email)

    ok = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert ok.status_code == 200

    assert await _fail_login(client, email) == 401


async def test_locking_one_account_does_not_affect_another(
    client: AsyncClient,
) -> None:
    victim, bystander = _email(), _email()
    await _register(client, victim)
    await _register(client, bystander)

    for _ in range(get_settings().login_max_attempts):
        await _fail_login(client, victim)

    response = await client.post(
        "/api/v1/auth/login", json={"email": bystander, "password": PASSWORD}
    )
    assert response.status_code == 200


async def test_attempts_against_an_unknown_address_are_also_throttled(
    client: AsyncClient,
) -> None:
    """Otherwise an attacker enumerates addresses at unlimited speed."""
    unknown = _email()
    for _ in range(get_settings().login_max_attempts):
        assert await _fail_login(client, unknown) == 401

    assert await _fail_login(client, unknown) == 429
