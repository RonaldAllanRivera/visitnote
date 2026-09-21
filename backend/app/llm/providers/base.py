"""LLM provider protocol.

One method, because the pipeline only ever does one thing to a model: hand it a
system prompt, hand it the transcript, and require structured output matching a
schema. Anything richer would be an SDK surface leaking through the seam.

No vendor type crosses this boundary. `LLMResult` and `LLMUsage` are what the
pipeline, the eval runner, and the tracing layer see -- which is what makes it
possible to swap providers, and to run the entire suite with no API key.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LLMOutputError(Exception):
    """The model returned something that is not usable structured output.

    Distinct from a transport error: a 500 from the provider should be retried as a
    job, while unusable output is retried once with a repair instruction and then
    gives up. Conflating them would burn all three attempts on a model that is
    reliably producing prose.
    """


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """What a single generation cost, in provider-neutral terms.

    Recorded on the job so per-note margin is visible in the operator console
    without querying a vendor dashboard.
    """

    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class LLMResult:
    data: dict[str, Any]
    usage: LLMUsage


class LLMProvider(Protocol):
    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], model_id: str
    ) -> LLMResult: ...


@lru_cache
def get_llm_provider() -> LLMProvider:
    """Resolve the configured LLM backend.

    The same fallback rule as storage and transcription, and for the sharpest reason
    of the three: a production note produced by a fixture provider would be a
    fabricated clinical record that looks exactly like a real one.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        if settings.is_production:
            raise RuntimeError("LLM provider is not configured; set ANTHROPIC_API_KEY")
        logger.warning(
            "LLM provider is not configured; using the fake provider. "
            "Generated notes will be fixtures.",
            extra={"environment": settings.environment},
        )
        from app.llm.providers.fake import FakeLLMProvider

        return FakeLLMProvider()

    from app.llm.providers.anthropic import AnthropicProvider

    return AnthropicProvider()
