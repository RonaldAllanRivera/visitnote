"""What an account is allowed to do, published on its profile.

The rules themselves are enforced server-side on every request that depends on them;
these are the same rules stated to the client so it can stop offering what will be
refused. A client that re-derives them holds a second copy of a legal constraint, and
the copy is the one that goes stale.
"""

import uuid

from httpx import AsyncClient

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def _account(client: AsyncClient, timezone: str) -> dict[str, str]:
    body = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    await client.patch(
        "/api/v1/auth/me", headers=headers, json={"role_title": "rn", "timezone": timezone}
    )
    return headers


async def _capabilities(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    return response.json()["capabilities"]


async def test_a_ph_account_may_only_record_itself(client: AsyncClient) -> None:
    headers = await _account(client, "Asia/Manila")

    capabilities = await _capabilities(client, headers)

    assert capabilities["allowed_capture_modes"] == ["spoken_recap"]


async def test_a_ph_account_is_told_which_statute_restricts_it(client: AsyncClient) -> None:
    # The client shows this text rather than writing its own. One wording, from the
    # same place that enforces the rule.
    headers = await _account(client, "Asia/Manila")

    restriction = (await _capabilities(client, headers))["capture_restriction"]

    assert restriction["code"] == "RA_4200"
    assert restriction["mode"] == "live_audio"
    assert "RA 4200" in restriction["message"]


async def test_a_us_account_may_record_a_visit(client: AsyncClient) -> None:
    headers = await _account(client, "America/Los_Angeles")

    capabilities = await _capabilities(client, headers)

    assert set(capabilities["allowed_capture_modes"]) == {"live_audio", "spoken_recap"}
    assert capabilities["capture_restriction"] is None


async def test_available_formats_come_from_the_seeded_templates(client: AsyncClient) -> None:
    # Read from note_templates rather than a hardcoded map, so seeding a template for
    # a jurisdiction makes the format available with no code change -- the same
    # property the pipeline already has.
    ph = await _capabilities(client, await _account(client, "Asia/Manila"))
    us = await _capabilities(client, await _account(client, "America/Los_Angeles"))

    assert set(ph["available_formats"]) == {"fdar", "soapie"}
    assert set(us["available_formats"]) == {"shift_note", "soapie"}


async def test_switching_jurisdiction_changes_the_limits_immediately(
    client: AsyncClient,
) -> None:
    # The point of publishing limits rather than minting them into a token: a switch
    # takes effect on the next read, with no re-login and no stale capability.
    headers = await _account(client, "America/Los_Angeles")
    assert "live_audio" in (await _capabilities(client, headers))["allowed_capture_modes"]

    switched = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"jurisdiction": "PH"}
    )
    assert switched.status_code == 200

    assert switched.json()["capabilities"]["allowed_capture_modes"] == ["spoken_recap"]
    assert (await _capabilities(client, headers))["allowed_capture_modes"] == ["spoken_recap"]


async def test_the_access_token_carries_no_capabilities(client: AsyncClient) -> None:
    # Guards the design decision, not an implementation detail: capabilities must not
    # be mintable into a bearer token, or a token issued before a jurisdiction switch
    # would keep authorising what that jurisdiction forbids.
    import jwt

    body = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})

    assert set(claims) == {"sub", "type", "iat", "exp", "jti"}
