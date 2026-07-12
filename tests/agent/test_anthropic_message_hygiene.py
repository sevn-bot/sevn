"""Anthropic message coalescing and tool-pairing repair (§2 / 2013 fix)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_hooks import inject_owner_steer
from sevn.agent.adapters.tier_b_model import (
    SYNTHETIC_TOOL_RESULT_REPLAY_STUB,
    _count_replay_stub_tool_results,
    append_owner_steer_model_request,
    build_tier_b_function_model,
    coalesce_adjacent_anthropic_messages,
    prepare_anthropic_messages_for_transport,
    pydantic_messages_to_anthropic_messages,
    repair_anthropic_tool_pairing,
    replay_stubs_are_same_turn_only,
    strip_orphan_tool_result_blocks,
)
from sevn.agent.executors.b_types import ResolvedTierBModel, SteerInject
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import AnthropicMessagesTransport
from sevn.agent.transcript_replay import sanitize_provider_turn_messages_for_storage
from tests.agent.test_tier_b_hooks import _deps, _run_ctx


def _info() -> AgentInfo:
    return AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=MagicMock(),
        instructions=None,
    )


def _assert_no_consecutive_same_role(rows: list[dict[str, object]], role: str) -> None:
    roles = [row.get("role") for row in rows]
    for idx in range(len(roles) - 1):
        assert not (roles[idx] == role and roles[idx + 1] == role)


def test_coalesce_merges_tool_result_and_owner_steer_user_rows() -> None:
    raw = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "load_tool", "input": {"name": "read"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": '{"ok": false}'},
            ],
        },
        {"role": "user", "content": "[Owner steer] call list_registry directly"},
    ]
    out = coalesce_adjacent_anthropic_messages(raw)
    assert len(out) == 2
    user_blocks = out[1]["content"]
    assert isinstance(user_blocks, list)
    assert user_blocks[0]["type"] == "tool_result"
    assert user_blocks[1]["type"] == "text"


def test_repair_closes_trailing_orphan_tool_use_from_replay() -> None:
    """Cross-turn replay may end on ``run_code`` without ``tool_result`` (S2 2013)."""
    raw = [
        {"role": "user", "content": "earlier question"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "rc1", "name": "run_code", "input": {"code": "x = 1"}},
            ],
        },
    ]
    repaired = repair_anthropic_tool_pairing(raw)
    assert repaired[-1]["role"] == "user"
    blocks = repaired[-1]["content"]
    assert isinstance(blocks, list)
    assert blocks[0]["tool_use_id"] == "rc1"
    assert blocks[0]["is_error"] is False
    assert "replay_stub" in blocks[0]["content"]
    assert SYNTHETIC_TOOL_RESULT_REPLAY_STUB in blocks[0]["content"]


def test_strip_orphan_tool_result_drops_unpaired_result() -> None:
    # Contract: runs AFTER strip_orphan_tool_use_blocks, so a tool_result whose tool_use
    # is no longer present (it was stripped) must be dropped — this is the orphan that
    # makes MiniMax 400 (error 2013).
    rows = [
        {"role": "user", "content": [{"type": "text", "text": "actually, check the code"}]},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "minimax-xml-1", "content": "ok"},
            ],
        },
    ]
    out, stripped = strip_orphan_tool_result_blocks(rows)
    assert stripped == 1
    for row in out:
        content = row.get("content")
        if isinstance(content, list):
            assert not any(b.get("type") == "tool_result" for b in content)


def test_strip_orphan_tool_result_keeps_paired_result() -> None:
    # A tool_result whose tool_use still survives must be kept untouched.
    rows = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "minimax-xml-1", "name": "read", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "minimax-xml-1", "content": "ok"},
            ],
        },
    ]
    out, stripped = strip_orphan_tool_result_blocks(rows)
    assert stripped == 0
    assert out == rows


def test_prepare_pipeline_drops_orphan_result_from_split_replay() -> None:
    # End-to-end: the full transport pipeline must leave no tool_result whose tool_use
    # was stripped, so the MiniMax Anthropic POST stays valid.
    raw = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "minimax-xml-1", "name": "read", "input": {}},
            ],
        },
        {"role": "user", "content": "actually, check the code"},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "minimax-xml-1", "content": "ok"},
            ],
        },
    ]
    out = prepare_anthropic_messages_for_transport(raw)
    live_use_ids = {
        str(b.get("id"))
        for row in out
        if row.get("role") == "assistant" and isinstance(row.get("content"), list)
        for b in row["content"]
        if b.get("type") == "tool_use"
    }
    for row in out:
        content = row.get("content")
        if isinstance(content, list):
            for b in content:
                if b.get("type") == "tool_result":
                    assert str(b.get("tool_use_id")) in live_use_ids


def test_prepare_trailing_orphan_then_new_user_coalesces() -> None:
    raw = [
        {"role": "user", "content": "earlier"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "rc1", "name": "run_code", "input": {}},
            ],
        },
        {"role": "user", "content": "which tools and skills were used?"},
    ]
    out = prepare_anthropic_messages_for_transport(raw)
    _assert_no_consecutive_same_role(out, "user")
    assert _count_replay_stub_tool_results(out) == 0
    last_user = out[-1]
    assert last_user["role"] == "user"
    content = last_user["content"]
    if isinstance(content, list):
        assert not any(b.get("type") == "tool_result" for b in content)
        assert any(b.get("type") == "text" for b in content)
    else:
        assert "which tools and skills were used?" in str(content)


def test_repair_inserts_missing_tool_results_before_next_assistant() -> None:
    raw = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "gc1", "name": "get_page_content", "input": {}},
                {"type": "tool_use", "id": "gc2", "name": "get_page_content", "input": {}},
            ],
        },
        {"role": "assistant", "content": "continuing without results"},
    ]
    repaired = repair_anthropic_tool_pairing(raw)
    assert repaired[0]["role"] == "assistant"
    assert repaired[1]["role"] == "user"
    user_blocks = repaired[1]["content"]
    assert isinstance(user_blocks, list)
    assert len(user_blocks) == 2
    assert {b["tool_use_id"] for b in user_blocks} == {"gc1", "gc2"}


def test_prepare_pipeline_from_pydantic_tool_round_with_steer() -> None:
    history = [
        ModelRequest(parts=[UserPromptPart(content="what can you help with?")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="load_tool", args={"name": "list_registry"}, tool_call_id="tu1"
                ),
            ],
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="load_tool",
                    content='{"ok": false}',
                    tool_call_id="tu1",
                ),
            ],
        ),
        ModelRequest(parts=[UserPromptPart(content="[Owner steer] call list_registry")]),
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="run_code", args={"code": "..."}, tool_call_id="tu2"),
            ],
        ),
    ]
    out = pydantic_messages_to_anthropic_messages(history)
    _assert_no_consecutive_same_role(out, "user")
    _assert_no_consecutive_same_role(out, "assistant")


def test_parallel_get_page_content_then_read_round_trips() -> None:
    history = [
        ModelRequest(parts=[UserPromptPart(content="fetch DutchNews")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="get_page_content",
                    args={"url": "https://www.dutchnews.nl/"},
                    tool_call_id="gp1",
                ),
                ToolCallPart(
                    tool_name="get_page_content",
                    args={"url": "https://www.dutchnews.nl/news/"},
                    tool_call_id="gp2",
                ),
            ],
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(tool_name="get_page_content", content="ok1", tool_call_id="gp1"),
                ToolReturnPart(tool_name="get_page_content", content="ok2", tool_call_id="gp2"),
            ],
        ),
        ModelResponse(
            parts=[
                TextPart(content="reading saved files"),
                ToolCallPart(tool_name="read", args={"path": "out/x.md"}, tool_call_id="r1"),
            ],
        ),
    ]
    projected = pydantic_messages_to_anthropic_messages(history)
    out = prepare_anthropic_messages_for_transport(projected)
    assert _count_replay_stub_tool_results(out) == 0
    assert out[-1]["role"] == "assistant"
    assistant_content = out[-1]["content"]
    if isinstance(assistant_content, list):
        assert assistant_content[0]["type"] == "text"
        assert not any(b.get("type") == "tool_use" for b in assistant_content)
    else:
        assert assistant_content == "reading saved files"


def test_append_owner_steer_merges_into_trailing_model_request() -> None:
    merged = append_owner_steer_model_request(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="serp",
                        content="{}",
                        tool_call_id="s1",
                    ),
                ],
            ),
        ],
        "search again",
    )
    assert len(merged) == 1
    assert len(merged[0].parts) == 2
    assert isinstance(merged[0].parts[1], UserPromptPart)


@pytest.mark.asyncio
async def test_inject_owner_steer_hook_merges_into_trailing_request() -> None:
    steer = SteerInject(pending_text="retry with log_query")
    ctx = _run_ctx(_deps(steer=steer))
    request_context = ModelRequestContext(
        model=MagicMock(),
        messages=[
            ModelRequest(parts=[UserPromptPart(content="check logs")]),
            ModelResponse(parts=[TextPart(content="On it.")]),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="log_query",
                        content="[]",
                        tool_call_id="lq1",
                    ),
                ],
            ),
        ],
        model_settings=None,
        model_request_parameters=MagicMock(),
    )
    updated = await inject_owner_steer(ctx, request_context)
    assert len(updated.messages) == 3
    last = updated.messages[-1]
    assert isinstance(last, ModelRequest)
    assert len(last.parts) == 2


def test_sanitize_then_transport_has_zero_replay_stubs_for_complete_turn() -> None:
    history = [
        ModelRequest(parts=[UserPromptPart(content="read a.py")]),
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="read", args={"path": "a.py"}, tool_call_id="r1"),
            ],
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read",
                    content='{"ok": true}',
                    tool_call_id="r1",
                ),
            ],
        ),
        ModelResponse(parts=[TextPart(content="Done.")]),
    ]
    raw = pydantic_messages_to_anthropic_messages(history)
    sanitized, stripped = sanitize_provider_turn_messages_for_storage(raw)
    assert stripped == 0
    transport = prepare_anthropic_messages_for_transport(sanitized)
    assert _count_replay_stub_tool_results(transport) == 0


def test_sanitize_orphan_tail_yields_zero_replay_stubs_on_transport() -> None:
    raw = [
        {"role": "user", "content": "run code"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "rc1", "name": "run_code", "input": {}},
            ],
        },
    ]
    sanitized, stripped = sanitize_provider_turn_messages_for_storage(raw)
    assert stripped == 1
    assert sanitized == [{"role": "user", "content": "run code"}]
    transport = prepare_anthropic_messages_for_transport(sanitized)
    assert _count_replay_stub_tool_results(transport) == 0


def test_replay_stub_same_turn_classification() -> None:
    projected = [
        {"role": "user", "content": "prior"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "new question"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
            ],
        },
    ]
    repaired = repair_anthropic_tool_pairing(projected)
    assert replay_stubs_are_same_turn_only(
        projected=projected,
        repaired=repaired,
        turn_message_start_index=2,
    )
    assert not replay_stubs_are_same_turn_only(
        projected=projected,
        repaired=repaired,
        turn_message_start_index=4,
    )


def test_replay_stub_cross_turn_classification() -> None:
    projected = [
        {"role": "user", "content": "prior"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "old1", "name": "run_code", "input": {}},
            ],
        },
        {"role": "user", "content": "follow up"},
    ]
    repaired = repair_anthropic_tool_pairing(projected)
    assert not replay_stubs_are_same_turn_only(
        projected=projected,
        repaired=repaired,
        turn_message_start_index=2,
    )


@pytest.mark.asyncio
async def test_same_turn_orphan_tool_use_strips_without_replay_stub_warning() -> None:
    class _CapturingAnthropic(AnthropicMessagesTransport):
        def __init__(self) -> None:
            super().__init__(proxy_base_url="http://test")

        async def complete(self, request: dict[str, object]) -> dict[str, object]:
            return {
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "stop_reason": "end_turn",
            }

    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M3",
            transport=_CapturingAnthropic(),
            budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        agent="tier_b",
        turn_message_start_index=0,
    )
    history = [
        ModelRequest(parts=[UserPromptPart(content="run")]),
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="run_code", args={"code": "1"}, tool_call_id="rc1"),
            ],
        ),
    ]
    with patch("sevn.agent.adapters.tier_b_model.logger.warning") as mock_warning:
        await model.function(history, _info())
    assert mock_warning.call_count == 0
