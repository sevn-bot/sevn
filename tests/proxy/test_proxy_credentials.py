"""Tests for proxy credential boot (`specs/06-secrets.md` §2.4)."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.credentials import ProviderCredentials, build_proxy_settings
from sevn.proxy.settings import ProxySettings
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.chain import SecretsChain


@pytest.mark.anyio
async def test_provider_binding_resolves_in_credentials_map(tmp_path: Path) -> None:
    """``SEVN_SECRET_*`` refs resolve into ``provider_credentials`` at boot."""
    store = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    await chain.set("SEVN_SECRET_OPENAI", "PLACEHOLDER_OPENAI_KEY")

    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}]
        },
        providers={
            "tier_default": {"triager": "openai/gpt-4o"},
            "openai": {"api_key": "${SECRET:SEVN_SECRET_OPENAI}"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()
    try:
        out = await build_proxy_settings(
            workspace_config=cfg,
            content_root=tmp_path,
            env_settings=ProxySettings(),
        )
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)
    provider_map = getattr(out, "provider_credentials", None)
    assert isinstance(provider_map, ProviderCredentials)
    assert provider_map.by_name["openai"].api_key == "PLACEHOLDER_OPENAI_KEY"
    assert out.openai_api_key is None


@pytest.mark.anyio
async def test_openai_env_overrides_secrets_chain(tmp_path: Path) -> None:
    """``OPENAI_API_KEY`` env wins over empty route bucket."""
    cfg = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    out = await build_proxy_settings(
        workspace_config=cfg,
        content_root=tmp_path,
        env_settings=ProxySettings(openai_api_key="from-env"),
    )
    assert out.openai_api_key == "from-env"


@pytest.mark.anyio
async def test_minimax_catalog_sets_anthropic_base_url(tmp_path: Path) -> None:
    """Any ``minimax/`` catalog model enables MiniMax Anthropic upstream URL."""
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
            "minimax": {"base_url": "https://custom.minimax.example/anthropic/v1"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    out = await build_proxy_settings(
        workspace_config=cfg,
        content_root=tmp_path,
        env_settings=ProxySettings(),
    )
    assert out.anthropic_base_url == "https://custom.minimax.example/anthropic/v1"
    assert out.openai_base_url == "https://api.openai.com/v1"


@pytest.mark.anyio
async def test_minimax_catalog_default_anthropic_base_url(tmp_path: Path) -> None:
    """Missing ``providers.minimax.base_url`` uses ``DEFAULT_MINIMAX_ANTHROPIC_BASE_URL``."""
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={"tier_default": {"B": "minimax/MiniMax-M2.7"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    out = await build_proxy_settings(
        workspace_config=cfg,
        content_root=tmp_path,
        env_settings=ProxySettings(),
    )
    assert out.anthropic_base_url == "https://api.minimax.io/anthropic/v1"


@pytest.mark.anyio
async def test_minimax_provider_binding_resolves_anthropic_key(tmp_path: Path) -> None:
    """Per-provider MiniMax binding supplies the resolved key (not route buckets)."""
    store = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    await chain.set("SEVN_SECRET_MINIMAX", "mm-key")

    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}]
        },
        providers={
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
            "minimax": {"api_key": "${SECRET:SEVN_SECRET_MINIMAX}"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()
    try:
        out = await build_proxy_settings(
            workspace_config=cfg,
            content_root=tmp_path,
            env_settings=ProxySettings(),
        )
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)
    provider_map = getattr(out, "provider_credentials", None)
    assert isinstance(provider_map, ProviderCredentials)
    assert provider_map.by_name["minimax"].api_key == "mm-key"
    assert out.anthropic_api_key is None


@pytest.mark.anyio
async def test_legacy_openai_minimax_base_url_normalized(tmp_path: Path) -> None:
    """Legacy ``…/v1`` minimax base_url is upgraded to Anthropic-compatible default."""
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={
            "tier_default": {"triager": "minimax/text-01"},
            "minimax": {"base_url": "https://api.minimax.io/v1"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    out = await build_proxy_settings(
        workspace_config=cfg,
        content_root=tmp_path,
        env_settings=ProxySettings(),
    )
    assert out.anthropic_base_url == "https://api.minimax.io/anthropic/v1"


@pytest.mark.anyio
async def test_build_proxy_settings_survives_locked_encrypted_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory boot must not crash when the encrypted store needs a daemon passphrase."""
    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}]
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    monkeypatch.delenv("SEVN_SECRETS_MASTER_KEY", raising=False)
    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE", raising=False)
    out = await build_proxy_settings(
        workspace_config=cfg,
        content_root=tmp_path,
        env_settings=ProxySettings(),
    )
    assert out.openai_api_key is None


@pytest.mark.anyio
async def test_build_proxy_settings_reconciles_stale_unlock_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot must *reconcile* the unlock var against the Keychain, replacing a stale/wrong launchd
    value — not fill-only prime.

    Regression: a stale ``launchctl setenv SEVN_SECRETS_PASSPHRASE`` (persisted across logout)
    shadows the correct Keychain copy; a fill-only prime is a no-op when the var is already set, so
    the wrong value trips ``AEAD decrypt failed`` on every boot and launchd ``KeepAlive``
    crash-loops the proxy forever. Reconcile overrides the stale value so boot self-heals.
    """
    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "passphrase"}]
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    # Simulate the stale/wrong value left behind in the launchd session.
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "stale-launchd-value")

    called: dict[str, str] = {}

    async def _fake_reconcile(*, key_source: str, service: str | None = None) -> bool:
        called["key_source"] = key_source
        # Reconcile replaces the stale env value with the authoritative Keychain copy.
        os.environ["SEVN_SECRETS_PASSPHRASE"] = "keychain-value"
        return True

    monkeypatch.setattr(
        "sevn.proxy.credentials.reconcile_unlock_env_with_keychain", _fake_reconcile
    )

    out = await build_proxy_settings(
        workspace_config=cfg,
        content_root=tmp_path,
        env_settings=ProxySettings(),
    )
    assert called["key_source"] == "passphrase"
    assert os.environ["SEVN_SECRETS_PASSPHRASE"] == "keychain-value"
    assert isinstance(out, ProxySettings)


@pytest.mark.anyio
async def test_build_proxy_settings_sync_from_running_event_loop(tmp_path: Path) -> None:
    """Factory boot must work when uvicorn already has a running loop."""
    from sevn.proxy.credentials import build_proxy_settings_sync

    cfg = WorkspaceConfig(
        schema_version=1, providers={}, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    out = build_proxy_settings_sync(workspace_config=cfg, content_root=tmp_path)
    assert out.openai_base_url == "https://api.openai.com/v1"


@pytest.mark.anyio
async def test_brave_key_resolves_from_secrets_chain(tmp_path: Path) -> None:
    """``web.brave.api_key`` in the secrets store populates ``brave_api_key``."""
    from sevn.proxy.credentials import BRAVE_SECRET_ID

    store = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    await chain.set(BRAVE_SECRET_ID, "brave-from-store")

    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}]
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()
    try:
        out = await build_proxy_settings(
            workspace_config=cfg,
            content_root=tmp_path,
            env_settings=ProxySettings(),
        )
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)
    assert out.brave_api_key == "brave-from-store"


@pytest.mark.anyio
async def test_brave_env_overrides_secrets_chain(tmp_path: Path) -> None:
    """An explicit ``BRAVE_API_KEY`` env value wins over the stored secret."""
    from sevn.proxy.credentials import BRAVE_SECRET_ID

    store = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    backend = EncryptedFileBackend(store, master_key=mk)
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    await chain.set(BRAVE_SECRET_ID, "brave-from-store")

    cfg = WorkspaceConfig(
        schema_version=1,
        secrets_backend={
            "chain": [{"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}]
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    os.environ["SEVN_SECRETS_MASTER_KEY"] = mk.hex()
    try:
        out = await build_proxy_settings(
            workspace_config=cfg,
            content_root=tmp_path,
            env_settings=ProxySettings(brave_api_key="brave-from-env"),
        )
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)
    assert out.brave_api_key == "brave-from-env"


@pytest.mark.anyio
async def test_brave_key_absent_stays_none(tmp_path: Path) -> None:
    """No stored key and no env → ``brave_api_key`` stays ``None`` (web_search off)."""
    cfg = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    out = await build_proxy_settings(
        workspace_config=cfg,
        content_root=tmp_path,
        env_settings=ProxySettings(),
    )
    assert out.brave_api_key is None
