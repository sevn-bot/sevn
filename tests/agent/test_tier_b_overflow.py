"""Tests for tier-B overflow capability (harness ToolOutputLimits via factory)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import ToolReturn
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

from sevn.agent.adapters.tier_b_tool_output_limits import (
    OVERFLOW_SPILL_THRESHOLD,
    OVERFLOW_TRUNCATE_FLOOR,
    build_overflow_capability,
)


def _result_text(result: object) -> str:
    if isinstance(result, ToolReturn):
        return str(result.return_value)
    return str(result)


@pytest.fixture
def spill_dir(tmp_path: Path) -> Path:
    """Provide a temp directory for spill files."""
    return tmp_path / "spills"


@pytest.fixture
def cap(spill_dir: Path) -> ToolOutputLimits[Any]:
    """Capability with low thresholds for testing."""
    return build_overflow_capability(
        truncate_floor=20,
        spill_threshold=100,
        spill_dir=spill_dir,
    )


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Minimal RunContext mock."""
    ctx = MagicMock()
    ctx.run_id = "run_test"
    ctx.retry = 0
    return ctx


@pytest.fixture
def mock_call() -> MagicMock:
    """Minimal ToolCallPart mock."""
    call = MagicMock()
    call.tool_name = "glob"
    call.tool_call_id = "call_123"
    return call


@pytest.fixture
def mock_tool_def() -> MagicMock:
    """Minimal ToolDefinition mock."""
    return MagicMock()


class TestPassthrough:
    """Results below spill_threshold pass unchanged."""

    @pytest.mark.anyio
    async def test_small_string_passthrough(
        self,
        cap: ToolOutputLimits[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result="short"
        )
        assert result == "short"

    @pytest.mark.anyio
    async def test_small_dict_passthrough(
        self,
        cap: ToolOutputLimits[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        data = {"ok": True, "v": 1}
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=data
        )
        assert result == data


class TestFullInline:
    """Results up to spill_threshold are returned in full (no truncation, no spill pointer)."""

    @pytest.mark.anyio
    async def test_mid_size_returned_in_full(
        self,
        cap: ToolOutputLimits[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        content = "x" * 50
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        assert result == content
        assert "truncated" not in _result_text(result)
        assert "read_tool_result" not in _result_text(result)

    @pytest.mark.anyio
    async def test_tool_return_unwrapped_in_full(
        self,
        cap: ToolOutputLimits[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        """A CodeMode ToolReturn keeps its envelope when below the spill band."""
        payload = '{"ok":true,"data":{"v":' + "9" * 40 + "}}"
        wrapped = ToolReturn(return_value=payload, metadata={"code_mode": True})
        result = await cap.after_tool_execute(
            mock_ctx,
            call=mock_call,
            tool_def=mock_tool_def,
            args={},
            result=wrapped,
        )
        assert isinstance(result, ToolReturn)
        assert result.return_value == payload
        assert "ToolReturn(" not in _result_text(result)


class TestSpill:
    """Results above spill_threshold are spilled to disk."""

    @pytest.mark.anyio
    async def test_large_result_spilled(
        self,
        cap: ToolOutputLimits[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
        spill_dir: Path,
    ) -> None:
        content = "y" * 200
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        text = _result_text(result)
        assert "read_tool_result" in text
        assert "stored to handle" in text.lower() or "too large" in text.lower()
        assert any(spill_dir.rglob("*"))

    @pytest.mark.anyio
    async def test_dict_result_spilled(
        self,
        cap: ToolOutputLimits[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        data = {"content": "a" * 200}
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=data
        )
        assert "read_tool_result" in _result_text(result)


class TestReadToolResult:
    """The read_tool_result tool is registered for spilled payloads."""

    def test_toolset_registered(self) -> None:
        cap = build_overflow_capability()
        ts = cap.get_toolset()
        assert ts is not None
        assert "read_tool_result" in ts.tools


class TestSelfSkip:
    """read_tool_result calls are not themselves overflowed."""

    @pytest.mark.anyio
    async def test_read_tool_result_bypassed(
        self,
        cap: ToolOutputLimits[Any],
        mock_ctx: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        call = MagicMock()
        call.tool_name = "read_tool_result"
        call.tool_call_id = "c2"
        big_result = "w" * 500
        result = await cap.after_tool_execute(
            mock_ctx, call=call, tool_def=mock_tool_def, args={}, result=big_result
        )
        assert result == big_result


class TestBuildHelper:
    """build_overflow_capability factory."""

    def test_default_thresholds(self) -> None:
        cap = build_overflow_capability()
        assert isinstance(cap, ToolOutputLimits)
        assert cap.bands[0].over == OVERFLOW_SPILL_THRESHOLD

    def test_custom_thresholds(self) -> None:
        cap = build_overflow_capability(truncate_floor=1024, spill_threshold=8192)
        assert isinstance(cap, ToolOutputLimits)
        assert cap.bands[0].over == 8192
        _ = OVERFLOW_TRUNCATE_FLOOR  # retained in API; factory accepts the kwarg


class TestBuildTierBCapabilities:
    """build_tier_b_capabilities includes overflow."""

    def test_overflow_included_by_default(self) -> None:
        from pydantic_ai.capabilities.hooks import Hooks

        from sevn.agent.executors.b_harness import build_tier_b_capabilities

        caps = build_tier_b_capabilities(hooks=Hooks())
        cap_names = [c.__class__.__name__ for c in caps]
        assert "ToolOutputLimits" in cap_names

    def test_overflow_disabled(self) -> None:
        from pydantic_ai.capabilities.hooks import Hooks

        from sevn.agent.executors.b_harness import build_tier_b_capabilities

        caps = build_tier_b_capabilities(hooks=Hooks(), overflow_on=False)
        cap_names = [c.__class__.__name__ for c in caps]
        assert "ToolOutputLimits" not in cap_names
