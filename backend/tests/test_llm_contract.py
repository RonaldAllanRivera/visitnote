"""The generated-note output contract.

Validation failures here are not exceptional -- they are an expected, budgeted part
of using a language model. What matters is that every failure produces an
instruction specific enough for the repair retry to act on, rather than "invalid
output".
"""

import pytest

from app.llm.contract import BANNED_PHRASES, NoteValidationError, validate_output
from app.llm.templates import TemplateSpec
from app.models.enums import FlagSeverity, Jurisdiction, NoteFormat

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

SPEC = TemplateSpec.from_schemas(
    jurisdiction=Jurisdiction.US,
    note_format=NoteFormat.SHIFT_NOTE,
    version=1,
    name="Shift Note",
    requires_diarization=True,
    section_schema=SECTION_SCHEMA,
    flag_schema=FLAG_SCHEMA,
    prompt_version="shift_note_v1",
    llm_provider="anthropic",
    model_id="test-model",
)

VISIT_DETAILS = {
    "client_label": "Mrs R",
    "visit_date": "2026-09-21",
    "start_time": "08:00",
    "end_time": "12:00",
}

# A generic repeating section, shaped like FDAR's focus entries but not named after
# it -- this module validates whatever the template declares, and the fixture should
# not suggest otherwise.
REPEATING_SECTION_SCHEMA = {
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

REPEATING_SPEC = TemplateSpec.from_schemas(
    jurisdiction=Jurisdiction.US,
    note_format=NoteFormat.SHIFT_NOTE,
    version=1,
    name="Repeating-section format",
    requires_diarization=True,
    section_schema=REPEATING_SECTION_SCHEMA,
    flag_schema=FLAG_SCHEMA,
    prompt_version="repeating_v1",
    llm_provider="anthropic",
    model_id="test-model",
)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "visit_details": dict(VISIT_DETAILS),
        "sections": {"observations": "Ate half of lunch.", "handover": None},
        "flags": [],
    }
    base.update(overrides)
    return base


def test_a_conforming_payload_validates() -> None:
    note = validate_output(_payload(), SPEC)

    assert note.sections["observations"] == "Ate half of lunch."
    assert note.sections["handover"] is None


def test_a_missing_section_is_rejected_and_named() -> None:
    """An omitted key and a deliberately empty section must not look the same."""
    payload = _payload(sections={"observations": "Ate half of lunch."})

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, SPEC)

    assert "handover" in exc.value.repair_instruction


def test_an_invented_section_is_rejected_and_named() -> None:
    payload = _payload(sections={"observations": "x", "handover": None, "vital_signs": "BP 130/80"})

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, SPEC)

    assert "vital_signs" in exc.value.repair_instruction


def test_an_invented_flag_code_is_rejected_and_named() -> None:
    """A code outside the template has no label in the editor and no row in analytics."""
    payload = _payload(
        flags=[{"code": "PATIENT_SEEMED_SAD", "message": "m", "severity": "warning"}]
    )

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, SPEC)

    assert "PATIENT_SEEMED_SAD" in exc.value.repair_instruction


def test_severity_is_taken_from_the_template_not_the_model() -> None:
    """A critical code downgraded by the model is still critical."""
    payload = _payload(
        flags=[{"code": "UNREPORTED_CHANGE", "message": "Fall mentioned.", "severity": "info"}]
    )

    note = validate_output(payload, SPEC)

    assert note.flags[0].severity == FlagSeverity.CRITICAL


def test_a_banned_phrase_in_a_section_is_rejected() -> None:
    """The phrase is the failure: it is what a note says when it documents nothing."""
    payload = _payload(sections={"observations": "Client was doing well.", "handover": None})

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, SPEC)

    assert "doing well" in exc.value.repair_instruction


def test_banned_phrase_detection_ignores_case() -> None:
    payload = _payload(sections={"observations": "No Issues today.", "handover": None})

    with pytest.raises(NoteValidationError):
        validate_output(payload, SPEC)


def test_a_banned_phrase_inside_a_quotation_is_allowed() -> None:
    """The ban is on the note's voice. What the patient actually said is evidence."""
    payload = _payload(
        sections={"observations": 'Client stated "I am doing well" when asked.', "handover": None}
    )

    note = validate_output(payload, SPEC)

    assert note.sections["observations"] is not None


def test_missing_visit_details_is_rejected() -> None:
    payload = _payload(visit_details={"client_label": "Mrs R"})

    with pytest.raises(NoteValidationError):
        validate_output(payload, SPEC)


def test_a_null_time_is_allowed_because_it_is_what_raises_the_flag() -> None:
    """Refusing to invent a time is correct behaviour, not a validation failure."""
    payload = _payload(visit_details={**VISIT_DETAILS, "end_time": None})

    note = validate_output(payload, SPEC)

    assert note.visit_details["end_time"] is None


def test_the_repair_instruction_is_addressed_to_the_model() -> None:
    """It is pasted into a follow-up turn, so it has to read as an instruction."""
    payload = _payload(sections={"observations": "x"})

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, SPEC)

    assert len(exc.value.repair_instruction) > 20


def test_the_banned_list_covers_the_phrases_the_specification_names() -> None:
    for phrase in ("doing well", "no issues", "seemed fine", "routine visit"):
        assert phrase in BANNED_PHRASES


def _repeating_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "visit_details": dict(VISIT_DETAILS),
        "sections": {
            "shift_details": "Ward 3, Bed 4, night shift.",
            "focus_entries": [
                {
                    "focus": "Pain",
                    "data": "Reports 7/10 on movement.",
                    "action": "Gave PRN analgesic per order.",
                    "response": "Rated 3/10 after 30 minutes.",
                },
                {
                    "focus": "Fever",
                    "data": "Temp 38.6C at 0200.",
                    "action": "Administered antipyretic per order.",
                    "response": "Temp 37.4C at 0300.",
                },
            ],
        },
        "flags": [],
    }
    base.update(overrides)
    return base


def test_a_repeating_section_with_well_formed_entries_validates_cleanly() -> None:
    """Two foci in one shift is exactly what the array shape exists to carry."""
    note = validate_output(_repeating_payload(), REPEATING_SPEC)

    entries = note.sections["focus_entries"]
    assert isinstance(entries, list)
    assert len(entries) == 2


def test_a_repeating_entry_missing_a_declared_field_is_rejected_and_named() -> None:
    """MISSING_RESPONSE can only fire if an omitted key can't slip past validation."""
    payload = _repeating_payload(
        sections={
            "shift_details": "Ward 3, Bed 4, night shift.",
            "focus_entries": [
                {
                    "focus": "Pain",
                    "data": "Reports 7/10 on movement.",
                    "action": "Gave PRN analgesic per order.",
                    # response omitted
                }
            ],
        }
    )

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, REPEATING_SPEC)

    assert "focus_entries" in exc.value.repair_instruction
    assert "entry 0" in exc.value.repair_instruction
    assert "response" in exc.value.repair_instruction


def test_a_repeating_entry_with_an_undeclared_key_is_rejected_and_named() -> None:
    payload = _repeating_payload(
        sections={
            "shift_details": "Ward 3, Bed 4, night shift.",
            "focus_entries": [
                {
                    "focus": "Pain",
                    "data": "Reports 7/10 on movement.",
                    "action": "Gave PRN analgesic per order.",
                    "response": "Rated 3/10 after 30 minutes.",
                    "nurse_initials": "JR",
                }
            ],
        }
    )

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, REPEATING_SPEC)

    assert "focus_entries" in exc.value.repair_instruction
    assert "entry 0" in exc.value.repair_instruction
    assert "nurse_initials" in exc.value.repair_instruction


def test_a_repeating_section_sent_as_a_plain_string_is_rejected() -> None:
    """A model that flattens the foci into prose defeats the whole point of the array."""
    payload = _repeating_payload(
        sections={
            "shift_details": "Ward 3, Bed 4, night shift.",
            "focus_entries": "Pain: better after PRN. Fever: resolving.",
        }
    )

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, REPEATING_SPEC)

    assert "focus_entries" in exc.value.repair_instruction


def test_a_non_repeating_section_sent_as_a_list_is_rejected() -> None:
    """The converse: a flat section must not silently accept an array either."""
    payload = _payload(sections={"observations": [{"note": "not prose"}], "handover": None})

    with pytest.raises(NoteValidationError) as exc:
        validate_output(payload, SPEC)

    assert "observations" in exc.value.repair_instruction
