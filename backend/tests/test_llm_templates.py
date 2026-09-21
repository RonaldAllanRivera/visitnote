"""Template specs and the JSON schema handed to the model.

The whole "one pipeline, two formats" claim rests on this layer: everything
format-specific is read out of the `note_templates` row, so adding a third format is
a data change plus a prompt module rather than a branch in the pipeline.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.templates import TemplateSpec, json_schema_for
from app.models import NoteFormat, NoteTemplate
from app.models.enums import Jurisdiction

SECTION_SCHEMA = {
    "sections": [
        {"key": "observations", "label": "Observations", "order": 1, "description": "Factual."},
        {"key": "handover", "label": "Handover", "order": 2, "description": "Next caregiver."},
    ]
}
FLAG_SCHEMA = {
    "flags": [
        {"code": "MISSING_ADLS", "severity": "warning", "description": "No ADLs."},
        {"code": "UNREPORTED_CHANGE", "severity": "critical", "description": "Change missed."},
    ]
}


def _spec(**overrides: Any) -> TemplateSpec:
    defaults: dict[str, Any] = {
        "jurisdiction": Jurisdiction.US,
        "note_format": NoteFormat.SHIFT_NOTE,
        "version": 1,
        "name": "Shift Note",
        "requires_diarization": True,
        "section_schema": SECTION_SCHEMA,
        "flag_schema": FLAG_SCHEMA,
        "prompt_version": "shift_note_v1",
        "llm_provider": "anthropic",
        "model_id": "test-model",
    }
    defaults.update(overrides)
    return TemplateSpec.from_schemas(**defaults)


def test_sections_are_exposed_in_schema_order() -> None:
    """The editor renders in this order and the prompt lists them in it."""
    assert _spec().section_keys == ("observations", "handover")


def test_a_flag_code_resolves_to_its_declared_severity() -> None:
    """Severity is the template's to decide, not the model's."""
    spec = _spec()

    assert spec.severity_of("UNREPORTED_CHANGE") == "critical"
    assert spec.severity_of("MISSING_ADLS") == "warning"


def test_an_undeclared_flag_code_has_no_severity() -> None:
    assert _spec().severity_of("INVENTED_CODE") is None


def test_the_json_schema_requires_every_section_key() -> None:
    """A section the model omits is indistinguishable from one it forgot; require all."""
    schema = json_schema_for(_spec())

    assert set(schema["properties"]["sections"]["properties"]) == {"observations", "handover"}
    assert schema["properties"]["sections"]["required"] == ["observations", "handover"]


def test_the_json_schema_allows_a_null_section() -> None:
    """No transcript support for a section is a legitimate, expected outcome."""
    schema = json_schema_for(_spec())
    observations = schema["properties"]["sections"]["properties"]["observations"]

    assert observations["type"] == ["string", "null"]


def test_the_json_schema_constrains_flag_codes_to_the_template() -> None:
    schema = json_schema_for(_spec())
    code = schema["properties"]["flags"]["items"]["properties"]["code"]

    assert set(code["enum"]) == {"MISSING_ADLS", "UNREPORTED_CHANGE"}


def test_the_json_schema_forbids_extra_keys_everywhere() -> None:
    """Without this the model can add a section that no editor will ever render."""
    schema = json_schema_for(_spec())

    assert schema["additionalProperties"] is False
    assert schema["properties"]["sections"]["additionalProperties"] is False
    assert schema["properties"]["flags"]["items"]["additionalProperties"] is False


def test_the_json_schema_carries_visit_details() -> None:
    """Times are flagged as critical when missing, so they need a machine-readable home."""
    schema = json_schema_for(_spec())

    assert set(schema["properties"]["visit_details"]["properties"]) == {
        "client_label",
        "visit_date",
        "start_time",
        "end_time",
    }


async def test_both_seeded_templates_parse_into_a_spec(session: AsyncSession) -> None:
    """The seeded rows are the real input; a spec that only parses fixtures is useless.

    Scoped to US: PH SOAPIE now shares the "soapie" format key, and this test's
    section-count assertions are specifically about the US shapes (ten sections,
    homebound status included), so an unscoped query risks `by_format[SOAPIE]`
    resolving to whichever row the query happens to return last.
    """
    rows = (
        (
            await session.execute(
                select(NoteTemplate).where(NoteTemplate.jurisdiction == Jurisdiction.US)
            )
        )
        .scalars()
        .all()
    )

    specs = [TemplateSpec.from_template(row) for row in rows]

    by_format = {spec.format: spec for spec in specs}
    assert len(by_format[NoteFormat.SHIFT_NOTE].section_keys) == 9
    assert len(by_format[NoteFormat.SOAPIE].section_keys) == 10
    assert by_format[NoteFormat.SOAPIE].severity_of("MISSING_VITALS") == "critical"


_FDAR_SECTIONS = {
    "sections": [
        {
            "key": "shift_details",
            "label": "Shift details",
            "order": 1,
            "description": "Unit, bed, shift.",
        },
        {
            "key": "focus_entries",
            "label": "Focus entries",
            "order": 2,
            "description": "One entry per focus.",
            "repeating": True,
            "fields": [
                {"key": "focus", "label": "Focus", "order": 1, "description": "The problem."},
                {"key": "data", "label": "Data", "order": 2, "description": "Findings."},
                {"key": "action", "label": "Action", "order": 3, "description": "Interventions."},
                {
                    "key": "response",
                    "label": "Response",
                    "order": 4,
                    "description": "Patient response.",
                },
            ],
        },
    ]
}


def test_a_repeating_section_parses_its_fields() -> None:
    spec = _spec(section_schema=_FDAR_SECTIONS)
    focus_entries = next(s for s in spec.sections if s.key == "focus_entries")
    assert focus_entries.repeating is True
    assert tuple(f.key for f in focus_entries.fields) == ("focus", "data", "action", "response")


def test_a_flat_section_has_no_fields_and_is_not_repeating() -> None:
    spec = _spec(section_schema=_FDAR_SECTIONS)
    shift_details = next(s for s in spec.sections if s.key == "shift_details")
    assert shift_details.repeating is False
    assert shift_details.fields == ()


def test_a_repeating_section_becomes_an_array_in_the_output_contract() -> None:
    """A shift produces several FDAR entries, so the contract must allow several.

    A string here would force the model to flatten three foci into one blob, which is
    exactly the deficiency MISSING_RESPONSE exists to catch.
    """
    schema = json_schema_for(_spec(section_schema=_FDAR_SECTIONS))
    focus_entries = schema["properties"]["sections"]["properties"]["focus_entries"]
    assert focus_entries["type"] == "array"
    assert set(focus_entries["items"]["required"]) == {"focus", "data", "action", "response"}
    assert focus_entries["items"]["additionalProperties"] is False
