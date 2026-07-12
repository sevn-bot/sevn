"""CLI activity log ``[cli]`` sink tests (W1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.cli_activity_log import (
    CLI_LOG_SOURCE,
    log_cli_activity,
    resolve_cli_log_path,
    shutdown_cli_activity_log,
)


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


@pytest.fixture
def bound_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    return home


@pytest.fixture(autouse=True)
def _reset_cli_log_sink() -> None:
    shutdown_cli_activity_log()
    yield
    shutdown_cli_activity_log()


def test_resolve_cli_log_path(bound_home: Path) -> None:
    path = resolve_cli_log_path(operator_home=bound_home)
    assert path.name == "cli.log"
    assert path.parent.name == "logs"


def test_log_cli_activity_redacts_secrets(
    bound_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_HOME", str(bound_home))
    path = resolve_cli_log_path(operator_home=bound_home)
    shutdown_cli_activity_log()
    from sevn.cli.cli_activity_log import install_cli_activity_log

    install_cli_activity_log(enabled=True)
    log_cli_activity("token=supersecret1234567890abcdef")
    text = path.read_text(encoding="utf-8")
    assert f"[{CLI_LOG_SOURCE}]" in text
    assert "supersecret" not in text
    assert "<redacted>" in text


def test_version_appends_cli_activity_line(runner: ClickCliRunner, bound_home: Path) -> None:
    result = runner.invoke(
        get_command(app),
        ["version"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    cli_log = resolve_cli_log_path(operator_home=bound_home)
    assert cli_log.is_file()
    body = cli_log.read_text(encoding="utf-8")
    assert f"[{CLI_LOG_SOURCE}]" in body
    assert "invoke sevn version" in body


def test_no_cli_log_flag_skips_sink(runner: ClickCliRunner, bound_home: Path) -> None:
    result = runner.invoke(
        get_command(app),
        ["--no-cli-log", "version"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    cli_log = resolve_cli_log_path(operator_home=bound_home)
    assert not cli_log.exists()
