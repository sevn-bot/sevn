"""Batch D W14 RED — terminal timeout teardown & dead-session guard (#176; green after W15).

Contracts: SIGKILL timeout path returns ``session_destroyed: true`` and drops the
registry row (D20); ``_ensure_session_terminal`` must not return a dead pexpect child.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.terminal import (
    DEFAULT_SESSION_TERMINAL_ID,
    TerminalSession,
    _ensure_session_terminal,
    _session_map,
    reset_terminal_store_for_tests,
)


class _SandboxWiringStub:
    """Minimal ``sandbox_client`` for host-backed tool tests."""


@pytest.fixture(autouse=True)
def _clean_terminal_store() -> None:
    reset_terminal_store_for_tests()
    yield
    reset_terminal_store_for_tests()


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    root = tmp_path / "ws"
    root.mkdir()
    return ToolContext(
        session_id="post-audit-terminal-teardown",
        workspace_path=root,
        workspace_id="post-audit-terminal-teardown-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        sandbox_client=_SandboxWiringStub(),
    )


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W15: terminal timeout session_destroyed", strict=False)
async def test_terminal_run_timeout_sigkill_sets_session_destroyed(ctx: ToolContext) -> None:
    """W14.2: SIGKILL timeout path must expose ``session_destroyed: true`` in the envelope."""
    live_child = MagicMock()
    live_child.isalive.return_value = True

    with (
        patch("sevn.tools.terminal._spawn_sync", return_value=live_child),
        patch("sevn.tools.terminal._probe_spawn_health", return_value=(True, "")),
        patch(
            "sevn.tools.terminal._run_sync",
            return_value=("partial output", True, None),
        ),
    ):
        exe, _ = build_session_registry(registry_version=1)
        raw = await exe.dispatch(
            ctx,
            ToolCall(
                name="terminal_run",
                arguments={
                    "command": "sleep 999",
                    "prefer_sandbox": False,
                    "timeout_s": 1,
                },
            ),
        )

    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"].get("timed_out") is True
    assert env["data"].get("session_destroyed") is True


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W15: terminal timeout drops registry row", strict=False)
async def test_terminal_run_timeout_removes_session_from_registry(ctx: ToolContext) -> None:
    """W14.2: after SIGKILL timeout the terminal session must not remain in the registry."""
    live_child = MagicMock()
    live_child.isalive.return_value = True

    with (
        patch("sevn.tools.terminal._spawn_sync", return_value=live_child),
        patch("sevn.tools.terminal._probe_spawn_health", return_value=(True, "")),
        patch(
            "sevn.tools.terminal._run_sync",
            return_value=("partial output", True, None),
        ),
    ):
        exe, _ = build_session_registry(registry_version=1)
        first = await exe.dispatch(
            ctx,
            ToolCall(
                name="terminal_run",
                arguments={"command": "echo warm", "prefer_sandbox": False},
            ),
        )
        assert json.loads(first)["ok"] is True
        assert DEFAULT_SESSION_TERMINAL_ID in _session_map(ctx.session_id)

        await exe.dispatch(
            ctx,
            ToolCall(
                name="terminal_run",
                arguments={
                    "command": "sleep 999",
                    "prefer_sandbox": False,
                    "timeout_s": 1,
                },
            ),
        )

    assert DEFAULT_SESSION_TERMINAL_ID not in _session_map(ctx.session_id)


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W15: dead default session isalive guard", strict=False)
async def test_ensure_session_terminal_recreates_when_default_child_dead(
    ctx: ToolContext,
) -> None:
    """W14.3: a dead default session must be recreated, not handed back to callers."""
    dead_child = MagicMock()
    dead_child.isalive.return_value = False

    _session_map(ctx.session_id)[DEFAULT_SESSION_TERMINAL_ID] = TerminalSession(
        terminal_id=DEFAULT_SESSION_TERMINAL_ID,
        shell="/bin/sh",
        cwd=ctx.workspace_path,
        child=dead_child,
    )

    replacement = MagicMock()
    replacement.isalive.return_value = True
    spawn_calls: list[dict[str, Any]] = []

    def _fake_spawn(*, shell: str, cwd: Path) -> Any:
        spawn_calls.append({"shell": shell, "cwd": cwd})
        return replacement

    with (
        patch("sevn.tools.terminal._spawn_sync", side_effect=_fake_spawn),
        patch("sevn.tools.terminal._probe_spawn_health", return_value=(True, "")),
    ):
        resolved = await _ensure_session_terminal(ctx, terminal_id=None)

    assert not isinstance(resolved, str)
    terminal_id, session = resolved
    assert terminal_id == DEFAULT_SESSION_TERMINAL_ID
    assert session.child.isalive() is True
    assert spawn_calls, "expected dead session to trigger respawn"
