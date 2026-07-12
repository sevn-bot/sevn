"""Agent context trace snapshots."""

from __future__ import annotations

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from sevn.agent.tracing.agent_context import (
    build_tier_b_context_attrs,
    build_triager_context_attrs,
    serialize_message_history_for_trace,
    trace_text_field,
)


def test_trace_text_field_truncates_long_text() -> None:
    out = trace_text_field("a" * 50, field="body", max_chars=10)
    assert out["body_truncated"] is True
    assert out["body_chars"] == 50
    assert len(str(out["body"])) == 11


def test_build_triager_context_attrs_includes_segments() -> None:
    attrs = build_triager_context_attrs(
        segments=("static", "registry", "personality", "suffix"),
        current_message="hello",
        transcript_turns=["user: hi"],
        registry_version=2,
        personality_version=3,
        user_language="en",
        attachment_hints=[{"kind": "image"}],
        user_blob="full prompt",
    )
    assert attrs["agent"] == "triager"
    assert attrs["current_message"] == "hello"
    assert attrs["prompt_segments"]["static_prefix"] == "static"


def test_build_tier_b_context_attrs_includes_history() -> None:
    history = [
        ModelRequest(parts=[UserPromptPart(content="prior")]),
        ModelResponse(parts=[TextPart(content="reply")]),
    ]
    attrs = build_tier_b_context_attrs(
        incoming_text="now",
        triager_first_reply="ack",
        system_prompt="sys",
        instructions="inst",
        message_history=history,
        user_prompt="now",
        tools=["read"],
        skills=["pdf"],
    )
    assert attrs["agent"] == "tier_b"
    assert attrs["operator_message"] == "now"
    assert attrs["message_history_count"] == 2
    assert serialize_message_history_for_trace(history)[0]["kind"] == "request"
