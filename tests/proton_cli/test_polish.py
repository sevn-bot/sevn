"""Tests for polish features (api, settings, hv, status)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.hv.resolver import cli_hv_resolver
from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError
from proton_cli.service.calendar.service import CalendarService

runner = CliRunner()


def test_proton_cli_command_tree_registered() -> None:
    for name in ("status", "api", "settings", "calendar", "contacts", "drive", "mail", "pass"):
        result = runner.invoke(root_app, [name, "--help"])
        assert result.exit_code == 0, name


def test_status_runs_without_subcommand() -> None:
    result = runner.invoke(root_app, ["--output", "json", "status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout or result.output or "{}")
    assert "version" in payload
    assert "session_exists" in payload


def test_status_honours_legacy_session_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    legacy = tmp_path / "proton-cli" / "session.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}", encoding="utf-8")
    result = runner.invoke(root_app, ["--output", "json", "status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout or result.output or "{}")
    assert payload["session_exists"] is True
    assert payload["session_file"] == str(legacy)


def test_api_get_runs_mocked() -> None:
    with patch("proton_cli.cli.api_cmd._run") as run_app:
        app = MagicMock()
        app.api.do.return_value = MagicMock(body=b'{"Code":1000}')
        app.renderer.json_body = MagicMock()
        run_app.return_value = app
        result = runner.invoke(root_app, ["api", "GET", "/core/v4/users"])
    assert result.exit_code == 0
    assert "Missing command" not in (result.output or "")
    app.api.do.assert_called_once()
    app.renderer.json_body.assert_called_once_with(b'{"Code":1000}')


def test_settings_set_rejects_empty_value() -> None:
    result = runner.invoke(root_app, ["settings", "set", "page-size"])
    assert result.exit_code != 0
    out = (result.output or "").lower()
    assert "value" in out or "missing" in out


def test_hv_resolver_uses_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROTON_HV_TOKEN", "tok-abc")
    monkeypatch.setenv("PROTON_HV_TYPE", "captcha")
    token, kind = cli_hv_resolver(HumanVerificationError(token="x", web_url="https://example.com"))
    assert token == "tok-abc"
    assert kind == "captcha"


def test_hv_resolver_raises_without_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PROTON_HV_TOKEN", raising=False)
    with pytest.raises(ErrHVUnavailable):
        cli_hv_resolver(
            HumanVerificationError(token="x", methods=["captcha"], web_url="https://hv")
        )
    assert "https://hv" in capsys.readouterr().err


def test_api_response_json_body(capsys: pytest.CaptureFixture[str]) -> None:
    from proton_cli.render.output import Format, Renderer

    renderer = Renderer(Format.JSON)
    renderer.json_body(b'{"Code":1000,"Calendars":[]}')
    out = capsys.readouterr().out
    assert "Calendars" in out


def test_settings_keys_list() -> None:
    from proton_cli.cli.settings_cmd import MAIL_SETTINGS

    assert "page-size" in MAIL_SETTINGS
    assert MAIL_SETTINGS["sign"][2] is True


def test_calendar_list_mock() -> None:
    class FakeClient:
        def decode(self, req, out):
            out.clear()
            out.update({"Calendars": []})

    assert CalendarService(FakeClient()).calendars_list() == []
