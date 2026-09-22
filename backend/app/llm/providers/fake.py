"""In-memory LLM provider for tests, evals, and local development.

Scripted rather than mocked: a test hands it the exact payloads a model would have
returned and then asserts on what the pipeline did with them. That is how the repair
retry, the failure path, and flag persistence are all tested without a paid API call.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from app.llm.providers.base import LLMResult, LLMUsage

# What an unscripted fake writes into every section. Deliberately unmistakable:
# a placeholder that reads like a real note is a trap for whoever sees it next.
PLACEHOLDER = "[fake provider] No model was called. Configure ANTHROPIC_API_KEY."


def response_for_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Build a conforming answer from the output schema.

    An unscripted fake cannot use a fixed payload: note formats have different
    section keys, and a payload that satisfies one fails validation against another.
    Deriving it from the schema is what makes `docker compose up` produce a working
    end-to-end flow with no API key -- otherwise every recording in local
    development fails at generation.

    A repeating section (FDAR's focus entries) is a JSON Schema array of objects,
    not a string like every other section, so it needs a list of entries rather
    than the placeholder every flat section gets -- a string there fails
    validate_output, and the fake is sticky, so the repair attempt would return the
    same non-conforming payload.
    """
    properties = schema.get("properties", {})

    def keys_of(name: str) -> list[str]:
        return list(properties.get(name, {}).get("properties", {}))

    section_properties: dict[str, Any] = properties.get("sections", {}).get("properties", {})

    return {
        # Null throughout: the fake was not given a transcript to read times off,
        # and inventing them is the one thing this system must never model.
        "visit_details": dict.fromkeys(keys_of("visit_details")),
        "sections": {
            key: _section_value(section_schema)
            for key, section_schema in section_properties.items()
        },
        "flags": [],
    }


def _section_value(section_schema: dict[str, Any]) -> Any:
    if section_schema.get("type") != "array":
        return PLACEHOLDER

    entry_keys = list(section_schema.get("items", {}).get("properties", {}))
    # Two entries, not one: a single entry would not exercise the multi-entry path a
    # repeating section exists for, and that path is exactly what needs to be
    # reachable locally with no API key.
    return [dict.fromkeys(entry_keys, PLACEHOLDER) for _ in range(2)]


@dataclass(frozen=True, slots=True)
class RecordedCall:
    system: str
    user: str
    schema: dict[str, Any]
    model_id: str


@dataclass
class FakeLLMProvider:
    """Returns scripted responses in order.

    The last entry is sticky: a single configured response answers every call, which
    keeps the common case (one generation, no repair) free of ceremony. An entry that
    is an exception is raised instead of returned, which is how the failure paths are
    driven.
    """

    # Empty means "derive an answer from the schema", which is what local
    # development runs on. A test that cares about the content scripts it.
    responses: list[dict[str, Any] | Exception] = field(default_factory=list)
    calls: list[RecordedCall] = field(default_factory=list)
    _index: int = 0

    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], model_id: str
    ) -> LLMResult:
        started = time.monotonic()
        self.calls.append(
            RecordedCall(system=system, user=user, schema=schema, model_id=model_id)
        )

        if not self.responses:
            response: dict[str, Any] | Exception = response_for_schema(schema)
        else:
            response = self.responses[min(self._index, len(self.responses) - 1)]
        self._index += 1

        if isinstance(response, Exception):
            raise response

        return LLMResult(
            data=response,
            usage=LLMUsage(
                model_id=model_id,
                # Roughly four characters per token. Not accurate, but non-zero and
                # proportional to the prompt, so a cost assertion has something real
                # to work with.
                input_tokens=max(1, (len(system) + len(user)) // 4),
                output_tokens=max(1, len(str(response)) // 4),
                latency_ms=int((time.monotonic() - started) * 1000),
            ),
        )
