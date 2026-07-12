"""Tests for CLI waves W10-W19 command groups."""

from __future__ import annotations

import json

import pytest
from tests.cli.dashboard_testutil import patch_dashboard_gateway
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.cli.help.panels import panel_for


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_panels_w10_w19_commands() -> None:
    assert panel_for("channels") == "Observability"
    assert panel_for("tools") == "Agent"
    assert panel_for("usage") == "Observability"
    assert panel_for("providers") == "Ops"


def test_sevn_channels_status_json(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    patch_dashboard_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["channels", "status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "channels" in payload["data"]


def test_sevn_usage_show_json(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    patch_dashboard_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["usage", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_sevn_tools_health_json(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    patch_dashboard_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["tools", "health", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_sevn_providers_oauth_login(
    runner: CliRunner,
) -> None:
    result = runner.invoke(
        app,
        ["providers", "oauth", "login", "--provider", "anthropic"],
        env={"NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert "oauth.anthropic" in result.stdout


def test_sevn_update_shows_hint(runner: CliRunner) -> None:
    result = runner.invoke(app, ["update"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "uv tool upgrade" in result.stdout or "pip install" in result.stdout


def test_sevn_guide_lists_new_topics(runner: CliRunner) -> None:
    result = runner.invoke(app, ["guide"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "channels" in result.stdout
    assert "usage" in result.stdout


def test_message_send_requires_session_and_text(runner: CliRunner) -> None:
    result = runner.invoke(app, ["message", "send", "--json"])
    assert result.exit_code == 2
