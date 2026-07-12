"""Process and terminal tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 8)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.process import list_session_jobs, reset_process_store_for_tests
from sevn.tools.registry import build_session_registry
from sevn.tools.terminal import reset_terminal_store_for_tests


@pytest.fixture(autouse=True)
def _clean_stores() -> None:
    reset_process_store_for_tests()
    reset_terminal_store_for_tests()
    yield
    reset_process_store_for_tests()
    reset_terminal_store_for_tests()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="proc-term-sess",
        workspace_path=workspace,
        workspace_id="proc-term-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def test_process_terminal_tools_registered() -> None:
    exe, _ = build_session_registry(registry_version=1)
    names = {d.name for d in exe.definitions()}
    assert {"process", "terminal_spawn", "terminal_run", "terminal_close"} <= names


@pytest.mark.asyncio
async def test_process_start_list_stop(ctx: ToolContext, workspace: Path) -> None:
    exe, _ = build_session_registry(registry_version=1)
    py = sys.executable
    start_raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="process",
            arguments={
                "action": "start",
                "argv": [
                    py,
                    "-u",
                    "-c",
                    "import time; print('bg-hello', flush=True); time.sleep(30)",
                ],
            },
        ),
    )
    start_env = json.loads(start_raw)
    assert start_env["ok"] is True
    job_id = start_env["data"]["job_id"]

    list_raw = await exe.dispatch(ctx, ToolCall(name="process", arguments={"action": "list"}))
    list_env = json.loads(list_raw)
    assert list_env["ok"] is True
    assert any(row["job_id"] == job_id for row in list_env["data"]["jobs"])
    assert list_session_jobs(ctx.session_id)[0]["status"] == "running"

    await asyncio.sleep(0.2)

    await exe.dispatch(
        ctx,
        ToolCall(name="process", arguments={"action": "output", "job_id": job_id, "lines": 20}),
    )

    stop_raw = await exe.dispatch(
        ctx,
        ToolCall(name="process", arguments={"action": "stop", "job_id": job_id}),
    )
    stop_env = json.loads(stop_raw)
    assert stop_env["ok"] is True
    assert stop_env["data"]["status"] == "stopped"

    out_raw = await exe.dispatch(
        ctx,
        ToolCall(name="process", arguments={"action": "output", "job_id": job_id}),
    )
    out_env = json.loads(out_raw)
    assert out_env["ok"] is True
    assert "bg-hello" in out_env["data"]["stdout"]


@pytest.mark.asyncio
async def test_process_unknown_action_is_rejected_not_silent(ctx: ToolContext) -> None:
    """An unsupported ``action`` must fail loudly, never report empty success.

    Regression for the live-session bug where ``action="run"`` fell through
    every branch, returned ``None``, and serialised as ``ok:true {}`` — the
    agent read that as "process is silenced" and abandoned a working fallback.
    """
    exe, _ = build_session_registry(registry_version=1)
    for bogus in ("run", "env"):
        raw = await exe.dispatch(
            ctx,
            ToolCall(name="process", arguments={"action": bogus, "command": "echo hi"}),
        )
        env = json.loads(raw)
        assert env["ok"] is False, f"action={bogus!r} must not report success"
        assert env.get("data") in (None, {}) or "jobs" not in env.get("data", {})


@pytest.mark.asyncio
async def test_terminal_run_auto_creates_default_without_terminal_id(ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    run_raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="terminal_run",
            arguments={"command": "echo terminal-auto", "prefer_sandbox": False},
        ),
    )
    run_env = json.loads(run_raw)
    assert run_env["ok"] is True
    assert run_env["data"]["terminal_id"]
    assert "terminal-auto" in run_env["data"]["output"]

    second_raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="terminal_run",
            arguments={"command": "echo again", "prefer_sandbox": False},
        ),
    )
    second_env = json.loads(second_raw)
    assert second_env["ok"] is True
    assert second_env["data"]["terminal_id"] == run_env["data"]["terminal_id"]


@pytest.mark.asyncio
async def test_terminal_spawn_run_close_roundtrip(ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    spawn_raw = await exe.dispatch(ctx, ToolCall(name="terminal_spawn", arguments={}))
    spawn_env = json.loads(spawn_raw)
    assert spawn_env["ok"] is True
    terminal_id = spawn_env["data"]["terminal_id"]

    run_raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="terminal_run",
            arguments={
                "terminal_id": terminal_id,
                "command": "echo terminal-ok",
                "prefer_sandbox": False,
            },
        ),
    )
    run_env = json.loads(run_raw)
    assert run_env["ok"] is True
    assert "terminal-ok" in run_env["data"]["output"]

    close_raw = await exe.dispatch(
        ctx,
        ToolCall(name="terminal_close", arguments={"terminal_id": terminal_id}),
    )
    close_env = json.loads(close_raw)
    assert close_env["ok"] is True
    assert close_env["data"]["closed"] is True


@pytest.mark.asyncio
async def test_terminal_run_prefers_sandbox_when_wired(ctx: ToolContext) -> None:
    class _FakeSandbox:
        async def sandbox_exec(
            self, *, language: str, code: str, ctx: ToolContext
        ) -> dict[str, object]:
            _ = (language, ctx)
            return {"exit_code": 0, "stdout": f"sandbox:{code}", "stderr": ""}

    sandbox_ctx = ToolContext(
        session_id=ctx.session_id,
        workspace_path=ctx.workspace_path,
        workspace_id=ctx.workspace_id,
        registry_version=ctx.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        sandbox_client=_FakeSandbox(),
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        sandbox_ctx,
        ToolCall(name="terminal_run", arguments={"command": "echo routed"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["routed_via"] == "sandbox_exec"
    assert "sandbox:echo routed" in str(env["data"]["stdout"])
