"""Batch B W4 RED — digest pinning (#170; D14) and network telemetry (#171; D15).

Contracts: pull-then-pin with ``RepoDigests`` only; fail closed when digests missing;
``@sha256:`` config skips pull; ``sandbox.runtime`` emits ``network_enforcement`` without
``network_policy_path`` or egress rules files on Docker spawn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.sandbox_errors import SandboxConfigurationError
from sevn.security.sandbox_runtime import (
    DockerSandboxRuntime,
    _resolve_digest_pinned_image,
)

_DIGEST = "example/sandbox@sha256:abc123deadbeef0123456789abcdef0123456789abcdef0123456789ab"
_TAG = "fresh-registry.example/sandbox:v1"
_IMAGE_ID = "sha256:1111111111111111111111111111111111111111111111111111111111111111"


class _RecordingTraceSink(TraceSink):
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


async def _mock_docker_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    image: str,
    sink: _RecordingTraceSink | None = None,
    inspect_responses: dict[str, str] | None = None,
) -> tuple[list[list[str]], list[TraceEvent]]:
    captured: list[list[str]] = []
    inspect_map = dict(inspect_responses or {})

    async def fake_docker_run(
        argv: list[str],
        *,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout_s, stdin
        captured.append(list(argv))
        joined = " ".join(argv)
        if "network" in argv and argv[1:3] == ["network", "create"]:
            return 0, "", ""
        if "pull" in argv:
            return 0, "", ""
        if "image" in argv and "inspect" in argv:
            for key, val in inspect_map.items():
                if key in joined:
                    return (0, val, "") if val else (1, "", "not found")
            if "RepoDigests" in joined:
                return 1, "", "not found"
            if ".Id" in joined:
                return 0, _IMAGE_ID, ""
        if len(argv) > 1 and argv[1] == "run":
            return 0, "container-id-abc", ""
        return 0, "", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    rt = DockerSandboxRuntime(trace_sink=sink, cfg=cfg, image=image)
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".llmignore").mkdir()
    await rt.spawn(
        run_id="post-audit-pin-w4",
        workspace=ws,
        env={
            "SEVN_PROXY_URL": "http://127.0.0.1:8787",
            "SEVN_SESSION_TOKEN": "tok",
            "SEVN_WORKSPACE": "/workspace",
        },
    )
    return captured, sink.events if sink else []


@pytest.mark.xfail(reason="green after W7: pull-then-pin digest flow", strict=False)
@pytest.mark.asyncio
async def test_fresh_image_pulls_tag_then_runs_with_repo_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sink = _RecordingTraceSink()
    captured, events = await _mock_docker_spawn(
        monkeypatch,
        tmp_path,
        image=_TAG,
        sink=sink,
        inspect_responses={"RepoDigests": _DIGEST},
    )
    pull_argv = [argv for argv in captured if "pull" in argv]
    run_argv = [argv for argv in captured if len(argv) > 2 and argv[1] == "run"]
    assert pull_argv, "expected docker pull before run"
    assert _TAG in pull_argv[0]
    assert run_argv, "expected docker run"
    joined_run = " ".join(run_argv[-1])
    assert "@sha256:" in joined_run
    runtime = [e for e in events if e.kind == "sandbox.runtime"]
    assert runtime
    assert "@sha256:" in str(runtime[-1].attrs.get("image", ""))


@pytest.mark.xfail(reason="green after W7: fail closed on empty RepoDigests", strict=False)
@pytest.mark.asyncio
async def test_empty_repo_digests_raises_without_id_fallback_pull(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[list[str]] = []

    async def fake_docker_run(
        argv: list[str],
        *,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout_s, stdin
        captured.append(list(argv))
        joined = " ".join(argv)
        if "network" in argv and argv[1:3] == ["network", "create"]:
            return 0, "", ""
        if "pull" in argv:
            return 0, "", ""
        if "image" in argv and "inspect" in argv:
            if "RepoDigests" in joined:
                return 0, "", ""
            if ".Id" in joined:
                return 0, _IMAGE_ID, ""
        if len(argv) > 1 and argv[1] == "run":
            return 0, "container-id-abc", ""
        return 0, "", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    rt = DockerSandboxRuntime(trace_sink=None, cfg=cfg, image="local-built:latest")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".llmignore").mkdir()
    with pytest.raises(SandboxConfigurationError, match=r"RepoDigests|digest|registry"):
        await rt.spawn(
            run_id="post-audit-pin-fail",
            workspace=ws,
            env={
                "SEVN_PROXY_URL": "http://127.0.0.1:8787",
                "SEVN_SESSION_TOKEN": "tok",
                "SEVN_WORKSPACE": "/workspace",
            },
        )
    pull_targets = [argv[-1] for argv in captured if "pull" in argv]
    assert not any(t.startswith("sha256:") for t in pull_targets)


@pytest.mark.xfail(reason="green after W7: fail closed on empty RepoDigests", strict=False)
@pytest.mark.asyncio
async def test_resolve_digest_pinned_image_raises_when_no_repo_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_docker_run(
        argv: list[str],
        *,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout_s, stdin
        joined = " ".join(argv)
        if "RepoDigests" in joined:
            return 0, "", ""
        if ".Id" in joined:
            return 0, _IMAGE_ID, ""
        return 1, "", "not found"

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)
    with pytest.raises(SandboxConfigurationError, match=r"RepoDigests|digest|registry"):
        await _resolve_digest_pinned_image("local-built:latest")


@pytest.mark.xfail(reason="green after W7: @sha256 config skips pull", strict=False)
@pytest.mark.asyncio
async def test_digest_config_skips_pull(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pinned = "example/sandbox@sha256:abc123deadbeef0123456789abcdef0123456789abcdef0123456789abcdef"
    captured, _ = await _mock_docker_spawn(
        monkeypatch,
        tmp_path,
        image=pinned,
    )
    pull_argv = [argv for argv in captured if "pull" in argv]
    assert not pull_argv, f"expected no docker pull for pinned config, got {pull_argv}"
    run_argv = [argv for argv in captured if len(argv) > 2 and argv[1] == "run"]
    assert pinned in " ".join(run_argv[-1])


@pytest.mark.xfail(reason="green after W8: network_enforcement telemetry", strict=False)
@pytest.mark.asyncio
async def test_docker_spawn_emits_network_enforcement_without_policy_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sink = _RecordingTraceSink()
    inspect_map = {"RepoDigests": _DIGEST}
    captured: list[list[str]] = []

    async def fake_docker_run(
        argv: list[str],
        *,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout_s, stdin
        captured.append(list(argv))
        joined = " ".join(argv)
        if "network" in argv and argv[1:3] == ["network", "create"]:
            return 0, "", ""
        if "pull" in argv:
            return 0, "", ""
        if "image" in argv and "inspect" in joined:
            return 0, inspect_map.get("RepoDigests", _DIGEST), ""
        if len(argv) > 1 and argv[1] == "run":
            return 0, "container-id-abc", ""
        return 0, "", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    rt = DockerSandboxRuntime(trace_sink=sink, cfg=cfg, image=_TAG)
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".llmignore").mkdir()
    await rt.spawn(
        run_id="post-audit-telemetry-w4",
        workspace=ws,
        env={
            "SEVN_PROXY_URL": "http://127.0.0.1:8787",
            "SEVN_SESSION_TOKEN": "tok",
            "SEVN_WORKSPACE": "/workspace",
        },
    )
    runtime = [e for e in sink.events if e.kind == "sandbox.runtime"]
    assert runtime, "expected sandbox.runtime trace event"
    attrs: dict[str, Any] = dict(runtime[-1].attrs)
    assert attrs.get("network_enforcement") == "docker_internal"
    assert "network_policy_path" not in attrs
    rules = list((ws / ".sevn").glob("sandbox-egress.*.rules"))
    assert not rules, f"unexpected egress rules files: {rules}"
