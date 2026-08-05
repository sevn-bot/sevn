"""Prod-readiness Batch B W6 RED - spawn pull cache + startup pin (C4.2, C5.1-C5.4; D43).

Contracts (``about-sevn.bot/specs/08-sandbox.md``):
- N spawns with the same configured image produce exactly one ``docker pull`` (C5.4).
- Digest is resolved/validated once at gateway startup; a spawn against an already-local
  digest-pinned image performs no pull (C5.1, C5.2).
- An explicit image-update operation is the only path that refreshes the cached digest (C5.3).
- Startup refuses when the release digest is absent and cannot be pulled (C4.2).

Hard constraint (D43): pull-then-pin and the empty-``RepoDigests`` fail-closed path stay
unchanged — covered by ``tests/sandbox/test_post_audit_image_pin_w4_red.py`` (W6.8).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.sandbox_errors import SandboxConfigurationError
from sevn.security.sandbox_runtime import DockerSandboxRuntime

_TAG = "fresh-registry.example/sandbox:v1"
_DIGEST = (
    "fresh-registry.example/sandbox@sha256:"
    "abc123deadbeef0123456789abcdef0123456789abcdef0123456789abcdef"
)
_RELEASE_DIGEST = (
    "ghcr.io/sevn-bot/sevn/sandbox@sha256:"
    "feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface"
)


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / ".llmignore").mkdir(exist_ok=True)
    return ws


@pytest.fixture(autouse=True)
def _clear_sandbox_image_digest_cache() -> Iterator[None]:
    """Isolate process-lifetime cache from sibling suites sharing the same mock tag."""
    from sevn.security import sandbox_runtime as mod

    mod._SANDBOX_IMAGE_DIGEST_CACHE.clear()
    yield
    mod._SANDBOX_IMAGE_DIGEST_CACHE.clear()


async def _spawn_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    image: str,
    captured: list[list[str]],
    inspect_digest: str = _DIGEST,
    local_digests: set[str] | None = None,
    pull_fail_for: set[str] | None = None,
) -> None:
    present = set(local_digests or set())
    fail_pull = set(pull_fail_for or set())

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
            target = argv[-1]
            if target in fail_pull:
                return 1, "", f"pull failed for {target}"
            present.add(target)
            if "@sha256:" not in target:
                present.add(inspect_digest)
            return 0, "", ""
        if "image" in argv and "inspect" in argv:
            for key in present | {inspect_digest, image}:
                if key in joined or (len(argv) > 0 and argv[-1] == key):
                    if "RepoDigests" in joined:
                        return 0, inspect_digest, ""
                    return 0, inspect_digest if "@sha256:" in key else "ok", ""
            if "RepoDigests" in joined:
                return 1, "", "not found"
            return 1, "", "not found"
        if len(argv) > 1 and argv[1] == "run":
            return 0, "container-id-abc", ""
        return 0, "", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    rt = DockerSandboxRuntime(trace_sink=None, cfg=cfg, image=image)
    await rt.spawn(
        run_id="prod-ready-pull-cache",
        workspace=_workspace(tmp_path),
        env={
            "SEVN_PROXY_URL": "http://127.0.0.1:8787",
            "SEVN_SESSION_TOKEN": "tok",
            "SEVN_WORKSPACE": "/workspace",
        },
    )


def _pull_count(captured: list[list[str]]) -> int:
    return sum(1 for argv in captured if "pull" in argv)


def _import_image_ready_api() -> Any:
    """W8 deliverables — process-lifetime resolve/cache + explicit refresh (D43)."""
    from sevn.security import sandbox_runtime as mod

    ensure = getattr(mod, "ensure_sandbox_image_ready", None)
    refresh = getattr(mod, "refresh_sandbox_image", None)
    if ensure is None or refresh is None:
        msg = (
            "missing ensure_sandbox_image_ready / refresh_sandbox_image "
            "(green after W8: process-lifetime image cache)"
        )
        raise AssertionError(msg)
    return ensure, refresh


@pytest.mark.asyncio
async def test_w6_4_n_spawns_produce_exactly_one_pull(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """C5.4 — regression anchor: unconditional per-spawn pull must not return."""
    captured: list[list[str]] = []
    n = 3
    for i in range(n):
        await _spawn_once(
            monkeypatch,
            tmp_path / f"run-{i}",
            image=_TAG,
            captured=captured,
        )
    assert _pull_count(captured) == 1, (
        f"expected exactly one docker pull across {n} spawns, got {_pull_count(captured)}: "
        f"{[a for a in captured if 'pull' in a]}"
    )


@pytest.mark.asyncio
async def test_w6_5_startup_resolves_once_and_local_digest_skips_pull(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """C5.1 + C5.2 — startup validates once; already-local digest-pinned spawn does not pull."""
    ensure, _refresh = _import_image_ready_api()
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
            if "RepoDigests" in joined or _DIGEST in joined or _TAG in joined:
                return 0, _DIGEST, ""
            return 0, _DIGEST, ""
        if len(argv) > 1 and argv[1] == "run":
            return 0, "container-id-abc", ""
        return 0, "", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)

    pinned = await ensure(_TAG)
    assert "@sha256:" in pinned
    pulls_after_startup = _pull_count(captured)
    assert pulls_after_startup == 1

    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    rt = DockerSandboxRuntime(trace_sink=None, cfg=cfg, image=pinned)
    await rt.spawn(
        run_id="prod-ready-local-digest",
        workspace=_workspace(tmp_path),
        env={
            "SEVN_PROXY_URL": "http://127.0.0.1:8787",
            "SEVN_SESSION_TOKEN": "tok",
            "SEVN_WORKSPACE": "/workspace",
        },
    )
    assert _pull_count(captured) == pulls_after_startup, (
        "spawn of an already-present digest-pinned image must not docker pull"
    )


@pytest.mark.asyncio
async def test_w6_6_explicit_image_update_is_only_cache_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C5.3 — never refresh implicitly per spawn; only ``refresh_sandbox_image`` updates cache."""
    ensure, refresh = _import_image_ready_api()
    captured: list[list[str]] = []
    pull_targets: list[str] = []

    async def fake_docker_run(
        argv: list[str],
        *,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout_s, stdin
        captured.append(list(argv))
        if "pull" in argv:
            pull_targets.append(argv[-1])
            return 0, "", ""
        if "image" in argv and "inspect" in argv:
            return 0, _DIGEST, ""
        return 0, "", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)

    first = await ensure(_TAG)
    assert _pull_count(captured) == 1
    second = await ensure(_TAG)
    assert second == first
    assert _pull_count(captured) == 1, "second ensure must hit the process-lifetime cache"

    refreshed = await refresh(_TAG)
    assert "@sha256:" in refreshed
    assert _pull_count(captured) == 2, "explicit refresh is the only path that pulls again"
    assert pull_targets.count(_TAG) == 2


@pytest.mark.asyncio
async def test_w6_7_startup_refuses_when_release_digest_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C4.2 — failure surfaces at boot, not at first tier-B turn."""
    ensure, _refresh = _import_image_ready_api()

    async def fake_docker_run(
        argv: list[str],
        *,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout_s, stdin
        if "pull" in argv:
            return 1, "", "manifest unknown"
        if "image" in argv and "inspect" in argv:
            return 1, "", "No such image"
        return 0, "", ""

    monkeypatch.setattr("sevn.security.sandbox_runtime._docker_run", fake_docker_run)

    with pytest.raises(SandboxConfigurationError, match=r"pull|digest|absent|not present|image"):
        await ensure(_RELEASE_DIGEST)
