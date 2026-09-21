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
#
# _PH_SOAPIE_FLAGS excludes UNATTRIBUTED_STATEMENT, which the spec document as
# originally written still lists (inherited unexamined from US SOAPIE). The
# coordinator is correcting the spec to match: PH SOAPIE capture is single-speaker by
# law exactly like PH FDAR, so the code has no path to firing there either. This set
# reflects the corrected spec, not a stale reading of the current document.

_FLAG_TOKEN = re.compile(r"[A-Z][A-Z_]{5,}")

# Words that match the flag-token shape but are not flag codes -- unavoidable in a
# format's own name appearing in its prompt's prose.
_NOT_A_FLAG = {"SOAPIE"}

# PH SOAPIE retains every US SOAPIE flag except the three CMS-specific ones dropped
# with Homebound status (MISSING_HOMEBOUND, MISSING_NECESSITY_RATIONALE,
# MISSING_POC_LINK), per the spec's "everything else is retained" -- with one further
# correction: UNATTRIBUTED_STATEMENT is excluded here too (see
# _PH_SOAPIE_SUPPRESSED_FLAGS below). The spec originally inherited it unexamined from
# US SOAPIE; PH SOAPIE capture is single-speaker by law exactly like PH FDAR, so the
# coordinator corrected the spec rather than leaving the two PH formats inconsistent
# for no relevant reason.
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
    "MISSING_EDUCATION_RESPONSE",
    "MISSING_PAIN_ASSESSMENT",
}

# PH FDAR's declared set, exactly as the spec lists it. Does NOT include
# UNATTRIBUTED_STATEMENT: the spec's own rationale is that a dictated recap has one
# speaker, so there is nothing to attribute, and Task 9 seeds `flag_schema` from this
# list as written -- declaring a code the engine has no path to ever raising would be
# its own kind of lie in the schema.
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
}

# Codes a prompt names only to forbid raising them, never to raise them -- distinct
# from the declared sets above, which a prompt may legitimately instruct the model to
# raise. SHARED_RULES (embedded verbatim in every format, required by
# test_every_ph_prompt_carries_the_shared_rules above) instructs raising
# UNATTRIBUTED_STATEMENT whenever a statement's speaker cannot be determined. Both PH
# formats' transcripts are single-speaker dictations -- PH capture is dictation-only
# under RA 4200, not just an FDAR trait -- so that condition is structurally
# impossible in either, and both SYSTEM_PROMPTs explicitly override the shared clause
# and say why rather than silently inheriting it. The token is still present in the
# text -- to forbid it -- so it must be accounted for here, but accounting for it as
# "declared" would hide the fact that neither PH template's flag_schema (Task 9)
# includes this code. This is not a workaround for unresolved drift; it is what the
# override in each ph_*_v1.py module is supposed to produce.
_PH_SOAPIE_SUPPRESSED_FLAGS = {"UNATTRIBUTED_STATEMENT"}
_PH_FDAR_SUPPRESSED_FLAGS = {"UNATTRIBUTED_STATEMENT"}

_EXPECTED_FLAGS_BY_VERSION = {
    "ph_soapie_v1": _PH_SOAPIE_FLAGS | _PH_SOAPIE_SUPPRESSED_FLAGS,
    "ph_fdar_v1": _PH_FDAR_FLAGS | _PH_FDAR_SUPPRESSED_FLAGS,
}


def test_ph_prompts_name_only_flag_codes_their_template_will_declare() -> None:
    for version, expected in _EXPECTED_FLAGS_BY_VERSION.items():
        tokens = set(_FLAG_TOKEN.findall(get_prompt(version).system_prompt)) - _NOT_A_FLAG
        undeclared = tokens - expected
        assert not undeclared, f"{version} names flag code(s) outside its spec set: {undeclared}"


def test_ph_prompts_override_shared_rules_to_forbid_unattributed_statement() -> None:
    """Distinguishes 'names to forbid' from 'names to raise' for the one suppressed code.

    The subset check above would pass just as happily whether a PH prompt raises
    UNATTRIBUTED_STATEMENT or forbids it -- both name the token. What makes each
    format's behaviour correct is the override's actual wording, and that it comes
    after SHARED_RULES' own "raise it" instruction rather than before -- an override
    a model reads before the rule it overrides is not reliably an override. Both PH
    formats carry the same override for the same reason (single-speaker capture under
    RA 4200), so both are checked identically here.
    """
    for version in ("ph_soapie_v1", "ph_fdar_v1"):
        prompt = get_prompt(version).system_prompt
        assert "Never raise UNATTRIBUTED_STATEMENT" in prompt
        # SHARED_RULES' own instruction is the first mention of the code in the
        # rendered prompt; the override must come after it to read as overriding
        # rather than being overridden. Located by the flag code itself, not "raise
        # UNATTRIBUTED_STATEMENT", because SHARED_RULES wraps a line between the two
        # words.
        first_mention = prompt.index("UNATTRIBUTED_STATEMENT")
        override_mention = prompt.index("Never raise UNATTRIBUTED_STATEMENT")
        assert override_mention > first_mention
