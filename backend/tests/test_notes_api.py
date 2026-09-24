"""Reading a note.

The editor renders from the template's section schema, so the read has to carry that
schema -- and it has to be the schema of the template that produced the note, not
whichever one is active when someone opens it.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteTemplate

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def test_reading_a_note_returns_its_sections_and_flags(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture

    response = await client.get(f"/api/v1/notes/{note.id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(note.id)
    assert body["version"] == 1
    assert body["edited"] is False
    assert set(body["sections"]) == {s["key"] for s in body["template"]["sections"]}


async def test_the_read_carries_the_schema_of_the_producing_template(
    client: AsyncClient, session: AsyncSession, note_fixture
) -> None:
    # The whole point of the foreign key. With a v2 seeded and active, resolving by
    # (jurisdiction, format) would hand the editor v2's schema for a note whose
    # sections were shaped by v1.
    note, headers = note_fixture
    produced_by = (
        await session.execute(select(NoteTemplate).where(NoteTemplate.id == note.note_template_id))
    ).scalar_one()
    v2 = NoteTemplate(
        jurisdiction=produced_by.jurisdiction,
        format=produced_by.format,
        version=produced_by.version + 1,
        name=f"{produced_by.name} v{produced_by.version + 1}",
        section_schema={
            "sections": [
                {"key": "completely_different", "label": "Different", "order": 1,
                 "description": "Only in v2."}
            ]
        },
        flag_schema=produced_by.flag_schema,
        requires_diarization=produced_by.requires_diarization,
        prompt_version=produced_by.prompt_version,
        llm_provider=produced_by.llm_provider,
        model_id=produced_by.model_id,
        is_active=True,
    )
    session.add(v2)
    await session.commit()

    # This test commits against the real, shared database (see conftest -- there is
    # no per-test rollback or truncation). Leaving `v2` active would permanently
    # change what `NoteTemplateRepository.get_active()` resolves for US shift notes
    # in every test that runs afterward, in this run and in every run after it. The
    # cleanup below removes it regardless of whether the assertions pass, matching
    # the convention in test_note_templates.py.
    try:
        body = (await client.get(f"/api/v1/notes/{note.id}", headers=headers)).json()

        assert body["template"]["version"] == produced_by.version
        assert "completely_different" not in {s["key"] for s in body["template"]["sections"]}
    finally:
        await session.rollback()
        await session.delete(await session.get(NoteTemplate, v2.id))
        await session.commit()


async def test_another_users_note_is_not_found(
    client: AsyncClient, note_fixture
) -> None:
    # 404 rather than 403: a caller must not be able to probe for note ids they do
    # not own.
    note, _ = note_fixture
    other = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    response = await client.get(f"/api/v1/notes/{note.id}", headers=headers)

    assert response.status_code == 404


async def test_the_list_returns_your_own_notes_newest_first(
    client: AsyncClient, two_notes_fixture
) -> None:
    (older, newer), headers = two_notes_fixture

    body = (await client.get("/api/v1/notes", headers=headers)).json()

    assert [item["id"] for item in body] == [str(newer.id), str(older.id)]


async def test_the_list_counts_flags_by_severity(
    client: AsyncClient, note_fixture
) -> None:
    # Aggregated in SQL over note_flags rather than by counting the JSONB payload in
    # Python: that normalized table exists for exactly this access pattern.
    _note, headers = note_fixture

    body = (await client.get("/api/v1/notes", headers=headers)).json()

    assert body[0]["flag_counts"]["critical"] >= 1


async def test_the_list_excludes_other_users_notes(
    client: AsyncClient, note_fixture
) -> None:
    _, _ = note_fixture
    other = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    body = (await client.get("/api/v1/notes", headers=headers)).json()

    assert body == []
