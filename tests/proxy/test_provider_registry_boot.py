"""Proxy boot tests for provider registry map (W1 contract 5; green after W3)."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.credentials import (
    ProviderCredentialEntry,
    ProviderCredentials,
    build_proxy_settings,
)
from sevn.proxy.settings import ProxySettings
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.chain import SecretsChain


@pytest.mark.anyio
async def test_build_proxy_settings_builds_provider_credentials_map(tmp_path: Path) -> None:
    """Contract 5: boot resolves ``providers.*`` keys into a name → credential map."""
    store = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    await chain.set("SEVN_SECRET_MINIMAX", "sk-mm-resolved")
    await chain.set("SEVN_SECRET_ANTHROPIC", "sk-ant-resolved")

    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}]
        },
        providers={
            "tier_default": {
                "triager": "minimax/MiniMax-M2",
                "B": "anthropic/claude-3-5-sonnet",
            },
            "minimax": {"api_key": "${SECRET:SEVN_SECRET_MINIMAX}"},
            "anthropic": {"api_key": "${SECRET:SEVN_SECRET_ANTHROPIC}"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()
    try:
        out = await build_proxy_settings(
            workspace_config=cfg,
            content_root=tmp_path,
            env_settings=ProxySettings(
                openai_api_key="sk-env-openai",
                anthropic_api_key="sk-env-anthropic",
            ),
        )
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)

    provider_map = getattr(out, "provider_credentials", None)
    assert isinstance(provider_map, ProviderCredentials)
    assert provider_map.by_name["minimax"].api_key == "sk-mm-resolved"
    assert provider_map.by_name["anthropic"].api_key == "sk-ant-resolved"


@pytest.mark.anyio
async def test_minimax_resolves_binding_first_no_route_bucket_fallback(
    tmp_path: Path,
) -> None:
    """MiniMax resolves ``providers.minimax.api_key`` from the credentials map only."""
    from sevn.proxy.credentials import resolve_request_credential

    store = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    await chain.set("SEVN_SECRET_MINIMAX", "sk-mm-wizard")

    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}]
        },
        providers={
            "tier_default": {"triager": "minimax/MiniMax-M3"},
            "minimax": {
                "transport": "chat_completions",
                "base_url": "https://api.minimax.io/v1",
                "api_key": "${SECRET:SEVN_SECRET_MINIMAX}",
            },
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()
    try:
        out = await build_proxy_settings(
            workspace_config=cfg,
            content_root=tmp_path,
            env_settings=ProxySettings(),  # no openai/anthropic env buckets
        )
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)

    provider_map = getattr(out, "provider_credentials", None)
    assert isinstance(provider_map, ProviderCredentials)
    assert provider_map.by_name["minimax"].api_key == "sk-mm-wizard"

    app_state = type("S", (), {"settings": out, "provider_credentials": provider_map})()
    for model_id in ("minimax/MiniMax-M3", "MiniMax-M3"):
        key, _base = resolve_request_credential(
            cfg, app_state, model_id, "/llm/openai/chat/completions"
        )
        assert key == "sk-mm-wizard", model_id


@pytest.mark.anyio
async def test_resolve_request_credential_precedence_binding_first(tmp_path: Path) -> None:
    """Contract 5 / D3: per-request resolver prefers provider binding over route bucket."""
    from sevn.proxy.credentials import resolve_request_credential

    cfg = WorkspaceConfig.minimal(
        providers={
            "minimax": {"api_key": "${SECRET:MM}", "base_url": "https://minimax.example/v1"},
        },
    )
    app_state = type(
        "State",
        (),
        {
            "settings": ProxySettings(
                anthropic_api_key="sk-route-bucket",
                openai_api_key="sk-openai-bucket",
                anthropic_base_url="https://api.anthropic.com",
            ),
            "provider_credentials": ProviderCredentials(
                by_name={
                    "minimax": ProviderCredentialEntry(
                        api_key="sk-binding",
                        anthropic_base_url="https://minimax.example/v1",
                    ),
                },
            ),
        },
    )()
    key, base_url = resolve_request_credential(
        cfg,
        app_state,
        "minimax/MiniMax-M2",
        "/llm/anthropic/messages",
    )
    assert key == "sk-binding"
    assert base_url == "https://minimax.example/v1"
