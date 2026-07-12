"""``sevn dashboard`` (`specs/23-cli.md` §2.4.2, Wave MC-13)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.json_util import CLI_JSON_SCHEMA_VERSION

# NO_COLOR only strips color; Rich still emits bold/dim styling that splits
# option strings like ``--open`` across escape sequences. Strip all SGR codes
# before substring assertions so they hold under any renderer.
_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_SGR_RE.sub("", text)


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _write_workspace(
    home: Path,
    *,
    dashboard_enabled: bool = True,
    login_password: str | None = None,
    tunnel_mode: str = "none",
) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    doc: dict[str, object] = {
        "schema_version": 1,
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "dashboard": {"enabled": dashboard_enabled},
        "infrastructure": {"tunnel": {"mode": tunnel_mode}},
    }
    if login_password is not None:
        dash = doc["dashboard"]
        assert isinstance(dash, dict)
        dash["login_password"] = login_password
    (ws / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")


def test_dashboard_help(runner: ClickCliRunner) -> None:
    result = runner.invoke(
        get_command(app),
        ["dashboard", "--help"],
        env={"NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert "--open" in _strip_ansi(result.stdout)


def test_dashboard_disabled_exit4(runner: ClickCliRunner, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_workspace(home, dashboard_enabled=False)
    result = runner.invoke(
        get_command(app),
        ["dashboard"],
        env={"SEVN_HOME": str(home)},
    )
    assert result.exit_code == 4
    assert "disabled" in result.stderr


def test_dashboard_missing_workspace_exit4(runner: ClickCliRunner, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    result = runner.invoke(
        get_command(app),
        ["dashboard"],
        env={"SEVN_HOME": str(home)},
    )
    assert result.exit_code == 4


def _patch_gateway_get_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.cli.gateway_client import gateway_get as real_get

    def _ok(path: str, **kwargs: object) -> httpx.Response:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ok"}, request=request),
        )
        return real_get(path, transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("sevn.cli.commands.dashboard_cmd.gateway_get", _ok)


def test_dashboard_prints_url_and_local_open_hint(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _write_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_gateway_get_ok(monkeypatch)

    result = runner.invoke(get_command(app), ["dashboard"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:3001/mission/" in result.stdout
    assert "loopback access" in result.stdout


def test_dashboard_tunnel_auth_hint(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _write_workspace(home, tunnel_mode="cloudflare", login_password="secret")
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_gateway_get_ok(monkeypatch)

    result = runner.invoke(get_command(app), ["dashboard"])
    assert result.exit_code == 0
    assert "owner password" in result.stdout
    assert "secret" not in result.stdout


def test_dashboard_json_envelope(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _write_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_gateway_get_ok(monkeypatch)

    result = runner.invoke(get_command(app), ["dashboard", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "sevn dashboard"
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION
    data = payload["data"]
    assert data["url"] == "http://127.0.0.1:3001/mission/"
    assert data["local_open"] is True
    assert data["auth_required"] is False
    assert data["tunnel_active"] is False


def test_dashboard_gateway_down_exit4(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.cli.gateway_client import gateway_get as real_get

    home = tmp_path / "home"
    _write_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    def _down(path: str, **kwargs: object) -> httpx.Response:
        def _raise(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        return real_get(path, transport=httpx.MockTransport(_raise), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("sevn.cli.commands.dashboard_cmd.gateway_get", _down)

    result = runner.invoke(get_command(app), ["dashboard"])
    assert result.exit_code == 4
    assert "unreachable" in result.stderr.lower() or "gateway" in result.stderr.lower()
