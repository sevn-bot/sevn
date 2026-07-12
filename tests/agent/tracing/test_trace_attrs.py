"""Tests for trace attrs normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.agent.tracing.attrs import (
    json_safe_trace_attrs,
    trace_tool_result_value,
)
from sevn.agent.tracing.sink import NullTraceSink, checkpoint_snapshot
from sevn.tools.base import ToolCall, ToolContext, ToolExecutor


class _RecordingTrace(NullTraceSink):
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_checkpoint_snapshot_persists_state_dict() -> None:
    rec = _RecordingTrace()
    await checkpoint_snapshot(
        rec,
        session_id="s",
        turn_id="t",
        tier="B",
        kind="tool.before",
        state={"name": "read", "arguments": {"path": "x"}},
    )
    assert len(rec.events) == 1
    event = rec.events[0]
    assert event.kind == "snapshot.checkpoint"
    assert event.attrs["state"]["name"] == "read"
    assert event.attrs["state"]["arguments"] == {"path": "x"}


def test_trace_tool_result_value_parses_json_envelope() -> None:
    assert trace_tool_result_value('{"ok": true}') == {"ok": True}
    assert trace_tool_result_value("plain") == "plain"


def test_json_safe_trace_attrs_coerces_path() -> None:
    assert json_safe_trace_attrs({"p": Path("/tmp/x")}) == {"p": "/tmp/x"}


@pytest.mark.asyncio
async def test_tool_dispatch_trace_includes_arguments_and_result(tmp_path: Path) -> None:
    from sevn.tools.base import FunctionTool, ToolDefinition, enveloped_success

    rec = _RecordingTrace()
    executor = ToolExecutor(default_timeout_seconds=5.0)

    async def _tick(_ctx: ToolContext) -> str:
        return enveloped_success({"tick": True})

    executor.register(
        FunctionTool(
            ToolDefinition(
                name="tick",
                category="meta",
                description="test tick",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            _tick,
        ),
    )
    ctx = ToolContext(
        session_id="s1",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
        trace=rec,
        turn_id="t1",
    )
    await executor.dispatch(ctx, ToolCall(name="tick", arguments={}))
    kinds = {getattr(e, "kind", None): e for e in rec.events}
    invoke = kinds["tool.invoke"]
    complete = kinds["tool.complete"]
    assert invoke.attrs["arguments"] == {}
    assert complete.attrs["result"]["ok"] is True
