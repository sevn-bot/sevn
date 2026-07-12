"""W1 RED suite — tier-B ``_build_req`` chat_completions tool pairing (MiniMax 2013).

Contracts locked in ``plan/waveorch/minimax-2013-tool-pairing-wave-W0.md`` (D1-D6).
Drives ``build_tier_b_function_model`` through the request-capturing transport seam
so POSTed ``messages`` reflect ``repair_openai_tool_pairing`` once W2 wires it into
``_build_req``'s chat_completions branch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_model import (
    build_tier_b_function_model,
    coalesce_adjacent_openai_messages,
    finalize_openai_chat_messages,
    pydantic_messages_to_openai_chat,
    repair_openai_tool_pairing,
)
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import (
    ChatCompletionsTransport,
    StreamFinal,
    StreamTextDelta,
)

_SYNTHETIC_STUB_CONTENT = "[no result recorded]"

# W0.4 fixture — turn e15729 synthetic dangling ``run_code`` call (no operator text).
W1_DANGLING_RUN_CODE_FIXTURE: list[ModelMessage] = [
    ModelResponse(
        parts=[
            ToolCallPart(
                tool_name="run_code",
                args={"code": "result = await serp(query='…')\nresult"},
                tool_call_id="e15729-rc1",
            ),
        ],
    ),
]

W1_DANGLING_WITH_PRIOR_ROUND: list[ModelMessage] = [
    ModelRequest(parts=[UserPromptPart(content="search scores")]),
    ModelResponse(
        parts=[ToolCallPart(tool_name="read", args={"path": "x"}, tool_call_id="prior-1")],
    ),
    ModelRequest(
        parts=[ToolReturnPart(tool_name="read", content="ok", tool_call_id="prior-1")],
    ),
    ModelResponse(
        parts=[
            ToolCallPart(
                tool_name="run_code",
                args={"code": "result = await serp(query='…')\nresult"},
                tool_call_id="e15729-rc1",
            ),
        ],
    ),
]

W1_WELL_PAIRED_FIXTURE: list[ModelMessage] = [
    ModelRequest(parts=[UserPromptPart(content="go")]),
    ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="t1")]),
    ModelRequest(parts=[ToolReturnPart(tool_name="read", content="ok", tool_call_id="t1")]),
    ModelResponse(parts=[TextPart(content="done")]),
]


def _info() -> AgentInfo:
    return AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=None,
    )


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _CapturingChatTransport(ChatCompletionsTransport):
    """Captures the last ``complete`` request body."""

    captured: dict[str, object]

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.captured = dict(request)
        return _openai_assistant_text("ok")


class _CapturingStreamChatTransport(ChatCompletionsTransport):
    """Captures the ``complete_stream`` request body."""

    captured: dict[str, object]

    async def complete_stream(
        self,
        request: dict[str, object],
    ) -> AsyncIterator[StreamTextDelta | StreamFinal]:
        self.captured = dict(request)
        yield StreamTextDelta(text="ok")
        yield StreamFinal(response=_openai_assistant_text("ok"))


def _build_chat_model(
    transport: ChatCompletionsTransport,
    *,
    agent: str = "tier_b",
    session_id: str = "sess-w1",
    turn_id: str = "turn-w1",
) -> Any:
    return build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="openai/gpt-test",
            transport=transport,
            budget=ModelBudget(
                model_id="openai/gpt-test",
                regime=BudgetRegime.PER_TOKEN,
            ),
        ),
        steer_buffer=None,
        trace=None,
        session_id=session_id,
        turn_id=turn_id,
        provider_round_counter=[0],
        agent=agent,
    )


def _non_system_messages(request: dict[str, object]) -> list[dict[str, Any]]:
    messages = request.get("messages")
    assert isinstance(messages, list)
    return [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]


def _assistant_tool_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            if isinstance(call, dict) and call.get("id"):
                ids.add(str(call["id"]))
    return ids


def _tool_result_ids(messages: list[dict[str, Any]]) -> set[str]:
    return {
        str(msg["tool_call_id"])
        for msg in messages
        if msg.get("role") == "tool" and msg.get("tool_call_id")
    }


def _assert_fully_paired(messages: list[dict[str, Any]]) -> None:
    call_ids = _assistant_tool_call_ids(messages)
    result_ids = _tool_result_ids(messages)
    assert call_ids == result_ids, (
        f"unmatched tool pairing: call_ids={call_ids!r} result_ids={result_ids!r}"
    )


def _assert_tool_stub(
    messages: list[dict[str, Any]],
    tool_call_id: str,
    *,
    content: str = _SYNTHETIC_STUB_CONTENT,
) -> None:
    tool_rows = [
        m
        for m in messages
        if m.get("role") == "tool" and str(m.get("tool_call_id")) == tool_call_id
    ]
    assert len(tool_rows) == 1, f"expected one tool row for {tool_call_id!r}, got {tool_rows!r}"
    assert tool_rows[0].get("content") == content


def _manual_chat_projection(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Simulate post-repair OpenAI-row hygiene (W0.3 ordering)."""
    repaired = repair_openai_tool_pairing(messages)
    return finalize_openai_chat_messages(
        coalesce_adjacent_openai_messages(pydantic_messages_to_openai_chat(repaired)),
    )


@pytest.mark.asyncio
async def test_build_req_dangling_run_code_gets_synthetic_tool_stub() -> None:
    """W1.1 — dangling ``run_code`` call (§W0.4) must POST a paired synthetic ``tool`` row."""
    transport = _CapturingChatTransport(proxy_base_url="http://w1-dangling.test")
    model = _build_chat_model(transport)
    await model.function(W1_DANGLING_RUN_CODE_FIXTURE, _info())

    messages = _non_system_messages(transport.captured)
    _assert_tool_stub(messages, "e15729-rc1")
    _assert_fully_paired(messages)


@pytest.mark.asyncio
async def test_build_req_dangling_after_well_paired_round_gets_stub() -> None:
    """W1.1 extension — CodeMode-faithful history; dangling ``run_code`` still paired."""
    transport = _CapturingChatTransport(proxy_base_url="http://w1-dangling-prior.test")
    model = _build_chat_model(transport)
    await model.function(W1_DANGLING_WITH_PRIOR_ROUND, _info())

    messages = _non_system_messages(transport.captured)
    _assert_tool_stub(messages, "e15729-rc1")
    _assert_fully_paired(messages)


@pytest.mark.asyncio
async def test_build_req_orphan_tool_return_dropped() -> None:
    """W1.2 — orphan ``tool`` return (no preceding call) is dropped; request stays valid."""
    transport = _CapturingChatTransport(proxy_base_url="http://w1-orphan.test")
    model = _build_chat_model(transport)
    history: list[ModelMessage] = [
        ModelRequest(
            parts=[
                UserPromptPart(content="hi"),
                ToolReturnPart(tool_name="x", content="zz", tool_call_id="ghost"),
            ],
        ),
    ]
    await model.function(history, _info())

    messages = _non_system_messages(transport.captured)
    assert _tool_result_ids(messages) == set()
    assert messages == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_well_paired_history_idempotent_through_builder() -> None:
    """W1.3 — well-paired history is unchanged when repair is a no-op (idempotence)."""
    transport = _CapturingChatTransport(proxy_base_url="http://w1-idempotent.test")
    model = _build_chat_model(transport)
    await model.function(W1_WELL_PAIRED_FIXTURE, _info())

    captured = _non_system_messages(transport.captured)
    expected = _manual_chat_projection(W1_WELL_PAIRED_FIXTURE)
    assert captured == expected
    assert repair_openai_tool_pairing(W1_WELL_PAIRED_FIXTURE) == W1_WELL_PAIRED_FIXTURE


@pytest.mark.asyncio
async def test_triager_clean_history_unchanged_through_builder() -> None:
    """W1.4 — triager chat_completions build with clean history is unchanged (D3)."""
    transport = _CapturingChatTransport(proxy_base_url="http://w1-triager.test")
    model = _build_chat_model(
        transport,
        agent="triager",
        session_id="triager",
        turn_id="triager",
    )
    await model.function(W1_WELL_PAIRED_FIXTURE, _info())

    captured = _non_system_messages(transport.captured)
    expected = _manual_chat_projection(W1_WELL_PAIRED_FIXTURE)
    assert captured == expected


@pytest.mark.asyncio
async def test_complete_stream_applies_same_tool_pairing_repair() -> None:
    """W1.5 — ``complete_stream`` path uses the same ``_build_req`` repair as non-stream."""
    transport = _CapturingStreamChatTransport(proxy_base_url="http://w1-stream.test")
    model = _build_chat_model(transport)
    assert model.stream_function is not None

    async for _chunk in model.stream_function(W1_DANGLING_RUN_CODE_FIXTURE, _info()):
        pass

    messages = _non_system_messages(transport.captured)
    _assert_tool_stub(messages, "e15729-rc1")
    _assert_fully_paired(messages)


@pytest.mark.asyncio
async def test_openai_tool_pairing_repaired_log_emitted_on_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.6 — D5 debug_event + logger.info fire when repair changes the message list."""
    debug_events: list[tuple[str, dict[str, object]]] = []
    info_records: list[str] = []

    def _capture_debug(event: str, **fields: object) -> None:
        debug_events.append((event, dict(fields)))

    def _capture_info(message: str, *args: object, **_kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr("sevn.logging.structured.debug_event", _capture_debug)
    monkeypatch.setattr(
        "sevn.agent.adapters.tier_b_model.logger.info",
        _capture_info,
    )

    transport = _CapturingChatTransport(proxy_base_url="http://w1-log-change.test")
    model = _build_chat_model(transport, session_id="sess-log", turn_id="turn-log")
    await model.function(W1_DANGLING_RUN_CODE_FIXTURE, _info())

    pairing_events = [e for e, _ in debug_events if e == "tier_b.openai_tool_pairing_repaired"]
    assert pairing_events, (
        f"expected debug_event tier_b.openai_tool_pairing_repaired, got {debug_events!r}"
    )

    _, fields = next(e for e in debug_events if e[0] == "tier_b.openai_tool_pairing_repaired")
    assert fields.get("session_id") == "sess-log"
    assert fields.get("turn_id") == "turn-log"
    assert isinstance(fields.get("synthesized"), int)
    assert isinstance(fields.get("dropped"), int)
    assert int(fields["synthesized"]) >= 1

    repaired_logs = [m for m in info_records if "tier_b.openai_tool_pairing_repaired" in m]
    assert repaired_logs
    assert "session_id=sess-log" in repaired_logs[0]
    assert "turn_id=turn-log" in repaired_logs[0]


@pytest.mark.asyncio
async def test_openai_tool_pairing_repaired_log_suppressed_when_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.6 — no D5 log when repair is a no-op on an already well-paired history."""
    debug_events: list[str] = []
    info_records: list[str] = []

    def _capture_debug(event: str, **_fields: object) -> None:
        debug_events.append(event)

    def _capture_info(message: str, *_args: object, **_kwargs: object) -> None:
        info_records.append(message)

    monkeypatch.setattr("sevn.logging.structured.debug_event", _capture_debug)
    monkeypatch.setattr(
        "sevn.agent.adapters.tier_b_model.logger.info",
        _capture_info,
    )

    transport = _CapturingChatTransport(proxy_base_url="http://w1-log-noop.test")
    model = _build_chat_model(transport)
    await model.function(W1_WELL_PAIRED_FIXTURE, _info())

    assert "tier_b.openai_tool_pairing_repaired" not in debug_events
    assert not any("tier_b.openai_tool_pairing_repaired" in m for m in info_records)
