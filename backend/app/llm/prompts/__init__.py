"""Versioned prompt registry.

Prompts are modules, not database rows and not editable strings. A change is a new
module; the active version is chosen by `note_templates.prompt_version`, and
promoting one requires a passing eval run. Rolling back is pointing the template at
the previous version, so old versions are never deleted.

The registry is explicit rather than discovered by scanning the package. A prompt
version appearing in production because someone dropped a file in a directory is
precisely the accident this design exists to prevent.
"""

from dataclasses import dataclass

from app.llm.prompts import shift_note_v1, soapie_v1
from app.llm.prompts.shared import (
    SHARED_RULES,
    infer_recording_speaker,
    render_transcript,
)


class UnknownPromptVersionError(Exception):
    """The template points at a prompt version that does not exist.

    Raised rather than defaulted. Generating under a different version than the one
    recorded on the note would make the note's provenance a lie.
    """


@dataclass(frozen=True, slots=True)
class Prompt:
    version: str
    system_prompt: str


_REGISTRY: dict[str, Prompt] = {
    module.VERSION: Prompt(version=module.VERSION, system_prompt=module.SYSTEM_PROMPT)
    for module in (shift_note_v1, soapie_v1)
}


def get_prompt(version: str) -> Prompt:
    try:
        return _REGISTRY[version]
    except KeyError as exc:
        raise UnknownPromptVersionError(
            f"no prompt module registered for version {version!r}; "
            f"known versions: {', '.join(sorted(_REGISTRY))}"
        ) from exc


def known_versions() -> tuple[str, ...]:
    """Used by /ops/prompts to list what a template may be promoted to."""
    return tuple(sorted(_REGISTRY))


__all__ = [
    "SHARED_RULES",
    "Prompt",
    "UnknownPromptVersionError",
    "get_prompt",
    "infer_recording_speaker",
    "known_versions",
    "render_transcript",
]
