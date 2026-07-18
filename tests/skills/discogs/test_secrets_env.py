"""Secrets → subprocess env injection for Discogs skills (W1.3 / D5/D6/D8)."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from tests.skills.discogs.conftest import (
    DISCOGS_SECRET_ALIASES,
    import_discogs_module,
    load_discogs_common,
)

from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.chain import SecretsChain

pytestmark = pytest.mark.xfail(
    reason="green after W2: merge_discogs_proc_env + build_client",
    strict=False,
)


class _MemBackend:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


def _secrets_mod() -> Any:
    return import_discogs_module("sevn.skills.discogs_secrets")


def _user_token_cfg() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={
            "discogs": {
                "enabled": True,
                "auth_method": "user_token",
                "user_token": "${SECRET:discogs.user_token}",
            },
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def _oauth_cfg() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={
            "discogs": {
                "enabled": True,
                "auth_method": "oauth",
                "consumer_key": "${SECRET:discogs.consumer_key}",
                "consumer_secret": "${SECRET:discogs.consumer_secret}",
                "oauth_token": "${SECRET:discogs.oauth_token}",
                "oauth_token_secret": "${SECRET:discogs.oauth_token_secret}",
            },
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.mark.asyncio
async def test_merge_discogs_proc_env_user_token_keys(tmp_path) -> None:
    mod = _secrets_mod()
    store = {"discogs.user_token": "discogs-token-value"}
    chain = SecretsChain([_MemBackend(store)])
    cfg = _user_token_cfg()
    env: dict[str, str] = {}
    original = mod.secrets_chain_from_workspace
    mod.secrets_chain_from_workspace = lambda _r, _b: chain  # type: ignore[assignment]
    try:
        await mod.merge_discogs_proc_env(env, content_root=tmp_path, cfg=cfg)
    finally:
        mod.secrets_chain_from_workspace = original

    assert env["DISCOGS_AUTH_METHOD"] == "user_token"
    assert env["DISCOGS_USER_AGENT"] == "sevn-discogs/1.0"
    assert env["DISCOGS_CONFIRM_WRITES"] == "true"
    assert env["DISCOGS_USER_TOKEN"] == "discogs-token-value"


@pytest.mark.asyncio
async def test_merge_discogs_proc_env_oauth_keys(tmp_path) -> None:
    mod = _secrets_mod()
    store = {
        "discogs.consumer_key": "ck",
        "discogs.consumer_secret": "cs",
        "discogs.oauth_token": "ot",
        "discogs.oauth_token_secret": "ots",
    }
    chain = SecretsChain([_MemBackend(store)])
    cfg = _oauth_cfg()
    env: dict[str, str] = {}
    original = mod.secrets_chain_from_workspace
    mod.secrets_chain_from_workspace = lambda _r, _b: chain  # type: ignore[assignment]
    try:
        await mod.merge_discogs_proc_env(env, content_root=tmp_path, cfg=cfg)
    finally:
        mod.secrets_chain_from_workspace = original

    assert env["DISCOGS_AUTH_METHOD"] == "oauth"
    assert env["DISCOGS_CONSUMER_KEY"] == "ck"
    assert env["DISCOGS_CONSUMER_SECRET"] == "cs"
    assert env["DISCOGS_OAUTH_TOKEN"] == "ot"
    assert env["DISCOGS_OAUTH_TOKEN_SECRET"] == "ots"


@pytest.mark.asyncio
async def test_merge_discogs_proc_env_setdefault_semantics(tmp_path) -> None:
    mod = _secrets_mod()
    store = {"discogs.user_token": "from-secret"}
    chain = SecretsChain([_MemBackend(store)])
    cfg = _user_token_cfg()
    env = {"DISCOGS_USER_TOKEN": "from-operator"}
    original = mod.secrets_chain_from_workspace
    mod.secrets_chain_from_workspace = lambda _r, _b: chain  # type: ignore[assignment]
    try:
        await mod.merge_discogs_proc_env(env, content_root=tmp_path, cfg=cfg)
    finally:
        mod.secrets_chain_from_workspace = original

    assert env["DISCOGS_USER_TOKEN"] == "from-operator"


def test_build_client_missing_extra_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    common = load_discogs_common()
    monkeypatch.setitem(__import__("sys").modules, "discogs_client", None)
    result = common.build_client()
    payload = result if isinstance(result, dict) else json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "DISCOGS_EXTRA_MISSING"
    assert "uv sync --extra discogs" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_merge_discogs_proc_env_never_logs_secret_values(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mod = _secrets_mod()
    secret_value = "super-secret-discogs-token"
    store = {"discogs.user_token": secret_value}
    chain = SecretsChain([_MemBackend(store)])
    cfg = _user_token_cfg()
    env: dict[str, str] = {}
    original = mod.secrets_chain_from_workspace
    mod.secrets_chain_from_workspace = lambda _r, _b: chain  # type: ignore[assignment]
    caplog.set_level(logging.DEBUG)
    try:
        await mod.merge_discogs_proc_env(env, content_root=tmp_path, cfg=cfg)
    finally:
        mod.secrets_chain_from_workspace = original

    for alias in DISCOGS_SECRET_ALIASES:
        assert alias not in caplog.text or secret_value not in caplog.text
    assert secret_value not in caplog.text
