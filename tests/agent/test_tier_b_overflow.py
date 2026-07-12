"""Tests for tier-B overflow capability (Wave W5 — provider-neutral)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.agent.adapters.tier_b_overflow import (
    OVERFLOW_SPILL_THRESHOLD,
    OVERFLOW_TRUNCATE_FLOOR,
    OverflowingToolOutput,
    build_overflow_capability,
)


@pytest.fixture
def spill_dir(tmp_path: Path) -> Path:
    """Provide a temp directory for spill files."""
    return tmp_path / "spills"


@pytest.fixture
def cap(spill_dir: Path) -> OverflowingToolOutput[Any]:
    """Capability with low thresholds for testing."""
    return OverflowingToolOutput(
        truncate_floor=20,
        spill_threshold=100,
        spill_dir=spill_dir,
    )


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Minimal RunContext mock."""
    return MagicMock()


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
    """Results below truncate_floor pass unchanged."""

    @pytest.mark.anyio
    async def test_small_string_passthrough(
        self,
        cap: OverflowingToolOutput[Any],
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
        cap: OverflowingToolOutput[Any],
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
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        content = "x" * 50  # > old truncate_floor, < spill_threshold
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        assert result == content  # full content; LLM never faces a truncation notice
        assert "truncated" not in str(result)
        assert "read_tool_result" not in str(result)

    @pytest.mark.anyio
    async def test_tool_return_unwrapped_in_full(
        self,
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        """A CodeMode ToolReturn is unwrapped to its return_value, not the wrapper repr."""
        from pydantic_ai.messages import ToolReturn

        payload = '{"ok":true,"data":{"v":' + "9" * 40 + "}}"
        result = await cap.after_tool_execute(
            mock_ctx,
            call=mock_call,
            tool_def=mock_tool_def,
            args={},
            result=ToolReturn(return_value=payload, metadata={"code_mode": True}),
        )
        assert result == payload  # clean content, no "ToolReturn(return_value=" repr
        assert "ToolReturn(" not in str(result)


class TestSpill:
    """Results above spill_threshold are spilled to disk."""

    @pytest.mark.anyio
    async def test_large_result_spilled(
        self,
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
        spill_dir: Path,
    ) -> None:
        content = "y" * 200
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        assert isinstance(result, str)
        assert "spilled to disk" in result.lower() or "spill" in result.lower()
        assert "read_tool_result" in result
        assert "spill_0" in result
        # Verify file exists on disk
        assert (spill_dir / "spill_0.txt").exists()

    @pytest.mark.anyio
    async def test_spill_content_retrievable(
        self,
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        content = "z" * 200
        await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        slice_result = cap.read_spill("spill_0", offset=0, limit=50)
        assert "z" * 50 in slice_result

    @pytest.mark.anyio
    async def test_spill_offset_and_limit(
        self,
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        content = "0123456789" * 30  # 300 bytes
        await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        slice_result = cap.read_spill("spill_0", offset=10, limit=10)
        assert "0123456789" in slice_result

    @pytest.mark.anyio
    async def test_dict_result_spilled(
        self,
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        data = {"content": "a" * 200}
        result = await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=data
        )
        assert "read_tool_result" in result


class TestReadToolResult:
    """The read_tool_result tool retrieves spilled content."""

    def test_toolset_registered(self) -> None:
        cap: OverflowingToolOutput[Any] = OverflowingToolOutput()
        ts = cap.get_toolset()
        assert ts is not None

    @pytest.mark.anyio
    async def test_read_unknown_spill_id(self, cap: OverflowingToolOutput[Any]) -> None:
        result = cap.read_spill("nonexistent")
        assert "error" in result.lower()
        assert "unknown" in result.lower()

    @pytest.mark.anyio
    async def test_read_spill_function(
        self,
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
    ) -> None:
        content = "payload_data" * 20  # > 100 threshold
        await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        result = cap.read_spill("spill_0", offset=0, limit=50)
        assert "payload_data" in result


class TestSelfSkip:
    """read_tool_result calls are not themselves overflowed."""

    @pytest.mark.anyio
    async def test_read_tool_result_bypassed(
        self,
        cap: OverflowingToolOutput[Any],
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
        assert isinstance(cap, OverflowingToolOutput)
        assert cap.truncate_floor == OVERFLOW_TRUNCATE_FLOOR
        assert cap.spill_threshold == OVERFLOW_SPILL_THRESHOLD

    def test_custom_thresholds(self) -> None:
        cap = build_overflow_capability(truncate_floor=1024, spill_threshold=8192)
        assert isinstance(cap, OverflowingToolOutput)
        assert cap.truncate_floor == 1024
        assert cap.spill_threshold == 8192


class TestCleanup:
    """Cleanup removes spill files."""

    @pytest.mark.anyio
    async def test_cleanup_removes_files(
        self,
        cap: OverflowingToolOutput[Any],
        mock_ctx: MagicMock,
        mock_call: MagicMock,
        mock_tool_def: MagicMock,
        spill_dir: Path,
    ) -> None:
        content = "q" * 200
        await cap.after_tool_execute(
            mock_ctx, call=mock_call, tool_def=mock_tool_def, args={}, result=content
        )
        assert (spill_dir / "spill_0.txt").exists()
        cap.cleanup()
        assert not (spill_dir / "spill_0.txt").exists()
        assert len(cap._spills) == 0


class TestBuildTierBCapabilities:
    """build_tier_b_capabilities includes overflow."""

    def test_overflow_included_by_default(self) -> None:
        from pydantic_ai.capabilities.hooks import Hooks

        from sevn.agent.executors.b_harness import build_tier_b_capabilities

        caps = build_tier_b_capabilities(hooks=Hooks())
        cap_names = [c.__class__.__name__ for c in caps]
        assert "OverflowingToolOutput" in cap_names

    def test_overflow_disabled(self) -> None:
        from pydantic_ai.capabilities.hooks import Hooks

        from sevn.agent.executors.b_harness import build_tier_b_capabilities

        caps = build_tier_b_capabilities(hooks=Hooks(), overflow_on=False)
        cap_names = [c.__class__.__name__ for c in caps]
        assert "OverflowingToolOutput" not in cap_names
