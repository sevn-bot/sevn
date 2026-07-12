"""Onboard daemon install gate (`specs/23-cli.md` §4.2, Wave 1)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.install_gate import (
    maybe_install_daemon_after_promote,
    parse_install_daemon_flag_from_env,
    should_install_daemon,
)


def test_should_install_daemon_flag_off() -> None:
    assert (
        should_install_daemon(
            home=Path("/tmp/h"),
            reuse=False,
            install_daemon_flag=False,
        )
        is False
    )


def test_should_install_daemon_fresh_install_when_flag_on() -> None:
    assert (
        should_install_daemon(
            home=Path("/tmp/h"),
            reuse=False,
            install_daemon_flag=True,
        )
        is True
    )


def test_should_install_daemon_reuse_skips_when_units_active() -> None:
    with patch(
        "sevn.cli.install_gate.both_units_installed_and_active",
        return_value=True,
    ):
        assert (
            should_install_daemon(
                home=Path("/tmp/h"),
                reuse=True,
                install_daemon_flag=True,
            )
            is False
        )


def test_should_install_daemon_reuse_installs_when_units_inactive() -> None:
    with patch(
        "sevn.cli.install_gate.both_units_installed_and_active",
        return_value=False,
    ):
        assert (
            should_install_daemon(
                home=Path("/tmp/h"),
                reuse=True,
                install_daemon_flag=True,
            )
            is True
        )


def test_parse_install_daemon_flag_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_ONBOARD_INSTALL_DAEMON", "1")
    assert parse_install_daemon_flag_from_env() is True
    monkeypatch.setenv("SEVN_ONBOARD_INSTALL_DAEMON", "0")
    assert parse_install_daemon_flag_from_env() is False


def test_maybe_install_daemon_after_promote_respects_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_ONBOARD_INSTALL_DAEMON", "0")
    assert maybe_install_daemon_after_promote() is None


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_onboard_config_default_installs_daemon(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sevn onboard --config`` installs units by default."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "queue_mode": "cancel",
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                },
            }
        ),
        encoding="utf-8",
    )
    with (
        patch("sevn.cli.install_gate.install_daemon_plan") as mock_install,
        patch(
            "sevn.onboarding.service_restart.restart_services_after_promote",
            return_value={"ok": True, "message": "started"},
        ),
    ):
        mock_install.return_value = "service units (launchd): g + p"
        result = runner.invoke(
            get_command(app),
            [
                "onboard",
                "--config",
                str(cfg),
                "--no-prompt-bot-name",
                "--bot-name",
                "GateBot",
            ],
        )
    assert result.exit_code == 0, result.stdout + result.stderr
    mock_install.assert_called_once()
    assert "service units" in result.stdout


def test_onboard_config_no_install_daemon_skips(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "queue_mode": "cancel",
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                },
            }
        ),
        encoding="utf-8",
    )
    with (
        patch("sevn.cli.install_gate.install_daemon_plan") as mock_install,
        patch(
            "sevn.onboarding.service_restart.restart_services_after_promote",
            return_value={"ok": True},
        ),
    ):
        result = runner.invoke(
            get_command(app),
            [
                "onboard",
                "--config",
                str(cfg),
                "--no-install-daemon",
                "--no-prompt-bot-name",
                "--bot-name",
                "GateBot",
            ],
        )
    assert result.exit_code == 0
    mock_install.assert_not_called()


def test_maybe_install_reuse_skips_when_units_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_ONBOARD_INSTALL_DAEMON", "1")
    monkeypatch.setenv("SEVN_ONBOARD_REUSE", "1")
    with (
        patch(
            "sevn.cli.install_gate.both_units_installed_and_active",
            return_value=True,
        ),
        patch("sevn.cli.install_gate.install_daemon_plan") as mock_install,
    ):
        assert maybe_install_daemon_after_promote() is None
    mock_install.assert_not_called()
