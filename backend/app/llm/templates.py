"""Note templates as the LLM layer sees them.

`TemplateSpec` is a parsed, immutable view of a `note_templates` row. Everything
format-specific in this phase -- which sections exist, which flag codes may be
raised, which prompt module runs, which model answers -- is read from here, which is
what lets one pipeline serve both formats and a third format arrive as a data change.

Nothing in this module knows what a SOAPIE note is.
"""

from dataclasses import dataclass
from typing import Any

from app.models import NoteTemplate
from app.models.enums import FlagSeverity, Jurisdiction, NoteFormat

# The structured header both formats carry. It is kept out of `sections` because it
# is the only part of the output that is queried rather than read: MISSING_SHIFT_TIMES
# and MISSING_VISIT_TIMES are both critical flags, and deciding whether a time is
# present should not mean parsing prose.
VISIT_DETAIL_KEYS: tuple[str, ...] = ("client_label", "visit_date", "start_time", "end_time")


@dataclass(frozen=True, slots=True)
class SectionSpec:
    key: str
    label: str
    order: int
    description: str
    # FDAR charts one F-D-A-R block per focus, and a shift has several. Every other
    # format is a flat list, so this is False everywhere but there.
    repeating: bool = False
    fields: tuple["SectionSpec", ...] = ()


def _parse_sections(items: list[dict[str, Any]]) -> tuple[SectionSpec, ...]:
    return tuple(
        SectionSpec(
            key=str(item["key"]),
            label=str(item["label"]),
            order=int(item["order"]),
            description=str(item.get("description", "")),
            repeating=bool(item.get("repeating", False)),
            fields=_parse_sections(item.get("fields", [])),
        )
        for item in sorted(items, key=lambda s: int(s["order"]))
    )


@dataclass(frozen=True, slots=True)
class FlagSpec:
    code: str
    severity: FlagSeverity
    description: str


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    jurisdiction: Jurisdiction
    format: NoteFormat
    version: int
    name: str
    requires_diarization: bool
    sections: tuple[SectionSpec, ...]
    flags: tuple[FlagSpec, ...]
    prompt_version: str
    llm_provider: str
    model_id: str

    @classmethod
    def from_template(cls, template: NoteTemplate) -> "TemplateSpec":
        return cls.from_schemas(
            jurisdiction=template.jurisdiction,
            note_format=template.format,
            version=template.version,
            name=template.name,
            requires_diarization=template.requires_diarization,
            section_schema=template.section_schema,
            flag_schema=template.flag_schema,
            prompt_version=template.prompt_version,
            llm_provider=template.llm_provider,
            model_id=template.model_id,
        )

    @classmethod
    def from_schemas(
        cls,
        *,
        jurisdiction: Jurisdiction,
        note_format: NoteFormat,
        version: int,
        name: str,
        requires_diarization: bool,
        section_schema: dict[str, Any],
        flag_schema: dict[str, Any],
        prompt_version: str,
        llm_provider: str,
        model_id: str,
    ) -> "TemplateSpec":
        sections = _parse_sections(section_schema["sections"])
        flags = tuple(
            FlagSpec(
                code=str(item["code"]),
                severity=FlagSeverity(item["severity"]),
                description=str(item.get("description", "")),
            )
            for item in flag_schema["flags"]
        )
        return cls(
            jurisdiction=jurisdiction,
            format=note_format,
            version=version,
            name=name,
            requires_diarization=requires_diarization,
            sections=sections,
            flags=flags,
            prompt_version=prompt_version,
            llm_provider=llm_provider,
            model_id=model_id,
        )

    @property
    def section_keys(self) -> tuple[str, ...]:
        return tuple(section.key for section in self.sections)

    def severity_of(self, code: str) -> FlagSeverity | None:
        """The template's declared severity for a code, or None if it declares none.

        Severity belongs to the template rather than to the model. A model that calls
        a missing homebound justification "info" does not make it info: it is a
        billing risk in the nurse tier regardless of how the generation phrased it.
        """
        for flag in self.flags:
            if flag.code == code:
                return flag.severity
        return None


def _section_property(section: SectionSpec) -> dict[str, Any]:
    """The output contract for one section.

    A repeating section is an array of objects, so three foci arrive as three entries
    rather than as one flattened string the flag engine cannot inspect per-entry.
    """
    if not section.repeating:
        return {"type": ["string", "null"], "description": section.description}
    return {
        "type": "array",
        "description": section.description,
        "items": {
            "type": "object",
            "properties": {
                field.key: {"type": ["string", "null"], "description": field.description}
                for field in section.fields
            },
            "required": [field.key for field in section.fields],
            "additionalProperties": False,
        },
    }


def json_schema_for(spec: TemplateSpec) -> dict[str, Any]:
    """The output contract, expressed as JSON Schema for the provider to constrain on.

    Constraining generation is not the same as validating it -- the pipeline still
    runs the payload through Pydantic afterwards -- but it moves the common failures
    from "repair retry" to "never happened", which is a real cost saving at volume.
    """
    return {
        "type": "object",
        "properties": {
            "visit_details": {
                "type": "object",
                "properties": {
                    key: {
                        "type": ["string", "null"],
                        "description": _VISIT_DETAIL_DESCRIPTIONS[key],
                    }
                    for key in VISIT_DETAIL_KEYS
                },
                "required": list(VISIT_DETAIL_KEYS),
                "additionalProperties": False,
            },
            "sections": {
                "type": "object",
                "properties": {
                    section.key: _section_property(section) for section in spec.sections
                },
                # Every key required, null where unsupported. An omitted key and a
                # deliberately empty section would otherwise be indistinguishable,
                # and only one of those is acceptable.
                "required": list(spec.section_keys),
                "additionalProperties": False,
            },
            "flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        # Enumerated, so the model cannot invent a code the review UI
                        # has no label for and the analytics tables cannot group by.
                        "code": {"type": "string", "enum": [flag.code for flag in spec.flags]},
                        "message": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": [severity.value for severity in FlagSeverity],
                        },
                    },
                    "required": ["code", "message", "severity"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["visit_details", "sections", "flags"],
        "additionalProperties": False,
    }


_VISIT_DETAIL_DESCRIPTIONS = {
    "client_label": "The pseudonymous label used for this person, exactly as stated.",
    "visit_date": "ISO date of the visit, only if stated in the audio.",
    "start_time": "Arrival or shift start time as stated, e.g. '08:15'. Null if not stated.",
    "end_time": "Departure or shift end time as stated. Null if not stated.",
}
