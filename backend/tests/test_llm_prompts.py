"""Prompt modules, transcript rendering, and speaker-role inference.

The inference is the sharp edge. Telling the model which speaker is the caregiver
makes patient quotes attributable; telling it *wrongly* makes every quote in the note
a fabrication. So the rule errs towards "unknown", and the prompt says so out loud.
"""

import pytest

from app.llm.prompts import (
    UnknownPromptVersionError,
    get_prompt,
    infer_recording_speaker,
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
