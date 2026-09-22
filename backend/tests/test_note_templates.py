"""Seeded note templates.

The templates are the contract shared by the review editor, the flag engine, and the
LLM layer. A missing or malformed seed is not a cosmetic problem -- it is a format
that cannot be rendered or validated.
"""

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteFormat, NoteTemplate
from app.models.enums import Jurisdiction
from app.repositories.note_templates import NoteTemplateRepository


async def test_both_formats_are_seeded_and_active(session: AsyncSession) -> None:
    rows = (await session.execute(select(NoteTemplate))).scalars().all()

    # Four rows now, not two: PH SOAPIE and PH FDAR joined the original US pair in
    # this phase. Checked as a set of formats rather than per-jurisdiction, since
    # soapie itself now has two rows (US and PH) and this test only cares which
    # formats exist at all.
    by_format = {row.format: row for row in rows}
    assert set(by_format) == {NoteFormat.SHIFT_NOTE, NoteFormat.SOAPIE, NoteFormat.FDAR}
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
    """The flag that makes a skilled visit billable is present by definition.

    Scoped to US: PH SOAPIE shares the "soapie" format value but drops this exact
    flag (it is a CMS survey requirement with no PhilHealth analogue), so an
    unscoped query would now return two rows and `.scalar_one()` would raise.
    """
    row = (
        await session.execute(
            select(NoteTemplate).where(
                NoteTemplate.jurisdiction == Jurisdiction.US,
                NoteTemplate.format == NoteFormat.SOAPIE,
            )
        )
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
                jurisdiction, format, version, name, section_schema, flag_schema,
                requires_diarization, prompt_version, llm_provider, model_id, is_active
            ) VALUES (
                'PH', 'a_format_from_the_future', 1, 'Future', '{"sections": []}'::jsonb,
                '{"flags": []}'::jsonb, false, 'future_v1', 'anthropic', 'test-model', false
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


async def test_the_same_format_can_exist_in_two_jurisdictions(
    session: AsyncSession,
) -> None:
    """The constraint that makes PH SOAPIE possible.

    Filipino nurses chart SOAPIE too, but PH SOAPIE must not flag homebound status.
    Same format, different flag schema, two rows -- which the old (format, version)
    unique constraint forbade.

    Version 2 and a synthetic prompt_version, deliberately not `(PH, soapie, 1)` /
    `ph_soapie_v1`: Task 9 seeded exactly that row for real, so reusing it here would
    collide with the unique constraint this test exists to prove permits two
    jurisdictions -- and the cleanup DELETE below is keyed on prompt_version, so
    reusing the real one would delete the real seeded row as a side effect of this
    test, not just this test's own fixture.
    """
    template = NoteTemplate(
        jurisdiction=Jurisdiction.PH,
        format=NoteFormat.SOAPIE,
        version=2,
        name="PH Skilled Nursing Note (test fixture)",
        section_schema={"sections": []},
        flag_schema={"flags": []},
        requires_diarization=False,
        prompt_version="ph_soapie_test_fixture_v1",
        llm_provider="anthropic",
        model_id="test-model",
        is_active=False,
    )
    session.add(template)
    await session.commit()

    # This test commits against the real, shared database (see conftest -- there is
    # no per-test rollback or truncation), so the PH row above is already durable. If
    # the assertion below fails, the row must still be removed or it poisons every
    # later run -- and worse than the sibling `a_format_from_the_future` case, a
    # stray PH SOAPIE row makes any later `.scalar_one()` filtered on
    # `format == SOAPIE` raise `MultipleResultsFound` instead of just returning a
    # wrong row. rollback() first clears whatever transaction state the try block
    # left behind, so the cleanup DELETE always runs in a fresh transaction.
    try:
        both = (
            (
                await session.execute(
                    select(NoteTemplate).where(NoteTemplate.format == NoteFormat.SOAPIE)
                )
            )
            .scalars()
            .all()
        )
        assert {t.jurisdiction for t in both} == {Jurisdiction.US, Jurisdiction.PH}
    finally:
        await session.rollback()
        await session.execute(
            sa.text("DELETE FROM note_templates WHERE prompt_version = 'ph_soapie_test_fixture_v1'")
        )
        await session.commit()


async def test_us_templates_require_diarization_and_ph_templates_do_not(
    session: AsyncSession,
) -> None:
    """Diarization is a property of the template, not of the pipeline.

    A US home visit has two to four speakers and a mis-attributed quote is a
    fabrication. A PH spoken recap has one speaker, so paying for diarization on a
    monologue buys nothing. Both halves are asserted now that the PH rows exist --
    the US-only check was all Task 3 could write, since no PH row existed yet.
    """
    us_soapie = (
        await session.execute(
            select(NoteTemplate).where(
                NoteTemplate.jurisdiction == Jurisdiction.US,
                NoteTemplate.format == NoteFormat.SOAPIE,
            )
        )
    ).scalar_one()
    assert us_soapie.requires_diarization is True

    repository = NoteTemplateRepository(session)
    for note_format in (NoteFormat.SOAPIE, NoteFormat.FDAR):
        ph_template = await repository.get_active(Jurisdiction.PH, note_format)
        assert ph_template is not None, note_format
        assert ph_template.requires_diarization is False


async def test_resolution_is_scoped_to_the_jurisdiction(session: AsyncSession) -> None:
    """The whole point of the dimension: same format, different row.

    Seeded PH templates arrive in Task 8; this asserts the US side resolves correctly
    and that asking for a jurisdiction with no row returns None rather than another
    jurisdiction's template.
    """
    repository = NoteTemplateRepository(session)

    us = await repository.get_active(Jurisdiction.US, NoteFormat.SHIFT_NOTE)
    assert us is not None
    assert us.jurisdiction is Jurisdiction.US

    # shift_note is a US home-care format; PH has no row for it.
    assert await repository.get_active(Jurisdiction.PH, NoteFormat.SHIFT_NOTE) is None


async def test_the_ph_templates_are_seeded_and_resolve(session: AsyncSession) -> None:
    repository = NoteTemplateRepository(session)
    for note_format in (NoteFormat.SOAPIE, NoteFormat.FDAR):
        template = await repository.get_active(Jurisdiction.PH, note_format)
        assert template is not None, note_format
        assert template.jurisdiction is Jurisdiction.PH
        assert template.requires_diarization is False


async def test_ph_soapie_drops_the_three_cms_only_flags(session: AsyncSession) -> None:
    """The single test that proves jurisdiction carries semantic weight.

    Same format, same sections bar one, different flag schema -- because homebound
    status, skilled-necessity rationale and plan-of-care linkage are CMS survey
    requirements with no Philippine analogue.
    """
    repository = NoteTemplateRepository(session)
    us = await repository.get_active(Jurisdiction.US, NoteFormat.SOAPIE)
    ph = await repository.get_active(Jurisdiction.PH, NoteFormat.SOAPIE)
    assert us is not None and ph is not None

    cms_only = {"MISSING_HOMEBOUND", "MISSING_NECESSITY_RATIONALE", "MISSING_POC_LINK"}
    us_codes = {f["code"] for f in us.flag_schema["flags"]}
    ph_codes = {f["code"] for f in ph.flag_schema["flags"]}

    assert cms_only <= us_codes
    assert cms_only.isdisjoint(ph_codes)


async def test_ph_soapie_section_descriptions_drop_cms_framing(session: AsyncSession) -> None:
    """`json_schema_for()` puts every `section.description` into the schema the
    provider is constrained on, so a CMS concept surviving here reaches the model
    through a channel no amount of careful prompt wording can block --
    MISSING_NECESSITY_RATIONALE and MISSING_POC_LINK were deliberately dropped from
    PH SOAPIE's flag set, so PH-flavoured necessity or plan-of-care content invented
    to satisfy a description that still asked for it would go unflagged.

    US SOAPIE's descriptions are asserted unchanged in the same test, not a separate
    one, so a fix that "cleans up" the shared wording instead of only the PH row
    fails loudly here rather than shipping quietly.
    """
    repository = NoteTemplateRepository(session)
    us = await repository.get_active(Jurisdiction.US, NoteFormat.SOAPIE)
    ph = await repository.get_active(Jurisdiction.PH, NoteFormat.SOAPIE)
    assert us is not None and ph is not None

    ph_descriptions = {s["key"]: s["description"] for s in ph.section_schema["sections"]}
    us_descriptions = {s["key"]: s["description"] for s in us.section_schema["sections"]}

    cms_phrases = {
        "intervention": "licensed nurse",
        "plan": "skilled care",
        "evaluation": "plan-of-care",
    }
    for key, phrase in cms_phrases.items():
        assert phrase not in ph_descriptions[key], (key, ph_descriptions[key])
        assert phrase in us_descriptions[key], (key, us_descriptions[key])


async def test_ph_templates_flag_a_spoken_patient_identifier(
    session: AsyncSession,
) -> None:
    """A pseudonymous label never de-identified the audio; this is what enforces it.

    Scoped to PH because a declared flag is only half of the control: the prompt has
    to ask for it. `ph_soapie_v1` and `ph_fdar_v1` both carry the redaction
    instruction; `shift_note_v1` and `soapie_v1` do not, and they are immutable
    modules. Declaring the code on the US rows would put it in the generation schema
    with nothing ever requesting it, which yields a clean note instead of a
    missing-control finding. US coverage arrives with the v2 prompt modules.
    """
    repository = NoteTemplateRepository(session)
    for note_format in (NoteFormat.SOAPIE, NoteFormat.FDAR):
        template = await repository.get_active(Jurisdiction.PH, note_format)
        assert template is not None, note_format
        codes = {f["code"] for f in template.flag_schema["flags"]}
        assert "PATIENT_IDENTIFIER_DETECTED" in codes, template.prompt_version


async def test_us_templates_do_not_yet_declare_the_identifier_flag(
    session: AsyncSession,
) -> None:
    """The deferral, asserted rather than assumed.

    This test should fail -- loudly, and with a pointer to the reason -- the moment
    someone declares the code on a US row without also shipping a prompt that asks
    for it. Delete it when `shift_note_v2` / `soapie_v2` land.
    """
    repository = NoteTemplateRepository(session)
    for note_format in (NoteFormat.SHIFT_NOTE, NoteFormat.SOAPIE):
        template = await repository.get_active(Jurisdiction.US, note_format)
        assert template is not None, note_format
        codes = {f["code"] for f in template.flag_schema["flags"]}
        assert "PATIENT_IDENTIFIER_DETECTED" not in codes, (
            f"{template.prompt_version} declares PATIENT_IDENTIFIER_DETECTED but the US "
            "prompt modules carry no redaction instruction -- ship shift_note_v2 / "
            "soapie_v2 first, then delete this test."
        )


async def test_ph_fdar_has_a_repeating_focus_section(session: AsyncSession) -> None:
    fdar = await NoteTemplateRepository(session).get_active(Jurisdiction.PH, NoteFormat.FDAR)
    assert fdar is not None
    sections = fdar.section_schema["sections"]
    focus = next(s for s in sections if s["key"] == "focus_entries")
    assert focus["repeating"] is True
    assert [f["key"] for f in focus["fields"]] == ["focus", "data", "action", "response"]
