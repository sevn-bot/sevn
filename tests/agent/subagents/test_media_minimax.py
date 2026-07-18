"""Unit tests for MiniMax media adapter helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.subagents.media_minimax import (
    MiniMaxMediaError,
    _ensure_under_content_root,
    _normalize_file_id,
    _poll_video_file_id,
)


class TestNormalizeFileId:
    """``file_id`` accepted as int or str."""

    def test_int(self) -> None:
        assert _normalize_file_id(12345) == "12345"

    def test_str(self) -> None:
        assert _normalize_file_id("abc-1") == "abc-1"

    def test_none_raises(self) -> None:
        with pytest.raises(MiniMaxMediaError, match="missing file_id"):
            _normalize_file_id(None)

    def test_bool_raises(self) -> None:
        with pytest.raises(MiniMaxMediaError, match="missing file_id"):
            _normalize_file_id(True)

    def test_empty_str_raises(self) -> None:
        with pytest.raises(MiniMaxMediaError, match="missing file_id"):
            _normalize_file_id("  ")


class TestEnsureUnderContentRoot:
    """Path containment for local media refs."""

    def test_under_root(self, tmp_path: Path) -> None:
        target = tmp_path / "a.jpg"
        target.write_bytes(b"x")
        assert _ensure_under_content_root(target, tmp_path) == target.resolve()

    def test_escape_raises(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside.jpg"
        with pytest.raises(MiniMaxMediaError, match="escapes workspace"):
            _ensure_under_content_root(outside, tmp_path)


class TestPollVideoFileId:
    """Poll success / Fail / timeout."""

    @pytest.mark.asyncio
    async def test_success_with_int_file_id(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "status": "Success",
            "file_id": 999001,
            "base_resp": {"status_code": 0},
        }
        http = AsyncMock()
        http.get = AsyncMock(return_value=response)
        file_id = await _poll_video_file_id(
            http,
            "sk-test",
            "task-1",
            poll_interval_s=0.0,
            max_polls=3,
        )
        assert file_id == "999001"

    @pytest.mark.asyncio
    async def test_fail_status_raises(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "status": "Fail",
            "error_message": "bad prompt",
            "base_resp": {"status_code": 0},
        }
        http = AsyncMock()
        http.get = AsyncMock(return_value=response)
        with pytest.raises(MiniMaxMediaError, match="video_generation failed"):
            await _poll_video_file_id(
                http,
                "sk-test",
                "task-1",
                poll_interval_s=0.0,
                max_polls=3,
            )

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "status": "Processing",
            "base_resp": {"status_code": 0},
        }
        http = AsyncMock()
        http.get = AsyncMock(return_value=response)
        with pytest.raises(MiniMaxMediaError, match="timed out"):
            await _poll_video_file_id(
                http,
                "sk-test",
                "task-1",
                poll_interval_s=0.0,
                max_polls=2,
            )
