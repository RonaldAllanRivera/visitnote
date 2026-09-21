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
    result = parse_response(PAYLOAD, model_id="nova-3")

    assert [turn.text for turn in result.turns] == [
        "Good morning.",
        "Not well. My left hip was aching.",
    ]


def test_speaker_numbers_become_stable_labels() -> None:
    """The rest of the system keys on the label, so the mapping must not drift."""
    result = parse_response(PAYLOAD, model_id="nova-3")

    assert [turn.speaker_label for turn in result.turns] == ["speaker_0", "speaker_1"]
    assert result.speaker_count == 2


def test_seconds_are_converted_to_milliseconds() -> None:
    """Turn boundaries are stored as integer ms; floats from the wire must be converted."""
    result = parse_response(PAYLOAD, model_id="nova-3")

    assert (result.turns[1].start_ms, result.turns[1].end_ms) == (2100, 5620)


def test_raw_text_is_rebuilt_from_the_turns() -> None:
    """Not taken from the channel transcript: it must match the turns the LLM sees."""
    result = parse_response(PAYLOAD, model_id="nova-3")

    assert result.raw_text == "Good morning. Not well. My left hip was aching."


def test_records_the_model_that_produced_it() -> None:
    result = parse_response(PAYLOAD, model_id="nova-3")

    assert (result.provider, result.model_id) == ("deepgram", "nova-3")


def test_confidence_comes_from_the_channel_alternative() -> None:
    result = parse_response(PAYLOAD, model_id="nova-3")

    assert result.confidence == pytest.approx(0.9913)


def test_a_response_without_utterances_is_an_error_not_a_flat_transcript() -> None:
    """Undiarized audio must fail loudly.

    Falling back to one unattributed blob would let every quote in the note be
    attributed to whoever the model guessed -- the precise fabrication this provider
    exists to prevent.
    """
    undiarized = {
        "metadata": {"duration": 3.0},
        "results": {"channels": PAYLOAD["results"]["channels"]},
    }

    with pytest.raises(DiarizationUnavailableError):
        parse_response(undiarized, model_id="nova-3")
