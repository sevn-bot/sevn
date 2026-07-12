"""Gated Docker contract: ``HTTP_PROXY`` parity with ``build_sandbox_child_env`` (§10.4)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

from sevn.security.sandbox_runtime import build_sandbox_child_env, docker_daemon_reachable

pytestmark = pytest.mark.sandbox_docker

_BUSYBOX = "busybox:1.36"
_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "sandbox"


@pytest.fixture(autouse=True)
def _require_docker_gate() -> None:
    if os.environ.get("SEVN_CI_SANDBOX_DOCKER") != "1":
        pytest.skip("Set SEVN_CI_SANDBOX_DOCKER=1 (see make sandbox-integration)")
    if not docker_daemon_reachable():
        pytest.skip("Docker daemon not reachable")


def test_docker_run_echoes_proxy_env_from_build_sandbox_child_env() -> None:
    contract = json.loads((_ROOT / "child_env_contract.json").read_text(encoding="utf-8"))
    proxy = "http://127.0.0.1:19999"
    child = build_sandbox_child_env(
        proxy_url=proxy,
        session_token="test-token",
        workspace_mount_path="/workspace",
    )
    for key in contract["required_env_keys"]:
        assert key in child
    docker_bin = shutil.which("docker")
    assert docker_bin is not None
    cmd: list[str] = [docker_bin, "run", "--rm"]
    for key, val in child.items():
        cmd.extend(["-e", f"{key}={val}"])
    cmd.extend([_BUSYBOX, "sh", "-c", 'printf %s "$HTTP_PROXY"'])
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )  # nosec B603
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == proxy
