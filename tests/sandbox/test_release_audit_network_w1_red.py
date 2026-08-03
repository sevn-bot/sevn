"""Batch A W1 RED — Docker sandbox network policy (#142; green after W5).

Contracts: dedicated internal network (not default bridge), workspace ``:ro`` bind with
narrow rw output volume. Regression: preserve ``--read-only`` and ``_docker_resource_args``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.sandbox_runtime import DockerSandboxRuntime, _docker_resource_args


async def _capture_docker_run_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> list[str]:
    captured: list[list[str]] = []

    async def fake_docker_run(
        argv: list[str],
        *,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout_s, stdin
        captured.append(list(argv))
        if "pull" in argv:
            return 0, "", ""
        return 0, "container-id-abc", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    rt = DockerSandboxRuntime(trace_sink=None, cfg=cfg, image="example/sandbox:test")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".llmignore").mkdir()
    await rt.spawn(
        run_id="audit-network-w1",
        workspace=ws,
        env={
            "SEVN_PROXY_URL": "http://127.0.0.1:8787",
            "SEVN_SESSION_TOKEN": "tok",
            "SEVN_WORKSPACE": "/workspace",
        },
    )
    run_calls = [argv for argv in captured if "run" in argv]
    assert run_calls, "expected docker run argv capture"
    return run_calls[-1]


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W5: docker spawn uses isolated network", strict=False)
async def test_docker_spawn_uses_dedicated_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_argv = await _capture_docker_run_argv(monkeypatch, tmp_path)
    joined = " ".join(run_argv)
    assert "--network" in run_argv
    assert "bridge" not in joined.split("--network")[-1].split()[0]


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W5: workspace bind is read-only", strict=False)
async def test_docker_spawn_workspace_mount_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_argv = await _capture_docker_run_argv(monkeypatch, tmp_path)
    ws = tmp_path / "workspace"
    mount_pairs = [arg for arg in run_argv if str(ws) in arg and ":" in arg]
    assert mount_pairs, "expected workspace volume mount"
    assert any(pair.endswith(":ro") for pair in mount_pairs), (
        f"workspace mount must be :ro, got {mount_pairs}"
    )


@pytest.mark.asyncio
async def test_docker_spawn_preserves_read_only_rootfs_regression(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """R2 — do not regress existing ``--read-only`` rootfs (verify only)."""
    run_argv = await _capture_docker_run_argv(monkeypatch, tmp_path)
    assert "--read-only" in run_argv


@pytest.mark.asyncio
async def test_docker_spawn_includes_resource_args_regression(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """R3 — ``_docker_resource_args()`` must reach ``docker run`` (verify only)."""
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    expected = _docker_resource_args(cfg)
    run_argv = await _capture_docker_run_argv(monkeypatch, tmp_path)
    for flag in expected:
        assert flag in run_argv


def test_docker_resource_args_non_empty_regression() -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    args = _docker_resource_args(cfg)
    assert "--cpus" in args
    assert "--memory" in args
    assert "--pids-limit" in args
