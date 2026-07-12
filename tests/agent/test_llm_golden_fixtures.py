"""Golden LLM response fixtures vs ``Transport.tokens_used`` / ``cache_breakpoints``.

Verifies wire-shape parsing for stub transports per ``specs/01-system-overview.md`` §10.4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.adapters.tier_b_model import (
    anthropic_completion_to_model_response,
    bedrock_converse_to_model_response,
)
from sevn.agent.providers.transport import (
    AnthropicTransport,
    BedrockTransport,
    ChatCompletionsTransport,
    ResponsesApiTransport,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "llm"


def _load(name: str) -> dict[str, Any]:
    path = _FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture", "transport", "expected"),
    [
        ("anthropic_messages_completion.json", AnthropicTransport(), (42, 7)),
        ("openai_chat_completion.json", ChatCompletionsTransport(), (100, 25)),
        ("openai_responses_completion.json", ResponsesApiTransport(), (3, 9)),
        ("bedrock_converse.json", BedrockTransport(), (11, 22)),
    ],
)
def test_tokens_used_matches_fixture(
    fixture: str,
    transport: AnthropicTransport
    | ChatCompletionsTransport
    | ResponsesApiTransport
    | BedrockTransport,
    expected: tuple[int, int],
) -> None:
    """Each provider fixture exercises ``tokens_used`` for that transport family."""
    response = _load(fixture)
    assert transport.tokens_used(response) == expected


@pytest.mark.parametrize(
    ("fixture", "parser"),
    [
        ("anthropic_messages_response_text.json", anthropic_completion_to_model_response),
        ("bedrock_converse_response_text.json", bedrock_converse_to_model_response),
    ],
)
def test_vendor_response_fixtures_parse_to_model_response(
    fixture: str,
    parser: object,
) -> None:
    """Wave P vendor-mock fixtures exercise tier-B response parsers."""
    data = _load(fixture)
    resp = parser(data)  # type: ignore[operator]
    assert len(resp.parts) >= 1


@pytest.mark.parametrize(
    "transport",
    [
        AnthropicTransport(),
        ChatCompletionsTransport(),
        ResponsesApiTransport(),
        BedrockTransport(),
    ],
)
def test_cache_breakpoints_pass_through(
    transport: AnthropicTransport
    | ChatCompletionsTransport
    | ResponsesApiTransport
    | BedrockTransport,
) -> None:
    """Phase-1 transports return a shallow copy of prompt segments (§2.4)."""
    segments: list[dict[str, object]] = [{"role": "system", "content": "x"}]
    out = transport.cache_breakpoints(segments)
    assert out == segments
    assert out is not segments
