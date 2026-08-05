"""W6 unit tests for sandbox spawn session-token resolution (#168, D12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.proxy.auth import SESSION_SCOPE_SANDBOX, mint_session_token, validate_session_token
from sevn.security.sandbox_runtime import _resolve_spawn_session_token

if TYPE_CHECKING:
    import pytest

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


def test_resolve_spawn_session_token_returns_empty_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    assert _resolve_spawn_session_token(run_id="run-empty", env={}) == ""


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
