"""Tier-B streaming observability (`plan/gateway-operator-recovery-wave-plan.md` W5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai._agent_graph import ModelRequestNode

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import AnthropicMessagesTransport
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
async def test_streaming_skipped_logs_no_sink_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``streaming_sink=None`` emits one ``streaming_skipped reason=no_sink`` log."""
    info_records: list[str] = []

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr(
        "sevn.agent.executors.b_harness.logger.info",
        _capture_info,
    )

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
        streaming_sink=None,
    )

    skipped = [m for m in info_records if "streaming_skipped" in m]
    assert len(skipped) == 1
    assert "reason=no_sink" in skipped[0]
    assert "model_id=openai/gpt-test" in skipped[0]
    assert "transport=chat_completions" in skipped[0]


@pytest.mark.asyncio
async def test_streaming_unavailable_logs_transport_reason_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``node.stream`` raises, one ``streaming_unavailable`` log carries the reason."""
    info_records: list[str] = []

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr(
        "sevn.agent.executors.b_harness.logger.info",
        _capture_info,
    )

    def _failing_stream(self, ctx: Any) -> Any:  # type: ignore[no-untyped-def]
        raise RuntimeError("transport refused stream")

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
    assert "transport refused stream" in unavailable[0]
    assert "model_id=openai/gpt-test" in unavailable[0]
    assert "transport=chat_completions" in unavailable[0]


@pytest.mark.asyncio
async def test_tier_b_stream_function_invokes_sink(
    tmp_path: Path,
) -> None:
    """``build_tier_b_function_model`` stream path forwards accumulated text to the sink."""
    exe, tool_set = _make_tick_executor()
    triage = _base_triage(tools=[])
    captured: list[str] = []

    async def _once(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Hello streaming world.")

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

    async def _sink(text: str) -> None:
        captured.append(text)

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
        streaming_debounce_s=0.0,
    )

    assert captured
    assert captured[-1] == "Hello streaming world."


def _anthropic_assistant_text(text: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


class _ScriptedAnthropicTransport(AnthropicMessagesTransport):
    """``AnthropicMessagesTransport`` whose ``complete`` never hits the proxy.

    ``complete_stream`` replays the scripted ``complete`` payload as genuine text
    deltas + ``StreamFinal`` so streaming stays hermetic (matches the real SSE
    reconstruction surface).
    """

    def __init__(self, fn: Any) -> None:
        super().__init__(proxy_base_url="http://tier-b-harness.test.invalid")
        self._fn = fn
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        body = dict(request)
        self.requests.append(body)
        return await self._fn(body)

    async def complete_stream(self, request: dict[str, object]) -> Any:
        from sevn.agent.providers.transport import StreamFinal, StreamTextDelta

        payload = await self.complete(request)
        for block in payload.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                for ch in str(block.get("text", "")):
                    yield StreamTextDelta(text=ch)
        yield StreamFinal(response=payload)


@pytest.mark.asyncio
async def test_streaming_disabled_for_unsupported_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sink + a transport opting out of streaming logs one ``streaming_disabled`` line.

    A wire with ``supports_streaming=False`` (e.g. Bedrock, or a future batch-only
    transport) must make the harness skip the ``node.stream`` tap entirely (no
    per-turn ``streaming_unavailable`` error), emit a single
    ``streaming_disabled reason=transport_unsupported`` line, never call the sink,
    and still finalize the turn. Anthropic/MiniMax now streams for real, so this
    forces the gate off on the instance to exercise the skip path.
    """
    info_records: list[str] = []

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr(
        "sevn.agent.executors.b_harness.logger.info",
        _capture_info,
    )

    def _boom_stream(self, ctx: Any) -> Any:  # type: ignore[no-untyped-def]
        raise AssertionError("node.stream must not be attempted for a gated transport")

    monkeypatch.setattr(ModelRequestNode, "stream", _boom_stream)

    exe, tool_set = _make_tick_executor()
    triage = _base_triage(tools=[])
    captured: list[str] = []

    async def _once(_req: dict[str, Any]) -> dict[str, Any]:
        return _anthropic_assistant_text("done.")

    transport = _ScriptedAnthropicTransport(_once)
    # Anthropic/MiniMax now streams for real; force the per-transport gate off to
    # exercise the harness skip path that batch-only wires (e.g. Bedrock) rely on.
    transport.supports_streaming = False
    assert transport.supports_streaming is False
    bundle = ResolvedTierBModel(
        model_id="minimax/MiniMax-M3",
        transport=transport,
        budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
    )
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp_path),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )

    async def _sink(text: str) -> None:
        captured.append(text)

    outcome = await run_b_turn(
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

    disabled = [m for m in info_records if "streaming_disabled" in m]
    assert len(disabled) == 1
    assert "reason=transport_unsupported" in disabled[0]
    assert "model_id=minimax/MiniMax-M3" in disabled[0]
    assert "transport=anthropic" in disabled[0]
    # No fallback ``no_sink`` / ``unavailable`` noise, sink never tapped, turn done.
    assert not [m for m in info_records if "streaming_skipped" in m]
    assert not [m for m in info_records if "streaming_unavailable" in m]
    assert captured == []
    assert outcome.status == "completed"
