"""Visit creation.

Two properties carry real weight here.

**Idempotency.** Field staff create visits on cellular connections that drop. A retry
must return the visit that already exists rather than create a second one -- a
duplicate is a second unit of the user's monthly quota consumed for one piece of work,
and a second orphaned recording to store.

**Consent.** Recording a live visit without the patient's acknowledgment is the single
clearest legal exposure in the product, so the API refuses to open a live recording
without it rather than trusting the client to have asked.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConsentLog, Visit

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


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


async def _client_record(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/api/v1/clients", headers=headers, json={"label": "Mrs R"})
    return response.json()["id"]


def _payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "capture_mode": "spoken_recap",
        "idempotency_key": str(uuid.uuid4()),
    }
    payload.update(overrides)
    return payload


async def _create(client: AsyncClient, headers: dict[str, str], payload: dict) -> dict:
    response = await client.post("/api/v1/visits", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# -- creation --------------------------------------------------------------------


async def test_a_new_visit_starts_in_the_recording_state(client: AsyncClient) -> None:
    headers = await _account(client)
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))
    assert visit["status"] == "recording"


async def test_visit_defaults_to_the_users_note_format(client: AsyncClient) -> None:
    """An RN gets SOAPIE without having to choose it on every visit."""
    headers = await _account(client)
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))
    assert visit["note_format"] == "soapie"


async def test_an_explicit_note_format_overrides_the_default(client: AsyncClient) -> None:
    headers = await _account(client)
    visit = await _create(
        client, headers, _payload(await _client_record(client, headers), note_format="shift_note")
    )
    assert visit["note_format"] == "shift_note"


async def test_visit_captures_the_users_timezone(client: AsyncClient) -> None:
    """The visit carries the zone it was recorded in, so an overnight shift renders on
    the right calendar day for every later reader."""
    headers = await _account(client, timezone="Asia/Manila")
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))
    assert visit["timezone"] == "Asia/Manila"


# -- idempotency -----------------------------------------------------------------


async def test_replaying_the_same_key_returns_the_same_visit(client: AsyncClient) -> None:
    headers = await _account(client)
    payload = _payload(await _client_record(client, headers))

    first = await _create(client, headers, payload)
    second = await client.post("/api/v1/visits", headers=headers, json=payload)

    assert second.status_code in (200, 201)
    assert second.json()["id"] == first["id"]


async def test_replaying_a_key_does_not_create_a_second_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = await _account(client)
    payload = _payload(await _client_record(client, headers))

    await _create(client, headers, payload)
    await client.post("/api/v1/visits", headers=headers, json=payload)

    rows = (
        await session.execute(
            select(Visit).where(Visit.idempotency_key == payload["idempotency_key"])
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_a_different_key_creates_a_different_visit(client: AsyncClient) -> None:
    headers = await _account(client)
    client_id = await _client_record(client, headers)

    first = await _create(client, headers, _payload(client_id))
    second = await _create(client, headers, _payload(client_id))
    assert first["id"] != second["id"]


async def test_two_users_may_use_the_same_key(client: AsyncClient) -> None:
    """Keys are generated client-side, so uniqueness must be scoped per user.

    A globally unique constraint would let one user's key collide with another's and
    hand back a visit belonging to someone else.
    """
    mine, theirs = await _account(client), await _account(client)
    key = str(uuid.uuid4())

    first = await _create(
        client, mine, _payload(await _client_record(client, mine), idempotency_key=key)
    )
    second = await _create(
        client, theirs, _payload(await _client_record(client, theirs), idempotency_key=key)
    )
    assert first["id"] != second["id"]


# -- consent ---------------------------------------------------------------------


async def test_live_recording_requires_consent(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json=_payload(await _client_record(client, headers), capture_mode="live_audio"),
    )
    assert response.status_code == 422


async def test_live_recording_with_consent_is_accepted(client: AsyncClient) -> None:
    headers = await _account(client)
    visit = await _create(
        client,
        headers,
        _payload(
            await _client_record(client, headers),
            capture_mode="live_audio",
            consent_acknowledged=True,
        ),
    )
    assert visit["capture_mode"] == "live_audio"


async def test_consent_is_recorded_for_audit(
    client: AsyncClient, session: AsyncSession
) -> None:
    """"They said it was fine" is not a defence. The acknowledgment is a stored record."""
    headers = await _account(client)
    visit = await _create(
        client,
        headers,
        _payload(
            await _client_record(client, headers),
            capture_mode="live_audio",
            consent_acknowledged=True,
        ),
    )

    logged = (
        await session.execute(
            select(ConsentLog).where(ConsentLog.visit_id == uuid.UUID(visit["id"]))
        )
    ).scalar_one()
    assert logged.capture_mode == "live_audio"
    assert logged.acknowledged is True


async def test_spoken_recap_is_logged_too(
    client: AsyncClient, session: AsyncSession
) -> None:
    """No third party is recorded, but which mode was used still matters later."""
    headers = await _account(client)
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))

    logged = (
        await session.execute(
            select(ConsentLog).where(ConsentLog.visit_id == uuid.UUID(visit["id"]))
        )
    ).scalar_one()
    assert logged.capture_mode == "spoken_recap"


# -- isolation -------------------------------------------------------------------


async def test_cannot_open_a_visit_against_someone_elses_client(
    client: AsyncClient,
) -> None:
    mine, theirs = await _account(client), await _account(client)
    their_client = await _client_record(client, theirs)

    response = await client.post("/api/v1/visits", headers=mine, json=_payload(their_client))
    assert response.status_code == 404


async def test_cannot_read_another_users_visit(client: AsyncClient) -> None:
    mine, theirs = await _account(client), await _account(client)
    visit = await _create(client, theirs, _payload(await _client_record(client, theirs)))

    response = await client.get(f"/api/v1/visits/{visit['id']}", headers=mine)
    assert response.status_code == 404


async def test_visit_status_is_readable_by_its_owner(client: AsyncClient) -> None:
    headers = await _account(client)
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))

    response = await client.get(f"/api/v1/visits/{visit['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "recording"


async def test_creating_a_visit_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/visits", json=_payload(str(uuid.uuid4())))
    assert response.status_code == 401


# -- jurisdiction ------------------------------------------------------------------


async def test_a_visit_carries_the_jurisdiction_it_was_captured_under(
    client: AsyncClient,
) -> None:
    headers = await _account(client, timezone="Asia/Manila")
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))
    assert visit["jurisdiction"] == "PH"


async def test_changing_jurisdiction_does_not_rewrite_existing_visits(
    client: AsyncClient,
) -> None:
    """The same argument the row already makes for timezone.

    A nurse who moves must not have the notes she already captured re-resolved against
    a different jurisdiction's template.
    """
    headers = await _account(client, timezone="Asia/Manila")
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))

    await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": "US"})

    unchanged = (await client.get(f"/api/v1/visits/{visit['id']}", headers=headers)).json()
    assert unchanged["jurisdiction"] == "PH"


# -- prohibited capture modes -----------------------------------------------------


async def test_a_ph_user_cannot_open_a_live_recording(client: AsyncClient) -> None:
    """RA 4200 requires all-party consent, with criminal liability.

    A ward holds twenty to forty patients, their families, and other staff. Consent
    from all parties is not obtainable, and a checkbox does not obtain it on a
    bystander's behalf. Rejected by the API, not hidden in the UI.
    """
    headers = await _account(client, timezone="Asia/Manila")
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json=_payload(
            await _client_record(client, headers),
            capture_mode="live_audio",
            consent_acknowledged=True,
        ),
    )
    assert response.status_code == 422
    assert "RA 4200" in response.json()["detail"]


async def test_a_ph_user_can_still_dictate_a_spoken_recap(client: AsyncClient) -> None:
    """The PH product is a spoken-recap product, and that path stays open."""
    headers = await _account(client, timezone="Asia/Manila")
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))
    assert visit["capture_mode"] == "spoken_recap"


async def test_a_us_user_may_still_open_a_live_recording(client: AsyncClient) -> None:
    headers = await _account(client, timezone="America/Los_Angeles")
    visit = await _create(
        client,
        headers,
        _payload(
            await _client_record(client, headers),
            capture_mode="live_audio",
            consent_acknowledged=True,
        ),
    )
    assert visit["capture_mode"] == "live_audio"


async def test_replaying_a_key_returns_the_existing_visit_even_for_a_now_prohibited_mode(
    client: AsyncClient,
) -> None:
    """The prohibited-mode check guards creation, not retrieval.

    The idempotency lookup runs first, so a replayed key still returns the visit that
    was already created even when the retried payload's capture_mode would itself be
    rejected for this user's jurisdiction.
    """
    headers = await _account(client, timezone="Asia/Manila")
    payload = _payload(await _client_record(client, headers))
    first = await _create(client, headers, payload)

    replay = await client.post(
        "/api/v1/visits",
        headers=headers,
        json={**payload, "capture_mode": "live_audio", "consent_acknowledged": True},
    )
    assert replay.status_code in (200, 201)
    assert replay.json()["id"] == first["id"]


# -- note format validation -------------------------------------------------------


async def _stranded_account(client: AsyncClient, jurisdiction: str = "PH") -> dict[str, str]:
    """A user who abandoned onboarding before naming a role: no default format set."""
    body = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": jurisdiction})
    return headers


async def test_a_stranded_ph_user_cannot_open_a_visit_with_no_note_format(
    client: AsyncClient,
) -> None:
    """Neither an explicit format nor a default is present: that is an error, not a
    fallback to a US-only format PH seeds no template for.

    Before this guard, the unresolved format silently fell back to shift_note, the
    visit was accepted, a quota unit was spent, and generation died non-retryably
    minutes later for a mistake made here.
    """
    headers = await _stranded_account(client)
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json=_payload(await _client_record(client, headers)),
    )
    assert response.status_code == 422


async def test_a_stranded_us_user_cannot_open_a_visit_with_no_note_format(
    client: AsyncClient,
) -> None:
    headers = await _stranded_account(client, jurisdiction="US")
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json=_payload(await _client_record(client, headers)),
    )
    assert response.status_code == 422


async def test_a_ph_user_cannot_explicitly_request_a_us_only_format(
    client: AsyncClient,
) -> None:
    """PH seeds no shift_note template; posting it explicitly must not bypass the guard
    that a stranded default is already refused by."""
    headers = await _account(client, timezone="Asia/Manila")
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json=_payload(await _client_record(client, headers), note_format="shift_note"),
    )
    assert response.status_code == 422


async def test_a_us_user_cannot_explicitly_request_a_ph_only_format(
    client: AsyncClient,
) -> None:
    headers = await _account(client, timezone="America/Los_Angeles")
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json=_payload(await _client_record(client, headers), note_format="fdar"),
    )
    assert response.status_code == 422


async def test_replaying_a_key_returns_the_existing_visit_even_for_a_now_unsupported_format(
    client: AsyncClient,
) -> None:
    """The format guard runs at creation, not on every read of an idempotency key.

    A user who changes jurisdiction after opening a visit must still get that visit
    back on retry -- the same argument idempotency already makes for capture mode.
    """
    headers = await _account(client, timezone="Asia/Manila")
    payload = _payload(await _client_record(client, headers), note_format="fdar")
    first = await _create(client, headers, payload)

    await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": "US"})

    replay = await client.post("/api/v1/visits", headers=headers, json=payload)
    assert replay.status_code in (200, 201)
    assert replay.json()["id"] == first["id"]
