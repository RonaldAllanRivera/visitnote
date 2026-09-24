"""The generated-note output contract and its validation.

A language model producing output that does not conform is an expected event, not an
exceptional one. The design consequence is that every rejection here has to carry an
instruction the model can act on -- naming the section it invented or the phrase it
used -- because that instruction is the entire content of the repair retry. "Invalid
output" would waste the retry.
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.llm.templates import VISIT_DETAIL_KEYS, SectionSpec, TemplateSpec
from app.models.enums import FlagSeverity

# Phrases that are never acceptable in the note's own voice. Each one is a sentence
# that documents nothing: it survives a reader's glance while telling them, and an
# auditor, precisely zero facts.
#
# "stable" is deliberately absent. It is banned by the prompt only when unsupported
# by data, and "blood pressure stable at 130/80 across three readings" is a
# legitimate clinical statement. An automated check cannot tell those apart, so
# enforcing it here would reject correct notes; the eval suite judges it instead.
BANNED_PHRASES: tuple[str, ...] = (
    "doing well",
    "no issues",
    "seemed fine",
    "a little off",
    "routine visit",
    "routine check-up",
    "routine checkup",
    "care provided as ordered",
)

# Quoted spans are exempt from the ban. The rule governs how the note describes the
# visit; what the patient actually said is evidence, and "the patient said they were
# doing well" is a fact worth recording.
_QUOTED_SPAN = re.compile(r'"[^"]*"|“[^”]*”')


class NoteValidationError(Exception):
    """The generation does not satisfy the template's contract."""

    def __init__(self, repair_instruction: str) -> None:
        super().__init__(repair_instruction)
        self.repair_instruction = repair_instruction


class GeneratedFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: FlagSeverity


# A section is either a block of prose or, for a repeating group like FDAR's
# focus entries, a list of entries. FDAR charts one F-D-A-R block per focus and a
# shift has several, so flattening them into one string would make MISSING_RESPONSE
# -- an Action with no documented patient Response -- impossible to evaluate per entry.
SectionValue = str | list[dict[str, str | None]] | None


class GeneratedNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visit_details: dict[str, str | None]
    sections: dict[str, SectionValue]
    flags: list[GeneratedFlag]


def validate_sections_structure(
    sections: dict[str, SectionValue], spec: TemplateSpec
) -> None:
    """Check a section map against the template's shape.

    Shared by generation and by the review editor, so the two cannot disagree about
    what a valid repeating section looks like. Structure only: the banned-phrase rule
    belongs to `validate_output`, because it governs how the model writes rather than
    what a human author is allowed to say about their own patient.
    """
    _check_keys(
        actual=set(sections),
        expected={section.key for section in spec.sections},
        label="sections",
    )
    _check_repeating_sections(sections, spec)


def validate_output(payload: dict[str, Any], spec: TemplateSpec) -> GeneratedNote:
    """Validate a generation against the active template, or explain how to fix it."""
    try:
        note = GeneratedNote.model_validate(payload)
    except ValidationError as exc:
        raise NoteValidationError(
            "The output did not match the required shape. Return a JSON object with "
            "exactly the keys visit_details, sections and flags. "
            f"Errors: {_summarise(exc)}"
        ) from exc

    _check_keys(
        actual=set(note.visit_details),
        expected=set(VISIT_DETAIL_KEYS),
        label="visit_details",
    )
    validate_sections_structure(note.sections, spec)
    _check_banned_phrases(note.sections)

    return note.model_copy(update={"flags": _normalise_flags(note.flags, spec)})


def _check_keys(*, actual: set[str], expected: set[str], label: str) -> None:
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if not missing and not unexpected:
        return

    problems = []
    if missing:
        problems.append(
            f"{label} is missing required keys: {', '.join(missing)}. "
            "Include every key, using null where the transcript does not support one."
        )
    if unexpected:
        problems.append(
            f"{label} contains keys that are not part of this note format: "
            f"{', '.join(unexpected)}. Remove them."
        )
    raise NoteValidationError(" ".join(problems))


def _check_repeating_sections(sections: dict[str, SectionValue], spec: TemplateSpec) -> None:
    """A repeating section (FDAR's focus entries) needs per-entry validation.

    `_check_keys` above only confirms the top-level section keys match the template;
    it cannot see inside a list. Without this, a model returning `[{"focus": "pain"}]`
    -- no `data`, `action`, or `response` -- would validate cleanly, and
    MISSING_RESPONSE exists specifically to catch an Action with no documented
    Response. A key the model never emits and a response it determined absent must
    not be indistinguishable.
    """
    for section in spec.sections:
        if section.key not in sections:
            continue  # a missing or invented key was already rejected by _check_keys
        value = sections[section.key]
        if section.repeating:
            _check_repeating_entries(section, value)
        elif isinstance(value, list):
            raise NoteValidationError(
                f'The "{section.key}" section must be a single value, not a list. '
                "This note format does not repeat that section."
            )


def _check_repeating_entries(section: SectionSpec, value: SectionValue) -> None:
    if not isinstance(value, list):
        raise NoteValidationError(
            f'The "{section.key}" section must be a list of entries -- one per '
            f"{section.label.lower()} -- because this note format repeats it."
        )
    expected = {field.key for field in section.fields}
    for index, entry in enumerate(value):
        actual = set(entry)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if not missing and not unexpected:
            continue

        problems = []
        if missing:
            problems.append(f"is missing required keys: {', '.join(missing)}")
        if unexpected:
            problems.append(f"contains keys this section does not declare: {', '.join(unexpected)}")
        raise NoteValidationError(
            f'The "{section.key}" section, entry {index}, {"; ".join(problems)}. '
            f"Every entry needs exactly these keys: {', '.join(sorted(expected))}."
        )


def _check_banned_phrases(sections: dict[str, SectionValue]) -> None:
    """Reject the banned phrases wherever a section carries the note's own prose.

    A repeating section keeps its prose inside each entry's fields -- FDAR's Data and
    Action text -- rather than in the section value itself. Skipping list values here
    (as an earlier version did, solely to avoid `.sub()` crashing on a list) would
    make a flag like VAGUE_LANGUAGE unenforceable on exactly the format whose
    substance lives almost entirely in entries, with no test failure to show it.
    """
    for key, value in sections.items():
        if isinstance(value, str):
            phrase = _banned_phrase_in(value)
            if phrase is not None:
                raise NoteValidationError(
                    f'The {key} section contains the banned phrase "{phrase}". '
                    "Replace it with a specific, measurable statement from the "
                    "transcript, or set the section to null and raise the "
                    "appropriate flag. Do not invent detail to replace it."
                )
        elif isinstance(value, list):
            for index, entry in enumerate(value):
                for field_key, field_value in entry.items():
                    if not isinstance(field_value, str):
                        continue
                    phrase = _banned_phrase_in(field_value)
                    if phrase is not None:
                        raise NoteValidationError(
                            f'The "{key}" section, entry {index}, field "{field_key}" '
                            f'contains the banned phrase "{phrase}". Replace it with a '
                            "specific, measurable statement from the transcript, or "
                            "set the field to null and raise the appropriate flag. Do "
                            "not invent detail to replace it."
                        )


def _banned_phrase_in(text: str) -> str | None:
    """The first banned phrase used in `text`'s own voice, or None.

    Quoted spans are exempt: the ban governs how the note describes the visit, not
    what the patient is recorded as having said, and that has to hold identically
    whether `text` is a flat section's value or one field of a repeating entry.
    """
    if not text:
        return None
    unquoted = _QUOTED_SPAN.sub(" ", text).lower()
    for phrase in BANNED_PHRASES:
        if phrase in unquoted:
            return phrase
    return None


def _normalise_flags(flags: list[GeneratedFlag], spec: TemplateSpec) -> list[GeneratedFlag]:
    """Reject undeclared codes; take severity from the template.

    Severity is not the model's call. A missing homebound justification is a billing
    risk whatever the generation labelled it, and the dashboards aggregate on
    severity -- so one generation deciding a critical code is "info" would quietly
    move a note out of the review queue.
    """
    normalised: list[GeneratedFlag] = []
    for flag in flags:
        severity = spec.severity_of(flag.code)
        if severity is None:
            raise NoteValidationError(
                f'"{flag.code}" is not a flag code defined for this note format. '
                f"Use only these codes: {', '.join(f.code for f in spec.flags)}."
            )
        normalised.append(flag.model_copy(update={"severity": severity}))
    return normalised


def _summarise(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()[:5]
    )
