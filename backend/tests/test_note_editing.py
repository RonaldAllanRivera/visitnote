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
    await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": stale, "sections": body["sections"]},
    )

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": stale, "sections": body["sections"]},
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
