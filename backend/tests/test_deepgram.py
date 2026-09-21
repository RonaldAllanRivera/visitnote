"""Deepgram response parsing.

Parsed from a recorded payload rather than a live call: the thing that breaks when a
provider changes is the shape of what comes back, and that is exactly what a network
test would be too slow and too flaky to guard.
"""

from typing import Any

import pytest

from app.transcription.deepgram import DiarizationUnavailableError, parse_response

# Trimmed from an actual /v1/listen response with diarize=true and utterances=true.
PAYLOAD: dict[str, Any] = {
    "metadata": {"duration": 14.02, "channels": 1},
    "results": {
        "channels": [
            {
                "alternatives": [
                    {
                        "transcript": "Good morning. Not well. My left hip was aching.",
                        "confidence": 0.9913,
                    }
                ]
            }
        ],
        "utterances": [
            {
                "start": 0.0,
                "end": 1.84,
                "confidence": 0.99,
                "speaker": 0,
                "transcript": "Good morning.",
            },
            {
                "start": 2.1,
                "end": 5.62,
                "confidence": 0.95,
                "speaker": 1,
                "transcript": "Not well. My left hip was aching.",
            },
        ],
    },
}


def test_utterances_become_ordered_turns() -> None:
    result = parse_response(PAYLOAD, model_id="nova-3", diarize=True)

    assert [turn.text for turn in result.turns] == [
        "Good morning.",
        "Not well. My left hip was aching.",
    ]


def test_speaker_numbers_become_stable_labels() -> None:
    """The rest of the system keys on the label, so the mapping must not drift."""
    result = parse_response(PAYLOAD, model_id="nova-3", diarize=True)

    assert [turn.speaker_label for turn in result.turns] == ["speaker_0", "speaker_1"]
    assert result.speaker_count == 2


def test_seconds_are_converted_to_milliseconds() -> None:
    """Turn boundaries are stored as integer ms; floats from the wire must be converted."""
    result = parse_response(PAYLOAD, model_id="nova-3", diarize=True)

    assert (result.turns[1].start_ms, result.turns[1].end_ms) == (2100, 5620)


def test_raw_text_is_rebuilt_from_the_turns() -> None:
    """Not taken from the channel transcript: it must match the turns the LLM sees."""
    result = parse_response(PAYLOAD, model_id="nova-3", diarize=True)

    assert result.raw_text == "Good morning. Not well. My left hip was aching."


def test_records_the_model_that_produced_it() -> None:
    result = parse_response(PAYLOAD, model_id="nova-3", diarize=True)

    assert (result.provider, result.model_id) == ("deepgram", "nova-3")


def test_confidence_comes_from_the_channel_alternative() -> None:
    result = parse_response(PAYLOAD, model_id="nova-3", diarize=True)

    assert result.confidence == pytest.approx(0.9913)


def test_a_response_without_utterances_is_an_error_when_diarization_was_required() -> None:
    """Undiarized audio must fail loudly when a US template requires diarization.

    Falling back to one unattributed blob would let every quote in the note be
    attributed to whoever the model guessed -- the precise fabrication this provider
    exists to prevent.
    """
    undiarized = {
        "metadata": {"duration": 3.0},
        "results": {"channels": PAYLOAD["results"]["channels"]},
    }

    with pytest.raises(DiarizationUnavailableError):
        parse_response(undiarized, model_id="nova-3", diarize=True)


def test_a_response_without_utterances_is_not_an_error_when_diarization_was_not_required() -> None:
    """A PH spoken recap can legitimately come back with nothing Deepgram segmented.

    Without diarize=True gating the check, this would fail a PH note for the same
    reason a US note is supposed to fail -- a fabrication risk that does not exist
    when nobody asked the provider to tell speakers apart.
    """
    undiarized = {
        "metadata": {"duration": 3.0},
        "results": {"channels": PAYLOAD["results"]["channels"]},
    }

    result = parse_response(undiarized, model_id="nova-3", diarize=False)

    assert result.turns == ()
    assert result.speaker_count == 0


def test_a_single_speaker_response_parses_without_raising_under_diarize_false() -> None:
    """The expected shape of a diarize=False call: utterances present, one speaker.

    This is what a PH spoken recap looks like -- one nurse dictating alone -- and it
    must be accepted as a correct result, not treated as diarization having failed.
    """
    single_speaker = {
        "metadata": {"duration": 12.0},
        "results": {
            "channels": PAYLOAD["results"]["channels"],
            "utterances": [
                {
                    "start": 0.0,
                    "end": 12.0,
                    "confidence": 0.97,
                    "transcript": "Wound care follow-up completed without incident.",
                }
            ],
        },
    }

    result = parse_response(single_speaker, model_id="nova-3", diarize=False)

    assert result.speaker_count == 1
    assert result.turns[0].speaker_label == "speaker_0"
