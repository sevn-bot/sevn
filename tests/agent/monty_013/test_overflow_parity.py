"""W1.4 — harness OverflowingToolOutput parity with sevn shim (D7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.agent.adapters.tier_b_overflow import (
    OVERFLOW_SPILL_THRESHOLD,
    build_overflow_capability,
)
from sevn.agent.adapters.tier_b_overflow import (
    OverflowingToolOutput as SevnOverflowingToolOutput,
)


def _harness_overflow_cls() -> type[Any] | None:
    try:
        from pydantic_ai_harness.overflowing_tool_output import OverflowingToolOutput
    except ImportError:
        return None
    return OverflowingToolOutput


def _mock_ctx() -> MagicMock:
    return MagicMock()


def _mock_call() -> MagicMock:
    call = MagicMock()
    call.tool_name = "glob"
    call.tool_call_id = "call_parity"
    return call


def _mock_tool_def() -> MagicMock:
    return MagicMock()


@pytest.mark.xfail(reason="green after W4: harness overflow import + wiring", strict=False)
def test_build_overflow_capability_uses_harness_module() -> None:
    cap = build_overflow_capability()
    assert cap.__class__.__module__.startswith("pydantic_ai_harness")


@pytest.mark.xfail(reason="green after W4: full inline content parity (D7)", strict=False)
@pytest.mark.anyio
async def test_harness_overflow_returns_full_content_below_threshold(
    tmp_path: Path,
) -> None:
    harness_cls = _harness_overflow_cls()
    assert harness_cls is not None, "harness OverflowingToolOutput not on installed wheel"

    sevn_cap = SevnOverflowingToolOutput(
        truncate_floor=20,
        spill_threshold=100,
        spill_dir=tmp_path / "sevn",
    )
    harness_cap = harness_cls(
        bands=[{"max_tokens": 100, "action": "inline"}],
        spill_dir=tmp_path / "harness",
    )

    content = "x" * 50
    ctx, call, tool_def = _mock_ctx(), _mock_call(), _mock_tool_def()

    sevn_result = await sevn_cap.after_tool_execute(
        ctx, call=call, tool_def=tool_def, args={}, result=content
    )
    harness_result = await harness_cap.after_tool_execute(
        ctx, call=call, tool_def=tool_def, args={}, result=content
    )

    assert sevn_result == content
    assert harness_result == content
    assert "truncated" not in str(harness_result).lower()


@pytest.mark.xfail(reason="green after W4: oversize spill + read_tool_result pager", strict=False)
@pytest.mark.anyio
async def test_harness_overflow_spills_pathological_result(tmp_path: Path) -> None:
    harness_cls = _harness_overflow_cls()
    assert harness_cls is not None

    harness_cap = harness_cls(
        bands=[{"max_tokens": 50, "action": "spill"}],
        spill_dir=tmp_path / "spills",
    )
    content = "y" * (OVERFLOW_SPILL_THRESHOLD + 500)
    ctx, call, tool_def = _mock_ctx(), _mock_call(), _mock_tool_def()

    result = await harness_cap.after_tool_execute(
        ctx, call=call, tool_def=tool_def, args={}, result=content
    )
    assert isinstance(result, str)
    assert "read_tool_result" in result
    toolset = harness_cap.get_tools()
    assert any(getattr(t, "name", "") == "read_tool_result" for t in toolset.tools)
