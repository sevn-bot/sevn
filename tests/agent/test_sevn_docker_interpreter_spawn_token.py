"""SevnDockerInterpreter must mint (not hardcode) sandbox session tokens."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sevn.agent.runtimes.sandbox import SevnDockerInterpreter
from sevn.proxy.bootstrap_secret import ensure_proxy_shared_secret_file


@pytest.mark.anyio
async def test_ensure_spawned_mints_without_placeholder_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed spawn rejects opaque placeholders; interpreter must leave token unset."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    secret = "repl-interpreter-signing-key-32chars!"
    ensure_proxy_shared_secret_file(tmp_path, secret=secret)

    interp = SevnDockerInterpreter(image="sevn-sandbox:test", workspace=tmp_path)
    seen: dict[str, object] = {}

    async def fake_spawn(*, run_id: str, workspace: Path, env: dict[str, str]) -> str:
        seen["run_id"] = run_id
        seen["workspace"] = workspace
        seen["env"] = dict(env)
        return "container-id"

    monkeypatch.setattr(interp._runtime, "spawn", fake_spawn)
    # Also exercise the real assemble path via signing_key on the runtime.
    assert interp._runtime._proxy_shared_secret == secret

    sid = await interp._ensure_spawned()
    assert sid == "container-id"
    env = seen["env"]
    assert isinstance(env, dict)
    assert env.get("SEVN_SESSION_TOKEN") in (None, "")
    assert "repl-session-token" not in str(env.values())


@pytest.mark.anyio
async def test_ensure_spawned_accepts_injected_signing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chain-only: constructor-injected secret reaches DockerSandboxRuntime."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    chain_secret = "chain-only-repl-signing-key-32chars!!"
    interp = SevnDockerInterpreter(
        image="sevn-sandbox:test",
        workspace=tmp_path,
        proxy_shared_secret=chain_secret,
    )
    assert interp._runtime._proxy_shared_secret == chain_secret
    interp._runtime.spawn = AsyncMock(return_value="cid")  # type: ignore[method-assign]
    assert await interp._ensure_spawned() == "cid"
