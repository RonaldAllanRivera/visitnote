"""Correcting a generated note.

The version check is the whole point: a supervisor opening a note in the review queue
while its author edits it on their phone must not silently discard one of them.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.notes import NoteRepository

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def _sections(client: AsyncClient, note_id: uuid.UUID, headers: dict) -> dict:
    return (await client.get(f"/api/v1/notes/{note_id}", headers=headers)).json()


async def test_editing_a_section_bumps_the_version_and_marks_it_edited(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    sections = body["sections"]
    first_key = body["template"]["sections"][0]["key"]
    sections[first_key] = "Corrected by the nurse."

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "sections": sections},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["version"] == body["version"] + 1
    assert updated["edited"] is True
    assert updated["sections"][first_key] == "Corrected by the nurse."


async def test_a_stale_version_is_refused(client: AsyncClient, note_fixture) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    stale = body["version"]
    first_key = body["template"]["sections"][0]["key"]
    # Genuine, distinct edits: an unchanged save is a no-op (Finding 2) and would not
    # bump the version at all, which would make this test pass for the wrong reason.
    sections = dict(body["sections"])
    sections[first_key] = "First edit."
    await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": stale, "sections": sections},
    )

    sections[first_key] = "Second edit, still against the stale version."
    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": stale, "sections": sections},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["current_version"] == stale + 1


async def test_a_refused_edit_leaves_the_note_alone(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    first_key = body["template"]["sections"][0]["key"]
    original = body["sections"][first_key]
    sections = dict(body["sections"])
    sections[first_key] = "Should not be stored."

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"] - 1, "sections": sections},
    )
    assert response.status_code == 409

    after = await _sections(client, note.id, headers)
    assert after["sections"][first_key] == original


async def test_a_stale_conflict_reports_the_version_the_database_actually_holds(
    session_factory: async_sessionmaker[AsyncSession], note_fixture
) -> None:
    """Finding 1, repository level.

    A genuine concurrent-session HTTP race is impractical to force deterministically
    here: the app hands each request its own session via dependency injection, so two
    sequential PATCHes through `client` never leave a session holding a `note` object
    that predates more than one write -- that is exactly why the original
    `test_a_stale_version_is_refused` (one writer, one stale retry) could not catch
    this.

    This drives two independent sessions straight at `NoteRepository` instead.
    Session A loads the note once and holds it. A stand-in for a concurrent author
    (session B) then advances the row *twice* before A ever attempts its write. With
    SQLAlchemy's default `synchronize_session="evaluate"`, A's in-memory `note` would
    appear to satisfy the UPDATE's WHERE clause against A's own stale reading and get
    bumped by exactly one in memory even though zero database rows changed -- so a
    409 built from that object would always claim `expected_version + 1`, regardless
    of how far the row actually moved. The fix (`synchronize_session=False` plus an
    explicit refresh after a failed conditional update) must report what B actually
    committed instead.
    """
    note, _ = note_fixture

    async with session_factory() as session_a, session_factory() as session_b:
        repo_a = NoteRepository(session_a)
        repo_b = NoteRepository(session_b)

        loaded = await repo_a.get_for_user(note.id, note.user_id)
        assert loaded is not None
        starting_version = loaded.version

        # Two independent writes through session B, so the database ends up two
        # versions ahead of the `expected_version` session A is about to use --
        # more than the single `+1` the bug would report.
        for _ in range(2):
            concurrent = await repo_b.get_for_user(note.id, note.user_id)
            assert concurrent is not None
            advanced = await repo_b.update_if_current(
                note=concurrent,
                expected_version=concurrent.version,
                visit_details=None,
                sections=None,
            )
            assert advanced is True

        applied = await repo_a.update_if_current(
            note=loaded,
            expected_version=starting_version,
            visit_details=None,
            sections=None,
        )

        assert applied is False
        assert loaded.version == starting_version + 2


async def test_an_unknown_section_key_is_rejected(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    sections = dict(body["sections"])
    sections["invented_section"] = "text"

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "sections": sections},
    )

    assert response.status_code == 422
    assert "invented_section" in str(response.json()["detail"])


async def test_a_nurses_own_words_are_never_refused(
    client: AsyncClient, note_fixture
) -> None:
    # BANNED_PHRASES governs how the model writes. The author of a clinical record is
    # not subject to it.
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    sections = dict(body["sections"])
    sections[body["template"]["sections"][0]["key"]] = "routine visit"

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "sections": sections},
    )

    assert response.status_code == 200


async def test_editing_another_users_note_is_not_found(
    client: AsyncClient, note_fixture
) -> None:
    note, _ = note_fixture
    other = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    response = await client.patch(
        f"/api/v1/notes/{note.id}", headers=headers, json={"version": 1, "sections": {}}
    )

    assert response.status_code == 404


async def test_visit_details_with_a_wrong_key_is_rejected(
    client: AsyncClient, note_fixture
) -> None:
    """Finding 1: the edit path never enforced VISIT_DETAIL_KEYS the way generation does.

    A payload missing a required key (or carrying one the template does not declare)
    must be refused the same way an unknown section key is, rather than silently
    written -- which is what let a later `GET /notes` 500 permanently for the owner.
    """
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={
            "version": body["version"],
            # Missing visit_date, start_time, end_time -- exactly the shape
            # `_check_keys` rejects for a generation, and must reject here too.
            "visit_details": {"client_label": "Bed 12"},
        },
    )

    assert response.status_code == 422
    assert "visit_details" in str(response.json()["detail"])

    after = await _sections(client, note.id, headers)
    assert after["visit_details"] == body["visit_details"]


async def test_visit_details_with_a_wrong_value_type_is_rejected(
    client: AsyncClient, note_fixture
) -> None:
    """Finding 1's milder, structurally-typed case: a value that is not a string.

    The schema itself (`dict[str, str | None]`) is what rejects this -- there is no
    service-level check to exercise, only the request body failing validation before
    it ever reaches `NoteService.update`.
    """
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    visit_details = dict(body["visit_details"])
    visit_details["client_label"] = {"nested": "not a string"}

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "visit_details": visit_details},
    )

    assert response.status_code == 422

    after = await _sections(client, note.id, headers)
    assert after["visit_details"] == body["visit_details"]


async def test_saving_an_unchanged_note_twice_leaves_the_version_alone(
    client: AsyncClient, note_fixture
) -> None:
    """Finding 2: opening a note and clicking Save without changing anything must not
    bump `version` or `edited` -- that false bump is what makes a concurrent reader's
    own, real save collide with a 409 caused by a non-event.
    """
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    payload = {
        "version": body["version"],
        "sections": body["sections"],
        "visit_details": body["visit_details"],
    }

    first = await client.patch(f"/api/v1/notes/{note.id}", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["version"] == body["version"]
    assert first.json()["edited"] is False

    second = await client.patch(f"/api/v1/notes/{note.id}", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["version"] == body["version"]
    assert second.json()["edited"] is False


async def test_a_payload_omitting_sections_is_not_treated_as_changing_it(
    client: AsyncClient, note_fixture
) -> None:
    """Comparing only the fields the payload actually carries.

    A payload that changes visit_details but omits sections entirely must not be
    treated as if it cleared or changed sections -- and, since that leaves nothing
    that actually changed here, must not bump the version either.
    """
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "visit_details": body["visit_details"]},
    )

    assert response.status_code == 200
    assert response.json()["version"] == body["version"]
    assert response.json()["edited"] is False
    assert response.json()["sections"] == body["sections"]
