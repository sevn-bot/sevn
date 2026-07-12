from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.sandbox_errors import SandboxPolicyViolationError
from sevn.security.sandbox_runtime import SubprocessSandboxRuntime
from sevn.workspace.layout import WorkspaceLayout


@pytest.mark.asyncio
async def test_subprocess_spawn_exec_echo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    monkeypatch.chdir(tmp_path)
    lay = WorkspaceLayout.from_config(tmp_path / "sevn.json", cfg)
    rt = SubprocessSandboxRuntime(trace_sink=None, layout=lay, cfg=cfg)
    sb = await rt.spawn(
        run_id="r1",
        workspace=tmp_path,
        env={"SEVN_PROXY_URL": "http://127.0.0.1:9", "SEVN_SESSION_TOKEN": "tok"},
    )
    py = shutil.which("python3") or shutil.which("python")
    if py is None:
        pytest.skip("no python interpreter on PATH for subprocess smoke")
    res = await rt.exec(sb, [py, "-c", "print('sevn_ok')"])
    await rt.teardown(sb)
    assert isinstance(res, dict)
    assert res.get("exit_code") == 0
    assert "sevn_ok" in str(res.get("stdout", ""))


@pytest.mark.asyncio
async def test_subprocess_self_preservation_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    monkeypatch.chdir(tmp_path)
    lay = WorkspaceLayout.from_config(tmp_path / "sevn.json", cfg)
    rt = SubprocessSandboxRuntime(trace_sink=None, layout=lay, cfg=cfg)
    sb = await rt.spawn(
        run_id="r1",
        workspace=tmp_path,
        env={"SEVN_PROXY_URL": "http://127.0.0.1:9", "SEVN_SESSION_TOKEN": "tok"},
    )
    with pytest.raises(SandboxPolicyViolationError):
        await rt.exec(sb, ["pkill", "anything"])
