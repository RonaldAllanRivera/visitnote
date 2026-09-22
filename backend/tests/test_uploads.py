"""Audio upload.

Field staff upload over cellular. A ninety-minute recording that fails at 95% of a
single PUT loses the whole visit, so anything sizeable is uploaded in parts that can
be retried individually and resumed after the connection drops.

Storage sits behind a Protocol with a fake, so these tests exercise the negotiation,
the size thresholds, and the ownership rules without touching a network or a bucket.
"""

import uuid

from httpx import AsyncClient

from app.models.enums import VisitStatus

PASSWORD = "a-sufficiently-long-password"
MEGABYTE = 1024 * 1024


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def _account(client: AsyncClient) -> dict[str, str]:
    body = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _visit(client: AsyncClient, headers: dict[str, str]) -> str:
    care_recipient = (
        await client.post("/api/v1/clients", headers=headers, json={"label": "Mrs R"})
    ).json()["id"]
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json={
            "client_id": care_recipient,
            "capture_mode": "spoken_recap",
            "idempotency_key": str(uuid.uuid4()),
            # This account never completes onboarding, so it has no default note
            # format; these tests exercise upload mechanics, not format resolution,
            # so a format valid for the (default US) jurisdiction is supplied explicitly.
            "note_format": "shift_note",
        },
    )
    return response.json()["id"]


async def _begin(
    client: AsyncClient,
    headers: dict[str, str],
    visit_id: str,
    *,
    size: int,
    content_type: str = "audio/webm",
):
    return await client.post(
        f"/api/v1/visits/{visit_id}/upload",
        headers=headers,
        json={"content_type": content_type, "size_bytes": size},
    )


# -- negotiation -----------------------------------------------------------------


async def test_a_small_file_gets_a_single_upload_url(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await _begin(client, headers, await _visit(client, headers), size=2 * MEGABYTE)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "single"
    assert body["url"]


async def test_a_large_file_gets_a_multipart_upload(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await _begin(client, headers, await _visit(client, headers), size=60 * MEGABYTE)

    body = response.json()
    assert body["mode"] == "multipart"
    assert body["upload_id"]
    assert body["part_size_bytes"] > 0


async def test_multipart_issues_one_url_per_part(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await _begin(client, headers, await _visit(client, headers), size=60 * MEGABYTE)

    body = response.json()
    expected = -(-60 * MEGABYTE // body["part_size_bytes"])  # ceiling division
    assert len(body["parts"]) == expected
    assert [part["part_number"] for part in body["parts"]] == list(range(1, expected + 1))


async def test_an_oversized_file_is_refused(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await _begin(client, headers, await _visit(client, headers), size=400 * MEGABYTE)
    assert response.status_code == 422


async def test_an_empty_file_is_refused(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await _begin(client, headers, await _visit(client, headers), size=0)
    assert response.status_code == 422


async def test_a_non_audio_content_type_is_refused(client: AsyncClient) -> None:
    """The bucket holds audio. Accepting anything else makes it a file-sharing host."""
    headers = await _account(client)
    response = await _begin(
        client,
        headers,
        await _visit(client, headers),
        size=MEGABYTE,
        content_type="application/zip",
    )
    assert response.status_code == 422


# -- resume ----------------------------------------------------------------------


async def test_reissuing_part_urls_keeps_the_same_upload(client: AsyncClient) -> None:
    """Resume after a dropped connection: the client asks for fresh URLs for the parts
    it has not finished, and must continue the upload it already started rather than
    beginning a new one and orphaning the uploaded parts."""
    headers = await _account(client)
    visit_id = await _visit(client, headers)
    first = (await _begin(client, headers, visit_id, size=60 * MEGABYTE)).json()

    resumed = await client.post(
        f"/api/v1/visits/{visit_id}/upload/parts",
        headers=headers,
        json={"part_numbers": [3, 4]},
    )

    assert resumed.status_code == 200
    assert resumed.json()["upload_id"] == first["upload_id"]
    assert [p["part_number"] for p in resumed.json()["parts"]] == [3, 4]


async def test_requesting_parts_without_an_upload_is_rejected(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await client.post(
        f"/api/v1/visits/{await _visit(client, headers)}/upload/parts",
        headers=headers,
        json={"part_numbers": [1]},
    )
    assert response.status_code == 409


# -- completion ------------------------------------------------------------------


async def test_completing_a_single_upload_marks_the_visit_uploaded(
    client: AsyncClient,
) -> None:
    headers = await _account(client)
    visit_id = await _visit(client, headers)
    await _begin(client, headers, visit_id, size=2 * MEGABYTE)

    response = await client.post(
        f"/api/v1/visits/{visit_id}/upload/complete", headers=headers, json={"parts": []}
    )
    assert response.status_code == 200
    assert response.json()["status"] == VisitStatus.UPLOADED


async def test_completing_records_the_audio_key(client: AsyncClient) -> None:
    headers = await _account(client)
    visit_id = await _visit(client, headers)
    await _begin(client, headers, visit_id, size=2 * MEGABYTE)
    await client.post(
        f"/api/v1/visits/{visit_id}/upload/complete", headers=headers, json={"parts": []}
    )

    visit = (await client.get(f"/api/v1/visits/{visit_id}", headers=headers)).json()
    assert visit["audio_key"]


async def test_completing_a_multipart_upload_requires_the_part_list(
    client: AsyncClient,
) -> None:
    """S3 needs every part's ETag to assemble the object. Omitting them would leave
    an incomplete upload silently accruing storage charges."""
    headers = await _account(client)
    visit_id = await _visit(client, headers)
    await _begin(client, headers, visit_id, size=60 * MEGABYTE)

    response = await client.post(
        f"/api/v1/visits/{visit_id}/upload/complete", headers=headers, json={"parts": []}
    )
    assert response.status_code == 422


async def test_completing_a_multipart_upload_succeeds_with_parts(
    client: AsyncClient,
) -> None:
    headers = await _account(client)
    visit_id = await _visit(client, headers)
    begun = (await _begin(client, headers, visit_id, size=60 * MEGABYTE)).json()

    response = await client.post(
        f"/api/v1/visits/{visit_id}/upload/complete",
        headers=headers,
        json={
            "parts": [
                {"part_number": part["part_number"], "etag": f"etag-{part['part_number']}"}
                for part in begun["parts"]
            ]
        },
    )
    assert response.status_code == 200


async def test_cannot_complete_an_upload_that_never_began(client: AsyncClient) -> None:
    headers = await _account(client)
    response = await client.post(
        f"/api/v1/visits/{await _visit(client, headers)}/upload/complete",
        headers=headers,
        json={"parts": []},
    )
    assert response.status_code == 409


# -- isolation -------------------------------------------------------------------


async def test_cannot_start_an_upload_for_someone_elses_visit(
    client: AsyncClient,
) -> None:
    mine, theirs = await _account(client), await _account(client)
    visit_id = await _visit(client, theirs)

    # The owner's identical request must succeed. Without this half, the test would
    # also pass against a route that does not exist at all -- a 404 for the wrong
    # reason is not tenant isolation.
    assert (await _begin(client, theirs, visit_id, size=MEGABYTE)).status_code == 200

    response = await _begin(client, mine, visit_id, size=MEGABYTE)
    assert response.status_code == 404


async def test_upload_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/visits/{uuid.uuid4()}/upload",
        json={"content_type": "audio/webm", "size_bytes": 1024},
    )
    assert response.status_code == 401
