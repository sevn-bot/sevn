"""W1.4 — harness ToolOutputLimits parity with prior sevn overflow shim (D7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import ToolReturn
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

from sevn.agent.adapters.tier_b_tool_output_limits import (
    OVERFLOW_SPILL_THRESHOLD,
    build_overflow_capability,
)


def _mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.run_id = "run_parity"
    ctx.retry = 0
    return ctx


def _mock_call() -> MagicMock:
    call = MagicMock()
    call.tool_name = "glob"
    call.tool_call_id = "call_parity"
    return call


def _mock_tool_def() -> MagicMock:
    return MagicMock()


def _result_text(result: object) -> str:
    if isinstance(result, ToolReturn):
        return str(result.return_value)
    return str(result)


def test_build_overflow_capability_uses_harness_module() -> None:
    cap = build_overflow_capability()
    assert cap.__class__.__module__.startswith("pydantic_ai_harness")
    assert isinstance(cap, ToolOutputLimits)


@pytest.mark.anyio
async def test_harness_overflow_returns_full_content_below_threshold(
    tmp_path: Path,
) -> None:
    cap = build_overflow_capability(
        truncate_floor=20,
        spill_threshold=100,
        spill_dir=tmp_path / "inline",
    )

    content = "x" * 50
    ctx, call, tool_def = _mock_ctx(), _mock_call(), _mock_tool_def()

    result = await cap.after_tool_execute(
        ctx, call=call, tool_def=tool_def, args={}, result=content
    )

    assert result == content
    assert "truncated" not in _result_text(result).lower()
    assert "read_tool_result" not in _result_text(result)


@pytest.mark.anyio
async def test_harness_overflow_spills_pathological_result(tmp_path: Path) -> None:
    cap = build_overflow_capability(
        spill_threshold=OVERFLOW_SPILL_THRESHOLD,
        spill_dir=tmp_path / "spills",
    )
    content = "y" * (OVERFLOW_SPILL_THRESHOLD + 500)
    ctx, call, tool_def = _mock_ctx(), _mock_call(), _mock_tool_def()

    result = await cap.after_tool_execute(
        ctx, call=call, tool_def=tool_def, args={}, result=content
    )
    text = _result_text(result)
    assert "read_tool_result" in text
    toolset = cap.get_toolset()
    assert toolset is not None
    assert "read_tool_result" in toolset.tools
