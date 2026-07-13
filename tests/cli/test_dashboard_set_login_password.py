"""Tests for ``sevn dashboard set-login-password``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from sevn.cli.app import app
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.ui.dashboard.dashboard_password import (
    DASHBOARD_LOGIN_PASSWORD_CONFIG_REF,
    DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY,
)

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
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "secrets_backend": {
                    "chain": [
                        {
                            "type": "encrypted_file",
                            "path": ".sevn/secrets/store.enc",
                            "key_source": "master_key",
                        }
                    ]
                },
            },
        ),
        encoding="utf-8",
    )
    return (tmp_home, sevn_json)


def test_set_login_password_stamps_secret_ref_and_stores_logical_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)

    result = runner.invoke(
        app,
        ["dashboard", "set-login-password", "--set-value", "owner-password-12"],
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert doc["dashboard"]["enabled"] is True
    assert doc["dashboard"]["login_password"] == DASHBOARD_LOGIN_PASSWORD_CONFIG_REF

    from sevn.config.workspace_config import parse_workspace_config

    cfg = parse_workspace_config(doc)
    chain = secrets_chain_from_workspace(home / "workspace", cfg.secrets_backend)
    import asyncio

    stored = asyncio.run(chain.get(DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY))
    assert stored == "owner-password-12"
