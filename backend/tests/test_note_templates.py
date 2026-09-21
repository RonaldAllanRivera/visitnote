"""Seeded note templates.

The templates are the contract shared by the review editor, the flag engine, and the
LLM layer. A missing or malformed seed is not a cosmetic problem -- it is a format
that cannot be rendered or validated.
"""

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
        await session.execute(
            select(NoteTemplate).where(NoteTemplate.format == NoteFormat.SOAPIE)
        )
    ).scalar_one()

    critical = {f["code"] for f in row.flag_schema["flags"] if f["severity"] == "critical"}
    assert "MISSING_NECESSITY_RATIONALE" in critical
    assert "MISSING_HOMEBOUND" in critical
