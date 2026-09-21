"""Pipeline tracing.

One trace per visit, with a span per stage: download, normalise, transcribe,
generate, repair retry if there was one, and flag evaluation.

**Content redaction is on by default in production**, so no transcript text and no
note body leaves the system. That is the correct privacy posture, and it means the
trace has to carry enough non-content signal to still be worth having. The
`_CONTENT_ATTRIBUTES` set below is the entire list of things redaction removes:
everything else -- prompt version, model id, token counts, cost, per-stage latency,
audio duration, speaker count, flag *codes*, schema validity, whether a repair was
needed, transcript confidence -- is recorded either way, and answers the questions
tracing exists to answer.

Redaction works by denylist rather than allowlist deliberately. An allowlist would
silently drop a new diagnostic attribute someone adds later, and a trace that
quietly loses signal is worse than one that never had it.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Attributes that carry patient content. These are the only things redaction
# removes, and the only things that must never reach a tracing backend from
# production.
_CONTENT_ATTRIBUTES = frozenset(
    {
        "transcript_text",
        "transcript_turns",
        "note_sections",
        "note_visit_details",
        "system_prompt",
        "user_content",
        "flag_messages",
        "repair_instruction",
    }
)


@dataclass
class RecordedSpan:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: str | None = None


class SpanHandle(Protocol):
    def set(self, **attributes: Any) -> None: ...


@dataclass
class _Span:
    record: RecordedSpan
    redact_content: bool

    def set(self, **attributes: Any) -> None:
        for key, value in attributes.items():
            if self.redact_content and key in _CONTENT_ATTRIBUTES:
                continue
            self.record.attributes[key] = value


class Tracer:
    """Base tracer. Times each span and hands the finished record to `emit`."""

    def __init__(self, *, redact_content: bool = True) -> None:
        self.redact_content = redact_content

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[SpanHandle]:
        record = RecordedSpan(name=name)
        handle = _Span(record=record, redact_content=self.redact_content)
        handle.set(**attributes)

        started = time.monotonic()
        try:
            yield handle
        except Exception as exc:
            # Recorded before re-raising. A trace that covers only the successful
            # runs cannot explain the failed ones, which are the runs anyone
            # actually opens a tracing tool to look at.
            record.error = str(exc)
            raise
        finally:
            record.duration_ms = int((time.monotonic() - started) * 1000)
            self.emit(record)

    def emit(self, span: RecordedSpan) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def flush(self) -> None:
        """Send anything buffered. A no-op unless the backend buffers."""
        return None

    @property
    def spans(self) -> list[RecordedSpan]:
        return []


class NoOpTracer(Tracer):
    """What runs when tracing is switched off.

    Every call site behaves identically with tracing on or off, so there is no
    `if tracing_enabled` anywhere in the pipeline.
    """

    def emit(self, span: RecordedSpan) -> None:
        return None


class RecordingTracer(Tracer):
    """Keeps spans in memory, for tests and for local inspection."""

    def __init__(self, *, redact_content: bool = True) -> None:
        super().__init__(redact_content=redact_content)
        self._spans: list[RecordedSpan] = []

    def emit(self, span: RecordedSpan) -> None:
        self._spans.append(span)

    @property
    def spans(self) -> list[RecordedSpan]:
        return self._spans


@lru_cache
def get_tracer() -> Tracer:
    settings = get_settings()

    if not settings.langfuse_enabled:
        return NoOpTracer()

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("LANGFUSE_ENABLED is set but no keys are configured; tracing is off")
        return NoOpTracer()

    from app.observability.langfuse import LangfuseTracer

    return LangfuseTracer(redact_content=settings.langfuse_redact_content)
