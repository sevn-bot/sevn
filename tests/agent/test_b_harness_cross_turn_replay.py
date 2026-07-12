"""Cross-turn provider-native transcript replay (W11)."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from sevn.agent.adapters.tier_b_model import pydantic_messages_to_anthropic_messages
from sevn.agent.transcript_replay import (
    TranscriptRow,
    anthropic_messages_to_pydantic_history,
    build_cross_turn_message_history,
    serialize_provider_turn_messages,
)


def test_two_turn_tool_conversation_replays_tool_use() -> None:
    """Prior assistant row with structured payload restores ``ToolCallPart`` history."""
    turn_one_messages = [
        ModelRequest(parts=[UserPromptPart(content="read a.py")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read",
                    args={"file_path": "a.py"},
                    tool_call_id="toolu_1",
                ),
            ],
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read",
                    content="file contents",
                    tool_call_id="toolu_1",
                ),
            ],
        ),
    ]
    provider_blob = serialize_provider_turn_messages(turn_one_messages)
    rows = [
        TranscriptRow(role="user", text="read a.py"),
        TranscriptRow(
            role="assistant",
            text="done",
            provider_turn_messages=provider_blob,
        ),
        TranscriptRow(role="user", text="now summarize it"),
    ]
    history = build_cross_turn_message_history(rows[:-1], replay_provider_history=True)
    assert len(history) == 3
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[2], ModelRequest)
    tool_parts = [p for p in history[1].parts if isinstance(p, ToolCallPart)]
    assert len(tool_parts) == 1
    assert tool_parts[0].tool_name == "read"


def test_replay_disabled_falls_back_to_text_only() -> None:
    provider_blob = serialize_provider_turn_messages(
        [
            ModelRequest(parts=[UserPromptPart(content="read a.py")]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read",
                        args={"file_path": "a.py"},
                        tool_call_id="toolu_1",
                    ),
                ],
            ),
        ],
    )
    rows = [
        TranscriptRow(role="user", text="read a.py"),
        TranscriptRow(
            role="assistant",
            text="done",
            provider_turn_messages=provider_blob,
        ),
    ]
    history = build_cross_turn_message_history(rows, replay_provider_history=False)
    assert len(history) == 2
    assert isinstance(history[1], ModelResponse)
    assert history[1].parts == [TextPart(content="done")]


def test_streaming_vs_batch_history_parity_thinking_text_tool_use() -> None:
    """Batch ingest and stored anthropic rows round-trip to identical egress."""
    api_content = [
        {"type": "thinking", "thinking": "plan", "signature": "sig"},
        {"type": "text", "text": "Answer."},
        {
            "type": "tool_use",
            "id": "toolu_parity",
            "name": "glob",
            "input": {"pattern": "*.py"},
        },
    ]
    batch_history = anthropic_messages_to_pydantic_history(
        [{"role": "assistant", "content": api_content}],
    )
    stored = serialize_provider_turn_messages(batch_history)
    replay_history = anthropic_messages_to_pydantic_history(stored)
    assert pydantic_messages_to_anthropic_messages(replay_history) == [
        {"role": "assistant", "content": api_content},
    ]


def test_followup_routing_policy_enables_replay() -> None:
    from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
    from sevn.agent.triager.routing_policy import apply_routing_policy

    result = TriageResult(
        intent=Intent.FOLLOWUP,
        complexity=ComplexityTier.B,
        first_message="Continuing.",
        tools=["read"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    adjusted = apply_routing_policy(result, current_message="and then?", turn_id="t1")
    assert adjusted.replay_provider_history is True
