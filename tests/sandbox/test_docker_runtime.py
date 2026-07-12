"""Docker spawn/exec + DSPy REPL handshake (``specs/08-sandbox.md`` Wave Q)."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

from sevn.agent.runtimes.sandbox import SevnDockerInterpreter
from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.sandbox_runtime import DockerSandboxRuntime, docker_daemon_reachable

pytestmark = pytest.mark.sandbox_docker

_DEFAULT_CANDIDATES: tuple[str, ...] = (
    "sevn-sandbox:local",
    "ghcr.io/sevn-bot/sevn/sandbox:dev",
    "python:3.12-slim-bookworm",
)


@pytest.fixture(autouse=True)
def _require_docker_gate() -> None:
    if os.environ.get("SEVN_CI_SANDBOX_DOCKER") != "1":
        pytest.skip("Set SEVN_CI_SANDBOX_DOCKER=1 (see make sandbox-integration)")
    if not docker_daemon_reachable():
        pytest.skip("Docker daemon not reachable")


def _image_exists(tag: str) -> bool:
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return False
    proc = subprocess.run(
        [docker_bin, "image", "inspect", tag],
        check=False,
        capture_output=True,
        timeout=30,
    )  # nosec B603
    return proc.returncode == 0


def _resolve_sandbox_image() -> str:
    override = os.environ.get("SEVN_SANDBOX_IMAGE", "").strip()
    if override and _image_exists(override):
        return override
    for tag in _DEFAULT_CANDIDATES:
        if _image_exists(tag):
            return tag
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        pytest.skip("docker CLI missing")
    for tag in _DEFAULT_CANDIDATES:
        pull = subprocess.run(
            [docker_bin, "pull", tag],
            check=False,
            capture_output=True,
            timeout=600,
        )  # nosec B603
        if pull.returncode == 0:
            return tag
    pytest.skip("no sandbox image available (try make docker-build-ci)")


@pytest.mark.asyncio
async def test_docker_spawn_exec_echo(tmp_path: Path) -> None:
    image = _resolve_sandbox_image()
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    rt = DockerSandboxRuntime(trace_sink=None, cfg=cfg, image=image)
    _ = (tmp_path / "visible.txt").write_text("ok", encoding="utf-8")
    (tmp_path / ".llmignore").mkdir()
    (tmp_path / ".llmignore" / "secret.bin").write_bytes(b"hidden")

    sb = await rt.spawn(
        run_id="wave-q-exec",
        workspace=tmp_path,
        env={
            "SEVN_PROXY_URL": "http://127.0.0.1:8787",
            "SEVN_SESSION_TOKEN": "tok",
            "SEVN_WORKSPACE": "/workspace",
        },
    )
    try:
        res = await rt.exec(sb, ["python", "-c", "print('sevn_docker_ok')"])
        assert isinstance(res, dict)
        assert res.get("exit_code") == 0
        assert "sevn_docker_ok" in str(res.get("stdout", ""))

        mask_probe = await rt.exec(
            sb,
            [
                "python",
                "-c",
                "import os; print(os.path.exists('/workspace/.llmignore/secret.bin'))",
            ],
        )
        assert str(mask_probe.get("stdout", "")).strip() == "False"
    finally:
        await rt.teardown(sb)


@pytest.mark.asyncio
async def test_sevn_docker_interpreter_repl_handshake(tmp_path: Path) -> None:
    image = _resolve_sandbox_image()
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    interp = SevnDockerInterpreter(
        image=image,
        cfg=cfg,
        workspace=tmp_path,
        child_env={
            "SEVN_PROXY_URL": "http://127.0.0.1:8787",
            "SEVN_SESSION_TOKEN": "repl-tok",
        },
    )
    try:
        out = interp.execute_python("print(41 + 1)")
        assert "42" in out
    finally:
        await interp.aclose()
