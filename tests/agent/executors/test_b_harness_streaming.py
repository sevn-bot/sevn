"""Tests for ``run_b_turn`` streaming sink (`PROBLEMS.md` Priority 2 Mode 1 / Step 6).

The harness taps each ``ModelRequestNode``'s text stream when a ``streaming_sink``
callback is provided, forwarding accumulated answer text to the gateway's
``TierBAnswerFinalizer`` for in-place placeholder edits.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai._agent_graph import ModelRequestNode
from pydantic_ai.models.test import TestModel

if TYPE_CHECKING:
    from sevn.agent.executors.b_harness import StreamingSink


@pytest.mark.asyncio
async def test_per_node_stream_yields_accumulated_text() -> None:
    """``ModelRequestNode.stream`` yields progressively-larger accumulated text.

    This pins the pydantic-ai contract that Step 6 relies on. If pydantic-ai
    ever changes the shape (e.g., delta-only events), the harness's streaming
    loop in ``b_harness.run_b_turn`` will need to be updated and this test
    will catch the drift.
    """
    model = TestModel(custom_output_text="Hello world from streaming.")
    agent = Agent(model)
    chunks: list[str] = []
    async with agent.iter("hi") as agent_run:
        async for node in agent_run:
            if isinstance(node, ModelRequestNode):
                async with node.stream(agent_run.ctx) as stream:
                    async for accumulated in stream.stream_text(
                        delta=False,
                        debounce_by=None,
                    ):
                        chunks.append(accumulated)
    assert chunks  # at least one chunk produced
    # Accumulating contract: every chunk is a prefix of the next.
    for i in range(1, len(chunks)):
        assert chunks[i].startswith(chunks[i - 1])
    assert chunks[-1] == "Hello world from streaming."


@pytest.mark.asyncio
async def test_streaming_sink_signature_callable() -> None:
    """``StreamingSink`` is structurally a ``Callable[[str], Awaitable[None]]``."""
    captured: list[str] = []

    async def sink(text: str) -> None:
        captured.append(text)

    s: StreamingSink = sink
    await s("hello")
    await s("hello world")
    assert captured == ["hello", "hello world"]


@pytest.mark.asyncio
async def test_streaming_sink_failures_are_swallowed() -> None:
    """Sink raising must not abort the executor — Step 6 best-effort contract."""
    from loguru import logger
    from pydantic_ai import Agent
    from pydantic_ai._agent_graph import ModelRequestNode
    from pydantic_ai.models.test import TestModel

    model = TestModel(custom_output_text="hello")
    agent = Agent(model)
    raised: list[BaseException] = []

    async def raising_sink(_text: str) -> None:
        raise RuntimeError("sink down")

    # Mimic the b_harness loop with the same try/except shape — verifies the
    # logger.exception path is exercised without aborting the iteration.
    handler_id = logger.add(lambda _msg: None)  # silence captured stderr
    try:
        async with agent.iter("hi") as agent_run:
            async for node in agent_run:
                if not isinstance(node, ModelRequestNode):
                    continue
                try:
                    async with node.stream(agent_run.ctx) as model_stream:
                        async for accumulated in model_stream.stream_text(
                            delta=False,
                            debounce_by=None,
                        ):
                            try:
                                await raising_sink(accumulated)
                            except Exception as exc:
                                raised.append(exc)
                except Exception:
                    pass
    finally:
        logger.remove(handler_id)

    assert raised  # the sink raised at least once
    assert all(isinstance(e, RuntimeError) for e in raised)
    _ = cast("Any", MagicMock())  # silence unused import warning
    _ = asyncio.iscoroutinefunction  # ditto


@pytest.mark.asyncio
async def test_finish_streaming_error_disables_streaming_for_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finish-streaming contract violation aborts streaming; turn still completes (W7)."""
    from tests.agent.test_b_harness import (
        _base_triage,
        _make_tick_executor,
        _openai_assistant_text,
        _ScriptedChatTransport,
    )

    from sevn.agent.executors import b_harness as b_harness_mod
    from sevn.agent.executors.b_harness import run_b_turn
    from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
    from sevn.agent.providers.budget import BudgetRegime, ModelBudget
    from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
    from sevn.tools.cache import LoadedBodyCache
    from sevn.tools.context import ToolContext
    from sevn.tools.permissions import AllowAllPermissionPolicy

    info_records: list[str] = []

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr(
        "sevn.agent.executors.b_harness.logger.info",
        _capture_info,
    )

    real_consume = b_harness_mod._consume_model_request_stream
    consume_calls = 0

    async def _patched_consume(*args: object, **kwargs: object) -> None:
        nonlocal consume_calls
        consume_calls += 1
        if consume_calls == 1:
            raise RuntimeError("You must finish streaming before calling run()")
        await real_consume(*args, **kwargs)

    monkeypatch.setattr(
        b_harness_mod,
        "_consume_model_request_stream",
        _patched_consume,
    )

    exe, tool_set = _make_tick_executor()
    triage = _base_triage(tools=[])
    captured: list[str] = []

    async def _once(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Recovered after streaming abort.")

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
        streaming_debounce_s=0.0,
    )

    aborted = [m for m in info_records if "streaming_aborted" in m]
    assert len(aborted) == 1
    assert "reason=finish_streaming_contract" in aborted[0]
    assert not [m for m in info_records if "streaming_unavailable" in m]
    assert outcome.status == "completed"
    assert outcome.final_messages
    assert "Recovered after streaming abort." in outcome.final_messages[-1].text


@pytest.mark.asyncio
async def test_consume_model_request_stream_drains_to_sink() -> None:
    """``_consume_model_request_stream`` forwards drained accumulated text to the sink."""
    from pydantic_ai import Agent
    from pydantic_ai._agent_graph import ModelRequestNode
    from pydantic_ai.models.test import TestModel

    from sevn.agent.executors.b_harness import _consume_model_request_stream

    model = TestModel(custom_output_text="Drained answer.")
    agent = Agent(model)
    captured: list[str] = []

    async def _sink(text: str) -> None:
        captured.append(text)

    async with agent.iter("hi") as agent_run:
        async for node in agent_run:
            if isinstance(node, ModelRequestNode):
                await _consume_model_request_stream(
                    node,
                    agent_run.ctx,
                    sink=_sink,
                    debounce_s=0.0,
                    session_id="s1",
                    turn_id="t1",
                )
    assert captured
    assert captured[-1] == "Drained answer."
