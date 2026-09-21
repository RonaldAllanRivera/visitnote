"""Seeded note templates.

The templates are the contract shared by the review editor, the flag engine, and the
LLM layer. A missing or malformed seed is not a cosmetic problem -- it is a format
that cannot be rendered or validated.
"""

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteFormat, NoteTemplate


async def test_both_formats_are_seeded_and_active(session: AsyncSession) -> None:
    rows = (await session.execute(select(NoteTemplate))).scalars().all()

    by_format = {row.format: row for row in rows}
    assert set(by_format) == {NoteFormat.SHIFT_NOTE, NoteFormat.SOAPIE}
    assert all(row.is_active for row in rows)


async def test_templates_pin_a_prompt_version_provider_and_model(
    session: AsyncSession,
) -> None:
    """Every note must be traceable to exactly what generated it."""
    rows = (await session.execute(select(NoteTemplate))).scalars().all()

    for row in rows:
        assert row.prompt_version, row.format
        assert row.llm_provider, row.format
        assert row.model_id, row.format


async def test_section_ordering_is_contiguous_and_flag_codes_are_unique(
    session: AsyncSession,
) -> None:
    rows = (await session.execute(select(NoteTemplate))).scalars().all()

    for row in rows:
        sections = row.section_schema["sections"]
        assert [s["order"] for s in sections] == list(range(1, len(sections) + 1))

        codes = [f["code"] for f in row.flag_schema["flags"]]
        assert len(codes) == len(set(codes)), f"duplicate flag code in {row.format}"

        severities = {f["severity"] for f in row.flag_schema["flags"]}
        assert severities <= {"info", "warning", "critical"}


async def test_soapie_requires_a_necessity_rationale_flag(session: AsyncSession) -> None:
    """The flag that makes a skilled visit billable is present by definition."""
    row = (
        await session.execute(select(NoteTemplate).where(NoteTemplate.format == NoteFormat.SOAPIE))
    ).scalar_one()

    critical = {f["code"] for f in row.flag_schema["flags"] if f["severity"] == "critical"}
    assert "MISSING_NECESSITY_RATIONALE" in critical
    assert "MISSING_HOMEBOUND" in critical


async def test_a_new_format_value_needs_no_type_alteration(session: AsyncSession) -> None:
    """The point of leaving the ENUM: a fourth format is an INSERT, not a DDL change.

    This inserts a format string no Python enum member covers. Under the old
    Postgres ENUM it raised InvalidTextRepresentation.
    """
    await session.execute(
        sa.text(
            """
            INSERT INTO note_templates (
                format, version, name, section_schema, flag_schema,
                prompt_version, llm_provider, model_id, is_active
            ) VALUES (
                'a_format_from_the_future', 1, 'Future', '{"sections": []}'::jsonb,
                '{"flags": []}'::jsonb, 'future_v1', 'anthropic', 'test-model', false
            )
            """
        )
    )
    await session.commit()

    # This test commits against the real, shared database (see conftest -- there is
    # no per-test rollback or truncation). The INSERT above is already durable, so if
    # the assertion below fails -- or anything else raises before the DELETE runs --
    # the row must still be removed, or it poisons every later run: it breaks the
    # exact-set assertion in test_both_formats_are_seeded_and_active on every
    # subsequent test session. The rollback() clears whatever transaction state the
    # try block left behind (a failed assertion leaves a clean, still-usable
    # transaction; a DBAPI error would leave an aborted one) so the cleanup DELETE
    # always runs in a fresh transaction rather than risking "current transaction is
    # aborted" on top of the original failure.
    try:
        stored = (
            await session.execute(
                sa.text("SELECT format FROM note_templates WHERE prompt_version = 'future_v1'")
            )
        ).scalar_one()
        assert stored == "a_format_from_the_future"
    finally:
        await session.rollback()
        await session.execute(
            sa.text("DELETE FROM note_templates WHERE prompt_version = 'future_v1'")
        )
        await session.commit()


async def test_the_note_format_enum_type_is_gone(session: AsyncSession) -> None:
    exists = (
        await session.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'note_format')")
        )
    ).scalar_one()
    assert exists is False
