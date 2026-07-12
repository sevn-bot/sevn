"""Tier-B per-round heartbeat + streaming_unavailable INFO demotion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai._agent_graph import ModelRequestNode
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_model import build_tier_b_function_model
from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from tests.agent.test_b_harness import (
    _base_triage,
    _make_tick_executor,
    _openai_assistant_text,
    _ScriptedChatTransport,
)


@pytest.mark.asyncio
async def test_streaming_unavailable_info_once_per_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``b_harness.streaming_unavailable`` logs at INFO at most once per turn."""
    info_records: list[str] = []

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr(
        "sevn.agent.executors.b_harness.logger.info",
        _capture_info,
    )

    def _failing_stream(self, ctx: Any) -> Any:  # type: ignore[no-untyped-def]
        raise RuntimeError("no stream")

    monkeypatch.setattr(ModelRequestNode, "stream", _failing_stream)

    exe, tool_set = _make_tick_executor()
    triage = _base_triage(tools=[])

    async def _once(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("done.")

    transport = _ScriptedChatTransport(_once)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.PER_TOKEN),
    )
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp_path),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )

    async def _sink(_text: str) -> None:
        return None

    await run_b_turn(
        workspace=ws,
        session=SessionHandle(session_id="s1"),
        turn_id="t1",
        triage=triage,
        incoming_text="hi",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=4),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s1",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=tool_set.registry_version,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t1",
        ),
        streaming_sink=_sink,
    )

    unavailable = [m for m in info_records if "streaming_unavailable" in m]
    assert len(unavailable) == 1


@pytest.mark.asyncio
async def test_agent_turn_heartbeat_one_info_per_counted_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counted outer rounds emit exactly one INFO ``agent_turn round=…`` line each."""
    from pydantic_ai.messages import ToolCallPart

    info_records: list[str] = []

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr(
        "sevn.agent.adapters.tier_b_model.logger.info",
        _capture_info,
    )

    transport = ChatCompletionsTransport()
    calls = 0

    async def _complete(req: dict) -> dict:  # type: ignore[type-arg]
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "read", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        return {
            "choices": [{"message": {"role": "assistant", "content": "done"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    transport.complete = _complete  # type: ignore[method-assign]

    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="test-model",
            transport=transport,
            budget=ModelBudget(model_id="test-model", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        count_planning=False,
        max_rounds=5,
    )
    info = AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions="",
    )

    await model.function(
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
        info,
    )
    await model.function(
        [
            ModelRequest(parts=[UserPromptPart(content="hi")]),
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read", args={}, tool_call_id="c1"),
                ]
            ),
        ],
        info,
    )

    heartbeats = [m for m in info_records if m.startswith("agent_turn round=")]
    assert len(heartbeats) == 1
    assert "tier=B" in heartbeats[0]
    assert "tools_used=1" in heartbeats[0]
    assert "elapsed_ms=" in heartbeats[0]
