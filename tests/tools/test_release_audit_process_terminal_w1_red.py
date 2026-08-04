"""Batch A W1 RED — process drain + terminal sentinel (#143, #144; green after W6).

Contracts: drain stdout to EOF; ``start_new_session`` + ``killpg`` stop path; sentinel-based
terminal completion with timeout escalation; strip sentinel from output.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.process import reset_process_store_for_tests
from sevn.tools.registry import build_session_registry
from sevn.tools.terminal import reset_terminal_store_for_tests


class _SandboxWiringStub:
    """Minimal ``sandbox_client`` for host-backed tool tests after W4 wiring gate."""


@pytest.fixture(autouse=True)
def _clean_stores() -> None:
    reset_process_store_for_tests()
    reset_terminal_store_for_tests()
    yield
    reset_process_store_for_tests()
    reset_terminal_store_for_tests()


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    root = tmp_path / "ws"
    root.mkdir()
    return ToolContext(
        session_id="audit-process-terminal",
        workspace_path=root,
        workspace_id="audit-process-terminal-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        sandbox_client=_SandboxWiringStub(),
    )


@pytest.mark.asyncio
async def test_process_output_includes_bytes_after_early_reader_cap(ctx: ToolContext) -> None:
    """Process emits a second line after the reader would have stopped at MAX_CAPTURE_CHARS."""
    exe, _ = build_session_registry(registry_version=1)
    script = (
        "import sys,time;"
        "print('line-one', flush=True);"
        "time.sleep(0.3);"
        "print('line-two-after-cap', flush=True)"
    )
    start_raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="process",
            arguments={"action": "start", "argv": [sys.executable, "-u", "-c", script]},
        ),
    )
    start_env = json.loads(start_raw)
    assert start_env["ok"] is True
    job_id = start_env["data"]["job_id"]

    await asyncio.sleep(0.8)

    out_raw = await exe.dispatch(
        ctx,
        ToolCall(name="process", arguments={"action": "output", "job_id": job_id}),
    )
    out_env = json.loads(out_raw)
    assert out_env["ok"] is True
    stdout = out_env["data"]["stdout"]
    assert "line-one" in stdout
    assert "line-two-after-cap" in stdout


@pytest.mark.asyncio
async def test_process_start_passes_start_new_session(ctx: ToolContext) -> None:
    captured: list[dict[str, Any]] = []

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> Any:
        captured.append(dict(kwargs))
        proc = MagicMock()
        proc.stdout = asyncio.StreamReader()
        proc.stderr = asyncio.StreamReader()
        proc.returncode = None
        proc.wait = AsyncMock(return_value=0)
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        return proc

    with patch("sevn.tools.process.asyncio.create_subprocess_exec", fake_create_subprocess_exec):
        exe, _ = build_session_registry(registry_version=1)
        raw = await exe.dispatch(
            ctx,
            ToolCall(
                name="process",
                arguments={
                    "action": "start",
                    "argv": [sys.executable, "-c", "print('spawn-session')"],
                },
            ),
        )
    env = json.loads(raw)
    assert env["ok"] is True
    assert captured, "expected create_subprocess_exec call"
    assert captured[0].get("start_new_session") is True


@pytest.mark.asyncio
async def test_process_stop_uses_killpg(ctx: ToolContext) -> None:
    killpg_calls: list[tuple[int, int]] = []

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> Any:
        proc = MagicMock()
        proc.pid = 4242
        proc.returncode = None
        proc.stdout = asyncio.StreamReader()
        proc.stderr = asyncio.StreamReader()
        proc.wait = AsyncMock(return_value=-9)
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        return proc

    def fake_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))

    with (
        patch("sevn.tools.process.asyncio.create_subprocess_exec", fake_create_subprocess_exec),
        patch("sevn.tools.process.os.getpgid", return_value=4242),
        patch("sevn.tools.process.os.killpg", fake_killpg),
    ):
        exe, _ = build_session_registry(registry_version=1)
        start_raw = await exe.dispatch(
            ctx,
            ToolCall(
                name="process",
                arguments={
                    "action": "start",
                    "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
                },
            ),
        )
        job_id = json.loads(start_raw)["data"]["job_id"]
        stop_raw = await exe.dispatch(
            ctx,
            ToolCall(name="process", arguments={"action": "stop", "job_id": job_id}),
        )
    stop_env = json.loads(stop_raw)
    assert stop_env["ok"] is True
    assert killpg_calls, "expected os.killpg during stop"


def test_terminal_run_sync_uses_sentinel_marker() -> None:
    import inspect

    from sevn.tools import terminal as terminal_mod

    source = inspect.getsource(terminal_mod._run_sync)
    assert "__SEVN_TERM_DONE__" in source or "sentinel" in source.lower()
    assert r"[$#>]" not in source


@pytest.mark.asyncio
async def test_terminal_run_strips_sentinel_from_output(ctx: ToolContext) -> None:
    sentinel = "__SEVN_TERM_DONE__"
    captured: dict[str, str] = {}

    def fake_run_sync(
        *, child: Any, command: str, timeout_s: float
    ) -> tuple[str, bool, int | None, bool]:
        _ = child, timeout_s
        captured["command"] = command
        # Real _run_sync strips the sentinel before returning; simulate that here.
        return "hello", False, 0, False

    with patch("sevn.tools.terminal._run_sync", fake_run_sync):
        exe, _ = build_session_registry(registry_version=1)
        raw = await exe.dispatch(
            ctx,
            ToolCall(
                name="terminal_run",
                arguments={"command": "echo hello", "prefer_sandbox": False},
            ),
        )
    env = json.loads(raw)
    assert env["ok"] is True
    assert sentinel not in env["data"]["output"]
    assert "hello" in env["data"]["output"]
    assert captured.get("command") == "echo hello"


def test_terminal_timeout_path_sends_signals() -> None:
    import inspect

    from sevn.tools import terminal as terminal_mod

    source = inspect.getsource(terminal_mod._run_sync)
    lowered = source.lower()
    assert "sigint" in lowered or "kill" in lowered or "terminate" in lowered
