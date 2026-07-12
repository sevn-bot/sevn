"""Tests for ``sevn gateway set-gateway-token``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from sevn.cli.app import app
from sevn.gateway.gateway_token import (
    GATEWAY_TOKEN_CONFIG_REF,
    GATEWAY_TOKEN_LOGICAL_KEY,
    generate_gateway_token,
)
from sevn.security.secrets.factory import secrets_chain_from_workspace

runner = CliRunner()


def _install_workspace(tmp_home: Path) -> tuple[Path, Path]:
    ws = tmp_home / "workspace"
    ws.mkdir(parents=True)
    sevn_json = ws / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"host": "127.0.0.1", "port": 3001, "token": GATEWAY_TOKEN_CONFIG_REF},
                "secrets_backend": {
                    "chain": [
                        {
                            "type": "encrypted_file",
                            "path": ".sevn/secrets/store.enc",
                            "key_source": "master_key",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return (tmp_home, sevn_json)


def test_set_gateway_token_auto_generate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["gateway", "set-gateway-token"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "fingerprint=" in result.output
    assert "copy now" in result.output.lower()
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert doc["gateway"]["token"] == GATEWAY_TOKEN_CONFIG_REF
    from sevn.config.workspace_config import parse_workspace_config

    cfg = parse_workspace_config(doc)
    chain = secrets_chain_from_workspace(home / "workspace", cfg.secrets_backend)
    import asyncio

    stored = asyncio.run(chain.get(GATEWAY_TOKEN_LOGICAL_KEY))
    assert stored is not None
    assert len(stored) >= 32


def test_set_gateway_token_rejects_short_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["gateway", "set-gateway-token", "--set-value", "short"])
    assert result.exit_code == 4


def test_set_gateway_token_json_omits_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["gateway", "set-gateway-token", "--json"])
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["ok"] is True
    assert "fingerprint_sha256_hex" in body["data"]
    assert body["data"]["generated"] is True
    # H2: assert the *actually stored* token is absent from the envelope, not a fresh
    # random one (which is trivially absent by construction).
    from sevn.config.workspace_config import parse_workspace_config

    doc = json.loads((home / "workspace" / "sevn.json").read_text(encoding="utf-8"))
    cfg = parse_workspace_config(doc)
    chain = secrets_chain_from_workspace(home / "workspace", cfg.secrets_backend)
    import asyncio

    stored = asyncio.run(chain.get(GATEWAY_TOKEN_LOGICAL_KEY))
    assert stored is not None
    assert stored not in result.stdout


def test_set_gateway_token_set_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    custom = "a" * 64
    result = runner.invoke(app, ["gateway", "set-gateway-token", "--set-value", custom])
    assert result.exit_code == 0
    assert custom not in result.output or "--set-value" in result.output


def _install_legacy_workspace(tmp_home: Path) -> tuple[Path, Path]:
    """Install a workspace whose sevn.json has no ``gateway`` key at all (C1/L3)."""
    ws = tmp_home / "workspace"
    ws.mkdir(parents=True)
    sevn_json = ws / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "secrets_backend": {
                    "chain": [
                        {
                            "type": "encrypted_file",
                            "path": ".sevn/secrets/store.enc",
                            "key_source": "master_key",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return (tmp_home, sevn_json)


def test_set_gateway_token_bootstraps_legacy_tokenless_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # C1/L3: the command must succeed on a sevn.json that lacks gateway.token entirely,
    # because that is exactly the workspace an operator runs it on. A full-config parse
    # would reject the document before the command could stamp the ref.
    home, sevn_json = _install_legacy_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["gateway", "set-gateway-token"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert doc["gateway"]["token"] == GATEWAY_TOKEN_CONFIG_REF
    from sevn.config.workspace_config import parse_workspace_config

    cfg = parse_workspace_config(doc)
    chain = secrets_chain_from_workspace(home / "workspace", cfg.secrets_backend)
    import asyncio

    stored = asyncio.run(chain.get(GATEWAY_TOKEN_LOGICAL_KEY))
    assert stored is not None
    assert len(stored) >= 32


def test_set_gateway_token_stdin_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    token = generate_gateway_token()
    result = runner.invoke(app, ["gateway", "set-gateway-token", "--stdin"], input=f"{token}\n")
    assert result.exit_code == 0, result.output
    assert token not in result.output
    from sevn.config.workspace_config import parse_workspace_config

    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    cfg = parse_workspace_config(doc)
    chain = secrets_chain_from_workspace(home / "workspace", cfg.secrets_backend)
    import asyncio

    stored = asyncio.run(chain.get(GATEWAY_TOKEN_LOGICAL_KEY))
    assert stored == token
