"""Turn-root ``parent_span_id`` linkage for tool and provider spans (Wave T-1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_model import build_tier_b_function_model
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import TraceSink
from sevn.tools.base import FunctionTool, ToolCall, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import TracingToolExecutor


class _RecordingTrace(TraceSink):
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _EchoExecutor(ToolExecutor):
    def __init__(self) -> None:
        super().__init__(default_timeout_seconds=5.0)

        async def body(ctx: ToolContext, **_kwargs: Any) -> str:
            _ = ctx
            return enveloped_success({"pong": True})

        definition = ToolDefinition(
            name="echo",
            category="meta",
            description="echo",
            parameters={"type": "object", "properties": {}},
        )
        self.register(FunctionTool(definition, body))


@pytest.mark.asyncio
async def test_tracing_tool_executor_parent_is_turn_span_id(tmp_path: Path) -> None:
    turn_root = "gateway-turn-root-abc"
    trace = _RecordingTrace()
    ctx = ToolContext(
        session_id="s1",
        workspace_path=tmp_path,
        workspace_id="w1",
        registry_version=1,
        trace=trace,
        permissions=AllowAllPermissionPolicy(),
        turn_id="t1",
        turn_span_id=turn_root,
        executor_tier="B",
    )
    inner = _EchoExecutor()
    exe = TracingToolExecutor(default_timeout_seconds=5.0)
    for tool in inner._tools.values():
        exe.register(tool)
    await exe.dispatch(ctx, ToolCall(name="echo", arguments={}))
    tool_events = [e for e in trace.events if e.kind == "tool.echo"]
    assert tool_events
    assert all(e.parent_span_id == turn_root for e in tool_events)


@pytest.mark.asyncio
async def test_tier_b_provider_span_parent_is_turn_root() -> None:
    turn_root = "gateway-turn-root-xyz"
    trace = _RecordingTrace()

    class _StubTransport(ChatCompletionsTransport):
        async def complete(self, request: dict[str, object]) -> dict[str, object]:
            _ = request
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="openai/gpt-test",
            transport=_StubTransport(proxy_base_url="http://test"),
            budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=trace,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        parent_span_id=turn_root,
    )
    info = AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=None,
    )
    await model.function([ModelRequest(parts=[UserPromptPart(content="hi")])], info)
    provider_events = [e for e in trace.events if e.kind.startswith("provider.")]
    assert provider_events
    started = next(e for e in provider_events if e.status == "started")
    assert started.parent_span_id == turn_root
    assert started.attrs.get("model_id") == "openai/gpt-test"
    assert started.attrs.get("budget_regime") == BudgetRegime.PER_TOKEN.value
