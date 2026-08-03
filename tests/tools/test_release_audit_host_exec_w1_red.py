"""Batch A W1 RED — host execution refusal (#140; green after W4).

Contracts: subprocess sandbox requires explicit dangerous opt-in; terminal/process tools
refuse host paths when sandbox is unwired.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sevn.config.workspace_config import parse_workspace_config
from sevn.security.sandbox_errors import SandboxConfigurationError
from sevn.security.sandbox_runtime import SandboxDriver, resolve_sandbox_driver
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.process import reset_process_store_for_tests
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
def ctx(tmp_path: Path) -> ToolContext:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return ToolContext(
        session_id="audit-host-exec",
        workspace_path=workspace,
        workspace_id="audit-host-exec-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        sandbox_client=None,
    )


@pytest.mark.xfail(
    reason="green after W4: subprocess fallback requires SEVN_DANGEROUS_HOST_SANDBOX=1",
    strict=False,
)
def test_resolve_sandbox_driver_rejects_subprocess_without_dangerous_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEVN_DANGEROUS_HOST_SANDBOX", raising=False)
    monkeypatch.setattr(
        "sevn.security.sandbox_runtime.docker_daemon_reachable",
        lambda timeout_s=5.0: False,
        raising=False,
    )
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "security": {"sandbox": {"allow_subprocess_fallback": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    with pytest.raises(SandboxConfigurationError, match="SEVN_DANGEROUS_HOST_SANDBOX"):
        resolve_sandbox_driver(cfg)


@pytest.mark.xfail(
    reason="green after W4: no docker→subprocess degrade without dangerous opt-in",
    strict=False,
)
def test_resolve_sandbox_driver_does_not_degrade_to_subprocess_when_docker_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEVN_DANGEROUS_HOST_SANDBOX", raising=False)
    monkeypatch.setattr(
        "sevn.security.sandbox_runtime.docker_daemon_reachable",
        lambda timeout_s=5.0: True,
        raising=False,
    )
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "security": {"sandbox": {"allow_subprocess_fallback": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert resolve_sandbox_driver(cfg) is SandboxDriver.docker


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W4: terminal_run refuses host without sandbox", strict=False)
async def test_terminal_run_rejects_host_path_without_sandbox(ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="terminal_run", arguments={"command": "echo audit-host-refusal"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    blob = json.dumps(env).lower()
    assert "sandbox" in blob or "host" in blob


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W4: process start refuses host without sandbox", strict=False
)
async def test_process_start_rejects_host_path_without_sandbox(ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="process",
            arguments={
                "action": "start",
                "argv": [sys.executable, "-c", "print('host-refusal')"],
            },
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    blob = json.dumps(env).lower()
    assert "sandbox" in blob or "host" in blob


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W4: terminal_spawn rejects caller-selected shell", strict=False
)
async def test_terminal_spawn_rejects_custom_shell(ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="terminal_spawn", arguments={"shell": "/bin/bash"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert "shell" in json.dumps(env).lower()
