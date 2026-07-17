"""Tests for polish features (api, settings, hv, status)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.hv.resolver import cli_hv_resolver
from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError
from proton_cli.service.calendar.service import CalendarService


def test_proton_cli_command_tree_registered() -> None:
    runner = CliRunner()
    for name in ("status", "api", "settings", "calendar", "contacts", "drive", "mail", "pass"):
        result = runner.invoke(root_app, [name, "--help"])
        assert result.exit_code == 0, name


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
