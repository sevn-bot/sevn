"""Tests for CLI waves W10-W19 command groups."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.cli.dashboard_testutil import patch_dashboard_gateway
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.cli.help.panels import panel_for


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_panels_w10_w19_commands() -> None:
    assert panel_for("channels") == "Chat"
    assert panel_for("tools") == "Skills & Tools"
    assert panel_for("usage") == "Health"
    assert panel_for("providers") == "Access"


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


def test_sevn_update_runs_force_sync(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "sevn.bot"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    (repo_root / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")

    from sevn.cli.repo_sync import SyncResult

    monkeypatch.setattr(
        "sevn.cli.commands.update_cmd.sync_source_tree",
        lambda **kwargs: SyncResult(
            updated=True,
            local_rev="abc1234",
            remote_rev="def5678",
            detail="Force-updated checkout to def5678 on pre-0.0.1.",
        ),
    )

    result = runner.invoke(
        app,
        ["update", "--repo", str(repo_root), "--no-restart"],
        env={"NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert "Force-updated checkout" in result.stdout


def test_sevn_guide_lists_new_topics(runner: CliRunner) -> None:
    result = runner.invoke(app, ["guide"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "channels" in result.stdout
    assert "usage" in result.stdout


def test_message_send_requires_session_and_text(runner: CliRunner) -> None:
    result = runner.invoke(app, ["message", "send", "--json"])
    assert result.exit_code == 2
