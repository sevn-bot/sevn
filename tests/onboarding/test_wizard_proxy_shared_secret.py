"""Wizard proxy shared-secret generation and gateway env priming (Batch B W5)."""

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
            assert os.environ.get("SEVN_PROXY_SHARED_SECRET") == proxy_secret

    asyncio.run(_run())


def test_prime_proxy_shared_secret_env_skips_when_env_already_set(tmp_path: Path) -> None:
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
