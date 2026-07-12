"""DEBUG log enrichment for ``TracingToolExecutor`` (`specs/11-tools-registry.md` §10.10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="tool-dispatch-log",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
        executor_tier="B",
    )


async def _dispatch_with_debug_capture(
    ctx: ToolContext,
    call: ToolCall,
) -> tuple[str, list[str]]:
    from loguru import logger as loguru_logger

    exe, _ = build_session_registry(registry_version=1)
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        raw = await exe.dispatch(ctx, call)
    finally:
        loguru_logger.remove(sink_id)
    return raw, captured


@pytest.mark.asyncio
async def test_tool_call_start_logs_arg_values(ctx: ToolContext) -> None:
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    _, lines = await _dispatch_with_debug_capture(ctx, call)
    start_lines = [line for line in lines if "tool_call.start" in line]
    assert start_lines, lines
    assert "arg_values=" in start_lines[0]
    assert '"name":"read"' in start_lines[0]


@pytest.mark.asyncio
async def test_tool_call_finish_logs_full_result_by_default(ctx: ToolContext) -> None:
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    raw, lines = await _dispatch_with_debug_capture(ctx, call)
    finish_lines = [line for line in lines if "tool_call.finish" in line]
    assert finish_lines, lines
    assert "result=" in finish_lines[0]
    compact = json.dumps(json.loads(raw), separators=(",", ":"), ensure_ascii=False)
    assert compact in finish_lines[0]


@pytest.mark.asyncio
async def test_tool_call_finish_logs_span_id_and_turn_id(ctx: ToolContext) -> None:
    """tool_call.finish must carry span_id and turn_id for log correlation (Wave 7.1)."""
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    _, lines = await _dispatch_with_debug_capture(ctx, call)
    finish_lines = [line for line in lines if "tool_call.finish" in line]
    assert finish_lines, lines
    assert "span_id=" in finish_lines[0], finish_lines[0]
    assert "turn_id=" in finish_lines[0], finish_lines[0]


@pytest.mark.asyncio
async def test_tool_call_finish_span_id_matches_start(ctx: ToolContext) -> None:
    """The span_id on tool_call.finish must match the span_id on tool_call.start (Wave 7.1)."""
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    _, lines = await _dispatch_with_debug_capture(ctx, call)

    def _extract(line: str, key: str) -> str:
        # Parse key=<value> where value ends at whitespace or end-of-string
        import re as _re

        m = _re.search(rf"{_re.escape(key)}=(\S+)", line)
        return m.group(1) if m else ""

    start_lines = [ln for ln in lines if "tool_call.start" in ln]
    finish_lines = [ln for ln in lines if "tool_call.finish" in ln]
    assert start_lines, lines
    assert finish_lines, lines
    start_span = _extract(start_lines[0], "span_id")
    finish_span = _extract(finish_lines[0], "span_id")
    assert start_span, start_lines[0]
    assert finish_span, finish_lines[0]
    assert start_span == finish_span, (
        f"span_id mismatch: start={start_span!r} finish={finish_span!r}"
    )


@pytest.mark.asyncio
async def test_tool_call_finish_truncates_result_when_configured(ctx: ToolContext) -> None:
    ctx.tool_debug_result_max_chars = 50
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    _, lines = await _dispatch_with_debug_capture(ctx, call)
    finish_lines = [line for line in lines if "tool_call.finish" in line]
    assert finish_lines
    assert "result=" in finish_lines[0]
    # After Wave 7.1 span_id and turn_id are appended after the result, so the
    # truncation marker "..." appears inside the line rather than at the end.
    assert "..." in finish_lines[0]


@pytest.mark.asyncio
async def test_tool_call_start_redacts_sensitive_arg_values(ctx: ToolContext) -> None:
    call = ToolCall(
        name="load_tool",
        arguments={"name": "read", "api_key": "sk-abcdefghijklmnopqrstuvwxyz123456"},
    )
    _, lines = await _dispatch_with_debug_capture(ctx, call)
    start_lines = [line for line in lines if "tool_call.start" in line]
    assert start_lines
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in start_lines[0]
    assert "<redacted>" in start_lines[0]


@pytest.mark.asyncio
async def test_tool_call_cached_logs_arg_values_and_result(ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    await exe.dispatch(ctx, call)

    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        await exe.dispatch(ctx, call)
    finally:
        loguru_logger.remove(sink_id)

    cached_lines = [line for line in captured if "tool_call.cached" in line]
    assert cached_lines
    assert "arg_values=" in cached_lines[0]
    assert "result=" in cached_lines[0]
