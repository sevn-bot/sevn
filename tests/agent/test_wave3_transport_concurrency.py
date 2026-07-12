"""Wave 3 transport & text-assembly tests (P7, P11)."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic_ai.messages import ModelResponse, TextPart

from sevn.agent.adapters.tier_b_model import (
    _display_text_from_model_response,
    merge_adjacent_anthropic_text_blocks,
    pydantic_messages_to_anthropic_messages,
    sanitize_anthropic_messages,
)
from sevn.gateway.agent_turn import _tier_b_full_index_retry_warranted


def test_merge_adjacent_anthropic_text_blocks() -> None:
    blocks = [
        {"type": "text", "text": "On it."},
        {"type": "text", "text": "Saved."},
    ]
    assert merge_adjacent_anthropic_text_blocks(blocks) == [
        {"type": "text", "text": "On it.\n\nSaved."},
    ]


def test_sanitize_anthropic_messages_drops_empty_user_blocks() -> None:
    out = sanitize_anthropic_messages(
        [
            {"role": "user", "content": [{"type": "text", "text": ""}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        ],
    )
    assert out == [{"role": "assistant", "content": "ok"}]


def test_pydantic_messages_merge_adjacent_assistant_text_parts() -> None:
    resp = ModelResponse(parts=[TextPart(content="On it."), TextPart(content="Saved.")])
    out = pydantic_messages_to_anthropic_messages([resp])
    assert out == [{"role": "assistant", "content": "On it.\n\nSaved."}]


def test_display_text_joins_text_parts_with_blank_line() -> None:
    resp = ModelResponse(parts=[TextPart(content="On it."), TextPart(content="Saved.")])
    assert _display_text_from_model_response(resp) == "On it.\n\nSaved."


def test_full_index_retry_not_warranted_on_transport_failure() -> None:
    outcome = SimpleNamespace(
        status="failed",
        final_messages=(),
        had_tool_failures=False,
        failure_detail="LLM proxy returned 400 for /v1/messages",
    )
    assert _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=outcome) is False
