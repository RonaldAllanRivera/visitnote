"""Onboarding.

Registration creates an account; onboarding makes it usable. Kept separate so a user
who abandons onboarding still has an account they can come back to.

The timezone captured here is load-bearing: every visit the user records inherits it,
and an overnight shift documented in the wrong zone lands on the wrong calendar day.
"""

import uuid

from httpx import AsyncClient

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    body = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _account(client: AsyncClient, timezone: str = "America/Los_Angeles") -> dict[str, str]:
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


async def test_onboarding_stores_the_profile(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    response = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={
            "full_name": "Alex Reyes",
            "role_title": "rn",
            "timezone": "America/Los_Angeles",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Alex Reyes"
    assert body["timezone"] == "America/Los_Angeles"


async def test_a_nurse_defaults_to_the_soapie_format(client: AsyncClient) -> None:
    """Role sets the default note format so the user does not have to know the term."""
    headers = await _auth_headers(client)
    response = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"role_title": "rn"}
    )
    assert response.json()["default_note_format"] == "soapie"


async def test_a_caregiver_defaults_to_the_shift_note_format(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    response = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"role_title": "hha"}
    )
    assert response.json()["default_note_format"] == "shift_note"


async def test_an_explicit_format_overrides_the_role_default(client: AsyncClient) -> None:
    """An RN doing non-clinical shifts must be able to say so."""
    headers = await _auth_headers(client)
    response = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"role_title": "rn", "default_note_format": "shift_note"},
    )
    assert response.json()["default_note_format"] == "shift_note"


async def test_an_unknown_timezone_is_rejected(client: AsyncClient) -> None:
    """A bad zone must fail here, not silently mis-date notes months later."""
    headers = await _auth_headers(client)
    response = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"timezone": "Mars/Olympus_Mons"}
    )
    assert response.status_code == 422


async def test_a_partial_update_leaves_other_fields_alone(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"full_name": "Alex Reyes", "timezone": "Asia/Manila"},
    )
    response = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"role_title": "cna"}
    )
    assert response.json()["full_name"] == "Alex Reyes"
    assert response.json()["timezone"] == "Asia/Manila"


async def test_onboarding_requires_authentication(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/auth/me", json={"timezone": "UTC"})
    assert response.status_code == 401


async def test_a_user_cannot_make_themselves_staff(client: AsyncClient) -> None:
    """The most direct privilege escalation there is: unknown fields must not be applied."""
    headers = await _auth_headers(client)
    response = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"timezone": "UTC", "is_staff": True, "is_demo": True},
    )
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert response.json()["is_staff"] is False


async def test_onboarding_derives_jurisdiction_from_the_timezone(
    client: AsyncClient,
) -> None:
    headers = await _account(client)
    body = (
        await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"role_title": "rn", "timezone": "Asia/Manila"},
        )
    ).json()
    assert body["jurisdiction"] == "PH"


async def test_an_explicit_jurisdiction_overrides_the_derived_one(
    client: AsyncClient,
) -> None:
    """A Filipino nurse working a US telehealth contract is a real case.

    The derivation is a default, not a determination.
    """
    headers = await _account(client)
    body = (
        await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"timezone": "Asia/Manila", "jurisdiction": "US"},
        )
    ).json()
    assert body["jurisdiction"] == "US"


async def test_a_new_account_defaults_to_us_before_onboarding(client: AsyncClient) -> None:
    headers = await _account(client)
    body = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert body["jurisdiction"] == "US"


async def test_switching_jurisdiction_reconciles_a_stranded_note_format(
    client: AsyncClient,
) -> None:
    """Switching PH -> US must not leave the user pointing at a format that has no
    template in their new jurisdiction.

    A PH RN defaults to fdar. There is no (US, fdar) template, so without
    reconciliation their next visit would resolve to None and fail in the pipeline --
    a failure at generation time, minutes later, for a mistake made at the switch.
    """
    headers = await _account(client)
    ph = (
        await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"role_title": "rn", "timezone": "Asia/Manila"},
        )
    ).json()
    assert ph["default_note_format"] == "fdar"

    us = (
        await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": "US"})
    ).json()
    assert us["jurisdiction"] == "US"
    assert us["default_note_format"] == "soapie"


async def test_switching_jurisdiction_keeps_a_format_that_is_still_valid(
    client: AsyncClient,
) -> None:
    """Reconciliation only fires when the format is actually stranded.

    soapie exists in both jurisdictions, so a US RN who moves to PH keeps it rather
    than being silently switched to fdar.
    """
    headers = await _account(client)
    await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"role_title": "rn", "timezone": "America/Los_Angeles"},
    )
    moved = (
        await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": "PH"})
    ).json()
    assert moved["default_note_format"] == "soapie"


async def test_a_ph_rn_defaults_to_fdar_and_a_us_rn_to_soapie(client: AsyncClient) -> None:
    """Role alone cannot pick a format once there are two jurisdictions.

    An RN on a Manila ward charts FDAR; an RN doing US home health charts SOAPIE.
    """
    ph = await _account(client)
    ph_profile = (
        await client.patch(
            "/api/v1/auth/me",
            headers=ph,
            json={"role_title": "rn", "timezone": "Asia/Manila"},
        )
    ).json()
    assert ph_profile["default_note_format"] == "fdar"

    us = await _account(client)
    us_profile = (
        await client.patch(
            "/api/v1/auth/me",
            headers=us,
            json={"role_title": "rn", "timezone": "America/Los_Angeles"},
        )
    ).json()
    assert us_profile["default_note_format"] == "soapie"
