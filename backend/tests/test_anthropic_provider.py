"""Anthropic provider response handling.

Tested against synthetic content blocks rather than a live call. The blocks are
duck-typed here on purpose: if these tests ever needed to import an SDK class, the
"no vendor type escapes the provider module" rule would already be broken.
"""

from dataclasses import dataclass

import pytest

from app.llm.providers.anthropic import extract_json
from app.llm.providers.base import LLMOutputError


@dataclass
class _Block:
    type: str
    text: str = ""


def test_parses_the_json_carried_by_the_first_text_block() -> None:
    blocks = [_Block(type="text", text='{"sections": {"handover": "Restock gauze."}, "flags": []}')]

    assert extract_json(blocks) == {"sections": {"handover": "Restock gauze."}, "flags": []}


def test_skips_non_text_blocks() -> None:
    """Adaptive thinking is on by default, so a thinking block can precede the answer."""
    blocks = [_Block(type="thinking"), _Block(type="text", text='{"sections": {}, "flags": []}')]

    assert extract_json(blocks) == {"sections": {}, "flags": []}


def test_prose_instead_of_json_is_an_output_error() -> None:
    """Distinct from a transport error: this is repaired once, not retried three times."""
    blocks = [_Block(type="text", text="I'm sorry, I can't summarise this recording.")]

    with pytest.raises(LLMOutputError):
        extract_json(blocks)


def test_a_response_with_no_text_block_is_an_output_error() -> None:
    with pytest.raises(LLMOutputError):
        extract_json([_Block(type="thinking")])


def test_a_json_array_is_rejected_because_the_contract_is_an_object() -> None:
    blocks = [_Block(type="text", text='["sections", "flags"]')]

    with pytest.raises(LLMOutputError):
        extract_json(blocks)
