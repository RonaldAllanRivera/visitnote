"""Prompt modules, transcript rendering, and speaker-role inference.

The inference is the sharp edge. Telling the model which speaker is the caregiver
makes patient quotes attributable; telling it *wrongly* makes every quote in the note
a fabrication. So the rule errs towards "unknown", and the prompt says so out loud.
"""

import re

import pytest

from app.llm.prompts import (
    SHARED_RULES,
    UnknownPromptVersionError,
    get_prompt,
    infer_recording_speaker,
    known_versions,
    render_transcript,
)
from app.transcription import TranscriptTurn


def _turn(speaker: str, text: str, start_ms: int, end_ms: int) -> TranscriptTurn:
    return TranscriptTurn(speaker_label=speaker, start_ms=start_ms, end_ms=end_ms, text=text)


# -- Prompt registry -------------------------------------------------------


def test_each_seeded_prompt_version_resolves() -> None:
    for version in ("shift_note_v1", "soapie_v1"):
        assert get_prompt(version).system_prompt


def test_an_unknown_prompt_version_is_an_error_not_a_default() -> None:
    """Silently falling back would generate a note under a version it does not record."""
    with pytest.raises(UnknownPromptVersionError):
        get_prompt("soapie_v99")


def test_a_prompt_reports_its_own_version() -> None:
    """Every note stores this, so it must come from the module, not the caller."""
    assert get_prompt("soapie_v1").version == "soapie_v1"


def test_both_prompts_forbid_fabrication() -> None:
    for version in ("shift_note_v1", "soapie_v1"):
        assert "never invent" in get_prompt(version).system_prompt.lower()


def test_both_prompts_carry_the_banned_phrases() -> None:
    """The validator rejects them after the fact; the prompt is what avoids the retry."""
    for version in ("shift_note_v1", "soapie_v1"):
        assert "doing well" in get_prompt(version).system_prompt


def test_the_soapie_prompt_requires_a_necessity_rationale() -> None:
    assert "MISSING_NECESSITY_RATIONALE" in get_prompt("soapie_v1").system_prompt


def test_the_shift_note_prompt_does_not_mention_soapie_flags() -> None:
    """Formats must not leak into each other; a caregiver note has no homebound status."""
    assert "MISSING_HOMEBOUND" not in get_prompt("shift_note_v1").system_prompt


# -- Speaker inference -----------------------------------------------------


def test_a_single_speaker_is_the_recording_user() -> None:
    """A spoken recap has one voice, and it is the person holding the phone."""
    turns = [_turn("speaker_0", "Recapping my visit.", 0, 8_000)]

    assert infer_recording_speaker(turns) == "speaker_0"


def test_the_speaker_who_opens_and_dominates_is_the_recording_user() -> None:
    turns = [
        _turn("speaker_0", "Good morning, I'm here for your visit.", 0, 6_000),
        _turn("speaker_1", "Hello.", 6_000, 7_000),
        _turn("speaker_0", "Let's check your dressing and your blood pressure.", 7_000, 15_000),
    ]

    assert infer_recording_speaker(turns) == "speaker_0"


def test_no_inference_when_the_opener_is_not_the_dominant_speaker() -> None:
    """Ambiguity must resolve to "unknown". A wrong guess fabricates every quote."""
    turns = [
        _turn("speaker_0", "Hi.", 0, 1_000),
        _turn("speaker_1", "I have been up all night with this hip, it aches.", 1_000, 20_000),
    ]

    assert infer_recording_speaker(turns) is None


def test_no_inference_when_the_opener_leads_only_marginally() -> None:
    """A near-even split is a conversation, not a clear caregiver.

    Two people talking for roughly the same time could be a nurse and a patient in
    either order. "Probably" is not a basis for attributing a clinical quote.
    """
    turns = [
        _turn("speaker_0", "Good morning, how are you feeling today?", 0, 11_000),
        _turn("speaker_1", "Not too bad, though my hip has been aching.", 11_000, 21_000),
    ]

    assert infer_recording_speaker(turns) is None


def test_no_inference_from_an_empty_transcript() -> None:
    assert infer_recording_speaker([]) is None


# -- Transcript rendering --------------------------------------------------


def test_each_turn_is_rendered_with_its_speaker_and_start_time() -> None:
    turns = [
        _turn("speaker_0", "How did you sleep?", 0, 3_000),
        _turn("speaker_1", "Badly.", 3_500, 5_000),
    ]

    rendered = render_transcript(turns, recording_speaker="speaker_0")

    assert "speaker_0" in rendered
    assert "How did you sleep?" in rendered
    assert "Badly." in rendered


def test_the_recording_user_is_identified_when_it_is_known() -> None:
    turns = [_turn("speaker_0", "Starting the visit.", 0, 4_000)]

    rendered = render_transcript(turns, recording_speaker="speaker_0")

    assert "speaker_0 is the caregiver or nurse" in rendered


def test_an_unknown_recording_user_produces_an_explicit_instruction_not_silence() -> None:
    """Omitting the hint would leave the model free to assume. It must be told not to."""
    turns = [
        _turn("speaker_0", "Hi.", 0, 1_000),
        _turn("speaker_1", "My hip aches badly all night long.", 1_000, 20_000),
    ]

    rendered = render_transcript(turns, recording_speaker=None)

    assert "could not be determined" in rendered
    assert "UNATTRIBUTED_STATEMENT" in rendered


# -- PH prompt modules -------------------------------------------------------


def test_the_ph_prompt_versions_are_registered() -> None:
    assert {"ph_soapie_v1", "ph_fdar_v1"} <= set(known_versions())


def test_ph_soapie_does_not_ask_for_homebound_status() -> None:
    """Homebound status is a CMS survey requirement with no PhilHealth analogue.

    Asking for it would invite the model to invent one, which is the exact failure
    class the fabrication checker exists to catch.
    """
    prompt = get_prompt("ph_soapie_v1").system_prompt.lower()
    assert "homebound" not in prompt


def test_ph_fdar_names_the_four_fdar_elements() -> None:
    prompt = get_prompt("ph_fdar_v1").system_prompt.lower()
    for element in ("focus", "data", "action", "response"):
        assert element in prompt


def test_every_ph_prompt_carries_the_shared_rules() -> None:
    """The no-fabrication rules are not per-format and must not be re-stated per format."""
    for version in ("ph_soapie_v1", "ph_fdar_v1"):
        assert SHARED_RULES in get_prompt(version).system_prompt


# -- Flag-code drift guard ---------------------------------------------------
#
# json_schema_for() (app/llm/templates.py) turns a template's declared flag codes
# into a JSON Schema enum that constrains generation. A prompt naming a code outside
# that enum is not a validation error at generation time -- the model can never emit
# a token the schema forbids, so the flag simply never fires, silently. A misspelled
# or borrowed code is therefore not a typo, it is a flag that is permanently dead on
# arrival. This test is the cheapest possible guard against that failure class.
#
# The expected sets below are hardcoded from visitnote-claude-code-prompt-v9.md's
# Note Formats section (the PH SOAPIE and PH FDAR flag lists), which is the binding
# authority Task 9 seeds `flag_schema` from. They are hardcoded rather than read from
# the database because Task 9 has not seeded the PH template rows yet -- this test
# exists precisely so it is already true once that seeding lands.

_FLAG_TOKEN = re.compile(r"[A-Z][A-Z_]{5,}")

# Words that match the flag-token shape but are not flag codes -- unavoidable in a
# format's own name appearing in its prompt's prose.
_NOT_A_FLAG = {"SOAPIE"}

# PH SOAPIE retains every US SOAPIE flag except the three CMS-specific ones dropped
# with Homebound status (MISSING_HOMEBOUND, MISSING_NECESSITY_RATIONALE,
# MISSING_POC_LINK), per the spec's "everything else is retained".
_PH_SOAPIE_FLAGS = {
    "MISSING_VITALS",
    "MISSING_VISIT_TIMES",
    "MISSING_SKILLED_SERVICE",
    "UNREPORTED_CHANGE",
    "PATIENT_IDENTIFIER_DETECTED",
    "MISSING_RESPONSE",
    "MISSING_MED_REVIEW",
    "MISSING_NEXT_VISIT_PLAN",
    "MISSING_COORDINATION",
    "VAGUE_LANGUAGE",
    "UNATTRIBUTED_STATEMENT",
    "MISSING_EDUCATION_RESPONSE",
    "MISSING_PAIN_ASSESSMENT",
}

_PH_FDAR_FLAGS = {
    "MISSING_SHIFT_TIMES",
    "MISSING_FOCUS",
    "MISSING_RESPONSE",
    "MED_WITHOUT_ROUTE_OR_TIME",
    "PRN_WITHOUT_RESPONSE",
    "UNREPORTED_CHANGE",
    "PATIENT_IDENTIFIER_DETECTED",
    "MISSING_VITALS_TIME",
    "MISSING_INTAKE_OUTPUT",
    "PAIN_NOT_REASSESSED",
    "ORDER_NOT_ACKNOWLEDGED",
    "MISSING_ENDORSEMENT",
    "VAGUE_LANGUAGE",
    "MISSING_EDUCATION_RESPONSE",
    # NOT in the spec's PH FDAR list -- the spec's own rationale is that a dictated
    # recap has one speaker, so there is nothing to attribute. But SHARED_RULES
    # (embedded verbatim in every prompt, ph_fdar_v1 included -- required by this
    # module's own carries-the-shared-rules test above) raises this flag
    # unconditionally whenever a statement's speaker cannot be determined, so the
    # token is structurally present in this prompt's text regardless of the spec's
    # per-format list. Allow-listed here as a known, reported spec/architecture
    # inconsistency (see the task-8 fix-round report), not a silent workaround: if
    # Task 9 seeds PH FDAR's flag_schema exactly per the spec's list (omitting this
    # code), the enum will reject the one instruction SHARED_RULES gives every
    # format unconditionally.
    "UNATTRIBUTED_STATEMENT",
}

_EXPECTED_FLAGS_BY_VERSION = {
    "ph_soapie_v1": _PH_SOAPIE_FLAGS,
    "ph_fdar_v1": _PH_FDAR_FLAGS,
}


def test_ph_prompts_name_only_flag_codes_their_template_will_declare() -> None:
    for version, expected in _EXPECTED_FLAGS_BY_VERSION.items():
        tokens = set(_FLAG_TOKEN.findall(get_prompt(version).system_prompt)) - _NOT_A_FLAG
        undeclared = tokens - expected
        assert not undeclared, f"{version} names flag code(s) outside its spec set: {undeclared}"
