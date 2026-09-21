"""Anthropic LLM provider.

The only module in the system that imports the Anthropic SDK. Everything downstream
sees `LLMResult` and `LLMUsage`.

No model identifier is written here. It arrives as an argument, sourced from
`note_templates.model_id` with the config default behind it, so pinning a different
model for one note format is a data change rather than a deployment.
"""

import json
import logging
import time
from typing import Any, Protocol, cast

import anthropic
from anthropic.types.output_config_param import OutputConfigParam

from app.core.config import get_settings
from app.llm.providers.base import LLMOutputError, LLMResult, LLMUsage

logger = logging.getLogger(__name__)

# A generated note is a few thousand tokens at most; this is headroom, not a target.
# Comfortably under the SDK's non-streaming HTTP timeout.
MAX_OUTPUT_TOKENS = 8_000


class _ContentBlock(Protocol):
    """The shape this module needs from a response block, and nothing more."""

    @property
    def type(self) -> str: ...


def extract_json(blocks: list[Any]) -> dict[str, Any]:
    """Pull the structured output out of a response.

    `output_config.format` constrains the model to emit JSON in a text block, but the
    response can still carry other blocks in front of it -- adaptive thinking is on by
    default on the current models -- so the first *text* block is the one to read.

    A failure here is an output error, not a transport error. The distinction matters
    downstream: unusable output is repaired once and then abandoned, while a 500 from
    the provider is retried as a job. Conflating them would spend all three job
    attempts on a model that is reliably producing prose.
    """
    for block in blocks:
        if getattr(block, "type", None) != "text":
            continue

        text = getattr(block, "text", "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"model returned text that is not JSON: {text[:200]}") from exc

        if not isinstance(parsed, dict):
            raise LLMOutputError(f"expected a JSON object, got {type(parsed).__name__}")
        return cast(dict[str, Any], parsed)

    raise LLMOutputError("response contained no text block")


class AnthropicProvider:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._effort = settings.llm_effort

    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], model_id: str
    ) -> LLMResult:
        started = time.monotonic()

        # Constrains the response to the note template's own schema. Validation still
        # happens afterwards with Pydantic: this makes malformed output rare, it does
        # not make it impossible.
        #
        # No temperature is set. The current models reject sampling parameters
        # outright, and the schema constraint is what buys determinism here anyway.
        output_config: OutputConfigParam = {
            "format": {"type": "json_schema", "schema": schema},
            # The cost lever, kept in configuration so it can be tuned against eval
            # scores without a deployment.
            "effort": self._effort,
        }

        response = await self._client.messages.create(
            model=model_id,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "max_tokens":
            raise LLMOutputError("generation hit the output limit and was truncated")

        return LLMResult(
            data=extract_json(list(response.content)),
            usage=LLMUsage(
                model_id=model_id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
            ),
        )
