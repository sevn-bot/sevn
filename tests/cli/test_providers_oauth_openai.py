"""CLI tests for ``sevn providers oauth`` OpenAI/Codex flow (W1.7 — D6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from sevn.cli.app import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _install_workspace(home: Path) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": {"openai": {"auth_mode": "oauth"}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )


def test_oauth_login_openai_starts_pkce_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """``login --provider openai`` opens Codex authorize URL (not manual-paste stub)."""
    home = tmp_path / "home"
    _install_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    with patch("sevn.cli.commands.providers_cmd.build_authorization_flow") as build_flow:
        from sevn.security.oauth.authorize import AuthorizationFlow
        from sevn.security.oauth.pkce import PkcePair

        build_flow.return_value = AuthorizationFlow(
            pkce=PkcePair(verifier="v", challenge="c"),
            state="state-1",
            authorize_url="https://auth.openai.com/oauth/authorize?client_id=test",
        )
        result = runner.invoke(
            app,
            ["providers", "oauth", "login", "--provider", "openai"],
            env={"NO_COLOR": "1"},
        )
    assert result.exit_code == 0
    assert "auth.openai.com/oauth/authorize" in result.stdout
    assert "Store an OAuth token" not in result.stdout


def test_oauth_status_openai_shows_expiry_and_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """``status`` reports ``oauth.openai`` expiry and ``account_id`` for OpenAI."""
    home = tmp_path / "home"
    _install_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    health_body = {"providers": [{"id": "openai", "ok": True}]}
    oauth_blob = {
        "access": "jwt",
        "refresh": "rt",
        "expires": 1_800_000_000_000,
        "account_id": "acct-status-77",
    }

    with (
        patch("sevn.cli.commands.providers_cmd.dashboard_api_get", return_value=health_body),
        patch(
            "sevn.cli.commands.providers_cmd.secrets_list",
            return_value=[{"alias": "oauth.openai", "fingerprint_sha256_hex": "abc"}],
        ),
        patch(
            "sevn.cli.commands.providers_cmd.load_codex_oauth_credential_from_workspace",
            return_value=oauth_blob,
        ),
    ):
        result = runner.invoke(
            app,
            ["providers", "oauth", "status", "--json"],
            env={"NO_COLOR": "1"},
        )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    openai = payload["data"].get("openai") or payload["data"]
    assert "acct-status-77" in json.dumps(openai)
    assert "expires" in json.dumps(openai).lower()


def test_oauth_logout_openai_deletes_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """``logout --provider openai`` deletes ``oauth.openai`` from the secrets chain."""
    home = tmp_path / "home"
    _install_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    deleted: dict[str, Any] = {}

    def _delete(_bound: object, *, alias: str, **kwargs: object) -> None:
        deleted["alias"] = alias

    with (
        patch("sevn.cli.commands.providers_cmd.secrets_list") as list_fn,
        patch("sevn.cli.commands.providers_cmd.secrets_delete", side_effect=_delete),
    ):
        list_fn.return_value = [
            {"alias": "oauth.openai", "fingerprint_sha256_hex": "deadbeef" * 8},
        ]
        result = runner.invoke(
            app,
            ["providers", "oauth", "logout", "--provider", "openai", "--yes", "--json"],
            env={"NO_COLOR": "1"},
        )
    assert result.exit_code == 0
    assert deleted.get("alias") == "oauth.openai"
    payload = json.loads(result.stdout)
    assert payload["data"].get("deleted") is True
    assert payload["data"].get("provider") == "openai"


def test_oauth_login_stub_still_prints_handoff_for_non_openai(runner: CliRunner) -> None:
    """Non-openai providers keep generic handoff until provider-specific flows land."""
    result = runner.invoke(
        app,
        ["providers", "oauth", "login", "--provider", "anthropic"],
        env={"NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert "oauth.anthropic" in result.stdout
