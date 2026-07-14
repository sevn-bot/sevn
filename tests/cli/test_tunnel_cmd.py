"""Tests for ``sevn tunnel`` (setup / status / start / stop)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.gateway.runtime.gateway_token import GATEWAY_TOKEN_CONFIG_REF
from sevn.infrastructure.tunnel_config import (
    CF_TOKEN_CONFIG_REF,
    CF_TOKEN_LOGICAL_KEY,
    NGROK_AUTHTOKEN_CONFIG_REF,
    NGROK_AUTHTOKEN_LOGICAL_KEY,
)
from sevn.security.secrets.factory import secrets_chain_from_workspace

runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_cloudflare_auto_start(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if request.node.get_closest_marker("no_cloudflare_api_stub"):
        return
    from sevn.infrastructure.cloudflare_tunnel_api import CloudflareTunnelProvisionResult

    monkeypatch.setattr(
        "sevn.cli.commands.tunnel_cmd._auto_provision_and_start_cloudflare",
        lambda: {
            "cloudflared_path": "/usr/bin/cloudflared",
            "cloudflared_detail": "cloudflared already on PATH",
            "started": True,
            "pid": 4242,
            "public_url": "https://bot.example.com/",
            "mission_control_url": "https://bot.example.com/",
        },
    )

    def _fake_api_setup(
        **_kwargs: object,
    ) -> tuple[CloudflareTunnelProvisionResult, dict[str, str], str]:
        result = CloudflareTunnelProvisionResult(
            tunnel_id="tunnel-uuid",
            tunnel_token="cf-secret-token",
            hostname="bot.example.com",
            public_url="https://bot.example.com/",
            zone_id="zone123",
            tunnel_name="sevn-bot-example-com",
        )
        fields = {
            "infrastructure.tunnel.cloudflare.account_id": "acct",
            "infrastructure.tunnel.hostname": "bot.example.com",
            "infrastructure.tunnel.tunnel_id": "tunnel-uuid",
        }
        return result, fields, "api-token"

    monkeypatch.setattr(
        "sevn.cli.commands.tunnel_cmd._resolve_cloudflare_api_setup",
        _fake_api_setup,
    )


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


def _stored_secret(home: Path, logical_key: str) -> str | None:
    from sevn.config.workspace_config import parse_workspace_config

    doc = json.loads((home / "workspace" / "sevn.json").read_text(encoding="utf-8"))
    cfg = parse_workspace_config(doc)
    chain = secrets_chain_from_workspace(home / "workspace", cfg.secrets_backend)
    return asyncio.run(chain.get(logical_key))


def test_setup_cloudflare_stores_token_and_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(
        app,
        [
            "tunnel",
            "setup",
            "--mode",
            "cloudflare",
            "--hostname",
            "bot.example.com",
            "--token-stdin",
        ],
        input="cf-secret-token\n",
    )
    assert result.exit_code == 0, result.output
    assert "cf-secret-token" not in result.output
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    tunnel = doc["infrastructure"]["tunnel"]
    assert tunnel["mode"] == "cloudflare"
    assert tunnel["hostname"] == "bot.example.com"
    assert tunnel["token"] == CF_TOKEN_CONFIG_REF
    assert _stored_secret(home, CF_TOKEN_LOGICAL_KEY) == "cf-secret-token"


def test_setup_ngrok_stores_authtoken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(
        app,
        [
            "tunnel",
            "setup",
            "--mode",
            "ngrok",
            "--local-port",
            "3001",
            "--token",
            "ng-token",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["data"]["mode"] == "ngrok"
    assert body["data"]["secret_stored"] is True
    assert "ng-token" not in result.stdout
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    tunnel = doc["infrastructure"]["tunnel"]
    assert tunnel["ngrok_authtoken"] == NGROK_AUTHTOKEN_CONFIG_REF
    assert _stored_secret(home, NGROK_AUTHTOKEN_LOGICAL_KEY) == "ng-token"


def test_setup_tailscale_needs_no_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "tailscale-funnel", "--local-port", "3001", "--json"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["data"]["mode"] == "tailscale_funnel"
    assert body["data"]["secret_stored"] is False
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert doc["infrastructure"]["tunnel"]["mode"] == "tailscale_funnel"


def test_setup_rejects_unknown_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["tunnel", "setup", "--mode", "bogus", "--json"])
    assert result.exit_code == 4
    body = json.loads(result.stdout)
    assert body["error_code"] == "INVALID_MODE"


def test_setup_config_path_clears_stale_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    # First configure with a token, then switch to a cloudflared config file.
    runner.invoke(app, ["tunnel", "setup", "--mode", "cloudflare", "--token", "cf-tok"])
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "cloudflare", "--config-path", "/etc/cloudflared/config.yml"],
    )
    assert result.exit_code == 0, result.output
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert "token" not in tunnel
    assert tunnel["config_path"] == "/etc/cloudflared/config.yml"


def test_setup_cloudflare_clears_stale_ngrok_authtoken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    runner.invoke(
        app,
        [
            "tunnel",
            "setup",
            "--mode",
            "ngrok",
            "--hostname",
            "old.example.com",
            "--token",
            "ng-token",
        ],
    )
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "cloudflare", "--token", "cf-token"],
    )
    assert result.exit_code == 0, result.output
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["mode"] == "cloudflare"
    assert "ngrok_authtoken" not in tunnel
    assert "hostname" not in tunnel
    assert tunnel["token"] == CF_TOKEN_CONFIG_REF
    assert _stored_secret(home, CF_TOKEN_LOGICAL_KEY) == "cf-token"


def test_setup_same_mode_preserves_hostname(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    runner.invoke(
        app,
        [
            "tunnel",
            "setup",
            "--mode",
            "cloudflare",
            "--hostname",
            "bot.example.com",
            "--token",
            "cf-token",
        ],
    )
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "cloudflare", "--local-port", "3005"],
    )
    assert result.exit_code == 0, result.output
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["hostname"] == "bot.example.com"
    assert tunnel["local_port"] == 3005


def test_setup_local_port_without_reentering_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "ngrok", "--token", "ng-token"],
    )
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "ngrok", "--local-port", "3005", "--json"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["data"]["secret_stored"] is False
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["local_port"] == 3005
    assert tunnel["ngrok_authtoken"] == NGROK_AUTHTOKEN_CONFIG_REF


def test_start_exits_nonzero_when_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "cloudflare", "--token", "cf-token"],
    )

    from sevn.infrastructure.tunnel_manager import TunnelStatus

    def _unhealthy_start(_cfg: dict[str, object], *, confirm: bool) -> TunnelStatus:
        return TunnelStatus(
            mode="cloudflare",
            pid=None,
            healthy=False,
            public_url=None,
            error="tunnel process exited with code 1",
        )

    monkeypatch.setattr(
        "sevn.infrastructure.tunnel_manager.TunnelManager.start",
        lambda self, cfg, *, confirm: _unhealthy_start(cfg, confirm=confirm),
    )
    result = runner.invoke(app, ["tunnel", "start"])
    assert result.exit_code == 4, result.output


def test_status_reports_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "ngrok", "--token", "ng-token"],
    )
    result = runner.invoke(app, ["tunnel", "status", "--json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["data"]["mode"] == "ngrok"
    assert body["data"]["healthy"] is False


def test_setup_cloudflare_interactive_shows_token_collection_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.cli import prompt_util

    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    monkeypatch.setattr(
        "sevn.cli.commands.tunnel_cmd._interactive_setup_enabled",
        lambda *, json_out: True,
    )

    def _fake_prompt(
        field_path: str,
        prompt: str,
        *,
        hide_input: bool = False,
        default: str | None = None,
        collect_only: bool = False,
    ) -> str:
        prompt_util.echo_field_collect_guide(field_path, collect_only=collect_only)
        if hide_input:
            return "cf-secret-token"
        return default or ""

    monkeypatch.setattr("sevn.cli.commands.tunnel_cmd.prompt_with_field_help", _fake_prompt)
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "cloudflare"],
    )
    assert result.exit_code == 0, result.output
    assert "Install as service" not in result.output
    assert "Cloudflared config YAML" not in result.output
    assert "Public hostname" not in result.output
    assert "cf-secret-token" not in result.output
    assert "tunnel started" in result.output
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["mode"] == "cloudflare"
    assert tunnel["token"] == CF_TOKEN_CONFIG_REF
    assert _stored_secret(home, CF_TOKEN_LOGICAL_KEY) == "cf-secret-token"


def test_setup_cloudflare_parses_install_as_service_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    install_cmd = "sudo cloudflared service install eyJhIjoiYzExZGY0YjJjIn0="
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "cloudflare", "--token-stdin"],
        input=f"{install_cmd}\n",
    )
    assert result.exit_code == 0, result.output
    assert _stored_secret(home, CF_TOKEN_LOGICAL_KEY) == "eyJhIjoiYzExZGY0YjJjIn0="
    assert "tunnel started" in result.output


def test_setup_cloudflare_succeeds_when_auto_start_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)

    def _fail_auto_start() -> dict[str, object]:
        msg = "install cloudflared: brew install cloudflared"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "sevn.cli.commands.tunnel_cmd._auto_provision_and_start_cloudflare",
        _fail_auto_start,
    )
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "cloudflare", "--token", "cf-token", "--json"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["data"]["secret_stored"] is True
    assert body["data"]["auto_start_attempted"] is True
    assert "auto_start_error" in body["data"]
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["token"] == CF_TOKEN_CONFIG_REF
    assert _stored_secret(home, CF_TOKEN_LOGICAL_KEY) == "cf-token"


def test_setup_ngrok_interactive_shows_authtoken_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.cli import prompt_util

    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    monkeypatch.setattr(
        "sevn.cli.commands.tunnel_cmd._interactive_setup_enabled",
        lambda *, json_out: True,
    )

    def _fake_prompt(
        field_path: str,
        prompt: str,
        *,
        hide_input: bool = False,
        default: str | None = None,
        collect_only: bool = False,
    ) -> str:
        prompt_util.echo_field_collect_guide(field_path, collect_only=collect_only)
        if hide_input:
            return "ng-token"
        return default or ""

    monkeypatch.setattr("sevn.cli.commands.tunnel_cmd.prompt_with_field_help", _fake_prompt)
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "ngrok"],
    )
    assert result.exit_code == 0, result.output
    assert "How to collect:" in result.output
    assert "dashboard.ngrok.com" in result.output
    assert "Reserved ngrok domain" not in result.output
    assert _stored_secret(home, NGROK_AUTHTOKEN_LOGICAL_KEY) == "ng-token"


def test_setup_tailscale_interactive_configures_without_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    monkeypatch.setattr(
        "sevn.cli.commands.tunnel_cmd._interactive_setup_enabled",
        lambda *, json_out: True,
    )
    result = runner.invoke(
        app,
        ["tunnel", "setup", "--mode", "tailscale-serve"],
    )
    assert result.exit_code == 0, result.output
    assert "How to collect:" not in result.output
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["mode"] == "tailscale_serve"


@pytest.mark.no_cloudflare_api_stub
def test_setup_cloudflare_non_tty_requires_api_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    result = runner.invoke(app, ["tunnel", "setup", "--mode", "cloudflare"])
    assert result.exit_code == 4, result.output
    assert "account id" in result.output.lower()


@pytest.mark.no_cloudflare_api_stub
def test_setup_cloudflare_json_requires_api_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["tunnel", "setup", "--mode", "cloudflare", "--json"])
    assert result.exit_code == 4, result.output
    body = json.loads(result.stdout)
    assert body["error_code"] == "SETUP_FAILED"
    assert "account id" in body["message"].lower()


def test_setup_cloudflare_quick_starts_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["tunnel", "setup", "--mode", "cloudflare-quick", "--json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["data"]["mode"] == "cloudflare_quick"
    assert body["data"]["secret_stored"] is False
    assert body["data"]["mission_control_url"] == "https://bot.example.com/"
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["mode"] == "cloudflare_quick"


def test_setup_cloudflare_quick_flag_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, sevn_json = _install_workspace(tmp_path / "home")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)
    result = runner.invoke(app, ["tunnel", "setup", "--mode", "cloudflare", "--quick"])
    assert result.exit_code == 0, result.output
    tunnel = json.loads(sevn_json.read_text(encoding="utf-8"))["infrastructure"]["tunnel"]
    assert tunnel["mode"] == "cloudflare_quick"
