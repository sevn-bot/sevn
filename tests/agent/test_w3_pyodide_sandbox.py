"""Wave W3: Pyodide+Deno sandbox_exec + RuntimeToolBindings factory (`specs/08` §4.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from sevn.agent.runtimes.pyodide_deno import (
    PyodideDenoRunner,
    PyodideDenoUnavailable,
    PyodideExecResult,
    deno_binary_on_path,
    effective_sandbox_exec_driver,
    reconcile_sandbox_mode_document,
    resolve_sandbox_exec_driver,
    sandbox_exec_unavailable_note,
    should_wire_pyodide_sandbox,
)
from sevn.agent.runtimes.sandbox_client import (
    SevnSandboxExecutorClient,
    build_sandbox_executor_client,
)
from sevn.config.workspace_config import RlmWorkspaceConfig, WorkspaceConfig
from sevn.tools.base import ToolCall
from sevn.tools.codes import ToolResultCode
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.readiness import readiness_for_tool
from sevn.tools.registry import build_session_registry
from sevn.tools.runtime_bindings_factory import build_runtime_tool_bindings
from sevn.tools.runtime_dispatch import RuntimeToolBindings

if TYPE_CHECKING:
    from sevn.tools.context import ToolContext


@pytest.fixture(autouse=True)
def _clear_readiness_overrides() -> None:
    """Isolate module-level readiness overrides between tests."""
    from sevn.tools.readiness import _OVERRIDES

    _OVERRIDES.clear()
    yield
    _OVERRIDES.clear()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    return workspace_dir


@pytest.fixture
def exec_ctx(workspace: Path) -> ToolContext:
    from sevn.tools.context import ToolContext

    return ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=99,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


class _FakeRunner:
    """Minimal runner stand-in for unit tests."""

    available = True

    async def execute_python_async(self, code: str) -> PyodideExecResult:
        return PyodideExecResult(exit_code=0, stdout=f"out:{code}\n", stderr="")


@pytest.fixture
def pyodide_workspace() -> WorkspaceConfig:
    """Workspace explicitly requesting Pyodide sandbox."""
    return WorkspaceConfig(
        schema_version=1,
        rlm=RlmWorkspaceConfig(sandbox="pyodide_deno"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def test_should_wire_pyodide_when_rlm_sandbox_set(pyodide_workspace: WorkspaceConfig) -> None:
    with patch(
        "sevn.agent.runtimes.pyodide_deno.deno_binary_on_path", return_value="/usr/bin/deno"
    ):
        assert should_wire_pyodide_sandbox(pyodide_workspace) is True


def test_should_not_wire_pyodide_when_deno_missing(pyodide_workspace: WorkspaceConfig) -> None:
    with patch("sevn.agent.runtimes.pyodide_deno.deno_binary_on_path", return_value=None):
        assert should_wire_pyodide_sandbox(pyodide_workspace) is False


def test_resolve_driver_reads_sandbox_mode_extra() -> None:
    cfg = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "sandbox": {"mode": "pyodide_deno"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert resolve_sandbox_exec_driver(cfg) == "pyodide_deno"


def test_reconcile_downgrades_pyodide_without_deno() -> None:
    doc: dict[str, object] = {
        "schema_version": 1,
        "sandbox": {"mode": "pyodide_deno"},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    with (
        patch("sevn.agent.runtimes.pyodide_deno.deno_binary_on_path", return_value=None),
        patch("sevn.agent.runtimes.pyodide_deno.docker_daemon_reachable", return_value=True),
    ):
        warnings = reconcile_sandbox_mode_document(doc)
    assert doc["sandbox"] == {"mode": "docker"}
    assert len(warnings) >= 1
    assert "downgraded" in warnings[0]


def test_sandbox_exec_unavailable_note_when_pyodide_without_deno(
    pyodide_workspace: WorkspaceConfig,
) -> None:
    with patch("sevn.agent.runtimes.pyodide_deno.deno_binary_on_path", return_value=None):
        note = sandbox_exec_unavailable_note(pyodide_workspace)
    assert note is not None
    assert "Deno" in note


def test_effective_driver_downgrades_pyodide_to_docker(pyodide_workspace: WorkspaceConfig) -> None:
    with (
        patch("sevn.agent.runtimes.pyodide_deno.deno_binary_on_path", return_value=None),
        patch("sevn.agent.runtimes.pyodide_deno.docker_daemon_reachable", return_value=True),
    ):
        assert effective_sandbox_exec_driver(pyodide_workspace) == "docker"


def test_build_sandbox_client_none_without_deno(pyodide_workspace: WorkspaceConfig) -> None:
    with patch("sevn.agent.runtimes.sandbox_client.deno_binary_on_path", return_value=None):
        assert build_sandbox_executor_client(pyodide_workspace) is None


@pytest.mark.asyncio
async def test_sandbox_client_returns_stdout_with_fake_runner(
    pyodide_workspace: WorkspaceConfig,
    exec_ctx: ToolContext,
) -> None:
    client = SevnSandboxExecutorClient(pyodide_workspace, runner=_FakeRunner())
    payload = await client.sandbox_exec(language="python", code="print(1)", ctx=exec_ctx)
    assert payload["exit_code"] == 0
    assert "print(1)" in payload["stdout"]
    assert payload["driver"] == "pyodide_deno"


@pytest.mark.asyncio
async def test_sandbox_client_unavailable_raises_typed(
    pyodide_workspace: WorkspaceConfig,
    exec_ctx: ToolContext,
) -> None:
    with patch("sevn.agent.runtimes.pyodide_deno.deno_binary_on_path", return_value=None):
        client = SevnSandboxExecutorClient(
            pyodide_workspace,
            runner=PyodideDenoRunner(deno_bin="/nonexistent/deno"),
        )
    with pytest.raises(PyodideDenoUnavailable, match="Deno"):
        await client.sandbox_exec(language="python", code="1", ctx=exec_ctx)


@pytest.mark.asyncio
async def test_sandbox_exec_dispatches_via_bindings_factory(
    exec_ctx: ToolContext,
    pyodide_workspace: WorkspaceConfig,
) -> None:
    sandbox = SevnSandboxExecutorClient(pyodide_workspace, runner=_FakeRunner())
    bindings = RuntimeToolBindings(sandbox=sandbox)
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        runtime_bindings=bindings,
    )
    raw = await executor.dispatch(
        exec_ctx,
        ToolCall(name="sandbox_exec", arguments={"language": "python", "code": "2+2"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["stdout"]


def test_bindings_factory_wires_sandbox_mcp_integration_slots(
    pyodide_workspace: WorkspaceConfig,
) -> None:
    fake_sandbox = SevnSandboxExecutorClient(pyodide_workspace, runner=_FakeRunner())

    class _Integration:
        async def integration_call(self, **_kwargs: Any) -> dict[str, str]:
            return {"ok": "integration"}

    with (
        patch(
            "sevn.tools.runtime_bindings_factory.build_sandbox_executor_client",
            return_value=fake_sandbox,
        ),
        patch(
            "sevn.tools.runtime_bindings_factory.build_mcp_stdio_client",
            return_value=None,
        ),
        patch(
            "sevn.tools.runtime_bindings_factory.build_integration_proxy_client",
            return_value=None,
        ),
    ):
        bindings = build_runtime_tool_bindings(
            pyodide_workspace,
            mcp_servers={},
            integration=_Integration(),
        )
    assert bindings.integration is not None
    assert bindings.sandbox is fake_sandbox
    assert bindings.mcp is None


def test_readiness_ready_when_sandbox_wired(pyodide_workspace: WorkspaceConfig) -> None:
    fake_sandbox = SevnSandboxExecutorClient(pyodide_workspace, runner=_FakeRunner())
    with patch(
        "sevn.tools.runtime_bindings_factory.build_sandbox_executor_client",
        return_value=fake_sandbox,
    ):
        build_runtime_tool_bindings(pyodide_workspace, mcp_servers={})
    row = readiness_for_tool("sandbox_exec")
    assert row is not None
    assert row["status"] == "ready"


def test_readiness_pending_when_deno_missing(pyodide_workspace: WorkspaceConfig) -> None:
    with patch(
        "sevn.tools.runtime_bindings_factory.build_sandbox_executor_client",
        return_value=None,
    ):
        build_runtime_tool_bindings(pyodide_workspace, mcp_servers={})
    row = readiness_for_tool("sandbox_exec")
    assert row is not None
    assert row["status"] == "pending"
    assert "Deno" in row.get("note", "")


@pytest.mark.asyncio
async def test_registry_disabled_without_sandbox_binding(exec_ctx: ToolContext) -> None:
    executor, _ts = build_session_registry(registry_version=exec_ctx.registry_version)
    raw = await executor.dispatch(
        exec_ctx,
        ToolCall(name="sandbox_exec", arguments={"language": "python", "code": "1"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.DISABLED_TOOL


@pytest.mark.skipif(deno_binary_on_path() is None, reason="deno not installed")
@pytest.mark.asyncio
async def test_pyodide_runner_prints_stdout() -> None:
    runner = PyodideDenoRunner()
    if not runner.available:
        pytest.skip("pyodide runner script or deno missing")
    result = await runner.execute_python_async("print('w3-pyodide')")
    assert result.exit_code == 0
    assert "w3-pyodide" in result.stdout
