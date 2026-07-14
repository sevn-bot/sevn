"""Tests for ``sevn.gateway.runtime.gateway_token`` resolution."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import GatewayConfig, WorkspaceConfig
from sevn.gateway.runtime.gateway_token import (
    GATEWAY_TOKEN_CONFIG_REF,
    GATEWAY_TOKEN_LOGICAL_KEY,
    generate_gateway_token,
    resolve_gateway_token_ref,
    validate_gateway_token_plaintext,
)
from sevn.security.secrets.factory import secrets_chain_from_workspace


def test_generate_gateway_token_hex_length() -> None:
    tok = generate_gateway_token()
    assert len(tok) == 64
    assert all(c in "0123456789abcdef" for c in tok)


def test_validate_gateway_token_plaintext_rejects_short() -> None:
    with pytest.raises(ValueError, match="at least"):
        validate_gateway_token_plaintext("short")


@pytest.mark.asyncio
async def test_resolve_literal_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    plain = "literal-gateway-token-at-least-32-chars-long"
    ws = WorkspaceConfig(schema_version=1, gateway=GatewayConfig(token=plain))
    got = await resolve_gateway_token_ref(ws, content_root=tmp_path)
    assert got == plain


@pytest.mark.asyncio
async def test_resolve_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "env-override-gateway-token-32chars")
    ws = WorkspaceConfig.minimal()
    got = await resolve_gateway_token_ref(ws, content_root=tmp_path)
    assert got == "env-override-gateway-token-32chars"


@pytest.mark.asyncio
async def test_resolve_env_override_beats_config_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "env-override-beats-config-ref-32chars")
    process = ProcessSettings()
    ws = WorkspaceConfig(schema_version=1, gateway=GatewayConfig(token=GATEWAY_TOKEN_CONFIG_REF))
    got = await resolve_gateway_token_ref(ws, content_root=tmp_path, process=process)
    assert got == "env-override-beats-config-ref-32chars"


@pytest.mark.asyncio
async def test_resolve_secret_ref_from_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "resolve-test-passphrase")
    plain = generate_gateway_token()
    ws = WorkspaceConfig.minimal()
    chain = secrets_chain_from_workspace(tmp_path, ws.secrets_backend)
    await chain.set(GATEWAY_TOKEN_LOGICAL_KEY, plain)
    ws_ref = WorkspaceConfig(
        schema_version=1, gateway=GatewayConfig(token=GATEWAY_TOKEN_CONFIG_REF)
    )
    got = await resolve_gateway_token_ref(ws_ref, content_root=tmp_path)
    assert got == plain


def test_cli_resolve_secret_ref_without_content_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.cli.gateway_client import resolve_gateway_token

    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    ws = WorkspaceConfig.minimal()
    assert resolve_gateway_token(workspace=ws, content_root=None) is None


def test_cli_resolve_literal_without_content_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.cli.gateway_client import resolve_gateway_token

    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    plain = "literal-gateway-token-at-least-32-chars-long"
    ws = WorkspaceConfig(schema_version=1, gateway=GatewayConfig(token=plain))
    assert resolve_gateway_token(workspace=ws, content_root=None) == plain


def test_asyncio_run_resolve_in_sync_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sevn.cli.gateway_client import resolve_gateway_token

    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "resolve-test-passphrase")
    plain = generate_gateway_token()
    ws = WorkspaceConfig.minimal()
    chain = secrets_chain_from_workspace(tmp_path, ws.secrets_backend)
    asyncio.run(chain.set(GATEWAY_TOKEN_LOGICAL_KEY, plain))
    ws_ref = WorkspaceConfig(
        schema_version=1, gateway=GatewayConfig(token=GATEWAY_TOKEN_CONFIG_REF)
    )
    got = resolve_gateway_token(workspace=ws_ref, content_root=tmp_path)
    assert got == plain
