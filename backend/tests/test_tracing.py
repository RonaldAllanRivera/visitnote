"""Pipeline tracing.

Content redaction is on by default in production, which makes the trace worth having
only if it still answers the questions tracing exists for: is a prompt version
regressing, which stage is slow, what does a note cost, how often is the output
invalid. So the tests here are mostly about what survives redaction, not what is
removed by it.
"""

import pytest

from app.observability import NoOpTracer, RecordingTracer, get_tracer


def test_a_span_records_its_name() -> None:
    tracer = RecordingTracer(redact_content=False)

    with tracer.span("transcription"):
        pass

    assert [span.name for span in tracer.spans] == ["transcription"]


def test_a_span_records_its_duration() -> None:
    """Per-stage latency is the point: "the note was slow" is not an answer."""
    tracer = RecordingTracer(redact_content=False)

    with tracer.span("generation"):
        pass

    assert tracer.spans[0].duration_ms >= 0


def test_attributes_set_inside_a_span_are_recorded() -> None:
    tracer = RecordingTracer(redact_content=False)

    with tracer.span("generation") as span:
        span.set(input_tokens=1200, model_id="test-model")

    assert tracer.spans[0].attributes["input_tokens"] == 1200
    assert tracer.spans[0].attributes["model_id"] == "test-model"


def test_redaction_removes_transcript_text() -> None:
    """No patient content may reach a tracing backend from production."""
    tracer = RecordingTracer(redact_content=True)

    with tracer.span("transcription") as span:
        span.set(transcript_text="My hip has been aching all night.", speaker_count=2)

    assert "transcript_text" not in tracer.spans[0].attributes


def test_redaction_removes_the_note_body() -> None:
    tracer = RecordingTracer(redact_content=True)

    with tracer.span("generation") as span:
        span.set(note_sections={"observations": "Ate half of lunch."})

    assert "note_sections" not in tracer.spans[0].attributes


def test_redaction_keeps_the_signal_the_trace_exists_for() -> None:
    """Everything here is non-content and is exactly what a regression looks like."""
    tracer = RecordingTracer(redact_content=True)

    with tracer.span("generation") as span:
        span.set(
            prompt_version="soapie_v1",
            model_id="test-model",
            input_tokens=1200,
            output_tokens=400,
            cost_usd="0.0042",
            audio_seconds=612.0,
            speaker_count=2,
            flag_codes=["MISSING_VITALS"],
            schema_valid=True,
            repair_attempted=False,
            transcript_confidence=0.94,
        )

    recorded = tracer.spans[0].attributes
    assert recorded["prompt_version"] == "soapie_v1"
    assert recorded["flag_codes"] == ["MISSING_VITALS"]
    assert recorded["repair_attempted"] is False
    assert recorded["transcript_confidence"] == 0.94


def test_flag_codes_are_not_treated_as_content() -> None:
    """A flag code is a label from a fixed vocabulary; it is not patient data."""
    tracer = RecordingTracer(redact_content=True)

    with tracer.span("flag_evaluation") as span:
        span.set(flag_codes=["UNREPORTED_CHANGE"], flag_severities=["critical"])

    assert tracer.spans[0].attributes["flag_codes"] == ["UNREPORTED_CHANGE"]


def test_content_survives_when_redaction_is_off() -> None:
    """Local development traces content on purpose; that is how prompts get debugged."""
    tracer = RecordingTracer(redact_content=False)

    with tracer.span("transcription") as span:
        span.set(transcript_text="My hip aches.")

    assert tracer.spans[0].attributes["transcript_text"] == "My hip aches."


def test_a_span_is_recorded_even_when_the_stage_raises() -> None:
    """A trace that only covers successes cannot explain a failure."""
    tracer = RecordingTracer(redact_content=False)

    with pytest.raises(RuntimeError), tracer.span("download"):
        raise RuntimeError("bucket unreachable")

    assert tracer.spans[0].name == "download"
    assert tracer.spans[0].error == "bucket unreachable"


def test_the_no_op_tracer_accepts_everything_and_records_nothing() -> None:
    """Tracing is optional; with it off, every call site must still work untouched."""
    tracer = NoOpTracer()

    with tracer.span("generation") as span:
        span.set(input_tokens=10, transcript_text="anything")

    assert tracer.spans == []


def test_tracing_is_disabled_by_default() -> None:
    get_tracer.cache_clear()

    assert isinstance(get_tracer(), NoOpTracer)

    get_tracer.cache_clear()
