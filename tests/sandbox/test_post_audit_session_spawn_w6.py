"""W6 unit tests for sandbox spawn session-token resolution (#168, D12)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sevn.proxy.auth import SESSION_SCOPE_SANDBOX, mint_session_token, validate_session_token
from sevn.proxy.bootstrap_secret import ensure_proxy_shared_secret_file
from sevn.security.sandbox_errors import SandboxConfigurationError
from sevn.security.sandbox_runtime import _resolve_spawn_session_token

_SIGNING_KEY = "spawn-test-signing-key-at-least-32-chars"


def test_resolve_spawn_session_token_preserves_existing_env_token() -> None:
    assert (
        _resolve_spawn_session_token(
            run_id="run-keep",
            env={"SEVN_SESSION_TOKEN": "pre-minted-token"},
        )
        == "pre-minted-token"
    )


def test_resolve_spawn_session_token_mints_sandbox_scope_when_secret_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    token = _resolve_spawn_session_token(run_id="run-mint", env={})
    assert token.startswith("v1.")
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is True
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/llm/openai/chat/completions",
        )
        is False
    )


def test_resolve_spawn_session_token_raises_without_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed: no env and no generate-once file → SandboxConfigurationError (Thermos T2)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    with pytest.raises(SandboxConfigurationError, match="SEVN_PROXY_SHARED_SECRET"):
        _resolve_spawn_session_token(run_id="run-empty", env={})


def test_resolve_spawn_session_token_mints_from_generate_once_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose default: blank env + generate-once file under SEVN_HOME still mints (T2)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    ensure_proxy_shared_secret_file(tmp_path, secret=_SIGNING_KEY)
    token = _resolve_spawn_session_token(run_id="run-file", env={})
    assert token.startswith("v1.")
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is True


def test_resolve_spawn_session_token_mints_with_injected_signing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chain-only installs: injected signing_key mints without env/file (D41)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    chain_secret = "chain-only-spawn-signing-key-32chars!"
    token = _resolve_spawn_session_token(
        run_id="run-chain",
        env={},
        signing_key=chain_secret,
    )
    assert token.startswith("v1.")
    assert validate_session_token(token, signing_key=chain_secret, path="/web/fetch") is True
    assert "SEVN_PROXY_SHARED_SECRET" not in os.environ


def test_assemble_spawn_child_env_uses_injected_signing_key_without_leaking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injected chain secret mints a token and is not copied into child env."""
    from sevn.security.sandbox_runtime import _assemble_spawn_child_env

    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    chain_secret = "assemble-chain-only-signing-key-32ch!"
    env = _assemble_spawn_child_env(
        run_id="run-assemble-chain",
        env={"SEVN_PROXY_URL": "http://127.0.0.1:9"},
        workspace_mount_path="/w",
        signing_key=chain_secret,
    )
    assert set(env.keys()) == {"SEVN_PROXY_URL", "SEVN_SESSION_TOKEN", "SEVN_WORKSPACE"}
    assert "SEVN_PROXY_SHARED_SECRET" not in env
    assert validate_session_token(
        env["SEVN_SESSION_TOKEN"],
        signing_key=chain_secret,
        path="/web/fetch",
    )


def test_resolve_spawn_session_token_embeds_run_id_in_minted_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    run_id = "run-correlation-42"
    token = _resolve_spawn_session_token(run_id=run_id, env={})
    expected = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
    )
    assert token == expected
