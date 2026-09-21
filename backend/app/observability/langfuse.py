"""Langfuse tracing backend.

The only module that imports the Langfuse SDK. Everything else sees `Tracer` and
`RecordedSpan`, which is what makes the whole suite runnable with no tracing
backend and no keys.

Langfuse Cloud's free tier is the default. Self-hosting is a documented option in
the deployment guide rather than the default: its stack wants PostgreSQL,
ClickHouse, Redis and object storage, which is a lot to run beside api/worker/redis
on a small VM -- and an out-of-memory kill there takes down the product, not just
the tracing.
"""

import logging

from app.core.config import get_settings
from app.observability.tracing import RecordedSpan, Tracer

logger = logging.getLogger(__name__)


class LangfuseTracer(Tracer):
    def __init__(self, *, redact_content: bool = True) -> None:
        super().__init__(redact_content=redact_content)
        settings = get_settings()

        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )

    def emit(self, span: RecordedSpan) -> None:
        """Send a finished span.

        The pipeline stamps every span of one visit with the same `trace_id`, which
        is passed through as the trace context here -- that is what turns six
        separate events into one trace per visit, with download, transcription and
        generation legible as stages of the same piece of work.

        Failures are logged and swallowed. Observability must never be able to fail
        the work it observes: a note that was generated correctly must not be marked
        failed because a tracing backend was unreachable.
        """
        trace_id = span.attributes.get("trace_id")

        try:
            self._client.create_event(
                # A Langfuse trace id is a 32-character lowercase hex string, which
                # is exactly what `uuid4().hex` produces upstream.
                trace_context={"trace_id": str(trace_id)} if trace_id else None,
                name=span.name,
                metadata={**span.attributes, "duration_ms": span.duration_ms},
                level="ERROR" if span.error else "DEFAULT",
                status_message=span.error,
            )
        except Exception:
            logger.warning("failed to emit trace span", extra={"span": span.name}, exc_info=True)

    def flush(self) -> None:
        """Send anything still buffered.

        The worker is a short-lived process per job batch; without an explicit flush
        the last spans of a run can be lost when it exits.
        """
        try:
            self._client.flush()
        except Exception:
            logger.warning("failed to flush traces", exc_info=True)
