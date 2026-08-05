"""Wizard proxy shared-secret generation and gateway priming (Batch B W5 / prod W3)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import (
    EncryptedFileBackendEntry,
    SecretsBackendSectionConfig,
    parse_workspace_config,
)
from sevn.gateway.http_server import _prime_proxy_shared_secret_env
from sevn.gateway.runtime.gateway_token import GATEWAY_TOKEN_MIN_CHARS
from sevn.onboarding.web_app import _wizard_proxy_shared_secret_plaintext
from sevn.onboarding.wizard_credentials import store_wizard_credentials
from sevn.proxy.bootstrap_secret import (
    ensure_proxy_shared_secret_file,
    read_proxy_shared_secret_file,
)


def test_wizard_proxy_shared_secret_auto_generate_min_length() -> None:
    secret = _wizard_proxy_shared_secret_plaintext({})
    assert len(secret) >= GATEWAY_TOKEN_MIN_CHARS


def test_wizard_proxy_shared_secret_honors_explicit_value() -> None:
    explicit = "a" * GATEWAY_TOKEN_MIN_CHARS
    assert (
        _wizard_proxy_shared_secret_plaintext({"wizard.proxy_shared_secret": explicit}) == explicit
    )


def test_wizard_proxy_shared_secret_rejects_short_value() -> None:
    with pytest.raises(ValueError, match="proxy shared secret must be at least"):
        _wizard_proxy_shared_secret_plaintext({"wizard.proxy_shared_secret": "short"})


def test_store_wizard_credentials_writes_proxy_shared_secret(tmp_path: Path) -> None:
    """Store still persists the secret; priming must not write it back to os.environ (D41)."""
    section = SecretsBackendSectionConfig(
        chain=[EncryptedFileBackendEntry(path=".sevn/secrets/store.enc")]
    )
    proxy_secret = "c" * 64
    asyncio.run(
        store_wizard_credentials(
            tmp_path,
            gateway_token="d" * 64,
            bot_token="123:abc",
            proxy_shared_secret=proxy_secret,
            secrets_passphrase="doctest-passphrase",
            section=section,
        )
    )
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "secrets_backend": {
                "chain": [{"type": "encrypted_file", "path": ".sevn/secrets/store.enc"}]
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )

    async def _run() -> None:
        with patch(
            "sevn.gateway.http_server.secrets_chain_from_workspace",
            return_value=AsyncMock(get_resilient=AsyncMock(return_value=proxy_secret)),
        ):
            os.environ.pop("SEVN_PROXY_SHARED_SECRET", None)
            await _prime_proxy_shared_secret_env(cfg, content_root=tmp_path)
            assert os.environ.get("SEVN_PROXY_SHARED_SECRET") is None

    asyncio.run(_run())


def test_store_wizard_credentials_overwrites_proxy_secret_file_on_explicit_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thermos T5: explicit wizard secret overwrites an existing generate-once file."""
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    stale = "s" * 64
    rotated = "r" * 64
    ensure_proxy_shared_secret_file(tmp_path, secret=stale)
    assert read_proxy_shared_secret_file(tmp_path) == stale

    section = SecretsBackendSectionConfig(
        chain=[EncryptedFileBackendEntry(path=".sevn/secrets/store.enc")]
    )
    asyncio.run(
        store_wizard_credentials(
            tmp_path,
            gateway_token="d" * 64,
            bot_token="123:abc",
            proxy_shared_secret=rotated,
            secrets_passphrase="doctest-passphrase",
            section=section,
        )
    )
    assert read_proxy_shared_secret_file(tmp_path) == rotated


def test_prime_proxy_shared_secret_env_is_noop(tmp_path: Path) -> None:
    """Deprecated prime helper must not mutate environ or touch the secrets chain (D41 / #228)."""
    cfg = parse_workspace_config({"schema_version": 1, "gateway": {"token": "x" * 32}})
    os.environ["SEVN_PROXY_SHARED_SECRET"] = "already-set"

    async def _run() -> None:
        with patch(
            "sevn.gateway.http_server.secrets_chain_from_workspace",
            return_value=AsyncMock(get_resilient=AsyncMock(return_value="from-chain")),
        ) as chain_factory:
            await _prime_proxy_shared_secret_env(cfg, content_root=tmp_path)
            chain_factory.assert_not_called()
            assert os.environ.get("SEVN_PROXY_SHARED_SECRET") == "already-set"

    try:
        asyncio.run(_run())
    finally:
        os.environ.pop("SEVN_PROXY_SHARED_SECRET", None)
