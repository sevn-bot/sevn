"""Within-turn ``read`` dedupe + bounded tool-result logging (`specs/11-tools-registry.md` §10.11-10.12).

Covers P2 from ``plan/minimax-m3-session-bugs-plan.md``: repeated identical reads
short-circuit to a compact notice (token blowup) and a large tool result is
elided in the structured DEBUG log line while still returned in full to the caller
(``gateway.log`` megabyte blowup).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config.defaults import TOOL_DEBUG_RESULT_LOG_HARD_CAP
from sevn.tools.base import (
    FunctionTool,
    ToolCall,
    ToolDefinition,
    enveloped_success,
)
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import (
    TracingToolExecutor,
    _tool_debug_result,
    build_session_registry,
)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="read-dedupe",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
        executor_tier="B",
    )


@pytest.mark.asyncio
async def test_identical_read_short_circuits_second_time(ctx: ToolContext) -> None:
    """Two identical reads in one turn: full body once, then a compact notice."""
    target = ctx.workspace_path / "sample.py"
    body = "\n".join(f"line {i}" for i in range(1, 80))
    target.write_text(body, encoding="utf-8")

    exe, _ = build_session_registry(registry_version=1)
    call = ToolCall(name="read", arguments={"path": "sample.py"})

    first = await exe.dispatch(ctx, call)
    second = await exe.dispatch(ctx, call)

    first_blob = json.loads(first)
    second_blob = json.loads(second)

    # First read carries the real body and is not flagged as deduped.
    assert first_blob["ok"] is True
    assert "line 1" in first_blob["data"]["content"]
    assert first_blob["data"].get("deduped") is not True

    # Second read short-circuits to a compact pointer notice.
    assert second_blob["ok"] is True
    assert second_blob["data"]["deduped"] is True
    assert "already read above" in second_blob["data"]["content"]
    assert "line 1" not in second_blob["data"]["content"]
    assert len(second) < len(first)


@pytest.mark.asyncio
async def test_read_dedupe_keyed_on_offset_limit(ctx: ToolContext) -> None:
    """A different offset/limit is a different range — not deduped."""
    target = ctx.workspace_path / "sample.py"
    target.write_text("\n".join(f"line {i}" for i in range(1, 80)), encoding="utf-8")

    exe, _ = build_session_registry(registry_version=1)
    full = ToolCall(name="read", arguments={"path": "sample.py"})
    paged = ToolCall(name="read", arguments={"path": "sample.py", "offset": 10, "limit": 5})

    await exe.dispatch(ctx, full)
    paged_blob = json.loads(await exe.dispatch(ctx, paged))

    # Distinct range: full body returned, not the dedupe notice.
    assert paged_blob["data"].get("deduped") is not True
    assert "line 10" in paged_blob["data"]["content"]


def test_tool_debug_result_elides_large_payload_with_size_marker() -> None:
    """A megabyte-class result is bounded to the hard cap + size marker for logging."""
    raw = '{"ok":true,"data":{"content":"' + "x" * 1_000_000 + '"}}'
    rendered = _tool_debug_result(raw, max_chars=None)
    assert len(rendered) < len(raw)
    assert len(rendered) <= TOOL_DEBUG_RESULT_LOG_HARD_CAP + 64
    assert "chars]" in rendered


def test_tool_debug_result_keeps_small_payload_whole() -> None:
    raw = '{"ok":true,"data":{"content":"short"}}'
    assert _tool_debug_result(raw, max_chars=None) == raw


@pytest.mark.asyncio
async def test_large_inline_result_truncated_in_log_but_full_to_caller(
    ctx: ToolContext,
) -> None:
    """A large inline tool result is elided in the DEBUG log line yet returned in full.

    The payload carries ``spill_depth=1`` so the universal disk-spill path treats
    it as terminal and returns it inline — mirroring a production read of a large
    terminal spill artifact, the exact case the structured-log hard cap defends
    against (`specs/11-tools-registry.md` §10.12).
    """
    from loguru import logger as loguru_logger

    marker = "Z" * 500_000
    big_envelope = enveloped_success({"content": marker, "spill_depth": 1})

    async def _giant(ctx: ToolContext, **_kwargs: object) -> str:
        _ = ctx
        return big_envelope

    definition = ToolDefinition(
        name="giant_inline",
        category="test",
        description="returns a large inline payload",
        parameters={"type": "object", "properties": {}},
    )
    exe = TracingToolExecutor(default_timeout_seconds=None)
    exe.register(FunctionTool(definition, _giant))
    call = ToolCall(name="giant_inline", arguments={})

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        raw = await exe.dispatch(ctx, call)
    finally:
        loguru_logger.remove(sink_id)

    # Full body returned to the caller (the model), untouched by log bounding.
    assert raw == big_envelope
    assert json.loads(raw)["data"]["content"] == marker

    finish_lines = [line for line in captured if "tool_call.finish" in line]
    assert finish_lines, captured
    # The result rendered into the log is bounded + carries the size marker.
    assert "chars]" in finish_lines[0]
    # The full half-megabyte content never lands verbatim in the log line.
    assert marker not in finish_lines[0]
    assert len(finish_lines[0]) < len(raw)
