"""Care recipient records.

Stored as a pseudonymous label only. The label limits what a database leak exposes; it
does not de-identify the audio, which carries the patient's voice and conditions
regardless of what the record is called.

Tenant isolation is the property that matters most here and is asserted directly: one
user must never be able to read, modify, or even confirm the existence of another's
records.
"""

import uuid

from httpx import AsyncClient

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def _account(client: AsyncClient) -> dict[str, str]:
    body = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _create(client: AsyncClient, headers: dict[str, str], label: str = "Client A") -> dict:
    response = await client.post("/api/v1/clients", headers=headers, json={"label": label})
    assert response.status_code == 201, response.text
    return response.json()


# -- ownership -------------------------------------------------------------------


async def test_created_record_is_returned_with_its_label(client: AsyncClient) -> None:
    headers = await _account(client)
    assert (await _create(client, headers, "Mrs R, Tuesdays"))["label"] == "Mrs R, Tuesdays"


async def test_listing_returns_only_your_own_records(client: AsyncClient) -> None:
    mine, theirs = await _account(client), await _account(client)
    await _create(client, mine, "Mine")
    await _create(client, theirs, "Theirs")

    labels = [row["label"] for row in (await client.get("/api/v1/clients", headers=mine)).json()]
    assert labels == ["Mine"]


async def test_another_users_record_reports_not_found(client: AsyncClient) -> None:
    """404 rather than 403. A 403 confirms the record exists, which is itself a leak."""
    mine, theirs = await _account(client), await _account(client)
    other = await _create(client, theirs)

    response = await client.get(f"/api/v1/clients/{other['id']}", headers=mine)
    assert response.status_code == 404


async def test_another_users_record_cannot_be_edited(client: AsyncClient) -> None:
    mine, theirs = await _account(client), await _account(client)
    other = await _create(client, theirs)

    response = await client.patch(
        f"/api/v1/clients/{other['id']}", headers=mine, json={"label": "hijacked"}
    )
    assert response.status_code == 404


async def test_another_users_record_cannot_be_deleted(client: AsyncClient) -> None:
    mine, theirs = await _account(client), await _account(client)
    other = await _create(client, theirs)

    response = await client.delete(f"/api/v1/clients/{other['id']}", headers=mine)
    assert response.status_code == 404

    still_there = await client.get(f"/api/v1/clients/{other['id']}", headers=theirs)
    assert still_there.status_code == 200


# -- lifecycle -------------------------------------------------------------------


async def test_label_can_be_changed(client: AsyncClient) -> None:
    headers = await _account(client)
    record = await _create(client, headers)

    response = await client.patch(
        f"/api/v1/clients/{record['id']}", headers=headers, json={"label": "Renamed"}
    )
    assert response.json()["label"] == "Renamed"


async def test_deleting_removes_it_from_the_list(client: AsyncClient) -> None:
    headers = await _account(client)
    record = await _create(client, headers)

    deleted = await client.delete(f"/api/v1/clients/{record['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/clients", headers=headers)).json() == []


async def test_records_are_deactivated_rather_than_erased(client: AsyncClient) -> None:
    """Visits reference the record. Hard deletion would orphan signed documentation,
    which is a legal record that must remain readable."""
    headers = await _account(client)
    record = await _create(client, headers)
    await client.delete(f"/api/v1/clients/{record['id']}", headers=headers)

    response = await client.get(f"/api/v1/clients/{record['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False


# -- validation ------------------------------------------------------------------


async def test_a_blank_label_is_rejected(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await client.post("/api/v1/clients", headers=headers, json={"label": "   "})
    assert response.status_code == 422


async def test_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/clients")).status_code == 401
