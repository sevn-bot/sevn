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


def test_resolve_spawn_session_token_preserves_existing_env_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a resolved signing key the function trusts the env token as-is.

    PR #245 Codex finding 6 adds run/container binding checks when a secret
    resolves; this test pins the no-secret branch (no ``SEVN_PROXY_SHARED_SECRET``
    env, no ``SEVN_HOME`` generate-once file, no injected ``signing_key``).
    """
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
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


def test_resolve_spawn_session_token_rejects_existing_token_for_other_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing token minted for a different ``run_id`` is rejected (PR #245 Codex finding 6).

    Without the binding re-check, a sandbox could accept a session token left in
    the spawn env by a previous run and emit its own claims, letting an old
    credential extend into a fresh run's binding.
    """
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    other_run_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-other",
        container_id="ctr-other",
    )
    with pytest.raises(SandboxConfigurationError, match="different run/container"):
        _resolve_spawn_session_token(
            run_id="run-current",
            env={"SEVN_SESSION_TOKEN": other_run_token},
            container_id="ctr-current",
        )


def test_resolve_spawn_session_token_rejects_existing_token_for_other_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing token minted for a different ``container_id`` is rejected."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    other_container_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-shared",
        container_id="ctr-other",
    )
    with pytest.raises(SandboxConfigurationError, match="different run/container"):
        _resolve_spawn_session_token(
            run_id="run-shared",
            env={"SEVN_SESSION_TOKEN": other_container_token},
            container_id="ctr-current",
        )


def test_resolve_spawn_session_token_accepts_existing_token_with_matching_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing token whose ``run_id`` / ``container_id`` match the spawn is kept."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    matching_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-shared",
        container_id="ctr-shared",
    )
    assert (
        _resolve_spawn_session_token(
            run_id="run-shared",
            env={"SEVN_SESSION_TOKEN": matching_token},
            container_id="ctr-shared",
        )
        == matching_token
    )
